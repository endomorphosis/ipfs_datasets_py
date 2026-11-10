"""Writable user-data roots for legal scraper caches and generated output.

Generated files (harvest downloads, caches, corpora, learned rules, dataset
builds) must never be written inside the installed ``ipfs_datasets_py``
package.  Every writable default in ``legal_scrapers`` resolves through this
module so the location is consistent and configurable:

* ``user_data_dir(*parts, env=...)`` returns ``$env`` when that variable is
  set, otherwise ``~/.ipfs_datasets/<parts...>``.
* ``LEGAL_SCRAPERS_PACKAGE_DIR`` / ``is_inside_package`` let callers and tests
  assert that a writable path is outside the package tree.

Packaged seed and catalog files are still read from the package; only writes
are redirected.  This module has no heavy imports so it is safe to use from
standalone scripts and from the package ``__init__`` chain.
"""

from __future__ import annotations

import os
from pathlib import Path

LEGAL_SCRAPERS_PACKAGE_DIR = Path(__file__).resolve().parent
IPFS_DATASETS_PACKAGE_DIR = LEGAL_SCRAPERS_PACKAGE_DIR.parents[1]
DATA_DIR_NAME = ".ipfs_datasets"


def default_data_root() -> Path:
    """Base directory for all writable ipfs_datasets user data."""

    return (Path.home() / DATA_DIR_NAME).resolve()


def user_data_dir(*parts: str, env: str | None = None) -> Path:
    """Return a writable directory, honoring ``env`` when it is set."""

    if env:
        value = str(os.environ.get(env) or "").strip()
        if value:
            return Path(value).expanduser().resolve()
    root = default_data_root()
    for part in parts:
        root = root / part
    return root.resolve()


def is_inside_package(path: str | Path) -> bool:
    """True when ``path`` resolves inside the installed ``ipfs_datasets_py`` package."""

    try:
        Path(path).expanduser().resolve().relative_to(IPFS_DATASETS_PACKAGE_DIR)
    except ValueError:
        return False
    return True


__all__ = [
    "DATA_DIR_NAME",
    "IPFS_DATASETS_PACKAGE_DIR",
    "LEGAL_SCRAPERS_PACKAGE_DIR",
    "default_data_root",
    "is_inside_package",
    "user_data_dir",
]
