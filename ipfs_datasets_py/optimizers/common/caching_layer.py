"""
Multi-level caching architecture with L1/L2 cache layers.

Provides in-memory (L1) and disk-based (L2) caching with configurable
eviction policies, TTL support, and automatic promotion/demotion between levels.

Classes:
    CacheEntry: Single cache entry with metadata
    EvictionPolicy: Eviction strategy enumeration
    CacheL1: In-memory cache with multiple eviction strategies
    CacheL2: Disk-based persistent cache
    MultiLevelCache: Two-level cache orchestrator
    CacheMetrics: Cache performance metrics
"""

import os
import json
import pickle
import time
import threading
from dataclasses import dataclass, field
from collections import OrderedDict
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple, cast
from pathlib import Path

from ipfs_datasets_py.optimizers.common.path_validator import (
    validate_input_path,
    validate_output_path,
)


class EvictionPolicy(Enum):
    """Cache eviction policy enumeration."""
    LRU = "lru"      # Least Recently Used
    LFU = "lfu"      # Least Frequently Used
    FIFO = "fifo"    # First In First Out
    TTL = "ttl"      # Time To Live (oldest first)
    THRESHOLD = "threshold"  # Based on size threshold


@dataclass
class CacheEntry:
    """Single cache entry with metadata."""
    key: str
    value: Any
    ttl: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.ttl is None:
            return False
        return time.time() - self.created_at > self.ttl
    
    def mark_accessed(self) -> None:
        """Mark entry as accessed."""
        self.last_accessed = time.time()
        self.access_count += 1


@dataclass
class CacheMetrics:
    """Cache performance metrics."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    memory_used_bytes: int = 0
    entry_count: int = 0
    
    def hit_rate(self) -> float:
        """Calculate hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    def miss_rate(self) -> float:
        """Calculate miss rate."""
        total = self.hits + self.misses
        return self.misses / total if total > 0 else 0.0


class CacheL1:
    """In-memory level 1 cache with configurable eviction."""
    
    def __init__(self, max_size: int = 100, eviction_policy: EvictionPolicy = EvictionPolicy.LRU, default_ttl: Optional[float] = None):
        self.max_size = max_size
        self.eviction_policy = eviction_policy
        self.default_ttl = default_ttl
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.metrics = CacheMetrics()
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        with self._lock:
            if key not in self.cache:
                self.metrics.misses += 1
                return None
            
            entry = self.cache[key]
            
            # Check expiration
            if entry.is_expired():
                del self.cache[key]
                self.metrics.misses += 1
                return None
            
            # Update access info and move to end (for LRU)
            entry.mark_accessed()
            self.cache.move_to_end(key)
            
            self.metrics.hits += 1
            return entry.value
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set value in cache."""
        with self._lock:
            ttl = ttl or self.default_ttl
            
            # Remove old entry if exists
            if key in self.cache:
                del self.cache[key]
            
            # Check if eviction needed
            if len(self.cache) >= self.max_size:
                self._evict_one()
            
            # Add new entry
            entry = CacheEntry(key=key, value=value, ttl=ttl)
            self.cache[key] = entry
    
    def delete(self, key: str) -> bool:
        """Delete entry from cache."""
        with self._lock:
            if key in self.cache:
                del self.cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self.cache.clear()
            self.metrics = CacheMetrics()
    
    def _should_evict(self) -> bool:
        """Check if eviction is needed."""
        return len(self.cache) >= self.max_size
    
    def _evict_one(self) -> None:
        """Evict one entry based on policy."""
        if len(self.cache) == 0:
            return
        
        if self.eviction_policy == EvictionPolicy.LRU:
            key_to_evict = next(iter(self.cache))  # First item (oldest access)
        elif self.eviction_policy == EvictionPolicy.LFU:
            key_to_evict = min(self.cache.keys(), key=lambda k: self.cache[k].access_count)
        elif self.eviction_policy == EvictionPolicy.FIFO:
            key_to_evict = next(iter(self.cache))  # First item (oldest created)
        elif self.eviction_policy == EvictionPolicy.TTL:
            key_to_evict = max(self.cache.keys(), key=lambda k: self.cache[k].created_at)
        else:
            key_to_evict = next(iter(self.cache))
        
        del self.cache[key_to_evict]
        self.metrics.evictions += 1
    
    def get_metrics(self) -> CacheMetrics:
        """Get cache metrics."""
        with self._lock:
            self.metrics.entry_count = len(self.cache)
            return self.metrics


class CacheL2:
    """Disk-based level 2 cache with Parquet persistence."""
    
    def __init__(self, path: str = "/tmp/cache_l2"):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.index_path = self.path / "index.json"
        self.metrics = CacheMetrics()
        self._lock = threading.RLock()
        self._load_index()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from L2 cache."""
        with self._lock:
            index = self._load_index()
            if key not in index:
                self.metrics.misses += 1
                return None
            
            try:
                file_path = self.path / f"{key}.pkl"
                if not file_path.exists():
                    self.metrics.misses += 1
                    return None
                
                with open(file_path, 'rb') as f:
                    value = pickle.load(f)
                
                self.metrics.hits += 1
                index[key]['accessed_at'] = time.time()
                index[key]['access_count'] += 1
                self._save_index(index)
                
                return value
            except (
                OSError,
                EOFError,
                pickle.PickleError,
                AttributeError,
                ValueError,
                TypeError,
            ):
                self.metrics.misses += 1
                return None
    
    def set(self, key: str, value: Any) -> None:
        """Set value in L2 cache."""
        with self._lock:
            try:
                file_path = self.path / f"{key}.pkl"
                
                # Validate output path
                base_dir = file_path.parent if file_path.is_absolute() else None
                safe_path = validate_output_path(str(file_path), allow_overwrite=True, base_dir=base_dir)
                
                with open(safe_path, 'wb') as f:
                    pickle.dump(value, f)
                
                index = self._load_index()
                index[key] = {
                    'created_at': time.time(),
                    'accessed_at': time.time(),
                    'access_count': 0
                }
                self._save_index(index)
            except (
                OSError,
                pickle.PickleError,
                AttributeError,
                ValueError,
                TypeError,
            ):
                pass
    
    def delete(self, key: str) -> bool:
        """Delete entry from L2 cache."""
        with self._lock:
            try:
                file_path = self.path / f"{key}.pkl"
                if file_path.exists():
                    file_path.unlink()
                    index = self._load_index()
                    if key in index:
                        del index[key]
                    self._save_index(index)
                    return True
            except OSError:
                pass
            return False
    
    def clear(self) -> None:
        """Clear all L2 cache entries."""
        with self._lock:
            for f in self.path.glob("*.pkl"):
                f.unlink()
            self.index_path.unlink(missing_ok=True)
    
    def _load_index(self) -> Dict[str, Any]:
        """Load index from disk."""
        if self.index_path.exists():
            try:
                # Validate input path
                base_dir = self.index_path.parent if self.index_path.is_absolute() else None
                safe_path = validate_input_path(str(self.index_path), must_exist=True, base_dir=base_dir)
                
                with open(safe_path, 'r') as f:
                    return cast(Dict[str, Any], json.load(f))
            except (OSError, json.JSONDecodeError, ValueError, TypeError):
                return {}
        return {}
    
    def _save_index(self, index: Dict[str, Any]) -> None:
        """Save index to disk."""
        try:
            # Validate output path
            base_dir = self.index_path.parent if self.index_path.is_absolute() else None
            safe_path = validate_output_path(str(self.index_path), allow_overwrite=True, base_dir=base_dir)
            
            with open(safe_path, 'w') as f:
                json.dump(index, f)
        except (OSError, TypeError, ValueError):
            pass


