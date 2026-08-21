# Contributing

PackRehearsal welcomes small, evidence-backed improvements. The project is
maintainer-led: opening a pull request does not guarantee that a feature will be
accepted, but every respectful report will receive a concrete disposition.

## Start with a problem

Choose the narrowest public intake form:

- [bug report](https://github.com/liyuqin606-del/packrehearsal/issues/new?template=bug.yml)
  for crashes, unsafe behavior, and incorrect CLI behavior;
- [false-positive report](https://github.com/liyuqin606-del/packrehearsal/issues/new?template=false-positive.yml)
  when a valid release candidate triggers a rule;
- [rule request](https://github.com/liyuqin606-del/packrehearsal/issues/new?template=rule.yml)
  for a new evidence-backed gate;
- [real-repository pilot](https://github.com/liyuqin606-del/packrehearsal/issues/new?template=real-repository-case.yml)
  to volunteer a public release candidate for measured testing.

For a new rule or ecosystem behavior, include:

1. the smallest public manifest or artifact that demonstrates the problem;
2. what a registry or package consumer does with it;
3. the evidence a deterministic rule can inspect;
4. likely false-positive cases;
5. a safe remediation.

Avoid adding rules that merely enforce personal style. A release-blocking rule
must show a broken consumer, missing required artifact, sensitive disclosure, or
another material release risk.

## Development

```bash
uv sync --extra dev
uv run ruff format --check .
uv run ruff check .
uv run mypy src/packrehearsal
uv run pytest --cov=packrehearsal --cov-branch
```

Tests must not access public registries. Use small, reviewable fixtures assembled
inside a temporary directory. Do not commit real credentials, production package
archives, copied private repositories, or generated dependency directories.

Real-repository reports are evidence, not an invitation to copy the project into
the test suite. Follow the consent and minimization process in
[`docs/community/PILOT_AND_CASE_STUDY_GUIDE.md`](docs/community/PILOT_AND_CASE_STUDY_GUIDE.md).

## Pull request expectations

- one focused change;
- tests covering positive, negative, and false-positive cases;
- deterministic output assertions where applicable;
- documentation for user-visible behavior;
- a threat-model note when the change reads archives or executes tools;
- no weakening of static-mode safety defaults;
- no undocumented breaking change to the 1.x CLI, exit codes, v1 schemas, or
  published rule IDs.

Human maintainers review and merge every change. AI-generated code is welcome
only when the contributor understands it, can explain it, and has verified its
license and behavior.

## Current roadmap and adding an ecosystem

The public maintenance sequence and acceptance gates are tracked in
[`docs/MAINTENANCE_ROADMAP.md`](docs/MAINTENANCE_ROADMAP.md). Roadmap targets are
not adoption claims; completed items require linked evidence.

New ecosystems are intentionally out of scope during the current 1.x
stabilization. A proposal needs at least two external maintainers willing to
test fixtures and review the rules.
