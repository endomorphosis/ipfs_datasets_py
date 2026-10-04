"""Contracts for concurrency, rely-guarantee, session, and refinement (LFV-G027)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.software_verification.concurrency import (
    CONCURRENCY_IR_INTERFACE,
    AtomicRegion,
    AtomicityKind,
    BoundedSchedule,
    ChannelMode,
    ComponentKind,
    ConcurrencyFairness,
    ConcurrencyIR,
    ConcurrencyValidationError,
    ConcurrentChannel,
    ConcurrentComponent,
    ConcurrentStep,
    FairnessKind,
    InterferenceAssumption,
    InterferenceKind,
    LinearizabilityPoint,
    RelyGuaranteeContract,
    SessionAction,
    SessionPolarity,
    SessionProtocol,
    SessionRole,
    StepOwner,
    dual_polarity,
    dual_role,
)
from ipfs_datasets_py.logic.software_verification.refinement import (
    REFINEMENT_IR_INTERFACE,
    BoundednessKind,
    RefinementBoundedness,
    RefinementIR,
    RefinementKind,
    RefinementObligation,
    RefinementState,
    RefinementSystem,
    RefinementTransition,
    RefinementValidationError,
    SimulationCouple,
    SimulationDirection,
    SimulationRelation,
    SystemLevel,
)


def _producer_consumer() -> ConcurrencyIR:
    """Two-thread producer/consumer with environment interference and sessions."""

    producer_steps = (
        ConcurrentStep(
            "step:prod-write",
            StepOwner.COMPONENT,
            "produce",
            guard_statement="buffer_space > 0",
            effect_statement="buffer := buffer + 1",
            component_id="comp:producer",
            atomic_region_id="atom:prod",
            read_variable_ids=("var:buffer",),
            write_variable_ids=("var:buffer",),
        ),
    )
    consumer_steps = (
        ConcurrentStep(
            "step:cons-read",
            StepOwner.COMPONENT,
            "consume",
            guard_statement="buffer > 0",
            effect_statement="buffer := buffer - 1",
            component_id="comp:consumer",
            atomic_region_id="atom:cons",
            read_variable_ids=("var:buffer",),
            write_variable_ids=("var:buffer",),
        ),
    )
    env_steps = (
        ConcurrentStep(
            "step:env-noise",
            StepOwner.ENVIRONMENT,
            "environment interference",
            guard_statement="true",
            effect_statement="may read buffer",
            read_variable_ids=("var:buffer",),
        ),
    )
    components = (
        ConcurrentComponent(
            "comp:producer",
            ComponentKind.THREAD,
            "Producer",
            step_ids=("step:prod-write",),
        ),
        ConcurrentComponent(
            "comp:consumer",
            ComponentKind.THREAD,
            "Consumer",
            step_ids=("step:cons-read",),
        ),
    )
    client_actions = (
        SessionAction(
            "sess:req",
            SessionPolarity.SEND,
            "request",
            payload_sort="Item",
            continuation_action_ids=("sess:ack",),
        ),
        SessionAction(
            "sess:ack",
            SessionPolarity.RECEIVE,
            "ack",
            payload_sort="Ack",
            continuation_action_ids=("sess:end",),
        ),
        SessionAction("sess:end", SessionPolarity.END, "end"),
    )
    client = SessionProtocol(
        "sess:client",
        "ItemClient",
        SessionRole.CLIENT,
        client_actions,
        entry_action_id="sess:req",
        dual_protocol_id="sess:server",
    )
    server = client.dual(protocol_id="sess:server", name="ItemServer")
    return ConcurrencyIR(
        components=components,
        steps=producer_steps + consumer_steps + env_steps,
        shared_variable_ids=("var:buffer",),
        atomic_regions=(
            AtomicRegion(
                "atom:prod",
                "comp:producer",
                ("step:prod-write",),
                AtomicityKind.ATOMIC,
                "produce is atomic",
            ),
            AtomicRegion(
                "atom:cons",
                "comp:consumer",
                ("step:cons-read",),
                AtomicityKind.ATOMIC,
                "consume is atomic",
            ),
        ),
        interference=(
            InterferenceAssumption(
                "intf:env-buffer",
                InterferenceKind.READ,
                "Environment may observe the buffer.",
                subject_component_id="comp:producer",
                interferer_is_environment=True,
                shared_variable_ids=("var:buffer",),
            ),
            InterferenceAssumption(
                "intf:peer",
                InterferenceKind.BOTH,
                "Consumer may read and write the buffer while producer runs.",
                subject_component_id="comp:producer",
                interferer_component_id="comp:consumer",
                shared_variable_ids=("var:buffer",),
            ),
        ),
        fairness=(
            ConcurrencyFairness(
                "fair:prod",
                FairnessKind.WEAK,
                "Producer is weakly fair.",
                step_ids=("step:prod-write",),
            ),
            ConcurrencyFairness(
                "fair:cons",
                FairnessKind.WEAK,
                "Consumer is weakly fair.",
                component_ids=("comp:consumer",),
            ),
        ),
        rely_guarantee=(
            RelyGuaranteeContract(
                "rg:producer",
                "comp:producer",
                rely_statement="buffer stays non-negative",
                guarantee_statement="buffer increases by at most one",
                shared_variable_ids=("var:buffer",),
                interference_ids=("intf:env-buffer", "intf:peer"),
            ),
            RelyGuaranteeContract(
                "rg:consumer",
                "comp:consumer",
                rely_statement="buffer stays non-negative",
                guarantee_statement="buffer decreases by at most one",
                shared_variable_ids=("var:buffer",),
                interference_ids=("intf:peer",),
            ),
        ),
        channels=(
            ConcurrentChannel(
                "chan:items",
                "items",
                ChannelMode.BUFFERED,
                ("comp:producer", "comp:consumer"),
                payload_sort="Item",
                capacity=4,
            ),
        ),
        sessions=(client, server),
        linearizability_points=(
            LinearizabilityPoint(
                "lin:prod",
                "step:prod-write",
                "AbstractEnqueue",
                "produce linearizes at the write",
            ),
            LinearizabilityPoint(
                "lin:cons",
                "step:cons-read",
                "AbstractDequeue",
                "consume linearizes at the read",
            ),
        ),
        schedules=(
            BoundedSchedule(
                "sched:depth-8",
                max_steps=8,
                component_ids=("comp:producer", "comp:consumer"),
                claims_unbounded_refinement=False,
                statement="explore at most 8 interleavings",
            ),
        ),
        require_interference=True,
        require_fairness=True,
        metadata={"example": "producer-consumer"},
    )


def _counter_refinement() -> RefinementIR:
    """Concrete counter refines an abstract two-state flag via forward simulation."""

    abstract = RefinementSystem(
        "sys:abstract-flag",
        SystemLevel.ABSTRACT,
        "AbstractFlag",
        states=(
            RefinementState("abs:off", "off", is_initial=True),
            RefinementState("abs:on", "on"),
        ),
        transitions=(
            RefinementTransition("abs:t-on", "abs:off", "abs:on", "enable"),
            RefinementTransition("abs:t-off", "abs:on", "abs:off", "disable"),
        ),
    )
    concrete = RefinementSystem(
        "sys:concrete-counter",
        SystemLevel.CONCRETE,
        "ConcreteCounter",
        states=(
            RefinementState("con:0", "zero", is_initial=True, predicate_statement="n = 0"),
            RefinementState("con:1", "one", predicate_statement="n = 1"),
            RefinementState("con:2", "two", predicate_statement="n >= 2"),
        ),
        transitions=(
            RefinementTransition("con:inc0", "con:0", "con:1", "enable"),
            RefinementTransition("con:inc1", "con:1", "con:2", "enable"),
            RefinementTransition("con:reset", "con:1", "con:0", "disable"),
            RefinementTransition("con:reset2", "con:2", "con:0", "disable"),
            RefinementTransition(
                "con:stutter2",
                "con:2",
                "con:2",
                "tau",
                is_stutter=True,
            ),
        ),
    )
    # Forward simulation: abstract off ~ concrete 0; abstract on ~ concrete 1 or 2.
    simulation = SimulationRelation(
        "sim:forward",
        SimulationDirection.FORWARD,
        abstract_system_id="sys:abstract-flag",
        concrete_system_id="sys:concrete-counter",
        couples=(
            SimulationCouple("c:off-0", "abs:off", "con:0"),
            SimulationCouple("c:on-1", "abs:on", "con:1"),
            SimulationCouple("c:on-2", "abs:on", "con:2"),
        ),
        statement="counter refines flag",
        max_matching_steps=4,
        claims_unbounded_refinement=False,
    )
    bound = RefinementBoundedness(
        "bound:steps-16",
        BoundednessKind.BOUNDED,
        "At most 16 refinement matching steps.",
        max_steps=16,
        claims_unbounded_refinement=False,
    )
    obligation = RefinementObligation(
        "obl:sim",
        RefinementKind.SIMULATION,
        "Concrete counter forward-simulates the abstract flag.",
        abstract_system_id="sys:abstract-flag",
        concrete_system_id="sys:concrete-counter",
        simulation_relation_id="sim:forward",
        boundedness_id="bound:steps-16",
        claims_unbounded_refinement=False,
    )
    return RefinementIR(
        systems=(abstract, concrete),
        simulations=(simulation,),
        obligations=(obligation,),
        boundedness=(bound,),
        metadata={"example": "flag-counter"},
    )


# ---------------------------------------------------------------------------
# ConcurrencyIR
# ---------------------------------------------------------------------------


def test_concurrency_ir_round_trip_identity_and_interface() -> None:
    document = _producer_consumer()
    assert document.interface == CONCURRENCY_IR_INTERFACE
    assert document.INTERFACE == CONCURRENCY_IR_INTERFACE
    assert document.document_id
    assert document.canonical_id == document.document_id
    assert len(document.environment_steps()) == 1
    assert len(document.component_steps("comp:producer")) == 1

    rebuilt = ConcurrencyIR.from_dict(document.to_dict())
    assert rebuilt == document
    assert rebuilt.document_id == document.document_id
    with pytest.raises(FrozenInstanceError):
        document.document_id = "changed"  # type: ignore[misc]
    with pytest.raises(ConcurrencyValidationError, match="does not match"):
        replace(document, document_id="bafkbad")


def test_environment_and_component_steps_are_distinct() -> None:
    with pytest.raises(ConcurrencyValidationError, match="require a component_id"):
        ConcurrentStep(
            "step:bad",
            StepOwner.COMPONENT,
            "missing component",
        )
    with pytest.raises(ConcurrencyValidationError, match="must not claim a component_id"):
        ConcurrentStep(
            "step:bad-env",
            StepOwner.ENVIRONMENT,
            "env with component",
            component_id="comp:producer",
        )

    document = _producer_consumer()
    env = document.environment_steps()[0]
    comp = document.component_steps("comp:producer")[0]
    assert env.owner is StepOwner.ENVIRONMENT
    assert comp.owner is StepOwner.COMPONENT
    assert env.owner is not comp.owner
    assert StepOwner.ENVIRONMENT.value != StepOwner.COMPONENT.value

    # Listing an environment step on a component fails closed.
    with pytest.raises(ConcurrencyValidationError, match="environment step"):
        ConcurrencyIR(
            components=(
                ConcurrentComponent(
                    "comp:only",
                    ComponentKind.PROCESS,
                    "Only",
                    step_ids=("step:env-noise",),
                ),
            ),
            steps=(
                ConcurrentStep(
                    "step:env-noise",
                    StepOwner.ENVIRONMENT,
                    "env",
                ),
            ),
            require_interference=False,
        )


def test_interference_and_fairness_are_explicit() -> None:
    with pytest.raises(ConcurrencyValidationError, match="never implicit"):
        ConcurrencyFairness("fair:empty", FairnessKind.WEAK, "no subjects")

    with pytest.raises(ConcurrencyValidationError, match="interferer"):
        InterferenceAssumption(
            "intf:bad",
            InterferenceKind.WRITE,
            "missing interferer",
            subject_component_id="comp:a",
        )

    with pytest.raises(ConcurrencyValidationError, match="explicit interference"):
        ConcurrencyIR(
            components=(
                ConcurrentComponent(
                    "comp:a",
                    ComponentKind.THREAD,
                    "A",
                    step_ids=("step:a",),
                ),
                ConcurrentComponent(
                    "comp:b",
                    ComponentKind.THREAD,
                    "B",
                    step_ids=("step:b",),
                ),
            ),
            steps=(
                ConcurrentStep(
                    "step:a",
                    StepOwner.COMPONENT,
                    "a",
                    component_id="comp:a",
                ),
                ConcurrentStep(
                    "step:b",
                    StepOwner.COMPONENT,
                    "b",
                    component_id="comp:b",
                ),
            ),
            interference=(),
            require_interference=True,
        )

    with pytest.raises(ConcurrencyValidationError, match="fairness assumptions are required"):
        base = _producer_consumer()
        ConcurrencyIR(
            components=base.components,
            steps=base.steps,
            shared_variable_ids=base.shared_variable_ids,
            atomic_regions=base.atomic_regions,
            interference=base.interference,
            fairness=(),
            require_interference=True,
            require_fairness=True,
        )


def test_atomic_regions_channels_rely_guarantee_and_linearizability() -> None:
    document = _producer_consumer()
    assert document.atomic_regions[0].atomicity is AtomicityKind.ATOMIC
    assert document.channels[0].mode is ChannelMode.BUFFERED
    assert document.channels[0].capacity == 4
    assert document.rely_guarantee[0].rely_statement
    operations = {
        item.abstract_operation for item in document.linearizability_points
    }
    assert operations == {"AbstractEnqueue", "AbstractDequeue"}

    with pytest.raises(ConcurrencyValidationError, match="capacity"):
        ConcurrentChannel(
            "chan:bad",
            "bad",
            ChannelMode.BUFFERED,
            ("comp:producer", "comp:consumer"),
        )
    with pytest.raises(ConcurrencyValidationError, match="at least two endpoint"):
        ConcurrentChannel(
            "chan:one",
            "one",
            ChannelMode.SYNCHRONOUS,
            ("comp:producer",),
        )
    with pytest.raises(ConcurrencyValidationError, match="must not be 'none'"):
        AtomicRegion(
            "atom:none",
            "comp:producer",
            ("step:prod-write",),
            AtomicityKind.NONE,
        )


def test_session_duality_validates_and_is_involutive() -> None:
    assert dual_polarity(SessionPolarity.SEND) is SessionPolarity.RECEIVE
    assert dual_polarity(SessionPolarity.RECEIVE) is SessionPolarity.SEND
    assert dual_polarity(SessionPolarity.END) is SessionPolarity.END
    assert dual_role(SessionRole.CLIENT) is SessionRole.SERVER

    document = _producer_consumer()
    client = next(item for item in document.sessions if item.role is SessionRole.CLIENT)
    server = next(item for item in document.sessions if item.role is SessionRole.SERVER)
    assert client.is_dual_of(server)
    assert server.is_dual_of(client)

    twice = client.dual().dual(protocol_id=client.protocol_id, name=client.name)
    # Dual of dual restores polarities and role.
    assert twice.role is client.role
    assert [item.polarity for item in twice.actions] == [
        item.polarity for item in client.actions
    ]

    broken_server = SessionProtocol(
        "sess:broken",
        "Broken",
        SessionRole.SERVER,
        (
            SessionAction(
                "sess:req",
                SessionPolarity.SEND,  # should be RECEIVE for dual of client
                "request",
                payload_sort="Item",
                continuation_action_ids=("sess:ack",),
            ),
            SessionAction(
                "sess:ack",
                SessionPolarity.SEND,
                "ack",
                payload_sort="Ack",
                continuation_action_ids=("sess:end",),
            ),
            SessionAction("sess:end", SessionPolarity.END, "end"),
        ),
        entry_action_id="sess:req",
        dual_protocol_id="sess:client",
    )
    with pytest.raises(ConcurrencyValidationError, match="not dual"):
        ConcurrencyIR(
            components=document.components,
            steps=document.steps,
            shared_variable_ids=document.shared_variable_ids,
            atomic_regions=document.atomic_regions,
            interference=document.interference,
            fairness=document.fairness,
            sessions=(
                replace(client, dual_protocol_id="sess:broken"),
                broken_server,
            ),
            require_interference=True,
            require_fairness=True,
        )


def test_bounded_schedules_never_claim_unbounded_refinement() -> None:
    with pytest.raises(ConcurrencyValidationError, match="never claim unbounded"):
        BoundedSchedule(
            "sched:bad",
            max_steps=4,
            claims_unbounded_refinement=True,
        )
    schedule = BoundedSchedule("sched:ok", max_steps=4)
    assert schedule.claims_unbounded_refinement is False
    assert schedule.max_steps == 4


# ---------------------------------------------------------------------------
# RefinementIR
# ---------------------------------------------------------------------------


def test_refinement_ir_round_trip_identity_and_interface() -> None:
    document = _counter_refinement()
    assert document.interface == REFINEMENT_IR_INTERFACE
    assert document.INTERFACE == REFINEMENT_IR_INTERFACE
    assert document.abstract_systems()
    assert document.concrete_systems()
    assert document.system("sys:abstract-flag").level is SystemLevel.ABSTRACT

    rebuilt = RefinementIR.from_dict(document.to_dict())
    assert rebuilt == document
    assert rebuilt.document_id == document.document_id
    with pytest.raises(FrozenInstanceError):
        document.document_id = "changed"  # type: ignore[misc]
    with pytest.raises(RefinementValidationError, match="does not match"):
        replace(document, document_id="bafkbad")


def test_forward_and_backward_simulation_relations_validate() -> None:
    document = _counter_refinement()
    forward = document.simulations[0]
    assert forward.direction is SimulationDirection.FORWARD
    # Structural validation already ran during construction.
    forward.validate_against(
        document.system("sys:abstract-flag"),
        document.system("sys:concrete-counter"),
    )

    # Backward simulation: reverse the roles of matching by relating each
    # concrete initial to an abstract initial and matching concrete steps.
    abstract = RefinementSystem(
        "sys:abs-b",
        SystemLevel.ABSTRACT,
        "AbsB",
        states=(
            RefinementState("a0", "a0", is_initial=True),
            RefinementState("a1", "a1"),
        ),
        transitions=(
            RefinementTransition("at", "a0", "a1", "go"),
        ),
    )
    concrete = RefinementSystem(
        "sys:con-b",
        SystemLevel.CONCRETE,
        "ConB",
        states=(
            RefinementState("c0", "c0", is_initial=True),
            RefinementState("c1", "c1"),
        ),
        transitions=(
            RefinementTransition("ct", "c0", "c1", "go"),
        ),
    )
    backward = SimulationRelation(
        "sim:back",
        SimulationDirection.BACKWARD,
        abstract_system_id="sys:abs-b",
        concrete_system_id="sys:con-b",
        couples=(
            SimulationCouple("cb0", "a0", "c0"),
            SimulationCouple("cb1", "a1", "c1"),
        ),
    )
    document_b = RefinementIR(
        systems=(abstract, concrete),
        simulations=(backward,),
    )
    assert document_b.simulations[0].direction is SimulationDirection.BACKWARD

    # Missing matching transition fails closed.
    bad_concrete = RefinementSystem(
        "sys:con-bad",
        SystemLevel.CONCRETE,
        "ConBad",
        states=(
            RefinementState("c0", "c0", is_initial=True),
            RefinementState("c1", "c1"),
        ),
        transitions=(),  # no enable transition
    )
    with pytest.raises(RefinementValidationError, match="fails to match"):
        RefinementIR(
            systems=(document.system("sys:abstract-flag"), bad_concrete),
            simulations=(
                SimulationRelation(
                    "sim:bad",
                    SimulationDirection.FORWARD,
                    abstract_system_id="sys:abstract-flag",
                    concrete_system_id="sys:con-bad",
                    couples=(
                        SimulationCouple("x0", "abs:off", "c0"),
                        SimulationCouple("x1", "abs:on", "c1"),
                    ),
                ),
            ),
        )


def test_bounded_refinement_never_claims_unbounded() -> None:
    with pytest.raises(RefinementValidationError, match="never claim unbounded"):
        RefinementBoundedness(
            "bound:bad",
            BoundednessKind.BOUNDED,
            "bounded but claims unbounded",
            max_steps=3,
            claims_unbounded_refinement=True,
        )
    with pytest.raises(RefinementValidationError, match="never claim unbounded"):
        SimulationRelation(
            "sim:bad-bound",
            SimulationDirection.FORWARD,
            abstract_system_id="sys:a",
            concrete_system_id="sys:c",
            couples=(SimulationCouple("c1", "a0", "c0"),),
            max_matching_steps=2,
            claims_unbounded_refinement=True,
        )
    with pytest.raises(RefinementValidationError, match="finite schedule bounds"):
        RefinementBoundedness(
            "bound:unbounded-with-steps",
            BoundednessKind.UNBOUNDED,
            "unbounded with steps",
            max_steps=5,
            claims_unbounded_refinement=True,
        )

    bound = RefinementBoundedness(
        "bound:ok",
        BoundednessKind.BOUNDED,
        "ok",
        max_steps=8,
        claims_unbounded_refinement=False,
    )
    assert bound.kind is BoundednessKind.BOUNDED
    assert bound.claims_unbounded_refinement is False


def test_refinement_requires_abstract_and_concrete_systems() -> None:
    only_abstract = RefinementSystem(
        "sys:only-abs",
        SystemLevel.ABSTRACT,
        "OnlyAbs",
        states=(RefinementState("s0", "s0", is_initial=True),),
    )
    with pytest.raises(RefinementValidationError, match="concrete system"):
        RefinementIR(systems=(only_abstract,))

    only_concrete = RefinementSystem(
        "sys:only-con",
        SystemLevel.CONCRETE,
        "OnlyCon",
        states=(RefinementState("s0", "s0", is_initial=True),),
    )
    with pytest.raises(RefinementValidationError, match="abstract system"):
        RefinementIR(systems=(only_concrete,))


def test_simulation_obligation_requires_relation_and_levels() -> None:
    document = _counter_refinement()
    with pytest.raises(RefinementValidationError, match="require simulation_relation_id"):
        RefinementObligation(
            "obl:missing-sim",
            RefinementKind.SIMULATION,
            "missing relation",
            abstract_system_id="sys:abstract-flag",
            concrete_system_id="sys:concrete-counter",
        )

    with pytest.raises(RefinementValidationError, match="must reference an abstract"):
        RefinementIR(
            systems=document.systems,
            simulations=document.simulations,
            obligations=(
                RefinementObligation(
                    "obl:swap",
                    RefinementKind.STATE,
                    "swapped levels",
                    abstract_system_id="sys:concrete-counter",
                    concrete_system_id="sys:abstract-flag",
                ),
            ),
        )


def test_forward_simulation_initial_coupling_required() -> None:
    abstract = RefinementSystem(
        "sys:a",
        SystemLevel.ABSTRACT,
        "A",
        states=(
            RefinementState("a0", "a0", is_initial=True),
            RefinementState("a1", "a1"),
        ),
        transitions=(RefinementTransition("t", "a0", "a1", "go"),),
    )
    concrete = RefinementSystem(
        "sys:c",
        SystemLevel.CONCRETE,
        "C",
        states=(
            RefinementState("c0", "c0", is_initial=True),
            RefinementState("c1", "c1"),
        ),
        transitions=(RefinementTransition("t", "c0", "c1", "go"),),
    )
    with pytest.raises(RefinementValidationError, match="initial state"):
        RefinementIR(
            systems=(abstract, concrete),
            simulations=(
                SimulationRelation(
                    "sim:no-init",
                    SimulationDirection.FORWARD,
                    abstract_system_id="sys:a",
                    concrete_system_id="sys:c",
                    couples=(
                        # Relates abstract initial only to non-initial concrete.
                        SimulationCouple("bad", "a0", "c1"),
                        SimulationCouple("ok", "a1", "c1"),
                    ),
                ),
            ),
        )


def test_metadata_and_attributes_are_frozen() -> None:
    payload = {"nested": {"values": [1]}}
    step = ConcurrentStep(
        "step:meta",
        StepOwner.ENVIRONMENT,
        "meta",
        attributes=payload,
    )
    payload["nested"]["values"].append(2)
    assert step.attributes["nested"]["values"] == (1,)

    couple = SimulationCouple(
        "c:meta",
        "a0",
        "c0",
        attributes={"tag": ["x"]},
    )
    assert couple.attributes.to_dict()["tag"] == ["x"]
