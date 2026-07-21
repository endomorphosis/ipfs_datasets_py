"""Rollout gates for hammer/Leanstral legal-IR optimizer runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
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


STAGED_ROLLOUT_SCHEMA_VERSION = "legal-ir-hammer-leanstral-rollout-v1"
LEGAL_IR_LEARNED_GUIDANCE_PROMOTION_SCHEMA_VERSION = (
    "legal-ir-learned-guidance-promotion-v1"
)
LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION = (
    "legal-ir-stable-autoencoder-feature-export-v1"
)


@dataclass(frozen=True)
class RolloutStageSpec:
    """One immutable step in the production rollout contract."""

    name: str
    duration_seconds: int


STAGED_ROLLOUT_STAGES = (
    RolloutStageSpec("short_smoke", 10 * 60),
    RolloutStageSpec("one_hour_hparam", 60 * 60),
    RolloutStageSpec("eight_hour_canary", 8 * 60 * 60),
    RolloutStageSpec("twenty_four_hour_production", 24 * 60 * 60),
)

STAGED_HARD_GUARDRAILS = (
    "semantic",
    "provenance",
    "anti_copy",
    "hammer_proof",
    "lean_reconstruction",
    "process_lifecycle",
    "queue_lag",
)


@dataclass(frozen=True)
class StagedRolloutConfig:
    """Fail-closed policy for promotion through the four rollout stages."""

    require_all_stages: bool = True
    require_complete_snapshots: bool = True
    require_managed_process_evidence: bool = True
    require_trusted_feedback: bool = True
    require_rollback_evidence: bool = True
    require_representation_promotion_reports: bool = True
    require_successful_representation_promotion: bool = False
    require_complete_representation_evidence: bool = True
    verify_rollback_artifacts: bool = False
    duration_tolerance_seconds: float = 0.0
    max_queue_lag_p95_seconds: float = 120.0
    max_queue_lag_regression: float = 0.0
    max_accepted_patches_per_hour_regression: float = 0.0
    required_families: tuple[str, ...] = LEGAL_IR_VIEW_FAMILIES
    required_guardrails: tuple[str, ...] = STAGED_HARD_GUARDRAILS


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


def staged_rollout_gate(
    snapshots: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    config: StagedRolloutConfig | None = None,
) -> RolloutGateResult:
    """Evaluate a complete rollout or an explicitly allowed ordered prefix.

    The staged contract deliberately consumes persisted snapshots, rather than
    live process state.  A stage is promotable only when the snapshot proves
    its duration, guardrails, process cleanup, feedback delivery, productivity,
    and rollback point.  Missing evidence is a failure, never a warning.
    """

    cfg = config or StagedRolloutConfig()
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {
        "schema_version": STAGED_ROLLOUT_SCHEMA_VERSION,
        "expected_stage_sequence": [stage.name for stage in STAGED_ROLLOUT_STAGES],
    }
    items, envelope_failures = _staged_snapshot_items(snapshots)
    failures.extend(envelope_failures)
    expected_count = len(STAGED_ROLLOUT_STAGES)
    if not items:
        failures.append("stage_sequence:no_snapshots")
    if len(items) > expected_count:
        failures.append(f"stage_sequence:too_many_snapshots:{len(items)}>{expected_count}")
    if cfg.require_all_stages and len(items) != expected_count:
        failures.append(
            f"stage_sequence:incomplete:{len(items)}/{expected_count}"
        )

    completed: list[str] = []
    rates: dict[str, float] = {}
    queue_lags: dict[str, float] = {}
    rollback: dict[str, dict[str, Any]] = {}
    previous_rate: float | None = None
    previous_queue_lag: float | None = None

    for index, snapshot in enumerate(items[:expected_count]):
        expected = STAGED_ROLLOUT_STAGES[index]
        stage_name = str(snapshot.get("stage") or snapshot.get("stage_name") or "").strip()
        if stage_name != expected.name:
            failures.append(
                f"stage_sequence:index_{index}:expected_{expected.name}:got_{stage_name or 'missing'}"
            )
            # Attribute subsequent failures to the expected slot so malformed
            # names cannot create ambiguous or attacker-controlled diagnostics.
        stage_label = expected.name
        completed.append(stage_name or stage_label)

        duration = _first_finite(snapshot, ("duration_seconds", "planned_duration_seconds"))
        if duration is None:
            failures.append(f"stage_duration_missing:{stage_label}")
        elif abs(duration - expected.duration_seconds) > max(0.0, cfg.duration_tolerance_seconds):
            failures.append(
                f"stage_duration:{stage_label}:{duration:g}!={expected.duration_seconds}"
            )

        elapsed = _first_finite(snapshot, ("elapsed_seconds", "wall_clock_seconds"))
        if elapsed is None or elapsed <= 0.0:
            failures.append(f"stage_wall_clock_missing:{stage_label}")
        elif elapsed + max(0.0, cfg.duration_tolerance_seconds) < expected.duration_seconds:
            failures.append(
                f"stage_duration:{stage_label}:elapsed_{elapsed:g}<"
                f"{expected.duration_seconds}"
            )
        status = str(snapshot.get("status") or "").strip().lower()
        if status not in {"completed", "passed", "succeeded", "success"}:
            failures.append(f"stage_status:{stage_label}:{status or 'missing'}")
        if cfg.require_complete_snapshots and snapshot.get("snapshot_complete") is not True:
            failures.append(f"incomplete_snapshot:{stage_label}")

        failures.extend(_managed_process_failures(snapshot, stage_label, cfg))
        failures.extend(_family_guardrail_failures(snapshot, stage_label, cfg))
        failures.extend(_trusted_feedback_failures(snapshot, stage_label, cfg))
        failures.extend(_representation_snapshot_failures(snapshot, stage_label, cfg))

        queue_lag = _stage_queue_lag(snapshot)
        if queue_lag is None:
            failures.append(f"queue_lag_evidence_missing:{stage_label}")
        else:
            queue_lags[stage_label] = queue_lag
            if queue_lag > cfg.max_queue_lag_p95_seconds:
                failures.append(
                    f"queue_lag_limit_exceeded:{stage_label}:{queue_lag:g}>"
                    f"{cfg.max_queue_lag_p95_seconds:g}"
                )
            if (
                previous_queue_lag is not None
                and queue_lag - previous_queue_lag > cfg.max_queue_lag_regression + 1.0e-12
            ):
                failures.append(
                    f"queue_lag_regression:{stage_label}:{previous_queue_lag:g}->"
                    f"{queue_lag:g}"
                )
            previous_queue_lag = queue_lag

        patch_count = _first_finite(
            snapshot,
            ("accepted_patches", "codex_accepted_patch_count", "codex_main_apply_count"),
        )
        wall_clock = _first_finite(snapshot, ("wall_clock_seconds", "elapsed_seconds"))
        if patch_count is None or patch_count < 0.0 or wall_clock is None or wall_clock <= 0.0:
            failures.append(f"accepted_patch_productivity_evidence_missing:{stage_label}")
        else:
            rate = patch_count * 3600.0 / wall_clock
            rates[stage_label] = round(rate, 12)
            if (
                previous_rate is not None
                and previous_rate - rate
                > cfg.max_accepted_patches_per_hour_regression + 1.0e-12
            ):
                failures.append(
                    f"accepted_patches_per_hour_regression:{stage_label}:"
                    f"{previous_rate:g}->{rate:g}"
                )
            previous_rate = rate

        rollback_value, rollback_failures = _validated_rollback_evidence(
            snapshot, stage_label, cfg
        )
        failures.extend(rollback_failures)
        if rollback_value is not None:
            rollback[stage_label] = rollback_value

    next_stage = (
        STAGED_ROLLOUT_STAGES[len(items)].name
        if len(items) < expected_count
        else None
    )
    metrics.update(
        {
            "completed_stages": completed,
            "next_stage": next_stage,
            "accepted_patches_per_hour": rates,
            "accepted_patches_per_wall_clock_hour": rates,
            "queue_lag_p95_seconds": queue_lags,
            "rollback_evidence": rollback,
            "trusted_feedback_reached_autoencoder": not any(
                item.startswith("trusted_feedback_") for item in failures
            ) and bool(items),
        }
    )
    return RolloutGateResult(
        accepted=not failures,
        failures=list(dict.fromkeys(failures)),
        warnings=warnings,
        metrics=metrics,
    )


def _staged_snapshot_items(
    value: Sequence[Mapping[str, Any]] | Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], list[str]]:
    failures: list[str] = []
    raw: Any = value
    if isinstance(value, Mapping):
        schema = value.get("schema_version")
        if schema not in (None, "", STAGED_ROLLOUT_SCHEMA_VERSION):
            failures.append(f"snapshot_schema_unsupported:{schema}")
        raw = value.get("snapshots", value.get("stages"))
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return [], failures + ["snapshot_envelope_invalid"]
    items: list[Mapping[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            failures.append(f"incomplete_snapshot:index_{index}:not_an_object")
            continue
        items.append(item)
    return items, failures


def _managed_process_failures(
    snapshot: Mapping[str, Any],
    stage: str,
    cfg: StagedRolloutConfig,
) -> list[str]:
    raw = snapshot.get("managed_processes", snapshot.get("process_lifecycle"))
    if isinstance(raw, Mapping):
        raw = raw.get("processes", raw.get("managed_processes"))
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)) or not raw:
        return [f"managed_process_evidence_missing:{stage}"] if cfg.require_managed_process_evidence else []
    failures: list[str] = []
    for index, process in enumerate(raw):
        if not isinstance(process, Mapping):
            failures.append(f"managed_process_evidence_incomplete:{stage}:index_{index}")
            continue
        name = str(
            process.get("name")
            or process.get("managed_process_id")
            or process.get("role")
            or f"index_{index}"
        )
        state = str(process.get("status") or process.get("state") or "").strip().lower()
        orphaned = process.get("orphaned") is True or state in {
            "orphaned", "running", "alive", "unknown", "leaked"
        }
        if orphaned:
            failures.append(f"orphaned_managed_process:{stage}:{name}")
        if state not in {"completed", "exited", "stopped", "terminated", "cleaned"}:
            failures.append(f"managed_process_not_reaped:{stage}:{name}:{state or 'missing'}")
        code = process.get("exit_code", process.get("returncode"))
        if code is None:
            failures.append(f"managed_process_exit_missing:{stage}:{name}")
        elif _is_nonzero_exit(code):
            failures.append(f"managed_process_failure:{stage}:{name}:exit_{code}")
    return failures


def _family_guardrail_failures(
    snapshot: Mapping[str, Any],
    stage: str,
    cfg: StagedRolloutConfig,
) -> list[str]:
    raw = snapshot.get("family_metrics", snapshot.get("per_family_guardrails"))
    if not isinstance(raw, Mapping):
        return [f"per_family_guardrail_evidence_missing:{stage}"]
    failures: list[str] = []
    for family in cfg.required_families:
        values = raw.get(family)
        if not isinstance(values, Mapping):
            failures.append(f"per_family_guardrail_evidence_missing:{stage}:{family}")
            continue
        for guardrail in cfg.required_guardrails:
            regression_key = f"{guardrail}_regression"
            regression = values.get(regression_key)
            calculated = _paired_guardrail_regression(values, guardrail)
            if regression is True or calculated is True:
                failures.append(f"{guardrail}_regression:{stage}:{family}")
            elif regression is not False and calculated is None:
                failures.append(
                    f"per_family_guardrail_evidence_missing:{stage}:{family}:{guardrail}"
                )
    return failures


def _paired_guardrail_regression(
    values: Mapping[str, Any], guardrail: str
) -> bool | None:
    """Recompute a declared family guardrail when paired values are present."""

    baseline = values.get("baseline")
    candidate = values.get("candidate")
    if not isinstance(baseline, Mapping) or not isinstance(candidate, Mapping):
        return None
    directions: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
        "semantic": (
            (
                "ir_cosine_similarity",
                "compiler_ir_cosine",
                "symbolic_validity_success_rate",
                "structural_validity",
            ),
            ("ir_cross_entropy_loss", "compiler_ir_cross_entropy_loss"),
        ),
        "provenance": (
            (
                "provenance_alignment",
                "provenance_alignment_score",
                "provenance_success_rate",
                "provenance_coverage",
            ),
            ("provenance_failure_count", "provenance_violation_rate"),
        ),
        "anti_copy": (
            ("anti_copy_success_rate",),
            (
                "source_copy_penalty",
                "source_copy_reward_hack_penalty",
                "source_copy_rate",
            ),
        ),
        "hammer_proof": (("hammer_proof_success_rate",), ("hammer_failure_rate",)),
        "lean_reconstruction": (
            ("reconstruction_success_rate", "hammer_reconstruction_success_rate"),
            ("reconstruction_failure_rate",),
        ),
        "process_lifecycle": (
            ("process_cleanup_success_rate",),
            ("process_failure_count", "orphan_process_count", "process_timeout_rate"),
        ),
        "queue_lag": ((), ("queue_lag_p95_seconds", "queue_lag_seconds")),
    }
    higher, lower = directions.get(guardrail, ((), ()))
    compared = False
    for name in higher:
        before = _finite_float(baseline.get(name))
        after = _finite_float(candidate.get(name))
        if before is not None and after is not None:
            compared = True
            if after < before - 1.0e-12:
                return True
    for name in lower:
        before = _finite_float(baseline.get(name))
        after = _finite_float(candidate.get(name))
        if before is not None and after is not None:
            compared = True
            if after > before + 1.0e-12:
                return True
    return False if compared else None


def _trusted_feedback_failures(
    snapshot: Mapping[str, Any],
    stage: str,
    cfg: StagedRolloutConfig,
) -> list[str]:
    if not cfg.require_trusted_feedback:
        return []
    value = snapshot.get("trusted_feedback")
    if not isinstance(value, Mapping):
        return [f"trusted_feedback_evidence_missing:{stage}"]
    trusted = _first_finite(
        value, ("trusted_count", "verified_count", "accepted_count", "produced_count")
    )
    received = _first_finite(
        value,
        (
            "autoencoder_received_count",
            "autoencoder_applied_count",
            "applied_count",
            "weight_update_count",
        ),
    )
    source_digest = str(value.get("source_digest") or value.get("feedback_digest") or "")
    received_digest = str(
        value.get("autoencoder_source_digest")
        or value.get("applied_feedback_digest")
        or ""
    )
    applied_ids = value.get("applied_feedback_ids", value.get("guidance_ids"))
    ids_prove_delivery = (
        isinstance(applied_ids, Sequence)
        and not isinstance(applied_ids, (str, bytes, bytearray))
        and received is not None
        and len(applied_ids) >= int(received)
    )
    digest_proves_delivery = bool(source_digest) and source_digest == received_digest
    weight_writes = value.get("write_to_autoencoder_weights")
    production_writes = value.get("production_weight_writes_enabled")
    ablation = value.get("ablation_evidence")
    ablation_passed = not isinstance(ablation, Mapping) or (
        ablation.get("passed") is True
        or ablation.get("guardrails_passed") is True
        or str(ablation.get("status") or "").lower() in {"passed", "accepted"}
    )
    if (
        trusted is None
        or trusted <= 0.0
        or received is None
        or received < trusted
        or not (digest_proves_delivery or ids_prove_delivery)
        or weight_writes is False
        or production_writes is False
        or not ablation_passed
    ):
        return [f"trusted_feedback_not_applied:{stage}"]
    return []


def _representation_snapshot_failures(
    snapshot: Mapping[str, Any],
    stage: str,
    cfg: StagedRolloutConfig,
) -> list[str]:
    if not cfg.require_representation_promotion_reports:
        return []
    if not _representation_snapshot_is_eligible(snapshot):
        return []
    metrics: dict[str, Any] = {}
    warnings: list[str] = []
    failures = _representation_promotion_failures(
        snapshot,
        RolloutGateConfig(
            require_representation_promotion=True,
            require_successful_representation_promotion=(
                cfg.require_successful_representation_promotion
            ),
            require_complete_representation_evidence=(
                cfg.require_complete_representation_evidence
            ),
        ),
        metrics,
        warnings,
    )
    return [f"{failure}:{stage}" for failure in failures]


def _representation_snapshot_is_eligible(snapshot: Mapping[str, Any]) -> bool:
    if snapshot.get("representation_promotion_eligible") is True:
        return True
    if snapshot.get("eligible_legal_ir_learned_guidance_snapshot") is True:
        return True
    if _representation_promotion_report(snapshot)[1] is not None:
        return True
    for key in (
        "latest_legal_ir_stable_feature_export",
        "legal_ir_stable_feature_export",
        "stable_legal_ir_feature_export",
        "learned_export",
        "source_export_id",
        "learned_export_id",
    ):
        value = snapshot.get(key)
        if isinstance(value, Mapping) and value:
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def _stage_queue_lag(snapshot: Mapping[str, Any]) -> float | None:
    value = snapshot.get("queue_lag")
    if isinstance(value, Mapping):
        result = _first_finite(value, ("p95_seconds", "queue_lag_p95_seconds", "p95"))
        if result is not None:
            return result
    return _first_finite(snapshot, ("queue_lag_p95_seconds", "program_synthesis_queue_lag_p95_seconds"))


def _validated_rollback_evidence(
    snapshot: Mapping[str, Any],
    stage: str,
    cfg: StagedRolloutConfig,
) -> tuple[dict[str, Any] | None, list[str]]:
    value = snapshot.get("rollback_evidence")
    if not isinstance(value, Mapping):
        return None, [f"rollback_evidence_missing:{stage}"] if cfg.require_rollback_evidence else []
    artifact_path = str(value.get("artifact_path") or value.get("snapshot_path") or "").strip()
    digest = str(value.get("sha256") or value.get("artifact_sha256") or "").strip().lower()
    revision = str(value.get("baseline_revision") or value.get("revision") or "").strip()
    restorable = value.get("restorable") is True
    valid_digest = len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)
    if not artifact_path or not valid_digest or not revision or not restorable:
        return None, [f"rollback_evidence_missing:{stage}"]
    if cfg.verify_rollback_artifacts:
        artifact = Path(artifact_path)
        if not artifact.is_file():
            return None, [f"rollback_evidence_invalid:{stage}:artifact_missing"]
        try:
            observed_digest = snapshot_sha256(artifact)
        except OSError as exc:
            return None, [
                f"rollback_evidence_invalid:{stage}:artifact_unreadable:{type(exc).__name__}"
            ]
        if observed_digest != digest:
            return None, [f"rollback_evidence_invalid:{stage}:sha256_mismatch"]
    return {
        "artifact_path": artifact_path,
        "sha256": digest,
        "baseline_revision": revision,
        "restorable": True,
    }, []


def write_rollout_evidence(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Atomically persist a gate decision or rollback manifest."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def snapshot_sha256(path: str | Path) -> str:
    """Return a streaming SHA-256 digest for operator rollback evidence."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    require_success = cfg.require_successful_representation_promotion
    schema = str(report.get("schema_version") or "").strip()
    metrics["representation_promotion_schema_version"] = schema
    if (
        (promoted or require_success or cfg.require_complete_representation_evidence)
        and schema != LEGAL_IR_LEARNED_GUIDANCE_PROMOTION_SCHEMA_VERSION
    ):
        failures.append(
            "representation_promotion_schema_mismatch:"
            f"{schema or 'missing'}"
        )
    report_outcome = str(
        report.get("report_outcome")
        or report.get("promotion_report_outcome")
        or report.get("outcome")
        or ""
    ).strip()
    if report_outcome:
        metrics["representation_promotion_report_outcome"] = report_outcome
    if report_outcome and report_outcome not in {
        "success",
        "rejection",
        "no_candidate",
    }:
        failures.append(f"representation_promotion_report_outcome_invalid:{report_outcome}")
    if promoted and report_outcome and report_outcome != "success":
        failures.append(
            f"representation_promotion_outcome_mismatch:{report_outcome}:promoted"
        )
    if not promoted and report_outcome == "success":
        failures.append("representation_promotion_outcome_mismatch:success:not_promoted")
    if require_success and not promoted:
        suffix = ",".join(block_reasons) if block_reasons else "unspecified"
        failures.append(f"representation_promotion_blocked:{suffix}")
    elif not promoted:
        warnings.append("representation_promotion_not_activated")

    raw_evidence = report.get("canary_evidence")
    evidence = raw_evidence if isinstance(raw_evidence, Mapping) else None
    evidence_required = promoted or require_success or (
        cfg.require_representation_promotion
        and cfg.require_complete_representation_evidence
    )
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
    if cfg.require_complete_representation_evidence or promoted or require_success:
        failures.extend(
            _representation_report_binding_failures(
                summary,
                report,
                evidence,
                promoted=promoted,
                require_complete=cfg.require_complete_representation_evidence
                or promoted
                or require_success,
                metrics=metrics,
            )
        )

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


