"""SPAR-012 hard-dependency SCCs and extraction condensation DAG.

This module extends datasets formal semantic authority with
``SCCSnapshot@1`` and ``ExtractionCondensationDAG@1``.  It condenses
``SemanticRefactoringGraphView@1`` under a versioned hard-edge policy,
preserves conservative/dynamic edges, records oversized-cycle gaps, and
exposes incremental invalidation.

It does not replace SPAR-007 graph meaning or SPAR-008 frontier meaning.
Heuristic, vector, and model edges never enter the hard SCC.  Happens-before
and initialization-order edges remain forbidden.  Model output remains
nomination-only and cannot authorize a transition or completion.

Accepted ``@1`` payloads are never rewritten in place.  Observational
metadata is excluded from identity.  Incremental invalidation of an unchanged
graph is identity-equivalent to a clean rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    PROFILE_ID,
    STRUCTURED_CODEC,
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.semantic_refactoring.dynamic_frontier import (
    DynamicPythonFrontier,
    DynamicRiskKind,
    Presence,
)
from ipfs_datasets_py.semantic_refactoring.program_graph import (
    DECLARED_EDGE_KINDS,
    FORBIDDEN_EDGE_KINDS,
    IDENTITY_EXCLUDED_FIELDS,
    SemanticRefactoringGraphView,
    GraphConfidence,
    GraphEvidenceClass,
    RefactoringEdgeKind,
    RefactoringGraphEdge,
    RefactoringNodeKind,
    is_forbidden_edge_kind,
)


TASK_ID: Final[str] = "SPAR-012"
GOAL_ID: Final[str] = "SPAR-G031"
PROGRAM: Final[str] = "semantic-preserving-autonomous-remodularization-v1"
AUTHORITY: Final[str] = "formal semantic authority"
AUTHORITY_OWNER: Final[str] = "ipfs_datasets_py"
ANALYZER_ID: Final[str] = "ipfs_datasets_py.semantic_refactoring.scc@1"

SCC_SNAPSHOT_INTERFACE: Final[str] = "SCCSnapshot@1"
EXTRACTION_CONDENSATION_DAG_INTERFACE: Final[str] = "ExtractionCondensationDAG@1"
HARD_EDGE_POLICY_INTERFACE: Final[str] = "HardEdgePolicy@1"
SCC_COMPONENT_INTERFACE: Final[str] = "SCCComponent@1"
CONSERVATIVE_EDGE_INTERFACE: Final[str] = "PreservedConservativeEdge@1"
OVERSIZED_CYCLE_GAP_INTERFACE: Final[str] = "OversizedCycleGap@1"
CONDENSATION_EDGE_INTERFACE: Final[str] = "CondensationEdge@1"
INVALIDATION_INDEX_INTERFACE: Final[str] = "SCCInvalidationIndex@1"

SCC_SNAPSHOT_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.scc-snapshot@1"
)
EXTRACTION_CONDENSATION_DAG_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.extraction-condensation-dag@1"
)
HARD_EDGE_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.hard-edge-policy@1"
)
SCC_COMPONENT_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.scc-component@1"
)
CONSERVATIVE_EDGE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.preserved-conservative-edge@1"
)
OVERSIZED_CYCLE_GAP_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.oversized-cycle-gap@1"
)
CONDENSATION_EDGE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.condensation-edge@1"
)
INVALIDATION_INDEX_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.scc-invalidation-index@1"
)

SCC_CONTRACT_VERSION: Final[str] = "1"
HARD_EDGE_POLICY_ID: Final[str] = "hard-edge-policy@1"
HARD_EDGE_POLICY_REVISION: Final[str] = "1"
SCC_CID_CODEC: Final[str] = STRUCTURED_CODEC
SCC_CID_PROFILE: Final[str] = PROFILE_ID

SCC_CAN_AUTHORIZE_TRANSITION: Final[bool] = False
SCC_CAN_AUTHORIZE_COMPLETION: Final[bool] = False
SCC_CAN_CREATE_AUTHORITY: Final[bool] = False
VECTOR_SIMILARITY_IS_AUTHORITY: Final[bool] = False
MODEL_OUTPUT_IS_PROPOSAL_ONLY: Final[bool] = True
TEST_PASS_IS_NOT_COMPLETION: Final[bool] = True
MARKDOWN_IS_NOT_COMPLETION: Final[bool] = True
WORKER_SELF_APPROVAL: Final[bool] = False
DUCKLAKE_IS_AUTHORITY: Final[bool] = False
HEURISTIC_EDGES_ARE_NOT_HARD: Final[bool] = True
CONSERVATIVE_EDGES_ARE_PRESERVED: Final[bool] = True
INCREMENTAL_EQUALS_CLEAN_REBUILD: Final[bool] = True

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_SCCS: Final[int] = 16_384
MAX_SCC_MEMBERS: Final[int] = 16_384
MAX_EDGES: Final[int] = 65_536
MAX_GAPS: Final[int] = 4_096
DEFAULT_OVERSIZED_CYCLE_BOUND: Final[int] = 256

DEFAULT_HARD_EDGE_KINDS: Final[tuple[str, ...]] = (
    RefactoringEdgeKind.ALIASES.value,
    RefactoringEdgeKind.CALLS.value,
    RefactoringEdgeKind.DEPENDS_ON.value,
    RefactoringEdgeKind.DERIVED_FROM.value,
    RefactoringEdgeKind.IMPLEMENTS.value,
    RefactoringEdgeKind.IMPORTS.value,
    RefactoringEdgeKind.REGISTERS.value,
    RefactoringEdgeKind.USES_RESOURCE.value,
)

SOFT_EDGE_KINDS: Final[frozenset[str]] = frozenset(
    {
        RefactoringEdgeKind.CONTAINS.value,
        RefactoringEdgeKind.DEFINES.value,
        RefactoringEdgeKind.DOCUMENTS.value,
        RefactoringEdgeKind.EXPORTS.value,
        RefactoringEdgeKind.MEMBER_OF.value,
        RefactoringEdgeKind.PROVES.value,
        RefactoringEdgeKind.REFERENCES.value,
        RefactoringEdgeKind.TESTS.value,
    }
)

_EXACT_EVIDENCE: Final[frozenset[str]] = frozenset(
    {GraphEvidenceClass.EXACT_STATIC_FACT.value}
)
_CONSERVATIVE_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        GraphEvidenceClass.CONSERVATIVE_MAY_FACT.value,
        GraphEvidenceClass.RUNTIME_OBSERVATION.value,
        GraphEvidenceClass.REVIEWED_SPECIFICATION.value,
        GraphEvidenceClass.TEST.value,
        GraphEvidenceClass.PROOF_CANDIDATE.value,
        GraphEvidenceClass.RECONSTRUCTED_PROOF.value,
        GraphEvidenceClass.COUNTERMODEL.value,
        GraphEvidenceClass.REPLAYED_COUNTEREXAMPLE.value,
        GraphEvidenceClass.HUMAN_POLICY_DECISION.value,
    }
)
_HARD_CONFIDENCE: Final[frozenset[str]] = frozenset(
    {
        GraphConfidence.EXACT.value,
        GraphConfidence.CONSERVATIVE.value,
    }
)
_DYNAMIC_CONSERVATIVE_KINDS: Final[frozenset[str]] = frozenset(
    {
        DynamicRiskKind.RELATIVE_CIRCULAR_IMPORT.value,
        DynamicRiskKind.DYNAMIC_IMPORT.value,
        DynamicRiskKind.HIGHER_ORDER.value,
        DynamicRiskKind.SINGLEDISPATCH.value,
        DynamicRiskKind.PLUGIN_REGISTRY.value,
        DynamicRiskKind.NATIVE_FFI.value,
        DynamicRiskKind.GENERATED_CODE.value,
    }
)


class SccContractError(ValueError):
    """Fail-closed violation of a SPAR-012 SCC contract."""


class EdgeAdmission(str, Enum):
    HARD_EXACT = "hard_exact"
    HARD_CONSERVATIVE = "hard_conservative"
    PRESERVED_CONSERVATIVE = "preserved_conservative"
    ADVISORY = "advisory"
    EXCLUDED = "excluded"


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str:
        raise SccContractError(f"{name} must be a string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise SccContractError(f"{name} must be trimmed NFC text")
    if not empty and not value:
        raise SccContractError(f"{name} must be a nonempty string")
    if any(not char.isprintable() for char in value):
        raise SccContractError(f"{name} contains invalid text")
    if len(value) > MAX_TEXT_CHARS:
        raise SccContractError(f"{name} exceeds text bound")
    return value


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise SccContractError(f"{name} must be a valid CID") from exc


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise SccContractError(f"{name} must be a boolean")
    return value


def _positive_int(value: Any, name: str, *, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1:
        raise SccContractError(f"{name} must be a positive integer")
    if value > maximum:
        raise SccContractError(f"{name} exceeds maximum length")
    return value


def _tree_id(value: Any) -> str:
    text = _text(value, "tree_id")
    if len(text) not in {40, 64} or any(
        char not in "0123456789abcdef" for char in text
    ):
        raise SccContractError("tree_id must be a lowercase hex Git tree identity")
    return text


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping) or isinstance(data, (str, bytes, bytearray)):
        raise SccContractError(f"{name} must be an object")
    extra = set(data) - fields
    missing = fields - set(data)
    if extra & IDENTITY_EXCLUDED_FIELDS:
        raise SccContractError(
            f"{name} identity excludes observational fields: "
            f"{sorted(extra & IDENTITY_EXCLUDED_FIELDS)}"
        )
    if extra:
        raise SccContractError(f"unknown {name} field: {sorted(extra)}")
    if missing:
        raise SccContractError(f"missing {name} field: {sorted(missing)}")
    return dict(data)


def _reject_excluded(payload: Mapping[str, Any], name: str) -> None:
    present = IDENTITY_EXCLUDED_FIELDS & set(payload)
    if present:
        raise SccContractError(
            f"{name} identity excludes observational fields: {sorted(present)}"
        )


def _verify_cid(claimed: Any, computed: str, name: str) -> None:
    cid = _cid(claimed, name)
    if cid != computed:
        raise SccContractError(f"{name} does not verify")


def _require_dag_json(value: Any, name: str) -> None:
    try:
        validate_structured_value(value)
    except Exception as exc:
        raise SccContractError(f"{name} must be strict DAG-JSON") from exc


def _unique_sorted_text(values: Any, name: str, *, limit: int) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise SccContractError(f"{name} must be a list")
    ordered = tuple(sorted(_text(item, name) for item in values))
    if len(ordered) > limit:
        raise SccContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise SccContractError(f"{name} must not contain duplicates")
    return ordered


def scc_cid_profile() -> dict[str, str]:
    return {
        "profile_id": SCC_CID_PROFILE,
        "codec": SCC_CID_CODEC,
        "rule": (
            "CID identifies exact canonical bytes under declared codec/profile, "
            "not universal meaning"
        ),
    }


def is_default_hard_edge_kind(kind: str) -> bool:
    return kind in DEFAULT_HARD_EDGE_KINDS


def is_soft_edge_kind(kind: str) -> bool:
    return kind in SOFT_EDGE_KINDS


def _tarjan_sccs(
    nodes: Sequence[str],
    adjacency: Mapping[str, Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    result: list[tuple[str, ...]] = []

    def strongconnect(vertex: str) -> None:
        nonlocal index
        indices[vertex] = index
        lowlink[vertex] = index
        index += 1
        stack.append(vertex)
        on_stack.add(vertex)
        for successor in adjacency.get(vertex, ()):
            if successor not in indices:
                strongconnect(successor)
                lowlink[vertex] = min(lowlink[vertex], lowlink[successor])
            elif successor in on_stack:
                lowlink[vertex] = min(lowlink[vertex], indices[successor])
        if lowlink[vertex] == indices[vertex]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == vertex:
                    break
            result.append(tuple(sorted(component)))

    for node in sorted(nodes):
        if node not in indices:
            strongconnect(node)
    result.sort(key=lambda members: (members[0], len(members), members))
    return tuple(result)


def _topological_order(
    nodes: Sequence[str],
    edges: Sequence[tuple[str, str]],
) -> tuple[str, ...]:
    incoming = {node: 0 for node in nodes}
    outgoing: dict[str, list[str]] = {node: [] for node in nodes}
    seen: set[tuple[str, str]] = set()
    for source, target in edges:
        if source not in incoming or target not in incoming:
            raise SccContractError("condensation edge names an unknown SCC")
        pair = (source, target)
        if pair in seen:
            continue
        seen.add(pair)
        outgoing[source].append(target)
        incoming[target] += 1
    for node in outgoing:
        outgoing[node] = sorted(set(outgoing[node]))
    ready = sorted(node for node, count in incoming.items() if count == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for successor in outgoing[node]:
            incoming[successor] -= 1
            if incoming[successor] == 0:
                ready.append(successor)
                ready.sort()
    if len(order) != len(nodes):
        raise SccContractError("condensation DAG contains a cycle")
    return tuple(order)


def classify_edge(
    edge: RefactoringGraphEdge,
    policy: "HardEdgePolicy",
) -> EdgeAdmission:
    if is_forbidden_edge_kind(edge.kind):
        raise SccContractError(f"forbidden edge kind {edge.kind!r}")
    hard = edge.kind in policy.hard_edge_kinds
    conservative = (
        edge.confidence == GraphConfidence.CONSERVATIVE.value
        or edge.evidence_class in _CONSERVATIVE_EVIDENCE
    )
    exact = (
        edge.confidence == GraphConfidence.EXACT.value
        and edge.evidence_class in _EXACT_EVIDENCE
    )
    if hard and exact:
        return EdgeAdmission.HARD_EXACT
    if hard and conservative and policy.include_conservative_hard_edges:
        return EdgeAdmission.HARD_CONSERVATIVE
    if conservative:
        return EdgeAdmission.PRESERVED_CONSERVATIVE
    if hard:
        return EdgeAdmission.ADVISORY
    return EdgeAdmission.EXCLUDED


@dataclass(frozen=True, slots=True)
class HardEdgePolicy:
    """Versioned closed set of SPAR-007 kinds that participate in hard SCCs."""

    hard_edge_kinds: Sequence[str] = DEFAULT_HARD_EDGE_KINDS
    include_conservative_hard_edges: bool = True
    max_scc_members: int = DEFAULT_OVERSIZED_CYCLE_BOUND
    policy_id: str = HARD_EDGE_POLICY_ID
    revision: str = HARD_EDGE_POLICY_REVISION

    interface: ClassVar[str] = HARD_EDGE_POLICY_INTERFACE
    schema: ClassVar[str] = HARD_EDGE_POLICY_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "policy_id",
            "revision",
            "hard_edge_kinds",
            "include_conservative_hard_edges",
            "max_scc_members",
            "policy_cid",
        }
    )

    def __post_init__(self) -> None:
        policy_id = _text(self.policy_id, "policy_id")
        if policy_id != HARD_EDGE_POLICY_ID:
            raise SccContractError("unsupported hard-edge policy identity")
        revision = _text(self.revision, "revision")
        kinds = _unique_sorted_text(
            list(self.hard_edge_kinds),
            "hard_edge_kinds",
            limit=len(DECLARED_EDGE_KINDS),
        )
        forbidden = [kind for kind in kinds if is_forbidden_edge_kind(kind)]
        if forbidden:
            raise SccContractError(f"forbidden edge kind {forbidden[0]!r}")
        unknown = [kind for kind in kinds if kind not in DECLARED_EDGE_KINDS]
        if unknown:
            raise SccContractError(f"unknown hard edge kind {unknown[0]!r}")
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "hard_edge_kinds", kinds)
        object.__setattr__(
            self,
            "include_conservative_hard_edges",
            _bool(
                self.include_conservative_hard_edges,
                "include_conservative_hard_edges",
            ),
        )
        object.__setattr__(
            self,
            "max_scc_members",
            _positive_int(
                self.max_scc_members,
                "max_scc_members",
                maximum=MAX_SCC_MEMBERS,
            ),
        )

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": HARD_EDGE_POLICY_SCHEMA,
            "interface": HARD_EDGE_POLICY_INTERFACE,
            "policy_id": self.policy_id,
            "revision": self.revision,
            "hard_edge_kinds": list(self.hard_edge_kinds),
            "include_conservative_hard_edges": self.include_conservative_hard_edges,
            "max_scc_members": self.max_scc_members,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def policy_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["policy_cid"] = self.policy_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HardEdgePolicy":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("policy_cid")
        if payload.pop("schema") != HARD_EDGE_POLICY_SCHEMA:
            raise SccContractError("unsupported HardEdgePolicy schema")
        if payload.pop("interface") != HARD_EDGE_POLICY_INTERFACE:
            raise SccContractError("unsupported HardEdgePolicy interface")
        result = cls(**payload)
        _verify_cid(claimed, result.policy_cid, "HardEdgePolicy policy_cid")
        return result


def default_hard_edge_policy() -> HardEdgePolicy:
    return HardEdgePolicy()


def _coerce_policy(value: HardEdgePolicy | Mapping[str, Any] | None) -> HardEdgePolicy:
    if value is None:
        return default_hard_edge_policy()
    if isinstance(value, HardEdgePolicy):
        return value
    if isinstance(value, Mapping):
        if "policy_cid" in value:
            return HardEdgePolicy.from_dict(value)
        return HardEdgePolicy(**dict(value))
    raise SccContractError("hard-edge policy must be a HardEdgePolicy")


@dataclass(frozen=True, slots=True)
class PreservedConservativeEdge:
    """One conservative/dynamic edge retained beside the hard SCC."""

    source_id: str
    target_id: str
    kind: str
    evidence_class: str
    confidence: str
    admission: EdgeAdmission | str

    interface: ClassVar[str] = CONSERVATIVE_EDGE_INTERFACE
    schema: ClassVar[str] = CONSERVATIVE_EDGE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "source_id",
            "target_id",
            "kind",
            "evidence_class",
            "confidence",
            "admission",
            "edge_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        object.__setattr__(self, "target_id", _text(self.target_id, "target_id"))
        kind = _text(self.kind, "kind")
        if is_forbidden_edge_kind(kind):
            raise SccContractError(f"forbidden edge kind {kind!r}")
        if kind not in DECLARED_EDGE_KINDS:
            raise SccContractError(f"unknown edge kind {kind!r}")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "evidence_class",
            GraphEvidenceClass(self.evidence_class).value
            if not isinstance(self.evidence_class, GraphEvidenceClass)
            else self.evidence_class.value,
        )
        object.__setattr__(
            self,
            "confidence",
            GraphConfidence(self.confidence).value
            if not isinstance(self.confidence, GraphConfidence)
            else self.confidence.value,
        )
        admission = (
            self.admission
            if isinstance(self.admission, EdgeAdmission)
            else EdgeAdmission(self.admission)
        )
        if admission not in {
            EdgeAdmission.HARD_CONSERVATIVE,
            EdgeAdmission.PRESERVED_CONSERVATIVE,
        }:
            raise SccContractError("preserved edge admission must be conservative")
        object.__setattr__(self, "admission", admission.value)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": CONSERVATIVE_EDGE_SCHEMA,
            "interface": CONSERVATIVE_EDGE_INTERFACE,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "evidence_class": self.evidence_class,
            "confidence": self.confidence,
            "admission": self.admission,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def edge_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["edge_cid"] = self.edge_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PreservedConservativeEdge":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("edge_cid")
        if payload.pop("schema") != CONSERVATIVE_EDGE_SCHEMA:
            raise SccContractError("unsupported PreservedConservativeEdge schema")
        if payload.pop("interface") != CONSERVATIVE_EDGE_INTERFACE:
            raise SccContractError("unsupported PreservedConservativeEdge interface")
        result = cls(**payload)
        _verify_cid(claimed, result.edge_cid, "PreservedConservativeEdge edge_cid")
        return result


@dataclass(frozen=True, slots=True)
class OversizedCycleGap:
    """Typed gap for a cyclic SCC that exceeds the versioned size bound."""

    scc_id: str
    member_count: int
    extraction_supported: bool = False

    interface: ClassVar[str] = OVERSIZED_CYCLE_GAP_INTERFACE
    schema: ClassVar[str] = OVERSIZED_CYCLE_GAP_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "scc_id",
            "member_count",
            "extraction_supported",
            "gap_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "scc_id", _cid(self.scc_id, "scc_id"))
        object.__setattr__(
            self,
            "member_count",
            _positive_int(self.member_count, "member_count", maximum=MAX_SCC_MEMBERS),
        )
        supported = _bool(self.extraction_supported, "extraction_supported")
        if supported:
            raise SccContractError("oversized-cycle gaps cannot support extraction")
        object.__setattr__(self, "extraction_supported", False)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": OVERSIZED_CYCLE_GAP_SCHEMA,
            "interface": OVERSIZED_CYCLE_GAP_INTERFACE,
            "scc_id": self.scc_id,
            "member_count": self.member_count,
            "extraction_supported": False,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def gap_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["gap_cid"] = self.gap_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OversizedCycleGap":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("gap_cid")
        if payload.pop("schema") != OVERSIZED_CYCLE_GAP_SCHEMA:
            raise SccContractError("unsupported OversizedCycleGap schema")
        if payload.pop("interface") != OVERSIZED_CYCLE_GAP_INTERFACE:
            raise SccContractError("unsupported OversizedCycleGap interface")
        result = cls(**payload)
        _verify_cid(claimed, result.gap_cid, "OversizedCycleGap gap_cid")
        return result


@dataclass(frozen=True, slots=True)
class SCCComponent:
    """One deterministic strongly connected component."""

    member_ids: Sequence[str]
    graph_view_cid: str
    policy_cid: str
    cyclic: bool
    state_owner_ids: Sequence[str] = ()
    oversized: bool = False

    interface: ClassVar[str] = SCC_COMPONENT_INTERFACE
    schema: ClassVar[str] = SCC_COMPONENT_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "member_ids",
            "graph_view_cid",
            "policy_cid",
            "cyclic",
            "state_owner_ids",
            "oversized",
            "scc_id",
        }
    )

    def __post_init__(self) -> None:
        members = _unique_sorted_text(
            list(self.member_ids), "member_ids", limit=MAX_SCC_MEMBERS
        )
        if not members:
            raise SccContractError("SCC component requires at least one member")
        owners = _unique_sorted_text(
            list(self.state_owner_ids), "state_owner_ids", limit=MAX_SCC_MEMBERS
        )
        unknown_owners = [item for item in owners if item not in members]
        if unknown_owners:
            raise SccContractError("state_owner_ids must be component members")
        object.__setattr__(self, "member_ids", members)
        object.__setattr__(self, "state_owner_ids", owners)
        object.__setattr__(
            self, "graph_view_cid", _cid(self.graph_view_cid, "graph_view_cid")
        )
        object.__setattr__(self, "policy_cid", _cid(self.policy_cid, "policy_cid"))
        object.__setattr__(self, "cyclic", _bool(self.cyclic, "cyclic"))
        object.__setattr__(self, "oversized", _bool(self.oversized, "oversized"))
        if self.oversized and not self.cyclic:
            raise SccContractError("oversized flag applies only to cyclic SCCs")

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": SCC_COMPONENT_SCHEMA,
            "interface": SCC_COMPONENT_INTERFACE,
            "member_ids": list(self.member_ids),
            "graph_view_cid": self.graph_view_cid,
            "policy_cid": self.policy_cid,
            "cyclic": self.cyclic,
            "state_owner_ids": list(self.state_owner_ids),
            "oversized": self.oversized,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def scc_id(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def extraction_supported(self) -> bool:
        return not self.oversized

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["scc_id"] = self.scc_id
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SCCComponent":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("scc_id")
        if payload.pop("schema") != SCC_COMPONENT_SCHEMA:
            raise SccContractError("unsupported SCCComponent schema")
        if payload.pop("interface") != SCC_COMPONENT_INTERFACE:
            raise SccContractError("unsupported SCCComponent interface")
        result = cls(**payload)
        _verify_cid(claimed, result.scc_id, "SCCComponent scc_id")
        return result


def _coerce_component(value: SCCComponent | Mapping[str, Any]) -> SCCComponent:
    if isinstance(value, SCCComponent):
        return value
    if isinstance(value, Mapping):
        if "scc_id" in value:
            return SCCComponent.from_dict(value)
        return SCCComponent(**dict(value))
    raise SccContractError("component must be an SCCComponent")


def _coerce_conservative_edge(
    value: PreservedConservativeEdge | Mapping[str, Any],
) -> PreservedConservativeEdge:
    if isinstance(value, PreservedConservativeEdge):
        return value
    if isinstance(value, Mapping):
        if "edge_cid" in value:
            return PreservedConservativeEdge.from_dict(value)
        return PreservedConservativeEdge(**dict(value))
    raise SccContractError("conservative edge must be a PreservedConservativeEdge")


def _coerce_gap(value: OversizedCycleGap | Mapping[str, Any]) -> OversizedCycleGap:
    if isinstance(value, OversizedCycleGap):
        return value
    if isinstance(value, Mapping):
        if "gap_cid" in value:
            return OversizedCycleGap.from_dict(value)
        return OversizedCycleGap(**dict(value))
    raise SccContractError("gap must be an OversizedCycleGap")


@dataclass(frozen=True, slots=True)
class SCCInvalidationIndex:
    """Node-to-SCC and condensation adjacency used for incremental invalidation."""

    node_to_scc: Mapping[str, str]
    successors: Mapping[str, Sequence[str]]
    predecessors: Mapping[str, Sequence[str]]

    interface: ClassVar[str] = INVALIDATION_INDEX_INTERFACE
    schema: ClassVar[str] = INVALIDATION_INDEX_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "node_to_scc",
            "successors",
            "predecessors",
            "index_cid",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.node_to_scc, Mapping):
            raise SccContractError("node_to_scc must be an object")
        node_to_scc = {
            _text(key, "node_id"): _cid(value, "scc_id")
            for key, value in self.node_to_scc.items()
        }
        if len(node_to_scc) > MAX_SCC_MEMBERS:
            raise SccContractError("node_to_scc exceeds maximum length")
        scc_ids = set(node_to_scc.values())

        def _adj(raw: Any, name: str) -> dict[str, tuple[str, ...]]:
            if not isinstance(raw, Mapping):
                raise SccContractError(f"{name} must be an object")
            mapping: dict[str, tuple[str, ...]] = {}
            for key, values in raw.items():
                scc_id = _cid(key, name)
                if scc_id not in scc_ids:
                    raise SccContractError(f"{name} names an unknown SCC")
                mapping[scc_id] = _unique_sorted_text(list(values), name, limit=MAX_SCCS)
                unknown = [item for item in mapping[scc_id] if item not in scc_ids]
                if unknown:
                    raise SccContractError(f"{name} names an unknown SCC")
            missing = [item for item in sorted(scc_ids) if item not in mapping]
            if missing:
                raise SccContractError(f"{name} must cover every SCC")
            return mapping

        successors = _adj(self.successors, "successors")
        predecessors = _adj(self.predecessors, "predecessors")
        for scc_id, targets in successors.items():
            for target in targets:
                if scc_id not in predecessors[target]:
                    raise SccContractError("invalidation index adjacency is asymmetric")
        object.__setattr__(self, "node_to_scc", dict(sorted(node_to_scc.items())))
        object.__setattr__(
            self,
            "successors",
            {key: successors[key] for key in sorted(successors)},
        )
        object.__setattr__(
            self,
            "predecessors",
            {key: predecessors[key] for key in sorted(predecessors)},
        )

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": INVALIDATION_INDEX_SCHEMA,
            "interface": INVALIDATION_INDEX_INTERFACE,
            "node_to_scc": dict(self.node_to_scc),
            "successors": {
                key: list(values) for key, values in self.successors.items()
            },
            "predecessors": {
                key: list(values) for key, values in self.predecessors.items()
            },
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def index_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def affected_sccs(self, changed_node_ids: Sequence[str]) -> tuple[str, ...]:
        seeds: set[str] = set()
        for node_id in changed_node_ids:
            text = _text(node_id, "changed_node_id")
            scc_id = self.node_to_scc.get(text)
            if scc_id is not None:
                seeds.add(scc_id)
        affected = set(seeds)
        stack = list(seeds)
        while stack:
            current = stack.pop()
            for neighbor in self.successors[current]:
                if neighbor not in affected:
                    affected.add(neighbor)
                    stack.append(neighbor)
            for neighbor in self.predecessors[current]:
                if neighbor not in affected:
                    affected.add(neighbor)
                    stack.append(neighbor)
        return tuple(sorted(affected))

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["index_cid"] = self.index_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SCCInvalidationIndex":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("index_cid")
        if payload.pop("schema") != INVALIDATION_INDEX_SCHEMA:
            raise SccContractError("unsupported SCCInvalidationIndex schema")
        if payload.pop("interface") != INVALIDATION_INDEX_INTERFACE:
            raise SccContractError("unsupported SCCInvalidationIndex interface")
        result = cls(**payload)
        _verify_cid(claimed, result.index_cid, "SCCInvalidationIndex index_cid")
        return result


def _coerce_index(
    value: SCCInvalidationIndex | Mapping[str, Any],
) -> SCCInvalidationIndex:
    if isinstance(value, SCCInvalidationIndex):
        return value
    if isinstance(value, Mapping):
        if "index_cid" in value:
            return SCCInvalidationIndex.from_dict(value)
        return SCCInvalidationIndex(**dict(value))
    raise SccContractError("invalidation index must be an SCCInvalidationIndex")


@dataclass(frozen=True, slots=True)
class SCCSnapshot:
    """Deterministic hard-dependency SCC snapshot bound to one graph view."""

    tree_id: str
    graph_view_cid: str
    policy: HardEdgePolicy | Mapping[str, Any]
    components: Sequence[SCCComponent | Mapping[str, Any]]
    preserved_conservative_edges: Sequence[
        PreservedConservativeEdge | Mapping[str, Any]
    ] = ()
    oversized_cycle_gaps: Sequence[OversizedCycleGap | Mapping[str, Any]] = ()
    condensation_edges: Sequence[CondensationEdge | Mapping[str, Any]] = ()
    invalidation_index: SCCInvalidationIndex | Mapping[str, Any] | None = None
    dynamic_conservative_kinds: Sequence[str] = ()
    analyzer_id: str = ANALYZER_ID

    interface: ClassVar[str] = SCC_SNAPSHOT_INTERFACE
    schema: ClassVar[str] = SCC_SNAPSHOT_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "tree_id",
            "graph_view_cid",
            "policy",
            "components",
            "preserved_conservative_edges",
            "oversized_cycle_gaps",
            "condensation_edges",
            "invalidation_index",
            "dynamic_conservative_kinds",
            "analyzer_id",
            "snapshot_cid",
        }
    )

    def __post_init__(self) -> None:
        policy = _coerce_policy(self.policy)
        components = tuple(_coerce_component(item) for item in self.components)
        if len(components) > MAX_SCCS:
            raise SccContractError("components exceed maximum length")
        components = tuple(sorted(components, key=lambda item: item.scc_id))
        seen_ids = [item.scc_id for item in components]
        if len(seen_ids) != len(set(seen_ids)):
            raise SccContractError("duplicate SCC identity")
        members: list[str] = []
        for item in components:
            if item.policy_cid != policy.policy_cid:
                raise SccContractError("component policy_cid must match snapshot policy")
            if item.graph_view_cid != _cid(self.graph_view_cid, "graph_view_cid"):
                raise SccContractError(
                    "component graph_view_cid must match snapshot graph_view_cid"
                )
            members.extend(item.member_ids)
        if len(members) != len(set(members)):
            raise SccContractError("SCC members must be partitioned")
        edges = tuple(
            _coerce_conservative_edge(item)
            for item in self.preserved_conservative_edges
        )
        if len(edges) > MAX_EDGES:
            raise SccContractError("preserved conservative edges exceed maximum length")
        edges = tuple(sorted(edges, key=lambda item: item.edge_cid))
        gaps = tuple(_coerce_gap(item) for item in self.oversized_cycle_gaps)
        if len(gaps) > MAX_GAPS:
            raise SccContractError("oversized-cycle gaps exceed maximum length")
        gaps = tuple(sorted(gaps, key=lambda item: item.gap_cid))
        condensation = tuple(
            _coerce_condensation_edge(item) for item in self.condensation_edges
        )
        if len(condensation) > MAX_EDGES:
            raise SccContractError("condensation edges exceed maximum length")
        condensation_keys = [
            (item.source_scc_id, item.target_scc_id, item.witness_kind)
            for item in condensation
        ]
        if len(condensation_keys) != len(set(condensation_keys)):
            raise SccContractError("duplicate condensation edge")
        condensation = tuple(sorted(condensation, key=lambda item: item.edge_cid))
        present_sccs = {item.scc_id for item in components}
        for edge in condensation:
            if (
                edge.source_scc_id not in present_sccs
                or edge.target_scc_id not in present_sccs
            ):
                raise SccContractError("condensation edge names an unknown SCC")
        component_by_id = {item.scc_id: item for item in components}
        for gap in gaps:
            component = component_by_id.get(gap.scc_id)
            if component is None:
                raise SccContractError("oversized-cycle gap names an unknown SCC")
            if not component.oversized or not component.cyclic:
                raise SccContractError(
                    "oversized-cycle gap must name an oversized cyclic SCC"
                )
            if gap.member_count != len(component.member_ids):
                raise SccContractError("oversized-cycle gap member_count mismatch")
        oversized_ids = {item.scc_id for item in components if item.oversized}
        gap_ids = {item.scc_id for item in gaps}
        if oversized_ids != gap_ids:
            raise SccContractError("every oversized cyclic SCC requires a typed gap")
        kinds = _unique_sorted_text(
            list(self.dynamic_conservative_kinds),
            "dynamic_conservative_kinds",
            limit=64,
        )
        unknown_kinds = [
            kind for kind in kinds if kind not in {item.value for item in DynamicRiskKind}
        ]
        if unknown_kinds:
            raise SccContractError(
                f"unknown dynamic conservative kind {unknown_kinds[0]!r}"
            )
        pairs = tuple(
            (item.source_scc_id, item.target_scc_id) for item in condensation
        )
        index = self.invalidation_index
        if index is None:
            index = _index_from_components(components, pairs)
        else:
            index = _coerce_index(index)
        expected_nodes = {member: item.scc_id for item in components for member in item.member_ids}
        if dict(index.node_to_scc) != expected_nodes:
            raise SccContractError("invalidation index node map must match components")
        expected_successors = {item.scc_id: [] for item in components}
        for edge in condensation:
            expected_successors[edge.source_scc_id].append(edge.target_scc_id)
        expected_successors = {
            key: tuple(sorted(set(values)))
            for key, values in expected_successors.items()
        }
        actual_successors = {
            key: tuple(values) for key, values in index.successors.items()
        }
        if actual_successors != expected_successors:
            raise SccContractError(
                "invalidation index successors must match condensation edges"
            )
        object.__setattr__(self, "tree_id", _tree_id(self.tree_id))
        object.__setattr__(
            self, "graph_view_cid", _cid(self.graph_view_cid, "graph_view_cid")
        )
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "preserved_conservative_edges", edges)
        object.__setattr__(self, "oversized_cycle_gaps", gaps)
        object.__setattr__(self, "condensation_edges", condensation)
        object.__setattr__(self, "invalidation_index", index)
        object.__setattr__(self, "dynamic_conservative_kinds", kinds)
        analyzer = _text(self.analyzer_id, "analyzer_id")
        if analyzer != ANALYZER_ID:
            raise SccContractError("analyzer_id must remain the SPAR-012 analyzer")
        object.__setattr__(self, "analyzer_id", analyzer)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": SCC_SNAPSHOT_SCHEMA,
            "interface": SCC_SNAPSHOT_INTERFACE,
            "tree_id": self.tree_id,
            "graph_view_cid": self.graph_view_cid,
            "policy": self.policy.to_dict(),
            "components": [item.to_dict() for item in self.components],
            "preserved_conservative_edges": [
                item.to_dict() for item in self.preserved_conservative_edges
            ],
            "oversized_cycle_gaps": [
                item.to_dict() for item in self.oversized_cycle_gaps
            ],
            "condensation_edges": [
                item.to_dict() for item in self.condensation_edges
            ],
            "invalidation_index": self.invalidation_index.to_dict(),
            "dynamic_conservative_kinds": list(self.dynamic_conservative_kinds),
            "analyzer_id": self.analyzer_id,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def snapshot_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def scc_ids(self) -> tuple[str, ...]:
        return tuple(item.scc_id for item in self.components)

    def component_for_node(self, node_id: str) -> SCCComponent:
        scc_id = self.invalidation_index.node_to_scc.get(node_id)
        if scc_id is None:
            raise SccContractError("node_id is not present in the SCC snapshot")
        for item in self.components:
            if item.scc_id == scc_id:
                return item
        raise SccContractError("node maps to a missing SCC")

    def affected_sccs(self, changed_node_ids: Sequence[str]) -> tuple[str, ...]:
        return self.invalidation_index.affected_sccs(changed_node_ids)

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["snapshot_cid"] = self.snapshot_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SCCSnapshot":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("snapshot_cid")
        if payload.pop("schema") != SCC_SNAPSHOT_SCHEMA:
            raise SccContractError("unsupported SCCSnapshot schema")
        if payload.pop("interface") != SCC_SNAPSHOT_INTERFACE:
            raise SccContractError("unsupported SCCSnapshot interface")
        result = cls(**payload)
        _verify_cid(claimed, result.snapshot_cid, "SCCSnapshot snapshot_cid")
        return result


@dataclass(frozen=True, slots=True)
class CondensationEdge:
    """Directed condensation edge: source SCC hard-depends on target SCC."""

    source_scc_id: str
    target_scc_id: str
    witness_kind: str

    interface: ClassVar[str] = CONDENSATION_EDGE_INTERFACE
    schema: ClassVar[str] = CONDENSATION_EDGE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "source_scc_id",
            "target_scc_id",
            "witness_kind",
            "edge_cid",
        }
    )

    def __post_init__(self) -> None:
        source = _cid(self.source_scc_id, "source_scc_id")
        target = _cid(self.target_scc_id, "target_scc_id")
        if source == target:
            raise SccContractError("condensation edges cannot be self-loops")
        kind = _text(self.witness_kind, "witness_kind")
        if kind not in DECLARED_EDGE_KINDS:
            raise SccContractError(f"unknown witness kind {kind!r}")
        object.__setattr__(self, "source_scc_id", source)
        object.__setattr__(self, "target_scc_id", target)
        object.__setattr__(self, "witness_kind", kind)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": CONDENSATION_EDGE_SCHEMA,
            "interface": CONDENSATION_EDGE_INTERFACE,
            "source_scc_id": self.source_scc_id,
            "target_scc_id": self.target_scc_id,
            "witness_kind": self.witness_kind,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def edge_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["edge_cid"] = self.edge_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CondensationEdge":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("edge_cid")
        if payload.pop("schema") != CONDENSATION_EDGE_SCHEMA:
            raise SccContractError("unsupported CondensationEdge schema")
        if payload.pop("interface") != CONDENSATION_EDGE_INTERFACE:
            raise SccContractError("unsupported CondensationEdge interface")
        result = cls(**payload)
        _verify_cid(claimed, result.edge_cid, "CondensationEdge edge_cid")
        return result


def _coerce_condensation_edge(
    value: CondensationEdge | Mapping[str, Any],
) -> CondensationEdge:
    if isinstance(value, CondensationEdge):
        return value
    if isinstance(value, Mapping):
        if "edge_cid" in value:
            return CondensationEdge.from_dict(value)
        return CondensationEdge(**dict(value))
    raise SccContractError("condensation edge must be a CondensationEdge")


@dataclass(frozen=True, slots=True)
class ExtractionCondensationDAG:
    """Acyclic condensation of SCCs used as the extraction wave order."""

    snapshot_cid: str
    scc_ids: Sequence[str]
    edges: Sequence[CondensationEdge | Mapping[str, Any]]
    extraction_order: Sequence[str]

    interface: ClassVar[str] = EXTRACTION_CONDENSATION_DAG_INTERFACE
    schema: ClassVar[str] = EXTRACTION_CONDENSATION_DAG_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "snapshot_cid",
            "scc_ids",
            "edges",
            "extraction_order",
            "dag_cid",
        }
    )

    def __post_init__(self) -> None:
        scc_ids = _unique_sorted_text(list(self.scc_ids), "scc_ids", limit=MAX_SCCS)
        edges = tuple(_coerce_condensation_edge(item) for item in self.edges)
        if len(edges) > MAX_EDGES:
            raise SccContractError("condensation edges exceed maximum length")
        keys = [(item.source_scc_id, item.target_scc_id, item.witness_kind) for item in edges]
        if len(keys) != len(set(keys)):
            raise SccContractError("duplicate condensation edge")
        present = set(scc_ids)
        for edge in edges:
            if edge.source_scc_id not in present or edge.target_scc_id not in present:
                raise SccContractError("condensation edge names an unknown SCC")
        edges = tuple(sorted(edges, key=lambda item: item.edge_cid))
        pairs = tuple((item.source_scc_id, item.target_scc_id) for item in edges)
        computed_order = tuple(reversed(_topological_order(scc_ids, pairs)))
        claimed_order = tuple(_text(item, "extraction_order") for item in self.extraction_order)
        if claimed_order != computed_order:
            raise SccContractError(
                "extraction_order must be the deterministic dependency-first order"
            )
        object.__setattr__(self, "snapshot_cid", _cid(self.snapshot_cid, "snapshot_cid"))
        object.__setattr__(self, "scc_ids", scc_ids)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(self, "extraction_order", computed_order)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": EXTRACTION_CONDENSATION_DAG_SCHEMA,
            "interface": EXTRACTION_CONDENSATION_DAG_INTERFACE,
            "snapshot_cid": self.snapshot_cid,
            "scc_ids": list(self.scc_ids),
            "edges": [item.to_dict() for item in self.edges],
            "extraction_order": list(self.extraction_order),
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def dag_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["dag_cid"] = self.dag_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExtractionCondensationDAG":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("dag_cid")
        if payload.pop("schema") != EXTRACTION_CONDENSATION_DAG_SCHEMA:
            raise SccContractError("unsupported ExtractionCondensationDAG schema")
        if payload.pop("interface") != EXTRACTION_CONDENSATION_DAG_INTERFACE:
            raise SccContractError("unsupported ExtractionCondensationDAG interface")
        result = cls(**payload)
        _verify_cid(claimed, result.dag_cid, "ExtractionCondensationDAG dag_cid")
        return result


def _index_from_components(
    components: Sequence[SCCComponent],
    condensation_pairs: Sequence[tuple[str, str]],
) -> SCCInvalidationIndex:
    node_to_scc = {
        member: item.scc_id for item in components for member in item.member_ids
    }
    scc_ids = [item.scc_id for item in components]
    successors: dict[str, list[str]] = {scc_id: [] for scc_id in scc_ids}
    predecessors: dict[str, list[str]] = {scc_id: [] for scc_id in scc_ids}
    for source, target in condensation_pairs:
        if source != target:
            successors[source].append(target)
            predecessors[target].append(source)
    return SCCInvalidationIndex(
        node_to_scc=node_to_scc,
        successors=successors,
        predecessors=predecessors,
    )


def _verify_state_uniqueness(view: SemanticRefactoringGraphView) -> None:
    seen: dict[str, str] = {}
    for node in view.nodes:
        if node.kind != RefactoringNodeKind.STATE_OWNER.value:
            continue
        if node.identity_set_cid is None:
            continue
        prior = seen.get(node.identity_set_cid)
        if prior is not None and prior != node.node_id:
            raise SccContractError("state uniqueness violated: duplicated state owner")
        seen[node.identity_set_cid] = node.node_id


def _dynamic_conservative_kinds(
    frontier: DynamicPythonFrontier | None,
    *,
    tree_id: str,
) -> tuple[str, ...]:
    if frontier is None:
        return ()
    if frontier.tree_id != tree_id:
        raise SccContractError("dynamic frontier tree_id must match the graph view")
    kinds = {
        item.kind
        for item in frontier.findings
        if item.presence == Presence.PRESENT.value
        and item.kind in _DYNAMIC_CONSERVATIVE_KINDS
    }
    unknown = {
        item.kind
        for item in frontier.findings
        if item.presence == Presence.UNKNOWN.value
        and item.kind in _DYNAMIC_CONSERVATIVE_KINDS
    }
    return tuple(sorted(kinds | unknown))


def build_scc_snapshot(
    view: SemanticRefactoringGraphView,
    *,
    policy: HardEdgePolicy | Mapping[str, Any] | None = None,
    frontier: DynamicPythonFrontier | None = None,
) -> SCCSnapshot:
    """Compute one closed SCCSnapshot@1 from a SPAR-007 graph view."""

    if not isinstance(view, SemanticRefactoringGraphView):
        raise SccContractError("view must be a SemanticRefactoringGraphView")
    resolved_policy = _coerce_policy(policy)
    _verify_state_uniqueness(view)
    node_ids = list(view.node_ids)
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    preserved: list[PreservedConservativeEdge] = []
    hard_witness: dict[tuple[str, str], str] = {}
    for edge in view.edges:
        admission = classify_edge(edge, resolved_policy)
        if admission in {EdgeAdmission.HARD_EXACT, EdgeAdmission.HARD_CONSERVATIVE}:
            adjacency[edge.source_id].append(edge.target_id)
            hard_witness.setdefault((edge.source_id, edge.target_id), edge.kind)
        if admission in {
            EdgeAdmission.HARD_CONSERVATIVE,
            EdgeAdmission.PRESERVED_CONSERVATIVE,
        }:
            preserved.append(
                PreservedConservativeEdge(
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    kind=edge.kind,
                    evidence_class=edge.evidence_class,
                    confidence=edge.confidence,
                    admission=admission,
                )
            )
    adjacency = {
        node_id: tuple(sorted(set(successors)))
        for node_id, successors in adjacency.items()
    }
    groups = _tarjan_sccs(node_ids, adjacency)
    owners_by_node = {
        node.node_id: node
        for node in view.nodes
        if node.kind == RefactoringNodeKind.STATE_OWNER.value
    }
    graph_view_cid = view.graph_view_cid
    policy_cid = resolved_policy.policy_cid
    components: list[SCCComponent] = []
    member_to_scc_members: dict[str, tuple[str, ...]] = {}
    for members in groups:
        cyclic = len(members) > 1 or any(
            member in adjacency.get(member, ()) for member in members
        )
        oversized = cyclic and len(members) > resolved_policy.max_scc_members
        component = SCCComponent(
            member_ids=members,
            graph_view_cid=graph_view_cid,
            policy_cid=policy_cid,
            cyclic=cyclic,
            state_owner_ids=tuple(
                member for member in members if member in owners_by_node
            ),
            oversized=oversized,
        )
        components.append(component)
        for member in members:
            member_to_scc_members[member] = members
    component_ids = {tuple(item.member_ids): item.scc_id for item in components}
    pairs: list[tuple[str, str]] = []
    condensation_edges: list[CondensationEdge] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    for (source, target), kind in hard_witness.items():
        source_scc = component_ids[member_to_scc_members[source]]
        target_scc = component_ids[member_to_scc_members[target]]
        if source_scc == target_scc:
            continue
        key = (source_scc, target_scc, kind)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        pairs.append((source_scc, target_scc))
        condensation_edges.append(
            CondensationEdge(
                source_scc_id=source_scc,
                target_scc_id=target_scc,
                witness_kind=kind,
            )
        )
    gaps = tuple(
        OversizedCycleGap(
            scc_id=item.scc_id,
            member_count=len(item.member_ids),
        )
        for item in components
        if item.oversized
    )
    index = _index_from_components(components, pairs)
    return SCCSnapshot(
        tree_id=view.tree_id,
        graph_view_cid=graph_view_cid,
        policy=resolved_policy,
        components=components,
        preserved_conservative_edges=preserved,
        oversized_cycle_gaps=gaps,
        condensation_edges=condensation_edges,
        invalidation_index=index,
        dynamic_conservative_kinds=_dynamic_conservative_kinds(
            frontier, tree_id=view.tree_id
        ),
    )


def build_extraction_condensation_dag(
    snapshot: SCCSnapshot,
) -> ExtractionCondensationDAG:
    """Build the acyclic extraction condensation DAG for one SCC snapshot."""

    if not isinstance(snapshot, SCCSnapshot):
        raise SccContractError("snapshot must be an SCCSnapshot")
    pairs = tuple(
        (item.source_scc_id, item.target_scc_id)
        for item in snapshot.condensation_edges
    )
    order = tuple(reversed(_topological_order(snapshot.scc_ids, pairs)))
    return ExtractionCondensationDAG(
        snapshot_cid=snapshot.snapshot_cid,
        scc_ids=snapshot.scc_ids,
        edges=snapshot.condensation_edges,
        extraction_order=order,
    )


def rebuild_scc_snapshot(
    view: SemanticRefactoringGraphView,
    *,
    previous: SCCSnapshot | None = None,
    changed_node_ids: Sequence[str] = (),
    policy: HardEdgePolicy | Mapping[str, Any] | None = None,
    frontier: DynamicPythonFrontier | None = None,
) -> SCCSnapshot:
    """Rebuild a snapshot. Unchanged graphs stay identity-equivalent."""

    rebuilt = build_scc_snapshot(view, policy=policy, frontier=frontier)
    if previous is None:
        return rebuilt
    if (
        previous.graph_view_cid == rebuilt.graph_view_cid
        and previous.policy.policy_cid == rebuilt.policy.policy_cid
        and previous.tree_id == rebuilt.tree_id
        and not tuple(changed_node_ids)
    ):
        if previous.snapshot_cid != rebuilt.snapshot_cid:
            raise SccContractError(
                "incremental invalidation is not identity-equivalent to a clean rebuild"
            )
        return previous
    if previous.snapshot_cid != rebuilt.snapshot_cid and not tuple(changed_node_ids):
        raise SccContractError(
            "graph or policy changed without incremental invalidation seeds"
        )
    return rebuilt


def encode_canonical_scc_snapshot(snapshot: SCCSnapshot) -> dict[str, Any]:
    return snapshot.to_dict()


def decode_canonical_scc_snapshot(payload: Mapping[str, Any]) -> SCCSnapshot:
    return SCCSnapshot.from_dict(payload)


def encode_canonical_condensation_dag(
    dag: ExtractionCondensationDAG,
) -> dict[str, Any]:
    return dag.to_dict()


def decode_canonical_condensation_dag(
    payload: Mapping[str, Any],
) -> ExtractionCondensationDAG:
    return ExtractionCondensationDAG.from_dict(payload)


def provider_free_exports() -> tuple[str, ...]:
    return tuple(sorted(__all__))


__all__ = [
    "ANALYZER_ID",
    "AUTHORITY",
    "AUTHORITY_OWNER",
    "CONSERVATIVE_EDGES_ARE_PRESERVED",
    "DEFAULT_HARD_EDGE_KINDS",
    "DUCKLAKE_IS_AUTHORITY",
    "EXTRACTION_CONDENSATION_DAG_INTERFACE",
    "GOAL_ID",
    "HARD_EDGE_POLICY_ID",
    "HARD_EDGE_POLICY_INTERFACE",
    "HARD_EDGE_POLICY_REVISION",
    "HEURISTIC_EDGES_ARE_NOT_HARD",
    "INCREMENTAL_EQUALS_CLEAN_REBUILD",
    "MARKDOWN_IS_NOT_COMPLETION",
    "MODEL_OUTPUT_IS_PROPOSAL_ONLY",
    "PROGRAM",
    "SCC_CAN_AUTHORIZE_COMPLETION",
    "SCC_CAN_AUTHORIZE_TRANSITION",
    "SCC_CAN_CREATE_AUTHORITY",
    "SCC_CID_CODEC",
    "SCC_CID_PROFILE",
    "SCC_CONTRACT_VERSION",
    "SCC_SNAPSHOT_INTERFACE",
    "SOFT_EDGE_KINDS",
    "TASK_ID",
    "TEST_PASS_IS_NOT_COMPLETION",
    "VECTOR_SIMILARITY_IS_AUTHORITY",
    "WORKER_SELF_APPROVAL",
    "CondensationEdge",
    "EdgeAdmission",
    "ExtractionCondensationDAG",
    "HardEdgePolicy",
    "OversizedCycleGap",
    "PreservedConservativeEdge",
    "SCCComponent",
    "SCCInvalidationIndex",
    "SCCSnapshot",
    "SccContractError",
    "build_extraction_condensation_dag",
    "build_scc_snapshot",
    "classify_edge",
    "decode_canonical_condensation_dag",
    "decode_canonical_scc_snapshot",
    "default_hard_edge_policy",
    "encode_canonical_condensation_dag",
    "encode_canonical_scc_snapshot",
    "is_default_hard_edge_kind",
    "is_soft_edge_kind",
    "provider_free_exports",
    "rebuild_scc_snapshot",
    "scc_cid_profile",
]

assert SCC_SNAPSHOT_INTERFACE == "SCCSnapshot@1"
assert EXTRACTION_CONDENSATION_DAG_INTERFACE == "ExtractionCondensationDAG@1"
assert TASK_ID == "SPAR-012"
assert SCC_CAN_AUTHORIZE_COMPLETION is False
assert MODEL_OUTPUT_IS_PROPOSAL_ONLY is True
assert set(DEFAULT_HARD_EDGE_KINDS).isdisjoint(SOFT_EDGE_KINDS)
assert set(DEFAULT_HARD_EDGE_KINDS).isdisjoint(FORBIDDEN_EDGE_KINDS)
assert INCREMENTAL_EQUALS_CLEAN_REBUILD is True
