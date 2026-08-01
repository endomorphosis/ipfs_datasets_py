"""Closed UI/UX IR v1 envelope schema.

The wire identifier is ``ui-ux-ir/v1``. This module defines the immutable
top-level document, declared collection semantics, exact reference namespaces,
and closed validation. Detailed component/layout/behavior/modality leaves are
owned by later model modules; the envelope records here establish stable IDs,
cross-reference closure, entry/terminal semantics, and namespaced extensions.

Executable callbacks, free-form code, and mutation after construction are
forbidden. Unknown versions and undeclared top-level fields fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from ..ir_core.canonical import CollectionSchema, CollectionSemantics

UI_UX_IR_SCHEMA_VERSION: Final = "ui-ux-ir/v1"
LEGACY_UI_UX_IR_SCHEMA_VERSION: Final = "ui-ux-ir/v0.1"
UI_UX_IR_SCHEMA_JSON_PATH: Final = Path(__file__).with_name("ui_ux_ir.schema.json")
UI_UX_IR_INTERFACE: Final = "UIUXIR@1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NAMESPACE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_-]{0,63}(\.[A-Za-z][A-Za-z0-9_-]{0,63}){0,7}$"
)
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")

# Keys that never appear in a declaration. Callbacks and free-form executable
# content are unsupported semantics for ui-ux-ir/v1.
_FORBIDDEN_EXECUTABLE_KEYS: Final = frozenset(
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

_FORBIDDEN_EXECUTABLE_KEY_PREFIXES: Final = ("on_", "handle_")


class UIIRValidationError(ValueError):
    """Raised when a UI/UX IR document violates its closed envelope contract."""


class ReviewStatus(str, Enum):
    """Human/machine review state for source and declaration trust."""

    UNREVIEWED = "unreviewed"
    MACHINE_EXTRACTED = "machine_extracted"
    HUMAN_REVIEWED = "human_reviewed"
    TRUSTED_FIXTURE = "trusted_fixture"
    QUARANTINED = "quarantined"


class CompositionEdgeKind(str, Enum):
    """Structural relationship between semantic components."""

    PARENT = "parent"
    CHILD = "child"
    SLOT = "slot"
    LABEL = "label"
    DESCRIBED_BY = "described_by"
    OWNS = "owns"
    FLOW = "flow"


class LayoutRegionKind(str, Enum):
    """Abstract layout region kinds."""

    FLOW = "flow"
    GRID = "grid"
    STACK = "stack"
    OVERLAY = "overlay"
    SPATIAL_ANCHOR = "spatial_anchor"
    AUDIO_SEQUENCE = "audio_sequence"


class AdaptationPolicy(str, Enum):
    """How a required semantic may adapt under projection loss."""

    PRESERVE = "preserve"
    ADAPT = "adapt"
    SUMMARIZE = "summarize"
    FALLBACK = "fallback"
    OMIT = "omit"


class ProgramBindingTargetKind(str, Enum):
    """Exactly one semantic target family per program binding."""

    MCP_IDL = "mcp_idl_interface_method_schema"
    INTENT_IR = "intent_ir_document_action"
    INVOCATION_TEMPLATE = "invocation_intent_template"
    LOCAL_STATE = "local_state_only_transition"
    COMPOSITE_WORKFLOW = "versioned_composite_workflow"


class TerminalOutcomeKind(str, Enum):
    """Declared terminal UX outcomes."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


class EventKind(str, Enum):
    """Bounded behavior event families."""

    INPUT = "input"
    DOMAIN = "domain"
    LIFECYCLE = "lifecycle"
    TIMER = "timer"
    PROGRAM_RESULT = "program_result"


class AuthorityKind(str, Enum):
    """Result-authority classes; non-substitutable."""

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


# Every collection in the v1 wire contract has declared semantics.
UI_UX_IR_COLLECTION_SEMANTICS: Mapping[str, CollectionSemantics] = MappingProxyType(
    {
        "UIIRDocument.sources": CollectionSemantics.SET_LIKE,
        "UIIRDocument.trust_bindings": CollectionSemantics.SET_LIKE,
        "UIIRDocument.components": CollectionSemantics.SET_LIKE,
        "UIIRDocument.composition_edges": CollectionSemantics.SET_LIKE,
        "UIIRDocument.layout_regions": CollectionSemantics.SET_LIKE,
        "UIIRDocument.layout_constraints": CollectionSemantics.SET_LIKE,
        "UIIRDocument.design_token_refs": CollectionSemantics.SET_LIKE,
        "UIIRDocument.state_variables": CollectionSemantics.SET_LIKE,
        "UIIRDocument.states": CollectionSemantics.SET_LIKE,
        "UIIRDocument.events": CollectionSemantics.SET_LIKE,
        "UIIRDocument.transitions": CollectionSemantics.SET_LIKE,
        "UIIRDocument.guards": CollectionSemantics.SET_LIKE,
        "UIIRDocument.effects": CollectionSemantics.SET_LIKE,
        "UIIRDocument.ux_tasks": CollectionSemantics.SET_LIKE,
        "UIIRDocument.journeys": CollectionSemantics.SET_LIKE,
        "UIIRDocument.success_failure_recovery": CollectionSemantics.SET_LIKE,
        "UIIRDocument.feedback_contracts": CollectionSemantics.SET_LIKE,
        "UIIRDocument.accessibility": CollectionSemantics.SET_LIKE,
        "UIIRDocument.localization": CollectionSemantics.SET_LIKE,
        "UIIRDocument.input_modality_requirements": CollectionSemantics.SET_LIKE,
        "UIIRDocument.output_modality_requirements": CollectionSemantics.SET_LIKE,
        "UIIRDocument.modality_alternatives": CollectionSemantics.SET_LIKE,
        "UIIRDocument.device_capability_requirements": CollectionSemantics.SET_LIKE,
        "UIIRDocument.adaptive_variants": CollectionSemantics.SET_LIKE,
        "UIIRDocument.data_bindings": CollectionSemantics.SET_LIKE,
        "UIIRDocument.content_references": CollectionSemantics.SET_LIKE,
        "UIIRDocument.program_bindings": CollectionSemantics.SET_LIKE,
        "UIIRDocument.intent_ir_bindings": CollectionSemantics.SET_LIKE,
        "UIIRDocument.invocation_bindings": CollectionSemantics.SET_LIKE,
        "UIIRDocument.mcp_idl_bindings": CollectionSemantics.SET_LIKE,
        "UIIRDocument.formal_constraint_refs": CollectionSemantics.SET_LIKE,
        "UIIRDocument.proof_obligation_refs": CollectionSemantics.SET_LIKE,
        "UIIRDocument.entry_components": CollectionSemantics.SET_LIKE,
        "UIIRDocument.initial_states": CollectionSemantics.SET_LIKE,
        "UIIRDocument.terminal_outcomes": CollectionSemantics.SET_LIKE,
        "UIIRDocument.tags": CollectionSemantics.SET_LIKE,
        "UIIRDocument.extensions": CollectionSemantics.SET_LIKE,
        "UIIRDocument.locale_defaults.fallback_locales": CollectionSemantics.ORDERED,
        "UISourceRef.span": CollectionSemantics.ORDERED,
        "UIComponent.child_ids": CollectionSemantics.ORDERED,
        "UIComponent.modality_binding_ids": CollectionSemantics.SET_LIKE,
        "UIComponent.data_binding_ids": CollectionSemantics.SET_LIKE,
        "UIComponent.program_binding_ids": CollectionSemantics.SET_LIKE,
        "UIComponent.feedback_ids": CollectionSemantics.SET_LIKE,
        "UIComponent.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UICompositionEdge.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UILayoutRegion.component_ids": CollectionSemantics.ORDERED,
        "UILayoutRegion.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UILayoutConstraint.region_ids": CollectionSemantics.SET_LIKE,
        "UILayoutConstraint.component_ids": CollectionSemantics.SET_LIKE,
        "UILayoutConstraint.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIStateVariable.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIState.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIEvent.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UITransition.effect_ids": CollectionSemantics.ORDERED,
        "UITransition.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIGuard.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIEffect.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIUXTask.step_component_ids": CollectionSemantics.ORDERED,
        "UIUXTask.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIJourney.task_ids": CollectionSemantics.ORDERED,
        "UIJourney.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIRecoveryPath.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIFeedbackContract.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIAccessibilityBinding.relationship_ids": CollectionSemantics.SET_LIKE,
        "UIAccessibilityBinding.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UILocalizationBinding.variable_ids": CollectionSemantics.SET_LIKE,
        "UILocalizationBinding.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIModalityRequirement.capability_ids": CollectionSemantics.SET_LIKE,
        "UIModalityRequirement.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIModalityAlternative.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIDeviceCapabilityRequirement.capability_ids": CollectionSemantics.SET_LIKE,
        "UIDeviceCapabilityRequirement.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIAdaptiveVariant.capability_predicate_ids": CollectionSemantics.SET_LIKE,
        "UIAdaptiveVariant.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIDataBinding.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIContentReference.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIProgramBinding.precondition_ids": CollectionSemantics.SET_LIKE,
        "UIProgramBinding.effect_ids": CollectionSemantics.SET_LIKE,
        "UIProgramBinding.verification_ids": CollectionSemantics.SET_LIKE,
        "UIProgramBinding.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIIntentIRBinding.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIInvocationBinding.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIMCPIDLBinding.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIFormalConstraintRef.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIProofObligationRef.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UITerminalOutcome.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UINamespacedExtension.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UIDesignTokenRef.source_ref_ids": CollectionSemantics.SET_LIKE,
        "UITrustBinding.source_ref_ids": CollectionSemantics.SET_LIKE,
    }
)

