"""Baseline support for incremental adoption in existing repositories."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from packrehearsal.models import Finding, ScanReport
from packrehearsal.serialization import atomic_write_text, canonical_json, read_json

BASELINE_SCHEMA_VERSION = "1"
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{24}$")


def create_baseline(report: ScanReport, *, include_all: bool = True) -> dict[str, Any]:
    """Create a deterministic baseline document from a report."""

    findings = report.findings if include_all else report.new_findings
    entries = [
        {
            "fingerprint": finding.fingerprint,
            "location": finding.location,
            "package": finding.package,
            "rule_id": finding.rule_id,
        }
        for finding in sorted(findings, key=lambda item: item.fingerprint)
    ]
    return {
        "entries": entries,
        "report_scan_id": report.scan_id,
        "schema_version": BASELINE_SCHEMA_VERSION,
        "tool": "packrehearsal",
    }


def save_baseline(path: Path, report: ScanReport) -> None:
    atomic_write_text(path, canonical_json(create_baseline(report), pretty=True))


def load_baseline(path: Path) -> tuple[str, ...]:
    """Load and strictly validate baseline fingerprints."""

    payload = read_json(path)
    if not isinstance(payload, Mapping):
        raise ValueError("baseline root must be an object")
    if payload.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported baseline schema {payload.get('schema_version')!r}; "
            f"expected {BASELINE_SCHEMA_VERSION!r}"
        )
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("baseline entries must be an array")
    fingerprints: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ValueError(f"baseline entry {index} must be an object")
        fingerprint = entry.get("fingerprint")
        if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
            raise ValueError(f"baseline entry {index} has an invalid fingerprint")
        fingerprints.append(fingerprint)
    if len(set(fingerprints)) != len(fingerprints):
        raise ValueError("baseline contains duplicate fingerprints")
    return tuple(sorted(fingerprints))


def partition_findings(
    findings: Iterable[Finding], fingerprints: Iterable[str]
) -> tuple[tuple[Finding, ...], tuple[Finding, ...]]:
    """Return ``(new, baselined)`` findings."""

    known = set(fingerprints)
    new: list[Finding] = []
    baselined: list[Finding] = []
    for finding in findings:
        (baselined if finding.fingerprint in known else new).append(finding)
    return tuple(new), tuple(baselined)
