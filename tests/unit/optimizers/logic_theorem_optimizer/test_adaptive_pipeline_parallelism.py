from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.parallelism_autotuner import (
    ADAPTIVE_PIPELINE_PARALLELISM_SCHEMA_VERSION,
    AdaptivePipelineParallelismController,
    AdaptivePipelineSignals,
    GlobalResourceBounds,
    ParallelismProfile,
    RuntimeResourcePressure,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    ResourceSchedulerConfig,
    SchedulerPressureSummary,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.runtime_telemetry import (
    ResourceSnapshot,
)


def _profile() -> ParallelismProfile:
    return ParallelismProfile(
        name="adaptive",
        hammer_workers=6,
        lean_reconstruction_workers=3,
        leanstral_workers=2,
        legal_ir_family_workers=5,
        incremental_validation_workers=5,
        snapshot_evaluator_workers=4,
        codex_workers=4,
        orchestration_workers=2,
        hammer_lean_cpu_slots=9,
        validation_cpu_slots=5,
        codex_cpu_slots=4,
        orchestration_cpu_slots=2,
        reserve_cpu_slots=1,
    )


def _signals(**overrides) -> AdaptivePipelineSignals:
    data = {
        "ready_queue_depth": {
            "codex": 12,
            "evaluator": 10,
            "hammer": 18,
            "lean_reconstruction": 8,
            "leanstral": 6,
            "snapshot": 5,
            "validation": 9,
        },
        "measured_service_time_seconds": {
            "codex": 60.0,
            "evaluator": 12.0,
            "hammer": 10.0,
            "lean_reconstruction": 8.0,
            "leanstral": 15.0,
            "snapshot": 30.0,
            "validation": 6.0,
        },
        "disjoint_codex_scope_count": 3,
        "nested_child_count": 4,
        "validation_capacity": 3,
        "merge_conflict_rate": 0.0,
        "resource_pressure": RuntimeResourcePressure(
            cpu_utilization=0.74,
            memory_pressure=0.50,
            swap_pressure=0.0,
            gpu_memory_pressure=0.45,
            gpu_telemetry_known=True,
            child_process_count=6,
            child_process_limit=64,
        ),
    }
    data.update(overrides)
    return AdaptivePipelineSignals(**data)


def test_adaptive_controller_uses_queue_scope_service_and_validation_capacity() -> None:
    decision = AdaptivePipelineParallelismController(
        _profile(),
        GlobalResourceBounds(useful_cpu_utilization_min=0.70, useful_cpu_utilization_max=0.90),
    ).recommend(_signals())

    counts = decision.counts
    assert decision.schema_version == ADAPTIVE_PIPELINE_PARALLELISM_SCHEMA_VERSION
    assert decision.target_useful_cpu_range == (0.70, 0.90)
    assert counts.trainer_count == 1
    assert counts.overlapping_write_merge_workers == 1
    assert counts.hammer_workers == 6
    assert counts.codex_workers == 3
    assert counts.legal_ir_family_workers <= 3
    assert counts.incremental_validation_workers <= 3
    assert counts.snapshot_evaluator_workers <= 3
    assert decision.useful_cpu_occupancy == 0.74


def test_adaptive_controller_scales_down_before_contention() -> None:
    healthy = AdaptivePipelineParallelismController(_profile()).recommend(_signals())
    pressured = AdaptivePipelineParallelismController(_profile()).recommend(
        _signals(
            merge_conflict_rate=0.12,
            nested_child_count=50,
            resource_pressure=RuntimeResourcePressure(
                cpu_utilization=0.87,
                memory_pressure=0.83,
                swap_pressure=0.0,
                gpu_memory_pressure=0.84,
                gpu_telemetry_known=True,
                child_process_count=50,
                child_process_limit=64,
            ),
        )
    )

    assert pressured.counts.total_non_trainer_workers < healthy.counts.total_non_trainer_workers
    assert "scaled_down_before_contention" in pressured.reasons
    assert "ram_precontention" in pressured.reasons
    assert "gpu_memory_precontention" in pressured.reasons
    assert "merge_conflict_precontention" in pressured.reasons


def test_unknown_gpu_telemetry_prevents_leanstral_scale_up() -> None:
    decision = AdaptivePipelineParallelismController(_profile()).recommend(
        _signals(
            active_worker_counts={"leanstral": 1},
            resource_pressure=RuntimeResourcePressure(
                cpu_utilization=0.72,
                memory_pressure=0.50,
                swap_pressure=0.0,
                gpu_memory_pressure=0.0,
                gpu_telemetry_known=False,
                child_process_count=2,
                child_process_limit=64,
            ),
        )
    )

    assert decision.counts.leanstral_workers == 1
    assert "gpu_telemetry_unknown" in decision.reasons


def test_resource_scheduler_pressure_summary_normalizes_runtime_telemetry(tmp_path: Path) -> None:
    scheduler = GlobalResourceScheduler(
        ResourceSchedulerConfig(
            total_cpu_slots=4,
            total_memory_mb=1024,
            lane_reservations={"hammer_lean": 4},
            state_path=tmp_path / "scheduler.json",
            auto_renew_leases=False,
        )
    )
    with scheduler.acquire("hammer_lean", cpu_slots=2, memory_mb=128, timeout=0):
        summary = scheduler.pressure_summary(
            resource_snapshot=ResourceSnapshot(
                cpu_percent=86.0,
                memory_percent=81.0,
                swap_percent=2.0,
                gpu_memory_percent=83.0,
                gpu_utilization_percent=70.0,
                gpu_telemetry_available=True,
                child_process_count=11,
            ),
            child_process_limit=20,
        )

    assert summary["cpu_utilization"] == 0.86
    assert summary["memory_pressure"] == 0.81
    assert summary["swap_pressure"] == 0.02
    assert summary["gpu_memory_pressure"] == 0.83
    assert summary["child_process_count"] == 11
    assert summary["child_process_limit"] == 20


def test_scheduler_pressure_summary_from_scheduler_snapshot_falls_back_without_cuda() -> None:
    summary = SchedulerPressureSummary.from_scheduler_snapshot(
        {
            "allocated": {"cpu_slots": 3},
            "available": {"memory_mb": 256, "gpu_memory_mb": 1024},
            "capacity": {
                "cpu_slots": 4,
                "usable_memory_mb": 1024,
                "usable_gpu_memory_mb": 4096,
            },
            "active_child_lease_count": 5,
            "waiting_request_count": 2,
            "counters": {"saturation_events_total": 7},
        },
        child_process_limit=10,
    )

    assert summary.cpu_utilization == 0.75
    assert summary.memory_pressure == 0.75
    assert summary.gpu_memory_pressure == 0.75
    assert summary.child_process_count == 5
    assert summary.waiting_request_count == 2
    assert summary.saturation_events_total == 7


def test_paired_daemon_command_builder_applies_adaptive_counts() -> None:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        uscode_modal_daemon_runner as runner,
    )

    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(
        [
            "--run-id",
            "adaptive-paired",
            "--duration-seconds",
            "1",
            "--loop-role",
            "paired",
            "--codex-parallel-scopes",
            "all",
            "--adaptive-hammer-ready-depth",
            "1",
            "--adaptive-evaluator-ready-depth",
            "1",
            "--adaptive-validation-ready-depth",
            "1",
            "--adaptive-snapshot-ready-depth",
            "1",
            "--codex-apply-conflict-rate",
            "0.25",
        ]
    )
    paired = runner.build_paired_daemon_commands(args, module_name=runner.__name__)
    plan = paired["adaptive_pipeline_parallelism"]
    counts = plan["counts"]

    assert plan["enabled"] is True
    assert counts["trainer_count"] == 1
    assert counts["overlapping_write_merge_workers"] == 1
    assert len(paired["codex_children"]) == max(1, counts["codex_workers"])
    assert paired["autoencoder_command"][
        paired["autoencoder_command"].index("--daemon-hammer-guidance-parallel-workers") + 1
    ] == str(counts["hammer_workers"])
    assert paired["autoencoder_command"][
        paired["autoencoder_command"].index("--autoencoder-bridge-workers") + 1
    ] == str(counts["legal_ir_family_workers"])
