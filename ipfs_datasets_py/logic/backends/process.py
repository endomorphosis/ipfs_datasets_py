"""Bounded, injectable lifecycle for external logic tools.

This module is the common process boundary for native executables, proof-kernel
hosts, and tools hosted by JVM, OCaml/opam, or WASM runtimes.  It intentionally
does not know how to install any of them.  Discovery is a side-effect-free path
lookup and execution happens only after an explicit
:meth:`BoundedToolRunner.run` call.

The boundary implements ``UniversalBoundedToolLifecycle@1`` /
``BoundedToolRunner@1`` and has four important properties:

* commands are argv sequences and are always launched with ``shell=False``;
* every run receives a private workspace which is removed on every exit path;
* wall time, OS resources, captured streams, inputs, outputs, and paths are
  bounded;
* cancellation and timeout terminate the process group, not only its leader.

``BoundedToolRunner`` accepts an injected executor.  Backend adapters can
therefore use a deterministic fake in unit tests while production uses
``SubprocessExecutor``.  SMT/differential-style stdin solvers should call
:func:`run_bounded_stdin_tool` instead of raw ``subprocess.run``.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Protocol

BOUNDED_TOOL_RUNNER_VERSION: Final = "bounded-tool-runner/v1"
UNIVERSAL_BOUNDED_TOOL_LIFECYCLE_VERSION: Final = "universal-bounded-tool-lifecycle/v1"
WORKSPACE_PLACEHOLDER: Final = "{workspace}"
REDACTION: Final = "<redacted>"

# Runtime families that must share one injected lifecycle contract.
UNIVERSAL_TOOL_RUNTIMES: Final = frozenset(
    {
        "native",
        "jvm",
        "ocaml",
        "opam",
        "wasm",
        "kernel",
    }
)

_SENSITIVE_NAME = re.compile(
    r"(?:^|_)(?:api_?key|access_?key|authorization|credential|passwd|password|"
    r"private_?key|secret|session|token)(?:$|_)",
    re.IGNORECASE,
)
_SENSITIVE_OPTION = re.compile(
    r"^--?(?:api[-_]?key|access[-_]?key|authorization|credential|passwd|"
    r"password|private[-_]?key|secret|session|token)$",
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"^(--?(?:api[-_]?key|access[-_]?key|authorization|credential|passwd|"
    r"password|private[-_]?key|secret|session|token))=(.*)$",
    re.IGNORECASE,
)


class ToolProcessError(ValueError):
    """Raised when a process request violates the bounded-runner contract."""


class ToolRuntime(StrEnum):
    """Execution families supported by the shared lifecycle.

    ``KERNEL`` covers proof assistants (Lean, Isabelle, Rocq/Coq) that still
    run as ordinary host processes under the same isolation contract as
    ``NATIVE``.  Adapters may use either spelling; both share one runner.
    """

    NATIVE = "native"
    JVM = "jvm"
    OCAML = "ocaml"
    OPAM = "opam"
    WASM = "wasm"
    KERNEL = "kernel"


@dataclass(frozen=True, slots=True)
class ToolRunLimits:
    """Hard and capture bounds for a single tool invocation."""

    timeout_seconds: float = 30.0
    termination_grace_seconds: float = 0.25
    cpu_seconds: float | None = None
    memory_bytes: int | None = None
    max_output_bytes: int = 1_048_576
    max_input_bytes: int = 1_048_576
    max_workspace_bytes: int = 16_777_216
    max_output_files: int = 64
    max_path_bytes: int = 512
    max_arguments: int = 256
    max_argument_bytes: int = 65_536
    max_environment_bytes: int = 131_072
    enforce_file_size_limit: bool = True

    def __post_init__(self) -> None:
        for name in ("timeout_seconds", "termination_grace_seconds"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
            ):
                raise ToolProcessError(f"{name} must be a finite non-negative number")
        if self.timeout_seconds <= 0:
            raise ToolProcessError("timeout_seconds must be positive")
        if self.cpu_seconds is not None and (
            isinstance(self.cpu_seconds, bool)
            or not isinstance(self.cpu_seconds, (int, float))
            or not math.isfinite(float(self.cpu_seconds))
            or self.cpu_seconds <= 0
        ):
            raise ToolProcessError("cpu_seconds must be a finite positive number")
        for name in (
            "memory_bytes",
            "max_output_bytes",
            "max_input_bytes",
            "max_workspace_bytes",
            "max_output_files",
            "max_path_bytes",
            "max_arguments",
            "max_argument_bytes",
            "max_environment_bytes",
        ):
            value = getattr(self, name)
            if value is None and name == "memory_bytes":
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ToolProcessError(f"{name} must be a positive integer")
        if self.max_workspace_bytes < self.max_input_bytes:
            raise ToolProcessError(
                "max_workspace_bytes must be at least max_input_bytes"
            )
        if not isinstance(self.enforce_file_size_limit, bool):
            raise ToolProcessError(
                "enforce_file_size_limit must be a boolean"
            )


@dataclass(frozen=True, slots=True)
class ToolRunRequest:
    """One inert external-tool request.

    ``input_files`` and ``output_paths`` are relative POSIX paths inside the
    private workspace.  Use ``{workspace}`` in an argument when a tool needs
    the absolute workspace path (for example ``{workspace}/model.smt2``).
    """

    argv: tuple[str, ...]
    runtime: ToolRuntime = ToolRuntime.NATIVE
    limits: ToolRunLimits = field(default_factory=ToolRunLimits)
    stdin: bytes | str | None = field(default=None, repr=False)
    input_files: Mapping[str, bytes | str] = field(
        default_factory=dict, repr=False
    )
    output_paths: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict, repr=False)
    secrets: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.argv, (str, bytes, bytearray)):
            raise ToolProcessError("argv must be a sequence, never a shell string")
        object.__setattr__(self, "argv", tuple(self.argv))
        try:
            runtime = (
                self.runtime
                if isinstance(self.runtime, ToolRuntime)
                else ToolRuntime(self.runtime)
            )
        except (TypeError, ValueError) as error:
            raise ToolProcessError(f"unsupported tool runtime: {self.runtime!r}") from error
        object.__setattr__(self, "runtime", runtime)
        if not isinstance(self.limits, ToolRunLimits):
            raise ToolProcessError("limits must be ToolRunLimits")
        if not isinstance(self.input_files, Mapping):
            raise ToolProcessError("input_files must be a mapping")
        if not isinstance(self.environment, Mapping):
            raise ToolProcessError("environment must be a mapping")
        object.__setattr__(
            self, "input_files", MappingProxyType(dict(self.input_files))
        )
        object.__setattr__(
            self, "environment", MappingProxyType(dict(self.environment))
        )
        object.__setattr__(self, "output_paths", tuple(self.output_paths))
        object.__setattr__(self, "secrets", tuple(self.secrets))


@dataclass(frozen=True, slots=True)
class ProcessInvocation:
    """Validated invocation passed to an injected executor."""

    argv: tuple[str, ...]
    runtime: ToolRuntime
    cwd: Path
    environment: Mapping[str, str]
    stdin: bytes | None
    limits: ToolRunLimits


@dataclass(frozen=True, slots=True)
class RawProcessResult:
    """Executor-level result before redaction and declared-output collection."""

    returncode: int | None
    stdout: bytes | str = b""
    stderr: bytes | str = b""
    elapsed_seconds: float = 0.0
    pid: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    output_truncated: bool = False
    process_tree_terminated: bool = False
    resource_exhausted: bool = False
    error: str = ""


@dataclass(frozen=True, slots=True)
class ToolProbe:
    """Side-effect-free executable discovery result."""

    runtime: ToolRuntime
    requested_executable: str
    available: bool
    executable_path: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ToolRunResult:
    """Sanitized result of a complete bounded lifecycle."""

    interface_version: str
    runtime: ToolRuntime
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_seconds: float
    output_files: Mapping[str, bytes]
    pid: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    unavailable: bool = False
    output_truncated: bool = False
    workspace_limit_exceeded: bool = False
    process_tree_terminated: bool = False
    resource_exhausted: bool = False
    workspace_cleaned: bool = True
    termination_reason: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return (
            self.returncode == 0
            and not self.timed_out
            and not self.cancelled
            and not self.unavailable
            and not self.resource_exhausted
        )

    @property
    def outputs(self) -> Mapping[str, bytes]:
        """Compatibility spelling for callers that prefer ``outputs``."""

        return self.output_files

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface_version": self.interface_version,
            "runtime": self.runtime.value,
            "command": list(self.command),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "elapsed_seconds": self.elapsed_seconds,
            "output_files": {
                path: content.decode("utf-8", errors="replace")
                for path, content in self.output_files.items()
            },
            "pid": self.pid,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "unavailable": self.unavailable,
            "output_truncated": self.output_truncated,
            "workspace_limit_exceeded": self.workspace_limit_exceeded,
            "process_tree_terminated": self.process_tree_terminated,
            "resource_exhausted": self.resource_exhausted,
            "workspace_cleaned": self.workspace_cleaned,
            "termination_reason": self.termination_reason,
            "error": self.error,
        }


class CancellationSignal(Protocol):
    """Structural cancellation contract accepted by the runner."""

    def is_cancelled(self) -> bool: ...


class CancellationToken:
    """Small thread-safe cancellation token for direct users of this module."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)


