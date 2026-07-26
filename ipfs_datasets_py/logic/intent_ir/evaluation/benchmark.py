"""Leakage-safe paired benchmarks for Intent IR formalization.

The benchmark contract deliberately separates evaluation truth from model
output.  Every arm is evaluated on the same immutable examples and split
manifest, and learned output remains candidate-only.  The evaluator never
trains a model, invokes a prover, or treats a confidence value as authority.

Three canonical arms are supported:

* the deterministic compiler;
* an Intent advisor initialized from scratch; and
* an Intent advisor using a transferred Legal encoder (with Intent heads).

Callers may evaluate pre-computed observations or provide offline runners.
Either path produces the same content-addressed, JSON-ready receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
import tracemalloc
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ...formalization.compiler import FormalizationArtifact
from ...ir_core.claims import thaw_json
from ..formalize.advisor import (
    IntentAdvisorRun,
    validate_intent_advisor_artifact,
)
from ..formalize.compiler import IntentFormalizationCompiler
from ..formalize.decompiler import IntentDecompiler
from ..formalize.obligations import (
    IntentProofDisposition,
    IntentProofExecution,
    IntentProofObligationError,
    IntentProofObligations,
)
from ..schema import IntentIRDocument, validate_intent_ir
from .splits import (
    HELD_OUT_DOMAIN_PARTITION,
    HELD_OUT_TIME_REVISION_PARTITION,
    TEST_PARTITION,
    IntentSplitLeakageError,
    IntentSplitManifest,
    validate_retrieval_partition_fence,
)


INTENT_FORMALIZATION_BENCHMARK_SCHEMA_VERSION: Final = (
    "intent-formalization-benchmark/v1"
)
INTENT_FORMALIZATION_BENCHMARK_EXAMPLE_SCHEMA_VERSION: Final = (
    "intent-formalization-benchmark-example/v1"
)
INTENT_FORMALIZATION_BENCHMARK_OBSERVATION_SCHEMA_VERSION: Final = (
    "intent-formalization-benchmark-observation/v1"
)
INTENT_FORMALIZATION_BENCHMARK_REPORT_SCHEMA_VERSION: Final = (
    "intent-formalization-benchmark-report/v1"
)

DEFAULT_EVALUATION_PARTITIONS: Final = (
    TEST_PARTITION,
    HELD_OUT_DOMAIN_PARTITION,
    HELD_OUT_TIME_REVISION_PARTITION,
)


class IntentBenchmarkError(ValueError):
    """Base class for malformed or incomplete benchmark inputs."""


class IntentBenchmarkIntegrityError(IntentBenchmarkError):
    """Raised when a paired comparison cannot be made without leakage."""


class IntentBenchmarkArm(str, Enum):
    """Canonical paired evaluation arms."""

    DETERMINISTIC_ONLY = "deterministic_only"
    DETERMINISTIC = "deterministic_only"
    INTENT_FROM_SCRATCH = "intent_from_scratch"
    FROM_SCRATCH = "intent_from_scratch"
    LEGAL_ENCODER_TRANSFER = "legal_encoder_transfer"
    LEGAL_ENCODER = "legal_encoder_transfer"


# Variant is common benchmark terminology; keep it as an exact type alias.
IntentBenchmarkVariant = IntentBenchmarkArm


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _bounded_text(value: Any, field_name: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise IntentBenchmarkError(f"{field_name} must be a string")
    result = value.strip()
    if (required and not result) or len(result) > 1024 or "\x00" in result:
        qualifier = "non-empty " if required else ""
        raise IntentBenchmarkError(
            f"{field_name} must be bounded {qualifier}text"
        )
    return result


def _strings(value: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise IntentBenchmarkError(f"{field_name} must be a sequence")
    result = tuple(
        _bounded_text(item, field_name) for item in value
    )
    if len(result) != len(set(result)):
        raise IntentBenchmarkError(f"{field_name} must not contain duplicates")
    return tuple(sorted(result))


def _finite_nonnegative(value: Any, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise IntentBenchmarkError(
            f"{field_name} must be a finite non-negative number"
        )
    return float(value)


def _rate(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 1.0


def _f1(expected: set[tuple[str, str]], predicted: set[tuple[str, str]]) -> float:
    true_positive = len(expected & predicted)
    false_positive = len(predicted - expected)
    false_negative = len(expected - predicted)
    denominator = 2 * true_positive + false_positive + false_negative
    return _rate(2 * true_positive, denominator)


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(
        0,
        min(
            len(ordered) - 1,
            math.ceil((percentile / 100.0) * len(ordered)) - 1,
        ),
    )
    return ordered[index]


def _formula_map(
    artifact: FormalizationArtifact | None,
) -> dict[str, Any]:
    return (
        {}
        if artifact is None
        else {item.formula_id: item for item in artifact.formulas}
    )


def _expression(formula: Any) -> Mapping[str, Any]:
    value = thaw_json(formula.expression)
    return value if isinstance(value, Mapping) else {}


def _first_node_id(formula: Any) -> str:
    metadata = formula.metadata.to_dict()
    values = metadata.get("intent_node_ids", ())
    if (
        isinstance(values, Sequence)
        and not isinstance(values, (str, bytes, bytearray))
        and values
    ):
        return str(values[0])
    for node_id in formula.input_node_ids:
        if node_id.startswith("intent-node:") and ":" in node_id:
            return node_id.rsplit(":", 1)[-1]
    return formula.formula_id


def _modality_labels(
    artifact: FormalizationArtifact | None,
) -> set[tuple[str, str]]:
    labels: set[tuple[str, str]] = set()
    if artifact is None:
        return labels
    for formula in artifact.formulas:
        expression = _expression(formula)
        if expression.get("kind") == "intention_deontic_formula":
            labels.add((_first_node_id(formula), str(expression.get("operator"))))
    return labels


def _control_labels(
    artifact: FormalizationArtifact | None,
) -> set[tuple[str, str]]:
    labels: set[tuple[str, str]] = set()
    if artifact is None:
        return labels
    for formula in artifact.formulas:
        expression = _expression(formula)
        if expression.get("kind") == "workflow_temporal_transition":
            labels.add((_first_node_id(formula), str(expression.get("operator"))))
    return labels


def _formula_review_state(formula: Any) -> str:
    expression = _expression(formula)
    for container in (
        expression.get("body"),
        expression.get("action"),
        expression,
    ):
        if isinstance(container, Mapping) and container.get("review_status"):
            return str(container["review_status"])
    return "unspecified"


def _formula_default_confidence(formula: Any) -> float | None:
    expression = _expression(formula)
    for container in (expression.get("body"), expression):
        if isinstance(container, Mapping):
            value = container.get("confidence")
            if (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(float(value))
                and 0.0 <= float(value) <= 1.0
            ):
                return float(value)
    return None


def _formula_correct(reference: Any, predicted: Any) -> bool:
    return (
        reference.view_id == predicted.view_id
        and thaw_json(reference.expression) == thaw_json(predicted.expression)
        and reference.source_ref_ids == predicted.source_ref_ids
        and reference.assumption_ids == predicted.assumption_ids
        and reference.opaque is predicted.opaque
    )


def _obligation_key(obligation: Any) -> str:
    """Return an artifact-independent semantic key for one obligation."""

    metadata = obligation.metadata
    kind = str(metadata.get("obligation_kind") or obligation.logic_family)
    semantic_id = str(
        metadata.get("intent_semantic_id")
        or metadata.get("intent_node_id")
        or ""
    )
    formula_id = str(metadata.get("formula_id") or "")
    if semantic_id or formula_id:
        return f"{kind}|{semantic_id}|{formula_id}"
    return f"id:{obligation.obligation_id}"


def _execution_keys(
    execution: IntentProofExecution | None,
    *,
    disposition: IntentProofDisposition | None = None,
    positive: bool = False,
) -> set[str]:
    if execution is None:
        return set()
    obligations = {
        item.obligation_id: item for item in execution.packet.obligations
    }
    return {
        _obligation_key(obligations[outcome.obligation_id])
        for outcome in execution.outcomes
        if (outcome.positive if positive else outcome.disposition is disposition)
    }


def _expected_obligation_keys(
    artifact: FormalizationArtifact,
    obligation_ids: Sequence[str],
) -> set[str]:
    if not obligation_ids:
        return set()
    try:
        packet = IntentProofObligations().generate(artifact)
    except IntentProofObligationError:
        return {f"id:{item}" for item in obligation_ids}
    by_id = {
        item.obligation_id: _obligation_key(item)
        for item in packet.obligations
    }
    return {by_id.get(item, f"id:{item}") for item in obligation_ids}


@dataclass(frozen=True, slots=True)
class IntentBenchmarkCost:
    """Reported resource cost for one example (never inferred from quality)."""

    input_tokens: int = 0
    output_tokens: int = 0
    compute_seconds: float = 0.0
    estimated_usd: float = 0.0

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise IntentBenchmarkError(
                    f"{name} must be a non-negative integer"
                )
        for name in ("compute_seconds", "estimated_usd"):
            object.__setattr__(
                self,
                name,
                _finite_nonnegative(getattr(self, name), name),
            )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "IntentBenchmarkCost") -> "IntentBenchmarkCost":
        if not isinstance(other, IntentBenchmarkCost):
            return NotImplemented
        return IntentBenchmarkCost(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            compute_seconds=self.compute_seconds + other.compute_seconds,
            estimated_usd=self.estimated_usd + other.estimated_usd,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "compute_seconds": self.compute_seconds,
            "estimated_usd": self.estimated_usd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class IntentBenchmarkExample:
    """One held-out document and its curated or deterministic formal reference."""

    document: IntentIRDocument
    reference_artifact: FormalizationArtifact | None = None
    provable_obligation_ids: tuple[str, ...] = ()
    unsupported_obligation_ids: tuple[str, ...] = ()
    expected_unsupported_formula_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = (
        INTENT_FORMALIZATION_BENCHMARK_EXAMPLE_SCHEMA_VERSION
    )

    def __post_init__(self) -> None:
        document = validate_intent_ir(self.document)
        object.__setattr__(self, "document", document)
        reference = self.reference_artifact
        if reference is not None:
            if not isinstance(reference, FormalizationArtifact):
                raise IntentBenchmarkError(
                    "reference_artifact must be a FormalizationArtifact"
                )
            reference.validate()
            if (
                reference.declaration_id != document.document_id
                or reference.declaration_digest
                != IntentFormalizationCompiler()
                .adapt_sample(document)
                .declaration_digest
            ):
                raise IntentBenchmarkError(
                    "reference artifact does not identify the example document"
                )
        for name in (
            "provable_obligation_ids",
            "unsupported_obligation_ids",
            "expected_unsupported_formula_ids",
        ):
            object.__setattr__(
                self, name, _strings(getattr(self, name), name)
            )
        if set(self.provable_obligation_ids) & set(
            self.unsupported_obligation_ids
        ):
            raise IntentBenchmarkError(
                "an obligation cannot be both provable and unsupported"
            )
        if not isinstance(self.metadata, Mapping) or any(
            not isinstance(key, str) for key in self.metadata
        ):
            raise IntentBenchmarkError("example metadata must be a mapping")
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(
                json.loads(_canonical_json(dict(self.metadata)))
            ),
        )
        if (
            self.schema_version
            != INTENT_FORMALIZATION_BENCHMARK_EXAMPLE_SCHEMA_VERSION
        ):
            raise IntentBenchmarkError("unsupported benchmark example schema")

    @property
    def sample_id(self) -> str:
        return self.document.document_id

    def with_reference(
        self, compiler: IntentFormalizationCompiler
    ) -> "IntentBenchmarkExample":
        if self.reference_artifact is not None:
            return self
        artifact = compiler.compile(self.document)
        unsupported_formulas = (
            self.expected_unsupported_formula_ids
            or tuple(
                item.formula_id for item in artifact.formulas if item.opaque
            )
        )
        try:
            packet = IntentProofObligations().generate(artifact)
        except IntentProofObligationError:
            packet_obligations: tuple[Any, ...] = ()
        else:
            packet_obligations = packet.obligations
        unsupported_obligations = self.unsupported_obligation_ids or tuple(
            item.obligation_id
            for item in packet_obligations
            if item.metadata.get("opaque_semantics") is True
        )
        provable = self.provable_obligation_ids or tuple(
            item.obligation_id
            for item in packet_obligations
            if item.obligation_id not in set(unsupported_obligations)
        )
        return replace(
            self,
            reference_artifact=artifact,
            provable_obligation_ids=provable,
            unsupported_obligation_ids=unsupported_obligations,
            expected_unsupported_formula_ids=unsupported_formulas,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_digest": (
                self.reference_artifact.declaration_digest
                if self.reference_artifact is not None
                else IntentFormalizationCompiler()
                .adapt_sample(self.document)
                .declaration_digest
            ),
            "expected_unsupported_formula_ids": list(
                self.expected_unsupported_formula_ids
            ),
            "metadata": dict(self.metadata),
            "provable_obligation_ids": list(self.provable_obligation_ids),
            "reference_artifact_digest": (
                self.reference_artifact.digest
                if self.reference_artifact is not None
                else ""
            ),
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "unsupported_obligation_ids": list(
                self.unsupported_obligation_ids
            ),
        }


@dataclass(frozen=True, slots=True)
class IntentBenchmarkObservation:
    """One arm's authority-free observation for one benchmark example."""

    sample_id: str
    arm: IntentBenchmarkArm
    artifact: FormalizationArtifact | None
    proof_execution: IntentProofExecution | None = None
    claimed_proof_ids: tuple[str, ...] = ()
    claimed_completion: bool = False
    confidences: Mapping[str, float] = field(default_factory=dict)
    retrieved_sample_ids: tuple[str, ...] = ()
    graph_snapshot_id: str = ""
    embedding_snapshot_id: str = ""
    authority: str = ""
    authority_violations: tuple[str, ...] = ()
    latency_ms: float = 0.0
    peak_memory_bytes: int = 0
    cost: IntentBenchmarkCost = field(default_factory=IntentBenchmarkCost)
    schema_version: str = (
        INTENT_FORMALIZATION_BENCHMARK_OBSERVATION_SCHEMA_VERSION
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "sample_id", _bounded_text(self.sample_id, "sample_id")
        )
        try:
            arm = (
                self.arm
                if isinstance(self.arm, IntentBenchmarkArm)
                else IntentBenchmarkArm(self.arm)
            )
        except (TypeError, ValueError) as exc:
            raise IntentBenchmarkError(
                f"unknown benchmark arm: {self.arm!r}"
            ) from exc
        object.__setattr__(self, "arm", arm)
        if self.artifact is not None:
            if not isinstance(self.artifact, FormalizationArtifact):
                raise IntentBenchmarkError(
                    "artifact must be a FormalizationArtifact or None"
                )
            self.artifact.validate()
            if self.artifact.declaration_id != self.sample_id:
                raise IntentBenchmarkError(
                    "observation artifact identifies another sample"
                )
        if self.proof_execution is not None and not isinstance(
            self.proof_execution, IntentProofExecution
        ):
            raise IntentBenchmarkError(
                "proof_execution must be an IntentProofExecution"
            )
        for name in (
            "claimed_proof_ids",
            "retrieved_sample_ids",
            "authority_violations",
        ):
            object.__setattr__(
                self, name, _strings(getattr(self, name), name)
            )
        if not isinstance(self.claimed_completion, bool):
            raise IntentBenchmarkError("claimed_completion must be a boolean")
        if not isinstance(self.confidences, Mapping):
            raise IntentBenchmarkError("confidences must be a mapping")
        confidences: dict[str, float] = {}
        for formula_id, raw_confidence in self.confidences.items():
            formula_id = _bounded_text(formula_id, "confidence formula ID")
            confidence = _finite_nonnegative(
                raw_confidence, f"confidence[{formula_id!r}]"
            )
            if confidence > 1.0:
                raise IntentBenchmarkError(
                    "confidence values must be between zero and one"
                )
            confidences[formula_id] = confidence
        object.__setattr__(
            self,
            "confidences",
            MappingProxyType(dict(sorted(confidences.items()))),
        )
        for name in ("graph_snapshot_id", "embedding_snapshot_id"):
            object.__setattr__(
                self,
                name,
                _bounded_text(
                    getattr(self, name), name, required=False
                ),
            )
        default_authority = (
            "deterministic_compiler_output"
            if arm is IntentBenchmarkArm.DETERMINISTIC_ONLY
            else "unverified_candidate_only"
        )
        object.__setattr__(
            self,
            "authority",
            _bounded_text(
                self.authority or default_authority, "authority"
            ),
        )
        object.__setattr__(
            self,
            "latency_ms",
            _finite_nonnegative(self.latency_ms, "latency_ms"),
        )
        if (
            isinstance(self.peak_memory_bytes, bool)
            or not isinstance(self.peak_memory_bytes, int)
            or self.peak_memory_bytes < 0
        ):
            raise IntentBenchmarkError(
                "peak_memory_bytes must be a non-negative integer"
            )
        if not isinstance(self.cost, IntentBenchmarkCost):
            if isinstance(self.cost, Mapping):
                object.__setattr__(self, "cost", IntentBenchmarkCost(**self.cost))
            else:
                raise IntentBenchmarkError(
                    "cost must be an IntentBenchmarkCost"
                )
        if (
            self.schema_version
            != INTENT_FORMALIZATION_BENCHMARK_OBSERVATION_SCHEMA_VERSION
        ):
            raise IntentBenchmarkError(
                "unsupported benchmark observation schema"
            )

    @property
    def authoritative_positive_ids(self) -> tuple[str, ...]:
        if self.proof_execution is None:
            return ()
        return tuple(
            item.obligation_id
            for item in self.proof_execution.outcomes
            if item.positive
        )

    @property
    def unsupported_proof_ids(self) -> tuple[str, ...]:
        if self.proof_execution is None:
            return ()
        return tuple(
            item.obligation_id
            for item in self.proof_execution.outcomes
            if item.disposition is IntentProofDisposition.UNSUPPORTED
        )

    @classmethod
    def from_advisor_run(
        cls,
        run: IntentAdvisorRun,
        *,
        arm: IntentBenchmarkArm | str,
        candidate_index: int = 0,
        **telemetry: Any,
    ) -> "IntentBenchmarkObservation":
        """Project an existing Intent advisor run into benchmark material.

        The deterministic artifact remains the baseline.  A learned arm uses
        one explicitly indexed, still-unverified candidate formula set; an
        abstaining advisor therefore scores the unchanged baseline.
        """

        if not isinstance(run, IntentAdvisorRun):
            raise IntentBenchmarkError("run must be an IntentAdvisorRun")
        normalized_arm = (
            arm if isinstance(arm, IntentBenchmarkArm) else IntentBenchmarkArm(arm)
        )
        artifact = run.deterministic_artifact
        authority = "deterministic_compiler_output"
        if normalized_arm is not IntentBenchmarkArm.DETERMINISTIC_ONLY:
            authority = "unverified_candidate_only"
            if run.candidates:
                if (
                    isinstance(candidate_index, bool)
                    or not isinstance(candidate_index, int)
                    or not 0 <= candidate_index < len(run.candidates)
                ):
                    raise IntentBenchmarkError(
                        "candidate_index is outside the advisor candidates"
                    )
                artifact = replace(
                    artifact,
                    formulas=run.candidates[candidate_index].formulas,
                )
        return cls(
            sample_id=artifact.declaration_id,
            arm=normalized_arm,
            artifact=artifact,
            authority=authority,
            **telemetry,
        )


