"""Reproducible, source-free baselines for one modal-autoencoder cycle.

This module is deliberately an *offline* reducer.  It consumes summaries made
by :mod:`runtime_telemetry` and ``uscode_modal_daemon_runner`` and never calls a
trainer, compiler, prover, model service, or Codex worker.  Consequently adding
or removing this benchmark cannot change training order, random-number state,
cache contents, or promotion decisions.

The reducer has three important properties:

* cold and warm observations must replay exactly the same ordered sample IDs;
* every frozen document is canonical JSON with a digest over its complete body;
* incomplete resource, lane, I/O, or per-family guardrail evidence fails closed
  by default rather than silently turning "not measured" into a zero.

The accepted input is intentionally tolerant of the stable aliases emitted by
older daemon versions.  The output, however, has one versioned schema and is
strictly source-free: sample identifiers are hashed before they are retained.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal, Optional

from .legal_ir_family_evaluator import (
    LEGAL_IR_EVALUATION_FAMILIES,
    canonical_legal_ir_evaluation_family,
)
from .runtime_telemetry import RUNTIME_PHASES, canonical_runtime_phase


CYCLE_THROUGHPUT_BASELINE_SCHEMA_VERSION: Final = (
    "legal-ir-modal-autoencoder-cycle-throughput-v1"
)
CYCLE_THROUGHPUT_BENCHMARK_SCHEMA_VERSION: Final = (
    CYCLE_THROUGHPUT_BASELINE_SCHEMA_VERSION
)
CANONICAL_SAMPLE_SCHEMA_VERSION: Final = "legal-ir-cycle-canonical-sample-v1"

TimeKind = Literal[
    "useful_compute", "wait", "serialization", "persistence", "child_process"
]
TIME_KINDS: Final[tuple[TimeKind, ...]] = (
    "useful_compute",
    "wait",
    "serialization",
    "persistence",
    "child_process",
)

WAIT_PHASES: Final = frozenset(("leanstral_queue", "codex_queue_wait"))
SERIALIZATION_PHASES: Final = frozenset(
    (
        "serialization",
        "state_serialization",
        "checkpoint_serialization",
        "disagreement_export",
    )
)
PERSISTENCE_PHASES: Final = frozenset(("state_persistence",))
CHILD_PROCESS_PHASES: Final = frozenset(
    (
        "solver_execution",
        "lean_reconstruction",
        "leanstral_inference",
        "validation",
    )
)

GUARDRAIL_NAMES: Final = (
    "cross_entropy_loss",
    "cosine_similarity",
    "semantic_equivalence",
    "proof_validity",
    "round_trip",
    "source_copy",
)

_FAMILY_ALIASES: Final = {
    "kg": "knowledge_graphs",
    "knowledge_graph": "knowledge_graphs",
    "prover": "external_provers",
    "external_prover": "external_provers",
    "frame": "frame_logic",
    "flogic": "frame_logic",
}
_SAMPLE_ID_KEYS: Final = (
    "benchmark_sample_ids",
    "canonical_sample_ids",
    "latest_compiler_ir_validation_sample_ids",
    "compiler_ir_validation_sample_ids",
    "sample_ids",
)
_VOLATILE_SOURCE_KEYS: Final = frozenset(
    {
        "captured_at",
        "created_at",
        "ended_at",
        "parent_span_id",
        "span_id",
        "started_at",
        "timestamp",
        "trace_id",
    }
)


class BaselineEvidenceError(ValueError):
    """Raised when evidence cannot support an immutable matched baseline."""


def canonical_json(value: Any) -> str:
    """Return the one JSON representation used for every artifact digest."""

    return json.dumps(
        _thaw(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_digest(value: Any) -> str:
    """Return the SHA-256 digest of canonical JSON-compatible evidence."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


canonical_digest = content_digest


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in sorted(value.items())}
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_thaw(item) for item in value]
    return value


def _finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nonnegative(value: Any, default: float = 0.0) -> float:
    number = _finite(value)
    return default if number is None else max(0.0, number)


def _integer(value: Any, default: int = 0) -> int:
    number = _finite(value)
    return default if number is None else max(0, int(number))


def _nested_mappings(value: Any, *, max_depth: int = 8) -> Iterable[Mapping[str, Any]]:
    if max_depth < 0:
        return
    if isinstance(value, Mapping):
        yield value
        for item in value.values():
            yield from _nested_mappings(item, max_depth=max_depth - 1)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _nested_mappings(item, max_depth=max_depth - 1)


def _first(summary: Mapping[str, Any], keys: Sequence[str]) -> tuple[Any, bool]:
    for block in _nested_mappings(summary):
        for key in keys:
            if key in block and block[key] is not None:
                return block[key], True
    return None, False


def _number(summary: Mapping[str, Any], keys: Sequence[str]) -> tuple[float, bool]:
    value, observed = _first(summary, keys)
    number = _finite(value)
    return (number if number is not None else 0.0), bool(observed and number is not None)


def _normalized_source(value: Any) -> Any:
    """Remove span UUIDs/timestamps while retaining all measurement evidence."""

    if isinstance(value, Mapping):
        return {
            str(key): _normalized_source(item)
            for key, item in sorted(value.items())
            if str(key) not in _VOLATILE_SOURCE_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalized_source(item) for item in value]
    return value


