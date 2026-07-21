"""Production drift monitor for promoted LegalIR learned guidance.

Promoted learned guidance is deliberately reversible.  This module consumes
source-free production summaries and compares them with an immutable baseline.
When any configured drift threshold is exceeded it emits deterministic rollback
evidence, marks active promoted guidance as disabled, and opens operator TODO
records that can be routed into the existing Codex queue.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final


LEGAL_IR_DRIFT_MONITOR_SCHEMA_VERSION: Final = "legal-ir-drift-monitor-v1"
LEGAL_IR_DRIFT_ROLLBACK_TODO_SCHEMA_VERSION: Final = (
    "legal-ir-drift-rollback-todo-v1"
)
LEGAL_IR_DRIFT_ROLLBACK_DECISION_SCHEMA_VERSION: Final = (
    "legal-ir-drift-rollback-decision-v1"
)
PRODUCTION_DRIFT_AND_ROLLBACK_HARD_GUARDRAIL: Final = (
    "learned_guidance_is_reversible"
)

DEFAULT_FAMILY_METRICS_HIGHER_IS_BETTER: Final = frozenset(
    {
        "autoencoder_cosine_similarity",
        "compiler_ir_cosine",
        "compiler_ir_cosine_similarity",
        "hammer_proof_success_rate",
        "hammer_reconstruction_success_rate",
        "ir_cosine_similarity",
        "reconstruction_success_rate",
        "semantic_equivalence",
        "semantic_equivalence_rate",
        "structural_validity",
        "symbolic_validity",
        "symbolic_validity_success_rate",
    }
)
DEFAULT_FAMILY_METRICS_LOWER_IS_BETTER: Final = frozenset(
    {
        "autoencoder_cross_entropy_loss",
        "compiler_ir_cross_entropy_loss",
        "hammer_failure_rate",
        "ir_cross_entropy_loss",
        "proof_failure_rate",
        "reconstruction_failure_rate",
        "source_copy_penalty",
        "source_copy_reward_hack_penalty",
    }
)

_PROMOTION_KEYS: Final = (
    "latest_legal_ir_learned_guidance_promotion",
    "legal_ir_learned_guidance_promotion",
    "latest_learned_representation_promotion",
    "learned_representation_promotion",
    "latest_representation_promotion",
    "representation_promotion",
)
_DISTRIBUTION_KEYS: Final = (
    "production_distribution",
    "family_distribution",
    "target_family_distribution",
    "legal_ir_family_distribution",
    "view_family_distribution",
)
_FAMILY_METRIC_KEYS: Final = (
    "family_metrics",
    "view_family_metrics",
    "legal_ir_view_family_metrics",
    "metrics_by_family",
)
_RESOURCE_KEYS: Final = (
    "resource_pressure",
    "resource_snapshot",
    "runtime_resources",
    "latest_resource_snapshot",
    "scheduler_pressure",
    "resource_degradation",
)
_REJECTION_KEYS: Final = (
    "prompt_rejections",
    "prompt_security",
    "premise_rejections",
    "premise_security",
    "premise_selection",
)


def _canonical_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return round(value, 12)
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_json_value(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _canonical_json_value(value.to_dict())
    return str(value)


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(
        _canonical_json_value(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_rate(value: Any) -> float | None:
    result = _finite_float(value)
    if result is None:
        return None
    if result > 1.0 and result <= 100.0:
        result /= 100.0
    return max(0.0, min(1.0, result))


def _mapping(value: Any) -> Mapping[str, Any]:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _string(value: Any) -> str:
    return str(value or "").strip()


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = _string(value)
        return (text,) if text else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(_string(item) for item in value if _string(item))
    text = _string(value)
    return (text,) if text else ()


def _first_mapping(payload: Mapping[str, Any], keys: Sequence[str]) -> Mapping[str, Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _first_number(payload: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        if key in payload:
            value = _finite_float(payload.get(key))
            if value is not None:
                return value
    return None


def _rate_from_counts(payload: Mapping[str, Any]) -> float | None:
    rejected = _first_number(
        payload,
        (
            "rejected_count",
            "blocked_count",
            "rejection_count",
            "prompt_rejected_count",
            "premise_rejected_count",
        ),
    )
    total = _first_number(
        payload,
        (
            "total_count",
            "evaluated_count",
            "sample_count",
            "prompt_count",
            "premise_count",
        ),
    )
    if rejected is None or total is None or total <= 0:
        return None
    return max(0.0, min(1.0, rejected / total))


def _normalise_distribution(payload: Mapping[str, Any]) -> dict[str, float]:
    raw: Any = None
    for key in _DISTRIBUTION_KEYS:
        if isinstance(payload.get(key), Mapping):
            raw = payload[key]
            break
    if raw is None:
        for key in ("family_counts", "view_family_counts", "legal_ir_family_counts"):
            if isinstance(payload.get(key), Mapping):
                raw = payload[key]
                break
    if raw is None:
        family_metrics = _normalise_family_metrics(payload)
        counts = {
            family: metrics.get("sample_count")
            for family, metrics in family_metrics.items()
            if metrics.get("sample_count") is not None
        }
        raw = counts
    if not isinstance(raw, Mapping):
        return {}
    values: dict[str, float] = {}
    for raw_family, raw_value in raw.items():
        value = _finite_float(raw_value)
        if value is None or value < 0.0:
            continue
        family = _canonical_family(raw_family)
        if family:
            values[family] = values.get(family, 0.0) + value
    total = sum(values.values())
    if total <= 0.0:
        return {}
    return {family: value / total for family, value in sorted(values.items())}


def _canonical_family(value: Any) -> str:
    text = _string(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "temporal": "tdfol",
        "temporal_deontic": "tdfol",
        "frame": "frame_logic",
        "frame_logic": "frame_logic",
        "knowledge_graph": "kg",
        "external_prover": "external_provers",
        "external_provers": "external_provers",
        "lean": "external_provers",
        "hammer": "external_provers",
    }
    return aliases.get(text, text)


def _normalise_family_metrics(payload: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    raw = _first_mapping(payload, _FAMILY_METRIC_KEYS)
    if not raw and isinstance(payload.get("aggregate"), Mapping):
        raw = _first_mapping(_mapping(payload["aggregate"]), _FAMILY_METRIC_KEYS)
    result: dict[str, dict[str, float]] = {}
    for raw_family, raw_metrics in raw.items():
        metrics = _mapping(raw_metrics)
        if not metrics:
            continue
        if isinstance(metrics.get("candidate"), Mapping):
            metrics = _mapping(metrics["candidate"])
        family = _canonical_family(raw_family)
        values: dict[str, float] = {}
        for raw_metric, raw_value in metrics.items():
            value = _finite_float(raw_value)
            if value is None:
                continue
            metric = _canonical_metric_name(raw_metric)
            values[metric] = value
        if family and values:
            result[family] = values
    return result


def _canonical_metric_name(value: Any) -> str:
    text = _string(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "hammer_proof_validity": "hammer_proof_success_rate",
        "proof_success_rate": "hammer_proof_success_rate",
        "proof_validity_rate": "hammer_proof_success_rate",
        "symbolic_validity": "symbolic_validity_success_rate",
        "structural_validity": "symbolic_validity_success_rate",
        "source_copy_loss": "source_copy_penalty",
        "hammer_source_copy_penalty": "source_copy_penalty",
        "source_copy_reward_hack": "source_copy_reward_hack_penalty",
    }
    return aliases.get(text, text)


def _jensen_shannon_divergence(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = sorted(set(left).union(right))
    if not keys:
        return 0.0
    midpoint = {key: (float(left.get(key, 0.0)) + float(right.get(key, 0.0))) / 2.0 for key in keys}

    def kl_divergence(source: Mapping[str, float], target: Mapping[str, float]) -> float:
        total = 0.0
        for key in keys:
            p = max(0.0, float(source.get(key, 0.0)))
            q = max(0.0, float(target.get(key, 0.0)))
            if p > 0.0 and q > 0.0:
                total += p * math.log2(p / q)
        return total

    return max(0.0, min(1.0, 0.5 * kl_divergence(left, midpoint) + 0.5 * kl_divergence(right, midpoint)))


@dataclass(frozen=True, slots=True)
class LegalIRDriftMonitorConfig:
    """Thresholds for fail-closed production drift monitoring."""

    max_distribution_js_divergence: float = 0.12
    max_family_distribution_delta: float = 0.20
    max_family_metric_regression: float = 0.05
    max_proof_failure_rate_increase: float = 0.05
    max_prompt_rejection_rate_increase: float = 0.05
    max_premise_rejection_rate_increase: float = 0.05
    max_prompt_rejection_rate: float = 0.25
    max_premise_rejection_rate: float = 0.25
    max_gpu_memory_pressure_increase: float = 0.15
    max_gpu_utilization_drop: float = 0.30
    max_memory_pressure_increase: float = 0.20
    max_cpu_utilization_increase: float = 0.35
    max_queue_lag_p95_seconds_increase: float = 120.0
    max_resource_saturation_event_increase: int = 0
    max_accepted_patch_rate_regression: float = 0.10
    fail_on_schema_version_change: bool = True
    fail_on_schema_signature_change: bool = True
    require_guidance_rollback_metadata: bool = True
    higher_is_better_metrics: frozenset[str] = DEFAULT_FAMILY_METRICS_HIGHER_IS_BETTER
    lower_is_better_metrics: frozenset[str] = DEFAULT_FAMILY_METRICS_LOWER_IS_BETTER

    def __post_init__(self) -> None:
        for name in (
            "max_distribution_js_divergence",
            "max_family_distribution_delta",
            "max_family_metric_regression",
            "max_proof_failure_rate_increase",
            "max_prompt_rejection_rate_increase",
            "max_premise_rejection_rate_increase",
            "max_prompt_rejection_rate",
            "max_premise_rejection_rate",
            "max_gpu_memory_pressure_increase",
            "max_gpu_utilization_drop",
            "max_memory_pressure_increase",
            "max_cpu_utilization_increase",
            "max_queue_lag_p95_seconds_increase",
            "max_accepted_patch_rate_regression",
        ):
            value = _finite_float(getattr(self, name))
            if value is None or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, value)
        if (
            isinstance(self.max_resource_saturation_event_increase, bool)
            or not isinstance(self.max_resource_saturation_event_increase, int)
            or self.max_resource_saturation_event_increase < 0
        ):
            raise ValueError("max_resource_saturation_event_increase must be a non-negative integer")
        object.__setattr__(
            self,
            "higher_is_better_metrics",
            frozenset(_canonical_metric_name(name) for name in self.higher_is_better_metrics),
        )
        object.__setattr__(
            self,
            "lower_is_better_metrics",
            frozenset(_canonical_metric_name(name) for name in self.lower_is_better_metrics),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fail_on_schema_signature_change": self.fail_on_schema_signature_change,
            "fail_on_schema_version_change": self.fail_on_schema_version_change,
            "higher_is_better_metrics": sorted(self.higher_is_better_metrics),
            "lower_is_better_metrics": sorted(self.lower_is_better_metrics),
            "max_accepted_patch_rate_regression": self.max_accepted_patch_rate_regression,
            "max_cpu_utilization_increase": self.max_cpu_utilization_increase,
            "max_distribution_js_divergence": self.max_distribution_js_divergence,
            "max_family_distribution_delta": self.max_family_distribution_delta,
            "max_family_metric_regression": self.max_family_metric_regression,
            "max_gpu_memory_pressure_increase": self.max_gpu_memory_pressure_increase,
            "max_gpu_utilization_drop": self.max_gpu_utilization_drop,
            "max_memory_pressure_increase": self.max_memory_pressure_increase,
            "max_premise_rejection_rate": self.max_premise_rejection_rate,
            "max_premise_rejection_rate_increase": self.max_premise_rejection_rate_increase,
            "max_prompt_rejection_rate": self.max_prompt_rejection_rate,
            "max_prompt_rejection_rate_increase": self.max_prompt_rejection_rate_increase,
            "max_proof_failure_rate_increase": self.max_proof_failure_rate_increase,
            "max_queue_lag_p95_seconds_increase": self.max_queue_lag_p95_seconds_increase,
            "max_resource_saturation_event_increase": self.max_resource_saturation_event_increase,
            "require_guidance_rollback_metadata": self.require_guidance_rollback_metadata,
        }


@dataclass(frozen=True, slots=True)
class LegalIRDriftEvent:
    """One threshold breach observed by the production monitor."""

    category: str
    signal: str
    observed: float | str
    threshold: float | str
    baseline: float | str = ""
    current: float | str = ""
    family: str = ""
    metric: str = ""
    severity: str = "critical"
    rollback_required: bool = True
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def event_id(self) -> str:
        return "lir-drift-" + _stable_digest(
            {
                "baseline": self.baseline,
                "category": self.category,
                "current": self.current,
                "family": self.family,
                "metric": self.metric,
                "observed": self.observed,
                "signal": self.signal,
                "threshold": self.threshold,
            }
        )[:20]

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline,
            "category": self.category,
            "current": self.current,
            "event_id": self.event_id,
            "evidence": _canonical_json_value(self.evidence),
            "family": self.family,
            "metric": self.metric,
            "observed": self.observed,
            "rollback_required": self.rollback_required,
            "severity": self.severity,
            "signal": self.signal,
            "threshold": self.threshold,
        }


@dataclass(frozen=True, slots=True)
class LegalIRRollbackTodo:
    """Operator TODO opened when learned guidance must be rolled back."""

    todo_id: str
    title: str
    affected_promotion_id: str
    rollback_id: str
    drift_event_ids: tuple[str, ...]
    guidance_ids: tuple[str, ...] = ()
    priority: str = "P0"
    status: str = "todo"
    track: str = "production-safety"
    action: str = "remove_promoted_guidance_records"
    schema_version: str = LEGAL_IR_DRIFT_ROLLBACK_TODO_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance": (
                "Promoted learned guidance remains disabled until production drift "
                "clears and a fresh promotion report passes rollback readiness gates."
            ),
            "action": self.action,
            "affected_promotion_id": self.affected_promotion_id,
            "drift_event_ids": list(self.drift_event_ids),
            "guidance_ids": list(self.guidance_ids),
            "hard_guardrail": PRODUCTION_DRIFT_AND_ROLLBACK_HARD_GUARDRAIL,
            "priority": self.priority,
            "rollback_id": self.rollback_id,
            "schema_version": self.schema_version,
            "status": self.status,
            "title": self.title,
            "todo_id": self.todo_id,
            "track": self.track,
        }


@dataclass(frozen=True, slots=True)
class LegalIRRollbackDecision:
    """Rollback action plan for drift-affected learned guidance."""

    rollback_required: bool
    disabled_promotions: tuple[Mapping[str, Any], ...] = ()
    rollback_todos: tuple[LegalIRRollbackTodo, ...] = ()
    block_reasons: tuple[str, ...] = ()
    schema_version: str = LEGAL_IR_DRIFT_ROLLBACK_DECISION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_reasons": list(self.block_reasons),
            "disabled_promotions": _canonical_json_value(self.disabled_promotions),
            "hard_guardrail": PRODUCTION_DRIFT_AND_ROLLBACK_HARD_GUARDRAIL,
            "rollback_required": self.rollback_required,
            "rollback_todos": [todo.to_dict() for todo in self.rollback_todos],
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class LegalIRDriftReport:
    """Complete production drift and rollback report."""

    report_id: str
    drift_detected: bool
    rollback_decision: LegalIRRollbackDecision
    events: tuple[LegalIRDriftEvent, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    config: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_DRIFT_MONITOR_SCHEMA_VERSION

    @property
    def accepted(self) -> bool:
        return not self.drift_detected

    @property
    def status(self) -> str:
        if self.rollback_decision.rollback_required:
            return "rollback_required"
        return "drift_detected" if self.drift_detected else "stable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "config": _canonical_json_value(self.config),
            "drift_detected": self.drift_detected,
            "drift_event_count": len(self.events),
            "events": [event.to_dict() for event in self.events],
            "hard_guardrail": PRODUCTION_DRIFT_AND_ROLLBACK_HARD_GUARDRAIL,
            "metrics": _canonical_json_value(self.metrics),
            "report_id": self.report_id,
            "rollback_decision": self.rollback_decision.to_dict(),
            "schema_version": self.schema_version,
            "status": self.status,
        }


class LegalIRDriftMonitor:
    """Compare production evidence against a baseline and plan rollback."""

    def __init__(self, config: LegalIRDriftMonitorConfig | None = None) -> None:
        self.config = config or LegalIRDriftMonitorConfig()

    def evaluate(
        self,
        baseline: Mapping[str, Any] | Any,
        current: Mapping[str, Any] | Any,
        *,
        promoted_guidance: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    ) -> LegalIRDriftReport:
        baseline_payload = _mapping(baseline)
        current_payload = _mapping(current)
        events: list[LegalIRDriftEvent] = []
        metrics: dict[str, Any] = {}

        distribution_events, distribution_metrics = self._distribution_drift(
            baseline_payload, current_payload
        )
        events.extend(distribution_events)
        metrics["production_distribution"] = distribution_metrics

        family_events, family_metrics = self._family_metric_drift(
            baseline_payload, current_payload
        )
        events.extend(family_events)
        metrics["family_metric_drift"] = family_metrics

        proof_events, proof_metrics = self._proof_failure_drift(
            baseline_payload, current_payload
        )
        events.extend(proof_events)
        metrics["proof_failure_drift"] = proof_metrics

        rejection_events, rejection_metrics = self._rejection_spikes(
            baseline_payload, current_payload
        )
        events.extend(rejection_events)
        metrics["rejection_spikes"] = rejection_metrics

        schema_events, schema_metrics = self._schema_drift(
            baseline_payload, current_payload
        )
        events.extend(schema_events)
        metrics["schema_drift"] = schema_metrics

        resource_events, resource_metrics = self._resource_degradation(
            baseline_payload, current_payload
        )
        events.extend(resource_events)
        metrics["resource_degradation"] = resource_metrics

        patch_events, patch_metrics = self._accepted_patch_regression(
            baseline_payload, current_payload
        )
        events.extend(patch_events)
        metrics["accepted_patch_regression"] = patch_metrics

        promotions = _active_promotions(current_payload, promoted_guidance)
        rollback_readiness_events = self._rollback_readiness_events(promotions)
        events.extend(rollback_readiness_events)
        metrics["promoted_guidance"] = {
            "active_promotion_count": len(promotions),
            "active_promotion_ids": [
                str(promotion.get("promotion_id") or "") for promotion in promotions
            ],
        }

        deduped_events = tuple(_dedupe_events(events))
        rollback_decision = _build_rollback_decision(deduped_events, promotions)
        report_id = "lir-drift-report-" + _stable_digest(
            {
                "baseline": _baseline_identity(baseline_payload),
                "config": self.config.to_dict(),
                "current": _baseline_identity(current_payload),
                "events": [event.to_dict() for event in deduped_events],
                "rollback": rollback_decision.to_dict(),
            }
        )[:24]
        return LegalIRDriftReport(
            report_id=report_id,
            drift_detected=bool(deduped_events),
            events=deduped_events,
            rollback_decision=rollback_decision,
            metrics=metrics,
            config=self.config.to_dict(),
        )

    def _distribution_drift(
        self, baseline: Mapping[str, Any], current: Mapping[str, Any]
    ) -> tuple[list[LegalIRDriftEvent], dict[str, Any]]:
        before = _normalise_distribution(baseline)
        after = _normalise_distribution(current)
        events: list[LegalIRDriftEvent] = []
        jsd = _jensen_shannon_divergence(before, after) if before and after else 0.0
        if before and after and jsd > self.config.max_distribution_js_divergence:
            events.append(
                LegalIRDriftEvent(
                    category="production_distribution_drift",
                    signal="jensen_shannon_divergence",
                    observed=round(jsd, 12),
                    threshold=self.config.max_distribution_js_divergence,
                    evidence={"baseline_distribution": before, "current_distribution": after},
                )
            )
        family_deltas: dict[str, float] = {}
        for family in sorted(set(before).union(after)):
            delta = abs(float(after.get(family, 0.0)) - float(before.get(family, 0.0)))
            family_deltas[family] = round(delta, 12)
            if before and after and delta > self.config.max_family_distribution_delta:
                events.append(
                    LegalIRDriftEvent(
                        category="production_distribution_drift",
                        signal="family_distribution_delta",
                        family=family,
                        observed=round(delta, 12),
                        threshold=self.config.max_family_distribution_delta,
                        baseline=round(float(before.get(family, 0.0)), 12),
                        current=round(float(after.get(family, 0.0)), 12),
                    )
                )
        return events, {
            "baseline": before,
            "current": after,
            "family_deltas": family_deltas,
            "jensen_shannon_divergence": round(jsd, 12),
        }

    def _family_metric_drift(
        self, baseline: Mapping[str, Any], current: Mapping[str, Any]
    ) -> tuple[list[LegalIRDriftEvent], dict[str, Any]]:
        before = _normalise_family_metrics(baseline)
        after = _normalise_family_metrics(current)
        events: list[LegalIRDriftEvent] = []
        deltas: dict[str, dict[str, float]] = {}
        for family in sorted(set(before).intersection(after)):
            deltas[family] = {}
            for metric in sorted(set(before[family]).intersection(after[family])):
                if metric not in self.config.higher_is_better_metrics and metric not in self.config.lower_is_better_metrics:
                    continue
                baseline_value = before[family][metric]
                current_value = after[family][metric]
                regression = (
                    baseline_value - current_value
                    if metric in self.config.higher_is_better_metrics
                    else current_value - baseline_value
                )
                deltas[family][metric] = round(regression, 12)
                if regression > self.config.max_family_metric_regression:
                    events.append(
                        LegalIRDriftEvent(
                            category="family_metric_drift",
                            signal="family_metric_regression",
                            family=family,
                            metric=metric,
                            observed=round(regression, 12),
                            threshold=self.config.max_family_metric_regression,
                            baseline=round(baseline_value, 12),
                            current=round(current_value, 12),
                        )
                    )
        return events, {"deltas": deltas}

    def _proof_failure_drift(
        self, baseline: Mapping[str, Any], current: Mapping[str, Any]
    ) -> tuple[list[LegalIRDriftEvent], dict[str, Any]]:
        before_rate = _proof_failure_rate(baseline)
        after_rate = _proof_failure_rate(current)
        events: list[LegalIRDriftEvent] = []
        increase = None
        if before_rate is not None and after_rate is not None:
            increase = after_rate - before_rate
            if increase > self.config.max_proof_failure_rate_increase:
                events.append(
                    LegalIRDriftEvent(
                        category="proof_failure_drift",
                        signal="proof_failure_rate_increase",
                        observed=round(increase, 12),
                        threshold=self.config.max_proof_failure_rate_increase,
                        baseline=round(before_rate, 12),
                        current=round(after_rate, 12),
                    )
                )
        return events, {
            "baseline_failure_rate": before_rate,
            "current_failure_rate": after_rate,
            "increase": round(increase, 12) if increase is not None else None,
        }

    def _rejection_spikes(
        self, baseline: Mapping[str, Any], current: Mapping[str, Any]
    ) -> tuple[list[LegalIRDriftEvent], dict[str, Any]]:
        events: list[LegalIRDriftEvent] = []
        metrics: dict[str, Any] = {}
        for kind in ("prompt", "premise"):
            before = _rejection_rate(baseline, kind)
            after = _rejection_rate(current, kind)
            threshold = (
                self.config.max_prompt_rejection_rate_increase
                if kind == "prompt"
                else self.config.max_premise_rejection_rate_increase
            )
            ceiling = (
                self.config.max_prompt_rejection_rate
                if kind == "prompt"
                else self.config.max_premise_rejection_rate
            )
            increase = None
            if before is not None and after is not None:
                increase = after - before
                if increase > threshold:
                    events.append(
                        LegalIRDriftEvent(
                            category=f"{kind}_rejection_spike",
                            signal=f"{kind}_rejection_rate_increase",
                            observed=round(increase, 12),
                            threshold=threshold,
                            baseline=round(before, 12),
                            current=round(after, 12),
                        )
                    )
            if after is not None and after > ceiling:
                events.append(
                    LegalIRDriftEvent(
                        category=f"{kind}_rejection_spike",
                        signal=f"{kind}_rejection_rate_ceiling",
                        observed=round(after, 12),
                        threshold=ceiling,
                        baseline=round(before, 12) if before is not None else "",
                        current=round(after, 12),
                    )
                )
            metrics[kind] = {
                "baseline_rate": before,
                "current_rate": after,
                "increase": round(increase, 12) if increase is not None else None,
            }
        return events, metrics

    def _schema_drift(
        self, baseline: Mapping[str, Any], current: Mapping[str, Any]
    ) -> tuple[list[LegalIRDriftEvent], dict[str, Any]]:
        before = _schema_identity(baseline)
        after = _schema_identity(current)
        events: list[LegalIRDriftEvent] = []
        if (
            self.config.fail_on_schema_version_change
            and before.get("schema_version")
            and after.get("schema_version")
            and before.get("schema_version") != after.get("schema_version")
        ):
            events.append(
                LegalIRDriftEvent(
                    category="schema_drift",
                    signal="schema_version_change",
                    observed=f"{before['schema_version']}->{after['schema_version']}",
                    threshold="no_change",
                    baseline=str(before["schema_version"]),
                    current=str(after["schema_version"]),
                )
            )
        if (
            self.config.fail_on_schema_signature_change
            and before.get("schema_signature")
            and after.get("schema_signature")
            and before.get("schema_signature") != after.get("schema_signature")
        ):
            events.append(
                LegalIRDriftEvent(
                    category="schema_drift",
                    signal="schema_signature_change",
                    observed="changed",
                    threshold="no_change",
                    baseline=str(before["schema_signature"]),
                    current=str(after["schema_signature"]),
                    evidence={
                        "added_keys": sorted(set(after["schema_keys"]) - set(before["schema_keys"])),
                        "removed_keys": sorted(set(before["schema_keys"]) - set(after["schema_keys"])),
                    },
                )
            )
        return events, {"baseline": before, "current": after}

    def _resource_degradation(
        self, baseline: Mapping[str, Any], current: Mapping[str, Any]
    ) -> tuple[list[LegalIRDriftEvent], dict[str, Any]]:
        before = _resource_metrics(baseline)
        after = _resource_metrics(current)
        events: list[LegalIRDriftEvent] = []

        for signal, threshold in (
            ("gpu_memory_pressure", self.config.max_gpu_memory_pressure_increase),
            ("memory_pressure", self.config.max_memory_pressure_increase),
            ("cpu_utilization", self.config.max_cpu_utilization_increase),
        ):
            baseline_value = before.get(signal)
            current_value = after.get(signal)
            if baseline_value is None or current_value is None:
                continue
            increase = float(current_value) - float(baseline_value)
            if increase > threshold:
                events.append(
                    LegalIRDriftEvent(
                        category="gpu_resource_degradation" if signal.startswith("gpu") else "resource_degradation",
                        signal=f"{signal}_increase",
                        observed=round(increase, 12),
                        threshold=threshold,
                        baseline=round(float(baseline_value), 12),
                        current=round(float(current_value), 12),
                    )
                )

        gpu_before = before.get("gpu_utilization")
        gpu_after = after.get("gpu_utilization")
        if gpu_before is not None and gpu_after is not None:
            drop = float(gpu_before) - float(gpu_after)
            if drop > self.config.max_gpu_utilization_drop:
                events.append(
                    LegalIRDriftEvent(
                        category="gpu_resource_degradation",
                        signal="gpu_utilization_drop",
                        observed=round(drop, 12),
                        threshold=self.config.max_gpu_utilization_drop,
                        baseline=round(float(gpu_before), 12),
                        current=round(float(gpu_after), 12),
                    )
                )

        if before.get("gpu_telemetry_known") is True and after.get("gpu_telemetry_known") is False:
            events.append(
                LegalIRDriftEvent(
                    category="gpu_resource_degradation",
                    signal="gpu_telemetry_lost",
                    observed="unknown",
                    threshold="known",
                    baseline="known",
                    current="unknown",
                )
            )

        lag_before = before.get("queue_lag_p95_seconds")
        lag_after = after.get("queue_lag_p95_seconds")
        if lag_before is not None and lag_after is not None:
            increase = float(lag_after) - float(lag_before)
            if increase > self.config.max_queue_lag_p95_seconds_increase:
                events.append(
                    LegalIRDriftEvent(
                        category="resource_degradation",
                        signal="queue_lag_p95_seconds_increase",
                        observed=round(increase, 12),
                        threshold=self.config.max_queue_lag_p95_seconds_increase,
                        baseline=round(float(lag_before), 12),
                        current=round(float(lag_after), 12),
                    )
                )

        saturation_before = before.get("saturation_events_total")
        saturation_after = after.get("saturation_events_total")
        if saturation_before is not None and saturation_after is not None:
            increase = int(saturation_after) - int(saturation_before)
            if increase > self.config.max_resource_saturation_event_increase:
                events.append(
                    LegalIRDriftEvent(
                        category="resource_degradation",
                        signal="resource_saturation_event_increase",
                        observed=increase,
                        threshold=self.config.max_resource_saturation_event_increase,
                        baseline=int(saturation_before),
                        current=int(saturation_after),
                    )
                )
        return events, {"baseline": before, "current": after}

    def _accepted_patch_regression(
        self, baseline: Mapping[str, Any], current: Mapping[str, Any]
    ) -> tuple[list[LegalIRDriftEvent], dict[str, Any]]:
        before = _accepted_patch_rate(baseline)
        after = _accepted_patch_rate(current)
        events: list[LegalIRDriftEvent] = []
        regression = None
        if before is not None and after is not None:
            regression = before - after
            if regression > self.config.max_accepted_patch_rate_regression:
                events.append(
                    LegalIRDriftEvent(
                        category="accepted_patch_regression",
                        signal="accepted_patch_rate_regression",
                        observed=round(regression, 12),
                        threshold=self.config.max_accepted_patch_rate_regression,
                        baseline=round(before, 12),
                        current=round(after, 12),
                    )
                )
        return events, {
            "baseline_rate": before,
            "current_rate": after,
            "regression": round(regression, 12) if regression is not None else None,
        }

    def _rollback_readiness_events(
        self, promotions: Sequence[Mapping[str, Any]]
    ) -> list[LegalIRDriftEvent]:
        if not self.config.require_guidance_rollback_metadata:
            return []
        events: list[LegalIRDriftEvent] = []
        for promotion in promotions:
            promotion_id = _string(promotion.get("promotion_id"))
            rollback = _mapping(promotion.get("rollback_metadata"))
            if not rollback or not _string(rollback.get("rollback_id")):
                events.append(
                    LegalIRDriftEvent(
                        category="rollback_readiness",
                        signal="promoted_guidance_rollback_metadata_missing",
                        observed=promotion_id or "active_guidance",
                        threshold="rollback_metadata_present",
                        current=promotion_id,
                    )
                )
        return events


def _proof_failure_rate(payload: Mapping[str, Any]) -> float | None:
    direct = _first_number(
        payload,
        ("proof_failure_rate", "hammer_failure_rate", "latest_proof_failure_rate"),
    )
    if direct is not None:
        return _safe_rate(direct)
    hammer = _mapping(payload.get("hammer_metrics") or _mapping(payload.get("latest_daemon_hammer_guidance")).get("hammer_metrics"))
    success = _first_number(
        hammer or payload,
        (
            "hammer_proof_success_rate",
            "proof_success_rate",
            "proof_validity_rate",
        ),
    )
    if success is not None:
        rate = _safe_rate(success)
        return 1.0 - rate if rate is not None else None
    failed = _first_number(payload, ("proof_failed_count", "failed_count", "hammer_failed_count"))
    attempted = _first_number(payload, ("proof_attempted_count", "attempted_count", "hammer_attempted_count"))
    if failed is not None and attempted is not None and attempted > 0:
        return max(0.0, min(1.0, failed / attempted))
    family_metrics = _normalise_family_metrics(payload)
    family_rates: list[float] = []
    for metrics in family_metrics.values():
        failure = _safe_rate(metrics.get("proof_failure_rate"))
        if failure is not None:
            family_rates.append(failure)
            continue
        success = _safe_rate(metrics.get("hammer_proof_success_rate"))
        if success is not None:
            family_rates.append(1.0 - success)
    if family_rates:
        return sum(family_rates) / len(family_rates)
    return None


def _rejection_rate(payload: Mapping[str, Any], kind: str) -> float | None:
    direct = _first_number(
        payload,
        (
            f"{kind}_rejection_rate",
            f"{kind}_rejected_rate",
            f"latest_{kind}_rejection_rate",
        ),
    )
    if direct is not None:
        return _safe_rate(direct)
    for key in _REJECTION_KEYS:
        if not key.startswith(kind):
            continue
        nested = _mapping(payload.get(key))
        rate = _first_number(nested, ("rejection_rate", "rejected_rate", "blocked_rate"))
        if rate is not None:
            return _safe_rate(rate)
        counted = _rate_from_counts(nested)
        if counted is not None:
            return counted
    counted = _rate_from_counts(payload)
    return counted


def _schema_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    schema = _mapping(
        payload.get("schema")
        or payload.get("ir_schema")
        or payload.get("legal_ir_schema")
        or payload.get("schema_contract")
    )
    if schema:
        version = _string(schema.get("schema_version") or schema.get("version"))
        keys = tuple(sorted(str(key) for key in schema.keys()))
        signature_source: Any = schema
    else:
        version = _string(
            payload.get("schema_version")
            or _mapping(payload.get("versions")).get("schema_version")
        )
        keys = tuple(sorted(str(key) for key in payload.keys()))
        signature_source = {"schema_version": version, "keys": keys}
    explicit_signature = _string(
        payload.get("schema_signature")
        or payload.get("schema_digest")
        or payload.get("schema_hash")
        or schema.get("schema_signature")
        or schema.get("sha256")
    )
    return {
        "schema_keys": keys,
        "schema_signature": explicit_signature or _stable_digest(signature_source),
        "schema_version": version,
    }


def _resource_metrics(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = _first_mapping(payload, _RESOURCE_KEYS)
    if not raw and isinstance(payload.get("evaluator_health"), Mapping):
        raw = _mapping(payload["evaluator_health"])
    queue_lag = _queue_lag(payload)
    result: dict[str, Any] = {
        "cpu_utilization": _safe_rate(_first_number(raw or payload, ("cpu_utilization", "cpu_percent"))),
        "gpu_memory_pressure": _safe_rate(_first_number(raw or payload, ("gpu_memory_pressure", "gpu_memory_percent"))),
        "gpu_utilization": _safe_rate(_first_number(raw or payload, ("gpu_utilization", "gpu_utilization_percent"))),
        "memory_pressure": _safe_rate(_first_number(raw or payload, ("memory_pressure", "memory_percent"))),
        "queue_lag_p95_seconds": queue_lag,
        "saturation_events_total": _first_number(raw or payload, ("saturation_events_total", "resource_saturation_events_total", "resource_saturation_events")),
    }
    telemetry_known = (raw or payload).get("gpu_telemetry_known")
    if telemetry_known is None:
        telemetry_known = (raw or payload).get("gpu_telemetry_available")
    if telemetry_known is None:
        status = _string((raw or payload).get("collector_status")).lower()
        telemetry_known = False if "gpu_unavailable" in status else None
    result["gpu_telemetry_known"] = telemetry_known if isinstance(telemetry_known, bool) else None
    return result


def _queue_lag(payload: Mapping[str, Any]) -> float | None:
    direct = _first_number(
        payload,
        (
            "queue_lag_p95_seconds",
            "latest_queue_lag_p95_seconds",
            "codex_queue_lag_p95_seconds",
        ),
    )
    if direct is not None:
        return direct
    queue_lag = _mapping(payload.get("queue_lag"))
    return _first_number(queue_lag, ("p95_seconds", "p95", "seconds"))


def _accepted_patch_rate(payload: Mapping[str, Any]) -> float | None:
    direct = _first_number(
        payload,
        (
            "accepted_patch_rate",
            "task_to_accepted_patch_rate",
            "accepted_patches_per_hour",
            "accepted_patches_per_wall_clock_hour",
        ),
    )
    if direct is not None:
        return direct
    thresholds = _mapping(payload.get("promotion_thresholds"))
    for key in ("task_to_accepted_patch_rate", "accepted_patch_rate"):
        value = thresholds.get(key)
        if isinstance(value, Mapping):
            candidate = _finite_float(value.get("candidate"))
            if candidate is not None:
                return candidate
    count = _first_number(
        payload,
        ("accepted_patches", "codex_accepted_patch_count", "codex_main_apply_count"),
    )
    elapsed = _first_number(payload, ("wall_clock_seconds", "elapsed_seconds", "duration_seconds"))
    if count is not None and elapsed is not None and elapsed > 0.0:
        return count * 3600.0 / elapsed
    return None


def _active_promotions(
    current: Mapping[str, Any],
    promoted_guidance: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> tuple[Mapping[str, Any], ...]:
    raw_items: list[Any] = []
    if promoted_guidance is not None:
        if isinstance(promoted_guidance, Mapping):
            raw_items.append(promoted_guidance)
        else:
            raw_items.extend(_sequence(promoted_guidance))
    for key in _PROMOTION_KEYS:
        value = current.get(key)
        if isinstance(value, Mapping):
            raw_items.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            raw_items.extend(value)
    result: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = _mapping(raw)
        if not item:
            continue
        activation = _mapping(item.get("activation_state"))
        active = (
            item.get("promoted") is True
            or activation.get("active") is True
            or activation.get("activation_allowed") is True
        )
        if not active:
            continue
        promotion_id = _string(
            item.get("promotion_id")
            or activation.get("active_promotion_id")
            or item.get("activation_key")
        )
        key = promotion_id or _stable_digest(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


def _build_rollback_decision(
    events: Sequence[LegalIRDriftEvent],
    promotions: Sequence[Mapping[str, Any]],
) -> LegalIRRollbackDecision:
    rollback_required = any(event.rollback_required for event in events)
    if not rollback_required:
        return LegalIRRollbackDecision(rollback_required=False)
    event_ids = tuple(event.event_id for event in events if event.rollback_required)
    disabled: list[Mapping[str, Any]] = []
    todos: list[LegalIRRollbackTodo] = []
    block_reasons = tuple(sorted({event.category for event in events if event.rollback_required}))
    for promotion in promotions:
        promotion_id = _string(
            promotion.get("promotion_id")
            or _mapping(promotion.get("activation_state")).get("active_promotion_id")
        )
        if not promotion_id:
            promotion_id = "promotion-" + _stable_digest(promotion)[:16]
        rollback = dict(_mapping(promotion.get("rollback_metadata")))
        if not rollback:
            rollback = {
                "activation_key": promotion_id,
                "disable_action": "remove_promoted_guidance_records",
                "restore_mode": "canary_only",
                "rollback_id": "lir-guidance-rollback-" + _stable_digest(
                    {"promotion_id": promotion_id}
                )[:24],
            }
        rollback_id = _string(rollback.get("rollback_id")) or (
            "lir-guidance-rollback-" + _stable_digest({"promotion_id": promotion_id})[:24]
        )
        guidance_ids = _guidance_ids(promotion)
        disabled_state = {
            "activation_allowed": False,
            "active": False,
            "active_promotion_id": "",
            "block_reasons": list(block_reasons),
            "disabled_by": "legal_ir_drift_monitor",
            "disabled_by_report_events": list(event_ids),
            "previous_active_promotion_id": promotion_id,
            "state": "disabled_due_to_production_drift",
        }
        disabled.append(
            {
                "activation_state": disabled_state,
                "affected_guidance_ids": list(guidance_ids),
                "disable_action": _string(rollback.get("disable_action")) or "remove_promoted_guidance_records",
                "disabled": True,
                "promotion_id": promotion_id,
                "rollback_metadata": {
                    **rollback,
                    "rollback_id": rollback_id,
                    "rollback_trigger": "production_drift_monitor",
                    "rollback_trigger_event_ids": list(event_ids),
                },
                "source_export_id": _string(promotion.get("source_export_id") or promotion.get("learned_export_id")),
            }
        )
        todo_id = "PORTAL-LIR-HAMMER-083-ROLLBACK-" + _stable_digest(
            {
                "events": event_ids,
                "guidance_ids": guidance_ids,
                "promotion_id": promotion_id,
                "rollback_id": rollback_id,
            }
        )[:12].upper()
        todos.append(
            LegalIRRollbackTodo(
                todo_id=todo_id,
                title=f"Rollback learned guidance {promotion_id} after production drift",
                affected_promotion_id=promotion_id,
                rollback_id=rollback_id,
                drift_event_ids=event_ids,
                guidance_ids=guidance_ids,
                action=_string(rollback.get("disable_action")) or "remove_promoted_guidance_records",
            )
        )
    if not promotions:
        todo_id = "PORTAL-LIR-HAMMER-083-ROLLBACK-" + _stable_digest(
            {"events": event_ids, "promotion_id": "missing_active_promotion"}
        )[:12].upper()
        todos.append(
            LegalIRRollbackTodo(
                todo_id=todo_id,
                title="Investigate production drift with no active guidance record",
                affected_promotion_id="",
                rollback_id="",
                drift_event_ids=event_ids,
                action="verify_no_promoted_guidance_active",
            )
        )
    return LegalIRRollbackDecision(
        rollback_required=True,
        disabled_promotions=tuple(disabled),
        rollback_todos=tuple(todos),
        block_reasons=block_reasons,
    )


def _guidance_ids(promotion: Mapping[str, Any]) -> tuple[str, ...]:
    records = promotion.get("guidance_records", promotion.get("records", ()))
    ids: list[str] = []
    for record in _sequence(records):
        item = _mapping(record)
        guidance_id = _string(item.get("guidance_id") or item.get("id"))
        if guidance_id:
            ids.append(guidance_id)
    return tuple(dict.fromkeys(ids))


def _dedupe_events(events: Sequence[LegalIRDriftEvent]) -> list[LegalIRDriftEvent]:
    result: list[LegalIRDriftEvent] = []
    seen: set[str] = set()
    for event in events:
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        result.append(event)
    return result


def _baseline_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": _string(
            payload.get("artifact_id")
            or payload.get("snapshot_id")
            or payload.get("baseline_id")
            or payload.get("run_id")
        ),
        "schema": _schema_identity(payload),
    }


def monitor_legal_ir_production_drift(
    baseline: Mapping[str, Any] | Any,
    current: Mapping[str, Any] | Any,
    *,
    config: LegalIRDriftMonitorConfig | None = None,
    promoted_guidance: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
) -> LegalIRDriftReport:
    """Evaluate production drift and rollback promoted learned guidance."""

    return LegalIRDriftMonitor(config).evaluate(
        baseline,
        current,
        promoted_guidance=promoted_guidance,
    )


def persist_legal_ir_drift_report(
    report: LegalIRDriftReport | Mapping[str, Any],
    path: str | Path,
) -> Path:
    """Persist a drift report atomically enough for operator handoff tests."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict() if isinstance(report, LegalIRDriftReport) else dict(report)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(
        json.dumps(_canonical_json_value(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(target)
    return target


def append_rollback_todos(
    report: LegalIRDriftReport | Mapping[str, Any],
    path: str | Path,
) -> Path:
    """Append rollback TODO records as JSONL for downstream queue import."""

    payload = report.to_dict() if isinstance(report, LegalIRDriftReport) else dict(report)
    decision = _mapping(payload.get("rollback_decision"))
    todos = _sequence(decision.get("rollback_todos"))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for todo in todos:
            handle.write(
                json.dumps(_canonical_json_value(todo), sort_keys=True, separators=(",", ":"))
                + "\n"
            )
    return target


__all__ = [
    "LEGAL_IR_DRIFT_MONITOR_SCHEMA_VERSION",
    "LEGAL_IR_DRIFT_ROLLBACK_DECISION_SCHEMA_VERSION",
    "LEGAL_IR_DRIFT_ROLLBACK_TODO_SCHEMA_VERSION",
    "PRODUCTION_DRIFT_AND_ROLLBACK_HARD_GUARDRAIL",
    "LegalIRDriftEvent",
    "LegalIRDriftMonitor",
    "LegalIRDriftMonitorConfig",
    "LegalIRDriftReport",
    "LegalIRRollbackDecision",
    "LegalIRRollbackTodo",
    "append_rollback_todos",
    "monitor_legal_ir_production_drift",
    "persist_legal_ir_drift_report",
]
