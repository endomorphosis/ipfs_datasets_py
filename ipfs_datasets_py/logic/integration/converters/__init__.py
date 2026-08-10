"""Converters subsystem for the logic integration package.

The public converter classes stay import-compatible, but are loaded only when
their attributes are requested.  In particular, importing a lightweight
converter module must not transitively initialize the optional SymbolicAI
runtime through :mod:`modal_logic_extension`.

Components:
- DeonticLogicConverter: Deontic logic converter
- LogicTranslationCore: Logic translation utilities
- ModalLogicExtension: Modal logic extensions
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY_EXPORTS = {
    "DeonticLogicConverter": (
        ".deontic_logic_converter",
        "DeonticLogicConverter",
    ),
    "LogicTranslationCore": (
        ".logic_translation_core",
        "LogicTranslationCore",
    ),
    "ModalLogicExtension": (
        ".modal_logic_extension",
        "ModalLogicExtension",
    ),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    try:
        value = getattr(importlib.import_module(module_name, __name__), attribute_name)
    except ImportError:
        # Preserve the historical optional-dependency behavior: the package
        # export was ``None`` when its implementation could not be imported.
        value = None
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))

__all__ = [
    "DeonticLogicConverter",
    "LogicTranslationCore",
    "ModalLogicExtension",
]
