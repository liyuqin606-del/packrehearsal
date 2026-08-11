"""SARIF 2.1.0 reporter for GitHub code scanning and IDEs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from packrehearsal.models import Finding, ScanReport, Severity
from packrehearsal.serialization import canonical_json

_LEVEL = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}


def sarif_dict(report: ScanReport, *, new_only: bool = False) -> dict[str, Any]:
    findings = report.new_findings if new_only else report.findings
    rule_groups: dict[str, list[Finding]] = {}
    for finding in findings:
        rule_groups.setdefault(finding.rule_id, []).append(finding)
    rules = [
        {
            "defaultConfiguration": {
                "level": _LEVEL[max(group, key=lambda item: item.severity.rank).severity]
            },
            "fullDescription": {"text": group[0].message},
            "help": {"text": group[0].remediation},
            "id": rule_id,
            "name": _sarif_name(rule_id),
            "shortDescription": {"text": group[0].title},
        }
        for rule_id, group in sorted(rule_groups.items())
    ]
    results = [_result(finding) for finding in _sorted_findings(findings)]
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "automationDetails": {"id": f"packrehearsal/{report.scan_id}"},
                "results": results,
                "tool": {
                    "driver": {
                        "informationUri": "https://github.com/liyuqin606-del/packrehearsal",
                        "name": "PackRehearsal",
                        "rules": rules,
                        "semanticVersion": report.tool_version,
                    }
                },
            }
        ],
        "version": "2.1.0",
    }


def render_sarif(report: ScanReport, *, new_only: bool = False, pretty: bool = True) -> str:
    return canonical_json(sarif_dict(report, new_only=new_only), pretty=pretty)


def _result(finding: Finding) -> dict[str, Any]:
    result: dict[str, Any] = {
        "fingerprints": {"packrehearsal/v1": finding.fingerprint},
        "level": _LEVEL[finding.severity],
        "message": {"text": f"{finding.message} Remediation: {finding.remediation}"},
        "ruleId": finding.rule_id,
    }
    if finding.location:
        result["locations"] = [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": finding.location},
                    "region": {"startColumn": 1, "startLine": 1},
                }
            }
        ]
    if finding.package:
        result["properties"] = {"package": finding.package, "severity": finding.severity.value}
    return result


def _sorted_findings(findings: Iterable[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda item: (
            -item.severity.rank,
            item.rule_id,
            item.package or "",
            item.location or "",
        ),
    )


def _sarif_name(rule_id: str) -> str:
    return "".join(part.capitalize() for part in rule_id.replace("_", "-").split("-"))
