"""Root-anchored, no-follow reads for untrusted repository files.

The POSIX implementation walks from an already chosen root directory using
``dir_fd``/``openat`` semantics and refuses symbolic links at every component.
The portable fallback verifies lexical and resolved containment plus stable
``lstat``/``fstat`` identity before and after a bounded descriptor read.  If a
platform cannot provide the identity needed for that verification, it fails
closed instead of following a path optimistically.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar, Token
from pathlib import Path

_READ_CHUNK_BYTES = 64 * 1024
_ACTIVE_ROOT: ContextVar[Path | None] = ContextVar("packrehearsal_safe_root", default=None)
_OPENAT_AVAILABLE = (
    os.name == "posix"
    and os.open in os.supports_dir_fd
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
)


class SafeIOError(OSError):
    """A repository file could not be verified and read without following links."""


@contextmanager
def repository_read_root(root: Path | str) -> Iterator[None]:
    """Set the repository anchor used by compatibility path-only readers."""

    anchor = Path(root).expanduser().absolute()
    token: Token[Path | None] = _ACTIVE_ROOT.set(anchor)
    try:
        yield
    finally:
        _ACTIVE_ROOT.reset(token)


def read_text_file(path: Path | str, *, limit: int, encoding: str = "utf-8") -> str:
    """Safely read a path using the active repository root when available."""

    root, relative = _anchor_for_path(Path(path))
    return read_text_beneath(root, relative, limit=limit, encoding=encoding)


def read_text_beneath(
    root: Path | str,
    relative: Path | str,
    *,
    limit: int,
    encoding: str = "utf-8",
) -> str:
    """Read one regular file below *root* without following any symlink."""

    if limit < 0:
        raise ValueError("read limit must be non-negative")
    data = read_bytes_beneath(root, relative, limit=limit)
    return data.decode(encoding)


def read_bytes_beneath(root: Path | str, relative: Path | str, *, limit: int) -> bytes:
    """Return at most *limit* bytes from a verified regular file below *root*."""

    if limit < 0:
        raise ValueError("read limit must be non-negative")
    anchor = Path(root).expanduser().absolute()
    parts = _relative_parts(relative)
    if _supports_openat():
        with _open_regular_posix(anchor, parts) as descriptor:
            return _bounded_read(descriptor, limit)
    return _read_regular_fallback(anchor, parts, limit)


def regular_file_size_beneath(root: Path | str, relative: Path | str) -> int:
    """Return a verified regular file size without following path components."""

    anchor = Path(root).expanduser().absolute()
    parts = _relative_parts(relative)
    if _supports_openat():
        with _open_regular_posix(anchor, parts) as descriptor:
            return os.fstat(descriptor).st_size
    descriptor, before, candidate, resolved_root = _open_regular_fallback(anchor, parts)
    try:
        after_fd = os.fstat(descriptor)
        _require_unchanged(before, after_fd, "file changed while its size was checked")
        _verify_fallback_path(candidate, resolved_root, before)
        return after_fd.st_size
    finally:
        os.close(descriptor)


def is_regular_file_beneath(root: Path | str, relative: Path | str) -> bool:
    """Whether a path can be opened as a verified regular file below *root*."""

    try:
        regular_file_size_beneath(root, relative)
    except (OSError, ValueError):
        return False
    return True


def _anchor_for_path(path: Path) -> tuple[Path, Path]:
    active = _ACTIVE_ROOT.get()
    candidate = path.expanduser()
    if active is not None:
        absolute = candidate if candidate.is_absolute() else active / candidate
        try:
            return active, absolute.relative_to(active)
        except ValueError as exc:
            raise SafeIOError(f"path escapes active repository root: {path}") from exc

    absolute = candidate.absolute()
    anchor_text = absolute.anchor
    if not anchor_text:
        raise SafeIOError(f"path has no filesystem anchor: {path}")
    anchor = Path(anchor_text)
    try:
        return anchor, absolute.relative_to(anchor)
    except ValueError as exc:  # pragma: no cover - a Path always belongs to its own anchor
        raise SafeIOError(f"cannot anchor path safely: {path}") from exc


def _relative_parts(relative: Path | str) -> tuple[str, ...]:
    path = Path(relative)
    if path.is_absolute():
        raise SafeIOError(f"path must be relative to its repository root: {relative}")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts or any(part == ".." for part in parts):
        raise SafeIOError(f"path must name a file below its repository root: {relative}")
    if any("\x00" in part for part in parts):
        raise SafeIOError("path contains a NUL byte")
    return parts


def _supports_openat() -> bool:
    return _OPENAT_AVAILABLE


def _read_flags(*, directory: bool = False, nofollow: bool = False) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    else:
        flags |= getattr(os, "O_NONBLOCK", 0)
    if nofollow:
        flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


@contextmanager
def _open_regular_posix(root: Path, parts: tuple[str, ...]) -> Iterator[int]:
    descriptors: list[int] = []
    try:
        root_fd = os.open(root, _read_flags(directory=True, nofollow=True))
        descriptors.append(root_fd)
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            raise SafeIOError(f"repository root is not a directory: {root}")

        parent_fd = root_fd
        for component in parts[:-1]:
            directory_fd = os.open(
                component,
                _read_flags(directory=True, nofollow=True),
                dir_fd=parent_fd,
            )
            descriptors.append(directory_fd)
            if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
                raise SafeIOError(f"path component is not a directory: {component}")
            parent_fd = directory_fd

        descriptor = os.open(
            parts[-1],
            _read_flags(nofollow=True),
            dir_fd=parent_fd,
        )
        descriptors.append(descriptor)
        file_status = os.fstat(descriptor)
        if not stat.S_ISREG(file_status.st_mode):
            raise SafeIOError(f"path is not a regular file: {'/'.join(parts)}")
        yield descriptor
    except SafeIOError:
        raise
    except OSError as exc:
        raise SafeIOError(f"cannot safely open {'/'.join(parts)} below {root}: {exc}") from exc
    finally:
        for descriptor in reversed(descriptors):
            with suppress(OSError):
                os.close(descriptor)


def _read_regular_fallback(root: Path, parts: tuple[str, ...], limit: int) -> bytes:
    descriptor, before, candidate, resolved_root = _open_regular_fallback(root, parts)
    try:
        data = _bounded_read(descriptor, limit)
        after_fd = os.fstat(descriptor)
        _require_unchanged(before, after_fd, "file changed while it was read")
        _verify_fallback_path(candidate, resolved_root, before)
        return data
    finally:
        os.close(descriptor)


def _open_regular_fallback(
    root: Path, parts: tuple[str, ...]
) -> tuple[int, os.stat_result, Path, Path]:
    try:
        root_status = root.lstat()
        if stat.S_ISLNK(root_status.st_mode) or not stat.S_ISDIR(root_status.st_mode):
            raise SafeIOError(f"repository root is not a real directory: {root}")
        resolved_root = root.resolve(strict=True)
        candidate = root.joinpath(*parts)

        current = root
        for index, component in enumerate(parts):
            current = current / component
            component_status = current.lstat()
            if stat.S_ISLNK(component_status.st_mode):
                raise SafeIOError(f"symbolic-link path component is not allowed: {current}")
            final = index == len(parts) - 1
            expected_type = stat.S_ISREG if final else stat.S_ISDIR
            if not expected_type(component_status.st_mode):
                kind = "regular file" if final else "directory"
                raise SafeIOError(f"path component is not a {kind}: {current}")

        resolved_candidate = candidate.resolve(strict=True)
        _require_contained(resolved_root, resolved_candidate)
        before = candidate.lstat()
        _require_identity(before)
        descriptor = os.open(candidate, _read_flags())
        opened = os.fstat(descriptor)
        try:
            if not stat.S_ISREG(opened.st_mode):
                raise SafeIOError(f"path is not a regular file: {candidate}")
            _require_unchanged(before, opened, "path changed while it was opened")
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor, before, candidate, resolved_root
    except SafeIOError:
        raise
    except OSError as exc:
        raise SafeIOError(f"cannot safely open {'/'.join(parts)} below {root}: {exc}") from exc


def _verify_fallback_path(candidate: Path, resolved_root: Path, expected: os.stat_result) -> None:
    try:
        after = candidate.lstat()
        resolved_candidate = candidate.resolve(strict=True)
    except OSError as exc:
        raise SafeIOError(f"path changed while it was verified: {candidate}: {exc}") from exc
    _require_unchanged(expected, after, "path changed while it was verified")
    _require_contained(resolved_root, resolved_candidate)


def _require_contained(root: Path, candidate: Path) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SafeIOError(f"resolved path escapes repository root: {candidate}") from exc


def _require_identity(status: os.stat_result) -> None:
    if not hasattr(status, "st_dev") or not hasattr(status, "st_ino") or status.st_ino == 0:
        raise SafeIOError("platform cannot verify stable file identity")


def _require_unchanged(
    before: os.stat_result,
    after: os.stat_result,
    message: str,
) -> None:
    _require_identity(before)
    _require_identity(after)
    before_identity = (before.st_dev, before.st_ino, before.st_mode)
    after_identity = (after.st_dev, after.st_ino, after.st_mode)
    if before_identity != after_identity:
        raise SafeIOError(message)
    before_content = (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_content = (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if before_content != after_content:
        raise SafeIOError(message)


def _bounded_read(descriptor: int, limit: int) -> bytes:
    status = os.fstat(descriptor)
    if not stat.S_ISREG(status.st_mode):
        raise SafeIOError("opened descriptor is not a regular file")
    if status.st_size > limit:
        raise SafeIOError(f"file is {status.st_size} bytes; limit is {limit} bytes")

    chunks: list[bytes] = []
    consumed = 0
    while True:
        chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, limit - consumed + 1))
        if not chunk:
            break
        consumed += len(chunk)
        if consumed > limit:
            raise SafeIOError(f"file exceeds read limit of {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)
