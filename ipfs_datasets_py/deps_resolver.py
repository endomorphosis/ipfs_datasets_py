from __future__ import annotations

import importlib
from typing import Any


def deps_get(deps: object | None, key: str) -> Any | None:
    if deps is None or not key:
        return None
    getter = getattr(deps, "get_cached", None)
    if callable(getter):
        try:
            return getter(key)
        except Exception:
            return None
    if isinstance(deps, dict):
        return deps.get(key)
    return None


def deps_set(deps: object | None, key: str, value: Any) -> Any:
    if deps is None or not key:
        return value
    setter = getattr(deps, "set_cached", None)
    if callable(setter):
        try:
            return setter(key, value)
        except Exception:
            return value
    if isinstance(deps, dict):
        deps[key] = value
    return value


def resolve_module(
    module_name: str,
    *,
    deps: object | None = None,
    module_override: Any | None = None,
    cache_key: str | None = None,
) -> Any | None:
    """Resolve a Python module with optional injection + deps caching."""
    if module_override is not None:
        deps_set(deps, cache_key or f"pip::{module_name}", module_override)
        return module_override

    cached = deps_get(deps, cache_key or f"pip::{module_name}")
    if cached is not None:
        return cached

    try:
        module = importlib.import_module(module_name)
    except Exception:
        return None

    deps_set(deps, cache_key or f"pip::{module_name}", module)
    return module


def once(deps: object | None, key: str) -> bool:
    """Return True the first time per deps container, False thereafter."""
    if deps is None or not key:
        return True
    if deps_get(deps, key):
        return False
    deps_set(deps, key, True)
    return True
