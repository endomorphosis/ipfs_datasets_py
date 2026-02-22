"""
CEC Formula Caching System

This module provides advanced caching mechanisms for CEC formulas, proofs,
and parsing results to improve performance.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Tuple, List
from functools import lru_cache
from collections import OrderedDict
import hashlib
import pickle
import time


@dataclass
class CacheEntry:
    """
    A single cache entry.
    
    Attributes:
        key: Cache key
        value: Cached value
        created_at: Creation timestamp
        accessed_at: Last access timestamp
        access_count: Number of times accessed
        size_bytes: Approximate size in bytes
    """
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    access_count: int = 0
    size_bytes: int = 0
    
    def access(self) -> None:
        """Mark entry as accessed."""
        self.accessed_at = time.time()
        self.access_count += 1


class FormulaInterningCache:
    """
    Formula interning cache to reduce memory usage.
    
    Ensures that identical formulas share the same object in memory,
    reducing memory footprint and enabling fast equality checks.
    """
    
    def __init__(self):
        """Initialize the formula interning cache."""
        self._cache: Dict[str, Any] = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "interned_count": 0
        }
    
    def intern(self, formula: Any) -> Any:
        """
        Intern a formula.
        
        Args:
            formula: Formula to intern
            
        Returns:
            Interned formula (may be same object or cached copy)
        """
        # Create hash key from formula
        key = self._get_formula_key(formula)
        
        if key in self._cache:
            self._stats["hits"] += 1
            return self._cache[key]
        else:
            self._stats["misses"] += 1
            self._cache[key] = formula
            self._stats["interned_count"] = len(self._cache)
            return formula
    
    def _get_formula_key(self, formula: Any) -> str:
        """
        Get cache key for formula.
        
        Args:
            formula: Formula object
            
        Returns:
            String key
        """
        # Use string representation for key
        formula_str = str(formula)
        return hashlib.md5(formula_str.encode()).hexdigest()
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        total_requests = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total_requests if total_requests > 0 else 0.0
        
        return {
            **self._stats,
            "total_requests": total_requests,
            "hit_rate": hit_rate
        }
    
    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "interned_count": 0
        }


class LRUCache:
    """
    Least Recently Used (LRU) cache implementation.
    
    Maintains a fixed-size cache that evicts least recently used items
    when capacity is reached.
    """
    
    def __init__(self, max_size: int = 1000):
        """
        Initialize LRU cache.
        
        Args:
            max_size: Maximum number of entries
        """
        self.max_size = max_size
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0
        }
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found
        """
        if key in self._cache:
            self._stats["hits"] += 1
            entry = self._cache[key]
            entry.access()
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            return entry.value
        else:
            self._stats["misses"] += 1
            return None
    
    def put(self, key: str, value: Any) -> None:
        """
        Put value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        if key in self._cache:
            # Update existing entry
            entry = self._cache[key]
            entry.value = value
            entry.access()
            self._cache.move_to_end(key)
        else:
            # Add new entry
            if len(self._cache) >= self.max_size:
                # Evict least recently used
                self._cache.popitem(last=False)
                self._stats["evictions"] += 1
            
            # Estimate size
            try:
                size_bytes = len(pickle.dumps(value))
            except:
                size_bytes = 0
            
            entry = CacheEntry(key=key, value=value, size_bytes=size_bytes)
            self._cache[key] = entry
    
    def contains(self, key: str) -> bool:
        """Check if key is in cache."""
        return key in self._cache
    
    def remove(self, key: str) -> bool:
        """
        Remove key from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if key was removed, False if not found
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False
    
    def clear(self) -> None:
        """Clear all entries from cache."""
        self._cache.clear()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0
        }
    
    @property
    def current_size(self) -> int:
        """Get current number of entries in cache."""
        return len(self._cache)
    
    def get_all_keys(self) -> List[str]:
        """Get all keys currently in cache."""
        return list(self._cache.keys())
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_requests = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total_requests if total_requests > 0 else 0.0
        
        total_size = sum(entry.size_bytes for entry in self._cache.values())
        
        return {
            **self._stats,
            "total_requests": total_requests,
            "hit_rate": hit_rate,
            "current_size": len(self._cache),
            "max_size": self.max_size,
            "total_bytes": total_size
        }
    
    def get_most_accessed(self, n: int = 10) -> List[Tuple[str, int]]:
        """
        Get most frequently accessed entries.
        
        Args:
            n: Number of entries to return
            
        Returns:
            List of (key, access_count) tuples
        """
        entries = [(k, e.access_count) for k, e in self._cache.items()]
        entries.sort(key=lambda x: x[1], reverse=True)
        return entries[:n]


