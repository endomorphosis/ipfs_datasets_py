"""Intent IR and Invocation IR adapters for UI/UX IR (UIR-031).

Projects source-grounded Intent IR documents and governed
:class:`InvocationIntentEnvelope` records into stable UI program bindings,
tasks, state candidates, control-flow transitions, feedback, and clarification
needs.

Interfaces:
- ``IntentUIIRAdapter@1``
- ``InvocationUIIRAdapter@1``

Non-goals (fail-closed invariants):
- Never execute Intent procedures, control edges, or invocation envelopes.
- Never copy executable procedure bodies or free-form code into UI nodes.
- Never treat source text as instructions, policy, or authority.
- Never embed raw secrets; secret-bearing material is referenced or redacted
  under the existing invocation argument-commitment policy.
- Never grant UCAN, capability tokens, role grants, or permission elevations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from ...intent_ir.invocation.model import (
    ArgumentCommitment,
    InvocationIntentEnvelope,
    InvocationKind,
    validate_invocation_envelope,
)
from ...intent_ir.schema import (
    ControlEdgeKind,
    IntentAction,
    IntentControlEdge,
    IntentIRDocument,
    IntentIRValidationError,
    IntentStatement,
    SourceRef as IntentSourceRef,
    StatementKind,
    validate_intent_ir,
)
from ..model.bindings import (
    ConfirmationClass,
    IdempotencyClass,
    RiskClass,
    UIActionBinding,
    UIProgramRef,
    validate_action_binding,
)
from ..schema import (
    EventKind,
    ProgramBindingTargetKind,
    ReviewStatus,
    SourceSpan,
    TerminalOutcomeKind,
    UIEffect,
    UIEvent,
    UIFeedbackContract,
    UIGuard,
    UIIntentIRBinding,
    UIInvocationBinding,
    UILocalizationBinding,
    UIProgramBinding,
    UIRecoveryPath,
    UISourceRef,
    UIState,
    UITransition,
    UIUXTask,
    UIIRValidationError,
)

INTENT_UIIR_ADAPTER: Final = "IntentUIIRAdapter@1"
INVOCATION_UIIR_ADAPTER: Final = "InvocationUIIRAdapter@1"
INTENT_UIIR_ADAPTER_VERSION: Final = "intent-uiir-adapter/v1"
INVOCATION_UIIR_ADAPTER_VERSION: Final = "invocation-uiir-adapter/v1"
CONTROL_FLOW_MAPPING_RECEIPT_VERSION: Final = "intent-control-flow-mapping/v1"
INVOCATION_METADATA_RECEIPT_VERSION: Final = "invocation-ui-metadata/v1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_EXECUTABLE_TEXT_MARKERS: Final = (
    "${",
    "{{",
    "javascript:",
    "=>",
    "eval(",
    "exec(",
    "Function(",
    "__import__",
    "subprocess.",
    "os.system",
)
# Instruction-like authority markers that must not elevate source text.
_INSTRUCTION_AUTHORITY_MARKERS: Final = (
    "you are now",
    "ignore previous",
    "system prompt",
    "act as root",
    "grant permission",
    "elevate privileges",
    "bypass policy",
    "execute the following",
)
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(^|[_.-])(password|passwd|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|authorization|bearer|credential|session[_-]?id)([_.-]|$)"
)
_REDACTED_VALUE_RE = re.compile(
    r"(?i)^(\[REDACTED\]|<REDACTED>|REDACTED|\*{3,}|secret:[A-Za-z0-9._:/-]{1,255}"
    r"|ref:secret:[A-Za-z0-9._:/-]{1,255}|\$\{SECRET:[A-Za-z0-9._:/-]+\}$)$"
)

_EDGE_TO_EVENT: Final[Mapping[ControlEdgeKind, str]] = MappingProxyType(
    {
        ControlEdgeKind.NEXT: "intent.control.next",
        ControlEdgeKind.ON_SUCCESS: "intent.control.on_success",
        ControlEdgeKind.ON_FAILURE: "intent.control.on_failure",
        ControlEdgeKind.CONDITIONAL: "intent.control.conditional",
        ControlEdgeKind.RETRY: "intent.control.retry",
        ControlEdgeKind.PARALLEL: "intent.control.parallel",
        ControlEdgeKind.JOIN: "intent.control.join",
    }
)

_EDGE_EVENT_KIND: Final[Mapping[ControlEdgeKind, EventKind]] = MappingProxyType(
    {
        ControlEdgeKind.NEXT: EventKind.DOMAIN,
        ControlEdgeKind.ON_SUCCESS: EventKind.PROGRAM_RESULT,
        ControlEdgeKind.ON_FAILURE: EventKind.PROGRAM_RESULT,
        ControlEdgeKind.CONDITIONAL: EventKind.DOMAIN,
        ControlEdgeKind.RETRY: EventKind.DOMAIN,
        ControlEdgeKind.PARALLEL: EventKind.DOMAIN,
        ControlEdgeKind.JOIN: EventKind.DOMAIN,
    }
)


class IntentUIIRAdapterError(ValueError):
    """Raised when Intent IR cannot be projected into UI/UX IR fragments."""


class InvocationUIIRAdapterError(ValueError):
    """Raised when an invocation envelope cannot be projected into UI/UX IR."""


class ClarificationKind(str, Enum):
    """Why a projected fragment needs clarification before use."""

    MISSING_ACTION = "missing_action"
    MISSING_GOAL = "missing_goal"
    LOW_CONFIDENCE = "low_confidence"
    INFERRED_NODE = "inferred_node"
    AMBIGUOUS_CONTROL = "ambiguous_control"
    UNSUPPORTED_FIELD = "unsupported_field"
    SECRET_REDACTED = "secret_redacted"
    SOURCE_TEXT_NON_AUTHORITY = "source_text_non_authority"


@dataclass(frozen=True, slots=True)
class ClarificationNeed:
    """Bounded clarification request; never elevates source text to authority."""

    clarification_id: str
    kind: ClarificationKind
    subject_ref: str
    reason: str
    source_ref_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "clarification_id": self.clarification_id,
            "kind": self.kind.value,
            "reason": self.reason,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "subject_ref": self.subject_ref,
        }


@dataclass(frozen=True, slots=True)
class ControlFlowMappingReceipt:
    """Evidence that Intent control edges map to UI transitions by identity."""

    receipt_id: str
    intent_document_id: str
    edge_mappings: tuple[tuple[str, str], ...]
    action_state_mappings: tuple[tuple[str, str], ...]
    schema_version: str = CONTROL_FLOW_MAPPING_RECEIPT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_state_mappings": [
                {"action_id": action_id, "state_id": state_id}
                for action_id, state_id in self.action_state_mappings
            ],
            "edge_mappings": [
                {"edge_id": edge_id, "transition_id": transition_id}
                for edge_id, transition_id in self.edge_mappings
            ],
            "intent_document_id": self.intent_document_id,
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class IntentUIIRProjection:
    """Source-grounded UI fragments projected from one Intent IR document."""

    intent_document_id: str
    intent_ir_bindings: tuple[UIIntentIRBinding, ...]
    program_bindings: tuple[UIProgramBinding, ...]
    action_bindings: tuple[UIActionBinding, ...]
    ux_tasks: tuple[UIUXTask, ...]
    states: tuple[UIState, ...]
    events: tuple[UIEvent, ...]
    transitions: tuple[UITransition, ...]
    guards: tuple[UIGuard, ...]
    effects: tuple[UIEffect, ...]
    feedback_contracts: tuple[UIFeedbackContract, ...]
    recovery_paths: tuple[UIRecoveryPath, ...]
    localization: tuple[UILocalizationBinding, ...]
    sources: tuple[UISourceRef, ...]
    clarification_needs: tuple[ClarificationNeed, ...]
    control_flow_receipt: ControlFlowMappingReceipt
    condition_refs: tuple[str, ...] = ()
    effect_refs: tuple[str, ...] = ()
    verification_refs: tuple[str, ...] = ()
    failure_refs: tuple[str, ...] = ()
    goal_refs: tuple[str, ...] = ()
    adapter: str = INTENT_UIIR_ADAPTER
    schema_version: str = INTENT_UIIR_ADAPTER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_bindings": [item.to_dict() for item in self.action_bindings],
            "adapter": self.adapter,
            "clarification_needs": [
                item.to_dict() for item in self.clarification_needs
            ],
            "condition_refs": sorted(set(self.condition_refs)),
            "control_flow_receipt": self.control_flow_receipt.to_dict(),
            "effect_refs": sorted(set(self.effect_refs)),
            "effects": [item.to_dict() for item in self.effects],
            "events": [item.to_dict() for item in self.events],
            "failure_refs": sorted(set(self.failure_refs)),
            "feedback_contracts": [
                item.to_dict() for item in self.feedback_contracts
            ],
            "goal_refs": sorted(set(self.goal_refs)),
            "guards": [item.to_dict() for item in self.guards],
            "intent_document_id": self.intent_document_id,
            "intent_ir_bindings": [
                item.to_dict() for item in self.intent_ir_bindings
            ],
            "localization": [item.to_dict() for item in self.localization],
            "program_bindings": [item.to_dict() for item in self.program_bindings],
            "recovery_paths": [item.to_dict() for item in self.recovery_paths],
            "schema_version": self.schema_version,
            "sources": [item.to_dict() for item in self.sources],
            "states": [item.to_dict() for item in self.states],
            "transitions": [item.to_dict() for item in self.transitions],
            "ux_tasks": [item.to_dict() for item in self.ux_tasks],
            "verification_refs": sorted(set(self.verification_refs)),
        }


@dataclass(frozen=True, slots=True)
class InvocationMetadataReceipt:
    """Preserved governed-invocation metadata without authority grants."""

    receipt_id: str
    envelope_id: str
    template_cid: str
    actor_id: str
    actor_kind: str
    delegation_link_ids: tuple[str, ...]
    action_scope_ids: tuple[str, ...]
    argument_commitment: str
    secret_refs: tuple[str, ...]
    redacted_argument_keys: tuple[str, ...]
    scope_entry_ids: tuple[str, ...]
    purpose: str
    environment_id: str
    environment_snapshot_digest: str
    rollback_step_ids: tuple[str, ...]
    verification_step_ids: tuple[str, ...]
    precondition_refs: tuple[str, ...]
    postcondition_refs: tuple[str, ...]
    failure_mode_refs: tuple[str, ...]
    tool_id: str
    tool_name: str
    audience_id: str
    tenant_id: str
    invocation_kind: str
    schema_version: str = INVOCATION_METADATA_RECEIPT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_scope_ids": list(self.action_scope_ids),
            "actor_id": self.actor_id,
            "actor_kind": self.actor_kind,
            "argument_commitment": self.argument_commitment,
            "audience_id": self.audience_id,
            "delegation_link_ids": list(self.delegation_link_ids),
            "envelope_id": self.envelope_id,
            "environment_id": self.environment_id,
            "environment_snapshot_digest": self.environment_snapshot_digest,
            "failure_mode_refs": list(self.failure_mode_refs),
            "invocation_kind": self.invocation_kind,
            "postcondition_refs": list(self.postcondition_refs),
            "precondition_refs": list(self.precondition_refs),
            "purpose": self.purpose,
            "receipt_id": self.receipt_id,
            "redacted_argument_keys": list(self.redacted_argument_keys),
            "rollback_step_ids": list(self.rollback_step_ids),
            "schema_version": self.schema_version,
            "scope_entry_ids": list(self.scope_entry_ids),
            "secret_refs": list(self.secret_refs),
            "template_cid": self.template_cid,
            "tenant_id": self.tenant_id,
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "verification_step_ids": list(self.verification_step_ids),
        }


@dataclass(frozen=True, slots=True)
class InvocationUIIRProjection:
    """UI fragments projected from one governed invocation envelope."""

    envelope_id: str
    template_cid: str
    invocation_bindings: tuple[UIInvocationBinding, ...]
    program_bindings: tuple[UIProgramBinding, ...]
    action_bindings: tuple[UIActionBinding, ...]
    intent_ir_bindings: tuple[UIIntentIRBinding, ...]
    feedback_contracts: tuple[UIFeedbackContract, ...]
    recovery_paths: tuple[UIRecoveryPath, ...]
    localization: tuple[UILocalizationBinding, ...]
    clarification_needs: tuple[ClarificationNeed, ...]
    metadata_receipt: InvocationMetadataReceipt
    condition_refs: tuple[str, ...] = ()
    effect_refs: tuple[str, ...] = ()
    verification_refs: tuple[str, ...] = ()
    failure_refs: tuple[str, ...] = ()
    adapter: str = INVOCATION_UIIR_ADAPTER
    schema_version: str = INVOCATION_UIIR_ADAPTER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_bindings": [item.to_dict() for item in self.action_bindings],
            "adapter": self.adapter,
            "clarification_needs": [
                item.to_dict() for item in self.clarification_needs
            ],
            "condition_refs": sorted(set(self.condition_refs)),
            "effect_refs": sorted(set(self.effect_refs)),
            "envelope_id": self.envelope_id,
            "failure_refs": sorted(set(self.failure_refs)),
            "feedback_contracts": [
                item.to_dict() for item in self.feedback_contracts
            ],
            "intent_ir_bindings": [
                item.to_dict() for item in self.intent_ir_bindings
            ],
            "invocation_bindings": [
                item.to_dict() for item in self.invocation_bindings
            ],
            "localization": [item.to_dict() for item in self.localization],
            "metadata_receipt": self.metadata_receipt.to_dict(),
            "program_bindings": [item.to_dict() for item in self.program_bindings],
            "recovery_paths": [item.to_dict() for item in self.recovery_paths],
            "schema_version": self.schema_version,
            "template_cid": self.template_cid,
            "verification_refs": sorted(set(self.verification_refs)),
        }


def _require_identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise IntentUIIRAdapterError(f"{name} is not a stable identifier: {value!r}")
    return value


def _stable_id(*parts: str) -> str:
    cleaned = [part.strip().replace(" ", "_") for part in parts if part and part.strip()]
    if not cleaned:
        raise IntentUIIRAdapterError("Cannot build empty stable identifier")
    candidate = ":".join(cleaned)
    # Collapse characters outside the identifier alphabet.
    candidate = re.sub(r"[^A-Za-z0-9._:/-]+", "_", candidate)
    if not _IDENTIFIER_RE.fullmatch(candidate):
        # Prefix to guarantee a leading alphanumeric when needed.
        candidate = f"id:{candidate}"
        candidate = re.sub(r"[^A-Za-z0-9._:/-]+", "_", candidate)
    if not _IDENTIFIER_RE.fullmatch(candidate):
        raise IntentUIIRAdapterError(f"Cannot stabilize identifier from parts {parts!r}")
    return candidate


def _map_review_status(value: Any) -> ReviewStatus:
    if isinstance(value, ReviewStatus):
        return value
    text = getattr(value, "value", value)
    try:
        return ReviewStatus(str(text))
    except ValueError:
        return ReviewStatus.UNREVIEWED


def _project_source(source: IntentSourceRef) -> UISourceRef:
    span = None
    if source.span is not None:
        span = SourceSpan(
            start_char=source.span.start_char,
            end_char=source.span.end_char,
        )
    return UISourceRef(
        ref_id=source.ref_id,
        source_uri=source.source_uri,
        source_id=source.source_id,
        source_revision=source.source_revision,
        content_sha256=source.content_sha256,
        container_uri=source.container_uri,
        container_sha256=source.container_sha256,
        content_cid=source.content_cid,
        license_expression=source.license_expression,
        review_status=_map_review_status(source.review_status),
        span=span,
    )


def _display_text_or_reference(
    text: str,
    *,
    subject_ref: str,
    source_ref_ids: tuple[str, ...],
    clarifications: list[ClarificationNeed],
    clarification_prefix: str,
) -> str:
    """Return safe display text; never elevate source text to authority.

    Instruction-like or executable-looking text is replaced with a neutral
    reference token and recorded as a clarification need.
    """

    if not isinstance(text, str):
        return ""
    lowered = text.lower()
    if any(marker in text for marker in _EXECUTABLE_TEXT_MARKERS) or any(
        marker in lowered for marker in _INSTRUCTION_AUTHORITY_MARKERS
    ):
        clarifications.append(
            ClarificationNeed(
                clarification_id=_stable_id(
                    clarification_prefix, "non_authority", subject_ref
                ),
                kind=ClarificationKind.SOURCE_TEXT_NON_AUTHORITY,
                subject_ref=subject_ref,
                reason=(
                    "Source text retained only as a non-authority reference; "
                    "it cannot become instructions, policy, or grants"
                ),
                source_ref_ids=source_ref_ids,
            )
        )
        return f"ref:statement:{subject_ref}"
    return text


def _redact_mapping_keys(value: Mapping[str, Any]) -> tuple[str, ...]:
    """Return keys that are secret-bearing or already redacted under policy."""

    keys: list[str] = []
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        if _SENSITIVE_KEY_RE.search(key):
            keys.append(key)
        elif isinstance(item, str) and _REDACTED_VALUE_RE.fullmatch(item):
            keys.append(key)
    return tuple(sorted(set(keys)))


def _edge_priority(kind: ControlEdgeKind) -> int:
    # Deterministic, non-colliding priority classes by edge kind.
    order = {
        ControlEdgeKind.ON_FAILURE: 100,
        ControlEdgeKind.RETRY: 90,
        ControlEdgeKind.CONDITIONAL: 80,
        ControlEdgeKind.ON_SUCCESS: 70,
        ControlEdgeKind.NEXT: 60,
        ControlEdgeKind.PARALLEL: 50,
        ControlEdgeKind.JOIN: 40,
    }
    return order.get(kind, 0)


class IntentUIIRAdapter:
    """Project Intent IR into source-grounded UI/UX IR fragments.

    Interface identity: ``IntentUIIRAdapter@1``.
    """

    interface: Final = INTENT_UIIR_ADAPTER
    version: Final = INTENT_UIIR_ADAPTER_VERSION

    def adapt(self, document: IntentIRDocument) -> IntentUIIRProjection:
        """Project a validated Intent IR document into UI IR fragments."""

        try:
            validated = validate_intent_ir(document)
        except IntentIRValidationError as exc:
            raise IntentUIIRAdapterError(str(exc)) from exc
        return self._project(validated)

    def _project(self, document: IntentIRDocument) -> IntentUIIRProjection:
        clarifications: list[ClarificationNeed] = []
        sources = tuple(_project_source(source) for source in document.sources)
        source_ids = {source.ref_id for source in sources}

        statements_by_id = {
            statement.statement_id: statement for statement in document.statements
        }
        goal_ids = tuple(
            statement.statement_id
            for statement in document.statements
            if statement.kind is StatementKind.GOAL
        )
        condition_ids = tuple(
            statement.statement_id
            for statement in document.statements
            if statement.kind
            in {
                StatementKind.PRECONDITION,
                StatementKind.GUARD,
                StatementKind.ASSUMPTION,
            }
        )
        effect_ids = tuple(
            statement.statement_id
            for statement in document.statements
            if statement.kind
            in {StatementKind.EFFECT, StatementKind.POSTCONDITION}
        )
        verification_ids = tuple(
            statement.statement_id
            for statement in document.statements
            if statement.kind
            in {StatementKind.VERIFICATION, StatementKind.INVARIANT}
        )
        failure_ids = tuple(
            statement.statement_id
            for statement in document.statements
            if statement.kind is StatementKind.FAILURE
        )

        if not goal_ids:
            clarifications.append(
                ClarificationNeed(
                    clarification_id=_stable_id(
                        "clarify", document.document_id, "missing_goal"
                    ),
                    kind=ClarificationKind.MISSING_GOAL,
                    subject_ref=document.document_id,
                    reason="Intent document has no goal statements to project as UX tasks",
                )
            )
        if not document.actions and document.intent_kind.value == "procedure":
            clarifications.append(
                ClarificationNeed(
                    clarification_id=_stable_id(
                        "clarify", document.document_id, "missing_action"
                    ),
                    kind=ClarificationKind.MISSING_ACTION,
                    subject_ref=document.document_id,
                    reason="Procedure Intent IR has no actions to bind as UI actions",
                )
            )

        localization: list[UILocalizationBinding] = []
        for statement in document.statements:
            display = _display_text_or_reference(
                statement.normalized_text,
                subject_ref=statement.statement_id,
                source_ref_ids=statement.source_ref_ids,
                clarifications=clarifications,
                clarification_prefix="clarify",
            )
            localization.append(
                UILocalizationBinding(
                    localization_id=_stable_id(
                        "loc", document.document_id, statement.statement_id
                    ),
                    message_id=_stable_id("msg", statement.statement_id),
                    # Display-only: never used as instruction or authority.
                    default_text=display,
                    source_ref_ids=statement.source_ref_ids,
                )
            )
            if statement.confidence < 0.5:
                clarifications.append(
                    ClarificationNeed(
                        clarification_id=_stable_id(
                            "clarify", "low_conf", statement.statement_id
                        ),
                        kind=ClarificationKind.LOW_CONFIDENCE,
                        subject_ref=statement.statement_id,
                        reason=(
                            f"Statement confidence {statement.confidence} is below "
                            "the clarification threshold"
                        ),
                        source_ref_ids=statement.source_ref_ids,
                    )
                )
            if statement.grounding.value == "inferred":
                clarifications.append(
                    ClarificationNeed(
                        clarification_id=_stable_id(
                            "clarify", "inferred", statement.statement_id
                        ),
                        kind=ClarificationKind.INFERRED_NODE,
                        subject_ref=statement.statement_id,
                        reason="Inferred statement requires human clarification before UI authority",
                        source_ref_ids=statement.source_ref_ids,
                    )
                )

        intent_ir_bindings: list[UIIntentIRBinding] = [
            UIIntentIRBinding(
                binding_id=_stable_id("intent_bind", document.document_id),
                intent_document_id=document.document_id,
                intent_action_id="",
                source_ref_ids=tuple(
                    sorted({ref for source in document.sources for ref in (source.ref_id,)})
                ),
            )
        ]

        action_bindings: list[UIActionBinding] = []
        program_bindings: list[UIProgramBinding] = []
        states: list[UIState] = []
        effects: list[UIEffect] = []
        guards: list[UIGuard] = []
        action_state_map: list[tuple[str, str]] = []

        for action in document.actions:
            self._require_known_sources(action.source_ref_ids, source_ids, action.action_id)
            state_id = _stable_id("state", document.document_id, action.action_id)
            states.append(
                UIState(
                    state_id=state_id,
                    region_id=_stable_id("region", document.document_id, "procedure"),
                    source_ref_ids=action.source_ref_ids,
                )
            )
            action_state_map.append((action.action_id, state_id))

            intent_binding = UIIntentIRBinding(
                binding_id=_stable_id(
                    "intent_bind", document.document_id, action.action_id
                ),
                intent_document_id=document.document_id,
                intent_action_id=action.action_id,
                source_ref_ids=action.source_ref_ids,
            )
            intent_ir_bindings.append(intent_binding)

            program_ref = UIProgramRef(
                target_kind=ProgramBindingTargetKind.INTENT_IR,
                intent_document_id=document.document_id,
                intent_action_id=action.action_id,
            )
            risk, confirmation = self._risk_for_action(action, statements_by_id)
            action_binding = UIActionBinding(
                binding_id=_stable_id(
                    "action_bind", document.document_id, action.action_id
                ),
                action_id=action.action_id,
                program_ref=program_ref,
                risk_class=risk,
                confirmation_class=confirmation,
                idempotency=IdempotencyClass.UNKNOWN,
                precondition_ids=action.precondition_ids,
                effect_ids=action.effect_ids,
                verification_ids=action.verification_ids,
                source_ref_ids=action.source_ref_ids,
            )
            validate_action_binding(action_binding)
            action_bindings.append(action_binding)
            program_bindings.append(action_binding.to_envelope_program_binding())

            for effect_id in action.effect_ids:
                effects.append(
                    UIEffect(
                        effect_id=_stable_id(
                            "ui_effect",
                            document.document_id,
                            action.action_id,
                            effect_id,
                        ),
                        program_binding_id=action_binding.binding_id,
                        source_ref_ids=action.source_ref_ids,
                    )
                )
            for precondition_id in action.precondition_ids:
                guards.append(
                    UIGuard(
                        guard_id=_stable_id(
                            "guard",
                            document.document_id,
                            action.action_id,
                            precondition_id,
                        ),
                        constraint_ref=precondition_id,
                        source_ref_ids=action.source_ref_ids,
                    )
                )

        # Control-flow projection: edges become transitions, never executable code.
        events_by_id: dict[str, UIEvent] = {}
        transitions: list[UITransition] = []
        edge_mappings: list[tuple[str, str]] = []
        state_by_action = dict(action_state_map)

        for edge in document.control_edges:
            self._require_known_sources(edge.source_ref_ids, source_ids, edge.edge_id)
            source_state = state_by_action.get(edge.source_action_id)
            target_state = state_by_action.get(edge.target_action_id)
            if source_state is None or target_state is None:
                clarifications.append(
                    ClarificationNeed(
                        clarification_id=_stable_id(
                            "clarify", "edge", edge.edge_id
                        ),
                        kind=ClarificationKind.AMBIGUOUS_CONTROL,
                        subject_ref=edge.edge_id,
                        reason=(
                            "Control edge references an action without a projected "
                            "state candidate"
                        ),
                        source_ref_ids=edge.source_ref_ids,
                    )
                )
                continue

            event_token = _EDGE_TO_EVENT[edge.kind]
            event_id = _stable_id(
                "event", document.document_id, edge.kind.value, event_token
            )
            if event_id not in events_by_id:
                events_by_id[event_id] = UIEvent(
                    event_id=event_id,
                    kind=_EDGE_EVENT_KIND[edge.kind],
                    source_ref_ids=edge.source_ref_ids,
                )
            else:
                # Merge source refs deterministically.
                prior = events_by_id[event_id]
                merged = tuple(
                    sorted(set(prior.source_ref_ids) | set(edge.source_ref_ids))
                )
                events_by_id[event_id] = UIEvent(
                    event_id=prior.event_id,
                    kind=prior.kind,
                    source_ref_ids=merged,
                )

            guard_id = ""
            if edge.guard_statement_id:
                guard_id = _stable_id(
                    "guard", document.document_id, "edge", edge.guard_statement_id
                )
                guards.append(
                    UIGuard(
                        guard_id=guard_id,
                        constraint_ref=edge.guard_statement_id,
                        source_ref_ids=edge.source_ref_ids,
                    )
                )

            transition_id = _stable_id(
                "transition", document.document_id, edge.edge_id
            )
            transitions.append(
                UITransition(
                    transition_id=transition_id,
                    source_state_id=source_state,
                    target_state_id=target_state,
                    event_id=event_id,
                    guard_id=guard_id,
                    effect_ids=(),
                    priority=_edge_priority(edge.kind),
                    source_ref_ids=edge.source_ref_ids,
                )
            )
            edge_mappings.append((edge.edge_id, transition_id))

        # Goals project to UX tasks over ordered entry/action step refs.
        ux_tasks: list[UIUXTask] = []
        step_ids = tuple(
            _stable_id("step", document.document_id, action_id)
            for action_id in (
                document.entry_action_ids
                or tuple(action.action_id for action in document.actions)
            )
        )
        for goal_id in goal_ids or (document.document_id,):
            goal_statement = statements_by_id.get(goal_id)
            source_refs = (
                goal_statement.source_ref_ids
                if goal_statement is not None
                else tuple(source.ref_id for source in document.sources)
            )
            task_name = document.title
            if goal_statement is not None:
                candidate = goal_statement.normalized_text[:120]
                lowered = candidate.lower()
                if not any(
                    marker in candidate for marker in _EXECUTABLE_TEXT_MARKERS
                ) and not any(
                    marker in lowered for marker in _INSTRUCTION_AUTHORITY_MARKERS
                ):
                    task_name = candidate
            ux_tasks.append(
                UIUXTask(
                    task_id=_stable_id("task", document.document_id, goal_id),
                    name=task_name,
                    # Step component IDs are stable placeholders that synthesis
                    # may later bind to concrete components; they are not code.
                    step_component_ids=step_ids,
                    source_ref_ids=source_refs,
                )
            )

        feedback_contracts: list[UIFeedbackContract] = []
        recovery_paths: list[UIRecoveryPath] = []
        for failure_id in failure_ids:
            statement = statements_by_id[failure_id]
            feedback_contracts.append(
                UIFeedbackContract(
                    feedback_id=_stable_id(
                        "feedback", document.document_id, failure_id
                    ),
                    channel="status",
                    source_ref_ids=statement.source_ref_ids,
                )
            )
            recovery_paths.append(
                UIRecoveryPath(
                    path_id=_stable_id(
                        "recovery", document.document_id, failure_id
                    ),
                    kind=TerminalOutcomeKind.FAILURE,
                    source_ref_ids=statement.source_ref_ids,
                )
            )
        for verification_id in verification_ids:
            statement = statements_by_id[verification_id]
            feedback_contracts.append(
                UIFeedbackContract(
                    feedback_id=_stable_id(
                        "feedback", "verify", document.document_id, verification_id
                    ),
                    channel="verification",
                    source_ref_ids=statement.source_ref_ids,
                )
            )

        # Deduplicate guards by id (action preconditions may overlap edges).
        unique_guards = self._unique_by_id(guards, key=lambda item: item.guard_id)
        unique_intent_bindings = self._unique_by_id(
            intent_ir_bindings, key=lambda item: item.binding_id
        )

        for item in unique_intent_bindings:
            item.validate()
        for item in program_bindings:
            item.validate()
        for item in states:
            item.validate()
        for item in events_by_id.values():
            item.validate()
        for item in transitions:
            item.validate()
        for item in unique_guards:
            item.validate()
        for item in effects:
            item.validate()
        for item in ux_tasks:
            item.validate()
        for item in feedback_contracts:
            item.validate()
        for item in recovery_paths:
            item.validate()
        for item in localization:
            item.validate()
        for item in sources:
            item.validate()

        receipt = ControlFlowMappingReceipt(
            receipt_id=_stable_id("receipt", "control", document.document_id),
            intent_document_id=document.document_id,
            edge_mappings=tuple(sorted(edge_mappings, key=lambda pair: pair[0])),
            action_state_mappings=tuple(
                sorted(action_state_map, key=lambda pair: pair[0])
            ),
        )

        return IntentUIIRProjection(
            intent_document_id=document.document_id,
            intent_ir_bindings=tuple(unique_intent_bindings),
            program_bindings=tuple(program_bindings),
            action_bindings=tuple(action_bindings),
            ux_tasks=tuple(ux_tasks),
            states=tuple(states),
            events=tuple(events_by_id[key] for key in sorted(events_by_id)),
            transitions=tuple(
                sorted(transitions, key=lambda item: item.transition_id)
            ),
            guards=tuple(unique_guards),
            effects=tuple(effects),
            feedback_contracts=tuple(feedback_contracts),
            recovery_paths=tuple(recovery_paths),
            localization=tuple(localization),
            sources=tuple(sources),
            clarification_needs=tuple(clarifications),
            control_flow_receipt=receipt,
            condition_refs=condition_ids,
            effect_refs=effect_ids,
            verification_refs=verification_ids,
            failure_refs=failure_ids,
            goal_refs=goal_ids,
        )

    @staticmethod
    def _require_known_sources(
        source_ref_ids: Sequence[str],
        known: set[str],
        subject: str,
    ) -> None:
        unknown = sorted(set(source_ref_ids) - known)
        if unknown:
            raise IntentUIIRAdapterError(
                f"{subject} references unknown source_ref_ids: {', '.join(unknown)}"
            )

    @staticmethod
    def _risk_for_action(
        action: IntentAction,
        statements: Mapping[str, IntentStatement],
    ) -> tuple[RiskClass, ConfirmationClass]:
        """Derive a conservative risk/confirmation class without inventing grants."""

        verb = action.verb.lower()
        destructive_verbs = {
            "delete",
            "destroy",
            "drop",
            "purge",
            "remove",
            "wipe",
            "revoke",
        }
        high_verbs = {"update", "write", "mutate", "transfer", "publish", "deploy"}
        if verb in destructive_verbs:
            return RiskClass.DESTRUCTIVE, ConfirmationClass.DOUBLE_CONFIRM
        if verb in high_verbs:
            return RiskClass.HIGH, ConfirmationClass.CONFIRM
        # Failure-linked actions elevate confirmation conservatively.
        for effect_id in action.effect_ids:
            statement = statements.get(effect_id)
            if statement is not None and statement.kind is StatementKind.FAILURE:
                return RiskClass.MEDIUM, ConfirmationClass.CONFIRM
        return RiskClass.LOW, ConfirmationClass.NONE

    @staticmethod
    def _unique_by_id(
        items: Iterable[Any], *, key
    ) -> list[Any]:
        seen: dict[str, Any] = {}
        for item in items:
            item_id = key(item)
            if item_id not in seen:
                seen[item_id] = item
        return [seen[item_id] for item_id in sorted(seen)]


class InvocationUIIRAdapter:
    """Project governed invocation envelopes into UI/UX IR fragments.

    Interface identity: ``InvocationUIIRAdapter@1``.

    Preserves actor, delegation link identities, action/scope, argument
    commitment (not raw secrets), purpose, environment, rollback, verification,
    conditions, effects, and failure modes as references. Source text and
    redacted argument display values never become instructions or authority.
    """

    interface: Final = INVOCATION_UIIR_ADAPTER
    version: Final = INVOCATION_UIIR_ADAPTER_VERSION

    def adapt(
        self, envelope: InvocationIntentEnvelope
    ) -> InvocationUIIRProjection:
        """Project a validated invocation envelope into UI IR fragments."""

        try:
            validated = validate_invocation_envelope(envelope)
        except Exception as exc:  # envelope validates fail-closed
            raise InvocationUIIRAdapterError(str(exc)) from exc
        return self._project(validated)

    def _project(
        self, envelope: InvocationIntentEnvelope
    ) -> InvocationUIIRProjection:
        clarifications: list[ClarificationNeed] = []
        template_cid = envelope.content_cid or envelope.content_digest
        if not template_cid:
            raise InvocationUIIRAdapterError(
                "Invocation envelope lacks content_cid/content_digest template identity"
            )

        source_ref_ids: tuple[str, ...] = ()
        if envelope.source.source_ref:
            source_ref_ids = (envelope.source.source_ref,)

        invocation_binding = UIInvocationBinding(
            binding_id=_stable_id("inv_bind", envelope.envelope_id),
            template_cid=template_cid,
            source_ref_ids=source_ref_ids,
        )
        invocation_binding.validate()

        program_ref = UIProgramRef(
            target_kind=ProgramBindingTargetKind.INVOCATION_TEMPLATE,
            invocation_template_cid=template_cid,
        )
        risk, confirmation = self._risk_for_envelope(envelope)
        action_binding = UIActionBinding(
            binding_id=_stable_id("action_bind", envelope.envelope_id),
            action_id=_stable_id(
                "action",
                envelope.tool.tool_id or envelope.envelope_id,
            ),
            program_ref=program_ref,
            risk_class=risk,
            confirmation_class=confirmation,
            idempotency=IdempotencyClass.UNKNOWN,
            precondition_ids=tuple(
                _stable_id("pre", envelope.envelope_id, str(index))
                for index, _ in enumerate(envelope.preconditions)
            ),
            effect_ids=tuple(
                _stable_id("post", envelope.envelope_id, str(index))
                for index, _ in enumerate(envelope.postconditions)
            ),
            verification_ids=tuple(
                step.step_id for step in envelope.verification
            ),
            rollback_ref=(
                envelope.rollback[0].step_id if envelope.rollback else ""
            ),
            audience=envelope.audience.audience_id,
            source_ref_ids=source_ref_ids,
        )
        validate_action_binding(action_binding)
        program_binding = action_binding.to_envelope_program_binding()

        intent_ir_bindings: list[UIIntentIRBinding] = []
        if envelope.source.intent_document_id:
            binding = UIIntentIRBinding(
                binding_id=_stable_id(
                    "intent_bind",
                    envelope.envelope_id,
                    envelope.source.intent_document_id,
                ),
                intent_document_id=envelope.source.intent_document_id,
                intent_action_id="",
                source_ref_ids=source_ref_ids,
            )
            binding.validate()
            intent_ir_bindings.append(binding)

        # Arguments: preserve commitment + secret refs; never raw secrets.
        arguments = envelope.arguments
        self._assert_arguments_safe(arguments)
        redacted_keys = _redact_mapping_keys(dict(arguments.redacted_arguments))
        if arguments.secret_refs or redacted_keys:
            clarifications.append(
                ClarificationNeed(
                    clarification_id=_stable_id(
                        "clarify", envelope.envelope_id, "secrets"
                    ),
                    kind=ClarificationKind.SECRET_REDACTED,
                    subject_ref=envelope.envelope_id,
                    reason=(
                        "Secret-bearing arguments are referenced or redacted; "
                        "raw secret material is not projected into UI nodes"
                    ),
                    source_ref_ids=source_ref_ids,
                )
            )

        localization: list[UILocalizationBinding] = []
        # Purpose and conditions are display-only references, not authority.
        if envelope.purpose.purpose:
            display = _display_text_or_reference(
                envelope.purpose.purpose,
                subject_ref=f"{envelope.envelope_id}:purpose",
                source_ref_ids=source_ref_ids,
                clarifications=clarifications,
                clarification_prefix="clarify",
            )
            localization.append(
                UILocalizationBinding(
                    localization_id=_stable_id(
                        "loc", envelope.envelope_id, "purpose"
                    ),
                    message_id=_stable_id("msg", envelope.envelope_id, "purpose"),
                    default_text=display,
                    source_ref_ids=source_ref_ids,
                )
            )

        condition_refs: list[str] = []
        for index, text in enumerate(envelope.preconditions):
            ref = _stable_id("pre", envelope.envelope_id, str(index))
            condition_refs.append(ref)
            display = _display_text_or_reference(
                text,
                subject_ref=ref,
                source_ref_ids=source_ref_ids,
                clarifications=clarifications,
                clarification_prefix="clarify",
            )
            localization.append(
                UILocalizationBinding(
                    localization_id=_stable_id("loc", ref),
                    message_id=_stable_id("msg", ref),
                    default_text=display,
                    source_ref_ids=source_ref_ids,
                )
            )

        effect_refs: list[str] = []
        for index, text in enumerate(envelope.postconditions):
            ref = _stable_id("post", envelope.envelope_id, str(index))
            effect_refs.append(ref)
            display = _display_text_or_reference(
                text,
                subject_ref=ref,
                source_ref_ids=source_ref_ids,
                clarifications=clarifications,
                clarification_prefix="clarify",
            )
            localization.append(
                UILocalizationBinding(
                    localization_id=_stable_id("loc", ref),
                    message_id=_stable_id("msg", ref),
                    default_text=display,
                    source_ref_ids=source_ref_ids,
                )
            )

        failure_refs: list[str] = []
        feedback: list[UIFeedbackContract] = []
        recovery: list[UIRecoveryPath] = []
        for index, text in enumerate(envelope.failure_modes):
            ref = _stable_id("fail", envelope.envelope_id, str(index))
            failure_refs.append(ref)
            display = _display_text_or_reference(
                text,
                subject_ref=ref,
                source_ref_ids=source_ref_ids,
                clarifications=clarifications,
                clarification_prefix="clarify",
            )
            localization.append(
                UILocalizationBinding(
                    localization_id=_stable_id("loc", ref),
                    message_id=_stable_id("msg", ref),
                    default_text=display,
                    source_ref_ids=source_ref_ids,
                )
            )
            feedback.append(
                UIFeedbackContract(
                    feedback_id=_stable_id("feedback", ref),
                    channel="error",
                    source_ref_ids=source_ref_ids,
                )
            )
            recovery.append(
                UIRecoveryPath(
                    path_id=_stable_id("recovery", ref),
                    kind=TerminalOutcomeKind.FAILURE,
                    source_ref_ids=source_ref_ids,
                )
            )

        for step in envelope.rollback:
            recovery.append(
                UIRecoveryPath(
                    path_id=_stable_id("rollback", step.step_id),
                    kind=TerminalOutcomeKind.PARTIAL,
                    recovery_component_id=step.action_ref or "",
                    source_ref_ids=source_ref_ids,
                )
            )
            display = _display_text_or_reference(
                step.description,
                subject_ref=step.step_id,
                source_ref_ids=source_ref_ids,
                clarifications=clarifications,
                clarification_prefix="clarify",
            )
            localization.append(
                UILocalizationBinding(
                    localization_id=_stable_id("loc", "rollback", step.step_id),
                    message_id=_stable_id("msg", "rollback", step.step_id),
                    default_text=display,
                    source_ref_ids=source_ref_ids,
                )
            )

        verification_refs = tuple(step.step_id for step in envelope.verification)
        for step in envelope.verification:
            feedback.append(
                UIFeedbackContract(
                    feedback_id=_stable_id("feedback", "verify", step.step_id),
                    channel="verification",
                    source_ref_ids=source_ref_ids,
                )
            )
            display = _display_text_or_reference(
                step.description,
                subject_ref=step.step_id,
                source_ref_ids=source_ref_ids,
                clarifications=clarifications,
                clarification_prefix="clarify",
            )
            localization.append(
                UILocalizationBinding(
                    localization_id=_stable_id("loc", "verify", step.step_id),
                    message_id=_stable_id("msg", "verify", step.step_id),
                    default_text=display,
                    source_ref_ids=source_ref_ids,
                )
            )

        for field in envelope.unsupported_fields:
            clarifications.append(
                ClarificationNeed(
                    clarification_id=_stable_id(
                        "clarify", "unsupported", envelope.envelope_id, field.field_path
                    ),
                    kind=ClarificationKind.UNSUPPORTED_FIELD,
                    subject_ref=field.field_path,
                    reason=field.reason,
                    source_ref_ids=(
                        (field.source_ref,) if field.source_ref else source_ref_ids
                    ),
                )
            )

        scope_entry_ids: list[str] = []
        action_scope_ids: list[str] = []
        for name in (
            "actions",
            "effects",
            "capabilities",
            "assets",
            "resources",
            "data_classes",
            "network",
            "filesystem",
            "subprocess",
            "secret_refs",
        ):
            for entry in getattr(envelope.scope, name):
                scope_entry_ids.append(entry.entry_id)
                if name == "actions":
                    action_scope_ids.append(entry.entry_id)

        metadata = InvocationMetadataReceipt(
            receipt_id=_stable_id("receipt", "invocation", envelope.envelope_id),
            envelope_id=envelope.envelope_id,
            template_cid=template_cid,
            actor_id=envelope.actor.actor_id,
            actor_kind=envelope.actor.kind,
            delegation_link_ids=tuple(link.link_id for link in envelope.delegation),
            action_scope_ids=tuple(action_scope_ids),
            argument_commitment=arguments.commitment,
            secret_refs=tuple(arguments.secret_refs),
            redacted_argument_keys=redacted_keys,
            scope_entry_ids=tuple(sorted(set(scope_entry_ids))),
            purpose=envelope.purpose.purpose,
            environment_id=envelope.environment.environment_id,
            environment_snapshot_digest=envelope.environment.snapshot_digest,
            rollback_step_ids=tuple(step.step_id for step in envelope.rollback),
            verification_step_ids=verification_refs,
            precondition_refs=tuple(condition_refs),
            postcondition_refs=tuple(effect_refs),
            failure_mode_refs=tuple(failure_refs),
            tool_id=envelope.tool.tool_id,
            tool_name=envelope.tool.tool_name,
            audience_id=envelope.audience.audience_id,
            tenant_id=envelope.tenant_id,
            invocation_kind=(
                envelope.invocation_kind.value
                if isinstance(envelope.invocation_kind, InvocationKind)
                else str(envelope.invocation_kind)
            ),
        )

        for item in localization:
            item.validate()
        for item in feedback:
            item.validate()
        for item in recovery:
            item.validate()

        # Fail closed: action binding must never carry authority-grant keys.
        payload = action_binding.to_dict()
        forbidden = {
            "authority_grant",
            "capability_token",
            "delegation",
            "grant",
            "grants",
            "permission",
            "permissions",
            "ucan",
            "ucan_token",
        }
        if forbidden.intersection(payload):
            raise InvocationUIIRAdapterError(
                "Projected action binding must not embed authority-grant fields"
            )

        return InvocationUIIRProjection(
            envelope_id=envelope.envelope_id,
            template_cid=template_cid,
            invocation_bindings=(invocation_binding,),
            program_bindings=(program_binding,),
            action_bindings=(action_binding,),
            intent_ir_bindings=tuple(intent_ir_bindings),
            feedback_contracts=tuple(feedback),
            recovery_paths=tuple(recovery),
            localization=tuple(localization),
            clarification_needs=tuple(clarifications),
            metadata_receipt=metadata,
            condition_refs=tuple(condition_refs),
            effect_refs=tuple(effect_refs),
            verification_refs=verification_refs,
            failure_refs=tuple(failure_refs),
        )

    @staticmethod
    def _assert_arguments_safe(arguments: ArgumentCommitment) -> None:
        """Reject raw secret material that escaped envelope validation."""

        for key, value in dict(arguments.redacted_arguments).items():
            if not isinstance(key, str):
                raise InvocationUIIRAdapterError(
                    "Argument keys must be strings"
                )
            if _SENSITIVE_KEY_RE.search(key):
                if not isinstance(value, str) or not _REDACTED_VALUE_RE.fullmatch(
                    value
                ):
                    raise InvocationUIIRAdapterError(
                        f"Sensitive argument {key!r} must be redacted or a secret reference"
                    )

    @staticmethod
    def _risk_for_envelope(
        envelope: InvocationIntentEnvelope,
    ) -> tuple[RiskClass, ConfirmationClass]:
        """Conservative risk from scope effects; never invents authority."""

        effect_values = {
            entry.value.lower() for entry in envelope.scope.effects
        }
        action_values = {
            entry.value.lower() for entry in envelope.scope.actions
        }
        destructive_tokens = {
            "delete",
            "destroy",
            "drop",
            "purge",
            "wipe",
            "revoke",
        }
        if any(
            any(token in value for token in destructive_tokens)
            for value in effect_values | action_values
        ):
            return RiskClass.DESTRUCTIVE, ConfirmationClass.DOUBLE_CONFIRM
        if envelope.scope.network or envelope.scope.subprocess:
            return RiskClass.HIGH, ConfirmationClass.CONFIRM
        if envelope.scope.filesystem or envelope.scope.secret_refs:
            return RiskClass.MEDIUM, ConfirmationClass.CONFIRM
        return RiskClass.LOW, ConfirmationClass.NONE


__all__ = [
    "CONTROL_FLOW_MAPPING_RECEIPT_VERSION",
    "ClarificationKind",
    "ClarificationNeed",
    "ControlFlowMappingReceipt",
    "INTENT_UIIR_ADAPTER",
    "INTENT_UIIR_ADAPTER_VERSION",
    "INVOCATION_METADATA_RECEIPT_VERSION",
    "INVOCATION_UIIR_ADAPTER",
    "INVOCATION_UIIR_ADAPTER_VERSION",
    "IntentUIIRAdapter",
    "IntentUIIRAdapterError",
    "IntentUIIRProjection",
    "InvocationMetadataReceipt",
    "InvocationUIIRAdapter",
    "InvocationUIIRAdapterError",
    "InvocationUIIRProjection",
]
