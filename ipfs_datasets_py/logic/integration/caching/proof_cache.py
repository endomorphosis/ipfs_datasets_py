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
from typing import Optional

# Import from unified location
from ...common.proof_cache import (
    ProofCache,
    CachedProofResult as CachedProof,
    get_global_cache,
)

# Emit deprecation warning
warnings.warn(
    "integration.caching.proof_cache is deprecated. "
    "Import from ipfs_datasets_py.logic.common.proof_cache instead. "
    "This shim will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2
)

__all__ = [
    'ProofCache',
    'CachedProof',
    'get_global_cache',
]
