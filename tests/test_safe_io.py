from __future__ import annotations

import os
from pathlib import Path

import pytest

import packrehearsal.safe_io as safe_io
from packrehearsal.discovery import discover_packages
from packrehearsal.models import Ecosystem, Package
from packrehearsal.rules import RuleContext
from packrehearsal.safe_io import (
    SafeIOError,
    is_regular_file_beneath,
    read_text_beneath,
    read_text_file,
    regular_file_size_beneath,
    repository_read_root,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _python_package() -> Package:
    return Package(
        ecosystem=Ecosystem.PYTHON,
        name="safe",
        version="1.0.0",
        root=".",
        manifest="pyproject.toml",
    )


def test_rooted_reader_accepts_normal_regular_file(tmp_path: Path) -> None:
    _write(tmp_path / "nested/data.txt", "hello")

    assert read_text_beneath(tmp_path, "nested/data.txt", limit=5) == "hello"
    assert regular_file_size_beneath(tmp_path, "nested/data.txt") == 5
    assert is_regular_file_beneath(tmp_path, "nested/data.txt")

    with repository_read_root(tmp_path):
        assert read_text_file(tmp_path / "nested/data.txt", limit=5) == "hello"
        with pytest.raises(SafeIOError, match="escapes active repository root"):
            read_text_file(tmp_path.parent / "outside.txt", limit=5)


def test_rooted_reader_rejects_escape_symlink_nonregular_and_limit(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    _write(outside, "outside")
    (tmp_path / "link").symlink_to(outside.parent, target_is_directory=True)
    _write(tmp_path / "large.txt", "12345")
    (tmp_path / "folder").mkdir()

    with pytest.raises(SafeIOError):
        read_text_beneath(tmp_path, "../outside.txt", limit=100)
    with pytest.raises(SafeIOError):
        read_text_beneath(tmp_path, f"link/{outside.name}", limit=100)
    with pytest.raises(SafeIOError, match="regular file"):
        read_text_beneath(tmp_path, "folder", limit=100)
    with pytest.raises(SafeIOError, match="limit"):
        read_text_beneath(tmp_path, "large.txt", limit=4)
    assert not is_regular_file_beneath(tmp_path, "folder")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_rooted_reader_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)

    with pytest.raises(SafeIOError, match="regular file"):
        read_text_beneath(tmp_path, "pipe", limit=10)


@pytest.mark.skipif(not safe_io._supports_openat(), reason="openat/O_NOFOLLOW is unavailable")
def test_posix_descriptor_read_is_stable_when_path_is_swapped_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.txt"
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    _write(target, "inside")
    _write(outside, "outside")
    original_read = safe_io._bounded_read
    swapped = False

    def swap_then_read(descriptor: int, limit: int) -> bytes:
        nonlocal swapped
        if not swapped:
            target.unlink()
            target.symlink_to(outside)
            swapped = True
        return original_read(descriptor, limit)

    monkeypatch.setattr(safe_io, "_bounded_read", swap_then_read)

    assert read_text_beneath(tmp_path, "target.txt", limit=10) == "inside"
    assert target.is_symlink()


def test_fallback_rejects_deterministic_swap_between_lstat_and_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.txt"
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    _write(target, "inside")
    _write(outside, "outside")
    original_open = safe_io.os.open
    swapped = False

    def swap_then_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and Path(path) == target:
            target.unlink()
            target.symlink_to(outside)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(safe_io, "_supports_openat", lambda: False)
    monkeypatch.setattr(safe_io.os, "open", swap_then_open)

    with pytest.raises(SafeIOError, match="changed while it was opened"):
        read_text_beneath(tmp_path, "target.txt", limit=10)


@pytest.mark.skipif(not safe_io._supports_openat(), reason="openat/O_NOFOLLOW is unavailable")
def test_manifest_swap_before_final_open_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "package.json"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-package.json"
    _write(manifest, '{"name":"inside","version":"1.0.0"}')
    _write(outside, '{"name":"outside","version":"9.9.9"}')
    original_open = safe_io.os.open
    swapped = False

    def swap_then_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and path == "package.json" and dir_fd is not None:
            manifest.unlink()
            manifest.symlink_to(outside)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(safe_io.os, "open", swap_then_open)
    result = discover_packages(tmp_path)

    assert not result.packages
    assert [finding.rule_id for finding in result.findings] == ["discovery-manifest-invalid"]
    assert "outside" not in result.findings[0].message


@pytest.mark.skipif(not safe_io._supports_openat(), reason="openat/O_NOFOLLOW is unavailable")
def test_rule_text_swap_before_final_open_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "pyproject.toml"
    outside = tmp_path.parent / f"{tmp_path.name}-outside.toml"
    _write(manifest, "[project]\nname='inside'\nversion='1'\n")
    _write(outside, "[project]\nname='outside'\nversion='9'\n")
    context = RuleContext(root=tmp_path, package=_python_package())
    original_open = safe_io.os.open
    swapped = False

    def swap_then_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and path == "pyproject.toml" and dir_fd is not None:
            manifest.unlink()
            manifest.symlink_to(outside)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(safe_io.os, "open", swap_then_open)

    with pytest.raises(OSError, match="unsafe repository path"):
        context.read_repository_text("pyproject.toml")
