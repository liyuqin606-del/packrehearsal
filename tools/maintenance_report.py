#!/usr/bin/env python3
"""Validate a Codex maintenance ledger and render a deterministic public report.

This repository utility intentionally uses only the Python standard library. It
does not contact a network service, invoke a model, or change project files.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

OUTCOMES = ("accepted", "modified", "rejected")
VERIFICATION_OUTCOMES = ("passed", "failed", "not_run")
REPORT_STATUSES = ("measured", "template")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class LedgerValidationError(ValueError):
    """Raised when a maintenance ledger does not satisfy the v1 contract."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("\n".join(self.errors))


def _is_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return isinstance(value, int) or math.isfinite(value)


def _check_keys(
    value: Mapping[str, object],
    *,
    path: str,
    required: set[str],
    errors: list[str],
) -> None:
    missing = sorted(required - value.keys())
    extra = sorted(value.keys() - required)
    for key in missing:
        errors.append(f"{path}: missing required property {key!r}")
    for key in extra:
        errors.append(f"{path}: unexpected property {key!r}")


def _check_string(value: object, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: must be a non-empty string")


def _check_id(value: object, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        errors.append(f"{path}: must match {ID_PATTERN.pattern!r} (1-128 portable ID characters)")


def _check_non_negative_number(value: object, path: str, errors: list[str]) -> None:
    if not _is_number(value) or value < 0:  # type: ignore[operator]
        errors.append(f"{path}: must be a finite, non-negative number")


def _check_date(value: object, path: str, errors: list[str]) -> date | None:
    if not isinstance(value, str):
        errors.append(f"{path}: must be an ISO 8601 date (YYYY-MM-DD)")
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        errors.append(f"{path}: must be an ISO 8601 date (YYYY-MM-DD)")
        return None
    if parsed.isoformat() != value:
        errors.append(f"{path}: must use canonical ISO 8601 form YYYY-MM-DD")
        return None
    return parsed


def validate_ledger(value: object) -> dict[str, Any]:
    """Return *value* as a ledger dict, or raise ``LedgerValidationError``."""

    errors: list[str] = []
    if not isinstance(value, dict):
        raise LedgerValidationError(("$: must be a JSON object",))

    required = {"schema_version", "project", "report_status", "period", "tasks", "targets"}
    _check_keys(value, path="$", required=required, errors=errors)

    if value.get("schema_version") != "1":
        errors.append("$.schema_version: must equal '1'")
    _check_string(value.get("project"), "$.project", errors)

    status = value.get("report_status")
    if status not in REPORT_STATUSES:
        errors.append(f"$.report_status: must be one of {', '.join(REPORT_STATUSES)}")

    period = value.get("period")
    if period is None:
        if status == "measured":
            errors.append("$.period: measured ledgers require a reporting period")
    elif not isinstance(period, dict):
        errors.append("$.period: must be null or an object")
    else:
        _check_keys(period, path="$.period", required={"start", "end"}, errors=errors)
        start = _check_date(period.get("start"), "$.period.start", errors)
        end = _check_date(period.get("end"), "$.period.end", errors)
        if start is not None and end is not None and start > end:
            errors.append("$.period: start must not be after end")

    tasks = value.get("tasks")
    task_ids: set[str] = set()
    finding_ids: set[str] = set()
    if not isinstance(tasks, list):
        errors.append("$.tasks: must be an array")
    else:
        if status == "template" and tasks:
            errors.append("$.tasks: template ledgers must not contain measured task records")
        for index, task in enumerate(tasks):
            task_path = f"$.tasks[{index}]"
            if not isinstance(task, dict):
                errors.append(f"{task_path}: must be an object")
                continue
            task_keys = {
                "task_id",
                "finding_ids",
                "outcome",
                "human_minutes",
                "codex_minutes",
                "false_positive",
                "boundary_violation",
                "verification",
            }
            _check_keys(task, path=task_path, required=task_keys, errors=errors)

            task_id = task.get("task_id")
            _check_id(task_id, f"{task_path}.task_id", errors)
            if isinstance(task_id, str):
                if task_id in task_ids:
                    errors.append(f"{task_path}.task_id: duplicate task ID {task_id!r}")
                task_ids.add(task_id)

            current_finding_ids = task.get("finding_ids")
            if not isinstance(current_finding_ids, list):
                errors.append(f"{task_path}.finding_ids: must be an array")
            else:
                local_ids: set[str] = set()
                for finding_index, finding_id in enumerate(current_finding_ids):
                    finding_path = f"{task_path}.finding_ids[{finding_index}]"
                    _check_id(finding_id, finding_path, errors)
                    if isinstance(finding_id, str):
                        if finding_id in local_ids:
                            errors.append(f"{finding_path}: duplicate finding ID {finding_id!r}")
                        elif finding_id in finding_ids:
                            errors.append(
                                f"{finding_path}: finding ID {finding_id!r} is already assigned"
                            )
                        local_ids.add(finding_id)
                        finding_ids.add(finding_id)

            outcome = task.get("outcome")
            if outcome not in OUTCOMES:
                errors.append(f"{task_path}.outcome: must be one of {', '.join(OUTCOMES)}")
            _check_non_negative_number(
                task.get("human_minutes"), f"{task_path}.human_minutes", errors
            )
            _check_non_negative_number(
                task.get("codex_minutes"), f"{task_path}.codex_minutes", errors
            )
            for field in ("false_positive", "boundary_violation"):
                if not isinstance(task.get(field), bool):
                    errors.append(f"{task_path}.{field}: must be a boolean")
            verification = task.get("verification")
            if verification not in VERIFICATION_OUTCOMES:
                errors.append(
                    f"{task_path}.verification: must be one of {', '.join(VERIFICATION_OUTCOMES)}"
                )

    targets = value.get("targets")
    target_ids: set[str] = set()
    if not isinstance(targets, list):
        errors.append("$.targets: must be an array")
    else:
        for index, target in enumerate(targets):
            target_path = f"$.targets[{index}]"
            if not isinstance(target, dict):
                errors.append(f"{target_path}: must be an object")
                continue
            _check_keys(
                target,
                path=target_path,
                required={"target_id", "description", "value", "unit"},
                errors=errors,
            )
            target_id = target.get("target_id")
            _check_id(target_id, f"{target_path}.target_id", errors)
            if isinstance(target_id, str):
                if target_id in target_ids:
                    errors.append(f"{target_path}.target_id: duplicate target ID {target_id!r}")
                target_ids.add(target_id)
            _check_string(target.get("description"), f"{target_path}.description", errors)
            _check_non_negative_number(target.get("value"), f"{target_path}.value", errors)
            _check_string(target.get("unit"), f"{target_path}.unit", errors)

    if status == "template" and period is not None:
        errors.append("$.period: template ledgers must use null because no period was measured")

    if errors:
        raise LedgerValidationError(errors)
    return value


def load_ledger(path: Path) -> dict[str, Any]:
    """Load and validate a ledger without resolving URLs or contacting a network."""

    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LedgerValidationError((f"{path}: could not read valid UTF-8 JSON: {exc}",)) from exc
    return validate_ledger(value)


def _escape(value: object) -> str:
    escaped = html.escape(str(value), quote=True)
    for character in "\\`*_{}[]()#+-.!|":
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _format_number(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    return format(value, ".15g")


def _percentage(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a (no tasks)"
    return f"{(100 * numerator / denominator):.1f}%"


def render_markdown(ledger: Mapping[str, Any]) -> str:
    """Render a validated ledger as deterministic, evidence-limited Markdown."""

    validated = validate_ledger(dict(ledger))
    tasks = sorted(validated["tasks"], key=lambda item: item["task_id"])
    targets = sorted(validated["targets"], key=lambda item: item["target_id"])
    status = validated["report_status"]
    period = validated["period"]

    outcome_counts = dict.fromkeys(OUTCOMES, 0)
    verification_counts = dict.fromkeys(VERIFICATION_OUTCOMES, 0)
    human_minutes: int | float = 0
    codex_minutes: int | float = 0
    false_positives = 0
    boundary_violations = 0
    for task in tasks:
        outcome_counts[task["outcome"]] += 1
        verification_counts[task["verification"]] += 1
        human_minutes += task["human_minutes"]
        codex_minutes += task["codex_minutes"]
        false_positives += int(task["false_positive"])
        boundary_violations += int(task["boundary_violation"])

    if status == "template":
        status_text = "Template — no measured observations"
        period_text = "not set"
    else:
        status_text = "Measured observations"
        period_text = f"{period['start']} through {period['end']}"

    total = len(tasks)
    incorporated = outcome_counts["accepted"] + outcome_counts["modified"]
    lines = [
        "# Codex maintenance evidence",
        "",
        f"- Project: {_escape(validated['project'])}",
        f"- Data status: **{status_text}**",
        f"- Reporting period: {period_text}",
        "",
        "## Observed results",
        "",
    ]
    if status == "template":
        lines.extend(
            [
                "This is an empty recording template. It contains no task outcomes or "
                "measured use.",
                "",
            ]
        )
    elif not tasks:
        lines.extend(["No maintenance tasks were recorded in this reporting period.", ""])

    lines.extend(
        [
            "| Metric | Observed value |",
            "| --- | ---: |",
            f"| Tasks recorded | {total} |",
            f"| Accepted | {outcome_counts['accepted']} |",
            f"| Modified before acceptance | {outcome_counts['modified']} |",
            f"| Rejected | {outcome_counts['rejected']} |",
            f"| Acceptance or adjustment rate | {_percentage(incorporated, total)} |",
            f"| Verification passed | {verification_counts['passed']} |",
            f"| Verification failed | {verification_counts['failed']} |",
            f"| Verification not run | {verification_counts['not_run']} |",
            f"| Flagged false positives | {false_positives} |",
            f"| False-positive rate | {_percentage(false_positives, total)} |",
            f"| Boundary violations | {boundary_violations} |",
            f"| Boundary-violation rate | {_percentage(boundary_violations, total)} |",
            f"| Human minutes recorded | {_format_number(human_minutes)} |",
            f"| Codex minutes recorded | {_format_number(codex_minutes)} |",
            "",
            "The two duration totals are separate observations. Their difference is not "
            "presented as time saved because this ledger does not contain a controlled "
            "counterfactual.",
            "",
            "## Task records",
            "",
        ]
    )
    if not tasks:
        lines.extend(["No task records.", ""])
    else:
        lines.extend(
            [
                "| Task ID | Finding IDs | Decision | Human min | Codex min | False positive | "
                "Boundary violation | Verification |",
                "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
            ]
        )
        for task in tasks:
            findings = ", ".join(_escape(item) for item in sorted(task["finding_ids"])) or "—"
            lines.append(
                f"| {_escape(task['task_id'])} | {findings} | {task['outcome']} | "
                f"{_format_number(task['human_minutes'])} | "
                f"{_format_number(task['codex_minutes'])} | "
                f"{'yes' if task['false_positive'] else 'no'} | "
                f"{'yes' if task['boundary_violation'] else 'no'} | "
                f"{task['verification']} |"
            )
        lines.append("")

    lines.extend(["## Targets (not observed results)", ""])
    if not targets:
        lines.extend(["No targets declared.", ""])
    else:
        lines.extend(
            [
                "Targets below are prospective goals. They are not evidence of adoption, "
                "quality, or completed work.",
                "",
                "| Target ID | Goal | Value | Unit |",
                "| --- | --- | ---: | --- |",
            ]
        )
        for target in targets:
            lines.append(
                f"| {_escape(target['target_id'])} | {_escape(target['description'])} | "
                f"{_format_number(target['value'])} | {_escape(target['unit'])} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Interpretation limits",
            "",
            "This report is a deterministic summary of maintainer-entered records. The generator "
            "validates structure and arithmetic only; it does not independently verify task "
            "outcomes, authorship, causality, security, adoption, or time savings.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_report(markdown: str, destination: str) -> None:
    if destination == "-":
        sys.stdout.write(markdown)
        return
    Path(destination).write_text(markdown, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="validate a ledger")
    validate_parser.add_argument("ledger", type=Path)
    report_parser = subparsers.add_parser("report", help="validate and render Markdown")
    report_parser.add_argument("ledger", type=Path)
    report_parser.add_argument("--output", "-o", default="-", help="output path, or - for stdout")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ledger = load_ledger(args.ledger)
        if args.command == "report":
            _write_report(render_markdown(ledger), args.output)
        else:
            print(f"valid maintenance ledger: {args.ledger}")
    except LedgerValidationError as exc:
        for error in exc.errors:
            print(f"error: {error}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: could not write report: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
