from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import packrehearsal.artifacts.builder as builder_module
from packrehearsal.artifacts import (
    BuildPlan,
    plan_package_build,
    plan_trusted_build,
    run_build_plan,
    run_trusted_build,
)
from packrehearsal.config import Config
from packrehearsal.exceptions import RehearsalError
from packrehearsal.models import Ecosystem, Package


def _package(root: Path, ecosystem: Ecosystem) -> Package:
    manifests = {
        Ecosystem.NPM: "package.json",
        Ecosystem.PYTHON: "pyproject.toml",
        Ecosystem.RUST: "Cargo.toml",
    }
    return Package(
        ecosystem=ecosystem,
        name="demo",
        version="1.0.0",
        root=root.name,
        manifest=f"{root.name}/{manifests[ecosystem]}",
    )


def _direct_plan(source: Path, *, timeout_seconds: int = 10) -> BuildPlan:
    return BuildPlan(
        package="npm:demo@1.0.0",
        ecosystem=Ecosystem.NPM,
        source_root=source,
        argv=(sys.executable, "-c", "raise SystemExit(0)"),
        artifact_globs=("*.zip",),
        timeout_seconds=timeout_seconds,
    )


def test_npm_safe_plan_disables_scripts_and_network(tmp_path: Path) -> None:
    source = tmp_path / "npm-package"
    source.mkdir()
    (source / "package.json").write_text('{"name":"demo","version":"1.0.0"}')

    package = _package(source, Ecosystem.NPM)
    plan = plan_package_build(package, repository_root=tmp_path)
    trusted = plan_trusted_build(package, repository_root=tmp_path)

    assert plan.source_root == source
    assert "--ignore-scripts" in plan.argv
    assert "--ignore-scripts" in trusted.argv
    assert plan.executes_project_code is False
    assert trusted.executes_project_code is False
    assert plan.allow_network is False
    assert plan.artifact_globs == ("*.tgz",)


def test_rust_safe_and_trusted_plans_have_distinct_verification_modes(tmp_path: Path) -> None:
    source = tmp_path / "rust-package"
    source.mkdir()
    (source / "Cargo.toml").write_text('[package]\nname="demo"\nversion="1.0.0"\n')
    package = _package(source, Ecosystem.RUST)

    safe = plan_package_build(package, repository_root=tmp_path)
    trusted = plan_trusted_build(package, repository_root=tmp_path)

    assert "--no-verify" in safe.argv
    assert "--offline" in safe.argv
    assert safe.executes_project_code is False
    assert "--no-verify" not in trusted.argv
    assert trusted.executes_project_code is True


def test_python_requires_an_explicit_trusted_plan(tmp_path: Path) -> None:
    source = tmp_path / "python-package"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\nname='demo'\nversion='1.0.0'\n")
    package = _package(source, Ecosystem.PYTHON)

    with pytest.raises(RehearsalError, match="PEP 517"):
        plan_package_build(package, repository_root=tmp_path)

    trusted = plan_trusted_build(package, repository_root=tmp_path)
    assert trusted.executes_project_code is True
    assert "--no-isolation" in trusted.argv


def test_trusted_and_network_plans_require_execution_confirmation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    trusted = BuildPlan(
        package="python:demo@1.0.0",
        ecosystem=Ecosystem.PYTHON,
        source_root=source,
        argv=(sys.executable, "-c", "raise SystemExit(0)"),
        artifact_globs=("*.zip",),
        executes_project_code=True,
    )
    network = BuildPlan(
        package="npm:demo@1.0.0",
        ecosystem=Ecosystem.NPM,
        source_root=source,
        argv=(sys.executable, "-c", "raise SystemExit(0)"),
        artifact_globs=("*.zip",),
        allow_network=True,
    )
    apparently_safe = BuildPlan(
        package="npm:demo@1.0.0",
        ecosystem=Ecosystem.NPM,
        source_root=source,
        argv=(sys.executable, "-c", "raise SystemExit(0)"),
        artifact_globs=("*.zip",),
    )

    with pytest.raises(RehearsalError, match="explicit trusted confirmation"):
        run_build_plan(trusted)
    with pytest.raises(RehearsalError, match="explicit trusted confirmation"):
        run_build_plan(network)
    with pytest.raises(RehearsalError, match="explicit trusted confirmation"):
        run_build_plan(apparently_safe)


