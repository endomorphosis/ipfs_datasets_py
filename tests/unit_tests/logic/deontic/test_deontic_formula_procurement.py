"""Focused tests for procurement and award formula normalization."""

from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
)
from ipfs_datasets_py.logic.deontic.exports import (
    build_deterministic_parser_capability_profile_records,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.prover_syntax import validate_ir_with_provers
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_procurement_solicitation_award_duties_export_operative_predicates():
    examples = [
        (
            "The Bureau shall conduct procurement of the supplies.",
            "conduct procurement of the supplies",
            "O(∀x (Bureau(x) → ProcureSupplies(x)))",
            "ConductProcurementSupplies",
        ),
        (
            "The Clerk shall issue a solicitation for the bids.",
            "issue a solicitation for the bids",
            "O(∀x (Clerk(x) → SolicitBids(x)))",
            "IssueSolicitationBids",
        ),
        (
            "The Director shall make an award of the contract.",
            "make an award of the contract",
            "O(∀x (Director(x) → AwardContract(x)))",
            "MakeAwardContract",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)
        action_span = element["field_spans"]["action"]

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["text"][action_span[0]:action_span[1]] == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False


def test_procurement_selection_opening_and_administration_export_operative_predicates():
    examples = [
        (
            "The Board shall make a selection of the vendor.",
            "make a selection of the vendor",
            "O(∀x (Board(x) → SelectVendor(x)))",
            "MakeSelectionVendor",
        ),
        (
            "The Bureau shall conduct bid opening for the proposals.",
            "conduct bid opening for the proposals",
            "O(∀x (Bureau(x) → OpenProposals(x)))",
            "ConductBidOpeningProposals",
        ),
        (
            "The Officer shall perform contract administration of the agreement.",
            "perform contract administration of the agreement",
            "O(∀x (Officer(x) → AdministerAgreement(x)))",
            "PerformContractAdministrationAgreement",
        ),
    ]

    norms = []
    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)
        action_span = element["field_spans"]["action"]
        report = validate_ir_with_provers(norm)

        norms.append(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
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
        "procurement_contracting_duty",
        "procurement_contracting_duty",
        "procurement_contracting_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        "O(∀x (Board(x) → SelectVendor(x)))",
        "O(∀x (Bureau(x) → OpenProposals(x)))",
        "O(∀x (Officer(x) → AdministerAgreement(x)))",
    ]
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)


def test_procurement_slice_preserves_unresolved_numbered_exception_repair_gate():
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
    assert "cross_reference_requires_resolution" in blocked_record["blockers"]
    assert "exception_requires_scope_review" in blocked_record["blockers"]


