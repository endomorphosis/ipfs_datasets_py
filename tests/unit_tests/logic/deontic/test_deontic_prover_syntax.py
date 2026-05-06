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


def test_prover_syntax_records_carry_target_parse_profiles():
    norm = LegalNormIR.from_parser_element(
        extract_normative_elements("The tenant must pay rent monthly.")[0]
    )

    records = {
        target.target: target.to_dict()
        for target in validate_ir_with_provers(norm).targets
    }

    assert records["frame_logic"]["target_parse_profile"]["top_level_symbol"] == (
        "legal_norm"
    )
    assert records["frame_logic"]["target_parse_profile"]["frame_slots"] == [
        "actor",
        "action",
        "formula",
    ]
    assert records["deontic_cec"]["target_parse_profile"]["event_predicates"] == [
        "Happens",
        "HoldsAt",
    ]
    assert records["fol"]["target_parse_profile"]["top_level_symbol"] == "forall"
    assert records["fol"]["target_parse_profile"]["quantifier_variables"] == ["x"]
    assert records["deontic_fol"]["target_parse_profile"]["wrapper_sequence"] == ["O"]
    assert records["deontic_temporal_fol"]["target_parse_profile"][
        "wrapper_sequence"
    ] == ["always", "O"]
    assert all(
        record["target_parse_profile"]["target_parse_profile_complete"] is True
        for record in records.values()
    )
    assert all(
        record["target_components"]["target_parse_profile_complete"] is True
        for record in records.values()
    )
    assert records["frame_logic"]["target_components"]["parse_frame_slots"] == [
        "actor",
        "action",
        "formula",
    ]
    assert records["deontic_cec"]["target_components"]["parse_event_predicates"] == [
        "Happens",
        "HoldsAt",
    ]
    assert records["fol"]["target_components"]["parse_quantifier_variables"] == ["x"]
    assert len(
        {
            record["target_parse_profile_fingerprint"]
            for record in records.values()
        }
    ) == 5


def test_prover_syntax_records_carry_quantifier_and_deontic_scope_profiles():
    examples = [
        (
            "The tenant must pay rent monthly.",
            "O",
            ["Tenant", "PeriodMonthly"],
            ["PayRentMonthly"],
        ),
        (
            "No person may discharge pollutants into the sewer.",
            "F",
            ["Person"],
            ["DischargePollutantsIntoSewer"],
        ),
        (
            "The permittee may appeal the decision.",
            "P",
            ["Permittee"],
            ["AppealDecision"],
        ),
    ]

    for text, operator, antecedent_symbols, consequent_symbols in examples:
        norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])
        records = {
            target.target: target.to_dict()
            for target in validate_ir_with_provers(norm).targets
        }
        matrix_symbols = antecedent_symbols + consequent_symbols

        fol_scope = records["fol"]["target_parse_profile"]["quantifier_scopes"][0]
        assert fol_scope["variable"] == "x"
        assert fol_scope["antecedent_symbols"] == antecedent_symbols
        assert fol_scope["consequent_symbols"] == consequent_symbols
        assert fol_scope["matrix_symbols"] == matrix_symbols
        assert fol_scope["has_implication"] is True

        deontic_profile = records["deontic_fol"]["target_parse_profile"]
        temporal_profile = records["deontic_temporal_fol"]["target_parse_profile"]
        assert deontic_profile["deontic_operator_sequence"] == [operator]
        assert temporal_profile["deontic_operator_sequence"] == [operator]
        assert deontic_profile["deontic_scopes"][0]["formula_symbols"] == matrix_symbols
        assert temporal_profile["deontic_scopes"][0]["formula_symbols"] == matrix_symbols
        assert deontic_profile["deontic_scopes"][0]["contains_quantifier"] is True
        assert temporal_profile["deontic_scopes"][0]["quantifier_variables"] == ["x"]

        assert records["fol"]["target_components"]["parse_quantifier_scope_count"] == 1
        assert records["fol"]["target_components"]["parse_deontic_scope_count"] == 0
        assert records["deontic_fol"]["target_components"]["parse_deontic_scope_count"] == 1
        assert records["deontic_temporal_fol"]["target_components"][
            "parse_deontic_scope_symbols"
        ] == matrix_symbols
        assert records["frame_logic"]["target_components"]["parse_quantifier_scope_count"] == 0

    applicability = LegalNormIR.from_parser_element(
        extract_normative_elements("This section applies to food carts.")[0]
    )
    applicability_records = {
        target.target: target.to_dict()
        for target in validate_ir_with_provers(applicability).targets
    }

    assert applicability_records["fol"]["target_parse_profile"]["quantifier_scopes"] == []
    assert applicability_records["fol"]["target_parse_profile"]["deontic_scopes"] == []
    assert applicability_records["deontic_temporal_fol"]["target_parse_profile"][
        "wrapper_sequence"
    ] == ["always"]
    assert applicability_records["deontic_temporal_fol"]["target_components"][
        "parse_deontic_operator_sequence"
    ] == []


