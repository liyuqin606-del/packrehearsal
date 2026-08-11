"""Shared, non-executing helpers for ecosystem manifest adapters."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packrehearsal.exceptions import DiscoveryError
from packrehearsal.models import Ecosystem, Evidence, Finding, Severity
from packrehearsal.safe_io import read_text_file

MAX_MANIFEST_BYTES = 4 * 1024 * 1024


class ManifestParseError(DiscoveryError):
    """A manifest is unreadable or has a shape the adapter cannot normalize."""

    def __init__(self, manifest: Path, reason: str) -> None:
        self.manifest = manifest
        self.reason = reason
        super().__init__(f"cannot parse {manifest}: {reason}")


@dataclass(frozen=True, slots=True)
class ParsedManifest:
    """Raw manifest data retained for workspace-aware second-pass parsing."""

    path: Path
    data: Mapping[str, Any]


def read_json_manifest(path: Path) -> Mapping[str, Any]:
    """Read a bounded UTF-8 JSON object without importing or executing it."""

    raw = _read_bounded(path)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        reason = f"invalid JSON at line {exc.lineno}, column {exc.colno}"
        raise ManifestParseError(path, reason) from exc
    if not isinstance(value, dict):
        raise ManifestParseError(path, "top-level value must be an object")
    return value


def read_toml_manifest(path: Path) -> Mapping[str, Any]:
    """Read a bounded TOML object with the standard-library parser."""

    raw = _read_bounded(path)
    try:
        value = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestParseError(path, f"invalid TOML: {exc}") from exc
    if not isinstance(value, dict):  # pragma: no cover - tomllib currently always returns a dict
        raise ManifestParseError(path, "top-level value must be a table")
    return value


def manifest_finding(
    root: Path,
    manifest: Path,
    ecosystem: Ecosystem,
    reason: str,
    *,
    package: str | None = None,
) -> Finding:
    """Convert a local parse failure into a deterministic, actionable finding."""

    location = relative_path(root, manifest)
    return Finding(
        rule_id="discovery-manifest-invalid",
        severity=Severity.HIGH,
        title="Package manifest could not be normalized",
        message=f"{location} was skipped: {reason}",
        remediation="Correct the manifest syntax and required package metadata, then scan again.",
        package=package,
        location=location,
        evidence=(Evidence("ecosystem", ecosystem.value),),
    )


def relative_path(root: Path, path: Path) -> str:
    """Return a stable repository-relative POSIX path, using ``.`` for root."""

    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DiscoveryError(f"path escapes discovery root: {path}") from exc
    value = relative.as_posix()
    return value or "."


def repository_path(root: Path, package_root: Path, value: str) -> str | None:
    """Normalize a manifest path without allowing it to escape the repository."""

    if not value or "\x00" in value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return None
    combined = package_root / candidate
    try:
        normalized = combined.resolve(strict=False)
        normalized.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return relative_path(root, normalized)


def find_readme(root: Path, package_root: Path) -> str | None:
    """Find a conventional README deterministically without recursing."""

    try:
        candidates = sorted(
            (
                child
                for child in package_root.iterdir()
                if child.is_file() and child.name.casefold().startswith("readme")
            ),
            key=lambda item: (item.name.casefold(), item.name),
        )
    except OSError:
        return None
    return relative_path(root, candidates[0]) if candidates else None


def string_mapping(value: Any) -> dict[str, str]:
    """Return only string-to-string entries from a manifest mapping."""

    if not isinstance(value, Mapping):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str) and key and item
    }


def table(value: Any) -> Mapping[str, Any]:
    """Narrow an arbitrary parsed value to a mapping."""

    return value if isinstance(value, Mapping) else {}


def string_list(value: Any) -> tuple[str, ...]:
    """Narrow an arbitrary parsed value to non-empty strings."""

    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _read_bounded(path: Path) -> str:
    try:
        return read_text_file(path, limit=MAX_MANIFEST_BYTES)
    except UnicodeDecodeError as exc:
        raise ManifestParseError(path, "file is not valid UTF-8") from exc
    except OSError as exc:
        raise ManifestParseError(path, f"cannot read file: {exc}") from exc
