"""Hand, gaze, head, motion, and Neural Band/captouch normalization (UIR-052).

EmbodiedInputAdapter@1 and NeuralBandIntentAdapter@1 convert injected recognized
gestures, pose tokens, D-pad/captouch events, and Arrow/Enter-style Neural Band
intents into canonical interaction events.

Raw video frames, continuous gaze streams, biometrics, EMG samples, and vendor
SDK objects remain outside UIIR. Only normalized intent tokens, confidence,
calibration, consent/purpose, dwell/debounce metadata, perception-vs-intention
phase, and redacted evidence refs are admitted.

Never decides policy or authorization. High-risk activations require
confirmation; gaze requires dwell; duplicate activations within the debounce
window are suppressed. Unavailable hand/gaze/neural capabilities express
conventional/mobile fallbacks explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, MutableMapping, Sequence

from ...schema import UIIRValidationError
from ..events import (
    CanonicalInteractionEvent,
    EventKind,
    EventProvenance,
    validate_event,
)

EMBODIED_ADAPTER_ID: Final = "runtime.input.embodied@1"
EMBODIED_INPUT_ADAPTER_INTERFACE: Final = "EmbodiedInputAdapter@1"
NEURAL_BAND_ADAPTER_ID: Final = "runtime.input.neural_band@1"
NEURAL_BAND_INTENT_ADAPTER_INTERFACE: Final = "NeuralBandIntentAdapter@1"

# Canonical capability ids (must match modality.InputCapabilityKind values).
CAPABILITY_HAND_GESTURE: Final = "hand_gesture"
CAPABILITY_GAZE: Final = "gaze"
CAPABILITY_HEAD_POSE: Final = "head_pose"
CAPABILITY_MOTION: Final = "motion_orientation"
CAPABILITY_DPAD_CAPTOUCH: Final = "dpad_captouch"
CAPABILITY_NEURAL_BAND: Final = "neural_band_normalized"

EMBODIED_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        CAPABILITY_HAND_GESTURE,
        CAPABILITY_GAZE,
        CAPABILITY_HEAD_POSE,
        CAPABILITY_MOTION,
        CAPABILITY_DPAD_CAPTOUCH,
        CAPABILITY_NEURAL_BAND,
    }
)

# Default gates (ms / confidence).
DEFAULT_CONFIDENCE_THRESHOLD: Final = 0.6
DEFAULT_GAZE_DWELL_MS: Final = 500
DEFAULT_HIGH_RISK_GAZE_DWELL_MS: Final = 1_200
DEFAULT_DEBOUNCE_MS: Final = 350
DEFAULT_HIGH_RISK_DEBOUNCE_MS: Final = 800
DEFAULT_MAX_AGE_MS: Final = 30_000

_HIGH_RISK_CLASSES: Final = frozenset({"high", "destructive"})

# Conventional / mobile surfaces used when embodied capability is unavailable.
DEFAULT_FALLBACKS: Final[tuple[str, ...]] = (
    "pointer_mouse",
    "keyboard",
    "touchscreen",
    "mobile_companion",
)

# Source channel aliases → capability id.
_CHANNEL_TO_CAPABILITY: Final[Mapping[str, str]] = MappingProxyType(
    {
        "hand": CAPABILITY_HAND_GESTURE,
        "hand_gesture": CAPABILITY_HAND_GESTURE,
        "gesture": CAPABILITY_HAND_GESTURE,
        "gaze": CAPABILITY_GAZE,
        "eye": CAPABILITY_GAZE,
        "eye_gaze": CAPABILITY_GAZE,
        "head": CAPABILITY_HEAD_POSE,
        "head_pose": CAPABILITY_HEAD_POSE,
        "pose": CAPABILITY_HEAD_POSE,
        "motion": CAPABILITY_MOTION,
        "motion_orientation": CAPABILITY_MOTION,
        "orientation": CAPABILITY_MOTION,
        "imu": CAPABILITY_MOTION,
        "captouch": CAPABILITY_DPAD_CAPTOUCH,
        "dpad": CAPABILITY_DPAD_CAPTOUCH,
        "dpad_captouch": CAPABILITY_DPAD_CAPTOUCH,
        "touchpad": CAPABILITY_DPAD_CAPTOUCH,
        "neural": CAPABILITY_NEURAL_BAND,
        "neural_band": CAPABILITY_NEURAL_BAND,
        "neural_band_normalized": CAPABILITY_NEURAL_BAND,
        "meta_neural_band": CAPABILITY_NEURAL_BAND,
    }
)

# Raw sensor / EMG / visual stream surfaces — never part of UIIR.
_FORBIDDEN_RAW_SENSOR_KEYS: Final = frozenset(
    {
        "camera",
        "camera_frame",
        "camera_frames",
        "emg",
        "emg_raw",
        "emg_samples",
        "emg_signal",
        "frame",
        "frames",
        "gaze_stream",
        "image",
        "image_bytes",
        "image_data",
        "pixels",
        "raw_emg",
        "raw_frame",
        "raw_gaze",
        "raw_sensor",
        "raw_video",
        "rgb_frame",
        "sdk_handle",
        "sdk_object",
        "sensor_buffer",
        "vendor_sdk",
        "video",
        "video_frame",
        "visual_stream",
        "continuous_neural",
        "neural_band_raw",
        "neural_stream",
        "biometric",
        "biometrics",
    }
)

_FORBIDDEN_AUTHORITY_KEYS: Final = frozenset(
    {
        "authorization",
        "authority",
        "capability_token",
        "delegation",
        "grant",
        "grants",
        "password",
        "permission",
        "permissions",
        "private_key",
        "privilege",
        "privileges",
        "secret",
        "token",
        "ucan",
        "ucan_token",
    }
)

# Explicit intent tokens → canonical event kinds.
_INTENT_TO_KIND: Final[Mapping[str, EventKind]] = MappingProxyType(
    {
        "activate": EventKind.ACTIVATE,
        "blur": EventKind.BLUR,
        "cancel": EventKind.CANCEL,
        "confirm": EventKind.CONFIRM,
        "focus": EventKind.FOCUS,
        "hover": EventKind.HOVER,
        "input": EventKind.INPUT_VALUE,
        "input_value": EventKind.INPUT_VALUE,
        "navigate": EventKind.NAVIGATE,
        "scroll": EventKind.SCROLL,
        "select": EventKind.SELECT,
    }
)

# Recognized hand gesture tokens (normalized labels only, not raw joint data).
_HAND_GESTURE_TO_INTENT: Final[Mapping[str, str]] = MappingProxyType(
    {
        "air_tap": "activate",
        "click": "activate",
        "grab": "select",
        "open_palm": "cancel",
        "pinch": "activate",
        "point": "focus",
        "release": "blur",
        "swipe_down": "navigate",
        "swipe_left": "navigate",
        "swipe_right": "navigate",
        "swipe_up": "navigate",
        "tap": "activate",
        "thumbs_down": "cancel",
        "thumbs_up": "confirm",
    }
)

# Head pose discrete tokens.
_HEAD_POSE_TO_INTENT: Final[Mapping[str, str]] = MappingProxyType(
    {
        "look_down": "scroll",
        "look_left": "navigate",
        "look_right": "navigate",
        "look_up": "scroll",
        "nod": "confirm",
        "shake": "cancel",
        "tilt_left": "navigate",
        "tilt_right": "navigate",
    }
)

# Motion / orientation discrete tokens.
_MOTION_TO_INTENT: Final[Mapping[str, str]] = MappingProxyType(
    {
        "shake": "cancel",
        "tilt_down": "scroll",
        "tilt_left": "navigate",
        "tilt_right": "navigate",
        "tilt_up": "scroll",
        "wrist_raise": "focus",
    }
)

# Captouch / D-pad tokens and Meta Web Apps Arrow/Enter mapping.
_DPAD_TO_INTENT: Final[Mapping[str, str]] = MappingProxyType(
    {
        "arrowdown": "navigate",
        "arrowleft": "navigate",
        "arrowright": "navigate",
        "arrowup": "navigate",
        "down": "navigate",
        "enter": "activate",
        "left": "navigate",
        "right": "navigate",
        "select": "activate",
        "swipe_backward": "navigate",
        "swipe_down": "navigate",
        "swipe_forward": "navigate",
        "swipe_left": "navigate",
        "swipe_right": "navigate",
        "swipe_up": "navigate",
        "tap": "activate",
        "up": "navigate",
    }
)

# Neural Band only admits Arrow/Enter-style normalized intents (no EMG).
_NEURAL_BAND_TOKENS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "arrowdown": "navigate",
        "arrowleft": "navigate",
        "arrowright": "navigate",
        "arrowup": "navigate",
        "down": "navigate",
        "enter": "activate",
        "left": "navigate",
        "right": "navigate",
        "select": "activate",
        "up": "navigate",
    }
)

# Perception-only signals: presence / tracking without intentional activation.
_PERCEPTION_TOKENS: Final = frozenset(
    {
        "detected",
        "dwell_progress",
        "fixing",
        "gaze_enter",
        "gaze_exit",
        "gaze_move",
        "hand_visible",
        "hover",
        "looking_at",
        "present",
        "tracking",
        "visible",
    }
)


class EmbodiedPhase(str, Enum):
    """DCEC-aligned distinction: raw perception is not yet intention."""

    PERCEPTION = "perception"
    INTENTION = "intention"


class EmbodiedGateReason(str, Enum):
    """Why an embodied candidate is gated before mediation."""

    LOW_CONFIDENCE = "low_confidence"
    INSUFFICIENT_DWELL = "insufficient_dwell"
    DEBOUNCE_DUPLICATE = "debounce_duplicate"
    HIGH_RISK_CONFIRMATION = "high_risk_confirmation"
    GESTURE_AMBIGUITY = "gesture_ambiguity"
    PERCEPTION_ONLY = "perception_only"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    STALE_CANDIDATE = "stale_candidate"
    UNCALIBRATED = "uncalibrated"


class EmbodiedCapabilityStatus(str, Enum):
    """Runtime availability of an embodied sensing channel."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class EmbodiedGate:
    """Bounded gate / clarification request; never elevates sensors to authority."""

    reason: EmbodiedGateReason
    detail: str
    candidate_targets: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_targets": list(self.candidate_targets),
            "detail": self.detail,
            "reason": self.reason.value,
        }


