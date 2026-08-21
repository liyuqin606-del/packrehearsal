from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "tools" / "maintenance_report.py"
SPEC = importlib.util.spec_from_file_location("maintenance_report", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

LedgerValidationError = MODULE.LedgerValidationError
render_markdown = MODULE.render_markdown
validate_ledger = MODULE.validate_ledger


def measured_ledger() -> dict[str, object]:
    return {
        "schema_version": "1",
        "project": "packrehearsal",
        "report_status": "measured",
        "period": {"start": "2026-08-01", "end": "2026-08-31"},
        "tasks": [
            {
                "task_id": "task-002",
                "finding_ids": ["finding-b"],
                "outcome": "modified",
                "human_minutes": 12,
                "codex_minutes": 4.5,
                "false_positive": False,
                "boundary_violation": False,
                "verification": "passed",
            },
            {
                "task_id": "task-001",
                "finding_ids": ["finding-a"],
                "outcome": "rejected",
                "human_minutes": 3,
                "codex_minutes": 2,
                "false_positive": True,
                "boundary_violation": True,
                "verification": "failed",
            },
        ],
        "targets": [
            {
                "target_id": "reviewed-tasks",
                "description": "Review bounded maintenance tasks",
                "value": 10,
                "unit": "tasks",
            }
        ],
    }


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("outcome", "merged"),
        ("verification", "probably"),
    ],
)
def test_invalid_enums_are_rejected(field: str, invalid: str) -> None:
    ledger = measured_ledger()
    task = ledger["tasks"][0]  # type: ignore[index]
    task[field] = invalid

    with pytest.raises(LedgerValidationError, match=field):
        validate_ledger(ledger)


@pytest.mark.parametrize("field", ["human_minutes", "codex_minutes"])
def test_negative_durations_are_rejected(field: str) -> None:
    ledger = measured_ledger()
    task = ledger["tasks"][0]  # type: ignore[index]
    task[field] = -0.1

    with pytest.raises(LedgerValidationError, match="non-negative"):
        validate_ledger(ledger)


def test_duplicate_task_and_finding_ids_are_rejected() -> None:
    ledger = measured_ledger()
    tasks = ledger["tasks"]  # type: ignore[assignment]
    tasks[1]["task_id"] = tasks[0]["task_id"]
    tasks[1]["finding_ids"] = tasks[0]["finding_ids"]

    with pytest.raises(LedgerValidationError) as exc_info:
        validate_ledger(ledger)

    message = str(exc_info.value)
    assert "duplicate task ID" in message
    assert "already assigned" in message


def test_report_is_deterministic_and_sorts_records() -> None:
    ledger = measured_ledger()

    first = render_markdown(ledger)
    second = render_markdown(copy.deepcopy(ledger))

    assert first == second
    assert first.index("task\\-001") < first.index("task\\-002")
    assert "| Human minutes recorded | 15 |" in first
    assert "| Codex minutes recorded | 6.5 |" in first
    assert "difference is not presented as time saved" in first
    assert "Targets (not observed results)" in first


def test_zero_tasks_uses_na_instead_of_dividing_by_zero() -> None:
    ledger = measured_ledger()
    ledger["tasks"] = []

    report = render_markdown(ledger)

    assert "No maintenance tasks were recorded" in report
    assert report.count("n/a (no tasks)") == 3
    assert "| Tasks recorded | 0 |" in report


def test_empty_template_is_explicitly_not_measured() -> None:
    ledger = {
        "schema_version": "1",
        "project": "packrehearsal",
        "report_status": "template",
        "period": None,
        "tasks": [],
        "targets": [],
    }

    report = render_markdown(ledger)

    assert "Template — no measured observations" in report
    assert "empty recording template" in report
    assert "No task records." in report


def test_template_cannot_contain_tasks() -> None:
    ledger = measured_ledger()
    ledger["report_status"] = "template"
    ledger["period"] = None

    with pytest.raises(LedgerValidationError, match="must not contain"):
        validate_ledger(ledger)
