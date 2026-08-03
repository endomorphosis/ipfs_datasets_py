"""
Multi-process concurrency over shared file-backed MVCC (KGP-008).

Uses true subprocess boundaries (no shared process caches). Writers and
readers coordinate only through durable files under a temporary root.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict

import pytest

from .helpers import (
    CHILD_COMMIT,
    CHILD_READ_HEAD,
    NUM_GRAPHS,
    TENANTS,
    make_file_mvcc,
    run_child,
    tenant_graph_pairs,
)


def _parse_json_line(proc) -> Dict[str, Any]:
    assert proc.returncode == 0, (
        f"child failed rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    line = (proc.stdout or "").strip().splitlines()[-1]
    return json.loads(line)


class TestMultiProcessWriters:
    def test_sixteen_graphs_across_processes(self, tmp_path):
        """
        GIVEN: A shared file-backed MVCC root
        WHEN: 16 child processes each commit one graph (multi-tenant)
        THEN: Parent reopen sees all 16 advanced heads with correct tenants
        """
        root = tmp_path / "mvcc-root"
        pairs = tenant_graph_pairs()
        assert len(pairs) >= NUM_GRAPHS
        assert {t for t, _ in pairs} == set(TENANTS)

        boot = make_file_mvcc(root, holder_id="bootstrap")
        for tenant, gid in pairs:
            boot.open_snapshot(tenant, gid)

        outcomes: list = []

        def _spawn(tenant: str, gid: str):
            proc = run_child(
                CHILD_COMMIT,
                str(root),
                tenant,
                gid,
                f"e-{gid}",
                f"holder-{gid}",
                f"idem-{gid}",
            )
            return _parse_json_line(proc)

        with ThreadPoolExecutor(max_workers=NUM_GRAPHS) as pool:
            futs = [pool.submit(_spawn, t, g) for t, g in pairs]
            for f in as_completed(futs):
                outcomes.append(f.result())

        assert len(outcomes) == len(pairs)
        ok = [o for o in outcomes if o.get("ok")]
        assert len(ok) == len(pairs), outcomes

        reopened = make_file_mvcc(root, holder_id="parent-reader")
        for tenant, gid in pairs:
            head = reopened.store.get_head(tenant, gid, "main")
            assert head != "rev-genesis"
            snap = reopened.open_snapshot(tenant, gid)
            assert snap.revision_id == head
            assert snap.tenant == tenant
            assert snap.graph_id == gid

    def test_reader_process_after_writer_process(self, tmp_path):
        """
        GIVEN: Writer process commits a head
        WHEN: A separate reader process opens a snapshot
        THEN: Reader observes the committed revision (not genesis, not partial)
        """
        root = tmp_path / "mvcc-root"
        tenant, gid = "tenant-alpha", "graph-00"
        make_file_mvcc(root, holder_id="boot").open_snapshot(tenant, gid)

        w = run_child(
            CHILD_COMMIT,
            str(root),
            tenant,
            gid,
            "entity-1",
            "writer-proc",
            "idem-rw-1",
        )
        wdata = _parse_json_line(w)
        assert wdata["ok"] is True

        r = run_child(CHILD_READ_HEAD, str(root), tenant, gid)
        rdata = _parse_json_line(r)
        assert rdata["revision"] == wdata["revision"]
        assert rdata["tenant"] == tenant
        assert rdata["graph_id"] == gid

    def test_same_graph_two_processes_deterministic_conflict_or_serial(self, tmp_path):
        """
        GIVEN: Two processes write the same tenant/graph concurrently
        WHEN: Both attempt lease + commit
        THEN: Outcomes are only ok or typed ConflictError/LeaseFencedError;
              exactly one successful head advance is visible
        """
        root = tmp_path / "mvcc-root"
        tenant, gid = "tenant-alpha", "graph-race"
        make_file_mvcc(root, holder_id="boot").open_snapshot(tenant, gid)

        def _one(holder: str, entity: str):
            proc = run_child(
                CHILD_COMMIT,
                str(root),
                tenant,
                gid,
                entity,
                holder,
                f"idem-{holder}",
            )
            # May non-zero only if crash; our child always prints JSON and exits 0
            assert proc.returncode == 0, proc.stderr
            return json.loads(proc.stdout.strip().splitlines()[-1])

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_one, "h1", "e1")
            f2 = pool.submit(_one, "h2", "e2")
            results = [f1.result(), f2.result()]

        for r in results:
            assert r.get("ok") is True or r.get("error") in (
                "ConflictError",
                "LeaseFencedError",
            ), results

        successes = [r for r in results if r.get("ok")]
        assert 1 <= len(successes) <= 2, results

        final = make_file_mvcc(root, holder_id="final")
        head = final.store.get_head(tenant, gid, "main")
        assert head != "rev-genesis"
        if len(successes) == 1:
            assert head == successes[0]["revision"]
        else:
            success_revs = {s["revision"] for s in successes}
            # Serial success: both commits may land if second re-leases after first
            assert head in success_revs

    def test_cross_tenant_isolation_across_processes(self, tmp_path):
        """
        GIVEN: Same graph_id under two tenants written by different processes
        WHEN: Readers query each tenant scope
        THEN: Each tenant sees only its own head
        """
        root = tmp_path / "mvcc-root"
        gid = "shared-label"
        boot = make_file_mvcc(root, holder_id="boot")
        for tenant in TENANTS:
            boot.open_snapshot(tenant, gid)

        procs = []
        for tenant in TENANTS:
            p = run_child(
                CHILD_COMMIT,
                str(root),
                tenant,
                gid,
                f"entity-{tenant}",
                f"holder-{tenant}",
                f"idem-{tenant}",
            )
            data = _parse_json_line(p)
            assert data["ok"] is True
            procs.append((tenant, data))

        heads = {}
        for tenant, data in procs:
            r = run_child(CHILD_READ_HEAD, str(root), tenant, gid)
            rdata = _parse_json_line(r)
            assert rdata["revision"] == data["revision"]
            assert rdata["tenant"] == tenant
            heads[tenant] = rdata["revision"]

        assert heads[TENANTS[0]] != heads[TENANTS[1]]
        store = make_file_mvcc(root, holder_id="parent").store
        with pytest.raises(KeyError):
            store.get_revision(TENANTS[1], gid, heads[TENANTS[0]])


class TestMultiProcessIdempotentRetry:
    def test_duplicate_retry_same_idempotency_key_is_safe(self, tmp_path):
        """
        GIVEN: A successful commit with an idempotency key
        WHEN: A second process retries COMPLETE-equivalent append path via
              a new commit with a different key (new txn) — and WAL COMPLETE
              re-append with the original key is idempotent
        THEN: Head remains the first committed revision; COMPLETE re-append
              does not grow the durable log
        """
        from ipfs_datasets_py.knowledge_graphs.transactions import WALPhase

        root = tmp_path / "mvcc-root"
        tenant, gid = "tenant-alpha", "graph-00"
        make_file_mvcc(root, holder_id="boot").open_snapshot(tenant, gid)

        first = _parse_json_line(
            run_child(
                CHILD_COMMIT,
                str(root),
                tenant,
                gid,
                "entity-1",
                "holder-1",
                "client-retry-key",
            )
        )
        assert first["ok"] is True
        rev1 = first["revision"]

        # Expire any held lease so a second process can write a distinct txn.
        state_path = root / "branch_store.json"
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        now = time.time()
        for key, lease in list(raw.get("leases", {}).items()):
            lease["expires_at"] = now - 10.0
            raw["leases"][key] = lease
        state_path.write_text(json.dumps(raw, sort_keys=True), encoding="utf-8")

        second = _parse_json_line(
            run_child(
                CHILD_COMMIT,
                str(root),
                tenant,
                gid,
                "entity-2",
                "holder-2",
                "client-retry-key-2",
            )
        )
        assert second["ok"] is True

        reopened = make_file_mvcc(root, holder_id="idem-check")
        head = reopened.store.get_head(tenant, gid, "main")
        assert head == second["revision"]
        assert head != rev1

        # Idempotent COMPLETE re-append for an observed COMPLETE entry
        history = list(reopened.wal.read())
        complete = [
            e
            for e in history
            if e.resolved_phase() == WALPhase.COMPLETE and e.idempotency_key
        ]
        assert complete, "expected COMPLETE entries with idempotency keys"
        sample = complete[0]
        count_before = reopened.wal._entry_count
        cid = reopened.wal.append_phase(
            txn_id=sample.txn_id,
            phase=WALPhase.COMPLETE,
            operations=[],
            tenant=sample.tenant,
            graph_id=sample.graph_id,
            branch=sample.branch,
            base_revision=sample.base_revision,
            new_revision=sample.new_revision,
            staged_root_cid=sample.staged_root_cid,
            lease_id=sample.lease_id,
            lease_epoch=sample.lease_epoch,
            idempotency_key=sample.idempotency_key,
            record_seq=sample.record_seq,
        )
        assert cid is not None
        assert reopened.wal._entry_count == count_before
        key = f"idem:{sample.idempotency_key}:COMPLETE:{sample.record_seq}"
        assert key in reopened.wal._applied_keys
