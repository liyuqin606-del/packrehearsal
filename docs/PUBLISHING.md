# Release checklist

Use this checklist for every PackRehearsal release.

1. Resolve or explicitly defer release-blocking issues.
2. Update `CHANGELOG.md`, package metadata, examples, and schema documentation.
3. Run Ruff, Mypy, the full test suite with branch coverage, and the self-scan.
4. Build the sdist and wheel from a clean checkout.
5. Inspect both artifacts and run manifest-aware rules against them.
6. Verify installation of the wheel in a clean environment.
7. Confirm README Action examples point to a reviewed immutable commit.
8. Tag only a commit whose GitHub Actions matrix is green.
9. Push an annotated `vX.Y.Z` tag whose value matches both package version
   sources; the Release workflow builds, tests, inspects, attests, and uploads
   the assets.
10. Verify the GitHub release contains the sdist, wheel, four inspection
    reports, a Codex release task, checksums, and artifact attestations.
11. Download the published assets and verify `SHA256SUMS.txt` plus
    `gh attestation verify` independently.
12. Record the CI and Release workflow URLs and any known limitations.

Tags should be signed when the maintainer's release environment supports it.
GitHub artifact attestations authenticate the workflow-built release assets
even when local tag signing is unavailable.
