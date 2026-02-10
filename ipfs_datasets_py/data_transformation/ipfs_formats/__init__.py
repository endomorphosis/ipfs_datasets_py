"""Canonical IPFS format utilities.

This package is the canonical import location for IPFS-specific format helpers.

Import-safety:
The underlying implementation uses the optional third-party `multiformats` package.
To keep `import ipfs_datasets_py` and `import ipfs_datasets_py.data_transformation.ipfs_formats`
safe when optional dependencies are missing, this package exports symbols lazily.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Tuple


_EXPORTS: Dict[str, Tuple[str, str]] = {
    "ipfs_multiformats_py": ("ipfs_datasets_py.data_transformation.ipfs_formats.ipfs_multiformats", "ipfs_multiformats_py"),
    "get_cid": ("ipfs_datasets_py.data_transformation.ipfs_formats.ipfs_multiformats", "get_cid"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        # Provide a clearer error when the optional dependency is missing.
        if getattr(e, "name", None) == "multiformats":
            raise ImportError(
                "Optional dependency 'multiformats' is required for CID/multihash helpers. "
                "Install it to use ipfs_datasets_py.data_transformation.ipfs_formats."
            ) from e
        raise

    value = getattr(module, attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS.keys())
