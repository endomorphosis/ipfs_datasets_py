"""Verified hard-negative curricula for LegalIR training.

Hard negatives are only useful when they are trusted labels.  This module
therefore accepts verified fuzzing counterexamples and deterministic mutation
oracles over trusted positive LegalIR records, rejects unverified model guesses,
schedules negatives by difficulty, and emits an explicit before/after effect
report for semantic-equivalence false positives and trusted positive
obligations.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Optional

from ipfs_datasets_py.logic.formalization.training_contracts import (
    EvidenceStatus,
    ExampleDisposition,
    IRHardNegative,
    IRTrainingExample,
    LabelAuthority,
    LabelEvidence,
    LineageBinding,
    MutationClass,
    NegativeDisposition,
    RepresentationKind,
    SemanticRelationship,
    StatementAuthority,
    StatementBinding,
    TrainingContractValidationError,
)
from ipfs_datasets_py.logic.formalization.training_shared import (
    IR_HARD_NEGATIVE_INTERFACE,
    IR_HARD_NEGATIVE_SCHEMA_VERSION,
    _RELATION_AUTHORITIES,
)
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind
from ipfs_datasets_py.logic.ir_core.source_lineage import RightsDisposition

from .legal_ir_family_evaluator import (
    LEGAL_IR_EVALUATION_FAMILIES,
    canonical_legal_ir_evaluation_family,
)
from .legal_ir_fuzzing import (
    EVIDENCE_COUNTEREXAMPLE,
    EVIDENCE_ENTAILMENT,
    EVIDENCE_NON_EQUIVALENCE,
    EVIDENCE_SATISFIABILITY,
    MINIMAL_MUTATION_CLASSES,
    MutationValidationRecord,
    SOLVER_TIMED_OUT,
    SOLVER_UNAVAILABLE,
    SOLVER_UNKNOWN,
    collect_mutation_evidence,
    generate_minimal_semantic_mutations,
    seeded_unavailable_solver_mutation,
    seeded_unknown_solver_mutation,
    validate_all_minimal_mutation_classes,
)
from .legal_ir_positive_pairs import (
    INDEPENDENT_AUTHORITIES,
    MODEL_ONLY_AUTHORITIES,
    PositiveEquivalenceIndex,
    SEALED_CORPUS_MANIFEST_CID,
    SEALED_CORPUS_MANIFEST_ID,
    SEALED_CORPUS_ROOT_SHA256,
    SEALED_LINEAGE_GRAPH_CID,
    SEALED_LINEAGE_GRAPH_ID,
    SEALED_SPLIT_MANIFEST_DIGEST,
    SEALED_SPLIT_MANIFEST_ID,
    SEALED_SPLIT_ROOT_SHA256,
    TRAIN_SPLIT_NAME,
    cas_write_json,
    content_cid,
    content_digest,
    load_positive_pair_shards,
    make_relationship_evidence,
    make_statement,
    mine_canonical_positive_pairs,
    resolve_positive_pair_data_dir,
    sealed_campaign_lineage,
)
from .legal_ir_semantic_metrics import (
    OBLIGATION_EQUIVALENCE,
    SEMANTIC_EQUIVALENCE_METRICS,
    STRUCTURAL_EQUIVALENCE,
    evaluate_legal_ir_semantic_equivalence,
)


LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION: Final = "legal-ir-hard-negative-curriculum-v1"
LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION: Final = "legal-ir-hard-negative-effect-v1"

VERIFIED_COUNTEREXAMPLE: Final = "verified_counterexample"
NEAR_MISS_CLAUSE: Final = "near_miss_clause"
SWAPPED_ACTOR: Final = "swapped_actor"
INVERTED_MODALITY: Final = "inverted_modality"
STALE_AMENDMENT: Final = "stale_amendment"
WRONG_CITATION: Final = "wrong_citation"
SOURCE_COPY_SPAN: Final = "source_copy_span"
DECOMPILER_HALLUCINATION: Final = "decompiler_hallucination"

HARD_NEGATIVE_FAMILIES: Final[tuple[str, ...]] = (
    SOURCE_COPY_SPAN,
    WRONG_CITATION,
    SWAPPED_ACTOR,
    INVERTED_MODALITY,
    NEAR_MISS_CLAUSE,
    STALE_AMENDMENT,
    VERIFIED_COUNTEREXAMPLE,
    DECOMPILER_HALLUCINATION,
)

DEFAULT_NEGATIVE_FAMILY_DIFFICULTY: Final[Mapping[str, float]] = {
    SOURCE_COPY_SPAN: 0.20,
    WRONG_CITATION: 0.30,
    SWAPPED_ACTOR: 0.45,
    INVERTED_MODALITY: 0.55,
    NEAR_MISS_CLAUSE: 0.65,
    STALE_AMENDMENT: 0.72,
    VERIFIED_COUNTEREXAMPLE: 0.82,
    DECOMPILER_HALLUCINATION: 0.92,
}

DEFAULT_LEGAL_IR_FAMILY_DIFFICULTY: Final[Mapping[str, float]] = {
    "deontic": 0.00,
    "frame_logic": 0.04,
    "tdfol": 0.10,
    "knowledge_graphs": 0.12,
    "cec": 0.14,
    "external_provers": 0.18,
    "decompiler": 0.20,
    "temporal": 0.16,
    "provenance": 0.15,
}

_TRUE: Final = frozenset(
    {"1", "accepted", "passed", "proved", "true", "trusted", "verified", "yes"}
)
_VERIFIER_KEYS: Final = (
    "verified",
    "proof_checked",
    "deterministic_trusted",
    "leanstral_verified",
    "hammer_verified",
    "verifier_confirmed",
)


def _stable_json(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return round(value, 12)
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return list(value)
    return [value]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE


def _canonical_family_or_default(value: Any, default: str = "deontic") -> str:
    try:
        return canonical_legal_ir_evaluation_family(str(value or default))
    except ValueError:
        target = str(value or "").strip().lower()
        if target == "decompiler":
            return "decompiler"
        if target in {"temporal", "amendment", "stale_amendment"}:
            return "temporal"
        if target in {"citation", "wrong_citation", "source"}:
            return "provenance"
        return default


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _verification_payload(value: Any) -> dict[str, Any]:
    source = _as_mapping(value)
    verification = source.get("verification")
    if isinstance(verification, Mapping):
        merged = dict(verification)
        for key in ("trusted", "accepted", "verified", "proof_checked"):
            if key in source and key not in merged:
                merged[key] = source[key]
        return merged
    return {
        key: source[key]
        for key in (
            "accepted",
            "backend_statuses",
            "deterministic_trusted",
            "evidence_ids",
            "hammer_verified",
            "leanstral_verified",
            "proof_checked",
            "trusted",
            "verified",
            "verified_by",
        )
        if key in source
    }


def _verified(value: Any) -> bool:
    source = _as_mapping(value)
    verification = _verification_payload(value)
    if _truthy(source.get("trusted")) and not verification:
        return False
    return any(_truthy(verification.get(key)) for key in _VERIFIER_KEYS) or bool(
        verification.get("verified_by")
    )


@dataclass(frozen=True, slots=True)
class LegalIRHardNegativeConfig:
    """Policy for verified negative selection, scheduling, and effect gates."""

    legal_ir_families: tuple[str, ...] = LEGAL_IR_EVALUATION_FAMILIES
    negative_family_difficulty: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_NEGATIVE_FAMILY_DIFFICULTY)
    )
    legal_ir_family_difficulty: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_LEGAL_IR_FAMILY_DIFFICULTY)
    )
    stage_count: int = 4
    semantic_equivalence_false_positive_threshold: float = 0.80
    minimum_false_positive_reduction: float = 0.05
    trusted_positive_obligation_tolerance: float = 0.02
    require_verified_negatives: bool = True
    require_all_negative_families: bool = True
    require_trusted_positive_obligation_evidence: bool = True

    def __post_init__(self) -> None:
        families = tuple(
            canonical_legal_ir_evaluation_family(family) for family in self.legal_ir_families
        )
        if not families:
            raise ValueError("at least one LegalIR family is required")
        object.__setattr__(self, "legal_ir_families", families)
        stage_count = int(self.stage_count)
        if stage_count < 1:
            raise ValueError("stage_count must be at least 1")
        object.__setattr__(self, "stage_count", stage_count)
        for name in (
            "semantic_equivalence_false_positive_threshold",
            "minimum_false_positive_reduction",
            "trusted_positive_obligation_tolerance",
        ):
            value = _finite_float(getattr(self, name), -1.0)
            if value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "negative_family_difficulty",
            _normalized_difficulty_map(
                self.negative_family_difficulty,
                DEFAULT_NEGATIVE_FAMILY_DIFFICULTY,
            ),
        )
        object.__setattr__(
            self,
            "legal_ir_family_difficulty",
            _normalized_difficulty_map(
                self.legal_ir_family_difficulty,
                DEFAULT_LEGAL_IR_FAMILY_DIFFICULTY,
            ),
        )


@dataclass(frozen=True, slots=True)
class LegalIRHardNegativeExample:
    """One verified non-equivalence training example."""

    example_id: str
    negative_family: str
    semantic_family: str
    reference_ir: Any
    candidate_ir: Any
    verification: Mapping[str, Any]
    difficulty: float
    sample_id: str = ""
    label: str = "semantic_non_equivalence"
    source: str = "verified_oracle"
    trusted: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_text_sha256: str = ""

    def __post_init__(self) -> None:
        if self.negative_family not in HARD_NEGATIVE_FAMILIES:
            raise ValueError(f"unsupported hard-negative family: {self.negative_family!r}")
        object.__setattr__(
            self,
            "semantic_family",
            _canonical_family_or_default(self.semantic_family),
        )
        difficulty = min(1.0, max(0.0, _finite_float(self.difficulty, 0.0)))
        object.__setattr__(self, "difficulty", difficulty)

    @property
    def training_partition(self) -> str:
        return "trusted_hard_negative"

    @property
    def is_training_label(self) -> bool:
        return self.trusted and _verified(
            {"trusted": self.trusted, "verification": self.verification}
        )

    @property
    def semantic_equivalence_score(self) -> float:
        result = evaluate_legal_ir_semantic_equivalence(
            self.reference_ir,
            self.candidate_ir,
            family=self.semantic_family,
        )
        return min(result.scores.values()) if result.scores else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_ir": _json_ready(self.candidate_ir),
            "difficulty": round(self.difficulty, 12),
            "example_id": self.example_id,
            "is_training_label": self.is_training_label,
            "label": self.label,
            "metadata": _json_ready(self.metadata),
            "negative_family": self.negative_family,
            "reference_ir": _json_ready(self.reference_ir),
            "schema_version": LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION,
            "semantic_equivalence_score": round(self.semantic_equivalence_score, 12),
            "semantic_family": self.semantic_family,
            "source": self.source,
            "source_text_sha256": self.source_text_sha256,
            "sample_id": self.sample_id,
            "training_partition": self.training_partition,
            "trusted": self.trusted,
            "verification": _json_ready(self.verification),
        }


@dataclass(frozen=True, slots=True)
class RejectedHardNegative:
    """A candidate that was explicitly not promoted to a training label."""

    candidate_id: str
    reason: str
    source: str
    payload_digest: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "metadata": _json_ready(self.metadata),
            "payload_digest": self.payload_digest,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class LegalIRHardNegativeCurriculumStage:
    """One scheduled training stage."""

    stage_index: int
    min_difficulty: float
    max_difficulty: float
    examples: tuple[LegalIRHardNegativeExample, ...]

    @property
    def example_ids(self) -> tuple[str, ...]:
        return tuple(example.example_id for example in self.examples)

    @property
    def family_counts(self) -> Mapping[str, int]:
        return dict(Counter(example.negative_family for example in self.examples))

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_ids": list(self.example_ids),
            "family_counts": dict(self.family_counts),
            "max_difficulty": round(self.max_difficulty, 12),
            "min_difficulty": round(self.min_difficulty, 12),
            "stage_index": self.stage_index,
        }


@dataclass(frozen=True, slots=True)
class LegalIRHardNegativeCurriculum:
    """Complete scheduled hard-negative curriculum."""

    curriculum_id: str
    examples: tuple[LegalIRHardNegativeExample, ...]
    stages: tuple[LegalIRHardNegativeCurriculumStage, ...]
    rejected_candidates: tuple[RejectedHardNegative, ...]
    config: LegalIRHardNegativeConfig
    schema_version: str = LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION

    @property
    def accepted_count(self) -> int:
        return len(self.examples)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_candidates)

    @property
    def covered_negative_families(self) -> tuple[str, ...]:
        covered = {example.negative_family for example in self.examples}
        return tuple(family for family in HARD_NEGATIVE_FAMILIES if family in covered)

    @property
    def missing_negative_families(self) -> tuple[str, ...]:
        if not self.config.require_all_negative_families:
            return ()
        covered = set(self.covered_negative_families)
        return tuple(family for family in HARD_NEGATIVE_FAMILIES if family not in covered)

    @property
    def ready_for_training(self) -> bool:
        return (
            bool(self.examples)
            and not self.missing_negative_families
            and all(example.is_training_label for example in self.examples)
        )

    def by_family(self, negative_family: str) -> tuple[LegalIRHardNegativeExample, ...]:
        return tuple(
            example for example in self.examples if example.negative_family == negative_family
        )

    def to_dict(self, *, include_examples: bool = True) -> dict[str, Any]:
        payload = {
            "accepted_count": self.accepted_count,
            "covered_negative_families": list(self.covered_negative_families),
            "curriculum_id": self.curriculum_id,
            "missing_negative_families": list(self.missing_negative_families),
            "ready_for_training": self.ready_for_training,
            "rejected_candidates": [candidate.to_dict() for candidate in self.rejected_candidates],
            "rejected_count": self.rejected_count,
            "schema_version": self.schema_version,
            "stages": [stage.to_dict() for stage in self.stages],
        }
        if include_examples:
            payload["examples"] = [example.to_dict() for example in self.examples]
        else:
            payload["example_ids"] = [example.example_id for example in self.examples]
        return payload


@dataclass(frozen=True, slots=True)
class HardNegativeEffectReport:
    """Evidence that hard negatives improved semantic-equivalence behavior."""

    curriculum_id: str
    negative_example_count: int
    baseline_false_positive_count: int
    trained_false_positive_count: int
    baseline_false_positive_rate: float
    trained_false_positive_rate: float
    false_positive_reduction: float
    minimum_false_positive_reduction: float
    trusted_positive_count: int
    worst_trusted_positive_degradation: float
    trusted_positive_tolerance: float
    trusted_positive_guard_passed: bool
    hard_negative_guard_passed: bool
    block_reasons: tuple[str, ...]
    per_negative: Mapping[str, Mapping[str, Any]]
    per_positive: Mapping[str, Mapping[str, Any]]
    schema_version: str = LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION

    @property
    def accepted(self) -> bool:
        return not self.block_reasons

    @property
    def hard_negatives_reduce_false_positive_semantic_equivalence(self) -> bool:
        return self.hard_negative_guard_passed

    @property
    def trusted_positive_obligations_within_tolerance(self) -> bool:
        return self.trusted_positive_guard_passed

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "baseline_false_positive_count": self.baseline_false_positive_count,
            "baseline_false_positive_rate": round(self.baseline_false_positive_rate, 12),
            "block_reasons": list(self.block_reasons),
            "curriculum_id": self.curriculum_id,
            "false_positive_reduction": round(self.false_positive_reduction, 12),
            "hard_negative_guard_passed": self.hard_negative_guard_passed,
            "hard_negatives_reduce_false_positive_semantic_equivalence": (
                self.hard_negatives_reduce_false_positive_semantic_equivalence
            ),
            "minimum_false_positive_reduction": round(
                self.minimum_false_positive_reduction,
                12,
            ),
            "negative_example_count": self.negative_example_count,
            "per_negative": _json_ready(self.per_negative),
            "per_positive": _json_ready(self.per_positive),
            "schema_version": self.schema_version,
            "trained_false_positive_count": self.trained_false_positive_count,
            "trained_false_positive_rate": round(self.trained_false_positive_rate, 12),
            "trusted_positive_count": self.trusted_positive_count,
            "trusted_positive_guard_passed": self.trusted_positive_guard_passed,
            "trusted_positive_obligations_within_tolerance": (
                self.trusted_positive_obligations_within_tolerance
            ),
            "trusted_positive_tolerance": round(self.trusted_positive_tolerance, 12),
            "worst_trusted_positive_degradation": round(
                self.worst_trusted_positive_degradation,
                12,
            ),
        }


class LegalIRHardNegativeCurriculumBuilder:
    """Build and schedule verified LegalIR hard-negative examples."""

    def __init__(self, config: Optional[LegalIRHardNegativeConfig] = None) -> None:
        self.config = config or LegalIRHardNegativeConfig()

    def build(
        self,
        *,
        verified_counterexamples: Sequence[Any] = (),
        source_records: Sequence[Any] = (),
        model_negatives: Sequence[Any] = (),
    ) -> LegalIRHardNegativeCurriculum:
        accepted: list[LegalIRHardNegativeExample] = []
        rejected: list[RejectedHardNegative] = []

        for item in verified_counterexamples:
            example = self._example_from_counterexample(item)
            if example is None:
                rejected.append(_rejected(item, "unverified_counterexample_not_training_label"))
            else:
                accepted.append(example)

        for record in source_records:
            if not _verified(record):
                rejected.append(_rejected(record, "unverified_source_record"))
                continue
            accepted.extend(self._examples_from_source_record(record))

        for item in model_negatives:
            if not _verified(item):
                rejected.append(
                    _rejected(
                        item,
                        "unverified_model_negative_not_training_label",
                        source="model_negative",
                    )
                )
                continue
            example = self._example_from_model_negative(item)
            if example is None:
                rejected.append(
                    _rejected(
                        item,
                        "model_negative_missing_reference_or_candidate",
                        source="model_negative",
                    )
                )
            else:
                accepted.append(example)

        deduped = _dedupe_examples(accepted)
        scheduled = self._schedule(deduped)
        descriptor = {
            "examples": [example.example_id for example in deduped],
            "rejected": [item.payload_digest for item in rejected],
            "stages": [stage.example_ids for stage in scheduled],
        }
        return LegalIRHardNegativeCurriculum(
            curriculum_id="lir-hard-negative-curriculum-" + _stable_hash(descriptor)[:24],
            examples=deduped,
            stages=scheduled,
            rejected_candidates=tuple(rejected),
            config=self.config,
        )

    def _example_from_counterexample(
        self,
        candidate: Any,
    ) -> Optional[LegalIRHardNegativeExample]:
        if self.config.require_verified_negatives and not _verified(candidate):
            return None
        source = _as_mapping(candidate)
        minimal = source.get("minimal_counterexample", source.get("candidate_ir", source))
        reference = source.get("reference_ir", source.get("original_ir", {}))
        target = source.get("target", source.get("semantic_family", "deontic"))
        negative_family = _counterexample_negative_family(source, minimal)
        semantic_family = _canonical_family_or_default(
            source.get("semantic_family") or _family_from_target(target)
        )
        verification = _verification_payload(candidate)
        difficulty = self._difficulty(negative_family, semantic_family)
        example_id = (
            source.get("candidate_id")
            or source.get("example_id")
            or (
                "lir-hard-negative-"
                + _stable_hash(
                    {
                        "family": negative_family,
                        "minimal": minimal,
                        "reference": reference,
                        "verification": verification,
                    }
                )[:24]
            )
        )
        return LegalIRHardNegativeExample(
            example_id=str(example_id),
            negative_family=negative_family,
            semantic_family=semantic_family,
            reference_ir=reference,
            candidate_ir=minimal,
            verification=verification,
            difficulty=difficulty,
            sample_id=str(source.get("sample_id") or ""),
            source="verified_counterexample",
            trusted=True,
            metadata={
                "source_mutation_id": source.get("source_mutation_id", ""),
                "target": target,
            },
            source_text_sha256=str(source.get("source_text_sha256") or ""),
        )

    def _examples_from_source_record(
        self,
        record: Any,
    ) -> tuple[LegalIRHardNegativeExample, ...]:
        source = _as_mapping(record)
        text = str(source.get("text") or source.get("source_text") or "")
        reference = copy.deepcopy(
            source.get("reference_ir")
            or source.get("canonical_ir")
            or _reference_ir_from_text(text, source)
        )
        semantic_family = _canonical_family_or_default(
            source.get("semantic_family") or source.get("family") or "deontic"
        )
        sample_id = str(source.get("sample_id") or source.get("id") or "")
        verification = {
            "deterministic_mutation_oracle": True,
            "source_record_verified": True,
            "verified": True,
            "verified_by": [
                "trusted_positive_source_record",
                "deterministic_hard_negative_mutation",
                "semantic_non_equivalence_metric",
            ],
        }
        if _verification_payload(record):
            verification["source_verification"] = _verification_payload(record)
        variants = (
            (NEAR_MISS_CLAUSE, _near_miss(reference, text)),
            (SWAPPED_ACTOR, _swap_actor(reference, text)),
            (INVERTED_MODALITY, _invert_modality(reference, text)),
            (STALE_AMENDMENT, _stale_amendment(reference, source)),
            (WRONG_CITATION, _wrong_citation(reference, source)),
            (SOURCE_COPY_SPAN, _source_copy_candidate(text, source)),
            (DECOMPILER_HALLUCINATION, _decompiler_hallucination(reference, source)),
        )
        examples: list[LegalIRHardNegativeExample] = []
        for negative_family, candidate in variants:
            family = (
                "decompiler" if negative_family == DECOMPILER_HALLUCINATION else semantic_family
            )
            if negative_family in {WRONG_CITATION, SOURCE_COPY_SPAN}:
                family = "provenance"
            if negative_family == STALE_AMENDMENT:
                family = "temporal"
            metric = evaluate_legal_ir_semantic_equivalence(
                reference,
                candidate,
                family=family,
            )
            if all(score >= 1.0 for score in metric.scores.values()):
                continue
            payload = {
                "candidate": candidate,
                "family": family,
                "negative_family": negative_family,
                "reference": reference,
                "sample_id": sample_id,
            }
            examples.append(
                LegalIRHardNegativeExample(
                    example_id="lir-hard-negative-" + _stable_hash(payload)[:24],
                    negative_family=negative_family,
                    semantic_family=family,
                    reference_ir=reference,
                    candidate_ir=candidate,
                    verification={
                        **verification,
                        "semantic_scores": metric.scores,
                        "raw_deltas": metric.raw_deltas,
                    },
                    difficulty=self._difficulty(negative_family, family),
                    sample_id=sample_id,
                    source="deterministic_mutation_oracle",
                    trusted=True,
                    metadata={
                        "source_record_digest": _stable_hash(source),
                        "source_citation": source.get("citation", ""),
                    },
                    source_text_sha256=str(source.get("source_text_sha256") or _text_hash(text))
                    if text
                    else "",
                )
            )
        return tuple(examples)

    def _example_from_model_negative(
        self,
        item: Any,
    ) -> Optional[LegalIRHardNegativeExample]:
        source = _as_mapping(item)
        reference = source.get("reference_ir", source.get("canonical_ir"))
        candidate = source.get("candidate_ir", source.get("predicted_ir"))
        if reference is None or candidate is None:
            return None
        negative_family = str(source.get("negative_family") or VERIFIED_COUNTEREXAMPLE)
        if negative_family not in HARD_NEGATIVE_FAMILIES:
            negative_family = VERIFIED_COUNTEREXAMPLE
        semantic_family = _canonical_family_or_default(source.get("semantic_family"))
        return LegalIRHardNegativeExample(
            example_id=str(
                source.get("example_id") or "lir-hard-negative-" + _stable_hash(source)[:24]
            ),
            negative_family=negative_family,
            semantic_family=semantic_family,
            reference_ir=reference,
            candidate_ir=candidate,
            verification=_verification_payload(item),
            difficulty=self._difficulty(negative_family, semantic_family),
            sample_id=str(source.get("sample_id") or ""),
            source="verified_model_negative",
            trusted=True,
            metadata={"model_origin": source.get("model_origin", "")},
            source_text_sha256=str(source.get("source_text_sha256") or ""),
        )

    def _difficulty(self, negative_family: str, semantic_family: str) -> float:
        return min(
            1.0,
            self.config.negative_family_difficulty.get(negative_family, 0.5)
            + self.config.legal_ir_family_difficulty.get(semantic_family, 0.0),
        )

    def _schedule(
        self,
        examples: Sequence[LegalIRHardNegativeExample],
    ) -> tuple[LegalIRHardNegativeCurriculumStage, ...]:
        ordered = tuple(
            sorted(
                examples,
                key=lambda item: (
                    item.difficulty,
                    HARD_NEGATIVE_FAMILIES.index(item.negative_family),
                    item.semantic_family,
                    item.example_id,
                ),
            )
        )
        if not ordered:
            return ()
        stages: list[LegalIRHardNegativeCurriculumStage] = []
        for stage_index in range(self.config.stage_count):
            lower = stage_index / self.config.stage_count
            upper = (stage_index + 1) / self.config.stage_count
            stage_examples = tuple(
                example
                for example in ordered
                if (
                    lower <= example.difficulty < upper
                    or (
                        stage_index == self.config.stage_count - 1
                        and lower <= example.difficulty <= upper
                    )
                )
            )
            if stage_examples:
                stages.append(
                    LegalIRHardNegativeCurriculumStage(
                        stage_index=stage_index,
                        min_difficulty=min(example.difficulty for example in stage_examples),
                        max_difficulty=max(example.difficulty for example in stage_examples),
                        examples=stage_examples,
                    )
                )
        return tuple(stages)


def build_legal_ir_hard_negative_curriculum(
    *,
    verified_counterexamples: Sequence[Any] = (),
    source_records: Sequence[Any] = (),
    model_negatives: Sequence[Any] = (),
    config: Optional[LegalIRHardNegativeConfig] = None,
) -> LegalIRHardNegativeCurriculum:
    """Build a staged curriculum from verified LegalIR negative evidence."""

    return LegalIRHardNegativeCurriculumBuilder(config=config).build(
        verified_counterexamples=verified_counterexamples,
        source_records=source_records,
        model_negatives=model_negatives,
    )


def prove_hard_negatives_reduce_false_positive_semantic_equivalence(
    curriculum: LegalIRHardNegativeCurriculum,
    *,
    baseline_scores: Mapping[str, Any],
    trained_scores: Mapping[str, Any],
    trusted_positive_obligations: Sequence[Any],
    config: Optional[LegalIRHardNegativeConfig] = None,
) -> HardNegativeEffectReport:
    """Gate hard-negative training by negative and trusted-positive evidence."""

    cfg = config or curriculum.config
    threshold = cfg.semantic_equivalence_false_positive_threshold
    per_negative: dict[str, dict[str, Any]] = {}
    baseline_fp = 0
    trained_fp = 0
    for example in curriculum.examples:
        before = _score_for_id(baseline_scores, example.example_id, default=1.0)
        after = _score_for_id(trained_scores, example.example_id, default=before)
        before_fp = before >= threshold
        after_fp = after >= threshold
        baseline_fp += int(before_fp)
        trained_fp += int(after_fp)
        per_negative[example.example_id] = {
            "after_score": after,
            "baseline_score": before,
            "baseline_false_positive": before_fp,
            "false_positive_removed": before_fp and not after_fp,
            "negative_family": example.negative_family,
            "semantic_family": example.semantic_family,
            "trained_false_positive": after_fp,
        }

    total = len(curriculum.examples)
    baseline_rate = baseline_fp / total if total else 0.0
    trained_rate = trained_fp / total if total else 0.0
    reduction = baseline_rate - trained_rate
    hard_negative_guard = (
        total > 0
        and reduction + 1.0e-12 >= cfg.minimum_false_positive_reduction
        and trained_fp <= baseline_fp
    )

    per_positive: dict[str, dict[str, Any]] = {}
    worst_degradation = 0.0
    verified_positive_count = 0
    for index, obligation in enumerate(trusted_positive_obligations):
        source = _as_mapping(obligation)
        if not _verified(source):
            continue
        positive_id = str(
            source.get("obligation_id")
            or source.get("sample_id")
            or source.get("id")
            or f"trusted-positive-{index}"
        )
        before = _positive_before_score(source)
        after = _positive_after_score(source, default=before)
        degradation = max(0.0, before - after)
        worst_degradation = max(worst_degradation, degradation)
        verified_positive_count += 1
        per_positive[positive_id] = {
            "after_score": after,
            "baseline_score": before,
            "degradation": degradation,
            "within_tolerance": degradation <= cfg.trusted_positive_obligation_tolerance,
        }

    positive_guard = worst_degradation <= cfg.trusted_positive_obligation_tolerance and (
        verified_positive_count > 0 or not cfg.require_trusted_positive_obligation_evidence
    )
    block_reasons: list[str] = []
    if not curriculum.ready_for_training:
        block_reasons.append("curriculum_not_ready_for_training")
    if not hard_negative_guard:
        block_reasons.append("hard_negatives_did_not_reduce_false_positive_equivalence")
    if verified_positive_count == 0 and cfg.require_trusted_positive_obligation_evidence:
        block_reasons.append("trusted_positive_obligation_evidence_missing")
    elif not positive_guard:
        block_reasons.append("trusted_positive_obligation_degraded_beyond_tolerance")

    return HardNegativeEffectReport(
        curriculum_id=curriculum.curriculum_id,
        negative_example_count=total,
        baseline_false_positive_count=baseline_fp,
        trained_false_positive_count=trained_fp,
        baseline_false_positive_rate=baseline_rate,
        trained_false_positive_rate=trained_rate,
        false_positive_reduction=reduction,
        minimum_false_positive_reduction=cfg.minimum_false_positive_reduction,
        trusted_positive_count=verified_positive_count,
        worst_trusted_positive_degradation=worst_degradation,
        trusted_positive_tolerance=cfg.trusted_positive_obligation_tolerance,
        trusted_positive_guard_passed=positive_guard,
        hard_negative_guard_passed=hard_negative_guard,
        block_reasons=tuple(block_reasons),
        per_negative=per_negative,
        per_positive=per_positive,
    )


def hard_negative_training_effect_gate(
    curriculum: LegalIRHardNegativeCurriculum,
    *,
    baseline_scores: Mapping[str, Any],
    trained_scores: Mapping[str, Any],
    trusted_positive_obligations: Sequence[Any],
    config: Optional[LegalIRHardNegativeConfig] = None,
) -> dict[str, Any]:
    """Dictionary API for rollout and promotion gate callers."""

    return prove_hard_negatives_reduce_false_positive_semantic_equivalence(
        curriculum,
        baseline_scores=baseline_scores,
        trained_scores=trained_scores,
        trusted_positive_obligations=trusted_positive_obligations,
        config=config,
    ).to_dict()


def _normalized_difficulty_map(
    supplied: Mapping[str, float],
    defaults: Mapping[str, float],
) -> dict[str, float]:
    values = dict(defaults)
    for key, value in supplied.items():
        score = _finite_float(value, defaults.get(str(key), 0.5))
        values[str(key)] = min(1.0, max(0.0, score))
    return values


def _dedupe_examples(
    examples: Sequence[LegalIRHardNegativeExample],
) -> tuple[LegalIRHardNegativeExample, ...]:
    by_digest: dict[str, LegalIRHardNegativeExample] = {}
    for example in examples:
        digest = _stable_hash(
            {
                "candidate": example.candidate_ir,
                "family": example.negative_family,
                "reference": example.reference_ir,
                "semantic_family": example.semantic_family,
            }
        )
        existing = by_digest.get(digest)
        if existing is None or example.difficulty < existing.difficulty:
            by_digest[digest] = example
    return tuple(by_digest.values())


def _rejected(
    value: Any,
    reason: str,
    *,
    source: str = "verified_counterexample",
) -> RejectedHardNegative:
    mapping = _as_mapping(value)
    return RejectedHardNegative(
        candidate_id=str(
            mapping.get("candidate_id")
            or mapping.get("example_id")
            or "rejected-" + _stable_hash(value)[:16]
        ),
        reason=reason,
        source=source,
        payload_digest=_stable_hash(value),
        metadata={"trusted": mapping.get("trusted", False)},
    )


def _counterexample_negative_family(source: Mapping[str, Any], minimal: Any) -> str:
    verification = _verification_payload(source)
    grammar_rejections = " ".join(
        str(item) for item in _sequence(verification.get("grammar_rejections"))
    ).lower()
    target = str(source.get("target", "")).lower()
    if "source_copy" in grammar_rejections or _contains_source_copy_marker(minimal):
        return SOURCE_COPY_SPAN
    if target == "decompiler":
        return DECOMPILER_HALLUCINATION
    return VERIFIED_COUNTEREXAMPLE


def _contains_source_copy_marker(value: Any) -> bool:
    if isinstance(value, Mapping):
        policy = str(value.get("source_copy_policy", "")).lower()
        if policy in {"hash_only", "raw_source", "source_span"}:
            return True
        return any(_contains_source_copy_marker(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return any(_contains_source_copy_marker(item) for item in value)
    if isinstance(value, str):
        return "source_copy" in value.lower()
    return False


def _family_from_target(target: Any) -> str:
    name = str(target or "").lower()
    if name == "decompiler":
        return "decompiler"
    if name in {"wrong_citation", "source_copy_span"}:
        return "provenance"
    if name == "stale_amendment":
        return "temporal"
    return "deontic"


def _reference_ir_from_text(text: str, source: Mapping[str, Any]) -> dict[str, Any]:
    citation = source.get("citation", "")
    actor = _first_match(text, (r"\b(the\s+agency)\b", r"\b(an?\s+\w+)\b"), "agency")
    modality = _modality(text)
    return {
        "citation": citation,
        "rules": [
            {
                "actor": actor,
                "action": _action_after_modality(text),
                "modality": modality,
                "object": "legal_obligation",
                "text_digest": _text_hash(text) if text else "",
            }
        ],
        "temporal": _temporal_window(text),
    }


def _near_miss(reference: Any, text: str) -> Any:
    candidate = copy.deepcopy(reference)
    if isinstance(candidate, Mapping):
        candidate = dict(candidate)
        candidate["near_miss_clause"] = _near_miss_text(text)
        rules = _sequence(candidate.get("rules"))
        if rules and isinstance(rules[0], Mapping):
            first = dict(rules[0])
            first["exception"] = "removed" if "unless" in text.lower() else "spurious"
            rules[0] = first
            candidate["rules"] = rules
    return candidate


def _swap_actor(reference: Any, text: str) -> Any:
    candidate = copy.deepcopy(reference)
    replacement = "applicant" if "agency" in text.lower() else "agency"
    return _mutate_rule_field(candidate, ("actor", "subject"), replacement)


def _invert_modality(reference: Any, text: str) -> Any:
    return _mutate_rule_field(
        copy.deepcopy(reference), ("modality", "operator"), _flip_modality(_modality(text))
    )


def _stale_amendment(reference: Any, source: Mapping[str, Any]) -> Any:
    candidate = copy.deepcopy(reference)
    if not isinstance(candidate, Mapping):
        candidate = {"reference": candidate}
    candidate = dict(candidate)
    candidate["authority"] = {
        "amendment_status": "repealed",
        "current_authority": False,
        "effective_date": source.get("superseded_date", "1999-01-01"),
        "superseded_by": source.get("current_citation", source.get("citation", "")),
    }
    return candidate


def _wrong_citation(reference: Any, source: Mapping[str, Any]) -> Any:
    candidate = copy.deepcopy(reference)
    if not isinstance(candidate, Mapping):
        candidate = {"reference": candidate}
    candidate = dict(candidate)
    citation = str(source.get("citation") or candidate.get("citation") or "5 U.S.C. 552")
    candidate["citation"] = _wrong_citation_text(citation)
    candidate["citation_verified"] = False
    return candidate


def _source_copy_candidate(text: str, source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_copy_policy": "hash_only",
        "source_span": {
            "redacted": True,
            "sha256": _text_hash(text),
        },
        "target_view": source.get("target_view", "deontic.ir"),
        "verbatim_source_copy": True,
    }


def _decompiler_hallucination(reference: Any, source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "feature_targets": [
            "hallucinated_exception=sovereign_immunity",
            "hallucinated_actor=tribunal",
        ],
        "reference_digest": _stable_hash(reference),
        "source": "decompiler",
        "target_view": source.get("target_view", "decompiler"),
    }


def _mutate_rule_field(value: Any, names: Sequence[str], replacement: str) -> Any:
    candidate = copy.deepcopy(value)
    if not isinstance(candidate, Mapping):
        return {"mutated_field": names[0], "replacement": replacement, "reference": candidate}
    candidate = dict(candidate)
    rules = _sequence(candidate.get("rules"))
    if rules and isinstance(rules[0], Mapping):
        first = dict(rules[0])
        for name in names:
            if name in first:
                first[name] = replacement
                break
        else:
            first[names[0]] = replacement
        rules[0] = first
        candidate["rules"] = rules
    else:
        candidate[names[0]] = replacement
    return candidate


def _near_miss_text(text: str) -> str:
    if re.search(r"\bunless\b", text, flags=re.I):
        return re.sub(r"\bunless\b", "if", text, count=1, flags=re.I)
    if re.search(r"\bif\b", text, flags=re.I):
        return re.sub(r"\bif\b", "unless", text, count=1, flags=re.I)
    return text + " unless an unverified exception applies"


def _wrong_citation_text(citation: str) -> str:
    match = re.search(r"(\d+)(?!.*\d)", citation)
    if not match:
        return citation + " (wrong citation)"
    number = str(int(match.group(1)) + 1)
    return citation[: match.start(1)] + number + citation[match.end(1) :]


def _first_match(text: str, patterns: Sequence[str], default: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return " ".join(match.group(1).lower().split())
    return default


def _modality(text: str) -> str:
    lowered = text.lower()
    if "shall not" in lowered or "must not" in lowered or "may not" in lowered:
        return "prohibition"
    if re.search(r"\bmay\b", lowered):
        return "permission"
    return "obligation"


def _flip_modality(value: str) -> str:
    if value == "permission":
        return "obligation"
    if value == "prohibition":
        return "permission"
    return "permission"


def _action_after_modality(text: str) -> str:
    match = re.search(r"\b(?:shall|must|may)\s+(not\s+)?([a-z][a-z_-]*)", text, re.I)
    if match:
        return "not_" + match.group(2).lower() if match.group(1) else match.group(2).lower()
    return "act"


def _temporal_window(text: str) -> str:
    match = re.search(
        r"\bwithin\s+\d+\s+(?:day|days|month|months|year|years)\b",
        text,
        re.I,
    )
    return match.group(0).lower() if match else ""


def _score_for_id(scores: Mapping[str, Any], example_id: str, *, default: float) -> float:
    value = scores.get(example_id, default)
    if isinstance(value, Mapping):
        for key in (
            "semantic_equivalence_score",
            "equivalence_score",
            "score",
            "probability",
        ):
            if key in value:
                return min(1.0, max(0.0, _finite_float(value[key], default)))
    return min(1.0, max(0.0, _finite_float(value, default)))


def _positive_before_score(source: Mapping[str, Any]) -> float:
    for key in (
        "before_obligation_equivalence",
        "baseline_obligation_equivalence",
        "before_score",
        "baseline_score",
        OBLIGATION_EQUIVALENCE,
        STRUCTURAL_EQUIVALENCE,
    ):
        if key in source:
            return min(1.0, max(0.0, _finite_float(source[key], 1.0)))
    return _semantic_score_from_positive_pair(source, "reference_ir", "baseline_ir")


def _positive_after_score(source: Mapping[str, Any], *, default: float) -> float:
    for key in (
        "after_obligation_equivalence",
        "trained_obligation_equivalence",
        "after_score",
        "trained_score",
    ):
        if key in source:
            return min(1.0, max(0.0, _finite_float(source[key], default)))
    return _semantic_score_from_positive_pair(
        source,
        "reference_ir",
        "trained_ir",
        default=default,
    )


def _semantic_score_from_positive_pair(
    source: Mapping[str, Any],
    reference_key: str,
    candidate_key: str,
    *,
    default: float = 1.0,
) -> float:
    if reference_key not in source or candidate_key not in source:
        return default
    result = evaluate_legal_ir_semantic_equivalence(
        source[reference_key],
        source[candidate_key],
        family=_canonical_family_or_default(source.get("semantic_family")),
    )
    values = [
        result.scores[metric] for metric in SEMANTIC_EQUIVALENCE_METRICS if metric in result.scores
    ]
    return min(values) if values else default


# ---------------------------------------------------------------------------
# PGIR-041 IRHardNegative@1 miner
# ---------------------------------------------------------------------------

IR_HARD_NEGATIVE_SHARD_INTERFACE: Final = "IRHardNegativeShard@1"
IR_HARD_NEGATIVE_SHARD_SCHEMA: Final = "ir-hard-negative-shard/v1"
IR_HARD_NEGATIVE_RECIPE_INTERFACE: Final = "IRHardNegativeRecipe@1"
IR_HARD_NEGATIVE_RECIPE_SCHEMA: Final = "ir-hard-negative-recipe/v1"
IR_HARD_NEGATIVE_MANIFEST_INTERFACE: Final = "IRHardNegativeManifest@1"
IR_HARD_NEGATIVE_MANIFEST_SCHEMA: Final = "ir-hard-negative-manifest/v1"
IR_HARD_NEGATIVE_INDEX_INTERFACE: Final = "IRHardNegativeIndex@1"
IR_HARD_NEGATIVE_MINER_VERSION: Final = "pgir-041-negative-miner-v1"
IR_HARD_NEGATIVE_TASK_ID: Final = "PGIR-041"

RECEIPT_COUNTEREXAMPLE: Final = "counterexample"
RECEIPT_NON_EQUIVALENCE: Final = "non_equivalence"
RECEIPT_SATISFIABILITY: Final = "satisfiability"
RECEIPT_ENTAILMENT: Final = "entailment"

RECEIPT_KINDS: Final[tuple[str, ...]] = (
    RECEIPT_COUNTEREXAMPLE,
    RECEIPT_NON_EQUIVALENCE,
    RECEIPT_SATISFIABILITY,
    RECEIPT_ENTAILMENT,
)

FALSE_NEGATIVE_SIBLING_CLASSES: Final[frozenset[SemanticRelationship]] = frozenset(
    {
        SemanticRelationship.EXACT,
        SemanticRelationship.ALPHA_EQUIVALENT,
        SemanticRelationship.CANONICAL_EQUIVALENT,
        SemanticRelationship.LOGICALLY_EQUIVALENT,
        SemanticRelationship.PROOF_EQUIVALENT,
        SemanticRelationship.TRANSLATION_EQUIVALENT,
        SemanticRelationship.PARAPHRASE,
        SemanticRelationship.EQUISATISFIABLE,
    }
)

DEFAULT_NEGATIVE_PAIR_DATA_DIR: Final = Path("data/ir_learning/pairs/negative")

_RELATIONSHIP_FROM_VALUE: Final[dict[str, SemanticRelationship]] = {
    item.value: item for item in SemanticRelationship
}

_RECEIPT_KIND_FOR_EVIDENCE: Final[dict[str, str]] = {
    EVIDENCE_COUNTEREXAMPLE: RECEIPT_COUNTEREXAMPLE,
    EVIDENCE_NON_EQUIVALENCE: RECEIPT_NON_EQUIVALENCE,
    EVIDENCE_SATISFIABILITY: RECEIPT_SATISFIABILITY,
    EVIDENCE_ENTAILMENT: RECEIPT_ENTAILMENT,
}

_AUTHORITY_FOR_EVIDENCE: Final[dict[str, LabelAuthority]] = {
    EVIDENCE_COUNTEREXAMPLE: LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER,
    EVIDENCE_NON_EQUIVALENCE: LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
    EVIDENCE_SATISFIABILITY: LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER,
    EVIDENCE_ENTAILMENT: LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
}

_RESULT_AUTHORITY_FOR_EVIDENCE: Final[dict[str, AuthorityKind]] = {
    EVIDENCE_COUNTEREXAMPLE: AuthorityKind.SATISFIABILITY,
    EVIDENCE_NON_EQUIVALENCE: AuthorityKind.SATISFIABILITY,
    EVIDENCE_SATISFIABILITY: AuthorityKind.SATISFIABILITY,
    EVIDENCE_ENTAILMENT: AuthorityKind.THEOREM_PROOF,
}


class HardNegativeMinerError(ValueError):
    """Raised when a candidate cannot become an ``IRHardNegative@1`` record."""


class HardNegativeAdmissionError(HardNegativeMinerError):
    """Raised when an explicit evidence or false-negative gate fails closed."""


class HardNegativeShardConflictError(HardNegativeMinerError):
    """Raised when a compare-and-swap shard write would clobber different bytes."""


class HardNegativeRejection(str, Enum):
    """Closed vocabulary of miner rejection reasons."""

    TIMEOUT_AS_NEGATIVE = "timeout_as_negative"
    UNAVAILABLE_AS_NEGATIVE = "unavailable_as_negative"
    UNKNOWN_AS_NEGATIVE = "unknown_as_negative"
    UNCHECKED_MODEL_LABEL = "unchecked_model_label"
    SAME_PROPOSITION_SIBLING = "same_proposition_sibling"
    POSITIVE_EQUIVALENCE_SIBLING = "positive_equivalence_sibling"
    ALPHA_EQUIVALENT_SIBLING = "alpha_equivalent_sibling"
    TRANSLATION_SIBLING = "translation_sibling"
    PROOF_EQUIVALENT_SIBLING = "proof_equivalent_sibling"
    PARSE_OR_TYPE_ERROR = "parse_or_type_error"
    MINIMALITY_UNCHECKED = "minimality_unchecked"
    MISSING_EVIDENCE = "missing_evidence"
    UNVERIFIED_EVIDENCE = "unverified_evidence"
    AUTHORITY_NOT_ADMITTED = "authority_not_admitted"
    ENDPOINTS_NOT_DISTINCT = "endpoints_not_distinct"
    NON_TRAINING_SPLIT = "non_training_split"
    INCOMPLETE_LINEAGE = "incomplete_lineage"
    RIGHTS_NOT_ADMITTED = "rights_not_admitted"
    DUPLICATE_NEGATIVE = "duplicate_negative"
    UNKNOWN_MUTATION_CLASS = "unknown_mutation_class"
    CONFIRMED_WITHOUT_MINIMALITY = "confirmed_without_minimality"


def _digest_for(*parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _short_id(digest: str, size: int = 16) -> str:
    hex_part = digest.split(":", 1)[-1]
    return hex_part[:size]


def _endpoint_key(statement: StatementBinding) -> tuple[str, str]:
    return (statement.statement_id, statement.statement_digest)


def hard_negative_authorities(relationship: SemanticRelationship) -> frozenset[LabelAuthority]:
    return _RELATION_AUTHORITIES.get(relationship, frozenset())


@dataclass(frozen=True, slots=True)
class HardNegativeCandidate:
    """One proposed mutation before fail-closed admission."""

    candidate_id: str
    original: StatementBinding
    mutant: StatementBinding
    mutation_class: MutationClass
    mutated_paths: tuple[str, ...]
    relationship: SemanticRelationship
    lineage: LineageBinding
    evidence: tuple[LabelEvidence, ...]
    minimality_checked: bool
    disposition: NegativeDisposition
    evidence_kind: str = RECEIPT_NON_EQUIVALENCE
    solver_outcome: str = "disproved"
    source_kind: str = "typed_mutation"
    split_name: str = TRAIN_SPLIT_NAME
    sibling_statement_ids: tuple[str, ...] = ()
    sibling_relationship: SemanticRelationship | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "disposition": self.disposition.value,
            "evidence": [item.to_dict() for item in self.evidence],
            "evidence_kind": self.evidence_kind,
            "lineage": self.lineage.to_dict(),
            "minimality_checked": self.minimality_checked,
            "mutant": self.mutant.to_dict(),
            "mutated_paths": list(self.mutated_paths),
            "mutation_class": self.mutation_class.value,
            "original": self.original.to_dict(),
            "relationship": self.relationship.value,
            "sibling_statement_ids": list(self.sibling_statement_ids),
            "solver_outcome": self.solver_outcome,
            "source_kind": self.source_kind,
            "split_name": self.split_name,
        }


@dataclass(frozen=True, slots=True)
class RejectedHardNegativePair:
    """A candidate that failed a fail-closed negative gate."""

    candidate_id: str
    reason: HardNegativeRejection
    detail: str
    mutation_class: str
    disposition: str = NegativeDisposition.QUARANTINED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "detail": self.detail,
            "disposition": self.disposition,
            "mutation_class": self.mutation_class,
            "reason": self.reason.value,
        }


@dataclass(frozen=True, slots=True)
class NegativeEvidenceReceipt:
    """Counterexample, satisfiability, non-equivalence, or entailment receipt."""

    receipt_id: str
    kind: str
    negative_id: str
    evidence_id: str
    evidence_digest: str
    authority: str
    independent: bool
    relationship: str
    solver_outcome: str
    minimality_checked: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "evidence_digest": self.evidence_digest,
            "evidence_id": self.evidence_id,
            "independent": self.independent,
            "kind": self.kind,
            "minimality_checked": self.minimality_checked,
            "negative_id": self.negative_id,
            "receipt_id": self.receipt_id,
            "relationship": self.relationship,
            "solver_outcome": self.solver_outcome,
        }


@dataclass(frozen=True, slots=True)
class AdmittedHardNegative:
    """An ``IRHardNegative@1`` plus the receipt that justified it."""

    record: IRHardNegative
    source_kind: str
    receipt: NegativeEvidenceReceipt | None
    example: IRTrainingExample

    @property
    def negative_id(self) -> str:
        return self.record.negative_id

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "example_cid": self.example.cid,
            "example_digest": self.example.digest,
            "negative": self.record.to_dict(),
            "negative_cid": self.record.cid,
            "negative_digest": self.record.digest,
            "source_kind": self.source_kind,
        }
        if self.receipt is not None:
            payload["receipt"] = self.receipt.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class HardNegativeIndex:
    """Read-only index of mined negatives by class and disposition."""

    interface: str = IR_HARD_NEGATIVE_INDEX_INTERFACE
    negatives_by_class: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    negatives_by_disposition: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    class_by_negative: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_by_negative": dict(self.class_by_negative),
            "interface": self.interface,
            "negatives_by_class": {
                key: list(value) for key, value in self.negatives_by_class.items()
            },
            "negatives_by_disposition": {
                key: list(value) for key, value in self.negatives_by_disposition.items()
            },
        }


@dataclass(frozen=True, slots=True)
class HardNegativeMiningResult:
    """Deterministic output of one hard-negative mining pass."""

    admitted: tuple[AdmittedHardNegative, ...]
    unknown: tuple[AdmittedHardNegative, ...]
    rejected: tuple[RejectedHardNegativePair, ...]
    index: HardNegativeIndex
    receipts: tuple[NegativeEvidenceReceipt, ...]
    miner_version: str = IR_HARD_NEGATIVE_MINER_VERSION
    interface: str = IR_HARD_NEGATIVE_INTERFACE

    @property
    def records(self) -> tuple[IRHardNegative, ...]:
        return tuple(item.record for item in (*self.admitted, *self.unknown))

    @property
    def covered_mutation_classes(self) -> tuple[str, ...]:
        seen = {item.record.mutation_class for item in self.admitted}
        return tuple(
            mutation_class.value
            for mutation_class in MINIMAL_MUTATION_CLASSES
            if mutation_class in seen
        )

    def identity(self) -> str:
        return content_digest(
            {
                "admitted": [item.to_dict() for item in self.admitted],
                "covered_mutation_classes": list(self.covered_mutation_classes),
                "interface": self.interface,
                "miner_version": self.miner_version,
                "rejected": [item.to_dict() for item in self.rejected],
                "unknown": [item.to_dict() for item in self.unknown],
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": [item.to_dict() for item in self.admitted],
            "admitted_count": len(self.admitted),
            "covered_mutation_classes": list(self.covered_mutation_classes),
            "identity": self.identity(),
            "index": self.index.to_dict(),
            "interface": self.interface,
            "miner_version": self.miner_version,
            "receipts": [item.to_dict() for item in self.receipts],
            "rejected": [item.to_dict() for item in self.rejected],
            "rejected_count": len(self.rejected),
            "unknown": [item.to_dict() for item in self.unknown],
            "unknown_count": len(self.unknown),
        }


def load_positive_equivalence_index(
    input_dir: str | Path | None = None,
) -> PositiveEquivalenceIndex:
    """Load the sealed PGIR-040 positive index used for false-negative protection."""

    if input_dir is not None:
        root = Path(input_dir)
        manifest_path = root / "manifest.json"
        if manifest_path.is_file():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            index_payload = payload.get("index") or {}
            return PositiveEquivalenceIndex(
                interface=str(
                    index_payload.get("interface") or PositiveEquivalenceIndex().interface
                ),
                pairs_by_class={
                    str(key): tuple(values)
                    for key, values in dict(index_payload.get("pairs_by_class") or {}).items()
                },
                siblings_by_statement={
                    str(key): tuple(values)
                    for key, values in dict(
                        index_payload.get("siblings_by_statement") or {}
                    ).items()
                },
                class_by_pair={
                    str(key): str(value)
                    for key, value in dict(index_payload.get("class_by_pair") or {}).items()
                },
            )
        pairs = load_positive_pair_shards(root)
        siblings: dict[str, set[str]] = {}
        class_by_pair: dict[str, str] = {}
        pairs_by_class: dict[str, list[str]] = {}
        for pair in pairs:
            class_by_pair[pair.pair_id] = pair.relationship.value
            pairs_by_class.setdefault(pair.relationship.value, []).append(pair.pair_id)
            siblings.setdefault(pair.left.statement_id, set()).add(pair.right.statement_id)
            siblings.setdefault(pair.right.statement_id, set()).add(pair.left.statement_id)
        return PositiveEquivalenceIndex(
            pairs_by_class={key: tuple(values) for key, values in pairs_by_class.items()},
            siblings_by_statement={
                key: tuple(sorted(values)) for key, values in sorted(siblings.items())
            },
            class_by_pair=class_by_pair,
        )
    try:
        return load_positive_equivalence_index(resolve_positive_pair_data_dir())
    except (OSError, json.JSONDecodeError, FileNotFoundError):
        return mine_canonical_positive_pairs().index


def _lineage_complete(lineage: LineageBinding, *statements: StatementBinding) -> bool:
    if not lineage.corpus_manifest_id or not lineage.corpus_manifest_cid:
        return False
    if not lineage.lineage_graph_id or not lineage.lineage_graph_cid:
        return False
    if not lineage.split_manifest_id or not lineage.split_manifest_digest:
        return False
    if not lineage.lineage_group_ids:
        return False
    if not lineage.source_record_ids and not lineage.parent_example_id:
        return False
    for statement in statements:
        if not statement.lineage_group_ids:
            return False
        if set(statement.lineage_group_ids) - set(lineage.lineage_group_ids):
            return False
        if not lineage.parent_example_id and (
            not statement.source_record_ids or not statement.source_ref_ids
        ):
            return False
        if set(statement.source_record_ids) - set(lineage.source_record_ids):
            return False
    return True


def _is_positive_or_same_proposition_sibling(
    candidate: HardNegativeCandidate,
    index: PositiveEquivalenceIndex,
) -> bool:
    original_id = candidate.original.statement_id
    mutant_id = candidate.mutant.statement_id
    siblings = set(index.siblings(original_id)) | set(candidate.sibling_statement_ids)
    return mutant_id in siblings or original_id in set(index.siblings(mutant_id))


def classify_hard_negative_candidate(
    candidate: HardNegativeCandidate,
    *,
    positive_index: PositiveEquivalenceIndex | None = None,
) -> HardNegativeRejection | None:
    """Return the first fail-closed rejection, or ``None`` when admissible."""

    index = positive_index or PositiveEquivalenceIndex()
    if candidate.mutation_class not in MINIMAL_MUTATION_CLASSES:
        return HardNegativeRejection.UNKNOWN_MUTATION_CLASS
    if _endpoint_key(candidate.original) == _endpoint_key(candidate.mutant):
        return HardNegativeRejection.ENDPOINTS_NOT_DISTINCT
    if candidate.lineage.rights_disposition is not RightsDisposition.ADMITTED:
        return HardNegativeRejection.RIGHTS_NOT_ADMITTED
    if not _lineage_complete(candidate.lineage, candidate.original, candidate.mutant):
        return HardNegativeRejection.INCOMPLETE_LINEAGE
    if (
        candidate.split_name != TRAIN_SPLIT_NAME
        or candidate.lineage.split_name != TRAIN_SPLIT_NAME
    ):
        return HardNegativeRejection.NON_TRAINING_SPLIT

    if _is_positive_or_same_proposition_sibling(candidate, index):
        sibling_class = candidate.sibling_relationship
        if sibling_class is SemanticRelationship.ALPHA_EQUIVALENT:
            return HardNegativeRejection.ALPHA_EQUIVALENT_SIBLING
        if sibling_class is SemanticRelationship.TRANSLATION_EQUIVALENT:
            return HardNegativeRejection.TRANSLATION_SIBLING
        if sibling_class is SemanticRelationship.PROOF_EQUIVALENT:
            return HardNegativeRejection.PROOF_EQUIVALENT_SIBLING
        if sibling_class in FALSE_NEGATIVE_SIBLING_CLASSES:
            return HardNegativeRejection.POSITIVE_EQUIVALENCE_SIBLING
        if mutant_in_index := (
            candidate.mutant.statement_id in set(index.siblings(candidate.original.statement_id))
            or candidate.original.statement_id in set(index.siblings(candidate.mutant.statement_id))
        ):
            return HardNegativeRejection.POSITIVE_EQUIVALENCE_SIBLING
        return HardNegativeRejection.SAME_PROPOSITION_SIBLING

    outcome = str(candidate.solver_outcome or "").strip().lower()
    if candidate.disposition is NegativeDisposition.CONFIRMED_NEGATIVE:
        if outcome in {SOLVER_TIMED_OUT, "timeout"}:
            return HardNegativeRejection.TIMEOUT_AS_NEGATIVE
        if outcome == SOLVER_UNAVAILABLE:
            return HardNegativeRejection.UNAVAILABLE_AS_NEGATIVE
        if (
            outcome == SOLVER_UNKNOWN
            or candidate.relationship is SemanticRelationship.UNKNOWN
        ):
            return HardNegativeRejection.UNKNOWN_AS_NEGATIVE
        if not candidate.minimality_checked:
            return HardNegativeRejection.CONFIRMED_WITHOUT_MINIMALITY
        if not candidate.evidence:
            return HardNegativeRejection.MISSING_EVIDENCE
        if any(item.authority in MODEL_ONLY_AUTHORITIES for item in candidate.evidence):
            return HardNegativeRejection.UNCHECKED_MODEL_LABEL
        verified = [
            item
            for item in candidate.evidence
            if item.status is EvidenceStatus.VERIFIED
            and item.relationship is candidate.relationship
        ]
        if not verified:
            return HardNegativeRejection.UNVERIFIED_EVIDENCE
        admitted = hard_negative_authorities(candidate.relationship)
        if any(item.authority not in admitted for item in verified):
            return HardNegativeRejection.AUTHORITY_NOT_ADMITTED
        if not any(
            item.independent and item.authority in INDEPENDENT_AUTHORITIES for item in verified
        ):
            return HardNegativeRejection.UNVERIFIED_EVIDENCE
    elif candidate.disposition is NegativeDisposition.UNKNOWN:
        if outcome in {SOLVER_TIMED_OUT, "timeout"}:
            return None
        if outcome == SOLVER_UNAVAILABLE:
            return None
        if candidate.relationship is not SemanticRelationship.UNKNOWN:
            return HardNegativeRejection.UNKNOWN_AS_NEGATIVE
    return None


def _negative_and_example(
    candidate: HardNegativeCandidate,
) -> tuple[IRHardNegative, IRTrainingExample]:
    negative_id = (
        f"negative:{candidate.mutation_class.value}:"
        f"{_short_id(_digest_for(candidate.original.statement_digest, candidate.mutant.statement_digest, candidate.mutation_class.value))}"
    )
    record = IRHardNegative(
        negative_id=negative_id,
        lineage=candidate.lineage,
        original=candidate.original,
        mutant=candidate.mutant,
        relationship=candidate.relationship,
        mutation_class=candidate.mutation_class,
        mutated_paths=candidate.mutated_paths,
        minimality_checked=candidate.minimality_checked,
        disposition=candidate.disposition,
        evidence=candidate.evidence,
    )
    selected = record.evidence[0].evidence_id if record.evidence else ""
    example = IRTrainingExample.classify(
        example_id=f"example:{record.negative_id}",
        record=record,
        selected_evidence_id=selected,
    )
    if (
        candidate.disposition is NegativeDisposition.CONFIRMED_NEGATIVE
        and not example.training_eligible
    ):
        raise HardNegativeAdmissionError(
            f"{record.negative_id} failed training admission: "
            + ", ".join(item.value for item in example.quarantine_reasons)
        )
    return record, example


def _receipt_for(
    record: IRHardNegative,
    candidate: HardNegativeCandidate,
) -> NegativeEvidenceReceipt | None:
    if not record.evidence or record.disposition is NegativeDisposition.UNKNOWN:
        return None
    evidence = record.evidence[0]
    kind = candidate.evidence_kind or RECEIPT_NON_EQUIVALENCE
    if kind not in RECEIPT_KINDS:
        raise HardNegativeAdmissionError(f"unknown receipt kind {kind!r}")
    return NegativeEvidenceReceipt(
        receipt_id=f"receipt:{kind}:{_short_id(evidence.evidence_digest)}",
        kind=kind,
        negative_id=record.negative_id,
        evidence_id=evidence.evidence_id,
        evidence_digest=evidence.evidence_digest,
        authority=evidence.authority.value,
        independent=evidence.independent,
        relationship=record.relationship.value,
        solver_outcome=candidate.solver_outcome,
        minimality_checked=record.minimality_checked,
    )


def _build_negative_index(
    admitted: Sequence[AdmittedHardNegative],
    unknown: Sequence[AdmittedHardNegative],
) -> HardNegativeIndex:
    by_class: dict[str, list[str]] = {item.value: [] for item in MINIMAL_MUTATION_CLASSES}
    by_disposition: dict[str, list[str]] = {
        NegativeDisposition.CONFIRMED_NEGATIVE.value: [],
        NegativeDisposition.UNKNOWN.value: [],
    }
    class_by_negative: dict[str, str] = {}
    for item in (*admitted, *unknown):
        record = item.record
        by_class.setdefault(record.mutation_class.value, []).append(record.negative_id)
        by_disposition.setdefault(record.disposition.value, []).append(record.negative_id)
        class_by_negative[record.negative_id] = record.mutation_class.value
    return HardNegativeIndex(
        negatives_by_class={key: tuple(values) for key, values in by_class.items() if values},
        negatives_by_disposition={
            key: tuple(values) for key, values in by_disposition.items() if values
        },
        class_by_negative=class_by_negative,
    )


def mine_hard_negatives(
    candidates: Sequence[HardNegativeCandidate],
    *,
    positive_index: PositiveEquivalenceIndex | None = None,
    raise_on_reject: bool = False,
) -> HardNegativeMiningResult:
    """Admit confirmed negatives, segregate unknowns, and reject false negatives."""

    index = positive_index or load_positive_equivalence_index()
    rejected: list[RejectedHardNegativePair] = []
    pending: list[HardNegativeCandidate] = []
    seen: set[tuple[tuple[str, str], tuple[str, str], str]] = set()

    for candidate in candidates:
        reason = classify_hard_negative_candidate(candidate, positive_index=index)
        if reason is not None:
            item = RejectedHardNegativePair(
                candidate_id=candidate.candidate_id,
                reason=reason,
                detail=reason.value,
                mutation_class=candidate.mutation_class.value,
            )
            rejected.append(item)
            if raise_on_reject:
                raise HardNegativeAdmissionError(f"{candidate.candidate_id}: {reason.value}")
            continue
        key = (
            _endpoint_key(candidate.original),
            _endpoint_key(candidate.mutant),
            candidate.mutation_class.value,
        )
        if key in seen:
            rejected.append(
                RejectedHardNegativePair(
                    candidate_id=candidate.candidate_id,
                    reason=HardNegativeRejection.DUPLICATE_NEGATIVE,
                    detail="duplicate endpoints and mutation class",
                    mutation_class=candidate.mutation_class.value,
                )
            )
            continue
        seen.add(key)
        pending.append(candidate)

    admitted: list[AdmittedHardNegative] = []
    unknown: list[AdmittedHardNegative] = []
    for candidate in sorted(
        pending,
        key=lambda item: (
            0 if item.disposition is NegativeDisposition.CONFIRMED_NEGATIVE else 1,
            item.mutation_class.value,
            item.original.statement_id,
            item.mutant.statement_id,
            item.candidate_id,
        ),
    ):
        record, example = _negative_and_example(candidate)
        receipt = _receipt_for(record, candidate)
        wrapped = AdmittedHardNegative(
            record=record,
            source_kind=candidate.source_kind,
            receipt=receipt,
            example=example,
        )
        if record.disposition is NegativeDisposition.UNKNOWN:
            unknown.append(wrapped)
        else:
            admitted.append(wrapped)

    receipts = tuple(item.receipt for item in admitted if item.receipt is not None)
    return HardNegativeMiningResult(
        admitted=tuple(admitted),
        unknown=tuple(unknown),
        rejected=tuple(
            sorted(rejected, key=lambda item: (item.reason.value, item.candidate_id))
        ),
        index=_build_negative_index(admitted, unknown),
        receipts=receipts,
    )


def candidate_from_validation_record(
    record: MutationValidationRecord,
    *,
    case_id: str | None = None,
    sibling_statement_ids: Sequence[str] = (),
    authority: LabelAuthority | None = None,
    evidence_status: EvidenceStatus | None = None,
    independent: bool | None = None,
) -> HardNegativeCandidate:
    """Bind a typed mutation validation record to a sealed candidate."""

    mutation = record.mutation
    case = case_id or mutation.mutation_class.value
    group = f"lineage:pgir-041:{case}"
    source = f"source:pgir-041:{case}"
    original = make_statement(
        f"{case}-original",
        digest=_digest_for("original", case, _stable_json(mutation.original)),
        representation=RepresentationKind.CANONICAL_IR,
        lineage_group_ids=(group,),
        source_record_ids=(source,),
    )
    mutant = make_statement(
        f"{case}-mutant",
        digest=_digest_for("mutant", case, _stable_json(mutation.mutant)),
        representation=RepresentationKind.CANONICAL_IR,
        lineage_group_ids=(group,),
        source_record_ids=(source,),
    )
    lineage = sealed_campaign_lineage(
        lineage_group_ids=(group,),
        source_record_ids=(source,),
    )
    if record.unknown or not record.confirmed:
        return HardNegativeCandidate(
            candidate_id=f"candidate:{case}",
            original=original,
            mutant=mutant,
            mutation_class=mutation.mutation_class,
            mutated_paths=record.minimal_mutated_paths or mutation.mutated_paths,
            relationship=SemanticRelationship.UNKNOWN,
            lineage=lineage,
            evidence=(),
            minimality_checked=False,
            disposition=NegativeDisposition.UNKNOWN,
            evidence_kind=mutation.evidence_kind,
            solver_outcome=record.solver_outcome,
            source_kind="typed_mutation",
            sibling_statement_ids=tuple(sibling_statement_ids),
        )
    kind = mutation.evidence_kind
    label_authority = authority or _AUTHORITY_FOR_EVIDENCE[kind]
    status = evidence_status or EvidenceStatus.VERIFIED
    relationship = _RELATIONSHIP_FROM_VALUE[record.relationship]
    evidence = make_relationship_evidence(
        original,
        mutant,
        relationship,
        evidence_id=f"evidence:{case}",
        authority=label_authority,
        status=status,
        independent=independent if independent is not None else label_authority in INDEPENDENT_AUTHORITIES,
        result_authority=_RESULT_AUTHORITY_FOR_EVIDENCE[kind],
        producer_id="checker:pgir-041",
        producer_version="1.0",
    )
    return HardNegativeCandidate(
        candidate_id=f"candidate:{case}",
        original=original,
        mutant=mutant,
        mutation_class=mutation.mutation_class,
        mutated_paths=record.minimal_mutated_paths or mutation.mutated_paths,
        relationship=relationship,
        lineage=lineage,
        evidence=(evidence,),
        minimality_checked=record.minimality_checked,
        disposition=NegativeDisposition.CONFIRMED_NEGATIVE,
        evidence_kind=_RECEIPT_KIND_FOR_EVIDENCE[kind],
        solver_outcome=record.solver_outcome,
        source_kind="typed_mutation",
        sibling_statement_ids=tuple(sibling_statement_ids),
    )


def candidate_from_recipe_case(case: Mapping[str, Any]) -> HardNegativeCandidate:
    """Expand one compact recipe case into a fully bound candidate."""

    if not isinstance(case, Mapping):
        raise HardNegativeMinerError("recipe case must be a mapping")
    case_id = str(case.get("case_id") or "").strip()
    if not case_id:
        raise HardNegativeMinerError("recipe case requires case_id")
    try:
        mutation_class = MutationClass(str(case.get("mutation_class") or ""))
    except ValueError as exc:
        raise HardNegativeMinerError(
            f"unknown mutation class {case.get('mutation_class')!r}"
        ) from exc
    solver_outcome = str(case.get("solver_outcome") or "")
    matching = next(
        (
            mutation
            for mutation in generate_minimal_semantic_mutations()
            if mutation.mutation_class is mutation_class
        ),
        None,
    )
    if matching is None:
        raise HardNegativeMinerError(f"no generator for {mutation_class.value}")
    record = collect_mutation_evidence(
        matching,
        solver_outcome=solver_outcome or matching.solver_outcome,
    )
    authority_raw = case.get("authority")
    authority = LabelAuthority(str(authority_raw)) if authority_raw else None
    status_raw = case.get("evidence_status")
    status = EvidenceStatus(str(status_raw)) if status_raw else None
    candidate = candidate_from_validation_record(
        record,
        case_id=case_id,
        sibling_statement_ids=tuple(case.get("sibling_statement_ids") or ()),
        authority=authority,
        evidence_status=status,
        independent=case.get("independent"),
    )
    if "disposition" in case:
        disposition = NegativeDisposition(str(case["disposition"]))
        relationship = (
            SemanticRelationship.UNKNOWN
            if disposition is NegativeDisposition.UNKNOWN
            else candidate.relationship
        )
        candidate = HardNegativeCandidate(
            candidate_id=candidate.candidate_id,
            original=candidate.original,
            mutant=candidate.mutant,
            mutation_class=candidate.mutation_class,
            mutated_paths=tuple(case.get("mutated_paths") or candidate.mutated_paths),
            relationship=relationship,
            lineage=candidate.lineage,
            evidence=() if disposition is NegativeDisposition.UNKNOWN else candidate.evidence,
            minimality_checked=(
                False
                if disposition is NegativeDisposition.UNKNOWN
                else candidate.minimality_checked
            ),
            disposition=disposition,
            evidence_kind=str(case.get("evidence_kind") or candidate.evidence_kind),
            solver_outcome=solver_outcome or candidate.solver_outcome,
            source_kind=str(case.get("source_kind") or candidate.source_kind),
            sibling_statement_ids=candidate.sibling_statement_ids,
        )
    return candidate


def canonical_hard_negative_recipe() -> dict[str, Any]:
    """Compact generator for the sealed PGIR-041 mutation-class coverage set."""

    cases: list[dict[str, Any]] = []
    for mutation_class in MINIMAL_MUTATION_CLASSES:
        matching = next(
            mutation
            for mutation in generate_minimal_semantic_mutations()
            if mutation.mutation_class is mutation_class
        )
        cases.append(
            {
                "authority": _AUTHORITY_FOR_EVIDENCE[matching.evidence_kind].value,
                "case_id": f"{mutation_class.value}-minimal",
                "disposition": NegativeDisposition.CONFIRMED_NEGATIVE.value,
                "evidence_kind": matching.evidence_kind,
                "independent": True,
                "mutation_class": mutation_class.value,
                "mutated_paths": list(matching.mutated_paths),
                "relationship": matching.relationship,
                "result_authority": _RESULT_AUTHORITY_FOR_EVIDENCE[matching.evidence_kind].value,
                "solver_outcome": matching.solver_outcome,
                "source_kind": "typed_mutation",
            }
        )
    cases.append(
        {
            "case_id": "solver-timeout-unknown",
            "disposition": NegativeDisposition.UNKNOWN.value,
            "mutation_class": MutationClass.OPERATOR.value,
            "relationship": SemanticRelationship.UNKNOWN.value,
            "solver_outcome": SOLVER_TIMED_OUT,
            "source_kind": "seeded_false_negative_fixture",
        }
    )
    recipe = {
        "cases": cases,
        "compiler_identity": "RESULT(PGIR-021)",
        "corpus_manifest_cid": SEALED_CORPUS_MANIFEST_CID,
        "corpus_manifest_id": SEALED_CORPUS_MANIFEST_ID,
        "corpus_root_sha256": SEALED_CORPUS_ROOT_SHA256,
        "decompiler_identity": "RESULT(PGIR-022)",
        "false_negative_protection": [
            "timeout_as_negative",
            "unavailable_as_negative",
            "unknown_as_negative",
            "same_proposition_sibling",
            "alpha_equivalent_sibling",
            "translation_sibling",
            "proof_equivalent_sibling",
            "unchecked_model_labels",
        ],
        "interface": IR_HARD_NEGATIVE_RECIPE_INTERFACE,
        "miner_version": IR_HARD_NEGATIVE_MINER_VERSION,
        "model_checkpoint_identity": "none/deterministic",
        "mutation_classes": [item.value for item in MINIMAL_MUTATION_CLASSES],
        "prohibited": [
            "timeout_unavailable_unknown_as_negative",
            "same_proposition_siblings_as_negatives",
            "unchecked_model_labels",
        ],
        "schema": IR_HARD_NEGATIVE_RECIPE_SCHEMA,
        "split_manifest_digest": SEALED_SPLIT_MANIFEST_DIGEST,
        "split_name": TRAIN_SPLIT_NAME,
        "split_root_sha256": SEALED_SPLIT_ROOT_SHA256,
        "task_id": IR_HARD_NEGATIVE_TASK_ID,
    }
    recipe["recipe_cid"] = content_cid(
        recipe,
        domain="ir.hard-negative-recipe",
        schema_version=IR_HARD_NEGATIVE_RECIPE_SCHEMA,
    )
    return recipe


def mutation_class_catalog() -> dict[str, Any]:
    catalog = {
        "classes": [
            {
                "authorities": [
                    item.value
                    for item in sorted(
                        hard_negative_authorities(
                            _RELATIONSHIP_FROM_VALUE[_CLASS_RELATIONSHIP_VALUE(mutation_class)]
                        ),
                        key=lambda item: item.value,
                    )
                ],
                "evidence_kind": _RECEIPT_KIND_FOR_MUTATION(mutation_class),
                "mutation_class": mutation_class.value,
                "relationship": _CLASS_RELATIONSHIP_VALUE(mutation_class),
            }
            for mutation_class in MINIMAL_MUTATION_CLASSES
        ],
        "interface": "IRHardNegativeClassCatalog@1",
        "schema": "ir-hard-negative-class/v1",
        "task_id": IR_HARD_NEGATIVE_TASK_ID,
    }
    catalog["catalog_cid"] = content_cid(
        catalog,
        domain="ir.hard-negative-class-catalog",
        schema_version="ir-hard-negative-class/v1",
    )
    return catalog


def _CLASS_RELATIONSHIP_VALUE(mutation_class: MutationClass) -> str:
    matching = next(
        mutation
        for mutation in generate_minimal_semantic_mutations()
        if mutation.mutation_class is mutation_class
    )
    return matching.relationship


def _RECEIPT_KIND_FOR_MUTATION(mutation_class: MutationClass) -> str:
    matching = next(
        mutation
        for mutation in generate_minimal_semantic_mutations()
        if mutation.mutation_class is mutation_class
    )
    return _RECEIPT_KIND_FOR_EVIDENCE[matching.evidence_kind]


def mine_canonical_hard_negatives() -> HardNegativeMiningResult:
    recipe = canonical_hard_negative_recipe()
    candidates = tuple(candidate_from_recipe_case(case) for case in recipe["cases"])
    return mine_hard_negatives(candidates)


def build_hard_negative_shards(
    result: HardNegativeMiningResult,
    *,
    recipe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    recipe_payload = dict(recipe or canonical_hard_negative_recipe())
    shards: list[dict[str, Any]] = []
    for mutation_class in MINIMAL_MUTATION_CLASSES:
        members = [
            item.to_dict()
            for item in result.admitted
            if item.record.mutation_class is mutation_class
        ]
        if not members:
            continue
        body = {
            "class": mutation_class.value,
            "disposition": NegativeDisposition.CONFIRMED_NEGATIVE.value,
            "interface": IR_HARD_NEGATIVE_SHARD_INTERFACE,
            "miner_version": IR_HARD_NEGATIVE_MINER_VERSION,
            "negatives": members,
            "pair_count": len(members),
            "schema": IR_HARD_NEGATIVE_SHARD_SCHEMA,
            "split_name": TRAIN_SPLIT_NAME,
            "task_id": IR_HARD_NEGATIVE_TASK_ID,
        }
        shards.append(
            {
                **body,
                "shard_cid": content_cid(
                    body,
                    domain="ir.hard-negative-shard",
                    schema_version=IR_HARD_NEGATIVE_SHARD_SCHEMA,
                ),
                "shard_digest": content_digest(body),
            }
        )
    if result.unknown:
        unknown_body = {
            "class": "unknown",
            "disposition": NegativeDisposition.UNKNOWN.value,
            "interface": IR_HARD_NEGATIVE_SHARD_INTERFACE,
            "miner_version": IR_HARD_NEGATIVE_MINER_VERSION,
            "negatives": [item.to_dict() for item in result.unknown],
            "pair_count": len(result.unknown),
            "schema": IR_HARD_NEGATIVE_SHARD_SCHEMA,
            "split_name": TRAIN_SPLIT_NAME,
            "task_id": IR_HARD_NEGATIVE_TASK_ID,
        }
        shards.append(
            {
                **unknown_body,
                "shard_cid": content_cid(
                    unknown_body,
                    domain="ir.hard-negative-shard",
                    schema_version=IR_HARD_NEGATIVE_SHARD_SCHEMA,
                ),
                "shard_digest": content_digest(unknown_body),
            }
        )
    receipts = {
        "interface": "IRHardNegativeReceiptSet@1",
        "kinds": sorted({item.kind for item in result.receipts}),
        "receipts": [item.to_dict() for item in result.receipts],
        "schema": "ir-hard-negative-receipts/v1",
        "task_id": IR_HARD_NEGATIVE_TASK_ID,
    }
    receipts["receipts_cid"] = content_cid(
        receipts,
        domain="ir.hard-negative-receipts",
        schema_version="ir-hard-negative-receipts/v1",
    )
    catalog = mutation_class_catalog()
    manifest = {
        "corpus_manifest_cid": SEALED_CORPUS_MANIFEST_CID,
        "covered_mutation_classes": list(result.covered_mutation_classes),
        "index": result.index.to_dict(),
        "interface": IR_HARD_NEGATIVE_MANIFEST_INTERFACE,
        "miner_identity": result.identity(),
        "miner_version": IR_HARD_NEGATIVE_MINER_VERSION,
        "model_checkpoint_identity": "none/deterministic",
        "pair_count": len(result.admitted) + len(result.unknown),
        "recipe_cid": recipe_payload.get("recipe_cid"),
        "receipts_cid": receipts["receipts_cid"],
        "rejected_count": len(result.rejected),
        "schema": IR_HARD_NEGATIVE_MANIFEST_SCHEMA,
        "shards": [
            {
                "class": shard["class"],
                "disposition": shard["disposition"],
                "pair_count": shard["pair_count"],
                "path": f"shards/{shard['class']}.json",
                "shard_cid": shard["shard_cid"],
                "shard_digest": shard["shard_digest"],
            }
            for shard in shards
        ],
        "split_manifest_digest": SEALED_SPLIT_MANIFEST_DIGEST,
        "split_name": TRAIN_SPLIT_NAME,
        "task_id": IR_HARD_NEGATIVE_TASK_ID,
        "unknown_count": len(result.unknown),
    }
    manifest["manifest_cid"] = content_cid(
        manifest,
        domain="ir.hard-negative-manifest",
        schema_version=IR_HARD_NEGATIVE_MANIFEST_SCHEMA,
    )
    return {
        "catalog": catalog,
        "manifest": manifest,
        "receipts": receipts,
        "recipe": recipe_payload,
        "shards": shards,
    }


def write_hard_negative_shards(
    output_dir: str | Path,
    *,
    result: HardNegativeMiningResult | None = None,
    recipe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist immutable recipe, class catalog, receipts, and class shards."""

    mined = result or mine_canonical_hard_negatives()
    bundle = build_hard_negative_shards(mined, recipe=recipe)
    root = Path(output_dir)
    try:
        cas_write_json(root / "recipe.json", bundle["recipe"])
        cas_write_json(root / "classes.json", bundle["catalog"])
        cas_write_json(root / "receipts.json", bundle["receipts"])
        cas_write_json(root / "manifest.json", bundle["manifest"])
        for shard in bundle["shards"]:
            cas_write_json(root / "shards" / f"{shard['class']}.json", shard)
    except Exception as exc:
        raise HardNegativeShardConflictError(str(exc)) from exc
    return bundle


