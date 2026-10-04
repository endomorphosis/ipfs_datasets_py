"""Omni-converter dependency access backed by the shared lazy resolver."""

from ipfs_datasets_py.lazy_dependencies import (
    DEFAULT_CRITICAL_DEPENDENCIES,
    DEFAULT_DEPENDENCY_MODULES,
    LazyDependencyProxy,
)


class _Dependencies(LazyDependencyProxy):
    """Compatibility name retained for standalone converter imports."""


dependencies = _Dependencies(
    DEFAULT_DEPENDENCY_MODULES,
    critical_dependencies=(*DEFAULT_CRITICAL_DEPENDENCIES, "magic"),
)
