"""Canonical backend adapters for file conversion.

Canonical import path:
    ipfs_datasets_py.processors.file_converter.backends
"""

from __future__ import annotations

import importlib
import warnings
from typing import Any, Dict, Tuple


_EXPORTS: Dict[str, Tuple[str, str]] = {
    "MarkItDownBackend": (
        "ipfs_datasets_py.processors.file_converter.backends.markitdown_backend",
        "MarkItDownBackend",
    ),
    "OmniBackend": ("ipfs_datasets_py.processors.file_converter.backends.omni_backend", "OmniBackend"),
    "NativeBackend": ("ipfs_datasets_py.processors.file_converter.backends.native_backend", "NativeBackend"),
    "IPFSBackend": ("ipfs_datasets_py.processors.file_converter.backends.ipfs_backend", "IPFSBackend"),
    "get_ipfs_backend": (
        "ipfs_datasets_py.processors.file_converter.backends.ipfs_backend",
        "get_ipfs_backend",
    ),
    "IPFS_AVAILABLE": (
        "ipfs_datasets_py.processors.file_converter.backends.ipfs_backend",
        "IPFS_AVAILABLE",
    ),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if not target:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = importlib.import_module(module_name)

    value = getattr(module, attr_name)
    globals()[name] = value
    return value
