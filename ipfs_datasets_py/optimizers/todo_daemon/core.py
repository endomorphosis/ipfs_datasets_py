"""Shared process lifecycle primitives for optimizer todo daemons.

The logic-port daemon started as a collection of shell scripts.  This module
keeps the shell entry points stable while moving the reusable parts into Python
so future todo daemons can share health checks, ensure/startup behavior, and
process-family cleanup without copying brittle shell functions.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class ManagedDaemonSpec:
    """Declarative lifecycle configuration for one managed daemon family."""

    name: str
    schema: str
    repo_root: Path
    daemon_dir: Path
    runner: Tuple[str, ...]
    status_path: Path
    supervisor_status_path: Path
    supervisor_pid_path: Path
    child_pid_path: Path
    supervisor_out_path: Path
    ensure_status_path: Path
    ensure_check_path: Path
    progress_path: Optional[Path] = None
    result_log_path: Optional[Path] = None
    task_board_path: Optional[Path] = None
    supervisor_lock_path: Optional[Path] = None
    latest_log_path: Optional[Path] = None
    tmux_session_name: str = ""
    worktree_root: Optional[Path] = None
    daemon_process_match_all: Tuple[str, ...] = field(default_factory=tuple)
    llm_process_match_any: Tuple[str, ...] = field(default_factory=tuple)
    protected_ancestor_patterns: Tuple[str, ...] = field(default_factory=tuple)
    launch_env: Mapping[str, str] = field(default_factory=dict)

    def resolve(self, path: Optional[Path]) -> Optional[Path]:
        if path is None:
            return None
        return path if path.is_absolute() else self.repo_root / path

    def repo_relative(self, path: Optional[Path]) -> str:
        if path is None:
            return ""
        if path.is_absolute():
            try:
                return path.relative_to(self.repo_root).as_posix()
            except ValueError:
                return path.as_posix()
        return path.as_posix()


@dataclass(frozen=True)
class DaemonHealth:
    """Health-check result with the process-style exit code."""

    payload: JsonDict
    exit_code: int


@dataclass(frozen=True)
class EnsureResult:
    """Result from starting or confirming a supervised daemon."""

    payload: JsonDict
    check: JsonDict
    exit_code: int


@dataclass(frozen=True)
class StopResult:
    """Result from stopping a supervised daemon family."""

    payload: JsonDict
    exit_code: int


@dataclass(frozen=True)
class SupervisorMaintenanceSnapshot:
    """Parsed supervisor maintenance state for daemon health payloads."""

    active: bool
    fresh: bool
    timeout_seconds: float
    started_at: Optional[datetime]
    age_seconds: Optional[float]
    status: str
    running_status: str
    reason: str

    @property
    def rounded_age_seconds(self) -> Optional[float]:
        if self.age_seconds is None:
            return None
        return round(self.age_seconds, 3)


def read_json(path: Optional[Path]) -> JsonDict:
    if path is None:
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(dict(payload), handle, indent=2, sort_keys=True)
        handle.write("\n")


def parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def _as_utc_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def supervisor_maintenance_snapshot(
    supervisor: Mapping[str, Any],
    *,
    now: datetime,
    supervisor_alive: bool,
    active_statuses: Sequence[str] = ("agentic_maintenance_started",),
    active_status_suffixes: Sequence[str] = (),
    running_statuses: Sequence[str] = ("running",),
    running_status_suffixes: Sequence[str] = (),
    active_timeout_key: str = "active_agentic_maintenance_timeout_seconds",
    default_timeout_key: str = "agentic_timeout_seconds",
    stuck_timeout_key: str = "agentic_stuck_maintenance_timeout_seconds",
    stuck_reason_prefixes: Sequence[str] = (
        "stuck_phase:",
        "stuck_llm_subprocess:",
        "duplicate_llm_subprocesses:",
    ),
    grace_seconds: float = 60.0,
) -> SupervisorMaintenanceSnapshot:
    """Return whether supervisor-owned agentic maintenance is still fresh."""

    status = str(supervisor.get("status") or "")
    running_status = str(supervisor.get("last_agentic_maintenance_status") or "")
    reason = str(supervisor.get("last_agentic_maintenance_reason") or "")
    active = status in set(active_statuses) or any(
        suffix and status.endswith(suffix) for suffix in active_status_suffixes
    )
    running = running_status in set(running_statuses) or any(
        suffix and running_status.endswith(suffix) for suffix in running_status_suffixes
    )

    timeout = supervisor.get(active_timeout_key)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        if any(prefix and reason.startswith(prefix) for prefix in stuck_reason_prefixes):
            timeout = supervisor.get(stuck_timeout_key)
        else:
            timeout = supervisor.get(default_timeout_key)
    try:
        timeout_seconds = float(timeout)
    except Exception:
        timeout_seconds = 0.0

    now_at = _as_utc_datetime(now) or now_utc()
    started_at = _as_utc_datetime(
        parse_timestamp(supervisor.get("active_agentic_maintenance_started_at") or supervisor.get("updated_at"))
    )
    age_seconds = None
    fresh = False
    if supervisor_alive and active and running and started_at is not None and timeout_seconds > 0:
        age_seconds = max(0.0, (now_at - started_at).total_seconds())
        fresh = age_seconds <= timeout_seconds + max(0.0, float(grace_seconds))

    return SupervisorMaintenanceSnapshot(
        active=active,
        fresh=fresh,
        timeout_seconds=timeout_seconds,
        started_at=started_at,
        age_seconds=age_seconds,
        status=status,
        running_status=running_status,
        reason=reason,
    )


def pid_alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def read_pid_file(path: Optional[Path]) -> Optional[int]:
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else None
    except Exception:
        return None


def process_args(pid: int) -> str:
    result = subprocess.run(
        ("ps", "-o", "args=", "-p", str(pid)),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def parent_pid(pid: int) -> Optional[int]:
    result = subprocess.run(
        ("ps", "-o", "ppid=", "-p", str(pid)),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    digits = "".join(ch for ch in result.stdout if ch.isdigit())
    if not digits:
        return None
    parent = int(digits)
    return None if parent in {0, pid} else parent


def iter_processes() -> Iterable[Tuple[int, str]]:
    result = subprocess.run(
        ("ps", "-eo", "pid=,args="),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, args = stripped.partition(" ")
        try:
            yield int(pid_text), args.strip()
        except ValueError:
            continue


def pid_has_ancestor_matching(pid: int, patterns: Sequence[str]) -> bool:
    current: Optional[int] = pid
    while current and current not in {0, 1}:
        args = process_args(current)
        if any(pattern and pattern in args for pattern in patterns):
            return True
        current = parent_pid(current)
    return False


def child_pids(pid: int) -> List[int]:
    result = subprocess.run(
        ("pgrep", "-P", str(pid)),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    children: List[int] = []
    for line in result.stdout.splitlines():
        try:
            children.append(int(line.strip()))
        except ValueError:
            continue
    return children


def terminate_pid_tree(pid: int, *, grace_seconds: float) -> bool:
    if not pid_alive(pid):
        return False
    for child in child_pids(pid):
        terminate_pid_tree(child, grace_seconds=grace_seconds)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False

    deadline = time.monotonic() + max(0.0, grace_seconds)
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if pid_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
    return True


def check_daemon_health(spec: ManagedDaemonSpec, *, stale_after_seconds: float = 180.0) -> DaemonHealth:
    """Return the same health payload shape that the shell check script used."""

    status = read_json(spec.resolve(spec.status_path))
    progress = read_json(spec.resolve(spec.progress_path))
    supervisor = read_json(spec.resolve(spec.supervisor_status_path))
    checked_at = now_utc()
    heartbeat_at = parse_timestamp(
        status.get("heartbeat_at")
        or status.get("updated_at")
        or progress.get("updated_at")
        or supervisor.get("updated_at")
    )
    heartbeat_age = None
    if heartbeat_at is not None:
        heartbeat_age = max(0.0, (checked_at - heartbeat_at).total_seconds())

    supervisor_pid = supervisor.get("supervisor_pid") or read_pid_file(spec.resolve(spec.supervisor_pid_path))
    supervisor_alive = bool(supervisor_pid and pid_alive(supervisor_pid))
    supervisor_daemon_pid = supervisor.get("daemon_pid")
    status_daemon_pid = status.get("heartbeat_pid") or status.get("pid")
    daemon_pid = supervisor_daemon_pid if supervisor_alive and supervisor_daemon_pid else status_daemon_pid
    daemon_alive = bool(daemon_pid and pid_alive(daemon_pid))
    fresh = heartbeat_age is not None and heartbeat_age <= stale_after_seconds

    maintenance = supervisor_maintenance_snapshot(
        supervisor,
        now=checked_at,
        supervisor_alive=supervisor_alive,
    )

    alive = bool(supervisor_alive and ((daemon_alive and fresh) or maintenance.fresh))
    status_label = "maintenance_running" if maintenance.fresh else "running" if alive else "stale_or_stopped"
    active_state = status.get("active_state") or status.get("state") or progress.get("active_state")

    def first_present(*values: Any) -> Any:
        for value in values:
            if value is not None and value != "":
                return value
        return None

    payload: JsonDict = {
        "alive": alive,
        "status": status_label,
        "checked_at": checked_at.isoformat(),
        "stale_after_seconds": stale_after_seconds,
        "heartbeat_age_seconds": None if heartbeat_age is None else round(heartbeat_age, 3),
        "daemon_pid": daemon_pid,
        "daemon_pid_alive": daemon_alive,
        "status_daemon_pid": status_daemon_pid,
        "supervisor_daemon_pid": supervisor_daemon_pid,
        "supervisor_pid": supervisor_pid,
        "supervisor_pid_alive": supervisor_alive,
        "supervisor_status": supervisor.get("status"),
        "restart_count": supervisor.get("restart_count"),
        "watchdog_stale_after_seconds": supervisor.get("watchdog_stale_after_seconds"),
        "watchdog_startup_grace_seconds": supervisor.get("watchdog_startup_grace_seconds"),
        "phase_stuck_grace_seconds": supervisor.get("phase_stuck_grace_seconds"),
        "stop_grace_seconds": supervisor.get("stop_grace_seconds"),
        "last_recycle_reason": supervisor.get("last_recycle_reason"),
        "active_state": active_state,
        "active_state_started_at": status.get("active_state_started_at") or status.get("state_started_at"),
        "current_task": progress.get("current_task") or status.get("selected_task"),
        "plan_status_counts": progress.get("plan_status_counts"),
        "failure_kind_counts": progress.get("failure_kind_counts"),
        "typescript_quality_failures": progress.get("typescript_quality_failures"),
        "stagnant_rounds_since_valid": progress.get("stagnant_rounds_since_valid"),
        "latest_round": progress.get("latest_round"),
        "model_name": status.get("model_name") or supervisor.get("model_name"),
        "provider": status.get("provider") or supervisor.get("provider"),
        "router_default_mode": supervisor.get("router_default_mode"),
        "enable_ipfs_accelerate": supervisor.get("enable_ipfs_accelerate"),
        "proposal_transport": first_present(
            status.get("proposal_transport"),
            progress.get("proposal_transport"),
            supervisor.get("proposal_transport"),
        ),
        "worktree_edit_timeout_seconds": first_present(
            status.get("worktree_edit_timeout_seconds"),
            progress.get("worktree_edit_timeout_seconds"),
            supervisor.get("worktree_edit_timeout_seconds"),
        ),
        "worktree_stale_after_seconds": first_present(
            status.get("worktree_stale_after_seconds"),
            progress.get("worktree_stale_after_seconds"),
            supervisor.get("worktree_stale_after_seconds"),
        ),
        "worktree_codex_sandbox": first_present(
            status.get("worktree_codex_sandbox"),
            progress.get("worktree_codex_sandbox"),
            supervisor.get("worktree_codex_sandbox"),
        ),
        "worktree_root": first_present(
            status.get("worktree_root"),
            progress.get("worktree_root"),
            supervisor.get("worktree_root"),
        ),
        "worktree_repair_attempts": first_present(
            status.get("worktree_repair_attempts"),
            progress.get("worktree_repair_attempts"),
            supervisor.get("worktree_repair_attempts"),
        ),
        "auto_commit": first_present(
            status.get("auto_commit"),
            progress.get("auto_commit"),
            supervisor.get("auto_commit"),
        ),
        "auto_commit_startup_dirty": first_present(
            status.get("auto_commit_startup_dirty"),
            progress.get("auto_commit_startup_dirty"),
            supervisor.get("auto_commit_startup_dirty"),
        ),
        "auto_commit_branch": first_present(
            status.get("auto_commit_branch"),
            progress.get("auto_commit_branch"),
            supervisor.get("auto_commit_branch"),
        ),
        "status_path": spec.repo_relative(spec.status_path),
        "progress_path": spec.repo_relative(spec.progress_path),
        "supervisor_status_path": spec.repo_relative(spec.supervisor_status_path),
        "supervisor_lock_path": supervisor.get("supervisor_lock_path")
        or spec.repo_relative(spec.supervisor_lock_path),
        "agentic_maintenance_enabled": supervisor.get("agentic_maintenance_enabled"),
        "agentic_stagnant_rounds": supervisor.get("agentic_stagnant_rounds"),
        "agentic_task_failures": supervisor.get("agentic_task_failures"),
        "agentic_proposal_failures": supervisor.get("agentic_proposal_failures"),
        "agentic_rollback_failures": supervisor.get("agentic_rollback_failures"),
        "agentic_typescript_quality_failures": supervisor.get("agentic_typescript_quality_failures"),
        "agentic_cooldown_seconds": supervisor.get("agentic_cooldown_seconds"),
        "agentic_timeout_seconds": supervisor.get("agentic_timeout_seconds"),
        "agentic_stuck_maintenance_timeout_seconds": supervisor.get("agentic_stuck_maintenance_timeout_seconds"),
        "task_board_path": supervisor.get("task_board_path") or spec.repo_relative(spec.task_board_path),
        "active_agentic_maintenance_started_at": supervisor.get("active_agentic_maintenance_started_at"),
        "active_agentic_maintenance_timeout_seconds": supervisor.get("active_agentic_maintenance_timeout_seconds"),
        "active_agentic_maintenance_age_seconds": maintenance.rounded_age_seconds,
        "active_agentic_maintenance_fresh": maintenance.fresh,
        "agentic_state_path": supervisor.get("agentic_state_path"),
        "last_agentic_maintenance_status": supervisor.get("last_agentic_maintenance_status"),
        "last_agentic_maintenance_reason": supervisor.get("last_agentic_maintenance_reason"),
        "last_agentic_maintenance_log_path": supervisor.get("last_agentic_maintenance_log_path"),
    }
    return DaemonHealth(payload=payload, exit_code=0 if alive else 1)


def _merged_launch_env(spec: ManagedDaemonSpec, extra_env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    env = dict(os.environ)
    env.update({key: str(value) for key, value in spec.launch_env.items()})
    if extra_env:
        env.update({key: str(value) for key, value in extra_env.items()})
    env["REPO_ROOT"] = str(spec.repo_root)
    return env


def _quote_env_exports(env: Mapping[str, str], keys: Sequence[str]) -> str:
    parts = []
    for key in keys:
        if key in env:
            parts.append(f"{key}={shlex.quote(str(env[key]))}")
    return " ".join(parts)


def _tmux_has_session(name: str) -> bool:
    return (
        subprocess.run(
            ("tmux", "has-session", "-t", name),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def _tmux_available() -> bool:
    return (
        subprocess.run(
            ("bash", "-lc", "command -v tmux >/dev/null 2>&1"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def launch_supervisor(
    spec: ManagedDaemonSpec,
    *,
    launch_mode: str,
    tmux_restart_delay_seconds: int,
    extra_env: Optional[Mapping[str, str]] = None,
) -> Tuple[str, int]:
    """Launch the configured supervisor and return ``(mode, launcher_pid)``."""

    env = _merged_launch_env(spec, extra_env)
    out_path = spec.resolve(spec.supervisor_out_path)
    assert out_path is not None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    runner = tuple(str(part) for part in spec.runner)

    if launch_mode == "tmux" and spec.tmux_session_name and _tmux_available():
        if _tmux_has_session(spec.tmux_session_name):
            subprocess.run(
                ("tmux", "kill-session", "-t", spec.tmux_session_name),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        export_keys = tuple(spec.launch_env.keys()) + ("REPO_ROOT",)
        exports = _quote_env_exports(env, export_keys)
        command = " ".join(shlex.quote(part) for part in runner)
        out_quoted = shlex.quote(str(out_path))
        restart_delay = int(tmux_restart_delay_seconds)
        wrapper = (
            f"while true; do {exports} {command} </dev/null > {out_quoted} 2>&1; "
            "rc=$?; "
            f"printf '%s supervisor exited with code %s; tmux wrapper restarting in {restart_delay}s\\n' "
            "\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"$rc\" >> "
            f"{out_quoted}; sleep {restart_delay}; done"
        )
        result = subprocess.run(
            ("tmux", "new-session", "-d", "-s", spec.tmux_session_name, "-c", str(spec.repo_root), wrapper),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return "tmux", 0

    out_handle = out_path.open("wb")
    process = subprocess.Popen(
        runner,
        cwd=str(spec.repo_root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=out_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    out_handle.close()
    return "nohup_setsid", int(process.pid)


def wait_for_supervisor(spec: ManagedDaemonSpec, *, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while time.monotonic() < deadline:
        pid = read_pid_file(spec.resolve(spec.supervisor_pid_path))
        if pid and pid_alive(pid):
            return True
        time.sleep(0.5)
    pid = read_pid_file(spec.resolve(spec.supervisor_pid_path))
    return bool(pid and pid_alive(pid))


def ensure_daemon_running(
    spec: ManagedDaemonSpec,
    *,
    stale_after_seconds: float = 180.0,
    startup_wait_seconds: float = 20.0,
    launch_mode: str = "nohup",
    tmux_restart_delay_seconds: int = 5,
    extra_env: Optional[Mapping[str, str]] = None,
) -> EnsureResult:
    """Start a supervisor if the managed daemon is not healthy."""

    daemon_dir = spec.resolve(spec.daemon_dir)
    assert daemon_dir is not None
    daemon_dir.mkdir(parents=True, exist_ok=True)
    checked_at = now_iso()
    initial = check_daemon_health(spec, stale_after_seconds=stale_after_seconds)
    if initial.exit_code == 0:
        payload = {
            "schema": f"{spec.schema}.ensure",
            "status": "already_running",
            "checked_at": checked_at,
            "started_supervisor": False,
            "check": initial.payload,
        }
        ensure_path = spec.resolve(spec.ensure_status_path)
        assert ensure_path is not None
        write_json(ensure_path, payload)
        return EnsureResult(payload=payload, check=initial.payload, exit_code=0)

    actual_launch_mode, launcher_pid = launch_supervisor(
        spec,
        launch_mode=launch_mode,
        tmux_restart_delay_seconds=tmux_restart_delay_seconds,
        extra_env=extra_env,
    )
    wait_for_supervisor(spec, timeout_seconds=startup_wait_seconds)
    followup = check_daemon_health(spec, stale_after_seconds=stale_after_seconds)
    supervisor_pid = read_pid_file(spec.resolve(spec.supervisor_pid_path))
    supervisor_alive = bool(supervisor_pid and pid_alive(supervisor_pid))
    supervisor_status = read_json(spec.resolve(spec.supervisor_status_path))
    if followup.exit_code == 0:
        status = "started"
        exit_code = 0
    elif supervisor_alive:
        status = "supervisor_started_waiting_for_daemon"
        exit_code = 0
    else:
        status = "start_attempted_but_unhealthy"
        exit_code = 1

    payload = {
        "schema": f"{spec.schema}.ensure",
        "status": status,
        "checked_at": checked_at,
        "started_supervisor": True,
        "launcher_pid": launcher_pid,
        "launch_mode": actual_launch_mode,
        "tmux_session_name": spec.tmux_session_name,
        "tmux_restart_delay_seconds": int(tmux_restart_delay_seconds),
        "supervisor_pid": supervisor_pid,
        "supervisor_pid_alive": supervisor_alive,
        "supervisor_status": supervisor_status.get("status"),
        "startup_wait_seconds": int(startup_wait_seconds),
        "check": followup.payload,
    }
    if "SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE" in spec.launch_env:
        payload["agentic_startup_failure_maintenance"] = spec.launch_env[
            "SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE"
        ]
    for key in (
        "proposal_transport",
        "worktree_root",
        "worktree_repair_attempts",
        "auto_commit",
        "auto_commit_startup_dirty",
        "auto_commit_branch",
    ):
        payload[key] = followup.payload.get(key)
    ensure_path = spec.resolve(spec.ensure_status_path)
    assert ensure_path is not None
    write_json(ensure_path, payload)
    check_path = spec.resolve(spec.ensure_check_path)
    if check_path is not None:
        write_json(check_path, followup.payload)
    return EnsureResult(payload=payload, check=followup.payload, exit_code=exit_code)


def _matches_all(args: str, patterns: Sequence[str]) -> bool:
    return bool(patterns) and all(pattern in args for pattern in patterns)


def _is_managed_codex_process(spec: ManagedDaemonSpec, pid: int, args: str) -> bool:
    if "codex exec --skip-git-repo-check" not in args:
        return False
    if spec.llm_process_match_any and not any(pattern in args for pattern in spec.llm_process_match_any):
        return False
    if spec.protected_ancestor_patterns and pid_has_ancestor_matching(pid, spec.protected_ancestor_patterns):
        return False
    worktree_root = spec.resolve(spec.worktree_root)
    cwd = ""
    try:
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except Exception:
        pass
    if not worktree_root:
        return cwd == str(spec.repo_root)
    worktree_text = str(worktree_root)
    return (
        cwd == str(spec.repo_root)
        or cwd == str(spec.repo_root / "ipfs_datasets_py")
        or cwd.startswith(worktree_text)
        or spec.repo_relative(spec.worktree_root) in args
        or worktree_text in args
    )


def stop_daemon(
    spec: ManagedDaemonSpec,
    *,
    grace_seconds: float = 10.0,
    cleanup_tmux: bool = True,
) -> StopResult:
    """Stop a supervisor, its child process, and matching managed LLM calls."""

    stopped: List[int] = []
    supervisor_pid = read_pid_file(spec.resolve(spec.supervisor_pid_path))
    child_pid = read_pid_file(spec.resolve(spec.child_pid_path))
    primary_running = False
    if supervisor_pid and pid_alive(supervisor_pid):
        primary_running = True
        if terminate_pid_tree(supervisor_pid, grace_seconds=grace_seconds):
            stopped.append(supervisor_pid)
    elif child_pid and pid_alive(child_pid):
        primary_running = True
        if terminate_pid_tree(child_pid, grace_seconds=grace_seconds):
            stopped.append(child_pid)

    for pid, args in list(iter_processes()):
        if pid == os.getpid():
            continue
        if _matches_all(args, spec.daemon_process_match_all):
            if terminate_pid_tree(pid, grace_seconds=grace_seconds):
                stopped.append(pid)

    for pid, args in list(iter_processes()):
        if pid == os.getpid():
            continue
        if _is_managed_codex_process(spec, pid, args):
            if terminate_pid_tree(pid, grace_seconds=grace_seconds):
                stopped.append(pid)

    tmux_killed = False
    if cleanup_tmux and spec.tmux_session_name and _tmux_available() and _tmux_has_session(spec.tmux_session_name):
        result = subprocess.run(
            ("tmux", "kill-session", "-t", spec.tmux_session_name),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        tmux_killed = result.returncode == 0

    time.sleep(0.5)
    for path in (spec.resolve(spec.supervisor_pid_path), spec.resolve(spec.child_pid_path)):
        if path is not None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    payload = {
        "schema": f"{spec.schema}.stop",
        "status": "stopped" if primary_running or stopped or tmux_killed else "not_running",
        "checked_at": now_iso(),
        "stopped_pids": sorted(set(stopped)),
        "tmux_session_killed": tmux_killed,
        "supervisor_pid": supervisor_pid,
        "child_pid": child_pid,
    }
    return StopResult(payload=payload, exit_code=0)
