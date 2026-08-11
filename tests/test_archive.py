from __future__ import annotations

import hashlib
import io
import os
import stat
import struct
import tarfile
import zipfile
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import pytest

import packrehearsal.artifacts.archive as archive_module
from packrehearsal.artifacts import detect_artifact_format, inspect_artifact, inspect_artifacts
from packrehearsal.config import ArchiveLimits
from packrehearsal.exceptions import ArchiveSafetyError


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


def _write_tar(
    path: Path,
    entries: list[tuple[str, bytes]],
    *,
    mode: Literal["w", "w:gz"] = "w",
) -> None:
    with tarfile.open(path, mode) as archive:
        for name, payload in entries:
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(payload))


def test_wheel_snapshot_is_deterministic_and_hashes_entries(tmp_path: Path) -> None:
    artifact = tmp_path / "demo-1.0-py3-none-any.whl"
    payload = b"Metadata-Version: 2.4\nName: demo\nVersion: 1.0\n"
    _write_zip(
        artifact,
        {
            "demo/__init__.py": b"__version__ = '1.0'\n",
            "demo-1.0.dist-info/METADATA": payload,
            "demo-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
        },
    )

    first = inspect_artifact(artifact, display_path="dist/demo.whl")
    second = inspect_artifact(artifact, display_path="dist/demo.whl")

    assert first == second
    assert first.to_dict() == second.to_dict()
    assert first.format == "wheel"
    assert first.path == "dist/demo.whl"
    assert first.sha256 == hashlib.sha256(artifact.read_bytes()).hexdigest()
    metadata_entry = next(entry for entry in first.entries if entry.path.endswith("METADATA"))
    assert metadata_entry.sha256 == hashlib.sha256(payload).hexdigest()
    assert first.metadata == {
        "container": "zip",
        "entry_count": 3,
        "hashed_entry_count": 3,
        "metadata_source": "demo-1.0.dist-info/METADATA",
        "package_name": "demo",
        "package_version": "1.0",
        "unpacked_size": sum(entry.size for entry in first.entries),
    }


@pytest.mark.parametrize(
    ("filename", "entries", "mode", "expected_format"),
    [
        ("plain.zip", [("README.md", b"ok")], "zip", "zip"),
        ("plain.tar", [("README.md", b"ok")], "tar", "tar"),
        ("package.tgz", [("package/package.json", b"{}")], "tgz", "tgz"),
        (
            "demo-1.0.tar.gz",
            [("demo-1.0/PKG-INFO", b"Name: demo\nVersion: 1.0\n")],
            "tgz",
            "sdist",
        ),
        (
            "demo-1.0.crate",
            [("demo-1.0/.cargo_vcs_info.json", b"{}")],
            "tgz",
            "crate",
        ),
    ],
)
def test_recognizes_supported_formats(
    tmp_path: Path,
    filename: str,
    entries: list[tuple[str, bytes]],
    mode: str,
    expected_format: str,
) -> None:
    artifact = tmp_path / filename
    if mode == "zip":
        _write_zip(artifact, dict(entries))
    elif mode == "tar":
        _write_tar(artifact, entries)
    else:
        _write_tar(artifact, entries, mode="w:gz")

    snapshot = inspect_artifact(artifact)

    assert snapshot.format == expected_format
    assert tuple(entry.path for entry in snapshot.entries) == tuple(
        sorted(name for name, _ in entries)
    )


@pytest.mark.parametrize(
    "member_name",
    ["../escape", "safe/../../escape", "/absolute", r"..\escape", r"C:\escape"],
)
def test_zip_rejects_traversal_and_absolute_paths(tmp_path: Path, member_name: str) -> None:
    artifact = tmp_path / "attack.zip"
    _write_zip(artifact, {member_name: b"owned"})

    with pytest.raises(ArchiveSafetyError, match=r"absolute|traverses"):
        inspect_artifact(artifact)


