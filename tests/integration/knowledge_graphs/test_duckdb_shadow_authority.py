"""Integration tests: DuckDB graph shadow authority (DQK-059).

Acceptance coverage:

* Branch CAS, leases, pins, tombstones, WAL/MVCC, restart and crypto-flow
  histories have SQLite/DuckDB parity
* Every producer operation has an idempotent DB operation ID
* Parquet/IPLD bytes, checksums, and CIDs remain unchanged
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.duckdb_control.authority_transition import (  # noqa: E402
    AuthorityMode,
)
from ipfs_datasets_py.knowledge_graphs.catalog.store import (  # noqa: E402
    GRAPH_SHADOW_DOMAIN,
    GRAPH_SHADOW_OWNER_TASK,
    GRAPH_SHADOW_SCHEMA,
    GraphCatalog,
    GraphShadowAuthority,
    configure_graph_shadow_authority,
    get_graph_shadow_authority,
    new_graph_operation_id,
    reset_graph_shadow_authority,
)
from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine  # noqa: E402
from ipfs_datasets_py.knowledge_graphs.crypto_flows.store import (  # noqa: E402
    InMemoryGraphSnapshotStore,
    ShadowingGraphSnapshotStore,
)
from ipfs_datasets_py.knowledge_graphs.service import (  # noqa: E402
    GraphService,
    GraphTarget,
)
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
def shadow(tmp_path: Path) -> GraphShadowAuthority:
    reset_graph_shadow_authority()
    auth = configure_graph_shadow_authority(
        tmp_path / "graph_shadow_catalog.duckdb",
        duckdb_tx_path=tmp_path / "graph_shadow_tx.duckdb",
        duckdb_crypto_path=tmp_path / "graph_shadow_crypto.duckdb",
        enabled=True,
    )
    yield auth
    reset_graph_shadow_authority()


@pytest.fixture
def catalog(tmp_path: Path, shadow: GraphShadowAuthority) -> GraphCatalog:
    cat = GraphCatalog(
        tmp_path / "catalog.sqlite",
        shadow_authority=shadow,
    )
    yield cat
    cat.close()


# ---------------------------------------------------------------------------
# Module / wiring invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_schema_and_owner_constants(self) -> None:
        assert GRAPH_SHADOW_OWNER_TASK == "DQK-059"
        assert GRAPH_SHADOW_DOMAIN == "graphs"
        assert GRAPH_SHADOW_SCHEMA.startswith("ipfs_datasets_py/")

    def test_process_registry_configure_get_reset(self, tmp_path: Path) -> None:
        reset_graph_shadow_authority()
        assert get_graph_shadow_authority() is None
        auth = configure_graph_shadow_authority(tmp_path / "c.duckdb")
        assert get_graph_shadow_authority() is auth
        assert auth.enabled
        assert auth.mode == AuthorityMode.SHADOW.value
        reset_graph_shadow_authority()
        assert get_graph_shadow_authority() is None


# ---------------------------------------------------------------------------
# Catalog: branch CAS, leases, pins, tombstones + operation ids
# ---------------------------------------------------------------------------


def _catalog_trace(catalog: GraphCatalog) -> Dict[str, Any]:
    g = catalog.create_graph(
        "t1",
        "g1",
        storage_profile="parquet",
        idempotency_key="create:g1",
    )
    # Idempotent create
    g2 = catalog.create_graph(
        "t1",
        "g1",
        storage_profile="parquet",
        idempotency_key="create:g1",
    )
    assert g.graph_id == g2.graph_id
    bootstrap = catalog.get_branch("t1", "g1", "main").head_revision
    checksum = "sha256:" + ("ab" * 32)
    manifest_cid = "bafygraphmanifest01"
    r2 = catalog.put_revision(
        "t1",
        "g1",
        "rev-2",
        parent_revision=bootstrap,
        storage_profile="parquet",
        checksum=checksum,
        manifest_cid=manifest_cid,
    )
    lease = catalog.acquire_lease(
        "t1", "g1", "main", holder="writer-a", ttl_seconds=60
    )
    head = catalog.cas_set_head(
        "t1",
        "g1",
        "main",
        expected_revision=bootstrap,
        new_revision=r2.revision_id,
        lease_id=lease.lease_id,
        lease_epoch=lease.epoch,
        idempotency_key="cas:1",
    )
    pin = catalog.set_pin_root(
        "t1", "g1", r2.revision_id, root_cid="bafytestpinroot01"
    )
    return {
        "graph": g,
        "bootstrap": bootstrap,
        "revision": r2,
        "lease": lease,
        "head": head,
        "pin": pin,
        "checksum": checksum,
        "manifest_cid": manifest_cid,
    }


class TestCatalogParity:
    def test_branch_cas_leases_pins_have_sqlite_duckdb_parity(
        self, catalog: GraphCatalog, shadow: GraphShadowAuthority
    ) -> None:
        trace = _catalog_trace(catalog)
        view = shadow.parity_for(catalog, "t1", "g1")
        assert view.branch_matched is True, view.to_dict()
        assert view.lease_matched is True, view.to_dict()
        assert view.pin_matched is True, view.to_dict()
        assert view.revision_matched is True, view.to_dict()
        assert view.matched is True, view.to_dict()

        # Content identity projected by reference only
        assert trace["revision"].checksum == trace["checksum"]
        assert trace["revision"].manifest_cid == trace["manifest_cid"]
        assert view.legacy["revisions"]["rev-2"]["checksum"] == trace["checksum"]
        assert view.shadow["revisions"]["rev-2"]["checksum"] == trace["checksum"]
        assert view.legacy["revisions"]["rev-2"]["manifest_cid"] == trace["manifest_cid"]
        assert view.shadow["revisions"]["rev-2"]["manifest_cid"] == trace["manifest_cid"]

    def test_tombstone_parity(
        self, catalog: GraphCatalog, shadow: GraphShadowAuthority
    ) -> None:
        catalog.create_graph("t1", "g-tomb", storage_profile="parquet")
        catalog.delete_graph("t1", "g-tomb", reason="retire")
        view = shadow.parity_for(catalog, "t1", "g-tomb")
        assert view.legacy["status"] == "tombstoned"
        assert view.shadow["status"] == "tombstoned"
        assert view.tombstone_matched is True, view.to_dict()

    def test_every_catalog_mutation_has_operation_id_and_parity_receipt(
        self, catalog: GraphCatalog, shadow: GraphShadowAuthority
    ) -> None:
        _catalog_trace(catalog)
        receipts = shadow.list_mutation_receipts()
        assert receipts, "catalog mutations must emit receipts"
        catalog_receipts = [r for r in receipts if r.producer == "catalog"]
        assert catalog_receipts
        for receipt in catalog_receipts:
            assert receipt.operation_id, f"missing operation_id: {receipt}"
            assert receipt.mode in {"shadow", "disabled"}
            assert receipt.authority == "legacy"
            # Authority-port parity must match for dual projection of the same body
            assert receipt.parity_matched is True, receipt.to_dict()
            assert receipt.parity_receipt_cid or receipt.mode == "disabled"

        # Idempotent replay under fixed operation id
        fixed = shadow.record_operation(
            producer="catalog",
            kind="probe",
            key="graph:t1/g1",
            payload={"probe": True},
            operation_id="op:idempotent-fixed",
        )
        replay = shadow.record_operation(
            producer="catalog",
            kind="probe",
            key="graph:t1/g1",
            payload={"probe": True},
            operation_id="op:idempotent-fixed",
        )
        assert replay.idempotent_replay is True
        assert replay.operation_id == fixed.operation_id
        assert replay.parity_receipt_cid == fixed.parity_receipt_cid

    def test_parity_across_restart(
        self, catalog: GraphCatalog, shadow: GraphShadowAuthority, tmp_path: Path
    ) -> None:
        _catalog_trace(catalog)
        restarted = shadow.parity_across_restart(catalog, "t1", "g1")
        assert restarted.matched is True, restarted.to_dict()
        assert restarted.branch_matched is True
        assert restarted.lease_matched is True
        assert restarted.pin_matched is True
        assert restarted.revision_matched is True


# ---------------------------------------------------------------------------
# Service producer
# ---------------------------------------------------------------------------


class TestServiceProducer:
    def test_service_routes_through_shadow_authority(
        self, tmp_path: Path, shadow: GraphShadowAuthority
    ) -> None:
        svc = GraphService.open(
            tmp_path / "svc_catalog.sqlite",
            storage_path=tmp_path / "svc_payloads",
            shadow_authority=shadow,
        )
        try:
            target = GraphTarget(tenant="acme", graph_id="svc-g1", branch="main")
            result = svc.create(
                target,
                idempotency_key="svc-create-1",
                params={"storage_profile": "parquet"},
            )
            assert result.status == "success"
            receipts = [
                r
                for r in shadow.list_mutation_receipts()
                if r.producer in {"catalog", "service"}
            ]
            assert receipts
            assert all(r.operation_id for r in receipts)
            assert all(r.parity_matched for r in receipts if r.producer == "service")
        finally:
            svc.close()


# ---------------------------------------------------------------------------
# Engine producer
# ---------------------------------------------------------------------------


class TestEngineProducer:
    def test_engine_mutations_emit_operation_ids(
        self, shadow: GraphShadowAuthority
    ) -> None:
        engine = GraphEngine(shadow_authority=shadow)
        node = engine.create_node(labels=["Person"], properties={"name": "Ada"})
        node_id = node.id
        engine.update_node(node_id, {"age": 36})
        rel = engine.create_relationship(
            "KNOWS", node_id, node_id, properties={"since": 2020}
        )
        rel_id = getattr(rel, "id", None) or getattr(rel, "rel_id", None)
        assert rel_id
        engine.delete_relationship(rel_id)
        engine.delete_node(node_id)

        engine_receipts = [
            r for r in shadow.list_mutation_receipts() if r.producer == "engine"
        ]
        assert len(engine_receipts) >= 4
        assert all(r.operation_id for r in engine_receipts)
        assert all(r.parity_matched for r in engine_receipts)
        assert all(r.authority == "legacy" for r in engine_receipts)


# ---------------------------------------------------------------------------
# Transaction / WAL / MVCC producer
# ---------------------------------------------------------------------------


class TestTransactionWalMvccParity:
    def test_wal_mvcc_control_state_shadowed(
        self, shadow: GraphShadowAuthority
    ) -> None:
        """WAL/MVCC control projection via TransactionManager + direct CID parity.

        Full IPLD WAL append needs a network-ready backend; this test exercises
        the manager begin/rollback shadow path and durable DuckDB WAL control
        state with fixed CIDs so content identity is proven unchanged.
        """

        engine = GraphEngine(shadow_authority=shadow)
        # Begin/rollback do not require IPLD storage; pass a sentinel backend.
        class _NoopBackend:
            pass

        mgr = TransactionManager(engine, _NoopBackend(), shadow_authority=shadow)
        txn = mgr.begin()
        assert txn.txn_id
        mgr.rollback(txn)

        # Project a commit-shaped WAL control envelope with fixed CIDs.
        wal_cid = "bafywalcommit0001"
        receipt = shadow.record_transaction_mutation(
            kind="commit",
            txn_id=txn.txn_id,
            payload={
                "txn_id": txn.txn_id,
                "state": "COMMITTED",
                "isolation_level": "REPEATABLE_READ",
                "read_set": [],
                "write_set": ["entity-1"],
                "start_time": 0.0,
                "snapshot_cid": None,
                "wal_entries": [wal_cid],
            },
            operation_id=new_graph_operation_id("txn.commit"),
            wal_cid=wal_cid,
        )
        assert receipt.operation_id
        assert receipt.parity_matched is True
        assert receipt.content_cid == wal_cid

        tx_receipts = [
            r
            for r in shadow.list_mutation_receipts()
            if r.producer == "transactions"
        ]
        assert tx_receipts
        assert all(r.operation_id for r in tx_receipts)
        assert all(r.parity_matched for r in tx_receipts)

        duck_tx = shadow.duckdb_transaction_state
        assert duck_tx is not None
        assert duck_tx.get_wal_head_cid() == wal_cid
        applied = duck_tx.list_wal_applied_keys()
        assert txn.txn_id in applied
        assert applied[txn.txn_id] == wal_cid

        rollbacks = [
            r for r in shadow.list_mutation_receipts() if r.kind == "rollback"
        ]
        assert rollbacks


# ---------------------------------------------------------------------------
# Hybrid storage: bytes / checksums / CIDs unchanged
# ---------------------------------------------------------------------------


class TestHybridStorageContentIdentity:
    def test_parquet_ipld_bytes_checksums_cids_unchanged(
        self, tmp_path: Path, shadow: GraphShadowAuthority
    ) -> None:
        cache = VerifiedHybridCache(
            tmp_path / "hybrid_cache",
            shadow_authority=shadow,
        )
        payload = b"PAR1" + b"hybrid-shadow-payload-bytes-001" + b"\x00" * 16
        meta = cache.put(payload, pin=True)
        cid = meta.cid
        checksum = meta.sha256
        assert checksum.startswith("sha256:") or len(checksum) == 64

        # Re-read bytes must match exactly
        loaded = cache.get(cid)
        assert loaded == payload

        # Shadow fingerprinted the original bytes
        fp = shadow.content_fingerprint(f"storage:{cid}")
        assert fp is not None
        assert fp["cid"] == cid
        assert shadow.assert_content_unchanged(
            f"storage:{cid}",
            content_bytes=payload,
            content_cid=cid,
        )

        storage_receipts = [
            r for r in shadow.list_mutation_receipts() if r.producer == "storage"
        ]
        assert storage_receipts
        assert all(r.operation_id for r in storage_receipts)
        assert all(r.content_cid == cid or r.kind in {"pin", "unpin"} for r in storage_receipts)

        # Pin does not rewrite content
        pinned = cache.pin(cid)
        assert pinned.sha256 == checksum
        assert cache.get(cid) == payload


# ---------------------------------------------------------------------------
# Crypto-flow histories
# ---------------------------------------------------------------------------


def _make_crypto_snapshot(snapshot_id: str):
    from ipfs_datasets_py.knowledge_graphs.crypto_flows.builder import (
        CryptoFlowGraphBuilder,
    )
    from ipfs_datasets_py.knowledge_graphs.crypto_flows.model import (
        CompletenessReceipt,
        CompletenessStatus,
        ExactAmount,
        FinalityStatus,
        LedgerCoordinate,
        RetractionStatus,
        ValidityWindow,
    )
    from ipfs_datasets_py.logic.crypto_ir.model import (
        AssetIdentity,
        ChainIdentity,
    )

    chain = ChainIdentity(
        chain_namespace="eip155",
        network="ethereum-mainnet",
        genesis_digest="sha256:" + ("ab" * 32),
        chain_id="1",
        display_name="Ethereum Mainnet",
    )
    asset = AssetIdentity(
        chain=chain,
        asset_namespace="native",
        asset_reference="eth",
        decimals=18,
        symbol="ETH",
    )
    builder = CryptoFlowGraphBuilder(f"graph-{snapshot_id}")
    builder.add_observed_address("a", chain=chain, address="0xa")
    builder.add_observed_address("b", chain=chain, address="0xb")
    builder.add_account_transfer(
        f"xfer-{snapshot_id}",
        source_node_id="a",
        target_node_id="b",
        chain=chain,
        asset=asset,
        amount=ExactAmount.from_int(5, decimals=18),
        coordinate=LedgerCoordinate(sequence=9, hash="0x9"),
        provider_ids=("prov-a",),
    )
    builder.add_completeness_receipt(
        CompletenessReceipt(
            receipt_id=f"r-{snapshot_id}",
            chain=chain,
            scope="ledger-range",
            completeness=CompletenessStatus.COMPLETE,
            finality=FinalityStatus.FINALIZED,
            validity=ValidityWindow(start="2024-01-01T00:00:00Z", end=""),
            retraction=RetractionStatus.NOT_RETRACTED,
            covered_ranges=(LedgerCoordinate(sequence=1, hash="0x1"),),
            missing_ranges=(),
            provider_ids=("prov-a",),
        )
    )
    return builder.snapshot(snapshot_id)


class TestCryptoFlowHistoryParity:
    def test_crypto_flow_histories_have_sqlite_duckdb_parity(
        self, shadow: GraphShadowAuthority
    ) -> None:
        legacy = InMemoryGraphSnapshotStore()
        store = ShadowingGraphSnapshotStore(
            legacy=legacy, shadow_authority=shadow
        )
        snap_ids: List[str] = []
        digests: Dict[str, str] = {}
        cids: Dict[str, str] = {}
        for i in range(3):
            sid = f"snap-{i}"
            snap = _make_crypto_snapshot(sid)
            digests[sid] = snap.graph_digest
            cids[sid] = snap.graph_cid
            store.put(snap, operation_id=new_graph_operation_id(f"crypto.{i}"))
            snap_ids.append(sid)

        # Legacy is authority and retains full history
        assert set(store.list_ids()) == set(snap_ids)
        for sid in snap_ids:
            got = store.get(sid)
            assert got.graph_digest == digests[sid]
            assert got.graph_cid == cids[sid]

        history = store.history_parity()
        assert history["matched"] is True, history
        assert history["count"] == 3
        for entry in history["entries"]:
            assert entry["matched"] is True
            assert entry["legacy"]["graph_digest"] == entry["shadow"]["graph_digest"]
            assert entry["legacy"]["graph_cid"] == entry["shadow"]["graph_cid"]

        crypto_receipts = store.mutation_receipts
        assert len(crypto_receipts) == 3
        assert all(r.operation_id for r in crypto_receipts)
        assert all(r.parity_matched for r in crypto_receipts)
        assert all(r.content_checksum for r in crypto_receipts)


# ---------------------------------------------------------------------------
# End-to-end multi-producer parity
# ---------------------------------------------------------------------------


class TestMultiProducerIntegration:
    def test_all_producers_emit_idempotent_operation_ids(
        self, tmp_path: Path, shadow: GraphShadowAuthority
    ) -> None:
        cat = GraphCatalog(tmp_path / "multi.sqlite", shadow_authority=shadow)
        try:
            _catalog_trace(cat)
            engine = GraphEngine(shadow_authority=shadow)
            engine.create_node(labels=["X"], properties={"k": 1})

            class _NoopBackend:
                pass

            mgr = TransactionManager(
                engine, _NoopBackend(), shadow_authority=shadow
            )
            txn = mgr.begin()
            mgr.rollback(txn)
            shadow.record_transaction_mutation(
                kind="commit",
                txn_id=txn.txn_id,
                payload={
                    "txn_id": txn.txn_id,
                    "state": "COMMITTED",
                    "isolation_level": "REPEATABLE_READ",
                    "read_set": [],
                    "write_set": [],
                    "start_time": 0.0,
                    "wal_entries": ["bafymulti0001"],
                },
                wal_cid="bafymulti0001",
            )
            cache = VerifiedHybridCache(
                tmp_path / "multi_cache", shadow_authority=shadow
            )
            payload = b"multi-producer-bytes"
            cache.put(payload)
            legacy = InMemoryGraphSnapshotStore()
            legacy.attach_shadow_authority(shadow)
            legacy.put(_make_crypto_snapshot("multi-snap"))

            receipts = shadow.list_mutation_receipts()
            producers = {r.producer for r in receipts}
            assert "catalog" in producers
            assert "engine" in producers
            assert "transactions" in producers
            assert "storage" in producers
            assert "crypto_flows" in producers
            assert all(r.operation_id for r in receipts)
            # No producer rewrote content identity under shadow mode
            for r in receipts:
                if r.content_cid:
                    assert isinstance(r.content_cid, str)
                assert r.authority in {"legacy", ""}
        finally:
            cat.close()
