"""
Unified Proof Cache with CID (Content ID) Hashing and IPFS Backend Support

**UNIFIED CACHE (2026-02-14):** This module provides the unified caching layer
for ALL theorem provers and proof systems across the logic module, consolidating
the previously separate cache implementations in external_provers/, TDFOL/, and
integration/caching/.

**IPFS INTEGRATION (2026-02-19 - Phase 1 Task 1.3):** Added distributed caching
via IPFS router backend, enabling proof result sharing across nodes with automatic
fallback to local caching.

This module provides a high-performance caching layer for all theorem provers
using IPFS-native CID (Content Identifier) hashing for O(1) lookups, with optional
distributed storage via IPFS.

Features:
- CID-based content addressing (deterministic hashing)
- O(1) lookups using hash-based indexing
- Optional IPFS backend for distributed caching
- Automatic fallback to local cache if IPFS unavailable
- Thread-safe operations with RLock
- TTL-based expiration
- LRU eviction when cache is full
- Cache hit/miss statistics
- Support for all prover types (native, Z3, SymbolicAI, external, TDFOL, etc.)
- Persistence to disk (optional)
- Unified API across all proof systems

The cache key is computed as:
    CID(formula_canonical_representation + axioms + prover_config)

This ensures:
1. Same formula always produces same CID (deterministic)
2. Different formulas always produce different CIDs (collision-resistant)
3. O(1) lookup performance (hash-based)
4. IPFS-compatible addressing (can be stored on IPFS)

Usage:
    >>> from ipfs_datasets_py.logic.common import ProofCache, get_global_cache
    >>> 
    >>> # Local caching only
    >>> cache = ProofCache(maxsize=1000, ttl=3600)
    >>> 
    >>> # With IPFS backend for distributed caching
    >>> cache = ProofCache(maxsize=1000, ttl=3600, enable_ipfs_backend=True)
    >>> 
    >>> # Cache a proof result
    >>> result = prover.prove(formula)
    >>> cache.set(formula, result, prover_name="z3")
    >>> 
    >>> # Retrieve cached result (O(1) lookup, checks IPFS if enabled)
    >>> cached = cache.get(formula, prover_name="z3")
    >>> if cached:
    ...     print("Cache hit!")
    >>> 
    >>> # Or use the global singleton
    >>> global_cache = get_global_cache()
    >>> global_cache.set(formula, result, prover_name="lean")

Backward Compatibility:
    The module is used as the unified cache for:
    - external_provers.proof_cache.ProofCache
    - TDFOL.tdfol_proof_cache.TDFOLProofCache  
    - integration.caching.proof_cache.ProofCache
    
    All legacy imports are maintained via compatibility shims.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Union
from threading import RLock
import time
import logging
import json

try:
    from cachetools import TTLCache
    CACHETOOLS_AVAILABLE = True
except ImportError:
    CACHETOOLS_AVAILABLE = False
    TTLCache = None

try:
    from ipfs_datasets_py.utils.cid_utils import cid_for_obj, canonical_json_bytes
    CID_UTILS_AVAILABLE = True
except ImportError:
    CID_UTILS_AVAILABLE = False
    # Fallback to simple hashing
    import hashlib
    
    def cid_for_obj(obj: Any) -> str:
        """Fallback CID computation using SHA256."""
        json_str = json.dumps(obj, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()

# Import IPFS backend support (optional - Phase 1 Task 1.3)
try:
    from ipfs_datasets_py.caching.router_remote_cache import IPFSBackedRemoteCache
    from ipfs_datasets_py.ipfs_backend_router import get_ipfs_backend
    IPFS_BACKEND_AVAILABLE = True
except ImportError:
    IPFS_BACKEND_AVAILABLE = False
    IPFSBackedRemoteCache = None  # type: ignore
    get_ipfs_backend = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class CachedProofResult:
    """Cached proof result with metadata.
    
    Attributes:
        result: The actual proof result (any prover result type)
        cid: Content identifier (hash) of the query
        prover_name: Name of prover that produced this result
        formula_str: String representation of formula
        timestamp: When this result was cached
        hit_count: Number of times this result was retrieved
    """
    result: Any
    cid: str
    prover_name: str
    formula_str: str
    timestamp: float
    hit_count: int = 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'cid': self.cid,
            'prover_name': self.prover_name,
            'formula_str': self.formula_str,
            'timestamp': self.timestamp,
            'hit_count': self.hit_count,
            # result is not serialized (may contain non-serializable objects)
        }


class ProofCache:
    """Unified proof cache with CID-based content addressing.
    
    This cache provides O(1) lookups for proof results across all provers
    using IPFS-native CID hashing.
    
    Attributes:
        maxsize: Maximum number of cached proofs
        ttl: Time-to-live in seconds
        cache: Underlying cache storage (TTLCache if available)
        lock: Thread lock for safe concurrent access
        stats: Cache statistics
    """
    
    def __init__(
        self,
        maxsize: int = 1000,
        ttl: int = 3600,
        enable_persistence: bool = False,
        persistence_path: Optional[str] = None,
        enable_ipfs_backend: bool = False,
        ipfs_backend: Optional[Any] = None,
        ipfs_pin: bool = False,
        ipfs_ttl: Optional[int] = None,
        # Backward-compat aliases
        max_size: Optional[int] = None,
        default_ttl: Optional[int] = None,
    ):
        """Initialize proof cache with optional IPFS backend.
        
        Args:
            maxsize: Maximum number of cached proofs (default: 1000)
            ttl: Time-to-live in seconds for local cache (default: 3600 = 1 hour)
            enable_persistence: Whether to persist cache to disk
            persistence_path: Path for cache persistence
            enable_ipfs_backend: Enable IPFS-backed distributed caching (Phase 1 Task 1.3)
            ipfs_backend: Optional custom IPFS backend instance
            ipfs_pin: Whether to pin proof results in IPFS (permanent storage)
            ipfs_ttl: TTL for IPFS cache entries (None = no expiration)
        """
        # Apply compat aliases
        if max_size is not None:
            maxsize = max_size
        if default_ttl is not None:
            ttl = default_ttl
        self.maxsize = maxsize
        self.ttl = ttl
        # Backward-compat property aliases
        self.max_size = maxsize
        self.default_ttl = ttl
        self.enable_persistence = enable_persistence
        self.persistence_path = persistence_path
        self.enable_ipfs_backend = enable_ipfs_backend
        self.ipfs_pin = ipfs_pin
        self.ipfs_ttl = ipfs_ttl or ttl
        
        # Initialize cache storage
        if CACHETOOLS_AVAILABLE:
            self.cache = TTLCache(maxsize=maxsize, ttl=ttl)
        else:
            # Fallback to simple dict (no TTL or size limit)
            self.cache = {}
            logger.warning("cachetools not available, using simple dict cache")
        
        self.lock = RLock()
        # Backward-compat attributes (ordered dict for LRU)
        from collections import OrderedDict
        self._cache: dict = OrderedDict()
        self._compat_hits: int = 0
        self._compat_misses: int = 0
        self._compat_evictions: int = 0
        self._compat_expirations: int = 0
        self._compat_puts: int = 0
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'evictions': 0,
            'cid_collisions': 0,
            'ipfs_hits': 0,
            'ipfs_sets': 0,
            'ipfs_errors': 0,
        }
        
        # Initialize IPFS backend if requested (Phase 1 Task 1.3)
        self.ipfs_backend = None
        self.ipfs_cache = None
        if enable_ipfs_backend:
            if not IPFS_BACKEND_AVAILABLE:
                logger.warning(
                    "IPFS backend requested but ipfs_backend_router not available. "
                    "Falling back to local-only caching."
                )
            else:
                try:
                    # Get or create IPFS backend
                    backend = ipfs_backend or get_ipfs_backend()
                    
                    # Create local mapping cache for IPFS pointers
                    mapping_cache = {}  # Simple dict for CID -> IPFS pointer mapping
                    
                    # Initialize IPFS-backed cache
                    self.ipfs_cache = IPFSBackedRemoteCache(
                        mapping_cache=mapping_cache,
                        ipfs_backend=backend,
                        pin=ipfs_pin,
                        ttl_seconds=ipfs_ttl,
                        broadcast=True
                    )
                    self.ipfs_backend = backend
                    logger.info(
                        f"IPFS backend enabled with pin={ipfs_pin}, ttl={ipfs_ttl}s"
                    )
                except Exception as e:
                    logger.warning(f"Failed to initialize IPFS backend: {e}. "
                                 "Falling back to local-only caching.")
        
        logger.info(f"Initialized ProofCache with maxsize={maxsize}, ttl={ttl}s, "
                   f"ipfs_backend={enable_ipfs_backend}")
    
    def _compute_cid(
        self,
        formula,
        axioms: Optional[List] = None,
        prover_name: str = "unknown",
        prover_config: Optional[Dict] = None
    ) -> str:
        """Compute CID for a proof query.
        
        The CID is computed from:
        - Formula (canonical representation)
        - Axioms (if any)
        - Prover name
        - Prover configuration (if any)
        
        This ensures different queries get different CIDs.
        
        Args:
            formula: TDFOL formula or string
            axioms: Optional list of axioms
            prover_name: Name of prover
            prover_config: Optional prover configuration
            
        Returns:
            CID string (content identifier)
        """
        # Build canonical representation
        query_obj = {
            'formula': str(formula),
            'axioms': [str(a) for a in axioms] if axioms else [],
            'prover': prover_name,
            'config': prover_config or {}
        }
        
        # Compute CID
        try:
            cid = cid_for_obj(query_obj)
            return cid
        except Exception as e:
            logger.warning(f"CID computation failed, using fallback: {e}")
            # Fallback to simple hash
            import hashlib
            json_str = json.dumps(query_obj, sort_keys=True, default=str)
            return hashlib.sha256(json_str.encode()).hexdigest()
    
    def get(
        self,
        formula,
        axioms_or_prover=None,
        prover_name: str = None,
        prover_config: Optional[Dict] = None,
        *,
        axioms: Optional[List] = None,
    ) -> Optional[Any]:
        """Get cached proof result (O(1) lookup).

        Supports two call styles:
          - New API: get(formula, axioms=[], prover_name="z3")
          - Compat API: get(formula, "prover_name")
          - Keyword: get(formula, prover_name="z3")

        The second positional argument is interpreted as *axioms* when it is
        a list (or None) and as *prover_name* when it is a string.

        Args:
            formula: TDFOL formula or string
            axioms_or_prover: axioms list (new API) or prover_name string (compat API)
            prover_name: prover name (keyword arg takes priority over positional)
            prover_config: Optional prover configuration
            axioms: explicit axioms keyword arg (takes priority over positional)

        Returns:
            Cached proof result if found, None otherwise
        """
        # axioms= keyword arg takes priority over positional
        if axioms is not None:
            _axioms = axioms
            _prover_name = prover_name or (axioms_or_prover if isinstance(axioms_or_prover, str) else "unknown")
        elif prover_name is not None:
            # Explicit prover_name keyword
            _prover_name = prover_name
            _axioms = axioms_or_prover if isinstance(axioms_or_prover, list) else None
        elif isinstance(axioms_or_prover, str):
            # Compat API: get(formula, "prover_name")
            _prover_name = axioms_or_prover
            _axioms = None
        else:
            # New API: get(formula, axioms_list)
            _axioms = axioms_or_prover  # list or None
            _prover_name = "unknown"

        # Check compat cache first (formula::prover_name key)
        import time as _time
        key = self._make_key(str(formula), _prover_name)
        if key in self._cache:
            entry = self._cache[key]
            if entry._expires_at is not None and _time.monotonic() > entry._expires_at:
                del self._cache[key]
                self._compat_expirations += 1
                self._compat_misses += 1
            else:
                entry.hit_count += 1
                self._compat_hits += 1
                self._cache.move_to_end(key)
                self.stats['hits'] += 1
                return entry.result

        cid = self._compute_cid(formula, _axioms, _prover_name, prover_config)

        # Check CID-based local cache
        with self.lock:
            if cid in self.cache:
                cached = self.cache[cid]
                if hasattr(cached, 'hit_count'):
                    cached.hit_count += 1
                self.stats['hits'] += 1
                logger.debug(f"Local cache HIT for CID {cid[:16]}... (prover: {_prover_name})")
                return cached.result if hasattr(cached, 'result') else cached

        # If not in local cache and IPFS backend enabled, try IPFS
        if self.ipfs_cache is not None:
            try:
                ipfs_result = self.ipfs_cache.get(cid)
                if ipfs_result is not None:
                    with self.lock:
                        cached_result = CachedProofResult(
                            result=ipfs_result,
                            cid=cid,
                            prover_name=_prover_name,
                            formula_str=str(formula),
                            timestamp=time.time(),
                            hit_count=1
                        )
                        self.cache[cid] = cached_result
                        self.stats['ipfs_hits'] += 1
                        self.stats['hits'] += 1
                    logger.debug(f"IPFS cache HIT for CID {cid[:16]}... (prover: {_prover_name})")
                    return ipfs_result
            except Exception as e:
                logger.debug(f"IPFS cache lookup failed for CID {cid[:16]}...: {e}")
                with self.lock:
                    self.stats['ipfs_errors'] += 1

        # Not found in either cache
        self._compat_misses += 1
        with self.lock:
            self.stats['misses'] += 1
        logger.debug(f"Cache MISS for CID {cid[:16]}... (prover: {_prover_name})")
        return None

    def set(
        self,
        formula,
        result: Any,
        axioms: Optional[List] = None,
        prover_name: str = "unknown",
        prover_config: Optional[Dict] = None
    ) -> str:
        """Cache a proof result (O(1) insertion).
        
        Stores in local cache and optionally in IPFS backend if enabled.
        
        Args:
            formula: TDFOL formula or string
            result: Proof result to cache
            axioms: Optional list of axioms
            prover_name: Name of prover
            prover_config: Optional prover configuration
            
        Returns:
            CID of the cached entry
        """
        cid = self._compute_cid(formula, axioms, prover_name, prover_config)
        
        with self.lock:
            cached_result = CachedProofResult(
                result=result,
                cid=cid,
                prover_name=prover_name,
                formula_str=str(formula),
                timestamp=time.time(),
                hit_count=0
            )
            
            # Check if cache is full (for non-TTLCache)
            if not CACHETOOLS_AVAILABLE and len(self.cache) >= self.maxsize:
                # Simple LRU eviction: remove oldest entry
                oldest_cid = min(self.cache.keys(), key=lambda k: self.cache[k].timestamp)
                del self.cache[oldest_cid]
                self.stats['evictions'] += 1
            
            self.cache[cid] = cached_result
            self.stats['sets'] += 1
            logger.debug(f"Cached result in local cache with CID {cid[:16]}... (prover: {prover_name})")
        
        # Also store in IPFS backend if enabled
        if self.ipfs_cache is not None:
            try:
                # Serialize result for IPFS storage
                result_data = {
                    'result': result,
                    'prover_name': prover_name,
                    'formula_str': str(formula),
                    'timestamp': time.time(),
                    'cid': cid
                }
                self.ipfs_cache.set(cid, result_data)
                with self.lock:
                    self.stats['ipfs_sets'] += 1
                logger.debug(f"Cached result in IPFS with CID {cid[:16]}...")
            except Exception as e:
                logger.debug(f"IPFS cache storage failed for CID {cid[:16]}...: {e}")
                with self.lock:
                    self.stats['ipfs_errors'] += 1
        
        return cid
    
    def invalidate(
        self,
        formula,
        axioms: Optional[List] = None,
        prover_name: str = "unknown",
        prover_config: Optional[Dict] = None
    ) -> bool:
        """Invalidate a cached entry.
        
        Args:
            formula: TDFOL formula or string
            axioms: Optional list of axioms
            prover_name: Name of prover
            prover_config: Optional prover configuration
            
        Returns:
            True if entry was found and removed, False otherwise
        """
        cid = self._compute_cid(formula, axioms, prover_name, prover_config)
        
        with self.lock:
            if cid in self.cache:
                del self.cache[cid]
                logger.debug(f"Invalidated cache entry {cid[:16]}...")
                return True
            return False
    
    def clear(self):
        """Clear all cached entries. Returns the number of entries cleared."""
        with self.lock:
            count = len(self._cache) + len(self.cache)
            self.cache.clear()
            self._cache.clear()
            logger.info("Cache cleared")
            return count
    
    def get_stats(self) -> Dict:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache statistics including hit rate
        """
        with self.lock:
            total_requests = self.stats['hits'] + self.stats['misses']
            hit_rate = self.stats['hits'] / total_requests if total_requests > 0 else 0.0
            
            return {
                **self.stats,
                'total_requests': total_requests,
                'hit_rate': hit_rate,
                'cache_size': len(self.cache),
                'maxsize': self.maxsize,
                'ttl': self.ttl
            }
    

    # ------------------------------------------------------------------
    # Compat API (simple formula+prover_name key-value interface)
    # ------------------------------------------------------------------

    def _make_key(self, formula: str, prover_name: str) -> str:
        """Create compat cache key."""
        return f"{formula}::{prover_name}"

    def put(self, formula: str, prover_name: str, result: Any, ttl: int = None) -> None:
        """Simple compat put: store (formula, prover_name) → result."""
        import time as _time
        key = self._make_key(formula, prover_name)
        # LRU eviction if at capacity
        if self.max_size and len(self._cache) >= self.max_size and key not in self._cache:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            self._compat_evictions += 1
        effective_ttl = ttl if ttl is not None else self.default_ttl
        class _Entry:
            __slots__ = ('result', 'ttl', '_expires_at', 'hit_count', 'prover', 'formula', 'timestamp')
            def __init__(self, result, ttl, expires_at, prover, formula, timestamp):
                self.result = result
                self.ttl = ttl
                self._expires_at = expires_at
                self.hit_count = 0
                self.prover = prover
                self.formula = formula
                self.timestamp = timestamp
        self._cache[key] = _Entry(
            result=result,
            ttl=effective_ttl,
            expires_at=_time.monotonic() + effective_ttl if effective_ttl else None,
            prover=prover_name,
            formula=formula,
            timestamp=_time.monotonic(),
        )
        self._compat_puts += 1

    def compat_get(self, formula: str, prover_name: str = "unknown",
            axioms=None, prover_config=None) -> Any:
        """Retrieve a cached proof (compat API — checks compat cache, CID cache, then IPFS)."""
        import time as _time
        key = self._make_key(formula, prover_name)
        if key in self._cache:
            entry = self._cache[key]
            # Check TTL expiration
            if entry._expires_at is not None and _time.monotonic() > entry._expires_at:
                del self._cache[key]
                self._compat_expirations += 1
                self._compat_misses += 1
            else:
                entry.hit_count += 1
                self._compat_hits += 1
                self._cache.move_to_end(key)
                return entry.result

        # Check CID-based local cache
        cid = self._compute_cid(formula, axioms, prover_name, prover_config)
        with self.lock:
            if cid in self.cache:
                cached = self.cache[cid]
                if hasattr(cached, 'hit_count'):
                    cached.hit_count += 1
                self.stats['hits'] += 1
                return cached.result if hasattr(cached, 'result') else cached

        # Check IPFS backend if enabled
        if self.ipfs_cache is not None:
            try:
                ipfs_result = self.ipfs_cache.get(cid)
                if ipfs_result is not None:
                    with self.lock:
                        cached_result = CachedProofResult(
                            result=ipfs_result,
                            cid=cid,
                            prover_name=prover_name,
                            formula_str=str(formula),
                            timestamp=time.time(),
                            hit_count=1
                        )
                        self.cache[cid] = cached_result
                        self.stats['ipfs_hits'] += 1
                        self.stats['hits'] += 1
                    return ipfs_result
            except Exception as e:
                logger.debug(f"IPFS cache lookup failed: {e}")
                with self.lock:
                    self.stats['ipfs_errors'] += 1

        # Not found in any cache
        self._compat_misses += 1
        with self.lock:
            self.stats['misses'] += 1
        return None

    def invalidate(self, formula: str, prover_name: str = "unknown") -> bool:
        """Remove a cached entry."""
        key = self._make_key(formula, prover_name)
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        import time as _time
        now = _time.monotonic()
        expired_keys = [
            k for k, v in list(self._cache.items())
            if v._expires_at is not None and now > v._expires_at
        ]
        for k in expired_keys:
            del self._cache[k]
        self._compat_expirations += len(expired_keys)
        return len(expired_keys)

    def get_cached_entries(self):
        """Return list of cached entry metadata."""
        return [
            {
                "formula": v.formula,
                "prover": v.prover,
                "hit_count": v.hit_count,
                "timestamp": v.timestamp,
                "ttl": v.ttl,
            }
            for v in self._cache.values()
        ]

    def resize(self, new_size: int) -> None:
        """Resize the cache, evicting oldest entries if needed."""
        self.max_size = new_size
        self.maxsize = new_size
        while len(self._cache) > new_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            self._compat_evictions += 1

    def get_statistics(self) -> Dict:
        """Return unified statistics dict (compat API)."""
        total = self._compat_hits + self._compat_misses
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._compat_hits,
            "misses": self._compat_misses,
            "hit_rate": (self._compat_hits / total) if total > 0 else 0.0,
            "evictions": self._compat_evictions,
            "expirations": self._compat_expirations,
            "total_puts": self._compat_puts,
            # Also include CID-based stats
            "cache_size": len(self.cache),
        }

    def get_info(self, cid: str) -> Optional[Dict]:
        """Get information about a cached entry.
        
        Args:
            cid: Content identifier
            
        Returns:
            Dictionary with entry information, or None if not found
        """
        with self.lock:
            if cid in self.cache:
                return self.cache[cid].to_dict()
            return None