@dataclass(frozen=True, slots=True)
class EmbodiedUnavailable:
    """Structured unavailable/unsupported capability with conventional fallbacks."""

    capability_id: str
    status: EmbodiedCapabilityStatus
    reason: str
    fallback_modalities: tuple[str, ...] = DEFAULT_FALLBACKS

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "fallback_modalities": list(self.fallback_modalities),
            "reason": self.reason,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class EmbodiedNormalizationResult:
    """Normalized embodied event plus phase, gates, and availability metadata."""

    event: CanonicalInteractionEvent | None
    phase: EmbodiedPhase
    requires_dwell: bool
    requires_confirmation: bool
    duplicate_suppressed: bool
    capability_id: str
    gates: tuple[EmbodiedGate, ...]
    unavailable: EmbodiedUnavailable | None = None
    purpose: str = ""
    calibrated: bool = True

    @property
    def requires_clarification(self) -> bool:
        return bool(self.gates) or self.requires_confirmation or self.requires_dwell

    @property
    def is_intention(self) -> bool:
        return self.phase is EmbodiedPhase.INTENTION and self.event is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibrated": self.calibrated,
            "capability_id": self.capability_id,
            "duplicate_suppressed": self.duplicate_suppressed,
            "event_id": None if self.event is None else self.event.event_id,
            "gates": [g.to_dict() for g in self.gates],
            "kind": None if self.event is None else self.event.kind.value,
            "phase": self.phase.value,
            "purpose": self.purpose,
            "requires_clarification": self.requires_clarification,
            "requires_confirmation": self.requires_confirmation,
            "requires_dwell": self.requires_dwell,
            "unavailable": None if self.unavailable is None else self.unavailable.to_dict(),
        }


@dataclass
class _DebounceState:
    """In-memory debounce ledger keyed by activation identity."""

    last_activation_ms: MutableMapping[str, int] = field(default_factory=dict)

    def activation_key(
        self,
        *,
        capability_id: str,
        target_component_id: str,
        intent: str,
        recognized_token: str,
    ) -> str:
        return f"{capability_id}|{target_component_id}|{intent}|{recognized_token}"

    def is_duplicate(
        self,
        key: str,
        *,
        timestamp_ms: int,
        debounce_ms: int,
    ) -> bool:
        previous = self.last_activation_ms.get(key)
        if previous is None:
            return False
        return 0 <= (timestamp_ms - previous) < debounce_ms

    def record(self, key: str, timestamp_ms: int) -> None:
        self.last_activation_ms[key] = timestamp_ms

    def clear(self) -> None:
        self.last_activation_ms.clear()


def _as_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise UIIRValidationError(f"embodied input {field_name} must be a boolean")


def _as_confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UIIRValidationError(
            "embodied input confidence must be a number in [0, 1]"
        )
    conf = float(value)
    if not 0.0 <= conf <= 1.0:
        raise UIIRValidationError(
            "embodied input confidence must be a number in [0, 1]"
        )
    return conf


