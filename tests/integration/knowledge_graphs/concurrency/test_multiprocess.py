"""Multi-process concurrency over shared file-backed MVCC (KGP-008).

Uses true subprocess boundaries (no shared process caches). Writers and
readers coordinate only through durable files under a temporary root.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

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
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


class TestMultiProcessWriters:
    def test_sixteen_graphs_across_processes(self, tmp_path: Path):
        """
        GIVEN: A shared file-backed MVCC root
        WHEN: 16 child processes each commit one graph (multi-tenant)
        THEN: Parent reopen sees all 16 advanced heads with correct tenants
        """
        root = tmp_path / "mvcc-root"
        pairs = tenant_graph_pairs(NUM_GRAPHS)
        assert len(pairs) >= 16
        assert {t for t, _ in pairs} >= set(TENANTS)

        # Bootstrap genesis so children only need to commit.
        boot = make_file_mvcc(root, holder_id="bootstrap")
        for tenant, gid in pairs:
            boot.open_snapshot(tenant, gid)

        def _spawn(pair: Tuple[str, str]) -> Dict[str, Any]:
            tenant, gid = pair
            proc = run_child(
                CHILD_COMMIT,
                str(root),
                tenant,
                gid,
                f"entity-{tenant}-{gid}",
                f"holder-{tenant}-{gid}",
                f"idem-{tenant}-{gid}",
            )
            return _parse_json_line(proc)

        # Parallel process launches (thread pool only orchestrates subprocesses).
        outcomes: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(_spawn, p) for p in pairs]
            for f in as_completed(futs):
                outcomes.append(f.result())

        assert len(outcomes) == len(pairs)
        ok = [o for o in outcomes if o.get("ok")]
        # Distinct graphs should not CAS-conflict with each other; all succeed.
        assert len(ok) == len(pairs), outcomes

        # Fresh process-local reopen (parent) verifies durability.
        reopened = make_file_mvcc(root, holder_id="parent-reader")
        for tenant, gid in pairs:
            head = reopened.store.get_head(tenant, gid, "main")
            assert head != "rev-genesis"
            snap = reopened.open_snapshot(tenant, gid)
            assert snap.revision_id == head
            assert snap.tenant == tenant
            assert snap.graph_id == gid

    def test_reader_process_after_writer_process(self, tmp_path: Path):
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

    def test_same_graph_two_processes_deterministic_conflict_or_serial(self, tmp_path: Path):
        """
        GIVEN: Two processes write the same tenant/graph concurrently
        WHEN: Both attempt lease + commit
        THEN: Outcomes are only ok or typed ConflictError/LeaseFencedError;
              final head is exactly one committed revision (no torn state)
        """
        root = tmp_path / "mvcc-root"
        tenant, gid = "tenant-beta", "graph-race"
        make_file_mvcc(root, holder_id="boot").open_snapshot(tenant, gid)

        def _one(tag: str) -> Dict[str, Any]:
            proc = run_child(
                CHILD_COMMIT,
                str(root),
                tenant,
                gid,
                f"entity-{tag}",
                f"holder-{tag}",
                f"idem-{tag}",
            )
            # May non-zero only on unexpected errors; typed failures still exit 0.
            if proc.returncode != 0:
                return {
                    "ok": False,
                    "error": "ProcessError",
                    "message": proc.stderr,
                    "stdout": proc.stdout,
                }
            return json.loads(proc.stdout.strip().splitlines()[-1])

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_one, "a")
            f2 = pool.submit(_one, "b")
            results = [f1.result(), f2.result()]

        for r in results:
            assert r.get("error") in (None, "ConflictError", "LeaseFencedError") or r.get(
                "ok"
            ), results

        successes = [r for r in results if r.get("ok")]
        # At least one must fully commit; both may if they serialize via leases.
        assert len(successes) >= 1, results

        final = make_file_mvcc(root, holder_id="final")
        head = final.store.get_head(tenant, gid, "main")
        assert head != "rev-genesis"
        # Head must match one of the successful revisions if present
        success_revs = {r["revision"] for r in successes}
        assert head in success_revs

    def test_cross_tenant_isolation_across_processes(self, tmp_path: Path):
        """
        GIVEN: Same graph_id under two tenants written by different processes
        WHEN: Readers query each tenant scope
        THEN: Each tenant sees only its own head
        """
        root = tmp_path / "mvcc-root"
        gid = "shared-label"
        for tenant in TENANTS:
            make_file_mvcc(root, holder_id="boot").open_snapshot(tenant, gid)

        procs = []
        for tenant in TENANTS:
            procs.append(
                run_child(
                    CHILD_COMMIT,
                    str(root),
                    tenant,
                    gid,
                    f"entity-{tenant}",
                    f"holder-{tenant}",
                    f"idem-{tenant}",
                )
            )
        data = [_parse_json_line(p) for p in procs]
        assert all(d["ok"] for d in data)

        heads = {}
        for tenant in TENANTS:
            r = _parse_json_line(run_child(CHILD_READ_HEAD, str(root), tenant, gid))
            heads[tenant] = r["revision"]
            assert r["tenant"] == tenant

        assert heads[TENANTS[0]] != heads[TENANTS[1]]

        # Parent store also isolates revision records by tenant key.
        store = make_file_mvcc(root, holder_id="parent").store
        with pytest.raises(KeyError):
            store.get_revision(TENANTS[1], gid, heads[TENANTS[0]])


class TestMultiProcessIdempotentRetry:
    def test_duplicate_retry_same_idempotency_key_is_safe(self, tmp_path: Path):
        """
        GIVEN: A successful commit with an idempotency key
        WHEN: A second process retries COMPLETE-equivalent append path via
              a new commit with a different key (new txn) — and WAL phase
              replay is exercised in-process with the same key
        THEN: Head remains a single committed revision; duplicate COMPLETE
              phase does not create a second physical entry for that key
        """
        from ipfs_datasets_py.knowledge_graphs.transactions import WALPhase

        root = tmp_path / "mvcc-root"
        tenant, gid = "tenant-alpha", "graph-idem"
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

        # Expire the first writer's lease so a different process holder can
        # acquire (fencing epoch bumps). No timing sleep — force expires_at.
        state_path = root / "branch_store.json"
        import time as _time

        raw = json.loads(state_path.read_text())
        for key, lease in list(raw.get("leases", {}).items()):
            lease["expires_at"] = _time.time() - 1.0
            raw["leases"][key] = lease
        state_path.write_text(json.dumps(raw, sort_keys=True))

        # Second independent commit (new txn) advances further — proves
        # multi-process durability. Idempotent WAL phase replay is checked below.
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
        assert second["ok"] is True, second

        reopened = make_file_mvcc(root, holder_id="idem-check")
        head = reopened.store.get_head(tenant, gid, "main")
        assert head == second["revision"]
        assert head != rev1

        # Exact COMPLETE phase retry is a no-op at the WAL layer.
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
            idempotency_key=sample.idempotency_key,
            record_seq=sample.record_seq,
            operations=[],
        )
        key = f"idem:{sample.idempotency_key}:COMPLETE:{sample.record_seq}"
        assert cid == reopened.wal._applied_keys[key]
        assert reopened.wal._entry_count == count_before
        assert reopened.store.get_head(tenant, gid, "main") == head
