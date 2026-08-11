"""Canonical serialization and atomic file helpers."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any


def canonical_json(value: Any, *, pretty: bool = False) -> str:
    """Serialize JSON deterministically with a trailing newline."""

    if pretty:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def read_json(path: Path) -> Any:
    """Read UTF-8 JSON from a regular file."""

    if not path.is_file() or path.is_symlink():
        raise ValueError(f"expected a regular JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_text(path: Path, content: str, *, mode: int = 0o644) -> None:
    """Atomically replace ``path`` without following an existing symlink."""

    requested = path.expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    requested.parent.mkdir(parents=True, exist_ok=True)
    # Resolve only the parent. Resolving the final component would follow an
    # attacker-controlled symlink before we can reject it.
    parent = requested.parent.resolve(strict=True)
    target = parent / requested.name
    _reject_symlink(target)

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=parent)
    temporary = Path(temporary_name)
    directory_fd: int | None = None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            directory_fd = os.open(parent, directory_flags)
        except (OSError, TypeError):
            # Windows lacks reliable directory-fd support. os.replace still
            # replaces the link itself rather than opening its target.
            _reject_symlink(target)
            os.replace(temporary, target)
        else:
            try:
                current = os.stat(target.name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                current = None
            if current is not None and stat.S_ISLNK(current.st_mode):
                raise ValueError(f"refusing to replace symlink: {target}")
            os.replace(temporary, target.name, dst_dir_fd=directory_fd)
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
        temporary.unlink(missing_ok=True)


def _reject_symlink(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"refusing to replace symlink: {path}")
