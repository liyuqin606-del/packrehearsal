# Twelve-week maintenance roadmap

Status date: 2026-08-21. This is an execution plan, not a record of adoption or
completed outcomes. A checkbox may be marked complete only when its linked
artifact, issue, pull request, release, or measurement record is public and
reviewable.

## Status vocabulary

- **Shipped:** present on the default branch and verified by the named check.
- **In progress:** implementation exists but an acceptance gate remains open.
- **Planned:** no completion claim; timing may change after maintainer feedback.
- **Deferred:** deliberately excluded with a documented reason.

Targets such as “five pilots” remain targets until the public evidence ledger
contains five eligible entries. Stars, clones, page views, form submissions, and
unverified anecdotes are not counted as successful use.

## Phase 1 — maintenance entry points (weeks 1–2)

**Outcome:** a new maintainer can install, run, interpret, and report a problem
without disclosing private material.

- [x] Add separate forms for bugs, false positives, rule requests, and public
  repository pilots.
- [x] Add discussion forms for questions and release-workflow reports.
- [x] Document pilot consent, minimization, redaction, and publication approval.
- [x] Confirm GitHub Discussions is enabled and the `q-a` and `show-and-tell`
  categories exist (verified through the GitHub API on 2026-08-21).
- [ ] After these templates reach the default branch, confirm both discussion
  categories render their forms correctly.
- [ ] Set a GitHub homepage only after a stable public WebUI or documentation
  URL exists; until then, keep the repository as the canonical homepage.
- [ ] Run every documented install and scan command in clean Linux, macOS, and
  Windows environments; record workflow links.
- [ ] Add one minimal end-to-end example per supported ecosystem, each generated
  from redistributable source and containing both a passing and failing case.
- [ ] Decide package-index publication only after name ownership, provenance,
  rollback, and release instructions are independently checked.

**Exit gate:** all issue forms render; support links resolve; clean-install
evidence exists for each supported operating system; documentation does not
promise a package-index install path that has not been published.

## Phase 2 — real WebUI evidence path (weeks 3–5)

**Outcome:** the experimental UI consumes an actual report and exports a bounded
Codex task without uploading an artifact or pretending to fix code.

- [x] Import `report-v1` JSON through a local file picker and reject incompatible
  or malformed schema versions.
- [x] Render the report's package, artifact hash, finding, evidence, remediation,
  and rule ID rather than example-only values.
- [x] Export a schema-valid `codex-task-v1` document scoped to selected findings.
- [x] Make local-only behavior visible and test that no network request or
  project-code execution is introduced.
- [ ] Cover keyboard navigation, narrow and wide layouts, high zoom, empty
  reports, malformed input, unsupported schemas, and large-but-bounded reports.
- [ ] Publish a redacted diagnostic export that excludes artifact contents and
  workstation paths.

**Exit gate:** checked-in browser tests load a real CLI report, validate a task
against the repository schema, and prove malformed/unsupported inputs fail
closed. Until then, the UI remains explicitly labeled a preview.

## Phase 3 — real cases and rule quality (weeks 5–8)

**Outcome:** rule decisions are informed by authorized, reproducible release
cases instead of synthetic happy paths alone.

- [ ] Invite maintainers to submit public release candidates through the pilot
  form; do not scrape or scan unrelated projects for promotion.
- [ ] Complete up to ten pilots, aiming for at least three eligible external
  repositories across the supported ecosystems.
- [ ] Classify every result as accepted finding, disputed finding, false
  positive, missing rule, no finding, or inconclusive.
- [ ] Convert only minimized, redistributable reproductions into regression
  fixtures. Never copy a production archive into the repository.
- [ ] Give each confirmed false positive a public disposition: fixed, narrowed,
  documented, deferred with rationale, or not reproduced.
- [ ] Publish a named case only after the project representative approves the
  final draft; otherwise report only consented aggregate data.

