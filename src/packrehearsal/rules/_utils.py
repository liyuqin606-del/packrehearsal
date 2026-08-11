"""Implementation helpers shared by built-in rules."""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any

from packrehearsal.models import Ecosystem
from packrehearsal.rules.base import RuleContext, join_relative, normalize_relative_path

_SEMVER = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_PEP440 = re.compile(
    r"^v?(?:(?:[1-9]\d*)!)?(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*))*"
    r"(?:[-_.]?(?:a|b|c|rc|alpha|beta|pre|preview)[-_.]?\d*)?"
    r"(?:(?:-(?:0|[1-9]\d*))|(?:[-_.]?(?:post|rev|r)[-_.]?\d*))?"
    r"(?:[-_.]?dev[-_.]?\d*)?(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?$",
    re.IGNORECASE,
)
_PLACEHOLDERS = {
    "0.0.0",
    "dev",
    "development",
    "none",
    "placeholder",
    "todo",
    "tbd",
    "unknown",
    "x.y.z",
}


def is_placeholder_version(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        normalized in _PLACEHOLDERS
        or normalized.startswith(("${", "{{", "<"))
        or bool(
            re.fullmatch(
                r"0\.0\.0[-_.]?(?:dev|development|placeholder|unknown|snapshot).*", normalized
            )
        )
    )


