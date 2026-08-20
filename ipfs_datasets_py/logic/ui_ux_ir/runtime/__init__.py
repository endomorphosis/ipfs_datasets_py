"""Runtime event envelope, fusion, state machine, mediator, receipts (UIR-069).

Importing this package is offline and side-effect free. Leaf modules load
lazily so optional executors / transports are never contacted at import time.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Final

UIUXIR_INTERNAL_PACKAGES_INTERFACE: Final = "UIUXIRInternalPackages@1"

__all__ = [
    "UIUXIR_INTERNAL_PACKAGES_INTERFACE",
    "events",
    "fusion",
    "input",
    "mediator",
    "receipts",
    "state_machine",
]

_LAZY_MODULES = frozenset(__all__) - {"UIUXIR_INTERNAL_PACKAGES_INTERFACE"}


def __getattr__(name: str) -> Any:
    if name in _LAZY_MODULES:
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
