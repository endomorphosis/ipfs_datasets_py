"""UI/UX IR formalization compilers and ontology contracts (UIR-069).

Lazy internal surface: importing this package does not load backends or
optional provers. Backend-private AST types stay behind leaf modules.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Final

UIUXIR_INTERNAL_PACKAGES_INTERFACE: Final = "UIUXIRInternalPackages@1"

__all__ = [
    "UIUXIR_INTERNAL_PACKAGES_INTERFACE",
    "compiler",
    "contracts",
    "dcec",
    "decompiler",
    "event_calculus",
    "flogic",
    "ontology",
    "roundtrip",
    "synthesis",
    "tdfol",
]

_LAZY_MODULES = frozenset(__all__) - {"UIUXIR_INTERNAL_PACKAGES_INTERFACE"}


def __getattr__(name: str) -> Any:
    if name in _LAZY_MODULES:
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
