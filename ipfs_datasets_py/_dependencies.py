"""Backward-compatible access to the shared lazy dependency proxy."""

from __future__ import annotations

import importlib.util

from .lazy_dependencies import (
    DEFAULT_CRITICAL_DEPENDENCIES,
    DEFAULT_DEPENDENCY_MODULES,
    LazyDependencyProxy,
)


class _Dependencies(LazyDependencyProxy):
    """Compatibility name retained for existing imports."""


dependencies = _Dependencies(
    DEFAULT_DEPENDENCY_MODULES,
    critical_dependencies=DEFAULT_CRITICAL_DEPENDENCIES,
)

# Capability probes are side-effect free. Accessing a dependency through the
# proxy is what may trigger the configured lazy installer.
HAVE_IPFS = importlib.util.find_spec(
    "ipfs_datasets_py.ipfs_backend_router"
) is not None
HAVE_IPLD_CAR = importlib.util.find_spec("ipld_car") is not None