def test_trusted_build_uses_clean_environment_and_removes_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("source remains untouched")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-leak")
    script = """
import os
import pathlib
import sys
import zipfile

output = pathlib.Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(output / "demo.zip", "w") as archive:
    archive.writestr("package/data.txt", "built")
print(os.environ["HOME"])
print("offline=" + os.environ.get("PIP_NO_INDEX", ""))
print("secret=" + str("GITHUB_TOKEN" in os.environ))
"""
    plan = BuildPlan(
        package="python:demo@1.0.0",
        ecosystem=Ecosystem.PYTHON,
        source_root=source,
        argv=(sys.executable, "-c", script, "{output_dir}"),
        artifact_globs=("*.zip",),
        timeout_seconds=10,
        executes_project_code=True,
    )

    result = run_trusted_build(plan)

    lines = result.stdout.strip().splitlines()
    temporary_home = Path(lines[0])
    assert not temporary_home.exists()
    assert "offline=1" in lines
    assert "secret=False" in lines
    assert result.command == plan.argv
    assert result.returncode == 0
    assert len(result.artifacts) == 1
    assert result.artifacts[0].format == "zip"
    assert result.artifacts[0].path == "demo.zip"
    assert (source / "input.txt").read_text() == "source remains untouched"


def test_safe_plan_sets_ignore_scripts_without_inheriting_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setenv("NPM_TOKEN", "must-not-leak")
    script = """
import os
import pathlib
import sys
import zipfile

output = pathlib.Path(sys.argv[1])
with zipfile.ZipFile(output / "safe.zip", "w") as archive:
    archive.writestr("ok", "yes")
print("scripts=" + os.environ.get("NPM_CONFIG_IGNORE_SCRIPTS", ""))
print("offline=" + os.environ.get("NPM_CONFIG_OFFLINE", ""))
print("secret=" + str("NPM_TOKEN" in os.environ))
"""
    plan = BuildPlan(
        package="npm:demo@1.0.0",
        ecosystem=Ecosystem.NPM,
        source_root=source,
        argv=(sys.executable, "-c", script, "{output_dir}"),
        artifact_globs=("*.zip",),
        timeout_seconds=10,
    )

    result = run_build_plan(plan, confirm_trusted=True)

    assert "scripts=true" in result.stdout
    assert "offline=true" in result.stdout
    assert "secret=False" in result.stdout