def is_valid_version(ecosystem: Ecosystem, value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    if ecosystem is Ecosystem.PYTHON:
        return bool(_PEP440.fullmatch(normalized))
    return bool(_SEMVER.fullmatch(normalized))


def normalize_package_name(ecosystem: Ecosystem, value: str) -> str:
    """Return the registry-facing comparison form of a package name."""

    normalized = value.strip().casefold()
    if ecosystem is Ecosystem.PYTHON:
        return re.sub(r"[-_.]+", "-", normalized)
    if ecosystem is Ecosystem.RUST:
        return re.sub(r"[-_]+", "-", normalized)
    return normalized


def package_uses_dynamic_version(context: RuleContext) -> bool:
    """Whether a Python package delegates its version to its build backend."""

    return context.package.ecosystem is Ecosystem.PYTHON and (
        context.package.metadata.get("dynamic_version") is True
        or context.package.version.strip().casefold() == "<dynamic>"
    )


def package_version_for_validation(context: RuleContext) -> tuple[str | None, str]:
    """Return the real version to validate and its evidence source.

    Static versions always come from the manifest.  A PEP 621 dynamic sentinel
    is not a release version; only parsed artifact metadata can resolve it.
    """

    if not package_uses_dynamic_version(context):
        return context.package.version, "manifest"
    if context.artifact is not None:
        value = context.artifact.metadata.get("package_version")
        if isinstance(value, str) and value.strip():
            return value.strip(), "artifact.metadata.package_version"
    return None, "dynamic-unresolved"


def versions_equivalent(ecosystem: Ecosystem, left: str, right: str) -> bool:
    """Compare versions after conservative ecosystem-specific normalization."""

    if ecosystem is Ecosystem.PYTHON:
        if not is_valid_version(ecosystem, left) or not is_valid_version(ecosystem, right):
            return left.strip() == right.strip()
        return _normalized_pep440_version(left) == _normalized_pep440_version(right)
    return left.strip() == right.strip()


def _normalized_pep440_version(value: str) -> tuple[object, ...]:
    """Build an equality key for the PEP 440 forms accepted by this project."""

    normalized = value.strip().casefold()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    public, separator, local = normalized.partition("+")
    epoch_text, epoch_separator, public = public.partition("!")
    epoch = int(epoch_text) if epoch_separator else 0
    if not epoch_separator:
        public = epoch_text

    release_match = re.match(r"\d+(?:\.\d+)*", public)
    if release_match is None:  # guarded by ``is_valid_version``
        return (normalized,)
    release = [int(item) for item in release_match.group(0).split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()

    suffix = public[release_match.end() :]
    if re.fullmatch(r"-\d+", suffix):
        suffix = f"post{suffix[1:]}"
    suffix = re.sub(r"[-_.]?(?:alpha)[-_.]?", "a", suffix)
    suffix = re.sub(r"[-_.]?(?:beta)[-_.]?", "b", suffix)
    suffix = re.sub(r"[-_.]?(?:c|pre|preview)[-_.]?", "rc", suffix)
    suffix = re.sub(r"[-_.]?(?:rev|r)[-_.]?", "post", suffix)
    suffix = re.sub(r"[-_.]", "", suffix)
    suffix = re.sub(r"(?:a|b|rc|post|dev)$", lambda match: f"{match.group(0)}0", suffix)
    local_key = re.sub(r"[-_]", ".", local) if separator else ""
    return (epoch, tuple(release), suffix, local_key)


def path_matches(path: str, pattern: str) -> bool:
    """Case-insensitive matching suitable for portable repository paths."""

    candidate = normalize_relative_path(path).lower()
    normalized_pattern = pattern.replace("\\", "/").removeprefix("./").lower()
    return fnmatch.fnmatchcase(candidate, normalized_pattern) or PurePosixPath(candidate).match(
        normalized_pattern
    )


def any_path_matches(paths: Iterable[str], patterns: Iterable[str]) -> bool:
    return any(path_matches(path, pattern) for path in paths for pattern in patterns)


def declared_path_candidates(ecosystem: Ecosystem, value: str, *, kind: str) -> tuple[str, ...]:
    """Return conservative file-resolution candidates for a manifest path."""

    logical_value = value
    if ecosystem is Ecosystem.PYTHON and "=" in value:
        logical_value = value.split("=", 1)[1].split(":", 1)[0].replace(".", "/")
    try:
        path = normalize_relative_path(logical_value)
    except ValueError:
        return ()
    candidates = {path}
    suffix = PurePosixPath(path).suffix
    if ecosystem is Ecosystem.NPM:
        if kind == "types":
            if not suffix:
                candidates.add(f"{path}.d.ts")
            candidates.add(f"{path}/index.d.ts")
        elif kind == "main":
            if not suffix:
                candidates.update(f"{path}{extension}" for extension in (".js", ".json", ".node"))
            candidates.update(f"{path}/index{extension}" for extension in (".js", ".json", ".node"))
    elif ecosystem is Ecosystem.PYTHON:
        candidates.update(
            {
                f"{path}.py",
                f"{path}/__init__.py",
                f"src/{path}.py",
                f"src/{path}/__init__.py",
            }
        )
    return tuple(sorted(candidates))


def candidates_exist(
    context: RuleContext,
    candidates: Iterable[str],
    *,
    require_artifact: bool = True,
) -> tuple[bool, tuple[str, ...]]:
    """Return existence plus a stable list of missing sources."""

    normalized = tuple(candidates)
    repo_ok = any(context.repo_has_file(item) for item in normalized)
    artifact_ok = context.artifact is None or any(
        context.artifact_has_file(item) for item in normalized
    )
    missing: list[str] = []
    if not repo_ok:
        missing.append("repository")
    if require_artifact and not artifact_ok:
        missing.append("artifact")
    return not missing, tuple(missing)


def load_json_manifest(context: RuleContext) -> tuple[Mapping[str, Any] | None, str | None]:
    try:
        payload = json.loads(context.read_repository_text(context.manifest_path()))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(payload, Mapping):
        return None, "manifest root is not an object"
    return payload, None


def load_toml_manifest(context: RuleContext) -> tuple[Mapping[str, Any] | None, str | None]:
    try:
        payload = tomllib.loads(context.read_repository_text(context.manifest_path()))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        return None, str(exc)
    return payload, None


def nested_mapping(value: object, *keys: str) -> Mapping[str, Any] | None:
    current: object = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, Mapping) else None


def requirement_allows_version(requirement: str, version: str) -> bool:
    """Conservatively evaluate common npm, Cargo, and Python constraints."""

    spec = requirement.strip()
    if not spec:
        return False
    if spec.startswith("workspace:"):
        spec = spec.removeprefix("workspace:").strip()
    if spec.lower().startswith(("file:", "link:", "path:", "git+", "http://", "https://")):
        return True
    if spec in {"*", "x", "X", "latest", "^", "~"}:
        return True
    if ";" in spec:
        spec = spec.split(";", 1)[0].strip()
    if "||" in spec:
        return any(requirement_allows_version(part, version) for part in spec.split("||"))

    target = _numeric_version(version)
    if target is None:
        return requirement.lstrip("=") == version

    hyphen = re.fullmatch(r"\s*([v\d][^ ]*)\s+-\s+([v\d][^ ]*)\s*", spec)
    if hyphen:
        lower = _numeric_version(hyphen.group(1))
        upper = _numeric_version(hyphen.group(2))
        return (
            lower is not None
            and upper is not None
            and _compare(target, lower) >= 0
            and _compare(target, upper) <= 0
        )

    pieces = [item for item in re.split(r"[ ,]+", spec) if item]
    if len(pieces) > 1 and all(re.match(r"^(?:~=|<=|>=|!=|==|=|<|>)", item) for item in pieces):
        return all(_comparison_allows(item, target) for item in pieces)
    if spec.startswith((">", "<", "=", "!", "~=")):
        return _comparison_allows(spec, target)

    operator = spec[0] if spec[0] in {"^", "~"} else ""
    raw = spec[1:] if operator else spec
    raw = raw.lstrip("v")
    if re.search(r"(?:^|\.)(?:x|X|\*)$", raw):
        prefix = tuple(int(item) for item in raw.split(".") if item not in {"x", "X", "*"})
        return target[: len(prefix)] == prefix
    base = _numeric_version(raw)
    if base is None:
        return spec == version
    supplied_parts = len(re.match(r"\d+(?:\.\d+)*", raw).group(0).split("."))  # type: ignore[union-attr]
    if operator == "^":
        if _compare(target, base) < 0:
            return False
        pivot = next((index for index, item in enumerate(base) if item), len(base) - 1)
        return target[: pivot + 1] == base[: pivot + 1]
    if operator == "~":
        return _compare(target, base) >= 0 and target[:2] == base[:2]
    if supplied_parts < 3:
        return target[:supplied_parts] == base[:supplied_parts]
    return target == base


def _numeric_version(value: str) -> tuple[int, ...] | None:
    match = re.match(r"^v?(\d+(?:\.\d+)*)", value.strip())
    if not match:
        return None
    result = tuple(int(item) for item in match.group(1).split("."))
    return (*result, *((0,) * (3 - len(result))))


def _compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    length = max(len(left), len(right))
    padded_left = (*left, *((0,) * (length - len(left))))
    padded_right = (*right, *((0,) * (length - len(right))))
    return (padded_left > padded_right) - (padded_left < padded_right)


def _comparison_allows(spec: str, target: tuple[int, ...]) -> bool:
    match = re.fullmatch(r"(~=|<=|>=|!=|==|=|<|>)\s*v?(\d+(?:\.\d+)*)(\.\*)?", spec)
    if not match:
        return False
    expected = _numeric_version(match.group(2))
    if expected is None:
        return False
    operator = match.group(1)
    wildcard = match.group(3) is not None
    supplied = tuple(int(item) for item in match.group(2).split("."))
    if wildcard:
        if operator not in {"==", "!="}:
            return False
        matches = target[: len(supplied)] == supplied
        return matches if operator == "==" else not matches
    if operator == "~=":
        if len(supplied) < 2 or _compare(target, expected) < 0:
            return False
        compatible_prefix = supplied[:-1]
        return target[: len(compatible_prefix)] == compatible_prefix
    comparison = _compare(target, expected)
    return {
        "<": comparison < 0,
        "<=": comparison <= 0,
        "=": comparison == 0,
        "==": comparison == 0,
        "!=": comparison != 0,
        ">=": comparison >= 0,
        ">": comparison > 0,
    }[operator]


def artifact_member_paths(context: RuleContext) -> tuple[str, ...]:
    result: set[str] = set()
    for entry in context.artifact_entries:
        if entry.kind == "file":
            result.update(context.artifact_relative_paths(entry))
    return tuple(sorted(result))


def repository_relative_for_package(context: RuleContext, package_relative: str) -> str:
    return join_relative(context.package_root, package_relative)
