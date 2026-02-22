"""Backward-compatible proof cache with LRU eviction and per-entry TTL.

This module provides the legacy proof-cache API used by existing tests and
benchmarks.  New code should prefer ``ipfs_datasets_py.logic.common.proof_cache``.

Public API (legacy):
    - :class:`CachedProof`  – single cached proof entry
    - :class:`ProofCache`   – LRU+TTL cache with statistics
    - :func:`get_global_cache` – process-wide singleton

The class accepted keyword argument spellings historically used in this repo
are: ``max_size`` (≡ ``maxsize``), ``default_ttl`` (≡ ``ttl``).
``ProofCache.put(formula, prover, result, *, ttl=None)`` is the legacy write API;
``ProofCache.get(formula, prover)`` is the legacy read API.  Both 2-arg and
3-arg forms of ``put`` / ``get`` are accepted so that callers that omit
the *prover* argument still work.
"""

from __future__ import annotations

import time
import threading
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "CachedProof",
    "ProofCache",
    "get_global_cache",
]

# ---------------------------------------------------------------------------
# CachedProof
# ---------------------------------------------------------------------------

@dataclass
class CachedProof:
    """Single cached proof result.

    Fields
    ------
    formula_hash : str
        A key / hash identifying the formula (caller-supplied string).
    prover : str
        Name of the prover that produced this result.
    result_data : dict
        The serialisable proof result payload.
    timestamp : float
        Unix time when this entry was stored.
    ttl : float
        Time-to-live in seconds; 0 means *never expires* (default 3600).
    hit_count : int
        Number of times this entry has been retrieved.
    metadata : dict, optional
        Arbitrary extra metadata.
    """

    formula_hash: str
    prover: str
    result_data: Dict[str, Any]
    timestamp: float
    ttl: float = 3600.0
    hit_count: int = 0
    metadata: Optional[Dict[str, Any]] = None

    def is_expired(self) -> bool:
        """Return True iff this entry's TTL has elapsed."""
        if self.ttl == 0:
            return False
        return (time.time() - self.timestamp) > self.ttl

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "formula_hash": self.formula_hash,
            "prover": self.prover,
            "result_data": self.result_data,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
            "hit_count": self.hit_count,
            "metadata": self.metadata or {},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CachedProof":
        """Reconstruct a CachedProof from a plain dict."""
        return cls(
            formula_hash=data["formula_hash"],
            prover=data["prover"],
            result_data=data.get("result_data", {}),
            timestamp=data.get("timestamp", time.time()),
            ttl=float(data.get("ttl", 3600)),
            hit_count=int(data.get("hit_count", 0)),
            metadata=data.get("metadata"),
        )


# ---------------------------------------------------------------------------
# ProofCache
# ---------------------------------------------------------------------------

