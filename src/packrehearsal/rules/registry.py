"""Deterministic registry and execution helpers for package rules."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from packrehearsal.models import Finding, RuleDescriptor
from packrehearsal.rules.base import Rule, RuleContext


class RuleRegistry:
    """A duplicate-safe registry ordered by stable rule ID."""

    def __init__(self, rules: Iterable[Rule] = ()) -> None:
        self._rules: dict[str, Rule] = {}
        for rule in rules:
            self.register(rule)

    def register(self, rule: Rule) -> Rule:
        rule_id = rule.descriptor.rule_id
        if rule_id in self._rules:
            raise ValueError(f"duplicate rule ID: {rule_id}")
        self._rules[rule_id] = rule
        return rule

    def get(self, rule_id: str) -> Rule:
        try:
            return self._rules[rule_id]
        except KeyError as exc:
            raise KeyError(f"unknown rule ID: {rule_id}") from exc

    def __contains__(self, rule_id: object) -> bool:
        return rule_id in self._rules

    def __iter__(self) -> Iterator[Rule]:
        yield from (self._rules[rule_id] for rule_id in sorted(self._rules))

    def __len__(self) -> int:
        return len(self._rules)

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(rule.descriptor.rule_id for rule in self)

    @property
    def descriptors(self) -> tuple[RuleDescriptor, ...]:
        return tuple(rule.descriptor for rule in self)

    def run(self, context: RuleContext) -> tuple[Finding, ...]:
        findings = [finding for rule in self for finding in rule.run(context)]
        return tuple(
            sorted(
                findings,
                key=lambda item: (
                    -item.severity.rank,
                    item.rule_id,
                    item.location or "",
                    item.fingerprint,
                ),
            )
        )


def deduplicate_findings(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    """Deduplicate findings from overlapping package roots by fingerprint."""

    unique = {finding.fingerprint: finding for finding in findings}
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                -item.severity.rank,
                item.rule_id,
                item.package or "",
                item.location or "",
                item.fingerprint,
            ),
        )
    )