class ProofResultCache:
    """
    Cache for proof results.
    
    Caches theorem proving results to avoid re-proving the same formulas.
    """
    
    def __init__(self, max_size: int = 500):
        """
        Initialize proof result cache.
        
        Args:
            max_size: Maximum number of cached proofs
        """
        self._cache = LRUCache(max_size=max_size)
    
    def get_proof(
        self,
        formula: Any,
        axioms: Optional[List[Any]] = None
    ) -> Optional[Any]:
        """
        Get cached proof result.
        
        Args:
            formula: Formula to prove
            axioms: Optional axioms used
            
        Returns:
            Cached proof result or None
        """
        key = self._make_key(formula, axioms)
        return self._cache.get(key)
    
    def cache_proof(
        self,
        formula: Any,
        axioms: Optional[List[Any]],
        result: Any
    ) -> None:
        """
        Cache a proof result.
        
        Args:
            formula: Formula that was proved
            axioms: Axioms used
            result: Proof result
        """
        key = self._make_key(formula, axioms)
        self._cache.put(key, result)
    
    def _make_key(self, formula: Any, axioms: Optional[List[Any]]) -> str:
        """
        Create cache key from formula and axioms.
        
        Args:
            formula: Formula
            axioms: Optional axioms
            
        Returns:
            String key
        """
        formula_str = str(formula)
        axioms_str = "" if axioms is None else str(sorted(str(a) for a in axioms))
        combined = f"{formula_str}|{axioms_str}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return self._cache.get_stats()

    def get_statistics(self) -> Dict[str, Any]:
        """Alias for get_stats() for API consistency."""
        return self.get_stats()

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()


class ParseResultCache:
    """
    Cache for natural language parsing results.
    
    Caches NL → formula parsing to avoid re-parsing same text.
    """
    
    def __init__(self, max_size: int = 1000):
        """
        Initialize parse result cache.
        
        Args:
            max_size: Maximum number of cached parse results
        """
        self._cache = LRUCache(max_size=max_size)
    
    def get_parse_result(self, text: str, language: str = "en") -> Optional[Any]:
        """
        Get cached parse result.
        
        Args:
            text: Natural language text
            language: Language code
            
        Returns:
            Cached parse result or None
        """
        key = self._make_key(text, language)
        return self._cache.get(key)
    
    def cache_parse_result(self, text: str, language: str, result: Any) -> None:
        """
        Cache a parse result.
        
        Args:
            text: Natural language text
            language: Language code
            result: Parse result
        """
        key = self._make_key(text, language)
        self._cache.put(key, result)
    
    def _make_key(self, text: str, language: str) -> str:
        """
        Create cache key from text and language.
        
        Args:
            text: Input text
            language: Language code
            
        Returns:
            String key
        """
        combined = f"{language}:{text}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return self._cache.get_stats()
    
    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()


class MemoizationCache:
    """
    General-purpose memoization cache with TTL support.
    
    Caches function results with optional time-to-live.
    """
    
    def __init__(self, max_size: int = 1000, ttl: Optional[float] = None):
        """
        Initialize memoization cache.
        
        Args:
            max_size: Maximum number of cached results
            ttl: Time-to-live in seconds (None for no expiration)
        """
        self._cache = LRUCache(max_size=max_size)
        self.ttl = ttl
    
    def memoize(self, func):
        """
        Decorator for memoizing function results.
        
        Args:
            func: Function to memoize
            
        Returns:
            Decorated function
        """
        def wrapper(*args, **kwargs):
            key = self._make_key(func.__name__, args, kwargs)
            
            # Check cache
            cached = self._cache.get(key)
            if cached is not None:
                # Check TTL if set
                if self.ttl is not None:
                    entry = self._cache._cache[key]
                    age = time.time() - entry.created_at
                    if age > self.ttl:
                        # Expired, remove and recompute
                        self._cache.remove(key)
                    else:
                        return cached
                else:
                    return cached
            
            # Compute and cache
            result = func(*args, **kwargs)
            self._cache.put(key, result)
            return result
        
        return wrapper
    
    def _make_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        """
        Create cache key from function name and arguments.
        
        Args:
            func_name: Function name
            args: Positional arguments
            kwargs: Keyword arguments
            
        Returns:
            String key
        """
        key_data = (func_name, args, tuple(sorted(kwargs.items())))
        key_str = str(key_data)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return self._cache.get_stats()
    
    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()


class CacheManager:
    """
    Central manager for all CEC caches.
    
    Provides unified interface to all caching systems.
    """
    
    def __init__(
        self,
        proof_cache_size: int = 500,
        parse_cache_size: int = 1000,
        memoization_cache_size: int = 1000
    ):
        """
        Initialize cache manager.
        
        Args:
            proof_cache_size: Size of proof result cache
            parse_cache_size: Size of parse result cache
            memoization_cache_size: Size of memoization cache
        """
        self.formula_interning = FormulaInterningCache()
        self.proof_cache = ProofResultCache(max_size=proof_cache_size)
        self.parse_cache = ParseResultCache(max_size=parse_cache_size)
        self.memoization = MemoizationCache(max_size=memoization_cache_size)
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Get statistics from all caches.
        
        Returns:
            Dictionary of cache statistics
        """
        return {
            "formula_interning": self.formula_interning.get_stats(),
            "proof_cache": self.proof_cache.get_stats(),
            "parse_cache": self.parse_cache.get_stats(),
            "memoization": self.memoization.get_stats()
        }
    
    def clear_all(self) -> None:
        """Clear all caches."""
        self.formula_interning.clear()
        self.proof_cache.clear()
        self.parse_cache.clear()
        self.memoization.clear()
