from __future__ import annotations

import json

from packrehearsal.models import (
    Ecosystem,
    Evidence,
    Finding,
    Package,
    ScanReport,
    Severity,
)


def test_finding_fingerprint_is_stable_and_scope_sensitive() -> None:
    finding = Finding(
        rule_id="common-sensitive-file",
        severity=Severity.HIGH,
        title="Sensitive file",
        message="A key would ship.",
        remediation="Exclude it.",
        package="npm:demo@1.0.0",
        location="package/.env",
        evidence=(Evidence("pattern", ".env"),),
    )
    same_scope_different_prose = Finding(
        rule_id="common-sensitive-file",
        severity=Severity.CRITICAL,
        title="Changed title",
        message="Changed explanation.",
        remediation="Changed remediation.",
        package="npm:demo@1.0.0",
        location="package/.env",
        evidence=(Evidence("pattern", ".env"),),
    )
    other_location = Finding(
        rule_id="common-sensitive-file",
        severity=Severity.HIGH,
        title="Sensitive file",
        message="A key would ship.",
        remediation="Exclude it.",
        package="npm:demo@1.0.0",
        location="package/other.env",
        evidence=(Evidence("pattern", ".env"),),
    )

    assert len(finding.fingerprint) == 24
    assert finding.fingerprint == same_scope_different_prose.fingerprint
    assert finding.fingerprint != other_location.fingerprint


def test_report_serialization_and_scan_id_are_deterministic() -> None:
    package = Package(
        ecosystem=Ecosystem.PYTHON,
        name="demo",
        version="1.0.0",
        root=".",
        manifest="pyproject.toml",
        expected_files=("z.py", "a.py"),
    )
    low = Finding(
        rule_id="z-rule",
        severity=Severity.LOW,
        title="Z",
        message="z",
        remediation="fix z",
    )
    high = Finding(
        rule_id="a-rule",
        severity=Severity.HIGH,
        title="A",
        message="a",
        remediation="fix a",
    )
    report = ScanReport(root=".", packages=(package,), findings=(low, high))
    payload = report.to_dict()

    assert payload["findings"][0]["rule_id"] == "a-rule"
    assert payload["packages"][0]["expected_files"] == ["a.py", "z.py"]
    assert payload["scan_id"] == report.scan_id
    assert len(report.scan_id) == 64
    assert json.dumps(payload, sort_keys=True) == json.dumps(report.to_dict(), sort_keys=True)


def test_baseline_changes_new_finding_gate_not_total_counts() -> None:
    finding = Finding(
        rule_id="release-broken",
        severity=Severity.CRITICAL,
        title="Broken",
        message="broken",
        remediation="fix",
    )
    report = ScanReport(
        root=".",
        packages=(),
        findings=(finding,),
        baseline_fingerprints=(finding.fingerprint,),
    )

    assert report.counts()["critical"] == 1
    assert report.counts(new_only=True)["critical"] == 0
    assert report.highest_severity() is Severity.CRITICAL
    assert report.highest_severity(new_only=True) is None
    assert report.should_fail(Severity.HIGH, new_only=False)
    assert not report.should_fail(Severity.HIGH, new_only=True)


def test_severity_parser_is_strict_and_case_insensitive() -> None:
    assert Severity.parse(" HIGH ") is Severity.HIGH
    try:
        Severity.parse("urgent")
    except ValueError as exc:
        assert "unknown severity" in str(exc)
    else:
        raise AssertionError("invalid severity was accepted")
