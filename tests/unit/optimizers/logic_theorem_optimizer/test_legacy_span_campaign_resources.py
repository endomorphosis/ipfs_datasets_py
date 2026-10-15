"""Local filesystem/scheduler tests; synthetic CUDA observations are unit tests."""
import json
import os
import pickle
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_campaign_resources as work
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
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
        lane_reservations={}, state_path=tmp_path / "scheduler.json", proof_safety_enabled=True,
        auto_renew_leases=False))
    monkeypatch.setattr(host, "get_global_resource_scheduler", lambda: pytest.fail("implicit global facade"))
    real_factory = existing.open_existing_scheduler
    def private_factory(*args):
        facade = real_factory(*args)
        facade.config.proof_resource_sampler = lambda: existing.native.ProofHostResources(
            8, 32768, 32768, pid_task_limit=500, available_pid_tasks=400)
        facade.config.auto_renew_leases = False
        return facade
    monkeypatch.setattr(existing, "open_existing_scheduler", private_factory)
    ledger = tmp_path / "disk.json"
    ledger.write_text(json.dumps({"schema": host.SCHEMA, "roots": [host._root_identity(root)],
        "limit_bytes": host.MAX_STORAGE_BYTES, "reservations": {
            "preserved": {"reservation_id": "preserved", "status": "retained",
                "owner_pid": 999999, "storage_bytes": 1234, "reason": "other owner's failure"}}}))
    return runtime, ledger, scheduler


def binding(scheduler):
    path = scheduler.state_path
    return dict(scheduler_state_path=path,
        expected_scheduler_policy_sha256=existing.policy_sha256(json.loads(path.read_bytes())["config"]))


def test_local_checks_avoid_global_census_and_explicit_close_preserves_other_claim(local, monkeypatch):
    runtime, ledger, scheduler = local
    preserved = json.loads(ledger.read_text())["reservations"]["preserved"]
    with work.LegacySpanCampaignResources(runtime, ledger, storage_bytes=100_000,
                                         cpu_slots=2, child_process_slots=2, **binding(scheduler)) as owned:
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
    runtime, ledger, scheduler = local
    with work.LegacySpanCampaignResources(runtime, ledger, storage_bytes=100_000,
                                         cpu_slots=1, child_process_slots=1, **binding(scheduler)) as owned:
        key = owned.reservation.reservation_id
    assert json.loads(ledger.read_text())["reservations"][key]["status"] == "retained"


def test_local_overflow_is_rejected_without_releasing_claim(local):
    runtime, ledger, scheduler = local
    with work.LegacySpanCampaignResources(runtime, ledger, storage_bytes=5,
                                         cpu_slots=1, child_process_slots=1, **binding(scheduler)) as owned:
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
        work.LegacySpanCampaignResources(outside, ledger, **binding(scheduler))
    with pytest.raises(work.LegacySpanResourceError, match="interval"):
        work.LegacySpanCampaignResources(runtime, ledger, full_check_interval_seconds=float("inf"), **binding(scheduler))
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


@pytest.mark.parametrize("reserved", [0, work.GIB])
@pytest.mark.parametrize("difference", [-1, 0, 1])
def test_cuda_admission_headroom_boundary_preserves_allocator_reserve(reserved, difference):
    required = 4 * work.GIB - reserved
    torch, calls = _torch(free=required + difference, reserved=reserved)
    if difference < 0:
        with pytest.raises(work.CudaHeadroomPressure) as caught:
            work.admit_cuda_device(torch_module=torch)
        observed = caught.value.observation
        assert observed["free_bytes"] == required - 1
        assert observed["required_free_bytes"] == required
        assert observed["headroom_ok"] is False
        assert observed["allocator_fraction_set"] is False
        assert observed["admission"] is True
        assert calls == []
    else:
        observed = work.admit_cuda_device(torch_module=torch)
        assert observed["required_free_bytes"] == required
        assert observed["headroom_ok"] is True
        assert observed["allocator_fraction_set"] is True
        assert calls == [(0.125, 0)]
    assert observed["budget_bytes"] == 2 * work.GIB
    assert observed["safety_bytes"] == 2 * work.GIB
    assert observed["host_global_gpu_reservation"] is False


