"""Contracts for state, action-system, and Kripke semantics (LFV-G022)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.software_verification.state import (
    STATE_SCHEMA_INTERFACE,
    Boundedness,
    FiniteDomainBound,
    LabelKind,
    PredicateRole,
    StateLabel,
    StatePredicate,
    StateSchema,
    StateTypeKind,
    StateValidationError,
    StateValuation,
    StateVariable,
    VariantMeasure,
)
from ipfs_datasets_py.logic.software_verification.transitions import (
    STATE_TRANSITION_IR_INTERFACE,
    Action,
    ActionFrame,
    FairnessConstraint,
    FairnessKind,
    KripkeEdge,
    KripkeStructure,
    KripkeWorld,
    StateTransitionIR,
    TransitionKind,
    TransitionRelation,
    TransitionValidationError,
)


def _counter_schema() -> StateSchema:
    return StateSchema(
        variables=(
            StateVariable(
                "var:pc",
                "pc",
                StateTypeKind.ENUMERATION,
                Boundedness.FINITE,
                domain_bound=FiniteDomainBound(
                    "bound:pc",
                    members=("idle", "busy", "done"),
                ),
            ),
            StateVariable(
                "var:count",
                "count",
                StateTypeKind.INTEGER,
                Boundedness.FINITE,
                domain_bound=FiniteDomainBound("bound:count", lower=0, upper=3),
            ),
            StateVariable(
                "var:ready",
                "ready",
                StateTypeKind.BOOLEAN,
                Boundedness.FINITE,
                domain_bound=FiniteDomainBound(
                    "bound:bool",
                    members=("false", "true"),
                    cardinality=2,
                ),
            ),
        ),
        metadata={"model": "bounded-counter"},
    )


def _predicate(
    predicate_id: str,
    role: PredicateRole,
    statement: str,
    *,
    subjects: tuple[str, ...] = (),
    expression: dict[str, object] | None = None,
) -> StatePredicate:
    return StatePredicate(
        predicate_id,
        role,
        statement,
        expression=expression or {"role": role.value},
        subject_variable_ids=subjects,
    )


def _counter_document(
    *,
    exclusive: bool = False,
    with_kripke: bool = True,
) -> StateTransitionIR:
    schema = _counter_schema()
    initial = _predicate(
        "pred:init",
        PredicateRole.INITIAL,
        "pc = idle /\\ count = 0 /\\ ready",
        subjects=("var:pc", "var:count", "var:ready"),
        expression={"pc": "idle", "count": 0, "ready": True},
    )
    guard = _predicate(
        "pred:guard-inc",
        PredicateRole.GUARD,
        "count < 3 /\\ ready",
        subjects=("var:count", "var:ready"),
    )
    next_inc = _predicate(
        "pred:next-inc",
        PredicateRole.NEXT,
        "count' = count + 1 /\\ pc' = busy",
        subjects=("var:count", "var:pc"),
    )
    invariant = _predicate(
        "pred:inv",
        PredicateRole.INVARIANT,
        "0 <= count <= 3",
        subjects=("var:count",),
    )
    fairness_pred = _predicate(
        "pred:fair",
        PredicateRole.FAIRNESS,
        "ready is true infinitely often",
        subjects=("var:ready",),
    )
    labels = (
        StateLabel("label:ready", "ready", LabelKind.ATOMIC_PROPOSITION),
        StateLabel("label:done", "done", LabelKind.ATOMIC_PROPOSITION),
    )
    frame = ActionFrame(reads=("var:count", "var:ready", "var:pc"), writes=("var:count", "var:pc"))
    action = Action(
        "action:inc",
        "Increment",
        frame,
        guard_predicate_id="pred:guard-inc",
        next_predicate_id="pred:next-inc",
        label_ids=("label:ready",),
        attributes={"exclusive_next": exclusive},
    )
    relation = TransitionRelation(
        "rel:next",
        TransitionKind.ACTION,
        "Next is the disjunction of enabled actions.",
        action_ids=("action:inc",),
        allows_stutter=True,
    )
    fairness = FairnessConstraint(
        "fair:ready",
        FairnessKind.WEAK,
        "Weak fairness of the ready signal.",
        predicate_id="pred:fair",
    )
    variant = VariantMeasure(
        "variant:remaining",
        "3 - count decreases on Increment",
        expression={"operator": "subtract", "operands": [3, "count"]},
        subject_variable_ids=("var:count",),
    )
    valuations = (
        StateValuation(
            "val:s0",
            {"var:pc": "idle", "var:count": 0, "var:ready": True},
        ),
        StateValuation(
            "val:s1",
            {"var:pc": "busy", "var:count": 1, "var:ready": True},
        ),
    )
    kripke = None
    if with_kripke:
        kripke = KripkeStructure(
            "kripke:counter",
            worlds=(
                KripkeWorld("world:s0", "val:s0", ("label:ready",)),
                KripkeWorld("world:s1", "val:s1", ("label:ready",)),
            ),
            edges=(
                KripkeEdge(
                    "edge:s0-s1",
                    "world:s0",
                    "world:s1",
                    action_id="action:inc",
                ),
            ),
            initial_world_ids=("world:s0",),
        )
    return StateTransitionIR(
        schema=schema,
        predicates=(initial, guard, next_inc, invariant, fairness_pred),
        actions=(action,),
        transitions=(relation,),
        fairness=(fairness,),
        labels=labels,
        variants=(variant,),
        valuations=valuations,
        kripke=kripke,
        metadata={"subject": "counter"},
    )


def test_state_schema_is_typed_deterministic_and_content_addressed() -> None:
    first = _counter_schema()
    # Variable order in construction must not affect identity.
    second = StateSchema(
        variables=tuple(reversed(first.variables)),
        metadata={"model": "bounded-counter"},
    )
    assert first.schema_id == second.schema_id
    assert first.INTERFACE == STATE_SCHEMA_INTERFACE
    assert first.variable_ids == ("var:count", "var:pc", "var:ready")
    round_trip = StateSchema.from_dict(first.to_dict())
    assert round_trip == first
    assert round_trip.schema_id == first.schema_id
    with pytest.raises(FrozenInstanceError):
        first.schema_id = "changed"  # type: ignore[misc]
    with pytest.raises(StateValidationError, match="does not match"):
        replace(first, schema_id="bafkbad")


def test_finite_bounds_are_explicit_and_unbounded_rejects_domain_bound() -> None:
    with pytest.raises(StateValidationError, match="requires an explicit domain_bound"):
        StateVariable(
            "var:x",
            "x",
            StateTypeKind.INTEGER,
            Boundedness.FINITE,
        )
    with pytest.raises(StateValidationError, match="must not declare domain_bound"):
        StateVariable(
            "var:y",
            "y",
            StateTypeKind.INTEGER,
            Boundedness.UNBOUNDED,
            domain_bound=FiniteDomainBound("bound:y", lower=0, upper=1),
        )
    with pytest.raises(StateValidationError, match="require members"):
        FiniteDomainBound("bound:empty")
    with pytest.raises(StateValidationError, match="must be finite"):
        StateVariable(
            "var:e",
            "e",
            StateTypeKind.ENUMERATION,
            Boundedness.UNBOUNDED,
        )
    with pytest.raises(StateValidationError, match="finite boundedness"):
        StateVariable(
            "var:b",
            "b",
            StateTypeKind.BOOLEAN,
            Boundedness.UNBOUNDED,
        )


def test_valuations_fail_closed_for_incomplete_surplus_or_ill_typed() -> None:
    schema = _counter_schema()
    good = StateValuation(
        "val:ok",
        {"var:pc": "idle", "var:count": 2, "var:ready": False},
    )
    good.validate_against(schema)

    with pytest.raises(StateValidationError, match="missing assignments"):
        StateValuation(
            "val:missing",
            {"var:pc": "idle", "var:count": 0},
        ).validate_against(schema)
    with pytest.raises(StateValidationError, match="unknown variables"):
        StateValuation(
            "val:surplus",
            {
                "var:pc": "idle",
                "var:count": 0,
                "var:ready": True,
                "var:extra": True,
            },
        ).validate_against(schema)
    with pytest.raises(StateValidationError, match="ill-typed"):
        StateValuation(
            "val:bad-type",
            {"var:pc": "idle", "var:count": "two", "var:ready": True},
        ).validate_against(schema)
    with pytest.raises(StateValidationError, match="ill-typed"):
        StateValuation(
            "val:out-of-range",
            {"var:pc": "idle", "var:count": 99, "var:ready": True},
        ).validate_against(schema)
    with pytest.raises(StateValidationError, match="ill-typed"):
        StateValuation(
            "val:bad-enum",
            {"var:pc": "running", "var:count": 0, "var:ready": True},
        ).validate_against(schema)


def test_predicate_roles_are_distinct_and_part_of_identity() -> None:
    initial = _predicate("pred:same", PredicateRole.INITIAL, "Init")
    invariant = _predicate("pred:same", PredicateRole.INVARIANT, "Init")
    assert initial.to_dict()["role"] == "initial"
    assert invariant.to_dict()["role"] == "invariant"
    assert initial.to_dict() != invariant.to_dict()

    roles = {
        PredicateRole.INITIAL,
        PredicateRole.NEXT,
        PredicateRole.INVARIANT,
        PredicateRole.FAIRNESS,
        PredicateRole.GUARD,
        PredicateRole.VARIANT,
        PredicateRole.LABEL,
    }
    assert roles == set(PredicateRole)


def test_actions_expose_read_write_frames_and_reject_unknown_variables() -> None:
    frame = ActionFrame(reads=("var:count",), writes=("var:count",))
    assert frame.permits_access(read_variable_ids=("var:count",), write_variable_ids=("var:count",))
    assert not frame.permits_access(write_variable_ids=("var:pc",))
    with pytest.raises(TransitionValidationError, match="cannot accompany"):
        ActionFrame(reads=("var:count",), allows_all_reads=True)

    document = _counter_document(with_kripke=False)
    assert document.actions[0].frame.reads == ("var:count", "var:pc", "var:ready")
    assert document.actions[0].frame.writes == ("var:count", "var:pc")

    bad_frame = ActionFrame(reads=("var:missing",), writes=())
    with pytest.raises(TransitionValidationError, match="unknown ids"):
        StateTransitionIR(
            schema=document.schema,
            predicates=document.predicates,
            actions=(
                Action(
                    "action:bad",
                    "Bad",
                    bad_frame,
                    guard_predicate_id="pred:guard-inc",
                ),
            ),
            transitions=document.transitions,
            labels=document.labels,
        )


def test_state_transition_ir_is_immutable_round_trippable_and_interface_tagged() -> None:
    document = _counter_document()
    assert document.interface == STATE_TRANSITION_IR_INTERFACE
    assert document.INTERFACE == STATE_TRANSITION_IR_INTERFACE
    assert document.predicates_by_role(PredicateRole.INITIAL)
    assert document.predicates_by_role(PredicateRole.INVARIANT)
    assert document.predicates_by_role(PredicateRole.FAIRNESS)
    assert document.predicates_by_role(PredicateRole.NEXT)
    assert document.kripke is not None
    assert document.kripke.successors("world:s0") == ("world:s1",)

    payload = {"nested": {"values": [1]}}
    action = Action(
        "action:meta",
        "Meta",
        ActionFrame(allows_all_reads=True, allows_all_writes=True),
        next_predicate_id="pred:next-inc",
        attributes=payload,
    )
    payload["nested"]["values"].append(2)
    assert action.attributes["nested"]["values"] == (1,)

    rebuilt = StateTransitionIR.from_dict(document.to_dict())
    assert rebuilt == document
    assert rebuilt.document_id == document.document_id
    assert rebuilt.canonical_id == document.document_id
    with pytest.raises(FrozenInstanceError):
        document.document_id = "changed"  # type: ignore[misc]
    with pytest.raises(TransitionValidationError, match="does not match"):
        replace(document, document_id="bafkbad")


def test_role_mismatches_and_missing_initial_fail_closed() -> None:
    document = _counter_document(with_kripke=False)
    wrong_guard = replace(
        document.actions[0],
        guard_predicate_id="pred:init",
    )
    with pytest.raises(TransitionValidationError, match="must have role 'guard'"):
        StateTransitionIR(
            schema=document.schema,
            predicates=document.predicates,
            actions=(wrong_guard,),
            transitions=(),
            labels=document.labels,
        )

    wrong_fairness = FairnessConstraint(
        "fair:bad",
        FairnessKind.STRONG,
        "Uses an invariant as fairness.",
        predicate_id="pred:inv",
    )
    with pytest.raises(TransitionValidationError, match="must have role 'fairness'"):
        StateTransitionIR(
            schema=document.schema,
            predicates=document.predicates,
            actions=document.actions,
            fairness=(wrong_fairness,),
            labels=document.labels,
        )

    with pytest.raises(TransitionValidationError, match="initial predicate"):
        StateTransitionIR(
            schema=document.schema,
            predicates=(
                _predicate("pred:only-inv", PredicateRole.INVARIANT, "true"),
            ),
            actions=document.actions,
            labels=document.labels,
        )

    with pytest.raises(TransitionValidationError, match="actions or transition"):
        StateTransitionIR(
            schema=document.schema,
            predicates=(
                _predicate("pred:init-only", PredicateRole.INITIAL, "Init"),
            ),
        )


def test_ambiguous_exclusive_next_actions_fail_closed() -> None:
    schema = _counter_schema()
    predicates = (
        _predicate("pred:init", PredicateRole.INITIAL, "Init"),
        _predicate("pred:next-a", PredicateRole.NEXT, "Next A"),
        _predicate("pred:next-b", PredicateRole.NEXT, "Next B"),
    )
    frame = ActionFrame(allows_all_reads=True, allows_all_writes=True)
    actions = (
        Action(
            "action:a",
            "A",
            frame,
            next_predicate_id="pred:next-a",
            attributes={"exclusive_next": True},
        ),
        Action(
            "action:b",
            "B",
            frame,
            next_predicate_id="pred:next-b",
            attributes={"exclusive_next": True},
        ),
    )
    with pytest.raises(TransitionValidationError, match="ambiguous exclusive next"):
        StateTransitionIR(
            schema=schema,
            predicates=predicates,
            actions=actions,
        )


def test_kripke_structure_requires_closed_world_resolution() -> None:
    document = _counter_document()
    assert document.kripke is not None
    with pytest.raises(TransitionValidationError, match="at least one initial world"):
        KripkeStructure(
            "kripke:empty-init",
            worlds=(KripkeWorld("world:s0"),),
            edges=(),
            initial_world_ids=(),
        )
    with pytest.raises(TransitionValidationError, match="unknown ids"):
        KripkeStructure(
            "kripke:bad-edge",
            worlds=(KripkeWorld("world:s0"),),
            edges=(KripkeEdge("edge:x", "world:s0", "world:missing"),),
            initial_world_ids=("world:s0",),
        )
    with pytest.raises(TransitionValidationError, match="unknown ids"):
        StateTransitionIR(
            schema=document.schema,
            predicates=document.predicates,
            actions=document.actions,
            transitions=document.transitions,
            fairness=document.fairness,
            labels=document.labels,
            valuations=document.valuations,
            kripke=KripkeStructure(
                "kripke:bad-val",
                worlds=(KripkeWorld("world:s0", "val:missing"),),
                edges=(),
                initial_world_ids=("world:s0",),
            ),
        )


def test_transition_kinds_and_fairness_are_closed() -> None:
    with pytest.raises(TransitionValidationError, match="requires action_ids"):
        TransitionRelation("rel:bad", TransitionKind.ACTION, "missing actions")
    with pytest.raises(TransitionValidationError, match="requires predicate_id"):
        TransitionRelation("rel:bad", TransitionKind.RELATION, "missing predicate")
    with pytest.raises(TransitionValidationError, match="must not reference"):
        TransitionRelation(
            "rel:stutter",
            TransitionKind.STUTTER,
            "stutter",
            action_ids=("action:x",),
        )
    with pytest.raises(TransitionValidationError, match="cannot mix"):
        FairnessConstraint(
            "fair:mix",
            FairnessKind.STRONG,
            "mixed",
            action_ids=("action:inc",),
            predicate_id="pred:fair",
        )
    stutter = TransitionRelation(
        "rel:stutter",
        TransitionKind.STUTTER,
        "Stuttering steps are allowed.",
        allows_stutter=True,
    )
    document = _counter_document(with_kripke=False)
    combined = StateTransitionIR(
        schema=document.schema,
        predicates=document.predicates,
        actions=document.actions,
        transitions=document.transitions + (stutter,),
        fairness=document.fairness,
        labels=document.labels,
        variants=document.variants,
        valuations=document.valuations,
    )
    assert any(item.kind is TransitionKind.STUTTER for item in combined.transitions)


def test_set_and_map_variables_require_element_types() -> None:
    with pytest.raises(StateValidationError, match="requires element_type_kind"):
        StateVariable(
            "var:s",
            "s",
            StateTypeKind.SET,
            Boundedness.FINITE,
            domain_bound=FiniteDomainBound("bound:s", cardinality=2),
        )
    variable = StateVariable(
        "var:ids",
        "ids",
        StateTypeKind.SET,
        Boundedness.FINITE,
        domain_bound=FiniteDomainBound(
            "bound:ids",
            members=("a", "b"),
            cardinality=2,
        ),
        element_type_kind=StateTypeKind.ENUMERATION,
    )
    assert variable.accepts_value(("a",))
    assert not variable.accepts_value(("a", "a"))
    assert not variable.accepts_value(("missing",))

    mapping = StateVariable(
        "var:map",
        "map",
        StateTypeKind.MAP,
        Boundedness.UNBOUNDED,
        element_type_kind=StateTypeKind.INTEGER,
    )
    assert mapping.accepts_value({"x": 1})
    assert not mapping.accepts_value({1: 2})  # type: ignore[dict-item]


def test_variants_and_labels_round_trip() -> None:
    label = StateLabel(
        "label:term",
        "terminated",
        LabelKind.STATE_PREDICATE,
        expression={"pc": "done"},
        subject_variable_ids=("var:pc",),
    )
    variant = VariantMeasure(
        "variant:pc",
        "progress toward done",
        expression={"measure": "remaining"},
        subject_variable_ids=("var:pc",),
    )
    assert StateLabel.from_dict(label.to_dict()) == label
    assert VariantMeasure.from_dict(variant.to_dict()) == variant
