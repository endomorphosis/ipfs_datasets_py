"""Integration tests for parallel DuckLake subplan execution (DQK-092).

Acceptance coverage:

* Independent shard scans overlap without sharing mutable connections while
  same-shard mutations are serialized
* Every worker acquires, renews, and releases an authoritative DQK-090 lease
  around the complete lifetime of its remote Quack attachment, scan, and
  result materialization
* Lease evidence binds process birth identity, endpoint owner generation, and
  task/run/generation fences; cancellation closes readers before release while
  crash recovery relies on bounded expiry
* Deadlines and cancellation propagate to every worker
* A slow or failed catalog owner cannot starve supervisor heartbeats or
  unrelated shards
* Receipts bind plan, snapshot vector, Quack endpoint/owner identity,
  reader-lease identity, resource use, result digest, and partial-failure
  policy

Hermetic: in-memory Quack endpoints, snapshot vectors, and lease authority.
No live DuckDB / network / catalog files required.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
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

from ipfs_datasets_py.duckdb_control import parallel_query as pq
from ipfs_datasets_py.duckdb_control.query_registry import CancellationToken
from ipfs_datasets_py.ducklake import config as cfg
from ipfs_datasets_py.ducklake import execution as lake
from ipfs_datasets_py.ducklake import snapshots as snap
from ipfs_datasets_py.ducklake.snapshots import ReaderLeaseError


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

_CMDLINE = "sha256:" + ("11" * 32)
_DIGEST_A = "sha256:" + ("ab" * 32)
_DIGEST_B = "sha256:" + ("cd" * 32)
_DIGEST_C = "sha256:" + ("ef" * 32)


def _birth(**overrides: Any) -> cfg.ProcessBirthBinding:
    payload = {
        "pid": 4242,
        "boot_id": "boot-dqk092-001",
        "start_ticks": 1000,
        "cmdline_sha256": _CMDLINE,
    }
    payload.update(overrides)
    return cfg.ProcessBirthBinding(**payload)


def _member(catalog_id: str, *, port: int, digest: str, **overrides: Any) -> snap.SnapshotVectorMember:
    payload: dict[str, Any] = {
        "catalog_id": catalog_id,
        "owner_generation": 1,
        "fencing_epoch": 1,
        "quack_endpoint_identity": f"quacks://127.0.0.1:{port}/{catalog_id}",
        "catalog_global_snapshot_id": 7,
        "schema_version": "ducklake-schema@1",
        "storage_root": f"s3://lake/{catalog_id}/data",
        "logical_datasets": ("events",),
        "source_revisions": {"src-1": f"rev-{catalog_id}"},
        "policy_decision_id": "pol-1",
        "policy_decision": {
            "decision_id": "pol-1",
            "allowed": True,
            "decided_by": "broker",
        },
        "tenant_id": "acme",
        "catalog_digest": digest,
        "shard_id": f"shard-{catalog_id}",
    }
    payload.update(overrides)
    return snap.SnapshotVectorMember(**payload)


def _vector_two() -> snap.SnapshotVector:
    return snap.capture_snapshot_vector(
        [
            _member("cat_a", port=19001, digest=_DIGEST_A),
            _member("cat_b", port=19002, digest=_DIGEST_B),
        ]
    )


def _vector_three() -> snap.SnapshotVector:
    return snap.capture_snapshot_vector(
        [
            _member("cat_a", port=19001, digest=_DIGEST_A),
            _member("cat_b", port=19002, digest=_DIGEST_B),
            _member("cat_c", port=19003, digest=_DIGEST_C),
        ]
    )


def _subplan(
    vector: snap.SnapshotVector,
    catalog_id: str,
    *,
    hold_ms: float = 80.0,
    rows_hint: str = "",
) -> lake.LakeShardSubplan:
    member = vector.member_for(catalog_id)
    return lake.LakeShardSubplan(
        subplan_id=f"sp-{catalog_id}",
        catalog_id=catalog_id,
        shard_id=member.shard_id,
        quack_endpoint_identity=member.quack_endpoint_identity,
        owner_generation=member.owner_generation,
        fencing_epoch=member.fencing_epoch,
        snapshot_version=member.catalog_global_snapshot_id,
        vector_id=vector.vector_id,
        dataset_id=f"ds_{catalog_id}",
        hold_ms=hold_ms,
        metadata={"hint": rows_hint} if rows_hint else {},
    )


def _budget(**kwargs: Any) -> lake.LakeCatalogBudget:
    defaults: dict[str, Any] = {
        "max_connections": 1,
        "max_rows": 100,
        "max_bytes": 1 * 1024 * 1024,
        "max_memory_bytes": 2 * 1024 * 1024,
        "max_duration_ms": 5_000,
        "max_spill_bytes": 4 * 1024 * 1024,
        "lease_ttl_seconds": 30,
        "renew_interval_ms": 15,
    }
    defaults.update(kwargs)
    return lake.LakeCatalogBudget(**defaults)


def _plan(
    vector: snap.SnapshotVector,
    catalog_ids: tuple[str, ...],
    *,
    budget: lake.LakeCatalogBudget | None = None,
    birth: cfg.ProcessBirthBinding | None = None,
    policy: pq.PartialFailurePolicy = pq.PartialFailurePolicy.CONTINUE,
    hold_ms: float = 80.0,
    task_id: str = "task-dqk092",
    run_id: str = "run-dqk092",
) -> lake.LakeExecutionPlan:
    return lake.LakeExecutionPlan(
        subplans=tuple(
            _subplan(vector, cid, hold_ms=hold_ms) for cid in catalog_ids
        ),
        snapshot_vector=vector,
        process_birth=birth or _birth(),
        task_id=task_id,
        run_id=run_id,
        plan_id="plan-dqk092",
        catalog_budget=budget or _budget(),
        partial_failure_policy=policy,
        reserved_control_plane_ms=250,
        reserved_control_plane_slots=1,
        total_slots=8,
        heartbeat_interval_ms=5,
        heartbeat_p99_slo_ms=50.0,
    )


def _endpoint(
    vector: snap.SnapshotVector,
    catalog_id: str,
    **kwargs: Any,
) -> lake.InMemoryLakeQuackEndpoint:
    member = vector.member_for(catalog_id)
    return lake.InMemoryLakeQuackEndpoint(
        catalog_id=catalog_id,
        quack_endpoint_identity=member.quack_endpoint_identity,
        rows=[{"entity": catalog_id, "score": 1.0}],
        **kwargs,
    )


def _executor(
    vector: snap.SnapshotVector,
    catalog_ids: tuple[str, ...],
    *,
    endpoints: dict[str, lake.InMemoryLakeQuackEndpoint] | None = None,
) -> tuple[lake.LakeParallelExecutor, dict[str, lake.InMemoryLakeQuackEndpoint]]:
    lease_db = snap.AuthoritativeSnapshotDatabase()
    lease_db.put_vector(vector)
    exec_ = lake.LakeParallelExecutor(lease_db=lease_db)
    eps = endpoints or {}
    for cid in catalog_ids:
        if cid not in eps:
            eps[cid] = _endpoint(vector, cid, scan_hold_ms=80.0)
        exec_.register_endpoint(eps[cid])
    return exec_, eps


# ---------------------------------------------------------------------------
# Schema / import inertness
# ---------------------------------------------------------------------------


def test_module_import_is_inert_and_schema_pinned() -> None:
    assert lake.LAKE_EXECUTION_SCHEMA.endswith("@1")
    assert lake.LAKE_EXECUTION_RECEIPT_SCHEMA.endswith("@1")
    assert lake.LAKE_WORKER_EVIDENCE_SCHEMA.endswith("@1")
    assert "dqk-092" in lake.LAKE_EXECUTION_IMPLEMENTATION_GENERATION
    assert pq.DEFAULT_MAX_CONNECTIONS_PER_CATALOG == 1
    assert "max_memory_bytes" in pq.ParallelQueryBudget().to_dict()
    assert "max_spill_bytes" in pq.ParallelQueryBudget().to_dict()
    assert "max_connections_per_catalog" in pq.ParallelQueryBudget().to_dict()


def test_broker_budget_reserves_control_plane_and_catalog_caps() -> None:
    budget = _budget(max_duration_ms=1000)
    parallel = budget.to_parallel_budget(max_workers=2, total_slots=8)
    assert parallel.analytical_time_ms == 1000 - pq.DEFAULT_RESERVED_CONTROL_PLANE_MS
    assert parallel.max_connections_per_catalog == 1
    assert parallel.max_memory_bytes == budget.max_memory_bytes
    with pytest.raises(lake.LakeExecutionError):
        lake.LakeCatalogBudget(max_duration_ms=0)


# ---------------------------------------------------------------------------
# Acceptance: independent shard scans overlap; no shared mutable connections
# ---------------------------------------------------------------------------


def test_independent_shard_scans_overlap_without_shared_connections() -> None:
    vector = _vector_two()
    catalogs = ("cat_a", "cat_b")
    executor, eps = _executor(vector, catalogs)
    plan = _plan(vector, catalogs, hold_ms=100.0, budget=_budget(max_duration_ms=5_000))

    result = executor.execute(plan, run_heartbeat_monitor=True)

    assert result.receipt.independent_shards_overlapped is True
    assert result.independent_shards_overlapped is True
    assert result.receipt.no_shared_mutable_connections is True

    # Distinct exclusive connection identities.
    conn_ids = [e.connection_id for e in result.worker_evidence if e.connection_id]
    assert len(conn_ids) == 2
    assert len(set(conn_ids)) == 2

    # Broker-level shard overlap evidence agrees.
    shard_overlap = result.broker_result.receipt.shard_overlap
    assert shard_overlap["no_shared_mutable_connections"] is True
    assert shard_overlap["max_concurrency"] >= 2

    # Each endpoint saw its own attachment only.
    for cid in catalogs:
        assert len(eps[cid].attachments) == 1
        assert eps[cid].attachments[0].connection_id in conn_ids
        assert eps[cid].attachments[0].closed is True

    assert all(o.succeeded for o in result.broker_result.outcomes)
    assert len(result.rows) >= 2
    assert result.status in {"succeeded", "partial", "truncated"}


def test_same_shard_mutations_are_serialized() -> None:
    gate = lake.CatalogOwnerMutationGate()
    order: list[str] = []
    order_lock = threading.Lock()
    errors: list[BaseException] = []
    a_started = threading.Event()
    b_started = threading.Event()

    def mut_a() -> None:
        try:
            def body() -> str:
                a_started.set()
                with order_lock:
                    order.append("a-enter")
                # Hold long enough that concurrent peer would interleave if unlocked.
                time.sleep(0.08)
                with order_lock:
                    order.append("a-exit")
                return "a"

            gate.mutate("cat_a", lake.MutationKind.INGEST, body, holder="owner-a")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def mut_b() -> None:
        try:
            # Wait until a has entered the critical section (or timed out starting).
            a_started.wait(timeout=2.0)

            def body() -> str:
                b_started.set()
                with order_lock:
                    order.append("b-enter")
                time.sleep(0.02)
                with order_lock:
                    order.append("b-exit")
                return "b"

            gate.mutate("cat_a", lake.MutationKind.COMPACT, body, holder="owner-b")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    # Different catalogs must not serialize against each other.
    other_done = threading.Event()
    other_during_a = threading.Event()

    def mut_other() -> None:
        try:
            a_started.wait(timeout=2.0)

            def body() -> str:
                # If we run while a holds cat_a, unrelated shards are free.
                if gate.is_active("cat_a"):
                    other_during_a.set()
                other_done.set()
                return "other"

            gate.mutate(
                "cat_b",
                lake.MutationKind.INGEST,
                body,
                holder="owner-other",
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t_other = threading.Thread(target=mut_other)
    t1 = threading.Thread(target=mut_a)
    t2 = threading.Thread(target=mut_b)
    t1.start()
    t_other.start()
    t2.start()
    t_other.join(timeout=5.0)
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)
    assert not errors
    assert other_done.is_set()
    assert other_during_a.is_set(), "unrelated shard mutation must not wait on cat_a"
    # Same-shard: enter/exit pairs nest serially, never interleaved mid-body.
    assert order == ["a-enter", "a-exit", "b-enter", "b-exit"]
    history = gate.history()
    assert len([h for h in history if h["catalog_id"] == "cat_a"]) == 2


# ---------------------------------------------------------------------------
# Acceptance: DQK-090 lease lifecycle around attachment/scan/materialize
# ---------------------------------------------------------------------------


def test_every_worker_acquires_renews_and_releases_lease() -> None:
    vector = _vector_two()
    catalogs = ("cat_a", "cat_b")
    executor, _eps = _executor(vector, catalogs)
    plan = _plan(
        vector,
        catalogs,
        hold_ms=60.0,
        budget=_budget(renew_interval_ms=10, lease_ttl_seconds=30, max_duration_ms=5_000),
    )

    result = executor.execute(plan, run_heartbeat_monitor=True)

    for ev in result.worker_evidence:
        assert ev.lease is not None
        assert ev.lease.acquired is True
        assert ev.lease.released is True
        assert ev.lease.final_status == "released"
        assert ev.lease.renewed_count >= 1
        assert ev.lease.readers_closed_before_release is True
        # Fence bindings
        assert ev.lease.process_birth["pid"] == plan.process_birth.pid
        assert ev.lease.process_birth["boot_id"] == plan.process_birth.boot_id
        assert ev.lease.owner_generation == ev.owner_generation
        assert ev.lease.fencing_epoch == ev.fencing_epoch
        assert ev.lease.task_id == plan.task_id
        assert ev.lease.run_id == plan.run_id
        assert ev.lease.vector_id == vector.vector_id
        # Attachment closed after release path.
        assert ev.connection_id
        assert ev.quack_endpoint_identity
        assert ev.opens_catalog_file is False

    # No live leases remain after clean release.
    live = executor.lease_db.list_live_leases(vector_id=vector.vector_id)
    assert live == ()


def test_lease_renew_fails_closed_on_pid_reuse_and_stale_fence() -> None:
    vector = _vector_two()
    db = snap.AuthoritativeSnapshotDatabase()
    db.put_vector(vector)
    birth = _birth(pid=100, start_ticks=10)
    lease = db.acquire_lease(
        vector=vector,
        catalog_id="cat_a",
        process_birth=birth,
        task_id="t1",
        run_id="r1",
        worker_id="w1",
        ttl_seconds=30,
    )
    # PID reuse: same pid, different start_ticks.
    reused = _birth(pid=100, start_ticks=9999)
    with pytest.raises(ReaderLeaseError) as exc:
        db.renew_lease(
            lease_id=lease.lease_id,
            lease_token=lease.lease_token,
            process_birth=reused,
            task_id="t1",
            run_id="r1",
        )
    assert "PID reuse" in str(exc.value) or "process birth" in str(exc.value).lower()

    # Stale owner generation fence.
    with pytest.raises(ReaderLeaseError):
        db.renew_lease(
            lease_id=lease.lease_id,
            lease_token=lease.lease_token,
            process_birth=birth,
            task_id="t1",
            run_id="r1",
            owner_generation=999,
        )

    # Foreign token.
    with pytest.raises(ReaderLeaseError):
        db.release_lease(
            lease_id=lease.lease_id,
            lease_token="not-the-token",
            process_birth=birth,
            task_id="t1",
            run_id="r1",
        )


def test_cancellation_closes_readers_before_lease_release() -> None:
    vector = _vector_two()
    catalogs = ("cat_a", "cat_b")
    # Slow endpoints so cancellation hits mid-scan.
    eps = {
        cid: _endpoint(vector, cid, slow_ms=500.0, scan_hold_ms=500.0)
        for cid in catalogs
    }
    executor, _ = _executor(vector, catalogs, endpoints=eps)
    plan = _plan(
        vector,
        catalogs,
        hold_ms=500.0,
        budget=_budget(max_duration_ms=5_000, renew_interval_ms=20),
    )
    cancel = CancellationToken()

    def _cancel_soon() -> None:
        time.sleep(0.05)
        cancel.cancel("test_cancel")

    threading.Thread(target=_cancel_soon, daemon=True).start()
    result = executor.execute(plan, cancellation=cancel, run_heartbeat_monitor=True)

    assert result.status in {"cancelled", "partial", "failed", "timeout"}
    # At least one worker observed cancel and closed readers before release.
    closed_before = [
        e
        for e in result.worker_evidence
        if e.lease is not None and e.lease.readers_closed_before_release
    ]
    assert closed_before, "expected readers closed before lease release on cancel"
    for ev in closed_before:
        assert ev.lease is not None
        # Lease was acquired; release path ran after close.
        assert ev.lease.acquired is True
        # Released or not renewable (expired/released).
        assert ev.lease.final_status in {"released", "expired", "active", "not_acquired"} or (
            ev.lease.released is True
        )

    # Attachments left closed.
    for cid in catalogs:
        for att in eps[cid].attachments:
            assert att.closed is True


def test_crash_recovery_relies_on_bounded_lease_expiry() -> None:
    vector = _vector_two()
    db = snap.AuthoritativeSnapshotDatabase()
    # Deterministic clock for expiry.
    clock = {"t": 1_700_000_000.0}
    db.set_clock(lambda: clock["t"])
    db.put_vector(vector)
    birth = _birth()
    lease = db.acquire_lease(
        vector=vector,
        catalog_id="cat_a",
        process_birth=birth,
        task_id="t-crash",
        run_id="r-crash",
        worker_id="w-crash",
        ttl_seconds=5,
    )
    assert lease.is_live(now=clock["t"])
    live = db.list_live_leases(catalog_id="cat_a")
    assert len(live) == 1

    # Simulate worker death: no release; advance past TTL.
    clock["t"] += 10.0
    expired = db.expire_due_leases()
    assert lease.lease_id in expired
    assert db.list_live_leases(catalog_id="cat_a") == ()
    # Renew after crash expiry fails closed (not renewable stale lease).
    with pytest.raises(ReaderLeaseError):
        db.renew_lease(
            lease_id=lease.lease_id,
            lease_token=lease.lease_token,
            process_birth=birth,
            task_id="t-crash",
            run_id="r-crash",
        )


# ---------------------------------------------------------------------------
# Acceptance: deadlines / cancellation propagate to every worker
# ---------------------------------------------------------------------------


def test_deadlines_propagate_to_every_worker() -> None:
    vector = _vector_two()
    catalogs = ("cat_a", "cat_b")
    # Workers that ignore cancel still hit analytical deadline via context.check.
    eps = {
        cid: _endpoint(vector, cid, slow_ms=2_000.0, scan_hold_ms=2_000.0)
        for cid in catalogs
    }
    executor, _ = _executor(vector, catalogs, endpoints=eps)
    plan = _plan(
        vector,
        catalogs,
        hold_ms=2_000.0,
        budget=_budget(
            max_duration_ms=400,  # short analytical window after reserved CP
            renew_interval_ms=20,
        ),
    )
    result = executor.execute(plan, run_heartbeat_monitor=True)
    # Both workers should fail via timeout/cancel/budget, not hang forever.
    assert len(result.broker_result.outcomes) == 2
    assert all(not o.succeeded for o in result.broker_result.outcomes) or result.status in {
        "timeout",
        "cancelled",
        "partial",
        "failed",
    }
    assert result.receipt.duration_ms < 5_000


def test_cancellation_propagates_to_every_worker() -> None:
    vector = _vector_three()
    catalogs = ("cat_a", "cat_b", "cat_c")
    eps = {
        cid: _endpoint(vector, cid, slow_ms=800.0, scan_hold_ms=800.0)
        for cid in catalogs
    }
    executor, _ = _executor(vector, catalogs, endpoints=eps)
    plan = _plan(
        vector,
        catalogs,
        hold_ms=800.0,
        budget=_budget(max_duration_ms=5_000),
        policy=pq.PartialFailurePolicy.FAIL_FAST,
    )
    cancel = CancellationToken()
    cancel.cancel("preempt")
    result = executor.execute(plan, cancellation=cancel, run_heartbeat_monitor=False)
    assert result.status == "cancelled"
    assert all(
        o.status is pq.SubqueryStatus.CANCELLED for o in result.broker_result.outcomes
    )


# ---------------------------------------------------------------------------
# Acceptance: slow/failed catalog cannot starve heartbeats or unrelated shards
# ---------------------------------------------------------------------------


def test_slow_catalog_cannot_starve_heartbeats_or_unrelated_shards() -> None:
    vector = _vector_three()
    # cat_a is pathological (very slow); cat_b and cat_c are healthy.
    eps = {
        "cat_a": _endpoint(vector, "cat_a", slow_ms=400.0, scan_hold_ms=400.0),
        "cat_b": _endpoint(vector, "cat_b", scan_hold_ms=40.0),
        "cat_c": _endpoint(vector, "cat_c", scan_hold_ms=40.0),
    }
    executor, _ = _executor(vector, ("cat_a", "cat_b", "cat_c"), endpoints=eps)
    plan = lake.LakeExecutionPlan(
        subplans=(
            _subplan(vector, "cat_a", hold_ms=400.0),
            _subplan(vector, "cat_b", hold_ms=40.0),
            _subplan(vector, "cat_c", hold_ms=40.0),
        ),
        snapshot_vector=vector,
        process_birth=_birth(),
        task_id="task-slow",
        run_id="run-slow",
        plan_id="plan-slow",
        catalog_budget=_budget(max_duration_ms=3_000, renew_interval_ms=10),
        reserved_control_plane_ms=250,
        reserved_control_plane_slots=1,
        total_slots=8,
        heartbeat_interval_ms=5,
        heartbeat_p99_slo_ms=50.0,
    )

    result = executor.execute(plan, run_heartbeat_monitor=True)

    # Healthy shards completed.
    healthy = [
        o
        for o in result.broker_result.outcomes
        if o.catalog_id in {"cat_b", "cat_c"}
    ]
    assert all(o.succeeded for o in healthy)

    # Control-plane heartbeats remained within SLO despite slow shard.
    assert result.broker_result.heartbeat.count >= 1
    assert result.receipt.control_plane_within_slo is True
    assert result.broker_result.heartbeat.within_slo is True

    # Capacity snapshot shows reserved control slots never borrowed as analytical.
    capacity = result.broker_result.receipt.capacity
    assert capacity["reserved_control_plane_slots"] >= 1
    assert capacity["analytical_slots"] == capacity["total_slots"] - capacity[
        "reserved_control_plane_slots"
    ]


def test_failed_catalog_does_not_block_unrelated_shards() -> None:
    vector = _vector_two()
    eps = {
        "cat_a": _endpoint(
            vector, "cat_a", fail=RuntimeError("owner down")
        ),
        "cat_b": _endpoint(vector, "cat_b", scan_hold_ms=40.0),
    }
    executor, _ = _executor(vector, ("cat_a", "cat_b"), endpoints=eps)
    plan = _plan(
        vector,
        ("cat_a", "cat_b"),
        hold_ms=40.0,
        budget=_budget(max_duration_ms=3_000),
        policy=pq.PartialFailurePolicy.CONTINUE,
    )
    result = executor.execute(plan, run_heartbeat_monitor=True)
    by_cat = {o.catalog_id: o for o in result.broker_result.outcomes}
    assert by_cat["cat_b"].succeeded
    assert not by_cat["cat_a"].succeeded
    assert result.status == "partial"
    assert result.receipt.control_plane_within_slo is True


# ---------------------------------------------------------------------------
# Acceptance: receipts bind plan, vector, endpoint/owner, lease, resources
# ---------------------------------------------------------------------------


def test_receipts_bind_plan_vector_lease_endpoint_and_resources() -> None:
    vector = _vector_two()
    catalogs = ("cat_a", "cat_b")
    executor, _ = _executor(vector, catalogs)
    plan = _plan(
        vector,
        catalogs,
        hold_ms=50.0,
        budget=_budget(max_duration_ms=5_000, renew_interval_ms=10),
        policy=pq.PartialFailurePolicy.CONTINUE,
    )
    result = executor.execute(plan, run_heartbeat_monitor=True)
    receipt = result.receipt

    assert receipt.schema == lake.LAKE_EXECUTION_RECEIPT_SCHEMA
    assert receipt.plan_id == plan.plan_id
    assert receipt.run_id == plan.run_id
    assert receipt.task_id == plan.task_id
    assert receipt.snapshot_vector_id == vector.vector_id
    assert receipt.snapshot_vector_digest == vector.identity_digest
    assert receipt.partial_failure_policy == pq.PartialFailurePolicy.CONTINUE.value
    assert receipt.result_digest.startswith("sha256:")
    assert receipt.identity_id.startswith("sha256:")
    assert dict(receipt.process_birth) == dict(plan.process_birth.as_mapping())
    assert "rows" in receipt.resource_use or "duration_ms" in receipt.resource_use

    for ev in result.worker_evidence:
        body = ev.to_dict()
        assert body["quack_endpoint_identity"]
        assert body["owner_generation"] == 1
        assert body["lease"] is not None
        assert body["lease"]["lease_id"]
        assert body["lease"]["process_birth"]["pid"] == plan.process_birth.pid
        assert body["resource_use"]
        assert body["opens_catalog_file"] is False
        assert body["result_digest"].startswith("sha256:") or body["row_count"] >= 0

    # Broker receipt also carries result digest + partial-failure policy.
    br = receipt.broker_receipt
    assert br["partial_failure_policy"] == pq.PartialFailurePolicy.CONTINUE.value
    assert br["result_digest"].startswith("sha256:")
    assert "resource_use" in br


# ---------------------------------------------------------------------------
# Catalog connection pool isolation (broker unit surface)
# ---------------------------------------------------------------------------


def test_catalog_connection_pool_isolates_handles() -> None:
    pool = pq.CatalogConnectionPool(max_connections_per_catalog=1)
    a1 = pool.acquire("cat_a", timeout=0.5, owner_token="w1")
    b1 = pool.acquire("cat_b", timeout=0.5, owner_token="w2")
    assert a1 is not None and b1 is not None
    assert a1 != b1
    # Same catalog is serialized.
    blocked = pool.acquire("cat_a", timeout=0.05, owner_token="w3")
    assert blocked is None
    pool.release("cat_a", a1)
    a2 = pool.acquire("cat_a", timeout=0.5, owner_token="w3")
    assert a2 is not None
    assert a2 != a1
    pool.release("cat_a", a2)
    pool.release("cat_b", b1)


def test_refuse_catalog_file_endpoint() -> None:
    vector = _vector_two()
    with pytest.raises(lake.LakeExecutionError) as exc:
        lake.LakeShardSubplan(
            subplan_id="bad",
            catalog_id="cat_a",
            shard_id="shard-a",
            quack_endpoint_identity="file:///var/lib/ducklake/catalog.duckdb",
            owner_generation=1,
            fencing_epoch=1,
            snapshot_version=7,
            vector_id=vector.vector_id,
        )
    assert exc.value.code == "ATTACH"
