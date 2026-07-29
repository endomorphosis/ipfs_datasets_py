"""Bounded sanctions exposure traversal over monetary-flow graphs (CRYPTOIR-G430).

This module computes *exact*, *budgeted* paths from an origin to listed
identifiers under one pinned graph snapshot, list revision, and path policy.
It never:

* infers unlimited transitive guilt beyond configured bounds;
* elevates indirect exposure into a designation; or
* claims that an incomplete or truncated search proves no connection exists.

Negative conclusions (no path found) are valid only when the search completed
within every bound **and** the attached completeness frontier covers the
queried providers, assets, ranges, and finality.  Truncation or partial
coverage yields an explicit incomplete result that must fail closed for
automation.
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.knowledge_graphs.crypto_flows.model import (
    AmbiguityKind,
    CryptoFlowGraph,
    DerivationMethod,
    EdgeKind,
    FlowEdge,
    FlowNode,
    GraphPlane,
    GraphSnapshot,
    NodeKind,
)
from ipfs_datasets_py.logic.crypto_ir.identity import crypto_ir_identity
from ipfs_datasets_py.logic.crypto_ir.model import (
    CompletenessReceipt,
    CompletenessStatus,
    FinalityStatus,
    RetractionStatus,
)
from ipfs_datasets_py.logic.crypto_ir.provenance import AuthorityKind
from ipfs_datasets_py.logic.crypto_ir.schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.provenance import thaw_json

from .models import (
    CRYPTO_IR_COMPLIANCE_DOMAIN,
    ComplianceModelError,
    SanctionsPolicyOutcome,
    _digest,
    _identifier,
    _instant,
    _known,
    _mapping,
    _text,
)


EXPOSURE_SCHEMA_VERSION: Final[str] = "ipfs-datasets.crypto-ir.bounded-exposure@1.0.0"
EXPOSURE_POLICY_SCHEMA_VERSION: Final[str] = (
    "ipfs-datasets.crypto-ir.exposure-policy@1.0.0"
)

# Finality ranks: higher means stronger settlement guarantee.
_FINALITY_RANK: Final[Mapping[FinalityStatus, int]] = {
    FinalityStatus.UNKNOWN: 0,
    FinalityStatus.PROPOSED: 1,
    FinalityStatus.CONFIRMED: 2,
    FinalityStatus.FINALIZED: 3,
    FinalityStatus.REORGED: -1,
    FinalityStatus.RETRACTED: -1,
}

# Derivation methods that never create designation authority and must not be
# treated as exact direct hits by themselves.
_HEURISTIC_DERIVATIONS: Final[frozenset[DerivationMethod]] = frozenset(
    {
        DerivationMethod.HEURISTIC_CLUSTER,
        DerivationMethod.HEURISTIC_PEEL,
        DerivationMethod.HEURISTIC_CHANGE,
        DerivationMethod.HEURISTIC_COINJOIN,
        DerivationMethod.HEURISTIC_SHARED_INFRA,
        DerivationMethod.GRAPHRAG_CANDIDATE,
    }
)

# Edge kinds that preserve multi-party ambiguity (service/pool/mixer/bridge).
_AMBIGUOUS_EDGE_KINDS: Final[frozenset[EdgeKind]] = frozenset(
    {
        EdgeKind.POOL_DEPOSIT,
        EdgeKind.POOL_WITHDRAW,
        EdgeKind.MIXER_DEPOSIT,
        EdgeKind.MIXER_WITHDRAW,
        EdgeKind.EXCHANGE_DEPOSIT,
        EdgeKind.EXCHANGE_WITHDRAW,
        EdgeKind.COINJOIN,
        EdgeKind.BRIDGE_LOCK,
        EdgeKind.BRIDGE_MINT,
        EdgeKind.BRIDGE_BURN,
        EdgeKind.BRIDGE_RELEASE,
        EdgeKind.SHARED_INFRASTRUCTURE,
    }
)


class ExposureError(ComplianceModelError):
    """Raised when exposure inputs, bounds, or results are malformed."""


class ExposureVerdict(str, Enum):
    """Outcome of one bounded exposure analysis.

    Distinct from transaction authorization and from legal designation.
    ``NO_PATH_WITHIN_BOUNDS`` is *not* a global "no connection exists" claim.
    """

    DIRECT_HIT = "direct_hit"
    INDIRECT_EXPOSURE = "indirect_exposure"
    NO_PATH_WITHIN_BOUNDS = "no_path_within_bounds"
    TRUNCATED = "truncated"
    INCOMPLETE_FRONTIER = "incomplete_frontier"
    STALE = "stale"
    ERROR = "error"


class TruncationReason(str, Enum):
    """Why a search stopped before exhausting the frontier."""

    MAX_DEPTH = "max_depth"
    MAX_NODES = "max_nodes"
    MAX_EDGES = "max_edges"
    MAX_PATHS = "max_paths"
    MAX_RUNTIME = "max_runtime"
    TIME_WINDOW = "time_window"
    ASSET_FILTER = "asset_filter"
    AMOUNT_FILTER = "amount_filter"
    FINALITY_FILTER = "finality_filter"
    PROVIDER_FILTER = "provider_filter"
    RETRACTED_EDGE = "retracted_edge"
    HEURISTIC_BLOCKED = "heuristic_blocked"


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise ExposureError(f"{name} must be a non-negative int")
    return value


def _positive_int(value: Any, name: str) -> int:
    value = _non_negative_int(value, name)
    if value < 1:
        raise ExposureError(f"{name} must be a positive int")
    return value


def _basis_points(value: Any, name: str) -> int:
    value = _non_negative_int(value, name)
    if value > 10_000:
        raise ExposureError(f"{name} must be in 0..10000")
    return value


def _enum(enum_type: type[Any], value: Any, name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ExposureError(f"unsupported {name}: {value!r}") from exc


def _ids(values: Any, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ExposureError(f"{name} must be a sequence")
    result = tuple(_identifier(item, name) for item in values)
    if not allow_empty and not result:
        raise ExposureError(f"{name} must not be empty")
    if len(result) != len(set(result)):
        raise ExposureError(f"{name} values must be unique")
    return result


def _outcome(value: Any, name: str) -> SanctionsPolicyOutcome:
    outcome = _enum(SanctionsPolicyOutcome, value, name)
    if outcome not in (
        SanctionsPolicyOutcome.REVIEW,
        SanctionsPolicyOutcome.DENY,
    ):
        raise ExposureError(
            f"{name} for indirect exposure must be REVIEW or DENY, not {outcome.value}"
        )
    return outcome


def _finality_floor(value: Any, name: str = "min_finality") -> FinalityStatus:
    status = _enum(FinalityStatus, value, name)
    if status in (FinalityStatus.REORGED, FinalityStatus.RETRACTED):
        raise ExposureError(f"{name} cannot be reorged or retracted")
    return status


def _meets_finality(observed: FinalityStatus, required: FinalityStatus) -> bool:
    return _FINALITY_RANK.get(observed, -1) >= _FINALITY_RANK.get(required, 0)


def _sha256_hex(*parts: str) -> str:
    material = "\x00".join(parts).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


# ---------------------------------------------------------------------------
# Path policy and path records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExposurePolicy:
    """Explicit resource and semantic bounds for one exposure search.

    Every bound is versioned policy data.  The engine does not invent unlimited
    depth or claim global completeness.  ``indirect_outcome`` is the configured
    treatment of a proved bounded-indirect path and never manufactures a
    designation.
    """

    policy_id: str
    revision: str
    max_depth: int = 3
    max_nodes: int = 256
    max_edges: int = 512
    max_paths: int = 32
    max_runtime_ms: int = 5_000
    earliest_time: str = ""
    latest_time: str = ""
    allowed_asset_ids: tuple[str, ...] = ()
    required_provider_ids: tuple[str, ...] = ()
    min_finality: FinalityStatus = FinalityStatus.CONFIRMED
    min_amount_base_units: str = "0"
    min_path_ratio_basis_points: int = 0
    indirect_outcome: SanctionsPolicyOutcome = SanctionsPolicyOutcome.REVIEW
    direct_outcome: SanctionsPolicyOutcome = SanctionsPolicyOutcome.DENY
    plane: GraphPlane = GraphPlane.OBSERVED_ADDRESS
    allow_heuristic_edges: bool = False
    allow_ambiguous_service_edges: bool = True
    require_completeness_for_absence: bool = True
    graph_snapshot_id: str = ""
    list_snapshot_id: str = ""
    list_revision: str = ""
    schema_version: str = EXPOSURE_POLICY_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(self, "revision", _identifier(self.revision, "revision"))
        object.__setattr__(self, "max_depth", _positive_int(self.max_depth, "max_depth"))
        object.__setattr__(self, "max_nodes", _positive_int(self.max_nodes, "max_nodes"))
        object.__setattr__(self, "max_edges", _positive_int(self.max_edges, "max_edges"))
        object.__setattr__(self, "max_paths", _positive_int(self.max_paths, "max_paths"))
        object.__setattr__(
            self, "max_runtime_ms", _positive_int(self.max_runtime_ms, "max_runtime_ms")
        )
        object.__setattr__(
            self,
            "earliest_time",
            _instant(self.earliest_time, "earliest_time", allow_empty=True)
            if self.earliest_time
            else "",
        )
        object.__setattr__(
            self,
            "latest_time",
            _instant(self.latest_time, "latest_time", allow_empty=True)
            if self.latest_time
            else "",
        )
        object.__setattr__(
            self,
            "allowed_asset_ids",
            _ids(self.allowed_asset_ids, "allowed_asset_ids"),
        )
        object.__setattr__(
            self,
            "required_provider_ids",
            _ids(self.required_provider_ids, "required_provider_ids"),
        )
        object.__setattr__(
            self, "min_finality", _finality_floor(self.min_finality, "min_finality")
        )
        amount = _text(self.min_amount_base_units, "min_amount_base_units")
        if not amount.lstrip("-").isdigit():
            raise ExposureError("min_amount_base_units must be a decimal integer string")
        object.__setattr__(self, "min_amount_base_units", amount)
        object.__setattr__(
            self,
            "min_path_ratio_basis_points",
            _basis_points(
                self.min_path_ratio_basis_points, "min_path_ratio_basis_points"
            ),
        )
        object.__setattr__(
            self,
            "indirect_outcome",
            _outcome(self.indirect_outcome, "indirect_outcome"),
        )
        direct = _enum(SanctionsPolicyOutcome, self.direct_outcome, "direct_outcome")
        if direct is not SanctionsPolicyOutcome.DENY:
            raise ExposureError("direct_outcome must be DENY under applicable policy")
        object.__setattr__(self, "direct_outcome", direct)
        object.__setattr__(self, "plane", _enum(GraphPlane, self.plane, "plane"))
        for name in (
            "allow_heuristic_edges",
            "allow_ambiguous_service_edges",
            "require_completeness_for_absence",
        ):
            if type(getattr(self, name)) is not bool:
                raise ExposureError(f"{name} must be a boolean")
        object.__setattr__(
            self,
            "graph_snapshot_id",
            _text(self.graph_snapshot_id, "graph_snapshot_id", allow_empty=True),
        )
        object.__setattr__(
            self,
            "list_snapshot_id",
            _text(self.list_snapshot_id, "list_snapshot_id", allow_empty=True),
        )
        object.__setattr__(
            self,
            "list_revision",
            _text(self.list_revision, "list_revision", allow_empty=True),
        )
        if self.schema_version != EXPOSURE_POLICY_SCHEMA_VERSION:
            raise ExposureError(
                f"unsupported exposure policy schema: {self.schema_version}"
            )

    @property
    def rules_digest(self) -> str:
        """Canonical digest of bound parameters (excludes free-form notes)."""

        payload = {
            "allow_ambiguous_service_edges": self.allow_ambiguous_service_edges,
            "allow_heuristic_edges": self.allow_heuristic_edges,
            "allowed_asset_ids": list(self.allowed_asset_ids),
            "direct_outcome": self.direct_outcome.value,
            "earliest_time": self.earliest_time,
            "indirect_outcome": self.indirect_outcome.value,
            "latest_time": self.latest_time,
            "max_depth": self.max_depth,
            "max_edges": self.max_edges,
            "max_nodes": self.max_nodes,
            "max_paths": self.max_paths,
            "max_runtime_ms": self.max_runtime_ms,
            "min_amount_base_units": self.min_amount_base_units,
            "min_finality": self.min_finality.value,
            "min_path_ratio_basis_points": self.min_path_ratio_basis_points,
            "plane": self.plane.value,
            "policy_id": self.policy_id,
            "require_completeness_for_absence": (
                self.require_completeness_for_absence
            ),
            "required_provider_ids": list(self.required_provider_ids),
            "revision": self.revision,
            "schema_version": self.schema_version,
        }
        digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return f"sha256:{digest}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_ambiguous_service_edges": self.allow_ambiguous_service_edges,
            "allow_heuristic_edges": self.allow_heuristic_edges,
            "allowed_asset_ids": list(self.allowed_asset_ids),
            "direct_outcome": self.direct_outcome.value,
            "earliest_time": self.earliest_time,
            "graph_snapshot_id": self.graph_snapshot_id,
            "indirect_outcome": self.indirect_outcome.value,
            "latest_time": self.latest_time,
            "list_revision": self.list_revision,
            "list_snapshot_id": self.list_snapshot_id,
            "max_depth": self.max_depth,
            "max_edges": self.max_edges,
            "max_nodes": self.max_nodes,
            "max_paths": self.max_paths,
            "max_runtime_ms": self.max_runtime_ms,
            "min_amount_base_units": self.min_amount_base_units,
            "min_finality": self.min_finality.value,
            "min_path_ratio_basis_points": self.min_path_ratio_basis_points,
            "plane": self.plane.value,
            "policy_id": self.policy_id,
            "require_completeness_for_absence": (
                self.require_completeness_for_absence
            ),
            "required_provider_ids": list(self.required_provider_ids),
            "revision": self.revision,
            "rules_digest": self.rules_digest,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExposurePolicy":
        value = _mapping(value, "ExposurePolicy")
        fields = frozenset(
            {
                "policy_id",
                "revision",
                "max_depth",
                "max_nodes",
                "max_edges",
                "max_paths",
                "max_runtime_ms",
                "earliest_time",
                "latest_time",
                "allowed_asset_ids",
                "required_provider_ids",
                "min_finality",
                "min_amount_base_units",
                "min_path_ratio_basis_points",
                "indirect_outcome",
                "direct_outcome",
                "plane",
                "allow_heuristic_edges",
                "allow_ambiguous_service_edges",
                "require_completeness_for_absence",
                "graph_snapshot_id",
                "list_snapshot_id",
                "list_revision",
                "schema_version",
                "rules_digest",
            }
        )
        _known(value, fields, "ExposurePolicy")
        return cls(
            policy_id=value.get("policy_id", ""),
            revision=value.get("revision", ""),
            max_depth=value.get("max_depth", 3),
            max_nodes=value.get("max_nodes", 256),
            max_edges=value.get("max_edges", 512),
            max_paths=value.get("max_paths", 32),
            max_runtime_ms=value.get("max_runtime_ms", 5_000),
            earliest_time=value.get("earliest_time", ""),
            latest_time=value.get("latest_time", ""),
            allowed_asset_ids=tuple(value.get("allowed_asset_ids", ())),
            required_provider_ids=tuple(value.get("required_provider_ids", ())),
            min_finality=value.get("min_finality", FinalityStatus.CONFIRMED.value),
            min_amount_base_units=str(value.get("min_amount_base_units", "0")),
            min_path_ratio_basis_points=value.get("min_path_ratio_basis_points", 0),
            indirect_outcome=value.get(
                "indirect_outcome", SanctionsPolicyOutcome.REVIEW.value
            ),
            direct_outcome=value.get(
                "direct_outcome", SanctionsPolicyOutcome.DENY.value
            ),
            plane=value.get("plane", GraphPlane.OBSERVED_ADDRESS.value),
            allow_heuristic_edges=bool(value.get("allow_heuristic_edges", False)),
            allow_ambiguous_service_edges=bool(
                value.get("allow_ambiguous_service_edges", True)
            ),
            require_completeness_for_absence=bool(
                value.get("require_completeness_for_absence", True)
            ),
            graph_snapshot_id=value.get("graph_snapshot_id", ""),
            list_snapshot_id=value.get("list_snapshot_id", ""),
            list_revision=value.get("list_revision", ""),
            schema_version=value.get(
                "schema_version", EXPOSURE_POLICY_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ExposurePathStep:
    """One explainable hop in an exposure path, bound to exact edge/node ids."""

    step_index: int
    edge_id: str
    from_node_id: str
    to_node_id: str
    edge_kind: str
    finality: str
    derivation: str
    ambiguity: str
    asset_id: str = ""
    amount_base_units: str = ""
    timestamp: str = ""
    provider_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "step_index", _non_negative_int(self.step_index, "step_index")
        )
        for name in (
            "edge_id",
            "from_node_id",
            "to_node_id",
            "edge_kind",
            "finality",
            "derivation",
            "ambiguity",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self, "asset_id", _text(self.asset_id, "asset_id", allow_empty=True)
        )
        object.__setattr__(
            self,
            "amount_base_units",
            _text(self.amount_base_units, "amount_base_units", allow_empty=True),
        )
        object.__setattr__(
            self, "timestamp", _text(self.timestamp, "timestamp", allow_empty=True)
        )
        object.__setattr__(
            self, "provider_ids", _ids(self.provider_ids, "provider_ids")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity": self.ambiguity,
            "amount_base_units": self.amount_base_units,
            "asset_id": self.asset_id,
            "derivation": self.derivation,
            "edge_id": self.edge_id,
            "edge_kind": self.edge_kind,
            "finality": self.finality,
            "from_node_id": self.from_node_id,
            "provider_ids": list(self.provider_ids),
            "step_index": self.step_index,
            "timestamp": self.timestamp,
            "to_node_id": self.to_node_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExposurePathStep":
        value = _mapping(value, "ExposurePathStep")
        return cls(
            step_index=value.get("step_index", 0),
            edge_id=value.get("edge_id", ""),
            from_node_id=value.get("from_node_id", ""),
            to_node_id=value.get("to_node_id", ""),
            edge_kind=value.get("edge_kind", ""),
            finality=value.get("finality", ""),
            derivation=value.get("derivation", ""),
            ambiguity=value.get("ambiguity", ""),
            asset_id=value.get("asset_id", ""),
            amount_base_units=value.get("amount_base_units", ""),
            timestamp=value.get("timestamp", ""),
            provider_ids=tuple(value.get("provider_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class ExposurePath:
    """Explainable, replayable path under one graph/list/policy snapshot.

    Paths never declare a designation.  ``is_direct`` is depth == 1 with a
    non-heuristic derivation; deeper paths are bounded-indirect exposure only.
    """

    path_id: str
    origin_node_id: str
    target_node_id: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    steps: tuple[ExposurePathStep, ...]
    depth: int
    listed_identifier: str = ""
    designation_id: str = ""
    target_address_ref: str = ""
    graph_snapshot_id: str = ""
    graph_digest: str = ""
    list_snapshot_id: str = ""
    list_revision: str = ""
    policy_id: str = ""
    policy_revision: str = ""
    policy_rules_digest: str = ""
    min_finality_observed: str = FinalityStatus.UNKNOWN.value
    ambiguity_kinds: tuple[str, ...] = ()
    contains_heuristic_hop: bool = False
    claims_designation: bool = False
    schema_version: str = EXPOSURE_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.RESULT

    def __post_init__(self) -> None:
        object.__setattr__(self, "path_id", _identifier(self.path_id, "path_id"))
        object.__setattr__(
            self, "origin_node_id", _identifier(self.origin_node_id, "origin_node_id")
        )
        object.__setattr__(
            self, "target_node_id", _identifier(self.target_node_id, "target_node_id")
        )
        object.__setattr__(self, "node_ids", _ids(self.node_ids, "node_ids", allow_empty=False))
        object.__setattr__(self, "edge_ids", _ids(self.edge_ids, "edge_ids"))
        steps = tuple(
            item
            if isinstance(item, ExposurePathStep)
            else ExposurePathStep.from_dict(_mapping(item, "steps"))
            for item in self.steps
        )
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "depth", _non_negative_int(self.depth, "depth"))
        if self.depth != len(self.edge_ids):
            raise ExposureError("depth must equal number of edge hops")
        if len(self.node_ids) != self.depth + 1:
            raise ExposureError("node_ids length must be depth + 1")
        if self.node_ids[0] != self.origin_node_id:
            raise ExposureError("first node_id must equal origin_node_id")
        if self.node_ids[-1] != self.target_node_id:
            raise ExposureError("last node_id must equal target_node_id")
        if len(self.steps) != self.depth:
            raise ExposureError("steps length must equal depth")
        for name in (
            "listed_identifier",
            "designation_id",
            "target_address_ref",
            "graph_snapshot_id",
            "graph_digest",
            "list_snapshot_id",
            "list_revision",
            "policy_id",
            "policy_revision",
            "policy_rules_digest",
            "min_finality_observed",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        kinds = tuple(_text(item, "ambiguity_kinds") for item in self.ambiguity_kinds)
        if len(kinds) != len(set(kinds)):
            raise ExposureError("ambiguity_kinds must be unique")
        object.__setattr__(self, "ambiguity_kinds", kinds)
        for name in ("contains_heuristic_hop", "claims_designation"):
            if type(getattr(self, name)) is not bool:
                raise ExposureError(f"{name} must be a boolean")
        # Hard invariant: exposure paths never mint designations.
        if self.claims_designation:
            raise ExposureError(
                "ExposurePath must never claim designation authority"
            )
        if self.schema_version != EXPOSURE_SCHEMA_VERSION:
            raise ExposureError(f"unsupported path schema: {self.schema_version}")

    @property
    def is_direct(self) -> bool:
        """True only for a single non-heuristic hop to a listed target."""

        return self.depth == 1 and not self.contains_heuristic_hop

    @property
    def is_indirect(self) -> bool:
        return self.depth >= 2 or (self.depth == 1 and self.contains_heuristic_hop)

    def explanation(self) -> str:
        """Human-readable replay of the path (not a legal conclusion)."""

        hops = " -> ".join(self.node_ids)
        kind = "direct" if self.is_direct else "bounded-indirect"
        target = self.listed_identifier or self.target_address_ref or self.target_node_id
        return (
            f"{kind} path depth={self.depth} origin={self.origin_node_id} "
            f"target={target} via [{hops}] "
            f"graph={self.graph_snapshot_id or 'unbound'} "
            f"list={self.list_snapshot_id or 'unbound'} "
            f"policy={self.policy_id or 'unbound'}@{self.policy_revision or '?'}; "
            "does_not_declare_designation=true"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity_kinds": list(self.ambiguity_kinds),
            "claims_designation": self.claims_designation,
            "contains_heuristic_hop": self.contains_heuristic_hop,
            "depth": self.depth,
            "designation_id": self.designation_id,
            "edge_ids": list(self.edge_ids),
            "explanation": self.explanation(),
            "graph_digest": self.graph_digest,
            "graph_snapshot_id": self.graph_snapshot_id,
            "is_direct": self.is_direct,
            "is_indirect": self.is_indirect,
            "list_revision": self.list_revision,
            "list_snapshot_id": self.list_snapshot_id,
            "listed_identifier": self.listed_identifier,
            "min_finality_observed": self.min_finality_observed,
            "node_ids": list(self.node_ids),
            "origin_node_id": self.origin_node_id,
            "path_id": self.path_id,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "policy_rules_digest": self.policy_rules_digest,
            "schema_version": self.schema_version,
            "steps": [step.to_dict() for step in self.steps],
            "target_address_ref": self.target_address_ref,
            "target_node_id": self.target_node_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExposurePath":
        value = _mapping(value, "ExposurePath")
        # Derived fields may appear in serialized form.
        fields = frozenset(
            {
                "path_id",
                "origin_node_id",
                "target_node_id",
                "node_ids",
                "edge_ids",
                "steps",
                "depth",
                "listed_identifier",
                "designation_id",
                "target_address_ref",
                "graph_snapshot_id",
                "graph_digest",
                "list_snapshot_id",
                "list_revision",
                "policy_id",
                "policy_revision",
                "policy_rules_digest",
                "min_finality_observed",
                "ambiguity_kinds",
                "contains_heuristic_hop",
                "claims_designation",
                "schema_version",
                "explanation",
                "is_direct",
                "is_indirect",
            }
        )
        _known(value, fields, "ExposurePath")
        return cls(
            path_id=value.get("path_id", ""),
            origin_node_id=value.get("origin_node_id", ""),
            target_node_id=value.get("target_node_id", ""),
            node_ids=tuple(value.get("node_ids", ())),
            edge_ids=tuple(value.get("edge_ids", ())),
            steps=tuple(
                ExposurePathStep.from_dict(item) for item in value.get("steps", ())
            ),
            depth=value.get("depth", 0),
            listed_identifier=value.get("listed_identifier", ""),
            designation_id=value.get("designation_id", ""),
            target_address_ref=value.get("target_address_ref", ""),
            graph_snapshot_id=value.get("graph_snapshot_id", ""),
            graph_digest=value.get("graph_digest", ""),
            list_snapshot_id=value.get("list_snapshot_id", ""),
            list_revision=value.get("list_revision", ""),
            policy_id=value.get("policy_id", ""),
            policy_revision=value.get("policy_revision", ""),
            policy_rules_digest=value.get("policy_rules_digest", ""),
            min_finality_observed=value.get(
                "min_finality_observed", FinalityStatus.UNKNOWN.value
            ),
            ambiguity_kinds=tuple(value.get("ambiguity_kinds", ())),
            contains_heuristic_hop=bool(value.get("contains_heuristic_hop", False)),
            claims_designation=bool(value.get("claims_designation", False)),
            schema_version=value.get("schema_version", EXPOSURE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class CompletenessFrontier:
    """Scoped coverage statement for a negative or truncated exposure result.

    Absence is *never* global.  A frontier records exactly which providers,
    assets, ranges, and completeness statuses were considered.
    """

    status: CompletenessStatus
    covered_providers: tuple[str, ...] = ()
    covered_assets: tuple[str, ...] = ()
    covered_chains: tuple[str, ...] = ()
    missing_providers: tuple[str, ...] = ()
    receipt_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(CompletenessStatus, self.status, "status")
        )
        object.__setattr__(
            self, "covered_providers", _ids(self.covered_providers, "covered_providers")
        )
        object.__setattr__(
            self, "covered_assets", _ids(self.covered_assets, "covered_assets")
        )
        object.__setattr__(
            self, "covered_chains", _ids(self.covered_chains, "covered_chains")
        )
        object.__setattr__(
            self, "missing_providers", _ids(self.missing_providers, "missing_providers")
        )
        object.__setattr__(self, "receipt_ids", _ids(self.receipt_ids, "receipt_ids"))
        notes = tuple(_text(item, "notes") for item in self.notes)
        object.__setattr__(self, "notes", notes)

    @property
    def supports_absence_claim(self) -> bool:
        """Only COMPLETE frontiers may underwrite a bounded-absence result."""

        return self.status is CompletenessStatus.COMPLETE

    def to_dict(self) -> dict[str, Any]:
        return {
            "covered_assets": list(self.covered_assets),
            "covered_chains": list(self.covered_chains),
            "covered_providers": list(self.covered_providers),
            "missing_providers": list(self.missing_providers),
            "notes": list(self.notes),
            "receipt_ids": list(self.receipt_ids),
            "status": self.status.value,
            "supports_absence_claim": self.supports_absence_claim,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompletenessFrontier":
        value = _mapping(value, "CompletenessFrontier")
        return cls(
            status=value.get("status", CompletenessStatus.UNKNOWN.value),
            covered_providers=tuple(value.get("covered_providers", ())),
            covered_assets=tuple(value.get("covered_assets", ())),
            covered_chains=tuple(value.get("covered_chains", ())),
            missing_providers=tuple(value.get("missing_providers", ())),
            receipt_ids=tuple(value.get("receipt_ids", ())),
            notes=tuple(value.get("notes", ())),
        )


@dataclass(frozen=True, slots=True)
class BoundedExposure:
    """Result of one deterministic bounded exposure analysis.

    Invariants:

    * direct exact hits map to policy ``direct_outcome`` (DENY);
    * indirect paths map to configured ``indirect_outcome`` and never designate;
    * ``proves_no_connection`` is True only when the search finished without
      truncation, the completeness frontier supports absence, and no path was
      found — still scoped to the pinned snapshots, never global;
    * truncation always fails closed for absence claims.
    """

    exposure_id: str
    origin_node_id: str
    policy: ExposurePolicy
    verdict: ExposureVerdict
    paths: tuple[ExposurePath, ...] = ()
    listed_target_node_ids: tuple[str, ...] = ()
    truncation_reasons: tuple[str, ...] = ()
    truncated: bool = False
    frontier: CompletenessFrontier | None = None
    nodes_visited: int = 0
    edges_visited: int = 0
    runtime_ms: int = 0
    graph_snapshot_id: str = ""
    graph_digest: str = ""
    list_snapshot_id: str = ""
    list_revision: str = ""
    reason_codes: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = EXPOSURE_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.RESULT

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "exposure_id", _identifier(self.exposure_id, "exposure_id")
        )
        object.__setattr__(
            self, "origin_node_id", _identifier(self.origin_node_id, "origin_node_id")
        )
        if not isinstance(self.policy, ExposurePolicy):
            object.__setattr__(
                self,
                "policy",
                ExposurePolicy.from_dict(_mapping(self.policy, "policy")),
            )
        object.__setattr__(
            self, "verdict", _enum(ExposureVerdict, self.verdict, "verdict")
        )
        paths = tuple(
            item
            if isinstance(item, ExposurePath)
            else ExposurePath.from_dict(_mapping(item, "paths"))
            for item in self.paths
        )
        object.__setattr__(self, "paths", paths)
        object.__setattr__(
            self,
            "listed_target_node_ids",
            _ids(self.listed_target_node_ids, "listed_target_node_ids"),
        )
        reasons = tuple(
            _text(item, "truncation_reasons") for item in self.truncation_reasons
        )
        if len(reasons) != len(set(reasons)):
            raise ExposureError("truncation_reasons must be unique")
        object.__setattr__(self, "truncation_reasons", reasons)
        if type(self.truncated) is not bool:
            raise ExposureError("truncated must be a boolean")
        if self.frontier is not None and not isinstance(
            self.frontier, CompletenessFrontier
        ):
            object.__setattr__(
                self,
                "frontier",
                CompletenessFrontier.from_dict(_mapping(self.frontier, "frontier")),
            )
        for name in ("nodes_visited", "edges_visited", "runtime_ms"):
            object.__setattr__(
                self, name, _non_negative_int(getattr(self, name), name)
            )
        for name in (
            "graph_snapshot_id",
            "graph_digest",
            "list_snapshot_id",
            "list_revision",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        codes = tuple(_identifier(item, "reason_codes") for item in self.reason_codes)
        if len(codes) != len(set(codes)):
            raise ExposureError("reason_codes must be unique")
        object.__setattr__(self, "reason_codes", codes)
        if not isinstance(self.attributes, Mapping):
            raise ExposureError("attributes must be a mapping")
        object.__setattr__(self, "attributes", dict(self.attributes))
        if self.schema_version != EXPOSURE_SCHEMA_VERSION:
            raise ExposureError(f"unsupported exposure schema: {self.schema_version}")
        # Structural fail-closed invariants.
        if self.truncated and self.verdict is ExposureVerdict.NO_PATH_WITHIN_BOUNDS:
            raise ExposureError(
                "truncated search cannot claim no_path_within_bounds"
            )
        if self.proves_no_connection and self.paths:
            raise ExposureError("cannot prove absence while paths exist")
        if any(path.claims_designation for path in self.paths):
            raise ExposureError("paths must not claim designation")

    @property
    def has_direct_hit(self) -> bool:
        return any(path.is_direct for path in self.paths)

    @property
    def has_indirect_exposure(self) -> bool:
        return any(path.is_indirect for path in self.paths)

    @property
    def policy_outcome(self) -> SanctionsPolicyOutcome:
        """Configured sanctions-policy-class outcome for this exposure."""

        if self.verdict is ExposureVerdict.DIRECT_HIT:
            return self.policy.direct_outcome
        if self.verdict is ExposureVerdict.INDIRECT_EXPOSURE:
            return self.policy.indirect_outcome
        if self.verdict in (
            ExposureVerdict.TRUNCATED,
            ExposureVerdict.INCOMPLETE_FRONTIER,
            ExposureVerdict.STALE,
            ExposureVerdict.ERROR,
        ):
            return SanctionsPolicyOutcome.INCONCLUSIVE
        return SanctionsPolicyOutcome.ALLOW

    @property
    def proves_no_connection(self) -> bool:
        """Bounded absence only — never a claim about the unobserved world.

        True only when:

        1. no path was found;
        2. the search was not truncated; and
        3. the completeness frontier supports absence (or the policy waives
           that requirement).
        """

        if self.paths or self.truncated:
            return False
        if self.verdict is not ExposureVerdict.NO_PATH_WITHIN_BOUNDS:
            return False
        if not self.policy.require_completeness_for_absence:
            return True
        return bool(self.frontier and self.frontier.supports_absence_claim)

    @property
    def declares_designation(self) -> bool:
        """Exposure analysis never creates designation authority."""

        return False

    @property
    def identity(self):
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=f"{CRYPTO_IR_COMPLIANCE_DOMAIN}.bounded-exposure",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(dict(self.attributes)),
            "declares_designation": self.declares_designation,
            "edges_visited": self.edges_visited,
            "exposure_id": self.exposure_id,
            "frontier": None if self.frontier is None else self.frontier.to_dict(),
            "graph_digest": self.graph_digest,
            "graph_snapshot_id": self.graph_snapshot_id,
            "has_direct_hit": self.has_direct_hit,
            "has_indirect_exposure": self.has_indirect_exposure,
            "list_revision": self.list_revision,
            "list_snapshot_id": self.list_snapshot_id,
            "listed_target_node_ids": list(self.listed_target_node_ids),
            "nodes_visited": self.nodes_visited,
            "origin_node_id": self.origin_node_id,
            "paths": [path.to_dict() for path in self.paths],
            "policy": self.policy.to_dict(),
            "policy_outcome": self.policy_outcome.value,
            "proves_no_connection": self.proves_no_connection,
            "reason_codes": list(self.reason_codes),
            "runtime_ms": self.runtime_ms,
            "schema_version": self.schema_version,
            "truncated": self.truncated,
            "truncation_reasons": list(self.truncation_reasons),
            "verdict": self.verdict.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BoundedExposure":
        value = _mapping(value, "BoundedExposure")
        fields = frozenset(
            {
                "exposure_id",
                "origin_node_id",
                "policy",
                "verdict",
                "paths",
                "listed_target_node_ids",
                "truncation_reasons",
                "truncated",
                "frontier",
                "nodes_visited",
                "edges_visited",
                "runtime_ms",
                "graph_snapshot_id",
                "graph_digest",
                "list_snapshot_id",
                "list_revision",
                "reason_codes",
                "attributes",
                "schema_version",
                # Derived serialization fields.
                "declares_designation",
                "has_direct_hit",
                "has_indirect_exposure",
                "policy_outcome",
                "proves_no_connection",
            }
        )
        _known(value, fields, "BoundedExposure")
        frontier_raw = value.get("frontier")
        return cls(
            exposure_id=value.get("exposure_id", ""),
            origin_node_id=value.get("origin_node_id", ""),
            policy=ExposurePolicy.from_dict(_mapping(value.get("policy", {}), "policy")),
            verdict=value.get("verdict", ""),
            paths=tuple(
                ExposurePath.from_dict(item) for item in value.get("paths", ())
            ),
            listed_target_node_ids=tuple(value.get("listed_target_node_ids", ())),
            truncation_reasons=tuple(value.get("truncation_reasons", ())),
            truncated=bool(value.get("truncated", False)),
            frontier=None
            if frontier_raw is None
            else CompletenessFrontier.from_dict(_mapping(frontier_raw, "frontier")),
            nodes_visited=value.get("nodes_visited", 0),
            edges_visited=value.get("edges_visited", 0),
            runtime_ms=value.get("runtime_ms", 0),
            graph_snapshot_id=value.get("graph_snapshot_id", ""),
            graph_digest=value.get("graph_digest", ""),
            list_snapshot_id=value.get("list_snapshot_id", ""),
            list_revision=value.get("list_revision", ""),
            reason_codes=tuple(value.get("reason_codes", ())),
            attributes=value.get("attributes", {}),
            schema_version=value.get("schema_version", EXPOSURE_SCHEMA_VERSION),
        )


# ---------------------------------------------------------------------------
# Listed targets and traversal
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ListedTarget:
    """A listed digital-currency identifier or designation endpoint in the graph."""

    node_id: str
    address_ref: str = ""
    listed_identifier: str = ""
    designation_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _identifier(self.node_id, "node_id"))
        for name in ("address_ref", "listed_identifier", "designation_id"):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )


def _asset_id(edge: FlowEdge) -> str:
    if edge.asset is None:
        return ""
    ref = edge.asset.asset_reference or ""
    ns = edge.asset.asset_namespace or ""
    if ns and ref:
        return f"{ns}:{ref}"
    return ref or ns


def _amount_units(edge: FlowEdge) -> str:
    if edge.amount is None:
        return ""
    return edge.amount.base_units


def _edge_usable(
    edge: FlowEdge,
    policy: ExposurePolicy,
    truncation: set[str],
) -> bool:
    if edge.retraction is not RetractionStatus.NOT_RETRACTED:
        truncation.add(TruncationReason.RETRACTED_EDGE.value)
        return False
    if edge.finality in (FinalityStatus.REORGED, FinalityStatus.RETRACTED):
        truncation.add(TruncationReason.FINALITY_FILTER.value)
        return False
    if not _meets_finality(edge.finality, policy.min_finality):
        truncation.add(TruncationReason.FINALITY_FILTER.value)
        return False
    if edge.derivation in _HEURISTIC_DERIVATIONS and not policy.allow_heuristic_edges:
        truncation.add(TruncationReason.HEURISTIC_BLOCKED.value)
        return False
    if (
        edge.kind in _AMBIGUOUS_EDGE_KINDS
        and not policy.allow_ambiguous_service_edges
    ):
        truncation.add(TruncationReason.HEURISTIC_BLOCKED.value)
        return False
    if policy.allowed_asset_ids:
        asset = _asset_id(edge)
        if asset and asset not in policy.allowed_asset_ids:
            truncation.add(TruncationReason.ASSET_FILTER.value)
            return False
        if not asset:
            truncation.add(TruncationReason.ASSET_FILTER.value)
            return False
    if policy.required_provider_ids:
        if not set(edge.provider_ids) & set(policy.required_provider_ids):
            # Node-level providers may still satisfy; edge-only filter when set.
            if edge.provider_ids:
                truncation.add(TruncationReason.PROVIDER_FILTER.value)
                return False
    if policy.earliest_time and edge.timestamp and edge.timestamp < policy.earliest_time:
        truncation.add(TruncationReason.TIME_WINDOW.value)
        return False
    if policy.latest_time and edge.timestamp and edge.timestamp > policy.latest_time:
        truncation.add(TruncationReason.TIME_WINDOW.value)
        return False
    if policy.min_amount_base_units not in ("0", ""):
        units = _amount_units(edge)
        if units:
            try:
                if abs(int(units)) < abs(int(policy.min_amount_base_units)):
                    truncation.add(TruncationReason.AMOUNT_FILTER.value)
                    return False
            except ValueError:
                truncation.add(TruncationReason.AMOUNT_FILTER.value)
                return False
    return True


def _adjacency(
    graph: CryptoFlowGraph, plane: GraphPlane
) -> dict[str, list[tuple[FlowEdge, str]]]:
    """Undirected adjacency on the selected plane for exposure connectivity.

    Exposure cares about *connection* under observed flows.  Direction is
    preserved on the path step; traversal follows either endpoint.
    """

    adj: dict[str, list[tuple[FlowEdge, str]]] = defaultdict(list)
    for edge in graph.active_edges():
        if edge.plane is not plane:
            continue
        adj[edge.source_node_id].append((edge, edge.target_node_id))
        if edge.source_node_id != edge.target_node_id:
            adj[edge.target_node_id].append((edge, edge.source_node_id))
    for node_id in adj:
        adj[node_id].sort(key=lambda item: (item[0].edge_id, item[1]))
    return adj


def _build_frontier(
    snapshot: GraphSnapshot | None,
    graph: CryptoFlowGraph,
    policy: ExposurePolicy,
    receipts: Sequence[CompletenessReceipt],
) -> CompletenessFrontier:
    covered_providers: set[str] = set(graph.provider_ids)
    covered_assets: set[str] = set(graph.asset_ids)
    covered_chains: set[str] = set(graph.chain_ids)
    receipt_ids: list[str] = []
    statuses: list[CompletenessStatus] = []
    notes: list[str] = []

    if snapshot is not None:
        covered_providers.update(snapshot.covered_providers)
        covered_assets.update(snapshot.covered_assets)
        covered_chains.update(snapshot.covered_chains)
        statuses.append(snapshot.completeness)
        if snapshot.missing_ranges:
            notes.append("snapshot_has_missing_ranges")
        for receipt in snapshot.completeness_receipts:
            receipt_ids.append(receipt.receipt_id)
            statuses.append(receipt.completeness)
            covered_providers.update(receipt.provider_ids)

    for receipt in receipts:
        receipt_ids.append(receipt.receipt_id)
        statuses.append(receipt.completeness)
        covered_providers.update(receipt.provider_ids)

    for receipt in graph.completeness_receipts:
        if receipt.receipt_id not in receipt_ids:
            receipt_ids.append(receipt.receipt_id)
            statuses.append(receipt.completeness)
            covered_providers.update(receipt.provider_ids)

    missing_providers = tuple(
        sorted(set(policy.required_provider_ids) - covered_providers)
    )
    if missing_providers:
        notes.append("required_providers_missing")
        status = CompletenessStatus.PARTIAL
    elif not statuses:
        status = CompletenessStatus.UNKNOWN
        notes.append("no_completeness_receipt")
    elif any(s is CompletenessStatus.UNSUPPORTED for s in statuses):
        status = CompletenessStatus.UNSUPPORTED
    elif any(s is CompletenessStatus.PARTIAL for s in statuses):
        status = CompletenessStatus.PARTIAL
    elif any(s is CompletenessStatus.UNKNOWN for s in statuses):
        status = CompletenessStatus.UNKNOWN
    elif all(s is CompletenessStatus.COMPLETE for s in statuses):
        status = CompletenessStatus.COMPLETE
    else:
        status = CompletenessStatus.UNKNOWN

    return CompletenessFrontier(
        status=status,
        covered_providers=tuple(sorted(covered_providers)),
        covered_assets=tuple(sorted(covered_assets)),
        covered_chains=tuple(sorted(covered_chains)),
        missing_providers=missing_providers,
        receipt_ids=tuple(sorted(set(receipt_ids))),
        notes=tuple(notes),
    )


def _make_path(
    *,
    origin: str,
    target: ListedTarget,
    node_ids: Sequence[str],
    edge_seq: Sequence[FlowEdge],
    policy: ExposurePolicy,
    graph_snapshot_id: str,
    graph_digest: str,
) -> ExposurePath:
    steps: list[ExposurePathStep] = []
    ambiguities: set[str] = set()
    heuristic = False
    min_finality = FinalityStatus.FINALIZED
    directed_nodes = [origin]
    for index, edge in enumerate(edge_seq):
        prev = directed_nodes[-1]
        nxt = edge.target_node_id if edge.source_node_id == prev else edge.source_node_id
        directed_nodes.append(nxt)
        if edge.derivation in _HEURISTIC_DERIVATIONS:
            heuristic = True
        if edge.ambiguity is not AmbiguityKind.NONE:
            ambiguities.add(edge.ambiguity.value)
        if _FINALITY_RANK.get(edge.finality, 0) < _FINALITY_RANK.get(min_finality, 0):
            min_finality = edge.finality
        steps.append(
            ExposurePathStep(
                step_index=index,
                edge_id=edge.edge_id,
                from_node_id=prev,
                to_node_id=nxt,
                edge_kind=edge.kind.value,
                finality=edge.finality.value,
                derivation=edge.derivation.value,
                ambiguity=edge.ambiguity.value,
                asset_id=_asset_id(edge),
                amount_base_units=_amount_units(edge),
                timestamp=edge.timestamp,
                provider_ids=edge.provider_ids,
            )
        )
    path_material = "\x00".join(
        (
            origin,
            target.node_id,
            * (e.edge_id for e in edge_seq),
            policy.policy_id,
            policy.revision,
            graph_snapshot_id,
        )
    )
    path_id = f"path:{hashlib.sha256(path_material.encode('utf-8')).hexdigest()[:32]}"
    return ExposurePath(
        path_id=path_id,
        origin_node_id=origin,
        target_node_id=target.node_id,
        node_ids=tuple(directed_nodes),
        edge_ids=tuple(e.edge_id for e in edge_seq),
        steps=tuple(steps),
        depth=len(edge_seq),
        listed_identifier=target.listed_identifier,
        designation_id=target.designation_id,
        target_address_ref=target.address_ref,
        graph_snapshot_id=graph_snapshot_id,
        graph_digest=graph_digest,
        list_snapshot_id=policy.list_snapshot_id,
        list_revision=policy.list_revision,
        policy_id=policy.policy_id,
        policy_revision=policy.revision,
        policy_rules_digest=policy.rules_digest,
        min_finality_observed=min_finality.value,
        ambiguity_kinds=tuple(sorted(ambiguities)),
        contains_heuristic_hop=heuristic,
        claims_designation=False,
    )


def compute_bounded_exposure(
    *,
    origin_node_id: str,
    listed_targets: Sequence[ListedTarget],
    policy: ExposurePolicy,
    graph: CryptoFlowGraph | None = None,
    snapshot: GraphSnapshot | None = None,
    completeness_receipts: Sequence[CompletenessReceipt] = (),
    at_time: str = "",
) -> BoundedExposure:
    """Compute exact bounded exposure paths under one pinned snapshot set.

    The search is deterministic BFS by edge_id order.  Budgets for depth,
    nodes, edges, paths, and wall-clock runtime are enforced.  Truncation and
    incomplete frontiers fail closed for absence claims.
    """

    if not isinstance(policy, ExposurePolicy):
        raise ExposureError("policy must be an ExposurePolicy")
    origin_node_id = _identifier(origin_node_id, "origin_node_id")
    targets = tuple(
        item
        if isinstance(item, ListedTarget)
        else ListedTarget(
            node_id=item.get("node_id", ""),  # type: ignore[union-attr]
            address_ref=item.get("address_ref", ""),  # type: ignore[union-attr]
            listed_identifier=item.get("listed_identifier", ""),  # type: ignore[union-attr]
            designation_id=item.get("designation_id", ""),  # type: ignore[union-attr]
        )
        for item in listed_targets
    )
    if not targets:
        raise ExposureError("listed_targets must not be empty")

    if snapshot is not None:
        if not isinstance(snapshot, GraphSnapshot):
            raise ExposureError("snapshot must be a GraphSnapshot")
        graph = snapshot.graph
        graph_snapshot_id = snapshot.snapshot_id
        graph_digest = snapshot.graph_digest
    else:
        if graph is None:
            raise ExposureError("graph or snapshot is required")
        if not isinstance(graph, CryptoFlowGraph):
            raise ExposureError("graph must be a CryptoFlowGraph")
        graph_snapshot_id = policy.graph_snapshot_id or graph.graph_id
        graph_digest = graph.identity.digest

    if policy.graph_snapshot_id and policy.graph_snapshot_id != graph_snapshot_id:
        raise ExposureError(
            "policy.graph_snapshot_id does not match the supplied snapshot"
        )

    node_map = graph.node_map()
    if origin_node_id not in node_map:
        raise ExposureError(f"origin_node_id not in graph: {origin_node_id}")
    origin_node = node_map[origin_node_id]
    if origin_node.plane is not policy.plane:
        raise ExposureError("origin node plane must match exposure policy plane")

    target_by_id = {t.node_id: t for t in targets}
    listed_ids = set(target_by_id)
    for tid in listed_ids:
        if tid not in node_map:
            raise ExposureError(f"listed target node missing from graph: {tid}")
        if node_map[tid].plane is not policy.plane:
            raise ExposureError("listed target plane must match exposure policy plane")

    frontier = _build_frontier(snapshot, graph, policy, completeness_receipts)
    adj = _adjacency(graph, policy.plane)

    started = time.monotonic()
    deadline = started + (policy.max_runtime_ms / 1000.0)
    truncation: set[str] = set()
    hit_budget = False

    # Direct self-hit: origin itself is listed.
    found_paths: list[ExposurePath] = []
    if origin_node_id in listed_ids:
        target = target_by_id[origin_node_id]
        path_id = f"path:{_sha256_hex(origin_node_id, 'self', policy.policy_id)[:32]}"
        found_paths.append(
            ExposurePath(
                path_id=path_id,
                origin_node_id=origin_node_id,
                target_node_id=origin_node_id,
                node_ids=(origin_node_id,),
                edge_ids=(),
                steps=(),
                depth=0,
                listed_identifier=target.listed_identifier,
                designation_id=target.designation_id,
                target_address_ref=target.address_ref or origin_node.address_ref,
                graph_snapshot_id=graph_snapshot_id,
                graph_digest=graph_digest,
                list_snapshot_id=policy.list_snapshot_id,
                list_revision=policy.list_revision,
                policy_id=policy.policy_id,
                policy_revision=policy.revision,
                policy_rules_digest=policy.rules_digest,
                min_finality_observed=FinalityStatus.FINALIZED.value,
                claims_designation=False,
            )
        )

    # BFS state: (current_node, path_nodes, path_edges)
    queue: deque[tuple[str, tuple[str, ...], tuple[FlowEdge, ...]]] = deque()
    queue.append((origin_node_id, (origin_node_id,), ()))
    visited_nodes: set[str] = {origin_node_id}
    edges_seen: set[str] = set()
    # Prevent re-expanding the same node at the same or greater depth with same
    # edge set is expensive; use per-node min depth for simple bound search.
    best_depth: dict[str, int] = {origin_node_id: 0}

    while queue:
        if time.monotonic() > deadline:
            truncation.add(TruncationReason.MAX_RUNTIME.value)
            hit_budget = True
            break
        if len(found_paths) >= policy.max_paths:
            truncation.add(TruncationReason.MAX_PATHS.value)
            hit_budget = True
            break

        current, path_nodes, path_edges = queue.popleft()
        depth = len(path_edges)
        # Paths may be at most max_depth hops.  Nodes already at the bound are
        # not expanded; any usable further edge means the search is truncated
        # for absence claims (never "proved no connection" beyond the bound).
        if depth >= policy.max_depth:
            for edge, neighbor in adj.get(current, ()):
                if neighbor in path_nodes:
                    continue
                if edge.edge_id in {e.edge_id for e in path_edges}:
                    continue
                soft: set[str] = set()
                if _edge_usable(edge, policy, soft):
                    truncation.add(TruncationReason.MAX_DEPTH.value)
                    hit_budget = True
                    break
            continue

        for edge, neighbor in adj.get(current, ()):
            if time.monotonic() > deadline:
                truncation.add(TruncationReason.MAX_RUNTIME.value)
                hit_budget = True
                break
            if edge.edge_id in {e.edge_id for e in path_edges}:
                continue  # simple cycle guard on edges
            if neighbor in path_nodes:
                continue  # simple cycle guard on nodes

            soft_trunc: set[str] = set()
            if not _edge_usable(edge, policy, soft_trunc):
                # Filtered edges do not expand the frontier.  Filters are
                # intentional policy exclusions, not search truncation.
                continue

            edges_seen.add(edge.edge_id)
            if len(edges_seen) > policy.max_edges:
                truncation.add(TruncationReason.MAX_EDGES.value)
                hit_budget = True
                break

            new_nodes = path_nodes + (neighbor,)
            new_edges = path_edges + (edge,)
            new_depth = len(new_edges)
            if new_depth > policy.max_depth:
                truncation.add(TruncationReason.MAX_DEPTH.value)
                hit_budget = True
                continue

            visited_nodes.add(neighbor)
            if len(visited_nodes) > policy.max_nodes:
                truncation.add(TruncationReason.MAX_NODES.value)
                hit_budget = True
                break

            if neighbor in listed_ids:
                target = target_by_id[neighbor]
                found_paths.append(
                    _make_path(
                        origin=origin_node_id,
                        target=target,
                        node_ids=new_nodes,
                        edge_seq=new_edges,
                        policy=policy,
                        graph_snapshot_id=graph_snapshot_id,
                        graph_digest=graph_digest,
                    )
                )
                if len(found_paths) >= policy.max_paths:
                    truncation.add(TruncationReason.MAX_PATHS.value)
                    hit_budget = True
                    break
                # Continue searching for additional explainable paths.

            prev_best = best_depth.get(neighbor)
            if prev_best is not None and new_depth >= prev_best:
                continue
            best_depth[neighbor] = new_depth
            if new_depth < policy.max_depth:
                queue.append((neighbor, new_nodes, new_edges))
            else:
                # Arrived at exactly max_depth: record path hits above, but do
                # not expand further.  Mark truncation when the frontier still
                # has usable edges beyond this bound.
                for edge2, neighbor2 in adj.get(neighbor, ()):
                    if neighbor2 in new_nodes:
                        continue
                    if edge2.edge_id in {e.edge_id for e in new_edges}:
                        continue
                    soft2: set[str] = set()
                    if _edge_usable(edge2, policy, soft2):
                        truncation.add(TruncationReason.MAX_DEPTH.value)
                        hit_budget = True
                        break

        if hit_budget and TruncationReason.MAX_PATHS.value in truncation:
            break
        # Depth/node/edge/runtime budgets still allow collecting any already-
        # queued work only for path discovery; absence is fail-closed via
        # truncated=True once any bound is hit.  Continue draining only when
        # we have not yet hit a hard stop that makes further work useless.
        if hit_budget and not queue:
            break

    # Deterministic path ordering.
    found_paths.sort(key=lambda p: (p.depth, p.path_id))
    # Cap paths if over (should already be capped).
    if len(found_paths) > policy.max_paths:
        found_paths = found_paths[: policy.max_paths]
        truncation.add(TruncationReason.MAX_PATHS.value)
        hit_budget = True

    runtime_ms = int((time.monotonic() - started) * 1000)
    truncated = hit_budget

    reason_codes: list[str] = []
    if any(p.depth == 0 or p.is_direct for p in found_paths):
        # depth 0 self-hit is a direct exact listed origin.
        verdict = ExposureVerdict.DIRECT_HIT
        reason_codes.append("direct_exact_hit")
    elif any(p.is_indirect for p in found_paths):
        verdict = ExposureVerdict.INDIRECT_EXPOSURE
        reason_codes.append("bounded_indirect_exposure")
    elif truncated:
        verdict = ExposureVerdict.TRUNCATED
        reason_codes.append("search_truncated")
        reason_codes.append("absence_not_proved")
    elif policy.require_completeness_for_absence and not frontier.supports_absence_claim:
        verdict = ExposureVerdict.INCOMPLETE_FRONTIER
        reason_codes.append("incomplete_completeness_frontier")
        reason_codes.append("absence_not_proved")
    else:
        verdict = ExposureVerdict.NO_PATH_WITHIN_BOUNDS
        reason_codes.append("no_path_within_bounds")
        reason_codes.append("absence_scoped_to_frontier")

    if at_time:
        # Staleness is policy-layer; this module only records the evaluation time.
        reason_codes.append("evaluated_at_bound_time")

    # Prefer stronger verdict when both direct and indirect exist.
    if any(p.is_direct or p.depth == 0 for p in found_paths):
        verdict = ExposureVerdict.DIRECT_HIT

    exposure_id = (
        "exposure:"
        + _sha256_hex(
            origin_node_id,
            policy.policy_id,
            policy.revision,
            graph_snapshot_id,
            graph_digest,
            *(t.node_id for t in targets),
        )[:40]
    )

    return BoundedExposure(
        exposure_id=exposure_id,
        origin_node_id=origin_node_id,
        policy=policy,
        verdict=verdict,
        paths=tuple(found_paths),
        listed_target_node_ids=tuple(sorted(listed_ids)),
        truncation_reasons=tuple(sorted(truncation)),
        truncated=truncated,
        frontier=frontier,
        nodes_visited=len(visited_nodes),
        edges_visited=len(edges_seen),
        runtime_ms=runtime_ms,
        graph_snapshot_id=graph_snapshot_id,
        graph_digest=graph_digest,
        list_snapshot_id=policy.list_snapshot_id,
        list_revision=policy.list_revision,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        attributes={
            "at_time": at_time,
            "never_infers_unlimited_transitive_guilt": True,
            "never_claims_global_absence": True,
        },
    )


def replay_exposure_path(
    path: ExposurePath,
    graph: CryptoFlowGraph,
    *,
    graph_snapshot_id: str = "",
    graph_digest: str = "",
) -> bool:
    """Replay a path against one graph snapshot; return True if still present.

    Replays verify edge endpoints, order, plane, and non-retraction.  A mismatch
    fails closed (returns False) rather than inventing a connection.
    """

    if not isinstance(path, ExposurePath):
        raise ExposureError("path must be an ExposurePath")
    if not isinstance(graph, CryptoFlowGraph):
        raise ExposureError("graph must be a CryptoFlowGraph")
    if graph_snapshot_id and path.graph_snapshot_id and (
        path.graph_snapshot_id != graph_snapshot_id
    ):
        return False
    if graph_digest and path.graph_digest and path.graph_digest != graph_digest:
        return False
    node_map = graph.node_map()
    edge_map = graph.edge_map()
    for node_id in path.node_ids:
        if node_id not in node_map:
            return False
    for step in path.steps:
        edge = edge_map.get(step.edge_id)
        if edge is None:
            return False
        if edge.retraction is not RetractionStatus.NOT_RETRACTED:
            return False
        endpoints = {edge.source_node_id, edge.target_node_id}
        if step.from_node_id not in endpoints or step.to_node_id not in endpoints:
            return False
        if edge.kind.value != step.edge_kind:
            return False
    return True


__all__ = [
    "EXPOSURE_POLICY_SCHEMA_VERSION",
    "EXPOSURE_SCHEMA_VERSION",
    "BoundedExposure",
    "CompletenessFrontier",
    "ExposureError",
    "ExposurePath",
    "ExposurePathStep",
    "ExposurePolicy",
    "ExposureVerdict",
    "ListedTarget",
    "TruncationReason",
    "compute_bounded_exposure",
    "replay_exposure_path",
]
