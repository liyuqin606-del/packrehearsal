"""Static checks for npm package manifests and packed entrypoints."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from packrehearsal.models import Ecosystem, Finding, RuleDescriptor, Severity
from packrehearsal.rules._utils import (
    candidates_exist,
    declared_path_candidates,
    load_json_manifest,
)
from packrehearsal.rules.base import Rule, RuleContext


class NpmManifestRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="npm.invalid-manifest",
        title="package.json is invalid",
        description="npm metadata must be a readable JSON object before publishing.",
        default_severity=Severity.HIGH,
        ecosystems=(Ecosystem.NPM,),
    )

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        _manifest, error = load_json_manifest(context)
        if error is None:
            return
        yield self.finding(
            context,
            message=f"The npm manifest cannot be read safely: {error}",
            remediation="Repair package.json and rerun package discovery before publishing.",
            location=context.manifest_path(),
            evidence={"error": error, "manifest": context.manifest_path()},
        )


class NpmMainRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="npm.invalid-main",
        title="npm main entry is invalid",
        description="The package.json main field must resolve to a file in source and the tarball.",
        default_severity=Severity.HIGH,
        ecosystems=(Ecosystem.NPM,),
    )

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        manifest, error = load_json_manifest(context)
        if error is not None or manifest is None or "main" not in manifest:
            return
        value = manifest.get("main")
        yield from _check_declared_path(self, context, field="main", value=value, kind="main")


class NpmTypesRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="npm.invalid-types",
        title="npm type declaration entry is invalid",
        description=(
            "types, typings, and conditional export type paths must resolve to declarations."
        ),
        default_severity=Severity.HIGH,
        ecosystems=(Ecosystem.NPM,),
    )

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        manifest, error = load_json_manifest(context)
        if error is not None or manifest is None:
            return
        declarations: list[tuple[str, object]] = []
        for key in ("types", "typings"):
            if key in manifest:
                declarations.append((key, manifest.get(key)))
        declarations.extend(
            ("exports.types", item) for item in _export_type_paths(manifest.get("exports"))
        )
        for field, value in declarations:
            yield from _check_declared_path(self, context, field=field, value=value, kind="types")


class NpmBinRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="npm.invalid-bin",
        title="npm executable entry is invalid",
        description="Each package.json bin path must resolve to a packaged file.",
        default_severity=Severity.HIGH,
        ecosystems=(Ecosystem.NPM,),
    )

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        manifest, error = load_json_manifest(context)
        if error is not None or manifest is None or "bin" not in manifest:
            return
        value = manifest.get("bin")
        if isinstance(value, str):
            entries: tuple[tuple[str, object], ...] = ((context.package.name, value),)
        elif isinstance(value, Mapping):
            entries = tuple(sorted((str(name), path) for name, path in value.items()))
            if not entries:
                yield self.finding(
                    context,
                    message="The package.json bin mapping is empty.",
                    remediation=(
                        "Remove the bin field or map at least one command name to an executable "
                        "file."
                    ),
                    location=context.manifest_path(),
                    evidence={"field": "bin", "value_type": "empty mapping"},
                )
                return
        else:
            yield self.finding(
                context,
                message=(
                    "The package.json bin field must be a path string or command-to-path mapping."
                ),
                remediation=(
                    "Set bin to a package-relative file path or an object of command paths."
                ),
                location=context.manifest_path(),
                evidence={"field": "bin", "value_type": type(value).__name__},
            )
            return

        for command, path in entries:
            if not command.strip():
                yield self.finding(
                    context,
                    message="The package.json bin mapping contains an empty command name.",
                    remediation="Give every executable a non-empty command name.",
                    location=context.manifest_path(),
                    evidence={"command": "<empty>", "field": "bin"},
                )
                continue
            yield from _check_declared_path(
                self,
                context,
                field=f"bin.{command}",
                value=path,
                kind="bin",
            )


def _check_declared_path(
    rule: Rule,
    context: RuleContext,
    *,
    field: str,
    value: object,
    kind: str,
) -> Iterable[Finding]:
    if not isinstance(value, str) or not value.strip():
        yield rule.finding(
            context,
            message=f"package.json field {field!r} must contain a non-empty path string.",
            remediation=f"Set {field} to a package-relative {kind} file path or remove the field.",
            location=context.manifest_path(),
            evidence={"field": field, "value_type": type(value).__name__},
        )
        return
    candidates = declared_path_candidates(Ecosystem.NPM, value, kind=kind)
    if not candidates:
        yield rule.finding(
            context,
            message=f"package.json field {field!r} contains an unsafe path {value!r}.",
            remediation="Use a package-relative path that does not traverse outside the package.",
            location=context.manifest_path(),
            evidence={"field": field, "path": value, "reason": "unsafe path"},
        )
        return
    exists, missing = candidates_exist(context, candidates)
    if exists:
        return
    yield rule.finding(
        context,
        message=(
            f"package.json field {field!r} points to {value!r}, missing from {', '.join(missing)}."
        ),
        remediation=f"Build and include the declared {kind} file, or correct the {field} path.",
        location=context.manifest_path(),
        evidence={
            "candidates": ",".join(candidates),
            "field": field,
            "missing_from": ",".join(missing),
            "path": value,
        },
    )


def _export_type_paths(value: object) -> tuple[str, ...]:
    result: list[str] = []

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if key == "types" and isinstance(nested, str):
                    result.append(nested)
                else:
                    visit(nested)
        elif isinstance(item, list | tuple):
            for nested in item:
                visit(nested)

    visit(value)
    return tuple(sorted(set(result)))


NPM_RULES = (NpmManifestRule(), NpmMainRule(), NpmTypesRule(), NpmBinRule())
