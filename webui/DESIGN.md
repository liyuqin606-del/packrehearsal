# PackRehearsal Release Gate design system

## Direction

Pristine light editorial release tooling: calm, exact, and evidence-led. The
interface should feel closer to a carefully typeset technical review than a
generic SaaS dashboard.

## Color

- Paper: `#fffdf9`; surface: `#ffffff`; divider: `#e5e1dc`.
- Primary ink: `#0c1a4b`; muted ink: `#68708a`.
- Primary action only: cobalt `#0628c9`, hover `#001ea7`.
- Blocking status: red `#e51b22` on `#fff4f1`.
- Passed status: green `#187844` on `#edf8f0`.
- No gradients. Shadows are reserved for the selected evidence surface and
  dialogs.

## Typography

- Display and prose: `CMU Serif`.
- Navigation, controls, table labels: `CMU Sans Serif`.
- Hashes, rule IDs, commands, artifact metadata: `CMU Typewriter Text`.
- Keep body text at 14–16 px with comfortable 1.35–1.5 line height. Use the
  display serif at 48–64 px for the release verdict.

## Layout

- Desktop reference viewport: 1487 × 1058.
- 26 px page gutters, 68 px header, 155 px release summary, 58 px drop zone.
- Main workspace: 43.5% gate list / 56.5% evidence, separated by one divider.
- At 820 px and below, stack the release summary and workspace vertically.
- Prefer alignment and whitespace over nested cards.

## Components

- Safety states are compact outline controls in the header.
- Release gates are flat rows with a numbered status circle; only the selected
  blocking gate receives a tinted surface and left rule.
- The evidence panel is the single elevated surface.
- The only dominant action is `Prepare Codex fix brief`.
- Visible icons come from Phosphor Icons.

## Interaction

- Gate rows are keyboard-selectable and update the evidence panel. Their task
  checkboxes are separate controls with valid keyboard semantics.
- The drop zone imports `report-v1` JSON with drag/drop or browse, then displays
  local loading, contract error, empty, ready, or findings states.
- Evidence rows open read-only detail.
- Only non-baselined findings can be selected. The Codex action opens a
  deterministic `codex-task-v1` preview with copy and download actions.
- Validation is described precisely: it checks shape and internal counts, not
  authorship, provenance, or a rerun of the scan.
- Provide visible focus, hover, active, loading, success, and passed states.
