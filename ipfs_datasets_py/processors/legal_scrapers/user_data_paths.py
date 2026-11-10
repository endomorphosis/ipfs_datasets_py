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


WORK_ROOT_ENV = "IPFS_DATASETS_LEGAL_WORK_ROOT"


def legal_work_root() -> Path:
    """Writable root that mirrors the legal_scrapers tree for script-local outputs."""

    return user_data_dir("legal_scrapers_work", env=WORK_ROOT_ENV)


def _relative_to_legal_scrapers(path: Path) -> Path:
    try:
        return path.relative_to(LEGAL_SCRAPERS_PACKAGE_DIR)
    except ValueError:
        parts = path.parts
        idx = max((i for i, part in enumerate(parts) if part == "legal_scrapers"), default=None)
        return Path(*parts[idx + 1 :]) if idx is not None else Path(path.name)


def work_mirror_path(src: str | Path) -> Path:
    """Mirror of a package script path under ``legal_work_root()``.

    Campaign scripts used ``Path(__file__).parent / "out"`` (and similar) for
    generated files; mapping ``__file__`` through this keeps their relative
    layout (including sibling-campaign references) while moving every
    generated file out of the package.
    """

    return legal_work_root() / _relative_to_legal_scrapers(Path(src).resolve())


def source_path_for_mirror(path: str | Path, src: str | Path) -> Path:
    """Inverse of ``work_mirror_path`` relative to script ``src`` (for code files)."""

    path = Path(path)
    mirror = work_mirror_path(src)
    source = Path(src).resolve()
    for _ in range(len(mirror.parts)):
        try:
            return source.joinpath(path.relative_to(mirror)).resolve()
        except ValueError:
            mirror, source = mirror.parent, source.parent
    return path


__all__ = [
    "WORK_ROOT_ENV",
    "legal_work_root",
    "source_path_for_mirror",
    "work_mirror_path",
    "DATA_DIR_NAME",
    "IPFS_DATASETS_PACKAGE_DIR",
    "LEGAL_SCRAPERS_PACKAGE_DIR",
    "default_data_root",
    "is_inside_package",
    "user_data_dir",
]
