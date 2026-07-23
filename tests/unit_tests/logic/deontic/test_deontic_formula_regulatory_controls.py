"""Focused tests for regulatory control formula normalization."""

from ipfs_datasets_py.logic.deontic.exports import (
    build_deterministic_parser_capability_profile_records,
)
from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.prover_syntax import validate_ir_with_provers
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_regulatory_control_duties_export_operative_predicates():
    examples = [
        (
            "The Director shall impose a quarantine on the shipment.",
            "impose a quarantine on the shipment",
            "O(∀x (Director(x) → QuarantineShipment(x)))",
            "ImposeQuarantineShipment",
        ),
        (
            "The Commissioner shall order an embargo against the goods.",
            "order an embargo against the goods",
            "O(∀x (Commissioner(x) → EmbargoGoods(x)))",
            "OrderEmbargoGoods",
        ),
        (
            "The Bureau shall conduct a recall of the product.",
            "conduct a recall of the product",
            "O(∀x (Bureau(x) → RecallProduct(x)))",
            "ConductRecallProduct",
        ),
        (
            "The Officer shall issue a condemnation of the structure.",
            "issue a condemnation of the structure",
            "O(∀x (Officer(x) → CondemnStructure(x)))",
            "IssueCondemnationStructure",
        ),
    ]

    norms = []
    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)
        report = validate_ir_with_provers(norm)
        action_span = element["field_spans"]["action"]
        norms.append(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert element["text"][action_span[0]:action_span[1]] == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False
        assert report.syntax_valid is True
        assert report.proof_ready is True
        assert report.valid_target_count == 5

    capability_records = build_deterministic_parser_capability_profile_records(norms)

    assert [record["capability_family"] for record in capability_records] == [
        "regulatory_control_duty",
        "regulatory_control_duty",
        "regulatory_control_duty",
        "regulatory_control_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        "O(∀x (Director(x) → QuarantineShipment(x)))",
        "O(∀x (Commissioner(x) → EmbargoGoods(x)))",
        "O(∀x (Bureau(x) → RecallProduct(x)))",
        "O(∀x (Officer(x) → CondemnStructure(x)))",
    ]
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)


def test_regulatory_control_slice_preserves_unresolved_numbered_exception_repair_gate():
    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    blocked_norm = LegalNormIR.from_parser_element(blocked)
    blocked_record = build_deontic_formula_record_from_ir(blocked_norm)

    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
    assert blocked_record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert blocked_record["proof_ready"] is False
    assert blocked_record["requires_validation"] is True
    assert blocked_record["repair_required"] is True


def test_data_protection_duties_export_operative_predicates():
    examples = [
        (
            "The Bureau shall perform de-identification of the records.",
            "perform de-identification of the records",
            "O(∀x (Bureau(x) → DeidentifyRecords(x)))",
            "PerformDeIdentificationRecords",
        ),
        (
            "The Clerk shall conduct hashing of the identifier.",
            "conduct hashing of the identifier",
            "O(∀x (Clerk(x) → HashIdentifier(x)))",
            "ConductHashingIdentifier",
        ),
        (
            "The Registrar shall carry out encryption of the file.",
            "carry out encryption of the file",
            "O(∀x (Registrar(x) → EncryptFile(x)))",
            "CarryOutEncryptionFile",
        ),
        (
            "The Processor shall complete tokenization of the account number.",
            "complete tokenization of the account number",
            "O(∀x (Processor(x) → TokenizeAccountNumber(x)))",
            "CompleteTokenizationAccountNumber",
        ),
        (
            "The Agency shall make pseudonymization of the dataset.",
            "make pseudonymization of the dataset",
            "O(∀x (Agency(x) → PseudonymizeDataset(x)))",
            "MakePseudonymizationDataset",
        ),
        (
            "The Court shall order sealing of the juvenile record.",
            "order sealing of the juvenile record",
            "O(∀x (Court(x) → SealJuvenileRecord(x)))",
            "OrderSealingJuvenileRecord",
        ),
    ]

    norms = []
    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)
        report = validate_ir_with_provers(norm)
        action_span = element["field_spans"]["action"]
        norms.append(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert element["text"][action_span[0]:action_span[1]] == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False
        assert report.syntax_valid is True
        assert report.proof_ready is True
        assert report.valid_target_count == 5

    capability_records = build_deterministic_parser_capability_profile_records(norms)

    assert [record["capability_family"] for record in capability_records] == [
        "data_protection_duty",
        "data_protection_duty",
        "data_protection_duty",
        "data_protection_duty",
        "data_protection_duty",
        "data_protection_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        "O(∀x (Bureau(x) → DeidentifyRecords(x)))",
        "O(∀x (Clerk(x) → HashIdentifier(x)))",
        "O(∀x (Registrar(x) → EncryptFile(x)))",
        "O(∀x (Processor(x) → TokenizeAccountNumber(x)))",
        "O(∀x (Agency(x) → PseudonymizeDataset(x)))",
        "O(∀x (Court(x) → SealJuvenileRecord(x)))",
    ]
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)


