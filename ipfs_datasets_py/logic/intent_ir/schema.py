"""Canonical, source-grounded Intent IR schema.

Intent IR models what a skill is trying to accomplish and the procedure it
describes.  It does not authorize or execute the procedure.  Raw source bodies,
GraphRAG indexes, embeddings, model responses, and proof artifacts live in
separate content-addressed artifacts and are joined through identifiers.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

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

# Datasets-owned deterministic normalization identity (DOEP-021).  Extends the
# existing SupervisorObjectiveIntent / materialization contracts with a
# fail-closed, semantic-only normalization carrier.  It does not authorize
# execution, admit policy, or complete objectives, and it is not a second
# Intent IR or planner subsystem.
DETERMINISTIC_NORMALIZATION_SCHEMA = (
    "ipfs_datasets_py/logic/intent-ir/deterministic-normalization@1"
)
DETERMINISTIC_NORMALIZATION_SCHEMA_VERSION = "deterministic-normalization/v1"
DETERMINISTIC_NORMALIZER_ID = (
    "ipfs_datasets_py/logic/intent-ir/deterministic-normalizer@1"
)
DETERMINISTIC_NORMALIZER_VERSION = "1"
DETERMINISTIC_NORMALIZATION_AUTHORITY = "semantic_only"
DETERMINISTIC_NORMALIZATION_MAX_SCOPE_PATHS = 64
_BUDGET_PROFILE_RE = re.compile(r"^B[0-9]$")
_RISK_CLASS_RE = re.compile(r"^R[0-9]$")
DETERMINISTIC_NORMALIZATION_FORBIDDEN_FIELDS = frozenset(
    {
        "authorization",
        "authorization_decision",
        "budgets",
        "completion_authoritative",
        "duckdb",
        "ducklake",
        "execution_authorization",
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
        "storage_authorization",
        "task_cids",
        "terminalize",
    }
)

# Datasets-owned rule/template objective decomposition (DOEP-023).  Extends the
# existing SupervisorObjectiveIntent / DeterministicObjectiveNormalization
# contracts with a fail-closed, semantic-only decomposition carrier for known
# objective classes.  It does not authorize execution, admit policy, or complete
# objectives, and it is not a second Intent IR, planner, or competing subsystem.
RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA = (
    "ipfs_datasets_py/logic/intent-ir/rule-driven-objective-decomposition@1"
)
RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA_VERSION = (
    "rule-driven-objective-decomposition/v1"
)
RULE_DRIVEN_OBJECTIVE_DECOMPOSER_ID = (
    "ipfs_datasets_py/logic/intent-ir/rule-driven-objective-decomposer@1"
)
RULE_DRIVEN_OBJECTIVE_DECOMPOSER_VERSION = "1"
RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_AUTHORITY = "semantic_only"
RULE_DRIVEN_DECOMPOSITION_MAX_CHILDREN = 12
RULE_DRIVEN_DECOMPOSITION_MAX_CHILD_SCOPE_PATHS = 64
RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_FORBIDDEN_FIELDS = frozenset(
    DETERMINISTIC_NORMALIZATION_FORBIDDEN_FIELDS
    | {
        "assumptions",
        "acceptance_conditions",
        "guarantees",
        "non_goals",
        "budget_profile",
        "risk_class",
        "dry_run",
        "effect_claims",
        "expected_effects",
    }
)

# Datasets-owned unresolved semantic-question contract (DOEP-025).  Extends the
# existing SupervisorObjectiveIntent / DeterministicObjectiveNormalization /
# RuleDrivenObjectiveDecomposition carriers with a fail-closed, semantic-only
# record of named questions that remain after deterministic stages.  It names
# the smallest adequate specialist class and a typed response shape, but it
# does not dispatch models, execute tools, admit policy, or complete
# objectives, and it is not a second Intent IR, planner, or competing
# subsystem.
UNRESOLVED_QUESTION_SCHEMA = (
    "ipfs_datasets_py/logic/intent-ir/unresolved-question@1"
)
UNRESOLVED_QUESTION_SCHEMA_VERSION = "unresolved-question/v1"
UNRESOLVED_QUESTION_CAPTURE_SCHEMA = (
    "ipfs_datasets_py/logic/intent-ir/unresolved-question-capture@1"
)
UNRESOLVED_QUESTION_CAPTURE_SCHEMA_VERSION = "unresolved-question-capture/v1"
UNRESOLVED_QUESTION_CAPTURE_ID = (
    "ipfs_datasets_py/logic/intent-ir/unresolved-question-capture@1"
)
UNRESOLVED_QUESTION_CAPTURE_VERSION = "1"
UNRESOLVED_QUESTION_AUTHORITY = "semantic_only"
UNRESOLVED_QUESTION_MAX_QUESTIONS = 16
UNRESOLVED_QUESTION_MAX_TEXT_CHARS = 4096
UNRESOLVED_QUESTION_MAX_REASON_CHARS = 2048
UNRESOLVED_QUESTION_MAX_EVIDENCE_ITEMS = 64
UNRESOLVED_QUESTION_MAX_EVIDENCE_CHARS = 1024
UNRESOLVED_QUESTION_MAX_RESPONSE_VALUES = 16
UNRESOLVED_QUESTION_MAX_RESPONSE_VALUE_CHARS = 256
UNRESOLVED_QUESTION_MAX_CONTEXT_BUDGET = 262144
UNRESOLVED_QUESTION_FORBIDDEN_FIELDS = frozenset(
    RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_FORBIDDEN_FIELDS
    | {
        "tool_calls",
        "tool_call",
        "tools",
        "execute_tools",
        "dispatch",
        "dispatch_now",
        "model_invocation",
        "invoke_model",
        "completion_authoritative",
        "terminal_answer",
    }
)
_QUESTION_IDENTITY_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


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


def supervisor_objective_intent_sha256(
    intent: SupervisorObjectiveIntent | Mapping[str, Any],
) -> str:
    """Return the lowercase hex SHA-256 of a validated intent's canonical JSON."""

    validated = validate_supervisor_objective_intent(intent)
    canonical = json.dumps(
        validated.to_dict(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_scope_path(path: Any, *, label: str) -> str:
    if not isinstance(path, str):
        raise IntentIRValidationError(f"{label} must be a string")
    text = path.strip().replace("\\", "/")
    if not text:
        raise IntentIRValidationError(f"{label} must not be empty")
    if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
        raise IntentIRValidationError(f"{label} must be a relative path")
    if any(part == ".." for part in text.split("/")):
        raise IntentIRValidationError(f"{label} rejects parent-path escapes")
    normalized = posixpath.normpath(text)
    if normalized in {"", "."}:
        return "."
    if normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
        raise IntentIRValidationError(f"{label} rejects parent-path escapes")
    if normalized != text.rstrip("/"):
        # Callers must supply already-lexically-normalized relative paths so
        # normalization never silently rewrites declared scope.
        raise IntentIRValidationError(f"{label} must be lexically normalized")
    return normalized


def _normalize_profile_token(
    value: Any, *, label: str, pattern: re.Pattern[str]
) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise IntentIRValidationError(f"{label} must be a string")
    text = value.strip()
    if not text:
        return ""
    if not pattern.fullmatch(text):
        raise IntentIRValidationError(f"{label} is not a closed profile token")
    return text


@dataclass(frozen=True, slots=True)
class DeterministicObjectiveNormalization:
    """Semantic-only result of deterministic supervisor-objective normalization.

    Parallel to :class:`SupervisorObjectiveIntent` and
    :class:`ObjectiveMaterializationReceipt`.  The carrier binds a validated
    intent digest to normalized scope and non-authoritative budget/risk/policy
    hints.  Accelerate alone admits operational policy, budgets, and execution.
    """

    intent_id: str
    intent_sha256: str
    idea_sha256: str
    repository_id: str
    board_namespace: str
    title_hint: str = ""
    tags: tuple[str, ...] = ()
    scope_paths: tuple[str, ...] = ()
    proposed_budget_profile: str = ""
    proposed_risk_class: str = ""
    policy_binding: str = ""
    normalizer_id: str = DETERMINISTIC_NORMALIZER_ID
    normalizer_version: str = DETERMINISTIC_NORMALIZER_VERSION
    schema_version: str = DETERMINISTIC_NORMALIZATION_SCHEMA_VERSION

    def validate(self) -> None:
        validate_deterministic_objective_normalization(self)

    @property
    def schema(self) -> str:
        return DETERMINISTIC_NORMALIZATION_SCHEMA

    @property
    def authority(self) -> str:
        return DETERMINISTIC_NORMALIZATION_AUTHORITY

    @property
    def is_completion_authority(self) -> bool:
        return False

    @property
    def callers_supply_authoritative_policy(self) -> bool:
        return False

    @property
    def normalization_sha256(self) -> str:
        payload = self.to_dict()
        canonical = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": DETERMINISTIC_NORMALIZATION_AUTHORITY,
            "board_namespace": self.board_namespace,
            "idea_sha256": self.idea_sha256,
            "intent_id": self.intent_id,
            "intent_sha256": self.intent_sha256,
            "normalizer_id": self.normalizer_id,
            "normalizer_version": self.normalizer_version,
            "policy_binding": self.policy_binding,
            "proposed_budget_profile": self.proposed_budget_profile,
            "proposed_risk_class": self.proposed_risk_class,
            "repository_id": self.repository_id,
            "schema": DETERMINISTIC_NORMALIZATION_SCHEMA,
            "schema_version": self.schema_version,
            "scope_paths": list(self.scope_paths),
            "tags": list(self.tags),
            "title_hint": self.title_hint,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeterministicObjectiveNormalization":
        if not isinstance(value, Mapping):
            raise IntentIRValidationError(
                "DeterministicObjectiveNormalization mapping must be a mapping"
            )
        forbidden = sorted(
            key
            for key in value
            if key in DETERMINISTIC_NORMALIZATION_FORBIDDEN_FIELDS
        )
        if forbidden:
            raise IntentIRValidationError(
                "DeterministicObjectiveNormalization forbids authoritative fields: "
                + ", ".join(forbidden)
            )
        allowed = {
            "authority",
            "board_namespace",
            "idea_sha256",
            "intent_id",
            "intent_sha256",
            "normalization_sha256",
            "normalizer_id",
            "normalizer_version",
            "policy_binding",
            "proposed_budget_profile",
            "proposed_risk_class",
            "repository_id",
            "schema",
            "schema_version",
            "scope_paths",
            "tags",
            "title_hint",
        }
        unknown = sorted(key for key in value if key not in allowed)
        if unknown:
            raise IntentIRValidationError(
                "DeterministicObjectiveNormalization has unknown fields: "
                + ", ".join(unknown)
            )
        schema = value.get("schema", DETERMINISTIC_NORMALIZATION_SCHEMA)
        if schema != DETERMINISTIC_NORMALIZATION_SCHEMA:
            raise IntentIRValidationError(
                "Unsupported DeterministicObjectiveNormalization schema: "
                f"{schema!r}"
            )
        authority = value.get("authority", DETERMINISTIC_NORMALIZATION_AUTHORITY)
        if authority != DETERMINISTIC_NORMALIZATION_AUTHORITY:
            raise IntentIRValidationError(
                "DeterministicObjectiveNormalization cannot claim authority"
            )
        scope_raw = value.get("scope_paths", ())
        if isinstance(scope_raw, str) or not isinstance(scope_raw, Iterable):
            raise IntentIRValidationError(
                "DeterministicObjectiveNormalization.scope_paths must be an iterable of strings"
            )
        tags_raw = value.get("tags", ())
        if isinstance(tags_raw, str) or not isinstance(tags_raw, Iterable):
            raise IntentIRValidationError(
                "DeterministicObjectiveNormalization.tags must be an iterable of strings"
            )
        return cls(
            intent_id=str(value.get("intent_id") or ""),
            intent_sha256=str(value.get("intent_sha256") or ""),
            idea_sha256=str(value.get("idea_sha256") or ""),
            repository_id=str(value.get("repository_id") or ""),
            board_namespace=str(value.get("board_namespace") or ""),
            title_hint=str(value.get("title_hint") or ""),
            tags=tuple(str(item) for item in tags_raw),
            scope_paths=tuple(str(item) for item in scope_raw),
            proposed_budget_profile=str(value.get("proposed_budget_profile") or ""),
            proposed_risk_class=str(value.get("proposed_risk_class") or ""),
            policy_binding=str(value.get("policy_binding") or ""),
            normalizer_id=str(
                value.get("normalizer_id") or DETERMINISTIC_NORMALIZER_ID
            ),
            normalizer_version=str(
                value.get("normalizer_version") or DETERMINISTIC_NORMALIZER_VERSION
            ),
            schema_version=str(
                value.get("schema_version")
                or DETERMINISTIC_NORMALIZATION_SCHEMA_VERSION
            ),
        )


def validate_deterministic_objective_normalization(
    value: DeterministicObjectiveNormalization | Mapping[str, Any],
) -> DeterministicObjectiveNormalization:
    """Validate and return a :class:`DeterministicObjectiveNormalization`."""

    if isinstance(value, Mapping):
        value = DeterministicObjectiveNormalization.from_dict(value)
    if not isinstance(value, DeterministicObjectiveNormalization):
        raise IntentIRValidationError(
            "DeterministicObjectiveNormalization mappings require from_dict or a typed value"
        )
    if value.schema_version != DETERMINISTIC_NORMALIZATION_SCHEMA_VERSION:
        raise IntentIRValidationError(
            "Unsupported DeterministicObjectiveNormalization schema_version: "
            f"{value.schema_version!r}"
        )
    if value.normalizer_id != DETERMINISTIC_NORMALIZER_ID:
        raise IntentIRValidationError(
            "DeterministicObjectiveNormalization.normalizer_id is unsupported: "
            f"{value.normalizer_id!r}"
        )
    if value.normalizer_version != DETERMINISTIC_NORMALIZER_VERSION:
        raise IntentIRValidationError(
            "DeterministicObjectiveNormalization.normalizer_version is unsupported: "
            f"{value.normalizer_version!r}"
        )
    _validate_identifier(
        "DeterministicObjectiveNormalization.intent_id", value.intent_id
    )
    _validate_sha256(
        "DeterministicObjectiveNormalization.intent_sha256", value.intent_sha256
    )
    _validate_sha256(
        "DeterministicObjectiveNormalization.idea_sha256", value.idea_sha256
    )
    _validate_string(
        "DeterministicObjectiveNormalization.repository_id", value.repository_id
    )
    if value.repository_id:
        _validate_identifier(
            "DeterministicObjectiveNormalization.repository_id",
            value.repository_id,
        )
    _validate_string(
        "DeterministicObjectiveNormalization.board_namespace", value.board_namespace
    )
    if value.board_namespace:
        _validate_identifier(
            "DeterministicObjectiveNormalization.board_namespace",
            value.board_namespace,
        )
    _validate_string(
        "DeterministicObjectiveNormalization.title_hint", value.title_hint
    )
    _require_tuple("DeterministicObjectiveNormalization.tags", value.tags)
    _validate_string_items("DeterministicObjectiveNormalization.tags", value.tags)
    _require_unique(value.tags, "DeterministicObjectiveNormalization.tags member")
    if list(value.tags) != sorted(value.tags):
        raise IntentIRValidationError(
            "DeterministicObjectiveNormalization.tags must be sorted"
        )
    _require_tuple(
        "DeterministicObjectiveNormalization.scope_paths", value.scope_paths
    )
    if len(value.scope_paths) > DETERMINISTIC_NORMALIZATION_MAX_SCOPE_PATHS:
        raise IntentIRValidationError(
            "DeterministicObjectiveNormalization.scope_paths exceeds "
            f"{DETERMINISTIC_NORMALIZATION_MAX_SCOPE_PATHS} members"
        )
    normalized_paths = tuple(
        _normalize_scope_path(
            path, label=f"DeterministicObjectiveNormalization.scope_paths[{index}]"
        )
        for index, path in enumerate(value.scope_paths)
    )
    _require_unique(
        normalized_paths, "DeterministicObjectiveNormalization.scope_paths member"
    )
    if normalized_paths != value.scope_paths:
        raise IntentIRValidationError(
            "DeterministicObjectiveNormalization.scope_paths must be lexically normalized"
        )
    if list(value.scope_paths) != sorted(value.scope_paths):
        raise IntentIRValidationError(
            "DeterministicObjectiveNormalization.scope_paths must be sorted"
        )
    budget = _normalize_profile_token(
        value.proposed_budget_profile,
        label="DeterministicObjectiveNormalization.proposed_budget_profile",
        pattern=_BUDGET_PROFILE_RE,
    )
    if budget != value.proposed_budget_profile:
        raise IntentIRValidationError(
            "DeterministicObjectiveNormalization.proposed_budget_profile is invalid"
        )
    risk = _normalize_profile_token(
        value.proposed_risk_class,
        label="DeterministicObjectiveNormalization.proposed_risk_class",
        pattern=_RISK_CLASS_RE,
    )
    if risk != value.proposed_risk_class:
        raise IntentIRValidationError(
            "DeterministicObjectiveNormalization.proposed_risk_class is invalid"
        )
    _validate_string(
        "DeterministicObjectiveNormalization.policy_binding", value.policy_binding
    )
    if value.policy_binding:
        _validate_identifier(
            "DeterministicObjectiveNormalization.policy_binding",
            value.policy_binding,
        )
    return value


def normalize_supervisor_objective_deterministically(
    intent: SupervisorObjectiveIntent | Mapping[str, Any],
    *,
    scope_paths: Sequence[str] | None = None,
    proposed_budget_profile: str = "",
    proposed_risk_class: str = "",
    policy_binding: str = "",
) -> DeterministicObjectiveNormalization:
    """Deterministically validate and normalize one supervisor objective intent.

    This is a thin extension of the existing datasets-owned intent contracts:
    it reuses :func:`validate_supervisor_objective_intent`, normalizes scope
    paths, and records non-authoritative budget/risk/policy bindings.  It does
    not create a competing Intent IR document, planner, or admission authority.
    """

    if isinstance(intent, Mapping):
        forbidden = sorted(
            key
            for key in intent
            if key in DETERMINISTIC_NORMALIZATION_FORBIDDEN_FIELDS
            or key in SUPERVISOR_OBJECTIVE_INTENT_FORBIDDEN_FIELDS
        )
        if forbidden:
            raise IntentIRValidationError(
                "deterministic normalization rejects authority/path escapes: "
                + ", ".join(forbidden)
            )
    validated = validate_supervisor_objective_intent(intent)
    raw_paths = () if scope_paths is None else scope_paths
    if isinstance(raw_paths, (str, bytes, bytearray)) or not isinstance(
        raw_paths, Sequence
    ):
        raise IntentIRValidationError("scope_paths must be a sequence of strings")
    normalized_paths = sorted(
        {
            _normalize_scope_path(path, label=f"scope_paths[{index}]")
            for index, path in enumerate(raw_paths)
        }
    )
    if len(normalized_paths) > DETERMINISTIC_NORMALIZATION_MAX_SCOPE_PATHS:
        raise IntentIRValidationError(
            "scope_paths exceeds "
            f"{DETERMINISTIC_NORMALIZATION_MAX_SCOPE_PATHS} members"
        )
    budget = _normalize_profile_token(
        proposed_budget_profile,
        label="proposed_budget_profile",
        pattern=_BUDGET_PROFILE_RE,
    )
    risk = _normalize_profile_token(
        proposed_risk_class,
        label="proposed_risk_class",
        pattern=_RISK_CLASS_RE,
    )
    binding = policy_binding.strip() if isinstance(policy_binding, str) else ""
    if policy_binding is not None and not isinstance(policy_binding, str):
        raise IntentIRValidationError("policy_binding must be a string")
    if binding:
        _validate_identifier("policy_binding", binding)
    tags = tuple(sorted(set(validated.tags)))
    result = DeterministicObjectiveNormalization(
        intent_id=validated.intent_id,
        intent_sha256=supervisor_objective_intent_sha256(validated),
        idea_sha256=validated.idea_sha256,
        repository_id=validated.repository_id,
        board_namespace=validated.board_namespace,
        title_hint=validated.title_hint.strip(),
        tags=tags,
        scope_paths=tuple(normalized_paths),
        proposed_budget_profile=budget,
        proposed_risk_class=risk,
        policy_binding=binding,
    )
    return validate_deterministic_objective_normalization(result)


class KnownObjectiveClass(str, Enum):
    """Closed set of objective classes with rule/template decomposition."""

    DIRECT_OBJECTIVE_CONTRACT = "direct_objective_contract"
    DETERMINISTIC_NORMALIZATION = "deterministic_normalization"
    REPOSITORY_CAPABILITY_ANALYSIS = "repository_capability_analysis"
    STAGED_OBJECTIVE_COMPILER = "staged_objective_compiler"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RuleDrivenDecompositionChild:
    """One semantic child fragment produced by a known-class rule template.

    Children are advisory plan fragments only.  They do not admit tasks, leases,
    policy, or execution, and they are not a second planner subsystem.
    """

    child_id: str
    title: str
    role: str
    scope_paths: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    covers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "child_id": self.child_id,
            "covers": list(self.covers),
            "depends_on": list(self.depends_on),
            "role": self.role,
            "scope_paths": list(self.scope_paths),
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuleDrivenDecompositionChild":
        if not isinstance(value, Mapping):
            raise IntentIRValidationError(
                "RuleDrivenDecompositionChild mapping must be a mapping"
            )
        allowed = {
            "child_id",
            "covers",
            "depends_on",
            "role",
            "scope_paths",
            "title",
        }
        unknown = sorted(key for key in value if key not in allowed)
        if unknown:
            raise IntentIRValidationError(
                "RuleDrivenDecompositionChild has unknown fields: "
                + ", ".join(unknown)
            )
        for key in ("scope_paths", "depends_on", "covers"):
            raw = value.get(key, ())
            if isinstance(raw, str) or not isinstance(raw, Iterable):
                raise IntentIRValidationError(
                    f"RuleDrivenDecompositionChild.{key} must be an iterable of strings"
                )
        return cls(
            child_id=str(value.get("child_id") or ""),
            title=str(value.get("title") or ""),
            role=str(value.get("role") or ""),
            scope_paths=tuple(str(item) for item in value.get("scope_paths", ())),
            depends_on=tuple(str(item) for item in value.get("depends_on", ())),
            covers=tuple(str(item) for item in value.get("covers", ())),
        )


@dataclass(frozen=True, slots=True)
class KnownObjectiveClassRule:
    """Closed rule/template used to expand one known objective class."""

    rule_id: str
    objective_class: KnownObjectiveClass
    match_tags: tuple[str, ...]
    child_templates: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "child_templates": [dict(item) for item in self.child_templates],
            "match_tags": list(self.match_tags),
            "objective_class": self.objective_class.value,
            "rule_id": self.rule_id,
        }


@dataclass(frozen=True, slots=True)
class RuleDrivenObjectiveDecomposition:
    """Semantic-only result of rule/template supervisor-objective decomposition.

    Parallel to :class:`DeterministicObjectiveNormalization` and
    :class:`SupervisorObjectiveIntent`.  The carrier binds a validated
    normalization digest to a bounded, acyclic child-fragment DAG for a known
    objective class.  Accelerate alone admits operational plans and execution.
    It does not create a competing Intent IR or planner subsystem.
    """

    intent_id: str
    intent_sha256: str
    idea_sha256: str
    normalization_sha256: str
    repository_id: str
    board_namespace: str
    objective_class: str
    matched_rule_id: str
    matched: bool
    truncated: bool
    reason_code: str
    scope_paths: tuple[str, ...] = ()
    children: tuple[RuleDrivenDecompositionChild, ...] = ()
    dependency_edges: tuple[tuple[str, str], ...] = ()
    available_capability_ids: tuple[str, ...] = ()
    repository_analysis_cid: str = ""
    decomposer_id: str = RULE_DRIVEN_OBJECTIVE_DECOMPOSER_ID
    decomposer_version: str = RULE_DRIVEN_OBJECTIVE_DECOMPOSER_VERSION
    schema_version: str = RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA_VERSION

    def validate(self) -> None:
        validate_rule_driven_objective_decomposition(self)

    @property
    def schema(self) -> str:
        return RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA

    @property
    def authority(self) -> str:
        return RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_AUTHORITY

    @property
    def is_completion_authority(self) -> bool:
        return False

    @property
    def callers_supply_authoritative_policy(self) -> bool:
        return False

    @property
    def decomposition_sha256(self) -> str:
        payload = self.to_dict()
        canonical = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_AUTHORITY,
            "available_capability_ids": list(self.available_capability_ids),
            "board_namespace": self.board_namespace,
            "children": [child.to_dict() for child in self.children],
            "decomposer_id": self.decomposer_id,
            "decomposer_version": self.decomposer_version,
            "dependency_edges": [list(edge) for edge in self.dependency_edges],
            "idea_sha256": self.idea_sha256,
            "intent_id": self.intent_id,
            "intent_sha256": self.intent_sha256,
            "matched": self.matched,
            "matched_rule_id": self.matched_rule_id,
            "normalization_sha256": self.normalization_sha256,
            "objective_class": self.objective_class,
            "reason_code": self.reason_code,
            "repository_analysis_cid": self.repository_analysis_cid,
            "repository_id": self.repository_id,
            "schema": RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA,
            "schema_version": self.schema_version,
            "scope_paths": list(self.scope_paths),
            "truncated": self.truncated,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuleDrivenObjectiveDecomposition":
        if not isinstance(value, Mapping):
            raise IntentIRValidationError(
                "RuleDrivenObjectiveDecomposition mapping must be a mapping"
            )
        forbidden = sorted(
            key
            for key in value
            if key in RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_FORBIDDEN_FIELDS
        )
        if forbidden:
            raise IntentIRValidationError(
                "RuleDrivenObjectiveDecomposition forbids authoritative fields: "
                + ", ".join(forbidden)
            )
        allowed = {
            "authority",
            "available_capability_ids",
            "board_namespace",
            "children",
            "decomposition_sha256",
            "decomposer_id",
            "decomposer_version",
            "dependency_edges",
            "idea_sha256",
            "intent_id",
            "intent_sha256",
            "matched",
            "matched_rule_id",
            "normalization_sha256",
            "objective_class",
            "reason_code",
            "repository_analysis_cid",
            "repository_id",
            "schema",
            "schema_version",
            "scope_paths",
            "truncated",
        }
        unknown = sorted(key for key in value if key not in allowed)
        if unknown:
            raise IntentIRValidationError(
                "RuleDrivenObjectiveDecomposition has unknown fields: "
                + ", ".join(unknown)
            )
        schema = value.get("schema", RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA)
        if schema != RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA:
            raise IntentIRValidationError(
                "Unsupported RuleDrivenObjectiveDecomposition schema: "
                f"{schema!r}"
            )
        authority = value.get(
            "authority", RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_AUTHORITY
        )
        if authority != RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_AUTHORITY:
            raise IntentIRValidationError(
                "RuleDrivenObjectiveDecomposition cannot claim authority"
            )
        for key in (
            "scope_paths",
            "available_capability_ids",
        ):
            raw = value.get(key, ())
            if isinstance(raw, str) or not isinstance(raw, Iterable):
                raise IntentIRValidationError(
                    f"RuleDrivenObjectiveDecomposition.{key} must be an iterable of strings"
                )
        children_raw = value.get("children", ())
        if isinstance(children_raw, (str, bytes, bytearray)) or not isinstance(
            children_raw, Iterable
        ):
            raise IntentIRValidationError(
                "RuleDrivenObjectiveDecomposition.children must be an iterable"
            )
        edges_raw = value.get("dependency_edges", ())
        if isinstance(edges_raw, (str, bytes, bytearray)) or not isinstance(
            edges_raw, Iterable
        ):
            raise IntentIRValidationError(
                "RuleDrivenObjectiveDecomposition.dependency_edges must be an iterable"
            )
        children: list[RuleDrivenDecompositionChild] = []
        for item in children_raw:
            if isinstance(item, RuleDrivenDecompositionChild):
                children.append(item)
            elif isinstance(item, Mapping):
                children.append(RuleDrivenDecompositionChild.from_dict(item))
            else:
                raise IntentIRValidationError(
                    "RuleDrivenObjectiveDecomposition.children members must be mappings"
                )
        edges: list[tuple[str, str]] = []
        for item in edges_raw:
            if (
                isinstance(item, Sequence)
                and not isinstance(item, (str, bytes, bytearray))
                and len(item) == 2
            ):
                edges.append((str(item[0]), str(item[1])))
            else:
                raise IntentIRValidationError(
                    "RuleDrivenObjectiveDecomposition.dependency_edges members must be pairs"
                )
        matched = value.get("matched", False)
        truncated = value.get("truncated", False)
        if not isinstance(matched, bool):
            raise IntentIRValidationError(
                "RuleDrivenObjectiveDecomposition.matched must be a bool"
            )
        if not isinstance(truncated, bool):
            raise IntentIRValidationError(
                "RuleDrivenObjectiveDecomposition.truncated must be a bool"
            )
        return cls(
            intent_id=str(value.get("intent_id") or ""),
            intent_sha256=str(value.get("intent_sha256") or ""),
            idea_sha256=str(value.get("idea_sha256") or ""),
            normalization_sha256=str(value.get("normalization_sha256") or ""),
            repository_id=str(value.get("repository_id") or ""),
            board_namespace=str(value.get("board_namespace") or ""),
            objective_class=str(value.get("objective_class") or ""),
            matched_rule_id=str(value.get("matched_rule_id") or ""),
            matched=matched,
            truncated=truncated,
            reason_code=str(value.get("reason_code") or ""),
            scope_paths=tuple(str(item) for item in value.get("scope_paths", ())),
            children=tuple(children),
            dependency_edges=tuple(edges),
            available_capability_ids=tuple(
                str(item) for item in value.get("available_capability_ids", ())
            ),
            repository_analysis_cid=str(value.get("repository_analysis_cid") or ""),
            decomposer_id=str(
                value.get("decomposer_id") or RULE_DRIVEN_OBJECTIVE_DECOMPOSER_ID
            ),
            decomposer_version=str(
                value.get("decomposer_version")
                or RULE_DRIVEN_OBJECTIVE_DECOMPOSER_VERSION
            ),
            schema_version=str(
                value.get("schema_version")
                or RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA_VERSION
            ),
        )


def _known_objective_class_rules() -> tuple[KnownObjectiveClassRule, ...]:
    """Return the closed rule/template table for known objective classes."""

    return (
        KnownObjectiveClassRule(
            rule_id="rule:direct-objective-contract/v1",
            objective_class=KnownObjectiveClass.DIRECT_OBJECTIVE_CONTRACT,
            match_tags=("contract", "direct-objective", "doep"),
            child_templates=(
                {
                    "child_id_suffix": "define-contract",
                    "title": "Define datasets-owned semantic contract",
                    "role": "define_contract",
                    "covers": ("schema", "contract"),
                    "depends_on": (),
                },
                {
                    "child_id_suffix": "independent-test",
                    "title": "Add independent current-tree contract test",
                    "role": "independent_test",
                    "covers": ("test",),
                    "depends_on": ("define-contract",),
                },
                {
                    "child_id_suffix": "output-receipt",
                    "title": "Emit output manifest and candidate receipt",
                    "role": "output_receipt",
                    "covers": ("output", "receipt"),
                    "depends_on": ("independent-test",),
                },
            ),
        ),
        KnownObjectiveClassRule(
            rule_id="rule:deterministic-normalization/v1",
            objective_class=KnownObjectiveClass.DETERMINISTIC_NORMALIZATION,
            match_tags=("deterministic", "normalization", "doep"),
            child_templates=(
                {
                    "child_id_suffix": "validate-intent",
                    "title": "Validate supervisor objective intent",
                    "role": "validate_intent",
                    "covers": ("intent",),
                    "depends_on": (),
                },
                {
                    "child_id_suffix": "normalize-scope",
                    "title": "Normalize scope and non-authoritative bindings",
                    "role": "normalize_scope",
                    "covers": ("scope", "budget_hint", "risk_hint"),
                    "depends_on": ("validate-intent",),
                },
                {
                    "child_id_suffix": "bind-carrier",
                    "title": "Bind deterministic normalization carrier",
                    "role": "bind_carrier",
                    "covers": ("normalization",),
                    "depends_on": ("normalize-scope",),
                },
            ),
        ),
        KnownObjectiveClassRule(
            rule_id="rule:repository-capability-analysis/v1",
            objective_class=KnownObjectiveClass.REPOSITORY_CAPABILITY_ANALYSIS,
            match_tags=("capability", "repository-analysis", "doep"),
            child_templates=(
                {
                    "child_id_suffix": "inspect-capabilities",
                    "title": "Inspect repository capability indexes",
                    "role": "inspect_capabilities",
                    "covers": ("capability",),
                    "depends_on": (),
                },
                {
                    "child_id_suffix": "emit-analysis",
                    "title": "Emit advisory repository analysis fragment",
                    "role": "emit_analysis",
                    "covers": ("analysis",),
                    "depends_on": ("inspect-capabilities",),
                },
            ),
        ),
        KnownObjectiveClassRule(
            rule_id="rule:staged-objective-compiler/v1",
            objective_class=KnownObjectiveClass.STAGED_OBJECTIVE_COMPILER,
            match_tags=("compiler", "staged", "doep"),
            child_templates=(
                {
                    "child_id_suffix": "normalize",
                    "title": "Deterministically normalize objective",
                    "role": "normalize",
                    "covers": ("normalization",),
                    "depends_on": (),
                },
                {
                    "child_id_suffix": "analyze",
                    "title": "Analyze repository and capabilities",
                    "role": "analyze",
                    "covers": ("analysis",),
                    "depends_on": ("normalize",),
                },
                {
                    "child_id_suffix": "decompose",
                    "title": "Apply rule-driven decomposition",
                    "role": "decompose",
                    "covers": ("decomposition",),
                    "depends_on": ("analyze",),
                },
                {
                    "child_id_suffix": "obligations",
                    "title": "Attach assumptions, guarantees, and acceptance",
                    "role": "obligations",
                    "covers": ("obligations",),
                    "depends_on": ("decompose",),
                },
                {
                    "child_id_suffix": "questions",
                    "title": "Capture unresolved semantic questions",
                    "role": "questions",
                    "covers": ("questions",),
                    "depends_on": ("obligations",),
                },
                {
                    "child_id_suffix": "residual",
                    "title": "Interpret logic-constrained residuals",
                    "role": "residual",
                    "covers": ("residual",),
                    "depends_on": ("questions",),
                },
                {
                    "child_id_suffix": "validate-plan",
                    "title": "Validate plan and completeness witness",
                    "role": "validate_plan",
                    "covers": ("validation",),
                    "depends_on": ("residual",),
                },
            ),
        ),
    )


_KNOWN_OBJECTIVE_CLASS_RULES: tuple[KnownObjectiveClassRule, ...] = (
    _known_objective_class_rules()
)
_KNOWN_OBJECTIVE_CLASS_BY_VALUE: dict[str, KnownObjectiveClass] = {
    item.value: item for item in KnownObjectiveClass
}
_RULE_BY_OBJECTIVE_CLASS: dict[KnownObjectiveClass, KnownObjectiveClassRule] = {
    rule.objective_class: rule for rule in _KNOWN_OBJECTIVE_CLASS_RULES
}


def list_known_objective_class_rules() -> tuple[KnownObjectiveClassRule, ...]:
    """Return the closed known-objective-class rule/template table."""

    return _KNOWN_OBJECTIVE_CLASS_RULES


def _coerce_known_objective_class(
    value: str | KnownObjectiveClass | None,
) -> KnownObjectiveClass | None:
    if value is None:
        return None
    if isinstance(value, KnownObjectiveClass):
        return value
    if not isinstance(value, str):
        raise IntentIRValidationError("objective_class must be a string or enum")
    text = value.strip()
    if not text:
        return None
    matched = _KNOWN_OBJECTIVE_CLASS_BY_VALUE.get(text)
    if matched is None:
        raise IntentIRValidationError(
            f"objective_class is not a closed known class: {text!r}"
        )
    return matched


def _select_known_objective_class_rule(
    *,
    objective_class: KnownObjectiveClass | None,
    tags: Sequence[str],
) -> tuple[KnownObjectiveClassRule | None, KnownObjectiveClass, str]:
    if objective_class is not None:
        if objective_class is KnownObjectiveClass.UNKNOWN:
            return None, KnownObjectiveClass.UNKNOWN, "unknown_objective_class"
        rule = _RULE_BY_OBJECTIVE_CLASS.get(objective_class)
        if rule is None:
            return None, KnownObjectiveClass.UNKNOWN, "unknown_objective_class"
        return rule, objective_class, "matched_template"

    tag_set = set(tags)
    ranked: list[tuple[int, KnownObjectiveClassRule]] = []
    for rule in _KNOWN_OBJECTIVE_CLASS_RULES:
        overlap = len(tag_set.intersection(rule.match_tags))
        if overlap:
            ranked.append((overlap, rule))
    if not ranked:
        return None, KnownObjectiveClass.UNKNOWN, "unknown_objective_class"
    ranked.sort(key=lambda item: (-item[0], item[1].rule_id))
    best_overlap, best_rule = ranked[0]
    if len(ranked) > 1 and ranked[1][0] == best_overlap:
        return None, KnownObjectiveClass.UNKNOWN, "ambiguous_objective_class"
    return best_rule, best_rule.objective_class, "matched_template"


def _child_scope_subset_of_parent(
    child_paths: Sequence[str], parent_paths: Sequence[str]
) -> bool:
    if not child_paths:
        return True
    if not parent_paths:
        return False
    parent = set(parent_paths)
    for path in child_paths:
        if path in parent:
            continue
        if not any(
            path == item or path.startswith(f"{item}/") for item in parent_paths
        ):
            return False
    return True


def _validate_dependency_dag(
    children: Sequence[RuleDrivenDecompositionChild],
) -> tuple[tuple[str, str], ...]:
    ids = [child.child_id for child in children]
    id_set = set(ids)
    if len(ids) != len(id_set):
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.children child_id values must be unique"
        )
    edges: list[tuple[str, str]] = []
    for child in children:
        for dependency in child.depends_on:
            if dependency not in id_set:
                raise IntentIRValidationError(
                    "RuleDrivenObjectiveDecomposition child depends_on references unknown child_id: "
                    f"{dependency!r}"
                )
            if dependency == child.child_id:
                raise IntentIRValidationError(
                    "RuleDrivenObjectiveDecomposition child cannot depend on itself"
                )
            edges.append((dependency, child.child_id))
    # Kahn topological sort for acyclicity.
    incoming: dict[str, int] = {child_id: 0 for child_id in ids}
    adjacency: dict[str, list[str]] = {child_id: [] for child_id in ids}
    for source, target in edges:
        adjacency[source].append(target)
        incoming[target] += 1
    queue = sorted(child_id for child_id, count in incoming.items() if count == 0)
    seen = 0
    while queue:
        node = queue.pop(0)
        seen += 1
        for nxt in sorted(adjacency[node]):
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                queue.append(nxt)
                queue.sort()
    if seen != len(ids):
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.children dependency graph must be acyclic"
        )
    return tuple(sorted(edges))


