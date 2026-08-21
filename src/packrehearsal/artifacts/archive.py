"""Bounded, read-only inspection of untrusted package archives.

The inspector deliberately never calls archive extraction helpers.  Member
names and metadata are validated first, and small regular files are hashed by
streaming their decompressed bytes directly from the archive reader.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
import tarfile
import tempfile
import tomllib
import unicodedata
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from email import policy
from email.parser import Parser
from pathlib import Path
from typing import IO

from packrehearsal.config import ArchiveLimits
from packrehearsal.exceptions import ArchiveSafetyError
from packrehearsal.models import ArtifactEntry, ArtifactSnapshot

_HASH_CHUNK_BYTES = 1024 * 1024
_HARD_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
_HARD_MAX_ZIP_ENTRIES = 20_000
_HARD_MAX_ZIP_CENTRAL_DIRECTORY_BYTES = 64 * 1024 * 1024
_MAX_METADATA_BYTES = 256 * 1024
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_ZIP_METHODS = {
    zipfile.ZIP_STORED,
    zipfile.ZIP_DEFLATED,
    zipfile.ZIP_BZIP2,
    zipfile.ZIP_LZMA,
}
_GZIP_MAGIC = b"\x1f\x8b"
_BZIP2_MAGIC = b"BZh"
_XZ_MAGIC = b"\xfd7zXZ\x00"
_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP64_EOCD_SIGNATURE = b"PK\x06\x06"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_CENTRAL_FILE_SIGNATURE = b"PK\x01\x02"
_CENTRAL_DIGITAL_SIGNATURE = b"PK\x05\x05"
_EOCD_MIN_SIZE = 22
_EOCD_SEARCH_BYTES = _EOCD_MIN_SIZE + 65_535


@dataclass(frozen=True, slots=True)
class _CapturedArtifact:
    path: Path
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class _ZipDirectory:
    entries: int
    size: int
    offset: int


_MetadataCandidates = dict[str, tuple[str, bytes] | None]


def inspect_artifact(
    path: Path | str,
    *,
    limits: ArchiveLimits | None = None,
    display_path: str | None = None,
) -> ArtifactSnapshot:
    """Return a deterministic, safe snapshot of ``path``.

    ``display_path`` lets callers provide a repository-relative POSIX path for
    reports.  The source artifact itself must be a regular, non-symlink file.
    """

    source = Path(path)
    active_limits = limits or ArchiveLimits()
    with _capture_artifact(source, active_limits) as captured:
        container = _detect_container(captured.path)
        if container == "zip":
            _preflight_zip(captured.path, active_limits)
            entries, unpacked_size, candidates = _inspect_zip(captured.path, active_limits)
            compressed = True
        else:
            compressed = _is_compressed_tar(captured.path)
            entries, unpacked_size, candidates = _inspect_tar(
                captured.path,
                active_limits,
                compressed=compressed,
            )

        artifact_format = _classify_format(source, container, (entry.path for entry in entries))
        package_metadata = _package_metadata(artifact_format, candidates)
    shown_path = display_path if display_path is not None else source.as_posix()
    metadata = {
        "container": container,
        "entry_count": len(entries),
        "hashed_entry_count": sum(entry.sha256 is not None for entry in entries),
        "unpacked_size": unpacked_size,
    }
    if container == "tar":
        metadata["compressed"] = compressed
    metadata.update(package_metadata)
    return ArtifactSnapshot(
        path=shown_path,
        format=artifact_format,
        sha256=captured.sha256,
        size=captured.size,
        entries=tuple(sorted(entries, key=lambda item: item.path)),
        metadata=metadata,
    )


def inspect_artifacts(
    paths: Iterable[Path | str],
    *,
    limits: ArchiveLimits | None = None,
    root: Path | str | None = None,
) -> tuple[ArtifactSnapshot, ...]:
    """Inspect several artifacts and return snapshots in stable path order."""

    resolved_root = Path(root).resolve() if root is not None else None
    snapshots: list[ArtifactSnapshot] = []
    for item in paths:
        path = Path(item)
        display_path: str | None = None
        if resolved_root is not None:
            try:
                display_path = path.resolve().relative_to(resolved_root).as_posix()
            except ValueError as exc:
                raise ArchiveSafetyError(
                    f"artifact is outside the requested report root: {path}"
                ) from exc
        snapshots.append(inspect_artifact(path, limits=limits, display_path=display_path))
    return tuple(sorted(snapshots, key=lambda item: item.path))


def detect_artifact_format(path: Path | str, *, limits: ArchiveLimits | None = None) -> str:
    """Safely identify an artifact's package/container format."""

    return inspect_artifact(path, limits=limits).format


