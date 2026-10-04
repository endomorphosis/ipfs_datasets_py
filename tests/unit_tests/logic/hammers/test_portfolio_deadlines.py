"""One finite portfolio deadline covers real shared admission and all attempts."""
from dataclasses import replace
import math
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.hammers import portfolio as module
from ipfs_datasets_py.logic.hammers.models import (
    HammerPolicy, SolverVerdict, TranslationRecord, TranslationStatus, TranslationTarget,
)
from ipfs_datasets_py.logic.hammers.policy import PortfolioPolicy, SolverBudget
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig, LeaseCancelledError, LeaseTimeoutError,
)


@pytest.fixture
def owner(tmp_path):
    healthy = ProofHostResources(8, 8192, 8192)
    pressure = [healthy]
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "portfolio.json", proof_resource_sampler=lambda: pressure[0],
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005,
        proof_backoff_seconds=.005,
    ))
    yield scheduler, pressure, healthy
    assert scheduler.active_leases() == []
    assert scheduler.snapshot()["waiting_request_count"] == 0


def attempts(count=1):
    return [module.PortfolioAttemptSpec(TranslationRecord(
        translation_id=f"t-{i}", request_id="bounded", target=TranslationTarget.SMTLIB,
        status=TranslationStatus.SUPPORTED, source_construct="authored", translated_text="(assert false)"),
        "z3") for i in range(count)]


def portfolio(owner, *, timeout=1.0, runner=None, prober=None, **kwargs):
    policy = PortfolioPolicy(
        hammer_policy=HammerPolicy(allowed_solvers=["z3"], timeout_seconds=timeout),
        solver_budgets={"z3": SolverBudget(timeout_seconds=timeout, memory_mb=128, cpu_seconds=timeout)},
        executable_overrides={"z3": sys.executable}, max_parallel_processes=1,
        cancel_on_first_conclusive=False,
    )
    return module.SolverPortfolio(policy, resource_scheduler=owner,
        process_runner=runner or (lambda *_a, **_k: pytest.fail("unexpected solver launch")),
        version_prober=prober or (lambda *_a: pytest.fail("unexpected version probe")), **kwargs)


@pytest.fixture
def clock(monkeypatch):
    values = [100.0]
    # Only portfolio time is controlled; the actual scheduler retains its real
    # clock, locking, durable state, cancellation and pressure gates.
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: values[0]))
    return values


@pytest.mark.parametrize("field, value", [
    *(('overall_timeout_seconds', item) for item in (0, -1, True, "1", float('nan'), float('inf'))),
    *(('resource_wait_timeout_seconds', item) for item in (-1, True, "1", float('nan'), float('inf'))),
])
def test_invalid_limits_cannot_disable_finite_admission(owner, field, value):
    scheduler, _, _ = owner
    with pytest.raises(ValueError, match=field):
        portfolio(scheduler, **{field: value})


def test_default_policy_deadline_expires_under_persistent_root_pressure(owner, monkeypatch):
    scheduler, pressure, healthy = owner
    pressure[0] = replace(healthy, cpu_stall_percent=90)
    waits = []
    acquire = scheduler.acquire
    def tracked(*args, **kwargs):
        waits.append(kwargs["timeout"])
        return acquire(*args, **kwargs)
    monkeypatch.setattr(scheduler, "acquire", tracked)
    transport = portfolio(scheduler, timeout=.06)
    started = time.monotonic()
    with pytest.raises(LeaseTimeoutError):
        transport.run("bounded", attempts())
    assert time.monotonic() - started < 1
    assert transport.overall_timeout_seconds == .06
    assert len(waits) == 1 and 0 < waits[0] <= .06
    assert scheduler.snapshot()["proof_backoff"]["reason"] == "proof_cpu_stall"


def test_child_pressure_uses_remaining_deadline_and_records_admission_error(owner, monkeypatch):
    scheduler, pressure, healthy = owner
    acquire = scheduler.acquire
    waits = []
    def pressure_after_root(*args, **kwargs):
        waits.append(kwargs["timeout"])
        lease = acquire(*args, **kwargs)
        if kwargs.get("parent_lease") is None:
            pressure[0] = replace(healthy, cpu_stall_percent=90)
        return lease
    monkeypatch.setattr(scheduler, "acquire", pressure_after_root)
    result = portfolio(scheduler, timeout=.08).run("bounded", attempts())
    assert len(waits) == 2 and 0 < waits[1] < waits[0] <= .08
    assert result.attempts[0].verdict is SolverVerdict.ERROR
    assert result.attempts[0].resource_usage["native_execution_started"] is False
    assert result.resource_telemetry["overall_deadline_exceeded"]


