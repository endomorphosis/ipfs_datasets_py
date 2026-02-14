"""
Caching subsystem for logic module.

Provides proof caching, IPFS-backed caching, and IPLD storage.

**Phase 4 - Cache Unification (2026-02-14):**
ProofCache has been unified into common.proof_cache. This module now provides
backward compatibility while IPFSProofCache and LogicIPLDStorage remain here.

Components:
- ProofCache: Unified proof cache (redirects to common.proof_cache)
- IPFSProofCache: IPFS-backed distributed caching
- LogicIPLDStorage: IPLD-based logic storage
"""

from .proof_cache import ProofCache, get_global_cache
from .ipfs_proof_cache import IPFSProofCache, get_global_ipfs_cache
from .ipld_logic_storage import LogicIPLDStorage

__all__ = [
    'ProofCache',
    'get_global_cache',
    'IPFSProofCache',
    'get_global_ipfs_cache',
    'LogicIPLDStorage',
]
