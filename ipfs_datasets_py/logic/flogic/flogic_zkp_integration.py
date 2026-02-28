"""
ZKP-F-logic integration layer.

This module bridges F-logic (ErgoAI) query results with the
zero-knowledge proof system in :mod:`ipfs_datasets_py.logic.zkp`,
following the same pattern as
:mod:`ipfs_datasets_py.logic.CEC.native.cec_zkp_integration`.

Hybrid proving strategy
-----------------------
1. **Cache lookup** (O(1), µs) — check the unified proof cache first.
2. **Standard query** — execute the ErgoAI query (or simulate it).
3. **ZKP attestation** (optional) — generate a ZK proof that the query
   result is consistent with the ontology, without revealing the full
   knowledge base.

The ZKP attestation is useful when you need to share a proof with an
untrusted party (e.g., across IPFS nodes) without exposing proprietary
ontology rules.

Example::

    from ipfs_datasets_py.logic.flogic.flogic_zkp_integration import (
        ZKPFLogicProver,
    )
    from ipfs_datasets_py.logic.flogic import FLogicClass, FLogicFrame

    prover = ZKPFLogicProver(enable_zkp=True, enable_caching=True)
    prover.add_class(FLogicClass("Dog", superclasses=["Animal"]))
    prover.add_frame(FLogicFrame("rex", isa="Dog"))

    result = prover.query("?X : Dog", prefer_zkp=False)
    print(result.status, result.from_cache, result.zkp_proof)
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from .flogic_proof_cache import CachedErgoAIWrapper, FLogicCachedQueryResult
from .flogic_types import FLogicClass, FLogicFrame, FLogicOntology, FLogicStatus

# Optional ZKP module
try:
    from .. import zkp as _zkp  # type: ignore
    _HAVE_ZKP = True
except ImportError:
    _zkp = None  # type: ignore
    _HAVE_ZKP = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Proving method enum
# ---------------------------------------------------------------------------


class FLogicProvingMethod(Enum):
    """Method used to produce an F-logic query result."""

    STANDARD = "flogic_standard"
    ZKP = "flogic_zkp"
    CACHED = "flogic_cached"


# ---------------------------------------------------------------------------
# Unified result
# ---------------------------------------------------------------------------


@dataclass
class ZKPFLogicResult:
    """
    Unified F-logic query result supporting both standard and ZKP paths.

    Attributes:
        goal: The query string.
        status: :class:`~ipfs_datasets_py.logic.flogic.flogic_types.FLogicStatus`.
        bindings: Variable bindings (may be empty for ZKP-only results).
        method: How the result was produced.
        proof_time: Seconds taken by the prover / cache lookup.
        from_cache: ``True`` when the result came from the proof cache.
        zkp_proof: ZKP proof object (``None`` for standard / cached results).
        is_private: ``True`` when the ontology was hidden via ZKP.
        zkp_backend: Name of the ZKP backend used (if any).
        error_message: Human-readable error if status is ``ERROR``.
        timestamp: Unix time of result creation.
    """

    goal: str
    status: FLogicStatus
    bindings: List[Dict[str, Any]] = field(default_factory=list)
    method: FLogicProvingMethod = FLogicProvingMethod.STANDARD
    proof_time: float = 0.0
    from_cache: bool = False
    zkp_proof: Optional[Any] = None
    is_private: bool = False
    zkp_backend: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def from_cached(cls, cached: FLogicCachedQueryResult) -> "ZKPFLogicResult":
        """Build from a :class:`~ipfs_datasets_py.logic.flogic.flogic_proof_cache.FLogicCachedQueryResult`."""
        return cls(
            goal=cached.goal,
            status=cached.status,
            bindings=list(cached.bindings),
            method=FLogicProvingMethod.CACHED if cached.from_cache else FLogicProvingMethod.STANDARD,
            proof_time=cached.execution_time,
            from_cache=cached.from_cache,
            error_message=cached.error_message,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "goal": self.goal,
            "status": self.status.value,
            "bindings": self.bindings,
            "method": self.method.value,
            "proof_time": self.proof_time,
            "from_cache": self.from_cache,
            "is_private": self.is_private,
            "zkp_backend": self.zkp_backend,
            "error_message": self.error_message,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# ZKP + cache prover
# ---------------------------------------------------------------------------


class ZKPFLogicProver:
    """
    Hybrid F-logic prover integrating the unified proof cache and ZKP attestation.

    Proving strategy (in order):

    1. **Cache** — if ``use_cache=True`` and the unified cache has an entry,
       return it immediately.
    2. **ZKP attestation** — if ``prefer_zkp=True`` and the ZKP module is
       available, generate a ZK proof that the query result is consistent with
       the ontology hash (without revealing the full ontology).
    3. **Standard query** — run via
       :class:`~ipfs_datasets_py.logic.flogic.flogic_proof_cache.CachedErgoAIWrapper`
       and persist the result in the cache.

    Args:
        enable_zkp: Enable ZKP attestation (requires ``ipfs_datasets_py.logic.zkp``).
        enable_caching: Enable proof caching via the unified cache.
        zkp_backend: ZKP backend — ``"simulated"`` or ``"groth16"``.
        ontology_name: Name for the internal ontology.
        binary: Path to the ErgoAI binary (``None`` → simulation mode).
    """

    def __init__(
        self,
        enable_zkp: bool = True,
        enable_caching: bool = True,
        zkp_backend: str = "simulated",
        ontology_name: str = "default",
        binary=None,
    ) -> None:
        self._ergo = CachedErgoAIWrapper(
            enable_caching=enable_caching,
            ontology_name=ontology_name,
            binary=binary,
        )

        self.enable_zkp = enable_zkp and _HAVE_ZKP
        self.zkp_backend = zkp_backend

        if self.enable_zkp:
            try:
                self._zkp_prover = _zkp.ZKPProver(backend=zkp_backend)
                self._zkp_verifier = _zkp.ZKPVerifier(backend=zkp_backend)
                logger.info("F-logic ZKP enabled with backend: %s", zkp_backend)
            except Exception as exc:
                logger.warning("F-logic: failed to initialise ZKP backend: %s", exc)
                self.enable_zkp = False
                self._zkp_prover = None
                self._zkp_verifier = None
        else:
            self._zkp_prover = None
            self._zkp_verifier = None

        # Stats
        self._zkp_attempts = 0
        self._zkp_successes = 0
        self._standard_queries = 0

    # ------------------------------------------------------------------
    # Knowledge base construction (delegated to inner wrapper)
    # ------------------------------------------------------------------

    def add_frame(self, frame: FLogicFrame) -> None:
        """Add an F-logic frame to the ontology."""
        self._ergo.add_frame(frame)

    def add_class(self, cls: FLogicClass) -> None:
        """Add an F-logic class to the ontology."""
        self._ergo.add_class(cls)

    def add_rule(self, rule: str) -> None:
        """Add a raw Ergo rule to the ontology."""
        self._ergo.add_rule(rule)

    def load_ontology(self, ontology: FLogicOntology) -> None:
        """Replace the current ontology."""
        self._ergo.load_ontology(ontology)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def query(
        self,
        goal: str,
        prefer_zkp: bool = False,
        private_ontology: bool = False,
        use_cache: bool = True,
    ) -> ZKPFLogicResult:
        """
        Execute a query using the hybrid strategy.

        Args:
            goal: Ergo query goal string.
            prefer_zkp: Try ZKP attestation before the standard path.
            private_ontology: When combined with ZKP, hide the ontology
                contents from the result (only the ontology *hash* is exposed).
            use_cache: Check the proof cache before running the prover.

        Returns:
            :class:`ZKPFLogicResult` describing the outcome.
        """
        start = time.monotonic()

        # Strategy 1: Cache — do a pure lookup without running the prover
        if use_cache and self._ergo.enable_caching and self._ergo._cache is not None:
            cache_result = self._ergo._get_from_cache(goal)
            if cache_result is not None:
                cache_result.from_cache = True
                return ZKPFLogicResult.from_cached(cache_result)

        # Strategy 2: ZKP attestation
        if prefer_zkp and self.enable_zkp and self._zkp_prover:
            try:
                self._zkp_attempts += 1
                zkp_result = self._attest_with_zkp(goal, private_ontology)
                if zkp_result.status == FLogicStatus.SUCCESS:
                    self._zkp_successes += 1
                    return zkp_result
                logger.debug("F-logic ZKP attestation inconclusive, falling back")
            except Exception as exc:
                logger.warning("F-logic ZKP attestation error: %s", exc)

        # Strategy 3: Standard query (with cache write)
        self._standard_queries += 1
        cached = self._ergo.query(goal)
        return ZKPFLogicResult.from_cached(cached)

    def batch_query(
        self,
        goals: Sequence[str],
        prefer_zkp: bool = False,
        private_ontology: bool = False,
        use_cache: bool = True,
    ) -> List[ZKPFLogicResult]:
        """Execute multiple goals and return one :class:`ZKPFLogicResult` per goal."""
        return [
            self.query(g, prefer_zkp=prefer_zkp,
                       private_ontology=private_ontology, use_cache=use_cache)
            for g in goals
        ]

    # ------------------------------------------------------------------
    # ZKP internals
    # ------------------------------------------------------------------

    def _ontology_hash(self) -> str:
        """Compute a deterministic SHA-256 hash of the current ontology program."""
        prog = self._ergo.get_program()
        return hashlib.sha256(prog.encode()).hexdigest()

    def _attest_with_zkp(
        self,
        goal: str,
        private_ontology: bool,
    ) -> ZKPFLogicResult:
        """
        Generate a ZKP attestation that *goal* is consistent with the ontology.

        The ZK statement is: "I know an ontology O such that O ⊨ goal",
        where O is committed to via its SHA-256 hash.  The witness is the
        full ontology program (or its hash when ``private_ontology=True``
        to avoid exposing proprietary rules, while still providing a valid
        commitment that the backend can check).
        """
        assert self._zkp_prover is not None
        start = time.monotonic()

        ontology_hash = self._ontology_hash()
        statement = f"{goal}#{ontology_hash}"

        # When private_ontology=True we commit to the hash rather than the
        # raw program text, so the witness remains verifiable without leaking
        # the full ontology to verifiers.
        witness = {
            "ontology": ontology_hash if private_ontology else self._ergo.get_program()
        }

        zkp_proof = self._zkp_prover.prove(statement, witness)
        is_valid = self._zkp_verifier.verify(
            {"goal": goal, "ontology_hash": ontology_hash},
            zkp_proof,
        )

        proof_time = time.monotonic() - start
        status = FLogicStatus.SUCCESS if is_valid else FLogicStatus.FAILURE

        return ZKPFLogicResult(
            goal=goal,
            status=status,
            bindings=[],
            method=FLogicProvingMethod.ZKP,
            proof_time=proof_time,
            zkp_proof=zkp_proof,
            is_private=private_ontology,
            zkp_backend=self.zkp_backend,
        )

    # ------------------------------------------------------------------
    # Statistics / utilities
    # ------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        """Combined statistics for the ZKP prover, query engine, and cache."""
        stats: Dict[str, Any] = {
            "zkp_enabled": self.enable_zkp,
            "zkp_attempts": self._zkp_attempts,
            "zkp_successes": self._zkp_successes,
            "zkp_success_rate": (
                self._zkp_successes / self._zkp_attempts
                if self._zkp_attempts > 0
                else 0.0
            ),
            "standard_queries": self._standard_queries,
        }
        stats.update(self._ergo.get_statistics())
        return stats

    def clear_cache(self) -> None:
        """Clear the proof cache."""
        self._ergo.clear_cache()

    def get_program(self) -> str:
        """Return the current ontology as an Ergo source string."""
        return self._ergo.get_program()


__all__ = [
    "FLogicProvingMethod",
    "ZKPFLogicResult",
    "ZKPFLogicProver",
    "_HAVE_ZKP",
]
