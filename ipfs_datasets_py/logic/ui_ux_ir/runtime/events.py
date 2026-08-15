"""Canonical interaction event envelope (UIR-050)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping

from ..schema import UIIRValidationError

UI_RUNTIME_EVENT_INTERFACE: Final = "UIRuntimeEvent@1"


class EventProvenance(str, Enum):
    HUMAN = "human"
    SYNTHETIC = "synthetic"
    AGENT = "agent"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class EventKind(str, Enum):
    ACTIVATE = "activate"
    FOCUS = "focus"
    BLUR = "blur"
    SELECT = "select"
    INPUT_VALUE = "input_value"
    CANCEL = "cancel"
    CONFIRM = "confirm"
    NAVIGATE = "navigate"
    HOVER = "hover"
    SCROLL = "scroll"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class CanonicalInteractionEvent:
    """Bounded canonical event; raw payload is never authority."""

    event_id: str
    kind: EventKind
    target_component_id: str
    timestamp_ms: int
    provenance: EventProvenance
    capability_id: str
    consent_ok: bool
    sequence: int = 0
    confidence: float | None = None
    raw_payload: Mapping[str, Any] = MappingProxyType({})
    source_adapter: str = ""
    schema_version: str = "ui-runtime-event/v1"


MAX_RAW_PAYLOAD_BYTES: Final = 4096
_FORBIDDEN_RAW_KEYS: Final = frozenset(
    {
        "authorization",
        "authority",
        "grant",
        "password",
        "secret",
        "token",
        "private_key",
        "raw_emg",
        "continuous_neural",
    }
)


def _payload_size(payload: Mapping[str, Any]) -> int:
    # Approximate UTF-8 size of a compact JSON-like representation.
    return len(repr(dict(payload)).encode("utf-8", errors="replace"))


def validate_event(event: CanonicalInteractionEvent) -> CanonicalInteractionEvent:
    """Fail closed on stale, malformed, replay-unsafe, or consent-missing events."""

    if not event.event_id.strip():
        raise UIIRValidationError("event_id must not be empty")
    if not event.target_component_id.strip():
        raise UIIRValidationError("target_component_id must not be empty")
    if not event.capability_id.strip():
        raise UIIRValidationError("capability_id must not be empty")
    if event.timestamp_ms < 0:
        raise UIIRValidationError("timestamp_ms must be non-negative")
    if event.sequence < 0:
        raise UIIRValidationError("sequence must be non-negative")
    if event.confidence is not None and not (0.0 <= float(event.confidence) <= 1.0):
        raise UIIRValidationError("confidence must be in [0, 1]")
    if not event.consent_ok:
        raise UIIRValidationError(
            f"Event {event.event_id!r} missing consent before mediation"
        )
    if not isinstance(event.raw_payload, Mapping):
        raise UIIRValidationError("raw_payload must be a mapping")
    lowered = {str(k).lower() for k in event.raw_payload}
    bad = lowered & _FORBIDDEN_RAW_KEYS
    if bad:
        raise UIIRValidationError(
            f"Event {event.event_id!r} raw_payload contains forbidden keys: "
            + ", ".join(sorted(bad))
        )
    if _payload_size(event.raw_payload) > MAX_RAW_PAYLOAD_BYTES:
        raise UIIRValidationError(
            f"Event {event.event_id!r} raw_payload exceeds {MAX_RAW_PAYLOAD_BYTES} bytes"
        )
    # Raw payload is never canonical authority: event identity is the envelope fields.
    return event


def assert_not_authority(event: CanonicalInteractionEvent) -> None:
    """Document that raw_payload is observational only."""

    if event.raw_payload.get("is_authority") is True:
        raise UIIRValidationError(
            f"Event {event.event_id!r} raw_payload must not claim authority"
        )


__all__ = [
    "CanonicalInteractionEvent",
    "EventKind",
    "EventProvenance",
    "MAX_RAW_PAYLOAD_BYTES",
    "UI_RUNTIME_EVENT_INTERFACE",
    "assert_not_authority",
    "validate_event",
]
