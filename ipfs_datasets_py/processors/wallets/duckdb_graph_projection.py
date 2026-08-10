"""Incrementally project wallet ledger records into crypto-flow graph revisions (DQK-038).

Derives **observed-address** and **asserted-entity** crypto-flow nodes and edges
from normalized wallet transactions, transfers, and UTXOs while:

* remaining **idempotent by ledger revision and graph revision**
* **retracting** reorged history rather than silently mutating prior projections
* keeping asserted and observed planes strictly separated

Published snapshots are durable via
:class:`~ipfs_datasets_py.knowledge_graphs.crypto_flows.duckdb_store.DuckDBGraphSnapshotStore`
(DQK-019).  Each successful projection yields an immutable snapshot whose
``snapshot_id`` is a deterministic function of
``(graph_id, ledger_revision, graph_revision)`` so crash-replay of the same
revision pair is a no-op that returns the prior receipt.

Importing this module performs no network I/O.  Opening DuckDB is deferred to
projector construction.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Union

from ipfs_datasets_py.knowledge_graphs.crypto_flows.builder import (
    CryptoFlowGraphBuilder,
)
from ipfs_datasets_py.knowledge_graphs.crypto_flows.duckdb_store import (
    DuckDBGraphSnapshotStore,
)
from ipfs_datasets_py.knowledge_graphs.crypto_flows.model import (
    AmbiguityKind,
    CryptoFlowGraph,
    DerivationMethod,
    EdgeKind,
    FinalityStatus,
    FlowDirection,
    FlowEdge,
    FlowNode,
    GraphPlane,
    GraphSnapshot,
    LedgerCoordinate,
    LedgerModel,
    NodeKind,
    RetractionStatus,
    default_ledger_model,
)
from ipfs_datasets_py.knowledge_graphs.crypto_flows.store import SnapshotStoreError
from ipfs_datasets_py.logic.crypto_ir.model import (
    AssetIdentity,
    ChainIdentity,
    CompletenessReceipt,
    CompletenessStatus,
    ExactAmount as CryptoExactAmount,
    ValidityWindow,
)

from .canonical import deterministic_id, format_datetime
from .models import (
    AccountKind,
    AccountRef,
    AssetRef,
    ChainRef,
    ExactAmount,
    Finality,
    LedgerRecord,
    TransactionRecord,
    TransferKind,
    TransferRecord,
    UTXORecord,
)

# ---------------------------------------------------------------------------
# Interface pins
# ---------------------------------------------------------------------------

DUCKDB_WALLET_GRAPH_PROJECTION_INTERFACE: Final[str] = (
    "WalletCryptoFlowProjector@1"
)
DUCKDB_WALLET_GRAPH_PROJECTION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/processors-wallets-duckdb-graph-projection@1"
)
SCHEMA_VERSION: Final[int] = 1

CRYPTO_FLOW_EXTENSION_NS: Final[str] = "crypto_flow"

_HEX64: Final[re.Pattern[str]] = re.compile(r"^[0-9a-fA-F]{64}$")
_TAGGED_DIGEST: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+:[0-9a-f]+$")

PathLike = Union[str, Path]

__all__ = [
    "CRYPTO_FLOW_EXTENSION_NS",
    "DUCKDB_WALLET_GRAPH_PROJECTION_INTERFACE",
    "DUCKDB_WALLET_GRAPH_PROJECTION_SCHEMA",
    "SCHEMA_VERSION",
    "EntityAssertion",
    "PlaneConfusionError",
    "ProjectionReceipt",
    "WalletCryptoFlowProjector",
    "WalletGraphProjectionError",
    "derive_edge_id",
    "derive_node_id",
    "map_wallet_finality",
    "normalize_genesis_digest",
    "open_wallet_graph_projector",
    "projection_snapshot_id",
    "to_asset_identity",
    "to_chain_identity",
    "to_crypto_amount",
    "to_ledger_coordinate",
]


# ---------------------------------------------------------------------------
# Errors and value objects
# ---------------------------------------------------------------------------


class WalletGraphProjectionError(ValueError):
    """Raised when a wallet → crypto-flow projection fails closed."""


class PlaneConfusionError(WalletGraphProjectionError):
    """Raised when observed and asserted planes would be mixed."""


class ProjectionStatus(StrEnum):
    """Whether a project() call wrote a new snapshot or replayed one."""

    APPLIED = "applied"
    IDEMPOTENT_REPLAY = "idempotent_replay"


@dataclass(frozen=True, slots=True)
class EntityAssertion:
    """An asserted-entity plane claim that must never contaminate observed nodes.

    Ownership / control evidence lives only on the asserted plane.  Observed
    address node ids may be referenced as *attributes* (string refs) but are
    never written onto asserted nodes as ``address_ref`` authority, and
    asserted ``entity_ref`` values are never written onto observed nodes.
    """

    entity_ref: str
    node_id: str = ""
    kind: NodeKind = NodeKind.ENTITY
    confidence: str = "0.5"
    ambiguity: AmbiguityKind = AmbiguityKind.MULTI_PARTY
    derivation: DerivationMethod = DerivationMethod.HEURISTIC_CLUSTER
    source: str = "assertion"
    provider_ids: tuple[str, ...] = ()
    # Optional peer entity for an asserted-plane OWNS / CONTROLS edge.
    related_entity_ref: str = ""
    relation: EdgeKind = EdgeKind.OWNS
    # Optional observed address id recorded only as attribute evidence.
    observed_address_node_id: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.entity_ref, str) or not self.entity_ref.strip():
            raise WalletGraphProjectionError("entity_ref must be a non-empty string")
        object.__setattr__(self, "entity_ref", self.entity_ref.strip())
        if self.kind is NodeKind.ADDRESS:
            raise PlaneConfusionError(
                "asserted-entity claims must not use NodeKind.ADDRESS"
            )
        nid = self.node_id.strip() if isinstance(self.node_id, str) else ""
        if not nid:
            nid = derive_node_id(
                "asserted_entity",
                {"entity_ref": self.entity_ref, "kind": self.kind.value},
            )
        object.__setattr__(self, "node_id", nid)
        if not isinstance(self.kind, NodeKind):
            object.__setattr__(self, "kind", NodeKind(self.kind))
        if not isinstance(self.ambiguity, AmbiguityKind):
            object.__setattr__(self, "ambiguity", AmbiguityKind(self.ambiguity))
        if not isinstance(self.derivation, DerivationMethod):
            object.__setattr__(
                self, "derivation", DerivationMethod(self.derivation)
            )
        if not isinstance(self.relation, EdgeKind):
            object.__setattr__(self, "relation", EdgeKind(self.relation))
        object.__setattr__(
            self,
            "provider_ids",
            tuple(str(p) for p in self.provider_ids if str(p).strip()),
        )
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(dict(self.attributes or {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity": self.ambiguity.value,
            "attributes": dict(self.attributes),
            "confidence": self.confidence,
            "derivation": self.derivation.value,
            "entity_ref": self.entity_ref,
            "kind": self.kind.value,
            "node_id": self.node_id,
            "observed_address_node_id": self.observed_address_node_id,
            "provider_ids": list(self.provider_ids),
            "related_entity_ref": self.related_entity_ref,
            "relation": self.relation.value,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ProjectionReceipt:
    """Outcome of a single project() call (applied or idempotent replay)."""

    graph_id: str
    ledger_revision: str
    graph_revision: str
    snapshot_id: str
    identity_digest: str
    graph_digest: str
    node_count: int
    edge_count: int
    observed_node_count: int
    asserted_node_count: int
    observed_edge_count: int
    asserted_edge_count: int
    reorged_edge_ids: tuple[str, ...]
    retracted_edge_ids: tuple[str, ...]
    status: ProjectionStatus
    schema_version: str = DUCKDB_WALLET_GRAPH_PROJECTION_SCHEMA

    @property
    def applied(self) -> bool:
        return self.status is ProjectionStatus.APPLIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "asserted_edge_count": self.asserted_edge_count,
            "asserted_node_count": self.asserted_node_count,
            "edge_count": self.edge_count,
            "graph_digest": self.graph_digest,
            "graph_id": self.graph_id,
            "graph_revision": self.graph_revision,
            "identity_digest": self.identity_digest,
            "ledger_revision": self.ledger_revision,
            "node_count": self.node_count,
            "observed_edge_count": self.observed_edge_count,
            "observed_node_count": self.observed_node_count,
            "reorged_edge_ids": list(self.reorged_edge_ids),
            "retracted_edge_ids": list(self.retracted_edge_ids),
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "status": self.status.value,
        }


# ---------------------------------------------------------------------------
# Identity / mapping helpers
# ---------------------------------------------------------------------------


def normalize_genesis_digest(value: str) -> str:
    """Normalize a wallet genesis hash into a crypto-ir tagged digest.

    Wallet :class:`ChainRef` values often carry ``0x``-prefixed block hashes.
    Crypto-IR requires a tagged digest (``algorithm:hex``) or bare sha256 hex.
    """
    if not isinstance(value, str) or not value.strip():
        raise WalletGraphProjectionError("genesis digest must be a non-empty string")
    text = value.strip()
    if _TAGGED_DIGEST.fullmatch(text):
        return text
    if text.startswith(("0x", "0X")):
        body = text[2:]
        if _HEX64.fullmatch(body):
            return f"sha256:{body.lower()}"
        # Non-64-hex genesis anchors still need a stable digest form.
        return f"sha256:{sha256(text.encode('utf-8')).hexdigest()}"
    if _HEX64.fullmatch(text):
        return f"sha256:{text.lower()}"
    # Arbitrary genesis strings → content digest of the literal.
    return f"sha256:{sha256(text.encode('utf-8')).hexdigest()}"


def to_chain_identity(chain: ChainRef) -> ChainIdentity:
    """Map a wallet :class:`ChainRef` to a crypto-ir :class:`ChainIdentity`."""
    if not isinstance(chain, ChainRef):
        raise WalletGraphProjectionError("chain must be a ChainRef")
    return ChainIdentity(
        chain_namespace=chain.namespace,
        network=chain.network,
        genesis_digest=normalize_genesis_digest(chain.genesis_hash),
        chain_id=chain.chain_id,
        display_name=chain.network,
    )


def to_asset_identity(asset: AssetRef) -> AssetIdentity:
    """Map a wallet :class:`AssetRef` to a crypto-ir :class:`AssetIdentity`."""
    if not isinstance(asset, AssetRef):
        raise WalletGraphProjectionError("asset must be an AssetRef")
    return AssetIdentity(
        chain=to_chain_identity(asset.chain),
        asset_namespace=asset.asset_namespace,
        asset_reference=asset.asset_reference,
        decimals=asset.decimals,
        symbol=asset.symbol or "",
    )


def to_crypto_amount(amount: ExactAmount) -> CryptoExactAmount:
    """Map a wallet exact amount to the crypto-ir exact amount type."""
    if not isinstance(amount, ExactAmount):
        raise WalletGraphProjectionError("amount must be ExactAmount")
    return CryptoExactAmount(base_units=amount.base_units, decimals=amount.decimals)


def to_ledger_coordinate(
    record: LedgerRecord,
    *,
    transaction_hash: str | None = None,
    event_index: int | None = None,
) -> LedgerCoordinate:
    """Build a crypto-flow ledger coordinate from a wallet record envelope."""
    position = record.ledger_position
    tx_index = position.transaction_index
    evt = event_index if event_index is not None else position.event_index
    hash_value = position.hash or transaction_hash or ""
    return LedgerCoordinate(
        sequence=position.sequence,
        hash=hash_value or "",
        transaction_index=tx_index,
        event_index=evt,
    )


def map_wallet_finality(finality: Finality | str) -> FinalityStatus:
    """Map wallet :class:`Finality` to crypto-flow :class:`FinalityStatus`.

    Correction states (orphaned / reverted) become ``REORGED`` so reorg lineage
    is visible on the flow graph.  ``FAILED`` maps to ``RETRACTED``.
    """
    if isinstance(finality, Finality):
        value = finality
    else:
        try:
            value = Finality(str(finality))
        except ValueError as exc:
            raise WalletGraphProjectionError(
                f"unknown wallet finality: {finality!r}"
            ) from exc
    mapping: Mapping[Finality, FinalityStatus] = {
        Finality.UNKNOWN: FinalityStatus.UNKNOWN,
        Finality.OBSERVED: FinalityStatus.PROPOSED,
        Finality.PENDING: FinalityStatus.PROPOSED,
        Finality.CONFIRMED: FinalityStatus.CONFIRMED,
        Finality.SAFE: FinalityStatus.CONFIRMED,
        Finality.FINALIZED: FinalityStatus.FINALIZED,
        Finality.ORPHANED: FinalityStatus.REORGED,
        Finality.REVERTED: FinalityStatus.REORGED,
        Finality.FAILED: FinalityStatus.RETRACTED,
    }
    return mapping[value]


def derive_node_id(kind: str, identity: Mapping[str, Any]) -> str:
    """Deterministic flow-graph node id from semantic coordinates."""
    return deterministic_id(f"graph_node_{kind}", dict(identity))


def derive_edge_id(kind: str, identity: Mapping[str, Any]) -> str:
    """Deterministic flow-graph edge id from semantic coordinates."""
    return deterministic_id(f"graph_edge_{kind}", dict(identity))


def projection_snapshot_id(
    graph_id: str,
    ledger_revision: str,
    graph_revision: str,
) -> str:
    """Deterministic snapshot id for a (ledger, graph) revision pair."""
    if not graph_id or not str(graph_id).strip():
        raise WalletGraphProjectionError("graph_id must be a non-empty string")
    if not ledger_revision or not str(ledger_revision).strip():
        raise WalletGraphProjectionError("ledger_revision must be a non-empty string")
    if not graph_revision or not str(graph_revision).strip():
        raise WalletGraphProjectionError("graph_revision must be a non-empty string")
    return deterministic_id(
        "graph_projection",
        {
            "graph_id": str(graph_id).strip(),
            "graph_revision": str(graph_revision).strip(),
            "ledger_revision": str(ledger_revision).strip(),
        },
    )


def observed_address_node_id(account: AccountRef) -> str:
    """Stable observed-plane node id for an account/address."""
    return derive_node_id(
        "observed_address",
        {
            "account_id": account.account_id,
            "address": account.address,
            "chain": account.chain.identity_dict(),
            "kind": account.kind.value,
        },
    )


def transfer_edge_id(record: TransferRecord) -> str:
    """Stable edge id for a transfer record (bound to record_id)."""
    return derive_edge_id(
        "transfer",
        {
            "record_id": record.record_id,
            "transaction_hash": record.transaction_hash,
            "transfer_index": record.transfer_index,
        },
    )


def utxo_node_id(record: UTXORecord) -> str:
    return derive_node_id(
        "utxo",
        {
            "output_index": record.output_index,
            "record_id": record.record_id,
            "transaction_hash": record.transaction_hash,
        },
    )


def transaction_node_id(record: TransactionRecord) -> str:
    return derive_node_id(
        "transaction",
        {
            "record_id": record.record_id,
            "transaction_hash": record.transaction_hash,
        },
    )


def _system_node_id(role: str, chain: ChainRef) -> str:
    return derive_node_id(
        "system",
        {"chain": chain.identity_dict(), "role": role},
    )


def _account_node_kind(account: AccountRef) -> NodeKind:
    if account.kind is AccountKind.CONTRACT:
        return NodeKind.CONTRACT
    if account.kind is AccountKind.SCRIPT:
        return NodeKind.SCRIPT
    if account.kind is AccountKind.TOKEN_ACCOUNT:
        return NodeKind.ACCOUNT
    if account.kind is AccountKind.PROTOCOL_SUBJECT:
        return NodeKind.SERVICE
    return NodeKind.ADDRESS


def _transfer_edge_kind(record: TransferRecord) -> EdgeKind:
    mapping = {
        TransferKind.NATIVE: EdgeKind.TRANSFER,
        TransferKind.TOKEN: EdgeKind.TRANSFER,
        TransferKind.FEE: EdgeKind.TRANSFER,
        TransferKind.REWARD: EdgeKind.TRANSFER,
        TransferKind.MINT: EdgeKind.TRANSFER,
        TransferKind.BURN: EdgeKind.TRANSFER,
        TransferKind.UNKNOWN: EdgeKind.TRANSFER,
    }
    # Extension override (optional crypto_flow.edge_kind).
    ext = record.extensions.get(CRYPTO_FLOW_EXTENSION_NS)
    if ext is not None:
        raw = ext.data.get("edge_kind") if isinstance(ext.data, Mapping) else None
        if isinstance(raw, str) and raw.strip():
            try:
                return EdgeKind(raw.strip())
            except ValueError:
                pass
    return mapping.get(record.transfer_kind, EdgeKind.TRANSFER)


def _extension_ambiguity(record: LedgerRecord) -> AmbiguityKind:
    ext = record.extensions.get(CRYPTO_FLOW_EXTENSION_NS)
    if ext is None or not isinstance(ext.data, Mapping):
        return AmbiguityKind.NONE
    raw = ext.data.get("ambiguity")
    if not isinstance(raw, str) or not raw.strip():
        return AmbiguityKind.NONE
    try:
        return AmbiguityKind(raw.strip())
    except ValueError:
        return AmbiguityKind.UNKNOWN


def _extension_derivation(
    record: LedgerRecord, default: DerivationMethod
) -> DerivationMethod:
    ext = record.extensions.get(CRYPTO_FLOW_EXTENSION_NS)
    if ext is None or not isinstance(ext.data, Mapping):
        return default
    raw = ext.data.get("derivation")
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        return DerivationMethod(raw.strip())
    except ValueError:
        return default


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Pure derivation onto a builder
# ---------------------------------------------------------------------------


def _ensure_observed_address(
    builder: CryptoFlowGraphBuilder,
    account: AccountRef,
    *,
    finality: FinalityStatus,
    provider_ids: Sequence[str],
    source: str,
) -> str:
    node_id = observed_address_node_id(account)
    existing = builder._nodes.get(node_id)  # noqa: SLF001 — intentional internal reuse
    if existing is not None:
        if existing.plane is not GraphPlane.OBSERVED_ADDRESS:
            raise PlaneConfusionError(
                f"node {node_id} already exists on plane {existing.plane.value}"
            )
        if existing.entity_ref:
            raise PlaneConfusionError(
                "observed address node must not carry entity_ref authority"
            )
        return node_id
    chain = to_chain_identity(account.chain)
    model = default_ledger_model(chain)
    builder.add_node(
        FlowNode(
            node_id=node_id,
            kind=_account_node_kind(account),
            plane=GraphPlane.OBSERVED_ADDRESS,
            chain=chain,
            ledger_model=model,
            address_ref=account.address,
            entity_ref="",  # plane separation: never set on observed nodes
            finality=finality,
            source=source,
            derivation=DerivationMethod.DIRECT_OBSERVATION,
            provider_ids=tuple(provider_ids),
            attributes={
                "account_id": account.account_id,
                "account_kind": account.kind.value,
            },
        )
    )
    return node_id


def _ensure_system_node(
    builder: CryptoFlowGraphBuilder,
    role: str,
    chain: ChainRef,
    *,
    finality: FinalityStatus,
    provider_ids: Sequence[str],
) -> str:
    node_id = _system_node_id(role, chain)
    if node_id in builder._nodes:  # noqa: SLF001
        return node_id
    chain_id = to_chain_identity(chain)
    builder.add_node(
        FlowNode(
            node_id=node_id,
            kind=NodeKind.SERVICE,
            plane=GraphPlane.OBSERVED_ADDRESS,
            chain=chain_id,
            ledger_model=default_ledger_model(chain_id),
            address_ref="",
            entity_ref="",
            finality=finality,
            source=f"system:{role}",
            derivation=DerivationMethod.DIRECT_OBSERVATION,
            provider_ids=tuple(provider_ids),
            attributes={"system_role": role},
        )
    )
    return node_id


def _project_transfer(
    builder: CryptoFlowGraphBuilder, record: TransferRecord
) -> str:
    providers = (record.provenance.provider,)
    finality = map_wallet_finality(record.finality)
    # Orphaned / reverted transfers still land in the graph so reorg lineage is
    # retained; they are immediately marked reorged/superseded.
    chain = to_chain_identity(record.chain)
    asset = to_asset_identity(record.asset)
    amount = to_crypto_amount(record.amount)
    coordinate = to_ledger_coordinate(
        record,
        transaction_hash=record.transaction_hash,
        event_index=record.transfer_index,
    )
    ambiguity = _extension_ambiguity(record)
    derivation = _extension_derivation(
        record, DerivationMethod.ACCOUNT_TRANSFER
    )
    ledger_model = default_ledger_model(chain)
    if ledger_model is LedgerModel.UTXO:
        derivation = _extension_derivation(record, DerivationMethod.UTXO_SPEND)

    if record.source_account is not None:
        src = _ensure_observed_address(
            builder,
            record.source_account,
            finality=finality
            if finality not in (FinalityStatus.REORGED, FinalityStatus.RETRACTED)
            else FinalityStatus.CONFIRMED,
            provider_ids=providers,
            source=record.provenance.provider,
        )
    else:
        src = _ensure_system_node(
            builder,
            "mint",
            record.chain,
            finality=FinalityStatus.FINALIZED,
            provider_ids=providers,
        )

    if record.destination_account is not None:
        tgt = _ensure_observed_address(
            builder,
            record.destination_account,
            finality=finality
            if finality not in (FinalityStatus.REORGED, FinalityStatus.RETRACTED)
            else FinalityStatus.CONFIRMED,
            provider_ids=providers,
            source=record.provenance.provider,
        )
    else:
        tgt = _ensure_system_node(
            builder,
            "burn",
            record.chain,
            finality=FinalityStatus.FINALIZED,
            provider_ids=providers,
        )

    edge_id = transfer_edge_id(record)
    if edge_id in builder._edges:  # noqa: SLF001
        return edge_id

    edge_finality = finality
    retraction = RetractionStatus.NOT_RETRACTED
    if finality is FinalityStatus.REORGED:
        retraction = RetractionStatus.SUPERSEDED
        if ambiguity is AmbiguityKind.NONE:
            ambiguity = AmbiguityKind.REORG
    elif finality is FinalityStatus.RETRACTED:
        retraction = RetractionStatus.RETRACTED

    # Heuristic / service edges must preserve non-NONE ambiguity.
    edge_kind = _transfer_edge_kind(record)
    conf = "1"
    if derivation in (
        DerivationMethod.HEURISTIC_CLUSTER,
        DerivationMethod.HEURISTIC_PEEL,
        DerivationMethod.HEURISTIC_CHANGE,
        DerivationMethod.HEURISTIC_COINJOIN,
        DerivationMethod.HEURISTIC_SHARED_INFRA,
        DerivationMethod.GRAPHRAG_CANDIDATE,
    ):
        conf = "0.5"
        if ambiguity is AmbiguityKind.NONE:
            ambiguity = AmbiguityKind.MULTI_PARTY

    edge = FlowEdge(
        edge_id=edge_id,
        kind=edge_kind,
        plane=GraphPlane.OBSERVED_ADDRESS,
        source_node_id=src,
        target_node_id=tgt,
        chain=chain,
        ledger_model=ledger_model,
        coordinate=coordinate,
        asset=asset,
        amount=amount,
        direction=FlowDirection.OUT,
        finality=edge_finality,
        source=record.provenance.provider,
        confidence=conf,
        derivation=derivation,
        retraction=retraction,
        ambiguity=ambiguity,
        provider_ids=providers,
        timestamp=format_datetime(record.provenance.observed_at)
        if record.provenance.observed_at.tzinfo
        else "",
        attributes={
            "record_id": record.record_id,
            "transaction_hash": record.transaction_hash,
            "transfer_index": record.transfer_index,
            "transfer_kind": record.transfer_kind.value,
        },
    )
    builder.add_edge(edge)
    return edge_id


def _project_utxo(builder: CryptoFlowGraphBuilder, record: UTXORecord) -> str:
    providers = (record.provenance.provider,)
    finality = map_wallet_finality(record.finality)
    chain = to_chain_identity(record.chain)
    asset = to_asset_identity(record.asset)
    amount = to_crypto_amount(record.amount)
    node_id = utxo_node_id(record)
    if node_id not in builder._nodes:  # noqa: SLF001
        builder.add_node(
            FlowNode(
                node_id=node_id,
                kind=NodeKind.UTXO,
                plane=GraphPlane.OBSERVED_ADDRESS,
                chain=chain,
                ledger_model=LedgerModel.UTXO,
                coordinate=to_ledger_coordinate(
                    record, transaction_hash=record.transaction_hash
                ),
                asset=asset,
                amount=amount,
                address_ref=record.owner.address if record.owner is not None else "",
                entity_ref="",
                finality=finality
                if finality
                not in (FinalityStatus.REORGED, FinalityStatus.RETRACTED)
                else FinalityStatus.CONFIRMED,
                source=record.provenance.provider,
                derivation=DerivationMethod.DIRECT_OBSERVATION,
                provider_ids=providers,
                attributes={
                    "output_index": record.output_index,
                    "record_id": record.record_id,
                    "spent_by": record.spent_by_transaction_hash or "",
                    "transaction_hash": record.transaction_hash,
                },
            )
        )
    if record.owner is not None:
        owner_id = _ensure_observed_address(
            builder,
            record.owner,
            finality=FinalityStatus.CONFIRMED,
            provider_ids=providers,
            source=record.provenance.provider,
        )
        creates_id = derive_edge_id(
            "utxo_creates",
            {"owner": owner_id, "utxo": node_id},
        )
        if creates_id not in builder._edges:  # noqa: SLF001
            builder.add_edge(
                FlowEdge(
                    edge_id=creates_id,
                    kind=EdgeKind.CREATES,
                    plane=GraphPlane.OBSERVED_ADDRESS,
                    source_node_id=owner_id,
                    target_node_id=node_id,
                    chain=chain,
                    ledger_model=LedgerModel.UTXO,
                    coordinate=to_ledger_coordinate(
                        record, transaction_hash=record.transaction_hash
                    ),
                    asset=asset,
                    amount=amount,
                    direction=FlowDirection.OUT,
                    finality=map_wallet_finality(record.finality)
                    if record.finality
                    not in (Finality.ORPHANED, Finality.REVERTED, Finality.FAILED)
                    else FinalityStatus.CONFIRMED,
                    source=record.provenance.provider,
                    derivation=DerivationMethod.UTXO_SPEND,
                    provider_ids=providers,
                    attributes={"record_id": record.record_id},
                )
            )
        if record.spent_by_transaction_hash:
            spends_id = derive_edge_id(
                "utxo_spends",
                {
                    "spent_by": record.spent_by_transaction_hash,
                    "utxo": node_id,
                },
            )
            if spends_id not in builder._edges:  # noqa: SLF001
                # Synthetic spender endpoint keyed by spending tx hash.
                spender = derive_node_id(
                    "tx_spender",
                    {
                        "chain": record.chain.identity_dict(),
                        "transaction_hash": record.spent_by_transaction_hash,
                    },
                )
                if spender not in builder._nodes:  # noqa: SLF001
                    builder.add_node(
                        FlowNode(
                            node_id=spender,
                            kind=NodeKind.TRANSACTION,
                            plane=GraphPlane.OBSERVED_ADDRESS,
                            chain=chain,
                            ledger_model=LedgerModel.UTXO,
                            address_ref="",
                            entity_ref="",
                            finality=FinalityStatus.CONFIRMED,
                            source=record.provenance.provider,
                            derivation=DerivationMethod.UTXO_SPEND,
                            provider_ids=providers,
                            attributes={
                                "transaction_hash": record.spent_by_transaction_hash
                            },
                        )
                    )
                builder.add_edge(
                    FlowEdge(
                        edge_id=spends_id,
                        kind=EdgeKind.SPENDS,
                        plane=GraphPlane.OBSERVED_ADDRESS,
                        source_node_id=node_id,
                        target_node_id=spender,
                        chain=chain,
                        ledger_model=LedgerModel.UTXO,
                        asset=asset,
                        amount=amount,
                        direction=FlowDirection.OUT,
                        finality=FinalityStatus.CONFIRMED,
                        source=record.provenance.provider,
                        derivation=DerivationMethod.UTXO_SPEND,
                        provider_ids=providers,
                        attributes={"record_id": record.record_id},
                    )
                )
    return node_id


def _project_transaction(
    builder: CryptoFlowGraphBuilder, record: TransactionRecord
) -> str:
    providers = (record.provenance.provider,)
    finality = map_wallet_finality(record.finality)
    chain = to_chain_identity(record.chain)
    node_id = transaction_node_id(record)
    if node_id not in builder._nodes:  # noqa: SLF001
        builder.add_node(
            FlowNode(
                node_id=node_id,
                kind=NodeKind.TRANSACTION,
                plane=GraphPlane.OBSERVED_ADDRESS,
                chain=chain,
                ledger_model=default_ledger_model(chain),
                coordinate=to_ledger_coordinate(
                    record, transaction_hash=record.transaction_hash
                ),
                address_ref="",
                entity_ref="",
                finality=finality
                if finality
                not in (FinalityStatus.REORGED, FinalityStatus.RETRACTED)
                else FinalityStatus.CONFIRMED,
                source=record.provenance.provider,
                derivation=DerivationMethod.DIRECT_OBSERVATION,
                provider_ids=providers,
                attributes={
                    "record_id": record.record_id,
                    "status": record.status.value,
                    "transaction_hash": record.transaction_hash,
                },
            )
        )
    for participant in record.participants:
        pid = _ensure_observed_address(
            builder,
            participant,
            finality=FinalityStatus.CONFIRMED,
            provider_ids=providers,
            source=record.provenance.provider,
        )
        edge_id = derive_edge_id(
            "tx_participant",
            {"participant": pid, "transaction": node_id},
        )
        if edge_id not in builder._edges:  # noqa: SLF001
            builder.add_edge(
                FlowEdge(
                    edge_id=edge_id,
                    kind=EdgeKind.OBSERVES,
                    plane=GraphPlane.OBSERVED_ADDRESS,
                    source_node_id=node_id,
                    target_node_id=pid,
                    chain=chain,
                    ledger_model=default_ledger_model(chain),
                    coordinate=to_ledger_coordinate(
                        record, transaction_hash=record.transaction_hash
                    ),
                    direction=FlowDirection.NONE,
                    finality=FinalityStatus.CONFIRMED,
                    source=record.provenance.provider,
                    derivation=DerivationMethod.DIRECT_OBSERVATION,
                    provider_ids=providers,
                    attributes={"record_id": record.record_id},
                )
            )
    return node_id


def project_record(
    builder: CryptoFlowGraphBuilder, record: LedgerRecord
) -> str | None:
    """Project a single normalized ledger record onto *builder*.

    Returns the primary node/edge id produced, or ``None`` when the record type
    is intentionally ignored by this projector.
    """
    if not isinstance(record, LedgerRecord):
        raise WalletGraphProjectionError("record must be a LedgerRecord")
    if isinstance(record, TransferRecord):
        return _project_transfer(builder, record)
    if isinstance(record, UTXORecord):
        return _project_utxo(builder, record)
    if isinstance(record, TransactionRecord):
        return _project_transaction(builder, record)
    # Blocks, balances, token accounts, contract events are out of scope for
    # monetary-flow edges; callers may still pass mixed batches.
    return None


def project_assertion(
    builder: CryptoFlowGraphBuilder, assertion: EntityAssertion
) -> str:
    """Project an entity assertion strictly onto the asserted-entity plane."""
    if not isinstance(assertion, EntityAssertion):
        raise WalletGraphProjectionError("assertion must be an EntityAssertion")
    if assertion.kind is NodeKind.ADDRESS:
        raise PlaneConfusionError(
            "asserted-entity plane must not host raw ADDRESS nodes"
        )

    # Observed address refs may only appear as non-authoritative attributes.
    attrs = dict(assertion.attributes)
    if assertion.observed_address_node_id:
        attrs["observed_address_node_id"] = assertion.observed_address_node_id

    if assertion.node_id not in builder._nodes:  # noqa: SLF001
        builder.add_asserted_entity(
            assertion.node_id,
            entity_ref=assertion.entity_ref,
            kind=assertion.kind,
            source=assertion.source,
            confidence=assertion.confidence,
            derivation=assertion.derivation,
            ambiguity=assertion.ambiguity,
            provider_ids=assertion.provider_ids,
            attributes=attrs,
        )
    else:
        existing = builder._nodes[assertion.node_id]  # noqa: SLF001
        if existing.plane is not GraphPlane.ASSERTED_ENTITY:
            raise PlaneConfusionError(
                f"node {assertion.node_id} is not on the asserted_entity plane"
            )
        if existing.address_ref:
            raise PlaneConfusionError(
                "asserted entity node must not carry address_ref authority"
            )

    if assertion.related_entity_ref:
        related_id = derive_node_id(
            "asserted_entity",
            {
                "entity_ref": assertion.related_entity_ref,
                "kind": NodeKind.ENTITY.value,
            },
        )
        if related_id not in builder._nodes:  # noqa: SLF001
            builder.add_asserted_entity(
                related_id,
                entity_ref=assertion.related_entity_ref,
                kind=NodeKind.ENTITY,
                source=assertion.source,
                confidence=assertion.confidence,
                derivation=assertion.derivation,
                ambiguity=assertion.ambiguity,
                provider_ids=assertion.provider_ids,
            )
        edge_id = derive_edge_id(
            "asserted_relation",
            {
                "relation": assertion.relation.value,
                "source": assertion.node_id,
                "target": related_id,
            },
        )
        if edge_id not in builder._edges:  # noqa: SLF001
            if assertion.ambiguity is AmbiguityKind.NONE:
                raise PlaneConfusionError(
                    "asserted-plane relation edges must preserve non-NONE ambiguity"
                )
            builder.add_edge(
                FlowEdge(
                    edge_id=edge_id,
                    kind=assertion.relation,
                    plane=GraphPlane.ASSERTED_ENTITY,
                    source_node_id=assertion.node_id,
                    target_node_id=related_id,
                    derivation=assertion.derivation,
                    ambiguity=assertion.ambiguity,
                    confidence=assertion.confidence,
                    direction=FlowDirection.NONE,
                    source=assertion.source,
                    provider_ids=assertion.provider_ids,
                    attributes={
                        "entity_ref": assertion.entity_ref,
                        "related_entity_ref": assertion.related_entity_ref,
                    },
                )
            )
    return assertion.node_id


def _seed_builder_from_graph(
    builder: CryptoFlowGraphBuilder, graph: CryptoFlowGraph
) -> None:
    """Copy nodes, edges, and receipts from a prior immutable graph."""
    for node in graph.nodes:
        builder.add_node(node, replace_existing=True)
    for edge in graph.edges:
        builder.add_edge(edge, replace_existing=True)
    for receipt in graph.completeness_receipts:
        builder.add_completeness_receipt(receipt)
    for key, value in graph.attributes.items():
        builder.set_attribute(key, value)


def _edge_id_for_record_id(
    builder: CryptoFlowGraphBuilder, record_id: str
) -> str | None:
    """Locate an edge whose attributes.record_id matches *record_id*."""
    for edge in builder._edges.values():  # noqa: SLF001
        attrs = edge.attributes or {}
        if attrs.get("record_id") == record_id:
            return edge.edge_id
    # Also accept direct edge-id equality for callers that pass edge ids.
    if record_id in builder._edges:  # noqa: SLF001
        return record_id
    return None


def _apply_reorgs(
    builder: CryptoFlowGraphBuilder, identifiers: Sequence[str]
) -> tuple[str, ...]:
    """Mark edges as reorged/superseded; never delete them from history."""
    reorged: list[str] = []
    for ident in identifiers:
        edge_id = _edge_id_for_record_id(builder, ident)
        if edge_id is None:
            raise WalletGraphProjectionError(
                f"unknown edge/record for reorg: {ident}"
            )
        prior = builder._edges[edge_id]  # noqa: SLF001
        # Already reorged — idempotent within this builder.
        if (
            prior.finality is FinalityStatus.REORGED
            and prior.retraction is RetractionStatus.SUPERSEDED
        ):
            reorged.append(edge_id)
            continue
        builder.apply_reorg(edge_id)
        reorged.append(edge_id)
    return tuple(reorged)


def _apply_retractions(
    builder: CryptoFlowGraphBuilder, identifiers: Sequence[str]
) -> tuple[str, ...]:
    retracted: list[str] = []
    for ident in identifiers:
        edge_id = _edge_id_for_record_id(builder, ident)
        if edge_id is None:
            raise WalletGraphProjectionError(
                f"unknown edge/record for retraction: {ident}"
            )
        prior = builder._edges[edge_id]  # noqa: SLF001
        if prior.retraction is RetractionStatus.RETRACTED:
            retracted.append(edge_id)
            continue
        builder.retract_edge(edge_id)
        retracted.append(edge_id)
    return tuple(retracted)


def _assert_plane_integrity(graph: CryptoFlowGraph) -> None:
    """Fail closed if any node/edge confuses observed and asserted planes."""
    for node in graph.nodes:
        if node.plane is GraphPlane.OBSERVED_ADDRESS and node.entity_ref:
            raise PlaneConfusionError(
                f"observed node {node.node_id} carries entity_ref"
            )
        if node.plane is GraphPlane.ASSERTED_ENTITY and node.kind is NodeKind.ADDRESS:
            raise PlaneConfusionError(
                f"asserted node {node.node_id} has ADDRESS kind"
            )
        if node.plane is GraphPlane.ASSERTED_ENTITY and node.address_ref:
            # address_ref as empty string is fine; non-empty is confusion.
            raise PlaneConfusionError(
                f"asserted node {node.node_id} carries address_ref authority"
            )
    nodes = graph.node_map()
    for edge in graph.edges:
        src = nodes[edge.source_node_id]
        tgt = nodes[edge.target_node_id]
        if edge.plane is not src.plane or edge.plane is not tgt.plane:
            raise PlaneConfusionError(
                f"edge {edge.edge_id} crosses graph planes"
            )
        if edge.plane is GraphPlane.OBSERVED_ADDRESS and (
            src.entity_ref or tgt.entity_ref
        ):
            raise PlaneConfusionError(
                f"observed edge {edge.edge_id} endpoints carry entity_ref"
            )


def _receipt_from_snapshot(
    snapshot: GraphSnapshot,
    *,
    ledger_revision: str,
    graph_revision: str,
    status: ProjectionStatus,
    reorged_edge_ids: Sequence[str] = (),
    retracted_edge_ids: Sequence[str] = (),
) -> ProjectionReceipt:
    graph = snapshot.graph
    observed_nodes = graph.nodes_on_plane(GraphPlane.OBSERVED_ADDRESS)
    asserted_nodes = graph.nodes_on_plane(GraphPlane.ASSERTED_ENTITY)
    observed_edges = graph.edges_on_plane(GraphPlane.OBSERVED_ADDRESS)
    asserted_edges = graph.edges_on_plane(GraphPlane.ASSERTED_ENTITY)
    # Prefer attributes written at publish time when present.
    attrs = graph.attributes or {}
    ledger_rev = str(attrs.get("ledger_revision", ledger_revision))
    graph_rev = str(attrs.get("graph_revision", graph_revision))
    stored_reorged = attrs.get("reorged_edge_ids")
    stored_retracted = attrs.get("retracted_edge_ids")
    if isinstance(stored_reorged, Sequence) and not isinstance(stored_reorged, str):
        reorged = tuple(str(x) for x in stored_reorged)
    else:
        reorged = tuple(reorged_edge_ids)
    if isinstance(stored_retracted, Sequence) and not isinstance(
        stored_retracted, str
    ):
        retracted = tuple(str(x) for x in stored_retracted)
    else:
        retracted = tuple(retracted_edge_ids)
    return ProjectionReceipt(
        graph_id=graph.graph_id,
        ledger_revision=ledger_rev,
        graph_revision=graph_rev,
        snapshot_id=snapshot.snapshot_id,
        identity_digest=snapshot.identity.digest,
        graph_digest=graph.identity.digest,
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        observed_node_count=len(observed_nodes),
        asserted_node_count=len(asserted_nodes),
        observed_edge_count=len(observed_edges),
        asserted_edge_count=len(asserted_edges),
        reorged_edge_ids=reorged,
        retracted_edge_ids=retracted,
        status=status,
    )


# ---------------------------------------------------------------------------
# Projector
# ---------------------------------------------------------------------------


class WalletCryptoFlowProjector:
    """Incrementally derive and publish crypto-flow graph revisions from wallets.

    Thread-safe for process-local use.  Each ``project()`` call either:

    * **applies** a new immutable snapshot for ``(ledger_revision, graph_revision)``, or
    * **replays** an existing snapshot for that pair (idempotent).

    Reorgs never mutate a previously published snapshot.  Callers open a
    *successor* graph revision that marks prior edges ``REORGED`` /
    ``SUPERSEDED`` while retaining them as durable lineage.
    """

    def __init__(
        self,
        path: PathLike = ":memory:",
        *,
        graph_id: str = "wallet-crypto-flow",
        snapshot_store: DuckDBGraphSnapshotStore | None = None,
    ) -> None:
        if not isinstance(graph_id, str) or not graph_id.strip():
            raise WalletGraphProjectionError("graph_id must be a non-empty string")
        self._graph_id = graph_id.strip()
        self._lock = threading.RLock()
        self._closed = False
        if snapshot_store is not None:
            self._store = snapshot_store
            self._owns_store = False
            self._path = snapshot_store.path
        else:
            self._store = DuckDBGraphSnapshotStore(path)
            self._owns_store = True
            self._path = self._store.path

    # -- lifecycle -----------------------------------------------------------

    @property
    def graph_id(self) -> str:
        return self._graph_id

    @property
    def path(self) -> Path:
        return self._path

    @property
    def store(self) -> DuckDBGraphSnapshotStore:
        self._ensure_open()
        return self._store

    @property
    def interface_id(self) -> str:
        return DUCKDB_WALLET_GRAPH_PROJECTION_INTERFACE

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                if self._owns_store:
                    self._store.close()
            finally:
                self._closed = True

    def __enter__(self) -> "WalletCryptoFlowProjector":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise WalletGraphProjectionError("wallet graph projector is closed")

    # -- projection ----------------------------------------------------------

    def project(
        self,
        records: Sequence[LedgerRecord] = (),
        *,
        ledger_revision: str,
        graph_revision: str,
        assertions: Sequence[EntityAssertion] = (),
        reorg_ids: Sequence[str] = (),
        retract_ids: Sequence[str] = (),
        parent_ledger_revision: str | None = None,
        parent_graph_revision: str | None = None,
        completeness: CompletenessStatus = CompletenessStatus.PARTIAL,
        created_at: str = "",
    ) -> ProjectionReceipt:
        """Derive nodes/edges and publish an immutable graph revision.

        Parameters
        ----------
        records:
            Normalized wallet ledger records (transfers, UTXOs, transactions).
        ledger_revision:
            Wallet ledger / checkpoint revision that this projection covers.
        graph_revision:
            Graph revision identity for this projection outcome.
        assertions:
            Asserted-entity plane claims (never mixed into observed nodes).
        reorg_ids:
            Edge ids or source ``record_id`` values to mark as reorged in this
            revision (prior edges are superseded, not deleted).
        retract_ids:
            Edge ids or ``record_id`` values to mark as retracted.
        parent_ledger_revision / parent_graph_revision:
            Optional prior revision pair to seed incremental derivation from.
            Both must be provided together when used.
        """
        self._ensure_open()
        if not ledger_revision or not str(ledger_revision).strip():
            raise WalletGraphProjectionError(
                "ledger_revision must be a non-empty string"
            )
        if not graph_revision or not str(graph_revision).strip():
            raise WalletGraphProjectionError(
                "graph_revision must be a non-empty string"
            )
        ledger_revision = str(ledger_revision).strip()
        graph_revision = str(graph_revision).strip()

        if (parent_ledger_revision is None) ^ (parent_graph_revision is None):
            raise WalletGraphProjectionError(
                "parent_ledger_revision and parent_graph_revision must be "
                "provided together"
            )

        snapshot_id = projection_snapshot_id(
            self._graph_id, ledger_revision, graph_revision
        )

        with self._lock:
            # Idempotent by (ledger_revision, graph_revision).
            if self._store.contains(snapshot_id):
                existing = self._store.get(snapshot_id)
                return _receipt_from_snapshot(
                    existing,
                    ledger_revision=ledger_revision,
                    graph_revision=graph_revision,
                    status=ProjectionStatus.IDEMPOTENT_REPLAY,
                )

            builder = CryptoFlowGraphBuilder(self._graph_id)

            if parent_graph_revision is not None:
                parent_sid = projection_snapshot_id(
                    self._graph_id,
                    str(parent_ledger_revision).strip(),
                    str(parent_graph_revision).strip(),
                )
                try:
                    parent = self._store.get(parent_sid)
                except SnapshotStoreError as exc:
                    raise WalletGraphProjectionError(
                        f"parent graph revision not found: "
                        f"ledger={parent_ledger_revision!r} "
                        f"graph={parent_graph_revision!r}"
                    ) from exc
                _seed_builder_from_graph(builder, parent.graph)

            # Apply reorg / retraction on the seeded builder *before* new
            # records so replacement edges can coexist with superseded history.
            reorged = _apply_reorgs(builder, reorg_ids)
            retracted = _apply_retractions(builder, retract_ids)

            for record in records:
                project_record(builder, record)

            for assertion in assertions:
                project_assertion(builder, assertion)

            builder.set_attribute("ledger_revision", ledger_revision)
            builder.set_attribute("graph_revision", graph_revision)
            builder.set_attribute("projection_schema", DUCKDB_WALLET_GRAPH_PROJECTION_SCHEMA)
            builder.set_attribute("reorged_edge_ids", list(reorged))
            builder.set_attribute("retracted_edge_ids", list(retracted))
            if parent_graph_revision is not None:
                builder.set_attribute(
                    "parent_ledger_revision", str(parent_ledger_revision).strip()
                )
                builder.set_attribute(
                    "parent_graph_revision", str(parent_graph_revision).strip()
                )

            # Completeness receipt when we have any chain coverage.
            chains_seen: dict[str, ChainIdentity] = {}
            for record in records:
                if isinstance(record, LedgerRecord):
                    ci = to_chain_identity(record.chain)
                    key = f"{ci.chain_namespace}:{ci.network}:{ci.chain_id}"
                    chains_seen[key] = ci
            for idx, chain in enumerate(sorted(chains_seen.values(), key=lambda c: c.network)):
                builder.add_completeness_receipt(
                    CompletenessReceipt(
                        receipt_id=f"wallet-proj-{ledger_revision}-{idx}",
                        chain=chain,
                        scope="wallet-graph-projection",
                        completeness=completeness,
                        finality=FinalityStatus.CONFIRMED,
                        validity=ValidityWindow(
                            start=created_at or "1970-01-01T00:00:00Z",
                            end="",
                        ),
                        retraction=RetractionStatus.NOT_RETRACTED,
                        covered_ranges=(),
                        missing_ranges=(),
                        provider_ids=(),
                    )
                )

            snapshot = builder.snapshot(
                snapshot_id,
                completeness=completeness,
                created_at=created_at or _utc_now_iso(),
            )
            _assert_plane_integrity(snapshot.graph)

            try:
                self._store.put(snapshot)
            except SnapshotStoreError as exc:
                # Race: another writer published the same revision.
                if self._store.contains(snapshot_id):
                    existing = self._store.get(snapshot_id)
                    return _receipt_from_snapshot(
                        existing,
                        ledger_revision=ledger_revision,
                        graph_revision=graph_revision,
                        status=ProjectionStatus.IDEMPOTENT_REPLAY,
                    )
                raise WalletGraphProjectionError(str(exc)) from exc

            return _receipt_from_snapshot(
                snapshot,
                ledger_revision=ledger_revision,
                graph_revision=graph_revision,
                status=ProjectionStatus.APPLIED,
                reorged_edge_ids=reorged,
                retracted_edge_ids=retracted,
            )

    def get_snapshot(
        self, *, ledger_revision: str, graph_revision: str
    ) -> GraphSnapshot:
        """Fetch a published projection snapshot by revision pair."""
        self._ensure_open()
        sid = projection_snapshot_id(
            self._graph_id, ledger_revision, graph_revision
        )
        try:
            return self._store.get(sid)
        except SnapshotStoreError as exc:
            raise WalletGraphProjectionError(
                f"projection not found for ledger={ledger_revision!r} "
                f"graph={graph_revision!r}"
            ) from exc

    def contains(self, *, ledger_revision: str, graph_revision: str) -> bool:
        self._ensure_open()
        return self._store.contains(
            projection_snapshot_id(self._graph_id, ledger_revision, graph_revision)
        )

    def list_revision_pairs(self) -> tuple[tuple[str, str], ...]:
        """Return ``(ledger_revision, graph_revision)`` pairs from attributes."""
        self._ensure_open()
        pairs: list[tuple[str, str]] = []
        for sid in self._store.list_ids():
            snap = self._store.get(sid)
            attrs = snap.graph.attributes or {}
            ledger = attrs.get("ledger_revision")
            graph = attrs.get("graph_revision")
            if isinstance(ledger, str) and isinstance(graph, str):
                pairs.append((ledger, graph))
        return tuple(sorted(pairs))


def open_wallet_graph_projector(
    path: PathLike = ":memory:",
    *,
    graph_id: str = "wallet-crypto-flow",
) -> WalletCryptoFlowProjector:
    """Factory for a :class:`WalletCryptoFlowProjector`."""
    return WalletCryptoFlowProjector(path, graph_id=graph_id)
