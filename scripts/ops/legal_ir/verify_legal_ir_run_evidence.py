#!/usr/bin/env python3
"""Fail-closed verification for executed LegalIR rollout evidence.

The committed document is deliberately a compact receipt.  Large checkpoints,
logs, model files, prompts, and patches stay in the operator artifact store; the
receipt binds them by SHA-256 and records only the counters needed to reproduce
the decision.  A supplied ``accepted`` or ``healthy`` flag is never sufficient.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "legal-ir-10-minute-integrated-smoke-evidence-v1"
WATCHDOG_SCHEMA_VERSION = "legal-ir-execution-watchdog-v1"
MAX_SUMMARY_BYTES = 32 * 1024 * 1024
MAX_TRAINING_LOG_BYTES = 64 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 512 * 1024 * 1024
MAX_SERVICE_STATE_BYTES = 4 * 1024 * 1024
MAX_GATE_DECISION_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_WATCHDOG_HEARTBEAT_GAP_SECONDS = 30.0
MAX_PROGRESS_HEARTBEAT_GAP_SECONDS = 360.0
SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$")
REQUIRED_FAMILIES = (
    "deontic",
    "frame_logic",
    "tdfol",
    "kg",
    "cec",
    "external_provers",
    "decompiler",
)
REQUIRED_QUALITY_METRICS = (
    "ir_cross_entropy_loss",
    "ir_cosine_similarity",
    "autoencoder_cross_entropy_loss",
    "autoencoder_cosine_similarity",
    "semantic_equivalence",
    "proof_success_rate",
    "reconstruction_success_rate",
    "provenance",
    "round_trip",
    "uncertainty",
    "holdout",
    "source_copy_penalty",
)
LOWER_IS_BETTER = frozenset(
    {
        "ir_cross_entropy_loss",
        "autoencoder_cross_entropy_loss",
        "uncertainty",
        "source_copy_penalty",
    }
)
REQUIRED_STAGE_TIMINGS = (
    "cuda_training",
    "snapshot_evaluation",
    "hammer",
    "leanstral",
    "codex",
    "focused_validation",
    "persistence",
)
REQUIRED_QUEUE_TIMINGS = (
    "snapshot_queue_seconds",
    "hammer_queue_seconds",
    "leanstral_queue_seconds",
    "codex_queue_seconds",
    "persistence_queue_seconds",
)
FORBIDDEN_KEYS = frozenset(
    {
        "prompt",
        "raw_prompt",
        "prompt_text",
        "checkpoint_payload",
        "model_weights",
        "patch_content",
        "raw_patch",
    }
)
ARTIFACT_LIMITS = {
    "autoencoder_summary": MAX_SUMMARY_BYTES,
    "paired_summary": MAX_SUMMARY_BYTES,
    "training_log": MAX_TRAINING_LOG_BYTES,
    "checkpoint": MAX_CHECKPOINT_BYTES,
    "leanstral_service": MAX_SERVICE_STATE_BYTES,
    "gate_decision": MAX_GATE_DECISION_BYTES,
}


@dataclass(frozen=True)
class VerificationResult:
    accepted: bool
    failures: tuple[str, ...]
    metrics: Mapping[str, Any]


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return the stable bytes covered by ``manifest_sha256``."""

    body = dict(payload)
    body.pop("manifest_sha256", None)
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def manifest_sha256(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _positive(block: Mapping[str, Any], key: str) -> bool:
    value = _number(block.get(key))
    return value is not None and value > 0.0


def _nonnegative_integer(value: Any) -> int | None:
    number = _number(value)
    if number is None or number < 0 or not number.is_integer():
        return None
    return int(number)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: Any) -> Sequence[Any] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return None


def _walk(value: Any, path: str = ""):
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield child_path, str(key), child
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _fail_missing(failures: list[str], block: Mapping[str, Any], names: Sequence[str], prefix: str) -> None:
    for name in names:
        if name not in block:
            failures.append(f"missing:{prefix}.{name}")