def _sample_ids(summary: Mapping[str, Any]) -> tuple[str, ...]:
    blocks = list(_nested_mappings(summary))

    def parse(raw: Any) -> tuple[str, ...]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            return ()
        ids = tuple(str(item).strip() for item in raw if str(item).strip())
        if len(ids) != len(set(ids)):
            raise BaselineEvidenceError("canonical sample IDs must be unique")
        return ids

    # Prefer an explicit canonical manifest and benchmark keys globally.  This
    # prevents a deeply nested evaluator-local ``sample_ids`` list from being
    # mistaken for the full replay sample merely because it appeared earlier
    # in mapping insertion order.
    for block in blocks:
        canonical = block.get("canonical_sample")
        if isinstance(canonical, Mapping):
            for raw in (canonical.get("ordered_sample_ids"), canonical.get("sample_ids")):
                ids = parse(raw)
                if ids:
                    return ids
    for key in _SAMPLE_ID_KEYS:
        for block in blocks:
            ids = parse(block.get(key))
            if ids:
                return ids
    raise BaselineEvidenceError(
        "summary is missing ordered canonical sample IDs; a count is not replay evidence"
    )


def canonical_sample_manifest(sample_ids: Sequence[str]) -> dict[str, Any]:
    """Build a source-free identity for an ordered canonical replay sample."""

    ordered = tuple(str(item).strip() for item in sample_ids)
    if not ordered or any(not item for item in ordered):
        raise BaselineEvidenceError("canonical sample must contain non-empty sample IDs")
    if len(ordered) != len(set(ordered)):
        raise BaselineEvidenceError("canonical sample IDs must be unique")
    ordered_hashes = tuple(
        f"sha256:{hashlib.sha256(item.encode('utf-8')).hexdigest()}" for item in ordered
    )
    identity = {
        "schema_version": CANONICAL_SAMPLE_SCHEMA_VERSION,
        "sample_count": len(ordered_hashes),
        "ordered_sample_id_hashes": list(ordered_hashes),
    }
    identity["sample_digest"] = content_digest(identity)
    return identity


