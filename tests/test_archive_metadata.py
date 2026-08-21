from __future__ import annotations

import io
import random
import tarfile
import zipfile
from pathlib import Path

import pytest

from packrehearsal.artifacts import inspect_artifact


def _write_tar(path: Path, entries: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in entries.items():
            member = tarfile.TarInfo(name)
            member.mode = 0o644
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


@pytest.mark.parametrize(
    ("filename", "entries", "expected"),
    [
        (
            "demo-1.2.3.tgz",
            {
                "package/package.json": (
                    b'{"name":"@scope/demo","version":"1.2.3","private_data":"discard"}'
                )
            },
            {
                "metadata_source": "package/package.json",
                "package_name": "@scope/demo",
                "package_version": "1.2.3",
            },
        ),
        (
            "demo-1.2.3.tar.gz",
            {
                "demo-1.2.3/PKG-INFO": (
                    b"Metadata-Version: 2.4\nName: demo\nVersion: 1.2.3\nPrivate-Header: discard\n"
                )
            },
            {
                "metadata_source": "demo-1.2.3/PKG-INFO",
                "package_name": "demo",
                "package_version": "1.2.3",
            },
        ),
        (
            "demo-1.2.3.crate",
            {
                "demo-1.2.3/Cargo.toml": (
                    b'[package]\nname = "demo"\nversion = "1.2.3"\ndescription = "discard"\n'
                )
            },
            {
                "metadata_source": "demo-1.2.3/Cargo.toml",
                "package_name": "demo",
                "package_version": "1.2.3",
            },
        ),
    ],
)
def test_tar_package_metadata_is_minimal(
    tmp_path: Path,
    filename: str,
    entries: dict[str, bytes],
    expected: dict[str, str],
) -> None:
    artifact = tmp_path / filename
    _write_tar(artifact, entries)

    snapshot = inspect_artifact(artifact)

    assert {key: snapshot.metadata[key] for key in expected} == expected
    assert "private_data" not in snapshot.metadata
    assert "Private-Header" not in snapshot.metadata
    assert "description" not in snapshot.metadata


def test_wheel_metadata_is_minimal(tmp_path: Path) -> None:
    artifact = tmp_path / "demo-1.2.3-py3-none-any.whl"
    _write_zip(
        artifact,
        {
            "demo-1.2.3.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
            "demo-1.2.3.dist-info/METADATA": (
                b"Metadata-Version: 2.4\nName: demo\nVersion: 1.2.3\n"
                b"Requires-Python: >=3.11\nLicense-Expression: MIT\n"
                b"Requires-Dist: beta>=2\nRequires-Dist: alpha>=1\n"
                b"Provides-Extra: fast\nPrivate-Header: discard\n"
            ),
        },
    )

    snapshot = inspect_artifact(artifact)

    assert snapshot.metadata["package_name"] == "demo"
    assert snapshot.metadata["package_version"] == "1.2.3"
    assert snapshot.metadata["metadata_source"] == "demo-1.2.3.dist-info/METADATA"
    assert snapshot.metadata["requires_python"] == ">=3.11"
    assert snapshot.metadata["license_expression"] == "MIT"
    assert snapshot.metadata["requires_dist"] == ("alpha>=1", "beta>=2")
    assert snapshot.metadata["provides_extra"] == ("fast",)
    assert "Private-Header" not in snapshot.metadata


@pytest.mark.parametrize(
    ("filename", "entry_name", "payload"),
    [
        ("broken.tgz", "package/package.json", b"{not-json"),
        ("broken.whl", "broken.dist-info/METADATA", b"\xff\xfe"),
        ("broken.tar.gz", "broken/PKG-INFO", b"Name: demo\nName: duplicate\nVersion: 1\n"),
        ("broken.crate", "broken/Cargo.toml", b"[package\nname = 'broken'"),
    ],
)
def test_malformed_metadata_is_ignored(
    tmp_path: Path,
    filename: str,
    entry_name: str,
    payload: bytes,
) -> None:
    artifact = tmp_path / filename
    if filename.endswith(".whl"):
        _write_zip(artifact, {entry_name: payload})
    else:
        _write_tar(artifact, {entry_name: payload})

    snapshot = inspect_artifact(artifact)

    assert "package_name" not in snapshot.metadata
    assert "package_version" not in snapshot.metadata
    assert "metadata_source" not in snapshot.metadata


def test_metadata_larger_than_hard_cap_is_not_retained(tmp_path: Path) -> None:
    artifact = tmp_path / "oversized.tgz"
    payload = random.Random(0).randbytes(256 * 1024 + 1)
    _write_tar(artifact, {"package/package.json": payload})

    snapshot = inspect_artifact(artifact)

    assert next(entry for entry in snapshot.entries if entry.path.endswith("package.json")).sha256
    assert "package_name" not in snapshot.metadata
    assert "package_version" not in snapshot.metadata
    assert "metadata_source" not in snapshot.metadata


def test_ambiguous_metadata_sources_are_ignored(tmp_path: Path) -> None:
    artifact = tmp_path / "ambiguous.whl"
    payload = b"Metadata-Version: 2.4\nName: demo\nVersion: 1\n"
    _write_zip(
        artifact,
        {
            "first.dist-info/METADATA": payload,
            "second.dist-info/METADATA": payload,
        },
    )

    snapshot = inspect_artifact(artifact)

    assert "package_name" not in snapshot.metadata
