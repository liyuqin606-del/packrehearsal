# PackRehearsal Release Gate WebUI

This directory contains the local-first Release Gate frontend for
PackRehearsal. Its visual hierarchy follows the release decision itself:
verdict, artifact identity, gate evidence, remediation, then a bounded Codex
maintenance brief.

![Desktop Release Gate](design-qa/desktop-1487x1058.png)

## Run locally

```bash
npm ci
npm run dev
```

Open `http://127.0.0.1:5173/`. The report/task contracts, production build,
and static hosting contract can be verified with:

```bash
npm test
npm run build
npm run test:sites
```

## Current scope

- Computer Modern typography: CMU Serif for the release verdict, CMU Sans
  Serif for interface text, and CMU Typewriter Text for hashes and rule IDs.
- Responsive desktop and mobile release-gate layouts.
- Local import of real PackRehearsal `report-v1` JSON with strict version,
  required-field, unknown-field, digest, fingerprint, and count validation.
- Honest idle, loading, invalid-report, empty-report, ready, and findings states.
- Real package, artifact, finding, location, fingerprint, and evidence rendering.
- Selection of non-baselined findings and deterministic generation of a
  root-schema-validated `codex-task-v1` JSON brief for copy or download.
- Browser-memory file reading only. Reports are not uploaded, project files are
  not read, and project code is not executed.
- No automatic edit, merge, publish, or release action.

The PackRehearsal CLI remains the source of truth. WebUI validation confirms the
document contract and internal counts, but does not authenticate its author or
independently rerun a scan. A valid report with no new findings deliberately
offers no Codex work.

## Import contract

Create a report without executing project code:

```bash
packrehearsal scan . --format json --no-fail > report-v1.json
```

Drop `report-v1.json` onto the import surface or use the file chooser. The file
is limited to 10 MB and parsed in browser memory. A finding present in
`baseline_fingerprints` remains visible as context but cannot be selected for a
new Codex task.

The design contract is recorded in [DESIGN.md](DESIGN.md), and visual QA is in
[design-qa.md](design-qa.md).
