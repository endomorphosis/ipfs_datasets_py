"""Fail closed when the legal compiler resolves outside this checkout.

The check does not rewrite ``sys.path`` and does not retarget an editable
install. Callers that need this tree put it on the path themselves.
"""

from __future__ import annotations

import importlib
from pathlib import Path


class LogicTreePinError(RuntimeError):
    """The compiler, decompiler, or parser loaded from a different checkout."""


def workspace_root() -> Path:
    """Return ``external/ipfs_datasets`` for this file's checkout."""

    return Path(__file__).resolve().parents[3]


_MODULES = (
    ("compiler", "ipfs_datasets_py.logic.legal_ir.canonical_compiler"),
    ("decompiler", "ipfs_datasets_py.logic.legal_ir.canonical_decompiler"),
    ("parser", "ipfs_datasets_py.logic.deontic.utils.deontic_parser"),
)


def require_workspace_logic_tree() -> dict[str, str]:
    """Import the compiler, decompiler, and parser and require this checkout.

    Prints one resolved-path line. Raises ``LogicTreePinError`` when any
    module file sits outside ``workspace_root()``.
    """

    root = workspace_root()
    resolved: dict[str, str] = {}
    outside: list[str] = []
    for label, name in _MODULES:
        module = importlib.import_module(name)
        raw = getattr(module, "__file__", "") or ""
        path = Path(raw).resolve() if raw else Path()
        resolved[label] = str(path)
        if not path.is_file() or root not in path.parents:
            outside.append(f"{label}={path}")
    if outside:
        raise LogicTreePinError(
            "Legal compiler, decompiler, and parser must load from "
            f"{root}. Resolved outside that tree: {', '.join(outside)}. "
            "Put that tree first on PYTHONPATH, or point the editable install "
            "at it. This check does not rewrite the install."
        )
    print("logic tree pin " + " ".join(f"{label}={path}" for label, path in resolved.items()))
    return resolved
