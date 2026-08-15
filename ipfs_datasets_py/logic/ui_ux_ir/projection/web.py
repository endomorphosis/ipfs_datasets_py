"""Web/desktop projection adapter and renderer (UIIRWebRenderer@1).

Projects a shared :class:`UIProjectionArtifact` (or a document/problem solved
under the reference desktop profile) into deterministic accessible web/desktop
models. Also accepts :class:`DomAriaAdapterResult` fragments so DOM/ARIA import
and web export share the same role/name/value/state/relationship/action/
validation/live-feedback/focus-order contract.

Web is a **presentation target**, not a separate policy owner. Capability
negotiation, budget enforcement, and loss receipts remain owned by the
projection core (``capabilities`` / ``solver`` / ``loss``). This module only
maps already-solved projection nodes (and sanitized DOM/ARIA fragments) into
web surface descriptors with explicit:

- ARIA roles, names, values, and states
- relationship edges (labelledby, describedby, controls, owns, flowto, …)
- actions (activate, submit, toggle, select, edit, dismiss, confirm)
- form validation messages
- live region feedback
- keyboard / focus order independent of visual order
- denial, error, and confirmation surfaces that are visible and accessible
- CSS / framework details retained only as source metadata or loss receipts

Side-effect free: never executes markup or scripts; never opens network or
browser APIs. HTML export is a sanitized declarative model, not a DOM host.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ..schema import UIIRDocument, UIIRValidationError
from ..source_adapters.dom_aria import (
    DOMARIA_UIIR_ADAPTER,
    DomAriaAdapterResult,
    DomAriaDocument,
    adapt_dom_aria_to_uiir,
)
from .capabilities import ProfileFamily, UIDeviceProfile, desktop_profile
from .loss import MandatorySemanticKind
from .solver import (
    PresentationDisposition,
    ProjectedNode,
    ProjectionItem,
    ProjectionPolicy,
    ProjectionProblem,
    ProjectionStatus,
    UIProjectionArtifact,
    project_ui_ir,
)

UIIR_WEB_RENDERER_INTERFACE: Final = "UIIRWebRenderer@1"
UIIR_WEB_PROJECTION_INTERFACE: Final = "UIIRWebProjection@1"
UIIR_WEB_PROJECTION_SCHEMA_VERSION: Final = "ui-web-projection/v1"
UIIR_WEB_RENDER_MODEL_VERSION: Final = "ui-web-render-model/v1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

_EXECUTABLE_TEXT_MARKERS: Final = (
    "<script",
    "</script",
    "javascript:",
    "vbscript:",
    "onerror=",
    "onload=",
    "onclick=",
    "eval(",
    "Function(",
    "document.write",
    "innerHTML",
    "__proto__",
)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_CONFIRM_KINDS: Final = frozenset(
    {
        MandatorySemanticKind.CONFIRMATION.value,
        MandatorySemanticKind.CONSENT.value,
        MandatorySemanticKind.CONSEQUENCE.value,
    }
)
_ERROR_KINDS: Final = frozenset({MandatorySemanticKind.ERROR.value})
_DENIAL_HINTS: Final = frozenset(
    {"deny", "denied", "denial", "forbidden", "unauthorized", "blocked", "rejected"}
)
_PENDING_HINTS: Final = frozenset(
    {"pending", "loading", "in_progress", "busy", "progress"}
)

# Semantic kind / label → default ARIA role for web presentation.
_KIND_TO_ROLE: Final[Mapping[str, str]] = MappingProxyType(
    {
        MandatorySemanticKind.ACTION.value: "button",
        MandatorySemanticKind.CONFIRMATION.value: "alertdialog",
        MandatorySemanticKind.CONSENT.value: "dialog",
        MandatorySemanticKind.CONSEQUENCE.value: "status",
        MandatorySemanticKind.ERROR.value: "alert",
        MandatorySemanticKind.FEEDBACK.value: "status",
        MandatorySemanticKind.ACCESSIBILITY.value: "region",
        MandatorySemanticKind.PRIVACY.value: "status",
        "denial": "alert",
        "form": "form",
        "textbox": "textbox",
        "checkbox": "checkbox",
        "radio": "radio",
        "switch": "switch",
        "list": "list",
        "listitem": "listitem",
        "navigation": "navigation",
        "link": "link",
        "heading": "heading",
        "dialog": "dialog",
        "main": "main",
        "banner": "banner",
        "contentinfo": "contentinfo",
    }
)


class WebSurfaceKind(str, Enum):
    """Closed web/desktop surface models."""

    DOCUMENT = "document"
    REGION = "region"
    FORM = "form"
    CONTROL = "control"
    ACTION = "action"
    STATUS = "status"
    ALERT = "alert"
    CONFIRMATION = "confirmation"
    DENIAL = "denial"
    LIVE_REGION = "live_region"
    LANDMARK = "landmark"
    FALLBACK = "fallback"


class WebInteractionState(str, Enum):
    """Cross-cutting interaction presentation states for web surfaces."""

    IDLE = "idle"
    PENDING = "pending"
    ERROR = "error"
    CONFIRMATION = "confirmation"
    DENIAL = "denial"
    SUCCESS = "success"
    DISABLED = "disabled"
    INVALID = "invalid"


class WebFocusRestoreStrategy(str, Enum):
    """How focus returns after modal/confirmation/denial."""

    PREVIOUS_TARGET = "previous_target"
    ENTRY_COMPONENT = "entry_component"
    FIRST_ACTIONABLE = "first_actionable"
    ANNOUNCE_ONLY = "announce_only"


class WebKeyboardNavMode(str, Enum):
    """Keyboard navigation contract for the web surface tree."""

    TAB_ORDER = "tab_order"
    ROVING_TABINDEX = "roving_tabindex"
    DIALOG_TRAP = "dialog_trap"


def _validate_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise UIIRValidationError(f"{name} is not a stable identifier: {value!r}")


def _require_tuple(name: str, value: Any) -> None:
    if not isinstance(value, tuple):
        raise UIIRValidationError(f"{name} must be an immutable tuple")


def _sanitize_text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    text = _CONTROL_CHARS_RE.sub("", value)
    lower = text.lower()
    for marker in _EXECUTABLE_TEXT_MARKERS:
        if marker in lower:
            pattern = re.compile(re.escape(marker), re.IGNORECASE)
            text = pattern.sub("", text)
            lower = text.lower()
    text = re.sub(r"<\s*/?\s*script[^>]*>", "", text, flags=re.IGNORECASE)
    return text.strip()


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        result = value.to_dict()
        if isinstance(result, Mapping):
            return result
    return None


@dataclass(frozen=True, slots=True)
class WebSourceMetadata:
    """Retained non-semantic source details (CSS/framework/spans)."""

    metadata_id: str
    node_id: str
    tag_name: str = ""
    css_classes: tuple[str, ...] = ()
    css_inline_summary: str = ""
    framework_hints: Mapping[str, str] = field(default_factory=dict)
    attributes_retained: Mapping[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        _validate_identifier("WebSourceMetadata.metadata_id", self.metadata_id)
        _validate_identifier("WebSourceMetadata.node_id", self.node_id)
        _require_tuple("WebSourceMetadata.css_classes", self.css_classes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes_retained": dict(self.attributes_retained),
            "css_classes": list(self.css_classes),
            "css_inline_summary": self.css_inline_summary,
            "framework_hints": dict(self.framework_hints),
            "metadata_id": self.metadata_id,
            "node_id": self.node_id,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True, slots=True)
class WebFormValidation:
    """Form validation presentation for a control."""

    valid: bool | None = None
    message: str = ""
    required: bool = False
    invalid_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "invalid_state": self.invalid_state,
            "message": self.message,
            "required": self.required,
            "valid": self.valid,
        }


@dataclass(frozen=True, slots=True)
class WebLiveRegion:
    """Live feedback region configuration for assistive tech."""

    politeness: str = "off"  # off | polite | assertive
    atomic: bool = False
    relevant: str = "additions text"

    def to_dict(self) -> dict[str, Any]:
        return {
            "atomic": self.atomic,
            "politeness": self.politeness,
            "relevant": self.relevant,
        }


@dataclass(frozen=True, slots=True)
class WebRelationship:
    """One ARIA relationship edge retained for web presentation."""

    kind: str
    source_node_id: str
    target_node_id: str

    def validate(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise UIIRValidationError("WebRelationship.kind must be non-empty")
        _validate_identifier("WebRelationship.source_node_id", self.source_node_id)
        _validate_identifier("WebRelationship.target_node_id", self.target_node_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
        }


@dataclass(frozen=True, slots=True)
class WebNodeModel:
    """One accessible web/desktop node in the render model."""

    node_id: str
    kind: WebSurfaceKind
    role: str
    name: str
    semantic_kind: str
    disposition: str
    order: int
    focus_index: int | None = None
    value: str = ""
    description: str = ""
    states: Mapping[str, str] = field(default_factory=dict)
    actions: tuple[str, ...] = ()
    relationships: tuple[WebRelationship, ...] = ()
    validation: WebFormValidation = field(default_factory=WebFormValidation)
    live: WebLiveRegion = field(default_factory=WebLiveRegion)
    interaction_state: WebInteractionState = WebInteractionState.IDLE
    mandatory: bool = False
    visible: bool = True
    accessible: bool = True
    component_id: str = ""
    source_item_id: str = ""
    body: str = ""
    status_tone: str = "neutral"
    fallback_ref: str = ""
    source_metadata_id: str = ""
    children: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _validate_identifier("WebNodeModel.node_id", self.node_id)
        if not isinstance(self.kind, WebSurfaceKind):
            raise UIIRValidationError("WebNodeModel.kind must be a WebSurfaceKind")
        if not isinstance(self.role, str) or not self.role.strip():
            raise UIIRValidationError("WebNodeModel.role must be non-empty")
        if not isinstance(self.name, str) or not self.name.strip():
            raise UIIRValidationError("WebNodeModel.name must be non-empty")
        if not isinstance(self.interaction_state, WebInteractionState):
            raise UIIRValidationError(
                "WebNodeModel.interaction_state must be a WebInteractionState"
            )
        if not isinstance(self.visible, bool) or not isinstance(self.accessible, bool):
            raise UIIRValidationError(
                "WebNodeModel.visible and accessible must be booleans"
            )
        # Denial / error / confirmation must be visible and accessible.
        if self.kind in {
            WebSurfaceKind.DENIAL,
            WebSurfaceKind.ALERT,
            WebSurfaceKind.CONFIRMATION,
        }:
            if not self.visible or not self.accessible:
                raise UIIRValidationError(
                    f"WebNodeModel {self.node_id!r} of kind {self.kind.value} "
                    "must be visible and accessible"
                )
        _require_tuple("WebNodeModel.actions", self.actions)
        _require_tuple("WebNodeModel.relationships", self.relationships)
        _require_tuple("WebNodeModel.children", self.children)
        for rel in self.relationships:
            rel.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessible": self.accessible,
            "actions": list(self.actions),
            "body": self.body,
            "children": list(self.children),
            "component_id": self.component_id,
            "description": self.description,
            "disposition": self.disposition,
            "fallback_ref": self.fallback_ref,
            "focus_index": self.focus_index,
            "interaction_state": self.interaction_state.value,
            "kind": self.kind.value,
            "live": self.live.to_dict(),
            "mandatory": self.mandatory,
            "metadata": dict(self.metadata),
            "name": self.name,
            "node_id": self.node_id,
            "order": self.order,
            "relationships": [rel.to_dict() for rel in self.relationships],
            "role": self.role,
            "semantic_kind": self.semantic_kind,
            "source_item_id": self.source_item_id,
            "source_metadata_id": self.source_metadata_id,
            "states": dict(self.states),
            "status_tone": self.status_tone,
            "validation": self.validation.to_dict(),
            "value": self.value,
            "visible": self.visible,
        }


@dataclass(frozen=True, slots=True)
class WebFocusPlan:
    """Keyboard focus contract for the projected web tree."""

    order: tuple[str, ...]
    restore_strategy: WebFocusRestoreStrategy = WebFocusRestoreStrategy.PREVIOUS_TARGET
    restore_target_id: str = ""
    keyboard_mode: WebKeyboardNavMode = WebKeyboardNavMode.TAB_ORDER
    trap_while_modal: bool = False
    announce_on_restore: bool = True

    def validate(self) -> None:
        _require_tuple("WebFocusPlan.order", self.order)
        if not isinstance(self.restore_strategy, WebFocusRestoreStrategy):
            raise UIIRValidationError(
                "WebFocusPlan.restore_strategy must be a WebFocusRestoreStrategy"
            )
        if not isinstance(self.keyboard_mode, WebKeyboardNavMode):
            raise UIIRValidationError(
                "WebFocusPlan.keyboard_mode must be a WebKeyboardNavMode"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "announce_on_restore": self.announce_on_restore,
            "keyboard_mode": self.keyboard_mode.value,
            "order": list(self.order),
            "restore_strategy": self.restore_strategy.value,
            "restore_target_id": self.restore_target_id,
            "trap_while_modal": self.trap_while_modal,
        }


@dataclass(frozen=True, slots=True)
class WebLossReceipt:
    """Explicit loss or retained-metadata receipt for one web detail."""

    loss_id: str
    path: str
    reason: str
    category: str = "unsupported"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "detail": self.detail,
            "loss_id": self.loss_id,
            "path": self.path,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class WebProjectionArtifact:
    """Deterministic web/desktop projection + render model.

    Interface identity: ``UIIRWebProjection@1`` / ``UIIRWebRenderer@1``.
    """

    artifact_id: str
    nodes: tuple[WebNodeModel, ...]
    focus: WebFocusPlan
    source_metadata: tuple[WebSourceMetadata, ...] = ()
    losses: tuple[WebLossReceipt, ...] = ()
    projection_artifact_id: str = ""
    projection_status: str = ""
    profile_id: str = ""
    document_id: str = ""
    loss_report: Mapping[str, Any] = field(default_factory=dict)
    policy_owner: str = "UIProjectionSolver@1"
    notes: tuple[str, ...] = ()
    execution_performed: bool = False  # always False
    schema_version: str = UIIR_WEB_PROJECTION_SCHEMA_VERSION
    render_model_version: str = UIIR_WEB_RENDER_MODEL_VERSION
    interface: str = UIIR_WEB_PROJECTION_INTERFACE
    renderer: str = UIIR_WEB_RENDERER_INTERFACE

    def validate(self) -> "WebProjectionArtifact":
        _validate_identifier("WebProjectionArtifact.artifact_id", self.artifact_id)
        if self.schema_version != UIIR_WEB_PROJECTION_SCHEMA_VERSION:
            raise UIIRValidationError(
                f"Unsupported web projection schema_version: {self.schema_version!r}"
            )
        if self.interface != UIIR_WEB_PROJECTION_INTERFACE:
            raise UIIRValidationError(
                f"Unsupported web projection interface: {self.interface!r}"
            )
        if self.renderer != UIIR_WEB_RENDERER_INTERFACE:
            raise UIIRValidationError(
                f"Unsupported web renderer interface: {self.renderer!r}"
            )
        if self.policy_owner != "UIProjectionSolver@1":
            raise UIIRValidationError(
                "Web projection must not become a separate policy owner; "
                "policy_owner must remain UIProjectionSolver@1"
            )
        if self.execution_performed:
            raise UIIRValidationError(
                "Web renderer must never execute imported markup/scripts "
                "(execution_performed must be False)"
            )
        _require_tuple("WebProjectionArtifact.nodes", self.nodes)
        for node in self.nodes:
            if not isinstance(node, WebNodeModel):
                raise UIIRValidationError("nodes members must be WebNodeModel")
            node.validate()
        self.focus.validate()
        _require_tuple("WebProjectionArtifact.source_metadata", self.source_metadata)
        for meta in self.source_metadata:
            meta.validate()
        _require_tuple("WebProjectionArtifact.losses", self.losses)
        _require_tuple("WebProjectionArtifact.notes", self.notes)
        # Ensure denial/error/confirmation nodes exist as visible when status demands.
        critical = [
            n
            for n in self.nodes
            if n.kind
            in {
                WebSurfaceKind.DENIAL,
                WebSurfaceKind.ALERT,
                WebSurfaceKind.CONFIRMATION,
            }
        ]
        for node in critical:
            if not node.visible or not node.accessible:
                raise UIIRValidationError(
                    f"Critical surface {node.node_id!r} must remain visible/accessible"
                )
        return self

    def digest(self) -> str:
        text = json.dumps(
            self.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "document_id": self.document_id,
            "execution_performed": self.execution_performed,
            "focus": self.focus.to_dict(),
            "interface": self.interface,
            "loss_report": dict(self.loss_report),
            "losses": [item.to_dict() for item in self.losses],
            "nodes": [
                node.to_dict()
                for node in sorted(self.nodes, key=lambda n: (n.order, n.node_id))
            ],
            "notes": list(self.notes),
            "policy_owner": self.policy_owner,
            "profile_id": self.profile_id,
            "projection_artifact_id": self.projection_artifact_id,
            "projection_status": self.projection_status,
            "render_model_version": self.render_model_version,
            "renderer": self.renderer,
            "schema_version": self.schema_version,
            "source_metadata": [item.to_dict() for item in self.source_metadata],
        }

    def nodes_by_kind(self, kind: WebSurfaceKind | str) -> tuple[WebNodeModel, ...]:
        kind_value = kind.value if isinstance(kind, WebSurfaceKind) else str(kind)
        return tuple(n for n in self.nodes if n.kind.value == kind_value)

    def to_accessible_html_model(self) -> dict[str, Any]:
        """Declarative sanitized HTML-oriented model (never executed)."""

        elements: list[dict[str, Any]] = []
        for node in sorted(self.nodes, key=lambda n: (n.order, n.node_id)):
            attrs: dict[str, str] = {
                "id": node.node_id,
                "role": node.role.removeprefix("aria:"),
                "aria-label": node.name,
            }
            if node.description:
                attrs["aria-description"] = node.description
            if node.value:
                attrs["aria-valuetext"] = node.value
            for state_key, state_val in sorted(node.states.items()):
                attrs[f"aria-{state_key}"] = state_val
            if node.live.politeness in {"polite", "assertive"}:
                attrs["aria-live"] = node.live.politeness
                attrs["aria-atomic"] = "true" if node.live.atomic else "false"
            if node.validation.required:
                attrs["aria-required"] = "true"
            if node.validation.invalid_state == "true" or node.validation.valid is False:
                attrs["aria-invalid"] = "true"
            if node.focus_index is not None:
                attrs["tabindex"] = "0" if node.focus_index == 0 else "-1"
                if self.focus.keyboard_mode is WebKeyboardNavMode.TAB_ORDER:
                    attrs["tabindex"] = "0"
            if not node.visible:
                attrs["aria-hidden"] = "true"
            # Critical surfaces always expose visible text content.
            text = node.body or node.name
            if node.kind is WebSurfaceKind.DENIAL:
                text = f"Denied: {text}"
            elif node.kind is WebSurfaceKind.ALERT:
                text = f"Error: {text}"
            elif node.kind is WebSurfaceKind.CONFIRMATION:
                text = f"Confirm: {text}"
            elements.append(
                {
                    "tag": _html_tag_for(node),
                    "attributes": attrs,
                    "text": _sanitize_text(text),
                    "children": list(node.children),
                    "actions": list(node.actions),
                    "focus_index": node.focus_index,
                    "kind": node.kind.value,
                    "visible": node.visible,
                    "accessible": node.accessible,
                }
            )
        return {
            "execution_performed": False,
            "focus_order": list(self.focus.order),
            "elements": elements,
            "renderer": self.renderer,
            "schema_version": UIIR_WEB_RENDER_MODEL_VERSION,
        }


@dataclass(frozen=True, slots=True)
class WebProjectionOptions:
    """Presentation options for web/desktop (not policy)."""

    keyboard_mode: WebKeyboardNavMode = WebKeyboardNavMode.TAB_ORDER
    include_source_metadata: bool = True
    notes: tuple[str, ...] = ()

    def validate(self) -> "WebProjectionOptions":
        if not isinstance(self.keyboard_mode, WebKeyboardNavMode):
            raise UIIRValidationError(
                "keyboard_mode must be a WebKeyboardNavMode"
            )
        return self


def _html_tag_for(node: WebNodeModel) -> str:
    role = node.role.removeprefix("aria:")
    if node.kind is WebSurfaceKind.FORM or role == "form":
        return "form"
    if role == "button" or node.kind is WebSurfaceKind.ACTION:
        return "button"
    if role == "link":
        return "a"
    if role == "textbox":
        return "input"
    if role in {"checkbox", "radio", "switch"}:
        return "input"
    if role == "heading":
        return "h2"
    if node.kind in {
        WebSurfaceKind.ALERT,
        WebSurfaceKind.DENIAL,
        WebSurfaceKind.CONFIRMATION,
        WebSurfaceKind.STATUS,
        WebSurfaceKind.LIVE_REGION,
    }:
        return "div"
    if role in {"main", "navigation", "banner", "contentinfo", "complementary"}:
        return role if role != "contentinfo" else "footer"
    return "div"


def _role_for_node(node: ProjectedNode) -> str:
    kind = node.semantic_kind.lower()
    if kind in _KIND_TO_ROLE:
        return _KIND_TO_ROLE[kind]
    label = (node.label or node.component_id or node.item_id or "").lower()
    for token, role in (
        ("deny", "alert"),
        ("error", "alert"),
        ("confirm", "alertdialog"),
        ("form", "form"),
        ("input", "textbox"),
        ("button", "button"),
        ("nav", "navigation"),
        ("list", "list"),
        ("link", "link"),
    ):
        if token in label or token in kind:
            return role
    if kind == MandatorySemanticKind.ACTION.value:
        return "button"
    return "region"


def _surface_for_node(node: ProjectedNode) -> WebSurfaceKind:
    kind = node.semantic_kind.lower()
    label = (node.label or node.item_id or "").lower()
    disposition = node.disposition

    if disposition is PresentationDisposition.FALLBACK:
        return WebSurfaceKind.FALLBACK
    if disposition is PresentationDisposition.UNSATISFIABLE:
        return WebSurfaceKind.DENIAL
    if kind in _CONFIRM_KINDS:
        return WebSurfaceKind.CONFIRMATION
    if kind in _ERROR_KINDS:
        return WebSurfaceKind.ALERT
    if kind == "denial" or any(hint in label for hint in _DENIAL_HINTS):
        return WebSurfaceKind.DENIAL
    if kind == MandatorySemanticKind.FEEDBACK.value:
        return WebSurfaceKind.LIVE_REGION
    if kind == MandatorySemanticKind.ACTION.value:
        return WebSurfaceKind.ACTION
    if "form" in kind or "form" in label:
        return WebSurfaceKind.FORM
    if any(token in kind or token in label for token in ("input", "textbox", "field")):
        return WebSurfaceKind.CONTROL
    if any(token in kind or token in label for token in ("nav", "banner", "main")):
        return WebSurfaceKind.LANDMARK
    return WebSurfaceKind.REGION


def _interaction_state_for_node(node: ProjectedNode) -> WebInteractionState:
    kind = node.semantic_kind.lower()
    label = (node.label or node.item_id or "").lower()
    if kind in _CONFIRM_KINDS:
        return WebInteractionState.CONFIRMATION
    if kind in _ERROR_KINDS:
        return WebInteractionState.ERROR
    if kind == "denial" or any(hint in label for hint in _DENIAL_HINTS):
        return WebInteractionState.DENIAL
    if any(hint in label for hint in _PENDING_HINTS) or kind == "pending":
        return WebInteractionState.PENDING
    if node.disposition is PresentationDisposition.UNSATISFIABLE:
        return WebInteractionState.DENIAL
    return WebInteractionState.IDLE


def _status_tone(state: WebInteractionState, kind: WebSurfaceKind) -> str:
    if state is WebInteractionState.ERROR or kind is WebSurfaceKind.ALERT:
        return "danger"
    if state is WebInteractionState.DENIAL or kind is WebSurfaceKind.DENIAL:
        return "danger"
    if state is WebInteractionState.CONFIRMATION or kind is WebSurfaceKind.CONFIRMATION:
        return "warning"
    if state is WebInteractionState.PENDING:
        return "active"
    if state is WebInteractionState.SUCCESS:
        return "success"
    if state is WebInteractionState.INVALID:
        return "danger"
    return "neutral"


def _live_for(state: WebInteractionState, kind: WebSurfaceKind, semantic: str) -> WebLiveRegion:
    if (
        state in {WebInteractionState.ERROR, WebInteractionState.DENIAL}
        or kind in {WebSurfaceKind.ALERT, WebSurfaceKind.DENIAL}
        or semantic == MandatorySemanticKind.ERROR.value
    ):
        return WebLiveRegion(politeness="assertive", atomic=True)
    if (
        state is WebInteractionState.CONFIRMATION
        or kind is WebSurfaceKind.CONFIRMATION
    ):
        return WebLiveRegion(politeness="assertive", atomic=True)
    if (
        state is WebInteractionState.PENDING
        or kind is WebSurfaceKind.LIVE_REGION
        or semantic == MandatorySemanticKind.FEEDBACK.value
    ):
        return WebLiveRegion(politeness="polite", atomic=False)
    return WebLiveRegion()


def _actions_for(node: ProjectedNode, kind: WebSurfaceKind) -> tuple[str, ...]:
    semantic = node.semantic_kind.lower()
    if kind is WebSurfaceKind.CONFIRMATION:
        return ("confirm", "dismiss")
    if kind is WebSurfaceKind.DENIAL:
        return ("dismiss",)
    if kind is WebSurfaceKind.ACTION or semantic == MandatorySemanticKind.ACTION.value:
        return ("activate",)
    if kind is WebSurfaceKind.FORM:
        return ("submit",)
    if kind is WebSurfaceKind.CONTROL:
        return ("edit",)
    return ()


def _body_for(
    node: ProjectedNode,
    kind: WebSurfaceKind,
    title: str,
) -> str:
    if kind is WebSurfaceKind.CONFIRMATION:
        return f"Confirm: {title}"
    if kind is WebSurfaceKind.DENIAL:
        return f"Denied: {title}"
    if kind is WebSurfaceKind.ALERT:
        return f"Error: {title}"
    if kind is WebSurfaceKind.FALLBACK:
        return f"Fallback: {title}"
    if _interaction_state_for_node(node) is WebInteractionState.PENDING:
        return f"Pending: {title}"
    return title


def _build_node_from_projected(
    node: ProjectedNode,
    *,
    order_index: int,
) -> WebNodeModel:
    kind = _surface_for_node(node)
    interaction = _interaction_state_for_node(node)
    title = _sanitize_text(node.label or node.component_id or node.item_id) or node.item_id
    role = _role_for_node(node)
    # Unsatisfiable / denial / error / confirmation always visible + accessible.
    force_visible = kind in {
        WebSurfaceKind.DENIAL,
        WebSurfaceKind.ALERT,
        WebSurfaceKind.CONFIRMATION,
    } or node.mandatory
    states: dict[str, str] = {}
    if interaction is WebInteractionState.PENDING:
        states["busy"] = "true"
    if interaction is WebInteractionState.DISABLED:
        states["disabled"] = "true"
    if kind is WebSurfaceKind.CONFIRMATION:
        states["modal"] = "true"

    return WebNodeModel(
        node_id=f"web:{node.item_id}",
        kind=kind,
        role=f"aria:{role}",
        name=title,
        semantic_kind=node.semantic_kind,
        disposition=node.disposition.value,
        order=order_index,
        value="",
        description="",
        states=states,
        actions=_actions_for(node, kind),
        relationships=(),
        validation=WebFormValidation(),
        live=_live_for(interaction, kind, node.semantic_kind),
        interaction_state=interaction,
        mandatory=node.mandatory,
        visible=True if force_visible else True,
        accessible=True,
        component_id=node.component_id,
        source_item_id=node.item_id,
        body=_body_for(node, kind, title),
        status_tone=_status_tone(interaction, kind),
        fallback_ref=node.fallback_ref,
        metadata={
            "source_order": node.order,
            "component_id": node.component_id,
        },
    )


def _build_nodes_from_dom_aria(
    result: DomAriaAdapterResult,
) -> tuple[
    list[WebNodeModel],
    list[WebSourceMetadata],
    list[WebLossReceipt],
    list[str],
]:
    """Map a DOM/ARIA adapter result into web nodes preserving semantics."""

    nodes: list[WebNodeModel] = []
    source_metadata: list[WebSourceMetadata] = []
    losses: list[WebLossReceipt] = []
    focus_order: list[str] = []

    loc_text: dict[str, str] = {}
    for loc in result.localization:
        loc_text[loc.localization_id] = loc.default_text

    a11y_by_id = {a.component_id: a for a in result.accessibility}

    # Relationship edges from composition.
    rels_by_source: dict[str, list[WebRelationship]] = {}
    for edge in result.composition_edges:
        kind = edge.kind.value if hasattr(edge.kind, "value") else str(edge.kind)
        if kind == "child":
            continue
        rel_kind = {
            "label": "labelledby",
            "described_by": "describedby",
            "owns": "owns",
            "flow": "flowto",
        }.get(kind, kind)
        rel = WebRelationship(
            kind=rel_kind,
            source_node_id=edge.source_component_id,
            target_node_id=edge.target_component_id,
        )
        rels_by_source.setdefault(edge.source_component_id, []).append(rel)

    for index, component in enumerate(result.components):
        node_id = component.component_id
        role = component.role.removeprefix("aria:")
        name = loc_text.get(component.accessible_name_ref, "") or role
        description = loc_text.get(component.accessible_description_ref, "")
        states = dict(result.node_states.get(node_id, {}))
        value = result.node_values.get(node_id, "")
        validation_raw = result.node_validations.get(node_id, {})
        live_raw = result.live_regions.get(node_id, {})
        actions = tuple(result.actions_by_node.get(node_id, ()))

        validation = WebFormValidation(
            valid=validation_raw.get("valid"),
            message=_sanitize_text(validation_raw.get("message") or ""),
            required=bool(validation_raw.get("required")),
            invalid_state=str(validation_raw.get("invalid_state") or ""),
        )
        live = WebLiveRegion(
            politeness=str(live_raw.get("politeness") or "off"),
            atomic=bool(live_raw.get("atomic", False)),
            relevant=str(live_raw.get("relevant") or "additions text"),
        )

        kind = _surface_kind_from_role(role, states, validation, live, name)
        interaction = _interaction_from_states(states, validation, kind)
        a11y = a11y_by_id.get(node_id)

        # Force visibility for critical semantics.
        visible = True
        accessible = True
        if states.get("hidden", "").lower() in {"true", "1", "hidden"}:
            if kind not in {
                WebSurfaceKind.DENIAL,
                WebSurfaceKind.ALERT,
                WebSurfaceKind.CONFIRMATION,
            }:
                visible = False

        body = name
        if kind is WebSurfaceKind.DENIAL:
            body = f"Denied: {name}"
        elif kind is WebSurfaceKind.ALERT:
            body = f"Error: {name}" if not validation.message else validation.message
        elif kind is WebSurfaceKind.CONFIRMATION:
            body = f"Confirm: {name}"
        elif validation.message:
            body = validation.message

        web_node = WebNodeModel(
            node_id=node_id,
            kind=kind,
            role=component.role if component.role.startswith("aria:") else f"aria:{role}",
            name=_sanitize_text(name) or role,
            semantic_kind=_semantic_from_role(role, kind),
            disposition=PresentationDisposition.PRESERVED.value,
            order=index,
            value=_sanitize_text(value),
            description=_sanitize_text(description),
            states=states,
            actions=actions,
            relationships=tuple(rels_by_source.get(node_id, ())),
            validation=validation,
            live=live,
            interaction_state=interaction,
            mandatory=kind
            in {
                WebSurfaceKind.DENIAL,
                WebSurfaceKind.ALERT,
                WebSurfaceKind.CONFIRMATION,
            },
            visible=visible,
            accessible=accessible,
            component_id=node_id,
            source_item_id=node_id,
            body=_sanitize_text(body),
            status_tone=_status_tone(interaction, kind),
            children=tuple(component.child_ids),
            metadata={
                "presentation_classification": component.presentation_classification,
                "live_region_binding": bool(a11y.live_region) if a11y else False,
            },
        )
        nodes.append(web_node)

    for meta in result.source_metadata:
        source_metadata.append(
            WebSourceMetadata(
                metadata_id=meta.metadata_id,
                node_id=meta.node_id,
                tag_name=meta.tag_name,
                css_classes=meta.css_classes,
                css_inline_summary=meta.css_inline_summary,
                framework_hints=dict(meta.framework_hints),
                attributes_retained=dict(meta.attributes_retained),
            )
        )
        if meta.css_classes or meta.css_inline_summary:
            losses.append(
                WebLossReceipt(
                    loss_id=f"loss:css-metadata:{meta.node_id}",
                    path=f"source_metadata/{meta.node_id}/css",
                    reason="CSS retained as source metadata only; not reconstructed",
                    category="source_metadata",
                    detail=meta.css_inline_summary
                    or " ".join(meta.css_classes),
                )
            )
        if meta.framework_hints:
            losses.append(
                WebLossReceipt(
                    loss_id=f"loss:framework-metadata:{meta.node_id}",
                    path=f"source_metadata/{meta.node_id}/framework",
                    reason="Framework hints retained as source metadata only",
                    category="source_metadata",
                    detail=",".join(
                        f"{k}={v}" for k, v in sorted(meta.framework_hints.items())
                    ),
                )
            )

    for loss in result.losses:
        losses.append(
            WebLossReceipt(
                loss_id=loss.loss_id,
                path=loss.path,
                reason=loss.reason,
                category=loss.category.value
                if hasattr(loss.category, "value")
                else str(loss.category),
                detail=loss.detail,
            )
        )

    # Focus order: prefer adapter focus_order, then focusable roles.
    if result.focus_order:
        focus_order = list(result.focus_order)
    else:
        for node in nodes:
            if _is_focusable_role(node.role, node.states):
                focus_order.append(node.node_id)

    # Stamp focus_index onto nodes.
    focus_index_map = {nid: idx for idx, nid in enumerate(focus_order)}
    stamped: list[WebNodeModel] = []
    for node in nodes:
        stamped.append(
            WebNodeModel(
                node_id=node.node_id,
                kind=node.kind,
                role=node.role,
                name=node.name,
                semantic_kind=node.semantic_kind,
                disposition=node.disposition,
                order=node.order,
                focus_index=focus_index_map.get(node.node_id),
                value=node.value,
                description=node.description,
                states=node.states,
                actions=node.actions,
                relationships=node.relationships,
                validation=node.validation,
                live=node.live,
                interaction_state=node.interaction_state,
                mandatory=node.mandatory,
                visible=node.visible,
                accessible=node.accessible,
                component_id=node.component_id,
                source_item_id=node.source_item_id,
                body=node.body,
                status_tone=node.status_tone,
                fallback_ref=node.fallback_ref,
                source_metadata_id=f"meta:{node.node_id}",
                children=node.children,
                metadata=node.metadata,
            )
        )
    return stamped, source_metadata, losses, focus_order


def _surface_kind_from_role(
    role: str,
    states: Mapping[str, str],
    validation: WebFormValidation,
    live: WebLiveRegion,
    name: str,
) -> WebSurfaceKind:
    role_l = role.removeprefix("aria:").lower()
    name_l = name.lower()
    if role_l in {"alertdialog"} or "confirm" in name_l:
        return WebSurfaceKind.CONFIRMATION
    if role_l == "alert" or any(h in name_l for h in _DENIAL_HINTS):
        if any(h in name_l for h in _DENIAL_HINTS):
            return WebSurfaceKind.DENIAL
        return WebSurfaceKind.ALERT
    if role_l == "dialog":
        return WebSurfaceKind.CONFIRMATION
    if role_l == "form":
        return WebSurfaceKind.FORM
    if role_l in {
        "button",
        "link",
        "menuitem",
        "tab",
    }:
        return WebSurfaceKind.ACTION
    if role_l in {
        "textbox",
        "checkbox",
        "radio",
        "switch",
        "combobox",
        "listbox",
        "slider",
        "spinbutton",
        "option",
    }:
        return WebSurfaceKind.CONTROL
    if live.politeness in {"polite", "assertive"} or role_l in {"status", "log"}:
        return WebSurfaceKind.LIVE_REGION
    if role_l in {
        "navigation",
        "main",
        "banner",
        "contentinfo",
        "complementary",
        "region",
        "search",
    }:
        return WebSurfaceKind.LANDMARK
    if validation.message or validation.invalid_state == "true":
        return WebSurfaceKind.CONTROL
    if states.get("disabled", "").lower() in {"true", "1"}:
        return WebSurfaceKind.CONTROL
    return WebSurfaceKind.REGION


def _interaction_from_states(
    states: Mapping[str, str],
    validation: WebFormValidation,
    kind: WebSurfaceKind,
) -> WebInteractionState:
    if kind is WebSurfaceKind.CONFIRMATION:
        return WebInteractionState.CONFIRMATION
    if kind is WebSurfaceKind.DENIAL:
        return WebInteractionState.DENIAL
    if kind is WebSurfaceKind.ALERT:
        return WebInteractionState.ERROR
    if validation.valid is False or validation.invalid_state == "true":
        return WebInteractionState.INVALID
    if states.get("busy", "").lower() in {"true", "1", "busy"}:
        return WebInteractionState.PENDING
    if states.get("disabled", "").lower() in {"true", "1", "disabled"}:
        return WebInteractionState.DISABLED
    return WebInteractionState.IDLE


def _semantic_from_role(role: str, kind: WebSurfaceKind) -> str:
    if kind is WebSurfaceKind.CONFIRMATION:
        return MandatorySemanticKind.CONFIRMATION.value
    if kind is WebSurfaceKind.DENIAL:
        return "denial"
    if kind is WebSurfaceKind.ALERT:
        return MandatorySemanticKind.ERROR.value
    if kind is WebSurfaceKind.ACTION:
        return MandatorySemanticKind.ACTION.value
    if kind is WebSurfaceKind.LIVE_REGION:
        return MandatorySemanticKind.FEEDBACK.value
    if kind is WebSurfaceKind.FORM:
        return "form"
    role_l = role.removeprefix("aria:")
    return role_l or "region"


def _is_focusable_role(role: str, states: Mapping[str, str]) -> bool:
    role_l = role.removeprefix("aria:")
    if states.get("disabled", "").lower() in {"true", "1", "disabled"}:
        return False
    if states.get("hidden", "").lower() in {"true", "1", "hidden"}:
        return False
    return role_l in {
        "button",
        "link",
        "textbox",
        "checkbox",
        "radio",
        "switch",
        "combobox",
        "listbox",
        "option",
        "slider",
        "spinbutton",
        "tab",
        "menuitem",
        "treeitem",
        "search",
        "dialog",
        "alertdialog",
    }


def _focus_plan_from_nodes(
    nodes: Sequence[WebNodeModel],
    focus_order: Sequence[str],
    *,
    keyboard_mode: WebKeyboardNavMode,
) -> WebFocusPlan:
    confirmations = [n for n in nodes if n.kind is WebSurfaceKind.CONFIRMATION]
    denials = [n for n in nodes if n.kind is WebSurfaceKind.DENIAL]
    actions = [
        n
        for n in nodes
        if n.kind is WebSurfaceKind.ACTION
        or n.semantic_kind == MandatorySemanticKind.ACTION.value
    ]
    trap = bool(confirmations or denials)
    mode = WebKeyboardNavMode.DIALOG_TRAP if trap else keyboard_mode
    if confirmations:
        restore = actions[0].node_id if actions else ""
        return WebFocusPlan(
            order=tuple(focus_order),
            restore_strategy=(
                WebFocusRestoreStrategy.PREVIOUS_TARGET
                if restore
                else WebFocusRestoreStrategy.FIRST_ACTIONABLE
            ),
            restore_target_id=restore,
            keyboard_mode=mode,
            trap_while_modal=True,
            announce_on_restore=True,
        )
    if denials:
        restore = actions[0].node_id if actions else (focus_order[0] if focus_order else "")
        return WebFocusPlan(
            order=tuple(focus_order),
            restore_strategy=WebFocusRestoreStrategy.PREVIOUS_TARGET,
            restore_target_id=restore,
            keyboard_mode=mode,
            trap_while_modal=True,
            announce_on_restore=True,
        )
    if actions:
        return WebFocusPlan(
            order=tuple(focus_order),
            restore_strategy=WebFocusRestoreStrategy.ENTRY_COMPONENT,
            restore_target_id=actions[0].node_id,
            keyboard_mode=keyboard_mode,
            trap_while_modal=False,
            announce_on_restore=True,
        )
    return WebFocusPlan(
        order=tuple(focus_order),
        restore_strategy=WebFocusRestoreStrategy.ANNOUNCE_ONLY,
        restore_target_id="",
        keyboard_mode=keyboard_mode,
        trap_while_modal=False,
        announce_on_restore=True,
    )


def _stamp_focus(
    nodes: Sequence[WebNodeModel],
    focus_order: Sequence[str],
) -> list[WebNodeModel]:
    focus_index_map = {nid: idx for idx, nid in enumerate(focus_order)}
    stamped: list[WebNodeModel] = []
    for node in nodes:
        stamped.append(
            WebNodeModel(
                node_id=node.node_id,
                kind=node.kind,
                role=node.role,
                name=node.name,
                semantic_kind=node.semantic_kind,
                disposition=node.disposition,
                order=node.order,
                focus_index=focus_index_map.get(node.node_id),
                value=node.value,
                description=node.description,
                states=node.states,
                actions=node.actions,
                relationships=node.relationships,
                validation=node.validation,
                live=node.live,
                interaction_state=node.interaction_state,
                mandatory=node.mandatory,
                visible=node.visible,
                accessible=node.accessible,
                component_id=node.component_id,
                source_item_id=node.source_item_id,
                body=node.body,
                status_tone=node.status_tone,
                fallback_ref=node.fallback_ref,
                source_metadata_id=node.source_metadata_id,
                children=node.children,
                metadata=node.metadata,
            )
        )
    return stamped


def _ensure_projection_artifact(
    source: UIProjectionArtifact
    | ProjectionProblem
    | UIIRDocument
    | Mapping[str, Any],
    *,
    profile: UIDeviceProfile | None = None,
    policy: ProjectionPolicy | None = None,
) -> UIProjectionArtifact:
    if isinstance(source, UIProjectionArtifact):
        return source.validate()

    device_profile = profile or desktop_profile()
    if not isinstance(device_profile, UIDeviceProfile):
        raise UIIRValidationError(
            "profile must be a UIDeviceProfile when solving for web"
        )

    if isinstance(source, ProjectionProblem):
        return project_ui_ir(source, device_profile, policy)

    if isinstance(source, Mapping) and source.get("interface") == (
        "UIProjectionArtifact@1"
    ):
        raise UIIRValidationError(
            "raw UIProjectionArtifact mappings must be constructed as "
            "UIProjectionArtifact instances before web projection"
        )

    return project_ui_ir(source, device_profile, policy)


def project_to_web(
    source: UIProjectionArtifact
    | ProjectionProblem
    | UIIRDocument
    | DomAriaAdapterResult
    | DomAriaDocument
    | Mapping[str, Any],
    *,
    profile: UIDeviceProfile | None = None,
    policy: ProjectionPolicy | None = None,
    options: WebProjectionOptions | None = None,
) -> WebProjectionArtifact:
    """Project a shared projection artifact, document, or DOM/ARIA result to web.

    Does **not** invent policy: when given a document/problem, delegates to
    :func:`project_ui_ir` with the reference desktop profile. Never executes
    markup or scripts.
    """

    opts = (options or WebProjectionOptions()).validate()

    # DOM/ARIA direct path preserves full semantic subset.
    if isinstance(source, DomAriaAdapterResult):
        return _project_from_dom_aria(source, options=opts)
    if isinstance(source, DomAriaDocument):
        return _project_from_dom_aria(adapt_dom_aria_to_uiir(source), options=opts)
    if isinstance(source, Mapping) and (
        source.get("adapter") == DOMARIA_UIIR_ADAPTER
        or source.get("schema_version") == "dom-aria-uiir-adapter/v1"
    ):
        # Accept adapter-result-shaped mappings by re-adapting from embedded doc
        # is not available; treat as error with clear guidance.
        raise UIIRValidationError(
            "DOM/ARIA adapter result mappings must be DomAriaAdapterResult or "
            "DomAriaDocument instances; pass adapt_dom_aria_to_uiir(...) output"
        )
    if isinstance(source, Mapping) and (
        "root" in source and ("document_id" in source or "title" in source)
    ):
        # Treat as DomAriaDocument mapping.
        adapted = adapt_dom_aria_to_uiir(source)
        return _project_from_dom_aria(adapted, options=opts)

    device_profile = profile or desktop_profile()
    artifact = _ensure_projection_artifact(
        source, profile=device_profile, policy=policy
    )

    nodes: list[WebNodeModel] = []
    sorted_nodes = sorted(artifact.nodes, key=lambda n: (n.order, n.item_id))
    for index, node in enumerate(sorted_nodes):
        nodes.append(_build_node_from_projected(node, order_index=index))

    # Explicit unsatisfiable banner when projection status demands it.
    if artifact.status is ProjectionStatus.UNSATISFIABLE and not any(
        n.kind is WebSurfaceKind.DENIAL for n in nodes
    ):
        nodes.append(
            WebNodeModel(
                node_id="web:denial:unsatisfiable",
                kind=WebSurfaceKind.DENIAL,
                role="aria:alert",
                name="Projection unsatisfiable",
                semantic_kind="denial",
                disposition=PresentationDisposition.UNSATISFIABLE.value,
                order=len(nodes),
                actions=("dismiss",),
                live=WebLiveRegion(politeness="assertive", atomic=True),
                interaction_state=WebInteractionState.DENIAL,
                mandatory=True,
                visible=True,
                accessible=True,
                body="Denied: required web surface cannot be projected",
                status_tone="danger",
                source_item_id="denial:unsatisfiable",
            )
        )

    # Focus order: actionable nodes first by order, then remaining.
    focus_order: list[str] = []
    for node in sorted(nodes, key=lambda n: (n.order, n.node_id)):
        if node.focus_index is not None:
            continue
        if node.kind in {
            WebSurfaceKind.ACTION,
            WebSurfaceKind.CONTROL,
            WebSurfaceKind.FORM,
            WebSurfaceKind.CONFIRMATION,
            WebSurfaceKind.DENIAL,
        } or _is_focusable_role(node.role, node.states):
            focus_order.append(node.node_id)
    # Modal surfaces first in focus order for accessibility.
    modal_ids = [
        n.node_id
        for n in nodes
        if n.kind in {WebSurfaceKind.CONFIRMATION, WebSurfaceKind.DENIAL}
    ]
    if modal_ids:
        rest = [nid for nid in focus_order if nid not in set(modal_ids)]
        focus_order = modal_ids + rest

    nodes = _stamp_focus(nodes, focus_order)
    focus = _focus_plan_from_nodes(nodes, focus_order, keyboard_mode=opts.keyboard_mode)

    loss_report: Mapping[str, Any] = {}
    if artifact.loss_report is not None:
        loss_report = artifact.loss_report.to_dict()

    losses: list[WebLossReceipt] = []
    for entry in getattr(artifact.loss_report, "losses", ()) or ():
        losses.append(
            WebLossReceipt(
                loss_id=getattr(entry, "loss_id", f"loss:{getattr(entry, 'semantic_id', 'x')}"),
                path=getattr(entry, "semantic_id", ""),
                reason=getattr(entry, "reason", "projection loss"),
                category=(
                    entry.category.value
                    if hasattr(getattr(entry, "category", None), "value")
                    else str(getattr(entry, "category", "unsupported"))
                ),
                detail=getattr(entry, "semantic_kind", ""),
            )
        )

    notes = list(opts.notes)
    notes.append("web is presentation-only; policy_owner=UIProjectionSolver@1")
    notes.append("execution_performed=false; markup/scripts are never executed")
    if device_profile.family not in {ProfileFamily.DESKTOP, ProfileFamily.CUSTOM}:
        notes.append(
            f"source profile family {device_profile.family.value}; "
            "web remains presentation-only"
        )

    result = WebProjectionArtifact(
        artifact_id=f"web:{artifact.artifact_id}",
        nodes=tuple(nodes),
        focus=focus,
        source_metadata=(),
        losses=tuple(losses),
        projection_artifact_id=artifact.artifact_id,
        projection_status=artifact.status.value,
        profile_id=artifact.profile_id or device_profile.profile_id,
        document_id=artifact.document_id,
        loss_report=loss_report,
        policy_owner="UIProjectionSolver@1",
        notes=tuple(notes),
        execution_performed=False,
    )
    return result.validate()


def _project_from_dom_aria(
    adapted: DomAriaAdapterResult,
    *,
    options: WebProjectionOptions,
) -> WebProjectionArtifact:
    nodes, source_metadata, losses, focus_order = _build_nodes_from_dom_aria(adapted)
    if not options.include_source_metadata:
        # Still report CSS/framework as losses, drop retained metadata payload.
        source_metadata = []
    focus = _focus_plan_from_nodes(
        nodes, focus_order, keyboard_mode=options.keyboard_mode
    )
    notes = list(options.notes)
    notes.append("projected from DOMARIAUIIRAdapter@1")
    notes.append("execution_performed=false; imported markup/scripts never executed")
    notes.append("CSS/framework details retained as source metadata or loss receipts")

    result = WebProjectionArtifact(
        artifact_id=f"web:dom-aria:{adapted.document_id}",
        nodes=tuple(nodes),
        focus=focus,
        source_metadata=tuple(source_metadata),
        losses=tuple(losses),
        projection_artifact_id="",
        projection_status="satisfied",
        profile_id="profile:desktop:default",
        document_id=adapted.document_id,
        loss_report={},
        policy_owner="UIProjectionSolver@1",
        notes=tuple(notes),
        execution_performed=False,
    )
    return result.validate()


def render_web(
    source: UIProjectionArtifact
    | ProjectionProblem
    | UIIRDocument
    | DomAriaAdapterResult
    | DomAriaDocument
    | Mapping[str, Any]
    | WebProjectionArtifact,
    *,
    profile: UIDeviceProfile | None = None,
    policy: ProjectionPolicy | None = None,
    options: WebProjectionOptions | None = None,
) -> dict[str, Any]:
    """Render a sanitized accessible HTML model (never executes scripts)."""

    if isinstance(source, WebProjectionArtifact):
        artifact = source.validate()
    else:
        artifact = project_to_web(
            source, profile=profile, policy=policy, options=options
        )
    model = artifact.to_accessible_html_model()
    model["artifact_id"] = artifact.artifact_id
    model["document_id"] = artifact.document_id
    model["losses"] = [loss.to_dict() for loss in artifact.losses]
    model["source_metadata"] = [meta.to_dict() for meta in artifact.source_metadata]
    return model


class UIIRWebRenderer:
    """Reference web/desktop renderer implementing UIIRWebRenderer@1."""

    interface: str = UIIR_WEB_RENDERER_INTERFACE

    def project(
        self,
        source: UIProjectionArtifact
        | ProjectionProblem
        | UIIRDocument
        | DomAriaAdapterResult
        | DomAriaDocument
        | Mapping[str, Any],
        *,
        profile: UIDeviceProfile | None = None,
        policy: ProjectionPolicy | None = None,
        options: WebProjectionOptions | None = None,
    ) -> WebProjectionArtifact:
        return project_to_web(
            source, profile=profile, policy=policy, options=options
        )

    def render(
        self,
        source: UIProjectionArtifact
        | ProjectionProblem
        | UIIRDocument
        | DomAriaAdapterResult
        | DomAriaDocument
        | Mapping[str, Any]
        | WebProjectionArtifact,
        *,
        profile: UIDeviceProfile | None = None,
        policy: ProjectionPolicy | None = None,
        options: WebProjectionOptions | None = None,
    ) -> dict[str, Any]:
        return render_web(
            source, profile=profile, policy=policy, options=options
        )


def web_projection_from_document(
    document: UIIRDocument | Mapping[str, Any],
    *,
    profile: UIDeviceProfile | None = None,
    policy: ProjectionPolicy | None = None,
    options: WebProjectionOptions | None = None,
) -> WebProjectionArtifact:
    """Convenience: document → shared solver (desktop profile) → web models."""

    return project_to_web(
        document,
        profile=profile or desktop_profile(),
        policy=policy,
        options=options,
    )


def web_pilot_problem() -> ProjectionProblem:
    """Reference web pilot problem covering denial/error/confirmation/action."""

    items = (
        ProjectionItem(
            item_id="action_submit",
            semantic_kind=MandatorySemanticKind.ACTION.value,
            mandatory=True,
            required_capability_ids=("pointer_mouse", "keyboard", "display"),
            component_id="btn_submit",
            label="Submit",
            action_cost=1,
            text_chars=12,
            priority=10,
        ),
        ProjectionItem(
            item_id="confirm_delete",
            semantic_kind=MandatorySemanticKind.CONFIRMATION.value,
            mandatory=True,
            required_capability_ids=("display", "keyboard"),
            component_id="dlg_confirm",
            label="Confirm delete",
            action_cost=1,
            text_chars=20,
            priority=5,
        ),
        ProjectionItem(
            item_id="error_surface",
            semantic_kind=MandatorySemanticKind.ERROR.value,
            mandatory=True,
            required_capability_ids=("display",),
            component_id="err_banner",
            label="Something failed",
            text_chars=30,
            priority=3,
        ),
        ProjectionItem(
            item_id="denial_surface",
            semantic_kind="denial",
            mandatory=True,
            required_capability_ids=("display",),
            component_id="deny_banner",
            label="Access denied",
            text_chars=24,
            priority=2,
        ),
        ProjectionItem(
            item_id="feedback_pending",
            semantic_kind=MandatorySemanticKind.FEEDBACK.value,
            mandatory=True,
            required_capability_ids=("display",),
            component_id="status_pending",
            label="Working…",
            text_chars=10,
            priority=15,
        ),
        ProjectionItem(
            item_id="form_email",
            semantic_kind="textbox",
            mandatory=False,
            required_capability_ids=("keyboard", "display"),
            component_id="field_email",
            label="Email",
            text_chars=40,
            priority=20,
        ),
    )
    return ProjectionProblem(problem_id="pweb", items=items, document_id="doc:web")


__all__ = [
    "UIIRWebRenderer",
    "UIIR_WEB_PROJECTION_INTERFACE",
    "UIIR_WEB_PROJECTION_SCHEMA_VERSION",
    "UIIR_WEB_RENDERER_INTERFACE",
    "UIIR_WEB_RENDER_MODEL_VERSION",
    "WebFocusPlan",
    "WebFocusRestoreStrategy",
    "WebFormValidation",
    "WebInteractionState",
    "WebKeyboardNavMode",
    "WebLiveRegion",
    "WebLossReceipt",
    "WebNodeModel",
    "WebProjectionArtifact",
    "WebProjectionOptions",
    "WebRelationship",
    "WebSourceMetadata",
    "WebSurfaceKind",
    "project_to_web",
    "render_web",
    "web_pilot_problem",
    "web_projection_from_document",
]