# Prediction is a more natural name when observations come from a model.
IntentBenchmarkPrediction = IntentBenchmarkObservation


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    count: int = 0
    brier_score: float = 0.0
    expected_calibration_error: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "brier_score": self.brier_score,
            "count": self.count,
            "expected_calibration_error": self.expected_calibration_error,
        }


def _calibration(
    pairs: Sequence[tuple[float, bool]], *, bin_count: int = 10
) -> CalibrationMetrics:
    if not pairs:
        return CalibrationMetrics()
    brier = _mean(
        [(confidence - float(correct)) ** 2 for confidence, correct in pairs]
    )
    bins: list[list[tuple[float, bool]]] = [
        [] for _ in range(bin_count)
    ]
    for confidence, correct in pairs:
        index = min(bin_count - 1, int(confidence * bin_count))
        bins[index].append((confidence, correct))
    ece = sum(
        (len(items) / len(pairs))
        * abs(
            _mean([confidence for confidence, _ in items])
            - _mean([float(correct) for _, correct in items])
        )
        for items in bins
        if items
    )
    return CalibrationMetrics(
        count=len(pairs),
        brier_score=brier,
        expected_calibration_error=ece,
    )


@dataclass(frozen=True, slots=True)
class IntentBenchmarkMetrics:
    """Complete quality, safety, and resource metrics for one arm."""

    example_count: int
    grounding_accuracy: float
    schema_validity: float
    type_validity: float
    view_accuracy: float
    modality_f1: float
    control_f1: float
    proof_obligation_closure: float
    unsupported_recall: float
    semantic_mutation_rate: float
    round_trip_accuracy: float
    calibration: CalibrationMetrics
    calibration_by_review_state: Mapping[str, CalibrationMetrics]
    false_proof_count: int
    false_completion_count: int
    leakage_count: int
    authority_violation_count: int
    mean_latency_ms: float
    p95_latency_ms: float
    peak_memory_bytes: int
    cost: IntentBenchmarkCost

    @property
    def grounding(self) -> float:
        return self.grounding_accuracy

    @property
    def schema_type_accuracy(self) -> float:
        return min(self.schema_validity, self.type_validity)

    @property
    def round_trip(self) -> float:
        return self.round_trip_accuracy

    @property
    def promotion_safe(self) -> bool:
        return (
            self.leakage_count == 0
            and self.authority_violation_count == 0
            and self.false_proof_count == 0
            and self.false_completion_count == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_violation_count": self.authority_violation_count,
            "calibration": self.calibration.to_dict(),
            "calibration_by_review_state": {
                key: value.to_dict()
                for key, value in self.calibration_by_review_state.items()
            },
            "control_f1": self.control_f1,
            "cost": self.cost.to_dict(),
            "example_count": self.example_count,
            "false_completion_count": self.false_completion_count,
            "false_proof_count": self.false_proof_count,
            "grounding_accuracy": self.grounding_accuracy,
            "leakage_count": self.leakage_count,
            "mean_latency_ms": self.mean_latency_ms,
            "modality_f1": self.modality_f1,
            "p95_latency_ms": self.p95_latency_ms,
            "peak_memory_bytes": self.peak_memory_bytes,
            "promotion_safe": self.promotion_safe,
            "proof_obligation_closure": self.proof_obligation_closure,
            "round_trip_accuracy": self.round_trip_accuracy,
            "round_trip": self.round_trip_accuracy,
            "schema_validity": self.schema_validity,
            "schema_type_accuracy": self.schema_type_accuracy,
            "semantic_mutation_rate": self.semantic_mutation_rate,
            "type_validity": self.type_validity,
            "unsupported_recall": self.unsupported_recall,
            "view_accuracy": self.view_accuracy,
        }


