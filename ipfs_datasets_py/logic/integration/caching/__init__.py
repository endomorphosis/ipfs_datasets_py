"""
Caching subsystem for logic module.

Provides proof caching, IPFS-backed caching, and IPLD storage.

Components:
- ProofCache: LRU + TTL proof caching
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
