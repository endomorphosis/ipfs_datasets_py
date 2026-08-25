"""
Backward compatibility shim for integration.caching.proof_cache

This module has been unified into common.proof_cache (Phase 4 - Cache Unification).
All imports from this location are redirected to the unified cache.

**DEPRECATED:** Import from ipfs_datasets_py.logic.common.proof_cache instead.
"""

import warnings
import time as _time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


__all__ = [
    "ProofCache",
    "CachedProof",
    "get_global_cache",
    "LEGACY_PROOF_BACKENDS",
    "LegacyProofBackend",
    "ProofAuthorityJSONRewriteError",
    "ProofJSONCompatibilityError",
    "ProofPublicationPolicyError",
    "UnifiedProofAuthorityRepository",
    "UnifiedProofShadowRepository",
    "assert_compatibility_shims_import_unified_repository",
    "assert_direct_json_persistence_forbidden",
    "build_proof_authority_repository",
    "build_proof_shadow_repository",
    "get_authority_repository",
    "get_shadow_repository",
    "legacy_json_persistence_allowed",
    "set_authority_repository",
    "set_shadow_repository",
    "INTEGRATION_CACHING_LEGACY_BACKEND",
]


from ...common.proof_cache import (  # noqa: E402
    LEGACY_PROOF_BACKENDS,
    LegacyProofBackend,
    ProofAuthorityJSONRewriteError,
    ProofJSONCompatibilityError,
    ProofPublicationPolicyError,
    UnifiedProofAuthorityRepository,
    UnifiedProofShadowRepository,
    assert_compatibility_shims_import_unified_repository,
    assert_direct_json_persistence_forbidden,
    build_proof_authority_repository,
    build_proof_shadow_repository,
    get_authority_repository,
    get_shadow_repository,
    legacy_json_persistence_allowed,
    set_authority_repository,
    set_shadow_repository,
)

INTEGRATION_CACHING_LEGACY_BACKEND = LegacyProofBackend.INTEGRATION_CACHING


@dataclass
class CachedProof:
    """Compat CachedProof dataclass matching the test API."""

    formula_hash: str
    prover: str
    result_data: Dict[str, Any]
    timestamp: float
    ttl: int = 3600
    hit_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Return True if this entry has exceeded its TTL."""
        if self.ttl == 0:
            return False
        return (_time.time() - self.timestamp) > self.ttl

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formula_hash": self.formula_hash,
            "prover": self.prover,
            "result_data": self.result_data,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
            "hit_count": self.hit_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CachedProof":
        return cls(
            formula_hash=data.get("formula_hash", ""),
            prover=data.get("prover", "unknown"),
            result_data=data.get("result_data", {}),
            timestamp=data.get("timestamp", _time.time()),
            ttl=data.get("ttl", 3600),
            hit_count=data.get("hit_count", 0),
            metadata=data.get("metadata", {}),
        )


def __getattr__(name: str) -> Any:
    if name not in {"ProofCache", "get_global_cache"}:
        raise AttributeError(name)

    warnings.warn(
        "integration.caching.proof_cache is deprecated. "
        "Import from ipfs_datasets_py.logic.common.proof_cache instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    from ...common.proof_cache import ProofCache, get_global_cache

    if name == "ProofCache":
        # Default shadow backend for this shim path.
        class _ShadowAwareProofCache(ProofCache):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                kwargs.setdefault("shadow_backend", "integration_caching")
                super().__init__(*args, **kwargs)

        return _ShadowAwareProofCache
    return get_global_cache


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + __all__)