def test_build_timeout_terminates_and_cleans_up(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    script = "import time; print('started', flush=True); time.sleep(30)"
    plan = BuildPlan(
        package="python:demo@1.0.0",
        ecosystem=Ecosystem.PYTHON,
        source_root=source,
        argv=(sys.executable, "-c", script),
        artifact_globs=("*.zip",),
        timeout_seconds=1,
        executes_project_code=True,
    )

    started = time.monotonic()
    with pytest.raises(RehearsalError, match="timed out after 1 seconds"):
        run_trusted_build(plan)

    assert time.monotonic() - started < 8


def test_copy_time_is_charged_to_the_build_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("copy me", encoding="utf-8")
    clock = {"now": 0.0}
    real_copytree = builder_module.shutil.copytree

    def consuming_copytree(*args: object, **kwargs: object) -> Path:
        result = real_copytree(*args, **kwargs)  # type: ignore[arg-type]
        clock["now"] = 2.0
        return Path(result)

    monkeypatch.setattr(builder_module, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(builder_module.shutil, "copytree", consuming_copytree)
    with pytest.raises(RehearsalError, match="timed out after 1 seconds"):
        run_build_plan(_direct_plan(source, timeout_seconds=1), confirm_trusted=True)


@pytest.mark.parametrize("stream_fd", (1, 2))
def test_build_output_flood_is_capped_and_terminated(tmp_path: Path, stream_fd: int) -> None:
    source = tmp_path / "source"
    source.mkdir()
    script = f"""
import os

remaining = {builder_module._OUTPUT_LIMIT_BYTES + 128 * 1024}
chunk = b"x" * (64 * 1024)
while remaining:
    written = os.write({stream_fd}, chunk[:remaining])
    remaining -= written
"""
    plan = BuildPlan(
        package="npm:demo@1.0.0",
        ecosystem=Ecosystem.NPM,
        source_root=source,
        argv=(sys.executable, "-c", script),
        artifact_globs=("*.zip",),
        timeout_seconds=10,
    )

    with pytest.raises(RehearsalError, match=r"hard capture limit.*output truncated"):
        run_build_plan(plan, confirm_trusted=True)


def test_copy_preflight_enforces_entry_and_logical_size_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "one").write_bytes(b"123")
    (source / "two").write_bytes(b"456")

    monkeypatch.setattr(builder_module, "_COPY_MAX_ENTRIES", 1)
    with pytest.raises(RehearsalError, match="entry limit"):
        run_build_plan(_direct_plan(source), confirm_trusted=True)

    monkeypatch.setattr(builder_module, "_COPY_MAX_ENTRIES", 10)
    monkeypatch.setattr(builder_module, "_COPY_MAX_FILE_BYTES", 2)
    with pytest.raises(RehearsalError, match="single-file copy limit"):
        run_build_plan(_direct_plan(source), confirm_trusted=True)

    monkeypatch.setattr(builder_module, "_COPY_MAX_FILE_BYTES", 10_000)
    monkeypatch.setattr(builder_module, "_COPY_MAX_TOTAL_LOGICAL_BYTES", 5)
    with pytest.raises(RehearsalError, match="total logical-byte"):
        run_build_plan(_direct_plan(source), confirm_trusted=True)


def test_copy_preflight_enforces_allocated_size_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "one").write_bytes(b"1")
    (source / "two").write_bytes(b"2")
    monkeypatch.setattr(builder_module, "_allocated_file_bytes", lambda _metadata: 4)
    monkeypatch.setattr(builder_module, "_COPY_MAX_TOTAL_ALLOCATED_BYTES", 7)

    with pytest.raises(RehearsalError, match="total allocated-byte"):
        run_build_plan(_direct_plan(source), confirm_trusted=True)


