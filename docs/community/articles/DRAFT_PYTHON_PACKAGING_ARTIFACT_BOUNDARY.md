# DRAFT — Test the wheel and sdist, not only the Python source tree

**Target:** Python Packaging, Announcements  
**Status:** Draft; do not publish without a maintainer's final review  
**Primary question:** Which wheel/sdist consistency check has the highest value
and lowest false-positive risk for your release workflow?

> Publication note: this is a technical announcement draft, not evidence of
> PyPA endorsement or downstream adoption. Before posting, validate all commands
> against the linked immutable release and add one redistributable example whose
> expected result has been reviewed.

## Draft post

Python packaging review often stops at `pyproject.toml` and a successful build.
The user, however, installs a wheel or sdist. The archive can disagree with the
source manifest even when the source tree is tidy: a version can drift, a
console-script target can be absent from the wheel, or a referenced file can be
left out of the sdist.

PackRehearsal is an Apache-2.0, zero-runtime-dependency CLI that statically
compares Python release metadata with existing wheel and sdist bytes. It also
supports npm and Rust, but this post is specifically asking for feedback on the
Python rules.

### Inspect an already-built candidate

Use artifacts produced by a trusted build process:

```bash
packrehearsal inspect dist/example-1.2.3-py3-none-any.whl
packrehearsal inspect dist/example-1.2.3.tar.gz

packrehearsal scan . \
  --artifact dist/example-1.2.3-py3-none-any.whl \
  --artifact dist/example-1.2.3.tar.gz \
  --format json \
  --output packrehearsal-report.json
```

Static inspection does not import the package, run build hooks, extract the
archive, or contact an index. ZIP and TAR inputs are subject to entry, byte,
expansion, path, link, special-file, and compression-ratio limits.

Building is intentionally separate. `packrehearsal rehearse` invokes ecosystem
build tools and can therefore execute project code; it requires
`--trusted-rehearsal` and is not an OS sandbox. For an unreviewed repository,
inspect an artifact created by its maintainer rather than enabling a build.

### What gets compared

The Python adapter relates declarative source metadata and archive evidence:

- project name and version versus wheel `METADATA` or sdist `PKG-INFO`;
- console-script module paths versus packaged Python modules;
- source README and license references versus their release representation;
- required project files versus sdist members;
- artifact filename and embedded metadata consistency.

The comparison must respect legitimate wheel/sdist differences. A wheel may
embed the long description in `METADATA` instead of carrying the source README
as a top-level file. License material may be relocated below
`.dist-info/licenses/`. These are valid cases, not omissions, and are covered by
separate expectations.

Every finding carries a rule ID, severity, package/location, evidence,
remediation, and stable fingerprint. JSON, Markdown, and SARIF outputs are
available. A reviewed baseline can suppress an existing fingerprint from the
failure gate, but changing a baseline does not repair an artifact.

### An intentionally narrow claim

PackRehearsal can show that a bounded set of static release invariants passed or
failed for the provided bytes. It cannot show that the package is safe, that
runtime imports succeed on every platform, or that an index will accept a future
upload. Receipts are unsigned consistency evidence, not signatures.

The current pilot therefore records accepted findings, disputed findings, false
positives, missing rules, no-finding cases, and inconclusive runs. No category is
dropped from the denominator.

### Feedback requested

If you maintain a Python package, **which single wheel/sdist consistency check
would you trust as a release gate, and what valid edge case must it exempt?** A
small public reproducer or specification link is more useful than a feature
vote. There is also a consent-scoped pilot form for maintainers willing to test
an immutable public release candidate.

Repository: <REPOSITORY_URL>  
Rule catalog: <RULES_URL>  
Threat model: <THREAT_MODEL_URL>  
Pilot protocol: <PILOT_GUIDE_URL>

## Publication checklist

- [ ] Confirm the Python Packaging category's current announcement rules.
- [ ] Verify both artifacts and save a redacted example report.
- [ ] Have a Python packaging maintainer review the example's expected result.
- [ ] Verify the linked release, rule catalog, and threat model match the text.
- [ ] Replace every placeholder and remove this checklist from the post.
- [ ] State any observed false positive in the post instead of silently changing
  the example.
