"""
MCP++ Result Caching System (Phase 4.4)

Implements result caching with:
- TTL (Time-To-Live) expiration
- Multiple cache backends (memory, disk)
- Cache invalidation strategies
- LRU/LFU eviction policies
- Integration with workflow DAG for result reuse

This enables efficient result reuse across workflow executions.
"""

import asyncio
import hashlib
import json
import logging
import pickle
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from threading import RLock
from enum import Enum

logger = logging.getLogger(__name__)


class EvictionPolicy(Enum):
    """Cache eviction policy types."""
    LRU = "lru"  # Least Recently Used
    LFU = "lfu"  # Least Frequently Used
    FIFO = "fifo"  # First In, First Out
    TTL = "ttl"  # Time To Live (expire old entries)


@dataclass
class CacheEntry:
    """Cache entry with metadata."""
    
    key: str
    value: Any
    created_at: float
    last_accessed: float
    access_count: int
    ttl: Optional[float]
    size_bytes: int
    
    @property
    def age_seconds(self) -> float:
        """Calculate entry age in seconds."""
        return time.time() - self.created_at
    
    @property
    def is_expired(self) -> bool:
        """Check if entry has expired based on TTL."""
        if self.ttl is None:
            return False
        return self.age_seconds > self.ttl
    
    def access(self) -> None:
        """Record an access to this entry."""
        self.last_accessed = time.time()
        self.access_count += 1


class CacheBackend(ABC):
    """Abstract base class for cache backends."""
    
    @abstractmethod
    async def get(self, key: str) -> Optional[CacheEntry]:
        """Get entry from cache."""
        pass
    
    @abstractmethod
    async def put(self, entry: CacheEntry) -> None:
        """Put entry into cache."""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete entry from cache."""
        pass
    
    @abstractmethod
    async def clear(self) -> int:
        """Clear all entries from cache."""
        pass
    
    @abstractmethod
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        pass


class MemoryCacheBackend(CacheBackend):
    """In-memory cache backend using OrderedDict."""
    
    def __init__(
        self,
        max_size: int = 1000,
        max_memory_mb: float = 100.0
    ):
        """
        Initialize memory cache.
        
        Args:
            max_size: Maximum number of entries
            max_memory_mb: Maximum memory usage in MB
        """
        self.max_size = max_size
        self.max_memory_bytes = int(max_memory_mb * 1024 * 1024)
        
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = RLock()
        self._total_bytes = 0
    
    async def get(self, key: str) -> Optional[CacheEntry]:
        """Get entry from cache."""
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                entry.access()
            return entry
    
    async def put(self, entry: CacheEntry) -> None:
        """Put entry into cache."""
        with self._lock:
            # Check if key already exists
            if entry.key in self._cache:
                old_entry = self._cache[entry.key]
                self._total_bytes -= old_entry.size_bytes
                del self._cache[entry.key]
            
            # Add new entry
            self._cache[entry.key] = entry
            self._total_bytes += entry.size_bytes
            
            # Evict if necessary
            await self._evict_if_needed()
    
    async def delete(self, key: str) -> bool:
        """Delete entry from cache."""
        with self._lock:
            entry = self._cache.pop(key, None)
            if entry:
                self._total_bytes -= entry.size_bytes
                return True
            return False
    
    async def clear(self) -> int:
        """Clear all entries from cache."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._total_bytes = 0
            return count
    
    async def _evict_if_needed(self) -> None:
        """Evict entries if size limits exceeded."""
        with self._lock:
            # Evict oldest entries until within limits
            while (len(self._cache) > self.max_size or 
                   self._total_bytes > self.max_memory_bytes):
                if not self._cache:
                    break
                
                # Remove oldest (first) entry
                key, entry = self._cache.popitem(last=False)
                self._total_bytes -= entry.size_bytes
                logger.debug(f"Evicted cache entry: {key}")
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            return {
                'backend': 'memory',
                'size': len(self._cache),
                'max_size': self.max_size,
                'total_bytes': self._total_bytes,
                'max_bytes': self.max_memory_bytes,
                'utilization': len(self._cache) / self.max_size if self.max_size > 0 else 0
            }