UI_UX_IR_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/sources": CollectionSemantics.SET_LIKE,
        "/trust_bindings": CollectionSemantics.SET_LIKE,
        "/trust_bindings/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/components": CollectionSemantics.SET_LIKE,
        "/components/*/child_ids": CollectionSemantics.ORDERED,
        "/components/*/modality_binding_ids": CollectionSemantics.SET_LIKE,
        "/components/*/data_binding_ids": CollectionSemantics.SET_LIKE,
        "/components/*/program_binding_ids": CollectionSemantics.SET_LIKE,
        "/components/*/feedback_ids": CollectionSemantics.SET_LIKE,
        "/components/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/composition_edges": CollectionSemantics.SET_LIKE,
        "/composition_edges/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/layout_regions": CollectionSemantics.SET_LIKE,
        "/layout_regions/*/component_ids": CollectionSemantics.ORDERED,
        "/layout_regions/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/layout_constraints": CollectionSemantics.SET_LIKE,
        "/layout_constraints/*/region_ids": CollectionSemantics.SET_LIKE,
        "/layout_constraints/*/component_ids": CollectionSemantics.SET_LIKE,
        "/layout_constraints/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/design_token_refs": CollectionSemantics.SET_LIKE,
        "/design_token_refs/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/state_variables": CollectionSemantics.SET_LIKE,
        "/state_variables/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/states": CollectionSemantics.SET_LIKE,
        "/states/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/events": CollectionSemantics.SET_LIKE,
        "/events/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/transitions": CollectionSemantics.SET_LIKE,
        "/transitions/*/effect_ids": CollectionSemantics.ORDERED,
        "/transitions/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/guards": CollectionSemantics.SET_LIKE,
        "/guards/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/effects": CollectionSemantics.SET_LIKE,
        "/effects/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/ux_tasks": CollectionSemantics.SET_LIKE,
        "/ux_tasks/*/step_component_ids": CollectionSemantics.ORDERED,
        "/ux_tasks/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/journeys": CollectionSemantics.SET_LIKE,
        "/journeys/*/task_ids": CollectionSemantics.ORDERED,
        "/journeys/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/success_failure_recovery": CollectionSemantics.SET_LIKE,
        "/success_failure_recovery/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/feedback_contracts": CollectionSemantics.SET_LIKE,
        "/feedback_contracts/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/accessibility": CollectionSemantics.SET_LIKE,
        "/accessibility/*/relationship_ids": CollectionSemantics.SET_LIKE,
        "/accessibility/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/localization": CollectionSemantics.SET_LIKE,
        "/localization/*/variable_ids": CollectionSemantics.SET_LIKE,
        "/localization/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/input_modality_requirements": CollectionSemantics.SET_LIKE,
        "/input_modality_requirements/*/capability_ids": CollectionSemantics.SET_LIKE,
        "/input_modality_requirements/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/output_modality_requirements": CollectionSemantics.SET_LIKE,
        "/output_modality_requirements/*/capability_ids": CollectionSemantics.SET_LIKE,
        "/output_modality_requirements/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/modality_alternatives": CollectionSemantics.SET_LIKE,
        "/modality_alternatives/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/device_capability_requirements": CollectionSemantics.SET_LIKE,
        "/device_capability_requirements/*/capability_ids": CollectionSemantics.SET_LIKE,
        "/device_capability_requirements/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/adaptive_variants": CollectionSemantics.SET_LIKE,
        "/adaptive_variants/*/capability_predicate_ids": CollectionSemantics.SET_LIKE,
        "/adaptive_variants/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/data_bindings": CollectionSemantics.SET_LIKE,
        "/data_bindings/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/content_references": CollectionSemantics.SET_LIKE,
        "/content_references/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/program_bindings": CollectionSemantics.SET_LIKE,
        "/program_bindings/*/precondition_ids": CollectionSemantics.SET_LIKE,
        "/program_bindings/*/effect_ids": CollectionSemantics.SET_LIKE,
        "/program_bindings/*/verification_ids": CollectionSemantics.SET_LIKE,
        "/program_bindings/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/intent_ir_bindings": CollectionSemantics.SET_LIKE,
        "/intent_ir_bindings/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/invocation_bindings": CollectionSemantics.SET_LIKE,
        "/invocation_bindings/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/mcp_idl_bindings": CollectionSemantics.SET_LIKE,
        "/mcp_idl_bindings/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/formal_constraint_refs": CollectionSemantics.SET_LIKE,
        "/formal_constraint_refs/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/proof_obligation_refs": CollectionSemantics.SET_LIKE,
        "/proof_obligation_refs/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/entry_components": CollectionSemantics.SET_LIKE,
        "/initial_states": CollectionSemantics.SET_LIKE,
        "/terminal_outcomes": CollectionSemantics.SET_LIKE,
        "/terminal_outcomes/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/tags": CollectionSemantics.SET_LIKE,
        "/extensions": CollectionSemantics.SET_LIKE,
        "/extensions/*/source_ref_ids": CollectionSemantics.SET_LIKE,
        "/locale_defaults/fallback_locales": CollectionSemantics.ORDERED,
    },
    require_declared=True,
)

# Closed top-level wire keys for ui-ux-ir/v1.
UIIR_DOCUMENT_FIELDS: Final = frozenset(
    {
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
    }
)

