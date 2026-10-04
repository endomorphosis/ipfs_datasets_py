"""Compatibility shim for accelerate integration.

The canonical location is `ipfs_datasets_py.ml.accelerate_integration`.

This shim keeps legacy imports working without eagerly importing optional heavy
dependencies.
"""

from __future__ import annotations

import importlib
from typing import Any


_IMPL = importlib.import_module("ipfs_datasets_py.ml.accelerate_integration")


def __getattr__(name: str) -> Any:  # pragma: no cover
    return getattr(_IMPL, name)


def __dir__() -> list[str]:  # pragma: no cover
    return sorted(set(dir(_IMPL)))


__all__ = list(getattr(_IMPL, "__all__", []))
