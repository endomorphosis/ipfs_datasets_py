"""Typed interpretations preserve the original counter fixture and real semantics.

The interpretation is authored evidence, not learned state or recovered source
code. Its explicit arithmetic effects supplement opaque native edge labels.
"""
from copy import deepcopy
from pathlib import Path
import os

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression, ProgramIR, ProgramSymbol
from ipfs_datasets_py.logic.software_verification.refinement import RefinementIR
from ipfs_datasets_py.logic.formalization.autoencoder.native_refinement_lean import emit_refinement
from ipfs_datasets_py.logic.formalization.autoencoder.native_symbolic_refinement_lean import INTERPRETATION_SCHEMA
from ipfs_datasets_py.logic.formalization.autoencoder.native_interpretation_expressions import digest, make_carrier
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake_v5 import _execute
from tests.unit.logic.software_verification.test_concurrency_refinement import _counter_refinement


def authored_interpretation(original_payload):
    """Explicitly authored Int counter interpretation of this exact native fixture.

    ``n`` is mathematical Int; enable adds one; disable resets to zero; the tau
    edge preserves n. These are supplied assumptions and never label inference.
    """
    assert original_payload == _counter_refinement().to_dict()
    source = SourceRef("source:counter-native", "urn:authored:counter-refinement-interpretation",
        "counter-refinement-native-declaration", "v1", digest(original_payload))
    mapped = {"source_ref_ids": (source.ref_id,)}
    def literal(key, value):
        return ProgramExpression(key, "literal", "boolean" if type(value) is bool else "integer",
            attributes={"value": value}, **mapped)
    def binary(key, operator, left, right, kind="boolean"):
        return ProgramExpression(key, "binary", kind, operand_ids=(left, right), operator=operator, **mapped)
    true = literal("truth", True)
    abstract = make_carrier((), (true,), sources=(source,))
    concrete = make_carrier((ProgramSymbol("n", "n", "integer", "global", **mapped),), (
        true, literal("zero", 0), literal("one", 1), literal("two", 2), literal("falsity", False),
        ProgramExpression("n", "symbol", "integer", symbol_ids=("n",), **mapped),
        ProgramExpression("oldn", "old", "integer", operand_ids=("n",), **mapped),
        binary("eq0", "eq", "n", "zero"), binary("eq1", "eq", "n", "one"),
        binary("ge2", "ge", "n", "two"), binary("increment", "add", "oldn", "one", "integer"),
        binary("update_increment", "eq", "n", "increment"), binary("update_stutter", "eq", "n", "oldn"),
    ), sources=(source,))
    ref = "urn:authored:counter-refinement-interpretation:v1"
    state_roots = {"abs:off": "truth", "abs:on": "truth", "con:0": "eq0", "con:1": "eq1", "con:2": "ge2"}
    edge_roots = {"abs:t-on": "truth", "abs:t-off": "truth", "con:inc0": "update_increment",
        "con:inc1": "update_increment", "con:reset": "eq0", "con:reset2": "eq0", "con:stutter2": "update_stutter"}
    systems = []
    for system in original_payload["systems"]:
        is_concrete = system["system_id"] == "sys:concrete-counter"
        systems.append({"system_id": system["system_id"], "expression_program": concrete if is_concrete else abstract,
            "state_predicates": [{"state_id": state["state_id"], "statement": state["predicate_statement"],
                "expression_id": state_roots[state["state_id"]], "evidence_ref": ref} for state in system["states"]],
            "transition_relations": [{"transition_id": edge["transition_id"], "expression_id": edge_roots[edge["transition_id"]],
                "semantics": "caller_declared_before_after_relation", "evidence_ref": ref} for edge in system["transitions"]],
            "initial_witness": {"state_id": "con:0" if is_concrete else "abs:off", "values": {"n": 0} if is_concrete else {}}})
    bindings = []
    for collection, identity, meaning in (("simulations", "relation_id", "simulation"),
            ("obligations", "obligation_id", "simulation"), ("boundedness", "boundedness_id", "bounded_simulation")):
        bindings.extend({"collection": collection, "record_id": row[identity], "statement": row["statement"],
            "semantics": meaning, "evidence_ref": ref} for row in original_payload[collection])
    return {"schema": INTERPRETATION_SCHEMA, "native_document_sha256": digest(original_payload),
        "systems": systems, "statement_bindings": bindings,
        "metadata_annotation": {"metadata": deepcopy(original_payload["metadata"]),
            "role": "descriptive_annotation", "evidence_ref": ref}}


