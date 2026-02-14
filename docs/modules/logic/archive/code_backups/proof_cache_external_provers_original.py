"""
Backward compatibility shim for external_provers.proof_cache

This module has been unified into common.proof_cache (Phase 4 - Cache Unification).
All imports from this location are redirected to the unified cache.

**DEPRECATED:** Import from ipfs_datasets_py.logic.common.proof_cache instead.

The unified cache provides:
- Single implementation across all proof systems
- Consistent behavior and API
- ~40% code reduction
- Easier maintenance

Migration:
    # Old (still works but deprecated)
    from ipfs_datasets_py.logic.external_provers.proof_cache import ProofCache
    
    # New (recommended)
    from ipfs_datasets_py.logic.common.proof_cache import ProofCache
"""

import warnings

# Import from unified location
from ..common.proof_cache import (
    ProofCache,
    CachedProofResult,
    get_global_cache,
)

# Emit deprecation warning
warnings.warn(
    "external_provers.proof_cache is deprecated. "
    "Import from ipfs_datasets_py.logic.common.proof_cache instead. "
    "This shim will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2
)

__all__ = [
    'ProofCache',
    'CachedProofResult',
    'get_global_cache',
]
