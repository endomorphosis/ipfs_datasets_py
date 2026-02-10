"""Legacy file converter backends (deprecated).

Deprecated import path:
	ipfs_datasets_py.file_converter.backends

Canonical import path:
	ipfs_datasets_py.processors.file_converter.backends
"""

from __future__ import annotations

import importlib
import warnings
from typing import Any


warnings.warn(
		"ipfs_datasets_py.file_converter.backends is deprecated; use ipfs_datasets_py.processors.file_converter.backends",
		DeprecationWarning,
		stacklevel=2,
)

_canonical = importlib.import_module("ipfs_datasets_py.processors.file_converter.backends")

__all__ = list(getattr(_canonical, "__all__", []))


def __getattr__(name: str) -> Any:
		value = getattr(_canonical, name)
		globals()[name] = value
		return value
