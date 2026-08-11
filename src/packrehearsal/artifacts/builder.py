"""Explicit, isolated build plans for artifact rehearsal.

Safe plans disable lifecycle scripts or verification builds where the package
manager supports that mode. Every subprocess requires a second
``confirm_trusted`` gate at execution time. Commands always use ``shell=False``
inside a disposable copy with a small allow-listed environment.

The offline environment and package-manager flags are defense in depth, not an
OS network sandbox.  Only explicitly trusted project code should ever be run.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from time import monotonic
from typing import BinaryIO

from packrehearsal.config import ArchiveLimits, Config
from packrehearsal.exceptions import RehearsalError
from packrehearsal.models import ArtifactSnapshot, Ecosystem, Package

from .archive import inspect_artifact

_OUTPUT_LIMIT_BYTES = 1024 * 1024
_OUTPUT_DRAIN_GRACE_SECONDS = 1.0
_COPY_MAX_ENTRIES = 50_000
_COPY_MAX_FILE_BYTES = 256 * 1024 * 1024
_COPY_MAX_TOTAL_LOGICAL_BYTES = 1024 * 1024 * 1024
_COPY_MAX_TOTAL_ALLOCATED_BYTES = 1024 * 1024 * 1024
_PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_ALLOWED_PLACEHOLDERS = {"{output_dir}", "{workspace}"}
_SENSITIVE_ENV_FRAGMENT = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTHORIZATION|API_KEY|PRIVATE_KEY)", re.I
)
# These variables define the executable search path, temporary/home isolation,
# interpreter loading, package-manager safety, or network policy. A BuildPlan
# may add application-specific values, but it must never weaken this boundary.
_RESERVED_ENVIRONMENT = {
    "ALL_PROXY",
    "BASH_ENV",
    "CARGO_HOME",
    "CARGO_NET_OFFLINE",
    "CI",
    "COMSPEC",
    "ENV",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_GLOBAL",
    "GIT_TERMINAL_PROMPT",
    "HOME",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "LANG",
    "LC_ALL",
    "NODE_OPTIONS",
    "NODE_PATH",
    "NO_PROXY",
    "NPM_CONFIG_IGNORE_SCRIPTS",
    "NPM_CONFIG_OFFLINE",
    "NPM_CONFIG_REGISTRY",
    "NPM_CONFIG_USERCONFIG",
    "PATH",
    "PATHEXT",
    "PIP_CONFIG_FILE",
    "PIP_DISABLE_PIP_VERSION_CHECK",
    "PIP_EXTRA_INDEX_URL",
    "PIP_INDEX_URL",
    "PIP_NO_INDEX",
    "PYTHONHOME",
    "PYTHONPATH",
    "SYSTEMROOT",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "WINDIR",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
}
_RESERVED_ENVIRONMENT_PREFIXES = (
    "CARGO_REGISTRIES_",
    "DYLD_",
    "GIT_CONFIG_",
    "LD_",
)
_COPY_IGNORES = (
    "__pycache__",
    ".coverage",
    ".hypothesis",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "node_modules",
    "target",
)


@dataclass(frozen=True, slots=True)
class BuildPlan:
    """A structured, shell-free command to produce candidate artifacts."""

    package: str
    ecosystem: Ecosystem
    source_root: Path
    argv: tuple[str, ...]
    artifact_globs: tuple[str, ...]
    timeout_seconds: int = 180
    executes_project_code: bool = False
    allow_network: bool = False
    environment: Mapping[str, str] = field(default_factory=dict, compare=False, hash=False)
    # Kept last so callers using the historical positional arguments retain
    # their meaning; new code should pass this field by keyword.
    working_directory: str = "."

    def __post_init__(self) -> None:
        if not self.argv or any(not argument or "\x00" in argument for argument in self.argv):
            raise ValueError("build argv must contain non-empty, NUL-free arguments")
        unknown_placeholders = {
            placeholder
            for argument in self.argv
            for placeholder in _PLACEHOLDER.findall(argument)
            if placeholder not in _ALLOWED_PLACEHOLDERS
        }
        if unknown_placeholders:
            raise ValueError(
                f"unsupported build placeholders: {', '.join(sorted(unknown_placeholders))}"
            )
        if not self.artifact_globs:
            raise ValueError("at least one artifact glob is required")
        for pattern in self.artifact_globs:
            portable = pattern.replace("\\", "/")
            if not portable or portable.startswith("/") or ".." in portable.split("/"):
                raise ValueError(f"artifact glob must stay below the output directory: {pattern!r}")
        working_directory = _safe_relative_directory(self.working_directory)
        object.__setattr__(self, "working_directory", working_directory)
        if self.timeout_seconds < 1 or self.timeout_seconds > 3_600:
            raise ValueError("build timeout must be between 1 and 3600 seconds")
        for key, value in self.environment.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("build environment names and values must be strings")
            if not key or "=" in key or "\x00" in key or "\x00" in value:
                raise ValueError(f"invalid build environment entry: {key!r}")
            if _SENSITIVE_ENV_FRAGMENT.search(key):
                raise ValueError(f"credentials must not be injected into rehearsal builds: {key}")
            if _reserved_environment_key(key):
                raise ValueError(
                    f"build environment cannot override reserved safety variable: {key}"
                )


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Serializable evidence retained after the temporary build tree is removed."""

    package: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    artifacts: tuple[ArtifactSnapshot, ...]


