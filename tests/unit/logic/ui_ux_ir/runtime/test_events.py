"""UIR-050: canonical interaction events and conventional input adapters."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import (
    CanonicalInteractionEvent,
    EventKind,
    EventProvenance,
    assert_not_authority,
    validate_event,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.input.conventional import (
    CONVENTIONAL_ADAPTER_ID,
    normalize_conventional_input,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError


def test_canonical_event_requires_consent_and_bounds_raw_payload() -> None:
    event = CanonicalInteractionEvent(
        event_id="evt:1",
        kind=EventKind.ACTIVATE,
        target_component_id="component:submit",
        timestamp_ms=1,
        provenance=EventProvenance.HUMAN,
        capability_id="pointer_mouse",
        consent_ok=True,
        raw_payload={"x": 1, "y": 2},
    )
    assert validate_event(event).event_id == "evt:1"
    assert_not_authority(event)
    with pytest.raises(UIIRValidationError, match="consent"):
        validate_event(
            CanonicalInteractionEvent(
                event_id="evt:2",
                kind=EventKind.ACTIVATE,
                target_component_id="component:submit",
                timestamp_ms=1,
                provenance=EventProvenance.HUMAN,
                capability_id="pointer_mouse",
                consent_ok=False,
            )
        )
    with pytest.raises(UIIRValidationError, match="forbidden"):
        validate_event(
            CanonicalInteractionEvent(
                event_id="evt:3",
                kind=EventKind.INPUT_VALUE,
                target_component_id="component:field",
                timestamp_ms=1,
                provenance=EventProvenance.HUMAN,
                capability_id="keyboard",
                consent_ok=True,
                raw_payload={"password": "secret"},
            )
        )


def test_synthetic_vs_human_provenance_is_explicit() -> None:
    human = CanonicalInteractionEvent(
        event_id="evt:h",
        kind=EventKind.FOCUS,
        target_component_id="c1",
        timestamp_ms=10,
        provenance=EventProvenance.HUMAN,
        capability_id="keyboard",
        consent_ok=True,
    )
    agent = CanonicalInteractionEvent(
        event_id="evt:a",
        kind=EventKind.ACTIVATE,
        target_component_id="c1",
        timestamp_ms=11,
        provenance=EventProvenance.AGENT,
        capability_id="agent_proposal",
        consent_ok=True,
    )
    assert validate_event(human).provenance is EventProvenance.HUMAN
    assert validate_event(agent).provenance is EventProvenance.AGENT


def test_conventional_adapter_maps_devices_and_never_decides_policy() -> None:
    click = normalize_conventional_input(
        {"device": "mouse", "type": "click", "x": 10, "y": 20},
        event_id="evt:click",
        target_component_id="component:submit",
        timestamp_ms=100,
    )
    assert click.kind is EventKind.ACTIVATE
    assert click.capability_id == "pointer_mouse"
    assert click.source_adapter == CONVENTIONAL_ADAPTER_ID
    key = normalize_conventional_input(
        {"device": "keyboard", "type": "keydown", "key": "Enter"},
        event_id="evt:key",
        target_component_id="component:submit",
        timestamp_ms=101,
    )
    assert key.kind is EventKind.INPUT_VALUE
    assert key.capability_id == "keyboard"
    touch = normalize_conventional_input(
        {"device": "touch", "type": "pointerdown"},
        event_id="evt:touch",
        target_component_id="component:submit",
        timestamp_ms=102,
    )
    assert touch.capability_id == "touchscreen"
    with pytest.raises(UIIRValidationError):
        normalize_conventional_input(
            {"device": "gaze", "type": "click"},
            event_id="evt:bad",
            target_component_id="c",
            timestamp_ms=1,
        )
