"""Bootstrap the vendored ipfs_datasets_py package from the repository root."""

from __future__ import annotations

from pathlib import Path


_INNER_PACKAGE = Path(__file__).resolve().parent / "ipfs_datasets_py"
if _INNER_PACKAGE.exists():
    inner = str(_INNER_PACKAGE)
    package_path = globals().get("__path__")
    if package_path is None:
        package_path = []
        __path__ = package_path
    if inner not in package_path:
        package_path.insert(0, inner)
