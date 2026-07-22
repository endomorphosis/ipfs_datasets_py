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
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "legal-ir-10-minute-integrated-smoke-evidence-v1"
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
            last_end = finish
            interval_total += seconds
    if active is not None and abs(interval_total - active) > max(1.0, active * 0.01):
        failures.append("timing:active_interval_sum")
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
    for name in ("forward_count", "loss_count", "backward_count", "optimizer_step_count"):
        if not _positive(auto, name):
            failures.append(f"service:autoencoder:{name}")

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
        if not _positive(lean, name):
            failures.append(f"service:leanstral:{name}")
    if (_number(lean.get("request_count")) or 0) < 2 or lean.get("healthy_cuda_service_reused") is not True:
        failures.append("service:leanstral:not_reused_after_warmup")
    for name in ("queue_seconds", "inference_seconds", "verification_seconds", "restart_seconds"):
        value = _number(lean.get(name))
        if value is None or value < 0:
            failures.append(f"service:leanstral:{name}")

    hammer = _mapping(services.get("hammer")) or {}
    if hammer.get("healthy") is not True or hammer.get("backend_available") is not True:
        failures.append("service:hammer:backend")
    for name in ("obligation_count", "backend_attempt_count", "proof_attempt_count", "reconstruction_count"):
        if not _positive(hammer, name):
            failures.append(f"service:hammer:{name}")
    if _number(hammer.get("fatal_failure_count")) != 0:
        failures.append("service:hammer:fatal_failure")

    codex = _mapping(services.get("codex")) or {}
    if codex.get("fixture_sha256") != lineage.get("fixture_sha256") or codex.get("run_id") != run_id:
        failures.append("service:codex:lineage")
    for name in ("todo_count", "invocation_count", "focused_validation_count"):
        if not _positive(codex, name):
            failures.append(f"service:codex:{name}")
    max_todos, todo_count = _number(codex.get("max_todos")), _number(codex.get("todo_count"))
    max_bytes, queue_bytes = _number(codex.get("max_queue_bytes")), _number(codex.get("queue_bytes_peak"))
    if max_todos is None or todo_count is None or todo_count > max_todos or max_todos <= 0:
        failures.append("service:codex:todo_bound")
    if max_bytes is None or queue_bytes is None or queue_bytes > max_bytes or max_bytes <= 0:
        failures.append("service:codex:queue_bound")
    accepted_count = _number(codex.get("accepted_merge_count")) or 0
    rejected_count = _number(codex.get("safe_rejection_count")) or 0
    if accepted_count + rejected_count < 1:
        failures.append("service:codex:no_safe_terminal_path")
    dispositions = _sequence(codex.get("dispositions"))
    if not dispositions:
        failures.append("service:codex:dispositions_missing")
    else:
        for index, raw in enumerate(dispositions):
            item = _mapping(raw) or {}
            if item.get("status") not in {"merged", "safe_rejection"}:
                failures.append(f"service:codex:disposition:{index}:status")
            if not _sha(item.get("todo_sha256")) or not _sha(item.get("validation_sha256")):
                failures.append(f"service:codex:disposition:{index}:digest")
            if item.get("focused_validation") is not True:
                failures.append(f"service:codex:disposition:{index}:validation")
            if item.get("status") == "safe_rejection" and not str(item.get("reason_code") or "").strip():
                failures.append(f"service:codex:disposition:{index}:reason")

    watchdog = _mapping(services.get("watchdog")) or {}
    if watchdog.get("healthy") is not True or watchdog.get("status") != "exited_cleanly":
        failures.append("service:watchdog:health")
    for name in ("heartbeat_count", "children_launched", "children_reaped"):
        if not _positive(watchdog, name):
            failures.append(f"service:watchdog:{name}")
    if watchdog.get("children_launched") != watchdog.get("children_reaped"):
        failures.append("service:watchdog:children_not_reaped")
    for name in ("missed_heartbeat_count", "fatal_event_count", "orphaned_child_count", "concurrent_writer_count"):
        if _number(watchdog.get(name)) != 0:
            failures.append(f"service:watchdog:{name}")
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
    for name in ("autoencoder_summary", "paired_summary", "checkpoint", "leanstral_service", "gate_decision"):
        item = _mapping(artifacts.get(name))
        if item is None:
            failures.append(f"artifact:{name}:missing")
            continue
        size = _number(item.get("bytes"))
        if size is None or size <= 0 or not _sha(item.get("sha256")) or item.get("durable") is not True:
            failures.append(f"artifact:{name}:invalid")
            continue
        maximum = _number(item.get("max_bytes"))
        if maximum is not None and size > maximum:
            failures.append(f"artifact:{name}:oversized")
        path_value = item.get("path")
        if path_value is not None:
            if not isinstance(path_value, str) or Path(path_value).is_absolute() or ".." in Path(path_value).parts:
                failures.append(f"artifact:{name}:unsafe_path")
            elif verify_available_artifacts:
                base = evidence_path.parent if evidence_path is not None else Path.cwd()
                artifact_path = (base / path_value).resolve()
                if artifact_path.exists() and (artifact_path.stat().st_size != int(size) or file_sha256(artifact_path) != item.get("sha256")):
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
    raw_receipt: Any = (
        fragment
        if fragment.get("schema_version") == SCHEMA_VERSION
        else fragment.get("execution_receipt")
    )
    if not isinstance(raw_receipt, Mapping):
        return VerificationResult(
            False,
            ("seal:canonical_fragment_missing_execution_receipt",),
            {"source_fragment": str(fragment_path)},
        )
    receipt = json.loads(json.dumps(raw_receipt))
    watchdog = load_evidence(watchdog_path)
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
