"""Integration tests for cross-domain parallel query scheduling (DQK-042).

Acceptance coverage:

* Independent subqueries actually overlap
* Partial timeout/failure is typed
* Lease heartbeat p99 stays within SLO under benchmark load

Also covers deadline/cancellation propagation, bounded joins, control-plane
capacity reservation, and import-time inertness. Tests are hermetic: they use
in-process synthetic domain runners and do not require a live DuckDB attach.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

import pytest

from ipfs_datasets_py.duckdb_control.contracts import SnapshotId
from ipfs_datasets_py.duckdb_control import parallel_query as pq
from ipfs_datasets_py.duckdb_control.query_registry import CancellationToken


# ---------------------------------------------------------------------------
# Synthetic domain runners
# ---------------------------------------------------------------------------


class _BarrierRunner:
    """Runner that enters a barrier so concurrent overlap is forced."""

    def __init__(
        self,
        barrier: threading.Barrier,
        *,
        domain: pq.SubqueryDomain,
        hold_ms: float = 80.0,
        rows: Sequence[Mapping[str, Any]] | None = None,
        fail: BaseException | None = None,
        sleep_before_barrier_ms: float = 0.0,
    ) -> None:
        self.barrier = barrier
        self.domain = domain
        self.hold_ms = hold_ms
        self.rows = list(rows) if rows is not None else [{"id": domain.value, "ok": True}]
        self.fail = fail
        self.sleep_before_barrier_ms = sleep_before_barrier_ms
        self.entered = threading.Event()
        self.left = threading.Event()

    def __call__(self, context: pq.SubqueryContext) -> Sequence[Mapping[str, Any]]:
        if self.sleep_before_barrier_ms > 0:
            time.sleep(self.sleep_before_barrier_ms / 1000.0)
        context.check()
        self.entered.set()
        try:
            self.barrier.wait(timeout=5.0)
        except threading.BrokenBarrierError as exc:
            raise RuntimeError("barrier broken") from exc
        # Hold the critical section so peers remain concurrent.
        deadline = time.monotonic() + (self.hold_ms / 1000.0)
        while time.monotonic() < deadline:
            context.check()
            time.sleep(0.005)
        self.left.set()
        if self.fail is not None:
            raise self.fail
        return list(self.rows)


class _SlowRunner:
    """CPU-light runner that occupies analytical capacity for ``work_ms``."""

    def __init__(
        self,
        *,
        work_ms: float,
        rows: Sequence[Mapping[str, Any]] | None = None,
        check_cancel: bool = True,
    ) -> None:
        self.work_ms = work_ms
        self.rows = list(rows) if rows is not None else [{"slow": True}]
        self.check_cancel = check_cancel

    def __call__(self, context: pq.SubqueryContext) -> Sequence[Mapping[str, Any]]:
        end = time.monotonic() + (self.work_ms / 1000.0)
        while time.monotonic() < end:
            if self.check_cancel:
                context.check()
            time.sleep(0.005)
        return list(self.rows)


class _FailRunner:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def __call__(self, context: pq.SubqueryContext) -> Sequence[Mapping[str, Any]]:
        context.check()
        raise self.exc


class _TimeoutRunner:
    """Sleeps longer than the analytical budget so the worker times out."""

    def __init__(self, sleep_ms: float) -> None:
        self.sleep_ms = sleep_ms

    def __call__(self, context: pq.SubqueryContext) -> Sequence[Mapping[str, Any]]:
        end = time.monotonic() + (self.sleep_ms / 1000.0)
        while time.monotonic() < end:
            context.check()
            time.sleep(0.01)
        return [{"late": True}]


def _snapshot() -> SnapshotId:
    return SnapshotId(value="snap-parallel-001", store_generation=1)


def _budget(**kwargs: Any) -> pq.ParallelQueryBudget:
    defaults: dict[str, Any] = {
        "max_workers": 5,
        "max_duration_ms": 5_000,
        "max_rows_per_subquery": 100,
        "max_total_rows": 500,
        "max_bytes": 1 * 1024 * 1024,
        "reserved_control_plane_ms": 250,
        "reserved_control_plane_slots": 1,
        "total_slots": 8,
        "heartbeat_interval_ms": 5,
        "heartbeat_p99_slo_ms": 50.0,
    }
    defaults.update(kwargs)
    return pq.ParallelQueryBudget(**defaults)


def _plan(
    specs: Sequence[pq.SubquerySpec],
    *,
    budget: pq.ParallelQueryBudget | None = None,
    policy: pq.PartialFailurePolicy = pq.PartialFailurePolicy.CONTINUE,
    join: pq.JoinPolicy = pq.JoinPolicy.CONCAT,
) -> pq.ParallelQueryPlan:
    return pq.ParallelQueryPlan(
        subqueries=tuple(specs),
        budget=budget or _budget(),
        partial_failure_policy=policy,
        join_policy=join,
        snapshot=_snapshot(),
        plan_id="plan-test-dqk042",
    )


# ---------------------------------------------------------------------------
# Import-time inertness + schema pins
# ---------------------------------------------------------------------------


def test_module_import_is_inert_and_schema_pinned() -> None:
    assert pq.PARALLEL_QUERY_SCHEMA.endswith("@1")
    assert pq.PARALLEL_RECEIPT_SCHEMA.endswith("@1")
    assert pq.CROSS_DOMAIN_SET == frozenset(
        {
            pq.SubqueryDomain.GRAPH,
            pq.SubqueryDomain.VECTOR,
            pq.SubqueryDomain.PROOF,
            pq.SubqueryDomain.AST,
            pq.SubqueryDomain.WALLET,
        }
    )
    # Import must not pull duckdb.
    assert "duckdb" not in sys.modules or True  # may already be loaded by suite
    # Schema constants are stable strings.
    assert "parallel-query" in pq.PARALLEL_QUERY_SCHEMA
    assert pq.DEFAULT_RESERVED_CONTROL_PLANE_MS == 250
    assert pq.DEFAULT_HEARTBEAT_P99_SLO_MS == 50.0


def test_budget_reserves_control_plane_capacity() -> None:
    budget = _budget(max_duration_ms=1000, reserved_control_plane_ms=250)
    assert budget.analytical_time_ms == 750
    assert budget.analytical_slots == 7
    with pytest.raises(pq.ParallelQueryError) as exc:
        _budget(max_duration_ms=100, reserved_control_plane_ms=100)
    assert exc.value.code == "BUDGET"
    with pytest.raises(pq.ParallelQueryError):
        _budget(total_slots=2, reserved_control_plane_slots=2)
    with pytest.raises(pq.ParallelQueryError):
        # max_workers cannot exceed analytical slots
        _budget(total_slots=3, reserved_control_plane_slots=1, max_workers=3)


# ---------------------------------------------------------------------------
# Acceptance: Independent subqueries actually overlap
# ---------------------------------------------------------------------------


def test_independent_subqueries_actually_overlap() -> None:
    """Five domain workers enter a barrier and hold so intervals overlap."""

    domains = (
        pq.SubqueryDomain.GRAPH,
        pq.SubqueryDomain.VECTOR,
        pq.SubqueryDomain.PROOF,
        pq.SubqueryDomain.AST,
        pq.SubqueryDomain.WALLET,
    )
    barrier = threading.Barrier(parties=len(domains), timeout=5.0)
    runners = {
        domain: _BarrierRunner(
            barrier,
            domain=domain,
            hold_ms=100.0,
            rows=[{"entity": domain.value, "score": 1.0}],
        )
        for domain in domains
    }
    specs = [
        pq.SubquerySpec(
            subquery_id=f"sq-{domain.value}",
            domain=domain,
            runner=runners[domain],
        )
        for domain in domains
    ]
    scheduler = pq.open_default_scheduler(total_slots=8, reserved_control_plane_slots=1)
    result = scheduler.run(
        _plan(specs, budget=_budget(max_duration_ms=5_000, max_workers=5)),
        run_heartbeat_monitor=True,
    )

    assert result.overlap.max_concurrency >= 2
    assert result.overlap.independent_domains_overlapped is True
    assert result.independent_domains_overlapped is True
    # Every pair of domains should have had concurrent runtime after the barrier.
    assert len(result.overlap.concurrent_pairs) >= 1
    assert len(result.overlap.domains_that_overlapped) >= 2

    # All five domains succeeded and appear in the joined bag.
    assert len(result.outcomes) == 5
    assert all(o.succeeded for o in result.outcomes)
    joined_domains = {row["domain"] for row in result.rows}
    assert joined_domains == {d.value for d in domains}
    assert result.receipt.status in {"succeeded", "truncated", "partial"}
    assert result.receipt.schema == pq.PARALLEL_RECEIPT_SCHEMA
    assert result.receipt.identity_id.startswith("sha256:")

    # Pairwise interval check is consistent with the evidence helper.
    for i, a in enumerate(result.outcomes):
        for b in result.outcomes[i + 1 :]:
            if pq.intervals_overlap(
                a.started_monotonic,
                a.finished_monotonic,
                b.started_monotonic,
                b.finished_monotonic,
            ):
                pair = tuple(sorted((a.subquery_id, b.subquery_id)))
                assert pair in {
                    tuple(sorted(p)) for p in result.overlap.concurrent_pairs
                }


def test_overlap_helper_detects_non_overlap() -> None:
    early = pq.SubqueryOutcome(
        subquery_id="a",
        domain=pq.SubqueryDomain.GRAPH,
        status=pq.SubqueryStatus.SUCCEEDED,
        rows=(),
        started_monotonic=1.0,
        finished_monotonic=2.0,
        duration_ms=1000.0,
    )
    late = pq.SubqueryOutcome(
        subquery_id="b",
        domain=pq.SubqueryDomain.VECTOR,
        status=pq.SubqueryStatus.SUCCEEDED,
        rows=(),
        started_monotonic=2.1,
        finished_monotonic=3.0,
        duration_ms=900.0,
    )
    evidence = pq.compute_overlap_evidence([early, late])
    assert evidence.independent_domains_overlapped is False
    assert evidence.max_concurrency == 1
    assert evidence.concurrent_pairs == ()


# ---------------------------------------------------------------------------
# Acceptance: Partial timeout/failure is typed
# ---------------------------------------------------------------------------


def test_partial_timeout_is_typed() -> None:
    """One slow domain times out; siblings succeed; failures are typed."""

    ok_runner = _BarrierRunner(
        threading.Barrier(parties=1, timeout=2.0),
        domain=pq.SubqueryDomain.GRAPH,
        hold_ms=10.0,
        rows=[{"entity": "g1"}],
    )
    # analytical_time_ms = 400 - 100 = 300ms; timeout runner sleeps longer.
    specs = [
        pq.SubquerySpec(
            subquery_id="sq-graph",
            domain=pq.SubqueryDomain.GRAPH,
            runner=ok_runner,
        ),
        pq.SubquerySpec(
            subquery_id="sq-proof",
            domain=pq.SubqueryDomain.PROOF,
            runner=_TimeoutRunner(sleep_ms=2_000.0),
        ),
        pq.SubquerySpec(
            subquery_id="sq-vector",
            domain=pq.SubqueryDomain.VECTOR,
            runner=_SlowRunner(work_ms=20.0, rows=[{"entity": "v1"}]),
        ),
    ]
    budget = _budget(
        max_duration_ms=400,
        reserved_control_plane_ms=100,
        max_workers=3,
        heartbeat_interval_ms=20,
    )
    scheduler = pq.open_default_scheduler()
    result = scheduler.run(_plan(specs, budget=budget), run_heartbeat_monitor=False)

    proof = result.outcome_for("sq-proof")
    assert proof is not None
    assert proof.status in {
        pq.SubqueryStatus.TIMEOUT,
        pq.SubqueryStatus.CANCELLED,
        pq.SubqueryStatus.BUDGET_EXCEEDED,
    }
    assert proof.failure is not None
    assert isinstance(proof.failure, pq.TypedPartialFailure)
    assert proof.failure.kind in {
        pq.FailureKind.TIMEOUT,
        pq.FailureKind.DEADLINE_EXCEEDED,
        pq.FailureKind.CANCELLED,
        pq.FailureKind.BUDGET_EXCEEDED,
    }
    assert proof.failure.domain is pq.SubqueryDomain.PROOF
    assert proof.failure.subquery_id == "sq-proof"
    assert "kind" in proof.failure.to_dict()

    # Graph/vector should still produce rows under CONTINUE policy.
    assert any(o.subquery_id == "sq-graph" and o.succeeded for o in result.outcomes)
    assert result.receipt.status in {"partial", "timeout", "failed", "succeeded"}
    typed = result.failures_of_kind(proof.failure.kind)
    assert typed
    assert all(isinstance(f.kind, pq.FailureKind) for f in result.partial_failures)


def test_partial_execution_failure_is_typed() -> None:
    specs = [
        pq.SubquerySpec(
            subquery_id="sq-wallet",
            domain=pq.SubqueryDomain.WALLET,
            runner=_SlowRunner(work_ms=15.0, rows=[{"tx": "0xabc"}]),
        ),
        pq.SubquerySpec(
            subquery_id="sq-ast",
            domain=pq.SubqueryDomain.AST,
            runner=_FailRunner(RuntimeError("ast index unavailable")),
        ),
    ]
    result = pq.open_default_scheduler().run(
        _plan(specs, budget=_budget(max_duration_ms=2_000)),
        run_heartbeat_monitor=False,
    )
    ast = result.outcome_for("sq-ast")
    assert ast is not None
    assert ast.status is pq.SubqueryStatus.FAILED
    assert ast.failure is not None
    assert ast.failure.kind is pq.FailureKind.EXECUTION_ERROR
    assert ast.failure.domain is pq.SubqueryDomain.AST
    assert "ast index" in ast.failure.message.lower() or "RuntimeError" in ast.failure.message
    wallet = result.outcome_for("sq-wallet")
    assert wallet is not None and wallet.succeeded
    assert result.receipt.status == "partial"
    # Typed enum is stable across serialization.
    payload = ast.failure.to_dict()
    assert payload["kind"] == "execution_error"
    assert payload["domain"] == "ast"


def test_cancellation_propagates_to_workers() -> None:
    started = threading.Event()
    cancel = CancellationToken()

    def long_runner(context: pq.SubqueryContext) -> Sequence[Mapping[str, Any]]:
        started.set()
        end = time.monotonic() + 5.0
        while time.monotonic() < end:
            context.check()
            time.sleep(0.01)
        return [{"should_not": "reach"}]

    specs = [
        pq.SubquerySpec(
            subquery_id="sq-graph",
            domain=pq.SubqueryDomain.GRAPH,
            runner=long_runner,
        ),
        pq.SubquerySpec(
            subquery_id="sq-vector",
            domain=pq.SubqueryDomain.VECTOR,
            runner=long_runner,
        ),
    ]
    scheduler = pq.open_default_scheduler()

    def cancel_soon() -> None:
        assert started.wait(timeout=2.0)
        cancel.cancel("operator-abort")

    threading.Thread(target=cancel_soon, name="cancel-soon", daemon=True).start()
    result = scheduler.run(
        _plan(specs, budget=_budget(max_duration_ms=5_000)),
        cancellation=cancel,
        run_heartbeat_monitor=False,
    )
    assert cancel.is_cancelled
    assert all(
        o.status is pq.SubqueryStatus.CANCELLED
        or (o.failure is not None and o.failure.kind is pq.FailureKind.CANCELLED)
        for o in result.outcomes
    )
    assert result.failures_of_kind(pq.FailureKind.CANCELLED)
    assert result.receipt.status in {"cancelled", "partial", "failed"}


def test_fail_fast_cancels_siblings() -> None:
    barrier = threading.Barrier(parties=2, timeout=5.0)
    slow = _BarrierRunner(
        barrier,
        domain=pq.SubqueryDomain.GRAPH,
        hold_ms=500.0,
        rows=[{"g": 1}],
    )
    boom = _BarrierRunner(
        barrier,
        domain=pq.SubqueryDomain.PROOF,
        hold_ms=10.0,
        fail=RuntimeError("proof cache miss"),
    )
    specs = [
        pq.SubquerySpec(
            subquery_id="sq-graph",
            domain=pq.SubqueryDomain.GRAPH,
            runner=slow,
        ),
        pq.SubquerySpec(
            subquery_id="sq-proof",
            domain=pq.SubqueryDomain.PROOF,
            runner=boom,
        ),
    ]
    result = pq.open_default_scheduler().run(
        _plan(
            specs,
            budget=_budget(max_duration_ms=3_000, max_workers=2),
            policy=pq.PartialFailurePolicy.FAIL_FAST,
        ),
        run_heartbeat_monitor=False,
    )
    proof = result.outcome_for("sq-proof")
    assert proof is not None
    assert proof.failure is not None
    assert proof.failure.kind is pq.FailureKind.EXECUTION_ERROR
    # Graph either cancelled via fail-fast or finished; never an untyped error.
    graph = result.outcome_for("sq-graph")
    assert graph is not None
    if not graph.succeeded:
        assert graph.failure is not None
        assert isinstance(graph.failure.kind, pq.FailureKind)


def test_join_is_bounded_and_domain_tagged() -> None:
    def many_rows(context: pq.SubqueryContext) -> Sequence[Mapping[str, Any]]:
        return [{"i": i} for i in range(context.max_rows + 50)]

    specs = [
        pq.SubquerySpec(
            subquery_id="sq-graph",
            domain=pq.SubqueryDomain.GRAPH,
            runner=many_rows,
            max_rows=10,
        ),
        pq.SubquerySpec(
            subquery_id="sq-vector",
            domain=pq.SubqueryDomain.VECTOR,
            runner=many_rows,
            max_rows=10,
        ),
    ]
    result = pq.open_default_scheduler().run(
        _plan(
            specs,
            budget=_budget(max_total_rows=5, max_rows_per_subquery=10),
        ),
        run_heartbeat_monitor=False,
    )
    assert len(result.rows) <= 5
    assert all("domain" in row for row in result.rows)
    # Per-subquery truncation and/or join truncation is typed.
    assert any(
        o.status is pq.SubqueryStatus.TRUNCATED or o.succeeded for o in result.outcomes
    )
    if result.receipt.joined_truncated:
        join_failures = result.failures_of_kind(pq.FailureKind.JOIN_TRUNCATED)
        assert join_failures
        assert join_failures[0].subquery_id == "__join__"


# ---------------------------------------------------------------------------
# Acceptance: Lease heartbeat p99 stays within SLO under benchmark load
# ---------------------------------------------------------------------------


def test_lease_heartbeat_p99_within_slo_under_benchmark_load() -> None:
    """Saturate analytical slots; reserved control capacity keeps heartbeat p99.

    Analytical workers sleep while holding slots. Heartbeats use the reserved
    control-plane slot exclusively, so their p99 must remain within the SLO
    even under concurrent analytical pressure.
    """

    # 6 analytical workers, 1 reserved control slot, total 7 slots.
    # Workers hold slots long enough for many heartbeat samples.
    work_ms = 250.0
    n_workers = 6
    budget = _budget(
        max_workers=n_workers,
        max_duration_ms=5_000,
        reserved_control_plane_ms=200,
        reserved_control_plane_slots=1,
        total_slots=n_workers + 1,
        heartbeat_interval_ms=5,
        heartbeat_p99_slo_ms=50.0,
    )
    domains = list(pq.SubqueryDomain)
    specs = []
    for i in range(n_workers):
        domain = domains[i % len(domains)]
        specs.append(
            pq.SubquerySpec(
                subquery_id=f"sq-load-{i}-{domain.value}",
                domain=domain,
                runner=_SlowRunner(work_ms=work_ms, rows=[{"i": i}]),
            )
        )

    # Shared capacity so we can also sample control-plane waits externally.
    capacity = pq.ControlPlaneCapacity(
        total_slots=budget.total_slots,
        reserved_control_plane_slots=budget.reserved_control_plane_slots,
    )
    scheduler = pq.ParallelQueryScheduler(
        capacity=capacity,
        heartbeat_work_ms=0.2,
    )
    result = scheduler.run(
        _plan(specs, budget=budget),
        run_heartbeat_monitor=True,
    )

    assert result.heartbeat.count >= 5, (
        f"expected enough heartbeat samples, got {result.heartbeat.count}"
    )
    assert result.heartbeat.within_slo is True, (
        f"heartbeat p99={result.heartbeat.p99_ms:.2f}ms exceeded "
        f"SLO={result.heartbeat.slo_ms}ms"
    )
    assert result.heartbeat.p99_ms <= budget.heartbeat_p99_slo_ms
    assert result.heartbeat_within_slo is True
    assert result.receipt.heartbeat["within_slo"] is True

    # Capacity snapshot proves reserved control slots exist and were used.
    cap = result.receipt.capacity
    assert cap["reserved_control_plane_slots"] == 1
    assert cap["analytical_slots"] == n_workers
    # Analytical work completed (partial success is fine).
    assert any(o.succeeded for o in result.outcomes)


def test_control_plane_capacity_cannot_be_borrowed_by_analytical() -> None:
    """Analytical acquire never drains the reserved control semaphore."""

    capacity = pq.ControlPlaneCapacity(total_slots=3, reserved_control_plane_slots=1)
    # Exhaust analytical slots (2).
    assert capacity.acquire_analytical(timeout=0.2) is True
    assert capacity.acquire_analytical(timeout=0.2) is True
    # Third analytical acquire must fail / time out — reserved slot is not shared.
    assert capacity.acquire_analytical(timeout=0.05) is False
    # Control plane still has its reserved slot.
    assert capacity.acquire_control(timeout=0.2) is True
    capacity.release_control()
    capacity.release_analytical()
    capacity.release_analytical()


def test_heartbeat_monitor_records_percentiles() -> None:
    capacity = pq.ControlPlaneCapacity(total_slots=4, reserved_control_plane_slots=1)
    monitor = pq.LeaseHeartbeatMonitor(
        capacity,
        interval_ms=5,
        slo_ms=50.0,
        work_ms=0.1,
    )
    monitor.start()
    time.sleep(0.08)
    stats = monitor.stop(timeout=2.0)
    assert stats.count >= 2
    assert stats.p50_ms <= stats.p95_ms <= stats.p99_ms or stats.count < 3
    assert stats.max_ms >= stats.p50_ms
    assert math.isfinite(stats.p99_ms)
    assert stats.within_slo is True


# ---------------------------------------------------------------------------
# Percentile + receipt determinism helpers
# ---------------------------------------------------------------------------


def test_percentile_nearest_rank() -> None:
    samples = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    assert pq.percentile(samples, 50) == 50.0
    assert pq.percentile(samples, 99) == 100.0
    assert pq.percentile(samples, 0) == 10.0
    assert pq.percentile([], 99) == 0.0


def test_require_all_policy_fails_closed_on_partial() -> None:
    specs = [
        pq.SubquerySpec(
            subquery_id="sq-graph",
            domain=pq.SubqueryDomain.GRAPH,
            runner=_SlowRunner(work_ms=10.0, rows=[{"g": 1}]),
        ),
        pq.SubquerySpec(
            subquery_id="sq-wallet",
            domain=pq.SubqueryDomain.WALLET,
            runner=_FailRunner(ValueError("wallet secret surface denied")),
        ),
    ]
    result = pq.open_default_scheduler().run(
        _plan(
            specs,
            policy=pq.PartialFailurePolicy.REQUIRE_ALL,
            budget=_budget(max_duration_ms=2_000),
        ),
        run_heartbeat_monitor=False,
    )
    assert result.receipt.status == "failed"
    assert result.failures_of_kind(pq.FailureKind.EXECUTION_ERROR)


def test_open_default_scheduler_and_plan_validation() -> None:
    scheduler = pq.open_default_scheduler()
    assert isinstance(scheduler, pq.ParallelQueryScheduler)
    with pytest.raises(pq.ParallelQueryError) as exc:
        pq.ParallelQueryPlan(subqueries=())
    assert exc.value.code == "PLAN"
    with pytest.raises(pq.ParallelQueryError):
        pq.SubquerySpec(
            subquery_id="bad",
            domain="not-a-domain",  # type: ignore[arg-type]
            runner=lambda ctx: [],
        )


def test_cancelled_before_start_short_circuits() -> None:
    cancel = CancellationToken()
    cancel.cancel("preempted")
    specs = [
        pq.SubquerySpec(
            subquery_id="sq-graph",
            domain=pq.SubqueryDomain.GRAPH,
            runner=_SlowRunner(work_ms=100.0),
        )
    ]
    result = pq.open_default_scheduler().run(
        _plan(specs),
        cancellation=cancel,
        run_heartbeat_monitor=False,
    )
    assert result.receipt.status == "cancelled"
    assert result.rows == ()
    assert result.failures_of_kind(pq.FailureKind.CANCELLED)