def test_success_without_artifacts_is_an_error(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    plan = BuildPlan(
        package="npm:demo@1.0.0",
        ecosystem=Ecosystem.NPM,
        source_root=source,
        argv=(sys.executable, "-c", "print('nothing built')"),
        artifact_globs=("*.tgz",),
        timeout_seconds=10,
    )

    with pytest.raises(RehearsalError, match="produced no matching artifacts"):
        run_build_plan(plan, confirm_trusted=True)


def test_nonzero_build_and_missing_executable_are_actionable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    failed = BuildPlan(
        package="npm:demo@1.0.0",
        ecosystem=Ecosystem.NPM,
        source_root=source,
        argv=(sys.executable, "-c", "import sys; print('bad', file=sys.stderr); sys.exit(7)"),
        artifact_globs=("*.zip",),
    )
    with pytest.raises(RehearsalError, match="exit code 7: bad"):
        run_build_plan(failed, confirm_trusted=True)

    missing = BuildPlan(
        package="npm:demo@1.0.0",
        ecosystem=Ecosystem.NPM,
        source_root=source,
        argv=("packrehearsal-command-that-does-not-exist",),
        artifact_globs=("*.zip",),
    )
    with pytest.raises(RehearsalError, match="cannot start artifact rehearsal command"):
        run_build_plan(missing, confirm_trusted=True)


def test_source_symlinks_cannot_escape_disposable_workspace(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (source / "escape").symlink_to(outside)
    plan = BuildPlan(
        package="npm:demo@1.0.0",
        ecosystem=Ecosystem.NPM,
        source_root=source,
        argv=(sys.executable, "-c", "raise SystemExit(0)"),
        artifact_globs=("*.zip",),
    )

    with pytest.raises(RehearsalError, match=r"absolute symlink|escapes the allowed root"):
        run_build_plan(plan, confirm_trusted=True)


def test_detected_source_reparse_point_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "junction").mkdir()
    monkeypatch.setattr(
        builder_module,
        "_is_reparse_point",
        lambda path, _metadata: path.name == "junction",
    )

    with pytest.raises(RehearsalError, match=r"junction or reparse point"):
        run_build_plan(_direct_plan(source), confirm_trusted=True)


@pytest.mark.skipif(
    os.name != "nt" or not hasattr(Path, "is_junction"),
    reason="real junction coverage requires Windows with Path.is_junction",
)
def test_windows_source_junction_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    junction = source / "junction"
    subprocess.run(
        ("cmd", "/c", "mklink", "/J", str(junction), str(target)),
        check=True,
        capture_output=True,
    )
    assert junction.is_junction()  # type: ignore[attr-defined]

    with pytest.raises(RehearsalError, match=r"junction or reparse point"):
        run_build_plan(_direct_plan(source), confirm_trusted=True)


@pytest.mark.parametrize(
    ("ecosystem", "manifest"),
    [
        (Ecosystem.NPM, "package.json"),
        (Ecosystem.RUST, "Cargo.toml"),
    ],
)
def test_workspace_plan_copies_root_and_runs_from_member(
    tmp_path: Path,
    ecosystem: Ecosystem,
    manifest: str,
) -> None:
    member = tmp_path / "packages" / "app"
    member.mkdir(parents=True)
    (tmp_path / manifest).write_text("workspace root", encoding="utf-8")
    (member / manifest).write_text("member", encoding="utf-8")
    package = Package(
        ecosystem=ecosystem,
        name="app",
        version="1.0.0",
        root="packages/app",
        manifest=f"packages/app/{manifest}",
        workspace_root=".",
    )

    plan = plan_package_build(package, repository_root=tmp_path)

    assert plan.source_root == tmp_path.resolve()
    assert plan.working_directory == "packages/app"


def test_workspace_execution_keeps_root_siblings_and_committed_dist(tmp_path: Path) -> None:
    member = tmp_path / "packages" / "app"
    sibling = tmp_path / "packages" / "core"
    (member / "dist").mkdir(parents=True)
    sibling.mkdir(parents=True)
    (tmp_path / "package.json").write_text('{"private":true}', encoding="utf-8")
    (sibling / "package.json").write_text('{"name":"core"}', encoding="utf-8")
    (member / "dist" / "index.js").write_text("committed bundle", encoding="utf-8")
    script = """
import pathlib
import sys
import zipfile

cwd = pathlib.Path.cwd()
assert (cwd / "dist" / "index.js").read_text() == "committed bundle"
assert (cwd.parent.parent / "package.json").is_file()
assert (cwd.parent / "core" / "package.json").is_file()
output = pathlib.Path(sys.argv[1])
with zipfile.ZipFile(output / "workspace.zip", "w") as archive:
    archive.writestr("package/dist/index.js", "committed bundle")
"""
    plan = BuildPlan(
        package="npm:app@1.0.0",
        ecosystem=Ecosystem.NPM,
        source_root=tmp_path,
        working_directory="packages/app",
        argv=(sys.executable, "-c", script, "{output_dir}"),
        artifact_globs=("*.zip",),
    )

    result = run_build_plan(plan, confirm_trusted=True)

    assert [artifact.path for artifact in result.artifacts] == ["workspace.zip"]


@pytest.mark.parametrize(
    "key",
    [
        "PATH",
        "home",
        "HTTP_PROXY",
        "npm_config_offline",
        "PIP_NO_INDEX",
        "PYTHONPATH",
        "LD_PRELOAD",
        "DYLD_INSERT_LIBRARIES",
        "NODE_OPTIONS",
        "GIT_CONFIG_COUNT",
    ],
)
def test_plan_rejects_reserved_environment_overrides(tmp_path: Path, key: str) -> None:
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(ValueError, match="reserved safety variable"):
        BuildPlan(
            package="npm:demo@1.0.0",
            ecosystem=Ecosystem.NPM,
            source_root=source,
            argv=("tool",),
            artifact_globs=("*.zip",),
            environment={key: "attacker-controlled"},
        )


def test_runtime_scrubs_reserved_environment_from_forged_plan(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    script = """
import json
import os
import pathlib
import sys
import zipfile

keys = [
    "PATH", "HOME", "HTTP_PROXY", "PIP_NO_INDEX", "PYTHONPATH",
    "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "API_KEY", "PACKREHEARSAL_TEST",
]
print(json.dumps({key: os.environ.get(key) for key in keys}, sort_keys=True))
output = pathlib.Path(sys.argv[1])
with zipfile.ZipFile(output / "safe.zip", "w") as archive:
    archive.writestr("ok", "yes")
"""
    plan = BuildPlan(
        package="npm:demo@1.0.0",
        ecosystem=Ecosystem.NPM,
        source_root=source,
        argv=(sys.executable, "-c", script, "{output_dir}"),
        artifact_globs=("*.zip",),
    )
    object.__setattr__(
        plan,
        "environment",
        {
            "PATH": "poisoned-path",
            "HOME": "poisoned-home",
            "HTTP_PROXY": "http://attacker.invalid",
            "PIP_NO_INDEX": "0",
            "PYTHONPATH": "poisoned-pythonpath",
            "LD_PRELOAD": "poisoned-preload",
            "DYLD_INSERT_LIBRARIES": "poisoned-dyld",
            "API_KEY": "poisoned-credential",
            "PACKREHEARSAL_TEST": "kept",
        },
    )

    result = run_build_plan(plan, confirm_trusted=True)
    environment = __import__("json").loads(result.stdout)

    assert environment["PATH"] != "poisoned-path"
    assert environment["HOME"] != "poisoned-home"
    assert environment["HTTP_PROXY"] == "http://127.0.0.1:9"
    assert environment["PIP_NO_INDEX"] == "1"
    assert environment["PYTHONPATH"] is None
    assert environment["LD_PRELOAD"] is None
    assert environment["DYLD_INSERT_LIBRARIES"] is None
    assert environment["API_KEY"] is None
    assert environment["PACKREHEARSAL_TEST"] == "kept"


def test_invalid_plan_rejects_escape_globs_placeholders_and_credentials(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(ValueError, match="output directory"):
        BuildPlan(
            package="npm:demo@1.0.0",
            ecosystem=Ecosystem.NPM,
            source_root=source,
            argv=("tool",),
            artifact_globs=("../*.zip",),
        )
    with pytest.raises(ValueError, match="unsupported build placeholders"):
        BuildPlan(
            package="npm:demo@1.0.0",
            ecosystem=Ecosystem.NPM,
            source_root=source,
            argv=("tool", "{unknown}"),
            artifact_globs=("*.zip",),
        )
    with pytest.raises(ValueError, match="credentials"):
        BuildPlan(
            package="npm:demo@1.0.0",
            ecosystem=Ecosystem.NPM,
            source_root=source,
            argv=("tool",),
            artifact_globs=("*.zip",),
            environment={"API_KEY": "secret"},
        )
    with pytest.raises(ValueError, match="working directory"):
        BuildPlan(
            package="npm:demo@1.0.0",
            ecosystem=Ecosystem.NPM,
            source_root=source,
            argv=("tool",),
            artifact_globs=("*.zip",),
            working_directory="../escape",
        )


def test_repository_root_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-package"
    outside.mkdir(exist_ok=True)
    try:
        package = Package(
            ecosystem=Ecosystem.NPM,
            name="demo",
            version="1.0.0",
            root="../outside-package",
            manifest="../outside-package/package.json",
        )
        with pytest.raises(RehearsalError, match="escapes the allowed root"):
            plan_package_build(package, repository_root=tmp_path, config=Config())
    finally:
        os.rmdir(outside)
