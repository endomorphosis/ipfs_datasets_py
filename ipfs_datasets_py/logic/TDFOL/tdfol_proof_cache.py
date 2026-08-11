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
from dataclasses import dataclass
from typing import Any, Optional

# Import from unified location (DQK-065/066/067)
from ..common.proof_cache import (
    CachedProofResult as CachedProofEntry,
    LEGACY_PROOF_BACKENDS,
    LegacyProofBackend,
    ProofAuthorityJSONRewriteError,
    ProofCache as _CommonProofCache,
    ProofJSONCompatibilityError,
    ProofPublicationPolicyError,
    UnifiedProofAuthorityRepository,
    UnifiedProofShadowRepository,
    assert_compatibility_shims_import_unified_repository,
    assert_direct_json_persistence_forbidden,
    build_proof_authority_repository,
    build_proof_shadow_repository,
    get_global_cache,
    get_authority_repository,
    get_shadow_repository,
    legacy_json_persistence_allowed,
    set_authority_repository,
    set_shadow_repository,
)

TDFOL_LEGACY_BACKEND = LegacyProofBackend.TDFOL


class TDFOLProofCache(_CommonProofCache):
    """TDFOL façade over the unified proof cache (DQK-065 shadow-ready)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("shadow_backend", TDFOL_LEGACY_BACKEND.value)
        super().__init__(*args, **kwargs)


# Alias for backward compatibility
ProofCache = TDFOLProofCache


@dataclass
class TDFOLProofResult:
    """Backward-compatible proof result container for caching tests.

    This is distinct from `tdfol_prover.ProofResult` (which models a proof
    attempt). This type represents the cached outcome as used by legacy APIs.
    """

    is_proved: bool
    formula: Any
    method: str
    proof_steps: list
    proof_time: float

def get_global_proof_cache() -> ProofCache:
    """Get or create the global TDFOL proof cache.
    
    **DEPRECATED:** Use get_global_cache() from common.proof_cache instead.
    
    Returns:
        Global ProofCache instance
    """
    warnings.warn(
        "TDFOL.tdfol_proof_cache is deprecated. "
        "Import from ipfs_datasets_py.logic.common.proof_cache instead. "
        "This shim will be removed in a future version.",
        DeprecationWarning,
        stacklevel=2
    )

    return get_global_cache(maxsize=1000, ttl=3600)


def clear_global_proof_cache() -> None:
    """Clear the global TDFOL proof cache.

    This is a backward-compatibility shim. New code should prefer
    `ipfs_datasets_py.logic.common.proof_cache.get_global_cache().clear()`.
    """
    cache = get_global_proof_cache()
    cache.clear()


__all__ = [
    'TDFOLProofCache',
    'ProofCache',
    'CachedProofEntry',
    'get_global_proof_cache',
    'clear_global_proof_cache',
    'TDFOLProofResult',
    'LEGACY_PROOF_BACKENDS',
    'LegacyProofBackend',
    'TDFOL_LEGACY_BACKEND',
    'ProofAuthorityJSONRewriteError',
    'ProofJSONCompatibilityError',
    'ProofPublicationPolicyError',
    'UnifiedProofAuthorityRepository',
    'UnifiedProofShadowRepository',
    'assert_compatibility_shims_import_unified_repository',
    'assert_direct_json_persistence_forbidden',
    'build_proof_authority_repository',
    'build_proof_shadow_repository',
    'get_authority_repository',
    'get_shadow_repository',
    'legacy_json_persistence_allowed',
    'set_authority_repository',
    'set_shadow_repository',
]