@pytest.mark.parametrize("admission", [False, True])
@pytest.mark.parametrize("difference", [-1, 0, 1])
def test_cuda_budget_records_pressure_and_recovers_without_releasing_owner(
        tmp_path, monkeypatch, admission, difference):
    torch, _ = _torch()
    observed = work.cuda_memory_snapshot(torch_module=torch)
    monkeypatch.setattr(work, "cuda_memory_snapshot", lambda device=0: dict(observed))
    with work.CudaDeviceBudget(tmp_path) as budget:
        required = (4 if admission else 2) * work.GIB
        observed["free_bytes"] = required + difference
        observed["observed_at"] += 1
        if difference < 0:
            with pytest.raises(work.CudaHeadroomPressure) as caught:
                budget.check(admission=admission)
            failure = caught.value
            assert failure.args == ("insufficient observed CUDA memory headroom",)
            assert failure.observation == budget.last_observation
            assert failure.observation is not budget.last_observation
            assert failure.observation["free_bytes"] == required - 1
            assert failure.observation["required_free_bytes"] == required
            assert failure.observation["observed_at"] == observed["observed_at"]
            assert failure.observation["headroom_ok"] is False
            restored = pickle.loads(pickle.dumps(failure))
            assert type(restored) is work.CudaHeadroomPressure
            assert restored.args == failure.args
            assert restored.observation == failure.observation
            assert restored.observation is not failure.observation
            restored.observation["free_bytes"] = 0
            assert failure.observation["free_bytes"] == required - 1
            observed["free_bytes"] = required
        healthy = budget.check(admission=admission)
        assert healthy["headroom_ok"] is True
        assert healthy["required_free_bytes"] == required
        assert healthy["free_bytes"] >= required
        assert healthy["admission"] is admission
        assert healthy["budget_bytes"] == 2 * work.GIB
        assert healthy["safety_bytes"] == 2 * work.GIB
        assert healthy["host_global_gpu_reservation"] is False
        assert budget._fd is not None
        # A pause keeps this process's ownership; another owner cannot enter.
        with pytest.raises(work.LegacySpanResourceError, match="already active") as caught:
            with work.CudaDeviceBudget(tmp_path):
                pytest.fail("pressure handling released the CUDA owner")
        assert not isinstance(caught.value, work.CudaHeadroomPressure)
    assert budget._fd is None


@pytest.mark.parametrize("values", [
    {"available": False}, {"free": None}, {"free": 20 * work.GIB},
    {"reserved": 3 * work.GIB}, {"total": work.GIB, "free": work.GIB},
])
def test_only_valid_cuda_free_memory_pressure_is_temporary(values):
    torch, calls = _torch(**values)
    with pytest.raises(work.LegacySpanResourceError) as caught:
        work.admit_cuda_device(torch_module=torch)
    assert not isinstance(caught.value, work.CudaHeadroomPressure)
    assert calls == []


@pytest.mark.parametrize("invalid", [
    {"free_bytes": None}, {"reserved_bytes": 3 * work.GIB},
    {"allocated_bytes": 1, "reserved_bytes": 0},
])
def test_cuda_budget_invalid_telemetry_and_allocator_violation_stay_fatal(
        tmp_path, monkeypatch, invalid):
    torch, _ = _torch()
    observed = work.cuda_memory_snapshot(torch_module=torch)
    monkeypatch.setattr(work, "cuda_memory_snapshot", lambda device=0: dict(observed))
    with work.CudaDeviceBudget(tmp_path) as budget:
        observed.update(invalid)
        with pytest.raises(work.LegacySpanResourceError) as caught:
            budget.check()
        assert not isinstance(caught.value, work.CudaHeadroomPressure)
        assert budget.last_observation["headroom_ok"] is True


def test_cuda_budget_lock_identity_change_is_fatal_even_when_headroom_is_low(
        tmp_path, monkeypatch):
    torch, _ = _torch()
    observed = work.cuda_memory_snapshot(torch_module=torch)
    monkeypatch.setattr(work, "cuda_memory_snapshot", lambda device=0: dict(observed))
    with work.CudaDeviceBudget(tmp_path) as budget:
        budget.lock_path.rename(tmp_path / "retained-lock")
        budget.lock_path.write_bytes(b"")
        observed["free_bytes"] = 0
        with pytest.raises(work.LegacySpanResourceError, match="identity changed") as caught:
            budget.check()
        assert not isinstance(caught.value, work.CudaHeadroomPressure)
        assert budget.last_observation["headroom_ok"] is True
