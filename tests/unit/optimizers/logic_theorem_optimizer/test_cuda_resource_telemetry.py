from __future__ import annotations

import os
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.bench_legal_ir_optimizer_pipeline import aggregate_pipeline_summaries
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.parallelism_autotuner import (
    BenchmarkTrial,
    ParallelismAutotuner,
    ParallelismProfile,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    LeaseTimeoutError,
    ResourceSchedulerConfig,
    ResourceUnavailableError,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.runtime_telemetry import (
    ResourceSnapshot,
    collect_resource_snapshot,
)


def _summary(cache_state: str, *, cache_hit: float) -> dict:
    quality = {
        "compiler_ir_cosine": 0.9,
        "structural_validity": 0.98,
        "symbolic_validity_success_rate": 0.97,
        "hammer_proof_success_rate": 0.93,
        "hammer_reconstruction_success_rate": 0.91,
        "source_copy_penalty": 0.05,
    }
    resources = {
        "cpu_percent": 82.0,
        "gpu_utilization_percent": 70.0,
        "gpu_memory_percent": 75.0,
        "gpu_telemetry_available": True,
        "memory_percent": 65.0,
        "memory_used_bytes": 1024,
        "swap_percent": 0.0,
        "swap_used_bytes": 0,
        "child_process_count": 8,
        "queue_depth": 3,
    }
    spans = []
    for phase, duration, units in (
        ("compilation", 2.0, 10.0),
        ("projection_training", 2.0, 1.0),
        ("solver_execution", 1.0, 8.0),
        ("lean_reconstruction", 1.5, 6.0),
        ("leanstral_queue", 0.4, 2.0),
        ("codex_queue_wait", 0.8, 1.0),
    ):
        spans.append(
            {
                "phase": phase,
                "duration_seconds": duration,
                "unit_count": units,
                "resources_start": dict(resources),
                "resources_end": dict(resources),
            }
        )
    return {
        "benchmark_cache_state": cache_state,
        "benchmark_elapsed_seconds": 10.0,
        "benchmark_completed_units": 20,
        "benchmark_quality_metrics": quality,
        "codex_main_apply_count": 1,
        "program_synthesis_transient_failure_rate": 0.05,
        "runtime_telemetry": {"cache_hit_rate": cache_hit, "spans": spans},
        "leanstral_batch_telemetry": {
            "dispatched_item_count": 8,
            "formed_batch_count": 1,
            "batch_sizes": [8],
        },
    }


class _Cuda:
    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def device_count() -> int:
        return 1

    @staticmethod
    def memory_allocated(index: int = 0) -> int:
        assert index == 0
        return 256 * 1024 * 1024

    @staticmethod
    def memory_reserved(index: int = 0) -> int:
        assert index == 0
        return 512 * 1024 * 1024

    @staticmethod
    def get_device_properties(index: int = 0):
        assert index == 0
        return types.SimpleNamespace(total_memory=16 * 1024 * 1024 * 1024)


def _scheduler_config(
    state_path: Path,
    *,
    sampler=None,
    gpu_memory: int | None = 4096,
    reserved_memory: int = 0,
    reserved_gpu_memory: int = 0,
) -> ResourceSchedulerConfig:
    return ResourceSchedulerConfig(
        total_cpu_slots=2,
        total_memory_mb=1024,
        total_gpu_memory_mb=gpu_memory,
        reserved_memory_mb=reserved_memory,
        reserved_gpu_memory_mb=reserved_gpu_memory,
        lane_reservations={"hammer_lean": {"cpu_slots": 2, "memory_mb": 1024 - reserved_memory}},
        state_path=state_path,
        lease_ttl_seconds=5,
        poll_interval_seconds=0.001,
        auto_renew_leases=False,
        max_memory_percent=90.0,
        max_swap_percent=1.0,
        max_gpu_memory_percent=92.0,
        resource_pressure_sampler=sampler,
    )


def test_pytorch_cuda_detection_survives_nvml_unavailability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=_Cuda()))
    monkeypatch.setitem(sys.modules, "pynvml", None)
    monkeypatch.setattr("shutil.which", lambda name: None)

    snapshot = collect_resource_snapshot()

    assert snapshot.cuda_available is True
    assert snapshot.gpu_device_count == 1
    assert snapshot.gpu_telemetry_available is True
    assert snapshot.gpu_memory_total_bytes == 16 * 1024 * 1024 * 1024
    assert snapshot.process_gpu_memory_used_bytes == 512 * 1024 * 1024
    assert "torch_cuda_ok" in snapshot.collector_status
    assert "nvml_unavailable" in snapshot.collector_status
    assert "gpu_unavailable" not in snapshot.collector_status