def validate_rule_driven_decomposition_child(
    value: RuleDrivenDecompositionChild | Mapping[str, Any],
    *,
    parent_scope_paths: Sequence[str] | None = None,
) -> RuleDrivenDecompositionChild:
    """Validate one rule-driven decomposition child fragment."""

    if isinstance(value, Mapping):
        value = RuleDrivenDecompositionChild.from_dict(value)
    if not isinstance(value, RuleDrivenDecompositionChild):
        raise IntentIRValidationError(
            "RuleDrivenDecompositionChild mappings require from_dict or a typed value"
        )
    _validate_identifier("RuleDrivenDecompositionChild.child_id", value.child_id)
    _validate_string("RuleDrivenDecompositionChild.title", value.title)
    if not value.title.strip():
        raise IntentIRValidationError(
            "RuleDrivenDecompositionChild.title must not be empty"
        )
    if value.title != value.title.strip():
        raise IntentIRValidationError(
            "RuleDrivenDecompositionChild.title must be trimmed"
        )
    _validate_identifier("RuleDrivenDecompositionChild.role", value.role)
    _require_tuple("RuleDrivenDecompositionChild.scope_paths", value.scope_paths)
    if len(value.scope_paths) > RULE_DRIVEN_DECOMPOSITION_MAX_CHILD_SCOPE_PATHS:
        raise IntentIRValidationError(
            "RuleDrivenDecompositionChild.scope_paths exceeds "
            f"{RULE_DRIVEN_DECOMPOSITION_MAX_CHILD_SCOPE_PATHS} members"
        )
    normalized_paths = tuple(
        _normalize_scope_path(
            path, label=f"RuleDrivenDecompositionChild.scope_paths[{index}]"
        )
        for index, path in enumerate(value.scope_paths)
    )
    _require_unique(
        normalized_paths, "RuleDrivenDecompositionChild.scope_paths member"
    )
    if normalized_paths != value.scope_paths:
        raise IntentIRValidationError(
            "RuleDrivenDecompositionChild.scope_paths must be lexically normalized"
        )
    if list(value.scope_paths) != sorted(value.scope_paths):
        raise IntentIRValidationError(
            "RuleDrivenDecompositionChild.scope_paths must be sorted"
        )
    if parent_scope_paths is not None and not _child_scope_subset_of_parent(
        value.scope_paths, parent_scope_paths
    ):
        raise IntentIRValidationError(
            "RuleDrivenDecompositionChild.scope_paths must be within parent scope"
        )
    _require_tuple("RuleDrivenDecompositionChild.depends_on", value.depends_on)
    _validate_string_items(
        "RuleDrivenDecompositionChild.depends_on", value.depends_on
    )
    for dependency in value.depends_on:
        _validate_identifier("RuleDrivenDecompositionChild.depends_on member", dependency)
    _require_unique(
        value.depends_on, "RuleDrivenDecompositionChild.depends_on member"
    )
    if list(value.depends_on) != sorted(value.depends_on):
        raise IntentIRValidationError(
            "RuleDrivenDecompositionChild.depends_on must be sorted"
        )
    _require_tuple("RuleDrivenDecompositionChild.covers", value.covers)
    _validate_string_items("RuleDrivenDecompositionChild.covers", value.covers)
    for cover in value.covers:
        _validate_identifier("RuleDrivenDecompositionChild.covers member", cover)
    _require_unique(value.covers, "RuleDrivenDecompositionChild.covers member")
    if list(value.covers) != sorted(value.covers):
        raise IntentIRValidationError(
            "RuleDrivenDecompositionChild.covers must be sorted"
        )
    return value


