"""Chaos: process-kill smoke bridge (KGP-031).

Delegates to the durable WAL-boundary crash suite while providing an
explicit process-kill entry point for the soak/chaos acceptance matrix.
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.knowledge_graphs.transactions import RecoveryAction, WALPhase

from tests.integration.knowledge_graphs.concurrency.helpers import (
    CHILD_READ_HEAD,
    CHILD_RECOVER,
    CHILD_STOP_AT_PHASE,
    GENESIS,
    make_file_mvcc,
    run_child,
)


def _parse(proc):
    assert proc.returncode == 0, (
        f"child failed rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    return json.loads((proc.stdout or "").strip().splitlines()[-1])


class TestProcessKill:
    @pytest.mark.parametrize("stop_phase", ["INTENT", "PREPARE", "PUBLISH", "COMPLETE"])
    def test_process_stop_at_phase_recovers_legal_head(self, tmp_path, stop_phase):
        root = tmp_path / f"kill-{stop_phase.lower()}"
        tenant, gid = "tenant-alpha", "graph-kill"
        make_file_mvcc(root, holder_id="boot").open_snapshot(tenant, gid)

        stopped = _parse(
            run_child(
                CHILD_STOP_AT_PHASE,
                str(root),
                tenant,
                gid,
                "entity-kill",
                f"holder-{stop_phase}",
                stop_phase,
                f"idem-{stop_phase}",
            )
        )
        assert stopped["stopped"] == stop_phase

        recovered = _parse(
            run_child(CHILD_RECOVER, str(root), json.dumps([[tenant, gid]]))
        )
        d = next(x for x in recovered["decisions"] if x["txn_id"] == stopped["txn_id"])
        expected = {
            "INTENT": RecoveryAction.DISCARD_STAGED.value,
            "PREPARE": RecoveryAction.DISCARD_STAGED.value,
            "PUBLISH": RecoveryAction.FINISH_PUBLICATION.value,
            "COMPLETE": RecoveryAction.IDEMPOTENT_SKIP.value,
        }[stop_phase]
        assert d["action"] == expected

        final_head = recovered["heads"][f"{tenant}/{gid}"]
        allowed = {GENESIS}
        if stop_phase in ("PUBLISH", "COMPLETE"):
            allowed.add(stopped.get("staged_revision") or stopped.get("revision"))
        assert final_head in allowed

        reader = _parse(run_child(CHILD_READ_HEAD, str(root), tenant, gid))
        assert reader["revision"] in allowed

    def test_kill_then_new_writer_can_commit(self, tmp_path):
        """After PREPARE kill + recovery, a fresh writer advances the head."""
        import time as _time

        root = tmp_path / "kill-resume"
        tenant, gid = "tenant-alpha", "graph-resume"
        make_file_mvcc(root, holder_id="boot").open_snapshot(tenant, gid)
        stopped = _parse(
            run_child(
                CHILD_STOP_AT_PHASE,
                str(root),
                tenant,
                gid,
                "e-stop",
                "h-stop",
                "PREPARE",
                "idem-stop",
            )
        )
        assert stopped["stopped"] == "PREPARE"
        _parse(run_child(CHILD_RECOVER, str(root), json.dumps([[tenant, gid]])))

        # Recovery discards staged PREPARE work but the killed writer's lease
        # may still be live. Steal it by advancing the clock past expiry.
        fresh = make_file_mvcc(root, holder_id="fresh")
        far = _time.time() + 10**9
        stolen = fresh.store.acquire_lease(
            tenant, gid, "main", holder="fresh", ttl_seconds=60.0, now=far
        )
        assert stolen.holder == "fresh"
        # begin() renews for the same holder using wall clock; the stolen
        # lease expires far in the future so renewal succeeds.
        txn = fresh.begin(tenant, gid, acquire_lease=True)
        fresh.stage_mutations(txn, entities=[{"id": "after-kill"}])
        # CAS must use a non-expired lease relative to wall clock; re-acquire
        # with wall-clock now after forced-steal epoch is already ours.
        result = fresh.commit(txn)
        assert result["revision"] != GENESIS
        assert fresh.store.get_head(tenant, gid, "main") == result["revision"]
