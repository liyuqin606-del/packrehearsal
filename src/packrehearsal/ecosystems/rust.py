"""Static Cargo manifest and workspace discovery."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Any

from packrehearsal.models import Ecosystem, Finding, InternalDependency, Package

from .common import (
    ManifestParseError,
    ParsedManifest,
    find_readme,
    manifest_finding,
    read_toml_manifest,
    relative_path,
    repository_path,
    string_list,
    table,
)


@dataclass(frozen=True, slots=True)
class RustDiscovery:
    packages: tuple[Package, ...]
    findings: tuple[Finding, ...]


def discover_rust_packages(root: Path, manifests: Iterable[Path]) -> RustDiscovery:
    """Parse Cargo packages and resolve explicit workspace inheritance."""

    parsed: list[ParsedManifest] = []
    findings: list[Finding] = []
    for manifest in sorted(set(manifests), key=lambda item: relative_path(root, item)):
        try:
            parsed.append(ParsedManifest(manifest, read_toml_manifest(manifest)))
        except ManifestParseError as exc:
            findings.append(manifest_finding(root, manifest, Ecosystem.RUST, exc.reason))

    workspace_roots = [item for item in parsed if table(item.data.get("workspace"))]
    packages: list[Package] = []
    for item in parsed:
        workspace = _nearest_workspace(root, item.path, workspace_roots)
        try:
            package = _package_from_data(
                item.path,
                root,
                item.data,
                workspace_root=workspace.path.parent if workspace is not None else None,
                workspace_data=workspace.data if workspace is not None else None,
            )
        except ManifestParseError as exc:
            findings.append(manifest_finding(root, item.path, Ecosystem.RUST, exc.reason))
            continue
        if package is not None:
            packages.append(package)

    return RustDiscovery(
        packages=tuple(sorted(packages, key=lambda item: (item.root, item.name))),
        findings=tuple(sorted(findings, key=lambda item: (item.location or "", item.message))),
    )


def parse_rust_manifest(
    manifest: Path,
    root: Path,
    *,
    workspace_root: Path | None = None,
    workspace_manifest: Path | None = None,
) -> Package | None:
    """Parse one Cargo package, optionally resolving a workspace manifest."""

    workspace_data = read_toml_manifest(workspace_manifest) if workspace_manifest else None
    return _package_from_data(
        manifest,
        root,
        read_toml_manifest(manifest),
        workspace_root=workspace_root,
        workspace_data=workspace_data,
    )


def _package_from_data(
    manifest: Path,
    root: Path,
    data: Mapping[str, Any],
    *,
    workspace_root: Path | None,
    workspace_data: Mapping[str, Any] | None,
) -> Package | None:
    package = table(data.get("package"))
    if not package:
        return None
    workspace_package = table(table(workspace_data or {}).get("workspace")).get("package", {})
    workspace_package = table(workspace_package)

    name = package.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ManifestParseError(manifest, "Cargo package name must be a non-empty string")
    version_value = _workspace_value(package, workspace_package, "version")
    if not isinstance(version_value, str) or not version_value.strip():
        raise ManifestParseError(manifest, f"Cargo package {name!r} has no resolvable version")

    package_root = manifest.parent
    readme_value = _workspace_value(package, workspace_package, "readme")
    readme = (
        repository_path(root, package_root, readme_value)
        if isinstance(readme_value, str)
        else find_readme(root, package_root)
    )
    license_value = _workspace_value(package, workspace_package, "license")
    license_expression = license_value if isinstance(license_value, str) else None
    license_file_value = _workspace_value(package, workspace_package, "license-file")
    license_file = (
        repository_path(root, package_root, license_file_value)
        if isinstance(license_file_value, str)
        else None
    )
    include_files = {
        path
        for value in string_list(package.get("include"))
        if (path := repository_path(root, package_root, value)) is not None
    }
    include_files.update(item for item in (readme, license_file) if item is not None)

    metadata: dict[str, Any] = {}
    for manifest_key, metadata_key in (
        ("edition", "edition"),
        ("rust-version", "rust_version"),
        ("publish", "publish"),
    ):
        value = _workspace_value(package, workspace_package, manifest_key)
        if value is not None:
            metadata[metadata_key] = value

    return Package(
        ecosystem=Ecosystem.RUST,
        name=name.strip(),
        version=version_value.strip(),
        root=relative_path(root, package_root),
        manifest=relative_path(root, manifest),
        workspace_root=(
            relative_path(root, workspace_root) if workspace_root is not None else None
        ),
        license_expression=license_expression,
        readme=readme,
        entrypoints=_entrypoints(root, package_root, data),
        expected_files=tuple(sorted(include_files)),
        internal_dependencies=_dependencies(data, workspace_data),
        metadata=metadata,
    )


def _workspace_value(
    package: Mapping[str, Any],
    workspace_package: Mapping[str, Any],
    key: str,
) -> Any:
    value = package.get(key)
    if isinstance(value, Mapping) and value.get("workspace") is True:
        return workspace_package.get(key)
    return value


def _nearest_workspace(
    root: Path,
    manifest: Path,
    workspace_roots: Iterable[ParsedManifest],
) -> ParsedManifest | None:
    matches: list[ParsedManifest] = []
    for workspace in workspace_roots:
        workspace_dir = workspace.path.parent
        try:
            member = manifest.parent.relative_to(workspace_dir).as_posix() or "."
        except ValueError:
            continue
        workspace_table = table(workspace.data.get("workspace"))
        members = string_list(workspace_table.get("members"))
        excludes = string_list(workspace_table.get("exclude"))
        included = manifest == workspace.path or any(_glob_match(member, item) for item in members)
        excluded = any(_glob_match(member, item) for item in excludes)
        if included and not excluded:
            matches.append(workspace)
    return max(
        matches,
        key=lambda item: len(item.path.parent.relative_to(root).parts),
        default=None,
    )


def _glob_match(value: str, pattern: str) -> bool:
    pattern = pattern.removesuffix("/")
    if not pattern or Path(pattern).is_absolute() or ".." in PurePosixPath(pattern).parts:
        return False
    return fnmatchcase(value, pattern) or PurePosixPath(value).match(pattern)


def _dependencies(
    data: Mapping[str, Any],
    workspace_data: Mapping[str, Any] | None,
) -> tuple[InternalDependency, ...]:
    workspace_dependencies = table(table(workspace_data or {}).get("workspace")).get(
        "dependencies", {}
    )
    workspace_dependencies = table(workspace_dependencies)
    result: set[InternalDependency] = set()
    sections = (
        ("dependencies", "runtime"),
        ("dev-dependencies", "development"),
        ("build-dependencies", "build"),
    )
    for section_name, kind in sections:
        _add_dependency_table(result, table(data.get(section_name)), kind, workspace_dependencies)
    for target_name, target_data in table(data.get("target")).items():
        for section_name, kind in sections:
            _add_dependency_table(
                result,
                table(table(target_data).get(section_name)),
                f"target:{target_name}:{kind}",
                workspace_dependencies,
            )
    return tuple(sorted(result, key=lambda item: (item.kind, item.name, item.requirement)))


def _add_dependency_table(
    output: set[InternalDependency],
    dependencies: Mapping[str, Any],
    kind: str,
    workspace_dependencies: Mapping[str, Any],
) -> None:
    for alias, declared in dependencies.items():
        if not isinstance(alias, str):
            continue
        effective = declared
        if isinstance(declared, Mapping) and declared.get("workspace") is True:
            effective = workspace_dependencies.get(alias, declared)
        actual_name = alias
        if isinstance(declared, Mapping) and isinstance(declared.get("package"), str):
            actual_name = declared["package"]
        elif isinstance(effective, Mapping) and isinstance(effective.get("package"), str):
            actual_name = effective["package"]
        requirement = _dependency_requirement(effective)
        if requirement is not None:
            output.add(InternalDependency(actual_name, requirement, kind))


def _dependency_requirement(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, Mapping):
        for key in ("version", "path", "git", "registry"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate if key == "version" else f"{key}:{candidate}"
        if value.get("workspace") is True:
            return "workspace"
    return None


def _entrypoints(root: Path, package_root: Path, data: Mapping[str, Any]) -> tuple[str, ...]:
    result: set[str] = set()
    lib = table(data.get("lib"))
    if isinstance(lib.get("path"), str):
        path = repository_path(root, package_root, lib["path"])
        if path is not None:
            result.add(path)
    elif (package_root / "src/lib.rs").is_file():
        result.add(relative_path(root, package_root / "src/lib.rs"))

    bins = data.get("bin")
    if isinstance(bins, list):
        for item in bins:
            path_value = table(item).get("path")
            if isinstance(path_value, str):
                path = repository_path(root, package_root, path_value)
                if path is not None:
                    result.add(path)
    if not result and (package_root / "src/main.rs").is_file():
        result.add(relative_path(root, package_root / "src/main.rs"))
    return tuple(sorted(result))
