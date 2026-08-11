from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from packrehearsal.config import Config
from packrehearsal.models import (
    ArtifactEntry,
    ArtifactSnapshot,
    Ecosystem,
    Evidence,
    Finding,
    Package,
    RuleDescriptor,
    Severity,
)
from packrehearsal.rules._utils import (
    any_path_matches,
    artifact_member_paths,
    candidates_exist,
    declared_path_candidates,
    is_placeholder_version,
    is_valid_version,
    load_json_manifest,
    load_toml_manifest,
    nested_mapping,
    path_matches,
    repository_relative_for_package,
    requirement_allows_version,
)
from packrehearsal.rules.base import (
    Rule,
    RuleContext,
    join_relative,
    normalize_relative_path,
    path_is_within,
    relative_to_root,
)
from packrehearsal.rules.registry import RuleRegistry, deduplicate_findings


def _package(
    ecosystem: Ecosystem = Ecosystem.NPM,
    *,
    name: str = "demo",
    root: str = ".",
    manifest: str = "package.json",
    workspace_root: str | None = None,
) -> Package:
    return Package(
        ecosystem=ecosystem,
        name=name,
        version="1.2.3",
        root=root,
        manifest=manifest,
        workspace_root=workspace_root,
    )


def _artifact(*entries: ArtifactEntry) -> ArtifactSnapshot:
    return ArtifactSnapshot(
        path="demo.tgz",
        format="tar.gz",
        sha256="a" * 64,
        size=10,
        entries=entries,
    )


def _context(
    root: Path,
    *,
    package: Package | None = None,
    files: tuple[str, ...] = (),
    artifact: ArtifactSnapshot | None = None,
    packages: tuple[Package, ...] = (),
    config: Config | None = None,
) -> RuleContext:
    return RuleContext(
        root=root,
        package=package or _package(),
        repository_files=files,
        artifact=artifact,
        packages=packages,
        config=config or Config(),
    )


class _ProbeRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="test.probe",
        title="Probe",
        description="Exercise the base rule contract.",
        default_severity=Severity.HIGH,
        ecosystems=(Ecosystem.NPM,),
    )

    def __init__(self, modes: tuple[str, ...] = ("valid",)) -> None:
        self.modes = modes

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        for mode in self.modes:
            if mode == "wrong-id":
                yield Finding(
                    rule_id="test.other",
                    severity=Severity.LOW,
                    title="Wrong",
                    message="Wrong rule ID",
                    remediation="Fix it",
                    evidence=(Evidence("mode", mode),),
                )
            elif mode == "no-remediation":
                yield self.finding(
                    context,
                    message="Missing remediation",
                    remediation=" ",
                    evidence={"mode": mode},
                )
            elif mode == "no-evidence":
                yield self.finding(
                    context,
                    message="Missing evidence",
                    remediation="Fix it",
                    evidence=(),
                )
            else:
                yield self.finding(
                    context,
                    message=f"Finding at {mode}",
                    remediation="Fix it",
                    evidence={"z": 2, "a": 1},
                    location=None if mode == "root" else mode,
                )


class _LowRule(Rule):
    descriptor = RuleDescriptor(
        rule_id="test.low",
        title="Low",
        description="Exercise registry ordering.",
        default_severity=Severity.LOW,
    )

    def evaluate(self, context: RuleContext) -> Iterable[Finding]:
        yield self.finding(
            context,
            message="Low finding",
            remediation="Fix it",
            evidence={"source": "low"},
            location="z",
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("./a\\b", "a/b"),
        (".", "."),
        ("", "."),
    ],
)
def test_normalize_relative_path(value: str, expected: str) -> None:
    assert normalize_relative_path(value) == expected


@pytest.mark.parametrize("value", ["/absolute", "a/../escape"])
def test_normalize_relative_path_rejects_escape(value: str) -> None:
    with pytest.raises(ValueError, match="inside the repository"):
        normalize_relative_path(value)


def test_relative_path_helpers_cover_roots_and_failures() -> None:
    assert join_relative("root", ".") == "root"
    assert join_relative(".", "child") == "child"
    assert join_relative("root", "child") == "root/child"
    assert path_is_within("anything/here", ".")
    assert path_is_within("root", "root")
    assert path_is_within("root/child", "root")
    assert not path_is_within("rooted/child", "root")
    assert relative_to_root("root/child", ".") == "root/child"
    assert relative_to_root("root", "root") == "."
    assert relative_to_root("root/child", "root") == "child"
    with pytest.raises(ValueError, match="is not below"):
        relative_to_root("other/child", "root")