def validate_rule_driven_objective_decomposition(
    value: RuleDrivenObjectiveDecomposition | Mapping[str, Any],
) -> RuleDrivenObjectiveDecomposition:
    """Validate and return a :class:`RuleDrivenObjectiveDecomposition`."""

    if isinstance(value, Mapping):
        value = RuleDrivenObjectiveDecomposition.from_dict(value)
    if not isinstance(value, RuleDrivenObjectiveDecomposition):
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition mappings require from_dict or a typed value"
        )
    if value.schema_version != RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA_VERSION:
        raise IntentIRValidationError(
            "Unsupported RuleDrivenObjectiveDecomposition schema_version: "
            f"{value.schema_version!r}"
        )
    if value.decomposer_id != RULE_DRIVEN_OBJECTIVE_DECOMPOSER_ID:
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.decomposer_id is unsupported: "
            f"{value.decomposer_id!r}"
        )
    if value.decomposer_version != RULE_DRIVEN_OBJECTIVE_DECOMPOSER_VERSION:
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.decomposer_version is unsupported: "
            f"{value.decomposer_version!r}"
        )
    _validate_identifier(
        "RuleDrivenObjectiveDecomposition.intent_id", value.intent_id
    )
    _validate_sha256(
        "RuleDrivenObjectiveDecomposition.intent_sha256", value.intent_sha256
    )
    _validate_sha256(
        "RuleDrivenObjectiveDecomposition.idea_sha256", value.idea_sha256
    )
    _validate_sha256(
        "RuleDrivenObjectiveDecomposition.normalization_sha256",
        value.normalization_sha256,
    )
    _validate_string(
        "RuleDrivenObjectiveDecomposition.repository_id", value.repository_id
    )
    if value.repository_id:
        _validate_identifier(
            "RuleDrivenObjectiveDecomposition.repository_id",
            value.repository_id,
        )
    _validate_string(
        "RuleDrivenObjectiveDecomposition.board_namespace", value.board_namespace
    )
    if value.board_namespace:
        _validate_identifier(
            "RuleDrivenObjectiveDecomposition.board_namespace",
            value.board_namespace,
        )
    objective_class = _KNOWN_OBJECTIVE_CLASS_BY_VALUE.get(value.objective_class)
    if objective_class is None:
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.objective_class is unsupported: "
            f"{value.objective_class!r}"
        )
    _validate_string(
        "RuleDrivenObjectiveDecomposition.matched_rule_id", value.matched_rule_id
    )
    if value.matched:
        _validate_identifier(
            "RuleDrivenObjectiveDecomposition.matched_rule_id",
            value.matched_rule_id,
        )
        if objective_class is KnownObjectiveClass.UNKNOWN:
            raise IntentIRValidationError(
                "RuleDrivenObjectiveDecomposition cannot match the unknown class"
            )
    elif value.matched_rule_id:
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.matched_rule_id must be empty when unmatched"
        )
    _validate_identifier(
        "RuleDrivenObjectiveDecomposition.reason_code", value.reason_code
    )
    _require_tuple(
        "RuleDrivenObjectiveDecomposition.scope_paths", value.scope_paths
    )
    if len(value.scope_paths) > DETERMINISTIC_NORMALIZATION_MAX_SCOPE_PATHS:
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.scope_paths exceeds "
            f"{DETERMINISTIC_NORMALIZATION_MAX_SCOPE_PATHS} members"
        )
    normalized_paths = tuple(
        _normalize_scope_path(
            path, label=f"RuleDrivenObjectiveDecomposition.scope_paths[{index}]"
        )
        for index, path in enumerate(value.scope_paths)
    )
    _require_unique(
        normalized_paths, "RuleDrivenObjectiveDecomposition.scope_paths member"
    )
    if normalized_paths != value.scope_paths:
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.scope_paths must be lexically normalized"
        )
    if list(value.scope_paths) != sorted(value.scope_paths):
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.scope_paths must be sorted"
        )
    _require_tuple("RuleDrivenObjectiveDecomposition.children", value.children)
    if len(value.children) > RULE_DRIVEN_DECOMPOSITION_MAX_CHILDREN:
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.children exceeds "
            f"{RULE_DRIVEN_DECOMPOSITION_MAX_CHILDREN} members"
        )
    if value.truncated and len(value.children) < RULE_DRIVEN_DECOMPOSITION_MAX_CHILDREN:
        # Truncation is only meaningful at the declared child cap.
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.truncated requires a full child cap"
        )
    validated_children = tuple(
        validate_rule_driven_decomposition_child(
            child, parent_scope_paths=value.scope_paths
        )
        for child in value.children
    )
    if validated_children != value.children:
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.children must already be validated shape"
        )
    child_ids = [child.child_id for child in value.children]
    if list(child_ids) != sorted(child_ids):
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.children must be sorted by child_id"
        )
    derived_edges = _validate_dependency_dag(value.children)
    _require_tuple(
        "RuleDrivenObjectiveDecomposition.dependency_edges", value.dependency_edges
    )
    normalized_edges = tuple(
        (str(edge[0]), str(edge[1])) for edge in value.dependency_edges
    )
    for index, edge in enumerate(normalized_edges):
        if len(edge) != 2:
            raise IntentIRValidationError(
                "RuleDrivenObjectiveDecomposition.dependency_edges members must be pairs"
            )
        _validate_identifier(
            f"RuleDrivenObjectiveDecomposition.dependency_edges[{index}][0]",
            edge[0],
        )
        _validate_identifier(
            f"RuleDrivenObjectiveDecomposition.dependency_edges[{index}][1]",
            edge[1],
        )
    if normalized_edges != tuple(sorted(normalized_edges)):
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.dependency_edges must be sorted"
        )
    if normalized_edges != derived_edges:
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.dependency_edges must match children depends_on"
        )
    if not value.matched and value.children:
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition unmatched results must not invent children"
        )
    _require_tuple(
        "RuleDrivenObjectiveDecomposition.available_capability_ids",
        value.available_capability_ids,
    )
    _validate_string_items(
        "RuleDrivenObjectiveDecomposition.available_capability_ids",
        value.available_capability_ids,
    )
    for capability_id in value.available_capability_ids:
        _validate_identifier(
            "RuleDrivenObjectiveDecomposition.available_capability_ids member",
            capability_id,
        )
    _require_unique(
        value.available_capability_ids,
        "RuleDrivenObjectiveDecomposition.available_capability_ids member",
    )
    if list(value.available_capability_ids) != sorted(value.available_capability_ids):
        raise IntentIRValidationError(
            "RuleDrivenObjectiveDecomposition.available_capability_ids must be sorted"
        )
    _validate_string(
        "RuleDrivenObjectiveDecomposition.repository_analysis_cid",
        value.repository_analysis_cid,
    )
    if value.repository_analysis_cid:
        _validate_identifier(
            "RuleDrivenObjectiveDecomposition.repository_analysis_cid",
            value.repository_analysis_cid,
        )
    return value