UIIR_REQUIRED_PATHS: Final = frozenset(
    {
        "schema_version",
        "document_id",
        "title",
        "sources",
        "components",
        "entry_components",
        "terminal_outcomes",
    }
)


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Character span in a separately stored source artifact."""

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
    """Immutable reference to evidence used by one UI/UX IR document."""

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
        _validate_enum("UISourceRef.review_status", self.review_status, ReviewStatus)
        for name in ("source_uri", "source_id", "source_revision"):
            _validate_non_empty_string(f"UISourceRef.{name}", getattr(self, name))
        for name in ("container_uri", "content_cid", "license_expression"):
            _validate_string(f"UISourceRef.{name}", getattr(self, name))
        _validate_sha256("UISourceRef.content_sha256", self.content_sha256)
        _validate_string("UISourceRef.container_sha256", self.container_sha256)
        if self.container_sha256:
            _validate_sha256("UISourceRef.container_sha256", self.container_sha256)
        if self.span is not None:
            if not isinstance(self.span, SourceSpan):
                raise UIIRValidationError(
                    "UISourceRef.span must be a SourceSpan or None"
                )
            self.span.validate()
        _reject_executable_payload(self.to_dict(), "UISourceRef")

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
class UILocaleDefaults:
    """Default locale and ordered fallback chain."""

    default_locale: str = "en"
    fallback_locales: tuple[str, ...] = ()
    text_direction: str = "ltr"

    def validate(self) -> None:
        _validate_non_empty_string(
            "UILocaleDefaults.default_locale", self.default_locale
        )
        _require_tuple(
            "UIIRDocument.locale_defaults.fallback_locales", self.fallback_locales
        )
        _validate_string_items(
            "UILocaleDefaults.fallback_locales", self.fallback_locales
        )
        _validate_non_empty_string(
            "UILocaleDefaults.text_direction", self.text_direction
        )
        if self.text_direction not in {"ltr", "rtl", "auto"}:
            raise UIIRValidationError(
                "UILocaleDefaults.text_direction must be ltr, rtl, or auto"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_locale": self.default_locale,
            "fallback_locales": list(self.fallback_locales),
            "text_direction": self.text_direction,
        }


@dataclass(frozen=True, slots=True)
class UIProducer:
    """Producer of the declaration (tooling, adapter, or authoring system)."""

    producer_id: str
    name: str
    version: str = ""

    def validate(self) -> None:
        _validate_identifier("UIProducer.producer_id", self.producer_id)
        _validate_non_empty_string("UIProducer.name", self.name)
        _validate_string("UIProducer.version", self.version)

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "producer_id": self.producer_id,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class UIConfiguration:
    """Immutable configuration binding for the declaration."""

    configuration_id: str
    profile: str = "default"
    settings: Mapping[str, Any] = MappingProxyType({})

    def validate(self) -> None:
        _validate_identifier("UIConfiguration.configuration_id", self.configuration_id)
        _validate_non_empty_string("UIConfiguration.profile", self.profile)
        if not isinstance(self.settings, Mapping):
            raise UIIRValidationError("UIConfiguration.settings must be a mapping")
        _reject_executable_payload(dict(self.settings), "UIConfiguration.settings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration_id": self.configuration_id,
            "profile": self.profile,
            "settings": dict(self.settings),
        }


@dataclass(frozen=True, slots=True)
class UIReviewBinding:
    """Review status attached to the declaration itself."""

    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    reviewer: str = ""
    notes: str = ""

    def validate(self) -> None:
        _validate_enum(
            "UIReviewBinding.review_status", self.review_status, ReviewStatus
        )
        _validate_string("UIReviewBinding.reviewer", self.reviewer)
        _validate_string("UIReviewBinding.notes", self.notes)

    def to_dict(self) -> dict[str, str]:
        return {
            "notes": self.notes,
            "review_status": self.review_status.value,
            "reviewer": self.reviewer,
        }


@dataclass(frozen=True, slots=True)
class UITrustBinding:
    """Typed trust binding; never confuses authority kinds."""

    trust_id: str
    authority_kind: AuthorityKind
    subject_ref: str
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UITrustBinding.trust_id", self.trust_id)
        _validate_enum(
            "UITrustBinding.authority_kind", self.authority_kind, AuthorityKind
        )
        _validate_non_empty_string("UITrustBinding.subject_ref", self.subject_ref)
        _require_tuple("UITrustBinding.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UITrustBinding.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_kind": self.authority_kind.value,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "subject_ref": self.subject_ref,
            "trust_id": self.trust_id,
        }


@dataclass(frozen=True, slots=True)
class UIComponent:
    """Semantic component node (not a framework widget)."""

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
        _validate_non_empty_string("UIComponent.role", self.role)
        if not _IDENTIFIER_RE.fullmatch(self.role) and not self.role.startswith(
            "aria:"
        ):
            # Allow ARIA tokens and namespaced domain roles.
            if ":" not in self.role and "." not in self.role:
                raise UIIRValidationError(
                    f"UIComponent {self.component_id!r}.role is not a stable role token"
                )
        for name in (
            "purpose",
            "accessible_name_ref",
            "accessible_description_ref",
            "parent_id",
            "privacy_sensitivity",
            "presentation_classification",
        ):
            _validate_string(f"UIComponent.{name}", getattr(self, name))
        if self.parent_id:
            _validate_identifier("UIComponent.parent_id", self.parent_id)
        for field_name in (
            "child_ids",
            "modality_binding_ids",
            "data_binding_ids",
            "program_binding_ids",
            "feedback_ids",
            "source_ref_ids",
        ):
            values = getattr(self, field_name)
            _require_tuple(f"UIComponent.{field_name}", values)
            if field_name == "child_ids":
                _validate_identifier_items(f"UIComponent.{field_name}", values)
            else:
                _validate_identifier_items(f"UIComponent.{field_name}", values)
                if field_name != "source_ref_ids":
                    _require_unique(values, f"UIComponent.{field_name} member")
        _require_unique(self.source_ref_ids, "UIComponent.source_ref_ids member")
        _reject_executable_payload(self.to_dict(), f"UIComponent {self.component_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessible_description_ref": self.accessible_description_ref,
            "accessible_name_ref": self.accessible_name_ref,
            "child_ids": list(self.child_ids),
            "component_id": self.component_id,
            "data_binding_ids": sorted(set(self.data_binding_ids)),
            "feedback_ids": sorted(set(self.feedback_ids)),
            "modality_binding_ids": sorted(set(self.modality_binding_ids)),
            "parent_id": self.parent_id,
            "presentation_classification": self.presentation_classification,
            "privacy_sensitivity": self.privacy_sensitivity,
            "program_binding_ids": sorted(set(self.program_binding_ids)),
            "purpose": self.purpose,
            "role": self.role,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UICompositionEdge:
    """Composition edge between components."""

    edge_id: str
    kind: CompositionEdgeKind
    source_component_id: str
    target_component_id: str
    slot_name: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UICompositionEdge.edge_id", self.edge_id)
        _validate_enum("UICompositionEdge.kind", self.kind, CompositionEdgeKind)
        _validate_identifier(
            "UICompositionEdge.source_component_id", self.source_component_id
        )
        _validate_identifier(
            "UICompositionEdge.target_component_id", self.target_component_id
        )
        _validate_string("UICompositionEdge.slot_name", self.slot_name)
        _require_tuple("UICompositionEdge.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UICompositionEdge.source_ref_ids", self.source_ref_ids
        )
        _require_unique(
            self.source_ref_ids, "UICompositionEdge.source_ref_ids member"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "kind": self.kind.value,
            "slot_name": self.slot_name,
            "source_component_id": self.source_component_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "target_component_id": self.target_component_id,
        }


@dataclass(frozen=True, slots=True)
class UILayoutRegion:
    """Abstract layout region over components."""

    region_id: str
    kind: LayoutRegionKind
    component_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UILayoutRegion.region_id", self.region_id)
        _validate_enum("UILayoutRegion.kind", self.kind, LayoutRegionKind)
        _require_tuple("UILayoutRegion.component_ids", self.component_ids)
        _validate_identifier_items(
            "UILayoutRegion.component_ids", self.component_ids
        )
        _require_tuple("UILayoutRegion.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UILayoutRegion.source_ref_ids", self.source_ref_ids
        )
        _require_unique(
            self.source_ref_ids, "UILayoutRegion.source_ref_ids member"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_ids": list(self.component_ids),
            "kind": self.kind.value,
            "region_id": self.region_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UILayoutConstraint:
    """Layout constraint predicate over regions/components."""

    constraint_id: str
    kind: str
    region_ids: tuple[str, ...] = ()
    component_ids: tuple[str, ...] = ()
    adaptation_policy: AdaptationPolicy = AdaptationPolicy.PRESERVE
    expression_ref: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UILayoutConstraint.constraint_id", self.constraint_id)
        _validate_non_empty_string("UILayoutConstraint.kind", self.kind)
        _validate_enum(
            "UILayoutConstraint.adaptation_policy",
            self.adaptation_policy,
            AdaptationPolicy,
        )
        _validate_string("UILayoutConstraint.expression_ref", self.expression_ref)
        if self.expression_ref:
            _validate_identifier(
                "UILayoutConstraint.expression_ref", self.expression_ref
            )
        for field_name in ("region_ids", "component_ids", "source_ref_ids"):
            values = getattr(self, field_name)
            _require_tuple(f"UILayoutConstraint.{field_name}", values)
            _validate_identifier_items(f"UILayoutConstraint.{field_name}", values)
            _require_unique(values, f"UILayoutConstraint.{field_name} member")
        _reject_executable_payload(
            self.to_dict(), f"UILayoutConstraint {self.constraint_id}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adaptation_policy": self.adaptation_policy.value,
            "component_ids": sorted(set(self.component_ids)),
            "constraint_id": self.constraint_id,
            "expression_ref": self.expression_ref,
            "kind": self.kind,
            "region_ids": sorted(set(self.region_ids)),
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIDesignTokenRef:
    """Design-token reference (not device pixels)."""

    token_id: str
    category: str
    token_name: str
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIDesignTokenRef.token_id", self.token_id)
        _validate_non_empty_string("UIDesignTokenRef.category", self.category)
        _validate_non_empty_string("UIDesignTokenRef.token_name", self.token_name)
        _require_tuple("UIDesignTokenRef.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIDesignTokenRef.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "token_id": self.token_id,
            "token_name": self.token_name,
        }


@dataclass(frozen=True, slots=True)
class UIStateVariable:
    """Typed state variable in the behavior model."""

    variable_id: str
    value_type: str
    derived: bool = False
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIStateVariable.variable_id", self.variable_id)
        _validate_non_empty_string("UIStateVariable.value_type", self.value_type)
        if not isinstance(self.derived, bool):
            raise UIIRValidationError("UIStateVariable.derived must be a boolean")
        _require_tuple("UIStateVariable.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIStateVariable.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived": self.derived,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "value_type": self.value_type,
            "variable_id": self.variable_id,
        }


@dataclass(frozen=True, slots=True)
class UIState:
    """Named state in a bounded hierarchical state machine."""

    state_id: str
    region_id: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIState.state_id", self.state_id)
        _validate_string("UIState.region_id", self.region_id)
        if self.region_id:
            _validate_identifier("UIState.region_id", self.region_id)
        _require_tuple("UIState.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items("UIState.source_ref_ids", self.source_ref_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "state_id": self.state_id,
        }


@dataclass(frozen=True, slots=True)
class UIEvent:
    """Typed event that may trigger transitions."""

    event_id: str
    kind: EventKind
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIEvent.event_id", self.event_id)
        _validate_enum("UIEvent.kind", self.kind, EventKind)
        _require_tuple("UIEvent.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items("UIEvent.source_ref_ids", self.source_ref_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind.value,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIGuard:
    """Guard referencing facts or formal constraints (no free-form code)."""

    guard_id: str
    constraint_ref: str = ""
    formal_constraint_id: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIGuard.guard_id", self.guard_id)
        _validate_string("UIGuard.constraint_ref", self.constraint_ref)
        _validate_string("UIGuard.formal_constraint_id", self.formal_constraint_id)
        if self.constraint_ref:
            _validate_identifier("UIGuard.constraint_ref", self.constraint_ref)
        if self.formal_constraint_id:
            _validate_identifier(
                "UIGuard.formal_constraint_id", self.formal_constraint_id
            )
        if not self.constraint_ref and not self.formal_constraint_id:
            raise UIIRValidationError(
                f"UIGuard {self.guard_id!r} requires constraint_ref or formal_constraint_id"
            )
        _require_tuple("UIGuard.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items("UIGuard.source_ref_ids", self.source_ref_ids)
        _reject_executable_payload(self.to_dict(), f"UIGuard {self.guard_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_ref": self.constraint_ref,
            "formal_constraint_id": self.formal_constraint_id,
            "guard_id": self.guard_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIEffect:
    """Effect referencing program bindings or local state transitions."""

    effect_id: str
    program_binding_id: str = ""
    local_state_transition: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIEffect.effect_id", self.effect_id)
        _validate_string("UIEffect.program_binding_id", self.program_binding_id)
        _validate_string(
            "UIEffect.local_state_transition", self.local_state_transition
        )
        if self.program_binding_id:
            _validate_identifier(
                "UIEffect.program_binding_id", self.program_binding_id
            )
        if self.local_state_transition:
            _validate_identifier(
                "UIEffect.local_state_transition", self.local_state_transition
            )
        if not self.program_binding_id and not self.local_state_transition:
            raise UIIRValidationError(
                f"UIEffect {self.effect_id!r} requires program_binding_id or local_state_transition"
            )
        _require_tuple("UIEffect.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items("UIEffect.source_ref_ids", self.source_ref_ids)
        _reject_executable_payload(self.to_dict(), f"UIEffect {self.effect_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "local_state_transition": self.local_state_transition,
            "program_binding_id": self.program_binding_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UITransition:
    """Deterministic state transition with priority."""

    transition_id: str
    source_state_id: str
    target_state_id: str
    event_id: str = ""
    guard_id: str = ""
    effect_ids: tuple[str, ...] = ()
    priority: int = 0
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UITransition.transition_id", self.transition_id)
        _validate_identifier("UITransition.source_state_id", self.source_state_id)
        _validate_identifier("UITransition.target_state_id", self.target_state_id)
        _validate_string("UITransition.event_id", self.event_id)
        _validate_string("UITransition.guard_id", self.guard_id)
        if self.event_id:
            _validate_identifier("UITransition.event_id", self.event_id)
        if self.guard_id:
            _validate_identifier("UITransition.guard_id", self.guard_id)
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise UIIRValidationError("UITransition.priority must be an integer")
        _require_tuple("UITransition.effect_ids", self.effect_ids)
        _validate_identifier_items("UITransition.effect_ids", self.effect_ids)
        _require_tuple("UITransition.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UITransition.source_ref_ids", self.source_ref_ids
        )
        _reject_executable_payload(
            self.to_dict(), f"UITransition {self.transition_id}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_ids": list(self.effect_ids),
            "event_id": self.event_id,
            "guard_id": self.guard_id,
            "priority": self.priority,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "source_state_id": self.source_state_id,
            "target_state_id": self.target_state_id,
            "transition_id": self.transition_id,
        }


@dataclass(frozen=True, slots=True)
class UIUXTask:
    """UX task over ordered component steps."""

    task_id: str
    name: str
    step_component_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIUXTask.task_id", self.task_id)
        _validate_non_empty_string("UIUXTask.name", self.name)
        _require_tuple("UIUXTask.step_component_ids", self.step_component_ids)
        _validate_identifier_items(
            "UIUXTask.step_component_ids", self.step_component_ids
        )
        _require_tuple("UIUXTask.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items("UIUXTask.source_ref_ids", self.source_ref_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "step_component_ids": list(self.step_component_ids),
            "task_id": self.task_id,
        }


@dataclass(frozen=True, slots=True)
class UIJourney:
    """UX journey over ordered tasks."""

    journey_id: str
    name: str
    task_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIJourney.journey_id", self.journey_id)
        _validate_non_empty_string("UIJourney.name", self.name)
        _require_tuple("UIJourney.task_ids", self.task_ids)
        _validate_identifier_items("UIJourney.task_ids", self.task_ids)
        _require_tuple("UIJourney.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items("UIJourney.source_ref_ids", self.source_ref_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "journey_id": self.journey_id,
            "name": self.name,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "task_ids": list(self.task_ids),
        }


@dataclass(frozen=True, slots=True)
class UIRecoveryPath:
    """Success, failure, or recovery path contract."""

    path_id: str
    kind: TerminalOutcomeKind
    target_outcome_id: str = ""
    recovery_component_id: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIRecoveryPath.path_id", self.path_id)
        _validate_enum("UIRecoveryPath.kind", self.kind, TerminalOutcomeKind)
        _validate_string("UIRecoveryPath.target_outcome_id", self.target_outcome_id)
        _validate_string(
            "UIRecoveryPath.recovery_component_id", self.recovery_component_id
        )
        if self.target_outcome_id:
            _validate_identifier(
                "UIRecoveryPath.target_outcome_id", self.target_outcome_id
            )
        if self.recovery_component_id:
            _validate_identifier(
                "UIRecoveryPath.recovery_component_id", self.recovery_component_id
            )
        _require_tuple("UIRecoveryPath.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIRecoveryPath.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "path_id": self.path_id,
            "recovery_component_id": self.recovery_component_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "target_outcome_id": self.target_outcome_id,
        }


@dataclass(frozen=True, slots=True)
class UIFeedbackContract:
    """Feedback channel and error/recovery surface contract."""

    feedback_id: str
    channel: str
    component_id: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIFeedbackContract.feedback_id", self.feedback_id)
        _validate_non_empty_string("UIFeedbackContract.channel", self.channel)
        _validate_string("UIFeedbackContract.component_id", self.component_id)
        if self.component_id:
            _validate_identifier(
                "UIFeedbackContract.component_id", self.component_id
            )
        _require_tuple("UIFeedbackContract.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIFeedbackContract.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "component_id": self.component_id,
            "feedback_id": self.feedback_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIAccessibilityBinding:
    """Accessibility semantics for a component."""

    accessibility_id: str
    component_id: str
    role: str = ""
    name_ref: str = ""
    description_ref: str = ""
    relationship_ids: tuple[str, ...] = ()
    live_region: bool = False
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier(
            "UIAccessibilityBinding.accessibility_id", self.accessibility_id
        )
        _validate_identifier(
            "UIAccessibilityBinding.component_id", self.component_id
        )
        for name in ("role", "name_ref", "description_ref"):
            _validate_string(f"UIAccessibilityBinding.{name}", getattr(self, name))
        if not isinstance(self.live_region, bool):
            raise UIIRValidationError(
                "UIAccessibilityBinding.live_region must be a boolean"
            )
        _require_tuple(
            "UIAccessibilityBinding.relationship_ids", self.relationship_ids
        )
        _validate_identifier_items(
            "UIAccessibilityBinding.relationship_ids", self.relationship_ids
        )
        _require_tuple("UIAccessibilityBinding.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIAccessibilityBinding.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessibility_id": self.accessibility_id,
            "component_id": self.component_id,
            "description_ref": self.description_ref,
            "live_region": self.live_region,
            "name_ref": self.name_ref,
            "relationship_ids": sorted(set(self.relationship_ids)),
            "role": self.role,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UILocalizationBinding:
    """Translatable message binding."""

    localization_id: str
    message_id: str
    default_text: str = ""
    variable_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier(
            "UILocalizationBinding.localization_id", self.localization_id
        )
        _validate_non_empty_string(
            "UILocalizationBinding.message_id", self.message_id
        )
        _validate_string("UILocalizationBinding.default_text", self.default_text)
        _require_tuple("UILocalizationBinding.variable_ids", self.variable_ids)
        _validate_identifier_items(
            "UILocalizationBinding.variable_ids", self.variable_ids
        )
        _require_tuple("UILocalizationBinding.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UILocalizationBinding.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_text": self.default_text,
            "localization_id": self.localization_id,
            "message_id": self.message_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "variable_ids": sorted(set(self.variable_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIModalityRequirement:
    """Input or output modality requirement."""

    requirement_id: str
    direction: str
    capability_ids: tuple[str, ...]
    essential: bool = True
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier(
            "UIModalityRequirement.requirement_id", self.requirement_id
        )
        if self.direction not in {"input", "output"}:
            raise UIIRValidationError(
                "UIModalityRequirement.direction must be 'input' or 'output'"
            )
        if not self.capability_ids:
            raise UIIRValidationError(
                f"UIModalityRequirement {self.requirement_id!r}.capability_ids must not be empty"
            )
        _require_tuple(
            "UIModalityRequirement.capability_ids", self.capability_ids
        )
        _validate_identifier_items(
            "UIModalityRequirement.capability_ids", self.capability_ids
        )
        _require_unique(
            self.capability_ids, "UIModalityRequirement.capability_ids member"
        )
        if not isinstance(self.essential, bool):
            raise UIIRValidationError(
                "UIModalityRequirement.essential must be a boolean"
            )
        _require_tuple("UIModalityRequirement.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIModalityRequirement.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_ids": sorted(set(self.capability_ids)),
            "direction": self.direction,
            "essential": self.essential,
            "requirement_id": self.requirement_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIModalityAlternative:
    """Alternative modality for an essential action/output."""

    alternative_id: str
    primary_requirement_id: str
    alternative_requirement_id: str
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier(
            "UIModalityAlternative.alternative_id", self.alternative_id
        )
        _validate_identifier(
            "UIModalityAlternative.primary_requirement_id",
            self.primary_requirement_id,
        )
        _validate_identifier(
            "UIModalityAlternative.alternative_requirement_id",
            self.alternative_requirement_id,
        )
        if self.primary_requirement_id == self.alternative_requirement_id:
            raise UIIRValidationError(
                f"UIModalityAlternative {self.alternative_id!r} primary and alternative must differ"
            )
        _require_tuple("UIModalityAlternative.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIModalityAlternative.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternative_id": self.alternative_id,
            "alternative_requirement_id": self.alternative_requirement_id,
            "primary_requirement_id": self.primary_requirement_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIDeviceCapabilityRequirement:
    """Device capability requirement for adaptive projection."""

    requirement_id: str
    capability_ids: tuple[str, ...]
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier(
            "UIDeviceCapabilityRequirement.requirement_id", self.requirement_id
        )
        if not self.capability_ids:
            raise UIIRValidationError(
                f"UIDeviceCapabilityRequirement {self.requirement_id!r}.capability_ids must not be empty"
            )
        _require_tuple(
            "UIDeviceCapabilityRequirement.capability_ids", self.capability_ids
        )
        _validate_identifier_items(
            "UIDeviceCapabilityRequirement.capability_ids", self.capability_ids
        )
        _require_tuple(
            "UIDeviceCapabilityRequirement.source_ref_ids", self.source_ref_ids
        )
        _validate_identifier_items(
            "UIDeviceCapabilityRequirement.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_ids": sorted(set(self.capability_ids)),
            "requirement_id": self.requirement_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIAdaptiveVariant:
    """Adaptive variant selected by capability predicates."""

    variant_id: str
    adaptation_policy: AdaptationPolicy
    capability_predicate_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIAdaptiveVariant.variant_id", self.variant_id)
        _validate_enum(
            "UIAdaptiveVariant.adaptation_policy",
            self.adaptation_policy,
            AdaptationPolicy,
        )
        _require_tuple(
            "UIAdaptiveVariant.capability_predicate_ids",
            self.capability_predicate_ids,
        )
        _validate_identifier_items(
            "UIAdaptiveVariant.capability_predicate_ids",
            self.capability_predicate_ids,
        )
        _require_tuple("UIAdaptiveVariant.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIAdaptiveVariant.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adaptation_policy": self.adaptation_policy.value,
            "capability_predicate_ids": sorted(set(self.capability_predicate_ids)),
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "variant_id": self.variant_id,
        }


@dataclass(frozen=True, slots=True)
class UIDataBinding:
    """Data source/query/update reference (no executable query code)."""

    binding_id: str
    kind: str
    resource_ref: str
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIDataBinding.binding_id", self.binding_id)
        _validate_non_empty_string("UIDataBinding.kind", self.kind)
        _validate_non_empty_string("UIDataBinding.resource_ref", self.resource_ref)
        _require_tuple("UIDataBinding.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIDataBinding.source_ref_ids", self.source_ref_ids
        )
        _reject_executable_payload(self.to_dict(), f"UIDataBinding {self.binding_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "kind": self.kind,
            "resource_ref": self.resource_ref,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIContentReference:
    """Content reference for labels, media, and messages."""

    content_id: str
    kind: str
    resource_ref: str
    localization_id: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIContentReference.content_id", self.content_id)
        _validate_non_empty_string("UIContentReference.kind", self.kind)
        _validate_non_empty_string(
            "UIContentReference.resource_ref", self.resource_ref
        )
        _validate_string(
            "UIContentReference.localization_id", self.localization_id
        )
        if self.localization_id:
            _validate_identifier(
                "UIContentReference.localization_id", self.localization_id
            )
        _require_tuple("UIContentReference.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIContentReference.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "kind": self.kind,
            "localization_id": self.localization_id,
            "resource_ref": self.resource_ref,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIProgramBinding:
    """Program action binding with exactly one semantic target family."""

    binding_id: str
    target_kind: ProgramBindingTargetKind
    target_ref: str
    risk_class: str = "low"
    confirmation_class: str = "none"
    precondition_ids: tuple[str, ...] = ()
    effect_ids: tuple[str, ...] = ()
    verification_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIProgramBinding.binding_id", self.binding_id)
        _validate_enum(
            "UIProgramBinding.target_kind",
            self.target_kind,
            ProgramBindingTargetKind,
        )
        _validate_non_empty_string("UIProgramBinding.target_ref", self.target_ref)
        _validate_non_empty_string("UIProgramBinding.risk_class", self.risk_class)
        _validate_non_empty_string(
            "UIProgramBinding.confirmation_class", self.confirmation_class
        )
        for field_name in (
            "precondition_ids",
            "effect_ids",
            "verification_ids",
            "source_ref_ids",
        ):
            values = getattr(self, field_name)
            _require_tuple(f"UIProgramBinding.{field_name}", values)
            _validate_identifier_items(f"UIProgramBinding.{field_name}", values)
            _require_unique(values, f"UIProgramBinding.{field_name} member")
        _reject_executable_payload(
            self.to_dict(), f"UIProgramBinding {self.binding_id}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "confirmation_class": self.confirmation_class,
            "effect_ids": sorted(set(self.effect_ids)),
            "precondition_ids": sorted(set(self.precondition_ids)),
            "risk_class": self.risk_class,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "target_kind": self.target_kind.value,
            "target_ref": self.target_ref,
            "verification_ids": sorted(set(self.verification_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIIntentIRBinding:
    """Stable Intent IR document/action reference."""

    binding_id: str
    intent_document_id: str
    intent_action_id: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIIntentIRBinding.binding_id", self.binding_id)
        _validate_identifier(
            "UIIntentIRBinding.intent_document_id", self.intent_document_id
        )
        _validate_string("UIIntentIRBinding.intent_action_id", self.intent_action_id)
        if self.intent_action_id:
            _validate_identifier(
                "UIIntentIRBinding.intent_action_id", self.intent_action_id
            )
        _require_tuple("UIIntentIRBinding.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIIntentIRBinding.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "intent_action_id": self.intent_action_id,
            "intent_document_id": self.intent_document_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIInvocationBinding:
    """Invocation Intent template reference."""

    binding_id: str
    template_cid: str
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIInvocationBinding.binding_id", self.binding_id)
        _validate_non_empty_string(
            "UIInvocationBinding.template_cid", self.template_cid
        )
        _require_tuple("UIInvocationBinding.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIInvocationBinding.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "template_cid": self.template_cid,
        }


@dataclass(frozen=True, slots=True)
class UIMCPIDLBinding:
    """MCP-IDL interface method and schema reference."""

    binding_id: str
    interface_cid: str
    method_name: str
    argument_schema_ref: str = ""
    result_schema_ref: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UIMCPIDLBinding.binding_id", self.binding_id)
        _validate_non_empty_string(
            "UIMCPIDLBinding.interface_cid", self.interface_cid
        )
        _validate_non_empty_string("UIMCPIDLBinding.method_name", self.method_name)
        for name in ("argument_schema_ref", "result_schema_ref"):
            _validate_string(f"UIMCPIDLBinding.{name}", getattr(self, name))
        _require_tuple("UIMCPIDLBinding.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIMCPIDLBinding.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "argument_schema_ref": self.argument_schema_ref,
            "binding_id": self.binding_id,
            "interface_cid": self.interface_cid,
            "method_name": self.method_name,
            "result_schema_ref": self.result_schema_ref,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIFormalConstraintRef:
    """Formal constraint reference for guards and obligations."""

    constraint_id: str
    view: str
    formula_ref: str
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier(
            "UIFormalConstraintRef.constraint_id", self.constraint_id
        )
        _validate_non_empty_string("UIFormalConstraintRef.view", self.view)
        _validate_non_empty_string(
            "UIFormalConstraintRef.formula_ref", self.formula_ref
        )
        _require_tuple("UIFormalConstraintRef.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIFormalConstraintRef.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "formula_ref": self.formula_ref,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "view": self.view,
        }


@dataclass(frozen=True, slots=True)
class UIProofObligationRef:
    """Proof obligation reference linked to formal constraints."""

    obligation_id: str
    constraint_id: str
    prover: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier(
            "UIProofObligationRef.obligation_id", self.obligation_id
        )
        _validate_identifier(
            "UIProofObligationRef.constraint_id", self.constraint_id
        )
        _validate_string("UIProofObligationRef.prover", self.prover)
        _require_tuple("UIProofObligationRef.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UIProofObligationRef.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "obligation_id": self.obligation_id,
            "prover": self.prover,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UITerminalOutcome:
    """Declared terminal outcome of the UI interaction."""

    outcome_id: str
    kind: TerminalOutcomeKind
    description: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UITerminalOutcome.outcome_id", self.outcome_id)
        _validate_enum("UITerminalOutcome.kind", self.kind, TerminalOutcomeKind)
        _validate_string("UITerminalOutcome.description", self.description)
        _require_tuple("UITerminalOutcome.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UITerminalOutcome.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "kind": self.kind.value,
            "outcome_id": self.outcome_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UINamespacedExtension:
    """Versioned, namespaced extension record (declaration content).

    Extensions affect canonical identity. Observations, telemetry, projections,
    and proof/policy results are not extensions and must not appear here.
    """

    extension_id: str
    namespace: str
    version: str
    payload: Mapping[str, Any] = MappingProxyType({})
    required: bool = False
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("UINamespacedExtension.extension_id", self.extension_id)
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
        if not isinstance(self.payload, Mapping):
            raise UIIRValidationError(
                "UINamespacedExtension.payload must be a mapping"
            )
        if not isinstance(self.required, bool):
            raise UIIRValidationError(
                "UINamespacedExtension.required must be a boolean"
            )
        _reject_executable_payload(
            dict(self.payload), f"UINamespacedExtension {self.extension_id}.payload"
        )
        # Fail closed for derived-runtime artifacts disguised as extensions.
        banned_namespaces = {
            "observation",
            "telemetry",
            "projection",
            "proof",
            "policy_result",
            "runtime",
        }
        root = self.namespace.split(".", 1)[0]
        if root in banned_namespaces:
            raise UIIRValidationError(
                f"UINamespacedExtension namespace {self.namespace!r} is not declaration content"
            )
        _require_tuple("UINamespacedExtension.source_ref_ids", self.source_ref_ids)
        _validate_identifier_items(
            "UINamespacedExtension.source_ref_ids", self.source_ref_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "extension_id": self.extension_id,
            "namespace": self.namespace,
            "payload": dict(self.payload),
            "required": self.required,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class UIIRDocument:
    """Immutable closed UI/UX IR v1 declaration envelope."""

    document_id: str
    title: str
    sources: tuple[UISourceRef, ...]
    components: tuple[UIComponent, ...]
    entry_components: tuple[str, ...]
    terminal_outcomes: tuple[UITerminalOutcome, ...]
    schema_version: str = UI_UX_IR_SCHEMA_VERSION
    locale_defaults: UILocaleDefaults = UILocaleDefaults()
    tags: tuple[str, ...] = ()
    producer: UIProducer | None = None
    configuration: UIConfiguration | None = None
    review: UIReviewBinding = UIReviewBinding()
    trust_bindings: tuple[UITrustBinding, ...] = ()
    composition_edges: tuple[UICompositionEdge, ...] = ()
    layout_regions: tuple[UILayoutRegion, ...] = ()
    layout_constraints: tuple[UILayoutConstraint, ...] = ()
    design_token_refs: tuple[UIDesignTokenRef, ...] = ()
    state_variables: tuple[UIStateVariable, ...] = ()
    states: tuple[UIState, ...] = ()
    events: tuple[UIEvent, ...] = ()
    transitions: tuple[UITransition, ...] = ()
    guards: tuple[UIGuard, ...] = ()
    effects: tuple[UIEffect, ...] = ()
    ux_tasks: tuple[UIUXTask, ...] = ()
    journeys: tuple[UIJourney, ...] = ()
    success_failure_recovery: tuple[UIRecoveryPath, ...] = ()
    feedback_contracts: tuple[UIFeedbackContract, ...] = ()
    accessibility: tuple[UIAccessibilityBinding, ...] = ()
    localization: tuple[UILocalizationBinding, ...] = ()
    input_modality_requirements: tuple[UIModalityRequirement, ...] = ()
    output_modality_requirements: tuple[UIModalityRequirement, ...] = ()
    modality_alternatives: tuple[UIModalityAlternative, ...] = ()
    device_capability_requirements: tuple[UIDeviceCapabilityRequirement, ...] = ()
    adaptive_variants: tuple[UIAdaptiveVariant, ...] = ()
    data_bindings: tuple[UIDataBinding, ...] = ()
    content_references: tuple[UIContentReference, ...] = ()
    program_bindings: tuple[UIProgramBinding, ...] = ()
    intent_ir_bindings: tuple[UIIntentIRBinding, ...] = ()
    invocation_bindings: tuple[UIInvocationBinding, ...] = ()
    mcp_idl_bindings: tuple[UIMCPIDLBinding, ...] = ()
    formal_constraint_refs: tuple[UIFormalConstraintRef, ...] = ()
    proof_obligation_refs: tuple[UIProofObligationRef, ...] = ()
    initial_states: tuple[str, ...] = ()
    extensions: tuple[UINamespacedExtension, ...] = ()

    def validate(self) -> None:
        validate_ui_ir(self)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-ready closed envelope payload."""

        payload = {
            "accessibility": [
                item.to_dict()
                for item in sorted(
                    self.accessibility, key=lambda item: item.accessibility_id
                )
            ],
            "adaptive_variants": [
                item.to_dict()
                for item in sorted(
                    self.adaptive_variants, key=lambda item: item.variant_id
                )
            ],
            "components": [
                item.to_dict()
                for item in sorted(
                    self.components, key=lambda item: item.component_id
                )
            ],
            "composition_edges": [
                item.to_dict()
                for item in sorted(
                    self.composition_edges, key=lambda item: item.edge_id
                )
            ],
            "configuration": (
                self.configuration.to_dict() if self.configuration else None
            ),
            "content_references": [
                item.to_dict()
                for item in sorted(
                    self.content_references, key=lambda item: item.content_id
                )
            ],
            "data_bindings": [
                item.to_dict()
                for item in sorted(
                    self.data_bindings, key=lambda item: item.binding_id
                )
            ],
            "design_token_refs": [
                item.to_dict()
                for item in sorted(
                    self.design_token_refs, key=lambda item: item.token_id
                )
            ],
            "device_capability_requirements": [
                item.to_dict()
                for item in sorted(
                    self.device_capability_requirements,
                    key=lambda item: item.requirement_id,
                )
            ],
            "document_id": self.document_id,
            "effects": [
                item.to_dict()
                for item in sorted(self.effects, key=lambda item: item.effect_id)
            ],
            "entry_components": sorted(set(self.entry_components)),
            "events": [
                item.to_dict()
                for item in sorted(self.events, key=lambda item: item.event_id)
            ],
            "extensions": [
                item.to_dict()
                for item in sorted(
                    self.extensions, key=lambda item: item.extension_id
                )
            ],
            "feedback_contracts": [
                item.to_dict()
                for item in sorted(
                    self.feedback_contracts, key=lambda item: item.feedback_id
                )
            ],
            "formal_constraint_refs": [
                item.to_dict()
                for item in sorted(
                    self.formal_constraint_refs, key=lambda item: item.constraint_id
                )
            ],
            "guards": [
                item.to_dict()
                for item in sorted(self.guards, key=lambda item: item.guard_id)
            ],
            "initial_states": sorted(set(self.initial_states)),
            "input_modality_requirements": [
                item.to_dict()
                for item in sorted(
                    self.input_modality_requirements,
                    key=lambda item: item.requirement_id,
                )
            ],
            "intent_ir_bindings": [
                item.to_dict()
                for item in sorted(
                    self.intent_ir_bindings, key=lambda item: item.binding_id
                )
            ],
            "invocation_bindings": [
                item.to_dict()
                for item in sorted(
                    self.invocation_bindings, key=lambda item: item.binding_id
                )
            ],
            "journeys": [
                item.to_dict()
                for item in sorted(self.journeys, key=lambda item: item.journey_id)
            ],
            "layout_constraints": [
                item.to_dict()
                for item in sorted(
                    self.layout_constraints, key=lambda item: item.constraint_id
                )
            ],
            "layout_regions": [
                item.to_dict()
                for item in sorted(
                    self.layout_regions, key=lambda item: item.region_id
                )
            ],
            "locale_defaults": self.locale_defaults.to_dict(),
            "localization": [
                item.to_dict()
                for item in sorted(
                    self.localization, key=lambda item: item.localization_id
                )
            ],
            "mcp_idl_bindings": [
                item.to_dict()
                for item in sorted(
                    self.mcp_idl_bindings, key=lambda item: item.binding_id
                )
            ],
            "modality_alternatives": [
                item.to_dict()
                for item in sorted(
                    self.modality_alternatives, key=lambda item: item.alternative_id
                )
            ],
            "output_modality_requirements": [
                item.to_dict()
                for item in sorted(
                    self.output_modality_requirements,
                    key=lambda item: item.requirement_id,
                )
            ],
            "producer": self.producer.to_dict() if self.producer else None,
            "program_bindings": [
                item.to_dict()
                for item in sorted(
                    self.program_bindings, key=lambda item: item.binding_id
                )
            ],
            "proof_obligation_refs": [
                item.to_dict()
                for item in sorted(
                    self.proof_obligation_refs, key=lambda item: item.obligation_id
                )
            ],
            "review": self.review.to_dict(),
            "schema_version": self.schema_version,
            "sources": [
                item.to_dict()
                for item in sorted(self.sources, key=lambda item: item.ref_id)
            ],
            "state_variables": [
                item.to_dict()
                for item in sorted(
                    self.state_variables, key=lambda item: item.variable_id
                )
            ],
            "states": [
                item.to_dict()
                for item in sorted(self.states, key=lambda item: item.state_id)
            ],
            "success_failure_recovery": [
                item.to_dict()
                for item in sorted(
                    self.success_failure_recovery, key=lambda item: item.path_id
                )
            ],
            "tags": sorted(set(self.tags)),
            "terminal_outcomes": [
                item.to_dict()
                for item in sorted(
                    self.terminal_outcomes, key=lambda item: item.outcome_id
                )
            ],
            "title": self.title,
            "transitions": [
                item.to_dict()
                for item in sorted(
                    self.transitions, key=lambda item: item.transition_id
                )
            ],
            "trust_bindings": [
                item.to_dict()
                for item in sorted(
                    self.trust_bindings, key=lambda item: item.trust_id
                )
            ],
            "ux_tasks": [
                item.to_dict()
                for item in sorted(self.ux_tasks, key=lambda item: item.task_id)
            ],
        }
        return payload


