"""Static Python metadata and wheel layout checks."""

from __future__ import annotations

import configparser
import re
from collections.abc import Iterable
from pathlib import PurePosixPath

from packrehearsal.models import Ecosystem, Finding, RuleDescriptor, Severity
from packrehearsal.rules._utils import (
    load_toml_manifest,
    nested_mapping,
    package_uses_dynamic_version,
    package_version_for_validation,
)
from packrehearsal.rules.base import Rule, RuleContext


class PythonMetadataRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="python.invalid-metadata",
        title="Python package metadata is incomplete",
        description=(
            "Build metadata must provide a package name and a static or declared dynamic version."
        ),
        default_severity=Severity.HIGH,
        ecosystems=(Ecosystem.PYTHON,),
    )

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        manifest_name = PurePosixPath(context.package.manifest).name.lower()
        missing: list[str] = []
        error: str | None = None
        metadata_kind = manifest_name

        if manifest_name == "pyproject.toml":
            payload, error = load_toml_manifest(context)
            if payload is not None:
                project = nested_mapping(payload, "project")
                poetry = nested_mapping(payload, "tool", "poetry")
                if project is not None:
                    metadata_kind = "project"
                    if not _nonempty_string(project.get("name")):
                        missing.append("project.name")
                    dynamic = project.get("dynamic", ())
                    dynamic_version = isinstance(dynamic, list | tuple) and "version" in dynamic
                    if not _nonempty_string(project.get("version")) and not dynamic_version:
                        missing.append("project.version or project.dynamic=['version']")
                elif poetry is not None:
                    metadata_kind = "tool.poetry"
                    if not _nonempty_string(poetry.get("name")):
                        missing.append("tool.poetry.name")
                    if not _nonempty_string(poetry.get("version")):
                        missing.append("tool.poetry.version")
                else:
                    missing.append("project or tool.poetry table")
        elif manifest_name == "setup.cfg":
            metadata_kind = "setup.cfg [metadata]"
            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read_string(context.read_repository_text(context.manifest_path()))
            except (OSError, UnicodeError, configparser.Error) as exc:
                error = str(exc)
            else:
                if not parser.has_section("metadata"):
                    missing.append("[metadata]")
                else:
                    if not parser.get("metadata", "name", fallback="").strip():
                        missing.append("metadata.name")
                    if not parser.get("metadata", "version", fallback="").strip():
                        missing.append("metadata.version")
        elif manifest_name == "setup.py":
            # setup.py cannot be inspected reliably without executing project code.
            return
        else:
            return

        if error is not None:
            yield self.finding(
                context,
                message=f"Python metadata cannot be parsed safely: {error}",
                remediation="Repair the declarative package metadata and rerun discovery.",
                location=context.manifest_path(),
                evidence={"error": error, "manifest": context.manifest_path()},
            )
            return
        if missing:
            yield self.finding(
                context,
                message=f"Python metadata is missing: {', '.join(missing)}.",
                remediation=(
                    "Declare the project name and version (or dynamic version source) in build "
                    "metadata."
                ),
                location=context.manifest_path(),
                evidence={"metadata_kind": metadata_kind, "missing_fields": ",".join(missing)},
            )


class PythonDynamicVersionRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="python.dynamic-version-unresolved",
        title="Dynamic Python version is not resolved yet",
        description=(
            "PEP 621 dynamic versions can only be validated after artifact metadata is available."
        ),
        default_severity=Severity.LOW,
        ecosystems=(Ecosystem.PYTHON,),
    )

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        if not package_uses_dynamic_version(context):
            return
        version, source = package_version_for_validation(context)
        if version is not None:
            return
        yield self.finding(
            context,
            message=(
                "The manifest delegates its version, but no parsed artifact version is available."
            ),
            remediation=(
                "Build or provide a candidate artifact whose snapshot metadata contains the "
                "resolved package_version, then rerun the release checks."
            ),
            location=context.manifest_path(),
            evidence={
                "artifact": context.artifact.path if context.artifact is not None else "<none>",
                "manifest_version": context.package.version,
                "version_source": source,
            },
        )


class PythonWheelRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="python.invalid-wheel",
        title="Python wheel layout is invalid",
        description=(
            "A wheel must contain one matching dist-info directory and its required metadata files."
        ),
        default_severity=Severity.HIGH,
        ecosystems=(Ecosystem.PYTHON,),
    )

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        artifact = context.artifact
        if artifact is None or not (
            artifact.path.lower().endswith(".whl") or artifact.format.lower() in {"wheel", "whl"}
        ):
            return

        paths = tuple(
            sorted(
                path
                for entry in context.artifact_entries
                if entry.kind == "file"
                for path in context.artifact_relative_paths(entry)
            )
        )
        dist_info_roots = sorted(
            {
                part
                for path in paths
                for part in PurePosixPath(path).parts
                if part.endswith(".dist-info")
            }
        )
        missing_members: list[str] = []
        if len(dist_info_roots) == 1:
            dist_info = dist_info_roots[0]
            for filename in ("METADATA", "WHEEL", "RECORD"):
                if not any(path.endswith(f"{dist_info}/{filename}") for path in paths):
                    missing_members.append(filename)
        else:
            dist_info = "<none>" if not dist_info_roots else ",".join(dist_info_roots)

        problems: list[str] = []
        if len(dist_info_roots) != 1:
            problems.append(f"expected one .dist-info directory, found {len(dist_info_roots)}")
        if missing_members:
            problems.append(f"missing {', '.join(missing_members)}")

        resolved_version, version_source = package_version_for_validation(context)
        expected = "<dynamic-version-unresolved>"
        if resolved_version is not None:
            expected = (
                f"{_wheel_name(context.package.name)}-{_wheel_version(resolved_version)}.dist-info"
            )
            if len(dist_info_roots) == 1 and dist_info_roots[0].lower() != expected.lower():
                problems.append(f"dist-info {dist_info_roots[0]!r} does not match {expected!r}")

        filename_problem = _wheel_filename_problem(
            PurePosixPath(artifact.path).name,
            context.package.name,
            resolved_version,
        )
        if filename_problem is not None:
            problems.append(filename_problem)
        if not problems:
            return
        yield self.finding(
            context,
            message="Wheel validation failed: " + "; ".join(problems) + ".",
            remediation=(
                "Rebuild the wheel so its filename, dist-info directory, and required metadata "
                "agree."
            ),
            location=artifact.path,
            evidence={
                "artifact": artifact.path,
                "dist_info": dist_info,
                "expected_dist_info": expected,
                "missing_members": ",".join(missing_members) or "<none>",
                "version_source": version_source,
            },
        )


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _wheel_name(value: str) -> str:
    return re.sub(r"[-_.]+", "_", value.strip())


def _wheel_version(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "_", value.strip())


def _wheel_filename_problem(filename: str, name: str, version: str | None) -> str | None:
    if not filename.lower().endswith(".whl"):
        return "artifact filename does not end in .whl"
    parts = filename[:-4].split("-")
    if len(parts) not in {5, 6} or any(not item for item in parts):
        return (
            "wheel filename does not have distribution-version-[build]-python-abi-platform fields"
        )
    if parts[0].lower() != _wheel_name(name).lower():
        return f"wheel distribution {parts[0]!r} does not match package name"
    if version is not None and _wheel_version(parts[1]).lower() != _wheel_version(version).lower():
        return f"wheel version {parts[1]!r} does not match package version"
    return None


PYTHON_RULES = (PythonMetadataRule(), PythonDynamicVersionRule(), PythonWheelRule())