def _reject_forbidden_keys(raw: Mapping[str, Any], *, path: str = "") -> None:
    lowered = {str(k).lower() for k in raw}
    sensors = lowered & _FORBIDDEN_RAW_SENSOR_KEYS
    if sensors:
        raise UIIRValidationError(
            "Raw EMG/visual sensor data remains outside UIIR; forbidden keys: "
            + ", ".join(sorted(sensors))
        )
    authority = lowered & _FORBIDDEN_AUTHORITY_KEYS
    if authority:
        raise UIIRValidationError(
            "Embodied payload must not carry authority/grant keys: "
            + ", ".join(sorted(authority))
        )
    for key, value in raw.items():
        if isinstance(value, Mapping):
            nested_path = f"{path}/{key}" if path else str(key)
            nested_lowered = {str(k).lower() for k in value}
            nested_sensors = nested_lowered & _FORBIDDEN_RAW_SENSOR_KEYS
            if nested_sensors:
                raise UIIRValidationError(
                    f"Raw EMG/visual sensor data remains outside UIIR under "
                    f"{nested_path!r}: " + ", ".join(sorted(nested_sensors))
                )
            nested_auth = nested_lowered & _FORBIDDEN_AUTHORITY_KEYS
            if nested_auth:
                raise UIIRValidationError(
                    f"Embodied payload under {nested_path!r} must not carry "
                    "authority keys: " + ", ".join(sorted(nested_auth))
                )
            _reject_forbidden_keys(value, path=nested_path)


def _parse_capability(raw: Mapping[str, Any]) -> str:
    explicit = (
        raw.get("capability_id")
        or raw.get("capability")
        or raw.get("source_capability")
    )
    if explicit is not None:
        cap = str(explicit).strip().lower()
        if cap in EMBODIED_CAPABILITIES:
            return cap
        # Allow channel aliases when callers pass them as capability.
        if cap in _CHANNEL_TO_CAPABILITY:
            return _CHANNEL_TO_CAPABILITY[cap]
        raise UIIRValidationError(
            f"Unsupported embodied capability {cap!r}; expected one of "
            + ", ".join(sorted(EMBODIED_CAPABILITIES))
        )

    channel = (
        raw.get("channel")
        or raw.get("source")
        or raw.get("modality")
        or raw.get("device")
        or raw.get("device_class")
    )
    if channel is None:
        raise UIIRValidationError(
            "embodied input requires capability_id or channel "
            "(hand/gaze/head/motion/captouch/neural_band)"
        )
    channel_s = str(channel).strip().lower()
    if channel_s not in _CHANNEL_TO_CAPABILITY:
        raise UIIRValidationError(
            f"Unsupported embodied channel {channel_s!r}; expected "
            "hand/gaze/head/motion/captouch/neural_band"
        )
    return _CHANNEL_TO_CAPABILITY[channel_s]


def _parse_capability_status(raw: Mapping[str, Any]) -> EmbodiedCapabilityStatus:
    status = raw.get("capability_status") or raw.get("status") or raw.get("availability")
    if status is None:
        # Boolean availability flags
        if "available" in raw:
            available = _as_bool(raw.get("available"), field_name="available")
            return (
                EmbodiedCapabilityStatus.AVAILABLE
                if available
                else EmbodiedCapabilityStatus.UNAVAILABLE
            )
        if "unsupported" in raw and raw.get("unsupported") is True:
            return EmbodiedCapabilityStatus.UNSUPPORTED
        return EmbodiedCapabilityStatus.AVAILABLE
    status_s = str(status).strip().lower()
    try:
        return EmbodiedCapabilityStatus(status_s)
    except ValueError as exc:
        raise UIIRValidationError(
            f"Unsupported capability_status {status_s!r}; expected "
            "available/unavailable/unsupported/denied"
        ) from exc


def _parse_fallbacks(raw: Mapping[str, Any]) -> tuple[str, ...]:
    items = raw.get("fallback_modalities") or raw.get("fallbacks") or DEFAULT_FALLBACKS
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        raise UIIRValidationError("fallback_modalities must be a sequence of strings")
    out: list[str] = []
    for item in items:
        s = str(item).strip()
        if s and s not in out:
            out.append(s)
    if not out:
        raise UIIRValidationError("fallback_modalities must not be empty")
    return tuple(out)


def _parse_risk_class(raw: Mapping[str, Any]) -> str:
    risk = raw.get("risk_class") or raw.get("risk") or "low"
    risk_s = str(risk).strip().lower()
    if risk_s not in {"low", "medium", "high", "destructive"}:
        raise UIIRValidationError(
            f"Unsupported embodied risk_class {risk_s!r}; "
            "expected low/medium/high/destructive"
        )
    return risk_s


def _parse_targets(
    raw: Mapping[str, Any],
    *,
    target_component_id: str | None,
) -> tuple[str, tuple[str, ...]]:
    candidates: list[str] = []
    multi = raw.get("target_component_ids")
    if multi is None:
        multi = raw.get("targets")
    if multi is None:
        multi = raw.get("target_ids")
    if multi is not None:
        if not isinstance(multi, Sequence) or isinstance(multi, (str, bytes, bytearray)):
            raise UIIRValidationError(
                "embodied target_component_ids must be a sequence of component ids"
            )
        for item in multi:
            tid = str(item).strip()
            if tid and tid not in candidates:
                candidates.append(tid)
    if not candidates:
        single = raw.get("target_component_id") or raw.get("target")
        if single is not None:
            tid = str(single).strip()
            if tid:
                candidates.append(tid)
    if target_component_id is not None:
        tid = str(target_component_id).strip()
        if tid:
            if tid in candidates:
                candidates.remove(tid)
            candidates.insert(0, tid)
    if not candidates:
        raise UIIRValidationError(
            "embodied input requires at least one target_component_id"
        )
    return candidates[0], tuple(candidates)


def _parse_recognized_token(raw: Mapping[str, Any], *, capability_id: str) -> str:
    token = (
        raw.get("recognized")
        or raw.get("gesture")
        or raw.get("token")
        or raw.get("intent_token")
        or raw.get("key")
        or raw.get("type")
        or raw.get("event_type")
        or raw.get("pose")
        or raw.get("action")
    )
    if token is None:
        # Gaze may use "dwell" as the intention token.
        if capability_id == CAPABILITY_GAZE and (
            "dwell_ms" in raw or raw.get("phase") == "intention"
        ):
            return "dwell"
        raise UIIRValidationError(
            "embodied input requires a recognized gesture/pose/token "
            "(no raw sensor streams)"
        )
    token_s = str(token).strip().lower().replace(" ", "_").replace("-", "_")
    if not token_s:
        raise UIIRValidationError("recognized token must be non-empty")
    return token_s


def _kind_for_intent(intent: str) -> EventKind:
    if intent in _INTENT_TO_KIND:
        return _INTENT_TO_KIND[intent]
    return EventKind.CUSTOM


