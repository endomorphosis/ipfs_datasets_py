"""Tests for prover/export semantic-family parity."""

from ipfs_datasets_py.logic.deontic.exports import (
    build_deterministic_parser_capability_profile_record,
    build_prover_syntax_target_coverage_records_from_irs,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.prover_syntax import (
    LOCAL_PROVER_TARGETS,
    validate_ir_with_provers,
)
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    extract_normative_elements,
)


def test_prover_semantic_families_match_export_capability_families():
    examples = [
        (
            "The Clerk shall record the deed.",
            "O(∀x (Clerk(x) → RecordDeed(x)))",
            "legal_recordkeeping_duty",
        ),
        (
            "The Agency shall redact the record.",
            "O(∀x (Agency(x) → RedactRecord(x)))",
            "data_protection_duty",
        ),
        (
            "The Officer shall preserve evidence.",
            "O(∀x (Officer(x) → PreserveEvidence(x)))",
            "evidence_custody_duty",
        ),
        (
            "The Registrar shall index the filing.",
            "O(∀x (Registrar(x) → IndexFiling(x)))",
            "records_information_processing_duty",
        ),
        (
            "The Bureau shall provide public access to records.",
            "O(∀x (Bureau(x) → ProvidePublicAccessRecords(x)))",
            "public_access_records_duty",
        ),
    ]

    for text, expected_formula, expected_family in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        capability = build_deterministic_parser_capability_profile_record(norm)
        report = validate_ir_with_provers(norm)
        records = [target.to_dict() for target in report.targets]
        coverage = build_prover_syntax_target_coverage_records_from_irs([norm])[0]

        assert capability["formula"] == expected_formula
        assert capability["capability_family"] == expected_family
        assert report.syntax_valid is True
        assert report.proof_ready is True
        assert [record["target"] for record in records] == list(LOCAL_PROVER_TARGETS)
        assert all(
            record["target_components"]["semantic_formula_family"] == expected_family
            for record in records
        )
        assert all(
            record["target_components"]["semantic_formula_predicate"]
            in record["exported_formula_symbols"]
            for record in records
        )
        assert coverage["formal_syntax_valid"] is True
        assert coverage["semantic_formula_families"] == [expected_family]
        assert coverage["semantic_formula_family_distribution"] == {
            expected_family: len(LOCAL_PROVER_TARGETS)
        }
        assert coverage["target_semantic_family_consistent"] is True
        assert coverage["semantic_family_summary"]["semantic_formula_family"] == (
            expected_family
        )


def test_prover_semantic_family_slice_preserves_numbered_reference_repair_gate():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)
    coverage = build_prover_syntax_target_coverage_records_from_irs([norm])[0]

    assert element["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in element["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in element["llm_repair"]["reasons"]
    assert norm.proof_ready is False
    assert coverage["formal_syntax_valid"] is False
    assert coverage["requires_validation"] is True
    assert coverage["semantic_formula_families"] == ["ordinary_duty"]
    assert coverage["target_semantic_family_consistent"] is True
    assert "failed_prover_quality_check:formula_proof_ready" in coverage[
        "coverage_blockers"
    ]