@dataclass(frozen=True, slots=True)
class IntentPairedDelta:
    """Candidate-minus-deterministic deltas over the exact same examples."""

    arm: IntentBenchmarkArm
    grounding_accuracy: float
    schema_validity: float
    type_validity: float
    view_accuracy: float
    modality_f1: float
    control_f1: float
    proof_obligation_closure: float
    unsupported_recall: float
    semantic_mutation_rate: float
    round_trip_accuracy: float
    calibration_error: float
    false_proof_count: int
    authority_violation_count: int
    mean_latency_ms: float
    peak_memory_bytes: int
    estimated_usd: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm.value,
            "authority_violation_count": self.authority_violation_count,
            "calibration_error": self.calibration_error,
            "control_f1": self.control_f1,
            "estimated_usd": self.estimated_usd,
            "false_proof_count": self.false_proof_count,
            "grounding_accuracy": self.grounding_accuracy,
            "mean_latency_ms": self.mean_latency_ms,
            "modality_f1": self.modality_f1,
            "peak_memory_bytes": self.peak_memory_bytes,
            "proof_obligation_closure": self.proof_obligation_closure,
            "round_trip_accuracy": self.round_trip_accuracy,
            "schema_validity": self.schema_validity,
            "semantic_mutation_rate": self.semantic_mutation_rate,
            "type_validity": self.type_validity,
            "unsupported_recall": self.unsupported_recall,
            "view_accuracy": self.view_accuracy,
        }


