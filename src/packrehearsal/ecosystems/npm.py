"""Static npm ``package.json`` and workspace discovery."""

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
    read_json_manifest,
    relative_path,
    repository_path,
    string_list,
    string_mapping,
)


@dataclass(frozen=True, slots=True)
class NpmDiscovery:
    packages: tuple[Package, ...]
    findings: tuple[Finding, ...]


def discover_npm_packages(root: Path, manifests: Iterable[Path]) -> NpmDiscovery:
    """Parse npm manifests and assign workspace roots without invoking npm."""

    parsed: list[ParsedManifest] = []
    findings: list[Finding] = []
    for manifest in sorted(set(manifests), key=lambda item: relative_path(root, item)):
        try:
            parsed.append(ParsedManifest(manifest, read_json_manifest(manifest)))
        except ManifestParseError as exc:
            findings.append(manifest_finding(root, manifest, Ecosystem.NPM, exc.reason))

    workspace_roots = [item for item in parsed if _workspace_patterns(item.data)]
    packages: list[Package] = []
    for item in parsed:
        workspace = _nearest_workspace(root, item.path, workspace_roots)
        try:
            package = _package_from_data(
                item.path,
                root,
                item.data,
                workspace_root=workspace.path.parent if workspace is not None else None,
            )
        except ManifestParseError as exc:
            findings.append(manifest_finding(root, item.path, Ecosystem.NPM, exc.reason))
            continue
        if package is not None:
            packages.append(package)

    return NpmDiscovery(
        packages=tuple(sorted(packages, key=lambda item: (item.root, item.name))),
        findings=tuple(sorted(findings, key=lambda item: (item.location or "", item.message))),
    )


def parse_npm_manifest(
    manifest: Path,
    root: Path,
    *,
    workspace_root: Path | None = None,
) -> Package | None:
    """Parse one package manifest; virtual workspace coordinators return ``None``."""

    return _package_from_data(
        manifest,
        root,
        read_json_manifest(manifest),
        workspace_root=workspace_root,
    )


def _package_from_data(
    manifest: Path,
    root: Path,
    data: Mapping[str, Any],
    *,
    workspace_root: Path | None,
) -> Package | None:
    name = data.get("name")
    version = data.get("version")
    has_workspaces = bool(_workspace_patterns(data))
    private = data.get("private") is True

    if not isinstance(name, str) or not name.strip():
        if has_workspaces and private:
            return None
        raise ManifestParseError(manifest, "npm package name must be a non-empty string")
    if not isinstance(version, str) or not version.strip():
        if has_workspaces and private:
            return None
        raise ManifestParseError(manifest, f"npm package {name!r} has no string version")

    package_root = manifest.parent
    entrypoints = _entrypoints(root, package_root, data)
    expected_files = tuple(
        sorted(
            path
            for value in string_list(data.get("files"))
            if (path := _npm_package_path(root, package_root, value)) is not None
        )
    )
    readme = None
    readme_value = data.get("readmeFilename")
    if isinstance(readme_value, str):
        readme = repository_path(root, package_root, readme_value)
    readme = readme or find_readme(root, package_root)

    license_value = data.get("license")
    license_expression = license_value if isinstance(license_value, str) else None
    metadata: dict[str, Any] = {"private": private}
    if isinstance(data.get("packageManager"), str):
        metadata["package_manager"] = data["packageManager"]
    if isinstance(data.get("publishConfig"), Mapping):
        metadata["publish_config"] = dict(data["publishConfig"])

    return Package(
        ecosystem=Ecosystem.NPM,
        name=name.strip(),
        version=version.strip(),
        root=relative_path(root, package_root),
        manifest=relative_path(root, manifest),
        workspace_root=(
            relative_path(root, workspace_root) if workspace_root is not None else None
        ),
        license_expression=license_expression,
        readme=readme,
        entrypoints=entrypoints,
        expected_files=expected_files,
        internal_dependencies=_dependencies(data),
        metadata=metadata,
    )


def _workspace_patterns(data: Mapping[str, Any]) -> tuple[str, ...]:
    value = data.get("workspaces")
    if isinstance(value, Mapping):
        value = value.get("packages")
    return string_list(value)


def _nearest_workspace(
    root: Path,
    manifest: Path,
    workspace_roots: Iterable[ParsedManifest],
) -> ParsedManifest | None:
    matches: list[ParsedManifest] = []
    for workspace in workspace_roots:
        workspace_dir = workspace.path.parent
        try:
            member_dir = manifest.parent.relative_to(workspace_dir).as_posix() or "."
        except ValueError:
            continue
        is_member = _workspace_match(member_dir, _workspace_patterns(workspace.data))
        if manifest == workspace.path or is_member:
            matches.append(workspace)
    return max(
        matches,
        key=lambda item: len(item.path.parent.relative_to(root).parts),
        default=None,
    )


def _workspace_match(member: str, patterns: tuple[str, ...]) -> bool:
    positive = False
    for raw_pattern in patterns:
        negated = raw_pattern.startswith("!")
        pattern = raw_pattern[1:] if negated else raw_pattern
        pattern = pattern.removesuffix("/")
        if not pattern or Path(pattern).is_absolute() or ".." in PurePosixPath(pattern).parts:
            continue
        matched = fnmatchcase(member, pattern) or PurePosixPath(member).match(pattern)
        if matched:
            if negated:
                return False
            positive = True
    return positive


def _dependencies(data: Mapping[str, Any]) -> tuple[InternalDependency, ...]:
    sections = (
        ("dependencies", "runtime"),
        ("optionalDependencies", "optional"),
        ("peerDependencies", "peer"),
        ("devDependencies", "development"),
    )
    values = {
        InternalDependency(name=name, requirement=requirement, kind=kind)
        for section, kind in sections
        for name, requirement in string_mapping(data.get(section)).items()
    }
    return tuple(sorted(values, key=lambda item: (item.kind, item.name, item.requirement)))


def _entrypoints(root: Path, package_root: Path, data: Mapping[str, Any]) -> tuple[str, ...]:
    values: set[str] = set()
    for key in ("main", "module", "types", "typings"):
        value = data.get(key)
        if isinstance(value, str):
            values.add(value)
    bin_value = data.get("bin")
    if isinstance(bin_value, str):
        values.add(bin_value)
    else:
        values.update(string_mapping(bin_value).values())
    _collect_export_targets(data.get("exports"), values)
    normalized = {
        path
        for value in values
        if (path := _npm_package_path(root, package_root, value)) is not None
    }
    return tuple(sorted(normalized))


def _npm_package_path(root: Path, package_root: Path, value: str) -> str | None:
    """Reject npm publish paths that leave their package directory."""

    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return repository_path(root, package_root, value)


def _collect_export_targets(value: Any, output: set[str]) -> None:
    if isinstance(value, str):
        output.add(value)
    elif isinstance(value, Mapping):
        for child in value.values():
            _collect_export_targets(child, output)
    elif isinstance(value, list):
        for child in value:
            _collect_export_targets(child, output)