def test_nvml_process_attribution_separates_trainer_and_leanstral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer_pid = os.getpid()
    leanstral_pid = trainer_pid + 1000

    class _Memory:
        used = 3 * 1024 * 1024 * 1024
        total = 16 * 1024 * 1024 * 1024

    class _Utilization:
        gpu = 41

    class _Nvml:
        @staticmethod
        def nvmlInit() -> None:
            return None

        @staticmethod
        def nvmlShutdown() -> None:
            return None

        @staticmethod
        def nvmlDeviceGetCount() -> int:
            return 1

        @staticmethod
        def nvmlDeviceGetHandleByIndex(index: int) -> str:
            assert index == 0
            return "gpu0"

        @staticmethod
        def nvmlDeviceGetUtilizationRates(handle: str) -> _Utilization:
            assert handle == "gpu0"
            return _Utilization()

        @staticmethod
        def nvmlDeviceGetMemoryInfo(handle: str) -> _Memory:
            assert handle == "gpu0"
            return _Memory()

        @staticmethod
        def nvmlDeviceGetComputeRunningProcesses(handle: str):
            assert handle == "gpu0"
            return [
                types.SimpleNamespace(pid=trainer_pid, usedGpuMemory=1024 * 1024 * 1024),
                types.SimpleNamespace(pid=leanstral_pid, usedGpuMemory=2 * 1024 * 1024 * 1024),
            ]

    class _Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def memory_info(self):
            return types.SimpleNamespace(rss=200 * 1024 * 1024)

        def cmdline(self):
            if self.pid == leanstral_pid:
                return ["python", "-m", "leanstral_server"]
            return ["python", "-m", "trusted_feedback_trainer"]

        def name(self):
            return "python"

        def parents(self):
            return []

        def children(self, recursive: bool = False):
            return []

        def cpu_percent(self, interval=None):
            return 0.0

    psutil = types.SimpleNamespace(
        Process=_Process,
        virtual_memory=lambda: types.SimpleNamespace(
            used=10 * 1024 * 1024 * 1024,
            total=128 * 1024 * 1024 * 1024,
            percent=7.8,
        ),
        swap_memory=lambda: types.SimpleNamespace(used=0, percent=0.0),
        cpu_percent=lambda interval=None: 0.0,
    )
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "pynvml", _Nvml)
    monkeypatch.setitem(sys.modules, "psutil", psutil)
    monkeypatch.setattr("shutil.which", lambda name: None)

    snapshot = collect_resource_snapshot()

    assert snapshot.gpu_utilization_percent == 41.0
    assert snapshot.trainer_gpu_memory_used_bytes == 1024 * 1024 * 1024
    assert snapshot.leanstral_gpu_memory_used_bytes == 2 * 1024 * 1024 * 1024
    assert snapshot.trainer_unified_memory_used_bytes == 1224 * 1024 * 1024
    assert snapshot.leanstral_unified_memory_used_bytes == 2248 * 1024 * 1024
    assert {item["role"] for item in snapshot.to_dict()["gpu_processes"]} >= {
        "trainer",
        "leanstral",
    }


def test_zero_gpu_use_is_not_reported_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class _IdleCuda(_Cuda):
        @staticmethod
        def memory_allocated(index: int = 0) -> int:
            return 0

        @staticmethod
        def memory_reserved(index: int = 0) -> int:
            return 0

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=_IdleCuda()))
    monkeypatch.setitem(sys.modules, "pynvml", None)
    monkeypatch.setattr("shutil.which", lambda name: None)

    snapshot = collect_resource_snapshot()

    assert snapshot.gpu_memory_used_bytes == 0
    assert snapshot.gpu_memory_percent == 0.0
    assert snapshot.gpu_telemetry_available is True
    assert "gpu_unavailable" not in snapshot.collector_status


def test_gpu_unavailable_keeps_gpu_values_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NoCuda:
        @staticmethod
        def is_available() -> bool:
            return False

        @staticmethod
        def device_count() -> int:
            return 0

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=_NoCuda()))
    monkeypatch.setitem(sys.modules, "pynvml", None)
    monkeypatch.setattr("shutil.which", lambda name: None)

    snapshot = collect_resource_snapshot()

    assert snapshot.cuda_available is False
    assert snapshot.gpu_device_count == 0
    assert snapshot.gpu_memory_used_bytes is None
    assert snapshot.gpu_memory_percent is None
    assert snapshot.gpu_telemetry_available is False
    assert "gpu_unavailable" in snapshot.collector_status