@dataclass(slots=True)
class _BoundedOutput:
    """One pipe's bounded in-memory capture state."""

    payload: bytearray = field(default_factory=bytearray)
    truncated: bool = False
    error: OSError | None = None


def plan_package_build(
    package: Package,
    *,
    repository_root: Path | str = Path("."),
    config: Config | None = None,
    trusted: bool = False,
    allow_network: bool | None = None,
    python_executable: str | None = None,
) -> BuildPlan:
    """Create a conservative package-manager build plan.

    npm and Cargo have useful no-script/no-build packaging modes.  PEP 517 has
    no equivalent: even metadata/build hooks execute backend code, so Python
    plans require ``trusted=True``.
    """

    active_config = config or Config()
    network_enabled = active_config.allow_network if allow_network is None else allow_network
    repo_root = Path(repository_root).resolve()
    package_root = (repo_root / package.root).resolve()
    _require_within(package_root, repo_root, label="package root")
    if not package_root.is_dir():
        raise RehearsalError(f"package root is not a directory: {package_root}")

    copy_root_value = package.workspace_root if package.workspace_root is not None else package.root
    source_root = (repo_root / copy_root_value).resolve()
    _require_within(source_root, repo_root, label="workspace root")
    if not source_root.is_dir():
        raise RehearsalError(f"workspace root is not a directory: {source_root}")
    _require_within(package_root, source_root, label="package root")
    working_directory = package_root.relative_to(source_root).as_posix() or "."

    artifact_globs: tuple[str, ...]
    if package.ecosystem is Ecosystem.NPM:
        argv = [
            "npm",
            "pack",
            "--json",
            "--pack-destination",
            "{output_dir}",
            "--ignore-scripts",
        ]
        artifact_globs = ("*.tgz",)
    elif package.ecosystem is Ecosystem.PYTHON:
        if not trusted:
            raise RehearsalError(
                "Python artifact builds execute a PEP 517 backend; request a trusted plan "
                "explicitly or inspect an existing dist artifact"
            )
        argv = [python_executable or sys.executable, "-m", "build"]
        if not network_enabled:
            argv.append("--no-isolation")
        argv.extend(("--outdir", "{output_dir}", "."))
        artifact_globs = ("*.whl", "*.tar.gz", "*.zip")
    elif package.ecosystem is Ecosystem.RUST:
        argv = [
            "cargo",
            "package",
            "--allow-dirty",
            "--target-dir",
            "{output_dir}/target",
        ]
        if not trusted:
            argv.append("--no-verify")
        if not network_enabled:
            argv.append("--offline")
        artifact_globs = ("target/package/*.crate",)
    else:  # pragma: no cover - the enum currently makes this defensive only
        raise RehearsalError(f"unsupported package ecosystem: {package.ecosystem}")

    return BuildPlan(
        package=package.identity,
        ecosystem=package.ecosystem,
        source_root=source_root,
        argv=tuple(argv),
        artifact_globs=artifact_globs,
        working_directory=working_directory,
        timeout_seconds=active_config.trusted_timeout_seconds,
        executes_project_code=trusted and package.ecosystem is not Ecosystem.NPM,
        allow_network=network_enabled,
    )


