"""
Backward compatibility shim for integration.caching.proof_cache

This module has been unified into common.proof_cache (Phase 4 - Cache Unification).
All imports from this location are redirected to the unified cache.

**DEPRECATED:** Import from ipfs_datasets_py.logic.common.proof_cache instead.

The unified cache provides all features of the integration cache while
maintaining a single codebase across all proof systems.

Migration:
    # Old (still works but deprecated)
    from ipfs_datasets_py.logic.integration.caching.proof_cache import ProofCache
    
    # New (recommended)
    from ipfs_datasets_py.logic.common.proof_cache import ProofCache
"""

import warnings
from typing import Any


__all__ = [
    "ProofCache",
    "CachedProof",
    "get_global_cache",
]


_DEPRECATION_MESSAGE = (
    "integration.caching.proof_cache is deprecated. "
    "Import from ipfs_datasets_py.logic.common.proof_cache instead. "
    "This shim will be removed in a future version."
)


def __getattr__(name: str) -> Any:
    if name not in {"ProofCache", "CachedProof", "get_global_cache"}:
        raise AttributeError(name)

    warnings.warn(
        _DEPRECATION_MESSAGE,
        DeprecationWarning,
        stacklevel=2,
    )

    from ...common.proof_cache import (
        ProofCache,
        CachedProofResult as CachedProof,
        get_global_cache,
    )

    if name == "ProofCache":
        return ProofCache
    if name == "CachedProof":
        return CachedProof
    return get_global_cache


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + __all__)