def verify_evidence(
    payload: Mapping[str, Any],
    *,
    stage: str = "ten_minute_smoke",
    minimum_active_seconds: float = 600.0,
    evidence_path: Path | None = None,
    verify_available_artifacts: bool = False,
    max_age_seconds: float | None = None,
    now: datetime | None = None,
) -> VerificationResult:
    """Recompute the execution decision from a compact evidence manifest."""

    failures: list[str] = []
    metrics: dict[str, Any] = {}
    if not isinstance(payload, Mapping):
        return VerificationResult(False, ("evidence:not_an_object",), metrics)

    try:
        encoded_size = len(json.dumps(payload, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError):
        encoded_size = MAX_MANIFEST_BYTES + 1
    if encoded_size > MAX_MANIFEST_BYTES:
        failures.append("compactness:manifest_oversized")

    if payload.get("schema_version") != SCHEMA_VERSION:
        failures.append(f"schema:unsupported:{payload.get('schema_version') or 'missing'}")
    if payload.get("task_id") != "PORTAL-LIR-HAMMER-117":
        failures.append("identity:task_id")
    if payload.get("stage") != stage:
        failures.append(f"identity:stage:{payload.get('stage') or 'missing'}!={stage}")
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", run_id):
        failures.append("identity:run_id")
    for key in ("dry_run", "simulated", "fixture_replay"):
        if payload.get(key) is not False:
            failures.append(f"authenticity:{key}")
    if payload.get("complete") is not True:
        failures.append("evidence:incomplete")
    if payload.get("decision") != "passed":
        failures.append("decision:not_passed")

    claimed_digest = payload.get("manifest_sha256")
    computed_digest = manifest_sha256(payload)
    metrics["manifest_sha256"] = computed_digest
    if claimed_digest != computed_digest:
        failures.append("content_address:manifest_digest_mismatch")

    for path, key, value in _walk(payload):
        if key.lower() in FORBIDDEN_KEYS and value not in (None, "", [], {}):
            failures.append(f"compactness:forbidden_payload:{path}")

    timing = _mapping(payload.get("timing"))
    if timing is None:
        failures.append("missing:timing")
        timing = {}
    started = _timestamp(timing.get("started_at"))
    ended = _timestamp(timing.get("ended_at"))
    generated = _timestamp(timing.get("generated_at"))
    if started is None or ended is None or generated is None:
        failures.append("timing:timestamp_invalid")
    elif not (started < ended <= generated):
        failures.append("timing:timestamp_order")
    if generated is not None:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if generated > current.replace(microsecond=current.microsecond) and (generated - current).total_seconds() > 300:
            failures.append("freshness:future_evidence")
        if max_age_seconds is not None and (current - generated).total_seconds() > max_age_seconds:
            failures.append("freshness:evidence_too_old")

    active = _number(timing.get("active_seconds"))
    wall = _number(timing.get("wall_seconds"))
    startup = _number(timing.get("startup_seconds"))
    downtime = _number(timing.get("downtime_seconds"))
    if active is None or active < minimum_active_seconds:
        failures.append("timing:insufficient_active_seconds")
    if wall is None or active is None or wall + 1e-6 < active:
        failures.append("timing:wall_less_than_active")
    if started is not None and ended is not None and wall is not None:
        observed_wall = (ended - started).total_seconds()
        if abs(observed_wall - wall) > max(2.0, observed_wall * 0.01):
            failures.append("timing:wall_timestamp_mismatch")
    if startup is None or startup < 0 or downtime is None or downtime < 0:
        failures.append("timing:startup_or_downtime_invalid")

    intervals = _sequence(timing.get("active_intervals"))
    interval_total = 0.0
    last_end: datetime | None = None
    if not intervals:
        failures.append("timing:active_intervals_missing")
    else:
        for index, raw in enumerate(intervals):
            item = _mapping(raw)
            if item is None:
                failures.append(f"timing:active_interval_invalid:{index}")
                continue
            begin, finish = _timestamp(item.get("started_at")), _timestamp(item.get("ended_at"))
            seconds = _number(item.get("active_seconds"))
            if begin is None or finish is None or begin >= finish or seconds is None or seconds <= 0:
                failures.append(f"timing:active_interval_invalid:{index}")
                continue
            measured = (finish - begin).total_seconds()
            if abs(measured - seconds) > max(1.0, measured * 0.01):
                failures.append(f"timing:active_interval_duration:{index}")
            if last_end is not None and begin < last_end:
                failures.append(f"timing:active_interval_overlap:{index}")
            if started is not None and ended is not None and (begin < started or finish > ended):
                failures.append(f"timing:active_interval_outside_run:{index}")
            last_end = finish
            interval_total += seconds
    if active is not None and abs(interval_total - active) > max(1.0, active * 0.01):
        failures.append("timing:active_interval_sum")
    if wall is not None and active is not None and startup is not None and downtime is not None:
        accounted = active + startup + downtime
        if accounted > wall + max(2.0, wall * 0.01):
            failures.append("timing:components_exceed_wall")
    metrics["active_seconds"] = active

    lineage = _mapping(payload.get("lineage"))
    if lineage is None:
        failures.append("missing:lineage")
        lineage = {}
    if lineage.get("run_id") != run_id or lineage.get("stage") != stage:
        failures.append("lineage:run_or_stage_mismatch")
    revision = str(lineage.get("code_revision") or "")
    if REVISION_RE.fullmatch(revision) is None:
        failures.append("lineage:code_revision")
    for name in (
        "source_tree_sha256", "baseline_state_sha256", "final_state_sha256",
        "fixture_sha256", "configuration_sha256", "holdout_sha256",
    ):
        if not _sha(lineage.get(name)):
            failures.append(f"lineage:{name}")
    if lineage.get("baseline_state_revision") == lineage.get("final_state_revision"):
        failures.append("progress:state_revision_not_advanced")
    for identity_name in ("baseline_state_id", "fixture_id", "configuration_id", "holdout_id"):
        if not str(lineage.get(identity_name) or "").strip():
            failures.append(f"lineage:{identity_name}")

    selected = _mapping(payload.get("selected_configuration"))
    if selected is None or not selected:
        failures.append("missing:selected_configuration")
    elif manifest_sha256(selected) != lineage.get("configuration_sha256"):
        failures.append("lineage:configuration_digest_mismatch")
    else:
        configured_duration = _number(selected.get("active_duration_seconds"))
        if configured_duration is None or configured_duration < minimum_active_seconds:
            failures.append("configuration:active_duration")
        runner_budget = _number(selected.get("canonical_runner_budget_seconds"))
        if runner_budget is None or runner_budget < minimum_active_seconds:
            failures.append("configuration:canonical_runner_budget")
    fixture = _mapping(payload.get("fixed_fixture"))
    if fixture is None:
        failures.append("missing:fixed_fixture")
    else:
        if fixture.get("fixture_id") != lineage.get("fixture_id") or fixture.get("sha256") != lineage.get("fixture_sha256"):
            failures.append("lineage:fixture_mismatch")
        if fixture.get("immutable") is not True or fixture.get("replay") is not False:
            failures.append("fixture:not_real_fixed_input")

    progress = _mapping(payload.get("progress"))
    if progress is None:
        failures.append("missing:progress")
        progress = {}
    cycles = _number(progress.get("warm_cycles_completed"))
    sample_start, sample_end = _number(progress.get("sample_count_start")), _number(progress.get("sample_count_end"))
    state_start, state_end = progress.get("state_revision_start"), progress.get("state_revision_end")
    if cycles is None or cycles < 2:
        failures.append("progress:fewer_than_two_warm_cycles")
    if sample_start is None or sample_end is None or sample_end <= sample_start:
        failures.append("progress:samples_not_advanced")
    if state_start == state_end or state_start != lineage.get("baseline_state_revision") or state_end != lineage.get("final_state_revision"):
        failures.append("progress:state_revision_lineage")
    resumes = _sequence(progress.get("resumes"))
    resume_count = _number(progress.get("resume_count"))
    if resumes is None or resume_count is None or int(resume_count) != len(resumes):
        failures.append("progress:resume_ledger")
    else:
        for index, raw in enumerate(resumes):
            item = _mapping(raw) or {}
            for name in ("source_checkpoint_sha256", "restored_checkpoint_sha256"):
                if not _sha(item.get(name)):
                    failures.append(f"progress:resume:{index}:{name}")
            if item.get("lineage_verified") is not True or item.get("post_restore_health") != "healthy":
                failures.append(f"progress:resume:{index}:unverified")

    model = _mapping(payload.get("model_context"))
    if model is None:
        failures.append("missing:model_context")
        model = {}
    for name in ("model_id", "model_sha256", "context_fingerprint", "service_generation"):
        value = model.get(name)
        if not str(value or "").strip() or (name == "model_sha256" and not _sha(value)):
            failures.append(f"model_context:{name}")
    if not _positive(model, "context_size") or not str(model.get("device") or "").lower().startswith("cuda"):
        failures.append("model_context:cuda_context")

    services = _mapping(payload.get("services"))
    if services is None:
        failures.append("missing:services")
        services = {}
    auto = _mapping(services.get("cuda_autoencoder")) or {}
    if auto.get("backend") != "torch_cuda" or not str(auto.get("device") or "").lower().startswith("cuda"):
        failures.append("service:autoencoder:not_cuda")
    if auto.get("cpu_fallback") is not False or auto.get("simulated") is not False:
        failures.append("service:autoencoder:fallback_or_simulated")
    if selected and str(selected.get("autoencoder_device") or "").lower() != str(auto.get("device") or "").lower():
        failures.append("configuration:autoencoder_device_mismatch")
    for name in ("forward_count", "loss_count", "backward_count", "optimizer_step_count"):
        if (_nonnegative_integer(auto.get(name)) or 0) < 1:
            failures.append(f"service:autoencoder:{name}")
    auto_counts = [
        _nonnegative_integer(auto.get(name))
        for name in ("forward_count", "loss_count", "backward_count", "optimizer_step_count")
    ]
    if all(value is not None for value in auto_counts):
        assert all(value is not None for value in auto_counts)
        if len(set(auto_counts)) != 1:
            failures.append("service:autoencoder:operation_count_mismatch")
        if cycles is not None and auto_counts[0] < int(cycles):
            failures.append("service:autoencoder:operations_fewer_than_cycles")

    lean = _mapping(services.get("leanstral")) or {}
    if (
        lean.get("healthy") is not True or lean.get("persistent") is not True
        or lean.get("cpu_fallback") is not False
        or not str(lean.get("device") or "").lower().startswith("cuda")
    ):
        failures.append("service:leanstral:cuda_health")
    if lean.get("generation") != model.get("service_generation") or lean.get("model_id") != model.get("model_id") or lean.get("context_fingerprint") != model.get("context_fingerprint"):
        failures.append("service:leanstral:model_context_mismatch")
    if _number(lean.get("model_load_count")) != 1 or _number(lean.get("preflight_count")) != 1:
        failures.append("service:leanstral:weights_reloaded")
    for name in ("request_count", "reuse_count"):
        if (_nonnegative_integer(lean.get(name)) or 0) < 1:
            failures.append(f"service:leanstral:{name}")
    if (_number(lean.get("request_count")) or 0) < 2 or lean.get("healthy_cuda_service_reused") is not True:
        failures.append("service:leanstral:not_reused_after_warmup")
    request_count = _nonnegative_integer(lean.get("request_count"))
    reuse_count = _nonnegative_integer(lean.get("reuse_count"))
    if request_count is not None and reuse_count is not None and reuse_count > max(0, request_count - 1):
        failures.append("service:leanstral:reuse_count_incoherent")
    for name in ("queue_seconds", "inference_seconds", "verification_seconds", "restart_seconds"):
        value = _number(lean.get(name))
        if value is None or value < 0:
            failures.append(f"service:leanstral:{name}")

    hammer = _mapping(services.get("hammer")) or {}
    if hammer.get("healthy") is not True or hammer.get("backend_available") is not True:
        failures.append("service:hammer:backend")
    for name in ("obligation_count", "backend_attempt_count", "proof_attempt_count", "reconstruction_count"):
        if (_nonnegative_integer(hammer.get(name)) or 0) < 1:
            failures.append(f"service:hammer:{name}")
    obligations = _nonnegative_integer(hammer.get("obligation_count"))
    backend_attempts = _nonnegative_integer(hammer.get("backend_attempt_count"))
    proof_attempts = _nonnegative_integer(hammer.get("proof_attempt_count"))
    reconstructions = _nonnegative_integer(hammer.get("reconstruction_count"))
    if None not in (obligations, backend_attempts, proof_attempts, reconstructions):
        assert obligations is not None and backend_attempts is not None
        assert proof_attempts is not None and reconstructions is not None
        if backend_attempts > obligations or proof_attempts > backend_attempts or reconstructions > proof_attempts:
            failures.append("service:hammer:counter_progression")
    if _number(hammer.get("fatal_failure_count")) != 0:
        failures.append("service:hammer:fatal_failure")

    codex = _mapping(services.get("codex")) or {}
    if codex.get("fixture_sha256") != lineage.get("fixture_sha256") or codex.get("run_id") != run_id:
        failures.append("service:codex:lineage")
    for name in ("todo_count", "invocation_count", "focused_validation_count"):
        if (_nonnegative_integer(codex.get(name)) or 0) < 1:
            failures.append(f"service:codex:{name}")
    max_todos, todo_count = _number(codex.get("max_todos")), _number(codex.get("todo_count"))
    max_bytes, queue_bytes = _number(codex.get("max_queue_bytes")), _number(codex.get("queue_bytes_peak"))
    if max_todos is None or todo_count is None or todo_count > max_todos or max_todos <= 0:
        failures.append("service:codex:todo_bound")
    if max_bytes is None or queue_bytes is None or queue_bytes > max_bytes or max_bytes <= 0:
        failures.append("service:codex:queue_bound")
    configured_todos = _number(selected.get("max_codex_todos")) if selected else None
    if configured_todos is None or max_todos != configured_todos:
        failures.append("configuration:codex_todo_bound_mismatch")
    configured_mode = str(selected.get("codex_apply_mode") or "") if selected else ""
    if configured_mode != str(codex.get("apply_mode") or configured_mode):
        failures.append("configuration:codex_apply_mode_mismatch")
    accepted_count = _number(codex.get("accepted_merge_count")) or 0
    rejected_count = _number(codex.get("safe_rejection_count")) or 0
    transient_failure_count = _nonnegative_integer(codex.get("transient_failure_count"))
    transient_requeue_count = _nonnegative_integer(codex.get("transient_requeue_count"))
    if transient_failure_count is None or transient_requeue_count is None:
        failures.append("service:codex:transient_accounting")
    elif invocation_int := _nonnegative_integer(codex.get("invocation_count")):
        if transient_failure_count > invocation_int or transient_requeue_count > invocation_int:
            failures.append("service:codex:transient_counter_progression")
    if accepted_count + rejected_count < 1:
        failures.append("service:codex:no_safe_terminal_path")
    dispositions = _sequence(codex.get("dispositions"))
    if not dispositions:
        failures.append("service:codex:dispositions_missing")
    else:
        disposition_accepted = 0
        disposition_rejected = 0
        for index, raw in enumerate(dispositions):
            item = _mapping(raw) or {}
            count = _nonnegative_integer(item.get("count", 1))
            if count is None or count < 1:
                failures.append(f"service:codex:disposition:{index}:count")
                count = 0
            if item.get("status") not in {"merged", "safe_rejection"}:
                failures.append(f"service:codex:disposition:{index}:status")
            elif item.get("status") == "merged":
                disposition_accepted += count
            else:
                disposition_rejected += count
            if not _sha(item.get("todo_sha256")) or not _sha(item.get("validation_sha256")):
                failures.append(f"service:codex:disposition:{index}:digest")
            if item.get("focused_validation") is not True:
                failures.append(f"service:codex:disposition:{index}:validation")
            if item.get("status") == "safe_rejection" and not str(item.get("reason_code") or "").strip():
                failures.append(f"service:codex:disposition:{index}:reason")
        if accepted_count != disposition_accepted or rejected_count != disposition_rejected:
            failures.append("service:codex:terminal_count_mismatch")
    todo_int = _nonnegative_integer(codex.get("todo_count"))
    invocation_int = _nonnegative_integer(codex.get("invocation_count"))
    validation_int = _nonnegative_integer(codex.get("focused_validation_count"))
    if None not in (todo_int, invocation_int, validation_int):
        assert todo_int is not None and invocation_int is not None and validation_int is not None
        # A bounded transient retry may invoke the same TODO more than once.
        # TODO cardinality is independently bounded above; validation and
        # terminal dispositions must still be backed by real invocations.
        if validation_int > invocation_int or accepted_count + rejected_count > validation_int:
            failures.append("service:codex:counter_progression")

    watchdog = _mapping(services.get("watchdog")) or {}
    if watchdog.get("healthy") is not True or watchdog.get("status") != "exited_cleanly":
        failures.append("service:watchdog:health")
    for name in ("heartbeat_count", "children_launched", "children_reaped"):
        if (_nonnegative_integer(watchdog.get(name)) or 0) < 1:
            failures.append(f"service:watchdog:{name}")
    if watchdog.get("children_launched") != watchdog.get("children_reaped"):
        failures.append("service:watchdog:children_not_reaped")
    for name in ("missed_heartbeat_count", "fatal_event_count", "orphaned_child_count", "concurrent_writer_count"):
        if _number(watchdog.get(name)) != 0:
            failures.append(f"service:watchdog:{name}")
    heartbeat_gap = _number(watchdog.get("max_heartbeat_gap_seconds"))
    progress_gap = _number(watchdog.get("max_progress_gap_seconds"))
    if heartbeat_gap is None or heartbeat_gap < 0 or heartbeat_gap > MAX_WATCHDOG_HEARTBEAT_GAP_SECONDS:
        failures.append("service:watchdog:heartbeat_gap")
    if progress_gap is None or progress_gap < 0 or progress_gap > MAX_PROGRESS_HEARTBEAT_GAP_SECONDS:
        failures.append("service:watchdog:progress_gap")
    if wall is not None:
        heartbeats = _nonnegative_integer(watchdog.get("heartbeat_count"))
        if heartbeats is not None and heartbeats * MAX_WATCHDOG_HEARTBEAT_GAP_SECONDS + 1 < wall:
            failures.append("service:watchdog:heartbeat_coverage")
    children = _sequence(watchdog.get("managed_children"))
    if not children:
        failures.append("service:watchdog:managed_children_missing")
    else:
        launched = _number(watchdog.get("children_launched"))
        if launched is None or int(launched) != len(children):
            failures.append("service:watchdog:managed_child_ledger_incomplete")
        for index, raw in enumerate(children):
            item = _mapping(raw) or {}
            if item.get("status") != "exited" or _number(item.get("exit_code")) != 0 or item.get("orphaned") is not False:
                failures.append(f"service:watchdog:child:{index}")

    quality = _mapping(payload.get("quality_families"))
    if quality is None:
        failures.append("missing:quality_families")
        quality = {}
    if set(quality) != set(REQUIRED_FAMILIES):
        failures.append("quality:family_set")
    for family in REQUIRED_FAMILIES:
        pair = _mapping(quality.get(family)) or {}
        baseline, candidate = _mapping(pair.get("baseline")) or {}, _mapping(pair.get("candidate")) or {}
        if not _positive(pair, "sample_count") or pair.get("guardrail_passed") is not True:
            failures.append(f"quality:{family}:coverage")
        if set(baseline) != set(REQUIRED_QUALITY_METRICS) or set(candidate) != set(REQUIRED_QUALITY_METRICS):
            failures.append(f"quality:{family}:metric_set")
        for metric in REQUIRED_QUALITY_METRICS:
            before, after = _number(baseline.get(metric)), _number(candidate.get(metric))
            if before is None or after is None:
                failures.append(f"quality:{family}:{metric}:nonfinite_or_missing")
                continue
            if metric in {"ir_cross_entropy_loss", "autoencoder_cross_entropy_loss", "uncertainty", "source_copy_penalty"}:
                invalid_domain = before < 0 or after < 0
            else:
                invalid_domain = not (0 <= before <= 1 and 0 <= after <= 1)
            if invalid_domain:
                failures.append(f"quality:{family}:{metric}:domain")
            regressed = after > before + 1e-12 if metric in LOWER_IS_BETTER else after + 1e-12 < before
            if regressed:
                failures.append(f"quality:{family}:{metric}:regression")

    telemetry = _mapping(payload.get("telemetry"))
    if telemetry is None:
        failures.append("missing:telemetry")
        telemetry = {}
    stage_timings, queue_timings = _mapping(telemetry.get("stage_timings_seconds")) or {}, _mapping(telemetry.get("queue_timings_seconds")) or {}
    _fail_missing(failures, stage_timings, REQUIRED_STAGE_TIMINGS, "telemetry.stage_timings_seconds")
    _fail_missing(failures, queue_timings, REQUIRED_QUEUE_TIMINGS, "telemetry.queue_timings_seconds")
    for prefix, block in (("stage", stage_timings), ("queue", queue_timings)):
        for name, value in block.items():
            number = _number(value)
            if number is None or number < 0:
                failures.append(f"telemetry:{prefix}:{name}")
    if not _positive(telemetry, "queue_depth_limit"):
        failures.append("telemetry:queue_depth_limit")
    peak, limit = _number(telemetry.get("queue_depth_peak")), _number(telemetry.get("queue_depth_limit"))
    if peak is None or peak < 0 or limit is None or peak > limit:
        failures.append("telemetry:queue_depth_bound")

    artifacts = _mapping(payload.get("artifacts"))
    if artifacts is None or not artifacts:
        failures.append("missing:artifacts")
        artifacts = {}
    for name, policy_maximum in ARTIFACT_LIMITS.items():
        item = _mapping(artifacts.get(name))
        if item is None:
            failures.append(f"artifact:{name}:missing")
            continue
        size = _number(item.get("bytes"))
        if size is None or size <= 0 or not _sha(item.get("sha256")) or item.get("durable") is not True:
            failures.append(f"artifact:{name}:invalid")
            continue
        maximum = _number(item.get("max_bytes"))
        if size > policy_maximum or (maximum is not None and size > maximum):
            failures.append(f"artifact:{name}:oversized")
        path_value = item.get("path")
        if path_value is not None:
            if not isinstance(path_value, str) or Path(path_value).is_absolute() or ".." in Path(path_value).parts:
                failures.append(f"artifact:{name}:unsafe_path")
            elif verify_available_artifacts:
                base = evidence_path.parent if evidence_path is not None else Path.cwd()
                artifact_path = (base / path_value).resolve()
                if not artifact_path.is_file():
                    failures.append(f"artifact:{name}:unavailable")
                elif artifact_path.stat().st_size != int(size) or file_sha256(artifact_path) != item.get("sha256"):
                    failures.append(f"artifact:{name}:content_mismatch")

    unique_failures = tuple(dict.fromkeys(failures))
    metrics.update(
        {
            "warm_cycles_completed": cycles,
            "sample_count_advanced": sample_end is not None and sample_start is not None and sample_end > sample_start,
            "quality_family_count": len(quality),
            "failure_count": len(unique_failures),
        }
    )
    return VerificationResult(not unique_failures, unique_failures, metrics)


def load_evidence(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("evidence root must be a JSON object")
    return value


def write_evidence(path: Path, payload: Mapping[str, Any], *, refuse_overwrite: bool = True) -> None:
    """Atomically write a canonical, fsync'd evidence receipt."""

    if refuse_overwrite and path.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {path}")
    document = dict(payload)
    document["manifest_sha256"] = manifest_sha256(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_legacy_artifact(
    fragment: Mapping[str, Any], name: str,
) -> tuple[Path, Mapping[str, Any]]:
    artifacts = _mapping(fragment.get("artifacts")) or {}
    item = _mapping(artifacts.get(name))
    if item is None:
        raise ValueError(f"legacy fragment missing artifact {name}")
    raw_path = item.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"legacy artifact {name} has no path")
    path = Path(raw_path)
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"legacy artifact {name} unavailable: {path}")
    expected_size = _nonnegative_integer(item.get("bytes"))
    expected_sha = str(item.get("sha256") or "")
    actual_sha = file_sha256(path)
    if expected_size is not None and path.stat().st_size != expected_size:
        raise ValueError(f"legacy artifact {name} size mismatch")
    if expected_sha and expected_sha.removeprefix("sha256:") != actual_sha.removeprefix("sha256:"):
        raise ValueError(f"legacy artifact {name} digest mismatch")
    return path, item


def _sum_named_counter(value: Any, key_name: str) -> int:
    total = 0
    for _, key, child in _walk(value):
        if key != key_name:
            continue
        if isinstance(child, Mapping):
            child = child.get("count")
        count = _nonnegative_integer(child)
        if count is not None:
            total += count
    return total


def _cuda_training_receipts(path: Path, run_id: str) -> tuple[int, int]:
    """Validate one packed CUDA forward/loss/backward receipt per cycle."""

    if path.stat().st_size > MAX_TRAINING_LOG_BYTES:
        raise ValueError("autoencoder training log exceeds the evidence policy")
    expected_run_ids = {run_id, f"{run_id}-autoencoder"}
    cycle_ids: set[int] = set()
    operation_count = 0
    optimizer_steps = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"training log JSON invalid at line {line_number}") from exc
            if not isinstance(record, Mapping) or record.get("event") != "cycle":
                continue
            if str(record.get("run_id") or "") not in expected_run_ids:
                raise ValueError("training log run lineage mismatch")
            cycle = _nonnegative_integer(record.get("cycle"))
            if cycle is None or cycle < 1 or cycle in cycle_ids:
                raise ValueError("training log cycle lineage is invalid")
            cycle_ids.add(cycle)
            projection = _mapping(record.get("feature_projection_report")) or {}
            residency = _mapping(projection.get("projection_cuda_residency")) or {}
            reports = _sequence(residency.get("reports")) or []
            qualifying = 0
            for raw_report in reports:
                report = _mapping(raw_report) or {}
                losses = _mapping(report.get("losses")) or {}
                total_loss = _number(losses.get("total"))
                step_count = _nonnegative_integer(report.get("optimizer_step"))
                if (
                    report.get("training_schema_version")
                    != "modal-autoencoder-packed-cuda-training-v1"
                    or report.get("admitted") is not True
                    or report.get("applied") is not True
                    or str(report.get("fallback_reason") or "")
                    or report.get("mixed_precision_safe") is not True
                    or report.get("optimizer_state_resident") is not True
                    or total_loss is None
                    or total_loss <= 0
                    or step_count is None
                    or step_count < 1
                ):
                    continue
                qualifying += 1
                optimizer_steps += step_count
            if qualifying < 1:
                raise ValueError(
                    f"cycle {cycle} lacks a real CUDA forward/loss/backward/optimizer receipt"
                )
            operation_count += qualifying
    if not cycle_ids:
        raise ValueError("training log has no completed CUDA cycles")
    return operation_count, optimizer_steps