def decompose_supervisor_objective_by_rules(
    normalization: DeterministicObjectiveNormalization | Mapping[str, Any],
    *,
    objective_class: str | KnownObjectiveClass | None = None,
    available_capability_ids: Sequence[str] = (),
    repository_analysis_cid: str = "",
) -> RuleDrivenObjectiveDecomposition:
    """Apply closed rule/template decomposition to one normalized objective.

    This is a thin extension of the existing datasets-owned intent contracts:
    it reuses :func:`validate_deterministic_objective_normalization`, matches a
    known objective class, and expands a bounded child-fragment DAG.  It does
    not create a competing Intent IR document, planner, or admission authority.
    Unknown classes fail closed with empty children so residuals stay with the
    later unresolved-question / residual stages.
    """

    if isinstance(normalization, Mapping):
        forbidden = sorted(
            key
            for key in normalization
            if key in RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_FORBIDDEN_FIELDS
            or key in DETERMINISTIC_NORMALIZATION_FORBIDDEN_FIELDS
        )
        if forbidden:
            raise IntentIRValidationError(
                "rule-driven decomposition rejects authority/path escapes: "
                + ", ".join(forbidden)
            )
    validated = validate_deterministic_objective_normalization(normalization)
    requested_class = _coerce_known_objective_class(objective_class)
    rule, selected_class, reason_code = _select_known_objective_class_rule(
        objective_class=requested_class,
        tags=validated.tags,
    )
    if isinstance(available_capability_ids, (str, bytes, bytearray)) or not isinstance(
        available_capability_ids, Sequence
    ):
        raise IntentIRValidationError(
            "available_capability_ids must be a sequence of strings"
        )
    capability_ids = tuple(
        sorted(
            {
                item.strip()
                for item in available_capability_ids
                if isinstance(item, str) and item.strip()
            }
        )
    )
    for capability_id in capability_ids:
        _validate_identifier("available_capability_ids member", capability_id)
    if repository_analysis_cid is not None and not isinstance(
        repository_analysis_cid, str
    ):
        raise IntentIRValidationError("repository_analysis_cid must be a string")
    analysis_cid = repository_analysis_cid.strip() if repository_analysis_cid else ""
    if analysis_cid:
        _validate_identifier("repository_analysis_cid", analysis_cid)

    children: list[RuleDrivenDecompositionChild] = []
    truncated = False
    matched = False
    matched_rule_id = ""
    if rule is not None:
        matched = True
        matched_rule_id = rule.rule_id
        parent_scope = validated.scope_paths
        for template in rule.child_templates:
            if len(children) >= RULE_DRIVEN_DECOMPOSITION_MAX_CHILDREN:
                truncated = True
                break
            suffix = str(template.get("child_id_suffix") or "").strip()
            if not suffix:
                raise IntentIRValidationError(
                    "known objective class rule child template missing child_id_suffix"
                )
            child_id = f"{validated.intent_id}:{suffix}"
            depends_suffixes = tuple(
                sorted(
                    {
                        str(item).strip()
                        for item in template.get("depends_on", ())
                        if str(item).strip()
                    }
                )
            )
            depends_on = tuple(
                f"{validated.intent_id}:{item}" for item in depends_suffixes
            )
            covers = tuple(
                sorted(
                    {
                        str(item).strip()
                        for item in template.get("covers", ())
                        if str(item).strip()
                    }
                )
            )
            template_scope = template.get("scope_paths")
            if template_scope is None:
                child_scope = parent_scope
            else:
                if isinstance(template_scope, str) or not isinstance(
                    template_scope, Iterable
                ):
                    raise IntentIRValidationError(
                        "child template scope_paths must be an iterable of strings"
                    )
                child_scope = tuple(
                    sorted(
                        {
                            _normalize_scope_path(
                                path, label="child template scope_paths"
                            )
                            for path in template_scope
                        }
                    )
                )
                if not _child_scope_subset_of_parent(child_scope, parent_scope):
                    raise IntentIRValidationError(
                        "child template scope_paths escape parent scope"
                    )
            children.append(
                RuleDrivenDecompositionChild(
                    child_id=child_id,
                    title=str(template.get("title") or "").strip(),
                    role=str(template.get("role") or "").strip(),
                    scope_paths=child_scope,
                    depends_on=depends_on,
                    covers=covers,
                )
            )
        children.sort(key=lambda item: item.child_id)

    dependency_edges = (
        _validate_dependency_dag(children) if children else tuple()
    )
    result = RuleDrivenObjectiveDecomposition(
        intent_id=validated.intent_id,
        intent_sha256=validated.intent_sha256,
        idea_sha256=validated.idea_sha256,
        normalization_sha256=validated.normalization_sha256,
        repository_id=validated.repository_id,
        board_namespace=validated.board_namespace,
        objective_class=selected_class.value,
        matched_rule_id=matched_rule_id,
        matched=matched,
        truncated=truncated,
        reason_code=reason_code,
        scope_paths=validated.scope_paths,
        children=tuple(children),
        dependency_edges=dependency_edges,
        available_capability_ids=capability_ids,
        repository_analysis_cid=analysis_cid,
    )
    return validate_rule_driven_objective_decomposition(result)


