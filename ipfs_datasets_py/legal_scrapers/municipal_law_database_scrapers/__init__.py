"""Deprecated import path for municipal law database scrapers.

Deprecated import path:
  ipfs_datasets_py.legal_scrapers.municipal_law_database_scrapers

Canonical import path:
  ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers

This is a compatibility shim. It extends the package search path so the actual
modules (e.g., hugging_face_pipeline.py, municode_scraper.py, _utils/*) continue
to be importable from the canonical location.
"""

from __future__ import annotations

from pathlib import Path
import pkgutil
import warnings


warnings.warn(
    "ipfs_datasets_py.legal_scrapers.municipal_law_database_scrapers is deprecated; "
    "use ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers instead.",
    DeprecationWarning,
    stacklevel=2,
)

__path__ = pkgutil.extend_path(__path__, __name__)  # type: ignore[name-defined]

_pkg_root = Path(__file__).resolve().parents[2]
_processors_dir = _pkg_root / "processors" / "legal_scrapers" / "municipal_law_database_scrapers"
if _processors_dir.is_dir():
    __path__.append(str(_processors_dir))  # type: ignore[attr-defined]

__all__: list[str] = []