def plan_trusted_build(
    package: Package,
    *,
    repository_root: Path | str = Path("."),
    config: Config | None = None,
    allow_network: bool | None = None,
    python_executable: str | None = None,
) -> BuildPlan:
    """Convenience wrapper whose name makes the trust transition explicit."""

    return plan_package_build(
        package,
        repository_root=repository_root,
        config=config,
        trusted=True,
        allow_network=allow_network,
        python_executable=python_executable,
    )


def run_build_plan(
    plan: BuildPlan,
    *,
    confirm_trusted: bool = False,
    limits: ArchiveLimits | None = None,
) -> BuildResult:
    """Execute a plan in a disposable workspace and inspect its artifacts."""

    if not confirm_trusted:
        raise RehearsalError(
            "every artifact rehearsal subprocess requires explicit trusted confirmation"
        )

    deadline = monotonic() + plan.timeout_seconds
    requested_source_root = plan.source_root.expanduser()
    try:
        requested_metadata = requested_source_root.lstat()
    except OSError as exc:
        raise RehearsalError(f"cannot inspect build source {requested_source_root}: {exc}") from exc
    if _is_reparse_point(requested_source_root, requested_metadata):
        raise RehearsalError(
            f"build source contains a Windows junction or reparse point: {requested_source_root}"
        )
    source_root = plan.source_root.resolve()
    if not source_root.is_dir():
        raise RehearsalError(f"build source no longer exists: {source_root}")
    _preflight_source_copy(
        source_root,
        deadline=deadline,
        timeout_seconds=plan.timeout_seconds,
    )
    _require_time_remaining(deadline, plan.timeout_seconds)

    with tempfile.TemporaryDirectory(prefix="packrehearsal-build-") as temporary:
        # macOS commonly exposes /var as a symlink to /private/var. Resolve the
        # temporary root once so containment checks compare canonical paths.
        temporary_root = Path(temporary).resolve()
        workspace = temporary_root / "workspace"
        output_dir = temporary_root / "artifacts"
        home = temporary_root / "home"
        output_dir.mkdir(mode=0o700)
        home.mkdir(mode=0o700)
        ignored = shutil.ignore_patterns(*_COPY_IGNORES)

        def ignore_with_deadline(directory: str, names: list[str]) -> set[str]:
            _require_time_remaining(deadline, plan.timeout_seconds)
            return set(ignored(directory, names))

        def copy_with_deadline(source: str, destination: str) -> str:
            _require_time_remaining(deadline, plan.timeout_seconds)
            result = shutil.copy2(source, destination)
            _require_time_remaining(deadline, plan.timeout_seconds)
            return result

        try:
            shutil.copytree(
                source_root,
                workspace,
                symlinks=True,
                ignore=ignore_with_deadline,
                copy_function=copy_with_deadline,
            )
        except OSError as exc:
            raise RehearsalError(f"cannot create disposable build workspace: {exc}") from exc
        _require_time_remaining(deadline, plan.timeout_seconds)

        build_directory = (workspace / plan.working_directory).resolve()
        _require_within(build_directory, workspace, label="build working directory")
        if not build_directory.is_dir():
            raise RehearsalError(
                f"build working directory does not exist in disposable workspace: "
                f"{plan.working_directory}"
            )

        command = tuple(
            argument.replace("{output_dir}", str(output_dir)).replace("{workspace}", str(workspace))
            for argument in plan.argv
        )
        environment = _clean_environment(plan, temporary_root=temporary_root, home=home)
        returncode, stdout, stderr = _run_command(
            command,
            cwd=build_directory,
            environment=environment,
            timeout_seconds=plan.timeout_seconds,
            deadline=deadline,
        )
        if returncode != 0:
            detail = stderr.strip() or stdout.strip() or "no diagnostic output"
            raise RehearsalError(
                f"artifact rehearsal failed for {plan.package} with exit code {returncode}: "
                f"{detail}"
            )

        artifact_paths = _collect_artifacts(output_dir, plan.artifact_globs)
        if not artifact_paths:
            raise RehearsalError(
                f"artifact rehearsal for {plan.package} succeeded but produced no matching "
                "artifacts"
            )
        snapshots = tuple(
            inspect_artifact(
                artifact,
                limits=limits,
                display_path=artifact.relative_to(output_dir).as_posix(),
            )
            for artifact in artifact_paths
        )
        return BuildResult(
            package=plan.package,
            command=plan.argv,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            artifacts=snapshots,
        )


