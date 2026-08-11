"""Canonical JSON reporter."""

from __future__ import annotations

from packrehearsal.models import ScanReport
from packrehearsal.serialization import canonical_json


def render_json(report: ScanReport, *, pretty: bool = True) -> str:
    return canonical_json(report.to_dict(), pretty=pretty)
