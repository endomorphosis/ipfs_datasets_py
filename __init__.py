"""Bootstrap the vendored ipfs_datasets_py package from the repository root."""

from __future__ import annotations

from pathlib import Path


_INNER_PACKAGE = Path(__file__).resolve().parent / "ipfs_datasets_py"
if _INNER_PACKAGE.exists():
    inner = str(_INNER_PACKAGE)
    if inner not in __path__:
        __path__.insert(0, inner)