def run_trusted_build(plan: BuildPlan, *, limits: ArchiveLimits | None = None) -> BuildResult:
    """Run a plan with an explicit trust-bearing function call."""

    return run_build_plan(plan, confirm_trusted=True, limits=limits)


def _clean_environment(
    plan: BuildPlan,
    *,
    temporary_root: Path,
    home: Path,
) -> dict[str, str]:
    allowed_inherited = (
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TERM",
        "WINDIR",
    )
    inherited = {key: os.environ[key] for key in allowed_inherited if key in os.environ}
    controlled = {
        "CI": "true",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(home),
        "TMP": str(temporary_root),
        "TEMP": str(temporary_root),
        "TMPDIR": str(temporary_root),
        "USERPROFILE": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
    }
    if plan.ecosystem is Ecosystem.NPM:
        controlled.update(
            {
                "NPM_CONFIG_IGNORE_SCRIPTS": "true",
                "npm_config_ignore_scripts": "true",
            }
        )
    if not plan.allow_network:
        unreachable_proxy = "http://127.0.0.1:9"
        controlled.update(
            {
                "ALL_PROXY": unreachable_proxy,
                "CARGO_NET_OFFLINE": "true",
                "HTTP_PROXY": unreachable_proxy,
                "HTTPS_PROXY": unreachable_proxy,
                "NO_PROXY": "",
                "NPM_CONFIG_OFFLINE": "true",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_INDEX": "1",
                "all_proxy": unreachable_proxy,
                "http_proxy": unreachable_proxy,
                "https_proxy": unreachable_proxy,
                "no_proxy": "",
                "npm_config_offline": "true",
            }
        )
    # Start with caller additions, remove any reserved key again in case a
    # forged/deserialized plan bypassed ``BuildPlan.__post_init__``, then apply
    # inherited and safety-controlled values last.
    environment = {
        key: value
        for key, value in plan.environment.items()
        if isinstance(key, str)
        and isinstance(value, str)
        and not _reserved_environment_key(key)
        and not _SENSITIVE_ENV_FRAGMENT.search(key)
    }
    environment.update(inherited)
    environment.update(controlled)
    return environment


def _reserved_environment_key(key: str) -> bool:
    normalized = key.upper()
    return normalized in _RESERVED_ENVIRONMENT or normalized.startswith(
        _RESERVED_ENVIRONMENT_PREFIXES
    )


