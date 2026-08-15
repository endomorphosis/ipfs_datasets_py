"""UIR-061: bounded state-model checks (not theorem proof).

Distinguishes bounded reachability / deadlock evidence from formal theorem
authority. Bounds and seeds are explicit.
"""

from __future__ import annotations

from typing import Final

from ipfs_datasets_py.logic.ui_ux_ir.model.behavior import (
    BehaviorModel,
    BehaviorState,
    BehaviorTransition,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.state_machine import (
    EffectKind,
    EffectSpec,
    TransitionDisposition,
    UXPhase,
    create_runtime,
)

STATE_MODEL_SEED: Final = 0x061_51C
STATE_MODEL_BOUND: Final = 16
# Explicit: this suite produces *bounded model evidence*, not theorem proof.
EVIDENCE_KIND: Final = "bounded_model_check"
EVIDENCE_AUTHORITY: Final = "observation"  # never "proof" / "theorem"


def _linear_flow() -> BehaviorModel:
    return BehaviorModel(
        model_id="property-linear",
        states=(
            BehaviorState(state_id="idle"),
            BehaviorState(state_id="focused"),
            BehaviorState(state_id="pending"),
            BehaviorState(state_id="result_success", terminal=True),
            BehaviorState(state_id="error", terminal=True),
        ),
        transitions=(
            BehaviorTransition(
                transition_id="t1",
                source_state_ids=("idle",),
                target_state_id="focused",
                event_id="focus",
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t2",
                source_state_ids=("focused",),
                target_state_id="pending",
                event_id="activate",
                priority=10,
                effect_ids=("effect:invoke",),
            ),
            BehaviorTransition(
                transition_id="t3",
                source_state_ids=("pending",),
                target_state_id="result_success",
                event_id="result_success",
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t4",
                source_state_ids=("pending",),
                target_state_id="error",
                event_id="result_failure",
                priority=10,
            ),
        ),
        initial_state_ids=("idle",),
    )


def test_bounds_and_authority_recorded() -> None:
    assert STATE_MODEL_BOUND >= 8
    assert EVIDENCE_KIND == "bounded_model_check"
    assert EVIDENCE_AUTHORITY != "proof"
    assert EVIDENCE_AUTHORITY != "theorem"
    assert STATE_MODEL_SEED == 0x061_51C


def test_bounded_reachability_success_path() -> None:
    rt = create_runtime(_linear_flow())
    snap = rt.initial_snapshot(timestamp_ms=0)
    events = ["focus", "activate", "result_success"]
    assert len(events) <= STATE_MODEL_BOUND
    for i, eid in enumerate(events):
        step = rt.step(
            snap,
            eid,
            timestamp_ms=(i + 1) * 10,
            expected_state_version=snap.state_version,
        )
        assert step.disposition is TransitionDisposition.APPLIED
        snap = step.snapshot
    assert "result_success" in snap.active_state_ids
    assert snap.phase is UXPhase.RESULT_SUCCESS


def test_duplicate_event_safety() -> None:
    """Replaying the same event after transition is a no-match, not a rewrite."""

    rt = create_runtime(_linear_flow())
    snap = rt.initial_snapshot()
    first = rt.step(snap, "focus", timestamp_ms=1, expected_state_version=0)
    assert first.disposition is TransitionDisposition.APPLIED
    snap = first.snapshot
    version = snap.state_version
    second = rt.step(
        snap, "focus", timestamp_ms=2, expected_state_version=version
    )
    # From focused, focus has no transition.
    assert second.disposition is TransitionDisposition.NO_MATCH
    assert second.snapshot.state_version == version


def test_stale_event_fence() -> None:
    rt = create_runtime(_linear_flow())
    snap = rt.initial_snapshot(timestamp_ms=100)
    step = rt.step(snap, "focus", timestamp_ms=110, expected_state_version=0)
    assert step.disposition is TransitionDisposition.APPLIED
    snap = step.snapshot
    stale = rt.step(
        snap,
        "activate",
        timestamp_ms=50,  # older than latest
        expected_state_version=0,  # stale fence on version
    )
    assert stale.disposition in {
        TransitionDisposition.REJECT_STALE,
        TransitionDisposition.NO_MATCH,
        TransitionDisposition.REJECT_INVALID,
    }


def test_external_effects_remain_staged() -> None:
    rt = create_runtime(
        _linear_flow(),
        effects={
            "effect:invoke": EffectSpec(
                effect_id="effect:invoke",
                kind=EffectKind.EXTERNAL_REQUEST,
                binding_ref="binding:submit",
            ),
        },
    )
    snap = rt.initial_snapshot()
    snap = rt.step(snap, "focus", timestamp_ms=1, expected_state_version=0).snapshot
    step = rt.step(
        snap, "activate", timestamp_ms=2, expected_state_version=snap.state_version
    )
    assert step.disposition is TransitionDisposition.APPLIED
    for staged in step.staged_effects:
        if staged.effect_id == "effect:invoke":
            assert staged.executed is False


def test_deadlock_detection_on_closed_sink() -> None:
    """Terminal state with no transitions is a bounded sink (not a proof of liveness)."""

    model = BehaviorModel(
        model_id="sink",
        states=(BehaviorState(state_id="result_success", terminal=True),),
        transitions=(),
        initial_state_ids=("result_success",),
    )
    rt = create_runtime(model)
    snap = rt.initial_snapshot()
    step = rt.step(snap, "focus", timestamp_ms=1, expected_state_version=0)
    assert step.disposition is TransitionDisposition.NO_MATCH
    assert "result_success" in step.snapshot.active_state_ids