def fixture():
    payload = _counter_refinement().to_dict()
    return payload, authored_interpretation(payload)


def lake(source):
    executable = os.environ.get("IR384_TEST_LAKE_EXECUTABLE")
    if not executable:
        pytest.skip("Set IR384_TEST_LAKE_EXECUTABLE for real native Lean execution")
    assert Path(executable).is_file()
    return _execute("set_option autoImplicit false\nnamespace SymbolicRefinementTest\n" + source +
        "\nend SymbolicRefinementTest\n", "SymbolicRefinementTest", executable, 60)


def rebound(payload, interpretation):
    payload.pop("document_id", None)
    payload = RefinementIR.from_dict(payload).to_dict()
    interpretation["native_document_sha256"] = digest(payload)
    return payload, interpretation


def test_original_fixture_identity_is_preserved_and_context_is_explicit():
    payload, interpretation = fixture()
    saved = deepcopy((payload, interpretation))
    assert payload["document_id"] == "bafkreiez2r7wsvzszqam7znnmwph4zemcvaegodbdyoxxnbyrdnq6ekt7y"
    with pytest.raises(UnsupportedNativeLean): emit_refinement(payload)
    source, details = emit_refinement(payload, interpretation=interpretation)
    assert (payload, interpretation) == saved
    assert details["payload_sha256"] == digest(payload)
    assert details["interpretation_sha256"] == digest(interpretation)
    assert "originalRefinementDeclaration" in source and "explicitRefinementInterpretation" in source
    assert "boundedSymbolicSimulation" in source and "def obligation_0 : Prop" in source
    assert not details["proof_obligations_asserted"] and not details["source_semantics_verified"]
    assert not details["source_meaning_inferred"] and not details["capability_floor_eligible"]
    assert not details["obligation_decision_procedure_executed"]


def test_original_context_builds_with_nontrivial_typed_integer_predicates_and_effects():
    payload, interpretation = fixture()
    source, details = emit_refinement(payload, interpretation=interpretation)
    assert details["transition_symbols"]["sys:concrete-counter/con:inc1"] == "System_1.edge_1"
    extra = '''
example : System_1.valid ⟨"con:2", ⟨1000000⟩⟩ = true := by decide
example : System_1.valid ⟨"con:2", ⟨1⟩⟩ = false := by decide
example : System_1.edge_1 ⟨"con:1", ⟨1⟩⟩ ⟨"con:2", ⟨2⟩⟩ = true := by decide
example : System_1.edge_1 ⟨"con:1", ⟨1⟩⟩ ⟨"con:2", ⟨3⟩⟩ = false := by decide
example : System_1.edge_3 ⟨"con:2", ⟨1000000⟩⟩ ⟨"con:0", ⟨0⟩⟩ = true := by decide
example : System_1.silent ⟨"con:2", ⟨2⟩⟩ ⟨"con:2", ⟨2⟩⟩ = true := by decide
example : System_1.silent ⟨"con:2", ⟨2⟩⟩ ⟨"con:2", ⟨3⟩⟩ = false := by decide
example : related_0 ⟨"abs:on", {}⟩ ⟨"con:2", ⟨1000000⟩⟩ := by unfold related_0; decide
example : symbolicVisibleMatch System_1.system 1 ⟨"con:2", ⟨2⟩⟩ "disable" ⟨"con:0", ⟨0⟩⟩ := by
  exact Or.inl (by decide)
'''
    receipt = lake(source + extra)
    assert receipt["status"] == "passed", receipt


def test_false_transition_theorem_is_rejected_by_the_real_kernel():
    payload, interpretation = fixture()
    source, _ = emit_refinement(payload, interpretation=interpretation)
    receipt = lake(source + '\nexample : System_1.edge_1 ⟨"con:1", ⟨1⟩⟩ ⟨"con:2", ⟨3⟩⟩ = true := by decide\n')
    assert receipt["backend_executed"] and receipt["status"] == "failed", receipt


def test_false_initial_witness_cannot_create_vacuous_refinement_success():
    payload, interpretation = fixture()
    interpretation["systems"][1]["initial_witness"]["values"]["n"] = 1
    source, _ = emit_refinement(payload, interpretation=interpretation)
    receipt = lake(source)
    assert receipt["backend_executed"] and receipt["status"] == "failed", receipt