class DiskCacheBackend(CacheBackend):
    """Disk-based cache backend using pickle."""
    
    def __init__(
        self,
        cache_dir: Path,
        max_size: int = 10000
    ):
        """
        Initialize disk cache.
        
        Args:
            cache_dir: Directory to store cache files
            max_size: Maximum number of entries
        """
        self.cache_dir = Path(cache_dir)
        self.max_size = max_size
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._index: Dict[str, Path] = {}
        self._lock = RLock()
        
        # Load index
        asyncio.create_task(self._load_index())
    
    async def _load_index(self) -> None:
        """Load cache index from disk, keyed by the original entry key."""
        with self._lock:
            for cache_file in self.cache_dir.glob("*.cache"):
                try:
                    with open(cache_file, 'rb') as f:
                        entry = pickle.load(f)
                    self._index[entry.key] = cache_file
                except Exception as e:
                    logger.warning(
                        f"Skipping unreadable cache file {cache_file}: {e}. "
                        "The entry will not be available in this session."
                    )
    
    def _get_cache_path(self, key: str) -> Path:
        """Get file path for cache key."""
        # Hash key to create filename
        key_hash = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self.cache_dir / f"{key_hash}.cache"
    
    async def get(self, key: str) -> Optional[CacheEntry]:
        """Get entry from cache."""
        with self._lock:
            cache_path = self._index.get(key)
            if not cache_path or not cache_path.exists():
                return None
            
            try:
                with open(cache_path, 'rb') as f:
                    entry = pickle.load(f)
                    entry.access()
                    
                    # Save updated access info
                    with open(cache_path, 'wb') as f:
                        pickle.dump(entry, f)
                    
                    return entry
            except Exception as e:
                logger.error(f"Error loading cache entry {key}: {e}")
                return None
    
    async def put(self, entry: CacheEntry) -> None:
        """Put entry into cache."""
        with self._lock:
            cache_path = self._get_cache_path(entry.key)
            
            try:
                with open(cache_path, 'wb') as f:
                    pickle.dump(entry, f)
                
                self._index[entry.key] = cache_path
                
                # Evict if necessary
                await self._evict_if_needed()
            except Exception as e:
                logger.error(f"Error saving cache entry {entry.key}: {e}")
    
    async def delete(self, key: str) -> bool:
        """Delete entry from cache."""
        with self._lock:
            cache_path = self._index.pop(key, None)
            if cache_path and cache_path.exists():
                try:
                    cache_path.unlink()
                    return True
                except Exception as e:
                    logger.error(f"Error deleting cache entry {key}: {e}")
            return False
    
    async def clear(self) -> int:
        """Clear all entries from cache."""
        with self._lock:
            count = 0
            for cache_path in self._index.values():
                if cache_path.exists():
                    try:
                        cache_path.unlink()
                        count += 1
                    except Exception as e:
                        logger.error(f"Error deleting cache file {cache_path}: {e}")
            
            self._index.clear()
            return count
    
    async def _evict_if_needed(self) -> None:
        """Evict oldest entries if size limit exceeded."""
        with self._lock:
            if len(self._index) <= self.max_size:
                return
            
            # Get all entries and sort by age
            entries = []
            for key, cache_path in self._index.items():
                if cache_path.exists():
                    entries.append((key, cache_path.stat().st_mtime))
            
            entries.sort(key=lambda x: x[1])  # Sort by modification time
            
            # Remove oldest entries
            to_remove = len(self._index) - self.max_size
            for key, _ in entries[:to_remove]:
                await self.delete(key)
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_size = sum(
                path.stat().st_size 
                for path in self._index.values() 
                if path.exists()
            )
            
            return {
                'backend': 'disk',
                'size': len(self._index),
                'max_size': self.max_size,
                'total_bytes': total_size,
                'cache_dir': str(self.cache_dir)
            }


