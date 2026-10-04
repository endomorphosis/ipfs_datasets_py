"""Unit tests for multi-chain monetary-flow knowledge graph (CRYPTOIR-G420).

Acceptance coverage:

* nodes and edges bind chain, ledger coordinate, asset, exact amount, direction,
  finality, source, confidence, validity, derivation, and retraction;
* observed-address and asserted-entity graphs remain separate;
* UTXO and account ledgers are chain-correct;
* pool, mixer, exchange, bridge, CoinJoin, peel/change, and shared-infrastructure
  ambiguity is preserved;
* deterministic snapshots report provider/range/asset completeness;
* reorg/retraction supersede rather than mutate;
* GraphRAG/heuristic candidates never claim certainty.
"""

from __future__ import annotations

import dataclasses

import pytest

from ipfs_datasets_py.knowledge_graphs.crypto_flows import (
    AmbiguityKind,
    CompletenessReceipt,
    CompletenessStatus,
    CryptoFlowGraph,
    CryptoFlowGraphBuilder,
    CryptoFlowValidationError,
    DerivationMethod,
    EdgeKind,
    ExactAmount,
    FinalityStatus,
    FlowDirection,
    FlowEdge,
    FlowNode,
    GraphPlane,
    GraphSnapshot,
    InMemoryGraphSnapshotStore,
    LedgerCoordinate,
    LedgerModel,
    NodeKind,
    RetractionStatus,
    SnapshotStoreError,
    ValidityWindow,
    assert_ledger_model_chain_correct,
    build_graph_from_records,
    default_ledger_model,
)
from ipfs_datasets_py.logic.crypto_ir.model import AssetIdentity, ChainIdentity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


GENESIS_ETH = "sha256:" + ("ab" * 32)
GENESIS_BTC = "sha256:" + ("cd" * 32)
GENESIS_SOL = "sha256:" + ("ef" * 32)


def eth_chain() -> ChainIdentity:
    return ChainIdentity(
        chain_namespace="eip155",
        network="ethereum-mainnet",
        genesis_digest=GENESIS_ETH,
        chain_id="1",
        display_name="Ethereum Mainnet",
    )


def btc_chain() -> ChainIdentity:
    return ChainIdentity(
        chain_namespace="bip122",
        network="bitcoin-mainnet",
        genesis_digest=GENESIS_BTC,
        chain_id="000000000019d6689c085ae165831e93",
        display_name="Bitcoin Mainnet",
    )


def sol_chain() -> ChainIdentity:
    return ChainIdentity(
        chain_namespace="solana",
        network="solana-mainnet",
        genesis_digest=GENESIS_SOL,
        chain_id="5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
        display_name="Solana Mainnet",
    )


def eth_asset() -> AssetIdentity:
    return AssetIdentity(
        chain=eth_chain(),
        asset_namespace="native",
        asset_reference="eth",
        decimals=18,
        symbol="ETH",
    )


def btc_asset() -> AssetIdentity:
    return AssetIdentity(
        chain=btc_chain(),
        asset_namespace="native",
        asset_reference="btc",
        decimals=8,
        symbol="BTC",
    )


def sol_asset() -> AssetIdentity:
    return AssetIdentity(
        chain=sol_chain(),
        asset_namespace="native",
        asset_reference="sol",
        decimals=9,
        symbol="SOL",
    )


def completeness(
    receipt_id: str,
    chain: ChainIdentity,
    *,
    providers: tuple[str, ...] = ("provider-a",),
    status: CompletenessStatus = CompletenessStatus.COMPLETE,
    covered: tuple[LedgerCoordinate, ...] = (),
    missing: tuple[LedgerCoordinate, ...] = (),
) -> CompletenessReceipt:
    return CompletenessReceipt(
        receipt_id=receipt_id,
        chain=chain,
        scope="ledger-range",
        completeness=status,
        finality=FinalityStatus.FINALIZED,
        validity=ValidityWindow(start="2024-01-01T00:00:00Z", end=""),
        retraction=RetractionStatus.NOT_RETRACTED,
        covered_ranges=covered or (LedgerCoordinate(sequence=1, hash="0x1"),),
        missing_ranges=missing,
        provider_ids=providers,
    )


