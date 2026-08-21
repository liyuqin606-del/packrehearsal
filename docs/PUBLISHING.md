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

## First PyPI publication

GitHub releases and PyPI publication are intentionally separate. The tag-driven
release workflow remains the authority that builds, tests, scans, attests, and
publishes immutable assets. The manual `Publish an existing release to PyPI`
workflow only downloads the wheel and sdist from that existing release, verifies
them against `SHA256SUMS.txt`, and then sends those exact bytes to PyPI.

Before the first publication, the project owner must complete the account-bound
steps in PyPI:

1. Enable two-factor authentication on the maintainer's PyPI account.
2. Create a pending trusted publisher for project `packrehearsal` using owner
   `liyuqin606-del`, repository `packrehearsal`, workflow `pypi.yml`, and
   environment `pypi`.
3. Confirm that the GitHub `pypi` environment has the intended reviewer policy.
4. Run the manual workflow with an existing, fully verified release tag.
5. Install from PyPI in a new environment and record the published URL and
   installation result in the release notes.

Do not add a long-lived PyPI token to the repository. The workflow uses GitHub
OIDC and PyPI's
[trusted publishing](https://docs.pypi.org/trusted-publishers/) flow. A failed
or incomplete first publication must not be described as package-registry
availability.

Tags should be signed when the maintainer's release environment supports it.
GitHub artifact attestations authenticate the workflow-built release assets
even when local tag signing is unavailable.
