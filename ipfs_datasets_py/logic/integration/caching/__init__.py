"""Caching subsystem for logic module.

Provides proof caching, IPFS-backed caching, and IPLD storage.

**Phase 4 - Cache Unification (2026-02-14):**
ProofCache has been unified into common.proof_cache. This module now provides
backward compatibility while IPFSProofCache and LogicIPLDStorage remain here.

Components:
- ProofCache: Unified proof cache (redirects to common.proof_cache)
- IPFSProofCache: IPFS-backed distributed caching
- LogicIPLDStorage: IPLD-based logic storage
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from ...common.proof_cache import ProofCache, get_global_cache

if TYPE_CHECKING:
    from .ipfs_proof_cache import IPFSProofCache, get_global_ipfs_cache
    from .ipld_logic_storage import LogicIPLDStorage

__all__ = [
    'ProofCache',
    'get_global_cache',
    'IPFSProofCache',
    'get_global_ipfs_cache',
    'LogicIPLDStorage',
]

_LAZY_EXPORTS = {
    "IPFSProofCache": (".ipfs_proof_cache", "IPFSProofCache"),
    "get_global_ipfs_cache": (".ipfs_proof_cache", "get_global_ipfs_cache"),
    "LogicIPLDStorage": (".ipld_logic_storage", "LogicIPLDStorage"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
