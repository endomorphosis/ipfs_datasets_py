"""Deterministic ingestion builder for multi-chain monetary-flow graphs.

The builder accumulates frozen nodes and edges, enforces plane separation and
chain-correct ledger models at construction time, and emits immutable
:class:`CryptoFlowGraph` / :class:`GraphSnapshot` records.  Reorgs and
retractions replace prior edges with superseded/retracted copies rather than
mutating in place.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from ipfs_datasets_py.logic.crypto_ir.model import (
    AssetIdentity,
    ChainIdentity,
    CompletenessReceipt,
    CompletenessStatus,
    ExactAmount,
    FinalityStatus,
    LedgerCoordinate,
    RetractionStatus,
)

from .model import (
    AmbiguityKind,
    CryptoFlowGraph,
    CryptoFlowValidationError,
    DerivationMethod,
    EdgeKind,
    FlowDirection,
    FlowEdge,
    FlowNode,
    GraphPlane,
    GraphSnapshot,
    LedgerModel,
    NodeKind,
    assert_ledger_model_chain_correct,
    default_ledger_model,
    merge_provider_ids,
)


class CryptoFlowGraphBuilder:
    """Deterministic multi-chain flow graph builder.

    Ingestion is order-independent for content identity (set-like nodes/edges).
    Duplicate ``node_id`` / ``edge_id`` values fail closed unless
    ``replace_existing`` is set for explicit supersession.
    """

    def __init__(self, graph_id: str = "crypto-flow-graph") -> None:
        if not isinstance(graph_id, str) or not graph_id.strip():
            raise CryptoFlowValidationError("graph_id must be a non-empty string")
        self._graph_id = graph_id.strip()
        self._nodes: dict[str, FlowNode] = {}
        self._edges: dict[str, FlowEdge] = {}
        self._receipts: dict[str, CompletenessReceipt] = {}
        self._provider_ids: set[str] = set()
        self._asset_ids: set[str] = set()
        self._chain_ids: set[str] = set()
        self._attributes: dict[str, Any] = {}
        self._sealed = False

    def _assert_open(self) -> None:
        if self._sealed:
            raise CryptoFlowValidationError("builder is sealed after build()")

    def _track_chain(self, chain: ChainIdentity | None) -> None:
        if chain is None:
            return
        key = f"{chain.chain_namespace}:{chain.network}:{chain.chain_id or '-'}"
        self._chain_ids.add(key)

    def _track_asset(self, asset: AssetIdentity | None) -> None:
        if asset is None:
            return
        key = (
            f"{asset.chain.chain_namespace}:{asset.asset_namespace}:"
            f"{asset.asset_reference}"
        )
        self._asset_ids.add(key)

    def _track_providers(self, provider_ids: Sequence[str]) -> None:
        for pid in provider_ids:
            self._provider_ids.add(pid)

    def add_node(
        self, node: FlowNode, *, replace_existing: bool = False
    ) -> "CryptoFlowGraphBuilder":
        """Add or replace a flow node."""
        self._assert_open()
        if not isinstance(node, FlowNode):
            raise CryptoFlowValidationError("node must be a FlowNode")
        if node.node_id in self._nodes and not replace_existing:
            raise CryptoFlowValidationError(
                f"duplicate node_id without replace_existing: {node.node_id}"
            )
        self._nodes[node.node_id] = node
        self._track_chain(node.chain)
        self._track_asset(node.asset)
        self._track_providers(node.provider_ids)
        return self

    def add_edge(
        self, edge: FlowEdge, *, replace_existing: bool = False
    ) -> "CryptoFlowGraphBuilder":
        """Add or replace a flow edge; endpoints must already exist."""
        self._assert_open()
        if not isinstance(edge, FlowEdge):
            raise CryptoFlowValidationError("edge must be a FlowEdge")
        if edge.edge_id in self._edges and not replace_existing:
            raise CryptoFlowValidationError(
                f"duplicate edge_id without replace_existing: {edge.edge_id}"
            )
        if edge.source_node_id not in self._nodes:
            raise CryptoFlowValidationError(
                f"edge source node missing: {edge.source_node_id}"
            )
        if edge.target_node_id not in self._nodes:
            raise CryptoFlowValidationError(
                f"edge target node missing: {edge.target_node_id}"
            )
        src = self._nodes[edge.source_node_id]
        tgt = self._nodes[edge.target_node_id]
        if edge.plane is not src.plane or edge.plane is not tgt.plane:
            raise CryptoFlowValidationError("edge must not cross graph planes")
        self._edges[edge.edge_id] = edge
        self._track_chain(edge.chain)
        self._track_asset(edge.asset)
        self._track_providers(edge.provider_ids)
        return self

    def add_completeness_receipt(
        self, receipt: CompletenessReceipt
    ) -> "CryptoFlowGraphBuilder":
        """Attach a CompletenessReceipt for provider/range/asset coverage."""
        self._assert_open()
        if not isinstance(receipt, CompletenessReceipt):
            raise CryptoFlowValidationError(
                "receipt must be a CompletenessReceipt"
            )
        self._receipts[receipt.receipt_id] = receipt
        self._track_chain(receipt.chain)
        self._track_providers(receipt.provider_ids)
        return self

    def set_attribute(self, key: str, value: Any) -> "CryptoFlowGraphBuilder":
        self._assert_open()
        if not isinstance(key, str) or not key.strip():
            raise CryptoFlowValidationError("attribute key must be a non-empty string")
        self._attributes[key.strip()] = value
        return self

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    def add_observed_address(
        self,
        node_id: str,
        *,
        chain: ChainIdentity,
        address: str,
        kind: NodeKind = NodeKind.ADDRESS,
        ledger_model: LedgerModel | None = None,
        source: str = "observation",
        finality: FinalityStatus = FinalityStatus.FINALIZED,
        provider_ids: Sequence[str] = (),
        attributes: Mapping[str, Any] | None = None,
    ) -> FlowNode:
        """Create and register an observed-address plane node."""
        model = ledger_model if ledger_model is not None else default_ledger_model(chain)
        assert_ledger_model_chain_correct(chain, model)
        if kind is NodeKind.ENTITY:
            raise CryptoFlowValidationError(
                "ENTITY nodes belong on the asserted_entity plane"
            )
        node = FlowNode(
            node_id=node_id,
            kind=kind,
            plane=GraphPlane.OBSERVED_ADDRESS,
            chain=chain,
            ledger_model=model,
            address_ref=address,
            source=source,
            finality=finality,
            derivation=DerivationMethod.DIRECT_OBSERVATION,
            provider_ids=tuple(provider_ids),
            attributes=dict(attributes or {}),
        )
        self.add_node(node)
        return node

    def add_asserted_entity(
        self,
        node_id: str,
        *,
        entity_ref: str,
        kind: NodeKind = NodeKind.ENTITY,
        source: str = "assertion",
        confidence: str = "0.5",
        derivation: DerivationMethod = DerivationMethod.HEURISTIC_CLUSTER,
        ambiguity: AmbiguityKind = AmbiguityKind.MULTI_PARTY,
        provider_ids: Sequence[str] = (),
        attributes: Mapping[str, Any] | None = None,
    ) -> FlowNode:
        """Create and register an asserted-entity plane node."""
        if kind is NodeKind.ADDRESS:
            raise CryptoFlowValidationError(
                "raw ADDRESS nodes belong on the observed_address plane"
            )
        node = FlowNode(
            node_id=node_id,
            kind=kind,
            plane=GraphPlane.ASSERTED_ENTITY,
            entity_ref=entity_ref,
            source=source,
            confidence=confidence,
            derivation=derivation,
            ambiguity=ambiguity,
            provider_ids=tuple(provider_ids),
            attributes=dict(attributes or {}),
        )
        self.add_node(node)
        return node

    def add_utxo_spend(
        self,
        edge_id: str,
        *,
        source_node_id: str,
        target_node_id: str,
        chain: ChainIdentity,
        asset: AssetIdentity,
        amount: ExactAmount,
        coordinate: LedgerCoordinate,
        source: str = "utxo-observation",
        finality: FinalityStatus = FinalityStatus.FINALIZED,
        provider_ids: Sequence[str] = (),
        timestamp: str = "",
    ) -> FlowEdge:
        """Add a chain-correct UTXO spend edge on the observed plane."""
        assert_ledger_model_chain_correct(chain, LedgerModel.UTXO)
        edge = FlowEdge(
            edge_id=edge_id,
            kind=EdgeKind.SPENDS,
            plane=GraphPlane.OBSERVED_ADDRESS,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            chain=chain,
            ledger_model=LedgerModel.UTXO,
            coordinate=coordinate,
            asset=asset,
            amount=amount,
            direction=FlowDirection.OUT,
            finality=finality,
            source=source,
            derivation=DerivationMethod.UTXO_SPEND,
            provider_ids=tuple(provider_ids),
            timestamp=timestamp,
        )
        self.add_edge(edge)
        return edge

    def add_account_transfer(
        self,
        edge_id: str,
        *,
        source_node_id: str,
        target_node_id: str,
        chain: ChainIdentity,
        asset: AssetIdentity,
        amount: ExactAmount,
        coordinate: LedgerCoordinate,
        source: str = "account-observation",
        finality: FinalityStatus = FinalityStatus.FINALIZED,
        provider_ids: Sequence[str] = (),
        timestamp: str = "",
    ) -> FlowEdge:
        """Add a chain-correct account-model transfer edge."""
        assert_ledger_model_chain_correct(chain, LedgerModel.ACCOUNT)
        edge = FlowEdge(
            edge_id=edge_id,
            kind=EdgeKind.TRANSFER,
            plane=GraphPlane.OBSERVED_ADDRESS,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            chain=chain,
            ledger_model=LedgerModel.ACCOUNT,
            coordinate=coordinate,
            asset=asset,
            amount=amount,
            direction=FlowDirection.OUT,
            finality=finality,
            source=source,
            derivation=DerivationMethod.ACCOUNT_TRANSFER,
            provider_ids=tuple(provider_ids),
            timestamp=timestamp,
        )
        self.add_edge(edge)
        return edge

    def add_ambiguous_service_edge(
        self,
        edge_id: str,
        *,
        kind: EdgeKind,
        source_node_id: str,
        target_node_id: str,
        ambiguity: AmbiguityKind,
        chain: ChainIdentity | None = None,
        asset: AssetIdentity | None = None,
        amount: ExactAmount | None = None,
        coordinate: LedgerCoordinate | None = None,
        derivation: DerivationMethod = DerivationMethod.HEURISTIC_CLUSTER,
        confidence: str = "0.4",
        source: str = "service-observation",
        provider_ids: Sequence[str] = (),
        timestamp: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> FlowEdge:
        """Add a pool/mixer/exchange/bridge/CoinJoin/peel edge with ambiguity.

        Never collapses multi-party service ambiguity into a single-customer
        certain transfer.
        """
        if ambiguity is AmbiguityKind.NONE:
            raise CryptoFlowValidationError(
                "ambiguous service edges must declare a non-NONE AmbiguityKind"
            )
        ledger = (
            default_ledger_model(chain)
            if chain is not None
            else LedgerModel.UNKNOWN
        )
        # Heuristic / GraphRAG derivations cannot claim unit confidence; direct
        # observation of a service hop may, while still preserving ambiguity
        # about multi-party customer linkage inside the service.
        heuristic = derivation in (
            DerivationMethod.HEURISTIC_CLUSTER,
            DerivationMethod.HEURISTIC_PEEL,
            DerivationMethod.HEURISTIC_CHANGE,
            DerivationMethod.HEURISTIC_COINJOIN,
            DerivationMethod.HEURISTIC_SHARED_INFRA,
            DerivationMethod.GRAPHRAG_CANDIDATE,
        )
        conf = confidence
        if heuristic and conf == "1":
            conf = "0.5"
        edge = FlowEdge(
            edge_id=edge_id,
            kind=kind,
            plane=GraphPlane.OBSERVED_ADDRESS,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            chain=chain,
            ledger_model=ledger,
            coordinate=coordinate,
            asset=asset,
            amount=amount,
            direction=FlowDirection.OUT,
            finality=FinalityStatus.CONFIRMED,
            source=source,
            confidence=conf,
            derivation=derivation,
            ambiguity=ambiguity,
            provider_ids=tuple(provider_ids),
            timestamp=timestamp,
            attributes=dict(attributes or {}),
        )
        self.add_edge(edge)
        return edge

    def add_bridge_pair(
        self,
        *,
        lock_edge_id: str,
        mint_edge_id: str,
        source_node_id: str,
        bridge_node_id: str,
        dest_node_id: str,
        source_chain: ChainIdentity,
        dest_chain: ChainIdentity,
        source_asset: AssetIdentity,
        dest_asset: AssetIdentity,
        amount: ExactAmount,
        source_coordinate: LedgerCoordinate,
        dest_coordinate: LedgerCoordinate,
        provider_ids: Sequence[str] = (),
    ) -> tuple[FlowEdge, FlowEdge]:
        """Record a cross-chain bridge lock+mint with bridge ambiguity."""
        lock = self.add_ambiguous_service_edge(
            lock_edge_id,
            kind=EdgeKind.BRIDGE_LOCK,
            source_node_id=source_node_id,
            target_node_id=bridge_node_id,
            ambiguity=AmbiguityKind.BRIDGE,
            chain=source_chain,
            asset=source_asset,
            amount=amount,
            coordinate=source_coordinate,
            derivation=DerivationMethod.BRIDGE_MESSAGE,
            confidence="0.8",
            source="bridge-lock",
            provider_ids=provider_ids,
        )
        mint = self.add_ambiguous_service_edge(
            mint_edge_id,
            kind=EdgeKind.BRIDGE_MINT,
            source_node_id=bridge_node_id,
            target_node_id=dest_node_id,
            ambiguity=AmbiguityKind.BRIDGE,
            chain=dest_chain,
            asset=dest_asset,
            amount=amount,
            coordinate=dest_coordinate,
            derivation=DerivationMethod.BRIDGE_MESSAGE,
            confidence="0.8",
            source="bridge-mint",
            provider_ids=provider_ids,
        )
        return lock, mint

    def add_coinjoin(
        self,
        edge_id: str,
        *,
        source_node_id: str,
        target_node_id: str,
        chain: ChainIdentity,
        asset: AssetIdentity,
        amount: ExactAmount,
        coordinate: LedgerCoordinate,
        provider_ids: Sequence[str] = (),
    ) -> FlowEdge:
        """Preserve CoinJoin multi-party ambiguity."""
        return self.add_ambiguous_service_edge(
            edge_id,
            kind=EdgeKind.COINJOIN,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            ambiguity=AmbiguityKind.COINJOIN,
            chain=chain,
            asset=asset,
            amount=amount,
            coordinate=coordinate,
            derivation=DerivationMethod.HEURISTIC_COINJOIN,
            confidence="0.3",
            source="coinjoin-heuristic",
            provider_ids=provider_ids,
        )

    def add_peel_change(
        self,
        peel_edge_id: str,
        change_edge_id: str,
        *,
        source_node_id: str,
        peel_target_id: str,
        change_target_id: str,
        chain: ChainIdentity,
        asset: AssetIdentity,
        peel_amount: ExactAmount,
        change_amount: ExactAmount,
        coordinate: LedgerCoordinate,
        provider_ids: Sequence[str] = (),
    ) -> tuple[FlowEdge, FlowEdge]:
        """Preserve peel-chain / change-output ambiguity."""
        peel = self.add_ambiguous_service_edge(
            peel_edge_id,
            kind=EdgeKind.PEEL,
            source_node_id=source_node_id,
            target_node_id=peel_target_id,
            ambiguity=AmbiguityKind.PEEL_CHANGE,
            chain=chain,
            asset=asset,
            amount=peel_amount,
            coordinate=coordinate,
            derivation=DerivationMethod.HEURISTIC_PEEL,
            confidence="0.55",
            source="peel-heuristic",
            provider_ids=provider_ids,
        )
        change = self.add_ambiguous_service_edge(
            change_edge_id,
            kind=EdgeKind.CHANGE,
            source_node_id=source_node_id,
            target_node_id=change_target_id,
            ambiguity=AmbiguityKind.PEEL_CHANGE,
            chain=chain,
            asset=asset,
            amount=change_amount,
            coordinate=coordinate,
            derivation=DerivationMethod.HEURISTIC_CHANGE,
            confidence="0.55",
            source="change-heuristic",
            provider_ids=provider_ids,
        )
        return peel, change

    def apply_reorg(
        self,
        edge_id: str,
        *,
        replacement: FlowEdge | None = None,
    ) -> FlowEdge:
        """Mark an edge as reorged and optionally install a replacement.

        Prior edge becomes ``finality=REORGED`` / ``retraction=SUPERSEDED``.
        """
        self._assert_open()
        if edge_id not in self._edges:
            raise CryptoFlowValidationError(f"unknown edge_id for reorg: {edge_id}")
        prior = self._edges[edge_id]
        reorged = replace(
            prior,
            finality=FinalityStatus.REORGED,
            retraction=RetractionStatus.SUPERSEDED,
            ambiguity=AmbiguityKind.REORG
            if prior.ambiguity is AmbiguityKind.NONE
            else prior.ambiguity,
        )
        self._edges[edge_id] = reorged
        if replacement is not None:
            if replacement.edge_id == edge_id:
                raise CryptoFlowValidationError(
                    "replacement edge must use a new edge_id"
                )
            self.add_edge(replacement)
        return reorged

    def retract_edge(self, edge_id: str) -> FlowEdge:
        """Mark an edge as retracted."""
        self._assert_open()
        if edge_id not in self._edges:
            raise CryptoFlowValidationError(
                f"unknown edge_id for retraction: {edge_id}"
            )
        prior = self._edges[edge_id]
        retracted = replace(
            prior,
            finality=FinalityStatus.RETRACTED,
            retraction=RetractionStatus.RETRACTED,
        )
        self._edges[edge_id] = retracted
        return retracted

    def build(self, *, seal: bool = True) -> CryptoFlowGraph:
        """Materialize an immutable CryptoFlowGraph."""
        self._assert_open()
        providers = merge_provider_ids(self._provider_ids)
        graph = CryptoFlowGraph(
            graph_id=self._graph_id,
            nodes=tuple(self._nodes.values()),
            edges=tuple(self._edges.values()),
            completeness_receipts=tuple(self._receipts.values()),
            provider_ids=providers,
            asset_ids=tuple(sorted(self._asset_ids)),
            chain_ids=tuple(sorted(self._chain_ids)),
            attributes=dict(self._attributes),
        )
        if seal:
            self._sealed = True
        return graph

    def snapshot(
        self,
        snapshot_id: str,
        *,
        completeness: CompletenessStatus | None = None,
        covered_ranges: Sequence[LedgerCoordinate] = (),
        missing_ranges: Sequence[LedgerCoordinate] = (),
        created_at: str = "",
        seal: bool = True,
    ) -> GraphSnapshot:
        """Build the graph and wrap it in a deterministic GraphSnapshot."""
        graph = self.build(seal=seal)
        receipts = graph.completeness_receipts
        if completeness is None:
            if not receipts:
                status = CompletenessStatus.UNKNOWN
            elif any(r.completeness is CompletenessStatus.PARTIAL for r in receipts):
                status = CompletenessStatus.PARTIAL
            elif all(r.completeness is CompletenessStatus.COMPLETE for r in receipts):
                status = CompletenessStatus.COMPLETE
            else:
                status = CompletenessStatus.UNKNOWN
        else:
            status = completeness
        covered_providers = merge_provider_ids(
            graph.provider_ids,
            *(r.provider_ids for r in receipts),
        )
        return GraphSnapshot(
            snapshot_id=snapshot_id,
            graph=graph,
            completeness=status,
            completeness_receipts=receipts,
            covered_providers=covered_providers,
            covered_assets=graph.asset_ids,
            covered_chains=graph.chain_ids,
            covered_ranges=tuple(covered_ranges),
            missing_ranges=tuple(missing_ranges),
            created_at=created_at,
        )


def build_graph_from_records(
    graph_id: str,
    nodes: Sequence[FlowNode | Mapping[str, Any]],
    edges: Sequence[FlowEdge | Mapping[str, Any]],
    *,
    receipts: Sequence[CompletenessReceipt | Mapping[str, Any]] = (),
) -> CryptoFlowGraph:
    """Convenience: construct a graph from pre-built or mapping records."""
    builder = CryptoFlowGraphBuilder(graph_id)
    for node in nodes:
        if isinstance(node, FlowNode):
            builder.add_node(node)
        else:
            builder.add_node(FlowNode.from_dict(node))
    for edge in edges:
        if isinstance(edge, FlowEdge):
            builder.add_edge(edge)
        else:
            builder.add_edge(FlowEdge.from_dict(edge))
    for receipt in receipts:
        if isinstance(receipt, CompletenessReceipt):
            builder.add_completeness_receipt(receipt)
        else:
            builder.add_completeness_receipt(CompletenessReceipt.from_dict(receipt))
    return builder.build()


__all__ = [
    "CryptoFlowGraphBuilder",
    "build_graph_from_records",
]
