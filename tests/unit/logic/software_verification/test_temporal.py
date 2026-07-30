"""Contracts for typed trace and temporal semantics."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, replace

import pytest
from ipfs_datasets_py.logic.software_verification.temporal import (
    DeclarationOnlySemanticsError,
    Monitorability,
    PathQuantifier,
    SemanticsDomainMismatchError,
    TemporalFormula,
    TemporalLogic,
    TemporalOperator,
    TemporalValidationError,
    TemporalVerdict,
    TimeInterval,
    always,
    binary,
    eventually,
    monitor_prefix,
    next_time,
    unary,
    until,
)
from ipfs_datasets_py.logic.software_verification.trace import (
    Clock,
    ClockDomain,
    Event,
    ObservationPolicy,
    ObservationPolicyKind,
    ObservationValue,
    TimePoint,
    TimeUnit,
    TimeValue,
    TraceIR,
    TraceKind,
    TraceValidationError,
)


def _clock(
    *,
    domain: ClockDomain = ClockDomain.DISCRETE,
    unit: TimeUnit = TimeUnit.LOGICAL_TICK,
    resolution: TimeValue | None = None,
) -> Clock:
    return Clock("clock:main", domain, unit, resolution or TimeValue(1))


def _event(
    index: int,
    *true: str,
    false: tuple[str, ...] = (),
    time: TimeValue | None = None,
) -> Event:
    return Event(
        f"event:{index}",
        "state",
        TimePoint("clock:main", time or TimeValue(index)),
        true,
        false,
        payload={"sequence": index},
        source_ref_ids=("source:example",),
    )


def _trace(
    kind: TraceKind,
    events: tuple[Event, ...],
    *,
    clock: Clock | None = None,
    policy: ObservationPolicy | None = None,
    loop_start: int | None = None,
) -> TraceIR:
    selected_clock = clock or _clock()
    return TraceIR(
        clocks=(selected_clock,),
        events=events,
        kind=kind,
        observation_policy=policy
        or ObservationPolicy("policy:closed", ObservationPolicyKind.CLOSED_WORLD),
        primary_clock_id=selected_clock.clock_id,
        loop_start=loop_start,
        metadata={"subject": "counter"},
    )


def test_time_values_are_exact_canonical_rationals() -> None:
    assert TimeValue(2, 4) == TimeValue(1, 2)
    assert TimeValue.from_value({"numerator": 9, "denominator": 3}) == TimeValue(3)
    with pytest.raises(TraceValidationError, match="non-negative"):
        TimeValue(-1)
    with pytest.raises(TraceValidationError, match="mapping"):
        TimeValue.from_value(0.1)  # type: ignore[arg-type]
    with pytest.raises(TraceValidationError, match="whole number"):
        Clock(
            "clock:discrete",
            ClockDomain.DISCRETE,
            TimeUnit.SECOND,
            TimeValue(1, 2),
        )


def test_events_and_traces_are_deeply_immutable_and_content_addressed() -> None:
    payload = {"nested": {"values": [1]}}
    event = Event(
        "event:0",
        "request",
        TimePoint("clock:main", TimeValue(0)),
        ("ready",),
        payload=payload,
    )
    payload["nested"]["values"].append(2)
    trace = _trace(TraceKind.FINITE, (event,))
    round_trip = TraceIR.from_dict(trace.to_dict())

    assert event.payload["nested"]["values"] == (1,)
    assert event.kind == "request"
    assert event.timestamp == TimeValue(0)
    assert round_trip == trace
    assert round_trip.trace_id == trace.trace_id
    assert trace.trace_kind is TraceKind.FINITE
    with pytest.raises(TypeError):
        event.payload["changed"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        trace.trace_id = "changed"  # type: ignore[misc]
    with pytest.raises(TraceValidationError, match="does not match"):
        replace(trace, trace_id="bafkbad")


def test_trace_order_is_semantic_and_clock_constraints_fail_closed() -> None:
    first = _event(0, "a")
    second = _event(1, "b")
    trace = _trace(TraceKind.FINITE, (first, second))
    reordered = _trace(
        TraceKind.FINITE,
        (
            replace(second, time=TimePoint("clock:main", TimeValue(0))),
            first,
        ),
    )
    assert trace.trace_id != reordered.trace_id

    with pytest.raises(TraceValidationError, match="non-decreasing"):
        _trace(
            TraceKind.FINITE,
            (
                replace(first, time=TimePoint("clock:main", TimeValue(2))),
                second,
            ),
        )
    with pytest.raises(TraceValidationError, match="resolution"):
        _trace(
            TraceKind.FINITE,
            (_event(0, time=TimeValue(3)),),
            clock=_clock(resolution=TimeValue(2)),
        )
    with pytest.raises(TraceValidationError, match="primary clock"):
        _trace(
            TraceKind.FINITE,
            (
                replace(
                    first,
                    time=TimePoint("clock:other", TimeValue(0)),
                ),
            ),
        )


def test_finite_prefix_and_infinite_lasso_are_not_interchangeable() -> None:
    events = (_event(0, "safe"), _event(1, "safe"))
    with pytest.raises(TraceValidationError, match="requires loop_start"):
        _trace(TraceKind.INFINITE, events)
    with pytest.raises(TraceValidationError, match="only valid"):
        _trace(TraceKind.FINITE_PREFIX, events, loop_start=0)

    infinite = _trace(TraceKind.INFINITE, events, loop_start=1)
    assert infinite.successor(0) == 1
    assert infinite.successor(1) == 1
    assert infinite.is_complete
    assert not _trace(TraceKind.FINITE_PREFIX, events).is_complete


def test_observation_policies_make_absence_explicit() -> None:
    event = _event(0, "present", false=("false",))
    closed = ObservationPolicy("policy:closed", ObservationPolicyKind.CLOSED_WORLD)
    explicit = ObservationPolicy("policy:explicit", ObservationPolicyKind.EXPLICIT)
    projected = ObservationPolicy(
        "policy:projected",
        ObservationPolicyKind.PROJECTED,
        ("visible",),
    )

    assert closed.observe(event, "missing") is ObservationValue.FALSE
    assert explicit.observe(event, "missing") is ObservationValue.UNKNOWN
    assert explicit.observe(event, "false") is ObservationValue.FALSE
    assert projected.observe(event, "visible") is ObservationValue.FALSE
    assert projected.observe(event, "secret") is ObservationValue.UNKNOWN
    with pytest.raises(TraceValidationError, match="both true and false"):
        _event(0, "same", false=("same",))


def test_ltlf_complete_finite_semantics_cover_boolean_and_future_operators() -> None:
    trace = _trace(
        TraceKind.FINITE,
        (
            _event(0, "safe"),
            _event(1, "safe"),
            _event(2, "safe", "done"),
        ),
    )
    safe = TemporalFormula.atom("safe", logic=TemporalLogic.LTLF)
    done = TemporalFormula.atom("done", logic=TemporalLogic.LTLF)

    assert always(safe).evaluate(trace).holds
    assert eventually(done).evaluate(trace).holds
    assert next_time(safe).evaluate(trace).holds
    assert until(safe, done).evaluate(trace).holds
    assert binary(TemporalOperator.IMPLIES, safe, eventually(done)).evaluate(trace).holds
    assert not next_time(done).evaluate(trace, position=2).holds
    assert TemporalFormula.from_dict(always(safe).to_dict()) == always(safe)


def test_ltl_requires_an_infinite_trace_and_uses_lasso_fixed_points() -> None:
    safe = TemporalFormula.atom("safe")
    done = TemporalFormula.atom("done")
    formula = always(eventually(done))
    infinite = _trace(
        TraceKind.INFINITE,
        (
            _event(0, "safe"),
            _event(1, "safe", "done"),
            _event(2, "safe"),
        ),
        loop_start=1,
    )

    result = formula.evaluate(infinite)
    assert result.verdict is TemporalVerdict.TRUE
    assert result.conclusive
    assert not result.authorizes_global_proof
    assert always(safe).evaluate(infinite).holds

    with pytest.raises(SemanticsDomainMismatchError, match="infinite"):
        formula.evaluate(_trace(TraceKind.FINITE, infinite.events))


def test_ltlf_rejects_prefix_and_infinite_trace_domains() -> None:
    formula = always(TemporalFormula.atom("safe", logic=TemporalLogic.LTLF))
    events = (_event(0, "safe"),)
    with pytest.raises(SemanticsDomainMismatchError, match="complete finite"):
        formula.evaluate(_trace(TraceKind.FINITE_PREFIX, events))
    with pytest.raises(SemanticsDomainMismatchError, match="complete finite"):
        formula.evaluate(_trace(TraceKind.INFINITE, events, loop_start=0))


def test_clean_prefix_never_implies_global_truth() -> None:
    prefix = _trace(
        TraceKind.FINITE_PREFIX,
        (_event(0, "safe"), _event(1, "safe")),
    )
    formula = always(TemporalFormula.atom("safe"))
    result = formula.monitor(prefix)

    assert result.verdict is TemporalVerdict.INCONCLUSIVE
    assert not result.conclusive
    assert not result.authorizes_global_proof
    assert result.monitorability is Monitorability.VIOLATION
    with pytest.raises(TemporalValidationError, match="no boolean"):
        _ = result.holds


def test_prefix_monitoring_can_report_finite_witnesses_and_violations() -> None:
    prefix = _trace(
        TraceKind.FINITE_PREFIX,
        (
            _event(0, "safe"),
            _event(1, "safe", "done"),
            _event(2, false=("safe",)),
        ),
        policy=ObservationPolicy("policy:explicit", ObservationPolicyKind.EXPLICIT),
    )
    safe = TemporalFormula.atom("safe")
    done = TemporalFormula.atom("done")

    assert eventually(done).monitor(prefix).verdict is TemporalVerdict.TRUE
    assert always(safe).monitor(prefix).verdict is TemporalVerdict.FALSE
    assert until(safe, done).monitor(prefix).verdict is TemporalVerdict.TRUE
    assert monitor_prefix(next_time(done), prefix).verdict is TemporalVerdict.TRUE
    with pytest.raises(SemanticsDomainMismatchError, match="finite_prefix"):
        monitor_prefix(done, _trace(TraceKind.FINITE, prefix.events))


def test_open_observations_propagate_inconclusive_truth() -> None:
    trace = _trace(
        TraceKind.FINITE,
        (_event(0),),
        policy=ObservationPolicy("policy:explicit", ObservationPolicyKind.EXPLICIT),
    )
    atom = TemporalFormula.atom("unobserved", logic=TemporalLogic.LTLF)
    assert atom.evaluate(trace).verdict is TemporalVerdict.INCONCLUSIVE


def test_mtl_intervals_have_exact_units_and_boundary_semantics() -> None:
    clock = _clock(
        domain=ClockDomain.DENSE,
        unit=TimeUnit.SECOND,
        resolution=TimeValue(1, 2),
    )
    trace = _trace(
        TraceKind.FINITE,
        (
            _event(0, time=TimeValue(0)),
            _event(1, time=TimeValue(1, 2)),
            _event(2, "ready", time=TimeValue(1)),
        ),
        clock=clock,
    )
    ready = TemporalFormula.atom("ready", logic=TemporalLogic.MTL)
    closed = TimeInterval.closed(0, 1, TimeUnit.SECOND)
    open_upper = TimeInterval(
        TimeValue(0),
        TimeValue(1),
        TimeUnit.SECOND,
        upper_closed=False,
    )

    assert eventually(ready, interval=closed).evaluate(trace).holds
    assert not eventually(ready, interval=open_upper).evaluate(trace).holds
    assert TimeInterval.from_dict(closed.to_dict()) == closed
    with pytest.raises(TemporalValidationError, match="must not be empty"):
        TimeInterval(
            TimeValue(1),
            TimeValue(1),
            TimeUnit.SECOND,
            lower_closed=False,
        )
    with pytest.raises(SemanticsDomainMismatchError, match="unit"):
        eventually(
            ready,
            interval=TimeInterval.closed(0, 1, TimeUnit.MILLISECOND),
        ).evaluate(trace)


def test_bounded_mtl_prefix_becomes_conclusive_only_after_its_horizon() -> None:
    clock = _clock(unit=TimeUnit.SECOND)
    ready = TemporalFormula.atom("ready", logic=TemporalLogic.MTL)
    bounded = eventually(
        ready,
        interval=TimeInterval.closed(0, 2, TimeUnit.SECOND),
    )
    early = _trace(
        TraceKind.FINITE_PREFIX,
        (_event(0), _event(1)),
        clock=clock,
    )
    past_horizon = _trace(
        TraceKind.FINITE_PREFIX,
        (_event(0), _event(1), _event(3)),
        clock=clock,
    )

    assert bounded.monitorability is Monitorability.PREFIX
    assert bounded.monitor(early).verdict is TemporalVerdict.INCONCLUSIVE
    assert bounded.monitor(past_horizon).verdict is TemporalVerdict.FALSE


def test_mtl_requires_explicit_intervals_and_rejects_infinite_lassos() -> None:
    atom = TemporalFormula.atom("ready", logic=TemporalLogic.MTL)
    with pytest.raises(TemporalValidationError, match="explicit interval"):
        always(atom)
    bounded = always(
        atom,
        interval=TimeInterval.closed(0, 1, TimeUnit.LOGICAL_TICK),
    )
    with pytest.raises(SemanticsDomainMismatchError, match="lasso"):
        bounded.evaluate(_trace(TraceKind.INFINITE, (_event(0, "ready"),), loop_start=0))


def test_ctl_and_ctl_star_are_typed_declaration_only_surfaces() -> None:
    ctl_atom = TemporalFormula.atom("safe", logic=TemporalLogic.CTL)
    ctl_future = unary(TemporalOperator.ALWAYS, ctl_atom)
    ctl = TemporalFormula.path(PathQuantifier.ALL, ctl_future)
    ctl.validate_root()

    star_atom = TemporalFormula.atom("safe", logic=TemporalLogic.CTL_STAR)
    star_path = TemporalFormula.path(
        PathQuantifier.EXISTS,
        binary(
            TemporalOperator.OR,
            unary(TemporalOperator.EVENTUALLY, star_atom),
            unary(TemporalOperator.ALWAYS, star_atom),
        ),
    )

    assert ctl.declaration_only
    assert ctl.monitorability is Monitorability.DECLARATION_ONLY
    assert star_path.declaration_only
    assert TemporalFormula.from_dict(ctl.to_dict()) == ctl
    with pytest.raises(DeclarationOnlySemanticsError, match="declaration"):
        ctl.evaluate(_trace(TraceKind.FINITE, (_event(0, "safe"),)))
    with pytest.raises(DeclarationOnlySemanticsError, match="declaration"):
        star_path.monitor(_trace(TraceKind.FINITE_PREFIX, (_event(0, "safe"),)))


def test_malformed_ctl_and_cross_logic_trees_fail_closed() -> None:
    ctl_atom = TemporalFormula.atom("safe", logic=TemporalLogic.CTL)
    unquantified = unary(TemporalOperator.ALWAYS, ctl_atom)
    with pytest.raises(TemporalValidationError, match="path quantifier"):
        unquantified.validate_root()

    with pytest.raises(TemporalValidationError, match="same temporal logic"):
        TemporalFormula(
            TemporalOperator.AND,
            TemporalLogic.LTL,
            (
                TemporalFormula.atom("a", logic=TemporalLogic.LTL),
                TemporalFormula.atom("b", logic=TemporalLogic.LTLF),
            ),
        )
    with pytest.raises(TemporalValidationError, match="only valid for CTL"):
        TemporalFormula.path(PathQuantifier.ALL, TemporalFormula.atom("a"))


def test_legacy_state_and_formula_conversion_is_explicit() -> None:
    @dataclass
    class LegacyState:
        time: int
        valuations: dict[str, bool]

    class LegacyAtom:
        def __init__(self, name: str) -> None:
            self.name = name

        def to_string(self) -> str:
            return f"{self.name}()"

    class LegacyOperator:
        name = "ALWAYS"

    class LegacyFormula:
        operator = LegacyOperator()
        formula = LegacyAtom("safe")
        formula2 = None

    trace = TraceIR.from_state_sequence(
        (
            LegacyState(0, {"safe": True}),
            LegacyState(1, {"safe": True}),
        )
    )
    formula = TemporalFormula.from_legacy(LegacyFormula(), logic=TemporalLogic.LTLF)

    assert trace.kind is TraceKind.FINITE
    assert trace.observation_policy.kind is ObservationPolicyKind.EXPLICIT
    assert formula.operator is TemporalOperator.ALWAYS
    assert formula.evaluate(trace).holds


def test_schema_round_trips_reject_unknown_fields_and_stale_ids() -> None:
    formula = eventually(TemporalFormula.atom("done", logic=TemporalLogic.LTLF))
    malformed = formula.to_dict()
    malformed["unexpected"] = True
    with pytest.raises(TemporalValidationError, match="unknown"):
        TemporalFormula.from_dict(malformed)
    with pytest.raises(TemporalValidationError, match="does not match"):
        replace(formula, formula_id="bafkbad")
