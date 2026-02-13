"""
Proof Cache System for Logic Module

Implements LRU cache for proof results with optional IPFS backing.
Provides significant performance improvements for repeated proofs.
"""

import hashlib
import json
import time
import logging
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CachedProof:
    """
    Represents a cached proof result.
    
    Attributes:
        formula_hash: Hash of the formula being proved
        prover: Name of the theorem prover used
        result_data: Serialized proof result
        timestamp: When the proof was cached
        ttl: Time-to-live in seconds (default: 3600 = 1 hour)
        hit_count: Number of times this cached proof was retrieved
        metadata: Additional metadata
    """
    formula_hash: str
    prover: str
    result_data: Dict[str, Any]
    timestamp: float
    ttl: int = 3600
    hit_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Check if cached proof has expired."""
        if self.ttl <= 0:  # 0 or negative means never expires
            return False
        return (time.time() - self.timestamp) > self.ttl
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CachedProof":
        """Create from dictionary."""
        return cls(**data)


class ProofCache:
    """
    LRU cache for proof results with optional IPFS backing.
    
    Features:
    - LRU eviction policy
    - Configurable TTL
    - Optional IPFS storage
    - Cache statistics and monitoring
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: int = 3600,
        ipfs_backed: bool = False,
        cache_dir: Optional[Path] = None
    ):
        """
        Initialize proof cache.
        
        Args:
            max_size: Maximum number of cached proofs
            default_ttl: Default time-to-live in seconds
            ipfs_backed: Whether to use IPFS for persistent storage
            cache_dir: Directory for file-based cache (if not using IPFS)
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.ipfs_backed = ipfs_backed
        self.cache_dir = cache_dir or Path("/tmp/logic_proof_cache")
        
        # LRU cache: OrderedDict maintains insertion order
        self._cache: OrderedDict[str, CachedProof] = OrderedDict()
        
        # Statistics
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expirations": 0,
            "total_puts": 0,
        }
        
        # Create cache directory if using file-based caching
        if not ipfs_backed:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Proof cache initialized: max_size={max_size}, cache_dir={self.cache_dir}")
        else:
            logger.info(f"Proof cache initialized with IPFS backing: max_size={max_size}")
    
    def _make_key(self, formula: str, prover: str) -> str:
        """
        Generate cache key from formula and prover.
        
        Args:
            formula: Logical formula
            prover: Prover name
            
        Returns:
            SHA256 hash of formula + prover
        """
        key_str = f"{formula}:{prover}"
        return hashlib.sha256(key_str.encode()).hexdigest()
    
    def get(self, formula: str, prover: str) -> Optional[Dict[str, Any]]:
        """
        Get cached proof result.
        
        Args:
            formula: Logical formula to look up
            prover: Name of prover to use
            
        Returns:
            Cached proof result or None if not found/expired
        """
        key = self._make_key(formula, prover)
        
        if key in self._cache:
            cached = self._cache[key]
            
            # Check if expired
            if cached.is_expired():
                self._stats["expirations"] += 1
                del self._cache[key]
                logger.debug(f"Cache expired: {key[:16]}...")
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            
            # Update statistics
            cached.hit_count += 1
            self._stats["hits"] += 1
            
            logger.debug(f"Cache hit: {key[:16]}... (hit_count={cached.hit_count})")
            return cached.result_data
        
        self._stats["misses"] += 1
        logger.debug(f"Cache miss: {key[:16]}...")
        return None
    
    def put(
        self,
        formula: str,
        prover: str,
        result: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> None:
        """
        Cache proof result.
        
        Args:
            formula: Logical formula
            prover: Name of prover
            result: Proof result to cache
            ttl: Optional TTL override (uses default if None)
        """
        key = self._make_key(formula, prover)
        
        # Evict oldest if at capacity
        if key not in self._cache and len(self._cache) >= self.max_size:
            oldest_key, _ = self._cache.popitem(last=False)
            self._stats["evictions"] += 1
            logger.debug(f"Evicted: {oldest_key[:16]}...")
        
        # Create cached proof
        cached = CachedProof(
            formula_hash=key,
            prover=prover,
            result_data=result,
            timestamp=time.time(),
            ttl=ttl if ttl is not None else self.default_ttl
        )
        
        # Add to cache
        self._cache[key] = cached
        self._stats["total_puts"] += 1
        
        # Optionally persist to file/IPFS
        if self.ipfs_backed:
            self._persist_to_ipfs(key, cached)
        else:
            self._persist_to_file(key, cached)
        
        logger.debug(f"Cached: {key[:16]}... (size={len(self._cache)}/{self.max_size})")
    
    def _persist_to_file(self, key: str, cached: CachedProof) -> None:
        """Persist cached proof to file."""
        try:
            cache_file = self.cache_dir / f"{key}.json"
            with open(cache_file, "w") as f:
                json.dump(cached.to_dict(), f)
        except Exception as e:
            logger.warning(f"Failed to persist cache to file: {e}")
    
    def _persist_to_ipfs(self, key: str, cached: CachedProof) -> None:
        """Persist cached proof to IPFS."""
        # TODO: Implement IPFS storage
        # This would use ipfs_kit_py to store the cached proof
        logger.debug(f"IPFS persistence not yet implemented for {key[:16]}...")
        pass
    
    def invalidate(self, formula: str, prover: str) -> bool:
        """
        Invalidate cached proof.
        
        Args:
            formula: Formula to invalidate
            prover: Prover name
            
        Returns:
            True if entry was removed, False if not found
        """
        key = self._make_key(formula, prover)
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"Invalidated: {key[:16]}...")
            return True
        return False
    
    def clear(self) -> int:
        """
        Clear all cached proofs.
        
        Returns:
            Number of entries cleared
        """
        count = len(self._cache)
        self._cache.clear()
        logger.info(f"Cache cleared: {count} entries removed")
        return count
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics including hit rate
        """
        total_requests = self._stats["hits"] + self._stats["misses"]
        hit_rate = (
            self._stats["hits"] / total_requests
            if total_requests > 0
            else 0.0
        )
        
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": hit_rate,
            "evictions": self._stats["evictions"],
            "expirations": self._stats["expirations"],
            "total_puts": self._stats["total_puts"],
            "ipfs_backed": self.ipfs_backed,
        }
    
    def get_cached_entries(self) -> List[Dict[str, Any]]:
        """
        Get list of all cached entries (for monitoring/debugging).
        
        Returns:
            List of cached entry summaries
        """
        entries = []
        for key, cached in self._cache.items():
            entries.append({
                "key": key[:16] + "...",
                "prover": cached.prover,
                "timestamp": cached.timestamp,
                "age_seconds": time.time() - cached.timestamp,
                "ttl": cached.ttl,
                "expired": cached.is_expired(),
                "hit_count": cached.hit_count,
            })
        return entries
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.
        
        Returns:
            Number of entries removed
        """
        expired_keys = [
            key for key, cached in self._cache.items()
            if cached.is_expired()
        ]
        
        for key in expired_keys:
            del self._cache[key]
            self._stats["expirations"] += 1
        
        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired entries")
        
        return len(expired_keys)
    
    def resize(self, new_max_size: int) -> None:
        """
        Resize cache capacity.
        
        Args:
            new_max_size: New maximum cache size
        """
        old_size = self.max_size
        self.max_size = new_max_size
        
        # Evict oldest entries if needed
        while len(self._cache) > new_max_size:
            self._cache.popitem(last=False)
            self._stats["evictions"] += 1
        
        logger.info(f"Cache resized: {old_size} -> {new_max_size}")


# Global cache instance (singleton pattern)
_global_cache: Optional[ProofCache] = None


def get_global_cache(
    max_size: int = 1000,
    default_ttl: int = 3600,
    ipfs_backed: bool = False
) -> ProofCache:
    """
    Get or create global proof cache instance.
    
    Args:
        max_size: Maximum cache size (only used if creating new cache)
        default_ttl: Default TTL (only used if creating new cache)
        ipfs_backed: Whether to use IPFS backing
        
    Returns:
        Global ProofCache instance
    """
    global _global_cache
    
    if _global_cache is None:
        _global_cache = ProofCache(
            max_size=max_size,
            default_ttl=default_ttl,
            ipfs_backed=ipfs_backed
        )
    
    return _global_cache


__all__ = [
    "CachedProof",
    "ProofCache",
    "get_global_cache",
]
