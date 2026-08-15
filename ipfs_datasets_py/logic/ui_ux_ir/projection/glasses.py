"""Meta-glasses and spatial projection adapter (UIIRGlassesProjection@1).

Maps UI/UX IR projection problems onto bounded HUD cards, actions, status,
privacy indicators, audio summaries, and mobile companion fallbacks while
respecting current Meta DAT versus Web App capability paths.

Authoritative constraints (UIR-001 Meta capability matrix):

- Web Apps expose Neural Band/captouch as Arrow/Enter-style intents only.
- DAT is a distinct capability path; adapters must not collapse DAT and Web App.
- Continuous cursor, free-form touch, continuous text input, and raw EMG are
  never assumed.
- Mandatory semantics that do not fit spatial budgets fall back to mobile/audio
  or fail with an explicit loss receipt. Privacy indicators and confirmations
  always survive or are marked unsatisfiable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping, Sequence

from ..schema import AdaptationPolicy, UIIRDocument, UIIRValidationError
from .capabilities import (
    BudgetKind,
    ProfileBudget,
    ProfileFamily,
    UIDeviceProfile,
    glasses_profile,
    validate_device_profile,
)
from .loss import (
    LossCategory,
    MANDATORY_SEMANTIC_KINDS,
    MandatorySemanticKind,
    ProjectionLoss,
    ProjectionLossReport,
    assert_no_silent_mandatory_omission,
    build_loss_report,
    make_loss,
)
from .solver import (
    PresentationDisposition,
    ProjectionItem,
    ProjectionPolicy,
    ProjectionProblem,
    ProjectionStatus,
    UIProjectionArtifact,
    project_ui_ir,
    projection_problem_from_document,
    solve_projection,
)

UIIR_GLASSES_PROJECTION_INTERFACE: Final = "UIIRGlassesProjection@1"
UIIR_GLASSES_PROJECTION_SCHEMA_VERSION: Final = "ui-glasses-projection/v1"
UIIR_GLASSES_ADAPTER_INTERFACE: Final = "UIIRGlassesAdapter@1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

# Meta Web Apps Arrow/Enter surface for Neural Band and captouch.
ARROW_ENTER_TOKENS: Final[tuple[str, ...]] = (
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "Enter",
)

# Abstract intent tokens produced from Arrow/Enter (never raw EMG features).
ARROW_ENTER_INTENT_MAP: Final[Mapping[str, str]] = {
    "ArrowUp": "navigate_up",
    "ArrowDown": "navigate_down",
    "ArrowLeft": "navigate_left",
    "ArrowRight": "navigate_right",
    "Enter": "activate",
    # Lowercase aliases accepted at the adapter boundary.
    "arrowup": "navigate_up",
    "arrowdown": "navigate_down",
    "arrowleft": "navigate_left",
    "arrowright": "navigate_right",
    "enter": "activate",
    "up": "navigate_up",
    "down": "navigate_down",
    "left": "navigate_left",
    "right": "navigate_right",
    "select": "activate",
}

# Assumptions that glasses projection must never fabricate.
UNSUPPORTED_GLASSES_ASSUMPTIONS: Final[frozenset[str]] = frozenset(
    {
        "continuous_cursor",
        "freeform_touch",
        "continuous_text_input",
        "raw_emg",
        "raw_neural_stream",
        "full_touchscreen_pointer",
    }
)

# Semantic kinds that always retain a visible/audible surface or explicit fail.
_SURVIVAL_KINDS: Final[frozenset[str]] = frozenset(
    {
        MandatorySemanticKind.CONFIRMATION.value,
        MandatorySemanticKind.PRIVACY.value,
        MandatorySemanticKind.CONSENT.value,
        MandatorySemanticKind.CONSEQUENCE.value,
    }
)

# Default action/text/update/FOV budgets (aligned with glasses_profile soft limits).
DEFAULT_GLASSES_MAX_ACTIONS: Final = 4
DEFAULT_GLASSES_MAX_TEXT_CHARS: Final = 180
DEFAULT_GLASSES_MAX_UPDATE_HZ: Final = 10
DEFAULT_GLASSES_FOV_PERCENT: Final = 30


class GlassesCapabilityPath(str, Enum):
    """Distinct Meta capability paths (must not be collapsed)."""

    DAT = "dat"
    WEB_APP = "web_app"
    SIMULATOR = "simulator"


class GlassesSurfaceKind(str, Enum):
    """Bounded presentation surfaces on glasses or companion fallbacks."""

    HUD_CARD = "hud_card"
    ACTION = "action"
    STATUS = "status"
    CONFIRMATION = "confirmation"
    PRIVACY_INDICATOR = "privacy_indicator"
    AUDIO_SUMMARY = "audio_summary"
    MOBILE_FALLBACK = "mobile_fallback"
    NOTIFICATION = "notification"
    UNSATISFIABLE = "unsatisfiable"


class GlassesInputSource(str, Enum):
    """Normalized glasses input sources (no raw sensor streams)."""

    NEURAL_BAND = "neural_band"
    CAPTOUCH = "captouch"
    DPAD = "dpad"
    SPEECH = "speech"
    HAND_GESTURE = "hand_gesture"
    GAZE = "gaze"
    HEAD_POSE = "head_pose"
    MOBILE_ACTION = "mobile_action"


class GlassesRenderPath(str, Enum):
    """Render target path for the projection handoff."""

    DAT_NATIVE = "dat-native"
    DISPLAY_WEBAPP = "display-webapp"
    SIMULATOR = "simulator"
    MOBILE_CARD = "mobile-card"
    AUDIO_SUMMARY = "audio-summary"
    NOTIFICATION = "notification"


def _validate_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise UIIRValidationError(f"{name} is not a stable identifier")


def _validate_non_empty_string(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise UIIRValidationError(f"{name} must be a non-empty string")


def _require_tuple(name: str, value: Any) -> None:
    if not isinstance(value, tuple):
        raise UIIRValidationError(f"{name} must be an immutable tuple")


def _budget(
    kind: BudgetKind,
    limit: int,
    *,
    unit: str = "count",
    soft_limit: int | None = None,
) -> ProfileBudget:
    return ProfileBudget(kind=kind, limit=limit, unit=unit, soft_limit=soft_limit)


def glasses_web_app_profile(
    profile_id: str = "profile:glasses:web_app",
) -> UIDeviceProfile:
    """Web App capability path: Arrow/Enter Neural Band/captouch, spatial HUD.

    Does not claim camera, microphone, speaker, continuous cursor, free-form
    touch, continuous text input, or raw EMG.
    """

    return validate_device_profile(
        UIDeviceProfile(
            profile_id=profile_id,
            family=ProfileFamily.GLASSES,
            input_capability_ids=(
                "dpad_captouch",
                "neural_band_normalized",
                "speech",
            ),
            output_capability_ids=(
                "spatial_display",
                "audio",
                "speech_output",
                "mobile_companion",
                "notification",
                "fallback",
            ),
            budgets=(
                _budget(BudgetKind.ACTION_COUNT, DEFAULT_GLASSES_MAX_ACTIONS, soft_limit=3),
                _budget(BudgetKind.TEXT_DENSITY, DEFAULT_GLASSES_MAX_TEXT_CHARS, unit="chars"),
                _budget(BudgetKind.UPDATE_RATE, DEFAULT_GLASSES_MAX_UPDATE_HZ, unit="hz"),
                _budget(BudgetKind.LATENCY, 80, unit="ms"),
                _budget(BudgetKind.ATTENTION, 25, unit="points"),
                _budget(BudgetKind.FIELD_OF_VIEW, DEFAULT_GLASSES_FOV_PERCENT, unit="percent"),
                _budget(BudgetKind.SAFE_AREA, 70, unit="percent"),
                _budget(BudgetKind.MEMORY, 80, unit="nodes"),
            ),
            adaptation_policy=AdaptationPolicy.FALLBACK,
            max_solve_ms=80,
            max_solve_steps=5_000,
            max_memory_nodes=80,
            description=(
                "Meta Web App glasses path: Neural Band/captouch as Arrow/Enter "
                "intents; no camera/mic/raw-EMG claims"
            ),
        )
    )


def glasses_dat_profile(
    profile_id: str = "profile:glasses:dat",
) -> UIDeviceProfile:
    """DAT capability path: native spatial display plus embodied inputs.

    Distinct from Web App. Camera/mic remain adapter-local consented surfaces
    outside this profile's input claims (UIIR never admits raw streams).
    """

    return validate_device_profile(
        UIDeviceProfile(
            profile_id=profile_id,
            family=ProfileFamily.GLASSES,
            input_capability_ids=(
                "dpad_captouch",
                "neural_band_normalized",
                "gaze",
                "head_pose",
                "speech",
                "hand_gesture",
            ),
            output_capability_ids=(
                "spatial_display",
                "audio",
                "speech_output",
                "haptic",
                "mobile_companion",
                "notification",
                "fallback",
            ),
            budgets=(
                _budget(BudgetKind.ACTION_COUNT, DEFAULT_GLASSES_MAX_ACTIONS, soft_limit=3),
                _budget(BudgetKind.TEXT_DENSITY, DEFAULT_GLASSES_MAX_TEXT_CHARS, unit="chars"),
                _budget(BudgetKind.UPDATE_RATE, DEFAULT_GLASSES_MAX_UPDATE_HZ, unit="hz"),
                _budget(BudgetKind.LATENCY, 80, unit="ms"),
                _budget(BudgetKind.ATTENTION, 30, unit="points"),
                _budget(BudgetKind.FIELD_OF_VIEW, DEFAULT_GLASSES_FOV_PERCENT, unit="percent"),
                _budget(BudgetKind.SAFE_AREA, 70, unit="percent"),
                _budget(BudgetKind.MEMORY, 100, unit="nodes"),
            ),
            adaptation_policy=AdaptationPolicy.FALLBACK,
            max_solve_ms=80,
            max_solve_steps=5_000,
            max_memory_nodes=100,
            description=(
                "Meta DAT glasses path: native spatial display with normalized "
                "embodied inputs; distinct from Web App capability path"
            ),
        )
    )


def glasses_simulator_profile(
    profile_id: str = "profile:glasses:simulator",
) -> UIDeviceProfile:
    """Hardware-free simulator path used for replay and conformance."""

    base = glasses_web_app_profile(profile_id=profile_id)
    return validate_device_profile(
        UIDeviceProfile(
            profile_id=profile_id,
            family=ProfileFamily.GLASSES,
            input_capability_ids=base.input_capability_ids,
            output_capability_ids=base.output_capability_ids,
            budgets=base.budgets,
            adaptation_policy=AdaptationPolicy.FALLBACK,
            max_solve_ms=base.max_solve_ms,
            max_solve_steps=base.max_solve_steps,
            max_memory_nodes=base.max_memory_nodes,
            description="Hardware-free Meta glasses simulator projection path",
        )
    )


def profile_for_capability_path(path: GlassesCapabilityPath | str) -> UIDeviceProfile:
    """Resolve a capability path to its exclusive device profile."""

    if isinstance(path, str):
        try:
            path = GlassesCapabilityPath(path)
        except ValueError as exc:
            raise UIIRValidationError(
                f"Unknown glasses capability path: {path!r}"
            ) from exc
    if path is GlassesCapabilityPath.DAT:
        return glasses_dat_profile()
    if path is GlassesCapabilityPath.WEB_APP:
        return glasses_web_app_profile()
    if path is GlassesCapabilityPath.SIMULATOR:
        return glasses_simulator_profile()
    raise UIIRValidationError(f"Unsupported glasses capability path: {path!r}")


def render_path_for_capability_path(
    path: GlassesCapabilityPath | str,
) -> GlassesRenderPath:
    if isinstance(path, str):
        path = GlassesCapabilityPath(path)
    if path is GlassesCapabilityPath.DAT:
        return GlassesRenderPath.DAT_NATIVE
    if path is GlassesCapabilityPath.WEB_APP:
        return GlassesRenderPath.DISPLAY_WEBAPP
    return GlassesRenderPath.SIMULATOR


def normalize_arrow_enter_intent(token: str) -> str:
    """Map an Arrow/Enter-style token to an abstract intent (fail closed).

    Accepts canonical ``ArrowUp``/``Enter`` tokens and lowercase aliases used by
    captouch/D-pad adapters. Never accepts raw EMG samples or continuous streams.
    """

    if not isinstance(token, str) or not token.strip():
        raise UIIRValidationError(
            "Arrow/Enter intent token must be a non-empty string"
        )
    key = token.strip()
    intent = ARROW_ENTER_INTENT_MAP.get(key) or ARROW_ENTER_INTENT_MAP.get(key.lower())
    if intent is None:
        raise UIIRValidationError(
            f"Unsupported glasses intent token {token!r}; expected Arrow/Enter-style "
            f"normalized intents only (admitted: {', '.join(ARROW_ENTER_TOKENS)})"
        )
    return intent


def is_supported_arrow_enter_token(token: str) -> bool:
    if not isinstance(token, str):
        return False
    key = token.strip()
    return key in ARROW_ENTER_INTENT_MAP or key.lower() in ARROW_ENTER_INTENT_MAP


@dataclass(frozen=True, slots=True)
class GlassesInputBinding:
    """Normalized input binding for Neural Band/captouch/D-pad."""

    binding_id: str
    source: GlassesInputSource
    capability_id: str
    capability_path: GlassesCapabilityPath
    admitted_tokens: tuple[str, ...]
    intent_map: Mapping[str, str]
    raw_emg_allowed: bool = False
    continuous_cursor_allowed: bool = False
    freeform_touch_allowed: bool = False
    continuous_text_input_allowed: bool = False

    def validate(self) -> "GlassesInputBinding":
        _validate_identifier("GlassesInputBinding.binding_id", self.binding_id)
        if not isinstance(self.source, GlassesInputSource):
            raise UIIRValidationError(
                "GlassesInputBinding.source must be a GlassesInputSource"
            )
        _validate_non_empty_string(
            "GlassesInputBinding.capability_id", self.capability_id
        )
        if not isinstance(self.capability_path, GlassesCapabilityPath):
            raise UIIRValidationError(
                "GlassesInputBinding.capability_path must be a GlassesCapabilityPath"
            )
        _require_tuple("GlassesInputBinding.admitted_tokens", self.admitted_tokens)
        if not self.admitted_tokens:
            raise UIIRValidationError(
                "GlassesInputBinding.admitted_tokens must not be empty"
            )
        if self.raw_emg_allowed:
            raise UIIRValidationError(
                "GlassesInputBinding must never allow raw EMG"
            )
        if self.continuous_cursor_allowed:
            raise UIIRValidationError(
                "GlassesInputBinding must never allow continuous cursor"
            )
        if self.freeform_touch_allowed:
            raise UIIRValidationError(
                "GlassesInputBinding must never allow free-form touch"
            )
        if self.continuous_text_input_allowed:
            raise UIIRValidationError(
                "GlassesInputBinding must never allow continuous text input"
            )
        return self

    def resolve_intent(self, token: str) -> str:
        self.validate()
        if token not in self.admitted_tokens and token.lower() not in {
            t.lower() for t in self.admitted_tokens
        }:
            raise UIIRValidationError(
                f"Token {token!r} is not admitted on binding {self.binding_id}"
            )
        return normalize_arrow_enter_intent(token)

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_tokens": list(self.admitted_tokens),
            "binding_id": self.binding_id,
            "capability_id": self.capability_id,
            "capability_path": self.capability_path.value,
            "continuous_cursor_allowed": False,
            "continuous_text_input_allowed": False,
            "freeform_touch_allowed": False,
            "intent_map": {
                token: self.intent_map[token]
                for token in self.admitted_tokens
                if token in self.intent_map
            },
            "raw_emg_allowed": False,
            "source": self.source.value,
        }


def default_input_bindings(
    capability_path: GlassesCapabilityPath,
) -> tuple[GlassesInputBinding, ...]:
    """Arrow/Enter Neural Band + captouch/D-pad bindings for a capability path."""

    intent_map = {
        token: ARROW_ENTER_INTENT_MAP[token] for token in ARROW_ENTER_TOKENS
    }
    neural = GlassesInputBinding(
        binding_id=f"binding:{capability_path.value}:neural_band",
        source=GlassesInputSource.NEURAL_BAND,
        capability_id="neural_band_normalized",
        capability_path=capability_path,
        admitted_tokens=ARROW_ENTER_TOKENS,
        intent_map=intent_map,
    ).validate()
    captouch = GlassesInputBinding(
        binding_id=f"binding:{capability_path.value}:captouch",
        source=GlassesInputSource.CAPTOUCH,
        capability_id="dpad_captouch",
        capability_path=capability_path,
        admitted_tokens=ARROW_ENTER_TOKENS,
        intent_map=intent_map,
    ).validate()
    dpad = GlassesInputBinding(
        binding_id=f"binding:{capability_path.value}:dpad",
        source=GlassesInputSource.DPAD,
        capability_id="dpad_captouch",
        capability_path=capability_path,
        admitted_tokens=ARROW_ENTER_TOKENS,
        intent_map=intent_map,
    ).validate()
    return (neural, captouch, dpad)


@dataclass(frozen=True, slots=True)
class GlassesBudgetReceipt:
    """Measured action/text/update/FOV budget usage for a glasses projection."""

    action_count: int
    action_limit: int
    text_chars: int
    text_limit: int
    update_hz: int
    update_limit: int
    field_of_view_share: int
    field_of_view_limit: int
    exceeded: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_count": self.action_count,
            "action_limit": self.action_limit,
            "exceeded": list(self.exceeded),
            "field_of_view_limit": self.field_of_view_limit,
            "field_of_view_share": self.field_of_view_share,
            "text_chars": self.text_chars,
            "text_limit": self.text_limit,
            "update_hz": self.update_hz,
            "update_limit": self.update_limit,
        }


@dataclass(frozen=True, slots=True)
class GlassesCapabilityReceipt:
    """Exact capability path and unsupported-assumption receipt."""

    capability_path: GlassesCapabilityPath
    profile_id: str
    render_path: GlassesRenderPath
    input_capability_ids: tuple[str, ...]
    output_capability_ids: tuple[str, ...]
    unsupported_assumptions: tuple[str, ...]
    dat_webapp_collapsed: bool = False

    def validate(self) -> "GlassesCapabilityReceipt":
        if not isinstance(self.capability_path, GlassesCapabilityPath):
            raise UIIRValidationError(
                "GlassesCapabilityReceipt.capability_path must be GlassesCapabilityPath"
            )
        _validate_identifier("GlassesCapabilityReceipt.profile_id", self.profile_id)
        if self.dat_webapp_collapsed:
            raise UIIRValidationError(
                "DAT and Web App capability paths must not be collapsed"
            )
        forbidden = set(self.unsupported_assumptions) - UNSUPPORTED_GLASSES_ASSUMPTIONS
        # Allow listing the closed unsupported set only.
        if forbidden and not set(self.unsupported_assumptions) <= (
            UNSUPPORTED_GLASSES_ASSUMPTIONS
            | {"camera_raw_stream", "microphone_raw_stream"}
        ):
            # Extra explicit denials are fine; unknown positives are not.
            pass
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_path": self.capability_path.value,
            "dat_webapp_collapsed": False,
            "input_capability_ids": list(self.input_capability_ids),
            "output_capability_ids": list(self.output_capability_ids),
            "profile_id": self.profile_id,
            "render_path": self.render_path.value,
            "unsupported_assumptions": list(self.unsupported_assumptions),
        }


@dataclass(frozen=True, slots=True)
class GlassesPresentationNode:
    """One projected HUD/card/action/fallback surface node."""

    node_id: str
    surface: GlassesSurfaceKind
    semantic_id: str
    semantic_kind: str
    disposition: PresentationDisposition
    mandatory: bool
    order: int
    label: str = ""
    text: str = ""
    action_id: str = ""
    focus_index: int | None = None
    fallback_ref: str = ""
    component_id: str = ""

    def validate(self) -> None:
        _validate_identifier("GlassesPresentationNode.node_id", self.node_id)
        if not isinstance(self.surface, GlassesSurfaceKind):
            raise UIIRValidationError(
                "GlassesPresentationNode.surface must be a GlassesSurfaceKind"
            )
        _validate_identifier("GlassesPresentationNode.semantic_id", self.semantic_id)
        _validate_non_empty_string(
            "GlassesPresentationNode.semantic_kind", self.semantic_kind
        )
        if not isinstance(self.disposition, PresentationDisposition):
            raise UIIRValidationError(
                "GlassesPresentationNode.disposition must be a PresentationDisposition"
            )
        if not isinstance(self.mandatory, bool):
            raise UIIRValidationError(
                "GlassesPresentationNode.mandatory must be a boolean"
            )
        if not isinstance(self.order, int) or isinstance(self.order, bool) or self.order < 0:
            raise UIIRValidationError(
                "GlassesPresentationNode.order must be a non-negative integer"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "component_id": self.component_id,
            "disposition": self.disposition.value,
            "fallback_ref": self.fallback_ref,
            "focus_index": self.focus_index,
            "label": self.label,
            "mandatory": self.mandatory,
            "node_id": self.node_id,
            "order": self.order,
            "semantic_id": self.semantic_id,
            "semantic_kind": self.semantic_kind,
            "surface": self.surface.value,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class GlassesCompilerHandoff:
    """Inputs compatible with existing glasses display compiler/profile shapes."""

    template: str
    render_path: str
    max_actions: int
    max_text_chars: int
    max_update_hz: int
    focus_order: tuple[str, ...]
    actions: tuple[Mapping[str, Any], ...]
    regions: tuple[Mapping[str, Any], ...]
    fallbacks: tuple[Mapping[str, Any], ...]
    input_kinds: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [dict(item) for item in self.actions],
            "fallbacks": [dict(item) for item in self.fallbacks],
            "focus_order": list(self.focus_order),
            "input_kinds": list(self.input_kinds),
            "max_actions": self.max_actions,
            "max_text_chars": self.max_text_chars,
            "max_update_hz": self.max_update_hz,
            "regions": [dict(item) for item in self.regions],
            "render_path": self.render_path,
            "template": self.template,
        }


@dataclass(frozen=True, slots=True)
class UIIRGlassesProjection:
    """Deterministic Meta-glasses projection artifact.

    Interface identity: ``UIIRGlassesProjection@1``.
    """

    projection_id: str
    capability_path: GlassesCapabilityPath
    status: ProjectionStatus
    nodes: tuple[GlassesPresentationNode, ...]
    input_bindings: tuple[GlassesInputBinding, ...]
    loss_report: ProjectionLossReport
    budget_receipt: GlassesBudgetReceipt
    capability_receipt: GlassesCapabilityReceipt
    compiler_handoff: GlassesCompilerHandoff
    solver_artifact: UIProjectionArtifact | None = None
    document_id: str = ""
    profile_id: str = ""
    schema_version: str = UIIR_GLASSES_PROJECTION_SCHEMA_VERSION
    interface: str = UIIR_GLASSES_PROJECTION_INTERFACE

    def validate(self) -> "UIIRGlassesProjection":
        if self.schema_version != UIIR_GLASSES_PROJECTION_SCHEMA_VERSION:
            raise UIIRValidationError(
                f"Unsupported glasses projection schema_version: "
                f"{self.schema_version!r}"
            )
        if self.interface != UIIR_GLASSES_PROJECTION_INTERFACE:
            raise UIIRValidationError(
                f"Unexpected glasses projection interface: {self.interface!r}"
            )
        _validate_identifier("UIIRGlassesProjection.projection_id", self.projection_id)
        if not isinstance(self.capability_path, GlassesCapabilityPath):
            raise UIIRValidationError(
                "UIIRGlassesProjection.capability_path must be GlassesCapabilityPath"
            )
        if not isinstance(self.status, ProjectionStatus):
            raise UIIRValidationError(
                "UIIRGlassesProjection.status must be a ProjectionStatus"
            )
        _require_tuple("UIIRGlassesProjection.nodes", self.nodes)
        for node in self.nodes:
            if not isinstance(node, GlassesPresentationNode):
                raise UIIRValidationError(
                    "UIIRGlassesProjection.nodes members must be GlassesPresentationNode"
                )
            node.validate()
        _require_tuple("UIIRGlassesProjection.input_bindings", self.input_bindings)
        for binding in self.input_bindings:
            if not isinstance(binding, GlassesInputBinding):
                raise UIIRValidationError(
                    "input_bindings members must be GlassesInputBinding"
                )
            binding.validate()
        self.loss_report.validate()
        self.capability_receipt.validate()
        if self.capability_receipt.capability_path is not self.capability_path:
            raise UIIRValidationError(
                "capability_receipt.capability_path must match projection capability_path"
            )
        # Privacy indicators and confirmations must survive or be explicit.
        _assert_survival_semantics(self.nodes, self.loss_report)
        return self

    def digest(self) -> str:
        text = json.dumps(
            self.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_receipt": self.budget_receipt.to_dict(),
            "capability_path": self.capability_path.value,
            "capability_receipt": self.capability_receipt.to_dict(),
            "compiler_handoff": self.compiler_handoff.to_dict(),
            "document_id": self.document_id,
            "input_bindings": [
                binding.to_dict()
                for binding in sorted(
                    self.input_bindings, key=lambda b: b.binding_id
                )
            ],
            "interface": self.interface,
            "loss_report": self.loss_report.to_dict(),
            "nodes": [node.to_dict() for node in self.nodes],
            "profile_id": self.profile_id,
            "projection_id": self.projection_id,
            "schema_version": self.schema_version,
            "solver_artifact_id": (
                None
                if self.solver_artifact is None
                else self.solver_artifact.artifact_id
            ),
            "status": self.status.value,
        }


def _assert_survival_semantics(
    nodes: Sequence[GlassesPresentationNode],
    loss_report: ProjectionLossReport,
) -> None:
    """Confirmations and privacy must not be silently dropped."""

    present: dict[str, str] = {}
    for node in nodes:
        if node.semantic_kind in _SURVIVAL_KINDS:
            if node.surface is not GlassesSurfaceKind.UNSATISFIABLE:
                present[node.semantic_id] = node.semantic_kind
    for loss in loss_report.losses:
        if loss.semantic_kind in _SURVIVAL_KINDS:
            present.setdefault(loss.semantic_id, loss.semantic_kind)
    # If survival kinds appear only as omitted without policy, fail.
    for loss in loss_report.losses:
        if (
            loss.semantic_kind in _SURVIVAL_KINDS
            and loss.category is LossCategory.OMITTED
            and loss.adaptation_policy is not AdaptationPolicy.OMIT
        ):
            raise UIIRValidationError(
                f"Mandatory survival semantic {loss.semantic_id!r} "
                f"({loss.semantic_kind}) cannot be silently omitted on glasses"
            )


def _surface_for_item(
    item: ProjectionItem,
    disposition: PresentationDisposition,
) -> GlassesSurfaceKind:
    kind = item.semantic_kind
    if disposition is PresentationDisposition.UNSATISFIABLE:
        return GlassesSurfaceKind.UNSATISFIABLE
    if disposition is PresentationDisposition.FALLBACK:
        if item.fallback_ref.startswith("fallback:mobile") or (
            "mobile_companion" in item.fallback_capability_ids
        ):
            return GlassesSurfaceKind.MOBILE_FALLBACK
        if (
            item.fallback_ref.startswith("fallback:audio")
            or "audio" in item.fallback_capability_ids
            or "speech_output" in item.fallback_capability_ids
        ):
            return GlassesSurfaceKind.AUDIO_SUMMARY
        if "notification" in item.fallback_capability_ids:
            return GlassesSurfaceKind.NOTIFICATION
        return GlassesSurfaceKind.MOBILE_FALLBACK
    if kind == MandatorySemanticKind.CONFIRMATION.value:
        return GlassesSurfaceKind.CONFIRMATION
    if kind in {
        MandatorySemanticKind.PRIVACY.value,
        MandatorySemanticKind.CONSENT.value,
    }:
        return GlassesSurfaceKind.PRIVACY_INDICATOR
    if kind == MandatorySemanticKind.ACTION.value:
        return GlassesSurfaceKind.ACTION
    if kind in {
        MandatorySemanticKind.ERROR.value,
        MandatorySemanticKind.FEEDBACK.value,
        MandatorySemanticKind.CONSEQUENCE.value,
    }:
        return GlassesSurfaceKind.STATUS
    return GlassesSurfaceKind.HUD_CARD


def _truncate_text(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def _glasses_problem_from_items(
    items: Sequence[ProjectionItem],
    *,
    problem_id: str,
    document_id: str = "",
) -> ProjectionProblem:
    """Rewrite projection items to prefer spatial_display on glasses."""

    rewritten: list[ProjectionItem] = []
    for item in items:
        required = item.required_capability_ids
        # Prefer spatial_display as primary on glasses; keep display as alt.
        if "display" in required and "spatial_display" not in required:
            required = ("spatial_display",) + tuple(
                c for c in required if c != "display"
            )
            alternatives = tuple(
                dict.fromkeys(
                    ("display",) + item.alternative_capability_ids
                )
            )
        else:
            alternatives = item.alternative_capability_ids
        fallbacks = item.fallback_capability_ids
        if not fallbacks:
            fallbacks = ("mobile_companion", "audio", "speech_output", "notification")
        fallback_ref = item.fallback_ref
        if not fallback_ref and (
            item.mandatory or item.semantic_kind in MANDATORY_SEMANTIC_KINDS
        ):
            if "mobile_companion" in fallbacks:
                fallback_ref = f"fallback:mobile:{item.item_id}"
            else:
                fallback_ref = f"fallback:audio:{item.item_id}"
        rewritten.append(
            ProjectionItem(
                item_id=item.item_id,
                semantic_kind=item.semantic_kind,
                mandatory=item.mandatory
                or item.semantic_kind in MANDATORY_SEMANTIC_KINDS,
                required_capability_ids=required,
                alternative_capability_ids=alternatives,
                fallback_capability_ids=fallbacks,
                fallback_ref=fallback_ref,
                adaptation_policy=(
                    AdaptationPolicy.FALLBACK
                    if (
                        item.mandatory
                        or item.semantic_kind in MANDATORY_SEMANTIC_KINDS
                    )
                    and item.adaptation_policy is AdaptationPolicy.PRESERVE
                    else item.adaptation_policy
                ),
                action_cost=item.action_cost,
                text_chars=item.text_chars,
                update_rate=item.update_rate,
                latency_ms=item.latency_ms,
                attention_cost=item.attention_cost,
                field_of_view_share=item.field_of_view_share,
                safe_area_share=item.safe_area_share,
                memory_nodes=item.memory_nodes,
                priority=item.priority,
                component_id=item.component_id,
                label=item.label,
            )
        )
    return ProjectionProblem(
        problem_id=problem_id,
        items=tuple(rewritten),
        document_id=document_id,
    ).validate()


def _nodes_from_artifact(
    artifact: UIProjectionArtifact,
    problem: ProjectionProblem,
    *,
    text_limit: int,
) -> tuple[GlassesPresentationNode, ...]:
    items_by_id = {item.item_id: item for item in problem.items}
    nodes: list[GlassesPresentationNode] = []
    focus_counter = 0
    for projected in artifact.nodes:
        item = items_by_id.get(projected.item_id)
        if item is None:
            # Should not happen for solver outputs from this problem.
            continue
        surface = _surface_for_item(item, projected.disposition)
        label = projected.label or item.label or projected.item_id
        text = _truncate_text(label, text_limit)
        action_id = ""
        focus_index: int | None = None
        if surface is GlassesSurfaceKind.ACTION and projected.disposition not in {
            PresentationDisposition.OMITTED,
            PresentationDisposition.UNSATISFIABLE,
        }:
            action_id = projected.item_id
            focus_index = focus_counter
            focus_counter += 1
        nodes.append(
            GlassesPresentationNode(
                node_id=f"glasses:{projected.item_id}",
                surface=surface,
                semantic_id=projected.item_id,
                semantic_kind=projected.semantic_kind,
                disposition=projected.disposition,
                mandatory=projected.mandatory,
                order=projected.order,
                label=label,
                text=text,
                action_id=action_id,
                focus_index=focus_index,
                fallback_ref=projected.fallback_ref or item.fallback_ref,
                component_id=projected.component_id or item.component_id,
            )
        )
    return tuple(nodes)


def _budget_receipt_from_artifact(
    artifact: UIProjectionArtifact,
    profile: UIDeviceProfile,
) -> GlassesBudgetReceipt:
    usage = {u.kind: u for u in artifact.budget_usage}
    action = usage.get(BudgetKind.ACTION_COUNT.value)
    text = usage.get(BudgetKind.TEXT_DENSITY.value)
    update = usage.get(BudgetKind.UPDATE_RATE.value)
    fov = usage.get(BudgetKind.FIELD_OF_VIEW.value)
    action_limit = profile.budget_limit(BudgetKind.ACTION_COUNT) or DEFAULT_GLASSES_MAX_ACTIONS
    text_limit = profile.budget_limit(BudgetKind.TEXT_DENSITY) or DEFAULT_GLASSES_MAX_TEXT_CHARS
    update_limit = profile.budget_limit(BudgetKind.UPDATE_RATE) or DEFAULT_GLASSES_MAX_UPDATE_HZ
    fov_limit = profile.budget_limit(BudgetKind.FIELD_OF_VIEW) or DEFAULT_GLASSES_FOV_PERCENT
    exceeded = tuple(
        u.kind
        for u in artifact.budget_usage
        if u.exceeded
        and u.kind
        in {
            BudgetKind.ACTION_COUNT.value,
            BudgetKind.TEXT_DENSITY.value,
            BudgetKind.UPDATE_RATE.value,
            BudgetKind.FIELD_OF_VIEW.value,
        }
    )
    return GlassesBudgetReceipt(
        action_count=0 if action is None else action.used,
        action_limit=action_limit,
        text_chars=0 if text is None else text.used,
        text_limit=text_limit,
        update_hz=0 if update is None else update.used,
        update_limit=update_limit,
        field_of_view_share=0 if fov is None else fov.used,
        field_of_view_limit=fov_limit,
        exceeded=exceeded,
    )


def _compiler_handoff(
    *,
    nodes: Sequence[GlassesPresentationNode],
    capability_path: GlassesCapabilityPath,
    profile: UIDeviceProfile,
    budget: GlassesBudgetReceipt,
) -> GlassesCompilerHandoff:
    render = render_path_for_capability_path(capability_path)
    actions: list[dict[str, Any]] = []
    regions: list[dict[str, Any]] = []
    focus_order: list[str] = []
    fallbacks: list[dict[str, Any]] = []

    # Title/status region always present for HUD structure.
    regions.append(
        {
            "id": "title",
            "kind": "text",
            "text": {"value": "UI/UX IR Glasses Projection", "max_chars": 40, "max_lines": 1},
        }
    )

    for node in sorted(nodes, key=lambda n: n.order):
        if node.disposition in {
            PresentationDisposition.OMITTED,
            PresentationDisposition.UNSATISFIABLE,
        }:
            if node.disposition is PresentationDisposition.UNSATISFIABLE:
                fallbacks.append(
                    {
                        "when": ["unsatisfiable_mandatory"],
                        "render_path": "notification",
                        "message": f"Cannot present {node.semantic_id} on glasses",
                        "semantic_id": node.semantic_id,
                    }
                )
            continue
        if node.surface is GlassesSurfaceKind.ACTION:
            action_id = node.action_id or node.semantic_id
            actions.append(
                {
                    "id": action_id,
                    "method": action_id,
                    "backend_action_id": node.semantic_id,
                    "label": _truncate_text(node.label or action_id, 12),
                    "focusable": True,
                }
            )
            focus_order.append(action_id)
            regions.append(
                {
                    "id": f"action:{action_id}",
                    "kind": "action",
                    "action_id": action_id,
                    "text": {
                        "value": node.text,
                        "max_chars": min(40, budget.text_limit),
                        "max_lines": 1,
                    },
                }
            )
        elif node.surface is GlassesSurfaceKind.CONFIRMATION:
            regions.append(
                {
                    "id": f"confirm:{node.semantic_id}",
                    "kind": "status",
                    "text": {
                        "value": node.text or "Confirm",
                        "max_chars": min(80, budget.text_limit),
                        "max_lines": 2,
                    },
                    "visible_if": "confirmation_required",
                }
            )
        elif node.surface is GlassesSurfaceKind.PRIVACY_INDICATOR:
            regions.append(
                {
                    "id": f"privacy:{node.semantic_id}",
                    "kind": "status",
                    "text": {
                        "value": node.text or "Privacy",
                        "max_chars": min(60, budget.text_limit),
                        "max_lines": 1,
                    },
                    "visible_if": "privacy_active",
                }
            )
        elif node.surface is GlassesSurfaceKind.MOBILE_FALLBACK:
            fallbacks.append(
                {
                    "when": ["display_unsupported", "budget_exceeded"],
                    "render_path": "mobile-card",
                    "message": node.text or "Continue on phone",
                    "semantic_id": node.semantic_id,
                }
            )
        elif node.surface is GlassesSurfaceKind.AUDIO_SUMMARY:
            fallbacks.append(
                {
                    "when": ["display_unsupported"],
                    "render_path": "audio-summary",
                    "message": node.text or "Audio summary",
                    "semantic_id": node.semantic_id,
                }
            )
        else:
            regions.append(
                {
                    "id": f"region:{node.semantic_id}",
                    "kind": "status" if node.surface is GlassesSurfaceKind.STATUS else "text",
                    "text": {
                        "value": node.text,
                        "max_chars": min(80, budget.text_limit),
                        "max_lines": 2,
                    },
                }
            )

    if not fallbacks:
        fallbacks.append(
            {
                "when": ["dat_native_display_unavailable", "session_not_ready"],
                "render_path": "mobile-card",
                "message": "View on phone",
            }
        )

    template = "confirmation" if any(
        n.surface is GlassesSurfaceKind.CONFIRMATION for n in nodes
    ) else ("single-card" if len(actions) <= 1 else "stack")

    input_kinds: list[str] = ["dpad"]
    if capability_path is GlassesCapabilityPath.DAT:
        input_kinds.extend(["gesture", "voice", "mobile_action"])
    else:
        input_kinds.extend(["voice", "mobile_action"])

    max_actions = profile.budget_limit(BudgetKind.ACTION_COUNT) or DEFAULT_GLASSES_MAX_ACTIONS
    return GlassesCompilerHandoff(
        template=template,
        render_path=render.value,
        max_actions=max_actions,
        max_text_chars=budget.text_limit,
        max_update_hz=budget.update_limit,
        focus_order=tuple(focus_order[:max_actions]),
        actions=tuple(actions[:max_actions]),
        regions=tuple(regions),
        fallbacks=tuple(fallbacks),
        input_kinds=tuple(input_kinds),
    )


def project_to_glasses(
    source: UIIRDocument
    | Mapping[str, Any]
    | ProjectionProblem
    | UIProjectionArtifact,
    *,
    capability_path: GlassesCapabilityPath | str = GlassesCapabilityPath.WEB_APP,
    policy: ProjectionPolicy | None = None,
    projection_id: str = "",
) -> UIIRGlassesProjection:
    """Project UI/UX IR content onto a Meta-glasses spatial presentation.

    Returns a validated :class:`UIIRGlassesProjection` with capability-path
    receipts, Arrow/Enter input bindings, budget usage, loss receipts, and a
    compiler handoff for existing glasses display profiles.
    """

    if isinstance(capability_path, str):
        try:
            capability_path = GlassesCapabilityPath(capability_path)
        except ValueError as exc:
            raise UIIRValidationError(
                f"Unknown glasses capability path: {capability_path!r}"
            ) from exc

    profile = profile_for_capability_path(capability_path)
    policy = (policy or ProjectionPolicy(policy_id="policy:glasses:default")).validate()

    document_id = ""
    problem: ProjectionProblem
    artifact: UIProjectionArtifact

    if isinstance(source, UIProjectionArtifact):
        artifact = source.validate()
        # Rebuild a minimal problem from artifact nodes for surface mapping.
        items = tuple(
            ProjectionItem(
                item_id=node.item_id,
                semantic_kind=node.semantic_kind,
                mandatory=node.mandatory,
                required_capability_ids=("spatial_display",),
                fallback_capability_ids=("mobile_companion", "audio"),
                fallback_ref=node.fallback_ref or f"fallback:mobile:{node.item_id}",
                adaptation_policy=AdaptationPolicy.FALLBACK,
                label=node.label,
                component_id=node.component_id,
                action_cost=1 if node.semantic_kind == "action" else 0,
                text_chars=max(8, len(node.label or node.item_id)),
                field_of_view_share=6,
            )
            for node in artifact.nodes
        )
        if not items:
            raise UIIRValidationError(
                "UIProjectionArtifact has no nodes to project to glasses"
            )
        problem = ProjectionProblem(
            problem_id=artifact.problem_id or "problem:glasses:from-artifact",
            items=items,
            document_id=artifact.document_id,
        ).validate()
        document_id = artifact.document_id
        # Re-solve under the glasses path profile for path-specific budgets.
        problem = _glasses_problem_from_items(
            problem.items,
            problem_id=problem.problem_id,
            document_id=document_id,
        )
        artifact = solve_projection(problem, profile, policy)
    elif isinstance(source, ProjectionProblem):
        problem = _glasses_problem_from_items(
            source.validate().items,
            problem_id=source.problem_id,
            document_id=source.document_id,
        )
        document_id = problem.document_id
        artifact = solve_projection(problem, profile, policy)
    else:
        base = projection_problem_from_document(source)
        document_id = base.document_id
        problem = _glasses_problem_from_items(
            base.items,
            problem_id=base.problem_id or f"problem:glasses:{document_id or 'anon'}",
            document_id=document_id,
        )
        artifact = solve_projection(problem, profile, policy)

    text_limit = profile.budget_limit(BudgetKind.TEXT_DENSITY) or DEFAULT_GLASSES_MAX_TEXT_CHARS
    nodes = _nodes_from_artifact(artifact, problem, text_limit=text_limit)
    budget_receipt = _budget_receipt_from_artifact(artifact, profile)
    bindings = default_input_bindings(capability_path)
    render = render_path_for_capability_path(capability_path)

    # Augment loss report with unsupported-assumption and path receipts.
    extra_losses: list[ProjectionLoss] = list(artifact.loss_report.losses)
    for assumption in sorted(UNSUPPORTED_GLASSES_ASSUMPTIONS):
        extra_losses.append(
            make_loss(
                loss_id=f"loss:unsupported-assumption:{assumption}",
                semantic_id=f"assumption:{assumption}",
                semantic_kind="capability_assumption",
                category=LossCategory.UNSUPPORTED,
                reason=(
                    f"Glasses projection never fabricates {assumption}; "
                    f"path={capability_path.value}"
                ),
                mandatory=False,
                adaptation_policy=AdaptationPolicy.OMIT,
                details=(f"capability_path={capability_path.value}",),
            )
        )

    # Ensure survival semantics present in the problem are covered.
    required_survival = {
        item.item_id: item.semantic_kind
        for item in problem.items
        if item.semantic_kind in _SURVIVAL_KINDS
        or (
            item.mandatory
            and item.semantic_kind
            in {
                MandatorySemanticKind.CONFIRMATION.value,
                MandatorySemanticKind.PRIVACY.value,
                MandatorySemanticKind.CONSENT.value,
            }
        )
    }
    preserved_ids = {
        node.semantic_id
        for node in nodes
        if node.disposition
        in {
            PresentationDisposition.PRESERVED,
            PresentationDisposition.ADAPTED,
            PresentationDisposition.SUMMARIZED,
            PresentationDisposition.FALLBACK,
        }
    }
    assert_no_silent_mandatory_omission(
        required_survival,
        extra_losses,
        preserved_ids,
    )

    loss_report = build_loss_report(
        f"loss-report:glasses:{artifact.artifact_id}",
        extra_losses,
    )
    capability_receipt = GlassesCapabilityReceipt(
        capability_path=capability_path,
        profile_id=profile.profile_id,
        render_path=render,
        input_capability_ids=tuple(sorted(profile.input_capability_ids)),
        output_capability_ids=tuple(sorted(profile.output_capability_ids)),
        unsupported_assumptions=tuple(sorted(UNSUPPORTED_GLASSES_ASSUMPTIONS)),
        dat_webapp_collapsed=False,
    ).validate()
    handoff = _compiler_handoff(
        nodes=nodes,
        capability_path=capability_path,
        profile=profile,
        budget=budget_receipt,
    )

    proj_id = projection_id or f"glasses:{capability_path.value}:{artifact.artifact_id}"
    return UIIRGlassesProjection(
        projection_id=proj_id,
        capability_path=capability_path,
        status=artifact.status,
        nodes=nodes,
        input_bindings=bindings,
        loss_report=loss_report,
        budget_receipt=budget_receipt,
        capability_receipt=capability_receipt,
        compiler_handoff=handoff,
        solver_artifact=artifact,
        document_id=document_id,
        profile_id=profile.profile_id,
    ).validate()


class UIIRGlassesAdapter:
    """Reference glasses adapter implementing UIIRGlassesAdapter@1."""

    interface: str = UIIR_GLASSES_ADAPTER_INTERFACE

    def __init__(
        self,
        capability_path: GlassesCapabilityPath | str = GlassesCapabilityPath.WEB_APP,
    ) -> None:
        if isinstance(capability_path, str):
            capability_path = GlassesCapabilityPath(capability_path)
        self.capability_path = capability_path

    def project(
        self,
        source: UIIRDocument
        | Mapping[str, Any]
        | ProjectionProblem
        | UIProjectionArtifact,
        *,
        policy: ProjectionPolicy | None = None,
    ) -> UIIRGlassesProjection:
        return project_to_glasses(
            source,
            capability_path=self.capability_path,
            policy=policy,
        )

    def normalize_intent(self, token: str) -> str:
        return normalize_arrow_enter_intent(token)

    def profile(self) -> UIDeviceProfile:
        return profile_for_capability_path(self.capability_path)

    def input_bindings(self) -> tuple[GlassesInputBinding, ...]:
        return default_input_bindings(self.capability_path)


def reject_fabricated_capability_claims(payload: Mapping[str, Any]) -> None:
    """Fail closed if a payload fabricates forbidden glasses capabilities."""

    if not isinstance(payload, Mapping):
        raise UIIRValidationError("capability claim payload must be a mapping")
    lowered = {str(k).lower() for k in payload}
    values = {str(v).lower() for v in payload.values() if isinstance(v, str)}
    forbidden_hits = (lowered | values) & {
        "raw_emg",
        "emg_raw",
        "continuous_cursor",
        "freeform_touch",
        "continuous_text_input",
        "neural_band_raw",
        "raw_neural_stream",
    }
    if forbidden_hits:
        raise UIIRValidationError(
            "Fabricated glasses capability claims are forbidden: "
            + ", ".join(sorted(forbidden_hits))
        )
    if payload.get("dat_webapp_collapsed") is True:
        raise UIIRValidationError(
            "DAT and Web App capability paths must not be collapsed"
        )


__all__ = [
    "ARROW_ENTER_INTENT_MAP",
    "ARROW_ENTER_TOKENS",
    "DEFAULT_GLASSES_FOV_PERCENT",
    "DEFAULT_GLASSES_MAX_ACTIONS",
    "DEFAULT_GLASSES_MAX_TEXT_CHARS",
    "DEFAULT_GLASSES_MAX_UPDATE_HZ",
    "GlassesBudgetReceipt",
    "GlassesCapabilityPath",
    "GlassesCapabilityReceipt",
    "GlassesCompilerHandoff",
    "GlassesInputBinding",
    "GlassesInputSource",
    "GlassesPresentationNode",
    "GlassesRenderPath",
    "GlassesSurfaceKind",
    "UIIRGlassesAdapter",
    "UIIRGlassesProjection",
    "UIIR_GLASSES_ADAPTER_INTERFACE",
    "UIIR_GLASSES_PROJECTION_INTERFACE",
    "UIIR_GLASSES_PROJECTION_SCHEMA_VERSION",
    "UNSUPPORTED_GLASSES_ASSUMPTIONS",
    "default_input_bindings",
    "glasses_dat_profile",
    "glasses_profile",
    "glasses_simulator_profile",
    "glasses_web_app_profile",
    "is_supported_arrow_enter_token",
    "normalize_arrow_enter_intent",
    "profile_for_capability_path",
    "project_to_glasses",
    "project_ui_ir",
    "reject_fabricated_capability_claims",
    "render_path_for_capability_path",
]
