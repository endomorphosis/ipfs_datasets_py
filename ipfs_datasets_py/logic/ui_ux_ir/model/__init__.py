"""UI/UX IR leaf model packages (UIR-069 internal surface).

Imports are offline and side-effect free: no network, process, hardware, or
optional solver action. Symbols are reviewed module-local contracts only.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Final

UIUXIR_INTERNAL_PACKAGES_INTERFACE: Final = "UIUXIRInternalPackages@1"

__all__ = [
    "UIUXIR_INTERNAL_PACKAGES_INTERFACE",
    "behavior",
    "bindings",
    "components",
    "experience",
    "layout",
    "modality",
]

_LAZY_MODULES = frozenset(__all__) - {"UIUXIR_INTERNAL_PACKAGES_INTERFACE"}


def __getattr__(name: str) -> Any:
    if name in _LAZY_MODULES:
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
