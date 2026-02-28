"""
F-logic proof / query cache.

Integrates F-logic (ErgoAI) query results with the unified
:class:`~ipfs_datasets_py.logic.common.proof_cache.ProofCache`, preventing
redundant re-execution of identical queries against the same ontology.

The cache key is built from::

    CID(ergo_program_canonical + goal_canonical + prover_name)

which mirrors the scheme used by
:mod:`ipfs_datasets_py.logic.CEC.native.cec_proof_cache`.

Example::

    from ipfs_datasets_py.logic.flogic.flogic_proof_cache import CachedErgoAIWrapper
    from ipfs_datasets_py.logic.flogic import FLogicClass, FLogicFrame

    ergo = CachedErgoAIWrapper()
    ergo.add_class(FLogicClass("Dog", superclasses=["Animal"]))
    ergo.add_frame(FLogicFrame("rex", isa="Dog"))

    # First call — cache miss, result stored
    r1 = ergo.query("?X : Dog")

    # Second call — cache hit, O(1) lookup
    r2 = ergo.query("?X : Dog")
    assert r2.from_cache
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, List, Optional, Sequence

from .ergoai_wrapper import ErgoAIWrapper
from .flogic_types import FLogicClass, FLogicFrame, FLogicOntology, FLogicQuery, FLogicStatus

# Import the unified proof cache (optional dep)
try:
    from ..common.proof_cache import ProofCache, get_global_cache
    _HAVE_CACHE = True
except ImportError:
    ProofCache = None  # type: ignore
    get_global_cache = None  # type: ignore
    _HAVE_CACHE = False

logger = logging.getLogger(__name__)

_PROVER_NAME = "ergoai_flogic"


# ---------------------------------------------------------------------------
# Cached result type
# ---------------------------------------------------------------------------


@dataclass
class FLogicCachedQueryResult:
    """
    Cached result of an F-logic query.

    Attributes:
        goal: The original query string.
        status: :class:`~ipfs_datasets_py.logic.flogic.flogic_types.FLogicStatus`.
        bindings: Variable bindings returned by the query.
        execution_time: Seconds taken by the underlying prover.
        from_cache: ``True`` when this result was retrieved from the cache.
        error_message: Human-readable error (if status is ERROR).
        timestamp: Unix timestamp of when this result was computed.
    """

    goal: str
    status: FLogicStatus
    bindings: List[Dict[str, Any]] = field(default_factory=list)
    execution_time: float = 0.0
    from_cache: bool = False
    error_message: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def from_query(
        cls,
        result: FLogicQuery,
        execution_time: float = 0.0,
    ) -> "FLogicCachedQueryResult":
        """Build from a :class:`~ipfs_datasets_py.logic.flogic.flogic_types.FLogicQuery`."""
        return cls(
            goal=result.goal,
            status=result.status,
            bindings=list(result.bindings),
            execution_time=execution_time,
            error_message=result.error_message,
        )

    def to_flogic_query(self) -> FLogicQuery:
        """Reconstruct the original :class:`FLogicQuery`."""
        return FLogicQuery(
            goal=self.goal,
            bindings=list(self.bindings),
            status=self.status,
            error_message=self.error_message,
        )


# ---------------------------------------------------------------------------
# Cached wrapper
# ---------------------------------------------------------------------------


class CachedErgoAIWrapper(ErgoAIWrapper):
    """
    :class:`~ipfs_datasets_py.logic.flogic.ergoai_wrapper.ErgoAIWrapper`
    extended with automatic proof / query caching.

    On each :meth:`query` call:

    1. Check the unified :class:`~ipfs_datasets_py.logic.common.proof_cache.ProofCache`.
    2. On a **hit** return the cached :class:`FLogicCachedQueryResult` immediately.
    3. On a **miss** run the underlying prover and persist the result.

    The ontology program is included in the cache key so that adding new frames
    or rules correctly invalidates old cached results.

    Args:
        cache_size: Maximum number of entries in a private cache
            (ignored when ``use_global_cache=True``).
        cache_ttl: Time-to-live in seconds (``0`` = no expiry).
        use_global_cache: When ``True``, share the process-wide
            :func:`~ipfs_datasets_py.logic.common.proof_cache.get_global_cache` singleton.
        enable_caching: Set to ``False`` to disable caching entirely (useful
            in tests).
        ontology_name: Forwarded to
            :class:`~ipfs_datasets_py.logic.flogic.ergoai_wrapper.ErgoAIWrapper`.
        binary: Forwarded to
            :class:`~ipfs_datasets_py.logic.flogic.ergoai_wrapper.ErgoAIWrapper`.
    """

    def __init__(
        self,
        cache_size: int = 1000,
        cache_ttl: int = 3600,
        use_global_cache: bool = True,
        enable_caching: bool = True,
        ontology_name: str = "default",
        binary=None,
    ) -> None:
        super().__init__(ontology_name=ontology_name, binary=binary)

        self.enable_caching = enable_caching and _HAVE_CACHE

        if self.enable_caching:
            if use_global_cache:
                self._cache = get_global_cache()
                logger.info("F-logic: using global proof cache")
            else:
                self._cache = ProofCache(maxsize=cache_size, ttl=cache_ttl)
                logger.info(
                    "F-logic: created local proof cache (size=%d, ttl=%ds)",
                    cache_size,
                    cache_ttl,
                )
        else:
            self._cache = None
            if not _HAVE_CACHE:
                logger.warning(
                    "F-logic proof cache unavailable — install cachetools"
                )

        self._hits = 0
        self._misses = 0
        self._lock = RLock()

    # ------------------------------------------------------------------
    # Overridden query methods
    # ------------------------------------------------------------------

    def query(self, goal: str) -> FLogicCachedQueryResult:  # type: ignore[override]
        """
        Execute a query, returning a cached result where possible.

        Returns:
            :class:`FLogicCachedQueryResult` with ``from_cache=True`` on a hit.
        """
        if self.enable_caching and self._cache is not None:
            cached = self._get_from_cache(goal)
            if cached is not None:
                with self._lock:
                    self._hits += 1
                cached.from_cache = True
                return cached
            with self._lock:
                self._misses += 1

        start = time.monotonic()
        raw: FLogicQuery = super().query(goal)
        elapsed = time.monotonic() - start

        result = FLogicCachedQueryResult.from_query(raw, execution_time=elapsed)

        if self.enable_caching and self._cache is not None:
            self._put_in_cache(goal, result)

        return result

    def batch_query(self, goals: Sequence[str]) -> List[FLogicCachedQueryResult]:  # type: ignore[override]
        """Execute multiple goals with per-goal caching."""
        return [self.query(g) for g in goals]

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_key_for(self, goal: str) -> str:
        """
        Build the cache formula key: ``sha256(program)|goal``.

        We hash the ontology program text so that the key construction is
        O(n) in program length at most once per ontology state, rather than
        concatenating large strings on every cache lookup.
        """
        import hashlib
        prog_hash = hashlib.sha256(self.get_program().encode()).hexdigest()[:16]
        return f"{prog_hash}|{goal}"

    def _get_from_cache(self, goal: str) -> Optional[FLogicCachedQueryResult]:
        if self._cache is None:
            return None
        try:
            key = self._cache_key_for(goal)
            cached = self._cache.get(
                formula=key,
                prover_name=_PROVER_NAME,
            )
            if cached is None:
                return None
            if isinstance(cached, FLogicCachedQueryResult):
                return cached
            # Wrapped in CachedProofResult
            inner = getattr(cached, "result", cached)
            if isinstance(inner, FLogicCachedQueryResult):
                return inner
        except Exception as exc:
            logger.warning("F-logic cache lookup error: %s", exc)
        return None

    def _put_in_cache(self, goal: str, result: FLogicCachedQueryResult) -> None:
        if self._cache is None:
            return
        try:
            key = self._cache_key_for(goal)
            self._cache.set(
                formula=key,
                result=result,
                prover_name=_PROVER_NAME,
            )
        except Exception as exc:
            logger.warning("F-logic cache store error: %s", exc)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_cache_statistics(self) -> Dict[str, Any]:
        """Return cache hit/miss statistics."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "cache_enabled": self.enable_caching,
                "hits": self._hits,
                "misses": self._misses,
                "total": total,
                "hit_rate": self._hits / total if total > 0 else 0.0,
            }

    def clear_cache(self) -> None:
        """Clear the proof cache and reset statistics."""
        if self._cache is not None:
            self._cache.clear()
        with self._lock:
            self._hits = 0
            self._misses = 0

    def get_statistics(self) -> Dict[str, Any]:
        """Combined ergoai + cache statistics."""
        stats = super().get_statistics()
        stats.update(self.get_cache_statistics())
        return stats


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_global_cached_wrapper: Optional[CachedErgoAIWrapper] = None


def get_global_cached_wrapper() -> CachedErgoAIWrapper:
    """
    Return (or create) the process-wide :class:`CachedErgoAIWrapper` singleton.

    Uses the same global :class:`~ipfs_datasets_py.logic.common.proof_cache.ProofCache`
    as the CEC and TDFOL provers, so all logic systems share a single cache.
    """
    global _global_cached_wrapper
    if _global_cached_wrapper is None:
        _global_cached_wrapper = CachedErgoAIWrapper(use_global_cache=True)
    return _global_cached_wrapper


__all__ = [
    "FLogicCachedQueryResult",
    "CachedErgoAIWrapper",
    "get_global_cached_wrapper",
    "_HAVE_CACHE",
]