# Global cache instance (singleton)
_global_proof_cache: Optional[ProofCache] = None


def get_global_cache(
    maxsize: int = 1000,
    ttl: int = 3600
) -> ProofCache:
    """Get or create global proof cache instance.
    
    Args:
        maxsize: Maximum cache size (only used if creating new cache)
        ttl: Time-to-live in seconds (only used if creating new cache)
        
    Returns:
        Global ProofCache instance
    """
    global _global_proof_cache
    
    if _global_proof_cache is None:
        _global_proof_cache = ProofCache(maxsize=maxsize, ttl=ttl)
    
    return _global_proof_cache


def cache_proof_result(func):
    """Decorator to cache proof results.
    
    Usage:
        @cache_proof_result
        def prove(self, formula, axioms=None):
            # ... proving logic ...
            return result
    """
    from functools import wraps
    
    @wraps(func)
    def wrapper(self, formula, axioms=None, *args, **kwargs):
        # Get prover name
        prover_name = getattr(self, '__class__', type(self)).__name__
        
        # Try to get from cache
        cache = get_global_cache()
        cached_result = cache.get(
            formula,
            axioms=axioms,
            prover_name=prover_name,
            prover_config=kwargs
        )
        
        if cached_result is not None:
            return cached_result
        
        # Not in cache, compute result
        result = func(self, formula, axioms, *args, **kwargs)
        
        # Cache the result
        cache.set(
            formula,
            result,
            axioms=axioms,
            prover_name=prover_name,
            prover_config=kwargs
        )
        
        return result
    
    return wrapper


__all__ = [
    'ProofCache',
    'CachedProofResult',
    'get_global_cache',
    'cache_proof_result',
]
