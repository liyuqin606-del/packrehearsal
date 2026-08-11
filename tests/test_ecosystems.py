from __future__ import annotations

import json
from pathlib import Path

import pytest

from packrehearsal.ecosystems import (
    discover_npm_packages,
    discover_rust_packages,
    parse_npm_manifest,
    parse_python_manifest,
    parse_rust_manifest,
)
from packrehearsal.exceptions import DiscoveryError


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    _write(path, json.dumps(payload))


def test_npm_parser_normalizes_paths_entrypoints_and_metadata(tmp_path: Path) -> None:
    manifest = tmp_path / "packages/widget/package.json"
    _write_json(
        manifest,
        {
            "name": "@scope/widget",
            "version": "2.4.0",
            "license": "MIT",
            "private": False,
            "packageManager": "pnpm@10",
            "files": ["dist", "../escaping"],
            "main": "./dist/index.cjs",
            "module": "./dist/index.js",
            "types": "./dist/index.d.ts",
            "bin": {"widget": "bin/widget.js"},
            "exports": {".": {"import": "./dist/index.js"}},
            "dependencies": {"inside": "workspace:^", "outside": "^1"},
            "optionalDependencies": {"optional": "1"},
        },
    )
    _write(manifest.parent / "README.md", "widget")

    package = parse_npm_manifest(manifest, tmp_path)

    assert package is not None
    assert package.root == "packages/widget"
    assert package.manifest == "packages/widget/package.json"
    assert package.readme == "packages/widget/README.md"
    assert package.license_expression == "MIT"
    assert package.entrypoints == (
        "packages/widget/bin/widget.js",
        "packages/widget/dist/index.cjs",
        "packages/widget/dist/index.d.ts",
        "packages/widget/dist/index.js",
    )
    assert package.expected_files == ("packages/widget/dist",)
    assert package.metadata["package_manager"] == "pnpm@10"
    assert {(item.name, item.kind) for item in package.internal_dependencies} == {
        ("inside", "runtime"),
        ("outside", "runtime"),
        ("optional", "optional"),
    }


def test_npm_workspace_object_and_negation_are_supported(tmp_path: Path) -> None:
    root_manifest = tmp_path / "package.json"
    kept_manifest = tmp_path / "packages/kept/package.json"
    excluded_manifest = tmp_path / "packages/excluded/package.json"
    _write_json(
        root_manifest,
        {"private": True, "workspaces": {"packages": ["packages/*", "!packages/excluded"]}},
    )
    _write_json(kept_manifest, {"name": "kept", "version": "1"})
    _write_json(excluded_manifest, {"name": "excluded", "version": "1"})

    result = discover_npm_packages(tmp_path, [excluded_manifest, root_manifest, kept_manifest])
    packages = {item.name: item for item in result.packages}

    assert packages["kept"].workspace_root == "."
    assert packages["excluded"].workspace_root is None
    assert not result.findings


def test_private_virtual_npm_workspace_is_not_a_publishable_package(tmp_path: Path) -> None:
    manifest = tmp_path / "package.json"
    _write_json(manifest, {"private": True, "workspaces": ["packages/*"]})

    assert parse_npm_manifest(manifest, tmp_path) is None


def test_python_pep621_dynamic_version_scripts_and_optional_dependencies(tmp_path: Path) -> None:
    manifest = tmp_path / "services/api/pyproject.toml"
    _write(
        manifest,
        """
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "demo-api"
dynamic = ["version"]
readme = { file = "docs/README.md" }
license-expression = "Apache-2.0"
dependencies = ["demo-core>=1; python_version >= '3.11'", "httpx>=0.28"]

[project.optional-dependencies]
test = ["demo-test~=1"]

[project.scripts]
demo = "demo_api.cli:main"

[dependency-groups]
dev = ["demo-core @ file://../core"]
""",
    )
    _write(manifest.parent / "docs/README.md", "API")

    package = parse_python_manifest(manifest, tmp_path)

    assert package is not None
    assert package.version == "<dynamic>"
    assert package.metadata["dynamic_version"] is True
    assert package.metadata["build_system"]["build-backend"] == "hatchling.build"
    assert package.readme == "services/api/docs/README.md"
    assert package.entrypoints == ("console:demo=demo_api.cli:main",)
    assert {(item.name, item.kind) for item in package.internal_dependencies} == {
        ("demo-core", "runtime"),
        ("httpx", "runtime"),
        ("demo-test", "optional:test"),
        ("demo-core", "group:dev"),
    }