# ---------------------------------------------------------------------------
# Ledger model correctness
# ---------------------------------------------------------------------------


def test_default_ledger_models_are_chain_correct() -> None:
    assert default_ledger_model(eth_chain()) is LedgerModel.ACCOUNT
    assert default_ledger_model(btc_chain()) is LedgerModel.UTXO
    assert default_ledger_model(sol_chain()) is LedgerModel.ACCOUNT


def test_assert_ledger_model_rejects_mismatched_utxo_on_evm() -> None:
    with pytest.raises(CryptoFlowValidationError, match="chain-correct"):
        assert_ledger_model_chain_correct(eth_chain(), LedgerModel.UTXO)


def test_flow_node_rejects_utxo_model_on_ethereum() -> None:
    with pytest.raises(CryptoFlowValidationError, match="chain-correct"):
        FlowNode(
            node_id="n1",
            kind=NodeKind.ADDRESS,
            plane=GraphPlane.OBSERVED_ADDRESS,
            chain=eth_chain(),
            ledger_model=LedgerModel.UTXO,
            address_ref="0xabc",
        )


def test_flow_edge_rejects_account_model_on_bitcoin() -> None:
    with pytest.raises(CryptoFlowValidationError, match="chain-correct"):
        FlowEdge(
            edge_id="e1",
            kind=EdgeKind.TRANSFER,
            plane=GraphPlane.OBSERVED_ADDRESS,
            source_node_id="a",
            target_node_id="b",
            chain=btc_chain(),
            ledger_model=LedgerModel.ACCOUNT,
        )


# ---------------------------------------------------------------------------
# Plane separation
# ---------------------------------------------------------------------------


def test_observed_address_plane_rejects_entity_ref() -> None:
    with pytest.raises(CryptoFlowValidationError, match="entity_ref"):
        FlowNode(
            node_id="n1",
            kind=NodeKind.ADDRESS,
            plane=GraphPlane.OBSERVED_ADDRESS,
            chain=eth_chain(),
            ledger_model=LedgerModel.ACCOUNT,
            address_ref="0xabc",
            entity_ref="entity:evil",
        )


def test_asserted_entity_plane_rejects_raw_address_kind() -> None:
    with pytest.raises(CryptoFlowValidationError, match="ADDRESS"):
        FlowNode(
            node_id="n1",
            kind=NodeKind.ADDRESS,
            plane=GraphPlane.ASSERTED_ENTITY,
            entity_ref="entity:x",
        )


def test_edges_cannot_cross_planes() -> None:
    builder = CryptoFlowGraphBuilder("plane-test")
    builder.add_observed_address(
        "addr-1", chain=eth_chain(), address="0xaaa", provider_ids=("p1",)
    )
    builder.add_asserted_entity("ent-1", entity_ref="entity:alice")
    with pytest.raises(CryptoFlowValidationError, match="cross graph planes"):
        builder.add_edge(
            FlowEdge(
                edge_id="cross",
                kind=EdgeKind.OWNS,
                plane=GraphPlane.OBSERVED_ADDRESS,
                source_node_id="addr-1",
                target_node_id="ent-1",
            )
        )


def test_planes_remain_separate_in_built_graph() -> None:
    builder = CryptoFlowGraphBuilder("planes")
    builder.add_observed_address(
        "addr-1", chain=eth_chain(), address="0xaaa"
    )
    builder.add_asserted_entity("ent-1", entity_ref="entity:alice")
    graph = builder.build()
    assert len(graph.nodes_on_plane(GraphPlane.OBSERVED_ADDRESS)) == 1
    assert len(graph.nodes_on_plane(GraphPlane.ASSERTED_ENTITY)) == 1
    assert graph.nodes_on_plane(GraphPlane.OBSERVED_ADDRESS)[0].entity_ref == ""
    assert graph.nodes_on_plane(GraphPlane.ASSERTED_ENTITY)[0].address_ref == ""


# ---------------------------------------------------------------------------
# Node/edge field bindings
# ---------------------------------------------------------------------------


