"""Resource estimates bound dispatch without changing training or admission."""
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_capacity as cap
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig,
)


PROBE = {"hardware_cpu_count": 20, "affinity_cpu_count": 20, "cgroup_cpu_count": None,
         "available_memory_mb": 45 * 1024, "cgroup_memory_remaining_mb": None}


def plan(**kwargs):
    args = {"max_workers": 32, "memory_budget_mb": 8192, "pending_count": 100,
            "probe": PROBE}
    return cap.capacity_plan(**{**args, **kwargs})


def test_existing_eight_gib_reservation_caps_auto_width_at_seven():
    result = plan()
    assert result["workers"] == 7
    assert result["limits"]["hardware_cpu_count"] == 20
    assert result["admitted"] is False
    assert result["scope"] == "concurrent_independent_passes"


@pytest.mark.parametrize("observed, expected", [
    ({"affinity_cpu_count": 3}, 3),
    ({"cgroup_cpu_count": 2.5}, 2),
    ({"cgroup_cpu_count": .5}, 0),
    ({"cgroup_memory_remaining_mb": 2000}, 1),
    ({"available_memory_mb": 1400}, 0),
    ({"available_memory_mb": None}, 0),
    ({"hardware_cpu_count": None}, 0),
    ({"probe_errors": ["unreadable_limit"]}, 0),
])
def test_affinity_cgroup_and_unknown_memory_bound_dispatch(observed, expected):
    assert plan(probe={**PROBE, **observed})["workers"] == expected


def test_scheduler_and_storage_capacity_can_defer_without_forcing_one():
    assert plan(scheduler_available_cpu=2)["workers"] == 2
    assert plan(scheduler_available_memory_mb=0)["workers"] == 0
    assert plan(scheduler_available_process_slots=0)["workers"] == 0
    assert plan(storage_headroom_bytes=1_499_999_999, per_worker_storage_bytes=1_500_000_000)["workers"] == 0
    assert plan(storage_headroom_bytes=None, per_worker_storage_bytes=1)["workers"] == 0
    assert plan(pending_count=0)["workers"] == 0
    assert plan(max_workers=1, memory_budget_mb=0)["workers"] == 0


def test_fleet_counts_both_existing_root_and_nested_cpu_memory_envelopes():
    result = plan(memory_budget_mb=80_000, reserve_mb=0,
                  per_worker_memory_mb=9216, per_worker_cpu=2,
                  scheduler_available_cpu=8, scheduler_available_memory_mb=30_000,
                  storage_headroom_bytes=4_000_000_000, per_worker_storage_bytes=1_500_000_000)
    assert result["workers"] == 2
    assert result["limits"]["scheduler_cpu"] == 4
    assert result["limits"]["scheduler_memory"] == 3


def test_reserved_envelope_does_not_double_subtract_other_scheduler_allocations():
    assert plan(cpu_budget=4)["workers"] == 4
    assert plan(cpu_budget=4, scheduler_available_cpu=0)["workers"] == 0


def test_execution_routes_include_nested_proofs_and_owner_memory():
    kwargs = {"max_workers": 32, "memory_budget_mb": 8192, "pending_count": 32, "probe": PROBE}
    training = cap.execution_capacity_plan("training", **kwargs)
    inference = cap.execution_capacity_plan("inference", **kwargs)
    assert training["workers"] == 5
    assert training["execution_envelope"]["estimated_memory_mb"] == 7808
    assert training["execution_envelope"]["child_process_slots"] == 9
    assert inference["workers"] == 4
    assert inference["execution_envelope"]["estimated_memory_mb"] == 7680
    assert inference["execution_envelope"]["child_process_slots"] == 14
    assert cap.execution_envelope("training", 2)["estimated_memory_mb"] >= 2 * 1024 + 2048
    assert cap.execution_envelope("inference", 2)["estimated_memory_mb"] > 2828


def test_process_envelope_overhead_is_reserved_before_counting_passes():
    kwargs = {"max_workers": 8, "memory_budget_mb": 16000, "pending_count": 8, "probe": PROBE}
    assert cap.execution_capacity_plan("inference", scheduler_available_process_slots=4, **kwargs)["workers"] == 0
    assert cap.execution_capacity_plan("inference", scheduler_available_process_slots=8, **kwargs)["workers"] == 2
    assert cap.execution_capacity_plan("training", scheduler_available_process_slots=4, **kwargs)["workers"] == 0
    assert cap.execution_capacity_plan("training", scheduler_available_process_slots=6, **kwargs)["workers"] == 2
    # Inside a leased group, the already-reserved process budget constrains the
    # dispatch without asking the global scheduler to charge it a second time.
    assert cap.execution_capacity_plan("inference", process_budget=5, **kwargs)["workers"] == 1
    assert cap.execution_capacity_plan("training", process_budget=6, **kwargs)["workers"] == 2