**Exit gate:** at least three eligible pilot records exist, every reported
finding has a disposition, and at least one rule-quality change or explicit
no-change decision is backed by a minimal regression test. If no maintainers
volunteer, report that outcome rather than manufacturing cases.

## Phase 4 — measured Codex maintenance loop (weeks 6–10)

**Outcome:** evaluate whether bounded briefs help maintainers without granting
an agent merge or release authority.

- [ ] Register each task's scan ID, task ID, finding fingerprints, scope, and
  verification command before Codex starts.
- [ ] Record suggested files, changed files, maintainer disposition
  (`accepted`, `modified`, or `rejected`), test result, review minutes, and any
  scope violation in the [maintenance evidence ledger](MAINTENANCE_LEDGER.md).
- [ ] Include triage, documentation, tests, release preparation, and code fixes
  only when a real issue or finding justifies the work.
- [ ] Preserve no-op briefs outside the completed-task count; a brief with no
  selected findings must not be turned into invented cleanup.
- [ ] Stop and record the conflict if a suggested change weakens a rule,
  baseline, trust boundary, or verification requirement.
- [x] Publish the measurement method before publishing aggregate results.

**Exit gate:** ten eligible tasks are a target, not a quota. Report the actual
denominator, missing data, rejected suggestions, and scope violations. Human
review remains required for every merge and release.

## Phase 5 — technical content and community feedback (weeks 7–12)

**Outcome:** obtain specific engineering feedback without synchronized promotion
or inflated impact claims.

- [x] Prepare platform-specific drafts for the OpenAI Developer Community,
  Python Packaging, and Open Design/Show HN.
- [ ] Re-run every command and replace every draft placeholder immediately before
  publication.
- [ ] Publish sequentially, not simultaneously; incorporate feedback from one
  community before approaching the next.
- [ ] Ask one concrete question per post and respond to technical criticism.
- [ ] Record resulting issues, reproducible reports, and declined suggestions;
  do not use votes or stars as evidence of correctness.
- [ ] Publish a maintenance report containing actual counts, denominators,
  limitations, and links to the underlying public evidence.

**Exit gate:** at least one substantive feedback thread produces a reproducible
issue, documented design decision, or confirmed no-change decision. External
posting and publication remain manual maintainer actions.

## Weekly operating rhythm

| Cadence | Required action | Evidence |
|---|---|---|
| Weekly | Triage issues, false positives, dependency alerts, and security reports | Linked issue dispositions and workflow runs |
| Every two weeks | Review pilot and Codex-task ledgers for missing consent or measurements | Redacted ledger revision |
| Monthly | Publish a factual maintenance note, including zero-activity periods | Dated note with denominators |
| Every release | Run the full publishing checklist and verify downloaded assets | Release URL, checksums, attestations, clean-install result |
| Week 12 | Decide continue, narrow, or stop each experiment | Decision record with evidence and limitations |

## Pilot and community evidence index

Codex task outcomes use the versioned
[maintenance evidence ledger](MAINTENANCE_LEDGER.md). Pilot and community
records need a separate public index because they have consent and input fields
that are not Codex task outcomes. That index may be Markdown, CSV, or JSON, but
each row must include:

| Field | Meaning |
|---|---|
| `record_id` | Stable local identifier with no personal data |
| `record_type` | `pilot`, `finding`, `codex_task`, or `community_feedback` |
| `date` | Observation date, not publication date |
| `public_source` | Issue, discussion, commit, or workflow link when consent permits |
| `consent_scope` | `pilot_only`, `aggregate_only`, or `named_draft_approved` |
| `input_identity` | Public immutable commit/artifact plus digest, or `redacted` |
| `outcome` | Controlled category defined before analysis |
| `verification` | Test, rescan, reviewer decision, or reason verification was impossible |
| `limitations` | Missing data, ambiguity, and non-generalizable context |

Do not put emails, private paths, private source, raw archives, access tokens, or
unpublished vulnerability details in the public ledger.
