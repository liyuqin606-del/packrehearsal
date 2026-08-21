# Public pilot and case-study guide

PackRehearsal invites maintainers to test public release candidates. A pilot is
a bounded technical evaluation, not proof of adoption, endorsement, package
safety, or security review. No project is named in a case study without a second,
explicit approval of the final draft.

## Eligible inputs

An eligible pilot has all of the following:

1. a public repository and an immutable public commit or tag;
2. a public release artifact or reproducible instructions for creating a small
   synthetic artifact;
3. a reporter who states their relationship to the project and authority to
   share the links;
4. an exact PackRehearsal version, command, and question;
5. no credentials, private source, personal data, or undisclosed vulnerability.

Do not build or execute code from an unreviewed fork. Static inspection accepts
an existing artifact and does not need project execution. If a package must be
built, the project maintainer should build it in their trusted release
environment and provide the already-public artifact or a minimized synthetic
reproducer.

## Consent choices

The reporter chooses one initial scope in the pilot form:

| Scope | What may be retained publicly | What is prohibited |
|---|---|---|
| Pilot only | Issue text, public links, redacted technical disposition | Named article, quote, adoption claim, aggregate use |
| Aggregate only | Above plus a de-identified count in a defined aggregate | Project name, identifying quote, repository screenshot |
| Open to named draft | Above plus preparation of a named draft for review | Publication before final written approval |

Consent is purpose-specific. Permission to inspect a public artifact does not
grant permission to change its repository, quote a maintainer, use its logo, or
call it a PackRehearsal user. A reporter may narrow or withdraw publication
permission before publication; the factual public issue history may remain under
GitHub's normal retention rules.

## Pilot procedure

### 1. Freeze the input

Record the immutable commit/tag, artifact filename, SHA-256 digest, tool version,
configuration, and exact command. If an identity cannot be made public, record
`redacted` and exclude the pilot from reproducibility claims.

### 2. Minimize data

- Inspect only files required by the selected rules.
- Prefer generated reproductions over copied production archives.
- Replace workstation paths and usernames with neutral placeholders.
- Do not retain archive contents after analysis unless their redistribution
  terms and the reporter's permission are documented.
- Move a suspected vulnerability to private reporting and stop the public pilot.

### 3. Run and classify

Record every outcome, including zero findings and tool failures. Use only these
predeclared categories:

- `accepted_finding`: the project representative agrees the evidence identifies
  a release problem;
- `disputed_finding`: evidence or impact remains contested;
- `false_positive`: the release is valid and the rule boundary is too broad;
- `missing_rule`: a concrete release failure is not detected;
- `no_finding`: the selected checks report nothing actionable;
- `inconclusive`: input, consent, or verification is insufficient.

Do not silently remove false positives or count multiple findings from one scan
as multiple successful pilots.

### 4. Verify a disposition

A code or metadata change is verified only when the same pinned command is
rerun against a new immutable input and the targeted fingerprint disappears
without an unacceptable new finding. A baseline or disabled rule is not, by
itself, a fix. Human maintainers decide whether any change is merged or released.

### 5. Review before publication

Send a named case-study draft to the authorized project representative. The
approval request must enumerate the project name, quoted words, screenshots,
artifact identities, findings, metrics, and intended publication venues. Record
approval in the public issue or another auditable channel before publishing.

## Redaction checklist

Before posting an issue, report, screenshot, or article, remove:

- tokens, cookies, credentials, signing material, and private registry URLs;
- emails, usernames unrelated to public authorship, local home directories, and
  machine names;
- private repository names, internal package scopes, unreleased versions, and
  embargoed vulnerability details;
- unrelated source files and full archive member lists when a minimal excerpt is
  sufficient;
- Codex prompts or outputs containing repository text outside the accepted
  finding scope.

Keep rule IDs, finding fingerprints, artifact digests, exact commands, and
verification results when they are safe to publish; these make the technical
claim auditable.

## Metrics that may be reported

Report counts with denominators and a fixed observation window. Suitable fields
include pilots started/completed, artifacts scanned, findings by disposition,
false-positive reports, missing-rule reports, time-to-disposition, and Codex
suggestions accepted/modified/rejected. Codex task measurements follow the
[maintenance evidence ledger](../MAINTENANCE_LEDGER.md). Report missing
measurements explicitly.

Do not infer time saved from commit timestamps, equate stars or page views with
adoption, or describe a project as protected, certified, secure, or endorsed.
Comparisons need the same task scope and measurement method.

## Maintainer response template

```text
Pilot record: PRP-YYYY-NNN
Input: <public immutable reference and SHA-256, or redacted>
PackRehearsal version and command: <exact values>
Consent scope: <pilot_only | aggregate_only | named_draft_approved>
Observed findings: <rule IDs and fingerprints, including zero>
Disposition: <accepted_finding | disputed_finding | false_positive |
              missing_rule | no_finding | inconclusive>
Verification: <rescan/test/reviewer evidence>
Data retained: <minimal public material>
Limitations: <what this case cannot establish>
Publication status: <not proposed | draft pending review | approved with link>
```

Open a [real repository pilot](https://github.com/liyuqin606-del/packrehearsal/issues/new?template=real-repository-case.yml)
only after reviewing this guide.
