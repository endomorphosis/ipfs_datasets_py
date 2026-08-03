"""Compatibility shim: canonical registry lives in ``registry.py``.

PATLAW-003 merged the dual ``processor_registry`` / ``registry`` modules into
a single canonical :class:`~ipfs_datasets_py.processors.core.registry.ProcessorRegistry`.

This module re-exports the same symbols so historical imports such as::

    from ipfs_datasets_py.processors.core.processor_registry import (
        ProcessorRegistry,
        get_global_registry,
    )

continue to resolve to the canonical implementation and the **same** global
singleton (no dual live routers).

New code should import from ``ipfs_datasets_py.processors.core.registry`` or
``ipfs_datasets_py.processors.core``.
"""

from __future__ import annotations

# Re-export the canonical surface. Importing this module is supported for
# historical call sites; prefer ``processors.core.registry`` for new code.
from .registry import (  # noqa: F401
    EmptyProcessorSetError,
    ProcessorEntry,
    ProcessorRegistrationError,
    ProcessorRegistry,
    get_global_registry,
    reset_global_registry,
)

__all__ = [
    "ProcessorEntry",
    "ProcessorRegistry",
    "ProcessorRegistrationError",
    "EmptyProcessorSetError",
    "get_global_registry",
    "reset_global_registry",
]
