"""Declared alternative scope survives native syntax and engineering countermodels."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.autoformal import legal_coordination as bridge
from ipfs_datasets_py.logic.autoformal import family_qualification
from ipfs_datasets_py.logic.deontic.coordination import build_coordination_groups, reconstruct_source
from ipfs_datasets_py.logic.deontic.exports import build_document_export_tables_from_ir, parser_elements_for_metrics
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as emitters


SOURCE = "The Secretary shall publish the notice or shall retain the record."
MARKER = "formula_coordination_scope_unresolved"


def declared(source=SOURCE, *, scope="modal_over_actions"):
    group, = build_coordination_groups(source, source_id="authored:coordination")
    sidecar = bridge.interpretation_skeleton(group)
    sidecar.update(modal_scope=scope, connective="inclusive_or", binding_profile="universal_actor_predicate")
    return group, sidecar


@pytest.mark.parametrize("scope", ["modal_over_actions", "disjunction_of_norms"])
@pytest.mark.parametrize("modal", ["shall", "may", "shall not"])
def test_declared_scope_compiles_but_never_clears_legacy_branch_readiness(scope, modal):
    source = f"The Secretary {modal} publish the notice or {modal} retain the record."
    group, sidecar = declared(source, scope=scope)
    original = deepcopy((group.to_dict(), sidecar))
    result = bridge.compile_coordination_group(group, sidecar)
    assert (group.to_dict(), sidecar) == original
    assert bridge.reconstruct_compiled_group(result) == reconstruct_source(group)
    assert result["source_semantics_verified"] is False
    assert result["admitted"] is result["proof_ready"] is False
    assert result["requires_validation"] is True
    for family in ("deontic_fol", "tdfol"):
        validation = family_qualification.validate_family_artifact(family, result["formula"])
        assert validation["passed"] is True
    rows = extract_normative_elements(source)
    assert rows
    tables = build_document_export_tables_from_ir([LegalNormIR.from_parser_element(row) for row in rows])
    for name in ("canonical", "formal_logic", "proof_obligations"):
        for row in tables[name]:
            assert row["proof_ready"] is False
            assert MARKER in row["blockers"]
    for row in tables["decoder_reconstructions"]:
        assert row["proof_ready"] is False
        assert row["requires_validation"] is True
    projected = parser_elements_for_metrics(rows)
    assert all(row["export_readiness"]["formula_proof_ready"] is False for row in projected)


def test_two_interpretations_of_same_source_retain_distinct_full_native_structure():
    wide_group, wide_declaration = declared()
    narrow_group, narrow_declaration = declared(scope="disjunction_of_norms")
    assert wide_group.to_dict() == narrow_group.to_dict()
    wide = bridge.compile_coordination_group(wide_group, wide_declaration)
    narrow = bridge.compile_coordination_group(narrow_group, narrow_declaration)
    assert wide["formula"] != narrow["formula"]
    assert wide["native_ast"] != narrow["native_ast"]
    assert wide["native_ast"]["node_type"] == "DeonticFormula"
    assert narrow["native_ast"]["node_type"] == "BinaryFormula"
    assert wide["native_ast"]["operator"]["value"] == "O"
    assert narrow["native_ast"]["operator"]["value"] == "∨"
    assert bridge.reconstruct_compiled_group(wide) == bridge.reconstruct_compiled_group(narrow)
    for result in (wide, narrow):
        assert result["native_payload"]["format"] == "native_tdfol_ast"
        code, receipt = emitters.native_modal(result["native_payload"], "tdfol")
        assert code == result["lean_body"]
        assert receipt == result["native_validation"]


@pytest.mark.parametrize("field", ["formula", "native_ast", "lean_body", "proof_ready", "source_semantics_verified"])
def test_group_reconstruction_rejects_rewritten_compiled_records(field):
    group, declaration = declared()
    compiled = bridge.compile_coordination_group(group, declaration)
    altered = deepcopy(compiled)
    if field == "formula":
        altered[field] = "O(∀x. True(x))"
    elif field == "native_ast":
        altered[field]["operator"]["value"] = "P"
    elif field == "lean_body":
        altered[field] += "\n-- unbound replacement"
    else:
        altered[field] = True
    with pytest.raises(ValueError):
        bridge.reconstruct_compiled_group(altered)
    assert bridge.reconstruct_compiled_group(compiled) == reconstruct_source(group)


def native_scope_countermodel_source():
    """Build a fixture from actual compiled outputs under an authored model.

    Two accessible worlds are represented by trace points 0 and 1. The modal
    interpretation requires its argument at both points. This is an engineering
    countermodel for unsafe distribution, not a legal-source interpretation.
    """
    group, wide_declaration = declared()
    _, narrow_declaration = declared(scope="disjunction_of_norms")
    wide = bridge.compile_coordination_group(group, wide_declaration)
    narrow = bridge.compile_coordination_group(group, narrow_declaration)
    assert wide["mapping"]["actor_symbols"] == narrow["mapping"]["actor_symbols"]
    assert wide["mapping"]["action_symbols"] == narrow["mapping"]["action_symbols"]
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
    return source, (wide, narrow)


def run_lake(directory, source, *, executable=None):
    executable = executable or os.environ.get("IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE")
    if not executable:
        pytest.skip("set explicit installed Lake executable")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "lakefile.toml").write_text(
        'name = "coordination_witness"\nversion = "0.1.0"\n'
        '[[lean_lib]]\nname = "legal"\nroots = ["CoordinationWitness"]\n')
    (directory / "CoordinationWitness.lean").write_text(source)
    return subprocess.run([str(Path(executable).resolve()), "build", "legal"],
                          cwd=directory, text=True, capture_output=True, timeout=60)


def test_real_lake_distinguishes_declared_modal_scopes(tmp_path):
    source, _ = native_scope_countermodel_source()
    result = run_lake(tmp_path, source)
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_lake_rejects_false_distribution_claim(tmp_path):
    source, _ = native_scope_countermodel_source()
    source += '''
example : Narrow.formula_0 twoWorlds 0 := by
  simp [Narrow.formula_0, twoWorlds]
'''
    result = run_lake(tmp_path, source)
    assert result.returncode != 0
    assert "error:" in result.stdout + result.stderr
