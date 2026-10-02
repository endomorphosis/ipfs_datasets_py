"""Strict UI declarations into native control and finite-prefix trace owners.

Untimed, single-state event-labelled transitions retain their declared edges.
Unknown guards, effects, timing, parallel joins and recovery semantics refuse
the state projection instead of disappearing from a ready training target.
Events are supplied observations, never proof of a completed user workflow.
"""
from __future__ import annotations

from . import family_training as core


class UIProjectionFrontier(ValueError):
    pass


def legacy_ec_omissions(document):
    """Name declared semantics absent from the old structural EC view.

    Timeout values themselves are retained by that compiler's explicit timeout
    records. This gate concerns fields it never emits, not family/backend proof.
    """
    from ...ui_ux_ir.model.behavior import TransitionJoinKind
    model = document.behavior_model
    if model is None:
        return []
    result = []
    for state in model.states:
        if state.parallel_region:
            result.append({"state_id": state.state_id, "fields": ["parallel_region"]})
    for edge in model.transitions:
        omitted = [name for name in ("guard_id", "effect_ids", "priority", "retryable", "undoable", "rollback_target_state_id")
                   if getattr(edge, name)]
        if not edge.cancelable:
            omitted.append("cancelable")
        if len(edge.source_state_ids) != 1 or edge.join_kind is not TransitionJoinKind.ALL:
            omitted.append("join_kind")
        if omitted:
            result.append({"transition_id": edge.transition_id, "fields": omitted})
    return result


def declared_state(document, source):
    from ...ui_ux_ir.model.behavior import BehaviorModel, BehaviorState, BehaviorTransition, TransitionJoinKind, validate_behavior_model
    from ...software_verification.state import StateSchema, StateVariable, FiniteDomainBound, StatePredicate
    from ...software_verification.transitions import StateTransitionIR, Action, ActionFrame, TransitionRelation
    model = document.behavior_model
    if type(model) is not BehaviorModel:
        raise UIProjectionFrontier("missing_native_UI_behavior_model")
    if (type(model.states) is not tuple or type(model.transitions) is not tuple
            or any(type(state) is not BehaviorState or type(state.terminal) is not bool
                or type(state.parallel_region) is not str for state in model.states)
            or any(type(edge) is not BehaviorTransition or type(edge.priority) is not int
                or any(type(getattr(edge, flag)) is not bool for flag in ("cancelable", "retryable", "undoable"))
                or any(type(getattr(edge, field)) is not str for field in ("event_id", "guard_id", "rollback_target_state_id"))
                or type(edge.effect_ids) is not tuple for edge in model.transitions)):
        raise UIProjectionFrontier("closed_native_UI_state_and_transition_fields_required")
    validate_behavior_model(model)
    if (not 1 <= len(model.states) <= 64 or not 1 <= len(model.transitions) <= 128
            or len(model.initial_state_ids) != 1):
        raise UIProjectionFrontier("bounded_nonempty_single_initial_UI_state_model_required")
    if len({t.transition_id for t in model.transitions}) != len(model.transitions):
        raise UIProjectionFrontier("duplicate_UI_transition_identity")
    if any(state.parallel_region for state in model.states):
        raise UIProjectionFrontier("UI_parallel_regions_require_explicit_product_state_semantics")
    states = {state.state_id: state for state in model.states}
    for edge in model.transitions:
        if len(edge.source_state_ids) != 1 or edge.join_kind is not TransitionJoinKind.ALL:
            raise UIProjectionFrontier("UI_join_semantics_not_lowered")
        if edge.guard_id or edge.effect_ids:
            raise UIProjectionFrontier("UI_guards_and_effects_require_typed_semantics")
        if edge.timeout_ms is not None:
            raise UIProjectionFrontier("UI_timeout_semantics_not_lowered")
        if edge.priority or edge.retryable or edge.undoable or edge.rollback_target_state_id or not edge.cancelable:
            raise UIProjectionFrontier("UI_priority_or_recovery_semantics_not_lowered")
        if states[edge.source_state_ids[0]].terminal:
            raise UIProjectionFrontier("terminal_UI_state_declares_outgoing_transition")
    # Identifiers in emitted code come only from enumeration; original labels
    # remain data in the reversible origin map, not executable target syntax.
    positions = {state_id: f"state_{index}" for index, state_id in enumerate(sorted(states))}
    refs = (source.ref_id,)
    variable = StateVariable("var:ui-state", "ui_state", "enumeration", "finite",
        domain_bound=FiniteDomainBound("bound:ui-state", members=tuple(positions.values())),
        description="Declared untimed UI control state; event-labelled steps are possibilities, not observations.",
        source_ref_ids=refs)
    schema = StateSchema(variables=(variable,))
    predicates = [StatePredicate("pred:ui-init", "initial", "Declared initial UI control state.",
        expression={variable.variable_id: positions[model.initial_state_ids[0]]},
        subject_variable_ids=(variable.variable_id,), source_ref_ids=refs)]
    actions, origins = [], []
    for index, edge in enumerate(sorted(model.transitions, key=lambda value: value.transition_id)):
        guard_id, next_id = f"pred:ui-guard:{index}", f"pred:ui-next:{index}"
        before, after = positions[edge.source_state_ids[0]], positions[edge.target_state_id]
        predicates.extend((StatePredicate(guard_id, "guard", "Declared source state of event-labelled transition.",
            expression={variable.variable_id: before}, subject_variable_ids=(variable.variable_id,), source_ref_ids=refs),
            StatePredicate(next_id, "next", "Declared target state of event-labelled transition.",
            expression={variable.variable_id: after}, subject_variable_ids=(variable.variable_id,), source_ref_ids=refs)))
        action = Action(f"action:ui:{index}", f"UIEvent{index}", ActionFrame(reads=(variable.variable_id,), writes=(variable.variable_id,)),
            guard_predicate_id=guard_id, next_predicate_id=next_id, source_ref_ids=refs,
            attributes={"UI_transition_id": edge.transition_id, "event_id": edge.event_id,
                "step_is_declared_possibility_not_observed_occurrence": True})
        actions.append(action)
        origins.append({"action_id": action.action_id, "transition": core._json(edge), "from_state": before, "to_state": after})
    relation = TransitionRelation("transition:ui", "action", "Declared untimed event-labelled UI edges.",
        action_ids=tuple(action.action_id for action in actions), allows_stutter=False)
    return StateTransitionIR(schema=schema, predicates=tuple(predicates), actions=tuple(actions), transitions=(relation,),
        metadata={"UI_document_id": document.document_id, "UI_model_id": model.model_id,
            "source_sha256": source.content_sha256, "state_map": positions, "origins": origins,
            "terminal_states": [positions[state.state_id] for state in model.states if state.terminal],
            "actual_event_occurrence_asserted": False, "guard_effect_timeout_loss": False})


