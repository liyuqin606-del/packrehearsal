"""High-level scan orchestration shared by the CLI and integrations."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from packrehearsal.artifacts import inspect_artifacts
from packrehearsal.config import Config, validate_configured_rule_ids
from packrehearsal.discovery import discover_packages
from packrehearsal.exceptions import DiscoveryError
from packrehearsal.models import (
    ArtifactSnapshot,
    Ecosystem,
    Evidence,
    Finding,
    Package,
    ScanReport,
    Severity,
)
from packrehearsal.rules import (
    RuleContext,
    RuleRegistry,
    deduplicate_findings,
    default_registry,
    run_rules,
)


@dataclass(frozen=True, slots=True)
class ArtifactAssociation:
    """Explain how an artifact was associated with a discovered package."""

    artifact: ArtifactSnapshot
    package: Package | None
    reason: str


def scan_repository(
    root: Path | str,
    *,
    config: Config | None = None,
    artifact_paths: Iterable[Path | str] = (),
    artifacts: Iterable[ArtifactSnapshot] = (),
    baseline_fingerprints: Iterable[str] = (),
    registry: RuleRegistry | None = None,
) -> ScanReport:
    """Discover packages, inspect artifacts, and run deterministic rules.

    Static scans never run subprocesses. Callers that perform an explicit
    trusted build can pass its already-inspected snapshots via ``artifacts``.
    """

    repository_root = _validated_root(root)
    active_config = config or Config()
    active_registry = registry if registry is not None else default_registry()
    validate_configured_rule_ids(active_config, active_registry.rule_ids)
    discovery = discover_packages(repository_root, active_config)
    repository_files = collect_repository_files(repository_root, active_config)

    provided_snapshots = tuple(artifacts)
    inspected_snapshots = _inspect_requested_artifacts(
        repository_root,
        artifact_paths,
        active_config,
    )
    snapshots = tuple(
        sorted(
            (*provided_snapshots, *inspected_snapshots),
            key=lambda item: (item.path, item.sha256),
        )
    )
    associations = associate_artifacts(discovery.packages, snapshots)

    findings: list[Finding] = list(discovery.findings)
    package_artifacts: dict[str, list[ArtifactSnapshot]] = {
        package.identity: [] for package in discovery.packages
    }
    for association in associations:
        if association.package is None:
            findings.append(_unmatched_artifact_finding(association))
        else:
            package_artifacts[association.package.identity].append(association.artifact)

    for package in discovery.packages:
        candidates: tuple[ArtifactSnapshot | None, ...]
        matched = tuple(package_artifacts[package.identity])
        candidates = matched if matched else (None,)
        for artifact in candidates:
            context = RuleContext(
                root=repository_root,
                package=package,
                packages=discovery.packages,
                repository_files=repository_files,
                artifact=artifact,
                config=active_config,
            )
            findings.extend(run_rules(context, active_registry))

    if not discovery.packages:
        findings.append(
            Finding(
                rule_id="engine-no-supported-packages",
                severity=Severity.LOW,
                title="No supported packages discovered",
                message="No npm, Python, or Rust publishable manifest was discovered.",
                remediation=(
                    "Run PackRehearsal at the repository root or add a supported package manifest."
                ),
                location=".",
                evidence=(Evidence("supported_ecosystems", "npm,python,rust"),),
            )
        )

    return ScanReport(
        root=".",
        packages=discovery.packages,
        findings=deduplicate_findings(findings),
        artifacts=snapshots,
        baseline_fingerprints=tuple(sorted(set(baseline_fingerprints))),
    )


def collect_repository_files(root: Path, config: Config) -> tuple[str, ...]:
    """Collect regular files without following symlinks or excluded trees."""

    files: list[str] = []

    def on_error(error: OSError) -> None:
        raise DiscoveryError(f"cannot enumerate repository files below {root}: {error}") from error

    for current_text, directory_names, file_names in os.walk(
        root,
        topdown=True,
        onerror=on_error,
        followlinks=False,
    ):
        current = Path(current_text)
        relative_directory = current.relative_to(root)
        depth = len(relative_directory.parts)
        retained: list[str] = []
        if depth < config.max_depth:
            for name in sorted(directory_names):
                candidate = current / name
                relative = candidate.relative_to(root).as_posix()
                if candidate.is_symlink() or _excluded(relative, config.exclude):
                    continue
                if name.startswith(".") and not config.include_hidden and name != ".github":
                    continue
                retained.append(name)
        directory_names[:] = retained
        if depth > config.max_depth:
            continue
        for name in sorted(file_names):
            candidate = current / name
            if candidate.is_symlink():
                continue
            relative = candidate.relative_to(root).as_posix()
            if _excluded(relative, config.exclude):
                continue
            try:
                if candidate.is_file():
                    files.append(relative)
            except OSError as exc:
                raise DiscoveryError(f"cannot inspect repository file {candidate}: {exc}") from exc
    return tuple(sorted(set(files)))


def associate_artifacts(
    packages: Iterable[Package],
    artifacts: Iterable[ArtifactSnapshot],
) -> tuple[ArtifactAssociation, ...]:
    """Associate artifacts conservatively using ecosystem, name, and version.

    Ambiguous artifacts remain unmatched rather than being checked against the
    wrong package.
    """

    package_list = tuple(packages)
    result: list[ArtifactAssociation] = []
    for artifact in artifacts:
        compatible = tuple(
            package for package in package_list if _artifact_compatible(package, artifact)
        )
        scored = [(_artifact_match_score(package, artifact), package) for package in compatible]
        best_score = max((score for score, _ in scored), default=0)
        best = [package for score, package in scored if score == best_score and score > 0]
        if len(best) == 1:
            result.append(ArtifactAssociation(artifact, best[0], "name and version match"))
        elif len(compatible) == 1:
            result.append(ArtifactAssociation(artifact, compatible[0], "only compatible package"))
        elif not compatible:
            result.append(ArtifactAssociation(artifact, None, "no compatible package"))
        else:
            result.append(ArtifactAssociation(artifact, None, "ambiguous compatible packages"))
    return tuple(sorted(result, key=lambda item: item.artifact.path))


def _inspect_requested_artifacts(
    root: Path,
    artifact_paths: Iterable[Path | str],
    config: Config,
) -> tuple[ArtifactSnapshot, ...]:
    snapshots: list[ArtifactSnapshot] = []
    for item in artifact_paths:
        candidate = Path(item).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        # Preserve the final path component so the archive inspector can reject
        # symlinks itself. Resolving it here would silently follow the link.
        parent = candidate.parent.resolve(strict=True)
        raw_candidate = parent / candidate.name
        try:
            display = raw_candidate.relative_to(root).as_posix()
        except ValueError:
            # External artifacts can be inspected, but absolute workstation
            # paths must not leak into deterministic reports.
            display = raw_candidate.name
        snapshots.extend(inspect_artifacts((raw_candidate,), limits=config.archive, root=None))
        snapshots[-1] = ArtifactSnapshot(
            path=display,
            format=snapshots[-1].format,
            sha256=snapshots[-1].sha256,
            size=snapshots[-1].size,
            entries=snapshots[-1].entries,
            metadata=snapshots[-1].metadata,
        )
    return tuple(snapshots)


def _artifact_compatible(package: Package, artifact: ArtifactSnapshot) -> bool:
    formats = {
        Ecosystem.NPM: {"tgz"},
        Ecosystem.PYTHON: {"wheel", "sdist", "zip", "tar.gz"},
        Ecosystem.RUST: {"crate"},
    }
    return artifact.format.lower() in formats[package.ecosystem]


def _artifact_match_score(package: Package, artifact: ArtifactSnapshot) -> int:
    filename = PurePosixPath(artifact.path).name.casefold()
    normalized_filename = _normalized_token(filename)
    normalized_name = _normalized_token(package.name)
    normalized_version = _normalized_token(package.version)
    score = 0
    metadata_name = artifact.metadata.get("package_name")
    if (
        isinstance(metadata_name, str)
        and normalized_name
        and _normalized_token(metadata_name) == normalized_name
    ):
        score += 4
    metadata_version = artifact.metadata.get("package_version")
    if isinstance(metadata_version, str) and metadata_version.strip():
        if package.version == "<dynamic>":
            score += 1
        elif _normalized_token(metadata_version) == normalized_version:
            score += 2
    if normalized_name and normalized_name in normalized_filename:
        score += 2
    if normalized_version and normalized_version in normalized_filename:
        score += 1
    return score


def _normalized_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _unmatched_artifact_finding(association: ArtifactAssociation) -> Finding:
    artifact = association.artifact
    return Finding(
        rule_id="engine-artifact-unmatched",
        severity=Severity.MEDIUM,
        title="Artifact could not be associated with a package",
        message=f"{artifact.path!r} was not checked against package-specific rules.",
        remediation=(
            "Use a conventional artifact filename or scan a repository with exactly one "
            "compatible package."
        ),
        location=artifact.path,
        evidence=(
            Evidence("artifact_format", artifact.format),
            Evidence("reason", association.reason),
        ),
    )


def _validated_root(root: Path | str) -> Path:
    candidate = Path(root).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DiscoveryError(f"repository root cannot be resolved: {candidate}") from exc
    if not resolved.is_dir():
        raise DiscoveryError(f"repository root is not a directory: {resolved}")
    return resolved


def _excluded(relative: str, patterns: Iterable[str]) -> bool:
    path = PurePosixPath(relative)
    for raw in patterns:
        pattern = raw.replace("\\", "/").removeprefix("./").removesuffix("/")
        if not pattern:
            continue
        if pattern.endswith("/**"):
            prefix = pattern[:-3].removesuffix("/")
            if relative == prefix or relative.startswith(f"{prefix}/"):
                return True
        if fnmatchcase(relative, pattern) or path.match(pattern):
            return True
    return False