@dataclass(frozen=True, slots=True)
class IntentBenchmarkReport:
    """Content-addressed paired held-out-source benchmark receipt."""

    split_manifest_digest: str
    evaluation_partitions: tuple[str, ...]
    example_ids: tuple[str, ...]
    metrics_by_arm: Mapping[IntentBenchmarkArm, IntentBenchmarkMetrics]
    paired_deltas: Mapping[IntentBenchmarkArm, IntentPairedDelta]
    leakage_violations: tuple[Mapping[str, Any], ...] = ()
    authority_violations: tuple[Mapping[str, str], ...] = ()
    schema_version: str = (
        INTENT_FORMALIZATION_BENCHMARK_REPORT_SCHEMA_VERSION
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "metrics_by_arm",
            MappingProxyType(
                dict(
                    sorted(
                        self.metrics_by_arm.items(),
                        key=lambda item: item[0].value,
                    )
                )
            ),
        )
        object.__setattr__(
            self,
            "paired_deltas",
            MappingProxyType(
                dict(
                    sorted(
                        self.paired_deltas.items(),
                        key=lambda item: item[0].value,
                    )
                )
            ),
        )
        if (
            self.schema_version
            != INTENT_FORMALIZATION_BENCHMARK_REPORT_SCHEMA_VERSION
        ):
            raise IntentBenchmarkError("unsupported benchmark report schema")

    @property
    def leakage_count(self) -> int:
        return len(self.leakage_violations)

    @property
    def authority_violation_count(self) -> int:
        return len(self.authority_violations)

    @property
    def promotion_eligible(self) -> bool:
        return (
            set(self.metrics_by_arm) == set(IntentBenchmarkArm)
            and IntentBenchmarkArm.DETERMINISTIC_ONLY
            not in self.paired_deltas
            and set(self.paired_deltas)
            == set(IntentBenchmarkArm)
            - {IntentBenchmarkArm.DETERMINISTIC_ONLY}
            and self.leakage_count == 0
            and self.authority_violation_count == 0
            and all(item.promotion_safe for item in self.metrics_by_arm.values())
        )

    @property
    def passed(self) -> bool:
        return self.promotion_eligible

    @property
    def complete_arm_matrix(self) -> bool:
        return set(self.metrics_by_arm) == set(IntentBenchmarkArm)

    def require_safe(self) -> "IntentBenchmarkReport":
        """Fail closed unless leakage, authority, and false-proof gates pass."""

        if not self.promotion_eligible:
            raise IntentBenchmarkIntegrityError(
                "benchmark receipt is not promotion-safe: "
                f"leakage={self.leakage_count}, "
                f"authority_violations={self.authority_violation_count}, "
                "false proofs or false completions are present"
            )
        return self

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "authority_violation_count": self.authority_violation_count,
            "authority_violations": [dict(item) for item in self.authority_violations],
            "complete_arm_matrix": self.complete_arm_matrix,
            "evaluation_partitions": list(self.evaluation_partitions),
            "example_ids": list(self.example_ids),
            "leakage_count": self.leakage_count,
            "leakage_violations": [dict(item) for item in self.leakage_violations],
            "metrics_by_arm": {
                arm.value: metrics.to_dict()
                for arm, metrics in self.metrics_by_arm.items()
            },
            "paired_deltas": {
                arm.value: delta.to_dict()
                for arm, delta in self.paired_deltas.items()
            },
            "promotion_eligible": self.promotion_eligible,
            "schema_version": self.schema_version,
            "split_manifest_digest": self.split_manifest_digest,
        }
        if include_digest:
            result["report_digest"] = _digest(result)
        return result

    @property
    def digest(self) -> str:
        return self.to_dict()["report_digest"]

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


