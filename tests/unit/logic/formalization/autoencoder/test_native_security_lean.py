"""Kernel checked finite-heap and two-trace declaration semantics."""
import copy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_security_lean as emit
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake import _execute
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.logic.software_verification.heap import HeapModel, PointsToCell
from ipfs_datasets_py.logic.software_verification.separation import (
    SeparationLogicIR, points_to_formula, sep_conj, ordinary_and, pure_formula,
)
from ipfs_datasets_py.logic.software_verification.hyperproperties import HyperpropertyIR
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel


def fixtures():
    inputs = panel.source_inputs(panel.rows("security_ir", "train")[0])
    return tuple(item.document.to_dict() for item in inputs["typed_inputs"][4:7])


def lake(source, extra=""):
    paths = sorted((Path.home()/".elan"/"toolchains").glob("*/bin/lake"))
    if not paths:
        pytest.skip("Installed Lake unavailable; no download attempted")
    result = _execute("set_option autoImplicit false\nnamespace SecurityIR\n" + source + "\n" + extra + "\nend SecurityIR\n", "SecurityIR", paths[-1], 30)
    return result


def rebuild(value, cls):
    result = copy.deepcopy(value)
    result.pop("document_id", None)
    return cls.from_dict(result).to_dict()


def spatial(kind="sep_conj", same_location=False):
    heap, document, _ = fixtures()
    source = heap["locations"][0]["source_ref_ids"]
    first = heap["locations"][0]["location_id"]
    second = first
    if not same_location:
        item = copy.deepcopy(heap["locations"][0])
        item.update(location_id="loc:other", name="other")
        heap["locations"].append(item)
        second = item["location_id"]
    value = heap["values"][0]["value_id"]
    document["heap"] = HeapModel.from_dict(heap).to_dict()
    nodes = [points_to_formula("p", first, value, source_ref_ids=source),
             points_to_formula("q", second, value, source_ref_ids=source)]
    combine = sep_conj if kind == "sep_conj" else ordinary_and
    nodes.append(combine("root", "p", "q", source_ref_ids=source))
    document["formulas"] = [node.to_dict() for node in nodes]
    document["root_formula_id"] = "root"
    return rebuild(document, SeparationLogicIR)


def test_actual_native_three_payloads_compile_without_admitting_claims():
    heap, separation, hyper = fixtures()
    parts = []
    for namespace, render, payload in [("Heap", emit.emit_heap, heap),
                                      ("SL", emit.emit_separation, separation),
                                      ("Hyper", emit.emit_hyperproperty, hyper)]:
        source, details = render(payload)
        assert details["admitted"] is False and details["source_semantics_verified"] is False
        parts.append("namespace " + namespace + "\n" + source + "\nend " + namespace)
    result = lake("\n".join(parts))
    assert result["status"] == "passed", result


def test_disjoint_heap_union_is_satisfiable_and_not_ordinary_conjunction():
    source, _ = emit.emit_separation(spatial())
    extra = """
def interpretation : HeapInterpretation := ⟨fun name => if name = "loc:cell" then 0 else 1⟩
def leftHeap : Heap := singletonHeap 0 (HeapValue.integer 0)
def rightHeap : Heap := singletonHeap 1 (HeapValue.integer 0)
example : separationFormula interpretation (unionHeap leftHeap rightHeap) := by
  constructor
  · refine ⟨[0, 1], ?_⟩
    intro address h
    by_cases zero : address = 0
    · simp [zero]
    · by_cases one : address = 1
      · simp [one]
      · simp [unionHeap, leftHeap, rightHeap, singletonHeap, zero, one] at h
  · refine ⟨leftHeap, rightHeap, singletonHeap_finite _ _, singletonHeap_finite _ _, ?_, rfl, rfl, rfl⟩
    intro address
    by_cases zero : address = 0
    · right; simp [rightHeap, singletonHeap, zero]
    · left; simp [leftHeap, singletonHeap, zero]
"""
    result = lake(source, extra)
    assert result["status"] == "passed", result