def test_node_and_edge_bind_required_semantics() -> None:
    chain = eth_chain()
    asset = eth_asset()
    coord = LedgerCoordinate(sequence=18_000_000, hash="0xblock", transaction_index=3)
    amount = ExactAmount.from_int(10**18, decimals=18)
    node = FlowNode(
        node_id="acct-from",
        kind=NodeKind.ACCOUNT,
        plane=GraphPlane.OBSERVED_ADDRESS,
        chain=chain,
        ledger_model=LedgerModel.ACCOUNT,
        coordinate=coord,
        asset=asset,
        amount=amount,
        address_ref="0xfrom",
        finality=FinalityStatus.FINALIZED,
        source="rpc:erigon",
        confidence="1",
        validity=ValidityWindow(start="2024-06-01T00:00:00Z"),
        derivation=DerivationMethod.DIRECT_OBSERVATION,
        retraction=RetractionStatus.NOT_RETRACTED,
        provider_ids=("erigon",),
    )
    dest = FlowNode(
        node_id="acct-to",
        kind=NodeKind.ACCOUNT,
        plane=GraphPlane.OBSERVED_ADDRESS,
        chain=chain,
        ledger_model=LedgerModel.ACCOUNT,
        address_ref="0xto",
        finality=FinalityStatus.FINALIZED,
        source="rpc:erigon",
        derivation=DerivationMethod.DIRECT_OBSERVATION,
    )
    edge = FlowEdge(
        edge_id="xfer-1",
        kind=EdgeKind.TRANSFER,
        plane=GraphPlane.OBSERVED_ADDRESS,
        source_node_id="acct-from",
        target_node_id="acct-to",
        chain=chain,
        ledger_model=LedgerModel.ACCOUNT,
        coordinate=coord,
        asset=asset,
        amount=amount,
        direction=FlowDirection.OUT,
        finality=FinalityStatus.FINALIZED,
        source="rpc:erigon",
        confidence="1",
        validity=ValidityWindow(start="2024-06-01T00:00:00Z"),
        derivation=DerivationMethod.ACCOUNT_TRANSFER,
        retraction=RetractionStatus.NOT_RETRACTED,
        provider_ids=("erigon",),
        timestamp="2024-06-01T12:00:00Z",
    )
    graph = CryptoFlowGraph(graph_id="bind", nodes=(node, dest), edges=(edge,))
    assert edge.chain is not None
    assert edge.coordinate is not None
    assert edge.asset is not None
    assert edge.amount is not None
    assert edge.direction is FlowDirection.OUT
    assert edge.finality is FinalityStatus.FINALIZED
    assert edge.source == "rpc:erigon"
    assert edge.confidence == "1"
    assert edge.validity.start.startswith("2024")
    assert edge.derivation is DerivationMethod.ACCOUNT_TRANSFER
    assert edge.retraction is RetractionStatus.NOT_RETRACTED
    # Round-trip
    restored = CryptoFlowGraph.from_dict(graph.to_dict())
    assert restored.identity.digest == graph.identity.digest
    assert restored.edges[0].amount is not None
    assert restored.edges[0].amount.base_units == str(10**18)


def test_exact_amount_rejects_float_on_edge() -> None:
    with pytest.raises(Exception):
        ExactAmount(base_units=1.5, decimals=0)  # type: ignore[arg-type]


def test_confidence_rejects_binary_float() -> None:
    with pytest.raises(CryptoFlowValidationError, match="binary floats"):
        FlowNode(
            node_id="n",
            kind=NodeKind.ADDRESS,
            plane=GraphPlane.OBSERVED_ADDRESS,
            chain=eth_chain(),
            ledger_model=LedgerModel.ACCOUNT,
            address_ref="0x1",
            confidence=0.5,  # type: ignore[arg-type]
        )


