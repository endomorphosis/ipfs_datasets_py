"""Canonical, source-grounded Intent IR schema.

Intent IR models what a skill is trying to accomplish and the procedure it
describes.  It does not authorize or execute the procedure.  Raw source bodies,
GraphRAG indexes, embeddings, model responses, and proof artifacts live in
separate content-addressed artifacts and are joined through identifiers.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from ..ir_core.canonical import CollectionSchema, CollectionSemantics


INTENT_IR_SCHEMA_VERSION = "intent-ir/v1"
LEGACY_INTENT_IR_SCHEMA_VERSION = "intent-ir/v0.1"
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Datasets-owned direct-objective submission identity (DOEP-010).  Parallel to
# IntentIRDocument: describes one bounded high-level idea without authorizing
# execution, admitting policy, or completing objectives.
SUPERVISOR_OBJECTIVE_INTENT_SCHEMA = (
    "ipfs_datasets_py/logic/intent-ir/supervisor-objective-intent@1"
)
SUPERVISOR_OBJECTIVE_INTENT_SCHEMA_VERSION = "supervisor-objective-intent/v1"
SUPERVISOR_OBJECTIVE_INTENT_MAX_IDEA_UTF8_BYTES = 16384
SUPERVISOR_OBJECTIVE_INTENT_MAX_TAGS = 32
SUPERVISOR_OBJECTIVE_INTENT_FORBIDDEN_FIELDS = frozenset(
    {
        "authorization",
        "authorization_decision",
        "budget_profile",
        "budgets",
        "completion_authoritative",
        "dry_run",
        "ducklake",
        "effect_claims",
        "expected_effects",
        "fencing_epoch",
        "fencing_generation",
        "formal_plan",
        "goal_cids",
        "lease_id",
        "objective_cid",
        "objective_revision_cid",
        "partial_order",
        "plan",
        "plan_root_cid",
        "policy",
        "policy_document",
        "policy_id",
        "policy_revision",
        "quack_mutation",
        "risk_class",
        "task_cids",
        "terminalize",
    }
)

# Datasets-owned semantic materialization identity (DOEP-011).  A receipt
# records the immutable relationship between an accepted direct-objective
# intent and its semantic objective references.  It is evidence only: the
# operational service owns admission and execution, while Kit owns durable
# bytes and CID storage.
OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA = (
    "ipfs_datasets_py/logic/intent-ir/objective-materialization-receipt@1"
)
OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA_VERSION = "objective-materialization-receipt/v1"
OBJECTIVE_MATERIALIZATION_RECEIPT_FORBIDDEN_FIELDS = frozenset(
    {
        "authorization",
        "authorization_decision",
        "budget_profile",
        "budgets",
        "completion_authoritative",
        "duckdb",
        "ducklake",
        "execution_authorization",
        "fencing_epoch",
        "fencing_generation",
        "lease_id",
        "plan",
        "plan_root_cid",
        "policy",
        "policy_document",
        "policy_id",
        "policy_revision",
        "quack_mutation",
        "storage_authorization",
        "task_cids",
        "terminalize",
    }
)


class IntentIRValidationError(ValueError):
    """Raised when an Intent IR document violates its canonical contract."""


class ReviewStatus(str, Enum):
    """Human/machine review state; never infer trust from source popularity."""

    UNREVIEWED = "unreviewed"
    MACHINE_EXTRACTED = "machine_extracted"
    HUMAN_REVIEWED = "human_reviewed"
    TRUSTED_FIXTURE = "trusted_fixture"
    QUARANTINED = "quarantined"


class IntentKind(str, Enum):
    """Top-level semantic shape of an intent document."""

    PROCEDURE = "procedure"
    CAPABILITY = "capability"
    POLICY = "policy"
    DECLARATIVE = "declarative"


class IntentModality(str, Enum):
    """Force attached to a normalized statement."""

    ASSERTED = "asserted"
    INTENDED = "intended"
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    PERMITTED = "permitted"
    PROHIBITED = "prohibited"


class StatementKind(str, Enum):
    """Role of a normalized statement in the action contract."""

    GOAL = "goal"
    PRECONDITION = "precondition"
    POSTCONDITION = "postcondition"
    INVARIANT = "invariant"
    GUARD = "guard"
    EFFECT = "effect"
    ASSUMPTION = "assumption"
    FAILURE = "failure"
    VERIFICATION = "verification"


class ControlEdgeKind(str, Enum):
    """Control-flow relationship between two actions."""

    NEXT = "next"
    ON_SUCCESS = "on_success"
    ON_FAILURE = "on_failure"
    CONDITIONAL = "conditional"
    RETRY = "retry"
    PARALLEL = "parallel"
    JOIN = "join"


class NodeGrounding(str, Enum):
    """Whether a semantic node is stated by evidence or derived from it."""

    GROUNDED = "grounded"
    INFERRED = "inferred"


# Alias retained for callers that describe this dimension as a "kind".
GroundingKind = NodeGrounding


# Every collection in the v1 wire contract has declared semantics.  Set-like
# collections are unique and canonicalized by value or stable node identifier;
# ordered collections retain their input order and may contain repeated values.
INTENT_IR_COLLECTION_SEMANTICS: Mapping[str, CollectionSemantics] = MappingProxyType(
    {
        "IntentIRDocument.sources": CollectionSemantics.SET_LIKE,
        "IntentIRDocument.statements": CollectionSemantics.SET_LIKE,
        "IntentIRDocument.actions": CollectionSemantics.SET_LIKE,
        "IntentIRDocument.control_edges": CollectionSemantics.SET_LIKE,
        "IntentIRDocument.entry_action_ids": CollectionSemantics.SET_LIKE,
        "IntentIRDocument.terminal_action_ids": CollectionSemantics.SET_LIKE,
        "IntentIRDocument.tags": CollectionSemantics.SET_LIKE,
        "IntentStatement.arguments": CollectionSemantics.ORDERED,
        "IntentStatement.source_ref_ids": CollectionSemantics.SET_LIKE,
        "IntentAction.object_refs": CollectionSemantics.SET_LIKE,
        "IntentAction.source_ref_ids": CollectionSemantics.SET_LIKE,
        "IntentAction.tool_refs": CollectionSemantics.SET_LIKE,
        "IntentAction.input_refs": CollectionSemantics.SET_LIKE,
        "IntentAction.output_refs": CollectionSemantics.SET_LIKE,
        "IntentAction.precondition_ids": CollectionSemantics.SET_LIKE,
        "IntentAction.effect_ids": CollectionSemantics.SET_LIKE,
        "IntentAction.verification_ids": CollectionSemantics.SET_LIKE,
        "IntentControlEdge.source_ref_ids": CollectionSemantics.SET_LIKE,
    }
)

# Machine-consumable JSON-pointer rules for the shared canonical identity
# profile.  Wildcards cover each node in the set-like top-level collections.
INTENT_IR_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/sources": CollectionSemantics.SET_LIKE,
        "/statements": CollectionSemantics.SET_LIKE,
        "/statements/*/arguments": CollectionSemantics.ORDERED,
        "/statements/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/actions": CollectionSemantics.SET_LIKE,
        "/actions/*/object_refs": CollectionSemantics.SET_LIKE,
        "/actions/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/actions/*/tool_refs": CollectionSemantics.SET_LIKE,
        "/actions/*/input_refs": CollectionSemantics.SET_LIKE,
        "/actions/*/output_refs": CollectionSemantics.SET_LIKE,
        "/actions/*/precondition_ids": CollectionSemantics.SET_LIKE,
        "/actions/*/effect_ids": CollectionSemantics.SET_LIKE,
        "/actions/*/verification_ids": CollectionSemantics.SET_LIKE,
        "/control_edges": CollectionSemantics.SET_LIKE,
        "/control_edges/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/entry_action_ids": CollectionSemantics.SET_LIKE,
        "/terminal_action_ids": CollectionSemantics.SET_LIKE,
        "/tags": CollectionSemantics.SET_LIKE,
    },
    require_declared=True,
)


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Character span in a separately stored source artifact."""

    start_char: int
    end_char: int

    def validate(self) -> None:
        if isinstance(self.start_char, bool) or not isinstance(self.start_char, int):
            raise IntentIRValidationError("SourceSpan.start_char must be an integer")
        if isinstance(self.end_char, bool) or not isinstance(self.end_char, int):
            raise IntentIRValidationError("SourceSpan.end_char must be an integer")
        if self.start_char < 0 or self.end_char < self.start_char:
            raise IntentIRValidationError("SourceSpan must satisfy 0 <= start_char <= end_char")

    def to_dict(self) -> dict[str, int]:
        return {"end_char": self.end_char, "start_char": self.start_char}


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Immutable reference to evidence used by one Intent IR document.

    ``source_uri`` identifies the original source when available, while
    ``container_uri`` identifies the pinned corpus artifact that supplied the
    bytes.  ``content_sha256`` always binds the exact normalized source body.
    """

    ref_id: str
    source_uri: str
    source_id: str
    source_revision: str
    content_sha256: str
    container_uri: str = ""
    container_sha256: str = ""
    content_cid: str = ""
    license_expression: str = ""
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    span: SourceSpan | None = None

    def validate(self) -> None:
        _validate_identifier("SourceRef.ref_id", self.ref_id)
        _validate_enum("SourceRef.review_status", self.review_status, ReviewStatus)
        for name in ("source_uri", "source_id", "source_revision"):
            _validate_non_empty_string(f"SourceRef.{name}", getattr(self, name))
        for name in (
            "container_uri",
            "content_cid",
            "license_expression",
        ):
            _validate_string(f"SourceRef.{name}", getattr(self, name))
        _validate_sha256("SourceRef.content_sha256", self.content_sha256)
        _validate_string("SourceRef.container_sha256", self.container_sha256)
        if self.container_sha256:
            _validate_sha256("SourceRef.container_sha256", self.container_sha256)
        if self.span is not None and not isinstance(self.span, SourceSpan):
            raise IntentIRValidationError("SourceRef.span must be a SourceSpan or None")
        if self.span is not None:
            self.span.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "container_sha256": self.container_sha256,
            "container_uri": self.container_uri,
            "content_cid": self.content_cid,
            "content_sha256": self.content_sha256,
            "license_expression": self.license_expression,
            "ref_id": self.ref_id,
            "review_status": self.review_status.value,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "source_uri": self.source_uri,
            "span": self.span.to_dict() if self.span else None,
        }


@dataclass(frozen=True, slots=True)
class IntentStatement:
    """One normalized, source-grounded semantic statement."""

    statement_id: str
    kind: StatementKind
    modality: IntentModality
    normalized_text: str
    source_ref_ids: tuple[str, ...]
    predicate: str = ""
    arguments: tuple[str, ...] = ()
    confidence: float = 1.0
    review_status: ReviewStatus = ReviewStatus.MACHINE_EXTRACTED
    grounding: NodeGrounding = NodeGrounding.GROUNDED

    def validate(self) -> None:
        _validate_identifier("IntentStatement.statement_id", self.statement_id)
        _validate_enum("IntentStatement.kind", self.kind, StatementKind)
        _validate_enum("IntentStatement.modality", self.modality, IntentModality)
        _validate_enum("IntentStatement.review_status", self.review_status, ReviewStatus)
        _validate_enum("IntentStatement.grounding", self.grounding, NodeGrounding)
        _validate_non_empty_string(
            f"IntentStatement {self.statement_id!r}.normalized_text",
            self.normalized_text,
        )
        if self.grounding is NodeGrounding.GROUNDED and not self.source_ref_ids:
            raise IntentIRValidationError(
                f"Grounded IntentStatement {self.statement_id!r} requires source_ref_ids"
            )
        _validate_confidence(f"IntentStatement {self.statement_id!r}.confidence", self.confidence)
        _validate_string(f"IntentStatement {self.statement_id!r}.predicate", self.predicate)
        if self.predicate and not _IDENTIFIER_RE.fullmatch(self.predicate):
            raise IntentIRValidationError(
                f"IntentStatement {self.statement_id!r}.predicate is not a stable identifier"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "arguments": list(self.arguments),
            "confidence": self.confidence,
            "grounding": self.grounding.value,
            "kind": self.kind.value,
            "modality": self.modality.value,
            "normalized_text": self.normalized_text,
            "predicate": self.predicate,
            "review_status": self.review_status.value,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "statement_id": self.statement_id,
        }


@dataclass(frozen=True, slots=True)
class IntentAction:
    """One action node in an intent procedure."""

    action_id: str
    actor: str
    verb: str
    object_refs: tuple[str, ...]
    source_ref_ids: tuple[str, ...]
    tool_refs: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    precondition_ids: tuple[str, ...] = ()
    effect_ids: tuple[str, ...] = ()
    verification_ids: tuple[str, ...] = ()
    grounding: NodeGrounding = NodeGrounding.GROUNDED

    def validate(self) -> None:
        _validate_identifier("IntentAction.action_id", self.action_id)
        _validate_enum("IntentAction.grounding", self.grounding, NodeGrounding)
        _validate_non_empty_string(f"IntentAction {self.action_id!r}.actor", self.actor)
        _validate_non_empty_string(f"IntentAction {self.action_id!r}.verb", self.verb)
        if self.grounding is NodeGrounding.GROUNDED and not self.source_ref_ids:
            raise IntentIRValidationError(
                f"Grounded IntentAction {self.action_id!r} requires source_ref_ids"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "actor": self.actor,
            "effect_ids": sorted(set(self.effect_ids)),
            "grounding": self.grounding.value,
            "input_refs": sorted(set(self.input_refs)),
            "object_refs": sorted(set(self.object_refs)),
            "output_refs": sorted(set(self.output_refs)),
            "precondition_ids": sorted(set(self.precondition_ids)),
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "tool_refs": sorted(set(self.tool_refs)),
            "verb": self.verb,
            "verification_ids": sorted(set(self.verification_ids)),
        }


@dataclass(frozen=True, slots=True)
class IntentControlEdge:
    """Directed control-flow edge between action nodes."""

    edge_id: str
    source_action_id: str
    target_action_id: str
    kind: ControlEdgeKind = ControlEdgeKind.NEXT
    guard_statement_id: str = ""
    source_ref_ids: tuple[str, ...] = ()
    grounding: NodeGrounding = NodeGrounding.GROUNDED

    def validate(self) -> None:
        _validate_identifier("IntentControlEdge.edge_id", self.edge_id)
        _validate_enum("IntentControlEdge.kind", self.kind, ControlEdgeKind)
        _validate_enum("IntentControlEdge.grounding", self.grounding, NodeGrounding)
        _validate_identifier("IntentControlEdge.source_action_id", self.source_action_id)
        _validate_identifier("IntentControlEdge.target_action_id", self.target_action_id)
        _validate_string("IntentControlEdge.guard_statement_id", self.guard_statement_id)
        if self.guard_statement_id:
            _validate_identifier(
                "IntentControlEdge.guard_statement_id",
                self.guard_statement_id,
            )
        if (
            self.source_action_id == self.target_action_id
            and self.kind is not ControlEdgeKind.RETRY
        ):
            raise IntentIRValidationError(
                f"IntentControlEdge {self.edge_id!r} self-cycle must be a retry"
            )
        if self.grounding is NodeGrounding.GROUNDED and not self.source_ref_ids:
            raise IntentIRValidationError(
                f"Grounded IntentControlEdge {self.edge_id!r} requires source_ref_ids"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "guard_statement_id": self.guard_statement_id,
            "grounding": self.grounding.value,
            "kind": self.kind.value,
            "source_action_id": self.source_action_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "target_action_id": self.target_action_id,
        }


@dataclass(frozen=True, slots=True)
class IntentIRDocument:
    """Canonical semantic IR for one skill or source-grounded intent."""

    document_id: str
    title: str
    intent_kind: IntentKind
    sources: tuple[SourceRef, ...]
    statements: tuple[IntentStatement, ...]
    actions: tuple[IntentAction, ...] = ()
    control_edges: tuple[IntentControlEdge, ...] = ()
    entry_action_ids: tuple[str, ...] = ()
    terminal_action_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    schema_version: str = INTENT_IR_SCHEMA_VERSION

    def validate(self) -> None:
        validate_intent_ir(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [
                item.to_dict() for item in sorted(self.actions, key=lambda item: item.action_id)
            ],
            "control_edges": [
                item.to_dict() for item in sorted(self.control_edges, key=lambda item: item.edge_id)
            ],
            "document_id": self.document_id,
            "entry_action_ids": sorted(set(self.entry_action_ids)),
            "intent_kind": self.intent_kind.value,
            "schema_version": self.schema_version,
            "sources": [
                item.to_dict() for item in sorted(self.sources, key=lambda item: item.ref_id)
            ],
            "statements": [
                item.to_dict()
                for item in sorted(self.statements, key=lambda item: item.statement_id)
            ],
            "tags": sorted(set(self.tags)),
            "terminal_action_ids": sorted(set(self.terminal_action_ids)),
            "title": self.title,
        }


def validate_intent_ir(
    document: IntentIRDocument | Mapping[str, Any],
) -> IntentIRDocument:
    """Validate and return an :class:`IntentIRDocument`.

    Mappings must pass through :mod:`intent_ir.decoder`; accepting them here
    would let untrusted JSON bypass exact field and type validation.
    """

    if not isinstance(document, IntentIRDocument):
        raise IntentIRValidationError("Intent IR mappings require an explicit versioned decoder")
    if document.schema_version != INTENT_IR_SCHEMA_VERSION:
        raise IntentIRValidationError(
            f"Unsupported Intent IR schema_version: {document.schema_version!r}"
        )
    _validate_identifier("IntentIRDocument.document_id", document.document_id)
    _validate_enum("IntentIRDocument.intent_kind", document.intent_kind, IntentKind)
    _validate_non_empty_string("IntentIRDocument.title", document.title)
    if not document.sources:
        raise IntentIRValidationError("IntentIRDocument.sources must not be empty")
    if not document.statements:
        raise IntentIRValidationError("IntentIRDocument.statements must not be empty")

    _validate_record_collection("IntentIRDocument.sources", document.sources, SourceRef)
    _validate_record_collection("IntentIRDocument.statements", document.statements, IntentStatement)
    _validate_record_collection("IntentIRDocument.actions", document.actions, IntentAction)
    _validate_record_collection(
        "IntentIRDocument.control_edges",
        document.control_edges,
        IntentControlEdge,
    )
    _require_unique((item.ref_id for item in document.sources), "source ref")
    _require_unique((item.statement_id for item in document.statements), "statement")
    _require_unique((item.action_id for item in document.actions), "action")
    _require_unique((item.edge_id for item in document.control_edges), "control edge")
    _validate_document_collections(document)

    for source in document.sources:
        source.validate()
    for statement in document.statements:
        statement.validate()
    for action in document.actions:
        action.validate()
    for edge in document.control_edges:
        edge.validate()

    source_ids = {item.ref_id for item in document.sources}
    statements = {item.statement_id: item for item in document.statements}
    action_ids = {item.action_id for item in document.actions}

    for statement in document.statements:
        _require_known_refs(
            statement.source_ref_ids,
            source_ids,
            f"IntentStatement {statement.statement_id!r}.source_ref_ids",
        )
    for action in document.actions:
        _require_known_refs(
            action.source_ref_ids,
            source_ids,
            f"IntentAction {action.action_id!r}.source_ref_ids",
        )
        _require_statement_kinds(
            action.precondition_ids,
            statements,
            {StatementKind.PRECONDITION, StatementKind.GUARD, StatementKind.ASSUMPTION},
            f"IntentAction {action.action_id!r}.precondition_ids",
        )
        _require_statement_kinds(
            action.effect_ids,
            statements,
            {StatementKind.EFFECT, StatementKind.POSTCONDITION},
            f"IntentAction {action.action_id!r}.effect_ids",
        )
        _require_statement_kinds(
            action.verification_ids,
            statements,
            {StatementKind.VERIFICATION, StatementKind.INVARIANT},
            f"IntentAction {action.action_id!r}.verification_ids",
        )
    for edge in document.control_edges:
        _require_known_refs(
            (edge.source_action_id, edge.target_action_id),
            action_ids,
            f"IntentControlEdge {edge.edge_id!r}",
        )
        _require_known_refs(
            edge.source_ref_ids,
            source_ids,
            f"IntentControlEdge {edge.edge_id!r}.source_ref_ids",
        )
        if edge.guard_statement_id:
            _require_statement_kinds(
                (edge.guard_statement_id,),
                statements,
                {StatementKind.GUARD, StatementKind.PRECONDITION},
                f"IntentControlEdge {edge.edge_id!r}.guard_statement_id",
            )

    _require_known_refs(
        document.entry_action_ids,
        action_ids,
        "IntentIRDocument.entry_action_ids",
    )
    _require_known_refs(
        document.terminal_action_ids,
        action_ids,
        "IntentIRDocument.terminal_action_ids",
    )
    if document.intent_kind is IntentKind.PROCEDURE:
        if not document.actions:
            raise IntentIRValidationError("Procedure Intent IR requires at least one action")
        if not document.entry_action_ids or not document.terminal_action_ids:
            raise IntentIRValidationError(
                "Procedure Intent IR requires entry_action_ids and terminal_action_ids"
            )
    if not any(statement.kind is StatementKind.GOAL for statement in document.statements):
        raise IntentIRValidationError("IntentIRDocument requires at least one goal statement")
    return document


def _validate_document_collections(document: IntentIRDocument) -> None:
    """Enforce the immutable and declared collection contract."""

    _require_tuple("IntentIRDocument.sources", document.sources)
    _require_tuple("IntentIRDocument.statements", document.statements)
    _require_tuple("IntentIRDocument.actions", document.actions)
    _require_tuple("IntentIRDocument.control_edges", document.control_edges)

    set_collections: tuple[tuple[str, tuple[Any, ...]], ...] = (
        ("IntentIRDocument.entry_action_ids", document.entry_action_ids),
        ("IntentIRDocument.terminal_action_ids", document.terminal_action_ids),
        ("IntentIRDocument.tags", document.tags),
    )
    for statement in document.statements:
        _require_tuple(
            f"IntentStatement {statement.statement_id!r}.arguments",
            statement.arguments,
        )
        _validate_string_items(
            f"IntentStatement {statement.statement_id!r}.arguments",
            statement.arguments,
        )
        set_collections += (
            (
                f"IntentStatement {statement.statement_id!r}.source_ref_ids",
                statement.source_ref_ids,
            ),
        )
    for action in document.actions:
        for field_name in (
            "object_refs",
            "source_ref_ids",
            "tool_refs",
            "input_refs",
            "output_refs",
            "precondition_ids",
            "effect_ids",
            "verification_ids",
        ):
            set_collections += (
                (
                    f"IntentAction {action.action_id!r}.{field_name}",
                    getattr(action, field_name),
                ),
            )
    for edge in document.control_edges:
        set_collections += (
            (
                f"IntentControlEdge {edge.edge_id!r}.source_ref_ids",
                edge.source_ref_ids,
            ),
        )

    for name, values in set_collections:
        _require_tuple(name, values)
        _validate_string_items(name, values)
        _require_unique(values, f"{name} member")


def _validate_record_collection(name: str, value: Any, item_type: type[Any]) -> None:
    _require_tuple(name, value)
    for index, item in enumerate(value):
        if not isinstance(item, item_type):
            raise IntentIRValidationError(f"{name}[{index}] must be a {item_type.__name__}")


def _validate_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise IntentIRValidationError(f"{name} is not a stable identifier")


def _validate_string(name: str, value: Any) -> None:
    if not isinstance(value, str):
        raise IntentIRValidationError(f"{name} must be a string")


def _validate_non_empty_string(name: str, value: Any) -> None:
    _validate_string(name, value)
    if not value.strip():
        raise IntentIRValidationError(f"{name} must not be empty")


def _validate_string_items(name: str, values: Iterable[Any]) -> None:
    for index, value in enumerate(values):
        _validate_non_empty_string(f"{name}[{index}]", value)


def _require_tuple(name: str, value: Any) -> None:
    if not isinstance(value, tuple):
        raise IntentIRValidationError(
            f"{name} must be an immutable tuple with "
            f"{INTENT_IR_COLLECTION_SEMANTICS.get(name, 'declared')} semantics"
        )


def _validate_sha256(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise IntentIRValidationError(f"{name} must be a lowercase 64-character SHA-256")


def _validate_enum(name: str, value: Any, enum_type: type[Enum]) -> None:
    if not isinstance(value, enum_type):
        raise IntentIRValidationError(f"{name} must be a {enum_type.__name__} value")


def _validate_confidence(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IntentIRValidationError(f"{name} must be numeric")
    if not 0.0 <= float(value) <= 1.0:
        raise IntentIRValidationError(f"{name} must be between 0 and 1")


def _require_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise IntentIRValidationError(f"Duplicate {label} id: {value}")
        seen.add(value)


def _require_known_refs(values: Iterable[str], known: set[str], label: str) -> None:
    missing = sorted({value for value in values if value not in known})
    if missing:
        raise IntentIRValidationError(f"{label} references unknown ids: {', '.join(missing)}")


def _require_statement_kinds(
    values: Iterable[str],
    statements: Mapping[str, IntentStatement],
    allowed: set[StatementKind],
    label: str,
) -> None:
    _require_known_refs(values, set(statements), label)
    invalid = sorted(
        statement_id for statement_id in values if statements[statement_id].kind not in allowed
    )
    if invalid:
        allowed_values = ", ".join(sorted(item.value for item in allowed))
        raise IntentIRValidationError(
            f"{label} has incompatible statement kinds for {', '.join(invalid)}; "
            f"allowed: {allowed_values}"
        )


class SupervisorObjectiveSubmitterKind(str, Enum):
    """Who submitted the direct high-level objective idea."""

    HUMAN = "human"
    DELEGATED_AGENT = "delegated_agent"


@dataclass(frozen=True, slots=True)
class SupervisorObjectiveIntent:
    """Datasets-owned semantic contract for one direct objective submission.

    Parallel to :class:`IntentIRDocument` (skill-corpus IR).  This record binds
    a caller's bounded high-level idea and opaque identity hints.  It does not
    authorize execution, supply authoritative policy, open leases, compile
    plans, or complete objectives.  Accelerate admits and materializes it.
    """

    intent_id: str
    idea_text: str
    idea_sha256: str
    submitter_kind: SupervisorObjectiveSubmitterKind
    caller: str
    repository_id: str = ""
    board_namespace: str = ""
    title_hint: str = ""
    tags: tuple[str, ...] = ()
    schema_version: str = SUPERVISOR_OBJECTIVE_INTENT_SCHEMA_VERSION

    def validate(self) -> None:
        validate_supervisor_objective_intent(self)

    @property
    def schema(self) -> str:
        return SUPERVISOR_OBJECTIVE_INTENT_SCHEMA

    @property
    def callers_supply_authoritative_policy(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "board_namespace": self.board_namespace,
            "caller": self.caller,
            "idea_sha256": self.idea_sha256,
            "idea_text": self.idea_text,
            "intent_id": self.intent_id,
            "repository_id": self.repository_id,
            "schema": SUPERVISOR_OBJECTIVE_INTENT_SCHEMA,
            "schema_version": self.schema_version,
            "submitter_kind": self.submitter_kind.value,
            "tags": sorted(set(self.tags)),
            "title_hint": self.title_hint,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SupervisorObjectiveIntent":
        if not isinstance(value, Mapping):
            raise IntentIRValidationError(
                "SupervisorObjectiveIntent mapping must be a mapping"
            )
        unknown_forbidden = sorted(
            key for key in value if key in SUPERVISOR_OBJECTIVE_INTENT_FORBIDDEN_FIELDS
        )
        if unknown_forbidden:
            raise IntentIRValidationError(
                "SupervisorObjectiveIntent forbids authoritative fields: "
                + ", ".join(unknown_forbidden)
            )
        allowed = {
            "board_namespace",
            "caller",
            "idea_sha256",
            "idea_text",
            "intent_id",
            "repository_id",
            "schema",
            "schema_version",
            "submitter_kind",
            "tags",
            "title_hint",
        }
        unknown = sorted(key for key in value if key not in allowed)
        if unknown:
            raise IntentIRValidationError(
                "SupervisorObjectiveIntent has unknown fields: " + ", ".join(unknown)
            )
        schema = value.get("schema", SUPERVISOR_OBJECTIVE_INTENT_SCHEMA)
        if schema != SUPERVISOR_OBJECTIVE_INTENT_SCHEMA:
            raise IntentIRValidationError(
                f"Unsupported SupervisorObjectiveIntent schema: {schema!r}"
            )
        raw_kind = value.get("submitter_kind", "")
        try:
            submitter_kind = SupervisorObjectiveSubmitterKind(raw_kind)
        except ValueError as exc:
            raise IntentIRValidationError(
                f"SupervisorObjectiveIntent.submitter_kind is invalid: {raw_kind!r}"
            ) from exc
        tags_value = value.get("tags", ())
        if isinstance(tags_value, str) or not isinstance(tags_value, Iterable):
            raise IntentIRValidationError(
                "SupervisorObjectiveIntent.tags must be an iterable of strings"
            )
        return cls(
            intent_id=str(value.get("intent_id") or ""),
            idea_text=str(value.get("idea_text") or ""),
            idea_sha256=str(value.get("idea_sha256") or ""),
            submitter_kind=submitter_kind,
            caller=str(value.get("caller") or ""),
            repository_id=str(value.get("repository_id") or ""),
            board_namespace=str(value.get("board_namespace") or ""),
            title_hint=str(value.get("title_hint") or ""),
            tags=tuple(str(item) for item in tags_value),
            schema_version=str(
                value.get("schema_version") or SUPERVISOR_OBJECTIVE_INTENT_SCHEMA_VERSION
            ),
        )


def idea_text_sha256(idea_text: str) -> str:
    """Return the lowercase hex SHA-256 of UTF-8 ``idea_text``."""

    if not isinstance(idea_text, str):
        raise IntentIRValidationError("idea_text must be a string")
    return hashlib.sha256(idea_text.encode("utf-8")).hexdigest()


def validate_supervisor_objective_intent(
    intent: SupervisorObjectiveIntent | Mapping[str, Any],
) -> SupervisorObjectiveIntent:
    """Validate and return a :class:`SupervisorObjectiveIntent`."""

    if isinstance(intent, Mapping):
        intent = SupervisorObjectiveIntent.from_dict(intent)
    if not isinstance(intent, SupervisorObjectiveIntent):
        raise IntentIRValidationError(
            "SupervisorObjectiveIntent mappings require from_dict or a typed value"
        )
    if intent.schema_version != SUPERVISOR_OBJECTIVE_INTENT_SCHEMA_VERSION:
        raise IntentIRValidationError(
            "Unsupported SupervisorObjectiveIntent schema_version: "
            f"{intent.schema_version!r}"
        )
    _validate_identifier("SupervisorObjectiveIntent.intent_id", intent.intent_id)
    _validate_non_empty_string("SupervisorObjectiveIntent.idea_text", intent.idea_text)
    idea_bytes = intent.idea_text.encode("utf-8")
    if len(idea_bytes) > SUPERVISOR_OBJECTIVE_INTENT_MAX_IDEA_UTF8_BYTES:
        raise IntentIRValidationError(
            "SupervisorObjectiveIntent.idea_text exceeds "
            f"{SUPERVISOR_OBJECTIVE_INTENT_MAX_IDEA_UTF8_BYTES} UTF-8 bytes"
        )
    _validate_sha256("SupervisorObjectiveIntent.idea_sha256", intent.idea_sha256)
    expected_digest = hashlib.sha256(idea_bytes).hexdigest()
    if intent.idea_sha256 != expected_digest:
        raise IntentIRValidationError(
            "SupervisorObjectiveIntent.idea_sha256 does not match idea_text"
        )
    _validate_enum(
        "SupervisorObjectiveIntent.submitter_kind",
        intent.submitter_kind,
        SupervisorObjectiveSubmitterKind,
    )
    _validate_non_empty_string("SupervisorObjectiveIntent.caller", intent.caller)
    _validate_string("SupervisorObjectiveIntent.repository_id", intent.repository_id)
    if intent.repository_id:
        _validate_identifier(
            "SupervisorObjectiveIntent.repository_id",
            intent.repository_id,
        )
    _validate_string("SupervisorObjectiveIntent.board_namespace", intent.board_namespace)
    if intent.board_namespace:
        _validate_identifier(
            "SupervisorObjectiveIntent.board_namespace",
            intent.board_namespace,
        )
    _validate_string("SupervisorObjectiveIntent.title_hint", intent.title_hint)
    _require_tuple("SupervisorObjectiveIntent.tags", intent.tags)
    _validate_string_items("SupervisorObjectiveIntent.tags", intent.tags)
    _require_unique(intent.tags, "SupervisorObjectiveIntent.tags member")
    if len(intent.tags) > SUPERVISOR_OBJECTIVE_INTENT_MAX_TAGS:
        raise IntentIRValidationError(
            "SupervisorObjectiveIntent.tags exceeds "
            f"{SUPERVISOR_OBJECTIVE_INTENT_MAX_TAGS} members"
        )
    return intent


@dataclass(frozen=True, slots=True)
class ObjectiveMaterializationReceipt:
    """Immutable semantic evidence produced when an objective is materialized.

    The receipt binds the submitted intent's digest to the materialized
    semantic objective and revision identities.  It neither admits work nor
    authorizes storage, execution, policy decisions, or task completion.
    """

    receipt_id: str
    intent_id: str
    intent_sha256: str
    objective_id: str
    objective_cid: str
    objective_revision_cid: str
    schema_version: str = OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA_VERSION

    def validate(self) -> None:
        validate_objective_materialization_receipt(self)

    @property
    def schema(self) -> str:
        return OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA

    @property
    def is_completion_authority(self) -> bool:
        """Receipts are evidence and can never complete an objective."""

        return False

    def to_dict(self) -> dict[str, str]:
        self.validate()
        return {
            "intent_id": self.intent_id,
            "intent_sha256": self.intent_sha256,
            "objective_cid": self.objective_cid,
            "objective_id": self.objective_id,
            "objective_revision_cid": self.objective_revision_cid,
            "receipt_id": self.receipt_id,
            "schema": OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObjectiveMaterializationReceipt":
        if not isinstance(value, Mapping):
            raise IntentIRValidationError(
                "ObjectiveMaterializationReceipt mapping must be a mapping"
            )
        forbidden = sorted(
            key
            for key in value
            if key in OBJECTIVE_MATERIALIZATION_RECEIPT_FORBIDDEN_FIELDS
        )
        if forbidden:
            raise IntentIRValidationError(
                "ObjectiveMaterializationReceipt forbids authoritative fields: "
                + ", ".join(forbidden)
            )
        allowed = {
            "intent_id",
            "intent_sha256",
            "objective_cid",
            "objective_id",
            "objective_revision_cid",
            "receipt_id",
            "schema",
            "schema_version",
        }
        unknown = sorted(key for key in value if key not in allowed)
        if unknown:
            raise IntentIRValidationError(
                "ObjectiveMaterializationReceipt has unknown fields: "
                + ", ".join(unknown)
            )
        schema = value.get("schema", OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA)
        if schema != OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA:
            raise IntentIRValidationError(
                "Unsupported ObjectiveMaterializationReceipt schema: "
                f"{schema!r}"
            )
        return cls(
            receipt_id=str(value.get("receipt_id") or ""),
            intent_id=str(value.get("intent_id") or ""),
            intent_sha256=str(value.get("intent_sha256") or ""),
            objective_id=str(value.get("objective_id") or ""),
            objective_cid=str(value.get("objective_cid") or ""),
            objective_revision_cid=str(value.get("objective_revision_cid") or ""),
            schema_version=str(
                value.get("schema_version")
                or OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA_VERSION
            ),
        )


def validate_objective_materialization_receipt(
    receipt: ObjectiveMaterializationReceipt | Mapping[str, Any],
) -> ObjectiveMaterializationReceipt:
    """Validate and return an :class:`ObjectiveMaterializationReceipt`."""

    if isinstance(receipt, Mapping):
        receipt = ObjectiveMaterializationReceipt.from_dict(receipt)
    if not isinstance(receipt, ObjectiveMaterializationReceipt):
        raise IntentIRValidationError(
            "ObjectiveMaterializationReceipt mappings require from_dict or a typed value"
        )
    if receipt.schema_version != OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA_VERSION:
        raise IntentIRValidationError(
            "Unsupported ObjectiveMaterializationReceipt schema_version: "
            f"{receipt.schema_version!r}"
        )
    for name in ("receipt_id", "intent_id", "objective_id"):
        _validate_identifier(
            f"ObjectiveMaterializationReceipt.{name}", getattr(receipt, name)
        )
    _validate_sha256(
        "ObjectiveMaterializationReceipt.intent_sha256", receipt.intent_sha256
    )
    for name in ("objective_cid", "objective_revision_cid"):
        _validate_identifier(
            f"ObjectiveMaterializationReceipt.{name}", getattr(receipt, name)
        )
    return receipt


__all__ = [
    "CollectionSemantics",
    "INTENT_IR_COLLECTION_SCHEMA",
    "INTENT_IR_SCHEMA_VERSION",
    "INTENT_IR_COLLECTION_SEMANTICS",
    "LEGACY_INTENT_IR_SCHEMA_VERSION",
    "OBJECTIVE_MATERIALIZATION_RECEIPT_FORBIDDEN_FIELDS",
    "OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA",
    "OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA_VERSION",
    "SUPERVISOR_OBJECTIVE_INTENT_FORBIDDEN_FIELDS",
    "SUPERVISOR_OBJECTIVE_INTENT_MAX_IDEA_UTF8_BYTES",
    "SUPERVISOR_OBJECTIVE_INTENT_MAX_TAGS",
    "SUPERVISOR_OBJECTIVE_INTENT_SCHEMA",
    "SUPERVISOR_OBJECTIVE_INTENT_SCHEMA_VERSION",
    "ControlEdgeKind",
    "GroundingKind",
    "IntentAction",
    "IntentControlEdge",
    "IntentIRDocument",
    "IntentIRValidationError",
    "IntentKind",
    "IntentModality",
    "IntentStatement",
    "NodeGrounding",
    "ObjectiveMaterializationReceipt",
    "ReviewStatus",
    "SourceRef",
    "SourceSpan",
    "StatementKind",
    "SupervisorObjectiveIntent",
    "SupervisorObjectiveSubmitterKind",
    "idea_text_sha256",
    "validate_intent_ir",
    "validate_objective_materialization_receipt",
    "validate_supervisor_objective_intent",
]
