"""Legal-parser daemon lifecycle entry point built on reusable todo-daemon code."""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .core import (
    ManagedDaemonSpec,
    StopResult,
    child_pids,
    iter_processes,
    now_iso,
    now_utc,
    parse_timestamp,
    pid_alive,
    process_args,
    read_json,
    read_pid_file,
    stop_daemon,
    terminate_pid_tree,
    write_json,
)
from .cli import build_lifecycle_arg_parser, daemon_spec_payload, run_lifecycle_cli


JsonDict = Dict[str, Any]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _repo_root(explicit: Optional[str] = None) -> Path:
    return Path(explicit or os.environ.get("REPO_ROOT") or Path.cwd()).resolve()


def _daemon_dir() -> Path:
    return Path(_env("DAEMON_DIR", ".daemon"))


def legal_parser_launch_env() -> Dict[str, str]:
    """Return environment defaults used by the legal-parser supervisor."""

    return {
        "MODEL_NAME": _env("MODEL_NAME", "gpt-5.5"),
        "PROVIDER": _env("PROVIDER", "llm_router"),
        "IPFS_DATASETS_PY_LLM_PROVIDER": _env("IPFS_DATASETS_PY_LLM_PROVIDER", "codex_cli"),
    }


def build_legal_parser_spec(repo_root: Optional[str] = None) -> ManagedDaemonSpec:
    root = _repo_root(repo_root)
    daemon_dir = _daemon_dir()
    output_dir = Path(_env("OUTPUT_DIR", "artifacts/legal_parser_optimizer_daemon"))
    run_script = Path(_env("RUN_SCRIPT", "scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh"))
    worktree_root = Path(_env("LEGAL_PARSER_DAEMON_WORKTREE_ROOT", ".daemon/legal-parser-worktrees"))
    return ManagedDaemonSpec(
        name="legal-parser",
        schema="ipfs_datasets_py.legal_parser_daemon",
        repo_root=root,
        daemon_dir=daemon_dir,
        runner=("bash", run_script.as_posix()),
        status_path=output_dir / "current_status.json",
        progress_path=output_dir / "progress_summary.json",
        supervisor_status_path=Path(
            _env("SUPERVISOR_STATUS_PATH", f"{daemon_dir.as_posix()}/legal_parser_daemon_supervisor.json")
        ),
        supervisor_pid_path=Path(
            _env("SUPERVISOR_PID_PATH", f"{daemon_dir.as_posix()}/legal_parser_daemon_supervisor.pid")
        ),
        child_pid_path=Path(_env("CHILD_PID_PATH", f"{daemon_dir.as_posix()}/legal_parser_daemon.pid")),
        supervisor_out_path=Path(
            _env("SUPERVISOR_OUT_PATH", f"{daemon_dir.as_posix()}/legal_parser_daemon_supervisor.out")
        ),
        ensure_status_path=Path(
            _env("ENSURE_STATUS_PATH", f"{daemon_dir.as_posix()}/legal_parser_daemon_ensure.status.json")
        ),
        ensure_check_path=Path(
            _env("CHECK_LOG_PATH", f"{daemon_dir.as_posix()}/legal_parser_daemon_ensure_check.json")
        ),
        supervisor_lock_path=Path(
            _env("SUPERVISOR_LOCK_PATH", f"{daemon_dir.as_posix()}/legal_parser_daemon_supervisor.lock")
        ),
        latest_log_path=Path(_env("LATEST_LOG_PATH", f"{daemon_dir.as_posix()}/legal_parser_daemon_overnight.log")),
        tmux_session_name=_env("TMUX_SESSION_NAME", "legal-parser-daemon"),
        worktree_root=worktree_root,
        daemon_process_match_all=("ipfs_datasets_py.optimizers.logic.deontic.parser_daemon",),
        llm_process_match_any=(
            worktree_root.as_posix(),
            str(root / worktree_root),
        ),
        protected_ancestor_patterns=(
            "logic_port_daemon",
            "ppd/daemon/ppd_supervisor.py",
            "ppd/daemon/ppd_daemon.py",
        ),
        launch_env=legal_parser_launch_env(),
    )


