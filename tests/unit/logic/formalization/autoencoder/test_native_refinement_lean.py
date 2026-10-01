"""Native finite simulation formulas, exercised by the real Lean kernel."""
from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_verification.refinement import (
    RefinementIR, RefinementSystem, RefinementState, RefinementTransition,
    SimulationRelation, SimulationCouple, RefinementBoundedness, RefinementObligation,
)
from ipfs_datasets_py.logic.formalization.autoencoder.native_refinement_lean import emit_refinement
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake_v5 import _execute


def fixture(direction="forward", *, disabled_target=False, extra_concrete_edge=False):
    abstract = RefinementSystem("abstract", "abstract", "Abstract", states=(
        RefinementState("a0", "initial", is_initial=True), RefinementState("a1", "done", is_terminal=True)),
        transitions=(RefinementTransition("at", "a0", "a1", "finish"),))
    concrete = RefinementSystem("concrete", "concrete", "Concrete", states=(
        RefinementState("c0", "initial", is_initial=True), RefinementState("c1", "done", is_terminal=True,
            predicate_statement="false" if disabled_target else "true")),
        transitions=(RefinementTransition("ct", "c0", "c1", "finish"),) +
            ((RefinementTransition("extra", "c0", "c1", "unmatched"),) if extra_concrete_edge else ()))
    simulation = SimulationRelation("related", direction, "abstract", "concrete", couples=(
        SimulationCouple("pair0", "a0", "c0"), SimulationCouple("pair1", "a1", "c1")), max_matching_steps=1)
    bound = RefinementBoundedness("bound", "bounded", "bounded simulation", max_steps=2)
    obligation = RefinementObligation("goal", "simulation", "simulation", "abstract", "concrete",
        simulation_relation_id="related", boundedness_id="bound")
    return RefinementIR((abstract, concrete), (simulation,), (obligation,), (bound,))


def lake(source):
    path = os.environ.get("IR384_TEST_LAKE_EXECUTABLE")
    if not path:
        pytest.skip("Set IR384_TEST_LAKE_EXECUTABLE for real native Lean execution")
    assert Path(path).is_file()
    return _execute("namespace NativeRefinementTest\n" + source + "\nend NativeRefinementTest\n",
        "NativeRefinementTest", path, 60)


@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_complete_native_roundtrip_and_explicit_bound(direction):
    payload = fixture(direction).to_dict()
    saved = deepcopy(payload)
    source, details = emit_refinement(payload)
    assert payload == saved
    assert "boundedSimulation" in source and "obligation_0" in source and "simulation_0 2" in source
    assert details["simulation_symbols"] == {"related": "simulation_0"}
    assert not details["source_semantics_verified"] and not details["proof_obligations_asserted"]
    assert not details["capability_floor_eligible"]


@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_real_lake_computes_supported_directional_obligation(direction):
    source, _ = emit_refinement(fixture(direction).to_dict())
    result = lake(source + "\nexample : obligation_0_check = true := by decide\n")
    assert result["status"] == "passed", result


def test_constant_false_target_is_a_real_counterexample_not_dropped_metadata():
    source, _ = emit_refinement(fixture(disabled_target=True).to_dict())
    assert lake(source + "\nexample : obligation_0_check = false := by decide\n")["status"] == "passed"
    result = lake(source + "\nexample : obligation_0_check = true := by decide\n")
    assert result["backend_executed"] and result["status"] != "passed"


def test_direction_is_not_silently_swapped():
    # Native FORWARD is abstract-leading: extra concrete behavior is permitted.
    source, _ = emit_refinement(fixture(extra_concrete_edge=True).to_dict())
    assert lake(source + "\nexample : obligation_0_check = true := by decide\n")["status"] == "passed"
    with pytest.raises(ValueError, match="backward simulation"):
        fixture("backward", extra_concrete_edge=True)


@pytest.mark.parametrize("change,reason", [
    ("predicate", "state_predicate"), ("metadata", "metadata"),
    ("couple", "couple_predicate"), ("concurrency", "concurrency_link"),
    ("state_bound", "state_budget"), ("bound_missing", "exact_bound"),
    ("relation_bound", "matching_steps"), ("trace_kind", "simulation_obligation"),
    ("stutter", "stutter"),
])
def test_uninterpreted_or_unsupported_semantics_remain_blocked(change, reason):
    original = fixture()
    if change == "predicate":
        system = replace(original.systems[0], states=(replace(original.systems[0].states[0], predicate_statement="n >= 2"), original.systems[0].states[1]))
        changed = replace(original, systems=(system, original.systems[1]), document_id="")
    elif change == "metadata": changed = replace(original, metadata={"assume": "safe"}, document_id="")
    elif change == "couple": changed = replace(original, simulations=(replace(original.simulations[0], couples=(
        replace(original.simulations[0].couples[0], statement="x = y"), original.simulations[0].couples[1])),), document_id="")
    elif change == "concurrency": changed = replace(original, systems=(replace(original.systems[0], concurrency_document_id="foreign"), original.systems[1]), document_id="")
    elif change == "state_bound": changed = replace(original, boundedness=(replace(original.boundedness[0], max_states=2),), document_id="")
    elif change == "bound_missing": changed = replace(original, obligations=(replace(original.obligations[0], boundedness_id=""),), document_id="")
    elif change == "relation_bound": changed = replace(original, simulations=(replace(original.simulations[0], max_matching_steps=None),), document_id="")
    elif change == "trace_kind": changed = replace(original, obligations=(replace(original.obligations[0], kind="trace"),), document_id="")
    else:
        system = replace(original.systems[1], transitions=original.systems[1].transitions +
            (RefinementTransition("stutter", "c1", "c1", "tau", is_stutter=True),))
        changed = replace(original, systems=(original.systems[0], system), document_id="")
    with pytest.raises(UnsupportedNativeLean, match=reason): emit_refinement(changed.to_dict())


def test_no_unknown_json_field_can_be_lost_in_model_reconstruction():
    payload = fixture().to_dict()
    payload["simulations"][0]["ignored"] = True
    with pytest.raises(ValueError): emit_refinement(payload)


def test_original_counter_example_remains_blocked_instead_of_erasing_data_predicates():
    from tests.unit.logic.software_verification.test_concurrency_refinement import _counter_refinement
    with pytest.raises(UnsupportedNativeLean): emit_refinement(_counter_refinement().to_dict())


def test_all_disabled_initial_states_cannot_create_vacuous_success():
    original = fixture()
    changed = replace(original, systems=tuple(replace(system, states=tuple(
        replace(state, predicate_statement="false") if state.is_initial else state for state in system.states))
        for system in original.systems), document_id="")
    with pytest.raises(UnsupportedNativeLean, match="satisfiable_initial"):
        emit_refinement(changed.to_dict())


@pytest.mark.parametrize("part", ["relation", "obligation", "bound"])
def test_stronger_prose_cannot_become_an_unchecked_annotation(part):
    original = fixture()
    field = {"relation": "simulations", "obligation": "obligations", "bound": "boundedness"}[part]
    changed = replace(original, **{field: (replace(getattr(original, field)[0], statement="also proves all executions secure"),)}, document_id="")
    with pytest.raises(UnsupportedNativeLean, match="statement_requires_typed"):
        emit_refinement(changed.to_dict())
