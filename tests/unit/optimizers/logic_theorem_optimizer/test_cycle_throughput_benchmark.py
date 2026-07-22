from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cycle_throughput_benchmark import (
    BaselineEvidenceError,
    CycleThroughputBaseline,
    build_cycle_throughput_baseline,
    build_matched_cycle_throughput_baseline,
    canonical_sample_manifest,
    content_digest,
    write_content_addressed_baselines,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_family_evaluator import (
    LEGAL_IR_EVALUATION_FAMILIES,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.runtime_telemetry import (
    RUNTIME_PHASES,
)


SAMPLE_IDS = ("canonical-a", "canonical-b", "canonical-c")


def _summary(cache_state: str, *, volatile_suffix: str = "one") -> dict:
    resource = {
        "cpu_percent": 25.0,
        "process_cpu_percent": 12.5,
        "memory_used_bytes": 1000,
        "process_memory_bytes": 100,
        "swap_used_bytes": 0,
        "gpu_utilization_percent": 70.0,
        "gpu_memory_used_bytes": 800,
        "process_gpu_memory_used_bytes": 500,
        "unified_memory_used_bytes": 1800,
        "child_process_count": 2,
        "gpu_telemetry_available": True,
    }
    spans = [
        {
            "span_id": f"span-{volatile_suffix}-{index}",
            "started_at": f"2026-01-01T00:00:{index:02d}Z",
            "phase": phase,
            "duration_seconds": float(index + 1),
            "unit_count": 3,
            "status": "ok",
            "resources_start": resource,
            "resources_end": resource,
        }
        for index, phase in enumerate(RUNTIME_PHASES)
    ]
    spans.append(
        {
            "span_id": f"serialization-{volatile_suffix}",
            "phase": "state_serialization",
            "duration_seconds": 2.5,
            "unit_count": 1,
            "status": "ok",
            "resources_start": resource,
            "resources_end": resource,
        }
    )
    family_metrics = {
        family: {
            "sample_count": 3,
            "ir_cross_entropy_loss": 0.2,
            "ir_cosine_similarity": 0.9,
            "hammer_proof_success_rate": 1.0,
            "reconstruction_success_rate": 1.0,
            "source_copy_penalty": 0.0,
            "semantic_equivalence": {
                "structural_equivalence": 1.0,
                "obligation_equivalence": 1.0,
                "counterexample_equivalence": 1.0,
                "graph_isomorphism": 1.0,
                "temporal_window_agreement": 1.0,
                "decompiler_round_trip_preservation": 1.0,
                "proof_obligation_delta_score": 1.0,
            },
        }
        for family in LEGAL_IR_EVALUATION_FAMILIES
    }
    return {
        "benchmark_cache_state": cache_state,
        "benchmark_sample_ids": list(SAMPLE_IDS),
        "latest_cycle_seconds": 500.0 if cache_state == "cold" else 250.0,
        "runtime_telemetry": {"spans": spans, "resources": {"latest": resource}},
        "latest_autoencoder_state_telemetry": {
            "vector_entry_count": 11,
            "vector_scalar_count": 101,
            "nested_logit_entry_counts": {"head": 7},
            "state_file": {"size_bytes": 12345},
        },
        "io_telemetry": {"bytes_read": 400, "bytes_written": 800},
        "leanstral": {
            "leanstral_startup_count": 1 if cache_state == "cold" else 0,
            "leanstral_startup_seconds": 10.0 if cache_state == "cold" else 0.0,
            "leanstral_reuse_count": 0 if cache_state == "cold" else 1,
            "leanstral_request_count": 2,
            "healthy_cuda_service_reused": cache_state == "warm",
        },
        "hammer": {
            "hammer_attempt_count": 9,
            "hammer_proved_count": 8,
            "hammer_reconstruction_success_count": 7,
            "hammer_work_seconds": 6.0,
        },
        "codex": {
            "codex_attempt_count": 4,
            "validation_attempt_count": 4,
            "validation_passed_count": 3,
            "failed_validation_count": 1,
            "accepted_patch_count": 2,
        },
        "legal_ir_view_family_metrics": family_metrics,
    }


def test_freezes_complete_matched_cold_and_warm_cycle_evidence() -> None:
    baseline = build_matched_cycle_throughput_baseline(
        [_summary("cold")],
        [_summary("warm")],
    )
    document = baseline.to_dict()

    assert baseline.complete is True
    assert document["cold"]["completeness"] == {
        "complete": True,
        "missing_measurements": [],
    }
    assert document["warm"]["measurements"]["cycle"]["samples_per_second"] == pytest.approx(
        3 / 250
    )
    assert document["comparison"]["cycle_speedup_ratio"] == 2.0
    assert document["cold"]["measurements"]["resources"]["cuda_telemetry_available"] is True
    assert document["cold"]["measurements"]["state"]["cardinality"][
        "vector_scalar_count"
    ] == 101
    assert document["cold"]["measurements"]["io"]["bytes_written"] == 800
    assert document["warm"]["measurements"]["lanes"]["leanstral"]["reuse_count"] == 1
    assert document["cold"]["measurements"]["lanes"]["hammer"]["attempt_count"] == 9
    assert document["cold"]["measurements"]["lanes"]["codex"][
        "accepted_patch_count"
    ] == 2
    assert set(document["cold"]["measurements"]["family_guardrails"]) == set(
        LEGAL_IR_EVALUATION_FAMILIES
    )
    assert all(
        family["complete"]
        for family in document["cold"]["measurements"]["family_guardrails"].values()
    )


def test_phase_accounting_distinguishes_all_time_kinds() -> None:
    document = build_cycle_throughput_baseline(
        [_summary("cold")], cache_state="cold"
    ).to_dict()
    phases = document["measurements"]["phases"]
    breakdown = document["measurements"]["time_breakdown"]

    assert phases["projection_training"]["primary_time_kind"] == "useful_compute"
    assert phases["leanstral_queue"]["primary_time_kind"] == "wait"
    assert phases["state_serialization"]["primary_time_kind"] == "serialization"
    assert phases["state_persistence"]["primary_time_kind"] == "persistence"
    assert phases["solver_execution"]["primary_time_kind"] == "child_process"
    assert breakdown["classification_is_exclusive"] is True
    assert all(breakdown[f"{kind}_seconds"] > 0 for kind in (
        "useful_compute", "wait", "serialization", "persistence", "child_process"
    ))


def test_cold_and_warm_must_replay_same_ordered_canonical_sample() -> None:
    warm = _summary("warm")
    warm["benchmark_sample_ids"] = list(reversed(SAMPLE_IDS))

    with pytest.raises(BaselineEvidenceError, match="ordered canonical sample"):
        build_matched_cycle_throughput_baseline([_summary("cold")], [warm])


def test_sample_manifest_is_source_free_and_order_sensitive() -> None:
    manifest = canonical_sample_manifest(SAMPLE_IDS)

    assert not any(sample_id in json.dumps(manifest) for sample_id in SAMPLE_IDS)
    assert manifest["sample_digest"] != canonical_sample_manifest(tuple(reversed(SAMPLE_IDS)))[
        "sample_digest"
    ]


def test_missing_evidence_fails_closed_but_can_be_diagnosed() -> None:
    summary = _summary("cold")
    summary.pop("io_telemetry")

    with pytest.raises(BaselineEvidenceError, match=r"io\.bytes_read"):
        build_cycle_throughput_baseline([summary], cache_state="cold")

    diagnostic = build_cycle_throughput_baseline(
        [summary], cache_state="cold", strict=False
    )
    assert diagnostic.complete is False
    assert "io.bytes_written" in diagnostic.to_dict()["completeness"]["missing_measurements"]


def test_digest_is_stable_across_telemetry_ids_and_timestamps_and_detects_tampering() -> None:
    first = build_cycle_throughput_baseline(
        [_summary("cold", volatile_suffix="first")], cache_state="cold"
    )
    second = build_cycle_throughput_baseline(
        [_summary("cold", volatile_suffix="second")], cache_state="cold"
    )

    assert first.evidence_digest == second.evidence_digest
    assert content_digest(
        {key: value for key, value in first.to_dict().items() if key != "evidence_digest"}
    ) == first.evidence_digest

    tampered = first.to_dict()
    tampered["measurements"]["cycle"]["mean_seconds"] = 1.0
    with pytest.raises(BaselineEvidenceError, match="digest"):
        CycleThroughputBaseline.from_dict(tampered)


def test_artifacts_are_immutable_content_addressed_and_idempotent(tmp_path: Path) -> None:
    baseline = build_matched_cycle_throughput_baseline(
        [_summary("cold")], [_summary("warm")]
    )

    first = write_content_addressed_baselines(baseline, tmp_path)
    second = write_content_addressed_baselines(baseline, tmp_path)

    assert first == second
    assert set(first) == {"cold", "warm", "matched"}
    assert baseline.cold.evidence_digest in first["cold"].name
    assert json.loads(first["matched"].read_text(encoding="utf-8"))[
        "evidence_digest"
    ] == baseline.evidence_digest

