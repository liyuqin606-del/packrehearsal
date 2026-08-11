# PackRehearsal

[![CI](https://github.com/liyuqin606-del/packrehearsal/actions/workflows/ci.yml/badge.svg)](https://github.com/liyuqin606-del/packrehearsal/actions/workflows/ci.yml)
[![GitHub release](https://img.shields.io/github/v/release/liyuqin606-del/packrehearsal?display_name=tag)](https://github.com/liyuqin606-del/packrehearsal/releases)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-2E8B57.svg)](LICENSE)

**Catch missing files, metadata drift, and accidental payloads in npm, Python,
and Rust packages before publishing them.**

PackRehearsal is a local-first, zero-runtime-dependency release assurance CLI.
It compares package manifests with the archive bytes that will actually ship,
then emits deterministic findings, SARIF, baselines, and content-addressed
receipts. The default scan does not execute project code, contact a registry,
or extract an archive.

> PackRehearsal v0.1 is alpha software. Interfaces may change before v1.0.

## Quick start

Python 3.11 or newer is required. Until a PyPI release is available, install
the tagged source directly from GitHub:

```bash
python -m pip install \
  "packrehearsal @ git+https://github.com/liyuqin606-del/packrehearsal.git@v0.1.0"

packrehearsal scan .
```

The repository dogfoods its own static scan. The checked-in
[example report](examples/self-scan.json) currently renders as:

```text
PackRehearsal 0.1.0
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
  "packrehearsal[rehearsal] @ git+https://github.com/liyuqin606-del/packrehearsal.git@v0.1.0"

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
dependency step. Pin it to a reviewed full commit SHA:

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
        uses: liyuqin606-del/packrehearsal@a19188984efeb70be363f2864013a79cd99c6e39
        with:
          root: .
          format: sarif
          output: packrehearsal.sarif
          fail-on: high
```

Do not run trusted rehearsal on `pull_request_target` or on unreviewed fork
code. If a PR workflow needs a baseline, load it from an independently trusted
base-revision checkout rather than the proposed revision.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Scan completed and no new finding met the failure threshold |
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
```

The test suite is offline and covers archive bounds, symlink/TOCTOU defenses,
workspace discovery, trusted-build resource limits, rule behavior, reporters,
baselines, and receipts.

## Project status

- **v0.1:** discovery, archive inspection, rules, reporters, baselines, receipts,
  and an explicit trusted-rehearsal boundary;
- **v0.2:** expand real-world fixture coverage and monorepo dependency evidence;
- **v0.3:** explore opt-in clean-environment smoke tests for trusted branches;
- **later:** features justified by public issues and maintainer feedback.

## Contributing and security

- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Governance](GOVERNANCE.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Rule catalog](docs/RULES.md)

Security-sensitive reports should use GitHub private vulnerability reporting.
PackRehearsal is licensed under [Apache-2.0](LICENSE).
