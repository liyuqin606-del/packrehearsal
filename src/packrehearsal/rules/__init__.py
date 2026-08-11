"""Built-in rule catalog and engine-facing execution API.

Typical engine use::

    context = RuleContext(
        root=root,
        package=package,
        packages=all_packages,
        repository_files=repository_files,
        artifact=artifact_for_package,
        config=config,
    )
    findings = run_rules(context)

Run once per package. Passing ``all_packages`` lets repository rules attribute
nested files to the deepest package root. Engines that intentionally scan
overlapping roots can call :func:`deduplicate_findings` on the combined output.
"""

from __future__ import annotations

from packrehearsal.models import Finding
from packrehearsal.rules.base import Rule, RuleContext
from packrehearsal.rules.common import COMMON_RULES
from packrehearsal.rules.npm import NPM_RULES
from packrehearsal.rules.python import PYTHON_RULES
from packrehearsal.rules.registry import RuleRegistry, deduplicate_findings
from packrehearsal.rules.rust import RUST_RULES

BUILTIN_RULES = (*COMMON_RULES, *NPM_RULES, *PYTHON_RULES, *RUST_RULES)


def default_registry() -> RuleRegistry:
    """Return an independent registry containing all built-in rules."""

    return RuleRegistry(BUILTIN_RULES)


def run_rules(context: RuleContext, registry: RuleRegistry | None = None) -> tuple[Finding, ...]:
    """Run enabled rules for one package and apply configuration overrides."""

    selected = registry if registry is not None else default_registry()
    return selected.run(context)


__all__ = [
    "BUILTIN_RULES",
    "Rule",
    "RuleContext",
    "RuleRegistry",
    "deduplicate_findings",
    "default_registry",
    "run_rules",
]
