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
    CachedProofResult,
    LEGACY_PROOF_BACKENDS,
    LegacyProofBackend,
    ProofCache as _CommonProofCache,
    UnifiedProofShadowRepository,
    build_proof_shadow_repository,
    get_global_cache,
    get_shadow_repository,
    set_shadow_repository,
)

EXTERNAL_PROVERS_LEGACY_BACKEND = LegacyProofBackend.EXTERNAL_PROVERS


class ProofCache(_CommonProofCache):
    """External-prover façade over the unified proof cache (DQK-065 shadow-ready)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("shadow_backend", EXTERNAL_PROVERS_LEGACY_BACKEND.value)
        super().__init__(*args, **kwargs)


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
    'LEGACY_PROOF_BACKENDS',
    'LegacyProofBackend',
    'EXTERNAL_PROVERS_LEGACY_BACKEND',
    'UnifiedProofShadowRepository',
    'build_proof_shadow_repository',
    'get_shadow_repository',
    'set_shadow_repository',
]
