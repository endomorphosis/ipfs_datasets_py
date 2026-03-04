"""Root conftest.py for the repository.

Adds the legal_data directory to sys.path early (via pytest_configure)
so that `from reasoner.X import ...` resolves correctly for the WS11
reasoner tests, even with --import-mode=importlib.
"""
from __future__ import annotations

import sys
from pathlib import Path


def pytest_configure(config):  # noqa: ANN001
    """Inject the legal_data path before any test modules are collected."""
    _legal_data = Path(__file__).parent / "ipfs_datasets_py" / "processors" / "legal_data"
    _legal_data_str = str(_legal_data.resolve())
    if _legal_data_str not in sys.path:
        sys.path.insert(0, _legal_data_str)