def test_heuristic_edge_must_preserve_ambiguity_and_non_unit_confidence() -> None:
    with pytest.raises(CryptoFlowValidationError, match="ambiguity"):
        FlowEdge(
            edge_id="h1",
            kind=EdgeKind.SHARED_INFRASTRUCTURE,
            plane=GraphPlane.OBSERVED_ADDRESS,
            source_node_id="a",
            target_node_id="b",
            derivation=DerivationMethod.GRAPHRAG_CANDIDATE,
            ambiguity=AmbiguityKind.NONE,
            confidence="0.2",
        )
    with pytest.raises(CryptoFlowValidationError, match="confidence"):
        FlowEdge(
            edge_id="h2",
            kind=EdgeKind.SHARED_INFRASTRUCTURE,
            plane=GraphPlane.OBSERVED_ADDRESS,
            source_node_id="a",
            target_node_id="b",
            derivation=DerivationMethod.HEURISTIC_SHARED_INFRA,
            ambiguity=AmbiguityKind.SHARED_INFRASTRUCTURE,
            confidence="1",
        )


# ---------------------------------------------------------------------------
# Multi-chain UTXO + account builder fixtures
# ---------------------------------------------------------------------------


def test_multi_chain_utxo_and_account_ingestion() -> None:
    builder = CryptoFlowGraphBuilder("multi-chain")
    # Bitcoin UTXO
    builder.add_observed_address(
        "btc-utxo-in",
        chain=btc_chain(),
        address="bc1qin",
        kind=NodeKind.UTXO,
        provider_ids=("btc-node",),
    )
    builder.add_observed_address(
        "btc-utxo-out",
        chain=btc_chain(),
        address="bc1qout",
        kind=NodeKind.UTXO,
        provider_ids=("btc-node",),
    )
    builder.add_utxo_spend(
        "btc-spend-1",
        source_node_id="btc-utxo-in",
        target_node_id="btc-utxo-out",
        chain=btc_chain(),
        asset=btc_asset(),
        amount=ExactAmount.from_int(50_000_000, decimals=8),
        coordinate=LedgerCoordinate(sequence=800_000, hash="btc-block"),
        provider_ids=("btc-node",),
    )
    # Ethereum account
    builder.add_observed_address(
        "eth-from", chain=eth_chain(), address="0xfrom", provider_ids=("erigon",)
    )
    builder.add_observed_address(
        "eth-to", chain=eth_chain(), address="0xto", provider_ids=("erigon",)
    )
    builder.add_account_transfer(
        "eth-xfer-1",
        source_node_id="eth-from",
        target_node_id="eth-to",
        chain=eth_chain(),
        asset=eth_asset(),
        amount=ExactAmount.from_int(10**18, decimals=18),
        coordinate=LedgerCoordinate(sequence=18_000_000, hash="0xeth"),
        provider_ids=("erigon",),
    )
    # Solana account
    builder.add_observed_address(
        "sol-from", chain=sol_chain(), address="SolFrom111", provider_ids=("sol-rpc",)
    )
    builder.add_observed_address(
        "sol-to", chain=sol_chain(), address="SolTo222", provider_ids=("sol-rpc",)
    )
    builder.add_account_transfer(
        "sol-xfer-1",
        source_node_id="sol-from",
        target_node_id="sol-to",
        chain=sol_chain(),
        asset=sol_asset(),
        amount=ExactAmount.from_int(1_000_000_000, decimals=9),
        coordinate=LedgerCoordinate(sequence=250_000_000, hash="sol-slot"),
        provider_ids=("sol-rpc",),
    )
    builder.add_completeness_receipt(
        completeness("rcpt-eth", eth_chain(), providers=("erigon",))
    )
    builder.add_completeness_receipt(
        completeness("rcpt-btc", btc_chain(), providers=("btc-node",))
    )
    builder.add_completeness_receipt(
        completeness("rcpt-sol", sol_chain(), providers=("sol-rpc",))
    )

    snap = builder.snapshot(
        "snap-multi",
        covered_ranges=(
            LedgerCoordinate(sequence=800_000),
            LedgerCoordinate(sequence=18_000_000),
            LedgerCoordinate(sequence=250_000_000),
        ),
        created_at="2024-07-01T00:00:00Z",
    )
    graph = snap.graph
    assert len(graph.nodes) == 6
    assert len(graph.edges) == 3
    assert all(
        e.ledger_model is LedgerModel.UTXO
        for e in graph.edges
        if e.chain and e.chain.chain_namespace == "bip122"
    )
    assert all(
        e.ledger_model is LedgerModel.ACCOUNT
        for e in graph.edges
        if e.chain and e.chain.chain_namespace in ("eip155", "solana")
    )
    assert snap.completeness is CompletenessStatus.COMPLETE
    assert "erigon" in snap.covered_providers
    assert "btc-node" in snap.covered_providers
    assert "sol-rpc" in snap.covered_providers
    assert len(snap.covered_assets) >= 3
    assert len(snap.covered_chains) >= 3
    assert len(snap.covered_ranges) == 3