def validate_ui_ir(
    document: UIIRDocument | Mapping[str, Any],
) -> UIIRDocument:
    """Validate and return a :class:`UIIRDocument`.

    Mappings must pass through the versioned decoder (UIR-011). Accepting raw
    mappings here would let untrusted JSON bypass exact field and type checks.
    """

    if not isinstance(document, UIIRDocument):
        raise UIIRValidationError(
            "UI/UX IR mappings require an explicit versioned decoder"
        )
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
        raise UIIRValidationError("UIIRDocument.entry_components must not be empty")
    if not document.terminal_outcomes:
        raise UIIRValidationError("UIIRDocument.terminal_outcomes must not be empty")

    _validate_document_collections(document)
    _validate_record_types(document)

    document.locale_defaults.validate()
    document.review.validate()
    if document.producer is not None:
        document.producer.validate()
    if document.configuration is not None:
        document.configuration.validate()

    for source in document.sources:
        source.validate()
    for item in document.trust_bindings:
        item.validate()
    for item in document.components:
        item.validate()
    for item in document.composition_edges:
        item.validate()
    for item in document.layout_regions:
        item.validate()
    for item in document.layout_constraints:
        item.validate()
    for item in document.design_token_refs:
        item.validate()
    for item in document.state_variables:
        item.validate()
    for item in document.states:
        item.validate()
    for item in document.events:
        item.validate()
    for item in document.transitions:
        item.validate()
    for item in document.guards:
        item.validate()
    for item in document.effects:
        item.validate()
    for item in document.ux_tasks:
        item.validate()
    for item in document.journeys:
        item.validate()
    for item in document.success_failure_recovery:
        item.validate()
    for item in document.feedback_contracts:
        item.validate()
    for item in document.accessibility:
        item.validate()
    for item in document.localization:
        item.validate()
    for item in document.input_modality_requirements:
        item.validate()
    for item in document.output_modality_requirements:
        item.validate()
    for item in document.modality_alternatives:
        item.validate()
    for item in document.device_capability_requirements:
        item.validate()
    for item in document.adaptive_variants:
        item.validate()
    for item in document.data_bindings:
        item.validate()
    for item in document.content_references:
        item.validate()
    for item in document.program_bindings:
        item.validate()
    for item in document.intent_ir_bindings:
        item.validate()
    for item in document.invocation_bindings:
        item.validate()
    for item in document.mcp_idl_bindings:
        item.validate()
    for item in document.formal_constraint_refs:
        item.validate()
    for item in document.proof_obligation_refs:
        item.validate()
    for item in document.terminal_outcomes:
        item.validate()
    for item in document.extensions:
        item.validate()

    _validate_unique_ids(document)
    _validate_cross_references(document)
    _reject_executable_payload(document.to_dict(), "UIIRDocument")
    return document


