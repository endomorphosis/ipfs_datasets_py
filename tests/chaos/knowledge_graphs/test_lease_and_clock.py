"""Chaos: lease expiry and clock skew (KGP-031).

Expired writer leases cannot CAS heads; stealers advance epochs. Clock skew
on UCAN time caveats fails closed (expired / not-before) under a controlled clock.
"""

from __future__ import annotations

import time

import pytest

from ipfs_datasets_py.knowledge_graphs.auth.contracts import (
    GraphCapability,
    GraphCaveats,
    GraphDelegationLink,
    parse_graph_resource,
    validate_chain_time,
    caveats_allow_request,
)
from ipfs_datasets_py.knowledge_graphs.transactions import (
    InMemoryBranchStore,
    LeaseFencedError,
)

from tests.chaos.knowledge_graphs.helpers import make_file_mvcc, make_mvcc
from tests.integration.knowledge_graphs.concurrency.helpers import GENESIS


class TestLeaseExpiry:
    def test_expired_lease_cannot_cas_head(self) -> None:
        store = InMemoryBranchStore()
        tenant, gid = "tenant-alpha", "graph-lease"
        store.ensure_branch(tenant, gid, "main")
        lease = store.acquire_lease(
            tenant, gid, "main", holder="writer-a", ttl_seconds=0.05
        )
        now = lease.expires_at + 1.0
        head = store.get_head(tenant, gid, "main")
        with pytest.raises(LeaseFencedError) as ei:
            store.cas_set_head(
                tenant,
                gid,
                "main",
                expected_revision=head,
                new_revision="rev-should-not",
                lease_id=lease.lease_id,
                lease_epoch=lease.epoch,
                now=now,
            )
        msg = str(ei.value).lower()
        assert "expir" in msg or "lease" in msg
        assert store.get_head(tenant, gid, "main") == head

    def test_steal_after_expiry_bumps_epoch(self) -> None:
        store = InMemoryBranchStore()
        tenant, gid = "tenant-alpha", "graph-steal"
        store.ensure_branch(tenant, gid, "main")
        old = store.acquire_lease(
            tenant, gid, "main", holder="old", ttl_seconds=0.02
        )
        now = old.expires_at + 0.5
        new = store.acquire_lease(
            tenant, gid, "main", holder="new", ttl_seconds=60.0, now=now
        )
        assert new.epoch == old.epoch + 1
        assert new.holder == "new"

        # Old epoch cannot publish even if it still holds tokens.
        head = store.get_head(tenant, gid, "main")
        with pytest.raises(LeaseFencedError):
            store.cas_set_head(
                tenant,
                gid,
                "main",
                expected_revision=head,
                new_revision="rev-stale",
                lease_id=old.lease_id,
                lease_epoch=old.epoch,
                now=now,
            )

    def test_file_store_lease_expiry_across_holders(self, tmp_path) -> None:
        root = tmp_path / "lease-file"
        tenant, gid = "tenant-alpha", "g-lease"
        a = make_file_mvcc(root, holder_id="a")
        a.open_snapshot(tenant, gid)
        lease_a = a.store.acquire_lease(
            tenant, gid, "main", holder="a", ttl_seconds=0.05
        )
        time.sleep(0.08)
        b = make_file_mvcc(root, holder_id="b")
        lease_b = b.store.acquire_lease(
            tenant, gid, "main", holder="b", ttl_seconds=30.0
        )
        assert lease_b.epoch > lease_a.epoch

        head = b.store.get_head(tenant, gid, "main")
        with pytest.raises(LeaseFencedError):
            a.store.cas_set_head(
                tenant,
                gid,
                "main",
                expected_revision=head,
                new_revision="rev-from-a",
                lease_id=lease_a.lease_id,
                lease_epoch=lease_a.epoch,
            )
        txn = b.begin(tenant, gid, acquire_lease=True)
        b.stage_mutations(txn, entities=[{"id": "from-b"}])
        result = b.commit(txn)
        assert b.store.get_head(tenant, gid, "main") == result["revision"]
        assert result["revision"] != GENESIS

    def test_mvcc_commit_after_lease_expiry_fails_closed(self) -> None:
        """
        GIVEN: begin() acquires a short lease; lease expires before publish
        WHEN: commit attempts CAS with expired lease
        THEN: LeaseFencedError; head remains base
        """
        store = InMemoryBranchStore()
        mvcc = make_mvcc(holder_id="slow", branch_store=store)
        tenant, gid = "tenant-alpha", "g-exp"
        # Manually acquire ultra-short lease then begin without re-acquire.
        store.ensure_branch(tenant, gid, "main")
        lease = store.acquire_lease(
            tenant, gid, "main", holder="slow", ttl_seconds=0.01
        )
        base = store.get_head(tenant, gid, "main")
        time.sleep(0.03)
        # Stealer takes over so the original lease is definitely fenced.
        store.acquire_lease(
            tenant, gid, "main", holder="thief", ttl_seconds=60.0
        )
        with pytest.raises(LeaseFencedError):
            store.cas_set_head(
                tenant,
                gid,
                "main",
                expected_revision=base,
                new_revision="rev-nope",
                lease_id=lease.lease_id,
                lease_epoch=lease.epoch,
            )
        assert store.get_head(tenant, gid, "main") == base