BenchmarkRunner = Callable[
    [IntentBenchmarkExample],
    IntentBenchmarkObservation
    | IntentAdvisorRun
    | FormalizationArtifact
    | None,
]


class IntentFormalizationBenchmark:
    """Evaluate canonical formalization arms on one leak-free held-out set."""

    version: Final = INTENT_FORMALIZATION_BENCHMARK_SCHEMA_VERSION

    def __init__(
        self,
        examples: Sequence[IntentBenchmarkExample | IntentIRDocument],
        split_manifest: IntentSplitManifest,
        *,
        arms: Sequence[IntentBenchmarkArm | str] = tuple(IntentBenchmarkArm),
        evaluation_partitions: Sequence[str] = DEFAULT_EVALUATION_PARTITIONS,
        compiler: IntentFormalizationCompiler | None = None,
    ) -> None:
        if isinstance(examples, (str, bytes, bytearray)) or not isinstance(
            examples, Sequence
        ):
            raise IntentBenchmarkError("examples must be a sequence")
        self.compiler = compiler or IntentFormalizationCompiler()
        normalized = tuple(
            (
                item
                if isinstance(item, IntentBenchmarkExample)
                else IntentBenchmarkExample(document=item)
            ).with_reference(self.compiler)
            for item in examples
        )
        sample_ids = tuple(item.sample_id for item in normalized)
        if not normalized or len(sample_ids) != len(set(sample_ids)):
            raise IntentBenchmarkError(
                "benchmark examples must be non-empty with unique sample IDs"
            )
        if not isinstance(split_manifest, IntentSplitManifest):
            raise IntentBenchmarkError(
                "split_manifest must be an IntentSplitManifest"
            )
        try:
            split_manifest.require_valid()
        except IntentSplitLeakageError as exc:
            raise IntentBenchmarkIntegrityError(str(exc)) from exc
        normalized_arms = tuple(
            item if isinstance(item, IntentBenchmarkArm) else IntentBenchmarkArm(item)
            for item in arms
        )
        if (
            not normalized_arms
            or len(normalized_arms) != len(set(normalized_arms))
            or IntentBenchmarkArm.DETERMINISTIC_ONLY not in normalized_arms
        ):
            raise IntentBenchmarkError(
                "arms must be unique and include deterministic_only"
            )
        partitions = _strings(
            tuple(evaluation_partitions), "evaluation_partitions"
        )
        unknown_samples = set(sample_ids) - set(split_manifest.assignments)
        if unknown_samples:
            raise IntentBenchmarkIntegrityError(
                "benchmark examples are absent from the split manifest: "
                + ", ".join(sorted(unknown_samples))
            )
        wrong_partition = {
            sample_id: split_manifest.partition_of(sample_id)
            for sample_id in sample_ids
            if split_manifest.partition_of(sample_id) not in set(partitions)
        }
        if wrong_partition:
            raise IntentBenchmarkIntegrityError(
                "benchmark examples must be held out: "
                + ", ".join(
                    f"{sample_id}={partition}"
                    for sample_id, partition in sorted(wrong_partition.items())
                )
            )
        self.examples = tuple(sorted(normalized, key=lambda item: item.sample_id))
        self.split_manifest = split_manifest
        self.arms = normalized_arms
        self.evaluation_partitions = partitions

    def run(
        self, runners: Mapping[IntentBenchmarkArm | str, BenchmarkRunner]
    ) -> IntentBenchmarkReport:
        """Execute each runner sequentially with bounded local telemetry."""

        normalized_runners = {
            (
                key
                if isinstance(key, IntentBenchmarkArm)
                else IntentBenchmarkArm(key)
            ): value
            for key, value in runners.items()
        }
        if set(normalized_runners) != set(self.arms):
            raise IntentBenchmarkError(
                "runners must exactly cover configured benchmark arms"
            )
        observations: list[IntentBenchmarkObservation] = []
        for arm in self.arms:
            runner = normalized_runners[arm]
            if not callable(runner):
                raise IntentBenchmarkError(f"runner for {arm.value} is not callable")
            for example in self.examples:
                tracing_was_active = tracemalloc.is_tracing()
                if tracing_was_active:
                    memory_before, _ = tracemalloc.get_traced_memory()
                    tracemalloc.reset_peak()
                else:
                    tracemalloc.start()
                    memory_before = 0
                started = time.perf_counter()
                try:
                    result = runner(example)
                finally:
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    _, measured_peak = tracemalloc.get_traced_memory()
                    measured_peak = max(0, measured_peak - memory_before)
                    if not tracing_was_active:
                        tracemalloc.stop()
                if isinstance(result, FormalizationArtifact) or result is None:
                    observation = IntentBenchmarkObservation(
                        sample_id=example.sample_id,
                        arm=arm,
                        artifact=result,
                    )
                elif isinstance(result, IntentAdvisorRun):
                    observation = IntentBenchmarkObservation.from_advisor_run(
                        result, arm=arm
                    )
                elif isinstance(result, IntentBenchmarkObservation):
                    observation = result
                else:
                    raise IntentBenchmarkError(
                        f"runner for {arm.value} returned an unsupported value"
                    )
                if observation.sample_id != example.sample_id or observation.arm is not arm:
                    raise IntentBenchmarkError(
                        "runner observation does not match its paired sample and arm"
                    )
                observations.append(
                    replace(
                        observation,
                        latency_ms=(
                            observation.latency_ms
                            if observation.latency_ms > 0.0
                            else elapsed_ms
                        ),
                        peak_memory_bytes=max(
                            observation.peak_memory_bytes, measured_peak
                        ),
                    )
                )
        return self.evaluate(observations)

    def evaluate(
        self, observations: Sequence[IntentBenchmarkObservation]
    ) -> IntentBenchmarkReport:
        """Score a complete rectangular arm-by-example observation matrix."""

        if isinstance(observations, (str, bytes, bytearray)) or not isinstance(
            observations, Sequence
        ):
            raise IntentBenchmarkError("observations must be a sequence")
        keyed: dict[tuple[IntentBenchmarkArm, str], IntentBenchmarkObservation] = {}
        for item in observations:
            if not isinstance(item, IntentBenchmarkObservation):
                raise IntentBenchmarkError(
                    "observations must contain IntentBenchmarkObservation values"
                )
            key = (item.arm, item.sample_id)
            if key in keyed:
                raise IntentBenchmarkError(
                    f"duplicate observation for {item.arm.value}/{item.sample_id}"
                )
            keyed[key] = item
        expected = {
            (arm, example.sample_id)
            for arm in self.arms
            for example in self.examples
        }
        missing = expected - set(keyed)
        extra = set(keyed) - expected
        if missing or extra:
            raise IntentBenchmarkError(
                "observations must form an exact paired matrix; "
                f"missing={len(missing)}, extra={len(extra)}"
            )

        leakage: list[Mapping[str, Any]] = []
        authority: list[Mapping[str, str]] = []
        metrics: dict[IntentBenchmarkArm, IntentBenchmarkMetrics] = {}
        examples_by_id = {item.sample_id: item for item in self.examples}
        for arm in self.arms:
            arm_observations = tuple(
                keyed[(arm, example.sample_id)] for example in self.examples
            )
            arm_leakage, arm_authority = self._integrity_findings(
                arm_observations
            )
            leakage.extend(arm_leakage)
            authority.extend(arm_authority)
            metrics[arm] = self._metrics(
                arm_observations,
                examples_by_id,
                leakage_count=len(arm_leakage),
                authority_violation_count=len(arm_authority),
            )

        baseline = metrics[IntentBenchmarkArm.DETERMINISTIC_ONLY]
        deltas = {
            arm: self._delta(arm, baseline, arm_metrics)
            for arm, arm_metrics in metrics.items()
            if arm is not IntentBenchmarkArm.DETERMINISTIC_ONLY
        }
        return IntentBenchmarkReport(
            split_manifest_digest=self.split_manifest.digest,
            evaluation_partitions=self.evaluation_partitions,
            example_ids=tuple(item.sample_id for item in self.examples),
            metrics_by_arm=metrics,
            paired_deltas=deltas,
            leakage_violations=tuple(leakage),
            authority_violations=tuple(authority),
        )

    def _integrity_findings(
        self, observations: Sequence[IntentBenchmarkObservation]
    ) -> tuple[list[Mapping[str, Any]], list[Mapping[str, str]]]:
        leakage: list[Mapping[str, Any]] = []
        authority: list[Mapping[str, str]] = []
        for observation in observations:
            if observation.retrieved_sample_ids:
                fence = validate_retrieval_partition_fence(
                    self.split_manifest,
                    observation.sample_id,
                    observation.retrieved_sample_ids,
                    graph_snapshot_id=observation.graph_snapshot_id,
                    embedding_snapshot_id=observation.embedding_snapshot_id,
                )
                leakage.extend(
                    {
                        "arm": observation.arm.value,
                        "candidate_partition": item.candidate_partition,
                        "candidate_sample_id": item.candidate_sample_id,
                        "query_sample_id": observation.sample_id,
                        "reason": item.reason,
                    }
                    for item in fence.violations
                )
            expected_authority = (
                "deterministic_compiler_output"
                if observation.arm is IntentBenchmarkArm.DETERMINISTIC_ONLY
                else "unverified_candidate_only"
            )
            reasons = list(observation.authority_violations)
            if observation.authority != expected_authority:
                reasons.append(
                    f"unexpected_authority:{observation.authority}"
                )
            if observation.artifact is not None:
                if (
                    observation.artifact.metadata.get(
                        "retrieved_premises_have_proof_authority"
                    )
                    is not False
                ):
                    reasons.append("retrieved_premise_authority")
                try:
                    validate_intent_advisor_artifact(observation.artifact)
                except ValueError as exc:
                    reasons.append(f"artifact_authority_boundary:{exc}")
            if observation.proof_execution is not None and (
                observation.artifact is None
                or observation.proof_execution.packet.artifact_digest
                != observation.artifact.digest
            ):
                reasons.append("proof_execution_artifact_mismatch")
            for proof_id in observation.claimed_proof_ids:
                if proof_id not in set(
                    observation.authoritative_positive_ids
                ):
                    reasons.append(
                        f"unbacked_proof_claim:{proof_id}"
                    )
            authority.extend(
                {
                    "arm": observation.arm.value,
                    "reason": reason,
                    "sample_id": observation.sample_id,
                }
                for reason in dict.fromkeys(reasons)
            )
        return leakage, authority

    def _metrics(
        self,
        observations: Sequence[IntentBenchmarkObservation],
        examples: Mapping[str, IntentBenchmarkExample],
        *,
        leakage_count: int,
        authority_violation_count: int,
    ) -> IntentBenchmarkMetrics:
        grounding_numerator = grounding_denominator = 0
        schema_valid = type_valid = 0
        expected_views: set[tuple[str, str, str]] = set()
        predicted_views: set[tuple[str, str, str]] = set()
        expected_modalities: set[tuple[str, str]] = set()
        predicted_modalities: set[tuple[str, str]] = set()
        expected_controls: set[tuple[str, str]] = set()
        predicted_controls: set[tuple[str, str]] = set()
        provable: set[tuple[str, str]] = set()
        closed: set[tuple[str, str]] = set()
        unsupported_expected: set[tuple[str, str]] = set()
        unsupported_predicted: set[tuple[str, str]] = set()
        mutation_count = round_trip_passes = 0
        calibration_pairs: list[tuple[float, bool]] = []
        pairs_by_review: dict[str, list[tuple[float, bool]]] = defaultdict(list)
        false_proofs = false_completions = 0
        latencies: list[float] = []
        peak_memory = 0
        total_cost = IntentBenchmarkCost()
        decompiler = IntentDecompiler()

        for observation in observations:
            example = examples[observation.sample_id]
            reference = example.reference_artifact
            assert reference is not None
            predicted = observation.artifact
            reference_formulas = _formula_map(reference)
            predicted_formulas = _formula_map(predicted)

            for formula_id, formula in reference_formulas.items():
                expected_views.add(
                    (observation.sample_id, formula_id, formula.view_id)
                )
                grounding_denominator += 1
                candidate = predicted_formulas.get(formula_id)
                if candidate is not None:
                    if (
                        candidate.source_ref_ids == formula.source_ref_ids
                        and candidate.span_ids == formula.span_ids
                    ):
                        grounding_numerator += 1
                    predicted_views.add(
                        (
                            observation.sample_id,
                            formula_id,
                            candidate.view_id,
                        )
                    )
                    confidence = observation.confidences.get(formula_id)
                    if confidence is None:
                        confidence = _formula_default_confidence(candidate)
                    if confidence is not None:
                        pair = (
                            confidence,
                            _formula_correct(formula, candidate),
                        )
                        calibration_pairs.append(pair)
                        pairs_by_review[
                            _formula_review_state(formula)
                        ].append(pair)
            for formula_id, formula in predicted_formulas.items():
                if formula_id not in reference_formulas:
                    predicted_views.add(
                        (
                            observation.sample_id,
                            formula_id,
                            formula.view_id,
                        )
                    )

            if predicted is not None:
                try:
                    predicted.validate()
                    schema_valid += 1
                except ValueError:
                    pass
                try:
                    validate_intent_advisor_artifact(predicted)
                    type_valid += 1
                except ValueError:
                    pass

            expected_modalities.update(
                (observation.sample_id + "|" + node_id, label)
                for node_id, label in _modality_labels(reference)
            )
            predicted_modalities.update(
                (observation.sample_id + "|" + node_id, label)
                for node_id, label in _modality_labels(predicted)
            )
            expected_controls.update(
                (observation.sample_id + "|" + node_id, label)
                for node_id, label in _control_labels(reference)
            )
            predicted_controls.update(
                (observation.sample_id + "|" + node_id, label)
                for node_id, label in _control_labels(predicted)
            )

            expected_proof_keys = _expected_obligation_keys(
                reference, example.provable_obligation_ids
            )
            positive_proof_keys = _execution_keys(
                observation.proof_execution, positive=True
            )
            unsupported_proof_keys = _execution_keys(
                observation.proof_execution,
                disposition=IntentProofDisposition.UNSUPPORTED,
            )
            expected_unsupported_proof_keys = _expected_obligation_keys(
                reference, example.unsupported_obligation_ids
            )
            provable.update(
                (observation.sample_id, item)
                for item in expected_proof_keys
            )
            closed.update(
                (observation.sample_id, item)
                for item in positive_proof_keys
                if item in expected_proof_keys
            )
            unsupported_expected.update(
                (observation.sample_id, item)
                for item in example.expected_unsupported_formula_ids
            )
            unsupported_expected.update(
                (observation.sample_id, item)
                for item in expected_unsupported_proof_keys
            )
            unsupported_predicted.update(
                (observation.sample_id, item.formula_id)
                for item in (predicted.formulas if predicted else ())
                if item.opaque
            )
            unsupported_predicted.update(
                (observation.sample_id, item)
                for item in unsupported_proof_keys
            )

            if predicted is not None:
                try:
                    round_trip = decompiler.compare(example.document, predicted)
                except ValueError:
                    mutation_count += 1
                else:
                    if round_trip.passed:
                        round_trip_passes += 1
                    else:
                        mutation_count += 1
            else:
                mutation_count += 1

            claimed = set(observation.claimed_proof_ids)
            false_proofs += len(
                claimed - set(observation.authoritative_positive_ids)
            )
            false_proofs += len(
                positive_proof_keys - expected_proof_keys
            )
            if observation.claimed_completion and (
                not expected_proof_keys.issubset(positive_proof_keys)
                or bool(example.unsupported_obligation_ids)
            ):
                false_completions += 1

            latencies.append(observation.latency_ms)
            peak_memory = max(peak_memory, observation.peak_memory_bytes)
            total_cost += observation.cost

        calibration_by_review = MappingProxyType(
            {
                key: _calibration(value)
                for key, value in sorted(pairs_by_review.items())
            }
        )
        return IntentBenchmarkMetrics(
            example_count=len(observations),
            grounding_accuracy=_rate(
                grounding_numerator, grounding_denominator
            ),
            schema_validity=_rate(schema_valid, len(observations)),
            type_validity=_rate(type_valid, len(observations)),
            view_accuracy=_f1(expected_views, predicted_views),
            modality_f1=_f1(expected_modalities, predicted_modalities),
            control_f1=_f1(expected_controls, predicted_controls),
            proof_obligation_closure=_rate(
                len(closed), len(provable)
            ),
            unsupported_recall=_rate(
                len(unsupported_expected & unsupported_predicted),
                len(unsupported_expected),
            ),
            semantic_mutation_rate=_rate(
                mutation_count, len(observations)
            ),
            round_trip_accuracy=_rate(
                round_trip_passes, len(observations)
            ),
            calibration=_calibration(calibration_pairs),
            calibration_by_review_state=calibration_by_review,
            false_proof_count=false_proofs,
            false_completion_count=false_completions,
            leakage_count=leakage_count,
            authority_violation_count=authority_violation_count,
            mean_latency_ms=_mean(latencies),
            p95_latency_ms=_percentile(latencies, 95.0),
            peak_memory_bytes=peak_memory,
            cost=total_cost,
        )

    @staticmethod
    def _delta(
        arm: IntentBenchmarkArm,
        baseline: IntentBenchmarkMetrics,
        candidate: IntentBenchmarkMetrics,
    ) -> IntentPairedDelta:
        return IntentPairedDelta(
            arm=arm,
            grounding_accuracy=(
                candidate.grounding_accuracy - baseline.grounding_accuracy
            ),
            schema_validity=(
                candidate.schema_validity - baseline.schema_validity
            ),
            type_validity=(
                candidate.type_validity - baseline.type_validity
            ),
            view_accuracy=candidate.view_accuracy - baseline.view_accuracy,
            modality_f1=candidate.modality_f1 - baseline.modality_f1,
            control_f1=candidate.control_f1 - baseline.control_f1,
            proof_obligation_closure=(
                candidate.proof_obligation_closure
                - baseline.proof_obligation_closure
            ),
            unsupported_recall=(
                candidate.unsupported_recall - baseline.unsupported_recall
            ),
            semantic_mutation_rate=(
                candidate.semantic_mutation_rate
                - baseline.semantic_mutation_rate
            ),
            round_trip_accuracy=(
                candidate.round_trip_accuracy - baseline.round_trip_accuracy
            ),
            calibration_error=(
                candidate.calibration.expected_calibration_error
                - baseline.calibration.expected_calibration_error
            ),
            false_proof_count=(
                candidate.false_proof_count - baseline.false_proof_count
            ),
            authority_violation_count=(
                candidate.authority_violation_count
                - baseline.authority_violation_count
            ),
            mean_latency_ms=(
                candidate.mean_latency_ms - baseline.mean_latency_ms
            ),
            peak_memory_bytes=(
                candidate.peak_memory_bytes - baseline.peak_memory_bytes
            ),
            estimated_usd=(
                candidate.cost.estimated_usd
                - baseline.cost.estimated_usd
            ),
        )

    # Familiar harness spelling.
    benchmark = run


