"""Strict multi-chain monetary-flow knowledge graph records.

CRYPTOIR-G420 owns provenance-preserving, reorg-aware graph records for
transactions, UTXOs, transfers, calls, assets, services, bridges, list facts,
entities, ownership evidence, and retractions.

Observed-address and asserted-entity planes remain separate.  UTXO and
account ledgers are chain-correct.  Pool, mixer, exchange, bridge, CoinJoin,
peel/change, and shared-infrastructure ambiguity is preserved rather than
collapsed.  GraphRAG may surface candidate evidence; exact bounded traversal
(CRYPTOIR-G430) decides exposure.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.crypto_ir.identity import crypto_ir_identity
from ipfs_datasets_py.logic.crypto_ir.model import (
    AssetIdentity,
    ChainIdentity,
    CompletenessReceipt,
    CompletenessStatus,
    ExactAmount,
    FinalityStatus,
    LedgerCoordinate,
    RetractionStatus,
    ValidityWindow,
)
from ipfs_datasets_py.logic.crypto_ir.provenance import (
    AuthorityKind,
    CryptoIRProvenance,
    CryptoIRProvenanceError,
    freeze_json_mapping,
)
from ipfs_datasets_py.logic.ir_core.canonical import (
    CollectionSchema,
    CollectionSemantics,
    canonical_json_bytes,
)
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity
from ipfs_datasets_py.logic.ir_core.provenance import (
    ProvenanceValidationError,
    thaw_json,
)


CRYPTO_FLOWS_DOMAIN: Final[str] = "crypto-ir.crypto-flows"
CRYPTO_FLOWS_SCHEMA_VERSION: Final[str] = "crypto-flows.graph.v1"
CRYPTO_FLOWS_SNAPSHOT_SCHEMA_VERSION: Final[str] = "crypto-flows.snapshot.v1"
CRYPTO_FLOWS_NODE_SCHEMA_VERSION: Final[str] = "crypto-flows.node.v1"
CRYPTO_FLOWS_EDGE_SCHEMA_VERSION: Final[str] = "crypto-flows.edge.v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_CONFIDENCE_RE = re.compile(r"^(0(\.[0-9]+)?|1(\.0+)?)$")


class CryptoFlowValidationError(ValueError):
    """Raised when a flow-graph record is malformed or fails closed."""


class GraphPlane(str, Enum):
    """Separate planes: observed addresses vs asserted entities.

    Mixing planes in a single edge or collapsing them is forbidden.  Heuristic
    entity linkage is recorded as evidence on the asserted plane only.
    """

    OBSERVED_ADDRESS = "observed_address"
    ASSERTED_ENTITY = "asserted_entity"


class LedgerModel(str, Enum):
    """Chain-correct ledger accounting model."""

    UTXO = "utxo"
    ACCOUNT = "account"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class NodeKind(str, Enum):
    """Typed graph node kinds for monetary-flow topology."""

    CHAIN = "chain"
    ADDRESS = "address"
    ACCOUNT = "account"
    SCRIPT = "script"
    WALLET_CLAIM = "wallet_claim"
    TRANSACTION = "transaction"
    UTXO = "utxo"
    INPUT = "input"
    OUTPUT = "output"
    TRANSFER = "transfer"
    CALL = "call"
    PROGRAM = "program"
    CONTRACT = "contract"
    BRIDGE = "bridge"
    POOL = "pool"
    MIXER = "mixer"
    EXCHANGE = "exchange"
    ASSET = "asset"
    ENTITY = "entity"
    ALIAS = "alias"
    LIST_SNAPSHOT = "list_snapshot"
    DESIGNATION = "designation"
    OWNERSHIP_EVIDENCE = "ownership_evidence"
    LICENSE = "license"
    POLICY_REVISION = "policy_revision"
    COMPLETENESS = "completeness"
    RETRACTION = "retraction"
    ANALYSIS = "analysis"
    SERVICE = "service"
    OTHER = "other"


class EdgeKind(str, Enum):
    """Typed edge kinds carrying flow and provenance semantics."""

    TRANSFER = "transfer"
    SPENDS = "spends"
    CREATES = "creates"
    CALLS = "calls"
    APPROVES = "approves"
    BRIDGE_LOCK = "bridge_lock"
    BRIDGE_MINT = "bridge_mint"
    BRIDGE_BURN = "bridge_burn"
    BRIDGE_RELEASE = "bridge_release"
    POOL_DEPOSIT = "pool_deposit"
    POOL_WITHDRAW = "pool_withdraw"
    MIXER_DEPOSIT = "mixer_deposit"
    MIXER_WITHDRAW = "mixer_withdraw"
    EXCHANGE_DEPOSIT = "exchange_deposit"
    EXCHANGE_WITHDRAW = "exchange_withdraw"
    COINJOIN = "coinjoin"
    PEEL = "peel"
    CHANGE = "change"
    SHARED_INFRASTRUCTURE = "shared_infrastructure"
    OWNS = "owns"
    ALIASES = "aliases"
    DESIGNATES = "designates"
    CONTROLS = "controls"
    OBSERVES = "observes"
    DERIVES = "derives"
    RETRACTS = "retracts"
    OTHER = "other"


class FlowDirection(str, Enum):
    """Monetary direction of an edge relative to its endpoints."""

    OUT = "out"
    IN = "in"
    BIDIRECTIONAL = "bidirectional"
    NONE = "none"
    UNKNOWN = "unknown"


class DerivationMethod(str, Enum):
    """How an edge or node was derived; never elevates authority."""

    DIRECT_OBSERVATION = "direct_observation"
    UTXO_SPEND = "utxo_spend"
    ACCOUNT_TRANSFER = "account_transfer"
    LOG_EVENT = "log_event"
    BRIDGE_MESSAGE = "bridge_message"
    HEURISTIC_CLUSTER = "heuristic_cluster"
    HEURISTIC_PEEL = "heuristic_peel"
    HEURISTIC_CHANGE = "heuristic_change"
    HEURISTIC_COINJOIN = "heuristic_coinjoin"
    HEURISTIC_SHARED_INFRA = "heuristic_shared_infra"
    GRAPHRAG_CANDIDATE = "graphrag_candidate"
    POLICY_LINK = "policy_link"
    MANUAL = "manual"
    OTHER = "other"
    UNKNOWN = "unknown"


class AmbiguityKind(str, Enum):
    """Preserved ambiguity classes that must not be collapsed to certainty."""

    NONE = "none"
    POOL = "pool"
    MIXER = "mixer"
    EXCHANGE = "exchange"
    BRIDGE = "bridge"
    COINJOIN = "coinjoin"
    PEEL_CHANGE = "peel_change"
    SHARED_INFRASTRUCTURE = "shared_infrastructure"
    MULTI_PARTY = "multi_party"
    PROVIDER_DISAGREEMENT = "provider_disagreement"
    REORG = "reorg"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CryptoFlowValidationError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise CryptoFlowValidationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise CryptoFlowValidationError(f"{name} must not have surrounding whitespace")
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _ID_RE.fullmatch(normalized):
        raise CryptoFlowValidationError(f"{name} is not a stable identifier")
    return normalized


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CryptoFlowValidationError(f"{name} must be a mapping")
    return value


def _known_fields(value: Mapping[str, Any], allowed: frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CryptoFlowValidationError(
            f"unknown {name} field(s): {', '.join(unknown)}"
        )


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (ProvenanceValidationError, CryptoIRProvenanceError) as exc:
        raise CryptoFlowValidationError(str(exc)) from exc


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CryptoFlowValidationError(f"unsupported {name}: {value!r}") from exc


def _confidence(value: Any, name: str = "confidence") -> str:
    """Canonical decimal confidence in [0, 1] as a string (no binary floats)."""
    if isinstance(value, float) or isinstance(value, bool):
        raise CryptoFlowValidationError(f"{name} rejects binary floats and booleans")
    if type(value) is int:
        if value not in (0, 1):
            raise CryptoFlowValidationError(f"{name} integer must be 0 or 1")
        return str(value)
    text = _text(value, name)
    if not _CONFIDENCE_RE.fullmatch(text):
        raise CryptoFlowValidationError(
            f"{name} must be a canonical decimal string in [0, 1]"
        )
    return text


def _unique_ids(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoFlowValidationError(f"{name} must be a sequence")
    result = tuple(_identifier(item, name) for item in values)
    if len(result) != len(set(result)):
        raise CryptoFlowValidationError(f"{name} values must be unique")
    return result


def _optional_chain(value: Any, name: str) -> ChainIdentity | None:
    if value is None:
        return None
    if isinstance(value, ChainIdentity):
        return value
    return ChainIdentity.from_dict(_as_mapping(value, name))


def _optional_asset(value: Any, name: str) -> AssetIdentity | None:
    if value is None:
        return None
    if isinstance(value, AssetIdentity):
        return value
    return AssetIdentity.from_dict(_as_mapping(value, name))


def _optional_amount(value: Any, name: str) -> ExactAmount | None:
    if value is None:
        return None
    if isinstance(value, ExactAmount):
        return value
    if isinstance(value, float) or isinstance(value, bool):
        raise CryptoFlowValidationError(f"{name} rejects binary floats")
    return ExactAmount.from_dict(_as_mapping(value, name))


def _optional_coordinate(value: Any, name: str) -> LedgerCoordinate | None:
    if value is None:
        return None
    if isinstance(value, LedgerCoordinate):
        return value
    return LedgerCoordinate.from_dict(_as_mapping(value, name))


def _require_validity(value: Any, name: str = "validity") -> ValidityWindow:
    if isinstance(value, ValidityWindow):
        return value
    return ValidityWindow.from_dict(_as_mapping(value, name))


def _optional_provenance(value: Any, name: str) -> CryptoIRProvenance | None:
    if value is None:
        return None
    if isinstance(value, CryptoIRProvenance):
        return value
    return CryptoIRProvenance.from_dict(_as_mapping(value, name))


def _sequence_of(
    values: Any,
    item_type: type[Any],
    name: str,
    *,
    from_dict: Any | None = None,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoFlowValidationError(f"{name} must be a sequence")
    converted: list[Any] = []
    for item in values:
        if isinstance(item, item_type):
            converted.append(item)
        elif from_dict is not None and isinstance(item, Mapping):
            converted.append(from_dict(item))
        else:
            raise CryptoFlowValidationError(
                f"{name} items must be {item_type.__name__} or mappings"
            )
    return tuple(converted)


# Ledger models that are chain-correct for common namespaces.
_CHAIN_LEDGER_DEFAULTS: Final[Mapping[str, LedgerModel]] = {
    "eip155": LedgerModel.ACCOUNT,
    "solana": LedgerModel.ACCOUNT,
    "bip122": LedgerModel.UTXO,
    "bitcoin": LedgerModel.UTXO,
    "xrpl": LedgerModel.ACCOUNT,
    "ripple": LedgerModel.ACCOUNT,
    "worldchain": LedgerModel.ACCOUNT,
}


def default_ledger_model(chain: ChainIdentity) -> LedgerModel:
    """Return the chain-correct default ledger model for a chain identity."""
    namespace = chain.chain_namespace.lower()
    if namespace in _CHAIN_LEDGER_DEFAULTS:
        return _CHAIN_LEDGER_DEFAULTS[namespace]
    # World Chain and other EVM L2s often use eip155; fall through on network.
    network = chain.network.lower()
    if "bitcoin" in network or network.startswith("btc"):
        return LedgerModel.UTXO
    if any(token in network for token in ("ethereum", "world", "solana", "xrpl", "ripple")):
        return LedgerModel.ACCOUNT
    return LedgerModel.UNKNOWN


def assert_ledger_model_chain_correct(
    chain: ChainIdentity, ledger_model: LedgerModel
) -> None:
    """Fail closed when an explicit ledger model contradicts the chain."""
    expected = default_ledger_model(chain)
    if expected is LedgerModel.UNKNOWN:
        return
    if ledger_model is LedgerModel.UNKNOWN or ledger_model is LedgerModel.HYBRID:
        return
    if ledger_model is not expected:
        raise CryptoFlowValidationError(
            f"ledger_model {ledger_model.value!r} is not chain-correct for "
            f"{chain.chain_namespace}/{chain.network} (expected {expected.value})"
        )


# ---------------------------------------------------------------------------
# Nodes and edges
# ---------------------------------------------------------------------------


FLOW_NODE_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/provider_ids": CollectionSemantics.SET_LIKE,
        "/asset_ids": CollectionSemantics.SET_LIKE,
        "/assumption_ids": CollectionSemantics.SET_LIKE,
    }
)


@dataclass(frozen=True, slots=True)
class FlowNode:
    """Typed monetary-flow graph node with provenance and finality bindings.

    Every node binds plane, kind, optional chain/ledger coordinate, asset,
    exact amount, finality, source, confidence, validity, derivation, and
    retraction.  Observed-address nodes never carry asserted-entity identity
    as authority.
    """

    node_id: str
    kind: NodeKind
    plane: GraphPlane
    chain: ChainIdentity | None = None
    ledger_model: LedgerModel = LedgerModel.UNKNOWN
    coordinate: LedgerCoordinate | None = None
    asset: AssetIdentity | None = None
    amount: ExactAmount | None = None
    address_ref: str = ""
    entity_ref: str = ""
    finality: FinalityStatus = FinalityStatus.UNKNOWN
    source: str = ""
    confidence: str = "1"
    validity: ValidityWindow = field(default_factory=ValidityWindow)
    derivation: DerivationMethod = DerivationMethod.UNKNOWN
    retraction: RetractionStatus = RetractionStatus.NOT_RETRACTED
    ambiguity: AmbiguityKind = AmbiguityKind.NONE
    provider_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    provenance: CryptoIRProvenance | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_FLOWS_NODE_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.OBSERVATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _identifier(self.node_id, "node_id"))
        object.__setattr__(self, "kind", _enum(NodeKind, self.kind, "kind"))
        object.__setattr__(self, "plane", _enum(GraphPlane, self.plane, "plane"))
        object.__setattr__(self, "chain", _optional_chain(self.chain, "chain"))
        object.__setattr__(
            self, "ledger_model", _enum(LedgerModel, self.ledger_model, "ledger_model")
        )
        if self.chain is not None and self.ledger_model is not LedgerModel.UNKNOWN:
            assert_ledger_model_chain_correct(self.chain, self.ledger_model)
        object.__setattr__(
            self, "coordinate", _optional_coordinate(self.coordinate, "coordinate")
        )
        object.__setattr__(self, "asset", _optional_asset(self.asset, "asset"))
        object.__setattr__(self, "amount", _optional_amount(self.amount, "amount"))
        object.__setattr__(
            self, "address_ref", _text(self.address_ref, "address_ref", allow_empty=True)
        )
        object.__setattr__(
            self, "entity_ref", _text(self.entity_ref, "entity_ref", allow_empty=True)
        )
        # Plane separation: address refs belong to observed plane; entity refs
        # belong to asserted plane (may be empty on either).
        if self.plane is GraphPlane.OBSERVED_ADDRESS and self.entity_ref:
            raise CryptoFlowValidationError(
                "observed_address plane must not carry entity_ref authority"
            )
        if self.plane is GraphPlane.ASSERTED_ENTITY and self.kind is NodeKind.ADDRESS:
            raise CryptoFlowValidationError(
                "asserted_entity plane must not host raw ADDRESS nodes"
            )
        object.__setattr__(
            self, "finality", _enum(FinalityStatus, self.finality, "finality")
        )
        object.__setattr__(
            self, "source", _text(self.source, "source", allow_empty=True)
        )
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "validity", _require_validity(self.validity))
        object.__setattr__(
            self,
            "derivation",
            _enum(DerivationMethod, self.derivation, "derivation"),
        )
        object.__setattr__(
            self, "retraction", _enum(RetractionStatus, self.retraction, "retraction")
        )
        object.__setattr__(
            self, "ambiguity", _enum(AmbiguityKind, self.ambiguity, "ambiguity")
        )
        object.__setattr__(
            self, "provider_ids", _unique_ids(self.provider_ids, "provider_ids")
        )
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(
            self, "provenance", _optional_provenance(self.provenance, "provenance")
        )
        if self.provenance is not None:
            if self.provenance.authority.kind not in (
                AuthorityKind.OBSERVATION,
                AuthorityKind.EVIDENCE,
                AuthorityKind.ASSUMPTION,
                AuthorityKind.DECLARATION,
            ):
                raise CryptoFlowValidationError(
                    "FlowNode provenance authority must not be authorization"
                )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "address_ref": self.address_ref,
            "ambiguity": self.ambiguity.value,
            "amount": None if self.amount is None else self.amount.to_dict(),
            "asset": None if self.asset is None else self.asset.to_dict(),
            "assumption_ids": list(self.assumption_ids),
            "attributes": thaw_json(self.attributes),
            "chain": None if self.chain is None else self.chain.to_dict(),
            "confidence": self.confidence,
            "coordinate": None
            if self.coordinate is None
            else self.coordinate.to_dict(),
            "derivation": self.derivation.value,
            "entity_ref": self.entity_ref,
            "finality": self.finality.value,
            "kind": self.kind.value,
            "ledger_model": self.ledger_model.value,
            "node_id": self.node_id,
            "plane": self.plane.value,
            "provenance": None if self.provenance is None else self.provenance.to_dict(),
            "provider_ids": list(self.provider_ids),
            "retraction": self.retraction.value,
            "schema_version": self.schema_version,
            "source": self.source,
            "validity": self.validity.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FlowNode":
        value = _as_mapping(value, "FlowNode")
        _known_fields(
            value,
            frozenset(
                {
                    "node_id",
                    "kind",
                    "plane",
                    "chain",
                    "ledger_model",
                    "coordinate",
                    "asset",
                    "amount",
                    "address_ref",
                    "entity_ref",
                    "finality",
                    "source",
                    "confidence",
                    "validity",
                    "derivation",
                    "retraction",
                    "ambiguity",
                    "provider_ids",
                    "assumption_ids",
                    "provenance",
                    "attributes",
                    "schema_version",
                }
            ),
            "FlowNode",
        )
        chain_raw = value.get("chain")
        asset_raw = value.get("asset")
        amount_raw = value.get("amount")
        coord_raw = value.get("coordinate")
        prov_raw = value.get("provenance")
        return cls(
            node_id=value.get("node_id", ""),
            kind=value.get("kind", NodeKind.OTHER.value),
            plane=value.get("plane", GraphPlane.OBSERVED_ADDRESS.value),
            chain=None
            if chain_raw is None
            else ChainIdentity.from_dict(_as_mapping(chain_raw, "chain")),
            ledger_model=value.get("ledger_model", LedgerModel.UNKNOWN.value),
            coordinate=None
            if coord_raw is None
            else LedgerCoordinate.from_dict(_as_mapping(coord_raw, "coordinate")),
            asset=None
            if asset_raw is None
            else AssetIdentity.from_dict(_as_mapping(asset_raw, "asset")),
            amount=None
            if amount_raw is None
            else ExactAmount.from_dict(_as_mapping(amount_raw, "amount")),
            address_ref=value.get("address_ref", ""),
            entity_ref=value.get("entity_ref", ""),
            finality=value.get("finality", FinalityStatus.UNKNOWN.value),
            source=value.get("source", ""),
            confidence=value.get("confidence", "1"),
            validity=ValidityWindow.from_dict(
                _as_mapping(value.get("validity", {}), "validity")
            ),
            derivation=value.get("derivation", DerivationMethod.UNKNOWN.value),
            retraction=value.get("retraction", RetractionStatus.NOT_RETRACTED.value),
            ambiguity=value.get("ambiguity", AmbiguityKind.NONE.value),
            provider_ids=tuple(value.get("provider_ids", ())),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            provenance=None
            if prov_raw is None
            else CryptoIRProvenance.from_dict(_as_mapping(prov_raw, "provenance")),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_FLOWS_NODE_SCHEMA_VERSION
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            self.to_dict(), collection_schema=FLOW_NODE_COLLECTION_SCHEMA
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_FLOWS_DOMAIN}.node",
            collection_schema=FLOW_NODE_COLLECTION_SCHEMA,
        )


FLOW_EDGE_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/provider_ids": CollectionSemantics.SET_LIKE,
        "/assumption_ids": CollectionSemantics.SET_LIKE,
    }
)


@dataclass(frozen=True, slots=True)
class FlowEdge:
    """Typed edge with amount, direction, finality, derivation, and ambiguity.

    Edges never cross graph planes.  Ambiguity kinds (mixer, CoinJoin, bridge,
    peel/change, shared infrastructure) are first-class and must not be
    rewritten as certain single-party transfers.
    """

    edge_id: str
    kind: EdgeKind
    plane: GraphPlane
    source_node_id: str
    target_node_id: str
    chain: ChainIdentity | None = None
    ledger_model: LedgerModel = LedgerModel.UNKNOWN
    coordinate: LedgerCoordinate | None = None
    asset: AssetIdentity | None = None
    amount: ExactAmount | None = None
    direction: FlowDirection = FlowDirection.UNKNOWN
    finality: FinalityStatus = FinalityStatus.UNKNOWN
    source: str = ""
    confidence: str = "1"
    validity: ValidityWindow = field(default_factory=ValidityWindow)
    derivation: DerivationMethod = DerivationMethod.UNKNOWN
    retraction: RetractionStatus = RetractionStatus.NOT_RETRACTED
    ambiguity: AmbiguityKind = AmbiguityKind.NONE
    provider_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    timestamp: str = ""
    provenance: CryptoIRProvenance | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_FLOWS_EDGE_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.OBSERVATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))
        object.__setattr__(self, "kind", _enum(EdgeKind, self.kind, "kind"))
        object.__setattr__(self, "plane", _enum(GraphPlane, self.plane, "plane"))
        object.__setattr__(
            self, "source_node_id", _identifier(self.source_node_id, "source_node_id")
        )
        object.__setattr__(
            self, "target_node_id", _identifier(self.target_node_id, "target_node_id")
        )
        object.__setattr__(self, "chain", _optional_chain(self.chain, "chain"))
        object.__setattr__(
            self, "ledger_model", _enum(LedgerModel, self.ledger_model, "ledger_model")
        )
        if self.chain is not None and self.ledger_model is not LedgerModel.UNKNOWN:
            assert_ledger_model_chain_correct(self.chain, self.ledger_model)
        object.__setattr__(
            self, "coordinate", _optional_coordinate(self.coordinate, "coordinate")
        )
        object.__setattr__(self, "asset", _optional_asset(self.asset, "asset"))
        object.__setattr__(self, "amount", _optional_amount(self.amount, "amount"))
        object.__setattr__(
            self, "direction", _enum(FlowDirection, self.direction, "direction")
        )
        object.__setattr__(
            self, "finality", _enum(FinalityStatus, self.finality, "finality")
        )
        object.__setattr__(
            self, "source", _text(self.source, "source", allow_empty=True)
        )
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "validity", _require_validity(self.validity))
        object.__setattr__(
            self,
            "derivation",
            _enum(DerivationMethod, self.derivation, "derivation"),
        )
        object.__setattr__(
            self, "retraction", _enum(RetractionStatus, self.retraction, "retraction")
        )
        object.__setattr__(
            self, "ambiguity", _enum(AmbiguityKind, self.ambiguity, "ambiguity")
        )
        # Heuristic / GraphRAG edges cannot claim direct-observation certainty.
        if self.derivation in (
            DerivationMethod.HEURISTIC_CLUSTER,
            DerivationMethod.HEURISTIC_PEEL,
            DerivationMethod.HEURISTIC_CHANGE,
            DerivationMethod.HEURISTIC_COINJOIN,
            DerivationMethod.HEURISTIC_SHARED_INFRA,
            DerivationMethod.GRAPHRAG_CANDIDATE,
        ):
            if self.ambiguity is AmbiguityKind.NONE:
                raise CryptoFlowValidationError(
                    f"derivation {self.derivation.value} must preserve non-NONE ambiguity"
                )
            if self.confidence == "1":
                raise CryptoFlowValidationError(
                    f"derivation {self.derivation.value} must not claim confidence=1"
                )
        object.__setattr__(
            self, "provider_ids", _unique_ids(self.provider_ids, "provider_ids")
        )
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(
            self, "timestamp", _text(self.timestamp, "timestamp", allow_empty=True)
        )
        object.__setattr__(
            self, "provenance", _optional_provenance(self.provenance, "provenance")
        )
        if self.provenance is not None:
            if self.provenance.authority.kind is AuthorityKind.AUTHORIZATION:
                raise CryptoFlowValidationError(
                    "FlowEdge provenance must not carry authorization authority"
                )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity": self.ambiguity.value,
            "amount": None if self.amount is None else self.amount.to_dict(),
            "asset": None if self.asset is None else self.asset.to_dict(),
            "assumption_ids": list(self.assumption_ids),
            "attributes": thaw_json(self.attributes),
            "chain": None if self.chain is None else self.chain.to_dict(),
            "confidence": self.confidence,
            "coordinate": None
            if self.coordinate is None
            else self.coordinate.to_dict(),
            "derivation": self.derivation.value,
            "direction": self.direction.value,
            "edge_id": self.edge_id,
            "finality": self.finality.value,
            "kind": self.kind.value,
            "ledger_model": self.ledger_model.value,
            "plane": self.plane.value,
            "provenance": None if self.provenance is None else self.provenance.to_dict(),
            "provider_ids": list(self.provider_ids),
            "retraction": self.retraction.value,
            "schema_version": self.schema_version,
            "source": self.source,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "timestamp": self.timestamp,
            "validity": self.validity.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FlowEdge":
        value = _as_mapping(value, "FlowEdge")
        _known_fields(
            value,
            frozenset(
                {
                    "edge_id",
                    "kind",
                    "plane",
                    "source_node_id",
                    "target_node_id",
                    "chain",
                    "ledger_model",
                    "coordinate",
                    "asset",
                    "amount",
                    "direction",
                    "finality",
                    "source",
                    "confidence",
                    "validity",
                    "derivation",
                    "retraction",
                    "ambiguity",
                    "provider_ids",
                    "assumption_ids",
                    "timestamp",
                    "provenance",
                    "attributes",
                    "schema_version",
                }
            ),
            "FlowEdge",
        )
        chain_raw = value.get("chain")
        asset_raw = value.get("asset")
        amount_raw = value.get("amount")
        coord_raw = value.get("coordinate")
        prov_raw = value.get("provenance")
        return cls(
            edge_id=value.get("edge_id", ""),
            kind=value.get("kind", EdgeKind.OTHER.value),
            plane=value.get("plane", GraphPlane.OBSERVED_ADDRESS.value),
            source_node_id=value.get("source_node_id", ""),
            target_node_id=value.get("target_node_id", ""),
            chain=None
            if chain_raw is None
            else ChainIdentity.from_dict(_as_mapping(chain_raw, "chain")),
            ledger_model=value.get("ledger_model", LedgerModel.UNKNOWN.value),
            coordinate=None
            if coord_raw is None
            else LedgerCoordinate.from_dict(_as_mapping(coord_raw, "coordinate")),
            asset=None
            if asset_raw is None
            else AssetIdentity.from_dict(_as_mapping(asset_raw, "asset")),
            amount=None
            if amount_raw is None
            else ExactAmount.from_dict(_as_mapping(amount_raw, "amount")),
            direction=value.get("direction", FlowDirection.UNKNOWN.value),
            finality=value.get("finality", FinalityStatus.UNKNOWN.value),
            source=value.get("source", ""),
            confidence=value.get("confidence", "1"),
            validity=ValidityWindow.from_dict(
                _as_mapping(value.get("validity", {}), "validity")
            ),
            derivation=value.get("derivation", DerivationMethod.UNKNOWN.value),
            retraction=value.get("retraction", RetractionStatus.NOT_RETRACTED.value),
            ambiguity=value.get("ambiguity", AmbiguityKind.NONE.value),
            provider_ids=tuple(value.get("provider_ids", ())),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            timestamp=value.get("timestamp", ""),
            provenance=None
            if prov_raw is None
            else CryptoIRProvenance.from_dict(_as_mapping(prov_raw, "provenance")),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_FLOWS_EDGE_SCHEMA_VERSION
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            self.to_dict(), collection_schema=FLOW_EDGE_COLLECTION_SCHEMA
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_FLOWS_DOMAIN}.edge",
            collection_schema=FLOW_EDGE_COLLECTION_SCHEMA,
        )


# ---------------------------------------------------------------------------
# Graph and snapshot
# ---------------------------------------------------------------------------


CRYPTO_FLOW_GRAPH_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/nodes": CollectionSemantics.SET_LIKE,
        "/edges": CollectionSemantics.SET_LIKE,
        "/completeness_receipts": CollectionSemantics.SET_LIKE,
        "/asset_ids": CollectionSemantics.SET_LIKE,
        "/provider_ids": CollectionSemantics.SET_LIKE,
        "/chain_ids": CollectionSemantics.SET_LIKE,
    }
)


@dataclass(frozen=True, slots=True)
class CryptoFlowGraph:
    """Immutable multi-chain monetary-flow graph.

    Nodes and edges are validated for plane separation, endpoint existence, and
    chain-correct ledger models.  Order is not semantic; identities are
    content-addressed via set-like collection semantics.
    """

    graph_id: str
    nodes: tuple[FlowNode, ...] = ()
    edges: tuple[FlowEdge, ...] = ()
    completeness_receipts: tuple[CompletenessReceipt, ...] = ()
    provider_ids: tuple[str, ...] = ()
    asset_ids: tuple[str, ...] = ()
    chain_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_FLOWS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_id", _identifier(self.graph_id, "graph_id"))
        nodes = _sequence_of(
            self.nodes, FlowNode, "nodes", from_dict=FlowNode.from_dict
        )
        # Deterministic node order by node_id for stable iteration (set-like
        # identity still applies for content addressing).
        nodes = tuple(sorted(nodes, key=lambda n: n.node_id))
        object.__setattr__(self, "nodes", nodes)
        node_ids = {n.node_id for n in nodes}
        if len(node_ids) != len(nodes):
            raise CryptoFlowValidationError("node_id values must be unique")

        edges = _sequence_of(
            self.edges, FlowEdge, "edges", from_dict=FlowEdge.from_dict
        )
        edges = tuple(sorted(edges, key=lambda e: e.edge_id))
        object.__setattr__(self, "edges", edges)
        edge_ids = {e.edge_id for e in edges}
        if len(edge_ids) != len(edges):
            raise CryptoFlowValidationError("edge_id values must be unique")

        node_by_id = {n.node_id: n for n in nodes}
        for edge in edges:
            if edge.source_node_id not in node_by_id:
                raise CryptoFlowValidationError(
                    f"edge {edge.edge_id} source_node_id missing: {edge.source_node_id}"
                )
            if edge.target_node_id not in node_by_id:
                raise CryptoFlowValidationError(
                    f"edge {edge.edge_id} target_node_id missing: {edge.target_node_id}"
                )
            src = node_by_id[edge.source_node_id]
            tgt = node_by_id[edge.target_node_id]
            if edge.plane is not src.plane or edge.plane is not tgt.plane:
                raise CryptoFlowValidationError(
                    f"edge {edge.edge_id} must not cross graph planes"
                )

        receipts = _sequence_of(
            self.completeness_receipts,
            CompletenessReceipt,
            "completeness_receipts",
            from_dict=CompletenessReceipt.from_dict,
        )
        receipts = tuple(sorted(receipts, key=lambda r: r.receipt_id))
        object.__setattr__(self, "completeness_receipts", receipts)
        object.__setattr__(
            self, "provider_ids", _unique_ids(self.provider_ids, "provider_ids")
        )
        object.__setattr__(self, "asset_ids", _unique_ids(self.asset_ids, "asset_ids"))
        object.__setattr__(self, "chain_ids", _unique_ids(self.chain_ids, "chain_ids"))
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def node_map(self) -> Mapping[str, FlowNode]:
        return {n.node_id: n for n in self.nodes}

    def edge_map(self) -> Mapping[str, FlowEdge]:
        return {e.edge_id: e for e in self.edges}

    def nodes_on_plane(self, plane: GraphPlane) -> tuple[FlowNode, ...]:
        plane = _enum(GraphPlane, plane, "plane")  # type: ignore[assignment]
        return tuple(n for n in self.nodes if n.plane is plane)

    def edges_on_plane(self, plane: GraphPlane) -> tuple[FlowEdge, ...]:
        plane = _enum(GraphPlane, plane, "plane")  # type: ignore[assignment]
        return tuple(e for e in self.edges if e.plane is plane)

    def active_edges(self) -> tuple[FlowEdge, ...]:
        """Edges that are not retracted or reorged."""
        return tuple(
            e
            for e in self.edges
            if e.retraction is RetractionStatus.NOT_RETRACTED
            and e.finality not in (FinalityStatus.REORGED, FinalityStatus.RETRACTED)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_ids": list(self.asset_ids),
            "attributes": thaw_json(self.attributes),
            "chain_ids": list(self.chain_ids),
            "completeness_receipts": [
                r.to_dict() for r in self.completeness_receipts
            ],
            "edges": [e.to_dict() for e in self.edges],
            "graph_id": self.graph_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "provider_ids": list(self.provider_ids),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CryptoFlowGraph":
        value = _as_mapping(value, "CryptoFlowGraph")
        _known_fields(
            value,
            frozenset(
                {
                    "graph_id",
                    "nodes",
                    "edges",
                    "completeness_receipts",
                    "provider_ids",
                    "asset_ids",
                    "chain_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "CryptoFlowGraph",
        )
        return cls(
            graph_id=value.get("graph_id", ""),
            nodes=tuple(
                FlowNode.from_dict(item) for item in value.get("nodes", ())
            ),
            edges=tuple(
                FlowEdge.from_dict(item) for item in value.get("edges", ())
            ),
            completeness_receipts=tuple(
                CompletenessReceipt.from_dict(item)
                for item in value.get("completeness_receipts", ())
            ),
            provider_ids=tuple(value.get("provider_ids", ())),
            asset_ids=tuple(value.get("asset_ids", ())),
            chain_ids=tuple(value.get("chain_ids", ())),
            attributes=value.get("attributes", {}),
            schema_version=value.get("schema_version", CRYPTO_FLOWS_SCHEMA_VERSION),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            self.to_dict(), collection_schema=CRYPTO_FLOW_GRAPH_COLLECTION_SCHEMA
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_FLOWS_DOMAIN}.graph",
            collection_schema=CRYPTO_FLOW_GRAPH_COLLECTION_SCHEMA,
        )


GRAPH_SNAPSHOT_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/covered_providers": CollectionSemantics.SET_LIKE,
        "/covered_assets": CollectionSemantics.SET_LIKE,
        "/covered_chains": CollectionSemantics.SET_LIKE,
        "/completeness_receipts": CollectionSemantics.SET_LIKE,
    }
)


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    """Deterministic immutable snapshot of a flow graph plus completeness.

    Reports provider, range, and asset completeness via attached
    :class:`CompletenessReceipt` records.  Snapshot content identity is stable
    under equivalent set membership.
    """

    snapshot_id: str
    graph: CryptoFlowGraph
    completeness: CompletenessStatus = CompletenessStatus.UNKNOWN
    completeness_receipts: tuple[CompletenessReceipt, ...] = ()
    covered_providers: tuple[str, ...] = ()
    covered_assets: tuple[str, ...] = ()
    covered_chains: tuple[str, ...] = ()
    covered_ranges: tuple[LedgerCoordinate, ...] = ()
    missing_ranges: tuple[LedgerCoordinate, ...] = ()
    created_at: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_FLOWS_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "snapshot_id", _identifier(self.snapshot_id, "snapshot_id")
        )
        if not isinstance(self.graph, CryptoFlowGraph):
            object.__setattr__(
                self,
                "graph",
                CryptoFlowGraph.from_dict(_as_mapping(self.graph, "graph")),
            )
        object.__setattr__(
            self,
            "completeness",
            _enum(CompletenessStatus, self.completeness, "completeness"),
        )
        receipts = _sequence_of(
            self.completeness_receipts,
            CompletenessReceipt,
            "completeness_receipts",
            from_dict=CompletenessReceipt.from_dict,
        )
        # Prefer graph receipts when snapshot list empty.
        if not receipts and self.graph.completeness_receipts:
            receipts = self.graph.completeness_receipts
        receipts = tuple(sorted(receipts, key=lambda r: r.receipt_id))
        object.__setattr__(self, "completeness_receipts", receipts)
        object.__setattr__(
            self,
            "covered_providers",
            _unique_ids(self.covered_providers, "covered_providers"),
        )
        object.__setattr__(
            self, "covered_assets", _unique_ids(self.covered_assets, "covered_assets")
        )
        object.__setattr__(
            self, "covered_chains", _unique_ids(self.covered_chains, "covered_chains")
        )
        object.__setattr__(
            self,
            "covered_ranges",
            _sequence_of(
                self.covered_ranges,
                LedgerCoordinate,
                "covered_ranges",
                from_dict=LedgerCoordinate.from_dict,
            ),
        )
        object.__setattr__(
            self,
            "missing_ranges",
            _sequence_of(
                self.missing_ranges,
                LedgerCoordinate,
                "missing_ranges",
                from_dict=LedgerCoordinate.from_dict,
            ),
        )
        object.__setattr__(
            self, "created_at", _text(self.created_at, "created_at", allow_empty=True)
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def graph_digest(self) -> str:
        return self.graph.identity.digest

    @property
    def graph_cid(self) -> str:
        return self.graph.identity.cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "completeness": self.completeness.value,
            "completeness_receipts": [
                r.to_dict() for r in self.completeness_receipts
            ],
            "covered_assets": list(self.covered_assets),
            "covered_chains": list(self.covered_chains),
            "covered_providers": list(self.covered_providers),
            "covered_ranges": [c.to_dict() for c in self.covered_ranges],
            "created_at": self.created_at,
            "graph": self.graph.to_dict(),
            "graph_cid": self.graph_cid,
            "graph_digest": self.graph_digest,
            "missing_ranges": [c.to_dict() for c in self.missing_ranges],
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GraphSnapshot":
        value = _as_mapping(value, "GraphSnapshot")
        _known_fields(
            value,
            frozenset(
                {
                    "snapshot_id",
                    "graph",
                    "completeness",
                    "completeness_receipts",
                    "covered_providers",
                    "covered_assets",
                    "covered_chains",
                    "covered_ranges",
                    "missing_ranges",
                    "created_at",
                    "attributes",
                    "schema_version",
                    # Identity fields are derived; accept and ignore on input.
                    "graph_digest",
                    "graph_cid",
                }
            ),
            "GraphSnapshot",
        )
        return cls(
            snapshot_id=value.get("snapshot_id", ""),
            graph=CryptoFlowGraph.from_dict(_as_mapping(value.get("graph", {}), "graph")),
            completeness=value.get("completeness", CompletenessStatus.UNKNOWN.value),
            completeness_receipts=tuple(
                CompletenessReceipt.from_dict(item)
                for item in value.get("completeness_receipts", ())
            ),
            covered_providers=tuple(value.get("covered_providers", ())),
            covered_assets=tuple(value.get("covered_assets", ())),
            covered_chains=tuple(value.get("covered_chains", ())),
            covered_ranges=tuple(
                LedgerCoordinate.from_dict(item)
                for item in value.get("covered_ranges", ())
            ),
            missing_ranges=tuple(
                LedgerCoordinate.from_dict(item)
                for item in value.get("missing_ranges", ())
            ),
            created_at=value.get("created_at", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_FLOWS_SNAPSHOT_SCHEMA_VERSION
            ),
        )

    def canonical_bytes(self) -> bytes:
        payload = self.to_dict()
        # Exclude derived identity strings from content hash preimage to avoid
        # circular dependency; graph content is already embedded.
        payload.pop("graph_digest", None)
        payload.pop("graph_cid", None)
        return canonical_json_bytes(
            payload, collection_schema=GRAPH_SNAPSHOT_COLLECTION_SCHEMA
        )

    @property
    def identity(self) -> CanonicalIdentity:
        payload = self.to_dict()
        payload.pop("graph_digest", None)
        payload.pop("graph_cid", None)
        return crypto_ir_identity(
            payload,
            schema_version=self.schema_version,
            domain=f"{CRYPTO_FLOWS_DOMAIN}.snapshot",
            collection_schema=GRAPH_SNAPSHOT_COLLECTION_SCHEMA,
        )


def merge_provider_ids(*groups: Iterable[str]) -> tuple[str, ...]:
    """Deterministic unique provider id merge."""
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for item in group:
            ident = _identifier(item, "provider_id")
            if ident not in seen:
                seen.add(ident)
                ordered.append(ident)
    return tuple(sorted(ordered))


__all__ = [
    "CRYPTO_FLOWS_DOMAIN",
    "CRYPTO_FLOWS_EDGE_SCHEMA_VERSION",
    "CRYPTO_FLOWS_NODE_SCHEMA_VERSION",
    "CRYPTO_FLOWS_SCHEMA_VERSION",
    "CRYPTO_FLOWS_SNAPSHOT_SCHEMA_VERSION",
    "AmbiguityKind",
    "CompletenessReceipt",
    "CompletenessStatus",
    "CryptoFlowGraph",
    "CryptoFlowValidationError",
    "DerivationMethod",
    "EdgeKind",
    "ExactAmount",
    "FinalityStatus",
    "FlowDirection",
    "FlowEdge",
    "FlowNode",
    "GraphPlane",
    "GraphSnapshot",
    "LedgerCoordinate",
    "LedgerModel",
    "NodeKind",
    "RetractionStatus",
    "ValidityWindow",
    "assert_ledger_model_chain_correct",
    "default_ledger_model",
    "merge_provider_ids",
]