def sha256_file(path: Path | str) -> str:
    """Hash a regular, non-symlink file with bounded memory use."""

    digest = hashlib.sha256()
    source = Path(path)
    descriptor = _open_regular_nofollow(source)
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            for chunk in iter(lambda: stream.read(_HASH_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ArchiveSafetyError(f"cannot read artifact {path}: {exc}") from exc
    return digest.hexdigest()


@contextmanager
def _capture_artifact(path: Path, limits: ArchiveLimits) -> Iterator[_CapturedArtifact]:
    """Copy one opened source fd into a private, immutable parsing snapshot."""

    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise ArchiveSafetyError(f"cannot stat artifact {path}: {exc}") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise ArchiveSafetyError(f"artifact path must not be a symlink: {path}")
    if not stat.S_ISREG(path_stat.st_mode):
        raise ArchiveSafetyError(f"artifact is not a regular file: {path}")

    maximum = min(limits.max_archive_bytes, _HARD_MAX_ARCHIVE_BYTES)
    if path_stat.st_size > maximum:
        raise ArchiveSafetyError(
            f"archive size {path_stat.st_size} exceeds limit {maximum}: {path}"
        )
    if path_stat.st_size == 0:
        raise ArchiveSafetyError(f"artifact is empty: {path}")

    descriptor = _open_regular_nofollow(path, expected=path_stat)
    with tempfile.TemporaryDirectory(prefix="packrehearsal-artifact-") as temporary:
        snapshot = Path(temporary) / "artifact.snapshot"
        digest = hashlib.sha256()
        copied = 0
        opened_stat: os.stat_result | None = None
        final_stat: os.stat_result | None = None
        try:
            with os.fdopen(descriptor, "rb", closefd=True) as source, snapshot.open("xb") as target:
                opened_stat = os.fstat(source.fileno())
                while True:
                    chunk = source.read(min(_HASH_CHUNK_BYTES, maximum - copied + 1))
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > maximum:
                        raise ArchiveSafetyError(
                            f"archive grew beyond limit {maximum} while being captured: {path}"
                        )
                    digest.update(chunk)
                    target.write(chunk)
                final_stat = os.fstat(source.fileno())
                target.flush()
                os.fsync(target.fileno())
        except ArchiveSafetyError:
            raise
        except OSError as exc:
            raise ArchiveSafetyError(f"cannot capture artifact {path}: {exc}") from exc

        if opened_stat is None or final_stat is None:  # pragma: no cover - defensive
            raise ArchiveSafetyError(f"cannot capture artifact metadata: {path}")
        changed = _stat_identity(opened_stat) != _stat_identity(final_stat)
        if copied != opened_stat.st_size or changed:
            raise ArchiveSafetyError(f"artifact changed while it was captured: {path}")

        try:
            snapshot.chmod(0o400)
            yield _CapturedArtifact(snapshot, digest.hexdigest(), copied)
        finally:
            # Windows cannot remove a read-only temporary file during cleanup.
            with suppress(OSError):
                snapshot.chmod(0o600)


def _open_regular_nofollow(
    path: Path,
    *,
    expected: os.stat_result | None = None,
) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ArchiveSafetyError(
            f"cannot open artifact without following links {path}: {exc}"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ArchiveSafetyError(f"artifact is not a regular file: {path}")
        if expected is not None and (
            expected.st_dev != opened.st_dev or expected.st_ino != opened.st_ino
        ):
            raise ArchiveSafetyError(f"artifact path changed before it could be opened: {path}")
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _detect_container(path: Path) -> str:
    try:
        if zipfile.is_zipfile(path):
            return "zip"
        if tarfile.is_tarfile(path):
            return "tar"
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise ArchiveSafetyError(f"cannot identify artifact {path}: {exc}") from exc
    raise ArchiveSafetyError(f"unsupported or malformed archive: {path}")


def _preflight_zip(path: Path, limits: ArchiveLimits) -> None:
    """Bound the ZIP central directory before ``ZipFile`` allocates ``ZipInfo`` objects."""

    entry_limit = min(limits.max_entries, _HARD_MAX_ZIP_ENTRIES)
    try:
        with path.open("rb") as stream:
            directory = _read_zip_directory(stream, path.stat().st_size)
            if directory.entries > entry_limit:
                raise ArchiveSafetyError(
                    f"archive has {directory.entries} entries; limit is {entry_limit}: {path}"
                )
            if directory.size > _HARD_MAX_ZIP_CENTRAL_DIRECTORY_BYTES:
                raise ArchiveSafetyError(
                    f"ZIP central directory size {directory.size} exceeds hard limit "
                    f"{_HARD_MAX_ZIP_CENTRAL_DIRECTORY_BYTES}: {path}"
                )
            actual_entries = _count_central_directory_entries(stream, directory, entry_limit)
            if actual_entries != directory.entries:
                raise ArchiveSafetyError(
                    f"ZIP central directory count mismatch: declared {directory.entries}, "
                    f"found {actual_entries}: {path}"
                )
    except ArchiveSafetyError:
        raise
    except (OSError, EOFError, struct.error) as exc:
        raise ArchiveSafetyError(f"cannot preflight ZIP archive {path}: {exc}") from exc


def _read_zip_directory(stream: IO[bytes], file_size: int) -> _ZipDirectory:
    eocd_offset, eocd = _find_eocd(stream, file_size)
    (
        _signature,
        disk_number,
        directory_disk,
        disk_entries,
        total_entries,
        directory_size,
        directory_offset,
        _comment_size,
    ) = struct.unpack("<4s4H2LH", eocd)
    needs_zip64 = (
        disk_entries == 0xFFFF
        or total_entries == 0xFFFF
        or directory_size == 0xFFFFFFFF
        or directory_offset == 0xFFFFFFFF
    )
    if needs_zip64:
        return _read_zip64_directory(stream, eocd_offset, file_size)
    if disk_number != 0 or directory_disk != 0 or disk_entries != total_entries:
        raise ArchiveSafetyError("multi-disk ZIP archives are not supported")
    _validate_directory_bounds(directory_offset, directory_size, eocd_offset, file_size)
    return _ZipDirectory(total_entries, directory_size, directory_offset)


def _find_eocd(stream: IO[bytes], file_size: int) -> tuple[int, bytes]:
    tail_size = min(file_size, _EOCD_SEARCH_BYTES)
    stream.seek(file_size - tail_size)
    tail = stream.read(tail_size)
    search_end = len(tail)
    while True:
        index = tail.rfind(_EOCD_SIGNATURE, 0, search_end)
        if index < 0:
            raise ArchiveSafetyError("ZIP end-of-central-directory record was not found")
        if index + _EOCD_MIN_SIZE <= len(tail):
            comment_size = struct.unpack_from("<H", tail, index + 20)[0]
            if index + _EOCD_MIN_SIZE + comment_size == len(tail):
                return file_size - tail_size + index, tail[index : index + _EOCD_MIN_SIZE]
        search_end = index


def _read_zip64_directory(
    stream: IO[bytes],
    eocd_offset: int,
    file_size: int,
) -> _ZipDirectory:
    locator_offset = eocd_offset - 20
    if locator_offset < 0:
        raise ArchiveSafetyError("ZIP64 locator is missing")
    stream.seek(locator_offset)
    locator = stream.read(20)
    if len(locator) != 20:
        raise ArchiveSafetyError("ZIP64 locator is truncated")
    signature, record_disk, record_offset, disk_count = struct.unpack("<4sLQL", locator)
    if signature != _ZIP64_LOCATOR_SIGNATURE:
        raise ArchiveSafetyError("ZIP64 locator signature is missing")
    if record_disk != 0 or disk_count != 1:
        raise ArchiveSafetyError("multi-disk ZIP64 archives are not supported")
    if record_offset < 0 or record_offset + 56 > locator_offset:
        raise ArchiveSafetyError("ZIP64 end-of-central-directory offset is invalid")

    stream.seek(record_offset)
    record = stream.read(56)
    if len(record) != 56:
        raise ArchiveSafetyError("ZIP64 end-of-central-directory record is truncated")
    (
        signature,
        record_size,
        _made_by,
        _needed,
        disk_number,
        directory_disk,
        disk_entries,
        total_entries,
        directory_size,
        directory_offset,
    ) = struct.unpack("<4sQ2H2L4Q", record)
    if signature != _ZIP64_EOCD_SIGNATURE or record_size < 44:
        raise ArchiveSafetyError("ZIP64 end-of-central-directory record is malformed")
    if record_offset + 12 + record_size > locator_offset:
        raise ArchiveSafetyError("ZIP64 end-of-central-directory record overlaps its locator")
    if disk_number != 0 or directory_disk != 0 or disk_entries != total_entries:
        raise ArchiveSafetyError("multi-disk ZIP64 archives are not supported")
    _validate_directory_bounds(directory_offset, directory_size, record_offset, file_size)
    return _ZipDirectory(total_entries, directory_size, directory_offset)


def _validate_directory_bounds(offset: int, size: int, boundary: int, file_size: int) -> None:
    if offset > file_size or size > file_size or offset + size > boundary:
        raise ArchiveSafetyError("ZIP central directory is outside the archive bounds")


def _count_central_directory_entries(
    stream: IO[bytes],
    directory: _ZipDirectory,
    entry_limit: int,
) -> int:
    cursor = directory.offset
    end = directory.offset + directory.size
    count = 0
    while cursor < end:
        stream.seek(cursor)
        signature = stream.read(4)
        if signature == _CENTRAL_FILE_SIGNATURE:
            remainder = stream.read(42)
            if len(remainder) != 42:
                raise ArchiveSafetyError("ZIP central directory entry is truncated")
            header = signature + remainder
            name_size, extra_size, comment_size = struct.unpack_from("<3H", header, 28)
            record_size = 46 + name_size + extra_size + comment_size
            if cursor + record_size > end:
                raise ArchiveSafetyError("ZIP central directory entry exceeds declared bounds")
            count += 1
            if count > entry_limit:
                raise ArchiveSafetyError(
                    f"ZIP central directory has more than {entry_limit} entries"
                )
            cursor += record_size
            continue
        if signature == _CENTRAL_DIGITAL_SIGNATURE:
            size_bytes = stream.read(2)
            if len(size_bytes) != 2:
                raise ArchiveSafetyError("ZIP central-directory signature is truncated")
            signature_size = struct.unpack("<H", size_bytes)[0]
            record_size = 6 + signature_size
            if cursor + record_size != end:
                raise ArchiveSafetyError("ZIP central-directory signature has invalid bounds")
            cursor += record_size
            continue
        raise ArchiveSafetyError(f"unexpected ZIP central-directory signature at offset {cursor}")
    if cursor != end:
        raise ArchiveSafetyError("ZIP central directory did not end at its declared boundary")
    return count


def _inspect_zip(
    path: Path,
    limits: ArchiveLimits,
) -> tuple[list[ArtifactEntry], int, _MetadataCandidates]:
    entries: list[ArtifactEntry] = []
    seen: set[str] = set()
    total_unpacked = 0
    metadata_candidates: _MetadataCandidates = {}
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > limits.max_entries:
                raise ArchiveSafetyError(
                    f"archive has {len(members)} entries; limit is {limits.max_entries}: {path}"
                )
            for member in members:
                unix_mode = (member.external_attr >> 16) & 0xFFFF
                is_directory = member.is_dir() or stat.S_ISDIR(unix_mode)
                normalized = _safe_member_path(member.filename, is_directory=is_directory)
                if normalized is None:
                    continue
                _record_unique_path(normalized, seen)

                file_type = stat.S_IFMT(unix_mode)
                if stat.S_ISLNK(unix_mode):
                    raise ArchiveSafetyError(
                        f"archive member is a symbolic link: {member.filename!r}"
                    )
                if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ArchiveSafetyError(
                        f"archive member has unsupported special type: {member.filename!r}"
                    )
                if member.flag_bits & 0x1:
                    raise ArchiveSafetyError(
                        f"encrypted archive members are not supported: {member.filename!r}"
                    )
                if member.compress_type not in _ZIP_METHODS:
                    raise ArchiveSafetyError(
                        f"unsupported ZIP compression method for {member.filename!r}: "
                        f"{member.compress_type}"
                    )

                size = 0 if is_directory else member.file_size
                compressed_size = 0 if is_directory else member.compress_size
                _check_entry_size(normalized, size, limits)
                if not is_directory and size:
                    ratio = float("inf") if compressed_size <= 0 else size / compressed_size
                    if ratio > limits.max_compression_ratio:
                        raise ArchiveSafetyError(
                            f"archive member compression ratio {ratio:.1f} exceeds limit "
                            f"{limits.max_compression_ratio:.1f}: {normalized}"
                        )
                total_unpacked = _add_unpacked(total_unpacked, size, limits)

                entry_hash: str | None = None
                if not is_directory and size <= limits.hash_entry_bytes:
                    metadata_kind = _metadata_kind(normalized)
                    capture = metadata_kind is not None and size <= _MAX_METADATA_BYTES
                    with archive.open(member, "r") as stream:
                        entry_hash, payload = _hash_member_stream(
                            stream,
                            expected_size=size,
                            path=normalized,
                            max_bytes=limits.max_entry_bytes,
                            capture=capture,
                        )
                    if metadata_kind is not None and payload is not None:
                        _remember_metadata(metadata_candidates, metadata_kind, normalized, payload)
                entries.append(
                    ArtifactEntry(
                        path=normalized,
                        size=size,
                        compressed_size=compressed_size,
                        mode=stat.S_IMODE(unix_mode) if unix_mode else None,
                        kind="directory" if is_directory else "file",
                        sha256=entry_hash,
                    )
                )
    except ArchiveSafetyError:
        raise
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ArchiveSafetyError(f"cannot safely inspect ZIP archive {path}: {exc}") from exc
    return entries, total_unpacked, metadata_candidates


def _inspect_tar(
    path: Path,
    limits: ArchiveLimits,
    *,
    compressed: bool,
) -> tuple[list[ArtifactEntry], int, _MetadataCandidates]:
    entries: list[ArtifactEntry] = []
    seen: set[str] = set()
    total_unpacked = 0
    metadata_candidates: _MetadataCandidates = {}
    archive_size = path.stat().st_size
    try:
        with tarfile.open(path, mode="r:*") as archive:
            for index, member in enumerate(archive, start=1):
                if index > limits.max_entries:
                    raise ArchiveSafetyError(
                        f"archive has more than {limits.max_entries} entries: {path}"
                    )
                normalized = _safe_member_path(member.name, is_directory=member.isdir())
                if normalized is None:
                    continue
                _record_unique_path(normalized, seen)

                if member.issym():
                    raise ArchiveSafetyError(f"archive member is a symbolic link: {member.name!r}")
                if member.islnk():
                    raise ArchiveSafetyError(f"archive member is a hard link: {member.name!r}")
                if not (member.isfile() or member.isdir()):
                    raise ArchiveSafetyError(
                        f"archive member has unsupported special type: {member.name!r}"
                    )

                size = member.size if member.isfile() else 0
                _check_entry_size(normalized, size, limits)
                total_unpacked = _add_unpacked(total_unpacked, size, limits)
                if compressed and total_unpacked:
                    ratio = total_unpacked / archive_size
                    if ratio > limits.max_compression_ratio:
                        raise ArchiveSafetyError(
                            f"archive compression ratio {ratio:.1f} exceeds limit "
                            f"{limits.max_compression_ratio:.1f}: {path}"
                        )

                entry_hash: str | None = None
                if member.isfile() and size <= limits.hash_entry_bytes:
                    metadata_kind = _metadata_kind(normalized)
                    capture = metadata_kind is not None and size <= _MAX_METADATA_BYTES
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ArchiveSafetyError(f"cannot read archive member: {normalized}")
                    with stream:
                        entry_hash, payload = _hash_member_stream(
                            stream,
                            expected_size=size,
                            path=normalized,
                            max_bytes=limits.max_entry_bytes,
                            capture=capture,
                        )
                    if metadata_kind is not None and payload is not None:
                        _remember_metadata(metadata_candidates, metadata_kind, normalized, payload)
                entries.append(
                    ArtifactEntry(
                        path=normalized,
                        size=size,
                        mode=member.mode & 0o7777,
                        kind="directory" if member.isdir() else "file",
                        sha256=entry_hash,
                    )
                )
    except ArchiveSafetyError:
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise ArchiveSafetyError(f"cannot safely inspect tar archive {path}: {exc}") from exc
    return entries, total_unpacked, metadata_candidates


def _safe_member_path(raw_path: str, *, is_directory: bool) -> str | None:
    if not raw_path:
        raise ArchiveSafetyError("archive contains an empty member path")
    if "\x00" in raw_path:
        raise ArchiveSafetyError("archive member path contains a NUL byte")
    if any(ord(character) < 32 or ord(character) == 127 for character in raw_path):
        raise ArchiveSafetyError(f"archive member path contains control characters: {raw_path!r}")

    portable = unicodedata.normalize("NFC", raw_path.replace("\\", "/"))
    if portable.startswith("/") or _WINDOWS_DRIVE.match(portable):
        raise ArchiveSafetyError(f"archive member has an absolute path: {raw_path!r}")

    parts: list[str] = []
    for part in portable.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ArchiveSafetyError(f"archive member traverses its destination: {raw_path!r}")
        parts.append(part)
    if not parts:
        if is_directory:
            return None
        raise ArchiveSafetyError(f"archive member has no usable path: {raw_path!r}")
    return "/".join(parts)


def _record_unique_path(path: str, seen: set[str]) -> None:
    if path in seen:
        raise ArchiveSafetyError(f"archive contains duplicate normalized path: {path}")
    seen.add(path)


def _check_entry_size(path: str, size: int, limits: ArchiveLimits) -> None:
    if size < 0:
        raise ArchiveSafetyError(f"archive member has a negative size: {path}")
    if size > limits.max_entry_bytes:
        raise ArchiveSafetyError(
            f"archive member size {size} exceeds limit {limits.max_entry_bytes}: {path}"
        )


def _add_unpacked(total: int, size: int, limits: ArchiveLimits) -> int:
    updated = total + size
    if updated > limits.max_total_unpacked_bytes:
        raise ArchiveSafetyError(
            f"archive unpacked size {updated} exceeds limit {limits.max_total_unpacked_bytes}"
        )
    return updated


def _hash_member_stream(
    stream: IO[bytes],
    *,
    expected_size: int,
    path: str,
    max_bytes: int,
    capture: bool = False,
) -> tuple[str, bytes | None]:
    digest = hashlib.sha256()
    captured = bytearray() if capture else None
    consumed = 0
    while True:
        chunk = stream.read(min(_HASH_CHUNK_BYTES, max_bytes - consumed + 1))
        if not chunk:
            break
        consumed += len(chunk)
        if consumed > max_bytes or consumed > expected_size:
            raise ArchiveSafetyError(f"archive member expands beyond its declared size: {path}")
        digest.update(chunk)
        if captured is not None:
            captured.extend(chunk)
    if consumed != expected_size:
        raise ArchiveSafetyError(
            f"archive member size mismatch for {path}: declared {expected_size}, read {consumed}"
        )
    return digest.hexdigest(), bytes(captured) if captured is not None else None


def _metadata_kind(path: str) -> str | None:
    parts = path.split("/")
    if parts == ["package", "package.json"]:
        return "npm"
    if len(parts) >= 2 and parts[-1] == "METADATA" and parts[-2].endswith(".dist-info"):
        return "wheel"
    if len(parts) <= 2 and parts[-1] == "PKG-INFO":
        return "sdist"
    if len(parts) <= 2 and parts[-1] == "Cargo.toml":
        return "crate"
    return None


def _remember_metadata(
    candidates: _MetadataCandidates,
    kind: str,
    path: str,
    payload: bytes,
) -> None:
    if kind in candidates:
        candidates[kind] = None
    else:
        candidates[kind] = (path, payload)


def _package_metadata(
    artifact_format: str,
    candidates: _MetadataCandidates,
) -> dict[str, object]:
    expected_kind = {
        "tgz": "npm",
        "wheel": "wheel",
        "sdist": "sdist",
        "crate": "crate",
    }.get(artifact_format)
    if expected_kind is None:
        return {}
    candidate = candidates.get(expected_kind)
    if candidate is None:
        return {}
    source, payload = candidate
    try:
        if expected_kind == "npm":
            name, version = _parse_npm_metadata(payload)
        elif expected_kind in {"wheel", "sdist"}:
            parsed = _parse_python_metadata(payload)
            if parsed is None:
                return {}
            return {"metadata_source": source, **parsed}
        else:
            name, version = _parse_crate_metadata(payload)
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        return {}
    if name is None or version is None:
        return {}
    return {
        "metadata_source": source,
        "package_name": name,
        "package_version": version,
    }


def _parse_npm_metadata(payload: bytes) -> tuple[str | None, str | None]:
    decoded = payload.decode("utf-8", errors="strict")
    value = json.loads(decoded)
    if not isinstance(value, dict):
        return None, None
    return _metadata_value(value.get("name")), _metadata_value(value.get("version"))


def _parse_python_metadata(payload: bytes) -> dict[str, object] | None:
    decoded = payload.decode("utf-8", errors="strict")
    message = Parser(policy=policy.default).parsestr(decoded, headersonly=True)
    if message.defects:
        return None
    names = message.get_all("Name", [])
    versions = message.get_all("Version", [])
    if len(names) != 1 or len(versions) != 1:
        return None
    name = _metadata_value(names[0])
    version = _metadata_value(versions[0])
    if name is None or version is None:
        return None

    result: dict[str, object] = {
        "package_name": name,
        "package_version": version,
    }
    for header, key in (
        ("Requires-Python", "requires_python"),
        ("License-Expression", "license_expression"),
    ):
        scalar_values = message.get_all(header, [])
        if len(scalar_values) == 1 and (value := _metadata_value(scalar_values[0])) is not None:
            result[key] = value

    if "license_expression" not in result:
        legacy_values = message.get_all("License", [])
        if len(legacy_values) == 1:
            legacy = _metadata_value(legacy_values[0])
            if legacy is not None and legacy.casefold() != "unknown":
                result["license_expression"] = legacy

    for header, key in (
        ("Requires-Dist", "requires_dist"),
        ("Provides-Extra", "provides_extra"),
    ):
        raw_values = message.get_all(header, [])
        repeated_values = tuple(_metadata_value(item) for item in raw_values)
        if raw_values and all(item is not None for item in repeated_values):
            result[key] = tuple(sorted(item for item in repeated_values if item is not None))
    return result


def _parse_crate_metadata(payload: bytes) -> tuple[str | None, str | None]:
    decoded = payload.decode("utf-8", errors="strict")
    value = tomllib.loads(decoded)
    package = value.get("package")
    if not isinstance(package, dict):
        return None, None
    return _metadata_value(package.get("name")), _metadata_value(package.get("version"))


def _metadata_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 512:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        return None
    return normalized


def _is_compressed_tar(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            prefix = stream.read(max(len(_XZ_MAGIC), len(_BZIP2_MAGIC), len(_GZIP_MAGIC)))
    except OSError as exc:
        raise ArchiveSafetyError(f"cannot read artifact {path}: {exc}") from exc
    return (
        prefix.startswith(_GZIP_MAGIC)
        or prefix.startswith(_BZIP2_MAGIC)
        or prefix.startswith(_XZ_MAGIC)
    )


def _classify_format(path: Path, container: str, entry_paths: Iterable[str]) -> str:
    names = tuple(entry_paths)
    lowered_name = path.name.lower()
    lowered_entries = tuple(name.lower() for name in names)
    if lowered_name.endswith(".whl") or any(
        name.endswith(".dist-info/wheel") for name in lowered_entries
    ):
        return "wheel"
    if lowered_name.endswith(".crate") or any(
        name.endswith("/.cargo_vcs_info.json") or name == ".cargo_vcs_info.json"
        for name in lowered_entries
    ):
        return "crate"
    if any(name.endswith("/pkg-info") or name == "pkg-info" for name in lowered_entries):
        return "sdist"
    if lowered_name.endswith(".tgz"):
        return "tgz"
    if lowered_name.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        return "tar.gz" if lowered_name.endswith(".tar.gz") else "tar"
    return container