# ---------------------------------------------------------------------------
# Ambiguity preservation
# ---------------------------------------------------------------------------


def test_ambiguity_pool_mixer_exchange_bridge_coinjoin_peel_shared() -> None:
    builder = CryptoFlowGraphBuilder("ambiguity")
    chain = btc_chain()
    asset = btc_asset()
    coord = LedgerCoordinate(sequence=700_000, hash="b")

    for nid, addr, kind in (
        ("user-a", "bc1qa", NodeKind.ADDRESS),
        ("user-b", "bc1qb", NodeKind.ADDRESS),
        ("pool-1", "bc1qpool", NodeKind.POOL),
        ("mixer-1", "bc1qmix", NodeKind.MIXER),
        ("exch-1", "bc1qex", NodeKind.EXCHANGE),
        ("bridge-1", "bc1qbr", NodeKind.BRIDGE),
        ("service-infra", "bc1qinfra", NodeKind.SERVICE),
        ("peel-out", "bc1qpeel", NodeKind.ADDRESS),
        ("change-out", "bc1qchg", NodeKind.ADDRESS),
        ("cj-out", "bc1qcj", NodeKind.ADDRESS),
    ):
        builder.add_observed_address(
            nid, chain=chain, address=addr, kind=kind, provider_ids=("btc",)
        )

    # Pool / mixer / exchange deposits preserve ambiguity
    for edge_id, kind, target, amb in (
        ("pool-dep", EdgeKind.POOL_DEPOSIT, "pool-1", AmbiguityKind.POOL),
        ("mix-dep", EdgeKind.MIXER_DEPOSIT, "mixer-1", AmbiguityKind.MIXER),
        ("ex-dep", EdgeKind.EXCHANGE_DEPOSIT, "exch-1", AmbiguityKind.EXCHANGE),
    ):
        builder.add_ambiguous_service_edge(
            edge_id,
            kind=kind,
            source_node_id="user-a",
            target_node_id=target,
            ambiguity=amb,
            chain=chain,
            asset=asset,
            amount=ExactAmount.from_int(100_000, decimals=8),
            coordinate=coord,
            derivation=DerivationMethod.DIRECT_OBSERVATION,
            confidence="1",
            provider_ids=("btc",),
        )

    # Bridge pair across chains
    builder.add_observed_address(
        "eth-dest", chain=eth_chain(), address="0xbridgedest", provider_ids=("erigon",)
    )
    # Bridge node needs to accept multi-chain; use service on BTC side already present.
    builder.add_bridge_pair(
        lock_edge_id="br-lock",
        mint_edge_id="br-mint",
        source_node_id="user-a",
        bridge_node_id="bridge-1",
        dest_node_id="eth-dest",
        source_chain=btc_chain(),
        dest_chain=eth_chain(),
        source_asset=btc_asset(),
        dest_asset=eth_asset(),
        amount=ExactAmount.from_int(10_000, decimals=8),
        source_coordinate=coord,
        dest_coordinate=LedgerCoordinate(sequence=19_000_000, hash="0xe"),
        provider_ids=("bridge-oracle",),
    )

    builder.add_coinjoin(
        "cj-1",
        source_node_id="user-a",
        target_node_id="cj-out",
        chain=chain,
        asset=asset,
        amount=ExactAmount.from_int(50_000, decimals=8),
        coordinate=coord,
        provider_ids=("btc",),
    )
    builder.add_peel_change(
        "peel-1",
        "change-1",
        source_node_id="user-a",
        peel_target_id="peel-out",
        change_target_id="change-out",
        chain=chain,
        asset=asset,
        peel_amount=ExactAmount.from_int(40_000, decimals=8),
        change_amount=ExactAmount.from_int(9_000, decimals=8),
        coordinate=coord,
        provider_ids=("btc",),
    )
    builder.add_ambiguous_service_edge(
        "shared-1",
        kind=EdgeKind.SHARED_INFRASTRUCTURE,
        source_node_id="user-a",
        target_node_id="service-infra",
        ambiguity=AmbiguityKind.SHARED_INFRASTRUCTURE,
        chain=chain,
        derivation=DerivationMethod.HEURISTIC_SHARED_INFRA,
        confidence="0.25",
        provider_ids=("btc",),
    )

    graph = builder.build()
    by_kind = {e.edge_id: e for e in graph.edges}
    assert by_kind["pool-dep"].ambiguity is AmbiguityKind.POOL
    assert by_kind["mix-dep"].ambiguity is AmbiguityKind.MIXER
    assert by_kind["ex-dep"].ambiguity is AmbiguityKind.EXCHANGE
    assert by_kind["br-lock"].ambiguity is AmbiguityKind.BRIDGE
    assert by_kind["br-mint"].ambiguity is AmbiguityKind.BRIDGE
    assert by_kind["cj-1"].ambiguity is AmbiguityKind.COINJOIN
    assert by_kind["peel-1"].ambiguity is AmbiguityKind.PEEL_CHANGE
    assert by_kind["change-1"].ambiguity is AmbiguityKind.PEEL_CHANGE
    assert by_kind["shared-1"].ambiguity is AmbiguityKind.SHARED_INFRASTRUCTURE
    # Never collapse service ambiguity into NONE
    for edge in graph.edges:
        if edge.kind in (
            EdgeKind.POOL_DEPOSIT,
            EdgeKind.MIXER_DEPOSIT,
            EdgeKind.EXCHANGE_DEPOSIT,
            EdgeKind.BRIDGE_LOCK,
            EdgeKind.BRIDGE_MINT,
            EdgeKind.COINJOIN,
            EdgeKind.PEEL,
            EdgeKind.CHANGE,
            EdgeKind.SHARED_INFRASTRUCTURE,
        ):
            assert edge.ambiguity is not AmbiguityKind.NONE


