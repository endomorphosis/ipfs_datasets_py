"""
IPFS Proof Storage for TDFOL

This module provides IPFS-based proof caching using the ipfs_backend_router.
Proofs are stored on IPFS and retrieved by CID for distributed access across
P2P network nodes.

Key Features:
- Store proof results on IPFS with automatic pinning
- Retrieve proofs by CID
- List cached proof CIDs
- Clear cache (unpin proofs)
- Content-addressed storage for deduplication

Architecture:
- Uses ipfs_backend_router.IPFSBackend protocol
- Serializes ProofResult to JSON→bytes
- Calls backend.add_bytes(data, pin=True) → CID
- Retrieves with backend.cat(cid) → bytes → ProofResult

Author: Phase 13 Week 2 Day 8 Implementation
Date: 2026-02-18
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import IPFS backend
try:
    from ipfs_datasets_py.ipfs_backend_router import (
        IPFSBackend,
        get_backend,
        set_default_ipfs_backend
    )
    IPFS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"IPFS backend not available: {e}")
    IPFS_AVAILABLE = False
    IPFSBackend = None
    get_backend = None
    set_default_ipfs_backend = None

# Try to import TDFOL prover types
try:
    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import Formula
    TDFOL_AVAILABLE = True
except ImportError as e:
    logger.warning(f"TDFOL modules not available: {e}")
    TDFOL_AVAILABLE = False
    ProofResult = None
    ProofStatus = None
    Formula = None


class IPFSProofStorage:
    """
    IPFS-based proof storage and caching.
    
    Provides content-addressed proof storage on IPFS for distributed access.
    Proofs are automatically pinned and can be retrieved by any node with
    access to the IPFS network.
    
    Example:
        >>> storage = IPFSProofStorage()
        >>> cid = storage.store_proof("∀x.P(x)", proof_result)
        >>> retrieved = storage.retrieve_proof(cid)
    """
    
    def __init__(self, backend: Optional[IPFSBackend] = None):
        """Initialize IPFS proof storage.
        
        Args:
            backend: Optional IPFSBackend instance. If not provided,
                    uses default backend from ipfs_backend_router.
        """
        if not IPFS_AVAILABLE:
            logger.warning("IPFS backend not available")
            self.backend = None
            self.available = False
            return
        
        self.backend = backend or get_backend()
        self.available = self.backend is not None
        
        # Track pinned CIDs for cache management
        self._pinned_cids: List[str] = []
        
        if not self.available:
            logger.warning("IPFS proof storage not available - no backend")
    
    def store_proof(
        self,
        formula: str,
        proof_result: ProofResult,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Store proof result on IPFS.
        
        Args:
            formula: Formula string that was proved
            proof_result: ProofResult object from prover
            metadata: Optional metadata to store with proof
            
        Returns:
            CID (Content Identifier) of stored proof, or None if failed
            
        Example:
            >>> cid = storage.store_proof(
            ...     "∀x.(P(x) → Q(x))",
            ...     proof_result,
            ...     metadata={"prover": "forward_chaining", "time_ms": 150}
            ... )
            >>> print(f"Proof stored at {cid}")
        """
        if not self.available:
            logger.error("Cannot store proof: IPFS backend not available")
            return None
        
        try:
            # Serialize proof result to dict
            proof_data = self._serialize_proof_result(proof_result)
            
            # Create storage object
            storage_obj = {
                "formula": formula,
                "proof_result": proof_data,
                "metadata": metadata or {},
                "version": "1.0"
            }
            
            # Convert to JSON bytes
            json_bytes = json.dumps(storage_obj, indent=2).encode('utf-8')
            
            # Store on IPFS with pinning
            cid = self.backend.add_bytes(json_bytes, pin=True)
            
            # Track pinned CID
            if cid not in self._pinned_cids:
                self._pinned_cids.append(cid)
            
            logger.info(f"Stored proof on IPFS: {cid} (formula: {formula})")
            return cid
            
        except Exception as e:
            logger.error(f"Failed to store proof on IPFS: {e}")
            return None
    
    def retrieve_proof(self, cid: str) -> Optional[ProofResult]:
        """Retrieve proof result from IPFS by CID.
        
        Args:
            cid: Content Identifier of stored proof
            
        Returns:
            ProofResult object, or None if not found or failed
            
        Example:
            >>> proof_result = storage.retrieve_proof("QmXxx...")
            >>> if proof_result:
            ...     print(f"Retrieved proof: {proof_result.proved}")
        """
        if not self.available:
            logger.error("Cannot retrieve proof: IPFS backend not available")
            return None
        
        try:
            # Retrieve bytes from IPFS
            json_bytes = self.backend.cat(cid)
            
            # Parse JSON
            storage_obj = json.loads(json_bytes.decode('utf-8'))
            
            # Extract proof data
            proof_data = storage_obj.get("proof_result", {})
            
            # Deserialize proof result
            proof_result = self._deserialize_proof_result(proof_data)
            
            logger.info(f"Retrieved proof from IPFS: {cid}")
            return proof_result
            
        except Exception as e:
            logger.error(f"Failed to retrieve proof from IPFS: {e}")
            return None
    
    def retrieve_with_metadata(self, cid: str) -> Optional[Dict[str, Any]]:
        """Retrieve proof with full metadata.
        
        Args:
            cid: Content Identifier of stored proof
            
        Returns:
            Dictionary containing formula, proof_result, and metadata
        """
        if not self.available:
            return None
        
        try:
            # Retrieve bytes from IPFS
            json_bytes = self.backend.cat(cid)
            
            # Parse and return full storage object
            storage_obj = json.loads(json_bytes.decode('utf-8'))
            
            # Deserialize proof_result
            proof_data = storage_obj.get("proof_result", {})
            storage_obj["proof_result"] = self._deserialize_proof_result(proof_data)
            
            return storage_obj
            
        except Exception as e:
            logger.error(f"Failed to retrieve proof with metadata: {e}")
            return None
    
    def list_cached_proofs(self) -> List[str]:
        """List all cached proof CIDs.
        
        Returns:
            List of CIDs for proofs stored by this instance
        """
        return self._pinned_cids.copy()
    
    def clear_cache(self) -> int:
        """Unpin all cached proofs.
        
        Returns:
            Number of proofs unpinned
        """
        if not self.available:
            return 0
        
        unpinned_count = 0
        
        for cid in self._pinned_cids:
            try:
                self.backend.unpin(cid)
                unpinned_count += 1
            except Exception as e:
                logger.warning(f"Failed to unpin {cid}: {e}")
        
        self._pinned_cids.clear()
        logger.info(f"Cleared {unpinned_count} proofs from cache")
        
        return unpinned_count
    
    def unpin_proof(self, cid: str) -> bool:
        """Unpin a specific proof.
        
        Args:
            cid: CID to unpin
            
        Returns:
            True if successfully unpinned, False otherwise
        """
        if not self.available:
            return False
        
        try:
            self.backend.unpin(cid)
            if cid in self._pinned_cids:
                self._pinned_cids.remove(cid)
            logger.info(f"Unpinned proof: {cid}")
            return True
        except Exception as e:
            logger.error(f"Failed to unpin proof: {e}")
            return False
    
    def _serialize_proof_result(self, proof_result: ProofResult) -> Dict[str, Any]:
        """Serialize ProofResult to dict for JSON storage."""
        # Handle ProofResult serialization
        result_dict = {
            "status": str(proof_result.status),
            "proved": proof_result.proved,
            "proof_steps": [],
            "time_ms": getattr(proof_result, 'time_ms', 0),
            "countermodel": None
        }
        
        # Serialize proof steps
        if hasattr(proof_result, 'proof_steps') and proof_result.proof_steps:
            for step in proof_result.proof_steps:
                step_dict = {
                    "formula": str(step.formula) if hasattr(step, 'formula') else str(step),
                    "rule": getattr(step, 'rule', None),
                    "premises": getattr(step, 'premises', [])
                }
                result_dict["proof_steps"].append(step_dict)
        
        # Serialize countermodel if present
        if hasattr(proof_result, 'countermodel') and proof_result.countermodel:
            # TODO: Implement countermodel serialization
            result_dict["countermodel"] = str(proof_result.countermodel)
        
        return result_dict
    
    def _deserialize_proof_result(self, proof_data: Dict[str, Any]) -> ProofResult:
        """Deserialize dict to ProofResult object."""
        if not TDFOL_AVAILABLE or not ProofResult:
            # Return a simple dict-based proxy if TDFOL not available
            class ProofResultProxy:
                def __init__(self, data):
                    self.__dict__.update(data)
            return ProofResultProxy(proof_data)
        
        # Create ProofResult from serialized data
        # Note: This is a simplified reconstruction
        # In production, would need more robust deserialization
        
        try:
            status = ProofStatus(proof_data.get("status", "unknown"))
        except:
            status = proof_data.get("status", "unknown")
        
        # Create basic ProofResult
        # Actual ProofResult constructor may vary
        result = type('ProofResult', (), {
            'status': status,
            'proved': proof_data.get("proved", False),
            'proof_steps': proof_data.get("proof_steps", []),
            'time_ms': proof_data.get("time_ms", 0),
            'countermodel': proof_data.get("countermodel")
        })()
        
        return result


# Convenience function for getting default storage instance
_default_storage: Optional[IPFSProofStorage] = None

def get_default_proof_storage() -> IPFSProofStorage:
    """Get the default IPFS proof storage instance.
    
    Returns:
        IPFSProofStorage instance
    """
    global _default_storage
    if _default_storage is None:
        _default_storage = IPFSProofStorage()
    return _default_storage
