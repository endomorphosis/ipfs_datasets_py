"""Simulated scope contract tests, never real native or kernel qualification."""
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_kernel_custody as kernel
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_controller_worker as scopes
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_kernel_custody import (
    MOUNT, ROOT, WORKER, SimulatedCgroupFS,
)


@pytest.fixture
def pair(request):
    fs = SimulatedCgroupFS()
    fs.group(ROOT, processes="101", tasks=4, memory=512)
    fs.text("memory.max", "512")
    if getattr(request, "param", False):
        del fs.nodes[str(ROOT / "memory.peak")]
        del fs.nodes[str(WORKER / "memory.peak")]
    fs.processes[101] = dict(pid=101, birth=199, state="S", membership="/unit")
    def bind(path, parent, memory):
        return kernel.bind_cgroup(path, expected_root=parent, expected_owner_uid=1000,
            required_memory_max=memory, required_pids_max=8,
            required_cpu_quota_us=100000, required_cpu_period_us=100000, _backend=fs)
    controller = bind(ROOT, MOUNT, 1024)
    worker = bind(WORKER, ROOT, 512)
    try:
        yield fs, controller, worker
    finally:
        worker.close()
        controller.close()
    assert not fs.handles


def observe(pair, **kw):
    _, controller, worker = pair
    values = dict(owner_pid=101, native_memory_bytes=768, native_child_process_slots=2)
    values.update(kw)
    return scopes.observe_controller_worker(controller, worker, **values)


def test_hierarchical_memory_is_counted_once_and_capacity_is_not_a_grant(pair):
    result = observe(pair)
    assert result["aggregate_charged_memory_bytes"] == 512
    assert result["controller"]["memory_max_bytes"] == 1024
    assert result["worker"]["memory_current_bytes"] == 256
    assert result["native_memory_budget_bytes"] == 768
    assert result["controller_capacity_ceiling_is_reservation"] is False
    assert result["whole_controller_kernel_cap_at_native_budget"] is False
    assert result["native_admission"] is result["admitted"] is result["Lean_admitted"] is False
    assert result["simulation"] is result["observation_only"] is True


@pytest.mark.parametrize("owner", [100, 999, 0, True])
def test_owner_cannot_move_to_worker_or_disappear(pair, owner):
    with pytest.raises(kernel.KernelCustodyError):
        observe(pair, owner_pid=owner)


def test_tasks_are_not_native_child_process_slots(pair):
    fs, _, _ = pair
    fs.text("pids.current", "8", group=ROOT)
    assert observe(pair, native_child_process_slots=1)["controller"]["task_count"] == 8


def test_additional_descendants_consume_native_child_process_slots(pair):
    fs, _, _ = pair
    fs.text("cgroup.procs", "101 102", group=ROOT)
    with pytest.raises(kernel.KernelCustodyError, match="process budget"):
        observe(pair, native_child_process_slots=1)


@pytest.mark.parametrize("budget", [0, -1, True, float("inf"), 2048, 256])
def test_budget_numbers_cannot_be_replaced_by_controller_capacity(pair, budget):
    with pytest.raises(kernel.KernelCustodyError):
        observe(pair, native_memory_bytes=budget)


def test_current_charge_exceeding_native_budget_refuses_work(pair):
    fs, _, _ = pair
    fs.text("memory.current", "800", group=ROOT)
    fs.text("memory.peak", "800", group=ROOT)
    with pytest.raises(kernel.KernelCustodyError, match="aggregate controller charge"):
        observe(pair)


def test_between_sample_peak_exceeding_budget_is_not_hidden(pair):
    fs, _, _ = pair
    fs.text("memory.peak", "800", group=ROOT)
    with pytest.raises(kernel.KernelCustodyError, match="lifetime memory peak"):
        observe(pair)


@pytest.mark.parametrize("event", ["max", "oom", "oom_kill", "oom_group_kill"])
@pytest.mark.parametrize("group", [ROOT, WORKER])
def test_memory_limit_damage_is_not_hidden_by_low_current_charge(pair, event, group):
    fs, _, _ = pair
    text = fs.nodes[str(group / "memory.events")]["text"]
    fs.text("memory.events", text.replace(event+" 0", event+" 1"), group=group)
    with pytest.raises(kernel.KernelCustodyError, match="recorded memory limit or OOM event"):
        observe(pair)