def _representation_report_binding_failures(
    summary: Mapping[str, Any],
    report: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    promoted: bool,
    require_complete: bool,
    metrics: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    promotion_id = str(report.get("promotion_id") or "").strip()
    source_export_id = str(
        report.get("source_export_id") or report.get("learned_export_id") or ""
    ).strip()
    compiler_commit = str(report.get("compiler_commit") or "").strip()
    canary_id = str(evidence.get("canary_id") or "").strip()
    evidence_id = str(evidence.get("evidence_id") or "").strip()
    metrics["representation_promotion_id"] = promotion_id
    metrics["representation_source_export_id"] = source_export_id
    metrics["representation_compiler_commit"] = compiler_commit

    if require_complete and not promotion_id:
        failures.append("representation_promotion_id_missing")

    learned_export = report.get("learned_export")
    if not isinstance(learned_export, Mapping):
        failures.append("representation_learned_export_binding_missing")
        learned_export = {}
    else:
        export_id = str(learned_export.get("export_id") or "").strip()
        export_schema = str(learned_export.get("schema_version") or "").strip()
        export_sha = str(
            learned_export.get("sha256")
            or learned_export.get("export_sha256")
            or report.get("learned_export_sha256")
            or ""
        ).strip().lower()
        metrics["representation_learned_export_sha256"] = export_sha
        if require_complete and not export_id:
            failures.append("representation_learned_export_id_missing")
        if source_export_id and export_id and source_export_id != export_id:
            failures.append(
                "representation_learned_export_id_mismatch:"
                f"{source_export_id}!={export_id}"
            )
        if require_complete and export_schema != LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION:
            failures.append(
                "representation_learned_export_schema_mismatch:"
                f"{export_schema or 'missing'}"
            )
        if require_complete and not _valid_sha256(export_sha):
            failures.append("representation_learned_export_sha256_missing")
        if learned_export.get("sample_memory_included") is True:
            failures.append("representation_learned_export_contains_sample_memory")

    expected_export_id = _first_summary_string(
        summary,
        (
            "source_export_id",
            "learned_export_id",
            "latest_legal_ir_stable_feature_export.export_id",
            "legal_ir_stable_feature_export.export_id",
            "stable_legal_ir_feature_export.export_id",
            "learned_export.export_id",
        ),
    )
    if expected_export_id and source_export_id and expected_export_id != source_export_id:
        failures.append(
            "representation_promotion_report_stale:source_export_id:"
            f"{source_export_id}!={expected_export_id}"
        )

    if require_complete and not compiler_commit:
        failures.append("representation_compiler_commit_missing")
    expected_compiler_commit = _first_summary_string(
        summary,
        (
            "compiler_commit",
            "expected_compiler_commit",
            "selected_compiler_commit",
            "snapshot_selection.selected_compiler_commit",
            "snapshot_selection.compiler_commit",
            "context.compiler_commit",
            "latest_compiler_snapshot.compiler_commit",
        ),
    )
    if (
        expected_compiler_commit
        and compiler_commit
        and expected_compiler_commit != compiler_commit
    ):
        failures.append(
            "representation_promotion_report_stale:compiler_commit:"
            f"{compiler_commit}!={expected_compiler_commit}"
        )

    fixed_binding = report.get("fixed_canary_binding")
    if not isinstance(fixed_binding, Mapping):
        failures.append("representation_fixed_canary_binding_missing")
    else:
        bound_canary = str(fixed_binding.get("canary_id") or "").strip()
        bound_evidence = str(fixed_binding.get("evidence_id") or "").strip()
        if canary_id and bound_canary and bound_canary != canary_id:
            failures.append(
                "representation_fixed_canary_binding_mismatch:"
                f"{bound_canary}!={canary_id}"
            )
        if evidence_id and bound_evidence and bound_evidence != evidence_id:
            failures.append(
                "representation_fixed_canary_evidence_mismatch:"
                f"{bound_evidence}!={evidence_id}"
            )
        if require_complete and not bound_canary:
            failures.append("representation_fixed_canary_binding_id_missing")
    expected_canary_id = _first_summary_string(
        summary,
        (
            "fixed_canary_id",
            "validation_canary_id",
            "frozen_canary.canary_id",
            "latest_legal_ir_view_family_validation.canary_id",
            "latest_legal_ir_stable_feature_export.fixed_canary_id",
        ),
    )
    if expected_canary_id and canary_id and expected_canary_id != canary_id:
        failures.append(
            "representation_promotion_report_stale:fixed_canary:"
            f"{canary_id}!={expected_canary_id}"
        )

    proof_receipts = report.get("proof_receipts")
    if not isinstance(proof_receipts, Sequence) or isinstance(
        proof_receipts, (str, bytes, bytearray)
    ):
        failures.append("representation_proof_receipts_missing")
        proof_receipts = ()
    else:
        metrics["representation_proof_receipt_count"] = len(proof_receipts)
        if promoted and not proof_receipts:
            failures.append("representation_proof_receipts_missing")
        for index, receipt in enumerate(proof_receipts):
            if not isinstance(receipt, Mapping):
                failures.append(f"representation_proof_receipt_invalid:index_{index}")
                continue
            receipt_id = str(receipt.get("receipt_id") or receipt.get("id") or "").strip()
            if require_complete and not receipt_id:
                failures.append(
                    f"representation_proof_receipt_id_missing:index_{index}"
                )
            if promoted and receipt.get("trusted") is False:
                failures.append(f"representation_proof_receipt_untrusted:{receipt_id or index}")

    causal = report.get("causal_evidence")
    if not isinstance(causal, Mapping) or not causal:
        failures.append("representation_causal_evidence_missing")
    else:
        if require_complete and causal.get("fixed_canary_evidence_id") not in {
            None,
            "",
            evidence_id,
        }:
            failures.append("representation_causal_evidence_canary_mismatch")
        if require_complete and causal.get("metric_lineage_complete") is not True:
            failures.append("representation_causal_metric_lineage_incomplete")
        if promoted and causal.get("learned_path_responsive") is not True:
            failures.append("representation_causal_learned_path_unproven")

    source_copy = report.get("source_copy_checks")
    if not isinstance(source_copy, Mapping) or not source_copy:
        failures.append("representation_source_copy_checks_missing")
    else:
        if promoted and source_copy.get("guardrails_passed") is not True:
            failures.append("representation_source_copy_checks_failed")
        if source_copy.get("sample_memory_included") is True:
            failures.append("representation_source_copy_sample_memory_present")
        unsafe_count = _first_finite(
            source_copy,
            ("unsafe_feature_count", "forbidden_feature_marker_count"),
        )
        if unsafe_count is not None and unsafe_count > 0.0:
            failures.append(
                f"representation_source_copy_unsafe_features:{unsafe_count:g}"
            )
        regressions = _string_sequence(source_copy.get("source_copy_regressions"))
        if promoted and regressions:
            failures.append(
                "representation_source_copy_declared_regression:"
                + ",".join(regressions)
            )

    activation = report.get("activation_state")
    if not isinstance(activation, Mapping) or not activation:
        failures.append("representation_activation_state_missing")
    else:
        allowed = activation.get("activation_allowed")
        if allowed is not None and bool(allowed) != promoted:
            failures.append("representation_activation_state_mismatch")
        active_id = str(activation.get("active_promotion_id") or "").strip()
        if promoted and promotion_id and active_id and active_id != promotion_id:
            failures.append(
                "representation_activation_promotion_id_mismatch:"
                f"{active_id}!={promotion_id}"
            )
        if promoted and not active_id:
            failures.append("representation_activation_promotion_id_missing")

    rollback = report.get("rollback_metadata")
    if not isinstance(rollback, Mapping) or not rollback:
        failures.append("representation_rollback_metadata_missing")
    else:
        if require_complete and not str(rollback.get("rollback_id") or "").strip():
            failures.append("representation_rollback_id_missing")
        activation_key = str(rollback.get("activation_key") or "").strip()
        if promotion_id and activation_key and activation_key != promotion_id:
            failures.append(
                "representation_rollback_activation_key_mismatch:"
                f"{activation_key}!={promotion_id}"
            )
        rollback_export = str(rollback.get("source_export_id") or "").strip()
        if source_export_id and rollback_export and rollback_export != source_export_id:
            failures.append(
                "representation_rollback_source_export_mismatch:"
                f"{rollback_export}!={source_export_id}"
            )
        rollback_canary = str(rollback.get("canary_evidence_id") or "").strip()
        if evidence_id and rollback_canary and rollback_canary != evidence_id:
            failures.append(
                "representation_rollback_canary_evidence_mismatch:"
                f"{rollback_canary}!={evidence_id}"
            )

    report_path = str(report.get("report_artifact_path") or "").strip()
    expected_report_path = _first_summary_string(
        summary,
        (
            "representation_promotion_report_path",
            "latest_legal_ir_learned_guidance_promotion_path",
            "promotion_report_path",
            "promotion_artifact_path",
        ),
    )
    if expected_report_path and report_path and expected_report_path != report_path:
        failures.append(
            "representation_promotion_report_path_mismatch:"
            f"{report_path}!={expected_report_path}"
        )
    if expected_report_path and require_complete and not report_path:
        failures.append("representation_promotion_report_path_missing")

    snapshot_id = str(report.get("eligible_snapshot_id") or "").strip()
    expected_snapshot_id = _first_summary_string(
        summary,
        (
            "eligible_snapshot_id",
            "snapshot_id",
            "latest_published_snapshot.snapshot_id",
            "latest_promoted_snapshot_evaluation.snapshot_id",
        ),
    )
    if expected_snapshot_id and snapshot_id and expected_snapshot_id != snapshot_id:
        failures.append(
            "representation_promotion_report_stale:snapshot_id:"
            f"{snapshot_id}!={expected_snapshot_id}"
        )
    if expected_snapshot_id and require_complete and not snapshot_id:
        failures.append("representation_eligible_snapshot_id_missing")
    return failures


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


def _first_summary_string(
    payload: Mapping[str, Any], paths: Sequence[str]
) -> str:
    for path in paths:
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(part)
        if current is None:
            continue
        text = str(current).strip()
        if text:
            return text
    return ""


def _valid_sha256(value: str) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


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

    staged_parser = subparsers.add_parser(
        "staged-gate",
        help="Gate a persisted smoke/hparam/canary/production snapshot manifest",
    )
    staged_input = staged_parser.add_mutually_exclusive_group(required=True)
    staged_input.add_argument("--snapshot-path", type=Path)
    staged_input.add_argument("--manifest-path", type=Path)
    staged_parser.add_argument(
        "--evidence-output",
        type=Path,
        help="Atomically store the complete promotion decision",
    )
    staged_parser.add_argument(
        "--allow-prefix",
        action="store_true",
        help="Accept a valid ordered prefix so the launcher can authorize the next stage",
    )
    staged_parser.add_argument("--duration-tolerance-seconds", type=float, default=0.0)
    staged_parser.add_argument("--max-queue-lag-p95-seconds", type=float, default=120.0)
    staged_parser.add_argument("--max-queue-lag-regression", type=float, default=0.0)
    staged_parser.add_argument(
        "--max-accepted-patches-per-hour-regression", type=float, default=0.0
    )
    staged_parser.add_argument(
        "--verify-rollback-artifacts",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require rollback paths to exist and match their recorded SHA-256",
    )
    staged_parser.set_defaults(func=_cmd_staged_gate)
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


def _cmd_staged_gate(args: argparse.Namespace) -> int:
    snapshot_path: Path = args.snapshot_path or args.manifest_path
    try:
        with snapshot_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, (Mapping, list)):
            raise ValueError("snapshot manifest must be an object or array")
        result = staged_rollout_gate(
            payload,
            StagedRolloutConfig(
                require_all_stages=not args.allow_prefix,
                verify_rollback_artifacts=args.verify_rollback_artifacts,
                duration_tolerance_seconds=args.duration_tolerance_seconds,
                max_queue_lag_p95_seconds=args.max_queue_lag_p95_seconds,
                max_queue_lag_regression=args.max_queue_lag_regression,
                max_accepted_patches_per_hour_regression=(
                    args.max_accepted_patches_per_hour_regression
                ),
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = RolloutGateResult(
            accepted=False,
            failures=[f"incomplete_snapshot_manifest:{type(exc).__name__}:{exc}"],
            metrics={"schema_version": STAGED_ROLLOUT_SCHEMA_VERSION},
        )
    decision = result.to_dict()
    decision["schema_version"] = STAGED_ROLLOUT_SCHEMA_VERSION
    decision["snapshot_path"] = str(snapshot_path)
    if snapshot_path.is_file():
        decision["snapshot_sha256"] = snapshot_sha256(snapshot_path)
    if args.evidence_output is not None:
        write_rollout_evidence(args.evidence_output, decision)
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if result.accepted else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