# ---------------------------------------------------------------------------
# Reorg / retraction
# ---------------------------------------------------------------------------


def test_reorg_supersedes_edge_and_installs_replacement() -> None:
    builder = CryptoFlowGraphBuilder("reorg")
    builder.add_observed_address("a", chain=eth_chain(), address="0xa")
    builder.add_observed_address("b", chain=eth_chain(), address="0xb")
    builder.add_account_transfer(
        "xfer-old",
        source_node_id="a",
        target_node_id="b",
        chain=eth_chain(),
        asset=eth_asset(),
        amount=ExactAmount.from_int(1, decimals=18),
        coordinate=LedgerCoordinate(sequence=100, hash="0xold"),
        provider_ids=("rpc",),
    )
    replacement = FlowEdge(
        edge_id="xfer-new",
        kind=EdgeKind.TRANSFER,
        plane=GraphPlane.OBSERVED_ADDRESS,
        source_node_id="a",
        target_node_id="b",
        chain=eth_chain(),
        ledger_model=LedgerModel.ACCOUNT,
        coordinate=LedgerCoordinate(sequence=100, hash="0xnew"),
        asset=eth_asset(),
        amount=ExactAmount.from_int(1, decimals=18),
        direction=FlowDirection.OUT,
        finality=FinalityStatus.FINALIZED,
        source="rpc",
        derivation=DerivationMethod.ACCOUNT_TRANSFER,
        provider_ids=("rpc",),
    )
    reorged = builder.apply_reorg("xfer-old", replacement=replacement)
    assert reorged.finality is FinalityStatus.REORGED
    assert reorged.retraction is RetractionStatus.SUPERSEDED
    graph = builder.build()
    active = graph.active_edges()
    assert len(active) == 1
    assert active[0].edge_id == "xfer-new"
    assert graph.edge_map()["xfer-old"].finality is FinalityStatus.REORGED


