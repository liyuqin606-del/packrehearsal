"""Deterministic, zero-execution repository package discovery."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from packrehearsal.config import Config
from packrehearsal.ecosystems import (
    canonical_python_name,
    discover_npm_packages,
    discover_python_packages,
    discover_rust_packages,
)
from packrehearsal.ecosystems.common import manifest_finding, relative_path
from packrehearsal.exceptions import DiscoveryError
from packrehearsal.models import Ecosystem, Evidence, Finding, Package, Severity
from packrehearsal.safe_io import repository_read_root

_MANIFEST_ECOSYSTEM = {
    "package.json": Ecosystem.NPM,
    "pyproject.toml": Ecosystem.PYTHON,
    "Cargo.toml": Ecosystem.RUST,
}


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Packages and non-fatal findings produced by one repository walk."""

    packages: tuple[Package, ...]
    findings: tuple[Finding, ...]


def discover_packages(root: str | Path, config: Config | None = None) -> DiscoveryResult:
    """Discover supported package manifests without executing repository code.

    An invalid requested root raises :class:`DiscoveryError`. A malformed or
    unsafe individual manifest becomes a finding so other packages can still be
    inspected.
    """

    repository_root = _validated_root(root)
    resolved_config = config or Config()
    manifests, walk_findings = _collect_manifests(repository_root, resolved_config)

    with repository_read_root(repository_root):
        npm_result = discover_npm_packages(repository_root, manifests[Ecosystem.NPM])
        python_result = discover_python_packages(repository_root, manifests[Ecosystem.PYTHON])
        rust_result = discover_rust_packages(repository_root, manifests[Ecosystem.RUST])

    packages = _retain_internal_dependencies(
        (*npm_result.packages, *python_result.packages, *rust_result.packages)
    )
    duplicate_findings = _duplicate_name_findings(packages)
    findings = (
        *walk_findings,
        *npm_result.findings,
        *python_result.findings,
        *rust_result.findings,
        *duplicate_findings,
    )
    return DiscoveryResult(
        packages=tuple(
            sorted(packages, key=lambda item: (item.ecosystem.value, item.root, item.name))
        ),
        findings=tuple(
            sorted(
                findings,
                key=lambda item: (
                    item.rule_id,
                    item.location or "",
                    item.package or "",
                    item.message,
                ),
            )
        ),
    )


def discover_repository(root: str | Path, config: Config | None = None) -> DiscoveryResult:
    """Alias with a name convenient for CLI orchestration."""

    return discover_packages(root, config)


def _validated_root(root: str | Path) -> Path:
    candidate = Path(root).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        message = f"discovery root does not exist or cannot be resolved: {candidate}"
        raise DiscoveryError(message) from exc
    if not resolved.is_dir():
        raise DiscoveryError(f"discovery root is not a directory: {resolved}")
    return resolved


def _collect_manifests(
    root: Path,
    config: Config,
) -> tuple[dict[Ecosystem, tuple[Path, ...]], tuple[Finding, ...]]:
    found: dict[Ecosystem, list[Path]] = {ecosystem: [] for ecosystem in Ecosystem}
    findings: list[Finding] = []

    def on_error(error: OSError) -> None:
        raise DiscoveryError(f"cannot walk discovery root {root}: {error}") from error

    for current_text, directory_names, file_names in os.walk(
        root,
        topdown=True,
        onerror=on_error,
        followlinks=False,
    ):
        current = Path(current_text)
        current_relative = current.relative_to(root)
        depth = len(current_relative.parts)

        retained_directories: list[str] = []
        if depth < config.max_depth:
            for name in sorted(directory_names):
                candidate = current / name
                relative = candidate.relative_to(root).as_posix()
                if candidate.is_symlink():
                    continue
                if not config.include_hidden and name.startswith("."):
                    continue
                if _is_excluded(relative, config.exclude):
                    continue
                retained_directories.append(name)
        directory_names[:] = retained_directories

        if depth > config.max_depth:
            continue
        for name in sorted(file_names):
            ecosystem = _MANIFEST_ECOSYSTEM.get(name)
            if ecosystem is None:
                continue
            manifest = current / name
            relative = manifest.relative_to(root).as_posix()
            if _is_excluded(relative, config.exclude):
                continue
            if manifest.is_symlink():
                findings.append(
                    manifest_finding(
                        root,
                        manifest,
                        ecosystem,
                        "symbolic-link manifests are not followed during safe discovery",
                    )
                )
                continue
            found[ecosystem].append(manifest)

    ordered = {
        key: tuple(sorted(value, key=lambda path: relative_path(root, path)))
        for key, value in found.items()
    }
    return ordered, tuple(findings)


def _is_excluded(relative: str, patterns: Iterable[str]) -> bool:
    path = PurePosixPath(relative)
    for raw_pattern in patterns:
        pattern = raw_pattern.replace("\\", "/").removeprefix("./").removesuffix("/")
        if not pattern:
            continue
        if pattern.endswith("/**"):
            prefix = pattern[:-3].removesuffix("/")
            if relative == prefix or relative.startswith(f"{prefix}/"):
                return True
        if fnmatchcase(relative, pattern) or path.match(pattern):
            return True
    return False


def _retain_internal_dependencies(packages: Iterable[Package]) -> tuple[Package, ...]:
    package_list = tuple(packages)
    known: dict[Ecosystem, set[str]] = {ecosystem: set() for ecosystem in Ecosystem}
    for package in package_list:
        known[package.ecosystem].add(_normalized_name(package.ecosystem, package.name))

    return tuple(
        replace(
            package,
            internal_dependencies=tuple(
                dependency
                for dependency in package.internal_dependencies
                if _normalized_name(package.ecosystem, dependency.name) in known[package.ecosystem]
            ),
        )
        for package in package_list
    )


def _duplicate_name_findings(packages: Iterable[Package]) -> tuple[Finding, ...]:
    groups: dict[tuple[Ecosystem, str], list[Package]] = {}
    for package in packages:
        key = (package.ecosystem, _normalized_name(package.ecosystem, package.name))
        groups.setdefault(key, []).append(package)

    findings: list[Finding] = []
    for (ecosystem, _), duplicates in groups.items():
        if len(duplicates) < 2:
            continue
        locations = ", ".join(sorted(item.manifest for item in duplicates))
        for package in duplicates:
            findings.append(
                Finding(
                    rule_id="discovery-duplicate-package-name",
                    severity=Severity.MEDIUM,
                    title="Package name is ambiguous inside the repository",
                    message=(
                        f"{package.name!r} is declared by multiple {ecosystem.value} manifests: "
                        f"{locations}"
                    ),
                    remediation="Give repository packages unique publishable names.",
                    package=package.identity,
                    location=package.manifest,
                    evidence=(Evidence("ecosystem", ecosystem.value),),
                )
            )
    return tuple(findings)


def _normalized_name(ecosystem: Ecosystem, name: str) -> str:
    if ecosystem is Ecosystem.PYTHON:
        return canonical_python_name(name)
    return name