def _resolve_intent_and_phase(
    raw: Mapping[str, Any],
    *,
    capability_id: str,
    recognized: str,
) -> tuple[str, EmbodiedPhase]:
    """Map recognized tokens to intent and perception vs intention phase."""

    explicit_phase = raw.get("phase") or raw.get("embodied_phase")
    phase_override: EmbodiedPhase | None = None
    if explicit_phase is not None:
        phase_s = str(explicit_phase).strip().lower()
        try:
            phase_override = EmbodiedPhase(phase_s)
        except ValueError as exc:
            raise UIIRValidationError(
                f"Unsupported embodied phase {phase_s!r}; expected "
                "perception or intention"
            ) from exc

    explicit_intent = raw.get("intent") or raw.get("intent_id") or raw.get(
        "semantic_intent"
    )
    if explicit_intent is not None:
        intent = str(explicit_intent).strip().lower()
        if not intent:
            raise UIIRValidationError("embodied intent must be non-empty when provided")
        if phase_override is not None:
            return intent, phase_override
        # Explicit intention tokens default to intention unless perception-only.
        if recognized in _PERCEPTION_TOKENS or intent in {
            "hover",
            "focus",
            "blur",
        }:
            if intent in {"hover", "focus", "blur"} and recognized in _PERCEPTION_TOKENS:
                return intent, EmbodiedPhase.PERCEPTION
            if recognized in _PERCEPTION_TOKENS:
                return intent, EmbodiedPhase.PERCEPTION
        return intent, phase_override or EmbodiedPhase.INTENTION

    # Perception-only recognition never promotes to activation.
    if recognized in _PERCEPTION_TOKENS:
        if recognized in {"gaze_exit", "blur"}:
            return "blur", phase_override or EmbodiedPhase.PERCEPTION
        if recognized in {"gaze_enter", "looking_at", "point", "focusing", "hand_visible"}:
            return "focus", phase_override or EmbodiedPhase.PERCEPTION
        return "hover", phase_override or EmbodiedPhase.PERCEPTION

    if capability_id == CAPABILITY_HAND_GESTURE:
        if recognized not in _HAND_GESTURE_TO_INTENT:
            raise UIIRValidationError(
                f"Unsupported hand gesture token {recognized!r}; "
                "only recognized normalized gesture labels are admitted"
            )
        return _HAND_GESTURE_TO_INTENT[recognized], phase_override or EmbodiedPhase.INTENTION

    if capability_id == CAPABILITY_GAZE:
        if recognized in {"dwell", "dwell_complete", "select", "activate", "click"}:
            return "activate", phase_override or EmbodiedPhase.INTENTION
        if recognized in {"confirm"}:
            return "confirm", phase_override or EmbodiedPhase.INTENTION
        if recognized in {"cancel"}:
            return "cancel", phase_override or EmbodiedPhase.INTENTION
        # Unknown gaze tokens stay perception until dwell completes.
        return "hover", phase_override or EmbodiedPhase.PERCEPTION

    if capability_id == CAPABILITY_HEAD_POSE:
        if recognized not in _HEAD_POSE_TO_INTENT:
            raise UIIRValidationError(
                f"Unsupported head pose token {recognized!r}; "
                "only discrete pose labels are admitted"
            )
        return _HEAD_POSE_TO_INTENT[recognized], phase_override or EmbodiedPhase.INTENTION

    if capability_id == CAPABILITY_MOTION:
        if recognized not in _MOTION_TO_INTENT:
            raise UIIRValidationError(
                f"Unsupported motion token {recognized!r}; "
                "only discrete motion labels are admitted"
            )
        return _MOTION_TO_INTENT[recognized], phase_override or EmbodiedPhase.INTENTION

    if capability_id == CAPABILITY_DPAD_CAPTOUCH:
        # Accept raw Arrow* casing variants already lowercased.
        if recognized not in _DPAD_TO_INTENT:
            raise UIIRValidationError(
                f"Unsupported captouch/D-pad token {recognized!r}; "
                "expected Arrow/Enter-style or swipe/tap intents"
            )
        return _DPAD_TO_INTENT[recognized], phase_override or EmbodiedPhase.INTENTION

    if capability_id == CAPABILITY_NEURAL_BAND:
        if recognized not in _NEURAL_BAND_TOKENS:
            raise UIIRValidationError(
                f"Unsupported Neural Band token {recognized!r}; only normalized "
                "Arrow/Enter-style intents are admitted (no raw EMG)"
            )
        return _NEURAL_BAND_TOKENS[recognized], phase_override or EmbodiedPhase.INTENTION

    raise UIIRValidationError(f"Unhandled embodied capability {capability_id!r}")


def _parse_dwell_ms(raw: Mapping[str, Any]) -> int | None:
    if "dwell_ms" not in raw and "dwell_time_ms" not in raw:
        return None
    value = raw.get("dwell_ms", raw.get("dwell_time_ms"))
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UIIRValidationError("dwell_ms must be a non-negative number")
    dwell = int(value)
    if dwell < 0:
        raise UIIRValidationError("dwell_ms must be a non-negative number")
    return dwell


def _required_dwell_ms(risk_class: str, *, configured: int | None) -> int:
    if configured is not None:
        return configured
    if risk_class in _HIGH_RISK_CLASSES:
        return DEFAULT_HIGH_RISK_GAZE_DWELL_MS
    return DEFAULT_GAZE_DWELL_MS


def _required_debounce_ms(risk_class: str, *, configured: int | None) -> int:
    if configured is not None:
        return configured
    if risk_class in _HIGH_RISK_CLASSES:
        return DEFAULT_HIGH_RISK_DEBOUNCE_MS
    return DEFAULT_DEBOUNCE_MS


def _parse_purpose_and_consent(
    raw: Mapping[str, Any],
    *,
    consent_ok: bool | None,
    capability_id: str,
) -> tuple[bool, str]:
    purpose = raw.get("purpose") or raw.get("consent_purpose")
    if not isinstance(purpose, str) or not purpose.strip():
        raise UIIRValidationError(
            "embodied input requires explicit purpose for sensing consent"
        )
    purpose_s = purpose.strip()

    if "consent" in raw:
        channel_consent = _as_bool(raw.get("consent"), field_name="consent")
    elif "sensing_consent" in raw:
        channel_consent = _as_bool(
            raw.get("sensing_consent"), field_name="sensing_consent"
        )
    else:
        # Neural Band and gaze always require an explicit consent flag.
        if capability_id in {CAPABILITY_NEURAL_BAND, CAPABILITY_GAZE, CAPABILITY_HAND_GESTURE}:
            raise UIIRValidationError(
                "embodied input requires explicit consent for "
                f"{capability_id} sensing"
            )
        channel_consent = True

    if not channel_consent:
        raise UIIRValidationError(
            f"embodied input missing consent for {capability_id} before mediation"
        )

    if consent_ok is None:
        final_ok = channel_consent
    else:
        if not isinstance(consent_ok, bool):
            raise UIIRValidationError("consent_ok must be a boolean")
        final_ok = consent_ok and channel_consent
    if not final_ok:
        raise UIIRValidationError(
            f"Event missing consent before mediation for {capability_id}"
        )
    return final_ok, purpose_s


