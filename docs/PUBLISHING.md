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
9. Attach the sdist, wheel, checksums, and release notes to the GitHub release.
10. Record the CI run URL and any known limitations in the release notes.

Tags should be signed or otherwise independently authenticated when the
maintainer's release environment supports it.
