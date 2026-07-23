"""Constrained per-family objective balancing for LegalIR training.

This module keeps LegalIR objective tuning from collapsing into a single macro
score.  Every required semantic family has to expose the learned IR, compiler
IR, proof, reconstruction, and anti-copy signals before an update can pass.
Soft objective weights are adapted per family, but structural, provenance,
source-copy, Hammer trust, and frozen-canary signals are hard guardrails and are
never converted into tunable reward terms.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Optional

from .legal_ir_family_evaluator import (
    LEGAL_IR_EVALUATION_FAMILIES,
    canonical_legal_ir_evaluation_family,
)
from .legal_ir_semantic_metrics import (
    SemanticEquivalenceComparisonReport,
    SemanticEquivalenceConfig,
    compare_legal_ir_semantic_equivalence,
)


LEGAL_IR_OBJECTIVE_BALANCER_SCHEMA_VERSION: Final = (
    "legal-ir-per-family-constrained-objective-v1"
)

LEARNED_CE: Final = "learned_cross_entropy_loss"
LEARNED_COSINE: Final = "learned_cosine_similarity"
COMPILER_CE: Final = "compiler_cross_entropy_loss"
COMPILER_COSINE: Final = "compiler_cosine_similarity"
PROOF_VALIDITY: Final = "proof_validity_success_rate"
RECONSTRUCTION: Final = "reconstruction_success_rate"
ANTI_COPY: Final = "anti_copy_penalty"

SOFT_OBJECTIVE_METRICS: Final[tuple[str, ...]] = (
    LEARNED_CE,
    LEARNED_COSINE,
    COMPILER_CE,
    COMPILER_COSINE,
    PROOF_VALIDITY,
    RECONSTRUCTION,
    ANTI_COPY,
)

LOWER_IS_BETTER_SOFT_METRICS: Final = frozenset(
    {LEARNED_CE, COMPILER_CE, ANTI_COPY}
)
HIGHER_IS_BETTER_SOFT_METRICS: Final = frozenset(
    {LEARNED_COSINE, COMPILER_COSINE, PROOF_VALIDITY, RECONSTRUCTION}
)

_SOFT_ALIASES: Final[Mapping[str, tuple[str, ...]]] = {
    LEARNED_CE: (
        "learned_cross_entropy_loss",
        "autoencoder_cross_entropy_loss",
        "legal_ir_view_cross_entropy_loss",
        "cross_entropy_loss",
    ),
    LEARNED_COSINE: (
        "learned_cosine_similarity",
        "autoencoder_cosine_similarity",
        "embedding_cosine_similarity",
        "cosine_similarity",
    ),
    COMPILER_CE: (
        "compiler_cross_entropy_loss",
        "compiler_ir_cross_entropy_loss",
        "ir_cross_entropy_loss",
    ),
    COMPILER_COSINE: (
        "compiler_cosine_similarity",
        "compiler_ir_cosine_similarity",
        "ir_cosine_similarity",
    ),
    PROOF_VALIDITY: (
        "proof_validity_success_rate",
        "symbolic_validity_success_rate",
        "hammer_proof_success_rate",
    ),
    RECONSTRUCTION: (
        "reconstruction_success_rate",
        "round_trip_reconstruction_success_rate",
        "hammer_reconstruction_success_rate",
    ),
    ANTI_COPY: (
        "anti_copy_penalty",
        "source_copy_penalty",
        "source_copy_reward_hack_penalty",
        "round_trip_source_copy_guardrail_loss",
    ),
}

_HARD_GUARDRAIL_ALIASES: Final[Mapping[str, tuple[str, ...]]] = {
    "structural": (
        "structural_validity_success_rate",
        "structural_reconstruction_success_rate",
        "structural_text_reconstruction_loss",
        "round_trip_structural_reconstruction_loss",
    ),
    "provenance": (
        "provenance_preservation_success_rate",
        "provenance_alignment_success_rate",
        "provenance_consistency_success_rate",
        "missing_provenance_id_penalty",
        "provenance_regression_penalty",
    ),
    "source_copy": (
        "source_copy_penalty",
        "source_copy_reward_hack_penalty",
        "round_trip_source_copy_guardrail_loss",
        "source_copy_guardrail_passed",
    ),
    "hammer_trust": (
        "hammer_trusted_success_rate",
        "trusted_hammer_success_rate",
        "hammer_backend_unavailable_ratio",
        "hammer_trust_guardrail_passed",
    ),
    "frozen_canary": (
        "fixed_canary_guardrail_passed",
        "frozen_canary_guardrail_passed",
        "canary_source_copy_penalty",
        "canary_symbolic_validity_success_rate",
        "canary_structural_validity_success_rate",
    ),
}

_LOWER_IS_BETTER_GUARDRAIL_SUFFIXES: Final = (
    "_loss",
    "_penalty",
    "_failure_ratio",
    "_unavailable_ratio",
)


@dataclass(frozen=True, slots=True)
class ObjectiveWeightBounds:
    """Closed interval for one adaptive soft objective weight."""

    minimum: float
    maximum: float
    default: float

    def __post_init__(self) -> None:
        for name in ("minimum", "maximum", "default"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, value)
        if self.maximum < self.minimum:
            raise ValueError("maximum must be greater than or equal to minimum")
        if not self.minimum <= self.default <= self.maximum:
            raise ValueError("default must be inside the weight bounds")

    def clamp(self, value: Any) -> float:
        number = _finite_float(value, self.default)
        return min(self.maximum, max(self.minimum, number))

    def to_dict(self) -> dict[str, float]:
        return {
            "default": round(self.default, 12),
            "maximum": round(self.maximum, 12),
            "minimum": round(self.minimum, 12),
        }


DEFAULT_SOFT_WEIGHT_BOUNDS: Final[Mapping[str, ObjectiveWeightBounds]] = {
    LEARNED_CE: ObjectiveWeightBounds(0.50, 3.00, 1.00),
    LEARNED_COSINE: ObjectiveWeightBounds(0.50, 3.00, 1.00),
    COMPILER_CE: ObjectiveWeightBounds(0.75, 4.00, 1.25),
    COMPILER_COSINE: ObjectiveWeightBounds(0.75, 4.00, 1.25),
    PROOF_VALIDITY: ObjectiveWeightBounds(1.00, 5.00, 2.00),
    RECONSTRUCTION: ObjectiveWeightBounds(0.75, 4.00, 1.50),
    ANTI_COPY: ObjectiveWeightBounds(1.00, 5.00, 2.00),
}


@dataclass(frozen=True, slots=True)
class LegalIRObjectiveBalancerConfig:
    """Policy for constrained per-family objective evaluation."""

    families: tuple[str, ...] = LEGAL_IR_EVALUATION_FAMILIES
    soft_weight_bounds: Mapping[str, ObjectiveWeightBounds] = field(
        default_factory=lambda: dict(DEFAULT_SOFT_WEIGHT_BOUNDS)
    )
    adaptation_rate: float = 0.25
    metric_tolerance: float = 0.0
    minimum_family_improvement: float = 0.0
    require_complete_soft_metrics: bool = True
    require_hard_guardrail_evidence: bool = True
    require_semantic_equivalence_evidence: bool = True

    def __post_init__(self) -> None:
        families = tuple(
            canonical_legal_ir_evaluation_family(family) for family in self.families
        )
        if not families:
            raise ValueError("at least one LegalIR family is required")
        if len(set(families)) != len(families):
            raise ValueError("families must be unique after canonicalization")
        object.__setattr__(self, "families", families)

        bounds: dict[str, ObjectiveWeightBounds] = {}
        for metric in SOFT_OBJECTIVE_METRICS:
            raw = self.soft_weight_bounds.get(
                metric,
                DEFAULT_SOFT_WEIGHT_BOUNDS[metric],
            )
            if isinstance(raw, ObjectiveWeightBounds):
                bounds[metric] = raw
            elif isinstance(raw, Mapping):
                bounds[metric] = ObjectiveWeightBounds(
                    minimum=raw.get("minimum", raw.get("min", 0.0)),
                    maximum=raw.get("maximum", raw.get("max", 0.0)),
                    default=raw.get("default", 0.0),
                )
            else:
                raise TypeError(f"invalid weight bounds for {metric!r}")
        object.__setattr__(self, "soft_weight_bounds", bounds)

        for name in ("adaptation_rate", "metric_tolerance", "minimum_family_improvement"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class FamilyObjectiveResult:
    """Objective accounting for exactly one LegalIR family."""

    family: str
    before_metrics: Mapping[str, float]
    after_metrics: Mapping[str, float]
    metric_deltas: Mapping[str, float]
    before_objective: float
    after_objective: float
    objective_improvement: float
    soft_weights_before: Mapping[str, float]
    soft_weights_after: Mapping[str, float]
    missing_soft_metrics: tuple[str, ...] = ()
    hard_guardrail_regressions: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )
    missing_hard_guardrails: tuple[str, ...] = ()
    semantic_equivalence: Mapping[str, Any] = field(default_factory=dict)
    missing_semantic_equivalence_metrics: tuple[str, ...] = ()
    semantic_equivalence_regressions: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )
    semantic_equivalence_threshold_failures: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )
    semantic_ce_cosine_disagreement: bool = False

    @property
    def status(self) -> str:
        if self.hard_guardrail_regressions:
            return "hard_guardrail_regressed"
        if self.missing_hard_guardrails:
            return "hard_guardrail_evidence_missing"
        if self.missing_semantic_equivalence_metrics:
            return "semantic_equivalence_evidence_missing"
        if self.semantic_equivalence_threshold_failures:
            return "semantic_equivalence_threshold_failed"
        if self.semantic_equivalence_regressions:
            return "semantic_equivalence_regressed"
        if self.missing_soft_metrics:
            return "soft_metric_evidence_missing"
        if self.objective_improvement < 0.0:
            return "soft_objective_regressed"
        return "passed"

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "after_metrics": _round_mapping(self.after_metrics),
            "after_objective": round(self.after_objective, 12),
            "before_metrics": _round_mapping(self.before_metrics),
            "before_objective": round(self.before_objective, 12),
            "family": self.family,
            "hard_guardrail_regressions": _json_ready(self.hard_guardrail_regressions),
            "metric_deltas": _round_mapping(self.metric_deltas),
            "missing_hard_guardrails": list(self.missing_hard_guardrails),
            "missing_semantic_equivalence_metrics": list(
                self.missing_semantic_equivalence_metrics
            ),
            "missing_soft_metrics": list(self.missing_soft_metrics),
            "objective_improvement": round(self.objective_improvement, 12),
            "passed": self.passed,
            "semantic_ce_cosine_disagreement": self.semantic_ce_cosine_disagreement,
            "semantic_equivalence": _json_ready(self.semantic_equivalence),
            "semantic_equivalence_regressions": _json_ready(
                self.semantic_equivalence_regressions
            ),
            "semantic_equivalence_threshold_failures": _json_ready(
                self.semantic_equivalence_threshold_failures
            ),
            "soft_weights_after": _round_mapping(self.soft_weights_after),
            "soft_weights_before": _round_mapping(self.soft_weights_before),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class LegalIRObjectiveBalanceReport:
    """Admission and weight-adaptation report for one candidate update."""

    family_results: Mapping[str, FamilyObjectiveResult]
    block_reasons: tuple[str, ...]
    ignored_weight_keys: tuple[str, ...]
    macro_soft_improvement: float
    worst_family_improvement: float
    objective_id: str
    semantic_equivalence_report: Optional[SemanticEquivalenceComparisonReport] = None
    schema_version: str = LEGAL_IR_OBJECTIVE_BALANCER_SCHEMA_VERSION

    @property
    def failed_families(self) -> tuple[str, ...]:
        return tuple(
            family
            for family, result in self.family_results.items()
            if not result.passed
        )

    @property
    def accepted(self) -> bool:
        return not self.block_reasons and not self.failed_families

    @property
    def adapted_weights(self) -> dict[str, dict[str, float]]:
        return {
            family: dict(result.soft_weights_after)
            for family, result in self.family_results.items()
        }

    @property
    def macro_score_available(self) -> bool:
        return not self.failed_families

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "adapted_soft_weights": {
                family: _round_mapping(weights)
                for family, weights in self.adapted_weights.items()
            },
            "block_reasons": list(self.block_reasons),
            "failed_families": list(self.failed_families),
            "families": list(self.family_results),
            "family_count": len(self.family_results),
            "family_results": {
                family: result.to_dict()
                for family, result in self.family_results.items()
            },
            "guardrail_policy": {
                "hard_guardrails": sorted(_HARD_GUARDRAIL_ALIASES),
                "soft_objective_metrics": list(SOFT_OBJECTIVE_METRICS),
                "weights_apply_to_hard_guardrails": False,
            },
            "ignored_weight_keys": list(self.ignored_weight_keys),
            "macro_score_available": self.macro_score_available,
            "macro_soft_improvement": round(self.macro_soft_improvement, 12),
            "objective_id": self.objective_id,
            "semantic_equivalence_gate": self.semantic_equivalence_report.to_dict()
            if self.semantic_equivalence_report is not None
            else {},
            "schema_version": self.schema_version,
            "status": "accepted" if self.accepted else "blocked",
            "worst_family_improvement": round(self.worst_family_improvement, 12),
        }


class LegalIRObjectiveBalancer:
    """Evaluate and adapt bounded soft objective weights per LegalIR family."""

    def __init__(
        self,
        config: Optional[LegalIRObjectiveBalancerConfig] = None,
    ) -> None:
        self.config = config or LegalIRObjectiveBalancerConfig()

    def evaluate(
        self,
        baseline_metrics: Mapping[str, Any],
        candidate_metrics: Mapping[str, Any],
        *,
        current_weights: Optional[Mapping[str, Any]] = None,
    ) -> LegalIRObjectiveBalanceReport:
        baseline = _extract_family_payload(baseline_metrics, self.config.families)
        candidate = _extract_family_payload(candidate_metrics, self.config.families)
        semantic_report = compare_legal_ir_semantic_equivalence(
            baseline_metrics,
            candidate_metrics,
            config=SemanticEquivalenceConfig(
                families=self.config.families,
                regression_tolerance=self.config.metric_tolerance,
                require_complete_metrics=(
                    self.config.require_semantic_equivalence_evidence
                ),
            ),
        )
        hard_baseline = _extract_global_guardrails(baseline_metrics)
        hard_candidate = _extract_global_guardrails(candidate_metrics)
        weights, ignored_weight_keys = _normalize_current_weights(
            current_weights,
            self.config,
        )

        family_results: dict[str, FamilyObjectiveResult] = {}
        for family in self.config.families:
            before_soft = _extract_soft_metrics(baseline.get(family, {}))
            after_soft = _extract_soft_metrics(candidate.get(family, {}))
            before_hard = {
                **hard_baseline,
                **_extract_hard_guardrails(baseline.get(family, {})),
            }
            after_hard = {
                **hard_candidate,
                **_extract_hard_guardrails(candidate.get(family, {})),
            }
            missing_soft = tuple(
                metric
                for metric in SOFT_OBJECTIVE_METRICS
                if metric not in before_soft or metric not in after_soft
            )
            missing_hard = _missing_guardrail_groups(before_hard, after_hard)
            hard_regressions = _hard_guardrail_regressions(
                before_hard,
                after_hard,
                tolerance=self.config.metric_tolerance,
            )
            semantic_family = semantic_report.family_results[family]
            family_weights = weights[family]
            before_objective = _soft_objective(before_soft, family_weights)
            after_objective = _soft_objective(after_soft, family_weights)
            deltas = {
                metric: _metric_improvement(
                    before_soft.get(metric),
                    after_soft.get(metric),
                    metric,
                )
                for metric in SOFT_OBJECTIVE_METRICS
                if metric in before_soft and metric in after_soft
            }
            adapted = _adapt_family_weights(
                family_weights,
                after_soft,
                deltas,
                self.config,
            )
            family_results[family] = FamilyObjectiveResult(
                family=family,
                before_metrics=before_soft,
                after_metrics=after_soft,
                metric_deltas=deltas,
                before_objective=before_objective,
                after_objective=after_objective,
                objective_improvement=before_objective - after_objective,
                soft_weights_before=family_weights,
                soft_weights_after=adapted,
                missing_soft_metrics=missing_soft
                if self.config.require_complete_soft_metrics
                else (),
                hard_guardrail_regressions=hard_regressions,
                missing_hard_guardrails=missing_hard
                if self.config.require_hard_guardrail_evidence
                else (),
                semantic_equivalence=semantic_family.to_dict(),
                missing_semantic_equivalence_metrics=semantic_family.missing_metrics
                if self.config.require_semantic_equivalence_evidence
                else (),
                semantic_equivalence_regressions=semantic_family.regressions,
                semantic_equivalence_threshold_failures=(
                    semantic_family.threshold_failures
                ),
                semantic_ce_cosine_disagreement=semantic_family.disagreement,
            )

        improvements = [
            result.objective_improvement for result in family_results.values()
        ]
        macro = sum(improvements) / len(improvements) if improvements else 0.0
        worst = min(improvements) if improvements else 0.0
        block_reasons = _block_reasons(family_results, self.config)
        descriptor = {
            "after": {
                family: result.after_metrics
                for family, result in family_results.items()
            },
            "before": {
                family: result.before_metrics
                for family, result in family_results.items()
            },
            "families": self.config.families,
            "weights": {
                family: result.soft_weights_before
                for family, result in family_results.items()
            },
        }
        return LegalIRObjectiveBalanceReport(
            family_results=family_results,
            block_reasons=tuple(
                list(block_reasons)
                + [
                    reason
                    for reason in semantic_report.block_reasons
                    if reason not in block_reasons
                ]
            ),
            ignored_weight_keys=ignored_weight_keys,
            macro_soft_improvement=macro,
            worst_family_improvement=worst,
            objective_id="lir-per-family-objective-" + _stable_hash(descriptor)[:24],
            semantic_equivalence_report=semantic_report,
        )


def evaluate_constrained_legal_ir_objective(
    baseline_metrics: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
    *,
    current_weights: Optional[Mapping[str, Any]] = None,
    config: Optional[LegalIRObjectiveBalancerConfig] = None,
) -> LegalIRObjectiveBalanceReport:
    """Convenience wrapper for one constrained objective-balancing run."""

    return LegalIRObjectiveBalancer(config).evaluate(
        baseline_metrics,
        candidate_metrics,
        current_weights=current_weights,
    )


def balance_legal_ir_objective(
    baseline_metrics: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
    *,
    current_weights: Optional[Mapping[str, Any]] = None,
    config: Optional[LegalIRObjectiveBalancerConfig] = None,
) -> LegalIRObjectiveBalanceReport:
    """Compatibility alias matching the backlog wording."""

    return evaluate_constrained_legal_ir_objective(
        baseline_metrics,
        candidate_metrics,
        current_weights=current_weights,
        config=config,
    )


def _extract_family_payload(
    payload: Mapping[str, Any],
    families: Sequence[str],
) -> dict[str, dict[str, Any]]:
    source = _mapping_payload(payload)
    nested = source.get("view_family_metrics")
    if not isinstance(nested, Mapping):
        nested = source.get("legal_ir_view_family_metrics")
    by_family: dict[str, dict[str, Any]] = {family: {} for family in families}
    if isinstance(nested, Mapping):
        for raw_family, raw_metrics in nested.items():
            family = _canonical_family_or_empty(str(raw_family))
            if family in by_family and isinstance(raw_metrics, Mapping):
                by_family[family].update(dict(raw_metrics))

    flat = source.get("flat_metrics")
    if isinstance(flat, Mapping):
        _merge_flat_metrics(flat, by_family)
    _merge_flat_metrics(source, by_family)

    losses = source.get("legal_ir_losses")
    if isinstance(losses, Mapping):
        _merge_flat_metrics(losses, by_family)
    return by_family


def _merge_flat_metrics(
    flat: Mapping[str, Any],
    by_family: dict[str, dict[str, Any]],
) -> None:
    for key, value in flat.items():
        name = str(key)
        prefix = "legal_ir_view_family_"
        if not name.startswith(prefix):
            continue
        remainder = name.removeprefix(prefix)
        for raw_family in sorted(by_family, key=len, reverse=True):
            aliases = (raw_family, "kg") if raw_family == "knowledge_graphs" else (raw_family,)
            for alias in aliases:
                marker = f"{alias}_"
                if remainder.startswith(marker):
                    metric = remainder.removeprefix(marker)
                    by_family[raw_family][metric] = value
                    break


def _extract_soft_metrics(payload: Mapping[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for canonical, aliases in _SOFT_ALIASES.items():
        for alias in aliases:
            if alias in payload:
                number = _maybe_float(payload[alias])
                if number is not None:
                    metrics[canonical] = max(0.0, number)
                    break
    return metrics


def _extract_global_guardrails(payload: Mapping[str, Any]) -> dict[str, float | bool]:
    source = _mapping_payload(payload)
    guardrails = _extract_hard_guardrails(source)
    losses = source.get("legal_ir_losses")
    if isinstance(losses, Mapping):
        guardrails.update(_extract_hard_guardrails(losses))
    flat = source.get("flat_metrics")
    if isinstance(flat, Mapping):
        guardrails.update(_extract_hard_guardrails(flat))
    return guardrails


def _extract_hard_guardrails(payload: Mapping[str, Any]) -> dict[str, float | bool]:
    guardrails: dict[str, float | bool] = {}
    for group, aliases in _HARD_GUARDRAIL_ALIASES.items():
        for alias in aliases:
            if alias not in payload:
                continue
            key = f"{group}:{alias}"
            raw = payload[alias]
            if isinstance(raw, bool):
                guardrails[key] = raw
            else:
                number = _maybe_float(raw)
                if number is not None:
                    guardrails[key] = max(0.0, number)
    return guardrails


def _missing_guardrail_groups(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[str, ...]:
    missing: list[str] = []
    for group in _HARD_GUARDRAIL_ALIASES:
        if not any(key.startswith(f"{group}:") for key in baseline) or not any(
            key.startswith(f"{group}:") for key in candidate
        ):
            missing.append(group)
    return tuple(missing)


def _hard_guardrail_regressions(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    tolerance: float,
) -> dict[str, Mapping[str, Any]]:
    regressions: dict[str, Mapping[str, Any]] = {}
    for key in sorted(set(baseline) & set(candidate)):
        before = baseline[key]
        after = candidate[key]
        metric_name = key.split(":", 1)[1]
        if isinstance(after, bool) or isinstance(before, bool):
            if bool(before) and not bool(after):
                regressions[key] = {"before": bool(before), "after": bool(after)}
            continue
        before_number = _maybe_float(before)
        after_number = _maybe_float(after)
        if before_number is None or after_number is None:
            continue
        if _metric_lower_is_better(metric_name):
            regression = after_number - before_number
        else:
            regression = before_number - after_number
        if regression > tolerance:
            regressions[key] = {
                "after": round(after_number, 12),
                "before": round(before_number, 12),
                "regression": round(regression, 12),
            }
    return regressions


def _normalize_current_weights(
    current_weights: Optional[Mapping[str, Any]],
    config: LegalIRObjectiveBalancerConfig,
) -> tuple[dict[str, dict[str, float]], tuple[str, ...]]:
    source = dict(current_weights or {})
    ignored: set[str] = set()
    per_family_mode = any(
        _canonical_family_or_empty(str(key)) in config.families for key in source
    )
    weights: dict[str, dict[str, float]] = {}
    for family in config.families:
        if per_family_mode:
            raw_family = source.get(family)
            if raw_family is None and family == "knowledge_graphs":
                raw_family = source.get("kg")
            raw_weights = dict(raw_family or {}) if isinstance(raw_family, Mapping) else {}
        else:
            raw_weights = source
        family_weights: dict[str, float] = {}
        for metric in SOFT_OBJECTIVE_METRICS:
            family_weights[metric] = config.soft_weight_bounds[metric].clamp(
                raw_weights.get(metric, config.soft_weight_bounds[metric].default)
            )
        weights[family] = family_weights
        for key in raw_weights:
            if key not in SOFT_OBJECTIVE_METRICS:
                ignored.add(f"{family}:{key}" if per_family_mode else str(key))
    if per_family_mode:
        for key in source:
            family = _canonical_family_or_empty(str(key))
            if family not in config.families:
                ignored.add(str(key))
    return weights, tuple(sorted(ignored))


def _adapt_family_weights(
    weights: Mapping[str, float],
    after_metrics: Mapping[str, float],
    deltas: Mapping[str, float],
    config: LegalIRObjectiveBalancerConfig,
) -> dict[str, float]:
    component_losses = {
        metric: _component_loss(metric, value)
        for metric, value in after_metrics.items()
        if metric in SOFT_OBJECTIVE_METRICS
    }
    mean_loss = (
        sum(component_losses.values()) / len(component_losses)
        if component_losses
        else 0.0
    )
    adapted: dict[str, float] = {}
    for metric in SOFT_OBJECTIVE_METRICS:
        current = float(weights[metric])
        pressure = component_losses.get(metric, mean_loss) - mean_loss
        if deltas.get(metric, 0.0) < 0.0:
            pressure += abs(float(deltas[metric]))
        proposed = current * (1.0 + config.adaptation_rate * pressure)
        adapted[metric] = config.soft_weight_bounds[metric].clamp(proposed)
    return adapted


def _soft_objective(
    metrics: Mapping[str, float],
    weights: Mapping[str, float],
) -> float:
    total = 0.0
    for metric in SOFT_OBJECTIVE_METRICS:
        if metric in metrics:
            total += float(weights[metric]) * _component_loss(metric, metrics[metric])
    return total


def _component_loss(metric: str, value: float) -> float:
    number = max(0.0, float(value))
    if metric in {LEARNED_CE, COMPILER_CE}:
        return min(1.0, number / 3.0)
    if metric == ANTI_COPY:
        return min(1.0, number)
    return min(1.0, max(0.0, 1.0 - number))


def _metric_improvement(before: Any, after: Any, metric: str) -> float:
    before_number = _maybe_float(before)
    after_number = _maybe_float(after)
    if before_number is None or after_number is None:
        return 0.0
    if metric in LOWER_IS_BETTER_SOFT_METRICS:
        return before_number - after_number
    return after_number - before_number


def _block_reasons(
    results: Mapping[str, FamilyObjectiveResult],
    config: LegalIRObjectiveBalancerConfig,
) -> tuple[str, ...]:
    reasons: list[str] = []
    for family, result in results.items():
        if result.missing_soft_metrics:
            reasons.append(f"{family}:soft_metric_evidence_missing")
        if result.missing_hard_guardrails:
            reasons.append(f"{family}:hard_guardrail_evidence_missing")
        if result.hard_guardrail_regressions:
            reasons.append(f"{family}:hard_guardrail_regressed")
        if result.missing_semantic_equivalence_metrics:
            reasons.append(f"{family}:semantic_equivalence_evidence_missing")
        if result.semantic_equivalence_threshold_failures:
            reasons.append(f"{family}:semantic_equivalence_threshold_failed")
        if result.semantic_equivalence_regressions:
            reasons.append(f"{family}:semantic_equivalence_regressed")
        if result.semantic_ce_cosine_disagreement:
            reasons.append(f"{family}:ce_cosine_semantic_disagreement")
        if result.objective_improvement < float(config.minimum_family_improvement):
            reasons.append(f"{family}:soft_objective_regressed")
    return tuple(reasons)


def _mapping_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        raw = value.to_dict()
        return dict(raw) if isinstance(raw, Mapping) else {}
    return dict(value or {})


def _canonical_family_or_empty(value: str) -> str:
    try:
        return canonical_legal_ir_evaluation_family(value)
    except ValueError:
        return ""


def _maybe_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_float(value: Any, default: float) -> float:
    number = _maybe_float(value)
    return float(default) if number is None else number


def _metric_lower_is_better(name: str) -> bool:
    normalized = str(name or "")
    return normalized.endswith(_LOWER_IS_BETTER_GUARDRAIL_SUFFIXES) or (
        "source_copy" in normalized and "success_rate" not in normalized
    )


def _round_mapping(values: Mapping[str, Any]) -> dict[str, float]:
    rounded: dict[str, float] = {}
    for key, value in sorted(values.items()):
        number = _maybe_float(value)
        if number is not None:
            rounded[str(key)] = round(number, 12)
    return rounded


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, float):
        return round(value, 12) if math.isfinite(value) else 0.0
    return value


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        _json_ready(value),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "ANTI_COPY",
    "COMPILER_CE",
    "COMPILER_COSINE",
    "DEFAULT_SOFT_WEIGHT_BOUNDS",
    "HIGHER_IS_BETTER_SOFT_METRICS",
    "LEARNED_CE",
    "LEARNED_COSINE",
    "LEGAL_IR_OBJECTIVE_BALANCER_SCHEMA_VERSION",
    "LOWER_IS_BETTER_SOFT_METRICS",
    "PROOF_VALIDITY",
    "RECONSTRUCTION",
    "SOFT_OBJECTIVE_METRICS",
    "FamilyObjectiveResult",
    "LegalIRObjectiveBalanceReport",
    "LegalIRObjectiveBalancer",
    "LegalIRObjectiveBalancerConfig",
    "ObjectiveWeightBounds",
    "balance_legal_ir_objective",
    "evaluate_constrained_legal_ir_objective",
]
