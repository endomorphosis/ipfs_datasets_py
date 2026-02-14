"""
TDFOL Proof Cache - Caching layer for theorem proving results

This module provides proof result caching using CID-based content addressing
for O(1) lookups. Integrates with the existing proof cache infrastructure.

Features:
- CID-based formula hashing
- Proof result caching
- TTL-based expiration
- Thread-safe operations
- Statistics tracking
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from threading import RLock
from typing import Dict, List, Optional, Set, Tuple

from .tdfol_core import Formula
from .tdfol_prover import ProofResult, ProofStatus

logger = logging.getLogger(__name__)

# Try to import CID utils for content addressing
try:
    from ipfs_datasets_py.utils.cid_utils import cid_for_obj
    HAVE_CID_UTILS = True
except ImportError:
    HAVE_CID_UTILS = False
    logger.warning("CID utils not available, using fallback hashing")


@dataclass
class CachedProofEntry:
    """Entry in the proof cache."""
    
    formula_str: str
    result: ProofResult
    timestamp: float
    hit_count: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'formula_str': self.formula_str,
            'result_status': self.result.status.value,
            'result_proved': self.result.is_proved(),
            'result_time_ms': self.result.time_ms,
            'result_method': self.result.method,
            'timestamp': self.timestamp,
            'hit_count': self.hit_count,
        }


class TDFOLProofCache:
    """Cache for TDFOL proof results using CID-based addressing."""
    
    def __init__(self, maxsize: int = 1000, ttl: int = 3600):
        """
        Initialize proof cache.
        
        Args:
            maxsize: Maximum number of cached proofs
            ttl: Time-to-live in seconds (default: 1 hour)
        """
        self.maxsize = maxsize
        self.ttl = ttl
        self.cache: Dict[str, CachedProofEntry] = {}
        self.lock = RLock()
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'total_requests': 0,
        }
    
    def _formula_to_cid(self, formula: Formula, axioms: Optional[List[Formula]] = None) -> str:
        """
        Convert formula (and optional axioms) to CID.
        
        Args:
            formula: Formula to hash
            axioms: Optional list of axioms used in proof
            
        Returns:
            CID string for the proof problem
        """
        # Create canonical representation
        obj = {
            'formula': str(formula),
            'axioms': [str(ax) for ax in (axioms or [])],
        }
        
        if HAVE_CID_UTILS:
            try:
                return cid_for_obj(obj)
            except Exception as e:
                logger.debug(f"CID generation failed, using fallback: {e}")
        
        # Fallback: use SHA256 hash
        content = json.dumps(obj, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get(self, formula: Formula, axioms: Optional[List[Formula]] = None) -> Optional[ProofResult]:
        """
        Get cached proof result.
        
        Args:
            formula: Formula to lookup
            axioms: Optional axioms used in proof
            
        Returns:
            Cached ProofResult if found and not expired, None otherwise
        """
        cid = self._formula_to_cid(formula, axioms)
        
        with self.lock:
            self.stats['total_requests'] += 1
            
            if cid not in self.cache:
                self.stats['misses'] += 1
                return None
            
            entry = self.cache[cid]
            
            # Check if expired
            if time.time() - entry.timestamp > self.ttl:
                del self.cache[cid]
                self.stats['misses'] += 1
                return None
            
            # Cache hit!
            entry.hit_count += 1
            self.stats['hits'] += 1
            logger.debug(f"Cache hit for formula: {str(formula)[:50]}...")
            
            return entry.result
    
    def set(self, formula: Formula, result: ProofResult, axioms: Optional[List[Formula]] = None) -> None:
        """
        Cache a proof result.
        
        Args:
            formula: Formula that was proved
            result: Proof result to cache
            axioms: Optional axioms used in proof
        """
        cid = self._formula_to_cid(formula, axioms)
        
        with self.lock:
            # Check if cache is full
            if len(self.cache) >= self.maxsize and cid not in self.cache:
                # Evict oldest entry (simple FIFO)
                oldest_cid = min(self.cache.keys(), key=lambda k: self.cache[k].timestamp)
                del self.cache[oldest_cid]
                self.stats['evictions'] += 1
            
            # Cache the result
            self.cache[cid] = CachedProofEntry(
                formula_str=str(formula),
                result=result,
                timestamp=time.time(),
                hit_count=0
            )
            
            logger.debug(f"Cached proof result for: {str(formula)[:50]}...")
    
    def clear(self) -> None:
        """Clear all cached proofs."""
        with self.lock:
            self.cache.clear()
            logger.info("Proof cache cleared")
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        with self.lock:
            total = self.stats['total_requests']
            hit_rate = (self.stats['hits'] / total) if total > 0 else 0.0
            
            return {
                'size': len(self.cache),
                'maxsize': self.maxsize,
                'hits': self.stats['hits'],
                'misses': self.stats['misses'],
                'evictions': self.stats['evictions'],
                'total_requests': total,
                'hit_rate': hit_rate,
            }
    
    def __len__(self) -> int:
        """Get number of cached proofs."""
        return len(self.cache)
    
    def __contains__(self, formula: Formula) -> bool:
        """Check if formula result is cached."""
        cid = self._formula_to_cid(formula)
        with self.lock:
            return cid in self.cache


# Global proof cache instance
_global_proof_cache: Optional[TDFOLProofCache] = None


def get_global_proof_cache() -> TDFOLProofCache:
    """Get the global proof cache instance."""
    global _global_proof_cache
    if _global_proof_cache is None:
        _global_proof_cache = TDFOLProofCache()
    return _global_proof_cache


def clear_global_proof_cache() -> None:
    """Clear the global proof cache."""
    global _global_proof_cache
    if _global_proof_cache is not None:
        _global_proof_cache.clear()