def test_context_normalizes_packages_and_attributes_nested_files(tmp_path: Path) -> None:
    parent = _package(name="parent")
    package = _package(
        name="child",
        root="packages/child",
        manifest="package.json",
        workspace_root="packages",
    )
    grandchild = _package(
        name="grandchild",
        root="packages/child/examples/nested",
        manifest="package.json",
    )
    context = _context(
        tmp_path,
        package=package,
        files=(
            "outside.txt",
            "packages/child/own.txt",
            "packages\\child\\own.txt",
            "packages/child/examples/nested/deep.txt",
        ),
        packages=(parent, grandchild),
    )

    assert context.root == tmp_path.resolve()
    assert context.package_root == "packages/child"
    assert context.workspace_root == "packages"
    assert package in context.packages
    assert context.repository_files.count("packages/child/own.txt") == 1
    assert context.package_files == ("own.txt",)
    assert context.files_below("packages/child") == (
        "examples/nested/deep.txt",
        "own.txt",
    )

    root_context = _context(tmp_path)
    assert root_context.workspace_root is None
    assert root_context.packages == (root_context.package,)


def test_context_repository_paths_and_safe_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(root="packages/demo", manifest="package.json")
    source = tmp_path / "packages/demo/data.txt"
    source.parent.mkdir(parents=True)
    source.write_text("hello", encoding="utf-8")
    directory = tmp_path / "packages/demo/folder"
    directory.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / "escape.txt").symlink_to(outside)
    context = _context(tmp_path, package=package, files=("packages/demo/data.txt",))

    assert context.repository_path("packages/demo/data.txt") == source
    assert context.repository_path("escape.txt") is None
    assert context.package_repository_path("data.txt") == source
    assert context.repo_has_file("data.txt")
    assert context.repo_has_file("packages/demo/data.txt")
    assert not context.repo_has_file("missing.txt")
    assert context.repo_file_size("packages/demo/data.txt") == 5
    assert context.repo_file_size("escape.txt") is None
    assert context.repo_file_size("packages/demo/folder") is None
    assert context.read_repository_text("packages/demo/data.txt") == "hello"
    with pytest.raises(OSError, match="unsafe repository path"):
        context.read_repository_text("escape.txt")
    with pytest.raises(OSError, match="exceeds rule read limit"):
        context.read_repository_text("packages/demo/data.txt", limit=4)

    def fail_for_source(root: Path, relative: str) -> int:
        raise OSError(f"size check failed: {root}/{relative}")

    with monkeypatch.context() as patcher:
        patcher.setattr(
            "packrehearsal.rules.base.regular_file_size_beneath",
            fail_for_source,
        )
        assert context.repo_file_size("packages/demo/data.txt") is None


def test_context_artifact_paths_and_manifest_resolution(tmp_path: Path) -> None:
    package = _package(name="demo_pkg", root="packages/demo", manifest="package.json")
    artifact = _artifact(
        ArtifactEntry("z.txt", 1),
        ArtifactEntry("package/index.js", 1),
        ArtifactEntry("demo-pkg-1.2.3/module.py", 1),
        ArtifactEntry("package/folder", 0, kind="directory"),
        ArtifactEntry("../escape", 1),
    )
    context = _context(tmp_path, package=package, artifact=artifact)

    assert [entry.path for entry in context.artifact_entries] == [
        "../escape",
        "demo-pkg-1.2.3/module.py",
        "package/folder",
        "package/index.js",
        "z.txt",
    ]
    assert context.artifact_relative_paths(artifact.entries[1]) == ("index.js", "package/index.js")
    assert context.artifact_relative_paths(artifact.entries[2]) == (
        "demo-pkg-1.2.3/module.py",
        "module.py",
    )
    assert context.artifact_relative_paths(artifact.entries[-1]) == ()
    assert context.artifact_has_file("index.js")
    assert context.artifact_has_file("packages/demo/index.js")
    assert not context.artifact_has_file("folder")
    assert context.artifact_entry_for("packages/demo/module.py") == artifact.entries[2]
    assert context.artifact_entry_for("missing") is None
    assert context.manifest_path() == "packages/demo/package.json"

    full_manifest = _package(
        root="packages/demo",
        manifest="packages/demo/package.json",
    )
    assert _context(tmp_path, package=full_manifest).manifest_path() == full_manifest.manifest
    empty_artifact_context = _context(tmp_path)
    assert empty_artifact_context.artifact_entries == ()
    assert not empty_artifact_context.artifact_has_file("index.js")
    assert empty_artifact_context.artifact_entry_for("index.js") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.0.0", True),
        (" ${VERSION}", True),
        ("0.0.0-snapshot.1", True),
        ("1.2.3", False),
    ],
)
def test_placeholder_versions(value: str, expected: bool) -> None:
    assert is_placeholder_version(value) is expected