def _parse_calibration(raw: Mapping[str, Any]) -> bool:
    if "calibrated" in raw:
        return _as_bool(raw.get("calibrated"), field_name="calibrated")
    if "calibration" in raw:
        cal = raw.get("calibration")
        if isinstance(cal, bool):
            return cal
        if isinstance(cal, Mapping):
            if "ok" in cal:
                return _as_bool(cal.get("ok"), field_name="calibration.ok")
            if "calibrated" in cal:
                return _as_bool(
                    cal.get("calibrated"), field_name="calibration.calibrated"
                )
        raise UIIRValidationError(
            "calibration must be a boolean or mapping with ok/calibrated"
        )
    # Default: assume calibrated for discrete D-pad / Neural Band tokens.
    return True


def _parse_evidence_ref(raw: Mapping[str, Any]) -> str | None:
    ref = (
        raw.get("evidence_ref")
        or raw.get("redacted_evidence_ref")
        or raw.get("gesture_evidence_ref")
    )
    if ref is None:
        return None
    if not isinstance(ref, str) or not ref.strip():
        raise UIIRValidationError("evidence_ref must be a non-empty string ref")
    ref_s = ref.strip()
    if ref_s.startswith("data:") or len(ref_s) > 512:
        raise UIIRValidationError(
            "evidence_ref must be a short opaque reference, not inline sensor data"
        )
    lowered = ref_s.lower()
    if any(
        tok in lowered
        for tok in ("base64,", "image/", "video/", "emg/", "application/octet")
    ):
        raise UIIRValidationError(
            "evidence_ref must not embed raw visual or EMG media types"
        )
    return ref_s


def _parse_alternatives(raw: Mapping[str, Any]) -> tuple[tuple[Mapping[str, Any], ...], bool]:
    items = raw.get("alternatives") or raw.get("gesture_alternatives") or ()
    if items is None:
        items = ()
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        raise UIIRValidationError("embodied alternatives must be a sequence")
    bounded: list[dict[str, Any]] = []
    for item in items[:8]:
        if not isinstance(item, Mapping):
            raise UIIRValidationError("each embodied alternative must be a mapping")
        token = item.get("recognized") or item.get("gesture") or item.get("token")
        if token is None:
            continue
        conf_raw = item.get("confidence", item.get("score", 0.0))
        conf = _as_confidence(conf_raw) if conf_raw is not None else 0.0
        bounded.append(
            {
                "confidence": conf,
                "recognized": str(token).strip().lower(),
            }
        )
    ambiguous = False
    if len(bounded) >= 2:
        scores = sorted((float(x["confidence"]) for x in bounded), reverse=True)
        if scores[0] > 0.0 and (scores[0] - scores[1]) < 0.15 and scores[1] >= 0.4:
            ambiguous = True
    return tuple(MappingProxyType(dict(x)) for x in bounded), ambiguous


def _direction_for_token(recognized: str) -> str | None:
    mapping = {
        "arrowup": "up",
        "up": "up",
        "arrowdown": "down",
        "down": "down",
        "arrowleft": "left",
        "left": "left",
        "arrowright": "right",
        "right": "right",
        "swipe_up": "up",
        "swipe_down": "down",
        "swipe_left": "left",
        "swipe_right": "right",
        "swipe_forward": "forward",
        "swipe_backward": "backward",
        "look_left": "left",
        "look_right": "right",
        "look_up": "up",
        "look_down": "down",
        "tilt_left": "left",
        "tilt_right": "right",
    }
    return mapping.get(recognized)


def normalize_embodied_input(
    raw: Mapping[str, Any],
    *,
    event_id: str,
    timestamp_ms: int,
    target_component_id: str | None = None,
    sequence: int = 0,
    provenance: EventProvenance = EventProvenance.HUMAN,
    consent_ok: bool | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    max_age_ms: int = DEFAULT_MAX_AGE_MS,
    dwell_threshold_ms: int | None = None,
    debounce_ms: int | None = None,
    debounce_state: _DebounceState | None = None,
    record_activation: bool = True,
) -> CanonicalInteractionEvent:
    """Map recognized embodied tokens to a canonical event.

    Never decides policy. Fails closed on raw EMG/visual data, missing consent,
    or unavailable capability without producing a fake activation. Perception
    events are admitted as hover/focus only. Intention activations honor dwell,
    debounce, and high-risk confirmation gates via payload flags.
    """

    result = normalize_embodied_input_detailed(
        raw,
        event_id=event_id,
        timestamp_ms=timestamp_ms,
        target_component_id=target_component_id,
        sequence=sequence,
        provenance=provenance,
        consent_ok=consent_ok,
        confidence_threshold=confidence_threshold,
        max_age_ms=max_age_ms,
        dwell_threshold_ms=dwell_threshold_ms,
        debounce_ms=debounce_ms,
        debounce_state=debounce_state,
        record_activation=record_activation,
    )
    if result.event is None:
        if result.unavailable is not None:
            raise UIIRValidationError(
                f"embodied capability {result.unavailable.capability_id!r} is "
                f"{result.unavailable.status.value}: {result.unavailable.reason}; "
                "fallback modalities: "
                + ", ".join(result.unavailable.fallback_modalities)
            )
        raise UIIRValidationError(
            "embodied normalization produced no event "
            f"(phase={result.phase.value}, gates="
            + ",".join(g.reason.value for g in result.gates)
            + ")"
        )
    return result.event


