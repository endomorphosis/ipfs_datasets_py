"""Reusable child-process runtime helpers for todo-daemon supervisors."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

from .core import terminate_pid_tree


@dataclass(frozen=True)
class RestartPolicy:
    """Restart delays for a supervised daemon child."""

    restart_backoff_seconds: float = 30.0
    fast_restart_backoff_seconds: float = 2.0
    fast_restart_statuses: frozenset[str] = frozenset(
        {
            "dirty_recovery_skipped_clean",
            "repeated_rejection_recovery_skipped_clean",
            "no_change",
        }
    )

    def delay_for_status(self, status: str) -> float:
        if status in self.fast_restart_statuses:
            return max(0.0, float(self.fast_restart_backoff_seconds))
        return max(0.0, float(self.restart_backoff_seconds))


@dataclass(frozen=True)
class SupervisedChildSpec:
    """Configuration for one supervisor-owned child process."""

    repo_root: Path
    command: tuple[str, ...]
    log_path: Path
    child_pid_path: Path
    latest_log_path: Optional[Path] = None
    env: Mapping[str, str] = field(default_factory=dict)
    stdin_devnull: bool = True
    start_new_session: bool = True

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.repo_root / path


@dataclass(frozen=True)
class SupervisedChild:
    """A launched supervisor child process and its resolved artifacts."""

    pid: int
    command: tuple[str, ...]
    log_path: Path
    child_pid_path: Path
    latest_log_path: Optional[Path] = None
    started_at: str = ""


def supervisor_run_id(now: Optional[datetime] = None) -> str:
    """Return the stable UTC run id format used by unattended supervisors."""

    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def supervised_log_path(
    daemon_dir: Path,
    *,
    prefix: str,
    run_id: str,
    suffix: str = ".log",
) -> Path:
    """Return a supervisor child log path under ``daemon_dir``."""

    return daemon_dir / f"{prefix}_{run_id}{suffix}"


def build_python_module_command(
    module: str,
    args: Sequence[str] = (),
    *,
    python_executable: str = "python3",
    unbuffered: bool = True,
) -> tuple[str, ...]:
    """Build a ``python -m`` command tuple for a reusable daemon module."""

    command = [python_executable]
    if unbuffered:
        command.append("-u")
    command.extend(["-m", module])
    command.extend(str(arg) for arg in args)
    return tuple(command)


def launch_supervised_child(spec: SupervisedChildSpec) -> SupervisedChild:
    """Launch a supervisor-owned child process and write its marker files."""

    log_path = spec.resolve(spec.log_path)
    child_pid_path = spec.resolve(spec.child_pid_path)
    latest_log_path = spec.resolve(spec.latest_log_path) if spec.latest_log_path is not None else None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    child_pid_path.parent.mkdir(parents=True, exist_ok=True)
    if latest_log_path is not None:
        latest_log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            latest_log_path.unlink()
        except FileNotFoundError:
            pass
        latest_log_path.symlink_to(log_path.name)

    env = dict(os.environ)
    env.update({key: str(value) for key, value in spec.env.items()})
    out_handle = log_path.open("ab")
    try:
        process = subprocess.Popen(
            spec.command,
            cwd=str(spec.repo_root),
            env=env,
            stdin=subprocess.DEVNULL if spec.stdin_devnull else None,
            stdout=out_handle,
            stderr=subprocess.STDOUT,
            start_new_session=spec.start_new_session,
        )
    finally:
        out_handle.close()
    child_pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    return SupervisedChild(
        pid=int(process.pid),
        command=tuple(spec.command),
        log_path=log_path,
        child_pid_path=child_pid_path,
        latest_log_path=latest_log_path,
        started_at=datetime.now(timezone.utc).isoformat(),
    )


def clear_child_pid_file(child: SupervisedChild | SupervisedChildSpec, *, pid: Optional[int] = None) -> bool:
    """Remove a child pid file if it still refers to the expected child."""

    child_pid_path = child.child_pid_path
    if isinstance(child, SupervisedChildSpec):
        child_pid_path = child.resolve(child.child_pid_path)
    expected = str(pid if pid is not None else getattr(child, "pid", "")).strip()
    try:
        current = child_pid_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return False
    if expected and current != expected:
        return False
    child_pid_path.unlink(missing_ok=True)
    return True


def terminate_supervised_child(
    child: SupervisedChild,
    *,
    grace_seconds: float = 10.0,
    clear_pid_file: bool = True,
) -> bool:
    """Terminate a supervisor child process tree and optionally clear its pid file."""

    stopped = terminate_pid_tree(child.pid, grace_seconds=grace_seconds)
    if clear_pid_file:
        clear_child_pid_file(child)
    return stopped


def wait_for_child_exit(child: SupervisedChild, *, poll_interval_seconds: float = 0.2) -> int:
    """Wait for a child process id to disappear and return a process-style code."""

    while True:
        try:
            waited_pid, status = os.waitpid(child.pid, os.WNOHANG)
        except ChildProcessError:
            return 0
        if waited_pid == child.pid:
            if os.WIFEXITED(status):
                return os.WEXITSTATUS(status)
            if os.WIFSIGNALED(status):
                return 128 + os.WTERMSIG(status)
            return status
        time.sleep(max(0.01, float(poll_interval_seconds)))


def current_python_executable_command(module: str, args: Sequence[str] = ()) -> tuple[str, ...]:
    """Build a ``sys.executable -m`` command for in-package supervisors."""

    return build_python_module_command(
        module,
        args,
        python_executable=sys.executable,
        unbuffered=True,
    )
