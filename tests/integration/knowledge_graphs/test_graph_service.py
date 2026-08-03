"""Integration tests: long-lived GraphService (KGP-006).

Acceptance:
  Implement create/list/describe/open/branch/delete/write/query transaction
  boundaries around explicit GraphTarget and catalog snapshots. Dependency
  injection must make authorization, storage, clock, faults, and audit
  testable. A new client instance can reopen committed graphs and never
  receives an ambient empty graph.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from ipfs_datasets_py.knowledge_graphs.service import (
    CONTRACT_VERSION,
    QUERY_ENVELOPE_VERSION,
    AllowAllAuthorizer,
    FileGraphStorage,
    GraphService,
    GraphSnapshot,
    GraphTarget,
    GraphTargetError,
    InMemoryAuditSink,
    InMemoryGraphStorage,
    LifecycleRequest,
    PrincipalAuthorizer,
    ScriptedFaultInjector,
    SystemClock,
    TypedError,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _child_env() -> dict:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not existing else f"{_REPO_ROOT}{os.pathsep}{existing}"
    )
    return env


def _run_child(script: str, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=_child_env(),
        cwd=str(_REPO_ROOT),
    )


def _assert_json_safe(value: Any) -> None:
    json.dumps(value, allow_nan=False, sort_keys=True)


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "kg_catalog.sqlite", tmp_path / "kg_payloads"


def _open_service(
    tmp_path: Path,
    *,
    authorizer=None,
    audit=None,
    faults=None,
    clock=None,
    holder_id: Optional[str] = None,
) -> GraphService:
    catalog_path, storage_path = _paths(tmp_path)
    return GraphService.open(
        catalog_path,
        storage_path=storage_path,
        authorizer=authorizer,
        audit=audit,
        faults=faults,
        clock=clock,
        holder_id=holder_id,
    )


# ---------------------------------------------------------------------------
# Construction / no ambient graph
# ---------------------------------------------------------------------------


class TestNoAmbientEmptyGraph:
    def test_new_service_has_no_ambient_graph_handle(self, tmp_path: Path) -> None:
        svc = _open_service(tmp_path)
        try:
            # Internal open-handle map must start empty (no ambient graph).
            assert svc._open_handles == {}  # noqa: SLF001 — acceptance probe
            assert not hasattr(svc, "current_graph") or getattr(svc, "current_graph", None) is None
            listed = svc.list(GraphTarget(tenant="acme", graph_id="list"))
            assert listed.ok
            assert listed.result is not None
            assert listed.result["graphs"] == []
        finally:
            svc.close()

    def test_open_without_selector_is_invalid_target(self, tmp_path: Path) -> None:
        svc = _open_service(tmp_path)
        try:
            created = svc.create(
                GraphTarget(tenant="acme", graph_id="skills"),
                idempotency_key="create-1",
            )
            assert created.ok
            # open requires branch or revision
            bad = svc.open_graph(GraphTarget(tenant="acme", graph_id="skills"))
            assert not bad.ok
            assert bad.error is not None
            assert bad.error.code == "INVALID_TARGET"
        finally:
            svc.close()

    def test_construction_does_not_auto_create_graphs(self, tmp_path: Path) -> None:
        catalog_path, storage_path = _paths(tmp_path)
        with GraphService.open(catalog_path, storage_path=storage_path) as svc:
            result = svc.list({"tenant": "orphan", "graph_id": "list"})
            assert result.ok
            assert result.result["graphs"] == []


# ---------------------------------------------------------------------------
# Full lifecycle around explicit GraphTarget
# ---------------------------------------------------------------------------


class TestLifecycleOperations:
    def test_create_list_describe_open_branch_write_query_delete(
        self, tmp_path: Path
    ) -> None:
        svc = _open_service(tmp_path)
        try:
            target = GraphTarget(
                tenant="acme",
                graph_id="skills",
                branch="main",
                storage_profile="hybrid",
            )
            created = svc.create(
                target,
                idempotency_key="create-skills",
                params={"graph_kind": "skills", "metadata": {"owner": "team-a"}},
            )
            assert created.ok, created.to_json_dict()
            assert created.contract_version == CONTRACT_VERSION
            assert created.result["graph_id"] == "skills"
            assert created.result["branch"] == "main"
            assert created.result["revision"].startswith("kg-bootstrap-")
            assert created.result["storage_profile"] == "hybrid"
            _assert_json_safe(created.to_json_dict())

            listed = svc.list(GraphTarget(tenant="acme", graph_id="list"))
            assert listed.ok
            assert len(listed.result["graphs"]) == 1
            assert listed.result["graphs"][0]["graph_id"] == "skills"

            described = svc.describe(target)
            assert described.ok
            assert described.result["head_revision"] == created.result["revision"]
            assert described.result["storage_profile"] == "hybrid"
            assert described.result["graph_kind"] == "skills"
            assert any(b["branch"] == "main" for b in described.result["branches"])

            opened = svc.open_graph(target)
            assert opened.ok, opened.to_json_dict()
            assert opened.result["revision"] == created.result["revision"]
            assert opened.result["snapshot_id"].startswith("snap-")
            assert opened.target is not None
            assert opened.target.revision == created.result["revision"]

            branched = svc.branch(
                GraphTarget(tenant="acme", graph_id="skills", branch="feature"),
                params={"from_branch": "main"},
            )
            assert branched.ok, branched.to_json_dict()
            assert branched.result["branch"] == "feature"
            assert branched.result["revision"] == created.result["revision"]

            write = svc.write(
                GraphTarget(tenant="acme", graph_id="skills", branch="main"),
                idempotency_key="write-1",
                params={
                    "entities": [
                        {
                            "id": "e1",
                            "type": "Person",
                            "name": "Alice",
                            "properties": {"role": "eng"},
                        },
                        {
                            "id": "e2",
                            "type": "Skill",
                            "name": "Python",
                            "properties": {},
                        },
                    ],
                    "relationships": [
                        {
                            "id": "r1",
                            "type": "HAS_SKILL",
                            "source_id": "e1",
                            "target_id": "e2",
                        }
                    ],
                },
            )
            assert write.ok, write.to_json_dict()
            assert write.result["mutation_count"] >= 2
            new_rev = write.result["revision"]
            assert new_rev != created.result["revision"]
            assert write.result["parent_revision"] == created.result["revision"]

            # Query by branch head
            q = svc.query(
                GraphTarget(tenant="acme", graph_id="skills", branch="main"),
                params={"language": "scan"},
            )
            assert q.ok, q.to_json_dict()
            env = q.result
            assert env["envelope_version"] == QUERY_ENVELOPE_VERSION
            assert env["revision"] == new_rev
            assert env["row_count"] == 2
            assert env["target"]["revision"] == new_rev
            _assert_json_safe(q.to_json_dict())

            # Query by immutable revision pin
            q2 = svc.query(
                GraphTarget(
                    tenant="acme",
                    graph_id="skills",
                    revision=new_rev,
                ),
                params={"language": "count"},
            )
            assert q2.ok
            assert q2.result["rows"] == [[2, 1]]

            # Cypher-lite
            q3 = svc.query(
                GraphTarget(tenant="acme", graph_id="skills", branch="main"),
                params={
                    "language": "cypher",
                    "text": "MATCH (n:Person) RETURN n",
                },
            )
            assert q3.ok, q3.to_json_dict()
            assert q3.result["row_count"] == 1

            # feature branch still at bootstrap until written
            feat_open = svc.open_graph(
                GraphTarget(tenant="acme", graph_id="skills", branch="feature")
            )
            assert feat_open.ok
            assert feat_open.result["revision"] == created.result["revision"]

            deleted_branch = svc.delete(
                GraphTarget(tenant="acme", graph_id="skills", branch="feature"),
                params={"reason": "merged"},
            )
            assert deleted_branch.ok
            assert deleted_branch.result["tombstone"] is True

            deleted_graph = svc.delete(
                GraphTarget(tenant="acme", graph_id="skills"),
                idempotency_key="del-skills",
                params={"reason": "archive"},
            )
            assert deleted_graph.ok
            assert deleted_graph.result["tombstone"] is True

            listed_after = svc.list(GraphTarget(tenant="acme", graph_id="list"))
            assert listed_after.ok
            assert listed_after.result["graphs"] == []
        finally:
            svc.close()

    def test_create_idempotent_replay(self, tmp_path: Path) -> None:
        svc = _open_service(tmp_path)
        try:
            t = GraphTarget(tenant="t", graph_id="g", branch="main")
            a = svc.create(t, idempotency_key="idem-create")
            b = svc.create(t, idempotency_key="idem-create")
            assert a.ok and b.ok
            assert a.result["revision"] == b.result["revision"]
        finally:
            svc.close()

    def test_duplicate_create_without_idempotency_is_already_exists(
        self, tmp_path: Path
    ) -> None:
        svc = _open_service(tmp_path)
        try:
            t = GraphTarget(tenant="t", graph_id="g2")
            assert svc.create(t, idempotency_key="c1").ok
            again = svc.create(t, idempotency_key="c2")
            assert not again.ok
            assert again.error.code == "ALREADY_EXISTS"
        finally:
            svc.close()

    def test_execute_lifecycle_request_dispatch(self, tmp_path: Path) -> None:
        svc = _open_service(tmp_path)
        try:
            req = LifecycleRequest(
                operation="create",
                target=GraphTarget(tenant="acme", graph_id="via-exec"),
                idempotency_key="exec-create",
            )
            result = svc.execute(req)
            assert result.ok
            assert result.operation == "create"
        finally:
            svc.close()


# ---------------------------------------------------------------------------
# Transaction boundaries
# ---------------------------------------------------------------------------


class TestTransactionBoundaries:
    def test_begin_write_commit_and_query(self, tmp_path: Path) -> None:
        svc = _open_service(tmp_path, holder_id="writer-1")
        try:
            t = GraphTarget(tenant="acme", graph_id="txg", branch="main")
            assert svc.create(t, idempotency_key="tx-create").ok

            begin = svc.begin_tx(t)
            assert begin.ok, begin.to_json_dict()
            tx_id = begin.result["transaction_id"]
            assert begin.result["state"] == "open"
            assert begin.result["lease_id"]

            staged = svc.write(
                t,
                idempotency_key="tx-stage-1",
                params={
                    "transaction_id": tx_id,
                    "entities": [
                        {"id": "n1", "type": "Node", "name": "one"},
                        {"id": "n2", "type": "Node", "name": "two"},
                    ],
                },
            )
            assert staged.ok, staged.to_json_dict()
            assert staged.result["staged"] is True
            assert staged.result["state"] == "open"

            # Head must not advance until commit.
            desc = svc.describe(t)
            assert desc.result["head_revision"] == begin.result["base_revision"]

            commit = svc.commit_tx(
                t,
                idempotency_key="tx-commit-1",
                params={"transaction_id": tx_id},
            )
            assert commit.ok, commit.to_json_dict()
            assert commit.result["state"] == "committed"
            assert commit.result["mutation_count"] >= 2
            assert commit.result["revision"] != begin.result["base_revision"]

            q = svc.query(t, params={"language": "count"})
            assert q.ok
            assert q.result["rows"][0][0] == 2
        finally:
            svc.close()

    def test_rollback_discards_staged_mutations(self, tmp_path: Path) -> None:
        svc = _open_service(tmp_path)
        try:
            t = GraphTarget(tenant="acme", graph_id="txrb", branch="main")
            create = svc.create(t, idempotency_key="rb-create")
            assert create.ok
            boot = create.result["revision"]

            begin = svc.begin_tx(t, params={"acquire_lease": False})
            tx_id = begin.result["transaction_id"]
            svc.write(
                t,
                idempotency_key="rb-stage",
                params={
                    "transaction_id": tx_id,
                    "entities": [{"id": "x", "type": "T", "name": "x"}],
                },
            )
            rb = svc.rollback_tx(t, params={"transaction_id": tx_id})
            assert rb.ok
            assert rb.result["state"] == "rolled_back"

            desc = svc.describe(t)
            assert desc.result["head_revision"] == boot
            q = svc.query(t, params={"language": "count"})
            assert q.result["rows"][0][0] == 0
        finally:
            svc.close()

    def test_commit_conflict_when_head_moves(self, tmp_path: Path) -> None:
        svc = _open_service(tmp_path)
        try:
            t = GraphTarget(tenant="acme", graph_id="txc", branch="main")
            assert svc.create(t, idempotency_key="c-create").ok
            begin = svc.begin_tx(t, params={"acquire_lease": False})
            tx_id = begin.result["transaction_id"]

            # Concurrent auto-commit write moves head.
            w = svc.write(
                t,
                idempotency_key="c-write-other",
                params={"entities": [{"id": "other", "type": "X", "name": "o"}]},
            )
            assert w.ok

            svc.write(
                t,
                idempotency_key="c-stage",
                params={
                    "transaction_id": tx_id,
                    "entities": [{"id": "stale", "type": "X", "name": "s"}],
                },
            )
            commit = svc.commit_tx(
                t,
                idempotency_key="c-commit",
                params={"transaction_id": tx_id},
            )
            assert not commit.ok
            assert commit.error.code == "CONFLICT"
        finally:
            svc.close()


# ---------------------------------------------------------------------------
# Durable reopen with a new client instance
# ---------------------------------------------------------------------------


class TestReopenCommittedGraphs:
    def test_new_service_instance_reopens_committed_graph(self, tmp_path: Path) -> None:
        catalog_path, storage_path = _paths(tmp_path)
        with GraphService.open(catalog_path, storage_path=storage_path) as svc1:
            t = GraphTarget(tenant="acme", graph_id="durable", branch="main")
            c = svc1.create(t, idempotency_key="dur-create")
            assert c.ok
            w = svc1.write(
                t,
                idempotency_key="dur-write",
                params={
                    "entities": [
                        {"id": "a", "type": "Person", "name": "Ada"},
                    ]
                },
            )
            assert w.ok
            rev = w.result["revision"]

        # Brand-new client — no shared process caches.
        with GraphService.open(catalog_path, storage_path=storage_path) as svc2:
            assert svc2._open_handles == {}  # noqa: SLF001
            listed = svc2.list(GraphTarget(tenant="acme", graph_id="list"))
            assert any(g["graph_id"] == "durable" for g in listed.result["graphs"])

            opened = svc2.open_graph(t)
            assert opened.ok, opened.to_json_dict()
            assert opened.result["revision"] == rev
            assert opened.result["entity_count"] == 1

            # Pin by revision
            pin = svc2.open_graph(
                GraphTarget(tenant="acme", graph_id="durable", revision=rev)
            )
            assert pin.ok
            assert pin.result["revision"] == rev

            q = svc2.query(t, params={"language": "scan"})
            assert q.ok
            assert q.result["row_count"] == 1
            assert q.result["rows"][0][2] == "Ada"

    def test_subprocess_reopen_boundary(self, tmp_path: Path) -> None:
        catalog_path, storage_path = _paths(tmp_path)
        cat = str(catalog_path)
        store = str(storage_path)

        writer = r"""
