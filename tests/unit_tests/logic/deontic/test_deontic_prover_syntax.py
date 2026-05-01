"""Tests for Phase 8 local prover syntax validation."""

from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.prover_syntax import validate_ir_with_provers
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_prover_syntax_uses_formula_level_resolution_for_local_applicability():
    element = extract_normative_elements("This section applies to food carts.")[0]
    norm = LegalNormIR.from_parser_element(element)

    report = validate_ir_with_provers(norm)
    records = [target.to_dict() for target in report.targets]

    assert norm.proof_ready is False
    assert "cross_reference_requires_resolution" in norm.blockers
    assert report.syntax_valid is True
    assert report.proof_ready is True
    assert report.requires_validation is False
    assert report.valid_target_count == 5
    assert [record["target"] for record in records] == [
        "frame_logic",
        "deontic_cec",
        "fol",
        "deontic_fol",
        "deontic_temporal_fol",
    ]
    assert all(record["proof_ready"] is True for record in records)
    assert all(record["requires_validation"] is False for record in records)
    assert records[0]["exported_formula"].startswith("legal_norm(")
    assert records[2]["exported_formula"] == "AppliesTo(ThisSection, FoodCarts)"
    assert records[4]["exported_formula"] == "Always(AppliesTo(ThisSection, FoodCarts))"


def test_prover_syntax_keeps_protected_numbered_reference_exception_blocked():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    report = validate_ir_with_provers(norm)
    records = [target.to_dict() for target in report.targets]

    assert report.syntax_valid is True
    assert report.proof_ready is False
    assert report.requires_validation is True
    assert all(record["syntax_valid"] is True for record in records)
    assert all(record["proof_ready"] is False for record in records)
    assert all(record["requires_validation"] is True for record in records)
    assert all(record["diagnostics"] == [] for record in records)
    assert "cross_reference_requires_resolution" in norm.blockers
    assert "exception_requires_scope_review" in norm.blockers
    assert records[2]["exported_formula"] == "∀x (Secretary(x) → PublishNotice(x))"
    assert "Section552" not in records[2]["exported_formula"]


def test_prover_syntax_unknown_target_still_requires_validation():
    element = extract_normative_elements("The tenant must pay rent monthly.")[0]
    norm = LegalNormIR.from_parser_element(element)

    report = validate_ir_with_provers(norm, targets=["fol", "unknown-target"])
    records = [target.to_dict() for target in report.targets]

    assert report.syntax_valid is False
    assert report.proof_ready is False
    assert report.requires_validation is True
    assert records[0]["target"] == "fol"
    assert records[0]["proof_ready"] is True
    assert records[1]["target"] == "unknown_target"
    assert records[1]["syntax_valid"] is False
    assert records[1]["requires_validation"] is True
    assert records[1]["diagnostics"][0]["code"] == "unknown_target"
