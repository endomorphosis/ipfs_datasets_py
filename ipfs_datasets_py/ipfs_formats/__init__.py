"""Deprecated package for IPFS format helpers.

Canonical implementation:
  ipfs_datasets_py.data_transformation.ipfs_formats

This package remains to preserve backwards-compatible imports.
"""

from __future__ import annotations

import warnings
import importlib
from typing import Any, Dict, Tuple


warnings.warn(
    "ipfs_datasets_py.ipfs_formats is deprecated; "
    "use ipfs_datasets_py.data_transformation.ipfs_formats instead.",
    DeprecationWarning,
    stacklevel=2,
)


_EXPORTS: Dict[str, Tuple[str, str]] = {
  "ipfs_multiformats_py": ("ipfs_datasets_py.data_transformation.ipfs_formats", "ipfs_multiformats_py"),
  "get_cid": ("ipfs_datasets_py.data_transformation.ipfs_formats", "get_cid"),
}


def __getattr__(name: str) -> Any:
  target = _EXPORTS.get(name)
  if target is None:
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
  module_name, attr_name = target
  module = importlib.import_module(module_name)
  value = getattr(module, attr_name)
  globals()[name] = value
  return value


__all__ = list(_EXPORTS.keys())