import json, sys
from ipfs_datasets_py.knowledge_graphs.service import GraphService, GraphTarget
cat, store = sys.argv[1], sys.argv[2]
svc = GraphService.open(cat, storage_path=store)
try:
    t = GraphTarget(tenant="mp", graph_id="g1", branch="main")
    c = svc.create(t, idempotency_key="mp-create")
    assert c.status == "success", c.to_json_dict()
    w = svc.write(
        t,
        idempotency_key="mp-write",
        params={"entities": [{"id": "n1", "type": "T", "name": "proc"}]},
    )
    assert w.status == "success", w.to_json_dict()
    print(json.dumps({"revision": w.result["revision"], "parent": w.result["parent_revision"]}))
finally:
    svc.close()
"""
        reader = r"""
import json, sys
from ipfs_datasets_py.knowledge_graphs.service import GraphService, GraphTarget
cat, store, expected = sys.argv[1], sys.argv[2], sys.argv[3]
svc = GraphService.open(cat, storage_path=store)
try:
    # New instance must not present an ambient empty graph.
    assert svc._open_handles == {}
    t = GraphTarget(tenant="mp", graph_id="g1", branch="main")
    o = svc.open_graph(t)
    assert o.status == "success", o.to_json_dict()
    q = svc.query(t, params={"language": "scan"})
    assert q.status == "success", q.to_json_dict()
    print(json.dumps({
        "revision": o.result["revision"],
        "entity_count": o.result["entity_count"],
        "row_count": q.result["row_count"],
        "name": q.result["rows"][0][2] if q.result["rows"] else None,
        "open_handles_empty_at_start": True,
    }))
