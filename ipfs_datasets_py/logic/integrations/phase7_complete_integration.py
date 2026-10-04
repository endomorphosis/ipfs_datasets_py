"""DEPRECATED compatibility shim.

Canonical location:
  ipfs_datasets_py.processors.specialized.graphrag.integration

This module remains to preserve older import paths.
"""

from __future__ import annotations

import importlib
import warnings


_TARGET = "ipfs_datasets_py.processors.specialized.graphrag.integration"
_WARNED = False


def _warn_once() -> None:
    global _WARNED
    if _WARNED:
        return
    _WARNED = True
    warnings.warn(
        "ipfs_datasets_py.logic.integrations.phase7_complete_integration is deprecated; "
        "use ipfs_datasets_py.processors.specialized.graphrag.integration instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def _load():
    return importlib.import_module(_TARGET)


def __getattr__(name: str):
    _warn_once()
    return getattr(_load(), name)


def __dir__():
    try:
        return sorted(set(globals().keys()) | set(dir(_load())))
    except Exception:
        return sorted(globals().keys())
