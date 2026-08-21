# DRAFT — Put deterministic release evidence before a Codex repair

**Target:** OpenAI Developer Community, Codex category  
**Status:** Draft; do not publish without a maintainer's final review  
**Primary question:** Where does this evidence-to-agent boundary fail in a real
maintenance workflow?

> Publication note: rerun every command, replace all angle-bracket placeholders,
> verify the current release URL, and link a public example report before posting.
> Do not add adoption, accuracy, or time-saved claims without a dated public
> measurement ledger.

## Draft post

An agent can edit a release configuration quickly, but it should not get to
decide what the release problem was. Package repositories contain prose,
generated files, filenames, and metadata controlled by many authors. If all of
that is poured into a free-form prompt, scope and evidence become difficult to
review.

I am building PackRehearsal, an Apache-2.0 release-assurance CLI for Python,
npm, and Rust. Its Codex integration is deliberately split into three stages:

1. a deterministic scanner compares manifests with the exact archive bytes
   intended for publication;
2. `codex-brief` serializes only selected findings and their verification
   command into a bounded work order;
3. a human reviews the suggested patch, reruns the scanner, and decides whether
   to merge or release.

The scanner, not Codex, owns rule evaluation. The default scan does not execute
project code, import the inspected package, contact a registry, extract the
archive, or call an OpenAI API.

### A reproducible maintenance task

Given an existing artifact from a trusted release process:

```bash
packrehearsal scan . \
  --artifact dist/example-1.2.3-py3-none-any.whl \
  --format json \
  --output packrehearsal-report.json

packrehearsal codex-brief . \
  --artifact dist/example-1.2.3-py3-none-any.whl \
  --minimum-severity low \
  --format json \
  --output codex-maintenance-task.json
```

The task records the originating scan ID, artifact hash, rule IDs, stable
finding fingerprints, evidence, remediation, and an exact verification command.
Repository-derived strings are carried as untrusted data. The work order also
says what Codex cannot do: weaken a rule, edit a baseline to hide a finding,
make unrelated changes, merge, or publish.

That gives the maintainer a compact contract:

```text
finding fingerprint -> bounded files and remediation -> proposed diff
                    -> same verification command -> human disposition
```

If the selected scan has no findings, the generated task says
`no_changes_requested`. That no-op matters: an assistant should not manufacture
cleanup work just because it was invoked.

### Why use an artifact boundary?

A repository can look correct while the release archive omits a console-script
module, excludes a README or license, identifies a different version, or ships
an unexpected file. Reviewing only source configuration misses the object users
actually install. PackRehearsal reads bounded ZIP/TAR structure and metadata
without extracting the archive, then relates those bytes back to the manifest.

The output is evidence, not a security certificate. A receipt binds hashes for
offline consistency but is not proof of authorship. The opt-in `rehearse`
command is also a different trust boundary: building a package may execute
project code, so it requires explicit acknowledgement and is not described as
an operating-system sandbox.

### Measuring whether Codex helps

I do not want to infer usefulness from stars, generated lines, or how quickly a
patch appears. The proposed pilot records, per real task:

- scan ID, task ID, and selected finding fingerprints;
- files Codex proposed and files it actually changed;
- maintainer disposition: accepted, modified, or rejected;
- rescan and test outcome;
- human review minutes and any out-of-scope action.

No-op briefs are preserved as evidence but are not turned into completed
maintenance tasks.

Only public, authorized release candidates are eligible. Named case studies
need final approval from the project representative, and negative or no-op
results remain in the denominator.

### Feedback requested

I would value one specific kind of feedback: **what evidence or control is
missing before you would hand one release finding to Codex in a repository you
maintain?** Examples might be tighter file scope, a different verification
contract, provenance for the input artifact, or a clearer stop condition.

Repository: <REPOSITORY_URL>  
Pinned release/install instructions: <RELEASE_URL>  
Codex workflow: <CODEX_WORKFLOW_URL>  
Pilot protocol: <PILOT_GUIDE_URL>

PackRehearsal is community-maintained and is not affiliated with or endorsed by
OpenAI.

## Publication checklist

- [ ] Install the linked immutable release in a clean environment.
- [ ] Run both commands above and link the redacted output.
- [ ] Verify the task against `schemas/codex-task-v1.schema.json`.
- [ ] Confirm the current default branch still enforces all described safety
  boundaries.
- [ ] Replace every placeholder and remove this checklist from the post.
- [ ] Ask only the primary technical question; do not request stars or votes.
