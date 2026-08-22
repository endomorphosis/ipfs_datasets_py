"""Canonical, source-grounded UI/UX IR schema (ui-ux-ir/v1).

Python authority for the closed declaration envelope. SwissKnife TypeScript
codec (``swissknife/src/services/mcp/ui-ux-ir-codec.ts``) mirrors this module
for cross-language identity. Declarations never authorize execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


UI_UX_IR_SCHEMA_VERSION = "ui-ux-ir/v1"
LEGACY_UI_UX_IR_SCHEMA_VERSION = "ui-ux-ir/v0.1"
UI_UX_IR_INTERFACE = "UIUXIR@1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NAMESPACE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_-]{0,63}(\.[A-Za-z][A-Za-z0-9_-]{0,63}){0,7}$"
)
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")

# Closed top-level wire keys (must match TypeScript UIIR_DOCUMENT_FIELDS).
UIIR_DOCUMENT_FIELDS: tuple[str, ...] = (
    "schema_version",
    "document_id",
    "title",
    "locale_defaults",
    "tags",
    "sources",
    "producer",
    "configuration",
    "review",
    "trust_bindings",
    "components",
    "composition_edges",
    "layout_regions",
    "layout_constraints",
    "design_token_refs",
    "state_variables",
    "states",
    "events",
    "transitions",
    "guards",
    "effects",
    "ux_tasks",
    "journeys",
    "success_failure_recovery",
    "feedback_contracts",
    "accessibility",
    "localization",
    "input_modality_requirements",
    "output_modality_requirements",
    "modality_alternatives",
    "device_capability_requirements",
    "adaptive_variants",
    "data_bindings",
    "content_references",
    "program_bindings",
    "intent_ir_bindings",
    "invocation_bindings",
    "mcp_idl_bindings",
    "formal_constraint_refs",
    "proof_obligation_refs",
    "entry_components",
    "initial_states",
    "terminal_outcomes",
    "extensions",
)

UIIR_REQUIRED_PATHS: tuple[str, ...] = (
    "schema_version",
    "document_id",
    "title",
    "sources",
    "components",
    "entry_components",
    "terminal_outcomes",
)

_FORBIDDEN_EXECUTABLE_KEYS = frozenset(
    {
        "callback",
        "callbacks",
        "code",
        "eval",
        "exec",
        "executable",
        "fn",
        "function",
        "handler",
        "handlers",
        "javascript",
        "jsx",
        "lambda",
        "listener",
        "listeners",
        "on_blur",
        "on_change",
        "on_click",
        "on_focus",
        "on_input",
        "on_submit",
        "onchange",
        "onclick",
        "onsubmit",
        "script",
        "scripts",
        "tsx",
    }
)
_FORBIDDEN_EXECUTABLE_PREFIXES = ("on_", "handle_")


class UIIRValidationError(ValueError):
    """Raised when a UI/UX IR document violates its canonical contract."""


class ReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    MACHINE_EXTRACTED = "machine_extracted"
    HUMAN_REVIEWED = "human_reviewed"
    TRUSTED_FIXTURE = "trusted_fixture"
    QUARANTINED = "quarantined"


class TerminalOutcomeKind(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


class ProgramBindingTargetKind(str, Enum):
    MCP_IDL = "mcp_idl_interface_method_schema"
    INTENT_IR = "intent_ir_document_action"
    INVOCATION_TEMPLATE = "invocation_intent_template"
    LOCAL_STATE = "local_state_only_transition"
    COMPOSITE_WORKFLOW = "versioned_composite_workflow"


class LayoutRegionKind(str, Enum):
    FLOW = "flow"
    GRID = "grid"
    STACK = "stack"
    OVERLAY = "overlay"
    SPATIAL_ANCHOR = "spatial_anchor"
    AUDIO_SEQUENCE = "audio_sequence"


class AuthorityKind(str, Enum):
    DECLARATION = "declaration"
    INTERFACE = "interface"
    LEGACY_ALIAS = "legacy_alias"
    PROJECTION = "projection"
    OBSERVATION = "observation"
    MEDIATION = "mediation"
    INVOCATION = "invocation"
    SATISFIABILITY = "satisfiability"
    MONITOR = "monitor"
    PROOF = "proof"
    ACCESSIBILITY = "accessibility"
    POLICY = "policy"
    SYNTHESIS_CANDIDATE = "synthesis_candidate"
    CONFORMANCE = "conformance"


def _validate_identifier(name: str, value: Any) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise UIIRValidationError(f"{name} is not a stable identifier")


def _validate_non_empty_string(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise UIIRValidationError(f"{name} must be a non-empty string")


def _validate_string(name: str, value: Any) -> None:
    if not isinstance(value, str):
        raise UIIRValidationError(f"{name} must be a string")


def _validate_sha256(name: str, value: Any) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise UIIRValidationError(
            f"{name} must be a lowercase 64-character SHA-256"
        )


def _validate_enum(name: str, value: Any, enum_cls: type[Enum]) -> None:
    if isinstance(value, enum_cls):
        return
    allowed = {item.value for item in enum_cls}
    if value not in allowed:
        raise UIIRValidationError(
            f"{name} must be one of {sorted(allowed)}; got {value!r}"
        )


def _is_forbidden_executable_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _FORBIDDEN_EXECUTABLE_KEYS:
        return True
    return any(lowered.startswith(prefix) for prefix in _FORBIDDEN_EXECUTABLE_PREFIXES)


def reject_executable_payload(value: Any, label: str, path: str = "") -> None:
    """Fail closed on executable callback fields / functions."""
    if callable(value):
        raise UIIRValidationError(f"{label}{path} contains an executable callback")
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_s = str(key)
            if _is_forbidden_executable_key(key_s):
                raise UIIRValidationError(
                    f"{label}{path}/{key_s} is an executable callback field"
                )
            reject_executable_payload(item, label, f"{path}/{key_s}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_executable_payload(item, label, f"{path}[{index}]")


def _require_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise UIIRValidationError(f"Duplicate {label} id: {value}")
        seen.add(value)


def _require_known_refs(
    values: Iterable[str], known: set[str], label: str
) -> None:
    missing = sorted({v for v in values if v not in known})
    if missing:
        raise UIIRValidationError(
            f"{label} references unknown ids: {', '.join(missing)}"
        )


def _sorted_unique(values: Sequence[str] | None) -> list[str]:
    return sorted(set(values or ()))


def _sort_by_key(
    items: Sequence[Mapping[str, Any]] | Sequence[Any] | None,
    key_name: str,
) -> list[Any]:
    rows = list(items or ())
    return sorted(
        rows,
        key=lambda item: str(
            item.get(key_name, "") if isinstance(item, Mapping) else getattr(item, key_name, "")
        ),
    )


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start_char: int
    end_char: int

    def validate(self) -> None:
        if isinstance(self.start_char, bool) or not isinstance(self.start_char, int):
            raise UIIRValidationError("SourceSpan.start_char must be an integer")
        if isinstance(self.end_char, bool) or not isinstance(self.end_char, int):
            raise UIIRValidationError("SourceSpan.end_char must be an integer")
        if self.start_char < 0 or self.end_char < self.start_char:
            raise UIIRValidationError(
                "SourceSpan must satisfy 0 <= start_char <= end_char"
            )

    def to_dict(self) -> dict[str, int]:
        return {"end_char": self.end_char, "start_char": self.start_char}


@dataclass(frozen=True, slots=True)
class UISourceRef:
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
        _validate_identifier("UISourceRef.ref_id", self.ref_id)
        for name in ("source_uri", "source_id", "source_revision"):
            _validate_non_empty_string(f"UISourceRef.{name}", getattr(self, name))
        _validate_sha256("UISourceRef.content_sha256", self.content_sha256)
        if self.container_sha256:
            _validate_sha256("UISourceRef.container_sha256", self.container_sha256)
        status = self.review_status
        if isinstance(status, ReviewStatus):
            status_val = status.value
        else:
            status_val = str(status)
        _validate_enum("UISourceRef.review_status", status_val, ReviewStatus)
        if self.span is not None:
            self.span.validate()

    def to_dict(self) -> dict[str, Any]:
        status = (
            self.review_status.value
            if isinstance(self.review_status, ReviewStatus)
            else str(self.review_status)
        )
        return {
            "container_sha256": self.container_sha256,
            "container_uri": self.container_uri,
            "content_cid": self.content_cid,
            "content_sha256": self.content_sha256,
            "license_expression": self.license_expression,
            "ref_id": self.ref_id,
            "review_status": status,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "source_uri": self.source_uri,
            "span": self.span.to_dict() if self.span else None,
        }


@dataclass(frozen=True, slots=True)
class UIComponent:
    component_id: str
    role: str
    purpose: str = ""
    accessible_name_ref: str = ""
    accessible_description_ref: str = ""
    parent_id: str = ""
    child_ids: tuple[str, ...] = ()
    modality_binding_ids: tuple[str, ...] = ()
    data_binding_ids: tuple[str, ...] = ()
    program_binding_ids: tuple[str, ...] = ()
    feedback_ids: tuple[str, ...] = ()
    privacy_sensitivity: str = "none"
    presentation_classification: str = "interactive"
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIComponent.component_id", self.component_id)
        _validate_non_empty_string(
            f"UIComponent {self.component_id!r}.role", self.role
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessible_description_ref": self.accessible_description_ref,
            "accessible_name_ref": self.accessible_name_ref,
            "child_ids": list(self.child_ids),
            "component_id": self.component_id,
            "data_binding_ids": _sorted_unique(self.data_binding_ids),
            "feedback_ids": _sorted_unique(self.feedback_ids),
            "modality_binding_ids": _sorted_unique(self.modality_binding_ids),
            "parent_id": self.parent_id,
            "presentation_classification": self.presentation_classification
            or "interactive",
            "privacy_sensitivity": self.privacy_sensitivity or "none",
            "program_binding_ids": _sorted_unique(self.program_binding_ids),
            "purpose": self.purpose,
            "role": self.role,
            "source_ref_ids": _sorted_unique(self.source_ref_ids),
        }


@dataclass(frozen=True, slots=True)
class UITerminalOutcome:
    outcome_id: str
    kind: TerminalOutcomeKind | str
    description: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UITerminalOutcome.outcome_id", self.outcome_id)
        kind = self.kind.value if isinstance(self.kind, TerminalOutcomeKind) else self.kind
        _validate_enum("UITerminalOutcome.kind", kind, TerminalOutcomeKind)

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind.value if isinstance(self.kind, TerminalOutcomeKind) else str(self.kind)
        return {
            "description": self.description,
            "kind": kind,
            "outcome_id": self.outcome_id,
            "source_ref_ids": _sorted_unique(self.source_ref_ids),
        }


@dataclass(frozen=True, slots=True)
class UILocaleDefaults:
    default_locale: str = "en"
    fallback_locales: tuple[str, ...] = ()
    text_direction: str = "ltr"

    def validate(self) -> None:
        _validate_non_empty_string(
            "UILocaleDefaults.default_locale", self.default_locale
        )
        for item in self.fallback_locales:
            _validate_non_empty_string("UILocaleDefaults.fallback_locales", item)
        _validate_non_empty_string(
            "UILocaleDefaults.text_direction", self.text_direction
        )
        if self.text_direction not in {"ltr", "rtl", "auto"}:
            raise UIIRValidationError(
                "UILocaleDefaults.text_direction must be ltr, rtl, or auto"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_locale": self.default_locale or "en",
            "fallback_locales": list(self.fallback_locales),
            "text_direction": self.text_direction or "ltr",
        }


@dataclass(frozen=True, slots=True)
class UIProducer:
    producer_id: str
    name: str
    version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "producer_id": self.producer_id,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class UIConfiguration:
    configuration_id: str
    profile: str = "default"
    settings: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration_id": self.configuration_id,
            "profile": self.profile or "default",
            "settings": dict(self.settings or {}),
        }


@dataclass(frozen=True, slots=True)
class UIReviewBinding:
    review_status: ReviewStatus | str = ReviewStatus.UNREVIEWED
    reviewer: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        status = (
            self.review_status.value
            if isinstance(self.review_status, ReviewStatus)
            else str(self.review_status or ReviewStatus.UNREVIEWED.value)
        )
        return {
            "notes": self.notes,
            "review_status": status,
            "reviewer": self.reviewer,
        }


@dataclass(frozen=True, slots=True)
class UITrustBinding:
    trust_id: str
    authority_kind: AuthorityKind | str
    subject_ref: str
    source_ref_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        kind = (
            self.authority_kind.value
            if isinstance(self.authority_kind, AuthorityKind)
            else str(self.authority_kind)
        )
        return {
            "authority_kind": kind,
            "source_ref_ids": _sorted_unique(self.source_ref_ids),
            "subject_ref": self.subject_ref,
            "trust_id": self.trust_id,
        }


@dataclass(frozen=True, slots=True)
class UILayoutRegion:
    region_id: str
    kind: LayoutRegionKind | str
    component_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind.value if isinstance(self.kind, LayoutRegionKind) else str(self.kind)
        return {
            "component_ids": list(self.component_ids),
            "kind": kind,
            "region_id": self.region_id,
            "source_ref_ids": _sorted_unique(self.source_ref_ids),
        }


@dataclass(frozen=True, slots=True)
class UIProgramBinding:
    binding_id: str
    target_kind: ProgramBindingTargetKind | str
    target_ref: str
    confirmation_class: str = "none"
    risk_class: str = "low"
    effect_ids: tuple[str, ...] = ()
    precondition_ids: tuple[str, ...] = ()
    verification_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        kind = (
            self.target_kind.value
            if isinstance(self.target_kind, ProgramBindingTargetKind)
            else str(self.target_kind)
        )
        return {
            "binding_id": self.binding_id,
            "confirmation_class": self.confirmation_class or "none",
            "effect_ids": _sorted_unique(self.effect_ids),
            "precondition_ids": _sorted_unique(self.precondition_ids),
            "risk_class": self.risk_class or "low",
            "source_ref_ids": _sorted_unique(self.source_ref_ids),
            "target_kind": kind,
            "target_ref": self.target_ref,
            "verification_ids": _sorted_unique(self.verification_ids),
        }


@dataclass(frozen=True, slots=True)
class UIMCPIDLBinding:
    binding_id: str
    interface_cid: str
    method_name: str
    argument_schema_ref: str = ""
    result_schema_ref: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "argument_schema_ref": self.argument_schema_ref,
            "binding_id": self.binding_id,
            "interface_cid": self.interface_cid,
            "method_name": self.method_name,
            "result_schema_ref": self.result_schema_ref,
            "source_ref_ids": _sorted_unique(self.source_ref_ids),
        }


@dataclass(frozen=True, slots=True)
class UIFeedbackContract:
    feedback_id: str
    channel: str
    component_id: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "component_id": self.component_id,
            "feedback_id": self.feedback_id,
            "source_ref_ids": _sorted_unique(self.source_ref_ids),
        }


@dataclass(frozen=True, slots=True)
class UIStateVariable:
    variable_id: str
    value_type: str
    derived: bool = False
    source_ref_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived": bool(self.derived),
            "source_ref_ids": _sorted_unique(self.source_ref_ids),
            "value_type": self.value_type,
            "variable_id": self.variable_id,
        }


@dataclass(frozen=True, slots=True)
class UIEvent:
    event_id: str
    kind: str
    source_ref_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "source_ref_ids": _sorted_unique(self.source_ref_ids),
        }


@dataclass(frozen=True, slots=True)
class UIUXTask:
    task_id: str
    name: str
    step_component_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_ref_ids": _sorted_unique(self.source_ref_ids),
            "step_component_ids": list(self.step_component_ids),
            "task_id": self.task_id,
        }


@dataclass(frozen=True, slots=True)
class UIJourney:
    journey_id: str
    name: str
    task_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "journey_id": self.journey_id,
            "name": self.name,
            "source_ref_ids": _sorted_unique(self.source_ref_ids),
            "task_ids": list(self.task_ids),
        }


@dataclass(frozen=True, slots=True)
class UINamespacedExtension:
    extension_id: str
    namespace: str
    version: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    required: bool = False
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier(
            "UINamespacedExtension.extension_id", self.extension_id
        )
        if not isinstance(self.namespace, str) or not _NAMESPACE_RE.fullmatch(
            self.namespace
        ):
            raise UIIRValidationError(
                "UINamespacedExtension.namespace must be a dotted namespace"
            )
        if not isinstance(self.version, str) or not _VERSION_RE.fullmatch(
            self.version
        ):
            raise UIIRValidationError(
                "UINamespacedExtension.version must be a stable version token"
            )
        root = self.namespace.split(".", 1)[0]
        banned = {
            "observation",
            "telemetry",
            "projection",
            "proof",
            "policy_result",
            "runtime",
        }
        if root in banned:
            raise UIIRValidationError(
                f"UINamespacedExtension.namespace {self.namespace!r} is not declaration content"
            )
        reject_executable_payload(
            dict(self.payload or {}),
            f"UINamespacedExtension {self.extension_id}.payload",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "extension_id": self.extension_id,
            "namespace": self.namespace,
            "payload": dict(self.payload or {}),
            "required": bool(self.required),
            "source_ref_ids": _sorted_unique(self.source_ref_ids),
            "version": self.version,
        }


def _mapping_rows(items: Sequence[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items or ():
        if hasattr(item, "to_dict") and callable(item.to_dict):
            out.append(dict(item.to_dict()))
        elif isinstance(item, Mapping):
            out.append(dict(item))
        else:
            out.append({"value": item})
    return out


@dataclass(frozen=True, slots=True)
class UIIRDocument:
    """Closed ui-ux-ir/v1 document envelope."""

    schema_version: str
    document_id: str
    title: str
    sources: tuple[UISourceRef, ...]
    components: tuple[UIComponent, ...]
    entry_components: tuple[str, ...]
    terminal_outcomes: tuple[UITerminalOutcome, ...]
    locale_defaults: UILocaleDefaults = field(default_factory=UILocaleDefaults)
    tags: tuple[str, ...] = ()
    producer: UIProducer | None = None
    configuration: UIConfiguration | None = None
    review: UIReviewBinding = field(default_factory=UIReviewBinding)
    trust_bindings: tuple[UITrustBinding, ...] = ()
    composition_edges: tuple[Mapping[str, Any], ...] = ()
    layout_regions: tuple[UILayoutRegion, ...] = ()
    layout_constraints: tuple[Mapping[str, Any], ...] = ()
    design_token_refs: tuple[Mapping[str, Any], ...] = ()
    state_variables: tuple[UIStateVariable, ...] = ()
    states: tuple[Mapping[str, Any], ...] = ()
    events: tuple[UIEvent, ...] = ()
    transitions: tuple[Mapping[str, Any], ...] = ()
    guards: tuple[Mapping[str, Any], ...] = ()
    effects: tuple[Mapping[str, Any], ...] = ()
    ux_tasks: tuple[UIUXTask, ...] = ()
    journeys: tuple[UIJourney, ...] = ()
    success_failure_recovery: tuple[Mapping[str, Any], ...] = ()
    feedback_contracts: tuple[UIFeedbackContract, ...] = ()
    accessibility: tuple[Mapping[str, Any], ...] = ()
    localization: tuple[Mapping[str, Any], ...] = ()
    input_modality_requirements: tuple[Mapping[str, Any], ...] = ()
    output_modality_requirements: tuple[Mapping[str, Any], ...] = ()
    modality_alternatives: tuple[Mapping[str, Any], ...] = ()
    device_capability_requirements: tuple[Mapping[str, Any], ...] = ()
    adaptive_variants: tuple[Mapping[str, Any], ...] = ()
    data_bindings: tuple[Mapping[str, Any], ...] = ()
    content_references: tuple[Mapping[str, Any], ...] = ()
    program_bindings: tuple[UIProgramBinding, ...] = ()
    intent_ir_bindings: tuple[Mapping[str, Any], ...] = ()
    invocation_bindings: tuple[Mapping[str, Any], ...] = ()
    mcp_idl_bindings: tuple[UIMCPIDLBinding, ...] = ()
    formal_constraint_refs: tuple[Mapping[str, Any], ...] = ()
    proof_obligation_refs: tuple[Mapping[str, Any], ...] = ()
    initial_states: tuple[str, ...] = ()
    extensions: tuple[UINamespacedExtension, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Emit the full closed envelope (TypeScript uiIrToDict parity)."""
        return {
            "accessibility": _sort_by_key(
                _mapping_rows(self.accessibility), "accessibility_id"
            ),
            "adaptive_variants": _sort_by_key(
                _mapping_rows(self.adaptive_variants), "variant_id"
            ),
            "components": [
                item.to_dict()
                for item in sorted(self.components, key=lambda c: c.component_id)
            ],
            "composition_edges": _sort_by_key(
                _mapping_rows(self.composition_edges), "edge_id"
            ),
            "configuration": (
                self.configuration.to_dict() if self.configuration else None
            ),
            "content_references": _sort_by_key(
                _mapping_rows(self.content_references), "content_id"
            ),
            "data_bindings": _sort_by_key(
                _mapping_rows(self.data_bindings), "binding_id"
            ),
            "design_token_refs": _sort_by_key(
                _mapping_rows(self.design_token_refs), "token_id"
            ),
            "device_capability_requirements": _sort_by_key(
                _mapping_rows(self.device_capability_requirements),
                "requirement_id",
            ),
            "document_id": self.document_id,
            "effects": _sort_by_key(_mapping_rows(self.effects), "effect_id"),
            "entry_components": _sorted_unique(self.entry_components),
            "events": [
                item.to_dict()
                for item in sorted(self.events, key=lambda e: e.event_id)
            ],
            "extensions": [
                item.to_dict()
                for item in sorted(self.extensions, key=lambda e: e.extension_id)
            ],
            "feedback_contracts": [
                item.to_dict()
                for item in sorted(
                    self.feedback_contracts, key=lambda f: f.feedback_id
                )
            ],
            "formal_constraint_refs": _sort_by_key(
                _mapping_rows(self.formal_constraint_refs), "constraint_id"
            ),
            "guards": _sort_by_key(_mapping_rows(self.guards), "guard_id"),
            "initial_states": _sorted_unique(self.initial_states),
            "input_modality_requirements": _sort_by_key(
                _mapping_rows(self.input_modality_requirements), "requirement_id"
            ),
            "intent_ir_bindings": _sort_by_key(
                _mapping_rows(self.intent_ir_bindings), "binding_id"
            ),
            "invocation_bindings": _sort_by_key(
                _mapping_rows(self.invocation_bindings), "binding_id"
            ),
            "journeys": [
                item.to_dict()
                for item in sorted(self.journeys, key=lambda j: j.journey_id)
            ],
            "layout_constraints": _sort_by_key(
                _mapping_rows(self.layout_constraints), "constraint_id"
            ),
            "layout_regions": [
                item.to_dict()
                for item in sorted(self.layout_regions, key=lambda r: r.region_id)
            ],
            "locale_defaults": (
                self.locale_defaults.to_dict()
                if self.locale_defaults
                else UILocaleDefaults().to_dict()
            ),
            "localization": _sort_by_key(
                _mapping_rows(self.localization), "localization_id"
            ),
            "mcp_idl_bindings": [
                item.to_dict()
                for item in sorted(
                    self.mcp_idl_bindings, key=lambda b: b.binding_id
                )
            ],
            "modality_alternatives": _sort_by_key(
                _mapping_rows(self.modality_alternatives), "alternative_id"
            ),
            "output_modality_requirements": _sort_by_key(
                _mapping_rows(self.output_modality_requirements),
                "requirement_id",
            ),
            "producer": self.producer.to_dict() if self.producer else None,
            "program_bindings": [
                item.to_dict()
                for item in sorted(
                    self.program_bindings, key=lambda b: b.binding_id
                )
            ],
            "proof_obligation_refs": _sort_by_key(
                _mapping_rows(self.proof_obligation_refs), "obligation_id"
            ),
            "review": (
                self.review.to_dict()
                if self.review
                else UIReviewBinding().to_dict()
            ),
            "schema_version": self.schema_version or UI_UX_IR_SCHEMA_VERSION,
            "sources": [
                item.to_dict()
                for item in sorted(self.sources, key=lambda s: s.ref_id)
            ],
            "state_variables": [
                item.to_dict()
                for item in sorted(
                    self.state_variables, key=lambda v: v.variable_id
                )
            ],
            "states": _sort_by_key(_mapping_rows(self.states), "state_id"),
            "success_failure_recovery": _sort_by_key(
                _mapping_rows(self.success_failure_recovery), "path_id"
            ),
            "tags": _sorted_unique(self.tags),
            "terminal_outcomes": [
                item.to_dict()
                for item in sorted(
                    self.terminal_outcomes, key=lambda o: o.outcome_id
                )
            ],
            "title": self.title,
            "transitions": _sort_by_key(
                _mapping_rows(self.transitions), "transition_id"
            ),
            "trust_bindings": [
                item.to_dict()
                for item in sorted(self.trust_bindings, key=lambda t: t.trust_id)
            ],
            "ux_tasks": [
                item.to_dict()
                for item in sorted(self.ux_tasks, key=lambda t: t.task_id)
            ],
        }


