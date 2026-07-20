"""Rollout gates for hammer/Leanstral legal-IR optimizer runs."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_HARD_GUARDRAIL_METRICS = (
    "compiler_ir_cosine",
    "structural_validity",
    "source_copy_penalty",
    "source_copy_reward_hack_penalty",
    "hammer_proof_success_rate",
    "hammer_reconstruction_success_rate",
    "symbolic_validity_success_rate",
)

LEGAL_IR_VIEW_FAMILIES = (
    "deontic",
    "frame_logic",
    "tdfol",
    "kg",
    "cec",
    "external_provers",
    "decompiler",
)

LEGAL_IR_REPRESENTATION_METRICS = (
    "ir_cross_entropy_loss",
    "ir_cosine_similarity",
    "autoencoder_cross_entropy_loss",
    "autoencoder_cosine_similarity",
    "symbolic_validity_success_rate",
    "hammer_proof_success_rate",
    "reconstruction_success_rate",
    "source_copy_penalty",
)

REPRESENTATION_PROMOTION_SUMMARY_KEYS = (
    "latest_legal_ir_learned_guidance_promotion",
    "legal_ir_learned_guidance_promotion",
    "latest_learned_representation_promotion",
    "learned_representation_promotion",
    "latest_representation_promotion",
    "representation_promotion",
)

_LOWER_IS_BETTER_REPRESENTATION_METRICS = frozenset(
    {
        "ir_cross_entropy_loss",
        "autoencoder_cross_entropy_loss",
        "source_copy_penalty",
    }
)

_REPRESENTATION_METRIC_ALIASES = {
    "hammer_reconstruction_success_rate": "reconstruction_success_rate",
    "source_copy_loss": "source_copy_penalty",
    "source_copy_reward_hack_penalty": "source_copy_penalty",
    "structural_validity": "symbolic_validity_success_rate",
    "symbolic_validity": "symbolic_validity_success_rate",
}

DEFAULT_SOURCE_COPY_KEYS = (
    "latest_compiler_ir_source_copy_reward_hack_penalty",
    "latest_compiler_ir_guided_source_copy_reward_hack_penalty",
    "best_validation_ir_guided_source_copy_reward_hack_penalty",
    "compiler_ir_source_copy_reward_hack_penalty",
    "source_copy_reward_hack_penalty",
    "hammer_source_copy_penalty",
    "compiler_ir_hammer_source_copy_penalty",
    "source_copy_penalty",
    "compiler_ir_source_copy_penalty",
)

DEFAULT_FATAL_STOP_REASONS = frozenset(
    {
        "autoencoder_child_failed",
        "codex_child_failed",
        "main_apply_validation_failed",
        "main_apply_validation_failed_rolled_back",
        "paired_timeout_grace_exceeded",
        "target_metric_regression",
        "holdout-target-metric-regression",
        "unhandled_exception",
    }
)

DEFAULT_BACKEND_FATAL_STATUS_TOKENS = (
    "fatal",
    "crash",
    "segfault",
    "panic",
    "oom",
    "out_of_memory",
)

HAMMER_ALLOWED_STATUSES = frozenset(
    {
        "cache_hit",
        "completed",
        "completed_no_hammer_artifacts",
        "completed_persist_failed",
        "skipped_no_samples",
    }
)


@dataclass(frozen=True)
class RolloutGateConfig:
    """Thresholds used to reject a rollout summary."""

    max_validation_ce_regression: float = 0.02
    max_validation_cosine_regression: float = 0.02
    max_compiler_ir_ce_regression: float = 0.05
    max_compiler_ir_cosine_regression: float = 0.05
    max_source_copy_penalty: float = 0.35
    require_hammer_cycle: bool = True
    require_todo_activity: bool = True
    require_available_hammer_backend: bool = False
    max_hammer_backend_unavailable_ratio: float = 1.0
    min_cycles_for_todo_gate: int = 1
    require_representation_promotion: bool = False
    require_successful_representation_promotion: bool = False
    require_complete_representation_evidence: bool = True
    max_per_view_ir_metric_regression: float = 0.0
    max_symbolic_validity_regression: float = 0.0
    max_hammer_proof_rate_regression: float = 0.0
    max_reconstruction_rate_regression: float = 0.0
    max_source_copy_penalty_regression: float = 0.0
    max_todo_productivity_regression: float = 0.0
    required_representation_metrics: tuple[str, ...] = LEGAL_IR_REPRESENTATION_METRICS
    fatal_stop_reasons: frozenset[str] = DEFAULT_FATAL_STOP_REASONS
    source_copy_keys: tuple[str, ...] = DEFAULT_SOURCE_COPY_KEYS


@dataclass
class RolloutGateResult:
    """Structured result for CLI and unit-test callers."""

    accepted: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "failures": list(self.failures),
            "metrics": dict(self.metrics),
            "warnings": list(self.warnings),
        }


def load_summary(path: str | Path) -> dict[str, Any]:
    summary_path = Path(path)
    with summary_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"summary is not a JSON object: {summary_path}")
    return data


def hard_guardrail_metrics_csv() -> str:
    return ",".join(DEFAULT_HARD_GUARDRAIL_METRICS)


def rollout_gate(summary: Mapping[str, Any], config: RolloutGateConfig | None = None) -> RolloutGateResult:
    cfg = config or RolloutGateConfig()
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    failures.extend(_fatal_status_failures(summary, cfg))
    failures.extend(_metric_regression_failures(summary, cfg, metrics))
    failures.extend(_source_copy_failures(summary, cfg, metrics))
    failures.extend(_representation_promotion_failures(summary, cfg, metrics, warnings))
    failures.extend(_hammer_cycle_failures(summary, cfg, metrics, warnings))
    failures.extend(_todo_activity_failures(summary, cfg, metrics))
    failures.extend(_backend_availability_failures(summary, cfg, metrics, warnings))

    return RolloutGateResult(
        accepted=not failures,
        failures=failures,
        warnings=warnings,
        metrics=metrics,
    )


def _fatal_status_failures(summary: Mapping[str, Any], cfg: RolloutGateConfig) -> list[str]:
    failures: list[str] = []
    status = str(summary.get("status") or "").strip().lower()
    if status == "failed":
        failures.append("summary_status_failed")
    stop_reason = str(summary.get("latest_stop_reason") or "").strip()
    if stop_reason and stop_reason in cfg.fatal_stop_reasons:
        failures.append(f"fatal_stop_reason:{stop_reason}")
    autoencoder_exit_code = summary.get("autoencoder_exit_code")
    if _is_nonzero_exit(autoencoder_exit_code):
        failures.append(f"autoencoder_exit_code:{autoencoder_exit_code}")
    codex_exit_codes = summary.get("codex_exit_codes")
    if isinstance(codex_exit_codes, Mapping):
        for run_id, code in codex_exit_codes.items():
            if _is_nonzero_exit(code):
                failures.append(f"codex_exit_code:{run_id}:{code}")
    elif _is_nonzero_exit(summary.get("codex_exit_code")):
        failures.append(f"codex_exit_code:{summary.get('codex_exit_code')}")
    return failures


def _metric_regression_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    validation_ce_delta = _finite_float(summary.get("latest_validation_ce_delta"))
    if validation_ce_delta is not None:
        metrics["latest_validation_ce_delta"] = validation_ce_delta
        if validation_ce_delta > cfg.max_validation_ce_regression:
            failures.append(
                "validation_ce_regression:"
                f"{validation_ce_delta:g}>{cfg.max_validation_ce_regression:g}"
            )

    validation_cosine_delta = _finite_float(summary.get("latest_validation_cosine_delta"))
    if validation_cosine_delta is not None:
        metrics["latest_validation_cosine_delta"] = validation_cosine_delta
        if validation_cosine_delta < -cfg.max_validation_cosine_regression:
            failures.append(
                "validation_cosine_regression:"
                f"{validation_cosine_delta:g}<-{cfg.max_validation_cosine_regression:g}"
            )

    compiler_delta = summary.get("compiler_ir_validation_last_delta")
    if isinstance(compiler_delta, Mapping):
        ir_ce_delta = _finite_float(compiler_delta.get("compiler_ir_cross_entropy_loss"))
        if ir_ce_delta is not None:
            metrics["compiler_ir_cross_entropy_delta"] = ir_ce_delta
            if ir_ce_delta > cfg.max_compiler_ir_ce_regression:
                failures.append(
                    "compiler_ir_ce_regression:"
                    f"{ir_ce_delta:g}>{cfg.max_compiler_ir_ce_regression:g}"
                )
        ir_cos_delta = _finite_float(compiler_delta.get("compiler_ir_cosine_similarity"))
        if ir_cos_delta is not None:
            metrics["compiler_ir_cosine_delta"] = ir_cos_delta
            if ir_cos_delta < -cfg.max_compiler_ir_cosine_regression:
                failures.append(
                    "compiler_ir_cosine_regression:"
                    f"{ir_cos_delta:g}<-{cfg.max_compiler_ir_cosine_regression:g}"
                )
    return failures


def _source_copy_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    source_copy_values = {
        path: value
        for path, value in _collect_named_numeric_values(
            summary, cfg.source_copy_keys
        ).items()
        # Paired promotion baselines are comparison evidence, not the state that
        # would be activated by this rollout.
        if ".baseline." not in f".{path}."
    }
    if source_copy_values:
        metrics["source_copy_penalties"] = dict(sorted(source_copy_values.items()))
    for key, value in sorted(source_copy_values.items()):
        if value > cfg.max_source_copy_penalty:
            failures.append(f"source_copy_penalty:{key}:{value:g}>{cfg.max_source_copy_penalty:g}")
    return failures


def _representation_promotion_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
    warnings: list[str],
) -> list[str]:
    """Fail closed around a learned-representation promotion decision.

    Promotion serializers include convenient pass/fail flags, but rollout safety
    must not depend on those flags being internally consistent.  This check
    therefore recomputes every paired fixed-canary delta from the serialized
    baseline and candidate values.
    """

    failures: list[str] = []
    report_path, report = _representation_promotion_report(summary)
    metrics["representation_promotion_report_present"] = report is not None
    if report is None:
        if cfg.require_representation_promotion:
            failures.append("missing_representation_promotion_report")
        return failures

    metrics["representation_promotion_report_path"] = report_path
    promoted = _promotion_was_allowed(report)
    metrics["representation_promotion_allowed"] = promoted
    block_reasons = _string_sequence(report.get("block_reasons"))
    if block_reasons:
        metrics["representation_promotion_block_reasons"] = block_reasons

    require_success = (
        cfg.require_representation_promotion
        or cfg.require_successful_representation_promotion
    )
    if require_success and not promoted:
        suffix = ",".join(block_reasons) if block_reasons else "unspecified"
        failures.append(f"representation_promotion_blocked:{suffix}")
    elif not promoted:
        warnings.append("representation_promotion_not_activated")

    raw_evidence = report.get("canary_evidence")
    evidence = raw_evidence if isinstance(raw_evidence, Mapping) else None
    evidence_required = promoted or require_success
    if evidence is None:
        if evidence_required:
            failures.append("missing_representation_fixed_canary_evidence")
        else:
            warnings.append("representation_fixed_canary_evidence_absent")
        return failures

    canary_id = str(evidence.get("canary_id") or "").strip()
    fixed_sample_set = evidence.get("fixed_sample_set") is True
    metrics["representation_fixed_canary_id"] = canary_id
    metrics["representation_fixed_sample_set"] = fixed_sample_set
    if evidence_required and not canary_id:
        failures.append("representation_fixed_canary_identity_missing")
    if evidence_required and not fixed_sample_set:
        failures.append("representation_fixed_canary_sample_set_invalid")

    raw_family_metrics = evidence.get("family_metrics")
    family_metrics = (
        raw_family_metrics if isinstance(raw_family_metrics, Mapping) else {}
    )
    represented_families = _represented_view_families(report, family_metrics)
    metrics["representation_view_families"] = list(represented_families)
    if evidence_required and not represented_families:
        failures.append("representation_fixed_canary_view_families_missing")

    enforce_complete = evidence_required and cfg.require_complete_representation_evidence
    family_deltas: dict[str, dict[str, float]] = {}
    for family in represented_families:
        raw_family = family_metrics.get(family)
        if not isinstance(raw_family, Mapping):
            if enforce_complete:
                failures.append(
                    f"representation_canary_family_evidence_missing:{family}"
                )
            continue
        baseline = _normalized_representation_metrics(raw_family.get("baseline"))
        candidate = _normalized_representation_metrics(raw_family.get("candidate"))
        deltas: dict[str, float] = {}
        for metric_name in cfg.required_representation_metrics:
            canonical_name = _REPRESENTATION_METRIC_ALIASES.get(
                metric_name, metric_name
            )
            before = baseline.get(canonical_name)
            after = candidate.get(canonical_name)
            if before is None or after is None:
                if enforce_complete:
                    failures.append(
                        "representation_canary_evidence_incomplete:"
                        f"{family}:{canonical_name}"
                    )
                continue
            improvement = (
                before - after
                if canonical_name in _LOWER_IS_BETTER_REPRESENTATION_METRICS
                else after - before
            )
            deltas[canonical_name] = round(improvement, 12)
            regression = max(0.0, -improvement)
            allowed = _representation_regression_limit(cfg, canonical_name)
            if regression > allowed + 1.0e-12:
                failures.append(
                    _representation_regression_failure(
                        family,
                        canonical_name,
                        before,
                        after,
                        regression,
                        allowed,
                    )
                )
        if deltas:
            family_deltas[family] = dict(sorted(deltas.items()))
    metrics["representation_fixed_canary_improvements"] = family_deltas

    declared_regressions = _declared_representation_regressions(evidence)
    if declared_regressions:
        metrics["representation_declared_regressions"] = declared_regressions
        calculated_markers = {
            failure.split(":", 1)[1].rsplit(":", 2)[0]
            for failure in failures
            if failure.startswith("representation_")
            and "_regression:" in failure
            and failure.count(":") >= 4
        }
        for marker in declared_regressions:
            if marker not in calculated_markers:
                failures.append(f"representation_declared_metric_regression:{marker}")

    missing_declared = _string_sequence(
        evidence.get("missing_guardrail_evidence")
    )
    if missing_declared and evidence_required:
        metrics["representation_declared_missing_evidence"] = missing_declared
        failures.extend(
            f"representation_declared_guardrail_evidence_missing:{item}"
            for item in missing_declared
        )

    productivity = _paired_todo_productivity(summary, report, evidence)
    if productivity is None:
        if enforce_complete:
            failures.append("representation_todo_productivity_evidence_missing")
    else:
        before_productivity, after_productivity, productivity_path = productivity
        improvement = after_productivity - before_productivity
        metrics["representation_todo_productivity"] = {
            "baseline": before_productivity,
            "candidate": after_productivity,
            "evidence_path": productivity_path,
            "improvement": round(improvement, 12),
        }
        regression = max(0.0, -improvement)
        allowed = max(0.0, cfg.max_todo_productivity_regression)
        if regression > allowed + 1.0e-12:
            failures.append(
                "representation_todo_productivity_regression:"
                f"{before_productivity:g}->{after_productivity:g}:"
                f"{regression:g}>{allowed:g}"
            )

    if promoted and evidence.get("guardrails_passed") is not True:
        failures.append("representation_promoted_without_passing_guardrails")
    for reason in block_reasons:
        if "regression" in reason and not any(reason in item for item in failures):
            failures.append(f"representation_promotion_regression:{reason}")
    return list(dict.fromkeys(failures))


def _representation_promotion_report(
    summary: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any] | None]:
    for key in REPRESENTATION_PROMOTION_SUMMARY_KEYS:
        value = summary.get(key)
        if isinstance(value, Mapping):
            return key, value
    for path, value in _walk(summary):
        if not isinstance(value, Mapping):
            continue
        schema = str(value.get("schema_version") or "")
        if schema == "legal-ir-learned-guidance-promotion-v1":
            return path, value
    return "", None


def _promotion_was_allowed(report: Mapping[str, Any]) -> bool:
    return bool(
        report.get("promoted") is True
        or report.get("promotion_allowed") is True
        or str(report.get("status") or "").strip().lower() == "promoted"
    )


def _represented_view_families(
    report: Mapping[str, Any], family_metrics: Mapping[str, Any]
) -> tuple[str, ...]:
    represented = {
        family for family in LEGAL_IR_VIEW_FAMILIES if family in family_metrics
    }
    records = report.get("guidance_records", report.get("records"))
    if isinstance(records, Sequence) and not isinstance(
        records, (str, bytes, bytearray)
    ):
        for record in records:
            if not isinstance(record, Mapping):
                continue
            family = _canonical_view_family(record.get("view_family"))
            if family:
                represented.add(family)
    required = report.get("required_view_families")
    if isinstance(required, Sequence) and not isinstance(
        required, (str, bytes, bytearray)
    ):
        for value in required:
            family = _canonical_view_family(value)
            if family:
                represented.add(family)
    return tuple(family for family in LEGAL_IR_VIEW_FAMILIES if family in represented)


def _canonical_view_family(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "frame": "frame_logic",
        "knowledge_graph": "kg",
        "knowledge_graphs": "kg",
        "external_prover": "external_provers",
    }
    text = aliases.get(text, text)
    return text if text in LEGAL_IR_VIEW_FAMILIES else ""


def _normalized_representation_metrics(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, float] = {}
    for raw_name, raw_value in value.items():
        name = _REPRESENTATION_METRIC_ALIASES.get(str(raw_name), str(raw_name))
        if name not in LEGAL_IR_REPRESENTATION_METRICS:
            continue
        number = _finite_float(raw_value)
        if number is not None:
            normalized[name] = number
    return normalized


def _representation_regression_limit(
    cfg: RolloutGateConfig, metric_name: str
) -> float:
    if metric_name == "symbolic_validity_success_rate":
        return max(0.0, cfg.max_symbolic_validity_regression)
    if metric_name == "hammer_proof_success_rate":
        return max(0.0, cfg.max_hammer_proof_rate_regression)
    if metric_name == "reconstruction_success_rate":
        return max(0.0, cfg.max_reconstruction_rate_regression)
    if metric_name == "source_copy_penalty":
        return max(0.0, cfg.max_source_copy_penalty_regression)
    return max(0.0, cfg.max_per_view_ir_metric_regression)


def _representation_regression_failure(
    family: str,
    metric_name: str,
    before: float,
    after: float,
    regression: float,
    allowed: float,
) -> str:
    prefixes = {
        "symbolic_validity_success_rate": "representation_symbolic_validity_regression",
        "hammer_proof_success_rate": "representation_hammer_proof_rate_regression",
        "reconstruction_success_rate": "representation_reconstruction_rate_regression",
        "source_copy_penalty": "representation_source_copy_penalty_regression",
    }
    prefix = prefixes.get(
        metric_name, "representation_per_view_ir_metric_regression"
    )
    return (
        f"{prefix}:{family}:{metric_name}:{before:g}->{after:g}:"
        f"{regression:g}>{allowed:g}"
    )


def _declared_representation_regressions(
    evidence: Mapping[str, Any],
) -> list[str]:
    result: list[str] = []
    declared_metrics = {
        "metric_regressions": "",
        "source_copy_regressions": "source_copy_penalty",
        "symbolic_validity_regressions": "symbolic_validity_success_rate",
    }
    for key, default_metric in declared_metrics.items():
        for item in _string_sequence(evidence.get(key)):
            marker = (
                item
                if ":" in item or not default_metric
                else f"{item}:{default_metric}"
            )
            if marker not in result:
                result.append(marker)
    return result


def _paired_todo_productivity(
    summary: Mapping[str, Any],
    report: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> tuple[float, float, str] | None:
    containers = (
        ("promotion", report),
        ("canary_evidence", evidence),
        ("summary", summary),
    )
    for container_name, container in containers:
        for key in (
            "todo_generation_productivity",
            "todo_productivity",
            "codex_projection_productivity",
            "todo_generation_productivity_evidence",
        ):
            value = container.get(key)
            if not isinstance(value, Mapping):
                continue
            before = _productivity_value(
                value.get("baseline", value.get("before", value.get("control")))
            )
            after = _productivity_value(
                value.get("candidate", value.get("after", value.get("promoted")))
            )
            if before is not None and after is not None:
                return before, after, f"{container_name}.{key}"
            before = _first_finite(
                value,
                ("baseline_rate", "baseline_count", "before_rate", "control_rate"),
            )
            after = _first_finite(
                value,
                ("candidate_rate", "candidate_count", "after_rate", "promoted_rate"),
            )
            if before is not None and after is not None:
                return before, after, f"{container_name}.{key}"
        before = _first_finite(
            container,
            (
                "baseline_todo_generation_productivity",
                "before_todo_generation_productivity",
                "control_todo_generation_productivity",
            ),
        )
        after = _first_finite(
            container,
            (
                "candidate_todo_generation_productivity",
                "after_todo_generation_productivity",
                "promoted_todo_generation_productivity",
            ),
        )
        if before is not None and after is not None:
            return before, after, container_name
    return None


def _productivity_value(value: Any) -> float | None:
    number = _finite_float(value)
    if number is not None:
        return number
    if not isinstance(value, Mapping):
        return None
    preferred = _first_finite(
        value,
        (
            "productivity",
            "productivity_rate",
            "todos_per_cycle",
            "todos_per_hour",
            "rate",
            "total",
        ),
    )
    if preferred is not None:
        return preferred
    productive_tokens = (
        "accepted",
        "actionable",
        "completed",
        "deduped",
        "generated",
        "projected",
        "seeded",
        "todo",
    )
    values = [
        number
        for key, raw in value.items()
        if any(token in str(key).lower() for token in productive_tokens)
        and (number := _finite_float(raw)) is not None
    ]
    return sum(values) if values else None


def _first_finite(
    payload: Mapping[str, Any], keys: Sequence[str]
) -> float | None:
    for key in keys:
        number = _finite_float(payload.get(key))
        if number is not None:
            return number
    return None


def _string_sequence(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        return []
    return [str(item) for item in value if str(item)]


def _hammer_cycle_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
    warnings: list[str],
) -> list[str]:
    failures: list[str] = []
    hammer_report = summary.get("latest_daemon_hammer_guidance")
    has_hammer_report = isinstance(hammer_report, Mapping) and bool(hammer_report)
    metrics["hammer_report_present"] = has_hammer_report
    if not cfg.require_hammer_cycle:
        return failures
    if not has_hammer_report:
        failures.append("missing_daemon_hammer_guidance_report")
        return failures

    status = str(hammer_report.get("status") or "").strip()
    metrics["hammer_status"] = status
    if status not in HAMMER_ALLOWED_STATUSES:
        failures.append(f"hammer_status_unexpected:{status or 'empty'}")

    runtime_failure_count = int(_finite_float(hammer_report.get("runtime_failure_count"), 0.0) or 0)
    obligation_failure_count = int(
        _finite_float(hammer_report.get("obligation_failure_count"), 0.0) or 0
    )
    metrics["hammer_runtime_failure_count"] = runtime_failure_count
    metrics["hammer_obligation_failure_count"] = obligation_failure_count
    if runtime_failure_count > 0:
        warnings.append(f"hammer_runtime_failures_reported:{runtime_failure_count}")
    if obligation_failure_count > 0:
        warnings.append(f"hammer_obligation_failures_reported:{obligation_failure_count}")
    return failures


def _todo_activity_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    if not cfg.require_todo_activity:
        return failures

    cycles = int(_finite_float(summary.get("cycles"), 0.0) or 0)
    metrics["cycles"] = cycles
    if cycles < cfg.min_cycles_for_todo_gate:
        return failures

    active_todo_supervisor = summary.get("active_cycle_todo_supervisor")
    if isinstance(active_todo_supervisor, Mapping):
        skip_reason = str(active_todo_supervisor.get("skip_reason") or "")
        if skip_reason == "todo_supervisor_disabled":
            failures.append("todo_generation_disabled")

    queue_counts = {
        "pending": int(_finite_float(summary.get("program_synthesis_pending"), 0.0) or 0),
        "claimed": int(_finite_float(summary.get("program_synthesis_claimed"), 0.0) or 0),
        "completed": int(_finite_float(summary.get("program_synthesis_completed"), 0.0) or 0),
        "seeded": int(_finite_float(summary.get("program_synthesis_seeded"), 0.0) or 0),
        "deduped": int(_finite_float(summary.get("program_synthesis_deduped_total"), 0.0) or 0),
        "hammer_projected": int(
            _finite_float(summary.get("hammer_projected_todo_count_total"), 0.0) or 0
        ),
        "leanstral_projected": int(
            _finite_float(summary.get("leanstral_projection_seeded_total"), 0.0) or 0
        ),
    }
    latest_seeded = int(_finite_float(summary.get("latest_program_synthesis_seeded_count"), 0.0) or 0)
    latest_preinsert_deduped = int(
        _finite_float(summary.get("latest_program_synthesis_preinsert_deduped_count"), 0.0)
        or 0
    )
    queue_counts["latest_seeded"] = latest_seeded
    queue_counts["latest_preinsert_deduped"] = latest_preinsert_deduped
    metrics["program_synthesis_activity"] = dict(queue_counts)
    if sum(queue_counts.values()) <= 0:
        failures.append("todo_generation_stalled:no_program_synthesis_activity")
    return failures


def _backend_availability_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
    warnings: list[str],
) -> list[str]:
    failures: list[str] = []
    fatal_paths = list(_find_backend_fatal_paths(summary))
    if fatal_paths:
        metrics["backend_fatal_paths"] = fatal_paths
        failures.extend(f"fatal_backend_availability:{path}" for path in fatal_paths)

    unavailable_ratio = _hammer_backend_unavailable_ratio(summary)
    if unavailable_ratio is not None:
        metrics["hammer_backend_unavailable_ratio"] = unavailable_ratio
        if unavailable_ratio >= 1.0:
            warnings.append("all_hammer_backends_unavailable")
        if (
            cfg.require_available_hammer_backend
            and unavailable_ratio > cfg.max_hammer_backend_unavailable_ratio
        ):
            failures.append(
                "hammer_backend_unavailable_ratio:"
                f"{unavailable_ratio:g}>{cfg.max_hammer_backend_unavailable_ratio:g}"
            )
    return failures


def _is_nonzero_exit(value: Any) -> bool:
    if value is None:
        return False
    number = _finite_float(value)
    return number is not None and int(number) != 0


def _finite_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _collect_named_numeric_values(
    payload: Mapping[str, Any],
    keys: Sequence[str],
) -> dict[str, float]:
    wanted = set(keys)
    values: dict[str, float] = {}
    for path, value in _walk(payload):
        leaf = path.rsplit(".", 1)[-1]
        if leaf not in wanted:
            continue
        number = _finite_float(value)
        if number is not None:
            values[path] = number
    return values


def _hammer_backend_unavailable_ratio(summary: Mapping[str, Any]) -> float | None:
    for path, value in _walk(summary):
        if not path.endswith("hammer_backend_unavailable_ratio"):
            continue
        number = _finite_float(value)
        if number is not None:
            return number
    hammer_report = summary.get("latest_daemon_hammer_guidance")
    if isinstance(hammer_report, Mapping):
        metrics = hammer_report.get("hammer_metrics")
        if isinstance(metrics, Mapping):
            number = _finite_float(metrics.get("hammer_backend_unavailable_ratio"))
            if number is not None:
                return number
    return None


def _find_backend_fatal_paths(payload: Any, prefix: str = "") -> Iterable[str]:
    for path, value in _walk(payload, prefix=prefix):
        leaf = path.rsplit(".", 1)[-1].lower()
        if "backend" not in path.lower() and "solver" not in path.lower():
            continue
        if leaf in {"fatal", "fatal_error", "fatal_backend_error"} and bool(value):
            yield path
        if isinstance(value, str):
            lower = value.lower()
            if any(token in lower for token in DEFAULT_BACKEND_FATAL_STATUS_TOKENS):
                yield path


def _walk(payload: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key)
            child_prefix = f"{prefix}.{key_text}" if prefix else key_text
            yield child_prefix, value
            yield from _walk(value, prefix=child_prefix)
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for index, value in enumerate(payload):
            child_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
            yield child_prefix, value
            yield from _walk(value, prefix=child_prefix)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    metrics_parser = subparsers.add_parser("guardrail-metrics")
    metrics_parser.set_defaults(func=_cmd_guardrail_metrics)

    gate_parser = subparsers.add_parser("gate")
    gate_parser.add_argument("--summary-path", required=True, type=Path)
    gate_parser.add_argument("--max-validation-ce-regression", type=float, default=0.02)
    gate_parser.add_argument("--max-validation-cosine-regression", type=float, default=0.02)
    gate_parser.add_argument("--max-compiler-ir-ce-regression", type=float, default=0.05)
    gate_parser.add_argument("--max-compiler-ir-cosine-regression", type=float, default=0.05)
    gate_parser.add_argument("--max-source-copy-penalty", type=float, default=0.35)
    gate_parser.add_argument("--require-hammer-cycle", action=argparse.BooleanOptionalAction, default=True)
    gate_parser.add_argument("--require-todo-activity", action=argparse.BooleanOptionalAction, default=True)
    gate_parser.add_argument(
        "--require-available-hammer-backend",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    gate_parser.add_argument("--max-hammer-backend-unavailable-ratio", type=float, default=1.0)
    gate_parser.add_argument("--min-cycles-for-todo-gate", type=int, default=1)
    gate_parser.add_argument(
        "--require-representation-promotion",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require a learned-guidance promotion report in the run summary",
    )
    gate_parser.add_argument(
        "--require-successful-representation-promotion",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Reject a supervised run when representation promotion was blocked",
    )
    gate_parser.add_argument(
        "--require-complete-representation-evidence",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require all eight metrics and paired TODO productivity evidence",
    )
    gate_parser.add_argument("--max-per-view-ir-metric-regression", type=float, default=0.0)
    gate_parser.add_argument("--max-symbolic-validity-regression", type=float, default=0.0)
    gate_parser.add_argument("--max-hammer-proof-rate-regression", type=float, default=0.0)
    gate_parser.add_argument("--max-reconstruction-rate-regression", type=float, default=0.0)
    gate_parser.add_argument("--max-source-copy-penalty-regression", type=float, default=0.0)
    gate_parser.add_argument("--max-todo-productivity-regression", type=float, default=0.0)
    gate_parser.set_defaults(func=_cmd_gate)
    return parser


def _cmd_guardrail_metrics(args: argparse.Namespace) -> int:
    print(hard_guardrail_metrics_csv())
    return 0


def _cmd_gate(args: argparse.Namespace) -> int:
    summary = load_summary(args.summary_path)
    result = rollout_gate(
        summary,
        RolloutGateConfig(
            max_validation_ce_regression=args.max_validation_ce_regression,
            max_validation_cosine_regression=args.max_validation_cosine_regression,
            max_compiler_ir_ce_regression=args.max_compiler_ir_ce_regression,
            max_compiler_ir_cosine_regression=args.max_compiler_ir_cosine_regression,
            max_source_copy_penalty=args.max_source_copy_penalty,
            require_hammer_cycle=args.require_hammer_cycle,
            require_todo_activity=args.require_todo_activity,
            require_available_hammer_backend=args.require_available_hammer_backend,
            max_hammer_backend_unavailable_ratio=args.max_hammer_backend_unavailable_ratio,
            min_cycles_for_todo_gate=args.min_cycles_for_todo_gate,
            require_representation_promotion=args.require_representation_promotion,
            require_successful_representation_promotion=(
                args.require_successful_representation_promotion
            ),
            require_complete_representation_evidence=(
                args.require_complete_representation_evidence
            ),
            max_per_view_ir_metric_regression=(
                args.max_per_view_ir_metric_regression
            ),
            max_symbolic_validity_regression=args.max_symbolic_validity_regression,
            max_hammer_proof_rate_regression=args.max_hammer_proof_rate_regression,
            max_reconstruction_rate_regression=args.max_reconstruction_rate_regression,
            max_source_copy_penalty_regression=(
                args.max_source_copy_penalty_regression
            ),
            max_todo_productivity_regression=args.max_todo_productivity_regression,
        ),
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.accepted else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