def _runtime_block(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("runtime_telemetry", "latest_runtime_phase_telemetry"):
        value = summary.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _time_kind(phase: str, span: Optional[Mapping[str, Any]] = None) -> TimeKind:
    attributes = span.get("attributes", {}) if isinstance(span, Mapping) else {}
    explicit = ""
    if isinstance(attributes, Mapping):
        explicit = str(attributes.get("time_kind") or attributes.get("work_kind") or "")
    normalized = explicit.strip().lower().replace("-", "_")
    if normalized in TIME_KINDS:
        return normalized  # type: ignore[return-value]
    phase_name = phase.strip().lower().replace("-", "_")
    if phase_name in WAIT_PHASES or "queue_wait" in phase_name or phase_name.endswith("_wait"):
        return "wait"
    if phase_name in SERIALIZATION_PHASES or "serializ" in phase_name or "hashing" in phase_name:
        return "serialization"
    if phase_name in PERSISTENCE_PHASES or "persist" in phase_name or "checkpoint_write" in phase_name:
        return "persistence"
    if phase_name in CHILD_PROCESS_PHASES or bool(span and span.get("child_process") is True):
        return "child_process"
    return "useful_compute"


def _phase_records(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    spans = _runtime_block(summary).get("spans", ())
    if isinstance(spans, Sequence) and not isinstance(spans, (str, bytes, bytearray)):
        for raw in spans:
            if not isinstance(raw, Mapping):
                continue
            raw_phase = str(raw.get("phase") or "")
            if not raw_phase or raw_phase == "cycle":
                continue
            duration = _finite(raw.get("duration_seconds"))
            if duration is None or duration < 0.0:
                continue
            phase = canonical_runtime_phase(raw_phase)
            records.append(
                {
                    "phase": phase,
                    "duration_seconds": duration,
                    "unit_count": _nonnegative(raw.get("unit_count")),
                    "status": str(raw.get("status") or "unknown"),
                    "cache_hit": raw.get("cache_hit"),
                    "time_kind": _time_kind(phase, raw),
                }
            )
    if records:
        return records
    timings = summary.get("latest_cycle_phase_timings") or summary.get("cycle_phase_timings")
    if isinstance(timings, Mapping):
        for raw_phase, value in timings.items():
            duration = _finite(value)
            if duration is None or duration < 0.0:
                continue
            phase = canonical_runtime_phase(str(raw_phase))
            records.append(
                {
                    "phase": phase,
                    "duration_seconds": duration,
                    "unit_count": 0.0,
                    "status": "ok",
                    "cache_hit": None,
                    "time_kind": _time_kind(phase),
                }
            )
    return records


def _elapsed(summary: Mapping[str, Any]) -> float:
    value, observed = _number(
        summary,
        ("benchmark_elapsed_seconds", "latest_cycle_seconds", "cycle_seconds", "elapsed_seconds"),
    )
    if observed and value > 0.0:
        return value
    spans = _runtime_block(summary).get("spans", ())
    if isinstance(spans, Sequence):
        cycles = [
            _nonnegative(item.get("duration_seconds"))
            for item in spans
            if isinstance(item, Mapping) and item.get("phase") == "cycle"
        ]
        if cycles:
            return sum(cycles)
    raise BaselineEvidenceError("summary is missing a positive cycle elapsed time")


def _phase_measurements(
    summaries: Sequence[Mapping[str, Any]], total_cycle_seconds: float
) -> tuple[dict[str, Any], dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for summary in summaries:
        for record in _phase_records(summary):
            grouped[record["phase"]].append(record)

    catalog = list(RUNTIME_PHASES)
    for phase in sorted(grouped):
        if phase not in catalog:
            catalog.append(phase)
    phase_result: dict[str, Any] = {}
    buckets = {kind: 0.0 for kind in TIME_KINDS}
    observed_phase_seconds = 0.0
    for phase in catalog:
        records = grouped.get(phase, [])
        seconds = sum(float(item["duration_seconds"]) for item in records)
        units = sum(float(item["unit_count"]) for item in records)
        kinds = Counter(str(item["time_kind"]) for item in records)
        default_kind = _time_kind(phase)
        kind_seconds = {kind: 0.0 for kind in TIME_KINDS}
        for item in records:
            kind_seconds[str(item["time_kind"])] += float(item["duration_seconds"])
        for kind in TIME_KINDS:
            buckets[kind] += kind_seconds[kind]
        observed_phase_seconds += seconds
        cache_hits = sum(item["cache_hit"] is True for item in records)
        cache_misses = sum(item["cache_hit"] is False for item in records)
        statuses = Counter(str(item["status"]) for item in records)
        phase_result[phase] = {
            "observed": bool(records),
            "span_count": len(records),
            "duration_seconds": round(seconds, 9),
            "mean_seconds": round(seconds / len(records), 9) if records else 0.0,
            "unit_count": round(units, 6),
            "throughput_per_second": round(units / seconds, 9) if seconds else 0.0,
            "primary_time_kind": kinds.most_common(1)[0][0] if kinds else default_kind,
            "time_kind_seconds": {key: round(value, 9) for key, value in kind_seconds.items()},
            "status_counts": dict(sorted(statuses.items())),
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
        }
    breakdown = {
        f"{kind}_seconds": round(value, 9) for kind, value in buckets.items()
    }
    breakdown.update(
        {
            "observed_phase_seconds": round(observed_phase_seconds, 9),
            "unattributed_cycle_seconds": round(
                max(0.0, total_cycle_seconds - observed_phase_seconds), 9
            ),
            "overlap_seconds": round(max(0.0, observed_phase_seconds - total_cycle_seconds), 9),
            "classification_is_exclusive": True,
        }
    )
    return phase_result, breakdown


def _resource_records(summary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    spans = _runtime_block(summary).get("spans", ())
    if isinstance(spans, Sequence):
        for span in spans:
            if not isinstance(span, Mapping):
                continue
            for boundary in ("resources_start", "resources_end"):
                value = span.get(boundary)
                if isinstance(value, Mapping):
                    records.append(value)
    resources = _runtime_block(summary).get("resources")
    if isinstance(resources, Mapping):
        latest = resources.get("latest")
        if isinstance(latest, Mapping):
            records.append(latest)
    for key in ("latest_runtime_resources", "resources", "resource_telemetry"):
        value = summary.get(key)
        if isinstance(value, Mapping):
            latest = value.get("latest")
            records.append(latest if isinstance(latest, Mapping) else value)
    return records


def _resource_measurement(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    records = [record for summary in summaries for record in _resource_records(summary)]

    def values(*keys: str) -> list[float]:
        result: list[float] = []
        for record in records:
            for key in keys:
                number = _finite(record.get(key))
                if number is not None:
                    result.append(number)
                    break
        return result

    def stats(*keys: str) -> dict[str, Any]:
        observed = values(*keys)
        return {
            "observed": bool(observed),
            "sample_count": len(observed),
            "average": round(sum(observed) / len(observed), 6) if observed else 0.0,
            "peak": round(max(observed), 6) if observed else 0.0,
        }

    gpu_known = any(
        item.get("gpu_telemetry_available") is True
        or _finite(item.get("gpu_utilization_percent")) is not None
        for item in records
    )
    return {
        "resource_snapshot_count": len(records),
        "cpu_occupancy_percent": stats("cpu_percent", "cpu_occupancy_percent"),
        "process_cpu_occupancy_percent": stats("process_cpu_percent"),
        "host_memory_used_bytes": stats("memory_used_bytes"),
        "process_memory_used_bytes": stats("process_memory_bytes"),
        "cuda_utilization_percent": stats("gpu_utilization_percent", "cuda_utilization_percent"),
        "cuda_memory_used_bytes": stats("gpu_memory_used_bytes", "cuda_memory_used_bytes"),
        "process_cuda_memory_used_bytes": stats("process_gpu_memory_used_bytes"),
        "unified_memory_used_bytes": stats("unified_memory_used_bytes"),
        "swap_used_bytes": stats("swap_used_bytes"),
        "child_process_count": stats("child_process_count"),
        "cuda_telemetry_available": gpu_known,
    }


def _state_block(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in (
        "latest_autoencoder_state_telemetry",
        "autoencoder_state_telemetry",
        "state_telemetry",
    ):
        value = summary.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _flatten_cardinality(value: Mapping[str, Any], prefix: str = "") -> dict[str, int]:
    result: dict[str, int] = {}
    for key, item in sorted(value.items()):
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            result.update(_flatten_cardinality(item, name))
        elif (
            _finite(item) is not None
            and not isinstance(item, bool)
            and str(key).endswith(("_count", "_entries", "_entry_count", "_scalar_count"))
        ):
            result[name] = _integer(item)
    return result


def _state_measurement(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    blocks = [_state_block(summary) for summary in summaries]
    cardinalities: dict[str, int] = {}
    state_sizes: list[int] = []
    for block in blocks:
        for key, value in _flatten_cardinality(block).items():
            cardinalities[key] = max(cardinalities.get(key, 0), value)
        state_file = block.get("state_file")
        if isinstance(state_file, Mapping) and _finite(state_file.get("size_bytes")) is not None:
            state_sizes.append(_integer(state_file.get("size_bytes")))
        for key in ("state_bytes", "serialized_bytes", "size_bytes"):
            if _finite(block.get(key)) is not None:
                state_sizes.append(_integer(block.get(key)))
                break
    return {
        "observed": bool(any(blocks)),
        "cardinality": dict(sorted(cardinalities.items())),
        "cardinality_field_count": len(cardinalities),
        "state_bytes": max(state_sizes, default=0),
        "state_bytes_observed": bool(state_sizes),
    }


def _io_measurement(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    read_total = write_total = 0
    read_observed = write_observed = False
    for summary in summaries:
        read, has_read = _number(
            summary,
            ("bytes_read", "io_bytes_read", "read_bytes", "disk_read_bytes"),
        )
        written, has_written = _number(
            summary,
            ("bytes_written", "io_bytes_written", "write_bytes", "disk_write_bytes"),
        )
        read_total += int(read)
        write_total += int(written)
        read_observed |= has_read
        write_observed |= has_written
    return {
        "bytes_read": read_total,
        "bytes_written": write_total,
        "bytes_read_observed": read_observed,
        "bytes_written_observed": write_observed,
    }


def _lane_counter(
    summaries: Sequence[Mapping[str, Any]], aliases: Sequence[str]
) -> tuple[int, bool]:
    total = 0
    observed = False
    for summary in summaries:
        value, present = _number(summary, aliases)
        total += int(value)
        observed |= present
    return total, observed


def _lane_seconds(
    summaries: Sequence[Mapping[str, Any]], aliases: Sequence[str], phase: str = ""
) -> tuple[float, bool]:
    total = 0.0
    observed = False
    for summary in summaries:
        value, present = _number(summary, aliases)
        if present:
            total += value
            observed = True
        elif phase:
            matching = [item for item in _phase_records(summary) if item["phase"] == phase]
            if matching:
                total += sum(float(item["duration_seconds"]) for item in matching)
                observed = True
    return round(total, 9), observed


def _lane_measurements(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    lean_startups = _lane_counter(
        summaries, ("leanstral_startup_count", "leanstral_service_startup_count", "model_load_count")
    )
    lean_reuses = _lane_counter(
        summaries, ("leanstral_reuse_count", "leanstral_service_reuse_count", "service_reuse_count")
    )
    lean_requests = _lane_counter(
        summaries, ("leanstral_request_count", "accepted_request_count", "enqueued_count")
    )
    healthy_reuse_count = sum(
        1
        for summary in summaries
        if _first(summary, ("healthy_cuda_service_reused",))[0] is True
    )
    if healthy_reuse_count:
        lean_reuses = (max(lean_reuses[0], healthy_reuse_count), True)
    lean_startup_seconds = _lane_seconds(
        summaries,
        ("leanstral_startup_seconds", "leanstral_service_startup_seconds", "model_load_seconds"),
        "leanstral_startup",
    )
    lean_inference_seconds = _lane_seconds(
        summaries, ("leanstral_inference_seconds",), "leanstral_inference"
    )

    hammer_attempts = _lane_counter(
        summaries,
        ("hammer_attempt_count", "hammer_artifact_count", "proof_attempted_count", "obligation_count"),
    )
    hammer_proved = _lane_counter(
        summaries, ("hammer_proved_count", "proof_valid_count", "proved_count")
    )
    hammer_reconstructed = _lane_counter(
        summaries,
        ("hammer_reconstruction_success_count", "reconstruction_success_count"),
    )
    hammer_seconds = _lane_seconds(
        summaries, ("hammer_work_seconds", "hammer_seconds"), "solver_execution"
    )

    codex_attempts = _lane_counter(
        summaries,
        ("codex_attempt_count", "program_synthesis_claimed_count", "codex_claimed_count"),
    )
    validation_attempts = _lane_counter(
        summaries,
        ("validation_attempt_count", "program_synthesis_completed_count", "validation_count"),
    )
    validation_passed = _lane_counter(
        summaries,
        ("validation_passed_count", "passed_validation_count", "successful_validation_count"),
    )
    validation_failed = _lane_counter(
        summaries, ("failed_validation_count", "validation_failed_count")
    )
    accepted = _lane_counter(
        summaries,
        ("accepted_patch_count", "codex_accepted_patch_count", "codex_main_apply_count"),
    )

    def aggregate_counts(keys: Sequence[str]) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for summary in summaries:
            value, observed = _first(summary, keys)
            if observed and isinstance(value, Mapping):
                for name, count in value.items():
                    counts[str(name)] += _integer(count)
        return dict(sorted(counts.items()))

    validation_span_statuses: Counter[str] = Counter()
    for summary in summaries:
        for record in _phase_records(summary):
            if record["phase"] == "validation":
                validation_span_statuses[str(record["status"])] += 1
    validation_outcome_counts = aggregate_counts(
        ("validation_outcome_counts", "program_synthesis_validation_outcome_counts")
    )
    validation_outcome_counts.setdefault("passed", validation_passed[0])
    validation_outcome_counts.setdefault("failed", validation_failed[0])
    return {
        "leanstral": {
            "startup_count": lean_startups[0],
            "startup_count_observed": lean_startups[1],
            "startup_seconds": lean_startup_seconds[0],
            "startup_seconds_observed": lean_startup_seconds[1],
            "reuse_count": lean_reuses[0],
            "reuse_count_observed": lean_reuses[1],
            "request_count": lean_requests[0],
            "request_count_observed": lean_requests[1],
            "inference_seconds": lean_inference_seconds[0],
            "inference_seconds_observed": lean_inference_seconds[1],
            "healthy_cuda_service_reused": healthy_reuse_count > 0,
        },
        "hammer": {
            "attempt_count": hammer_attempts[0],
            "attempt_count_observed": hammer_attempts[1],
            "proved_count": hammer_proved[0],
            "proved_count_observed": hammer_proved[1],
            "reconstructed_count": hammer_reconstructed[0],
            "reconstructed_count_observed": hammer_reconstructed[1],
            "work_seconds": hammer_seconds[0],
            "work_seconds_observed": hammer_seconds[1],
        },
        "codex": {
            "attempt_count": codex_attempts[0],
            "attempt_count_observed": codex_attempts[1],
            "validation_attempt_count": validation_attempts[0],
            "validation_attempt_count_observed": validation_attempts[1],
            "validation_passed_count": validation_passed[0],
            "validation_passed_count_observed": validation_passed[1],
            "validation_failed_count": validation_failed[0],
            "validation_failed_count_observed": validation_failed[1],
            "validation_outcomes": {
                "outcome_counts": validation_outcome_counts,
                "span_status_counts": dict(sorted(validation_span_statuses.items())),
                "failure_kind_counts": aggregate_counts(
                    (
                        "program_synthesis_failed_validation_kind_counts",
                        "failed_validation_kind_counts",
                    )
                ),
                "failure_reason_counts": aggregate_counts(
                    (
                        "program_synthesis_failed_validation_reason_counts",
                        "failed_validation_reason_counts",
                    )
                ),
            },
            "accepted_patch_count": accepted[0],
            "accepted_patch_count_observed": accepted[1],
        },
    }


def _family_name(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    normalized = _FAMILY_ALIASES.get(normalized, normalized)
    try:
        return canonical_legal_ir_evaluation_family(normalized)
    except ValueError:
        return ""


def _family_payloads(summary: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    result: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    container_keys = {
        "view_family_metrics",
        "legal_ir_view_family_metrics",
        "semantic_equivalence_by_family",
        "semantic_family_metrics",
        "family_metrics",
    }
    for block in _nested_mappings(summary):
        for key in container_keys:
            nested = block.get(key)
            if not isinstance(nested, Mapping):
                continue
            for raw_family, payload in nested.items():
                family = _family_name(raw_family)
                if family and isinstance(payload, Mapping):
                    result[family].append(payload)
        # Accept a direct ``families: {family: metrics}`` benchmark block.
        nested = block.get("families")
        if isinstance(nested, Mapping):
            for raw_family, payload in nested.items():
                family = _family_name(raw_family)
                if family and isinstance(payload, Mapping):
                    result[family].append(payload)
    return result


_GUARDRAIL_ALIASES: Final[Mapping[str, tuple[str, ...]]] = {
    "cross_entropy_loss": (
        "ir_cross_entropy_loss",
        "compiler_ir_cross_entropy_loss",
        "autoencoder_cross_entropy_loss",
        "cross_entropy_loss",
        "ce",
    ),
    "cosine_similarity": (
        "ir_cosine_similarity",
        "compiler_ir_cosine_similarity",
        "autoencoder_cosine_similarity",
        "cosine_similarity",
        "cosine",
    ),
    "proof_validity": (
        "hammer_proof_success_rate",
        "proof_validity",
        "proof_validity_rate",
        "proof_success_rate",
    ),
    "round_trip": (
        "round_trip_reconstruction_success_rate",
        "reconstruction_success_rate",
        "decompiler_round_trip_preservation",
        "round_trip_success_rate",
        "round_trip",
    ),
    "source_copy": (
        "source_copy_penalty",
        "source_copy_reward_hack_penalty",
        "source_span_copy_ratio",
        "source_copy_ratio",
        "source_copy",
    ),
}
_SEMANTIC_KEYS: Final = (
    "structural_equivalence",
    "obligation_equivalence",
    "counterexample_equivalence",
    "graph_isomorphism",
    "temporal_window_agreement",
    "decompiler_round_trip_preservation",
    "proof_obligation_delta_score",
    "semantic_equivalence_score",
    "semantic_equivalence",
)


def _metric_from_payloads(
    payloads: Sequence[Mapping[str, Any]], aliases: Sequence[str]
) -> tuple[float, bool]:
    for payload in reversed(payloads):
        for block in _nested_mappings(payload, max_depth=3):
            for key in aliases:
                number = _finite(block.get(key))
                if number is not None:
                    return number, True
    return 0.0, False


def _metric_values_from_payloads(
    payloads: Sequence[Mapping[str, Any]], aliases: Sequence[str]
) -> list[float]:
    values: list[float] = []
    for payload in payloads:
        value, observed = _metric_from_payloads((payload,), aliases)
        if observed:
            values.append(value)
    return values


def _family_guardrails(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    collected: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for summary in summaries:
        for family, payloads in _family_payloads(summary).items():
            collected[family].extend(payloads)

    result: dict[str, Any] = {}
    for family in LEGAL_IR_EVALUATION_FAMILIES:
        payloads = collected.get(family, [])
        metrics: dict[str, Any] = {}
        for name, aliases in _GUARDRAIL_ALIASES.items():
            components: dict[str, float] = {}
            for alias in aliases:
                values = _metric_values_from_payloads(payloads, (alias,))
                if values:
                    components[alias] = round(
                        max(values)
                        if name in {"cross_entropy_loss", "source_copy"}
                        else min(values),
                        12,
                    )
            component_values = list(components.values())
            # Preserve the least-favourable observation when deterministic and
            # learned variants coexist.  The components retain both lineages.
            value = 0.0
            if component_values:
                value = (
                    max(component_values)
                    if name in {"cross_entropy_loss", "source_copy"}
                    else min(component_values)
                )
            metrics[name] = {
                "value": round(value, 12),
                "observed": bool(component_values),
                "components": dict(sorted(components.items())),
            }

        semantic_values: dict[str, float] = {}
        for key in _SEMANTIC_KEYS:
            values = _metric_values_from_payloads(payloads, (key,))
            if values:
                semantic_values[key] = round(min(values), 12)
        semantic_score = 0.0
        if semantic_values:
            explicit = semantic_values.get("semantic_equivalence_score")
            if explicit is None:
                explicit = semantic_values.get("semantic_equivalence")
            semantic_score = (
                explicit
                if explicit is not None
                else min(semantic_values.values())
            )
        metrics["semantic_equivalence"] = {
            "value": round(semantic_score, 12),
            "observed": bool(semantic_values),
            "components": dict(sorted(semantic_values.items())),
        }
        missing = [name for name in GUARDRAIL_NAMES if not metrics[name]["observed"]]
        sample_count, sample_observed = _metric_from_payloads(
            payloads, ("sample_count", "artifact_count", "evaluated_count")
        )
        result[family] = {
            "sample_count": int(sample_count),
            "sample_count_observed": sample_observed,
            "metrics": metrics,
            "complete": not missing,
            "missing_guardrails": missing,
        }
    return result


def _completeness(
    *,
    phases: Mapping[str, Any],
    resources: Mapping[str, Any],
    state: Mapping[str, Any],
    io: Mapping[str, Any],
    lanes: Mapping[str, Any],
    families: Mapping[str, Any],
) -> dict[str, Any]:
    missing: list[str] = []
    if not any(bool(value.get("observed")) for value in phases.values() if isinstance(value, Mapping)):
        missing.append("cycle_phases")
    for key in (
        "cpu_occupancy_percent",
        "cuda_utilization_percent",
        "cuda_memory_used_bytes",
    ):
        if not bool(resources.get(key, {}).get("observed")):
            missing.append(f"resources.{key}")
    if not state.get("observed") or not state.get("cardinality"):
        missing.append("state.cardinality")
    if not state.get("state_bytes_observed"):
        missing.append("state.state_bytes")
    if not io.get("bytes_read_observed"):
        missing.append("io.bytes_read")
    if not io.get("bytes_written_observed"):
        missing.append("io.bytes_written")
    for lane, required in {
        "leanstral": ("startup_count", "startup_seconds", "reuse_count", "request_count"),
        "hammer": ("attempt_count", "proved_count", "reconstructed_count", "work_seconds"),
        "codex": (
            "attempt_count",
            "validation_attempt_count",
            "validation_passed_count",
            "validation_failed_count",
            "accepted_patch_count",
        ),
    }.items():
        block = lanes[lane]
        for key in required:
            if not block.get(f"{key}_observed"):
                missing.append(f"lanes.{lane}.{key}")
    for family, block in families.items():
        for name in block.get("missing_guardrails", ()):
            missing.append(f"families.{family}.{name}")
    return {"complete": not missing, "missing_measurements": sorted(missing)}


@dataclass(frozen=True, slots=True)
class CycleThroughputBaseline:
    """One deeply immutable cold or warm aggregate."""

    _document: Mapping[str, Any]

    def __post_init__(self) -> None:
        document = _thaw(self._document)
        supplied = str(document.pop("evidence_digest", "") or "")
        expected = content_digest(document)
        if supplied and supplied != expected:
            raise BaselineEvidenceError("cycle baseline evidence digest does not match its body")
        document["evidence_digest"] = expected
        object.__setattr__(self, "_document", _deep_freeze(document))

    @property
    def cache_state(self) -> str:
        return str(self._document["cache_state"])

    @property
    def evidence_digest(self) -> str:
        return str(self._document["evidence_digest"])

    @property
    def canonical_sample_digest(self) -> str:
        return str(self._document["canonical_sample"]["sample_digest"])

    @property
    def measurements(self) -> Mapping[str, Any]:
        return self._document["measurements"]

    @property
    def complete(self) -> bool:
        return bool(self._document["completeness"]["complete"])

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self._document)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CycleThroughputBaseline":
        return cls(value)


@dataclass(frozen=True, slots=True)
class MatchedCycleThroughputBaseline:
    """Content-addressed matched cold/warm cycle evidence."""

    cold: CycleThroughputBaseline
    warm: CycleThroughputBaseline
    _document: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.cold.cache_state != "cold" or self.warm.cache_state != "warm":
            raise BaselineEvidenceError("matched baseline requires cold then warm evidence")
        if self.cold.canonical_sample_digest != self.warm.canonical_sample_digest:
            raise BaselineEvidenceError("cold and warm baselines replay different canonical samples")
        document = _thaw(self._document)
        supplied = str(document.pop("evidence_digest", "") or "")
        expected = content_digest(document)
        if supplied and supplied != expected:
            raise BaselineEvidenceError("matched baseline evidence digest does not match its body")
        document["evidence_digest"] = expected
        object.__setattr__(self, "_document", _deep_freeze(document))

    @property
    def evidence_digest(self) -> str:
        return str(self._document["evidence_digest"])

    @property
    def complete(self) -> bool:
        return self.cold.complete and self.warm.complete

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self._document)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MatchedCycleThroughputBaseline":
        cold = CycleThroughputBaseline.from_dict(value["cold"])
        warm = CycleThroughputBaseline.from_dict(value["warm"])
        return cls(cold=cold, warm=warm, _document=value)


def build_cycle_throughput_baseline(
    summaries: Sequence[Mapping[str, Any]],
    *,
    cache_state: str,
    expected_sample_ids: Optional[Sequence[str]] = None,
    strict: bool = True,
) -> CycleThroughputBaseline:
    """Aggregate repeated observations for one cache state.

    ``strict=False`` is intended only for diagnosing legacy telemetry.  Such a
    document is still content addressed, but its completeness block prevents it
    from being mistaken for promotion-grade baseline evidence.
    """

    state_name = str(cache_state).strip().lower()
    if state_name not in {"cold", "warm"}:
        raise BaselineEvidenceError("cache_state must be cold or warm")
    if not summaries:
        raise BaselineEvidenceError("at least one cycle summary is required")
    expected = tuple(str(item).strip() for item in expected_sample_ids or _sample_ids(summaries[0]))
    if not expected:
        raise BaselineEvidenceError("canonical sample may not be empty")
    for index, summary in enumerate(summaries):
        declared = str(summary.get("benchmark_cache_state") or summary.get("cache_state") or "")
        if declared and declared.lower() != state_name:
            raise BaselineEvidenceError(
                f"summary {index} declares cache state {declared!r}, expected {state_name!r}"
            )
        observed = _sample_ids(summary)
        if observed != expected:
            raise BaselineEvidenceError(
                f"summary {index} does not replay the ordered canonical sample"
            )

    elapsed_values = [_elapsed(summary) for summary in summaries]
    total_elapsed = sum(elapsed_values)
    sample_count = len(expected) * len(summaries)
    phases, time_breakdown = _phase_measurements(summaries, total_elapsed)
    resources = _resource_measurement(summaries)
    state = _state_measurement(summaries)
    io = _io_measurement(summaries)
    lanes = _lane_measurements(summaries)
    families = _family_guardrails(summaries)
    completeness = _completeness(
        phases=phases,
        resources=resources,
        state=state,
        io=io,
        lanes=lanes,
        families=families,
    )
    if strict and not completeness["complete"]:
        raise BaselineEvidenceError(
            "baseline evidence is incomplete: "
            + ", ".join(completeness["missing_measurements"])
        )

    document: dict[str, Any] = {
        "schema_version": CYCLE_THROUGHPUT_BASELINE_SCHEMA_VERSION,
        "cache_state": state_name,
        "canonical_sample": canonical_sample_manifest(expected),
        "observation_count": len(summaries),
        "source_evidence_digests": [
            content_digest(_normalized_source(summary)) for summary in summaries
        ],
        "measurements": {
            "cycle": {
                "cycle_count": len(summaries),
                "total_seconds": round(total_elapsed, 9),
                "mean_seconds": round(total_elapsed / len(summaries), 9),
                "minimum_seconds": round(min(elapsed_values), 9),
                "maximum_seconds": round(max(elapsed_values), 9),
                "sample_count": sample_count,
                "samples_per_second": round(sample_count / total_elapsed, 12),
                "samples_per_hour": round(sample_count / total_elapsed * 3600.0, 9),
            },
            "phases": phases,
            "time_breakdown": time_breakdown,
            "resources": resources,
            "state": state,
            "io": io,
            "lanes": lanes,
            "family_guardrails": families,
        },
        "completeness": completeness,
        "training_behavior": {
            "mode": "offline_summary_reduction",
            "trainer_invoked": False,
            "random_state_consumed": False,
            "state_mutated": False,
        },
    }
    document["evidence_digest"] = content_digest(document)
    return CycleThroughputBaseline(document)


freeze_cycle_throughput_baseline = build_cycle_throughput_baseline


def build_matched_cycle_throughput_baseline(
    cold_summaries: Sequence[Mapping[str, Any]],
    warm_summaries: Sequence[Mapping[str, Any]],
    *,
    expected_sample_ids: Optional[Sequence[str]] = None,
    strict: bool = True,
    dry_run: bool = False,
) -> MatchedCycleThroughputBaseline:
    """Build and verify a matched content-addressed cold/warm baseline pair."""

    if not cold_summaries or not warm_summaries:
        raise BaselineEvidenceError(
            "matched baseline requires at least one cold and one warm summary"
        )
    expected = tuple(expected_sample_ids or _sample_ids(cold_summaries[0]))
    cold = build_cycle_throughput_baseline(
        cold_summaries,
        cache_state="cold",
        expected_sample_ids=expected,
        strict=strict,
    )
    warm = build_cycle_throughput_baseline(
        warm_summaries,
        cache_state="warm",
        expected_sample_ids=expected,
        strict=strict,
    )
    cold_cycle = cold.measurements["cycle"]
    warm_cycle = warm.measurements["cycle"]
    cold_rate = float(cold_cycle["samples_per_second"])
    warm_rate = float(warm_cycle["samples_per_second"])
    cold_seconds = float(cold_cycle["mean_seconds"])
    warm_seconds = float(warm_cycle["mean_seconds"])
    document: dict[str, Any] = {
        "schema_version": CYCLE_THROUGHPUT_BASELINE_SCHEMA_VERSION,
        "benchmark_kind": "matched_cold_warm_modal_autoencoder_cycle",
        "dry_run": bool(dry_run),
        "canonical_sample_digest": cold.canonical_sample_digest,
        "cold": cold.to_dict(),
        "warm": warm.to_dict(),
        "comparison": {
            "throughput_ratio_warm_over_cold": round(warm_rate / cold_rate, 12)
            if cold_rate
            else 0.0,
            "cycle_seconds_saved_warm": round(cold_seconds - warm_seconds, 9),
            "cycle_speedup_ratio": round(cold_seconds / warm_seconds, 12)
            if warm_seconds
            else 0.0,
        },
        "complete": cold.complete and warm.complete,
    }
    document["evidence_digest"] = content_digest(document)
    return MatchedCycleThroughputBaseline(cold=cold, warm=warm, _document=document)


freeze_matched_cycle_baseline = build_matched_cycle_throughput_baseline
aggregate_cycle_summaries = build_cycle_throughput_baseline
build_matched_cycle_baseline = build_matched_cycle_throughput_baseline
CycleBaseline = CycleThroughputBaseline
MatchedCycleBaseline = MatchedCycleThroughputBaseline


def _write_immutable(path: Path, payload: str) -> Path:
    """Atomically install ``payload`` once; an existing mismatch is an error."""

    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload.encode("utf-8")
    if path.exists():
        if path.read_bytes() != data:
            raise BaselineEvidenceError(f"immutable artifact already exists with different bytes: {path}")
        return path
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise BaselineEvidenceError(
                    f"immutable artifact race installed different bytes: {path}"
                )
        return path
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_content_addressed_baselines(
    baseline: MatchedCycleThroughputBaseline,
    output_directory: str | Path,
) -> dict[str, Path]:
    """Write digest-named cold, warm, and matched immutable JSON artifacts."""

    directory = Path(output_directory)
    artifacts = {
        "cold": baseline.cold,
        "warm": baseline.warm,
        "matched": baseline,
    }
    result: dict[str, Path] = {}
    for name, artifact in artifacts.items():
        path = directory / f"{name}-{artifact.evidence_digest}.json"
        result[name] = _write_immutable(path, canonical_json(artifact.to_dict()) + "\n")
    return result


def write_immutable_baseline_document(
    document: Mapping[str, Any], path: str | Path
) -> Path:
    """Atomically write a canonical baseline document without overwriting it."""

    return _write_immutable(Path(path), canonical_json(document) + "\n")


write_baseline_artifacts = write_content_addressed_baselines


__all__ = [
    "BaselineEvidenceError",
    "CANONICAL_SAMPLE_SCHEMA_VERSION",
    "CYCLE_THROUGHPUT_BASELINE_SCHEMA_VERSION",
    "CYCLE_THROUGHPUT_BENCHMARK_SCHEMA_VERSION",
    "CycleThroughputBaseline",
    "CycleBaseline",
    "GUARDRAIL_NAMES",
    "MatchedCycleThroughputBaseline",
    "MatchedCycleBaseline",
    "TIME_KINDS",
    "aggregate_cycle_summaries",
    "build_cycle_throughput_baseline",
    "build_matched_cycle_baseline",
    "build_matched_cycle_throughput_baseline",
    "canonical_digest",
    "canonical_json",
    "canonical_sample_manifest",
    "content_digest",
    "freeze_cycle_throughput_baseline",
    "freeze_matched_cycle_baseline",
    "write_baseline_artifacts",
    "write_content_addressed_baselines",
    "write_immutable_baseline_document",
]