class ProcessExecutor(Protocol):
    """Injection point used by deterministic fake and production executors."""

    def execute(
        self,
        invocation: ProcessInvocation,
        cancellation: CancellationSignal | Any | None = None,
    ) -> RawProcessResult: ...


class UniversalBoundedToolLifecycle(Protocol):
    """``UniversalBoundedToolLifecycle@1`` structural surface.

    Every external tool adapter (SMT/differential, ATP, protocol, kernel,
    TLA/JVM, hyperproperties, OCaml/opam, WASM probes) must route execution
    through an object that satisfies this contract rather than calling
    ``subprocess`` directly.
    """

    interface_version: str

    def probe(
        self,
        executable: str,
        *,
        runtime: ToolRuntime = ToolRuntime.NATIVE,
        search_path: str | None = None,
    ) -> ToolProbe: ...

    def is_available(
        self,
        executable: str,
        *,
        runtime: ToolRuntime = ToolRuntime.NATIVE,
        search_path: str | None = None,
    ) -> bool: ...

    def run(
        self,
        request: ToolRunRequest | Sequence[str],
        *,
        cancellation: CancellationSignal | Any | None = None,
        runtime: ToolRuntime = ToolRuntime.NATIVE,
        limits: ToolRunLimits | None = None,
        stdin: bytes | str | None = None,
        input_files: Mapping[str, bytes | str] | None = None,
        output_paths: Sequence[str] = (),
        environment: Mapping[str, str] | None = None,
        secrets: Sequence[str] = (),
    ) -> ToolRunResult: ...


