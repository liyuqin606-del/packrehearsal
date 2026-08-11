"""Configuration loading with conservative safety defaults."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packrehearsal.exceptions import ConfigurationError
from packrehearsal.models import Severity

CONFIG_FILENAMES = (".packrehearsal.json", "packrehearsal.json")

# Repository configuration is untrusted on pull requests. These ceilings are
# therefore invariants, not defaults that a checked-in config may raise.
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 20_000
MAX_ENTRY_BYTES = 64 * 1024 * 1024
MAX_TOTAL_UNPACKED_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200.0
MAX_HASH_ENTRY_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Limits applied before and while reading untrusted archives."""

    max_archive_bytes: int = MAX_ARCHIVE_BYTES
    max_entries: int = MAX_ARCHIVE_ENTRIES
    max_entry_bytes: int = MAX_ENTRY_BYTES
    max_total_unpacked_bytes: int = MAX_TOTAL_UNPACKED_BYTES
    max_compression_ratio: float = MAX_COMPRESSION_RATIO
    hash_entry_bytes: int = MAX_HASH_ENTRY_BYTES

    def __post_init__(self) -> None:
        integer_fields = {
            "max_archive_bytes": self.max_archive_bytes,
            "max_entries": self.max_entries,
            "max_entry_bytes": self.max_entry_bytes,
            "max_total_unpacked_bytes": self.max_total_unpacked_bytes,
            "hash_entry_bytes": self.hash_entry_bytes,
        }
        invalid_types = [
            name
            for name, value in integer_fields.items()
            if isinstance(value, bool) or not isinstance(value, int)
        ]
        if invalid_types:
            raise ConfigurationError(
                "archive integer limits must be integers: " + ", ".join(sorted(invalid_types))
            )
        if any(value <= 0 for value in integer_fields.values()):
            raise ConfigurationError("archive limits must be positive")
        if isinstance(self.max_compression_ratio, bool) or not isinstance(
            self.max_compression_ratio, int | float
        ):
            raise ConfigurationError("max_compression_ratio must be a number")
        if not math.isfinite(self.max_compression_ratio):
            raise ConfigurationError("max_compression_ratio must be finite")
        if self.max_compression_ratio < 1.0:
            raise ConfigurationError("max_compression_ratio must be at least 1")
        ceilings = {
            "max_archive_bytes": (self.max_archive_bytes, MAX_ARCHIVE_BYTES),
            "max_entries": (self.max_entries, MAX_ARCHIVE_ENTRIES),
            "max_entry_bytes": (self.max_entry_bytes, MAX_ENTRY_BYTES),
            "max_total_unpacked_bytes": (
                self.max_total_unpacked_bytes,
                MAX_TOTAL_UNPACKED_BYTES,
            ),
            "max_compression_ratio": (
                self.max_compression_ratio,
                MAX_COMPRESSION_RATIO,
            ),
            "hash_entry_bytes": (self.hash_entry_bytes, MAX_HASH_ENTRY_BYTES),
        }
        exceeded = [name for name, (value, ceiling) in ceilings.items() if value > ceiling]
        if exceeded:
            raise ConfigurationError(
                "archive limits may only tighten built-in ceilings: " + ", ".join(sorted(exceeded))
            )


@dataclass(frozen=True, slots=True)
class Config:
    """Resolved configuration used for one scan."""

    fail_on: Severity = Severity.HIGH
    exclude: tuple[str, ...] = (
        ".git/**",
        ".hg/**",
        ".svn/**",
        "node_modules/**",
        "target/**",
        ".venv/**",
        "venv/**",
        "dist/**",
        "build/**",
    )
    include_hidden: bool = False
    max_depth: int = 12
    enabled_rules: tuple[str, ...] = ()
    disabled_rules: tuple[str, ...] = ()
    severity_overrides: Mapping[str, Severity] = field(default_factory=dict)
    required_files: tuple[str, ...] = ("README*", "LICENSE*")
    sensitive_patterns: tuple[str, ...] = (
        ".env",
        ".env.*",
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "id_rsa",
        "id_ed25519",
        "**/.npmrc",
        "**/.pypirc",
        "**/.cargo/credentials*",
    )
    archive: ArchiveLimits = field(default_factory=ArchiveLimits)
    trusted_timeout_seconds: int = 180
    allow_network: bool = False

    def __post_init__(self) -> None:
        if self.max_depth < 1 or self.max_depth > 128:
            raise ConfigurationError("max_depth must be between 1 and 128")
        if self.trusted_timeout_seconds < 1 or self.trusted_timeout_seconds > 3_600:
            raise ConfigurationError("trusted_timeout_seconds must be between 1 and 3600")
        overlap = set(self.enabled_rules) & set(self.disabled_rules)
        if overlap:
            raise ConfigurationError(
                f"rules cannot be both enabled and disabled: {', '.join(sorted(overlap))}"
            )

    def rule_enabled(self, rule_id: str) -> bool:
        if rule_id in self.disabled_rules:
            return False
        return not self.enabled_rules or rule_id in self.enabled_rules

    def severity_for(self, rule_id: str, default: Severity) -> Severity:
        return self.severity_overrides.get(rule_id, default)


