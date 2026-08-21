"""Core rule API and safe, deterministic rule context helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import ClassVar

from packrehearsal.config import Config
from packrehearsal.models import (
    ArtifactEntry,
    ArtifactSnapshot,
    Ecosystem,
    Evidence,
    Finding,
    Package,
    RuleDescriptor,
)
from packrehearsal.safe_io import read_text_beneath, regular_file_size_beneath


def normalize_relative_path(value: str) -> str:
    """Return a portable relative POSIX path and reject traversal."""

    raw = value.replace("\\", "/").strip()
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"path must stay inside the repository: {value!r}")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    return "/".join(parts) or "."


def join_relative(root: str, child: str) -> str:
    """Join two normalized repository-relative paths."""

    normalized_root = normalize_relative_path(root)
    normalized_child = normalize_relative_path(child)
    if normalized_child == ".":
        return normalized_root
    if normalized_root == ".":
        return normalized_child
    return f"{normalized_root}/{normalized_child}"


def path_is_within(path: str, root: str) -> bool:
    """Whether *path* is equal to or nested below *root*."""

    normalized_path = normalize_relative_path(path)
    normalized_root = normalize_relative_path(root)
    return (
        normalized_root == "."
        or normalized_path == normalized_root
        or normalized_path.startswith(f"{normalized_root}/")
    )


def relative_to_root(path: str, root: str) -> str:
    """Return *path* relative to *root*, which must contain it."""

    normalized_path = normalize_relative_path(path)
    normalized_root = normalize_relative_path(root)
    if normalized_root == ".":
        return normalized_path
    if normalized_path == normalized_root:
        return "."
    if not normalized_path.startswith(f"{normalized_root}/"):
        raise ValueError(f"{path!r} is not below {root!r}")
    return normalized_path[len(normalized_root) + 1 :]


@dataclass(frozen=True, slots=True)
class RuleContext:
    """Inputs available to a rule for one package.

    ``repository_files`` are repository-relative POSIX paths. Supplying all
    discovered packages lets the context attribute a file to the deepest
    package root, preventing repository checks from being repeated for parent
    and nested packages. ``artifact`` is the candidate currently being
    evaluated; ``artifacts`` contains every candidate associated with the
    package so cross-artifact rules can compare them without rereading files.
    """

    root: Path
    package: Package
    config: Config = field(default_factory=Config)
    repository_files: tuple[str, ...] = ()
    artifact: ArtifactSnapshot | None = None
    packages: tuple[Package, ...] = ()
    artifacts: tuple[ArtifactSnapshot, ...] = ()

    def __post_init__(self) -> None:
        root = self.root.expanduser().resolve()
        files = tuple(sorted({normalize_relative_path(item) for item in self.repository_files}))
        packages = self.packages
        if not packages:
            packages = (self.package,)
        elif not any(item.identity == self.package.identity for item in packages):
            packages = (*packages, self.package)
        packages = tuple(
            sorted(packages, key=lambda item: (normalize_relative_path(item.root), item.identity))
        )
        artifacts = self.artifacts
        if not artifacts and self.artifact is not None:
            artifacts = (self.artifact,)
        elif self.artifact is not None and self.artifact not in artifacts:
            artifacts = (*artifacts, self.artifact)
        artifacts = tuple(sorted(artifacts, key=lambda item: (item.path, item.sha256)))
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "repository_files", files)
        object.__setattr__(self, "packages", packages)
        object.__setattr__(self, "artifacts", artifacts)

    @property
    def package_root(self) -> str:
        return normalize_relative_path(self.package.root)

    @property
    def workspace_root(self) -> str | None:
        if self.package.workspace_root is None:
            return None
        return normalize_relative_path(self.package.workspace_root)

    @property
    def package_files(self) -> tuple[str, ...]:
        """Files owned by this package, relative to the package root."""

        result: list[str] = []
        for path in self.repository_files:
            if not path_is_within(path, self.package_root):
                continue
            matching_roots = {
                normalize_relative_path(item.root)
                for item in self.packages
                if path_is_within(path, item.root)
            }
            deepest = max((len(PurePosixPath(item).parts) for item in matching_roots), default=0)
            if len(PurePosixPath(self.package_root).parts) != deepest:
                continue
            result.append(relative_to_root(path, self.package_root))
        return tuple(result)

    def files_below(self, root: str) -> tuple[str, ...]:
        """Return repository files below *root*, relative to that root."""

        normalized_root = normalize_relative_path(root)
        return tuple(
            relative_to_root(path, normalized_root)
            for path in self.repository_files
            if path_is_within(path, normalized_root)
        )

    def repository_path(self, relative: str) -> Path | None:
        """Resolve a repository path without allowing traversal or symlink escape."""

        normalized = normalize_relative_path(relative)
        candidate = (self.root / normalized).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            return None
        return candidate

    def package_repository_path(self, relative: str) -> Path | None:
        return self.repository_path(join_relative(self.package_root, relative))

    def repo_has_file(self, relative: str) -> bool:
        """Check a package-relative path against discovery, then the filesystem."""

        normalized = normalize_relative_path(relative)
        full = (
            normalized
            if path_is_within(normalized, self.package_root)
            else join_relative(self.package_root, normalized)
        )
        if self.repository_files and full in self.repository_files:
            return True
        path = self.repository_path(full)
        return bool(path is not None and path.is_file())

    def repo_file_size(self, repository_relative: str) -> int | None:
        """Safely return a discovered file's size; symlinks are ignored."""

        try:
            normalized = normalize_relative_path(repository_relative)
            return regular_file_size_beneath(self.root, normalized)
        except (OSError, ValueError):
            return None

    def read_repository_text(self, repository_relative: str, *, limit: int = 2_000_000) -> str:
        """Read a small text file without following paths outside the root."""

        try:
            normalized = normalize_relative_path(repository_relative)
        except ValueError as exc:
            raise OSError(f"unsafe repository path: {repository_relative}") from exc
        try:
            return read_text_beneath(self.root, normalized, limit=limit)
        except OSError as exc:
            if "limit" in str(exc):
                raise OSError(
                    f"file exceeds rule read limit: {repository_relative}: {exc}"
                ) from exc
            raise OSError(
                f"unsafe repository path or unreadable file: {repository_relative}: {exc}"
            ) from exc

    @property
    def artifact_entries(self) -> tuple[ArtifactEntry, ...]:
        if self.artifact is None:
            return ()
        return tuple(sorted(self.artifact.entries, key=lambda item: item.path))

    def artifact_relative_paths(self, entry: ArtifactEntry) -> tuple[str, ...]:
        """Possible package-relative forms of an archive member path."""

        try:
            normalized = normalize_relative_path(entry.path)
        except ValueError:
            return ()
        candidates = {normalized}
        first, separator, rest = normalized.partition("/")
        package_names = {
            self.package.name,
            self.package.name.replace("_", "-"),
            self.package.name.replace("-", "_"),
        }
        package_versions = {self.package.version}
        if self.artifact is not None:
            metadata_name = self.artifact.metadata.get("package_name")
            metadata_version = self.artifact.metadata.get("package_version")
            if isinstance(metadata_name, str) and metadata_name.strip():
                package_names.update(
                    {
                        metadata_name.strip(),
                        metadata_name.strip().replace("_", "-"),
                        metadata_name.strip().replace("-", "_"),
                    }
                )
            if isinstance(metadata_version, str) and metadata_version.strip():
                package_versions.add(metadata_version.strip())
        package_prefixes = {
            "package",
            *(f"{name}-{version}" for name in package_names for version in package_versions),
        }
        if separator and first in package_prefixes:
            candidates.add(rest)
        return tuple(sorted(candidates))

    def artifact_has_file(self, relative: str) -> bool:
        if self.artifact is None:
            return False
        normalized = normalize_relative_path(relative)
        if self.package_root != "." and path_is_within(normalized, self.package_root):
            normalized = relative_to_root(normalized, self.package_root)
        return any(
            entry.kind == "file" and normalized in self.artifact_relative_paths(entry)
            for entry in self.artifact.entries
        )

    def artifact_entry_for(self, relative: str) -> ArtifactEntry | None:
        if self.artifact is None:
            return None
        normalized = normalize_relative_path(relative)
        if self.package_root != "." and path_is_within(normalized, self.package_root):
            normalized = relative_to_root(normalized, self.package_root)
        return next(
            (
                entry
                for entry in self.artifact_entries
                if entry.kind == "file" and normalized in self.artifact_relative_paths(entry)
            ),
            None,
        )

    def manifest_path(self) -> str:
        """Return the manifest as a repository-relative path."""

        manifest = normalize_relative_path(self.package.manifest)
        if path_is_within(manifest, self.package_root):
            return manifest
        return join_relative(self.package_root, manifest)