def _safe_relative_directory(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("build working directory must be a non-empty relative path")
    portable = value.replace("\\", "/")
    path = PurePosixPath(portable)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", portable) or ".." in path.parts:
        raise ValueError("build working directory must stay below the copied source root")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    return "/".join(parts) or "."


def _run_command(
    command: tuple[str, ...],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
    deadline: float | None = None,
) -> tuple[int, str, str]:
    active_deadline = monotonic() + timeout_seconds if deadline is None else deadline
    creationflags = 0
    start_new_session = os.name == "posix"
    if os.name == "nt":  # pragma: no cover - exercised on Windows CI
        creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=start_new_session,
            creationflags=creationflags,
        )
    except RehearsalError:
        raise
    except OSError as exc:
        raise RehearsalError(
            f"cannot start artifact rehearsal command {command[0]!r}: {exc}"
        ) from exc

    if process.stdout is None or process.stderr is None:  # pragma: no cover - Popen invariant
        _terminate_process_tree(process)
        process.wait()
        raise RehearsalError("cannot capture artifact rehearsal output")

    stdout_capture = _BoundedOutput()
    stderr_capture = _BoundedOutput()
    output_exceeded = threading.Event()
    readers = (
        threading.Thread(
            target=_drain_bounded_output,
            args=(process.stdout, stdout_capture, process, output_exceeded),
            daemon=True,
        ),
        threading.Thread(
            target=_drain_bounded_output,
            args=(process.stderr, stderr_capture, process, output_exceeded),
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()

    timed_out = False
    timeout_cause: subprocess.TimeoutExpired | None = None
    try:
        remaining = active_deadline - monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, timeout=0)
        returncode = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        timeout_cause = exc
        _terminate_process_tree(process)
        returncode = process.wait()

    _finish_output_readers(process, readers)
    stdout = _decode_bounded_output(stdout_capture)
    stderr = _decode_bounded_output(stderr_capture)
    capture_error = stdout_capture.error or stderr_capture.error
    if capture_error is not None:
        raise RehearsalError(f"cannot capture artifact rehearsal output: {capture_error}")
    if timed_out:
        detail = stderr.strip() or stdout.strip()
        suffix = f": {detail}" if detail else ""
        error = RehearsalError(
            f"artifact rehearsal timed out after {timeout_seconds} seconds{suffix}"
        )
        if timeout_cause is not None:
            raise error from timeout_cause
        raise error  # pragma: no cover - timeout always retains its cause
    if output_exceeded.is_set():
        detail = stderr.strip() or stdout.strip()
        bounded_detail = detail[:4096]
        suffix = f": {bounded_detail}" if bounded_detail else ""
        raise RehearsalError(
            f"artifact rehearsal output exceeded the hard capture limit of "
            f"{_OUTPUT_LIMIT_BYTES} bytes per stream [output truncated]{suffix}"
        )
    return returncode, stdout, stderr


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    else:  # pragma: no cover - exercised on Windows CI
        process.kill()


def _drain_bounded_output(
    stream: BinaryIO,
    capture: _BoundedOutput,
    process: subprocess.Popen[bytes],
    output_exceeded: threading.Event,
) -> None:
    try:
        while chunk := stream.read(64 * 1024):
            remaining = _OUTPUT_LIMIT_BYTES - len(capture.payload)
            if remaining > 0:
                capture.payload.extend(chunk[:remaining])
            if len(chunk) > remaining:
                capture.truncated = True
                if not output_exceeded.is_set():
                    output_exceeded.set()
                    _terminate_process_tree(process)
    except OSError as exc:
        capture.error = exc
    finally:
        try:
            stream.close()
        except OSError as exc:
            if capture.error is None:
                capture.error = exc


def _finish_output_readers(
    process: subprocess.Popen[bytes],
    readers: tuple[threading.Thread, threading.Thread],
) -> None:
    for reader in readers:
        reader.join(timeout=_OUTPUT_DRAIN_GRACE_SECONDS)
    if all(not reader.is_alive() for reader in readers):
        return
    # A descendant may have inherited a pipe after the command's main process
    # exited. On POSIX it remains in the command's process group, so terminate
    # that group before giving the bounded readers one final grace period.
    if os.name == "posix":
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    for reader in readers:
        reader.join(timeout=_OUTPUT_DRAIN_GRACE_SECONDS)
    if any(reader.is_alive() for reader in readers):
        raise RehearsalError("artifact rehearsal output pipes did not close")


def _decode_bounded_output(capture: _BoundedOutput) -> str:
    decoded = bytes(capture.payload).decode("utf-8", errors="replace")
    return decoded + ("\n[output truncated]" if capture.truncated else "")


def _collect_artifacts(output_dir: Path, patterns: tuple[str, ...]) -> tuple[Path, ...]:
    artifacts: dict[str, Path] = {}
    for pattern in patterns:
        for candidate in output_dir.glob(pattern):
            try:
                mode = candidate.lstat().st_mode
            except OSError as exc:
                raise RehearsalError(f"cannot stat produced artifact {candidate}: {exc}") from exc
            if stat.S_ISLNK(mode):
                raise RehearsalError(
                    f"build produced a symlink instead of an artifact: {candidate}"
                )
            if stat.S_ISREG(mode):
                relative = candidate.relative_to(output_dir).as_posix()
                artifacts[relative] = candidate
    return tuple(artifacts[key] for key in sorted(artifacts))


def _preflight_source_copy(
    source_root: Path,
    *,
    deadline: float,
    timeout_seconds: int,
) -> None:
    """Bound and validate exactly the source entries copytree will retain."""

    entries = 0
    total_logical = 0
    total_allocated = 0
    pending = [source_root]
    while pending:
        _require_time_remaining(deadline, timeout_seconds)
        current = pending.pop()
        try:
            children = sorted(os.scandir(current), key=lambda item: item.name)
        except OSError as exc:
            raise RehearsalError(f"cannot enumerate build source {current}: {exc}") from exc
        for child in children:
            _require_time_remaining(deadline, timeout_seconds)
            if child.name in _COPY_IGNORES:
                continue
            candidate = current / child.name
            try:
                metadata = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise RehearsalError(
                    f"cannot inspect build source entry {candidate}: {exc}"
                ) from exc
            if _is_reparse_point(candidate, metadata):
                raise RehearsalError(
                    f"build source contains a Windows junction or reparse point: {candidate}"
                )

            entries += 1
            if entries > _COPY_MAX_ENTRIES:
                raise RehearsalError(
                    f"build source exceeds hard copy entry limit {_COPY_MAX_ENTRIES}"
                )
            mode = metadata.st_mode
            if stat.S_ISLNK(mode):
                _validate_source_symlink(candidate, source_root)
            elif stat.S_ISDIR(mode):
                pending.append(candidate)
            elif stat.S_ISREG(mode):
                logical = metadata.st_size
                allocated = _allocated_file_bytes(metadata)
                if logical > _COPY_MAX_FILE_BYTES or allocated > _COPY_MAX_FILE_BYTES:
                    raise RehearsalError(
                        f"build source file exceeds hard single-file copy limit "
                        f"{_COPY_MAX_FILE_BYTES}: {candidate}"
                    )
                total_logical += logical
                total_allocated += allocated
                if total_logical > _COPY_MAX_TOTAL_LOGICAL_BYTES:
                    raise RehearsalError(
                        "build source exceeds hard total logical-byte copy limit "
                        f"{_COPY_MAX_TOTAL_LOGICAL_BYTES}"
                    )
                if total_allocated > _COPY_MAX_TOTAL_ALLOCATED_BYTES:
                    raise RehearsalError(
                        "build source exceeds hard total allocated-byte copy limit "
                        f"{_COPY_MAX_TOTAL_ALLOCATED_BYTES}"
                    )
            else:
                raise RehearsalError(
                    f"build source contains an unsupported special file: {candidate}"
                )


def _validate_source_symlink(candidate: Path, source_root: Path) -> None:
    try:
        link_target = Path(os.readlink(candidate))
    except OSError as exc:
        raise RehearsalError(f"cannot inspect source symlink {candidate}: {exc}") from exc
    if link_target.is_absolute():
        raise RehearsalError(f"source tree contains an absolute symlink: {candidate}")
    resolved_target = (candidate.parent / link_target).resolve(strict=False)
    _require_within(resolved_target, source_root, label=f"symlink {candidate}")


def _allocated_file_bytes(metadata: os.stat_result) -> int:
    blocks = getattr(metadata, "st_blocks", None)
    if isinstance(blocks, int) and blocks >= 0:
        return blocks * 512
    return metadata.st_size


def _is_reparse_point(path: Path, metadata: os.stat_result) -> bool:
    junction_check = getattr(path, "is_junction", None)
    if callable(junction_check) and junction_check():
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & marker)


def _require_time_remaining(deadline: float, timeout_seconds: int) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise RehearsalError(f"artifact rehearsal timed out after {timeout_seconds} seconds")
    return remaining


def _require_within(path: Path, root: Path, *, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RehearsalError(f"{label} escapes the allowed root: {path}") from exc
