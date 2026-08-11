"""Release evidence receipts and offline verification."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from packrehearsal.exceptions import ReceiptVerificationError
from packrehearsal.models import ScanReport
from packrehearsal.serialization import atomic_write_text, canonical_json, read_json

RECEIPT_SCHEMA_VERSION = "1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COUNT_KEYS = frozenset({"critical", "high", "medium", "low", "info"})
_RECEIPT_REQUIRED_KEYS = frozenset(
    {
        "artifacts",
        "created_at",
        "finding_counts",
        "package_identities",
        "receipt_id",
        "report_scan_id",
        "report_sha256",
        "schema_version",
        "tool",
        "tool_version",
    }
)


def create_receipt(
    report: ScanReport,
    *,
    repository_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Create a content-addressed receipt for a scan report and its artifacts.

    The receipt is self-consistent and can bind separately retained artifact
    bytes. It is not signed and therefore does not prove who created it.
    """

    report_payload = report.to_dict()
    content: dict[str, Any] = {
        "artifacts": [
            {"path": artifact.path, "sha256": artifact.sha256, "size": artifact.size}
            for artifact in sorted(report.artifacts, key=lambda item: item.path)
        ],
        "created_at": created_at or _receipt_timestamp(),
        "finding_counts": report.counts(),
        "package_identities": sorted(package.identity for package in report.packages),
        "report_scan_id": report.scan_id,
        "report_sha256": _sha256_text(canonical_json(report_payload)),
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "tool": "packrehearsal",
        "tool_version": report.tool_version,
    }
    if repository_commit is not None:
        content["repository_commit"] = repository_commit
    content["receipt_id"] = _receipt_id(content)
    _validate_receipt_shape(content)
    return content


def save_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    atomic_write_text(path, canonical_json(dict(receipt), pretty=True))


def load_receipt(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ReceiptVerificationError("receipt root must be an object")
    return payload


def verify_receipt(
    receipt: Mapping[str, Any],
    *,
    report: ScanReport | None = None,
    artifact_root: Path | None = None,
) -> tuple[str, ...]:
    """Verify receipt integrity and, optionally, report and artifact bytes.

    Returns human-readable checks that passed. Any mismatch raises
    ``ReceiptVerificationError``.
    """

    _validate_receipt_shape(receipt)
    claimed_id = receipt.get("receipt_id")
    if not isinstance(claimed_id, str) or claimed_id != _receipt_id(receipt):
        raise ReceiptVerificationError("receipt_id does not match receipt content")
    checks = ["receipt content hash"]

    if report is not None:
        if receipt.get("report_scan_id") != report.scan_id:
            raise ReceiptVerificationError("receipt does not match the supplied report")
        report_hash = _sha256_text(canonical_json(report.to_dict()))
        if receipt.get("report_sha256") != report_hash:
            raise ReceiptVerificationError("report hash does not match receipt")
        checks.append("report hash")

    if artifact_root is not None:
        entries = receipt.get("artifacts", [])
        if not isinstance(entries, list):
            raise ReceiptVerificationError("receipt artifacts must be an array")
        safe_root = artifact_root.expanduser().resolve(strict=True)
        if not safe_root.is_dir():
            raise ReceiptVerificationError(
                f"artifact verification root is not a directory: {safe_root}"
            )
        for index, entry in enumerate(entries):
            if not isinstance(entry, Mapping):
                raise ReceiptVerificationError(f"artifact entry {index} is not an object")
            relative = entry.get("path")
            expected_hash = entry.get("sha256")
            expected_size = entry.get("size")
            if (
                not isinstance(relative, str)
                or not isinstance(expected_hash, str)
                or isinstance(expected_size, bool)
                or not isinstance(expected_size, int)
            ):
                raise ReceiptVerificationError(f"artifact entry {index} is malformed")
            parts = _receipt_artifact_parts(relative)
            actual_size, actual_hash = _hash_regular_artifact(safe_root, parts, relative)
            if actual_size != expected_size:
                raise ReceiptVerificationError(f"artifact size mismatch: {relative}")
            if actual_hash != expected_hash:
                raise ReceiptVerificationError(f"artifact hash mismatch: {relative}")
        checks.append(f"{len(entries)} artifact hash(es)")
    return tuple(checks)


def _receipt_id(receipt: Mapping[str, Any]) -> str:
    content = {str(key): value for key, value in receipt.items() if key != "receipt_id"}
    return _sha256_text(canonical_json(content))


def _receipt_timestamp() -> str:
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch is not None:
        try:
            timestamp = datetime.fromtimestamp(int(source_date_epoch), tz=UTC)
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError("SOURCE_DATE_EPOCH must be a valid Unix timestamp") from exc
    else:
        timestamp = datetime.now(tz=UTC)
    return timestamp.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_receipt_shape(receipt: Mapping[str, Any]) -> None:
    keys = set(receipt)
    allowed = _RECEIPT_REQUIRED_KEYS | {"repository_commit"}
    missing = sorted(_RECEIPT_REQUIRED_KEYS - keys)
    unknown = sorted(str(key) for key in keys - allowed)
    if missing:
        raise ReceiptVerificationError(
            "receipt does not match schema; missing fields: " + ", ".join(missing)
        )
    if unknown:
        raise ReceiptVerificationError(
            "receipt does not match schema; unknown fields: " + ", ".join(unknown)
        )
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ReceiptVerificationError("unsupported receipt schema")
    if receipt.get("tool") != "packrehearsal":
        raise ReceiptVerificationError("receipt does not match schema; invalid tool")
    for key in ("receipt_id", "report_scan_id", "report_sha256"):
        value = receipt.get(key)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ReceiptVerificationError(f"receipt does not match schema; invalid {key}")
    tool_version = receipt.get("tool_version")
    if not isinstance(tool_version, str) or not tool_version:
        raise ReceiptVerificationError("receipt does not match schema; invalid tool_version")
    created_at = receipt.get("created_at")
    if not isinstance(created_at, str) or not _valid_timestamp(created_at):
        raise ReceiptVerificationError("receipt does not match schema; invalid created_at")
    repository_commit = receipt.get("repository_commit")
    if repository_commit is not None and (
        not isinstance(repository_commit, str) or not repository_commit
    ):
        raise ReceiptVerificationError("receipt does not match schema; invalid repository_commit")

    counts = receipt.get("finding_counts")
    if not isinstance(counts, Mapping) or set(counts) != _COUNT_KEYS:
        raise ReceiptVerificationError("receipt does not match schema; invalid finding_counts")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in counts.values()
    ):
        raise ReceiptVerificationError("receipt does not match schema; invalid finding count")

    identities = receipt.get("package_identities")
    if (
        not isinstance(identities, list)
        or not all(isinstance(value, str) for value in identities)
        or len(set(identities)) != len(identities)
    ):
        raise ReceiptVerificationError("receipt does not match schema; invalid package_identities")

    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list):
        raise ReceiptVerificationError("receipt does not match schema; invalid artifacts")
    paths: set[str] = set()
    for index, entry in enumerate(artifacts):
        if not isinstance(entry, Mapping) or set(entry) != {"path", "sha256", "size"}:
            raise ReceiptVerificationError(
                f"receipt does not match schema; invalid artifact entry {index}"
            )
        path = entry.get("path")
        sha256 = entry.get("sha256")
        size = entry.get("size")
        if not isinstance(path, str):
            raise ReceiptVerificationError(
                f"receipt does not match schema; invalid artifact path {index}"
            )
        _receipt_artifact_parts(path)
        if path in paths:
            raise ReceiptVerificationError(
                f"receipt does not match schema; duplicate artifact path: {path}"
            )
        paths.add(path)
        if not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None:
            raise ReceiptVerificationError(
                f"receipt does not match schema; invalid artifact hash {index}"
            )
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ReceiptVerificationError(
                f"receipt does not match schema; invalid artifact size {index}"
            )


