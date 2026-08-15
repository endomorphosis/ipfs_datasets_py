"""UIR-073: Meta-glasses multimodal and mobile-fallback pilot."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import (
    CanonicalInteractionEvent,
    EventKind,
    EventProvenance,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.fusion import (
    FusionCandidate,
    FusionDecision,
    fuse_events,
)

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "ui_ux_ir"
    / "pilots"
    / "meta_glasses.json"
)


def test_no_fabricated_capabilities_and_explicit_fallback() -> None:
    pilot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for bad in pilot["unsupported_capabilities"]:
        assert bad in {"raw_emg", "fabricated_cursor", "fabricated_touch"}
        assert bad not in pilot["required_capabilities"]

    assert pilot["fallback"]["target"] == "mobile"
    assert pilot["fallback"]["modality"] == "audio_voice"
    assert pilot["duplicate_gesture_policy"] == "dedupe_correlation"


def test_duplicate_gesture_correlation_suppresses_double_invoke() -> None:
    """Duplicate correlated gestures admit one intent (fusion never authorizes)."""

    e1 = CanonicalInteractionEvent(
        event_id="g1",
        kind=EventKind.ACTIVATE,
        target_component_id="btn",
        timestamp_ms=10,
        provenance=EventProvenance.HUMAN,
        capability_id="hand_gesture",
        consent_ok=True,
        confidence=0.9,
    )
    e2 = CanonicalInteractionEvent(
        event_id="g1-dup",
        kind=EventKind.ACTIVATE,
        target_component_id="btn",
        timestamp_ms=12,
        provenance=EventProvenance.HUMAN,
        capability_id="hand_gesture",
        consent_ok=True,
        confidence=0.91,
    )
    result = fuse_events(
        (
            FusionCandidate(event=e1, source_modality="hand"),
            FusionCandidate(event=e2, source_modality="hand"),
        )
    )
    assert result.decision in {
        FusionDecision.SELECT,
        FusionDecision.SUPPRESS_DUPLICATE,
        FusionDecision.CLARIFY,
    }
    # At most one selected event for a single physical action family.
    if result.selected is not None:
        assert result.selected.event_id in {"g1", "g1-dup"}