def discover_config(root: Path, explicit: Path | None = None) -> Path | None:
    """Find a configuration file without walking above the requested root."""

    if explicit is not None:
        path = explicit.expanduser().resolve()
        if not path.is_file():
            raise ConfigurationError(f"configuration file not found: {path}")
        return path
    for filename in CONFIG_FILENAMES:
        candidate = root / filename
        if candidate.is_file():
            return candidate
    return None


def load_config(root: Path, explicit: Path | None = None) -> Config:
    """Load JSON configuration or return secure defaults."""

    path = discover_config(root, explicit)
    if path is None:
        return Config()
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot read configuration {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError("configuration root must be a JSON object")
    return config_from_mapping(payload)


def config_from_mapping(payload: Mapping[str, Any]) -> Config:
    """Validate a mapping and convert it to ``Config``."""

    allowed = {
        "allow_network",
        "archive",
        "disabled_rules",
        "enabled_rules",
        "exclude",
        "fail_on",
        "include_hidden",
        "max_depth",
        "required_files",
        "sensitive_patterns",
        "severity_overrides",
        "trusted_timeout_seconds",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ConfigurationError(f"unknown configuration keys: {', '.join(sorted(unknown))}")

    archive_payload = payload.get("archive", {})
    if not isinstance(archive_payload, Mapping):
        raise ConfigurationError("archive must be an object")
    archive_allowed = {field.name for field in ArchiveLimits.__dataclass_fields__.values()}
    archive_unknown = set(archive_payload) - archive_allowed
    if archive_unknown:
        raise ConfigurationError(f"unknown archive keys: {', '.join(sorted(archive_unknown))}")

    overrides_payload = payload.get("severity_overrides", {})
    if not isinstance(overrides_payload, Mapping):
        raise ConfigurationError("severity_overrides must be an object")
    try:
        severity_overrides = {
            str(rule_id): Severity.parse(str(value)) for rule_id, value in overrides_payload.items()
        }
        return Config(
            allow_network=_boolean(payload, "allow_network", False),
            archive=ArchiveLimits(**{str(key): value for key, value in archive_payload.items()}),
            disabled_rules=_string_tuple(payload, "disabled_rules", ()),
            enabled_rules=_string_tuple(payload, "enabled_rules", ()),
            exclude=_string_tuple(payload, "exclude", Config().exclude),
            fail_on=Severity.parse(str(payload.get("fail_on", Severity.HIGH.value))),
            include_hidden=_boolean(payload, "include_hidden", False),
            max_depth=_integer(payload, "max_depth", 12),
            required_files=_string_tuple(payload, "required_files", Config().required_files),
            sensitive_patterns=_string_tuple(
                payload, "sensitive_patterns", Config().sensitive_patterns
            ),
            severity_overrides=severity_overrides,
            trusted_timeout_seconds=_integer(payload, "trusted_timeout_seconds", 180),
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ConfigurationError):
            raise
        raise ConfigurationError(str(exc)) from exc


def default_config_dict() -> dict[str, Any]:
    """Return a commented-example-friendly default mapping."""

    config = Config()
    return {
        "allow_network": config.allow_network,
        "archive": {
            "hash_entry_bytes": config.archive.hash_entry_bytes,
            "max_archive_bytes": config.archive.max_archive_bytes,
            "max_compression_ratio": config.archive.max_compression_ratio,
            "max_entries": config.archive.max_entries,
            "max_entry_bytes": config.archive.max_entry_bytes,
            "max_total_unpacked_bytes": config.archive.max_total_unpacked_bytes,
        },
        "disabled_rules": [],
        "enabled_rules": [],
        "exclude": list(config.exclude),
        "fail_on": config.fail_on.value,
        "include_hidden": config.include_hidden,
        "max_depth": config.max_depth,
        "required_files": list(config.required_files),
        "sensitive_patterns": list(config.sensitive_patterns),
        "severity_overrides": {},
        "trusted_timeout_seconds": config.trusted_timeout_seconds,
    }


def validate_configured_rule_ids(config: Config, known_rule_ids: Iterable[str]) -> None:
    """Reject configured rule IDs that are absent from the active registry."""

    known = set(known_rule_ids)
    configured = (
        set(config.enabled_rules) | set(config.disabled_rules) | set(config.severity_overrides)
    )
    unknown = sorted(configured - known)
    if unknown:
        raise ConfigurationError("unknown rule IDs in configuration: " + ", ".join(unknown))


def _string_tuple(
    payload: Mapping[str, Any], key: str, default: tuple[str, ...]
) -> tuple[str, ...]:
    value = payload.get(key, default)
    if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
        raise ConfigurationError(f"{key} must be an array of strings")
    return tuple(value)


def _boolean(payload: Mapping[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ConfigurationError(f"{key} must be a boolean")
    return value


def _integer(payload: Mapping[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{key} must be an integer")
    return value


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")