def _is_cancelled(cancellation: Any | None) -> bool:
    if cancellation is None:
        return False
    for name in ("is_cancelled", "is_set"):
        method = getattr(cancellation, name, None)
        if callable(method):
            return bool(method())
    return bool(getattr(cancellation, "cancelled", False))


def _resource_preexec(limits: ToolRunLimits) -> Callable[[], None] | None:
    if os.name != "posix":
        return None

    def apply_limits() -> None:
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if limits.enforce_file_size_limit:
            file_limit = limits.max_workspace_bytes
            resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
        if limits.cpu_seconds is not None:
            cpu_limit = max(1, int(math.ceil(limits.cpu_seconds)))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))
        if limits.memory_bytes is not None:
            resource.setrlimit(
                resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes)
            )

    return apply_limits


def _terminate_process_tree(
    process: subprocess.Popen[bytes],
    *,
    grace_seconds: float,
) -> bool:
    """Terminate the process and descendants without searching by name."""

    if process.poll() is not None:
        return False
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return False
        except PermissionError:
            process.terminate()
    else:  # pragma: no cover - exercised on Windows CI.
        process.terminate()
    try:
        process.wait(timeout=max(0.001, grace_seconds))
        return True
    except subprocess.TimeoutExpired:
        pass
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            process.kill()
    else:  # pragma: no cover - exercised on Windows CI.
        process.kill()
    try:
        process.wait(timeout=max(0.1, grace_seconds))
    except subprocess.TimeoutExpired:  # pragma: no cover - hostile OS boundary.
        return False
    return True


def _living_group_descendants(group_id: int, leader_pid: int) -> bool:
    """Return whether Linux exposes a live descendant in the process group."""

    if os.name != "posix" or not Path("/proc").is_dir():
        return False
    try:
        entries = tuple(Path("/proc").iterdir())
    except OSError:
        return False
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == leader_pid:
            continue
        try:
            raw = (entry / "stat").read_text(encoding="utf-8")
            closing = raw.rfind(")")
            fields = raw[closing + 2 :].split()
            state = fields[0]
            process_group_id = int(fields[2])
        except (OSError, IndexError, ValueError):
            continue
        if process_group_id == group_id and state != "Z":
            return True
    return False


