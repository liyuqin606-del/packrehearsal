# Decision record: why PackRehearsal

Date: 2026-08-11

## Decision

Build a local-first, read-only release artifact rehearsal tool for npm, Python,
and Rust maintainers.

## Alternatives considered

### GitHub Actions supply-chain scanner

Rejected. Mature projects already cover the space, including zizmor,
actionlint, Poutine, OpenSSF Scorecard, and harden-runner. A new scanner would
need unusually strong threat research and false-positive evidence to earn trust.

### General repository health score

Rejected. Aggregate scores hide judgment, overlap with Scorecard and CHAOSS, and
do not tell a maintainer exactly what bytes will ship.

### General AI issue and pull-request triage bot

Rejected. The category is crowded, requires repository write permissions, and
cannot be meaningfully validated without existing issue volume. It would also
make the project's utility depend on paid inference.

### Reproducible bug-report capsule

Strong runner-up. It addresses a real maintainer workflow and can remain local,
but safe redaction of arbitrary logs creates a difficult confidentiality promise.
It remains a possible separate project, not a PackRehearsal feature.

### Cross-ecosystem release artifact rehearsal

Selected. The final artifact is a concrete, inspectable boundary shared by
package maintainers. A useful implementation naturally requires parsers, archive
safety, package graphs, deterministic rules, reporters, fixtures, and trusted
build boundaries—substantial code justified by the problem rather than line-count
padding.

## Constraints

- The initial implementation deliberately supports only three ecosystems; v1.0
  retains that boundary until real maintainer evidence justifies another.
- Static mode is useful with no API key or network.
- No registry publishing, credential storage, hosted dashboard, telemetry, or
  automatic GitHub writes.
- No artificial LOC target.
- No claim of adoption until external evidence exists.
- External sponsorship never changes findings or safety defaults.

## Reversal criteria

Reconsider the direction if five relevant maintainers independently report that
artifact mismatch is not a material pain, or if a maintained cross-ecosystem tool
already supplies the same safe evidence model. Reconsider individual rules when
real-world false positives cannot be bounded with explicit evidence.