def test_geospatial_record_duties_export_operative_predicates():
    examples = [
        (
            "The Surveyor shall perform mapping of the parcels.",
            "perform mapping of the parcels",
            "O(∀x (Surveyor(x) → MapParcels(x)))",
            "PerformMappingParcels",
        ),
        (
            "The Assessor shall conduct geocoding of the addresses.",
            "conduct geocoding of the addresses",
            "O(∀x (Assessor(x) → GeocodeAddresses(x)))",
            "ConductGeocodingAddresses",
        ),
        (
            "The Clerk shall prepare georeferencing of the plats.",
            "prepare georeferencing of the plats",
            "O(∀x (Clerk(x) → GeoreferencePlats(x)))",
            "PrepareGeoreferencingPlats",
        ),
        (
            "The Department shall maintain a survey of the boundaries.",
            "maintain a survey of the boundaries",
            "O(∀x (Department(x) → SurveyBoundaries(x)))",
            "MaintainSurveyBoundaries",
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
        assert norm.support_span == norm.source_span
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
        "geospatial_records_duty",
        "geospatial_records_duty",
        "geospatial_records_duty",
        "geospatial_records_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        expected_formula for _, _, expected_formula, _ in examples
    ]
    assert all(
        record["checked_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(
        record["grounded_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_emergency_operations_duties_export_operative_predicates():
    examples = [
        (
            "The Coordinator shall conduct evacuation of the residents.",
            "conduct evacuation of the residents",
            "O(∀x (Coordinator(x) → EvacuateResidents(x)))",
            "ConductEvacuationResidents",
        ),
        (
            "The Agency shall provide sheltering for displaced persons.",
            "provide sheltering for displaced persons",
            "O(∀x (Agency(x) → ShelterDisplacedPersons(x)))",
            "ProvideShelteringDisplacedPersons",
        ),
        (
            "The Officer shall perform rescue of occupants.",
            "perform rescue of occupants",
            "O(∀x (Officer(x) → RescueOccupants(x)))",
            "PerformRescueOccupants",
        ),
        (
            "The Bureau shall carry out emergency drill for evacuation routes.",
            "carry out emergency drill for evacuation routes",
            "O(∀x (Bureau(x) → DrillEvacuationRoutes(x)))",
            "CarryOutEmergencyDrillEvacuationRoutes",
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
        assert norm.support_span == norm.source_span
        assert element["text"][action_span[0] : action_span[1]] == action
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
        "emergency_operations_duty",
        "emergency_operations_duty",
        "emergency_operations_duty",
        "emergency_operations_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        expected_formula for _, _, expected_formula, _ in examples
    ]
    assert all(
        record["checked_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(
        record["grounded_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_rulemaking_enactment_amendment_and_repeal_export_operative_predicates():
    examples = [
        (
            "The Commission shall initiate rulemaking for the safety standard.",
            "initiate rulemaking for the safety standard",
            "O(∀x (Commission(x) → MakeRuleSafetyStandard(x)))",
            "InitiateRulemakingSafetyStandard",
        ),
        (
            "The Council shall approve enactment of the ordinance.",
            "approve enactment of the ordinance",
            "O(∀x (Council(x) → EnactOrdinance(x)))",
            "ApproveEnactmentOrdinance",
        ),
        (
            "The Board shall adopt an amendment to the rule.",
            "adopt an amendment to the rule",
            "O(∀x (Board(x) → AmendRule(x)))",
            "AdoptAmendmentRule",
        ),
        (
            "The Council shall effectuate a repeal of the regulation.",
            "effectuate a repeal of the regulation",
            "O(∀x (Council(x) → RepealRegulation(x)))",
            "EffectuateRepealRegulation",
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
        assert norm.support_span == norm.source_span
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
        "rulemaking_legislative_duty",
        "rulemaking_legislative_duty",
        "rulemaking_legislative_duty",
        "rulemaking_legislative_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        "O(∀x (Commission(x) → MakeRuleSafetyStandard(x)))",
        "O(∀x (Council(x) → EnactOrdinance(x)))",
        "O(∀x (Board(x) → AmendRule(x)))",
        "O(∀x (Council(x) → RepealRegulation(x)))",
    ]
    assert all(
        record["checked_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(
        record["grounded_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)


def test_rulemaking_slice_preserves_unresolved_numbered_exception_repair_gate():
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
    assert "cross_reference_requires_resolution" in blocked_record["blockers"]
    assert "exception_requires_scope_review" in blocked_record["blockers"]


def test_health_compliance_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The clinic shall conduct screening of applicants.",
            "conduct screening of applicants",
            "O(∀x (Clinic(x) → ScreenApplicants(x)))",
            "ConductScreeningApplicants",
        ),
        (
            "The health officer shall perform diagnosis of cases.",
            "perform diagnosis of cases",
            "O(∀x (HealthOfficer(x) → DiagnoseCases(x)))",
            "PerformDiagnosisCases",
        ),
        (
            "The provider shall administer vaccination to children.",
            "administer vaccination to children",
            "O(∀x (Provider(x) → VaccinateChildren(x)))",
            "AdministerVaccinationChildren",
        ),
        (
            "The department shall provide immunization of residents.",
            "provide immunization of residents",
            "O(∀x (Department(x) → ImmunizeResidents(x)))",
            "ProvideImmunizationResidents",
        ),
        (
            "The examiner shall conduct medical examination of drivers.",
            "conduct medical examination of drivers",
            "O(∀x (Examiner(x) → ExamineDrivers(x)))",
            "ConductMedicalExaminationDrivers",
        ),
        (
            "The laboratory shall perform laboratory analysis of samples.",
            "perform laboratory analysis of samples",
            "O(∀x (Laboratory(x) → AnalyzeSamples(x)))",
            "PerformLaboratoryAnalysisSamples",
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
        assert norm.support_span == norm.source_span
        assert element["text"][action_span[0] : action_span[1]] == action
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
        "health_compliance_duty",
        "health_compliance_duty",
        "health_compliance_duty",
        "health_compliance_duty",
        "health_compliance_duty",
        "health_compliance_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        formula for _, _, formula, _ in examples
    ]
    assert all(
        record["checked_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(
        record["grounded_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)


def test_health_compliance_prover_records_preserve_symbols_and_reference_blocker():
    element = extract_normative_elements(
        "The provider shall administer vaccination to children."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    records = [target.to_dict() for target in validate_ir_with_provers(norm).targets]

    assert len(records) == 5
    assert all(
        record["source_formula_symbols"] == ["Provider", "VaccinateChildren"]
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
    assert records[2]["target"] == "fol"
    assert records[2]["exported_formula"] == (
        "forall x. (Provider(x) -> VaccinateChildren(x))"
    )

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    blocked_norm = LegalNormIR.from_parser_element(blocked)
    blocked_record = build_deontic_formula_record_from_ir(blocked_norm)

    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
    assert blocked_record["proof_ready"] is False
    assert blocked_record["requires_validation"] is True
    assert blocked_record["repair_required"] is True


def test_evidence_custody_inventory_and_transfer_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall maintain a custody log for the samples.",
            "maintain a custody log for the samples",
            "O(∀x (Clerk(x) → LogCustodySamples(x)))",
            "MaintainCustodyLogSamples",
        ),
        (
            "The Officer shall prepare an exhibit inventory of the records.",
            "prepare an exhibit inventory of the records",
            "O(∀x (Officer(x) → InventoryExhibitRecords(x)))",
            "PrepareExhibitInventoryRecords",
        ),
        (
            "The custodian shall record evidence transfer of the exhibits.",
            "record evidence transfer of the exhibits",
            "O(∀x (Custodian(x) → RecordEvidenceTransferExhibits(x)))",
            "",
        ),
        (
            "The laboratory shall document chain of custody for the specimen.",
            "document chain of custody for the specimen",
            "O(∀x (Laboratory(x) → DocumentChainCustodySpecimen(x)))",
            "",
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
        assert norm.support_span == norm.source_span
        assert element["text"][action_span[0] : action_span[1]] == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        if rejected_predicate:
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
        expected_formula for _, _, expected_formula, _ in examples
    ]
    assert all(
        record["checked_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(
        record["grounded_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_code_maintenance_revision_annotation_and_supplement_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall prepare a revision of the charter.",
            "prepare a revision of the charter",
            "O(∀x (Clerk(x) → ReviseCharter(x)))",
            "PrepareRevisionCharter",
        ),
        (
            "The Commission shall publish annotations to the code.",
            "publish annotations to the code",
            "O(∀x (Commission(x) → AnnotateCode(x)))",
            "PublishAnnotationsCode",
        ),
        (
            "The Bureau shall issue a supplement to the ordinance.",
            "issue a supplement to the ordinance",
            "O(∀x (Bureau(x) → SupplementOrdinance(x)))",
            "IssueSupplementOrdinance",
        ),
        (
            "The Council shall adopt revisions for the rules.",
            "adopt revisions for the rules",
            "O(∀x (Council(x) → ReviseRules(x)))",
            "AdoptRevisionsRules",
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
        assert norm.support_span == norm.source_span
        assert element["text"][action_span[0] : action_span[1]] == action
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
        "code_maintenance_duty",
        "code_maintenance_duty",
        "code_maintenance_duty",
        "code_maintenance_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        expected_formula for _, _, expected_formula, _ in examples
    ]
    assert all(
        record["checked_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(
        record["grounded_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_meeting_governance_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall prepare minutes of the meeting.",
            "prepare minutes of the meeting",
            [16, 46],
            "O(∀x (Clerk(x) → RecordMinutesMeeting(x)))",
            "PrepareMinutesMeeting",
        ),
        (
            "The Board shall approve the agenda for the hearing.",
            "approve the agenda for the hearing",
            [16, 50],
            "O(∀x (Board(x) → SetAgendaHearing(x)))",
            "ApproveAgendaHearing",
        ),
        (
            "The Secretary shall conduct a roll call of members.",
            "conduct a roll call of members",
            [20, 50],
            "O(∀x (Secretary(x) → CallRollMembers(x)))",
            "ConductRollCallMembers",
        ),
        (
            "The Commission shall publish meeting notices to the public.",
            "publish meeting notices to the public",
            [21, 58],
            "O(∀x (Commission(x) → NoticeMeetingPublic(x)))",
            "PublishMeetingNoticesPublic",
        ),
    ]

    norms = []
    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)
        report = validate_ir_with_provers(norm)
        norms.append(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert element["text"][action_span[0] : action_span[1]] == action
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
        "meeting_governance_duty",
        "meeting_governance_duty",
        "meeting_governance_duty",
        "meeting_governance_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        expected_formula for _, _, _, expected_formula, _ in examples
    ]
    assert all(
        record["checked_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(
        record["grounded_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_derivative_records_processing_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall prepare an abstract of the order.",
            "prepare an abstract of the order",
            [16, 48],
            "O(∀x (Clerk(x) → AbstractOrder(x)))",
            "PrepareAbstractOrder",
        ),
        (
            "The Agency shall publish excerpts of the rules.",
            "publish excerpts of the rules",
            [17, 46],
            "O(∀x (Agency(x) → ExcerptRules(x)))",
            "PublishExcerptsRules",
        ),
        (
            "The Bureau shall provide captioning for the video record.",
            "provide captioning for the video record",
            [17, 56],
            "O(∀x (Bureau(x) → CaptionVideoRecord(x)))",
            "ProvideCaptioningVideoRecord",
        ),
        (
            "The Registrar shall assign tags to the filings.",
            "assign tags to the filings",
            [20, 46],
            "O(∀x (Registrar(x) → TagFilings(x)))",
            "AssignTagsFilings",
        ),
    ]

    norms = []
    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)
        report = validate_ir_with_provers(norm)
        norms.append(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert element["text"][action_span[0] : action_span[1]] == action
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
        "records_information_processing_duty",
        "records_information_processing_duty",
        "records_information_processing_duty",
        "records_information_processing_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        expected_formula for _, _, _, expected_formula, _ in examples
    ]
    assert all(
        record["checked_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(
        record["grounded_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
