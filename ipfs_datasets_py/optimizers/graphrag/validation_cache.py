"""Advanced caching strategy for LogicValidator.

This module provides an enhanced caching layer for logic validation operations,
including LRU eviction, persistence, statistics, and warming strategies.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict

logger = logging.getLogger(__name__)


class CacheStatsDict(TypedDict, total=False):
    """Statistics dictionary for cache performance.
    
    Fields:
        hits: Number of cache hits
        misses: Number of cache misses
        evictions: Number of cache evictions
        writes: Number of cache writes
        hit_rate: Cache hit rate (0-1)
        total_requests: Total number of requests
        total_size_mb: Total cache size in megabytes
    """
    hits: int
    misses: int
    evictions: int
    writes: int
    hit_rate: float
    total_requests: int
    total_size_mb: float


class MultiLayerCacheStatsDict(TypedDict, total=False):
    """Combined statistics for multi-layer cache.
    
    Fields:
        tdfol_cache: Stats dict for TDFOL cache layer
        consistency_cache: Stats dict for consistency cache layer
        incremental_cache: Stats dict for incremental cache layer
        total_hit_rate: Combined hit rate across all layers (0-1)
    """
    tdfol_cache: CacheStatsDict
    consistency_cache: CacheStatsDict
    incremental_cache: CacheStatsDict
    total_hit_rate: float

@dataclass
class CacheStats:
    """Statistics for cache performance monitoring."""
    
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    writes: int = 0
    total_size_bytes: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate (0.0 to 1.0)."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    @property
    def total_requests(self) -> int:
        """Total number of cache requests."""
        return self.hits + self.misses
    
    def to_dict(self) -> CacheStatsDict:
        """Convert to dictionary for JSON serialization."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "writes": self.writes,
            "hit_rate": round(self.hit_rate, 4),
            "total_requests": self.total_requests,
            "total_size_mb": round(self.total_size_bytes / (1024 * 1024), 2),
        }