class MultiLevelCache:
    """Two-level cache with L1 (memory) and L2 (disk)."""
    
    def __init__(self, max_l1_size: int = 100, max_l2_size: int = 1000, 
                 eviction_policy: EvictionPolicy = EvictionPolicy.LRU,
                 default_ttl: Optional[float] = None, l2_path: str = "/tmp/cache_l2"):
        self.l1 = CacheL1(max_size=max_l1_size, eviction_policy=eviction_policy, default_ttl=default_ttl)
        self.l2 = CacheL2(path=l2_path)
        self.l1_capacity = max_l1_size
        self.l2_capacity = max_l2_size
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value, checking L1 then L2."""
        with self._lock:
            # Try L1
            value = self.l1.get(key)
            if value is not None:
                return value
            
            # Try L2
            value = self.l2.get(key)
            if value is not None:
                # Promote to L1
                self.l1.set(key, value)
                return value
            
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set value in L1, automatically promote to L2 if no TTL or long TTL."""
        with self._lock:
            self.l1.set(key, value, ttl=ttl)
            # Only promote to L2 if no TTL or reasonably long TTL (avoid promoting short-lived cache items)
            if ttl is None or ttl > 30:  # Don't promote short-TTL items (< 30 seconds)
                self.l2.set(key, value)
    
    def delete(self, key: str) -> None:
        """Delete from both levels."""
        with self._lock:
            self.l1.delete(key)
            self.l2.delete(key)
    
    def clear(self) -> None:
        """Clear both levels."""
        with self._lock:
            self.l1.clear()
            self.l2.clear()
    
    def warm_from_disk(self, keys: List[str]) -> None:
        """Load specific keys from L2 to L1."""
        with self._lock:
            for key in keys:
                value = self.l2.get(key)
                if value is not None:
                    self.l1.set(key, value)
    
    def get_combined_metrics(self) -> Dict[str, Any]:
        """Get combined metrics from both levels."""
        with self._lock:
            l1_metrics = self.l1.get_metrics()
            return {
                'total_hits': l1_metrics.hits + self.l2.metrics.hits,
                'total_misses': l1_metrics.misses + self.l2.metrics.misses,
                'l1_entries': l1_metrics.entry_count,
                'l2_entries': len(self.l2._load_index()),
                'evictions': l1_metrics.evictions,
            }
