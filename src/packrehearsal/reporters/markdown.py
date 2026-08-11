"""GitHub-friendly Markdown reporter."""

from __future__ import annotations

from packrehearsal.models import ScanReport


def render_markdown(report: ScanReport, *, new_only: bool = False) -> str:
    findings = report.new_findings if new_only else report.findings
    counts = report.counts(new_only=new_only)
    lines = [
        "# PackRehearsal report",
        "",
        f"Scan ID: `{report.scan_id}`",
        "",
        f"Discovered **{len(report.packages)}** package(s) and inspected "
        f"**{len(report.artifacts)}** artifact(s).",
        "",
        "| Critical | High | Medium | Low | Info |",
        "|---:|---:|---:|---:|---:|",
        f"| {counts['critical']} | {counts['high']} | {counts['medium']} | "
        f"{counts['low']} | {counts['info']} |",
        "",
    ]
    if not findings:
        lines.append("No findings.")
        return "\n".join(lines) + "\n"
    lines.extend(
        (
            "| Severity | Rule | Package | Location | Finding |",
            "|---|---|---|---|---|",
        )
    )
    for finding in sorted(
        findings,
        key=lambda item: (
            -item.severity.rank,
            item.rule_id,
            item.package or "",
            item.location or "",
        ),
    ):
        lines.append(
            "| {severity} | `{rule}` | {package} | `{location}` | {message}<br>**Fix:** "
            "{remediation}<br><sub>`{fingerprint}`</sub> |".format(
                severity=finding.severity.value,
                rule=_escape(finding.rule_id),
                package=_escape(finding.package or "repository"),
                location=_escape(finding.location or "-"),
                message=_escape(finding.message),
                remediation=_escape(finding.remediation),
                fingerprint=finding.fingerprint,
            )
        )
    return "\n".join(lines) + "\n"


def github_step_summary(report: ScanReport) -> str:
    """Render only new findings for GitHub's step summary."""

    return render_markdown(report, new_only=True)


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
