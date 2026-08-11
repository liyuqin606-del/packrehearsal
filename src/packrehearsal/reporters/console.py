"""Compact terminal reporter with optional ANSI color."""

from __future__ import annotations

from collections import defaultdict

from packrehearsal.models import Finding, ScanReport, Severity

_COLORS = {
    Severity.CRITICAL: "\x1b[1;35m",
    Severity.HIGH: "\x1b[1;31m",
    Severity.MEDIUM: "\x1b[1;33m",
    Severity.LOW: "\x1b[36m",
    Severity.INFO: "\x1b[2m",
}
_RESET = "\x1b[0m"


def render_console(report: ScanReport, *, color: bool = False, new_only: bool = False) -> str:
    findings = report.new_findings if new_only else report.findings
    lines = [
        f"PackRehearsal {report.tool_version}",
        f"root: {report.root}",
        f"packages: {len(report.packages)}  artifacts: {len(report.artifacts)}  "
        f"findings: {len(findings)}",
    ]
    if report.baseline_fingerprints:
        baselined = len(report.findings) - len(report.new_findings)
        lines.append(f"baseline: {baselined} known finding(s) hidden from the failure gate")
    if not findings:
        lines.extend(("", "No findings."))
        return "\n".join(lines) + "\n"

    grouped: dict[Severity, list[Finding]] = defaultdict(list)
    for finding in findings:
        grouped[finding.severity].append(finding)
    for severity in sorted(grouped, key=lambda item: -item.rank):
        label = severity.value.upper()
        if color:
            label = f"{_COLORS[severity]}{label}{_RESET}"
        lines.extend(("", f"{label} ({len(grouped[severity])})"))
        for finding in sorted(
            grouped[severity],
            key=lambda item: (item.rule_id, item.package or "", item.location or ""),
        ):
            scope = finding.package or "repository"
            location = f" [{finding.location}]" if finding.location else ""
            lines.append(f"  {finding.rule_id}  {scope}{location}")
            lines.append(f"    {finding.title}: {finding.message}")
            lines.append(f"    fix: {finding.remediation}")
            lines.append(f"    fingerprint: {finding.fingerprint}")
    return "\n".join(lines) + "\n"