class ProofCache:
    """LRU + TTL proof-result cache.

    Parameters
    ----------
    max_size / maxsize : int
        Maximum number of entries (default 1000).
    default_ttl / ttl : float
        Default time-to-live for each entry in seconds (default 3600).
    """

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: float = 3600.0,
        # forward-compat aliases
        maxsize: Optional[int] = None,
        ttl: Optional[float] = None,
        **_kwargs: Any,
    ) -> None:
        # Accept both old (max_size/default_ttl) and new (maxsize/ttl) kwargs
        self._max_size: int = int(maxsize if maxsize is not None else max_size)
        self._default_ttl: float = float(ttl if ttl is not None else default_ttl)
        # ordered so that LRU eviction (pop first item) works correctly
        self._cache: OrderedDict[str, CachedProof] = OrderedDict()
        self._lock = threading.RLock()
        # statistics
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0
        self._expirations: int = 0
        self._total_puts: int = 0

    # ------------------------------------------------------------------
    # Properties for backward compatibility
    # ------------------------------------------------------------------

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def default_ttl(self) -> float:
        return self._default_ttl

    # ------------------------------------------------------------------
    # Key construction
    # ------------------------------------------------------------------

    def _make_key(self, formula: str, prover: str = "") -> str:
        return f"{formula}||{prover}"

    # ------------------------------------------------------------------
    # Write / Read
    # ------------------------------------------------------------------

    def put(
        self,
        formula: str,
        prover_or_result: Any = None,
        result: Optional[Any] = None,
        *,
        ttl: Optional[float] = None,
    ) -> None:
        """Store a proof result.

        Accepts two call signatures:

        * 3-arg: ``put(formula, prover, result, *, ttl=None)``
        * 2-arg: ``put(formula, result, *, ttl=None)``  (prover defaults to "")
        """
        if result is None:
            # 2-arg form: put(formula, result)
            prover_name = ""
            result_data = prover_or_result if prover_or_result is not None else {}
        else:
            # 3-arg form: put(formula, prover, result)
            prover_name = str(prover_or_result) if prover_or_result is not None else ""
            result_data = result

        entry_ttl = float(ttl) if ttl is not None else self._default_ttl
        key = self._make_key(formula, prover_name)
        cached = CachedProof(
            formula_hash=key,
            prover=prover_name,
            result_data=result_data if isinstance(result_data, dict) else {"value": result_data},
            timestamp=time.time(),
            ttl=entry_ttl,
        )

        with self._lock:
            # If key already exists, remove it (re-insert at end to mark as MRU)
            if key in self._cache:
                del self._cache[key]
            # Evict LRU entry if over capacity
            while len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
                self._evictions += 1
            self._cache[key] = cached
            self._total_puts += 1

    # Forward-compat alias used by new API callers
    def set(
        self,
        formula: str,
        result: Any = None,
        *,
        prover_name: str = "",
        ttl: Optional[float] = None,
    ) -> None:
        self.put(formula, prover_name, result, ttl=ttl)

    def get(
        self,
        formula: str,
        prover: Optional[str] = None,
        *,
        prover_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a cached result dict or None on miss/expiry."""
        effective_prover = prover if prover is not None else (prover_name or "")
        key = self._make_key(formula, effective_prover)

        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired():
                del self._cache[key]
                self._expirations += 1
                self._misses += 1
                return None
            # Mark as recently used (MRU)
            self._cache.move_to_end(key)
            entry.hit_count += 1
            self._hits += 1
            return entry.result_data

    # ------------------------------------------------------------------
    # Invalidation / clearing
    # ------------------------------------------------------------------

    def invalidate(self, formula: str, prover: str = "") -> bool:
        """Remove a single entry; return True if it existed."""
        key = self._make_key(formula, prover)
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> int:
        """Remove all entries; return number removed."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def cleanup_expired(self) -> int:
        """Remove all expired entries; return count removed."""
        removed = 0
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
            for k in expired_keys:
                del self._cache[k]
                removed += 1
            self._expirations += removed
        return removed

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        """Return a statistics snapshot."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "evictions": self._evictions,
                "expirations": self._expirations,
                "total_puts": self._total_puts,
            }

    # Forward-compat alias
    def get_stats(self) -> Dict[str, Any]:
        return self.get_statistics()

    def get_cached_entries(self) -> List[Dict[str, Any]]:
        """Return summary dicts for all non-expired entries."""
        with self._lock:
            return [
                {
                    "formula_hash": v.formula_hash,
                    "prover": v.prover,
                    "timestamp": v.timestamp,
                    "hit_count": v.hit_count,
                    "ttl": v.ttl,
                }
                for v in self._cache.values()
                if not v.is_expired()
            ]

    # ------------------------------------------------------------------
    # Resize
    # ------------------------------------------------------------------

    def resize(self, new_size: int) -> None:
        """Change the maximum capacity, evicting LRU entries if needed."""
        new_size = int(new_size)
        with self._lock:
            while len(self._cache) > new_size:
                self._cache.popitem(last=False)
                self._evictions += 1
            self._max_size = new_size

    # ------------------------------------------------------------------
    # Forward-compat: get_info
    # ------------------------------------------------------------------

    def get_info(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._cache.get(key)
            return entry.to_dict() if entry else None


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_GLOBAL_CACHE: Optional[ProofCache] = None
_GLOBAL_LOCK = threading.Lock()


def get_global_cache(maxsize: int = 1000, ttl: float = 3600.0) -> ProofCache:
    """Return the process-wide ProofCache singleton (created on first call)."""
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None:
        with _GLOBAL_LOCK:
            if _GLOBAL_CACHE is None:
                _GLOBAL_CACHE = ProofCache(max_size=maxsize, default_ttl=ttl)
    return _GLOBAL_CACHE
