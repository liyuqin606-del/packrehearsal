"""Stable domain models shared by discovery, rules, reporters, and receipts.

The models intentionally store repository-relative POSIX paths instead of
``pathlib.Path`` objects. This makes reports portable and byte-for-byte stable
across operating systems.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    """Finding severity ordered from informational to release blocking."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {
            Severity.INFO: 0,
            Severity.LOW: 1,
            Severity.MEDIUM: 2,
            Severity.HIGH: 3,
            Severity.CRITICAL: 4,
        }[self]

    @classmethod
    def parse(cls, value: str) -> Severity:
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            choices = ", ".join(item.value for item in cls)
            raise ValueError(f"unknown severity {value!r}; expected one of: {choices}") from exc


class Ecosystem(StrEnum):
    """Supported package ecosystems."""

    NPM = "npm"
    PYTHON = "python"
    RUST = "rust"


@dataclass(frozen=True, slots=True)
class InternalDependency:
    """A dependency that may resolve to another package in the same repository."""

    name: str
    requirement: str
    kind: str = "runtime"

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "name": self.name, "requirement": self.requirement}


@dataclass(frozen=True, slots=True)
class Package:
    """Normalized package metadata obtained without executing project code."""

    ecosystem: Ecosystem
    name: str
    version: str
    root: str
    manifest: str
    workspace_root: str | None = None
    license_expression: str | None = None
    readme: str | None = None
    entrypoints: tuple[str, ...] = ()
    expected_files: tuple[str, ...] = ()
    internal_dependencies: tuple[InternalDependency, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def identity(self) -> str:
        return f"{self.ecosystem.value}:{self.name}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ecosystem": self.ecosystem.value,
            "entrypoints": sorted(self.entrypoints),
            "expected_files": sorted(self.expected_files),
            "internal_dependencies": [
                dependency.to_dict()
                for dependency in sorted(
                    self.internal_dependencies,
                    key=lambda item: (item.kind, item.name, item.requirement),
                )
            ],
            "manifest": self.manifest,
            "name": self.name,
            "root": self.root,
            "version": self.version,
        }
        if self.workspace_root is not None:
            result["workspace_root"] = self.workspace_root
        if self.license_expression is not None:
            result["license"] = self.license_expression
        if self.readme is not None:
            result["readme"] = self.readme
        if self.metadata:
            result["metadata"] = _json_safe(self.metadata)
        return result


@dataclass(frozen=True, slots=True)
class Evidence:
    """Small, non-secret supporting fact attached to a finding."""

    key: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "value": self.value}


@dataclass(frozen=True, slots=True)
class Finding:
    """An actionable rule result with a stable suppression fingerprint."""

    rule_id: str
    severity: Severity
    title: str
    message: str
    remediation: str
    package: str | None = None
    location: str | None = None
    evidence: tuple[Evidence, ...] = ()
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.rule_id or any(character.isspace() for character in self.rule_id):
            raise ValueError("rule_id must be non-empty and contain no whitespace")
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", self.compute_fingerprint())

    def compute_fingerprint(self) -> str:
        payload = {
            "evidence": [item.to_dict() for item in self.evidence],
            "location": self.location,
            "package": self.package,
            "rule_id": self.rule_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()[:24]

    def with_severity(self, severity: Severity) -> Finding:
        return replace(self, severity=severity)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "fingerprint": self.fingerprint,
            "message": self.message,
            "remediation": self.remediation,
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "title": self.title,
        }
        if self.package is not None:
            result["package"] = self.package
        if self.location is not None:
            result["location"] = self.location
        if self.evidence:
            result["evidence"] = [item.to_dict() for item in self.evidence]
        return result


@dataclass(frozen=True, slots=True)
class ArtifactEntry:
    """Normalized metadata for a single archive member."""

    path: str
    size: int
    compressed_size: int | None = None
    mode: int | None = None
    kind: str = "file"
    sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind, "path": self.path, "size": self.size}
        if self.compressed_size is not None:
            result["compressed_size"] = self.compressed_size
        if self.mode is not None:
            result["mode"] = self.mode
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        return result


