"""Optional logic integrations exposed under :mod:`ipfs_datasets_py.logic`.

Import policy:
- Importing :mod:`ipfs_datasets_py.logic.integrations` must be quiet and deterministic.
- Optional integrations are lazy-loaded on attribute access.

This package provides backwards-compatible shims for historical import paths.
"""

from __future__ import annotations

import importlib


_INTEGRATION_MODULES: tuple[str, ...] = (
    "enhanced_graphrag_integration",
    "unixfs_integration",
    "phase7_complete_integration",
)


def __getattr__(name: str):
    # Allow access to the integration modules themselves.
    if name in _INTEGRATION_MODULES:
        module = importlib.import_module(f".{name}", __name__)
        globals()[name] = module
        return module

    # Backward-compat: expose symbols that live inside any integration module,
    # but only import modules on-demand.
    for module_name in _INTEGRATION_MODULES:
        try:
            module = importlib.import_module(f".{module_name}", __name__)
        except Exception:
            # Missing optional deps should not warn/log at import time.
            continue

        if hasattr(module, name):
            value = getattr(module, name)
            globals()[name] = value
            return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(list(globals().keys()) + list(_INTEGRATION_MODULES)))
