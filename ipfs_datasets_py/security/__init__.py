"""Security package for ipfs_datasets_py.

EAAEF-122 session-poisoning detectors live here.  Unknown names are forwarded
lazily to the historical ``security.py`` module so ``SecurityManager`` imports
keep working after this package shadowed that module path.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

from .external_session_poisoning import (
    SessionPoisoningError,
    inspect_imported_session,
)

__all__ = ("SessionPoisoningError", "inspect_imported_session")

_LEGACY_MODULE: Any = None


def _legacy() -> Any:
    global _LEGACY_MODULE
    if _LEGACY_MODULE is None:
        path = Path(__file__).resolve().parent.parent / "security.py"
        spec = spec_from_file_location("ipfs_datasets_py._legacy_security_module", path)
        if spec is None or spec.loader is None:
            raise ImportError("legacy ipfs_datasets_py.security module is absent")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        _LEGACY_MODULE = module
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
