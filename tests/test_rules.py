from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from packrehearsal.config import ArchiveLimits, Config
from packrehearsal.ecosystems.python import parse_python_manifest
from packrehearsal.models import (
    ArtifactEntry,
    ArtifactSnapshot,
    Ecosystem,
    InternalDependency,
    Package,
    Severity,
)
from packrehearsal.rules import RuleContext, RuleRegistry, default_registry, run_rules


def _write(root: Path, relative: str, content: str = "x") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _package(
    ecosystem: Ecosystem = Ecosystem.NPM,
    *,
    name: str = "demo",
    version: str = "1.2.3",
    root: str = ".",
    manifest: str | None = None,
    entrypoints: tuple[str, ...] = ("src/index.js",),
    dependencies: tuple[InternalDependency, ...] = (),
    expected_files: tuple[str, ...] = (),
    readme: str | None = None,
    license_expression: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Package:
    manifests = {
        Ecosystem.NPM: "package.json",
        Ecosystem.PYTHON: "pyproject.toml",
        Ecosystem.RUST: "Cargo.toml",
    }
    return Package(
        ecosystem=ecosystem,
        name=name,
        version=version,
        root=root,
        manifest=manifest or manifests[ecosystem],
        license_expression=license_expression,
        readme=readme,
        entrypoints=entrypoints,
        expected_files=expected_files,
        internal_dependencies=dependencies,
        metadata=metadata or {},
    )


def _context(
    root: Path,
    package: Package,
    *,
    files: tuple[str, ...],
    config: Config | None = None,
    artifact: ArtifactSnapshot | None = None,
    packages: tuple[Package, ...] = (),
) -> RuleContext:
    return RuleContext(
        root=root,
        package=package,
        config=config or Config(),
        repository_files=files,
        artifact=artifact,
        packages=packages,
    )


def test_default_registry_has_unique_stable_ids() -> None:
    registry = default_registry()
    assert registry.rule_ids == tuple(sorted(registry.rule_ids))
    assert len(registry.rule_ids) == len(set(registry.rule_ids))
    assert {
        "common.sensitive-file",
        "npm.invalid-main",
        "python.invalid-wheel",
        "rust.invalid-include",
    } <= set(registry.rule_ids)
    with pytest.raises(ValueError, match="duplicate rule ID"):
        RuleRegistry((next(iter(registry)), next(iter(registry))))


def test_valid_npm_package_is_clean(tmp_path: Path) -> None:
    manifest = {"name": "demo", "version": "1.2.3", "main": "src/index.js"}
    _write(tmp_path, "package.json", json.dumps(manifest))
    _write(tmp_path, "README.md")
    _write(tmp_path, "LICENSE")
    _write(tmp_path, "src/index.js")
    files = ("LICENSE", "README.md", "package.json", "src/index.js")
    assert run_rules(_context(tmp_path, _package(), files=files)) == ()


def test_rule_enable_disable_and_severity_override(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", '{"name":"demo","version":"1.2.3"}')
    package = _package(entrypoints=())
    config = Config(
        enabled_rules=("common.missing-readme",),
        severity_overrides={"common.missing-readme": Severity.CRITICAL},
    )
    findings = run_rules(_context(tmp_path, package, files=("package.json",), config=config))
    assert [item.rule_id for item in findings] == ["common.missing-readme"]
    assert findings[0].severity is Severity.CRITICAL
    assert findings[0].evidence and findings[0].remediation

    disabled = Config(disabled_rules=("common.missing-readme",))
    findings = run_rules(_context(tmp_path, package, files=("package.json",), config=disabled))
    assert "common.missing-readme" not in {item.rule_id for item in findings}


@pytest.mark.parametrize(
    ("version", "rule_id"),
    [("0.0.0", "common.placeholder-version"), ("release-one", "common.invalid-version")],
)
def test_placeholder_and_invalid_versions(tmp_path: Path, version: str, rule_id: str) -> None:
    package = _package(version=version)
    config = Config(enabled_rules=(rule_id,))
    findings = run_rules(_context(tmp_path, package, files=(), config=config))
    assert [item.rule_id for item in findings] == [rule_id]
    assert findings[0].evidence[0].value


def test_pep621_dynamic_version_is_resolved_only_from_artifact_metadata(
    tmp_path: Path,
) -> None:
    package = _package(
        Ecosystem.PYTHON,
        version="<dynamic>",
        entrypoints=(),
        metadata={"dynamic_version": True},
    )
    enabled = (
        "common.artifact-metadata-mismatch",
        "common.invalid-version",
        "common.placeholder-version",
        "python.dynamic-version-unresolved",
    )
    config = Config(enabled_rules=enabled)

    unresolved = run_rules(_context(tmp_path, package, files=(), config=config))
    assert [item.rule_id for item in unresolved] == ["python.dynamic-version-unresolved"]
    assert unresolved[0].severity is Severity.LOW

    valid = ArtifactSnapshot(
        path="demo-1.4.0-py3-none-any.whl",
        format="wheel",
        sha256="a" * 64,
        size=10,
        entries=(),
        metadata={"package_name": "demo", "package_version": "1.4.0"},
    )
    assert run_rules(_context(tmp_path, package, files=(), config=config, artifact=valid)) == ()

    placeholder = ArtifactSnapshot(
        path="demo-0.0.0-py3-none-any.whl",
        format="wheel",
        sha256="b" * 64,
        size=10,
        entries=(),
        metadata={"package_name": "demo", "package_version": "0.0.0"},
    )
    findings = run_rules(_context(tmp_path, package, files=(), config=config, artifact=placeholder))
    assert {item.rule_id for item in findings} == {
        "common.artifact-metadata-mismatch",
        "common.placeholder-version",
    }
    assert all(item.severity is Severity.HIGH for item in findings)

    invalid = ArtifactSnapshot(
        path="demo-release-py3-none-any.whl",
        format="wheel",
        sha256="c" * 64,
        size=10,
        entries=(),
        metadata={"package_name": "demo", "package_version": "release"},
    )
    findings = run_rules(_context(tmp_path, package, files=(), config=config, artifact=invalid))
    assert {item.rule_id for item in findings} == {
        "common.artifact-metadata-mismatch",
        "common.invalid-version",
    }


def test_sensitive_and_large_files_check_repository_and_artifact(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "secret")
    _write(tmp_path, "large.bin", "12345")
    artifact = ArtifactSnapshot(
        path="demo.tgz",
        format="tar.gz",
        sha256="a" * 64,
        size=12,
        entries=(
            ArtifactEntry("package/.env", 6),
            ArtifactEntry("package/large.bin", 5),
        ),
    )
    config = Config(
        enabled_rules=("common.sensitive-file", "common.large-file"),
        archive=ArchiveLimits(max_entry_bytes=4),
    )
    findings = run_rules(
        _context(
            tmp_path,
            _package(),
            files=(".env", "large.bin"),
            config=config,
            artifact=artifact,
        )
    )
    assert [item.rule_id for item in findings].count("common.sensitive-file") == 2
    assert [item.rule_id for item in findings].count("common.large-file") == 4
    assert all(item.evidence and item.remediation for item in findings)


def test_internal_dependency_version_drift(tmp_path: Path) -> None:
    dependency = _package(name="core", version="2.0.0", root="core", manifest="core/package.json")
    consumer = _package(
        name="app",
        root="app",
        manifest="app/package.json",
        dependencies=(InternalDependency("core", "^1.0.0"),),
    )
    config = Config(enabled_rules=("common.internal-dependency-drift",))
    findings = run_rules(
        _context(
            tmp_path,
            consumer,
            files=(),
            config=config,
            packages=(consumer, dependency),
        )
    )
    assert [item.rule_id for item in findings] == ["common.internal-dependency-drift"]
    assert {item.key: item.value for item in findings[0].evidence}["internal_version"] == "2.0.0"


def test_pep508_dependencies_are_split_normalized_and_checked_with_pep440(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text(
        """[project]
name = "consumer"
dynamic = ["version"]
dependencies = [
  "Core_Pkg[fast] >= 1.2, < 2; python_version >= '3.11'",
  "NoSpec; os_name == 'posix'",
  "Direct @ https://example.invalid/direct.whl; python_version < '4'",
]
""",
        encoding="utf-8",
    )
    consumer = parse_python_manifest(manifest, tmp_path)
    assert consumer is not None
    assert consumer.version == "<dynamic>"
    assert [(item.name, item.requirement) for item in consumer.internal_dependencies] == [
        ("core-pkg", ">=1.2,<2; python_version >= '3.11'"),
        ("direct", "https://example.invalid/direct.whl; python_version < '4'"),
        ("nospec", "*; os_name == 'posix'"),
    ]

    target = _package(
        Ecosystem.PYTHON,
        name="Core.Pkg",
        version="1.5.0",
        root="core",
        manifest="core/pyproject.toml",
        entrypoints=(),
    )
    config = Config(enabled_rules=("common.internal-dependency-drift",))
    assert (
        run_rules(
            _context(
                tmp_path,
                consumer,
                files=("pyproject.toml",),
                config=config,
                packages=(consumer, target),
            )
        )
        == ()
    )

    incompatible = _package(
        Ecosystem.PYTHON,
        name="consumer",
        dependencies=(InternalDependency("core-pkg", "~=2.0"),),
        entrypoints=(),
    )
    findings = run_rules(
        _context(
            tmp_path,
            incompatible,
            files=("pyproject.toml",),
            config=config,
            packages=(incompatible, target),
        )
    )
    assert [item.rule_id for item in findings] == ["common.internal-dependency-drift"]


def test_readme_license_and_expected_files_must_enter_artifact(tmp_path: Path) -> None:
    _write(tmp_path, "README.md", "read me")
    _write(tmp_path, "LICENSE", "license")
    _write(tmp_path, "pyproject.toml", "[project]\nname='demo'\nversion='1.2.3'\n")
    files = ("LICENSE", "README.md", "pyproject.toml")
    package = _package(
        Ecosystem.PYTHON,
        entrypoints=(),
        readme="README.md",
        expected_files=("README.md", "LICENSE"),
    )
    incomplete = ArtifactSnapshot(
        path="demo-1.2.3.tar.gz",
        format="sdist",
        sha256="d" * 64,
        size=10,
        entries=(ArtifactEntry("demo-1.2.3/pyproject.toml", 1),),
    )
    config = Config(
        enabled_rules=(
            "common.missing-expected-file",
            "common.missing-license",
            "common.missing-readme",
        )
    )
    findings = run_rules(
        _context(tmp_path, package, files=files, config=config, artifact=incomplete)
    )
    assert [item.rule_id for item in findings].count("common.missing-expected-file") == 2
    assert {item.rule_id for item in findings} == {
        "common.missing-expected-file",
        "common.missing-license",
        "common.missing-readme",
    }
    assert all(
        "artifact" in {evidence.key: evidence.value for evidence in item.evidence}["missing_from"]
        for item in findings
    )

    complete = ArtifactSnapshot(
        path="demo-1.2.3.tar.gz",
        format="sdist",
        sha256="e" * 64,
        size=10,
        entries=(
            ArtifactEntry("demo-1.2.3/LICENSE", 1),
            ArtifactEntry("demo-1.2.3/README.md", 1),
        ),
    )
    assert (
        run_rules(_context(tmp_path, package, files=files, config=config, artifact=complete)) == ()
    )


def test_python_wheel_accepts_embedded_readme_and_relocated_license(tmp_path: Path) -> None:
    _write(tmp_path, "README.md", "read me")
    _write(tmp_path, "LICENSE", "license")
    _write(tmp_path, "pyproject.toml", "[project]\nname='demo'\nversion='1.2.3'\n")
    files = ("LICENSE", "README.md", "pyproject.toml")
    package = _package(
        Ecosystem.PYTHON,
        entrypoints=(),
        readme="README.md",
        expected_files=("README.md", "LICENSE"),
    )
    wheel = ArtifactSnapshot(
        path="demo-1.2.3-py3-none-any.whl",
        format="wheel",
        sha256="a" * 64,
        size=10,
        entries=(
            ArtifactEntry("demo-1.2.3.dist-info/METADATA", 1),
            ArtifactEntry("demo-1.2.3.dist-info/licenses/LICENSE", 1),
        ),
    )
    config = Config(
        enabled_rules=(
            "common.missing-expected-file",
            "common.missing-license",
            "common.missing-readme",
        )
    )
    assert run_rules(_context(tmp_path, package, files=files, config=config, artifact=wheel)) == ()


def test_missing_expected_file_handles_files_directories_and_artifacts(tmp_path: Path) -> None:
    _write(tmp_path, "assets/icon.svg")
    package = _package(
        expected_files=("NOTICE", "assets"),
        entrypoints=(),
    )
    artifact = ArtifactSnapshot(
        path="demo.tgz",
        format="tgz",
        sha256="f" * 64,
        size=10,
        entries=(ArtifactEntry("package/assets/icon.svg", 1),),
    )
    config = Config(enabled_rules=("common.missing-expected-file",))
    findings = run_rules(
        _context(
            tmp_path,
            package,
            files=("assets/icon.svg",),
            config=config,
            artifact=artifact,
        )
    )
    assert len(findings) == 1
    assert {item.key: item.value for item in findings[0].evidence}["missing_from"] == (
        "repository,artifact"
    )

    _write(tmp_path, "NOTICE")
    findings = run_rules(
        _context(
            tmp_path,
            package,
            files=("NOTICE", "assets/icon.svg"),
            config=config,
            artifact=artifact,
        )
    )
    assert len(findings) == 1
    assert {item.key: item.value for item in findings[0].evidence}["missing_from"] == "artifact"


@pytest.mark.parametrize(
    ("ecosystem", "manifest_name", "artifact_name", "manifest_version", "artifact_version"),
    [
        (Ecosystem.PYTHON, "Demo_Pkg", "demo-pkg", "1.0.0", "1.0"),
        (Ecosystem.NPM, "@scope/Demo", "@scope/demo", "1.2.3", "1.2.3"),
        (Ecosystem.RUST, "demo_pkg", "demo-pkg", "1.2.3", "1.2.3"),
    ],
)
def test_artifact_metadata_comparison_uses_ecosystem_normalization(
    tmp_path: Path,
    ecosystem: Ecosystem,
    manifest_name: str,
    artifact_name: str,
    manifest_version: str,
    artifact_version: str,
) -> None:
    package = _package(
        ecosystem,
        name=manifest_name,
        version=manifest_version,
        entrypoints=(),
    )
    artifact = ArtifactSnapshot(
        path="artifact.pkg",
        format="zip",
        sha256="1" * 64,
        size=10,
        entries=(),
        metadata={"package_name": artifact_name, "package_version": artifact_version},
    )
    config = Config(enabled_rules=("common.artifact-metadata-mismatch",))
    assert run_rules(_context(tmp_path, package, files=(), config=config, artifact=artifact)) == ()

    mismatch = ArtifactSnapshot(
        path="artifact.pkg",
        format="zip",
        sha256="2" * 64,
        size=10,
        entries=(),
        metadata={"package_name": "other", "package_version": "9.9.9"},
    )
    findings = run_rules(_context(tmp_path, package, files=(), config=config, artifact=mismatch))
    assert [item.rule_id for item in findings] == ["common.artifact-metadata-mismatch"]
    assert findings[0].evidence and findings[0].remediation


def test_npm_main_types_and_bin_paths(tmp_path: Path) -> None:
    manifest = {
        "name": "demo",
        "version": "1.2.3",
        "main": "dist/index",
        "types": "dist/index.d.ts",
        "bin": {"demo": "bin/demo.js"},
    }
    _write(tmp_path, "package.json", json.dumps(manifest))
    _write(tmp_path, "dist/index.js")
    files = ("package.json", "dist/index.js")
    config = Config(enabled_rules=("npm.invalid-main", "npm.invalid-types", "npm.invalid-bin"))
    findings = run_rules(_context(tmp_path, _package(), files=files, config=config))
    assert {item.rule_id for item in findings} == {"npm.invalid-types", "npm.invalid-bin"}


def test_python_metadata_and_wheel_rules(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", "[project]\nname = 'demo-pkg'\n")
    package = _package(
        Ecosystem.PYTHON,
        name="demo-pkg",
        version="1.2.3",
        entrypoints=(),
    )
    bad_wheel = ArtifactSnapshot(
        path="wrong-1.2.3-py3-none-any.whl",
        format="wheel",
        sha256="b" * 64,
        size=10,
        entries=(ArtifactEntry("wrong-1.2.3.dist-info/METADATA", 1),),
    )
    config = Config(enabled_rules=("python.invalid-metadata", "python.invalid-wheel"))
    findings = run_rules(
        _context(
            tmp_path,
            package,
            files=("pyproject.toml",),
            config=config,
            artifact=bad_wheel,
        )
    )
    assert {item.rule_id for item in findings} == {
        "python.invalid-metadata",
        "python.invalid-wheel",
    }

    _write(
        tmp_path,
        "pyproject.toml",
        "[project]\nname = 'demo-pkg'\nversion = '1.2.3'\n",
    )
    dist_info = "demo_pkg-1.2.3.dist-info"
    good_wheel = ArtifactSnapshot(
        path="demo_pkg-1.2.3-py3-none-any.whl",
        format="wheel",
        sha256="c" * 64,
        size=10,
        entries=tuple(
            ArtifactEntry(f"{dist_info}/{name}", 1) for name in ("METADATA", "WHEEL", "RECORD")
        ),
    )
    assert (
        run_rules(
            _context(
                tmp_path,
                package,
                files=("pyproject.toml",),
                config=config,
                artifact=good_wheel,
            )
        )
        == ()
    )


def test_rust_include_license_and_readme(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "Cargo.toml",
        """[package]
name = "demo"
version = "1.2.3"
include = ["src/**", "missing/**"]
license-file = "NO-LICENSE"
readme = "NO-README.md"
""",
    )
    _write(tmp_path, "src/lib.rs")
    package = _package(Ecosystem.RUST, entrypoints=("src/lib.rs",))
    config = Config(
        enabled_rules=(
            "rust.invalid-include",
            "rust.invalid-license",
            "rust.invalid-readme",
        )
    )
    findings = run_rules(
        _context(tmp_path, package, files=("Cargo.toml", "src/lib.rs"), config=config)
    )
    assert {item.rule_id for item in findings} == {
        "rust.invalid-include",
        "rust.invalid-license",
        "rust.invalid-readme",
    }


def test_nested_package_owns_its_files(tmp_path: Path) -> None:
    root_package = _package(name="root", root=".")
    child = _package(
        name="child",
        root="packages/child",
        manifest="packages/child/package.json",
    )
    files = ("root.txt", "packages/child/.env", "packages/child/src/index.js")
    root_context = _context(
        tmp_path,
        root_package,
        files=files,
        packages=(root_package, child),
    )
    child_context = _context(
        tmp_path,
        child,
        files=files,
        packages=(root_package, child),
    )
    assert "packages/child/.env" not in root_context.package_files
    assert ".env" in child_context.package_files


@pytest.mark.parametrize("content", ("{broken", "[]"))
def test_npm_invalid_manifest_variants(tmp_path: Path, content: str) -> None:
    _write(tmp_path, "package.json", content)
    config = Config(enabled_rules=("npm.invalid-manifest",))
    findings = run_rules(_context(tmp_path, _package(), files=("package.json",), config=config))
    assert [item.rule_id for item in findings] == ["npm.invalid-manifest"]


def test_npm_field_shape_and_unsafe_path_edges(tmp_path: Path) -> None:
    manifest = {
        "name": "demo",
        "version": "1.2.3",
        "main": 42,
        "types": "../escape.d.ts",
        "typings": "",
        "exports": [{"import": {"types": "missing/export.d.ts"}}, "ignored"],
        "bin": {"": "bin/empty.js", "bad": 7, "escape": "../bin.js"},
    }
    _write(tmp_path, "package.json", json.dumps(manifest))
    config = Config(enabled_rules=("npm.invalid-main", "npm.invalid-types", "npm.invalid-bin"))
    findings = run_rules(_context(tmp_path, _package(), files=("package.json",), config=config))
    assert {item.rule_id for item in findings} == {
        "npm.invalid-main",
        "npm.invalid-types",
        "npm.invalid-bin",
    }
    assert len(findings) >= 7


@pytest.mark.parametrize("bin_value", ({}, ["bin.js"]))
def test_npm_bin_invalid_container_shapes(tmp_path: Path, bin_value: object) -> None:
    _write(
        tmp_path,
        "package.json",
        json.dumps({"name": "demo", "version": "1.2.3", "bin": bin_value}),
    )
    config = Config(enabled_rules=("npm.invalid-bin",))
    findings = run_rules(_context(tmp_path, _package(), files=("package.json",), config=config))
    assert [item.rule_id for item in findings] == ["npm.invalid-bin"]


def test_npm_string_bin_and_nested_export_types_are_valid(tmp_path: Path) -> None:
    manifest = {
        "name": "demo",
        "version": "1.2.3",
        "bin": "bin/demo.js",
        "exports": {".": [{"types": "dist/index.d.ts"}, {"default": "dist/index.js"}]},
    }
    _write(tmp_path, "package.json", json.dumps(manifest))
    _write(tmp_path, "bin/demo.js")
    _write(tmp_path, "dist/index.d.ts")
    config = Config(enabled_rules=("npm.invalid-bin", "npm.invalid-types"))
    files = ("bin/demo.js", "dist/index.d.ts", "package.json")
    assert run_rules(_context(tmp_path, _package(), files=files, config=config)) == ()


@pytest.mark.parametrize(
    ("manifest", "content", "should_find"),
    [
        ("pyproject.toml", "[tool.other]\nx = 1\n", True),
        ("pyproject.toml", "[tool.poetry]\nname = ''\nversion = ''\n", True),
        ("pyproject.toml", "[project]\nname='demo'\ndynamic=['version']\n", False),
        ("setup.cfg", "[options]\nzip_safe = false\n", True),
        ("setup.cfg", "[metadata]\nname =\nversion =\n", True),
        ("setup.cfg", "[metadata]\nname=demo\nversion=1.0\n", False),
        ("setup.py", "raise RuntimeError\n", False),
        ("other.toml", "x = 1\n", False),
    ],
)
def test_python_metadata_variants(
    tmp_path: Path, manifest: str, content: str, should_find: bool
) -> None:
    _write(tmp_path, manifest, content)
    package = _package(
        Ecosystem.PYTHON,
        manifest=manifest,
        entrypoints=(),
    )
    config = Config(enabled_rules=("python.invalid-metadata",))
    findings = run_rules(_context(tmp_path, package, files=(manifest,), config=config))
    assert bool(findings) is should_find


def test_python_metadata_parse_error(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", "[project\n")
    package = _package(Ecosystem.PYTHON, entrypoints=())
    config = Config(enabled_rules=("python.invalid-metadata",))
    findings = run_rules(_context(tmp_path, package, files=("pyproject.toml",), config=config))
    assert [item.rule_id for item in findings] == ["python.invalid-metadata"]


def test_python_console_script_resolves_src_layout(tmp_path: Path) -> None:
    _write(tmp_path, "src/packrehearsal/cli.py", "def main(): return 0\n")
    package = _package(
        Ecosystem.PYTHON,
        name="packrehearsal",
        entrypoints=("console:packrehearsal=packrehearsal.cli:main",),
    )
    config = Config(enabled_rules=("common.missing-entrypoint",))
    files = ("pyproject.toml", "src/packrehearsal/cli.py")
    assert run_rules(_context(tmp_path, package, files=files, config=config)) == ()


@pytest.mark.parametrize(
    ("artifact_path", "artifact_format", "entries"),
    [
        ("demo.zip", "wheel", ()),
        (
            "demo-1.2.3-py3-none-any.whl",
            "wheel",
            (
                ArtifactEntry("a-1.2.3.dist-info/METADATA", 1),
                ArtifactEntry("b-1.2.3.dist-info/METADATA", 1),
            ),
        ),
        ("demo.whl", "wheel", (ArtifactEntry("demo-1.2.3.dist-info/METADATA", 1),)),
        (
            "other-1.2.3-py3-none-any.whl",
            "wheel",
            tuple(
                ArtifactEntry(f"demo-1.2.3.dist-info/{name}", 1)
                for name in ("METADATA", "WHEEL", "RECORD")
            ),
        ),
        (
            "demo-9.9.9-py3-none-any.whl",
            "wheel",
            tuple(
                ArtifactEntry(f"demo-1.2.3.dist-info/{name}", 1)
                for name in ("METADATA", "WHEEL", "RECORD")
            ),
        ),
    ],
)
def test_python_wheel_failure_shapes(
    tmp_path: Path,
    artifact_path: str,
    artifact_format: str,
    entries: tuple[ArtifactEntry, ...],
) -> None:
    package = _package(Ecosystem.PYTHON, version="1.2.3", entrypoints=())
    artifact = ArtifactSnapshot(
        path=artifact_path,
        format=artifact_format,
        sha256="d" * 64,
        size=10,
        entries=entries,
    )
    config = Config(enabled_rules=("python.invalid-wheel",))
    findings = run_rules(_context(tmp_path, package, files=(), config=config, artifact=artifact))
    assert [item.rule_id for item in findings] == ["python.invalid-wheel"]


@pytest.mark.parametrize("content", ("[package\n", "[workspace]\nmembers=[]\n"))
def test_rust_invalid_manifest_variants(tmp_path: Path, content: str) -> None:
    _write(tmp_path, "Cargo.toml", content)
    package = _package(Ecosystem.RUST, entrypoints=())
    config = Config(enabled_rules=("rust.invalid-manifest",))
    findings = run_rules(_context(tmp_path, package, files=("Cargo.toml",), config=config))
    assert [item.rule_id for item in findings] == ["rust.invalid-manifest"]


@pytest.mark.parametrize(
    "include_line",
    (
        'include = "src/**"',
        'include = ["!target/**"]',
        'include = ["../escape"]',
    ),
)
def test_rust_include_invalid_shapes(tmp_path: Path, include_line: str) -> None:
    _write(
        tmp_path,
        "Cargo.toml",
        f'[package]\nname="demo"\nversion="1.2.3"\n{include_line}\n',
    )
    package = _package(Ecosystem.RUST, entrypoints=())
    config = Config(enabled_rules=("rust.invalid-include",))
    findings = run_rules(_context(tmp_path, package, files=("Cargo.toml",), config=config))
    assert [item.rule_id for item in findings] == ["rust.invalid-include"]


def test_rust_license_and_readme_edge_branches(tmp_path: Path) -> None:
    package = _package(Ecosystem.RUST, entrypoints=())
    config = Config(enabled_rules=("rust.invalid-license", "rust.invalid-readme"))

    cases = (
        (
            '[package]\nname="demo"\nversion="1.2.3"\nlicense.workspace=true\nreadme.workspace=true\n',
            {"rust.invalid-license", "rust.invalid-readme"},
        ),
        (
            '[package]\nname="demo"\nversion="1.2.3"\nreadme=42\n',
            {"rust.invalid-license", "rust.invalid-readme"},
        ),
        (
            '[package]\nname="demo"\nversion="1.2.3"\nlicense="MIT"\nreadme=false\n',
            set(),
        ),
        (
            '[package]\nname="demo"\nversion="1.2.3"\nlicense-file="../LICENSE"\nreadme="../README"\n',
            {"rust.invalid-license", "rust.invalid-readme"},
        ),
    )
    for content, expected in cases:
        _write(tmp_path, "Cargo.toml", content)
        findings = run_rules(_context(tmp_path, package, files=("Cargo.toml",), config=config))
        assert {item.rule_id for item in findings} == expected


def test_rust_workspace_inheritance_and_existing_files(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "Cargo.toml",
        '[workspace]\nmembers=["crate"]\n[workspace.package]\nlicense="MIT"\nreadme="README.md"\n',
    )
    _write(
        tmp_path,
        "crate/Cargo.toml",
        '[package]\nname="demo"\nversion="1.2.3"\nlicense.workspace=true\nreadme.workspace=true\n',
    )
    _write(tmp_path, "crate/README.md")
    package = Package(
        ecosystem=Ecosystem.RUST,
        name="demo",
        version="1.2.3",
        root="crate",
        manifest="crate/Cargo.toml",
        workspace_root=".",
        entrypoints=(),
    )
    config = Config(enabled_rules=("rust.invalid-license", "rust.invalid-readme"))
    files = ("Cargo.toml", "crate/Cargo.toml", "crate/README.md")
    assert run_rules(_context(tmp_path, package, files=files, config=config)) == ()
