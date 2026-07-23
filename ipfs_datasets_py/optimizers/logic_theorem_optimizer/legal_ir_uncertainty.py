"""Uncertainty, abstention, and promotion gates for learned LegalIR guidance.

Learned guidance may rank useful compiler/decompiler repair features, but it
must not become a Codex TODO source unless the family-level confidence is
calibrated and the family is supported.  This module converts raw learned
guidance, proof-head metrics, or pre-aggregated family blocks into deterministic
per-family uncertainty reports.  The same report drives promotion gates and the
Codex-vs-Hammer/Leanstral routing decision.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Optional

from .legal_ir_family_evaluator import (
    LEGAL_IR_EVALUATION_FAMILIES,
    canonical_legal_ir_evaluation_family,
)


LEGAL_IR_UNCERTAINTY_SCHEMA_VERSION: Final = "legal-ir-uncertainty-v1"

ROUTE_CODEX_TODO: Final = "codex_todo_generation"
ROUTE_HAMMER_LEANSTRAL_AUDIT: Final = "hammer_leanstral_audit"

DEFAULT_MIN_CALIBRATED_CONFIDENCE: Final = 0.72
DEFAULT_MAX_NORMALIZED_ENTROPY: Final = 0.55
DEFAULT_MAX_CALIBRATION_ERROR: Final = 0.08
DEFAULT_MAX_OOD_RATE: Final = 0.0
DEFAULT_MAX_UNSUPPORTED_ABSTENTION_RATE: Final = 0.0

_GUIDANCE_LIST_KEYS: Final = (
    "ambiguities",
    "ambiguity_records",
    "guidance_items",
    "learned_guidance",
    "leanstral_guidance",
    "legal_ir_ambiguities",
    "guidance",
    "items",
    "verified_guidance",
    "hammer_guidance_artifacts",
)

_DISTRIBUTION_KEYS: Final = (
    "calibrated_family_distribution",
    "legal_ir_predicted_family_distribution",
    "legal_ir_predicted_view_distribution",
    "family_distribution",
    "view_family_weights",
    "probabilities",
    "probability_distribution",
    "legal_ir_view_distribution",
)

_TARGET_DISTRIBUTION_KEYS: Final = (
    "legal_ir_target_view_distribution",
    "target_family_distribution",
    "target_distribution",
    "label_distribution",
)

_CONFIDENCE_KEYS: Final = (
    "calibrated_confidence",
    "confidence",
    "model_confidence",
    "probability",
    "score",
)

_CALIBRATION_ERROR_KEYS: Final = (
    "calibration_error",
    "expected_calibration_error",
    "ece",
    "brier_score",
    "calibration",
)

_ENTROPY_KEYS: Final = (
    "normalized_entropy",
    "entropy",
    "entropy_loss",
    "predictive_entropy",
)

_OOD_KEYS: Final = (
    "ood",
    "out_of_distribution",
    "out_of_distribution_signal",
    "distribution_shift",
)

_OOD_SCORE_KEYS: Final = (
    "ood_score",
    "out_of_distribution_score",
    "distance_from_training_distribution",
)

_FAMILY_KEYS: Final = (
    "legal_ir_family",
    "family",
    "logic_family",
    "semantic_family",
    "view_family",
    "program_synthesis_scope",
)

_AMBIGUITY_KEYS: Final = (
    "ambiguity_id",
    "ambiguity_kind",
    "arbitrary_learned_label",
    "competing_parses",
    "human_review_required",
    "learned_label",
    "legal_ir_ambiguity",
    "unsupported_interpretations",
)

_VIEW_FAMILY_ALIASES: Final[Mapping[str, str]] = {
    "deontic": "deontic",
    "deontic.ir": "deontic",
    "legalnormir": "deontic",
    "frame": "frame_logic",
    "frame_logic": "frame_logic",
    "modal.frame_logic": "frame_logic",
    "flogic": "frame_logic",
    "tdfol": "tdfol",
    "tdfol.prover": "tdfol",
    "knowledge_graph": "knowledge_graphs",
    "knowledge_graphs": "knowledge_graphs",
    "knowledge_graphs.neo4j_compat": "knowledge_graphs",
    "kg": "knowledge_graphs",
    "cec": "cec",
    "dcec": "cec",
    "external_prover": "external_provers",
    "external_provers": "external_provers",
    "external_provers.router": "external_provers",
    "decompiler": "decompiler",
    "ir_decompiler": "decompiler",
    "temporal": "temporal",
    "provenance": "provenance",
}


@dataclass(frozen=True, slots=True)
class LegalIRUncertaintyConfig:
    """Family-threshold policy for uncertainty and promotion gating."""

    families: tuple[str, ...] = LEGAL_IR_EVALUATION_FAMILIES
    min_calibrated_confidence: Mapping[str, float] = field(default_factory=dict)
    max_normalized_entropy: Mapping[str, float] = field(default_factory=dict)
    max_calibration_error: Mapping[str, float] = field(default_factory=dict)
    max_ood_rate: Mapping[str, float] = field(default_factory=dict)
    max_unsupported_abstention_rate: Mapping[str, float] = field(default_factory=dict)
    ood_score_threshold: float = 0.5
    require_supported_family: bool = True

    def __post_init__(self) -> None:
        families = tuple(_canonical_supported_family(family) for family in self.families)
        if not families:
            raise ValueError("at least one LegalIR family is required")
        if len(set(families)) != len(families):
            raise ValueError("families must be unique after canonicalization")
        object.__setattr__(self, "families", families)
        object.__setattr__(
            self,
            "min_calibrated_confidence",
            _family_thresholds(
                self.min_calibrated_confidence,
                families,
                DEFAULT_MIN_CALIBRATED_CONFIDENCE,
                lower=0.0,
                upper=1.0,
            ),
        )
        object.__setattr__(
            self,
            "max_normalized_entropy",
            _family_thresholds(
                self.max_normalized_entropy,
                families,
                DEFAULT_MAX_NORMALIZED_ENTROPY,
                lower=0.0,
                upper=1.0,
            ),
        )
        object.__setattr__(
            self,
            "max_calibration_error",
            _family_thresholds(
                self.max_calibration_error,
                families,
                DEFAULT_MAX_CALIBRATION_ERROR,
                lower=0.0,
                upper=1.0,
            ),
        )
        object.__setattr__(
            self,
            "max_ood_rate",
            _family_thresholds(
                self.max_ood_rate,
                families,
                DEFAULT_MAX_OOD_RATE,
                lower=0.0,
                upper=1.0,
            ),
        )
        object.__setattr__(
            self,
            "max_unsupported_abstention_rate",
            _family_thresholds(
                self.max_unsupported_abstention_rate,
                families,
                DEFAULT_MAX_UNSUPPORTED_ABSTENTION_RATE,
                lower=0.0,
                upper=1.0,
            ),
        )
        object.__setattr__(
            self,
            "ood_score_threshold",
            max(0.0, min(1.0, _finite_float(self.ood_score_threshold, 0.5))),
        )

    def threshold(self, name: str, family: str) -> float:
        table = getattr(self, name)
        return float(table[_canonical_supported_family(family)])


@dataclass(frozen=True, slots=True)
class LegalIRFamilyUncertaintyResult:
    """Uncertainty evidence for one LegalIR family."""

    family: str
    observation_count: int
    calibrated_confidence: float
    raw_confidence: float
    normalized_entropy: float
    calibration_error: float
    abstention_rate: float
    ood_rate: float
    unsupported_family_rate: float
    unsupported_abstention_rate: float
    codex_todo_generation_count: int
    hammer_leanstral_audit_count: int
    block_reasons: tuple[str, ...] = ()
    evidence_sources: tuple[str, ...] = ()

    @property
    def abstained(self) -> bool:
        return self.abstention_rate > 0.0

    @property
    def promotion_allowed(self) -> bool:
        return not self.block_reasons

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstained": self.abstained,
            "abstention_rate": round(self.abstention_rate, 12),
            "block_reasons": list(self.block_reasons),
            "calibrated_confidence": round(self.calibrated_confidence, 12),
            "calibration_error": round(self.calibration_error, 12),
            "codex_todo_generation_count": self.codex_todo_generation_count,
            "evidence_sources": list(self.evidence_sources),
            "family": self.family,
            "hammer_leanstral_audit_count": self.hammer_leanstral_audit_count,
            "normalized_entropy": round(self.normalized_entropy, 12),
            "observation_count": self.observation_count,
            "ood_rate": round(self.ood_rate, 12),
            "promotion_allowed": self.promotion_allowed,
            "raw_confidence": round(self.raw_confidence, 12),
            "unsupported_abstention_rate": round(
                self.unsupported_abstention_rate,
                12,
            ),
            "unsupported_family_rate": round(self.unsupported_family_rate, 12),
        }


@dataclass(frozen=True, slots=True)
class LegalIRUncertaintyReport:
    """Aggregate uncertainty report across LegalIR families."""

    family_results: Mapping[str, LegalIRFamilyUncertaintyResult]
    block_reasons: tuple[str, ...]
    audit_guidance_ids: tuple[str, ...] = ()
    codex_guidance_ids: tuple[str, ...] = ()
    unsupported_guidance_ids: tuple[str, ...] = ()
    gate_id: str = ""
    schema_version: str = LEGAL_IR_UNCERTAINTY_SCHEMA_VERSION

    @property
    def promotion_allowed(self) -> bool:
        return not self.block_reasons

    @property
    def accepted(self) -> bool:
        return self.promotion_allowed

    @property
    def failed_families(self) -> tuple[str, ...]:
        return tuple(
            family
            for family, result in self.family_results.items()
            if not result.promotion_allowed
        )

    @property
    def audit_count(self) -> int:
        return sum(
            result.hammer_leanstral_audit_count
            for result in self.family_results.values()
        )

    @property
    def codex_todo_generation_count(self) -> int:
        return sum(
            result.codex_todo_generation_count
            for result in self.family_results.values()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "audit_count": self.audit_count,
            "audit_guidance_ids": list(self.audit_guidance_ids),
            "block_reasons": list(self.block_reasons),
            "codex_guidance_ids": list(self.codex_guidance_ids),
            "codex_todo_generation_count": self.codex_todo_generation_count,
            "failed_families": list(self.failed_families),
            "families": list(self.family_results),
            "family_results": {
                family: result.to_dict()
                for family, result in self.family_results.items()
            },
            "gate_id": self.gate_id,
            "hard_promotion_gate": True,
            "promotion_allowed": self.promotion_allowed,
            "schema_version": self.schema_version,
            "status": "accepted" if self.accepted else "blocked",
            "unsupported_guidance_ids": list(self.unsupported_guidance_ids),
        }


def evaluate_legal_ir_uncertainty(
    guidance: Any = (),
    *,
    metrics: Any = None,
    config: Optional[LegalIRUncertaintyConfig] = None,
) -> LegalIRUncertaintyReport:
    """Return family-level confidence, entropy, abstention, and OOD signals."""

    policy = config or LegalIRUncertaintyConfig()
    observations = _guidance_observations(guidance, policy=policy)
    observations.extend(_metric_observations(metrics, policy=policy))
    by_family: dict[str, list[dict[str, Any]]] = {family: [] for family in policy.families}
    unsupported: list[dict[str, Any]] = []
    for observation in observations:
        family = str(observation.get("family") or "")
        if family in by_family:
            by_family[family].append(observation)
        else:
            unsupported.append(observation)
    if unsupported:
        by_family.setdefault("unsupported", []).extend(unsupported)

    family_results: dict[str, LegalIRFamilyUncertaintyResult] = {}
    block_reasons: list[str] = []
    audit_guidance_ids: list[str] = []
    codex_guidance_ids: list[str] = []
    unsupported_guidance_ids: list[str] = []
    for family in (*policy.families, *(() if not unsupported else ("unsupported",))):
        rows = by_family.get(family, [])
        result = _family_result(family, rows, policy)
        family_results[family] = result
        block_reasons.extend(result.block_reasons)
        for row in rows:
            guidance_id = str(row.get("guidance_id") or "").strip()
            if not guidance_id:
                continue
            if row.get("route") == ROUTE_CODEX_TODO:
                codex_guidance_ids.append(guidance_id)
            else:
                audit_guidance_ids.append(guidance_id)
            if row.get("unsupported_family"):
                unsupported_guidance_ids.append(guidance_id)

    gate_payload = {
        "audit": _unique(audit_guidance_ids),
        "blocks": block_reasons,
        "codex": _unique(codex_guidance_ids),
        "families": {
            family: result.to_dict()
            for family, result in family_results.items()
            if result.observation_count
        },
        "schema": LEGAL_IR_UNCERTAINTY_SCHEMA_VERSION,
    }
    return LegalIRUncertaintyReport(
        family_results=family_results,
        block_reasons=tuple(_unique(block_reasons)),
        audit_guidance_ids=tuple(_unique(audit_guidance_ids)),
        codex_guidance_ids=tuple(_unique(codex_guidance_ids)),
        unsupported_guidance_ids=tuple(_unique(unsupported_guidance_ids)),
        gate_id="legal-ir-uncertainty-" + _hash_json(gate_payload)[:24],
    )


def route_learned_guidance_by_uncertainty(
    guidance: Any,
    *,
    metrics: Any = None,
    config: Optional[LegalIRUncertaintyConfig] = None,
) -> dict[str, Any]:
    """Split learned guidance into Codex-eligible items and audit-only items."""

    policy = config or LegalIRUncertaintyConfig()
    items = _guidance_items(guidance)
    report = evaluate_legal_ir_uncertainty(items, metrics=metrics, config=policy)
    codex_ids = set(report.codex_guidance_ids)
    audit_ids = set(report.audit_guidance_ids)
    codex_items: list[dict[str, Any]] = []
    audit_items: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        guidance_id = _guidance_id(item, index=index)
        if guidance_id in codex_ids and guidance_id not in audit_ids:
            routed = dict(item)
            routed["uncertainty_route"] = ROUTE_CODEX_TODO
            codex_items.append(routed)
        else:
            routed = dict(item)
            routed["uncertainty_route"] = ROUTE_HAMMER_LEANSTRAL_AUDIT
            audit_items.append(routed)
    return {
        "audit_guidance_items": audit_items,
        "codex_guidance_items": codex_items,
        "report": report.to_dict(),
    }


def legal_ir_uncertainty_promotion_gate(
    guidance: Any = (),
    *,
    metrics: Any = None,
    config: Optional[LegalIRUncertaintyConfig] = None,
) -> dict[str, Any]:
    """Return a hard promotion gate payload for learned LegalIR guidance."""

    return evaluate_legal_ir_uncertainty(
        guidance,
        metrics=metrics,
        config=config,
    ).to_dict()


def _family_result(
    family: str,
    rows: Sequence[Mapping[str, Any]],
    policy: LegalIRUncertaintyConfig,
) -> LegalIRFamilyUncertaintyResult:
    count = len(rows)
    raw_confidence = _mean([float(row["raw_confidence"]) for row in rows])
    calibrated_confidence = _mean(
        [float(row["calibrated_confidence"]) for row in rows]
    )
    normalized_entropy = _mean([float(row["normalized_entropy"]) for row in rows])
    calibration_error = _mean([float(row["calibration_error"]) for row in rows])
    abstention_rate = _mean([1.0 if row.get("abstained") else 0.0 for row in rows])
    ood_rate = _mean([1.0 if row.get("ood") else 0.0 for row in rows])
    unsupported_family_rate = _mean(
        [1.0 if row.get("unsupported_family") else 0.0 for row in rows]
    )
    unsupported_abstention_rate = _mean(
        [
            1.0
            if row.get("unsupported_family") and row.get("abstained")
            else 0.0
            for row in rows
        ]
    )
    codex_count = sum(1 for row in rows if row.get("route") == ROUTE_CODEX_TODO)
    audit_count = sum(1 for row in rows if row.get("route") != ROUTE_CODEX_TODO)
    evidence_sources = _unique(
        str(source)
        for row in rows
        for source in _sequence(row.get("evidence_sources"))
    )

    block_reasons: list[str] = []
    if family == "unsupported":
        if count and policy.require_supported_family:
            block_reasons.append("unsupported:unsupported_family_signal")
    elif count:
        min_confidence = policy.threshold("min_calibrated_confidence", family)
        max_entropy = policy.threshold("max_normalized_entropy", family)
        max_calibration = policy.threshold("max_calibration_error", family)
        max_ood = policy.threshold("max_ood_rate", family)
        max_unsupported = policy.threshold("max_unsupported_abstention_rate", family)
        if calibrated_confidence < min_confidence:
            block_reasons.append(f"{family}:calibrated_confidence_below_threshold")
        if normalized_entropy > max_entropy:
            block_reasons.append(f"{family}:entropy_above_threshold")
        if calibration_error > max_calibration:
            block_reasons.append(f"{family}:calibration_error_above_threshold")
        if ood_rate > max_ood:
            block_reasons.append(f"{family}:out_of_distribution_above_threshold")
        if unsupported_abstention_rate > max_unsupported:
            block_reasons.append(
                f"{family}:unsupported_abstention_above_threshold"
            )

    return LegalIRFamilyUncertaintyResult(
        family=family,
        observation_count=count,
        calibrated_confidence=calibrated_confidence,
        raw_confidence=raw_confidence,
        normalized_entropy=normalized_entropy,
        calibration_error=calibration_error,
        abstention_rate=abstention_rate,
        ood_rate=ood_rate,
        unsupported_family_rate=unsupported_family_rate,
        unsupported_abstention_rate=unsupported_abstention_rate,
        codex_todo_generation_count=codex_count,
        hammer_leanstral_audit_count=audit_count,
        block_reasons=tuple(block_reasons),
        evidence_sources=tuple(evidence_sources),
    )


def _guidance_observations(
    guidance: Any,
    *,
    policy: LegalIRUncertaintyConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(_guidance_items(guidance)):
        rows.append(_observation_from_item(item, index=index, policy=policy))
    return rows


def _metric_observations(
    metrics: Any,
    *,
    policy: LegalIRUncertaintyConfig,
) -> list[dict[str, Any]]:
    if metrics is None:
        return []
    rows: list[dict[str, Any]] = []
    for family, block in _family_metric_blocks(metrics).items():
        if not isinstance(block, Mapping):
            continue
        item = dict(block)
        item.setdefault("family", family)
        item.setdefault("source", "family_metrics")
        rows.append(
            _observation_from_item(
                item,
                index=len(rows),
                policy=policy,
                metric_only=True,
            )
        )
    return rows


def _observation_from_item(
    item: Mapping[str, Any],
    *,
    index: int,
    policy: LegalIRUncertaintyConfig,
    metric_only: bool = False,
) -> dict[str, Any]:
    if _looks_like_ambiguity_item(item):
        return _ambiguity_observation_from_item(item, index=index)

    explicit_family = _first_string(item, _FAMILY_KEYS)
    distribution = _distribution_from_item(item)
    if not explicit_family and distribution:
        explicit_family = max(distribution, key=distribution.get)
    family, unsupported = _canonical_family(explicit_family)
    explicit_unsupported = _first_optional_bool(
        item,
        (
            "unsupported_family",
            "unsupported_family_signal",
            "unsupported_legal_ir_family",
        ),
    )
    if explicit_unsupported is not None:
        unsupported = unsupported or explicit_unsupported
    confidence = _confidence_from_item(item, distribution)
    entropy = _entropy_from_item(item, distribution)
    calibration_error = _calibration_error_from_item(item, distribution)
    calibrated_confidence = max(0.0, min(1.0, confidence - calibration_error))
    explicit_abstain = _optional_bool(item.get("abstained"))
    if explicit_abstain is None:
        explicit_abstain = _optional_bool(item.get("abstain"))
    ood = _ood_from_item(item, normalized_entropy=entropy, policy=policy)
    if family in policy.families:
        below_confidence = calibrated_confidence < policy.threshold(
            "min_calibrated_confidence",
            family,
        )
        high_entropy = entropy > policy.threshold("max_normalized_entropy", family)
    else:
        below_confidence = True
        high_entropy = False
    abstained = bool(
        explicit_abstain
        or unsupported
        or ood
        or below_confidence
        or high_entropy
    )
    route = ROUTE_HAMMER_LEANSTRAL_AUDIT if abstained else ROUTE_CODEX_TODO
    evidence_sources = _unique(
        [
            str(item.get("source") or ""),
            "metric_block" if metric_only else "learned_guidance",
            "probability_distribution" if distribution else "",
        ]
    )
    return {
        "abstained": abstained,
        "calibrated_confidence": calibrated_confidence,
        "calibration_error": calibration_error,
        "evidence_sources": evidence_sources,
        "family": family,
        "guidance_id": _guidance_id(item, index=index),
        "normalized_entropy": entropy,
        "ood": ood,
        "raw_confidence": confidence,
        "route": route,
        "unsupported_family": unsupported,
    }


def _guidance_items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        payload = dict(value)
        nested: list[dict[str, Any]] = []
        for key in _GUIDANCE_LIST_KEYS:
            if key in payload and payload.get(key) is not value:
                nested.extend(_guidance_items(payload.get(key)))
        if nested:
            return nested
        if _looks_like_observation(payload):
            return [payload]
        if isinstance(payload.get("view_family_metrics"), Mapping):
            return [
                {"family": family, **dict(block)}
                for family, block in payload["view_family_metrics"].items()
                if isinstance(block, Mapping)
            ]
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items: list[dict[str, Any]] = []
        for item in value:
            items.extend(_guidance_items(item))
        return items
    return []


def _family_metric_blocks(value: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    payload = dict(value)
    for key in (
        "by_legal_ir_family",
        "family_results",
        "view_family_metrics",
        "calibration_by_family",
        "per_family_uncertainty",
    ):
        nested = payload.get(key)
        if not isinstance(nested, Mapping):
            continue
        blocks: dict[str, Mapping[str, Any]] = {}
        for family, block in nested.items():
            if isinstance(block, Mapping):
                blocks[str(family)] = block
            else:
                blocks[str(family)] = {"calibration_error": block}
        return blocks
    if any(key in payload for key in _CALIBRATION_ERROR_KEYS + _CONFIDENCE_KEYS):
        family = _first_string(payload, _FAMILY_KEYS) or "unsupported"
        return {family: payload}
    return {}


def _distribution_from_item(item: Mapping[str, Any]) -> dict[str, float]:
    for key in _DISTRIBUTION_KEYS:
        value = item.get(key)
        if isinstance(value, Mapping):
            distribution = _canonical_distribution(value)
            if distribution:
                return distribution
    heads = item.get("heads")
    if isinstance(heads, Mapping):
        confidences: dict[str, float] = {}
        for head_payload in heads.values():
            if not isinstance(head_payload, Mapping):
                continue
            probabilities = head_payload.get("probabilities")
            if isinstance(probabilities, Mapping):
                for label, probability in probabilities.items():
                    canonical = _canonical_family(str(label))[0]
                    if canonical in LEGAL_IR_EVALUATION_FAMILIES:
                        confidences[canonical] = max(
                            confidences.get(canonical, 0.0),
                            _finite_float(probability, 0.0),
                        )
        return _normalize_distribution(confidences)
    return {}


def _canonical_distribution(value: Mapping[str, Any]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for raw_key, raw_weight in value.items():
        family, unsupported = _canonical_family(str(raw_key))
        if unsupported:
            continue
        weights[family] = weights.get(family, 0.0) + max(
            0.0,
            _finite_float(raw_weight, 0.0),
        )
    return _normalize_distribution(weights)


def _normalize_distribution(value: Mapping[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(weight)) for weight in value.values())
    if total <= 0.0:
        return {}
    return {
        str(key): max(0.0, float(weight)) / total
        for key, weight in sorted(value.items())
        if max(0.0, float(weight)) > 0.0
    }


def _confidence_from_item(
    item: Mapping[str, Any],
    distribution: Mapping[str, float],
) -> float:
    explicit = _first_float(item, _CONFIDENCE_KEYS)
    if explicit is not None:
        return max(0.0, min(1.0, explicit))
    if distribution:
        return max(distribution.values())
    accuracy = _first_float(item, ("accuracy", "coverage"))
    if accuracy is not None:
        return max(0.0, min(1.0, accuracy))
    return 0.0


def _entropy_from_item(
    item: Mapping[str, Any],
    distribution: Mapping[str, float],
) -> float:
    explicit = _first_float(item, _ENTROPY_KEYS)
    if explicit is not None:
        if explicit > 1.0 and distribution:
            return max(0.0, min(1.0, explicit / math.log(len(distribution) or 2)))
        return max(0.0, min(1.0, explicit))
    if not distribution:
        return 1.0
    entropy = 0.0
    for probability in distribution.values():
        if probability > 0.0:
            entropy += probability * -math.log(probability)
    if len(distribution) <= 1:
        return 0.0
    return max(0.0, min(1.0, entropy / math.log(len(distribution))))


def _calibration_error_from_item(
    item: Mapping[str, Any],
    distribution: Mapping[str, float],
) -> float:
    explicit = _first_float(item, _CALIBRATION_ERROR_KEYS)
    if explicit is not None:
        return max(0.0, min(1.0, explicit))
    target = _target_distribution_from_item(item)
    if distribution and target:
        labels = set(distribution) | set(target)
        return max(
            0.0,
            min(
                1.0,
                sum(
                    (
                        float(distribution.get(label, 0.0))
                        - float(target.get(label, 0.0))
                    )
                    ** 2
                    for label in labels
                )
                / max(1, len(labels)),
            ),
        )
    if item.get("correct") is not None:
        confidence = _confidence_from_item(item, distribution)
        target = 1.0 if _optional_bool(item.get("correct")) else 0.0
        return (confidence - target) ** 2
    return 0.0


def _target_distribution_from_item(item: Mapping[str, Any]) -> dict[str, float]:
    for key in _TARGET_DISTRIBUTION_KEYS:
        value = item.get(key)
        if isinstance(value, Mapping):
            distribution = _canonical_distribution(value)
            if distribution:
                return distribution
    return {}


def _ood_from_item(
    item: Mapping[str, Any],
    *,
    normalized_entropy: float,
    policy: LegalIRUncertaintyConfig,
) -> bool:
    for key in _OOD_KEYS:
        value = _optional_bool(item.get(key))
        if value is not None:
            return value
    score = _first_float(item, _OOD_SCORE_KEYS)
    if score is not None and score > policy.ood_score_threshold:
        return True
    return normalized_entropy >= 0.999999


def _canonical_family(value: str) -> tuple[str, bool]:
    raw = str(value or "").strip()
    if not raw:
        return "unsupported", True
    normalized = raw.lower().replace("-", "_")
    normalized = normalized.removeprefix("legal_ir_view_")
    if normalized in _VIEW_FAMILY_ALIASES:
        return _VIEW_FAMILY_ALIASES[normalized], False
    if "." in normalized:
        prefix = normalized.split(".", 1)[0]
        if prefix in _VIEW_FAMILY_ALIASES:
            return _VIEW_FAMILY_ALIASES[prefix], False
    try:
        return canonical_legal_ir_evaluation_family(normalized), False
    except ValueError:
        return "unsupported", True


def _canonical_supported_family(value: str) -> str:
    family, unsupported = _canonical_family(value)
    if unsupported:
        raise ValueError(f"unsupported LegalIR family: {value!r}")
    return family


def _family_thresholds(
    values: Mapping[str, float],
    families: Sequence[str],
    default: float,
    *,
    lower: float,
    upper: float,
) -> dict[str, float]:
    result = {family: max(lower, min(upper, _finite_float(default, lower))) for family in families}
    for key, value in dict(values or {}).items():
        family = _canonical_supported_family(key)
        if family in result:
            result[family] = max(lower, min(upper, _finite_float(value, default)))
    return result


def _looks_like_observation(item: Mapping[str, Any]) -> bool:
    keys = set(item)
    return bool(
        keys.intersection(
            set(_FAMILY_KEYS)
            | set(_CONFIDENCE_KEYS)
            | set(_DISTRIBUTION_KEYS)
            | set(_CALIBRATION_ERROR_KEYS)
            | set(_AMBIGUITY_KEYS)
            | {"guidance_id", "task_id", "schema_version", "source"}
        )
    )


def _guidance_id(item: Mapping[str, Any], *, index: int) -> str:
    for key in ("guidance_id", "ambiguity_id", "task_id", "obligation_id", "sample_id", "id"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return "uncertainty-guidance-" + _hash_json({"index": index, "item": item})[:20]


def _looks_like_ambiguity_item(item: Mapping[str, Any]) -> bool:
    if item.get("legal_ir_ambiguity") is True:
        return True
    schema = str(item.get("schema_version") or "")
    if schema.startswith("legal-ir-ambiguity"):
        return True
    return bool(set(item).intersection(_AMBIGUITY_KEYS)) and bool(
        item.get("ambiguity_id") or item.get("ambiguity_kind")
    )


def _ambiguity_observation_from_item(
    item: Mapping[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    family, unsupported = _canonical_family(
        _first_string(item, _FAMILY_KEYS)
        or _ambiguity_target_view(item)
        or "deontic"
    )
    raw_confidence = max(0.0, min(1.0, _finite_float(item.get("confidence"), 0.0)))
    return {
        "abstained": True,
        "calibrated_confidence": 0.0,
        "calibration_error": 1.0,
        "evidence_sources": ("legal_ir_ambiguity",),
        "family": family,
        "guidance_id": _guidance_id(item, index=index),
        "normalized_entropy": 1.0,
        "ood": True,
        "raw_confidence": raw_confidence,
        "route": ROUTE_HAMMER_LEANSTRAL_AUDIT,
        "unsupported_family": True if unsupported else bool(
            item.get("learned_label") or item.get("arbitrary_learned_label")
        ),
    }


def _ambiguity_target_view(item: Mapping[str, Any]) -> str:
    for key in ("competing_parses", "unsupported_interpretations"):
        for candidate in _sequence(item.get(key)):
            if not isinstance(candidate, Mapping):
                continue
            view = str(
                candidate.get("target_view")
                or candidate.get("target_component")
                or candidate.get("legal_ir_view")
                or ""
            ).strip()
            if view:
                return view
    return ""


def _first_string(item: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    target_view = (
        item.get("legal_ir_view")
        or item.get("target_view")
        or item.get("target_component")
        or item.get("compiler_surface")
    )
    return str(target_view or "").strip()


def _first_float(item: Mapping[str, Any], keys: Iterable[str]) -> Optional[float]:
    for key in keys:
        if key not in item:
            continue
        value = _finite_float(item.get(key), math.nan)
        if math.isfinite(value):
            return value
    return None


def _optional_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "abstained", "unsupported"}:
        return True
    if text in {"0", "false", "no", "n", "off", "passed", "supported"}:
        return False
    return None


def _first_optional_bool(item: Mapping[str, Any], keys: Iterable[str]) -> Optional[bool]:
    for key in keys:
        if key not in item:
            continue
        value = _optional_bool(item.get(key))
        if value is not None:
            return value
    return None


def _finite_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _hash_json(value: Any) -> str:
    payload = json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_MAX_CALIBRATION_ERROR",
    "DEFAULT_MAX_NORMALIZED_ENTROPY",
    "DEFAULT_MAX_OOD_RATE",
    "DEFAULT_MAX_UNSUPPORTED_ABSTENTION_RATE",
    "DEFAULT_MIN_CALIBRATED_CONFIDENCE",
    "LEGAL_IR_UNCERTAINTY_SCHEMA_VERSION",
    "ROUTE_CODEX_TODO",
    "ROUTE_HAMMER_LEANSTRAL_AUDIT",
    "LegalIRFamilyUncertaintyResult",
    "LegalIRUncertaintyConfig",
    "LegalIRUncertaintyReport",
    "evaluate_legal_ir_uncertainty",
    "legal_ir_uncertainty_promotion_gate",
    "route_learned_guidance_by_uncertainty",
]