def test_disabling_reset_relations_exposes_a_real_refinement_counterexample():
    payload, interpretation = fixture()
    for edge in interpretation["systems"][1]["transition_relations"]:
        if edge["transition_id"] in ("con:reset", "con:reset2"):
            edge["expression_id"] = "falsity"
    source, details = emit_refinement(payload, interpretation=interpretation)
    # Native graph labels still pass the structural parser; typed edge semantics
    # make disable impossible, including after any finite silent prefix.
    extra = '''
theorem noDisable (budget : Nat) (before after : System_1.Configuration) :
    ¬ symbolicVisibleMatch System_1.system budget before "disable" after := by
  induction budget generalizing before with
  | zero => simp [symbolicVisibleMatch]
  | succ budget ih =>
    intro h
    rcases h with h | ⟨middle, _, remaining⟩
    · simp [System_1.system, System_1.visible, System_1.edge_2, System_1.edge_3,
        System_1.edgeRelation_2, System_1.edgeRelation_3] at h
    · exact ih middle remaining
example : ¬ obligation_0 := by
  intro h
  have related : related_0 ⟨"abs:on", {}⟩ ⟨"con:2", ⟨2⟩⟩ := by unfold related_0; decide
  have step := (h.2.2.2 ⟨"abs:on", {}⟩ ⟨"con:2", ⟨2⟩⟩ related).2 "disable" ⟨"abs:off", {}⟩ (by decide)
  rcases step with ⟨other, matching, _⟩
  exact noDisable 4 _ other matching
'''
    receipt = lake(source + extra)
    assert receipt["status"] == "passed", receipt
    assert not details["proof_obligations_asserted"]


def test_same_declared_label_never_silently_invents_arithmetic_updates():
    payload, interpretation = fixture()
    original, original_details = emit_refinement(payload, interpretation=interpretation)
    interpretation["systems"][1]["transition_relations"][1]["expression_id"] = "truth"
    changed, changed_details = emit_refinement(payload, interpretation=interpretation)
    assert original_details["payload_sha256"] == changed_details["payload_sha256"]
    assert original_details["interpretation_sha256"] != changed_details["interpretation_sha256"]
    # An explicitly unconstrained edge relation permits this successor; the
    # original authored increment relation rejects it in the preceding tests.
    receipt = lake(changed + '\nexample : System_1.edge_1 ⟨"con:1", ⟨1⟩⟩ ⟨"con:2", ⟨3⟩⟩ = true := by decide\n')
    assert receipt["status"] == "passed", receipt
    assert original != changed


def test_symbolic_silent_prefix_updates_state_and_consumes_matching_budget():
    payload, interpretation = fixture()
    concrete = interpretation["systems"][1]
    carrier = concrete["expression_program"]
    mapped = {"source_ref_ids": ("source:counter-native",)}
    carrier["expressions"].extend(expression.to_dict() for expression in (
        ProgramExpression("three", "literal", "integer", attributes={"value": 3}, **mapped),
        ProgramExpression("oldge3", "binary", "boolean", operand_ids=("oldn", "three"), operator="ge", **mapped),
        ProgramExpression("guarded_reset", "binary", "boolean", operand_ids=("eq0", "oldge3"), operator="and", **mapped)))
    carrier.pop("program_id")
    concrete["expression_program"] = ProgramIR.from_dict(carrier).to_dict()
    for edge in concrete["transition_relations"]:
        if edge["transition_id"] == "con:stutter2": edge["expression_id"] = "update_increment"
        if edge["transition_id"] == "con:reset2": edge["expression_id"] = "guarded_reset"
    source, _ = emit_refinement(payload, interpretation=interpretation)
    # This separate authored interpretation explicitly changes tau to increment
    # n, and permits reset only once old(n)>=3. Nothing is inferred from labels.
    extra = '''
example : ¬ symbolicVisibleMatch System_1.system 1 ⟨"con:2", ⟨2⟩⟩ "disable" ⟨"con:0", ⟨0⟩⟩ := by
  simp [symbolicVisibleMatch, System_1.system, System_1.visible, System_1.edge_2, System_1.edge_3,
    System_1.edgeRelation_3]
example : symbolicVisibleMatch System_1.system 2 ⟨"con:2", ⟨2⟩⟩ "disable" ⟨"con:0", ⟨0⟩⟩ := by
  exact Or.inr ⟨⟨"con:2", ⟨3⟩⟩, by decide, Or.inl (by decide)⟩
'''
    receipt = lake(source + extra)
    assert receipt["status"] == "passed", receipt