def test_data_protection_slice_preserves_unresolved_numbered_exception_repair_gate():
    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    blocked_norm = LegalNormIR.from_parser_element(blocked)
    blocked_record = build_deontic_formula_record_from_ir(blocked_norm)

    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
    assert blocked_record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert blocked_record["proof_ready"] is False
    assert blocked_record["requires_validation"] is True
    assert blocked_record["repair_required"] is True
    assert blocked_record["deterministic_resolution"] == {}


def test_evidence_custody_duties_export_operative_predicates():
    examples = [
        (
            "The officer shall perform evidence preservation for the exhibit.",
            "perform evidence preservation for the exhibit",
            "O(∀x (Officer(x) → PreserveEvidenceExhibit(x)))",
            "PerformEvidencePreservationExhibit",
        ),
        (
            "The clerk shall make an evidence inventory of the seized property.",
            "make an evidence inventory of the seized property",
            "O(∀x (Clerk(x) → InventoryEvidenceSeizedProperty(x)))",
            "MakeEvidenceInventorySeizedProperty",
        ),
        (
            "The laboratory shall conduct sample accessioning for the specimen.",
            "conduct sample accessioning for the specimen",
            "O(∀x (Laboratory(x) → AccessionSpecimen(x)))",
            "ConductSampleAccessioningSpecimen",
        ),
        (
            "The custodian shall document chain of custody for the sample.",
            "document chain of custody for the sample",
            "O(∀x (Custodian(x) → DocumentChainCustodySample(x)))",
            "DocumentChainOfCustodySample",
        ),
    ]

    norms = []
    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)
        report = validate_ir_with_provers(norm)
        action_span = element["field_spans"]["action"]
        norms.append(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert element["text"][action_span[0]:action_span[1]] == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False
        assert report.syntax_valid is True
        assert report.proof_ready is True
        assert report.valid_target_count == 5

    capability_records = build_deterministic_parser_capability_profile_records(norms)

    assert [record["capability_family"] for record in capability_records] == [
        "evidence_custody_duty",
        "evidence_custody_duty",
        "evidence_custody_duty",
        "evidence_custody_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        "O(∀x (Officer(x) → PreserveEvidenceExhibit(x)))",
        "O(∀x (Clerk(x) → InventoryEvidenceSeizedProperty(x)))",
        "O(∀x (Laboratory(x) → AccessionSpecimen(x)))",
        "O(∀x (Custodian(x) → DocumentChainCustodySample(x)))",
    ]
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)


def test_evidence_custody_slice_preserves_unresolved_numbered_exception_repair_gate():
    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    blocked_norm = LegalNormIR.from_parser_element(blocked)
    blocked_record = build_deontic_formula_record_from_ir(blocked_norm)

    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
    assert blocked_record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert blocked_record["proof_ready"] is False
    assert blocked_record["requires_validation"] is True
    assert blocked_record["repair_required"] is True
