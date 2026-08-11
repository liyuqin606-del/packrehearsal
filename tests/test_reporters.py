from __future__ import annotations

import json

from packrehearsal.models import Finding, ScanReport, Severity
from packrehearsal.reporters import render_console, render_json, render_markdown, render_sarif


def _report() -> ScanReport:
    finding = Finding(
        rule_id="common-sensitive-file",
        severity=Severity.HIGH,
        title="Sensitive file",
        message="A value with | pipe would ship.",
        remediation="Exclude it before release.",
        package="npm:demo@1.0.0",
        location="package/.env",
    )
    return ScanReport(root=".", packages=(), findings=(finding,))


def test_json_is_stable_and_parseable() -> None:
    first = render_json(_report())
    second = render_json(_report())
    assert first == second
    assert json.loads(first)["counts"]["high"] == 1


def test_console_contains_evidence_and_remediation() -> None:
    output = render_console(_report())
    assert "HIGH (1)" in output
    assert "common-sensitive-file" in output
    assert "fix: Exclude it before release." in output
    assert "fingerprint:" in output


def test_markdown_escapes_table_pipes() -> None:
    output = render_markdown(_report())
    assert "A value with \\| pipe would ship." in output
    assert "| Critical | High |" in output


def test_sarif_has_stable_rule_and_fingerprint() -> None:
    payload = json.loads(render_sarif(_report()))
    run = payload["runs"][0]
    assert payload["version"] == "2.1.0"
    assert run["tool"]["driver"]["rules"][0]["id"] == "common-sensitive-file"
    assert run["results"][0]["fingerprints"]["packrehearsal/v1"]
    assert (
        run["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        == "package/.env"
    )


def test_empty_and_colored_reports_cover_human_paths() -> None:
    empty = ScanReport(root=".", packages=(), findings=())
    assert "No findings." in render_console(empty)
    assert "No findings." in render_markdown(empty)
    assert "\x1b[" in render_console(_report(), color=True)


def test_baseline_note_and_new_only_reports() -> None:
    report = _report()
    finding = report.findings[0]
    baselined = ScanReport(
        root=".",
        packages=(),
        findings=(finding,),
        baseline_fingerprints=(finding.fingerprint,),
    )
    assert "1 known finding" in render_console(baselined)
    assert "No findings." in render_console(baselined, new_only=True)
    assert "No findings." in render_markdown(baselined, new_only=True)
