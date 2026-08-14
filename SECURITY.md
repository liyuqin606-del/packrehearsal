# Security policy

## Supported versions

Only the latest 1.x release receives security fixes. A confirmed vulnerability
that affects an older 1.x release will be documented in the advisory.

## Report privately

Do not open a public issue for a vulnerability that could expose credentials,
escape archive limits, execute untrusted project code, overwrite files, or
misrepresent evidence receipts. Use this repository's GitHub private
vulnerability reporting form so the report and follow-up remain confidential.

Include the affected version, operating system, minimal reproducer, impact, and
whether the static default path is affected. Never attach real secrets.

## Response targets

- acknowledgment within 3 business days;
- initial severity assessment within 7 days;
- coordinated remediation plan for confirmed high-severity issues;
- credit in the advisory unless the reporter prefers anonymity.

## Security boundaries

Static scan mode must not execute project code, access registries, or extract
archives. Trusted rehearsal is an explicit code-execution boundary and is safe
only for repositories and revisions the operator already trusts. See
[`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## Automated checks

Every pull request runs the cross-platform test matrix, static self-scan, and
CodeQL. Tagged releases additionally inspect both distributions, verify a clean
wheel installation, publish SHA-256 checksums, and create GitHub provenance
attestations. Automated checks supplement rather than replace human review.