# Alias retained for callers that prefer the longer family name.
validate_ui_ux_ir = validate_ui_ir


def reject_unknown_document_fields(payload: Mapping[str, Any]) -> None:
    """Fail closed when a wire mapping contains undeclared top-level fields."""

    if not isinstance(payload, Mapping):
        raise UIIRValidationError("document payload must be a mapping")
    unknown = sorted(set(payload) - UIIR_DOCUMENT_FIELDS)
    if unknown:
        raise UIIRValidationError(
            f"unknown UIIRDocument field(s): {', '.join(unknown)}"
        )
    missing = sorted(
        name for name in UIIR_REQUIRED_PATHS if name not in payload
    )
    if missing:
        raise UIIRValidationError(
            f"missing required UIIRDocument path(s): {', '.join(missing)}"
        )


def load_ui_ux_ir_json_schema() -> dict[str, Any]:
    """Load the closed JSON Schema document shipped beside this module."""

    import json

    if not UI_UX_IR_SCHEMA_JSON_PATH.is_file():
        raise UIIRValidationError(
            f"JSON Schema not found at {UI_UX_IR_SCHEMA_JSON_PATH}"
        )
    with UI_UX_IR_SCHEMA_JSON_PATH.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise UIIRValidationError("JSON Schema root must be an object")
    return schema


