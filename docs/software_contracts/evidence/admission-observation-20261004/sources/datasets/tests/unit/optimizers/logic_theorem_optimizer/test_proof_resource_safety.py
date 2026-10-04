"""Resource-pressure admission tests using small synthetic host snapshots."""
from dataclasses import replace
import threading
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import (
    ProofHostResources, collect_proof_host_resources,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceConfigurationError, ResourceSchedulerConfig,
    ResourceUnavailableError, LeaseCancelledError,
)


def test_probe_respects_nested_cgroup_limits(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    group = tmp_path / "cgroup"
    (proc / "self").mkdir(parents=True)
    (group / "worker").mkdir(parents=True)
    (proc / "meminfo").write_text("MemTotal: 8388608 kB\nMemAvailable: 6291456 kB\n")
    (proc / "self/cgroup").write_text("0::/worker\n")
    (group / "cpu.max").write_text("400000 100000")
    (group / "memory.max").write_text(str(4 * 1024**3))
    (group / "memory.current").write_text(str(3 * 1024**3))
    (group / "worker/cpu.max").write_text("250000 100000")
    (group / "worker/memory.high").write_text(str(2 * 1024**3))
    (group / "worker/memory.current").write_text(str(1536 * 1024**2))
    (group / "worker/memory.pressure").write_text("full avg10=3.25 avg60=0 avg300=0 total=1\n")
    monkeypatch.setattr("os.sched_getaffinity", lambda _: set(range(16)))
    result = collect_proof_host_resources(proc, group)
    assert result.cpu_slots == 2
    assert result.total_memory_mb == 2048
    assert result.available_memory_mb == 512
    assert result.memory_stall_percent == 3.25


def _scheduler(tmp_path, sampler):
    return GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json", proof_resource_sampler=sampler,
        lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=0,
    ))


def test_profile_preserves_headroom_and_caps_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_RESOURCE_CPU_SLOTS", "128")
    monkeypatch.setenv("IPFS_DATASETS_RESOURCE_MEMORY_MB", "999999")
    config = ResourceSchedulerConfig.for_proof_host(
        proof_resource_sampler=lambda: ProofHostResources(10, 1000, 900),
    )
    assert config.total_cpu_slots == 8
    assert config.total_memory_mb == 800
    assert config.proof_memory_headroom_mb == 200


@pytest.mark.parametrize("change", [
    {"available_memory_mb": 250}, {"memory_stall_percent": 2},
    {"cpu_stall_percent": 50}, {"io_stall_percent": 10},
])
def test_pressure_blocks_new_children_and_recovers(tmp_path, change):
    host = ProofHostResources(8, 1000, 1000)
    current = [host]
    scheduler = _scheduler(tmp_path, lambda: current[0])
    with scheduler.acquire("hammer", cpu_slots=2, memory_mb=200, timeout=0) as parent:
        current[0] = replace(host, **change)
        assert scheduler.try_acquire("hammer", cpu_slots=1, memory_mb=100, parent=parent) is None
        current[0] = host
        with parent.acquire_child(cpu_slots=1, memory_mb=100, timeout=0):
            pass
    assert scheduler.snapshot()["active_root_lease_count"] == 0


def test_pending_reservations_cannot_spend_same_available_ram(tmp_path):
    scheduler = _scheduler(tmp_path, lambda: ProofHostResources(8, 1000, 600))
    with scheduler.acquire("hammer", memory_mb=250, timeout=0):
        assert scheduler.try_acquire("hammer", memory_mb=250) is None
    with scheduler.acquire("hammer", memory_mb=250, timeout=0):
        pass


def test_unknown_telemetry_blocks_admission(tmp_path):
    healthy = [True]
    def sample():
        if not healthy[0]:
            raise OSError("telemetry unavailable")
        return ProofHostResources(8, 1000, 1000)
    scheduler = _scheduler(tmp_path, sample)
    healthy[0] = False
    assert scheduler.try_acquire("hammer", memory_mb=100) is None
    assert scheduler.snapshot()["waiting_request_count"] == 0


def test_unbudgeted_work_fails_immediately(tmp_path):
    scheduler = _scheduler(tmp_path, lambda: ProofHostResources(8, 1000, 1000))
    with pytest.raises(ResourceConfigurationError, match="positive memory_mb"):
        scheduler.acquire("hammer", timeout=0)


def test_default_scheduler_enables_safety_and_explicit_opt_out(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as module
    monkeypatch.delenv("IPFS_DATASETS_PROOF_RESOURCE_SAFETY", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_RESOURCE_SCHEDULER_PATH", str(tmp_path / "defaults.json"))
    monkeypatch.setattr(module, "collect_proof_host_resources", lambda: ProofHostResources(8, 1000, 1000))
    direct = GlobalResourceScheduler()
    shared = module.get_global_resource_scheduler()
    assert direct.config.proof_safety_enabled
    assert shared.config.proof_safety_enabled
    assert direct.config.total_cpu_slots == 6
    assert direct.config.max_waiting_requests == 256
    monkeypatch.setenv("IPFS_DATASETS_PROOF_RESOURCE_SAFETY", "0")
    assert not module.default_resource_scheduler_config().proof_safety_enabled


def test_waiting_job_automatically_resumes_after_external_load_clears(tmp_path):
    healthy = ProofHostResources(8, 1000, 1000)
    current = [replace(healthy, cpu_stall_percent=80)]
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json", proof_resource_sampler=lambda: current[0],
        lane_reservations={}, proof_backoff_seconds=0.05, poll_interval_seconds=0.005,
        auto_renew_leases=False,
    ))
    acquired = threading.Event()
    errors = []
    def run():
        try:
            with scheduler.acquire("hammer", memory_mb=100, timeout=2):
                acquired.set()
        except Exception as error:
            errors.append(error)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        deadline = time.monotonic() + 1
        while not scheduler.snapshot()["proof_backoff"] and time.monotonic() < deadline:
            time.sleep(0.005)
        assert scheduler.snapshot()["proof_backoff"]["reason"] == "proof_cpu_stall"
        assert not acquired.is_set()
        current[0] = healthy
        assert acquired.wait(1)
    finally:
        current[0] = healthy
        worker.join(2)
    assert not errors
    assert not worker.is_alive()
    assert scheduler.snapshot()["active_lease_count"] == 0