def test_same_address_separation_is_impossible_but_ordinary_conjunction_holds():
    separated, _ = emit.emit_separation(spatial(same_location=True))
    extra = """
example (i : HeapInterpretation) (heap : Heap) : ¬ separationFormula i heap := by
  intro claim
  rcases claim.2 with ⟨left, right, _, _, disjoint, _, lp, rp⟩
  change left = singletonHeap (location_0 i) value_0 at lp
  change right = singletonHeap (location_0 i) value_0 at rp
  subst left; subst right
  exact singleton_not_disjoint_with_itself _ _ disjoint
"""
    result = lake(separated, extra)
    assert result["status"] == "passed", result
    conjunction, _ = emit.emit_separation(spatial(kind="and", same_location=True))
    result = lake(conjunction, "example (i : HeapInterpretation) : separationFormula i (singletonHeap (location_0 i) value_0) := ⟨singletonHeap_finite _ _, rfl, rfl⟩")
    assert result["status"] == "passed", result


def test_different_identifiers_are_not_assumed_nonaliasing():
    source, _ = emit.emit_separation(spatial())
    result = lake(source, """
def aliases : HeapInterpretation := ⟨fun _ => 0⟩
example (heap : Heap) : ¬ separationFormula aliases heap := by
  intro claim
  rcases claim.2 with ⟨left, right, _, _, disjoint, _, lp, rp⟩
  change left = singletonHeap 0 value_0 at lp
  change right = singletonHeap 0 value_0 at rp
  subst left; subst right
  exact singleton_not_disjoint_with_itself _ _ disjoint
""")
    assert result["status"] == "passed", result


def test_empty_heap_and_integer_boolean_values_do_not_collapse():
    heap, separation, _ = fixtures()
    item = copy.deepcopy(heap["values"][0]); item.update(value_id="val:boolean", kind="boolean", type_name="boolean", literal="false")
    heap["values"].append(item)
    heap["values"][0]["literal"] = "-2"
    source, _ = emit.emit_heap(HeapModel.from_dict(heap).to_dict())
    result = lake(source, """
example : HeapValue.integer 0 ≠ HeapValue.boolean false := by decide
example : value_0 = HeapValue.boolean false := rfl
example : value_1 = HeapValue.integer (-2) := rfl
example : emp emptyHeap := rfl
example : ¬ emp (singletonHeap 0 (HeapValue.integer 0)) := by
  intro h
  have atZero := congrFun h 0
  simp [singletonHeap, emptyHeap] at atZero
""")
    assert result["status"] == "passed", result


HYPER_VIEWS = """
def safeView : ExecutionView Int := ⟨fun _ => 0, fun _ => 1, fun _ => 0⟩
def leakingView : ExecutionView Int := ⟨fun _ => 0, fun _ => 2, fun _ => 1⟩
def leakingExecutions (trace : ExecutionView Int) : Prop := trace = safeView ∨ trace = leakingView
"""


def test_hyperproperty_can_reject_leak_without_asserting_program_noninterference():
    _, _, payload = fixtures()
    source, details = emit.emit_hyperproperty(payload)
    assert details["capability_floor_eligible"] is False
    assert details["temporal_execution_bound_checked"] is False
    assert "some 4" in source
    extra = HYPER_VIEWS + """
example : noninterference (fun trace => trace = safeView) := by
  intro left hl right hr _
  subst left; subst right; rfl
example : ¬ noninterference leakingExecutions := by
  intro claim
  have contradiction := claim safeView (Or.inl rfl) leakingView (Or.inr rfl) rfl
  simp [observationProjection, observationFields, safeView, leakingView] at contradiction
example : sampleWithinCompositionBudget [safeView, leakingView] := by
  simp [sampleWithinCompositionBudget, maxTraces, maxPairs]
example : temporalExecutionBoundChecked = false := rfl
"""
    result = lake(source, extra)
    assert result["status"] == "passed", result
    failed = lake(source, HYPER_VIEWS + "example : noninterference leakingExecutions := by simp [noninterference, leakingExecutions, lowProjection, lowFields, observationProjection, observationFields, safeView, leakingView]")
    assert failed["status"] == "failed" and failed["returncode"] != 0


@pytest.mark.parametrize("field", ["metadata", "ownership", "aliases", "resource_units", "resource_algebras"])
def test_nonmodeled_heap_fields_are_never_silently_dropped(field):
    heap, _, _ = fixtures()
    heap[field] = {"opaque": True} if field == "metadata" else [{"opaque": True}]
    with pytest.raises((UnsupportedNativeLean, ValueError, TypeError)):
        emit.emit_heap(heap)