def _validate_record_types(document: UIIRDocument) -> None:
    checks: tuple[tuple[str, tuple[Any, ...], type[Any]], ...] = (
        ("UIIRDocument.sources", document.sources, UISourceRef),
        ("UIIRDocument.trust_bindings", document.trust_bindings, UITrustBinding),
        ("UIIRDocument.components", document.components, UIComponent),
        (
            "UIIRDocument.composition_edges",
            document.composition_edges,
            UICompositionEdge,
        ),
        ("UIIRDocument.layout_regions", document.layout_regions, UILayoutRegion),
        (
            "UIIRDocument.layout_constraints",
            document.layout_constraints,
            UILayoutConstraint,
        ),
        (
            "UIIRDocument.design_token_refs",
            document.design_token_refs,
            UIDesignTokenRef,
        ),
        ("UIIRDocument.state_variables", document.state_variables, UIStateVariable),
        ("UIIRDocument.states", document.states, UIState),
        ("UIIRDocument.events", document.events, UIEvent),
        ("UIIRDocument.transitions", document.transitions, UITransition),
        ("UIIRDocument.guards", document.guards, UIGuard),
        ("UIIRDocument.effects", document.effects, UIEffect),
        ("UIIRDocument.ux_tasks", document.ux_tasks, UIUXTask),
        ("UIIRDocument.journeys", document.journeys, UIJourney),
        (
            "UIIRDocument.success_failure_recovery",
            document.success_failure_recovery,
            UIRecoveryPath,
        ),
        (
            "UIIRDocument.feedback_contracts",
            document.feedback_contracts,
            UIFeedbackContract,
        ),
        (
            "UIIRDocument.accessibility",
            document.accessibility,
            UIAccessibilityBinding,
        ),
        ("UIIRDocument.localization", document.localization, UILocalizationBinding),
        (
            "UIIRDocument.input_modality_requirements",
            document.input_modality_requirements,
            UIModalityRequirement,
        ),
        (
            "UIIRDocument.output_modality_requirements",
            document.output_modality_requirements,
            UIModalityRequirement,
        ),
        (
            "UIIRDocument.modality_alternatives",
            document.modality_alternatives,
            UIModalityAlternative,
        ),
        (
            "UIIRDocument.device_capability_requirements",
            document.device_capability_requirements,
            UIDeviceCapabilityRequirement,
        ),
        (
            "UIIRDocument.adaptive_variants",
            document.adaptive_variants,
            UIAdaptiveVariant,
        ),
        ("UIIRDocument.data_bindings", document.data_bindings, UIDataBinding),
        (
            "UIIRDocument.content_references",
            document.content_references,
            UIContentReference,
        ),
        (
            "UIIRDocument.program_bindings",
            document.program_bindings,
            UIProgramBinding,
        ),
        (
            "UIIRDocument.intent_ir_bindings",
            document.intent_ir_bindings,
            UIIntentIRBinding,
        ),
        (
            "UIIRDocument.invocation_bindings",
            document.invocation_bindings,
            UIInvocationBinding,
        ),
        ("UIIRDocument.mcp_idl_bindings", document.mcp_idl_bindings, UIMCPIDLBinding),
        (
            "UIIRDocument.formal_constraint_refs",
            document.formal_constraint_refs,
            UIFormalConstraintRef,
        ),
        (
            "UIIRDocument.proof_obligation_refs",
            document.proof_obligation_refs,
            UIProofObligationRef,
        ),
        (
            "UIIRDocument.terminal_outcomes",
            document.terminal_outcomes,
            UITerminalOutcome,
        ),
        ("UIIRDocument.extensions", document.extensions, UINamespacedExtension),
    )
    for name, values, item_type in checks:
        _validate_record_collection(name, values, item_type)
    if not isinstance(document.locale_defaults, UILocaleDefaults):
        raise UIIRValidationError(
            "UIIRDocument.locale_defaults must be a UILocaleDefaults"
        )
    if not isinstance(document.review, UIReviewBinding):
        raise UIIRValidationError("UIIRDocument.review must be a UIReviewBinding")
    if document.producer is not None and not isinstance(document.producer, UIProducer):
        raise UIIRValidationError("UIIRDocument.producer must be a UIProducer or None")
    if document.configuration is not None and not isinstance(
        document.configuration, UIConfiguration
    ):
        raise UIIRValidationError(
            "UIIRDocument.configuration must be a UIConfiguration or None"
        )