@pytest.mark.parametrize("member_name", ["../escape", "/absolute", r"safe\..\escape"])
def test_tar_rejects_traversal_and_absolute_paths(tmp_path: Path, member_name: str) -> None:
    artifact = tmp_path / "attack.tar"
    _write_tar(artifact, [(member_name, b"owned")])

    with pytest.raises(ArchiveSafetyError, match=r"absolute|traverses"):
        inspect_artifact(artifact)


def test_zip_rejects_symbolic_links(tmp_path: Path) -> None:
    artifact = tmp_path / "symlink.zip"
    member = zipfile.ZipInfo("package/link")
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr(member, "../../outside")

    with pytest.raises(ArchiveSafetyError, match="symbolic link"):
        inspect_artifact(artifact)


@pytest.mark.parametrize("link_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_tar_rejects_symbolic_and_hard_links(tmp_path: Path, link_type: bytes) -> None:
    artifact = tmp_path / "link.tar"
    with tarfile.open(artifact, "w") as archive:
        member = tarfile.TarInfo("package/link")
        member.type = link_type
        member.linkname = "../../outside"
        archive.addfile(member)

    with pytest.raises(ArchiveSafetyError, match=r"symbolic link|hard link"):
        inspect_artifact(artifact)


def test_rejects_duplicate_normalized_paths(tmp_path: Path) -> None:
    artifact = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("package/./data.txt", "first")
        archive.writestr("package/data.txt", "second")

    with pytest.raises(ArchiveSafetyError, match="duplicate normalized path"):
        inspect_artifact(artifact)


def test_enforces_entry_count_entry_size_and_total_size(tmp_path: Path) -> None:
    entries_artifact = tmp_path / "entries.zip"
    _write_zip(entries_artifact, {"a": b"1", "b": b"2"})
    with pytest.raises(ArchiveSafetyError, match="entries"):
        inspect_artifact(entries_artifact, limits=ArchiveLimits(max_entries=1))

    entry_artifact = tmp_path / "entry.zip"
    _write_zip(entry_artifact, {"large": b"12345"})
    with pytest.raises(ArchiveSafetyError, match="member size"):
        inspect_artifact(entry_artifact, limits=ArchiveLimits(max_entry_bytes=4))

    total_artifact = tmp_path / "total.tar"
    _write_tar(total_artifact, [("a", b"123"), ("b", b"456")])
    with pytest.raises(ArchiveSafetyError, match="unpacked size"):
        inspect_artifact(
            total_artifact,
            limits=ArchiveLimits(max_entry_bytes=4, max_total_unpacked_bytes=5),
        )


def test_rejects_zip_and_tar_compression_bombs(tmp_path: Path) -> None:
    zip_artifact = tmp_path / "bomb.zip"
    _write_zip(zip_artifact, {"zeros": b"\x00" * 20_000})
    limits = ArchiveLimits(
        max_entry_bytes=30_000,
        max_total_unpacked_bytes=30_000,
        max_compression_ratio=2,
    )
    with pytest.raises(ArchiveSafetyError, match="compression ratio"):
        inspect_artifact(zip_artifact, limits=limits)

    tar_artifact = tmp_path / "bomb.tgz"
    _write_tar(tar_artifact, [("zeros", b"\x00" * 20_000)], mode="w:gz")
    with pytest.raises(ArchiveSafetyError, match="compression ratio"):
        inspect_artifact(tar_artifact, limits=limits)


def test_large_entries_are_listed_without_decompression_hash(tmp_path: Path) -> None:
    artifact = tmp_path / "large.zip"
    _write_zip(artifact, {"large.bin": b"abcdef"})

    snapshot = inspect_artifact(artifact, limits=ArchiveLimits(hash_entry_bytes=5))

    assert snapshot.entries[0].path == "large.bin"
    assert snapshot.entries[0].sha256 is None
    assert snapshot.metadata["hashed_entry_count"] == 0


def test_rejects_symlink_artifact_and_unsupported_file(tmp_path: Path) -> None:
    target = tmp_path / "target.zip"
    _write_zip(target, {"ok": b"yes"})
    link = tmp_path / "link.zip"
    link.symlink_to(target)
    with pytest.raises(ArchiveSafetyError, match="must not be a symlink"):
        inspect_artifact(link)

    plain = tmp_path / "plain.bin"
    plain.write_bytes(os.urandom(32))
    with pytest.raises(ArchiveSafetyError, match="unsupported or malformed"):
        inspect_artifact(plain)


def test_artifact_file_preconditions_and_format_helper(tmp_path: Path) -> None:
    missing = tmp_path / "missing.zip"
    with pytest.raises(ArchiveSafetyError, match="cannot stat"):
        inspect_artifact(missing)

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ArchiveSafetyError, match="not a regular file"):
        inspect_artifact(directory)

    empty = tmp_path / "empty.zip"
    empty.touch()
    with pytest.raises(ArchiveSafetyError, match="empty"):
        inspect_artifact(empty)

    artifact = tmp_path / "bounded.zip"
    _write_zip(artifact, {"ok": b"yes"})
    with pytest.raises(ArchiveSafetyError, match="archive size"):
        inspect_artifact(
            artifact,
            limits=ArchiveLimits(max_archive_bytes=artifact.stat().st_size - 1),
        )
    assert detect_artifact_format(artifact) == "zip"


