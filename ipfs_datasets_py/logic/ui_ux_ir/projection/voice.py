"""Voice audio and headless agent projections (UIR-044).

``UIIRVoiceProjection@1`` serializes tasks, prompts, choices, summaries,
confirmations, progress, results, errors, and recovery into ordered
speech/audio dialogue units with transcripts and captions.

``UIIRHeadlessProjection@1`` produces agent-readable structured sequences of
the same mandatory semantics without visual or TTS rendering.

Both surfaces are renderer-neutral: they emit speech text, structured steps,
and loss receipts — never microphone capture, ASR models, TTS engines, or
agent executors. Unavailable audio or display channels are reported
explicitly rather than silently omitted.
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
    ProfileFamily,
    UIDeviceProfile,
    headless_profile,
    validate_device_profile,
    voice_profile,
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
    merge_loss_reports,
)
from .solver import (
    PresentationDisposition,
    ProjectedNode,
    ProjectionItem,
    ProjectionPolicy,
    ProjectionProblem,
    ProjectionStatus,
    UIProjectionArtifact,
    project_ui_ir,
    projection_problem_from_document,
    solve_projection,
)

UI_VOICE_PROJECTION_INTERFACE: Final = "UIIRVoiceProjection@1"
UI_HEADLESS_PROJECTION_INTERFACE: Final = "UIIRHeadlessProjection@1"
UI_VOICE_ARTIFACT_SCHEMA_VERSION: Final = "ui-voice-projection/v1"
UI_HEADLESS_ARTIFACT_SCHEMA_VERSION: Final = "ui-headless-projection/v1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

# Semantic kinds that voice/headless must surface as first-class dialogue units.
_VOICE_SEMANTIC_KINDS: Final[frozenset[str]] = frozenset(
    {
        MandatorySemanticKind.ACTION.value,
        MandatorySemanticKind.CONSENT.value,
        MandatorySemanticKind.CONSEQUENCE.value,
        MandatorySemanticKind.ERROR.value,
        MandatorySemanticKind.CONFIRMATION.value,
        MandatorySemanticKind.FEEDBACK.value,
        MandatorySemanticKind.ACCESSIBILITY.value,
        MandatorySemanticKind.PRIVACY.value,
        "choice",
        "cancellation",
        "pending",
        "result",
        "recovery",
        "prompt",
        "summary",
        "progress",
        "task",
    }
)

# Kinds that must never be dropped without an explicit loss receipt.
_MANDATORY_VOICE_KINDS: Final[frozenset[str]] = frozenset(
    {
        MandatorySemanticKind.ACTION.value,
        MandatorySemanticKind.CONSENT.value,
        MandatorySemanticKind.CONSEQUENCE.value,
        MandatorySemanticKind.ERROR.value,
        MandatorySemanticKind.CONFIRMATION.value,
        MandatorySemanticKind.FEEDBACK.value,
        MandatorySemanticKind.ACCESSIBILITY.value,
        "choice",
        "cancellation",
        "pending",
        "result",
        "recovery",
    }
)

# Dialogue ordering rank (lower first). Ambiguity/choice before confirmation;
# errors and recovery after pending/result.
_KIND_ORDER: Final[dict[str, int]] = {
    MandatorySemanticKind.ACCESSIBILITY.value: 0,
    "task": 1,
    "prompt": 2,
    "summary": 3,
    MandatorySemanticKind.CONSENT.value: 4,
    MandatorySemanticKind.CONSEQUENCE.value: 5,
    "choice": 6,
    MandatorySemanticKind.CONFIRMATION.value: 7,
    MandatorySemanticKind.ACTION.value: 8,
    "pending": 9,
    "progress": 10,
    "result": 11,
    MandatorySemanticKind.ERROR.value: 12,
    "recovery": 13,
    "cancellation": 14,
    MandatorySemanticKind.FEEDBACK.value: 15,
    MandatorySemanticKind.PRIVACY.value: 16,
}

# Default spoken prefixes that keep dialogue self-describing without a renderer.
_KIND_SPEECH_PREFIX: Final[dict[str, str]] = {
    MandatorySemanticKind.ACCESSIBILITY.value: "Accessible name",
    "task": "Task",
    "prompt": "Prompt",
    "summary": "Summary",
    MandatorySemanticKind.CONSENT.value: "Consent required",
    MandatorySemanticKind.CONSEQUENCE.value: "Consequence",
    "choice": "Choice",
    MandatorySemanticKind.CONFIRMATION.value: "Please confirm",
    MandatorySemanticKind.ACTION.value: "Action",
    "pending": "Pending",
    "progress": "Progress",
    "result": "Result",
    MandatorySemanticKind.ERROR.value: "Error",
    "recovery": "Recovery",
    "cancellation": "Cancellation available",
    MandatorySemanticKind.FEEDBACK.value: "Status",
    MandatorySemanticKind.PRIVACY.value: "Privacy notice",
}


class DialogueRole(str, Enum):
    """Speaker/role for a projected dialogue unit (renderer-neutral)."""

    SYSTEM = "system"
    ASSISTANT = "assistant"
    USER_PROMPT = "user_prompt"
    CHOICE = "choice"
    CONFIRMATION = "confirmation"
    PENDING = "pending"
    RESULT = "result"
    ERROR = "error"
    RECOVERY = "recovery"
    CONSEQUENCE = "consequence"
    CANCEL = "cancel"
    ACCESSIBILITY = "accessibility"
    FEEDBACK = "feedback"
    PRIVACY = "privacy"
    TASK = "task"
    SUMMARY = "summary"
    PROGRESS = "progress"
    PROMPT = "prompt"
    ACTION = "action"
    CONSENT = "consent"


class UrgencyClass(str, Enum):
    """Closed urgency vocabulary for voice/headless delivery."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class InterruptionPolicy(str, Enum):
    """How a unit may interrupt ongoing speech or agent work."""

    ALLOW = "allow"
    DEFER = "defer"
    BLOCK = "block"
    ANNOUNCE_THEN_ALLOW = "announce_then_allow"


class ChannelKind(str, Enum):
    """Output channels tracked for availability / fallback."""

    AUDIO = "audio"
    SPEECH_OUTPUT = "speech_output"
    DISPLAY = "display"
    AGENT_STRUCTURED = "agent_structured"
    TRANSCRIPT = "transcript"
    CAPTION = "caption"
    NOTIFICATION = "notification"
    FALLBACK = "fallback"