def _validate_unique_ids(document: UIIRDocument) -> None:
    _require_unique((item.ref_id for item in document.sources), "source ref")
    _require_unique((item.trust_id for item in document.trust_bindings), "trust")
    _require_unique((item.component_id for item in document.components), "component")
    _require_unique((item.edge_id for item in document.composition_edges), "composition edge")
    _require_unique((item.region_id for item in document.layout_regions), "layout region")
    _require_unique(
        (item.constraint_id for item in document.layout_constraints),
        "layout constraint",
    )
    _require_unique((item.token_id for item in document.design_token_refs), "design token")
    _require_unique(
        (item.variable_id for item in document.state_variables), "state variable"
    )
    _require_unique((item.state_id for item in document.states), "state")
    _require_unique((item.event_id for item in document.events), "event")
    _require_unique((item.transition_id for item in document.transitions), "transition")
    _require_unique((item.guard_id for item in document.guards), "guard")
    _require_unique((item.effect_id for item in document.effects), "effect")
    _require_unique((item.task_id for item in document.ux_tasks), "ux task")
    _require_unique((item.journey_id for item in document.journeys), "journey")
    _require_unique(
        (item.path_id for item in document.success_failure_recovery), "recovery path"
    )
    _require_unique(
        (item.feedback_id for item in document.feedback_contracts), "feedback"
    )
    _require_unique(
        (item.accessibility_id for item in document.accessibility), "accessibility"
    )
    _require_unique(
        (item.localization_id for item in document.localization), "localization"
    )
    _require_unique(
        (item.requirement_id for item in document.input_modality_requirements),
        "input modality requirement",
    )
    _require_unique(
        (item.requirement_id for item in document.output_modality_requirements),
        "output modality requirement",
    )
    _require_unique(
        (item.alternative_id for item in document.modality_alternatives),
        "modality alternative",
    )
    _require_unique(
        (item.requirement_id for item in document.device_capability_requirements),
        "device capability requirement",
    )
    _require_unique(
        (item.variant_id for item in document.adaptive_variants), "adaptive variant"
    )
    _require_unique((item.binding_id for item in document.data_bindings), "data binding")
    _require_unique(
        (item.content_id for item in document.content_references), "content reference"
    )
    _require_unique(
        (item.binding_id for item in document.program_bindings), "program binding"
    )
    _require_unique(
        (item.binding_id for item in document.intent_ir_bindings), "intent ir binding"
    )
    _require_unique(
        (item.binding_id for item in document.invocation_bindings),
        "invocation binding",
    )
    _require_unique(
        (item.binding_id for item in document.mcp_idl_bindings), "mcp idl binding"
    )
    _require_unique(
        (item.constraint_id for item in document.formal_constraint_refs),
        "formal constraint",
    )
    _require_unique(
        (item.obligation_id for item in document.proof_obligation_refs),
        "proof obligation",
    )
    _require_unique(
        (item.outcome_id for item in document.terminal_outcomes), "terminal outcome"
    )
    _require_unique(
        (item.extension_id for item in document.extensions), "extension"
    )
    _require_unique(document.entry_components, "entry_components member")
    _require_unique(document.initial_states, "initial_states member")
    _require_unique(document.tags, "tags member")


def _validate_cross_references(document: UIIRDocument) -> None:
    source_ids = {item.ref_id for item in document.sources}
    component_ids = {item.component_id for item in document.components}
    state_ids = {item.state_id for item in document.states}
    event_ids = {item.event_id for item in document.events}
    guard_ids = {item.guard_id for item in document.guards}
    effect_ids = {item.effect_id for item in document.effects}
    region_ids = {item.region_id for item in document.layout_regions}
    feedback_ids = {item.feedback_id for item in document.feedback_contracts}
    data_binding_ids = {item.binding_id for item in document.data_bindings}
    program_binding_ids = {item.binding_id for item in document.program_bindings}
    task_ids = {item.task_id for item in document.ux_tasks}
    localization_ids = {
        item.localization_id for item in document.localization
    }
    modality_req_ids = {
        item.requirement_id for item in document.input_modality_requirements
    } | {item.requirement_id for item in document.output_modality_requirements}
    formal_ids = {
        item.constraint_id for item in document.formal_constraint_refs
    }
    outcome_ids = {item.outcome_id for item in document.terminal_outcomes}

    def sources_of(label: str, values: Iterable[str]) -> None:
        _require_known_refs(values, source_ids, label)

    for component in document.components:
        sources_of(
            f"UIComponent {component.component_id!r}.source_ref_ids",
            component.source_ref_ids,
        )
        if component.parent_id:
            _require_known_refs(
                (component.parent_id,),
                component_ids,
                f"UIComponent {component.component_id!r}.parent_id",
            )
        _require_known_refs(
            component.child_ids,
            component_ids,
            f"UIComponent {component.component_id!r}.child_ids",
        )
        _require_known_refs(
            component.feedback_ids,
            feedback_ids,
            f"UIComponent {component.component_id!r}.feedback_ids",
        )
        _require_known_refs(
            component.data_binding_ids,
            data_binding_ids,
            f"UIComponent {component.component_id!r}.data_binding_ids",
        )
        _require_known_refs(
            component.program_binding_ids,
            program_binding_ids,
            f"UIComponent {component.component_id!r}.program_binding_ids",
        )

    for edge in document.composition_edges:
        sources_of(
            f"UICompositionEdge {edge.edge_id!r}.source_ref_ids", edge.source_ref_ids
        )
        _require_known_refs(
            (edge.source_component_id, edge.target_component_id),
            component_ids,
            f"UICompositionEdge {edge.edge_id!r}",
        )

    for region in document.layout_regions:
        sources_of(
            f"UILayoutRegion {region.region_id!r}.source_ref_ids", region.source_ref_ids
        )
        _require_known_refs(
            region.component_ids,
            component_ids,
            f"UILayoutRegion {region.region_id!r}.component_ids",
        )

    for constraint in document.layout_constraints:
        sources_of(
            f"UILayoutConstraint {constraint.constraint_id!r}.source_ref_ids",
            constraint.source_ref_ids,
        )
        _require_known_refs(
            constraint.region_ids,
            region_ids,
            f"UILayoutConstraint {constraint.constraint_id!r}.region_ids",
        )
        _require_known_refs(
            constraint.component_ids,
            component_ids,
            f"UILayoutConstraint {constraint.constraint_id!r}.component_ids",
        )

    for state in document.states:
        sources_of(f"UIState {state.state_id!r}.source_ref_ids", state.source_ref_ids)
        if state.region_id:
            _require_known_refs(
                (state.region_id,),
                region_ids,
                f"UIState {state.state_id!r}.region_id",
            )

    for transition in document.transitions:
        sources_of(
            f"UITransition {transition.transition_id!r}.source_ref_ids",
            transition.source_ref_ids,
        )
        _require_known_refs(
            (transition.source_state_id, transition.target_state_id),
            state_ids,
            f"UITransition {transition.transition_id!r}",
        )
        if transition.event_id:
            _require_known_refs(
                (transition.event_id,),
                event_ids,
                f"UITransition {transition.transition_id!r}.event_id",
            )
        if transition.guard_id:
            _require_known_refs(
                (transition.guard_id,),
                guard_ids,
                f"UITransition {transition.transition_id!r}.guard_id",
            )
        _require_known_refs(
            transition.effect_ids,
            effect_ids,
            f"UITransition {transition.transition_id!r}.effect_ids",
        )

    for guard in document.guards:
        sources_of(f"UIGuard {guard.guard_id!r}.source_ref_ids", guard.source_ref_ids)
        if guard.formal_constraint_id:
            _require_known_refs(
                (guard.formal_constraint_id,),
                formal_ids,
                f"UIGuard {guard.guard_id!r}.formal_constraint_id",
            )

    for effect in document.effects:
        sources_of(
            f"UIEffect {effect.effect_id!r}.source_ref_ids", effect.source_ref_ids
        )
        if effect.program_binding_id:
            _require_known_refs(
                (effect.program_binding_id,),
                program_binding_ids,
                f"UIEffect {effect.effect_id!r}.program_binding_id",
            )

    for task in document.ux_tasks:
        sources_of(f"UIUXTask {task.task_id!r}.source_ref_ids", task.source_ref_ids)
        _require_known_refs(
            task.step_component_ids,
            component_ids,
            f"UIUXTask {task.task_id!r}.step_component_ids",
        )

    for journey in document.journeys:
        sources_of(
            f"UIJourney {journey.journey_id!r}.source_ref_ids", journey.source_ref_ids
        )
        _require_known_refs(
            journey.task_ids,
            task_ids,
            f"UIJourney {journey.journey_id!r}.task_ids",
        )

    for path in document.success_failure_recovery:
        sources_of(
            f"UIRecoveryPath {path.path_id!r}.source_ref_ids", path.source_ref_ids
        )
        if path.target_outcome_id:
            _require_known_refs(
                (path.target_outcome_id,),
                outcome_ids,
                f"UIRecoveryPath {path.path_id!r}.target_outcome_id",
            )
        if path.recovery_component_id:
            _require_known_refs(
                (path.recovery_component_id,),
                component_ids,
                f"UIRecoveryPath {path.path_id!r}.recovery_component_id",
            )

    for feedback in document.feedback_contracts:
        sources_of(
            f"UIFeedbackContract {feedback.feedback_id!r}.source_ref_ids",
            feedback.source_ref_ids,
        )
        if feedback.component_id:
            _require_known_refs(
                (feedback.component_id,),
                component_ids,
                f"UIFeedbackContract {feedback.feedback_id!r}.component_id",
            )

    for a11y in document.accessibility:
        sources_of(
            f"UIAccessibilityBinding {a11y.accessibility_id!r}.source_ref_ids",
            a11y.source_ref_ids,
        )
        _require_known_refs(
            (a11y.component_id,),
            component_ids,
            f"UIAccessibilityBinding {a11y.accessibility_id!r}.component_id",
        )

    for content in document.content_references:
        sources_of(
            f"UIContentReference {content.content_id!r}.source_ref_ids",
            content.source_ref_ids,
        )
        if content.localization_id:
            _require_known_refs(
                (content.localization_id,),
                localization_ids,
                f"UIContentReference {content.content_id!r}.localization_id",
            )

    for alt in document.modality_alternatives:
        sources_of(
            f"UIModalityAlternative {alt.alternative_id!r}.source_ref_ids",
            alt.source_ref_ids,
        )
        _require_known_refs(
            (alt.primary_requirement_id, alt.alternative_requirement_id),
            modality_req_ids,
            f"UIModalityAlternative {alt.alternative_id!r}",
        )

    for obligation in document.proof_obligation_refs:
        sources_of(
            f"UIProofObligationRef {obligation.obligation_id!r}.source_ref_ids",
            obligation.source_ref_ids,
        )
        _require_known_refs(
            (obligation.constraint_id,),
            formal_ids,
            f"UIProofObligationRef {obligation.obligation_id!r}.constraint_id",
        )

    for collection_name, records in (
        ("trust_bindings", document.trust_bindings),
        ("design_token_refs", document.design_token_refs),
        ("state_variables", document.state_variables),
        ("events", document.events),
        ("localization", document.localization),
        ("input_modality_requirements", document.input_modality_requirements),
        ("output_modality_requirements", document.output_modality_requirements),
        ("device_capability_requirements", document.device_capability_requirements),
        ("adaptive_variants", document.adaptive_variants),
        ("data_bindings", document.data_bindings),
        ("program_bindings", document.program_bindings),
        ("intent_ir_bindings", document.intent_ir_bindings),
        ("invocation_bindings", document.invocation_bindings),
        ("mcp_idl_bindings", document.mcp_idl_bindings),
        ("formal_constraint_refs", document.formal_constraint_refs),
        ("terminal_outcomes", document.terminal_outcomes),
        ("extensions", document.extensions),
    ):
        for record in records:
            ref_ids = getattr(record, "source_ref_ids", ())
            record_id = (
                getattr(record, "ref_id", None)
                or getattr(record, "trust_id", None)
                or getattr(record, "token_id", None)
                or getattr(record, "variable_id", None)
                or getattr(record, "event_id", None)
                or getattr(record, "localization_id", None)
                or getattr(record, "requirement_id", None)
                or getattr(record, "variant_id", None)
                or getattr(record, "binding_id", None)
                or getattr(record, "constraint_id", None)
                or getattr(record, "outcome_id", None)
                or getattr(record, "extension_id", None)
                or "?"
            )
            sources_of(
                f"UIIRDocument.{collection_name} {record_id!r}.source_ref_ids",
                ref_ids,
            )

    _require_known_refs(
        document.entry_components,
        component_ids,
        "UIIRDocument.entry_components",
    )
    if document.initial_states:
        if not state_ids:
            raise UIIRValidationError(
                "UIIRDocument.initial_states requires states to be declared"
            )
        _require_known_refs(
            document.initial_states,
            state_ids,
            "UIIRDocument.initial_states",
        )
    if document.states and not document.initial_states:
        raise UIIRValidationError(
            "UIIRDocument.initial_states must not be empty when states are declared"
        )