def load_hard_negative_shards(input_dir: str | Path) -> tuple[IRHardNegative, ...]:
    root = Path(input_dir)
    records: list[IRHardNegative] = []
    for path in sorted((root / "shards").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get("negatives", ()):
            records.append(IRHardNegative.from_dict(item["negative"]))
    return tuple(records)


def resolve_hard_negative_data_dir(start: str | Path | None = None) -> Path:
    """Locate ``data/ir_learning/pairs/negative`` from a package or cwd root."""

    if start is not None:
        candidate = Path(start)
        if candidate.is_dir():
            return candidate
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "ir_learning" / "pairs" / "negative"
        if candidate.is_dir():
            return candidate
    return Path.cwd() / "ipfs_datasets_py" / "data" / "ir_learning" / "pairs" / "negative"


__all__ = [
    "DECOMPILER_HALLUCINATION",
    "DEFAULT_LEGAL_IR_FAMILY_DIFFICULTY",
    "DEFAULT_NEGATIVE_FAMILY_DIFFICULTY",
    "DEFAULT_NEGATIVE_PAIR_DATA_DIR",
    "HARD_NEGATIVE_FAMILIES",
    "INVERTED_MODALITY",
    "IR_HARD_NEGATIVE_INTERFACE",
    "IR_HARD_NEGATIVE_MINER_VERSION",
    "IR_HARD_NEGATIVE_SCHEMA_VERSION",
    "LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION",
    "LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION",
    "MINIMAL_MUTATION_CLASSES",
    "NEAR_MISS_CLAUSE",
    "SOURCE_COPY_SPAN",
    "STALE_AMENDMENT",
    "SWAPPED_ACTOR",
    "VERIFIED_COUNTEREXAMPLE",
    "WRONG_CITATION",
    "AdmittedHardNegative",
    "HardNegativeAdmissionError",
    "HardNegativeCandidate",
    "HardNegativeEffectReport",
    "HardNegativeIndex",
    "HardNegativeMinerError",
    "HardNegativeMiningResult",
    "HardNegativeRejection",
    "HardNegativeShardConflictError",
    "LegalIRHardNegativeConfig",
    "LegalIRHardNegativeCurriculum",
    "LegalIRHardNegativeCurriculumBuilder",
    "LegalIRHardNegativeCurriculumStage",
    "LegalIRHardNegativeExample",
    "NegativeEvidenceReceipt",
    "RejectedHardNegative",
    "RejectedHardNegativePair",
    "build_hard_negative_shards",
    "build_legal_ir_hard_negative_curriculum",
    "candidate_from_recipe_case",
    "candidate_from_validation_record",
    "canonical_hard_negative_recipe",
    "classify_hard_negative_candidate",
    "hard_negative_training_effect_gate",
    "load_hard_negative_shards",
    "load_positive_equivalence_index",
    "mine_canonical_hard_negatives",
    "mine_hard_negatives",
    "mutation_class_catalog",
    "prove_hard_negatives_reduce_false_positive_semantic_equivalence",
    "resolve_hard_negative_data_dir",
    "write_hard_negative_shards",
]
