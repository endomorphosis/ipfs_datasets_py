"""Logic-port daemon lifecycle entry point built on reusable todo-daemon code."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Optional, Sequence

from .core import (
    ManagedDaemonSpec,
    check_daemon_health,
    ensure_daemon_running,
    stop_daemon,
)


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _boolish_env(name: str, default: str) -> str:
    value = _env(name, default).strip().lower()
    return "1" if value in {"1", "true", "yes", "on"} else "0"


def _repo_root(explicit: Optional[str] = None) -> Path:
    return Path(explicit or os.environ.get("REPO_ROOT") or Path.cwd()).resolve()


def logic_port_launch_env() -> Dict[str, str]:
    """Return the environment defaults the shell supervisor historically used."""

    provider = os.environ.get("LOGIC_PORT_PROVIDER", "")
    if provider:
        resolved_provider = provider
    elif os.environ.get("LOGIC_PORT_RESPECT_INHERITED_PROVIDER", "0") == "1":
        resolved_provider = os.environ.get("PROVIDER", "")
    else:
        resolved_provider = ""

    sandbox = _env("WORKTREE_CODEX_SANDBOX", _env("IPFS_DATASETS_PY_CODEX_SANDBOX", "danger-full-access"))
    return {
        "MODEL_NAME": _env("MODEL_NAME", "gpt-5.5"),
        "LOGIC_PORT_PROVIDER": provider,
        "PROVIDER": resolved_provider,
        "SLICE_MODE": _env("SLICE_MODE", "balanced"),
        "PROPOSAL_TRANSPORT": _env("PROPOSAL_TRANSPORT", "worktree"),
        "WORKTREE_EDIT_TIMEOUT_SECONDS": _env("WORKTREE_EDIT_TIMEOUT_SECONDS", "300"),
        "WORKTREE_STALE_AFTER_SECONDS": _env("WORKTREE_STALE_AFTER_SECONDS", "7200"),
        "WORKTREE_CODEX_SANDBOX": sandbox,
        "WORKTREE_ROOT": _env("WORKTREE_ROOT", "ipfs_datasets_py/.daemon/logic-port-worktrees"),
        "WORKTREE_REPAIR_ATTEMPTS": _env("WORKTREE_REPAIR_ATTEMPTS", "1"),
        "AUTO_COMMIT": _boolish_env("AUTO_COMMIT", "1"),
        "AUTO_COMMIT_STARTUP_DIRTY": _boolish_env("AUTO_COMMIT_STARTUP_DIRTY", "1"),
        "AUTO_COMMIT_BRANCH": _env("AUTO_COMMIT_BRANCH", "main"),
        "SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE": _env(
            "SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE",
            "1",
        ),
        "IPFS_DATASETS_PY_CODEX_SANDBOX": _env("IPFS_DATASETS_PY_CODEX_SANDBOX", "danger-full-access"),
        "IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE": _env("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE", "0"),
    }


def build_logic_port_spec(repo_root: Optional[str] = None) -> ManagedDaemonSpec:
    root = _repo_root(repo_root)
    daemon_dir = Path(_env("DAEMON_DIR", "ipfs_datasets_py/.daemon"))
    status_path = Path(_env("STATUS_PATH", f"{daemon_dir.as_posix()}/logic-port-daemon.status.json"))
    worktree_root = Path(_env("WORKTREE_ROOT", "ipfs_datasets_py/.daemon/logic-port-worktrees"))
    return ManagedDaemonSpec(
        name="logic-port",
        schema="ipfs_datasets_py.logic_port_daemon",
        repo_root=root,
        daemon_dir=daemon_dir,
        runner=("bash", "ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh"),
        status_path=status_path,
        progress_path=Path(_env("PROGRESS_PATH", f"{daemon_dir.as_posix()}/logic-port-daemon.progress.json")),
        result_log_path=Path(_env("RESULT_LOG_PATH", f"{daemon_dir.as_posix()}/logic-port-daemon.jsonl")),
        supervisor_status_path=Path(
            _env("SUPERVISOR_STATUS_PATH", f"{daemon_dir.as_posix()}/logic-port-daemon-supervisor.status.json")
        ),
        supervisor_pid_path=Path(
            _env("SUPERVISOR_PID_PATH", f"{daemon_dir.as_posix()}/logic-port-daemon-supervisor.pid")
        ),
        child_pid_path=Path(_env("CHILD_PID_PATH", f"{daemon_dir.as_posix()}/logic-port-daemon.pid")),
        supervisor_out_path=Path(
            _env("SUPERVISOR_OUT_PATH", f"{daemon_dir.as_posix()}/logic-port-daemon-supervisor.out")
        ),
        ensure_status_path=Path(
            _env("ENSURE_STATUS_PATH", f"{daemon_dir.as_posix()}/logic-port-daemon-ensure.status.json")
        ),
        ensure_check_path=Path(
            _env("CHECK_LOG_PATH", f"{daemon_dir.as_posix()}/logic-port-daemon-ensure-check.json")
        ),
        supervisor_lock_path=Path(
            _env("SUPERVISOR_LOCK_PATH", f"{daemon_dir.as_posix()}/logic-port-daemon-supervisor.lock")
        ),
        latest_log_path=Path(_env("LATEST_LOG_PATH", f"{daemon_dir.as_posix()}/logic-port-daemon-supervisor.latest.log")),
        task_board_path=Path(_env("TASK_BOARD_PATH", "docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md")),
        tmux_session_name=_env("TMUX_SESSION_NAME", "logic-port-daemon"),
        worktree_root=worktree_root,
        daemon_process_match_all=(
            "ipfs_datasets_py.optimizers.logic_port_daemon",
            f"--status-file {status_path.as_posix()}",
        ),
        llm_process_match_any=(
            "--ephemeral --json -",
            worktree_root.as_posix(),
            str(root / worktree_root),
        ),
        protected_ancestor_patterns=(
            "parser_daemon",
            "run_legal_parser_optimizer_daemon.sh",
            "ppd/daemon/ppd_supervisor.py",
            "ppd/daemon/ppd_daemon.py",
        ),
        launch_env=logic_port_launch_env(),
    )


def _json_print(payload) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the logic-port optimizer daemon lifecycle.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Print health JSON and exit 0 only when healthy.")
    check.add_argument("--repo-root", default=None)
    check.add_argument("--stale-after-seconds", type=float, default=float(_env("STALE_AFTER_SECONDS", "180")))

    ensure = subparsers.add_parser("ensure", help="Start the supervisor if the daemon is not healthy.")
    ensure.add_argument("--repo-root", default=None)
    ensure.add_argument("--stale-after-seconds", type=float, default=float(_env("STALE_AFTER_SECONDS", "180")))
    ensure.add_argument("--startup-wait-seconds", type=float, default=float(_env("ENSURE_STARTUP_WAIT_SECONDS", "20")))
    ensure.add_argument("--launch-mode", default=_env("ENSURE_LAUNCH_MODE", "nohup"), choices=("nohup", "tmux"))
    ensure.add_argument(
        "--tmux-restart-delay-seconds",
        type=int,
        default=int(_env("ENSURE_TMUX_RESTART_DELAY_SECONDS", "5")),
    )

    stop = subparsers.add_parser("stop", help="Stop the supervisor, daemon child, and owned worktree LLM calls.")
    stop.add_argument("--repo-root", default=None)
    stop.add_argument("--grace-seconds", type=float, default=float(_env("STOP_GRACE_SECONDS", "10")))
    stop.add_argument("--json", action="store_true", help="Print a machine-readable stop result.")

    spec = subparsers.add_parser("spec", help="Print the resolved reusable daemon spec.")
    spec.add_argument("--repo-root", default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    spec = build_logic_port_spec(getattr(args, "repo_root", None))
    if args.command == "check":
        health = check_daemon_health(spec, stale_after_seconds=args.stale_after_seconds)
        _json_print(health.payload)
        return health.exit_code
    if args.command == "ensure":
        result = ensure_daemon_running(
            spec,
            stale_after_seconds=args.stale_after_seconds,
            startup_wait_seconds=args.startup_wait_seconds,
            launch_mode=args.launch_mode,
            tmux_restart_delay_seconds=args.tmux_restart_delay_seconds,
        )
        _json_print(result.check)
        return result.exit_code
    if args.command == "stop":
        result = stop_daemon(spec, grace_seconds=args.grace_seconds)
        if args.json:
            _json_print(result.payload)
        elif result.payload.get("status") == "not_running":
            print("logic-port daemon supervisor is not running")
        return result.exit_code
    if args.command == "spec":
        _json_print(
            {
                "name": spec.name,
                "schema": spec.schema,
                "repo_root": str(spec.repo_root),
                "runner": list(spec.runner),
                "status_path": spec.repo_relative(spec.status_path),
                "progress_path": spec.repo_relative(spec.progress_path),
                "supervisor_status_path": spec.repo_relative(spec.supervisor_status_path),
                "supervisor_pid_path": spec.repo_relative(spec.supervisor_pid_path),
                "child_pid_path": spec.repo_relative(spec.child_pid_path),
                "task_board_path": spec.repo_relative(spec.task_board_path),
                "worktree_root": spec.repo_relative(spec.worktree_root),
                "tmux_session_name": spec.tmux_session_name,
                "launch_env": dict(spec.launch_env),
            }
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
