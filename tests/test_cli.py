from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import packrehearsal.cli as cli_module
from packrehearsal.artifacts import BuildPlan, BuildResult
from packrehearsal.cli import EXIT_FINDINGS, EXIT_OK, EXIT_REHEARSAL, EXIT_USAGE, main
from packrehearsal.models import Ecosystem


def _valid_python_project(root: Path) -> None:
    (root / "src" / "demo").mkdir(parents=True)
    (root / "src" / "demo" / "__init__.py").write_text("", encoding="utf-8")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    (root / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        """
[project]
name = "demo"
version = "1.0.0"
readme = "README.md"
license = { file = "LICENSE" }
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_scan_writes_json_and_baseline(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    _valid_python_project(tmp_path)
    report_path = tmp_path / "report.json"
    baseline_path = tmp_path / "baseline.json"
    exit_code = main(
        [
            "scan",
            str(tmp_path),
            "--format",
            "json",
            "--output",
            str(report_path),
            "--write-baseline",
            str(baseline_path),
            "--no-fail",
        ]
    )
    assert exit_code == EXIT_OK
    assert json.loads(report_path.read_text(encoding="utf-8"))["packages"][0]["name"] == "demo"
    assert json.loads(baseline_path.read_text(encoding="utf-8"))["schema_version"] == "1"
    assert capsys.readouterr().err == ""


def test_scan_returns_finding_exit_code(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "package.json").write_text(
        '{"name":"broken","version":"0.0.0","main":"missing.js"}', encoding="utf-8"
    )
    assert main(["scan", str(tmp_path), "--color", "never"]) == EXIT_FINDINGS
    output = capsys.readouterr().out
    assert "common.missing-license" in output
    assert "common.placeholder-version" in output


def test_init_refuses_to_replace_existing_config(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["init", "--root", str(tmp_path)]) == EXIT_OK
    assert main(["init", "--root", str(tmp_path)]) == EXIT_USAGE
    assert "configuration already exists" in capsys.readouterr().err


def test_rehearse_requires_explicit_trust(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    _valid_python_project(tmp_path)
    assert main(["rehearse", str(tmp_path)]) == EXIT_REHEARSAL
    assert "can execute project code" in capsys.readouterr().err


def test_rules_and_doctor_are_available(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["rules", "--format", "json"]) == EXIT_OK
    rules = json.loads(capsys.readouterr().out)
    assert any(rule["rule_id"] == "common.sensitive-file" for rule in rules)
    assert main(["doctor"]) == EXIT_OK
    assert "Static scan: ready" in capsys.readouterr().out


def test_inspect_and_receipt_verification_commands(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    artifact = tmp_path / "demo.whl"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("demo-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\n")
    assert main(["inspect", str(artifact), "--format", "json"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["artifacts"][0]["format"] == "wheel"

    _valid_python_project(tmp_path)
    receipt = tmp_path / "receipt.json"
    assert (
        main(
            [
                "scan",
                str(tmp_path),
                "--artifact",
                str(artifact),
                "--receipt",
                str(receipt),
                "--no-fail",
            ]
        )
        == EXIT_OK
    )
    capsys.readouterr()
    assert main(["verify-receipt", str(receipt)]) == EXIT_OK
    assert "Self-consistency checks passed: receipt content hash" in capsys.readouterr().out


def test_scan_can_emit_markdown_to_stdout(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    _valid_python_project(tmp_path)
    assert main(["scan", str(tmp_path), "--format", "markdown", "--no-fail"]) == EXIT_OK
    assert "# PackRehearsal report" in capsys.readouterr().out


def test_trusted_rehearsal_orchestration_without_running_project_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    _valid_python_project(tmp_path)
    plan = BuildPlan(
        package="python:demo@1.0.0",
        ecosystem=Ecosystem.PYTHON,
        source_root=tmp_path,
        argv=("python", "-m", "build", "--outdir", "{output_dir}"),
        artifact_globs=("*.whl",),
        executes_project_code=True,
    )
    monkeypatch.setattr(cli_module, "plan_trusted_build", lambda *args, **kwargs: plan)
    monkeypatch.setattr(
        cli_module,
        "run_build_plan",
        lambda *args, **kwargs: BuildResult(
            package=plan.package,
            command=plan.argv,
            returncode=0,
            stdout="",
            stderr="",
            artifacts=(),
        ),
    )
    assert main(
        [
            "rehearse",
            str(tmp_path),
            "--trusted-rehearsal",
            "--format",
            "json",
        ]
    ) in {EXIT_OK, EXIT_FINDINGS}
    captured = capsys.readouterr()
    assert json.loads(captured.out)["packages"][0]["name"] == "demo"
    assert "Trusted build plan for python:demo@1.0.0" in captured.err


def test_rehearse_validates_rule_ids_before_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    _valid_python_project(tmp_path)
    (tmp_path / ".packrehearsal.json").write_text(
        '{"enabled_rules":["typo.rule"]}', encoding="utf-8"
    )
    called = False

    def unexpected_build(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        raise AssertionError("build planning must not run for invalid configuration")

    monkeypatch.setattr(cli_module, "plan_trusted_build", unexpected_build)
    assert main(["rehearse", str(tmp_path), "--trusted-rehearsal"]) == EXIT_USAGE
    assert not called
    assert "unknown rule IDs" in capsys.readouterr().err


def test_no_repo_config_uses_built_in_policy(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    _valid_python_project(tmp_path)
    (tmp_path / ".packrehearsal.json").write_text(
        '{"enabled_rules":["not.a.real.rule"]}', encoding="utf-8"
    )
    assert main(["scan", str(tmp_path), "--no-repo-config", "--no-fail"]) == EXIT_OK
    capsys.readouterr()
    assert (
        main(
            [
                "scan",
                str(tmp_path),
                "--no-repo-config",
                "--config",
                str(tmp_path / ".packrehearsal.json"),
            ]
        )
        == EXIT_USAGE
    )
    assert "cannot be used together" in capsys.readouterr().err


def test_inspect_refuses_artifact_symlink(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    artifact = tmp_path / "demo.whl"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("demo-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\n")
    link = tmp_path / "candidate.whl"
    link.symlink_to(artifact)
    assert main(["inspect", str(link)]) == EXIT_USAGE
    assert "symlink" in capsys.readouterr().err
