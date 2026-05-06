from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path.cwd()

from .core import ManagedDaemonSpec
from .implementation_daemon import (
    DEFAULT_TRACKS,
    TASK_HEADER_PREFIX,
    PortalTaskState,
    load_json_dict,
    process_command_line,
    process_is_running,
    utc_now,
    write_json_atomic,
    write_text_atomic,
)
from .supervisor_loop import SupervisorLoop, SupervisorLoopConfig, SupervisorLoopDecision
from .supervisor_runtime import RestartPolicy

logger = logging.getLogger("ipfs_datasets_py.optimizers.todo_daemon.implementation_supervisor")


@dataclass
class PortalSupervisorConfig:
    todo_path: Path
    state_path: Path
    strategy_path: Path
    events_path: Path
    state_dir: Path
    stale_seconds: float = 1800.0
    check_interval: float = 60.0
    max_restarts: int = 10
    daemon_interval: float = 300.0
    task_prefix: str = TASK_HEADER_PREFIX
    state_prefix: str = "portal"
    implement: bool = False
    implementation_command: str = ""
    implementation_timeout: float = 1800.0
    use_ephemeral_worktree: bool = True
    worktree_root: Path | None = None
    repo_root: Path = field(default_factory=Path.cwd)
    daemon_script_path: Path | None = None


class AdoptedManagedDaemonProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if process_is_running(self.pid):
            return None
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        if self.poll() is not None:
            return
        try:
            os.kill(self.pid, signal.SIGTERM)
            self.returncode = -signal.SIGTERM
        except ProcessLookupError:
            self.returncode = 0

    def kill(self) -> None:
        if self.poll() is not None:
            return
        try:
            os.kill(self.pid, signal.SIGKILL)
            self.returncode = -signal.SIGKILL
        except ProcessLookupError:
            self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.time() + timeout
        while True:
            polled = self.poll()
            if polled is not None:
                return polled
            if deadline is not None and time.time() >= deadline:
                raise subprocess.TimeoutExpired(cmd=["pid", str(self.pid)], timeout=timeout)
            time.sleep(0.2)


