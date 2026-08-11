# Contributing

PackRehearsal welcomes small, evidence-backed improvements. The project is
maintainer-led: opening a pull request does not guarantee that a feature will be
accepted, but every respectful report will receive a concrete disposition.

## Start with a problem

For a new rule or ecosystem behavior, open an issue containing:

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
uv run ruff check .
uv run mypy
uv run pytest --cov
```

Tests must not access public registries. Use small, reviewable fixtures assembled
inside a temporary directory. Do not commit real credentials, production package
archives, copied private repositories, or generated dependency directories.

## Pull request expectations

- one focused change;
- tests covering positive, negative, and false-positive cases;
- deterministic output assertions where applicable;
- documentation for user-visible behavior;
- a threat-model note when the change reads archives or executes tools;
- no weakening of static-mode safety defaults.

Human maintainers review and merge every change. AI-generated code is welcome
only when the contributor understands it, can explain it, and has verified its
license and behavior.

## Adding an ecosystem

New ecosystems are intentionally out of scope for v0.1. A proposal needs at
least two external maintainers willing to test fixtures and review the rules.
