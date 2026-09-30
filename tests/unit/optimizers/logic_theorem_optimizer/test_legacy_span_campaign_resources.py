"""Local filesystem/scheduler tests; synthetic CUDA observations are unit tests."""
import json
import os
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_campaign_resources as work
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig,
)


@pytest.fixture
def local(tmp_path, monkeypatch):
    root = tmp_path / "outputs"
    root.mkdir()
    runtime = root / "runtime"
    runtime.mkdir()
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig(
        total_cpu_slots=4, total_memory_mb=16384, total_child_process_slots=8,
        lane_reservations={}, state_path=tmp_path / "scheduler.json", auto_renew_leases=False))
    monkeypatch.setattr(host, "get_global_resource_scheduler", lambda: scheduler)
    ledger = tmp_path / "disk.json"
    ledger.write_text(json.dumps({"schema": host.SCHEMA, "roots": [host._root_identity(root)],
        "limit_bytes": host.MAX_STORAGE_BYTES, "reservations": {
            "preserved": {"reservation_id": "preserved", "status": "retained",
                "owner_pid": 999999, "storage_bytes": 1234, "reason": "other owner's failure"}}}))
    return runtime, ledger, scheduler


def test_local_checks_avoid_global_census_and_explicit_close_preserves_other_claim(local, monkeypatch):
    runtime, ledger, scheduler = local
    preserved = json.loads(ledger.read_text())["reservations"]["preserved"]
    with work.LegacySpanCampaignResources(runtime, ledger, storage_bytes=100_000,
                                         cpu_slots=2, child_process_slots=2) as owned:
        assert scheduler.snapshot()["allocated"]["cpu_slots"] == 2
        original = owned.reservation.check_usage
        monkeypatch.setattr(owned.reservation, "check_usage", lambda *a, **k: pytest.fail("global census"))
        (runtime / "receipt").write_text("observed")
        result = owned.check_limits()
        assert result["full_ledger_check"] is False
        assert result["attempt_bytes"] == 8
        assert result["host_global_gpu_reservation"] is False
        monkeypatch.setattr(owned.reservation, "check_usage", original)
        assert owned.check_limits(full=True)["full_ledger_check"] is True
        assert owned.close(artifacts_durable=True)["status"] == "released"
    assert scheduler.snapshot()["allocated"]["cpu_slots"] == 0
    assert json.loads(ledger.read_text())["reservations"]["preserved"] == preserved


def test_context_exit_without_durable_close_retains_claim(local):
    runtime, ledger, _ = local
    with work.LegacySpanCampaignResources(runtime, ledger, storage_bytes=100_000,
                                         cpu_slots=1, child_process_slots=1) as owned:
        key = owned.reservation.reservation_id
    assert json.loads(ledger.read_text())["reservations"][key]["status"] == "retained"


def test_local_overflow_is_rejected_without_releasing_claim(local):
    runtime, ledger, _ = local
    with work.LegacySpanCampaignResources(runtime, ledger, storage_bytes=5,
                                         cpu_slots=1, child_process_slots=1) as owned:
        (runtime / "large").write_bytes(b"123456")
        with pytest.raises(work.LegacySpanResourceError, match="storage limit"):
            owned.check_limits()
        key = owned.reservation.reservation_id
    assert json.loads(ledger.read_text())["reservations"][key]["status"] == "retained"


def test_outside_runtime_and_nonfinite_interval_fail_before_admission(local, tmp_path):
    runtime, ledger, scheduler = local
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(work.LegacySpanResourceError, match="outside"):
        work.LegacySpanCampaignResources(outside, ledger)
    with pytest.raises(work.LegacySpanResourceError, match="interval"):
        work.LegacySpanCampaignResources(runtime, ledger, full_check_interval_seconds=float("inf"))
    assert scheduler.snapshot()["allocated"]["cpu_slots"] == 0


def _torch(*, free=8 * work.GIB, total=16 * work.GIB, reserved=0, available=True):
    calls = []
    cuda = SimpleNamespace(is_available=lambda: available, device_count=lambda: 1,
        mem_get_info=lambda device: (free, total), get_device_name=lambda device: "unit-test-device",
        memory_allocated=lambda device: 0, memory_reserved=lambda device: reserved,
        set_per_process_memory_fraction=lambda fraction, device: calls.append((fraction, device)))
    return SimpleNamespace(cuda=cuda, __version__="unit-test", version=SimpleNamespace(cuda="unit-test")), calls


def test_cuda_admission_sets_only_actual_worker_allocator_fraction():
    torch, calls = _torch()
    value = work.admit_cuda_device(torch_module=torch)
    assert calls == [(0.125, 0)]
    assert value["allocator_fraction_set"] is True
    assert value["host_global_gpu_reservation"] is False
    assert value["other_cuda_allocators_limited"] is False


@pytest.mark.parametrize("values", [
    {"available": False}, {"free": None}, {"free": 1},
    {"free": 20 * work.GIB}, {"reserved": 3 * work.GIB},
])
def test_unknown_insufficient_or_inconsistent_cuda_never_admits(values):
    torch, calls = _torch(**values)
    with pytest.raises(work.LegacySpanResourceError):
        work.admit_cuda_device(torch_module=torch)
    assert calls == []


def test_campaign_cuda_lock_excludes_second_owner_and_fails_on_lost_headroom(tmp_path, monkeypatch):
    torch, _ = _torch()
    observed = work.cuda_memory_snapshot(torch_module=torch)
    monkeypatch.setattr(work, "cuda_memory_snapshot", lambda device=0: dict(observed))
    with work.CudaDeviceBudget(tmp_path) as first:
        with pytest.raises(work.LegacySpanResourceError, match="already active"):
            with work.CudaDeviceBudget(tmp_path):
                pytest.fail("second owner admitted")
        observed["free_bytes"] = 0
        with pytest.raises(work.LegacySpanResourceError, match="headroom"):
            first.check()
    observed["free_bytes"] = 8 * work.GIB
    with work.CudaDeviceBudget(tmp_path):
        pass


def test_cuda_lock_symlink_rejected(tmp_path):
    (tmp_path / "other").write_text("preserved")
    (tmp_path / ".legacy-cuda-0.lock").symlink_to(tmp_path / "other")
    with pytest.raises(OSError):
        with work.CudaDeviceBudget(tmp_path):
            pytest.fail("symlink lock admitted")
    assert (tmp_path / "other").read_text() == "preserved"
