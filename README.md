# PackRehearsal

[![CI](https://github.com/liyuqin606-del/packrehearsal/actions/workflows/ci.yml/badge.svg)](https://github.com/liyuqin606-del/packrehearsal/actions/workflows/ci.yml)
[![CodeQL](https://github.com/liyuqin606-del/packrehearsal/actions/workflows/codeql.yml/badge.svg)](https://github.com/liyuqin606-del/packrehearsal/actions/workflows/codeql.yml)
[![GitHub release](https://img.shields.io/github/v/release/liyuqin606-del/packrehearsal?display_name=tag)](https://github.com/liyuqin606-del/packrehearsal/releases)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-2E8B57.svg)](LICENSE)

**Turn release evidence into a bounded Codex maintenance task before an npm,
Python, or Rust package is published.**

PackRehearsal is a local-first, zero-runtime-dependency release assurance CLI.
It compares package manifests with the archive bytes that will actually ship,
then emits deterministic findings, SARIF, baselines, receipts, and
evidence-bounded work orders for Codex. The scanner—not a model—defines the
finding scope and verification command. The default path does not execute
project code, call an OpenAI API, contact a registry, or extract an archive.

PackRehearsal 1.x is stable. CLI commands and exit codes; report, Codex task,
baseline, and receipt schemas v1; and published rule IDs follow the
compatibility policy below. Intentional breaking changes require a new major
version.

## Quick start

Python 3.11 or newer is required. Install the immutable wheel attached to the
GitHub release:

```bash
python -m pip install \
  "https://github.com/liyuqin606-del/packrehearsal/releases/download/v1.1.0/packrehearsal-1.1.0-py3-none-any.whl"

packrehearsal scan .
packrehearsal codex-brief . --output codex-maintenance-brief.md
```

The repository dogfoods its own static scan. The checked-in
[example report](examples/self-scan.json) currently renders as:

```text
PackRehearsal 1.1.0
root: .
packages: 1  artifacts: 0  findings: 0

No findings.
```

To compare source metadata with a built artifact:

```bash
packrehearsal scan . \
  --artifact dist/example-1.2.3-py3-none-any.whl
```

## What it catches

A green source tree can still produce a broken or unexpectedly packaged
artifact. PackRehearsal checks evidence at the release boundary:

| Problem | Evidence inspected |
|---|---|
| Declared entrypoint never reaches the archive | Manifest targets and archive members |
| Wheel or sdist identifies the wrong release | Manifest name/version and artifact metadata |
| README, license, or configured payload is omitted | Repository paths and packaged paths |
| Credential-like or unexpectedly large file would ship | Repository and archive member inventory |
| Monorepo packages publish incompatible sibling versions | Normalized internal dependency constraints |
| Archive contains traversal, links, special files, or excessive expansion | Bounded ZIP/TAR structural inspection |

Every finding includes a stable rule ID, severity, package/location, supporting
evidence, remediation, and a fingerprint suitable for reviewable baselines.
See the [rule catalog](docs/RULES.md) for the executable rule families.

## Codex maintenance loop

`codex-brief` turns only new, in-scope findings into a deterministic Markdown
or JSON task:

```bash
packrehearsal codex-brief . \
  --artifact dist/example-1.2.3-py3-none-any.whl \
  --minimum-severity low \
  --format json \
  --output codex-maintenance-task.json
```

The task carries a content-derived task ID, originating scan ID, artifact
hashes, exact finding fingerprints, remediation, guardrails, and a verification
command. Repository-derived text is marked as untrusted data. Codex is told not
to execute project code, weaken policy, make unrelated edits, merge, or release.
If there are no selected findings, the task explicitly says **do not invent
work**.

No API key is required: PackRehearsal produces the evidence bundle, while the
maintainer decides whether and where to give it to Codex. See the complete
[Codex maintainer workflow](docs/CODEX_WORKFLOW.md) and repository-native
[`AGENTS.md`](AGENTS.md).

## Safe by default

`packrehearsal scan` is deliberately static:

- no registry or network access;
- no writes to the inspected repository;
- no package lifecycle scripts or imports of project code;
- no extraction of untrusted archives;
- root-anchored, no-follow reads for manifests and rule inputs;
- hard ceilings for archive bytes, entries, expansion, and compression ratio;
- deterministic JSON suitable for review and baselining.

Receipts bind report and artifact hashes and can be verified offline. They are
unsigned self-consistency evidence—not proof of authorship or package safety.

Every v1 release includes SHA-256 checksums and GitHub build-provenance
attestations generated from the tagged source. After downloading an asset:

```bash
gh attestation verify packrehearsal-1.1.0-py3-none-any.whl \
  --repo liyuqin606-del/packrehearsal
```

`packrehearsal rehearse` is a separate trusted-code boundary. Package builders
can execute arbitrary project code, so rehearsal requires an explicit
`--trusted-rehearsal` acknowledgement. Source-copy size, entry count, deadline,
and subprocess output have hard caps, but rehearsal is **not an OS sandbox**.
Never enable it for an unreviewed fork. Read the [threat
model](docs/THREAT_MODEL.md) before using it in CI.

## Supported ecosystems

| Ecosystem | Static discovery | Artifact inspection | Trusted candidate build |
|---|---:|---:|---:|
| npm / workspaces | Yes | `.tgz` | `npm pack --ignore-scripts` |
| Python | Yes | wheel and sdist | `python -m build` |
| Rust / workspaces | Yes | `.crate` | `cargo package` |

New adapters will be considered after the current three are stabilized with
fixtures and maintainer feedback.

## Core workflows

### Inspect an existing artifact

```bash
packrehearsal inspect dist/example-1.2.3-py3-none-any.whl
packrehearsal inspect package/example-1.2.3.tgz --format json
```

`inspect` produces a bounded structural snapshot. Use `scan ROOT --artifact
PATH` when you also want manifest-aware rules.

### Produce machine-readable reports

```bash
packrehearsal scan . --format json --output report.json
packrehearsal scan . --format markdown --output report.md
packrehearsal scan . --format sarif --output report.sarif
```

### Generate a Codex work order

```bash
packrehearsal codex-brief . --format markdown --output codex-brief.md
packrehearsal codex-brief . --format json --output codex-task.json
```

`codex-brief` always exits zero after a successful scan because its job is to
write a task, not apply the normal finding gate. Findings remain unchanged and
continue to control `packrehearsal scan` exit status.

### Baseline existing findings

```bash
packrehearsal scan . --write-baseline .packrehearsal-baseline.json
packrehearsal scan . \
  --baseline .packrehearsal-baseline.json \
  --fail-on high
```

A baseline suppresses known fingerprints from the failure gate; review it like
code. The bundled GitHub Action refuses repository baselines on pull-request
and merge-group events so a proposed revision cannot exempt its own findings.

### Create an evidence receipt

```bash
packrehearsal scan . \
  --artifact dist/example.whl \
  --receipt release-receipt.json

packrehearsal verify-receipt release-receipt.json --artifact-root .
```

### Build artifacts from a trusted revision

Install the optional Python build frontend, then acknowledge the execution
boundary explicitly:

```bash
python -m pip install \
  "packrehearsal[rehearsal] @ https://github.com/liyuqin606-del/packrehearsal/releases/download/v1.1.0/packrehearsal-1.1.0-py3-none-any.whl"

packrehearsal rehearse . --trusted-rehearsal
```

## Configuration

Generate conservative defaults:

```bash
packrehearsal init
```

Unknown keys and rule IDs fail closed. Repository configuration may tighten
archive limits but cannot raise built-in ceilings. Use `--no-repo-config` when
CI must ignore configuration supplied by the checked-out revision.

```json
{
  "allow_network": false,
  "disabled_rules": [],
  "fail_on": "high",
  "include_hidden": false,
  "max_depth": 12,
  "severity_overrides": {},
  "trusted_timeout_seconds": 180
}
```

## GitHub Actions

The composite action runs only the static path, imports itself in Python
isolated mode, ignores repository configuration, and has no install-time
dependency step. Its optional `codex-output` input emits a JSON maintenance task
before the normal finding gate. Pin the Action to a reviewed full commit SHA:

```yaml
name: PackRehearsal

on:
  pull_request:

permissions:
  contents: read

jobs:
  scan:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Check out source
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.12"

      - name: Scan release metadata
        uses: liyuqin606-del/packrehearsal@a94d39c32da5ac698d28c5a84e74e65e699f81db
        with:
          root: .
          format: sarif
          output: packrehearsal.sarif
          fail-on: high
          codex-output: codex-maintenance-task.json

      - name: Retain the Codex maintenance task
        if: always()
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: codex-maintenance-task
          path: codex-maintenance-task.json
          if-no-files-found: warn
          retention-days: 7
```

Do not run trusted rehearsal on `pull_request_target` or on unreviewed fork
code. If a PR workflow needs a baseline, load it from an independently trusted
base-revision checkout rather than the proposed revision.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Command completed; for `scan`, no new finding met the failure threshold |
| `1` | A new finding met the configured severity threshold |
| `2` | Invalid arguments, configuration, or unsafe input |
| `3` | Trusted rehearsal failed, exceeded a resource bound, or timed out |

## Development

```bash
git clone https://github.com/liyuqin606-del/packrehearsal.git
cd packrehearsal
uv sync --extra dev --extra rehearsal
uv run ruff check .
uv run mypy src/packrehearsal
uv run pytest --cov=packrehearsal --cov-branch
uv run packrehearsal scan .
uv run packrehearsal codex-brief . --format json --output /tmp/codex-task.json
```

The test suite is offline and covers archive bounds, symlink/TOCTOU defenses,
workspace discovery, trusted-build resource limits, rule behavior, reporters,
Codex task injection boundaries, baselines, and receipts.

## Stability and roadmap

Version 1.1 adds the stable Codex task schema and repository-native maintainer
workflow to the 1.x discovery, archive inspection, rules, reporters, baselines,
receipts, and trusted-rehearsal boundary. Patch releases may add rules or harden
parsers without changing documented command semantics. New required arguments,
removal of public commands or rule IDs, incompatible schema changes, and weaker
safety defaults are reserved for a new major version.

Future work is driven by reproducible public issues: more real-world fixtures,
additional monorepo dependency evidence, and opt-in clean-environment smoke
tests for trusted branches. New ecosystems require maintainer feedback before
implementation.

The precise 1.x guarantees and intentionally unstable surfaces are documented
in the [compatibility policy](docs/COMPATIBILITY.md).

## Contributing and security

- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Governance](GOVERNANCE.md)
- [Compatibility policy](docs/COMPATIBILITY.md)
- [Support](SUPPORT.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Rule catalog](docs/RULES.md)
- [Codex workflow](docs/CODEX_WORKFLOW.md)

Security-sensitive reports should use GitHub private vulnerability reporting.
PackRehearsal is licensed under [Apache-2.0](LICENSE).

PackRehearsal is community-maintained and is not affiliated with or endorsed by
OpenAI. Codex and OpenAI are trademarks of their respective owner.
