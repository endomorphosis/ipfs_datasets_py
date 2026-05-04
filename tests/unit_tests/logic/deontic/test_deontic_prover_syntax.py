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
            ["actor", "action", "cross_references"],
            [],
        ),
        (
            "The Secretary shall publish the notice except as provided in section 552.",
            "Secretary shall publish the notice except as provided in section 552.",
            ["actor", "modality", "action", "exceptions", "cross_references"],
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


def test_prover_syntax_records_share_ir_semantics_across_target_dialects():
    norm = LegalNormIR.from_parser_element(
        extract_normative_elements("The tenant must pay rent monthly.")[0]
    )

    report = validate_ir_with_provers(norm)
    records = {target.target: target.to_dict() for target in report.targets}

    assert len({record["ir_semantic_fingerprint"] for record in records.values()}) == 1
    assert len({record["target_formula_fingerprint"] for record in records.values()}) == 5
    assert len({record["decoded_slot_fingerprint"] for record in records.values()}) == 1
    assert records["frame_logic"]["target_formula_role"] == "frame_record"
    assert records["deontic_cec"]["target_formula_role"] == "event_calculus_state"
    assert records["fol"]["target_formula_role"] == "first_order_formula"
    assert records["deontic_fol"]["target_formula_role"] == "deontic_first_order_formula"
    assert records["deontic_temporal_fol"]["target_formula_role"] == (
        "temporal_deontic_first_order_formula"
    )
    assert records["frame_logic"]["target_components"]["uses_frame_record"] is True
    assert records["deontic_cec"]["target_components"]["uses_event_calculus_wrapper"] is True
    assert records["fol"]["target_components"]["uses_deontic_wrapper"] is False
    assert records["deontic_fol"]["target_components"]["uses_deontic_wrapper"] is True
    assert records["deontic_temporal_fol"]["target_components"]["uses_temporal_wrapper"] is True
    assert all(
        record["target_components"]["contains_display_connectives"] is False
        for record in records.values()
    )


def test_prover_syntax_records_carry_target_dialect_profiles():
    norm = LegalNormIR.from_parser_element(
        extract_normative_elements("The tenant must pay rent monthly.")[0]
    )

    records = {target.target: target.to_dict() for target in validate_ir_with_provers(norm).targets}

    assert [records[target]["target_dialect_profile"]["dialect_family"] for target in records] == [
        "frame_logic",
        "event_calculus",
        "first_order",
        "deontic_first_order",
        "deontic_temporal_first_order",
    ]
    assert records["frame_logic"]["target_dialect_profile"]["required_wrappers"] == [
        "legal_norm"
    ]
    assert records["deontic_cec"]["target_dialect_profile"]["required_wrappers"] == [
        "Happens",
        "HoldsAt",
    ]
    assert records["fol"]["target_dialect_profile"]["forbidden_wrappers_absent"] is True
    assert records["deontic_fol"]["target_dialect_profile"]["present_wrappers"] == ["O"]
    assert records["deontic_temporal_fol"]["target_dialect_profile"]["present_wrappers"] == [
        "always",
        "O",
    ]
    assert all(
        record["target_dialect_profile"]["connective_style"] == "ascii"
        for record in records.values()
    )
    assert all(
        record["target_dialect_profile"]["target_dialect_profile_complete"] is True
        for record in records.values()
    )
    assert all(
        record["target_components"]["target_dialect_profile_complete"] is True
        for record in records.values()
    )
    assert len({record["target_dialect_profile_fingerprint"] for record in records.values()}) == 5


def test_prover_syntax_records_audit_grounded_ir_slots_across_targets():
    examples = [
        (
            "The Director shall issue a permit within 10 days after application unless approval is denied.",
            ["actor", "modality", "action", "exceptions", "temporal_constraints"],
            ["mental_state", "recipient", "conditions", "cross_references"],
        ),
        (
            "The Secretary shall publish the notice except as provided in section 552.",
            ["actor", "modality", "action", "exceptions", "cross_references"],
            ["mental_state", "recipient", "conditions", "temporal_constraints"],
        ),
    ]

    for text, grounded_slots, missing_slots in examples:
        norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])
        records = [target.to_dict() for target in validate_ir_with_provers(norm).targets]

        assert len(records) == 5
        assert len({record["ir_slot_grounding_fingerprint"] for record in records}) == 1
        assert all(record["grounded_ir_slots"] == grounded_slots for record in records)
        assert all(record["ungrounded_ir_slots"] == [] for record in records)
        assert all(record["missing_ir_slots"] == missing_slots for record in records)
        assert all(
            record["target_components"]["grounded_ir_slots"] == grounded_slots
            for record in records
        )
        assert all(
            record["target_components"]["grounded_ir_slot_count"] == len(grounded_slots)
            for record in records
        )
        assert all(
            record["target_components"]["missing_ir_slot_count"] == len(missing_slots)
            for record in records
        )
        assert records[0]["ir_slot_grounding"][0]["slot"] == "actor"
        assert records[0]["ir_slot_grounding"][0]["status"] == "grounded"