@pytest.mark.parametrize("pair", [True], indirect=True)
def test_missing_optional_peak_remains_unknown(pair):
    result = observe(pair)
    assert result["controller"]["memory_peak_bytes"] is None
    assert result["worker"]["memory_peak_bytes"] is None


def test_json_cannot_reconstruct_live_custody_or_native_authority(pair):
    _, controller, worker = pair
    with pytest.raises(kernel.KernelCustodyError, match="live held"):
        scopes.observe_controller_worker(controller.observe(), worker.observe(),
            owner_pid=101, native_memory_bytes=768, native_child_process_slots=2)


def test_closed_binding_is_not_a_cached_success(pair):
    _, controller, _ = pair
    controller.close()
    with pytest.raises(kernel.KernelCustodyError, match="closed"):
        observe(pair)


def test_controller_is_rechecked_after_worker_observation(pair, monkeypatch):
    _, controller, worker = pair
    original = worker.observe
    def closing_controller():
        result = original()
        controller.close()
        return result
    monkeypatch.setattr(worker, "observe", closing_controller)
    with pytest.raises(kernel.KernelCustodyError, match="closed"):
        observe(pair)


def test_worker_outside_controller_is_rejected(pair):
    fs, controller, _ = pair
    foreign = MOUNT / "foreign"
    fs.group(foreign)
    with kernel.bind_cgroup(foreign, expected_root=MOUNT, expected_owner_uid=1000,
            required_memory_max=1024, required_pids_max=8, required_cpu_quota_us=100000,
            required_cpu_period_us=100000, _backend=fs) as worker:
        with pytest.raises(kernel.KernelCustodyError, match="strict descendant"):
            scopes.observe_controller_worker(controller, worker, owner_pid=101,
                native_memory_bytes=768, native_child_process_slots=2)


def test_worker_must_bind_its_controller_as_exact_ancestry_anchor(pair):
    fs, controller, _ = pair
    with kernel.bind_cgroup(WORKER, expected_root=MOUNT, expected_owner_uid=1000,
            required_memory_max=512, required_pids_max=8, required_cpu_quota_us=100000,
            required_cpu_period_us=100000, _backend=fs) as worker:
        with pytest.raises(kernel.KernelCustodyError, match="ancestry anchor"):
            scopes.observe_controller_worker(controller, worker, owner_pid=101,
                native_memory_bytes=768, native_child_process_slots=2)


@pytest.mark.parametrize("fault", ["boot", "mount", "processes", "memory"])
def test_mismatched_kernel_and_hierarchy_observations_fail_closed(pair, fault):
    _, controller, _ = pair
    foreign = SimulatedCgroupFS()
    foreign.group(ROOT, processes="101", tasks=4, memory=512)
    foreign.text("memory.max", "512")
    if fault == "boot":
        foreign.boot = foreign.boot[:-1] + "c"
    elif fault == "mount":
        foreign.mount_record["mount_id"] += 1
    elif fault == "processes":
        foreign.text("cgroup.procs", "200")
    else:
        foreign.text("memory.current", "512")
        foreign.text("memory.peak", "512")
    with kernel.bind_cgroup(WORKER, expected_root=ROOT, expected_owner_uid=1000,
            required_memory_max=512, required_pids_max=8, required_cpu_quota_us=100000,
            required_cpu_period_us=100000, _backend=foreign) as worker:
        # Matching synthetic directory identities deliberately reach the
        # later boot/mount/inventory checks; both backends remain simulations.
        if fault == "memory":
            # root 512 and worker 512 are consistent; make the root smaller
            # while keeping its peak and all kernel limits valid.
            fs = pair[0]
            fs.text("memory.current", "256", group=ROOT)
        with pytest.raises(kernel.KernelCustodyError):
            scopes.observe_controller_worker(controller, worker, owner_pid=101,
                native_memory_bytes=768, native_child_process_slots=2)
