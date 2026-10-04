"""Actual native parser roundtrips and deliberately narrow legal routing."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.autoformal import legal_family_routes as routes
from ipfs_datasets_py.logic.autoformal import family_qualification as qualification
from ipfs_datasets_py.logic.CEC.native.dcec_integration import parse_dcec_string, DCECParsingError
from ipfs_datasets_py.logic.intent_ir.formalize.modal_projections import _ast
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as emitter


FIXTURES = [
    ("fol", "forall x. (Person(x) -> Eligible(x))"),
    ("deontic_fol", "O(retain(entity:agency, entity:record))"),
    ("deontic_fol", "P(retain(entity:agency, entity:record))"),
    ("deontic_fol", "F(retain(entity:agency, entity:record))"),
    ("temporal_fol", "G(retain(entity:agency, entity:record))"),
    ("temporal_fol", "(retain(entity:agency) U released(entity:record))"),
    ("tdfol", "G(O(retain(entity:agency, entity:record)))"),
    ("dcec", "O(retain(Agency, Record))"),
    ("dcec", "P(retain(Agency, Record))"),
    ("dcec", "F(retain(Agency, Record))"),
]


def expected_ast(family, text):
    return _ast(parse_dcec_string(text) if family == "dcec" else qualification._strict_tdfol(text)[0])


@pytest.mark.parametrize("family,formula", FIXTURES)
def test_native_structure_roundtrips_and_emits_real_lean(family, formula):
    ast = expected_ast(family, formula)
    result = routes.prepare_native_fragment(family=family, formula=formula, expected_ast=ast)
    assert result["native_ast"] == ast
    assert result["exact_native_ast_roundtrip"]
    assert result["parse_receipt"]["passed"] and result["printed_parse_receipt"]["passed"]
    assert "def formula_0" in result["lean_body"]
    assert result["source_bound"] is result["cross_family_equivalence_verified"] is False
    assert result["source_semantics_verified"] is result["all_logic_families_supported"] is False


@pytest.mark.parametrize("family,formula", [
    ("fol", "O(retain(entity:record))"), ("fol", "G(retain(entity:record))"),
    ("deontic_fol", "G(O(retain(entity:record)))"),
    ("temporal_fol", "O(retain(entity:record))"),
    ("tdfol", "O(retain(x))"),
    ("tdfol", "forall x:Agent. O(retain(x))"),
    ("tdfol", "O(retain(entity:record)) @ junk"),
    ("dcec", "forall x. O(retain(x))"),
    ("dcec", "I(Agent, retain(Record))"),
    ("frame_logic", "agency[record->retained]"),
    ("transition_system", "O(retain(Record))"),
])
def test_unsupported_families_scopes_sorts_or_input_never_get_a_fallback(family, formula):
    try:
        ast = expected_ast(family, formula)
    except Exception:
        ast = {}
    with pytest.raises(ValueError):
        routes.prepare_native_fragment(family=family, formula=formula, expected_ast=ast)


def test_native_ast_identity_is_not_replaced_by_syntax_acceptance():
    family, formula = FIXTURES[1]
    ast = expected_ast(family, formula)
    ast["operator"]["value"] = "P"
    with pytest.raises(ValueError, match="AST differs"):
        routes.prepare_native_fragment(family=family, formula=formula, expected_ast=ast)


def test_supplied_native_ast_is_bounded_inert_json():
    family, formula = FIXTURES[1]
    for ast in ({"oversized": "x" * 524289}, {"non_json": object()}, {"non_finite": float("inf")}):
        with pytest.raises(ValueError):
            routes.prepare_native_fragment(family=family, formula=formula, expected_ast=ast)
    cyclic = {}
    cyclic["cycle"] = cyclic
    with pytest.raises(ValueError):
        routes.prepare_native_fragment(family=family, formula=formula, expected_ast=cyclic)


def test_dcec_legacy_printing_bug_and_ground_printer_replay_are_distinguished():
    formula = "O(retain(Agency, Record))"
    native = parse_dcec_string(formula)
    assert "Agency()" in native.to_string()
    with pytest.raises(DCECParsingError):
        parse_dcec_string(native.to_string())
    result = routes.prepare_native_fragment(family="dcec", formula=formula, expected_ast=_ast(native))
    assert result["printed"] == formula
    assert _ast(parse_dcec_string(result["printed"])) == result["native_ast"]


def test_quantified_dcec_syntax_floor_does_not_authorize_legacy_native_lowering():
    formula = "forall x. O(retain(x))"
    assert qualification.validate_family_artifact("dcec", formula)["passed"]
    bad_native = parse_dcec_string(formula)
    assert type(bad_native).__name__ == "ConnectiveFormula"
    with pytest.raises(ValueError, match="ground"):
        routes.prepare_native_fragment(family="dcec", formula=formula, expected_ast=_ast(bad_native))


@pytest.mark.parametrize("family", ["fol", "temporal_fol", "tdfol", "dcec", "frame_logic", "higher_order"])
def test_canonical_deontic_calendar_rules_cannot_be_relabeled_other_families(family):
    with pytest.raises(ValueError, match="require the deontic route"):
        routes.route_canonical({}, {}, family=family)


def test_capability_matrix_keeps_legal_translation_and_native_fragments_separate():
    matrix = routes.capability_matrix()
    assert matrix["canonical_legal"]["supported_routes"] == ["deontic"]
    assert set(matrix["independent_native_fragments"]) == {"fol", "deontic_fol", "temporal_fol", "tdfol", "dcec"}
    assert matrix["all_logic_families_supported"] is False


def test_real_lake_build_legal_covers_all_supported_native_fixtures(tmp_path):
    executable = os.environ.get("IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE")
    if not executable: pytest.skip("set explicit installed Lake executable")
    lines = [emitter.PRELUDE]
    for index, (family, formula) in enumerate(FIXTURES):
        result = routes.prepare_native_fragment(family=family, formula=formula, expected_ast=expected_ast(family, formula))
        lines.append(f"namespace Case{index}\n" + result["lean_body"] + f"\nend Case{index}")
    # This model interprets permission and obligation differently. Compilation
    # must not silently identify modalities or assert their usual duality axioms.
    lines.append('''
def permitOnly : Interpretation Unit Unit where
  agent := fun _ => ()
  cognitive := fun _ _ body => body
  constant := fun _ => ()
  function := fun _ _ => ()
  atom := fun _ _ _ => True
  modal := fun label _ _ body t => label = "deontic:P" ∧ body t
  frame := fun _ _ _ => False
  frameScalar := fun _ _ => ()
  member := fun _ _ => False
  subclass := fun _ _ => False
example : Case2.formula_0 permitOnly 0 := by exact ⟨rfl, trivial⟩
example : ¬ Case1.formula_0 permitOnly 0 := by
  intro h
  exact (by decide : ¬ (("deontic:O" : String) = "deontic:P")) h.1
''')
    (tmp_path / "NativeFamilies.lean").write_text("\n".join(lines))
    (tmp_path / "lakefile.toml").write_text('name = "native_family_witness"\nversion = "0.1.0"\n[[lean_lib]]\nname = "legal"\nroots = ["NativeFamilies"]\n')
    result = subprocess.run([str(Path(executable).resolve()), "build", "legal"], cwd=tmp_path,
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
