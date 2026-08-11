"""Static Cargo manifest and package inclusion checks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from packrehearsal.models import Ecosystem, Finding, RuleDescriptor, Severity
from packrehearsal.rules._utils import any_path_matches, load_toml_manifest, nested_mapping
from packrehearsal.rules.base import Rule, RuleContext, join_relative, normalize_relative_path


class RustManifestRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="rust.invalid-manifest",
        title="Cargo.toml is invalid",
        description="Cargo package metadata must be parseable without executing project code.",
        default_severity=Severity.HIGH,
        ecosystems=(Ecosystem.RUST,),
    )

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        payload, error = load_toml_manifest(context)
        if error is None and nested_mapping(payload, "package") is not None:
            return
        reason = error or "missing [package] table"
        yield self.finding(
            context,
            message=f"Cargo manifest validation failed: {reason}.",
            remediation=(
                "Repair Cargo.toml and ensure the discovered manifest contains a [package] table."
            ),
            location=context.manifest_path(),
            evidence={"manifest": context.manifest_path(), "reason": reason},
        )


class RustIncludeRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="rust.invalid-include",
        title="Cargo include list is invalid",
        description="Positive Cargo include patterns should be safe and match package files.",
        default_severity=Severity.MEDIUM,
        ecosystems=(Ecosystem.RUST,),
    )

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        package, _workspace, error = _cargo_tables(context)
        if error is not None or package is None or "include" not in package:
            return
        value = package.get("include")
        if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
            yield self.finding(
                context,
                message="Cargo package.include must be an array of string patterns.",
                remediation=(
                    "Replace package.include with a non-empty array of package-relative patterns."
                ),
                location=context.manifest_path(),
                evidence={"field": "package.include", "value_type": type(value).__name__},
            )
            return

        positive = tuple(item for item in value if not item.startswith("!"))
        if not positive:
            yield self.finding(
                context,
                message="Cargo package.include contains no positive patterns.",
                remediation=(
                    "Add at least one positive include pattern for source and metadata files."
                ),
                location=context.manifest_path(),
                evidence={"patterns": ",".join(value) or "<empty>"},
            )
            return
        for pattern in positive:
            normalized = pattern.lstrip("/")
            try:
                normalized = normalize_relative_path(normalized)
            except ValueError:
                yield self.finding(
                    context,
                    message=f"Cargo include pattern {pattern!r} traverses outside the package.",
                    remediation="Use package-relative include patterns without parent traversal.",
                    location=context.manifest_path(),
                    evidence={"pattern": pattern, "reason": "unsafe path"},
                )
                continue
            if any_path_matches(context.package_files, (normalized,)):
                continue
            yield self.finding(
                context,
                message=f"Cargo include pattern {pattern!r} matches no discovered package file.",
                remediation=(
                    "Correct or remove the stale include pattern before publishing the crate."
                ),
                location=context.manifest_path(),
                evidence={"package_file_count": len(context.package_files), "pattern": pattern},
            )


class RustLicenseRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="rust.invalid-license",
        title="Cargo license metadata is invalid",
        description="A crate must declare a license expression or a real license-file.",
        default_severity=Severity.HIGH,
        ecosystems=(Ecosystem.RUST,),
    )

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        package, workspace_package, error = _cargo_tables(context)
        if error is not None or package is None:
            return
        license_value = _workspace_value(package.get("license"), workspace_package, "license")
        license_file = _workspace_value(
            package.get("license-file"), workspace_package, "license-file"
        )
        if license_value is _UNRESOLVED or license_file is _UNRESOLVED:
            yield self.finding(
                context,
                message=(
                    "Cargo license metadata inherits from a workspace value that cannot be "
                    "resolved."
                ),
                remediation=(
                    "Declare workspace.package license metadata in the workspace Cargo.toml."
                ),
                location=context.manifest_path(),
                evidence={
                    "field": "package.license/license-file",
                    "reason": "unresolved workspace inheritance",
                },
            )
            return

        if _nonempty_string(license_value) or _nonempty_string(context.package.license_expression):
            return
        if _nonempty_string(license_file):
            assert isinstance(license_file, str)
            try:
                normalized = normalize_relative_path(license_file)
            except ValueError:
                normalized = ""
            if normalized and context.repo_has_file(normalized):
                return
            yield self.finding(
                context,
                message=f"Cargo license-file {license_file!r} does not exist in the package.",
                remediation="Add the declared license file or correct package.license-file.",
                location=context.manifest_path(),
                evidence={"field": "package.license-file", "path": license_file},
            )
            return
        yield self.finding(
            context,
            message="Cargo metadata declares neither package.license nor package.license-file.",
            remediation="Add a valid SPDX expression or a package-relative license-file path.",
            location=context.manifest_path(),
            evidence={"license": "<none>", "license_file": "<none>"},
        )


class RustReadmeRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="rust.invalid-readme",
        title="Cargo readme metadata is invalid",
        description="An explicitly declared Cargo readme must be a real package file.",
        default_severity=Severity.MEDIUM,
        ecosystems=(Ecosystem.RUST,),
    )

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        package, workspace_package, error = _cargo_tables(context)
        if error is not None or package is None or "readme" not in package:
            return
        value = _workspace_value(package.get("readme"), workspace_package, "readme")
        if value is _UNRESOLVED:
            yield self.finding(
                context,
                message="Cargo readme inherits from an unresolved workspace.package.readme value.",
                remediation="Declare workspace.package.readme or set a package-local readme path.",
                location=context.manifest_path(),
                evidence={"field": "package.readme", "reason": "unresolved workspace inheritance"},
            )
            return
        if value is False:
            return
        if not _nonempty_string(value):
            yield self.finding(
                context,
                message="Cargo package.readme must be a non-empty path string or false.",
                remediation=(
                    "Point package.readme at a real README file or set it to false intentionally."
                ),
                location=context.manifest_path(),
                evidence={"field": "package.readme", "value_type": type(value).__name__},
            )
            return
        assert isinstance(value, str)
        try:
            normalized = normalize_relative_path(value)
        except ValueError:
            normalized = ""
        if normalized and context.repo_has_file(normalized):
            return
        yield self.finding(
            context,
            message=f"Cargo readme path {value!r} does not exist in the package.",
            remediation="Add the README file or correct package.readme before packaging.",
            location=context.manifest_path(),
            evidence={"field": "package.readme", "path": value},
        )


_UNRESOLVED = object()


def _cargo_tables(
    context: RuleContext,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None, str | None]:
    payload, error = load_toml_manifest(context)
    if payload is None:
        return None, None, error
    package = nested_mapping(payload, "package")
    workspace_package = nested_mapping(payload, "workspace", "package")
    if context.workspace_root is not None and context.workspace_root != context.package_root:
        workspace_manifest = join_relative(context.workspace_root, "Cargo.toml")
        try:
            import tomllib

            workspace_payload = tomllib.loads(context.read_repository_text(workspace_manifest))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            pass
        else:
            workspace_package = nested_mapping(workspace_payload, "workspace", "package")
    return package, workspace_package, error


def _workspace_value(
    value: object,
    workspace_package: Mapping[str, Any] | None,
    key: str,
) -> object:
    if isinstance(value, Mapping) and value.get("workspace") is True:
        if workspace_package is None or key not in workspace_package:
            return _UNRESOLVED
        return workspace_package.get(key)
    return value


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


RUST_RULES = (RustManifestRule(), RustIncludeRule(), RustLicenseRule(), RustReadmeRule())
