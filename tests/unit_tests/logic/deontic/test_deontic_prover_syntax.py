"""Tests for Phase 8 local prover syntax validation."""

from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.prover_syntax import (
    _syntax_diagnostics,
    validate_ir_with_provers,
)
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_prover_syntax_renders_target_specific_ascii_dialects():
    examples = [
        (
            "The tenant must pay rent monthly.",
            {
                "fol": "forall x. (Tenant(x) and PeriodMonthly(x) -> PayRentMonthly(x))",
                "deontic_fol": "O(forall x. (Tenant(x) and PeriodMonthly(x) -> PayRentMonthly(x)))",
                "deontic_temporal_fol": "always(O(forall x. (Tenant(x) and PeriodMonthly(x) -> PayRentMonthly(x))))",
            },
        ),
        (
            "No person may discharge pollutants into the sewer.",
            {
                "fol": "forall x. (Person(x) -> DischargePollutantsIntoSewer(x))",
                "deontic_fol": "F(forall x. (Person(x) -> DischargePollutantsIntoSewer(x)))",
                "deontic_temporal_fol": "always(F(forall x. (Person(x) -> DischargePollutantsIntoSewer(x))))",
            },
        ),
        (
            "This section applies to food carts.",
            {
                "fol": "AppliesTo(ThisSection, FoodCarts)",
                "deontic_fol": "AppliesTo(ThisSection, FoodCarts)",
                "deontic_temporal_fol": "always(AppliesTo(ThisSection, FoodCarts))",
            },
        ),
    ]

    for text, expected_by_target in examples:
        norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])
        report = validate_ir_with_provers(norm)
        records = {target.target: target.to_dict() for target in report.targets}

        assert report.syntax_valid is True
        assert set(records) == {
            "frame_logic",
            "deontic_cec",
            "fol",
            "deontic_fol",
            "deontic_temporal_fol",
        }
        assert records["deontic_cec"]["exported_formula"].startswith("Happens(")
        assert "HoldsAt(" in records["deontic_cec"]["exported_formula"]
        assert records["frame_logic"]["exported_formula"].startswith("legal_norm(")
        for target, expected_formula in expected_by_target.items():
            assert records[target]["exported_formula"] == expected_formula
            assert not any(
                connective in expected_formula for connective in ("∀", "∧", "→", "¬")
            )
            assert records[target]["diagnostics"] == []


def test_prover_syntax_records_carry_decoder_context_for_local_targets():
    examples = [
        (
            "The tenant must pay rent monthly.",
            "Tenant shall pay rent monthly.",
            ["actor", "modality", "action"],
            [],
        ),
        (
            "This section applies to food carts.",
            "This section applies to food carts.",
            ["actor", "action"],
            [],
        ),
        (
            "The Secretary shall publish the notice except as provided in section 552.",
            "Secretary shall publish the notice except as provided in section 552.",
            ["actor", "modality", "action", "exceptions"],
            [],
        ),
    ]

    for text, decoded_text, decoded_slots, missing_slots in examples:
        norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])
        report = validate_ir_with_provers(norm)
        records = [target.to_dict() for target in report.targets]

        assert len(records) == 5
        assert all(record["decoded_text"] == decoded_text for record in records)
        assert all(record["decoded_slots"] == decoded_slots for record in records)
        assert all(record["missing_decoded_slots"] == missing_slots for record in records)
        assert all(record["ungrounded_decoded_slots"] == [] for record in records)
        assert all(record["grounded_decoded_slots"] == decoded_slots for record in records)


def test_prover_syntax_reports_target_shape_diagnostics():
    cases = [
        (
            "frame_logic",
            "legal_norm(source)[actor->Tenant; formula->PayRent]",
            "frame_logic_shape",
        ),
        (
            "deontic_cec",
            "HoldsAt(O(forall x. Tenant(x)), t)",
            "deontic_cec_shape",
        ),
        (
            "fol",
            "O(forall x. Tenant(x))",
            "fol_shape",
        ),
        (
            "deontic_fol",
            "always(O(forall x. Tenant(x)))",
            "deontic_fol_shape",
        ),
        (
            "deontic_temporal_fol",
            "O(forall x. Tenant(x))",
            "temporal_wrapper",
        ),
    ]

    for target, exported_formula, expected_code in cases:
        diagnostics = _syntax_diagnostics(target, exported_formula)

        assert expected_code in [diagnostic["code"] for diagnostic in diagnostics]


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
    assert records[4]["exported_formula"] == "always(AppliesTo(ThisSection, FoodCarts))"


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
    assert records[2]["exported_formula"] == "forall x. (Secretary(x) -> PublishNotice(x))"
    assert "Section552" not in records[2]["exported_formula"]
    assert "∀" not in records[2]["exported_formula"]
    assert "→" not in records[2]["exported_formula"]


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
