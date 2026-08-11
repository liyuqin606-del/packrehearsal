"""Rules shared by every supported package ecosystem."""

from __future__ import annotations

from packrehearsal.models import RuleDescriptor, Severity
from packrehearsal.rules._utils import (
    any_path_matches,
    artifact_member_paths,
    candidates_exist,
    declared_path_candidates,
    is_placeholder_version,
    is_valid_version,
    normalize_package_name,
    package_uses_dynamic_version,
    package_version_for_validation,
    path_matches,
    requirement_allows_version,
    versions_equivalent,
)
from packrehearsal.rules.base import (
    Rule,
    RuleContext,
    join_relative,
    normalize_relative_path,
    path_is_within,
    relative_to_root,
)


def _patterns_for(context: RuleContext, prefix: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    configured = tuple(
        item for item in context.config.required_files if item.upper().startswith(prefix.upper())
    )
    return configured or fallback


def _roots_for_common_files(context: RuleContext) -> tuple[str, ...]:
    roots = {context.package_root}
    if context.workspace_root is not None:
        roots.add(context.workspace_root)
    return tuple(sorted(roots))


def _common_repository_file(
    context: RuleContext,
    *,
    declared: str | None,
    patterns: tuple[str, ...],
) -> str | None:
    if declared:
        try:
            normalized = normalize_relative_path(declared)
        except ValueError:
            normalized = ""
        if normalized and (
            context.repo_has_file(normalized) or normalized in context.repository_files
        ):
            return normalized
    for root in _roots_for_common_files(context):
        for relative in context.files_below(root):
            if any_path_matches((relative,), patterns):
                return join_relative(root, relative)
    return None


def _contains_expected_path(paths: tuple[str, ...], expected: str) -> bool:
    if any_path_matches(paths, (expected,)):
        return True
    if any(character in expected for character in "*?["):
        return False
    prefix = expected.rstrip("/")
    return any(path.startswith(f"{prefix}/") for path in paths)


def _expected_path_candidates(context: RuleContext, expected: str) -> tuple[str, ...]:
    candidates = {expected}
    if context.package_root != "." and not path_is_within(expected, context.package_root):
        candidates.add(join_relative(context.package_root, expected))
    return tuple(sorted(candidates))


def _artifact_expected_candidates(context: RuleContext, expected: str) -> tuple[str, ...]:
    result = {expected}
    for candidate in _expected_path_candidates(context, expected):
        if context.package_root != "." and path_is_within(candidate, context.package_root):
            result.add(relative_to_root(candidate, context.package_root))
        else:
            result.add(candidate)
    return tuple(sorted(result))


def _is_python_wheel(context: RuleContext) -> bool:
    artifact = context.artifact
    return bool(
        artifact is not None
        and context.package.ecosystem.value == "python"
        and artifact.format.casefold() in {"wheel", "whl"}
    )


def _wheel_has_relocated_license(context: RuleContext, source_path: str) -> bool:
    basename = source_path.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return any(
        ".dist-info/licenses/" in path.casefold()
        and path.casefold().endswith(f"/licenses/{basename}")
        for path in artifact_member_paths(context)
    )


def _artifact_has_common_file(context: RuleContext, source_path: str, *, kind: str) -> bool:
    if context.artifact is None or context.artifact_has_file(source_path):
        return True
    if not _is_python_wheel(context):
        return False
    if kind == "readme":
        # A wheel carries the project description in METADATA; the source
        # README is normally present only in the sdist.
        return True
    return kind == "license" and _wheel_has_relocated_license(context, source_path)


def _wheel_handles_expected_file(context: RuleContext, expected: str) -> bool:
    if not _is_python_wheel(context):
        return False
    declared_readme = context.package.readme
    if declared_readme is not None:
        try:
            readme_candidates = set(
                _artifact_expected_candidates(
                    context,
                    normalize_relative_path(declared_readme),
                )
            )
        except ValueError:
            readme_candidates = set()
        if readme_candidates & set(_artifact_expected_candidates(context, expected)):
            return True
    basename = expected.replace("\\", "/").rsplit("/", 1)[-1]
    if basename.upper().startswith(("LICENSE", "COPYING")):
        return _wheel_has_relocated_license(context, expected)
    return False


class MissingReadmeRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="common.missing-readme",
        title="README is missing",
        description="A release package should point users to installation and usage documentation.",
        default_severity=Severity.MEDIUM,
    )

    def evaluate(self, context: RuleContext):  # type: ignore[no-untyped-def]
        declared = context.package.readme
        patterns = _patterns_for(context, "README", ("README*",))
        repository_file = _common_repository_file(context, declared=declared, patterns=patterns)
        if repository_file is not None:
            if _artifact_has_common_file(context, repository_file, kind="readme"):
                return
            artifact = context.artifact
            assert artifact is not None
            yield self.finding(
                context,
                message=f"README {repository_file!r} is missing from the candidate artifact.",
                remediation="Include the repository README in the built release artifact.",
                location=artifact.path,
                evidence={
                    "artifact": artifact.path,
                    "missing_from": "artifact",
                    "readme": repository_file,
                },
            )
            return
        yield self.finding(
            context,
            message="No README file was found at the package or workspace root.",
            remediation=(
                "Add a README with installation, usage, and support information and include "
                "it in the release."
            ),
            location=context.package_root,
            evidence={
                "declared_readme": declared or "<none>",
                "patterns": ",".join(patterns),
                "searched_roots": ",".join(_roots_for_common_files(context)),
            },
        )


class MissingLicenseRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="common.missing-license",
        title="License file is missing",
        description="Published source should carry the license text that grants reuse rights.",
        default_severity=Severity.HIGH,
    )

    def evaluate(self, context: RuleContext):  # type: ignore[no-untyped-def]
        patterns = _patterns_for(context, "LICENSE", ("LICENSE*", "COPYING*"))
        repository_file = _common_repository_file(context, declared=None, patterns=patterns)
        if repository_file is not None:
            if _artifact_has_common_file(context, repository_file, kind="license"):
                return
            artifact = context.artifact
            assert artifact is not None
            yield self.finding(
                context,
                message=f"License file {repository_file!r} is missing from the candidate artifact.",
                remediation="Include the complete license text in the built release artifact.",
                location=artifact.path,
                evidence={
                    "artifact": artifact.path,
                    "license_file": repository_file,
                    "missing_from": "artifact",
                },
            )
            return
        yield self.finding(
            context,
            message="No license text was found at the package or workspace root.",
            remediation=(
                "Add the complete license text (for example LICENSE) and ensure packaging "
                "includes it."
            ),
            location=context.package_root,
            evidence={
                "license_expression": context.package.license_expression or "<none>",
                "patterns": ",".join(patterns),
                "searched_roots": ",".join(_roots_for_common_files(context)),
            },
        )


class MissingRequiredFileRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="common.missing-required-file",
        title="Configured required file is missing",
        description="Checks additional required file patterns configured by the repository.",
        default_severity=Severity.MEDIUM,
    )

    def evaluate(self, context: RuleContext):  # type: ignore[no-untyped-def]
        special_prefixes = ("README", "LICENSE")
        patterns = tuple(
            item
            for item in context.config.required_files
            if not item.upper().startswith(special_prefixes)
        )
        roots = _roots_for_common_files(context)
        for pattern in patterns:
            if any(any_path_matches(context.files_below(root), (pattern,)) for root in roots):
                continue
            yield self.finding(
                context,
                message=f"No file matches the configured requirement {pattern!r}.",
                remediation=(
                    f"Add a file matching {pattern!r} or remove the requirement from configuration."
                ),
                location=context.package_root,
                evidence={"pattern": pattern, "searched_roots": ",".join(roots)},
            )


class MissingExpectedFileRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="common.missing-expected-file",
        title="Manifest-declared package file is missing",
        description=(
            "Files declared by package metadata must exist in source and in a candidate artifact."
        ),
        default_severity=Severity.MEDIUM,
    )

    def evaluate(self, context: RuleContext):  # type: ignore[no-untyped-def]
        artifact_paths = artifact_member_paths(context)
        for raw_expected in sorted(set(context.package.expected_files)):
            try:
                expected = normalize_relative_path(raw_expected)
            except ValueError:
                yield self.finding(
                    context,
                    message=f"Expected file path {raw_expected!r} is unsafe.",
                    remediation=(
                        "Replace the manifest entry with a repository-relative path that does "
                        "not traverse outside the package."
                    ),
                    location=context.package.manifest,
                    evidence={"expected_file": raw_expected, "reason": "unsafe path"},
                )
                continue

            repository_candidates = _expected_path_candidates(context, expected)
            repository_present = any(
                context.repo_has_file(candidate) for candidate in repository_candidates
            ) or any(
                _contains_expected_path(context.repository_files, candidate)
                for candidate in repository_candidates
            )
            artifact_candidates = _artifact_expected_candidates(context, expected)
            artifact_present = (
                context.artifact is None
                or any(context.artifact_has_file(candidate) for candidate in artifact_candidates)
                or any(
                    _contains_expected_path(artifact_paths, candidate)
                    for candidate in artifact_candidates
                )
                or _wheel_handles_expected_file(context, expected)
            )

            missing: list[str] = []
            if not repository_present:
                missing.append("repository")
            if not artifact_present:
                missing.append("artifact")
            if not missing:
                continue
            yield self.finding(
                context,
                message=(
                    f"Expected package file {raw_expected!r} is missing from {', '.join(missing)}."
                ),
                remediation=(
                    "Add the declared file or pattern to the repository and ensure the package "
                    "build includes it."
                ),
                location=context.package.manifest,
                evidence={
                    "expected_file": raw_expected,
                    "missing_from": ",".join(missing),
                    "package_root": context.package_root,
                },
            )


class MissingEntrypointRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="common.missing-entrypoint",
        title="Package entrypoint is missing",
        description=(
            "Declared package entrypoints must exist in source and in a candidate artifact."
        ),
        default_severity=Severity.HIGH,
    )

    def evaluate(self, context: RuleContext):  # type: ignore[no-untyped-def]
        if not context.package.entrypoints:
            python_sources = tuple(
                path
                for path in context.package_files
                if path.endswith(".py") and ("/__init__.py" in path or path.startswith("src/"))
            )
            if context.package.ecosystem.value == "python" and python_sources:
                return
            yield self.finding(
                context,
                message=(
                    "The package discovery result contains no import, library, or executable "
                    "entrypoint."
                ),
                remediation=(
                    "Declare at least one real package entrypoint in the ecosystem manifest."
                ),
                location=context.package.manifest,
                evidence={"entrypoint_count": 0},
            )
            return

        for entrypoint in sorted(context.package.entrypoints):
            candidates = declared_path_candidates(
                context.package.ecosystem, entrypoint, kind="entrypoint"
            )
            if not candidates:
                yield self.finding(
                    context,
                    message=f"Entrypoint {entrypoint!r} is unsafe or cannot be resolved.",
                    remediation=(
                        "Use a package-relative entrypoint path that stays inside the package root."
                    ),
                    location=context.package.manifest,
                    evidence={"entrypoint": entrypoint, "reason": "unsafe path"},
                )
                continue
            exists, missing = candidates_exist(context, candidates)
            if exists:
                continue
            yield self.finding(
                context,
                message=f"Entrypoint {entrypoint!r} is missing from {', '.join(missing)}.",
                remediation=(
                    "Build or include the declared entrypoint before publishing the artifact."
                ),
                location=(
                    candidates[0]
                    if candidates[0].startswith(f"{context.package_root}/")
                    else join_relative(context.package_root, candidates[0])
                ),
                evidence={
                    "candidates": ",".join(candidates),
                    "entrypoint": entrypoint,
                    "missing_from": ",".join(missing),
                },
            )


class PlaceholderVersionRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="common.placeholder-version",
        title="Package version is a placeholder",
        description=(
            "Placeholder versions make release identity and dependency resolution ambiguous."
        ),
        default_severity=Severity.HIGH,
    )

    def evaluate(self, context: RuleContext):  # type: ignore[no-untyped-def]
        version, source = package_version_for_validation(context)
        if version is None or not is_placeholder_version(version):
            return
        yield self.finding(
            context,
            message=f"Version {version!r} looks like an unreplaced placeholder.",
            remediation=(
                "Set the final release version consistently in the manifest and generated metadata."
            ),
            location=context.package.manifest,
            evidence={"version": version, "version_source": source},
        )


class InvalidVersionRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="common.invalid-version",
        title="Package version is invalid",
        description="Versions must conform to the syntax expected by the target ecosystem.",
        default_severity=Severity.HIGH,
    )

    def evaluate(self, context: RuleContext):  # type: ignore[no-untyped-def]
        version, source = package_version_for_validation(context)
        if version is None:
            return
        if is_placeholder_version(version) or is_valid_version(context.package.ecosystem, version):
            return
        yield self.finding(
            context,
            message=f"Version {version!r} is not valid for {context.package.ecosystem.value}.",
            remediation="Use a valid SemVer version for npm/Rust or a PEP 440 version for Python.",
            location=context.package.manifest,
            evidence={
                "ecosystem": context.package.ecosystem.value,
                "version": version,
                "version_source": source,
            },
        )


class ArtifactMetadataMismatchRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="common.artifact-metadata-mismatch",
        title="Artifact metadata disagrees with the package manifest",
        description=(
            "Parsed artifact name and version metadata must identify the package being checked."
        ),
        default_severity=Severity.HIGH,
    )

    def evaluate(self, context: RuleContext):  # type: ignore[no-untyped-def]
        artifact = context.artifact
        if artifact is None:
            return
        metadata = artifact.metadata
        if "package_name" not in metadata and "package_version" not in metadata:
            return

        problems: list[str] = []
        actual_name = metadata.get("package_name")
        if "package_name" in metadata:
            if not isinstance(actual_name, str) or not actual_name.strip():
                problems.append("artifact package_name is not a non-empty string")
            elif normalize_package_name(
                context.package.ecosystem, actual_name
            ) != normalize_package_name(context.package.ecosystem, context.package.name):
                problems.append(
                    f"artifact name {actual_name!r} does not match {context.package.name!r}"
                )

        actual_version = metadata.get("package_version")
        if "package_version" in metadata:
            if not isinstance(actual_version, str) or not actual_version.strip():
                problems.append("artifact package_version is not a non-empty string")
            else:
                actual_version = actual_version.strip()
                if is_placeholder_version(actual_version) or not is_valid_version(
                    context.package.ecosystem, actual_version
                ):
                    problems.append(f"artifact version {actual_version!r} is not publishable")
                elif not package_uses_dynamic_version(context) and not versions_equivalent(
                    context.package.ecosystem,
                    context.package.version,
                    actual_version,
                ):
                    problems.append(
                        f"artifact version {actual_version!r} does not match "
                        f"{context.package.version!r}"
                    )

        if not problems:
            return
        yield self.finding(
            context,
            message="Artifact metadata validation failed: " + "; ".join(problems) + ".",
            remediation=(
                "Rebuild the artifact from this package and ensure its parsed name and version "
                "match the intended release."
            ),
            location=artifact.path,
            evidence={
                "artifact": artifact.path,
                "artifact_name": actual_name if isinstance(actual_name, str) else "<invalid>",
                "artifact_version": (
                    actual_version if isinstance(actual_version, str) else "<invalid>"
                ),
                "manifest_name": context.package.name,
                "manifest_version": context.package.version,
                "problems": " | ".join(problems),
            },
        )


class SensitiveFileRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="common.sensitive-file",
        title="Sensitive file may be published",
        description="Credential and secret-bearing file names should never be part of a release.",
        default_severity=Severity.CRITICAL,
    )

    def evaluate(self, context: RuleContext):  # type: ignore[no-untyped-def]
        patterns = context.config.sensitive_patterns
        for relative in context.package_files:
            repository_path = join_relative(context.package_root, relative)
            pattern = next(
                (
                    item
                    for item in patterns
                    if path_matches(relative, item) or path_matches(repository_path, item)
                ),
                None,
            )
            if pattern is None:
                continue
            yield self.finding(
                context,
                message=f"Repository file {repository_path!r} matches a sensitive-file pattern.",
                remediation=(
                    "Remove the file from version control and release inputs; rotate any "
                    "exposed credential."
                ),
                location=repository_path,
                evidence={"path": repository_path, "pattern": pattern, "source": "repository"},
            )

        if context.artifact is None:
            return
        for entry in context.artifact_entries:
            if entry.kind != "file":
                continue
            candidates = context.artifact_relative_paths(entry)
            pattern = next(
                (item for item in patterns if any(path_matches(path, item) for path in candidates)),
                None,
            )
            if pattern is None:
                continue
            yield self.finding(
                context,
                message=f"Artifact member {entry.path!r} matches a sensitive-file pattern.",
                remediation=(
                    "Exclude the file from the artifact and rotate any credential it may contain."
                ),
                location=f"{context.artifact.path}!{entry.path}",
                evidence={"path": entry.path, "pattern": pattern, "source": "artifact"},
            )


class LargeFileRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="common.large-file",
        title="Package contains an unusually large file",
        description="Large individual files increase registry, install, and review risk.",
        default_severity=Severity.MEDIUM,
    )

    def evaluate(self, context: RuleContext):  # type: ignore[no-untyped-def]
        limit = context.config.archive.max_entry_bytes
        for relative in context.package_files:
            repository_path = join_relative(context.package_root, relative)
            size = context.repo_file_size(repository_path)
            if size is None or size <= limit:
                continue
            yield self.finding(
                context,
                message=(
                    f"Repository file {repository_path!r} is {size} bytes, above the "
                    f"{limit}-byte limit."
                ),
                remediation=(
                    "Remove, compress, split, or externally host the file before packaging."
                ),
                location=repository_path,
                evidence={
                    "limit_bytes": limit,
                    "path": repository_path,
                    "size_bytes": size,
                    "source": "repository",
                },
            )

        if context.artifact is None:
            return
        for entry in context.artifact_entries:
            if entry.kind != "file" or entry.size <= limit:
                continue
            yield self.finding(
                context,
                message=(
                    f"Artifact member {entry.path!r} is {entry.size} bytes, above the "
                    f"{limit}-byte limit."
                ),
                remediation="Exclude or reduce the member and rebuild the package artifact.",
                location=f"{context.artifact.path}!{entry.path}",
                evidence={
                    "limit_bytes": limit,
                    "path": entry.path,
                    "size_bytes": entry.size,
                    "source": "artifact",
                },
            )


class InternalDependencyDriftRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="common.internal-dependency-drift",
        title="Internal dependency version has drifted",
        description=(
            "Workspace dependencies should accept the version being released from the same "
            "repository."
        ),
        default_severity=Severity.HIGH,
    )

    def evaluate(self, context: RuleContext):  # type: ignore[no-untyped-def]
        packages_by_name = {
            normalize_package_name(item.ecosystem, item.name): item
            for item in context.packages
            if item.ecosystem is context.package.ecosystem
        }
        for dependency in sorted(
            context.package.internal_dependencies,
            key=lambda item: (item.kind, item.name, item.requirement),
        ):
            normalized_dependency = normalize_package_name(
                context.package.ecosystem, dependency.name
            )
            target = packages_by_name.get(normalized_dependency)
            if target is None or requirement_allows_version(dependency.requirement, target.version):
                continue
            yield self.finding(
                context,
                message=(
                    f"Internal dependency {dependency.name!r} requires {dependency.requirement!r}, "
                    f"which does not accept workspace version {target.version!r}."
                ),
                remediation=(
                    "Update the dependency constraint or align package versions before publishing."
                ),
                location=context.package.manifest,
                evidence={
                    "declared_requirement": dependency.requirement,
                    "dependency": dependency.name,
                    "dependency_kind": dependency.kind,
                    "internal_version": target.version,
                    "normalized_dependency": normalized_dependency,
                    "target_package": target.identity,
                },
            )


COMMON_RULES = (
    MissingReadmeRule(),
    MissingLicenseRule(),
    MissingRequiredFileRule(),
    MissingExpectedFileRule(),
    MissingEntrypointRule(),
    PlaceholderVersionRule(),
    InvalidVersionRule(),
    ArtifactMetadataMismatchRule(),
    SensitiveFileRule(),
    LargeFileRule(),
    InternalDependencyDriftRule(),
)
