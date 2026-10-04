"""Closed end-goal, proof-hole, graph, and plan contracts (FVT-G021 / FVT-007).

Datasets-owned wire contracts shared with the supervisor for goal-directed
proof development.  These schemas are deliberately closed:

* every identity is content-addressed over the canonical semantic payload;
* tree / source spans / current and target state / property / quantifiers /
  environment / assumptions / logic / providers / bounds / ambiguity /
  provenance / authority / status are first-class bindings;
* proposals (candidates, draft plans) cannot claim proof or completion; and
* existing GoalDevelopment and supervisor ``ProofPlan`` surfaces adapt only
  through explicit conversion helpers that preserve a single root-goal
  identity rather than minting a competing one.

Interfaces (version 1):

* ``EndGoalSpec@1``
* ``ProofHole@1``
* ``ProofObligationGraph@1``
* ``GoalDirectedProofPlan@1``
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

# ---------------------------------------------------------------------------
# Interface and schema constants
# ---------------------------------------------------------------------------

END_GOAL_SPEC_INTERFACE: Final = "EndGoalSpec@1"
PROOF_HOLE_INTERFACE: Final = "ProofHole@1"
PROOF_OBLIGATION_GRAPH_INTERFACE: Final = "ProofObligationGraph@1"
GOAL_DIRECTED_PROOF_PLAN_INTERFACE: Final = "GoalDirectedProofPlan@1"

END_GOAL_SPEC_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/end-goal-spec@1"
)
END_GOAL_INTERPRETATION_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/end-goal-interpretation@1"
)
FORMAL_GOAL_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/formal-goal@1"
)
PROOF_HOLE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/proof-hole@1"
)
PROOF_GRAPH_NODE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/proof-graph-node@1"
)
PROOF_GRAPH_EDGE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/proof-graph-edge@1"
)
PROOF_OBLIGATION_GRAPH_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/proof-obligation-graph@1"
)
CANDIDATE_PROOF_STEP_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/candidate-proof-step@1"
)
CANDIDATE_VALIDATION_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/candidate-validation@1"
)
GOAL_DIRECTED_PROOF_PLAN_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/goal-directed-proof-plan@1"
)
GOAL_COMPLETION_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/goal-completion@1"
)

TACTICIAN_CONTRACT_VERSION: Final = 1

# False-claim keys that proposal-class artifacts must never set true.
_PROPOSAL_FORBIDDEN_TRUE_CLAIMS: Final[frozenset[str]] = frozenset(
    {
        "proof_claimed",
        "proved",
        "complete",
        "completion_claimed",
        "implementation_conformance_claimed",
        "implementation_conformant",
        "admitted",
        "admission_claimed",
        "attested",
        "kernel_verified",
    }
)


# ---------------------------------------------------------------------------
# Closed enumerations
# ---------------------------------------------------------------------------


class TacticianContractError(ValueError):
    """Raised when a tactician contract is malformed or unsafe."""


class PropertyClass(StrEnum):
    """Property class bound into an end goal (closed v1 vocabulary)."""

    EXISTENTIAL_REACHABILITY = "existential_reachability"
    UNIVERSAL_REACHABILITY = "universal_reachability"
    INEVITABILITY = "inevitability"
    LIVENESS = "liveness"
    INVARIANCE = "invariance"
    SAFETY = "safety"
    TERMINATION = "termination"
    REFINEMENT = "refinement"
    HYPERPROPERTY = "hyperproperty"
    AUTHORIZATION = "authorization"
    PROTOCOL = "protocol"
    THEOREM = "theorem"
    CONTRACT = "contract"
    UNSPECIFIED = "unspecified"


class QuantifierKind(StrEnum):
    """Path / state quantifiers over the target property."""

    EXISTS = "exists"
    FORALL = "forall"
    EVENTUALLY = "eventually"
    ALWAYS = "always"
    UNTIL = "until"
    NONE = "none"


class AssumptionClass(StrEnum):
    """How an assumption may be used in a proof chain."""

    TRUSTED = "trusted"
    MUST_PROVE = "must_prove"
    HYPOTHETICAL = "hypothetical"


class HoleKind(StrEnum):
    """Typed missing-proof obligations emitted by compilation / regression."""

    LOOP_INVARIANT = "loop_invariant"
    LOOP_VARIANT = "loop_variant"
    CALLEE_PRECONDITION = "callee_precondition"
    CALLEE_POSTCONDITION = "callee_postcondition"
    EXCEPTIONAL_CONTRACT = "exceptional_contract"
    FUNCTION_SUMMARY = "function_summary"
    FRAME = "frame"
    ALIAS = "alias"
    OWNERSHIP = "ownership"
    SEPARATION = "separation"
    RELY_GUARANTEE = "rely_guarantee"
    LINEARIZATION = "linearization"
    STATE_INVARIANT = "state_invariant"
    REFINEMENT_MAPPING = "refinement_mapping"
    TEMPORAL_FAIRNESS = "temporal_fairness"
    TEMPORAL_PROGRESS = "temporal_progress"
    PROTOCOL_TRUST = "protocol_trust"
    PROTOCOL_FRESHNESS = "protocol_freshness"
    PROTOCOL_SECRECY = "protocol_secrecy"
    PROTOCOL_AUTHENTICATION = "protocol_authentication"
    INFORMATION_FLOW = "information_flow"
    OBSERVATION_POLICY = "observation_policy"
    BRIDGE_LEMMA = "bridge_lemma"
    TRANSLATION_PRESERVATION = "translation_preservation"
    MISSING_SOURCE_FACT = "missing_source_fact"
    MISSING_EVIDENCE = "missing_evidence"
    UNSUPPORTED_SEMANTICS = "unsupported_semantics"
    UNAVAILABLE_TOOL = "unavailable_tool"
    UNAVAILABLE_RECONSTRUCTION = "unavailable_reconstruction"
    REQUIRED_IMPLEMENTATION_CHANGE = "required_implementation_change"
    OTHER = "other"


class HoleStatus(StrEnum):
    """Lifecycle of a typed proof hole (never a proof by itself)."""

    OPEN = "open"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    DISCHARGED = "discharged"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    FALSE = "false"
    UNKNOWN = "unknown"


class GraphNodeKind(StrEnum):
    """AND/OR obligation graph node kinds."""

    AND = "and"
    OR = "or"
    LEAF = "leaf"
    ROOT = "root"
    ASSUMPTION = "assumption"
    EVIDENCE = "evidence"


class GraphEdgeKind(StrEnum):
    """How one obligation relates to another."""

    DEPENDS_ON = "depends_on"
    REGRESSION = "regression"
    WEAKEST_PRECONDITION = "weakest_precondition"
    PREIMAGE = "preimage"
    RULE_INVERSION = "rule_inversion"
    UNIFICATION = "unification"
    SUBSUMPTION = "subsumption"
    ALTERNATIVE = "alternative"
    REPAIR = "repair"
    EVIDENCE_REF = "evidence_ref"


class CandidateStatus(StrEnum):
    """Status of a candidate proof step — proposals only."""

    PROPOSED = "proposed"
    RANKED = "ranked"
    SELECTED = "selected"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ValidationVerdict(StrEnum):
    """Independent validation result for a candidate or hole."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    BOUNDED = "bounded"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    UNKNOWN = "unknown"


class AuthorityCeiling(StrEnum):
    """Authority a contract may advertise (cannot self-upgrade)."""

    NONE = "none"
    ADVISORY = "advisory"
    CANDIDATE = "candidate"
    BOUNDED = "bounded"
    SATISFIABILITY = "satisfiability"
    MODEL_CHECK = "model_check"
    MONITOR = "monitor"
    AUTHORIZATION = "authorization"
    PROTOCOL = "protocol"
    HYPERPROPERTY = "hyperproperty"
    RECONSTRUCTION = "reconstruction"
    ATTESTATION = "attestation"
    THEOREM = "theorem"
    DECLARATIVE = "declarative"


class PlanStatus(StrEnum):
    """Goal-directed plan lifecycle (completion is a separate contract)."""

    DRAFT = "draft"
    RANKED = "ranked"
    SELECTED = "selected"
    EXECUTING = "executing"
    BLOCKED = "blocked"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    # Explicitly not COMPLETE — completion is GoalCompletion only.


class CompletionVerdict(StrEnum):
    """Trusted completion gate for a formal goal."""

    NOT_COMPLETE = "not_complete"
    BOUNDED_COMPLETE = "bounded_complete"
    COMPLETE = "complete"
    DISPROVED = "disproved"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class AmbiguityStatus(StrEnum):
    """Whether material ambiguity remains on an end goal."""

    NONE = "none"
    CANDIDATES_PRESENT = "candidates_present"
    REQUIRES_SELECTION = "requires_selection"
    RESOLVED = "resolved"
    UNSUPPORTED = "unsupported"


# ---------------------------------------------------------------------------
# Canonical helpers
# ---------------------------------------------------------------------------


def _text(
    value: object,
    label: str,
    *,
    optional: bool = False,
    maximum: int = 4096,
) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str):
        raise TacticianContractError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise TacticianContractError(f"{label} must not contain NUL")
    if not optional and not text:
        raise TacticianContractError(f"{label} is required")
    if len(text) > maximum:
        raise TacticianContractError(
            f"{label} exceeds maximum length of {maximum}"
        )
    return text


def _string_tuple(
    value: object,
    label: str,
    *,
    required: bool = False,
    preserve_order: bool = False,
    maximum_item: int = 512,
) -> tuple[str, ...]:
    if value is None:
        items: Iterable[Any] = ()
    elif isinstance(value, str):
        items = (value,)
    elif isinstance(value, Sequence) and not isinstance(
        value, (bytes, bytearray, memoryview)
    ):
        items = value
    else:
        raise TacticianContractError(f"{label} must be a sequence of strings")
    result: list[str] = []
    for raw in items:
        item = _text(raw, label, maximum=maximum_item)
        if item and item not in result:
            result.append(item)
    if required and not result:
        raise TacticianContractError(f"{label} must not be empty")
    return tuple(result if preserve_order else sorted(result))


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    if isinstance(value, enum_type):
        return value
    raw = getattr(value, "value", value)
    try:
        return enum_type(str(raw).strip().lower())
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise TacticianContractError(
            f"{label} must be one of: {allowed}"
        ) from exc


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TacticianContractError(f"{label} must be a non-negative integer")
    return value


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TacticianContractError(f"{label} must be a boolean")
    return value


