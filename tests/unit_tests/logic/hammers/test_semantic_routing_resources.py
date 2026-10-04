"""Checked routes keep portfolio and native leaves inside one reservation."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import shutil
import sys
import threading

import pytest

from ipfs_datasets_py.logic.hammers import semantic_routing as routing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


def target(solvers=("z3",)):
    parsed = routing.modal.parse_modal("p and not p", routing.modal.profile_k())
    replay = routing.modal.parse_modal(parsed.printed, routing.modal.profile_k())
    return dict(request_id="shared-parent", source_construct="exact-proposition", logic_family="propositional",
        ast_format="shared_logic", printed=parsed.printed, native_ast=replay.root.to_dict(), solver_names=solvers)


def policy(solvers=("z3",), *, fake=False):
    return routing.policy.PortfolioPolicy(
        hammer_policy=routing.models.HammerPolicy(allowed_solvers=list(solvers), timeout_seconds=3),
        solver_budgets={name: routing.policy.SolverBudget(timeout_seconds=3, cpu_seconds=2, memory_mb=128)
                        for name in solvers},
        executable_overrides={name: sys.executable for name in solvers} if fake else {},
        max_parallel_processes=len(solvers), cancel_on_first_conclusive=False)


@pytest.fixture
def admitted(tmp_path):
    pressure = [ProofHostResources(8, 8192, 8192)]
    owner = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "shared-resources.json", proof_resource_sampler=lambda: pressure[0],
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005, proof_backoff_seconds=.02))
    with owner.acquire("orchestration", cpu_slots=2, memory_mb=512,
                       child_process_slots=2, timeout=0) as parent:
        yield owner, parent, pressure
        assert owner.snapshot()["active_lease_count"] == 1
        assert owner.snapshot()["waiting_request_count"] == 0
    assert owner.snapshot()["active_lease_count"] == 0


def run(parent, *, scheduler=None, cancel=None, wait=.1, solvers=("z3",), fake=False):
    data = target(solvers)
    _, receipt = routing.prepare_family_portfolio(**data)
    return routing.run_family_portfolio(expected_routing=receipt, run_policy=policy(solvers, fake=fake),
        parent_lease=parent, resource_scheduler=scheduler, cancel_event=cancel,
        resource_wait_timeout_seconds=wait, **data)


def intercept_transport(monkeypatch, process_runner):
    implementation = routing.portfolio.SolverPortfolio
    def construct(run_policy, **kwargs):
        return implementation(run_policy, process_runner=process_runner, version_prober=lambda *_: "test-fixture", **kwargs)
    monkeypatch.setattr(routing.portfolio, "SolverPortfolio", construct)
    monkeypatch.setattr(routing.portfolio, "get_global_resource_scheduler",
                        lambda: pytest.fail("parent route allocated or consulted a second global root"))


@pytest.mark.parametrize("token", [False, True])
def test_parent_or_token_has_one_root_and_two_nested_leases(admitted, monkeypatch, token):
    owner, parent, _ = admitted
    observed = []
    def process(command, *, budget, cancel_event):
        snapshot = owner.snapshot()
        assert snapshot["active_root_lease_count"] == 1
        assert snapshot["active_child_lease_count"] == 2
        assert snapshot["allocated"] == {"cpu_slots": 2, "memory_mb": 512}
        assert snapshot["allocated_child_process_slots"] == 2
        assert not cancel_event.is_set()
        observed.append(budget.memory_mb)
        return routing.portfolio.SolverProcessOutcome(command, stdout="unsat\n", returncode=0)
    intercept_transport(monkeypatch, process)
    result = run(parent.token if token else parent, scheduler=owner if token else None, fake=True)
    assert observed == [128]
    assert result.attempts[0].verdict is routing.models.SolverVerdict.UNSAT
    assert not parent.released and not parent.cancelled
    assert result.resource_telemetry["scheduler"]["active_root_lease_count"] == 1


@pytest.mark.parametrize("cancel_owner", [False, True])
def test_external_or_parent_cancellation_reaches_leaf_and_cleans_children(admitted, monkeypatch, cancel_owner):
    owner, parent, _ = admitted
    event, started = threading.Event(), threading.Event()
    def process(command, *, budget, cancel_event):
        started.set()
        assert cancel_event.wait(2), "leaf never received external/parent cancellation"
        return routing.portfolio.SolverProcessOutcome(command, cancelled=True)
    intercept_transport(monkeypatch, process)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run, parent, cancel=event, fake=True)
        assert started.wait(2)
        parent.cancel() if cancel_owner else event.set()
        result = future.result(timeout=4)
    assert len(result.cancelled_attempt_ids) == 1
    assert result.attempts[0].verdict is routing.models.SolverVerdict.UNKNOWN
    assert owner.snapshot()["active_lease_count"] == 1


def test_precancelled_request_never_executes_or_leaks_waiter(admitted, monkeypatch):
    owner, parent, _ = admitted
    intercept_transport(monkeypatch, lambda *_args, **_kwargs: pytest.fail("cancelled request launched solver"))
    event = threading.Event()
    event.set()
    with pytest.raises(resources.LeaseCancelledError):
        run(parent, cancel=event, fake=True)
    assert owner.snapshot()["waiting_request_count"] == 0


def test_new_external_pressure_blocks_nested_solver_work(admitted, monkeypatch):
    owner, parent, pressure = admitted
    intercept_transport(monkeypatch, lambda *_args, **_kwargs: pytest.fail("pressure-blocked request launched solver"))
    pressure[0] = ProofHostResources(8, 8192, 128)
    with pytest.raises(resources.LeaseTimeoutError):
        run(parent, fake=True, wait=.03)
    assert owner.snapshot()["waiting_request_count"] == 0


def test_token_cannot_fall_back_to_root_scheduler(admitted, monkeypatch):
    _, parent, _ = admitted
    monkeypatch.setattr(routing.portfolio, "get_global_resource_scheduler", lambda: pytest.fail("root fallback"))
    with pytest.raises(ValueError, match="explicit resource scheduler"):
        run(parent.token, fake=True)


@pytest.mark.parametrize("token", [False, True])
def test_foreign_scheduler_is_rejected_without_allocating(admitted, tmp_path, token):
    owner, parent, _ = admitted
    foreign = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "foreign.json", proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
        lane_reservations={}, auto_renew_leases=False))
    with pytest.raises(ValueError, match="resource scheduler"):
        run(parent.token if token else parent, scheduler=foreign, fake=True)
    assert foreign.snapshot()["active_lease_count"] == 0
    assert owner.snapshot()["active_lease_count"] == 1


@pytest.mark.parametrize("parent", ["lease-id", {}, object()])
def test_untyped_parent_authority_is_rejected(parent):
    with pytest.raises(ValueError, match="native ResourceLease"):
        run(parent, fake=True)


@pytest.mark.parametrize("timeout", [-1, float("nan"), float("inf"), True, "1"])
def test_invalid_admission_budget_is_rejected(timeout):
    with pytest.raises(ValueError, match="wait timeout"):
        run(None, wait=timeout, fake=True)


def test_cancellation_requires_a_real_signal_contract():
    with pytest.raises(ValueError, match="is_set"):
        run(None, cancel=object(), fake=True)


def test_boolean_alias_cannot_mutate_expected_receipt(monkeypatch):
    data = target()
    _, receipt = routing.prepare_family_portfolio(**data)
    receipt = deepcopy(receipt)
    receipt["qualified"] = 0
    monkeypatch.setattr(routing.portfolio, "SolverPortfolio", lambda *a, **k: pytest.fail("mutated receipt executed"))
    with pytest.raises(ValueError, match="routing changed"):
        routing.run_family_portfolio(expected_routing=receipt, run_policy=policy(), **data)


@pytest.mark.skipif(not shutil.which("z3") or not shutil.which("cvc5"), reason="native Z3/CVC5 unavailable")
def test_native_checked_z3_cvc5_share_existing_root(admitted, monkeypatch):
    owner, parent, _ = admitted
    original = owner.acquire
    acquired = []
    def acquire(*args, **kwargs):
        lease = original(*args, **kwargs)
        acquired.append((lease.lease_id, lease.parent_lease_id, owner.snapshot()))
        return lease
    monkeypatch.setattr(owner, "acquire", acquire)
    monkeypatch.setattr(routing.portfolio, "get_global_resource_scheduler", lambda: pytest.fail("root fallback"))
    result = run(parent, solvers=("z3", "cvc5"), wait=2)
    assert result.denied == [] and len(result.attempts) == 2
    assert all(row.verdict is routing.models.SolverVerdict.UNSAT and row.solver_version for row in result.attempts)
    assert len(acquired) == 3
    portfolio_id = acquired[0][0]
    assert acquired[0][1] == parent.lease_id
    assert all(row[1] == portfolio_id for row in acquired[1:])
    assert all(row[2]["active_root_lease_count"] == 1 for row in acquired)
    assert all(row[2]["allocated"] == {"cpu_slots": 2, "memory_mb": 512} for row in acquired)
    assert owner.snapshot()["active_lease_count"] == 1
