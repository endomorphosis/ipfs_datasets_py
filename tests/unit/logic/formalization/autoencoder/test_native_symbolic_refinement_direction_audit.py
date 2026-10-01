"""Independent direction and silent-leading audit of the symbolic projection.

The fixture deliberately gives an abstract edge a false typed relation while
its concrete counterpart is enabled. The native graph remains structurally
valid in either direction, so only the symbolic semantics can tell them apart.
"""
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression
from ipfs_datasets_py.logic.software_verification.refinement import RefinementTransition
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.logic.formalization.autoencoder.native_interpretation_expressions import digest, make_carrier
from ipfs_datasets_py.logic.formalization.autoencoder.native_refinement_lean import emit_refinement
from ipfs_datasets_py.logic.formalization.autoencoder.native_symbolic_refinement_lean import INTERPRETATION_SCHEMA
from tests.unit.logic.formalization.autoencoder.test_native_refinement_lean import fixture as graph_fixture
from tests.unit.logic.formalization.autoencoder.test_native_symbolic_refinement_lean import lake


def interpreted_fixture(direction, *, leading_stutter=False):
    native = graph_fixture(direction)
    if leading_stutter:
        index = 0 if direction == "forward" else 1
        system = native.systems[index]
        initial = next(state.state_id for state in system.states if state.is_initial)
        stutter = RefinementTransition("audit:tau", initial, initial, "tau", is_stutter=True)
        systems = list(native.systems)
        systems[index] = replace(system, transitions=(*system.transitions, stutter))
        native = replace(native, systems=tuple(systems), document_id="")
    payload = native.to_dict()
    source = SourceRef("audit:source", "urn:authored:symbolic-refinement-direction-audit",
        "explicit-direction-audit", "v1", digest(payload))
    expressions = tuple(ProgramExpression(key, "literal", "boolean", attributes={"value": value},
        source_ref_ids=(source.ref_id,)) for key, value in (("truth", True), ("falsity", False)))
    carrier = make_carrier((), expressions, sources=(source,))
    reference = "urn:authored:symbolic-refinement-direction-audit:v1"
    systems = []
    for system in payload["systems"]:
        systems.append({"system_id": system["system_id"], "expression_program": carrier,
            "state_predicates": [{"state_id": state["state_id"], "statement": state["predicate_statement"],
                "expression_id": "truth", "evidence_ref": reference} for state in system["states"]],
            "transition_relations": [{"transition_id": edge["transition_id"],
                "expression_id": "falsity" if system["system_id"] == "abstract" else "truth",
                "semantics": "caller_declared_before_after_relation", "evidence_ref": reference}
                for edge in system["transitions"]],
            "initial_witness": {"state_id": next(state["state_id"] for state in system["states"]
                if state["is_initial"]), "values": {}}})
    bindings = []
    for collection, identity, meaning in (("simulations", "relation_id", "simulation"),
            ("obligations", "obligation_id", "simulation"), ("boundedness", "boundedness_id", "bounded_simulation")):
        bindings.extend({"collection": collection, "record_id": row[identity], "statement": row["statement"],
            "semantics": meaning, "evidence_ref": reference} for row in payload[collection])
    interpretation = {"schema": INTERPRETATION_SCHEMA, "native_document_sha256": digest(payload),
        "systems": systems, "statement_bindings": bindings,
        "metadata_annotation": {"metadata": payload["metadata"], "role": "descriptive_annotation",
            "evidence_ref": reference}}
    return payload, interpretation


FORWARD_PROOF = '''
theorem audit_no_abstract_step (before after : System_0.Configuration) (label : String) :
    System_0.system.visible before label after = false := by
  simp [System_0.system, System_0.visible, System_0.edge_0, System_0.edgeRelation_0]
theorem audit_forward_match (steps : Nat) (left : System_0.Configuration)
    (right : System_1.Configuration) (related : related_0 left right) :
    boundedSymbolicMatch System_0.system System_1.system related_0 1 steps left right := by
  cases steps with
  | zero => exact related
  | succ steps =>
    refine And.intro related ?_
    intro label next step
    rw [audit_no_abstract_step] at step
    contradiction
example (steps : Nat) : simulation_0 steps =
    boundedSymbolicSimulation System_0.system System_1.system related_0 1 steps := rfl
theorem audit_forward_valid : obligation_0 := by
  refine And.intro ⟨System_0.initialWitness, by decide⟩ ?_
  refine And.intro ⟨System_1.initialWitness, by decide⟩ ?_
  constructor
  · intro left initial
    refine ⟨System_1.initialWitness, by decide, audit_forward_match 2 left System_1.initialWitness ?_⟩
    have initial_parts : System_0.valid left = true ∧ left.node = "a0" := by
      simpa [System_0.system, System_0.initial] using initial
    unfold related_0
    exact ⟨initial_parts.1, by decide, Or.inl ⟨initial_parts.2, rfl⟩⟩
  · intro left right related
    exact audit_forward_match 2 left right related
'''


BACKWARD_PROOF = '''
example (steps : Nat) : simulation_0 steps =
    boundedSymbolicSimulation System_1.system System_0.system related_0 1 steps := rfl
theorem audit_backward_invalid : ¬ obligation_0 := by
  intro obligation
  have related : related_0 ⟨"c0", {}⟩ ⟨"a0", {}⟩ := by unfold related_0; decide
  have step := (obligation.2.2.2 ⟨"c0", {}⟩ ⟨"a0", {}⟩ related).2
    "finish" ⟨"c1", {}⟩ (by decide)
  rcases step with ⟨other, matching, _⟩
  simp [symbolicVisibleMatch, System_0.system, System_0.visible, System_0.silent,
    System_0.edge_0, System_0.edgeRelation_0] at matching
'''


@pytest.mark.parametrize("direction,proof", [("forward", FORWARD_PROOF), ("backward", BACKWARD_PROOF)],
    ids=["forward-valid", "backward-invalid"])
def test_real_lake_proves_asymmetric_directional_verdict(direction, proof):
    payload, interpretation = interpreted_fixture(direction)
    source, details = emit_refinement(payload, interpretation=interpretation)
    result = lake(source + proof)
    assert result["backend_executed"] and result["status"] == "passed", result
    assert not details["proof_obligations_asserted"]
    assert not details["source_semantics_verified"]


@pytest.mark.parametrize("direction,proof,false_proof", [
    ("forward", FORWARD_PROOF,
        'example : System_0.system.visible ⟨"a0", {}⟩ "finish" ⟨"a1", {}⟩ = true := by decide'),
    ("backward", BACKWARD_PROOF,
        'example : System_1.system.visible ⟨"c0", {}⟩ "finish" ⟨"c1", {}⟩ = false := by decide'),
], ids=["forward-leading-disabled", "backward-leading-enabled"])
def test_real_lake_rejects_swapped_leading_behavior(direction, proof, false_proof):
    payload, interpretation = interpreted_fixture(direction)
    source, _ = emit_refinement(payload, interpretation=interpretation)
    result = lake(source + proof + "\n" + false_proof)
    assert result["backend_executed"] and result["status"] == "failed", result


@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_leading_stutter_cannot_disappear_in_either_direction(direction):
    payload, interpretation = interpreted_fixture(direction, leading_stutter=True)
    with pytest.raises(UnsupportedNativeLean, match="leading_symbolic_refinement_stutters"):
        emit_refinement(payload, interpretation=interpretation)