def _validate_document_collections(document: UIIRDocument) -> None:
    """Enforce immutable tuple collections and set-like uniqueness."""

    tuple_fields = (
        "sources",
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
        "tags",
        "extensions",
    )
    for name in tuple_fields:
        _require_tuple(f"UIIRDocument.{name}", getattr(document, name))

    for name in ("entry_components", "initial_states", "tags"):
        values = getattr(document, name)
        _validate_string_items(f"UIIRDocument.{name}", values)
        if name != "tags":
            _validate_identifier_items(f"UIIRDocument.{name}", values)
        _require_unique(values, f"UIIRDocument.{name} member")


def _validate_record_collection(
    name: str, value: Any, item_type: type[Any]
) -> None:
    _require_tuple(name, value)
    for index, item in enumerate(value):
        if not isinstance(item, item_type):
            raise UIIRValidationError(
                f"{name}[{index}] must be a {item_type.__name__}"
            )


def _validate_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise UIIRValidationError(f"{name} is not a stable identifier")


def _validate_identifier_items(name: str, values: Iterable[Any]) -> None:
    for index, value in enumerate(values):
        _validate_identifier(f"{name}[{index}]", value)


def _validate_string(name: str, value: Any) -> None:
    if not isinstance(value, str):
        raise UIIRValidationError(f"{name} must be a string")


def _validate_non_empty_string(name: str, value: Any) -> None:
    _validate_string(name, value)
    if not value.strip():
        raise UIIRValidationError(f"{name} must not be empty")


def _validate_string_items(name: str, values: Iterable[Any]) -> None:
    for index, value in enumerate(values):
        _validate_non_empty_string(f"{name}[{index}]", value)


def _require_tuple(name: str, value: Any) -> None:
    if not isinstance(value, tuple):
        semantics = UI_UX_IR_COLLECTION_SEMANTICS.get(name, "declared")
        raise UIIRValidationError(
            f"{name} must be an immutable tuple with {semantics} semantics"
        )


def _validate_sha256(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise UIIRValidationError(
            f"{name} must be a lowercase 64-character SHA-256"
        )


def _validate_enum(name: str, value: Any, enum_type: type[Enum]) -> None:
    if not isinstance(value, enum_type):
        raise UIIRValidationError(f"{name} must be a {enum_type.__name__} value")


def _require_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise UIIRValidationError(f"Duplicate {label} id: {value}")
        seen.add(value)


def _require_known_refs(
    values: Iterable[str], known: set[str], label: str
) -> None:
    missing = sorted({value for value in values if value not in known})
    if missing:
        raise UIIRValidationError(
            f"{label} references unknown ids: {', '.join(missing)}"
        )


def _is_forbidden_executable_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _FORBIDDEN_EXECUTABLE_KEYS:
        return True
    return any(lowered.startswith(prefix) for prefix in _FORBIDDEN_EXECUTABLE_KEY_PREFIXES)


def _reject_executable_payload(value: Any, label: str, *, _path: str = "") -> None:
    """Reject callables and forbidden executable keys anywhere in a payload."""

    if callable(value) and not isinstance(value, type):
        raise UIIRValidationError(
            f"{label}{_path} contains an executable callback"
        )
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise UIIRValidationError(
                    f"{label}{_path} map keys must be strings"
                )
            if _is_forbidden_executable_key(key):
                raise UIIRValidationError(
                    f"{label}{_path}/{key} is an executable callback field"
                )
            _reject_executable_payload(item, label, _path=f"{_path}/{key}")
        return
    if isinstance(value, (str, bytes, bytearray)) or value is None:
        return
    if isinstance(value, Sequence):
        for index, item in enumerate(value):
            _reject_executable_payload(item, label, _path=f"{_path}[{index}]")


__all__ = [
    "AdaptationPolicy",
    "AuthorityKind",
    "CollectionSemantics",
    "CompositionEdgeKind",
    "EventKind",
    "LEGACY_UI_UX_IR_SCHEMA_VERSION",
    "LayoutRegionKind",
    "ProgramBindingTargetKind",
    "ReviewStatus",
    "SourceSpan",
    "TerminalOutcomeKind",
    "UI_UX_IR_COLLECTION_SCHEMA",
    "UI_UX_IR_COLLECTION_SEMANTICS",
    "UI_UX_IR_INTERFACE",
    "UI_UX_IR_SCHEMA_JSON_PATH",
    "UI_UX_IR_SCHEMA_VERSION",
    "UIAccessibilityBinding",
    "UIAdaptiveVariant",
    "UIComponent",
    "UICompositionEdge",
    "UIConfiguration",
    "UIContentReference",
    "UIDataBinding",
    "UIDesignTokenRef",
    "UIDeviceCapabilityRequirement",
    "UIEffect",
    "UIEvent",
    "UIFeedbackContract",
    "UIFormalConstraintRef",
    "UIGuard",
    "UIIRDocument",
    "UIIRValidationError",
    "UIIR_DOCUMENT_FIELDS",
    "UIIR_REQUIRED_PATHS",
    "UIIntentIRBinding",
    "UIInvocationBinding",
    "UIJourney",
    "UILayoutConstraint",
    "UILayoutRegion",
    "UILocaleDefaults",
    "UILocalizationBinding",
    "UIMCPIDLBinding",
    "UIModalityAlternative",
    "UIModalityRequirement",
    "UINamespacedExtension",
    "UIProducer",
    "UIProgramBinding",
    "UIProofObligationRef",
    "UIRecoveryPath",
    "UIReviewBinding",
    "UISourceRef",
    "UIState",
    "UIStateVariable",
    "UITerminalOutcome",
    "UITransition",
    "UITrustBinding",
    "UIUXTask",
    "load_ui_ux_ir_json_schema",
    "reject_unknown_document_fields",
    "validate_ui_ir",
    "validate_ui_ux_ir",
]
