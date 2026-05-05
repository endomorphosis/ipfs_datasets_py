"""Reusable Python supervisor loop for unattended todo daemons."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .core import ManagedDaemonSpec, read_json
from .supervisor import SupervisorStatusContext, heartbeat_snapshot, worktree_phase_worker_status
from .supervisor_runtime import (
    RestartPolicy,
    SupervisedChild,
    SupervisedChildSpec,
    clear_child_pid_file,
    launch_supervised_child,
    supervised_log_path,
    supervisor_run_id,
    terminate_supervised_child,
    wait_for_child_exit,
)


@dataclass(frozen=True)
class SupervisorLoopDecision:
    """Watchdog decision for a supervisor loop iteration."""

    action: str = "continue"
    reason: str = ""
    status: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def keep_running(cls) -> "SupervisorLoopDecision":
        return cls(action="continue")

    @classmethod
    def recycle(cls, reason: str, *, detail: Optional[Mapping[str, Any]] = None) -> "SupervisorLoopDecision":
        return cls(action="recycle", reason=reason, detail=dict(detail or {}))

    @classmethod
    def stop(cls, reason: str = "", *, status: str = "stopped") -> "SupervisorLoopDecision":
        return cls(action="stop", reason=reason, status=status)


@dataclass(frozen=True)
class SupervisorLoopConfig:
    """Configuration for a reusable child-process supervisor loop."""

    spec: ManagedDaemonSpec
    command: tuple[str, ...]
    log_prefix: str
    restart_policy: RestartPolicy = field(default_factory=RestartPolicy)
    heartbeat_seconds: float = 30.0
    poll_seconds: float = 1.0
    watchdog_stale_after_seconds: float = 180.0
    watchdog_startup_grace_seconds: float = 30.0
    stop_grace_seconds: float = 10.0
    max_restarts: int = 0
    latest_log_path: Optional[Path] = None
    child_env: Mapping[str, str] = field(default_factory=dict)
    status_static_fields: Mapping[str, Any] = field(default_factory=dict)
    status_extra_fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SupervisorLoopResult:
    """Summary returned by a completed reusable supervisor loop."""

    status: str
    restart_count: int
    last_exit_code: Optional[int] = None
    last_recycle_reason: str = ""
    last_run_id: str = ""
    last_log_path: str = ""


WatchdogHook = Callable[["SupervisorLoop", SupervisedChild, Mapping[str, Any]], SupervisorLoopDecision]
SupervisorLoopConfigFactory = Callable[[argparse.Namespace], SupervisorLoopConfig]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _poll_child_exit(child: SupervisedChild) -> Optional[int]:
    try:
        waited_pid, status = os.waitpid(child.pid, os.WNOHANG)
    except ChildProcessError:
        return 0
    if waited_pid != child.pid:
        return None
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return status


class SupervisorLoop:
    """Reusable long-running supervisor for todo-daemon child modules.

    The loop owns the common mechanics: launch child, write supervisor status,
    monitor stale heartbeats and workerless worktree phases, recycle unhealthy
    children, maintain PID/log markers, and apply restart delays.
    """

    def __init__(
        self,
        config: SupervisorLoopConfig,
        *,
        watchdog_hook: Optional[WatchdogHook] = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.watchdog_hook = watchdog_hook
        self.sleep = sleep
        self.monotonic = monotonic
        self.status = SupervisorStatusContext(
            config.spec,
            static_fields={
                "restart_backoff_seconds": config.restart_policy.restart_backoff_seconds,
                "fast_restart_backoff_seconds": config.restart_policy.fast_restart_backoff_seconds,
                "supervisor_heartbeat_seconds": config.heartbeat_seconds,
                "supervisor_poll_seconds": config.poll_seconds,
                "watchdog_stale_after_seconds": config.watchdog_stale_after_seconds,
                "watchdog_startup_grace_seconds": config.watchdog_startup_grace_seconds,
                "stop_grace_seconds": config.stop_grace_seconds,
                **dict(config.status_static_fields),
            },
        )
        self.restart_count = 0
        self.last_exit_code: Optional[int] = None
        self.last_recycle_reason = ""
        self.last_run_id = ""
        self.last_log_path = ""

    def _child_spec(self, run_id: str) -> SupervisedChildSpec:
        log_path = supervised_log_path(
            self.config.spec.daemon_dir,
            prefix=self.config.log_prefix,
            run_id=run_id,
        )
        return SupervisedChildSpec(
            repo_root=self.config.spec.repo_root,
            command=self.config.command,
            log_path=log_path,
            child_pid_path=self.config.spec.child_pid_path,
            latest_log_path=self.config.latest_log_path or self.config.spec.latest_log_path,
            env=self.config.child_env,
        )

    def _write_status(
        self,
        status: str,
        *,
        child: Optional[SupervisedChild] = None,
        run_id: str = "",
        log_path: str = "",
        last_exit_code: Any = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> None:
        payload_extra = {
            "last_recycle_reason": self.last_recycle_reason,
            **dict(self.config.status_extra_fields),
        }
        if extra:
            payload_extra.update(dict(extra))
        self.status.write(
            status,
            run_id=run_id,
            log_path=log_path,
            daemon_pid=child.pid if child is not None else None,
            restart_count=self.restart_count,
            last_exit_code=last_exit_code,
            extra=payload_extra,
        )

    def default_watchdog(self, child: SupervisedChild, current_status: Mapping[str, Any]) -> SupervisorLoopDecision:
        heartbeat = heartbeat_snapshot(
            current_status,
            stale_after_seconds=self.config.watchdog_stale_after_seconds,
        )
        if heartbeat.stale or (heartbeat.heartbeat_at is None and self.config.watchdog_stale_after_seconds <= 0):
            return SupervisorLoopDecision.recycle(
                "stale_heartbeat",
                detail=heartbeat.to_payload(),
            )
        try:
            threshold = float(
                current_status.get("worktree_no_child_stall_seconds")
                or self.config.status_static_fields.get("worktree_no_child_stall_seconds")
                or 0
            )
        except Exception:
            threshold = 0.0
        worker_status = worktree_phase_worker_status(current_status, child.pid, threshold)
        if worker_status.get("stalled_without_active_worker"):
            return SupervisorLoopDecision.recycle(
                "worktree_phase_without_active_child",
                detail=worker_status,
            )
        return SupervisorLoopDecision.keep_running()

    def watchdog_decision(self, child: SupervisedChild) -> SupervisorLoopDecision:
        current_status = read_json(self.config.spec.resolve(self.config.spec.status_path))
        decision = self.default_watchdog(child, current_status)
        if decision.action != "continue":
            return decision
        if self.watchdog_hook is not None:
            return self.watchdog_hook(self, child, current_status)
        return decision

    def run(self) -> SupervisorLoopResult:
        final_status = "stopped"
        while True:
            run_id = supervisor_run_id()
            child = launch_supervised_child(self._child_spec(run_id))
            log_path = self.config.spec.repo_relative(child.log_path)
            self.last_run_id = run_id
            self.last_log_path = log_path
            child_started_at = self.monotonic()
            self._write_status("starting", child=child, run_id=run_id, log_path=log_path)
            recycled = False

            while True:
                exit_code = _poll_child_exit(child)
                if exit_code is not None:
                    self.last_exit_code = exit_code
                    break
                self._write_status("running", child=child, run_id=run_id, log_path=log_path)
                if self.monotonic() - child_started_at >= self.config.watchdog_startup_grace_seconds:
                    decision = self.watchdog_decision(child)
                    if decision.action == "stop":
                        final_status = decision.status or "stopped"
                        self.last_recycle_reason = decision.reason
                        terminate_supervised_child(child, grace_seconds=self.config.stop_grace_seconds)
                        self.last_exit_code = wait_for_child_exit(child)
                        recycled = True
                        break
                    if decision.action == "recycle":
                        self.last_recycle_reason = decision.reason
                        self._write_status(
                            "recycling",
                            child=child,
                            run_id=run_id,
                            log_path=log_path,
                            extra={"watchdog_decision": decision.detail},
                        )
                        terminate_supervised_child(child, grace_seconds=self.config.stop_grace_seconds)
                        self.last_exit_code = wait_for_child_exit(child)
                        recycled = True
                        break
                self.sleep(max(0.01, min(float(self.config.heartbeat_seconds), float(self.config.poll_seconds))))

            clear_child_pid_file(child)
            self.restart_count += 1
            if self.config.max_restarts > 0 and self.restart_count >= self.config.max_restarts:
                final_status = "max_restarts_reached" if recycled else "child_exited"
                break
            self._write_status(
                "restarting",
                child=None,
                run_id=run_id,
                log_path=log_path,
                last_exit_code=self.last_exit_code,
            )
            self.sleep(self.config.restart_policy.delay_for_status(self.last_recycle_reason))

        self._write_status(
            final_status,
            child=None,
            run_id=self.last_run_id,
            log_path=self.last_log_path,
            last_exit_code=self.last_exit_code,
        )
        return SupervisorLoopResult(
            status=final_status,
            restart_count=self.restart_count,
            last_exit_code=self.last_exit_code,
            last_recycle_reason=self.last_recycle_reason,
            last_run_id=self.last_run_id,
            last_log_path=self.last_log_path,
        )


def build_supervisor_loop_arg_parser(
    *,
    description: str = "Run a reusable todo-daemon Python supervisor loop.",
) -> argparse.ArgumentParser:
    """Build a generic CLI parser for ``SupervisorLoop`` based supervisors."""

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--repo-root", default=_env("REPO_ROOT", "."))
    parser.add_argument("--name", default=_env("TODO_SUPERVISOR_NAME", "todo-daemon"))
    parser.add_argument("--schema", default=_env("TODO_SUPERVISOR_SCHEMA", "ipfs_datasets_py.todo_daemon"))
    parser.add_argument("--daemon-dir", default=_env("TODO_SUPERVISOR_DAEMON_DIR", ".daemon"))
    parser.add_argument("--status-path", default=_env("TODO_SUPERVISOR_STATUS_PATH", ".daemon/todo.status.json"))
    parser.add_argument("--progress-path", default=_env("TODO_SUPERVISOR_PROGRESS_PATH", ".daemon/todo.progress.json"))
    parser.add_argument(
        "--supervisor-status-path",
        default=_env("TODO_SUPERVISOR_STATUS_FILE", ".daemon/todo.supervisor.json"),
    )
    parser.add_argument("--supervisor-pid-path", default=_env("TODO_SUPERVISOR_PID_PATH", ".daemon/todo.supervisor.pid"))
    parser.add_argument("--child-pid-path", default=_env("TODO_SUPERVISOR_CHILD_PID_PATH", ".daemon/todo.child.pid"))
    parser.add_argument("--supervisor-out-path", default=_env("TODO_SUPERVISOR_OUT_PATH", ".daemon/todo.supervisor.out"))
    parser.add_argument("--ensure-status-path", default=_env("TODO_SUPERVISOR_ENSURE_STATUS_PATH", ".daemon/todo.ensure.json"))
    parser.add_argument("--ensure-check-path", default=_env("TODO_SUPERVISOR_ENSURE_CHECK_PATH", ".daemon/todo.ensure-check.json"))
    parser.add_argument("--supervisor-lock-path", default=_env("TODO_SUPERVISOR_LOCK_PATH", ".daemon/todo.supervisor.lock"))
    parser.add_argument("--latest-log-path", default=_env("TODO_SUPERVISOR_LATEST_LOG_PATH", ".daemon/todo.latest.log"))
    parser.add_argument("--log-prefix", default=_env("TODO_SUPERVISOR_LOG_PREFIX", "todo_supervised"))
    parser.add_argument("--heartbeat-seconds", type=float, default=float(_env("TODO_SUPERVISOR_HEARTBEAT_SECONDS", "30")))
    parser.add_argument("--poll-seconds", type=float, default=float(_env("TODO_SUPERVISOR_POLL_SECONDS", "1")))
    parser.add_argument("--watchdog-stale-after-seconds", type=float, default=float(_env("TODO_SUPERVISOR_STALE_AFTER_SECONDS", "180")))
    parser.add_argument("--watchdog-startup-grace-seconds", type=float, default=float(_env("TODO_SUPERVISOR_STARTUP_GRACE_SECONDS", "30")))
    parser.add_argument("--stop-grace-seconds", type=float, default=float(_env("TODO_SUPERVISOR_STOP_GRACE_SECONDS", "10")))
    parser.add_argument("--restart-backoff-seconds", type=float, default=float(_env("TODO_SUPERVISOR_RESTART_BACKOFF_SECONDS", "30")))
    parser.add_argument("--fast-restart-backoff-seconds", type=float, default=float(_env("TODO_SUPERVISOR_FAST_RESTART_BACKOFF_SECONDS", "2")))
    parser.add_argument("--max-restarts", type=int, default=int(_env("TODO_SUPERVISOR_MAX_RESTARTS", "0")))
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Environment variable to set for the supervised child. Can be repeated.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to supervise.")
    return parser


def _env_pairs(items: Sequence[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in items:
        key, sep, value = str(item).partition("=")
        if not sep or not key:
            raise ValueError(f"invalid --env item {item!r}; expected KEY=VALUE")
        env[key] = value
    return env


def supervisor_loop_config_from_args(args: argparse.Namespace) -> SupervisorLoopConfig:
    """Build ``SupervisorLoopConfig`` from generic parsed CLI args."""

    command_parts = [str(part) for part in getattr(args, "command", ()) if str(part)]
    if command_parts and command_parts[0] == "--":
        command_parts = command_parts[1:]
    command = tuple(command_parts)
    if not command:
        raise ValueError("supervisor loop command is required")
    repo_root = Path(args.repo_root).resolve()
    spec = ManagedDaemonSpec(
        name=str(args.name),
        schema=str(args.schema),
        repo_root=repo_root,
        daemon_dir=Path(args.daemon_dir),
        runner=command,
        status_path=Path(args.status_path),
        progress_path=Path(args.progress_path),
        supervisor_status_path=Path(args.supervisor_status_path),
        supervisor_pid_path=Path(args.supervisor_pid_path),
        child_pid_path=Path(args.child_pid_path),
        supervisor_out_path=Path(args.supervisor_out_path),
        ensure_status_path=Path(args.ensure_status_path),
        ensure_check_path=Path(args.ensure_check_path),
        supervisor_lock_path=Path(args.supervisor_lock_path),
        latest_log_path=Path(args.latest_log_path),
    )
    return SupervisorLoopConfig(
        spec=spec,
        command=command,
        log_prefix=str(args.log_prefix),
        restart_policy=RestartPolicy(
            restart_backoff_seconds=float(args.restart_backoff_seconds),
            fast_restart_backoff_seconds=float(args.fast_restart_backoff_seconds),
        ),
        heartbeat_seconds=float(args.heartbeat_seconds),
        poll_seconds=max(0.01, float(args.poll_seconds)),
        watchdog_stale_after_seconds=float(args.watchdog_stale_after_seconds),
        watchdog_startup_grace_seconds=float(args.watchdog_startup_grace_seconds),
        stop_grace_seconds=float(args.stop_grace_seconds),
        max_restarts=max(0, int(args.max_restarts)),
        child_env=_env_pairs(list(args.env or [])),
    )


def supervisor_loop_result_payload(result: SupervisorLoopResult) -> dict[str, Any]:
    """Return a JSON-serializable supervisor loop summary."""

    return {
        "status": result.status,
        "restart_count": result.restart_count,
        "last_exit_code": result.last_exit_code,
        "last_recycle_reason": result.last_recycle_reason,
        "last_run_id": result.last_run_id,
        "last_log_path": result.last_log_path,
    }


def run_supervisor_loop_cli(
    argv: Optional[Sequence[str]] = None,
    *,
    parser: Optional[argparse.ArgumentParser] = None,
    config_factory: SupervisorLoopConfigFactory = supervisor_loop_config_from_args,
) -> int:
    """Run the generic Python supervisor loop CLI."""

    parser = parser or build_supervisor_loop_arg_parser()
    try:
        config = config_factory(parser.parse_args(list(argv) if argv is not None else None))
    except ValueError as exc:
        parser.error(str(exc))
    result = SupervisorLoop(config).run()
    print(json.dumps(supervisor_loop_result_payload(result), indent=2, sort_keys=True))
    return 0 if result.last_exit_code in (None, 0) else int(result.last_exit_code)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for ``python -m ipfs_datasets_py.optimizers.todo_daemon.supervisor_loop``."""

    return run_supervisor_loop_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
