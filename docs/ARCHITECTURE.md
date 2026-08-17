# Architecture

PackRehearsal is a single-process CLI with an intentionally small trust boundary.

```text
repository
  │
  ├── safe discovery ──► normalized Package models
  │
  ├── optional artifact files ──► bounded archive snapshots
  │
  └── explicit trusted build ──► isolated temp copy ──► artifact snapshots
                                      (off by default)

Package + Snapshot + Config
  └── rule registry ──► Findings ──► baseline gate
                                      ├── console
                                      ├── deterministic JSON
                                      ├── Markdown
                                      ├── SARIF
                                      ├── evidence receipt
                                      └── bounded Codex task
```

## Layers

### Discovery

Adapters parse `package.json`, `pyproject.toml`, and `Cargo.toml` as data. They
never import packages or evaluate build scripts. Paths become repository-relative
POSIX strings at the boundary.

### Artifact inspection

ZIP and TAR readers enumerate members and hash bounded content without extracting
it. Absolute paths, parent traversal, links, excessive expansion, and suspicious
compression ratios stop inspection.

### Trusted rehearsal

Builders are command plans with a restricted environment, a timeout, and a
bounded temporary workspace/output capture. A single deadline covers source
preflight, copying, and the subprocess. They run only after a CLI trust
acknowledgement. They are not a sandbox; the project has the operator's account
privileges.

### Rules

Rules consume normalized models and return immutable findings. Stable IDs and
fingerprints make baselines reviewable. Severity overrides are configuration,
not hidden scoring.

### Reports and receipts

JSON and SARIF use sorted keys and paths. A scan ID hashes deterministic report
content. Receipts add an explicit timestamp, report hash, artifact hashes, and a
self-hash; timestamp-bearing receipts are intentionally not byte-stable.

### Codex tasks

`codex-brief` filters only new findings at a chosen severity and packages them
as deterministic JSON or reviewable Markdown. The task carries a content hash,
the originating scan ID, untrusted-data policy, editing constraints, and a
verification command. It calls no model and grants no merge or release
authority.

## Non-goals

- package publishing;
- registry credentials;
- automatic pull-request comments;
- hosted storage or telemetry;
- executing artifacts submitted by strangers;
- claiming that a static check proves a package is vulnerability-free.