def test_prover_syntax_records_carry_reconstruction_token_profiles():
    examples = [
        (
            "The tenant must pay rent monthly.",
            ["tenant", "pay", "rent", "monthly"],
        ),
        (
            "The inspector shall knowingly approve the discharge.",
            ["inspector", "knowingly", "approve", "discharge"],
        ),
        (
            "The Director shall issue a permit within 10 days after application.",
            [
                "director",
                "issue",
                "permit",
                "within",
                "10",
                "days",
                "after",
                "application",
            ],
        ),
    ]

    for text, expected_tokens in examples:
        norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])
        records = {
            target.target: target.to_dict()
            for target in validate_ir_with_provers(norm).targets
        }

        assert len(records) == 5
        assert all(
            record["reconstruction_token_profile"]["source_salient_tokens"]
            == expected_tokens
            for record in records.values()
        )
        assert all(
            record["reconstruction_token_profile"]["decoded_salient_tokens"]
            == expected_tokens
            for record in records.values()
        )
        assert all(
            record["reconstruction_token_profile"][
                "reconstruction_token_profile_complete"
            ]
            is True
            for record in records.values()
        )
        assert all(
            record["target_components"]["reconstruction_token_profile_complete"]
            is True
            for record in records.values()
        )
        assert all(
            record["target_components"]["salient_token_coverage_rate"] == 1.0
            for record in records.values()
        )
        assert len(
            {
                record["reconstruction_token_profile_fingerprint"]
                for record in records.values()
            }
        ) == 5


def test_prover_reconstruction_profile_preserves_blocked_reference_tokens_without_repair_clearance():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    records = [target.to_dict() for target in validate_ir_with_provers(norm).targets]

    assert element["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in element["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in element["llm_repair"]["reasons"]
    assert norm.proof_ready is False
    assert all(record["proof_ready"] is False for record in records)
    assert all(record["requires_validation"] is True for record in records)
    assert all(
        record["reconstruction_token_profile"]["source_salient_tokens"]
        == ["secretary", "publish", "notice", "except", "section", "552"]
        for record in records
    )
    assert all(
        record["reconstruction_token_profile"]["unreconstructed_source_tokens"] == []
        for record in records
    )
    assert all(
        record["reconstruction_token_profile"]["added_decoded_tokens"] == []
        for record in records
    )
    assert all(
        record["target_components"]["reconstruction_token_profile_complete"] is True
        for record in records
    )


def test_prover_syntax_records_carry_decoded_phrase_profiles():
    examples = [
        (
            "The tenant must pay rent monthly.",
            ["actor", "modality", "action"],
            [],
            [],
            3,
            3,
        ),
        (
            "The inspector shall knowingly approve the discharge.",
            ["actor", "modality", "mental_state", "action"],
            [],
            [],
            4,
            4,
        ),
        (
            "The Secretary shall publish the notice except as provided in section 552.",
            ["actor", "modality", "action", "exceptions", "cross_references"],
            ["exception_connector"],
            ["cross_references"],
            6,
            4,
        ),
    ]

    for (
        text,
        phrase_slots,
        fixed_slots,
        provenance_only_slots,
        phrase_count,
        legal_count,
    ) in examples:
        norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])
        records = {
            target.target: target.to_dict()
            for target in validate_ir_with_provers(norm).targets
        }

        assert len(records) == 5
        assert all(
            record["decoded_phrase_profile"]["phrase_slots"] == phrase_slots
            for record in records.values()
        )
        assert all(
            record["decoded_phrase_profile"]["fixed_slots"] == fixed_slots
            for record in records.values()
        )
        assert all(
            record["decoded_phrase_profile"]["provenance_only_slots"]
            == provenance_only_slots
            for record in records.values()
        )
        assert all(
            record["decoded_phrase_profile"]["phrase_count"] == phrase_count
            for record in records.values()
        )
        assert all(
            record["decoded_phrase_profile"]["legal_phrase_count"] == legal_count
            for record in records.values()
        )
        assert all(
            record["decoded_phrase_profile"]["decoded_phrase_profile_complete"] is True
            for record in records.values()
        )
        assert all(
            record["target_components"]["decoded_phrase_profile_complete"] is True
            for record in records.values()
        )
        assert all(
            record["target_components"]["decoded_phrase_slots"] == phrase_slots
            for record in records.values()
        )
        assert len(
            {
                record["decoded_phrase_profile_fingerprint"]
                for record in records.values()
            }
        ) == 5


