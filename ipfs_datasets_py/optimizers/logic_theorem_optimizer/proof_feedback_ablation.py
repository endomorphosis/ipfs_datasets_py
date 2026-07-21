"""Causal ablations for trusted Hammer and Leanstral proof feedback.

Production weight writes are gated by two facts that a trusted receipt alone
cannot establish: the feedback has to improve a frozen holdout, and the
correct labels have to beat matched controls.  This module runs those matched
arms on cloned autoencoder state and emits a receipt that remains compatible
with :class:`TrustedFeedbackTrainer`.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Optional

from ...logic.integration.reasoning.legal_ir_learned_guidance import (
    TRUSTED_FEEDBACK_ABLATION_SCHEMA_VERSION,
    TrustedFeedbackAblationEvidence,
)
from ...logic.integration.reasoning.legal_ir_proof_feedback import (
    LegalIRProofFeedbackRecord,
    ProofFeedbackVersions,
)
from .modal_autoencoder import (
    AdaptiveModalAutoencoder,
    AutoencoderEvaluation,
    LEGAL_IR_VIEW_FAMILIES,
    LEGAL_IR_VIEW_FAMILY_METRIC_NAMES,
    legal_ir_view_family_metric_block,
)
from .trusted_feedback_trainer import (
    TrustedFeedbackTrainer,
    TrustedFeedbackTrainerConfig,
)


PROOF_FEEDBACK_ABLATION_REPORT_SCHEMA_VERSION: Final = (
    "legal-ir-proof-feedback-causal-ablation-v1"
)
NO_FEEDBACK_ARM: Final = "none"
HAMMER_ONLY_ARM: Final = "hammer"
VERIFIED_LEANSTRAL_HAMMER_ARM: Final = "verified_leanstral_hammer"
SHUFFLED_LABEL_CONTROL_ARM: Final = "shuffled_control"
PROOF_FEEDBACK_ABLATION_ARMS: Final = (
    NO_FEEDBACK_ARM,
    HAMMER_ONLY_ARM,
    VERIFIED_LEANSTRAL_HAMMER_ARM,
    SHUFFLED_LABEL_CONTROL_ARM,
)

_PRIMARY_METRIC_CANDIDATES: Final = (
    "legal_ir_view_cross_entropy_loss",
    "compiler_ir_cross_entropy_loss",
    "autoencoder_cross_entropy_loss",
    "ir_cross_entropy_loss",
    "objective_loss",
)
_LOWER_IS_BETTER: Final = frozenset(
    {
        "autoencoder_cross_entropy_loss",
        "compiler_ir_cross_entropy_loss",
        "ir_cross_entropy_loss",
        "legal_ir_view_cross_entropy_loss",
        "objective_loss",
        "reconstruction_loss",
        "source_copy_penalty",
        "source_copy_reward_hack_penalty",
    }
)
_ATTRIBUTION_GROUPS: Final = {
    "learned_ir": (
        "autoencoder_cross_entropy_loss",
        "autoencoder_cosine_similarity",
    ),
    "compiler_ir": (
        "ir_cross_entropy_loss",
        "ir_cosine_similarity",
    ),
    "proof": (
        "hammer_proof_success_rate",
        "symbolic_validity_success_rate",
    ),
    "reconstruction": ("reconstruction_success_rate",),
    "anti_copy": ("source_copy_penalty",),
}
_VERIFIER_KEYS: Final = (
    "leanstral_verified",
    "proof_checked",
    "verified",
    "verifier_confirmed",
)


class _SerializableMapping(Mapping[str, Any]):
    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - protocol method
        raise NotImplementedError

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


ProofFeedbackMetricEvaluator = Callable[
    [AdaptiveModalAutoencoder, Sequence[Any], str, int],
    Mapping[str, Any] | AutoencoderEvaluation,
]


@dataclass(frozen=True)
class ProofFeedbackAblationConfig:
    """Controls for the frozen train/holdout ablation runner."""

    holdout_id: str = ""
    primary_metric: str = ""
    minimum_improvement: float = 1.0e-9
    metric_tolerance: float = 0.0
    repeat_count: int = 2
    learning_rate: float = 0.05
    max_updates_per_arm: int = 64
    require_explicit_train_partition: bool = False
    legal_ir_bridge_names: tuple[str, ...] = ()
    legal_ir_targets: Optional[Mapping[str, Any] | Sequence[Any]] = None
    legal_ir_parallel_workers: Optional[int] = None
    legal_ir_evaluate_provers: Optional[bool] = None

    def __post_init__(self) -> None:
        if int(self.repeat_count) < 1:
            raise ValueError("repeat_count must be at least 1")
        if int(self.max_updates_per_arm) < 1:
            raise ValueError("max_updates_per_arm must be at least 1")
        for name in ("learning_rate", "minimum_improvement", "metric_tolerance"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True)
class ProofFeedbackAblationArmResult(_SerializableMapping):
    """One repeated ablation arm over the same frozen partitions."""

    arm: str
    repeat_index: int
    training_sample_ids: tuple[str, ...]
    heldout_sample_ids: tuple[str, ...]
    holdout_metrics: Mapping[str, float]
    view_family_metrics: Mapping[str, Mapping[str, Any]]
    training_report: Mapping[str, Any] = field(default_factory=dict)
    trainable_head_norms: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "heldout_sample_ids": list(self.heldout_sample_ids),
            "holdout_metrics": _json_ready(self.holdout_metrics),
            "repeat_index": self.repeat_index,
            "trainable_head_norms": _json_ready(self.trainable_head_norms),
            "training_report": _json_ready(self.training_report),
            "training_sample_ids": list(self.training_sample_ids),
            "view_family_metrics": _json_ready(self.view_family_metrics),
        }


@dataclass(frozen=True)
class ProofFeedbackAblationReport(_SerializableMapping):
    """Rich causal report that also satisfies the legacy trainer gate."""

    ablation_id: str
    holdout_id: str
    primary_metric: str
    baseline_primary_value: float
    candidate_primary_value: float
    heldout_improvement: float
    minimum_improvement: float
    training_sample_ids: tuple[str, ...]
    heldout_sample_ids: tuple[str, ...]
    fixed_sample_set: bool
    holdout_isolated: bool
    source_copy_guard_passed: bool
    symbolic_validity_guard_passed: bool
    metric_guardrails_passed: bool
    arm_results: tuple[ProofFeedbackAblationArmResult, ...]
    per_family_deltas: Mapping[str, Mapping[str, Mapping[str, Any]]]
    repeat_control_margins: tuple[Mapping[str, float], ...]
    block_reasons: tuple[str, ...] = ()
    metric_deltas: Mapping[str, float] = field(default_factory=dict)
    report_schema_version: str = PROOF_FEEDBACK_ABLATION_REPORT_SCHEMA_VERSION
    schema_version: str = TRUSTED_FEEDBACK_ABLATION_SCHEMA_VERSION

    @property
    def heldout_benefit(self) -> bool:
        return (
            self.heldout_improvement > 0.0
            and self.heldout_improvement >= self.minimum_improvement
        )

    @property
    def production_writes_allowed(self) -> bool:
        return (
            bool(self.holdout_id)
            and bool(self.heldout_sample_ids)
            and self.fixed_sample_set
            and self.holdout_isolated
            and self.heldout_benefit
            and self.source_copy_guard_passed
            and self.symbolic_validity_guard_passed
            and self.metric_guardrails_passed
            and not self.block_reasons
        )

    @property
    def production_weight_writes_allowed(self) -> bool:
        return self.production_writes_allowed

    @property
    def status(self) -> str:
        return "passed" if self.production_writes_allowed else "blocked"

    def to_trusted_feedback_ablation_evidence(self) -> TrustedFeedbackAblationEvidence:
        return TrustedFeedbackAblationEvidence(
            ablation_id=self.ablation_id,
            holdout_id=self.holdout_id,
            primary_metric=self.primary_metric,
            baseline_primary_value=self.baseline_primary_value,
            candidate_primary_value=self.candidate_primary_value,
            heldout_improvement=self.heldout_improvement,
            minimum_improvement=self.minimum_improvement,
            training_sample_ids=self.training_sample_ids,
            heldout_sample_ids=self.heldout_sample_ids,
            fixed_sample_set=self.fixed_sample_set,
            holdout_isolated=self.holdout_isolated,
            source_copy_guard_passed=self.source_copy_guard_passed,
            symbolic_validity_guard_passed=self.symbolic_validity_guard_passed,
            metric_guardrails_passed=self.metric_guardrails_passed,
            block_reasons=self.block_reasons,
            metric_deltas=self.metric_deltas,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ablation_id": self.ablation_id,
            "arm_results": [result.to_dict() for result in self.arm_results],
            "arms": list(PROOF_FEEDBACK_ABLATION_ARMS),
            "baseline_primary_value": round(self.baseline_primary_value, 12),
            "block_reasons": list(self.block_reasons),
            "candidate_primary_value": round(self.candidate_primary_value, 12),
            "fixed_sample_set": self.fixed_sample_set,
            "heldout_benefit": self.heldout_benefit,
            "heldout_improvement": round(self.heldout_improvement, 12),
            "heldout_sample_ids": list(self.heldout_sample_ids),
            "holdout_id": self.holdout_id,
            "holdout_isolated": self.holdout_isolated,
            "metric_deltas": {
                str(key): round(float(value), 12)
                for key, value in sorted(self.metric_deltas.items())
            },
            "metric_guardrails_passed": self.metric_guardrails_passed,
            "minimum_improvement": round(self.minimum_improvement, 12),
            "per_family_deltas": _json_ready(self.per_family_deltas),
            "primary_metric": self.primary_metric,
            "production_weight_writes_allowed": self.production_weight_writes_allowed,
            "production_writes_allowed": self.production_writes_allowed,
            "repeat_control_margins": _json_ready(self.repeat_control_margins),
            "report_schema_version": self.report_schema_version,
            "schema_version": self.schema_version,
            "source_copy_guard_passed": self.source_copy_guard_passed,
            "status": self.status,
            "symbolic_validity_guard_passed": self.symbolic_validity_guard_passed,
            "training_sample_ids": list(self.training_sample_ids),
            "trusted_feedback_ablation_evidence": (
                self.to_trusted_feedback_ablation_evidence().to_dict()
            ),
        }


def run_proof_feedback_ablation(
    autoencoder: AdaptiveModalAutoencoder,
    train_samples: Iterable[Any],
    holdout_samples: Iterable[Any],
    *,
    hammer_feedback: Any = (),
    leanstral_feedback: Any = (),
    proof_feedback: Any = (),
    trusted_feedback: Any = (),
    expected_versions: ProofFeedbackVersions | Mapping[str, Any] | str | None = None,
    config: Optional[ProofFeedbackAblationConfig] = None,
    metric_evaluator: Optional[ProofFeedbackMetricEvaluator] = None,
) -> ProofFeedbackAblationReport:
    """Run matched trusted-feedback ablations on cloned model state.

    The caller's ``autoencoder`` is never mutated.  All arms start from the same
    generalizable state, train only on ``train_samples``, and are evaluated with
    sample memory disabled by the default evaluator.
    """

    cfg = config or ProofFeedbackAblationConfig()
    train = tuple(train_samples)
    holdout = tuple(holdout_samples)
    train_ids = tuple(sorted({_sample_id(sample) for sample in train if _sample_id(sample)}))
    holdout_ids = tuple(
        sorted({_sample_id(sample) for sample in holdout if _sample_id(sample)})
    )
    holdout_id = str(cfg.holdout_id or _stable_hash({"holdout_sample_ids": holdout_ids})[:24])
    fixed_sample_set = bool(holdout_id) and bool(holdout_ids)
    holdout_isolated = bool(holdout_ids) and not set(train_ids).intersection(holdout_ids)
    expected = expected_versions or _infer_expected_versions(
        hammer_feedback,
        leanstral_feedback,
        proof_feedback,
        trusted_feedback,
    )

    hammer_items = tuple(_feedback_items(hammer_feedback)) + tuple(
        item
        for item in _feedback_items(proof_feedback)
        if not _is_leanstral_feedback(item)
    )
    leanstral_items = tuple(_feedback_items(leanstral_feedback)) + tuple(
        item
        for item in _feedback_items(trusted_feedback)
        if _is_leanstral_feedback(item)
    )
    verified_items = tuple(hammer_items) + tuple(leanstral_items)
    shuffled_items = tuple(
        _shuffle_feedback_labels(verified_items, repeat_index=0)
    )
    samples_by_id = {sample_id: sample for sample in train if (sample_id := _sample_id(sample))}

    all_results: list[ProofFeedbackAblationArmResult] = []
    for repeat_index in range(int(cfg.repeat_count)):
        arm_feedback = {
            NO_FEEDBACK_ARM: (),
            HAMMER_ONLY_ARM: hammer_items,
            VERIFIED_LEANSTRAL_HAMMER_ARM: verified_items,
            SHUFFLED_LABEL_CONTROL_ARM: (
                _shuffle_feedback_labels(verified_items, repeat_index=repeat_index)
                if repeat_index
                else shuffled_items
            ),
        }
        for arm in PROOF_FEEDBACK_ABLATION_ARMS:
            clone = _clone_autoencoder(autoencoder)
            training_report: Mapping[str, Any] = {}
            feedback_for_arm = arm_feedback[arm]
            if feedback_for_arm:
                trainer = TrustedFeedbackTrainer(
                    clone,
                    expected_versions=expected,
                    config=TrustedFeedbackTrainerConfig(
                        learning_rate=cfg.learning_rate,
                        max_updates_per_batch=cfg.max_updates_per_arm,
                        production_weight_writes_enabled=True,
                        require_ablation=False,
                        require_explicit_train_partition=(
                            cfg.require_explicit_train_partition
                        ),
                    ),
                )
                training_report = trainer.train(
                    feedback_for_arm,
                    samples_by_id,
                    production_weight_writes_enabled=True,
                    learning_rate=cfg.learning_rate,
                ).to_dict()
            metrics, family_metrics = _evaluate_holdout(
                clone,
                holdout,
                arm=arm,
                repeat_index=repeat_index,
                config=cfg,
                evaluator=metric_evaluator,
            )
            all_results.append(
                ProofFeedbackAblationArmResult(
                    arm=arm,
                    repeat_index=repeat_index,
                    training_sample_ids=train_ids,
                    heldout_sample_ids=holdout_ids,
                    holdout_metrics=metrics,
                    view_family_metrics=family_metrics,
                    training_report=training_report,
                    trainable_head_norms=dict(
                        training_report.get("trainable_legal_ir_head_norms", {})
                    )
                    if isinstance(training_report, Mapping)
                    else {},
                )
            )

    by_repeat_arm = {
        (result.repeat_index, result.arm): result
        for result in all_results
    }
    primary_metric = _resolve_primary_metric(
        cfg.primary_metric,
        (result.holdout_metrics for result in all_results),
    )
    baseline_values = [
        _metric_value(
            by_repeat_arm[(repeat, NO_FEEDBACK_ARM)].holdout_metrics,
            primary_metric,
        )
        for repeat in range(int(cfg.repeat_count))
    ]
    candidate_values = [
        _metric_value(
            by_repeat_arm[(repeat, VERIFIED_LEANSTRAL_HAMMER_ARM)].holdout_metrics,
            primary_metric,
        )
        for repeat in range(int(cfg.repeat_count))
    ]
    repeat_margins: list[Mapping[str, float]] = []
    repeat_improvements: list[float] = []
    for repeat in range(int(cfg.repeat_count)):
        candidate = by_repeat_arm[(repeat, VERIFIED_LEANSTRAL_HAMMER_ARM)]
        margins = {}
        for control_arm in (NO_FEEDBACK_ARM, HAMMER_ONLY_ARM, SHUFFLED_LABEL_CONTROL_ARM):
            margin = _metric_improvement(
                by_repeat_arm[(repeat, control_arm)].holdout_metrics,
                candidate.holdout_metrics,
                primary_metric,
            )
            margins[f"{VERIFIED_LEANSTRAL_HAMMER_ARM}_vs_{control_arm}"] = round(
                margin,
                12,
            )
            if control_arm == NO_FEEDBACK_ARM:
                repeat_improvements.append(margin)
        repeat_margins.append(margins)

    baseline_mean = _mean_finite(baseline_values)
    candidate_mean = _mean_finite(candidate_values)
    conservative_improvement = min(repeat_improvements) if repeat_improvements else 0.0
    metric_deltas = _aggregate_metric_deltas(
        [result for result in all_results if result.arm == NO_FEEDBACK_ARM],
        [result for result in all_results if result.arm == VERIFIED_LEANSTRAL_HAMMER_ARM],
    )
    per_family_deltas = {
        arm: _mean_per_family_deltas(
            [
                _per_family_deltas(
                    by_repeat_arm[(repeat, NO_FEEDBACK_ARM)].view_family_metrics,
                    by_repeat_arm[(repeat, arm)].view_family_metrics,
                )
                for repeat in range(int(cfg.repeat_count))
            ]
        )
        for arm in (
            HAMMER_ONLY_ARM,
            VERIFIED_LEANSTRAL_HAMMER_ARM,
            SHUFFLED_LABEL_CONTROL_ARM,
        )
    }

    reasons = _block_reasons(
        fixed_sample_set=fixed_sample_set,
        holdout_isolated=holdout_isolated,
        holdout_ids=holdout_ids,
        primary_metric=primary_metric,
        conservative_improvement=conservative_improvement,
        minimum_improvement=cfg.minimum_improvement,
        repeat_margins=repeat_margins,
        results=all_results,
        metric_tolerance=cfg.metric_tolerance,
    )
    descriptor = {
        "arms": PROOF_FEEDBACK_ABLATION_ARMS,
        "holdout_id": holdout_id,
        "minimum_improvement": cfg.minimum_improvement,
        "primary_metric": primary_metric,
        "repeat_count": cfg.repeat_count,
        "training_sample_ids": train_ids,
        "heldout_sample_ids": holdout_ids,
    }
    lower = primary_metric in _LOWER_IS_BETTER
    evidence_candidate = (
        baseline_mean - conservative_improvement
        if lower
        else baseline_mean + conservative_improvement
    )
    if math.isfinite(candidate_mean):
        evidence_candidate = candidate_mean
    return ProofFeedbackAblationReport(
        ablation_id="lir-proof-feedback-causal-ablation-" + _stable_hash(descriptor)[:24],
        holdout_id=holdout_id,
        primary_metric=primary_metric,
        baseline_primary_value=baseline_mean,
        candidate_primary_value=evidence_candidate,
        heldout_improvement=conservative_improvement,
        minimum_improvement=float(cfg.minimum_improvement),
        training_sample_ids=train_ids,
        heldout_sample_ids=holdout_ids,
        fixed_sample_set=fixed_sample_set,
        holdout_isolated=holdout_isolated,
        source_copy_guard_passed=(
            "source_copy_guardrail_evidence_missing" not in reasons
            and "source_copy_guardrail_regression" not in reasons
        ),
        symbolic_validity_guard_passed=(
            "symbolic_validity_guardrail_evidence_missing" not in reasons
            and "symbolic_validity_guardrail_regression" not in reasons
        ),
        metric_guardrails_passed="heldout_metric_regression" not in reasons,
        arm_results=tuple(all_results),
        per_family_deltas=per_family_deltas,
        repeat_control_margins=tuple(repeat_margins),
        block_reasons=tuple(reasons),
        metric_deltas=metric_deltas,
    )


def evaluate_proof_feedback_ablation(*args: Any, **kwargs: Any) -> ProofFeedbackAblationReport:
    """Compatibility alias for callers using evaluation terminology."""

    return run_proof_feedback_ablation(*args, **kwargs)


def run_trusted_feedback_ablation(*args: Any, **kwargs: Any) -> ProofFeedbackAblationReport:
    """Compatibility alias for the trainer-facing trusted feedback gate."""

    return run_proof_feedback_ablation(*args, **kwargs)


def measure_trusted_feedback_causal_efficacy(
    *args: Any, **kwargs: Any
) -> ProofFeedbackAblationReport:
    """Compatibility alias matching the backlog task wording."""

    return run_proof_feedback_ablation(*args, **kwargs)


def _clone_autoencoder(autoencoder: AdaptiveModalAutoencoder) -> AdaptiveModalAutoencoder:
    clone = object.__new__(autoencoder.__class__)
    clone.__dict__ = dict(autoencoder.__dict__)
    clone.state = autoencoder.state.generalizable_copy()
    clone._sample_feature_cache = {}
    clone._legal_ir_loss_target_cache = {
        key: dict(value)
        for key, value in getattr(autoencoder, "_legal_ir_loss_target_cache", {}).items()
    }
    clone._legal_ir_view_target_cache = {
        key: dict(value)
        for key, value in getattr(autoencoder, "_legal_ir_view_target_cache", {}).items()
    }
    return clone


def _evaluate_holdout(
    autoencoder: AdaptiveModalAutoencoder,
    holdout: Sequence[Any],
    *,
    arm: str,
    repeat_index: int,
    config: ProofFeedbackAblationConfig,
    evaluator: Optional[ProofFeedbackMetricEvaluator],
) -> tuple[dict[str, float], dict[str, Mapping[str, Any]]]:
    raw = (
        evaluator(autoencoder, holdout, arm, repeat_index)
        if evaluator is not None
        else autoencoder.evaluate(
            holdout,
            legal_ir_bridge_names=config.legal_ir_bridge_names,
            legal_ir_evaluate_provers=config.legal_ir_evaluate_provers,
            legal_ir_targets=config.legal_ir_targets,
            legal_ir_parallel_workers=config.legal_ir_parallel_workers,
            use_sample_memory=False,
        )
    )
    metrics = _flatten_metrics(raw)
    family_block = legal_ir_view_family_metric_block(autoencoder_metrics=raw)
    family_metrics = {
        str(family): dict(values)
        for family, values in dict(family_block.get("view_family_metrics", {})).items()
        if isinstance(values, Mapping)
    }
    source_copy_present = _guard_evidence_present(
        raw,
        family_metrics,
        ("source_copy_penalty", "source_copy_reward_hack_penalty"),
    )
    symbolic_present = _guard_evidence_present(
        raw,
        family_metrics,
        ("symbolic_validity_success_rate", "symbolic_validity_penalty"),
    )
    metrics.setdefault("source_copy_penalty", _family_metric_mean(family_metrics, "source_copy_penalty"))
    metrics.setdefault(
        "symbolic_validity_success_rate",
        1.0 - max(0.0, float(metrics.get("symbolic_validity_penalty", 0.0))),
    )
    metrics["source_copy_guard_evidence_present"] = 1.0 if source_copy_present else 0.0
    metrics["symbolic_validity_guard_evidence_present"] = 1.0 if symbolic_present else 0.0
    metrics.setdefault(
        "reconstruction_success_rate",
        1.0 / (1.0 + max(0.0, float(metrics.get("reconstruction_loss", 0.0)))),
    )
    metrics.setdefault(
        "compiler_ir_cross_entropy_loss",
        _family_metric_mean(family_metrics, "ir_cross_entropy_loss"),
    )
    metrics.setdefault(
        "autoencoder_cross_entropy_loss",
        float(metrics.get("cross_entropy_loss", 0.0)),
    )
    metrics.setdefault(
        "legal_ir_view_cross_entropy_loss",
        float(
            metrics.get(
                "legal_ir_view_cross_entropy_loss",
                metrics.get("compiler_ir_cross_entropy_loss", metrics["autoencoder_cross_entropy_loss"]),
            )
        ),
    )
    return metrics, family_metrics


def _flatten_metrics(value: Mapping[str, Any] | AutoencoderEvaluation) -> dict[str, float]:
    payload = value.to_dict() if isinstance(value, AutoencoderEvaluation) else dict(value)
    flattened: dict[str, float] = {}
    for key, child in payload.items():
        if isinstance(child, (int, float)) and not isinstance(child, bool):
            number = float(child)
            if math.isfinite(number):
                flattened[str(key)] = number
        elif key == "legal_ir_losses" and isinstance(child, Mapping):
            for name, metric_value in child.items():
                try:
                    number = float(metric_value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(number):
                    flattened[str(name)] = number
        elif key == "flat_metrics" and isinstance(child, Mapping):
            for name, metric_value in child.items():
                try:
                    number = float(metric_value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(number):
                    flattened[str(name)] = number
    return flattened


def _guard_evidence_present(
    raw: Mapping[str, Any] | AutoencoderEvaluation,
    family_metrics: Mapping[str, Mapping[str, Any]],
    names: Sequence[str],
) -> bool:
    payload = raw.to_dict() if isinstance(raw, AutoencoderEvaluation) else dict(raw)
    if any(name in payload for name in names):
        return True
    losses = payload.get("legal_ir_losses")
    if isinstance(losses, Mapping) and any(name in losses for name in names):
        return True
    for metrics in family_metrics.values():
        observed = metrics.get("observed_metrics")
        if (
            isinstance(observed, Sequence)
            and not isinstance(observed, (bytes, bytearray, str))
            and set(str(name) for name in observed).intersection(names)
        ):
            return True
    return False


def _resolve_primary_metric(
    requested: str,
    metric_sets: Iterable[Mapping[str, Any]],
) -> str:
    if requested:
        return str(requested)
    available: set[str] = set()
    for metrics in metric_sets:
        available.update(str(key) for key in metrics)
    return next((name for name in _PRIMARY_METRIC_CANDIDATES if name in available), "")


def _metric_value(metrics: Mapping[str, Any], metric: str) -> float:
    try:
        value = float(metrics.get(metric, 0.0))
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def _metric_improvement(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    metric: str,
) -> float:
    before = _metric_value(baseline, metric)
    after = _metric_value(candidate, metric)
    return before - after if metric in _LOWER_IS_BETTER else after - before


def _aggregate_metric_deltas(
    baseline_results: Sequence[ProofFeedbackAblationArmResult],
    candidate_results: Sequence[ProofFeedbackAblationArmResult],
) -> dict[str, float]:
    by_metric: dict[str, list[float]] = {}
    for baseline, candidate in zip(baseline_results, candidate_results):
        for metric in sorted(set(baseline.holdout_metrics) & set(candidate.holdout_metrics)):
            by_metric.setdefault(metric, []).append(
                _metric_improvement(baseline.holdout_metrics, candidate.holdout_metrics, metric)
            )
    return {
        metric: round(_mean_finite(values), 12)
        for metric, values in sorted(by_metric.items())
    }


def _repeat_metric_deltas(
    results: Sequence[ProofFeedbackAblationArmResult],
    metric: str,
    *,
    lower_is_better: bool,
) -> list[float]:
    by_repeat_arm = {(result.repeat_index, result.arm): result for result in results}
    margins: list[float] = []
    repeat_indexes = sorted({result.repeat_index for result in results})
    for repeat in repeat_indexes:
        baseline = by_repeat_arm[(repeat, NO_FEEDBACK_ARM)]
        candidate = by_repeat_arm[(repeat, VERIFIED_LEANSTRAL_HAMMER_ARM)]
        before = _metric_value(baseline.holdout_metrics, metric)
        after = _metric_value(candidate.holdout_metrics, metric)
        margins.append(before - after if lower_is_better else after - before)
    return margins


def _block_reasons(
    *,
    fixed_sample_set: bool,
    holdout_isolated: bool,
    holdout_ids: Sequence[str],
    primary_metric: str,
    conservative_improvement: float,
    minimum_improvement: float,
    repeat_margins: Sequence[Mapping[str, float]],
    results: Sequence[ProofFeedbackAblationArmResult],
    metric_tolerance: float,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not fixed_sample_set:
        reasons.append("fixed_holdout_identity_missing_or_mismatched")
    if not holdout_ids:
        reasons.append("heldout_samples_missing")
    if not holdout_isolated:
        reasons.append("train_holdout_overlap")
    if not primary_metric:
        reasons.append("primary_metric_missing")
    if conservative_improvement <= 0.0 or conservative_improvement < float(minimum_improvement):
        reasons.append("heldout_benefit_not_demonstrated")
    if any(
        _metric_value(result.holdout_metrics, "source_copy_guard_evidence_present") <= 0.0
        for result in results
    ):
        reasons.append("source_copy_guardrail_evidence_missing")
    if any(
        _metric_value(result.holdout_metrics, "symbolic_validity_guard_evidence_present") <= 0.0
        for result in results
    ):
        reasons.append("symbolic_validity_guardrail_evidence_missing")
    for margins in repeat_margins:
        if margins.get(f"{VERIFIED_LEANSTRAL_HAMMER_ARM}_vs_{NO_FEEDBACK_ARM}", -math.inf) < float(minimum_improvement):
            reasons.append("verified_feedback_not_better_than_no_feedback")
        if margins.get(f"{VERIFIED_LEANSTRAL_HAMMER_ARM}_vs_{HAMMER_ONLY_ARM}", -math.inf) < float(minimum_improvement):
            reasons.append("verified_feedback_not_better_than_hammer_only")
        if margins.get(f"{VERIFIED_LEANSTRAL_HAMMER_ARM}_vs_{SHUFFLED_LABEL_CONTROL_ARM}", -math.inf) < float(minimum_improvement):
            reasons.append("verified_feedback_not_better_than_shuffled_control")
    if any(
        margin < -float(metric_tolerance)
        for margin in _repeat_metric_deltas(
            results,
            "source_copy_penalty",
            lower_is_better=True,
        )
    ):
        reasons.append("source_copy_guardrail_regression")
    if any(
        margin < -float(metric_tolerance)
        for margin in _repeat_metric_deltas(
            results,
            "symbolic_validity_success_rate",
            lower_is_better=False,
        )
    ):
        reasons.append("symbolic_validity_guardrail_regression")
    for margin in _repeat_metric_deltas(
        results,
        "reconstruction_success_rate",
        lower_is_better=False,
    ):
        if margin < -float(metric_tolerance):
            reasons.append("heldout_metric_regression")
            break
    return tuple(dict.fromkeys(reasons))


def _per_family_deltas(
    baseline: Mapping[str, Mapping[str, Any]],
    candidate: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Mapping[str, Any]]]:
    deltas: dict[str, dict[str, Mapping[str, Any]]] = {}
    for family in LEGAL_IR_VIEW_FAMILIES:
        base_metrics = dict(baseline.get(family, {}) or {})
        candidate_metrics = dict(candidate.get(family, {}) or {})
        family_groups: dict[str, Mapping[str, Any]] = {}
        for group, metric_names in _ATTRIBUTION_GROUPS.items():
            metric_deltas: dict[str, float] = {}
            observed: list[str] = []
            for metric in metric_names:
                if metric in base_metrics or metric in candidate_metrics:
                    observed.append(metric)
                before = _metric_value(base_metrics, metric)
                after = _metric_value(candidate_metrics, metric)
                improvement = before - after if metric in _LOWER_IS_BETTER else after - before
                metric_deltas[metric] = round(improvement, 12)
            family_groups[group] = {
                "metric_deltas": metric_deltas,
                "observed_metrics": observed,
                "score_delta": round(_mean_finite(metric_deltas.values()), 12),
            }
        deltas[family] = family_groups
    return deltas


def _mean_per_family_deltas(
    repeated: Sequence[Mapping[str, Mapping[str, Mapping[str, Any]]]],
) -> dict[str, dict[str, Mapping[str, Any]]]:
    merged: dict[str, dict[str, Mapping[str, Any]]] = {}
    for family in LEGAL_IR_VIEW_FAMILIES:
        merged[family] = {}
        for group, metric_names in _ATTRIBUTION_GROUPS.items():
            metric_values = {
                metric: [
                    float(
                        run[family][group]["metric_deltas"].get(metric, 0.0)
                    )
                    for run in repeated
                ]
                for metric in metric_names
            }
            merged[family][group] = {
                "metric_deltas": {
                    metric: round(_mean_finite(values), 12)
                    for metric, values in metric_values.items()
                },
                "observed_metrics": sorted(
                    {
                        metric
                        for run in repeated
                        for metric in run[family][group].get("observed_metrics", ())
                    }
                ),
                "score_delta": round(
                    _mean_finite(
                        _mean_finite(values)
                        for values in metric_values.values()
                    ),
                    12,
                ),
            }
    return merged


def _feedback_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, LegalIRProofFeedbackRecord):
        return [value]
    if isinstance(value, Mapping):
        nested: list[Any] = []
        for key in (
            "feedback_records",
            "trusted_feedback",
            "verified_guidance",
            "hammer_guidance_artifacts",
            "guidance_items",
            "items",
        ):
            if key in value:
                nested.extend(_feedback_items(value[key]))
        return nested or [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [item for child in value for item in _feedback_items(child)]
    return [value]


def _is_leanstral_feedback(value: Any) -> bool:
    item = _feedback_mapping(value)
    source = str(item.get("source") or item.get("schema_version") or "").lower()
    return "leanstral" in source or any(_truth(item.get(key)) is True for key in _VERIFIER_KEYS if "leanstral" in key)


def _feedback_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, LegalIRProofFeedbackRecord):
        return _record_guidance_mapping(value)
    if isinstance(value, Mapping):
        return {str(key): child for key, child in value.items()}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            converted = to_dict()
        except (TypeError, ValueError):
            return {}
        return dict(converted) if isinstance(converted, Mapping) else {}
    return {}


def _record_guidance_mapping(record: LegalIRProofFeedbackRecord) -> dict[str, Any]:
    return {
        "accepted": record.eligible_for_training,
        "guidance_id": record.record_id,
        "legal_ir_view": record.legal_ir_view,
        "partition": record.partition.value,
        "proof_checked": record.positive,
        "proof_feedback_version_fingerprint": record.version_fingerprint,
        "proved": record.positive,
        "sample_id": record.obligation_id,
        "source": "legal_ir_proof_feedback",
        "target_component": record.legal_ir_view,
        "trusted": record.eligible_for_training,
    }


def _shuffle_feedback_labels(items: Sequence[Any], *, repeat_index: int) -> tuple[Mapping[str, Any], ...]:
    mapped = [_feedback_mapping(item) for item in items]
    mapped = [item for item in mapped if item]
    labels = [
        str(item.get("target_component") or item.get("legal_ir_view") or "").strip()
        for item in mapped
    ]
    shuffled = _rotated_labels(labels, repeat_index=repeat_index)
    output: list[Mapping[str, Any]] = []
    for index, item in enumerate(mapped):
        copy = dict(item)
        label = shuffled[index] if index < len(shuffled) else _alternate_label(labels[index] if index < len(labels) else "")
        copy["target_component"] = label
        copy["legal_ir_view"] = label
        original_id = str(
            copy.get("guidance_id")
            or copy.get("record_id")
            or copy.get("feedback_id")
            or index
        )
        copy["guidance_id"] = f"{original_id}:shuffled:{repeat_index}"
        copy["shuffled_label_control"] = True
        output.append(copy)
    return tuple(output)


def _rotated_labels(labels: Sequence[str], *, repeat_index: int) -> list[str]:
    clean = [label or _alternate_label("") for label in labels]
    if not clean:
        return []
    unique = sorted(set(clean))
    if len(unique) <= 1:
        return [_alternate_label(label) for label in clean]
    shift = 1 + (int(repeat_index) % (len(clean) - 1))
    rotated = clean[shift:] + clean[:shift]
    return [
        rotated[index]
        if rotated[index] != clean[index]
        else _alternate_label(clean[index])
        for index in range(len(clean))
    ]


def _alternate_label(label: str) -> str:
    alternatives = (
        "TDFOL.prover",
        "modal.frame_logic",
        "knowledge_graphs.neo4j_compat",
        "external_provers.router",
        "deontic.ir",
    )
    for alternative in alternatives:
        if alternative != label:
            return alternative
    return "deontic.ir"


def _infer_expected_versions(*sources: Any) -> str:
    for item in _feedback_items(sources):
        if isinstance(item, LegalIRProofFeedbackRecord):
            return item.version_fingerprint
        mapping = _feedback_mapping(item)
        for key in (
            "proof_feedback_version_fingerprint",
            "version_fingerprint",
            "model_version_fingerprint",
        ):
            value = str(mapping.get(key) or "").strip()
            if value:
                return value
        versions = mapping.get("versions")
        if isinstance(versions, ProofFeedbackVersions):
            return versions.fingerprint
        if isinstance(versions, Mapping):
            try:
                return ProofFeedbackVersions.from_dict(versions).fingerprint
            except (KeyError, TypeError, ValueError):
                pass
    return ""


def _sample_id(sample: Any) -> str:
    if isinstance(sample, Mapping):
        return str(sample.get("sample_id") or sample.get("id") or "").strip()
    return str(getattr(sample, "sample_id", "") or getattr(sample, "id", "") or "").strip()


def _family_metric_mean(
    family_metrics: Mapping[str, Mapping[str, Any]],
    metric: str,
) -> float:
    values = [
        _metric_value(metrics, metric)
        for metrics in family_metrics.values()
        if metric in metrics
    ]
    return _mean_finite(values)


def _mean_finite(values: Iterable[Any]) -> float:
    numbers: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            numbers.append(number)
    return sum(numbers) / len(numbers) if numbers else 0.0


def _truth(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value) == 1.0:
            return True
        if float(value) == 0.0:
            return False
    text = str(value or "").strip().lower()
    if text in {"1", "accepted", "passed", "proved", "true", "trusted", "verified", "yes"}:
        return True
    if text in {"0", "false", "failed", "no", "rejected", "untrusted"}:
        return False
    return None


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_json_ready(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return round(value, 12) if math.isfinite(value) else str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(child)
            for key, child in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_ready(child) for child in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


__all__ = [
    "HAMMER_ONLY_ARM",
    "NO_FEEDBACK_ARM",
    "PROOF_FEEDBACK_ABLATION_ARMS",
    "PROOF_FEEDBACK_ABLATION_REPORT_SCHEMA_VERSION",
    "ProofFeedbackAblationArmResult",
    "ProofFeedbackAblationConfig",
    "ProofFeedbackAblationReport",
    "ProofFeedbackMetricEvaluator",
    "SHUFFLED_LABEL_CONTROL_ARM",
    "VERIFIED_LEANSTRAL_HAMMER_ARM",
    "evaluate_proof_feedback_ablation",
    "measure_trusted_feedback_causal_efficacy",
    "run_proof_feedback_ablation",
    "run_trusted_feedback_ablation",
]