def _terminate_remaining_group(group_id: int, grace_seconds: float) -> bool:
    """Reap descendants after their group leader has already exited."""

    if os.name != "posix":
        return False
    try:
        os.killpg(group_id, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not _living_group_descendants(group_id, group_id):
            return True
        time.sleep(0.01)
    try:
        os.killpg(group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        return False
    return True


class _BoundedCapture:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._value = bytearray()
        self.truncated = False

    def drain(self, stream: Any) -> None:
        try:
            while True:
                chunk = stream.read(65_536)
                if not chunk:
                    return
                remaining = self._limit - len(self._value)
                if remaining > 0:
                    self._value.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.truncated = True
        finally:
            try:
                stream.close()
            except OSError:
                pass

    @property
    def value(self) -> bytes:
        return bytes(self._value)


class SubprocessExecutor:
    """Production executor using a new process group and bounded pipe drains."""

    def __init__(
        self,
        *,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
        poll_interval_seconds: float = 0.01,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ToolProcessError("poll_interval_seconds must be positive")
        self._popen = popen
        self._clock = clock
        self._poll_interval_seconds = poll_interval_seconds

    def execute(
        self,
        invocation: ProcessInvocation,
        cancellation: CancellationSignal | Any | None = None,
    ) -> RawProcessResult:
        started = self._clock()
        if _is_cancelled(cancellation):
            return RawProcessResult(
                returncode=None,
                elapsed_seconds=0.0,
                cancelled=True,
                error="cancelled before process start",
            )

        creation_flags = 0
        if os.name == "nt":  # pragma: no cover - exercised on Windows CI.
            creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        process = self._popen(
            list(invocation.argv),
            cwd=str(invocation.cwd),
            env=dict(invocation.environment),
            stdin=(
                subprocess.PIPE
                if invocation.stdin is not None
                else subprocess.DEVNULL
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=(os.name == "posix"),
            creationflags=creation_flags,
            preexec_fn=_resource_preexec(invocation.limits),
        )
        assert process.stdout is not None
        assert process.stderr is not None
        stdout = _BoundedCapture(invocation.limits.max_output_bytes)
        stderr = _BoundedCapture(invocation.limits.max_output_bytes)
        readers = (
            threading.Thread(target=stdout.drain, args=(process.stdout,), daemon=True),
            threading.Thread(target=stderr.drain, args=(process.stderr,), daemon=True),
        )
        for reader in readers:
            reader.start()

        if invocation.stdin is not None:
            assert process.stdin is not None

            def write_stdin() -> None:
                try:
                    process.stdin.write(invocation.stdin or b"")
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass

            threading.Thread(target=write_stdin, daemon=True).start()

        deadline = started + invocation.limits.timeout_seconds
        timed_out = False
        cancelled = False
        tree_terminated = False
        while process.poll() is None:
            if _is_cancelled(cancellation):
                cancelled = True
                tree_terminated = _terminate_process_tree(
                    process,
                    grace_seconds=invocation.limits.termination_grace_seconds,
                )
                break
            if self._clock() >= deadline:
                timed_out = True
                tree_terminated = _terminate_process_tree(
                    process,
                    grace_seconds=invocation.limits.termination_grace_seconds,
                )
                break
            time.sleep(self._poll_interval_seconds)

        try:
            returncode = process.wait(
                timeout=max(0.1, invocation.limits.termination_grace_seconds)
            )
        except subprocess.TimeoutExpired:  # pragma: no cover - hostile OS boundary.
            tree_terminated = _terminate_process_tree(
                process,
                grace_seconds=invocation.limits.termination_grace_seconds,
            )
            returncode = process.poll()

        if _living_group_descendants(process.pid, process.pid):
            tree_terminated = (
                _terminate_remaining_group(
                    process.pid, invocation.limits.termination_grace_seconds
                )
                or tree_terminated
            )
        for reader in readers:
            reader.join(timeout=max(0.1, invocation.limits.termination_grace_seconds))
        resource_exhausted = (
            not timed_out
            and not cancelled
            and returncode is not None
            and returncode < 0
            and (
                invocation.limits.cpu_seconds is not None
                or invocation.limits.memory_bytes is not None
            )
        )
        return RawProcessResult(
            returncode=returncode,
            stdout=stdout.value,
            stderr=stderr.value,
            elapsed_seconds=max(0.0, self._clock() - started),
            pid=process.pid,
            timed_out=timed_out,
            cancelled=cancelled,
            output_truncated=stdout.truncated or stderr.truncated,
            process_tree_terminated=tree_terminated,
            resource_exhausted=resource_exhausted,
        )


def _validate_workspace_path(path: str, limits: ToolRunLimits) -> PurePosixPath:
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ToolProcessError("workspace paths must be non-empty strings without NUL")
    if len(path.encode("utf-8")) > limits.max_path_bytes:
        raise ToolProcessError(f"workspace path exceeds {limits.max_path_bytes} bytes")
    if "\\" in path:
        raise ToolProcessError("workspace paths must use portable POSIX separators")
    value = PurePosixPath(path)
    if value.is_absolute() or value == PurePosixPath(".") or ".." in value.parts:
        raise ToolProcessError(
            f"workspace path must be relative and traversal-free: {path!r}"
        )
    return value


def _bytes(value: bytes | str, field_name: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise ToolProcessError(f"{field_name} must be bytes or text")


def _redact_text(value: str, secrets: Sequence[str]) -> str:
    result = value
    for secret in sorted(
        {secret for secret in secrets if isinstance(secret, str) and secret},
        key=len,
        reverse=True,
    ):
        result = result.replace(secret, REDACTION)
    return result


def _redact_command(argv: Sequence[str], secrets: Sequence[str]) -> tuple[str, ...]:
    redacted: list[str] = []
    redact_next = False
    for argument in argv:
        if redact_next:
            redacted.append(REDACTION)
            redact_next = False
            continue
        assignment = _SENSITIVE_ASSIGNMENT.match(argument)
        if assignment:
            redacted.append(f"{assignment.group(1)}={REDACTION}")
            continue
        redacted.append(_redact_text(argument, secrets))
        redact_next = bool(_SENSITIVE_OPTION.match(argument))
    return tuple(redacted)


def _workspace_size(root: Path, limit: int) -> tuple[int, bool]:
    total = 0
    for directory, names, filenames in os.walk(root, followlinks=False):
        for name in (*names, *filenames):
            path = Path(directory) / name
            try:
                info = path.lstat()
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > limit:
                    return total, True
    return total, False


def tool_limits_from_milliseconds(
    timeout_ms: int,
    *,
    max_output_bytes: int = 1_048_576,
    max_memory_bytes: int | None = None,
    max_input_bytes: int | None = None,
    max_workspace_bytes: int | None = None,
    cpu_seconds: float | None = None,
    termination_grace_seconds: float = 0.25,
) -> ToolRunLimits:
    """Map millisecond wall bounds (ExecutionBounds-style) onto ToolRunLimits."""

    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ToolProcessError("timeout_ms must be a positive integer")
    output_bound = max_output_bytes if max_output_bytes > 0 else 1_048_576
    input_bound = max_input_bytes if max_input_bytes is not None else output_bound
    workspace_bound = (
        max_workspace_bytes
        if max_workspace_bytes is not None
        else max(output_bound * 2, input_bound + output_bound + 1024)
    )
    return ToolRunLimits(
        timeout_seconds=max(timeout_ms / 1000.0, 0.001),
        termination_grace_seconds=termination_grace_seconds,
        cpu_seconds=(
            max(timeout_ms / 1000.0, 0.001) if cpu_seconds is None else cpu_seconds
        ),
        memory_bytes=max_memory_bytes,
        max_output_bytes=output_bound,
        max_input_bytes=input_bound,
        max_workspace_bytes=max(workspace_bound, input_bound),
    )


@dataclass(frozen=True, slots=True)
class BoundedStdinObservation:
    """Normalized observation for stdin-fed tools (SMT/differential style)."""

    stdout: str = ""
    stderr: str = ""
    returncode: int | None = 0
    elapsed_ms: int = 0
    timed_out: bool = False
    cancelled: bool = False
    unavailable: bool = False
    process_tree_terminated: bool = False
    output_truncated: bool = False
    workspace_cleaned: bool = True
    resource_exhausted: bool = False
    termination_reason: str = ""
    command: tuple[str, ...] = ()
    error: str = ""
    interface_version: str = UNIVERSAL_BOUNDED_TOOL_LIFECYCLE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface_version": self.interface_version,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "elapsed_ms": self.elapsed_ms,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "unavailable": self.unavailable,
            "process_tree_terminated": self.process_tree_terminated,
            "output_truncated": self.output_truncated,
            "workspace_cleaned": self.workspace_cleaned,
            "resource_exhausted": self.resource_exhausted,
            "termination_reason": self.termination_reason,
            "command": list(self.command),
            "error": self.error,
        }


def run_bounded_stdin_tool(
    argv: Sequence[str],
    stdin: bytes | str,
    *,
    runner: BoundedToolRunner | UniversalBoundedToolLifecycle | None = None,
    runtime: ToolRuntime = ToolRuntime.NATIVE,
    limits: ToolRunLimits | None = None,
    cancellation: CancellationSignal | Any | None = None,
    environment: Mapping[str, str] | None = None,
    secrets: Sequence[str] = (),
    timeout_ms: int | None = None,
    max_output_bytes: int | None = None,
    max_memory_bytes: int | None = None,
) -> BoundedStdinObservation:
    """Run an argv+stdin tool through the universal bounded lifecycle.

    Preferred replacement for direct ``subprocess.run`` in SMT, differential,
    and version-probe paths that feed a script on standard input.
    """

    if isinstance(argv, (str, bytes, bytearray)):
        raise ToolProcessError("argv must be a sequence, never a shell string")
    resolved_limits = limits
    if resolved_limits is None:
        resolved_limits = tool_limits_from_milliseconds(
            timeout_ms if timeout_ms is not None else 30_000,
            max_output_bytes=(
                max_output_bytes if max_output_bytes is not None else 1_048_576
            ),
            max_memory_bytes=max_memory_bytes,
            max_input_bytes=len(_bytes(stdin, "stdin")) + 1,
        )
    active_runner: BoundedToolRunner | UniversalBoundedToolLifecycle
    if runner is None:
        active_runner = BoundedToolRunner()
    else:
        active_runner = runner
    request = ToolRunRequest(
        argv=tuple(argv),
        runtime=runtime,
        limits=resolved_limits,
        stdin=stdin,
        environment=environment or {},
        secrets=tuple(secrets),
    )
    result = active_runner.run(request, cancellation=cancellation)
    return BoundedStdinObservation(
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
        elapsed_ms=max(0, int(result.elapsed_seconds * 1000)),
        timed_out=result.timed_out,
        cancelled=result.cancelled,
        unavailable=result.unavailable,
        process_tree_terminated=result.process_tree_terminated,
        output_truncated=result.output_truncated,
        workspace_cleaned=result.workspace_cleaned,
        resource_exhausted=result.resource_exhausted,
        termination_reason=result.termination_reason,
        command=result.command,
        error=result.error,
    )


class BoundedToolRunner:
    """Reusable ``BoundedToolRunner@1`` / ``UniversalBoundedToolLifecycle@1``.

    An injected executor is trusted only to execute the validated invocation.
    The runner still owns workspace materialization, declared-output reads,
    redaction, and cleanup, so fake and real runs observe the same contract.
    """

    interface_version: Final = BOUNDED_TOOL_RUNNER_VERSION
    lifecycle_version: Final = UNIVERSAL_BOUNDED_TOOL_LIFECYCLE_VERSION

    def __init__(
        self,
        *,
        executor: ProcessExecutor
        | Callable[[ProcessInvocation, Any | None], RawProcessResult]
        | None = None,
        workspace_root: str | Path | None = None,
        base_environment: Mapping[str, str] | None = None,
        executable_roots: Sequence[str | Path] = (),
    ) -> None:
        self._default_executor = executor is None
        self._executor = executor or SubprocessExecutor()
        self._workspace_root = (
            Path(workspace_root).expanduser() if workspace_root is not None else None
        )
        default_environment = {
            name: value
            for name, value in os.environ.items()
            if name in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR"}
        }
        self._base_environment = dict(
            default_environment if base_environment is None else base_environment
        )
        self._executable_roots = tuple(
            Path(root).expanduser().resolve() for root in executable_roots
        )

    def probe(
        self,
        executable: str,
        *,
        runtime: ToolRuntime = ToolRuntime.NATIVE,
        search_path: str | None = None,
    ) -> ToolProbe:
        """Inspect executable availability without starting or installing it."""

        if not isinstance(executable, str) or not executable or "\x00" in executable:
            raise ToolProcessError("executable must be a non-empty string without NUL")
        try:
            resolved_runtime = (
                runtime if isinstance(runtime, ToolRuntime) else ToolRuntime(runtime)
            )
        except (TypeError, ValueError) as error:
            raise ToolProcessError(f"unsupported tool runtime: {runtime!r}") from error
        candidate = shutil.which(
            executable, path=search_path or self._base_environment.get("PATH")
        )
        if candidate is None:
            return ToolProbe(
                runtime=resolved_runtime,
                requested_executable=executable,
                available=False,
                reason="executable not found",
            )
        resolved = Path(candidate).resolve()
        if self._executable_roots and not any(
            resolved == root or root in resolved.parents
            for root in self._executable_roots
        ):
            return ToolProbe(
                runtime=resolved_runtime,
                requested_executable=executable,
                available=False,
                reason="executable is outside the allowed roots",
            )
        return ToolProbe(
            runtime=resolved_runtime,
            requested_executable=executable,
            available=True,
            executable_path=str(resolved),
        )

    def is_available(
        self,
        executable: str,
        *,
        runtime: ToolRuntime = ToolRuntime.NATIVE,
        search_path: str | None = None,
    ) -> bool:
        return self.probe(
            executable, runtime=runtime, search_path=search_path
        ).available

    def run(
        self,
        request: ToolRunRequest | Sequence[str],
        *,
        cancellation: CancellationSignal | Any | None = None,
        runtime: ToolRuntime = ToolRuntime.NATIVE,
        limits: ToolRunLimits | None = None,
        stdin: bytes | str | None = None,
        input_files: Mapping[str, bytes | str] | None = None,
        output_paths: Sequence[str] = (),
        environment: Mapping[str, str] | None = None,
        secrets: Sequence[str] = (),
    ) -> ToolRunResult:
        """Run one request and return a sanitized, non-raising operational result."""

        if not isinstance(request, ToolRunRequest):
            request = ToolRunRequest(
                argv=tuple(request),
                runtime=runtime,
                limits=limits or ToolRunLimits(),
                stdin=stdin,
                input_files=input_files or {},
                output_paths=tuple(output_paths),
                environment=environment or {},
                secrets=tuple(secrets),
            )
        self._validate_request(request)
        secret_values = self._secret_values(request)
        redacted_command = _redact_command(request.argv, secret_values)
        if _is_cancelled(cancellation):
            return self._result(
                request,
                command=redacted_command,
                raw=RawProcessResult(
                    returncode=None,
                    cancelled=True,
                    error="cancelled before process start",
                ),
                outputs={},
                secrets=secret_values,
                workspace_cleaned=True,
            )

        resolved_argv = request.argv
        if self._default_executor or self._executable_roots:
            probe = self.probe(
                request.argv[0],
                runtime=request.runtime,
                search_path=self._base_environment.get("PATH"),
            )
            if not probe.available:
                return self._result(
                    request,
                    command=redacted_command,
                    raw=RawProcessResult(
                        returncode=None,
                        error=probe.reason,
                    ),
                    outputs={},
                    secrets=secret_values,
                    workspace_cleaned=True,
                    unavailable=True,
                )
            resolved_argv = (probe.executable_path, *request.argv[1:])

        workspace_root = self._workspace_root
        if workspace_root is not None:
            workspace_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(
            prefix="logic-tool-",
            dir=str(workspace_root) if workspace_root is not None else None,
        )
        workspace = Path(temporary.name).resolve()
        try:
            try:
                os.chmod(workspace, 0o700)
            except OSError:  # pragma: no cover - permissions differ on Windows.
                pass
            self._write_inputs(workspace, request)
            expanded_argv = tuple(
                self._expand_workspace_argument(argument, workspace, request.limits)
                for argument in resolved_argv
            )
            invocation = ProcessInvocation(
                argv=expanded_argv,
                runtime=request.runtime,
                cwd=workspace,
                environment=MappingProxyType(
                    self._environment(request.environment, workspace, request.limits)
                ),
                stdin=(
                    None
                    if request.stdin is None
                    else _bytes(request.stdin, "stdin")
                ),
                limits=request.limits,
            )
            try:
                raw = self._execute(invocation, cancellation)
            except OSError as error:
                raw = RawProcessResult(returncode=None, error=str(error))
            except Exception as error:
                raw = RawProcessResult(
                    returncode=None,
                    error=f"executor failure: {type(error).__name__}: {error}",
                )
            outputs, files_truncated = self._read_outputs(workspace, request)
            _, workspace_exceeded = _workspace_size(
                workspace, request.limits.max_workspace_bytes
            )
            if files_truncated or workspace_exceeded:
                raw = replace(
                    raw,
                    output_truncated=raw.output_truncated or files_truncated,
                    resource_exhausted=raw.resource_exhausted or workspace_exceeded,
                )
            result = self._result(
                request,
                command=redacted_command,
                raw=raw,
                outputs=outputs,
                secrets=secret_values,
                workspace_cleaned=True,
                workspace_limit_exceeded=workspace_exceeded,
            )
        finally:
            temporary.cleanup()
        return result

    def _execute(
        self, invocation: ProcessInvocation, cancellation: Any | None
    ) -> RawProcessResult:
        execute = getattr(self._executor, "execute", None)
        raw = (
            execute(invocation, cancellation)
            if callable(execute)
            else self._executor(invocation, cancellation)  # type: ignore[operator]
        )
        if not isinstance(raw, RawProcessResult):
            raise TypeError("executor must return RawProcessResult")
        return raw

    @staticmethod
    def _validate_request(request: ToolRunRequest) -> None:
        limits = request.limits
        if not request.argv or len(request.argv) > limits.max_arguments:
            raise ToolProcessError(
                f"argv must contain 1..{limits.max_arguments} arguments"
            )
        argument_bytes = 0
        for argument in request.argv:
            if (
                not isinstance(argument, str)
                or not argument
                or "\x00" in argument
            ):
                raise ToolProcessError(
                    "argv entries must be non-empty strings without NUL"
                )
            argument_bytes += len(argument.encode("utf-8"))
        if argument_bytes > limits.max_argument_bytes:
            raise ToolProcessError(
                f"argv exceeds {limits.max_argument_bytes} encoded bytes"
            )
        if request.stdin is not None and len(_bytes(request.stdin, "stdin")) > limits.max_input_bytes:
            raise ToolProcessError("stdin exceeds max_input_bytes")
        if len(request.output_paths) > limits.max_output_files:
            raise ToolProcessError("too many declared output paths")
        paths = [
            _validate_workspace_path(path, limits)
            for path in request.output_paths
        ]
        if len(paths) != len(set(paths)):
            raise ToolProcessError("declared output paths must be unique")
        input_total = 0
        normalized_inputs: set[PurePosixPath] = set()
        for path, content in request.input_files.items():
            normalized = _validate_workspace_path(path, limits)
            if normalized in normalized_inputs:
                raise ToolProcessError("input paths must be unique")
            normalized_inputs.add(normalized)
            input_total += len(_bytes(content, f"input file {path!r}"))
        if input_total > limits.max_input_bytes:
            raise ToolProcessError("input files exceed max_input_bytes")
        if (
            request.stdin is not None
            and input_total + len(_bytes(request.stdin, "stdin"))
            > limits.max_input_bytes
        ):
            raise ToolProcessError("combined stdin and input files exceed max_input_bytes")
        for name, value in request.environment.items():
            if (
                not isinstance(name, str)
                or not name
                or "=" in name
                or "\x00" in name
                or not isinstance(value, str)
                or "\x00" in value
            ):
                raise ToolProcessError(
                    "environment keys and values must be valid NUL-free strings"
                )
        for secret in request.secrets:
            if not isinstance(secret, str) or not secret:
                raise ToolProcessError("secrets must be non-empty strings")

    @staticmethod
    def _write_inputs(workspace: Path, request: ToolRunRequest) -> None:
        for relative, content in request.input_files.items():
            path = workspace.joinpath(*_validate_workspace_path(relative, request.limits).parts)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                path.write_bytes(_bytes(content, f"input file {relative!r}"))
            except OSError as error:
                raise ToolProcessError(
                    f"could not materialize input file {relative!r}: {error}"
                ) from error

    @staticmethod
    def _expand_workspace_argument(
        argument: str, workspace: Path, limits: ToolRunLimits
    ) -> str:
        if WORKSPACE_PLACEHOLDER not in argument:
            return argument
        if argument == WORKSPACE_PLACEHOLDER:
            return str(workspace)
        prefix = f"{WORKSPACE_PLACEHOLDER}/"
        if not argument.startswith(prefix):
            raise ToolProcessError(
                "{workspace} may only be an argument or an argument prefix"
            )
        relative = _validate_workspace_path(argument[len(prefix) :], limits)
        return str(workspace.joinpath(*relative.parts))

    def _environment(
        self,
        requested: Mapping[str, str],
        workspace: Path,
        limits: ToolRunLimits,
    ) -> dict[str, str]:
        environment = dict(self._base_environment)
        environment.update(requested)
        isolated = str(workspace)
        environment.update(
            {
                "HOME": isolated,
                "TMPDIR": isolated,
                "TMP": isolated,
                "TEMP": isolated,
            }
        )
        size = sum(
            len(name.encode("utf-8")) + len(value.encode("utf-8")) + 2
            for name, value in environment.items()
        )
        if size > limits.max_environment_bytes:
            raise ToolProcessError("environment exceeds max_environment_bytes")
        return environment

    @staticmethod
    def _secret_values(request: ToolRunRequest) -> tuple[str, ...]:
        values = set(request.secrets)
        values.update(
            value
            for name, value in request.environment.items()
            if value and _SENSITIVE_NAME.search(name)
        )
        return tuple(sorted(values, key=len, reverse=True))

    @staticmethod
    def _read_outputs(
        workspace: Path, request: ToolRunRequest
    ) -> tuple[dict[str, bytes], bool]:
        outputs: dict[str, bytes] = {}
        truncated = False
        for relative in request.output_paths:
            path = workspace.joinpath(
                *_validate_workspace_path(relative, request.limits).parts
            )
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode) or path.is_symlink():
                continue
            with path.open("rb") as handle:
                content = handle.read(request.limits.max_output_bytes + 1)
            if len(content) > request.limits.max_output_bytes:
                content = content[: request.limits.max_output_bytes]
                truncated = True
            outputs[relative] = content
        return outputs, truncated

    @staticmethod
    def _result(
        request: ToolRunRequest,
        *,
        command: tuple[str, ...],
        raw: RawProcessResult,
        outputs: Mapping[str, bytes],
        secrets: Sequence[str],
        workspace_cleaned: bool,
        unavailable: bool = False,
        workspace_limit_exceeded: bool = False,
    ) -> ToolRunResult:
        stdout, stdout_truncated = _bounded_redacted_text(
            raw.stdout, secrets, request.limits.max_output_bytes
        )
        stderr, stderr_truncated = _bounded_redacted_text(
            raw.stderr, secrets, request.limits.max_output_bytes
        )
        error, error_truncated = _bounded_redacted_text(
            raw.error, secrets, request.limits.max_output_bytes
        )
        sanitized_outputs: dict[str, bytes] = {}
        file_redaction_truncated = False
        for path, content in outputs.items():
            sanitized = _redact_output_bytes(content, secrets)
            if len(sanitized) > request.limits.max_output_bytes:
                sanitized = sanitized[: request.limits.max_output_bytes]
                file_redaction_truncated = True
            sanitized_outputs[path] = sanitized
        if raw.cancelled:
            reason = "cancelled"
        elif raw.timed_out:
            reason = "timeout"
        elif workspace_limit_exceeded or raw.resource_exhausted:
            reason = "resource_limit"
        elif unavailable:
            reason = "unavailable"
        elif raw.returncode not in (0, None):
            reason = "nonzero_exit"
        elif raw.error:
            reason = "error"
        else:
            reason = "completed"
        return ToolRunResult(
            interface_version=BOUNDED_TOOL_RUNNER_VERSION,
            runtime=request.runtime,
            command=command,
            returncode=raw.returncode,
            stdout=stdout,
            stderr=stderr,
            elapsed_seconds=max(0.0, float(raw.elapsed_seconds)),
            output_files=MappingProxyType(sanitized_outputs),
            pid=raw.pid,
            timed_out=raw.timed_out,
            cancelled=raw.cancelled,
            unavailable=unavailable,
            output_truncated=(
                raw.output_truncated
                or stdout_truncated
                or stderr_truncated
                or error_truncated
                or file_redaction_truncated
            ),
            workspace_limit_exceeded=workspace_limit_exceeded,
            process_tree_terminated=raw.process_tree_terminated,
            resource_exhausted=raw.resource_exhausted,
            workspace_cleaned=workspace_cleaned,
            termination_reason=reason,
            error=error,
        )


def _bounded_redacted_text(
    value: bytes | str,
    secrets: Sequence[str],
    limit: int,
) -> tuple[str, bool]:
    encoded = value if isinstance(value, bytes) else str(value).encode("utf-8")
    truncated = len(encoded) > limit
    text = encoded[:limit].decode("utf-8", errors="replace")
    redacted = _redact_text(text, secrets)
    redacted_bytes = redacted.encode("utf-8")
    if len(redacted_bytes) > limit:
        truncated = True
        redacted = redacted_bytes[:limit].decode("utf-8", errors="replace")
    return redacted, truncated


def _redact_output_bytes(content: bytes, secrets: Sequence[str]) -> bytes:
    result = content
    for secret in sorted(
        {secret for secret in secrets if isinstance(secret, str) and secret},
        key=len,
        reverse=True,
    ):
        result = result.replace(secret.encode("utf-8"), REDACTION.encode("utf-8"))
    return result


# Stable descriptive aliases used by adapters with command-oriented naming.
ProcessLimits = ToolRunLimits
CommandRequest = ToolRunRequest
CommandResult = ToolRunResult
NativeProcessExecutor = SubprocessExecutor


__all__ = [
    "BOUNDED_TOOL_RUNNER_VERSION",
    "UNIVERSAL_BOUNDED_TOOL_LIFECYCLE_VERSION",
    "UNIVERSAL_TOOL_RUNTIMES",
    "WORKSPACE_PLACEHOLDER",
    "BoundedStdinObservation",
    "BoundedToolRunner",
    "CancellationSignal",
    "CancellationToken",
    "CommandRequest",
    "CommandResult",
    "NativeProcessExecutor",
    "ProcessExecutor",
    "ProcessInvocation",
    "ProcessLimits",
    "RawProcessResult",
    "SubprocessExecutor",
    "ToolProbe",
    "ToolProcessError",
    "ToolRunLimits",
    "ToolRunRequest",
    "ToolRunResult",
    "ToolRuntime",
    "UniversalBoundedToolLifecycle",
    "run_bounded_stdin_tool",
    "tool_limits_from_milliseconds",
]