class Rule(ABC):
    """Stateless package rule with a stable, machine-readable descriptor."""

    descriptor: ClassVar[RuleDescriptor]

    @abstractmethod
    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        """Yield findings before configuration severity overrides are applied."""

    def applies_to(self, ecosystem: Ecosystem) -> bool:
        ecosystems = self.descriptor.ecosystems
        return not ecosystems or ecosystem in ecosystems

    def run(self, context: RuleContext) -> tuple[Finding, ...]:
        rule_id = self.descriptor.rule_id
        if not self.applies_to(context.package.ecosystem):
            return ()
        if not context.config.rule_enabled(rule_id):
            return ()
        severity = context.config.severity_for(rule_id, self.descriptor.default_severity)
        findings: list[Finding] = []
        for finding in self.evaluate(context):
            if finding.rule_id != rule_id:
                raise ValueError(f"rule {rule_id!r} emitted a finding for {finding.rule_id!r}")
            if not finding.remediation.strip():
                raise ValueError(f"rule {rule_id!r} emitted a finding without remediation")
            if not finding.evidence:
                raise ValueError(f"rule {rule_id!r} emitted a finding without evidence")
            findings.append(finding.with_severity(severity))
        return tuple(
            sorted(
                findings,
                key=lambda item: (item.location or "", item.fingerprint),
            )
        )

    def finding(
        self,
        context: RuleContext,
        *,
        message: str,
        remediation: str,
        evidence: Mapping[str, object] | Iterable[tuple[str, object]],
        location: str | None = None,
        title: str | None = None,
    ) -> Finding:
        items = evidence.items() if isinstance(evidence, Mapping) else evidence
        normalized_evidence = tuple(
            Evidence(str(key), str(value))
            for key, value in sorted(items, key=lambda item: (str(item[0]), str(item[1])))
        )
        return Finding(
            rule_id=self.descriptor.rule_id,
            severity=self.descriptor.default_severity,
            title=title or self.descriptor.title,
            message=message,
            remediation=remediation,
            package=context.package.identity,
            location=location,
            evidence=normalized_evidence,
        )