@pytest.mark.parametrize(
    ("ecosystem", "value", "expected"),
    [
        (Ecosystem.NPM, "", False),
        (Ecosystem.NPM, "1.2.3-beta.1+build", True),
        (Ecosystem.NPM, "v1.2.3", False),
        (Ecosystem.RUST, "1.2", False),
        (Ecosystem.PYTHON, "v2!1.2rc1.post2.dev3+local.1", True),
        (Ecosystem.PYTHON, "release", False),
    ],
)
def test_version_validation(ecosystem: Ecosystem, value: str, expected: bool) -> None:
    assert is_valid_version(ecosystem, value) is expected


def test_path_matching_and_declared_candidates() -> None:
    assert path_matches("Src\\Index.JS", "./src/*.js")
    assert not path_matches("src/index.js", "lib/*.js")
    assert any_path_matches(("README.md", "src/index.js"), ("license*", "*.MD"))
    assert not any_path_matches(("src/index.js",), ("*.toml",))

    assert declared_path_candidates(Ecosystem.NPM, "dist/index", kind="main") == (
        "dist/index",
        "dist/index.js",
        "dist/index.json",
        "dist/index.node",
        "dist/index/index.js",
        "dist/index/index.json",
        "dist/index/index.node",
    )
    assert declared_path_candidates(Ecosystem.NPM, "dist/types", kind="types") == (
        "dist/types",
        "dist/types.d.ts",
        "dist/types/index.d.ts",
    )
    assert declared_path_candidates(Ecosystem.NPM, "dist/file.js", kind="main") == (
        "dist/file.js",
        "dist/file.js/index.js",
        "dist/file.js/index.json",
        "dist/file.js/index.node",
    )
    assert declared_path_candidates(Ecosystem.PYTHON, "pkg = demo.mod:main", kind="main") == (
        "demo/mod",
        "demo/mod.py",
        "demo/mod/__init__.py",
        "src/demo/mod.py",
        "src/demo/mod/__init__.py",
    )
    assert declared_path_candidates(Ecosystem.RUST, "src/lib.rs", kind="main") == ("src/lib.rs",)
    assert declared_path_candidates(Ecosystem.NPM, "../escape", kind="main") == ()


def test_candidate_existence_reports_sources(tmp_path: Path) -> None:
    (tmp_path / "present.js").write_text("x", encoding="utf-8")
    with_artifact = _context(
        tmp_path,
        files=("present.js",),
        artifact=_artifact(ArtifactEntry("package/present.js", 1)),
    )
    assert candidates_exist(with_artifact, ("present.js",)) == (True, ())
    assert candidates_exist(with_artifact, ("missing.js",)) == (
        False,
        ("repository", "artifact"),
    )

    repo_only = _context(tmp_path, files=("present.js",))
    assert candidates_exist(repo_only, ("present.js",)) == (True, ())
    assert candidates_exist(repo_only, ("missing.js",), require_artifact=False) == (
        False,
        ("repository",),
    )


def test_manifest_loading_success_and_errors(tmp_path: Path) -> None:
    json_path = tmp_path / "package.json"
    json_path.write_text('{"name": "demo"}', encoding="utf-8")
    context = _context(tmp_path)
    assert load_json_manifest(context) == ({"name": "demo"}, None)
    json_path.write_text("[]", encoding="utf-8")
    assert load_json_manifest(context) == (None, "manifest root is not an object")
    json_path.write_text("{", encoding="utf-8")
    payload, error = load_json_manifest(context)
    assert payload is None and error
    json_path.unlink()
    payload, error = load_json_manifest(context)
    assert payload is None and error

    toml_package = _package(Ecosystem.PYTHON, manifest="pyproject.toml")
    toml_path = tmp_path / "pyproject.toml"
    toml_path.write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    toml_context = _context(tmp_path, package=toml_package)
    assert load_toml_manifest(toml_context) == ({"project": {"name": "demo"}}, None)
    toml_path.write_text("[broken", encoding="utf-8")
    payload, error = load_toml_manifest(toml_context)
    assert payload is None and error


def test_nested_mapping_requires_mappings_at_every_level() -> None:
    payload = {"tool": {"build": {"wheel": True}, "scalar": 1}}
    assert nested_mapping(payload, "tool", "build") == {"wheel": True}
    assert nested_mapping(payload, "tool", "missing") is None
    assert nested_mapping(payload, "tool", "scalar", "child") is None
    assert nested_mapping("not-a-mapping", "tool") is None


