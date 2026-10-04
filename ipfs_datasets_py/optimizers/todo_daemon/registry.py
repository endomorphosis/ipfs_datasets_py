"""Registry helpers for package-dispatched todo daemon families."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence


DaemonMain = Callable[[Optional[Sequence[str]]], int]


@dataclass(frozen=True)
class TodoDaemonRegistration:
    """Declarative package dispatcher registration for one daemon family."""

    name: str
    module: str
    aliases: tuple[str, ...] = ()

    def names(self) -> tuple[str, ...]:
        """Return the canonical name followed by aliases."""

        return (self.name, *self.aliases)


DEFAULT_DAEMON_REGISTRATIONS: tuple[TodoDaemonRegistration, ...] = (
    TodoDaemonRegistration(
        name="legal-parser",
        module="ipfs_datasets_py.optimizers.todo_daemon.legal_parser",
        aliases=("legal_parser",),
    ),
    TodoDaemonRegistration(
        name="logic-port",
        module="ipfs_datasets_py.optimizers.todo_daemon.logic_port",
        aliases=("logic_port",),
    ),
)


def canonical_daemon_names(
    registrations: Sequence[TodoDaemonRegistration] = DEFAULT_DAEMON_REGISTRATIONS,
) -> tuple[str, ...]:
    """Return stable canonical names supported by the package dispatcher."""

    return tuple(sorted(registration.name for registration in registrations))


def daemon_alias_map(
    registrations: Sequence[TodoDaemonRegistration] = DEFAULT_DAEMON_REGISTRATIONS,
) -> dict[str, str]:
    """Return a mapping of dispatcher name or alias to module path."""

    aliases: dict[str, str] = {}
    for registration in registrations:
        for name in registration.names():
            aliases[name] = registration.module
    return aliases


def dispatcher_choices(
    registrations: Sequence[TodoDaemonRegistration] = DEFAULT_DAEMON_REGISTRATIONS,
    *,
    extra_commands: Sequence[str] = ("list", "supervise"),
) -> tuple[str, ...]:
    """Return argparse choices for registered daemons plus dispatcher commands."""

    return tuple(sorted((*daemon_alias_map(registrations), *extra_commands)))


def resolve_daemon_module(
    name: str,
    registrations: Sequence[TodoDaemonRegistration] = DEFAULT_DAEMON_REGISTRATIONS,
) -> str:
    """Resolve a dispatcher name or alias to an importable module path."""

    aliases = daemon_alias_map(registrations)
    try:
        return aliases[name]
    except KeyError as exc:
        raise KeyError(f"unknown todo daemon family: {name}") from exc


def load_daemon_main(
    name: str,
    registrations: Sequence[TodoDaemonRegistration] = DEFAULT_DAEMON_REGISTRATIONS,
) -> DaemonMain:
    """Import a registered daemon module and return its callable ``main``."""

    module_name = resolve_daemon_module(name, registrations)
    module = importlib.import_module(module_name)
    main = getattr(module, "main", None)
    if not callable(main):
        raise SystemExit(f"{module_name} does not expose a callable main()")
    return main


def daemon_registry_payload(
    registrations: Sequence[TodoDaemonRegistration] = DEFAULT_DAEMON_REGISTRATIONS,
) -> Mapping[str, object]:
    """Return a machine-readable registry description."""

    return {
        "daemons": [
            {
                "name": registration.name,
                "module": registration.module,
                "aliases": list(registration.aliases),
            }
            for registration in sorted(registrations, key=lambda item: item.name)
        ]
    }
