# Release Gate visual QA

## Source and target

- Reference: the user-selected PackRehearsal Release Gate image.
- Primary viewport: 1487 x 1058 CSS pixels.
- Responsive viewport: 390 x 844 CSS pixels.
- Typeface: Computer Modern through the OFL-licensed `computer-modern` package.
- Design method: Open Design `image-to-code-skill` for source analysis and
  `frontend-design` for implementation constraints.

## Fidelity checks

- The desktop header, release summary, artifact drop zone, 43.5/56.5 gate
  split, red/green gate states, evidence table, and single cobalt Codex action
  preserve the reference composition.
- The interface uses a flat paper field, one elevated evidence surface, thin
  dividers, and no decorative gradients or card grid.
- Serif, sans-serif, and typewriter roles are separated consistently.
- Phosphor icons replace text glyphs and improvised SVG icons.

## Interaction checks

- Gate selection switches between blocking and verified detail states.
- Gate definitions and individual evidence open read-only dialogs.
- The Codex brief opens, copies, and downloads as JSON.
- Local artifact selection computes SHA-256 with Web Crypto.
- Dialogs close from their named controls or backdrop.

## Responsive and runtime checks

- Desktop screenshot: [desktop-1487x1058.png](design-qa/desktop-1487x1058.png)
- Mobile screenshot: [mobile-390x844.png](design-qa/mobile-390x844.png)
- The mobile status strip wraps without horizontal overflow.
- Browser console: zero errors and warnings during the tested flows.
- `npm run build`: passed.
- `npm run test:sites`: 4 tests passed.

Result: **passed** for the current interaction-preview scope. CLI report import
remains explicitly out of scope for this preview.