def test_python_poetry_fallback_is_static_and_preserves_path_dependency(tmp_path: Path) -> None:
    manifest = tmp_path / "pyproject.toml"
    _write(
        manifest,
        """
[tool.poetry]
name = "poetry-demo"
version = "1.2.3"
license = "BSD-3-Clause"

[tool.poetry.dependencies]
python = ">=3.11"
local-lib = { path = "../local-lib" }
requests = "^2"

[tool.poetry.group.test.dependencies]
pytest = "^8"
""",
    )

    package = parse_python_manifest(manifest, tmp_path)

    assert package is not None
    assert package.metadata["metadata_source"] == "poetry"
    assert package.license_expression == "BSD-3-Clause"
    assert {(item.name, item.requirement, item.kind) for item in package.internal_dependencies} == {
        ("local-lib", "path:../local-lib", "runtime"),
        ("requests", "^2", "runtime"),
        ("pytest", "^8", "group:test"),
    }


def test_tool_only_pyproject_is_not_misidentified_as_a_package(tmp_path: Path) -> None:
    manifest = tmp_path / "pyproject.toml"
    _write(manifest, "[tool.ruff]\nline-length = 100")

    assert parse_python_manifest(manifest, tmp_path) is None


def test_rust_workspace_inheritance_aliases_and_targets(tmp_path: Path) -> None:
    workspace = tmp_path / "Cargo.toml"
    member = tmp_path / "crates/cli/Cargo.toml"
    core = tmp_path / "crates/core/Cargo.toml"
    _write(
        workspace,
        """
[workspace]
members = ["crates/*"]

[workspace.package]
version = "4.1.0"
license = "MIT OR Apache-2.0"
edition = "2024"

[workspace.dependencies]
core-alias = { package = "demo-core", path = "crates/core", version = "4" }
""",
    )
    _write(
        member,
        """
[package]
name = "demo-cli"
version.workspace = true
license.workspace = true
edition.workspace = true

[dependencies]
core-alias.workspace = true
serde = "1"

[target.'cfg(unix)'.build-dependencies]
demo-core = { path = "../core" }

[[bin]]
name = "demo"
path = "src/demo.rs"
""",
    )
    _write(core, "[package]\nname='demo-core'\nversion.workspace=true")
    _write(member.parent / "src/demo.rs", "fn main() {}")

    result = discover_rust_packages(tmp_path, [member, workspace, core])
    packages = {item.name: item for item in result.packages}
    package = packages["demo-cli"]

    assert package.version == "4.1.0"
    assert package.workspace_root == "."
    assert package.license_expression == "MIT OR Apache-2.0"
    assert package.metadata["edition"] == "2024"
    assert package.entrypoints == ("crates/cli/src/demo.rs",)
    assert {(item.name, item.requirement, item.kind) for item in package.internal_dependencies} == {
        ("demo-core", "4", "runtime"),
        ("serde", "1", "runtime"),
        ("demo-core", "path:../core", "target:cfg(unix):build"),
    }


def test_virtual_cargo_workspace_is_not_a_package(tmp_path: Path) -> None:
    manifest = tmp_path / "Cargo.toml"
    _write(manifest, "[workspace]\nmembers=[]")

    assert parse_rust_manifest(manifest, tmp_path) is None


@pytest.mark.parametrize(
    ("filename", "content", "parser"),
    [
        ("package.json", "[]", parse_npm_manifest),
        ("pyproject.toml", "[project\n", parse_python_manifest),
        ("Cargo.toml", "[package\n", parse_rust_manifest),
    ],
)
def test_direct_parsers_raise_discovery_error_for_bad_manifest(
    tmp_path: Path,
    filename: str,
    content: str,
    parser: object,
) -> None:
    manifest = tmp_path / filename
    _write(manifest, content)

    with pytest.raises(DiscoveryError):
        parser(manifest, tmp_path)  # type: ignore[operator]
