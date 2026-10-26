"""Hermetic loader for the world_municipal package under test.

The package is loaded by file location under a distinctive module name so
tests never trigger ``legal_scrapers/__init__``'s heavy import surface.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_PKG_DIR = (
    Path(__file__).resolve().parents[3]
    / "ipfs_datasets_py"
    / "processors"
    / "legal_scrapers"
    / "world_municipal"
)
_PKG_NAME = "wm_test_pkg"


def _ensure_pkg():
    if _PKG_NAME in sys.modules:
        return sys.modules[_PKG_NAME]
    spec = importlib.util.spec_from_file_location(
        _PKG_NAME,
        _PKG_DIR / "__init__.py",
        submodule_search_locations=[str(_PKG_DIR)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load world_municipal package at {_PKG_DIR}")
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[_PKG_NAME] = pkg
    spec.loader.exec_module(pkg)
    return pkg


@pytest.fixture(scope="session")
def wm():
    """The world_municipal package, loaded hermetically."""
    return _ensure_pkg()