@pytest.mark.parametrize("parent_token", [False, True])
def test_pressure_cancellation_keeps_supplied_parent_and_releases_waiter(owner, monkeypatch, parent_token):
    scheduler, pressure, healthy = owner
    with scheduler.acquire("outer", cpu_slots=1, memory_mb=256, child_process_slots=1, timeout=0) as parent:
        pressure[0] = replace(healthy, cpu_stall_percent=90)
        cancel = threading.Event()
        sample = scheduler.config.proof_resource_sampler
        calls = []
        def cancelling_sample():
            calls.append(True)
            cancel.set()
            return sample()
        monkeypatch.setattr(scheduler.config, "proof_resource_sampler", cancelling_sample)
        with pytest.raises(LeaseCancelledError):
            portfolio(scheduler).run("bounded", attempts(),
                parent_lease=parent.token if parent_token else parent, cancel_event=cancel)
        assert calls and not parent.released and not parent.cancelled
        assert scheduler.snapshot()["active_lease_count"] == 1


def test_pressure_recovery_runs_with_one_remaining_budget(owner, monkeypatch):
    scheduler, pressure, healthy = owner
    pressure[0] = replace(healthy, cpu_stall_percent=90)
    seen = threading.Event()
    sample = scheduler.config.proof_resource_sampler
    def observed_pressure():
        result = sample()
        if result.cpu_stall_percent:
            seen.set()
        return result
    monkeypatch.setattr(scheduler.config, "proof_resource_sampler", observed_pressure)
    def recover():
        assert seen.wait(1)
        pressure[0] = healthy
    worker = threading.Thread(target=recover)
    observed = []
    def run(command, *, budget, cancel_event):
        observed.append(budget.timeout_seconds)
        return module.SolverProcessOutcome(command, stdout="unsat", returncode=0)
    worker.start()
    try:
        result = portfolio(scheduler, timeout=.5, runner=run, prober=lambda *_: "test").run("bounded", attempts())
        assert result.attempts[0].verdict is SolverVerdict.UNSAT
        assert len(observed) == 1 and 0 < observed[0] < .5
    finally:
        pressure[0] = healthy
        worker.join(2)
    assert not worker.is_alive()


@pytest.mark.parametrize("stage", ["root", "child"])
@pytest.mark.parametrize("limit", ["overall", "wait_cap"])
def test_late_actual_grant_is_released_before_any_probe(owner, monkeypatch, clock, stage, limit):
    scheduler, _, _ = owner
    acquire = scheduler.acquire
    def late(*args, **kwargs):
        lease = acquire(*args, **kwargs)
        if (kwargs.get("parent_lease") is None) == (stage == "root"):
            clock[0] += 2 if limit == "overall" else .2
        return lease
    monkeypatch.setattr(scheduler, "acquire", late)
    transport = portfolio(scheduler, resource_wait_timeout_seconds=.1 if limit == "wait_cap" else None)
    if stage == "root":
        with pytest.raises(LeaseTimeoutError, match="admission exceeded"):
            transport.run("bounded", attempts())
    else:
        result = transport.run("bounded", attempts())
        assert result.attempts[0].verdict is SolverVerdict.ERROR
        assert not result.attempts[0].resource_usage["native_execution_started"]


def test_zero_wait_cap_allows_immediate_healthy_grants_with_finite_execution(owner, monkeypatch):
    scheduler, _, _ = owner
    waits = []
    acquire = scheduler.acquire
    def tracked(*args, **kwargs):
        waits.append(kwargs["timeout"])
        return acquire(*args, **kwargs)
    monkeypatch.setattr(scheduler, "acquire", tracked)
    observed = []
    def run(command, *, budget, cancel_event):
        observed.append(budget.timeout_seconds)
        return module.SolverProcessOutcome(command, stdout="sat")
    result = portfolio(scheduler, resource_wait_timeout_seconds=0, runner=run,
        prober=lambda *_: "test").run("bounded", attempts())
    assert waits == [0, 0]
    assert result.attempts[0].verdict is SolverVerdict.SAT
    assert 0 < observed[0] <= 1