def supplied_event_prefix(document, source):
    from ...ui_ux_ir.runtime.events import CanonicalInteractionEvent, validate_event
    from ...software_verification.trace import Clock, TimePoint, TimeValue, Event, TraceIR, ObservationPolicy
    if not 1 <= len(document.events) <= 256:
        raise UIProjectionFrontier("bounded_nonempty_supplied_UI_events_required")
    events = []
    previous = -1
    for index, event in enumerate(document.events):
        if type(event) is not CanonicalInteractionEvent:
            raise UIProjectionFrontier("native_UI_event_required")
        validate_event(event)
        if type(event.timestamp_ms) is not int or event.timestamp_ms < previous:
            raise UIProjectionFrontier("exact_nondecreasing_UI_event_timestamps_required")
        previous = event.timestamp_ms
        events.append(Event(f"event:ui:{index}", event.kind.value,
            TimePoint("clock:ui-ms", TimeValue(event.timestamp_ms)),
            payload={"supplied_UI_event": core._json(event)}, source_ref_ids=(source.ref_id,)))
    return TraceIR(clocks=(Clock("clock:ui-ms", unit="millisecond"),), events=tuple(events),
        kind="finite_prefix", observation_policy=ObservationPolicy("policy:ui-observed-only", kind="explicit"),
        primary_clock_id="clock:ui-ms", metadata={"UI_document_id": document.document_id,
            "source_sha256": source.content_sha256, "independently_attested": False,
            "complete_workflow_asserted": False, "event_order": "supplied_tuple_order"})


__all__ = ["UIProjectionFrontier", "legacy_ec_omissions", "declared_state", "supplied_event_prefix"]