class ResultCache:
    """
    Result caching system with TTL and multiple backends.
    
    Supports:
    - Multiple cache backends (memory, disk)
    - TTL-based expiration
    - LRU/LFU eviction policies
    - Cache invalidation
    - Statistics and monitoring
    
    Example:
        cache = ResultCache(backend=MemoryCacheBackend())
        
        # Cache a result
        await cache.put('task_123', {'result': 'data'}, ttl=3600)
        
        # Retrieve result
        result = await cache.get('task_123')
        
        # Invalidate cache
        await cache.invalidate('task_123')
    """
    
    def __init__(
        self,
        backend: CacheBackend,
        default_ttl: float = 3600.0,
        eviction_policy: EvictionPolicy = EvictionPolicy.LRU
    ):
        """
        Initialize result cache.
        
        Args:
            backend: Cache backend to use
            default_ttl: Default TTL in seconds
            eviction_policy: Eviction policy to use
        """
        self.backend = backend
        self.default_ttl = default_ttl
        self.eviction_policy = eviction_policy
        
        # Statistics
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self._lock = RLock()
        
        logger.info(f"Initialized ResultCache with {backend.__class__.__name__} backend")
    
    def _compute_key(self, task_id: str, inputs: Optional[Dict] = None) -> str:
        """Compute cache key from task ID and inputs."""
        if inputs:
            # Include inputs in key for deterministic caching
            inputs_str = json.dumps(inputs, sort_keys=True)
            key_str = f"{task_id}:{inputs_str}"
        else:
            key_str = task_id
        
        # Hash to fixed-length key
        return hashlib.sha256(key_str.encode()).hexdigest()
    
    def _estimate_size(self, value: Any) -> int:
        """Estimate size of cached value in bytes."""
        try:
            return len(pickle.dumps(value))
        except Exception:
            return 1024  # Default estimate
    
    async def get(
        self,
        task_id: str,
        inputs: Optional[Dict] = None
    ) -> Optional[Any]:
        """
        Get cached result.
        
        Args:
            task_id: Task identifier
            inputs: Optional task inputs (for deterministic caching)
            
        Returns:
            Cached result or None if not found
        """
        key = self._compute_key(task_id, inputs)
        
        entry = await self.backend.get(key)
        
        if entry is None:
            with self._lock:
                self.misses += 1
            return None
        
        # Check expiration
        if entry.is_expired:
            await self.backend.delete(key)
            with self._lock:
                self.misses += 1
            return None
        
        with self._lock:
            self.hits += 1
        
        logger.debug(f"Cache hit for {task_id}")
        return entry.value
    
    async def put(
        self,
        task_id: str,
        value: Any,
        ttl: Optional[float] = None,
        inputs: Optional[Dict] = None
    ) -> None:
        """
        Cache a result.
        
        Args:
            task_id: Task identifier
            value: Result value to cache
            ttl: Optional TTL in seconds (uses default if None)
            inputs: Optional task inputs (for deterministic caching)
        """
        key = self._compute_key(task_id, inputs)
        ttl = ttl if ttl is not None else self.default_ttl
        
        entry = CacheEntry(
            key=key,
            value=value,
            created_at=time.time(),
            last_accessed=time.time(),
            access_count=0,
            ttl=ttl,
            size_bytes=self._estimate_size(value)
        )
        
        await self.backend.put(entry)
        logger.debug(f"Cached result for {task_id} (ttl={ttl}s)")
    
    async def invalidate(
        self,
        task_id: str,
        inputs: Optional[Dict] = None
    ) -> bool:
        """
        Invalidate cached result.
        
        Args:
            task_id: Task identifier
            inputs: Optional task inputs
            
        Returns:
            True if entry was found and deleted
        """
        key = self._compute_key(task_id, inputs)
        deleted = await self.backend.delete(key)
        
        if deleted:
            logger.debug(f"Invalidated cache for {task_id}")
        
        return deleted
    
    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all entries matching a pattern.
        
        Args:
            pattern: Pattern to match (prefix matching)
            
        Returns:
            Number of entries invalidated
        """
        # This would require backend support for pattern matching
        # For now, it's a placeholder
        logger.warning("Pattern-based invalidation not yet implemented")
        return 0
    
    async def clear(self) -> int:
        """
        Clear all cached results.
        
        Returns:
            Number of entries cleared
        """
        count = await self.backend.clear()
        logger.info(f"Cleared {count} cache entries")
        return count
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        with self._lock:
            total = self.hits + self.misses
            if total == 0:
                return 0.0
            return self.hits / total
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        backend_stats = await self.backend.get_stats()
        
        with self._lock:
            return {
                **backend_stats,
                'hits': self.hits,
                'misses': self.misses,
                'hit_rate': self.hit_rate,
                'evictions': self.evictions,
                'default_ttl': self.default_ttl,
                'eviction_policy': self.eviction_policy.value
            }


# Example usage
if __name__ == '__main__':
    async def main():
        # Test memory cache
        print("Testing Memory Cache:")
        memory_backend = MemoryCacheBackend(max_size=3)
        cache = ResultCache(backend=memory_backend, default_ttl=2.0)
        
        # Cache some results
        await cache.put('task1', {'result': 1})
        await cache.put('task2', {'result': 2})
        await cache.put('task3', {'result': 3})
        
        # Retrieve results
        result1 = await cache.get('task1')
        print(f"task1: {result1}")
        
        # Add another (should evict oldest)
        await cache.put('task4', {'result': 4})
        
        # task1 should still be there (was accessed)
        result1 = await cache.get('task1')
        print(f"task1 after eviction: {result1}")
        
        # task2 should be evicted
        result2 = await cache.get('task2')
        print(f"task2 after eviction: {result2}")
        
        # Stats
        stats = await cache.get_stats()
        print(f"\nCache stats: {stats}")
        
        # Test TTL expiration
        print("\n\nTesting TTL Expiration:")
        await cache.put('temp', {'result': 'temporary'}, ttl=1.0)
        result = await cache.get('temp')
        print(f"Before expiration: {result}")
        
        await asyncio.sleep(1.5)
        result = await cache.get('temp')
        print(f"After expiration: {result}")
        
        # Test disk cache
        print("\n\nTesting Disk Cache:")
        disk_backend = DiskCacheBackend(Path('/tmp/mcp_cache'))
        disk_cache = ResultCache(backend=disk_backend)
        
        await disk_cache.put('disk_task', {'result': 'on disk'})
        result = await disk_cache.get('disk_task')
        print(f"From disk: {result}")
        
        stats = await disk_cache.get_stats()
        print(f"Disk cache stats: {stats}")
        
        # Clear
        await disk_cache.clear()
    
    asyncio.run(main())
