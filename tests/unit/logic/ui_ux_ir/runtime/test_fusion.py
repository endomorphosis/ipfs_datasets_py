"""UIR-053: deterministic multimodal fusion and arbitration."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import (
    CanonicalInteractionEvent,
    EventKind,
    EventProvenance,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.fusion import (
    DEFAULT_CORRELATION_WINDOW_MS,
    FusionConfig,
    FusionOutcome,
    UIMultimodalFusion,
    UI_MULTIMODAL_FUSION_INTERFACE,
    fuse_interactions,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError


def _event(
    event_id: str,
    *,
    kind: EventKind = EventKind.ACTIVATE,
    target: str = "component:submit",
    timestamp_ms: int = 1000,
    sequence: int = 0,
    provenance: EventProvenance = EventProvenance.HUMAN,
    capability_id: str = "pointer_mouse",
    confidence: float | None = 0.95,
    risk: str = "low",
    source_adapter: str = "runtime.input.conventional@1",
    extra_payload: dict | None = None,
) -> CanonicalInteractionEvent:
    payload = {"risk_class": risk}
    if extra_payload:
        payload.update(extra_payload)
    return CanonicalInteractionEvent(
        event_id=event_id,
        kind=kind,
        target_component_id=target,
        timestamp_ms=timestamp_ms,
        provenance=provenance,
        capability_id=capability_id,
        consent_ok=True,
        sequence=sequence,
        confidence=confidence,
        raw_payload=payload,
        source_adapter=source_adapter,
    )


def test_simultaneous_equivalent_inputs_deduplicate_to_one() -> None:
    """One physical/logical action invokes at most once."""

    click = _event(
        "evt:click",
        timestamp_ms=1000,
        capability_id="pointer_mouse",
        source_adapter="runtime.input.conventional@1",
    )
    speech = _event(
        "evt:speech",
        timestamp_ms=1005,
        capability_id="speech",
        confidence=0.9,
        source_adapter="runtime.input.speech@1",
        extra_payload={"primary_text": "submit form"},
    )
    gesture = _event(
        "evt:pinch",
        timestamp_ms=1010,
        capability_id="hand_gesture",
        source_adapter="runtime.input.embodied@1",
    )
    result = fuse_interactions(
        [click, speech, gesture],
        correlation_window_ms=250,
    )
    assert result.outcome is FusionOutcome.DEDUPLICATE
    assert result.selected is not None
    assert result.selected.kind is EventKind.ACTIVATE
    assert result.selected.target_component_id == "component:submit"
    assert len(result.explanation.suppressed_event_ids) == 2
    assert "one_physical_logical_action_at_most_once" in result.explanation.reasons
    assert result.authorizes_invocation is False
    assert result.requires_policy_mediation is True


def test_human_priority_over_agent_does_not_bypass_policy() -> None:
    human = _event(
        "evt:human",
        timestamp_ms=2000,
        provenance=EventProvenance.HUMAN,
        capability_id="touchscreen",
    )
    agent = _event(
        "evt:agent",
        timestamp_ms=2001,
        provenance=EventProvenance.AGENT,
        capability_id="agent_proposal",
        confidence=0.99,
    )
    result = fuse_interactions([agent, human], correlation_window_ms=100)
    assert result.selected is not None
    assert result.selected.event_id == "evt:human"
    assert result.explanation.human_priority_applied is True
    assert result.explanation.policy_bypass_allowed is False
    assert "human_priority_does_not_bypass_policy" in result.explanation.reasons
    assert result.requires_policy_mediation is True
    assert result.authorizes_invocation is False
    assert "evt:agent" in result.explanation.suppressed_event_ids


def test_inconsistent_high_impact_events_require_clarification() -> None:
    delete_a = _event(
        "evt:del-a",
        target="component:account-a",
        timestamp_ms=3000,
        risk="destructive",
        capability_id="speech",
        extra_payload={"intent_id": "delete_account", "primary_text": "delete account a"},
    )
    delete_b = _event(
        "evt:del-b",
        target="component:account-b",
        timestamp_ms=3010,
        risk="critical",
        capability_id="hand_gesture",
        extra_payload={"intent_id": "delete_account"},
    )
    result = fuse_interactions([delete_a, delete_b], correlation_window_ms=100)
    assert result.outcome is FusionOutcome.CLARIFY
    assert result.requires_clarification is True
    assert result.selected is None
    assert result.authorizes_invocation is False
    assert result.requires_policy_mediation is True
    assert any("inconsistent" in r or "high_impact" in r for r in result.explanation.reasons)


def test_late_stale_events_cannot_override_newer_state() -> None:
    stale = _event("evt:stale", timestamp_ms=100, sequence=1)
    result = fuse_interactions(
        [stale],
        now_ms=100_000,
        max_event_age_ms=1_000,
        state_watermark_ms=50_000,
    )
    assert result.outcome is FusionOutcome.REJECT_STALE
    assert result.selected is None
    assert "evt:stale" in result.explanation.stale_event_ids
    assert "late_stale_events_cannot_override_newer_state" in result.explanation.reasons

    behind_sequence = _event("evt:old-seq", timestamp_ms=60_000, sequence=3)
    result2 = fuse_interactions(
        [behind_sequence],
        state_sequence=10,
        state_watermark_ms=None,
        now_ms=60_100,
    )
    assert result2.outcome is FusionOutcome.REJECT_STALE
    assert result2.selected is None


def test_fresh_event_preferred_over_stale_in_mixed_batch() -> None:
    stale = _event("evt:stale", timestamp_ms=100, sequence=1)
    fresh = _event("evt:fresh", timestamp_ms=50_000, sequence=20)
    result = fuse_interactions(
        [stale, fresh],
        now_ms=50_100,
        max_event_age_ms=5_000,
        state_watermark_ms=1_000,
    )
    assert result.selected is not None
    assert result.selected.event_id == "evt:fresh"
    assert "evt:stale" in result.explanation.stale_event_ids
    assert "late_stale_events_cannot_override_newer_state" in result.explanation.reasons


def test_fusion_is_order_stable_under_correlation_window() -> None:
    a = _event("evt:a", timestamp_ms=1000, sequence=1, confidence=0.8)
    b = _event(
        "evt:b",
        timestamp_ms=1005,
        sequence=2,
        confidence=0.9,
        capability_id="speech",
    )
    c = _event(
        "evt:c",
        timestamp_ms=1010,
        sequence=3,
        confidence=0.85,
        capability_id="hand_gesture",
    )
    r1 = fuse_interactions([a, b, c], correlation_window_ms=50)
    r2 = fuse_interactions([c, a, b], correlation_window_ms=50)
    r3 = fuse_interactions([b, c, a], correlation_window_ms=50)
    assert r1.selected is not None and r2.selected is not None and r3.selected is not None
    assert r1.selected.event_id == r2.selected.event_id == r3.selected.event_id
    assert r1.outcome is r2.outcome is r3.outcome
    assert r1.explanation.to_dict() == r2.explanation.to_dict() == r3.explanation.to_dict()
    assert r1.explanation.detail
    assert r1.explanation.correlation_window_ms == 50


def test_cancel_supersedes_competing_activations() -> None:
    activate = _event("evt:act", kind=EventKind.ACTIVATE, timestamp_ms=4000)
    cancel = _event(
        "evt:cancel",
        kind=EventKind.CANCEL,
        timestamp_ms=4010,
        capability_id="speech",
        extra_payload={"primary_text": "cancel"},
    )
    result = fuse_interactions([activate, cancel], correlation_window_ms=100)
    assert result.outcome is FusionOutcome.CANCEL
    assert result.selected is not None
    assert result.selected.kind is EventKind.CANCEL
    assert result.selected.event_id == "evt:cancel"
    assert "cancel_supersedes_competing_actions" in result.explanation.reasons
    assert result.requires_policy_mediation is True


def test_empty_batch_and_explanation_surface() -> None:
    result = fuse_interactions([])
    assert result.outcome is FusionOutcome.EMPTY
    assert result.selected is None
    assert result.explanation.outcome is FusionOutcome.EMPTY
    assert result.interface == UI_MULTIMODAL_FUSION_INTERFACE
    assert result.to_dict()["authorizes_invocation"] is False


def test_low_confidence_cluster_clarifies() -> None:
    low1 = _event("evt:l1", confidence=0.2, timestamp_ms=5000, capability_id="speech")
    low2 = _event(
        "evt:l2",
        confidence=0.3,
        timestamp_ms=5010,
        capability_id="hand_gesture",
    )
    result = fuse_interactions(
        [low1, low2],
        correlation_window_ms=100,
        confidence_floor=0.55,
    )
    assert result.outcome is FusionOutcome.CLARIFY
    assert result.requires_clarification is True
    assert result.selected is None


def test_ui_multimodal_fusion_class_tracks_state_watermark() -> None:
    fusion = UIMultimodalFusion(
        FusionConfig(correlation_window_ms=100, max_event_age_ms=10_000)
    )
    first = fusion.fuse([_event("evt:1", timestamp_ms=1000, sequence=1)], now_ms=1100)
    assert first.selected is not None
    fusion.advance_state(watermark_ms=1000, sequence=1)

    late = fusion.fuse([_event("evt:late", timestamp_ms=500, sequence=0)], now_ms=1200)
    assert late.outcome is FusionOutcome.REJECT_STALE
    assert late.selected is None

    newer = fusion.fuse(
        [_event("evt:2", timestamp_ms=1500, sequence=2)],
        now_ms=1600,
    )
    assert newer.selected is not None
    assert newer.selected.event_id == "evt:2"


def test_fusion_never_treats_selection_as_authorization() -> None:
    result = fuse_interactions([_event("evt:solo")])
    assert result.outcome is FusionOutcome.SELECT
    assert result.authorizes_invocation is False
    assert result.requires_policy_mediation is True
    assert "fusion_does_not_authorize_invocation" in result.explanation.reasons
    assert result.explanation.policy_bypass_allowed is False


def test_events_outside_window_do_not_false_correlate() -> None:
    early = _event("evt:early", timestamp_ms=1000)
    late = _event(
        "evt:late",
        timestamp_ms=1000 + DEFAULT_CORRELATION_WINDOW_MS + 50,
        sequence=2,
    )
    result = fuse_interactions(
        [early, late],
        correlation_window_ms=DEFAULT_CORRELATION_WINDOW_MS,
    )
    # Newest cluster wins; older suppressed — still at most one action.
    assert result.selected is not None
    assert result.selected.event_id == "evt:late"
    assert "evt:early" in result.explanation.suppressed_event_ids
    assert "one_physical_logical_action_at_most_once" in result.explanation.reasons


def test_consent_missing_fails_closed() -> None:
    bad = CanonicalInteractionEvent(
        event_id="evt:bad",
        kind=EventKind.ACTIVATE,
        target_component_id="c",
        timestamp_ms=1,
        provenance=EventProvenance.HUMAN,
        capability_id="pointer_mouse",
        consent_ok=False,
    )
    with pytest.raises(UIIRValidationError, match="consent"):
        fuse_interactions([bad])


def test_invalid_config_rejected() -> None:
    with pytest.raises(UIIRValidationError):
        FusionConfig(correlation_window_ms=-1)
    with pytest.raises(UIIRValidationError):
        fuse_interactions("not-a-sequence")  # type: ignore[arg-type]
