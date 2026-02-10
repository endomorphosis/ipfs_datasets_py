"""Legacy compatibility shims for legal scrapers.

This package preserves the historical import path `ipfs_datasets_py.legal_scrapers.*`
while canonical implementations live under `ipfs_datasets_py.processors.legal_scrapers.*`.
"""

from __future__ import annotations

import pathlib
import warnings
from pkgutil import extend_path

warnings.warn(
    "ipfs_datasets_py.legal_scrapers is deprecated; use ipfs_datasets_py.processors.legal_scrapers instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Allow legacy package name to find canonical submodules.
__path__ = extend_path(__path__, __name__)  # type: ignore[name-defined]

_canonical_dir = (
    pathlib.Path(__file__).resolve().parent.parent / "processors" / "legal_scrapers"
)
if _canonical_dir.is_dir():
    __path__.append(str(_canonical_dir))  # type: ignore[attr-defined]

# Re-export canonical package symbols (best-effort).
from ipfs_datasets_py.processors.legal_scrapers import *  # noqa: F401,F403