def test_too_small_whole_group_cannot_hide_owner_or_lean_memory():
    kwargs = {"max_workers": 1, "memory_budget_mb": 2048, "pending_count": 1, "probe": PROBE}
    assert cap.execution_capacity_plan("training", **kwargs)["workers"] == 0
    assert cap.execution_capacity_plan("inference", **kwargs)["workers"] == 0
    assert cap.execution_envelope("training", 0)["child_process_slots"] == 0
    with pytest.raises(ValueError, match="overridden"):
        cap.execution_capacity_plan("training", reserve_mb=0, **kwargs)
    with pytest.raises(ValueError, match="execution mode"):
        cap.execution_envelope("train-and-infer", 1)


@pytest.mark.parametrize("kwargs", [
    {"max_workers": True}, {"max_workers": 33}, {"per_worker_cpu": 0},
    {"reserve_mb": -1}, {"pending_count": -1}, {"storage_headroom_bytes": -1},
    {"probe": {**PROBE, "cgroup_cpu_count": float("nan")}},
    {"probe": {**PROBE, "available_memory_mb": -1}},
])
def test_invalid_caps_do_not_turn_into_admission(kwargs):
    with pytest.raises(ValueError):
        plan(**kwargs)


def test_probe_reads_inherited_v2_limits_and_uses_most_restrictive(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self/cgroup").write_text("0::/parent/child\n")
    (proc / "self/mountinfo").write_text("1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n")
    (proc / "meminfo").write_text("MemAvailable: 10485760 kB\n")
    root = tmp_path / "mount/sys/fs/cgroup"
    child = root / "parent/child"
    child.mkdir(parents=True)
    (root / "cpu.max").write_text("max 100000")
    (root / "memory.max").write_text("max")
    (child.parent / "cpu.max").write_text("200000 100000")
    (child.parent / "memory.max").write_text(str(4096 * cap.MIB))
    (child.parent / "memory.current").write_text(str(3072 * cap.MIB))
    (child / "cpu.max").write_text("400000 100000")
    (child / "memory.max").write_text(str(8192 * cap.MIB))
    (child / "memory.current").write_text(str(512 * cap.MIB))
    monkeypatch.setattr(cap.os, "cpu_count", lambda: 20)
    monkeypatch.setattr(cap.os, "sched_getaffinity", lambda pid: set(range(6)))
    observed = cap.hardware_probe(proc_root=proc, mount_prefix=tmp_path / "mount")
    assert observed["cgroup_cpu_count"] == 2
    assert observed["cgroup_memory_remaining_mb"] == 1024
    assert observed["affinity_cpu_count"] == 6
    assert plan(probe=observed)["workers"] == 0
    assert observed["probe_errors"] == []


def test_probe_v1_limits_and_invalid_visible_memory_fail_closed(tmp_path):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self/cgroup").write_text("2:cpu,cpuacct:/job\n3:memory:/job\n")
    (proc / "self/mountinfo").write_text(
        "1 0 0:1 / /sys/fs/cgroup/cpu rw - cgroup cgroup rw,cpu,cpuacct\n"
        "2 0 0:2 / /sys/fs/cgroup/memory rw - cgroup cgroup rw,memory\n")
    (proc / "meminfo").write_text("MemAvailable: 10485760 kB\n")
    cpu = tmp_path / "mount/sys/fs/cgroup/cpu/job"
    memory = tmp_path / "mount/sys/fs/cgroup/memory/job"
    cpu.mkdir(parents=True)
    memory.mkdir(parents=True)
    (cpu / "cpu.cfs_quota_us").write_text("100000")
    (cpu / "cpu.cfs_period_us").write_text("100000")
    (memory / "memory.limit_in_bytes").write_text("2097152000")
    (memory / "memory.usage_in_bytes").write_text("invalid")
    observed = cap.hardware_probe(proc_root=proc, mount_prefix=tmp_path / "mount")
    assert observed["cgroup_cpu_count"] == 1
    assert observed["probe_errors"] == ["invalid_cgroup_memory_limit"]
    assert plan(probe=observed)["workers"] == 0


def test_scheduler_snapshot_never_creates_files_and_preserves_protected_lanes(tmp_path):
    config = ResourceSchedulerConfig(state_path=tmp_path / "absent/state.json", total_memory_mb=50_000)
    observed = cap.scheduler_snapshot(config)
    assert not (tmp_path / "absent").exists()
    free = cap.scheduler_capacity(observed)
    assert free == {"cpu_slots": 8, "memory_mb": 50_000, "child_process_slots": 64}


def test_scheduler_snapshot_counts_retained_roots_not_nested_children_without_recovery(tmp_path):
    config = ResourceSchedulerConfig(state_path=tmp_path / "scheduler.json", total_memory_mb=50_000,
                                     auto_renew_leases=False)
    scheduler = GlobalResourceScheduler(config)
    with scheduler.acquire(lane="hammer_lean", cpu_slots=2, memory_mb=8192, child_process_slots=2) as root:
        with root.acquire_child(cpu_slots=1, memory_mb=1024, child_process_slots=1):
            original = config.state_path.read_bytes()
            observed = cap.scheduler_snapshot(config)
            assert config.state_path.read_bytes() == original
            assert cap.scheduler_capacity(observed) == {
                "cpu_slots": 6, "memory_mb": 50_000 - 8192, "child_process_slots": 62}
            raw = json.loads(original)
            for record in raw["leases"].values():
                record["expires_at"] = 0
            config.state_path.write_text(json.dumps(raw))
            expired = config.state_path.read_bytes()
            assert cap.scheduler_capacity(cap.scheduler_snapshot(config)) == cap.scheduler_capacity(observed)
            assert config.state_path.read_bytes() == expired


def test_scheduler_corruption_or_configuration_drift_is_not_free_capacity(tmp_path):
    config = ResourceSchedulerConfig(state_path=tmp_path / "scheduler.json", total_memory_mb=50_000)
    GlobalResourceScheduler(config)
    other = ResourceSchedulerConfig(state_path=config.state_path, total_memory_mb=51_000)
    with pytest.raises(ValueError, match="configuration"):
        cap.scheduler_snapshot(other)
    config.state_path.write_text("{}")
    with pytest.raises(ValueError, match="schema"):
        cap.scheduler_snapshot(config)


@pytest.mark.parametrize("mode", ["training", "inference"])
@pytest.mark.parametrize("limit", ["cpu_budget", "scheduler_available_cpu", "affinity_cpu_count", "cgroup_cpu_count"])
def test_execution_reserves_owner_cpu_inside_every_independent_limit(mode, limit):
    kwargs = {"max_workers": 32, "memory_budget_mb": 32768, "pending_count": 8, "probe": PROBE}
    if limit in PROBE:
        kwargs["probe"] = {**PROBE, limit: 8}
    else:
        kwargs[limit] = 8
    result = cap.execution_capacity_plan(mode, **kwargs)
    assert result["workers"] == 7
    assert result["execution_envelope"]["cpu_slots"] == 8
    assert result["execution_envelope"]["worker_cpu_slots"] == 7
    assert result["execution_envelope"]["coordinator_cpu_slots"] == 1


def test_training_owner_cpu_is_not_charged_twice_inside_reserved_group():
    kwargs = {"max_workers": 32, "memory_budget_mb": 12288, "pending_count": 8, "probe": PROBE}
    root = cap.execution_capacity_plan("training", scheduler_available_cpu=8, **kwargs)
    assert root["workers"] == 7
    nested = cap.execution_capacity_plan("training",
        **{**kwargs, "max_workers": root["workers"]},
        cpu_budget=root["execution_envelope"]["cpu_slots"],
        process_budget=root["execution_envelope"]["child_process_slots"])
    assert nested["workers"] == 7
    shrunk = cap.execution_capacity_plan("training",
        **{**kwargs, "probe": {**PROBE, "affinity_cpu_count": 4}},
        cpu_budget=root["execution_envelope"]["cpu_slots"])
    assert shrunk["workers"] == 3
    assert cap.execution_capacity_plan("training", cpu_budget=1, **kwargs)["workers"] == 0
    assert cap.execution_envelope("training", 0)["cpu_slots"] == 0


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_invalid_owner_cpu_reserve_cannot_expand_capacity(value):
    with pytest.raises(ValueError):
        plan(reserve_cpu_slots=value)