def test_retract_edge() -> None:
    builder = CryptoFlowGraphBuilder("retract")
    builder.add_observed_address("a", chain=eth_chain(), address="0xa")
    builder.add_observed_address("b", chain=eth_chain(), address="0xb")
    builder.add_account_transfer(
        "xfer-1",
        source_node_id="a",
        target_node_id="b",
        chain=eth_chain(),
        asset=eth_asset(),
        amount=ExactAmount.from_int(2, decimals=18),
        coordinate=LedgerCoordinate(sequence=50, hash="0x50"),
    )
    builder.retract_edge("xfer-1")
    graph = builder.build()
    assert graph.active_edges() == ()
    assert graph.edges[0].retraction is RetractionStatus.RETRACTED


# ---------------------------------------------------------------------------
# Deterministic snapshots and store
# ---------------------------------------------------------------------------


def test_snapshot_determinism_independent_of_insert_order() -> None:
    def build(order: str) -> GraphSnapshot:
        builder = CryptoFlowGraphBuilder("det")
        if order == "ab":
            builder.add_observed_address("a", chain=eth_chain(), address="0xa")
            builder.add_observed_address("b", chain=eth_chain(), address="0xb")
        else:
            builder.add_observed_address("b", chain=eth_chain(), address="0xb")
            builder.add_observed_address("a", chain=eth_chain(), address="0xa")
        builder.add_account_transfer(
            "x",
            source_node_id="a",
            target_node_id="b",
            chain=eth_chain(),
            asset=eth_asset(),
            amount=ExactAmount.from_int(5, decimals=18),
            coordinate=LedgerCoordinate(sequence=1, hash="0x1"),
            provider_ids=("p",),
        )
        builder.add_completeness_receipt(
            completeness(
                "r1",
                eth_chain(),
                providers=("p",),
                status=CompletenessStatus.PARTIAL,
                missing=(LedgerCoordinate(sequence=2, hash="0x2"),),
            )
        )
        return builder.snapshot(
            "s1",
            covered_ranges=(LedgerCoordinate(sequence=1),),
            missing_ranges=(LedgerCoordinate(sequence=2),),
        )

    s1 = build("ab")
    s2 = build("ba")
    assert s1.graph.identity.digest == s2.graph.identity.digest
    assert s1.identity.digest == s2.identity.digest
    assert s1.completeness is CompletenessStatus.PARTIAL
    assert s1.missing_ranges[0].sequence == 2
    assert "p" in s1.covered_providers


def test_immutable_store_round_trip_and_no_overwrite() -> None:
    builder = CryptoFlowGraphBuilder("store-g")
    builder.add_observed_address("a", chain=eth_chain(), address="0xa")
    builder.add_observed_address("b", chain=eth_chain(), address="0xb")
    builder.add_account_transfer(
        "x",
        source_node_id="a",
        target_node_id="b",
        chain=eth_chain(),
        asset=eth_asset(),
        amount=ExactAmount.from_int(1, decimals=18),
        coordinate=LedgerCoordinate(sequence=9, hash="0x9"),
        provider_ids=("prov",),
    )
    builder.add_completeness_receipt(
        completeness("r", eth_chain(), providers=("prov",))
    )
    snap = builder.snapshot("snap-1")

    store = InMemoryGraphSnapshotStore()
    key = store.put(snap)
    assert key == "snap-1"
    loaded = store.get("snap-1")
    assert loaded.identity.digest == snap.identity.digest
    assert loaded.graph_digest == snap.graph.identity.digest
    by_digest = store.get_by_digest(snap.graph_digest)
    assert by_digest.snapshot_id == "snap-1"
    assert store.contains("snap-1")
    assert store.list_ids() == ("snap-1",)
    assert store.completeness_index()["snap-1"] == CompletenessStatus.COMPLETE.value

    with pytest.raises(SnapshotStoreError, match="immutable"):
        store.put(snap)

    with pytest.raises(SnapshotStoreError, match="not found"):
        store.get("missing")


def test_builder_sealed_after_build() -> None:
    builder = CryptoFlowGraphBuilder("seal")
    builder.add_observed_address("a", chain=eth_chain(), address="0xa")
    builder.build()
    with pytest.raises(CryptoFlowValidationError, match="sealed"):
        builder.add_observed_address("b", chain=eth_chain(), address="0xb")


