"""Detached semantic requests reach native output without a source or target shortcut."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.autoformal import legal_coordination as bridge
from ipfs_datasets_py.logic.autoformal import legal_coordination_evaluation as evaluation
from ipfs_datasets_py.logic.deontic import coordination, coordination_decoder as decoder
from ipfs_datasets_py.logic.deontic.exports import build_document_export_tables_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils import deontic_parser
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as emitters


SOURCE = "The Secretary shall publish the notice or shall retain the record."


def prepared(source=SOURCE, *, scope="modal_over_actions", source_id="fixture:one"):
    group, = coordination.build_coordination_groups(source, source_id=source_id)
    declaration = bridge.interpretation_skeleton(group)
    declaration.update(modal_scope=scope, connective="inclusive_or", binding_profile="universal_actor_predicate")
    compiled = bridge.compile_coordination_group(group, declaration)
    return compiled, bridge.coordination_decode_request_from_compiled(compiled)


def no_source_dependencies(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("source/teacher dependency was consulted during detached decoding")
    for module, names in (
        (coordination, ("build_coordination_groups", "reconstruct_source", "validate_coordination_group")),
        (deontic_parser, ("extract_normative_elements", "analyze_normative_sentence", "_unresolved_duty_disjunction_groups")),
        (bridge, ("compile_coordination_group", "reconstruct_compiled_group", "coordination_decode_request_from_compiled")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)


@pytest.mark.parametrize("scope", ["modal_over_actions", "disjunction_of_norms"])
def test_detached_decode_requires_no_source_parser_group_or_teacher_access(monkeypatch, scope):
    compiled, request = prepared(scope=scope)
    expected_formula, expected_ast = compiled["formula"], deepcopy(compiled["native_ast"])
    original = request.to_dict()
    assert set(original) == {"schema", "modal_scope", "connective", "binding_profile", "members"}
    assert all(set(member) == {"actor", "modality", "action"} for member in original["members"])
    no_source_dependencies(monkeypatch)
    decoded = decoder.decode_coordination_request(request)
    assert decoded["formula"] == expected_formula
    assert decoded["native_ast"] == expected_ast
    assert decoded["context"] == "source_withheld_semantic_ir"
    assert decoded["proof_ready"] is decoded["source_semantics_verified"] is False
    assert decoded["requires_validation"] is True
    assert decoded["family_validation"]["passed"] is True
    assert request.to_dict() == original


def test_different_original_surface_and_identity_produce_identical_detached_decoding():
    first, left = prepared()
    second, right = prepared("The Secretary must publish the notice or must retain the record!", source_id="fixture:other")
    assert first["source_sha256"] != second["source_sha256"]
    assert first["group_id"] != second["group_id"]
    assert left.to_dict() == right.to_dict()
    assert decoder.decode_coordination_request(left) == decoder.decode_coordination_request(right)


@pytest.mark.parametrize("scope", ["modal_over_actions", "disjunction_of_norms"])
def test_detached_decoder_does_not_promote_original_branch_scaffolds(scope):
    _, request = prepared(scope=scope)
    assert decoder.decode_coordination_request(request)["structure_compiled"] is True
    norms = [LegalNormIR.from_parser_element(row) for row in deontic_parser.extract_normative_elements(SOURCE)]
    tables = build_document_export_tables_from_ir(norms)
    for table in ("canonical", "formal_logic", "proof_obligations"):
        for row in tables[table]:
            assert row["proof_ready"] is False
            assert "formula_coordination_scope_unresolved" in row["blockers"]


@pytest.mark.parametrize("bad", [None, {}, {"formula": "O(Target)"}, {"members": []}])
def test_malformed_candidate_cannot_borrow_reference_formula_or_fields(monkeypatch, bad):
    _, reference = prepared()
    observed = []
    original_decode = decoder.decode_coordination_request
    def traced(request):
        observed.append(request.to_dict())
        return original_decode(request)
    monkeypatch.setattr(evaluation, "decode_coordination_request", traced)
    result = evaluation.evaluate_coordination_outputs([reference], [bad])
    assert observed == [reference.to_dict()]
    assert result["invalid_output_count"] == result["failed_count"] == 1
    assert result["passed_count"] == 0
    row, = result["cases"]
    assert "candidate_formula" not in row and "candidate_normalized_text" not in row
    assert all(value == 0 for value in result["measure_counts"].values())


def test_evaluation_decodes_actual_wrong_output_independently_of_reference(monkeypatch):
    _, reference = prepared()
    candidate = reference.to_dict()
    candidate["members"][0]["action"] = "withhold the notice"
    expected = decoder.decode_coordination_request(decoder.CoordinationDecodeRequest.from_dict(candidate))
    observed = []
    original_decode = decoder.decode_coordination_request
    def traced(request):
        observed.append(request.to_dict())
        return original_decode(request)
    monkeypatch.setattr(evaluation, "decode_coordination_request", traced)
    result = evaluation.evaluate_coordination_outputs([reference], [candidate])
    assert observed == [reference.to_dict(), candidate]
    row, = result["cases"]
    assert row["candidate_formula"] == expected["formula"]
    assert row["candidate_normalized_text"] == expected["normalized_text"]
    assert row["action_equal"] is row["native_ast_exact_match"] is False
    assert result["passed_count"] == 0
    assert result["model_calls"] == result["training_calls"] == 0


def native_decoder_countermodel_source():
    """Author semantic IR directly; no original source is supplied to this route."""
    requests, records = [], []
    for scope in ("modal_over_actions", "disjunction_of_norms"):
        request = decoder.CoordinationDecodeRequest.from_dict({
            "schema": decoder.COORDINATION_DECODE_REQUEST_SCHEMA,
            "modal_scope": scope, "connective": "inclusive_or", "binding_profile": "universal_actor_predicate",
            "members": [{"actor": "secretary", "modality": "O", "action": "publish the notice"},
                        {"actor": "secretary", "modality": "O", "action": "retain the record"}],
        })
        requests.append(request.to_dict())
        records.append(decoder.decode_coordination_request(request))
    wide, narrow = records
    assert wide["mapping"] == narrow["mapping"]
    actor, = wide["mapping"]["actor_symbols"]
    action_a, action_b = wide["mapping"]["action_symbols"]
    source = emitters.PRELUDE + "\n"
    for namespace, result in (("Wide", wide), ("Narrow", narrow)):
        source += f"namespace {namespace}\n{result['lean_body']}\nend {namespace}\n"
    source += f'''
def twoWorlds : Interpretation Unit Unit where
  agent := fun _ => ()
  cognitive := fun _ _ p => p
  constant := fun _ => ()
  function := fun _ _ => ()
  atom := fun name _ t => name = {json.dumps(actor["symbol"])} ∨
    (name = {json.dumps(action_a["symbol"])} ∧ t = 0) ∨
    (name = {json.dumps(action_b["symbol"])} ∧ t = 1)
  modal := fun _ _ _ p _ => p 0 ∧ p 1
  frame := fun _ _ _ => False
  frameScalar := fun _ _ => ()
  member := fun _ _ => False
  subclass := fun _ _ => False
example : Wide.formula_0 twoWorlds 0 := by
  simp [Wide.formula_0, twoWorlds]
example : ¬ Narrow.formula_0 twoWorlds 0 := by
  simp [Narrow.formula_0, twoWorlds]
example : ¬ (Wide.formula_0 twoWorlds 0 → Narrow.formula_0 twoWorlds 0) := by
  simp [Wide.formula_0, Narrow.formula_0, twoWorlds]
'''
    return source, requests, records


def run_lake(directory, source, *, executable=None):
    executable = executable or os.environ.get("IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE")
    if not executable:
        pytest.skip("set explicit installed Lake executable")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "lakefile.toml").write_text('name = "grouped_decoder_witness"\nversion = "0.1.0"\n[[lean_lib]]\nname = "legal"\nroots = ["DecoderWitness"]\n')
    (directory / "DecoderWitness.lean").write_text(source)
    return subprocess.run([str(Path(executable).resolve()), "build", "legal"], cwd=directory,
                          text=True, capture_output=True, timeout=60)


def test_real_lake_decoded_scopes_have_distinct_authored_countermodels(tmp_path, monkeypatch):
    no_source_dependencies(monkeypatch)
    source, _, _ = native_decoder_countermodel_source()
    result = run_lake(tmp_path, source)
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_lake_rejects_false_claim_from_detached_decoder_output(tmp_path, monkeypatch):
    no_source_dependencies(monkeypatch)
    source, _, _ = native_decoder_countermodel_source()
    source += '\nexample : Narrow.formula_0 twoWorlds 0 := by\n  simp [Narrow.formula_0, twoWorlds]\n'
    result = run_lake(tmp_path, source)
    assert result.returncode != 0
    assert "error:" in result.stdout + result.stderr