def test_inspect_artifacts_uses_relative_paths_and_stable_order(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "dist"
    artifacts_dir.mkdir()
    second = artifacts_dir / "b.zip"
    first = artifacts_dir / "a.zip"
    _write_zip(second, {"b": b"b"})
    _write_zip(first, {"a": b"a"})

    snapshots = inspect_artifacts([second, first], root=tmp_path)

    assert tuple(snapshot.path for snapshot in snapshots) == ("dist/a.zip", "dist/b.zip")

    outside = tmp_path.parent / "outside.zip"
    _write_zip(outside, {"x": b"x"})
    try:
        with pytest.raises(ArchiveSafetyError, match="outside"):
            inspect_artifacts([outside], root=tmp_path)
    finally:
        outside.unlink()


def test_path_swap_after_capture_cannot_mix_hash_and_entries(tmp_path: Path) -> None:
    live = tmp_path / "live.zip"
    replacement = tmp_path / "replacement.zip"
    original_path = tmp_path / "captured-original.zip"
    _write_zip(live, {"from-a.txt": b"A"})
    _write_zip(replacement, {"from-b.txt": b"B"})
    expected_hash = hashlib.sha256(live.read_bytes()).hexdigest()
    original_detect = archive_module._detect_container

    def swap_original_after_capture(snapshot_path: Path) -> str:
        live.rename(original_path)
        replacement.rename(live)
        return original_detect(snapshot_path)

    with patch.object(archive_module, "_detect_container", swap_original_after_capture):
        snapshot = inspect_artifact(live)

    assert snapshot.sha256 == expected_hash
    assert tuple(entry.path for entry in snapshot.entries) == ("from-a.txt",)
    assert tuple(entry.path for entry in inspect_artifact(live).entries) == ("from-b.txt",)


def test_zip64_entry_count_is_rejected_before_zipfile_construction(tmp_path: Path) -> None:
    artifact = tmp_path / "declared-120000.zip"
    entry_count = 120_000
    zip64_eocd = struct.pack(
        "<4sQ2H2L4Q",
        b"PK\x06\x06",
        44,
        45,
        45,
        0,
        0,
        entry_count,
        entry_count,
        0,
        0,
    )
    zip64_locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, 0, 1)
    eocd = struct.pack(
        "<4s4H2LH",
        b"PK\x05\x06",
        0,
        0,
        0xFFFF,
        0xFFFF,
        0xFFFFFFFF,
        0xFFFFFFFF,
        0,
    )
    artifact.write_bytes(zip64_eocd + zip64_locator + eocd)

    with (
        patch.object(
            archive_module.zipfile,
            "ZipFile",
            side_effect=AssertionError("ZipFile must not be constructed"),
        ),
        pytest.raises(ArchiveSafetyError, match="120000 entries; limit is 20000"),
    ):
        inspect_artifact(artifact)
