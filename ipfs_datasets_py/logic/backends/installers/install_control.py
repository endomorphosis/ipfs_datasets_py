"""Finite installation work and resource-admitted build/probe subprocesses.

Construction and configuration do not inspect the host. Native work acquires
real scheduler capacity and uses the bounded process lifecycle in the actual
build directory. Admission is an estimate; sampled RSS/disk guards can overshoot.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
import math
import os
from pathlib import Path
import shutil
import tempfile

from ..smt.operation_budget import (
    MAX_OPERATION_TIMEOUT_MS, current_proof_operation, proof_operation_scope,
    validate_operation_timeout_ms,
)


@dataclass(frozen=True)
class HyperInstallLimits:
    operation_timeout_ms: int = 1_800_000
    max_download_bytes: int = 256 * 1024**2
    max_extract_bytes: int = 1024**3
    max_member_bytes: int = 256 * 1024**2
    max_archive_members: int = 32_768
    max_archive_depth: int = 32
    max_path_bytes: int = 1024
    io_timeout_seconds: float = 5.0
    build_memory_bytes: int = 1024**3
    build_address_space_bytes: int = 8 * 1024**3
    build_output_bytes: int = 1024**2
    build_workspace_bytes: int = 2 * 1024**3
    build_cpu_slots: int = 1
    build_process_slots: int = 4

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if name == "io_timeout_seconds":
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                    raise ValueError("io_timeout_seconds must be finite and positive")
            elif type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        validate_operation_timeout_ms(self.operation_timeout_ms)
        if self.build_address_space_bytes < self.build_memory_bytes:
            raise ValueError("build address space must cover the declared resident memory")


class InstallControlError(RuntimeError):
    """Installation cannot obtain or retain its declared resource envelope."""


@dataclass(frozen=True)
class _Control:
    limits: HyperInstallLimits
    scheduler: object | None = None
    parent_lease: object | None = None


_CONTROL = ContextVar("hyper_install_control", default=None)


def current_install_limits() -> HyperInstallLimits:
    control = _CONTROL.get()
    return control.limits if control is not None else HyperInstallLimits()


def installation_checkpoint(phase="installation boundary") -> float:
    operation = current_proof_operation()
    if operation is None:
        raise InstallControlError("installation work requires an operation scope")
    return operation.checkpoint(phase)


@contextmanager
def installation_scope(*, limits=None, operation_timeout_ms=None, cancellation=None,
                       scheduler=None, parent_lease=None):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        GlobalResourceScheduler, ResourceLease,
    )
    previous = _CONTROL.get()
    if limits is None:
        limits = previous.limits if previous is not None else HyperInstallLimits()
    if not isinstance(limits, HyperInstallLimits):
        raise TypeError("limits must be HyperInstallLimits")
    if scheduler is not None and parent_lease is not None:
        raise ValueError("supply only scheduler or parent_lease")
    if scheduler is not None and not isinstance(scheduler, GlobalResourceScheduler):
        raise TypeError("scheduler must be an actual GlobalResourceScheduler")
    if parent_lease is not None and not isinstance(parent_lease, ResourceLease):
        raise TypeError("parent_lease must be an actual ResourceLease")
    if scheduler is None and parent_lease is None and previous is not None:
        scheduler, parent_lease = previous.scheduler, previous.parent_lease
    validate_operation_timeout_ms(operation_timeout_ms)
    timeout = min(limits.operation_timeout_ms,
                  operation_timeout_ms if operation_timeout_ms is not None else MAX_OPERATION_TIMEOUT_MS)
    token = _CONTROL.set(_Control(limits, scheduler, parent_lease))
    try:
        with proof_operation_scope(timeout_ms=timeout, cancellation=cancellation) as operation:
            yield operation
    finally:
        _CONTROL.reset(token)


def run_install_command(argv, *, cwd=None, environment=None, timeout_seconds=1800,
                        inherit_environment=True):
    """Run a bounded command, keeping its lease through descendant cleanup.

    An explicit build directory is scanned by the process guard and remains
    owned by the enclosing install transaction. A probe gets a disposable
    directory. Neither path redirects scans away from the actual command cwd.
    Set ``inherit_environment=False`` for an explicit environment without host
    loader/SDK overrides. Disposable dotnet probes keep first-use and package
    caches in their guarded workspace, including when the host sets cache paths.
    """
    from ..process import ProcessInvocation, SubprocessExecutor, ToolRunLimits, ToolRuntime
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        get_global_resource_scheduler, ResourceSchedulerError,
    )
    if type(inherit_environment) is not bool:
        raise ValueError("inherit_environment must be a bool")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if isinstance(argv, (str, bytes)) or not argv:
        raise ValueError("argv must be a nonempty argument sequence")
    arguments = tuple(str(value) for value in argv)
    if len(arguments) > 256 or any(not value or "\x00" in value for value in arguments):
        raise ValueError("invalid install command arguments")
    if sum(len(value.encode("utf-8")) for value in arguments) > 65_536:
        raise ValueError("install command arguments exceed limit")
    with installation_scope(operation_timeout_ms=max(1, min(MAX_OPERATION_TIMEOUT_MS, math.ceil(timeout_seconds * 1000)))) as operation:
        control = _CONTROL.get()
        bounds, parent = control.limits, control.parent_lease
        env = os.environ.copy() if inherit_environment else {}
        if environment:
            env.update(environment)
        if any(not isinstance(key, str) or not isinstance(value, str) or "\x00" in key + value
               or "=" in key for key, value in env.items()):
            raise ValueError("invalid installer command environment")
        env.pop("GHCRTS", None)
        for name in tuple(env):
            if name.startswith(("DOTNET_GC", "COMPlus_GC", "DOTNET_gc", "COMPlus_gc")):
                del env[name]
        # Compiler/build-system defaults must not spend every host core.
        env.update(MAKEFLAGS=f"-j{bounds.build_cpu_slots}",
            CMAKE_BUILD_PARALLEL_LEVEL=str(bounds.build_cpu_slots),
            DOTNET_PROCESSOR_COUNT=str(bounds.build_cpu_slots), DOTNET_gcServer="0",
            DOTNET_GCHeapHardLimit=format(max(1, bounds.build_memory_bytes // 2), "x"),
            OMP_NUM_THREADS=str(bounds.build_cpu_slots), OPENBLAS_NUM_THREADS=str(bounds.build_cpu_slots))
        if sum(len(key.encode()) + len(value.encode()) + 2 for key, value in env.items()) > 131_072:
            raise ValueError("installer environment exceeds limit")

        installation_checkpoint("before installer scheduler resolution")
        if parent is not None:
            if parent.owner_pid != os.getpid() or parent.released or parent.cancelled:
                raise InstallControlError("inactive or foreign installer parent lease")
            owner = parent._scheduler
        else:
            owner = control.scheduler or get_global_resource_scheduler()
        remaining = installation_checkpoint("before installer resource admission")
        try:
            lease = owner.acquire("validation", cpu_slots=bounds.build_cpu_slots,
                memory_mb=(bounds.build_memory_bytes + 1024**2 - 1) // 1024**2,
                child_process_slots=bounds.build_process_slots, parent_lease=parent,
                timeout=remaining, cancel_event=operation, request_id="hyper-installer-command")
        except ResourceSchedulerError as error:
            installation_checkpoint("installer resource admission failure")
            raise InstallControlError("installer resource admission refused") from error
        with lease:
            signal = lease.combined_cancellation_signal(operation)
            installation_checkpoint("after installer resource admission")
            if signal.is_set():
                raise InstallControlError("installer resource lease revoked")
            executable = shutil.which(arguments[0], path=env.get("PATH", os.defpath))
            if executable is None:
                raise InstallControlError("installer command executable unavailable")
            arguments = (str(Path(executable).resolve()), *arguments[1:])

            def execute(directory):
                remaining = installation_checkpoint("before installer command")
                if cwd is None and Path(arguments[0]).name.startswith("dotnet"):
                    # Probe work may create SDK first-use files even for a
                    # version query. Never charge a disposable probe directory
                    # while allowing those files into the user's home/cache.
                    scratch = directory / ".dotnet-probe"
                    scratch.mkdir()
                    home, temporary = scratch / "home", scratch / "tmp"
                    home.mkdir()
                    temporary.mkdir()
                    env.update(HOME=str(home), USERPROFILE=str(home),
                        DOTNET_CLI_HOME=str(home), TMPDIR=str(temporary),
                        TMP=str(temporary), TEMP=str(temporary),
                        NUGET_PACKAGES=str(scratch / "packages"),
                        NUGET_HTTP_CACHE_PATH=str(scratch / "http"),
                        NUGET_PLUGINS_CACHE_PATH=str(scratch / "plugins"),
                        DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1",
                        DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
                    if sum(len(key.encode()) + len(value.encode()) + 2 for key, value in env.items()) > 131_072:
                        raise ValueError("installer environment exceeds limit")
                limits = ToolRunLimits(timeout_seconds=remaining, cpu_seconds=remaining,
                    memory_bytes=bounds.build_address_space_bytes,
                    resident_memory_bytes=bounds.build_memory_bytes,
                    max_output_bytes=bounds.build_output_bytes,
                    max_workspace_bytes=bounds.build_workspace_bytes,
                    max_workspace_entries=65_536, max_workspace_depth=64,
                    # Managed runtimes use sparse files; workspace scanning
                    # remains enabled when the per-file signal is unsuitable.
                    enforce_file_size_limit=not Path(arguments[0]).name.startswith("dotnet"))
                raw = SubprocessExecutor().execute(ProcessInvocation(argv=arguments,
                    runtime=ToolRuntime.NATIVE, cwd=directory,
                    environment=env, stdin=None, limits=limits), cancellation=signal)
                installation_checkpoint("after installer command cleanup")
                if signal.is_set():
                    raise InstallControlError("installer resource lease revoked")
                size = sum(len(value if isinstance(value, bytes) else value.encode("utf-8"))
                           for value in (raw.stdout, raw.stderr))
                if size > bounds.build_output_bytes:
                    raw = replace(raw, output_truncated=True,
                                  error=raw.error or "combined installer output exceeds limit")
                return raw

            if cwd is None:
                with tempfile.TemporaryDirectory(prefix="hyper-installer-probe-") as temporary:
                    raw = execute(Path(temporary))
            else:
                directory = Path(cwd)
                if directory.is_symlink() or not directory.is_dir():
                    raise ValueError("installer command cwd must be a real directory")
                raw = execute(directory.resolve())
        installation_checkpoint("after installer resource release")
        return raw


__all__ = ["HyperInstallLimits", "InstallControlError", "installation_scope",
           "installation_checkpoint", "current_install_limits", "run_install_command"]
