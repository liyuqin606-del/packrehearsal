"""Command-line interface for PackRehearsal."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shlex
import shutil
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TextIO

from packrehearsal import __version__
from packrehearsal.artifacts import (
    inspect_artifact,
    plan_trusted_build,
    run_build_plan,
)
from packrehearsal.baseline import load_baseline, save_baseline
from packrehearsal.codex import render_codex_json, render_codex_markdown
from packrehearsal.config import (
    Config,
    default_config_dict,
    load_config,
    validate_configured_rule_ids,
)
from packrehearsal.discovery import discover_packages
from packrehearsal.engine import scan_repository
from packrehearsal.exceptions import PackRehearsalError, RehearsalError
from packrehearsal.models import ArtifactSnapshot, ScanReport, Severity
from packrehearsal.receipt import create_receipt, load_receipt, save_receipt, verify_receipt
from packrehearsal.reporters import render_console, render_json, render_markdown, render_sarif
from packrehearsal.rules import default_registry
from packrehearsal.serialization import atomic_write_text, canonical_json

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_REHEARSAL = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="packrehearsal",
        description="Inspect package artifacts before they reach a registry.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="run the safe static repository scan")
    _add_scan_arguments(scan)
    scan.set_defaults(handler=_handle_scan)

    codex_brief = subparsers.add_parser(
        "codex-brief",
        help="turn new static findings into an evidence-bounded Codex maintenance task",
    )
    _add_codex_brief_arguments(codex_brief)
    codex_brief.set_defaults(handler=_handle_codex_brief)

    inspect = subparsers.add_parser(
        "inspect", help="produce a bounded structural snapshot of an artifact"
    )
    inspect.add_argument("artifact", type=Path)
    _add_report_arguments(inspect, formats=("console", "json", "markdown", "sarif"))
    inspect.set_defaults(handler=_handle_inspect)

    rehearse = subparsers.add_parser(
        "rehearse", help="build candidates from an explicitly trusted repository"
    )
    rehearse.add_argument("root", nargs="?", type=Path, default=Path("."))
    rehearse.add_argument(
        "--trusted-rehearsal",
        action="store_true",
        help="acknowledge that package builds can execute arbitrary project code",
    )
    rehearse.add_argument("--allow-network", action="store_true")
    rehearse.add_argument("--config", type=Path)
    rehearse.add_argument(
        "--no-repo-config",
        action="store_true",
        help="ignore repository configuration and use built-in safety policy",
    )
    rehearse.add_argument("--baseline", type=Path)
    rehearse.add_argument("--receipt", type=Path)
    rehearse.add_argument("--fail-on", choices=[item.value for item in Severity])
    _add_report_arguments(rehearse, formats=("console", "json", "markdown", "sarif"))
    rehearse.set_defaults(handler=_handle_rehearse)

    verify = subparsers.add_parser("verify-receipt", help="verify an evidence receipt")
    verify.add_argument("receipt", type=Path)
    verify.add_argument("--artifact-root", type=Path)
    verify.set_defaults(handler=_handle_verify_receipt)

    initialize = subparsers.add_parser("init", help="write conservative configuration defaults")
    initialize.add_argument("--root", type=Path, default=Path("."))
    initialize.add_argument("--force", action="store_true")
    initialize.set_defaults(handler=_handle_init)

    rules = subparsers.add_parser("rules", help="list the executable rule catalog")
    rules.add_argument("--format", choices=("table", "json"), default="table")
    rules.set_defaults(handler=_handle_rules)

    doctor = subparsers.add_parser("doctor", help="show local toolchain readiness")
    doctor.set_defaults(handler=_handle_doctor)
    return parser


def _add_scan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--artifact", action="append", default=[], type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--no-repo-config",
        action="store_true",
        help="ignore repository configuration and use built-in safety policy",
    )
    parser.add_argument("--fail-on", choices=[item.value for item in Severity])
    parser.add_argument("--new-only", action="store_true")
    parser.add_argument("--no-fail", action="store_true")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--write-baseline", type=Path)
    _add_report_arguments(parser, formats=("console", "json", "markdown", "sarif"))


def _add_codex_brief_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--artifact", action="append", default=[], type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--no-repo-config",
        action="store_true",
        help="ignore repository configuration and use built-in safety policy",
    )
    parser.add_argument(
        "--minimum-severity",
        choices=[item.value for item in Severity],
        default=Severity.INFO.value,
        help="include new findings at or above this severity (default: info)",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)


def _add_report_arguments(
    parser: argparse.ArgumentParser,
    *,
    formats: tuple[str, ...],
) -> None:
    parser.add_argument("--format", choices=formats, default=formats[0])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
        return int(arguments.handler(arguments))
    except RehearsalError as exc:
        _error(str(exc))
        return EXIT_REHEARSAL
    except (PackRehearsalError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        _error(str(exc))
        return EXIT_USAGE


def _handle_scan(arguments: argparse.Namespace) -> int:
    root = arguments.root.expanduser().resolve()
    config = _resolved_config(
        root,
        arguments.config,
        arguments.fail_on,
        no_repo_config=arguments.no_repo_config,
    )
    baseline = load_baseline(arguments.baseline) if arguments.baseline else ()
    report = scan_repository(
        root,
        config=config,
        artifact_paths=arguments.artifact,
        baseline_fingerprints=baseline,
    )
    _emit_report(report, arguments)
    if arguments.write_baseline:
        save_baseline(arguments.write_baseline, report)
    if arguments.receipt:
        save_receipt(arguments.receipt, create_receipt(report))
    if arguments.no_fail:
        return EXIT_OK
    return EXIT_FINDINGS if report.should_fail(config.fail_on, new_only=True) else EXIT_OK


def _handle_codex_brief(arguments: argparse.Namespace) -> int:
    root = arguments.root.expanduser().resolve()
    _validate_codex_inputs_are_portable(root, arguments)
    config = _resolved_config(
        root,
        arguments.config,
        None,
        no_repo_config=arguments.no_repo_config,
    )
    baseline = load_baseline(arguments.baseline) if arguments.baseline else ()
    report = scan_repository(
        root,
        config=config,
        artifact_paths=arguments.artifact,
        baseline_fingerprints=baseline,
    )
    verification_command = _codex_verification_command(arguments, root)
    minimum_severity = Severity.parse(arguments.minimum_severity)
    if arguments.format == "json":
        content = render_codex_json(
            report,
            minimum_severity=minimum_severity,
            verification_command=verification_command,
        )
    else:
        content = render_codex_markdown(
            report,
            minimum_severity=minimum_severity,
            verification_command=verification_command,
        )
    if arguments.output is None:
        print(content, end="")
    else:
        atomic_write_text(arguments.output, content)
    return EXIT_OK


def _handle_inspect(arguments: argparse.Namespace) -> int:
    artifact = arguments.artifact.expanduser()
    snapshot = inspect_artifact(artifact, display_path=artifact.name)
    report = ScanReport(
        root=".",
        packages=(),
        findings=(),
        artifacts=(snapshot,),
    )
    _emit_report(report, arguments)
    return EXIT_OK


def _handle_rehearse(arguments: argparse.Namespace) -> int:
    if not arguments.trusted_rehearsal:
        raise RehearsalError(
            "trusted rehearsal can execute project code; rerun with --trusted-rehearsal "
            "only for a repository and revision you trust"
        )
    root = arguments.root.expanduser().resolve()
    config = _resolved_config(
        root,
        arguments.config,
        arguments.fail_on,
        no_repo_config=arguments.no_repo_config,
    )
    if arguments.allow_network:
        config = replace(config, allow_network=True)
    validate_configured_rule_ids(config, default_registry().rule_ids)
    discovery = discover_packages(root, config)
    if not discovery.packages:
        raise RehearsalError("no supported publishable packages were discovered")

    snapshots: list[ArtifactSnapshot] = []
    for package in discovery.packages:
        plan = plan_trusted_build(
            package,
            repository_root=root,
            config=config,
            allow_network=arguments.allow_network,
        )
        print(
            f"Trusted build plan for {package.identity}: {shlex.join(plan.argv)} "
            f"(network={'enabled' if plan.allow_network else 'disabled'})",
            file=sys.stderr,
        )
        result = run_build_plan(plan, confirm_trusted=True, limits=config.archive)
        snapshots.extend(result.artifacts)
    baseline = load_baseline(arguments.baseline) if arguments.baseline else ()
    report = scan_repository(
        root,
        config=config,
        artifacts=snapshots,
        baseline_fingerprints=baseline,
    )
    _emit_report(report, arguments)
    if arguments.receipt:
        save_receipt(arguments.receipt, create_receipt(report))
    return EXIT_FINDINGS if report.should_fail(config.fail_on, new_only=True) else EXIT_OK


def _handle_verify_receipt(arguments: argparse.Namespace) -> int:
    receipt = load_receipt(arguments.receipt)
    checks = verify_receipt(receipt, artifact_root=arguments.artifact_root)
    print("Self-consistency checks passed: " + ", ".join(checks))
    return EXIT_OK


def _handle_init(arguments: argparse.Namespace) -> int:
    root = arguments.root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"configuration root is not a directory: {root}")
    path = root / ".packrehearsal.json"
    if path.exists() and not arguments.force:
        raise ValueError(f"configuration already exists: {path}; use --force to replace it")
    atomic_write_text(path, canonical_json(default_config_dict(), pretty=True))
    print(path)
    return EXIT_OK


def _handle_rules(arguments: argparse.Namespace) -> int:
    descriptors = default_registry().descriptors
    if arguments.format == "json":
        print(canonical_json([item.to_dict() for item in descriptors], pretty=True), end="")
    else:
        print("RULE ID                         SEVERITY  ECOSYSTEMS  TITLE")
        for descriptor in descriptors:
            ecosystems = ",".join(item.value for item in descriptor.ecosystems) or "all"
            print(
                f"{descriptor.rule_id:<31} "
                f"{descriptor.default_severity.value:<9} "
                f"{ecosystems:<11} {descriptor.title}"
            )
    return EXIT_OK


def _handle_doctor(_arguments: argparse.Namespace) -> int:
    print(f"PackRehearsal {__version__}")
    print(f"Python: {platform.python_version()} ({sys.executable})")
    print(f"Platform: {platform.system()} {platform.machine()}")
    print("Static scan: ready (no external tools required)")
    python_build = "available" if importlib.util.find_spec("build") else "unavailable"
    print(f"Trusted Python rehearsal backend: {python_build} (install packrehearsal[rehearsal])")
    for name in ("npm", "cargo"):
        executable = shutil.which(name)
        print(f"Trusted {name} rehearsal: {executable or 'unavailable'}")
    print("Network policy: disabled by default; trusted builds are not an OS-level sandbox")
    return EXIT_OK


def _resolved_config(
    root: Path,
    explicit: Path | None,
    fail_on: str | None,
    *,
    no_repo_config: bool,
) -> Config:
    if no_repo_config and explicit is not None:
        raise ValueError("--config and --no-repo-config cannot be used together")
    config = Config() if no_repo_config else load_config(root, explicit)
    if fail_on is not None:
        config = replace(config, fail_on=Severity.parse(fail_on))
    return config


def _codex_verification_command(
    arguments: argparse.Namespace,
    root: Path,
) -> str:
    command = ["packrehearsal", "scan", "."]
    for artifact in arguments.artifact:
        command.extend(("--artifact", _repository_relative_path(artifact, root)))
    if arguments.baseline is not None:
        command.extend(("--baseline", _repository_relative_path(arguments.baseline, root)))
    if arguments.no_repo_config:
        command.append("--no-repo-config")
    elif arguments.config is not None:
        command.extend(("--config", _repository_relative_path(arguments.config, root)))
    command.extend(("--format", "json", "--no-fail"))
    return shlex.join(command)


def _validate_codex_inputs_are_portable(
    root: Path,
    arguments: argparse.Namespace,
) -> None:
    paths = [*arguments.artifact]
    if arguments.baseline is not None:
        paths.append(arguments.baseline)
    if arguments.config is not None:
        paths.append(arguments.config)
    for path in paths:
        _repository_relative_path(path, root)


def _repository_relative_path(path: Path, root: Path) -> str:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve(strict=False).relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Codex brief inputs must be inside the repository for a portable task: {path}"
        ) from exc


def _emit_report(report: ScanReport, arguments: argparse.Namespace) -> None:
    color = arguments.color == "always" or (
        arguments.color == "auto" and arguments.output is None and sys.stdout.isatty()
    )
    new_only = bool(getattr(arguments, "new_only", False))
    renderers = {
        "console": lambda: render_console(report, color=color, new_only=new_only),
        "json": lambda: render_json(report),
        "markdown": lambda: render_markdown(report, new_only=new_only),
        "sarif": lambda: render_sarif(report, new_only=new_only),
    }
    content = renderers[arguments.format]()
    if arguments.output is None:
        print(content, end="")
    else:
        atomic_write_text(arguments.output, content)


def _error(message: str, stream: TextIO | None = None) -> None:
    target = stream or sys.stderr
    print(f"packrehearsal: error: {message}", file=target)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
