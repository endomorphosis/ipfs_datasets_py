"""
Backward compatibility shim for TDFOL.tdfol_proof_cache

This module has been unified into common.proof_cache (Phase 4 - Cache Unification).
All imports from this location are redirected to the unified cache.

**DEPRECATED:** Import from ipfs_datasets_py.logic.common.proof_cache instead.

The unified cache provides TDFOL-specific features while maintaining a single
codebase across all proof systems.

Migration:
    # Old (still works but deprecated)
    from ipfs_datasets_py.logic.TDFOL.tdfol_proof_cache import TDFOLProofCache
    
    # New (recommended)
    from ipfs_datasets_py.logic.common.proof_cache import ProofCache as TDFOLProofCache
"""

import warnings
from typing import Optional

# Import from unified location
from ..common.proof_cache import (
    ProofCache,
    CachedProofResult as CachedProofEntry,
    get_global_cache,
)

# Alias for backward compatibility
TDFOLProofCache = ProofCache

# Global instance for TDFOL
_global_proof_cache: Optional[ProofCache] = None


def get_global_proof_cache() -> ProofCache:
    """Get or create the global TDFOL proof cache.
    
    **DEPRECATED:** Use get_global_cache() from common.proof_cache instead.
    
    Returns:
        Global ProofCache instance
    """
    global _global_proof_cache
    if _global_proof_cache is None:
        _global_proof_cache = ProofCache(maxsize=1000, ttl=3600)
    
    warnings.warn(
        "TDFOL.tdfol_proof_cache is deprecated. "
        "Import from ipfs_datasets_py.logic.common.proof_cache instead. "
        "This shim will be removed in a future version.",
        DeprecationWarning,
        stacklevel=2
    )
    
    return _global_proof_cache


__all__ = [
    'TDFOLProofCache',
    'CachedProofEntry',
    'get_global_proof_cache',
]
