"""Feature / optional-dependency detection utilities.

This module is used by `ipfs_datasets_py.logic.*` to probe optional dependencies
without importing them (and without triggering import-time side effects).

Key behavior:
- Uses `importlib.util.find_spec` to probe availability.
- Stays quiet by default (no warnings/logging at import time).
- Optional notices are gated by `IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS`.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import warnings

from functools import lru_cache
from types import ModuleType
from typing import Any


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def warn_optional_imports_enabled() -> bool:
    """True when optional-import warnings are enabled (default: False)."""

    return _truthy(os.environ.get("IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS"))


def minimal_imports_enabled() -> bool:
    """True when minimal/hermetic imports mode is enabled."""

    return _truthy(os.environ.get("IPFS_DATASETS_PY_MINIMAL_IMPORTS")) or _truthy(
        os.environ.get("IPFS_DATASETS_PY_BENCHMARK")
    )


def optional_import_notice(message: str, *, category: type[Warning] = ImportWarning) -> None:
    """Optionally emit a warning about missing optional dependencies."""

    if not warn_optional_imports_enabled():
        return

    try:
        warnings.warn(message, category=category, stacklevel=2)
    except Exception:
        pass


@lru_cache(maxsize=1024)
def _spec_exists(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def clear_feature_detection_cache() -> None:
    """Clear internal `find_spec` result cache."""

    _spec_exists.cache_clear()


def is_module_available(
    module_name: str,
    *,
    respect_minimal_imports: bool = True,
) -> bool:
    """Return True if `module_name` appears importable.

    This probes importability without importing the target module.
    """

    if respect_minimal_imports and minimal_imports_enabled():
        return False

    importlib.invalidate_caches()
    return _spec_exists(module_name)


def require_module(
    module_name: str,
    *,
    extra: str | None = None,
    message: str | None = None,
    respect_minimal_imports: bool = True,
) -> None:
    """Raise ImportError with a helpful message if `module_name` is unavailable."""

    if is_module_available(module_name, respect_minimal_imports=respect_minimal_imports):
        return

    if message is None:
        if extra:
            message = f"Optional dependency '{module_name}' is required. Install via: pip install {extra}"
        else:
            message = f"Optional dependency '{module_name}' is required."

    raise ImportError(message)


def import_optional_module(
    module_name: str,
    *,
    default: Any = None,
    notice: str | None = None,
    respect_minimal_imports: bool = True,
) -> ModuleType | Any:
    """Best-effort import of an optional module.

    Returns `default` when unavailable.
    """

    if respect_minimal_imports and minimal_imports_enabled():
        return default

    try:
        return importlib.import_module(module_name)
    except Exception as exc:
        if notice:
            optional_import_notice(f"{notice}: {exc}")
        return default


class FeatureDetector:
    """Backwards-compatible feature detector facade.

    Historically this module provided a `FeatureDetector` class with many
    `has_*()` methods. To preserve compatibility while improving import hygiene,
    those methods now use `find_spec`-based probing.
    """

    @classmethod
    def has_symbolicai(cls) -> bool:
        return is_module_available("symbolicai")

    @classmethod
    def has_z3(cls) -> bool:
        return is_module_available("z3")

    @classmethod
    def has_spacy(cls) -> bool:
        return is_module_available("spacy")

    @classmethod
    def has_spacy_model(cls, model: str = "en_core_web_sm") -> bool:
        # spaCy models are typically installable as importable packages.
        return is_module_available(model)

    @classmethod
    def has_xgboost(cls) -> bool:
        return is_module_available("xgboost")

    @classmethod
    def has_lightgbm(cls) -> bool:
        return is_module_available("lightgbm")

    @classmethod
    def has_ml_models(cls) -> bool:
        return cls.has_xgboost() or cls.has_lightgbm()

    @classmethod
    def has_ipfs(cls) -> bool:
        return is_module_available("ipfshttpclient")


__all__ = [
    "FeatureDetector",
    "warn_optional_imports_enabled",
    "minimal_imports_enabled",
    "optional_import_notice",
    "clear_feature_detection_cache",
    "is_module_available",
    "require_module",
    "import_optional_module",
]