class LRUCache:
    """
    Least-Recently-Used cache with size limits and eviction.
    
    This cache evicts the least recently used items when capacity is reached.
    Supports persistence to disk and statistical monitoring.
    
    Example:
        >>> cache = LRUCache(max_size=100, max_memory_mb=50)
        >>> cache.set("key1", {"result": "value"})
        >>> result = cache.get("key1")
        >>> print(cache.stats.hit_rate)
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        max_memory_mb: float = 100.0,
        enable_persistence: bool = False,
        persistence_path: Optional[Path] = None,
    ):
        """
        Initialize LRU cache.
        
        Args:
            max_size: Maximum number of entries
            max_memory_mb: Maximum memory usage in MB
            enable_persistence: Whether to persist cache to disk
            persistence_path: Path to cache file (default: ~/.cache/ontology_validator/)
        """
        self.max_size = max_size
        self.max_memory_bytes = int(max_memory_mb * 1024 * 1024)
        self.enable_persistence = enable_persistence
        self.persistence_path = persistence_path or (
            Path.home() / ".cache" / "ontology_validator" / "logic_cache.json"
        )
        
        # OrderedDict maintains insertion order
        self._cache: OrderedDict[str, Tuple[Any, int, float]] = OrderedDict()
        # Format: {key: (value, size_bytes, timestamp)}
        
        self.stats = CacheStats()
        
        # Load from disk if persistence enabled
        if self.enable_persistence:
            self._load_from_disk()
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found
        """
        if key in self._cache:
            # Move to end (mark as recently used)
            value, size, timestamp = self._cache.pop(key)
            self._cache[key] = (value, size, time.time())
            self.stats.hits += 1
            logger.debug(f"Cache hit: {key[:12]}... (hit rate: {self.stats.hit_rate:.2%})")
            return value
        else:
            self.stats.misses += 1
            logger.debug(f"Cache miss: {key[:12]}... (hit rate: {self.stats.hit_rate:.2%})")
            return None
    
    def set(self, key: str, value: Any) -> None:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        # Estimate size
        size_bytes = len(json.dumps(value).encode())
        
        # Remove old entry if exists
        if key in self._cache:
            old_value, old_size, old_timestamp = self._cache.pop(key)
            self.stats.total_size_bytes -= old_size
        
        # Evict entries if needed
        while (
            len(self._cache) >= self.max_size
            or self.stats.total_size_bytes + size_bytes > self.max_memory_bytes
        ):
            self._evict_lru()
        
        # Add new entry
        self._cache[key] = (value, size_bytes, time.time())
        self.stats.total_size_bytes += size_bytes
        self.stats.writes += 1
        
        logger.debug(
            f"Cache set: {key[:12]}... "
            f"(size: {len(self._cache)}/{self.max_size}, "
            f"mem: {self.stats.total_size_bytes / (1024*1024):.2f}MB)"
        )
    
    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._cache:
            return
        
        # Pop first item (LRU)
        key, (value, size, timestamp) = self._cache.popitem(last=False)
        self.stats.total_size_bytes -= size
        self.stats.evictions += 1
        logger.debug(f"Evicted LRU entry: {key[:12]}...")
    
    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self.stats.total_size_bytes = 0
        logger.info("Cache cleared")
    
    def _load_from_disk(self) -> None:
        """Load cache from disk."""
        if not self.persistence_path.exists():
            logger.debug("No cache file found, starting fresh")
            return
        
        try:
            with open(self.persistence_path, 'r') as f:
                data = json.load(f)
            
            # Restore cache entries
            for key, entry in data.get("entries", {}).items():
                value = entry["value"]
                size = entry["size"]
                timestamp = entry.get("timestamp", time.time())
                self._cache[key] = (value, size, timestamp)
                self.stats.total_size_bytes += size
            
            logger.info(f"Loaded {len(self._cache)} entries from cache file")
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(f"Failed to load cache from disk: {e}")
    
    def _save_to_disk(self) -> None:
        """Save cache to disk."""
        if not self.enable_persistence:
            return
        
        try:
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "version": "1.0",
                "entries": {
                    key: {
                        "value": value,
                        "size": size,
                        "timestamp": timestamp,
                    }
                    for key, (value, size, timestamp) in self._cache.items()
                },
                "stats": self.stats.to_dict(),
            }
            
            with open(self.persistence_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug(f"Saved cache to {self.persistence_path}")
        except (OSError, TypeError, ValueError) as e:
            logger.warning(f"Failed to save cache to disk: {e}")
    
    def __del__(self):
        """Save cache on destruction."""
        if self.enable_persistence:
            self._save_to_disk()


class ValidationCache:
    """
    Specialized cache for logic validation results.
    
    Provides multiple cache layers:
    - TDFOL formula cache (keyed by ontology hash)
    - Consistency check cache (keyed by formula hash)
    - Incremental validation cache (keyed by entity/relationship IDs)
    
    Example:
        >>> cache = ValidationCache(max_size=500)
        >>> cache.set_tdfol(ontology_hash, formulas)
        >>> formulas = cache.get_tdfol(ontology_hash)
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        max_memory_mb: float = 100.0,
        enable_persistence: bool = False,
    ):
        """
        Initialize validation cache.
        
        Args:
            max_size: Maximum entries per cache layer
            max_memory_mb: Maximum memory per cache layer
            enable_persistence: Enable disk persistence
        """
        self.tdfol_cache = LRUCache(
            max_size=max_size,
            max_memory_mb=max_memory_mb,
            enable_persistence=enable_persistence,
            persistence_path=Path.home() / ".cache" / "ontology_validator" / "tdfol_cache.json",
        )
        
        self.consistency_cache = LRUCache(
            max_size=max_size,
            max_memory_mb=max_memory_mb,
            enable_persistence=enable_persistence,
            persistence_path=Path.home() / ".cache" / "ontology_validator" / "consistency_cache.json",
        )
        
        self.incremental_cache = LRUCache(
            max_size=max_size * 10,  # More entries for incremental cache
            max_memory_mb=max_memory_mb * 2,
            enable_persistence=enable_persistence,
            persistence_path=Path.home() / ".cache" / "ontology_validator" / "incremental_cache.json",
        )
    
    def get_tdfol(self, key: str) -> Optional[List[Any]]:
        """Get TDFOL formulas from cache."""
        return self.tdfol_cache.get(f"tdfol:{key}")
    
    def set_tdfol(self, key: str, formulas: List[Any]) -> None:
        """Set TDFOL formulas in cache."""
        self.tdfol_cache.set(f"tdfol:{key}", formulas)
    
    def get_consistency(self, key: str) -> Optional[Dict[str, Any]]:
        """Get consistency check result from cache."""
        return self.consistency_cache.get(f"consistency:{key}")
    
    def set_consistency(self, key: str, result: Dict[str, Any]) -> None:
        """Set consistency check result in cache."""
        self.consistency_cache.set(f"consistency:{key}", result)
    
    def get_incremental(self, entity_ids: List[str]) -> Optional[Dict[str, Any]]:
        """Get incremental validation result from cache."""
        key = self._incremental_key(entity_ids)
        return self.incremental_cache.get(f"incremental:{key}")
    
    def set_incremental(self, entity_ids: List[str], result: Dict[str, Any]) -> None:
        """Set incremental validation result in cache."""
        key = self._incremental_key(entity_ids)
        self.incremental_cache.set(f"incremental:{key}", result)
    
    def _incremental_key(self, entity_ids: List[str]) -> str:
        """Generate cache key for incremental validation."""
        # Sort IDs for deterministic key
        sorted_ids = sorted(entity_ids)
        id_str = ",".join(sorted_ids)
        return hashlib.sha256(id_str.encode()).hexdigest()
    
    def get_stats(self) -> MultiLayerCacheStatsDict:
        """Get combined statistics for all cache layers."""
        return {
            "tdfol_cache": self.tdfol_cache.stats.to_dict(),
            "consistency_cache": self.consistency_cache.stats.to_dict(),
            "incremental_cache": self.incremental_cache.stats.to_dict(),
            "total_hit_rate": round(
                (
                    self.tdfol_cache.stats.hits
                    + self.consistency_cache.stats.hits
                    + self.incremental_cache.stats.hits
                )
                / max(
                    1,
                    self.tdfol_cache.stats.total_requests
                    + self.consistency_cache.stats.total_requests
                    + self.incremental_cache.stats.total_requests,
                ),
                4,
            ),
        }
    
    def clear_all(self) -> None:
        """Clear all cache layers."""
        self.tdfol_cache.clear()
        self.consistency_cache.clear()
        self.incremental_cache.clear()
        logger.info("All validation caches cleared")


# Global cache instance (optional, for convenience)
_global_cache: Optional[ValidationCache] = None


def get_global_cache() -> ValidationCache:
    """Get or create global validation cache."""
    global _global_cache
    if _global_cache is None:
        _global_cache = ValidationCache(
            max_size=1000,
            max_memory_mb=100.0,
            enable_persistence=True,
        )
    return _global_cache