@dataclass(frozen=True, slots=True)
class ArtifactSnapshot:
    """Safe, deterministic view of a candidate release artifact."""

    path: str
    format: str
    sha256: str
    size: int
    entries: tuple[ArtifactEntry, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "entries": [
                entry.to_dict() for entry in sorted(self.entries, key=lambda item: item.path)
            ],
            "format": self.format,
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
        }
        if self.metadata:
            result["metadata"] = _json_safe(self.metadata)
        return result


@dataclass(frozen=True, slots=True)
class RuleDescriptor:
    """Machine-readable rule catalog entry."""

    rule_id: str
    title: str
    description: str
    default_severity: Severity
    ecosystems: tuple[Ecosystem, ...] = ()
    references: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_severity": self.default_severity.value,
            "description": self.description,
            "ecosystems": sorted(item.value for item in self.ecosystems),
            "references": sorted(self.references),
            "rule_id": self.rule_id,
            "title": self.title,
        }


@dataclass(frozen=True, slots=True)
class ScanReport:
    """Deterministic result of one repository scan."""

    root: str
    packages: tuple[Package, ...]
    findings: tuple[Finding, ...]
    artifacts: tuple[ArtifactSnapshot, ...] = ()
    tool_version: str = "0.1.0"
    schema_version: str = "1"
    baseline_fingerprints: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def new_findings(self) -> tuple[Finding, ...]:
        baseline = set(self.baseline_fingerprints)
        return tuple(item for item in self.findings if item.fingerprint not in baseline)

    @property
    def scan_id(self) -> str:
        payload = self._content_dict(include_metadata=False)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def counts(self, *, new_only: bool = False) -> dict[str, int]:
        findings = self.new_findings if new_only else self.findings
        counts = {severity.value: 0 for severity in Severity}
        for finding in findings:
            counts[finding.severity.value] += 1
        return counts

    def highest_severity(self, *, new_only: bool = False) -> Severity | None:
        findings = self.new_findings if new_only else self.findings
        return max((item.severity for item in findings), key=lambda item: item.rank, default=None)

    def should_fail(self, threshold: Severity, *, new_only: bool = True) -> bool:
        findings = self.new_findings if new_only else self.findings
        return any(item.severity.rank >= threshold.rank for item in findings)

    def to_dict(self, *, include_metadata: bool = True) -> dict[str, Any]:
        result = self._content_dict(include_metadata=include_metadata)
        result["scan_id"] = self.scan_id
        return result

    def _content_dict(self, *, include_metadata: bool) -> dict[str, Any]:
        result: dict[str, Any] = {
            "artifacts": [
                artifact.to_dict()
                for artifact in sorted(self.artifacts, key=lambda item: item.path)
            ],
            "baseline_fingerprints": sorted(set(self.baseline_fingerprints)),
            "counts": self.counts(),
            "findings": [
                finding.to_dict()
                for finding in sorted(
                    self.findings,
                    key=lambda item: (
                        -item.severity.rank,
                        item.rule_id,
                        item.package or "",
                        item.location or "",
                        item.fingerprint,
                    ),
                )
            ],
            "packages": [
                package.to_dict()
                for package in sorted(
                    self.packages,
                    key=lambda item: (item.ecosystem.value, item.root, item.name),
                )
            ],
            "root": self.root,
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
        }
        if include_metadata and self.metadata:
            result["metadata"] = _json_safe(self.metadata)
        return result


def findings_at_or_above(findings: Iterable[Finding], threshold: Severity) -> tuple[Finding, ...]:
    """Return findings meeting a severity threshold while preserving order."""

    return tuple(item for item in findings if item.severity.rank >= threshold.rank)


def _json_safe(value: Any) -> Any:
    """Normalize mappings and sequences into deterministic JSON-compatible values."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda x: str(x[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return str(value)
