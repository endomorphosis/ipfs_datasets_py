"""Reusable command-line entry points for optimizer todo-daemon lifecycle modules."""

from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Mapping, Optional, Sequence

from .core import (
    DaemonHealth,
    EnsureResult,
    ManagedDaemonSpec,
    StopResult,
    check_daemon_health,
    ensure_daemon_running,
    stop_daemon,
)


SpecBuilder = Callable[[Optional[str]], ManagedDaemonSpec]
SpecPayloadBuilder = Callable[[ManagedDaemonSpec], Mapping[str, Any]]
CheckFunction = Callable[..., Any]
EnsureFunction = Callable[..., Any]
StopFunction = Callable[..., Any]
RunFunction = Callable[[Optional[Sequence[str]]], int]


def json_print(payload: Mapping[str, Any]) -> None:
    print(json.dumps(dict(payload), indent=2, sort_keys=True))


def daemon_spec_payload(
    spec: ManagedDaemonSpec,
    *,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Return a stable JSON-serializable description of a managed daemon spec."""

    payload: dict[str, Any] = {
        "name": spec.name,
        "schema": spec.schema,
        "repo_root": str(spec.repo_root),
        "runner": list(spec.runner),
        "status_path": spec.repo_relative(spec.status_path),
        "progress_path": spec.repo_relative(spec.progress_path),
        "result_log_path": spec.repo_relative(spec.result_log_path),
        "supervisor_status_path": spec.repo_relative(spec.supervisor_status_path),
        "supervisor_pid_path": spec.repo_relative(spec.supervisor_pid_path),
        "child_pid_path": spec.repo_relative(spec.child_pid_path),
        "supervisor_out_path": spec.repo_relative(spec.supervisor_out_path),
        "ensure_status_path": spec.repo_relative(spec.ensure_status_path),
        "ensure_check_path": spec.repo_relative(spec.ensure_check_path),
        "supervisor_lock_path": spec.repo_relative(spec.supervisor_lock_path),
        "latest_log_path": spec.repo_relative(spec.latest_log_path),
        "task_board_path": spec.repo_relative(spec.task_board_path),
        "worktree_root": spec.repo_relative(spec.worktree_root),
        "tmux_session_name": spec.tmux_session_name,
        "daemon_process_match_all": list(spec.daemon_process_match_all),
        "llm_process_match_any": list(spec.llm_process_match_any),
        "protected_ancestor_patterns": list(spec.protected_ancestor_patterns),
        "launch_env": dict(spec.launch_env),
    }
    if extra:
        payload.update(dict(extra))
    return payload


def build_lifecycle_arg_parser(
    *,
    description: str,
    default_stale_after_seconds: float,
    default_startup_wait_seconds: float,
    default_launch_mode: str,
    launch_mode_choices: Sequence[str],
    restart_delay_flag: str,
    default_restart_delay_seconds: int,
    stop_description: str,
    restart_delay_dest: str = "restart_delay_seconds",
    default_stop_grace_seconds: float = 10.0,
    ensure_description: str = "Start the supervisor if the daemon is not healthy.",
    run_description: Optional[str] = None,
) -> argparse.ArgumentParser:
    """Build the standard ``check|ensure|stop|spec`` lifecycle parser, optionally with ``run``."""

    parser = argparse.ArgumentParser(description=description)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Print health JSON and exit 0 only when healthy.")
    check.add_argument("--repo-root", default=None)
    check.add_argument("--stale-after-seconds", type=float, default=default_stale_after_seconds)

    ensure = subparsers.add_parser("ensure", help=ensure_description)
    ensure.add_argument("--repo-root", default=None)
    ensure.add_argument("--stale-after-seconds", type=float, default=default_stale_after_seconds)
    ensure.add_argument("--startup-wait-seconds", type=float, default=default_startup_wait_seconds)
    ensure.add_argument("--launch-mode", default=default_launch_mode, choices=tuple(launch_mode_choices))
    ensure.add_argument(
        restart_delay_flag,
        dest=restart_delay_dest,
        type=int,
        default=default_restart_delay_seconds,
    )

    stop = subparsers.add_parser("stop", help=stop_description)
    stop.add_argument("--repo-root", default=None)
    stop.add_argument("--grace-seconds", type=float, default=default_stop_grace_seconds)
    stop.add_argument("--json", action="store_true", help="Print a machine-readable stop result.")

    spec_parser = subparsers.add_parser("spec", help="Print the resolved reusable daemon spec.")
    spec_parser.add_argument("--repo-root", default=None)

    if run_description:
        run = subparsers.add_parser("run", help=run_description)
        run.add_argument("daemon_args", nargs=argparse.REMAINDER)
    return parser


def _health_payload_and_exit(result: Any) -> tuple[dict[str, Any], int]:
    if isinstance(result, DaemonHealth):
        return result.payload, result.exit_code
    payload = dict(result)
    return payload, 0 if payload.get("alive") else 1


def _ensure_payload_check_and_exit(result: Any) -> tuple[dict[str, Any], dict[str, Any], int]:
    if isinstance(result, EnsureResult):
        return result.payload, result.check, result.exit_code
    payload = dict(result)
    check = payload.get("check") if isinstance(payload.get("check"), dict) else payload
    exit_code = 1 if payload.get("status") == "failed_to_start" else 0
    return payload, dict(check), exit_code


def _stop_payload_and_exit(result: Any) -> tuple[dict[str, Any], int]:
    if isinstance(result, StopResult):
        return result.payload, result.exit_code
    payload = dict(result)
    return payload, int(payload.get("exit_code") or 0)


def run_lifecycle_args(
    args: argparse.Namespace,
    *,
    build_spec: SpecBuilder,
    check_fn: CheckFunction = check_daemon_health,
    ensure_fn: EnsureFunction = ensure_daemon_running,
    stop_fn: StopFunction = stop_daemon,
    ensure_restart_kw: str = "tmux_restart_delay_seconds",
    spec_payload_builder: SpecPayloadBuilder = daemon_spec_payload,
    stop_not_running_message: str = "daemon supervisor is not running",
    run_fn: Optional[RunFunction] = None,
) -> int:
    """Run parsed lifecycle CLI args against a managed daemon spec."""

    if args.command == "run":
        if run_fn is None:
            return 2
        daemon_args = list(getattr(args, "daemon_args", ()) or ())
        if daemon_args and daemon_args[0] == "--":
            daemon_args = daemon_args[1:]
        return run_fn(daemon_args)

    spec = build_spec(getattr(args, "repo_root", None))
    if args.command == "check":
        payload, exit_code = _health_payload_and_exit(
            check_fn(spec, stale_after_seconds=args.stale_after_seconds)
        )
        json_print(payload)
        return exit_code
    if args.command == "ensure":
        restart_delay_seconds = getattr(args, "restart_delay_seconds", None)
        if restart_delay_seconds is None:
            restart_delay_seconds = getattr(args, "tmux_restart_delay_seconds")
        ensure_kwargs = {
            "stale_after_seconds": args.stale_after_seconds,
            "startup_wait_seconds": args.startup_wait_seconds,
            "launch_mode": args.launch_mode,
            ensure_restart_kw: restart_delay_seconds,
        }
        _payload, check, exit_code = _ensure_payload_check_and_exit(ensure_fn(spec, **ensure_kwargs))
        json_print(check)
        return exit_code
    if args.command == "stop":
        payload, exit_code = _stop_payload_and_exit(stop_fn(spec, grace_seconds=args.grace_seconds))
        if args.json:
            json_print(payload)
        elif payload.get("status") == "not_running":
            print(stop_not_running_message)
        return exit_code
    if args.command == "spec":
        json_print(spec_payload_builder(spec))
        return 0
    return 2


def run_lifecycle_cli(
    argv: Optional[Sequence[str]],
    *,
    parser: argparse.ArgumentParser,
    build_spec: SpecBuilder,
    check_fn: CheckFunction = check_daemon_health,
    ensure_fn: EnsureFunction = ensure_daemon_running,
    stop_fn: StopFunction = stop_daemon,
    ensure_restart_kw: str = "tmux_restart_delay_seconds",
    spec_payload_builder: SpecPayloadBuilder = daemon_spec_payload,
    stop_not_running_message: str = "daemon supervisor is not running",
    run_fn: Optional[RunFunction] = None,
) -> int:
    """Parse and run a standard todo-daemon lifecycle CLI."""

    return run_lifecycle_args(
        parser.parse_args(argv),
        build_spec=build_spec,
        check_fn=check_fn,
        ensure_fn=ensure_fn,
        stop_fn=stop_fn,
        ensure_restart_kw=ensure_restart_kw,
        spec_payload_builder=spec_payload_builder,
        stop_not_running_message=stop_not_running_message,
        run_fn=run_fn,
    )
