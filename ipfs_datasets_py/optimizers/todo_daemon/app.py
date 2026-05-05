"""Reusable module-style entry point for hook-driven todo daemons."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .engine import Proposal
from .runner import TodoDaemonHooks, TodoDaemonRunner


HooksFactory = Callable[[Any], TodoDaemonHooks]
ConfigFactory = Callable[[argparse.Namespace], Any]


@dataclass
class TodoDaemonRuntimeConfig:
    """Default runtime config consumed by :class:`TodoDaemonRunner`.

    Domain-specific daemons can use this directly for simple todo-board tasks,
    or provide a ``config_factory`` to ``run_todo_daemon_cli`` that returns a
    richer config object with the same runner-facing attributes.
    """

    repo_root: Path
    task_board: Path = Path("TODO.md")
    status_file: Path = Path(".daemon/todo-daemon.status.json")
    progress_file: Path = Path(".daemon/todo-daemon.progress.json")
    result_log: Path = Path(".daemon/todo-daemon.results.jsonl")
    apply: bool = True
    watch: bool = False
    iterations: int = 1
    interval_seconds: float = 0.0
    heartbeat_seconds: float = 30.0
    crash_backoff_seconds: float = 0.0
    revisit_blocked: bool = False

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.repo_root / path


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def build_todo_runner_arg_parser(
    *,
    description: str = "Run a reusable optimizer todo daemon.",
) -> argparse.ArgumentParser:
    """Build the standard module-level runner parser for todo daemons."""

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--repo-root", default=_env("REPO_ROOT", "."))
    parser.add_argument("--task-board", default=_env("TODO_DAEMON_TASK_BOARD", "TODO.md"))
    parser.add_argument("--status-file", default=_env("TODO_DAEMON_STATUS_FILE", ".daemon/todo-daemon.status.json"))
    parser.add_argument(
        "--progress-file",
        default=_env("TODO_DAEMON_PROGRESS_FILE", ".daemon/todo-daemon.progress.json"),
    )
    parser.add_argument(
        "--result-log",
        default=_env("TODO_DAEMON_RESULT_LOG", ".daemon/todo-daemon.results.jsonl"),
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not apply accepted task output.")
    parser.add_argument("--watch", action="store_true", help="Run repeatedly without user input.")
    parser.add_argument("--iterations", type=int, default=int(_env("TODO_DAEMON_ITERATIONS", "1")))
    parser.add_argument("--interval", type=float, default=float(_env("TODO_DAEMON_INTERVAL_SECONDS", "0")))
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=float(_env("TODO_DAEMON_HEARTBEAT_SECONDS", "30")),
    )
    parser.add_argument(
        "--crash-backoff-seconds",
        type=float,
        default=float(_env("TODO_DAEMON_CRASH_BACKOFF_SECONDS", "0")),
    )
    parser.add_argument("--revisit-blocked", action="store_true")
    return parser


def config_from_todo_runner_args(args: argparse.Namespace) -> TodoDaemonRuntimeConfig:
    """Build the default runner config from parsed CLI args."""

    return TodoDaemonRuntimeConfig(
        repo_root=Path(args.repo_root).resolve(),
        task_board=Path(args.task_board),
        status_file=Path(args.status_file),
        progress_file=Path(args.progress_file),
        result_log=Path(args.result_log),
        apply=not bool(args.dry_run),
        watch=bool(args.watch),
        iterations=max(0, int(args.iterations)),
        interval_seconds=max(0.0, float(args.interval)),
        heartbeat_seconds=max(0.0, float(args.heartbeat_seconds)),
        crash_backoff_seconds=max(0.0, float(args.crash_backoff_seconds)),
        revisit_blocked=bool(args.revisit_blocked),
    )


def todo_daemon_run_summary(proposals: Sequence[Proposal]) -> dict[str, Any]:
    """Return a compact machine-readable summary for a runner invocation."""

    latest = proposals[-1] if proposals else Proposal(summary="No daemon cycles ran.", failure_kind="no_cycles")
    return {
        "iterations": len(proposals),
        "valid": latest.valid,
        "latest": latest.to_dict(),
    }


def todo_daemon_exit_code(proposals: Sequence[Proposal]) -> int:
    """Return a process exit code for a generic todo-daemon run."""

    if not proposals:
        return 1
    latest = proposals[-1]
    if latest.failure_kind == "no_eligible_tasks":
        return 0
    if latest.failure_kind == "daemon_exception":
        return 1
    if latest.dry_run:
        return 0
    return 0 if latest.valid else 1


def run_todo_daemon_cli(
    argv: Optional[Sequence[str]],
    *,
    hooks_factory: HooksFactory,
    config_factory: ConfigFactory = config_from_todo_runner_args,
    parser: Optional[argparse.ArgumentParser] = None,
) -> int:
    """Parse args, run ``TodoDaemonRunner``, print JSON, and return an exit code."""

    parser = parser or build_todo_runner_arg_parser()
    args = parser.parse_args(argv)
    config = config_factory(args)
    hooks = hooks_factory(config)
    proposals = TodoDaemonRunner(config, hooks).run()
    print(json.dumps(todo_daemon_run_summary(proposals), indent=2, sort_keys=True))
    return todo_daemon_exit_code(proposals)