def test_admission_and_probe_reduce_native_time_but_keep_per_solver_cap(owner, monkeypatch, clock):
    scheduler, _, _ = owner
    acquire = scheduler.acquire
    def delayed(*args, **kwargs):
        lease = acquire(*args, **kwargs)
        clock[0] += .3 if kwargs.get("parent_lease") is None else .2
        return lease
    monkeypatch.setattr(scheduler, "acquire", delayed)
    def probe(*_):
        clock[0] += .1
        return "test"
    observed = []
    def run(command, *, budget, cancel_event):
        observed.append(budget)
        return module.SolverProcessOutcome(command, stdout="unsat")
    result = portfolio(scheduler, runner=run, prober=probe).run("bounded", attempts())
    assert result.attempts[0].verdict is SolverVerdict.UNSAT
    assert observed[0].timeout_seconds == pytest.approx(.4)
    assert observed[0].cpu_seconds == pytest.approx(.4)
    assert result.attempts[0].timeout_seconds == pytest.approx(.5)
    assert result.attempts[0].resource_usage["configured_solver_timeout_seconds"] == 1


def test_expired_probe_cannot_launch_solver_or_refresh_budget(owner, clock):
    scheduler, _, _ = owner
    def probe(*_):
        clock[0] += 2
        return "test"
    result = portfolio(scheduler, prober=probe).run("bounded", attempts())
    assert result.attempts[0].verdict is SolverVerdict.TIMEOUT
    assert not result.attempts[0].resource_usage["native_execution_started"]


def test_larger_explicit_overall_budget_preserves_each_solver_execution_cap(owner, clock):
    scheduler, _, _ = owner
    observed = []
    def run(command, *, budget, cancel_event):
        observed.append(budget.timeout_seconds)
        clock[0] += .6
        return module.SolverProcessOutcome(command, stdout="unknown", wall_time_seconds=.6)
    result = portfolio(scheduler, overall_timeout_seconds=2, runner=run,
        prober=lambda *_: "test").run("bounded", attempts(3))
    assert len(observed) == 3 and all(0 < value <= 1 for value in observed)
    assert observed == pytest.approx([1, 1, .8])
    assert all(row.verdict is SolverVerdict.UNKNOWN for row in result.attempts)
    assert not result.resource_telemetry["overall_deadline_exceeded"]


@pytest.mark.parametrize("field", ["timeout_seconds", "cpu_seconds"])
def test_nonfinite_solver_budget_is_refused_before_admission_or_native_launch(owner, field):
    scheduler, _, _ = owner
    transport = portfolio(scheduler)
    transport.policy.solver_budgets["z3"] = replace(transport.policy.solver_budgets["z3"],
        **{field: float('nan')})
    with pytest.raises(module.PolicyError, match="finite and positive"):
        transport.run("bounded", attempts())


def test_native_version_probe_does_not_round_up_tiny_remaining_time(monkeypatch):
    observed = []
    def run(command, **kwargs):
        observed.append(kwargs["limits"])
        return SimpleNamespace(error=None, timed_out=False, cancelled=False,
            stdout="bounded-version", stderr="")
    monkeypatch.setattr(module, "get_process_supervisor", lambda: SimpleNamespace(run=run))
    assert module._probe_solver_version(sys.executable, module.solver_spec("z3"),
        timeout=.0000005, memory_mb=128, cpu_seconds=.0000005) == "bounded-version"
    assert observed[0].wall_time_seconds == .0000005


@pytest.mark.parametrize("interrupt", ["deadline", "cancel"])
def test_late_conclusive_output_is_evidence_only_and_queued_attempts_do_not_launch(owner, clock, interrupt):
    scheduler, _, _ = owner
    cancel = threading.Event()
    launched = []
    def run(command, *, budget, cancel_event):
        assert math.isfinite(budget.timeout_seconds) and budget.timeout_seconds > 0
        launched.append(command)
        if interrupt == "deadline":
            clock[0] += 2
        else:
            cancel.set()
        return module.SolverProcessOutcome(command, stdout="unsat", returncode=0)
    result = portfolio(scheduler, runner=run, prober=lambda *_: "test").run(
        "bounded", attempts(3), cancel_event=cancel)
    assert len(launched) == 1 and len(result.attempts) == 3
    assert all(row.verdict not in (SolverVerdict.SAT, SolverVerdict.UNSAT) for row in result.attempts)
    assert result.evidence[result.attempts[0].attempt_id].raw_stdout == "unsat"
    assert result.attempts[0].verdict is (SolverVerdict.TIMEOUT if interrupt == "deadline" else SolverVerdict.UNKNOWN)
    if interrupt == "deadline":
        assert all(row.verdict is SolverVerdict.ERROR for row in result.attempts[1:])
    else:
        assert len(result.cancelled_attempt_ids) == 3