def _wrapper_pid_path(spec: ManagedDaemonSpec) -> Path:
    return spec.repo_root / Path(
        _env("WRAPPER_PID_PATH", f"{spec.daemon_dir.as_posix()}/legal_parser_daemon_supervisor_wrapper.pid")
    )


def _pid_args(pid: Any) -> str:
    try:
        return process_args(int(pid))
    except Exception:
        return ""


def pid_is_legal_parser_supervisor(pid: Any) -> bool:
    try:
        pid_int = int(pid)
    except Exception:
        return False
    return pid_alive(pid_int) and "run_legal_parser_optimizer_daemon.sh" in _pid_args(pid_int)


def pid_is_legal_parser_wrapper(pid: Any) -> bool:
    try:
        pid_int = int(pid)
    except Exception:
        return False
    args = _pid_args(pid_int)
    return (
        pid_alive(pid_int)
        and "run_legal_parser_optimizer_daemon.sh" in args
        and "legal-parser supervisor exited with code" in args
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


def _wrapper_alive(spec: ManagedDaemonSpec, launch_mode: str) -> bool:
    if launch_mode == "tmux" and spec.tmux_session_name and _tmux_available():
        if _tmux_has_session(spec.tmux_session_name):
            return True
    return pid_is_legal_parser_wrapper(read_pid_file(_wrapper_pid_path(spec)))


def _descendant_processes(root_pid: Any) -> List[JsonDict]:
    try:
        root = int(root_pid)
    except Exception:
        return []
    stack = list(child_pids(root))
    seen: set[int] = set()
    found: List[JsonDict] = []
    while stack:
        pid = stack.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        found.append({"pid": pid, "cmdline": process_args(pid)})
        stack.extend(child_pids(pid))
    return found


def _worktree_phase_worker_status(
    current: Mapping[str, Any],
    daemon_pid: Any,
    threshold_seconds: float,
) -> JsonDict:
    phase = str(current.get("phase") or "")
    phases = {
        "requesting_worktree_edit",
        "retrying_worktree_edit",
        "repairing_failed_worktree_edit",
        "repairing_failed_tests_before_rollback",
    }
    if phase not in phases:
        return {"required": False, "phase": phase}
    now = now_utc()
    started = parse_timestamp(current.get("phase_started_at") or current.get("phase_updated_at"))
    age = None if started is None else max(0.0, (now - started).total_seconds())
    descendants = _descendant_processes(daemon_pid)
    workers = [
        item
        for item in descendants
        if "codex" in str(item.get("cmdline") or "").lower()
        and " exec" in (" " + " ".join(str(item.get("cmdline") or "").lower().split()))
    ]
    stalled = bool(age is not None and threshold_seconds > 0 and age >= threshold_seconds and not workers)
    return {
        "required": True,
        "phase": phase,
        "phase_age_seconds": None if age is None else round(age, 3),
        "threshold_seconds": threshold_seconds,
        "active_worker_pids": [item.get("pid") for item in workers],
        "active_worker_count": len(workers),
        "descendant_count": len(descendants),
        "stalled_without_active_worker": stalled,
    }


def check_legal_parser_health(
    spec: Optional[ManagedDaemonSpec] = None,
    *,
    stale_after_seconds: float = 120.0,
) -> JsonDict:
    """Return legal-parser daemon health with the historical check-script payload."""

    spec = spec or build_legal_parser_spec()
    current = read_json(spec.resolve(spec.status_path))
    supervisor = read_json(spec.resolve(spec.supervisor_status_path))
    ensure = read_json(spec.resolve(spec.ensure_status_path))
    progress = read_json(spec.resolve(spec.progress_path))
    supervisor_state = read_json(spec.repo_root / str(supervisor.get("agentic_state_path") or ""))

    now = now_utc()
    heartbeat_at = parse_timestamp(current.get("heartbeat_at") or current.get("updated_at"))
    heartbeat_age = None if heartbeat_at is None else max(0.0, (now - heartbeat_at).total_seconds())

    daemon_pid = current.get("heartbeat_pid") or current.get("pid")
    supervisor_pid = supervisor.get("supervisor_pid") or read_pid_file(spec.resolve(spec.supervisor_pid_path))
    supervisor_alive = pid_alive(supervisor_pid) if supervisor_pid else False
    daemon_alive = pid_alive(daemon_pid) if daemon_pid else False

    supervisor_status = str(supervisor.get("status") or "")
    maintenance_timeout = supervisor.get("active_agentic_maintenance_timeout_seconds")
    try:
        maintenance_timeout = float(maintenance_timeout)
    except Exception:
        maintenance_timeout = float(supervisor.get("agentic_timeout_seconds") or 0.0)
    maintenance_started_at = parse_timestamp(
        supervisor.get("active_agentic_maintenance_started_at") or supervisor.get("updated_at")
    )
    maintenance_age = None
    maintenance_fresh = False
    if (
        supervisor_alive
        and supervisor_status.endswith("_started")
        and str(supervisor.get("last_agentic_maintenance_status") or "").endswith("running")
        and maintenance_started_at is not None
        and maintenance_timeout > 0
    ):
        maintenance_age = max(0.0, (now - maintenance_started_at).total_seconds())
        maintenance_fresh = maintenance_age <= maintenance_timeout + 60.0
    daemon_fresh = heartbeat_age is not None and heartbeat_age <= stale_after_seconds
    alive = bool(supervisor_alive and ((daemon_alive and daemon_fresh) or maintenance_fresh))
    status_label = "maintenance_running" if maintenance_fresh else "running" if alive else "stale_or_stopped"

    try:
        worktree_no_child_threshold = float(
            current.get("worktree_no_child_stall_seconds")
            or supervisor.get("worktree_no_child_stall_seconds")
            or 0
        )
    except Exception:
        worktree_no_child_threshold = 0.0

    payload = {
        "alive": alive,
        "status": status_label,
        "checked_at": now.isoformat(),
        "stale_after_seconds": stale_after_seconds,
        "heartbeat_age_seconds": None if heartbeat_age is None else round(heartbeat_age, 3),
        "daemon_pid": daemon_pid,
        "daemon_pid_alive": daemon_alive,
        "supervisor_pid": supervisor_pid,
        "supervisor_pid_alive": supervisor_alive,
        "ensure_status": ensure.get("status"),
        "ensure_checked_at": ensure.get("checked_at"),
        "ensure_requested_launch_mode": ensure.get("requested_launch_mode"),
        "ensure_launch_mode": ensure.get("launch_mode"),
        "ensure_launcher_pid": ensure.get("launcher_pid"),
        "ensure_launcher_pid_alive": pid_is_legal_parser_wrapper(ensure.get("launcher_pid"))
        if ensure.get("launcher_pid")
        else False,
        "ensure_wrapper_pid": ensure.get("wrapper_pid"),
        "ensure_wrapper_pid_alive": pid_is_legal_parser_wrapper(ensure.get("wrapper_pid"))
        if ensure.get("wrapper_pid")
        else False,
        "ensure_supervisor_pid_alive": ensure.get("supervisor_pid_alive"),
        "cycle_index": current.get("cycle_index"),
        "phase": current.get("phase"),
        "model_name": current.get("model_name") or supervisor.get("model_name"),
        "provider": current.get("provider") or supervisor.get("provider"),
        "proposal_transport": current.get("proposal_transport") or supervisor.get("proposal_transport"),
        "worktree_edit_timeout_seconds": current.get("worktree_edit_timeout_seconds")
        or supervisor.get("worktree_edit_timeout_seconds"),
        "worktree_stale_after_seconds": current.get("worktree_stale_after_seconds")
        or supervisor.get("worktree_stale_after_seconds"),
        "worktree_codex_sandbox": current.get("worktree_codex_sandbox")
        or supervisor.get("worktree_codex_sandbox"),
        "repair_failed_tests_before_rollback": current.get("repair_failed_tests_before_rollback")
        if current.get("repair_failed_tests_before_rollback") is not None
        else supervisor.get("repair_failed_tests_before_rollback"),
        "failed_test_repair_attempts": current.get("failed_test_repair_attempts")
        or supervisor.get("failed_test_repair_attempts"),
        "worktree_no_child_stall_seconds": worktree_no_child_threshold,
        "worktree_phase_worker_status": _worktree_phase_worker_status(
            current,
            daemon_pid,
            worktree_no_child_threshold,
        ),
        "supervisor_status": supervisor.get("status"),
        "active_agentic_maintenance_started_at": supervisor.get("active_agentic_maintenance_started_at"),
        "active_agentic_maintenance_timeout_seconds": supervisor.get(
            "active_agentic_maintenance_timeout_seconds"
        ),
        "active_agentic_maintenance_age_seconds": None
        if maintenance_age is None
        else round(maintenance_age, 3),
        "active_agentic_maintenance_fresh": maintenance_fresh,
        "formal_logic_goal": supervisor.get("formal_logic_goal"),
        "restart_count": supervisor.get("restart_count"),
        "watchdog_stale_after_seconds": supervisor.get("watchdog_stale_after_seconds"),
        "watchdog_startup_grace_seconds": supervisor.get("watchdog_startup_grace_seconds"),
        "last_recycle_reason": supervisor.get("last_recycle_reason"),
        "phase_started_at": current.get("phase_started_at"),
        "phase_stale_after_seconds": current.get("phase_stale_after_seconds"),
        "phase_stale_after_reason": current.get("phase_stale_after_reason"),
        "agentic_maintenance_enabled": supervisor.get("agentic_maintenance_enabled"),
        "agentic_stalled_metric_cycles": supervisor.get("agentic_stalled_metric_cycles"),
        "agentic_acceptance_stall_cycles": supervisor.get("agentic_acceptance_stall_cycles"),
        "stalled_metric_cycles": progress.get("stalled_metric_cycles"),
        "cycles_since_meaningful_progress": progress.get("cycles_since_meaningful_progress"),
        "meaningful_progress_definition": progress.get("meaningful_progress_definition"),
        "rolled_back_since_meaningful_progress": progress.get("rolled_back_since_meaningful_progress"),
        "rolled_back_reasons_since_meaningful_progress": progress.get(
            "rolled_back_reasons_since_meaningful_progress"
        ),
        "current_dirty_legal_parser_targets": current.get("dirty_legal_parser_targets"),
        "current_dirty_legal_parser_targets_valid": current.get("dirty_legal_parser_targets_valid"),
        "current_dirty_legal_parser_targets_error": current.get("dirty_legal_parser_targets_error"),
        "current_dirty_legal_parser_targets_fingerprint": current.get(
            "dirty_legal_parser_targets_fingerprint"
        ),
        "current_dirty_legal_parser_targets_diff_summary": current.get(
            "dirty_legal_parser_targets_diff_summary"
        ),
        "progress_dirty_legal_parser_targets": progress.get("dirty_legal_parser_targets"),
        "progress_dirty_legal_parser_targets_valid": progress.get("dirty_legal_parser_targets_valid"),
        "progress_dirty_legal_parser_targets_error": progress.get("dirty_legal_parser_targets_error"),
        "progress_dirty_legal_parser_targets_fingerprint": progress.get(
            "dirty_legal_parser_targets_fingerprint"
        ),
        "progress_dirty_legal_parser_targets_diff_summary": progress.get(
            "dirty_legal_parser_targets_diff_summary"
        ),
        "active_dirty_touched_files": progress.get("active_dirty_touched_files"),
        "dirty_touched_file_rejection_count": progress.get("dirty_touched_file_rejection_count"),
        "supervisor_dirty_legal_parser_targets": supervisor_state.get("dirty_legal_parser_targets"),
        "supervisor_dirty_legal_parser_targets_fingerprint": supervisor_state.get(
            "dirty_legal_parser_targets_fingerprint"
        ),
        "supervisor_previous_dirty_legal_parser_targets": supervisor_state.get(
            "previous_dirty_legal_parser_targets"
        ),
        "supervisor_previous_dirty_legal_parser_targets_fingerprint": supervisor_state.get(
            "previous_dirty_legal_parser_targets_fingerprint"
        ),
        "supervisor_dirty_legal_parser_targets_confirmed": supervisor_state.get(
            "dirty_legal_parser_targets_confirmed"
        ),
        "supervisor_dirty_target_detection_valid": supervisor_state.get("dirty_target_detection_valid"),
        "supervisor_dirty_target_detection_errors": supervisor_state.get("dirty_target_detection_errors"),
        "supervisor_dirty_legal_parser_targets_deferred": supervisor_state.get(
            "dirty_legal_parser_targets_deferred"
        ),
        "supervisor_dirty_legal_parser_targets_defer_phase": supervisor_state.get(
            "dirty_legal_parser_targets_defer_phase"
        ),
        "supervisor_dirty_legal_parser_targets_pending_confirmation": supervisor_state.get(
            "dirty_legal_parser_targets_pending_confirmation"
        ),
        "supervisor_dirty_rejection_active_targets": supervisor_state.get("dirty_rejection_active_targets"),
        "supervisor_effective_phase_stall_threshold_seconds": supervisor_state.get(
            "effective_phase_stall_threshold_seconds"
        ),
        "agentic_rejected_tail": supervisor.get("agentic_rejected_tail"),
        "agentic_rolled_back_tail": supervisor.get("agentic_rolled_back_tail"),
        "agentic_cooldown_seconds": supervisor.get("agentic_cooldown_seconds"),
        "agentic_timeout_seconds": supervisor.get("agentic_timeout_seconds"),
        "agentic_state_path": supervisor.get("agentic_state_path"),
        "last_agentic_maintenance_status": supervisor.get("last_agentic_maintenance_status"),
        "last_agentic_maintenance_reason": supervisor.get("last_agentic_maintenance_reason"),
        "last_agentic_maintenance_log_path": supervisor.get("last_agentic_maintenance_log_path"),
        "current_status_path": spec.repo_relative(spec.status_path),
        "supervisor_status_path": spec.repo_relative(spec.supervisor_status_path),
    }
    return payload


def _write_health(spec: ManagedDaemonSpec, *, stale_after_seconds: float) -> JsonDict:
    payload = check_legal_parser_health(spec, stale_after_seconds=stale_after_seconds)
    path = spec.resolve(spec.ensure_check_path)
    if path is not None:
        write_json(path, payload)
    return payload


def _cleanup_stale_supervisor_artifacts(spec: ManagedDaemonSpec, launch_mode: str) -> None:
    supervisor_path = spec.resolve(spec.supervisor_pid_path)
    if supervisor_path is not None:
        pid = read_pid_file(supervisor_path)
        if pid and not pid_is_legal_parser_supervisor(pid):
            supervisor_path.unlink(missing_ok=True)
    lock_path = spec.resolve(spec.supervisor_lock_path)
    if lock_path is not None and not _supervisor_alive(spec):
        lock_path.unlink(missing_ok=True)
    wrapper_path = _wrapper_pid_path(spec)
    if wrapper_path.exists() and not _wrapper_alive(spec, launch_mode):
        wrapper_path.unlink(missing_ok=True)


def _supervisor_alive(spec: ManagedDaemonSpec) -> bool:
    return pid_is_legal_parser_supervisor(read_pid_file(spec.resolve(spec.supervisor_pid_path)))


def _wait_for_supervisor(spec: ManagedDaemonSpec, *, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while time.monotonic() < deadline:
        if _supervisor_alive(spec):
            return True
        time.sleep(0.5)
    return _supervisor_alive(spec)


def _launch_wrapper(
    spec: ManagedDaemonSpec,
    *,
    launch_mode: str,
    restart_delay_seconds: int,
    extra_env: Optional[Mapping[str, str]] = None,
) -> tuple[str, Optional[int]]:
    env = dict(os.environ)
    env.update(spec.launch_env)
    if extra_env:
        env.update({key: str(value) for key, value in extra_env.items()})
    env["REPO_ROOT"] = str(spec.repo_root)

    out_path = spec.resolve(spec.supervisor_out_path)
    assert out_path is not None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_pid_path = _wrapper_pid_path(spec)
    wrapper_pid_path.parent.mkdir(parents=True, exist_ok=True)

    model = shlex.quote(env.get("MODEL_NAME", "gpt-5.5"))
    provider = shlex.quote(env.get("PROVIDER", "llm_router"))
    router_provider = shlex.quote(env.get("IPFS_DATASETS_PY_LLM_PROVIDER", "codex_cli"))
    run_script = shlex.quote(spec.runner[-1])
    restart_delay = shlex.quote(str(int(restart_delay_seconds)))
    command_text = (
        f"while true; do MODEL_NAME={model} PROVIDER={provider} "
        f"IPFS_DATASETS_PY_LLM_PROVIDER={router_provider} bash {run_script}; "
        "rc=$?; "
        "printf '%s legal-parser supervisor exited with code %s; wrapper restarting in %ss\\n' "
        f"\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"$rc\" {restart_delay}; "
        f"sleep {restart_delay}; done"
    )

    if launch_mode == "tmux" and spec.tmux_session_name and _tmux_available():
        if _tmux_has_session(spec.tmux_session_name):
            subprocess.run(
                ("tmux", "kill-session", "-t", spec.tmux_session_name),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        result = subprocess.run(
            ("tmux", "new-session", "-d", "-s", spec.tmux_session_name, "-c", str(spec.repo_root), command_text),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            wrapper_pid_path.write_text("0\n", encoding="utf-8")
            return "tmux", 0

    out_handle = out_path.open("wb")
    process = subprocess.Popen(
        ("bash", "-lc", command_text),
        cwd=str(spec.repo_root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=out_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    out_handle.close()
    wrapper_pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    return "nohup_loop", int(process.pid)


def ensure_legal_parser_daemon(
    spec: Optional[ManagedDaemonSpec] = None,
    *,
    stale_after_seconds: float = 120.0,
    startup_wait_seconds: float = 30.0,
    launch_mode: str = "nohup_loop",
    restart_delay_seconds: int = 5,
    extra_env: Optional[Mapping[str, str]] = None,
) -> JsonDict:
    """Ensure the legal-parser wrapper/supervisor is running."""

    spec = spec or build_legal_parser_spec()
    daemon_dir = spec.resolve(spec.daemon_dir)
    assert daemon_dir is not None
    daemon_dir.mkdir(parents=True, exist_ok=True)
    checked_at = now_iso()

    _write_health(spec, stale_after_seconds=stale_after_seconds)
    supervisor_alive = _supervisor_alive(spec)
    wrapper_alive = _wrapper_alive(spec, launch_mode)
    started = False
    launcher_pid: Optional[int] = None
    actual_launch_mode = launch_mode

    if supervisor_alive and wrapper_alive:
        status = "already_running"
    elif supervisor_alive and not wrapper_alive:
        _cleanup_stale_supervisor_artifacts(spec, launch_mode)
        actual_launch_mode, launcher_pid = _launch_wrapper(
            spec,
            launch_mode=launch_mode,
            restart_delay_seconds=restart_delay_seconds,
            extra_env=extra_env,
        )
        status = "wrapped_existing_supervisor"
        started = True
    elif wrapper_alive and not supervisor_alive:
        if _wait_for_supervisor(spec, timeout_seconds=startup_wait_seconds):
            status = "wrapper_recovered_supervisor"
        else:
            _cleanup_stale_supervisor_artifacts(spec, launch_mode)
            actual_launch_mode, launcher_pid = _launch_wrapper(
                spec,
                launch_mode=launch_mode,
                restart_delay_seconds=restart_delay_seconds,
                extra_env=extra_env,
            )
            _wait_for_supervisor(spec, timeout_seconds=startup_wait_seconds)
            status = "started" if _supervisor_alive(spec) else "failed_to_start"
            started = True
    else:
        _cleanup_stale_supervisor_artifacts(spec, launch_mode)
        actual_launch_mode, launcher_pid = _launch_wrapper(
            spec,
            launch_mode=launch_mode,
            restart_delay_seconds=restart_delay_seconds,
            extra_env=extra_env,
        )
        _wait_for_supervisor(spec, timeout_seconds=startup_wait_seconds)
        status = "started" if _supervisor_alive(spec) else "failed_to_start"
        started = True

    check = _write_health(spec, stale_after_seconds=stale_after_seconds)
    supervisor_pid = read_pid_file(spec.resolve(spec.supervisor_pid_path))
    wrapper_pid = read_pid_file(_wrapper_pid_path(spec))
    payload = {
        "schema": "ipfs_datasets_py.legal_parser_daemon.ensure",
        "status": status,
        "checked_at": checked_at,
        "started_supervisor": started,
        "launcher_pid": launcher_pid,
        "wrapper_pid": wrapper_pid,
        "wrapper_pid_alive": pid_is_legal_parser_wrapper(wrapper_pid),
        "requested_launch_mode": launch_mode,
        "launch_mode": actual_launch_mode,
        "restart_delay_seconds": int(restart_delay_seconds),
        "supervisor_pid": supervisor_pid,
        "supervisor_pid_alive": pid_alive(supervisor_pid) if supervisor_pid else False,
        "supervisor_status_path": spec.repo_relative(spec.supervisor_status_path),
        "supervisor_out_path": spec.repo_relative(spec.supervisor_out_path),
        "check": check,
    }
    ensure_path = spec.resolve(spec.ensure_status_path)
    assert ensure_path is not None
    write_json(ensure_path, payload)
    return payload


def stop_legal_parser_daemon(
    spec: Optional[ManagedDaemonSpec] = None,
    *,
    grace_seconds: float = 10.0,
) -> StopResult:
    """Stop the legal-parser wrapper, supervisor, daemon child, and owned Codex calls."""

    spec = spec or build_legal_parser_spec()
    wrapper_pid = read_pid_file(_wrapper_pid_path(spec))
    stopped: List[int] = []
    if wrapper_pid and pid_alive(wrapper_pid):
        if terminate_pid_tree(wrapper_pid, grace_seconds=grace_seconds):
            stopped.append(wrapper_pid)
    result = stop_daemon(spec, grace_seconds=grace_seconds)
    stopped.extend(int(pid) for pid in result.payload.get("stopped_pids") or [])
    for pid, args in list(iter_processes()):
        if pid == os.getpid():
            continue
        if "run_legal_parser_optimizer_daemon.sh" in args or (
            "ipfs_datasets_py.optimizers.logic.deontic.parser_daemon" in args
        ):
            if terminate_pid_tree(pid, grace_seconds=grace_seconds):
                stopped.append(pid)
    try:
        _wrapper_pid_path(spec).unlink()
    except FileNotFoundError:
        pass
    payload = dict(result.payload)
    payload.update(
        {
            "schema": "ipfs_datasets_py.legal_parser_daemon.stop",
            "status": "stopped" if stopped or result.payload.get("status") == "stopped" else "not_running",
            "stopped_pids": sorted(set(stopped)),
            "wrapper_pid": wrapper_pid,
        }
    )
    return StopResult(payload=payload, exit_code=0)


def legal_parser_spec_payload(spec: ManagedDaemonSpec) -> Mapping[str, Any]:
    return daemon_spec_payload(
        spec,
        extra={"wrapper_pid_path": spec.repo_relative(_wrapper_pid_path(spec))},
    )


def build_arg_parser():
    return build_lifecycle_arg_parser(
        description="Manage the legal-parser optimizer daemon lifecycle.",
        default_stale_after_seconds=float(_env("STALE_AFTER_SECONDS", "120")),
        default_startup_wait_seconds=float(_env("ENSURE_STARTUP_WAIT_SECONDS", "30")),
        default_launch_mode=_env("ENSURE_LAUNCH_MODE", "nohup_loop"),
        launch_mode_choices=("nohup_loop", "tmux"),
        restart_delay_flag="--restart-delay-seconds",
        default_restart_delay_seconds=int(_env("ENSURE_RESTART_DELAY_SECONDS", "5")),
        default_stop_grace_seconds=float(_env("STOP_GRACE_SECONDS", "10")),
        ensure_description="Start the wrapper/supervisor if unhealthy.",
        stop_description="Stop the wrapper, supervisor, daemon, and owned Codex calls.",
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run_lifecycle_cli(
        argv,
        parser=build_arg_parser(),
        build_spec=build_legal_parser_spec,
        check_fn=check_legal_parser_health,
        ensure_fn=ensure_legal_parser_daemon,
        stop_fn=stop_legal_parser_daemon,
        ensure_restart_kw="restart_delay_seconds",
        spec_payload_builder=legal_parser_spec_payload,
        stop_not_running_message="legal-parser daemon supervisor is not running",
    )


if __name__ == "__main__":
    raise SystemExit(main())
