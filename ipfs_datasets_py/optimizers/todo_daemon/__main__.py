"""Package dispatcher for reusable optimizer todo-daemon lifecycle commands."""

from __future__ import annotations

import argparse
import importlib
import json
from typing import Callable, Optional, Sequence


DaemonMain = Callable[[Optional[Sequence[str]]], int]

_CANONICAL_DAEMONS = {
    "logic-port": "ipfs_datasets_py.optimizers.todo_daemon.logic_port",
    "legal-parser": "ipfs_datasets_py.optimizers.todo_daemon.legal_parser",
}
_ALIASES = {
    **_CANONICAL_DAEMONS,
    "logic_port": _CANONICAL_DAEMONS["logic-port"],
    "legal_parser": _CANONICAL_DAEMONS["legal-parser"],
}


def daemon_names() -> tuple[str, ...]:
    """Return stable names supported by the package-level lifecycle dispatcher."""

    return tuple(sorted(_CANONICAL_DAEMONS))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dispatch reusable optimizer todo-daemon lifecycle commands. "
            "Use '<daemon> --help' for daemon-specific options."
        )
    )
    parser.add_argument(
        "daemon",
        nargs="?",
        choices=tuple(sorted((*_ALIASES, "list"))),
        help="Daemon family to manage, or 'list' to print supported daemon families.",
    )
    parser.add_argument("daemon_args", nargs=argparse.REMAINDER)
    return parser


def _load_main(name: str) -> DaemonMain:
    module_name = _ALIASES[name]
    module = importlib.import_module(module_name)
    main = getattr(module, "main", None)
    if not callable(main):
        raise SystemExit(f"{module_name} does not expose a callable main()")
    return main


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.daemon is None:
        parser.print_help()
        return 2
    if args.daemon == "list":
        print(json.dumps({"daemons": list(daemon_names())}, indent=2, sort_keys=True))
        return 0
    return _load_main(args.daemon)(args.daemon_args)


if __name__ == "__main__":
    raise SystemExit(main())
