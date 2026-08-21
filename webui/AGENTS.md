# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## PackRehearsal visual target

- Source of truth: `/Users/yuqinli/.codex/generated_images/019ff099-3a09-7050-8edc-5bbefdf6b610/exec-fadde911-ad6f-49ac-975c-01e87dddb1a7.png`.
- Preserve the light Release Gate composition: top safety strip, release verdict,
  artifact drop zone, left gate list, right evidence surface, and one dominant
  Codex action.
- Use the Computer Modern Unicode family throughout: CMU Serif for display and
  prose, CMU Sans Serif for compact UI controls, and CMU Typewriter Text for
  hashes, rule IDs, commands, and evidence values.
- Use Phosphor icons. Do not substitute emoji, text glyphs, handcrafted SVG, or
  CSS drawings for visible icons.