def test_scheduler_admits_gpu_work_against_reserved_unified_memory_and_pressure(
    tmp_path: Path,
) -> None:
    healthy = ResourceSnapshot(
        memory_percent=70.0,
        swap_percent=0.0,
        gpu_memory_percent=40.0,
        gpu_memory_used_bytes=4 * 1024 * 1024 * 1024,
        gpu_device_count=1,
        gpu_telemetry_available=True,
        cuda_available=True,
    )
    scheduler = GlobalResourceScheduler(
        _scheduler_config(
            tmp_path / "scheduler.json",
            sampler=lambda: healthy,
            reserved_memory=128,
            reserved_gpu_memory=1024,
        )
    )
    lease = scheduler.acquire(
        "hammer_lean",
        cpu_slots=1,
        memory_mb=800,
        gpu_memory_mb=2048,
        requires_gpu=True,
        timeout=0,
    )
    try:
        snapshot = scheduler.snapshot()
        assert snapshot["capacity"]["usable_memory_mb"] == 896
        assert snapshot["capacity"]["usable_gpu_memory_mb"] == 3072
        assert snapshot["allocated_gpu_memory_mb"] == 2048
        with pytest.raises(ResourceUnavailableError):
            scheduler.acquire(
                "hammer_lean",
                cpu_slots=1,
                memory_mb=1,
                gpu_memory_mb=3073,
                requires_gpu=True,
                timeout=0,
            )
    finally:
        lease.release()

    pressured = replace(healthy, gpu_memory_percent=95.0)
    blocked = GlobalResourceScheduler(
        _scheduler_config(tmp_path / "blocked.json", sampler=lambda: pressured)
    )
    with pytest.raises(LeaseTimeoutError):
        blocked.acquire(
            "hammer_lean",
            cpu_slots=1,
            memory_mb=1,
            gpu_memory_mb=1,
            requires_gpu=True,
            timeout=0,
        )


def test_scheduler_rejects_gpu_work_when_gpu_telemetry_is_unknown(tmp_path: Path) -> None:
    unknown = ResourceSnapshot(
        memory_percent=70.0,
        swap_percent=0.0,
        gpu_memory_percent=None,
        gpu_memory_used_bytes=None,
        gpu_device_count=0,
        gpu_telemetry_available=False,
        cuda_available=None,
        collector_status="gpu_unavailable",
    )
    scheduler = GlobalResourceScheduler(
        _scheduler_config(tmp_path / "scheduler.json", sampler=lambda: unknown)
    )

    with pytest.raises(LeaseTimeoutError):
        scheduler.acquire(
            "hammer_lean",
            cpu_slots=1,
            memory_mb=1,
            gpu_memory_mb=1,
            requires_gpu=True,
            timeout=0,
        )


def test_autotuner_will_not_promote_candidate_from_unknown_gpu_evidence() -> None:
    baseline = aggregate_pipeline_summaries(
        [_summary("cold", cache_hit=0.0), _summary("warm", cache_hit=0.9)],
        ParallelismProfile(name="fixed_baseline"),
    )
    candidate_summaries = [_summary("cold", cache_hit=0.0), _summary("warm", cache_hit=0.9)]
    for summary in candidate_summaries:
        for span in summary["runtime_telemetry"]["spans"]:
            for boundary in ("resources_start", "resources_end"):
                span[boundary].pop("gpu_utilization_percent", None)
                span[boundary].pop("gpu_memory_percent", None)
                span[boundary].pop("gpu_memory_used_bytes", None)
                span[boundary]["gpu_telemetry_available"] = False
    candidate = aggregate_pipeline_summaries(
        candidate_summaries,
        ParallelismProfile(name="candidate"),
    )
    faster_unknown = BenchmarkTrial(
        candidate.profile,
        replace(
            candidate.metrics,
            cold_cache_throughput_per_hour=baseline.metrics.cold_cache_throughput_per_hour * 2,
            warm_cache_throughput_per_hour=baseline.metrics.warm_cache_throughput_per_hour * 2,
            cpu_utilization_average=0.82,
            cpu_utilization_peak=0.86,
        ),
    )

    result = ParallelismAutotuner().tune(baseline, [faster_unknown])

    assert result.promoted is False
    assert result.selected.profile.name == "fixed_baseline"
    assert result.evaluations[0].violations == ("gpu_telemetry_unknown",)
