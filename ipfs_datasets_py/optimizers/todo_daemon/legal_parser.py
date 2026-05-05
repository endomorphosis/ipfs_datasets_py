"""Legal-parser daemon lifecycle entry point built on reusable todo-daemon code."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .core import (
    ManagedDaemonSpec,
    StopResult,
    first_present,
    iter_processes,
    now_iso,
    now_utc,
    pid_alive,
    process_args,
    read_json,
    read_pid_file,
    stop_daemon,
    supervisor_maintenance_snapshot,
    terminate_pid_tree,
    write_json,
)
from .cli import build_lifecycle_arg_parser, daemon_spec_payload, run_lifecycle_cli
from .specs import env_float, env_int, env_path, env_path_in_dir, env_value, repo_root_from_env
from .supervisor import heartbeat_snapshot, worktree_phase_worker_status
from .wrapper import launch_restarting_wrapper, pid_matches_command_fragments, restarting_wrapper_alive


JsonDict = Dict[str, Any]


def _env(name: str, default: str) -> str:
    return env_value(name, default)


def _repo_root(explicit: Optional[str] = None) -> Path:
    return repo_root_from_env(explicit)


def _daemon_dir() -> Path:
    return env_path("DAEMON_DIR", ".daemon")


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
    output_dir = env_path("OUTPUT_DIR", "artifacts/legal_parser_optimizer_daemon")
    run_script = env_path("RUN_SCRIPT", "scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh")
    worktree_root = env_path("LEGAL_PARSER_DAEMON_WORKTREE_ROOT", ".daemon/legal-parser-worktrees")
    return ManagedDaemonSpec(
        name="legal-parser",
        schema="ipfs_datasets_py.legal_parser_daemon",
        repo_root=root,
        daemon_dir=daemon_dir,
        runner=("bash", run_script.as_posix()),
        status_path=output_dir / "current_status.json",
        progress_path=output_dir / "progress_summary.json",
        supervisor_status_path=env_path_in_dir(
            "SUPERVISOR_STATUS_PATH",
            daemon_dir,
            "legal_parser_daemon_supervisor.json",
        ),
        supervisor_pid_path=env_path_in_dir(
            "SUPERVISOR_PID_PATH",
            daemon_dir,
            "legal_parser_daemon_supervisor.pid",
        ),
        child_pid_path=env_path_in_dir("CHILD_PID_PATH", daemon_dir, "legal_parser_daemon.pid"),
        supervisor_out_path=env_path_in_dir(
            "SUPERVISOR_OUT_PATH",
            daemon_dir,
            "legal_parser_daemon_supervisor.out",
        ),
        ensure_status_path=env_path_in_dir("ENSURE_STATUS_PATH", daemon_dir, "legal_parser_daemon_ensure.status.json"),
        ensure_check_path=env_path_in_dir("CHECK_LOG_PATH", daemon_dir, "legal_parser_daemon_ensure_check.json"),
        supervisor_lock_path=env_path_in_dir(
            "SUPERVISOR_LOCK_PATH",
            daemon_dir,
            "legal_parser_daemon_supervisor.lock",
        ),
        latest_log_path=env_path_in_dir("LATEST_LOG_PATH", daemon_dir, "legal_parser_daemon_overnight.log"),
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
    return pid_matches_command_fragments(
        pid,
        (
            "run_legal_parser_optimizer_daemon.sh",
            "legal-parser supervisor exited with code",
        ),
    )


def _wrapper_alive(spec: ManagedDaemonSpec, launch_mode: str) -> bool:
    return restarting_wrapper_alive(
        launch_mode=launch_mode,
        tmux_session_name=spec.tmux_session_name,
        pid_path=_wrapper_pid_path(spec),
        command_fragments=(
            "run_legal_parser_optimizer_daemon.sh",
            "legal-parser supervisor exited with code",
        ),
    )


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
    heartbeat = heartbeat_snapshot(current, stale_after_seconds=stale_after_seconds, now=now)
    heartbeat_age = heartbeat.age_seconds

    daemon_pid = heartbeat.pid
    supervisor_pid = supervisor.get("supervisor_pid") or read_pid_file(spec.resolve(spec.supervisor_pid_path))
    supervisor_alive = pid_alive(supervisor_pid) if supervisor_pid else False
    daemon_alive = heartbeat.pid_alive

    maintenance = supervisor_maintenance_snapshot(
        supervisor,
        now=now,
        supervisor_alive=supervisor_alive,
        active_statuses=(),
        active_status_suffixes=("_started",),
        running_statuses=(),
        running_status_suffixes=("running",),
        stuck_reason_prefixes=(),
    )
    daemon_fresh = heartbeat.fresh
    alive = bool(supervisor_alive and ((daemon_alive and daemon_fresh) or maintenance.fresh))
    status_label = "maintenance_running" if maintenance.fresh else "running" if alive else "stale_or_stopped"

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
        "model_name": first_present(current.get("model_name"), supervisor.get("model_name")),
        "provider": first_present(current.get("provider"), supervisor.get("provider")),
        "proposal_transport": first_present(
            current.get("proposal_transport"),
            supervisor.get("proposal_transport"),
        ),
        "worktree_edit_timeout_seconds": first_present(
            current.get("worktree_edit_timeout_seconds"),
            supervisor.get("worktree_edit_timeout_seconds"),
        ),
        "worktree_stale_after_seconds": first_present(
            current.get("worktree_stale_after_seconds"),
            supervisor.get("worktree_stale_after_seconds"),
        ),
        "worktree_codex_sandbox": first_present(
            current.get("worktree_codex_sandbox"),
            supervisor.get("worktree_codex_sandbox"),
        ),
        "repair_failed_tests_before_rollback": first_present(
            current.get("repair_failed_tests_before_rollback"),
            supervisor.get("repair_failed_tests_before_rollback"),
        ),
        "failed_test_repair_attempts": first_present(
            current.get("failed_test_repair_attempts"),
            supervisor.get("failed_test_repair_attempts"),
        ),
        "worktree_no_child_stall_seconds": worktree_no_child_threshold,
        "worktree_phase_worker_status": worktree_phase_worker_status(
            current,
            daemon_pid,
            worktree_no_child_threshold,
        ),
        "supervisor_status": supervisor.get("status"),
        "active_agentic_maintenance_started_at": supervisor.get("active_agentic_maintenance_started_at"),
        "active_agentic_maintenance_timeout_seconds": supervisor.get(
            "active_agentic_maintenance_timeout_seconds"
        ),
        "active_agentic_maintenance_age_seconds": maintenance.rounded_age_seconds,
        "active_agentic_maintenance_fresh": maintenance.fresh,
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
    wrapper_pid_path = _wrapper_pid_path(spec)

    launch = launch_restarting_wrapper(
        repo_root=spec.repo_root,
        command=("bash", spec.runner[-1]),
        out_path=out_path,
        pid_path=wrapper_pid_path,
        env=env,
        env_keys=("MODEL_NAME", "PROVIDER", "IPFS_DATASETS_PY_LLM_PROVIDER"),
        launch_mode=launch_mode,
        restart_delay_seconds=restart_delay_seconds,
        restart_message="legal-parser supervisor exited with code",
        tmux_session_name=spec.tmux_session_name,
    )
    return launch.mode, launch.pid


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


def run_legal_parser_daemon_runtime(argv: Optional[Sequence[str]] = None) -> int:
    """Run the packaged deterministic legal-parser daemon runtime.

    This keeps the large domain optimizer in its existing module for backward
    compatibility, but makes the runnable daemon available through the reusable
    todo-daemon package dispatcher.
    """

    from ipfs_datasets_py.optimizers.logic.deontic.parser_daemon import main as runtime_main

    return runtime_main(argv)


def build_arg_parser():
    return build_lifecycle_arg_parser(
        description="Manage the legal-parser optimizer daemon lifecycle.",
        default_stale_after_seconds=env_float("STALE_AFTER_SECONDS", 120.0, minimum=0.0),
        default_startup_wait_seconds=env_float("ENSURE_STARTUP_WAIT_SECONDS", 30.0, minimum=0.0),
        default_launch_mode=_env("ENSURE_LAUNCH_MODE", "nohup_loop"),
        launch_mode_choices=("nohup_loop", "tmux"),
        restart_delay_flag="--restart-delay-seconds",
        default_restart_delay_seconds=env_int("ENSURE_RESTART_DELAY_SECONDS", 5, minimum=0),
        default_stop_grace_seconds=env_float("STOP_GRACE_SECONDS", 10.0, minimum=0.0),
        ensure_description="Start the wrapper/supervisor if unhealthy.",
        stop_description="Stop the wrapper, supervisor, daemon, and owned Codex calls.",
        run_description="Run the legal-parser optimizer daemon runtime in the foreground.",
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
        run_fn=run_legal_parser_daemon_runtime,
        stop_not_running_message="legal-parser daemon supervisor is not running",
    )


if __name__ == "__main__":
    raise SystemExit(main())
