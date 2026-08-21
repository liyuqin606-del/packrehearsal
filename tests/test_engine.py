from __future__ import annotations

import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from packrehearsal.config import Config
from packrehearsal.engine import associate_artifacts, collect_repository_files, scan_repository
from packrehearsal.exceptions import ConfigurationError
from packrehearsal.models import (
    ArtifactSnapshot,
    Ecosystem,
    Package,
    Severity,
)
from packrehearsal.rules import RuleRegistry


def _write_npm_package(root: Path) -> None:
    (root / "dist").mkdir()
    (root / "dist" / "index.js").write_text("export const ok = true;\n", encoding="utf-8")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "demo-package",
                "version": "1.2.3",
                "license": "MIT",
                "main": "dist/index.js",
                "files": ["dist", "README.md", "LICENSE"],
            }
        ),
        encoding="utf-8",
    )


def _npm_artifact(root: Path) -> Path:
    artifact = root / "demo-package-1.2.3.tgz"
    with tarfile.open(artifact, "w:gz") as archive:
        for relative in ("package/dist/index.js", "package/README.md", "package/LICENSE"):
            source = root / relative.removeprefix("package/")
            archive.add(source, arcname=relative)
    return artifact


def test_static_engine_scans_repository_and_artifact(tmp_path: Path) -> None:
    _write_npm_package(tmp_path)
    artifact = _npm_artifact(tmp_path)
    report = scan_repository(tmp_path, artifact_paths=(artifact,))

    assert [package.identity for package in report.packages] == ["npm:demo-package@1.2.3"]
    assert report.artifacts[0].format == "tgz"
    assert not any(finding.rule_id == "engine-artifact-unmatched" for finding in report.findings)
    assert report.scan_id == scan_repository(tmp_path, artifact_paths=(artifact,)).scan_id


def test_engine_baseline_controls_failure_gate(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"broken","version":"0.0.0","main":"missing.js"}', encoding="utf-8"
    )
    report = scan_repository(tmp_path)
    assert report.should_fail(Severity.HIGH)

    baselined = scan_repository(
        tmp_path,
        baseline_fingerprints=(finding.fingerprint for finding in report.findings),
    )
    assert not baselined.should_fail(Severity.HIGH)


def test_artifact_association_refuses_ambiguity() -> None:
    first = Package(Ecosystem.NPM, "demo-one", "1.0.0", "one", "one/package.json")
    second = Package(Ecosystem.NPM, "demo-two", "1.0.0", "two", "two/package.json")
    artifact = ArtifactSnapshot("release.tgz", "tgz", "0" * 64, 10, ())
    associations = associate_artifacts((first, second), (artifact,))
    assert associations[0].package is None
    assert associations[0].reason == "ambiguous compatible packages"


def test_artifact_association_uses_parsed_metadata_for_generic_filename() -> None:
    first = Package(Ecosystem.PYTHON, "demo-one", "1.0.0", "one", "one/pyproject.toml")
    second = Package(Ecosystem.PYTHON, "demo_two", "2.0.0", "two", "two/pyproject.toml")
    artifact = ArtifactSnapshot(
        "release.whl",
        "wheel",
        "0" * 64,
        10,
        (),
        metadata={"package_name": "demo-two", "package_version": "2.0.0"},
    )
    associations = associate_artifacts((first, second), (artifact,))
    assert associations[0].package == second


def test_engine_compares_the_complete_python_artifact_set(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    wheel = ArtifactSnapshot(
        "demo-1.0-py3-none-any.whl",
        "wheel",
        "a" * 64,
        10,
        (),
        metadata={
            "package_name": "demo",
            "package_version": "1.0",
            "requires_python": ">=3.11",
        },
    )
    sdist = ArtifactSnapshot(
        "demo-1.0.tar.gz",
        "sdist",
        "b" * 64,
        10,
        (),
        metadata={
            "package_name": "demo",
            "package_version": "1.0.0",
            "requires_python": ">=3.12",
        },
    )
    report = scan_repository(
        tmp_path,
        artifacts=(wheel, sdist),
        config=Config(enabled_rules=("python.artifact-set-mismatch",)),
    )
    assert [finding.rule_id for finding in report.findings] == ["python.artifact-set-mismatch"]
    assert report.findings[0].location == ("demo-1.0-py3-none-any.whl <> demo-1.0.tar.gz")


def test_file_collection_ignores_symlinks_and_excluded_trees(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("x", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=x", encoding="utf-8")
    (tmp_path / "link").symlink_to(tmp_path / "src" / "main.py")

    files = collect_repository_files(tmp_path, Config())
    assert files == (".env", "src/main.py")


def test_scan_without_packages_is_actionable(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("nothing publishable", encoding="utf-8")
    report = scan_repository(tmp_path)
    assert report.packages == ()
    assert report.findings[0].rule_id == "engine-no-supported-packages"


def test_unmatched_external_artifact_uses_private_path_free_name(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _write_npm_package(repository)
    artifact = tmp_path / "unrelated.whl"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("other-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\n")
    report = scan_repository(repository, artifact_paths=(artifact,))
    assert report.artifacts[0].path == "unrelated.whl"
    unmatched = next(
        finding for finding in report.findings if finding.rule_id == "engine-artifact-unmatched"
    )
    assert unmatched.location == "unrelated.whl"
    assert str(tmp_path) not in json.dumps(report.to_dict())


def test_invalid_repository_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="repository root"):
        scan_repository(tmp_path / "missing")


def test_engine_rejects_unknown_configured_rule_ids(tmp_path: Path) -> None:
    _write_npm_package(tmp_path)
    with pytest.raises(ConfigurationError, match=r"unknown rule IDs.*typo\.rule"):
        scan_repository(tmp_path, config=Config(enabled_rules=("typo.rule",)))


def test_engine_respects_explicit_empty_registry(tmp_path: Path) -> None:
    _write_npm_package(tmp_path)
    report = scan_repository(tmp_path, registry=RuleRegistry())
    assert report.findings == ()


def test_engine_refuses_artifact_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _write_npm_package(repository)
    artifact = _npm_artifact(repository)
    link = repository / "candidate.tgz"
    link.symlink_to(artifact)
    with pytest.raises(Exception, match="symlink"):
        scan_repository(repository, artifact_paths=(link,))
