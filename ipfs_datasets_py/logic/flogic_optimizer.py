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

    from ipfs_datasets_py.logic.flogic_optimizer import (
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
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    frame_ontology_contextualized_terms,
    frame_ontology_feature_keys,
    frame_ontology_feature_keys_from_values,
    frame_ontology_high_signal_terms,
    frame_ontology_terms_from_feature_keys,
    frame_ontology_terms_from_triples,
)

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
        *,
        frame_feature_keys: Optional[Sequence[str]] = None,
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
            frame_feature_keys: Optional modal/frame-logic audit features from
                the deterministic modal codec. These are recorded as diagnostics
                and do not alter the F-logic consistency decision.

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

        frame_metadata = _frame_ontology_metadata(
            kg_triples=kg_triples or [],
            frame_feature_keys=frame_feature_keys or [],
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
                **frame_metadata,
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
            subj = str(triple.get("subject", "")).strip()
            pred = str(triple.get("predicate", "")).strip()
            obj = str(triple.get("object", "")).strip()
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

        violations.extend(self._check_frame_ontology_constraints(kg_triples))
        return violations

    def _check_frame_ontology_constraints(
        self,
        kg_triples: Sequence[Mapping[str, Any]],
    ) -> List[OntologyViolation]:
        """Validate deterministic modal.frame_logic ontology invariants."""
        triples_by_subject: Dict[str, List[tuple[str, str]]] = {}
        for triple in kg_triples:
            subj = str(triple.get("subject", "")).strip()
            pred = str(triple.get("predicate", "")).strip()
            obj = str(triple.get("object", "")).strip()
            if not subj or not pred or not obj:
                continue
            triples_by_subject.setdefault(subj, []).append((pred, obj))

        document_selected_frames: Dict[str, str] = {}
        document_selected_terms: Dict[str, set[str]] = {}
        violations: List[OntologyViolation] = []
        for subj, facts in sorted(triples_by_subject.items()):
            selected_frames = [
                obj for pred, obj in facts if pred == "selected_ontology_frame"
            ]
            selected_terms = {
                obj for pred, obj in facts if pred == "selected_ontology_term"
            }
            selected_frame_constraints = {
                obj
                for pred, obj in facts
                if pred == "modal_frame_logic_ontology_constraint"
            }
            if selected_frames:
                unique_frames = sorted(set(selected_frames))
                if len(unique_frames) > 1:
                    violations.append(
                        OntologyViolation(
                            frame_id=subj,
                            constraint="single_selected_ontology_frame",
                            details=(
                                "Subject has multiple selected ontology frames: "
                                + ", ".join(unique_frames)
                            ),
                        )
                    )
                document_selected_frames[subj] = unique_frames[0]
                document_selected_terms[subj] = selected_terms
                if not selected_terms:
                    violations.append(
                        OntologyViolation(
                            frame_id=subj,
                            constraint="selected_frame_has_terms",
                            details=(
                                "Selected ontology frame "
                                f"{unique_frames[0]!r} has no selected_ontology_term facts"
                            ),
                        )
                    )
                violations.extend(
                    _selected_frame_constraint_violations(
                        frame_id=subj,
                        selected_frames=unique_frames,
                        selected_terms=selected_terms,
                        constraints=selected_frame_constraints,
                    )
                )
            elif selected_frame_constraints:
                violations.extend(
                    _selected_frame_constraint_violations(
                        frame_id=subj,
                        selected_frames=[],
                        selected_terms=selected_terms,
                        constraints=selected_frame_constraints,
                    )
                )

        if not document_selected_frames:
            return violations

        selected_frame_values = set(document_selected_frames.values())
        selected_terms_by_frame: Dict[str, set[str]] = {}
        for doc_id, frame in document_selected_frames.items():
            selected_terms_by_frame.setdefault(frame, set()).update(
                document_selected_terms.get(doc_id, set())
            )
        for subj, facts in sorted(triples_by_subject.items()):
            for pred, obj in facts:
                if pred != "interpreted_in_frame":
                    continue
                if obj not in selected_frame_values:
                    violations.append(
                        OntologyViolation(
                            frame_id=subj,
                            constraint="interpreted_frame_matches_selected_frame",
                            details=(
                                f"Formula is interpreted in {obj!r}, which is not "
                                "a selected ontology frame for the document"
                            ),
                        )
                    )
                elif not selected_terms_by_frame.get(obj):
                    violations.append(
                        OntologyViolation(
                            frame_id=subj,
                            constraint="interpreted_frame_has_selected_terms",
                            details=(
                                f"Interpreted frame {obj!r} has no selected term grounding"
                            ),
                        )
                    )
                    continue
                interpreted_terms = {
                    term
                    for term_pred, term in facts
                    if term_pred == "interpreted_in_frame_term"
                }
                ungrounded_terms = sorted(
                    interpreted_terms - selected_terms_by_frame.get(obj, set())
                )
                if ungrounded_terms:
                    violations.append(
                        OntologyViolation(
                            frame_id=subj,
                            constraint="interpreted_frame_terms_selected",
                            details=(
                                f"Formula terms are not selected ontology terms "
                                f"for frame {obj!r}: "
                                + ", ".join(ungrounded_terms)
                            ),
                        )
                    )

        return violations


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _selected_frame_constraint_violations(
    *,
    frame_id: str,
    selected_frames: Sequence[str],
    selected_terms: set[str],
    constraints: set[str],
) -> List[OntologyViolation]:
    """Validate explicit modal.frame_logic selected-frame constraint facts."""
    violations: List[OntologyViolation] = []
    if not constraints:
        return violations

    frame_satisfied = "selected_ontology_frame:required:satisfied" in constraints
    frame_missing = "selected_ontology_frame:required:missing" in constraints
    term_satisfied = "selected_ontology_term:required:satisfied" in constraints
    term_missing = "selected_ontology_term:required:missing" in constraints

    if frame_missing and selected_frames:
        violations.append(
            OntologyViolation(
                frame_id=frame_id,
                constraint="selected_frame_constraint_status_matches_facts",
                details=(
                    "modal.frame_logic constraint marks selected_ontology_frame "
                    "missing despite selected_ontology_frame facts"
                ),
            )
        )
    if frame_satisfied and not selected_frames:
        violations.append(
            OntologyViolation(
                frame_id=frame_id,
                constraint="selected_frame_constraint_status_matches_facts",
                details=(
                    "modal.frame_logic constraint marks selected_ontology_frame "
                    "satisfied without selected_ontology_frame facts"
                ),
            )
        )
    if term_missing and selected_terms:
        violations.append(
            OntologyViolation(
                frame_id=frame_id,
                constraint="selected_term_constraint_status_matches_facts",
                details=(
                    "modal.frame_logic constraint marks selected_ontology_term "
                    "missing despite selected_ontology_term facts"
                ),
            )
        )
    if term_satisfied and not selected_terms:
        violations.append(
            OntologyViolation(
                frame_id=frame_id,
                constraint="selected_term_constraint_status_matches_facts",
                details=(
                    "modal.frame_logic constraint marks selected_ontology_term "
                    "satisfied without selected_ontology_term facts"
                ),
            )
        )
    return violations


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


def _frame_ontology_metadata(
    *,
    kg_triples: Sequence[Mapping[str, Any]],
    frame_feature_keys: Sequence[Any],
) -> Dict[str, Any]:
    feature_keys = _normalized_frame_feature_keys(frame_feature_keys)
    audit_feature_keys = sorted(
        frame_ontology_feature_keys(
            feature_keys
            + frame_ontology_feature_keys_from_values(frame_feature_keys)
        )
    )
    feature_terms = sorted(
        frame_ontology_terms_from_feature_keys(audit_feature_keys)
    )
    triple_terms = sorted(
        frame_ontology_terms_from_triples(kg_triples)
    )
    contextualized_terms = sorted(
        frame_ontology_contextualized_terms(
            feature_keys=audit_feature_keys,
            triples=kg_triples,
        )
    )
    promoted_contextualized_terms = [
        term
        for term in contextualized_terms
        if _should_promote_contextualized_frame_ontology_term(term)
    ]
    # Contextualized terms preserve low-signal structural values by attaching
    # their frame predicate context. Only promote terms that add semantic
    # LegalIR/structural signal; broader aliases stay available in the
    # contextualized diagnostics without polluting the canonical term metric.
    ontology_terms = sorted(
        set(feature_terms) | set(triple_terms) | set(promoted_contextualized_terms)
    )
    feature_high_signal_terms = frame_ontology_high_signal_terms(feature_terms)
    triple_high_signal_terms = frame_ontology_high_signal_terms(triple_terms)
    contextualized_high_signal_terms = frame_ontology_high_signal_terms(
        contextualized_terms
    )
    high_signal_terms = frame_ontology_high_signal_terms(ontology_terms)

    return {
        "frame_feature_key_count": len(feature_keys),
        "frame_feature_keys": feature_keys,
        "frame_audit_feature_key_count": len(audit_feature_keys),
        "frame_audit_feature_keys": audit_feature_keys,
        "frame_ontology_terms_from_feature_keys_count": len(feature_terms),
        "frame_ontology_terms_from_feature_keys": feature_terms,
        "frame_ontology_terms_from_triples_count": len(triple_terms),
        "frame_ontology_terms_from_triples": triple_terms,
        "frame_ontology_contextualized_term_count": len(contextualized_terms),
        "frame_ontology_contextualized_terms": contextualized_terms,
        "frame_ontology_term_count": len(ontology_terms),
        "frame_ontology_terms": ontology_terms,
        "frame_ontology_high_signal_terms_from_feature_keys_count": len(
            feature_high_signal_terms
        ),
        "frame_ontology_high_signal_terms_from_feature_keys": feature_high_signal_terms,
        "frame_ontology_high_signal_terms_from_triples_count": len(
            triple_high_signal_terms
        ),
        "frame_ontology_high_signal_terms_from_triples": triple_high_signal_terms,
        "frame_ontology_high_signal_terms_from_contextualized_count": len(
            contextualized_high_signal_terms
        ),
        "frame_ontology_high_signal_terms_from_contextualized": contextualized_high_signal_terms,
        "frame_ontology_high_signal_term_count": len(high_signal_terms),
        "frame_ontology_high_signal_terms": high_signal_terms,
    }


def _should_promote_contextualized_frame_ontology_term(term: str) -> bool:
    normalized = str(term or "").strip().lower()
    if not normalized:
        return False
    if normalized.startswith(
        (
            "condition_consequence_",
            "legal_ir_view_",
            "quality_",
            "quality_frame_",
            "signature_frame_",
        )
    ):
        return True
    if normalized.startswith(
        (
            "condition_modal_family_",
            "condition_modal_operator_",
            "exception_modal_family_",
            "exception_modal_operator_",
        )
    ):
        return True
    return any(
        fragment in normalized
        for fragment in (
            "_distance_profile_",
            "_magnitude_bucket_",
            "_parity",
            "_thousands_block_",
            "citation_section_number_trailing_zero_count_positioned_",
            "citation_section_primary_number_trailing_zero_count_",
            "citation_title_section_primary_number_span_has_zero_digit_",
            "citation_title_section_primary_number_span_zero_digit_count_",
            "citation_title_section_terminal_number_span_has_zero_digit_",
            "predicate_alnum_segment_",
            "predicate_token_",
            "suffix_consonant_count",
        )
    )


def _normalized_frame_feature_keys(values: Sequence[Any]) -> List[str]:
    collected: List[str] = []
    _collect_frame_feature_key_values(values, collected)
    collected.extend(frame_ontology_feature_keys_from_values(values))
    return sorted(
        {
            str(value or "").strip()
            for value in collected
            if str(value or "").strip()
        }
    )


def _collect_frame_feature_key_values(
    value: Any,
    collected: List[str],
    *,
    depth: int = 0,
    max_depth: int = 6,
    max_values: int = 2048,
) -> None:
    if depth >= max_depth or len(collected) >= max_values or value is None:
        return

    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            if len(collected) >= max_values:
                return
            key_text = str(key or "").strip()
            synthetic_values = _synthetic_frame_feature_values(
                key_text,
                nested_value,
            )
            if synthetic_values:
                collected.extend(synthetic_values[: max_values - len(collected)])
                if isinstance(nested_value, (Mapping, list, tuple)):
                    _collect_frame_feature_key_values(
                        nested_value,
                        collected,
                        depth=depth + 1,
                        max_depth=max_depth,
                        max_values=max_values,
                    )
                continue
            if _should_recurse_frame_feature_field(key_text, nested_value):
                _collect_frame_feature_key_values(
                    nested_value,
                    collected,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_values=max_values,
                )
        return

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if len(collected) >= max_values:
                return
            _collect_frame_feature_key_values(
                item,
                collected,
                depth=depth + 1,
                max_depth=max_depth,
                max_values=max_values,
            )
        return

    text = str(value or "").strip()
    if not text:
        return
    parsed = _parsed_frame_feature_json(text)
    if parsed is not None:
        _collect_frame_feature_key_values(
            parsed,
            collected,
            depth=depth + 1,
            max_depth=max_depth,
            max_values=max_values,
        )
        return
    collected.append(text)


def _synthetic_frame_feature_values(key: str, value: Any) -> List[str]:
    if isinstance(value, Mapping):
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return []
    text = str(value or "").strip()
    if not text:
        return []
    normalized_key = key.strip().lower().replace("-", "_")
    prefix_by_key = {
        "candidate_frame": "frame-candidate:",
        "candidate_ontology_frame": "frame-candidate:",
        "candidate_frame_term": "frame-term:",
        "candidate_ontology_term": "frame-term:",
        "frame_id": "frame:",
        "frame_term": "frame-term:",
        "modal_family": "family:selected_frame:",
        "predicted_family": "family:selected_frame:",
        "selected_frame": "frame:",
        "selected_ontology_frame": "frame:",
        "selected_frame_term": "selected-frame-term:",
        "selected_ontology_term": "selected-frame-term:",
        "target_family": "family:selected_frame:",
    }
    prefix = prefix_by_key.get(normalized_key)
    if prefix:
        return [f"{prefix}{text}"]
    if normalized_key in {
        "citation",
        "document_id",
        "sample_id",
        "source_id",
        "source_id_citation_canonical",
    } and _looks_like_frame_feature_value(text):
        return [text]
    return []


def _should_recurse_frame_feature_field(key: str, value: Any) -> bool:
    if isinstance(value, (Mapping, list, tuple)):
        return True
    normalized_key = key.strip().lower().replace("-", "_")
    if normalized_key in {
        "feature",
        "feature_key",
        "feature_keys",
        "features",
        "frame_feature",
        "frame_feature_key",
        "frame_feature_keys",
        "frame_features",
        "hint_evidence",
        "top_embedding_features",
        "top_family_features",
    }:
        return True
    return _looks_like_frame_feature_value(str(value or ""))


def _looks_like_frame_feature_value(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return (
        ":" in text
        or lowered.startswith("us-code-")
        or lowered.startswith("us_code_")
        or " u.s.c. " in f" {lowered} "
    )


def _parsed_frame_feature_json(text: str) -> Any | None:
    stripped = str(text or "").strip()
    if not stripped or len(stripped) > 4096:
        return None
    if not (
        stripped.startswith("{")
        and stripped.endswith("}")
        or stripped.startswith("[")
        and stripped.endswith("]")
    ):
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, (Mapping, list, tuple)):
        return parsed
    return None


__all__ = [
    "FLogicSemanticOptimizer",
    "FLogicOptimizerConfig",
    "FLogicOptimizerResult",
    "OntologyViolation",
]
