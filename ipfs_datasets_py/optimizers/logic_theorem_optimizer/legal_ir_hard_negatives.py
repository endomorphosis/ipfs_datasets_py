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
from typing import Any, Final, Optional

from .legal_ir_family_evaluator import (
    LEGAL_IR_EVALUATION_FAMILIES,
    canonical_legal_ir_evaluation_family,
)
from .legal_ir_semantic_metrics import (
    OBLIGATION_EQUIVALENCE,
    SEMANTIC_EQUIVALENCE_METRICS,
    STRUCTURAL_EQUIVALENCE,
    evaluate_legal_ir_semantic_equivalence,
)


LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION: Final = "legal-ir-hard-negative-curriculum-v1"
LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION: Final = (
    "legal-ir-hard-negative-effect-v1"
)

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
            canonical_legal_ir_evaluation_family(family)
            for family in self.legal_ir_families
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
        return bool(self.examples) and not self.missing_negative_families and all(
            example.is_training_label for example in self.examples
        )

    def by_family(self, negative_family: str) -> tuple[LegalIRHardNegativeExample, ...]:
        return tuple(
            example
            for example in self.examples
            if example.negative_family == negative_family
        )

    def to_dict(self, *, include_examples: bool = True) -> dict[str, Any]:
        payload = {
            "accepted_count": self.accepted_count,
            "covered_negative_families": list(self.covered_negative_families),
            "curriculum_id": self.curriculum_id,
            "missing_negative_families": list(self.missing_negative_families),
            "ready_for_training": self.ready_for_training,
            "rejected_candidates": [
                candidate.to_dict() for candidate in self.rejected_candidates
            ],
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
                rejected.append(
                    _rejected(item, "unverified_counterexample_not_training_label")
                )
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
        example_id = source.get("candidate_id") or source.get("example_id") or (
            "lir-hard-negative-" + _stable_hash(
                {
                    "family": negative_family,
                    "minimal": minimal,
                    "reference": reference,
                    "verification": verification,
                }
            )[:24]
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
            family = "decompiler" if negative_family == DECOMPILER_HALLUCINATION else semantic_family
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
                    source_text_sha256=str(
                        source.get("source_text_sha256") or _text_hash(text)
                    )
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
                source.get("example_id")
                or "lir-hard-negative-" + _stable_hash(source)[:24]
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

    positive_guard = (
        worst_degradation <= cfg.trusted_positive_obligation_tolerance
        and (
            verified_positive_count > 0
            or not cfg.require_trusted_positive_obligation_evidence
        )
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
        str(item)
        for item in _sequence(verification.get("grammar_rejections"))
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
    return _mutate_rule_field(copy.deepcopy(reference), ("modality", "operator"), _flip_modality(_modality(text)))


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
        result.scores[metric]
        for metric in SEMANTIC_EQUIVALENCE_METRICS
        if metric in result.scores
    ]
    return min(values) if values else default


__all__ = [
    "DECOMPILER_HALLUCINATION",
    "DEFAULT_LEGAL_IR_FAMILY_DIFFICULTY",
    "DEFAULT_NEGATIVE_FAMILY_DIFFICULTY",
    "HARD_NEGATIVE_FAMILIES",
    "INVERTED_MODALITY",
    "LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION",
    "LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION",
    "NEAR_MISS_CLAUSE",
    "SOURCE_COPY_SPAN",
    "STALE_AMENDMENT",
    "SWAPPED_ACTOR",
    "VERIFIED_COUNTEREXAMPLE",
    "WRONG_CITATION",
    "HardNegativeEffectReport",
    "LegalIRHardNegativeConfig",
    "LegalIRHardNegativeCurriculum",
    "LegalIRHardNegativeCurriculumBuilder",
    "LegalIRHardNegativeCurriculumStage",
    "LegalIRHardNegativeExample",
    "RejectedHardNegative",
    "build_legal_ir_hard_negative_curriculum",
    "hard_negative_training_effect_gate",
    "prove_hard_negatives_reduce_false_positive_semantic_equivalence",
]