@pytest.mark.parametrize("pressure,reason", [
    ({"available_memory_mb": 100}, "proof_memory_headroom"),
    ({"cpu_stall_percent": 75}, "proof_cpu_stall"),
    ({"memory_stall_percent": 5}, "proof_memory_stall"),
    ({"io_stall_percent": 20}, "proof_io_stall"),
])
def test_external_pressure_backoff_is_shared_and_resumes_after_cooldown(tmp_path, monkeypatch, pressure, reason):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as module
    clock = [1000.0]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    healthy = ProofHostResources(8, 1000, 1000)
    current = [healthy]
    calls = []
    def sample():
        calls.append(clock[0])
        return current[0]
    config = ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json", proof_resource_sampler=sample,
        lane_reservations={}, auto_renew_leases=False, proof_backoff_seconds=2,
    )
    first = GlobalResourceScheduler(config)
    second = GlobalResourceScheduler(config)
    with first.acquire("hammer", cpu_slots=2, memory_mb=200, timeout=0) as parent:
        current[0] = replace(healthy, **pressure)
        assert second.try_acquire("hammer", memory_mb=100) is None
        assert second.snapshot()["proof_backoff"]["reason"] == reason
        # Existing work stays owned; children must also honor the host pause.
        current[0] = healthy
        count = len(calls)
        assert first.try_acquire("hammer", memory_mb=100, parent=parent) is None
        assert len(calls) == count
        clock[0] += 1.9
        assert second.try_acquire("hammer", memory_mb=100) is None
        clock[0] += 0.2
        with second.acquire("hammer", memory_mb=100, timeout=0):
            pass
        assert second.snapshot()["proof_backoff"] == {}
    assert first.snapshot()["waiting_request_count"] == 0


def test_admission_queue_is_bounded_and_cancellation_cleans_it(tmp_path):
    config = ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json",
        proof_resource_sampler=lambda: ProofHostResources(8, 1000, 0),
        lane_reservations={}, max_waiting_requests=1,
    )
    scheduler = GlobalResourceScheduler(config)
    cancel = threading.Event()
    errors = []
    def wait():
        try:
            scheduler.acquire("hammer", memory_mb=100, cancel_event=cancel, timeout=2)
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=wait)
    thread.start()
    try:
        deadline = time.monotonic() + 1
        while scheduler.snapshot()["waiting_request_count"] == 0 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert scheduler.snapshot()["waiting_request_count"] == 1
        with pytest.raises(ResourceUnavailableError, match="queue is full"):
            scheduler.acquire("hammer", memory_mb=100, timeout=0)
    finally:
        cancel.set()
        thread.join(2)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], LeaseCancelledError)
    assert scheduler.snapshot()["waiting_request_count"] == 0


@pytest.mark.parametrize("budget_mb", [600, None])
def test_hammer_safe_profile_sizes_portfolio_and_defaults_budgets(tmp_path, budget_mb):
    from ipfs_datasets_py.logic.hammers.models import HammerPolicy, TranslationRecord, TranslationStatus, TranslationTarget
    from ipfs_datasets_py.logic.hammers.policy import PortfolioPolicy, PolicyError
    from ipfs_datasets_py.logic.hammers.portfolio import SolverPortfolio, PortfolioAttemptSpec, SolverProcessOutcome
    scheduler = _scheduler(tmp_path, lambda: ProofHostResources(8, 1000, 1000))
    executable = tmp_path / "z3"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    policy = PortfolioPolicy(
        hammer_policy=HammerPolicy(timeout_seconds=5, memory_mb=budget_mb, allowed_solvers=["z3"]),
        executable_overrides={"z3": str(executable)}, max_parallel_processes=4,
        cancel_on_first_conclusive=False,
    )
    observed = []
    process_slots = []
    def runner(command, **kwargs):
        observed.append(scheduler.snapshot()["allocated"])
        process_slots.append(scheduler.snapshot()["allocated_child_process_slots"])
        return SolverProcessOutcome(command=command, stdout="unknown\n")
    portfolio = SolverPortfolio(policy, process_runner=runner, version_prober=lambda *_: None,
                                resource_scheduler=scheduler, resource_wait_timeout_seconds=1)
    attempts = [PortfolioAttemptSpec(translation=TranslationRecord(
        translation_id=f"translation-{index}", request_id="request",
        target=TranslationTarget.SMTLIB, status=TranslationStatus.SUPPORTED,
        source_construct="goal", translated_text="(assert true)",
    ), solver_name="z3") for index in range(2)]
    result = portfolio.run("request", attempts)
    assert len(result.attempts) == 2
    assert result.resource_telemetry["portfolio_cpu_slots"] == 1
    effective_memory = 600 if budget_mb is not None else 800
    assert all(value["memory_mb"] == effective_memory and value["cpu_slots"] == 1 for value in observed)
    assert process_slots == [1, 1]
    assert scheduler.snapshot()["active_lease_count"] == 0