def normalize_embodied_input_detailed(
    raw: Mapping[str, Any],
    *,
    event_id: str,
    timestamp_ms: int,
    target_component_id: str | None = None,
    sequence: int = 0,
    provenance: EventProvenance = EventProvenance.HUMAN,
    consent_ok: bool | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    max_age_ms: int = DEFAULT_MAX_AGE_MS,
    dwell_threshold_ms: int | None = None,
    debounce_ms: int | None = None,
    debounce_state: _DebounceState | None = None,
    record_activation: bool = True,
) -> EmbodiedNormalizationResult:
    """Like :func:`normalize_embodied_input` with full gate/phase metadata."""

    if not isinstance(raw, Mapping):
        raise UIIRValidationError("embodied input raw must be a mapping")
    if not str(event_id).strip():
        raise UIIRValidationError("event_id must not be empty")
    if not (0.0 <= float(confidence_threshold) <= 1.0):
        raise UIIRValidationError("confidence_threshold must be in [0, 1]")
    if max_age_ms < 0:
        raise UIIRValidationError("max_age_ms must be non-negative")
    if timestamp_ms < 0:
        raise UIIRValidationError("timestamp_ms must be non-negative")

    _reject_forbidden_keys(raw)

    capability_id = _parse_capability(raw)
    status = _parse_capability_status(raw)
    fallbacks = _parse_fallbacks(raw)

    if status is not EmbodiedCapabilityStatus.AVAILABLE:
        unavailable = EmbodiedUnavailable(
            capability_id=capability_id,
            status=status,
            reason=str(
                raw.get("unavailable_reason")
                or raw.get("reason")
                or f"{capability_id} is {status.value}"
            ),
            fallback_modalities=fallbacks,
        )
        gate = EmbodiedGate(
            reason=EmbodiedGateReason.CAPABILITY_UNAVAILABLE,
            detail=(
                f"Capability {capability_id!r} is {status.value}; "
                "use conventional/mobile fallback modalities"
            ),
        )
        return EmbodiedNormalizationResult(
            event=None,
            phase=EmbodiedPhase.PERCEPTION,
            requires_dwell=False,
            requires_confirmation=False,
            duplicate_suppressed=False,
            capability_id=capability_id,
            gates=(gate,),
            unavailable=unavailable,
            purpose=str(raw.get("purpose") or "").strip(),
            calibrated=False,
        )

    final_consent, purpose_s = _parse_purpose_and_consent(
        raw, consent_ok=consent_ok, capability_id=capability_id
    )
    calibrated = _parse_calibration(raw)
    risk_class = _parse_risk_class(raw)
    primary_target, all_targets = _parse_targets(
        raw, target_component_id=target_component_id
    )
    recognized = _parse_recognized_token(raw, capability_id=capability_id)
    intent, phase = _resolve_intent_and_phase(
        raw, capability_id=capability_id, recognized=recognized
    )
    kind = _kind_for_intent(intent)

    conf_raw = raw.get("confidence", raw.get("score"))
    if conf_raw is None:
        # Discrete D-pad / Neural Band Arrow tokens may omit confidence.
        if capability_id in {CAPABILITY_DPAD_CAPTOUCH, CAPABILITY_NEURAL_BAND}:
            confidence = 1.0
        else:
            raise UIIRValidationError(
                "embodied input requires calibrated confidence in [0, 1] "
                f"for {capability_id}"
            )
    else:
        confidence = _as_confidence(conf_raw)

    age_ms = raw.get("age_ms", raw.get("freshness_age_ms"))
    if age_ms is None:
        age_ms = 0
    if isinstance(age_ms, bool) or not isinstance(age_ms, (int, float)):
        raise UIIRValidationError("embodied age_ms must be a non-negative number")
    age_ms_i = int(age_ms)
    if age_ms_i < 0:
        raise UIIRValidationError("embodied age_ms must be a non-negative number")
    if age_ms_i > max_age_ms:
        raise UIIRValidationError(
            f"embodied candidate is stale (age_ms={age_ms_i} > max_age_ms={max_age_ms})"
        )

    alternatives, ambiguous = _parse_alternatives(raw)
    evidence_ref = _parse_evidence_ref(raw)
    dwell_ms = _parse_dwell_ms(raw)
    need_dwell_ms = _required_dwell_ms(risk_class, configured=dwell_threshold_ms)
    need_debounce_ms = _required_debounce_ms(risk_class, configured=debounce_ms)

    gates: list[EmbodiedGate] = []
    requires_dwell = False
    requires_confirmation = False
    duplicate_suppressed = False

    # Gaze intention requires completed dwell appropriate to risk.
    if (
        capability_id == CAPABILITY_GAZE
        and phase is EmbodiedPhase.INTENTION
        and kind in {EventKind.ACTIVATE, EventKind.CONFIRM, EventKind.SELECT}
    ):
        if dwell_ms is None:
            requires_dwell = True
            gates.append(
                EmbodiedGate(
                    reason=EmbodiedGateReason.INSUFFICIENT_DWELL,
                    detail=(
                        f"Gaze activation requires dwell_ms >= {need_dwell_ms} "
                        f"for risk_class={risk_class}"
                    ),
                    candidate_targets=all_targets,
                )
            )
        elif dwell_ms < need_dwell_ms:
            requires_dwell = True
            # Incomplete dwell is still perception, not intention.
            phase = EmbodiedPhase.PERCEPTION
            kind = EventKind.HOVER
            intent = "hover"
            gates.append(
                EmbodiedGate(
                    reason=EmbodiedGateReason.INSUFFICIENT_DWELL,
                    detail=(
                        f"Gaze dwell_ms={dwell_ms} is below required "
                        f"{need_dwell_ms} for risk_class={risk_class}"
                    ),
                    candidate_targets=all_targets,
                )
            )

    if phase is EmbodiedPhase.PERCEPTION:
        # Perception never claims activation intention.
        if kind in {EventKind.ACTIVATE, EventKind.CONFIRM, EventKind.SELECT}:
            kind = EventKind.HOVER
            intent = "hover"
        gates.append(
            EmbodiedGate(
                reason=EmbodiedGateReason.PERCEPTION_ONLY,
                detail=(
                    "Signal is perception (presence/tracking/hover), not intention; "
                    "downstream must not treat it as a committed action"
                ),
                candidate_targets=all_targets,
            )
        )

    if not calibrated and phase is EmbodiedPhase.INTENTION:
        gates.append(
            EmbodiedGate(
                reason=EmbodiedGateReason.UNCALIBRATED,
                detail="Embodied channel is uncalibrated; intention requires re-calibration",
                candidate_targets=all_targets,
            )
        )

    if confidence < float(confidence_threshold) and phase is EmbodiedPhase.INTENTION:
        gates.append(
            EmbodiedGate(
                reason=EmbodiedGateReason.LOW_CONFIDENCE,
                detail=(
                    f"Recognized confidence {confidence} is below clarification "
                    f"threshold {float(confidence_threshold)}"
                ),
                candidate_targets=all_targets,
            )
        )

    if ambiguous and phase is EmbodiedPhase.INTENTION:
        gates.append(
            EmbodiedGate(
                reason=EmbodiedGateReason.GESTURE_AMBIGUITY,
                detail="Competing gesture alternatives require clarification",
                candidate_targets=all_targets,
            )
        )

    # High-risk intention activations require confirmation (do not auto-commit).
    if (
        phase is EmbodiedPhase.INTENTION
        and risk_class in _HIGH_RISK_CLASSES
        and kind in {EventKind.ACTIVATE, EventKind.SELECT, EventKind.CONFIRM}
        and intent != "cancel"
    ):
        # Cancel is always allowed as a safety action without extra confirmation.
        if kind is not EventKind.CANCEL:
            requires_confirmation = True
            gates.append(
                EmbodiedGate(
                    reason=EmbodiedGateReason.HIGH_RISK_CONFIRMATION,
                    detail=(
                        f"High-risk embodied action ({risk_class}) requires "
                        "explicit confirmation before mediation commits"
                    ),
                    candidate_targets=all_targets,
                )
            )

    # Debounce: suppress accidental duplicate activations.
    activation_kinds = {
        EventKind.ACTIVATE,
        EventKind.CONFIRM,
        EventKind.SELECT,
        EventKind.NAVIGATE,
        EventKind.CANCEL,
    }
    if (
        phase is EmbodiedPhase.INTENTION
        and kind in activation_kinds
        and debounce_state is not None
    ):
        key = debounce_state.activation_key(
            capability_id=capability_id,
            target_component_id=primary_target,
            intent=intent,
            recognized_token=recognized,
        )
        if debounce_state.is_duplicate(
            key, timestamp_ms=timestamp_ms, debounce_ms=need_debounce_ms
        ):
            duplicate_suppressed = True
            gates.append(
                EmbodiedGate(
                    reason=EmbodiedGateReason.DEBOUNCE_DUPLICATE,
                    detail=(
                        f"Duplicate activation suppressed within debounce window "
                        f"of {need_debounce_ms}ms"
                    ),
                    candidate_targets=all_targets,
                )
            )
        elif record_activation and not requires_dwell:
            # Only record committed-looking intentions (still may need confirm).
            debounce_state.record(key, timestamp_ms)

    direction = _direction_for_token(recognized)

    payload: dict[str, Any] = {
        "capability": capability_id,
        "capability_id": capability_id,
        "calibrated": calibrated,
        "duplicate_suppressed": duplicate_suppressed,
        "fallback_modalities": list(fallbacks),
        "freshness_age_ms": age_ms_i,
        "intent": intent,
        "normalized_intent_only": True,
        "phase": phase.value,
        "purpose": purpose_s,
        "raw_emg_retained": False,
        "raw_visual_retained": False,
        "recognized": recognized,
        "requires_confirmation": requires_confirmation,
        "requires_dwell": requires_dwell,
        "requires_clarification": bool(gates)
        or requires_confirmation
        or requires_dwell
        or duplicate_suppressed,
        "risk_class": risk_class,
        "sensing_consent": True,
        "target_candidates": list(all_targets),
    }
    if alternatives:
        payload["alternatives"] = [dict(a) for a in alternatives]
    if dwell_ms is not None:
        payload["dwell_ms"] = dwell_ms
        payload["dwell_threshold_ms"] = need_dwell_ms
    if direction is not None:
        payload["direction"] = direction
    if evidence_ref is not None:
        payload["evidence_ref"] = evidence_ref
    if gates:
        payload["gates"] = [g.to_dict() for g in gates]
    if capability_id == CAPABILITY_NEURAL_BAND:
        payload["neural_band_representation"] = "arrow_enter_normalized"
        payload["emg_access"] = False
    if capability_id == CAPABILITY_DPAD_CAPTOUCH:
        payload["dpad_mapping"] = "arrow_enter_style"

    # Suppressed duplicates still produce an observational receipt event so
    # fusion/mediator can see the suppression, but mark them non-activating.
    event_kind = kind
    if duplicate_suppressed:
        event_kind = EventKind.CUSTOM
        payload["activation_suppressed"] = True

    event = CanonicalInteractionEvent(
        event_id=str(event_id),
        kind=event_kind,
        target_component_id=primary_target,
        timestamp_ms=timestamp_ms,
        provenance=provenance,
        capability_id=capability_id,
        consent_ok=final_consent,
        sequence=sequence,
        confidence=confidence,
        raw_payload=MappingProxyType(payload),
        source_adapter=EMBODIED_ADAPTER_ID
        if capability_id != CAPABILITY_NEURAL_BAND
        else NEURAL_BAND_ADAPTER_ID,
    )
    validated = validate_event(event)
    return EmbodiedNormalizationResult(
        event=validated,
        phase=phase,
        requires_dwell=requires_dwell,
        requires_confirmation=requires_confirmation,
        duplicate_suppressed=duplicate_suppressed,
        capability_id=capability_id,
        gates=tuple(gates),
        unavailable=None,
        purpose=purpose_s,
        calibrated=calibrated,
    )


