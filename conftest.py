"""Root conftest.py for the repository.

Adds the legal_data directory to sys.path early (via pytest_configure)
so that `from reasoner.X import ...` resolves correctly for the WS11
reasoner tests, even with --import-mode=importlib.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


def _truthy_env(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _ensure_pytest_plugin(module_name: str, package_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        pass

    if not _truthy_env("IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS", default=True):
        return False

    try:
        from ipfs_datasets_py.auto_installer import DependencyInstaller

        installer = DependencyInstaller(auto_install=True, verbose=_truthy_env("IPFS_INSTALL_VERBOSE"))
        if not installer.install_python_dependency(package_name):
            return False
        importlib.invalidate_caches()
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


_PYTEST_ASYNCIO_AVAILABLE = _ensure_pytest_plugin("pytest_asyncio", "pytest-asyncio")


def pytest_configure(config):  # noqa: ANN001
    """Inject the legal_data path before any test modules are collected."""
    _legal_data = Path(__file__).parent / "ipfs_datasets_py" / "processors" / "legal_data"
    _legal_data_str = str(_legal_data.resolve())
    if _legal_data_str not in sys.path:
        sys.path.insert(0, _legal_data_str)
    config.addinivalue_line("markers", "asyncio: run async tests with pytest-asyncio")
    if _PYTEST_ASYNCIO_AVAILABLE and not config.pluginmanager.hasplugin("asyncio"):
        try:
            plugin = importlib.import_module("pytest_asyncio.plugin")
            config.pluginmanager.register(plugin, "asyncio")
        except ValueError:
            pass
