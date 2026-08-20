"""Conventional pointer/keyboard/touch/switch/pen normalizer (UIR-050)."""

from __future__ import annotations

from typing import Any, Final, Mapping

from ...schema import UIIRValidationError
from ..events import (
    CanonicalInteractionEvent,
    EventKind,
    EventProvenance,
    validate_event,
)

CONVENTIONAL_ADAPTER_ID: Final = "runtime.input.conventional@1"

_CAPABILITY_BY_DEVICE: Final = {
    "pointer": "pointer_mouse",
    "mouse": "pointer_mouse",
    "keyboard": "keyboard",
    "touch": "touchscreen",
    "touchscreen": "touchscreen",
    "switch": "switch",
    "pen": "pen",
}

_KIND_BY_TYPE: Final = {
    "click": EventKind.ACTIVATE,
    "pointerdown": EventKind.ACTIVATE,
    "keydown": EventKind.INPUT_VALUE,
    "keypress": EventKind.INPUT_VALUE,
    "input": EventKind.INPUT_VALUE,
    "focus": EventKind.FOCUS,
    "blur": EventKind.BLUR,
    "change": EventKind.SELECT,
    "submit": EventKind.CONFIRM,
    "cancel": EventKind.CANCEL,
    "scroll": EventKind.SCROLL,
    "hover": EventKind.HOVER,
    "pointermove": EventKind.HOVER,
}


def normalize_conventional_input(
    raw: Mapping[str, Any],
    *,
    event_id: str,
    target_component_id: str,
    timestamp_ms: int,
    sequence: int = 0,
    provenance: EventProvenance = EventProvenance.HUMAN,
    consent_ok: bool = True,
) -> CanonicalInteractionEvent:
    """Map pointer/keyboard/touch/switch/pen device events to canonical kinds.

    Never decides policy. Fails closed on missing device class, missing type,
    or unknown device types outside the conventional set.
    """

    if not isinstance(raw, Mapping):
        raise UIIRValidationError("conventional input raw must be a mapping")
    device = str(raw.get("device") or raw.get("device_class") or "").strip().lower()
    event_type = str(raw.get("type") or raw.get("event_type") or "").strip().lower()
    if device not in _CAPABILITY_BY_DEVICE:
        raise UIIRValidationError(
            f"Unsupported conventional device class {device!r}; "
            "expected pointer/mouse/keyboard/touch/switch/pen"
        )
    kind = _KIND_BY_TYPE.get(event_type)
    if kind is None:
        raise UIIRValidationError(
            f"Unsupported conventional event type {event_type!r}"
        )
    # Bound/redact raw payload: keep only non-secret conventional fields.
    safe_keys = (
        "device",
        "device_class",
        "type",
        "event_type",
        "key",
        "code",
        "button",
        "x",
        "y",
        "pointer_type",
        "switch_id",
        "pressure",
    )
    redacted = {k: raw[k] for k in safe_keys if k in raw}
    event = CanonicalInteractionEvent(
        event_id=event_id,
        kind=kind,
        target_component_id=target_component_id,
        timestamp_ms=timestamp_ms,
        provenance=provenance,
        capability_id=_CAPABILITY_BY_DEVICE[device],
        consent_ok=consent_ok,
        sequence=sequence,
        raw_payload=redacted,
        source_adapter=CONVENTIONAL_ADAPTER_ID,
    )
    return validate_event(event)


__all__ = [
    "CONVENTIONAL_ADAPTER_ID",
    "normalize_conventional_input",
]
