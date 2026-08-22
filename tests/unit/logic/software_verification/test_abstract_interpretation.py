"""Executable laws and frontend cases for the initial abstract interpreter."""

from __future__ import annotations

import pytest
from ipfs_datasets_py.logic.software_verification.abstract_interpretation import (
    AbstractDomain,
    AbstractStore,
    AnalysisConfig,
    ConstantValue,
    EffectKind,
    EffectState,
    ExceptionState,
    IntervalValue,
    NullnessKind,
    NullnessValue,
    ProductValue,
    SoundnessClass,
    analyze_abstract_state,
    solve_worklist_fixpoint,
)


@pytest.mark.parametrize(
    "values",
    [
        (ConstantValue.bottom(), ConstantValue.constant(1), ConstantValue.top()),
        (IntervalValue.bottom(), IntervalValue(0, 1), IntervalValue.top()),
        (
            NullnessValue.bottom(),
            NullnessValue(NullnessKind.NONNULL),
            NullnessValue.top(),
        ),
        (
            ExceptionState.bottom(),
            ExceptionState(frozenset({"ValueError"})),
            ExceptionState.top(),
        ),
        (
            EffectState.bottom(),
            EffectState.bottom().add(EffectKind.READ, "x"),
            EffectState.top(),
        ),
    ],
)
def test_domain_lattice_laws(values: tuple[AbstractDomain, ...]) -> None:
    """Each component obeys bounded-lattice ordering and basic algebraic laws."""

    bottom, middle, top = values
    assert bottom.less_equal(middle)
    assert middle.less_equal(top)
    assert middle.join(bottom).abstract_equal(middle)
    assert middle.meet(top).abstract_equal(middle)
    assert middle.join(top).abstract_equal(top)
    assert middle.meet(bottom).abstract_equal(bottom)
    assert middle.join(middle).abstract_equal(middle)
    assert middle.meet(middle).abstract_equal(middle)


def test_product_join_is_a_sound_upper_bound_and_transfer_is_monotone() -> None:
    narrow = ProductValue.from_interval(IntervalValue(1, 2))
    broad = ProductValue.from_interval(IntervalValue(0, 5))
    delta = IntervalValue.constant(3)

    joined = narrow.join(broad)
    assert narrow.less_equal(joined)
    assert broad.less_equal(joined)
    assert narrow.interval.add(delta).less_equal(broad.interval.add(delta))


def test_interval_widening_converges_and_narrowing_recovers_bounds() -> None:
    value = IntervalValue(0, 0)
    for upper in range(1, 100):
        value = value.widen(IntervalValue(0, upper))

    assert value == IntervalValue(0, None)
    assert value.narrow(IntervalValue(0, 10)) == IntervalValue(0, 10)


def test_bounded_worklist_uses_widening_and_reaches_fixpoint() -> None:
    entry = AbstractStore().set("x", ProductValue.from_constant(0))

    def transfer(node: str, state: AbstractStore) -> AbstractStore:
        if node != "loop" or not state.reachable:
            return state
        current = state.get("x")
        incremented = ProductValue.from_interval(
            current.interval.add(IntervalValue.constant(1))
        )
        return state.set("x", incremented)

    result = solve_worklist_fixpoint(
        entry_node="entry",
        initial_state=entry,
        successors={"entry": ("loop",), "loop": ("loop", "exit"), "exit": ()},
        transfer=transfer,
        max_iterations=20,
        widening_after=1,
        narrowing_iterations=0,
    )

    assert result.converged
    assert "loop" in result.widened_nodes
    assert result.by_node["exit"].get("x").interval.upper is None


def test_unreachable_program_point_is_preserved() -> None:
    result = analyze_abstract_state(
        """
def stop():
    return 1
    impossible = 2
""",
        source_uri="fixture://unreachable.py",
    )

    summary = result.summaries_by_name["stop"]
    impossible = [point for point in summary.program_points if point.line == 4]
    assert len(impossible) == 1
    assert not impossible[0].state.reachable
    assert summary.return_value.constant == ConstantValue.constant(1)


