"""No family coverage from a mere grammar label or reinterpreted operator."""
from dataclasses import replace
import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_formula_evidence as api
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef

FORMULAS = {
    "FOL": "forall x. Person(x) -> Reports(x)",
    "DFOL": "forall x. O(Reports(x))",
    "TFOL": "forall x. □(Reports(x))",
    "TDFOL": "forall x. O(□(Reports(x)))",
    "CEC": "K(Officer,Happens(Submit,Time))",
    "DCEC": "O(K(Officer,Happens(Submit,Time)))",
    "frame_logic": "alice[role -> officer].",
    "propositional": "p and q",
}


def source():
    return SourceRef(ref_id="source:test", source_uri="urn:test", source_id="test",
                     source_revision="v1", content_sha256="a" * 64)


def prepare(requirement, formula):
    return api.prepare_native_formula_evidence(api.NativeFormulaEvidence(requirement, formula, source()), source())


@pytest.mark.parametrize("requirement,formula", FORMULAS.items())
def test_all_eight_routes_are_native_structures_with_source_join(requirement, formula):
    result = prepare(requirement, formula)
    assert result["payload"]["native_ast"]
    assert result["payload"]["source_ref"] == source().to_dict()
    assert result["payload"]["requirement_id"] == requirement
    assert all(result["validation"].values())
    assert not result["payload"]["source_meaning_verified"]
    assert result["qualification_gaps"]
    assert result["producer_pins"]
    assert "lake" not in result["validation"]
    again = prepare(requirement, result["payload"]["printed"])
    assert result["payload"]["native_ast"] == again["payload"]["native_ast"]


@pytest.mark.parametrize("requirement,formula", [
    ("FOL", "G(Reports(x))"), ("DFOL", "O(G(Reports(x)))"),
    ("FOL", "K(agent,Reports(x))"), ("FOL", "Happens(Event,Time)"),
    ("DFOL", "Reports(x)"), ("TFOL", "Reports(x)"),
    ("TDFOL", "O(Reports(x))"), ("FOL", "O(Reports(x))"),
    ("CEC", "Reports(Record)"), ("CEC", "Happens(Submit,Time)"),
    ("CEC", "K(Officer,Reports(Record))"),
    ("CEC", "O(K(Officer,Happens(Submit,Time)))"),
    ("DCEC", "O(Happens(Submit,Time))"),
    ("DCEC", "K(Officer,Happens(Submit,Time))"),
    ("DCEC", "O(K(Officer,Happens(Submit)))"),
    ("DCEC", "O(K(Officer,happens(Submit,Time)))"),
    ("DCEC", "O(K(officer,Happens(Submit,Time)))"),
    ("CEC", "K(Officer,Happens(Submit,Time)) garbage"),
    ("FOL", "Reports(x) $"), ("propositional", "O(p)"),
])
def test_weaker_fragments_recovery_and_operator_reinterpretation_fail(requirement, formula):
    with pytest.raises(ValueError):
        prepare(requirement, formula)


def test_changed_source_cannot_reuse_declaration():
    item = api.NativeFormulaEvidence("FOL", FORMULAS["FOL"], source())
    with pytest.raises(ValueError, match="SourceRef"):
        api.prepare_native_formula_evidence(item, replace(source(), content_sha256="b" * 64))


def test_native_temporal_alias_is_an_operator_not_an_ordinary_predicate():
    result = prepare("TDFOL", "O(G(Reports(x)))")
    assert result["payload"]["operator_counts"]["temporal"] == 1
    assert "TemporalFormula" in repr(result["payload"]["native_ast"])


@pytest.mark.parametrize("connective", ["and", "or", "implies", "iff"])
def test_cognitive_composition_preserves_boolean_structure(connective):
    report = prepare("DCEC", f"O({connective}(K(Officer,Happens(Submit,Time)),B(Officer,HoldsAt(Filed,Time))))")
    assert report["payload"]["operator_counts"] == {"cognitive": 2, "event": 2, "deontic": 1}
