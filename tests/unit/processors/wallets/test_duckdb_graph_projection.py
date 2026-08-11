"""Unit tests for wallet → crypto-flow graph projection (DQK-038).

Acceptance coverage:

* Projection is idempotent by ledger and graph revision
* Reorgs retract rather than silently mutate history
* Asserted and observed planes cannot be confused
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.knowledge_graphs.crypto_flows.model import (  # noqa: E402
    AmbiguityKind,
    DerivationMethod,
    EdgeKind,
    FinalityStatus,
    GraphPlane,
    NodeKind,
    RetractionStatus,
)
from ipfs_datasets_py.processors.wallets.duckdb_graph_projection import (  # noqa: E402
    DUCKDB_WALLET_GRAPH_PROJECTION_INTERFACE,
    DUCKDB_WALLET_GRAPH_PROJECTION_SCHEMA,
    EntityAssertion,
    PlaneConfusionError,
    ProjectionStatus,
    WalletCryptoFlowProjector,
    WalletGraphProjectionError,
    map_wallet_finality,
    normalize_genesis_digest,
    open_wallet_graph_projector,
    projection_snapshot_id,
    to_chain_identity,
    transfer_edge_id,
)
from ipfs_datasets_py.processors.wallets.models import (  # noqa: E402
    AccountKind,
    AccountRef,
    AssetKind,
    AssetRef,
    ChainRef,
    ExactAmount,
    Finality,
    LedgerPosition,
    Provenance,
    RawPayloadRef,
    TransactionStatus,
    TransferKind,
    TransferRecord,
    TransactionRecord,
    UTXORecord,
    VersionedExtension,
)


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
DIGEST = "sha256:" + ("cd" * 32)
GENESIS = "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"
BTC_GENESIS = "000000000019d6689c085ae165831e93d807aadf46290dc2ec96a94f0e3a3f9c"


@pytest.fixture
def eth_chain() -> ChainRef:
    return ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=GENESIS,
    )


@pytest.fixture
def btc_chain() -> ChainRef:
    return ChainRef(
        namespace="bip122",
        network="bitcoin-mainnet",
        chain_id="000000000019d6689c085ae165831e93",
        genesis_hash=BTC_GENESIS,
    )


@pytest.fixture
def provenance() -> Provenance:
    return Provenance(
        provider="fixture-rpc",
        provider_kind="json-rpc",
        request_id="req-graph-001",
        scope="wallet:0xabc",
        observed_at=NOW,
        raw_payload=RawPayloadRef(
            digest=DIGEST,
            cid="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
            media_type="application/json",
            byte_length=128,
        ),
    )


@pytest.fixture
def eth_asset(eth_chain: ChainRef) -> AssetRef:
    return AssetRef(
        chain=eth_chain,
        asset_namespace="native",
        asset_reference="eth",
        decimals=18,
        kind=AssetKind.NATIVE,
        symbol="ETH",
    )


@pytest.fixture
def btc_asset(btc_chain: ChainRef) -> AssetRef:
    return AssetRef(
        chain=btc_chain,
        asset_namespace="native",
        asset_reference="btc",
        decimals=8,
        kind=AssetKind.NATIVE,
        symbol="BTC",
    )


@pytest.fixture
def projector(tmp_path: Path) -> WalletCryptoFlowProjector:
    p = WalletCryptoFlowProjector(tmp_path / "wallet_graph.duckdb")
    yield p
    p.close()


@pytest.fixture
def mem_projector() -> WalletCryptoFlowProjector:
    p = open_wallet_graph_projector(":memory:")
    yield p
    p.close()


def _account(chain: ChainRef, address: str, kind: AccountKind = AccountKind.ADDRESS) -> AccountRef:
    return AccountRef(chain=chain, address=address, kind=kind)


def _transfer(
    chain: ChainRef,
    asset: AssetRef,
    provenance: Provenance,
    *,
    tx_hash: str = "0xtx1",
    index: int = 0,
    src: str | None = "0xaaa",
    dst: str | None = "0xbbb",
    amount: int = 10**18,
    finality: Finality = Finality.FINALIZED,
    transfer_kind: TransferKind = TransferKind.NATIVE,
    sequence: int = 100,
    extensions: dict | None = None,
) -> TransferRecord:
    return TransferRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(sequence=sequence, hash=f"0xblock{sequence}"),
        finality=finality,
        transaction_hash=tx_hash,
        transfer_index=index,
        asset=asset,
        amount=ExactAmount.from_int(amount, decimals=asset.decimals),
        source_account=_account(chain, src) if src else None,
        destination_account=_account(chain, dst) if dst else None,
        transfer_kind=transfer_kind,
        extensions=extensions or {},
    )


# ---------------------------------------------------------------------------
# Helpers / mapping
# ---------------------------------------------------------------------------


def test_interface_pins() -> None:
    assert DUCKDB_WALLET_GRAPH_PROJECTION_INTERFACE.startswith("WalletCryptoFlow")
    assert "graph-projection" in DUCKDB_WALLET_GRAPH_PROJECTION_SCHEMA


def test_normalize_genesis_digest_strips_0x() -> None:
    digest = normalize_genesis_digest(GENESIS)
    assert digest.startswith("sha256:")
    assert "0x" not in digest
    assert len(digest.split(":", 1)[1]) == 64


def test_map_wallet_finality_correction_states() -> None:
    assert map_wallet_finality(Finality.FINALIZED) is FinalityStatus.FINALIZED
    assert map_wallet_finality(Finality.ORPHANED) is FinalityStatus.REORGED
    assert map_wallet_finality(Finality.REVERTED) is FinalityStatus.REORGED
    assert map_wallet_finality(Finality.FAILED) is FinalityStatus.RETRACTED
    assert map_wallet_finality(Finality.PENDING) is FinalityStatus.PROPOSED


def test_to_chain_identity(eth_chain: ChainRef) -> None:
    identity = to_chain_identity(eth_chain)
    assert identity.chain_namespace == "eip155"
    assert identity.genesis_digest.startswith("sha256:")


def test_projection_snapshot_id_is_deterministic() -> None:
    a = projection_snapshot_id("g", "ledger-1", "graph-1")
    b = projection_snapshot_id("g", "ledger-1", "graph-1")
    c = projection_snapshot_id("g", "ledger-1", "graph-2")
    assert a == b
    assert a != c


# ---------------------------------------------------------------------------
# Basic observed projection
# ---------------------------------------------------------------------------


def test_project_transfer_builds_observed_nodes_and_edge(
    mem_projector: WalletCryptoFlowProjector,
    eth_chain: ChainRef,
    eth_asset: AssetRef,
    provenance: Provenance,
) -> None:
    record = _transfer(eth_chain, eth_asset, provenance)
    receipt = mem_projector.project(
        [record],
        ledger_revision="ledger-v1",
        graph_revision="graph-v1",
    )
    assert receipt.applied is True
    assert receipt.status is ProjectionStatus.APPLIED
    assert receipt.node_count >= 2
    assert receipt.edge_count >= 1
    assert receipt.observed_node_count >= 2
    assert receipt.asserted_node_count == 0
    assert receipt.observed_edge_count >= 1
    assert receipt.asserted_edge_count == 0

    snap = mem_projector.get_snapshot(
        ledger_revision="ledger-v1", graph_revision="graph-v1"
    )
    assert snap.snapshot_id == receipt.snapshot_id
    observed = snap.graph.nodes_on_plane(GraphPlane.OBSERVED_ADDRESS)
    assert all(n.entity_ref == "" for n in observed)
    assert all(n.plane is GraphPlane.OBSERVED_ADDRESS for n in observed)
    edges = snap.graph.edges_on_plane(GraphPlane.OBSERVED_ADDRESS)
    assert len(edges) >= 1
    edge = next(e for e in edges if e.attributes.get("record_id") == record.record_id)
    assert edge.finality is FinalityStatus.FINALIZED
    assert edge.retraction is RetractionStatus.NOT_RETRACTED
    assert edge.amount is not None
    assert edge.amount.base_units == str(10**18)


def test_project_mint_and_burn_use_system_endpoints(
    mem_projector: WalletCryptoFlowProjector,
    eth_chain: ChainRef,
    eth_asset: AssetRef,
    provenance: Provenance,
) -> None:
    mint = _transfer(
        eth_chain,
        eth_asset,
        provenance,
        tx_hash="0xmint",
        src=None,
        dst="0xccc",
        transfer_kind=TransferKind.MINT,
    )
    burn = _transfer(
        eth_chain,
        eth_asset,
        provenance,
        tx_hash="0xburn",
        index=1,
        src="0xccc",
        dst=None,
        transfer_kind=TransferKind.BURN,
    )
    receipt = mem_projector.project(
        [mint, burn],
        ledger_revision="ledger-mint",
        graph_revision="graph-mint",
    )
    assert receipt.applied
    snap = mem_projector.get_snapshot(
        ledger_revision="ledger-mint", graph_revision="graph-mint"
    )
    roles = {
        n.attributes.get("system_role")
        for n in snap.graph.nodes
        if n.attributes.get("system_role")
    }
    assert "mint" in roles
    assert "burn" in roles


def test_project_utxo_and_transaction(
    mem_projector: WalletCryptoFlowProjector,
    btc_chain: ChainRef,
    btc_asset: AssetRef,
    provenance: Provenance,
) -> None:
    owner = _account(btc_chain, "bc1qowner")
    utxo = UTXORecord(
        chain=btc_chain,
        provenance=provenance,
        ledger_position=LedgerPosition(sequence=800000, hash="0xbtcblock"),
        finality=Finality.CONFIRMED,
        transaction_hash="0xbtctx",
        output_index=0,
        asset=btc_asset,
        amount=ExactAmount.from_int(50_000_000, decimals=8),
        owner=owner,
        spent_by_transaction_hash="0xspendtx",
    )
    tx = TransactionRecord(
        chain=btc_chain,
        provenance=provenance,
        ledger_position=LedgerPosition(sequence=800000, hash="0xbtcblock"),
        finality=Finality.CONFIRMED,
        transaction_hash="0xbtctx",
        status=TransactionStatus.SUCCEEDED,
        participants=(owner,),
    )
    receipt = mem_projector.project(
        [utxo, tx],
        ledger_revision="ledger-btc",
        graph_revision="graph-btc",
    )
    assert receipt.applied
    snap = mem_projector.get_snapshot(
        ledger_revision="ledger-btc", graph_revision="graph-btc"
    )
    kinds = {n.kind for n in snap.graph.nodes}
    assert NodeKind.UTXO in kinds
    assert NodeKind.TRANSACTION in kinds
    edge_kinds = {e.kind for e in snap.graph.edges}
    assert EdgeKind.CREATES in edge_kinds or EdgeKind.SPENDS in edge_kinds


# ---------------------------------------------------------------------------
# Idempotency by ledger + graph revision
# ---------------------------------------------------------------------------


def test_projection_idempotent_by_ledger_and_graph_revision(
    projector: WalletCryptoFlowProjector,
    eth_chain: ChainRef,
    eth_asset: AssetRef,
    provenance: Provenance,
) -> None:
    record = _transfer(eth_chain, eth_asset, provenance)
    first = projector.project(
        [record],
        ledger_revision="L1",
        graph_revision="G1",
    )
    second = projector.project(
        [record],
        ledger_revision="L1",
        graph_revision="G1",
    )
    assert first.applied is True
    assert second.applied is False
    assert second.status is ProjectionStatus.IDEMPOTENT_REPLAY
    assert first.snapshot_id == second.snapshot_id
    assert first.identity_digest == second.identity_digest
    assert first.graph_digest == second.graph_digest

    # Different graph revision → new snapshot.
    third = projector.project(
        [record],
        ledger_revision="L1",
        graph_revision="G2",
    )
    assert third.applied is True
    assert third.snapshot_id != first.snapshot_id

    # Different ledger revision → new snapshot.
    fourth = projector.project(
        [record],
        ledger_revision="L2",
        graph_revision="G1",
    )
    assert fourth.applied is True
    assert fourth.snapshot_id != first.snapshot_id

    pairs = projector.list_revision_pairs()
    assert ("L1", "G1") in pairs
    assert ("L1", "G2") in pairs
    assert ("L2", "G1") in pairs


def test_idempotent_replay_does_not_mutate_prior_snapshot(
    projector: WalletCryptoFlowProjector,
    eth_chain: ChainRef,
    eth_asset: AssetRef,
    provenance: Provenance,
) -> None:
    record = _transfer(eth_chain, eth_asset, provenance)
    first = projector.project(
        [record], ledger_revision="L", graph_revision="G"
    )
    before = projector.get_snapshot(ledger_revision="L", graph_revision="G")
    projector.project([record], ledger_revision="L", graph_revision="G")
    after = projector.get_snapshot(ledger_revision="L", graph_revision="G")
    assert before.identity.digest == after.identity.digest
    assert before.graph.identity.digest == after.graph.identity.digest
    assert first.identity_digest == after.identity.digest


# ---------------------------------------------------------------------------
# Reorgs retract rather than silently mutate history
# ---------------------------------------------------------------------------


def test_reorg_marks_edge_superseded_and_preserves_parent_history(
    projector: WalletCryptoFlowProjector,
    eth_chain: ChainRef,
    eth_asset: AssetRef,
    provenance: Provenance,
) -> None:
    record = _transfer(eth_chain, eth_asset, provenance, tx_hash="0xreorg-tx")
    edge_id = transfer_edge_id(record)

    parent = projector.project(
        [record],
        ledger_revision="ledger-pre",
        graph_revision="graph-pre",
    )
    assert parent.applied
    parent_snap = projector.get_snapshot(
        ledger_revision="ledger-pre", graph_revision="graph-pre"
    )
    parent_edge = parent_snap.graph.edge_map()[edge_id]
    assert parent_edge.finality is FinalityStatus.FINALIZED
    assert parent_edge.retraction is RetractionStatus.NOT_RETRACTED
    parent_digest = parent_snap.identity.digest

    # Successor revision applies reorg without mutating parent snapshot.
    replacement = _transfer(
        eth_chain,
        eth_asset,
        provenance,
        tx_hash="0xreorg-tx",
        sequence=101,
        amount=2 * 10**18,
        finality=Finality.FINALIZED,
    )
    # New transfer has different record_id (sequence not in transfer identity —
    # actually transfer identity is tx_hash + index, so same record_id!).
    # Use a distinct transfer index for the replacement edge.
    replacement = _transfer(
        eth_chain,
        eth_asset,
        provenance,
        tx_hash="0xreorg-tx-new",
        index=0,
        sequence=101,
        amount=2 * 10**18,
    )

    child = projector.project(
        [replacement],
        ledger_revision="ledger-post",
        graph_revision="graph-post",
        parent_ledger_revision="ledger-pre",
        parent_graph_revision="graph-pre",
        reorg_ids=[record.record_id],
    )
    assert child.applied
    assert edge_id in child.reorged_edge_ids

    # Parent snapshot is unchanged (history not silently mutated).
    parent_after = projector.get_snapshot(
        ledger_revision="ledger-pre", graph_revision="graph-pre"
    )
    assert parent_after.identity.digest == parent_digest
    assert (
        parent_after.graph.edge_map()[edge_id].finality is FinalityStatus.FINALIZED
    )
    assert (
        parent_after.graph.edge_map()[edge_id].retraction
        is RetractionStatus.NOT_RETRACTED
    )

    # Child retains the reorged edge as SUPERSEDED/REORGED plus the replacement.
    child_snap = projector.get_snapshot(
        ledger_revision="ledger-post", graph_revision="graph-post"
    )
    reorged = child_snap.graph.edge_map()[edge_id]
    assert reorged.finality is FinalityStatus.REORGED
    assert reorged.retraction is RetractionStatus.SUPERSEDED
    active = child_snap.graph.active_edges()
    active_ids = {e.edge_id for e in active}
    assert edge_id not in active_ids
    assert transfer_edge_id(replacement) in active_ids

    # Lineage events retained in durable store.
    lineage = projector.store.list_reorg_history(snapshot_id=child.snapshot_id)
    assert any(ev.entity_id == edge_id for ev in lineage)


def test_retract_edge_preserves_history(
    mem_projector: WalletCryptoFlowProjector,
    eth_chain: ChainRef,
    eth_asset: AssetRef,
    provenance: Provenance,
) -> None:
    record = _transfer(eth_chain, eth_asset, provenance, tx_hash="0xret")
    mem_projector.project(
        [record], ledger_revision="L0", graph_revision="G0"
    )
    receipt = mem_projector.project(
        [],
        ledger_revision="L1",
        graph_revision="G1",
        parent_ledger_revision="L0",
        parent_graph_revision="G0",
        retract_ids=[record.record_id],
    )
    assert receipt.applied
    edge_id = transfer_edge_id(record)
    assert edge_id in receipt.retracted_edge_ids
    snap = mem_projector.get_snapshot(ledger_revision="L1", graph_revision="G1")
    edge = snap.graph.edge_map()[edge_id]
    assert edge.retraction is RetractionStatus.RETRACTED
    assert edge.finality is FinalityStatus.RETRACTED
    # Still present in full history (not deleted).
    assert edge_id in snap.graph.edge_map()
    assert edge_id not in {e.edge_id for e in snap.graph.active_edges()}


def test_orphan_finality_projects_as_reorged_edge(
    mem_projector: WalletCryptoFlowProjector,
    eth_chain: ChainRef,
    eth_asset: AssetRef,
    provenance: Provenance,
) -> None:
    record = _transfer(
        eth_chain,
        eth_asset,
        provenance,
        finality=Finality.ORPHANED,
        tx_hash="0xorphan",
    )
    receipt = mem_projector.project(
        [record], ledger_revision="Lo", graph_revision="Go"
    )
    snap = mem_projector.get_snapshot(ledger_revision="Lo", graph_revision="Go")
    edge = snap.graph.edge_map()[transfer_edge_id(record)]
    assert edge.finality is FinalityStatus.REORGED
    assert edge.retraction is RetractionStatus.SUPERSEDED
    assert edge.ambiguity is AmbiguityKind.REORG
    assert receipt.observed_edge_count >= 1


# ---------------------------------------------------------------------------
# Asserted vs observed plane separation
# ---------------------------------------------------------------------------


def test_asserted_and_observed_planes_remain_separate(
    mem_projector: WalletCryptoFlowProjector,
    eth_chain: ChainRef,
    eth_asset: AssetRef,
    provenance: Provenance,
) -> None:
    record = _transfer(eth_chain, eth_asset, provenance, tx_hash="0xplanes")
    assertion = EntityAssertion(
        entity_ref="entity:alice",
        related_entity_ref="entity:bob",
        relation=EdgeKind.OWNS,
        ambiguity=AmbiguityKind.MULTI_PARTY,
        confidence="0.4",
        derivation=DerivationMethod.HEURISTIC_CLUSTER,
        provider_ids=("analyst",),
    )
    receipt = mem_projector.project(
        [record],
        ledger_revision="Lp",
        graph_revision="Gp",
        assertions=[assertion],
    )
    assert receipt.asserted_node_count >= 2
    assert receipt.observed_node_count >= 2
    assert receipt.asserted_edge_count >= 1
    assert receipt.observed_edge_count >= 1

    snap = mem_projector.get_snapshot(ledger_revision="Lp", graph_revision="Gp")
    for node in snap.graph.nodes_on_plane(GraphPlane.OBSERVED_ADDRESS):
        assert node.entity_ref == ""
        assert node.plane is GraphPlane.OBSERVED_ADDRESS
    for node in snap.graph.nodes_on_plane(GraphPlane.ASSERTED_ENTITY):
        assert node.kind is not NodeKind.ADDRESS
        assert node.address_ref == ""
        assert node.entity_ref
    for edge in snap.graph.edges:
        src = snap.graph.node_map()[edge.source_node_id]
        tgt = snap.graph.node_map()[edge.target_node_id]
        assert edge.plane is src.plane is tgt.plane


def test_plane_confusion_rejected_for_address_kind_assertion() -> None:
    with pytest.raises(PlaneConfusionError):
        EntityAssertion(
            entity_ref="entity:x",
            kind=NodeKind.ADDRESS,
        )


def test_asserted_relation_requires_ambiguity(
    mem_projector: WalletCryptoFlowProjector,
) -> None:
    assertion = EntityAssertion(
        entity_ref="entity:a",
        related_entity_ref="entity:b",
        ambiguity=AmbiguityKind.NONE,
    )
    with pytest.raises(PlaneConfusionError, match="non-NONE ambiguity"):
        mem_projector.project(
            [],
            ledger_revision="La",
            graph_revision="Ga",
            assertions=[assertion],
        )


def test_ambiguity_extension_preserved_on_transfer(
    mem_projector: WalletCryptoFlowProjector,
    eth_chain: ChainRef,
    eth_asset: AssetRef,
    provenance: Provenance,
) -> None:
    record = _transfer(
        eth_chain,
        eth_asset,
        provenance,
        tx_hash="0xcj",
        extensions={
            "crypto_flow": VersionedExtension(
                schema_version="crypto-flow-hint/v1",
                data={
                    "ambiguity": "coinjoin",
                    "derivation": "heuristic_coinjoin",
                    "edge_kind": "coinjoin",
                },
            )
        },
    )
    mem_projector.project(
        [record], ledger_revision="Lc", graph_revision="Gc"
    )
    snap = mem_projector.get_snapshot(ledger_revision="Lc", graph_revision="Gc")
    edge = snap.graph.edge_map()[transfer_edge_id(record)]
    assert edge.ambiguity is AmbiguityKind.COINJOIN
    assert edge.derivation is DerivationMethod.HEURISTIC_COINJOIN
    assert edge.kind is EdgeKind.COINJOIN
    assert edge.confidence != "1"


# ---------------------------------------------------------------------------
# Failure modes / durability
# ---------------------------------------------------------------------------


def test_missing_parent_fails_closed(
    mem_projector: WalletCryptoFlowProjector,
) -> None:
    with pytest.raises(WalletGraphProjectionError, match="parent graph revision"):
        mem_projector.project(
            [],
            ledger_revision="L",
            graph_revision="G",
            parent_ledger_revision="missing-L",
            parent_graph_revision="missing-G",
        )


def test_unknown_reorg_id_fails_closed(
    mem_projector: WalletCryptoFlowProjector,
    eth_chain: ChainRef,
    eth_asset: AssetRef,
    provenance: Provenance,
) -> None:
    record = _transfer(eth_chain, eth_asset, provenance)
    mem_projector.project(
        [record], ledger_revision="L0", graph_revision="G0"
    )
    with pytest.raises(WalletGraphProjectionError, match="unknown edge"):
        mem_projector.project(
            [],
            ledger_revision="L1",
            graph_revision="G1",
            parent_ledger_revision="L0",
            parent_graph_revision="G0",
            reorg_ids=["urn:wallet:transfer:sha256:" + ("00" * 32)],
        )


def test_empty_revision_rejected(
    mem_projector: WalletCryptoFlowProjector,
) -> None:
    with pytest.raises(WalletGraphProjectionError):
        mem_projector.project([], ledger_revision="", graph_revision="G")
    with pytest.raises(WalletGraphProjectionError):
        mem_projector.project([], ledger_revision="L", graph_revision="")


def test_closed_projector_rejects_project(
    eth_chain: ChainRef,
    eth_asset: AssetRef,
    provenance: Provenance,
) -> None:
    p = open_wallet_graph_projector(":memory:")
    p.close()
    with pytest.raises(WalletGraphProjectionError, match="closed"):
        p.project(
            [_transfer(eth_chain, eth_asset, provenance)],
            ledger_revision="L",
            graph_revision="G",
        )


def test_file_backed_roundtrip(
    tmp_path: Path,
    eth_chain: ChainRef,
    eth_asset: AssetRef,
    provenance: Provenance,
) -> None:
    path = tmp_path / "durable.duckdb"
    record = _transfer(eth_chain, eth_asset, provenance, tx_hash="0xdur")
    with open_wallet_graph_projector(path) as p:
        receipt = p.project(
            [record], ledger_revision="Ld", graph_revision="Gd"
        )
        assert receipt.applied
        digest = receipt.identity_digest

    with open_wallet_graph_projector(path) as p2:
        assert p2.contains(ledger_revision="Ld", graph_revision="Gd")
        snap = p2.get_snapshot(ledger_revision="Ld", graph_revision="Gd")
        assert snap.identity.digest == digest
        # Idempotent after reopen.
        again = p2.project(
            [record], ledger_revision="Ld", graph_revision="Gd"
        )
        assert again.status is ProjectionStatus.IDEMPOTENT_REPLAY
