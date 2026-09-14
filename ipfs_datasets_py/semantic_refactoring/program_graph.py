"""SPAR-007 typed static program and refactoring graph.

This module extends datasets formal semantic authority with
``SemanticRefactoringGraphView@1``.  It binds typed semantic/refactoring
nodes and edges to an exact Git tree, analyzer identity, environment CID,
and unresolved frontier.

It does not replace the current accelerator program-graph query adapter
(``ipfs_accelerate_py/agent_supervisor/analysis/program_graph.py``).
Semantic and refactoring graph meaning remains datasets-owned.  Happens-before
and initialization-order edges are not minted here.  Model output remains
nomination-only and cannot authorize a transition or completion.

Accepted ``@1`` payloads are never rewritten in place.  Observational
metadata (timestamps, process IDs, local paths, model output) is excluded
from identity.
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


TASK_ID: Final[str] = "SPAR-007"
GOAL_ID: Final[str] = "SPAR-G021"
PROGRAM: Final[str] = "semantic-preserving-autonomous-remodularization-v1"
AUTHORITY: Final[str] = "formal semantic authority"
AUTHORITY_OWNER: Final[str] = "ipfs_datasets_py"

SEMANTIC_REFACTORING_GRAPH_VIEW_INTERFACE: Final[str] = (
    "SemanticRefactoringGraphView@1"
)
REFACTORING_GRAPH_NODE_INTERFACE: Final[str] = "RefactoringGraphNode@1"
REFACTORING_GRAPH_EDGE_INTERFACE: Final[str] = "RefactoringGraphEdge@1"
GRAPH_BINDING_INTERFACE: Final[str] = "GraphBinding@1"
UNRESOLVED_FRONTIER_INTERFACE: Final[str] = "UnresolvedFrontier@1"
UNRESOLVED_FRONTIER_ITEM_INTERFACE: Final[str] = "UnresolvedFrontierItem@1"

SEMANTIC_REFACTORING_GRAPH_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.semantic-refactoring-graph-view@1"
)
REFACTORING_GRAPH_NODE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.refactoring-graph-node@1"
)
REFACTORING_GRAPH_EDGE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.refactoring-graph-edge@1"
)
GRAPH_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.graph-binding@1"
)
UNRESOLVED_FRONTIER_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.unresolved-frontier@1"
)
UNRESOLVED_FRONTIER_ITEM_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.unresolved-frontier-item@1"
)

GRAPH_CONTRACT_VERSION: Final[str] = "1"
GRAPH_CID_CODEC: Final[str] = STRUCTURED_CODEC
GRAPH_CID_PROFILE: Final[str] = PROFILE_ID

GRAPH_CAN_AUTHORIZE_TRANSITION: Final[bool] = False
GRAPH_CAN_AUTHORIZE_COMPLETION: Final[bool] = False
GRAPH_CAN_CREATE_AUTHORITY: Final[bool] = False
VECTOR_SIMILARITY_IS_AUTHORITY: Final[bool] = False
MODEL_OUTPUT_IS_PROPOSAL_ONLY: Final[bool] = True
TEST_PASS_IS_NOT_COMPLETION: Final[bool] = True
MARKDOWN_IS_NOT_COMPLETION: Final[bool] = True
WORKER_SELF_APPROVAL: Final[bool] = False
DUCKLAKE_IS_AUTHORITY: Final[bool] = False

QUERY_ADAPTER_PATH: Final[str] = (
    "ipfs_accelerate_py/agent_supervisor/analysis/program_graph.py"
)
QUERY_ADAPTER_DISPOSITION: Final[str] = "reuse_query_adapter"
QUERY_ADAPTER_OWNER: Final[str] = "ipfs_accelerate_py"
QUERY_ADAPTER_INTERFACE_CONCERN: Final[str] = "program_graph"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_NODES: Final[int] = 16_384
MAX_EDGES: Final[int] = 65_536
MAX_FRONTIER_ITEMS: Final[int] = 8_192
MAX_UNRESOLVED_FIELDS: Final[int] = 256

IDENTITY_EXCLUDED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "timestamp",
        "timestamps",
        "clock",
        "clocks",
        "wall_clock",
        "process_id",
        "pid",
        "local_path",
        "local_paths",
        "checkout_path",
        "store_path",
        "model_output",
        "provider_output",
        "llm_output",
        "prompt",
        "prompts",
        "model",
        "provider",
        "lease",
        "fence",
        "generation",
        "receipt",
        "acceptance",
    }
)

_FORBIDDEN_CAPSULE_TYPE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "FunctionSemanticCapsule",
        "MethodSemanticCapsule",
        "ClassSemanticCapsule",
        "TopLevelBlockCapsule",
        "ModuleSemanticCapsule",
        "PackageSemanticCapsule",
        "CallsiteSemanticCapsule",
        "StateOwnerCapsule",
        "RegistrationCapsule",
        "ResourceLifecycleCapsule",
    }
)

# SPAR-002 capsule kinds remain first-class node kinds; plan extras fill the
# typed logical multigraph without minting a second capsule family.
CAPSULE_ALIGNED_NODE_KINDS: Final[tuple[str, ...]] = (
    "function",
    "method",
    "class",
    "callsite",
    "top_level_block",
    "module",
    "package",
    "state_owner",
    "registration",
    "resource_lifecycle",
)

PLAN_NODE_KINDS: Final[tuple[str, ...]] = (
    "repository",
    "basic_block",
    "variable",
    "decorator",
    "resource",
    "lock",
    "transaction",
    "configuration",
    "contract",
    "claim",
    "proof",
    "test",
    "external_boundary",
    "alias",
    "procedure",
)


class ProgramGraphContractError(ValueError):
    """Fail-closed violation of a SPAR-007 graph contract."""


class RefactoringNodeKind(str, Enum):
    """Closed SPAR-007 semantic/refactoring node vocabulary."""

    REPOSITORY = "repository"
    PACKAGE = "package"
    MODULE = "module"
    TOP_LEVEL_BLOCK = "top_level_block"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    CALLSITE = "callsite"
    BASIC_BLOCK = "basic_block"
    VARIABLE = "variable"
    STATE_OWNER = "state_owner"
    REGISTRATION = "registration"
    DECORATOR = "decorator"
    RESOURCE = "resource"
    RESOURCE_LIFECYCLE = "resource_lifecycle"
    LOCK = "lock"
    TRANSACTION = "transaction"
    CONFIGURATION = "configuration"
    CONTRACT = "contract"
    CLAIM = "claim"
    PROOF = "proof"
    TEST = "test"
    EXTERNAL_BOUNDARY = "external_boundary"
    ALIAS = "alias"
    PROCEDURE = "procedure"


class RefactoringEdgeKind(str, Enum):
    """Closed SPAR-007 semantic/refactoring edge vocabulary."""

    CONTAINS = "contains"
    DEFINES = "defines"
    MEMBER_OF = "member_of"
    DEPENDS_ON = "depends_on"
    DERIVED_FROM = "derived_from"
    IMPLEMENTS = "implements"
    CALLS = "calls"
    IMPORTS = "imports"
    EXPORTS = "exports"
    REFERENCES = "references"
    ALIASES = "aliases"
    REGISTERS = "registers"
    USES_RESOURCE = "uses_resource"
    TESTS = "tests"
    PROVES = "proves"
    DOCUMENTS = "documents"


class GraphConfidence(str, Enum):
    EXACT = "exact"
    CONSERVATIVE = "conservative"
    HEURISTIC = "heuristic"
    OPAQUE = "opaque"


class GraphEvidenceClass(str, Enum):
    EXACT_STATIC_FACT = "exact_static_fact"
    CONSERVATIVE_MAY_FACT = "conservative_may_fact"
    RUNTIME_OBSERVATION = "runtime_observation"
    REVIEWED_SPECIFICATION = "reviewed_specification"
    TEST = "test"
    PROOF_CANDIDATE = "proof_candidate"
    RECONSTRUCTED_PROOF = "reconstructed_proof"
    COUNTERMODEL = "countermodel"
    REPLAYED_COUNTEREXAMPLE = "replayed_counterexample"
    VECTOR_CANDIDATE = "vector_candidate"
    MODEL_HYPOTHESIS = "model_hypothesis"
    HUMAN_POLICY_DECISION = "human_policy_decision"
    UNKNOWN = "unknown"


class GraphFreshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class ResolverStatus(str, Enum):
    RESOLVED_STATIC = "resolved_static"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    DYNAMIC = "dynamic"


class FrontierReason(str, Enum):
    UNRESOLVED_IDENTITY = "unresolved_identity"
    DYNAMIC_DISPATCH = "dynamic_dispatch"
    MISSING_SOURCE = "missing_source"
    AMBIGUOUS_RESOLUTION = "ambiguous_resolution"
    UNSUPPORTED_CONSTRUCT = "unsupported_construct"
    ANALYZER_GAP = "analyzer_gap"
    OPAQUE_CAPABILITY = "opaque_capability"


DECLARED_NODE_KINDS: Final[frozenset[str]] = frozenset(
    kind.value for kind in RefactoringNodeKind
)
DECLARED_EDGE_KINDS: Final[frozenset[str]] = frozenset(
    kind.value for kind in RefactoringEdgeKind
)

# Structural edges form the Merkle snapshot; cycles among them are illegal.
# Call/import/alias cycles are retained as observed program structure.
STRUCTURAL_EDGE_KINDS: Final[frozenset[str]] = frozenset(
    {
        RefactoringEdgeKind.CONTAINS.value,
        RefactoringEdgeKind.DEFINES.value,
        RefactoringEdgeKind.MEMBER_OF.value,
        RefactoringEdgeKind.DEPENDS_ON.value,
        RefactoringEdgeKind.DERIVED_FROM.value,
        RefactoringEdgeKind.IMPLEMENTS.value,
    }
)
OBSERVED_EDGE_KINDS: Final[frozenset[str]] = DECLARED_EDGE_KINDS - STRUCTURAL_EDGE_KINDS

FORBIDDEN_EDGE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "happens_before",
        "happens-before",
        "happens_after",
        "initialization_order",
        "initialized_before",
        "precedes",
        "precedes_initialization",
        "import_order",
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
_HEURISTIC_EVIDENCE: Final[frozenset[str]] = _CONSERVATIVE_EVIDENCE | frozenset(
    {
        GraphEvidenceClass.VECTOR_CANDIDATE.value,
        GraphEvidenceClass.MODEL_HYPOTHESIS.value,
    }
)
_OPAQUE_EVIDENCE: Final[frozenset[str]] = frozenset(
    {GraphEvidenceClass.UNKNOWN.value}
)

UNRESOLVED_RESOLVER_STATUSES: Final[frozenset[str]] = frozenset(
    {
        ResolverStatus.UNRESOLVED.value,
        ResolverStatus.AMBIGUOUS.value,
        ResolverStatus.UNSUPPORTED.value,
        ResolverStatus.DYNAMIC.value,
    }
)

QUERY_ADAPTER_NODE_KIND_MAP: Final[Mapping[str, str]] = {
    RefactoringNodeKind.REPOSITORY.value: "repository",
    RefactoringNodeKind.MODULE.value: "module",
    RefactoringNodeKind.PACKAGE.value: "module",
    RefactoringNodeKind.FUNCTION.value: "symbol",
    RefactoringNodeKind.METHOD.value: "symbol",
    RefactoringNodeKind.CLASS.value: "symbol",
    RefactoringNodeKind.CALLSITE.value: "call",
    RefactoringNodeKind.CONTRACT.value: "contract",
    RefactoringNodeKind.TEST.value: "test",
    RefactoringNodeKind.PROOF.value: "proof_obligation",
    RefactoringNodeKind.REGISTRATION.value: "mcp_registration",
}


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str:
        raise ProgramGraphContractError(f"{name} must be a string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise ProgramGraphContractError(f"{name} must be trimmed NFC text")
    if not empty and not value:
        raise ProgramGraphContractError(f"{name} must be a nonempty string")
    if any(not char.isprintable() for char in value):
        raise ProgramGraphContractError(f"{name} contains invalid text")
    if len(value) > MAX_TEXT_CHARS:
        raise ProgramGraphContractError(f"{name} exceeds text bound")
    return value


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise ProgramGraphContractError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise ProgramGraphContractError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ProgramGraphContractError(f"{name} must be a boolean")
    return value


def _tree_id(value: Any) -> str:
    text = _text(value, "tree_id")
    if len(text) not in {40, 64} or any(
        char not in "0123456789abcdef" for char in text
    ):
        raise ProgramGraphContractError(
            "tree_id must be a lowercase hex Git tree identity"
        )
    return text


def _module_path(value: Any, *, kind: str) -> str:
    text = _text(value, "module_path", empty=True).replace("\\", "/")
    if kind == RefactoringNodeKind.REPOSITORY.value:
        if text:
            raise ProgramGraphContractError(
                "repository module_path must be empty"
            )
        return text
    if not text:
        raise ProgramGraphContractError("module_path must be a nonempty string")
    if text.startswith("/") or text.startswith("./") or ".." in text.split("/"):
        raise ProgramGraphContractError(
            "module_path must be a relative POSIX repository path"
        )
    if text.endswith("/") or "//" in text:
        raise ProgramGraphContractError("module_path must be a normalized POSIX path")
    return text


def _logical_name(value: Any, name: str) -> str:
    text = _text(value, name)
    if text.startswith("/") or text.startswith("\\") or text.startswith("file:"):
        raise ProgramGraphContractError(f"{name} must not be a local filesystem path")
    if len(text) > 1 and text[1] == ":" and text[0].isalpha():
        raise ProgramGraphContractError(f"{name} must not be a local filesystem path")
    if "\\" in text or text.startswith("~"):
        raise ProgramGraphContractError(f"{name} must not be a local filesystem path")
    return text


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping) or isinstance(data, (str, bytes, bytearray)):
        raise ProgramGraphContractError(f"{name} must be an object")
    extra = set(data) - fields
    missing = fields - set(data)
    if extra & IDENTITY_EXCLUDED_FIELDS:
        raise ProgramGraphContractError(
            f"{name} identity excludes observational fields: "
            f"{sorted(extra & IDENTITY_EXCLUDED_FIELDS)}"
        )
    if extra:
        raise ProgramGraphContractError(f"unknown {name} field: {sorted(extra)}")
    if missing:
        raise ProgramGraphContractError(f"missing {name} field: {sorted(missing)}")
    return dict(data)


def _reject_excluded(payload: Mapping[str, Any], name: str) -> None:
    present = IDENTITY_EXCLUDED_FIELDS & set(payload)
    if present:
        raise ProgramGraphContractError(
            f"{name} identity excludes observational fields: {sorted(present)}"
        )


def _verify_cid(claimed: Any, computed: str, name: str) -> None:
    cid = _cid(claimed, name)
    if cid != computed:
        raise ProgramGraphContractError(f"{name} does not verify")


def _require_dag_json(value: Any, name: str) -> None:
    try:
        validate_structured_value(value)
    except Exception as exc:
        raise ProgramGraphContractError(f"{name} must be strict DAG-JSON") from exc


def _unique_sorted_text(values: Any, name: str, *, limit: int) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ProgramGraphContractError(f"{name} must be a list")
    ordered = tuple(sorted(_text(item, name) for item in values))
    if len(ordered) > limit:
        raise ProgramGraphContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise ProgramGraphContractError(f"{name} must not contain duplicates")
    return ordered


def _confidence_compatible(confidence: str, evidence: str, name: str) -> None:
    if confidence == GraphConfidence.EXACT.value:
        if evidence not in _EXACT_EVIDENCE:
            raise ProgramGraphContractError(
                f"{name} exact confidence requires exact_static_fact evidence"
            )
    elif confidence == GraphConfidence.CONSERVATIVE.value:
        if evidence not in _CONSERVATIVE_EVIDENCE:
            raise ProgramGraphContractError(
                f"{name} conservative confidence has an incompatible evidence_class"
            )
    elif confidence == GraphConfidence.HEURISTIC.value:
        if evidence not in _HEURISTIC_EVIDENCE:
            raise ProgramGraphContractError(
                f"{name} heuristic confidence has an incompatible evidence_class"
            )
    elif confidence == GraphConfidence.OPAQUE.value:
        if evidence not in _OPAQUE_EVIDENCE:
            raise ProgramGraphContractError(
                f"{name} opaque confidence requires unknown evidence_class"
            )


def query_adapter_contract() -> dict[str, str]:
    """Return the body-free query-adapter reuse contract."""

    return {
        "path": QUERY_ADAPTER_PATH,
        "disposition": QUERY_ADAPTER_DISPOSITION,
        "owner": QUERY_ADAPTER_OWNER,
        "interface_concern": QUERY_ADAPTER_INTERFACE_CONCERN,
        "semantic_owner": AUTHORITY_OWNER,
        "happens_before_edges": "absent",
        "initialization_order_edges": "absent",
    }


def graph_cid_profile() -> dict[str, str]:
    return {
        "profile_id": GRAPH_CID_PROFILE,
        "codec": GRAPH_CID_CODEC,
        "rule": "CID identifies exact canonical bytes under declared codec/profile, not universal meaning",
    }


def is_structural_edge_kind(kind: str) -> bool:
    return kind in STRUCTURAL_EDGE_KINDS


def is_forbidden_edge_kind(kind: str) -> bool:
    return kind in FORBIDDEN_EDGE_KINDS


def _detect_structural_cycles(
    node_ids: Sequence[str],
    edges: Sequence["RefactoringGraphEdge"],
) -> None:
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        if edge.kind not in STRUCTURAL_EDGE_KINDS:
            continue
        adjacency[edge.source_id].append(edge.target_id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node_id: WHITE for node_id in node_ids}

    def visit(node_id: str) -> None:
        color[node_id] = GRAY
        for successor in adjacency[node_id]:
            status = color[successor]
            if status == GRAY:
                raise ProgramGraphContractError(
                    "illegal structural cycle among Merkle snapshot edges"
                )
            if status == WHITE:
                visit(successor)
        color[node_id] = BLACK

    for node_id in node_ids:
        if color[node_id] == WHITE:
            visit(node_id)


@dataclass(frozen=True, slots=True)
class GraphBinding:
    """Exact tree, analyzer, and environment binding for one graph view."""

    tree_id: str
    analyzer_id: str
    analyzer_revision: str
    environment_cid: str

    interface: ClassVar[str] = GRAPH_BINDING_INTERFACE
    schema: ClassVar[str] = GRAPH_BINDING_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "tree_id",
            "analyzer_id",
            "analyzer_revision",
            "environment_cid",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "tree_id", _tree_id(self.tree_id))
        object.__setattr__(
            self, "analyzer_id", _logical_name(self.analyzer_id, "analyzer_id")
        )
        object.__setattr__(
            self,
            "analyzer_revision",
            _cid(self.analyzer_revision, "analyzer_revision"),
        )
        object.__setattr__(
            self,
            "environment_cid",
            _cid(self.environment_cid, "environment_cid"),
        )

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": GRAPH_BINDING_SCHEMA,
            "interface": GRAPH_BINDING_INTERFACE,
            "tree_id": self.tree_id,
            "analyzer_id": self.analyzer_id,
            "analyzer_revision": self.analyzer_revision,
            "environment_cid": self.environment_cid,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["binding_cid"] = self.binding_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GraphBinding":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != GRAPH_BINDING_SCHEMA:
            raise ProgramGraphContractError("unsupported GraphBinding schema")
        if payload.pop("interface") != GRAPH_BINDING_INTERFACE:
            raise ProgramGraphContractError("unsupported GraphBinding interface")
        result = cls(**payload)
        _verify_cid(claimed, result.binding_cid, "GraphBinding binding_cid")
        return result


@dataclass(frozen=True, slots=True)
class UnresolvedFrontierItem:
    """One explicit unresolved residual on the graph frontier."""

    subject_id: str
    subject_kind: str
    reason: FrontierReason | str
    evidence_class: GraphEvidenceClass | str
    confidence: GraphConfidence | str
    unresolved_fields: Sequence[str] = ()

    interface: ClassVar[str] = UNRESOLVED_FRONTIER_ITEM_INTERFACE
    schema: ClassVar[str] = UNRESOLVED_FRONTIER_ITEM_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "subject_id",
            "subject_kind",
            "reason",
            "evidence_class",
            "confidence",
            "unresolved_fields",
            "item_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "subject_id", _logical_name(self.subject_id, "subject_id")
        )
        kind = _text(self.subject_kind, "subject_kind")
        if kind not in {"node", "edge"}:
            raise ProgramGraphContractError(
                "subject_kind must be 'node' or 'edge'"
            )
        object.__setattr__(self, "subject_kind", kind)
        reason = _enum(self.reason, FrontierReason, "reason")
        object.__setattr__(self, "reason", reason)
        evidence = _enum(self.evidence_class, GraphEvidenceClass, "evidence_class")
        confidence = _enum(self.confidence, GraphConfidence, "confidence")
        _confidence_compatible(confidence, evidence, "UnresolvedFrontierItem")
        unresolved = _unique_sorted_text(
            list(self.unresolved_fields),
            "unresolved_fields",
            limit=MAX_UNRESOLVED_FIELDS,
        )
        if confidence == GraphConfidence.EXACT.value:
            raise ProgramGraphContractError(
                "unresolved frontier forbids exact confidence"
            )
        if confidence == GraphConfidence.OPAQUE.value and not unresolved:
            raise ProgramGraphContractError(
                "opaque frontier items require unresolved_fields"
            )
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "unresolved_fields", unresolved)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": UNRESOLVED_FRONTIER_ITEM_SCHEMA,
            "interface": UNRESOLVED_FRONTIER_ITEM_INTERFACE,
            "subject_id": self.subject_id,
            "subject_kind": self.subject_kind,
            "reason": self.reason,
            "evidence_class": self.evidence_class,
            "confidence": self.confidence,
            "unresolved_fields": list(self.unresolved_fields),
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def item_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["item_cid"] = self.item_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UnresolvedFrontierItem":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("item_cid")
        if payload.pop("schema") != UNRESOLVED_FRONTIER_ITEM_SCHEMA:
            raise ProgramGraphContractError(
                "unsupported UnresolvedFrontierItem schema"
            )
        if payload.pop("interface") != UNRESOLVED_FRONTIER_ITEM_INTERFACE:
            raise ProgramGraphContractError(
                "unsupported UnresolvedFrontierItem interface"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.item_cid, "UnresolvedFrontierItem item_cid")
        return result


def _coerce_frontier_item(
    value: UnresolvedFrontierItem | Mapping[str, Any],
) -> UnresolvedFrontierItem:
    if isinstance(value, UnresolvedFrontierItem):
        return value
    if isinstance(value, Mapping):
        if "item_cid" in value:
            return UnresolvedFrontierItem.from_dict(value)
        return UnresolvedFrontierItem(**dict(value))
    raise ProgramGraphContractError(
        "frontier item must be an UnresolvedFrontierItem"
    )


@dataclass(frozen=True, slots=True)
class UnresolvedFrontier:
    """Explicit omitted/unresolved residual set; never inferred as empty."""

    items: Sequence[UnresolvedFrontierItem | Mapping[str, Any]] = ()

    interface: ClassVar[str] = UNRESOLVED_FRONTIER_INTERFACE
    schema: ClassVar[str] = UNRESOLVED_FRONTIER_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "items",
            "frontier_cid",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.items, (list, tuple)):
            raise ProgramGraphContractError("items must be a list")
        coerced = tuple(_coerce_frontier_item(item) for item in self.items)
        if len(coerced) > MAX_FRONTIER_ITEMS:
            raise ProgramGraphContractError("unresolved frontier exceeds maximum length")
        ordered = tuple(
            sorted(
                coerced,
                key=lambda item: (item.subject_id, item.subject_kind, item.reason),
            )
        )
        keys = [(item.subject_id, item.subject_kind, item.reason) for item in ordered]
        if len(keys) != len(set(keys)):
            raise ProgramGraphContractError(
                "unresolved frontier must not contain duplicate subject/reason pairs"
            )
        object.__setattr__(self, "items", ordered)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": UNRESOLVED_FRONTIER_SCHEMA,
            "interface": UNRESOLVED_FRONTIER_INTERFACE,
            "items": [item.to_dict() for item in self.items],
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def frontier_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def explicit(self) -> bool:
        return True

    @property
    def subject_ids(self) -> frozenset[str]:
        return frozenset(item.subject_id for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["frontier_cid"] = self.frontier_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UnresolvedFrontier":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("frontier_cid")
        if payload.pop("schema") != UNRESOLVED_FRONTIER_SCHEMA:
            raise ProgramGraphContractError("unsupported UnresolvedFrontier schema")
        if payload.pop("interface") != UNRESOLVED_FRONTIER_INTERFACE:
            raise ProgramGraphContractError(
                "unsupported UnresolvedFrontier interface"
            )
        result = cls(items=payload["items"])
        _verify_cid(claimed, result.frontier_cid, "UnresolvedFrontier frontier_cid")
        return result


@dataclass(frozen=True, slots=True)
class RefactoringGraphNode:
    """Typed semantic/refactoring node bound to capsule or identity CIDs."""

    node_id: str
    kind: RefactoringNodeKind | str
    qualified_name: str
    module_path: str
    evidence_class: GraphEvidenceClass | str = GraphEvidenceClass.EXACT_STATIC_FACT
    confidence: GraphConfidence | str = GraphConfidence.EXACT
    freshness: GraphFreshness | str = GraphFreshness.FRESH
    capsule_cid: str | None = None
    identity_set_cid: str | None = None

    interface: ClassVar[str] = REFACTORING_GRAPH_NODE_INTERFACE
    schema: ClassVar[str] = REFACTORING_GRAPH_NODE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "node_id",
            "kind",
            "qualified_name",
            "module_path",
            "evidence_class",
            "confidence",
            "freshness",
            "capsule_cid",
            "identity_set_cid",
            "node_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _logical_name(self.node_id, "node_id"))
        kind = _enum(self.kind, RefactoringNodeKind, "kind")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "qualified_name",
            _logical_name(self.qualified_name, "qualified_name"),
        )
        object.__setattr__(self, "module_path", _module_path(self.module_path, kind=kind))
        evidence = _enum(self.evidence_class, GraphEvidenceClass, "evidence_class")
        confidence = _enum(self.confidence, GraphConfidence, "confidence")
        _confidence_compatible(confidence, evidence, "RefactoringGraphNode")
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(
            self, "freshness", _enum(self.freshness, GraphFreshness, "freshness")
        )
        object.__setattr__(
            self, "capsule_cid", _optional_cid(self.capsule_cid, "capsule_cid")
        )
        object.__setattr__(
            self,
            "identity_set_cid",
            _optional_cid(self.identity_set_cid, "identity_set_cid"),
        )
        if kind in CAPSULE_ALIGNED_NODE_KINDS and self.capsule_cid is None:
            if confidence == GraphConfidence.EXACT.value:
                raise ProgramGraphContractError(
                    "exact capsule-aligned nodes require capsule_cid"
                )

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": REFACTORING_GRAPH_NODE_SCHEMA,
            "interface": REFACTORING_GRAPH_NODE_INTERFACE,
            "node_id": self.node_id,
            "kind": self.kind,
            "qualified_name": self.qualified_name,
            "module_path": self.module_path,
            "evidence_class": self.evidence_class,
            "confidence": self.confidence,
            "freshness": self.freshness,
            "capsule_cid": self.capsule_cid,
            "identity_set_cid": self.identity_set_cid,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def node_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def requires_frontier(self) -> bool:
        return self.confidence in {
            GraphConfidence.OPAQUE.value,
            GraphConfidence.HEURISTIC.value,
        } or self.evidence_class in {
            GraphEvidenceClass.UNKNOWN.value,
            GraphEvidenceClass.VECTOR_CANDIDATE.value,
            GraphEvidenceClass.MODEL_HYPOTHESIS.value,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["node_cid"] = self.node_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RefactoringGraphNode":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("node_cid")
        if payload.pop("schema") != REFACTORING_GRAPH_NODE_SCHEMA:
            raise ProgramGraphContractError(
                "unsupported RefactoringGraphNode schema"
            )
        if payload.pop("interface") != REFACTORING_GRAPH_NODE_INTERFACE:
            raise ProgramGraphContractError(
                "unsupported RefactoringGraphNode interface"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.node_cid, "RefactoringGraphNode node_cid")
        return result


@dataclass(frozen=True, slots=True)
class RefactoringGraphEdge:
    """Typed semantic/refactoring edge. Happens-before is not in this vocabulary."""

    source_id: str
    target_id: str
    kind: RefactoringEdgeKind | str
    evidence_class: GraphEvidenceClass | str = GraphEvidenceClass.EXACT_STATIC_FACT
    confidence: GraphConfidence | str = GraphConfidence.EXACT
    resolver_status: ResolverStatus | str = ResolverStatus.RESOLVED_STATIC

    interface: ClassVar[str] = REFACTORING_GRAPH_EDGE_INTERFACE
    schema: ClassVar[str] = REFACTORING_GRAPH_EDGE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "source_id",
            "target_id",
            "kind",
            "evidence_class",
            "confidence",
            "resolver_status",
            "edge_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_id", _logical_name(self.source_id, "source_id")
        )
        object.__setattr__(
            self, "target_id", _logical_name(self.target_id, "target_id")
        )
        raw_kind = self.kind
        if isinstance(raw_kind, str) and is_forbidden_edge_kind(raw_kind):
            raise ProgramGraphContractError(
                f"forbidden edge kind {raw_kind!r}; happens-before and "
                "initialization-order edges are absent from SPAR-007"
            )
        kind = _enum(self.kind, RefactoringEdgeKind, "kind")
        object.__setattr__(self, "kind", kind)
        evidence = _enum(self.evidence_class, GraphEvidenceClass, "evidence_class")
        confidence = _enum(self.confidence, GraphConfidence, "confidence")
        _confidence_compatible(confidence, evidence, "RefactoringGraphEdge")
        status = _enum(self.resolver_status, ResolverStatus, "resolver_status")
        if confidence == GraphConfidence.EXACT.value:
            if status != ResolverStatus.RESOLVED_STATIC.value:
                raise ProgramGraphContractError(
                    "exact edges require resolved_static resolver_status"
                )
        if (
            status in UNRESOLVED_RESOLVER_STATUSES
            and confidence == GraphConfidence.EXACT.value
        ):
            raise ProgramGraphContractError(
                "unresolved resolver_status forbids exact confidence"
            )
        if kind in STRUCTURAL_EDGE_KINDS and status in UNRESOLVED_RESOLVER_STATUSES:
            if confidence == GraphConfidence.EXACT.value:
                raise ProgramGraphContractError(
                    "structural edges cannot be exact while unresolved"
                )
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "resolver_status", status)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": REFACTORING_GRAPH_EDGE_SCHEMA,
            "interface": REFACTORING_GRAPH_EDGE_INTERFACE,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "evidence_class": self.evidence_class,
            "confidence": self.confidence,
            "resolver_status": self.resolver_status,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def edge_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def edge_key(self) -> tuple[str, str, str]:
        return (self.source_id, self.kind, self.target_id)

    @property
    def structural(self) -> bool:
        return self.kind in STRUCTURAL_EDGE_KINDS

    @property
    def requires_frontier(self) -> bool:
        return (
            self.resolver_status in UNRESOLVED_RESOLVER_STATUSES
            or self.confidence
            in {
                GraphConfidence.OPAQUE.value,
                GraphConfidence.HEURISTIC.value,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["edge_cid"] = self.edge_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RefactoringGraphEdge":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("edge_cid")
        if payload.pop("schema") != REFACTORING_GRAPH_EDGE_SCHEMA:
            raise ProgramGraphContractError(
                "unsupported RefactoringGraphEdge schema"
            )
        if payload.pop("interface") != REFACTORING_GRAPH_EDGE_INTERFACE:
            raise ProgramGraphContractError(
                "unsupported RefactoringGraphEdge interface"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.edge_cid, "RefactoringGraphEdge edge_cid")
        return result


def _coerce_binding(value: GraphBinding | Mapping[str, Any]) -> GraphBinding:
    if isinstance(value, GraphBinding):
        return value
    if isinstance(value, Mapping):
        if "binding_cid" in value:
            return GraphBinding.from_dict(value)
        return GraphBinding(**dict(value))
    raise ProgramGraphContractError("binding must be a GraphBinding")


def _coerce_node(value: RefactoringGraphNode | Mapping[str, Any]) -> RefactoringGraphNode:
    if isinstance(value, RefactoringGraphNode):
        return value
    if isinstance(value, Mapping):
        if "node_cid" in value:
            return RefactoringGraphNode.from_dict(value)
        return RefactoringGraphNode(**dict(value))
    raise ProgramGraphContractError("node must be a RefactoringGraphNode")


def _coerce_edge(value: RefactoringGraphEdge | Mapping[str, Any]) -> RefactoringGraphEdge:
    if isinstance(value, RefactoringGraphEdge):
        return value
    if isinstance(value, Mapping):
        raw_kind = value.get("kind")
        if isinstance(raw_kind, str) and is_forbidden_edge_kind(raw_kind):
            raise ProgramGraphContractError(
                f"forbidden edge kind {raw_kind!r}; happens-before and "
                "initialization-order edges are absent from SPAR-007"
            )
        if "edge_cid" in value:
            return RefactoringGraphEdge.from_dict(value)
        return RefactoringGraphEdge(**dict(value))
    raise ProgramGraphContractError("edge must be a RefactoringGraphEdge")


def _coerce_frontier(
    value: UnresolvedFrontier | Mapping[str, Any] | Sequence[Any] | None,
) -> UnresolvedFrontier:
    if value is None:
        return UnresolvedFrontier()
    if isinstance(value, UnresolvedFrontier):
        return value
    if isinstance(value, Mapping):
        if "frontier_cid" in value:
            return UnresolvedFrontier.from_dict(value)
        return UnresolvedFrontier(**dict(value))
    if isinstance(value, (list, tuple)):
        return UnresolvedFrontier(items=value)
    raise ProgramGraphContractError("unresolved_frontier must be an UnresolvedFrontier")


@dataclass(frozen=True, slots=True)
class SemanticRefactoringGraphView:
    """Typed static program/refactoring graph bound to exact current roots.

    Querying the accelerator program graph remains a reuse adapter.  This
    view owns semantic/refactoring meaning and cannot authorize completion.
    """

    binding: GraphBinding | Mapping[str, Any]
    nodes: Sequence[RefactoringGraphNode | Mapping[str, Any]] = ()
    edges: Sequence[RefactoringGraphEdge | Mapping[str, Any]] = ()
    unresolved_frontier: (
        UnresolvedFrontier | Mapping[str, Any] | Sequence[Any] | None
    ) = None
    query_adapter_path: str = QUERY_ADAPTER_PATH

    interface: ClassVar[str] = SEMANTIC_REFACTORING_GRAPH_VIEW_INTERFACE
    schema: ClassVar[str] = SEMANTIC_REFACTORING_GRAPH_VIEW_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "binding",
            "nodes",
            "edges",
            "unresolved_frontier",
            "query_adapter_path",
            "graph_view_cid",
        }
    )

    def __post_init__(self) -> None:
        binding = _coerce_binding(self.binding)
        object.__setattr__(self, "binding", binding)
        if not isinstance(self.nodes, (list, tuple)):
            raise ProgramGraphContractError("nodes must be a list")
        if not isinstance(self.edges, (list, tuple)):
            raise ProgramGraphContractError("edges must be a list")
        nodes = tuple(_coerce_node(node) for node in self.nodes)
        if len(nodes) > MAX_NODES:
            raise ProgramGraphContractError("nodes exceed maximum length")
        nodes = tuple(sorted(nodes, key=lambda node: node.node_id))
        node_ids = tuple(node.node_id for node in nodes)
        if len(node_ids) != len(set(node_ids)):
            raise ProgramGraphContractError("nodes must not contain duplicate node_id")
        object.__setattr__(self, "nodes", nodes)

        edges = tuple(_coerce_edge(edge) for edge in self.edges)
        if len(edges) > MAX_EDGES:
            raise ProgramGraphContractError("edges exceed maximum length")
        edges = tuple(sorted(edges, key=lambda edge: edge.edge_key))
        keys = tuple(edge.edge_key for edge in edges)
        if len(keys) != len(set(keys)):
            raise ProgramGraphContractError(
                "edges must not contain duplicate source/kind/target triples"
            )
        present = set(node_ids)
        for edge in edges:
            if edge.source_id not in present or edge.target_id not in present:
                raise ProgramGraphContractError(
                    "edge references a node that is not present in the graph"
                )
        _detect_structural_cycles(node_ids, edges)
        object.__setattr__(self, "edges", edges)

        adapter = _text(self.query_adapter_path, "query_adapter_path")
        if adapter != QUERY_ADAPTER_PATH:
            raise ProgramGraphContractError(
                "query_adapter_path must remain the current program-graph adapter"
            )
        object.__setattr__(self, "query_adapter_path", adapter)

        frontier = _coerce_frontier(self.unresolved_frontier)
        frontier_ids = frontier.subject_ids
        hidden_nodes = [
            node.node_id
            for node in nodes
            if node.requires_frontier and node.node_id not in frontier_ids
        ]
        hidden_edges = [
            edge
            for edge in edges
            if edge.requires_frontier
            and edge.source_id not in frontier_ids
            and edge.target_id not in frontier_ids
            and f"{edge.source_id}->{edge.kind}->{edge.target_id}" not in frontier_ids
        ]
        if hidden_nodes or hidden_edges:
            raise ProgramGraphContractError(
                "unresolved residuals must appear on the explicit frontier"
            )
        unknown_subjects = sorted(
            subject
            for subject in frontier_ids
            if subject not in present and "->" not in subject
        )
        if unknown_subjects:
            raise ProgramGraphContractError(
                "frontier subject_id must name a graph node or composite edge"
            )
        object.__setattr__(self, "unresolved_frontier", frontier)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": SEMANTIC_REFACTORING_GRAPH_VIEW_SCHEMA,
            "interface": SEMANTIC_REFACTORING_GRAPH_VIEW_INTERFACE,
            "binding": self.binding.to_dict(),
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "unresolved_frontier": self.unresolved_frontier.to_dict(),
            "query_adapter_path": self.query_adapter_path,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def graph_view_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def tree_id(self) -> str:
        return self.binding.tree_id

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(node.node_id for node in self.nodes)

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["graph_view_cid"] = self.graph_view_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticRefactoringGraphView":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("graph_view_cid")
        if payload.pop("schema") != SEMANTIC_REFACTORING_GRAPH_VIEW_SCHEMA:
            raise ProgramGraphContractError(
                "unsupported SemanticRefactoringGraphView schema"
            )
        if payload.pop("interface") != SEMANTIC_REFACTORING_GRAPH_VIEW_INTERFACE:
            raise ProgramGraphContractError(
                "unsupported SemanticRefactoringGraphView interface"
            )
        result = cls(**payload)
        _verify_cid(
            claimed,
            result.graph_view_cid,
            "SemanticRefactoringGraphView graph_view_cid",
        )
        return result

    def nodes_for_kind(self, kind: RefactoringNodeKind | str) -> tuple[RefactoringGraphNode, ...]:
        resolved = _enum(kind, RefactoringNodeKind, "kind")
        return tuple(node for node in self.nodes if node.kind == resolved)

    def edges_for_kind(self, kind: RefactoringEdgeKind | str) -> tuple[RefactoringGraphEdge, ...]:
        if isinstance(kind, str) and is_forbidden_edge_kind(kind):
            raise ProgramGraphContractError(
                f"forbidden edge kind {kind!r}; happens-before and "
                "initialization-order edges are absent from SPAR-007"
            )
        resolved = _enum(kind, RefactoringEdgeKind, "kind")
        return tuple(edge for edge in self.edges if edge.kind == resolved)

    def exact_static_nodes(self) -> tuple[RefactoringGraphNode, ...]:
        return tuple(
            node
            for node in self.nodes
            if node.confidence == GraphConfidence.EXACT.value
            and node.evidence_class == GraphEvidenceClass.EXACT_STATIC_FACT.value
        )

    def may_fact_edges(self) -> tuple[RefactoringGraphEdge, ...]:
        return tuple(
            edge
            for edge in self.edges
            if edge.evidence_class == GraphEvidenceClass.CONSERVATIVE_MAY_FACT.value
            or edge.confidence == GraphConfidence.CONSERVATIVE.value
        )

    def query_adapter_node_kind(self, kind: RefactoringNodeKind | str) -> str | None:
        resolved = _enum(kind, RefactoringNodeKind, "kind")
        return QUERY_ADAPTER_NODE_KIND_MAP.get(resolved)


def build_semantic_refactoring_graph_view(
    *,
    binding: GraphBinding | Mapping[str, Any],
    nodes: Sequence[RefactoringGraphNode | Mapping[str, Any]] = (),
    edges: Sequence[RefactoringGraphEdge | Mapping[str, Any]] = (),
    unresolved_frontier: (
        UnresolvedFrontier | Mapping[str, Any] | Sequence[Any] | None
    ) = None,
    query_adapter_path: str = QUERY_ADAPTER_PATH,
) -> SemanticRefactoringGraphView:
    """Construct one closed SemanticRefactoringGraphView@1 record."""

    return SemanticRefactoringGraphView(
        binding=binding,
        nodes=nodes,
        edges=edges,
        unresolved_frontier=unresolved_frontier,
        query_adapter_path=query_adapter_path,
    )


def encode_canonical_graph_view(view: SemanticRefactoringGraphView) -> dict[str, Any]:
    return view.to_dict()


def decode_canonical_graph_view(
    payload: Mapping[str, Any],
) -> SemanticRefactoringGraphView:
    return SemanticRefactoringGraphView.from_dict(payload)


def provider_free_exports() -> tuple[str, ...]:
    """Return the sorted public export surface (no provider or model names)."""

    return tuple(sorted(__all__))


__all__ = [
    "AUTHORITY",
    "AUTHORITY_OWNER",
    "CAPSULE_ALIGNED_NODE_KINDS",
    "DECLARED_EDGE_KINDS",
    "DECLARED_NODE_KINDS",
    "DUCKLAKE_IS_AUTHORITY",
    "FORBIDDEN_EDGE_KINDS",
    "GOAL_ID",
    "GRAPH_BINDING_INTERFACE",
    "GRAPH_BINDING_SCHEMA",
    "GRAPH_CAN_AUTHORIZE_COMPLETION",
    "GRAPH_CAN_AUTHORIZE_TRANSITION",
    "GRAPH_CAN_CREATE_AUTHORITY",
    "GRAPH_CID_CODEC",
    "GRAPH_CID_PROFILE",
    "GRAPH_CONTRACT_VERSION",
    "IDENTITY_EXCLUDED_FIELDS",
    "MARKDOWN_IS_NOT_COMPLETION",
    "MODEL_OUTPUT_IS_PROPOSAL_ONLY",
    "OBSERVED_EDGE_KINDS",
    "PLAN_NODE_KINDS",
    "PROGRAM",
    "QUERY_ADAPTER_DISPOSITION",
    "QUERY_ADAPTER_INTERFACE_CONCERN",
    "QUERY_ADAPTER_NODE_KIND_MAP",
    "QUERY_ADAPTER_OWNER",
    "QUERY_ADAPTER_PATH",
    "REFACTORING_GRAPH_EDGE_INTERFACE",
    "REFACTORING_GRAPH_EDGE_SCHEMA",
    "REFACTORING_GRAPH_NODE_INTERFACE",
    "REFACTORING_GRAPH_NODE_SCHEMA",
    "SEMANTIC_REFACTORING_GRAPH_VIEW_INTERFACE",
    "SEMANTIC_REFACTORING_GRAPH_VIEW_SCHEMA",
    "STRUCTURAL_EDGE_KINDS",
    "TASK_ID",
    "TEST_PASS_IS_NOT_COMPLETION",
    "UNRESOLVED_FRONTIER_INTERFACE",
    "UNRESOLVED_FRONTIER_ITEM_INTERFACE",
    "UNRESOLVED_FRONTIER_ITEM_SCHEMA",
    "UNRESOLVED_FRONTIER_SCHEMA",
    "VECTOR_SIMILARITY_IS_AUTHORITY",
    "WORKER_SELF_APPROVAL",
    "FrontierReason",
    "GraphBinding",
    "GraphConfidence",
    "GraphEvidenceClass",
    "GraphFreshness",
    "ProgramGraphContractError",
    "RefactoringEdgeKind",
    "RefactoringGraphEdge",
    "RefactoringGraphNode",
    "RefactoringNodeKind",
    "ResolverStatus",
    "SemanticRefactoringGraphView",
    "UnresolvedFrontier",
    "UnresolvedFrontierItem",
    "build_semantic_refactoring_graph_view",
    "decode_canonical_graph_view",
    "encode_canonical_graph_view",
    "graph_cid_profile",
    "is_forbidden_edge_kind",
    "is_structural_edge_kind",
    "provider_free_exports",
    "query_adapter_contract",
]

assert SEMANTIC_REFACTORING_GRAPH_VIEW_INTERFACE == "SemanticRefactoringGraphView@1"
assert TASK_ID == "SPAR-007"
assert GRAPH_CAN_AUTHORIZE_COMPLETION is False
assert MODEL_OUTPUT_IS_PROPOSAL_ONLY is True
assert "FunctionSemanticCapsule" in _FORBIDDEN_CAPSULE_TYPE_NAMES
assert QUERY_ADAPTER_PATH.endswith("analysis/program_graph.py")