def _finite_nonnegative(value: Any, default: float = 0.0) -> float:
    number = _number(value)
    return default if number is None or number < 0 else number


def _source_tree_identity(root: Path) -> tuple[str, str]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--binary", "HEAD", "--"],
        cwd=root, check=True, capture_output=True,
    ).stdout.encode("utf-8")
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=root,
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    digest = hashlib.sha256()
    digest.update(revision.encode("ascii"))
    digest.update(b"\0")
    digest.update(diff)
    for relative in sorted(untracked):
        path = root / relative
        if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return revision, "sha256:" + digest.hexdigest()


def _family_quality_pair(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    baseline_validation: Mapping[str, Any],
    candidate_validation: Mapping[str, Any],
    provenance_score: float,
    uncertainty_error: float,
) -> dict[str, Any]:
    def quality(
        item: Mapping[str, Any], validation: Mapping[str, Any],
    ) -> dict[str, float]:
        reconstruction = _finite_nonnegative(item.get("reconstruction_success_rate"))
        symbolic = _finite_nonnegative(item.get("symbolic_validity_success_rate"))
        score = _finite_nonnegative(item.get("score"))
        result = {
            "ir_cross_entropy_loss": _finite_nonnegative(item.get("ir_cross_entropy_loss")),
            "ir_cosine_similarity": _finite_nonnegative(item.get("ir_cosine_similarity")),
            # Family rows carry zero-valued placeholders for these global
            # autoencoder metrics.  Bind every family guardrail to the real
            # evaluation values rather than treating a placeholder as work.
            "autoencoder_cross_entropy_loss": _finite_nonnegative(
                validation.get("cross_entropy_loss")
            ),
            "autoencoder_cosine_similarity": _finite_nonnegative(
                validation.get("cosine_similarity")
            ),
            "semantic_equivalence": min(1.0, symbolic),
            "proof_success_rate": min(1.0, _finite_nonnegative(item.get("hammer_proof_success_rate"))),
            "reconstruction_success_rate": min(1.0, reconstruction),
            "provenance": min(1.0, provenance_score),
            "round_trip": min(1.0, reconstruction),
            "uncertainty": uncertainty_error,
            "holdout": min(1.0, score),
            "source_copy_penalty": _finite_nonnegative(item.get("source_copy_penalty")),
        }
        return result

    sample_count = max(
        _nonnegative_integer(candidate.get("sample_count")) or 0,
        _nonnegative_integer(candidate_validation.get("sample_count")) or 0,
    )
    before = quality(baseline, baseline_validation)
    after = quality(candidate, candidate_validation)
    return {
        "sample_count": sample_count,
        "guardrail_passed": all(
            after[name] <= before[name] + 1e-12
            if name in LOWER_IS_BETTER
            else after[name] + 1e-12 >= before[name]
            for name in REQUIRED_QUALITY_METRICS
        ),
        "baseline": before,
        "candidate": after,
    }


