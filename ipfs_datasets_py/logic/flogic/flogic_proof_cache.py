"""
F-logic proof / query cache.

Integrates F-logic (ErgoAI) query results with the unified
:class:`~ipfs_datasets_py.logic.common.proof_cache.ProofCache`, preventing
redundant re-execution of identical queries against the same ontology.

The cache key is a proper **IPFS CID** computed from::

    CID({"prover": "ergoai_flogic",
         "program_cid": CID(ontology_program_bytes),
         "goal": normalized_goal})

which mirrors the scheme used by ``ProofCache._compute_cid()`` and is
compatible with distributed IPFS-backed caching.

An optional :class:`~ipfs_datasets_py.logic.flogic.semantic_normalizer.SemanticNormalizer`
is applied to the goal before key computation so that semantically
equivalent queries (e.g. ``"?X : Canine"`` vs ``"?X : Dog"``) share the
same cache entry.

Example::

    from ipfs_datasets_py.logic.flogic.flogic_proof_cache import CachedErgoAIWrapper
    from ipfs_datasets_py.logic.flogic import FLogicClass, FLogicFrame

    ergo = CachedErgoAIWrapper()
    ergo.add_class(FLogicClass("Dog", superclasses=["Animal"]))
    ergo.add_frame(FLogicFrame("rex", isa="Dog"))

    # First call — cache miss, result stored with IPFS CID key
    r1 = ergo.query("?X : Dog")

    # Second call — cache hit, O(1) CID lookup
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

# Import IPFS CID utilities (optional dep — falls back to SHA-256)
try:
    from ipfs_datasets_py.utils.cid_utils import cid_for_obj as _cid_for_obj_impl
    # Verify multiformats is actually callable (lazy import inside cid_for_bytes)
    try:
        _cid_for_obj_impl({"_test": True})
        _HAVE_CID = True
        cid_for_obj = _cid_for_obj_impl  # type: ignore[assignment]
    except Exception:
        _HAVE_CID = False
        raise ImportError("multiformats not available")
except ImportError:
    _HAVE_CID = False
    import hashlib as _hashlib
    import json as _json

    def cid_for_obj(obj: Any, **_kwargs) -> str:  # type: ignore[misc]
        """SHA-256 fallback when multiformats is not installed."""
        data = _json.dumps(obj, sort_keys=True, separators=(",", ":"), default=repr)
        return _hashlib.sha256(data.encode()).hexdigest()

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
        cache_cid: IPFS CID of the cache entry (set when stored).
    """

    goal: str
    status: FLogicStatus
    bindings: List[Dict[str, Any]] = field(default_factory=list)
    execution_time: float = 0.0
    from_cache: bool = False
    error_message: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    cache_cid: Optional[str] = None

    @classmethod
    def from_query(
        cls,
        result: FLogicQuery,
        execution_time: float = 0.0,
        cache_cid: Optional[str] = None,
    ) -> "FLogicCachedQueryResult":
        """Build from a :class:`~ipfs_datasets_py.logic.flogic.flogic_types.FLogicQuery`."""
        return cls(
            goal=result.goal,
            status=result.status,
            bindings=list(result.bindings),
            execution_time=execution_time,
            error_message=result.error_message,
            cache_cid=cache_cid,
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
    extended with automatic proof / query caching and semantic normalization.

    On each :meth:`query` call:

    1. Optionally normalise the goal via
       :class:`~ipfs_datasets_py.logic.flogic.semantic_normalizer.SemanticNormalizer`
       so that semantic synonyms share the same cache entry.
    2. Compute an **IPFS CID** for ``(ontology_program, normalized_goal)``.
    3. Check the unified :class:`~ipfs_datasets_py.logic.common.proof_cache.ProofCache`.
    4. On a **hit** return the cached :class:`FLogicCachedQueryResult` immediately.
    5. On a **miss** run the underlying prover and persist the result.

    Args:
        cache_size: Maximum number of entries in a private cache
            (ignored when ``use_global_cache=True``).
        cache_ttl: Time-to-live in seconds (``0`` = no expiry).
        use_global_cache: When ``True``, share the process-wide
            :func:`~ipfs_datasets_py.logic.common.proof_cache.get_global_cache` singleton.
        enable_caching: Set to ``False`` to disable caching entirely.
        normalizer: Optional
            :class:`~ipfs_datasets_py.logic.flogic.semantic_normalizer.SemanticNormalizer`
            instance.  When ``None``, a default (SymAI-enabled) normalizer is
            created lazily on first use.
        enable_normalization: Set to ``False`` to skip semantic normalization.
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
        normalizer=None,
        enable_normalization: bool = True,
        ontology_name: str = "default",
        binary=None,
    ) -> None:
        super().__init__(ontology_name=ontology_name, binary=binary)

        self.enable_caching = enable_caching and _HAVE_CACHE
        self.enable_normalization = enable_normalization
        self._normalizer = normalizer  # lazily initialized if None

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
    # Semantic normalizer (lazy init)
    # ------------------------------------------------------------------

    @property
    def normalizer(self):
        """Return the :class:`~ipfs_datasets_py.logic.flogic.semantic_normalizer.SemanticNormalizer`."""
        if self._normalizer is None:
            try:
                from .semantic_normalizer import SemanticNormalizer
                self._normalizer = SemanticNormalizer()
            except Exception:
                self._normalizer = _NoopNormalizer()
        return self._normalizer

    def _normalize(self, goal: str) -> str:
        """Return the canonical form of *goal* (or *goal* itself if disabled)."""
        if not self.enable_normalization:
            return goal
        try:
            return self.normalizer.normalize_goal(goal)
        except Exception as exc:
            logger.debug("Goal normalization failed: %s", exc)
            return goal

    # ------------------------------------------------------------------
    # Overridden query methods
    # ------------------------------------------------------------------

    def query(self, goal: str) -> FLogicCachedQueryResult:  # type: ignore[override]
        """
        Execute a query, returning a cached result where possible.

        The goal is semantically normalized before cache key computation.

        Returns:
            :class:`FLogicCachedQueryResult` with ``from_cache=True`` on a hit
            and ``cache_cid`` populated with the IPFS CID of the cache entry.
        """
        normalized_goal = self._normalize(goal)

        if self.enable_caching and self._cache is not None:
            cached = self._get_from_cache(normalized_goal)
            if cached is not None:
                with self._lock:
                    self._hits += 1
                cached.from_cache = True
                # Preserve the original (un-normalized) goal in the result
                cached.goal = goal
                return cached
            with self._lock:
                self._misses += 1

        start = time.monotonic()
        raw: FLogicQuery = super().query(goal)
        elapsed = time.monotonic() - start

        cid = self._compute_entry_cid(normalized_goal)
        result = FLogicCachedQueryResult.from_query(raw, execution_time=elapsed, cache_cid=cid)

        if self.enable_caching and self._cache is not None:
            self._put_in_cache(normalized_goal, result)

        return result

    def batch_query(self, goals: Sequence[str]) -> List[FLogicCachedQueryResult]:  # type: ignore[override]
        """Execute multiple goals with per-goal caching."""
        return [self.query(g) for g in goals]

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _compute_entry_cid(self, normalized_goal: str) -> str:
        """
        Compute the **IPFS CID** that identifies this (ontology, goal) pair.

        Uses :func:`ipfs_datasets_py.utils.cid_utils.cid_for_obj` when
        ``multiformats`` is installed, falling back to SHA-256.

        The object fed to ``cid_for_obj`` is::

            {
                "prover": "ergoai_flogic",
                "program_cid": CID(ontology_program_utf8),
                "goal": normalized_goal
            }
        """
        # First compute the CID of the ontology program itself so that any
        # change to the ontology produces a different composite CID.
        # The program is generated internally and is always valid UTF-8, so
        # we can decode strictly and let any unexpected error fall through to
        # the except clause where we use a SHA-256 fallback.
        prog_bytes = self.get_program().encode()
        try:
            prog_cid = cid_for_obj({"data": prog_bytes.decode()})
        except Exception:
            import hashlib
            prog_cid = hashlib.sha256(prog_bytes).hexdigest()

        obj = {
            "prover": _PROVER_NAME,
            "program_cid": prog_cid,
            "goal": normalized_goal,
        }
        return cid_for_obj(obj)

    def _cache_key_for(self, normalized_goal: str) -> str:
        """Return the IPFS CID used as the formula key in the ProofCache."""
        return self._compute_entry_cid(normalized_goal)

    def _get_from_cache(self, normalized_goal: str) -> Optional[FLogicCachedQueryResult]:
        if self._cache is None:
            return None
        try:
            key = self._cache_key_for(normalized_goal)
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

    def _put_in_cache(self, normalized_goal: str, result: FLogicCachedQueryResult) -> None:
        if self._cache is None:
            return
        try:
            key = self._cache_key_for(normalized_goal)
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
                "cid_backend": "ipfs_multiformats" if _HAVE_CID else "sha256_fallback",
                "normalization_enabled": self.enable_normalization,
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
# Internal helpers
# ---------------------------------------------------------------------------


class _NoopNormalizer:
    """Minimal fallback normalizer that leaves goals unchanged."""

    @staticmethod
    def normalize_goal(goal: str) -> str:
        return goal

    @staticmethod
    def normalize_term(term: str) -> str:
        return term.lower()


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
    "_HAVE_CID",
]
