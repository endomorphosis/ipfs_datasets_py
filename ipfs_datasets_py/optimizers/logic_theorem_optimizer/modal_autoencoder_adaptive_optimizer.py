"""Bounded, job-local search policy for guarded sparse projection updates.

This is accepted-parameter-step momentum, not an autograd/Adam optimizer. It
never sees validation rows, writes a weight schema, or retains state across jobs.
"""
from __future__ import annotations

from collections import Counter
import math
from typing import Any, Iterable, Mapping


OPTIMIZER_SCOPE = "job_local_reset_per_training_call"
MAX_MOMENTUM_COORDINATES = 8192
# Only reusable heads used by projection. Sample memories and proof metadata
# are intentionally absent, including when supplied in an otherwise valid patch.
MOMENTUM_COMPONENTS = frozenset({
    "compiler_quality_embedding_weights", "compiler_quality_family_logits",
    "logic_signature_embedding_weights", "logic_signature_family_logits",
    "logic_signature_legal_ir_view_logits", "round_trip_signal_embedding_weights",
    "round_trip_signal_family_logits", "round_trip_signal_legal_ir_view_logits",
    "decompiler_plan_embedding_weights", "decompiler_plan_family_logits",
    "decompiler_plan_legal_ir_view_logits", "predicate_argument_embedding_weights",
    "predicate_argument_family_logits", "predicate_argument_legal_ir_view_logits",
    "feature_embedding_weights", "family_embedding_weights",
    "family_semantic_slot_embedding_weights", "family_semantic_slot_legal_ir_view_embedding_weights",
    "family_legal_ir_view_embedding_weights", "semantic_slot_embedding_weights",
    "feature_family_logits", "semantic_slot_family_logits", "legal_ir_view_logits",
    "legal_ir_view_embedding_weights", "legal_ir_view_family_logits",
    "feature_legal_ir_view_logits", "family_semantic_slot_legal_ir_view_logits",
    "semantic_slot_legal_ir_view_embedding_weights", "semantic_slot_legal_ir_view_family_logits",
    "semantic_slot_legal_ir_view_logits",
})


def nonfinite_evaluation_fields(evaluation: Any) -> list[str]:
    """Inspect raw metrics before objective normalizers can conceal NaN."""
    values = {
        name: getattr(evaluation, name, 0.0)
        for name in (
            "embedding_cosine_similarity", "cosine_loss", "reconstruction_loss",
            "cross_entropy_loss", "cross_entropy_excess_loss", "cross_entropy_entropy_loss",
            "frame_ranking_loss", "symbolic_validity_penalty",
        )
    }
    values.update({f"legal_ir_losses.{name}": value
                   for name, value in evaluation.legal_ir_losses.items()})
    for family, metrics in evaluation.legal_ir_view_family_metrics.items():
        values.update({f"legal_ir_view_family_metrics.{family}.{name}": value
                       for name, value in metrics.items()})
    invalid = []
    for name, value in values.items():
        try:
            finite = math.isfinite(float(value))
        except (TypeError, ValueError, OverflowError):
            finite = False
        if not finite:
            invalid.append(name)
    return sorted(invalid)


