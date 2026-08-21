# Codex maintenance evidence ledger

The maintenance ledger records what happened after a human maintainer used
Codex on bounded open-source maintenance work. It supports an auditable public
summary without claiming that suggestions were correct, that time was saved,
or that a target was achieved merely because it was declared.

This is a repository tool, not part of the PackRehearsal runtime. It uses only
the Python standard library, reads one local JSON file, and writes Markdown. It
does not contact a network, invoke Codex, send telemetry, edit the repository,
merge a change, or publish a release.

## Start from the empty template

Copy [`examples/maintenance-ledger-template.json`](../examples/maintenance-ledger-template.json).
It is intentionally labeled `template`, has no reporting period, and contains
no task records or adoption claims. A template cannot contain tasks.

When recording real observations:

1. change `report_status` to `measured`;
2. set an inclusive ISO date `period`;
3. add a record only after a maintainer has reviewed the task outcome; and
4. keep prospective goals in `targets`, never in `tasks`.

The complete machine-readable contract is
[`schemas/maintenance-ledger-v1.schema.json`](../schemas/maintenance-ledger-v1.schema.json).
The repository script also enforces globally unique task and finding IDs,
globally unique target IDs, canonical dates, and a period whose start is not
after its end.

## Task fields

| Field | Meaning |
| --- | --- |
| `task_id` | Stable ID for this reviewed maintenance task. |
| `finding_ids` | PackRehearsal fingerprints or other stable finding IDs in scope; use an empty array only when the work was not finding-driven. |
| `outcome` | `accepted`, `modified`, or `rejected` after human review. |
| `human_minutes` | Maintainer time observed for this task, at or above zero. |
| `codex_minutes` | Codex interaction/runtime time observed for this task, at or above zero. |
| `false_positive` | Whether the maintainer adjudicated the underlying finding as a false positive. |
| `boundary_violation` | Whether Codex attempted work beyond the task's declared scope or authority. |
| `verification` | `passed`, `failed`, or `not_run` for the recorded verification step. |

The duration fields are not a controlled comparison. The report deliberately
does not subtract them or label their difference “time saved.” A passed
verification is also not proof that a change is secure, correct in every
environment, merged, released, or adopted downstream.

## Validate and report

From the repository root:

```bash
python tools/maintenance_report.py validate path/to/maintenance-ledger.json
python tools/maintenance_report.py report path/to/maintenance-ledger.json \
  --output maintenance-evidence.md
```

Use `--output -` (the default) to write Markdown to standard output. Both
commands return exit code `2` for invalid input or an I/O failure. Output has no
timestamp and task/target rows are sorted by ID, so the same valid ledger
produces byte-for-byte identical Markdown.

## Targets are not results

Each optional target has a stable `target_id`, a description, a non-negative
numeric `value`, and a unit. The generated report places targets under
**Targets (not observed results)** and repeats that they are prospective goals.
Do not copy a target into project results until real, reviewable task records
support an appropriately scoped claim.

## Publication checklist

- Review every record against its issue, diff, verification output, and human decision.
- Remove secrets, private repository names, and personal data before publication.
- Do not record a `passed` verification merely because Codex said it ran a command.
- Preserve rejected suggestions, false positives, boundary violations, and failed checks.
- Publish the ledger beside the generated report when disclosure is safe, so readers can audit the arithmetic.
