from __future__ import annotations

import json
from pathlib import Path

import pytest

from packrehearsal.config import Config
from packrehearsal.discovery import DiscoveryResult, discover_packages, discover_repository
from packrehearsal.exceptions import DiscoveryError
from packrehearsal.models import Ecosystem


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    _write(path, json.dumps(payload))


def test_discovers_polyglot_workspaces_and_only_internal_dependencies(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "package.json",
        {"private": True, "workspaces": ["js/*"]},
    )
    _write_json(
        tmp_path / "js/app/package.json",
        {
            "name": "@demo/app",
            "version": "1.0.0",
            "dependencies": {"@demo/lib": "workspace:*", "react": "^19"},
        },
    )
    _write_json(
        tmp_path / "js/lib/package.json",
        {"name": "@demo/lib", "version": "1.0.0"},
    )

    _write(
        tmp_path / "python/api/pyproject.toml",
        """
[project]
name = "demo_api"
version = "0.2.0"
dependencies = ["demo-core>=0.2", "requests>=2"]
""",
    )
    _write(
        tmp_path / "python/core/pyproject.toml",
        """
[project]
name = "demo.core"
version = "0.2.0"
""",
    )

    _write(
        tmp_path / "rust/Cargo.toml",
        """
[workspace]
members = ["crates/*"]

[workspace.package]
version = "0.3.0"
license = "Apache-2.0"

[workspace.dependencies]
demo-core = { path = "crates/core", version = "0.3" }
""",
    )
    _write(
        tmp_path / "rust/crates/core/Cargo.toml",
        """
[package]
name = "demo-core"
version.workspace = true
license.workspace = true
""",
    )
    _write(
        tmp_path / "rust/crates/cli/Cargo.toml",
        """
[package]
name = "demo-cli"
version.workspace = true

[dependencies]
demo-core.workspace = true
serde = "1"
""",
    )

    result = discover_packages(tmp_path)

    assert isinstance(result, DiscoveryResult)
    assert not result.findings
    assert [(item.ecosystem, item.name) for item in result.packages] == [
        (Ecosystem.NPM, "@demo/app"),
        (Ecosystem.NPM, "@demo/lib"),
        (Ecosystem.PYTHON, "demo_api"),
        (Ecosystem.PYTHON, "demo.core"),
        (Ecosystem.RUST, "demo-cli"),
        (Ecosystem.RUST, "demo-core"),
    ]
    packages = {item.name: item for item in result.packages}
    assert packages["@demo/app"].workspace_root == "."
    assert [item.name for item in packages["@demo/app"].internal_dependencies] == ["@demo/lib"]
    assert [item.name for item in packages["demo_api"].internal_dependencies] == ["demo-core"]
    assert packages["demo-cli"].workspace_root == "rust"
    assert packages["demo-cli"].version == "0.3.0"
    assert [item.name for item in packages["demo-cli"].internal_dependencies] == ["demo-core"]
    for package in result.packages:
        assert not Path(package.root).is_absolute()
        assert not Path(package.manifest).is_absolute()


def test_bad_manifests_are_findings_and_do_not_hide_good_packages(tmp_path: Path) -> None:
    _write_json(tmp_path / "good/package.json", {"name": "good", "version": "1.0.0"})
    _write(tmp_path / "bad/package.json", "{ definitely not json")
    _write(tmp_path / "also-bad/pyproject.toml", "[project\nname = 'broken'")

    result = discover_packages(tmp_path)

    assert [item.name for item in result.packages] == ["good"]
    assert len(result.findings) == 2
    assert {item.rule_id for item in result.findings} == {"discovery-manifest-invalid"}
    assert {item.location for item in result.findings} == {
        "also-bad/pyproject.toml",
        "bad/package.json",
    }
    assert all(str(tmp_path) not in item.message for item in result.findings)


def test_default_exclusions_hidden_directories_and_max_depth_are_honored(tmp_path: Path) -> None:
    _write_json(tmp_path / "package.json", {"name": "root", "version": "1"})
    _write_json(tmp_path / "node_modules/dep/package.json", {"name": "dep", "version": "1"})
    _write_json(tmp_path / ".hidden/package.json", {"name": "hidden", "version": "1"})
    _write_json(tmp_path / "one/two/package.json", {"name": "deep", "version": "1"})

    result = discover_packages(tmp_path, Config(max_depth=1))
    hidden_result = discover_packages(tmp_path, Config(max_depth=2, include_hidden=True))

    assert [item.name for item in result.packages] == ["root"]
    assert [item.name for item in hidden_result.packages] == ["root", "hidden", "deep"]


def test_custom_exclusion_matches_files_and_directories(tmp_path: Path) -> None:
    _write_json(tmp_path / "keep/package.json", {"name": "keep", "version": "1"})
    _write_json(tmp_path / "examples/a/package.json", {"name": "example", "version": "1"})
    _write(tmp_path / "skip/pyproject.toml", "[project]\nname='skip'\nversion='1'")

    config = Config(exclude=("examples/**", "skip/pyproject.toml"))
    result = discover_packages(tmp_path, config)

    assert [item.name for item in result.packages] == ["keep"]


def test_result_order_and_fingerprints_are_stable(tmp_path: Path) -> None:
    _write_json(tmp_path / "z/package.json", {"name": "z", "version": "1"})
    _write_json(tmp_path / "a/package.json", {"name": "a", "version": "1"})
    _write(tmp_path / "broken/Cargo.toml", "[package\n")

    first = discover_packages(tmp_path)
    second = discover_repository(tmp_path)

    assert first == second
    assert [item.name for item in first.packages] == ["a", "z"]
    assert first.findings[0].fingerprint == second.findings[0].fingerprint


def test_python_distribution_names_are_canonicalized_for_internal_links(tmp_path: Path) -> None:
    _write(
        tmp_path / "api/pyproject.toml",
        "[project]\nname='my_api'\nversion='1'\ndependencies=['my.core>=1']",
    )
    _write(tmp_path / "core/pyproject.toml", "[project]\nname='my-core'\nversion='1'")

    result = discover_packages(tmp_path)

    api = next(item for item in result.packages if item.name == "my_api")
    assert [item.name for item in api.internal_dependencies] == ["my-core"]


def test_duplicate_publish_names_are_reported(tmp_path: Path) -> None:
    _write(tmp_path / "a/pyproject.toml", "[project]\nname='same_name'\nversion='1'")
    _write(tmp_path / "b/pyproject.toml", "[project]\nname='same-name'\nversion='2'")

    result = discover_packages(tmp_path)

    duplicates = [
        item for item in result.findings if item.rule_id == "discovery-duplicate-package-name"
    ]
    assert len(duplicates) == 2
    assert {item.location for item in duplicates} == {"a/pyproject.toml", "b/pyproject.toml"}


def test_invalid_discovery_roots_raise_actionable_error(tmp_path: Path) -> None:
    file_root = tmp_path / "file"
    _write(file_root, "not a directory")

    with pytest.raises(DiscoveryError, match="not a directory"):
        discover_packages(file_root)
    with pytest.raises(DiscoveryError, match="does not exist"):
        discover_packages(tmp_path / "missing")


def test_symlink_manifest_is_not_followed(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-package.json"
    _write_json(outside, {"name": "outside", "version": "1"})
    link = tmp_path / "package.json"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    result = discover_packages(tmp_path)

    assert not result.packages
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "discovery-manifest-invalid"
    assert "symbolic-link" in result.findings[0].message