finally:
    svc.close()
"""
        written = _run_child(writer, cat, store)
        assert written.returncode == 0, written.stderr
        payload = json.loads(written.stdout.strip())
        expected_rev = payload["revision"]

        seen = _run_child(reader, cat, store, expected_rev)
        assert seen.returncode == 0, seen.stderr
        out = json.loads(seen.stdout.strip())
        assert out["revision"] == expected_rev
        assert out["entity_count"] == 1
        assert out["row_count"] == 1
        assert out["name"] == "proc"


# ---------------------------------------------------------------------------
# Dependency injection: auth, clock, faults, audit, storage
# ---------------------------------------------------------------------------


class TestDependencyInjection:
    def test_authorizer_denies_without_principal(self, tmp_path: Path) -> None:
        authz = PrincipalAuthorizer(required_principal=True)
        svc = _open_service(tmp_path, authorizer=authz)
        try:
            r = svc.create(
                GraphTarget(tenant="acme", graph_id="sec"),
                idempotency_key="sec-create",
            )
            assert not r.ok
            assert r.error.code == "UNAUTHORIZED"
            assert r.authorization_receipt_ref
        finally:
            svc.close()

    def test_authorizer_allows_with_principal(self, tmp_path: Path) -> None:
        authz = PrincipalAuthorizer(required_principal=True)
        audit = InMemoryAuditSink()
        svc = _open_service(tmp_path, authorizer=authz, audit=audit)
        try:
            r = svc.create(
                GraphTarget(tenant="acme", graph_id="sec2"),
                idempotency_key="sec2-create",
                auth={"principal": "alice@acme"},
            )
            assert r.ok, r.to_json_dict()
            assert r.authorization_receipt_ref
            assert any(e.get("event") == "authorization" for e in audit.events)
            assert any(e.get("event") == "lifecycle_success" for e in audit.events)
        finally:
            svc.close()

    def test_authorizer_forbids_disallowed_ability(self, tmp_path: Path) -> None:
        authz = PrincipalAuthorizer(
            required_principal=True,
            allowed_abilities=["graph/list", "graph/read"],
        )
        svc = _open_service(tmp_path, authorizer=authz)
        try:
            r = svc.create(
                GraphTarget(tenant="acme", graph_id="forbid"),
                idempotency_key="f-create",
                auth={"principal": "bob"},
            )
            assert not r.ok
            assert r.error.code == "FORBIDDEN"
        finally:
            svc.close()

    def test_fault_injector_maps_to_internal(self, tmp_path: Path) -> None:
        faults = ScriptedFaultInjector()
        faults.arm("create", "before_handler", RuntimeError("boom"))
        svc = _open_service(tmp_path, faults=faults)
        try:
            r = svc.create(
                GraphTarget(tenant="acme", graph_id="faulty"),
                idempotency_key="fault-create",
            )
            assert not r.ok
            assert r.error.code == "INTERNAL"
        finally:
            svc.close()

    def test_custom_clock_appears_in_audit(self, tmp_path: Path) -> None:
        class FixedClock:
            def now_iso(self) -> str:
                return "2099-01-01T00:00:00.000Z"

        audit = InMemoryAuditSink()
        svc = _open_service(tmp_path, clock=FixedClock(), audit=audit)
        try:
            svc.create(
                GraphTarget(tenant="acme", graph_id="clock"),
                idempotency_key="clock-create",
            )
            assert any(
                e.get("at") == "2099-01-01T00:00:00.000Z" for e in audit.events
            )
        finally:
            svc.close()

    def test_in_memory_storage_isolation_vs_file_storage(self, tmp_path: Path) -> None:
        """File storage is durable; in-memory is not across service close+reopen
        with a fresh InMemoryGraphStorage (catalog still durable)."""
        catalog_path = tmp_path / "cat.sqlite"
        mem = InMemoryGraphStorage()
        from ipfs_datasets_py.knowledge_graphs.catalog import open_catalog

        cat = open_catalog(catalog_path)
        svc = GraphService(
            cat,
            storage=mem,
            close_catalog_on_close=True,
            close_storage_on_close=True,
        )
        try:
            t = GraphTarget(tenant="acme", graph_id="mem", branch="main")
            assert svc.create(t, idempotency_key="mem-c").ok
            w = svc.write(
                t,
                idempotency_key="mem-w",
                params={"entities": [{"id": "1", "type": "T", "name": "m"}]},
            )
            assert w.ok
            rev = w.result["revision"]
        finally:
            svc.close()

        # New in-memory store: catalog head exists but payload missing → empty snap.
        cat2 = open_catalog(catalog_path)
        svc2 = GraphService(
            cat2,
            storage=InMemoryGraphStorage(),
            close_catalog_on_close=True,
        )
        try:
            opened = svc2.open_graph(
                GraphTarget(tenant="acme", graph_id="mem", branch="main")
            )
            assert opened.ok
            assert opened.result["revision"] == rev
            # Payload was not durable → entity_count 0 after synthetic empty snap.
            assert opened.result["entity_count"] == 0
        finally:
            svc2.close()

    def test_file_storage_put_get_roundtrip(self, tmp_path: Path) -> None:
        store = FileGraphStorage(tmp_path / "payloads")
        snap = GraphSnapshot.empty("t", "g", "rev-1", metadata={"k": 1})
        snap.entities.append({"id": "e", "type": "X", "name": "n"})
        store.put_snapshot(snap)
        loaded = store.get_snapshot("t", "g", "rev-1")
        assert loaded is not None
        assert loaded.entities[0]["name"] == "n"
        store.close()


# ---------------------------------------------------------------------------
# Target / envelope contract surface
# ---------------------------------------------------------------------------


class TestTargetAndEnvelopes:
    def test_graph_target_uri_roundtrip(self) -> None:
        t = GraphTarget(tenant="acme", graph_id="skills", branch="main")
        assert t.uri == "kg://acme/skills/branches/main"
        assert GraphTarget.from_uri(t.uri) == t

        r = GraphTarget(tenant="acme", graph_id="skills", revision="kg-rev-abc")
        assert r.uri == "kg://acme/skills/revisions/kg-rev-abc"
        assert GraphTarget.from_uri(r.uri).revision == "kg-rev-abc"

    def test_branch_and_revision_mutually_exclusive(self) -> None:
        with pytest.raises(GraphTargetError) as ei:
            GraphTarget(
                tenant="a",
                graph_id="b",
                branch="main",
                revision="rev-1",
            )
        assert ei.value.code == "TARGET_BRANCH_AND_REVISION"

    def test_write_requires_idempotency_key(self, tmp_path: Path) -> None:
        svc = _open_service(tmp_path)
        try:
            t = GraphTarget(tenant="acme", graph_id="w", branch="main")
            assert svc.create(t, idempotency_key="w-c").ok
            # Bypass convenience wrapper validation by using execute without key.
            req = LifecycleRequest(
                operation="write",
                target=t,
                idempotency_key=None,
                params={"entities": [{"id": "1", "type": "T", "name": "n"}]},
            )
            result = svc.execute(req)
            assert not result.ok
            assert result.error.code == "INVALID_REQUEST"
        finally:
            svc.close()

    def test_not_found_for_unknown_graph(self, tmp_path: Path) -> None:
        svc = _open_service(tmp_path)
        try:
            r = svc.describe(GraphTarget(tenant="acme", graph_id="missing"))
            assert not r.ok
            assert r.error.code == "NOT_FOUND"
        finally:
            svc.close()

    def test_typed_error_closed_vocabulary(self) -> None:
        with pytest.raises(ValueError):
            TypedError(
                code="NOT_A_REAL_CODE",
                message="x",
                retryable=False,
                details={},
            )


# ---------------------------------------------------------------------------
# Concurrency: distinct graph identities via shared service catalog path
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_creates_distinct_graphs(self, tmp_path: Path) -> None:
        catalog_path, storage_path = _paths(tmp_path)
        n = 8
        barrier = threading.Barrier(n)
        errors: List[BaseException] = []
        results: List[str] = []

        def worker(i: int) -> None:
            try:
                svc = GraphService.open(
                    catalog_path,
                    storage_path=storage_path,
                    holder_id=f"w-{i}",
                )
                try:
                    barrier.wait(timeout=15)
                    t = GraphTarget(
                        tenant="shared",
                        graph_id=f"g{i:02d}",
                        branch="main",
                    )
                    r = svc.create(t, idempotency_key=f"cc-{i}")
                    assert r.ok, r.to_json_dict()
                    results.append(r.result["graph_id"])
                finally:
                    svc.close()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=30)

        assert not errors, errors
        assert sorted(results) == [f"g{i:02d}" for i in range(n)]

        with GraphService.open(catalog_path, storage_path=storage_path) as svc:
            listed = svc.list(GraphTarget(tenant="shared", graph_id="list"))
            assert listed.ok
            assert len(listed.result["graphs"]) == n
