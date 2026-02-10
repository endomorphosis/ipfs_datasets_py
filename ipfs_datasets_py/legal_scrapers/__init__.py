"""Deprecated import path for legal scrapers.

Deprecated import path:
  ipfs_datasets_py.legal_scrapers

Canonical import path:
  ipfs_datasets_py.processors.legal_scrapers

This package is a lightweight compatibility shim that:
- emits a DeprecationWarning, and
- exposes the canonical implementation via re-exports, and
- extends the package search path so submodules continue to import.
"""

from __future__ import annotations

from pathlib import Path
import pkgutil
import warnings


warnings.warn(
    "ipfs_datasets_py.legal_scrapers is deprecated; use ipfs_datasets_py.processors.legal_scrapers instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Allow submodules (e.g., municipal_law_database_scrapers.*) to be resolved from
# the canonical processors package directory without duplicating files.
__path__ = pkgutil.extend_path(__path__, __name__)  # type: ignore[name-defined]

_pkg_root = Path(__file__).resolve().parent.parent
_processors_dir = _pkg_root / "processors" / "legal_scrapers"
if _processors_dir.is_dir():
    __path__.append(str(_processors_dir))  # type: ignore[attr-defined]

from ipfs_datasets_py.processors.legal_scrapers import *  # noqa: F401,F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