class ChannelAvailability(str, Enum):
    """Explicit availability of an output channel."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    FALLBACK = "fallback"
    DEGRADED = "degraded"


class VoiceTurnKind(str, Enum):
    """Closed set of dialogue unit kinds in a voice projection."""

    PROMPT = "prompt"
    CHOICE = "choice"
    CONFIRMATION = "confirmation"
    CONSEQUENCE = "consequence"
    PENDING = "pending"
    RESULT = "result"
    ERROR = "error"
    RECOVERY = "recovery"
    CANCELLATION = "cancellation"
    ACCESSIBLE_NAME = "accessible_name"
    FEEDBACK = "feedback"
    SUMMARY = "summary"
    PROGRESS = "progress"
    TASK = "task"
    ACTION = "action"
    CONSENT = "consent"
    PRIVACY = "privacy"
    ANNOUNCEMENT = "announcement"


class HeadlessStepKind(str, Enum):
    """Closed set of agent-readable step kinds."""

    PROMPT = "prompt"
    CHOICE = "choice"
    CONFIRMATION = "confirmation"
    CONSEQUENCE = "consequence"
    PENDING = "pending"
    RESULT = "result"
    ERROR = "error"
    RECOVERY = "recovery"
    CANCELLATION = "cancellation"
    ACCESSIBLE_NAME = "accessible_name"
    FEEDBACK = "feedback"
    SUMMARY = "summary"
    PROGRESS = "progress"
    TASK = "task"
    ACTION = "action"
    CONSENT = "consent"
    PRIVACY = "privacy"
    STATE = "state"


# Map semantic_kind -> voice turn kind / dialogue role / headless step kind.
_SEMANTIC_TO_VOICE_TURN: Final[dict[str, VoiceTurnKind]] = {
    MandatorySemanticKind.ACCESSIBILITY.value: VoiceTurnKind.ACCESSIBLE_NAME,
    "task": VoiceTurnKind.TASK,
    "prompt": VoiceTurnKind.PROMPT,
    "summary": VoiceTurnKind.SUMMARY,
    MandatorySemanticKind.CONSENT.value: VoiceTurnKind.CONSENT,
    MandatorySemanticKind.CONSEQUENCE.value: VoiceTurnKind.CONSEQUENCE,
    "choice": VoiceTurnKind.CHOICE,
    MandatorySemanticKind.CONFIRMATION.value: VoiceTurnKind.CONFIRMATION,
    MandatorySemanticKind.ACTION.value: VoiceTurnKind.ACTION,
    "pending": VoiceTurnKind.PENDING,
    "progress": VoiceTurnKind.PROGRESS,
    "result": VoiceTurnKind.RESULT,
    MandatorySemanticKind.ERROR.value: VoiceTurnKind.ERROR,
    "recovery": VoiceTurnKind.RECOVERY,
    "cancellation": VoiceTurnKind.CANCELLATION,
    MandatorySemanticKind.FEEDBACK.value: VoiceTurnKind.FEEDBACK,
    MandatorySemanticKind.PRIVACY.value: VoiceTurnKind.PRIVACY,
}

_SEMANTIC_TO_DIALOGUE_ROLE: Final[dict[str, DialogueRole]] = {
    MandatorySemanticKind.ACCESSIBILITY.value: DialogueRole.ACCESSIBILITY,
    "task": DialogueRole.TASK,
    "prompt": DialogueRole.PROMPT,
    "summary": DialogueRole.SUMMARY,
    MandatorySemanticKind.CONSENT.value: DialogueRole.CONSENT,
    MandatorySemanticKind.CONSEQUENCE.value: DialogueRole.CONSEQUENCE,
    "choice": DialogueRole.CHOICE,
    MandatorySemanticKind.CONFIRMATION.value: DialogueRole.CONFIRMATION,
    MandatorySemanticKind.ACTION.value: DialogueRole.ACTION,
    "pending": DialogueRole.PENDING,
    "progress": DialogueRole.PROGRESS,
    "result": DialogueRole.RESULT,
    MandatorySemanticKind.ERROR.value: DialogueRole.ERROR,
    "recovery": DialogueRole.RECOVERY,
    "cancellation": DialogueRole.CANCEL,
    MandatorySemanticKind.FEEDBACK.value: DialogueRole.FEEDBACK,
    MandatorySemanticKind.PRIVACY.value: DialogueRole.PRIVACY,
}

_SEMANTIC_TO_HEADLESS_STEP: Final[dict[str, HeadlessStepKind]] = {
    MandatorySemanticKind.ACCESSIBILITY.value: HeadlessStepKind.ACCESSIBLE_NAME,
    "task": HeadlessStepKind.TASK,
    "prompt": HeadlessStepKind.PROMPT,
    "summary": HeadlessStepKind.SUMMARY,
    MandatorySemanticKind.CONSENT.value: HeadlessStepKind.CONSENT,
    MandatorySemanticKind.CONSEQUENCE.value: HeadlessStepKind.CONSEQUENCE,
    "choice": HeadlessStepKind.CHOICE,
    MandatorySemanticKind.CONFIRMATION.value: HeadlessStepKind.CONFIRMATION,
    MandatorySemanticKind.ACTION.value: HeadlessStepKind.ACTION,
    "pending": HeadlessStepKind.PENDING,
    "progress": HeadlessStepKind.PROGRESS,
    "result": HeadlessStepKind.RESULT,
    MandatorySemanticKind.ERROR.value: HeadlessStepKind.ERROR,
    "recovery": HeadlessStepKind.RECOVERY,
    "cancellation": HeadlessStepKind.CANCELLATION,
    MandatorySemanticKind.FEEDBACK.value: HeadlessStepKind.FEEDBACK,
    MandatorySemanticKind.PRIVACY.value: HeadlessStepKind.PRIVACY,
}

_DEFAULT_URGENCY_FOR_KIND: Final[dict[str, UrgencyClass]] = {
    MandatorySemanticKind.ERROR.value: UrgencyClass.HIGH,
    MandatorySemanticKind.CONFIRMATION.value: UrgencyClass.HIGH,
    MandatorySemanticKind.CONSENT.value: UrgencyClass.HIGH,
    MandatorySemanticKind.CONSEQUENCE.value: UrgencyClass.HIGH,
    MandatorySemanticKind.PRIVACY.value: UrgencyClass.HIGH,
    "cancellation": UrgencyClass.HIGH,
    "pending": UrgencyClass.NORMAL,
    "progress": UrgencyClass.LOW,
    "result": UrgencyClass.NORMAL,
    "recovery": UrgencyClass.HIGH,
    "choice": UrgencyClass.NORMAL,
    MandatorySemanticKind.ACTION.value: UrgencyClass.NORMAL,
    MandatorySemanticKind.FEEDBACK.value: UrgencyClass.LOW,
    MandatorySemanticKind.ACCESSIBILITY.value: UrgencyClass.NORMAL,
    "task": UrgencyClass.NORMAL,
    "prompt": UrgencyClass.NORMAL,
    "summary": UrgencyClass.LOW,
}

_DEFAULT_INTERRUPTION_FOR_KIND: Final[dict[str, InterruptionPolicy]] = {
    MandatorySemanticKind.ERROR.value: InterruptionPolicy.ANNOUNCE_THEN_ALLOW,
    MandatorySemanticKind.CONFIRMATION.value: InterruptionPolicy.BLOCK,
    MandatorySemanticKind.CONSENT.value: InterruptionPolicy.BLOCK,
    MandatorySemanticKind.CONSEQUENCE.value: InterruptionPolicy.BLOCK,
    MandatorySemanticKind.PRIVACY.value: InterruptionPolicy.BLOCK,
    "cancellation": InterruptionPolicy.ALLOW,
    "pending": InterruptionPolicy.DEFER,
    "progress": InterruptionPolicy.DEFER,
    "result": InterruptionPolicy.ANNOUNCE_THEN_ALLOW,
    "recovery": InterruptionPolicy.ANNOUNCE_THEN_ALLOW,
    "choice": InterruptionPolicy.BLOCK,
    MandatorySemanticKind.ACTION.value: InterruptionPolicy.ALLOW,
    MandatorySemanticKind.FEEDBACK.value: InterruptionPolicy.DEFER,
    MandatorySemanticKind.ACCESSIBILITY.value: InterruptionPolicy.ALLOW,
    "task": InterruptionPolicy.ALLOW,
    "prompt": InterruptionPolicy.ALLOW,
    "summary": InterruptionPolicy.DEFER,
}

# Dispositions that count as successfully presented (not silent omit).
_PRESENTED_DISPOSITIONS: Final[frozenset[PresentationDisposition]] = frozenset(
    {
        PresentationDisposition.PRESERVED,
        PresentationDisposition.ADAPTED,
        PresentationDisposition.SUMMARIZED,
        PresentationDisposition.FALLBACK,
    }
)


def _validate_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise UIIRValidationError(f"{name} is not a stable identifier")


def _validate_non_empty_string(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise UIIRValidationError(f"{name} must be a non-empty string")


def _require_tuple(name: str, value: Any) -> None:
    if not isinstance(value, tuple):
        raise UIIRValidationError(f"{name} must be an immutable tuple")


def _item_is_mandatory(item: ProjectionItem) -> bool:
    return (
        item.mandatory
        or item.semantic_kind in MANDATORY_SEMANTIC_KINDS
        or item.semantic_kind in _MANDATORY_VOICE_KINDS
    )


def _urgency_for(kind: str, explicit: UrgencyClass | str | None = None) -> UrgencyClass:
    if explicit is not None:
        if isinstance(explicit, UrgencyClass):
            return explicit
        try:
            return UrgencyClass(str(explicit))
        except ValueError as exc:
            raise UIIRValidationError(f"Unknown urgency class: {explicit!r}") from exc
    return _DEFAULT_URGENCY_FOR_KIND.get(kind, UrgencyClass.NORMAL)


def _interruption_for(
    kind: str, explicit: InterruptionPolicy | str | None = None
) -> InterruptionPolicy:
    if explicit is not None:
        if isinstance(explicit, InterruptionPolicy):
            return explicit
        try:
            return InterruptionPolicy(str(explicit))
        except ValueError as exc:
            raise UIIRValidationError(
                f"Unknown interruption policy: {explicit!r}"
            ) from exc
    return _DEFAULT_INTERRUPTION_FOR_KIND.get(kind, InterruptionPolicy.ALLOW)


def _speech_text(item: ProjectionItem, *, summarized: bool = False) -> str:
    """Build renderer-neutral spoken text from a projection item."""

    label = (item.label or item.item_id).strip()
    prefix = _KIND_SPEECH_PREFIX.get(item.semantic_kind, "Notice")
    if summarized and len(label) > 48:
        label = label[:45].rstrip() + "..."
    if item.semantic_kind == MandatorySemanticKind.ACCESSIBILITY.value:
        return f"{prefix}: {label}"
    if item.semantic_kind == "choice":
        return f"{prefix}: {label}. Say the option name or number to select."
    if item.semantic_kind == MandatorySemanticKind.CONFIRMATION.value:
        return f"{prefix}: {label}. Say confirm to proceed or cancel to abort."
    if item.semantic_kind == "cancellation":
        return f"{prefix}: {label}. You may cancel at any time."
    if item.semantic_kind == "pending":
        return f"{prefix}: {label}. Please wait."
    if item.semantic_kind == MandatorySemanticKind.ERROR.value:
        return f"{prefix}: {label}."
    if item.semantic_kind == "recovery":
        return f"{prefix}: {label}. You may retry or choose another path."
    return f"{prefix}: {label}."


def _caption_text(speech: str) -> str:
    """Caption mirrors speech for visual/text fallback surfaces."""

    return speech


def _transcript_text(speech: str, *, role: DialogueRole, order: int) -> str:
    """Stable transcript line for accessibility and audit."""

    return f"[{order}:{role.value}] {speech}"


@dataclass(frozen=True, slots=True)
class VoiceChoiceOption:
    """One selectable choice in a voice dialogue unit."""

    option_id: str
    label: str
    utterance_hints: tuple[str, ...] = ()
    consequence_ref: str = ""
    cancelable: bool = True

    def validate(self) -> None:
        _validate_identifier("VoiceChoiceOption.option_id", self.option_id)
        _validate_non_empty_string("VoiceChoiceOption.label", self.label)
        _require_tuple(
            "VoiceChoiceOption.utterance_hints", self.utterance_hints
        )
        for index, hint in enumerate(self.utterance_hints):
            if not isinstance(hint, str) or not hint.strip():
                raise UIIRValidationError(
                    f"VoiceChoiceOption.utterance_hints[{index}] must be non-empty"
                )
        if not isinstance(self.consequence_ref, str):
            raise UIIRValidationError(
                "VoiceChoiceOption.consequence_ref must be a string"
            )
        if not isinstance(self.cancelable, bool):
            raise UIIRValidationError(
                "VoiceChoiceOption.cancelable must be a boolean"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cancelable": self.cancelable,
            "consequence_ref": self.consequence_ref,
            "label": self.label,
            "option_id": self.option_id,
            "utterance_hints": list(self.utterance_hints),
        }


@dataclass(frozen=True, slots=True)
class ChannelStatus:
    """Explicit availability of one output channel with optional fallback."""

    channel: ChannelKind
    availability: ChannelAvailability
    fallback_channel: ChannelKind | None = None
    reason: str = ""

    def validate(self) -> None:
        if not isinstance(self.channel, ChannelKind):
            raise UIIRValidationError("ChannelStatus.channel must be a ChannelKind")
        if not isinstance(self.availability, ChannelAvailability):
            raise UIIRValidationError(
                "ChannelStatus.availability must be a ChannelAvailability"
            )
        if self.fallback_channel is not None and not isinstance(
            self.fallback_channel, ChannelKind
        ):
            raise UIIRValidationError(
                "ChannelStatus.fallback_channel must be a ChannelKind or None"
            )
        if not isinstance(self.reason, str):
            raise UIIRValidationError("ChannelStatus.reason must be a string")
        if (
            self.availability
            in {ChannelAvailability.UNAVAILABLE, ChannelAvailability.FALLBACK}
            and not self.reason.strip()
        ):
            raise UIIRValidationError(
                f"ChannelStatus for {self.channel.value} requires a reason when "
                f"availability is {self.availability.value}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "availability": self.availability.value,
            "channel": self.channel.value,
            "fallback_channel": (
                self.fallback_channel.value if self.fallback_channel else ""
            ),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class VoiceTurn:
    """One ordered speech unit in a voice projection (renderer-neutral)."""

    turn_id: str
    kind: VoiceTurnKind
    role: DialogueRole
    order: int
    speech_text: str
    transcript: str
    caption: str
    semantic_id: str
    semantic_kind: str
    mandatory: bool
    disposition: PresentationDisposition
    urgency: UrgencyClass = UrgencyClass.NORMAL
    interruption_policy: InterruptionPolicy = InterruptionPolicy.ALLOW
    accessible_name: str = ""
    choices: tuple[VoiceChoiceOption, ...] = ()
    cancelable: bool = False
    requires_confirmation: bool = False
    consequence_ref: str = ""
    recovery_ref: str = ""
    fallback_ref: str = ""
    component_id: str = ""
    ambiguity_group: str = ""
    details: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("VoiceTurn.turn_id", self.turn_id)
        if not isinstance(self.kind, VoiceTurnKind):
            raise UIIRValidationError("VoiceTurn.kind must be a VoiceTurnKind")
        if not isinstance(self.role, DialogueRole):
            raise UIIRValidationError("VoiceTurn.role must be a DialogueRole")
        if not isinstance(self.order, int) or isinstance(self.order, bool) or self.order < 0:
            raise UIIRValidationError("VoiceTurn.order must be a non-negative integer")
        _validate_non_empty_string("VoiceTurn.speech_text", self.speech_text)
        _validate_non_empty_string("VoiceTurn.transcript", self.transcript)
        _validate_non_empty_string("VoiceTurn.caption", self.caption)
        _validate_identifier("VoiceTurn.semantic_id", self.semantic_id)
        _validate_non_empty_string("VoiceTurn.semantic_kind", self.semantic_kind)
        if not isinstance(self.mandatory, bool):
            raise UIIRValidationError("VoiceTurn.mandatory must be a boolean")
        if not isinstance(self.disposition, PresentationDisposition):
            raise UIIRValidationError(
                "VoiceTurn.disposition must be a PresentationDisposition"
            )
        if not isinstance(self.urgency, UrgencyClass):
            raise UIIRValidationError("VoiceTurn.urgency must be an UrgencyClass")
        if not isinstance(self.interruption_policy, InterruptionPolicy):
            raise UIIRValidationError(
                "VoiceTurn.interruption_policy must be an InterruptionPolicy"
            )
        _require_tuple("VoiceTurn.choices", self.choices)
        for choice in self.choices:
            if not isinstance(choice, VoiceChoiceOption):
                raise UIIRValidationError(
                    "VoiceTurn.choices members must be VoiceChoiceOption"
                )
            choice.validate()
        if self.kind is VoiceTurnKind.CHOICE and not self.choices:
            raise UIIRValidationError(
                f"VoiceTurn {self.turn_id!r} of kind choice requires choices"
            )
        for name in (
            "accessible_name",
            "consequence_ref",
            "recovery_ref",
            "fallback_ref",
            "component_id",
            "ambiguity_group",
        ):
            if not isinstance(getattr(self, name), str):
                raise UIIRValidationError(f"VoiceTurn.{name} must be a string")
        for name in ("cancelable", "requires_confirmation"):
            if not isinstance(getattr(self, name), bool):
                raise UIIRValidationError(f"VoiceTurn.{name} must be a boolean")
        _require_tuple("VoiceTurn.details", self.details)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessible_name": self.accessible_name,
            "ambiguity_group": self.ambiguity_group,
            "cancelable": self.cancelable,
            "caption": self.caption,
            "choices": [item.to_dict() for item in self.choices],
            "component_id": self.component_id,
            "consequence_ref": self.consequence_ref,
            "details": list(self.details),
            "disposition": self.disposition.value,
            "fallback_ref": self.fallback_ref,
            "interruption_policy": self.interruption_policy.value,
            "kind": self.kind.value,
            "mandatory": self.mandatory,
            "order": self.order,
            "recovery_ref": self.recovery_ref,
            "requires_confirmation": self.requires_confirmation,
            "role": self.role.value,
            "semantic_id": self.semantic_id,
            "semantic_kind": self.semantic_kind,
            "speech_text": self.speech_text,
            "transcript": self.transcript,
            "turn_id": self.turn_id,
            "urgency": self.urgency.value,
        }


@dataclass(frozen=True, slots=True)
class HeadlessStep:
    """One agent-readable structured step (no visual/TTS rendering)."""

    step_id: str
    kind: HeadlessStepKind
    order: int
    payload: Mapping[str, Any]
    semantic_id: str
    semantic_kind: str
    mandatory: bool
    disposition: PresentationDisposition
    urgency: UrgencyClass = UrgencyClass.NORMAL
    interruption_policy: InterruptionPolicy = InterruptionPolicy.ALLOW
    accessible_name: str = ""
    choice_ids: tuple[str, ...] = ()
    cancelable: bool = False
    requires_confirmation: bool = False
    consequence_ref: str = ""
    recovery_ref: str = ""
    fallback_ref: str = ""
    component_id: str = ""
    message: str = ""

    def validate(self) -> None:
        _validate_identifier("HeadlessStep.step_id", self.step_id)
        if not isinstance(self.kind, HeadlessStepKind):
            raise UIIRValidationError("HeadlessStep.kind must be a HeadlessStepKind")
        if (
            not isinstance(self.order, int)
            or isinstance(self.order, bool)
            or self.order < 0
        ):
            raise UIIRValidationError(
                "HeadlessStep.order must be a non-negative integer"
            )
        if not isinstance(self.payload, Mapping):
            raise UIIRValidationError("HeadlessStep.payload must be a mapping")
        # Reject executable surfaces in agent payload.
        for key in self.payload:
            if not isinstance(key, str):
                raise UIIRValidationError(
                    "HeadlessStep.payload keys must be strings"
                )
            lowered = key.lower()
            if lowered in {
                "callback",
                "code",
                "eval",
                "exec",
                "function",
                "handler",
                "script",
            }:
                raise UIIRValidationError(
                    f"HeadlessStep.payload rejects executable key {key!r}"
                )
        _validate_identifier("HeadlessStep.semantic_id", self.semantic_id)
        _validate_non_empty_string("HeadlessStep.semantic_kind", self.semantic_kind)
        if not isinstance(self.mandatory, bool):
            raise UIIRValidationError("HeadlessStep.mandatory must be a boolean")
        if not isinstance(self.disposition, PresentationDisposition):
            raise UIIRValidationError(
                "HeadlessStep.disposition must be a PresentationDisposition"
            )
        if not isinstance(self.urgency, UrgencyClass):
            raise UIIRValidationError("HeadlessStep.urgency must be an UrgencyClass")
        if not isinstance(self.interruption_policy, InterruptionPolicy):
            raise UIIRValidationError(
                "HeadlessStep.interruption_policy must be an InterruptionPolicy"
            )
        _require_tuple("HeadlessStep.choice_ids", self.choice_ids)
        for index, choice_id in enumerate(self.choice_ids):
            _validate_identifier(f"HeadlessStep.choice_ids[{index}]", choice_id)
        for name in (
            "accessible_name",
            "consequence_ref",
            "recovery_ref",
            "fallback_ref",
            "component_id",
            "message",
        ):
            if not isinstance(getattr(self, name), str):
                raise UIIRValidationError(f"HeadlessStep.{name} must be a string")
        for name in ("cancelable", "requires_confirmation"):
            if not isinstance(getattr(self, name), bool):
                raise UIIRValidationError(f"HeadlessStep.{name} must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        # Deterministic payload serialization: sort keys at top level.
        payload = {
            key: self.payload[key]
            for key in sorted(self.payload.keys())
        }
        return {
            "accessible_name": self.accessible_name,
            "cancelable": self.cancelable,
            "choice_ids": list(self.choice_ids),
            "component_id": self.component_id,
            "consequence_ref": self.consequence_ref,
            "disposition": self.disposition.value,
            "fallback_ref": self.fallback_ref,
            "interruption_policy": self.interruption_policy.value,
            "kind": self.kind.value,
            "mandatory": self.mandatory,
            "message": self.message,
            "order": self.order,
            "payload": payload,
            "recovery_ref": self.recovery_ref,
            "requires_confirmation": self.requires_confirmation,
            "semantic_id": self.semantic_id,
            "semantic_kind": self.semantic_kind,
            "step_id": self.step_id,
            "urgency": self.urgency.value,
        }


@dataclass(frozen=True, slots=True)
class VoiceProjectionArtifact:
    """Deterministic voice/audio projection with transcripts and channel status.

    Interface identity: ``UIIRVoiceProjection@1``.
    """

    artifact_id: str
    status: ProjectionStatus
    profile_id: str
    problem_id: str
    turns: tuple[VoiceTurn, ...]
    channel_status: tuple[ChannelStatus, ...]
    loss_report: ProjectionLossReport
    base_artifact: UIProjectionArtifact
    document_id: str = ""
    dialogue_order: tuple[str, ...] = ()
    interruption_default: InterruptionPolicy = InterruptionPolicy.ALLOW
    schema_version: str = UI_VOICE_ARTIFACT_SCHEMA_VERSION
    interface: str = UI_VOICE_PROJECTION_INTERFACE
    renderer: str = "neutral"

    def validate(self) -> "VoiceProjectionArtifact":
        _validate_identifier("VoiceProjectionArtifact.artifact_id", self.artifact_id)
        if not isinstance(self.status, ProjectionStatus):
            raise UIIRValidationError(
                "VoiceProjectionArtifact.status must be a ProjectionStatus"
            )
        _validate_non_empty_string(
            "VoiceProjectionArtifact.profile_id", self.profile_id
        )
        _validate_non_empty_string(
            "VoiceProjectionArtifact.problem_id", self.problem_id
        )
        _require_tuple("VoiceProjectionArtifact.turns", self.turns)
        seen: set[str] = set()
        for turn in self.turns:
            if not isinstance(turn, VoiceTurn):
                raise UIIRValidationError(
                    "VoiceProjectionArtifact.turns members must be VoiceTurn"
                )
            turn.validate()
            if turn.turn_id in seen:
                raise UIIRValidationError(f"Duplicate turn id: {turn.turn_id}")
            seen.add(turn.turn_id)
        _require_tuple(
            "VoiceProjectionArtifact.channel_status", self.channel_status
        )
        for status in self.channel_status:
            if not isinstance(status, ChannelStatus):
                raise UIIRValidationError(
                    "channel_status members must be ChannelStatus"
                )
            status.validate()
        self.loss_report.validate()
        if not isinstance(self.base_artifact, UIProjectionArtifact):
            raise UIIRValidationError(
                "VoiceProjectionArtifact.base_artifact must be UIProjectionArtifact"
            )
        self.base_artifact.validate()
        if self.schema_version != UI_VOICE_ARTIFACT_SCHEMA_VERSION:
            raise UIIRValidationError(
                f"Unsupported voice projection schema_version: "
                f"{self.schema_version!r}"
            )
        if self.interface != UI_VOICE_PROJECTION_INTERFACE:
            raise UIIRValidationError(
                f"Unexpected voice projection interface: {self.interface!r}"
            )
        if self.renderer != "neutral":
            raise UIIRValidationError(
                "VoiceProjectionArtifact.renderer must be 'neutral' "
                "(no TTS/engine binding in projection)"
            )
        if not isinstance(self.interruption_default, InterruptionPolicy):
            raise UIIRValidationError(
                "VoiceProjectionArtifact.interruption_default must be "
                "an InterruptionPolicy"
            )
        _require_tuple(
            "VoiceProjectionArtifact.dialogue_order", self.dialogue_order
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
            "base_artifact": self.base_artifact.to_dict(),
            "channel_status": [
                item.to_dict()
                for item in sorted(
                    self.channel_status, key=lambda c: c.channel.value
                )
            ],
            "dialogue_order": list(self.dialogue_order),
            "document_id": self.document_id,
            "interface": self.interface,
            "interruption_default": self.interruption_default.value,
            "loss_report": self.loss_report.to_dict(),
            "problem_id": self.problem_id,
            "profile_id": self.profile_id,
            "renderer": self.renderer,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "turns": [turn.to_dict() for turn in self.turns],
        }


@dataclass(frozen=True, slots=True)
class HeadlessProjectionArtifact:
    """Deterministic agent-structured projection without visual/TTS rendering.

    Interface identity: ``UIIRHeadlessProjection@1``.
    """

    artifact_id: str
    status: ProjectionStatus
    profile_id: str
    problem_id: str
    steps: tuple[HeadlessStep, ...]
    channel_status: tuple[ChannelStatus, ...]
    loss_report: ProjectionLossReport
    base_artifact: UIProjectionArtifact
    document_id: str = ""
    step_order: tuple[str, ...] = ()
    interruption_default: InterruptionPolicy = InterruptionPolicy.ALLOW
    schema_version: str = UI_HEADLESS_ARTIFACT_SCHEMA_VERSION
    interface: str = UI_HEADLESS_PROJECTION_INTERFACE
    renderer: str = "neutral"

    def validate(self) -> "HeadlessProjectionArtifact":
        _validate_identifier(
            "HeadlessProjectionArtifact.artifact_id", self.artifact_id
        )
        if not isinstance(self.status, ProjectionStatus):
            raise UIIRValidationError(
                "HeadlessProjectionArtifact.status must be a ProjectionStatus"
            )
        _validate_non_empty_string(
            "HeadlessProjectionArtifact.profile_id", self.profile_id
        )
        _validate_non_empty_string(
            "HeadlessProjectionArtifact.problem_id", self.problem_id
        )
        _require_tuple("HeadlessProjectionArtifact.steps", self.steps)
        seen: set[str] = set()
        for step in self.steps:
            if not isinstance(step, HeadlessStep):
                raise UIIRValidationError(
                    "HeadlessProjectionArtifact.steps members must be HeadlessStep"
                )
            step.validate()
            if step.step_id in seen:
                raise UIIRValidationError(f"Duplicate step id: {step.step_id}")
            seen.add(step.step_id)
        _require_tuple(
            "HeadlessProjectionArtifact.channel_status", self.channel_status
        )
        for status in self.channel_status:
            if not isinstance(status, ChannelStatus):
                raise UIIRValidationError(
                    "channel_status members must be ChannelStatus"
                )
            status.validate()
        self.loss_report.validate()
        if not isinstance(self.base_artifact, UIProjectionArtifact):
            raise UIIRValidationError(
                "HeadlessProjectionArtifact.base_artifact must be UIProjectionArtifact"
            )
        self.base_artifact.validate()
        if self.schema_version != UI_HEADLESS_ARTIFACT_SCHEMA_VERSION:
            raise UIIRValidationError(
                f"Unsupported headless projection schema_version: "
                f"{self.schema_version!r}"
            )
        if self.interface != UI_HEADLESS_PROJECTION_INTERFACE:
            raise UIIRValidationError(
                f"Unexpected headless projection interface: {self.interface!r}"
            )
        if self.renderer != "neutral":
            raise UIIRValidationError(
                "HeadlessProjectionArtifact.renderer must be 'neutral'"
            )
        if not isinstance(self.interruption_default, InterruptionPolicy):
            raise UIIRValidationError(
                "HeadlessProjectionArtifact.interruption_default must be "
                "an InterruptionPolicy"
            )
        _require_tuple("HeadlessProjectionArtifact.step_order", self.step_order)
        return self

    def digest(self) -> str:
        text = json.dumps(
            self.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "base_artifact": self.base_artifact.to_dict(),
            "channel_status": [
                item.to_dict()
                for item in sorted(
                    self.channel_status, key=lambda c: c.channel.value
                )
            ],
            "document_id": self.document_id,
            "interface": self.interface,
            "interruption_default": self.interruption_default.value,
            "loss_report": self.loss_report.to_dict(),
            "problem_id": self.problem_id,
            "profile_id": self.profile_id,
            "renderer": self.renderer,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "step_order": list(self.step_order),
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(frozen=True, slots=True)
class VoiceProjectionOptions:
    """Optional voice-specific presentation knobs (still renderer-neutral)."""

    audio_available: bool = True
    display_available: bool = False
    prefer_captions: bool = True
    prefer_transcripts: bool = True
    interruption_default: InterruptionPolicy = InterruptionPolicy.ALLOW
    max_choices_announced: int = 6
    include_accessible_name_prefix: bool = True

    def validate(self) -> "VoiceProjectionOptions":
        for name in (
            "audio_available",
            "display_available",
            "prefer_captions",
            "prefer_transcripts",
            "include_accessible_name_prefix",
        ):
            if not isinstance(getattr(self, name), bool):
                raise UIIRValidationError(
                    f"VoiceProjectionOptions.{name} must be a boolean"
                )
        if not isinstance(self.interruption_default, InterruptionPolicy):
            raise UIIRValidationError(
                "VoiceProjectionOptions.interruption_default must be "
                "an InterruptionPolicy"
            )
        if (
            not isinstance(self.max_choices_announced, int)
            or isinstance(self.max_choices_announced, bool)
            or self.max_choices_announced < 1
        ):
            raise UIIRValidationError(
                "VoiceProjectionOptions.max_choices_announced must be a "
                "positive integer"
            )
        return self


@dataclass(frozen=True, slots=True)
class HeadlessProjectionOptions:
    """Optional headless presentation knobs."""

    agent_structured_available: bool = True
    display_available: bool = False
    audio_available: bool = False
    interruption_default: InterruptionPolicy = InterruptionPolicy.ALLOW
    include_state_envelope: bool = True

    def validate(self) -> "HeadlessProjectionOptions":
        for name in (
            "agent_structured_available",
            "display_available",
            "audio_available",
            "include_state_envelope",
        ):
            if not isinstance(getattr(self, name), bool):
                raise UIIRValidationError(
                    f"HeadlessProjectionOptions.{name} must be a boolean"
                )
        if not isinstance(self.interruption_default, InterruptionPolicy):
            raise UIIRValidationError(
                "HeadlessProjectionOptions.interruption_default must be "
                "an InterruptionPolicy"
            )
        return self


def _resolve_problem(
    source: UIIRDocument | Mapping[str, Any] | ProjectionProblem | UIProjectionArtifact,
) -> tuple[ProjectionProblem | None, UIProjectionArtifact | None]:
    if isinstance(source, UIProjectionArtifact):
        return None, source
    if isinstance(source, ProjectionProblem):
        return source.validate(), None
    if isinstance(source, (UIIRDocument, Mapping)):
        return projection_problem_from_document(source), None
    raise UIIRValidationError(
        "voice/headless projection expects UIIRDocument, mapping, "
        "ProjectionProblem, or UIProjectionArtifact"
    )


def _solve_base(
    source: UIIRDocument | Mapping[str, Any] | ProjectionProblem | UIProjectionArtifact,
    profile: UIDeviceProfile,
    policy: ProjectionPolicy | None,
) -> tuple[ProjectionProblem, UIProjectionArtifact]:
    problem, existing = _resolve_problem(source)
    if existing is not None:
        # Reconstruct a minimal problem shell for item metadata when only an
        # artifact is provided (items recovered from nodes + labels).
        items = tuple(
            ProjectionItem(
                item_id=node.item_id,
                semantic_kind=node.semantic_kind,
                mandatory=node.mandatory,
                fallback_ref=node.fallback_ref,
                component_id=node.component_id,
                label=node.label,
                priority=node.order,
            )
            for node in existing.nodes
        )
        if not items:
            raise UIIRValidationError(
                "UIProjectionArtifact has no nodes to project to voice/headless"
            )
        problem = ProjectionProblem(
            problem_id=existing.problem_id,
            items=items,
            document_id=existing.document_id,
        ).validate()
        return problem, existing.validate()
    assert problem is not None
    artifact = solve_projection(problem, profile, policy)
    return problem, artifact


def _items_by_id(problem: ProjectionProblem) -> dict[str, ProjectionItem]:
    return {item.item_id: item for item in problem.items}


def _node_by_id(artifact: UIProjectionArtifact) -> dict[str, ProjectedNode]:
    return {node.item_id: node for node in artifact.nodes}


def _sort_items_for_dialogue(
    items: Sequence[ProjectionItem],
) -> list[ProjectionItem]:
    def key(item: ProjectionItem) -> tuple[int, int, str]:
        kind_rank = _KIND_ORDER.get(item.semantic_kind, 50)
        return (kind_rank, item.priority, item.item_id)

    return sorted(items, key=key)


def _choice_options_for(
    item: ProjectionItem,
    *,
    max_choices: int,
) -> tuple[VoiceChoiceOption, ...]:
    """Derive choice options from label/details conventions.

    Labels of the form ``"A|B|C"`` or details prefixed with ``choice:`` expand
    into options. Otherwise a single option mirrors the item label.
    """

    options: list[VoiceChoiceOption] = []
    if "|" in (item.label or ""):
        parts = [part.strip() for part in item.label.split("|") if part.strip()]
        for index, part in enumerate(parts[:max_choices]):
            option_id = f"{item.item_id}:opt:{index + 1}"
            options.append(
                VoiceChoiceOption(
                    option_id=option_id,
                    label=part,
                    utterance_hints=(part.lower(), str(index + 1)),
                    cancelable=True,
                )
            )
    if options:
        return tuple(options)
    # Single implicit option for choice kinds without expanded labels.
    if item.semantic_kind == "choice":
        return (
            VoiceChoiceOption(
                option_id=f"{item.item_id}:opt:1",
                label=item.label or item.item_id,
                utterance_hints=((item.label or item.item_id).lower(), "1"),
                cancelable=True,
            ),
        )
    return ()


def _build_channel_status_voice(
    profile: UIDeviceProfile,
    options: VoiceProjectionOptions,
) -> tuple[ChannelStatus, ...]:
    available = set(profile.available_capability_ids)
    statuses: list[ChannelStatus] = []

    audio_on_profile = "audio" in available or "speech_output" in available
    if options.audio_available and audio_on_profile:
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.AUDIO,
                availability=ChannelAvailability.AVAILABLE,
                reason="audio/speech_output capability present",
            )
        )
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.SPEECH_OUTPUT,
                availability=ChannelAvailability.AVAILABLE,
                reason="speech_output or audio capability present",
            )
        )
    else:
        reason = (
            "audio unavailable: no audio/speech_output capability on profile"
            if not audio_on_profile
            else "audio unavailable: caller marked audio_available=false"
        )
        # Fallback to transcript/caption/agent_structured.
        fallback = ChannelKind.TRANSCRIPT
        if "agent_structured" in available:
            fallback = ChannelKind.AGENT_STRUCTURED
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.AUDIO,
                availability=ChannelAvailability.UNAVAILABLE,
                fallback_channel=fallback,
                reason=reason,
            )
        )
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.SPEECH_OUTPUT,
                availability=ChannelAvailability.FALLBACK,
                fallback_channel=fallback,
                reason=f"{reason}; using {fallback.value}",
            )
        )

    if options.display_available and "display" in available:
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.DISPLAY,
                availability=ChannelAvailability.AVAILABLE,
                reason="display capability present and enabled",
            )
        )
    else:
        reason = (
            "display unavailable: voice profile has no display capability"
            if "display" not in available
            else "display unavailable: caller marked display_available=false"
        )
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.DISPLAY,
                availability=ChannelAvailability.UNAVAILABLE,
                fallback_channel=ChannelKind.CAPTION
                if options.prefer_captions
                else ChannelKind.TRANSCRIPT,
                reason=reason,
            )
        )

    # Transcripts and captions are always materialised as text channels.
    statuses.append(
        ChannelStatus(
            channel=ChannelKind.TRANSCRIPT,
            availability=(
                ChannelAvailability.AVAILABLE
                if options.prefer_transcripts
                else ChannelAvailability.DEGRADED
            ),
            reason=(
                "transcripts preserved for accessibility and audit"
                if options.prefer_transcripts
                else "transcripts degraded by option"
            ),
        )
    )
    statuses.append(
        ChannelStatus(
            channel=ChannelKind.CAPTION,
            availability=(
                ChannelAvailability.AVAILABLE
                if options.prefer_captions
                else ChannelAvailability.DEGRADED
            ),
            reason=(
                "captions preserved as text fallback for speech"
                if options.prefer_captions
                else "captions degraded by option"
            ),
        )
    )

    if "agent_structured" in available:
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.AGENT_STRUCTURED,
                availability=ChannelAvailability.AVAILABLE,
                reason="agent_structured capability present",
            )
        )
    if "fallback" in available:
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.FALLBACK,
                availability=ChannelAvailability.AVAILABLE,
                reason="generic fallback capability present",
            )
        )
    return tuple(statuses)


def _build_channel_status_headless(
    profile: UIDeviceProfile,
    options: HeadlessProjectionOptions,
) -> tuple[ChannelStatus, ...]:
    available = set(profile.available_capability_ids)
    statuses: list[ChannelStatus] = []

    if options.agent_structured_available and "agent_structured" in available:
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.AGENT_STRUCTURED,
                availability=ChannelAvailability.AVAILABLE,
                reason="agent_structured capability present",
            )
        )
    else:
        reason = (
            "agent_structured unavailable on profile"
            if "agent_structured" not in available
            else "agent_structured unavailable: caller marked unavailable"
        )
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.AGENT_STRUCTURED,
                availability=ChannelAvailability.UNAVAILABLE,
                fallback_channel=ChannelKind.FALLBACK
                if "fallback" in available
                else ChannelKind.NOTIFICATION,
                reason=reason,
            )
        )

    if options.display_available and "display" in available:
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.DISPLAY,
                availability=ChannelAvailability.AVAILABLE,
                reason="display capability present and enabled",
            )
        )
    else:
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.DISPLAY,
                availability=ChannelAvailability.UNAVAILABLE,
                fallback_channel=ChannelKind.AGENT_STRUCTURED,
                reason=(
                    "display unavailable for headless projection; "
                    "agent-structured sequence is the primary surface"
                ),
            )
        )

    if options.audio_available and (
        "audio" in available or "speech_output" in available
    ):
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.AUDIO,
                availability=ChannelAvailability.AVAILABLE,
                reason="audio capability present and enabled",
            )
        )
    else:
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.AUDIO,
                availability=ChannelAvailability.UNAVAILABLE,
                fallback_channel=ChannelKind.AGENT_STRUCTURED,
                reason=(
                    "audio unavailable for headless projection; "
                    "structured steps do not require speech"
                ),
            )
        )

    if "notification" in available:
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.NOTIFICATION,
                availability=ChannelAvailability.AVAILABLE,
                reason="notification capability present",
            )
        )
    if "fallback" in available:
        statuses.append(
            ChannelStatus(
                channel=ChannelKind.FALLBACK,
                availability=ChannelAvailability.AVAILABLE,
                reason="generic fallback capability present",
            )
        )
    return tuple(statuses)


def _channel_losses(
    channel_status: Sequence[ChannelStatus],
    *,
    prefix: str,
) -> list[ProjectionLoss]:
    losses: list[ProjectionLoss] = []
    for status in channel_status:
        if status.availability is ChannelAvailability.AVAILABLE:
            continue
        if status.availability is ChannelAvailability.UNAVAILABLE:
            category = LossCategory.FALLBACK if status.fallback_channel else LossCategory.UNSUPPORTED
            losses.append(
                make_loss(
                    loss_id=f"loss:{prefix}:channel:{status.channel.value}",
                    semantic_id=f"channel:{status.channel.value}",
                    semantic_kind="channel",
                    category=category,
                    reason=status.reason
                    or f"{status.channel.value} unavailable",
                    mandatory=False,
                    adaptation_policy=AdaptationPolicy.FALLBACK,
                    fallback_ref=(
                        status.fallback_channel.value
                        if status.fallback_channel
                        else ""
                    ),
                    details=(status.availability.value,),
                )
            )
        elif status.availability is ChannelAvailability.FALLBACK:
            losses.append(
                make_loss(
                    loss_id=f"loss:{prefix}:channel-fallback:{status.channel.value}",
                    semantic_id=f"channel:{status.channel.value}",
                    semantic_kind="channel",
                    category=LossCategory.FALLBACK,
                    reason=status.reason or f"{status.channel.value} on fallback",
                    mandatory=False,
                    adaptation_policy=AdaptationPolicy.FALLBACK,
                    fallback_ref=(
                        status.fallback_channel.value
                        if status.fallback_channel
                        else "fallback"
                    ),
                )
            )
        elif status.availability is ChannelAvailability.DEGRADED:
            losses.append(
                make_loss(
                    loss_id=f"loss:{prefix}:channel-degraded:{status.channel.value}",
                    semantic_id=f"channel:{status.channel.value}",
                    semantic_kind="channel",
                    category=LossCategory.DEGRADED,
                    reason=status.reason or f"{status.channel.value} degraded",
                    mandatory=False,
                    adaptation_policy=AdaptationPolicy.ADAPT,
                )
            )
    return losses


def _turn_from_item(
    item: ProjectionItem,
    node: ProjectedNode,
    *,
    order: int,
    options: VoiceProjectionOptions,
    audio_available: bool,
) -> VoiceTurn | None:
    if node.disposition not in _PRESENTED_DISPOSITIONS:
        return None

    kind = _SEMANTIC_TO_VOICE_TURN.get(item.semantic_kind, VoiceTurnKind.ANNOUNCEMENT)
    role = _SEMANTIC_TO_DIALOGUE_ROLE.get(item.semantic_kind, DialogueRole.SYSTEM)
    summarized = node.disposition is PresentationDisposition.SUMMARIZED
    speech = _speech_text(item, summarized=summarized)
    accessible_name = item.label or item.item_id
    if (
        options.include_accessible_name_prefix
        and item.semantic_kind == MandatorySemanticKind.ACCESSIBILITY.value
    ):
        accessible_name = item.label or item.item_id

    choices = ()
    if item.semantic_kind == "choice" or kind is VoiceTurnKind.CHOICE:
        choices = _choice_options_for(
            item, max_choices=options.max_choices_announced
        )
        if choices:
            listed = "; ".join(
                f"{index + 1}: {opt.label}" for index, opt in enumerate(choices)
            )
            speech = f"{speech} Options: {listed}."

    caption = _caption_text(speech)
    transcript = _transcript_text(speech, role=role, order=order)

    # When audio is unavailable, speech still carries text for TTS-less clients
    # and captions/transcripts remain the accessible surface.
    details: list[str] = []
    if not audio_available:
        details.append("audio_unavailable:delivered_as_text_transcript_caption")
    if node.disposition is PresentationDisposition.FALLBACK:
        details.append(f"fallback:{node.fallback_ref or item.fallback_ref}")

    cancelable = item.semantic_kind in {
        "cancellation",
        MandatorySemanticKind.CONFIRMATION.value,
        "choice",
        MandatorySemanticKind.ACTION.value,
    }
    requires_confirmation = item.semantic_kind in {
        MandatorySemanticKind.CONFIRMATION.value,
        MandatorySemanticKind.CONSENT.value,
    }
    consequence_ref = ""
    recovery_ref = ""
    if item.semantic_kind == MandatorySemanticKind.CONSEQUENCE.value:
        consequence_ref = item.item_id
    if item.semantic_kind == "recovery":
        recovery_ref = item.item_id

    return VoiceTurn(
        turn_id=f"turn:{item.item_id}",
        kind=kind,
        role=role,
        order=order,
        speech_text=speech,
        transcript=transcript,
        caption=caption,
        semantic_id=item.item_id,
        semantic_kind=item.semantic_kind,
        mandatory=_item_is_mandatory(item),
        disposition=node.disposition,
        urgency=_urgency_for(item.semantic_kind),
        interruption_policy=_interruption_for(
            item.semantic_kind, options.interruption_default
            if item.semantic_kind not in _DEFAULT_INTERRUPTION_FOR_KIND
            else None
        ),
        accessible_name=accessible_name,
        choices=choices,
        cancelable=cancelable,
        requires_confirmation=requires_confirmation,
        consequence_ref=consequence_ref,
        recovery_ref=recovery_ref,
        fallback_ref=node.fallback_ref or item.fallback_ref,
        component_id=item.component_id or node.component_id,
        ambiguity_group=(
            f"ambiguity:{item.item_id}" if item.semantic_kind == "choice" else ""
        ),
        details=tuple(details),
    )


def _step_from_item(
    item: ProjectionItem,
    node: ProjectedNode,
    *,
    order: int,
    options: HeadlessProjectionOptions,
) -> HeadlessStep | None:
    if node.disposition not in _PRESENTED_DISPOSITIONS:
        return None

    kind = _SEMANTIC_TO_HEADLESS_STEP.get(item.semantic_kind, HeadlessStepKind.STATE)
    message = item.label or item.item_id
    choice_ids: tuple[str, ...] = ()
    if item.semantic_kind == "choice":
        options_voice = _choice_options_for(item, max_choices=12)
        choice_ids = tuple(opt.option_id for opt in options_voice)
        payload_choices = [opt.to_dict() for opt in options_voice]
    else:
        payload_choices = []

    payload: dict[str, Any] = {
        "component_id": item.component_id or node.component_id,
        "disposition": node.disposition.value,
        "label": message,
        "semantic_id": item.item_id,
        "semantic_kind": item.semantic_kind,
    }
    if payload_choices:
        payload["choices"] = payload_choices
    if item.fallback_ref or node.fallback_ref:
        payload["fallback_ref"] = node.fallback_ref or item.fallback_ref
    if options.include_state_envelope:
        payload["state"] = {
            "cancelable": item.semantic_kind
            in {
                "cancellation",
                MandatorySemanticKind.CONFIRMATION.value,
                "choice",
                MandatorySemanticKind.ACTION.value,
            },
            "requires_confirmation": item.semantic_kind
            in {
                MandatorySemanticKind.CONFIRMATION.value,
                MandatorySemanticKind.CONSENT.value,
            },
            "urgency": _urgency_for(item.semantic_kind).value,
            "interruption_policy": _interruption_for(item.semantic_kind).value,
        }

    return HeadlessStep(
        step_id=f"step:{item.item_id}",
        kind=kind,
        order=order,
        payload=payload,
        semantic_id=item.item_id,
        semantic_kind=item.semantic_kind,
        mandatory=_item_is_mandatory(item),
        disposition=node.disposition,
        urgency=_urgency_for(item.semantic_kind),
        interruption_policy=_interruption_for(item.semantic_kind),
        accessible_name=item.label or item.item_id,
        choice_ids=choice_ids,
        cancelable=item.semantic_kind
        in {
            "cancellation",
            MandatorySemanticKind.CONFIRMATION.value,
            "choice",
            MandatorySemanticKind.ACTION.value,
        },
        requires_confirmation=item.semantic_kind
        in {
            MandatorySemanticKind.CONFIRMATION.value,
            MandatorySemanticKind.CONSENT.value,
        },
        consequence_ref=(
            item.item_id
            if item.semantic_kind == MandatorySemanticKind.CONSEQUENCE.value
            else ""
        ),
        recovery_ref=item.item_id if item.semantic_kind == "recovery" else "",
        fallback_ref=node.fallback_ref or item.fallback_ref,
        component_id=item.component_id or node.component_id,
        message=message,
    )


def _collect_mandatory_map(
    problem: ProjectionProblem,
) -> dict[str, str]:
    return {
        item.item_id: item.semantic_kind
        for item in problem.items
        if _item_is_mandatory(item)
    }


def project_voice(
    source: UIIRDocument | Mapping[str, Any] | ProjectionProblem | UIProjectionArtifact,
    profile: UIDeviceProfile | None = None,
    policy: ProjectionPolicy | None = None,
    options: VoiceProjectionOptions | None = None,
) -> VoiceProjectionArtifact:
    """Project UI semantics into a renderer-neutral voice/audio dialogue.

    Preserves accessible names, consequences, choices, cancellation,
    confirmation, pending/result/error/recovery, transcripts/captions, urgency,
    and interruption policy. Unavailable audio or display is reported
    explicitly on ``channel_status`` with fallback receipts.
    """

    options = (options or VoiceProjectionOptions()).validate()
    profile = validate_device_profile(profile or voice_profile())
    if profile.family not in {ProfileFamily.VOICE, ProfileFamily.CUSTOM}:
        # Allow CUSTOM for tests; warn via loss when not voice-family.
        pass

    problem, base = _solve_base(source, profile, policy)
    items = _items_by_id(problem)
    nodes = _node_by_id(base)
    channel_status = _build_channel_status_voice(profile, options)
    audio_available = any(
        s.channel in {ChannelKind.AUDIO, ChannelKind.SPEECH_OUTPUT}
        and s.availability is ChannelAvailability.AVAILABLE
        for s in channel_status
    )

    ordered_items = _sort_items_for_dialogue(problem.items)
    turns: list[VoiceTurn] = []
    order = 0
    for item in ordered_items:
        node = nodes.get(item.item_id)
        if node is None:
            continue
        turn = _turn_from_item(
            item,
            node,
            order=order,
            options=options,
            audio_available=audio_available,
        )
        if turn is None:
            continue
        turns.append(turn)
        order += 1

    # Extra channel losses + base loss report merge.
    extra_losses = _channel_losses(channel_status, prefix="voice")
    # If audio is unavailable, ensure every presented mandatory still has
    # transcript/caption (already required on VoiceTurn) and emit a single
    # explicit fallback receipt for the audio surface.
    if not audio_available and turns:
        extra_losses.append(
            make_loss(
                loss_id="loss:voice:audio-text-fallback",
                semantic_id="channel:audio",
                semantic_kind="channel",
                category=LossCategory.FALLBACK,
                reason=(
                    "Audio unavailable; mandatory dialogue delivered via "
                    "transcript and caption text channels"
                ),
                mandatory=False,
                adaptation_policy=AdaptationPolicy.FALLBACK,
                fallback_ref="transcript+caption",
            )
        )

    merged = merge_loss_reports(
        report_id=f"loss-report:voice:{problem.problem_id}:{profile.profile_id}",
        reports=(
            base.loss_report,
            build_loss_report(
                report_id=f"loss-report:voice-channels:{problem.problem_id}",
                losses=extra_losses,
            ),
        ),
    )

    preserved_ids = [turn.semantic_id for turn in turns]
    # Also count unsatisfiable/omitted via base losses as explicit handling.
    assert_no_silent_mandatory_omission(
        _collect_mandatory_map(problem),
        merged.losses,
        preserved_ids,
    )

    dialogue_order = tuple(turn.turn_id for turn in turns)
    artifact = VoiceProjectionArtifact(
        artifact_id=f"voice:{problem.problem_id}:{profile.profile_id}",
        status=base.status,
        profile_id=profile.profile_id,
        problem_id=problem.problem_id,
        turns=tuple(turns),
        channel_status=channel_status,
        loss_report=merged,
        base_artifact=base,
        document_id=problem.document_id or base.document_id,
        dialogue_order=dialogue_order,
        interruption_default=options.interruption_default,
    )
    return artifact.validate()


def project_headless(
    source: UIIRDocument | Mapping[str, Any] | ProjectionProblem | UIProjectionArtifact,
    profile: UIDeviceProfile | None = None,
    policy: ProjectionPolicy | None = None,
    options: HeadlessProjectionOptions | None = None,
) -> HeadlessProjectionArtifact:
    """Project UI semantics into an agent-readable structured sequence.

    Same mandatory semantics as voice, without speech rendering. Display and
    audio unavailability are reported explicitly; agent_structured is primary.
    """

    options = (options or HeadlessProjectionOptions()).validate()
    profile = validate_device_profile(profile or headless_profile())
    problem, base = _solve_base(source, profile, policy)
    items = _items_by_id(problem)
    nodes = _node_by_id(base)
    channel_status = _build_channel_status_headless(profile, options)

    ordered_items = _sort_items_for_dialogue(problem.items)
    steps: list[HeadlessStep] = []
    order = 0
    for item in ordered_items:
        node = nodes.get(item.item_id)
        if node is None:
            continue
        step = _step_from_item(item, node, order=order, options=options)
        if step is None:
            continue
        steps.append(step)
        order += 1

    extra_losses = _channel_losses(channel_status, prefix="headless")
    agent_ok = any(
        s.channel is ChannelKind.AGENT_STRUCTURED
        and s.availability is ChannelAvailability.AVAILABLE
        for s in channel_status
    )
    if not agent_ok:
        # Without agent_structured, mandatory content is unsatisfiable for
        # headless unless a fallback channel exists.
        has_fallback = any(
            s.availability
            in {ChannelAvailability.AVAILABLE, ChannelAvailability.FALLBACK}
            and s.channel
            in {ChannelKind.FALLBACK, ChannelKind.NOTIFICATION, ChannelKind.AUDIO}
            for s in channel_status
        )
        if not has_fallback:
            for item in problem.items:
                if not _item_is_mandatory(item):
                    continue
                if any(step.semantic_id == item.item_id for step in steps):
                    continue
                extra_losses.append(
                    make_loss(
                        loss_id=f"loss:headless:unsat:{item.item_id}",
                        semantic_id=item.item_id,
                        semantic_kind=item.semantic_kind,
                        category=LossCategory.UNSATISFIABLE,
                        reason=(
                            "Mandatory semantic cannot project headless without "
                            "agent_structured or fallback channel"
                        ),
                        mandatory=True,
                        adaptation_policy=item.adaptation_policy,
                    )
                )

    merged = merge_loss_reports(
        report_id=f"loss-report:headless:{problem.problem_id}:{profile.profile_id}",
        reports=(
            base.loss_report,
            build_loss_report(
                report_id=f"loss-report:headless-channels:{problem.problem_id}",
                losses=extra_losses,
            ),
        ),
    )

    preserved_ids = [step.semantic_id for step in steps]
    assert_no_silent_mandatory_omission(
        _collect_mandatory_map(problem),
        merged.losses,
        preserved_ids,
    )

    # Elevate status if we introduced unsatisfiable channel losses.
    status = base.status
    if merged.has_unsatisfiable:
        status = ProjectionStatus.UNSATISFIABLE
    elif any(
        loss.category is LossCategory.FALLBACK for loss in extra_losses
    ) and status is ProjectionStatus.SATISFIED:
        status = ProjectionStatus.FALLBACK

    step_order = tuple(step.step_id for step in steps)
    artifact = HeadlessProjectionArtifact(
        artifact_id=f"headless:{problem.problem_id}:{profile.profile_id}",
        status=status,
        profile_id=profile.profile_id,
        problem_id=problem.problem_id,
        steps=tuple(steps),
        channel_status=channel_status,
        loss_report=merged,
        base_artifact=base,
        document_id=problem.document_id or base.document_id,
        step_order=step_order,
        interruption_default=options.interruption_default,
    )
    return artifact.validate()


class UIIRVoiceProjection:
    """Reference voice projection implementing UIIRVoiceProjection@1."""

    interface: str = UI_VOICE_PROJECTION_INTERFACE

    def project(
        self,
        source: UIIRDocument
        | Mapping[str, Any]
        | ProjectionProblem
        | UIProjectionArtifact,
        profile: UIDeviceProfile | None = None,
        policy: ProjectionPolicy | None = None,
        options: VoiceProjectionOptions | None = None,
    ) -> VoiceProjectionArtifact:
        return project_voice(source, profile, policy, options)


class UIIRHeadlessProjection:
    """Reference headless projection implementing UIIRHeadlessProjection@1."""

    interface: str = UI_HEADLESS_PROJECTION_INTERFACE

    def project(
        self,
        source: UIIRDocument
        | Mapping[str, Any]
        | ProjectionProblem
        | UIProjectionArtifact,
        profile: UIDeviceProfile | None = None,
        policy: ProjectionPolicy | None = None,
        options: HeadlessProjectionOptions | None = None,
    ) -> HeadlessProjectionArtifact:
        return project_headless(source, profile, policy, options)


def voice_dialogue_problem(
    *,
    problem_id: str = "problem:voice-dialogue",
    document_id: str = "doc:voice-dialogue",
) -> ProjectionProblem:
    """Reference dialogue problem covering acceptance semantics for tests/demos.

    Includes accessible name, consequence, choices, cancellation, confirmation,
    pending, result, error, recovery, feedback, and action — all with audio/
    speech fallbacks suitable for the voice profile.
    """

    def _item(
        item_id: str,
        kind: str,
        label: str,
        *,
        priority: int,
        mandatory: bool = True,
        action_cost: int = 0,
        text_chars: int = 40,
    ) -> ProjectionItem:
        return ProjectionItem(
            item_id=item_id,
            semantic_kind=kind,
            mandatory=mandatory,
            required_capability_ids=("display",),
            alternative_capability_ids=("audio", "speech_output"),
            fallback_capability_ids=("audio", "speech_output", "agent_structured"),
            fallback_ref=f"fallback:audio:{item_id}",
            adaptation_policy=AdaptationPolicy.FALLBACK,
            action_cost=action_cost,
            text_chars=text_chars,
            attention_cost=4 if mandatory else 1,
            field_of_view_share=0,
            safe_area_share=0,
            priority=priority,
            label=label,
            component_id=f"cmp:{item_id}",
        )

    return ProjectionProblem(
        problem_id=problem_id,
        document_id=document_id,
        items=(
            _item(
                "a11y_name",
                MandatorySemanticKind.ACCESSIBILITY.value,
                "Delete account control",
                priority=1,
                text_chars=24,
            ),
            _item(
                "task_delete",
                "task",
                "Delete account",
                priority=5,
                text_chars=20,
            ),
            _item(
                "prompt_intent",
                "prompt",
                "Do you want to permanently delete your account?",
                priority=10,
                text_chars=60,
            ),
            _item(
                "consequence_irrevocable",
                MandatorySemanticKind.CONSEQUENCE.value,
                "This permanently removes your data and cannot be undone",
                priority=15,
                text_chars=70,
            ),
            _item(
                "choice_method",
                "choice",
                "Delete now|Schedule deletion|Keep account",
                priority=20,
                text_chars=48,
                action_cost=1,
            ),
            _item(
                "confirm_delete",
                MandatorySemanticKind.CONFIRMATION.value,
                "Confirm permanent account deletion",
                priority=25,
                text_chars=40,
                action_cost=1,
            ),
            _item(
                "cancel_flow",
                "cancellation",
                "Cancel and keep your account",
                priority=26,
                text_chars=32,
                action_cost=1,
            ),
            _item(
                "action_submit",
                MandatorySemanticKind.ACTION.value,
                "Submit deletion request",
                priority=30,
                text_chars=28,
                action_cost=1,
            ),
            _item(
                "pending_delete",
                "pending",
                "Deletion request is being processed",
                priority=35,
                text_chars=40,
            ),
            _item(
                "result_success",
                "result",
                "Account scheduled for deletion",
                priority=40,
                text_chars=36,
            ),
            _item(
                "error_surface",
                MandatorySemanticKind.ERROR.value,
                "Deletion failed due to an active subscription",
                priority=45,
                text_chars=52,
            ),
            _item(
                "recovery_path",
                "recovery",
                "Cancel subscription then retry deletion",
                priority=50,
                text_chars=48,
                action_cost=1,
            ),
            _item(
                "feedback_live",
                MandatorySemanticKind.FEEDBACK.value,
                "Live status updates are available",
                priority=55,
                text_chars=36,
            ),
        ),
    ).validate()


__all__ = [
    "ChannelAvailability",
    "ChannelKind",
    "ChannelStatus",
    "DialogueRole",
    "HeadlessProjectionArtifact",
    "HeadlessProjectionOptions",
    "HeadlessStep",
    "HeadlessStepKind",
    "InterruptionPolicy",
    "UI_HEADLESS_ARTIFACT_SCHEMA_VERSION",
    "UI_HEADLESS_PROJECTION_INTERFACE",
    "UI_VOICE_ARTIFACT_SCHEMA_VERSION",
    "UI_VOICE_PROJECTION_INTERFACE",
    "UIIRHeadlessProjection",
    "UIIRVoiceProjection",
    "UrgencyClass",
    "VoiceChoiceOption",
    "VoiceProjectionArtifact",
    "VoiceProjectionOptions",
    "VoiceTurn",
    "VoiceTurnKind",
    "project_headless",
    "project_voice",
    "voice_dialogue_problem",
]
