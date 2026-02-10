"""Legacy compatibility shims for municipal law database scrapers.

Preserves `ipfs_datasets_py.legal_scrapers.municipal_law_database_scrapers.*`.
Canonical implementations live under
`ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.*`.
"""

from __future__ import annotations

import pathlib
import warnings
from pkgutil import extend_path

warnings.warn(
    "ipfs_datasets_py.legal_scrapers.municipal_law_database_scrapers is deprecated; "
    "use ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers instead.",
    DeprecationWarning,
    stacklevel=2,
)

__path__ = extend_path(__path__, __name__)  # type: ignore[name-defined]

_canonical_dir = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "processors"
    / "legal_scrapers"
    / "municipal_law_database_scrapers"
)
if _canonical_dir.is_dir():
    __path__.append(str(_canonical_dir))  # type: ignore[attr-defined]
