"""Evidence-complete compiler/decompiler evaluation and promotion gates.

``IREvaluationSuite@1`` consumes frozen, per-case evaluator observations.  It
does not compile inputs, call models, or expose source text.  Its only job is
to make N1--N8 evidence auditable: distinct compiler/decompiler reports,
denominators, strata, paired bootstrap uncertainty, tokenizer comparability,
and fail-closed noninferiority gates.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Final, Optional


IR_EVALUATION_SUITE_INTERFACE: Final = "IREvaluationSuite@1"
IR_EVALUATION_SUITE_SCHEMA_VERSION: Final = (
    "ipfs-datasets.ir-learning.evaluations.ir-evaluation-suite.v1"
)

COMPILER_SURFACE: Final = "compiler"
DECOMPILER_SURFACE: Final = "decompiler"
IR_EVALUATION_SURFACES: Final[tuple[str, ...]] = (
    COMPILER_SURFACE,
    DECOMPILER_SURFACE,
)

METRIC_STATUS_MEASURED: Final = "measured"
METRIC_STATUS_PARTIAL: Final = "partial"
METRIC_STATUS_UNSUPPORTED: Final = "unsupported"
METRIC_STATUS_UNAVAILABLE: Final = "unavailable"

SIGNIFICANCE_CORRECTION_HOLM: Final = "holm"
SIGNIFICANCE_CORRECTION_BONFERRONI: Final = "bonferroni"
SIGNIFICANCE_CORRECTION_NONE: Final = "none"
VALID_SIGNIFICANCE_CORRECTIONS: Final = frozenset(
    {
        SIGNIFICANCE_CORRECTION_HOLM,
        SIGNIFICANCE_CORRECTION_BONFERRONI,
        SIGNIFICANCE_CORRECTION_NONE,
    }
)

N1: Final = "N1"
N2: Final = "N2"
N3: Final = "N3"
N4: Final = "N4"
N5: Final = "N5"
N6: Final = "N6"
N7: Final = "N7"
N8: Final = "N8"
N1_TOKEN: Final = N1
N2_LATENT: Final = N2
N3_RETRIEVAL: Final = N3
N4_STRUCTURAL: Final = N4
N5_SEMANTIC: Final = N5
N6_PROOF: Final = N6
N7_READABILITY: Final = N7
N8_CALIBRATION_OOD: Final = N8
N_METRIC_IDS: Final[tuple[str, ...]] = (N1, N2, N3, N4, N5, N6, N7, N8)

N1_TOKEN_CROSS_ENTROPY: Final = "token_cross_entropy"
N2_LATENT_SEPARATION: Final = "latent_separation"
N3_RETRIEVAL_RECALL: Final = "retrieval_recall"
N4_STRUCTURAL_EQUIVALENCE: Final = "structural_equivalence"
N5_SEMANTIC_EQUIVALENCE: Final = "semantic_equivalence"
N6_PROOF_REPLAY_RATE: Final = "proof_replay_rate"
N7_READABILITY_SCORE: Final = "readability_score"
N8_CALIBRATION_ERROR: Final = "calibration_error"
N8_OOD_ACCEPTANCE: Final = "ood_acceptance"
IR_EVALUATION_MEASURE_IDS: Final[tuple[str, ...]] = (
    N1_TOKEN_CROSS_ENTROPY,
    N2_LATENT_SEPARATION,
    N3_RETRIEVAL_RECALL,
    N4_STRUCTURAL_EQUIVALENCE,
    N5_SEMANTIC_EQUIVALENCE,
    N6_PROOF_REPLAY_RATE,
    N7_READABILITY_SCORE,
    N8_CALIBRATION_ERROR,
    N8_OOD_ACCEPTANCE,
)

DEFAULT_BOOTSTRAP_SAMPLES: Final = 10_000
MAX_BOOTSTRAP_SAMPLES: Final = 1_000_000
DEFAULT_CONFIDENCE_LEVEL: Final = 0.95
DEFAULT_ALPHA: Final = 0.05
DEFAULT_MINIMUM_PAIRED_CASES: Final = 5


class IREvaluationSuiteError(ValueError):
    """Raised when supplied evidence cannot support a safe report."""


def _identifier(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text or any(char in text for char in "\r\n\0"):
        raise IREvaluationSuiteError(f"{field} must be a non-blank identifier")
    return text


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IREvaluationSuiteError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise IREvaluationSuiteError(f"{field} must be a finite number")
    return result


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise IREvaluationSuiteError(f"{field} must be a non-negative integer")
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    return value


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(float(value), 12)


def _seed(seed: int, *parts: str) -> int:
    encoded = json.dumps([seed, *parts], sort_keys=True, separators=(",", ":")).encode()
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big")


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise IREvaluationSuiteError("cannot take a quantile of empty evidence")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _surface(value: Any) -> str:
    aliases = {
        "compiler": COMPILER_SURFACE,
        "compile": COMPILER_SURFACE,
        "encoder": COMPILER_SURFACE,
        "decompiler": DECOMPILER_SURFACE,
        "decompile": DECOMPILER_SURFACE,
        "decoder": DECOMPILER_SURFACE,
    }
    result = aliases.get(str(value or "").strip().lower().replace("-", "_"))
    if result is None:
        raise IREvaluationSuiteError(f"unknown evaluation surface {value!r}")
    return result


def _strata(value: Any) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({"cohort": "all"})
    if not isinstance(value, Mapping):
        raise IREvaluationSuiteError("strata must be an object")
    result = {
        _identifier(key, "strata key"): _identifier(item, "strata value")
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }
    return MappingProxyType(dict(sorted(result.items())) or {"cohort": "all"})


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    metric_id: str
    n_metric: str
    description: str
    higher_is_better: bool
    unit: str
    requires_tokenizer_comparability: bool = False
    default_noninferiority_margin: float = 0.0
    gate_by_default: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_id", _identifier(self.metric_id, "metric_id"))
        if self.n_metric not in N_METRIC_IDS:
            raise IREvaluationSuiteError(f"unknown N metric {self.n_metric!r}")
        object.__setattr__(self, "description", _identifier(self.description, "description"))
        object.__setattr__(self, "unit", _identifier(self.unit, "unit"))
        margin = _finite(self.default_noninferiority_margin, "default_noninferiority_margin")
        if margin < 0:
            raise IREvaluationSuiteError("default_noninferiority_margin must be non-negative")
        object.__setattr__(self, "default_noninferiority_margin", margin)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_noninferiority_margin": _round(self.default_noninferiority_margin),
            "description": self.description,
            "gate_by_default": self.gate_by_default,
            "higher_is_better": self.higher_is_better,
            "metric_id": self.metric_id,
            "n_metric": self.n_metric,
            "requires_tokenizer_comparability": self.requires_tokenizer_comparability,
            "unit": self.unit,
        }


IR_EVALUATION_METRIC_CATALOG: Final[Mapping[str, MetricDefinition]] = MappingProxyType(
    {
        N1_TOKEN_CROSS_ENTROPY: MetricDefinition(
            N1_TOKEN_CROSS_ENTROPY,
            N1,
            "Canonical-tokenizer cross entropy; lower is better.",
            False,
            "nats_per_canonical_token",
            True,
            0.02,
        ),
        N2_LATENT_SEPARATION: MetricDefinition(
            N2_LATENT_SEPARATION,
            N2,
            "Latent separation/utility with retained false-neighbour evidence.",
            True,
            "score",
            False,
            0.02,
        ),
        N3_RETRIEVAL_RECALL: MetricDefinition(
            N3_RETRIEVAL_RECALL,
            N3,
            "Retrieval recall on frozen retrieval targets.",
            True,
            "rate",
            False,
            0.01,
        ),
        N4_STRUCTURAL_EQUIVALENCE: MetricDefinition(
            N4_STRUCTURAL_EQUIVALENCE,
            N4,
            "Structural LegalIR equivalence against frozen reference evidence.",
            True,
            "rate",
        ),
        N5_SEMANTIC_EQUIVALENCE: MetricDefinition(
            N5_SEMANTIC_EQUIVALENCE,
            N5,
            "Semantic LegalIR equivalence; readability cannot override it.",
            True,
            "rate",
        ),
        N6_PROOF_REPLAY_RATE: MetricDefinition(
            N6_PROOF_REPLAY_RATE,
            N6,
            "Independent proof-receipt replay rate.",
            True,
            "rate",
        ),
        N7_READABILITY_SCORE: MetricDefinition(
            N7_READABILITY_SCORE,
            N7,
            "Readability is informational and cannot clear semantic/proof failure.",
            True,
            "score",
            False,
            0.05,
            False,
        ),
        N8_CALIBRATION_ERROR: MetricDefinition(
            N8_CALIBRATION_ERROR,
            N8,
            "Expected calibration error on declared calibration strata.",
            False,
            "error",
            False,
            0.01,
        ),
        N8_OOD_ACCEPTANCE: MetricDefinition(
            N8_OOD_ACCEPTANCE,
            N8,
            "Safe OOD acceptance/abstention outcome on frozen OOD strata.",
            True,
            "rate",
        ),
    }
)

N_METRIC_CATALOG: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        N1: (N1_TOKEN_CROSS_ENTROPY,),
        N2: (N2_LATENT_SEPARATION,),
        N3: (N3_RETRIEVAL_RECALL,),
        N4: (N4_STRUCTURAL_EQUIVALENCE,),
        N5: (N5_SEMANTIC_EQUIVALENCE,),
        N6: (N6_PROOF_REPLAY_RATE,),
        N7: (N7_READABILITY_SCORE,),
        N8: (N8_CALIBRATION_ERROR, N8_OOD_ACCEPTANCE),
    }
)

_METRIC_ALIASES: Final = {
    "n1": N1_TOKEN_CROSS_ENTROPY,
    "n1_token": N1_TOKEN_CROSS_ENTROPY,
    "token": N1_TOKEN_CROSS_ENTROPY,
    "cross_entropy": N1_TOKEN_CROSS_ENTROPY,
    "n2": N2_LATENT_SEPARATION,
    "n2_latent": N2_LATENT_SEPARATION,
    "latent": N2_LATENT_SEPARATION,
    "n3": N3_RETRIEVAL_RECALL,
    "n3_retrieval": N3_RETRIEVAL_RECALL,
    "retrieval": N3_RETRIEVAL_RECALL,
    "n4": N4_STRUCTURAL_EQUIVALENCE,
    "n4_structural": N4_STRUCTURAL_EQUIVALENCE,
    "structural": N4_STRUCTURAL_EQUIVALENCE,
    "n5": N5_SEMANTIC_EQUIVALENCE,
    "n5_semantic": N5_SEMANTIC_EQUIVALENCE,
    "semantic": N5_SEMANTIC_EQUIVALENCE,
    "n6": N6_PROOF_REPLAY_RATE,
    "n6_proof": N6_PROOF_REPLAY_RATE,
    "proof": N6_PROOF_REPLAY_RATE,
    "n7": N7_READABILITY_SCORE,
    "n7_readability": N7_READABILITY_SCORE,
    "readability": N7_READABILITY_SCORE,
    "n8": N8_CALIBRATION_ERROR,
    "calibration": N8_CALIBRATION_ERROR,
    "n8_ood": N8_OOD_ACCEPTANCE,
    "ood": N8_OOD_ACCEPTANCE,
    **{metric_id: metric_id for metric_id in IR_EVALUATION_MEASURE_IDS},
}


def canonical_metric_id(metric_id: Any) -> str:
    """Normalize a metric alias to one canonical, separately reported measure."""

    normalized = str(metric_id or "").strip().lower().replace("-", "_").replace(" ", "_")
    result = _METRIC_ALIASES.get(normalized, normalized)
    if result not in IR_EVALUATION_METRIC_CATALOG:
        raise IREvaluationSuiteError(f"unsupported IREvaluationSuite metric {metric_id!r}")
    return result


DEFAULT_REQUIRED_METRIC_IDS: Final[tuple[str, ...]] = tuple(
    metric_id
    for metric_id, definition in IR_EVALUATION_METRIC_CATALOG.items()
    if definition.gate_by_default
)


@dataclass(frozen=True, slots=True)
class TokenizerIdentity:
    """All dimensions which must match before a CE comparison is valid."""

    tokenizer_id: str
    version: str
    vocabulary_digest: str
    normalization_digest: str
    special_tokens_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("tokenizer_id", "version", "vocabulary_digest", "normalization_digest"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "special_tokens_digest", str(self.special_tokens_digest or "").strip())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TokenizerIdentity":
        return cls(
            tokenizer_id=value.get("tokenizer_id", value.get("id", value.get("name", ""))),
            version=value.get("version", value.get("tokenizer_version", "")),
            vocabulary_digest=value.get(
                "vocabulary_digest", value.get("vocab_digest", value.get("vocabulary_hash", ""))
            ),
            normalization_digest=value.get(
                "normalization_digest",
                value.get("normalizer_digest", value.get("normalization_hash", "")),
            ),
            special_tokens_digest=value.get(
                "special_tokens_digest", value.get("special_token_digest", "")
            ),
        )

    def mismatches(self, other: "TokenizerIdentity") -> tuple[str, ...]:
        return tuple(
            name
            for name in (
                "tokenizer_id",
                "version",
                "vocabulary_digest",
                "normalization_digest",
                "special_tokens_digest",
            )
            if getattr(self, name) != getattr(other, name)
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "normalization_digest": self.normalization_digest,
            "special_tokens_digest": self.special_tokens_digest,
            "tokenizer_id": self.tokenizer_id,
            "version": self.version,
            "vocabulary_digest": self.vocabulary_digest,
        }


@dataclass(frozen=True, slots=True)
class FalseNeighborEvidence:
    """Retained latent false-neighbour evidence without source content."""

    sample_id: str
    neighbor_id: str
    reason: str
    similarity: Optional[float] = None
    strata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _identifier(self.sample_id, "sample_id"))
        object.__setattr__(self, "neighbor_id", _identifier(self.neighbor_id, "neighbor_id"))
        object.__setattr__(self, "reason", _identifier(self.reason, "reason"))
        if self.similarity is not None:
            object.__setattr__(self, "similarity", _finite(self.similarity, "similarity"))
        object.__setattr__(self, "strata", _strata(self.strata))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FalseNeighborEvidence":
        return cls(
            sample_id=value.get("sample_id", value.get("anchor_id", "")),
            neighbor_id=value.get("neighbor_id", value.get("false_neighbor_id", "")),
            reason=value.get("reason", value.get("kind", "semantic_mismatch")),
            similarity=value.get("similarity"),
            strata=value.get("strata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "neighbor_id": self.neighbor_id,
            "reason": self.reason,
            "sample_id": self.sample_id,
            "similarity": _round(self.similarity),
            "strata": _plain(self.strata),
        }


def _false_neighbors(value: Any) -> tuple[FalseNeighborEvidence, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        value = (value,)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise IREvaluationSuiteError("false_neighbors must be a sequence")
    return tuple(
        item
        if isinstance(item, FalseNeighborEvidence)
        else FalseNeighborEvidence.from_mapping(item)
        for item in value
    )


@dataclass(frozen=True, slots=True)
class EvaluationObservation:
    """One precomputed metric value (or explicit unsupported result) for a case."""

    candidate_id: str
    sample_id: str
    surface: str
    metric_id: str
    value: Optional[float] = None
    denominator: int = 1
    status: str = METRIC_STATUS_MEASURED
    reason: str = ""
    strata: Mapping[str, str] = field(default_factory=dict)
    tokenizer_identity: Optional[TokenizerIdentity] = None
    false_neighbors: tuple[FalseNeighborEvidence, ...] = ()
    false_neighbor_analysis_performed: Optional[bool] = None
    proof_receipt_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _identifier(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "sample_id", _identifier(self.sample_id, "sample_id"))
        object.__setattr__(self, "surface", _surface(self.surface))
        object.__setattr__(self, "metric_id", canonical_metric_id(self.metric_id))
        status = str(self.status or "").strip().lower()
        if status not in {METRIC_STATUS_MEASURED, METRIC_STATUS_UNSUPPORTED}:
            raise IREvaluationSuiteError("observation status must be measured or unsupported")
        denominator = _nonnegative_int(self.denominator, "denominator")
        reason = str(self.reason or "").strip()
        if status == METRIC_STATUS_MEASURED:
            if denominator < 1 or self.value is None or reason:
                raise IREvaluationSuiteError("measured observation requires only value and denominator")
            object.__setattr__(self, "value", _finite(self.value, "value"))
        elif self.value is not None or not reason:
            raise IREvaluationSuiteError("unsupported observation requires an explicit reason")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "denominator", denominator)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "strata", _strata(self.strata))
        identity = self.tokenizer_identity
        if isinstance(identity, Mapping):
            identity = TokenizerIdentity.from_mapping(identity)
        if identity is not None and not isinstance(identity, TokenizerIdentity):
            raise IREvaluationSuiteError("tokenizer_identity must be a TokenizerIdentity")
        object.__setattr__(self, "tokenizer_identity", identity)
        neighbors = _false_neighbors(self.false_neighbors)
        object.__setattr__(self, "false_neighbors", neighbors)
        performed = self.false_neighbor_analysis_performed
        if performed is not None and not isinstance(performed, bool):
            raise IREvaluationSuiteError("false_neighbor_analysis_performed must be bool or None")
        object.__setattr__(self, "false_neighbor_analysis_performed", bool(performed or neighbors))
        receipts = tuple(
            _identifier(item, "proof_receipt_ids[]")
            for item in self.proof_receipt_ids
            if str(item or "").strip()
        )
        object.__setattr__(self, "proof_receipt_ids", tuple(sorted(set(receipts))))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvaluationObservation":
        status = value.get("status")
        if status is None:
            status = METRIC_STATUS_MEASURED if value.get("value") is not None else METRIC_STATUS_UNSUPPORTED
        tokenizer = value.get("tokenizer_identity", value.get("tokenizer"))
        return cls(
            candidate_id=value.get("candidate_id", value.get("arm_id", "")),
            sample_id=value.get("sample_id", value.get("case_id", "")),
            surface=value.get("surface", value.get("direction", "")),
            metric_id=value.get("metric_id", value.get("metric", "")),
            value=value.get("value"),
            denominator=value.get("denominator", value.get("count", 1)),
            status=status,
            reason=value.get("reason", value.get("unsupported_reason", "")),
            strata=value.get("strata", value.get("stratum", {})),
            tokenizer_identity=tokenizer,
            false_neighbors=value.get("false_neighbors", value.get("false_neighbours", ())),
            false_neighbor_analysis_performed=value.get(
                "false_neighbor_analysis_performed",
                True if "false_neighbors" in value or "false_neighbours" in value else None,
            ),
            proof_receipt_ids=value.get("proof_receipt_ids", value.get("proof_receipts", ())),
        )


def _observations(values: Iterable[EvaluationObservation | Mapping[str, Any]]) -> tuple[EvaluationObservation, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise IREvaluationSuiteError("observations must be an iterable")
    result: list[EvaluationObservation] = []
    for value in values:
        if isinstance(value, EvaluationObservation):
            result.append(value)
        elif not isinstance(value, Mapping):
            raise IREvaluationSuiteError("observations contains an invalid item")
        elif isinstance(value.get("metrics"), Mapping) and "metric_id" not in value and "metric" not in value:
            for metric_id, metric_value in value["metrics"].items():
                expanded = dict(value)
                expanded.pop("metrics", None)
                expanded["metric_id"] = metric_id
                if isinstance(metric_value, Mapping):
                    expanded.update(metric_value)
                else:
                    expanded["value"] = metric_value
                result.append(EvaluationObservation.from_mapping(expanded))
        else:
            result.append(EvaluationObservation.from_mapping(value))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class EvaluationSuiteConfig:
    """Predeclared statistical and hard-gate policy."""

    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL
    alpha: float = DEFAULT_ALPHA
    seed: int = 17_071
    significance_correction: str = SIGNIFICANCE_CORRECTION_HOLM
    minimum_paired_cases: int = DEFAULT_MINIMUM_PAIRED_CASES
    noninferiority_margins: Mapping[str, float] = field(default_factory=dict)
    required_metric_ids: tuple[str, ...] = DEFAULT_REQUIRED_METRIC_IDS
    required_surfaces: tuple[str, ...] = IR_EVALUATION_SURFACES
    unsupported_required_metrics_block: bool = True
    require_proof_receipts: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.bootstrap_samples, bool)
            or not isinstance(self.bootstrap_samples, int)
            or not 1 <= self.bootstrap_samples <= MAX_BOOTSTRAP_SAMPLES
        ):
            raise IREvaluationSuiteError("bootstrap_samples is out of bounds")
        level, alpha = _finite(self.confidence_level, "confidence_level"), _finite(self.alpha, "alpha")
        if not 0 < level < 1 or not 0 < alpha < 1:
            raise IREvaluationSuiteError("confidence_level and alpha must be between zero and one")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise IREvaluationSuiteError("seed must be a non-negative integer")
        minimum = _nonnegative_int(self.minimum_paired_cases, "minimum_paired_cases")
        if minimum < 1:
            raise IREvaluationSuiteError("minimum_paired_cases must be positive")
        correction = str(self.significance_correction or "").lower().replace("-", "_")
        if correction == "holm_bonferroni":
            correction = SIGNIFICANCE_CORRECTION_HOLM
        if correction not in VALID_SIGNIFICANCE_CORRECTIONS:
            raise IREvaluationSuiteError("unsupported significance correction")
        margins = {
            metric_id: definition.default_noninferiority_margin
            for metric_id, definition in IR_EVALUATION_METRIC_CATALOG.items()
        }
        for metric_id, margin in self.noninferiority_margins.items():
            metric_id = canonical_metric_id(metric_id)
            margin = _finite(margin, "noninferiority margin")
            if margin < 0:
                raise IREvaluationSuiteError("noninferiority margins must be non-negative")
            margins[metric_id] = margin
        metrics = tuple(canonical_metric_id(item) for item in self.required_metric_ids)
        surfaces = tuple(_surface(item) for item in self.required_surfaces)
        if len(set(metrics)) != len(metrics) or not surfaces or len(set(surfaces)) != len(surfaces):
            raise IREvaluationSuiteError("required metrics/surfaces must be unique and non-empty")
        for name in ("unsupported_required_metrics_block", "require_proof_receipts"):
            if not isinstance(getattr(self, name), bool):
                raise IREvaluationSuiteError(f"{name} must be bool")
        object.__setattr__(self, "confidence_level", level)
        object.__setattr__(self, "alpha", alpha)
        object.__setattr__(self, "minimum_paired_cases", minimum)
        object.__setattr__(self, "significance_correction", correction)
        object.__setattr__(self, "noninferiority_margins", MappingProxyType(margins))
        object.__setattr__(self, "required_metric_ids", metrics)
        object.__setattr__(self, "required_surfaces", surfaces)

    def margin(self, metric_id: str) -> float:
        return float(self.noninferiority_margins[canonical_metric_id(metric_id)])

    def to_dict(self) -> dict[str, Any]:
        return {
            "alpha": _round(self.alpha),
            "bootstrap_samples": self.bootstrap_samples,
            "confidence_level": _round(self.confidence_level),
            "minimum_paired_cases": self.minimum_paired_cases,
            "noninferiority_margins": {
                key: _round(value) for key, value in self.noninferiority_margins.items()
            },
            "require_proof_receipts": self.require_proof_receipts,
            "required_metric_ids": list(self.required_metric_ids),
            "required_surfaces": list(self.required_surfaces),
            "seed": self.seed,
            "significance_correction": self.significance_correction,
            "unsupported_required_metrics_block": self.unsupported_required_metrics_block,
        }


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    estimate: float
    low: float
    high: float
    confidence_level: float
    bootstrap_samples: int
    method: str = "seeded_percentile_case_cluster_bootstrap"

    def __post_init__(self) -> None:
        for name in ("estimate", "low", "high"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.low > self.high:
            raise IREvaluationSuiteError("confidence interval low exceeds high")
        level = _finite(self.confidence_level, "confidence_level")
        if not 0 < level < 1:
            raise IREvaluationSuiteError("confidence_level must be between zero and one")
        _nonnegative_int(self.bootstrap_samples, "bootstrap_samples")
        object.__setattr__(self, "confidence_level", level)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bootstrap_samples": self.bootstrap_samples,
            "confidence_level": _round(self.confidence_level),
            "estimate": _round(self.estimate),
            "high": _round(self.high),
            "low": _round(self.low),
            "method": self.method,
            "resampling_unit": "case_cluster",
        }


def _weighted_mean(rows: Sequence[tuple[float, int]]) -> float:
    if not rows:
        raise IREvaluationSuiteError("cannot average empty metric evidence")
    weight = math.fsum(item[1] for item in rows)
    if weight <= 0:
        raise IREvaluationSuiteError("metric denominator must be positive")
    return math.fsum(value * denominator for value, denominator in rows) / weight


def _bootstrap(
    rows: Sequence[tuple[float, int]], *, config: EvaluationSuiteConfig, parts: Sequence[str]
) -> ConfidenceInterval:
    estimate = _weighted_mean(rows)
    rng = random.Random(_seed(config.seed, *parts))
    count = len(rows)
    draws = [
        _weighted_mean([rows[rng.randrange(count)] for _ in range(count)])
        for _ in range(config.bootstrap_samples)
    ]
    tail = (1.0 - config.confidence_level) / 2.0
    return ConfidenceInterval(
        estimate,
        _quantile(draws, tail),
        _quantile(draws, 1.0 - tail),
        config.confidence_level,
        config.bootstrap_samples,
    )


def _stratum_key(value: Mapping[str, str]) -> str:
    return "|".join(f"{key}={item}" for key, item in sorted(value.items()))


@dataclass(frozen=True, slots=True)
class MetricSummary:
    candidate_id: str
    surface: str
    metric_id: str
    status: str
    reason: str = ""
    denominator: int = 0
    sample_count: int = 0
    attempted_case_count: int = 0
    unsupported_case_count: int = 0
    value: Optional[float] = None
    confidence_interval: Optional[ConfidenceInterval] = None
    strata: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    tokenizer_identity: Optional[TokenizerIdentity] = None
    tokenizer_identity_issue: str = ""
    false_neighbor_analysis: Mapping[str, Any] = field(default_factory=dict)
    proof_receipts: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _identifier(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "surface", _surface(self.surface))
        object.__setattr__(self, "metric_id", canonical_metric_id(self.metric_id))
        if self.status not in {
            METRIC_STATUS_MEASURED,
            METRIC_STATUS_PARTIAL,
            METRIC_STATUS_UNSUPPORTED,
            METRIC_STATUS_UNAVAILABLE,
        }:
            raise IREvaluationSuiteError("invalid metric summary status")
        for name in ("denominator", "sample_count", "attempted_case_count", "unsupported_case_count"):
            object.__setattr__(self, name, _nonnegative_int(getattr(self, name), name))
        object.__setattr__(self, "reason", str(self.reason or "").strip())
        if self.status in {METRIC_STATUS_MEASURED, METRIC_STATUS_PARTIAL}:
            if self.value is None or not isinstance(self.confidence_interval, ConfidenceInterval):
                raise IREvaluationSuiteError("measured summary needs value and confidence interval")
            object.__setattr__(self, "value", _finite(self.value, "value"))
        elif self.value is not None or self.confidence_interval is not None or not self.reason:
            raise IREvaluationSuiteError("unmeasured summary needs an explicit unsupported reason")
        object.__setattr__(self, "strata", _freeze(self.strata))
        object.__setattr__(self, "false_neighbor_analysis", _freeze(self.false_neighbor_analysis))
        object.__setattr__(self, "proof_receipts", _freeze(self.proof_receipts))

    @property
    def definition(self) -> MetricDefinition:
        return IR_EVALUATION_METRIC_CATALOG[self.metric_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted_case_count": self.attempted_case_count,
            "candidate_id": self.candidate_id,
            "confidence_interval": (
                None if self.confidence_interval is None else self.confidence_interval.to_dict()
            ),
            "denominator": self.denominator,
            "false_neighbor_analysis": _plain(self.false_neighbor_analysis),
            "higher_is_better": self.definition.higher_is_better,
            "metric_id": self.metric_id,
            "n_metric": self.definition.n_metric,
            "proof_receipts": _plain(self.proof_receipts),
            "reason": self.reason or None,
            "sample_count": self.sample_count,
            "status": self.status,
            "strata": _plain(self.strata),
            "surface": self.surface,
            "tokenizer_identity": (
                None if self.tokenizer_identity is None else self.tokenizer_identity.to_dict()
            ),
            "tokenizer_identity_issue": self.tokenizer_identity_issue or None,
            "unit": self.definition.unit,
            "unsupported_case_count": self.unsupported_case_count,
            "value": _round(self.value),
        }


@dataclass(frozen=True, slots=True)
class PairedComparison:
    baseline_id: str
    candidate_id: str
    surface: str
    metric_id: str
    status: str
    reason: str = ""
    paired_case_count: int = 0
    baseline_only_case_count: int = 0
    candidate_only_case_count: int = 0
    paired_denominator: int = 0
    baseline_value: Optional[float] = None
    candidate_value: Optional[float] = None
    candidate_minus_baseline: Optional[float] = None
    quality_delta: Optional[float] = None
    raw_confidence_interval: Optional[ConfidenceInterval] = None
    quality_confidence_interval: Optional[ConfidenceInterval] = None
    noninferiority_margin: Optional[float] = None
    noninferiority_passed: Optional[bool] = None
    raw_p_value: Optional[float] = None
    adjusted_p_value: Optional[float] = None
    significance_correction: str = SIGNIFICANCE_CORRECTION_NONE
    significant_improvement: Optional[bool] = None
    paired_strata: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "baseline_id", _identifier(self.baseline_id, "baseline_id"))
        object.__setattr__(self, "candidate_id", _identifier(self.candidate_id, "candidate_id"))
        if self.baseline_id == self.candidate_id:
            raise IREvaluationSuiteError("baseline and candidate must differ")
        object.__setattr__(self, "surface", _surface(self.surface))
        object.__setattr__(self, "metric_id", canonical_metric_id(self.metric_id))
        if self.status not in {
            METRIC_STATUS_MEASURED,
            METRIC_STATUS_PARTIAL,
            METRIC_STATUS_UNSUPPORTED,
            METRIC_STATUS_UNAVAILABLE,
        }:
            raise IREvaluationSuiteError("invalid comparison status")
        object.__setattr__(self, "reason", str(self.reason or "").strip())
        for name in (
            "paired_case_count",
            "baseline_only_case_count",
            "candidate_only_case_count",
            "paired_denominator",
        ):
            object.__setattr__(self, name, _nonnegative_int(getattr(self, name), name))
        for name in (
            "baseline_value",
            "candidate_value",
            "candidate_minus_baseline",
            "quality_delta",
            "noninferiority_margin",
            "raw_p_value",
            "adjusted_p_value",
        ):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.status in {METRIC_STATUS_MEASURED, METRIC_STATUS_PARTIAL}:
            if not all(
                item is not None
                for item in (
                    self.baseline_value,
                    self.candidate_value,
                    self.candidate_minus_baseline,
                    self.quality_delta,
                    self.raw_confidence_interval,
                    self.quality_confidence_interval,
                    self.noninferiority_margin,
                    self.noninferiority_passed,
                    self.raw_p_value,
                )
            ):
                raise IREvaluationSuiteError("measured comparison is missing statistical evidence")
        elif not self.reason:
            raise IREvaluationSuiteError("unavailable comparison needs a reason")
        object.__setattr__(self, "paired_strata", MappingProxyType(dict(sorted(self.paired_strata.items()))))

    @property
    def complete_pairing(self) -> bool:
        return (
            self.status == METRIC_STATUS_MEASURED
            and self.baseline_only_case_count == 0
            and self.candidate_only_case_count == 0
        )

    @property
    def definition(self) -> MetricDefinition:
        return IR_EVALUATION_METRIC_CATALOG[self.metric_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjusted_p_value": _round(self.adjusted_p_value),
            "baseline_id": self.baseline_id,
            "baseline_only_case_count": self.baseline_only_case_count,
            "baseline_value": _round(self.baseline_value),
            "candidate_id": self.candidate_id,
            "candidate_minus_baseline": _round(self.candidate_minus_baseline),
            "candidate_only_case_count": self.candidate_only_case_count,
            "candidate_value": _round(self.candidate_value),
            "complete_pairing": self.complete_pairing,
            "higher_is_better": self.definition.higher_is_better,
            "metric_id": self.metric_id,
            "n_metric": self.definition.n_metric,
            "noninferiority_margin": _round(self.noninferiority_margin),
            "noninferiority_passed": self.noninferiority_passed,
            "paired_case_count": self.paired_case_count,
            "paired_denominator": self.paired_denominator,
            "paired_strata": dict(self.paired_strata),
            "quality_confidence_interval": (
                None if self.quality_confidence_interval is None else self.quality_confidence_interval.to_dict()
            ),
            "quality_delta": _round(self.quality_delta),
            "raw_confidence_interval": (
                None if self.raw_confidence_interval is None else self.raw_confidence_interval.to_dict()
            ),
            "raw_p_value": _round(self.raw_p_value),
            "reason": self.reason or None,
            "significance_correction": self.significance_correction,
            "significant_improvement": self.significant_improvement,
            "status": self.status,
            "surface": self.surface,
        }


@dataclass(frozen=True, slots=True)
class CandidatePromotionGate:
    candidate_id: str
    accepted: bool
    block_reasons: tuple[str, ...]
    required_metric_ids: tuple[str, ...]
    required_surfaces: tuple[str, ...]
    significant_improvements: tuple[str, ...] = ()
    readability_informational_only: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _identifier(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "block_reasons", tuple(sorted(set(self.block_reasons))))
        object.__setattr__(self, "required_metric_ids", tuple(canonical_metric_id(item) for item in self.required_metric_ids))
        object.__setattr__(self, "required_surfaces", tuple(_surface(item) for item in self.required_surfaces))
        object.__setattr__(self, "significant_improvements", tuple(sorted(set(self.significant_improvements))))
        if self.accepted == bool(self.block_reasons):
            raise IREvaluationSuiteError("accepted gates have no blocks; rejected gates explain blocks")

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "block_reasons": list(self.block_reasons),
            "candidate_id": self.candidate_id,
            "hard_promotion_gate": True,
            "readability_informational_only": self.readability_informational_only,
            "required_metric_ids": list(self.required_metric_ids),
            "required_surfaces": list(self.required_surfaces),
            "significant_improvements": list(self.significant_improvements),
            "status": "accepted" if self.accepted else "blocked",
        }


def _identity(rows: Sequence[EvaluationObservation], explicit: Optional[TokenizerIdentity]) -> tuple[Optional[TokenizerIdentity], str]:
    identities = [item.tokenizer_identity for item in rows if item.tokenizer_identity is not None]
    if explicit is not None:
        identities.append(explicit)
    if not identities:
        return None, "tokenizer_identity_missing"
    reference = identities[0]
    if any(reference.mismatches(item) for item in identities[1:]):
        return None, "inconsistent_tokenizer_identity_within_candidate"
    return reference, ""


def _false_neighbor_report(rows: Sequence[EvaluationObservation]) -> Mapping[str, Any]:
    if not any(item.false_neighbor_analysis_performed for item in rows):
        return MappingProxyType(
            {
                "denominator": len(rows),
                "false_neighbor_count": 0,
                "reason": "false-neighbour analysis was not supplied",
                "records": (),
                "status": METRIC_STATUS_UNSUPPORTED,
            }
        )
    records: dict[tuple[str, str, str, Optional[float]], FalseNeighborEvidence] = {}
    for row in rows:
        for item in row.false_neighbors:
            records[(item.sample_id, item.neighbor_id, item.reason, item.similarity)] = item
    rendered = tuple(item.to_dict() for _, item in sorted(records.items(), key=lambda pair: repr(pair[0])))
    denominator = len(rows)
    return MappingProxyType(
        {
            "denominator": denominator,
            "false_neighbor_count": len(rendered),
            "false_neighbor_rate": 0.0 if denominator == 0 else len(rendered) / denominator,
            "records": rendered,
            "status": METRIC_STATUS_MEASURED,
        }
    )


def _proof_receipt_report(rows: Sequence[EvaluationObservation]) -> Mapping[str, Any]:
    receipts = tuple(sorted({receipt for row in rows for receipt in row.proof_receipt_ids}))
    if not receipts:
        return MappingProxyType(
            {
                "reason": "independent proof receipts were not supplied",
                "receipt_count": 0,
                "receipt_ids": (),
                "status": METRIC_STATUS_UNSUPPORTED,
            }
        )
    return MappingProxyType(
        {"receipt_count": len(receipts), "receipt_ids": receipts, "status": METRIC_STATUS_MEASURED}
    )


def _summary(
    candidate_id: str,
    surface: str,
    metric_id: str,
    rows: Sequence[EvaluationObservation],
    config: EvaluationSuiteConfig,
    explicit_tokenizer: Optional[TokenizerIdentity],
) -> MetricSummary:
    measured = tuple(row for row in rows if row.status == METRIC_STATUS_MEASURED)
    unsupported = tuple(row for row in rows if row.status == METRIC_STATUS_UNSUPPORTED)
    if not measured:
        reasons = sorted({row.reason for row in unsupported if row.reason})
        return MetricSummary(
            candidate_id,
            surface,
            metric_id,
            METRIC_STATUS_UNSUPPORTED,
            "; ".join(reasons) or "no observation was supplied",
            attempted_case_count=len(rows),
            unsupported_case_count=len(unsupported),
            false_neighbor_analysis=(
                _false_neighbor_report(rows) if metric_id == N2_LATENT_SEPARATION else {}
            ),
            proof_receipts=(
                _proof_receipt_report(rows) if metric_id == N6_PROOF_REPLAY_RATE else {}
            ),
        )
    interval = _bootstrap(
        [(float(row.value), row.denominator) for row in measured],
        config=config,
        parts=(candidate_id, surface, metric_id, "summary"),
    )
    by_stratum: dict[str, list[EvaluationObservation]] = {}
    for row in measured:
        by_stratum.setdefault(_stratum_key(row.strata), []).append(row)
    strata = {
        key: {
            "denominator": sum(item.denominator for item in items),
            "labels": _plain(items[0].strata),
            "sample_count": len(items),
            "value": _round(_weighted_mean([(float(item.value), item.denominator) for item in items])),
        }
        for key, items in sorted(by_stratum.items())
    }
    definition = IR_EVALUATION_METRIC_CATALOG[metric_id]
    identity, identity_issue = (None, "")
    if definition.requires_tokenizer_comparability:
        identity, identity_issue = _identity(measured, explicit_tokenizer)
    reasons = sorted({row.reason for row in unsupported if row.reason})
    return MetricSummary(
        candidate_id,
        surface,
        metric_id,
        METRIC_STATUS_MEASURED if not unsupported else METRIC_STATUS_PARTIAL,
        "" if not unsupported else "some cases unsupported: " + "; ".join(reasons),
        sum(row.denominator for row in measured),
        len(measured),
        len(rows),
        len(unsupported),
        interval.estimate,
        interval,
        strata,
        identity,
        identity_issue,
        _false_neighbor_report(measured) if metric_id == N2_LATENT_SEPARATION else {},
        _proof_receipt_report(measured) if metric_id == N6_PROOF_REPLAY_RATE else {},
    )


def _unavailable(
    baseline_id: str,
    candidate_id: str,
    surface: str,
    metric_id: str,
    reason: str,
    baseline_only: int = 0,
    candidate_only: int = 0,
) -> PairedComparison:
    return PairedComparison(
        baseline_id,
        candidate_id,
        surface,
        metric_id,
        METRIC_STATUS_UNSUPPORTED,
        reason,
        baseline_only_case_count=baseline_only,
        candidate_only_case_count=candidate_only,
    )


def _comparison(
    baseline_id: str,
    candidate_id: str,
    surface: str,
    metric_id: str,
    baseline_rows: Sequence[EvaluationObservation],
    candidate_rows: Sequence[EvaluationObservation],
    baseline_summary: MetricSummary,
    candidate_summary: MetricSummary,
    config: EvaluationSuiteConfig,
) -> PairedComparison:
    definition = IR_EVALUATION_METRIC_CATALOG[metric_id]
    if not baseline_rows:
        return _unavailable(baseline_id, candidate_id, surface, metric_id, "baseline metric evidence is unavailable")
    if not candidate_rows:
        return _unavailable(baseline_id, candidate_id, surface, metric_id, "candidate metric evidence is unavailable")
    if definition.requires_tokenizer_comparability:
        if baseline_summary.tokenizer_identity is None or candidate_summary.tokenizer_identity is None:
            return _unavailable(
                baseline_id,
                candidate_id,
                surface,
                metric_id,
                "incomparable_tokenizers:identity_missing_or_inconsistent",
            )
        mismatches = baseline_summary.tokenizer_identity.mismatches(candidate_summary.tokenizer_identity)
        if mismatches:
            return _unavailable(
                baseline_id,
                candidate_id,
                surface,
                metric_id,
                "incomparable_tokenizers:" + ",".join(mismatches),
            )
    before = {row.sample_id: row for row in baseline_rows if row.status == METRIC_STATUS_MEASURED}
    after = {row.sample_id: row for row in candidate_rows if row.status == METRIC_STATUS_MEASURED}
    common = sorted(set(before) & set(after))
    before_only, after_only = set(before) - set(after), set(after) - set(before)
    if not common:
        return _unavailable(
            baseline_id,
            candidate_id,
            surface,
            metric_id,
            "no paired case overlap",
            len(before_only),
            len(after_only),
        )
    pairs = [(before[item], after[item]) for item in common]
    raw_rows = [(float(after.value) - float(before.value), min(before.denominator, after.denominator)) for before, after in pairs]
    raw_interval = _bootstrap(
        raw_rows,
        config=config,
        parts=(baseline_id, candidate_id, surface, metric_id, "paired"),
    )
    raw_draw_sign = 1.0 if definition.higher_is_better else -1.0
    quality_interval = ConfidenceInterval(
        raw_interval.estimate * raw_draw_sign,
        raw_interval.low if raw_draw_sign > 0 else -raw_interval.high,
        raw_interval.high if raw_draw_sign > 0 else -raw_interval.low,
        raw_interval.confidence_level,
        raw_interval.bootstrap_samples,
    )
    # Reproduce deterministic draws only for an explicitly reported bootstrap
    # tail probability; the gate itself is based on the confidence bound.
    rng = random.Random(_seed(config.seed, baseline_id, candidate_id, surface, metric_id, "paired"))
    draws = [
        _weighted_mean([raw_rows[rng.randrange(len(raw_rows))] for _ in range(len(raw_rows))])
        * raw_draw_sign
        for _ in range(config.bootstrap_samples)
    ]
    p_value = (1.0 + sum(value <= 0.0 for value in draws)) / (len(draws) + 1.0)
    stratum_counts: Counter[str] = Counter()
    for before_row, after_row in pairs:
        before_key, after_key = _stratum_key(before_row.strata), _stratum_key(after_row.strata)
        stratum_counts[after_key if before_key == after_key else f"candidate:{after_key}|baseline:{before_key}"] += 1
    partial_reasons: list[str] = []
    if before_only or after_only:
        partial_reasons.append("paired case coverage is incomplete")
    if baseline_summary.status != METRIC_STATUS_MEASURED:
        partial_reasons.append("baseline metric has unsupported cases")
    if candidate_summary.status != METRIC_STATUS_MEASURED:
        partial_reasons.append("candidate metric has unsupported cases")
    margin = config.margin(metric_id)
    return PairedComparison(
        baseline_id,
        candidate_id,
        surface,
        metric_id,
        METRIC_STATUS_PARTIAL if partial_reasons else METRIC_STATUS_MEASURED,
        "; ".join(partial_reasons),
        len(pairs),
        len(before_only),
        len(after_only),
        sum(weight for _, weight in raw_rows),
        _weighted_mean([(float(row.value), min(row.denominator, after[row.sample_id].denominator)) for row in before.values() if row.sample_id in after]),
        _weighted_mean([(float(row.value), min(row.denominator, before[row.sample_id].denominator)) for row in after.values() if row.sample_id in before]),
        raw_interval.estimate,
        quality_interval.estimate,
        raw_interval,
        quality_interval,
        margin,
        quality_interval.low >= -margin,
        p_value,
        paired_strata=dict(stratum_counts),
    )


def _correct(
    comparisons: Mapping[str, Mapping[str, Mapping[str, PairedComparison]]],
    config: EvaluationSuiteConfig,
) -> Mapping[str, Mapping[str, Mapping[str, PairedComparison]]]:
    rows = [
        ((candidate, surface, metric), comparison)
        for candidate, by_surface in comparisons.items()
        for surface, by_metric in by_surface.items()
        for metric, comparison in by_metric.items()
        if comparison.status in {METRIC_STATUS_MEASURED, METRIC_STATUS_PARTIAL}
    ]
    adjusted: dict[tuple[str, str, str], float] = {}
    if config.significance_correction == SIGNIFICANCE_CORRECTION_NONE:
        adjusted = {key: float(item.raw_p_value) for key, item in rows}
    elif config.significance_correction == SIGNIFICANCE_CORRECTION_BONFERRONI:
        adjusted = {key: min(1.0, len(rows) * float(item.raw_p_value)) for key, item in rows}
    else:
        running = 0.0
        for rank, (key, item) in enumerate(sorted(rows, key=lambda item: (float(item[1].raw_p_value), item[0]))):
            running = max(running, min(1.0, (len(rows) - rank) * float(item.raw_p_value)))
            adjusted[key] = running
    result: dict[str, dict[str, dict[str, PairedComparison]]] = {}
    for candidate, by_surface in comparisons.items():
        result[candidate] = {}
        for surface, by_metric in by_surface.items():
            result[candidate][surface] = {}
            for metric, comparison in by_metric.items():
                p_value = adjusted.get((candidate, surface, metric))
                significant = (
                    None
                    if p_value is None or comparison.quality_confidence_interval is None
                    else comparison.quality_confidence_interval.low > 0 and p_value <= config.alpha
                )
                result[candidate][surface][metric] = replace(
                    comparison,
                    adjusted_p_value=p_value,
                    significance_correction=config.significance_correction,
                    significant_improvement=significant,
                )
    return result


def _tokenizer_report(before: MetricSummary, after: MetricSummary) -> Mapping[str, Any]:
    if before.tokenizer_identity is None or after.tokenizer_identity is None:
        return MappingProxyType(
            {
                "baseline_identity": None if before.tokenizer_identity is None else before.tokenizer_identity.to_dict(),
                "candidate_identity": None if after.tokenizer_identity is None else after.tokenizer_identity.to_dict(),
                "comparable": False,
                "reason": "tokenizer identity missing or inconsistent",
            }
        )
    mismatches = before.tokenizer_identity.mismatches(after.tokenizer_identity)
    return MappingProxyType(
        {
            "baseline_identity": before.tokenizer_identity.to_dict(),
            "candidate_identity": after.tokenizer_identity.to_dict(),
            "comparable": not mismatches,
            "mismatched_dimensions": list(mismatches),
            "reason": None if not mismatches else "tokenizer identities differ",
        }
    )


def _gate(
    baseline_id: str,
    candidate_id: str,
    comparisons: Mapping[str, Mapping[str, PairedComparison]],
    summaries: Mapping[str, Mapping[str, Mapping[str, MetricSummary]]],
    config: EvaluationSuiteConfig,
) -> CandidatePromotionGate:
    blocks: list[str] = []
    improvements = [
        f"{surface}:{metric}"
        for surface, by_metric in comparisons.items()
        for metric, comparison in by_metric.items()
        if comparison.significant_improvement
    ]
    for surface in config.required_surfaces:
        for metric in config.required_metric_ids:
            comparison = comparisons[surface][metric]
            prefix = f"{surface}:{metric}"
            if comparison.status != METRIC_STATUS_MEASURED:
                if config.unsupported_required_metrics_block:
                    blocks.append(prefix + ":evidence_unavailable:" + comparison.reason)
                continue
            if comparison.paired_case_count < config.minimum_paired_cases:
                blocks.append(prefix + f":insufficient_paired_cases:{comparison.paired_case_count}")
            if comparison.noninferiority_passed is not True:
                blocks.append(prefix + ":noninferiority_failed")
            if metric == N6_PROOF_REPLAY_RATE and config.require_proof_receipts:
                for arm, label in ((baseline_id, "baseline"), (candidate_id, "candidate")):
                    receipts = summaries[arm][surface][metric].proof_receipts
                    if receipts.get("status") != METRIC_STATUS_MEASURED:
                        blocks.append(prefix + f":{label}_independent_proof_receipts_missing")
    # A readability score can be an observation, but it cannot clear a known
    # semantic regression even when a diagnostic policy chose not to require N5.
    for surface in IR_EVALUATION_SURFACES:
        semantic = comparisons[surface][N5_SEMANTIC_EQUIVALENCE]
        if semantic.status in {METRIC_STATUS_MEASURED, METRIC_STATUS_PARTIAL} and semantic.noninferiority_passed is False:
            blocks.append(f"{surface}:{N5_SEMANTIC_EQUIVALENCE}:semantic_noninferiority_failed")
    return CandidatePromotionGate(
        candidate_id,
        not blocks,
        tuple(blocks),
        config.required_metric_ids,
        config.required_surfaces,
        tuple(improvements),
    )


@dataclass(frozen=True, slots=True)
class IREvaluationSuiteReport:
    baseline_id: str
    candidate_ids: tuple[str, ...]
    metric_summaries: Mapping[str, Mapping[str, Mapping[str, MetricSummary]]]
    comparisons: Mapping[str, Mapping[str, Mapping[str, PairedComparison]]]
    tokenizer_comparability: Mapping[str, Mapping[str, Mapping[str, Any]]]
    promotion_gates: Mapping[str, CandidatePromotionGate]
    config: EvaluationSuiteConfig
    interface: str = IR_EVALUATION_SUITE_INTERFACE
    schema_version: str = IR_EVALUATION_SUITE_SCHEMA_VERSION

    @property
    def accepted_candidate_ids(self) -> tuple[str, ...]:
        return tuple(candidate for candidate in self.candidate_ids if self.promotion_gates[candidate].accepted)

    @property
    def rejected_candidate_ids(self) -> tuple[str, ...]:
        return tuple(candidate for candidate in self.candidate_ids if not self.promotion_gates[candidate].accepted)

    @property
    def accepted(self) -> bool:
        return not self.rejected_candidate_ids

    def metric_summary(self, candidate_id: str, surface: str, metric_id: str) -> MetricSummary:
        return self.metric_summaries[candidate_id][_surface(surface)][canonical_metric_id(metric_id)]

    def comparison(self, candidate_id: str, surface: str, metric_id: str) -> PairedComparison:
        return self.comparisons[candidate_id][_surface(surface)][canonical_metric_id(metric_id)]

    def to_dict(self) -> dict[str, Any]:
        surface_reports = {
            candidate: {
                surface: {metric: summary.to_dict() for metric, summary in by_metric.items()}
                for surface, by_metric in by_surface.items()
            }
            for candidate, by_surface in self.metric_summaries.items()
        }
        n_reports: dict[str, Any] = {}
        for candidate, by_surface in self.metric_summaries.items():
            n_reports[candidate] = {}
            for surface, by_metric in by_surface.items():
                n_reports[candidate][surface] = {n_metric: {} for n_metric in N_METRIC_IDS}
                for metric, summary in by_metric.items():
                    n_reports[candidate][surface][summary.definition.n_metric][metric] = summary.to_dict()
        return {
            "accepted": self.accepted,
            "accepted_candidate_ids": list(self.accepted_candidate_ids),
            "baseline_id": self.baseline_id,
            "candidate_ids": list(self.candidate_ids),
            "comparison_reports": {
                candidate: {
                    surface: {metric: comparison.to_dict() for metric, comparison in by_metric.items()}
                    for surface, by_metric in by_surface.items()
                }
                for candidate, by_surface in self.comparisons.items()
            },
            "config": self.config.to_dict(),
            "interface": self.interface,
            "metric_catalog": {
                metric: definition.to_dict() for metric, definition in IR_EVALUATION_METRIC_CATALOG.items()
            },
            "n_metric_reports": n_reports,
            "promotion_gates": {candidate: gate.to_dict() for candidate, gate in self.promotion_gates.items()},
            "rejected_candidate_ids": list(self.rejected_candidate_ids),
            "schema_version": self.schema_version,
            "surface_reports": surface_reports,
            "tokenizer_comparability": _plain(self.tokenizer_comparability),
        }


def _provided_tokenizers(values: Optional[Mapping[Any, Any]]) -> Mapping[tuple[str, str], TokenizerIdentity]:
    if values is None:
        return MappingProxyType({})
    if not isinstance(values, Mapping):
        raise IREvaluationSuiteError("tokenizer_identities must be an object")
    result: dict[tuple[str, str], TokenizerIdentity] = {}
    for key, value in values.items():
        if isinstance(key, tuple) and len(key) == 2:
            keys = ((_identifier(key[0], "candidate_id"), _surface(key[1])),)
            identity_values = (value,)
        else:
            candidate = _identifier(key, "candidate_id")
            if isinstance(value, TokenizerIdentity):
                keys = tuple((candidate, surface) for surface in IR_EVALUATION_SURFACES)
                identity_values = tuple(value for _ in keys)
            elif isinstance(value, Mapping) and any(str(name).lower() in IR_EVALUATION_SURFACES for name in value):
                keys = tuple((candidate, _surface(surface)) for surface in value)
                identity_values = tuple(value[surface] for surface in value)
            else:
                keys = tuple((candidate, surface) for surface in IR_EVALUATION_SURFACES)
                identity_values = tuple(value for _ in keys)
        for item_key, identity_value in zip(keys, identity_values, strict=True):
            result[item_key] = (
                identity_value
                if isinstance(identity_value, TokenizerIdentity)
                else TokenizerIdentity.from_mapping(identity_value)
            )
    return MappingProxyType(result)


class IREvaluationSuite:
    """Reduce immutable N1--N8 evidence into safe promotion reports."""

    interface: Final = IR_EVALUATION_SUITE_INTERFACE

    def __init__(self, *, config: Optional[EvaluationSuiteConfig] = None) -> None:
        self.config = config or EvaluationSuiteConfig()

    def evaluate(
        self,
        observations: Iterable[EvaluationObservation | Mapping[str, Any]],
        *,
        baseline_id: str,
        candidate_ids: Optional[Iterable[str]] = None,
        tokenizer_identities: Optional[Mapping[Any, Any]] = None,
    ) -> IREvaluationSuiteReport:
        baseline_id = _identifier(baseline_id, "baseline_id")
        observations = _observations(observations)
        observed_arms = {row.candidate_id for row in observations}
        if candidate_ids is None:
            candidates = tuple(sorted(observed_arms - {baseline_id}))
        else:
            if isinstance(candidate_ids, (str, bytes, bytearray)):
                raise IREvaluationSuiteError("candidate_ids must be an iterable")
            candidates = tuple(_identifier(item, "candidate_ids[]") for item in candidate_ids)
        if not candidates or len(set(candidates)) != len(candidates) or baseline_id in candidates:
            raise IREvaluationSuiteError("candidate_ids must be non-empty, unique, and exclude baseline")
        unknown_arms = observed_arms - {baseline_id, *candidates}
        if unknown_arms:
            raise IREvaluationSuiteError(f"observations include undeclared candidates: {sorted(unknown_arms)!r}")
        keys: set[tuple[str, str, str, str]] = set()
        for row in observations:
            key = (row.candidate_id, row.surface, row.metric_id, row.sample_id)
            if key in keys:
                raise IREvaluationSuiteError("candidate/surface/metric/sample observations must be unique")
            keys.add(key)
        by_key: dict[tuple[str, str, str], list[EvaluationObservation]] = {}
        for row in observations:
            by_key.setdefault((row.candidate_id, row.surface, row.metric_id), []).append(row)
        tokenizer_map = _provided_tokenizers(tokenizer_identities)
        arms = (baseline_id, *candidates)
        summaries: dict[str, dict[str, dict[str, MetricSummary]]] = {}
        row_groups: dict[tuple[str, str, str], tuple[EvaluationObservation, ...]] = {}
        for arm in arms:
            summaries[arm] = {}
            for surface in IR_EVALUATION_SURFACES:
                summaries[arm][surface] = {}
                for metric in IR_EVALUATION_MEASURE_IDS:
                    rows = tuple(by_key.get((arm, surface, metric), ()))
                    row_groups[(arm, surface, metric)] = rows
                    summaries[arm][surface][metric] = _summary(
                        arm,
                        surface,
                        metric,
                        rows,
                        self.config,
                        tokenizer_map.get((arm, surface)),
                    )
        comparisons: dict[str, dict[str, dict[str, PairedComparison]]] = {}
        tokenizer_reports: dict[str, dict[str, Mapping[str, Any]]] = {}
        for candidate in candidates:
            comparisons[candidate], tokenizer_reports[candidate] = {}, {}
            for surface in IR_EVALUATION_SURFACES:
                comparisons[candidate][surface] = {}
                for metric in IR_EVALUATION_MEASURE_IDS:
                    comparisons[candidate][surface][metric] = _comparison(
                        baseline_id,
                        candidate,
                        surface,
                        metric,
                        row_groups[(baseline_id, surface, metric)],
                        row_groups[(candidate, surface, metric)],
                        summaries[baseline_id][surface][metric],
                        summaries[candidate][surface][metric],
                        self.config,
                    )
                tokenizer_reports[candidate][surface] = _tokenizer_report(
                    summaries[baseline_id][surface][N1_TOKEN_CROSS_ENTROPY],
                    summaries[candidate][surface][N1_TOKEN_CROSS_ENTROPY],
                )
        comparisons = _correct(comparisons, self.config)
        gates = {
            candidate: _gate(baseline_id, candidate, comparisons[candidate], summaries, self.config)
            for candidate in candidates
        }
        return IREvaluationSuiteReport(
            baseline_id,
            candidates,
            _freeze(summaries),
            _freeze(comparisons),
            _freeze(tokenizer_reports),
            _freeze(gates),
            self.config,
        )


def evaluate_ir_evaluation_suite(
    observations: Iterable[EvaluationObservation | Mapping[str, Any]],
    *,
    baseline_id: str,
    candidate_ids: Optional[Iterable[str]] = None,
    tokenizer_identities: Optional[Mapping[Any, Any]] = None,
    config: Optional[EvaluationSuiteConfig] = None,
) -> IREvaluationSuiteReport:
    """Functional wrapper around :class:`IREvaluationSuite`."""

    return IREvaluationSuite(config=config).evaluate(
        observations,
        baseline_id=baseline_id,
        candidate_ids=candidate_ids,
        tokenizer_identities=tokenizer_identities,
    )


__all__ = [
    "IR_EVALUATION_SUITE_INTERFACE",
    "IR_EVALUATION_SUITE_SCHEMA_VERSION",
    "COMPILER_SURFACE",
    "DECOMPILER_SURFACE",
    "IR_EVALUATION_SURFACES",
    "METRIC_STATUS_MEASURED",
    "METRIC_STATUS_PARTIAL",
    "METRIC_STATUS_UNSUPPORTED",
    "METRIC_STATUS_UNAVAILABLE",
    "SIGNIFICANCE_CORRECTION_HOLM",
    "SIGNIFICANCE_CORRECTION_BONFERRONI",
    "SIGNIFICANCE_CORRECTION_NONE",
    "N1",
    "N2",
    "N3",
    "N4",
    "N5",
    "N6",
    "N7",
    "N8",
    "N1_TOKEN",
    "N2_LATENT",
    "N3_RETRIEVAL",
    "N4_STRUCTURAL",
    "N5_SEMANTIC",
    "N6_PROOF",
    "N7_READABILITY",
    "N8_CALIBRATION_OOD",
    "N_METRIC_IDS",
    "N1_TOKEN_CROSS_ENTROPY",
    "N2_LATENT_SEPARATION",
    "N3_RETRIEVAL_RECALL",
    "N4_STRUCTURAL_EQUIVALENCE",
    "N5_SEMANTIC_EQUIVALENCE",
    "N6_PROOF_REPLAY_RATE",
    "N7_READABILITY_SCORE",
    "N8_CALIBRATION_ERROR",
    "N8_OOD_ACCEPTANCE",
    "IR_EVALUATION_MEASURE_IDS",
    "IR_EVALUATION_METRIC_CATALOG",
    "N_METRIC_CATALOG",
    "DEFAULT_REQUIRED_METRIC_IDS",
    "IREvaluationSuiteError",
    "MetricDefinition",
    "TokenizerIdentity",
    "FalseNeighborEvidence",
    "EvaluationObservation",
    "EvaluationSuiteConfig",
    "ConfidenceInterval",
    "MetricSummary",
    "PairedComparison",
    "CandidatePromotionGate",
    "IREvaluationSuiteReport",
    "canonical_metric_id",
    "IREvaluationSuite",
    "evaluate_ir_evaluation_suite",
]
