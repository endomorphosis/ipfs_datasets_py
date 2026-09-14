"""SPAR-010 initialization-order and import-time effect graph.

This module extends datasets formal semantic authority with
``InitializationOrderGraph@1`` and ``InitializationStateMachine@1``.

Happens-before and initialization-order relations are owned here.  SPAR-007
forbids those edge kinds on ``SemanticRefactoringGraphView@1``; SPAR-010 adds
them under datasets semantic authority without minting a second program-graph
vocabulary, capsule family, or completion authority.

Normative rules:

* Top-level execution is partitioned into content-addressed blocks.
* Ordering, cycles, and import-time effects stay explicit.
* Explicit initialization candidates are synthesized, never hidden.
* Hermetic observation profiles bind without upgrading runtime evidence to
  exact static fact.
* Unsupported required behavior is a typed terminal and is never success.
* Observational metadata is excluded from identity.
* Model output remains nomination-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import ast
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    PROFILE_ID,
    STRUCTURED_CODEC,
    cid_for_bytes,
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.semantic_refactoring.compatibility import (
    EvidenceClass,
    ImportEagerness,
    InitializationEffectKind,
    SupportStatus,
)
from ipfs_datasets_py.semantic_refactoring.dynamic_frontier import (
    DEFAULT_HERMETIC_PROFILE,
    NETWORK_DENY,
)
from ipfs_datasets_py.semantic_refactoring.program_graph import (
    FORBIDDEN_EDGE_KINDS as SPAR007_FORBIDDEN_EDGE_KINDS,
    QUERY_ADAPTER_PATH,
)


TASK_ID: Final[str] = "SPAR-010"
GOAL_ID: Final[str] = "SPAR-G022"
PROGRAM: Final[str] = "semantic-preserving-autonomous-remodularization-v1"
AUTHORITY: Final[str] = "formal semantic authority"
AUTHORITY_OWNER: Final[str] = "ipfs_datasets_py"
ANALYZER_ID: Final[str] = "spar-010-initialization"

INITIALIZATION_ORDER_GRAPH_INTERFACE: Final[str] = "InitializationOrderGraph@1"
INITIALIZATION_STATE_MACHINE_INTERFACE: Final[str] = "InitializationStateMachine@1"
INITIALIZATION_GRAPH_NODE_INTERFACE: Final[str] = "InitializationGraphNode@1"
INITIALIZATION_ORDER_EDGE_INTERFACE: Final[str] = "InitializationOrderEdge@1"
INITIALIZATION_CANDIDATE_INTERFACE: Final[str] = "InitializationCandidate@1"
INITIALIZATION_STATE_TRANSITION_INTERFACE: Final[str] = (
    "InitializationStateTransition@1"
)
INITIALIZATION_TERMINAL_INTERFACE: Final[str] = "InitializationTerminal@1"

INITIALIZATION_ORDER_GRAPH_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.initialization-order-graph@1"
)
INITIALIZATION_STATE_MACHINE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.initialization-state-machine@1"
)
INITIALIZATION_GRAPH_NODE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.initialization-graph-node@1"
)
INITIALIZATION_ORDER_EDGE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.initialization-order-edge@1"
)
INITIALIZATION_CANDIDATE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.initialization-candidate@1"
)
INITIALIZATION_STATE_TRANSITION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.initialization-state-transition@1"
)
INITIALIZATION_TERMINAL_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.initialization-terminal@1"
)

INIT_CONTRACT_VERSION: Final[str] = "1"
INIT_CID_CODEC: Final[str] = STRUCTURED_CODEC
INIT_CID_PROFILE: Final[str] = PROFILE_ID

INIT_CAN_AUTHORIZE_TRANSITION: Final[bool] = False
INIT_CAN_AUTHORIZE_COMPLETION: Final[bool] = False
INIT_CAN_CREATE_AUTHORITY: Final[bool] = False
VECTOR_SIMILARITY_IS_AUTHORITY: Final[bool] = False
MODEL_OUTPUT_IS_PROPOSAL_ONLY: Final[bool] = True
TEST_PASS_IS_NOT_COMPLETION: Final[bool] = True
MARKDOWN_IS_NOT_COMPLETION: Final[bool] = True
WORKER_SELF_APPROVAL: Final[bool] = False
DUCKLAKE_IS_AUTHORITY: Final[bool] = False
RUNTIME_OBSERVATION_IS_NOT_STATIC_FACT: Final[bool] = True

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_NODES: Final[int] = 16_384
MAX_EDGES: Final[int] = 65_536
MAX_CANDIDATES: Final[int] = 4_096
MAX_TRANSITIONS: Final[int] = 256
MAX_CYCLE_LENGTH: Final[int] = 4_096

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
        "current_state",
        "runtime_state",
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

_REGISTRATION_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "register",
        "append",
        "setdefault",
        "update",
        "add_command",
        "command",
        "route",
        "include_router",
    }
)
_RESOURCE_NAMES: Final[frozenset[str]] = frozenset(
    {"open", "connect", "urlopen", "Session", "Client", "socket"}
)
_NETWORK_NAMES: Final[frozenset[str]] = frozenset(
    {"urlopen", "request", "get", "post", "urlretrieve"}
)
_SIGNAL_NAMES: Final[frozenset[str]] = frozenset({"register", "signal", "atexit"})
_EVAL_NAMES: Final[frozenset[str]] = frozenset({"eval", "exec", "compile"})
_DYNAMIC_IMPORT_NAMES: Final[frozenset[str]] = frozenset(
    {"__import__", "import_module"}
)
_CLI_DECORATORS: Final[frozenset[str]] = frozenset(
    {"command", "group", "click", "app", "typer"}
)


class InitializationContractError(ValueError):
    """Fail-closed violation of a SPAR-010 initialization-order contract."""


class InitializationRelationKind(str, Enum):
    """Order relations owned by SPAR-010, forbidden on SPAR-007."""

    HAPPENS_BEFORE = "happens_before"
    INITIALIZATION_ORDER = "initialization_order"


class InitializationNodeKind(str, Enum):
    TOP_LEVEL_BLOCK = "top_level_block"


class InitializationConfidence(str, Enum):
    EXACT = "exact"
    CONSERVATIVE = "conservative"
    OPAQUE = "opaque"


class InitializationCandidateKind(str, Enum):
    PRESERVE_ORDER = "preserve_order"
    EXPLICIT_INITIALIZER = "explicit_initializer"
    LAZY_IMPORT = "lazy_import"


class InitializationMachineState(str, Enum):
    UNINITIALIZED = "uninitialized"
    IMPORTING = "importing"
    EXECUTING = "executing"
    INITIALIZED = "initialized"
    CYCLIC = "cyclic"
    UNSUPPORTED = "unsupported"
    INCOMPLETE = "incomplete"


class InitializationMachineEvent(str, Enum):
    START = "start"
    EXECUTE = "execute"
    ADVANCE = "advance"
    COMPLETE = "complete"
    CYCLE = "cycle"
    UNSUPPORTED = "unsupported"
    INCOMPLETE = "incomplete"


class InitializationTerminalKind(str, Enum):
    ADMITTED = "admitted"
    CYCLIC = "cyclic"
    UNSUPPORTED_REQUIRED = "unsupported_required"
    UNKNOWN_REQUIRED = "unknown_required"
    INCOMPLETE_CONTRACT = "incomplete_contract"
    CONFLICT = "conflict"


DECLARED_RELATION_KINDS: Final[frozenset[str]] = frozenset(
    kind.value for kind in InitializationRelationKind
)
DECLARED_NODE_KINDS: Final[frozenset[str]] = frozenset(
    kind.value for kind in InitializationNodeKind
)
OWNED_SPAR007_FORBIDDEN_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        InitializationRelationKind.HAPPENS_BEFORE.value,
        InitializationRelationKind.INITIALIZATION_ORDER.value,
    }
)

MACHINE_STATES: Final[tuple[str, ...]] = tuple(
    state.value for state in InitializationMachineState
)
ACCEPTING_STATES: Final[frozenset[str]] = frozenset(
    {InitializationMachineState.INITIALIZED.value}
)
FAILURE_STATES: Final[frozenset[str]] = frozenset(
    {
        InitializationMachineState.CYCLIC.value,
        InitializationMachineState.UNSUPPORTED.value,
        InitializationMachineState.INCOMPLETE.value,
    }
)
NONTERMINAL_STATES: Final[tuple[str, ...]] = (
    InitializationMachineState.UNINITIALIZED.value,
    InitializationMachineState.IMPORTING.value,
    InitializationMachineState.EXECUTING.value,
)

_EXACT_EVIDENCE: Final[frozenset[str]] = frozenset(
    {EvidenceClass.EXACT_STATIC_FACT.value}
)
_CONSERVATIVE_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        EvidenceClass.CONSERVATIVE_MAY_FACT.value,
        EvidenceClass.RUNTIME_OBSERVATION.value,
    }
)


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str:
        raise InitializationContractError(f"{name} must be a string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise InitializationContractError(f"{name} must be trimmed NFC text")
    if not empty and not value:
        raise InitializationContractError(f"{name} must be a nonempty string")
    if any(not char.isprintable() for char in value):
        raise InitializationContractError(f"{name} contains invalid text")
    if len(value) > MAX_TEXT_CHARS:
        raise InitializationContractError(f"{name} exceeds text bound")
    return value


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise InitializationContractError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise InitializationContractError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise InitializationContractError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise InitializationContractError(f"{name} must be a nonnegative integer")
    return value


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1:
        raise InitializationContractError(f"{name} must be a positive integer")
    return value


def _tree_id(value: Any) -> str:
    text = _text(value, "tree_id")
    if len(text) not in {40, 64} or any(
        char not in "0123456789abcdef" for char in text
    ):
        raise InitializationContractError(
            "tree_id must be a lowercase hex Git tree identity"
        )
    return text


def _repo_relative_path(value: Any, name: str) -> str:
    text = _text(value, name)
    if text.startswith("/") or text.startswith("\\"):
        raise InitializationContractError(f"{name} must be repository-relative")
    parts = text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise InitializationContractError(f"{name} is not a POSIX repository path")
    return text


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping) or isinstance(data, (str, bytes, bytearray)):
        raise InitializationContractError(f"{name} must be a mapping")
    extra = set(data) - fields
    missing = fields - set(data)
    if extra & IDENTITY_EXCLUDED_FIELDS:
        raise InitializationContractError(
            f"{name} identity excludes observational fields: "
            f"{sorted(extra & IDENTITY_EXCLUDED_FIELDS)}"
        )
    if extra:
        raise InitializationContractError(f"unknown {name} field: {sorted(extra)}")
    if missing:
        raise InitializationContractError(f"missing {name} field: {sorted(missing)}")
    return dict(data)


def _reject_excluded(payload: Mapping[str, Any], name: str) -> None:
    present = IDENTITY_EXCLUDED_FIELDS & set(payload)
    if present:
        raise InitializationContractError(
            f"{name} identity excludes observational fields: {sorted(present)}"
        )


def _require_dag_json(value: Any, name: str) -> None:
    try:
        validate_structured_value(value)
    except Exception as exc:
        raise InitializationContractError(f"{name} must be strict DAG-JSON") from exc


def _verify_cid(claimed: Any, computed: str, name: str) -> None:
    cid = _cid(claimed, name)
    if cid != computed:
        raise InitializationContractError(f"{name} does not verify")


def _unique_sorted(values: Iterable[str], name: str) -> tuple[str, ...]:
    ordered = tuple(sorted(_text(item, name, empty=True) for item in values if item != ""))
    ordered = tuple(item for item in ordered if item)
    if len(ordered) != len(set(ordered)):
        raise InitializationContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_enums(
    values: Iterable[str], enum_type: type[Enum], name: str
) -> tuple[str, ...]:
    return _unique_sorted((_enum(item, enum_type, name) for item in values), name)


def _confidence_compatible(confidence: str, evidence: str, name: str) -> None:
    if evidence == EvidenceClass.RUNTIME_OBSERVATION.value:
        if confidence == InitializationConfidence.EXACT.value:
            raise InitializationContractError(
                "runtime observation cannot be exact_static_fact"
            )
    if confidence == InitializationConfidence.EXACT.value:
        if evidence not in _EXACT_EVIDENCE:
            raise InitializationContractError(
                f"{name} exact confidence requires exact_static_fact evidence"
            )
    elif confidence == InitializationConfidence.CONSERVATIVE.value:
        if evidence not in _CONSERVATIVE_EVIDENCE and evidence not in _EXACT_EVIDENCE:
            raise InitializationContractError(
                f"{name} conservative confidence has an incompatible evidence_class"
            )
    elif confidence == InitializationConfidence.OPAQUE.value:
        if evidence != EvidenceClass.RUNTIME_OBSERVATION.value and evidence not in {
            EvidenceClass.CONSERVATIVE_MAY_FACT.value
        }:
            raise InitializationContractError(
                f"{name} opaque confidence has an incompatible evidence_class"
            )


def relation_ownership_contract() -> dict[str, str]:
    """Body-free contract: SPAR-010 owns order relations SPAR-007 forbids."""

    missing = OWNED_SPAR007_FORBIDDEN_RELATIONS - SPAR007_FORBIDDEN_EDGE_KINDS
    if missing:
        raise InitializationContractError(
            f"SPAR-007 must forbid SPAR-010 relations: {sorted(missing)}"
        )
    return {
        "happens_before_edges": "owned",
        "initialization_order_edges": "owned",
        "spar007_happens_before_edges": "absent",
        "spar007_initialization_order_edges": "absent",
        "semantic_owner": AUTHORITY_OWNER,
        "query_adapter_path": QUERY_ADAPTER_PATH,
        "authority": AUTHORITY,
    }


def initialization_cid_profile() -> dict[str, str]:
    return {
        "profile_id": INIT_CID_PROFILE,
        "codec": INIT_CID_CODEC,
        "rule": "content identity is not universal meaning",
    }


@dataclass(frozen=True, slots=True)
class InitializationGraphNode:
    """Content-addressed top-level initialization block."""

    node_id: str
    kind: InitializationNodeKind | str
    qualified_name: str
    module_path: str
    order_index: int
    start_line: int
    end_line: int
    effect_kinds: Sequence[str] = ()
    defined_names: Sequence[str] = ()
    used_names: Sequence[str] = ()
    imported_modules: Sequence[str] = ()
    eagerness: ImportEagerness | str = ImportEagerness.EAGER
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    confidence: InitializationConfidence | str = InitializationConfidence.EXACT
    support_status: SupportStatus | str = SupportStatus.SUPPORTED
    required: bool = True
    unresolved: bool = False

    interface: ClassVar[str] = INITIALIZATION_GRAPH_NODE_INTERFACE
    schema: ClassVar[str] = INITIALIZATION_GRAPH_NODE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "node_id",
            "kind",
            "qualified_name",
            "module_path",
            "order_index",
            "start_line",
            "end_line",
            "effect_kinds",
            "defined_names",
            "used_names",
            "imported_modules",
            "eagerness",
            "evidence_class",
            "confidence",
            "support_status",
            "required",
            "unresolved",
            "node_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _text(self.node_id, "node_id"))
        object.__setattr__(
            self, "kind", _enum(self.kind, InitializationNodeKind, "kind")
        )
        object.__setattr__(
            self, "qualified_name", _text(self.qualified_name, "qualified_name")
        )
        object.__setattr__(
            self, "module_path", _repo_relative_path(self.module_path, "module_path")
        )
        object.__setattr__(
            self, "order_index", _nonneg_int(self.order_index, "order_index")
        )
        start = _positive_int(self.start_line, "start_line")
        end = _positive_int(self.end_line, "end_line")
        if end < start:
            raise InitializationContractError("end_line must be >= start_line")
        object.__setattr__(self, "start_line", start)
        object.__setattr__(self, "end_line", end)
        object.__setattr__(
            self,
            "effect_kinds",
            _unique_sorted_enums(
                self.effect_kinds, InitializationEffectKind, "effect_kind"
            ),
        )
        object.__setattr__(
            self, "defined_names", _unique_sorted(self.defined_names, "defined_name")
        )
        object.__setattr__(
            self, "used_names", _unique_sorted(self.used_names, "used_name")
        )
        object.__setattr__(
            self,
            "imported_modules",
            _unique_sorted(self.imported_modules, "imported_module"),
        )
        object.__setattr__(
            self, "eagerness", _enum(self.eagerness, ImportEagerness, "eagerness")
        )
        evidence = _enum(self.evidence_class, EvidenceClass, "evidence_class")
        confidence = _enum(self.confidence, InitializationConfidence, "confidence")
        _confidence_compatible(confidence, evidence, "InitializationGraphNode")
        unresolved = _bool(self.unresolved, "unresolved")
        if confidence == InitializationConfidence.EXACT.value and unresolved:
            raise InitializationContractError(
                "exact resolved blocks cannot be unresolved"
            )
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(
            self,
            "support_status",
            _enum(self.support_status, SupportStatus, "support_status"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))
        object.__setattr__(self, "unresolved", unresolved)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": INITIALIZATION_GRAPH_NODE_SCHEMA,
            "interface": INITIALIZATION_GRAPH_NODE_INTERFACE,
            "node_id": self.node_id,
            "kind": self.kind,
            "qualified_name": self.qualified_name,
            "module_path": self.module_path,
            "order_index": self.order_index,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "effect_kinds": list(self.effect_kinds),
            "defined_names": list(self.defined_names),
            "used_names": list(self.used_names),
            "imported_modules": list(self.imported_modules),
            "eagerness": self.eagerness,
            "evidence_class": self.evidence_class,
            "confidence": self.confidence,
            "support_status": self.support_status,
            "required": self.required,
            "unresolved": self.unresolved,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def node_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["node_cid"] = self.node_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InitializationGraphNode":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("node_cid")
        if payload.pop("schema") != INITIALIZATION_GRAPH_NODE_SCHEMA:
            raise InitializationContractError(
                "unsupported InitializationGraphNode schema"
            )
        if payload.pop("interface") != INITIALIZATION_GRAPH_NODE_INTERFACE:
            raise InitializationContractError(
                "unsupported InitializationGraphNode interface"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.node_cid, "InitializationGraphNode node_cid")
        return result


@dataclass(frozen=True, slots=True)
class InitializationOrderEdge:
    """Happens-before or initialization-order edge owned by SPAR-010."""

    source_id: str
    target_id: str
    kind: InitializationRelationKind | str
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    confidence: InitializationConfidence | str = InitializationConfidence.EXACT

    interface: ClassVar[str] = INITIALIZATION_ORDER_EDGE_INTERFACE
    schema: ClassVar[str] = INITIALIZATION_ORDER_EDGE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "source_id",
            "target_id",
            "kind",
            "evidence_class",
            "confidence",
            "edge_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        object.__setattr__(self, "target_id", _text(self.target_id, "target_id"))
        if self.source_id == self.target_id:
            raise InitializationContractError("order edge cannot be reflexive")
        kind = _enum(self.kind, InitializationRelationKind, "kind")
        evidence = _enum(self.evidence_class, EvidenceClass, "evidence_class")
        confidence = _enum(self.confidence, InitializationConfidence, "confidence")
        _confidence_compatible(confidence, evidence, "InitializationOrderEdge")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "confidence", confidence)

    @property
    def edge_key(self) -> tuple[str, str, str]:
        return (self.source_id, self.kind, self.target_id)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": INITIALIZATION_ORDER_EDGE_SCHEMA,
            "interface": INITIALIZATION_ORDER_EDGE_INTERFACE,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "evidence_class": self.evidence_class,
            "confidence": self.confidence,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "InitializationOrderEdge":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("edge_cid")
        if payload.pop("schema") != INITIALIZATION_ORDER_EDGE_SCHEMA:
            raise InitializationContractError(
                "unsupported InitializationOrderEdge schema"
            )
        if payload.pop("interface") != INITIALIZATION_ORDER_EDGE_INTERFACE:
            raise InitializationContractError(
                "unsupported InitializationOrderEdge interface"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.edge_cid, "InitializationOrderEdge edge_cid")
        return result


@dataclass(frozen=True, slots=True)
class InitializationCandidate:
    """Explicit initialization rewrite/adapter candidate. Nomination-only."""

    candidate_id: str
    kind: InitializationCandidateKind | str
    subject_ids: Sequence[str]
    reason: str
    support_status: SupportStatus | str = SupportStatus.SUPPORTED
    required: bool = False

    interface: ClassVar[str] = INITIALIZATION_CANDIDATE_INTERFACE
    schema: ClassVar[str] = INITIALIZATION_CANDIDATE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "candidate_id",
            "kind",
            "subject_ids",
            "reason",
            "support_status",
            "required",
            "candidate_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _text(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "kind", _enum(self.kind, InitializationCandidateKind, "kind")
        )
        subjects = tuple(_text(item, "subject_id") for item in self.subject_ids)
        if len(subjects) != len(set(subjects)):
            raise InitializationContractError("subject_ids must not contain duplicates")
        object.__setattr__(self, "subject_ids", subjects)
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(
            self,
            "support_status",
            _enum(self.support_status, SupportStatus, "support_status"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": INITIALIZATION_CANDIDATE_SCHEMA,
            "interface": INITIALIZATION_CANDIDATE_INTERFACE,
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "subject_ids": list(self.subject_ids),
            "reason": self.reason,
            "support_status": self.support_status,
            "required": self.required,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def candidate_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["candidate_cid"] = self.candidate_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InitializationCandidate":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("candidate_cid")
        if payload.pop("schema") != INITIALIZATION_CANDIDATE_SCHEMA:
            raise InitializationContractError(
                "unsupported InitializationCandidate schema"
            )
        if payload.pop("interface") != INITIALIZATION_CANDIDATE_INTERFACE:
            raise InitializationContractError(
                "unsupported InitializationCandidate interface"
            )
        result = cls(**payload)
        _verify_cid(
            claimed, result.candidate_cid, "InitializationCandidate candidate_cid"
        )
        return result


@dataclass(frozen=True, slots=True)
class InitializationStateTransition:
    """Deterministic state-machine transition. No live runtime pointer."""

    source_state: InitializationMachineState | str
    event: InitializationMachineEvent | str
    target_state: InitializationMachineState | str

    interface: ClassVar[str] = INITIALIZATION_STATE_TRANSITION_INTERFACE
    schema: ClassVar[str] = INITIALIZATION_STATE_TRANSITION_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "source_state",
            "event",
            "target_state",
            "transition_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_state",
            _enum(self.source_state, InitializationMachineState, "source_state"),
        )
        object.__setattr__(
            self, "event", _enum(self.event, InitializationMachineEvent, "event")
        )
        object.__setattr__(
            self,
            "target_state",
            _enum(self.target_state, InitializationMachineState, "target_state"),
        )

    @property
    def transition_key(self) -> tuple[str, str, str]:
        return (self.source_state, self.event, self.target_state)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": INITIALIZATION_STATE_TRANSITION_SCHEMA,
            "interface": INITIALIZATION_STATE_TRANSITION_INTERFACE,
            "source_state": self.source_state,
            "event": self.event,
            "target_state": self.target_state,
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def transition_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["transition_cid"] = self.transition_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InitializationStateTransition":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("transition_cid")
        if payload.pop("schema") != INITIALIZATION_STATE_TRANSITION_SCHEMA:
            raise InitializationContractError(
                "unsupported InitializationStateTransition schema"
            )
        if payload.pop("interface") != INITIALIZATION_STATE_TRANSITION_INTERFACE:
            raise InitializationContractError(
                "unsupported InitializationStateTransition interface"
            )
        result = cls(**payload)
        _verify_cid(
            claimed,
            result.transition_cid,
            "InitializationStateTransition transition_cid",
        )
        return result


def _standard_transitions() -> tuple[InitializationStateTransition, ...]:
    rows: list[InitializationStateTransition] = [
        InitializationStateTransition(
            source_state=InitializationMachineState.UNINITIALIZED,
            event=InitializationMachineEvent.START,
            target_state=InitializationMachineState.IMPORTING,
        ),
        InitializationStateTransition(
            source_state=InitializationMachineState.IMPORTING,
            event=InitializationMachineEvent.EXECUTE,
            target_state=InitializationMachineState.EXECUTING,
        ),
        InitializationStateTransition(
            source_state=InitializationMachineState.IMPORTING,
            event=InitializationMachineEvent.COMPLETE,
            target_state=InitializationMachineState.INITIALIZED,
        ),
        InitializationStateTransition(
            source_state=InitializationMachineState.EXECUTING,
            event=InitializationMachineEvent.ADVANCE,
            target_state=InitializationMachineState.IMPORTING,
        ),
        InitializationStateTransition(
            source_state=InitializationMachineState.EXECUTING,
            event=InitializationMachineEvent.COMPLETE,
            target_state=InitializationMachineState.INITIALIZED,
        ),
    ]
    failure_map = (
        (
            InitializationMachineEvent.CYCLE,
            InitializationMachineState.CYCLIC,
        ),
        (
            InitializationMachineEvent.UNSUPPORTED,
            InitializationMachineState.UNSUPPORTED,
        ),
        (
            InitializationMachineEvent.INCOMPLETE,
            InitializationMachineState.INCOMPLETE,
        ),
    )
    for state in NONTERMINAL_STATES:
        for event, target in failure_map:
            rows.append(
                InitializationStateTransition(
                    source_state=state,
                    event=event,
                    target_state=target,
                )
            )
    return tuple(sorted(rows, key=lambda item: item.transition_key))


STANDARD_TRANSITIONS: Final[tuple[InitializationStateTransition, ...]] = (
    _standard_transitions()
)


def _coerce_transition(
    value: InitializationStateTransition | Mapping[str, Any],
) -> InitializationStateTransition:
    if isinstance(value, InitializationStateTransition):
        return value
    if isinstance(value, Mapping):
        if "transition_cid" in value:
            return InitializationStateTransition.from_dict(value)
        return InitializationStateTransition(**dict(value))
    raise InitializationContractError(
        "transition must be an InitializationStateTransition"
    )


@dataclass(frozen=True, slots=True)
class InitializationStateMachine:
    """Closed initialization state machine. Live runtime state is excluded."""

    block_ids: Sequence[str]
    transitions: Sequence[
        InitializationStateTransition | Mapping[str, Any]
    ] = STANDARD_TRANSITIONS
    initial_state: InitializationMachineState | str = (
        InitializationMachineState.UNINITIALIZED
    )

    interface: ClassVar[str] = INITIALIZATION_STATE_MACHINE_INTERFACE
    schema: ClassVar[str] = INITIALIZATION_STATE_MACHINE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "block_ids",
            "states",
            "transitions",
            "initial_state",
            "accepting_states",
            "failure_states",
            "machine_cid",
        }
    )

    def __post_init__(self) -> None:
        blocks = tuple(_text(item, "block_id") for item in self.block_ids)
        if len(blocks) != len(set(blocks)):
            raise InitializationContractError("block_ids must not contain duplicates")
        object.__setattr__(self, "block_ids", blocks)
        transitions = tuple(_coerce_transition(item) for item in self.transitions)
        if len(transitions) > MAX_TRANSITIONS:
            raise InitializationContractError("transitions exceed maximum length")
        transitions = tuple(sorted(transitions, key=lambda item: item.transition_key))
        keys = tuple(item.transition_key for item in transitions)
        if len(keys) != len(set(keys)):
            raise InitializationContractError("transitions must be unique")
        object.__setattr__(self, "transitions", transitions)
        initial = _enum(
            self.initial_state, InitializationMachineState, "initial_state"
        )
        if initial != InitializationMachineState.UNINITIALIZED.value:
            raise InitializationContractError(
                "initial_state must be uninitialized"
            )
        object.__setattr__(self, "initial_state", initial)
        declared_states = {item.source_state for item in transitions} | {
            item.target_state for item in transitions
        } | {initial}
        if declared_states != set(MACHINE_STATES):
            raise InitializationContractError(
                "state machine must close over the declared initialization states"
            )

    @property
    def states(self) -> tuple[str, ...]:
        return MACHINE_STATES

    @property
    def accepting_states(self) -> tuple[str, ...]:
        return tuple(sorted(ACCEPTING_STATES))

    @property
    def failure_states(self) -> tuple[str, ...]:
        return tuple(sorted(FAILURE_STATES))

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": INITIALIZATION_STATE_MACHINE_SCHEMA,
            "interface": INITIALIZATION_STATE_MACHINE_INTERFACE,
            "block_ids": list(self.block_ids),
            "states": list(self.states),
            "transitions": [item.to_dict() for item in self.transitions],
            "initial_state": self.initial_state,
            "accepting_states": list(self.accepting_states),
            "failure_states": list(self.failure_states),
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def machine_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["machine_cid"] = self.machine_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InitializationStateMachine":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("machine_cid")
        if payload.pop("schema") != INITIALIZATION_STATE_MACHINE_SCHEMA:
            raise InitializationContractError(
                "unsupported InitializationStateMachine schema"
            )
        if payload.pop("interface") != INITIALIZATION_STATE_MACHINE_INTERFACE:
            raise InitializationContractError(
                "unsupported InitializationStateMachine interface"
            )
        states = payload.pop("states")
        accepting = payload.pop("accepting_states")
        failure = payload.pop("failure_states")
        result = cls(
            block_ids=payload["block_ids"],
            transitions=payload["transitions"],
            initial_state=payload["initial_state"],
        )
        if list(states) != list(result.states):
            raise InitializationContractError("states do not verify")
        if list(accepting) != list(result.accepting_states):
            raise InitializationContractError("accepting_states do not verify")
        if list(failure) != list(result.failure_states):
            raise InitializationContractError("failure_states do not verify")
        _verify_cid(claimed, result.machine_cid, "InitializationStateMachine machine_cid")
        return result

    def step(self, state: str, event: str) -> str:
        source = _enum(state, InitializationMachineState, "state")
        action = _enum(event, InitializationMachineEvent, "event")
        matches = [
            item
            for item in self.transitions
            if item.source_state == source and item.event == action
        ]
        if len(matches) != 1:
            raise InitializationContractError(
                f"state machine has no unique transition for {source!r}/{action!r}"
            )
        return matches[0].target_state


@dataclass(frozen=True, slots=True)
class InitializationTerminal:
    """Typed initialization evaluation. Success never authorizes completion."""

    kind: InitializationTerminalKind | str
    reason: str
    required: bool = True
    block_ids: Sequence[str] = ()
    cycle_ids: Sequence[str] = ()

    interface: ClassVar[str] = INITIALIZATION_TERMINAL_INTERFACE
    schema: ClassVar[str] = INITIALIZATION_TERMINAL_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "kind",
            "reason",
            "required",
            "success",
            "authorizes_completion",
            "block_ids",
            "cycle_ids",
            "terminal_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum(self.kind, InitializationTerminalKind, "kind")
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(self, "required", _bool(self.required, "required"))
        object.__setattr__(self, "block_ids", _unique_sorted(self.block_ids, "block_id"))
        object.__setattr__(self, "cycle_ids", _unique_sorted(self.cycle_ids, "cycle_id"))

    @property
    def success(self) -> bool:
        return self.kind == InitializationTerminalKind.ADMITTED.value

    @property
    def authorizes_completion(self) -> bool:
        return False

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": INITIALIZATION_TERMINAL_SCHEMA,
            "interface": INITIALIZATION_TERMINAL_INTERFACE,
            "kind": self.kind,
            "reason": self.reason,
            "required": self.required,
            "success": self.success,
            "authorizes_completion": False,
            "block_ids": list(self.block_ids),
            "cycle_ids": list(self.cycle_ids),
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def terminal_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["terminal_cid"] = self.terminal_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InitializationTerminal":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("terminal_cid")
        if payload.pop("schema") != INITIALIZATION_TERMINAL_SCHEMA:
            raise InitializationContractError(
                "unsupported InitializationTerminal schema"
            )
        if payload.pop("interface") != INITIALIZATION_TERMINAL_INTERFACE:
            raise InitializationContractError(
                "unsupported InitializationTerminal interface"
            )
        success = payload.pop("success")
        authorizes = payload.pop("authorizes_completion")
        result = cls(
            kind=payload["kind"],
            reason=payload["reason"],
            required=payload["required"],
            block_ids=payload["block_ids"],
            cycle_ids=payload["cycle_ids"],
        )
        if success is not result.success:
            raise InitializationContractError("success does not verify")
        if authorizes is not False:
            raise InitializationContractError(
                "initialization terminal cannot authorize completion"
            )
        _verify_cid(claimed, result.terminal_cid, "InitializationTerminal terminal_cid")
        return result


def _coerce_node(
    value: InitializationGraphNode | Mapping[str, Any],
) -> InitializationGraphNode:
    if isinstance(value, InitializationGraphNode):
        return value
    if isinstance(value, Mapping):
        if "node_cid" in value:
            return InitializationGraphNode.from_dict(value)
        return InitializationGraphNode(**dict(value))
    raise InitializationContractError("node must be an InitializationGraphNode")


def _coerce_edge(
    value: InitializationOrderEdge | Mapping[str, Any],
) -> InitializationOrderEdge:
    if isinstance(value, InitializationOrderEdge):
        return value
    if isinstance(value, Mapping):
        if "edge_cid" in value:
            return InitializationOrderEdge.from_dict(value)
        return InitializationOrderEdge(**dict(value))
    raise InitializationContractError("edge must be an InitializationOrderEdge")


def _coerce_candidate(
    value: InitializationCandidate | Mapping[str, Any],
) -> InitializationCandidate:
    if isinstance(value, InitializationCandidate):
        return value
    if isinstance(value, Mapping):
        if "candidate_cid" in value:
            return InitializationCandidate.from_dict(value)
        return InitializationCandidate(**dict(value))
    raise InitializationContractError(
        "candidate must be an InitializationCandidate"
    )


def _coerce_machine(
    value: InitializationStateMachine | Mapping[str, Any] | None,
    block_ids: Sequence[str],
) -> InitializationStateMachine:
    if value is None:
        return InitializationStateMachine(block_ids=block_ids)
    if isinstance(value, InitializationStateMachine):
        if tuple(value.block_ids) != tuple(block_ids):
            raise InitializationContractError(
                "state machine block_ids must match graph nodes"
            )
        return value
    if isinstance(value, Mapping):
        if "machine_cid" in value:
            machine = InitializationStateMachine.from_dict(value)
        else:
            machine = InitializationStateMachine(**dict(value))
        if tuple(machine.block_ids) != tuple(block_ids):
            raise InitializationContractError(
                "state machine block_ids must match graph nodes"
            )
        return machine
    raise InitializationContractError(
        "state_machine must be an InitializationStateMachine"
    )


def _canonical_cycle(nodes: Sequence[str]) -> tuple[str, ...]:
    if not nodes:
        return ()
    items = list(nodes)
    if len(items) > MAX_CYCLE_LENGTH:
        raise InitializationContractError("cycle exceeds maximum length")
    start = items.index(min(items))
    return tuple(items[start:] + items[:start])


def detect_order_cycles(
    node_ids: Sequence[str],
    edges: Sequence[InitializationOrderEdge],
    *,
    self_import_ids: Sequence[str] = (),
) -> tuple[tuple[str, ...], ...]:
    """Return canonical directed cycles over SPAR-010 order relations."""

    present = set(node_ids)
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        if edge.source_id in present and edge.target_id in present:
            adjacency[edge.source_id].append(edge.target_id)
    cycles: list[tuple[str, ...]] = []
    stack: list[str] = []
    on_stack: set[str] = set()
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    counter = 0

    def visit(node: str) -> None:
        nonlocal counter
        index[node] = counter
        lowlink[node] = counter
        counter += 1
        stack.append(node)
        on_stack.add(node)
        for nxt in adjacency[node]:
            if nxt not in index:
                visit(nxt)
                lowlink[node] = min(lowlink[node], lowlink[nxt])
            elif nxt in on_stack:
                lowlink[node] = min(lowlink[node], index[nxt])
        if lowlink[node] == index[node]:
            component: list[str] = []
            while True:
                item = stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node:
                    break
            if len(component) > 1:
                cycles.append(_canonical_cycle(component))
            elif node in adjacency[node]:
                cycles.append((node,))

    for node_id in node_ids:
        if node_id not in index:
            visit(node_id)
    for node_id in self_import_ids:
        if node_id in present:
            cycles.append((node_id,))
    unique = tuple(sorted(set(cycles), key=lambda item: (len(item), item)))
    return unique


def linearize_initialization_order(
    node_ids: Sequence[str],
    edges: Sequence[InitializationOrderEdge],
) -> tuple[str, ...]:
    """Kahn linearization. Empty when a cycle is present."""

    if detect_order_cycles(node_ids, edges):
        return ()
    incoming: dict[str, int] = {node_id: 0 for node_id in node_ids}
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        adjacency[edge.source_id].append(edge.target_id)
        incoming[edge.target_id] += 1
    ready = sorted(node_id for node_id, count in incoming.items() if count == 0)
    ordered: list[str] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for nxt in sorted(adjacency[node]):
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                ready.append(nxt)
                ready.sort()
    if len(ordered) != len(node_ids):
        return ()
    return tuple(ordered)


@dataclass(frozen=True, slots=True)
class InitializationOrderGraph:
    """Closed SPAR-010 initialization-order and import-time effect graph."""

    tree_id: str
    source_cid: str
    module_path: str
    module_name: str
    nodes: Sequence[InitializationGraphNode | Mapping[str, Any]] = ()
    edges: Sequence[InitializationOrderEdge | Mapping[str, Any]] = ()
    candidates: Sequence[InitializationCandidate | Mapping[str, Any]] = ()
    state_machine: InitializationStateMachine | Mapping[str, Any] | None = None
    observation_profile_cid: str | None = None
    analyzer_id: str = ANALYZER_ID

    interface: ClassVar[str] = INITIALIZATION_ORDER_GRAPH_INTERFACE
    schema: ClassVar[str] = INITIALIZATION_ORDER_GRAPH_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "tree_id",
            "source_cid",
            "module_path",
            "module_name",
            "analyzer_id",
            "nodes",
            "edges",
            "candidates",
            "state_machine",
            "observation_profile_cid",
            "cycles",
            "linearization",
            "graph_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "tree_id", _tree_id(self.tree_id))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self, "module_path", _repo_relative_path(self.module_path, "module_path")
        )
        object.__setattr__(
            self, "module_name", _text(self.module_name, "module_name")
        )
        object.__setattr__(
            self, "analyzer_id", _text(self.analyzer_id, "analyzer_id")
        )
        if self.analyzer_id != ANALYZER_ID:
            raise InitializationContractError(
                "analyzer_id must remain spar-010-initialization"
            )
        nodes = tuple(_coerce_node(item) for item in self.nodes)
        if len(nodes) > MAX_NODES:
            raise InitializationContractError("nodes exceed maximum length")
        nodes = tuple(sorted(nodes, key=lambda item: (item.order_index, item.node_id)))
        node_ids = tuple(item.node_id for item in nodes)
        if len(node_ids) != len(set(node_ids)):
            raise InitializationContractError("nodes must not contain duplicate node_id")
        indices = [item.order_index for item in nodes]
        if indices != sorted(indices):
            raise InitializationContractError("order_index must be nondecreasing")
        if len(indices) != len(set(indices)):
            raise InitializationContractError("order_index must be unique")
        object.__setattr__(self, "nodes", nodes)

        edges = tuple(_coerce_edge(item) for item in self.edges)
        if len(edges) > MAX_EDGES:
            raise InitializationContractError("edges exceed maximum length")
        edges = tuple(sorted(edges, key=lambda item: item.edge_key))
        keys = tuple(item.edge_key for item in edges)
        if len(keys) != len(set(keys)):
            raise InitializationContractError(
                "edges must not contain duplicate source/kind/target triples"
            )
        present = set(node_ids)
        for edge in edges:
            if edge.source_id not in present or edge.target_id not in present:
                raise InitializationContractError(
                    "edge references a node that is not present in the graph"
                )
        object.__setattr__(self, "edges", edges)

        candidates = tuple(_coerce_candidate(item) for item in self.candidates)
        if len(candidates) > MAX_CANDIDATES:
            raise InitializationContractError("candidates exceed maximum length")
        candidates = tuple(sorted(candidates, key=lambda item: item.candidate_id))
        candidate_ids = tuple(item.candidate_id for item in candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise InitializationContractError("candidates must have unique candidate_id")
        for candidate in candidates:
            unknown = [item for item in candidate.subject_ids if item not in present]
            if unknown and present:
                raise InitializationContractError(
                    "candidate subject_ids must name graph nodes"
                )
        object.__setattr__(self, "candidates", candidates)

        machine = _coerce_machine(self.state_machine, node_ids)
        object.__setattr__(self, "state_machine", machine)
        object.__setattr__(
            self,
            "observation_profile_cid",
            _optional_cid(
                self.observation_profile_cid, "observation_profile_cid"
            ),
        )

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(item.node_id for item in self.nodes)

    @property
    def self_import_ids(self) -> tuple[str, ...]:
        return tuple(
            node.node_id
            for node in self.nodes
            if self.module_name in node.imported_modules
            or any(
                item == self.module_name or item.startswith(self.module_name + ".")
                for item in node.imported_modules
            )
        )

    @property
    def cycles(self) -> tuple[list[str], ...]:
        return tuple(
            list(cycle)
            for cycle in detect_order_cycles(
                self.node_ids,
                self.edges,
                self_import_ids=self.self_import_ids,
            )
        )

    @property
    def linearization(self) -> tuple[str, ...]:
        if self.self_import_ids:
            return ()
        return linearize_initialization_order(self.node_ids, self.edges)

    @property
    def cyclic(self) -> bool:
        return bool(self.cycles)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": INITIALIZATION_ORDER_GRAPH_SCHEMA,
            "interface": INITIALIZATION_ORDER_GRAPH_INTERFACE,
            "tree_id": self.tree_id,
            "source_cid": self.source_cid,
            "module_path": self.module_path,
            "module_name": self.module_name,
            "analyzer_id": self.analyzer_id,
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "candidates": [item.to_dict() for item in self.candidates],
            "state_machine": self.state_machine.to_dict(),
            "observation_profile_cid": self.observation_profile_cid,
            "cycles": [list(cycle) for cycle in self.cycles],
            "linearization": list(self.linearization),
        }
        _require_dag_json(payload, self.__class__.__name__)
        return payload

    @property
    def graph_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["graph_cid"] = self.graph_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InitializationOrderGraph":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("graph_cid")
        if payload.pop("schema") != INITIALIZATION_ORDER_GRAPH_SCHEMA:
            raise InitializationContractError(
                "unsupported InitializationOrderGraph schema"
            )
        if payload.pop("interface") != INITIALIZATION_ORDER_GRAPH_INTERFACE:
            raise InitializationContractError(
                "unsupported InitializationOrderGraph interface"
            )
        cycles = payload.pop("cycles")
        linearization = payload.pop("linearization")
        result = cls(
            tree_id=payload["tree_id"],
            source_cid=payload["source_cid"],
            module_path=payload["module_path"],
            module_name=payload["module_name"],
            analyzer_id=payload["analyzer_id"],
            nodes=payload["nodes"],
            edges=payload["edges"],
            candidates=payload["candidates"],
            state_machine=payload["state_machine"],
            observation_profile_cid=payload["observation_profile_cid"],
        )
        if [list(cycle) for cycle in result.cycles] != list(cycles):
            raise InitializationContractError("cycles do not verify")
        if list(result.linearization) != list(linearization):
            raise InitializationContractError("linearization does not verify")
        _verify_cid(claimed, result.graph_cid, "InitializationOrderGraph graph_cid")
        return result

    def edges_for_kind(
        self, kind: InitializationRelationKind | str
    ) -> tuple[InitializationOrderEdge, ...]:
        resolved = _enum(kind, InitializationRelationKind, "kind")
        return tuple(edge for edge in self.edges if edge.kind == resolved)

    def evaluate(self) -> InitializationTerminal:
        return evaluate_initialization_order(self)


def evaluate_initialization_order(
    graph: InitializationOrderGraph,
) -> InitializationTerminal:
    """Evaluate one initialization-order graph. Typed terminals never complete."""

    block_ids = graph.node_ids
    if graph.cyclic:
        cycle_ids = tuple(
            "|".join(cycle) for cycle in detect_order_cycles(block_ids, graph.edges)
        )
        return InitializationTerminal(
            kind=InitializationTerminalKind.CYCLIC,
            reason="initialization-order graph contains an explicit cycle",
            required=True,
            block_ids=block_ids,
            cycle_ids=cycle_ids,
        )
    required_unsupported = [
        node.node_id
        for node in graph.nodes
        if node.required and node.support_status == SupportStatus.UNSUPPORTED.value
    ]
    if required_unsupported:
        return InitializationTerminal(
            kind=InitializationTerminalKind.UNSUPPORTED_REQUIRED,
            reason="required initialization effect is unsupported",
            required=True,
            block_ids=tuple(required_unsupported),
        )
    required_unknown = [
        node.node_id
        for node in graph.nodes
        if node.required and node.support_status == SupportStatus.UNKNOWN.value
    ]
    if required_unknown:
        return InitializationTerminal(
            kind=InitializationTerminalKind.UNKNOWN_REQUIRED,
            reason="required initialization effect is unknown",
            required=True,
            block_ids=tuple(required_unknown),
        )
    conflict = [
        node.node_id
        for node in graph.nodes
        if node.unresolved and node.confidence == InitializationConfidence.EXACT.value
    ]
    if conflict:
        return InitializationTerminal(
            kind=InitializationTerminalKind.CONFLICT,
            reason="exact initialization block cannot remain unresolved",
            required=True,
            block_ids=tuple(conflict),
        )
    if graph.observation_profile_cid is None:
        return InitializationTerminal(
            kind=InitializationTerminalKind.INCOMPLETE_CONTRACT,
            reason="initialization graph must bind a hermetic observation profile",
            required=True,
            block_ids=block_ids,
        )
    return InitializationTerminal(
        kind=InitializationTerminalKind.ADMITTED,
        reason="initialization-order and import-time effects are explicit",
        required=any(node.required for node in graph.nodes) if graph.nodes else False,
        block_ids=block_ids,
    )


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _leaf_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _target_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(node, ast.Name):
        names.add(node.id)
    elif isinstance(node, ast.Tuple):
        for elt in node.elts:
            names.update(_target_names(elt))
    elif isinstance(node, ast.List):
        for elt in node.elts:
            names.update(_target_names(elt))
    elif isinstance(node, ast.Starred):
        names.update(_target_names(node.value))
    return names


class _ImportTimeVisitor(ast.NodeVisitor):
    """Collect import-time names and effects. Function bodies are skipped."""

    def __init__(self) -> None:
        self.defined: set[str] = set()
        self.used: set[str] = set()
        self.effects: set[str] = set()
        self.unresolved = False
        self.unsupported = False
        self.conservative = False
        self.imported_modules: list[str] = []
        self._skip_function_body = False

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.used.add(node.id)
        elif isinstance(node.ctx, ast.Store):
            self.defined.add(node.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        self.defined.add(node.name)
        for decorator in node.decorator_list:
            self.effects.add(InitializationEffectKind.DECORATOR.value)
            deco = _call_name(decorator) or _leaf_name(decorator)
            if any(token in deco for token in _CLI_DECORATORS):
                self.effects.add(InitializationEffectKind.CLI_REGISTRATION.value)
            self.visit(decorator)
        for default in list(node.args.defaults) + list(node.args.kw_defaults):
            if default is not None:
                self.visit(default)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.defined.add(node.name)
        for decorator in node.decorator_list:
            self.effects.add(InitializationEffectKind.DECORATOR.value)
            self.visit(decorator)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.effects.add(InitializationEffectKind.IMPORT.value)
        for alias in node.names:
            self.imported_modules.append(alias.name)
            self.defined.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.effects.add(InitializationEffectKind.IMPORT.value)
        module = node.module or ""
        if node.level:
            self.conservative = True
            self.unresolved = True
        self.imported_modules.append(module)
        for alias in node.names:
            self.defined.add(alias.asname or alias.name)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        leaf = _leaf_name(node.func)
        if leaf in _EVAL_NAMES:
            self.effects.add(InitializationEffectKind.UNKNOWN.value)
            self.unsupported = True
            self.unresolved = True
        if leaf in _DYNAMIC_IMPORT_NAMES or name.startswith("importlib."):
            self.effects.add(InitializationEffectKind.IMPORT.value)
            self.conservative = True
            self.unresolved = True
        if leaf in _REGISTRATION_ATTRS:
            self.effects.add(InitializationEffectKind.REGISTRATION.value)
        if leaf in _RESOURCE_NAMES:
            self.effects.add(InitializationEffectKind.RESOURCE.value)
        if leaf in _NETWORK_NAMES or name.startswith("urllib.") or name.startswith(
            "requests."
        ):
            self.effects.add(InitializationEffectKind.NETWORK.value)
        if leaf in _SIGNAL_NAMES or name.startswith("atexit.") or name.startswith(
            "signal."
        ):
            if "atexit" in name or leaf == "atexit":
                self.effects.add(InitializationEffectKind.ATEXIT.value)
            else:
                self.effects.add(InitializationEffectKind.SIGNAL.value)
        if leaf not in _EVAL_NAMES and not isinstance(node.func, ast.Name):
            if leaf in _REGISTRATION_ATTRS or leaf in {"command", "route"}:
                self.effects.add(InitializationEffectKind.REGISTRATION.value)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self.defined.update(_target_names(target))
            if isinstance(target, ast.Subscript):
                self.effects.add(InitializationEffectKind.STATE_MUTATION.value)
                self.effects.add(InitializationEffectKind.REGISTRATION.value)
        self.visit(node.value)
        for target in node.targets:
            if not isinstance(target, (ast.Name, ast.Tuple, ast.List, ast.Starred)):
                self.visit(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.defined.update(_target_names(node.target))
        if node.value is not None:
            self.visit(node.value)
        self.visit(node.annotation)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.effects.add(InitializationEffectKind.STATE_MUTATION.value)
        self.defined.update(_target_names(node.target))
        self.visit(node.value)


def _stmt_end_line(node: ast.AST) -> int:
    end = getattr(node, "end_lineno", None) or getattr(node, "lineno", 1) or 1
    return int(end)


def partition_top_level_blocks(
    source: str,
    *,
    module_path: str,
    module_name: str,
) -> tuple[InitializationGraphNode, ...]:
    """Partition module body statements into content-addressed blocks."""

    if type(source) is not str:
        raise InitializationContractError("source must be a string")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise InitializationContractError("source must be parseable Python") from exc
    nodes: list[InitializationGraphNode] = []
    for index, stmt in enumerate(tree.body):
        visitor = _ImportTimeVisitor()
        visitor.visit(stmt)
        start = int(getattr(stmt, "lineno", 1) or 1)
        end = _stmt_end_line(stmt)
        effects = set(visitor.effects)
        if not effects and isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            effects.add(InitializationEffectKind.STATE_MUTATION.value)
        if visitor.unsupported:
            support = SupportStatus.UNSUPPORTED.value
            evidence = EvidenceClass.CONSERVATIVE_MAY_FACT.value
            confidence = InitializationConfidence.CONSERVATIVE.value
        elif visitor.conservative or visitor.unresolved:
            support = SupportStatus.SUPPORTED.value
            evidence = EvidenceClass.CONSERVATIVE_MAY_FACT.value
            confidence = InitializationConfidence.CONSERVATIVE.value
        else:
            support = SupportStatus.SUPPORTED.value
            evidence = EvidenceClass.EXACT_STATIC_FACT.value
            confidence = InitializationConfidence.EXACT.value
        nodes.append(
            InitializationGraphNode(
                node_id=f"block:{module_name}:toplevel:{index}",
                kind=InitializationNodeKind.TOP_LEVEL_BLOCK,
                qualified_name=f"{module_name}:block:{index}",
                module_path=module_path,
                order_index=index,
                start_line=start,
                end_line=end,
                effect_kinds=tuple(effects),
                defined_names=tuple(visitor.defined),
                used_names=tuple(visitor.used - visitor.defined),
                imported_modules=tuple(visitor.imported_modules),
                eagerness=ImportEagerness.EAGER,
                evidence_class=evidence,
                confidence=confidence,
                support_status=support,
                required=True,
                unresolved=visitor.unresolved,
            )
        )
    return tuple(nodes)


def infer_initialization_edges(
    nodes: Sequence[InitializationGraphNode],
    *,
    module_name: str,
) -> tuple[InitializationOrderEdge, ...]:
    """Infer sequential happens-before plus name/import initialization-order."""

    edges: list[InitializationOrderEdge] = []
    by_def: dict[str, str] = {}
    for node in nodes:
        for name in node.defined_names:
            by_def.setdefault(name, node.node_id)
        imported = node.imported_modules
        self_import = module_name in imported or any(
            item == module_name or item.startswith(module_name + ".")
            for item in imported
        )
        if self_import and len(nodes) > 1:
            other = nodes[-1] if node.node_id != nodes[-1].node_id else nodes[0]
            if other.node_id != node.node_id:
                edges.append(
                    InitializationOrderEdge(
                        source_id=other.node_id,
                        target_id=node.node_id,
                        kind=InitializationRelationKind.INITIALIZATION_ORDER,
                        evidence_class=EvidenceClass.EXACT_STATIC_FACT,
                        confidence=InitializationConfidence.EXACT,
                    )
                )
                edges.append(
                    InitializationOrderEdge(
                        source_id=node.node_id,
                        target_id=other.node_id,
                        kind=InitializationRelationKind.INITIALIZATION_ORDER,
                        evidence_class=EvidenceClass.EXACT_STATIC_FACT,
                        confidence=InitializationConfidence.EXACT,
                    )
                )
    for index, node in enumerate(nodes):
        if index > 0:
            predecessor = nodes[index - 1]
            edges.append(
                InitializationOrderEdge(
                    source_id=predecessor.node_id,
                    target_id=node.node_id,
                    kind=InitializationRelationKind.HAPPENS_BEFORE,
                    evidence_class=EvidenceClass.EXACT_STATIC_FACT,
                    confidence=InitializationConfidence.EXACT,
                )
            )
            edges.append(
                InitializationOrderEdge(
                    source_id=predecessor.node_id,
                    target_id=node.node_id,
                    kind=InitializationRelationKind.INITIALIZATION_ORDER,
                    evidence_class=EvidenceClass.EXACT_STATIC_FACT,
                    confidence=InitializationConfidence.EXACT,
                )
            )
        for name in node.used_names:
            defined_id = by_def.get(name)
            if defined_id and defined_id != node.node_id:
                def_node = next(item for item in nodes if item.node_id == defined_id)
                if def_node.order_index > node.order_index:
                    edges.append(
                        InitializationOrderEdge(
                            source_id=defined_id,
                            target_id=node.node_id,
                            kind=InitializationRelationKind.INITIALIZATION_ORDER,
                            evidence_class=EvidenceClass.CONSERVATIVE_MAY_FACT,
                            confidence=InitializationConfidence.CONSERVATIVE,
                        )
                    )
    unique: dict[tuple[str, str, str], InitializationOrderEdge] = {}
    for edge in edges:
        unique[edge.edge_key] = edge
    return tuple(sorted(unique.values(), key=lambda item: item.edge_key))


def synthesize_initialization_candidates(
    nodes: Sequence[InitializationGraphNode],
    *,
    cyclic: bool,
) -> tuple[InitializationCandidate, ...]:
    """Synthesize explicit initialization candidates. Never hide effects."""

    subject_ids = tuple(item.node_id for item in nodes)
    candidates: list[InitializationCandidate] = []
    if not cyclic:
        candidates.append(
            InitializationCandidate(
                candidate_id="candidate:preserve_order",
                kind=InitializationCandidateKind.PRESERVE_ORDER,
                subject_ids=subject_ids,
                reason="sequential top-level order is acyclic and explicit",
                required=False,
            )
        )
    effect_nodes = [
        node.node_id
        for node in nodes
        if any(
            kind
            in {
                InitializationEffectKind.REGISTRATION.value,
                InitializationEffectKind.DECORATOR.value,
                InitializationEffectKind.RESOURCE.value,
                InitializationEffectKind.IO.value,
                InitializationEffectKind.NETWORK.value,
                InitializationEffectKind.SIGNAL.value,
                InitializationEffectKind.ATEXIT.value,
                InitializationEffectKind.CLI_REGISTRATION.value,
                InitializationEffectKind.PLUGIN_REGISTRATION.value,
                InitializationEffectKind.STATE_MUTATION.value,
            }
            for kind in node.effect_kinds
        )
    ]
    if effect_nodes:
        candidates.append(
            InitializationCandidate(
                candidate_id="candidate:explicit_initializer",
                kind=InitializationCandidateKind.EXPLICIT_INITIALIZER,
                subject_ids=tuple(effect_nodes),
                reason="import-time effects can be lifted into an explicit initializer",
                required=False,
            )
        )
    if cyclic:
        candidates.append(
            InitializationCandidate(
                candidate_id="candidate:lazy_import",
                kind=InitializationCandidateKind.LAZY_IMPORT,
                subject_ids=subject_ids,
                reason="initialization cycle requires a lazy or deferred import adapter",
                required=True,
            )
        )
    return tuple(candidates)


def build_initialization_order_graph(
    *,
    tree_id: str,
    source_cid: str,
    module_path: str,
    module_name: str,
    nodes: Sequence[InitializationGraphNode | Mapping[str, Any]] = (),
    edges: Sequence[InitializationOrderEdge | Mapping[str, Any]] = (),
    candidates: Sequence[InitializationCandidate | Mapping[str, Any]] = (),
    state_machine: InitializationStateMachine | Mapping[str, Any] | None = None,
    observation_profile_cid: str | None = None,
) -> InitializationOrderGraph:
    """Construct one closed InitializationOrderGraph@1 record."""

    return InitializationOrderGraph(
        tree_id=tree_id,
        source_cid=source_cid,
        module_path=module_path,
        module_name=module_name,
        nodes=nodes,
        edges=edges,
        candidates=candidates,
        state_machine=state_machine,
        observation_profile_cid=observation_profile_cid,
    )


def analyze_source(
    source: str,
    *,
    tree_id: str,
    module_path: str,
    module_name: str,
    source_cid: str | None = None,
    observation_profile_cid: str | None = None,
) -> InitializationOrderGraph:
    """Partition source, infer order/cycles/effects, and bind observation."""

    if type(source) is not str:
        raise InitializationContractError("source must be a string")
    resolved_source_cid = source_cid or cid_for_bytes(source.encode("utf-8"))
    nodes = partition_top_level_blocks(
        source, module_path=module_path, module_name=module_name
    )
    edges = infer_initialization_edges(nodes, module_name=module_name)
    self_import_ids = tuple(
        node.node_id
        for node in nodes
        if module_name in node.imported_modules
        or any(
            item == module_name or item.startswith(module_name + ".")
            for item in node.imported_modules
        )
    )
    cyclic = bool(
        detect_order_cycles(
            tuple(item.node_id for item in nodes),
            edges,
            self_import_ids=self_import_ids,
        )
    )
    candidates = synthesize_initialization_candidates(nodes, cyclic=cyclic)
    profile = observation_profile_cid or DEFAULT_HERMETIC_PROFILE.profile_cid
    if DEFAULT_HERMETIC_PROFILE.network != NETWORK_DENY:
        raise InitializationContractError("observation profile must deny network")
    machine = InitializationStateMachine(
        block_ids=tuple(item.node_id for item in nodes)
    )
    return InitializationOrderGraph(
        tree_id=tree_id,
        source_cid=resolved_source_cid,
        module_path=module_path,
        module_name=module_name,
        nodes=nodes,
        edges=edges,
        candidates=candidates,
        state_machine=machine,
        observation_profile_cid=profile,
    )


def encode_canonical_initialization_graph(
    graph: InitializationOrderGraph,
) -> dict[str, Any]:
    return graph.to_dict()


def decode_canonical_initialization_graph(
    payload: Mapping[str, Any],
) -> InitializationOrderGraph:
    return InitializationOrderGraph.from_dict(payload)


def provider_free_exports() -> tuple[str, ...]:
    """Return the sorted public export surface (no provider or model names)."""

    return tuple(sorted(__all__))


def assert_not_competing_capsule_family() -> None:
    defined = {
        name
        for name, value in globals().items()
        if isinstance(value, type) and name in _FORBIDDEN_CAPSULE_TYPE_NAMES
    }
    if defined:
        raise InitializationContractError(
            f"initialization graph must not define capsule-family types: {sorted(defined)}"
        )


assert_not_competing_capsule_family()
assert INITIALIZATION_ORDER_GRAPH_INTERFACE == "InitializationOrderGraph@1"
assert INITIALIZATION_STATE_MACHINE_INTERFACE == "InitializationStateMachine@1"
assert TASK_ID == "SPAR-010"
assert INIT_CAN_AUTHORIZE_COMPLETION is False
assert MODEL_OUTPUT_IS_PROPOSAL_ONLY is True
assert OWNED_SPAR007_FORBIDDEN_RELATIONS <= SPAR007_FORBIDDEN_EDGE_KINDS
validate_structured_value(
    {
        "schema": INITIALIZATION_ORDER_GRAPH_SCHEMA,
        "task_id": TASK_ID,
        "authority_owner": AUTHORITY_OWNER,
    }
)


__all__ = [
    "ACCEPTING_STATES",
    "ANALYZER_ID",
    "AUTHORITY",
    "AUTHORITY_OWNER",
    "DECLARED_NODE_KINDS",
    "DECLARED_RELATION_KINDS",
    "DUCKLAKE_IS_AUTHORITY",
    "FAILURE_STATES",
    "GOAL_ID",
    "IDENTITY_EXCLUDED_FIELDS",
    "INIT_CAN_AUTHORIZE_COMPLETION",
    "INIT_CAN_AUTHORIZE_TRANSITION",
    "INIT_CAN_CREATE_AUTHORITY",
    "INIT_CID_CODEC",
    "INIT_CID_PROFILE",
    "INIT_CONTRACT_VERSION",
    "INITIALIZATION_ORDER_GRAPH_INTERFACE",
    "INITIALIZATION_ORDER_GRAPH_SCHEMA",
    "INITIALIZATION_STATE_MACHINE_INTERFACE",
    "INITIALIZATION_STATE_MACHINE_SCHEMA",
    "MACHINE_STATES",
    "MARKDOWN_IS_NOT_COMPLETION",
    "MODEL_OUTPUT_IS_PROPOSAL_ONLY",
    "OWNED_SPAR007_FORBIDDEN_RELATIONS",
    "RUNTIME_OBSERVATION_IS_NOT_STATIC_FACT",
    "STANDARD_TRANSITIONS",
    "TASK_ID",
    "TEST_PASS_IS_NOT_COMPLETION",
    "VECTOR_SIMILARITY_IS_AUTHORITY",
    "WORKER_SELF_APPROVAL",
    "InitializationCandidate",
    "InitializationCandidateKind",
    "InitializationConfidence",
    "InitializationContractError",
    "InitializationGraphNode",
    "InitializationMachineEvent",
    "InitializationMachineState",
    "InitializationNodeKind",
    "InitializationOrderEdge",
    "InitializationOrderGraph",
    "InitializationRelationKind",
    "InitializationStateMachine",
    "InitializationStateTransition",
    "InitializationTerminal",
    "InitializationTerminalKind",
    "analyze_source",
    "build_initialization_order_graph",
    "decode_canonical_initialization_graph",
    "detect_order_cycles",
    "encode_canonical_initialization_graph",
    "evaluate_initialization_order",
    "infer_initialization_edges",
    "initialization_cid_profile",
    "linearize_initialization_order",
    "partition_top_level_blocks",
    "provider_free_exports",
    "relation_ownership_contract",
    "synthesize_initialization_candidates",
]
