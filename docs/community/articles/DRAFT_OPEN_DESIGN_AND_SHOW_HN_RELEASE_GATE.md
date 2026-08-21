# DRAFT — Designing a local release gate that stops before the agent acts

**Targets:** Open Design “show your work”; later, a separately edited Show HN  
**Status:** Draft; do not publish without final review and a runnable public demo  
**Primary Open Design question:** Does the interface communicate evidence,
severity, and human authority without implying an automatic fix?  
**Primary Show HN question:** Can a maintainer reproduce the report-to-task flow
locally, and where does it fail?

> Publication note: Open Design and Show HN need different introductions; do not
> cross-post identical text. If the WebUI still contains example-only data, use
> only the Open Design process version and label it a preview. A Show HN launch
> requires real report import, task export, clean setup instructions, and a live
> verification pass on the public default branch.

## Shared technical article

Release tools usually show either a log or a pass/fail badge. I wanted the
PackRehearsal WebUI to expose a more reviewable chain:

```text
release artifact -> deterministic gate -> concrete evidence
                 -> bounded remediation brief -> human decision
```

The central screen is not a chatbot. It is a release-gate report. The left side
shows all gates and their status; the right side explains the selected finding,
source values, evidence, impact, and remediation. Preparing a Codex brief is a
separate final action. The interface never claims that preparing a brief fixes,
merges, or publishes anything.

### Why the hierarchy is deliberately asymmetric

The page gives the release decision the largest typographic weight, then the
artifact identity and hash, then the selected evidence. This order reflects the
maintainer's actual questions:

1. Is this candidate ready?
2. Which immutable bytes were inspected?
3. What exactly failed?
4. Can I verify the discrepancy without trusting generated prose?
5. What bounded work can I delegate, and what remains my responsibility?

Navigation and decoration are quieter. Blocking red is reserved for the failed
state and mismatched values. Passing green appears only beside checks backed by
the loaded report. The action color is blue so “prepare a brief” does not look
like either a failure or an automatic approval.

### Computer Modern in an operational interface

Computer Modern gives the release verdict and evidence view the tone of a
technical proof sheet rather than a generic administration dashboard. The risk
is obvious: a display face can become fragile at small sizes. The design keeps
long hashes, filenames, rule IDs, and structured evidence in a dedicated
monospace face; Computer Modern is used for hierarchy and readable prose, with
explicit fallbacks and layout tests required before release.

Typography must not be the only carrier of status. Gate numbers, text labels,
icons, borders, and semantic markup must remain understandable at high zoom,
with keyboard focus and reduced-motion behavior tested independently of the
visual style.

### The data boundary matters more than the screenshot

A polished mockup is not a working release gate. The publishable implementation
must load a real `report-v1` JSON document created by the CLI, reject an unknown
schema version, and render the report's actual artifact digest, rule IDs,
evidence, and remediation. It must export a schema-valid `codex-task-v1`
document scoped to the maintainer's selection.

All of this should happen locally in the browser. Importing a report must not
upload it, execute project code, extract an archive, or silently contact a
service. Malformed input, a report with no findings, and a large-but-bounded
report are first-class states rather than demo exceptions.

The WebUI also must not turn repository text into instructions. Evidence values
are rendered as data. The generated task carries explicit trust boundaries and
an exact rescan command; a human still reviews the diff and decides whether to
merge or release.

### What I would test before calling it a product

- a real CLI report imports on a clean checkout;
- invalid and incompatible JSON fails closed with an actionable message;
- export validates against the checked-in task schema;
- no network requests occur during import, review, or export;
- keyboard-only review reaches every gate, evidence view, and action;
- the layout survives narrow width, 200% zoom, long paths, and long hashes;
- an empty report produces a truthful no-op rather than invented maintenance;
- documentation labels any remaining example-only path as a preview.

This is also why the interface remains downstream of the scanner. A visual layer
can help a maintainer inspect evidence, but it cannot upgrade an unsupported
claim into a verified finding.

Repository: <REPOSITORY_URL>  
WebUI instructions: <WEBUI_URL>  
Schema and compatibility policy: <COMPATIBILITY_URL>  
Threat model: <THREAT_MODEL_URL>

PackRehearsal is community-maintained and is not affiliated with or endorsed by
OpenAI.

## Open Design introduction

I used a release-proof-sheet direction for this interface: Computer Modern for
editorial hierarchy, monospace for evidence, a restrained safety palette, and a
two-column gate-to-proof flow. I am sharing the design process before treating
the screenshot as product evidence.

The question I would like design feedback on is: **without reading the copy in
detail, does this screen make it clear that “prepare a Codex brief” is a bounded
handoff, not an automatic fix or approval?** I would especially value feedback
on hierarchy at laptop width, keyboard focus order, and how to show malformed or
empty reports without collapsing into nested cards.

Before posting, include: <BEFORE_IMAGE>, <AFTER_IMAGE>, viewport sizes tested,
and a short list of changes made in response to the design process.

## Show HN introduction — use only after the runnable gate passes

**Proposed title:** Show HN: PackRehearsal – inspect package artifacts before
Codex fixes them

PackRehearsal is a local-first release gate for Python, npm, and Rust. The CLI
compares manifests with the bytes that will ship; the WebUI lets you inspect a
real JSON report and export a bounded Codex maintenance task. Static inspection
does not execute project code, contact a registry, upload the report, or merge a
change.

Try it with the immutable release and sample at <RUNNABLE_DEMO_URL>. My main
question is: **can you reproduce the report-to-task path, and which assumption
breaks on your package format or release workflow?** Known limitations:
<CURRENT_LIMITATIONS>.

## Publication checklist

- [ ] Choose one target and delete the other target's introduction.
- [ ] Confirm real report import and schema-valid task export on the default
  branch; otherwise label the post an Open Design preview and do not Show HN.
- [ ] Run setup on a clean machine without private caches or credentials.
- [ ] Inspect browser network activity during the complete local flow.
- [ ] Test keyboard navigation, 200% zoom, narrow viewport, long values, empty
  report, and malformed JSON.
- [ ] Replace every placeholder with public evidence.
- [ ] Verify current community rules, disclose authorship, and do not request or
  coordinate votes.