def validate_optimizer_options(*, mode: str, momentum: float, epochs: int,
                               learning_rate: float, max_seconds: float | None,
                               max_attempts: int | None, l2: float,
                               prescreen: str, deadband: str,
                               training: list[Any], validation: list[Any]) -> str:
    if not isinstance(mode, str) or mode not in {"fixed", "guarded_adaptive"}:
        raise ValueError("projection_optimizer_mode must be fixed or guarded_adaptive")
    if isinstance(momentum, bool):
        raise ValueError("projection_momentum must be a number, not bool")
    beta = float(momentum)
    if not math.isfinite(beta) or not 0.0 <= beta <= 0.9:
        raise ValueError("projection_momentum must be finite and between 0 and 0.9")
    if mode == "fixed":
        if beta:
            raise ValueError("positive projection_momentum requires guarded_adaptive")
        return mode
    if type(epochs) is not int or not 1 <= epochs <= 32:
        raise ValueError("guarded_adaptive requires integer epochs from 1 to 32")
    if not math.isfinite(float(learning_rate)) or not 0.0 < float(learning_rate) <= 1.0:
        raise ValueError("guarded_adaptive requires learning_rate in (0, 1]")
    if float(learning_rate) * 0.35 == 0.0:
        raise ValueError("guarded_adaptive learning_rate underflows a projection head rate")
    if max_seconds is None or not math.isfinite(float(max_seconds)) or not 0.0 < float(max_seconds) <= 300.0:
        raise ValueError("guarded_adaptive requires finite max_seconds in (0, 300]")
    if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
        raise ValueError("guarded_adaptive requires explicit max_line_search_attempts from 1 to 10")
    if beta and max_attempts < 2:
        raise ValueError("positive projection_momentum requires at least two line-search attempts")
    if float(l2) != 0.0:
        raise ValueError("guarded_adaptive requires zero l2_regularization")
    if prescreen != "off" or deadband != "off":
        raise ValueError("guarded_adaptive requires prescreen and deadband off")
    if not training or not validation:
        raise ValueError("guarded_adaptive requires training and disjoint validation samples")
    for attribute in ("sample_id", "normalized_text"):
        train_keys = {str(getattr(row, attribute, "") or "") for row in training} - {""}
        validation_keys = {str(getattr(row, attribute, "") or "") for row in validation} - {""}
        if train_keys & validation_keys:
            raise ValueError("guarded_adaptive requires disjoint validation samples")
    return mode


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _pairs(before: Any, after: Any, path: tuple = ()) -> Iterable[tuple[tuple, float, float]]:
    if _numeric(before) and _numeric(after):
        a, b = float(before), float(after)
        if math.isfinite(a) and math.isfinite(b):
            yield path, a, b
    elif isinstance(before, Mapping) and isinstance(after, Mapping):
        for key in before:
            if key in after:
                yield from _pairs(before[key], after[key], (*path, key))
    elif isinstance(before, (list, tuple)) and isinstance(after, (list, tuple)) and len(before) == len(after):
        for index, (a, b) in enumerate(zip(before, after)):
            yield from _pairs(a, b, (*path, index))


def _patch_coordinates(patch: Any) -> Iterable[tuple[tuple, float, float]]:
    # Whole-component replacements, inserted rows and inserted coordinates do
    # not establish a known initialization baseline and cannot carry momentum.
    for row in patch.rows:
        if row.component in MOMENTUM_COMPONENTS and row.before_exists and row.after_exists:
            for path, before, after in _pairs(row.before_value, row.after_value):
                if before != after:
                    yield (row.component, row.key, path), before, after


def parameter_step_report(patch: Any) -> dict[str, Any]:
    norm = 0.0
    count = 0
    for _key, before, after in _patch_coordinates(patch):
        norm = math.hypot(norm, after - before)
        count += 1
    return {
        "parameter_delta_norm": norm,
        "parameter_delta_coordinate_count": count,
        "parameter_delta_scope": "existing_numeric_trainable_coordinates_only",
        "inserted_rows_excluded": sum(row.component in MOMENTUM_COMPONENTS and not row.before_exists
                                      for row in patch.rows),
        "autograd_gradient": False,
    }


def _set_coordinate(state: Any, key: tuple, value: float) -> None:
    component, row_key, path = key
    table = getattr(state, component)
    if not path:
        table[row_key] = value
        return
    node = table[row_key]
    for item in path[:-1]:
        node = node[item]
    node[path[-1]] = value