def test_prover_decoded_phrase_profile_preserves_protected_reference_blocker():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    records = [target.to_dict() for target in validate_ir_with_provers(norm).targets]

    assert element["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in element["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in element["llm_repair"]["reasons"]
    assert norm.proof_ready is False
    assert all(record["proof_ready"] is False for record in records)
    assert all(record["requires_validation"] is True for record in records)
    assert all(
        record["decoded_phrase_profile"]["provenance_only_slots"]
        == ["cross_references"]
        for record in records
    )
    assert all(
        record["decoded_phrase_profile"]["fixed_slots"] == ["exception_connector"]
        for record in records
    )
    assert all(
        record["target_components"]["decoded_provenance_only_phrase_count"] == 1
        for record in records
    )


def test_prover_syntax_records_carry_target_semantic_bridge_profiles():
    examples = [
        (
            "The tenant must pay rent.",
            "ordinary_duty",
            "PayRent",
            ["actor", "modality", "action"],
        ),
        (
            "The inspector shall knowingly approve the discharge.",
            "ordinary_duty",
            "ApproveDischarge",
            ["actor", "modality", "mental_state", "action"],
        ),
        (
            "The permittee may appeal the decision.",
            "ordinary_duty",
            "AppealDecision",
            ["actor", "modality", "action"],
        ),
    ]

    for text, family, predicate, formula_slots in examples:
        norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])
        records = {
            target.target: target.to_dict()
            for target in validate_ir_with_provers(norm).targets
        }

        assert len(records) == 5
        assert all(
            record["target_semantic_bridge_profile"]["semantic_formula_family"]
            == family
            for record in records.values()
        )
        assert all(
            record["target_semantic_bridge_profile"]["semantic_formula_predicate"]
            == predicate
            for record in records.values()
        )
        assert all(
            record["target_semantic_bridge_profile"]["formula_slots"] == formula_slots
            for record in records.values()
        )
        assert all(
            record["target_semantic_bridge_profile"]["decoded_formula_overlap"]
            == formula_slots
            for record in records.values()
        )
        assert all(
            record["target_semantic_bridge_profile"]["grounded_formula_overlap"]
            == formula_slots
            for record in records.values()
        )
        assert all(
            record["target_semantic_bridge_profile"]["semantic_bridge_complete"]
            is True
            for record in records.values()
        )
        assert all(
            record["target_semantic_bridge_profile"]["semantic_bridge_blockers"] == []
            for record in records.values()
        )
        assert len(
            {
                record["target_semantic_bridge_fingerprint"]
                for record in records.values()
            }
        ) == 5


def test_prover_semantic_bridge_profile_keeps_blocked_reference_visible():
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
        record["target_semantic_bridge_profile"]["semantic_formula_predicate"]
        == "PublishNotice"
        for record in records
    )
    assert all(
        record["target_semantic_bridge_profile"]["formula_slots"]
        == ["actor", "modality", "action", "exceptions"]
        for record in records
    )
    assert all(
        record["target_semantic_bridge_profile"]["semantic_bridge_complete"] is False
        for record in records
    )
    assert all(
        record["target_semantic_bridge_profile"]["semantic_bridge_blockers"]
        == ["formula_requires_validation"]
        for record in records
    )
    assert all(record["requires_validation"] is True for record in records)


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


def test_prover_target_components_classify_semantic_formula_families():
    examples = [
        (
            "The Coordinator shall conduct mediation of the dispute.",
            "MediateDispute",
            "dispute_resolution_duty",
        ),
        (
            "The Officer shall provide arbitration of the claim.",
            "ArbitrateClaim",
            "dispute_resolution_duty",
        ),
        (
            "The Board shall make a settlement of the appeal.",
            "SettleAppeal",
            "dispute_resolution_duty",
        ),
        (
            "The Permittee shall post a bond.",
            "PostBond",
            "financial_assurance_duty",
        ),
        (
            "This section applies to food carts.",
            "AppliesTo",
            "applicability_rule",
        ),
    ]

    for text, expected_predicate, expected_family in examples:
        norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])
        records = [target.to_dict() for target in validate_ir_with_provers(norm).targets]

        assert len(records) == 5
        assert all(
            record["target_components"]["semantic_formula_family"] == expected_family
            for record in records
        )
        assert all(
            record["target_components"]["semantic_formula_predicate"]
            == expected_predicate
            for record in records
        )
        assert all(
            expected_predicate
            in record["target_components"]["semantic_formula_symbols"]
            for record in records
        )
        assert all(
            record["target_components"]["semantic_formula_source"]
            == "source_formula_symbols"
            for record in records
        )

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


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