class PortalImplementationSupervisor:
    shared_supervisor_loop_class = SupervisorLoop
    shared_supervisor_loop_config_class = SupervisorLoopConfig
    shared_managed_daemon_spec_class = ManagedDaemonSpec

    def __init__(self, config: PortalSupervisorConfig) -> None:
        self.config = config
        self.restart_count = 0
        self.last_start_at: float | None = None

    def run_once(self) -> dict[str, Any]:
        state = PortalTaskState.load(self.config.state_path)
        stuck, reason = self.is_stuck(state, now_ts=time.time())
        if stuck:
            strategy = self.rewrite_strategy(state, reason)
            return {
                "stuck": True,
                "reason": reason,
                "strategy_generation": int(strategy.get("generation", 0)),
                "active_task_id": state.active_task_id,
            }
        self._record_event(
            "supervisor_check",
            {
                "stuck": False,
                "active_task_id": state.active_task_id,
                "completed_count": state.completed_count,
            },
        )
        return {
            "stuck": False,
            "active_task_id": state.active_task_id,
            "completed_count": state.completed_count,
        }

    def run_forever(self) -> None:
        loop = SupervisorLoop(
            self.build_supervisor_loop_config(),
            watchdog_hook=self._supervisor_loop_watchdog_decision,
        )
        result = loop.run()
        self.restart_count = result.restart_count
        self._record_event(
            "supervisor_loop_finished",
            {
                "status": result.status,
                "restart_count": result.restart_count,
                "last_exit_code": result.last_exit_code,
                "last_recycle_reason": result.last_recycle_reason,
                "last_run_id": result.last_run_id,
                "last_log_path": result.last_log_path,
            },
        )

    def build_supervisor_loop_config(self) -> SupervisorLoopConfig:
        command = tuple(self._build_daemon_command())
        prefix = self.config.state_prefix
        spec = ManagedDaemonSpec(
            name=f"{prefix}-implementation-daemon",
            schema="ipfs_datasets_py.todo_implementation_supervisor",
            repo_root=self.config.repo_root,
            daemon_dir=self.config.state_dir,
            runner=command,
            status_path=self.config.state_path,
            progress_path=self.config.state_path,
            result_log_path=self.config.events_path,
            task_board_path=self.config.todo_path,
            supervisor_status_path=self.config.state_dir / f"{prefix}_supervisor_status.json",
            supervisor_pid_path=self.config.state_dir / f"{prefix}_supervisor.pid",
            child_pid_path=self._managed_daemon_pid_path(),
            supervisor_out_path=self.config.state_dir / f"{prefix}_supervisor.out",
            ensure_status_path=self.config.state_dir / f"{prefix}_ensure_status.json",
            ensure_check_path=self.config.state_dir / f"{prefix}_ensure_check.json",
            supervisor_lock_path=self.config.state_dir / f"{prefix}_supervisor.lock",
            latest_log_path=self.config.state_dir / f"{prefix}_managed_daemon.latest.log",
            daemon_process_match_all=command,
            worktree_root=self.config.worktree_root,
        )
        return SupervisorLoopConfig(
            spec=spec,
            command=command,
            log_prefix=f"{prefix}_implementation_daemon",
            restart_policy=RestartPolicy(
                restart_backoff_seconds=max(0.0, float(self.config.check_interval)),
                fast_restart_backoff_seconds=min(2.0, max(0.0, float(self.config.check_interval))),
            ),
            heartbeat_seconds=max(0.01, float(self.config.check_interval)),
            poll_seconds=min(1.0, max(0.01, float(self.config.check_interval))),
            watchdog_stale_after_seconds=max(0.0, float(self.config.stale_seconds)),
            watchdog_startup_grace_seconds=max(0.0, float(self.config.stale_seconds)),
            stop_grace_seconds=15.0,
            max_restarts=max(0, int(self.config.max_restarts)),
            status_static_fields={
                "todo_path": str(self.config.todo_path),
                "state_path": str(self.config.state_path),
                "task_prefix": self.config.task_prefix,
                "state_prefix": self.config.state_prefix,
            },
        )

    def _supervisor_loop_watchdog_decision(
        self,
        _loop: SupervisorLoop,
        _child: Any,
        _current_status: dict[str, Any],
    ) -> SupervisorLoopDecision:
        state = PortalTaskState.load(self.config.state_path)
        stuck, reason = self.is_stuck(state, now_ts=time.time())
        if not stuck:
            return SupervisorLoopDecision.keep_running()
        self.rewrite_strategy(state, reason)
        return SupervisorLoopDecision.recycle(reason, detail={"active_task_id": state.active_task_id})

    def is_stuck(
        self,
        state: PortalTaskState,
        *,
        now_ts: float,
        ignore_progress_until_ts: float | None = None,
    ) -> tuple[bool, str]:
        heartbeat_age = self._age_seconds(state.heartbeat_at, now_ts)
        progress_age = self._age_seconds(state.last_progress_at, now_ts)
        stale = self.config.stale_seconds
        if state.active_task_id and heartbeat_age > stale:
            return True, f"heartbeat stale for active task {state.active_task_id}"
        if ignore_progress_until_ts is not None and now_ts < ignore_progress_until_ts:
            return False, ""
        if state.active_task_id and state.ready_count > 0 and progress_age > stale:
            return True, f"no progress on active task {state.active_task_id}"
        return False, ""

    def rewrite_strategy(self, state: PortalTaskState, reason: str) -> dict[str, Any]:
        strategy = self._load_strategy()
        active_track = state.active_task_track.strip().lower()
        focus_tracks = [str(item).lower() for item in strategy.get("focus_tracks", DEFAULT_TRACKS)]
        generation = int(strategy.get("generation", 0)) + 1
        deprioritized_tasks = list(dict.fromkeys([*strategy.get("deprioritized_tasks", []), state.active_task_id]))
        blocked_tasks = [str(item) for item in strategy.get("blocked_tasks", []) if str(item).strip()]

        if active_track and active_track in focus_tracks:
            focus_tracks = [track for track in focus_tracks if track != active_track] + [active_track]

        strategy.update(
            {
                "generation": generation,
                "focus_tracks": focus_tracks or DEFAULT_TRACKS,
                "blocked_tasks": blocked_tasks,
                "deprioritized_tasks": [task_id for task_id in deprioritized_tasks if task_id],
                "last_rewrite_at": utc_now(),
                "last_rewrite_reason": reason,
            }
        )
        write_json_atomic(self.config.strategy_path, strategy)
        self._record_event(
            "strategy_rewrite",
            {
                "reason": reason,
                "generation": generation,
                "active_task_id": state.active_task_id,
                "active_track": active_track,
            },
        )
        return strategy

    def _load_strategy(self) -> dict[str, Any]:
        defaults = {
            "generation": 0,
            "focus_tracks": DEFAULT_TRACKS,
            "blocked_tasks": [],
            "deprioritized_tasks": [],
            "last_rewrite_at": "",
            "last_rewrite_reason": "",
        }
        if not self.config.strategy_path.exists():
            return defaults
        payload = load_json_dict(self.config.strategy_path)
        if payload is None:
            logger.warning("Strategy file is missing or invalid JSON; using defaults: %s", self.config.strategy_path)
            return defaults.copy()
        return {**defaults, **payload}

    def _start_daemon(self) -> subprocess.Popen[str]:
        command = self._build_daemon_command()
        process = subprocess.Popen(command, cwd=self.config.repo_root, text=True)
        write_text_atomic(self._managed_daemon_pid_path(), f"{process.pid}\n")
        return process

    def _terminate(self, process: subprocess.Popen[str] | AdoptedManagedDaemonProcess) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
        pid_path = self._managed_daemon_pid_path()
        if pid_path.exists():
            pid_path.unlink()
        self._record_event("daemon_stop", {"returncode": process.returncode})

    def _build_daemon_command(self) -> list[str]:
        daemon_script_path = self.config.daemon_script_path
        if daemon_script_path is None:
            command = [sys.executable, "-m", "ipfs_datasets_py.optimizers.todo_daemon.implementation_daemon"]
        else:
            command = [sys.executable, str(daemon_script_path)]
        command.extend(
            [
                "--interval",
                str(self.config.daemon_interval),
                "--todo-path",
                str(self.config.todo_path),
                "--state-dir",
                str(self.config.state_dir),
                "--task-prefix",
                self.config.task_prefix,
                "--state-prefix",
                self.config.state_prefix,
            ]
        )
        if self.config.implement:
            command.append("--implement")
            command.extend(["--implementation-timeout", str(self.config.implementation_timeout)])
            if self.config.implementation_command:
                command.extend(["--implementation-command", self.config.implementation_command])
            if not self.config.use_ephemeral_worktree:
                command.append("--no-ephemeral-worktree")
            if self.config.worktree_root is not None:
                command.extend(["--worktree-root", str(self.config.worktree_root)])
        return command

    def _managed_daemon_pid_path(self) -> Path:
        return self.config.state_dir / f"{self.config.state_prefix}_managed_daemon.pid"

    def _adopt_existing_daemon(self) -> AdoptedManagedDaemonProcess | None:
        pid_path = self._managed_daemon_pid_path()
        if not pid_path.exists():
            return None
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            try:
                pid_path.unlink()
            except OSError:
                pass
            return None
        if not process_is_running(pid):
            try:
                pid_path.unlink()
            except OSError:
                pass
            return None
        command_line = process_command_line(pid)
        if not self._managed_daemon_matches_command_line(command_line):
            try:
                pid_path.unlink()
            except OSError:
                pass
            return None
        return AdoptedManagedDaemonProcess(pid)

    def _managed_daemon_matches_command_line(self, command_line: str) -> bool:
        daemon_script_path = self.config.daemon_script_path
        daemon_fragment = (
            Path(daemon_script_path).name
            if daemon_script_path is not None
            else "ipfs_datasets_py.optimizers.todo_daemon.implementation_daemon"
        )
        required_fragments = [
            daemon_fragment,
            "--state-dir",
            str(self.config.state_dir),
            "--state-prefix",
            self.config.state_prefix,
            "--todo-path",
            str(self.config.todo_path),
        ]
        if not all(fragment in command_line for fragment in required_fragments):
            return False
        has_implement_flag = "--implement" in command_line
        if self.config.implement != has_implement_flag:
            return False
        return True

    def _record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.config.events_path.parent.mkdir(parents=True, exist_ok=True)
        event = {"type": event_type, "timestamp": utc_now(), **payload}
        with self.config.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    @staticmethod
    def _age_seconds(timestamp: str, now_ts: float) -> float:
        if not timestamp:
            return float("inf")
        try:
            parsed = datetime.fromisoformat(timestamp)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, now_ts - parsed.timestamp())
        except ValueError:
            return float("inf")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Supervise the portal implementation backlog daemon")
    parser.add_argument("--once", action="store_true", help="Run one supervisor check and exit")
    parser.add_argument(
        "--todo-path",
        type=Path,
        default=Path("docs/211_SERVICE_NAVIGATION_PORTAL_TODO.md"),
        help="Machine-readable markdown backlog",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("data/portal_implementation/state"),
        help="Portal daemon state directory",
    )
    parser.add_argument("--stale-seconds", type=float, default=1800.0)
    parser.add_argument("--check-interval", type=float, default=60.0)
    parser.add_argument("--max-restarts", type=int, default=10)
    parser.add_argument("--daemon-interval", type=float, default=300.0)
    parser.add_argument(
        "--task-prefix",
        default=TASK_HEADER_PREFIX,
        help="Markdown heading prefix for tasks, for example '## PORTAL-' or '## AGENT-'",
    )
    parser.add_argument(
        "--state-prefix",
        default="portal",
        help="State file prefix inside --state-dir",
    )
    implement_group = parser.add_mutually_exclusive_group()
    implement_group.add_argument(
        "--implement",
        dest="implement",
        action="store_true",
        help="Allow the managed daemon to invoke the implementation agent",
    )
    implement_group.add_argument(
        "--no-implement",
        dest="implement",
        action="store_false",
        help="Only supervise backlog state; do not let the managed daemon invoke the implementation agent",
    )
    parser.set_defaults(implement=False)
    parser.add_argument(
        "--implementation-command",
        default="",
        help="Command used by the daemon for implementation. Defaults to codex exec --full-auto.",
    )
    parser.add_argument("--implementation-timeout", type=float, default=1800.0)
    parser.add_argument(
        "--no-ephemeral-worktree",
        action="store_true",
        help="Run implementation commands in the main checkout instead of isolated temporary git worktrees",
    )
    parser.add_argument(
        "--worktree-root",
        type=Path,
        default=None,
        help="Directory for temporary implementation worktrees",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    supervisor = PortalImplementationSupervisor(
        PortalSupervisorConfig(
            todo_path=args.todo_path,
            state_path=args.state_dir / f"{args.state_prefix}_task_state.json",
            strategy_path=args.state_dir / f"{args.state_prefix}_strategy.json",
            events_path=args.state_dir / f"{args.state_prefix}_supervisor_events.jsonl",
            state_dir=args.state_dir,
            stale_seconds=args.stale_seconds,
            check_interval=args.check_interval,
            max_restarts=args.max_restarts,
            daemon_interval=args.daemon_interval,
            task_prefix=args.task_prefix,
            state_prefix=args.state_prefix,
            implement=args.implement,
            implementation_command=args.implementation_command,
            implementation_timeout=args.implementation_timeout,
            use_ephemeral_worktree=args.implement and not args.no_ephemeral_worktree,
            worktree_root=args.worktree_root,
            repo_root=REPO_ROOT,
        )
    )
    if args.once:
        result = supervisor.run_once()
        logger.info("Portal implementation supervisor check complete: %s", result)
        return
    supervisor.run_forever()


if __name__ == "__main__":
    main()


TodoSupervisorConfig = PortalSupervisorConfig
TodoImplementationSupervisor = PortalImplementationSupervisor