def test_fractional_cells_opaque_formulas_and_unknown_fields_fail_closed():
    heap, separation, _ = fixtures()
    sources = heap["locations"][0]["source_ref_ids"]
    cell = PointsToCell("cell", "loc:cell", "val:result", source_ref_ids=tuple(sources)).to_dict()
    cell["permission"] = {"numerator": 1, "denominator": 2}
    heap["cells"] = [cell]
    with pytest.raises((UnsupportedNativeLean, ValueError), match="permission"):
        emit.emit_heap(HeapModel.from_dict(heap).to_dict())
    separation["formulas"] = [pure_formula("opaque", "heap is safe", source_ref_ids=sources).to_dict()]
    separation["root_formula_id"] = "opaque"
    with pytest.raises(UnsupportedNativeLean, match="opaque"):
        emit.emit_separation(rebuild(separation, SeparationLogicIR))
    heap, _, _ = fixtures(); heap["future_semantics"] = True
    with pytest.raises(ValueError): emit.emit_heap(heap)


def test_actual_allocated_heap_fragment_has_full_permission_cell_semantics():
    heap, _, _ = fixtures()
    sources = heap["locations"][0]["source_ref_ids"]
    heap["cells"] = [PointsToCell("cell", "loc:cell", "val:result", source_ref_ids=tuple(sources)).to_dict()]
    source, details = emit.emit_heap(HeapModel.from_dict(heap).to_dict())
    assert details["allocated_cells"] == 1 and details["capability_floor_eligible"] is True
    result = lake(source, """
example (i : HeapInterpretation) :
    declaredHeapFragment i (unionHeap (singletonHeap (location_0 i) value_0) emptyHeap) := by
  refine ⟨singletonHeap (location_0 i) value_0, emptyHeap,
    singletonHeap_finite _ _, emptyHeap_finite, ?_, rfl, rfl, rfl⟩
  intro address; right; rfl
""")
    assert result["status"] == "passed", result


@pytest.mark.parametrize("kind", ["wand", "septraction"])
def test_unsupported_resource_connectives_are_not_boolean_implications(kind):
    payload = spatial()
    payload["heap_theory"] = "custom"
    next(row for row in payload["formulas"] if row["formula_id"] == "root")["kind"] = kind
    with pytest.raises(UnsupportedNativeLean, match="extra_theory"):
        emit.emit_separation(rebuild(payload, SeparationLogicIR))


def test_failing_heap_proof_cannot_claim_overlapping_resource_ownership():
    source, _ = emit.emit_separation(spatial(same_location=True))
    result = lake(source, "example (i : HeapInterpretation) : separationFormula i (singletonHeap (location_0 i) value_0) := by simp [separationFormula, formula_0, formula_1, formula_2, separating, pointsTo]")
    assert result["status"] == "failed" and result["returncode"] != 0


@pytest.mark.parametrize("mutation", [
    lambda p: p["formula"].update(matrix_statement="forall traces. True"),
    lambda p: p["formula"]["quantifier_prefix"][0].update(quantifier="exists"),
    lambda p: p["formula"]["postconditions"][0]["atoms"][0].update(operator="not_equal"),
    lambda p: p["metadata"].update(opaque=True),
])
def test_noncanonical_hyperproperty_never_becomes_opaque_true_or_fresh_atom(mutation):
    _, _, payload = fixtures(); mutation(payload)
    with pytest.raises((UnsupportedNativeLean, ValueError)):
        emit.emit_hyperproperty(rebuild(payload, HyperpropertyIR))


def test_policy_field_selection_and_caps_are_retained_without_time_semantics():
    _, _, payload = fixtures()
    baseline, _ = emit.emit_hyperproperty(payload)
    payload["information_flow_policy"]["observation_fields"] = ["response.status"]
    payload["self_composition_bound"].update(max_steps=None, max_traces=3, max_pairs=2)
    source, _ = emit.emit_hyperproperty(rebuild(payload, HyperpropertyIR))
    assert source != baseline
    assert '["response.status"]' in source and "declaredMaxSteps : Option Nat := none" in source
    assert "maxTraces : Nat := 3" in source and "maxPairs : Nat := 2" in source
    assert "temporalExecutionBoundChecked : Bool := false" in source


def test_exact_route_bindings_are_required_and_unowned_routes_are_delegated():
    heap, _, _ = fixtures()
    with pytest.raises(NotImplementedError): emit.emit_projection({"projection_id": "other"})
    with pytest.raises(UnsupportedNativeLean, match="route"):
        emit.emit_projection(dict(projection_id="separation_logic.heap_model/v1", logic_family="program", profile="heap_model", payload=heap))
    source, _ = emit.emit_projection(dict(projection_id="separation_logic.heap_model/v1", logic_family="separation_logic", profile="heap_model", payload=heap))
    assert "def declaredHeapFragment" in source