def test_prover_syntax_records_expose_compound_mental_state_components():
    examples = [
        (
            "The inspector shall knowingly and willfully approve the discharge.",
            "knowingly and willfully",
            "O(∀x (Inspector(x) ∧ KnowinglyAndWillfully(x) → ApproveDischarge(x)))",
            "KnowinglyAndWillfully",
        ),
        (
            "The applicant shall intentionally or recklessly file a false statement.",
            "intentionally or recklessly",
            "O(∀x (Applicant(x) ∧ IntentionallyOrRecklessly(x) → FileFalseStatement(x)))",
            "IntentionallyOrRecklessly",
        ),
        (
            "The officer shall deliberately and corruptly alter the record.",
            "deliberately and corruptly",
            "O(∀x (Officer(x) ∧ DeliberatelyAndCorruptly(x) → AlterRecord(x)))",
            "DeliberatelyAndCorruptly",
        ),
    ]

    for text, mental_state, expected_formula, expected_predicate in examples:
        norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])
        report = validate_ir_with_provers(norm)
        records = [target.to_dict() for target in report.targets]

        assert norm.mental_state == mental_state
        assert report.syntax_valid is True
        assert report.proof_ready is True
        assert report.valid_target_count == 5
        assert all(record["formula"] == expected_formula for record in records)
        assert all(
            record["decoded_slots"] == ["actor", "modality", "mental_state", "action"]
            for record in records
        )
        assert all(
            record["grounded_decoded_slots"]
            == ["actor", "modality", "mental_state", "action"]
            for record in records
        )
        assert all(record["ungrounded_decoded_slots"] == [] for record in records)
        assert all(record["missing_decoded_slots"] == [] for record in records)
        assert all("mental_state" in record["grounded_ir_slots"] for record in records)
        assert all(
            expected_predicate in record["exported_formula"]
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


def test_prover_syntax_records_expose_phase8_target_quality_gates():
    proof_ready = LegalNormIR.from_parser_element(
        extract_normative_elements("The tenant must pay rent monthly.")[0]
    )
    formula_resolved = LegalNormIR.from_parser_element(
        extract_normative_elements("This section applies to food carts.")[0]
    )
    blocked = LegalNormIR.from_parser_element(
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0]
    )

    proof_ready_records = [
        target.to_dict() for target in validate_ir_with_provers(proof_ready).targets
    ]
    resolved_records = [
        target.to_dict() for target in validate_ir_with_provers(formula_resolved).targets
    ]
    blocked_records = [
        target.to_dict() for target in validate_ir_with_provers(blocked).targets
    ]

    assert all(
        record["target_quality_gate"]["formal_validation_complete"] is True
        for record in proof_ready_records
    )
    assert all(
        record["target_quality_gate"]["parser_theorem_promotable"] is True
        for record in proof_ready_records
    )
    assert all(
        record["target_quality_gate"]["failed_quality_checks"] == []
        for record in proof_ready_records
    )
    assert all(
        [
            check["check"]
            for check in record["target_quality_gate"]["quality_gate_checks"]
            if check["passed"] is False
        ]
        == []
        for record in proof_ready_records
    )
    assert all(
        record["target_quality_gate"]["quality_gate_blockers"] == []
        for record in proof_ready_records
    )
    assert all(
        record["target_quality_gate"]["source_grounding_diagnostics"]["parser_warnings"]
        == []
        for record in proof_ready_records
    )
    assert len(
        {
            record["target_quality_gate_fingerprint"]
            for record in proof_ready_records
        }
    ) == 5

    assert all(
        record["target_quality_gate"]["formal_validation_complete"] is True
        for record in resolved_records
    )
    assert all(
        record["target_quality_gate"]["parser_theorem_promotable"] is False
        for record in resolved_records
    )
    assert all(
        record["target_quality_gate"]["parser_proof_ready"] is False
        for record in resolved_records
    )
    assert all(
        record["target_quality_gate"]["quality_gate_blockers"] == []
        for record in resolved_records
    )
    assert all(
        record["target_quality_gate"]["source_grounding_diagnostics"]["parser_warnings"]
        == ["cross_reference_requires_resolution"]
        for record in resolved_records
    )
    assert all(
        record["target_quality_gate"]["source_grounding_diagnostics"]["blockers"]
        == ["cross_reference_requires_resolution"]
        for record in resolved_records
    )

    assert all(
        record["target_quality_gate"]["formal_validation_complete"] is False
        for record in blocked_records
    )
    assert all(
        record["target_quality_gate"]["formula_proof_ready"] is False
        for record in blocked_records
    )
    assert all(
        record["target_quality_gate"]["failed_quality_checks"]
        == ["formula_proof_ready", "formula_requires_validation"]
        for record in blocked_records
    )
    assert all(
        record["target_quality_gate"]["quality_gate_blockers"]
        == [
            "failed_prover_quality_check:formula_proof_ready",
            "failed_prover_quality_check:formula_requires_validation",
        ]
        for record in blocked_records
    )
    assert all(
        [
            check["check"]
            for check in record["target_quality_gate"]["quality_gate_checks"]
            if check["passed"] is False
        ]
        == ["formula_proof_ready", "formula_requires_validation"]
        for record in blocked_records
    )
    assert all(
        record["target_quality_gate"]["source_grounding_diagnostics"]["parser_warnings"]
        == ["cross_reference_requires_resolution", "exception_requires_scope_review"]
        for record in blocked_records
    )
    assert all(
        record["target_quality_gate"]["source_grounding_diagnostics"][
            "omitted_formula_slot_names"
        ]
        == ["exceptions"]
        for record in blocked_records
    )
    assert all(
        record["target_quality_gate"]["source_grounding_diagnostics"]["blockers"]
        == [
            "cross_reference_requires_resolution",
            "exception_requires_scope_review",
            "llm_repair_required",
        ]
        for record in blocked_records
    )