@pytest.mark.parametrize("mutation,reason", [
    ("native_hash", "native_document_differs"), ("unknown_field", "closed_symbolic"),
    ("missing_edge", "complete_refinement_transition"), ("missing_state", "complete_refinement_state"),
    ("extra_system", "exact_refinement_system"), ("duplicate_edge", "complete_refinement_transition"),
    ("predicate_erased", "does_not_match_source"), ("predicate_changed", "statement_binding_differs"),
    ("old_state", "time_scope_mismatch"), ("integer_edge", "root_type_mismatch"),
    ("unknown_statement", "statement_binding_differs"), ("statement_erased", "complete_refinement_statement"),
    ("metadata_erased", "exact_descriptive_annotation"), ("boolean_integer", "witness_value"),
    ("missing_witness_symbol", "complete_refinement_initial_witness"), ("blank_evidence", "evidence_reference"),
])
def test_incomplete_or_semantically_different_interpretations_are_rejected(mutation, reason):
    payload, interpretation = fixture()
    concrete = interpretation["systems"][1]
    if mutation == "native_hash": interpretation["native_document_sha256"] = "0" * 64
    elif mutation == "unknown_field": interpretation["trusted"] = True
    elif mutation == "missing_edge": concrete["transition_relations"].pop()
    elif mutation == "missing_state": concrete["state_predicates"].pop()
    elif mutation == "extra_system": interpretation["systems"].append(deepcopy(concrete))
    elif mutation == "duplicate_edge": concrete["transition_relations"].append(deepcopy(concrete["transition_relations"][0]))
    elif mutation == "predicate_erased": concrete["state_predicates"][2]["expression_id"] = "truth"
    elif mutation == "predicate_changed": concrete["state_predicates"][2]["statement"] = "true"
    elif mutation == "old_state": concrete["state_predicates"][2]["expression_id"] = "update_stutter"
    elif mutation == "integer_edge": concrete["transition_relations"][0]["expression_id"] = "n"
    elif mutation == "unknown_statement": interpretation["statement_bindings"][0]["statement"] = "all executions safe"
    elif mutation == "statement_erased": interpretation["statement_bindings"].pop()
    elif mutation == "metadata_erased": interpretation["metadata_annotation"]["metadata"] = {}
    elif mutation == "boolean_integer": concrete["initial_witness"]["values"]["n"] = False
    elif mutation == "missing_witness_symbol": concrete["initial_witness"]["values"] = {}
    else: concrete["transition_relations"][0]["evidence_ref"] = " "
    with pytest.raises(UnsupportedNativeLean, match=reason):
        emit_refinement(payload, interpretation=interpretation)


@pytest.mark.parametrize("statement,reason", [("m >= 2", "variable_requires_explicit_type"),
    ("danger(n)", "AST_node_not_supported"), ("n >= 2 and __import__('os')", "AST_node_not_supported"),
    ("0 <= n <= 2", "comparison_not_supported"), ("n / 2 >= 0", "binary_operator_not_supported")])
def test_opaque_source_grammar_cannot_be_guessed_or_executed(statement, reason):
    payload, interpretation = fixture()
    payload["systems"][1]["states"][2]["predicate_statement"] = statement
    interpretation["systems"][1]["state_predicates"][2]["statement"] = statement
    payload, interpretation = rebound(payload, interpretation)
    with pytest.raises(UnsupportedNativeLean, match=reason):
        emit_refinement(payload, interpretation=interpretation)


def test_uninterpreted_metadata_is_still_rejected_even_with_an_annotation_label():
    payload, interpretation = fixture()
    payload["metadata"]["assume_secure"] = True
    interpretation["metadata_annotation"]["metadata"] = deepcopy(payload["metadata"])
    payload, interpretation = rebound(payload, interpretation)
    with pytest.raises(UnsupportedNativeLean, match="exact_descriptive_annotation"):
        emit_refinement(payload, interpretation=interpretation)


def test_data_couple_relation_cannot_be_erased_by_a_statement_binding():
    payload, interpretation = fixture()
    payload["simulations"][0]["couples"][0]["statement"] = "left.n = right.n"
    payload, interpretation = rebound(payload, interpretation)
    with pytest.raises(UnsupportedNativeLean, match="couple_data_relation_not_lowered"):
        emit_refinement(payload, interpretation=interpretation)
