from ipfs_datasets_py.logic.ui_ux_ir.formalize.contracts import FormalView
from ipfs_datasets_py.logic.ui_ux_ir.formalize.dcec import compile_events_to_dcec
from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import (
    CanonicalInteractionEvent, EventKind, EventProvenance,
)

def test_dcec_does_not_promote_observation_to_knowledge():
    human = CanonicalInteractionEvent(
        event_id="e1", kind=EventKind.ACTIVATE, target_component_id="c1",
        timestamp_ms=1, provenance=EventProvenance.HUMAN, capability_id="pointer_mouse",
        consent_ok=True,
    )
    agent = CanonicalInteractionEvent(
        event_id="e2", kind=EventKind.ACTIVATE, target_component_id="c1",
        timestamp_ms=2, provenance=EventProvenance.AGENT, capability_id="agent_proposal",
        consent_ok=True,
    )
    result = compile_events_to_dcec((human, agent))
    assert result.view is FormalView.DCEC
    kinds = {f.kind for f in result.formulas}
    assert "observes" in kinds
    assert "knows" not in kinds  # unknown remains unknown without evidence
    assert any(f.kind == "delegates" for f in result.formulas)