def test_exceptional_flow_is_propagated_conservatively() -> None:
    result = analyze_abstract_state(
        """
def divide(value: int):
    if value == 0:
        raise ValueError("zero")
    return 10 // value
""",
        source_uri="fixture://exceptions.py",
    )

    exceptions = result.summaries_by_name["divide"].contract_candidate.possible_exceptions
    assert "ValueError" in exceptions.exceptions
    # The interval domain cannot express non-zero as a hole, so division must
    # retain this possible exception rather than silently assuming it away.
    assert "ZeroDivisionError" in exceptions.exceptions


def test_conditionally_defined_local_retains_unbound_exception() -> None:
    result = analyze_abstract_state(
        """
def maybe(flag):
    if flag:
        value = 1
    return value
""",
        source_uri="fixture://definedness.py",
    )

    exceptions = result.summaries_by_name["maybe"].contract_candidate.possible_exceptions
    assert "UnboundLocalError" in exceptions.exceptions


def test_local_call_uses_interprocedural_summary() -> None:
    result = analyze_abstract_state(
        """
def base():
    return 2

def consumer():
    return base() + 3
""",
        source_uri="fixture://interprocedural.py",
    )

    consumer = result.summaries_by_name["consumer"]
    assert consumer.return_value.constant == ConstantValue.constant(5)
    assert consumer.return_value.interval == IntervalValue.constant(5)
    assert any(
        effect.kind is EffectKind.CALL and effect.target == "base"
        for effect in consumer.contract_candidate.effects.effects
    )


def test_context_insensitive_policy_uses_reusable_broad_summary() -> None:
    source = """
def increment(value: int):
    return value + 1

def consumer():
    return increment(2)
"""
    sensitive = analyze_abstract_state(source, source_uri="fixture://context.py")
    insensitive = analyze_abstract_state(
        source,
        source_uri="fixture://context.py",
        config=AnalysisConfig(context_sensitive=False),
    )

    assert sensitive.summaries_by_name["consumer"].return_value.interval == IntervalValue.constant(3)
    assert insensitive.summaries_by_name["consumer"].return_value.interval == IntervalValue.top()


def test_loop_fixpoint_generates_a_bounded_summary() -> None:
    result = analyze_abstract_state(
        """
def count():
    index = 0
    while index < 10:
        index += 1
    return index
""",
        source_uri="fixture://loop.py",
    )

    summary = result.summaries_by_name["count"]
    assert summary.converged
    assert summary.iterations > 1
    assert summary.return_value.interval == IntervalValue.constant(10)
    assert "index >= 0" in summary.generated_invariants
    assert "index <= 10" in summary.generated_invariants


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("def dynamic(text):\n    return eval(text)\n", "dynamic_call:eval"),
        ("def callback(fn):\n    return fn(1)\n", "opaque_callback:fn"),
        ("import ctypes\ndef native():\n    return 1\n", "native_extension_import"),
        ("def reflected(obj, name):\n    return getattr(obj, name)\n", "dynamic_call:getattr"),
        ("def external():\n    return input()\n", "uncontrolled_io:input"),
        (
            "import importlib\ndef dynamic_module(name):\n    return importlib.import_module(name)\n",
            "dynamic_call:importlib.import_module",
        ),
    ],
)
def test_dynamic_and_native_frontiers_become_explicitly_opaque(
    source: str,
    reason: str,
) -> None:
    result = analyze_abstract_state(source, source_uri="fixture://opaque.py")

    assert result.soundness is SoundnessClass.OPAQUE
    assert any(reason in item for item in result.unsupported_constructs)


def test_analysis_identity_binds_source_and_analyzer_configuration() -> None:
    source = "def answer():\n    return 42\n"
    first = analyze_abstract_state(source, source_uri="fixture://identity.py")
    replay = analyze_abstract_state(source, source_uri="fixture://identity.py")
    changed_source = analyze_abstract_state(
        source.replace("42", "43"), source_uri="fixture://identity.py"
    )
    changed_config = analyze_abstract_state(
        source,
        source_uri="fixture://identity.py",
        config=AnalysisConfig(max_iterations=8),
    )

    assert first.analysis_id == replay.analysis_id
    assert first.source_identity == replay.source_identity
    assert first.analysis_id != changed_source.analysis_id
    assert first.source_identity != changed_source.source_identity
    assert first.analyzer_identity != changed_config.analyzer_identity
    assert first.analysis_id != changed_config.analysis_id