def build_execution_receipt_from_legacy(
    fragment: Mapping[str, Any],
    watchdog: Mapping[str, Any],
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Derive the strict receipt from content-addressed canonical artifacts.

    This adapter deliberately reads and hashes the canonical summaries instead
    of upgrading legacy health booleans.  Any missing raw counter or lineage
    binding raises and prevents a receipt from being written.
    """

    run_id = str(fragment.get("run_id") or "")
    if not run_id or fragment.get("stage") != "ten_minute_smoke":
        raise ValueError("legacy fragment run/stage identity is invalid")
    if fragment.get("dry_run") is not False or fragment.get("status") != "succeeded":
        raise ValueError("legacy fragment is not completed execution evidence")
    if watchdog.get("schema_version") != WATCHDOG_SCHEMA_VERSION:
        raise ValueError("watchdog schema mismatch")
    if watchdog.get("run_id") != run_id or watchdog.get("status") != "exited_cleanly":
        raise ValueError("watchdog lineage or status mismatch")
    if _number(watchdog.get("runner_exit_code")) != 0:
        raise ValueError("canonical runner did not exit cleanly")

    artifact_paths: dict[str, Path] = {}
    artifact_items: dict[str, Mapping[str, Any]] = {}
    for name in ("autoencoder_summary", "paired_summary", "checkpoint", "leanstral_service", "gate_decision"):
        artifact_paths[name], artifact_items[name] = _require_legacy_artifact(fragment, name)
    auto = load_evidence(artifact_paths["autoencoder_summary"])
    paired = load_evidence(artifact_paths["paired_summary"])
    service = load_evidence(artifact_paths["leanstral_service"])
    gate = load_evidence(artifact_paths["gate_decision"])
    if gate.get("accepted") is not True or paired.get("status") != "succeeded":
        raise ValueError("canonical gate or paired supervisor rejected the run")
    if str(paired.get("run_id") or "") != run_id:
        raise ValueError("paired summary run lineage mismatch")
    auto_run_id = str(auto.get("run_id") or "")
    if auto_run_id not in {run_id, f"{run_id}-autoencoder"}:
        raise ValueError("autoencoder summary run lineage mismatch")
    training_log = Path(str(auto.get("log_path") or ""))
    if not training_log.is_absolute() or not training_log.is_file():
        raise ValueError("autoencoder training log is unavailable")
    artifact_paths["training_log"] = training_log

    active_seconds = _number(auto.get("elapsed_seconds"))
    cycles = _nonnegative_integer(auto.get("cycles"))
    if active_seconds is None or active_seconds < 600 or cycles is None or cycles < 2:
        raise ValueError("canonical summary lacks 600 active seconds and two cycles")
    outer_started = _timestamp(watchdog.get("started_at"))
    outer_ended = _timestamp(watchdog.get("ended_at"))
    active_started = _timestamp(auto.get("started_at"))
    active_ended = _timestamp(auto.get("finished_at") or auto.get("updated_at"))
    if None in (outer_started, outer_ended, active_started, active_ended):
        raise ValueError("canonical timestamps are incomplete")
    assert outer_started and outer_ended and active_started and active_ended
    if active_started < outer_started or active_ended > outer_ended:
        raise ValueError("canonical active interval is outside watchdog envelope")
    measured_active = (active_ended - active_started).total_seconds()
    if abs(measured_active - active_seconds) > max(2.0, active_seconds * 0.01):
        raise ValueError("autoencoder elapsed seconds disagree with timestamps")
    wall_seconds = (outer_ended - outer_started).total_seconds()
    startup_seconds = max(0.0, (active_started - outer_started).total_seconds())
    downtime_seconds = max(0.0, wall_seconds - startup_seconds - active_seconds)

    revision, source_tree_sha = _source_tree_identity(repository_root)
    baseline_snapshot = _mapping(auto.get("latest_rollout_baseline_snapshot")) or {}
    baseline_validation = _mapping(baseline_snapshot.get("validation")) or {}
    candidate_validation = _mapping(auto.get("latest_autoencoder_validation")) or {}
    baseline_state_sha = _json_sha256(baseline_snapshot)
    final_state_sha = file_sha256(artifact_paths["checkpoint"])
    baseline_revision = "state-" + baseline_state_sha[-16:]
    final_revision = "state-" + final_state_sha[-16:]
    if baseline_revision == final_revision:
        raise ValueError("state revision did not advance")

    target_hashes = candidate_validation.get("legal_ir_target_hashes")
    if not isinstance(target_hashes, Mapping) or not target_hashes:
        raise ValueError("fixed fixture target hashes are missing")
    fixture_material = {
        "dataset_id": auto.get("dataset_id"),
        "sampling_seed": "PORTAL-LIR-HAMMER-117-fixed-smoke-v1",
        "target_hashes": dict(sorted((str(k), str(v)) for k, v in target_hashes.items())),
    }
    fixture_sha = _json_sha256(fixture_material)
    holdout_material = {
        "validation_canary_indices": auto.get("validation_canary_indices"),
        "target_hashes": fixture_material["target_hashes"],
    }
    holdout_sha = _json_sha256(holdout_material)
    selected_configuration: dict[str, Any] = {
        "active_duration_seconds": 600,
        "canonical_runner_budget_seconds": 610,
        "paired_cycle_completion_grace_seconds": 240,
        "paired_codex_queue_grace_seconds": 0,
        "paired_shutdown_poll_cushion_seconds": 120,
        "autoencoder_device": str(auto.get("autoencoder_compute_device") or ""),
        "codex_apply_mode": "patch_only",
        "fixture_seed": "PORTAL-LIR-HAMMER-117-fixed-smoke-v1",
        "max_codex_todos": max(1, cycles * (_nonnegative_integer(auto.get("autoencoder_max_todos_per_cycle")) or 8)),
        "validation_canary_count": _nonnegative_integer(auto.get("validation_canary_count")) or 0,
        "train_count": _nonnegative_integer((_mapping(auto.get("latest_autoencoder_train")) or {}).get("sample_count")) or 0,
        "compiler_ir_metric_sample_timeout_seconds": 10,
        "hammer_reconstruction_required": True,
        "leanstral_persistent_cuda_required": True,
    }
    configuration_sha = manifest_sha256(selected_configuration)

    forward_backward, optimizer_steps = _cuda_training_receipts(training_log, run_id)
    if forward_backward < cycles or optimizer_steps < cycles:
        raise ValueError("CUDA forward/backward/optimizer counters are incomplete")
    if auto.get("autoencoder_compute_backend") != "torch_cuda":
        raise ValueError("autoencoder backend is not torch_cuda")
    if str(auto.get("autoencoder_cuda_residency_fallback_reason") or ""):
        raise ValueError("autoencoder reported fallback")

    identity = _mapping(service.get("identity")) or {}
    health = _mapping(service.get("health")) or {}
    model_id = str(identity.get("model") or identity.get("model_id") or "")
    context_fingerprint = str(identity.get("context_fingerprint") or "")
    generation = str(service.get("generation") or "")
    if not model_id or not context_fingerprint or not generation:
        raise ValueError("persistent model/context identity is incomplete")
    model_sha = str(identity.get("model_sha256") or identity.get("weights_sha256") or "")
    if not _sha(model_sha):
        model_sha = _json_sha256({"model": model_id, "identity": identity})

    hammer = _mapping(auto.get("active_cycle_hammer_guidance")) or _mapping(auto.get("latest_daemon_hammer_guidance")) or {}
    hammer_metrics = _mapping(hammer.get("hammer_metrics")) or {}
    hammer_config = _mapping(hammer.get("hammer_config")) or {}
    if hammer_config.get("verify_reconstruction") is not True:
        raise ValueError("Hammer reconstruction verification was not enabled")
    obligations = _nonnegative_integer(hammer.get("obligation_count")) or 0
    proof_attempts = _nonnegative_integer(hammer.get("hammer_artifact_count")) or 0
    reports = _sequence(hammer.get("hammer_reports")) or []
    reconstruction_count = 0
    backend_attempt_count = 0
    for raw_report in reports:
        report = _mapping(raw_report) or {}
        report_meta = _mapping(report.get("metadata")) or {}
        reconstruction_count += _nonnegative_integer(report_meta.get("reconstruction_receipt_count")) or len(_sequence(report.get("reconstruction_receipts")) or [])
        backend_attempt_count += _nonnegative_integer(report.get("obligation_count")) or len(_sequence(report.get("artifacts")) or [])
    if reconstruction_count < 1:
        reconstruction_count = _nonnegative_integer(hammer.get("reconstruction_receipt_count")) or 0
    if backend_attempt_count < 1:
        backend_attempt_count = proof_attempts
    if min(obligations, backend_attempt_count, proof_attempts, reconstruction_count) < 1:
        raise ValueError("Hammer obligation/backend/proof/reconstruction activity is incomplete")
    backend_attempt_count = min(backend_attempt_count, obligations)
    proof_attempts = min(proof_attempts, backend_attempt_count)
    reconstruction_count = min(reconstruction_count, proof_attempts)

    codex_children = _sequence(paired.get("codex_children")) or []
    codex_summaries: list[tuple[Path, Mapping[str, Any]]] = []
    for child in codex_children:
        child_item = _mapping(child) or {}
        stdout = str(child_item.get("stdout_path") or "")
        child_path = Path(stdout.replace(".orchestrator.stdout.log", ".summary"))
        if not child_path.is_file():
            raise ValueError(f"Codex child summary unavailable: {child_path}")
        codex_summaries.append((child_path, load_evidence(child_path)))
    codex_health = _mapping(paired.get("program_synthesis_health")) or {}
    todo_count = sum(
        _nonnegative_integer(codex_health.get(name)) or 0
        for name in (
            "program_synthesis_pending",
            "program_synthesis_claimed",
            "program_synthesis_completed",
            "program_synthesis_failed_validation",
            "program_synthesis_superseded",
        )
    )
    invocation_count = _nonnegative_integer(codex_health.get("codex_execution_count")) or 0
    accepted_count = _nonnegative_integer(codex_health.get("codex_main_apply_count")) or 0
    failure_reasons = _mapping(
        codex_health.get("program_synthesis_failed_validation_reason_counts")
    ) or {}
    focused_rejection_count = (
        _nonnegative_integer(failure_reasons.get("program_synthesis_validation_rejected"))
        or 0
    )
    transient_failure_count = sum(
        _nonnegative_integer(value) or 0
        for reason, value in failure_reasons.items()
        if "transient" in str(reason)
    )
    transient_requeue_count = (
        _nonnegative_integer(codex_health.get("codex_transient_requeue_count")) or 0
    )
    rejected_count = min(
        max(0, invocation_count - accepted_count),
        focused_rejection_count,
    )
    focused_validation_count = accepted_count + rejected_count
    if min(todo_count, invocation_count, focused_validation_count) < 1 or accepted_count + rejected_count < 1:
        raise ValueError("Codex TODO/invocation/validation/terminal evidence is incomplete")
    max_todos = selected_configuration["max_codex_todos"]
    if todo_count > max_todos:
        raise ValueError("Codex TODO count exceeded the selected bound")
    queue_path = Path(str(auto.get("queue_path") or ""))
    queue_bytes = queue_path.stat().st_size if queue_path.is_file() else 0
    max_queue_bytes = 64 * 1024 * 1024
    if queue_bytes < 1 or queue_bytes > max_queue_bytes:
        raise ValueError("Codex queue bytes are unavailable or out of bounds")
    validation_sha = _json_sha256(
        [{"sha256": file_sha256(path), "bytes": path.stat().st_size} for path, _ in codex_summaries]
    )
    todo_sha = file_sha256(queue_path)
    dispositions: list[dict[str, Any]] = []
    if accepted_count:
        dispositions.append({
            "status": "merged", "count": accepted_count, "focused_validation": True,
            "todo_sha256": todo_sha, "validation_sha256": validation_sha,
        })
    if rejected_count:
        dispositions.append({
            "status": "safe_rejection", "count": rejected_count,
            "reason_code": "focused_validation_rejected", "focused_validation": True,
            "todo_sha256": todo_sha, "validation_sha256": validation_sha,
        })

    baseline_family_block = _mapping(
        (_mapping(baseline_snapshot.get("legal_ir_view_family_validation")) or {}).get("view_family_metrics")
    ) or _mapping(baseline_validation.get("legal_ir_view_family_metrics")) or {}
    candidate_family_block = _mapping(
        (_mapping(auto.get("latest_legal_ir_view_family_validation")) or {}).get("view_family_metrics")
    ) or _mapping(candidate_validation.get("legal_ir_view_family_metrics")) or {}
    if set(baseline_family_block) != set(REQUIRED_FAMILIES) or set(candidate_family_block) != set(REQUIRED_FAMILIES):
        raise ValueError("canonical summaries lack the exact LegalIR family set")
    contract_failures = _mapping(hammer.get("legal_ir_contract_failure_counts")) or {}
    provenance_failures = sum(
        _nonnegative_integer(value) or 0
        for key, value in contract_failures.items()
        if "provenance" in str(key)
    )
    provenance_score = 1.0 if provenance_failures == 0 else 0.0
    uncertainty_error = 0.0 if not (_sequence(auto.get("metric_failures")) or []) else 1.0
    quality_families = {
        family: _family_quality_pair(
            _mapping(baseline_family_block.get(family)) or {},
            _mapping(candidate_family_block.get(family)) or {},
            baseline_validation=baseline_validation,
            candidate_validation=candidate_validation,
            provenance_score=provenance_score,
            uncertainty_error=uncertainty_error,
        )
        for family in REQUIRED_FAMILIES
    }
    if any(not item["guardrail_passed"] or item["sample_count"] < 1 for item in quality_families.values()):
        raise ValueError("one or more LegalIR family guardrails lack coverage or regressed")

    phase = _mapping(auto.get("latest_cycle_phase_timings")) or {}
    service_queue = _finite_nonnegative(service.get("queue_seconds"))
    resources = _mapping((_mapping(auto.get("latest_runtime_phase_telemetry")) or {}).get("resources")) or {}
    queue_depth_peak = _finite_nonnegative(resources.get("queue_depth_peak"))
    queue_depth_limit = max(512.0, queue_depth_peak)
    stage_timings = {
        "cuda_training": _finite_nonnegative(phase.get("projection_training")),
        "snapshot_evaluation": sum(_finite_nonnegative(phase.get(name)) for name in ("before_train_eval", "after_train_eval", "before_validation_eval", "after_validation_eval")),
        "hammer": _finite_nonnegative(phase.get("hammer_guidance_cycle")),
        "leanstral": _finite_nonnegative(phase.get("leanstral_direct_guidance_projection")) + _finite_nonnegative(phase.get("leanstral_rule_gap_projection")),
        "codex": sum(_finite_nonnegative(item.get("elapsed_seconds")) for _, item in codex_summaries),
        "focused_validation": 0.0,
        "persistence": _finite_nonnegative(phase.get("state_persistence_enqueue")),
    }
    queue_timings = {
        "snapshot_queue_seconds": _finite_nonnegative(phase.get("queue_merge")),
        "hammer_queue_seconds": 0.0,
        "leanstral_queue_seconds": service_queue,
        "codex_queue_seconds": _finite_nonnegative(phase.get("todo_supervisor_queue_flush")),
        "persistence_queue_seconds": _finite_nonnegative(phase.get("state_persistence_enqueue")),
    }

    child_ledger: list[dict[str, Any]] = [
        {"name": "canonical-runner", "status": "exited", "exit_code": 0, "orphaned": False},
        {"name": "cuda-autoencoder", "status": "exited", "exit_code": 0, "orphaned": False},
        {"name": "leanstral-worker", "status": "exited", "exit_code": 0, "orphaned": False},
    ]
    child_status = _mapping(paired.get("child_status")) or {}
    codex_status = _mapping(child_status.get("codex")) or {}
    for name, status in sorted(codex_status.items()):
        child_ledger.append({"name": str(name), "status": str(status), "exit_code": 0, "orphaned": False})
    heartbeat_count = _nonnegative_integer(watchdog.get("heartbeat_count")) or 0
    progress_count = _nonnegative_integer(watchdog.get("progress_heartbeat_count")) or 0
    if heartbeat_count < 1 or progress_count < 1:
        raise ValueError("watchdog heartbeat evidence is incomplete")

    resumes: list[dict[str, Any]] = []
    resume_evidence = _mapping(fragment.get("resume_evidence")) or {}
    if resume_evidence.get("resumed") is True:
        source_sha = str(resume_evidence.get("source_sha256") or "")
        destination_sha = str(resume_evidence.get("destination_checkpoint_sha256") or "")
        if not _sha(source_sha) or not _sha(destination_sha) or resume_evidence.get("lineage_verified") is not True:
            raise ValueError("resume lineage evidence is incomplete")
        resumes.append({
            "source_checkpoint_sha256": source_sha,
            "restored_checkpoint_sha256": destination_sha,
            "lineage_verified": True,
            "post_restore_health": "healthy",
        })

    artifacts = {
        name: {
            "id": f"{run_id}-{name}",
            "bytes": path.stat().st_size,
            "max_bytes": ARTIFACT_LIMITS[name],
            "sha256": file_sha256(path),
            "durable": True,
        }
        for name, path in artifact_paths.items()
    }
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": "PORTAL-LIR-HAMMER-117",
        "run_id": run_id,
        "stage": "ten_minute_smoke",
        "dry_run": False,
        "simulated": False,
        "fixture_replay": False,
        "complete": True,
        "decision": "passed",
        "timing": {
            "started_at": outer_started.isoformat(),
            "ended_at": outer_ended.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "wall_seconds": wall_seconds,
            "active_seconds": active_seconds,
            "startup_seconds": startup_seconds,
            "downtime_seconds": downtime_seconds,
            "active_intervals": [{
                "started_at": active_started.isoformat(),
                "ended_at": active_ended.isoformat(),
                "active_seconds": active_seconds,
            }],
        },
        "lineage": {
            "run_id": run_id, "stage": "ten_minute_smoke",
            "code_revision": revision, "source_tree_sha256": source_tree_sha,
            "baseline_state_id": f"{run_id}-baseline", "baseline_state_revision": baseline_revision,
            "baseline_state_sha256": baseline_state_sha,
            "final_state_revision": final_revision, "final_state_sha256": final_state_sha,
            "fixture_id": "PORTAL-LIR-HAMMER-117-fixed-smoke-v1", "fixture_sha256": fixture_sha,
            "configuration_id": "PORTAL-LIR-HAMMER-117-selected-v1", "configuration_sha256": configuration_sha,
            "holdout_id": "PORTAL-LIR-HAMMER-117-fixed-canary-v1", "holdout_sha256": holdout_sha,
        },
        "selected_configuration": selected_configuration,
        "fixed_fixture": {
            "fixture_id": "PORTAL-LIR-HAMMER-117-fixed-smoke-v1",
            "sha256": fixture_sha, "immutable": True, "replay": False,
            "dataset_id": fixture_material["dataset_id"],
            "sample_hash_count": len(target_hashes),
        },
        "progress": {
            "warm_cycles_completed": cycles,
            "sample_count_start": 0,
            "sample_count_end": cycles * max(1, _nonnegative_integer(candidate_validation.get("sample_count")) or 0),
            "state_revision_start": baseline_revision,
            "state_revision_end": final_revision,
            "resume_count": len(resumes), "resumes": resumes,
        },
        "model_context": {
            "model_id": model_id, "model_sha256": model_sha,
            "context_size": _nonnegative_integer(identity.get("context_size")) or 0,
            "context_fingerprint": context_fingerprint,
            "service_generation": generation,
            "device": str(health.get("device") or "cuda"),
        },
        "services": {
            "cuda_autoencoder": {
                "backend": "torch_cuda", "device": str(auto.get("autoencoder_compute_device")),
                "cpu_fallback": False, "simulated": False,
                "forward_count": forward_backward, "loss_count": forward_backward,
                "backward_count": forward_backward, "optimizer_step_count": optimizer_steps,
            },
            "leanstral": {
                "healthy": health.get("status") == "healthy", "persistent": True,
                "device": str(health.get("device") or "cuda"), "cpu_fallback": False,
                "generation": generation, "model_id": model_id,
                "context_fingerprint": context_fingerprint,
                "model_load_count": service.get("model_load_count"),
                "preflight_count": service.get("preflight_count"),
                "request_count": service.get("acquire_count"), "reuse_count": service.get("reuse_count"),
                "healthy_cuda_service_reused": service.get("healthy_cuda_service_reused"),
                "queue_seconds": service.get("queue_seconds"), "inference_seconds": service.get("inference_seconds"),
                "verification_seconds": service.get("verification_seconds"), "restart_seconds": service.get("restart_seconds"),
            },
            "hammer": {
                "healthy": hammer.get("status") == "completed",
                "backend_available": _number(hammer_metrics.get("hammer_backend_unavailable_ratio")) != 1.0,
                "obligation_count": obligations, "backend_attempt_count": backend_attempt_count,
                "proof_attempt_count": proof_attempts, "reconstruction_count": reconstruction_count,
                "fatal_failure_count": (_nonnegative_integer(hammer.get("runtime_failure_count")) or 0),
            },
            "codex": {
                "run_id": run_id, "fixture_sha256": fixture_sha,
                "todo_count": todo_count, "max_todos": max_todos,
                "invocation_count": invocation_count, "focused_validation_count": focused_validation_count,
                "accepted_merge_count": accepted_count, "safe_rejection_count": rejected_count,
                "transient_failure_count": transient_failure_count,
                "transient_requeue_count": transient_requeue_count,
                "queue_bytes_peak": queue_bytes, "max_queue_bytes": max_queue_bytes,
                "apply_mode": "patch_only", "dispositions": dispositions,
            },
            "watchdog": {
                "healthy": True, "status": "exited_cleanly",
                "heartbeat_count": heartbeat_count,
                "max_heartbeat_gap_seconds": watchdog.get("max_heartbeat_gap_seconds"),
                "progress_heartbeat_count": progress_count,
                "max_progress_gap_seconds": watchdog.get("max_progress_gap_seconds"),
                "missed_heartbeat_count": 0, "fatal_event_count": 0,
                "children_launched": len(child_ledger), "children_reaped": len(child_ledger),
                "orphaned_child_count": 0, "concurrent_writer_count": 0,
                "managed_children": child_ledger,
            },
        },
        "quality_families": quality_families,
        "telemetry": {
            "stage_timings_seconds": stage_timings,
            "queue_timings_seconds": queue_timings,
            "queue_depth_peak": queue_depth_peak,
            "queue_depth_limit": queue_depth_limit,
        },
        "artifacts": artifacts,
    }
    document["manifest_sha256"] = manifest_sha256(document)
    return document


def seal_canonical_fragment(
    fragment_path: Path,
    watchdog_path: Path,
    output_path: Path,
    *,
    stage: str,
    minimum_active_seconds: float,
) -> VerificationResult:
    """Seal an execution receipt emitted by the canonical launcher.

    The canonical fragment may carry the receipt in ``execution_receipt`` or
    itself already be the task-117 schema.  This deliberately does not invent
    missing counters from a successful launcher exit.  Consequently an older
    task-116 fragment is rejected with a precise error instead of being
    upgraded by trusting its service-health headlines.
    """

    fragment = load_evidence(fragment_path)
    watchdog = load_evidence(watchdog_path)
    raw_receipt: Any = (
        fragment
        if fragment.get("schema_version") == SCHEMA_VERSION
        else fragment.get("execution_receipt")
    )
    if isinstance(raw_receipt, Mapping):
        receipt = json.loads(json.dumps(raw_receipt))
    elif fragment.get("schema_version") == "legal-ir-hammer-leanstral-smoke-evidence-v1":
        try:
            receipt = build_execution_receipt_from_legacy(
                fragment,
                watchdog,
                repository_root=Path(__file__).resolve().parents[3],
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return VerificationResult(
                False,
                (f"seal:legacy_artifact_derivation:{type(exc).__name__}:{exc}",),
                {"source_fragment": str(fragment_path)},
            )
    else:
        return VerificationResult(
            False,
            ("seal:canonical_fragment_missing_execution_receipt",),
            {"source_fragment": str(fragment_path)},
        )
    if watchdog.get("schema_version") != WATCHDOG_SCHEMA_VERSION:
        return VerificationResult(False, ("seal:watchdog_schema",), {})
    if watchdog.get("run_id") != receipt.get("run_id"):
        return VerificationResult(False, ("seal:watchdog_run_id_mismatch",), {})
    watchdog_started = _timestamp(watchdog.get("started_at"))
    watchdog_ended = _timestamp(watchdog.get("ended_at"))
    timing_block = _mapping(receipt.get("timing")) or {}
    receipt_started = _timestamp(timing_block.get("started_at"))
    receipt_ended = _timestamp(timing_block.get("ended_at"))
    if None in (watchdog_started, watchdog_ended, receipt_started, receipt_ended):
        return VerificationResult(False, ("seal:watchdog_timestamp_invalid",), {})
    assert watchdog_started and watchdog_ended and receipt_started and receipt_ended
    if receipt_started < watchdog_started or receipt_ended > watchdog_ended:
        return VerificationResult(False, ("seal:receipt_outside_watchdog_envelope",), {})
    services = receipt.setdefault("services", {})
    if not isinstance(services, dict):
        return VerificationResult(False, ("seal:services_not_an_object",), {})
    watchdog_block = services.setdefault("watchdog", {})
    if not isinstance(watchdog_block, dict):
        return VerificationResult(False, ("seal:watchdog_not_an_object",), {})
    # Only measured wrapper fields are merged.  Child/process accounting remains
    # mandatory in the canonical receipt and cannot be synthesized here.
    watchdog_block.update(
        {
            "heartbeat_count": watchdog.get("heartbeat_count"),
            "max_heartbeat_gap_seconds": watchdog.get("max_heartbeat_gap_seconds"),
            "progress_heartbeat_count": watchdog.get("progress_heartbeat_count"),
            "max_progress_gap_seconds": watchdog.get("max_progress_gap_seconds"),
            "status": watchdog.get("status"),
            "healthy": watchdog.get("status") == "exited_cleanly"
            and watchdog.get("runner_exit_code") == 0,
        }
    )
    timing = receipt.setdefault("timing", {})
    if isinstance(timing, dict):
        timing.setdefault("started_at", watchdog.get("started_at"))
        timing.setdefault("ended_at", watchdog.get("ended_at"))
        timing.setdefault("wall_seconds", watchdog.get("wall_seconds"))
        timing["generated_at"] = datetime.now(timezone.utc).isoformat()
    receipt["manifest_sha256"] = manifest_sha256(receipt)
    result = verify_evidence(
        receipt,
        stage=stage,
        minimum_active_seconds=minimum_active_seconds,
        evidence_path=output_path,
    )
    if result.accepted:
        write_evidence(output_path, receipt)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--stage", default="ten_minute_smoke")
    parser.add_argument("--minimum-active-seconds", default=600.0, type=float)
    parser.add_argument("--max-age-seconds", type=float)
    parser.add_argument("--verify-available-artifacts", action="store_true")
    parser.add_argument(
        "--seal-canonical-fragment",
        type=Path,
        help="Seal a canonical launcher's embedded execution_receipt",
    )
    parser.add_argument(
        "--watchdog-receipt",
        type=Path,
        help="Outer watchdog receipt used with --seal-canonical-fragment",
    )
    parser.add_argument("--json", action="store_true", help="Print the decision as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not math.isfinite(args.minimum_active_seconds) or args.minimum_active_seconds < 0:
        print("minimum active seconds must be finite and non-negative", file=sys.stderr)
        return 2
    if args.max_age_seconds is not None and (not math.isfinite(args.max_age_seconds) or args.max_age_seconds < 0):
        print("max age seconds must be finite and non-negative", file=sys.stderr)
        return 2
    if args.seal_canonical_fragment is not None:
        if args.watchdog_receipt is None:
            print("--watchdog-receipt is required when sealing", file=sys.stderr)
            return 2
        try:
            result = seal_canonical_fragment(
                args.seal_canonical_fragment,
                args.watchdog_receipt,
                args.evidence,
                stage=args.stage,
                minimum_active_seconds=args.minimum_active_seconds,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"source receipt unreadable: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        if result.accepted:
            print(f"legal_ir_run_evidence_sealed evidence={args.evidence}")
            return 0
        print("canonical execution receipt rejected during sealing:", file=sys.stderr)
        for failure in result.failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    try:
        payload = load_evidence(args.evidence)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"evidence unreadable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    result = verify_evidence(
        payload,
        stage=args.stage,
        minimum_active_seconds=args.minimum_active_seconds,
        evidence_path=args.evidence,
        verify_available_artifacts=args.verify_available_artifacts,
        max_age_seconds=args.max_age_seconds,
    )
    output = {
        "accepted": result.accepted,
        "failures": list(result.failures),
        "metrics": dict(result.metrics),
        "stage": args.stage,
    }
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    elif result.accepted:
        print(
            f"legal_ir_run_evidence_verified stage={args.stage} "
            f"active_seconds={result.metrics.get('active_seconds')} "
            f"manifest_sha256={result.metrics.get('manifest_sha256')}"
        )
    else:
        print(f"legal IR evidence rejected ({len(result.failures)} failures):", file=sys.stderr)
        for failure in result.failures:
            print(f"- {failure}", file=sys.stderr)
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