class MinimumSpecialistCapability(str, Enum):
    """Smallest specialist class permitted to answer one unresolved question.

    Values are advisory routing floors only.  Recording a capability does not
    dispatch a model, execute tools, or grant completion authority.
    """

    LOCAL_SMALL_SPECIALIST = "local_small_specialist_model"
    LOCAL_OR_REMOTE_MEDIUM = "local_or_remote_medium_model"
    REMOTE_STRONG_OR_FRONTIER = "remote_strong_or_frontier_model"
    HUMAN_DECISION = "human_decision"


class AdmissibleDecisionImpact(str, Enum):
    """Closed route outcomes that an answer may change.

    Mirrors the deterministic-first ladder outcomes so this contract does not
    invent a competing routing authority.
    """

    DETERMINISTIC_ONLY = "deterministic_only"
    SMALL_LOCAL_MODEL = "small_local_model"
    MEDIUM_MODEL = "medium_model"
    FRONTIER_MODEL = "frontier_model"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


def _normalize_question_text(value: Any, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise IntentIRValidationError(f"{label} must be a string")
    text = " ".join(value.split())
    if not text:
        raise IntentIRValidationError(f"{label} must not be empty")
    if len(text) > maximum:
        raise IntentIRValidationError(f"{label} exceeds {maximum} characters")
    return text


def _canonical_evidence_texts(
    value: Any,
    *,
    label: str,
    minimum_items: int = 0,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Iterable):
        raise IntentIRValidationError(f"{label} must be an iterable of strings")
    items = tuple(
        _normalize_question_text(
            item,
            label=f"{label} member",
            maximum=UNRESOLVED_QUESTION_MAX_EVIDENCE_CHARS,
        )
        for item in value
    )
    if not minimum_items <= len(items) <= UNRESOLVED_QUESTION_MAX_EVIDENCE_ITEMS:
        raise IntentIRValidationError(
            f"{label} must contain from {minimum_items} through "
            f"{UNRESOLVED_QUESTION_MAX_EVIDENCE_ITEMS} items"
        )
    _require_unique(items, f"{label} member")
    return tuple(sorted(items))


def _canonical_decision_impacts(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Iterable):
        raise IntentIRValidationError(
            "candidate_decisions_answer_could_change must be an iterable of strings"
        )
    allowed = {item.value for item in AdmissibleDecisionImpact}
    decisions: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise IntentIRValidationError(
                "candidate_decisions_answer_could_change contains a non-admissible decision"
            )
        decisions.append(item)
    if not 2 <= len(decisions) <= len(AdmissibleDecisionImpact):
        raise IntentIRValidationError(
            "candidate_decisions_answer_could_change must name at least two "
            "admissible decisions"
        )
    _require_unique(decisions, "candidate_decisions_answer_could_change member")
    return tuple(sorted(decisions))


def _canonical_response_enum(value: Any) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        if set(value) != {"type", "enum"}:
            raise IntentIRValidationError(
                "response_schema must be the closed string-enum response schema"
            )
        if value.get("type") != "string":
            raise IntentIRValidationError("response_schema.type must be 'string'")
        raw = value.get("enum")
    else:
        raw = value
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Iterable):
        raise IntentIRValidationError("response_schema.enum must be an iterable of strings")
    answers = tuple(
        _normalize_question_text(
            item,
            label="response_schema.enum member",
            maximum=UNRESOLVED_QUESTION_MAX_RESPONSE_VALUE_CHARS,
        )
        for item in raw
    )
    if not 2 <= len(answers) <= UNRESOLVED_QUESTION_MAX_RESPONSE_VALUES:
        raise IntentIRValidationError(
            "response_schema.enum must contain from 2 through "
            f"{UNRESOLVED_QUESTION_MAX_RESPONSE_VALUES} values"
        )
    _require_unique(answers, "response_schema.enum member")
    return tuple(sorted(answers))


def _coerce_minimum_specialist_capability(value: Any) -> str:
    if isinstance(value, MinimumSpecialistCapability):
        return value.value
    if not isinstance(value, str):
        raise IntentIRValidationError("minimum_specialist_capability must be a string")
    text = value.strip()
    allowed = {item.value for item in MinimumSpecialistCapability}
    if text not in allowed:
        raise IntentIRValidationError(
            f"minimum_specialist_capability is unsupported: {text!r}"
        )
    return text


