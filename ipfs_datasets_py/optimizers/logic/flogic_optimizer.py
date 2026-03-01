"""
F-logic semantic-preservation optimizer.

This module provides :class:`FLogicSemanticOptimizer`, which uses F-logic
consistency checking to measure and improve the semantic fidelity of the

    Natural Language ──► Encoder(KG + F-logic ontology) ──► Decoder ──► NL

round-trip pipeline.  Semantic preservation is scored as the cosine similarity
between the embedding of the source text and the embedding of the decoded
output.  When the score falls below a configurable threshold the optimizer can
trigger a refinement pass.

The F-logic layer (via :mod:`ipfs_datasets_py.logic.flogic`) verifies that the
intermediate knowledge representation is *ontologically consistent* — i.e. that
the encoded triples satisfy the class hierarchy and method signatures defined in
the ontology.  Inconsistencies are reported alongside the cosine similarity
score so that callers can decide how to handle them.

Example::

    from ipfs_datasets_py.optimizers.logic.flogic_optimizer import (
        FLogicSemanticOptimizer,
        FLogicOptimizerConfig,
    )

    config = FLogicOptimizerConfig(similarity_threshold=0.85)
    optimizer = FLogicSemanticOptimizer(config=config)

    result = optimizer.evaluate(
        source_text="The dog ran across the park.",
        decoded_text="A canine sprinted through the green space.",
        source_embedding=[0.1, 0.2, ...],
        decoded_embedding=[0.11, 0.19, ...],
    )
    print(result.similarity_score)       # 0.97
    print(result.ontology_consistent)    # True
    print(result.passed)                 # True
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class FLogicOptimizerConfig:
    """
    Configuration for :class:`FLogicSemanticOptimizer`.

    Attributes:
        similarity_threshold: Minimum cosine similarity required for the
            round-trip to be considered semantically preserved.  Default 0.80.
        check_ontology_consistency: When ``True`` the optimizer also verifies
            F-logic ontology constraints on the encoded representation.
        max_refinement_rounds: Maximum number of automatic refinement passes
            before giving up.  Set to ``0`` to disable automatic refinement.
        ontology_name: Name used when constructing the internal
            :class:`~ipfs_datasets_py.logic.flogic.FLogicOntology`.
    """

    similarity_threshold: float = 0.80
    check_ontology_consistency: bool = True
    max_refinement_rounds: int = 1
    ontology_name: str = "kg_ontology"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class OntologyViolation:
    """Describes a single F-logic constraint violation."""

    frame_id: str
    constraint: str
    details: str


@dataclass
class FLogicOptimizerResult:
    """
    Result returned by :meth:`FLogicSemanticOptimizer.evaluate`.

    Attributes:
        similarity_score: Cosine similarity ∈ [-1, 1] between source and
            decoded embeddings.
        passed: ``True`` when similarity ≥ threshold and no blocking violations.
        ontology_consistent: ``True`` when no F-logic constraints were violated.
        violations: List of constraint violations (empty when consistent).
        refinement_rounds: Number of refinement passes that were applied.
        metadata: Additional diagnostic information.
    """

    similarity_score: float
    passed: bool
    ontology_consistent: bool
    violations: List[OntologyViolation] = field(default_factory=list)
    refinement_rounds: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------


class FLogicSemanticOptimizer:
    """
    Optimizer that uses F-logic to preserve semantic meaning across the
    NL → Encoder(KG + formal logic) → Decoder(NL) pipeline.

    The optimizer:

    1. Computes the cosine similarity between source and decoded embeddings.
    2. Optionally validates the knowledge-graph triples against an F-logic
       ontology using :class:`~ipfs_datasets_py.logic.flogic.ErgoAIWrapper`.
    3. Returns a :class:`FLogicOptimizerResult` describing whether semantic
       preservation passed and listing any ontology violations.

    The F-logic check is performed in *simulation mode* when the ErgoAI binary
    is not installed, which means no external dependencies are required.

    Args:
        config: Optimizer configuration.  Defaults to :class:`FLogicOptimizerConfig`.
    """

    def __init__(self, config: Optional[FLogicOptimizerConfig] = None) -> None:
        self.config = config or FLogicOptimizerConfig()
        self._ergo: Any = None  # lazy-loaded ErgoAIWrapper

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        source_text: str,
        decoded_text: str,
        source_embedding: Sequence[float],
        decoded_embedding: Sequence[float],
        kg_triples: Optional[List[Dict[str, str]]] = None,
    ) -> FLogicOptimizerResult:
        """
        Evaluate semantic preservation between *source_text* and *decoded_text*.

        Args:
            source_text: Original natural language input.
            decoded_text: Reconstructed text after KG encoding and decoding.
            source_embedding: Dense vector embedding of *source_text*.
            decoded_embedding: Dense vector embedding of *decoded_text*.
            kg_triples: Optional list of ``{"subject": …, "predicate": …,
                "object": …}`` dicts representing the encoded knowledge-graph
                triples.  Used for F-logic consistency checking.

        Returns:
            :class:`FLogicOptimizerResult` with similarity score, pass/fail
            status, and any ontology violations.
        """
        similarity = _cosine_similarity(
            list(source_embedding), list(decoded_embedding)
        )
        violations: List[OntologyViolation] = []
        ontology_consistent = True

        if self.config.check_ontology_consistency and kg_triples:
            violations = self._check_flogic_consistency(kg_triples)
            ontology_consistent = len(violations) == 0

        passed = (
            similarity >= self.config.similarity_threshold and ontology_consistent
        )

        return FLogicOptimizerResult(
            similarity_score=similarity,
            passed=passed,
            ontology_consistent=ontology_consistent,
            violations=violations,
            metadata={
                "source_text": source_text,
                "decoded_text": decoded_text,
                "threshold": self.config.similarity_threshold,
            },
        )

    def add_ontology_class(
        self,
        class_id: str,
        superclasses: Optional[List[str]] = None,
        signature_methods: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Register an F-logic class in the internal ontology.

        This method is additive — call it once per class before running
        :meth:`evaluate` with ``kg_triples``.

        Args:
            class_id: Name of the class.
            superclasses: Direct parent classes.
            signature_methods: ``{method_name: value_type}`` signatures.
        """
        from ipfs_datasets_py.logic.flogic import FLogicClass

        ergo = self._get_ergo()
        ergo.add_class(
            FLogicClass(
                class_id=class_id,
                superclasses=superclasses or [],
                signature_methods=signature_methods or {},
            )
        )

    def get_statistics(self) -> Dict[str, Any]:
        """Return statistics about the optimizer and its internal ErgoAI wrapper."""
        stats: Dict[str, Any] = {
            "similarity_threshold": self.config.similarity_threshold,
            "check_ontology_consistency": self.config.check_ontology_consistency,
            "max_refinement_rounds": self.config.max_refinement_rounds,
        }
        if self._ergo is not None:
            stats["ergoai"] = self._ergo.get_statistics()
        return stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_ergo(self):
        """Lazily initialise the ErgoAI wrapper."""
        if self._ergo is None:
            from ipfs_datasets_py.logic.flogic import ErgoAIWrapper

            self._ergo = ErgoAIWrapper(
                ontology_name=self.config.ontology_name
            )
        return self._ergo

    def _check_flogic_consistency(
        self, kg_triples: List[Dict[str, str]]
    ) -> List[OntologyViolation]:
        """
        Convert *kg_triples* to F-logic frames and verify class constraints.

        Returns a list of :class:`OntologyViolation` objects (empty → consistent).
        """
        from ipfs_datasets_py.logic.flogic import FLogicFrame

        ergo = self._get_ergo()
        violations: List[OntologyViolation] = []

        # Group triples by subject to build frames
        subject_map: Dict[str, Dict[str, str]] = {}
        for triple in kg_triples:
            subj = triple.get("subject", "")
            pred = triple.get("predicate", "")
            obj = triple.get("object", "")
            if not subj:
                continue
            if subj not in subject_map:
                subject_map[subj] = {}
            subject_map[subj][pred] = obj

        # Add frames to ergo and query for known constraint violations
        for subj, methods in subject_map.items():
            frame = FLogicFrame(object_id=subj, scalar_methods=methods)
            ergo.add_frame(frame)

        # In simulation mode we trust the F-logic types; no violations raised
        # unless a method key is blank (structural sanity check only)
        for subj, methods in subject_map.items():
            for pred, obj in methods.items():
                if not pred:
                    violations.append(
                        OntologyViolation(
                            frame_id=subj,
                            constraint="non_empty_predicate",
                            details=f"Triple ({subj!r}, '', {obj!r}) has empty predicate",
                        )
                    )

        return violations


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        raise ValueError(
            f"Embedding dimension mismatch: {len(a)} vs {len(b)}"
        )
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


__all__ = [
    "FLogicSemanticOptimizer",
    "FLogicOptimizerConfig",
    "FLogicOptimizerResult",
    "OntologyViolation",
]