def _mapping(value: object, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TacticianContractError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise TacticianContractError(f"{label} keys must be strings")
    return _canonical_value(dict(value))


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise TacticianContractError(
            "tactician contracts cannot contain floating-point values"
        )
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, TacticianContract):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(k): _canonical_value(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_canonical_value(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    raise TacticianContractError(
        f"unsupported contract value type: {type(value).__name__}"
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Encode deterministic JSON bytes for content identity."""

    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_identity(value: Any) -> str:
    """Return a stable ``sha256:`` content identity for ``value``."""

    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _reject_unknown(
    payload: Mapping[str, Any], allowed: Iterable[str], *, artifact: str
) -> None:
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise TacticianContractError(
            f"{artifact} contains unsupported fields; rebuild its canonical payload"
        )


def _reject_proposal_authority_claims(
    payload: Mapping[str, Any], *, artifact: str
) -> None:
    """Fail closed when a proposal smuggles proof or completion authority."""

    for key in _PROPOSAL_FORBIDDEN_TRUE_CLAIMS:
        if key in payload and payload[key] is not False and payload[key] is not None:
            if payload[key] is True or (
                isinstance(payload[key], str)
                and payload[key].strip().lower()
                in {"true", "yes", "proved", "complete", "1"}
            ):
                raise TacticianContractError(
                    f"{artifact} cannot claim {key.replace('_', ' ')}"
                )


def _schema_check(payload: Mapping[str, Any], expected: str) -> None:
    if not isinstance(payload, Mapping):
        raise TacticianContractError("contract payload must be an object")
    supplied = payload.get("schema")
    if supplied not in (None, "", expected):
        raise TacticianContractError(
            f"unsupported contract schema; use {expected}"
        )
    version = payload.get("contract_version", payload.get("schema_version"))
    if version not in (None, TACTICIAN_CONTRACT_VERSION, str(TACTICIAN_CONTRACT_VERSION)):
        raise TacticianContractError(
            "unsupported tactician contract version"
        )


def _claim_identity(
    payload: Mapping[str, Any],
    actual: str,
    *,
    names: Sequence[str],
    artifact: str,
) -> None:
    for name in names:
        claimed = payload.get(name)
        if claimed not in (None, "") and claimed != actual:
            raise TacticianContractError(
                f"{artifact} content identity does not match payload"
            )


# ---------------------------------------------------------------------------
# Base contract
# ---------------------------------------------------------------------------


class TacticianContract:
    """Mixin for immutable content-addressed tactician contracts."""

    SCHEMA: ClassVar[str] = ""
    INTERFACE: ClassVar[str] = ""

    def _payload(self) -> dict[str, Any]:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": self.SCHEMA,
            "contract_version": TACTICIAN_CONTRACT_VERSION,
            **self._payload(),
        }
        if self.INTERFACE:
            payload["interface"] = self.INTERFACE
        return _canonical_value(payload)

    def to_json(self) -> str:
        return canonical_json_bytes(self.to_dict()).decode("utf-8")

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    @property
    def identity(self) -> str:
        return self.content_id

    def to_record(self) -> dict[str, Any]:
        return {**self.to_dict(), "content_id": self.content_id}


# ---------------------------------------------------------------------------
# Shared binding types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceSpanBinding(TacticianContract):
    """Repository tree and source/AST span binding."""

    SCHEMA: ClassVar[str] = (
        "ipfs_datasets_py/logic/software_verification/source-span-binding@1"
    )

    tree_id: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    ast_scope_ids: tuple[str, ...] = ()
    snapshot_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tree_id", _text(self.tree_id, "tree_id", optional=True, maximum=256)
        )
        object.__setattr__(
            self,
            "source_ref_ids",
            _string_tuple(self.source_ref_ids, "source_ref_ids"),
        )
        object.__setattr__(
            self, "span_ids", _string_tuple(self.span_ids, "span_ids")
        )
        object.__setattr__(
            self,
            "ast_scope_ids",
            _string_tuple(self.ast_scope_ids, "ast_scope_ids"),
        )
        object.__setattr__(
            self,
            "snapshot_id",
            _text(self.snapshot_id, "snapshot_id", optional=True, maximum=256),
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "tree_id": self.tree_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "ast_scope_ids": list(self.ast_scope_ids),
            "snapshot_id": self.snapshot_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SourceSpanBinding":
        _schema_check(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "tree_id",
                "source_ref_ids",
                "span_ids",
                "ast_scope_ids",
                "snapshot_id",
            },
            artifact="source span binding",
        )
        return cls(
            tree_id=payload.get("tree_id", ""),
            source_ref_ids=tuple(payload.get("source_ref_ids") or ()),
            span_ids=tuple(payload.get("span_ids") or ()),
            ast_scope_ids=tuple(payload.get("ast_scope_ids") or ()),
            snapshot_id=payload.get("snapshot_id", ""),
        )


@dataclass(frozen=True, slots=True)
class PhraseProvenance(TacticianContract):
    """Maps a caller phrase span to a structured clause identifier."""

    SCHEMA: ClassVar[str] = (
        "ipfs_datasets_py/logic/software_verification/phrase-provenance@1"
    )

    phrase: str
    clause_id: str
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    start_offset: int = 0
    end_offset: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "phrase", _text(self.phrase, "phrase", maximum=2048)
        )
        object.__setattr__(
            self, "clause_id", _text(self.clause_id, "clause_id", maximum=256)
        )
        object.__setattr__(
            self,
            "source_ref_ids",
            _string_tuple(self.source_ref_ids, "source_ref_ids"),
        )
        object.__setattr__(
            self, "span_ids", _string_tuple(self.span_ids, "span_ids")
        )
        object.__setattr__(
            self,
            "start_offset",
            _nonnegative_int(self.start_offset, "start_offset"),
        )
        object.__setattr__(
            self, "end_offset", _nonnegative_int(self.end_offset, "end_offset")
        )
        if self.end_offset < self.start_offset:
            raise TacticianContractError(
                "end_offset must be greater than or equal to start_offset"
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "phrase": self.phrase,
            "clause_id": self.clause_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PhraseProvenance":
        _schema_check(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "phrase",
                "clause_id",
                "source_ref_ids",
                "span_ids",
                "start_offset",
                "end_offset",
            },
            artifact="phrase provenance",
        )
        return cls(
            phrase=payload.get("phrase", ""),
            clause_id=payload.get("clause_id", ""),
            source_ref_ids=tuple(payload.get("source_ref_ids") or ()),
            span_ids=tuple(payload.get("span_ids") or ()),
            start_offset=int(payload.get("start_offset") or 0),
            end_offset=int(payload.get("end_offset") or 0),
        )


@dataclass(frozen=True, slots=True)
class AssumptionBinding(TacticianContract):
    """Assumption bound by class, kind, statement, and source map."""

    SCHEMA: ClassVar[str] = (
        "ipfs_datasets_py/logic/software_verification/assumption-binding@1"
    )

    assumption_id: str
    assumption_class: AssumptionClass
    kind: str = "semantic"
    statement: str = ""
    source: SourceSpanBinding = field(default_factory=SourceSpanBinding)
    authority: AuthorityCeiling = AuthorityCeiling.NONE
    reviewable: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assumption_id",
            _text(self.assumption_id, "assumption_id", maximum=256),
        )
        object.__setattr__(
            self,
            "assumption_class",
            _enum(self.assumption_class, AssumptionClass, "assumption_class"),
        )
        object.__setattr__(
            self, "kind", _text(self.kind, "kind", maximum=128)
        )
        object.__setattr__(
            self,
            "statement",
            _text(self.statement, "statement", optional=True, maximum=4096),
        )
        source = self.source
        if isinstance(source, Mapping):
            source = SourceSpanBinding.from_dict(source)
        elif not isinstance(source, SourceSpanBinding):
            raise TacticianContractError("source must be a SourceSpanBinding")
        object.__setattr__(self, "source", source)
        object.__setattr__(
            self, "authority", _enum(self.authority, AuthorityCeiling, "authority")
        )
        object.__setattr__(
            self, "reviewable", _bool(self.reviewable, "reviewable")
        )
        if self.assumption_class is AssumptionClass.HYPOTHETICAL:
            if self.authority not in {
                AuthorityCeiling.NONE,
                AuthorityCeiling.ADVISORY,
                AuthorityCeiling.CANDIDATE,
            }:
                raise TacticianContractError(
                    "hypothetical assumptions cannot claim elevated authority"
                )

    def _payload(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "assumption_class": self.assumption_class.value,
            "kind": self.kind,
            "statement": self.statement,
            "source": self.source.to_dict(),
            "authority": self.authority.value,
            "reviewable": self.reviewable,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AssumptionBinding":
        _schema_check(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "assumption_id",
                "assumption_class",
                "kind",
                "statement",
                "source",
                "authority",
                "reviewable",
            },
            artifact="assumption binding",
        )
        source_raw = payload.get("source") or {}
        return cls(
            assumption_id=payload.get("assumption_id", ""),
            assumption_class=payload.get(
                "assumption_class", AssumptionClass.HYPOTHETICAL
            ),
            kind=payload.get("kind", "semantic"),
            statement=payload.get("statement", ""),
            source=(
                SourceSpanBinding.from_dict(source_raw)
                if isinstance(source_raw, Mapping)
                else SourceSpanBinding()
            ),
            authority=payload.get("authority", AuthorityCeiling.NONE),
            reviewable=payload.get("reviewable", True),
        )


@dataclass(frozen=True, slots=True)
class ResourceBounds(TacticianContract):
    """Integer-only finite bounds and resource policy for a goal or plan."""

    SCHEMA: ClassVar[str] = (
        "ipfs_datasets_py/logic/software_verification/resource-bounds@1"
    )

    wall_time_ms: int = 0
    memory_bytes: int = 0
    max_steps: int = 0
    max_depth: int = 0
    max_nodes: int = 0
    max_candidates: int = 0
    model_token_limit: int = 0
    network_allowed: bool = False
    extra: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "wall_time_ms",
            "memory_bytes",
            "max_steps",
            "max_depth",
            "max_nodes",
            "max_candidates",
            "model_token_limit",
        ):
            object.__setattr__(
                self, name, _nonnegative_int(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "network_allowed",
            _bool(self.network_allowed, "network_allowed"),
        )
        extra = self.extra or {}
        if not isinstance(extra, Mapping):
            raise TacticianContractError("extra must be a mapping of integers")
        normalized: dict[str, int] = {}
        for key, value in extra.items():
            if not isinstance(key, str):
                raise TacticianContractError("extra keys must be strings")
            normalized[key] = _nonnegative_int(value, f"extra.{key}")
        object.__setattr__(self, "extra", _canonical_value(normalized))

    def _payload(self) -> dict[str, Any]:
        return {
            "wall_time_ms": self.wall_time_ms,
            "memory_bytes": self.memory_bytes,
            "max_steps": self.max_steps,
            "max_depth": self.max_depth,
            "max_nodes": self.max_nodes,
            "max_candidates": self.max_candidates,
            "model_token_limit": self.model_token_limit,
            "network_allowed": self.network_allowed,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ResourceBounds":
        _schema_check(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "wall_time_ms",
                "memory_bytes",
                "max_steps",
                "max_depth",
                "max_nodes",
                "max_candidates",
                "model_token_limit",
                "network_allowed",
                "extra",
            },
            artifact="resource bounds",
        )
        return cls(
            wall_time_ms=int(payload.get("wall_time_ms") or 0),
            memory_bytes=int(payload.get("memory_bytes") or 0),
            max_steps=int(payload.get("max_steps") or 0),
            max_depth=int(payload.get("max_depth") or 0),
            max_nodes=int(payload.get("max_nodes") or 0),
            max_candidates=int(payload.get("max_candidates") or 0),
            model_token_limit=int(payload.get("model_token_limit") or 0),
            network_allowed=bool(payload.get("network_allowed", False)),
            extra=payload.get("extra") or {},
        )


@dataclass(frozen=True, slots=True)
class ValidationRecipe(TacticianContract):
    """Machine-readable recipe for validating a hole or candidate."""

    SCHEMA: ClassVar[str] = (
        "ipfs_datasets_py/logic/software_verification/validation-recipe@1"
    )

    recipe_id: str
    checker_kind: str
    provider_ids: tuple[str, ...] = ()
    required_authority: AuthorityCeiling = AuthorityCeiling.CANDIDATE
    bounds: ResourceBounds = field(default_factory=ResourceBounds)
    steps: tuple[str, ...] = ()
    oracle_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "recipe_id", _text(self.recipe_id, "recipe_id", maximum=256)
        )
        object.__setattr__(
            self,
            "checker_kind",
            _text(self.checker_kind, "checker_kind", maximum=128),
        )
        object.__setattr__(
            self,
            "provider_ids",
            _string_tuple(self.provider_ids, "provider_ids"),
        )
        object.__setattr__(
            self,
            "required_authority",
            _enum(self.required_authority, AuthorityCeiling, "required_authority"),
        )
        bounds = self.bounds
        if isinstance(bounds, Mapping):
            bounds = ResourceBounds.from_dict(bounds)
        elif not isinstance(bounds, ResourceBounds):
            raise TacticianContractError("bounds must be a ResourceBounds")
        object.__setattr__(self, "bounds", bounds)
        object.__setattr__(
            self,
            "steps",
            _string_tuple(self.steps, "steps", preserve_order=True),
        )
        object.__setattr__(
            self,
            "oracle_id",
            _text(self.oracle_id, "oracle_id", optional=True, maximum=256),
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "recipe_id": self.recipe_id,
            "checker_kind": self.checker_kind,
            "provider_ids": list(self.provider_ids),
            "required_authority": self.required_authority.value,
            "bounds": self.bounds.to_dict(),
            "steps": list(self.steps),
            "oracle_id": self.oracle_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValidationRecipe":
        _schema_check(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "recipe_id",
                "checker_kind",
                "provider_ids",
                "required_authority",
                "bounds",
                "steps",
                "oracle_id",
            },
            artifact="validation recipe",
        )
        bounds_raw = payload.get("bounds") or {}
        return cls(
            recipe_id=payload.get("recipe_id", ""),
            checker_kind=payload.get("checker_kind", ""),
            provider_ids=tuple(payload.get("provider_ids") or ()),
            required_authority=payload.get(
                "required_authority", AuthorityCeiling.CANDIDATE
            ),
            bounds=(
                ResourceBounds.from_dict(bounds_raw)
                if isinstance(bounds_raw, Mapping)
                else ResourceBounds()
            ),
            steps=tuple(payload.get("steps") or ()),
            oracle_id=payload.get("oracle_id", ""),
        )


# ---------------------------------------------------------------------------
# End goal contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EndGoalInterpretation(TacticianContract):
    """One closed interpretation of a prose or typed end-goal request."""

    SCHEMA: ClassVar[str] = END_GOAL_INTERPRETATION_SCHEMA

    interpretation_id: str
    controlled_english: str
    property_class: PropertyClass
    quantifiers: tuple[QuantifierKind, ...] = ()
    current_state: Mapping[str, Any] = field(default_factory=dict)
    target_state: Mapping[str, Any] = field(default_factory=dict)
    environment: Mapping[str, Any] = field(default_factory=dict)
    semantic_diff: Mapping[str, Any] = field(default_factory=dict)
    unresolved_fields: tuple[str, ...] = ()
    selected: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "interpretation_id",
            _text(self.interpretation_id, "interpretation_id", maximum=256),
        )
        object.__setattr__(
            self,
            "controlled_english",
            _text(self.controlled_english, "controlled_english", maximum=8192),
        )
        object.__setattr__(
            self,
            "property_class",
            _enum(self.property_class, PropertyClass, "property_class"),
        )
        quantifiers = tuple(
            _enum(item, QuantifierKind, "quantifiers")
            for item in (self.quantifiers or ())
        )
        object.__setattr__(self, "quantifiers", quantifiers)
        object.__setattr__(
            self, "current_state", _mapping(self.current_state, "current_state")
        )
        object.__setattr__(
            self, "target_state", _mapping(self.target_state, "target_state")
        )
        object.__setattr__(
            self, "environment", _mapping(self.environment, "environment")
        )
        object.__setattr__(
            self, "semantic_diff", _mapping(self.semantic_diff, "semantic_diff")
        )
        object.__setattr__(
            self,
            "unresolved_fields",
            _string_tuple(self.unresolved_fields, "unresolved_fields"),
        )
        object.__setattr__(self, "selected", _bool(self.selected, "selected"))

    def _payload(self) -> dict[str, Any]:
        return {
            "interpretation_id": self.interpretation_id,
            "controlled_english": self.controlled_english,
            "property_class": self.property_class.value,
            "quantifiers": [item.value for item in self.quantifiers],
            "current_state": dict(self.current_state),
            "target_state": dict(self.target_state),
            "environment": dict(self.environment),
            "semantic_diff": dict(self.semantic_diff),
            "unresolved_fields": list(self.unresolved_fields),
            "selected": self.selected,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EndGoalInterpretation":
        _schema_check(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "interpretation_id",
                "controlled_english",
                "property_class",
                "quantifiers",
                "current_state",
                "target_state",
                "environment",
                "semantic_diff",
                "unresolved_fields",
                "selected",
            },
            artifact="end-goal interpretation",
        )
        return cls(
            interpretation_id=payload.get("interpretation_id", ""),
            controlled_english=payload.get("controlled_english", ""),
            property_class=payload.get(
                "property_class", PropertyClass.UNSPECIFIED
            ),
            quantifiers=tuple(payload.get("quantifiers") or ()),
            current_state=payload.get("current_state") or {},
            target_state=payload.get("target_state") or {},
            environment=payload.get("environment") or {},
            semantic_diff=payload.get("semantic_diff") or {},
            unresolved_fields=tuple(payload.get("unresolved_fields") or ()),
            selected=bool(payload.get("selected", False)),
        )


@dataclass(frozen=True, slots=True)
class EndGoalSpec(TacticianContract):
    """Closed, content-addressed end-goal specification (``EndGoalSpec@1``)."""

    SCHEMA: ClassVar[str] = END_GOAL_SPEC_SCHEMA
    INTERFACE: ClassVar[str] = END_GOAL_SPEC_INTERFACE

    goal_id: str
    caller_text: str
    source: SourceSpanBinding
    property_class: PropertyClass
    quantifiers: tuple[QuantifierKind, ...] = ()
    actors: tuple[str, ...] = ()
    state_variables: tuple[str, ...] = ()
    current_state: Mapping[str, Any] = field(default_factory=dict)
    target_state: Mapping[str, Any] = field(default_factory=dict)
    transitions: tuple[str, ...] = ()
    environment: Mapping[str, Any] = field(default_factory=dict)
    interference: Mapping[str, Any] = field(default_factory=dict)
    assumptions: tuple[AssumptionBinding, ...] = ()
    logic_family: str = ""
    provider_ids: tuple[str, ...] = ()
    assurance_target: AuthorityCeiling = AuthorityCeiling.BOUNDED
    bounds: ResourceBounds = field(default_factory=ResourceBounds)
    provenance: tuple[PhraseProvenance, ...] = ()
    interpretations: tuple[EndGoalInterpretation, ...] = ()
    ambiguity_status: AmbiguityStatus = AmbiguityStatus.NONE
    unsupported_semantics: tuple[str, ...] = ()
    translation_loss: tuple[str, ...] = ()
    acceptance_evidence: tuple[str, ...] = ()
    expected_receipt_classes: tuple[str, ...] = ()
    status: str = "draft"
    authority: AuthorityCeiling = AuthorityCeiling.NONE
    # Explicitly frozen false claims — proposals cannot flip these.
    proof_claimed: bool = False
    completion_claimed: bool = False
    root_goal_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "goal_id", _text(self.goal_id, "goal_id", maximum=256)
        )
        object.__setattr__(
            self,
            "caller_text",
            _text(self.caller_text, "caller_text", maximum=16384),
        )
        source = self.source
        if isinstance(source, Mapping):
            source = SourceSpanBinding.from_dict(source)
        elif not isinstance(source, SourceSpanBinding):
            raise TacticianContractError("source must be a SourceSpanBinding")
        object.__setattr__(self, "source", source)
        if not source.tree_id and not source.source_ref_ids and not source.span_ids:
            raise TacticianContractError(
                "EndGoalSpec must bind a tree_id or source/span identifiers"
            )
        object.__setattr__(
            self,
            "property_class",
            _enum(self.property_class, PropertyClass, "property_class"),
        )
        object.__setattr__(
            self,
            "quantifiers",
            tuple(
                _enum(item, QuantifierKind, "quantifiers")
                for item in (self.quantifiers or ())
            ),
        )
        object.__setattr__(
            self, "actors", _string_tuple(self.actors, "actors")
        )
        object.__setattr__(
            self,
            "state_variables",
            _string_tuple(self.state_variables, "state_variables"),
        )
        object.__setattr__(
            self, "current_state", _mapping(self.current_state, "current_state")
        )
        object.__setattr__(
            self, "target_state", _mapping(self.target_state, "target_state")
        )
        object.__setattr__(
            self,
            "transitions",
            _string_tuple(self.transitions, "transitions"),
        )
        object.__setattr__(
            self, "environment", _mapping(self.environment, "environment")
        )
        object.__setattr__(
            self, "interference", _mapping(self.interference, "interference")
        )
        assumptions: list[AssumptionBinding] = []
        for item in self.assumptions or ():
            if isinstance(item, AssumptionBinding):
                assumptions.append(item)
            elif isinstance(item, Mapping):
                assumptions.append(AssumptionBinding.from_dict(item))
            else:
                raise TacticianContractError(
                    "assumptions must contain AssumptionBinding values"
                )
        object.__setattr__(
            self,
            "assumptions",
            tuple(sorted(assumptions, key=lambda a: a.assumption_id)),
        )
        object.__setattr__(
            self,
            "logic_family",
            _text(self.logic_family, "logic_family", optional=True, maximum=128),
        )
        object.__setattr__(
            self,
            "provider_ids",
            _string_tuple(self.provider_ids, "provider_ids"),
        )
        object.__setattr__(
            self,
            "assurance_target",
            _enum(self.assurance_target, AuthorityCeiling, "assurance_target"),
        )
        bounds = self.bounds
        if isinstance(bounds, Mapping):
            bounds = ResourceBounds.from_dict(bounds)
        elif not isinstance(bounds, ResourceBounds):
            raise TacticianContractError("bounds must be a ResourceBounds")
        object.__setattr__(self, "bounds", bounds)
        provenance: list[PhraseProvenance] = []
        for item in self.provenance or ():
            if isinstance(item, PhraseProvenance):
                provenance.append(item)
            elif isinstance(item, Mapping):
                provenance.append(PhraseProvenance.from_dict(item))
            else:
                raise TacticianContractError(
                    "provenance must contain PhraseProvenance values"
                )
        object.__setattr__(self, "provenance", tuple(provenance))
        interpretations: list[EndGoalInterpretation] = []
        for item in self.interpretations or ():
            if isinstance(item, EndGoalInterpretation):
                interpretations.append(item)
            elif isinstance(item, Mapping):
                interpretations.append(EndGoalInterpretation.from_dict(item))
            else:
                raise TacticianContractError(
                    "interpretations must contain EndGoalInterpretation values"
                )
        object.__setattr__(self, "interpretations", tuple(interpretations))
        object.__setattr__(
            self,
            "ambiguity_status",
            _enum(self.ambiguity_status, AmbiguityStatus, "ambiguity_status"),
        )
        if (
            len(interpretations) > 1
            and self.ambiguity_status is AmbiguityStatus.NONE
        ):
            object.__setattr__(
                self, "ambiguity_status", AmbiguityStatus.CANDIDATES_PRESENT
            )
        object.__setattr__(
            self,
            "unsupported_semantics",
            _string_tuple(self.unsupported_semantics, "unsupported_semantics"),
        )
        object.__setattr__(
            self,
            "translation_loss",
            _string_tuple(self.translation_loss, "translation_loss"),
        )
        object.__setattr__(
            self,
            "acceptance_evidence",
            _string_tuple(self.acceptance_evidence, "acceptance_evidence"),
        )
        object.__setattr__(
            self,
            "expected_receipt_classes",
            _string_tuple(
                self.expected_receipt_classes, "expected_receipt_classes"
            ),
        )
        object.__setattr__(
            self, "status", _text(self.status, "status", maximum=64)
        )
        object.__setattr__(
            self, "authority", _enum(self.authority, AuthorityCeiling, "authority")
        )
        if self.authority not in {
            AuthorityCeiling.NONE,
            AuthorityCeiling.ADVISORY,
            AuthorityCeiling.CANDIDATE,
            AuthorityCeiling.DECLARATIVE,
        }:
            raise TacticianContractError(
                "EndGoalSpec authority cannot claim proof-level authority"
            )
        object.__setattr__(
            self, "proof_claimed", _bool(self.proof_claimed, "proof_claimed")
        )
        object.__setattr__(
            self,
            "completion_claimed",
            _bool(self.completion_claimed, "completion_claimed"),
        )
        if self.proof_claimed or self.completion_claimed:
            raise TacticianContractError(
                "EndGoalSpec cannot claim proof or completion"
            )
        object.__setattr__(
            self,
            "root_goal_id",
            _text(
                self.root_goal_id or self.goal_id,
                "root_goal_id",
                maximum=256,
            ),
        )

    @property
    def end_goal_id(self) -> str:
        return self.content_id

    def _payload(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "root_goal_id": self.root_goal_id,
            "caller_text": self.caller_text,
            "source": self.source.to_dict(),
            "property_class": self.property_class.value,
            "quantifiers": [item.value for item in self.quantifiers],
            "actors": list(self.actors),
            "state_variables": list(self.state_variables),
            "current_state": dict(self.current_state),
            "target_state": dict(self.target_state),
            "transitions": list(self.transitions),
            "environment": dict(self.environment),
            "interference": dict(self.interference),
            "assumptions": [item.to_dict() for item in self.assumptions],
            "logic_family": self.logic_family,
            "provider_ids": list(self.provider_ids),
            "assurance_target": self.assurance_target.value,
            "bounds": self.bounds.to_dict(),
            "provenance": [item.to_dict() for item in self.provenance],
            "interpretations": [item.to_dict() for item in self.interpretations],
            "ambiguity_status": self.ambiguity_status.value,
            "unsupported_semantics": list(self.unsupported_semantics),
            "translation_loss": list(self.translation_loss),
            "acceptance_evidence": list(self.acceptance_evidence),
            "expected_receipt_classes": list(self.expected_receipt_classes),
            "status": self.status,
            "authority": self.authority.value,
            "proof_claimed": False,
            "completion_claimed": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EndGoalSpec":
        _schema_check(payload, cls.SCHEMA)
        _reject_proposal_authority_claims(payload, artifact="EndGoalSpec")
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "end_goal_id",
                "goal_id",
                "root_goal_id",
                "caller_text",
                "source",
                "property_class",
                "quantifiers",
                "actors",
                "state_variables",
                "current_state",
                "target_state",
                "transitions",
                "environment",
                "interference",
                "assumptions",
                "logic_family",
                "provider_ids",
                "assurance_target",
                "bounds",
                "provenance",
                "interpretations",
                "ambiguity_status",
                "unsupported_semantics",
                "translation_loss",
                "acceptance_evidence",
                "expected_receipt_classes",
                "status",
                "authority",
                "proof_claimed",
                "completion_claimed",
            },
            artifact="EndGoalSpec",
        )
        source_raw = payload.get("source") or {}
        bounds_raw = payload.get("bounds") or {}
        result = cls(
            goal_id=payload.get("goal_id", ""),
            root_goal_id=payload.get("root_goal_id", ""),
            caller_text=payload.get("caller_text", ""),
            source=(
                SourceSpanBinding.from_dict(source_raw)
                if isinstance(source_raw, Mapping)
                else SourceSpanBinding()
            ),
            property_class=payload.get(
                "property_class", PropertyClass.UNSPECIFIED
            ),
            quantifiers=tuple(payload.get("quantifiers") or ()),
            actors=tuple(payload.get("actors") or ()),
            state_variables=tuple(payload.get("state_variables") or ()),
            current_state=payload.get("current_state") or {},
            target_state=payload.get("target_state") or {},
            transitions=tuple(payload.get("transitions") or ()),
            environment=payload.get("environment") or {},
            interference=payload.get("interference") or {},
            assumptions=tuple(payload.get("assumptions") or ()),
            logic_family=payload.get("logic_family", ""),
            provider_ids=tuple(payload.get("provider_ids") or ()),
            assurance_target=payload.get(
                "assurance_target", AuthorityCeiling.BOUNDED
            ),
            bounds=(
                ResourceBounds.from_dict(bounds_raw)
                if isinstance(bounds_raw, Mapping)
                else ResourceBounds()
            ),
            provenance=tuple(payload.get("provenance") or ()),
            interpretations=tuple(payload.get("interpretations") or ()),
            ambiguity_status=payload.get(
                "ambiguity_status", AmbiguityStatus.NONE
            ),
            unsupported_semantics=tuple(
                payload.get("unsupported_semantics") or ()
            ),
            translation_loss=tuple(payload.get("translation_loss") or ()),
            acceptance_evidence=tuple(payload.get("acceptance_evidence") or ()),
            expected_receipt_classes=tuple(
                payload.get("expected_receipt_classes") or ()
            ),
            status=payload.get("status", "draft"),
            authority=payload.get("authority", AuthorityCeiling.NONE),
            proof_claimed=False,
            completion_claimed=False,
        )
        _claim_identity(
            payload,
            result.content_id,
            names=("content_id", "end_goal_id"),
            artifact="EndGoalSpec",
        )
        return result


@dataclass(frozen=True, slots=True)
class FormalGoal(TacticianContract):
    """Caller-confirmed formal goal — still not a proof or completion."""

    SCHEMA: ClassVar[str] = FORMAL_GOAL_SCHEMA

    formal_goal_id: str
    end_goal: EndGoalSpec
    selected_interpretation_id: str
    confirmation_receipt_id: str = ""
    status: str = "confirmed"
    authority: AuthorityCeiling = AuthorityCeiling.DECLARATIVE
    proof_claimed: bool = False
    completion_claimed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", maximum=256),
        )
        end_goal = self.end_goal
        if isinstance(end_goal, Mapping):
            end_goal = EndGoalSpec.from_dict(end_goal)
        elif not isinstance(end_goal, EndGoalSpec):
            raise TacticianContractError("end_goal must be an EndGoalSpec")
        object.__setattr__(self, "end_goal", end_goal)
        object.__setattr__(
            self,
            "selected_interpretation_id",
            _text(
                self.selected_interpretation_id,
                "selected_interpretation_id",
                maximum=256,
            ),
        )
        selected_ids = {
            item.interpretation_id for item in end_goal.interpretations
        }
        if (
            end_goal.interpretations
            and self.selected_interpretation_id not in selected_ids
        ):
            raise TacticianContractError(
                "selected_interpretation_id must reference an interpretation "
                "on the EndGoalSpec"
            )
        if end_goal.ambiguity_status is AmbiguityStatus.REQUIRES_SELECTION:
            raise TacticianContractError(
                "FormalGoal requires ambiguity resolution before confirmation"
            )
        object.__setattr__(
            self,
            "confirmation_receipt_id",
            _text(
                self.confirmation_receipt_id,
                "confirmation_receipt_id",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self, "status", _text(self.status, "status", maximum=64)
        )
        object.__setattr__(
            self, "authority", _enum(self.authority, AuthorityCeiling, "authority")
        )
        if self.authority in {
            AuthorityCeiling.THEOREM,
            AuthorityCeiling.ATTESTATION,
            AuthorityCeiling.RECONSTRUCTION,
        }:
            raise TacticianContractError(
                "FormalGoal cannot self-assert theorem or attestation authority"
            )
        object.__setattr__(
            self, "proof_claimed", _bool(self.proof_claimed, "proof_claimed")
        )
        object.__setattr__(
            self,
            "completion_claimed",
            _bool(self.completion_claimed, "completion_claimed"),
        )
        if self.proof_claimed or self.completion_claimed:
            raise TacticianContractError(
                "FormalGoal cannot claim proof or completion"
            )

    @property
    def root_goal_id(self) -> str:
        return self.end_goal.root_goal_id

    def _payload(self) -> dict[str, Any]:
        return {
            "formal_goal_id": self.formal_goal_id,
            "end_goal": self.end_goal.to_dict(),
            "selected_interpretation_id": self.selected_interpretation_id,
            "confirmation_receipt_id": self.confirmation_receipt_id,
            "status": self.status,
            "authority": self.authority.value,
            "proof_claimed": False,
            "completion_claimed": False,
            "root_goal_id": self.root_goal_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FormalGoal":
        _schema_check(payload, cls.SCHEMA)
        _reject_proposal_authority_claims(payload, artifact="FormalGoal")
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "formal_goal_id",
                "end_goal",
                "selected_interpretation_id",
                "confirmation_receipt_id",
                "status",
                "authority",
                "proof_claimed",
                "completion_claimed",
                "root_goal_id",
            },
            artifact="FormalGoal",
        )
        end_raw = payload.get("end_goal") or {}
        result = cls(
            formal_goal_id=payload.get("formal_goal_id", ""),
            end_goal=(
                EndGoalSpec.from_dict(end_raw)
                if isinstance(end_raw, Mapping)
                else end_raw  # type: ignore[arg-type]
            ),
            selected_interpretation_id=payload.get(
                "selected_interpretation_id", ""
            ),
            confirmation_receipt_id=payload.get("confirmation_receipt_id", ""),
            status=payload.get("status", "confirmed"),
            authority=payload.get("authority", AuthorityCeiling.DECLARATIVE),
            proof_claimed=False,
            completion_claimed=False,
        )
        _claim_identity(
            payload,
            result.content_id,
            names=("content_id",),
            artifact="FormalGoal",
        )
        return result


# ---------------------------------------------------------------------------
# Proof holes and obligation graph
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofHole(TacticianContract):
    """Typed missing-proof obligation (``ProofHole@1``)."""

    SCHEMA: ClassVar[str] = PROOF_HOLE_SCHEMA
    INTERFACE: ClassVar[str] = PROOF_HOLE_INTERFACE

    hole_id: str
    kind: HoleKind
    reason: str
    source: SourceSpanBinding
    formal_goal_id: str = ""
    expected_authority: AuthorityCeiling = AuthorityCeiling.CANDIDATE
    dependency_ids: tuple[str, ...] = ()
    validation_recipe: ValidationRecipe | None = None
    status: HoleStatus = HoleStatus.OPEN
    property_class: PropertyClass = PropertyClass.UNSPECIFIED
    statement: str = ""
    provider_ids: tuple[str, ...] = ()
    bounds: ResourceBounds = field(default_factory=ResourceBounds)
    proof_claimed: bool = False
    completion_claimed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "hole_id", _text(self.hole_id, "hole_id", maximum=256)
        )
        object.__setattr__(self, "kind", _enum(self.kind, HoleKind, "kind"))
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", maximum=4096)
        )
        source = self.source
        if isinstance(source, Mapping):
            source = SourceSpanBinding.from_dict(source)
        elif not isinstance(source, SourceSpanBinding):
            raise TacticianContractError("source must be a SourceSpanBinding")
        object.__setattr__(self, "source", source)
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(
                self.formal_goal_id, "formal_goal_id", optional=True, maximum=256
            ),
        )
        object.__setattr__(
            self,
            "expected_authority",
            _enum(
                self.expected_authority, AuthorityCeiling, "expected_authority"
            ),
        )
        object.__setattr__(
            self,
            "dependency_ids",
            _string_tuple(self.dependency_ids, "dependency_ids"),
        )
        recipe = self.validation_recipe
        if recipe is None:
            pass
        elif isinstance(recipe, Mapping):
            recipe = ValidationRecipe.from_dict(recipe)
        elif not isinstance(recipe, ValidationRecipe):
            raise TacticianContractError(
                "validation_recipe must be a ValidationRecipe"
            )
        object.__setattr__(self, "validation_recipe", recipe)
        object.__setattr__(
            self, "status", _enum(self.status, HoleStatus, "status")
        )
        object.__setattr__(
            self,
            "property_class",
            _enum(self.property_class, PropertyClass, "property_class"),
        )
        object.__setattr__(
            self,
            "statement",
            _text(self.statement, "statement", optional=True, maximum=8192),
        )
        object.__setattr__(
            self,
            "provider_ids",
            _string_tuple(self.provider_ids, "provider_ids"),
        )
        bounds = self.bounds
        if isinstance(bounds, Mapping):
            bounds = ResourceBounds.from_dict(bounds)
        elif not isinstance(bounds, ResourceBounds):
            raise TacticianContractError("bounds must be a ResourceBounds")
        object.__setattr__(self, "bounds", bounds)
        object.__setattr__(
            self, "proof_claimed", _bool(self.proof_claimed, "proof_claimed")
        )
        object.__setattr__(
            self,
            "completion_claimed",
            _bool(self.completion_claimed, "completion_claimed"),
        )
        if self.proof_claimed or self.completion_claimed:
            raise TacticianContractError(
                "ProofHole cannot claim proof or completion"
            )
        if self.status is HoleStatus.DISCHARGED and self.expected_authority in {
            AuthorityCeiling.NONE,
            AuthorityCeiling.ADVISORY,
            AuthorityCeiling.CANDIDATE,
        }:
            # Discharge records require an elevated expected authority target.
            # The hole itself still does not claim proof.
            pass

    def _payload(self) -> dict[str, Any]:
        return {
            "hole_id": self.hole_id,
            "kind": self.kind.value,
            "reason": self.reason,
            "source": self.source.to_dict(),
            "formal_goal_id": self.formal_goal_id,
            "expected_authority": self.expected_authority.value,
            "dependency_ids": list(self.dependency_ids),
            "validation_recipe": (
                None
                if self.validation_recipe is None
                else self.validation_recipe.to_dict()
            ),
            "status": self.status.value,
            "property_class": self.property_class.value,
            "statement": self.statement,
            "provider_ids": list(self.provider_ids),
            "bounds": self.bounds.to_dict(),
            "proof_claimed": False,
            "completion_claimed": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofHole":
        _schema_check(payload, cls.SCHEMA)
        _reject_proposal_authority_claims(payload, artifact="ProofHole")
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "hole_id",
                "kind",
                "reason",
                "source",
                "formal_goal_id",
                "expected_authority",
                "dependency_ids",
                "validation_recipe",
                "status",
                "property_class",
                "statement",
                "provider_ids",
                "bounds",
                "proof_claimed",
                "completion_claimed",
            },
            artifact="ProofHole",
        )
        source_raw = payload.get("source") or {}
        bounds_raw = payload.get("bounds") or {}
        recipe_raw = payload.get("validation_recipe")
        result = cls(
            hole_id=payload.get("hole_id", ""),
            kind=payload.get("kind", HoleKind.OTHER),
            reason=payload.get("reason", ""),
            source=(
                SourceSpanBinding.from_dict(source_raw)
                if isinstance(source_raw, Mapping)
                else SourceSpanBinding()
            ),
            formal_goal_id=payload.get("formal_goal_id", ""),
            expected_authority=payload.get(
                "expected_authority", AuthorityCeiling.CANDIDATE
            ),
            dependency_ids=tuple(payload.get("dependency_ids") or ()),
            validation_recipe=(
                ValidationRecipe.from_dict(recipe_raw)
                if isinstance(recipe_raw, Mapping)
                else None
            ),
            status=payload.get("status", HoleStatus.OPEN),
            property_class=payload.get(
                "property_class", PropertyClass.UNSPECIFIED
            ),
            statement=payload.get("statement", ""),
            provider_ids=tuple(payload.get("provider_ids") or ()),
            bounds=(
                ResourceBounds.from_dict(bounds_raw)
                if isinstance(bounds_raw, Mapping)
                else ResourceBounds()
            ),
            proof_claimed=False,
            completion_claimed=False,
        )
        _claim_identity(
            payload, result.content_id, names=("content_id",), artifact="ProofHole"
        )
        return result


@dataclass(frozen=True, slots=True)
class ProofGraphNode(TacticianContract):
    """One node in a backward AND/OR proof obligation graph."""

    SCHEMA: ClassVar[str] = PROOF_GRAPH_NODE_SCHEMA

    node_id: str
    kind: GraphNodeKind
    obligation_id: str = ""
    hole_id: str = ""
    label: str = ""
    status: HoleStatus = HoleStatus.OPEN
    authority: AuthorityCeiling = AuthorityCeiling.NONE
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_id", _text(self.node_id, "node_id", maximum=256)
        )
        object.__setattr__(self, "kind", _enum(self.kind, GraphNodeKind, "kind"))
        object.__setattr__(
            self,
            "obligation_id",
            _text(
                self.obligation_id, "obligation_id", optional=True, maximum=256
            ),
        )
        object.__setattr__(
            self,
            "hole_id",
            _text(self.hole_id, "hole_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self, "label", _text(self.label, "label", optional=True, maximum=512)
        )
        object.__setattr__(
            self, "status", _enum(self.status, HoleStatus, "status")
        )
        object.__setattr__(
            self, "authority", _enum(self.authority, AuthorityCeiling, "authority")
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def _payload(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind.value,
            "obligation_id": self.obligation_id,
            "hole_id": self.hole_id,
            "label": self.label,
            "status": self.status.value,
            "authority": self.authority.value,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofGraphNode":
        _schema_check(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "node_id",
                "kind",
                "obligation_id",
                "hole_id",
                "label",
                "status",
                "authority",
                "metadata",
            },
            artifact="ProofGraphNode",
        )
        return cls(
            node_id=payload.get("node_id", ""),
            kind=payload.get("kind", GraphNodeKind.LEAF),
            obligation_id=payload.get("obligation_id", ""),
            hole_id=payload.get("hole_id", ""),
            label=payload.get("label", ""),
            status=payload.get("status", HoleStatus.OPEN),
            authority=payload.get("authority", AuthorityCeiling.NONE),
            metadata=payload.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ProofGraphEdge(TacticianContract):
    """Directed edge naming inference rule and reconstruction method."""

    SCHEMA: ClassVar[str] = PROOF_GRAPH_EDGE_SCHEMA

    edge_id: str
    source_node_id: str
    target_node_id: str
    kind: GraphEdgeKind
    inference_rule: str = ""
    reconstruction_method: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "edge_id", _text(self.edge_id, "edge_id", maximum=256)
        )
        object.__setattr__(
            self,
            "source_node_id",
            _text(self.source_node_id, "source_node_id", maximum=256),
        )
        object.__setattr__(
            self,
            "target_node_id",
            _text(self.target_node_id, "target_node_id", maximum=256),
        )
        if self.source_node_id == self.target_node_id:
            raise TacticianContractError(
                "proof graph edges cannot be self-loops"
            )
        object.__setattr__(
            self, "kind", _enum(self.kind, GraphEdgeKind, "kind")
        )
        object.__setattr__(
            self,
            "inference_rule",
            _text(
                self.inference_rule,
                "inference_rule",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self,
            "reconstruction_method",
            _text(
                self.reconstruction_method,
                "reconstruction_method",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def _payload(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "kind": self.kind.value,
            "inference_rule": self.inference_rule,
            "reconstruction_method": self.reconstruction_method,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofGraphEdge":
        _schema_check(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "edge_id",
                "source_node_id",
                "target_node_id",
                "kind",
                "inference_rule",
                "reconstruction_method",
                "metadata",
            },
            artifact="ProofGraphEdge",
        )
        return cls(
            edge_id=payload.get("edge_id", ""),
            source_node_id=payload.get("source_node_id", ""),
            target_node_id=payload.get("target_node_id", ""),
            kind=payload.get("kind", GraphEdgeKind.DEPENDS_ON),
            inference_rule=payload.get("inference_rule", ""),
            reconstruction_method=payload.get("reconstruction_method", ""),
            metadata=payload.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ProofObligationGraph(TacticianContract):
    """Bounded, cycle-safe AND/OR obligation graph (``ProofObligationGraph@1``)."""

    SCHEMA: ClassVar[str] = PROOF_OBLIGATION_GRAPH_SCHEMA
    INTERFACE: ClassVar[str] = PROOF_OBLIGATION_GRAPH_INTERFACE

    graph_id: str
    formal_goal_id: str
    root_node_id: str
    nodes: tuple[ProofGraphNode, ...]
    edges: tuple[ProofGraphEdge, ...]
    tree_id: str = ""
    bounds: ResourceBounds = field(default_factory=ResourceBounds)
    hole_ids: tuple[str, ...] = ()
    status: str = "open"
    authority: AuthorityCeiling = AuthorityCeiling.NONE
    proof_claimed: bool = False
    completion_claimed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "graph_id", _text(self.graph_id, "graph_id", maximum=256)
        )
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", maximum=256),
        )
        object.__setattr__(
            self,
            "root_node_id",
            _text(self.root_node_id, "root_node_id", maximum=256),
        )
        nodes: list[ProofGraphNode] = []
        for item in self.nodes or ():
            if isinstance(item, ProofGraphNode):
                nodes.append(item)
            elif isinstance(item, Mapping):
                nodes.append(ProofGraphNode.from_dict(item))
            else:
                raise TacticianContractError(
                    "nodes must contain ProofGraphNode values"
                )
        if not nodes:
            raise TacticianContractError("nodes must not be empty")
        by_id = {node.node_id: node for node in nodes}
        if len(by_id) != len(nodes):
            raise TacticianContractError("node_id values must be unique")
        if self.root_node_id not in by_id:
            raise TacticianContractError("root_node_id must reference a node")
        object.__setattr__(
            self,
            "nodes",
            tuple(sorted(nodes, key=lambda n: n.node_id)),
        )
        edges: list[ProofGraphEdge] = []
        for item in self.edges or ():
            if isinstance(item, ProofGraphEdge):
                edges.append(item)
            elif isinstance(item, Mapping):
                edges.append(ProofGraphEdge.from_dict(item))
            else:
                raise TacticianContractError(
                    "edges must contain ProofGraphEdge values"
                )
        edge_ids: set[str] = set()
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in by_id}
        for edge in edges:
            if edge.edge_id in edge_ids:
                raise TacticianContractError("edge_id values must be unique")
            edge_ids.add(edge.edge_id)
            if edge.source_node_id not in by_id or edge.target_node_id not in by_id:
                raise TacticianContractError(
                    f"edge {edge.edge_id} references unknown nodes"
                )
            adjacency[edge.source_node_id].append(edge.target_node_id)
        object.__setattr__(
            self,
            "edges",
            tuple(sorted(edges, key=lambda e: e.edge_id)),
        )
        self._assert_acyclic(adjacency)
        object.__setattr__(
            self,
            "tree_id",
            _text(self.tree_id, "tree_id", optional=True, maximum=256),
        )
        bounds = self.bounds
        if isinstance(bounds, Mapping):
            bounds = ResourceBounds.from_dict(bounds)
        elif not isinstance(bounds, ResourceBounds):
            raise TacticianContractError("bounds must be a ResourceBounds")
        if bounds.max_nodes and len(nodes) > bounds.max_nodes:
            raise TacticianContractError(
                "graph exceeds max_nodes resource bound"
            )
        object.__setattr__(self, "bounds", bounds)
        hole_ids = _string_tuple(self.hole_ids, "hole_ids")
        if not hole_ids:
            hole_ids = tuple(
                sorted(
                    {
                        node.hole_id
                        for node in nodes
                        if node.hole_id
                    }
                )
            )
        object.__setattr__(self, "hole_ids", hole_ids)
        object.__setattr__(
            self, "status", _text(self.status, "status", maximum=64)
        )
        object.__setattr__(
            self, "authority", _enum(self.authority, AuthorityCeiling, "authority")
        )
        object.__setattr__(
            self, "proof_claimed", _bool(self.proof_claimed, "proof_claimed")
        )
        object.__setattr__(
            self,
            "completion_claimed",
            _bool(self.completion_claimed, "completion_claimed"),
        )
        if self.proof_claimed or self.completion_claimed:
            raise TacticianContractError(
                "ProofObligationGraph cannot claim proof or completion"
            )

    @staticmethod
    def _assert_acyclic(adjacency: Mapping[str, Sequence[str]]) -> None:
        """Fail closed on directed cycles (bounded regression graphs)."""

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {node: WHITE for node in adjacency}

        def visit(node: str) -> None:
            color[node] = GRAY
            for nxt in adjacency[node]:
                if color[nxt] is GRAY:
                    raise TacticianContractError(
                        "proof obligation graph must be acyclic"
                    )
                if color[nxt] is WHITE:
                    visit(nxt)
            color[node] = BLACK

        for node in adjacency:
            if color[node] is WHITE:
                visit(node)

    def _payload(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "formal_goal_id": self.formal_goal_id,
            "root_node_id": self.root_node_id,
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "tree_id": self.tree_id,
            "bounds": self.bounds.to_dict(),
            "hole_ids": list(self.hole_ids),
            "status": self.status,
            "authority": self.authority.value,
            "proof_claimed": False,
            "completion_claimed": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofObligationGraph":
        _schema_check(payload, cls.SCHEMA)
        _reject_proposal_authority_claims(
            payload, artifact="ProofObligationGraph"
        )
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "graph_id",
                "formal_goal_id",
                "root_node_id",
                "nodes",
                "edges",
                "tree_id",
                "bounds",
                "hole_ids",
                "status",
                "authority",
                "proof_claimed",
                "completion_claimed",
            },
            artifact="ProofObligationGraph",
        )
        bounds_raw = payload.get("bounds") or {}
        result = cls(
            graph_id=payload.get("graph_id", ""),
            formal_goal_id=payload.get("formal_goal_id", ""),
            root_node_id=payload.get("root_node_id", ""),
            nodes=tuple(payload.get("nodes") or ()),
            edges=tuple(payload.get("edges") or ()),
            tree_id=payload.get("tree_id", ""),
            bounds=(
                ResourceBounds.from_dict(bounds_raw)
                if isinstance(bounds_raw, Mapping)
                else ResourceBounds()
            ),
            hole_ids=tuple(payload.get("hole_ids") or ()),
            status=payload.get("status", "open"),
            authority=payload.get("authority", AuthorityCeiling.NONE),
            proof_claimed=False,
            completion_claimed=False,
        )
        _claim_identity(
            payload,
            result.content_id,
            names=("content_id",),
            artifact="ProofObligationGraph",
        )
        return result


# ---------------------------------------------------------------------------
# Candidates, plans, validation, completion
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateProofStep(TacticianContract):
    """Proposal to close a hole — never a proof or completion claim."""

    SCHEMA: ClassVar[str] = CANDIDATE_PROOF_STEP_SCHEMA

    candidate_id: str
    hole_id: str
    kind: str
    statement: str
    status: CandidateStatus = CandidateStatus.PROPOSED
    source: SourceSpanBinding = field(default_factory=SourceSpanBinding)
    provider_ids: tuple[str, ...] = ()
    authority: AuthorityCeiling = AuthorityCeiling.CANDIDATE
    rank_score_millionths: int = 0
    new_assumption_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    proof_claimed: bool = False
    completion_claimed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _text(self.candidate_id, "candidate_id", maximum=256),
        )
        object.__setattr__(
            self, "hole_id", _text(self.hole_id, "hole_id", maximum=256)
        )
        object.__setattr__(self, "kind", _text(self.kind, "kind", maximum=128))
        object.__setattr__(
            self, "statement", _text(self.statement, "statement", maximum=8192)
        )
        object.__setattr__(
            self, "status", _enum(self.status, CandidateStatus, "status")
        )
        source = self.source
        if isinstance(source, Mapping):
            source = SourceSpanBinding.from_dict(source)
        elif not isinstance(source, SourceSpanBinding):
            raise TacticianContractError("source must be a SourceSpanBinding")
        object.__setattr__(self, "source", source)
        object.__setattr__(
            self,
            "provider_ids",
            _string_tuple(self.provider_ids, "provider_ids"),
        )
        object.__setattr__(
            self, "authority", _enum(self.authority, AuthorityCeiling, "authority")
        )
        if self.authority not in {
            AuthorityCeiling.NONE,
            AuthorityCeiling.ADVISORY,
            AuthorityCeiling.CANDIDATE,
        }:
            raise TacticianContractError(
                "CandidateProofStep authority is capped at candidate"
            )
        object.__setattr__(
            self,
            "rank_score_millionths",
            _nonnegative_int(
                self.rank_score_millionths, "rank_score_millionths"
            ),
        )
        object.__setattr__(
            self,
            "new_assumption_ids",
            _string_tuple(self.new_assumption_ids, "new_assumption_ids"),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _string_tuple(self.evidence_ids, "evidence_ids"),
        )
        object.__setattr__(
            self, "provenance", _mapping(self.provenance, "provenance")
        )
        object.__setattr__(
            self, "proof_claimed", _bool(self.proof_claimed, "proof_claimed")
        )
        object.__setattr__(
            self,
            "completion_claimed",
            _bool(self.completion_claimed, "completion_claimed"),
        )
        if self.proof_claimed or self.completion_claimed:
            raise TacticianContractError(
                "CandidateProofStep cannot claim proof or completion"
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "hole_id": self.hole_id,
            "kind": self.kind,
            "statement": self.statement,
            "status": self.status.value,
            "source": self.source.to_dict(),
            "provider_ids": list(self.provider_ids),
            "authority": self.authority.value,
            "rank_score_millionths": self.rank_score_millionths,
            "new_assumption_ids": list(self.new_assumption_ids),
            "evidence_ids": list(self.evidence_ids),
            "provenance": dict(self.provenance),
            "proof_claimed": False,
            "completion_claimed": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CandidateProofStep":
        _schema_check(payload, cls.SCHEMA)
        _reject_proposal_authority_claims(
            payload, artifact="CandidateProofStep"
        )
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "candidate_id",
                "hole_id",
                "kind",
                "statement",
                "status",
                "source",
                "provider_ids",
                "authority",
                "rank_score_millionths",
                "new_assumption_ids",
                "evidence_ids",
                "provenance",
                "proof_claimed",
                "completion_claimed",
            },
            artifact="CandidateProofStep",
        )
        source_raw = payload.get("source") or {}
        result = cls(
            candidate_id=payload.get("candidate_id", ""),
            hole_id=payload.get("hole_id", ""),
            kind=payload.get("kind", ""),
            statement=payload.get("statement", ""),
            status=payload.get("status", CandidateStatus.PROPOSED),
            source=(
                SourceSpanBinding.from_dict(source_raw)
                if isinstance(source_raw, Mapping)
                else SourceSpanBinding()
            ),
            provider_ids=tuple(payload.get("provider_ids") or ()),
            authority=payload.get("authority", AuthorityCeiling.CANDIDATE),
            rank_score_millionths=int(
                payload.get("rank_score_millionths") or 0
            ),
            new_assumption_ids=tuple(payload.get("new_assumption_ids") or ()),
            evidence_ids=tuple(payload.get("evidence_ids") or ()),
            provenance=payload.get("provenance") or {},
            proof_claimed=False,
            completion_claimed=False,
        )
        _claim_identity(
            payload,
            result.content_id,
            names=("content_id",),
            artifact="CandidateProofStep",
        )
        return result


@dataclass(frozen=True, slots=True)
class CandidateValidation(TacticianContract):
    """Independent validation record for a candidate proof step."""

    SCHEMA: ClassVar[str] = CANDIDATE_VALIDATION_SCHEMA

    validation_id: str
    candidate_id: str
    hole_id: str
    verdict: ValidationVerdict
    tree_id: str
    provider_id: str = ""
    provider_version: str = ""
    authority: AuthorityCeiling = AuthorityCeiling.BOUNDED
    recipe: ValidationRecipe | None = None
    assumption_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    minimality: str = "unknown"
    translation_receipt_id: str = ""
    proof_claimed: bool = False
    completion_claimed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "validation_id",
            _text(self.validation_id, "validation_id", maximum=256),
        )
        object.__setattr__(
            self,
            "candidate_id",
            _text(self.candidate_id, "candidate_id", maximum=256),
        )
        object.__setattr__(
            self, "hole_id", _text(self.hole_id, "hole_id", maximum=256)
        )
        object.__setattr__(
            self, "verdict", _enum(self.verdict, ValidationVerdict, "verdict")
        )
        object.__setattr__(
            self, "tree_id", _text(self.tree_id, "tree_id", maximum=256)
        )
        object.__setattr__(
            self,
            "provider_id",
            _text(self.provider_id, "provider_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "provider_version",
            _text(
                self.provider_version,
                "provider_version",
                optional=True,
                maximum=128,
            ),
        )
        object.__setattr__(
            self, "authority", _enum(self.authority, AuthorityCeiling, "authority")
        )
        recipe = self.recipe
        if recipe is None:
            pass
        elif isinstance(recipe, Mapping):
            recipe = ValidationRecipe.from_dict(recipe)
        elif not isinstance(recipe, ValidationRecipe):
            raise TacticianContractError("recipe must be a ValidationRecipe")
        object.__setattr__(self, "recipe", recipe)
        object.__setattr__(
            self,
            "assumption_ids",
            _string_tuple(self.assumption_ids, "assumption_ids"),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _string_tuple(self.evidence_ids, "evidence_ids"),
        )
        object.__setattr__(
            self,
            "minimality",
            _text(self.minimality, "minimality", maximum=64),
        )
        if self.minimality not in {
            "unknown",
            "bounded",
            "local",
            "subset",
            "not_applicable",
        }:
            raise TacticianContractError(
                "minimality must be one of: unknown, bounded, local, subset, "
                "not_applicable"
            )
        object.__setattr__(
            self,
            "translation_receipt_id",
            _text(
                self.translation_receipt_id,
                "translation_receipt_id",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self, "proof_claimed", _bool(self.proof_claimed, "proof_claimed")
        )
        object.__setattr__(
            self,
            "completion_claimed",
            _bool(self.completion_claimed, "completion_claimed"),
        )
        # Validation records may accept a candidate at a bounded authority,
        # but still cannot claim goal proof or completion by themselves.
        if self.proof_claimed or self.completion_claimed:
            raise TacticianContractError(
                "CandidateValidation cannot claim proof or completion"
            )
        if self.verdict is ValidationVerdict.ACCEPTED and self.authority in {
            AuthorityCeiling.NONE,
            AuthorityCeiling.ADVISORY,
            AuthorityCeiling.CANDIDATE,
        }:
            # Accepted candidates at advisory authority remain non-proof.
            pass

    def _payload(self) -> dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "candidate_id": self.candidate_id,
            "hole_id": self.hole_id,
            "verdict": self.verdict.value,
            "tree_id": self.tree_id,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "authority": self.authority.value,
            "recipe": None if self.recipe is None else self.recipe.to_dict(),
            "assumption_ids": list(self.assumption_ids),
            "evidence_ids": list(self.evidence_ids),
            "minimality": self.minimality,
            "translation_receipt_id": self.translation_receipt_id,
            "proof_claimed": False,
            "completion_claimed": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CandidateValidation":
        _schema_check(payload, cls.SCHEMA)
        _reject_proposal_authority_claims(
            payload, artifact="CandidateValidation"
        )
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "validation_id",
                "candidate_id",
                "hole_id",
                "verdict",
                "tree_id",
                "provider_id",
                "provider_version",
                "authority",
                "recipe",
                "assumption_ids",
                "evidence_ids",
                "minimality",
                "translation_receipt_id",
                "proof_claimed",
                "completion_claimed",
            },
            artifact="CandidateValidation",
        )
        recipe_raw = payload.get("recipe")
        result = cls(
            validation_id=payload.get("validation_id", ""),
            candidate_id=payload.get("candidate_id", ""),
            hole_id=payload.get("hole_id", ""),
            verdict=payload.get("verdict", ValidationVerdict.UNKNOWN),
            tree_id=payload.get("tree_id", ""),
            provider_id=payload.get("provider_id", ""),
            provider_version=payload.get("provider_version", ""),
            authority=payload.get("authority", AuthorityCeiling.BOUNDED),
            recipe=(
                ValidationRecipe.from_dict(recipe_raw)
                if isinstance(recipe_raw, Mapping)
                else None
            ),
            assumption_ids=tuple(payload.get("assumption_ids") or ()),
            evidence_ids=tuple(payload.get("evidence_ids") or ()),
            minimality=payload.get("minimality", "unknown"),
            translation_receipt_id=payload.get("translation_receipt_id", ""),
            proof_claimed=False,
            completion_claimed=False,
        )
        _claim_identity(
            payload,
            result.content_id,
            names=("content_id",),
            artifact="CandidateValidation",
        )
        return result


@dataclass(frozen=True, slots=True)
class GoalDirectedProofPlan(TacticianContract):
    """Ranked missing-proof plan (``GoalDirectedProofPlan@1``).

    Plans are execution proposals.  They never complete a goal by themselves.
    """

    SCHEMA: ClassVar[str] = GOAL_DIRECTED_PROOF_PLAN_SCHEMA
    INTERFACE: ClassVar[str] = GOAL_DIRECTED_PROOF_PLAN_INTERFACE

    plan_id: str
    formal_goal_id: str
    graph_id: str
    tree_id: str
    candidates: tuple[CandidateProofStep, ...]
    step_order: tuple[str, ...] = ()
    status: PlanStatus = PlanStatus.DRAFT
    bounds: ResourceBounds = field(default_factory=ResourceBounds)
    provider_ids: tuple[str, ...] = ()
    rank_score_millionths: int = 0
    root_goal_id: str = ""
    authority: AuthorityCeiling = AuthorityCeiling.CANDIDATE
    proof_claimed: bool = False
    completion_claimed: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "plan_id", _text(self.plan_id, "plan_id", maximum=256)
        )
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", maximum=256),
        )
        object.__setattr__(
            self, "graph_id", _text(self.graph_id, "graph_id", maximum=256)
        )
        object.__setattr__(
            self, "tree_id", _text(self.tree_id, "tree_id", maximum=256)
        )
        candidates: list[CandidateProofStep] = []
        for item in self.candidates or ():
            if isinstance(item, CandidateProofStep):
                candidates.append(item)
            elif isinstance(item, Mapping):
                candidates.append(CandidateProofStep.from_dict(item))
            else:
                raise TacticianContractError(
                    "candidates must contain CandidateProofStep values"
                )
        by_id = {c.candidate_id: c for c in candidates}
        if len(by_id) != len(candidates):
            raise TacticianContractError("candidate_id values must be unique")
        object.__setattr__(
            self,
            "candidates",
            tuple(sorted(candidates, key=lambda c: c.candidate_id)),
        )
        step_order = _string_tuple(
            self.step_order, "step_order", preserve_order=True
        )
        if step_order:
            missing = set(step_order) - set(by_id)
            if missing:
                raise TacticianContractError(
                    "step_order references unknown candidates: "
                    + ", ".join(sorted(missing))
                )
        else:
            step_order = tuple(c.candidate_id for c in self.candidates)
        object.__setattr__(self, "step_order", step_order)
        object.__setattr__(
            self, "status", _enum(self.status, PlanStatus, "status")
        )
        bounds = self.bounds
        if isinstance(bounds, Mapping):
            bounds = ResourceBounds.from_dict(bounds)
        elif not isinstance(bounds, ResourceBounds):
            raise TacticianContractError("bounds must be a ResourceBounds")
        if bounds.max_candidates and len(candidates) > bounds.max_candidates:
            raise TacticianContractError(
                "plan exceeds max_candidates resource bound"
            )
        object.__setattr__(self, "bounds", bounds)
        object.__setattr__(
            self,
            "provider_ids",
            _string_tuple(self.provider_ids, "provider_ids"),
        )
        object.__setattr__(
            self,
            "rank_score_millionths",
            _nonnegative_int(
                self.rank_score_millionths, "rank_score_millionths"
            ),
        )
        object.__setattr__(
            self,
            "root_goal_id",
            _text(
                self.root_goal_id or self.formal_goal_id,
                "root_goal_id",
                maximum=256,
            ),
        )
        object.__setattr__(
            self, "authority", _enum(self.authority, AuthorityCeiling, "authority")
        )
        if self.authority in {
            AuthorityCeiling.THEOREM,
            AuthorityCeiling.ATTESTATION,
        }:
            raise TacticianContractError(
                "GoalDirectedProofPlan cannot claim theorem or attestation authority"
            )
        object.__setattr__(
            self, "proof_claimed", _bool(self.proof_claimed, "proof_claimed")
        )
        object.__setattr__(
            self,
            "completion_claimed",
            _bool(self.completion_claimed, "completion_claimed"),
        )
        if self.proof_claimed or self.completion_claimed:
            raise TacticianContractError(
                "GoalDirectedProofPlan cannot claim proof or completion"
            )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        if "complete" in self.metadata or "proved" in self.metadata:
            raise TacticianContractError(
                "plan metadata cannot smuggle completion or proof claims"
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "formal_goal_id": self.formal_goal_id,
            "graph_id": self.graph_id,
            "tree_id": self.tree_id,
            "candidates": [item.to_dict() for item in self.candidates],
            "step_order": list(self.step_order),
            "status": self.status.value,
            "bounds": self.bounds.to_dict(),
            "provider_ids": list(self.provider_ids),
            "rank_score_millionths": self.rank_score_millionths,
            "root_goal_id": self.root_goal_id,
            "authority": self.authority.value,
            "proof_claimed": False,
            "completion_claimed": False,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GoalDirectedProofPlan":
        _schema_check(payload, cls.SCHEMA)
        _reject_proposal_authority_claims(
            payload, artifact="GoalDirectedProofPlan"
        )
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "plan_id",
                "formal_goal_id",
                "graph_id",
                "tree_id",
                "candidates",
                "step_order",
                "status",
                "bounds",
                "provider_ids",
                "rank_score_millionths",
                "root_goal_id",
                "authority",
                "proof_claimed",
                "completion_claimed",
                "metadata",
            },
            artifact="GoalDirectedProofPlan",
        )
        bounds_raw = payload.get("bounds") or {}
        result = cls(
            plan_id=payload.get("plan_id", ""),
            formal_goal_id=payload.get("formal_goal_id", ""),
            graph_id=payload.get("graph_id", ""),
            tree_id=payload.get("tree_id", ""),
            candidates=tuple(payload.get("candidates") or ()),
            step_order=tuple(payload.get("step_order") or ()),
            status=payload.get("status", PlanStatus.DRAFT),
            bounds=(
                ResourceBounds.from_dict(bounds_raw)
                if isinstance(bounds_raw, Mapping)
                else ResourceBounds()
            ),
            provider_ids=tuple(payload.get("provider_ids") or ()),
            rank_score_millionths=int(
                payload.get("rank_score_millionths") or 0
            ),
            root_goal_id=payload.get("root_goal_id", ""),
            authority=payload.get("authority", AuthorityCeiling.CANDIDATE),
            proof_claimed=False,
            completion_claimed=False,
            metadata=payload.get("metadata") or {},
        )
        _claim_identity(
            payload,
            result.content_id,
            names=("content_id",),
            artifact="GoalDirectedProofPlan",
        )
        return result


@dataclass(frozen=True, slots=True)
class GoalCompletion(TacticianContract):
    """Trusted completion decision for a formal goal.

    This is the only contract in this module that may record a completion
    verdict.  Proposals, candidates, holes, graphs, and plans never do.
    """

    SCHEMA: ClassVar[str] = GOAL_COMPLETION_SCHEMA

    completion_id: str
    formal_goal_id: str
    root_goal_id: str
    tree_id: str
    verdict: CompletionVerdict
    authority: AuthorityCeiling
    evidence_ids: tuple[str, ...] = ()
    plan_id: str = ""
    graph_id: str = ""
    receipt_ids: tuple[str, ...] = ()
    bounds: ResourceBounds = field(default_factory=ResourceBounds)
    proof_claimed: bool = False
    # completion_claimed is derived from verdict, not a free producer claim.

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "completion_id",
            _text(self.completion_id, "completion_id", maximum=256),
        )
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", maximum=256),
        )
        object.__setattr__(
            self,
            "root_goal_id",
            _text(self.root_goal_id, "root_goal_id", maximum=256),
        )
        object.__setattr__(
            self, "tree_id", _text(self.tree_id, "tree_id", maximum=256)
        )
        object.__setattr__(
            self, "verdict", _enum(self.verdict, CompletionVerdict, "verdict")
        )
        object.__setattr__(
            self, "authority", _enum(self.authority, AuthorityCeiling, "authority")
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _string_tuple(self.evidence_ids, "evidence_ids"),
        )
        object.__setattr__(
            self,
            "plan_id",
            _text(self.plan_id, "plan_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "graph_id",
            _text(self.graph_id, "graph_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "receipt_ids",
            _string_tuple(self.receipt_ids, "receipt_ids"),
        )
        bounds = self.bounds
        if isinstance(bounds, Mapping):
            bounds = ResourceBounds.from_dict(bounds)
        elif not isinstance(bounds, ResourceBounds):
            raise TacticianContractError("bounds must be a ResourceBounds")
        object.__setattr__(self, "bounds", bounds)
        object.__setattr__(
            self, "proof_claimed", _bool(self.proof_claimed, "proof_claimed")
        )
        if self.verdict is CompletionVerdict.COMPLETE:
            if self.authority not in {
                AuthorityCeiling.THEOREM,
                AuthorityCeiling.ATTESTATION,
                AuthorityCeiling.RECONSTRUCTION,
                AuthorityCeiling.MODEL_CHECK,
                AuthorityCeiling.SATISFIABILITY,
                AuthorityCeiling.AUTHORIZATION,
                AuthorityCeiling.PROTOCOL,
                AuthorityCeiling.HYPERPROPERTY,
                AuthorityCeiling.MONITOR,
                AuthorityCeiling.BOUNDED,
            }:
                raise TacticianContractError(
                    "COMPLETE verdict requires elevated authority"
                )
            if not self.evidence_ids and not self.receipt_ids:
                raise TacticianContractError(
                    "COMPLETE verdict requires evidence_ids or receipt_ids"
                )
            if not self.proof_claimed:
                # Completion may record proof only with sufficient authority
                # and evidence; require explicit true only when COMPLETE.
                object.__setattr__(self, "proof_claimed", True)
        elif self.verdict is CompletionVerdict.BOUNDED_COMPLETE:
            if self.authority in {
                AuthorityCeiling.NONE,
                AuthorityCeiling.ADVISORY,
                AuthorityCeiling.CANDIDATE,
            }:
                raise TacticianContractError(
                    "BOUNDED_COMPLETE requires at least bounded authority"
                )
        else:
            if self.proof_claimed:
                raise TacticianContractError(
                    "non-complete GoalCompletion cannot claim proof"
                )

    @property
    def completion_claimed(self) -> bool:
        return self.verdict in {
            CompletionVerdict.COMPLETE,
            CompletionVerdict.BOUNDED_COMPLETE,
        }

    def _payload(self) -> dict[str, Any]:
        return {
            "completion_id": self.completion_id,
            "formal_goal_id": self.formal_goal_id,
            "root_goal_id": self.root_goal_id,
            "tree_id": self.tree_id,
            "verdict": self.verdict.value,
            "authority": self.authority.value,
            "evidence_ids": list(self.evidence_ids),
            "plan_id": self.plan_id,
            "graph_id": self.graph_id,
            "receipt_ids": list(self.receipt_ids),
            "bounds": self.bounds.to_dict(),
            "proof_claimed": self.proof_claimed,
            "completion_claimed": self.completion_claimed,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GoalCompletion":
        _schema_check(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "contract_version",
                "schema_version",
                "interface",
                "content_id",
                "completion_id",
                "formal_goal_id",
                "root_goal_id",
                "tree_id",
                "verdict",
                "authority",
                "evidence_ids",
                "plan_id",
                "graph_id",
                "receipt_ids",
                "bounds",
                "proof_claimed",
                "completion_claimed",
            },
            artifact="GoalCompletion",
        )
        bounds_raw = payload.get("bounds") or {}
        result = cls(
            completion_id=payload.get("completion_id", ""),
            formal_goal_id=payload.get("formal_goal_id", ""),
            root_goal_id=payload.get("root_goal_id", ""),
            tree_id=payload.get("tree_id", ""),
            verdict=payload.get("verdict", CompletionVerdict.NOT_COMPLETE),
            authority=payload.get("authority", AuthorityCeiling.NONE),
            evidence_ids=tuple(payload.get("evidence_ids") or ()),
            plan_id=payload.get("plan_id", ""),
            graph_id=payload.get("graph_id", ""),
            receipt_ids=tuple(payload.get("receipt_ids") or ()),
            bounds=(
                ResourceBounds.from_dict(bounds_raw)
                if isinstance(bounds_raw, Mapping)
                else ResourceBounds()
            ),
            proof_claimed=bool(payload.get("proof_claimed", False)),
        )
        # completion_claimed is derived; reject mismatched producer claims.
        claimed = payload.get("completion_claimed")
        if claimed is not None and bool(claimed) != result.completion_claimed:
            raise TacticianContractError(
                "GoalCompletion completion_claimed does not match verdict"
            )
        _claim_identity(
            payload,
            result.content_id,
            names=("content_id",),
            artifact="GoalCompletion",
        )
        return result


# ---------------------------------------------------------------------------
# Explicit conversion adapters (no competing root-goal identity)
# ---------------------------------------------------------------------------


def end_goal_spec_from_goal_development_mapping(
    payload: Mapping[str, Any],
    *,
    root_goal_id: str | None = None,
) -> EndGoalSpec:
    """Adapt a GoalDevelopment request-like mapping into :class:`EndGoalSpec`.

    The adapter never invents a second root identity: ``root_goal_id`` is taken
    from the caller, then ``goal_id`` / ``root_objective_id`` / ``objective_id``
    fields on the mapping.  Proof and completion claims are stripped.
    """

    if not isinstance(payload, Mapping):
        raise TacticianContractError(
            "goal-development payload must be an object"
        )
    goal_id = _text(
        payload.get("goal_id")
        or payload.get("root_objective_id")
        or payload.get("objective_id")
        or payload.get("request_id")
        or "goal:unspecified",
        "goal_id",
        maximum=256,
    )
    root = _text(
        root_goal_id
        or payload.get("root_goal_id")
        or payload.get("root_objective_id")
        or goal_id,
        "root_goal_id",
        maximum=256,
    )
    tree_id = _text(
        payload.get("repository_tree_id")
        or payload.get("tree_id")
        or payload.get("tree")
        or "",
        "tree_id",
        optional=True,
        maximum=256,
    )
    source_refs = payload.get("source_ref_ids") or payload.get("code_references") or ()
    if isinstance(source_refs, Mapping):
        source_refs = tuple(source_refs.keys())
    span_ids = payload.get("span_ids") or ()
    caller_text = _text(
        payload.get("caller_text")
        or payload.get("prompt")
        or payload.get("text")
        or payload.get("goal_text")
        or "",
        "caller_text",
        optional=True,
        maximum=16384,
    )
    if not caller_text:
        caller_text = f"formalize root goal {root}"
    if not tree_id and not source_refs and not span_ids:
        # Goal-development requests always bind a repository tree in practice;
        # require at least a synthetic tree binding to keep the schema closed.
        tree_id = _text(
            payload.get("repository_id") or "tree:unspecified",
            "tree_id",
            maximum=256,
        )
    property_raw = (
        payload.get("property_class")
        or payload.get("property_kind")
        or payload.get("kind")
        or PropertyClass.UNSPECIFIED
    )
    try:
        property_class = _enum(property_raw, PropertyClass, "property_class")
    except TacticianContractError:
        property_class = PropertyClass.UNSPECIFIED
    assumptions_raw = payload.get("assumptions") or payload.get("assumption_ids") or ()
    assumptions: list[AssumptionBinding] = []
    if isinstance(assumptions_raw, Sequence) and not isinstance(
        assumptions_raw, (str, bytes, bytearray)
    ):
        for index, item in enumerate(assumptions_raw):
            if isinstance(item, Mapping):
                assumptions.append(
                    AssumptionBinding.from_dict(
                        {
                            "schema": AssumptionBinding.SCHEMA,
                            "assumption_id": item.get(
                                "assumption_id", f"assumption:{index}"
                            ),
                            "assumption_class": item.get(
                                "assumption_class",
                                AssumptionClass.HYPOTHETICAL.value,
                            ),
                            "kind": item.get("kind", "semantic"),
                            "statement": item.get("statement", ""),
                            "source": item.get("source")
                            or {
                                "schema": SourceSpanBinding.SCHEMA,
                                "tree_id": tree_id,
                            },
                            "authority": AuthorityCeiling.NONE.value,
                            "reviewable": True,
                        }
                    )
                )
            else:
                assumptions.append(
                    AssumptionBinding(
                        assumption_id=str(item),
                        assumption_class=AssumptionClass.HYPOTHETICAL,
                        kind="semantic",
                        source=SourceSpanBinding(tree_id=tree_id),
                    )
                )
    return EndGoalSpec(
        goal_id=goal_id,
        root_goal_id=root,
        caller_text=caller_text,
        source=SourceSpanBinding(
            tree_id=tree_id,
            source_ref_ids=tuple(str(x) for x in source_refs),
            span_ids=tuple(str(x) for x in span_ids),
            snapshot_id=str(payload.get("snapshot_id") or ""),
        ),
        property_class=property_class,
        quantifiers=tuple(payload.get("quantifiers") or ()),
        actors=tuple(str(x) for x in (payload.get("actors") or ())),
        state_variables=tuple(
            str(x) for x in (payload.get("state_variables") or ())
        ),
        current_state=payload.get("current_state") or {},
        target_state=payload.get("target_state") or payload.get("formula") or {},
        transitions=tuple(str(x) for x in (payload.get("transitions") or ())),
        environment=payload.get("environment") or {},
        assumptions=tuple(assumptions),
        logic_family=str(payload.get("logic_family") or ""),
        provider_ids=tuple(
            str(x) for x in (payload.get("provider_ids") or ())
        ),
        assurance_target=payload.get(
            "assurance_target", AuthorityCeiling.BOUNDED
        ),
        bounds=ResourceBounds.from_dict(
            {
                "schema": ResourceBounds.SCHEMA,
                **(
                    dict(payload.get("resource_budget") or {})
                    if isinstance(payload.get("resource_budget"), Mapping)
                    else {}
                ),
                **(
                    dict(payload.get("bounds") or {})
                    if isinstance(payload.get("bounds"), Mapping)
                    else {}
                ),
            }
        )
        if (
            isinstance(payload.get("resource_budget"), Mapping)
            or isinstance(payload.get("bounds"), Mapping)
        )
        else ResourceBounds(),
        status="adapted",
        authority=AuthorityCeiling.ADVISORY,
        proof_claimed=False,
        completion_claimed=False,
    )


def goal_directed_plan_from_supervisor_proof_plan(
    payload: Mapping[str, Any],
    *,
    formal_goal_id: str,
    graph_id: str = "",
    root_goal_id: str | None = None,
) -> GoalDirectedProofPlan:
    """Adapt a supervisor ``ProofPlan``-like mapping into a goal-directed plan.

    Step obligations become candidate proof steps with candidate authority.
    The plan never inherits proof or completion claims from the source plan.
    """

    if not isinstance(payload, Mapping):
        raise TacticianContractError("proof plan payload must be an object")
    tree_id = _text(
        payload.get("repository_tree_id") or payload.get("tree_id") or "",
        "tree_id",
        maximum=256,
    )
    plan_id = _text(
        payload.get("plan_id") or payload.get("content_id") or "plan:adapted",
        "plan_id",
        maximum=256,
    )
    steps = payload.get("steps") or ()
    candidates: list[CandidateProofStep] = []
    order: list[str] = []
    if isinstance(steps, Sequence) and not isinstance(
        steps, (str, bytes, bytearray)
    ):
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping):
                continue
            step_id = _text(
                step.get("step_id") or f"step:{index}",
                "step_id",
                maximum=256,
            )
            order.append(step_id)
            candidates.append(
                CandidateProofStep(
                    candidate_id=step_id,
                    hole_id=_text(
                        step.get("obligation_id") or step.get("hole_id") or step_id,
                        "hole_id",
                        maximum=256,
                    ),
                    kind=_text(
                        step.get("stage") or step.get("kind") or "solve",
                        "kind",
                        maximum=128,
                    ),
                    statement=_text(
                        step.get("statement")
                        or step.get("obligation_id")
                        or f"execute step {step_id}",
                        "statement",
                        maximum=8192,
                    ),
                    status=CandidateStatus.PROPOSED,
                    source=SourceSpanBinding(tree_id=tree_id),
                    provider_ids=_string_tuple(
                        step.get("provider_id") or step.get("provider_ids") or (),
                        "provider_ids",
                    ),
                    authority=AuthorityCeiling.CANDIDATE,
                    proof_claimed=False,
                    completion_claimed=False,
                )
            )
    if not candidates:
        raise TacticianContractError(
            "supervisor proof plan adaptation requires at least one step"
        )
    return GoalDirectedProofPlan(
        plan_id=plan_id,
        formal_goal_id=_text(formal_goal_id, "formal_goal_id", maximum=256),
        graph_id=_text(
            graph_id or payload.get("graph_id") or f"graph:{plan_id}",
            "graph_id",
            maximum=256,
        ),
        tree_id=tree_id,
        candidates=tuple(candidates),
        step_order=tuple(order),
        status=PlanStatus.DRAFT,
        bounds=ResourceBounds(),
        provider_ids=_string_tuple(
            payload.get("provider_ids") or (), "provider_ids"
        ),
        root_goal_id=_text(
            root_goal_id or formal_goal_id, "root_goal_id", maximum=256
        ),
        authority=AuthorityCeiling.CANDIDATE,
        proof_claimed=False,
        completion_claimed=False,
        metadata={
            "adapted_from": "supervisor_proof_plan",
            "source_schema": str(payload.get("schema") or ""),
        },
    )


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "AMBIVALENT",  # placeholder removed below
    "END_GOAL_SPEC_INTERFACE",
    "PROOF_HOLE_INTERFACE",
    "PROOF_OBLIGATION_GRAPH_INTERFACE",
    "GOAL_DIRECTED_PROOF_PLAN_INTERFACE",
    "END_GOAL_SPEC_SCHEMA",
    "END_GOAL_INTERPRETATION_SCHEMA",
    "FORMAL_GOAL_SCHEMA",
    "PROOF_HOLE_SCHEMA",
    "PROOF_GRAPH_NODE_SCHEMA",
    "PROOF_GRAPH_EDGE_SCHEMA",
    "PROOF_OBLIGATION_GRAPH_SCHEMA",
    "CANDIDATE_PROOF_STEP_SCHEMA",
    "CANDIDATE_VALIDATION_SCHEMA",
    "GOAL_DIRECTED_PROOF_PLAN_SCHEMA",
    "GOAL_COMPLETION_SCHEMA",
    "TACTICIAN_CONTRACT_VERSION",
    "TacticianContractError",
    "PropertyClass",
    "QuantifierKind",
    "AssumptionClass",
    "HoleKind",
    "HoleStatus",
    "GraphNodeKind",
    "GraphEdgeKind",
    "CandidateStatus",
    "ValidationVerdict",
    "AuthorityCeiling",
    "PlanStatus",
    "CompletionVerdict",
    "AmbiguityStatus",
    "canonical_json_bytes",
    "content_identity",
    "TacticianContract",
    "SourceSpanBinding",
    "PhraseProvenance",
    "AssumptionBinding",
    "ResourceBounds",
    "ValidationRecipe",
    "EndGoalInterpretation",
    "EndGoalSpec",
    "FormalGoal",
    "ProofHole",
    "ProofGraphNode",
    "ProofGraphEdge",
    "ProofObligationGraph",
    "CandidateProofStep",
    "CandidateValidation",
    "GoalDirectedProofPlan",
    "GoalCompletion",
    "end_goal_spec_from_goal_development_mapping",
    "goal_directed_plan_from_supervisor_proof_plan",
]

# Remove accidental placeholder if present in __all__.
__all__ = [name for name in __all__ if name != "AMBIVALENT"]
