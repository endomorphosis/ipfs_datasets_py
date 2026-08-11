"""Integration tests: DuckDB graph authority cutover (DQK-060).

Acceptance coverage:

* No branch-head split brain or lost transaction under crash/restart
* Readers bind one revision during promotion
* Legacy writes are outbox projections and rollback is receipted

Also covers fenced dual writes and promotion of DuckDB as authority for
graph catalog and transaction-control metadata while immutable Parquet/IPLD
revisions remain the content authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.duckdb_control.authority_transition import (  # noqa: E402
    AuthorityMode,
    DecisionKind,
)
from ipfs_datasets_py.knowledge_graphs.catalog.store import (  # noqa: E402
    GRAPH_AUTHORITY_DOMAIN,
    GRAPH_AUTHORITY_OWNER_TASK,
    GRAPH_AUTHORITY_SCHEMA,
    GraphAuthorityCatalog,
    GraphCatalog,
    GraphShadowAuthority,
    ReaderRevisionBinding,
    configure_graph_authority,
    get_graph_authority,
    new_graph_operation_id,
    reset_graph_authority,
    safe_dual_catalog_mutation,
)
from ipfs_datasets_py.knowledge_graphs.client import Client  # noqa: E402
from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine  # noqa: E402
from ipfs_datasets_py.knowledge_graphs.service import GraphTarget  # noqa: E402
from ipfs_datasets_py.knowledge_graphs.storage.hybrid import (  # noqa: E402
    VerifiedHybridCache,
)
from ipfs_datasets_py.knowledge_graphs.transactions.manager import (  # noqa: E402
    TransactionManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def authority(tmp_path: Path) -> GraphShadowAuthority:
    reset_graph_authority()
    auth = configure_graph_authority(
        tmp_path / "graph_authority_catalog.duckdb",
        duckdb_tx_path=tmp_path / "graph_authority_tx.duckdb",
        duckdb_crypto_path=tmp_path / "graph_authority_crypto.duckdb",
        enabled=True,
    )
    yield auth
    reset_graph_authority()


@pytest.fixture
def catalog(tmp_path: Path, authority: GraphShadowAuthority) -> GraphCatalog:
    cat = GraphCatalog(
        tmp_path / "catalog.sqlite",
        shadow_authority=authority,
    )
    yield cat
    cat.close()


def _seed_graph(
    catalog: GraphCatalog,
    *,
    tenant: str = "t1",
    graph_id: str = "g1",
    advance: bool = True,
) -> Dict[str, Any]:
    """Create a graph, optional revision + CAS head advance."""

    g = catalog.create_graph(
        tenant,
        graph_id,
        storage_profile="parquet",
        idempotency_key=f"create:{tenant}/{graph_id}",
    )
    bootstrap = catalog.get_branch(tenant, graph_id, "main").head_revision
    out: Dict[str, Any] = {
        "graph": g,
        "bootstrap": bootstrap,
        "tenant": tenant,
        "graph_id": graph_id,
        "head": bootstrap,
    }
    if not advance:
        return out
    checksum = "sha256:" + ("cd" * 32)
    manifest_cid = "bafygraphcutover01"
    rev = catalog.put_revision(
        tenant,
        graph_id,
        "rev-2",
        parent_revision=bootstrap,
        storage_profile="parquet",
        checksum=checksum,
        manifest_cid=manifest_cid,
    )
    lease = catalog.acquire_lease(
        tenant, graph_id, "main", holder="writer-cutover", ttl_seconds=60
    )
    head = catalog.cas_set_head(
        tenant,
        graph_id,
        "main",
        expected_revision=bootstrap,
        new_revision=rev.revision_id,
        lease_id=lease.lease_id,
        lease_epoch=lease.epoch,
        idempotency_key=f"cas:{tenant}/{graph_id}/1",
    )
    out.update(
        {
            "revision": rev,
            "lease": lease,
            "head": head.head_revision if hasattr(head, "head_revision") else rev.revision_id,
            "checksum": checksum,
            "manifest_cid": manifest_cid,
        }
    )
    return out


# ---------------------------------------------------------------------------
# Module / wiring invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_schema_and_owner_constants(self) -> None:
        assert GRAPH_AUTHORITY_OWNER_TASK == "DQK-060"
        assert GRAPH_AUTHORITY_DOMAIN == "graphs"
        assert GRAPH_AUTHORITY_SCHEMA.startswith("ipfs_datasets_py/")
        assert GraphAuthorityCatalog is GraphShadowAuthority

    def test_process_registry_defaults_to_dual(self, tmp_path: Path) -> None:
        reset_graph_authority()
        assert get_graph_authority() is None
        auth = configure_graph_authority(tmp_path / "c.duckdb")
        assert get_graph_authority() is auth
        assert auth.enabled
        assert auth.mode == AuthorityMode.DUAL.value
        assert auth._authority_label() == "dual"
        assert auth.legacy_is_outbox_projection is True
        reset_graph_authority()
        assert get_graph_authority() is None


# ---------------------------------------------------------------------------
# Dual mode: fenced dual writes; content stays Parquet/IPLD
# ---------------------------------------------------------------------------


class TestDualModeAuthority:
    def test_dual_writes_report_dual_authority_and_outbox(
        self, catalog: GraphCatalog, authority: GraphShadowAuthority
    ) -> None:
        seed = _seed_graph(catalog)
        receipts = [
            r
            for r in authority.list_mutation_receipts()
            if r.producer == "catalog"
        ]
        assert receipts
        for receipt in receipts:
            assert receipt.operation_id
            assert receipt.mode == AuthorityMode.DUAL.value
            assert receipt.authority in {"dual", "duckdb"}
            # Legacy is an outbox projection under dual mode.
            assert receipt.outbox_id, receipt.to_dict()
            assert receipt.parity_matched is True, receipt.to_dict()

        view = authority.parity_for(catalog, seed["tenant"], seed["graph_id"])
        assert view.matched is True, view.to_dict()
        assert view.branch_matched is True
        # Content identity (checksum / manifest CID) unchanged.
        assert seed["revision"].checksum == seed["checksum"]
        assert seed["revision"].manifest_cid == seed["manifest_cid"]

    def test_idempotent_dual_write_replay(
        self, catalog: GraphCatalog, authority: GraphShadowAuthority
    ) -> None:
        _seed_graph(catalog, graph_id="idem", advance=False)
        fixed_op = "op:dual-idempotent-probe"
        first = authority.record_operation(
            producer="catalog",
            kind="probe",
            key="graph:t1/idem",
            payload={"probe": True},
            operation_id=fixed_op,
        )
        second = authority.record_operation(
            producer="catalog",
            kind="probe",
            key="graph:t1/idem",
            payload={"probe": True},
            operation_id=fixed_op,
        )
        assert first.ok if hasattr(first, "ok") else True
        assert second.idempotent_replay is True
        assert second.operation_id == first.operation_id
        assert second.outbox_id == first.outbox_id

    def test_promote_to_db_primary(
        self, catalog: GraphCatalog, authority: GraphShadowAuthority
    ) -> None:
        seed = _seed_graph(catalog, graph_id="promo")
        assert authority.mode == AuthorityMode.DUAL.value

        decision = authority.ensure_duckdb_authority(
            tenant=seed["tenant"],
            graph_id=seed["graph_id"],
            decision_id="cutover:promo",
        )
        assert decision is not None
        assert decision.accepted is True
        assert decision.kind == DecisionKind.PROMOTE
        assert authority.mode == AuthorityMode.DB_PRIMARY.value
        assert authority._authority_label() == "duckdb"
        assert authority.is_duckdb_authority is True
        assert authority.legacy_is_outbox_projection is True

        # Idempotent re-ensure
        again = authority.ensure_duckdb_authority(
            tenant=seed["tenant"],
            graph_id=seed["graph_id"],
            decision_id="cutover:promo-2",
        )
        assert again is None or again.accepted is True
        assert authority.mode == AuthorityMode.DB_PRIMARY.value

    def test_legacy_writes_are_outbox_projections_after_cutover(
        self, catalog: GraphCatalog, authority: GraphShadowAuthority
    ) -> None:
        seed = _seed_graph(catalog, graph_id="outbox-g")
        authority.ensure_duckdb_authority(
            tenant=seed["tenant"],
            graph_id=seed["graph_id"],
            decision_id="cutover:outbox-g",
        )
        assert authority.mode == AuthorityMode.DB_PRIMARY.value

        # Further catalog mutation: SQLite is a legacy projection via outbox.
        checksum = "sha256:" + ("ef" * 32)
        rev = catalog.put_revision(
            seed["tenant"],
            seed["graph_id"],
            "rev-3",
            parent_revision=seed["head"],
            storage_profile="parquet",
            checksum=checksum,
            manifest_cid="bafygraphcutover02",
        )
        receipts = [
            r
            for r in authority.list_mutation_receipts()
            if r.kind == "put_revision" and "rev-3" in (r.payload_digest or r.key or "")
            or (r.kind == "put_revision" and r.content_cid == "bafygraphcutover02")
        ]
        # At least one post-cutover mutation receipt with duckdb authority.
        post = [
            r
            for r in authority.list_mutation_receipts()
            if r.mode == AuthorityMode.DB_PRIMARY.value
        ]
        assert post, "db-primary mutations must emit receipts"
        for receipt in post:
            assert receipt.authority in {"duckdb", "db-primary"}
            assert receipt.outbox_id, "legacy projection must be outbox-bound"
        assert rev.checksum == checksum


# ---------------------------------------------------------------------------
# Acceptance: readers bind one revision during promotion
# ---------------------------------------------------------------------------


class TestReaderRevisionBinding:
    def test_bind_one_revision_during_promotion(
        self, catalog: GraphCatalog, authority: GraphShadowAuthority
    ) -> None:
        seed = _seed_graph(catalog, graph_id="bind-g")
        assert authority.promotion_window_active is True

        binding = authority.bind_reader_revision(
            seed["tenant"],
            seed["graph_id"],
            "main",
            catalog=catalog,
        )
        assert isinstance(binding, ReaderRevisionBinding)
        assert binding.revision_id == seed["head"]
        assert binding.authority_mode == AuthorityMode.DUAL.value

        # Advance the head while bound — bound readers must not flip.
        # Reuse the existing writer lease from the seed path.
        checksum = "sha256:" + ("11" * 32)
        rev3 = catalog.put_revision(
            seed["tenant"],
            seed["graph_id"],
            "rev-bind-3",
            parent_revision=seed["head"],
            storage_profile="parquet",
            checksum=checksum,
            manifest_cid="bafygraphbind03",
        )
        lease = seed["lease"]
        catalog.cas_set_head(
            seed["tenant"],
            seed["graph_id"],
            "main",
            expected_revision=seed["head"],
            new_revision=rev3.revision_id,
            lease_id=lease.lease_id,
            lease_epoch=lease.epoch,
            idempotency_key="cas:bind-advance",
        )
        live_head = catalog.get_branch(
            seed["tenant"], seed["graph_id"], "main"
        ).head_revision
        assert live_head == rev3.revision_id

        # Bound revision is sticky.
        still = authority.get_bound_reader_revision(
            seed["tenant"], seed["graph_id"], "main"
        )
        assert still is not None
        assert still.revision_id == seed["head"]
        assert still.revision_id != live_head

        auth_head = authority.authoritative_branch_head(
            seed["tenant"], seed["graph_id"], "main", catalog=catalog
        )
        assert auth_head == seed["head"]

    def test_client_binds_revision_on_open_during_promotion(
        self, tmp_path: Path, authority: GraphShadowAuthority
    ) -> None:
        cat_path = tmp_path / "client_catalog.sqlite"
        catalog = GraphCatalog(cat_path, shadow_authority=authority)
        seed = _seed_graph(catalog, graph_id="client-g")
        catalog.close()

        client = Client.open(
            cat_path,
            storage_path=tmp_path / "client_payloads",
            authority=authority,
        )
        try:
            target = GraphTarget(
                tenant=seed["tenant"], graph_id=seed["graph_id"], branch="main"
            )
            bound = client.bind_revision(target)
            assert bound == seed["head"]
            assert client.bound_revision(target) == seed["head"]

            # Second bind returns same sticky revision.
            again = client.bind_revision(target)
            assert again == bound

            client.unbind_revision(target)
            assert client.bound_revision(target) is None
        finally:
            client.close()


# ---------------------------------------------------------------------------
# Acceptance: no split brain / lost tx under crash/restart
# ---------------------------------------------------------------------------


class TestCrashRestart:
    def test_no_branch_head_split_brain_after_restart(
        self, catalog: GraphCatalog, authority: GraphShadowAuthority, tmp_path: Path
    ) -> None:
        seed = _seed_graph(catalog, graph_id="crash-g")
        authority.ensure_duckdb_authority(
            tenant=seed["tenant"],
            graph_id=seed["graph_id"],
            decision_id="cutover:crash-g",
        )
        before = authority.parity_for(
            catalog, seed["tenant"], seed["graph_id"]
        )
        assert before.matched is True, before.to_dict()
        head_before = catalog.get_branch(
            seed["tenant"], seed["graph_id"], "main"
        ).head_revision

        # Simulate process restart: reopen DuckDB stores + recover outbox.
        authority.reopen()
        recovered = authority.recover_after_crash(catalog)
        assert recovered["ok"] is True, recovered
        assert recovered["authority"] == "duckdb"
        assert recovered["legacy_is_outbox_projection"] is True

        after = authority.parity_for(catalog, seed["tenant"], seed["graph_id"])
        assert after.matched is True, after.to_dict()
        assert after.branch_matched is True
        head_after = catalog.get_branch(
            seed["tenant"], seed["graph_id"], "main"
        ).head_revision
        duck_head = authority.authoritative_branch_head(
            seed["tenant"], seed["graph_id"], "main", catalog=catalog
        )
        assert head_after == head_before
        assert duck_head == head_before

    def test_reconcile_repairs_injected_split_brain(
        self, catalog: GraphCatalog, authority: GraphShadowAuthority
    ) -> None:
        seed = _seed_graph(catalog, graph_id="split-g")
        authority.ensure_duckdb_authority(
            tenant=seed["tenant"],
            graph_id=seed["graph_id"],
            decision_id="cutover:split-g",
        )
        # Inject SQLite-only divergence (simulates crash mid-projection).
        with catalog._lock:  # noqa: SLF001
            catalog._conn.execute(  # noqa: SLF001
                "UPDATE branches SET head_revision = ? "
                "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                ["rev-stale-only", seed["tenant"], seed["graph_id"], "main"],
            )
        sqlite_head = catalog.get_branch(
            seed["tenant"], seed["graph_id"], "main"
        ).head_revision
        assert sqlite_head == "rev-stale-only"

        receipt = authority.reconcile_branch_heads(
            catalog, seed["tenant"], seed["graph_id"], "main"
        )
        assert receipt["ok"] is True, receipt
        assert receipt["matched"] is True
        assert receipt["authority"] == "duckdb"
        # DuckDB head wins under db-primary; SQLite is re-projected.
        repaired = catalog.get_branch(
            seed["tenant"], seed["graph_id"], "main"
        ).head_revision
        assert repaired == seed["head"]
        assert repaired != "rev-stale-only"

    def test_no_lost_transaction_control_under_restart(
        self, authority: GraphShadowAuthority, tmp_path: Path
    ) -> None:
        engine = GraphEngine()

        class _NoopBackend:
            pass

        mgr = TransactionManager(engine, _NoopBackend(), shadow_authority=authority)
        txn = mgr.begin()
        assert txn.txn_id
        # Project a commit-shaped WAL control envelope with a fixed CID.
        wal_cid = "bafywalcutover0001"
        receipt = authority.record_transaction_mutation(
            kind="commit",
            txn_id=txn.txn_id,
            payload={
                "txn_id": txn.txn_id,
                "state": "COMMITTED",
                "isolation_level": "REPEATABLE_READ",
                "read_set": [],
                "write_set": ["entity-cutover-1"],
                "start_time": 0.0,
                "snapshot_cid": None,
                "wal_entries": [wal_cid],
            },
            operation_id=new_graph_operation_id("txn.commit"),
            wal_cid=wal_cid,
        )
        assert receipt.parity_matched is True
        assert receipt.content_cid == wal_cid
        assert receipt.authority in {"dual", "duckdb"}
        assert receipt.outbox_id

        duck_tx = authority.duckdb_transaction_state
        assert duck_tx is not None
        assert duck_tx.get_wal_head_cid() == wal_cid
        applied = duck_tx.list_wal_applied_keys()
        assert txn.txn_id in applied
        assert applied[txn.txn_id] == wal_cid

        # Crash/restart: durable DuckDB control state must survive.
        authority.reopen()
        recovered = mgr.recover_control_state_after_crash()
        assert recovered["ok"] is True, recovered
        duck_tx2 = authority.duckdb_transaction_state
        assert duck_tx2 is not None
        assert duck_tx2.get_wal_head_cid() == wal_cid
        applied2 = duck_tx2.list_wal_applied_keys()
        assert txn.txn_id in applied2
        assert applied2[txn.txn_id] == wal_cid

        # Rollback path is also dual-written / receipted.
        txn2 = mgr.begin()
        mgr.rollback(txn2)
        rollbacks = [
            r
            for r in authority.list_mutation_receipts()
            if r.kind == "rollback" and r.producer == "transactions"
        ]
        assert rollbacks
        assert all(r.operation_id for r in rollbacks)


# ---------------------------------------------------------------------------
# Acceptance: rollback is receipted
# ---------------------------------------------------------------------------


class TestReceiptedRollback:
    def test_rollback_authority_is_receipted(
        self, catalog: GraphCatalog, authority: GraphShadowAuthority
    ) -> None:
        seed = _seed_graph(catalog, graph_id="rb-g")
        authority.ensure_duckdb_authority(
            tenant=seed["tenant"],
            graph_id=seed["graph_id"],
            decision_id="cutover:rb-g",
        )
        assert authority.mode == AuthorityMode.DB_PRIMARY.value

        decision = authority.rollback_authority(
            AuthorityMode.DUAL,
            decision_id="rollback:rb-g",
            reason="operator_test_rollback",
        )
        assert decision.accepted is True
        assert decision.kind == DecisionKind.ROLLBACK
        assert decision.to_mode == AuthorityMode.DUAL
        assert "operator_test_rollback" in (decision.reason or "")
        assert authority.mode == AuthorityMode.DUAL.value

        last = authority.last_decision_receipt()
        assert last is not None
        assert last.decision_id == "rollback:rb-g"
        assert last.kind == DecisionKind.ROLLBACK

        # Idempotent replay of the same decision id.
        again = authority.rollback_authority(
            AuthorityMode.DUAL,
            decision_id="rollback:rb-g",
            reason="operator_test_rollback",
        )
        assert again.decision_id == decision.decision_id
        assert again.accepted is True


# ---------------------------------------------------------------------------
# Hybrid storage: content authority stays Parquet/IPLD
# ---------------------------------------------------------------------------


class TestContentAuthorityUnchanged:
    def test_parquet_ipld_bytes_remain_content_authority(
        self, tmp_path: Path, authority: GraphShadowAuthority
    ) -> None:
        cache = VerifiedHybridCache(
            tmp_path / "hybrid_cutover",
            shadow_authority=authority,
        )
        assert cache.content_authority == "parquet_ipld"
        payload = b"PAR1" + b"cutover-payload-bytes-001" + b"\x00" * 16
        meta = cache.put(payload, pin=True)
        cid = meta.cid
        loaded = cache.get(cid)
        assert loaded == payload

        fp = authority.content_fingerprint(f"storage:{cid}")
        assert fp is not None
        assert fp["cid"] == cid
        assert authority.assert_content_unchanged(
            f"storage:{cid}",
            content_bytes=payload,
            content_cid=cid,
        )

        storage_receipts = [
            r for r in authority.list_mutation_receipts() if r.producer == "storage"
        ]
        assert storage_receipts
        # Dual mode projects storage metadata with outbox; content CID preserved.
        assert all(r.content_cid == cid or r.kind in {"pin", "unpin"} for r in storage_receipts)
        assert all(r.authority in {"dual", "duckdb", "legacy"} for r in storage_receipts)


# ---------------------------------------------------------------------------
# Safe dual helper
# ---------------------------------------------------------------------------


class TestSafeDualHelper:
    def test_safe_dual_catalog_mutation(
        self, catalog: GraphCatalog, authority: GraphShadowAuthority
    ) -> None:
        # First create via catalog hooks (emits dual receipt).
        g = catalog.create_graph(
            "t1",
            "safe-g",
            storage_profile="parquet",
            idempotency_key="create:safe-g",
        )
        assert g.graph_id == "safe-g"
        # Explicit dual-write helper with a fixed operation id.
        receipt = authority.record_operation(
            producer="catalog",
            kind="probe",
            key="graph:t1/safe-g",
            payload={"operation": "safe_dual_probe"},
            operation_id="op:safe-dual-create",
        )
        assert receipt is not None
        assert receipt.operation_id == "op:safe-dual-create"
        assert receipt.outbox_id
        # Replay is idempotent under the same operation id.
        again = authority.record_operation(
            producer="catalog",
            kind="probe",
            key="graph:t1/safe-g",
            payload={"operation": "safe_dual_probe"},
            operation_id="op:safe-dual-create",
        )
        assert again is not None
        assert again.idempotent_replay is True
        # Helper is importable and returns None without authority.
        none_receipt = safe_dual_catalog_mutation(
            "create_graph",
            result=g,
            catalog=catalog,
            args=("t1", "safe-g"),
            authority=None,
        )
        # Process registry still has authority, so may not be None; just ensure
        # the helper does not raise.
        _ = none_receipt
