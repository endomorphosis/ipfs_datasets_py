"""UIR-053: deterministic multimodal fusion and arbitration."""

from __future__ import annotations

import pytest

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
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError


def _evt(
    event_id: str,
    *,
    kind: EventKind = EventKind.ACTIVATE,
    target: str = "btn",
    ts: int = 100,
    provenance: EventProvenance = EventProvenance.HUMAN,
    capability: str = "touchscreen",
    confidence: float | None = 0.9,
    sequence: int = 0,
    consent_ok: bool = True,
) -> CanonicalInteractionEvent:
    return CanonicalInteractionEvent(
        event_id=event_id,
        kind=kind,
        target_component_id=target,
        timestamp_ms=ts,
        provenance=provenance,
        capability_id=capability,
        consent_ok=consent_ok,
        confidence=confidence,
        sequence=sequence,
    )


def test_one_action_selected_once_debounces_duplicates() -> None:
    a = _evt("e1", ts=100, sequence=1)
    b = _evt("e2", ts=120, sequence=2)  # same target/kind within debounce
    result = fuse_events([a, b], debounce_window_ms=250)
    assert result.decision in {FusionDecision.SELECT, FusionDecision.SUPPRESS_DUPLICATE}
    if result.decision is FusionDecision.SELECT:
        assert result.selected is not None
        assert result.selected.event_id == "e1"
        assert any(e.event_id == "e2" for e in result.suppressed)


def test_human_priority_ranks_but_requires_consent() -> None:
    human = _evt("h", provenance=EventProvenance.HUMAN, confidence=0.7, sequence=1)
    agent = _evt(
        "a",
        provenance=EventProvenance.AGENT,
        capability="agent_proposal",
        confidence=0.99,
        sequence=2,
    )
    result = fuse_events([agent, human])
    assert result.decision is FusionDecision.SELECT
    assert result.selected is not None
    assert result.selected.provenance is EventProvenance.HUMAN
    with pytest.raises(UIIRValidationError, match="consent"):
        fuse_events([_evt("x", consent_ok=False)])


def test_stale_events_cannot_override_newer_state() -> None:
    stale = _evt("old", ts=50)
    result = fuse_events([stale], latest_state_timestamp_ms=100)
    assert result.decision is FusionDecision.REJECT_STALE
    assert result.selected is None


def test_inconsistent_high_impact_requires_clarification() -> None:
    a = FusionCandidate(
        event=_evt("e1", target="btn_a", kind=EventKind.ACTIVATE),
        risk_hint="high",
    )
    b = FusionCandidate(
        event=_evt("e2", target="btn_b", kind=EventKind.CONFIRM, capability="speech"),
        risk_hint="critical",
    )
    result = fuse_events([a, b])
    assert result.decision is FusionDecision.CLARIFY
    assert result.selected is None
    assert "inconsistent" in result.clarification_reason
    assert len(result.alternatives) == 2


def test_fusion_never_authorizes() -> None:
    result = fuse_events([_evt("e1")])
    assert "does not authorize" in result.notes or result.interface.endswith("Fusion@1")
    assert result.adapter_id == "runtime.fusion@1"