@pytest.mark.parametrize(
    ("requirement", "version", "expected"),
    [
        ("", "1.2.3", False),
        ("workspace:^1.0", "1.5.0", True),
        ("file:../core", "anything", True),
        ("*", "1.2.3", True),
        (">=1.0; python_version >= '3.11'", "1.2.3", True),
        ("^1 || ^2", "2.3.0", True),
        ("=banana", "banana", True),
        ("other", "banana", False),
        ("1.0 - 2.0", "1.5.0", True),
        ("1.0 - 2.0", "2.1.0", False),
        ("vbad - 2.0", "1.0.0", False),
        ("1.0 - vbad", "1.0.0", False),
        (">=1.0, <2.0", "1.5.0", True),
        (">=1.0, <2.0", "2.0.0", False),
        ("~=1.4", "1.9.0", True),
        ("~=1.4", "2.0.0", False),
        ("~=1.4.5", "1.4.9", True),
        ("~=1.4.5", "1.5.0", False),
        ("==1.4.*", "1.4.9", True),
        ("!=1.4.*", "1.5.0", True),
        (">=nonsense", "1.0.0", False),
        ("1.x", "1.9.3", True),
        ("1.x", "2.0.0", False),
        ("nonsense", "1.0.0", False),
        ("^2.0", "1.9.9", False),
        ("^0.2.0", "0.2.9", True),
        ("~1.2", "1.2.9", True),
        ("~1.2", "1.3.0", False),
        ("1.2", "1.2.9", True),
        ("1.2.3", "1.2.3", True),
        ("1.2.3", "1.2.4", False),
        ("!=1.2.3", "1.2.4", True),
    ],
)
def test_requirement_allows_version(requirement: str, version: str, expected: bool) -> None:
    assert requirement_allows_version(requirement, version) is expected


def test_artifact_member_and_repository_package_paths(tmp_path: Path) -> None:
    context = _context(
        tmp_path,
        package=_package(root="packages/demo"),
        artifact=_artifact(
            ArtifactEntry("package/b.js", 1),
            ArtifactEntry("a.js", 1),
            ArtifactEntry("folder", 0, kind="directory"),
            ArtifactEntry("../escape", 1),
        ),
    )
    assert artifact_member_paths(context) == ("a.js", "b.js", "package/b.js")
    assert repository_relative_for_package(context, "src/index.js") == (
        "packages/demo/src/index.js"
    )


def test_rule_run_filters_validates_overrides_and_sorts(tmp_path: Path) -> None:
    context = _context(
        tmp_path,
        config=Config(severity_overrides={"test.probe": Severity.CRITICAL}),
    )
    findings = _ProbeRule(("z", "root", "a")).run(context)
    assert [finding.location for finding in findings] == [None, "a", "z"]
    assert all(finding.severity is Severity.CRITICAL for finding in findings)
    assert [(item.key, item.value) for item in findings[0].evidence] == [
        ("a", "1"),
        ("z", "2"),
    ]

    python_context = _context(tmp_path, package=_package(Ecosystem.PYTHON))
    assert _ProbeRule().run(python_context) == ()
    disabled_context = _context(
        tmp_path,
        config=Config(disabled_rules=("test.probe",)),
    )
    assert _ProbeRule().run(disabled_context) == ()

    custom = _ProbeRule().finding(
        context,
        title="Custom title",
        message="Custom",
        remediation="Fix it",
        evidence=(("b", 2), ("a", 1)),
    )
    assert custom.title == "Custom title"
    assert [item.key for item in custom.evidence] == ["a", "b"]


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("wrong-id", "emitted a finding for"),
        ("no-remediation", "without remediation"),
        ("no-evidence", "without evidence"),
    ],
)
def test_rule_run_rejects_invalid_findings(tmp_path: Path, mode: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _ProbeRule((mode,)).run(_context(tmp_path))


def test_registry_api_ordering_and_deduplication(tmp_path: Path) -> None:
    probe = _ProbeRule(("a",))
    low = _LowRule()
    registry = RuleRegistry((probe, low))

    assert len(registry) == 2
    assert "test.probe" in registry
    assert object() not in registry
    assert list(registry) == [low, probe]
    assert registry.rule_ids == ("test.low", "test.probe")
    assert registry.descriptors == (low.descriptor, probe.descriptor)
    assert registry.get("test.probe") is probe
    with pytest.raises(KeyError, match="unknown rule ID"):
        registry.get("missing")
    with pytest.raises(ValueError, match="duplicate rule ID"):
        registry.register(_ProbeRule())

    findings = registry.run(_context(tmp_path))
    assert [finding.rule_id for finding in findings] == ["test.probe", "test.low"]

    duplicate = findings[0].with_severity(Severity.INFO)
    unique = deduplicate_findings((*findings, duplicate))
    assert len(unique) == 2
    assert next(item for item in unique if item.rule_id == "test.probe").severity is Severity.INFO
    assert [item.rule_id for item in unique] == ["test.low", "test.probe"]
