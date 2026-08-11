"""Unit tests for DuckDB crypto-flow graph snapshot store (DQK-019).

Acceptance:

* Snapshot identity is deterministic
* Reorg and retraction history is retained
* Concurrent readers never observe partial snapshots
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.knowledge_graphs.crypto_flows.builder import (  # noqa: E402
    CryptoFlowGraphBuilder,
)
from ipfs_datasets_py.knowledge_graphs.crypto_flows.duckdb_store import (  # noqa: E402
    CRYPTO_FLOW_SNAPSHOT_TABLES,
    DUCKDB_CRYPTO_FLOW_SNAPSHOT_SCHEMA,
    SCHEMA_VERSION,
    DuckDBGraphSnapshotStore,
)
from ipfs_datasets_py.knowledge_graphs.crypto_flows.model import (  # noqa: E402
    AmbiguityKind,
    CompletenessReceipt,
    CompletenessStatus,
    DerivationMethod,
    EdgeKind,
    ExactAmount,
    FinalityStatus,
    FlowDirection,
    FlowEdge,
    GraphPlane,
    GraphSnapshot,
    LedgerCoordinate,
    LedgerModel,
    NodeKind,
    RetractionStatus,
    ValidityWindow,
)
from ipfs_datasets_py.knowledge_graphs.crypto_flows.store import (  # noqa: E402
    SnapshotStoreError,
)
from ipfs_datasets_py.logic.crypto_ir.model import (  # noqa: E402
    AssetIdentity,
    ChainIdentity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


GENESIS = "sha256:" + ("ab" * 32)


def eth_chain() -> ChainIdentity:
    return ChainIdentity(
        chain_namespace="eip155",
        network="ethereum-mainnet",
        genesis_digest=GENESIS,
        chain_id="1",
        display_name="Ethereum Mainnet",
    )


def eth_asset() -> AssetIdentity:
    return AssetIdentity(
        chain=eth_chain(),
        asset_namespace="native",
        asset_reference="eth",
        decimals=18,
        symbol="ETH",
    )


def completeness(
    receipt_id: str,
    chain: ChainIdentity,
    *,
    providers: tuple[str, ...] = (),
    status: CompletenessStatus = CompletenessStatus.COMPLETE,
) -> CompletenessReceipt:
    return CompletenessReceipt(
        receipt_id=receipt_id,
        chain=chain,
        scope="ledger-range",
        completeness=status,
        finality=FinalityStatus.FINALIZED,
        validity=ValidityWindow(start="2024-01-01T00:00:00Z", end=""),
        retraction=RetractionStatus.NOT_RETRACTED,
        covered_ranges=(LedgerCoordinate(sequence=1, hash="0x1"),),
        missing_ranges=(),
        provider_ids=providers,
    )


@pytest.fixture
def store(tmp_path: Path) -> DuckDBGraphSnapshotStore:
    s = DuckDBGraphSnapshotStore(tmp_path / "crypto_flow_snapshots.duckdb")
    yield s
    s.close()


@pytest.fixture
def mem_store() -> DuckDBGraphSnapshotStore:
    s = DuckDBGraphSnapshotStore(":memory:")
    yield s
    s.close()


def _basic_transfer_snapshot(
    snapshot_id: str = "snap-1",
    *,
    graph_id: str = "g1",
    provider: str = "prov-a",
) -> GraphSnapshot:
    builder = CryptoFlowGraphBuilder(graph_id)
    builder.add_observed_address("a", chain=eth_chain(), address="0xa")
    builder.add_observed_address("b", chain=eth_chain(), address="0xb")
    builder.add_account_transfer(
        "xfer-1",
        source_node_id="a",
        target_node_id="b",
        chain=eth_chain(),
        asset=eth_asset(),
        amount=ExactAmount.from_int(5, decimals=18),
        coordinate=LedgerCoordinate(sequence=9, hash="0x9"),
        provider_ids=(provider,),
    )
    builder.add_completeness_receipt(
        completeness("r1", eth_chain(), providers=(provider,))
    )
    return builder.snapshot(snapshot_id)


def _dual_plane_snapshot(snapshot_id: str = "planes-1") -> GraphSnapshot:
    builder = CryptoFlowGraphBuilder("planes")
    builder.add_observed_address("addr-a", chain=eth_chain(), address="0xaa")
    builder.add_observed_address("addr-b", chain=eth_chain(), address="0xbb")
    builder.add_asserted_entity(
        "ent-1",
        kind=NodeKind.ENTITY,
        entity_ref="entity:alice",
        ambiguity=AmbiguityKind.MULTI_PARTY,
    )
    builder.add_asserted_entity(
        "ent-2",
        kind=NodeKind.ENTITY,
        entity_ref="entity:bob",
        ambiguity=AmbiguityKind.MULTI_PARTY,
    )
    builder.add_account_transfer(
        "xfer-obs",
        source_node_id="addr-a",
        target_node_id="addr-b",
        chain=eth_chain(),
        asset=eth_asset(),
        amount=ExactAmount.from_int(1, decimals=18),
        coordinate=LedgerCoordinate(sequence=1, hash="0x1"),
        provider_ids=("p",),
    )
    # Asserted-plane ownership edge with preserved ambiguity.
    builder.add_edge(
        FlowEdge(
            edge_id="owns-1",
            kind=EdgeKind.OWNS,
            plane=GraphPlane.ASSERTED_ENTITY,
            source_node_id="ent-1",
            target_node_id="ent-2",
            derivation=DerivationMethod.HEURISTIC_CLUSTER,
            ambiguity=AmbiguityKind.MULTI_PARTY,
            confidence="0.4",
            direction=FlowDirection.NONE,
        )
    )
    builder.add_completeness_receipt(
        completeness("r-planes", eth_chain(), providers=("p",))
    )
    return builder.snapshot(snapshot_id)


def _reorg_and_retract_snapshot() -> GraphSnapshot:
    builder = CryptoFlowGraphBuilder("reorg-hist")
    builder.add_observed_address("a", chain=eth_chain(), address="0xa")
    builder.add_observed_address("b", chain=eth_chain(), address="0xb")
    builder.add_observed_address("c", chain=eth_chain(), address="0xc")
    builder.add_account_transfer(
        "xfer-old",
        source_node_id="a",
        target_node_id="b",
        chain=eth_chain(),
        asset=eth_asset(),
        amount=ExactAmount.from_int(2, decimals=18),
        coordinate=LedgerCoordinate(sequence=3, hash="0xold"),
        provider_ids=("p",),
    )
    builder.add_account_transfer(
        "xfer-retract",
        source_node_id="b",
        target_node_id="c",
        chain=eth_chain(),
        asset=eth_asset(),
        amount=ExactAmount.from_int(1, decimals=18),
        coordinate=LedgerCoordinate(sequence=4, hash="0xret"),
        provider_ids=("p",),
    )
    replacement = FlowEdge(
        edge_id="xfer-new",
        kind=EdgeKind.TRANSFER,
        plane=GraphPlane.OBSERVED_ADDRESS,
        source_node_id="a",
        target_node_id="b",
        chain=eth_chain(),
        ledger_model=LedgerModel.ACCOUNT,
        asset=eth_asset(),
        amount=ExactAmount.from_int(2, decimals=18),
        coordinate=LedgerCoordinate(sequence=3, hash="0xnew"),
        direction=FlowDirection.OUT,
        finality=FinalityStatus.CONFIRMED,
        source="reorg-replacement",
        derivation=DerivationMethod.ACCOUNT_TRANSFER,
        provider_ids=("p",),
    )
    builder.apply_reorg("xfer-old", replacement=replacement)
    builder.retract_edge("xfer-retract")
    builder.add_completeness_receipt(
        completeness("r-reorg", eth_chain(), providers=("p",))
    )
    return builder.snapshot("snap-reorg")


# ---------------------------------------------------------------------------
# Schema / lifecycle
# ---------------------------------------------------------------------------


def test_schema_tables_and_version(store: DuckDBGraphSnapshotStore) -> None:
    tables = set(store.list_tables())
    for name in CRYPTO_FLOW_SNAPSHOT_TABLES:
        assert name in tables
    assert store.schema_id == DUCKDB_CRYPTO_FLOW_SNAPSHOT_SCHEMA
    assert SCHEMA_VERSION == 1


def test_context_manager_and_close(tmp_path: Path) -> None:
    path = tmp_path / "cm.duckdb"
    with DuckDBGraphSnapshotStore(path) as s:
        s.put(_basic_transfer_snapshot("cm-1"))
        assert s.contains("cm-1")
    with pytest.raises(SnapshotStoreError, match="closed"):
        s.get("cm-1")


def test_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "persist.duckdb"
    snap = _basic_transfer_snapshot("persist-1")
    with DuckDBGraphSnapshotStore(path) as s:
        s.put(snap)
        digest = snap.identity.digest
    with DuckDBGraphSnapshotStore(path) as s:
        loaded = s.get("persist-1")
        assert loaded.identity.digest == digest
        assert s.list_ids() == ("persist-1",)


# ---------------------------------------------------------------------------
# Protocol parity with in-memory store
# ---------------------------------------------------------------------------


def test_put_get_list_contains_round_trip(store: DuckDBGraphSnapshotStore) -> None:
    snap = _basic_transfer_snapshot("snap-1")
    key = store.put(snap)
    assert key == "snap-1"
    loaded = store.get("snap-1")
    assert loaded.identity.digest == snap.identity.digest
    assert loaded.graph_digest == snap.graph.identity.digest
    assert loaded.graph_cid == snap.graph.identity.cid
    by_digest = store.get_by_digest(snap.graph_digest)
    assert by_digest.snapshot_id == "snap-1"
    assert store.contains("snap-1")
    assert store.list_ids() == ("snap-1",)
    assert store.completeness_index()["snap-1"] == CompletenessStatus.COMPLETE.value
    assert "prov-a" in store.providers_union()


def test_immutability_fail_closed(store: DuckDBGraphSnapshotStore) -> None:
    snap = _basic_transfer_snapshot("imm-1")
    store.put(snap)
    with pytest.raises(SnapshotStoreError, match="immutable"):
        store.put(snap)
    # overwrite allowed
    store.put(snap, overwrite=True)
    assert store.get("imm-1").identity.digest == snap.identity.digest


def test_missing_snapshot_fails_closed(store: DuckDBGraphSnapshotStore) -> None:
    with pytest.raises(SnapshotStoreError, match="not found"):
        store.get("missing")
    with pytest.raises(SnapshotStoreError, match="no snapshot"):
        store.get_by_digest("sha256:" + ("00" * 32))
    assert store.contains("missing") is False


def test_invalid_ids_fail_closed(store: DuckDBGraphSnapshotStore) -> None:
    with pytest.raises(Exception):
        store.get("")
    with pytest.raises(Exception):
        store.get_by_digest("  ")


# ---------------------------------------------------------------------------
# Acceptance: deterministic snapshot identity
# ---------------------------------------------------------------------------


def test_snapshot_identity_is_deterministic(
    store: DuckDBGraphSnapshotStore,
) -> None:
    """Equivalent content → same digests; durable store preserves them."""

    def build(snapshot_id: str) -> GraphSnapshot:
        builder = CryptoFlowGraphBuilder("id-g")
        builder.add_observed_address("a", chain=eth_chain(), address="0xa")
        builder.add_observed_address("b", chain=eth_chain(), address="0xb")
        builder.add_account_transfer(
            "x",
            source_node_id="a",
            target_node_id="b",
            chain=eth_chain(),
            asset=eth_asset(),
            amount=ExactAmount.from_int(1, decimals=18),
            coordinate=LedgerCoordinate(sequence=1, hash="0x1"),
            provider_ids=("p1", "p2"),
        )
        builder.add_completeness_receipt(
            completeness("r", eth_chain(), providers=("p1", "p2"))
        )
        return builder.snapshot(snapshot_id)

    s1 = build("id-a")
    s2 = build("id-b")
    # Same graph payload → same graph digest (snapshot_id differs).
    assert s1.graph.identity.digest == s2.graph.identity.digest
    # Independent constructions of the same snapshot_id match exactly.
    s1_again = build("id-a")
    assert s1.identity.digest == s1_again.identity.digest
    assert s1.identity.cid == s1_again.identity.cid

    store.put(s1)
    store.put(s2)
    loaded1 = store.get("id-a")
    loaded2 = store.get("id-b")
    assert loaded1.identity.digest == s1.identity.digest
    assert loaded2.identity.digest == s2.identity.digest
    assert loaded1.graph_digest == loaded2.graph_digest == s1.graph.identity.digest
    # Re-put with overwrite does not change identity.
    store.put(s1_again, overwrite=True)
    assert store.get("id-a").identity.digest == s1.identity.digest
    idx = store.identity_index()
    assert idx["id-a"] == s1.identity.digest
    assert idx["id-b"] == s2.identity.digest


def test_identity_stable_across_memory_and_disk(tmp_path: Path) -> None:
    snap = _basic_transfer_snapshot("cross-1")
    with DuckDBGraphSnapshotStore(":memory:") as mem:
        mem.put(snap)
        mem_digest = mem.get("cross-1").identity.digest
    path = tmp_path / "disk.duckdb"
    with DuckDBGraphSnapshotStore(path) as disk:
        disk.put(snap)
        disk_digest = disk.get("cross-1").identity.digest
    assert mem_digest == disk_digest == snap.identity.digest


# ---------------------------------------------------------------------------
# Acceptance: reorg and retraction history retained
# ---------------------------------------------------------------------------


def test_reorg_and_retraction_history_retained(
    store: DuckDBGraphSnapshotStore,
) -> None:
    snap = _reorg_and_retract_snapshot()
    store.put(snap)
    loaded = store.get("snap-reorg")

    by_id = {e.edge_id: e for e in loaded.graph.edges}
    assert by_id["xfer-old"].finality is FinalityStatus.REORGED
    assert by_id["xfer-old"].retraction is RetractionStatus.SUPERSEDED
    assert by_id["xfer-old"].ambiguity is AmbiguityKind.REORG
    assert by_id["xfer-retract"].finality is FinalityStatus.RETRACTED
    assert by_id["xfer-retract"].retraction is RetractionStatus.RETRACTED
    assert by_id["xfer-new"].finality is FinalityStatus.CONFIRMED
    # Prior history is kept; active view excludes superseded/retracted.
    active_ids = {e.edge_id for e in loaded.graph.active_edges()}
    assert "xfer-new" in active_ids
    assert "xfer-old" not in active_ids
    assert "xfer-retract" not in active_ids

    reorgs = store.list_reorg_history(snapshot_id="snap-reorg")
    assert any(e.entity_id == "xfer-old" for e in reorgs)
    retractions = store.list_retraction_history(snapshot_id="snap-reorg")
    assert any(e.entity_id == "xfer-retract" for e in retractions)
    supersessions = store.list_lineage_events(
        snapshot_id="snap-reorg", event_kind="supersession"
    )
    assert any(e.entity_id == "xfer-old" for e in supersessions)


def test_history_retained_across_successive_snapshots(
    store: DuckDBGraphSnapshotStore,
) -> None:
    """Later snapshots do not erase prior reorg/retraction history rows."""
    first = _reorg_and_retract_snapshot()
    store.put(first)

    # Second snapshot: clean graph without reorged edges.
    clean = _basic_transfer_snapshot("snap-clean", graph_id="clean-g")
    store.put(clean)

    # First snapshot's lineage remains queryable.
    reorgs = store.list_reorg_history(snapshot_id="snap-reorg")
    assert len(reorgs) >= 1
    all_reorgs = store.list_reorg_history()
    assert any(e.snapshot_id == "snap-reorg" for e in all_reorgs)
    # Clean snapshot has no reorg lineage of its own.
    assert store.list_reorg_history(snapshot_id="snap-clean") == ()
    assert store.get("snap-reorg").identity.digest == first.identity.digest
    assert store.get("snap-clean").identity.digest == clean.identity.digest


# ---------------------------------------------------------------------------
# Planes and ambiguity indexing
# ---------------------------------------------------------------------------


def test_observed_and_asserted_planes_indexed(
    store: DuckDBGraphSnapshotStore,
) -> None:
    snap = _dual_plane_snapshot()
    store.put(snap)
    observed_nodes = store.list_node_ids_on_plane(
        "planes-1", GraphPlane.OBSERVED_ADDRESS
    )
    asserted_nodes = store.list_node_ids_on_plane(
        "planes-1", GraphPlane.ASSERTED_ENTITY
    )
    assert "addr-a" in observed_nodes and "addr-b" in observed_nodes
    assert "ent-1" in asserted_nodes
    assert "ent-1" not in observed_nodes
    observed_edges = store.list_edge_ids_on_plane(
        "planes-1", GraphPlane.OBSERVED_ADDRESS
    )
    asserted_edges = store.list_edge_ids_on_plane(
        "planes-1", GraphPlane.ASSERTED_ENTITY
    )
    assert "xfer-obs" in observed_edges
    assert "owns-1" in asserted_edges
    ambiguity_events = store.list_lineage_events(
        snapshot_id="planes-1", event_kind="ambiguity"
    )
    entity_ids = {e.entity_id for e in ambiguity_events}
    assert "owns-1" in entity_ids or "ent-1" in entity_ids


# ---------------------------------------------------------------------------
# Acceptance: concurrent readers never observe partial snapshots
# ---------------------------------------------------------------------------


def test_aborted_put_leaves_no_partial_snapshot(
    store: DuckDBGraphSnapshotStore,
) -> None:
    """If a write transaction fails mid-way, nothing is query-visible."""
    snap = _basic_transfer_snapshot("partial-1")
    identity = snap.identity
    graph_identity = snap.graph.identity
    node = snap.graph.nodes[0]

    with pytest.raises(RuntimeError, match="simulated mid-write failure"):
        with store._transaction() as conn:
            conn.execute(
                """
                INSERT INTO crypto_flow_snapshots (
                    snapshot_id, graph_id, identity_digest, identity_cid,
                    graph_digest, graph_cid, completeness, created_at,
                    schema_version, status, snapshot_json, stored_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    snap.snapshot_id,
                    snap.graph.graph_id,
                    identity.digest,
                    identity.cid,
                    graph_identity.digest,
                    graph_identity.cid,
                    snap.completeness.value,
                    snap.created_at,
                    snap.schema_version,
                    "published",
                    "{}",
                    "2024-01-01T00:00:00Z",
                ],
            )
            conn.execute(
                """
                INSERT INTO crypto_flow_nodes (
                    snapshot_id, node_id, plane, kind, ambiguity,
                    retraction, finality, address_ref, entity_ref, node_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    snap.snapshot_id,
                    node.node_id,
                    node.plane.value,
                    node.kind.value,
                    node.ambiguity.value,
                    node.retraction.value,
                    node.finality.value,
                    node.address_ref,
                    node.entity_ref,
                    "{}",
                ],
            )
            # Simulate failure before edges / commit.
            raise RuntimeError("simulated mid-write failure")

    assert store.contains("partial-1") is False
    assert store.list_ids() == ()
    with pytest.raises(SnapshotStoreError, match="not found"):
        store.get("partial-1")
    # No orphan envelope/node/edge/lineage rows after rollback.
    with store._read() as conn:
        assert conn.execute(
            "SELECT count(*) FROM crypto_flow_snapshots"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM crypto_flow_nodes"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM crypto_flow_edges"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM crypto_flow_lineage_events"
        ).fetchone()[0] == 0

    # A subsequent complete put still succeeds.
    store.put(snap)
    assert store.get("partial-1").identity.digest == snap.identity.digest


def test_concurrent_readers_never_see_partial_writes(
    tmp_path: Path,
) -> None:
    """Concurrent readers only observe fully published snapshots.

    The store serializes mutations under an RLock and commits envelope +
    children in one transaction.  Readers interleave with writers and must
    never load a snapshot whose node/edge counts disagree with the published
    graph, and must never see orphan envelope-only ids.
    """
    path = tmp_path / "concurrent.duckdb"
    store = DuckDBGraphSnapshotStore(path)
    first = _basic_transfer_snapshot("first")
    store.put(first)

    expected_nodes: dict[str, int] = {
        "first": len(first.graph.nodes),
    }
    expected_edges: dict[str, int] = {
        "first": len(first.graph.edges),
    }
    expected_digests: dict[str, str] = {
        "first": first.identity.digest,
    }

    stop = threading.Event()
    errors: list[BaseException] = []
    reader_hits = {"n": 0}

    def writer() -> None:
        try:
            for i in range(8):
                sid = f"w-{i:02d}"
                snap = _basic_transfer_snapshot(
                    sid, graph_id=f"gw-{i}", provider=f"prov-{i}"
                )
                expected_nodes[sid] = len(snap.graph.nodes)
                expected_edges[sid] = len(snap.graph.edges)
                expected_digests[sid] = snap.identity.digest
                store.put(snap)
                # Occasionally publish a heavier dual-plane graph.
                if i % 3 == 0:
                    psid = f"p-{i:02d}"
                    plane_snap = _dual_plane_snapshot(psid)
                    expected_nodes[psid] = len(plane_snap.graph.nodes)
                    expected_edges[psid] = len(plane_snap.graph.edges)
                    expected_digests[psid] = plane_snap.identity.digest
                    store.put(plane_snap)
                time.sleep(0.001)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            stop.set()

    def reader() -> None:
        try:
            while not stop.is_set() or reader_hits["n"] < 5:
                ids = store.list_ids()
                # Never see ids that cannot fully load.
                for sid in ids:
                    loaded = store.get(sid)
                    assert len(loaded.graph.nodes) == expected_nodes[sid]
                    assert len(loaded.graph.edges) == expected_edges[sid]
                    assert loaded.identity.digest == expected_digests[sid]
                    # Envelope and typed tables agree on identity digests.
                    assert loaded.graph_digest == loaded.graph.identity.digest
                reader_hits["n"] += 1
                time.sleep(0.001)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [
        threading.Thread(target=writer),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"concurrent errors: {errors}"
    assert reader_hits["n"] >= 5
    # Final state is complete and fully loadable.
    for sid in store.list_ids():
        loaded = store.get(sid)
        assert loaded.identity.digest == expected_digests[sid]
        assert len(loaded.graph.nodes) == expected_nodes[sid]
    store.close()


def test_put_is_atomic_all_or_nothing(mem_store: DuckDBGraphSnapshotStore) -> None:
    snap = _reorg_and_retract_snapshot()
    mem_store.put(snap)
    # Envelope + children + lineage all present together.
    with mem_store._read() as conn:
        n_snap = conn.execute(
            "SELECT count(*) FROM crypto_flow_snapshots WHERE snapshot_id = ?",
            ["snap-reorg"],
        ).fetchone()[0]
        n_nodes = conn.execute(
            "SELECT count(*) FROM crypto_flow_nodes WHERE snapshot_id = ?",
            ["snap-reorg"],
        ).fetchone()[0]
        n_edges = conn.execute(
            "SELECT count(*) FROM crypto_flow_edges WHERE snapshot_id = ?",
            ["snap-reorg"],
        ).fetchone()[0]
        n_lineage = conn.execute(
            "SELECT count(*) FROM crypto_flow_lineage_events WHERE snapshot_id = ?",
            ["snap-reorg"],
        ).fetchone()[0]
    assert n_snap == 1
    assert n_nodes == len(snap.graph.nodes)
    assert n_edges == len(snap.graph.edges)
    assert n_lineage >= 2  # reorg + retraction at minimum


def test_rejects_non_snapshot(store: DuckDBGraphSnapshotStore) -> None:
    with pytest.raises(Exception):
        store.put({"snapshot_id": "x"})  # type: ignore[arg-type]
