"""Mobile companion projection adapter (UIIRMobileProjection@1).

Projects a shared :class:`UIProjectionArtifact` (or a document/problem solved
under the reference mobile profile) into mobile card/form/list/navigation/
confirmation/fallback models.

Mobile is a **presentation target**, not a separate policy owner. Capability
negotiation, budget enforcement, and loss receipts remain owned by the
projection core (``capabilities`` / ``solver`` / ``loss``). This module only
maps already-solved projection nodes into companion-surface descriptors with
explicit:

- touch targets
- orientation
- safe areas
- virtual keyboard
- screen-reader order
- focus restoration
- pending / error / confirmation states
- offline / unavailable states
- glasses → mobile companion fallback

Side-effect free: no network, device SDK, or ORB calls.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Mapping, Sequence

from ..schema import AdaptationPolicy, UIIRDocument, UIIRValidationError
from .capabilities import ProfileFamily, UIDeviceProfile, mobile_profile
from .loss import MandatorySemanticKind, MANDATORY_SEMANTIC_KINDS
from .solver import (
    PresentationDisposition,
    ProjectedNode,
    ProjectionPolicy,
    ProjectionProblem,
    ProjectionStatus,
    UIProjectionArtifact,
    project_ui_ir,
    projection_problem_from_document,
)

UIIR_MOBILE_PROJECTION_INTERFACE: Final = "UIIRMobileProjection@1"
UIIR_MOBILE_PROJECTION_SCHEMA_VERSION: Final = "ui-mobile-projection/v1"
UIIR_MOBILE_ADAPTER_INTERFACE: Final = "UIIRMobileAdapter@1"

# WCAG / platform-aligned minimum interactive target (CSS px / density-independent).
MIN_TOUCH_TARGET_DP: Final = 44
MIN_TOUCH_SPACING_DP: Final = 8

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

# Role → mobile surface model mapping (presentation only).
_FORM_ROLES: Final = frozenset(
    {
        "form",
        "aria:form",
        "textbox",
        "aria:textbox",
        "searchbox",
        "aria:searchbox",
        "combobox",
        "aria:combobox",
        "spinbutton",
        "aria:spinbutton",
        "checkbox",
        "aria:checkbox",
        "radio",
        "aria:radio",
        "switch",
        "aria:switch",
        "slider",
        "aria:slider",
        "listbox",
        "aria:listbox",
    }
)
_LIST_ROLES: Final = frozenset(
    {
        "list",
        "aria:list",
        "listitem",
        "aria:listitem",
        "grid",
        "aria:grid",
        "table",
        "aria:table",
        "tree",
        "aria:tree",
        "menu",
        "aria:menu",
        "menuitem",
        "aria:menuitem",
    }
)
_NAV_ROLES: Final = frozenset(
    {
        "navigation",
        "aria:navigation",
        "tablist",
        "aria:tablist",
        "tab",
        "aria:tab",
        "menubar",
        "aria:menubar",
        "breadcrumb",
    }
)
_CONFIRM_KINDS: Final = frozenset(
    {
        MandatorySemanticKind.CONFIRMATION.value,
        MandatorySemanticKind.CONSENT.value,
        MandatorySemanticKind.CONSEQUENCE.value,
    }
)
_ERROR_KINDS: Final = frozenset({MandatorySemanticKind.ERROR.value})
_PENDING_HINTS: Final = frozenset(
    {"pending", "loading", "in_progress", "busy", "progress"}
)


class MobileSurfaceKind(str, Enum):
    """Closed mobile companion surface models."""

    CARD = "card"
    FORM = "form"
    LIST = "list"
    NAVIGATION = "navigation"
    CONFIRMATION = "confirmation"
    FALLBACK = "fallback"
    STATUS = "status"


class OrientationPolicy(str, Enum):
    """How the companion may reflow under device orientation."""

    PORTRAIT_PREFERRED = "portrait_preferred"
    LANDSCAPE_SUPPORTED = "landscape_supported"
    ANY = "any"
    LOCKED_PORTRAIT = "locked_portrait"


class ConnectivityState(str, Enum):
    """Companion connectivity / availability presentation."""

    ONLINE = "online"
    OFFLINE = "offline"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


class InteractionState(str, Enum):
    """Cross-cutting interaction presentation states."""

    IDLE = "idle"
    PENDING = "pending"
    ERROR = "error"
    CONFIRMATION = "confirmation"
    SUCCESS = "success"
    OFFLINE = "offline"
    UNAVAILABLE = "unavailable"


class FocusRestoreStrategy(str, Enum):
    """How focus returns after modal/confirmation/navigation."""

    PREVIOUS_TARGET = "previous_target"
    ENTRY_COMPONENT = "entry_component"
    FIRST_ACTIONABLE = "first_actionable"
    ANNOUNCE_ONLY = "announce_only"


class GlassesFallbackReason(str, Enum):
    """Why glasses content is projected onto the mobile companion."""

    NONE = "none"
    GLASSES_BUDGET = "glasses_budget"
    GLASSES_UNAVAILABLE = "glasses_unavailable"
    GLASSES_POLICY_FALLBACK = "glasses_policy_fallback"
    EXPLICIT_MOBILE_COMPANION = "explicit_mobile_companion"
    SPATIAL_UNSUPPORTED = "spatial_unsupported"


def _validate_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise UIIRValidationError(f"{name} is not a stable identifier: {value!r}")


def _require_tuple(name: str, value: Any) -> None:
    if not isinstance(value, tuple):
        raise UIIRValidationError(f"{name} must be an immutable tuple")


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        result = value.to_dict()
        if isinstance(result, Mapping):
            return result
    return None


def _node_role_hint(node: ProjectedNode | Mapping[str, Any]) -> str:
    if isinstance(node, ProjectedNode):
        label = (node.label or "").lower()
        kind = node.semantic_kind.lower()
        component_id = (node.component_id or "").lower()
    else:
        label = str(node.get("label") or "").lower()
        kind = str(node.get("semantic_kind") or "").lower()
        component_id = str(node.get("component_id") or "").lower()
    for token in (label, kind, component_id):
        if token in _FORM_ROLES or any(r in token for r in ("form", "input", "field")):
            return "form"
        if token in _LIST_ROLES or "list" in token:
            return "list"
        if token in _NAV_ROLES or "nav" in token:
            return "navigation"
    return ""


def _surface_for_node(node: ProjectedNode) -> MobileSurfaceKind:
    kind = node.semantic_kind.lower()
    disposition = node.disposition

    if disposition is PresentationDisposition.FALLBACK:
        return MobileSurfaceKind.FALLBACK
    if disposition is PresentationDisposition.UNSATISFIABLE:
        return MobileSurfaceKind.STATUS
    if kind in _CONFIRM_KINDS:
        return MobileSurfaceKind.CONFIRMATION
    if kind in _ERROR_KINDS:
        return MobileSurfaceKind.STATUS
    if kind == MandatorySemanticKind.FEEDBACK.value:
        return MobileSurfaceKind.STATUS
    if kind == MandatorySemanticKind.ACCESSIBILITY.value:
        return MobileSurfaceKind.STATUS

    role_hint = _node_role_hint(node)
    if role_hint == "form":
        return MobileSurfaceKind.FORM
    if role_hint == "list":
        return MobileSurfaceKind.LIST
    if role_hint == "navigation":
        return MobileSurfaceKind.NAVIGATION
    if kind == MandatorySemanticKind.ACTION.value:
        return MobileSurfaceKind.CARD
    return MobileSurfaceKind.CARD


def _interaction_state_for_node(node: ProjectedNode) -> InteractionState:
    kind = node.semantic_kind.lower()
    label = (node.label or node.item_id or "").lower()
    if kind in _CONFIRM_KINDS:
        return InteractionState.CONFIRMATION
    if kind in _ERROR_KINDS:
        return InteractionState.ERROR
    if any(hint in label for hint in _PENDING_HINTS) or kind == "pending":
        return InteractionState.PENDING
    if node.disposition is PresentationDisposition.UNSATISFIABLE:
        return InteractionState.UNAVAILABLE
    if node.disposition is PresentationDisposition.FALLBACK:
        return InteractionState.IDLE
    return InteractionState.IDLE


def _needs_virtual_keyboard(node: ProjectedNode) -> bool:
    role_hint = _node_role_hint(node)
    if role_hint == "form":
        return True
    kind = node.semantic_kind.lower()
    label = (node.label or "").lower()
    return kind in {"input", "text", "textbox"} or any(
        token in label for token in ("input", "text", "search", "password", "email")
    )


@dataclass(frozen=True, slots=True)
class TouchTargetSpec:
    """Explicit touch-target contract for one interactive control."""

    target_id: str
    min_width_dp: int = MIN_TOUCH_TARGET_DP
    min_height_dp: int = MIN_TOUCH_TARGET_DP
    min_spacing_dp: int = MIN_TOUCH_SPACING_DP
    interactive: bool = True

    def validate(self) -> None:
        _validate_identifier("TouchTargetSpec.target_id", self.target_id)
        for name in ("min_width_dp", "min_height_dp", "min_spacing_dp"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise UIIRValidationError(
                    f"TouchTargetSpec.{name} must be a non-negative integer"
                )
        if self.interactive and (
            self.min_width_dp < MIN_TOUCH_TARGET_DP
            or self.min_height_dp < MIN_TOUCH_TARGET_DP
        ):
            raise UIIRValidationError(
                f"TouchTargetSpec {self.target_id!r} interactive target must be "
                f"at least {MIN_TOUCH_TARGET_DP}dp"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interactive": self.interactive,
            "min_height_dp": self.min_height_dp,
            "min_spacing_dp": self.min_spacing_dp,
            "min_width_dp": self.min_width_dp,
            "target_id": self.target_id,
        }


@dataclass(frozen=True, slots=True)
class SafeAreaInsets:
    """Safe-area inset contract (density-independent pixels)."""

    top_dp: int = 0
    right_dp: int = 0
    bottom_dp: int = 0
    left_dp: int = 0
    respect_notch: bool = True
    respect_home_indicator: bool = True

    def validate(self) -> None:
        for name in ("top_dp", "right_dp", "bottom_dp", "left_dp"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise UIIRValidationError(
                    f"SafeAreaInsets.{name} must be a non-negative integer"
                )
        for name in ("respect_notch", "respect_home_indicator"):
            if not isinstance(getattr(self, name), bool):
                raise UIIRValidationError(f"SafeAreaInsets.{name} must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "bottom_dp": self.bottom_dp,
            "left_dp": self.left_dp,
            "respect_home_indicator": self.respect_home_indicator,
            "respect_notch": self.respect_notch,
            "right_dp": self.right_dp,
            "top_dp": self.top_dp,
        }


@dataclass(frozen=True, slots=True)
class VirtualKeyboardPolicy:
    """Virtual keyboard avoidance and input-mode contract."""

    avoid_occlusion: bool = True
    scroll_focused_into_view: bool = True
    dismiss_on_submit: bool = True
    input_mode: str = "default"
    required_for_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        for name in (
            "avoid_occlusion",
            "scroll_focused_into_view",
            "dismiss_on_submit",
        ):
            if not isinstance(getattr(self, name), bool):
                raise UIIRValidationError(
                    f"VirtualKeyboardPolicy.{name} must be a boolean"
                )
        if not isinstance(self.input_mode, str) or not self.input_mode.strip():
            raise UIIRValidationError(
                "VirtualKeyboardPolicy.input_mode must be a non-empty string"
            )
        _require_tuple(
            "VirtualKeyboardPolicy.required_for_ids", self.required_for_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "avoid_occlusion": self.avoid_occlusion,
            "dismiss_on_submit": self.dismiss_on_submit,
            "input_mode": self.input_mode,
            "required_for_ids": list(self.required_for_ids),
            "scroll_focused_into_view": self.scroll_focused_into_view,
        }


@dataclass(frozen=True, slots=True)
class ScreenReaderOrderEntry:
    """One screen-reader traversal entry independent of visual order."""

    order: int
    node_id: str
    accessible_name: str
    role: str = "none"
    live_region: str = ""
    importance: int = 0

    def validate(self) -> None:
        if not isinstance(self.order, int) or self.order < 0:
            raise UIIRValidationError(
                "ScreenReaderOrderEntry.order must be a non-negative integer"
            )
        _validate_identifier("ScreenReaderOrderEntry.node_id", self.node_id)
        if not isinstance(self.accessible_name, str) or not self.accessible_name.strip():
            raise UIIRValidationError(
                "ScreenReaderOrderEntry.accessible_name must be non-empty"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessible_name": self.accessible_name,
            "importance": self.importance,
            "live_region": self.live_region,
            "node_id": self.node_id,
            "order": self.order,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class FocusRestorationPlan:
    """Focus restoration plan after confirmation/modal/navigation."""

    strategy: FocusRestoreStrategy
    restore_target_id: str = ""
    announce_on_restore: bool = True
    trap_while_confirmation: bool = True

    def validate(self) -> None:
        if not isinstance(self.strategy, FocusRestoreStrategy):
            raise UIIRValidationError(
                "FocusRestorationPlan.strategy must be a FocusRestoreStrategy"
            )
        if not isinstance(self.restore_target_id, str):
            raise UIIRValidationError(
                "FocusRestorationPlan.restore_target_id must be a string"
            )
        for name in ("announce_on_restore", "trap_while_confirmation"):
            if not isinstance(getattr(self, name), bool):
                raise UIIRValidationError(
                    f"FocusRestorationPlan.{name} must be a boolean"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "announce_on_restore": self.announce_on_restore,
            "restore_target_id": self.restore_target_id,
            "strategy": self.strategy.value,
            "trap_while_confirmation": self.trap_while_confirmation,
        }


@dataclass(frozen=True, slots=True)
class GlassesFallbackContract:
    """Explicit glasses → mobile companion fallback contract.

    Policy authority remains with the projection solver / device profile;
    this only records that the companion is the selected fallback surface.
    """

    active: bool
    reason: GlassesFallbackReason
    source_profile_family: str = ""
    fallback_capability_id: str = "mobile_companion"
    glasses_node_ids: tuple[str, ...] = ()
    summary: str = ""

    def validate(self) -> None:
        if not isinstance(self.active, bool):
            raise UIIRValidationError(
                "GlassesFallbackContract.active must be a boolean"
            )
        if not isinstance(self.reason, GlassesFallbackReason):
            raise UIIRValidationError(
                "GlassesFallbackContract.reason must be a GlassesFallbackReason"
            )
        if self.active and self.reason is GlassesFallbackReason.NONE:
            raise UIIRValidationError(
                "GlassesFallbackContract active fallback requires a non-none reason"
            )
        if not isinstance(self.fallback_capability_id, str) or not self.fallback_capability_id:
            raise UIIRValidationError(
                "GlassesFallbackContract.fallback_capability_id must be non-empty"
            )
        _require_tuple(
            "GlassesFallbackContract.glasses_node_ids", self.glasses_node_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "fallback_capability_id": self.fallback_capability_id,
            "glasses_node_ids": list(self.glasses_node_ids),
            "reason": self.reason.value,
            "source_profile_family": self.source_profile_family,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class MobileSurfaceModel:
    """One mobile companion surface model (card/form/list/nav/confirm/fallback)."""

    surface_id: str
    kind: MobileSurfaceKind
    source_item_id: str
    semantic_kind: str
    disposition: str
    order: int
    title: str
    mandatory: bool = False
    body: str = ""
    interaction_state: InteractionState = InteractionState.IDLE
    component_id: str = ""
    action_ids: tuple[str, ...] = ()
    touch_target: TouchTargetSpec | None = None
    needs_virtual_keyboard: bool = False
    screen_reader_order: int = 0
    accessible_name: str = ""
    accessible_role: str = ""
    live_region: str = ""
    status_tone: str = "neutral"
    fallback_ref: str = ""
    lines: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _validate_identifier("MobileSurfaceModel.surface_id", self.surface_id)
        if not isinstance(self.kind, MobileSurfaceKind):
            raise UIIRValidationError(
                "MobileSurfaceModel.kind must be a MobileSurfaceKind"
            )
        _validate_identifier("MobileSurfaceModel.source_item_id", self.source_item_id)
        if not isinstance(self.semantic_kind, str) or not self.semantic_kind.strip():
            raise UIIRValidationError(
                "MobileSurfaceModel.semantic_kind must be non-empty"
            )
        if not isinstance(self.title, str) or not self.title.strip():
            raise UIIRValidationError("MobileSurfaceModel.title must be non-empty")
        if not isinstance(self.interaction_state, InteractionState):
            raise UIIRValidationError(
                "MobileSurfaceModel.interaction_state must be an InteractionState"
            )
        if self.touch_target is not None:
            self.touch_target.validate()
        _require_tuple("MobileSurfaceModel.action_ids", self.action_ids)
        _require_tuple("MobileSurfaceModel.lines", self.lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessible_name": self.accessible_name or self.title,
            "accessible_role": self.accessible_role,
            "action_ids": list(self.action_ids),
            "body": self.body,
            "component_id": self.component_id,
            "disposition": self.disposition,
            "fallback_ref": self.fallback_ref,
            "interaction_state": self.interaction_state.value,
            "kind": self.kind.value,
            "lines": list(self.lines),
            "live_region": self.live_region,
            "mandatory": self.mandatory,
            "metadata": dict(self.metadata),
            "needs_virtual_keyboard": self.needs_virtual_keyboard,
            "order": self.order,
            "screen_reader_order": self.screen_reader_order,
            "semantic_kind": self.semantic_kind,
            "source_item_id": self.source_item_id,
            "status_tone": self.status_tone,
            "surface_id": self.surface_id,
            "title": self.title,
            "touch_target": None
            if self.touch_target is None
            else self.touch_target.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class MobileViewportContract:
    """Viewport-level mobile constraints (touch, orientation, safe area, keyboard)."""

    orientation: OrientationPolicy = OrientationPolicy.PORTRAIT_PREFERRED
    safe_area: SafeAreaInsets = field(default_factory=SafeAreaInsets)
    virtual_keyboard: VirtualKeyboardPolicy = field(
        default_factory=VirtualKeyboardPolicy
    )
    min_touch_target_dp: int = MIN_TOUCH_TARGET_DP
    min_touch_spacing_dp: int = MIN_TOUCH_SPACING_DP
    max_content_width_dp: int = 480

    def validate(self) -> None:
        if not isinstance(self.orientation, OrientationPolicy):
            raise UIIRValidationError(
                "MobileViewportContract.orientation must be an OrientationPolicy"
            )
        self.safe_area.validate()
        self.virtual_keyboard.validate()
        if self.min_touch_target_dp < MIN_TOUCH_TARGET_DP:
            raise UIIRValidationError(
                f"min_touch_target_dp must be >= {MIN_TOUCH_TARGET_DP}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_content_width_dp": self.max_content_width_dp,
            "min_touch_spacing_dp": self.min_touch_spacing_dp,
            "min_touch_target_dp": self.min_touch_target_dp,
            "orientation": self.orientation.value,
            "safe_area": self.safe_area.to_dict(),
            "virtual_keyboard": self.virtual_keyboard.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class MobileProjectionArtifact:
    """Deterministic mobile companion projection result.

    Interface identity: ``UIIRMobileProjection@1``.
    """

    artifact_id: str
    surfaces: tuple[MobileSurfaceModel, ...]
    viewport: MobileViewportContract
    screen_reader_order: tuple[ScreenReaderOrderEntry, ...]
    focus_restoration: FocusRestorationPlan
    connectivity: ConnectivityState
    glasses_fallback: GlassesFallbackContract
    projection_artifact_id: str = ""
    projection_status: str = ""
    profile_id: str = ""
    document_id: str = ""
    loss_report: Mapping[str, Any] = field(default_factory=dict)
    policy_owner: str = "UIProjectionSolver@1"
    notes: tuple[str, ...] = ()
    schema_version: str = UIIR_MOBILE_PROJECTION_SCHEMA_VERSION
    interface: str = UIIR_MOBILE_PROJECTION_INTERFACE

    def validate(self) -> "MobileProjectionArtifact":
        _validate_identifier("MobileProjectionArtifact.artifact_id", self.artifact_id)
        if self.schema_version != UIIR_MOBILE_PROJECTION_SCHEMA_VERSION:
            raise UIIRValidationError(
                f"Unsupported mobile projection schema_version: "
                f"{self.schema_version!r}"
            )
        if self.interface != UIIR_MOBILE_PROJECTION_INTERFACE:
            raise UIIRValidationError(
                f"Unsupported mobile projection interface: {self.interface!r}"
            )
        if self.policy_owner != "UIProjectionSolver@1":
            raise UIIRValidationError(
                "Mobile projection must not become a separate policy owner; "
                "policy_owner must remain UIProjectionSolver@1"
            )
        _require_tuple("MobileProjectionArtifact.surfaces", self.surfaces)
        for surface in self.surfaces:
            if not isinstance(surface, MobileSurfaceModel):
                raise UIIRValidationError(
                    "surfaces members must be MobileSurfaceModel"
                )
            surface.validate()
        self.viewport.validate()
        _require_tuple(
            "MobileProjectionArtifact.screen_reader_order", self.screen_reader_order
        )
        for entry in self.screen_reader_order:
            entry.validate()
        self.focus_restoration.validate()
        if not isinstance(self.connectivity, ConnectivityState):
            raise UIIRValidationError(
                "connectivity must be a ConnectivityState"
            )
        self.glasses_fallback.validate()
        _require_tuple("MobileProjectionArtifact.notes", self.notes)
        return self

    def digest(self) -> str:
        text = json.dumps(
            self.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "connectivity": self.connectivity.value,
            "document_id": self.document_id,
            "focus_restoration": self.focus_restoration.to_dict(),
            "glasses_fallback": self.glasses_fallback.to_dict(),
            "interface": self.interface,
            "loss_report": dict(self.loss_report),
            "notes": list(self.notes),
            "policy_owner": self.policy_owner,
            "profile_id": self.profile_id,
            "projection_artifact_id": self.projection_artifact_id,
            "projection_status": self.projection_status,
            "schema_version": self.schema_version,
            "screen_reader_order": [
                entry.to_dict()
                for entry in sorted(self.screen_reader_order, key=lambda e: e.order)
            ],
            "surfaces": [
                surface.to_dict()
                for surface in sorted(self.surfaces, key=lambda s: (s.order, s.surface_id))
            ],
            "viewport": self.viewport.to_dict(),
        }

    def surfaces_by_kind(self, kind: MobileSurfaceKind | str) -> tuple[MobileSurfaceModel, ...]:
        kind_value = kind.value if isinstance(kind, MobileSurfaceKind) else str(kind)
        return tuple(s for s in self.surfaces if s.kind.value == kind_value)


@dataclass(frozen=True, slots=True)
class MobileProjectionOptions:
    """Presentation options for the mobile companion (not policy)."""

    orientation: OrientationPolicy = OrientationPolicy.PORTRAIT_PREFERRED
    safe_area: SafeAreaInsets = field(default_factory=SafeAreaInsets)
    connectivity: ConnectivityState = ConnectivityState.ONLINE
    glasses_fallback_reason: GlassesFallbackReason = GlassesFallbackReason.NONE
    source_profile_family: str = ProfileFamily.MOBILE.value
    max_content_width_dp: int = 480
    notes: tuple[str, ...] = ()

    def validate(self) -> "MobileProjectionOptions":
        if not isinstance(self.orientation, OrientationPolicy):
            raise UIIRValidationError(
                "orientation must be an OrientationPolicy"
            )
        self.safe_area.validate()
        if not isinstance(self.connectivity, ConnectivityState):
            raise UIIRValidationError(
                "connectivity must be a ConnectivityState"
            )
        if not isinstance(self.glasses_fallback_reason, GlassesFallbackReason):
            raise UIIRValidationError(
                "glasses_fallback_reason must be a GlassesFallbackReason"
            )
        return self


def _status_tone(state: InteractionState, kind: MobileSurfaceKind) -> str:
    if state is InteractionState.ERROR:
        return "danger"
    if state is InteractionState.CONFIRMATION:
        return "warning"
    if state is InteractionState.PENDING:
        return "active"
    if state is InteractionState.SUCCESS:
        return "success"
    if state in {InteractionState.OFFLINE, InteractionState.UNAVAILABLE}:
        return "neutral"
    if kind is MobileSurfaceKind.FALLBACK:
        return "neutral"
    return "neutral"


def _accessible_role(kind: MobileSurfaceKind, semantic_kind: str) -> str:
    if kind is MobileSurfaceKind.CONFIRMATION:
        return "dialog"
    if kind is MobileSurfaceKind.FORM:
        return "form"
    if kind is MobileSurfaceKind.LIST:
        return "list"
    if kind is MobileSurfaceKind.NAVIGATION:
        return "navigation"
    if kind is MobileSurfaceKind.STATUS:
        if semantic_kind == MandatorySemanticKind.ERROR.value:
            return "alert"
        return "status"
    if semantic_kind == MandatorySemanticKind.ACTION.value:
        return "button"
    return "summary"


def _live_region(state: InteractionState, semantic_kind: str) -> str:
    if state is InteractionState.ERROR or semantic_kind == MandatorySemanticKind.ERROR.value:
        return "assertive"
    if state is InteractionState.PENDING or semantic_kind == MandatorySemanticKind.FEEDBACK.value:
        return "polite"
    if state is InteractionState.CONFIRMATION:
        return "assertive"
    return ""


def _build_surface_from_node(
    node: ProjectedNode,
    *,
    order_index: int,
) -> MobileSurfaceModel:
    kind = _surface_for_node(node)
    interaction = _interaction_state_for_node(node)
    title = (node.label or node.component_id or node.item_id).strip() or node.item_id
    needs_keyboard = _needs_virtual_keyboard(node)
    interactive = (
        kind
        in {
            MobileSurfaceKind.CARD,
            MobileSurfaceKind.FORM,
            MobileSurfaceKind.CONFIRMATION,
            MobileSurfaceKind.NAVIGATION,
            MobileSurfaceKind.LIST,
        }
        and node.disposition
        not in {
            PresentationDisposition.OMITTED,
            PresentationDisposition.UNSATISFIABLE,
        }
    )
    touch = (
        TouchTargetSpec(target_id=f"touch:{node.item_id}")
        if interactive
        else TouchTargetSpec(
            target_id=f"touch:{node.item_id}",
            interactive=False,
            min_width_dp=0,
            min_height_dp=0,
        )
    )
    action_ids: tuple[str, ...] = ()
    if node.semantic_kind == MandatorySemanticKind.ACTION.value or kind in {
        MobileSurfaceKind.CARD,
        MobileSurfaceKind.CONFIRMATION,
    }:
        action_ids = (node.item_id,)

    lines: list[str] = []
    if node.fallback_ref:
        lines.append(f"fallback:{node.fallback_ref}")
    if node.disposition is not PresentationDisposition.PRESERVED:
        lines.append(f"disposition:{node.disposition.value}")
    if interaction is not InteractionState.IDLE:
        lines.append(f"state:{interaction.value}")

    body = ""
    if kind is MobileSurfaceKind.CONFIRMATION:
        body = f"Confirm: {title}"
    elif kind is MobileSurfaceKind.FALLBACK:
        body = f"Fallback surface for {title}"
    elif interaction is InteractionState.ERROR:
        body = f"Error: {title}"
    elif interaction is InteractionState.PENDING:
        body = f"Pending: {title}"

    return MobileSurfaceModel(
        surface_id=f"mobile:{node.item_id}",
        kind=kind,
        source_item_id=node.item_id,
        semantic_kind=node.semantic_kind,
        disposition=node.disposition.value,
        order=order_index,
        title=title,
        mandatory=node.mandatory,
        body=body,
        interaction_state=interaction,
        component_id=node.component_id,
        action_ids=action_ids,
        touch_target=touch,
        needs_virtual_keyboard=needs_keyboard,
        screen_reader_order=order_index,
        accessible_name=title,
        accessible_role=_accessible_role(kind, node.semantic_kind),
        live_region=_live_region(interaction, node.semantic_kind),
        status_tone=_status_tone(interaction, kind),
        fallback_ref=node.fallback_ref,
        lines=tuple(lines),
        metadata={
            "source_order": node.order,
            "component_id": node.component_id,
        },
    )


def _connectivity_from_status(
    status: ProjectionStatus,
    options: MobileProjectionOptions,
) -> ConnectivityState:
    if options.connectivity is not ConnectivityState.ONLINE:
        return options.connectivity
    if status is ProjectionStatus.UNSATISFIABLE:
        return ConnectivityState.UNAVAILABLE
    if status is ProjectionStatus.FALLBACK:
        return ConnectivityState.DEGRADED
    if status is ProjectionStatus.DEGRADED:
        return ConnectivityState.DEGRADED
    if status is ProjectionStatus.BOUND_EXCEEDED:
        return ConnectivityState.DEGRADED
    return ConnectivityState.ONLINE


def _glasses_fallback_contract(
    artifact: UIProjectionArtifact,
    options: MobileProjectionOptions,
) -> GlassesFallbackContract:
    reason = options.glasses_fallback_reason
    source_family = options.source_profile_family or ""
    glasses_node_ids = tuple(
        node.item_id
        for node in artifact.nodes
        if node.disposition is PresentationDisposition.FALLBACK
        and (
            "mobile_companion" in (node.fallback_ref or "")
            or node.fallback_ref.startswith("fallback:")
        )
    )

    # Infer glasses fallback when the source profile is glasses or reason set.
    if reason is GlassesFallbackReason.NONE:
        if source_family == ProfileFamily.GLASSES.value:
            reason = GlassesFallbackReason.GLASSES_POLICY_FALLBACK
        elif artifact.status is ProjectionStatus.FALLBACK and source_family in {
            ProfileFamily.GLASSES.value,
            "spatial",
        }:
            reason = GlassesFallbackReason.GLASSES_BUDGET
        elif any(
            "mobile_companion" in (node.fallback_ref or "")
            for node in artifact.nodes
        ):
            reason = GlassesFallbackReason.EXPLICIT_MOBILE_COMPANION

    active = reason is not GlassesFallbackReason.NONE
    summary = ""
    if active:
        summary = (
            f"Glasses content projected to mobile companion "
            f"({reason.value}); policy owner remains UIProjectionSolver@1"
        )

    return GlassesFallbackContract(
        active=active,
        reason=reason,
        source_profile_family=source_family,
        fallback_capability_id="mobile_companion",
        glasses_node_ids=glasses_node_ids,
        summary=summary,
    )


def _focus_plan(
    surfaces: Sequence[MobileSurfaceModel],
) -> FocusRestorationPlan:
    confirmations = [s for s in surfaces if s.kind is MobileSurfaceKind.CONFIRMATION]
    actions = [
        s
        for s in surfaces
        if s.kind is MobileSurfaceKind.CARD
        and s.semantic_kind == MandatorySemanticKind.ACTION.value
    ]
    if confirmations:
        restore = actions[0].surface_id if actions else ""
        return FocusRestorationPlan(
            strategy=(
                FocusRestoreStrategy.PREVIOUS_TARGET
                if restore
                else FocusRestoreStrategy.FIRST_ACTIONABLE
            ),
            restore_target_id=restore,
            announce_on_restore=True,
            trap_while_confirmation=True,
        )
    if actions:
        return FocusRestorationPlan(
            strategy=FocusRestoreStrategy.ENTRY_COMPONENT,
            restore_target_id=actions[0].surface_id,
            announce_on_restore=True,
            trap_while_confirmation=False,
        )
    return FocusRestorationPlan(
        strategy=FocusRestoreStrategy.ANNOUNCE_ONLY,
        restore_target_id="",
        announce_on_restore=True,
        trap_while_confirmation=False,
    )


def _screen_reader_entries(
    surfaces: Sequence[MobileSurfaceModel],
) -> tuple[ScreenReaderOrderEntry, ...]:
    # Priority: confirmation/error first, then mandatory actions, then rest by order.
    def sort_key(surface: MobileSurfaceModel) -> tuple[int, int, str]:
        if surface.kind is MobileSurfaceKind.CONFIRMATION:
            band = 0
        elif surface.interaction_state is InteractionState.ERROR:
            band = 1
        elif surface.mandatory:
            band = 2
        else:
            band = 3
        return (band, surface.order, surface.surface_id)

    ordered = sorted(surfaces, key=sort_key)
    entries: list[ScreenReaderOrderEntry] = []
    for index, surface in enumerate(ordered):
        entries.append(
            ScreenReaderOrderEntry(
                order=index,
                node_id=surface.surface_id,
                accessible_name=surface.accessible_name or surface.title,
                role=surface.accessible_role or "none",
                live_region=surface.live_region,
                importance=100 - index if surface.mandatory else max(0, 50 - index),
            )
        )
    return tuple(entries)


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

    device_profile = profile or mobile_profile()
    if not isinstance(device_profile, UIDeviceProfile):
        raise UIIRValidationError(
            "profile must be a UIDeviceProfile when solving for mobile"
        )

    if isinstance(source, ProjectionProblem):
        return project_ui_ir(source, device_profile, policy)

    # Mapping that already looks like a projection artifact.
    if isinstance(source, Mapping) and source.get("interface") == (
        "UIProjectionArtifact@1"
    ):
        raise UIIRValidationError(
            "raw UIProjectionArtifact mappings must be constructed as "
            "UIProjectionArtifact instances before mobile projection"
        )

    return project_ui_ir(source, device_profile, policy)


def project_to_mobile(
    source: UIProjectionArtifact
    | ProjectionProblem
    | UIIRDocument
    | Mapping[str, Any],
    *,
    profile: UIDeviceProfile | None = None,
    policy: ProjectionPolicy | None = None,
    options: MobileProjectionOptions | None = None,
) -> MobileProjectionArtifact:
    """Project a shared projection artifact (or document) to mobile companion models.

    Does **not** invent policy: when given a document/problem, delegates to
    :func:`project_ui_ir` with the reference mobile profile. Loss receipts and
    status are copied from the shared projection artifact.
    """

    opts = (options or MobileProjectionOptions()).validate()
    device_profile = profile or mobile_profile()
    artifact = _ensure_projection_artifact(source, profile=device_profile, policy=policy)

    # Reject using a non-mobile profile as if mobile owned a different policy.
    # Callers may still pass a custom profile with mobile family for testing.
    if (
        isinstance(device_profile, UIDeviceProfile)
        and device_profile.family not in {ProfileFamily.MOBILE, ProfileFamily.CUSTOM}
        and opts.glasses_fallback_reason is GlassesFallbackReason.NONE
        and opts.source_profile_family != ProfileFamily.GLASSES.value
    ):
        # Allow glasses source explicitly via options; otherwise require mobile family.
        if device_profile.family is ProfileFamily.GLASSES:
            opts = MobileProjectionOptions(
                orientation=opts.orientation,
                safe_area=opts.safe_area,
                connectivity=opts.connectivity,
                glasses_fallback_reason=GlassesFallbackReason.GLASSES_POLICY_FALLBACK,
                source_profile_family=ProfileFamily.GLASSES.value,
                max_content_width_dp=opts.max_content_width_dp,
                notes=opts.notes
                + (
                    "auto-marked glasses fallback; policy remains UIProjectionSolver@1",
                ),
            ).validate()
        else:
            # Still project presentation, but note that profile is non-mobile.
            opts = MobileProjectionOptions(
                orientation=opts.orientation,
                safe_area=opts.safe_area,
                connectivity=opts.connectivity,
                glasses_fallback_reason=opts.glasses_fallback_reason,
                source_profile_family=device_profile.family.value,
                max_content_width_dp=opts.max_content_width_dp,
                notes=opts.notes
                + (
                    f"source profile family {device_profile.family.value}; "
                    "mobile remains presentation-only",
                ),
            ).validate()

    # Build surfaces from projected nodes (presentation mapping only).
    surfaces: list[MobileSurfaceModel] = []
    keyboard_ids: list[str] = []
    sorted_nodes = sorted(artifact.nodes, key=lambda n: (n.order, n.item_id))
    for index, node in enumerate(sorted_nodes):
        surface = _build_surface_from_node(node, order_index=index)
        surfaces.append(surface)
        if surface.needs_virtual_keyboard:
            keyboard_ids.append(surface.surface_id)

    # Connectivity banner surface when offline/unavailable.
    connectivity = _connectivity_from_status(artifact.status, opts)
    if connectivity in {
        ConnectivityState.OFFLINE,
        ConnectivityState.UNAVAILABLE,
    }:
        banner_id = f"mobile:connectivity:{connectivity.value}"
        surfaces.append(
            MobileSurfaceModel(
                surface_id=banner_id,
                kind=MobileSurfaceKind.STATUS,
                source_item_id=f"connectivity:{connectivity.value}",
                semantic_kind="availability",
                disposition=PresentationDisposition.ADAPTED.value,
                order=len(surfaces),
                title=(
                    "Offline"
                    if connectivity is ConnectivityState.OFFLINE
                    else "Unavailable"
                ),
                mandatory=True,
                body=(
                    "Companion is offline; actions are deferred."
                    if connectivity is ConnectivityState.OFFLINE
                    else "Required mobile surface is unavailable."
                ),
                interaction_state=(
                    InteractionState.OFFLINE
                    if connectivity is ConnectivityState.OFFLINE
                    else InteractionState.UNAVAILABLE
                ),
                touch_target=TouchTargetSpec(
                    target_id=f"touch:{banner_id}",
                    interactive=False,
                    min_width_dp=0,
                    min_height_dp=0,
                ),
                screen_reader_order=0,
                accessible_name=(
                    "Offline" if connectivity is ConnectivityState.OFFLINE else "Unavailable"
                ),
                accessible_role="alert",
                live_region="assertive",
                status_tone="danger",
                lines=(f"connectivity:{connectivity.value}",),
                metadata={"connectivity": connectivity.value},
            )
        )

    screen_reader_order = _screen_reader_entries(surfaces)
    # Re-stamp screen_reader_order onto surfaces for explicit parity.
    order_by_id = {entry.node_id: entry.order for entry in screen_reader_order}
    surfaces = [
        MobileSurfaceModel(
            surface_id=s.surface_id,
            kind=s.kind,
            source_item_id=s.source_item_id,
            semantic_kind=s.semantic_kind,
            disposition=s.disposition,
            order=s.order,
            title=s.title,
            mandatory=s.mandatory,
            body=s.body,
            interaction_state=s.interaction_state,
            component_id=s.component_id,
            action_ids=s.action_ids,
            touch_target=s.touch_target,
            needs_virtual_keyboard=s.needs_virtual_keyboard,
            screen_reader_order=order_by_id.get(s.surface_id, s.screen_reader_order),
            accessible_name=s.accessible_name,
            accessible_role=s.accessible_role,
            live_region=s.live_region,
            status_tone=s.status_tone,
            fallback_ref=s.fallback_ref,
            lines=s.lines,
            metadata=s.metadata,
        )
        for s in surfaces
    ]

    focus = _focus_plan(surfaces)
    glasses = _glasses_fallback_contract(artifact, opts)

    viewport = MobileViewportContract(
        orientation=opts.orientation,
        safe_area=opts.safe_area,
        virtual_keyboard=VirtualKeyboardPolicy(
            avoid_occlusion=True,
            scroll_focused_into_view=True,
            dismiss_on_submit=True,
            input_mode="default",
            required_for_ids=tuple(keyboard_ids),
        ),
        min_touch_target_dp=MIN_TOUCH_TARGET_DP,
        min_touch_spacing_dp=MIN_TOUCH_SPACING_DP,
        max_content_width_dp=opts.max_content_width_dp,
    )

    loss_report: Mapping[str, Any] = {}
    if artifact.loss_report is not None:
        loss_report = artifact.loss_report.to_dict()

    notes = list(opts.notes)
    notes.append("mobile is presentation-only; policy_owner=UIProjectionSolver@1")
    if glasses.active:
        notes.append(f"glasses_fallback={glasses.reason.value}")

    result = MobileProjectionArtifact(
        artifact_id=f"mobile:{artifact.artifact_id}",
        surfaces=tuple(surfaces),
        viewport=viewport,
        screen_reader_order=screen_reader_order,
        focus_restoration=focus,
        connectivity=connectivity,
        glasses_fallback=glasses,
        projection_artifact_id=artifact.artifact_id,
        projection_status=artifact.status.value,
        profile_id=artifact.profile_id or device_profile.profile_id,
        document_id=artifact.document_id,
        loss_report=loss_report,
        policy_owner="UIProjectionSolver@1",
        notes=tuple(notes),
    )
    return result.validate()


class UIIRMobileProjection:
    """Reference mobile companion projection implementing UIIRMobileProjection@1."""

    interface: str = UIIR_MOBILE_PROJECTION_INTERFACE

    def project(
        self,
        source: UIProjectionArtifact
        | ProjectionProblem
        | UIIRDocument
        | Mapping[str, Any],
        *,
        profile: UIDeviceProfile | None = None,
        policy: ProjectionPolicy | None = None,
        options: MobileProjectionOptions | None = None,
    ) -> MobileProjectionArtifact:
        return project_to_mobile(
            source, profile=profile, policy=policy, options=options
        )


def mobile_projection_from_document(
    document: UIIRDocument | Mapping[str, Any],
    *,
    profile: UIDeviceProfile | None = None,
    policy: ProjectionPolicy | None = None,
    options: MobileProjectionOptions | None = None,
) -> MobileProjectionArtifact:
    """Convenience: document → shared solver (mobile profile) → mobile models."""

    return project_to_mobile(
        document, profile=profile or mobile_profile(), policy=policy, options=options
    )


__all__ = [
    "ConnectivityState",
    "FocusRestoreStrategy",
    "FocusRestorationPlan",
    "GlassesFallbackContract",
    "GlassesFallbackReason",
    "MIN_TOUCH_SPACING_DP",
    "MIN_TOUCH_TARGET_DP",
    "MobileProjectionArtifact",
    "MobileProjectionOptions",
    "MobileSurfaceKind",
    "MobileSurfaceModel",
    "MobileViewportContract",
    "OrientationPolicy",
    "SafeAreaInsets",
    "ScreenReaderOrderEntry",
    "TouchTargetSpec",
    "UIIRMobileProjection",
    "UIIR_MOBILE_ADAPTER_INTERFACE",
    "UIIR_MOBILE_PROJECTION_INTERFACE",
    "UIIR_MOBILE_PROJECTION_SCHEMA_VERSION",
    "VirtualKeyboardPolicy",
    "InteractionState",
    "mobile_projection_from_document",
    "project_to_mobile",
]