def test_prover_quality_gate_exposes_formula_slot_coverage_profiles():
    examples = [
        (
            "The inspector shall knowingly approve the discharge.",
            True,
            ["actor", "modality", "mental_state", "action"],
            ["actor", "modality", "mental_state", "action"],
            ["actor", "modality", "mental_state", "action"],
            [],
            [],
            1.0,
            1.0,
        ),
        (
            "The tenant must pay rent monthly.",
            False,
            ["actor", "modality", "temporal_constraints", "action"],
            ["actor", "modality", "action"],
            ["actor", "modality", "temporal_constraints", "action"],
            ["temporal_constraints"],
            [],
            0.75,
            1.0,
        ),
        (
            "The Secretary shall publish the notice except as provided in section 552.",
            True,
            ["actor", "modality", "action", "exceptions"],
            ["actor", "modality", "action", "exceptions"],
            ["actor", "modality", "action", "exceptions"],
            [],
            ["exceptions"],
            1.0,
            1.0,
        ),
    ]

    for (
        text,
        complete,
        formula_slots,
        decoded_slots,
        grounded_slots,
        missing_decoded_slots,
        omitted_slots,
        decoder_rate,
        grounding_rate,
    ) in examples:
        norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])
        records = [target.to_dict() for target in validate_ir_with_provers(norm).targets]

        assert len(records) == 5
        assert all(
            record["target_quality_gate"]["formula_slot_coverage"][
                "formula_slot_coverage_complete"
            ]
            is complete
            for record in records
        )
        assert all(
            record["target_quality_gate"]["formula_slot_coverage"]["formula_slots"]
            == formula_slots
            for record in records
        )
        assert all(
            record["target_quality_gate"]["formula_slot_coverage"][
                "decoded_formula_slots"
            ]
            == decoded_slots
            for record in records
        )
        assert all(
            record["target_quality_gate"]["formula_slot_coverage"][
                "grounded_formula_slots"
            ]
            == grounded_slots
            for record in records
        )
        assert all(
            record["target_quality_gate"]["formula_slot_coverage"][
                "missing_decoded_formula_slots"
            ]
            == missing_decoded_slots
            for record in records
        )
        assert all(
            record["target_quality_gate"]["formula_slot_coverage"][
                "omitted_formula_slot_names"
            ]
            == omitted_slots
            for record in records
        )
        assert all(
            record["target_quality_gate"]["formula_slot_coverage"][
                "formula_slot_decoder_rate"
            ]
            == decoder_rate
            for record in records
        )
        assert all(
            record["target_quality_gate"]["formula_slot_coverage"][
                "formula_slot_grounding_rate"
            ]
            == grounding_rate
            for record in records
        )
        assert all(
            record["target_components"]["formula_slot_coverage_complete"] is complete
            for record in records
        )
        assert all(
            record["target_components"]["formula_slot_decoder_rate"] == decoder_rate
            for record in records
        )
        assert all(
            record["target_quality_gate"]["source_grounding_diagnostics"][
                "formula_slot_coverage"
            ]
            == record["target_quality_gate"]["formula_slot_coverage"]
            for record in records
        )

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


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
