"""Package dispatcher for reusable optimizer todo-daemon lifecycle commands."""

from __future__ import annotations

import argparse
import json
from typing import Optional, Sequence

from .registry import canonical_daemon_names, dispatcher_choices, load_daemon_main


def daemon_names() -> tuple[str, ...]:
    """Return stable names supported by the package-level lifecycle dispatcher."""

    return canonical_daemon_names()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dispatch reusable optimizer todo-daemon lifecycle and supervisor commands. "
            "Use '<daemon> --help' or 'supervise --help' for command-specific options."
        )
    )
    parser.add_argument(
        "daemon",
        nargs="?",
        choices=dispatcher_choices(),
        help="Daemon family to manage, 'supervise' for the generic supervisor, or 'list'.",
    )
    parser.add_argument("daemon_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.daemon is None:
        parser.print_help()
        return 2
    if args.daemon == "list":
        print(json.dumps({"daemons": list(daemon_names())}, indent=2, sort_keys=True))
        return 0
    if args.daemon == "supervise":
        from .supervisor_loop import run_supervisor_loop_cli

        return run_supervisor_loop_cli(args.daemon_args)
    return load_daemon_main(args.daemon)(args.daemon_args)


if __name__ == "__main__":
    raise SystemExit(main())