def test_prover_syntax_records_align_decoder_ir_and_formula_slots():
    examples = [
        (
            "The Director shall issue a permit within 10 days after application unless approval is denied.",
            True,
            [],
            [],
            [],
            [],
        ),
        (
            "The tenant must pay rent monthly.",
            False,
            ["temporal_constraints"],
            ["temporal_constraints"],
            [],
            [],
        ),
        (
            "The Secretary shall publish the notice except as provided in section 552.",
            True,
            [],
            [],
            [],
            ["exceptions"],
        ),
    ]

    for (
        text,
        alignment_complete,
        missing_decoded,
        formula_missing_decoded,
        formula_ungrounded,
        omitted_formula_slots,
    ) in examples:
        norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])
        records = [target.to_dict() for target in validate_ir_with_provers(norm).targets]
        fingerprints = {record["slot_alignment_fingerprint"] for record in records}

        assert len(records) == 5
        assert len(fingerprints) == 1
        assert all(
            record["decoded_ir_slot_alignment"]["alignment_complete"] is alignment_complete
            for record in records
        )
        assert all(
            record["decoded_ir_slot_alignment"]["decoded_missing_grounded_ir_slots"]
            == missing_decoded
            for record in records
        )
        assert all(
            record["decoded_ir_slot_alignment"]["formula_missing_decoded_slots"]
            == formula_missing_decoded
            for record in records
        )
        assert all(
            record["decoded_ir_slot_alignment"]["formula_ungrounded_slots"]
            == formula_ungrounded
            for record in records
        )
        assert all(
            record["decoded_ir_slot_alignment"]["omitted_formula_slot_names"]
            == omitted_formula_slots
            for record in records
        )
        assert all(
            record["target_components"]["slot_alignment_complete"] is alignment_complete
            for record in records
        )
        assert all(record["formula_slots"] for record in records)

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_prover_syntax_records_audit_target_formula_symbols():
    examples = [
        (
            "The tenant must pay rent monthly.",
            ["Tenant", "PeriodMonthly", "PayRentMonthly"],
        ),
        (
            "No person may discharge pollutants into the sewer.",
            ["Person", "DischargePollutantsIntoSewer"],
        ),
        (
            "This section applies to food carts.",
            ["AppliesTo", "ThisSection", "FoodCarts"],
        ),
        (
            "The Director shall issue a permit within 10 days after application.",
            ["Director", "Deadline10DaysAfterApplication", "IssuePermit"],
        ),
    ]

    for text, expected_symbols in examples:
        norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])
        records = [target.to_dict() for target in validate_ir_with_provers(norm).targets]

        assert len(records) == 5
        assert all(record["source_formula_symbols"] == expected_symbols for record in records)
        assert all(
            record["target_symbol_alignment"]["source_formula_symbols"]
            == expected_symbols
            for record in records
        )
        assert all(
            record["target_symbol_alignment"]["target_symbol_alignment_complete"] is True
            for record in records
        )
        assert all(
            record["target_symbol_alignment"]["missing_exported_formula_symbols"] == []
            for record in records
        )
        assert all(
            record["target_components"]["target_symbol_alignment_complete"] is True
            for record in records
        )
        assert all(
            record["target_components"]["missing_exported_formula_symbols"] == []
            for record in records
        )
        assert len({record["target_symbol_alignment_fingerprint"] for record in records}) == 5


