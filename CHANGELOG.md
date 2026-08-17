# Changelog

All notable changes follow Keep a Changelog conventions. PackRehearsal uses
Semantic Versioning after the first public release.

## [Unreleased]

## [1.1.0] - 2026-08-17

### Added

- `packrehearsal codex-brief` generates deterministic Markdown or JSON
  maintenance work orders from new findings without calling a model, executing
  project code, or using the network.
- Codex task schema v1 with content-derived task IDs, scan IDs, artifact hashes,
  exact finding fingerprints, guardrails, and verification steps.
- Repository-native `AGENTS.md` and a documented human-reviewed Codex maintainer
  workflow.
- Optional `codex-output` support in the composite GitHub Action and a Codex task
  in CI and tagged-release evidence assets.

### Changed

- Project positioning, metadata, architecture, and compatibility documentation
  now describe the evidence-bounded Codex workflow.

### Fixed

- Release provenance now uses the checksum manifest as the exact subject list,
  preventing a trailing multiline-glob entry from attesting an unrelated file.

### Security

- Codex tasks label repository-derived values as untrusted data, render them as
  quoted code in Markdown, place trust constraints before findings, and require
  human review instead of automated merge or release.

## [1.0.0] - 2026-08-14

### Added

- Stable 1.x compatibility policy for CLI commands, exit codes, v1 schemas, and
  published rule IDs.
- CodeQL scanning, CODEOWNERS, structured issue routing, and automated tagged
  releases.
- Release checksums, clean-wheel installation verification, and GitHub
  build-provenance attestations.

### Changed

- Runtime and report versions now share one internal version source.
- CI uses uv 0.12.4, verifies formatting and lock consistency, and installs the
  built wheel into a clean environment.

### Security

- Tagged assets are built from the tag by GitHub Actions and attached only after
  tests, artifact inspection, clean installation, and provenance attestation.

## [0.1.0] - 2026-08-11

### Added

- Initial safe discovery for npm, Python, and Rust package manifests.
- Bounded ZIP and TAR artifact inspection.
- Evidence-based rules with console, JSON, Markdown, and SARIF reports.
- Incremental baselines and content-addressed, self-consistent release receipts.
- Explicit trusted-rehearsal boundary for candidate builds.

[Unreleased]: https://github.com/liyuqin606-del/packrehearsal/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/liyuqin606-del/packrehearsal/releases/tag/v1.1.0
[1.0.0]: https://github.com/liyuqin606-del/packrehearsal/releases/tag/v1.0.0
[0.1.0]: https://github.com/liyuqin606-del/packrehearsal/releases/tag/v0.1.0