def unresolved_question_identity_for(payload: Mapping[str, Any]) -> str:
    """Derive the sealed identity from a validated non-identity question body."""

    if not isinstance(payload, Mapping):
        raise IntentIRValidationError("unresolved question payload must be a mapping")
    body = {
        "candidate_decisions_answer_could_change": list(
            payload.get("candidate_decisions_answer_could_change", ())
        ),
        "context_budget": payload.get("context_budget", 0),
        "context_pack_hint": payload.get("context_pack_hint", ""),
        "evidence_available": list(payload.get("evidence_available", ())),
        "evidence_missing": list(payload.get("evidence_missing", ())),
        "exact_question": payload.get("exact_question", ""),
        "minimum_specialist_capability": payload.get(
            "minimum_specialist_capability", ""
        ),
        "response_schema": {
            "enum": list(
                payload.get("response_schema", {}).get("enum", ())
                if isinstance(payload.get("response_schema"), Mapping)
                else payload.get("response_enum", ())
            ),
            "type": "string",
        },
        "why_prior_deterministic_stages_could_not_resolve": payload.get(
            "why_prior_deterministic_stages_could_not_resolve", ""
        ),
    }
    canonical = json.dumps(
        body,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class UnresolvedQuestion:
    """One named unresolved semantic question after deterministic stages.

    Parallel to other datasets-owned intent carriers: it records a sealed
    question identity, evidence gap, specialist floor, and typed response
    shape.  Typed answers cannot execute tools.  Accelerate alone admits
    ContextPacks, model dispatch, and operational completion.
    """

    question_id: str
    exact_question: str
    why_prior_deterministic_stages_could_not_resolve: str
    evidence_available: tuple[str, ...]
    evidence_missing: tuple[str, ...]
    candidate_decisions_answer_could_change: tuple[str, ...]
    minimum_specialist_capability: str
    response_enum: tuple[str, ...]
    context_budget: int = 4096
    context_pack_hint: str = ""
    schema_version: str = UNRESOLVED_QUESTION_SCHEMA_VERSION

    def validate(self) -> None:
        validate_unresolved_question(self)

    @property
    def schema(self) -> str:
        return UNRESOLVED_QUESTION_SCHEMA

    @property
    def authority(self) -> str:
        return UNRESOLVED_QUESTION_AUTHORITY

    @property
    def is_completion_authority(self) -> bool:
        return False

    @property
    def can_execute_tools(self) -> bool:
        return False

    @property
    def callers_supply_authoritative_policy(self) -> bool:
        return False

    @property
    def response_schema(self) -> dict[str, Any]:
        return {"type": "string", "enum": list(self.response_enum)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": UNRESOLVED_QUESTION_AUTHORITY,
            "candidate_decisions_answer_could_change": list(
                self.candidate_decisions_answer_could_change
            ),
            "can_execute_tools": False,
            "context_budget": self.context_budget,
            "context_pack_hint": self.context_pack_hint,
            "evidence_available": list(self.evidence_available),
            "evidence_missing": list(self.evidence_missing),
            "exact_question": self.exact_question,
            "minimum_specialist_capability": self.minimum_specialist_capability,
            "question_id": self.question_id,
            "response_schema": self.response_schema,
            "schema": UNRESOLVED_QUESTION_SCHEMA,
            "schema_version": self.schema_version,
            "why_prior_deterministic_stages_could_not_resolve": (
                self.why_prior_deterministic_stages_could_not_resolve
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnresolvedQuestion":
        if not isinstance(value, Mapping):
            raise IntentIRValidationError("UnresolvedQuestion mapping must be a mapping")
        forbidden = sorted(
            key for key in value if key in UNRESOLVED_QUESTION_FORBIDDEN_FIELDS
        )
        if forbidden:
            raise IntentIRValidationError(
                "UnresolvedQuestion forbids authoritative/tool fields: "
                + ", ".join(forbidden)
            )
        allowed = {
            "authority",
            "candidate_decisions_answer_could_change",
            "can_execute_tools",
            "context_budget",
            "context_pack_hint",
            "evidence_available",
            "evidence_missing",
            "exact_question",
            "minimum_specialist_capability",
            "question_id",
            "response_enum",
            "response_schema",
            "schema",
            "schema_version",
            "why_prior_deterministic_stages_could_not_resolve",
        }
        unknown = sorted(key for key in value if key not in allowed)
        if unknown:
            raise IntentIRValidationError(
                "UnresolvedQuestion has unknown fields: " + ", ".join(unknown)
            )
        schema = value.get("schema", UNRESOLVED_QUESTION_SCHEMA)
        if schema != UNRESOLVED_QUESTION_SCHEMA:
            raise IntentIRValidationError(
                f"Unsupported UnresolvedQuestion schema: {schema!r}"
            )
        authority = value.get("authority", UNRESOLVED_QUESTION_AUTHORITY)
        if authority != UNRESOLVED_QUESTION_AUTHORITY:
            raise IntentIRValidationError("UnresolvedQuestion cannot claim authority")
        if "can_execute_tools" in value and value.get("can_execute_tools") is not False:
            raise IntentIRValidationError(
                "UnresolvedQuestion typed output cannot execute tools"
            )
        if "response_schema" in value:
            response_enum = _canonical_response_enum(value.get("response_schema"))
        else:
            response_enum = _canonical_response_enum(value.get("response_enum", ()))
        context_budget = value.get("context_budget", 4096)
        if isinstance(context_budget, bool) or not isinstance(context_budget, int):
            raise IntentIRValidationError("context_budget must be an integer")
        return cls(
            question_id=str(value.get("question_id") or ""),
            exact_question=str(value.get("exact_question") or ""),
            why_prior_deterministic_stages_could_not_resolve=str(
                value.get("why_prior_deterministic_stages_could_not_resolve") or ""
            ),
            evidence_available=tuple(
                str(item) for item in value.get("evidence_available", ())
            ),
            evidence_missing=tuple(
                str(item) for item in value.get("evidence_missing", ())
            ),
            candidate_decisions_answer_could_change=tuple(
                str(item)
                for item in value.get("candidate_decisions_answer_could_change", ())
            ),
            minimum_specialist_capability=str(
                value.get("minimum_specialist_capability") or ""
            ),
            response_enum=response_enum,
            context_budget=context_budget,
            context_pack_hint=str(value.get("context_pack_hint") or ""),
            schema_version=str(
                value.get("schema_version") or UNRESOLVED_QUESTION_SCHEMA_VERSION
            ),
        )


def validate_unresolved_question(
    value: UnresolvedQuestion | Mapping[str, Any],
) -> UnresolvedQuestion:
    """Validate and return one sealed :class:`UnresolvedQuestion`."""

    if isinstance(value, Mapping):
        value = UnresolvedQuestion.from_dict(value)
    if not isinstance(value, UnresolvedQuestion):
        raise IntentIRValidationError(
            "UnresolvedQuestion mappings require from_dict or a typed value"
        )
    if value.schema_version != UNRESOLVED_QUESTION_SCHEMA_VERSION:
        raise IntentIRValidationError(
            "Unsupported UnresolvedQuestion schema_version: "
            f"{value.schema_version!r}"
        )
    exact = _normalize_question_text(
        value.exact_question,
        label="UnresolvedQuestion.exact_question",
        maximum=UNRESOLVED_QUESTION_MAX_TEXT_CHARS,
    )
    reason = _normalize_question_text(
        value.why_prior_deterministic_stages_could_not_resolve,
        label="UnresolvedQuestion.why_prior_deterministic_stages_could_not_resolve",
        maximum=UNRESOLVED_QUESTION_MAX_REASON_CHARS,
    )
    available = _canonical_evidence_texts(
        value.evidence_available,
        label="UnresolvedQuestion.evidence_available",
    )
    missing = _canonical_evidence_texts(
        value.evidence_missing,
        label="UnresolvedQuestion.evidence_missing",
        minimum_items=1,
    )
    if set(available).intersection(missing):
        raise IntentIRValidationError(
            "evidence_available and evidence_missing must not overlap"
        )
    impacts = _canonical_decision_impacts(
        value.candidate_decisions_answer_could_change
    )
    capability = _coerce_minimum_specialist_capability(
        value.minimum_specialist_capability
    )
    response_enum = _canonical_response_enum(value.response_enum)
    if not (
        1 <= value.context_budget <= UNRESOLVED_QUESTION_MAX_CONTEXT_BUDGET
    ):
        raise IntentIRValidationError(
            "context_budget must be an integer from 1 through "
            f"{UNRESOLVED_QUESTION_MAX_CONTEXT_BUDGET}"
        )
    hint = value.context_pack_hint.strip() if isinstance(value.context_pack_hint, str) else ""
    if value.context_pack_hint is not None and not isinstance(
        value.context_pack_hint, str
    ):
        raise IntentIRValidationError("context_pack_hint must be a string")
    if hint:
        _validate_identifier("UnresolvedQuestion.context_pack_hint", hint)
    identity_payload = {
        "candidate_decisions_answer_could_change": impacts,
        "context_budget": value.context_budget,
        "context_pack_hint": hint,
        "evidence_available": available,
        "evidence_missing": missing,
        "exact_question": exact,
        "minimum_specialist_capability": capability,
        "response_schema": {"type": "string", "enum": list(response_enum)},
        "why_prior_deterministic_stages_could_not_resolve": reason,
    }
    expected_id = unresolved_question_identity_for(identity_payload)
    if not isinstance(value.question_id, str) or not _QUESTION_IDENTITY_RE.fullmatch(
        value.question_id
    ):
        raise IntentIRValidationError(
            "UnresolvedQuestion.question_id must be a sha256 identity"
        )
    if value.question_id != expected_id:
        raise IntentIRValidationError(
            "UnresolvedQuestion.question_id does not match the canonical question"
        )
    if (
        exact != value.exact_question
        or reason != value.why_prior_deterministic_stages_could_not_resolve
        or available != value.evidence_available
        or missing != value.evidence_missing
        or impacts != value.candidate_decisions_answer_could_change
        or capability != value.minimum_specialist_capability
        or response_enum != value.response_enum
        or hint != value.context_pack_hint
    ):
        return UnresolvedQuestion(
            question_id=expected_id,
            exact_question=exact,
            why_prior_deterministic_stages_could_not_resolve=reason,
            evidence_available=available,
            evidence_missing=missing,
            candidate_decisions_answer_could_change=impacts,
            minimum_specialist_capability=capability,
            response_enum=response_enum,
            context_budget=value.context_budget,
            context_pack_hint=hint,
            schema_version=value.schema_version,
        )
    return value


def build_unresolved_question(
    *,
    exact_question: str,
    why_prior_deterministic_stages_could_not_resolve: str,
    evidence_available: Sequence[str] = (),
    evidence_missing: Sequence[str],
    candidate_decisions_answer_could_change: Sequence[str],
    minimum_specialist_capability: str | MinimumSpecialistCapability,
    response_enum: Sequence[str] | Mapping[str, Any],
    context_budget: int = 4096,
    context_pack_hint: str = "",
    question_id: str | None = None,
) -> UnresolvedQuestion:
    """Build one sealed unresolved question and derive its identity.

    Callers may supply ``question_id`` only when it equals the canonical
    identity.  This prevents caller-selected unrelated identities while still
    allowing rehydration of already-sealed records.
    """

    if isinstance(response_enum, Mapping):
        enum_values = _canonical_response_enum(response_enum)
    else:
        enum_values = _canonical_response_enum(response_enum)
    placeholder = UnresolvedQuestion(
        question_id="sha256:" + ("0" * 64),
        exact_question=exact_question,
        why_prior_deterministic_stages_could_not_resolve=(
            why_prior_deterministic_stages_could_not_resolve
        ),
        evidence_available=tuple(evidence_available),
        evidence_missing=tuple(evidence_missing),
        candidate_decisions_answer_could_change=tuple(
            candidate_decisions_answer_could_change
        ),
        minimum_specialist_capability=(
            minimum_specialist_capability.value
            if isinstance(minimum_specialist_capability, MinimumSpecialistCapability)
            else str(minimum_specialist_capability)
        ),
        response_enum=enum_values,
        context_budget=context_budget,
        context_pack_hint=context_pack_hint,
    )
    # Validate shape without identity, then seal.
    exact = _normalize_question_text(
        placeholder.exact_question,
        label="exact_question",
        maximum=UNRESOLVED_QUESTION_MAX_TEXT_CHARS,
    )
    reason = _normalize_question_text(
        placeholder.why_prior_deterministic_stages_could_not_resolve,
        label="why_prior_deterministic_stages_could_not_resolve",
        maximum=UNRESOLVED_QUESTION_MAX_REASON_CHARS,
    )
    available = _canonical_evidence_texts(
        placeholder.evidence_available, label="evidence_available"
    )
    missing = _canonical_evidence_texts(
        placeholder.evidence_missing, label="evidence_missing", minimum_items=1
    )
    if set(available).intersection(missing):
        raise IntentIRValidationError(
            "evidence_available and evidence_missing must not overlap"
        )
    impacts = _canonical_decision_impacts(
        placeholder.candidate_decisions_answer_could_change
    )
    capability = _coerce_minimum_specialist_capability(
        placeholder.minimum_specialist_capability
    )
    if not (
        1 <= placeholder.context_budget <= UNRESOLVED_QUESTION_MAX_CONTEXT_BUDGET
    ):
        raise IntentIRValidationError(
            "context_budget must be an integer from 1 through "
            f"{UNRESOLVED_QUESTION_MAX_CONTEXT_BUDGET}"
        )
    hint = placeholder.context_pack_hint.strip()
    if hint:
        _validate_identifier("context_pack_hint", hint)
    identity_payload = {
        "candidate_decisions_answer_could_change": impacts,
        "context_budget": placeholder.context_budget,
        "context_pack_hint": hint,
        "evidence_available": available,
        "evidence_missing": missing,
        "exact_question": exact,
        "minimum_specialist_capability": capability,
        "response_schema": {"type": "string", "enum": list(enum_values)},
        "why_prior_deterministic_stages_could_not_resolve": reason,
    }
    identity = unresolved_question_identity_for(identity_payload)
    if question_id is not None and question_id != identity:
        raise IntentIRValidationError(
            "provided question_id does not match canonical question"
        )
    return validate_unresolved_question(
        UnresolvedQuestion(
            question_id=identity,
            exact_question=exact,
            why_prior_deterministic_stages_could_not_resolve=reason,
            evidence_available=available,
            evidence_missing=missing,
            candidate_decisions_answer_could_change=impacts,
            minimum_specialist_capability=capability,
            response_enum=enum_values,
            context_budget=placeholder.context_budget,
            context_pack_hint=hint,
        )
    )


@dataclass(frozen=True, slots=True)
class UnresolvedQuestionCapture:
    """Semantic-only capture of named unresolved questions for one objective.

    Parallel to :class:`RuleDrivenObjectiveDecomposition`.  The carrier binds
    validated intent/normalization digests to a bounded, sorted set of sealed
    questions.  It does not create a competing Intent IR, planner, or admission
    authority, and typed specialist answers cannot execute tools.
    """

    intent_id: str
    intent_sha256: str
    idea_sha256: str
    normalization_sha256: str
    repository_id: str
    board_namespace: str
    questions: tuple[UnresolvedQuestion, ...] = ()
    decomposition_sha256: str = ""
    truncated: bool = False
    reason_code: str = "explicit_questions"
    capture_id: str = UNRESOLVED_QUESTION_CAPTURE_ID
    capture_version: str = UNRESOLVED_QUESTION_CAPTURE_VERSION
    schema_version: str = UNRESOLVED_QUESTION_CAPTURE_SCHEMA_VERSION

    def validate(self) -> None:
        validate_unresolved_question_capture(self)

    @property
    def schema(self) -> str:
        return UNRESOLVED_QUESTION_CAPTURE_SCHEMA

    @property
    def authority(self) -> str:
        return UNRESOLVED_QUESTION_AUTHORITY

    @property
    def is_completion_authority(self) -> bool:
        return False

    @property
    def can_execute_tools(self) -> bool:
        return False

    @property
    def callers_supply_authoritative_policy(self) -> bool:
        return False

    @property
    def capture_sha256(self) -> str:
        payload = self.to_dict()
        canonical = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": UNRESOLVED_QUESTION_AUTHORITY,
            "board_namespace": self.board_namespace,
            "can_execute_tools": False,
            "capture_id": self.capture_id,
            "capture_version": self.capture_version,
            "decomposition_sha256": self.decomposition_sha256,
            "idea_sha256": self.idea_sha256,
            "intent_id": self.intent_id,
            "intent_sha256": self.intent_sha256,
            "normalization_sha256": self.normalization_sha256,
            "questions": [question.to_dict() for question in self.questions],
            "reason_code": self.reason_code,
            "repository_id": self.repository_id,
            "schema": UNRESOLVED_QUESTION_CAPTURE_SCHEMA,
            "schema_version": self.schema_version,
            "truncated": self.truncated,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnresolvedQuestionCapture":
        if not isinstance(value, Mapping):
            raise IntentIRValidationError(
                "UnresolvedQuestionCapture mapping must be a mapping"
            )
        forbidden = sorted(
            key for key in value if key in UNRESOLVED_QUESTION_FORBIDDEN_FIELDS
        )
        if forbidden:
            raise IntentIRValidationError(
                "UnresolvedQuestionCapture forbids authoritative/tool fields: "
                + ", ".join(forbidden)
            )
        allowed = {
            "authority",
            "board_namespace",
            "can_execute_tools",
            "capture_id",
            "capture_sha256",
            "capture_version",
            "decomposition_sha256",
            "idea_sha256",
            "intent_id",
            "intent_sha256",
            "normalization_sha256",
            "questions",
            "reason_code",
            "repository_id",
            "schema",
            "schema_version",
            "truncated",
        }
        unknown = sorted(key for key in value if key not in allowed)
        if unknown:
            raise IntentIRValidationError(
                "UnresolvedQuestionCapture has unknown fields: " + ", ".join(unknown)
            )
        schema = value.get("schema", UNRESOLVED_QUESTION_CAPTURE_SCHEMA)
        if schema != UNRESOLVED_QUESTION_CAPTURE_SCHEMA:
            raise IntentIRValidationError(
                f"Unsupported UnresolvedQuestionCapture schema: {schema!r}"
            )
        authority = value.get("authority", UNRESOLVED_QUESTION_AUTHORITY)
        if authority != UNRESOLVED_QUESTION_AUTHORITY:
            raise IntentIRValidationError(
                "UnresolvedQuestionCapture cannot claim authority"
            )
        if "can_execute_tools" in value and value.get("can_execute_tools") is not False:
            raise IntentIRValidationError(
                "UnresolvedQuestionCapture typed output cannot execute tools"
            )
        questions_raw = value.get("questions", ())
        if isinstance(questions_raw, (str, bytes, bytearray)) or not isinstance(
            questions_raw, Iterable
        ):
            raise IntentIRValidationError(
                "UnresolvedQuestionCapture.questions must be an iterable"
            )
        questions: list[UnresolvedQuestion] = []
        for item in questions_raw:
            if isinstance(item, UnresolvedQuestion):
                questions.append(item)
            elif isinstance(item, Mapping):
                questions.append(UnresolvedQuestion.from_dict(item))
            else:
                raise IntentIRValidationError(
                    "UnresolvedQuestionCapture.questions members must be mappings"
                )
        truncated = value.get("truncated", False)
        if not isinstance(truncated, bool):
            raise IntentIRValidationError(
                "UnresolvedQuestionCapture.truncated must be a bool"
            )
        return cls(
            intent_id=str(value.get("intent_id") or ""),
            intent_sha256=str(value.get("intent_sha256") or ""),
            idea_sha256=str(value.get("idea_sha256") or ""),
            normalization_sha256=str(value.get("normalization_sha256") or ""),
            repository_id=str(value.get("repository_id") or ""),
            board_namespace=str(value.get("board_namespace") or ""),
            questions=tuple(questions),
            decomposition_sha256=str(value.get("decomposition_sha256") or ""),
            truncated=truncated,
            reason_code=str(value.get("reason_code") or ""),
            capture_id=str(value.get("capture_id") or UNRESOLVED_QUESTION_CAPTURE_ID),
            capture_version=str(
                value.get("capture_version") or UNRESOLVED_QUESTION_CAPTURE_VERSION
            ),
            schema_version=str(
                value.get("schema_version")
                or UNRESOLVED_QUESTION_CAPTURE_SCHEMA_VERSION
            ),
        )


def validate_unresolved_question_capture(
    value: UnresolvedQuestionCapture | Mapping[str, Any],
) -> UnresolvedQuestionCapture:
    """Validate and return a :class:`UnresolvedQuestionCapture`."""

    if isinstance(value, Mapping):
        value = UnresolvedQuestionCapture.from_dict(value)
    if not isinstance(value, UnresolvedQuestionCapture):
        raise IntentIRValidationError(
            "UnresolvedQuestionCapture mappings require from_dict or a typed value"
        )
    if value.schema_version != UNRESOLVED_QUESTION_CAPTURE_SCHEMA_VERSION:
        raise IntentIRValidationError(
            "Unsupported UnresolvedQuestionCapture schema_version: "
            f"{value.schema_version!r}"
        )
    if value.capture_id != UNRESOLVED_QUESTION_CAPTURE_ID:
        raise IntentIRValidationError(
            "UnresolvedQuestionCapture.capture_id is unsupported: "
            f"{value.capture_id!r}"
        )
    if value.capture_version != UNRESOLVED_QUESTION_CAPTURE_VERSION:
        raise IntentIRValidationError(
            "UnresolvedQuestionCapture.capture_version is unsupported: "
            f"{value.capture_version!r}"
        )
    _validate_identifier("UnresolvedQuestionCapture.intent_id", value.intent_id)
    _validate_sha256(
        "UnresolvedQuestionCapture.intent_sha256", value.intent_sha256
    )
    _validate_sha256("UnresolvedQuestionCapture.idea_sha256", value.idea_sha256)
    _validate_sha256(
        "UnresolvedQuestionCapture.normalization_sha256",
        value.normalization_sha256,
    )
    if value.decomposition_sha256:
        _validate_sha256(
            "UnresolvedQuestionCapture.decomposition_sha256",
            value.decomposition_sha256,
        )
    _validate_string(
        "UnresolvedQuestionCapture.repository_id", value.repository_id
    )
    if value.repository_id:
        _validate_identifier(
            "UnresolvedQuestionCapture.repository_id", value.repository_id
        )
    _validate_string(
        "UnresolvedQuestionCapture.board_namespace", value.board_namespace
    )
    if value.board_namespace:
        _validate_identifier(
            "UnresolvedQuestionCapture.board_namespace", value.board_namespace
        )
    _validate_non_empty_string(
        "UnresolvedQuestionCapture.reason_code", value.reason_code
    )
    _require_tuple("UnresolvedQuestionCapture.questions", value.questions)
    if len(value.questions) > UNRESOLVED_QUESTION_MAX_QUESTIONS:
        raise IntentIRValidationError(
            "UnresolvedQuestionCapture.questions exceeds "
            f"{UNRESOLVED_QUESTION_MAX_QUESTIONS} members"
        )
    validated_questions = tuple(
        validate_unresolved_question(question) for question in value.questions
    )
    question_ids = [question.question_id for question in validated_questions]
    _require_unique(question_ids, "UnresolvedQuestionCapture.questions question_id")
    if question_ids != sorted(question_ids):
        raise IntentIRValidationError(
            "UnresolvedQuestionCapture.questions must be sorted by question_id"
        )
    if validated_questions != value.questions:
        return UnresolvedQuestionCapture(
            intent_id=value.intent_id,
            intent_sha256=value.intent_sha256,
            idea_sha256=value.idea_sha256,
            normalization_sha256=value.normalization_sha256,
            repository_id=value.repository_id,
            board_namespace=value.board_namespace,
            questions=validated_questions,
            decomposition_sha256=value.decomposition_sha256,
            truncated=value.truncated,
            reason_code=value.reason_code.strip(),
            capture_id=value.capture_id,
            capture_version=value.capture_version,
            schema_version=value.schema_version,
        )
    return value


def _question_from_decomposition_gap(
    decomposition: RuleDrivenObjectiveDecomposition,
) -> UnresolvedQuestion:
    reason_code = decomposition.reason_code or "unknown_objective_class"
    if decomposition.truncated:
        exact = (
            "Which residual child fragments remain after rule-driven decomposition "
            "truncation for this objective?"
        )
        reason = (
            "Rule-driven decomposition matched a known class but truncated the "
            "child-fragment DAG at the closed maximum."
        )
        missing = ("residual child fragment coverage",)
        impacts = (
            AdmissibleDecisionImpact.SMALL_LOCAL_MODEL.value,
            AdmissibleDecisionImpact.MEDIUM_MODEL.value,
        )
        capability = MinimumSpecialistCapability.LOCAL_SMALL_SPECIALIST
        answers = ("enumerate_residuals", "escalate_human")
    elif reason_code == "ambiguous_objective_class":
        exact = (
            "Which known objective class should resolve this ambiguous supervisor "
            "objective?"
        )
        reason = (
            "Deterministic tag matching ranked more than one known objective class "
            "with equal overlap."
        )
        missing = ("disambiguating objective-class evidence",)
        impacts = (
            AdmissibleDecisionImpact.DETERMINISTIC_ONLY.value,
            AdmissibleDecisionImpact.SMALL_LOCAL_MODEL.value,
            AdmissibleDecisionImpact.HUMAN_REVIEW_REQUIRED.value,
        )
        capability = MinimumSpecialistCapability.LOCAL_OR_REMOTE_MEDIUM
        answers = ("select_class", "mark_unknown", "escalate_human")
    else:
        exact = (
            "Which bounded specialist interpretation should cover the residual "
            "objective after deterministic stages failed to match a known class?"
        )
        reason = (
            "Rule-driven decomposition failed closed with empty children for an "
            "unknown or unmatched objective class."
        )
        missing = ("known objective-class template match",)
        impacts = (
            AdmissibleDecisionImpact.SMALL_LOCAL_MODEL.value,
            AdmissibleDecisionImpact.MEDIUM_MODEL.value,
            AdmissibleDecisionImpact.HUMAN_REVIEW_REQUIRED.value,
        )
        capability = MinimumSpecialistCapability.LOCAL_OR_REMOTE_MEDIUM
        answers = ("interpret_residual", "request_human", "abstain")
    available = (
        f"decomposition.reason_code:{reason_code}",
        f"objective_class:{decomposition.objective_class}",
    )
    return build_unresolved_question(
        exact_question=exact,
        why_prior_deterministic_stages_could_not_resolve=reason,
        evidence_available=available,
        evidence_missing=missing,
        candidate_decisions_answer_could_change=impacts,
        minimum_specialist_capability=capability,
        response_enum=answers,
        context_budget=4096,
        context_pack_hint="",
    )


def capture_unresolved_semantic_questions(
    normalization: DeterministicObjectiveNormalization | Mapping[str, Any],
    *,
    decomposition: RuleDrivenObjectiveDecomposition | Mapping[str, Any] | None = None,
    questions: Sequence[UnresolvedQuestion | Mapping[str, Any]] = (),
    context_pack_hint: str = "",
) -> UnresolvedQuestionCapture:
    """Capture named unresolved semantic questions after deterministic stages.

    This is a thin extension of the existing datasets-owned intent contracts:
    it reuses :func:`validate_deterministic_objective_normalization` and, when
    provided, :func:`validate_rule_driven_objective_decomposition`.  Explicit
    questions are sealed as-is.  When no explicit questions are supplied and
    decomposition failed closed, truncated, or remained unmatched, one named
    residual question is derived.  The capture does not dispatch specialists,
    execute tools, or create a competing planner subsystem.
    """

    if isinstance(normalization, Mapping):
        forbidden = sorted(
            key
            for key in normalization
            if key in UNRESOLVED_QUESTION_FORBIDDEN_FIELDS
            or key in DETERMINISTIC_NORMALIZATION_FORBIDDEN_FIELDS
        )
        if forbidden:
            raise IntentIRValidationError(
                "unresolved-question capture rejects authority/tool escapes: "
                + ", ".join(forbidden)
            )
    validated_normalization = validate_deterministic_objective_normalization(
        normalization
    )
    validated_decomposition: RuleDrivenObjectiveDecomposition | None = None
    decomposition_sha256 = ""
    if decomposition is not None:
        if isinstance(decomposition, Mapping):
            forbidden = sorted(
                key
                for key in decomposition
                if key in UNRESOLVED_QUESTION_FORBIDDEN_FIELDS
                or key in RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_FORBIDDEN_FIELDS
            )
            if forbidden:
                raise IntentIRValidationError(
                    "unresolved-question capture rejects authority/tool escapes: "
                    + ", ".join(forbidden)
                )
        validated_decomposition = validate_rule_driven_objective_decomposition(
            decomposition
        )
        if (
            validated_decomposition.intent_id != validated_normalization.intent_id
            or validated_decomposition.normalization_sha256
            != validated_normalization.normalization_sha256
        ):
            raise IntentIRValidationError(
                "decomposition does not bind the supplied normalization"
            )
        decomposition_sha256 = validated_decomposition.decomposition_sha256

    if isinstance(questions, (str, bytes, bytearray)) or not isinstance(
        questions, Sequence
    ):
        raise IntentIRValidationError("questions must be a sequence")
    sealed: list[UnresolvedQuestion] = []
    for item in questions:
        if isinstance(item, UnresolvedQuestion):
            sealed.append(validate_unresolved_question(item))
        elif isinstance(item, Mapping):
            payload = dict(item)
            if context_pack_hint and not payload.get("context_pack_hint"):
                payload["context_pack_hint"] = context_pack_hint
            if payload.get("question_id"):
                sealed.append(validate_unresolved_question(payload))
            else:
                sealed.append(
                    build_unresolved_question(
                        exact_question=str(payload.get("exact_question") or ""),
                        why_prior_deterministic_stages_could_not_resolve=str(
                            payload.get(
                                "why_prior_deterministic_stages_could_not_resolve"
                            )
                            or ""
                        ),
                        evidence_available=tuple(
                            str(entry)
                            for entry in payload.get("evidence_available", ())
                        ),
                        evidence_missing=tuple(
                            str(entry)
                            for entry in payload.get("evidence_missing", ())
                        ),
                        candidate_decisions_answer_could_change=tuple(
                            str(entry)
                            for entry in payload.get(
                                "candidate_decisions_answer_could_change", ()
                            )
                        ),
                        minimum_specialist_capability=str(
                            payload.get("minimum_specialist_capability") or ""
                        ),
                        response_enum=(
                            payload.get("response_schema")
                            if isinstance(payload.get("response_schema"), Mapping)
                            else payload.get("response_enum", ())
                        ),
                        context_budget=int(payload.get("context_budget", 4096)),
                        context_pack_hint=str(
                            payload.get("context_pack_hint") or context_pack_hint or ""
                        ),
                    )
                )
        else:
            raise IntentIRValidationError(
                "questions members must be UnresolvedQuestion values or mappings"
            )

    reason_code = "explicit_questions"
    truncated = False
    if not sealed and validated_decomposition is not None:
        if (
            not validated_decomposition.matched
            or validated_decomposition.truncated
            or validated_decomposition.objective_class
            == KnownObjectiveClass.UNKNOWN.value
        ):
            sealed.append(_question_from_decomposition_gap(validated_decomposition))
            reason_code = (
                "derived_from_decomposition:"
                + (validated_decomposition.reason_code or "unknown_objective_class")
            )
            truncated = validated_decomposition.truncated
        else:
            reason_code = "no_unresolved_questions"
    elif not sealed:
        reason_code = "no_unresolved_questions"

    if len(sealed) > UNRESOLVED_QUESTION_MAX_QUESTIONS:
        sealed = sealed[:UNRESOLVED_QUESTION_MAX_QUESTIONS]
        truncated = True
        reason_code = "truncated_questions"

    if context_pack_hint:
        hint = context_pack_hint.strip()
        _validate_identifier("context_pack_hint", hint)
        sealed = [
            build_unresolved_question(
                exact_question=question.exact_question,
                why_prior_deterministic_stages_could_not_resolve=(
                    question.why_prior_deterministic_stages_could_not_resolve
                ),
                evidence_available=question.evidence_available,
                evidence_missing=question.evidence_missing,
                candidate_decisions_answer_could_change=(
                    question.candidate_decisions_answer_could_change
                ),
                minimum_specialist_capability=question.minimum_specialist_capability,
                response_enum=question.response_enum,
                context_budget=question.context_budget,
                context_pack_hint=question.context_pack_hint or hint,
            )
            for question in sealed
        ]

    sealed.sort(key=lambda item: item.question_id)
    result = UnresolvedQuestionCapture(
        intent_id=validated_normalization.intent_id,
        intent_sha256=validated_normalization.intent_sha256,
        idea_sha256=validated_normalization.idea_sha256,
        normalization_sha256=validated_normalization.normalization_sha256,
        repository_id=validated_normalization.repository_id,
        board_namespace=validated_normalization.board_namespace,
        questions=tuple(sealed),
        decomposition_sha256=decomposition_sha256,
        truncated=truncated,
        reason_code=reason_code,
    )
    return validate_unresolved_question_capture(result)


__all__ = [
    "AdmissibleDecisionImpact",
    "CollectionSemantics",
    "DETERMINISTIC_NORMALIZATION_AUTHORITY",
    "DETERMINISTIC_NORMALIZATION_FORBIDDEN_FIELDS",
    "DETERMINISTIC_NORMALIZATION_MAX_SCOPE_PATHS",
    "DETERMINISTIC_NORMALIZATION_SCHEMA",
    "DETERMINISTIC_NORMALIZATION_SCHEMA_VERSION",
    "DETERMINISTIC_NORMALIZER_ID",
    "DETERMINISTIC_NORMALIZER_VERSION",
    "INTENT_IR_COLLECTION_SCHEMA",
    "INTENT_IR_SCHEMA_VERSION",
    "INTENT_IR_COLLECTION_SEMANTICS",
    "LEGACY_INTENT_IR_SCHEMA_VERSION",
    "OBJECTIVE_MATERIALIZATION_RECEIPT_FORBIDDEN_FIELDS",
    "OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA",
    "OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA_VERSION",
    "RULE_DRIVEN_DECOMPOSITION_MAX_CHILDREN",
    "RULE_DRIVEN_DECOMPOSITION_MAX_CHILD_SCOPE_PATHS",
    "RULE_DRIVEN_OBJECTIVE_DECOMPOSER_ID",
    "RULE_DRIVEN_OBJECTIVE_DECOMPOSER_VERSION",
    "RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_AUTHORITY",
    "RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_FORBIDDEN_FIELDS",
    "RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA",
    "RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA_VERSION",
    "SUPERVISOR_OBJECTIVE_INTENT_FORBIDDEN_FIELDS",
    "SUPERVISOR_OBJECTIVE_INTENT_MAX_IDEA_UTF8_BYTES",
    "SUPERVISOR_OBJECTIVE_INTENT_MAX_TAGS",
    "SUPERVISOR_OBJECTIVE_INTENT_SCHEMA",
    "SUPERVISOR_OBJECTIVE_INTENT_SCHEMA_VERSION",
    "UNRESOLVED_QUESTION_AUTHORITY",
    "UNRESOLVED_QUESTION_CAPTURE_ID",
    "UNRESOLVED_QUESTION_CAPTURE_SCHEMA",
    "UNRESOLVED_QUESTION_CAPTURE_SCHEMA_VERSION",
    "UNRESOLVED_QUESTION_CAPTURE_VERSION",
    "UNRESOLVED_QUESTION_FORBIDDEN_FIELDS",
    "UNRESOLVED_QUESTION_MAX_CONTEXT_BUDGET",
    "UNRESOLVED_QUESTION_MAX_QUESTIONS",
    "UNRESOLVED_QUESTION_SCHEMA",
    "UNRESOLVED_QUESTION_SCHEMA_VERSION",
    "ControlEdgeKind",
    "DeterministicObjectiveNormalization",
    "GroundingKind",
    "IntentAction",
    "IntentControlEdge",
    "IntentIRDocument",
    "IntentIRValidationError",
    "IntentKind",
    "IntentModality",
    "IntentStatement",
    "KnownObjectiveClass",
    "KnownObjectiveClassRule",
    "MinimumSpecialistCapability",
    "NodeGrounding",
    "ObjectiveMaterializationReceipt",
    "ReviewStatus",
    "RuleDrivenDecompositionChild",
    "RuleDrivenObjectiveDecomposition",
    "SourceRef",
    "SourceSpan",
    "StatementKind",
    "SupervisorObjectiveIntent",
    "SupervisorObjectiveSubmitterKind",
    "UnresolvedQuestion",
    "UnresolvedQuestionCapture",
    "build_unresolved_question",
    "capture_unresolved_semantic_questions",
    "decompose_supervisor_objective_by_rules",
    "idea_text_sha256",
    "list_known_objective_class_rules",
    "normalize_supervisor_objective_deterministically",
    "supervisor_objective_intent_sha256",
    "unresolved_question_identity_for",
    "validate_deterministic_objective_normalization",
    "validate_intent_ir",
    "validate_objective_materialization_receipt",
    "validate_rule_driven_decomposition_child",
    "validate_rule_driven_objective_decomposition",
    "validate_supervisor_objective_intent",
    "validate_unresolved_question",
    "validate_unresolved_question_capture",
]
