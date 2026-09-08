"""Security package for ipfs_datasets_py.

EAAEF-122 session-poisoning detectors live here. Unknown names are forwarded
to the preserved historical module so ``SecurityManager`` imports keep working
after this package replaced that module path.
"""

from __future__ import annotations

from typing import Any

from . import _compat as _LEGACY_MODULE
from .external_session_poisoning import (
    SessionPoisoningError,
    inspect_imported_session,
)

__all__ = ("SessionPoisoningError", "inspect_imported_session")
__all__ += tuple(
    name for name in vars(_LEGACY_MODULE) if not name.startswith("_") and name not in __all__
)


def _legacy() -> Any:
    return _LEGACY_MODULE


def __getattr__(name: str) -> Any:
    try:
        return getattr(_legacy(), name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


def __dir__() -> list[str]:
    names = set(__all__)
    names.update(name for name in dir(_legacy()) if not name.startswith("_"))
    return sorted(names)
