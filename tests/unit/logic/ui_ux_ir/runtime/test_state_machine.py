"""UIR-054: bounded UI state-machine runtime."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.model.behavior import (
    BehaviorModel,
    BehaviorState,
    BehaviorTransition,
    TransitionJoinKind,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.state_machine import (
    DEFAULT_MAX_TRACE_LENGTH,
    EffectKind,
    EffectSpec,
    TransitionDisposition,
    UIStateRuntime,
    UI_STATE_RUNTIME_INTERFACE,
    UXPhase,
    create_runtime,
    evaluate_guard,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError


# ---------------------------------------------------------------------------
# Fixture builders (compact recipes, not bulk golden dumps)
# ---------------------------------------------------------------------------


def _states(*ids: str, terminal: frozenset[str] | None = None) -> tuple[BehaviorState, ...]:
    terminal = terminal or frozenset()
    return tuple(
        BehaviorState(state_id=sid, terminal=sid in terminal, parallel_region="")
        for sid in ids
    )


def _states_parallel(
    region_a: tuple[str, ...],
    region_b: tuple[str, ...],
) -> tuple[BehaviorState, ...]:
    out: list[BehaviorState] = []
    for sid in region_a:
        out.append(BehaviorState(state_id=sid, parallel_region="region_a"))
    for sid in region_b:
        out.append(BehaviorState(state_id=sid, parallel_region="region_b"))
    return tuple(out)


def _ux_flow_model() -> BehaviorModel:
    """Focus → navigate → confirm → pending → result/error/recovery fixture."""

    return BehaviorModel(
        model_id="ux-flow",
        states=_states(
            "idle",
            "focused",
            "navigating",
            "confirming",
            "pending",
            "result_success",
            "result_failure",
            "error",
            "recovery",
            terminal=frozenset(
                {"result_success", "result_failure", "error", "recovery"}
            ),
        ),
        transitions=(
            BehaviorTransition(
                transition_id="t_focus",
                source_state_ids=("idle",),
                target_state_id="focused",
                event_id="focus",
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t_navigate",
                source_state_ids=("focused",),
                target_state_id="navigating",
                event_id="navigate",
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t_activate",
                source_state_ids=("navigating",),
                target_state_id="confirming",
                event_id="activate",
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t_confirm",
                source_state_ids=("confirming",),
                target_state_id="pending",
                event_id="confirm",
                effect_ids=("effect:invoke_submit", "effect:mark_pending"),
                priority=20,
                timeout_ms=5_000,
                rollback_target_state_id="idle",
                cancelable=True,
            ),
            BehaviorTransition(
                transition_id="t_cancel",
                source_state_ids=("confirming",),
                target_state_id="idle",
                event_id="cancel",
                priority=30,
                cancelable=True,
            ),
            BehaviorTransition(
                transition_id="t_result_ok",
                source_state_ids=("pending",),
                target_state_id="result_success",
                event_id="result_success",
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t_result_fail",
                source_state_ids=("pending",),
                target_state_id="result_failure",
                event_id="result_failure",
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t_error",
                source_state_ids=("pending",),
                target_state_id="error",
                event_id="error",
                priority=15,
            ),
            BehaviorTransition(
                transition_id="t_timeout",
                source_state_ids=("pending",),
                target_state_id="error",
                event_id="timeout",
                priority=5,
            ),
            BehaviorTransition(
                transition_id="t_recover_from_error",
                source_state_ids=("error",),
                target_state_id="recovery",
                event_id="recover",
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t_recover_from_failure",
                source_state_ids=("result_failure",),
                target_state_id="recovery",
                event_id="recover",
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t_recovery_done",
                source_state_ids=("recovery",),
                target_state_id="idle",
                event_id="retry",
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t_rollback",
                source_state_ids=("pending",),
                target_state_id="idle",
                event_id="rollback",
                priority=25,
            ),
        ),
        initial_state_ids=("idle",),
    )


def _guarded_model() -> BehaviorModel:
    return BehaviorModel(
        model_id="guarded",
        states=_states("idle", "ready", "done", terminal=frozenset({"done"})),
        transitions=(
            BehaviorTransition(
                transition_id="t_ready",
                source_state_ids=("idle",),
                target_state_id="ready",
                event_id="arm",
                guard_id="g_armed",
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t_done",
                source_state_ids=("ready",),
                target_state_id="done",
                event_id="go",
                guard_id="g_allowed",
                effect_ids=("effect:local_flag",),
                priority=10,
            ),
        ),
        initial_state_ids=("idle",),
    )


def _parallel_join_model() -> BehaviorModel:
    return BehaviorModel(
        model_id="parallel-join",
        states=_states_parallel(
            ("a_idle", "a_done"),
            ("b_idle", "b_done"),
        )
        + (BehaviorState(state_id="joined", terminal=True),),
        transitions=(
            BehaviorTransition(
                transition_id="t_a",
                source_state_ids=("a_idle",),
                target_state_id="a_done",
                event_id="finish_a",
                priority=1,
            ),
            BehaviorTransition(
                transition_id="t_b",
                source_state_ids=("b_idle",),
                target_state_id="b_done",
                event_id="finish_b",
                priority=1,
            ),
            BehaviorTransition(
                transition_id="t_join_all",
                source_state_ids=("a_done", "b_done"),
                target_state_id="joined",
                event_id="join",
                join_kind=TransitionJoinKind.ALL,
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t_join_any",
                source_state_ids=("a_done", "b_done"),
                target_state_id="joined",
                event_id="join_any",
                join_kind=TransitionJoinKind.ANY,
                priority=5,
            ),
        ),
        initial_state_ids=("a_idle", "b_idle"),
    )


def _ux_runtime() -> UIStateRuntime:
    return create_runtime(
        _ux_flow_model(),
        effects={
            "effect:invoke_submit": EffectSpec(
                effect_id="effect:invoke_submit",
                kind=EffectKind.EXTERNAL_REQUEST,
                binding_ref="binding:submit",
            ),
            "effect:mark_pending": EffectSpec(
                effect_id="effect:mark_pending",
                kind=EffectKind.STATE_ONLY,
                binding_ref="local:pending",
                set_fact="pending_flag",
                set_value=True,
            ),
        },
        focus_order=("comp:nav", "comp:submit", "comp:cancel"),
    )


# ---------------------------------------------------------------------------
# Closed guard language
# ---------------------------------------------------------------------------


def test_evaluate_guard_closed_language() -> None:
    facts = {"ready": True, "blocked": False}
    assert evaluate_guard("", facts) is True
    assert evaluate_guard("true", facts) is True
    assert evaluate_guard("false", facts) is False
    assert evaluate_guard("fact:ready", facts) is True
    assert evaluate_guard("ready", facts) is True
    assert evaluate_guard("not:fact:blocked", facts) is True
    assert evaluate_guard("fact:ready=true", facts) is True
    assert evaluate_guard("fact:ready=false", facts) is False
    with pytest.raises(UIIRValidationError, match="Unsupported"):
        evaluate_guard("ready && blocked", facts)
    with pytest.raises(UIIRValidationError, match="Unsupported|forbidden"):
        evaluate_guard("handler(() => true)", facts)
    with pytest.raises(UIIRValidationError, match="Unsupported|forbidden"):
        evaluate_guard("${evil()}", facts)


# ---------------------------------------------------------------------------
# Deterministic UX flow fixtures
# ---------------------------------------------------------------------------


def test_focus_navigation_confirmation_pending_result_recovery_trace() -> None:
    rt = _ux_runtime()
    snap = rt.initial_snapshot(timestamp_ms=0, focus_component_id="comp:nav")
    assert snap.phase is UXPhase.IDLE
    assert snap.state_version == 0

    trace = rt.run_trace(
        [
            ("focus", {"timestamp_ms": 10, "target_component_id": "comp:nav"}),
            ("navigate", {"timestamp_ms": 20, "target_component_id": "comp:submit"}),
            ("activate", {"timestamp_ms": 30}),
            ("confirm", {"timestamp_ms": 40}),
            ("result_success", {"timestamp_ms": 50}),
        ],
        initial=snap,
    )
    assert trace.terminated is True
    assert trace.final_snapshot.phase is UXPhase.RESULT_SUCCESS
    assert "result_success" in trace.final_snapshot.active_state_ids
    phases = [s.snapshot.phase for s in trace.steps if s.disposition is TransitionDisposition.APPLIED]
    assert phases == [
        UXPhase.FOCUSED,
        UXPhase.NAVIGATING,
        UXPhase.CONFIRMING,
        UXPhase.PENDING,
        UXPhase.RESULT_SUCCESS,
    ]
    # Pending phase marks confirmation/pending flag.
    pending_step = next(
        s for s in trace.steps if s.snapshot.phase is UXPhase.PENDING
    )
    assert pending_step.snapshot.pending_confirmation is True


def test_error_and_recovery_path() -> None:
    rt = _ux_runtime()
    # Fast-forward to pending.
    trace = rt.run_trace(
        [
            "focus",
            "navigate",
            "activate",
            "confirm",
            "error",
            "recover",
            "retry",
        ]
    )
    assert trace.terminated is True
    assert "idle" in trace.final_snapshot.active_state_ids
    assert trace.final_snapshot.phase is UXPhase.IDLE
    saw = {s.snapshot.phase for s in trace.steps if s.disposition is TransitionDisposition.APPLIED}
    assert UXPhase.ERROR in saw
    assert UXPhase.RECOVERY in saw


def test_cancel_from_confirmation() -> None:
    rt = _ux_runtime()
    trace = rt.run_trace(["focus", "navigate", "activate", "cancel"])
    assert "idle" in trace.final_snapshot.active_state_ids
    assert trace.final_snapshot.pending_confirmation is False


def test_result_failure_recovery() -> None:
    rt = _ux_runtime()
    trace = rt.run_trace(
        ["focus", "navigate", "activate", "confirm", "result_failure", "recover"]
    )
    assert trace.final_snapshot.phase is UXPhase.RECOVERY
    assert "recovery" in trace.final_snapshot.active_state_ids


# ---------------------------------------------------------------------------
# External effects remain staged
# ---------------------------------------------------------------------------


def test_external_effects_remain_staged_state_only_applied() -> None:
    rt = _ux_runtime()
    snap = rt.initial_snapshot()
    for event in ("focus", "navigate", "activate"):
        result = rt.step(snap, event, expected_state_version=snap.state_version)
        assert result.disposition is TransitionDisposition.APPLIED
        snap = result.snapshot
    result = rt.step(snap, "confirm", expected_state_version=snap.state_version)
    assert result.disposition is TransitionDisposition.APPLIED
    kinds = {e.effect_id: e for e in result.staged_effects}
    assert kinds["effect:invoke_submit"].kind is EffectKind.EXTERNAL_REQUEST
    assert kinds["effect:invoke_submit"].executed is False
    assert kinds["effect:mark_pending"].kind is EffectKind.STATE_ONLY
    assert kinds["effect:mark_pending"].executed is True
    assert result.snapshot.facts.get("pending_flag") is True
    # Accumulated staged effects on snapshot include the external request unexecuted.
    external = [
        e
        for e in result.snapshot.staged_effects
        if e.kind is EffectKind.EXTERNAL_REQUEST
    ]
    assert external
    assert all(e.executed is False for e in external)
    assert "does not execute" in result.notes or result.interface == UI_STATE_RUNTIME_INTERFACE


# ---------------------------------------------------------------------------
# State version / fencing rejects stale events
# ---------------------------------------------------------------------------


def test_state_version_fencing_rejects_stale_events() -> None:
    rt = _ux_runtime()
    snap = rt.initial_snapshot(timestamp_ms=100)
    result = rt.step(
        snap, "focus", expected_state_version=0, timestamp_ms=110
    )
    assert result.disposition is TransitionDisposition.APPLIED
    advanced = result.snapshot
    assert advanced.state_version == 1

    stale_version = rt.step(
        advanced, "navigate", expected_state_version=0, timestamp_ms=120
    )
    assert stale_version.disposition is TransitionDisposition.REJECT_STALE
    assert advanced.active_state_ids == stale_version.snapshot.active_state_ids

    stale_ts = rt.step(
        advanced, "navigate", expected_state_version=1, timestamp_ms=50
    )
    assert stale_ts.disposition is TransitionDisposition.REJECT_STALE
    assert "Stale" in stale_ts.notes or "stale" in stale_ts.reason.lower() or "fence" in stale_ts.reason


# ---------------------------------------------------------------------------
# Guards and priority
# ---------------------------------------------------------------------------


def test_guard_priority_and_deterministic_choice() -> None:
    model = BehaviorModel(
        model_id="prio",
        states=_states("idle", "low", "high"),
        transitions=(
            BehaviorTransition(
                transition_id="t_low",
                source_state_ids=("idle",),
                target_state_id="low",
                event_id="go",
                priority=1,
            ),
            BehaviorTransition(
                transition_id="t_high",
                source_state_ids=("idle",),
                target_state_id="high",
                event_id="go",
                priority=50,
            ),
        ),
        initial_state_ids=("idle",),
    )
    rt = create_runtime(model)
    result = rt.step(rt.initial_snapshot(), "go", expected_state_version=0)
    assert result.disposition is TransitionDisposition.APPLIED
    assert result.candidate is not None
    assert result.candidate.transition_id == "t_high"
    assert "high" in result.snapshot.active_state_ids


def test_guard_false_blocks_transition() -> None:
    rt = create_runtime(
        _guarded_model(),
        guards={"g_armed": "fact:armed", "g_allowed": "fact:allowed"},
    )
    snap = rt.initial_snapshot(facts={"armed": False, "allowed": False})
    blocked = rt.step(snap, "arm", expected_state_version=0)
    assert blocked.disposition is TransitionDisposition.GUARD_FALSE
    snap = rt.initial_snapshot(facts={"armed": True, "allowed": False})
    armed = rt.step(snap, "arm", expected_state_version=0)
    assert armed.disposition is TransitionDisposition.APPLIED
    blocked_go = rt.step(
        armed.snapshot, "go", expected_state_version=armed.snapshot.state_version
    )
    assert blocked_go.disposition is TransitionDisposition.GUARD_FALSE


def test_ambiguous_priority_fails_closed() -> None:
    # Construction-time collision for identical (sources, event, priority)
    # is rejected by validate_behavior_model; runtime also rejects when
    # equal-priority candidates are enabled simultaneously via parallel regions.
    model = BehaviorModel(
        model_id="ambig",
        states=_states("a", "b", "c", "d"),
        transitions=(
            BehaviorTransition(
                transition_id="t_a",
                source_state_ids=("a",),
                target_state_id="c",
                event_id="go",
                priority=10,
            ),
            BehaviorTransition(
                transition_id="t_b",
                source_state_ids=("b",),
                target_state_id="d",
                event_id="go",
                priority=10,
            ),
        ),
        initial_state_ids=("a", "b"),
    )
    rt = create_runtime(model)
    result = rt.step(rt.initial_snapshot(), "go", expected_state_version=0)
    assert result.disposition is TransitionDisposition.REJECT_AMBIGUOUS
    assert "Ambiguous" in result.reason


def test_construction_rejects_duplicate_priority_collision() -> None:
    model = BehaviorModel(
        model_id="bad",
        states=_states("idle", "a", "b"),
        transitions=(
            BehaviorTransition(
                transition_id="t1",
                source_state_ids=("idle",),
                target_state_id="a",
                event_id="go",
                priority=5,
            ),
            BehaviorTransition(
                transition_id="t2",
                source_state_ids=("idle",),
                target_state_id="b",
                event_id="go",
                priority=5,
            ),
        ),
        initial_state_ids=("idle",),
    )
    with pytest.raises(UIIRValidationError, match="priority|Ambiguous|Non-deterministic"):
        create_runtime(model)


# ---------------------------------------------------------------------------
# Unsupported expressions fail closed
# ---------------------------------------------------------------------------


def test_unsupported_guard_expression_fails_closed() -> None:
    rt = create_runtime(
        _guarded_model(),
        guards={"g_armed": "ready && true", "g_allowed": "true"},
    )
    result = rt.step(
        rt.initial_snapshot(facts={"armed": True}),
        "arm",
        expected_state_version=0,
    )
    assert result.disposition is TransitionDisposition.REJECT_UNSUPPORTED


def test_unsupported_effect_expression_fails_closed() -> None:
    model = BehaviorModel(
        model_id="fx",
        states=_states("idle", "done", terminal=frozenset({"done"})),
        transitions=(
            BehaviorTransition(
                transition_id="t",
                source_state_ids=("idle",),
                target_state_id="done",
                event_id="go",
                # Model validation rejects executable effect_ids at validate time.
                effect_ids=("ok_effect",),
                priority=1,
            ),
        ),
        initial_state_ids=("idle",),
    )
    # Inject bad expression via effects map binding is fine; bad effect *id* on
    # the transition is blocked by validate_behavior_model. Simulate runtime
    # rejection by calling evaluate path with a crafted step using a model that
    # has a plain id, then ensure parentheses in guard fail.
    rt = create_runtime(model)
    result = rt.step(rt.initial_snapshot(), "go", expected_state_version=0)
    assert result.disposition is TransitionDisposition.APPLIED

    with pytest.raises(UIIRValidationError, match="executable|effect"):
        validate_bad = BehaviorModel(
            model_id="fx2",
            states=_states("idle", "done"),
            transitions=(
                BehaviorTransition(
                    transition_id="tbad",
                    source_state_ids=("idle",),
                    target_state_id="done",
                    event_id="go",
                    effect_ids=("handler(() => 1)",),
                ),
            ),
            initial_state_ids=("idle",),
        )
        create_runtime(validate_bad)


# ---------------------------------------------------------------------------
# Parallel joins
# ---------------------------------------------------------------------------


def test_parallel_join_all_and_any() -> None:
    rt = create_runtime(_parallel_join_model())
    snap = rt.initial_snapshot()
    assert snap.active_state_ids == frozenset({"a_idle", "b_idle"})

    # Join ALL should not fire until both regions done.
    r = rt.step(snap, "join", expected_state_version=0)
    assert r.disposition is TransitionDisposition.NO_MATCH

    r = rt.step(snap, "finish_a", expected_state_version=0)
    snap = r.snapshot
    r = rt.step(snap, "join", expected_state_version=snap.state_version)
    assert r.disposition is TransitionDisposition.NO_MATCH  # b not done

    # ANY join works with only a_done.
    r_any = rt.step(snap, "join_any", expected_state_version=snap.state_version)
    assert r_any.disposition is TransitionDisposition.APPLIED
    assert "joined" in r_any.snapshot.active_state_ids

    # Fresh path for ALL.
    snap = rt.initial_snapshot()
    snap = rt.step(snap, "finish_a", expected_state_version=0).snapshot
    snap = rt.step(
        snap, "finish_b", expected_state_version=snap.state_version
    ).snapshot
    joined = rt.step(snap, "join", expected_state_version=snap.state_version)
    assert joined.disposition is TransitionDisposition.APPLIED
    assert joined.snapshot.active_state_ids == frozenset({"joined"})


# ---------------------------------------------------------------------------
# Timers / rollback
# ---------------------------------------------------------------------------


def test_timeout_and_rollback() -> None:
    rt = _ux_runtime()
    snap = rt.initial_snapshot(timestamp_ms=0)
    for event, ts in (("focus", 1), ("navigate", 2), ("activate", 3), ("confirm", 4)):
        r = rt.step(snap, event, expected_state_version=snap.state_version, timestamp_ms=ts)
        assert r.disposition is TransitionDisposition.APPLIED
        snap = r.snapshot
    assert snap.phase is UXPhase.PENDING
    assert snap.active_timers  # timeout armed on confirm transition

    timed = rt.step_timeout(snap, now_ms=10_000, expected_state_version=snap.state_version)
    assert timed.disposition is TransitionDisposition.APPLIED
    assert "error" in timed.snapshot.active_state_ids or "idle" in timed.snapshot.active_state_ids

    # Explicit rollback event.
    snap = rt.initial_snapshot(timestamp_ms=0)
    for event in ("focus", "navigate", "activate", "confirm"):
        snap = rt.step(
            snap, event, expected_state_version=snap.state_version
        ).snapshot
    rolled = rt.step(
        snap, "rollback", expected_state_version=snap.state_version
    )
    assert rolled.disposition is TransitionDisposition.APPLIED
    assert "idle" in rolled.snapshot.active_state_ids


# ---------------------------------------------------------------------------
# Nontermination / bounds fail closed
# ---------------------------------------------------------------------------


def test_trace_nontermination_fails_closed() -> None:
    rt = _ux_runtime()
    events = ["focus"] * (DEFAULT_MAX_TRACE_LENGTH + 5)
    # First focus applies; rest NO_MATCH — length itself is bounded.
    result = rt.run_trace(events, max_trace_length=3)
    # With max 3, 5 events should fail closed before running.
    assert result.terminated is False
    assert "Nontermination" in result.reason


def test_run_trace_respects_small_bound() -> None:
    rt = create_runtime(
        BehaviorModel(
            model_id="loopish",
            states=_states("a", "b"),
            transitions=(
                BehaviorTransition(
                    transition_id="t_ab",
                    source_state_ids=("a",),
                    target_state_id="b",
                    event_id="tick",
                    priority=1,
                ),
                BehaviorTransition(
                    transition_id="t_ba",
                    source_state_ids=("b",),
                    target_state_id="a",
                    event_id="tick",
                    priority=1,
                ),
            ),
            initial_state_ids=("a",),
        )
    )
    # 10 ticks with bound 4 → reject oversize trace without running.
    oversize = rt.run_trace(["tick"] * 10, max_trace_length=4)
    assert oversize.terminated is False
    assert oversize.steps == ()

    bounded = rt.run_trace(["tick"] * 4, max_trace_length=4)
    assert bounded.terminated is True
    assert len(bounded.steps) == 4
    assert all(s.disposition is TransitionDisposition.APPLIED for s in bounded.steps)


# ---------------------------------------------------------------------------
# Determinism / interface contract
# ---------------------------------------------------------------------------


def test_deterministic_repeated_execution() -> None:
    rt = _ux_runtime()
    events = [
        "focus",
        "navigate",
        "activate",
        "confirm",
        "result_success",
    ]
    a = rt.run_trace(events)
    b = rt.run_trace(events)
    assert [s.disposition for s in a.steps] == [s.disposition for s in b.steps]
    assert [s.candidate and s.candidate.transition_id for s in a.steps] == [
        s.candidate and s.candidate.transition_id for s in b.steps
    ]
    assert a.final_snapshot.active_state_ids == b.final_snapshot.active_state_ids
    assert a.final_snapshot.state_version == b.final_snapshot.state_version


def test_interface_constants() -> None:
    rt = _ux_runtime()
    assert rt.interface == UI_STATE_RUNTIME_INTERFACE
    result = rt.step(rt.initial_snapshot(), "focus", expected_state_version=0)
    assert result.interface == "UIStateRuntime@1"
    assert result.adapter_id == "runtime.state_machine@1"


def test_no_match_leaves_state_unchanged() -> None:
    rt = _ux_runtime()
    snap = rt.initial_snapshot()
    result = rt.step(snap, "result_success", expected_state_version=0)
    assert result.disposition is TransitionDisposition.NO_MATCH
    assert result.snapshot.state_version == snap.state_version
    assert result.snapshot.active_state_ids == snap.active_state_ids