def _valid_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _receipt_artifact_parts(relative: str) -> tuple[str, ...]:
    if "\x00" in relative or "\\" in relative:
        raise ReceiptVerificationError(f"artifact escapes verification root: {relative}")
    portable = PurePosixPath(relative)
    parts = portable.parts
    canonical = "/".join(parts)
    if (
        not parts
        or portable.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or canonical != relative
    ):
        raise ReceiptVerificationError(f"artifact escapes verification root: {relative}")
    return parts


def _hash_regular_artifact(
    root: Path,
    parts: tuple[str, ...],
    display_path: str,
) -> tuple[int, str]:
    """Hash a regular file below *root* without following symlink components."""

    supports_openat = (
        os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW")
    )
    if supports_openat:
        return _hash_regular_artifact_openat(root, parts, display_path)
    return _hash_regular_artifact_fallback(root, parts, display_path)


def _hash_regular_artifact_openat(
    root: Path,
    parts: tuple[str, ...],
    display_path: str,
) -> tuple[int, str]:
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptors: list[int] = []
    try:
        current = os.open(root, directory_flags)
        descriptors.append(current)
        for part in parts[:-1]:
            current = os.open(part, directory_flags, dir_fd=current)
            descriptors.append(current)
        descriptor = os.open(parts[-1], file_flags, dir_fd=current)
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ReceiptVerificationError(f"artifact not found as a regular file: {display_path}")
        digest = _sha256_descriptor(descriptor)
        after = os.fstat(descriptor)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ReceiptVerificationError(f"artifact changed while hashing: {display_path}")
        return after.st_size, digest
    except ReceiptVerificationError:
        raise
    except OSError as exc:
        raise ReceiptVerificationError(
            f"artifact not found as a regular file: {display_path}"
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _hash_regular_artifact_fallback(
    root: Path,
    parts: tuple[str, ...],
    display_path: str,
) -> tuple[int, str]:
    candidate = root
    final_metadata: os.stat_result | None = None
    try:
        for part in parts:
            candidate = candidate / part
            metadata = candidate.lstat()
            final_metadata = metadata
            if stat.S_ISLNK(metadata.st_mode) or _is_windows_reparse_point(metadata):
                raise ReceiptVerificationError(
                    f"artifact not found as a regular file: {display_path}"
                )
        descriptor = os.open(
            candidate,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
        )
    except ReceiptVerificationError:
        raise
    except OSError as exc:
        raise ReceiptVerificationError(
            f"artifact not found as a regular file: {display_path}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ReceiptVerificationError(f"artifact not found as a regular file: {display_path}")
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ReceiptVerificationError(
                f"artifact escapes verification root: {display_path}"
            ) from exc
        resolved_metadata = resolved.stat()
        if (
            final_metadata is None
            or (before.st_dev, before.st_ino)
            != (resolved_metadata.st_dev, resolved_metadata.st_ino)
            or (before.st_dev, before.st_ino) != (final_metadata.st_dev, final_metadata.st_ino)
        ):
            raise ReceiptVerificationError(f"artifact changed while opening: {display_path}")
        digest = _sha256_descriptor(descriptor)
        after = os.fstat(descriptor)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ReceiptVerificationError(f"artifact changed while hashing: {display_path}")
        return after.st_size, digest
    finally:
        os.close(descriptor)


def _sha256_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _is_windows_reparse_point(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)
