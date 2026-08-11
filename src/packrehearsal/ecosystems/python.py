"""Static Python ``pyproject.toml`` discovery using :mod:`tomllib`."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packrehearsal.models import Ecosystem, Finding, InternalDependency, Package

from .common import (
    ManifestParseError,
    find_readme,
    manifest_finding,
    read_toml_manifest,
    relative_path,
    repository_path,
    string_list,
    table,
)

_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")
_SPECIFIER_SPACE = re.compile(r"\s*(~=|===|==|!=|<=|>=|<|>)\s*")


@dataclass(frozen=True, slots=True)
class PythonDiscovery:
    packages: tuple[Package, ...]
    findings: tuple[Finding, ...]


def discover_python_packages(root: Path, manifests: Iterable[Path]) -> PythonDiscovery:
    """Parse Python project metadata without importing a build backend."""

    packages: list[Package] = []
    findings: list[Finding] = []
    for manifest in sorted(set(manifests), key=lambda item: relative_path(root, item)):
        try:
            package = parse_python_manifest(manifest, root)
        except ManifestParseError as exc:
            findings.append(manifest_finding(root, manifest, Ecosystem.PYTHON, exc.reason))
            continue
        if package is not None:
            packages.append(package)
    return PythonDiscovery(
        packages=tuple(sorted(packages, key=lambda item: (item.root, item.name))),
        findings=tuple(sorted(findings, key=lambda item: (item.location or "", item.message))),
    )


def parse_python_manifest(manifest: Path, root: Path) -> Package | None:
    """Parse PEP 621 metadata, with a conservative Poetry fallback."""

    data = read_toml_manifest(manifest)
    project = table(data.get("project"))
    poetry = table(table(data.get("tool")).get("poetry"))
    if not project and not poetry:
        return None

    source = project or poetry
    name = source.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ManifestParseError(manifest, "Python project name must be a non-empty string")

    dynamic = set(string_list(project.get("dynamic"))) if project else set()
    version_value = source.get("version")
    dynamic_version = "version" in dynamic and not isinstance(version_value, str)
    if dynamic_version:
        version = "<dynamic>"
    elif isinstance(version_value, str) and version_value.strip():
        version = version_value.strip()
    else:
        reason = f"Python project {name!r} has no static or dynamic version"
        raise ManifestParseError(manifest, reason)

    package_root = manifest.parent
    readme = _readme(root, package_root, source.get("readme")) or find_readme(root, package_root)
    license_expression, license_file = _license(root, package_root, source)
    expected_files = tuple(sorted({item for item in (readme, license_file) if item is not None}))

    metadata: dict[str, Any] = {"dynamic_version": dynamic_version}
    requires_python = project.get("requires-python")
    if isinstance(requires_python, str):
        metadata["requires_python"] = requires_python
    build_system = table(data.get("build-system"))
    if build_system:
        metadata["build_system"] = {
            key: value
            for key, value in build_system.items()
            if key in {"build-backend", "backend-path", "requires"}
        }
    if project:
        metadata["metadata_source"] = "pep621"
    else:
        metadata["metadata_source"] = "poetry"

    return Package(
        ecosystem=Ecosystem.PYTHON,
        name=name.strip(),
        version=version,
        root=relative_path(root, package_root),
        manifest=relative_path(root, manifest),
        license_expression=license_expression,
        readme=readme,
        entrypoints=_entrypoints(source),
        expected_files=expected_files,
        internal_dependencies=_dependencies(data, project, poetry),
        metadata=metadata,
    )


def canonical_python_name(name: str) -> str:
    """Normalize a distribution name according to PEP 503."""

    return re.sub(r"[-_.]+", "-", name.strip()).casefold()


def _dependencies(
    data: Mapping[str, Any],
    project: Mapping[str, Any],
    poetry: Mapping[str, Any],
) -> tuple[InternalDependency, ...]:
    result: set[InternalDependency] = set()
    if project:
        _add_requirement_list(result, project.get("dependencies"), "runtime")
        optional = table(project.get("optional-dependencies"))
        for extra, requirements in optional.items():
            if isinstance(extra, str):
                _add_requirement_list(result, requirements, f"optional:{extra}")
        groups = table(data.get("dependency-groups"))
        for group, requirements in groups.items():
            if isinstance(group, str):
                _add_requirement_list(result, requirements, f"group:{group}")
    elif poetry:
        poetry_sections = (
            ("dependencies", "runtime"),
            ("dev-dependencies", "development"),
        )
        for section_name, kind in poetry_sections:
            for dependency_name, constraint in table(poetry.get(section_name)).items():
                if not isinstance(dependency_name, str) or dependency_name.casefold() == "python":
                    continue
                requirement = _poetry_constraint(constraint)
                if requirement is not None:
                    result.add(
                        InternalDependency(
                            canonical_python_name(dependency_name), requirement, kind
                        )
                    )
        for group, group_data in table(poetry.get("group")).items():
            dependencies = table(table(group_data).get("dependencies"))
            for dependency_name, constraint in dependencies.items():
                if not isinstance(dependency_name, str):
                    continue
                requirement = _poetry_constraint(constraint)
                if requirement is not None:
                    result.add(
                        InternalDependency(
                            canonical_python_name(dependency_name),
                            requirement,
                            f"group:{group}",
                        )
                    )
    return tuple(sorted(result, key=lambda item: (item.kind, item.name, item.requirement)))


def _add_requirement_list(
    output: set[InternalDependency],
    value: Any,
    kind: str,
) -> None:
    for requirement in string_list(value):
        parsed = _pep508_dependency(requirement)
        if parsed is not None:
            name, specifier = parsed
            output.add(InternalDependency(name, specifier, kind))


def _pep508_dependency(value: str) -> tuple[str, str] | None:
    """Split a PEP 508 requirement into a canonical name and constraint.

    ``InternalDependency.requirement`` deliberately excludes the distribution
    name and extras.  Keeping only the version/direct-reference portion plus
    its marker lets workspace drift checks evaluate the constraint without
    mistaking the leading project name for a version.
    """

    match = _REQUIREMENT_NAME.match(value)
    if match is None:
        return None
    name = canonical_python_name(match.group(1))
    remainder = value[match.end() :].lstrip()

    if remainder.startswith("["):
        closing = remainder.find("]")
        if closing < 0:
            return None
        remainder = remainder[closing + 1 :].lstrip()

    constraint, separator, marker = remainder.partition(";")
    constraint = constraint.strip()
    if constraint.startswith("@"):
        constraint = constraint[1:].strip()
    if constraint.startswith("(") and constraint.endswith(")"):
        constraint = constraint[1:-1].strip()
    constraint = _SPECIFIER_SPACE.sub(r"\1", constraint)
    constraint = re.sub(r"\s*,\s*", ",", constraint)
    if not constraint:
        constraint = "*"

    if separator:
        normalized_marker = marker.strip()
        if normalized_marker:
            constraint = f"{constraint}; {normalized_marker}"
    return name, constraint


def _poetry_constraint(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, Mapping):
        for key in ("version", "path", "git", "url"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return f"{key}:{candidate}" if key != "version" else candidate
    return None


def _entrypoints(source: Mapping[str, Any]) -> tuple[str, ...]:
    result: set[str] = set()
    for section_name, prefix in (("scripts", "console"), ("gui-scripts", "gui")):
        for name, target in table(source.get(section_name)).items():
            if isinstance(name, str) and isinstance(target, str):
                result.add(f"{prefix}:{name}={target}")
    for group, entries in table(source.get("entry-points")).items():
        for name, target in table(entries).items():
            if isinstance(group, str) and isinstance(name, str) and isinstance(target, str):
                result.add(f"{group}:{name}={target}")
    return tuple(sorted(result))


def _readme(root: Path, package_root: Path, value: Any) -> str | None:
    if isinstance(value, str):
        return repository_path(root, package_root, value)
    if isinstance(value, Mapping) and isinstance(value.get("file"), str):
        return repository_path(root, package_root, value["file"])
    return None


def _license(
    root: Path,
    package_root: Path,
    source: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    expression = source.get("license-expression")
    if isinstance(expression, str):
        return expression, None
    value = source.get("license")
    if isinstance(value, str):
        return value, None
    if isinstance(value, Mapping):
        file_value = value.get("file")
        if isinstance(file_value, str):
            return None, repository_path(root, package_root, file_value)
        text_value = value.get("text")
        if isinstance(text_value, str):
            return text_value, None
    license_files = string_list(source.get("license-files"))
    if license_files:
        return None, repository_path(root, package_root, license_files[0])
    return None, None