def test_build_graph_from_records_and_package_exports() -> None:
    nodes = [
        FlowNode(
            node_id="n1",
            kind=NodeKind.ADDRESS,
            plane=GraphPlane.OBSERVED_ADDRESS,
            chain=eth_chain(),
            ledger_model=LedgerModel.ACCOUNT,
            address_ref="0x1",
        ),
        FlowNode(
            node_id="n2",
            kind=NodeKind.ADDRESS,
            plane=GraphPlane.OBSERVED_ADDRESS,
            chain=eth_chain(),
            ledger_model=LedgerModel.ACCOUNT,
            address_ref="0x2",
        ),
    ]
    edges = [
        FlowEdge(
            edge_id="e1",
            kind=EdgeKind.TRANSFER,
            plane=GraphPlane.OBSERVED_ADDRESS,
            source_node_id="n1",
            target_node_id="n2",
            chain=eth_chain(),
            ledger_model=LedgerModel.ACCOUNT,
            asset=eth_asset(),
            amount=ExactAmount.from_int(3, decimals=18),
            direction=FlowDirection.OUT,
            finality=FinalityStatus.CONFIRMED,
            source="t",
            derivation=DerivationMethod.ACCOUNT_TRANSFER,
        )
    ]
    graph = build_graph_from_records("from-records", nodes, edges)
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    # Frozen
    with pytest.raises(dataclasses.FrozenInstanceError):
        graph.nodes[0].address_ref = "mutated"  # type: ignore[misc]


def test_unknown_fields_fail_closed() -> None:
    with pytest.raises(CryptoFlowValidationError, match="unknown"):
        FlowNode.from_dict(
            {
                "node_id": "n",
                "kind": "address",
                "plane": "observed_address",
                "extra_field": True,
            }
        )


def test_utxo_helper_rejects_account_chain() -> None:
    builder = CryptoFlowGraphBuilder("bad-utxo")
    builder.add_observed_address("a", chain=eth_chain(), address="0xa")
    builder.add_observed_address("b", chain=eth_chain(), address="0xb")
    with pytest.raises(CryptoFlowValidationError, match="chain-correct"):
        builder.add_utxo_spend(
            "bad",
            source_node_id="a",
            target_node_id="b",
            chain=eth_chain(),
            asset=eth_asset(),
            amount=ExactAmount.from_int(1),
            coordinate=LedgerCoordinate(sequence=1),
        )


def test_account_helper_rejects_utxo_chain() -> None:
    builder = CryptoFlowGraphBuilder("bad-acct")
    builder.add_observed_address("a", chain=btc_chain(), address="bc1qa")
    builder.add_observed_address("b", chain=btc_chain(), address="bc1qb")
    with pytest.raises(CryptoFlowValidationError, match="chain-correct"):
        builder.add_account_transfer(
            "bad",
            source_node_id="a",
            target_node_id="b",
            chain=btc_chain(),
            asset=btc_asset(),
            amount=ExactAmount.from_int(1, decimals=8),
            coordinate=LedgerCoordinate(sequence=1),
        )


def test_snapshot_from_dict_round_trip() -> None:
    builder = CryptoFlowGraphBuilder("rt")
    builder.add_observed_address("a", chain=eth_chain(), address="0xa")
    builder.add_observed_address("b", chain=eth_chain(), address="0xb")
    builder.add_account_transfer(
        "x",
        source_node_id="a",
        target_node_id="b",
        chain=eth_chain(),
        asset=eth_asset(),
        amount=ExactAmount.from_int(7, decimals=18),
        coordinate=LedgerCoordinate(sequence=7, hash="0x7"),
        provider_ids=("p",),
    )
    builder.add_completeness_receipt(
        completeness("r", eth_chain(), providers=("p", "q"))
    )
    snap = builder.snapshot("snap-rt")
    restored = GraphSnapshot.from_dict(snap.to_dict())
    assert restored.graph_digest == snap.graph_digest
    assert restored.completeness is CompletenessStatus.COMPLETE
    assert set(restored.covered_providers) >= {"p", "q"}
