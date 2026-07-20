"""End-to-end contracts for source-free runtime phase/resource telemetry."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.runtime_telemetry import (
    LEGAL_IR_VIEW_PHASES,
    REQUIRED_RUNTIME_PHASES,
    RUNTIME_PHASES,
    RUNTIME_RESOURCE_TELEMETRY_SCHEMA_VERSION,
    RUNTIME_TELEMETRY_SCHEMA_VERSION,
    ResourceSnapshot,
    RuntimeTelemetry,
    attach_runtime_telemetry,
    canonical_runtime_phase,
    sanitize_telemetry_attributes,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    uscode_modal_daemon_runner as daemon_runner,
)


RAW_LEGAL_TEXT = "The agency shall not disclose the confidential statutory record."


def _resource(queue_depth: int = 0) -> ResourceSnapshot:
    return ResourceSnapshot(
        captured_at="2026-01-01T00:00:00+00:00",
        cpu_percent=51.0,
        process_cpu_percent=12.0,
        memory_used_bytes=1024,
        memory_percent=44.0,
        process_memory_bytes=512,
        swap_used_bytes=128,
        swap_percent=2.0,
        gpu_utilization_percent=33.0,
        gpu_memory_used_bytes=256,
        gpu_memory_percent=25.0,
        gpu_device_count=1,
        child_process_count=3,
        queue_depth=queue_depth,
    )


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        self.value += 0.25
        return self.value


def _telemetry(run_id: str = "runtime-test") -> RuntimeTelemetry:
    return RuntimeTelemetry(
        run_id,
        resource_sampler=lambda queue_depth=0: _resource(queue_depth),
        clock=_Clock(),
    )


def test_phase_catalog_covers_every_required_runtime_lane() -> None:
    expected = {
        "sampling",
        "compilation",
        "decoding",
        "embeddings",
        "projection_training",
        "bridge_evaluation",
        "premise_selection",
        "solver_execution",
        "lean_reconstruction",
        "leanstral_queue",
        "leanstral_inference",
        "disagreement_export",
        "codex_queue_wait",
        "validation",
        "merge",
        "cache_lookup",
        "state_persistence",
    }
    assert expected <= set(RUNTIME_PHASES)
    assert set(LEGAL_IR_VIEW_PHASES) <= set(RUNTIME_PHASES)
    assert REQUIRED_RUNTIME_PHASES == frozenset(RUNTIME_PHASES)
    assert canonical_runtime_phase("compiler_ir_train") == "compilation"
    assert canonical_runtime_phase("queue_merge") == "merge"
    assert canonical_runtime_phase("state_save") == "state_persistence"


def test_cycle_and_sample_spans_record_resources_throughput_and_cache_rates() -> None:
    telemetry = _telemetry()
    telemetry.start_cycle(7, queue_depth=9)
    telemetry.transition_cycle_phase(
        "sampling",
        cycle=7,
        queue_depth=9,
        attributes={"sample_count": 2},
    )
    with telemetry.span(
        "compilation",
        cycle=7,
        sample_id="sample-7",
        unit_count=2,
        queue_depth=8,
    ):
        pass
    telemetry.record_cache_lookup(
        hit=True,
        cycle=7,
        sample_id="sample-7",
        cache_kind="compiler_ir_metric_sample",
        queue_depth=8,
    )
    telemetry.record_cache_lookup(
        hit=False,
        cycle=7,
        sample_id="sample-8",
        cache_kind="compiler_ir_metric_sample",
        queue_depth=7,
    )
    telemetry.end_cycle(queue_depth=7)

    block = telemetry.to_dict()
    compilation = next(span for span in block["spans"] if span["phase"] == "compilation")
    assert block["schema_version"] == RUNTIME_TELEMETRY_SCHEMA_VERSION
    assert block["resource_schema_version"] == RUNTIME_RESOURCE_TELEMETRY_SCHEMA_VERSION
    assert compilation["scope"] == "sample"
    assert compilation["sample_id"] == "sample-7"
    assert compilation["duration_seconds"] == pytest.approx(0.25)
    assert compilation["throughput_per_second"] == pytest.approx(8.0)
    assert compilation["resources_start"]["child_process_count"] == 3
    assert compilation["resources_end"]["gpu_utilization_percent"] == 33.0
    assert block["resources"]["cpu_percent_peak"] == 51.0
    assert block["resources"]["memory_used_bytes_peak"] == 1024.0
    assert block["resources"]["swap_used_bytes_peak"] == 128.0
    assert block["resources"]["gpu_utilization_percent_peak"] == 33.0
    assert block["resources"]["child_process_count_peak"] == 3.0
    assert block["resources"]["queue_depth_peak"] == 9.0
    assert block["cache_hits"] == 1
    assert block["cache_misses"] == 1
    assert block["cache_hit_rate"] == 0.5


def test_progress_callbacks_create_per_sample_compiler_view_and_bridge_spans() -> None:
    telemetry = _telemetry()
    telemetry.start_cycle(1)
    telemetry.observe_progress(
        {"block": "compiler_ir", "stage": "sample_start", "sample_id": "sample-a"},
        cycle=1,
        dataset="train",
    )
    telemetry.observe_progress(
        {
            "block": "compiler_ir",
            "stage": "sample_cache_miss",
            "sample_id": "sample-a",
        },
        cycle=1,
        dataset="train",
    )
    telemetry.observe_progress(
        {
            "block": "compiler_ir",
            "stage": "sample_done",
            "sample_id": "sample-a",
            "formula_count": 2,
        },
        cycle=1,
        dataset="train",
    )
    telemetry.observe_progress(
        {"block": "bridge_ir", "stage": "sample_start", "sample_id": "sample-a"},
        cycle=1,
        dataset="validation",
    )
    telemetry.observe_progress(
        {"block": "bridge_ir", "stage": "sample_done", "sample_id": "sample-a"},
        cycle=1,
        dataset="validation",
    )
    telemetry.end_cycle()

    sample_phases = {
        span["phase"]
        for span in telemetry.to_dict()["spans"]
        if span["sample_id"] == "sample-a"
    }
    assert {
        "compilation",
        "decoding",
        "embeddings",
        "bridge_evaluation",
        "cache_lookup",
        *LEGAL_IR_VIEW_PHASES,
    } <= sample_phases


def test_telemetry_attribute_boundary_never_serializes_raw_legal_text() -> None:
    telemetry = _telemetry()
    telemetry.start_cycle(2)
    with telemetry.span(
        "validation",
        cycle=2,
        sample_id="safe-sample-id",
        attributes={
            "raw_text": RAW_LEGAL_TEXT,
            "source_text_preview": RAW_LEGAL_TEXT,
            "prompt": RAW_LEGAL_TEXT,
            "reason": RAW_LEGAL_TEXT,
            "status": "passed",
            "sample_count": 1,
        },
    ):
        pass
    telemetry.end_cycle()
    serialized = json.dumps(telemetry.to_dict(), sort_keys=True)

    assert RAW_LEGAL_TEXT not in serialized
    assert "source_text_preview" not in serialized
    assert "raw_text" not in serialized
    assert "prompt" not in serialized
    assert '"status": "passed"' in serialized
    assert sanitize_telemetry_attributes({"text": RAW_LEGAL_TEXT}) == {}


def test_summary_attachment_exposes_versioned_headline_metrics() -> None:
    telemetry = _telemetry("summary-run")
    telemetry.start_cycle(3)
    telemetry.transition_cycle_phase("projection_training", cycle=3)
    telemetry.end_cycle()
    summary: dict[str, object] = {}

    block = attach_runtime_telemetry(summary, telemetry, cycle=3)

    assert summary["runtime_telemetry_schema_version"] == RUNTIME_TELEMETRY_SCHEMA_VERSION
    assert summary["runtime_resource_telemetry_schema_version"] == (
        RUNTIME_RESOURCE_TELEMETRY_SCHEMA_VERSION
    )
    assert summary["runtime_phase_catalog"] == list(RUNTIME_PHASES)
    assert summary["latest_runtime_phase_telemetry"] == block
    assert summary["latest_runtime_resources"] == block["resources"]


def test_hammer_cycle_emits_sample_solver_and_reconstruction_spans_without_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    telemetry = _telemetry("hammer-runtime")
    sample = {
        "sample_id": "hammer-sample",
        "text": RAW_LEGAL_TEXT,
        "legal_ir_views": {
            "deontic": {
                "formula_id": "formula-1",
                "operator": "O",
                "norm_type": "obligation",
                "polarity": "positive",
                "actor": "agency",
                "action": "retain",
                "object": "record",
                "conditions": [],
                "exceptions": [],
                "provenance_ids": ["prov:hash-only"],
            }
        },
    }
    args = Namespace(
        daemon_hammer_guidance_cache_enabled=False,
        daemon_hammer_guidance_enabled=True,
        daemon_hammer_guidance_max_samples_per_cycle=1,
        daemon_hammer_guidance_output_dir=str(tmp_path),
        daemon_hammer_guidance_train_autoencoder=False,
        leanstral_direct_guidance_path="",
        run_id="hammer-runtime",
    )
    monkeypatch.setattr(
        daemon_runner,
        "generate_legal_ir_proof_obligations",
        lambda _sample: [object()],
    )
    monkeypatch.setattr(
        daemon_runner,
        "run_legal_ir_hammer",
        lambda *args, **kwargs: {
            "artifacts": [],
            "obligation_count": 1,
            "reconstruction_receipts": [{"status": "verified"}],
        },
    )

    report = daemon_runner.run_daemon_hammer_guidance_cycle(
        args=args,
        root=tmp_path,
        cycle=1,
        samples=[sample],
        runtime_telemetry=telemetry,
    )
    phases = {span["phase"] for span in telemetry.to_dict()["spans"]}
    serialized = json.dumps(telemetry.to_dict(), sort_keys=True)

    assert report["sample_ids"] == ["hammer-sample"]
    assert {"premise_selection", "solver_execution", "lean_reconstruction"} <= phases
    assert set(LEGAL_IR_VIEW_PHASES) <= phases
    assert "leanstral_inference" in phases
    assert "cache_lookup" in phases
    assert RAW_LEGAL_TEXT not in serialized