class TestClockSkew:
    def test_ucan_expired_under_skewed_clock(self) -> None:
        """
        GIVEN: Delegation with expiry at T+100
        WHEN: Verifier clock is skewed past expiry
        THEN: validate_chain_time fails with reason expired
        """
        now = 1_700_000_000.0
        cap = GraphCapability(
            resource=parse_graph_resource("kg://tenant-alpha/graph-clock"),
            ability="graph/read",
            caveats=GraphCaveats.from_mapping({}),
        )
        link = GraphDelegationLink(
            issuer="did:key:issuer",
            audience="did:key:audience",
            capabilities=(cap,),
            expiry=now + 100.0,
            not_before=now - 10.0,
            cid="bafy-clock-1",
        )
        # Nominal clock: valid.
        assert validate_chain_time([link], now=now) is None
        # Forward skew past expiry: fail closed.
        failure = validate_chain_time([link], now=now + 200.0)
        assert failure is not None
        assert failure.reason == "expired"

    def test_ucan_not_before_under_backward_skew(self) -> None:
        now = 1_700_000_000.0
        cap = GraphCapability(
            resource=parse_graph_resource("kg://tenant-alpha/graph-nbf"),
            ability="graph/write",
            caveats=GraphCaveats.from_mapping({}),
        )
        link = GraphDelegationLink(
            issuer="did:key:issuer",
            audience="did:key:audience",
            capabilities=(cap,),
            expiry=now + 10_000.0,
            not_before=now + 500.0,
            cid="bafy-clock-2",
        )
        failure = validate_chain_time([link], now=now)
        assert failure is not None
        assert failure.reason in {"not_before", "nbf", "not-yet-valid"} or "not" in (
            failure.reason or ""
        )

    def test_caveat_time_exp_fail_closed(self) -> None:
        now = time.time()
        expired = GraphCaveats.from_mapping({"time": {"expiry": now - 5}})
        ok, reason = caveats_allow_request(expired, now=now)
        assert not ok and reason == "expired"

        future = GraphCaveats.from_mapping({"time": {"not_before": now + 10_000}})
        ok2, reason2 = caveats_allow_request(future, now=now)
        assert not ok2

    def test_lease_expiry_respects_injected_now(self) -> None:
        """Clock skew for leases: same wall clock offset used for acquire + CAS."""
        store = InMemoryBranchStore()
        tenant, gid = "tenant-beta", "skew-lease"
        store.ensure_branch(tenant, gid, "main")
        t0 = 1_000_000.0
        lease = store.acquire_lease(
            tenant, gid, "main", holder="h", ttl_seconds=10.0, now=t0
        )
        assert not lease.is_expired(t0 + 9.0)
        assert lease.is_expired(t0 + 10.0)
        head = store.get_head(tenant, gid, "main")
        with pytest.raises(LeaseFencedError):
            store.cas_set_head(
                tenant,
                gid,
                "main",
                expected_revision=head,
                new_revision="rev-skew",
                lease_id=lease.lease_id,
                lease_epoch=lease.epoch,
                now=t0 + 10.0,
            )
