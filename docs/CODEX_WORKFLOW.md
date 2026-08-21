# Codex maintainer workflow

PackRehearsal can turn deterministic static findings into a bounded work order
for Codex. This keeps the scanner—not a model—in charge of what evidence exists,
which findings are in scope, and how completion is checked.

This integration follows OpenAI's published guidance for
[agent-friendly CLIs](https://learn.chatgpt.com/use-cases/agent-friendly-clis):
provide predictable structured output that Codex can compose with repository
tools. Repository conventions and safety boundaries live in
[`AGENTS.md`](../AGENTS.md), which Codex reads before working according to the
official [AGENTS.md guidance](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

PackRehearsal is community-maintained and is not affiliated with or endorsed by
OpenAI.

## 1. Generate the task

```bash
packrehearsal codex-brief . \
  --artifact dist/example-1.2.3-py3-none-any.whl \
  --artifact dist/example-1.2.3.tar.gz \
  --minimum-severity low \
  --format markdown \
  --output codex-maintenance-brief.md
```

Use `--format json` for automation. Schema v1 is documented in
[`schemas/codex-task-v1.schema.json`](../schemas/codex-task-v1.schema.json).
The task contains:

- a content-derived task ID and the originating scan ID;
- only new findings at or above the requested severity;
- package and artifact identities, including artifact SHA-256 hashes;
- finding fingerprints, evidence, and required remediation;
- explicit trust boundaries and a reproducible verification command.

Generating a brief does not call an OpenAI API, require an API key, execute
project code, use the network, or modify the inspected repository.
Artifact, baseline, and explicit configuration inputs must live below the
repository root so the verification command remains portable and does not leak
workstation paths.

## 2. Give Codex the bounded work order

Use a prompt such as:

> Read `codex-maintenance-brief.md` and every applicable `AGENTS.md`. Resolve
> only the listed fingerprints, preserve the stated trust boundaries, run the
> required verification, and report any conflict instead of guessing. Do not
> merge or release.

Repository-derived values are untrusted data. The Markdown renderer quotes them
as code, and the task explicitly tells an agent never to interpret those values
as instructions. The JSON format preserves exact evidence for auditing.

## 3. Review and verify

Codex should explain each changed file and show the exact commands it ran. A
human maintainer then reviews the diff and reruns the command stored in the
task. Completion means the targeted fingerprints are gone without new findings
at the selected threshold; it does not mean the package is vulnerability-free.

If the brief reports `no_changes_requested`, do not manufacture cleanup work.
That status is an explicit no-op result.

## GitHub Action output

The composite action accepts an optional `codex-output` path. When set, it
writes a JSON task before applying the normal finding gate:

```yaml
with:
  root: .
  format: sarif
  output: packrehearsal.sarif
  fail-on: high
  codex-output: codex-maintenance-task.json
```

The Action still ignores repository configuration and rejects repository
baselines on pull-request and merge-group events. Uploading or handing the task
to Codex is a separate, reviewable workflow step; PackRehearsal never posts,
edits, merges, or releases on its own.
