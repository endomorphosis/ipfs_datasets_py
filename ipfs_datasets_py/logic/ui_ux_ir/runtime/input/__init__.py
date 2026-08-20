"""Runtime input adapters (conventional, speech, embodied) — UIR-069.

Adapters expose semantic events only; raw biometric/neural streams stay out of
the public adapter surface. Imports perform no device I/O.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Final

UIUXIR_INTERNAL_PACKAGES_INTERFACE: Final = "UIUXIRInternalPackages@1"

__all__ = [
    "UIUXIR_INTERNAL_PACKAGES_INTERFACE",
    "conventional",
    "embodied",
    "speech",
]

_LAZY_MODULES = frozenset(__all__) - {"UIUXIR_INTERNAL_PACKAGES_INTERFACE"}


def __getattr__(name: str) -> Any:
    if name in _LAZY_MODULES:
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