class GuardedAdaptiveProjection:
    """At most five per-head rates and one bounded accepted sparse direction."""

    def __init__(self, learning_rate: float, scales: Mapping[str, float], momentum: float):
        self.rates = {head: min(1.0, float(learning_rate) * scale) for head, scale in scales.items()}
        self.floors = {head: min(rate, max(1.0e-12, rate / 1024.0)) for head, rate in self.rates.items()}
        self.momentum = float(momentum)
        self.history: dict[tuple, tuple[float, float]] = {}
        self.history_head: str | None = None
        self.phase_counts: Counter = Counter()
        self.reset_reasons: Counter = Counter()
        self.plateau_count = 0
        self.truncated_histories = 0

    def reset(self, reason: str) -> None:
        if self.history:
            self.reset_reasons[reason] += 1
        self.history.clear()
        self.history_head = None

    def backoff(self, head: str, rate: float) -> float:
        return max(self.floors[head], min(1.0, rate * 0.5))

    def finish_head(self, head: str, rate: float, accepted: bool) -> None:
        self.rates[head] = min(1.0, rate * 1.25) if accepted else self.backoff(head, rate)
        self.phase_counts["guarded_positive" if accepted else "head_rejected"] += 1

    def prepare(self, state: Any, patch: Any, *, head: str, allow_momentum: bool,
                logit_clip: float) -> dict[str, Any]:
        report = parameter_step_report(patch)
        report.update({"momentum_applied": False, "momentum_carry_norm": 0.0,
                       "momentum_coordinate_count": 0, "momentum_restart_reason": None})
        if not allow_momentum or not self.momentum or self.history_head != head or not self.history:
            return report
        matches = []
        fresh_norm = previous_norm = alignment = 0.0
        for key, before, after in _patch_coordinates(patch):
            previous = self.history.get(key)
            if previous is None or before != previous[1]:
                continue
            fresh = after - before
            previous_delta = previous[0]
            if not math.isfinite(fresh) or not math.isfinite(previous_delta):
                continue
            # Stored logits can exceed the reader's clipping interval. Leave
            # such a fresh proposal unchanged rather than applying a new clip.
            if "logits" in key[0] and logit_clip > 0 and abs(after) > logit_clip:
                continue
            matches.append((key, after, previous_delta))
            fresh_norm = math.hypot(fresh_norm, fresh)
            previous_norm = math.hypot(previous_norm, previous_delta)
            alignment += fresh * previous_delta
        reason = None
        if not matches or fresh_norm == 0.0 or previous_norm == 0.0:
            reason = "no_current_direction_intersection"
        elif not math.isfinite(alignment) or alignment <= 0.0:
            reason = "nonpositive_direction_alignment"
        if reason:
            self.reset(reason)
            report["momentum_restart_reason"] = reason
            return report
        # Carry is no greater than beta times this proposal's fresh norm.
        scale = self.momentum * min(1.0, fresh_norm / previous_norm)
        carry_norm = 0.0
        count = 0
        for key, after, delta in matches:
            value = after + scale * delta
            if "logits" in key[0] and logit_clip > 0.0:
                value = max(-logit_clip, min(logit_clip, value))
            if not math.isfinite(value):
                self.reset("nonfinite_carry")
                raise ValueError("nonfinite sparse momentum carry")
            if value != after:
                _set_coordinate(state, key, value)
                carry_norm = math.hypot(carry_norm, value - after)
                count += 1
        report.update({"momentum_applied": bool(count), "momentum_carry_norm": carry_norm,
                       "momentum_coordinate_count": count})
        return report

    def committed(self, head: str, patch: Any) -> None:
        self.plateau_count = 0
        self.reset("selected_patch_replaces_history")
        if not self.momentum:
            return
        # A composed update has another objective/step schedule: start its next
        # search from a plain update instead of attributing that step to a head.
        if head not in self.rates:
            self.reset_reasons["composed_update"] += 1
            return
        self.history_head = head
        for key, before, after in _patch_coordinates(patch):
            delta = after - before
            if not math.isfinite(delta):
                continue
            if len(self.history) >= MAX_MOMENTUM_COORDINATES:
                self.truncated_histories += 1
                break
            self.history[key] = (delta, after)

    def recover_plateau(self) -> bool:
        self.reset("plateau")
        self.plateau_count += 1
        self.phase_counts["plateau_sweep"] += 1
        return self.plateau_count <= 1

    def report(self) -> dict[str, Any]:
        return {
            "projection_optimizer_mode": "guarded_adaptive",
            "projection_optimizer_scope": OPTIMIZER_SCOPE,
            "projection_momentum": self.momentum,
            "optimizer_history_persisted": False,
            "projection_optimizer": {
                "learning_rates": dict(sorted(self.rates.items())),
                "phase_counts": dict(sorted(self.phase_counts.items())),
                "momentum_reset_reasons": dict(sorted(self.reset_reasons.items())),
                "momentum_history_coordinate_limit": MAX_MOMENTUM_COORDINATES,
                "momentum_history_coordinate_count": len(self.history),
                "momentum_history_truncation_count": self.truncated_histories,
                "momentum_direction": "selected_committed_parameter_delta",
                "validation_gradients_used": False,
                "global_minimum_claimed": False,
            },
        }