def normalize_neural_band_intent(
    raw: Mapping[str, Any],
    *,
    event_id: str,
    timestamp_ms: int,
    target_component_id: str | None = None,
    sequence: int = 0,
    provenance: EventProvenance = EventProvenance.HUMAN,
    consent_ok: bool | None = None,
    debounce_ms: int | None = None,
    debounce_state: _DebounceState | None = None,
    record_activation: bool = True,
) -> CanonicalInteractionEvent:
    """Map Arrow/Enter-style Neural Band intents only (no raw EMG)."""

    if not isinstance(raw, Mapping):
        raise UIIRValidationError("neural band input raw must be a mapping")
    # Force neural_band capability regardless of caller channel alias.
    enriched: dict[str, Any] = dict(raw)
    enriched.setdefault("capability_id", CAPABILITY_NEURAL_BAND)
    enriched.setdefault("channel", "neural_band")
    # Reject any attempt to claim continuous EMG.
    if enriched.get("emg_access") is True or enriched.get("raw_emg") is not None:
        raise UIIRValidationError(
            "Neural Band adapter never claims or retains raw EMG data"
        )
    return normalize_embodied_input(
        enriched,
        event_id=event_id,
        timestamp_ms=timestamp_ms,
        target_component_id=target_component_id,
        sequence=sequence,
        provenance=provenance,
        consent_ok=consent_ok,
        debounce_ms=debounce_ms,
        debounce_state=debounce_state,
        record_activation=record_activation,
    )


def normalize_neural_band_intent_detailed(
    raw: Mapping[str, Any],
    *,
    event_id: str,
    timestamp_ms: int,
    target_component_id: str | None = None,
    sequence: int = 0,
    provenance: EventProvenance = EventProvenance.HUMAN,
    consent_ok: bool | None = None,
    debounce_ms: int | None = None,
    debounce_state: _DebounceState | None = None,
    record_activation: bool = True,
) -> EmbodiedNormalizationResult:
    """Detailed Neural Band normalization (Arrow/Enter only)."""

    if not isinstance(raw, Mapping):
        raise UIIRValidationError("neural band input raw must be a mapping")
    enriched: dict[str, Any] = dict(raw)
    enriched.setdefault("capability_id", CAPABILITY_NEURAL_BAND)
    enriched.setdefault("channel", "neural_band")
    if enriched.get("emg_access") is True or enriched.get("raw_emg") is not None:
        raise UIIRValidationError(
            "Neural Band adapter never claims or retains raw EMG data"
        )
    return normalize_embodied_input_detailed(
        enriched,
        event_id=event_id,
        timestamp_ms=timestamp_ms,
        target_component_id=target_component_id,
        sequence=sequence,
        provenance=provenance,
        consent_ok=consent_ok,
        debounce_ms=debounce_ms,
        debounce_state=debounce_state,
        record_activation=record_activation,
    )