def reject_unknown_document_fields(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise UIIRValidationError("document payload must be a mapping")
    field_set = set(UIIR_DOCUMENT_FIELDS)
    unknown = sorted(k for k in payload.keys() if k not in field_set)
    if unknown:
        raise UIIRValidationError(
            f"unknown UIIRDocument field(s): {', '.join(unknown)}"
        )
    missing = sorted(name for name in UIIR_REQUIRED_PATHS if name not in payload)
    if missing:
        raise UIIRValidationError(
            f"missing required UIIRDocument path(s): {', '.join(missing)}"
        )


def validate_ui_ir(document: UIIRDocument) -> UIIRDocument:
    """Validate a decoded document (cross-reference closure)."""
    if document.schema_version != UI_UX_IR_SCHEMA_VERSION:
        raise UIIRValidationError(
            f"Unsupported UI/UX IR schema_version: {document.schema_version!r}"
        )
    _validate_identifier("UIIRDocument.document_id", document.document_id)
    _validate_non_empty_string("UIIRDocument.title", document.title)

    if not document.sources:
        raise UIIRValidationError("UIIRDocument.sources must not be empty")
    if not document.components:
        raise UIIRValidationError("UIIRDocument.components must not be empty")
    if not document.entry_components:
        raise UIIRValidationError(
            "UIIRDocument.entry_components must not be empty"
        )
    if not document.terminal_outcomes:
        raise UIIRValidationError(
            "UIIRDocument.terminal_outcomes must not be empty"
        )

    locale = document.locale_defaults or UILocaleDefaults()
    locale.validate()

    for source in document.sources:
        source.validate()
    for component in document.components:
        component.validate()
    for outcome in document.terminal_outcomes:
        outcome.validate()
    for ext in document.extensions:
        ext.validate()

    _require_unique((s.ref_id for s in document.sources), "source ref")
    _require_unique((c.component_id for c in document.components), "component")
    _require_unique(
        (o.outcome_id for o in document.terminal_outcomes), "terminal outcome"
    )
    _require_unique(document.entry_components, "entry_components member")
    _require_unique(document.tags, "tags member")
    _require_unique(document.initial_states, "initial_states member")
    _require_unique(
        (b.binding_id for b in document.program_bindings), "program binding"
    )
    _require_unique(
        (b.binding_id for b in document.mcp_idl_bindings), "mcp idl binding"
    )
    _require_unique(
        (f.feedback_id for f in document.feedback_contracts), "feedback"
    )
    _require_unique(
        (r.region_id for r in document.layout_regions), "layout region"
    )
    _require_unique(
        (e.extension_id for e in document.extensions), "extension"
    )

    source_ids = {s.ref_id for s in document.sources}
    component_ids = {c.component_id for c in document.components}
    program_ids = {b.binding_id for b in document.program_bindings}
    feedback_ids = {f.feedback_id for f in document.feedback_contracts}
    data_binding_ids = {
        str(item.get("binding_id") or "")
        for item in document.data_bindings
        if isinstance(item, Mapping)
    }
    modality_ids = {
        str(item.get("requirement_id") or "")
        for item in (
            *document.input_modality_requirements,
            *document.output_modality_requirements,
        )
        if isinstance(item, Mapping)
    }

    for component in document.components:
        _require_known_refs(
            component.source_ref_ids,
            source_ids,
            f"UIComponent {component.component_id!r}.source_ref_ids",
        )
        if component.parent_id:
            _require_known_refs(
                [component.parent_id],
                component_ids,
                f"UIComponent {component.component_id!r}.parent_id",
            )
        _require_known_refs(
            component.child_ids,
            component_ids,
            f"UIComponent {component.component_id!r}.child_ids",
        )
        if component.feedback_ids:
            _require_known_refs(
                component.feedback_ids,
                feedback_ids,
                f"UIComponent {component.component_id!r}.feedback_ids",
            )
        if component.program_binding_ids:
            _require_known_refs(
                component.program_binding_ids,
                program_ids,
                f"UIComponent {component.component_id!r}.program_binding_ids",
            )
        if component.data_binding_ids:
            _require_known_refs(
                component.data_binding_ids,
                data_binding_ids,
                f"UIComponent {component.component_id!r}.data_binding_ids",
            )
        if component.modality_binding_ids:
            _require_known_refs(
                component.modality_binding_ids,
                modality_ids,
                f"UIComponent {component.component_id!r}.modality_binding_ids",
            )

    _require_known_refs(
        document.entry_components,
        component_ids,
        "UIIRDocument.entry_components",
    )

    for outcome in document.terminal_outcomes:
        _require_known_refs(
            outcome.source_ref_ids,
            source_ids,
            f"UITerminalOutcome {outcome.outcome_id!r}.source_ref_ids",
        )

    for binding in document.program_bindings:
        _require_known_refs(
            binding.source_ref_ids,
            source_ids,
            f"UIProgramBinding {binding.binding_id!r}.source_ref_ids",
        )

    for binding in document.mcp_idl_bindings:
        _require_known_refs(
            binding.source_ref_ids,
            source_ids,
            f"UIMCPIDLBinding {binding.binding_id!r}.source_ref_ids",
        )

    for feedback in document.feedback_contracts:
        _require_known_refs(
            feedback.source_ref_ids,
            source_ids,
            f"UIFeedbackContract {feedback.feedback_id!r}.source_ref_ids",
        )
        if feedback.component_id:
            _require_known_refs(
                [feedback.component_id],
                component_ids,
                f"UIFeedbackContract {feedback.feedback_id!r}.component_id",
            )

    for region in document.layout_regions:
        _require_known_refs(
            region.source_ref_ids,
            source_ids,
            f"UILayoutRegion {region.region_id!r}.source_ref_ids",
        )
        _require_known_refs(
            region.component_ids,
            component_ids,
            f"UILayoutRegion {region.region_id!r}.component_ids",
        )

    if document.states and not document.initial_states:
        raise UIIRValidationError(
            "UIIRDocument.initial_states must not be empty when states are declared"
        )

    reject_executable_payload(document.to_dict(), "UIIRDocument")
    return document


# Public aliases matching TypeScript naming.
validate_uiir = validate_ui_ir

__all__ = [
    "AuthorityKind",
    "LEGACY_UI_UX_IR_SCHEMA_VERSION",
    "LayoutRegionKind",
    "ProgramBindingTargetKind",
    "ReviewStatus",
    "SourceSpan",
    "TerminalOutcomeKind",
    "UIConfiguration",
    "UIComponent",
    "UIEvent",
    "UIFeedbackContract",
    "UIIRDocument",
    "UIIRValidationError",
    "UIJourney",
    "UILayoutRegion",
    "UILocaleDefaults",
    "UIMCPIDLBinding",
    "UINamespacedExtension",
    "UIProducer",
    "UIProgramBinding",
    "UIReviewBinding",
    "UISourceRef",
    "UIStateVariable",
    "UITerminalOutcome",
    "UITrustBinding",
    "UIUXTask",
    "UI_UX_IR_INTERFACE",
    "UI_UX_IR_SCHEMA_VERSION",
    "UIIR_DOCUMENT_FIELDS",
    "UIIR_REQUIRED_PATHS",
    "reject_executable_payload",
    "reject_unknown_document_fields",
    "validate_ui_ir",
    "validate_uiir",
]