def run_intent_formalization_benchmark(
    examples: Sequence[IntentBenchmarkExample | IntentIRDocument],
    split_manifest: IntentSplitManifest,
    runners: Mapping[IntentBenchmarkArm | str, BenchmarkRunner],
    *,
    arms: Sequence[IntentBenchmarkArm | str] = tuple(IntentBenchmarkArm),
    evaluation_partitions: Sequence[str] = DEFAULT_EVALUATION_PARTITIONS,
) -> IntentBenchmarkReport:
    """Convenience entry point for the canonical paired benchmark."""

    return IntentFormalizationBenchmark(
        examples,
        split_manifest,
        arms=arms,
        evaluation_partitions=evaluation_partitions,
    ).run(runners)


IntentFormalizationBenchmarkReceipt = IntentBenchmarkReport


__all__ = [
    "DEFAULT_EVALUATION_PARTITIONS",
    "INTENT_FORMALIZATION_BENCHMARK_EXAMPLE_SCHEMA_VERSION",
    "INTENT_FORMALIZATION_BENCHMARK_OBSERVATION_SCHEMA_VERSION",
    "INTENT_FORMALIZATION_BENCHMARK_REPORT_SCHEMA_VERSION",
    "INTENT_FORMALIZATION_BENCHMARK_SCHEMA_VERSION",
    "BenchmarkRunner",
    "CalibrationMetrics",
    "IntentBenchmarkArm",
    "IntentBenchmarkCost",
    "IntentBenchmarkError",
    "IntentBenchmarkExample",
    "IntentBenchmarkIntegrityError",
    "IntentBenchmarkMetrics",
    "IntentBenchmarkObservation",
    "IntentBenchmarkPrediction",
    "IntentBenchmarkReport",
    "IntentBenchmarkVariant",
    "IntentFormalizationBenchmark",
    "IntentFormalizationBenchmarkReceipt",
    "IntentPairedDelta",
    "run_intent_formalization_benchmark",
]