class EmbodiedInputAdapter:
    """EmbodiedInputAdapter@1 — normalize injected gesture/pose/D-pad events.

    Does not open cameras, stream gaze, read EMG, or decide policy/authority.
    Maintains a local debounce ledger to prevent accidental duplicate activation.
    """

    interface_id: Final = EMBODIED_INPUT_ADAPTER_INTERFACE
    adapter_id: Final = EMBODIED_ADAPTER_ID

    def __init__(self) -> None:
        self._debounce = _DebounceState()

    def clear_debounce(self) -> None:
        self._debounce.clear()

    def normalize(
        self,
        raw: Mapping[str, Any],
        *,
        event_id: str,
        timestamp_ms: int,
        target_component_id: str | None = None,
        sequence: int = 0,
        provenance: EventProvenance = EventProvenance.HUMAN,
        consent_ok: bool | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        max_age_ms: int = DEFAULT_MAX_AGE_MS,
        dwell_threshold_ms: int | None = None,
        debounce_ms: int | None = None,
    ) -> CanonicalInteractionEvent:
        return normalize_embodied_input(
            raw,
            event_id=event_id,
            timestamp_ms=timestamp_ms,
            target_component_id=target_component_id,
            sequence=sequence,
            provenance=provenance,
            consent_ok=consent_ok,
            confidence_threshold=confidence_threshold,
            max_age_ms=max_age_ms,
            dwell_threshold_ms=dwell_threshold_ms,
            debounce_ms=debounce_ms,
            debounce_state=self._debounce,
        )

    def normalize_detailed(
        self,
        raw: Mapping[str, Any],
        *,
        event_id: str,
        timestamp_ms: int,
        target_component_id: str | None = None,
        sequence: int = 0,
        provenance: EventProvenance = EventProvenance.HUMAN,
        consent_ok: bool | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        max_age_ms: int = DEFAULT_MAX_AGE_MS,
        dwell_threshold_ms: int | None = None,
        debounce_ms: int | None = None,
    ) -> EmbodiedNormalizationResult:
        return normalize_embodied_input_detailed(
            raw,
            event_id=event_id,
            timestamp_ms=timestamp_ms,
            target_component_id=target_component_id,
            sequence=sequence,
            provenance=provenance,
            consent_ok=consent_ok,
            confidence_threshold=confidence_threshold,
            max_age_ms=max_age_ms,
            dwell_threshold_ms=dwell_threshold_ms,
            debounce_ms=debounce_ms,
            debounce_state=self._debounce,
        )

    def report_unavailable(
        self,
        *,
        capability_id: str,
        reason: str,
        status: EmbodiedCapabilityStatus = EmbodiedCapabilityStatus.UNAVAILABLE,
        fallback_modalities: Sequence[str] = DEFAULT_FALLBACKS,
    ) -> EmbodiedUnavailable:
        """Express unavailable hand/gaze/neural capability with fallbacks."""

        cap = str(capability_id).strip().lower()
        if cap not in EMBODIED_CAPABILITIES:
            if cap in _CHANNEL_TO_CAPABILITY:
                cap = _CHANNEL_TO_CAPABILITY[cap]
            else:
                raise UIIRValidationError(
                    f"Unknown embodied capability for unavailable report: {capability_id!r}"
                )
        fallbacks = tuple(
            s for s in (str(x).strip() for x in fallback_modalities) if s
        )
        if not fallbacks:
            fallbacks = DEFAULT_FALLBACKS
        return EmbodiedUnavailable(
            capability_id=cap,
            status=status,
            reason=str(reason).strip() or f"{cap} unavailable",
            fallback_modalities=fallbacks,
        )


class NeuralBandIntentAdapter:
    """NeuralBandIntentAdapter@1 — Arrow/Enter normalized intents only.

    Never claims continuous Neural Band streams or raw EMG features.
    """

    interface_id: Final = NEURAL_BAND_INTENT_ADAPTER_INTERFACE
    adapter_id: Final = NEURAL_BAND_ADAPTER_ID
    capability_id: Final = CAPABILITY_NEURAL_BAND

    def __init__(self) -> None:
        self._debounce = _DebounceState()

    def clear_debounce(self) -> None:
        self._debounce.clear()

    def normalize(
        self,
        raw: Mapping[str, Any],
        *,
        event_id: str,
        timestamp_ms: int,
        target_component_id: str | None = None,
        sequence: int = 0,
        provenance: EventProvenance = EventProvenance.HUMAN,
        consent_ok: bool | None = None,
        debounce_ms: int | None = None,
    ) -> CanonicalInteractionEvent:
        return normalize_neural_band_intent(
            raw,
            event_id=event_id,
            timestamp_ms=timestamp_ms,
            target_component_id=target_component_id,
            sequence=sequence,
            provenance=provenance,
            consent_ok=consent_ok,
            debounce_ms=debounce_ms,
            debounce_state=self._debounce,
        )

    def normalize_detailed(
        self,
        raw: Mapping[str, Any],
        *,
        event_id: str,
        timestamp_ms: int,
        target_component_id: str | None = None,
        sequence: int = 0,
        provenance: EventProvenance = EventProvenance.HUMAN,
        consent_ok: bool | None = None,
        debounce_ms: int | None = None,
    ) -> EmbodiedNormalizationResult:
        return normalize_neural_band_intent_detailed(
            raw,
            event_id=event_id,
            timestamp_ms=timestamp_ms,
            target_component_id=target_component_id,
            sequence=sequence,
            provenance=provenance,
            consent_ok=consent_ok,
            debounce_ms=debounce_ms,
            debounce_state=self._debounce,
        )


__all__ = [
    "CAPABILITY_DPAD_CAPTOUCH",
    "CAPABILITY_GAZE",
    "CAPABILITY_HAND_GESTURE",
    "CAPABILITY_HEAD_POSE",
    "CAPABILITY_MOTION",
    "CAPABILITY_NEURAL_BAND",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_DEBOUNCE_MS",
    "DEFAULT_FALLBACKS",
    "DEFAULT_GAZE_DWELL_MS",
    "DEFAULT_HIGH_RISK_DEBOUNCE_MS",
    "DEFAULT_HIGH_RISK_GAZE_DWELL_MS",
    "DEFAULT_MAX_AGE_MS",
    "EMBODIED_ADAPTER_ID",
    "EMBODIED_CAPABILITIES",
    "EMBODIED_INPUT_ADAPTER_INTERFACE",
    "NEURAL_BAND_ADAPTER_ID",
    "NEURAL_BAND_INTENT_ADAPTER_INTERFACE",
    "EmbodiedCapabilityStatus",
    "EmbodiedGate",
    "EmbodiedGateReason",
    "EmbodiedInputAdapter",
    "EmbodiedNormalizationResult",
    "EmbodiedPhase",
    "EmbodiedUnavailable",
    "NeuralBandIntentAdapter",
    "normalize_embodied_input",
    "normalize_embodied_input_detailed",
    "normalize_neural_band_intent",
    "normalize_neural_band_intent_detailed",
]