def test_prover_syntax_symbol_audit_keeps_blocked_reference_formula_grounded():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    records = [target.to_dict() for target in validate_ir_with_provers(norm).targets]

    assert element["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in element["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in element["llm_repair"]["reasons"]
    assert norm.proof_ready is False
    assert all(
        record["source_formula_symbols"] == ["Secretary", "PublishNotice"]
        for record in records
    )
    assert all(
        record["target_symbol_alignment"]["missing_exported_formula_symbols"] == []
        for record in records
    )
    assert all(
        "Section552" not in record["exported_formula_symbols"]
        for record in records
    )
    assert all(record["proof_ready"] is False for record in records)
    assert all(record["requires_validation"] is True for record in records)


def test_prover_syntax_records_expose_mental_state_components():
    norm = LegalNormIR.from_parser_element(
        extract_normative_elements(
            "The inspector shall knowingly approve the discharge."
        )[0]
    )

    records = [target.to_dict() for target in validate_ir_with_provers(norm).targets]

    assert len(records) == 5
    assert all(
        record["decoded_slots"] == ["actor", "modality", "mental_state", "action"]
        for record in records
    )
    assert all(
        record["grounded_decoded_slots"]
        == ["actor", "modality", "mental_state", "action"]
        for record in records
    )
    assert all("mental_state" in record["grounded_ir_slots"] for record in records)
    assert all(record["target_components"]["grounded_ir_slot_count"] >= 4 for record in records)
    assert all(
        record["exported_formula"].find("Knowingly") >= 0
        for record in records
        if record["target"] != "frame_logic"
    )


def test_prover_syntax_semantic_fingerprints_change_when_ir_slots_change():
    tenant = LegalNormIR.from_parser_element(
        extract_normative_elements("The tenant must pay rent monthly.")[0]
    )
    permittee = LegalNormIR.from_parser_element(
        extract_normative_elements("The permittee may appeal the decision.")[0]
    )

    tenant_records = [target.to_dict() for target in validate_ir_with_provers(tenant).targets]
    permittee_records = [
        target.to_dict() for target in validate_ir_with_provers(permittee).targets
    ]

    assert len({record["ir_semantic_fingerprint"] for record in tenant_records}) == 1
    assert len({record["ir_semantic_fingerprint"] for record in permittee_records}) == 1
    assert tenant_records[0]["ir_semantic_fingerprint"] != permittee_records[0][
        "ir_semantic_fingerprint"
    ]
    assert tenant_records[0]["decoded_slot_fingerprint"] != permittee_records[0][
        "decoded_slot_fingerprint"
    ]
    assert tenant_records[0]["decoded_slots"] == ["actor", "modality", "action"]
    assert permittee_records[0]["decoded_slots"] == ["actor", "modality", "action"]


def test_prover_syntax_target_components_cover_frame_applicability_and_blocked_reference():
    applicability = LegalNormIR.from_parser_element(
        extract_normative_elements("This section applies to food carts.")[0]
    )
    blocked = LegalNormIR.from_parser_element(
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0]
    )

    applicability_records = {
        target.target: target.to_dict()
        for target in validate_ir_with_provers(applicability).targets
    }
    blocked_records = {
        target.target: target.to_dict()
        for target in validate_ir_with_provers(blocked).targets
    }

    assert applicability_records["fol"]["target_components"]["uses_first_order_quantifier"] is False
    assert applicability_records["fol"]["target_components"]["uses_deontic_wrapper"] is False
    assert applicability_records["deontic_temporal_fol"]["target_components"][
        "uses_temporal_wrapper"
    ] is True
    assert blocked_records["fol"]["target_components"]["uses_first_order_quantifier"] is True
    assert blocked_records["deontic_fol"]["target_components"]["uses_deontic_wrapper"] is True
    assert blocked_records["deontic_temporal_fol"]["target_components"][
        "uses_temporal_wrapper"
    ] is True
    assert blocked_records["fol"]["proof_ready"] is False
    assert blocked_records["fol"]["requires_validation"] is True
    assert "cross_reference_requires_resolution" in blocked.blockers
    assert "exception_requires_scope_review" in blocked.blockers


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
