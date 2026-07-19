"""Deterministic decompiler for modal IR.

The decompiler keeps two views separate:

* ``DecodedModalText.text`` is a provenance-backed semantic reconstruction of
  the source text carried by the IR, so round-trip diagnostics measure whether
  the compiler/decompiler destroyed information.
* Modal formulas, operators, predicates, cues, and ontology frames remain in
  phrase metadata as audit evidence for expert review and program synthesis.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    FrameCandidate,
    frame_ontology_terms,
    frame_ontology_terms_from_feature_keys,
    normalize_frame_ontology_term,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    DEFAULT_MODAL_REGISTRY,
)

_CONDITION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("provided that", "provided_that"),
    ("subject to this subsection", "subject_to_this_subsection"),
    ("subject to this subchapter", "subject_to_this_subchapter"),
    ("subject to this subparagraph", "subject_to_this_subparagraph"),
    ("subject to this paragraph", "subject_to_this_paragraph"),
    ("subject to this section", "subject_to_this_section"),
    ("subject to this chapter", "subject_to_this_chapter"),
    ("subject to this title", "subject_to_this_title"),
    ("subject to subsection", "subject_to_subsection"),
    ("subject to subchapter", "subject_to_subchapter"),
    ("subject to subparagraph", "subject_to_subparagraph"),
    ("subject to paragraph", "subject_to_paragraph"),
    ("subject to section", "subject_to_section"),
    ("subject to chapter", "subject_to_chapter"),
    ("subject to title", "subject_to_title"),
    (
        "subject to the terms and conditions",
        "subject_to_the_terms_and_conditions",
    ),
    (
        "subject to such terms and conditions",
        "subject_to_such_terms_and_conditions",
    ),
    ("subject to terms and conditions", "subject_to_terms_and_conditions"),
    ("subject only to", "subject_only_to"),
    ("subject however to", "subject_however_to"),
    ("subject to", "subject_to"),
    ("in the case of", "in_the_case_of"),
    ("in the event that", "in_the_event_that"),
    ("in connection with", "in_connection_with"),
    ("in order to", "in_order_to"),
    ("notwithstanding", "notwithstanding"),
    ("for the purposes of", "for_the_purposes_of"),
    ("for purposes of", "for_purposes_of"),
    ("with respect to", "with_respect_to"),
    ("as otherwise provided in", "as_otherwise_provided_in"),
    ("as set forth in", "as_set_forth_in"),
    ("as described in", "as_described_in"),
    ("as defined in", "as_defined_in"),
    ("in accordance with", "in_accordance_with"),
    ("as provided in", "as_provided_in"),
    ("referred to in", "referred_to_in"),
    ("described in", "described_in"),
    ("defined in", "defined_in"),
    ("pursuant to", "pursuant_to"),
    ("under", "under"),
    ("to the extent", "to_the_extent"),
    ("to the extent provided", "to_the_extent_provided"),
    ("not later than", "not_later_than"),
    ("no later than", "no_later_than"),
    ("only after", "only_after"),
    ("thereafter", "thereafter"),
    ("if", "if"),
    ("when", "when"),
    ("until", "until"),
    ("during", "during"),
    ("within", "within"),
    ("after", "after"),
    ("before", "before"),
    ("by", "by"),
    ("upon", "upon"),
)
_EXCEPTION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("except as otherwise provided", "except_as_otherwise_provided"),
    ("except as provided in", "except_as_provided_in"),
    ("except to the extent", "except_to_the_extent"),
    ("except that", "except_that"),
    ("except as", "except_as"),
    ("provided that", "provided_that"),
    ("provided", "provided"),
    ("unless", "unless"),
    ("except", "except"),
)
_TEMPORAL_CLAUSE_PREFIX_RELATIONS: dict[str, str] = {
    "when": "when",
    "until": "until",
    "during": "during",
    "after": "after",
    "only_after": "after",
    "before": "before",
    "by": "deadline",
    "no_later_than": "deadline",
    "not_later_than": "deadline",
    "within": "deadline",
    "upon": "after",
    "thereafter": "after",
}
_USCODE_FALLBACK_STATUS_KEYWORDS: tuple[str, ...] = (
    "reclassified",
    "transferred",
    "codification",
    "repealed",
    "omitted",
    "reserved",
    "vacant",
    "renumbered",
    "terminated",
)
_USCODE_EDITORIAL_NOTE_LABELS: tuple[str, ...] = (
    "Editorial Notes",
    "Codification",
    "References in Text",
    "Historical and Revision Notes",
    "Prior Provisions",
    "Amendments",
    "Statutory Notes and Related Subsidiaries",
)
_PACKET_000600_USCODE_RECONSTRUCTION_ATOMS = frozenset(
    {
        "additional_distribution",
        "board_civil_action_authority",
        "board_enforcement_authority",
        "code_supplement_distribution",
        "district_columbia_code_supplement",
        "juvenile_delinquency_prevention",
        "juvenile_justice_program",
        "juvenile_justice_system_improvement",
        "justice_system_improvement",
        "land_accretion_resource",
        "land_improvement_exception",
        "land_parcel_exception",
        "rail_carrier_injunction",
        "rail_carrier_violation_enforcement",
        "state_water_pollution_revolving_fund",
        "statutory_operation_exception",
        "transportation_order_certificate_enforcement",
        "treatment_works_construction_assistance",
        "united_states_code_supplement",
        "water_pollution_control_program",
        "water_pollution_control_revolving_fund",
        "water_quality_management_program",
    }
)
_PACKET_000901_USCODE_RECONSTRUCTION_ATOMS = frozenset(
    {
        "adverse_action_procedure",
        "employee_adverse_action",
        "employee_notice_period",
        "government_agency_equipment_transfer",
        "government_printing_equipment",
        "program_payment_authority",
        "rural_development_grant_program",
        "secretary_payment_adjustment",
    }
)
_PACKET_000184_USCODE_RECONSTRUCTION_ATOMS = frozenset(
    {
        "crisis_counseling_assistance",
        "crisis_counseling_training",
        "disaster_mental_health_service",
        "investigation_oath_authority",
        "investigation_testimony_authority",
        "ready_reserve_muster_duty",
        "reserve_muster_authority",
        "student_assignment_transportation",
        "student_transportation_assignment",
    }
)
_PACKET_000188_USCODE_RECONSTRUCTION_ATOMS = frozenset(
    {
        "crime_control_enforcement_program",
        "economic_development_trade_benefit",
        "federal_reclamation_project_advance",
        "government_project_completion_advance",
        "laborer_mechanic_wage_standard",
        "missing_children_advisory_board",
        "project_safe_neighborhoods_grant",
        "public_building_work_contract",
        "service_connected_disability_compensation",
        "sub_saharan_africa_trade_benefit",
        "veterans_compensation_benefit",
    }
)
_PACKET_000189_FRAME_RECONSTRUCTION_ATOMS = frozenset(
    {
        "administrative_direction_authority",
        "administrative_protection_development",
        "annuity_receipt_right",
        "borrower_document_access",
        "dividend_declaration_authority",
        "document_access_right",
        "house_regulation_prescription_authority",
        "records_inspection_right",
        "regulation_prescription_authority",
        "service_of_process_agent",
    }
)
_PACKET_000190_USCODE_RECONSTRUCTION_ATOMS = frozenset(
    {
        "administrative_coordination_duty",
        "flood_map_certification",
        "flood_mapping_program",
        "labor_dispute_injunction",
        "national_emergency_labor_dispute",
        "national_strategic_uranium_reserve",
        "reserve_establishment_authority",
        "special_adapted_housing_coordination",
        "technical_mapping_advisory_review",
        "uranium_reserve_resource",
        "uscode_omitted_codification_record",
        "uscode_repealed_editorial_record",
    }
)
_PACKET_000626_USCODE_RECONSTRUCTION_ATOMS = frozenset(
    {
        "congressional_member_compensation_allowance",
        "national_military_park_resource",
        "national_security_act_reclassification",
        "uscode_appropriation_authorization_record",
        "uscode_capitol_visitor_center_administration",
    }
)
_PACKET_000627_USCODE_RECONSTRUCTION_ATOMS = frozenset(
    {
        "child_care_health_safety_program",
        "child_care_service_program",
        "coast_guard_child_care_program",
        "education_research_statistics_dissemination",
        "education_sciences_reform",
        "family_support_child_care_housing",
        "state_child_care_allotment",
        "state_child_care_program",
        "state_program_allotment_authority",
    }
)
_PACKET_000629_USCODE_RECONSTRUCTION_ATOMS = frozenset(
    {
        "agricultural_college_aid_appropriation",
        "college_racial_discrimination_prohibition",
        "cuyahoga_valley_national_park_status",
        "drug_free_communities_support_program",
        "ready_reserve_muster_duty",
        "reserve_muster_authority",
        "uscode_voting_elections_reclassification",
    }
)
_PACKET_000630_USCODE_RECONSTRUCTION_ATOMS = frozenset(
    {
        "army_officer_school_detail",
        "marine_corps_medical_officer",
        "marine_corps_headquarters_staff",
        "military_post_school_use",
        "preventive_health_demonstration_project",
        "preventive_health_service_grant",
        "public_housing_agency_assistance",
        "supplemental_preventive_health_grant",
        "wildlife_conservation_order",
    }
)
_PACKET_000633_USCODE_RECONSTRUCTION_ATOMS = frozenset(
    {
        "agreement_military_park_authority",
        "cumulative_remedy_preservation",
        "helen_keller_national_center_registry",
        "indian_loan_guaranty_power",
        "loan_guarantee_authority",
        "public_charter_school_program",
        "public_corporation_agreement_authority",
        "remedies_as_cumulative",
        "service_connected_disability_compensation",
        "uscode_registry_record",
        "veterans_compensation_benefit",
    }
)
_LEGAL_SEMANTIC_ATOM_PHRASES: tuple[tuple[str, str], ...] = (
    ("administration of this chapter", "chapter_administration"),
    ("administration and enforcement", "administration_enforcement"),
    ("monitoring and enforcement", "monitoring_enforcement"),
    ("monitoring enforcement", "monitoring_enforcement"),
    ("monitoring and enforcement of the", "monitoring_enforcement"),
    ("enter into contracts", "contracting_authority"),
    ("enter into a contract", "contracting_authority"),
    ("make cooperative agreements", "cooperative_agreement_authority"),
    ("cooperative agreements", "cooperative_agreement_authority"),
    ("cooperative agreement", "cooperative_agreement_authority"),
    ("machinery, material, equipment, or supplies", "government_printing_equipment"),
    ("printing, binding, and blank-book work", "government_printing_equipment"),
    ("photolithography", "government_printing_equipment"),
    ("lithography", "government_printing_equipment"),
    ("other government agencies", "government_agency_equipment_transfer"),
    ("adverse actions", "employee_adverse_action"),
    ("adverse action", "employee_adverse_action"),
    ("advance written notice", "employee_notice_period"),
    ("30 days' advance written notice", "employee_notice_period"),
    ("reasonable time to answer", "adverse_action_procedure"),
    ("is entitled to", "adverse_action_procedure"),
    ("make payments", "program_payment_authority"),
    ("payment adjustment", "secretary_payment_adjustment"),
    ("rural development", "rural_development_grant_program"),
    ("grant program", "rural_development_grant_program"),
    ("project safe neighborhoods", "project_safe_neighborhoods_grant"),
    ("crime control and law enforcement", "crime_control_enforcement_program"),
    ("law enforcement matters", "crime_control_enforcement_program"),
    ("service-connected disability", "service_connected_disability_compensation"),
    ("service connected disability", "service_connected_disability_compensation"),
    ("compensation for service-connected disability", "veterans_compensation_benefit"),
    ("compensation for service connected disability", "veterans_compensation_benefit"),
    ("veterans' benefits", "veterans_compensation_benefit"),
    ("veterans benefits", "veterans_compensation_benefit"),
    ("sub-saharan africa", "sub_saharan_africa_trade_benefit"),
    ("sub saharan africa", "sub_saharan_africa_trade_benefit"),
    ("trade benefits", "sub_saharan_africa_trade_benefit"),
    ("economic development related issues", "economic_development_trade_benefit"),
    ("economic development", "economic_development_trade_benefit"),
    ("advisory board on missing children", "missing_children_advisory_board"),
    ("missing children", "missing_children_advisory_board"),
    ("advances by government", "government_project_completion_advance"),
    ("complete government reclamation projects", "federal_reclamation_project_advance"),
    ("government reclamation projects", "federal_reclamation_project_advance"),
    ("reclamation projects", "federal_reclamation_project_advance"),
    ("public buildings and works", "public_building_work_contract"),
    ("public buildings, grounds, and parks", "public_building_work_contract"),
    ("laborers and mechanics", "laborer_mechanic_wage_standard"),
    ("rate of wages", "laborer_mechanic_wage_standard"),
    ("lease of reserved lands", "reserved_land_lease_authority"),
    ("reserved lands", "reserved_land"),
    ("reservation of lands", "reserved_land"),
    ("reconveying to the united states title", "federal_land_reconveyance"),
    ("reconveying title", "federal_land_reconveyance"),
    ("rental rates", "rental_rate_authority"),
    ("disposition of revenues", "revenue_disposition"),
    ("information technology acquisition", "information_technology_acquisition"),
    ("information technology management", "information_technology_management"),
    ("telemedicine and distance learning services", "telemedicine_distance_learning"),
    ("distance learning services", "telemedicine_distance_learning"),
    ("administration from the u.s. government publishing office", "program_administration"),
    ("administration from the us government publishing office", "program_administration"),
    ("administration", "program_administration"),
    ("authorization of appropriations", "appropriation_authorization"),
    ("authorized to be appropriated", "appropriation_authorization"),
    ("appropriations are authorized", "appropriation_authorization"),
    ("authorization of appropriations", "uscode_appropriation_authorization_record"),
    ("authorized to be appropriated", "uscode_appropriation_authorization_record"),
    ("national military parks", "national_military_park_resource"),
    ("national military park", "national_military_park_resource"),
    ("developing institutions", "developing_institution_program"),
    (
        "higher education resources and student assistance",
        "higher_education_student_assistance",
    ),
    ("higher education resources", "higher_education_student_assistance"),
    ("student assistance", "higher_education_student_assistance"),
    ("job corps", "job_corps_program"),
    ("workforce investment systems", "workforce_investment_system"),
    ("sense of congress", "sense_of_congress"),
    ("alaskan ownership", "alaskan_ownership_policy"),
    ("alaska natural gas pipeline", "alaska_natural_gas_pipeline"),
    ("committee allocations", "congressional_budget_allocation"),
    ("committee allocation", "congressional_budget_allocation"),
    ("congressional budget", "congressional_budget_process"),
    ("budget allocations", "congressional_budget_allocation"),
    ("budget allocation", "congressional_budget_allocation"),
    ("appropriations committee", "appropriations_committee_duty"),
    ("sustainable chemistry research and education", "sustainable_chemistry_research"),
    ("sustainable chemistry", "sustainable_chemistry_research"),
    ("make awards on a competitive basis", "competitive_award_program"),
    ("make awards", "award_program"),
    ("jurisdiction of new york state courts in civil actions", "state_court_civil_jurisdiction"),
    ("jurisdiction of new york state courts", "state_court_jurisdiction"),
    ("state courts in civil actions", "state_court_civil_jurisdiction"),
    ("civil actions", "civil_action"),
    ("civil action", "civil_action"),
    ("civil action in admiralty", "admiralty_civil_action"),
    ("action in admiralty", "admiralty_civil_action"),
    ("civil enforcement", "civil_enforcement"),
    ("public policy exception", "public_policy_exception"),
    ("manifestly contrary to the public policy", "public_policy_exception"),
    ("waiver of immunity", "sovereign_immunity_waiver"),
    ("waive immunity", "sovereign_immunity_waiver"),
    ("privately owned or operated", "private_vessel_ownership_condition"),
    ("privately owned or possessed", "private_property_possession_condition"),
    ("former jeopardy", "former_jeopardy_protection"),
    ("double jeopardy", "former_jeopardy_protection"),
    ("jeopardy for the same offense", "former_jeopardy_protection"),
    ("judicial review of certain actions", "presidential_action_judicial_review"),
    ("judicial review of certain action", "presidential_action_judicial_review"),
    ("judicial review", "judicial_review"),
    ("presidential order", "presidential_order"),
    ("presidential action", "presidential_action"),
    ("receiverships", "receivership_administration"),
    ("receivership", "receivership_administration"),
    ("appointment of a receiver", "receiver_appointment"),
    ("appoint a receiver", "receiver_appointment"),
    ("receiver shall", "receiver_duty"),
    ("protection from liability", "liability_protection"),
    ("protected from liability", "liability_protection"),
    ("liability protection", "liability_protection"),
    ("no cause of action shall lie", "liability_protection"),
    ("cybersecurity information sharing", "cybersecurity_information_sharing"),
    ("cybersecurity information", "cybersecurity_information_sharing"),
    ("information sharing", "information_sharing"),
    ("the term director means", "director_government_actor_definition"),
    ("director means the", "director_government_actor_definition"),
    ("the term director", "director_government_actor"),
    ("consultation and cooperation", "consultation_cooperation"),
    (
        "preservation of friendly foreign relations",
        "friendly_foreign_relations_preservation",
    ),
    ("friendly foreign relations", "friendly_foreign_relations"),
    ("following consultation", "consultation"),
    ("initiation of discussions", "interinstitutional_discussion"),
    ("initiate discussions", "interinstitutional_discussion"),
    ("provide advice and assistance", "development_advice_assistance"),
    ("debt reduction and conversion", "sovereign_debt_conversion"),
    ("reducing and converting sovereign debt", "sovereign_debt_conversion"),
    ("multilateral investment guarantee agency", "multilateral_investment_guarantee_agency"),
    ("multilateral investment guarantee", "multilateral_investment_guarantee"),
    ("investment guarantee agency", "investment_guarantee_agency"),
    ("investment guarantee", "investment_guarantee_authority"),
    ("human welfare and natural resource programs", "human_welfare_resource_program"),
    ("human welfare", "human_welfare_resource_program"),
    ("boundary and division fences", "boundary_division_fence"),
    ("build and maintain", "build_maintain_duty"),
    ("game and bird preserves", "game_bird_preserve_protection"),
    ("national game preserve", "game_preserve"),
    ("white horse hill national game preserve", "white_horse_hill_game_preserve"),
    ("government publications", "government_publication_depository_access"),
    ("public documents printed after expiration of terms", "post_term_public_document_allotment"),
    ("allotments of public documents", "public_document_allotment"),
    ("congressional allotment of public documents", "public_document_allotment"),
    ("additional distribution", "additional_distribution"),
    ("additional copies of supplements", "code_supplement_distribution"),
    (
        "supplements to the code of laws of the united states",
        "code_supplement_distribution",
    ),
    ("code of laws of the united states", "united_states_code_supplement"),
    ("district of columbia code", "district_columbia_code_supplement"),
    ("free use of government publications", "government_publication_depository_access"),
    ("depository libraries", "government_publication_depository_access"),
    ("distribution of precedents", "congressional_precedents_distribution"),
    ("sets of the precedents", "congressional_precedents_distribution"),
    ("official use", "official_use_restriction"),
    ("property of the united states government", "government_property_marking"),
    ("deposit of obscene matter", "postal_matter_deposit"),
    ("deposits in the mail any matter", "postal_matter_deposit"),
    ("deposits in mail any matter", "postal_matter_deposit"),
    ("matter declared nonmailable", "nonmailable_matter"),
    ("nonmailable by law", "nonmailable_matter"),
    ("obscene matter", "obscene_matter"),
    ("penalty for nonmailable matter", "nonmailable_matter_penalty"),
    (
        "nonmailable matter shall be subject to penalties",
        "nonmailable_matter_penalty",
    ),
    ("mail any matter", "postal_mail_matter"),
    ("free use of the general public", "public_access_requirement"),
    ("retiring members to documents", "retiring_member_document_right"),
    ("rights of retiring members", "retiring_member_document_right"),
    ("expiration of terms of members of congress", "post_term_member_right"),
    ("disposal of unwanted publications", "publication_disposal_authority"),
    ("dispose of them after retention", "publication_disposal_authority"),
    ("government losses in shipment", "government_shipment_loss_prevention"),
    ("shipment of valuables", "valuable_shipment_regulation"),
    ("valuables in shipment", "valuable_shipment_regulation"),
    ("obligations of public housing agencies", "public_housing_agency_obligation"),
    ("obligations issued by a public housing agency", "public_housing_agency_obligation"),
    ("public housing agencies", "public_housing_agency"),
    ("public housing agency", "public_housing_agency"),
    ("low-income housing projects", "low_income_housing_project"),
    ("low income housing projects", "low_income_housing_project"),
    ("full faith and credit of united states", "federal_full_faith_credit_security"),
    ("full faith and credit of the united states", "federal_full_faith_credit_security"),
    ("pledged as security", "federal_security_pledge"),
    ("contestability", "obligation_contestability"),
    ("tax exemption", "tax_exemption"),
    ("exempt from taxation", "tax_exemption"),
    ("shall be exempt from taxation", "tax_exemption"),
    ("negotiable bill of lading", "negotiable_bill_of_lading"),
    ("bill of lading", "bill_of_lading"),
    ("may be negotiated by indorsement", "bill_lading_indorsement_negotiation"),
    ("negotiated by indorsement", "bill_lading_indorsement_negotiation"),
    ("indorsement may be made", "bill_lading_indorsement_negotiation"),
    ("deliverable to the order", "order_document_delivery"),
    ("comply with the regulations", "regulatory_compliance_duty"),
    ("federal compliance", "federal_compliance_duty"),
    ("federal agency shall adopt procedures", "federal_compliance_duty"),
    ("shall adopt procedures necessary to assure", "federal_compliance_duty"),
    ("federal building energy standards", "federal_building_energy_standard"),
    (
        "meet or exceed the federal building energy standards",
        "federal_building_energy_standard",
    ),
    ("access to documents and information", "document_access_right"),
    ("copies of all documents signed by the borrower", "borrower_document_access"),
    ("copies of each appraisal", "borrower_document_access"),
    ("authority to prescribe regulations", "regulation_prescription_authority"),
    (
        "committee on house oversight of the house of representatives shall have authority to prescribe regulations",
        "house_regulation_prescription_authority",
    ),
    ("prescribe regulations governing", "regulation_prescription_authority"),
    ("records and inspection", "records_inspection_right"),
    ("may inspect the records", "records_inspection_right"),
    ("right to receive and receipt for all annuity money", "annuity_receipt_right"),
    ("administration, protection, and development", "administrative_protection_development"),
    ("under the direction of the secretary", "administrative_direction_authority"),
    ("service of process", "service_of_process_agent"),
    ("designated agent", "service_of_process_agent"),
    ("may declare a dividend", "dividend_declaration_authority"),
    (
        "penalty for operating under suspended tariff or service contract",
        "suspended_tariff_service_contract_penalty",
    ),
    ("operating under suspended tariff", "suspended_tariff_operation"),
    ("suspended tariff or service contract", "suspended_tariff_service_contract"),
    (
        "tariff or service contract that has been suspended",
        "suspended_tariff_service_contract",
    ),
    ("service contract that has been suspended", "service_contract_suspension"),
    ("tariff that has been suspended", "tariff_suspension"),
    (
        "common carrier that accepts or handles cargo",
        "common_carrier_cargo_carriage",
    ),
    ("accepts or handles cargo for carriage", "cargo_carriage"),
    ("cargo for carriage", "cargo_carriage"),
    ("common carrier", "common_carrier"),
    ("service contract", "service_contract"),
    ("suspended tariff", "tariff_suspension"),
    ("risk of loss and destruction", "loss_damage_risk_mitigation"),
    ("annual report", "annual_report"),
    ("reports to congress", "congressional_report_duty"),
    ("report to congress", "congressional_report_duty"),
    ("report to congress; contents", "report_contents"),
    ("report contents", "report_contents"),
    ("contents within one year", "report_contents"),
    ("colorado river floodway", "colorado_river_floodway_report"),
    ("secretary's recommendations", "secretary_recommendation_report"),
    ("secretary recommendations", "secretary_recommendation_report"),
    ("comprehensive inventory", "inventory_study_report"),
    ("uranium inventory study", "uranium_inventory_study"),
    ("national strategic uranium reserve", "national_strategic_uranium_reserve"),
    ("uranium reserve", "uranium_reserve_resource"),
    ("natural uranium and uranium equivalents", "uranium_reserve_resource"),
    ("flood insurance rate map certification", "flood_map_certification"),
    ("flood mapping program", "flood_mapping_program"),
    ("flood insurance rate map", "flood_map_certification"),
    ("technical mapping advisory council", "technical_mapping_advisory_review"),
    (
        "only after review by the technical mapping advisory council",
        "technical_mapping_advisory_review",
    ),
    ("injunctions during national emergencies", "national_emergency_labor_dispute"),
    ("injunctions during national emerg", "national_emergency_labor_dispute"),
    ("conciliation of labor disputes", "labor_dispute_injunction"),
    ("labor disputes national emergencies", "national_emergency_labor_dispute"),
    ("inventory study", "inventory_study_report"),
    ("generation-skipping transfer", "generation_skipping_transfer_tax"),
    ("generation skipping transfer", "generation_skipping_transfer_tax"),
    ("taxable amount", "taxable_amount_determination"),
    ("tax shall be computed", "tax_computation_rule"),
    ("university based research and development grant program", "university_research_grant_program"),
    ("university-based research and development grant program", "university_research_grant_program"),
    ("university based research and development program", "university_research_program"),
    ("university-based research and development program", "university_research_program"),
    ("research and development grant program", "research_development_grant_program"),
    ("research and development program", "research_development_program"),
    ("study carbon capture", "carbon_capture_research"),
    ("carbon capture", "carbon_capture_research"),
    ("implementation activities", "implementation_action_report"),
    ("implementation activity", "implementation_action_report"),
    ("carry out implementation", "implementation_action_report"),
    ("actions taken to implement", "implementation_action_report"),
    ("discussion of the actions", "implementation_action_report"),
    ("annual budget program", "budget_program_submission"),
    ("annually shall submit", "annual_report_duty"),
    ("prepare and submit", "submit_or_file"),
    ("preparation and submission", "submit_or_file"),
    ("submit to congress", "congressional_report_duty"),
    ("submit or file", "submit_or_file"),
    ("file or submit", "submit_or_file"),
    ("make publicly available a report", "public_report_duty"),
    ("shall make a report", "report_duty"),
    ("studies and reports", "study_report_duty"),
    ("shall submit the report", "report_duty"),
    ("shall submit a report", "report_duty"),
    ("study and report", "study_report_duty"),
    ("expenditures of department", "department_expenditure_authorization"),
    ("expenditures of the department", "department_expenditure_authorization"),
    ("expenditures upon business assigned by law", "department_expenditure_authorization"),
    ("business assigned by law to his department", "department_business_assignment"),
    ("business assigned by law to her department", "department_business_assignment"),
    ("business assigned by law to the department", "department_business_assignment"),
    ("requisitions for the advance or payment of money", "treasury_requisition_payment"),
    ("requisitions for advance or payment of money", "treasury_requisition_payment"),
    ("advance or payment of money", "treasury_requisition_payment"),
    ("out of the treasury", "treasury_payment_source"),
    ("estimates or accounts for expenditures", "expenditure_account_estimate"),
    ("buying power maintenance accounts", "buying_power_account_maintenance"),
    ("buying power maintenance", "buying_power_account_maintenance"),
    ("maintenance of accounts", "account_maintenance"),
    ("maintenance accounts", "account_maintenance"),
    ("custody of departmental records", "departmental_record_custody"),
    ("custody of department records", "departmental_record_custody"),
    ("custody of departmental property", "departmental_property_custody"),
    ("custody of department property", "departmental_property_custody"),
    ("custody of collections", "museum_collection_custody"),
    ("custody and control", "museum_collection_custody"),
    ("care and control", "museum_collection_custody"),
    ("national museum of the american indian", "national_museum_american_indian"),
    ("museum of the american indian", "national_museum_american_indian"),
    ("board of trustees", "museum_board_trustees"),
    ("board of regents", "museum_board_regents"),
    ("disposition of deceased veterans' personal property", "deceased_veterans_property_disposition"),
    ("disposition of deceased veterans personal property", "deceased_veterans_property_disposition"),
    ("deceased veterans' personal property", "deceased_veterans_property_disposition"),
    ("deceased veterans personal property", "deceased_veterans_property_disposition"),
    ("disposition of personal property", "personal_property_disposition"),
    ("personal property of deceased", "personal_property_disposition"),
    ("deliver the property", "property_delivery_duty"),
    ("delivery of property", "property_delivery_duty"),
    ("veterans' personal property", "veterans_personal_property"),
    ("veterans personal property", "veterans_personal_property"),
    ("hospital, nursing home, domiciliary, and medical care", "veterans_medical_care"),
    ("hospital nursing home domiciliary and medical care", "veterans_medical_care"),
    ("hospital care and medical services", "veterans_medical_care"),
    ("medical care and treatment for commonwealth army veterans", "veterans_medical_care"),
    ("commonwealth army veterans", "commonwealth_army_veteran_benefit"),
    ("specially adapted housing assistance", "special_adapted_housing_assistance"),
    ("specially adapted housing", "special_adapted_housing_assistance"),
    (
        "coordination of administration of benefits",
        "administrative_coordination_duty",
    ),
    ("coordination of administration", "administrative_coordination_duty"),
    ("coordination of administrat", "administrative_coordination_duty"),
    (
        "coordination of administration of specially adapted housing assistance",
        "special_adapted_housing_coordination",
    ),
    ("republic of the philippines", "philippines_veteran_assistance"),
    ("assist the republic of the philippines", "philippines_veteran_assistance"),
    ("common-funded budgets of nato", "nato_common_funded_budget"),
    ("common funded budgets of nato", "nato_common_funded_budget"),
    ("north atlantic treaty organization common-funded budgets", "nato_common_funded_budget"),
    ("north atlantic treaty organization common funded budgets", "nato_common_funded_budget"),
    ("united states contributions to the north atlantic treaty organization", "nato_contribution_authority"),
    ("nato common-funded budgets", "nato_common_funded_budget"),
    ("nato common funded budgets", "nato_common_funded_budget"),
    ("accountability and responsibility", "accountability_responsibility"),
    ("audits by comptroller general", "comptroller_general_audit"),
    ("audit by comptroller general", "comptroller_general_audit"),
    ("comptroller general", "comptroller_general_audit"),
    ("audit by government accountability office", "audit_requirement"),
    ("government accountability office", "audit_requirement"),
    ("termination of authority", "termination_authority"),
    ("termination of authorities", "termination_authority"),
    ("governing body", "governing_body"),
    ("board of directors", "board_of_directors"),
    ("promotion and retention of officers", "officer_promotion_retention"),
    ("promotion and retention", "promotion_retention"),
    ("promotion of officers", "officer_promotion"),
    ("retention of officers", "officer_retention"),
    (
        "assignment of naval officers to key management positions",
        "naval_officer_management_assignment",
    ),
    ("naval officers to key management positions", "naval_officer_management_assignment"),
    ("key management positions", "management_position_assignment"),
    ("reserve active-status list", "reserve_active_status_list"),
    ("reserve active status list", "reserve_active_status_list"),
    ("active-status list", "active_status_list"),
    ("active status list", "active_status_list"),
    ("national seashore recreational areas", "national_seashore_recreation_area"),
    ("national seashore", "national_seashore_recreation_area"),
    ("recreational areas", "recreation_area"),
    ("national historic site", "national_historic_site_designation"),
    ("historic site purposes", "national_historic_site_designation"),
    ("designated and set apart", "historic_site_preservation_designation"),
    ("set apart by proclamation", "historic_site_preservation_designation"),
    ("preservation as a national historic site", "historic_site_preservation_designation"),
    ("safe and adequate interstate air transportation", "air_transportation_service_duty"),
    ("safe and adequate air transportation", "air_transportation_service_duty"),
    ("air carrier shall provide", "air_carrier_service_duty"),
    ("interstate air transportation", "interstate_air_transportation"),
    ("enforcement by the board", "board_enforcement_authority"),
    ("board may bring a civil action", "board_civil_action_authority"),
    ("enjoin a rail carrier", "rail_carrier_injunction"),
    ("rail carrier from violating", "rail_carrier_violation_enforcement"),
    (
        "regulation prescribed or order or certificate issued",
        "transportation_order_certificate_enforcement",
    ),
    ("army national guard of the united states", "national_guard_unit_status"),
    ("air national guard of the united states", "national_guard_unit_status"),
    ("national guard of the united states", "national_guard_unit_status"),
    ("limitation on relocation of units", "national_guard_relocation_limit"),
    ("may not be relocated or withdrawn", "national_guard_relocation_limit"),
    ("relocated or withdrawn", "unit_relocation_withdrawal_restriction"),
    ("consent of the governor", "state_governor_consent_requirement"),
    ("performance accountability system", "workforce_performance_accountability"),
    ("state performance reports", "workforce_performance_reporting"),
    ("workforce development", "workforce_development_program"),
    ("independent living services and centers for independent living", "independent_living_services"),
    ("centers for independent living", "independent_living_center"),
    ("independent living services", "independent_living_services"),
    ("vocational rehabilitation", "vocational_rehabilitation_services"),
    ("rehabilitation services", "rehabilitation_services"),
    ("applicability of this chapter", "statutory_chapter_applicability"),
    ("applicability", "statutory_applicability"),
    ("short title", "statutory_short_title"),
    ("election of officers", "officer_election"),
    ("homestead entries", "homestead_entry_confirmation"),
    ("preemption and homestead entries", "homestead_entry_confirmation"),
    ("advisory committee", "advisory_committee"),
    ("appointment of an advisory committee", "advisory_committee_appointment"),
    ("authorized appointment", "appointment_authority"),
    ("state adjutants general", "state_adjutant_general_appointment"),
    ("state adjutant general", "state_adjutant_general_appointment"),
    ("special appointments", "special_appointment_authority"),
    ("railroad lands", "railroad_land_status"),
    ("railroad employees", "rail_employee_status"),
    ("railroad employee", "rail_employee_status"),
    ("railroad retirement", "rail_employee_trust_fund"),
    ("railroad unemployment insurance", "rail_employee_trust_fund"),
    ("railroad retirement account", "rail_employee_trust_fund"),
    ("withdrawal or after restoration to market", "land_withdrawal_restoration_scope"),
    ("restoration to market", "land_withdrawal_restoration_scope"),
    (
        "irrigation projects under reclamation act",
        "reclamation_act_irrigation_project",
    ),
    (
        "irrigation project under reclamation act",
        "reclamation_act_irrigation_project",
    ),
    ("irrigation projects", "irrigation_project"),
    ("irrigation project", "irrigation_project"),
    ("under reclamation act", "reclamation_act_authority"),
    ("reclamation act", "reclamation_act_authority"),
    ("irrigation, reclamation, and cultivation", "irrigation_reclamation_cultivation"),
    ("irrigation reclamation and cultivation", "irrigation_reclamation_cultivation"),
    ("reclamation, and cultivation", "irrigation_reclamation_cultivation"),
    ("international boundary and water commission", "international_boundary_water_commission"),
    ("international boundary and water commission, united states and mexico", "international_boundary_water_commission"),
    ("international storage dam", "international_storage_dam_authorization"),
    ("rio grande", "rio_grande_water_project"),
    ("joint construction, operation, and maintenance", "joint_infrastructure_operation"),
    ("joint construction", "joint_infrastructure_operation"),
    ("operation, and maintenance", "joint_infrastructure_operation"),
    ("local joint powers authorities", "local_joint_powers_authority"),
    ("joint powers authorities", "local_joint_powers_authority"),
    ("partnerships, grants, and cooperative agreements", "local_authority_partnership_grant"),
    ("partner, provide a grant to, or enter into a cooperative agreement", "local_authority_partnership_grant"),
    ("cooperative agreement with local joint powers authorities", "local_authority_cooperative_agreement"),
    ("provide a grant to", "grant_award_authority"),
    ("government of mexico", "mexico_bilateral_agreement"),
    ("united states and mexico", "mexico_bilateral_agreement"),
    ("conclude with the appropriate official", "international_agreement_authority"),
    ("agricultural commodity set-aside", "agricultural_commodity_set_aside"),
    ("agricultural commodity set aside", "agricultural_commodity_set_aside"),
    ("perishable agricultural commodities", "perishable_agricultural_commodity"),
    ("perishable agricultural commodity", "perishable_agricultural_commodity"),
    ("commodity set-aside", "commodity_set_aside"),
    ("commodity set aside", "commodity_set_aside"),
    ("determination of commodity value", "commodity_value_determination"),
    ("commodity value", "commodity_value_determination"),
    ("set-aside commodity", "commodity_set_aside"),
    ("set aside commodity", "commodity_set_aside"),
    ("interagency coordinating group", "interagency_coordination"),
    ("interagency coordination", "interagency_coordination"),
    ("international child abduction remedies", "child_abduction_remedy"),
    ("child abduction remedies", "child_abduction_remedy"),
    ("protection and conservation of wildlife", "wildlife_conservation_protection"),
    ("endangered species of fish and wildlife", "endangered_species_wildlife"),
    ("endangered species", "endangered_species_protection"),
    ("fish and wildlife", "fish_wildlife_conservation"),
    ("permanently nonirrigable lands", "permanent_nonirrigable_land_status"),
    ("permanently nonirrigable land", "permanent_nonirrigable_land_status"),
    ("permanently non-irrigable lands", "permanent_nonirrigable_land_status"),
    ("permanently non-irrigable land", "permanent_nonirrigable_land_status"),
    ("nonirrigable lands", "nonirrigable_land_status"),
    ("nonirrigable land", "nonirrigable_land_status"),
    ("non-irrigable lands", "nonirrigable_land_status"),
    ("non-irrigable land", "nonirrigable_land_status"),
    ("foreign commercial service", "foreign_commercial_service"),
    ("foreign relations exchange programs", "foreign_relations_exchange_program"),
    ("foreign relations exchange program", "foreign_relations_exchange_program"),
    ("foreign relations exchange", "foreign_relations_exchange_program"),
    ("exchange programs", "exchange_program"),
    ("exchange program", "exchange_program"),
    ("foreign service buildings", "foreign_service_building"),
    (
        "powers, duties and liabilities of consular officers",
        "consular_officer_powers_duties_liabilities",
    ),
    (
        "powers duties and liabilities of consular officers",
        "consular_officer_powers_duties_liabilities",
    ),
    ("duties and liabilities of consular officers", "consular_officer_duty_liability"),
    ("consular officers", "consular_officer"),
    ("consular officer", "consular_officer"),
    ("foreign service", "foreign_service"),
    ("transportation for illegal sexual activity", "illegal_sexual_activity_transport"),
    ("illegal sexual activity", "illegal_sexual_activity"),
    ("related crimes", "related_crime"),
    ("export promotion", "export_promotion"),
    ("export credit", "export_credit_authority"),
    ("credit authority", "credit_authority"),
    ("federal financing bank", "federal_financing_bank"),
    ("financing bank", "federal_financing_bank"),
    ("interstate traffic of viruses", "biological_product_interstate_traffic"),
    ("interstate traffic of virus", "biological_product_interstate_traffic"),
    ("sale of and interstate traffic", "biological_product_interstate_traffic"),
    ("viruses, serums, toxins, antitoxins", "biological_product_regulation"),
    ("viruses serums toxins antitoxins", "biological_product_regulation"),
    ("serums, toxins, antitoxins", "biological_product_regulation"),
    ("serums toxins antitoxins", "biological_product_regulation"),
    ("remain available until expended", "no_year_funding_availability"),
    ("available until expended", "no_year_funding_availability"),
    ("availability of appropriated amounts", "appropriated_amount_availability"),
    ("appropriated amounts", "appropriated_amount"),
    ("amounts appropriated", "appropriated_amount"),
    ("available to the secretary", "secretary_availability"),
    ("made available to the secretary", "secretary_availability"),
    ("made available", "resource_availability"),
    ("purchase paper in open market", "open_market_paper_purchase"),
    ("purchase of paper in open market", "open_market_paper_purchase"),
    ("paper in open market", "open_market_paper_purchase"),
    ("government publishing office to purchase paper", "government_publication_purchase_authority"),
    ("government publishing office may purchase paper", "government_publication_purchase_authority"),
    ("use of timber and stone by settlers", "settler_resource_use"),
    ("timber and stone by settlers", "settler_resource_use"),
    ("cutting of timber within forest", "timber_cutting_forest_scope"),
    ("cutting of timber", "timber_cutting"),
    ("reservation of timber", "forest_resource_reservation"),
    ("national forests", "national_forest_resource"),
    ("timber and stone", "timber_stone_use"),
    ("use of timber", "timber_stone_use"),
    ("use of stone", "timber_stone_use"),
    ("transfer of funds made available", "fund_transfer_authority"),
    ("transfer funds made available", "fund_transfer_authority"),
    ("transfer funds", "fund_transfer_authority"),
    ("transfer of certain housing", "housing_transfer_authority"),
    ("surplus housing", "surplus_housing_transfer"),
    ("classified by the secretary", "agency_certification_determination"),
    ("certification by the secretary", "agency_certification_determination"),
    ("certification by the secretary of the interior", "agency_certification_determination"),
    ("expenditures and cultivation requirements", "expenditure_requirement"),
    ("shall have expended", "expenditure_requirement"),
    ("land shall be patented", "land_patent_requirement"),
    ("necessary irrigation, reclamation", "irrigation_reclamation_cultivation"),
    ("mining claims", "mining_claim"),
    ("mining claim", "mining_claim"),
    ("mineral lands and mining", "mineral_land_status"),
    ("mineral leasing laws", "mineral_leasing_law"),
    ("mineral exploration and development", "mineral_development_technology"),
    ("mining laws of the united states", "mining_law_application"),
    ("mine safety and health", "mine_safety_health"),
    ("black lung benefits", "black_lung_benefits"),
    ("peacetime death compensation", "peacetime_death_compensation"),
    ("claims for benefits after", "black_lung_benefit_claim"),
    ("claims for benefits", "benefit_claim_adjudication"),
    ("located between", "date_range_temporal_scope"),
    ("findings and declaration", "congressional_findings_declaration"),
    ("congress finds and declares", "congressional_findings_declaration"),
    ("national and international monuments and memorials", "monument_memorial_administration"),
    ("national monuments and memorials", "monument_memorial_administration"),
    ("international monuments and memorials", "monument_memorial_administration"),
    ("national park", "national_park_resource"),
    ("national parks", "national_park_resource"),
    ("everglades national park", "everglades_national_park"),
    ("limitation of fees", "fee_limitation"),
    ("limitation on fees", "fee_limitation"),
    ("fees for admission", "admission_fee_collection"),
    ("judicial sales", "judicial_sale_execution"),
    ("executions and judicial sales", "judicial_sale_execution"),
    ("marshal's incapacity", "marshal_incapacity"),
    ("marshal incapacity", "marshal_incapacity"),
    ("military commissions", "military_commission_procedure"),
    ("military commission", "military_commission_procedure"),
    ("trial counsel", "military_trial_counsel_duty"),
    ("defense counsel", "military_defense_counsel_duty"),
    ("no land shall be patented", "patent_prohibition"),
    ("prohibitions on lie detector use", "lie_detector_use_prohibition"),
    ("prohibition on lie detector use", "lie_detector_use_prohibition"),
    ("lie detector use", "lie_detector_use_prohibition"),
    ("lie detector test", "lie_detector_test"),
    ("lie detector tests", "lie_detector_test"),
    ("polygraph test", "lie_detector_test"),
    ("polygraph tests", "lie_detector_test"),
    ("employee polygraph protection", "employee_polygraph_protection"),
    ("research program and plan", "research_program_plan"),
    ("formula grants to states", "state_formula_grant"),
    ("formula grants", "formula_grant"),
    (
        "state water pollution control revolving funds",
        "state_water_pollution_revolving_fund",
    ),
    (
        "water pollution control revolving fund",
        "water_pollution_control_revolving_fund",
    ),
    ("construction of treatment works", "treatment_works_construction_assistance"),
    ("implementation of management programs", "water_quality_management_program"),
    ("water pollution prevention and control", "water_pollution_control_program"),
    (
        "grants to states for reduction of excess hospital capacity",
        "excess_hospital_capacity_reduction",
    ),
    ("reduction of excess hospital capacity", "excess_hospital_capacity_reduction"),
    ("excess hospital capacity", "excess_hospital_capacity"),
    ("excesses in resources", "excess_resource_reduction"),
    ("reducing excesses in resources", "excess_resource_reduction"),
    ("shall make an allotment", "state_allotment_duty"),
    ("make an allotment", "state_allotment_duty"),
    ("allotment each fiscal year", "fiscal_year_allotment"),
    ("for each state in an amount", "state_allotment_amount"),
    ("center for substance abuse treatment", "substance_abuse_treatment_program"),
    ("substance abuse treatment", "substance_abuse_treatment_program"),
    ("grants for research", "research_grant"),
    ("grants for the conduct of research", "research_grant"),
    ("conduct of research", "research_activity"),
    ("public information program", "public_information_program"),
    ("information package for consumers", "consumer_information_package"),
    ("alternative fuels and alternative fueled vehicles", "alternative_fuel_vehicle_program"),
    ("alternative fueled vehicles", "alternative_fuel_vehicle_program"),
    ("alternative fuels in motor vehicles", "alternative_fuel_vehicle_program"),
    ("benefits and costs", "benefit_cost_information"),
    ("environmental performance", "environmental_performance_disclosure"),
    ("education sciences reform", "education_sciences_reform"),
    (
        "education research, statistics, evaluation, information, and dissemination",
        "education_research_statistics_dissemination",
    ),
    (
        "education research statistics evaluation information and dissemination",
        "education_research_statistics_dissemination",
    ),
    ("education research and statistics", "education_research_statistics"),
    (
        "research, statistics, evaluation, information, and dissemination",
        "education_research_statistics_dissemination",
    ),
    (
        "research statistics evaluation information and dissemination",
        "education_research_statistics_dissemination",
    ),
    ("education research", "education_research_program"),
    ("education statistics", "education_statistics_dissemination"),
    ("information and dissemination", "information_dissemination_program"),
    ("shall make allotments", "state_program_allotment_authority"),
    ("make allotments", "state_program_allotment_authority"),
    ("state allotments", "state_program_allotment_authority"),
    ("allotments to eligible states", "state_child_care_allotment"),
    ("allotments to enable the states", "state_child_care_allotment"),
    ("states to establish programs", "state_child_care_program"),
    ("programs to improve the health and safety of children", "child_care_health_safety_program"),
    ("health and safety of children receiving child care services", "child_care_health_safety_program"),
    ("children receiving child care services", "child_care_service_program"),
    ("child care services", "child_care_service_program"),
    ("coast guard child care", "coast_guard_child_care_program"),
    ("coast guard family support, child care, and housing", "family_support_child_care_housing"),
    ("family support, child care, and housing", "family_support_child_care_housing"),
    ("national oceanic and atmospheric administration", "noaa_administration"),
    ("national oceanic atmospheric administration", "noaa_administration"),
    ("use of funds", "fund_use_authority"),
    ("amounts provided under a grant or contract", "grant_contract_fund_use"),
    ("grant or contract awarded", "grant_contract_award"),
    ("training program development and support", "training_program_support"),
    ("faculty development", "faculty_development"),
    ("model demonstrations", "model_demonstration"),
    ("trainee support", "trainee_support"),
    ("individuals with disabilities", "disability_services"),
    ("freely associated states", "freely_associated_state"),
    ("freely associated state", "freely_associated_state"),
    ("republic of the marshall islands", "freely_associated_state"),
    ("federated states of micronesia", "freely_associated_state"),
    ("republic of palau", "freely_associated_state"),
    ("compact of free association", "compact_free_association"),
    ("free association", "compact_free_association"),
    ("funds for printing, binding", "printing_binding"),
    ("printing, binding", "printing_binding"),
    ("printing binding", "printing_binding"),
    ("article reprint purchases", "article_reprint_purchase"),
    ("reprint purchases", "article_reprint_purchase"),
    ("scientific and technical article", "technical_article"),
    ("exempt operations", "exempt_operation"),
    ("exempt operation", "exempt_operation"),
    ("shall not apply", "exemption"),
    ("provisions of this subchapter shall not apply", "exemption"),
    ("test platforms", "test_platform"),
    ("test platform", "test_platform"),
    ("ocean thermal energy conversion facility", "facility_operation"),
    ("ocean thermal energy conversion", "facility_operation"),
    ("plantship", "facility_operation"),
    ("editorially reclassified", "editorial_reclassification"),
    ("reclassified as section", "editorial_reclassification"),
    ("national security act of 1947", "national_security_act_reclassification"),
    ("crime control and law enforcement", "crime_control_law_enforcement"),
    ("law enforcement", "law_enforcement"),
    ("transferred editorial notes codification", "editorial_transfer_status"),
    ("transferred editorial notes", "editorial_transfer_status"),
    ("was editorially reclassified as section", "editorial_reclassification"),
    ("section was editorially reclassified", "editorial_reclassification"),
    ("plant variety protection office", "plant_variety_protection_office"),
    ("plant variety protection", "plant_variety_protection"),
    ("seal from the plant variety protection office", "office_seal"),
    ("seal of office", "office_seal"),
    ("official seal", "official_seal"),
    ("seal of department", "department_office_seal"),
    ("judicial notice shall be taken", "judicial_notice"),
    ("judicial notice", "judicial_notice"),
    ("capitol visitor center", "capitol_visitor_center"),
    (
        "office of the capitol visitor center",
        "uscode_capitol_visitor_center_administration",
    ),
    ("assistant to the chief executive officer", "visitor_center_assistant"),
    ("assistant to chief executive officer", "visitor_center_assistant"),
    ("chief executive officer", "chief_executive_officer"),
    ("absent uniformed services voter", "absent_uniformed_services_voter"),
    ("absent uniformed services voters", "absent_uniformed_services_voter"),
    ("uniformed services voter", "uniformed_services_voter"),
    ("uniformed services voters", "uniformed_services_voter"),
    ("overseas voters", "overseas_voter"),
    ("overseas voter", "overseas_voter"),
    ("management and disposition of vessels", "fishery_vessel_property_disposition"),
    ("disposition of vessels and other property", "fishery_vessel_property_disposition"),
    ("vessels and other property acquired", "fishery_vessel_property_disposition"),
    ("fishery loans", "fishery_loan_property"),
    ("arising out of fishery loans", "fishery_loan_property"),
    (
        "technical requirements of equipment on radiotelephone equipped ships",
        "radiotelephone_ship_equipment_requirement",
    ),
    ("radiotelephone equipped ships", "radiotelephone_ship_equipment"),
    ("radiotelephone station", "radiotelephone_station"),
    ("radiotelephone installation", "radiotelephone_installation"),
    ("radiotelegraph station", "radiotelegraph_station"),
    ("distress and safety of navigation", "navigation_safety_communication"),
    ("minimum normal range", "communication_range_requirement"),
    ("reserve source of electrical energy", "reserve_energy_requirement"),
    ("main source of electrical energy", "main_energy_requirement"),
    ("cargo ships", "cargo_ship"),
    ("recreational equipment", "recreational_equipment_tax"),
    ("sport fishing equipment", "recreational_equipment_tax"),
    ("wages due or accruing", "seaman_wage_tax_withholding"),
    ("withholding", "tax_withholding"),
    ("individual employed on a fishing vessel", "fishing_vessel_employment"),
    ("manufacturers excise taxes", "manufacturers_excise_tax"),
    ("miscellaneous excise taxes", "manufacturers_excise_tax"),
    ("excise tax", "excise_tax"),
    ("loan size limitation", "loan_size_limitation"),
    ("project loans", "project_loan_program"),
    ("project loan", "project_loan_program"),
    ("geothermal energy", "geothermal_energy_program"),
    ("loan made under this subchapter", "project_loan_limit"),
    ("loans made under this subchapter", "project_loan_limit"),
    ("loan guarantee", "loan_guarantee_authority"),
    ("border infrastructure and technology modernization", "border_infrastructure_modernization"),
    ("border infrastructure", "border_infrastructure_modernization"),
    ("technology modernization", "technology_modernization"),
    ("trust territory of pacific islands", "trust_territory_purchasing_authority"),
    ("make purchases through general services administration", "government_purchasing_authority"),
    ("general services administration", "government_purchasing_authority"),
    ("federal alcohol laws", "federal_alcohol_law_equal_treatment"),
    ("equal treatment under federal alcohol laws", "federal_alcohol_law_equal_treatment"),
    ("indian tribes under federal alcohol laws", "federal_alcohol_law_equal_treatment"),
    (
        "health professionals educational assistance program",
        "health_professional_education_assistance",
    ),
    ("health professional educational assistance", "health_professional_education_assistance"),
    ("health professionals educational assistance", "health_professional_education_assistance"),
    ("educational assistance program", "education_assistance_benefit"),
    ("educational assistance", "education_assistance_benefit"),
    ("scholarship program", "education_assistance_benefit"),
    ("repayment amount", "education_assistance_repayment"),
    ("repayment amounts", "education_assistance_repayment"),
    ("repayment of amounts", "education_assistance_repayment"),
    ("pay to the united states", "federal_repayment_obligation"),
    ("amounts paid under this subchapter", "education_assistance_repayment"),
    ("united states currency notes", "us_currency_note_obligation"),
    ("currency notes", "us_currency_note_obligation"),
    ("federal reserve banks", "federal_reserve_bank_note_distribution"),
    ("proof of citizenship", "mining_claim_citizenship_proof"),
    ("proofs of citizenship", "mining_claim_citizenship_proof"),
    ("land shall be patented", "land_patent_requirement"),
    ("mining claim shall be patented", "land_patent_requirement"),
    ("patents for designs", "design_patent_protection"),
    ("patent for a design", "design_patent_protection"),
    ("new original and ornamental design", "design_patent_protection"),
    ("ornamental design", "design_patent_protection"),
    ("limitation on assessments", "fund_assessment_limitation"),
    ("limitation on assessment", "fund_assessment_limitation"),
    ("assessments against migratory bird conservation fund", "migratory_bird_fund_assessment_limitation"),
    ("migratory bird conservation fund", "migratory_bird_conservation_fund"),
    ("gain or loss on disposition of property", "property_disposition_gain_loss"),
    ("gain or loss on disposition", "property_disposition_gain_loss"),
    ("disposition of property", "property_disposition"),
    ("basis of property", "property_basis_determination"),
    ("adjusted basis", "property_basis_determination"),
    ("nontaxation of deposits", "deposit_nontaxation"),
    ("nontaxation", "tax_exemption"),
    ("taxable income", "taxable_income_determination"),
    ("internal revenue code", "internal_revenue_code"),
    ("consolidated returns", "consolidated_return_rule"),
    ("related rules", "tax_related_rule"),
    ("graduated corporate rates", "graduated_corporate_rate_benefit"),
    ("accumulated earnings credit", "accumulated_earnings_credit"),
    ("deposits under", "deposit_tax_treatment"),
    ("moneys deposited by unknown parties", "unknown_party_deposit"),
    ("treasurer of the united states", "treasury_deposit"),
    ("costs and expenses", "cost_expense_charge"),
    ("charge on prize", "prize_proceeds_charge"),
    ("prize proceeds", "prize_proceeds_charge"),
    ("effect of act", "effect_of_act"),
    ("construction", "statutory_construction"),
    ("construction contracts", "construction_contract"),
    ("construction contract", "construction_contract"),
    ("architect of the capitol", "architect_capitol_administration"),
    ("architect of capitol", "architect_capitol_administration"),
    (
        "construction contracts from the u.s. government publishing office",
        "construction_contract",
    ),
    (
        "registry from the u.s. government publishing office",
        "uscode_registry_record",
    ),
    ("registry from the us government publishing office", "uscode_registry_record"),
    ("registry", "uscode_registry_record"),
    ("helen keller national center", "helen_keller_national_center_registry"),
    ("deaf-blind", "deaf_blind_services_registry"),
    ("deaf blind", "deaf_blind_services_registry"),
    ("public charter schools", "public_charter_school_program"),
    ("public charter school", "public_charter_school_program"),
    ("charter school program", "public_charter_school_program"),
    ("agreement with murray county", "agreement_military_park_authority"),
    ("national military park", "agreement_military_park_authority"),
    ("public corporation", "public_corporation_agreement_authority"),
    ("loan guaranty and insurance", "indian_loan_guaranty_power"),
    ("loan guaranty", "indian_loan_guaranty_power"),
    ("powers of secretary", "indian_loan_guaranty_power"),
    ("remedies as cumulative", "remedies_as_cumulative"),
    ("remedies provided under this part", "cumulative_remedy_preservation"),
    ("in addition to remedies", "cumulative_remedy_preservation"),
    ("remedies existing under another law", "cumulative_remedy_preservation"),
    ("shall not be construed", "construction_no_effect"),
    ("nothing in this", "construction_no_effect"),
    ("force and effect", "statutory_force_effect"),
    ("same force and effect", "statutory_force_effect"),
    ("relationship to other law", "legal_relationship_override"),
    ("relationship to middle class tax relief and job creation act", "legal_relationship_noninterference"),
    ("nothing in this chapter shall be construed", "legal_relationship_noninterference"),
    ("shall be construed to limit", "implementation_noninterference"),
    ("limit, restrict, or circumvent", "implementation_noninterference"),
    ("limit restrict or circumvent", "implementation_noninterference"),
    ("public safety broadband network", "public_safety_broadband_network"),
    ("nationwide public safety broadband network", "public_safety_broadband_network"),
    ("supplementary to those set forth in existing authorizations", "supplemental_authorization_policy"),
    ("supplemental to existing authorizations", "supplemental_authorization_policy"),
    ("supplementary to existing authorizations", "supplemental_authorization_policy"),
    ("existing authorizations", "supplemental_authorization_policy"),
    ("payment authorization", "payment_authorization"),
    ("policy disclosures", "policy_disclosure_requirement"),
    ("policy disclosure", "policy_disclosure_requirement"),
    ("national flood insurance program", "flood_insurance_program"),
    ("flood insurance program", "flood_insurance_program"),
    ("north american wetlands conservation", "wetlands_conservation_program"),
    ("wetlands conservation projects", "wetlands_conservation_project"),
    ("report to congress", "congressional_report_duty"),
    ("biennial assessment", "biennial_assessment_report"),
    ("annual assessment", "annual_assessment_report"),
    ("migratory birds", "migratory_bird_conservation"),
    ("waterfowl and other migratory birds", "migratory_bird_conservation"),
    ("western hemisphere", "western_hemisphere_conservation_agreement"),
    ("nutrition monitoring", "nutrition_monitoring_program"),
    ("food intakes of individuals", "food_intake_survey"),
    ("food consumption survey", "food_consumption_survey"),
    ("nutrient data base", "nutrient_database_maintenance"),
    ("nutritional and dietary status", "nutrition_status_assessment"),
    ("department of agriculture", "agriculture_department_program"),
    ("conditions, exclusion", "policy_condition_exclusion_disclosure"),
    ("conditions exclusion", "policy_condition_exclusion_disclosure"),
    ("conditions and exclusions", "policy_condition_exclusion_disclosure"),
    ("exclusions and limitations", "policy_condition_exclusion_disclosure"),
    ("securities and trust indentures", "securities_trust_indenture"),
    ("trust indentures", "securities_trust_indenture"),
    ("trust indenture", "securities_trust_indenture"),
    ("integration of procedure with securities and exchange commission", "securities_trust_indenture_procedure"),
    ("integration of procedure", "integrated_agency_procedure"),
    ("securities and exchange commission", "securities_exchange_commission"),
    ("establishment of the rio grande natural area", "natural_area_establishment"),
    ("rio grande natural area", "natural_area_establishment"),
    ("natural area", "conservation_area_management"),
    ("management plan", "conservation_area_management"),
    ("national seashore recreational areas", "national_seashore_recreation_area"),
    ("national seashore recreation areas", "national_seashore_recreation_area"),
    ("national seashore", "national_seashore_recreation_area"),
    ("donation of lands", "land_donation_acceptance"),
    ("donation of land", "land_donation_acceptance"),
    ("accept donations", "land_donation_acceptance"),
    ("accept donation", "land_donation_acceptance"),
    ("acquisition of lands", "land_acquisition_authority"),
    ("acquire lands", "land_acquisition_authority"),
    ("acquire land", "land_acquisition_authority"),
    ("title to lands", "land_title_authority"),
    ("title to land", "land_title_authority"),
    ("title to the lands", "land_title_authority"),
    ("title to the land", "land_title_authority"),
    ("land title", "land_title_authority"),
    ("exceptions from operation", "statutory_operation_exception"),
    ("excepted from the operation", "statutory_operation_exception"),
    ("tracts or parcels of land", "land_parcel_exception"),
    ("parcels of land", "land_parcel_exception"),
    ("accretions thereto", "land_accretion_resource"),
    ("resources therein", "land_accretion_resource"),
    ("improvements thereon", "land_improvement_exception"),
    ("transferred from the u.s. government publishing office", "editorial_transfer_status"),
    ("transferred from the us government publishing office", "editorial_transfer_status"),
    ("availability of appropriated amounts", "appropriated_amount_availability"),
    ("appropriated amounts for fiscal year", "fiscal_year_appropriation_availability"),
    ("following enactment of title", "codification_transition"),
    ("salvage archeological purposes", "salvage_archeology_administration"),
    ("salvage archaeological purposes", "salvage_archeology_administration"),
    ("make cooperative agreements", "cooperative_agreement_authority"),
    ("services of experts and consultants", "expert_consultant_service_authority"),
    ("funds made available for salvage", "salvage_fund_use_authority"),
    ("trade and rule of law", "trade_rule_of_law_compliance"),
    ("rule of law issues", "trade_rule_of_law_compliance"),
    ("united states-china relations", "china_relations_oversight"),
    ("united states china relations", "china_relations_oversight"),
    ("fees for internal services", "internal_service_fee"),
    ("fees for internal delivery", "internal_delivery_fee_collection"),
    (
        "internal delivery in house of representatives",
        "internal_delivery_fee_collection",
    ),
    ("internal delivery of nonpostage mail", "internal_delivery_fee_collection"),
    ("full and true account", "wage_account_discharge"),
    ("paying off or discharging", "seaman_discharge"),
    ("discharging the seaman", "seaman_discharge"),
    ("hospitalization of certain former members", "former_member_hospitalization"),
    ("hospitalization of former members", "former_member_hospitalization"),
    ("hospital relief for seamen", "seamen_hospital_relief"),
    ("used rechargeable batteries", "rechargeable_battery_regulation"),
    ("rechargeable batteries", "rechargeable_battery_regulation"),
    ("collection, storage, or transportation", "collection_storage_transport_regulation"),
    ("collection storage or transportation", "collection_storage_transport_regulation"),
    ("smart manufacturing", "smart_manufacturing_report"),
    ("progress made in advancing smart manufacturing", "smart_manufacturing_report"),
    ("expand the naval facilities", "naval_facility_expansion"),
    ("naval facilities", "naval_facility_expansion"),
    ("medal of honor", "medal_of_honor_award"),
    ("award to individual", "individual_military_award"),
    ("award to individual", "military_award_review"),
    ("award of the medal of honor", "medal_of_honor_award"),
    ("review the proposal", "award_proposal_review"),
    ("proposal for the award", "award_proposal_review"),
    ("local asthma surveillance", "public_health_surveillance"),
    ("asthma surveillance", "public_health_surveillance"),
    ("collect data on the prevalence", "public_health_surveillance"),
    ("magnet schools assistance", "education_assistance_program"),
    ("maximum utilization of the international space station", "iss_research_utilization"),
    ("international space station", "international_space_station"),
    ("maximize the productivity and use of the iss", "iss_research_utilization"),
    ("productivity and use of the iss", "iss_research_utilization"),
    ("scientific and technological research", "space_science_research"),
    ("income gap multiplier", "income_gap_multiplier"),
    ("federal payments", "federal_payment_formula"),
    ("general assistance administration", "federal_assistance_administration"),
    (
        "minority science and engineering improvement",
        "science_engineering_education_program",
    ),
    ("bail on appeal or certiorari", "appeal_bail_rule"),
    ("proposals; submission; payment for cost of examination", "proposal_examination_payment"),
    ("submission; payment for cost of examination", "proposal_examination_payment"),
    ("payment for cost of examination", "proposal_examination_payment"),
    ("cost of examination", "examination_cost_payment"),
    ("submit a proposal", "proposal_submission"),
    ("submission of proposal", "proposal_submission"),
    ("proposal therefor to the secretary", "proposal_submission"),
    ("in such form and manner as he shall prescribe", "proposal_prescription_duty"),
    ("in such form and manner as the secretary shall prescribe", "proposal_prescription_duty"),
    ("armed forces retirement home", "armed_forces_retirement_home"),
    ("payments to retirement home", "retirement_home_payment"),
    ("payment to retirement home", "retirement_home_payment"),
    ("use of facilities", "public_facility_use"),
    ("use the research, equipment, and facilities", "public_facility_use"),
    ("use the research equipment and facilities", "public_facility_use"),
    ("facilities of united states and foreign governments", "government_facility_use"),
    ("facilities of united states government", "government_facility_use"),
    ("facilities of foreign governments", "foreign_government_facility_use"),
    ("centers for disease control and prevention", "public_health_agency"),
    ("center for disease control and prevention", "public_health_agency"),
    ("office of women's health", "office_of_womens_health"),
    ("office of womens health", "office_of_womens_health"),
    ("there is established", "office_establishment"),
    ("is established within", "office_establishment"),
    ("office to be known as", "office_establishment"),
    (
        "assistance to the republic of the philippines",
        "philippines_medical_assistance_authority",
    ),
    (
        "assist the republic of the philippines",
        "philippines_medical_assistance_authority",
    ),
    ("providing medical care and treatment", "veterans_medical_care"),
    ("commonwealth army veterans", "veterans_medical_care"),
    ("new philippine scouts", "veterans_medical_care"),
    ("admission and other fees", "admission_fee_collection"),
    ("fees for admission", "admission_fee_collection"),
    ("collect fees", "fee_collection_authority"),
    (
        "higher education resources and student assistance",
        "higher_education_student_assistance",
    ),
    ("international education programs", "international_education_program"),
    ("international education program", "international_education_program"),
    (
        "activities in support of sustainable chemistry",
        "sustainable_chemistry_activity_support",
    ),
    ("carry out activities in support", "program_activity_implementation"),
    ("carry out activities", "program_activity_implementation"),
    ("advanced automotive technologies", "advanced_automotive_technology_conference"),
    ("advanced automotive technology", "advanced_automotive_technology_conference"),
    ("conference on advanced automotive", "public_technology_conference"),
    ("technology innovation", "technology_innovation_program"),
    ("customs administration", "customs_administration"),
    ("customs duties", "customs_duty_administration"),
    ("enforcement provisions", "customs_enforcement_provision"),
    ("tariff and related provisions", "tariff_administration"),
    ("internal revenue laws", "internal_revenue_administration"),
    ("application of internal revenue laws", "internal_revenue_administration"),
    ("procedure and administration", "tax_procedure_administration"),
    ("general rules", "tax_general_rule_administration"),
    ("false, fictitious or fraudulent claims", "false_fraudulent_claim"),
    ("false fictitious or fraudulent claims", "false_fraudulent_claim"),
    ("false, fictitious, or fraudulent", "false_fraudulent_claim"),
    ("knowing such claim to be false", "false_claim_knowledge"),
    ("claim upon or against the united states", "government_claim"),
    ("clean hulls", "clean_hull_administration_enforcement"),
    ("administer and enforce the convention", "clean_hull_administration_enforcement"),
    ("prescribe and enforce regulations", "regulatory_compliance_duty"),
    ("common-funded budgets of nato", "nato_common_funded_budget_contribution"),
    ("common funded budgets of nato", "nato_common_funded_budget_contribution"),
    (
        "north atlantic treaty organization common-funded budgets",
        "nato_common_funded_budget_contribution",
    ),
    (
        "north atlantic treaty organization common funded budgets",
        "nato_common_funded_budget_contribution",
    ),
    ("fiscal year 1998 baseline limitation", "fiscal_year_budget_limitation"),
    ("baseline limitation", "fiscal_year_budget_limitation"),
    ("trading without required certificate of documentation", "undocumented_trading_penalty"),
    ("production of certificate on entry", "certificate_production_on_entry"),
    ("produce the certificate of documentation", "certificate_production_on_entry"),
    ("without required certificate of documentation", "documentation_certificate_requirement"),
    ("required certificate of documentation", "documentation_certificate_requirement"),
    ("certificate of documentation", "documentation_certificate_requirement"),
    ("customs officer", "customs_entry_documentation"),
    ("on entry of a vessel", "vessel_entry_documentation"),
    ("notification of an active measures campaign", "active_measures_notification"),
    ("active measures campaign", "active_measures_campaign"),
    ("congressional intelligence committees", "congressional_intelligence_committee"),
    ("financial disclosure", "financial_disclosure_requirement"),
    ("financial disclosure reports", "financial_disclosure_requirement"),
    ("ethics in government", "ethics_government_requirement"),
    ("ethics requirements", "ethics_government_requirement"),
    ("predictive modeling and other analytics technologies", "predictive_analytics_disclosure"),
    ("predictive modeling technologies", "predictive_analytics_disclosure"),
    ("predictive modeling", "predictive_analytics"),
    ("waste, fraud, and abuse", "waste_fraud_abuse_prevention"),
    ("waste fraud and abuse", "waste_fraud_abuse_prevention"),
    ("identify and prevent waste", "waste_fraud_abuse_prevention"),
    ("buying livestock in commerce", "livestock_commerce"),
    ("conveyance to states", "state_conveyance_authority"),
    ("conveyance to a state", "state_conveyance_authority"),
    ("conveyance of roads", "road_conveyance"),
    ("convey roads", "road_conveyance"),
    ("roads leading to certain historical areas", "historic_area_access_road"),
    ("roads leading to historical areas", "historic_area_access_road"),
    ("historical areas", "historic_area"),
    ("participating jurisdictions", "participating_jurisdiction"),
    ("priority state", "priority_state"),
    ("priority states", "priority_state"),
    ("state energy program", "state_energy_program"),
    ("federal compliance", "federal_compliance_requirement"),
    ("federal building energy standards", "federal_building_energy_standard"),
    ("federal building energy standard", "federal_building_energy_standard"),
    ("new federal buildings", "federal_building_compliance"),
    ("new federal building", "federal_building_compliance"),
    ("adopt procedures necessary to assure", "procedure_adoption_duty"),
    ("adopt procedures", "procedure_adoption_duty"),
    ("juvenile justice", "juvenile_justice_program"),
    ("delinquency prevention", "juvenile_delinquency_prevention"),
    ("juvenile justice systems", "juvenile_justice_system_improvement"),
    ("justice system improvement", "justice_system_improvement"),
    ("renewable energy projects", "renewable_energy_project"),
    ("renewable energy project", "renewable_energy_project"),
    ("tax and rate treatment", "renewable_energy_tax_rate_treatment"),
    ("taxation and ratemaking procedures", "renewable_energy_tax_rate_treatment"),
    ("ratemaking procedures", "utility_ratemaking_procedure"),
    ("economic barriers to renewable energy", "renewable_energy_barrier_study"),
    ("barriers to renewable energy projects", "renewable_energy_barrier_study"),
    ("eligible for funding", "funding_eligibility"),
    ("eligible for funds", "funding_eligibility"),
    ("eligibility for services", "service_eligibility"),
    ("determination of eligibility", "eligibility_determination"),
    ("determine eligibility", "eligibility_determination"),
    (
        "health insurance reform implementation fund",
        "health_insurance_reform_implementation_fund",
    ),
    (
        "health insurance reform implementation",
        "health_insurance_reform_implementation",
    ),
    ("implementation funding", "implementation_funding"),
    ("implementation fund", "implementation_fund"),
    ("implementation fund within the department", "department_fund_administration"),
    (
        "established a health insurance reform implementation fund",
        "fund_establishment_authority",
    ),
    (
        "patient protection and affordable care act",
        "patient_protection_affordable_care_act",
    ),
    ("affordable care act", "patient_protection_affordable_care_act"),
    ("professional assessment committee", "professional_assessment_committee"),
    ("congregate services program", "congregate_services_program"),
    ("congregate services", "congregate_services_program"),
    ("eligible to participate", "participation_eligibility"),
    ("eligible state", "funding_eligibility"),
    ("eligible states", "funding_eligibility"),
    ("grievances concerning former", "former_employee_grievance"),
    ("former members of the service", "former_employee_grievance"),
    ("former employees of the department", "former_employee_grievance"),
    ("foreign service grievance", "foreign_service_grievance"),
    ("foreign service", "foreign_service"),
    ("severability", "statutory_severability"),
    ("per-capita combined", "per_capita_ranking"),
    ("per capita combined", "per_capita_ranking"),
    ("highest annual per-capita", "per_capita_ranking"),
    ("highest annual per capita", "per_capita_ranking"),
    ("states with the highest", "state_ranking"),
    ("15 states with the highest", "state_ranking"),
    ("decent, safe, sanitary, and affordable housing", "affordable_housing_supply"),
    ("decent safe sanitary and affordable housing", "affordable_housing_supply"),
    ("safe, sanitary, and affordable housing", "affordable_housing_supply"),
    ("safe sanitary and affordable housing", "affordable_housing_supply"),
    ("affordable housing", "affordable_housing_supply"),
    ("long-term supply", "long_term_housing_supply"),
    ("long term supply", "long_term_housing_supply"),
    ("funds available to participating jurisdictions", "housing_investment_authority"),
    (
        "investment to increase the number of families served",
        "housing_family_service_investment",
    ),
    ("families served with decent", "housing_family_service_investment"),
    ("partnership adjustment", "partnership_adjustment"),
    ("adjustment to partnership", "partnership_adjustment"),
    ("partnership-related item", "partnership_item"),
    ("partnership related item", "partnership_item"),
    ("partnership proceeding", "partnership_proceeding"),
    ("partnership proceedings", "partnership_proceeding"),
    ("notice of proceeding", "partnership_notice_proceeding"),
    ("notice of proceedings", "partnership_notice_proceeding"),
    ("notice of final partnership adjustment", "partnership_adjustment_notice"),
    ("partnership adjustment notice", "partnership_adjustment_notice"),
    ("partnership", "partnership"),
    ("sea grant colleges", "sea_grant_college"),
    ("sea grant college", "sea_grant_college"),
    ("marine science development", "marine_science_development"),
    ("national sea grant college program", "sea_grant_college_program"),
    ("sea grant program", "sea_grant_college_program"),
    ("technology transfer and transitions assessment", "technology_transfer_assessment"),
    ("technology transfer", "technology_transfer"),
    ("transitions assessment", "technology_transition_assessment"),
    ("appropriate committees of congress", "congressional_committee_report"),
    ("appropriate committees", "congressional_committee_report"),
    ("territorial jurisdiction", "territorial_jurisdiction"),
    ("hydraulic mining", "hydraulic_mining"),
    ("california debris commission", "california_debris_commission"),
    ("clearing banks", "clearing_bank_resolution"),
    ("clearing bank", "clearing_bank_resolution"),
    ("resolution of clearing banks", "clearing_bank_resolution"),
    ("federal reserve board", "federal_reserve_board_oversight"),
    ("false statement or representation", "false_statement_penalty"),
    ("false statements", "false_statement_penalty"),
    ("criminal penalty for false statements", "false_statement_penalty"),
    ("civil penalty", "civil_penalty_liability"),
    ("liable for a civil penalty", "civil_penalty_liability"),
    ("liable to the united states government for a civil penalty", "civil_penalty_liability"),
    ("violating this chapter", "statutory_violation_condition"),
    ("violation of this chapter", "statutory_violation_condition"),
    ("in violation of this chapter", "statutory_violation_condition"),
    ("knowingly and willfully", "scienter_requirement"),
    ("material fact", "material_fact_representation"),
    ("destruction of letter boxes or mail", "postal_mailbox_destruction"),
    ("letter boxes or mail", "postal_mailbox"),
    ("mail receptacles", "postal_mailbox"),
    ("postal service", "postal_service"),
    ("treatment of certain credit", "cost_sharing_credit_treatment"),
    ("cost sharing", "cost_sharing"),
    ("non-federal share", "non_federal_cost_share"),
    ("non federal share", "non_federal_cost_share"),
    ("non-federal cost sharing", "non_federal_cost_share"),
    ("non federal cost sharing", "non_federal_cost_share"),
    ("amendments", "statutory_amendment"),
    ("amendment", "statutory_amendment"),
    ("national insurance development program", "insurance_development_program"),
    ("federal insurance against burglary", "federal_burglary_insurance"),
    ("burglary and theft insurance", "burglary_theft_insurance"),
    ("crime insurance", "crime_insurance"),
    (
        "national and international monuments and memorials",
        "monument_memorial_administration",
    ),
    ("national monuments and memorials", "monument_memorial_administration"),
    ("international monuments and memorials", "monument_memorial_administration"),
    (
        "patriotic and national observances, ceremonies, and organizations",
        "patriotic_national_observance_organization",
    ),
    (
        "patriotic and national observances ceremonies and organizations",
        "patriotic_national_observance_organization",
    ),
    ("patriotic and national observances", "patriotic_national_observance"),
    ("national observances", "patriotic_national_observance"),
    ("ceremonies and organizations", "civic_ceremony_organization"),
    ("national ceremonies", "civic_ceremony_organization"),
    ("national organizations", "civic_national_organization"),
    ("patriotic organizations", "civic_national_organization"),
    ("national governing bodies", "amateur_sports_governing_body"),
    ("national governing body", "amateur_sports_governing_body"),
    ("amateur sports organization", "amateur_sports_organization"),
    ("amateur sports organizations", "amateur_sports_organization"),
    ("olympic and paralympic committee", "olympic_paralympic_committee"),
    ("united states olympic and paralympic committee", "olympic_paralympic_committee"),
    ("national park service", "national_park_service_administration"),
    ("energy emergency preparedness", "energy_emergency_preparedness"),
    (
        "energy supply and environmental coordination",
        "energy_supply_environmental_coordination",
    ),
    ("indian energy resource development", "indian_energy_resource_development"),
    ("tribal energy resource agreement", "tribal_energy_resource_agreement"),
    ("measurement", "measurement_determination"),
    ("measurement of vessels", "vessel_measurement"),
    ("vessel measurement", "vessel_measurement"),
    ("assign a length", "agency_measurement_assignment"),
    ("assign the length", "agency_measurement_assignment"),
    ("secretary shall assign", "agency_measurement_assignment"),
    ("length means the horizontal distance", "hull_length_definition"),
    ("horizontal distance of the hull", "hull_length_definition"),
    ("foremost part of the stem", "maritime_hull_measurement"),
    ("aftermost part of the stern", "maritime_hull_measurement"),
    ("oaths in investigations", "investigation_oath_authority"),
    ("oath in investigations", "investigation_oath_authority"),
    ("administer oaths", "investigation_oath_authority"),
    ("administer an oath", "investigation_oath_authority"),
    ("take testimony", "investigation_testimony_authority"),
    ("assignment and transportation of students", "student_assignment_transportation"),
    ("assignment and transportation of student", "student_assignment_transportation"),
    ("transportation of students", "student_transportation_assignment"),
    ("transportation of student", "student_transportation_assignment"),
    ("assignment of students", "student_assignment_transportation"),
    ("assignment of student", "student_assignment_transportation"),
    ("crisis counseling assistance and training", "crisis_counseling_assistance"),
    ("crisis counseling assistance", "crisis_counseling_assistance"),
    ("crisis counseling training", "crisis_counseling_training"),
    ("professional counseling services", "crisis_counseling_assistance"),
    ("mental health organizations", "disaster_mental_health_service"),
    ("private mental health organizations", "disaster_mental_health_service"),
    ("ready reserve: muster duty", "ready_reserve_muster_duty"),
    ("ready reserve muster duty", "ready_reserve_muster_duty"),
    ("muster duty", "reserve_muster_authority"),
    ("ready reserve", "reserve_muster_authority"),
    (
        "racial discrimination by colleges",
        "college_racial_discrimination_prohibition",
    ),
    ("racial discrimination", "college_racial_discrimination_prohibition"),
    (
        "agricultural and mechanical colleges",
        "agricultural_college_aid_appropriation",
    ),
    ("college-aid annual appropriation", "agricultural_college_aid_appropriation"),
    ("college aid annual appropriation", "agricultural_college_aid_appropriation"),
    ("drug-free communities support program", "drug_free_communities_support_program"),
    ("drug free communities support program", "drug_free_communities_support_program"),
    ("drug-free communities", "drug_free_communities_support_program"),
    ("drug free communities", "drug_free_communities_support_program"),
    ("cuyahoga valley national park", "cuyahoga_valley_national_park_status"),
    (
        "editorially reclassified as section 20504 of title 52",
        "uscode_voting_elections_reclassification",
    ),
    ("title 52, voting and elections", "uscode_voting_elections_reclassification"),
)
_PROGRAM_RECONSTRUCTION_ATOMS = frozenset(
    {
        "advanced_automotive_technology_conference",
        "crime_insurance",
        "energy_emergency_preparedness",
        "energy_supply_environmental_coordination",
        "federal_burglary_insurance",
        "higher_education_student_assistance",
        "health_insurance_reform_implementation",
        "health_insurance_reform_implementation_fund",
        "indian_energy_resource_development",
        "implementation_fund",
        "implementation_funding",
        "insurance_development_program",
        "international_education_program",
        "investment_guarantee_agency",
        "investment_guarantee_authority",
        "monument_memorial_administration",
        "amateur_sports_governing_body",
        "amateur_sports_organization",
        "civic_ceremony_organization",
        "civic_national_organization",
        "multilateral_investment_guarantee",
        "multilateral_investment_guarantee_agency",
        "national_park_service_administration",
        "olympic_paralympic_committee",
        "patriotic_national_observance",
        "patriotic_national_observance_organization",
        "program_activity_implementation",
        "public_technology_conference",
        "statutory_implementation_authority",
        "sustainable_chemistry_activity_support",
        "technology_innovation_program",
        "tribal_energy_resource_agreement",
        "salvage_archeology_administration",
    }
)
_ADMIN_ENFORCEMENT_RECONSTRUCTION_ATOMS = frozenset(
    {
        "cargo_carriage",
        "common_carrier",
        "common_carrier_cargo_carriage",
        "customs_administration",
        "customs_duty_administration",
        "customs_enforcement_provision",
        "internal_revenue_administration",
        "service_contract",
        "service_contract_suspension",
        "suspended_tariff_operation",
        "suspended_tariff_service_contract",
        "suspended_tariff_service_contract_penalty",
        "tariff_administration",
        "tariff_suspension",
        "tax_general_rule_administration",
        "tax_procedure_administration",
    }
)
_TEMPORAL_STATUTORY_RECONSTRUCTION_ATOMS = frozenset(
    {
        "annual_report_duty",
        "congressional_report_duty",
        "deadline_report_duty",
        "effective_date_transition",
        "inventory_study_report",
        "report_contents",
        "report_duty",
        "study_report_duty",
        "uranium_inventory_study",
    }
)
_RESEARCH_ADMINISTRATION_RECONSTRUCTION_ATOMS = frozenset(
    {
        "education_research_program",
        "education_research_statistics",
        "education_research_statistics_dissemination",
        "education_sciences_reform",
        "education_statistics_dissemination",
        "information_dissemination_program",
        "noaa_administration",
    }
)
_PROJECT_LOAN_AWARD_RECONSTRUCTION_ATOMS = frozenset(
    {
        "award_proposal_review",
        "geothermal_energy_program",
        "individual_military_award",
        "loan_guarantee_authority",
        "loan_size_limitation",
        "medal_of_honor_award",
        "military_award_review",
        "project_loan_limit",
        "project_loan_program",
    }
)
_CATALOG_CONTRACT_RECONSTRUCTION_ATOMS = frozenset(
    {
        "architect_capitol_administration",
        "construction_contract",
        "deaf_blind_services_registry",
        "helen_keller_national_center_registry",
        "uscode_registry_record",
    }
)
_MEASUREMENT_ASSIGNMENT_RECONSTRUCTION_ATOMS = frozenset(
    {
        "agency_measurement_assignment",
        "hull_length_definition",
        "maritime_hull_measurement",
        "measurement_determination",
        "vessel_measurement",
    }
)
_WILDLIFE_STATUS_RECONSTRUCTION_ATOMS = frozenset(
    {
        "endangered_species_protection",
        "endangered_species_wildlife",
        "fish_wildlife_conservation",
        "wildlife_conservation_protection",
    }
)
_PACKET_000819_SEMANTIC_RECONSTRUCTION_ATOMS = frozenset(
    {
        "accumulated_earnings_credit",
        "agriculture_department_program",
        "annual_assessment_report",
        "biennial_assessment_report",
        "cargo_ship",
        "communication_range_requirement",
        "congressional_report_duty",
        "consolidated_return_rule",
        "food_consumption_survey",
        "food_intake_survey",
        "graduated_corporate_rate_benefit",
        "main_energy_requirement",
        "migratory_bird_conservation",
        "navigation_safety_communication",
        "nutrient_database_maintenance",
        "nutrition_monitoring_program",
        "nutrition_status_assessment",
        "radiotelegraph_station",
        "radiotelephone_installation",
        "radiotelephone_ship_equipment",
        "radiotelephone_ship_equipment_requirement",
        "radiotelephone_station",
        "reserve_energy_requirement",
        "tax_related_rule",
        "western_hemisphere_conservation_agreement",
        "wetlands_conservation_program",
        "wetlands_conservation_project",
    }
)
_USCODE_STATUS_DERIVATION_RULES = frozenset(
    {
        "uscode_transferred_heading_v1",
        "uscode_codification_transfer_heading_v1",
        "uscode_editorial_status_heading_v1",
    }
)
_USCODE_SECTION_HEADING_TAIL_RULES = frozenset(
    {
        "uscode_section_heading_v1",
        "uscode_section_heading_coarse_v1",
    }
)
_USC_CITATION_RE = re.compile(
    r"^\s*(?P<title>\d+[A-Za-z]*)\s+U\.?\s*S\.?\s*C\.?\s*\.?\s*"
    r"(?:§{1,2}\s*|sec\.?\s*|section\s+)?"
    r"(?P<section>[0-9A-Za-z.\-]+(?:\s+(?:to|through|thru)\s+[0-9A-Za-z.\-]+)?)\s*$",
    re.IGNORECASE,
)
_USCODE_SOURCE_ID_RE = re.compile(
    r"^\s*(?P<scheme>us-code)-(?P<title>[^-]+)-(?P<section>.+)-(?P<digest>[0-9a-f]{16})\s*$",
    re.IGNORECASE,
)
_DEFINED_TERM_RE = re.compile(
    r"\bthe\s+term\s+['\"]?(?P<term>[A-Z][A-Za-z0-9]*(?:[-\s]+[A-Z][A-Za-z0-9]*){0,5})['\"]?"
    r"\s+(?:(?:has|shall\s+have)\s+the\s+meaning|means|includes?)\b",
    re.IGNORECASE,
)
_DEFINED_AS_USED_TERM_RE = re.compile(
    r"\b(?:the\s+term\s+|a\s+|an\s+)?['\"]?"
    r"(?P<term>[A-Za-z][A-Za-z0-9]*(?:[-\s]+[A-Za-z][A-Za-z0-9]*){0,5})['\"]?"
    r"\s+as\s+used\s+in\s+(?:this|the)\b",
    re.IGNORECASE,
)
_DEFINITION_HEADING_RE = re.compile(
    r"(?<!\w)['\"]?(?P<term>[A-Z][A-Za-z0-9]*(?:[-\s]+[A-Z][A-Za-z0-9]*){0,5})['\"]?"
    r"\s+defined\b",
    re.IGNORECASE,
)
_TRAILING_SECTION_PUNCT_RE = re.compile(r"[.;:]+$")
_CITATION_SECTION_COMPONENT_SPLIT_RE = re.compile(r"[.\-]+")
_CITATION_SECTION_DELIMITER_RE = re.compile(r"[.\-]+")
_USCODE_SECTION_TOKEN_PATTERN = r"\d[0-9A-Za-z.\-]*(?:\([^)]+\))*"
_USCODE_SECTION_LIST_PATTERN = (
    rf"{_USCODE_SECTION_TOKEN_PATTERN}"
    rf"(?:\s*(?:,|and|or|to|through|thru)\s*{_USCODE_SECTION_TOKEN_PATTERN})*"
)
_CITATION_SECTION_RANGE_RE = re.compile(
    r"^\s*(?P<start>[0-9A-Za-z.\-]+)\s+"
    r"(?P<connector>to|through|thru)\s+"
    r"(?P<end>[0-9A-Za-z.\-]+)\s*$",
    re.IGNORECASE,
)
_CITATION_SECTION_PART_RE = re.compile(
    r"^(?P<number>\d+)(?P<suffix>[A-Za-z]+)?$"
)
_USCODE_LEADING_SECTION_REF_RE = re.compile(
    rf"^\s*(?:(?:§{{1,2}}\s*|secs?\.?\s*|sections?\s+){_USCODE_SECTION_LIST_PATTERN}|{_USCODE_SECTION_TOKEN_PATTERN})\s*(?:[.:\-–—]+)?\s*",
    re.IGNORECASE,
)
_USCODE_CATCHLINE_BODY_START_RE = re.compile(
    r"\s+(?=(?:\([a-z0-9]+\)\s+|For\s+purposes\s+of\b|On\s+and\s+after\b|"
    r"No\s+\w+\b|The\s+\w+\b|A\s+\w+\b|An\s+\w+\b))",
    re.IGNORECASE,
)
_USCODE_STATUS_LEADING_SECTION_LABEL_RE = re.compile(
    r"^\s*(?:(?:this|such)\s+)?(?:sections?|secs?\.?)\b\s*[,.:;\-–—]*\s*",
    re.IGNORECASE,
)
_USCODE_STATUS_LEADING_SECTION_NUMBERS_RE = re.compile(
    rf"^\s*[,.:;\-–—]*\s*(?:{_USCODE_SECTION_LIST_PATTERN})\s*[,.:;\-–—]*\s*",
    re.IGNORECASE,
)
_USCODE_INLINE_SECTION_REF_RE = re.compile(
    rf"(?<!\w)(?:§{{1,2}}\s*|secs?\.?\s*|sections?\s+){_USCODE_SECTION_LIST_PATTERN}",
    re.IGNORECASE,
)
_USCODE_GPO_ATTRIBUTION_RE = re.compile(
    r"\bfrom\s+the\s+u\.?\s*s\.?\s+government\s+publishing\s+office\b.*$",
    re.IGNORECASE,
)
_USCODE_GPO_ATTRIBUTION_FRAGMENT_RE = re.compile(
    r"\bfrom\s+the\s+u(?:\s*\.?\s*s(?:\s*\.?\s*c\.?)?)?\b.*$",
    re.IGNORECASE,
)
_SECTION_HEADING_TAIL_SPLIT_RE = re.compile(r"[.;:\n]")
_INFERRED_CONDITION_CLAUSE_SPLIT_RE = re.compile(r"(?:;|[.?!]|—|–|,(?!\d))")
_STATUTORY_SCOPE_UNITS: tuple[str, ...] = (
    "subparagraph",
    "subsection",
    "subclause",
    "subchapter",
    "subdivision",
    "subpart",
    "subtitle",
    "subitem",
    "paragraph",
    "section",
    "chapter",
    "clause",
    "division",
    "article",
    "title",
    "part",
    "item",
)
_STATUTORY_SCOPE_UNIT_PATTERN = "|".join(f"{unit}s?" for unit in _STATUTORY_SCOPE_UNITS)
_STATUTORY_SCOPE_CONNECTORS: tuple[str, ...] = (
    "as otherwise provided in",
    "except as provided in",
    "in accordance with",
    "as referred to in",
    "as described in",
    "as defined in",
    "as set forth in",
    "as provided in",
    "referred to in",
    "described in",
    "defined in",
    "pursuant to",
    "under",
    "within",
    "in",
)
_STATUTORY_SCOPE_CONNECTOR_PATTERN = "|".join(
    re.escape(connector)
    for connector in _STATUTORY_SCOPE_CONNECTORS
)
_ROMAN_NUMERAL_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
_STRICT_ROMAN_NUMERAL_RE = re.compile(
    r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$",
    re.IGNORECASE,
)
_VOWEL_CHARS = frozenset({"a", "e", "i", "o", "u"})
_LOW_INFORMATION_SECTION_MARKER_TOKENS = frozenset(
    {
        "sec",
        "secs",
        "section",
        "sections",
    }
)
_LOW_INFORMATION_SECTION_MARKER_SINGLE_CHAR_TOKENS = frozenset(
    {
        "s",
    }
)
_LOW_INFORMATION_SCOPE_LEADING_TOKENS = frozenset(
    {
        "the",
        "a",
        "an",
        "this",
        "that",
        "such",
    }
)
_LOW_INFORMATION_PREDICATE_HEAD_TOKENS = frozenset(
    {
        "administration",
        "c",
        "codification",
        "code",
        "contents",
        "editorial",
        "heading",
        "note",
        "notes",
        "one",
        "pub",
        "report",
        "section",
        "sec",
        "sections",
        "states",
        "title",
        "u",
        "united",
        "us",
        "usc",
        "uscode",
    }
)
_STRUCTURAL_FRAME_CUE_TOKENS = frozenset(
    {
        "article",
        "chapter",
        "clause",
        "division",
        "paragraph",
        "part",
        "section",
        "subchapter",
        "subclause",
        "subparagraph",
        "subsection",
        "subtitle",
        "title",
    }
)
_SOURCE_ANCHOR_MODAL_CUE_TOKENS = frozenset(
    {
        "shall",
        "must",
        "may",
        "should",
        "will",
        "authorized",
        "required",
        "requires",
        "prohibited",
        "forbidden",
    }
)
_SOURCE_ANCHOR_CONDITION_MARKERS = frozenset(
    {
        "after",
        "before",
        "if",
        "notwithstanding",
        "provided",
        "subject",
        "under",
        "unless",
        "until",
        "when",
        "where",
        "within",
    }
)
_SOURCE_ANCHOR_EXCEPTION_MARKERS = frozenset(
    {
        "except",
        "unless",
    }
)
_SOURCE_ANCHOR_TEMPORAL_MARKERS = frozenset(
    {
        "after",
        "before",
        "by",
        "deadline",
        "effective",
        "fiscal",
        "calendar",
        "until",
        "when",
        "within",
        "year",
    }
)
_SOURCE_ANCHOR_TEMPORAL_CONTEXT_TOKENS = frozenset(
    _SOURCE_ANCHOR_TEMPORAL_MARKERS
    | {
        "date",
        "dates",
        "edition",
        "month",
        "months",
        "years",
    }
)
_SOURCE_ANCHOR_NEGATION_MARKERS = frozenset({"not", "no", "never", "without"})
_SOURCE_ANCHOR_RELATIONAL_TOKENS = frozenset(
    {
        "across",
        "against",
        "along",
        "among",
        "around",
        "at",
        "between",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "onto",
        "over",
        "per",
        "regarding",
        "respect",
        "through",
        "to",
        "under",
        "upon",
        "with",
    }
)
_SOURCE_ANCHOR_NOISE_TOKENS = frozenset(
    set(_LOW_INFORMATION_SCOPE_LEADING_TOKENS)
    | set(_SOURCE_ANCHOR_RELATIONAL_TOKENS)
    | {
        "code",
        "title",
        "chapter",
        "section",
        "subchapter",
        "subsection",
        "paragraph",
        "clause",
        "term",
        "usc",
    }
)
_SOURCE_ANCHOR_CONNECTIVE_TOKENS = frozenset(
    {
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "over",
        "per",
        "to",
        "under",
        "upon",
        "via",
        "with",
        "within",
    }
)
_SOURCE_ANCHOR_QUANTIFIER_TOKENS = frozenset(
    {
        "all",
        "any",
        "each",
        "either",
        "every",
        "many",
        "most",
        "much",
        "neither",
        "no",
        "some",
    }
)
_ALETHIC_SCOPE_CUE_OPERATOR_SYMBOLS: Mapping[str, str] = {
    "able": "◇",
    "actuality": "□",
    "actually": "□",
    "capable": "◇",
    "can": "◇",
    "cannot": "□",
    "impossible": "□",
    "may_be": "◇",
    "necessarily": "□",
    "necessity": "□",
    "necessary": "□",
    "possibility": "◇",
    "possibly": "◇",
    "possible": "◇",
}
_CANONICAL_MODAL_OPERATOR_LABELS: Mapping[Tuple[str, str], str] = {
    ("deontic", "O"): "obligation",
    ("deontic", "P"): "permission",
    ("deontic", "F"): "prohibition",
    ("conditional_normative", "O|"): "conditional_obligation",
    ("temporal", "F"): "eventuality",
    ("temporal", "G"): "always",
    ("temporal", "X"): "next",
    ("epistemic", "K"): "knowledge",
    ("doxastic", "B"): "belief",
    ("dynamic", "[a]"): "after_action",
    ("frame", "Frame"): "frame",
}
_CANONICAL_MODAL_OPERATOR_LABEL_ALIASES: Mapping[str, str] = {
    "obligatory": "obligation",
    "obligation": "obligation",
    "permitted": "permission",
    "permission": "permission",
    "forbidden": "prohibition",
    "prohibited": "prohibition",
    "prohibition": "prohibition",
    "conditionally obligatory": "conditional_obligation",
    "conditional obligation": "conditional_obligation",
    "eventually": "eventuality",
    "eventuality": "eventuality",
    "always": "always",
    "next": "next",
    "known": "knowledge",
    "knowledge": "knowledge",
    "believed": "belief",
    "belief": "belief",
    "after action": "after_action",
    "after_action": "after_action",
    "framed as": "frame",
    "frame": "frame",
}
_CUE_REGISTRY_BRIDGE_FAMILIES: frozenset[str] = frozenset(
    {
        "conditional_normative",
        "deontic",
        "temporal",
        "epistemic",
        "doxastic",
        "dynamic",
    }
)
_CUE_REGISTRY_BRIDGE_FAMILY_PRIORITY: Mapping[str, int] = {
    "deontic": 0,
    "temporal": 1,
    "conditional_normative": 2,
    "epistemic": 3,
    "doxastic": 4,
    "dynamic": 5,
}
_CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS: Mapping[str, tuple[tuple[str, str], ...]] = {
    "if": (("conditional_normative", "O|"),),
    "unless": (("conditional_normative", "O|"),),
    "except": (("conditional_normative", "O|"),),
    "except_as": (("conditional_normative", "O|"),),
    "except_as_provided_in": (("conditional_normative", "O|"),),
    "except_that": (("conditional_normative", "O|"),),
    "except_as_otherwise_provided": (("conditional_normative", "O|"),),
    "except_to_the_extent": (("conditional_normative", "O|"),),
    "provided": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "provided_that": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_subsection": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_subchapter": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_subparagraph": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_paragraph": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_section": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_chapter": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_title": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_subsection": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_subchapter": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_subparagraph": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_paragraph": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_section": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_chapter": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_title": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_the_terms_and_conditions": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_such_terms_and_conditions": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_terms_and_conditions": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_only_to": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_however_to": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "notwithstanding": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
    ),
    "under": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "to_the_extent": (("conditional_normative", "O|"),),
    "to_the_extent_provided": (("conditional_normative", "O|"),),
    "in_accordance_with": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "as_otherwise_provided_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "as_provided_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "as_set_forth_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "as_described_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "as_defined_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "referred_to_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "described_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "defined_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "pursuant_to": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "in_the_event_that": (("conditional_normative", "O|"),),
    "in_the_case_of": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "in_connection_with": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "in_order_to": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "for_purposes_of": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "for_the_purposes_of": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "with_respect_to": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "when": (
        ("conditional_normative", "O|"),
        ("temporal", "X"),
    ),
    "until": (
        ("conditional_normative", "O|"),
        ("temporal", "G"),
    ),
    "during": (
        ("conditional_normative", "O|"),
        ("temporal", "G"),
    ),
    "after": (
        ("conditional_normative", "O|"),
        ("temporal", "X"),
        ("dynamic", "[a]"),
    ),
    "only_after": (
        ("conditional_normative", "O|"),
        ("temporal", "X"),
        ("dynamic", "[a]"),
    ),
    "before": (
        ("conditional_normative", "O|"),
        ("temporal", "X"),
        ("dynamic", "[a]"),
    ),
    "upon": (
        ("conditional_normative", "O|"),
        ("temporal", "X"),
        ("dynamic", "[a]"),
    ),
    "thereafter": (
        ("conditional_normative", "O|"),
        ("temporal", "X"),
    ),
    "by": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "within": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "no_later_than": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "not_later_than": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "shall": (("deontic", "O"),),
    "must": (("deontic", "O"),),
    "obligation": (("deontic", "O"),),
    "obligated": (("deontic", "O"),),
    "obligatory": (("deontic", "O"),),
    "required": (("deontic", "O"),),
    "require": (("deontic", "O"),),
    "requires": (("deontic", "O"),),
    "requiring": (("deontic", "O"),),
    "authorized": (("deontic", "P"),),
    "may": (("deontic", "P"),),
    "authority": (
        ("frame", "Frame"),
        ("deontic", "O"),
    ),
    "jurisdiction": (("frame", "Frame"),),
    "administered_by": (("frame", "Frame"),),
    "transfer": (("dynamic", "[a]"),),
    "transfers": (("dynamic", "[a]"),),
    "transferred": (("dynamic", "[a]"),),
    "transferring": (("dynamic", "[a]"),),
    "suspend": (("dynamic", "[a]"),),
    "suspends": (("dynamic", "[a]"),),
    "suspended": (("dynamic", "[a]"),),
    "suspending": (("dynamic", "[a]"),),
    "suspension": (("dynamic", "[a]"),),
    "terminate": (("dynamic", "[a]"),),
    "terminates": (("dynamic", "[a]"),),
    "terminated": (("dynamic", "[a]"),),
    "terminating": (("dynamic", "[a]"),),
    "termination": (("dynamic", "[a]"),),
    "vest": (("dynamic", "[a]"),),
    "vests": (("dynamic", "[a]"),),
    "vested": (("dynamic", "[a]"),),
    "vesting": (("dynamic", "[a]"),),
    "fiscal_year": (("temporal", "F"),),
    "fiscal_years": (("temporal", "F"),),
    "calendar_year": (("temporal", "F"),),
    "calendar_years": (("temporal", "F"),),
    "effective_date": (("temporal", "F"),),
    "effective_dates": (("temporal", "F"),),
    "on_and_after": (("temporal", "F"),),
    "on_or_after": (("temporal", "F"),),
    "determine": (
        ("epistemic", "K"),
        ("doxastic", "B"),
        ("conditional_normative", "O|"),
    ),
    "determines": (
        ("epistemic", "K"),
        ("doxastic", "B"),
        ("conditional_normative", "O|"),
    ),
    "determined": (
        ("epistemic", "K"),
        ("doxastic", "B"),
        ("conditional_normative", "O|"),
    ),
    "determining": (
        ("epistemic", "K"),
        ("doxastic", "B"),
        ("conditional_normative", "O|"),
    ),
    "determination": (("epistemic", "K"),),
    "determinations": (("epistemic", "K"),),
    "finding": (("epistemic", "K"),),
    "findings": (("epistemic", "K"),),
    "find": (("epistemic", "K"),),
    "finds": (("epistemic", "K"),),
    "knowledge": (("epistemic", "K"),),
    "knows": (("epistemic", "K"),),
    "know": (("epistemic", "K"),),
    "known": (("epistemic", "K"),),
    "believe": (("doxastic", "B"),),
    "believes": (("doxastic", "B"),),
    "believed": (("doxastic", "B"),),
    "believing": (("doxastic", "B"),),
    "reason_to_believe": (
        ("epistemic", "K"),
        ("doxastic", "B"),
        ("conditional_normative", "O|"),
    ),
    "reasonably_believes": (("doxastic", "B"),),
    "intent_to": (("doxastic", "B"),),
    "with_intent_to": (("doxastic", "B"),),
}
_CROSS_FAMILY_BRIDGE_FAMILY_PRIORITY: Mapping[str, int] = {
    "conditional_normative": 0,
    "deontic": 1,
    "frame": 2,
    "temporal": 3,
    "epistemic": 4,
    "doxastic": 5,
    "dynamic": 6,
}
_SOURCE_ANCHOR_DIRECTIONAL_FAMILY_PAIR_TARGETS: Mapping[str, tuple[str, ...]] = {
    "alethic": ("conditional_normative", "deontic", "frame", "temporal"),
    "conditional_normative": ("conditional_normative", "deontic"),
    "deontic": ("conditional_normative", "deontic", "frame", "temporal"),
    "doxastic": ("conditional_normative", "deontic"),
    "frame": (
        "conditional_normative",
        "deontic",
        "doxastic",
        "epistemic",
        "frame",
        "temporal",
    ),
    "dynamic": (
        "dynamic",
        "deontic",
        "frame",
        "temporal",
    ),
    "temporal": (
        "conditional_normative",
        "deontic",
        "epistemic",
        "frame",
        "temporal",
    ),
}
_DEONTIC_BRIDGE_REINFORCEMENT_OPERATORS: frozenset[str] = frozenset(
    {
        "O",
        "P",
        "F",
    }
)
_DEONTIC_BRIDGE_REINFORCEMENT_CUES: frozenset[str] = frozenset(
    {
        "in_accordance_with",
        "may",
        "must",
        "shall",
        "authorized",
        "with_respect_to",
    }
)
_DEONTIC_EPISTEMIC_BRIDGE_CUES: frozenset[str] = frozenset(
    {
        "believe",
        "believes",
        "believed",
        "believing",
        "reasonably_believes",
    }
)
_EPISTEMIC_DEONTIC_BRIDGE_CUES: frozenset[str] = frozenset(
    {
        "determine",
        "determines",
        "determined",
        "determining",
        "find",
        "finds",
        "finding",
        "reason_to_believe",
    }
)
_CLAUSE_PREFIX_BRIDGE_CUES: frozenset[str] = frozenset(
    prefix_key
    for _, prefix_key in (*_CONDITION_PREFIXES, *_EXCEPTION_PREFIXES)
)
_DEONTIC_TEMPORAL_BRIDGE_CUES: frozenset[str] = frozenset(
    {
        "shall",
        "must",
        "obligation",
        "obligated",
        "obligatory",
        "required",
        "require",
        "requires",
        "requiring",
        "authorized",
        "may",
    }
)
_FRAME_TEMPORAL_BRIDGE_CUES: frozenset[str] = frozenset(
    _STRUCTURAL_FRAME_CUE_TOKENS
    | {
        "code",
        "frame",
    }
)
_TEMPORAL_BRIDGE_CONTEXT_TOKENS: frozenset[str] = frozenset(
    {
        "year",
        "day",
        "month",
        "deadline",
        "effective",
        "edition",
        "fiscal",
        "calendar",
        "immediately",
        "promptly",
        "subsequent",
        "thereafter",
        "timely",
        "period",
        "date",
        "term",
        "continuance",
    }
)
_TEMPORAL_BRIDGE_CONTEXT_PHRASES: tuple[tuple[str, str], ...] = (
    ("on and after", "on_and_after"),
    ("on or after", "on_or_after"),
    ("no later than", "no_later_than"),
    ("not later than", "not_later_than"),
    ("during continuance", "during_continuance"),
    ("during his continuance", "during_continuance"),
    ("during her continuance", "during_continuance"),
    ("during their continuance", "during_continuance"),
    ("continuance in office", "continuance_in_office"),
    ("effective date", "effective_date"),
    ("effective dates", "effective_date"),
    ("fiscal year", "fiscal_year"),
    ("fiscal years", "fiscal_year"),
    ("calendar year", "calendar_year"),
    ("calendar years", "calendar_year"),
    ("for each year thereafter", "year_thereafter"),
)
_TEMPORAL_BRIDGE_YEAR_RE = re.compile(r"(?<!\d)(?:18|19|20)\d{2}(?!\d)")
_TEMPORAL_ORIGIN_FROM_RE = re.compile(
    r"(?<!\w)from\s+(?:"
    r"(?:the\s+)?(?:date|effective\s+date|date\s+of\s+enactment|"
    r"enactment|beginning|start|commencement|fiscal\s+year|calendar\s+year|"
    r"taxable\s+year|school\s+year|program\s+year|year)\b"
    r"|(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+\d{1,2}\b"
    r"|(?:18|19|20)\d{2}\b"
    r")",
    re.IGNORECASE,
)
_MODAL_OPERATOR_SYMBOL_FEATURE_KEYS: Mapping[str, str] = {
    "O|": "o_pipe",
    "[a]": "a_box",
    "□": "box",
    "◇": "diamond",
}
_PROVENANCE_NUMERIC_ALIGNMENT_SIGNATURES: tuple[str, ...] = (
    "leading_digit",
    "parity",
    "has_zero_digit",
    "zero_digit_count",
    "magnitude_bucket",
    "thousands_block",
)
_STATUTORY_SCOPE_REFERENCE_RE = re.compile(
    rf"(?<!\w)"
    rf"(?P<connector>{_STATUTORY_SCOPE_CONNECTOR_PATTERN})"
    rf"\s+"
    rf"(?:(?P<determiner>this|such)\s+)?"
    rf"(?P<unit>{_STATUTORY_SCOPE_UNIT_PATTERN})"
    rf"(?:\s+(?P<target>(?:\([^)]+\))+|[0-9A-Za-z][0-9A-Za-z.\-]*(?:\([^)]+\))*))?"
    rf"(?!\w)",
    re.IGNORECASE,
)
_CUE_TOKEN_RE = re.compile(r"[a-z0-9]+")
_FRAME_ONTOLOGY_METADATA_MAX_DEPTH = 6
_FRAME_ONTOLOGY_METADATA_MAX_VALUES = 256
_FRAME_ONTOLOGY_METADATA_OPAQUE_ID_HEX_RE = re.compile(
    r"[0-9a-f]{12,}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DecodedModalPhrase:
    """One phrase rendered from a modal IR slot."""

    text: str
    slot: str
    spans: List[List[int]] = field(default_factory=list)
    fixed: bool = False
    provenance_only: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecodedModalText:
    """Decompiled modal text plus provenance and audit metadata."""

    source_id: str
    text: str
    phrases: List[DecodedModalPhrase]
    support_span: List[int]
    reconstruction_similarity: float = 0.0
    modal_span_coverage: float = 0.0
    reconstruction_strategy: str = "provenance_span_reconstruction_v1"
    parser_warnings: List[str] = field(default_factory=list)
    missing_slots: List[str] = field(default_factory=list)
    formulas: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["phrases"] = [phrase.to_dict() for phrase in self.phrases]
        return data


def decode_modal_ir_document(document: ModalIRDocument) -> DecodedModalText:
    """Reconstruct source semantics while preserving formula audit metadata."""
    source_phrases, modal_span_coverage = _source_reconstruction_phrases(document)
    typed_reconstruction_provenance_only = (
        bool(source_phrases)
        and not _should_emit_guided_semantic_reconstruction(document)
    )
    formula_order = tuple(sorted(document.formulas, key=lambda item: item.formula_id))
    phrases: List[DecodedModalPhrase] = [
        *source_phrases,
        *_source_span_slot_phrases(
            source_phrases,
            formulas=document.formulas,
        ),
        *_source_span_slot_phrases(source_phrases, formulas=formula_order),
        *_document_span_metric_phrases(
            document=document,
            modal_span_coverage=modal_span_coverage,
        ),
        *_source_identifier_phrases(document),
        *_document_citation_phrases(document),
        *_document_modal_family_count_phrases(document),
        *_autoencoder_modal_family_guidance_phrases(document),
        *_frame_candidate_phrases(document),
        *_frame_ontology_phrases(document),
    ]
    if not document.formulas:
        phrases.extend(_document_provenance_alignment_phrases(document))
    missing_slots: List[str] = []
    formulas: List[str] = []

    if not document.formulas:
        missing_slots.append("formulas")
    if not document.normalized_text:
        missing_slots.append("source_text")
    if document.normalized_text and not source_phrases:
        missing_slots.append("source_spans")

    for index, formula in enumerate(formula_order):
        if index:
            phrases.append(_fixed_phrase(";", "formula_separator"))
        formula_text = modal_formula_to_text(formula)
        formulas.append(formula_text)
        phrases.extend(_decode_formula_phrases(formula, document=document))
        phrases.extend(
            _fallback_section_heading_tail_phrases(
                document=document,
                formula=formula,
            )
        )
        phrases.extend(
            _fallback_surface_text_phrases(
                document=document,
                formula=formula,
            )
        )
        typed_reconstruction_phrases = _typed_ir_reconstruction_phrases(
            document=document,
            formula=formula,
            provenance_only=typed_reconstruction_provenance_only,
        )
        phrases.extend(typed_reconstruction_phrases)
        phrases.extend(
            _guided_semantic_reconstruction_phrases(
                document=document,
                formula=formula,
                typed_phrases=typed_reconstruction_phrases,
            )
        )

    selected_frame = _selected_frame(document)
    if selected_frame:
        if phrases:
            phrases.append(_fixed_phrase("in", "frame_connector"))
        phrases.append(
            DecodedModalPhrase(
                text=selected_frame,
                slot="selected_frame",
                fixed=False,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            selected_frame,
            slot_prefix="selected_frame",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )
        phrases.extend(_selected_frame_modal_family_phrases(document))

    support_span = _support_span(document.formulas)
    parser_warnings = [
        str(value)
        for value in document.metadata.get("parser_warnings", [])
        if value is not None
    ]
    reconstructed_text = _sentence_from_phrases(phrases)
    return DecodedModalText(
        source_id=document.document_id,
        text=reconstructed_text,
        phrases=phrases,
        support_span=support_span,
        reconstruction_similarity=modal_text_token_similarity(
            document.normalized_text,
            reconstructed_text,
        ),
        modal_span_coverage=modal_span_coverage,
        parser_warnings=parser_warnings,
        missing_slots=missing_slots,
        formulas=formulas,
    )


def modal_formula_to_text(formula: ModalIRFormula) -> str:
    """Render a stable formula-like string from one modal IR formula."""
    arguments = ", ".join(formula.predicate.arguments)
    predicate = formula.predicate.name
    if arguments:
        predicate = f"{predicate}({arguments})"
    return f"{formula.operator.symbol}[{formula.operator.family}:{formula.operator.system}]({predicate})"


def decoded_modal_phrase_slot_text_map(
    decoded: DecodedModalText,
    *,
    include_fixed: bool = False,
    include_provenance_only: bool = True,
) -> Dict[str, List[str]]:
    """Return decoded phrase texts grouped by source slot."""
    slot_texts: Dict[str, List[str]] = {}
    for phrase in decoded.phrases:
        if phrase.fixed and not include_fixed:
            continue
        if phrase.provenance_only and not include_provenance_only:
            continue
        slot = str(phrase.slot or "").strip()
        text = _clean_text(phrase.text)
        if not slot or not text:
            continue
        values = slot_texts.setdefault(slot, [])
        if text not in values:
            values.append(text)
    return slot_texts


def modal_text_token_similarity(left: str, right: str) -> float:
    """Return deterministic token-set F1 similarity for reconstruction checks."""
    left_tokens = set(_tokenize_for_similarity(left))
    right_tokens = set(_tokenize_for_similarity(right))
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    if overlap == 0:
        return 0.0
    precision = overlap / len(right_tokens)
    recall = overlap / len(left_tokens)
    return round((2.0 * precision * recall) / (precision + recall), 6)


def _decode_formula_phrases(
    formula: ModalIRFormula,
    *,
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    spans = [[formula.provenance.start_char, formula.provenance.end_char]]
    cue_start = formula.metadata.get("cue_start_char")
    cue_end = formula.metadata.get("cue_end_char")
    cue_values = _formula_cues(formula)
    argument_values = _phrase_values(formula.predicate.arguments)
    condition_values = _phrase_values(formula.conditions)
    if not condition_values:
        condition_values = _inferred_condition_values_from_source_span(
            document=document,
            formula=formula,
        )
    exception_values = _phrase_values(formula.exceptions)
    statutory_scope_emissions: set[Tuple[str, str]] = set()
    predicate_text = _predicate_phrase(formula)
    phrases = [
        DecodedModalPhrase(
            text=modal_formula_to_text(formula),
            slot="formula",
            spans=spans,
            provenance_only=True,
        ),
        DecodedModalPhrase(
            text=_operator_phrase(formula),
            slot="operator",
            spans=_span_from_values(cue_start, cue_end) or spans,
            provenance_only=True,
        ),
        DecodedModalPhrase(
            text=_clean_text(formula.operator.symbol),
            slot="modal_operator",
            spans=_span_from_values(cue_start, cue_end) or spans,
            provenance_only=True,
        ),
        DecodedModalPhrase(
            text=_clean_text(formula.operator.family),
            slot="modal_family",
            spans=_span_from_values(cue_start, cue_end) or spans,
            provenance_only=True,
        ),
        DecodedModalPhrase(
            text=_clean_text(formula.operator.system),
            slot="modal_system",
            spans=_span_from_values(cue_start, cue_end) or spans,
            provenance_only=True,
        ),
        DecodedModalPhrase(
            text=predicate_text,
            slot="predicate",
            spans=spans,
            provenance_only=True,
        ),
    ]
    for slot, value in _typed_identifier_slots(
        predicate_text,
        slot_prefix="predicate",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    phrases.extend(
        _content_scope_phrases(
            predicate_text,
            slot_prefix="predicate",
            spans=spans,
        )
    )
    phrases.extend(
        _typed_decompiler_role_phrases(
            formula=formula,
            text=predicate_text,
            slot_prefix="predicate",
            spans=spans,
        )
    )
    _append_statutory_scope_phrases(
        phrases,
        predicate_text,
        spans=spans,
        emitted=statutory_scope_emissions,
    )
    phrases.extend(
        _contextual_modal_cue_phrases(
            formula=formula,
            text=predicate_text,
            slot_prefix="predicate",
            spans=spans,
        )
    )
    operator_label = _resolved_modal_operator_label(formula)
    if operator_label:
        operator_spans = _span_from_values(cue_start, cue_end) or spans
        phrases.append(
            DecodedModalPhrase(
                text=operator_label,
                slot="modal_operator_label",
                spans=operator_spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            operator_label,
            slot_prefix="modal_operator_label",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=operator_spans,
                    provenance_only=True,
                )
            )
    canonical_operator_label = _canonical_modal_operator_label(
        formula,
        operator_label=operator_label,
    )
    if canonical_operator_label:
        operator_spans = _span_from_values(cue_start, cue_end) or spans
        phrases.append(
            DecodedModalPhrase(
                text=canonical_operator_label,
                slot="modal_operator_label_canonical",
                spans=operator_spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            canonical_operator_label,
            slot_prefix="modal_operator_label_canonical",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=operator_spans,
                    provenance_only=True,
                )
            )
    operator_signature = _modal_operator_signature(
        formula,
        operator_label=operator_label,
    )
    if operator_signature:
        operator_spans = _span_from_values(cue_start, cue_end) or spans
        phrases.append(
            DecodedModalPhrase(
                text=operator_signature,
                slot="modal_operator_signature",
                spans=operator_spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            operator_signature.replace(":", "_"),
            slot_prefix="modal_operator_signature",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=operator_spans,
                    provenance_only=True,
                )
            )
    for cue in cue_values:
        cue_spans = _span_from_values(cue_start, cue_end) or spans
        phrases.append(
            DecodedModalPhrase(
                text=cue,
                slot="cue",
                spans=cue_spans,
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=cue,
                slot="modal_cue",
                spans=cue_spans,
                provenance_only=True,
            )
        )
        for cue_slot, cue_value in _cue_modal_slots(formula, cue=cue):
            phrases.append(
                DecodedModalPhrase(
                    text=cue_value,
                    slot=cue_slot,
                    spans=cue_spans,
                    provenance_only=True,
                )
            )
            alias_slot = _cue_alias_slot_name(cue_slot)
            if alias_slot:
                phrases.append(
                    DecodedModalPhrase(
                        text=cue_value,
                        slot=alias_slot,
                        spans=cue_spans,
                        provenance_only=True,
                    )
                )
    for bridge_cue in _formula_bridge_cues(
        formula,
        extra_clauses=(*condition_values, *exception_values),
    ):
        bridge_spans = _span_from_values(cue_start, cue_end) or spans
        phrases.append(
            DecodedModalPhrase(
                text=bridge_cue,
                slot="bridge_cue",
                spans=bridge_spans,
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=bridge_cue,
                slot="modal_bridge_cue",
                spans=bridge_spans,
                provenance_only=True,
            )
        )
        for bridge_slot, bridge_value in _modal_lexeme_slots(
            formula,
            cue=bridge_cue,
            slot_prefix="bridge_modal",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=bridge_value,
                    slot=bridge_slot,
                    spans=bridge_spans,
                    provenance_only=True,
                )
            )
    if argument_values:
        phrases.append(
            DecodedModalPhrase(
                text=", ".join(argument_values),
                slot="arguments",
                spans=spans,
                provenance_only=True,
            )
        )
    for argument in argument_values:
        phrases.append(
            DecodedModalPhrase(
                text=argument,
                slot="argument",
                spans=spans,
                provenance_only=True,
            )
        )
        _append_statutory_scope_phrases(
            phrases,
            argument,
            spans=spans,
            emitted=statutory_scope_emissions,
        )
        phrases.extend(
            _contextual_modal_cue_phrases(
                formula=formula,
                text=argument,
                slot_prefix="argument",
                spans=spans,
            )
        )
        typed_argument_slot = _typed_argument_slot(argument)
        if typed_argument_slot is None:
            continue
        slot, value = typed_argument_slot
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    if formula.predicate.role:
        phrases.append(
            DecodedModalPhrase(
                text=str(formula.predicate.role),
                slot="role",
                spans=spans,
                provenance_only=True,
            )
        )
    proxy_condition_from_exception = not condition_values and bool(exception_values)
    for slot, value in _typed_deontic_ir_slots(
        formula=formula,
        document=document,
        predicate_text=predicate_text,
        cue_values=cue_values,
        condition_values=condition_values,
        exception_values=exception_values,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    for slot, value in _typed_decompiler_target_reconstruction_slots(
        formula=formula,
        document=document,
        predicate_text=predicate_text,
        condition_values=condition_values,
        exception_values=exception_values,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    for slot, value in _typed_decompiler_source_reconstruction_slots(
        formula=formula,
        document=document,
        predicate_text=predicate_text,
        condition_values=condition_values,
        exception_values=exception_values,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    for slot, value in _typed_decompiler_conditional_normative_preservation_slots(
        formula=formula,
        document=document,
        predicate_text=predicate_text,
        cue_values=cue_values,
        condition_values=condition_values,
        exception_values=exception_values,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    for condition in condition_values:
        phrases.append(
            DecodedModalPhrase(
                text=condition,
                slot="condition",
                spans=spans,
                provenance_only=True,
            )
        )
        for typed_slot, typed_value in _typed_identifier_slots(
            condition,
            slot_prefix="condition",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=typed_value,
                    slot=typed_slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        phrases.extend(
            _typed_clause_phrases(
                condition,
                slot="condition",
                spans=spans,
                formula=formula,
            )
        )
        _append_statutory_scope_phrases(
            phrases,
            condition,
            spans=spans,
            emitted=statutory_scope_emissions,
        )
    for exception in exception_values:
        phrases.append(
            DecodedModalPhrase(
                text=exception,
                slot="exception",
                spans=spans,
                provenance_only=True,
            )
        )
        for typed_slot, typed_value in _typed_identifier_slots(
            exception,
            slot_prefix="exception",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=typed_value,
                    slot=typed_slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        phrases.extend(
            _typed_clause_phrases(
                exception,
                slot="exception",
                spans=spans,
                formula=formula,
            )
        )
        _append_statutory_scope_phrases(
            phrases,
            exception,
            spans=spans,
            emitted=statutory_scope_emissions,
        )
        if proxy_condition_from_exception:
            phrases.extend(
                _condition_proxy_phrases_from_exception(
                    exception=exception,
                    spans=spans,
                    formula=formula,
                )
            )
    source_span_text = _formula_source_span_text(document=document, formula=formula)
    if source_span_text:
        phrases.extend(
            _legal_semantic_atom_phrases(
                text=source_span_text,
                slot_prefix="modal_source_span",
                spans=spans,
            )
        )
        phrases.extend(
            _contextual_modal_cue_phrases(
                formula=formula,
                text=source_span_text,
                slot_prefix="modal_source_span",
                spans=spans,
            )
        )
        phrases.extend(
            _source_role_anchor_phrases(
                document=document,
                formula=formula,
                spans=spans,
            )
        )
        phrases.extend(
            _typed_decompiler_role_phrases(
                formula=formula,
                text=source_span_text,
                slot_prefix="modal_source_span",
                spans=spans,
            )
        )
    for polarity_slot, polarity_value in _modal_polarity_slots(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
        document=document,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=polarity_value,
                slot=polarity_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    for cue_force_slot, cue_force_value in _typed_decompiler_cue_force_slots(
        formula=formula,
        document=document,
        text=source_span_text or predicate_text,
        condition_values=condition_values,
        exception_values=exception_values,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=cue_force_value,
                slot=cue_force_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    status_clause_text = _uscode_status_clause_text(
        document=document,
        formula=formula,
    )
    if status_clause_text:
        phrases.append(
            DecodedModalPhrase(
                text=status_clause_text,
                slot="source_status_clause",
                spans=spans,
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=status_clause_text,
                slot="typed_ir_surface_reconstruction",
                spans=spans,
                provenance_only=True,
            )
        )
        for typed_slot, typed_value in _typed_identifier_slots(
            status_clause_text,
            slot_prefix="source_status_clause",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=typed_value,
                    slot=typed_slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        for status_slot, status_value in _uscode_editorial_status_detail_slots(
            status_clause_text,
            slot_prefix="source_status_clause",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=status_value,
                    slot=status_slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        phrases.extend(
            _legal_semantic_atom_phrases(
                text=status_clause_text,
                slot_prefix="source_status_clause",
                spans=spans,
            )
        )
        phrases.extend(
            _contextual_modal_cue_phrases(
                formula=formula,
                text=status_clause_text,
                slot_prefix="source_status_clause",
                spans=spans,
            )
        )
        phrases.extend(
            _typed_decompiler_role_phrases(
                formula=formula,
                text=status_clause_text,
                slot_prefix="source_status_clause",
                spans=spans,
            )
        )
        for transition_slot, transition_value in _refined_contextual_modal_transition_slots(
            formula,
            text=status_clause_text,
            slot_prefix="source_status_clause",
        ):
            if not transition_slot.endswith("_refined_modal_family_pair"):
                continue
            phrases.append(
                DecodedModalPhrase(
                    text=transition_value,
                    slot="typed_decompiler_family_pair",
                    spans=spans,
                    provenance_only=True,
                )
            )
    fallback_rule = _clean_text(formula.metadata.get("fallback_rule") or "")
    if fallback_rule:
        phrases.append(
            DecodedModalPhrase(
                text=fallback_rule,
                slot="fallback_rule",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            fallback_rule,
            slot_prefix="fallback_rule",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    status_keyword = _derived_status_keyword(
        formula=formula,
        fallback_rule=fallback_rule,
    )
    if status_keyword:
        phrases.append(
            DecodedModalPhrase(
                text=status_keyword,
                slot="status_keyword",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            status_keyword,
            slot_prefix="status_keyword",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    statement_hint = _clean_text(formula.metadata.get("statement_hint") or "")
    if statement_hint:
        phrases.append(
            DecodedModalPhrase(
                text=statement_hint,
                slot="statement_hint",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            statement_hint,
            slot_prefix="statement_hint",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    procedural_keyword = _clean_text(formula.metadata.get("procedural_keyword") or "")
    if procedural_keyword:
        phrases.append(
            DecodedModalPhrase(
                text=procedural_keyword,
                slot="procedural_keyword",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            procedural_keyword,
            slot_prefix="procedural_keyword",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    source_id = _clean_text(formula.provenance.source_id or "")
    citation = _clean_text(formula.provenance.citation or "")
    citation_inferred_from_source_id = False
    if not citation:
        citation = _source_id_inferred_citation(source_id)
        citation_inferred_from_source_id = bool(citation)
    if citation:
        if citation_inferred_from_source_id:
            phrases.append(
                DecodedModalPhrase(
                    text="source_id_inferred",
                    slot="citation_derivation",
                    spans=spans,
                    provenance_only=True,
                )
            )
        phrases.append(
            DecodedModalPhrase(
                text=citation,
                slot="citation",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _citation_slots(citation):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    for slot, value in _provenance_alignment_slots(
        source_id=source_id,
        citation=citation,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    return phrases


def _fallback_section_heading_tail_phrases(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[DecodedModalPhrase]:
    heading_tail = _fallback_section_heading_tail_text(document=document, formula=formula)
    if not heading_tail:
        return []
    spans = [[formula.provenance.start_char, formula.provenance.end_char]]
    phrases = [
        DecodedModalPhrase(
            text=heading_tail,
            slot="section_heading_tail",
            spans=spans,
            provenance_only=True,
        )
    ]
    for slot, value in _typed_identifier_slots(
        heading_tail,
        slot_prefix="section_heading_tail",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    phrases.extend(
        _legal_semantic_atom_phrases(
            text=heading_tail,
            slot_prefix="section_heading_tail",
            spans=spans,
        )
    )
    phrases.extend(
        _contextual_modal_cue_phrases(
            formula=formula,
            text=heading_tail,
            slot_prefix="section_heading_tail",
            spans=spans,
        )
    )
    phrases.extend(
        _typed_decompiler_role_phrases(
            formula=formula,
            text=heading_tail,
            slot_prefix="section_heading_tail",
            spans=spans,
        )
    )
    return phrases


def _inferred_condition_values_from_source_span(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    max_candidates: int = 2,
    max_tokens: int = 40,
) -> List[str]:
    if formula.conditions:
        return []
    span_text = _formula_source_span_text(document=document, formula=formula)
    if not span_text:
        return []
    cue_key = _clean_text(formula.metadata.get("cue") or "").lower().replace(" ", "_")
    ordered_prefixes = sorted(
        _CONDITION_PREFIXES,
        key=lambda item: (
            item[1] == "under",
            -len(item[0]),
            item[0],
        ),
    )
    prioritized_prefixes: List[Tuple[str, str]] = []
    if cue_key:
        for prefix_text, prefix_key in ordered_prefixes:
            if prefix_key == cue_key:
                prioritized_prefixes.append((prefix_text, prefix_key))
    prioritized_prefixes.extend(
        (prefix_text, prefix_key)
        for prefix_text, prefix_key in ordered_prefixes
        if (prefix_text, prefix_key) not in prioritized_prefixes
    )
    lowered_span = span_text.lower()
    inferred: List[str] = []
    inferred_lower: set[str] = set()
    for prefix_text, prefix_key in prioritized_prefixes:
        if prefix_key == "under":
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(prefix_text)}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(lowered_span):
            clause = _trim_inferred_condition_clause(span_text[match.start() :])
            if not clause:
                continue
            token_count = len(_tokenize_for_similarity(clause))
            if token_count < 2 or token_count > max_tokens:
                continue
            parsed_clause = _typed_clause_slot(clause, slot="condition")
            if parsed_clause is None:
                continue
            _, parsed_prefix_key, scoped_value = parsed_clause
            if not scoped_value or parsed_prefix_key != prefix_key:
                continue
            clause_lower = clause.lower()
            if clause_lower in inferred_lower:
                continue
            inferred.append(clause)
            inferred_lower.add(clause_lower)
            if len(inferred) >= max_candidates:
                return inferred
    return inferred


def _formula_source_span_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> str:
    source_text = str(document.normalized_text or "")
    if not source_text:
        return ""
    start = max(0, min(len(source_text), int(formula.provenance.start_char)))
    end = max(start, min(len(source_text), int(formula.provenance.end_char)))
    return _clean_text(source_text[start:end])


def _trim_inferred_condition_clause(clause: str) -> str:
    normalized_clause = _clean_text(clause)
    if not normalized_clause:
        return ""
    normalized_clause = _strip_uscode_gpo_attribution_fragment(normalized_clause)
    trimmed = _clean_text(
        _INFERRED_CONDITION_CLAUSE_SPLIT_RE.split(normalized_clause, maxsplit=1)[0]
    )
    return _TRAILING_SECTION_PUNCT_RE.sub("", trimmed)


def _fallback_surface_text_phrases(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[DecodedModalPhrase]:
    surface_text = _fallback_surface_text(document=document, formula=formula)
    if not surface_text:
        return []
    spans = [[formula.provenance.start_char, formula.provenance.end_char]]
    phrases = [
        DecodedModalPhrase(
            text=surface_text,
            slot="fallback_surface_text",
            spans=spans,
            provenance_only=True,
        )
    ]
    for slot, value in _typed_identifier_slots(
        surface_text,
        slot_prefix="fallback_surface_text",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    phrases.extend(
        _legal_semantic_atom_phrases(
            text=surface_text,
            slot_prefix="fallback_surface_text",
            spans=spans,
        )
    )
    phrases.extend(
        _contextual_modal_cue_phrases(
            formula=formula,
            text=surface_text,
            slot_prefix="fallback_surface_text",
            spans=spans,
        )
    )
    phrases.extend(
        _typed_decompiler_role_phrases(
            formula=formula,
            text=surface_text,
            slot_prefix="fallback_surface_text",
            spans=spans,
        )
    )
    fallback_context = _fallback_surface_context_text(
        document=document,
        formula=formula,
        surface_text=surface_text,
    )
    if fallback_context:
        phrases.append(
            DecodedModalPhrase(
                text=fallback_context,
                slot="fallback_surface_context",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            fallback_context,
            slot_prefix="fallback_surface_context",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        phrases.extend(
            _legal_semantic_atom_phrases(
                text=fallback_context,
                slot_prefix="fallback_surface_context",
                spans=spans,
            )
        )
        phrases.extend(
            _contextual_modal_cue_phrases(
                formula=formula,
                text=fallback_context,
                slot_prefix="fallback_surface_context",
                spans=spans,
            )
        )
    return phrases


def _typed_ir_reconstruction_phrases(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    max_values: int = 10,
    max_tokens: int = 56,
    provenance_only: bool = True,
) -> List[DecodedModalPhrase]:
    """Emit bounded structural text from typed slots, not copied source spans."""
    spans = [[formula.provenance.start_char, formula.provenance.end_char]]
    predicate_text = _predicate_phrase(formula)
    argument_values = _phrase_values(formula.predicate.arguments)
    condition_values = _phrase_values(formula.conditions)
    if not condition_values:
        condition_values = _inferred_condition_values_from_source_span(
            document=document,
            formula=formula,
        )
    exception_values = _phrase_values(formula.exceptions)
    source_span_text = _formula_source_span_text(document=document, formula=formula)
    heading_text = _fallback_section_heading_tail_text(
        document=document,
        formula=formula,
        max_tokens=18,
    )
    fallback_text = _fallback_surface_text(
        document=document,
        formula=formula,
        max_tokens=24,
    )
    operator_label = _canonical_modal_operator_label(
        formula,
        operator_label=_resolved_modal_operator_label(formula),
    )
    family = _clean_text(formula.operator.family).lower()
    roles = _semantic_role_values_from_text(
        " ".join(
            value.replace("_", " ")
            for value in (
                predicate_text,
                source_span_text,
                " ".join(argument_values),
                " ".join(condition_values),
                " ".join(exception_values),
            )
            if _clean_text(value)
        )
    )
    for role, value in _semantic_role_values_from_arguments(argument_values).items():
        roles.setdefault(role, value)
    if family == "temporal" and "temporal" not in roles:
        roles["temporal"] = "temporal_operator_scope"
    semantic_atoms = _legal_semantic_atoms_from_text(
        " ".join(
            value
            for value in (
                heading_text,
                fallback_text,
                predicate_text,
                source_span_text,
                " ".join(condition_values),
                " ".join(exception_values),
            )
            if _clean_text(value)
        )
    )
    status_detail_values = [
        value
        for slot, value in _uscode_editorial_status_detail_slots(
            " ".join(
                value
                for value in (
                    heading_text,
                    fallback_text,
                    source_span_text,
                    " ".join(condition_values),
                    " ".join(exception_values),
                )
                if _clean_text(value)
            ),
            slot_prefix="typed_ir_status",
        )
        if slot.startswith("uscode_editorial_status_")
        and not slot.endswith("_keyword")
    ]
    targets = _typed_decompiler_bridge_target_families(
        formula=formula,
        text=" ".join(
            value.replace("_", " ")
            for value in (
                predicate_text,
                source_span_text,
                heading_text,
                fallback_text,
                " ".join(condition_values),
                " ".join(exception_values),
            )
            if _clean_text(value)
        ),
        roles=roles,
    )
    for guided_target in _autoencoder_target_family_guidance_values(document):
        if guided_target not in targets:
            targets.append(guided_target)
    for guided_target in _autoencoder_family_pair_target_guidance_values(
        document,
        source_family=family,
    ):
        if guided_target not in targets:
            targets.append(guided_target)
    if family == "temporal" and "temporal" not in targets:
        targets.append("temporal")
    if (condition_values or exception_values) and "conditional_normative" not in targets:
        targets.append("conditional_normative")
    if family == "frame" and semantic_atoms:
        for status_target in _typed_decompiler_status_atom_target_families(
            semantic_atoms
        ):
            if status_target not in targets:
                targets.append(status_target)
    for semantic_target in _typed_decompiler_semantic_atom_target_families(
        semantic_atoms
    ):
        if semantic_target not in targets:
            targets.append(semantic_target)
    for directional_target in _typed_decompiler_directional_target_families(family):
        if directional_target not in targets:
            targets.append(directional_target)

    legal_ir_view_support = _typed_ir_legal_view_support_values(document)
    support_values: List[str] = []

    def add_support(value: str) -> None:
        cleaned = _clean_text(value).replace("_", " ")
        if cleaned and cleaned not in support_values:
            support_values.append(cleaned)

    add_support(heading_text)
    add_support(fallback_text)
    add_support(predicate_text)
    add_support(operator_label)
    force = _modal_force_label(formula)
    polarity = _modal_scope_polarity(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
        document=document,
    )
    add_support(force)
    add_support(polarity.replace("_", " "))
    if "deontic" in targets or any(
        "deontic" in _clean_text(value).lower()
        for value in legal_ir_view_support
    ):
        add_support("deontic legal obligations")
        if force in {"obligation", "permission", "prohibition"}:
            add_support(f"{force} force")
    for cue in _typed_ir_reconstruction_cue_support_values(
        formula=formula,
        text=" ".join(
            value.replace("_", " ")
            for value in (
                predicate_text,
                source_span_text,
                heading_text,
                fallback_text,
                " ".join(condition_values),
                " ".join(exception_values),
            )
            if _clean_text(value)
        ),
        condition_values=condition_values,
        exception_values=exception_values,
    ):
        add_support(cue)
    for cue in _definition_condition_support_values(
        " ".join(
            value.replace("_", " ")
            for value in (
                predicate_text,
                source_span_text,
                heading_text,
                fallback_text,
                " ".join(condition_values),
                " ".join(exception_values),
            )
            if _clean_text(value)
        )
    ):
        add_support(cue)
    for value in (*condition_values, *exception_values):
        add_support(value)
    for atom in semantic_atoms:
        add_support(atom)
    for value in status_detail_values:
        add_support(value)
    for value in _typed_ir_role_reconstruction_values(roles):
        add_support(value)
    for view_support in legal_ir_view_support:
        add_support(view_support)
    for role in ("subject", "action", "object", "temporal"):
        add_support(roles.get(role, ""))

    ordered_targets = sorted(
        targets,
        key=_typed_ir_reconstruction_target_order,
    )
    target_labels = [
        _typed_ir_target_family_label(target)
        for target in ordered_targets
        if _typed_ir_target_family_label(target)
    ]
    pair_labels = [
        _typed_ir_family_pair_reconstruction_label(family, target)
        for target in ordered_targets
        if _typed_ir_family_pair_reconstruction_label(family, target)
    ]
    atom_support_values = [_humanize_typed_ir_value(atom) for atom in semantic_atoms]
    summary_parts = [
        *target_labels[:4],
        *pair_labels[:4],
        *atom_support_values[:6],
        *support_values[:max_values],
    ]
    summary = _bounded_reconstruction_text(summary_parts, max_tokens=max_tokens)
    semantic_surface = _typed_ir_semantic_surface_reconstruction_text(
        predicate_text=predicate_text,
        roles=roles,
        force=force,
        polarity=polarity,
        cue_values=_formula_cues(formula),
        condition_values=condition_values,
        exception_values=exception_values,
        semantic_atoms=semantic_atoms,
        targets=ordered_targets,
        max_tokens=max_tokens,
    )
    source_semantic_sentence = _typed_ir_source_semantic_sentence_text(
        source_family=family,
        include_family_pair_labels=_should_emit_guided_semantic_reconstruction(document),
        roles=roles,
        force=force,
        polarity=polarity,
        condition_values=condition_values,
        exception_values=exception_values,
        semantic_atoms=semantic_atoms,
        targets=ordered_targets,
        max_tokens=max_tokens,
    )
    normative_status_narrative = _typed_ir_normative_status_narrative_text(
        source_family=family,
        targets=ordered_targets,
        force=force,
        polarity=polarity,
        roles=roles,
        condition_values=condition_values,
        exception_values=exception_values,
        semantic_atoms=semantic_atoms,
        status_detail_values=status_detail_values,
        legal_ir_view_support=legal_ir_view_support,
        max_tokens=max_tokens,
    )
    semantic_reconstruction_clause = _typed_ir_semantic_reconstruction_clause_text(
        family=family,
        targets=ordered_targets,
        force=force,
        polarity=polarity,
        predicate_text=predicate_text,
        roles=roles,
        condition_values=condition_values,
        exception_values=exception_values,
        semantic_atoms=semantic_atoms,
        legal_ir_view_support=legal_ir_view_support,
        max_tokens=max_tokens,
    )
    scope_frame_texts = _typed_ir_scope_frame_texts(
        source_family=family,
        targets=ordered_targets,
        force=force,
        polarity=polarity,
        roles=roles,
        condition_values=condition_values,
        exception_values=exception_values,
        semantic_atoms=semantic_atoms,
    )

    phrases: List[DecodedModalPhrase] = []
    if semantic_surface:
        phrases.append(
            DecodedModalPhrase(
                text=semantic_surface,
                slot="typed_ir_semantic_surface_reconstruction",
                spans=spans,
                provenance_only=provenance_only,
            )
        )
    if source_semantic_sentence:
        phrases.append(
            DecodedModalPhrase(
                text=source_semantic_sentence,
                slot="typed_ir_source_semantic_sentence",
                spans=spans,
                provenance_only=provenance_only,
            )
        )
    if normative_status_narrative:
        phrases.append(
            DecodedModalPhrase(
                text=normative_status_narrative,
                slot="typed_ir_normative_status_narrative",
                spans=spans,
                provenance_only=provenance_only,
            )
        )
    if semantic_reconstruction_clause:
        phrases.append(
            DecodedModalPhrase(
                text=semantic_reconstruction_clause,
                slot="typed_ir_semantic_reconstruction_clause",
                spans=spans,
                provenance_only=provenance_only,
            )
        )
    for scope_frame_text in scope_frame_texts:
        phrases.append(
            DecodedModalPhrase(
                text=scope_frame_text,
                slot="typed_ir_scope_frame_reconstruction",
                spans=spans,
                provenance_only=provenance_only,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=_slot_safe_family_pair_key(scope_frame_text),
                slot="typed_ir_scope_frame_signature",
                spans=spans,
                provenance_only=True,
            )
        )
    if summary:
        phrases.append(
            DecodedModalPhrase(
                text=summary,
                slot="typed_ir_reconstruction",
                spans=spans,
                provenance_only=provenance_only,
            )
        )
    clause_role_support = _typed_ir_clause_role_support_text(
        predicate_text=predicate_text,
        roles=roles,
        semantic_atoms=semantic_atoms,
        condition_values=condition_values,
        exception_values=exception_values,
    )
    if clause_role_support:
        phrases.append(
            DecodedModalPhrase(
                text=clause_role_support,
                slot="typed_ir_clause_role_support",
                spans=spans,
                provenance_only=provenance_only,
            )
        )
    for value in support_values[:max_values]:
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot="typed_ir_semantic_support",
                spans=spans,
                provenance_only=provenance_only,
            )
        )
    if semantic_atoms:
        phrases.append(
            DecodedModalPhrase(
                text=_bounded_reconstruction_text(
                    (_humanize_typed_ir_value(atom) for atom in semantic_atoms),
                    max_tokens=24,
                ),
                slot="typed_ir_compact_semantic_support",
                spans=spans,
                provenance_only=provenance_only,
            )
        )
        if "transferred" in semantic_atoms:
            phrases.append(
                DecodedModalPhrase(
                    text="Transferred",
                    slot="typed_ir_compact_semantic_support",
                    spans=spans,
                    provenance_only=provenance_only,
                )
            )
    for value in legal_ir_view_support:
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot="typed_ir_legal_view_support",
                spans=spans,
                provenance_only=True,
            )
        )
    phrases.extend(
        _typed_ir_semantic_bridge_phrases(
            family=family,
            targets=ordered_targets,
            force=force,
            polarity=polarity,
            predicate_text=predicate_text,
            roles=roles,
            condition_values=condition_values,
            exception_values=exception_values,
            semantic_atoms=semantic_atoms,
            legal_ir_view_support=legal_ir_view_support,
            spans=spans,
            provenance_only=provenance_only,
        )
    )
    if family and targets:
        for target in targets:
            pair = f"{family}->{target}"
            pair_label = _typed_ir_family_pair_reconstruction_label(family, target)
            phrases.append(
                DecodedModalPhrase(
                    text=pair,
                    slot="typed_ir_cross_family_semantic_support",
                    spans=spans,
                    provenance_only=True,
                )
            )
            if pair_label:
                phrases.append(
                    DecodedModalPhrase(
                        text=pair_label,
                        slot="typed_ir_family_pair_reconstruction_support",
                        spans=spans,
                        provenance_only=provenance_only,
                    )
                )
            if heading_text or fallback_text:
                phrases.append(
                    DecodedModalPhrase(
                        text=f"{pair}:heading",
                        slot="typed_decompiler_family_pair_cue",
                        spans=spans,
                        provenance_only=True,
                    )
                )
            reconstruction_text = _typed_ir_family_pair_semantic_reconstruction_text(
                source_family=family,
                target_family=target,
                support_values=support_values,
                legal_ir_view_support=_typed_ir_guided_pair_view_support_values(
                    document=document,
                    source_family=family,
                    target_family=target,
                ),
                semantic_atoms=semantic_atoms,
                max_tokens=32,
            )
            bridge_label = _typed_ir_family_pair_bridge_label(family, target)
            if bridge_label:
                phrases.append(
                    DecodedModalPhrase(
                        text=bridge_label,
                        slot="typed_ir_family_pair_semantic_bridge",
                        spans=spans,
                        provenance_only=provenance_only,
                    )
                )
            if reconstruction_text:
                phrases.append(
                    DecodedModalPhrase(
                        text=reconstruction_text,
                        slot="typed_ir_family_pair_semantic_reconstruction",
                        spans=spans,
                        provenance_only=provenance_only,
                    )
                )
            policy_view_text = _typed_ir_policy_view_semantic_reconstruction_text(
                document=document,
                source_family=family,
                target_family=target,
                force=force,
                polarity=polarity,
                roles=roles,
                semantic_atoms=semantic_atoms,
                legal_ir_view_support=legal_ir_view_support,
                support_values=support_values,
                max_tokens=40,
            )
            if policy_view_text:
                phrases.append(
                    DecodedModalPhrase(
                        text=policy_view_text,
                        slot="typed_ir_policy_view_semantic_reconstruction",
                        spans=spans,
                        provenance_only=provenance_only,
                    )
                )
            target_view_clause = _typed_ir_target_view_semantic_clause_text(
                document=document,
                source_family=family,
                target_family=target,
                force=force,
                polarity=polarity,
                predicate_text=predicate_text,
                roles=roles,
                condition_values=condition_values,
                exception_values=exception_values,
                semantic_atoms=semantic_atoms,
                legal_ir_view_support=legal_ir_view_support,
                support_values=support_values,
                max_tokens=44,
            )
            if target_view_clause:
                phrases.append(
                    DecodedModalPhrase(
                        text=target_view_clause,
                        slot="typed_ir_target_view_semantic_clause",
                        spans=spans,
                        provenance_only=provenance_only,
                    )
                )
    return phrases


def _typed_ir_scope_frame_texts(
    *,
    source_family: str,
    targets: Sequence[str],
    force: str,
    polarity: str,
    roles: Mapping[str, str],
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    semantic_atoms: Sequence[str],
    max_tokens: int = 28,
) -> List[str]:
    """Render family-target scope frames from typed clauses and roles."""
    source = _clean_text(source_family).lower()
    if not source:
        return []
    normalized_targets = [
        _clean_text(target).lower()
        for target in targets
        if _clean_text(target).lower()
    ]
    if not normalized_targets:
        normalized_targets = [source]

    condition_scopes = _typed_clause_scope_units(
        condition_values,
        clause_type="condition",
    )
    exception_scopes = _typed_clause_scope_units(
        exception_values,
        clause_type="exception",
    )
    has_temporal_scope = any(scope["temporal_relation"] for scope in condition_scopes)
    has_condition_scope = bool(condition_scopes or exception_scopes)
    has_frame_self_scope = (
        source == "frame"
        and "frame" in normalized_targets
        and bool(roles or semantic_atoms)
    )
    if not has_condition_scope and not any(
        target in {"conditional_normative", "temporal"} for target in normalized_targets
    ) and not has_frame_self_scope:
        return []

    subject = _humanize_typed_ir_value(roles.get("subject", ""))
    action = _humanize_typed_ir_value(roles.get("action", ""))
    object_value = _humanize_typed_ir_value(roles.get("object", ""))
    temporal = _humanize_typed_ir_value(roles.get("temporal", ""))
    atom_values = [
        _humanize_typed_ir_value(atom)
        for atom in semantic_atoms
        if atom
        not in {
            "exception_or_condition",
            "obligation",
            "permission",
            "prohibition",
            "temporal_condition",
        }
    ]
    texts: List[str] = []

    def add_text(parts: Sequence[str]) -> None:
        text = _bounded_reconstruction_text(parts, max_tokens=max_tokens)
        if text and text not in texts:
            texts.append(text)

    for target in normalized_targets:
        if target == "conditional_normative" and has_condition_scope:
            parts: List[str] = [
                _typed_ir_family_pair_reconstruction_label(source, target),
                f"{force} force" if force else "",
                polarity.replace("_", " ") if polarity != "positive_scope" else "",
                "conditioned legal scope",
                subject,
                action,
                object_value,
            ]
            for scope in condition_scopes[:2]:
                parts.extend(
                    (
                        scope["prefix"],
                        scope["value"],
                    )
                )
            for scope in exception_scopes[:2]:
                parts.extend(("except", scope["value"]))
            parts.extend(atom_values[:3])
            add_text(parts)
        if target == "temporal" and (has_temporal_scope or temporal):
            parts = [
                _typed_ir_family_pair_reconstruction_label(source, target),
                f"{force} force" if force else "",
                "temporal deadline scope",
                subject,
                action,
                object_value,
                temporal,
            ]
            for scope in condition_scopes[:3]:
                if scope["temporal_relation"]:
                    parts.extend(
                        (
                            scope["temporal_relation"],
                            scope["prefix"],
                            scope["value"],
                        )
                    )
            parts.extend(atom_values[:3])
            add_text(parts)
        if target == "frame" and source == "frame":
            parts = [
                _typed_ir_family_pair_reconstruction_label(source, target),
                "frame scope",
                subject,
                action,
                object_value,
                *(scope["value"] for scope in condition_scopes[:2]),
                *(scope["value"] for scope in exception_scopes[:2]),
                *atom_values[:4],
            ]
            add_text(parts)
    return texts


def _typed_clause_scope_units(
    clauses: Sequence[str],
    *,
    clause_type: str,
) -> List[Dict[str, str]]:
    """Return normalized prefix/value units for reconstruction scope text."""
    units: List[Dict[str, str]] = []
    slot = "condition" if clause_type == "condition" else "exception"
    for clause in clauses:
        cleaned = _clean_text(clause)
        if not cleaned:
            continue
        parsed = _typed_clause_slot(cleaned, slot=slot)
        if parsed is None and slot == "exception":
            parsed = _typed_clause_slot(cleaned, slot="condition")
        if parsed is None:
            prefix_text = slot
            prefix_key = slot
            scoped_value = cleaned
        else:
            prefix_text, prefix_key, scoped_value = parsed
            scoped_value = scoped_value or cleaned
        units.append(
            {
                "prefix": prefix_text.replace("_", " "),
                "prefix_key": prefix_key,
                "temporal_relation": _temporal_clause_prefix_relation(prefix_key),
                "value": scoped_value,
            }
        )
    return units


def _typed_ir_semantic_bridge_phrases(
    *,
    family: str,
    targets: Sequence[str],
    force: str,
    polarity: str,
    predicate_text: str,
    roles: Mapping[str, str],
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    semantic_atoms: Sequence[str],
    legal_ir_view_support: Sequence[str],
    spans: List[List[int]],
    provenance_only: bool,
    max_tokens: int = 56,
) -> List[DecodedModalPhrase]:
    """Emit compact non-provenance bridge text for deontic/frame residuals."""
    normalized_family = _clean_text(family).lower()
    if not normalized_family or not targets:
        return []
    normalized_targets = [
        _clean_text(target).lower()
        for target in targets
        if _clean_text(target).lower()
    ]
    if not normalized_targets:
        return []
    if normalized_family not in {"deontic", "dynamic", "frame"} and not any(
        target in {"deontic", "dynamic", "frame"} for target in normalized_targets
    ):
        return []

    phrases: List[DecodedModalPhrase] = []
    predicate_head = _typed_decompiler_predicate_head_text(predicate_text)
    bridge_atoms = [
        atom
        for atom in semantic_atoms
        if atom
        not in {
            "exception_or_condition",
            "obligation",
            "permission",
            "prohibition",
            "temporal_condition",
        }
    ]
    role_values = [
        f"{role} {_humanize_typed_ir_value(roles.get(role, ''))}"
        for role in ("subject", "action", "object", "temporal")
        if roles.get(role, "")
    ]
    scope_values: List[str] = []
    for value in condition_values[:2]:
        cleaned = _humanize_typed_ir_value(value)
        if cleaned:
            scope_values.append(f"condition {cleaned}")
    for value in exception_values[:2]:
        cleaned = _humanize_typed_ir_value(value)
        if cleaned:
            scope_values.append(f"exception {cleaned}")
    view_values = [
        value
        for value in legal_ir_view_support
        if value
        and (
            "deontic" in value
            or "prover" in value
            or "event calculus" in value
            or "knowledge graph" in value
        )
    ]

    for target in normalized_targets:
        pair = f"{normalized_family}->{target}"
        if normalized_family == target and target not in {"deontic", "frame"}:
            continue
        parts = [
            _typed_ir_family_pair_reconstruction_label(normalized_family, target),
            f"{force} force" if force else "",
            polarity.replace("_", " ") if polarity else "",
            predicate_head,
            *(_humanize_typed_ir_value(atom) for atom in bridge_atoms[:6]),
            *role_values[:4],
            *scope_values[:4],
            *view_values[:3],
        ]
        text = _bounded_reconstruction_text(parts, max_tokens=max_tokens)
        if not text:
            continue
        phrases.append(
            DecodedModalPhrase(
                text=text,
                slot="typed_ir_semantic_bridge_reconstruction",
                spans=spans,
                provenance_only=provenance_only,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=f"{pair}:{force}:{polarity}",
                slot="typed_ir_semantic_bridge_signature",
                spans=spans,
                provenance_only=True,
            )
        )
        for atom in bridge_atoms[:8]:
            phrases.append(
                DecodedModalPhrase(
                    text=f"{atom}:{pair}",
                    slot="typed_ir_semantic_bridge_atom_pair",
                    spans=spans,
                    provenance_only=True,
                )
            )
    return phrases


def _guided_semantic_reconstruction_phrases(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    typed_phrases: Sequence[DecodedModalPhrase],
) -> List[DecodedModalPhrase]:
    """Promote one typed semantic clause when guidance flags decoder residuals."""
    if not _should_emit_guided_semantic_reconstruction(document):
        return []
    source_text = _formula_source_span_text(document=document, formula=formula)
    if not source_text:
        source_text = str(document.normalized_text or "")
    if not _clean_text(source_text):
        return []
    candidate = _guided_semantic_reconstruction_text(
        document=document,
        source_text=source_text,
        typed_phrases=typed_phrases,
    )
    if not candidate:
        return []
    return [
        DecodedModalPhrase(
            text=candidate,
            slot="guided_typed_ir_semantic_reconstruction",
            spans=[[formula.provenance.start_char, formula.provenance.end_char]],
            provenance_only=False,
        )
    ]


def _should_emit_guided_semantic_reconstruction(document: ModalIRDocument) -> bool:
    """Return whether packet evidence asks text to include typed IR semantics."""
    for entry in _autoencoder_guidance_entries(document):
        sources: List[Mapping[str, Any]] = [entry]
        for key in ("bundle", "semantic_bundle", "vector_bundle", "program_bundle"):
            nested = _autoencoder_guidance_nested_mapping(entry.get(key))
            if nested is not None:
                sources.append(nested)
        for source in sources:
            action = _clean_text(str(source.get("action") or "")).lower()
            target_component = _clean_text(
                str(source.get("target_component") or source.get("target") or "")
            ).lower()
            scope = _clean_text(
                str(
                    source.get("program_synthesis_scope")
                    or source.get("target_file_lane")
                    or source.get("scope")
                    or ""
                )
            ).lower()
            bridge_failure = _clean_text(
                str(source.get("bridge_failure_name") or "")
            ).lower()
            if (
                action
                in {
                    "refine_semantic_decompiler_reconstruction",
                    "refine_typed_ir_or_decompiler_slots",
                }
                and (
                    target_component == "modal.ir_decompiler"
                    or scope == "ir_decompiler"
                )
            ):
                return True
            if (
                scope == "ir_decompiler"
                and bridge_failure.startswith("source_decompiled_text_")
            ):
                return True
    return False


def _guided_semantic_reconstruction_text(
    *,
    document: ModalIRDocument,
    source_text: str,
    typed_phrases: Sequence[DecodedModalPhrase],
    max_tokens: int = 36,
) -> str:
    source_tokens = set(_tokenize_for_similarity(source_text))
    preferred_slots = (
        "typed_ir_policy_view_semantic_reconstruction",
        "typed_ir_family_pair_semantic_reconstruction",
        "typed_ir_semantic_bridge_reconstruction",
        "typed_ir_semantic_reconstruction_clause",
        "typed_ir_source_semantic_sentence",
        "typed_ir_semantic_surface_reconstruction",
        "typed_ir_reconstruction",
    )
    target_terms = _guided_semantic_reconstruction_target_terms(document)
    candidates: List[Tuple[int, int, int, int, str]] = []
    for phrase in typed_phrases:
        slot = _clean_text(phrase.slot)
        if slot not in preferred_slots:
            continue
        text = _clean_text(phrase.text)
        if not text:
            continue
        candidate_tokens = set(_tokenize_for_similarity(text))
        if not candidate_tokens:
            continue
        new_signal = candidate_tokens - source_tokens
        if len(new_signal) < 2:
            continue
        try:
            slot_rank = preferred_slots.index(slot)
        except ValueError:
            slot_rank = len(preferred_slots)
        target_rank = 3
        target_term_rank = len(target_terms)
        lowered_text = text.lower()
        for term_index, target_term in enumerate(target_terms):
            target_tokens = set(_tokenize_for_similarity(target_term))
            is_pair_term = (
                " source reconstructs " in target_term
                or " source reconstruction" in target_term
            )
            if is_pair_term:
                if target_term in lowered_text:
                    target_rank = 0
                    target_term_rank = min(target_term_rank, term_index)
                    break
                continue
            if target_term in lowered_text:
                target_rank = min(target_rank, 1)
                target_term_rank = min(target_term_rank, term_index)
            elif target_tokens and target_tokens.issubset(candidate_tokens):
                target_rank = min(target_rank, 2)
                target_term_rank = min(target_term_rank, term_index)
        candidates.append(
            (target_rank, target_term_rank, slot_rank, -len(new_signal), text)
        )
    if not candidates:
        return ""
    _target_rank, _term_rank, _slot_rank, _signal_rank, text = sorted(candidates)[0]
    return _bounded_reconstruction_text((text,), max_tokens=max_tokens)


def _guided_semantic_reconstruction_target_terms(
    document: ModalIRDocument,
) -> List[str]:
    """Return target labels that should dominate residual-guided reconstruction."""
    terms: List[str] = []

    def add(value: str) -> None:
        cleaned = _clean_text(value).lower()
        if cleaned and cleaned not in terms:
            terms.append(cleaned)

    for target in _autoencoder_target_family_guidance_values(document):
        add(_typed_ir_target_family_label(target))
    for entry in _autoencoder_guidance_entries(document):
        predicted = _slot_safe_family_key(
            _clean_text(str(entry.get("predicted_family") or "")).lower()
        )
        target = _slot_safe_family_key(
            _clean_text(str(entry.get("target_family") or "")).lower()
        )
        if target:
            add(_typed_ir_target_family_label(target))
        if predicted and target:
            add(_typed_ir_family_pair_reconstruction_label(predicted, target))
    for pair in _autoencoder_family_pair_guidance_values(document):
        source, target = pair.split("->", 1)
        add(_typed_ir_target_family_label(target))
        add(_typed_ir_family_pair_reconstruction_label(source, target))
    return terms


def _typed_decompiler_predicate_head_text(predicate_text: str) -> str:
    normalized = _clean_text(predicate_text).replace("_", " ")
    tokens = _tokenize_for_similarity(normalized)
    if not tokens:
        return ""
    return " ".join(tokens[:4])
def _typed_ir_family_pair_semantic_reconstruction_text(
    *,
    source_family: str,
    target_family: str,
    support_values: Sequence[str],
    legal_ir_view_support: Sequence[str],
    semantic_atoms: Sequence[str],
    max_tokens: int,
) -> str:
    pair_label = _typed_ir_family_pair_reconstruction_label(
        source_family,
        target_family,
    )
    if not pair_label:
        return ""
    support_text = [
        value
        for value in (
            *legal_ir_view_support,
            *(_humanize_typed_ir_value(atom) for atom in semantic_atoms),
            *support_values,
        )
        if _clean_text(value)
    ]
    return _bounded_reconstruction_text(
        (pair_label, *support_text),
        max_tokens=max_tokens,
    )


def _typed_ir_family_pair_bridge_label(source_family: str, target_family: str) -> str:
    """Render high-signal semantic bridges for packet-level family pairs."""
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    pair = f"{source}->{target}"
    labels = {
        "conditional_normative->deontic": (
            "conditional legal rule reconstructs deontic obligation"
        ),
        "conditional_normative->conditional_normative": (
            "conditional legal rule preserves conditioned obligation"
        ),
        "deontic->conditional_normative": (
            "deontic duty reconstructs conditioned legal obligation"
        ),
        "deontic->deontic": "deontic duty preserves legal obligation",
        "deontic->dynamic": "deontic permission reconstructs dynamic action",
        "deontic->frame": "deontic duty reconstructs legal frame",
        "deontic->temporal": "deontic duty reconstructs temporal deadline",
        "dynamic->deontic": "dynamic action reconstructs deontic duty",
        "dynamic->dynamic": "dynamic action preserves transfer event",
        "frame->conditional_normative": (
            "legal frame reconstructs conditional obligation"
        ),
        "frame->deontic": "legal frame reconstructs deontic duty",
        "frame->doxastic": "legal frame reconstructs belief and intent state",
        "frame->dynamic": "legal frame reconstructs dynamic action",
        "frame->epistemic": "legal frame reconstructs knowledge finding",
        "frame->frame": "legal frame preserves ontology frame",
        "frame->temporal": "legal frame reconstructs temporal deadline",
        "temporal->deontic": "temporal rule reconstructs deontic duty",
        "temporal->temporal": "temporal rule preserves deadline period",
    }
    return labels.get(pair, "")
def _typed_ir_policy_view_semantic_reconstruction_text(
    *,
    document: ModalIRDocument,
    source_family: str,
    target_family: str,
    force: str,
    polarity: str,
    roles: Mapping[str, str],
    semantic_atoms: Sequence[str],
    legal_ir_view_support: Sequence[str],
    support_values: Sequence[str],
    max_tokens: int,
) -> str:
    """Render typed cross-family policy semantics with LegalIR view anchors."""
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    if not source or not target:
        return ""

    pair_label = _typed_ir_family_pair_reconstruction_label(source, target)
    if not pair_label:
        return ""

    parts: List[str] = []

    def add(value: str) -> None:
        cleaned = _humanize_typed_ir_value(value)
        if cleaned and cleaned not in parts:
            parts.append(cleaned)

    add(pair_label)
    add(_typed_ir_target_family_label(target))
    if force in {"obligation", "permission", "prohibition", "frame", "knowledge"}:
        add(force)
    if polarity and polarity != "positive_scope":
        add(polarity)

    for view_label in _typed_ir_guided_pair_view_support_values(
        document=document,
        source_family=source,
        target_family=target,
    ):
        add(view_label)
    for atom in semantic_atoms[:5]:
        add(atom)
    for role in ("subject", "action", "object", "temporal"):
        value = roles.get(role, "")
        if value:
            add(value)
    for view in _typed_decompiler_family_pair_legal_ir_views(source, target):
        add(_legal_ir_view_semantic_label(view))
    for view_label in legal_ir_view_support[:4]:
        add(view_label)
    for value in support_values[:4]:
        add(value)

    if len(parts) <= 2:
        return ""
    return _bounded_reconstruction_text(parts, max_tokens=max_tokens)


def _typed_ir_target_view_semantic_clause_text(
    *,
    document: ModalIRDocument,
    source_family: str,
    target_family: str,
    force: str,
    polarity: str,
    predicate_text: str,
    roles: Mapping[str, str],
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    semantic_atoms: Sequence[str],
    legal_ir_view_support: Sequence[str],
    support_values: Sequence[str],
    max_tokens: int,
) -> str:
    """Render target-view legal semantics as a compact clause."""
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    if not source or target not in {
        "conditional_normative",
        "deontic",
        "doxastic",
        "dynamic",
        "frame",
        "temporal",
    }:
        return ""

    parts: List[str] = []

    def add(value: str) -> None:
        cleaned = _humanize_typed_ir_value(value)
        if cleaned:
            parts.append(cleaned)

    pair_label = (
        _typed_ir_family_pair_bridge_label(source, target)
        or _typed_ir_family_pair_reconstruction_label(source, target)
    )
    add(pair_label)
    for view_label in _typed_ir_guided_pair_view_support_values(
        document=document,
        source_family=source,
        target_family=target,
    ):
        add(view_label)

    subject = roles.get("subject", "")
    action = roles.get("action", "")
    object_value = roles.get("object", "")
    temporal = roles.get("temporal", "")
    predicate_head = _typed_decompiler_predicate_head_text(predicate_text)

    if target == "conditional_normative":
        first_condition = (
            _clean_text(condition_values[0]).lower() if condition_values else ""
        )
        if not first_condition.startswith(
            ("if ", "unless ", "except ", "provided ", "subject to ")
        ):
            add("if")
        for condition in condition_values[:2]:
            add(condition)
        for exception in exception_values[:2]:
            add("except")
            add(exception)
            add(subject)
    elif target == "temporal":
        first_temporal = _clean_text(
            temporal or (condition_values[0] if condition_values else "")
        ).lower()
        if not first_temporal.startswith(
            (
                "after ",
                "before ",
                "by ",
                "no later ",
                "not later ",
                "until ",
                "when ",
                "within ",
            )
        ):
            add("when")
        add(temporal)
        for condition in condition_values[:2]:
            add(condition)
        add("deadline period")
        add(subject)
    elif target == "deontic":
        add(subject)
        source_support_tokens = {
            token
            for value in support_values
            for token in _tokenize_for_similarity(value)
        }
        if source_support_tokens.intersection({"shall", "must", "required"}):
            add("shall")
        elif source_support_tokens.intersection({"may", "authorized", "permitted"}):
            add("may")
        elif force == "permission":
            add("may")
        elif force == "prohibition" or polarity == "negative_scope":
            add("must not")
        elif force == "obligation":
            add("shall")
        else:
            add("legal duty")
    elif target == "doxastic":
        add("belief intent knowledge state")
        add(subject)
        if force == "knowledge":
            add("knowledge finding")
        else:
            add("belief state")
    elif target == "frame":
        add("legal frame")
        add(subject)
    elif target == "dynamic":
        add("dynamic action")
        if force == "permission":
            add("may")
        add(subject)

    add(action)
    add(object_value)
    if not (subject or action or object_value):
        add(predicate_head or predicate_text)

    if force in {"obligation", "permission", "prohibition"}:
        add(force)
    if polarity == "negative_scope":
        add("negative scope")

    for atom in semantic_atoms[:6]:
        add(atom)
    for view in _typed_decompiler_family_pair_legal_ir_views(source, target):
        add(_legal_ir_view_semantic_label(view))
    for view_label in legal_ir_view_support[:4]:
        add(view_label)
    for value in support_values[:4]:
        add(value)

    if len(parts) <= 2:
        return ""
    return _bounded_surface_text(parts, max_tokens=max_tokens)


def _typed_ir_reconstruction_cue_support_values(
    *,
    formula: ModalIRFormula,
    text: str,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
) -> List[str]:
    cues: List[str] = []

    def add(value: str) -> None:
        cleaned = _clean_text(value).replace("_", " ")
        if cleaned and cleaned not in cues:
            cues.append(cleaned)

    for cue in _formula_cues(formula):
        add(cue)
    for cue in _typed_decompiler_condition_cues(
        condition_values=condition_values,
        exception_values=exception_values,
        text=text,
    ):
        add(cue)
    for cue in _bridge_cues_from_text(text):
        add(cue)
    for cue in _definition_condition_support_values(text):
        add(cue)
    for cue in list(cues):
        force = _typed_decompiler_force_for_cue(cue)
        if force:
            add(f"{cue} {force}")
        temporal_relation = _temporal_clause_prefix_relation(cue.replace(" ", "_"))
        if temporal_relation:
            add(f"{cue} temporal {temporal_relation}")
    return cues


def _typed_ir_clause_role_support_text(
    *,
    predicate_text: str,
    roles: Mapping[str, str],
    semantic_atoms: Sequence[str],
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    max_tokens: int = 48,
) -> str:
    """Render compact clause topology from typed IR fields, not raw spans."""
    parts: List[str] = []

    def add(value: str) -> None:
        cleaned = _clean_text(value).replace("_", " ")
        if cleaned:
            parts.append(cleaned)

    add("source clause")
    add(predicate_text)
    for role in ("subject", "action", "object", "temporal"):
        value = roles.get(role, "")
        if value:
            add(role)
            add(value)
    for label, values in (
        ("condition", condition_values),
        ("exception", exception_values),
    ):
        for value in values[:2]:
            add(label)
            add(value)
    if semantic_atoms:
        add("semantic")
        for atom in semantic_atoms[:6]:
            add(atom)
    return _bounded_reconstruction_text(parts, max_tokens=max_tokens)


def _typed_ir_role_reconstruction_values(
    roles: Mapping[str, str],
) -> List[str]:
    """Return compact role labels before generic support truncation."""
    values: List[str] = []
    for role in ("subject", "action", "object", "temporal"):
        value = _clean_text(roles.get(role, "")).replace("_", " ")
        if not value:
            continue
        role_text = f"{role} {value}"
        if role_text not in values:
            values.append(role_text)
    return values


def _typed_ir_semantic_surface_reconstruction_text(
    *,
    predicate_text: str,
    roles: Mapping[str, str],
    force: str,
    polarity: str,
    cue_values: Sequence[str],
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    semantic_atoms: Sequence[str],
    targets: Sequence[str],
    max_tokens: int = 56,
) -> str:
    """Render typed IR roles as a source-like clause without copying spans."""
    parts: List[str] = []

    def add(value: str) -> None:
        cleaned = _clean_text(value).replace("_", " ")
        if cleaned:
            parts.append(cleaned)

    subject = roles.get("subject", "")
    action = roles.get("action", "")
    object_value = roles.get("object", "")
    temporal = roles.get("temporal", "")
    has_deontic_target = any(
        _clean_text(target).lower() == "deontic" for target in targets
    )
    has_conditional_target = any(
        _clean_text(target).lower() == "conditional_normative" for target in targets
    )
    has_temporal_target = any(
        _clean_text(target).lower() == "temporal" for target in targets
    )
    has_dynamic_target = any(
        _clean_text(target).lower() == "dynamic" for target in targets
    )
    normalized_cues = {
        _clean_text(cue).lower().replace(" ", "_") for cue in cue_values
    }

    if has_conditional_target and condition_values:
        add("conditioned on")
    for condition in condition_values[:3]:
        add(condition)
    add(subject)
    if has_deontic_target:
        if force == "permission" or normalized_cues & {"may", "authorized", "permit"}:
            add("may")
        elif force == "prohibition":
            add("must not")
        elif force == "obligation":
            add("shall")
        elif polarity == "negative_scope":
            add("must not")
    add(action)
    add(object_value)
    if not (subject or action or object_value):
        add(predicate_text)
    if has_dynamic_target:
        add("dynamic action")
    if has_temporal_target and temporal:
        add("during")
        add(temporal)
    for exception in exception_values[:2]:
        add("except")
        add(exception)
    for atom in semantic_atoms[:4]:
        add(atom)
    return _bounded_surface_text(parts, max_tokens=max_tokens)


def _typed_ir_source_semantic_sentence_text(
    *,
    source_family: str,
    roles: Mapping[str, str],
    force: str,
    polarity: str,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    semantic_atoms: Sequence[str],
    targets: Sequence[str],
    max_tokens: int = 48,
    include_family_pair_labels: bool = False,
) -> str:
    """Render source-like legal semantics from typed slots, not raw spans."""
    parts: List[str] = []

    def add(value: str) -> None:
        cleaned = _humanize_typed_ir_value(value)
        if cleaned:
            parts.append(cleaned)

    target_set = {_clean_text(target).lower() for target in targets}
    normalized_source = _clean_text(source_family).lower()
    has_conditional_scope = bool(condition_values or exception_values)
    if "conditional_normative" in target_set and "deontic" in target_set:
        add("conditional legal duty")
    elif "conditional_normative" in target_set and "frame" in target_set:
        add("conditional legal frame")
    elif "conditional_normative" in target_set:
        add("conditional legal rule")
    elif "deontic" in target_set:
        add("legal duty")
    elif "temporal" in target_set:
        add("temporal legal rule")
    elif "dynamic" in target_set:
        add("dynamic legal action")
    elif "frame" in target_set:
        add("legal frame")

    if include_family_pair_labels and normalized_source:
        for target in targets[:4]:
            target_family = _clean_text(target).lower()
            if not target_family:
                continue
            add(
                _typed_ir_source_family_pair_surface_label(
                    normalized_source,
                    target_family,
                )
            )
            add(
                _typed_ir_family_pair_reconstruction_label(
                    normalized_source,
                    target_family,
                )
            )

    if force in {"obligation", "permission", "prohibition"}:
        add(force)
    if polarity == "negative_scope":
        add("negative scope")

    if has_conditional_scope:
        add("conditioned on")
        for condition in condition_values[:2]:
            add(condition)
        for exception in exception_values[:2]:
            add("except")
            add(exception)

    for role in ("subject", "action", "object", "temporal"):
        value = roles.get(role, "")
        if value:
            add(value)

    if not has_conditional_scope:
        for condition in condition_values[:2]:
            add("condition")
            add(condition)
        for exception in exception_values[:2]:
            add("exception")
            add(exception)
    for atom in semantic_atoms[:6]:
        add(atom)

    if include_family_pair_labels:
        return _bounded_surface_text(parts, max_tokens=max_tokens)
    return _bounded_reconstruction_text(parts, max_tokens=max_tokens)


def _typed_ir_normative_status_narrative_text(
    *,
    source_family: str,
    targets: Sequence[str],
    force: str,
    polarity: str,
    roles: Mapping[str, str],
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    semantic_atoms: Sequence[str],
    status_detail_values: Sequence[str],
    legal_ir_view_support: Sequence[str],
    max_tokens: int = 56,
) -> str:
    """Render high-signal legal status semantics from typed IR slots."""
    family = _clean_text(source_family).lower()
    target_set = {
        _clean_text(target).lower()
        for target in targets
        if _clean_text(target).lower()
    }
    atom_set = {
        _clean_text(atom).lower().replace(" ", "_")
        for atom in semantic_atoms
        if _clean_text(atom)
    }
    has_status_signal = bool(status_detail_values) or bool(
        atom_set.intersection(
            {
                "editorial_reclassification",
                "editorial_transfer_status",
                "transferred",
                "reclassified",
                "repealed",
                "omitted",
                "reserved",
            }
        )
    )
    has_normative_signal = bool(
        target_set.intersection({"conditional_normative", "deontic", "frame"})
        or family in {"conditional_normative", "deontic", "frame"}
        or condition_values
        or exception_values
        or force in {"obligation", "permission", "prohibition"}
    )
    if not (has_status_signal or has_normative_signal):
        return ""

    parts: List[str] = []

    def add(value: str) -> None:
        cleaned = _humanize_typed_ir_value(value)
        if cleaned and cleaned not in parts:
            parts.append(cleaned)

    if has_status_signal:
        add("legal status")
    elif "conditional_normative" in target_set:
        add("conditional legal status")
    elif "deontic" in target_set:
        add("deontic legal status")
    elif "frame" in target_set:
        add("frame legal status")

    if family:
        add(_typed_ir_target_family_label(family))
    for target in targets[:4]:
        add(_typed_ir_target_family_label(target))
        bridge_label = _typed_ir_family_pair_bridge_label(family, target)
        if bridge_label:
            add(bridge_label)

    if force in {"obligation", "permission", "prohibition"}:
        add(force)
    if polarity == "negative_scope":
        add("negative scope")

    if condition_values or exception_values:
        add("conditioned scope")
    for condition in condition_values[:2]:
        add(condition)
    for exception in exception_values[:2]:
        add("except")
        add(exception)

    for atom in semantic_atoms[:8]:
        add(atom)
    for value in status_detail_values[:6]:
        add(value)
    for view_support in legal_ir_view_support[:4]:
        add(view_support)
    for role in ("subject", "action", "object", "temporal"):
        value = roles.get(role, "")
        if value:
            add(role)
            add(value)

    if len(parts) <= 1:
        return ""
    return _bounded_surface_text(parts, max_tokens=max_tokens)


def _typed_ir_semantic_reconstruction_clause_text(
    *,
    family: str,
    targets: Sequence[str],
    force: str,
    polarity: str,
    predicate_text: str,
    roles: Mapping[str, str],
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    semantic_atoms: Sequence[str],
    legal_ir_view_support: Sequence[str],
    max_tokens: int = 56,
) -> str:
    """Render a typed, source-like clause for frame/deontic residuals."""
    normalized_family = _clean_text(family).lower()
    target_values = [
        _clean_text(target).lower()
        for target in targets
        if _clean_text(target).lower()
    ]
    if not normalized_family or not target_values:
        return ""
    if normalized_family not in {"deontic", "dynamic", "frame"} and not any(
        target
        in {"conditional_normative", "deontic", "dynamic", "frame", "temporal"}
        for target in target_values
    ):
        return ""

    parts: List[str] = []

    def add(value: str) -> None:
        cleaned = _humanize_typed_ir_value(value)
        if cleaned:
            parts.append(cleaned)

    pair_labels = [
        _typed_ir_family_pair_reconstruction_label(normalized_family, target)
        for target in target_values
        if _typed_ir_family_pair_reconstruction_label(normalized_family, target)
    ]
    for label in pair_labels[:3]:
        add(label)
    if force in {"obligation", "permission", "prohibition"}:
        add(force)
    if polarity == "negative_scope":
        add("negative scope")

    predicate_head = _typed_decompiler_predicate_head_text(predicate_text)
    add(predicate_head or predicate_text)
    for role in ("subject", "action", "object", "temporal"):
        value = roles.get(role, "")
        if value:
            add(role)
            add(value)
    for condition in condition_values[:2]:
        add("condition")
        add(condition)
    for exception in exception_values[:2]:
        add("exception")
        add(exception)
    for atom in semantic_atoms[:8]:
        add(atom)
    for view_support in legal_ir_view_support[:4]:
        add(view_support)

    return _bounded_reconstruction_text(parts, max_tokens=max_tokens)


def _typed_ir_legal_view_support_values(document: ModalIRDocument) -> List[str]:
    """Return deterministic semantic labels for LegalIR views flagged by evidence."""
    views: List[str] = []

    def add_view(value: Any) -> None:
        view = _clean_text(str(value or ""))
        if view and view not in views:
            views.append(view)

    for entry in _autoencoder_guidance_entries(document):
        for field in ("target_view", "predicted_view", "selected_view"):
            add_view(entry.get(field))
        for view in _legal_ir_view_guidance_features(entry):
            add_view(view)
        for value in _string_list(entry.get("legal_ir_underrepresented_components")):
            add_view(value)
        component_gaps = entry.get("legal_ir_component_gaps")
        if isinstance(component_gaps, Mapping):
            ranked_gaps: List[Tuple[float, str]] = []
            for view, gap in component_gaps.items():
                try:
                    gap_value = float(gap)
                except (TypeError, ValueError):
                    continue
                if gap_value > 0:
                    ranked_gaps.append((gap_value, _clean_text(str(view))))
            for _gap, view in sorted(ranked_gaps, reverse=True):
                add_view(view)

    labels: List[str] = []
    for view in views:
        label = _legal_ir_view_semantic_label(view)
        if label and label not in labels:
            labels.append(label)
    return labels


def _typed_ir_guided_pair_view_support_values(
    *,
    document: ModalIRDocument,
    source_family: str,
    target_family: str,
) -> List[str]:
    """Return target-view labels tied to one guided source/target family pair."""
    source = _slot_safe_family_key(_clean_text(source_family).lower())
    target = _slot_safe_family_key(_clean_text(target_family).lower())
    if not source or not target:
        return []
    pair = f"{source}->{target}"
    views: List[str] = []

    def add_view(value: Any) -> None:
        view = _clean_text(str(value or ""))
        if view and view not in views:
            views.append(view)

    def source_mappings(entry: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        sources: List[Mapping[str, Any]] = [entry]
        for key in ("bundle", "semantic_bundle", "vector_bundle", "program_bundle"):
            nested = _autoencoder_guidance_nested_mapping(entry.get(key))
            if nested is not None:
                sources.append(nested)
        return sources

    def mapping_pairs(mapping: Mapping[str, Any]) -> List[str]:
        pairs: List[str] = []

        def add_pair(value: Any) -> None:
            text = _clean_text(str(value or "")).lower().replace(" ", "")
            if "->" not in text:
                return
            left, right = text.split("->", 1)
            left = _slot_safe_family_key(left)
            right = _slot_safe_family_key(right)
            if left and right:
                rendered = f"{left}->{right}"
                if rendered not in pairs:
                    pairs.append(rendered)

        for key in (
            "family_pair",
            "family_pairs",
            "target_family_pair",
            "target_family_pairs",
        ):
            value = mapping.get(key)
            if isinstance(value, str):
                add_pair(value)
            else:
                for item in _string_list(value):
                    add_pair(item)
        return pairs

    for entry in _autoencoder_guidance_entries(document):
        predicted = _slot_safe_family_key(
            _clean_text(str(entry.get("predicted_family") or "")).lower()
        )
        entry_target = _slot_safe_family_key(
            _clean_text(str(entry.get("target_family") or "")).lower()
        )
        explicit_pair_match = any(
            pair in mapping_pairs(source) for source in source_mappings(entry)
        )
        direct_family_match = (
            entry_target == target
            and (not predicted or predicted == source)
        )
        if not explicit_pair_match and not direct_family_match:
            continue
        for field in ("target_view", "selected_view", "predicted_view"):
            add_view(entry.get(field))
        for view in _legal_ir_view_guidance_features(entry):
            add_view(view)
        for view in _string_list(entry.get("legal_ir_underrepresented_components")):
            add_view(view)
        component_gaps = entry.get("legal_ir_component_gaps")
        if isinstance(component_gaps, Mapping):
            ranked_gaps: List[Tuple[float, str]] = []
            for view, gap in component_gaps.items():
                try:
                    gap_value = float(gap)
                except (TypeError, ValueError):
                    continue
                if gap_value > 0:
                    ranked_gaps.append((gap_value, _clean_text(str(view))))
            for _gap, view in sorted(ranked_gaps, reverse=True):
                add_view(view)

    labels: List[str] = []
    for view in views:
        label = _legal_ir_view_semantic_label(view)
        if label and label not in labels:
            labels.append(label)
    return labels


def _legal_ir_view_semantic_label(view: str) -> str:
    normalized = _clean_text(view)
    lowered = normalized.lower()
    labels = {
        "cec.native": "event calculus native legal events",
        "knowledge_graphs.neo4j_compat": "knowledge graph legal relations",
        "tdfol.prover": "typed first order prover obligations",
        "deontic.ir": "deontic legal obligations",
        "modal.frame_logic": "frame logic ontology",
        "modal.autoencoder": "modal autoencoder reconstruction",
    }
    if lowered in labels:
        return labels[lowered]
    return normalized.replace(".", " ").replace("_", " ")


def _typed_ir_target_family_label(target: str) -> str:
    normalized = _clean_text(target).lower()
    if normalized == "conditional_normative":
        return "conditional obligation"
    if normalized == "deontic":
        return "obligation permission prohibition"
    if normalized == "epistemic":
        return "knowledge determination finding"
    if normalized == "doxastic":
        return "belief intent knowledge state"
    if normalized == "dynamic":
        return "dynamic action transfer change"
    if normalized == "temporal":
        return "temporal deadline period"
    if normalized == "frame":
        return "legal frame"
    if normalized == "alethic":
        return "capability possibility"
    return normalized.replace("_", " ")


def _typed_ir_family_pair_reconstruction_label(source: str, target: str) -> str:
    source_label = _typed_ir_target_family_label(source)
    target_label = _typed_ir_target_family_label(target)
    if not source_label or not target_label:
        return ""
    normalized_source = _clean_text(source).lower()
    normalized_target = _clean_text(target).lower()
    if normalized_source == normalized_target:
        return f"{target_label} source reconstruction"
    return f"{source_label} source reconstructs {target_label}"


def _typed_ir_source_family_pair_surface_label(source: str, target: str) -> str:
    source_key = _slot_safe_family_key(_clean_text(source).lower())
    target_label = _typed_ir_target_family_label(target)
    if not source_key or not target_label:
        return ""
    if source_key == _slot_safe_family_key(_clean_text(target).lower()):
        return f"{source_key} source reconstruction"
    return f"{source_key} source reconstructs {target_label}"


def _typed_ir_reconstruction_target_order(target: str) -> Tuple[int, str]:
    normalized = _clean_text(target).lower()
    priority = {
        "conditional_normative": 0,
        "epistemic": 1,
        "deontic": 2,
        "dynamic": 3,
        "temporal": 4,
        "frame": 5,
        "doxastic": 6,
        "alethic": 7,
    }
    return priority.get(normalized, 20), normalized


def _humanize_typed_ir_value(value: str) -> str:
    return _clean_text(value).replace("_", " ")


def _bounded_reconstruction_text(
    values: Iterable[str],
    *,
    max_tokens: int,
) -> str:
    tokens: List[str] = []
    seen_tokens: set[str] = set()
    for value in values:
        for token in _tokenize_for_similarity(_humanize_typed_ir_value(value)):
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
            tokens.append(token)
            if len(tokens) >= max_tokens:
                return _clean_text(" ".join(tokens))
    return _clean_text(" ".join(tokens))


def _bounded_surface_text(
    values: Iterable[str],
    *,
    max_tokens: int,
) -> str:
    tokens: List[str] = []
    for value in values:
        cleaned = _clean_text(value).replace("_", " ")
        if not cleaned:
            continue
        tokens.extend(cleaned.split())
        if len(tokens) >= max_tokens:
            return _clean_text(" ".join(tokens[:max_tokens]))
    return _clean_text(" ".join(tokens))


def _legal_semantic_atom_phrases(
    *,
    text: str,
    slot_prefix: str,
    spans: List[List[int]],
) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    prefix = _clean_text(slot_prefix).replace(" ", "_")
    slots = ["legal_semantic_atom"]
    if prefix:
        slots.append(f"{prefix}_legal_semantic_atom")
    for atom in _legal_semantic_atoms_from_text(text):
        for slot in slots:
            phrases.append(
                DecodedModalPhrase(
                    text=atom,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    return phrases


def _legal_semantic_atoms_from_text(text: str) -> List[str]:
    normalized = _clean_text(text).lower()
    if not normalized:
        return []
    tokens = set(_CUE_TOKEN_RE.findall(normalized))
    atoms: List[str] = []
    seen: set[str] = set()

    def add(atom: str) -> None:
        normalized_atom = _clean_text(atom).lower().replace(" ", "_")
        if normalized_atom and normalized_atom not in seen:
            seen.add(normalized_atom)
            atoms.append(normalized_atom)

    for keyword in _USCODE_FALLBACK_STATUS_KEYWORDS:
        if re.search(rf"(?<!\w){re.escape(keyword)}(?:d|ed|s)?(?!\w)", normalized):
            add(keyword)
    if "omitted" in tokens and re.search(r"\b(?:editorial\s+notes|codification)\b", normalized):
        add("uscode_omitted_codification_record")
    if "repealed" in tokens and re.search(
        r"\b(?:pub\.?|public\s+law|stat\.?|section|secs?\.?)\b",
        normalized,
    ):
        add("uscode_repealed_editorial_record")
    for term in _defined_term_atoms_from_text(text):
        add(term)
    if _has_definition_semantics(normalized):
        add("definition")
    if re.search(r"\bthe\s+term\s+director\s+means\b", normalized):
        add("director_government_actor_definition")
        add("director_government_actor")
    if re.search(
        r"\b(?:freely\s+associated\s+states?|compact\s+of\s+free\s+association|"
        r"republic\s+of\s+the\s+marshall\s+islands|"
        r"federated\s+states\s+of\s+micronesia|republic\s+of\s+palau)\b",
        normalized,
    ):
        add("freely_associated_state")
    if re.search(r"\bcompact\s+of\s+free\s+association\b", normalized):
        add("compact_free_association")
    if re.search(
        r"\b(?:members?\s+of\s+congress|the\s+congress)\b.{0,120}"
        r"\b(?:compensation|allowances?)\b|"
        r"\b(?:compensation|allowances?)\b.{0,120}"
        r"\b(?:members?\s+of\s+congress|the\s+congress)\b",
        normalized,
    ):
        add("congressional_member_compensation_allowance")
    if re.search(
        r"\bauthorization\s+of\s+appropriations\b|"
        r"\bauthorized\s+to\s+be\s+appropriated\b|"
        r"\bappropriations\s+are\s+authorized\b",
        normalized,
    ):
        add("appropriation_authorization")
        add("uscode_appropriation_authorization_record")
    if re.search(r"\bnational\s+military\s+parks?\b", normalized):
        add("national_military_park_resource")
    if re.search(r"\bnational\s+security\s+act\s+of\s+1947\b", normalized):
        add("national_security_act_reclassification")
    if re.search(
        r"\b(?:supplemental\s+grants?|additional\s+preventive\s+health\s+services?|"
        r"preventive\s+health\s+services?)\b",
        normalized,
    ):
        add("supplemental_preventive_health_grant")
        add("preventive_health_service_grant")
    if re.search(r"\bdemonstration\s+projects?\b", normalized) and re.search(
        r"\b(?:preventive\s+health|grants?|states?)\b",
        normalized,
    ):
        add("preventive_health_demonstration_project")
    if re.search(
        r"\b(?:medical\s+officer\s+of\s+the\s+marine\s+corps|"
        r"marine\s+corps\b.{0,80}\bmedical\s+officer|"
        r"headquarters,\s+marine\s+corps)\b",
        normalized,
    ):
        add("marine_corps_medical_officer")
        add("marine_corps_headquarters_staff")
    if re.search(
        r"\b(?:vacant\s+military\s+posts?|military\s+posts?\s+or\s+barracks|"
        r"barracks\s+for\s+schools?)\b",
        normalized,
    ):
        add("military_post_school_use")
    if re.search(
        r"\b(?:detail\s+of\s+army\s+officers?|army\s+officers?\b.{0,80}\bschools?)\b",
        normalized,
    ):
        add("army_officer_school_detail")
    if re.search(
        r"\b(?:wildlife|migratory\s+birds?|fish\s+and\s+wildlife|"
        r"conservation\s+order|hunting\s+regulations?)\b",
        normalized,
    ) and re.search(r"\b(?:shall|may|order|secretary|regulations?)\b", normalized):
        add("wildlife_conservation_order")
    if re.search(
        r"\b(?:public\s+housing\s+agenc(?:y|ies)|low[-\s]+income\s+housing|"
        r"assistance\s+payments?|housing\s+assistance)\b",
        normalized,
    ):
        add("public_housing_agency_assistance")
    if re.search(
        r"\b(?:public\s+charter\s+schools?|charter\s+school\s+program|"
        r"programs?\s+of\s+national\s+significance)\b",
        normalized,
    ):
        add("public_charter_school_program")
    if re.search(
        r"\b(?:agreement\s+with\s+murray\s+county|national\s+military\s+park)\b",
        normalized,
    ) and re.search(r"\bagreements?\b", normalized):
        add("agreement_military_park_authority")
    if re.search(
        r"\bagreements?\b.{0,120}\bpublic\s+corporation\b|"
        r"\bpublic\s+corporation\b.{0,120}\bagreements?\b",
        normalized,
    ):
        add("public_corporation_agreement_authority")
    if re.search(
        r"\b(?:loan\s+guaranty|loan\s+guarantee|loan\s+guaranty\s+and\s+insurance|"
        r"powers?\s+of\s+secretary)\b",
        normalized,
    ) and re.search(
        r"\b(?:indians?|indian\s+organizations?|secretary|loan)\b",
        normalized,
    ):
        add("indian_loan_guaranty_power")
        add("loan_guarantee_authority")
    if re.search(
        r"\bremed(?:y|ies)\s+as\s+cumulative\b|"
        r"\bremed(?:y|ies)\s+provided\s+under\s+this\s+part\b|"
        r"\bin\s+addition\s+to\s+remed(?:y|ies)\b|"
        r"\bremed(?:y|ies)\s+existing\s+under\s+another\s+law\b",
        normalized,
    ):
        add("remedies_as_cumulative")
        add("cumulative_remedy_preservation")
    if re.search(
        r"\b(?:export\s+credit|credit\s+authority|federal\s+financing\s+bank)\b",
        normalized,
    ):
        add("credit_authority")
        if "export" in tokens:
            add("export_credit_authority")
        if re.search(r"\bfederal\s+financing\s+bank\b", normalized):
            add("federal_financing_bank")
    if re.search(
        r"\brailroad\s+(?:employees?|retirement|unemployment\s+insurance)\b",
        normalized,
    ):
        add("rail_employee_status")
    if re.search(
        r"\brailroad\b.{0,80}\b(?:trust\s+fund|retirement\s+account|"
        r"unemployment\s+insurance)\b|"
        r"\b(?:trust\s+fund|retirement\s+account)\b.{0,80}\brailroad\b",
        normalized,
    ):
        add("rail_employee_trust_fund")
    if re.search(
        r"\b(?:lease|leases|leasing)\b.{0,120}\b(?:reserved\s+)?lands?\b|"
        r"\b(?:reserved\s+)?lands?\b.{0,120}\b(?:lease|leases|leasing)\b",
        normalized,
    ):
        add("reserved_land_lease_authority")
        add("reserved_land")
    if re.search(
        r"\b(?:establish|prescribe|set|fix)\b.{0,80}\brental\s+rates?\b|"
        r"\brental\s+rates?\b.{0,80}\b(?:establish|prescribe|set|fix)\b",
        normalized,
    ):
        add("rental_rate_authority")
    if re.search(
        r"\b(?:disposition|deposit|dispose|revenues?)\b.{0,80}\brevenues?\b|"
        r"\brevenues?\b.{0,80}\b(?:disposition|deposit|dispose)\b",
        normalized,
    ):
        add("revenue_disposition")
    if re.search(
        r"\b(?:nontaxation|internal\s+revenue\s+code|taxable\s+income)\b",
        normalized,
    ) and re.search(r"\bdeposits?\b", normalized):
        add("deposit_tax_treatment")
        add("tax_treatment")
    if re.search(
        r"\b(?:there\s+is\s+established|is\s+established\s+within|"
        r"office\s+to\s+be\s+known\s+as)\b",
        normalized,
    ):
        add("office_establishment")
    if re.search(
        r"\b(?:there\s+is\s+hereby\s+)?established\b.{0,120}"
        r"\b(?:reserve|national\s+strategic\s+uranium\s+reserve)\b",
        normalized,
    ):
        add("reserve_establishment_authority")
    if re.search(
        r"\bnational\s+strategic\s+uranium\s+reserve\b|"
        r"\buranium\s+reserve\b.{0,80}\b(?:secretary|reserve|direction|control)\b",
        normalized,
    ):
        add("national_strategic_uranium_reserve")
    if re.search(
        r"\b(?:natural\s+uranium|uranium\s+equivalents?|uranium\s+inventory)\b",
        normalized,
    ):
        add("uranium_reserve_resource")
    if re.search(
        r"\b(?:there\s+is\s+hereby\s+)?established\b.{0,120}\bfund\b",
        normalized,
    ):
        add("fund_establishment_authority")
    if re.search(
        r"\bfund\b.{0,80}\bwithin\s+the\s+department\b|"
        r"\bdepartment\b.{0,80}\bfund\b",
        normalized,
    ):
        add("department_fund_administration")
    if re.search(
        r"\bcarry\s+out\b.{0,120}\b(?:act|section|program|activities)\b",
        normalized,
    ):
        add("statutory_implementation_authority")
    if re.search(r"\bmeasurement\b.{0,80}\b(?:vessels?|hulls?)\b", normalized):
        add("vessel_measurement")
        add("measurement_determination")
    if re.search(
        r"\blength\b.{0,80}\bmeans\b.{0,120}\b(?:horizontal\s+distance|hull)\b|"
        r"\bhorizontal\s+distance\b.{0,120}\b(?:hull|stem|stern)\b",
        normalized,
    ):
        add("hull_length_definition")
        add("maritime_hull_measurement")
    if re.search(
        r"\b(?:secretary|administrator|commission)\b.{0,80}\bshall\s+assign\b|"
        r"\bshall\s+assign\b.{0,80}\b(?:length|measurement|number|rating)\b",
        normalized,
    ):
        add("agency_measurement_assignment")
    if re.search(
        r"\birrigation\s+projects?\b.{0,80}\breclamation\s+act\b|"
        r"\breclamation\s+act\b.{0,80}\birrigation\s+projects?\b",
        normalized,
    ):
        add("reclamation_act_irrigation_project")
        add("reclamation_act_authority")
    if re.search(
        r"\b(?:authorized\s+to\s+)?conclude\b.{0,80}\b(?:officials?|government)\b",
        normalized,
    ):
        add("international_agreement_authority")
    if re.search(
        r"\b(?:machinery|material|equipment|supplies)\b.{0,120}"
        r"\b(?:printing|binding|blank[-\s]+book|lithograph|photolithograph)\b|"
        r"\b(?:printing|binding|blank[-\s]+book|lithograph|photolithograph)\b.{0,120}"
        r"\b(?:machinery|material|equipment|supplies)\b",
        normalized,
    ):
        add("government_printing_equipment")
    if re.search(
        r"\b(?:officer|agency|agencies)\b.{0,120}\bgovernment\b.{0,120}"
        r"\b(?:machinery|material|equipment|supplies)\b|"
        r"\b(?:machinery|material|equipment|supplies)\b.{0,120}"
        r"\b(?:government\s+agenc(?:y|ies)|other\s+government)\b",
        normalized,
    ):
        add("government_agency_equipment_transfer")
    if re.search(
        r"\b(?:employee|employees)\b.{0,80}\b(?:adverse\s+actions?|suspension|removal)\b|"
        r"\b(?:adverse\s+actions?|suspension|removal)\b.{0,80}\b(?:employee|employees)\b",
        normalized,
    ):
        add("employee_adverse_action")
    if re.search(
        r"\b(?:30|thirty)\s+days?'?\s+advance\s+written\s+notice\b|"
        r"\badvance\s+written\s+notice\b.{0,80}\b(?:30|thirty)\s+days?\b",
        normalized,
    ):
        add("employee_notice_period")
    if re.search(
        r"\b(?:reasonable\s+time\s+to\s+answer|answer\s+orally\s+and\s+in\s+writing|"
        r"represented\s+by\s+an\s+attorney|employee\s+is\s+entitled\s+to)\b",
        normalized,
    ):
        add("adverse_action_procedure")
    if re.search(
        r"\b(?:secretary|administrator)\b.{0,120}\b(?:make|adjust|reduce|increase)\b"
        r".{0,80}\bpayments?\b|"
        r"\bpayments?\b.{0,120}\b(?:secretary|administrator)\b",
        normalized,
    ):
        add("program_payment_authority")
    if re.search(
        r"\b(?:adjust(?:ment|ed|s)?|reduc(?:e|ed|tion)|increas(?:e|ed))\b"
        r".{0,100}\bpayments?\b|"
        r"\bpayments?\b.{0,100}\b(?:adjust(?:ment|ed|s)?|reduc(?:e|ed|tion)|increas(?:e|ed))\b",
        normalized,
    ):
        add("secretary_payment_adjustment")
    if re.search(
        r"\b(?:rural\s+development|rural\s+business|community\s+facilit(?:y|ies)|"
        r"grants?\s+to\s+(?:eligible\s+)?(?:entities|recipients)|grant\s+program)\b",
        normalized,
    ):
        add("rural_development_grant_program")
    if re.search(
        r"\baccess\s+to\s+documents?\s+and\s+information\b|"
        r"\bcopies?\s+of\s+(?:all\s+)?documents?\b.{0,80}\bborrower\b|"
        r"\bborrowers?\b.{0,100}\bcopies?\s+of\s+(?:all\s+)?documents?\b|"
        r"\bcopies?\s+of\s+each\s+appraisal\b",
        normalized,
    ):
        add("document_access_right")
        if "borrower" in tokens or "borrowers" in tokens:
            add("borrower_document_access")
    if re.search(
        r"\bauthority\s+to\s+prescribe\s+regulations\b|"
        r"\bshall\s+have\s+authority\s+to\s+prescribe\s+regulations\b|"
        r"\bprescribe\s+regulations\s+for\s+the\s+carrying\s+out\b",
        normalized,
    ):
        add("regulation_prescription_authority")
        if "house" in tokens and "committee" in tokens:
            add("house_regulation_prescription_authority")
    if re.search(
        r"\brecords?\s+and\s+inspection\b|"
        r"\bmay\s+inspect\s+the\s+records?\b|"
        r"\brecords?\b.{0,80}\bproper\s+purpose\b",
        normalized,
    ):
        add("records_inspection_right")
    if re.search(
        r"\bright\s+to\s+receive\s+and\s+receipt\s+for\s+all\s+annuity\s+money\b|"
        r"\bannuity\s+money\b.{0,80}\b(?:due|receive|receipt)\b",
        normalized,
    ):
        add("annuity_receipt_right")
    if re.search(
        r"\badministration,\s*protection,\s+and\s+development\b|"
        r"\badministration\s+protection\s+and\s+development\b",
        normalized,
    ):
        add("administrative_protection_development")
    if re.search(
        r"\bunder\s+the\s+direction\s+of\s+the\s+secretary\b|"
        r"\bshall\s+be\s+exercised\s+under\s+the\s+direction\b",
        normalized,
    ):
        add("administrative_direction_authority")
    if re.search(
        r"\bservice\s+of\s+process\b|"
        r"\bdesignated\s+agent\b.{0,80}\b(?:receive|service|process)\b|"
        r"\blegal\s+process\s+or\s+demands\b",
        normalized,
    ):
        add("service_of_process_agent")
    if re.search(
        r"\bmay\s+declare\s+(?:and\s+pay\s+)?(?:a\s+)?dividends?\b|"
        r"\bdeclaration\s+and\s+payment\s+of\s+dividends?\b",
        normalized,
    ):
        add("dividend_declaration_authority")
    for phrase, atom in _LEGAL_SEMANTIC_ATOM_PHRASES:
        phrase_tokens = _CUE_TOKEN_RE.findall(phrase)
        if phrase in normalized or (
            phrase_tokens and all(token in tokens for token in phrase_tokens)
        ):
            add(atom)
    if re.search(r"\b(?:shall|must|required|requires?|obligat(?:e|ed|ion))\b", normalized):
        add("obligation")
    if re.search(r"\b(?:may|authorized|permitted|permission)\b", normalized):
        add("permission")
    if re.search(
        r"\b(?:may\s+not|shall\s+not|must\s+not|prohibit(?:ed|s)?|forbidden)\b",
        normalized,
    ):
        add("prohibition")
    if re.search(
        r"\b(?:lie\s+detector|polygraph)\b.{0,80}"
        r"\b(?:test|tests|examination|examinations|use)\b|"
        r"\b(?:test|tests|examination|examinations|use)\b.{0,80}"
        r"\b(?:lie\s+detector|polygraph)\b",
        normalized,
    ):
        add("lie_detector_test")
        if re.search(
            r"\b(?:prohibit(?:ed|s|ion|ions)?|may\s+not|shall\s+not|must\s+not)\b",
            normalized,
        ):
            add("lie_detector_use_prohibition")
    if re.search(
        r"\b(?:except|unless|notwithstanding|subject\s+to|provided\s+that)\b",
        normalized,
    ):
        add("exception_or_condition")
    if re.search(r"\b(?:with\s+)?intent\s+to\b", normalized):
        add("intent_condition")
    if re.search(
        r"\bdeposit(?:s|ed|ing)?\b.{0,80}\bmail\b.{0,80}\bmatter\b|"
        r"\bmail\b.{0,80}\bmatter\b.{0,80}\bdeposit(?:s|ed|ing)?\b",
        normalized,
    ):
        add("postal_matter_deposit")
        add("postal_mail_matter")
    if re.search(r"\bnonmailable\b|\bmatter\s+declared\s+nonmailable\b", normalized):
        add("nonmailable_matter")
    if re.search(r"\bobscene\s+matter\b", normalized):
        add("obscene_matter")
    if re.search(
        r"\b(?:exempt(?:ed|ion|ions)?|(?:shall|does|do|did)\s+not\s+apply|"
        r"provisions?\s+of\s+this\s+\w+\s+shall\s+not\s+apply)\b",
        normalized,
    ):
        add("exemption")
    if re.search(
        r"\bperishable\s+agricultural\s+commodit(?:y|ies)\b",
        normalized,
    ):
        add("perishable_agricultural_commodity")
    if re.search(
        r"\b(?:container|trailer)\b.{0,120}"
        r"\bperishable\s+agricultural\s+commodit(?:y|ies)\b",
        normalized,
    ) or re.search(
        r"\bperishable\s+agricultural\s+commodit(?:y|ies)\b.{0,120}"
        r"\b(?:container|trailer)\b",
        normalized,
    ):
        add("perishable_commodity_container_exemption")
    if re.search(r"\btest\s+platforms?\b", normalized):
        add("test_platform")
    if re.search(
        r"\b(?:ocean\s+thermal\s+energy\s+conversion|plantship|"
        r"facilit(?:y|ies)\s+(?:or\s+)?plantship)\b",
        normalized,
    ):
        add("facility_operation")
    if re.search(
        r"\b(?:not\s+later\s+than|no\s+later\s+than|until|after|before|effective\s+date)\b",
        normalized,
    ):
        add("temporal_condition")
    if re.search(
        r"\b(?:effective\s+(?:date|on)|takes?\s+effect|shall\s+take\s+effect)\b",
        normalized,
    ):
        add("effective_date_transition")
    if re.search(
        r"\b(?:between|from)\b.{0,80}\b(?:18|19|20)\d{2}\b"
        r".{0,80}\b(?:and|to|through|until)\b.{0,80}\b(?:18|19|20)\d{2}\b",
        normalized,
    ):
        add("date_range_temporal_scope")
    if re.search(r"\bannually\b", normalized) and re.search(
        r"\b(?:report|submit|make\s+publicly\s+available)\b",
        normalized,
    ):
        add("annual_report_duty")
    if re.search(
        r"\b(?:prepare|preparation)\b.{0,80}\bsubmit(?:s|ted|ting|tal|sion)?\b",
        normalized,
    ):
        add("submit_or_file")
    if re.search(
        r"\b(?:submit|file|provide|prepare)\b.{0,80}\b(?:budget|program|accounts?|audit)\b",
        normalized,
    ):
        add("submit_or_file")
    if re.search(
        r"\brequisitions?\b.{0,120}\b(?:advance|payment)\b.{0,80}\bmoney\b",
        normalized,
    ) or re.search(
        r"\b(?:advance|payment)\b.{0,80}\bmoney\b.{0,120}\brequisitions?\b",
        normalized,
    ):
        add("treasury_requisition_payment")
    if re.search(r"\bout\s+of\s+the\s+treasury\b", normalized):
        add("treasury_payment_source")
    if re.search(
        r"\bestimates?\b.{0,60}\baccounts?\b.{0,80}\bexpenditures?\b",
        normalized,
    ) or re.search(
        r"\baccounts?\b.{0,60}\bexpenditures?\b",
        normalized,
    ):
        add("expenditure_account_estimate")
    if re.search(
        r"\bexpenditures?\b.{0,120}\bbusiness\b.{0,80}\bassigned\s+by\s+law\b",
        normalized,
    ) or re.search(
        r"\bbusiness\b.{0,80}\bassigned\s+by\s+law\b.{0,80}\bdepartment\b",
        normalized,
    ):
        add("department_expenditure_authorization")
        add("department_business_assignment")
    if re.search(r"\bannual\s+budget\s+program\b", normalized):
        add("budget_program_submission")
    if re.search(r"\bbuying\s+power\b.{0,50}\bmaint(?:ain|enance)\b", normalized):
        add("buying_power_account_maintenance")
    if re.search(r"\bmaint(?:ain|enance)\b.{0,40}\baccounts?\b", normalized):
        add("account_maintenance")
    if re.search(
        r"\bcustody\b.{0,80}\b(?:departmental|department|records?|property)\b",
        normalized,
    ) or re.search(
        r"\b(?:departmental|department)\b.{0,80}\bcustody\b",
        normalized,
    ):
        add("departmental_record_custody")
    if re.search(
        r"\bcustody\b.{0,80}\b(?:collections?|museum|cultural\s+items?|objects?)\b",
        normalized,
    ) or re.search(
        r"\b(?:museum|collections?|cultural\s+items?|objects?)\b.{0,80}"
        r"\b(?:custody|care|control|administ(?:er|ration))\b",
        normalized,
    ):
        add("museum_collection_custody")
    if re.search(
        r"\bnational\s+museum\s+of\s+the\s+american\s+indian\b|"
        r"\bmuseum\s+of\s+the\s+american\s+indian\b",
        normalized,
    ):
        add("national_museum_american_indian")
    if re.search(r"\bboard\s+of\s+trustees\b", normalized):
        add("museum_board_trustees")
    if re.search(r"\bboard\s+of\s+regents\b", normalized):
        add("museum_board_regents")
    if re.search(
        r"\baccountab(?:ility|le)\b.{0,60}\bresponsib(?:ility|le)\b",
        normalized,
    ):
        add("accountability_responsibility")
    if re.search(
        r"\b(?:audit|audited)\b.{0,80}\b(?:government\s+accountability\s+office|comptroller\s+general)\b",
        normalized,
    ):
        add("audit_requirement")
    if re.search(
        r"\bflood\s+insurance\s+rate\s+maps?\b.{0,80}\bcertif(?:y|ication|ied)\b|"
        r"\bcertif(?:y|ication|ied)\b.{0,80}\bflood\s+insurance\s+rate\s+maps?\b",
        normalized,
    ):
        add("flood_map_certification")
    if re.search(
        r"\bflood\s+mapping\s+program\b|"
        r"\bmapping\s+program\b.{0,80}\bnational\s+flood\s+insurance\s+program\b",
        normalized,
    ):
        add("flood_mapping_program")
    if re.search(
        r"\btechnical\s+mapping\s+advisory\s+council\b|"
        r"\bonly\s+after\s+review\b.{0,100}\btechnical\s+mapping\b",
        normalized,
    ):
        add("technical_mapping_advisory_review")
    if re.search(
        r"\b(?:shall|must)\s+(?:submit|make|file|provide)\b.{0,80}\breports?\b",
        normalized,
    ):
        add("report_duty")
    if re.search(
        r"\breports?\b.{0,80}\b(?:contents?|discussion|actions?\s+taken|includes?)\b",
        normalized,
    ):
        add("report_contents")
    if re.search(
        r"\b(?:discussion|actions?\s+taken|implement(?:ation|ed)?)\b.{0,80}"
        r"\breports?\b|\breports?\b.{0,80}"
        r"\b(?:discussion|actions?\s+taken|implement(?:ation|ed)?)\b",
        normalized,
    ):
        add("implementation_action_report")
    if re.search(
        r"\b(?:study|review|assessment)\b.{0,40}\b(?:and\s+)?reports?\b",
        normalized,
    ):
        add("study_report_duty")
    if re.search(
        r"\binjunctions?\b.{0,100}\b(?:national\s+emergenc(?:y|ies)|labor\s+disputes?)\b|"
        r"\b(?:national\s+emergenc(?:y|ies)|labor\s+disputes?)\b.{0,100}\binjunctions?\b",
        normalized,
    ):
        add("labor_dispute_injunction")
    if re.search(
        r"\bnational\s+emergenc(?:y|ies)\b.{0,100}\blabor\s+disputes?\b|"
        r"\blabor\s+disputes?\b.{0,100}\bnational\s+emergenc(?:y|ies)\b",
        normalized,
    ):
        add("national_emergency_labor_dispute")
    if re.search(
        r"\b(?:transfer|transferred|transferring)\b.{0,80}\bfunds?\b",
        normalized,
    ) or re.search(
        r"\b(?:amounts?|appropriation|appropriated)\b.{0,120}"
        r"\b(?:transfer|transferred|transferring)\b.{0,120}"
        r"\b(?:account|appropriation|funds?)\b",
        normalized,
    ) or re.search(
        r"\b(?:transfer|transferred|transferring)\b.{0,120}"
        r"\b(?:amounts?|appropriation|appropriated|account|funds?)\b",
        normalized,
    ):
        add("fund_transfer_authority")
    if re.search(
        r"\b(?:carry\s+out|establish(?:ing)?|administer(?:ing)?)\b.{0,120}"
        r"\b(?:program|activities|awards?)\b",
        normalized,
    ):
        add("program_activity_implementation")
    if re.search(
        r"\b(?:make|making)\b.{0,40}\bawards?\b.{0,80}\bcompetitive\s+basis\b",
        normalized,
    ):
        add("competitive_award_program")
    if re.search(
        r"\b(?:medal\s+of\s+honor|military\s+decorations?|military\s+awards?)\b",
        normalized,
    ):
        add("medal_of_honor_award")
        add("individual_military_award")
        add("military_award_review")
    if re.search(
        r"\b(?:review|consider|submit|approve)\b.{0,100}"
        r"\b(?:proposal|recommendation)\b.{0,100}\b(?:award|medal)\b|"
        r"\b(?:proposal|recommendation)\b.{0,100}\b(?:award|medal)\b.{0,100}"
        r"\b(?:review|consider|submit|approve)\b",
        normalized,
    ):
        add("award_proposal_review")
    if re.search(
        r"\b(?:loan|loans)\b.{0,80}\b(?:size|limitation|limit|amount|exceed)\b|"
        r"\b(?:size|limitation|limit|amount|exceed)\b.{0,80}\b(?:loan|loans)\b",
        normalized,
    ):
        add("loan_size_limitation")
        add("project_loan_limit")
    if re.search(
        r"\b(?:project\s+loans?|loan\s+program|loan\s+guarantee)\b",
        normalized,
    ):
        add("project_loan_program")
    if re.search(r"\bgeothermal\s+energy\b", normalized):
        add("geothermal_energy_program")
    if re.search(
        r"\bhealth\s+professionals?\b.{0,80}\beducational\s+assistance\b",
        normalized,
    ) or re.search(
        r"\beducational\s+assistance\b.{0,80}\bprogram\b",
        normalized,
    ):
        add("health_professional_education_assistance")
        add("education_assistance_benefit")
    if re.search(
        r"\b(?:repay(?:ment)?|pay)\b.{0,120}\b(?:united\s+states|amounts?|scholarship|assistance)\b",
        normalized,
    ) or re.search(
        r"\bamounts?\b.{0,120}\b(?:paid|repay(?:ment)?|united\s+states)\b",
        normalized,
    ):
        add("education_assistance_repayment")
        add("federal_repayment_obligation")
    if re.search(r"\bterminat(?:e|es|ed|ion)\b.{0,60}\bauthorit(?:y|ies)\b", normalized):
        add("termination_authority")
    if re.search(r"\b(?:consultation|cooperation)\b", normalized):
        add("consultation")
    if re.search(
        r"\binitiat(?:e|es|ed|ing|ion)\b.{0,80}\bdiscussions?\b",
        normalized,
    ) or re.search(
        r"\bdiscussions?\b.{0,80}\b(?:directors?|institutions?|banks?|funds?)\b",
        normalized,
    ):
        add("interinstitutional_discussion")
    if re.search(
        r"\bprovide\b.{0,40}\badvice\b.{0,40}\bassistance\b",
        normalized,
    ):
        add("development_advice_assistance")
    if re.search(
        r"\b(?:reduc(?:e|ed|ing|tion)|convert(?:ed|ing|sion))\b.{0,80}"
        r"\b(?:sovereign\s+)?debt\b",
        normalized,
    ) or re.search(
        r"\b(?:sovereign\s+)?debt\b.{0,80}"
        r"\b(?:reduc(?:e|ed|ing|tion)|convert(?:ed|ing|sion))\b",
        normalized,
    ):
        add("sovereign_debt_conversion")
    if re.search(
        r"\bhuman\s+welfare\b|"
        r"\bnatural\s+resource\s+programs?\b|"
        r"\bconservation\b.{0,80}\brestoration\b.{0,80}\bnatural\s+resources?\b",
        normalized,
    ):
        add("human_welfare_resource_program")
    if re.search(r"\b(?:administ(?:er|ration)|enforce(?:ment|d|s)?)\b", normalized):
        add("administration_enforcement")
    if re.search(r"\bjurisdiction\b", normalized) and re.search(
        r"\b(?:court|courts|civil\s+actions?|actions?|state)\b",
        normalized,
    ):
        add("jurisdiction_authority")
    if re.search(r"\btimber\b", normalized) and re.search(r"\bstone\b", normalized):
        add("timber_stone_use")
        if re.search(r"\bsettlers?\b", normalized):
            add("settler_resource_use")
    if re.search(r"\bcut(?:ting)?\b.{0,40}\btimber\b", normalized):
        add("timber_cutting")
        if re.search(r"\bforest(?:s)?\b", normalized):
            add("timber_cutting_forest_scope")
    if re.search(
        r"\b(?:reserv(?:e|es|ed|ation)|reserved)\b.{0,80}\b(?:timber|forest|forests)\b",
        normalized,
    ) or re.search(
        r"\b(?:timber|forest|forests)\b.{0,80}\b(?:reserv(?:e|es|ed|ation)|reserved)\b",
        normalized,
    ):
        add("forest_resource_reservation")
    if re.search(r"\bnational\s+forests?\b", normalized):
        add("national_forest_resource")
    if re.search(
        r"\b(?:use|uses|using|utili[sz](?:e|es|ed|ation))\b.{0,80}"
        r"\b(?:timber|stone|forest|forests?|mineral|minerals?|land|lands)\b",
        normalized,
    ):
        add("natural_resource_use")
    if re.search(r"\bcivil\s+actions?\b", normalized):
        add("civil_action")
    if re.search(
        r"\b(?:protection\s+from\s+liability|liability\s+protection|"
        r"protected\s+from\s+liability|no\s+cause\s+of\s+action\s+shall\s+lie)\b",
        normalized,
    ):
        add("liability_protection")
    if re.search(r"\bcybersecurity\s+information(?:\s+sharing)?\b", normalized):
        add("cybersecurity_information_sharing")
    elif re.search(r"\binformation\s+sharing\b", normalized):
        add("information_sharing")
    if re.search(r"\blaw\s+enforcement\b", normalized):
        add("law_enforcement")
    if re.search(
        r"\b(?:government\s+publications?|depositor(?:y|ies)|"
        r"free\s+use\s+of\s+the\s+general\s+public)\b",
        normalized,
    ):
        add("government_publication_depository_access")
    if re.search(
        r"\b(?:congressional\s+)?allotments?\s+of\s+public\s+documents?\b",
        normalized,
    ) or re.search(
        r"\bpublic\s+documents?\b.{0,80}\b(?:printed\s+after|expiration\s+of\s+terms)\b",
        normalized,
    ):
        add("public_document_allotment")
    if re.search(
        r"\bretiring\s+members?\b.{0,80}\b(?:documents?|rights?)\b",
        normalized,
    ) or re.search(
        r"\bright(?:s)?\s+of\s+retiring\s+members?\b",
        normalized,
    ):
        add("retiring_member_document_right")
    if re.search(
        r"\b(?:after|following)\s+expiration\s+of\s+terms?\b",
        normalized,
    ) or re.search(
        r"\bexpiration\s+of\s+terms?\s+of\s+members?\s+of\s+congress\b",
        normalized,
    ):
        add("post_term_member_right")
        add("temporal_condition")
    if re.search(
        r"\b(?:dispose|disposal)\b.{0,80}\b(?:publications?|depositor(?:y|ies))\b",
        normalized,
    ):
        add("publication_disposal_authority")
    if re.search(r"\bshort\s+title\b", normalized):
        add("statutory_short_title")
    if re.search(
        r"\b(?:preemption\s+and\s+)?homestead\s+entries\b|"
        r"\bentries\b.{0,80}\bmade\s+in\s+good\s+faith\b",
        normalized,
    ):
        add("homestead_entry_confirmation")
    if re.search(r"\badvisory\s+committees?\b", normalized):
        add("advisory_committee")
    if re.search(
        r"\b(?:appoint(?:ment|ed|s)?|authoriz(?:e|ed|es|ation))\b.{0,80}"
        r"\badvisory\s+committees?\b|"
        r"\badvisory\s+committees?\b.{0,80}"
        r"\b(?:appoint(?:ment|ed|s)?|authoriz(?:e|ed|es|ation))\b",
        normalized,
    ):
        add("advisory_committee_appointment")
        add("appointment_authority")
    if re.search(r"\brailroad\s+lands?\b", normalized):
        add("railroad_land_status")
    if re.search(
        r"\b(?:withdrawal|restoration\s+to\s+market|after\s+restoration)\b",
        normalized,
    ):
        add("land_withdrawal_restoration_scope")
    if re.search(
        r"\b(?:army|air)?\s*national\s+guard\b.{0,100}"
        r"\b(?:relocat(?:e|ed|ion)|withdraw(?:n|al)?)\b",
        normalized,
    ) or re.search(
        r"\b(?:relocat(?:e|ed|ion)|withdraw(?:n|al)?)\b.{0,100}"
        r"\b(?:army|air)?\s*national\s+guard\b",
        normalized,
    ):
        add("national_guard_unit_status")
        add("national_guard_relocation_limit")
        add("unit_relocation_withdrawal_restriction")
    if re.search(
        r"\b(?:relocat(?:e|ed)|withdrawn)\b.{0,100}\bconsent\s+of\s+the\s+governor\b",
        normalized,
    ):
        add("state_governor_consent_requirement")
    if re.search(
        r"\bnational\s+historic\s+site\b|"
        r"\bhistoric\s+site\s+purposes\b|"
        r"\bdesignated\b.{0,80}\bpreservation\b.{0,80}\bhistoric\s+site\b|"
        r"\bset\s+apart\b.{0,80}\bpreservation\b",
        normalized,
    ):
        add("national_historic_site_designation")
        add("historic_site_preservation_designation")
    if re.search(
        r"\btransfer\b.{0,80}\b(?:housing|lands?|property)\b|"
        r"\b(?:housing|lands?|property)\b.{0,80}\btransfer\b",
        normalized,
    ):
        add("housing_transfer_authority")
    if re.search(r"\bsurplus\s+housing\b", normalized):
        add("surplus_housing_transfer")
    if re.search(
        r"\bspecial(?:ly)?\s+adapted\s+housing\b|"
        r"\badapted\s+housing\b.{0,80}\b(?:assist(?:ance)?|grant|benefit)\b|"
        r"\b(?:assist(?:ance)?|grant|benefit)\b.{0,80}\badapted\s+housing\b",
        normalized,
    ):
        add("special_adapted_housing_assistance")
    if re.search(
        r"\bcoordination\b.{0,80}\b(?:administration|benefits?|"
        r"special(?:ly)?\s+adapted\s+housing)\b|"
        r"\b(?:administration|benefits?)\b.{0,80}\bcoordination\b",
        normalized,
    ):
        add("administrative_coordination_duty")
        if re.search(r"\bspecial(?:ly)?\s+adapted\s+housing\b", normalized):
            add("special_adapted_housing_coordination")
    if re.search(
        r"\bcertification\b.{0,80}\bsecretar(?:y|ies)\b|"
        r"\bsecretar(?:y|ies)\b.{0,80}\bcertif(?:y|ies|ied|ication)\b",
        normalized,
    ):
        add("agency_certification_determination")
    if re.search(r"\b(?:official\s+)?seal\b", normalized):
        add("official_seal")
    if re.search(r"\bcapitol\s+visitor\s+center\b", normalized):
        add("capitol_visitor_center")
        add("uscode_capitol_visitor_center_administration")
    if re.search(
        r"\bassistant\b.{0,80}\bchief\s+executive\s+officer\b|"
        r"\bchief\s+executive\s+officer\b.{0,80}\bassistant\b",
        normalized,
    ):
        add("visitor_center_assistant")
        add("chief_executive_officer")
    if re.search(
        r"\babsent\s+uniformed\s+services?\s+voters?\b|"
        r"\buniformed\s+services?\s+voters?\b",
        normalized,
    ):
        add("absent_uniformed_services_voter")
    if re.search(r"\boverseas\s+voters?\b", normalized):
        add("overseas_voter")
    if re.search(
        r"\b(?:management|manage|disposition|dispose)\b.{0,100}"
        r"\b(?:vessels?|property)\b.{0,100}\bfishery\s+loans?\b|"
        r"\bfishery\s+loans?\b.{0,100}\b(?:vessels?|property|disposition)\b",
        normalized,
    ):
        add("fishery_vessel_property_disposition")
        add("fishery_loan_property")
    if re.search(
        r"\bborder\s+infrastructure\b|"
        r"\btechnology\s+modernization\b",
        normalized,
    ):
        add("border_infrastructure_modernization")
    if re.search(
        r"\btrust\s+territory\b.{0,80}\bpacific\s+islands\b|"
        r"\bpacific\s+islands\b.{0,80}\btrust\s+territory\b",
        normalized,
    ):
        add("trust_territory_purchasing_authority")
    if re.search(
        r"\b(?:make|makes|made)\s+purchases?\b.{0,80}"
        r"\bgeneral\s+services\s+administration\b|"
        r"\bgeneral\s+services\s+administration\b.{0,80}\bpurchases?\b",
        normalized,
    ):
        add("government_purchasing_authority")
    if re.search(
        r"\bfederal\s+alcohol\s+laws?\b|"
        r"\bequal\s+treatment\b.{0,80}\balcohol\s+laws?\b",
        normalized,
    ):
        add("federal_alcohol_law_equal_treatment")
    if re.search(r"\bplant\s+variety\s+protection\s+office\b", normalized):
        add("plant_variety_protection_office")
    elif re.search(r"\bplant\s+variety\s+protection\b", normalized):
        add("plant_variety_protection")
    if re.search(
        r"\b(?:secretary|administrator|agency|authority|commission|director)\b"
        r".{0,80}\b(?:determin(?:e|es|ed|ation|ations|ing)|find(?:s|ing)?)\b",
        normalized,
    ) or re.search(
        r"\b(?:determin(?:e|es|ed|ation|ations|ing)|find(?:s|ing)?)\b"
        r".{0,80}\b(?:secretary|administrator|agency|authority|commission|director)\b",
        normalized,
    ):
        add("agency_determination")
    if re.search(r"\bcommodit(?:y|ies)\b", normalized) and re.search(
        r"\b(?:set[-\s]?aside|value|determin(?:e|es|ed|ation|ing))\b",
        normalized,
    ):
        add("commodity_value_determination")
        if re.search(r"\bset[-\s]?aside\b", normalized):
            add("commodity_set_aside")
    if re.search(r"\binteragency\b.{0,40}\bcoordinat(?:e|es|ed|ing|ion|ing\s+group)\b", normalized):
        add("interagency_coordination")
    if re.search(r"\bchild\s+abduction\b.{0,60}\bremed(?:y|ies)\b", normalized):
        add("child_abduction_remedy")
    if re.search(
        r"\bendangered\s+species\b.{0,120}\b(?:fish|wildlife)\b|"
        r"\b(?:fish|wildlife)\b.{0,120}\bendangered\s+species\b",
        normalized,
    ):
        add("endangered_species_protection")
        add("endangered_species_wildlife")
    if re.search(
        r"\bprotection\s+and\s+conservation\b.{0,80}\bwildlife\b|"
        r"\bwildlife\b.{0,80}\bprotection\s+and\s+conservation\b",
        normalized,
    ):
        add("wildlife_conservation_protection")
    if re.search(r"\bfish\s+and\s+wildlife\b", normalized):
        add("fish_wildlife_conservation")
    if re.search(
        r"\bcongress\s+finds?\b.{0,80}\b(?:declares?|declaration|findings?)\b",
        normalized,
    ) or re.search(r"\bfindings?\s+and\s+declarations?\b", normalized):
        add("congressional_findings_declaration")
    if re.search(
        r"\blevel\s+of\s+technology\b.{0,80}\b(?:changed|radical|development|exploration)\b",
        normalized,
    ):
        add("mineral_development_technology")
    if re.search(
        r"\b(?:continued\s+)?application\b.{0,80}\bmining\s+laws?\b",
        normalized,
    ):
        add("mining_law_application")
    if re.search(
        r"\brelationship\s+to\s+other\s+law\b|"
        r"\bexcept\s+as\s+provided\b.{0,80}\b(?:law|section|title)\b",
        normalized,
    ):
        add("legal_relationship_override")
    if re.search(
        r"\bclassified\s+information\s+procedures?\s+act\b",
        normalized,
    ):
        add("classified_information_procedure")
    if re.search(
        r"\btechnology\s+transfer\b.{0,80}\b(?:transition|transitions|assessment)\b",
        normalized,
    ) or re.search(
        r"\b(?:transition|transitions|assessment)\b.{0,80}\btechnology\s+transfer\b",
        normalized,
    ):
        add("technology_transfer_assessment")
    if re.search(
        r"\b(?:secretary|administrator|director|agency)\b.{0,120}"
        r"\b(?:transmit|submit|provide|report)\b.{0,120}"
        r"\b(?:committee|committees|congress)\b",
        normalized,
    ) or re.search(
        r"\b(?:committee|committees|congress)\b.{0,120}"
        r"\b(?:transmit|submit|provide|report)\b",
        normalized,
    ):
        add("congressional_committee_report")
    if re.search(
        r"\b(?:not|no)\s+later\s+than\b.{0,160}"
        r"\b(?:transmit|submit|provide|report)\b",
        normalized,
    ):
        add("deadline_report_duty")
    if re.search(
        r"\bappropriated\s+amounts?\b.{0,120}\bfiscal\s+year\b|"
        r"\bfiscal\s+year\b.{0,120}\bappropriated\s+amounts?\b",
        normalized,
    ):
        add("appropriated_amount_availability")
        add("fiscal_year_appropriation_availability")
    if re.search(
        r"\b(?:omitted|reclassified|renumbered|transferred)\b.{0,120}"
        r"\bfollowing\s+enactment\b",
        normalized,
    ):
        add("codification_transition")
    if re.search(
        r"\bsalvage\s+archae?olog(?:ical|y)\b|"
        r"\b(?:experts?|consultants?)\b.{0,120}\bsalvage\s+archae?olog",
        normalized,
    ):
        add("salvage_archeology_administration")
    if re.search(
        r"\b(?:accept|utili[sz]e)\b.{0,120}\bfunds\b.{0,120}\bsalvage\s+archae?olog",
        normalized,
    ):
        add("salvage_fund_use_authority")
    if re.search(
        r"\b(?:obtain|services?\s+of)\b.{0,80}\bexperts?\b.{0,40}\bconsultants?\b",
        normalized,
    ):
        add("expert_consultant_service_authority")
    if re.search(
        r"\bterritorial\s+jurisdiction\b.{0,120}\b(?:hydraulic\s+)?mining\b",
        normalized,
    ) or re.search(
        r"\b(?:hydraulic\s+)?mining\b.{0,120}\bterritorial\s+jurisdiction\b",
        normalized,
    ):
        add("territorial_jurisdiction")
        add("hydraulic_mining")
    if re.search(r"\bcalifornia\s+debris\s+commission\b", normalized):
        add("california_debris_commission")
    if re.search(
        r"\b(?:resolution|resolve|resolving)\b.{0,80}\bclearing\s+banks?\b",
        normalized,
    ) or re.search(
        r"\bclearing\s+banks?\b.{0,80}\b(?:resolution|resolve|resolving)\b",
        normalized,
    ):
        add("clearing_bank_resolution")
    if re.search(r"\bfederal\s+reserve\s+board\b", normalized):
        add("federal_reserve_board_oversight")
    if re.search(
        r"\b(?:false|fictitious|fraudulent)\b.{0,80}"
        r"\b(?:statement|representation|material\s+fact)\b",
        normalized,
    ):
        add("false_statement_penalty")
    if re.search(r"\bknowingly\b.{0,40}\bwillfully\b", normalized):
        add("scienter_requirement")
    if re.search(r"\bmaterial\s+fact\b", normalized):
        add("material_fact_representation")
    if re.search(
        r"\bliab(?:le|ility)\b.{0,120}\bcivil\s+penalt(?:y|ies)\b|"
        r"\bcivil\s+penalt(?:y|ies)\b.{0,120}\bliab(?:le|ility)\b",
        normalized,
    ):
        add("civil_penalty_liability")
    if re.search(
        r"\b(?:penalt(?:y|ies)|liable)\b.{0,80}\b\d+\s+times\s+the\s+value\b|"
        r"\b\d+\s+times\s+the\s+value\b.{0,80}\b(?:penalt(?:y|ies)|liable)\b",
        normalized,
    ):
        add("penalty_value_multiplier")
    if re.search(
        r"\b(?:violat(?:e|es|ed|ing|ion|ions)|in\s+violation\s+of)\b"
        r".{0,80}\b(?:this|such)\s+"
        r"(?:chapter|section|subchapter|paragraph|subsection|title)\b",
        normalized,
    ):
        add("statutory_violation_condition")
    if re.search(
        r"\b(?:policies|goals)\b.{0,120}\bsupplement(?:al|ary)\b"
        r".{0,120}\bexisting\s+authorizations\b|"
        r"\bsupplement(?:al|ary)\b.{0,120}\bexisting\s+authorizations\b",
        normalized,
    ):
        add("supplemental_authorization_policy")
    if re.search(r"\bpredictive\s+modeling\b", normalized):
        add("predictive_analytics")
        if re.search(r"\b(?:disclos(?:e|ure)|analytics|technologies)\b", normalized):
            add("predictive_analytics_disclosure")
    if re.search(
        r"\b(?:waste|fraud|abuse)\b.{0,80}\b(?:prevent|identify|analytics|modeling)\b",
        normalized,
    ) or re.search(
        r"\b(?:prevent|identify|analytics|modeling)\b.{0,80}\b(?:waste|fraud|abuse)\b",
        normalized,
    ):
        add("waste_fraud_abuse_prevention")
    return atoms


def _defined_term_atoms_from_text(text: str) -> List[str]:
    atoms: List[str] = []
    seen: set[str] = set()
    has_definition_semantics = _has_definition_semantics(
        _clean_text(text).replace("_", " ").lower()
    )

    def add_atom(atom: str) -> None:
        normalized_atom = _clean_text(atom).lower().replace(" ", "_")
        if normalized_atom and normalized_atom not in seen:
            seen.add(normalized_atom)
            atoms.append(normalized_atom)

    for pattern in (
        _DEFINED_TERM_RE,
        _DEFINED_AS_USED_TERM_RE,
        _DEFINITION_HEADING_RE,
    ):
        for match in pattern.finditer(str(text or "")):
            term = _clean_text(match.group("term"))
            if not term:
                continue
            tokens = _CUE_TOKEN_RE.findall(term.lower())
            if not tokens or len(tokens) > 6:
                continue
            if tokens[0] in {"a", "an", "the", "this", "that", "such"}:
                tokens = tokens[1:]
            if not tokens:
                continue
            atom = "_".join(tokens)
            add_atom(atom)
            if has_definition_semantics:
                add_atom(f"{atom}_definition")
    return atoms


def _has_definition_semantics(normalized_text: str) -> bool:
    if not normalized_text:
        return False
    return bool(
        re.search(r"\bdefined\b", normalized_text)
        or re.search(r"\bas\s+used\s+in\s+(?:this|the)\b", normalized_text)
        or re.search(r"\b(?:means|includes?)\b", normalized_text)
    )


def _definition_condition_support_values(text: str) -> List[str]:
    """Return compact typed cues for definition clauses that impose criteria."""
    normalized = _clean_text(text).replace("_", " ").lower()
    if not normalized or not _has_definition_semantics(normalized):
        return []
    values: List[str] = []

    def add(value: str) -> None:
        cleaned = _clean_text(value).replace("_", " ")
        if cleaned and cleaned not in values:
            values.append(cleaned)

    add("definition condition")
    if re.search(r"\b(?:means|includes?)\b", normalized):
        add("defined term criteria")
    if re.search(r"\b(?:that|which)\b", normalized):
        add("definition relative condition")
    if re.search(r"\b(?:eligible|eligibility)\b", normalized):
        add("eligibility condition")
    if re.search(r"\b(?:among|highest|lowest|ranking|per\s+capita)\b", normalized):
        add("ranking condition")
    if re.search(r"\b(?:and|or)\b", normalized) and re.search(
        r"\([a-z0-9ivxlcdm]+\)", normalized
    ):
        add("enumerated definition criteria")
    return values


def _fallback_section_heading_tail_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    max_tokens: int = 18,
) -> str:
    fallback_rule = _clean_text(formula.metadata.get("fallback_rule") or "")
    if fallback_rule not in _USCODE_SECTION_HEADING_TAIL_RULES:
        return ""
    source_text = str(document.normalized_text or "")
    if not source_text:
        return ""
    start = max(0, min(len(source_text), int(formula.provenance.start_char)))
    end = max(start, min(len(source_text), int(formula.provenance.end_char)))
    local_heading = _leading_uscode_catchline_text(
        source_text[start:end],
        max_tokens=max_tokens,
    )
    if local_heading:
        return local_heading
    trailing = source_text[end:]
    if not trailing:
        return ""
    trailing = trailing.lstrip(" \t\r\n-–—:;,.")
    if not trailing:
        return ""
    candidate = _SECTION_HEADING_TAIL_SPLIT_RE.split(trailing, maxsplit=1)[0]
    heading_tail = _clean_text(candidate)
    heading_tail = _strip_uscode_gpo_attribution_fragment(heading_tail)
    heading_tail = _TRAILING_SECTION_PUNCT_RE.sub("", heading_tail)
    if not heading_tail:
        return ""
    if _is_low_information_section_marker(heading_tail):
        return ""
    lowered_heading_tail = heading_tail.lower()
    if (
        lowered_heading_tail.startswith("u.s.c. title")
        or lowered_heading_tail.startswith("usc title")
        or "united states code" in lowered_heading_tail
    ):
        return ""
    if len(_tokenize_for_similarity(heading_tail)) > max_tokens:
        return ""
    return heading_tail


def _leading_uscode_catchline_text(text: str, *, max_tokens: int) -> str:
    normalized = _clean_text(text)
    if not normalized:
        return ""
    stripped = _clean_text(
        _USCODE_LEADING_SECTION_REF_RE.sub("", normalized, count=1)
    )
    if not stripped or stripped == normalized:
        return ""
    stripped = _strip_uscode_gpo_attribution_fragment(stripped)
    stripped = _clean_text(stripped.lstrip(" \t\r\n-–—:;,."))
    if not stripped:
        return ""
    body_match = _USCODE_CATCHLINE_BODY_START_RE.search(stripped)
    if body_match is not None:
        stripped = _clean_text(stripped[: body_match.start()])
    else:
        stripped = _clean_text(
            _SECTION_HEADING_TAIL_SPLIT_RE.split(stripped, maxsplit=1)[0]
        )
    stripped = _TRAILING_SECTION_PUNCT_RE.sub("", stripped)
    if not stripped or _is_low_information_section_marker(stripped):
        return ""
    lowered = stripped.lower()
    if (
        lowered.startswith("u.s.c. title")
        or lowered.startswith("usc title")
        or "united states code" in lowered
    ):
        return ""
    if len(_tokenize_for_similarity(stripped)) > max_tokens:
        return ""
    return stripped


def _fallback_surface_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    max_tokens: int = 24,
) -> str:
    fallback_rule = _clean_text(formula.metadata.get("fallback_rule") or "")
    if not fallback_rule:
        return ""
    heading_tail = _fallback_section_heading_tail_text(
        document=document,
        formula=formula,
        max_tokens=max_tokens,
    )
    if heading_tail:
        return heading_tail
    source_text = str(document.normalized_text or "")
    if not source_text:
        return ""
    start = max(0, min(len(source_text), int(formula.provenance.start_char)))
    end = max(start, min(len(source_text), int(formula.provenance.end_char)))
    span_text = _clean_text(source_text[start:end])
    if not span_text:
        return ""
    normalized = _clean_text(_USCODE_LEADING_SECTION_REF_RE.sub("", span_text))
    normalized = _strip_uscode_gpo_attribution_fragment(normalized)
    normalized = _TRAILING_SECTION_PUNCT_RE.sub("", normalized)
    normalized = _trim_uscode_compilation_surface_text(
        normalized,
        max_tokens=max_tokens,
    )
    if not normalized:
        return ""
    status_keyword = _derived_status_keyword(
        formula=formula,
        fallback_rule=fallback_rule,
    )
    status_surface = _status_heading_surface_text(
        normalized,
        status_keyword=status_keyword,
    )
    if status_surface:
        return status_surface
    if _is_low_information_section_marker(normalized):
        if status_keyword:
            return status_keyword
        inferred_status = _status_keyword_from_source_text(source_text)
        if inferred_status:
            return inferred_status
        return ""
    tokens = _tokenize_for_similarity(normalized)
    if not tokens or len(tokens) > max_tokens:
        return ""
    return normalized


def _fallback_surface_context_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    surface_text: str,
    max_tokens: int = 24,
    right_context_char_window: int = 360,
    local_context_char_window: int = 180,
) -> str:
    source_text = str(document.normalized_text or "")
    if not source_text:
        return ""
    surface_value = _clean_text(surface_text).lower()
    if not surface_value:
        return ""
    source_length = len(source_text)
    start = max(0, min(source_length, int(formula.provenance.start_char)))
    end = max(start, min(source_length, int(formula.provenance.end_char)))
    right_context = _clean_text(
        source_text[end : min(source_length, end + right_context_char_window)]
    )
    local_context = _clean_text(
        source_text[
            max(0, start - local_context_char_window) : min(
                source_length,
                end + local_context_char_window,
            )
        ]
    )
    for raw_context in (right_context, local_context):
        if not raw_context:
            continue
        for segment in _SECTION_HEADING_TAIL_SPLIT_RE.split(raw_context):
            candidate = _clean_text(segment)
            if not candidate:
                continue
            candidate = _clean_text(_USCODE_LEADING_SECTION_REF_RE.sub("", candidate))
            candidate = candidate.lstrip(" \t\r\n-–—:;,.")
            candidate = _TRAILING_SECTION_PUNCT_RE.sub("", candidate)
            candidate = _trim_uscode_compilation_surface_text(
                candidate,
                max_tokens=max_tokens,
            )
            candidate = _clean_text(candidate)
            if (
                not candidate
                or candidate.lower() == surface_value
                or candidate.lower().startswith(surface_value)
            ):
                continue
            tokens = _tokenize_for_similarity(candidate)
            if not tokens or len(tokens) > max_tokens:
                continue
            if not _contextual_modal_cues_from_text(formula, text=candidate):
                continue
            return candidate
    return ""


def _trim_uscode_compilation_surface_text(
    text: str,
    *,
    max_tokens: int,
) -> str:
    normalized = _clean_text(text)
    if not normalized:
        return ""
    lowered = normalized.lower()
    likely_compilation = (
        "united states code" in lowered
        or lowered.startswith("u.s.c. title")
        or lowered.startswith("usc title")
        or "gpo.gov" in lowered
        or "government publishing office" in lowered
    )
    if not likely_compilation:
        return normalized
    section_match = _USCODE_INLINE_SECTION_REF_RE.search(normalized)
    # Residual span formulas often capture U.S.C. compilation headings that do
    # not include an inline "Sec./§" marker inside the selected span. Keep a
    # bounded cleaned fallback instead of dropping the span entirely so the
    # typed slot indexer preserves informative heading segments.
    if section_match is None:
        candidate = normalized
    else:
        candidate = _clean_text(
            normalized[section_match.end() :].lstrip(" \t\r\n-–—:;,.")
        )
    if not candidate:
        return ""
    candidate = _clean_text(_USCODE_GPO_ATTRIBUTION_RE.sub("", candidate))
    candidate = _TRAILING_SECTION_PUNCT_RE.sub("", candidate)
    if not candidate:
        return ""
    tokens = _tokenize_for_similarity(candidate)
    if not tokens:
        return ""
    if len(tokens) <= max_tokens:
        return candidate
    heading_candidate = _clean_text(_SECTION_HEADING_TAIL_SPLIT_RE.split(candidate, maxsplit=1)[0])
    heading_candidate = _TRAILING_SECTION_PUNCT_RE.sub("", heading_candidate)
    heading_tokens = _tokenize_for_similarity(heading_candidate)
    if heading_tokens and len(heading_tokens) <= max_tokens:
        return heading_candidate
    return ""


def _is_low_information_section_marker(text: str) -> bool:
    normalized = _clean_text(text)
    if not normalized:
        return False
    if re.fullmatch(r"[§\s.]+", normalized):
        return True
    tokens = _CUE_TOKEN_RE.findall(normalized.lower())
    if not tokens:
        return False
    if len(tokens) == 1:
        token = tokens[0]
        if (
            token in _LOW_INFORMATION_SECTION_MARKER_TOKENS
            or token in _LOW_INFORMATION_SECTION_MARKER_SINGLE_CHAR_TOKENS
            or token in _STRUCTURAL_FRAME_CUE_TOKENS
            or token.isdigit()
            or len(token) == 1
        ):
            return True
        if _is_canonical_roman_numeral(token):
            return True
        return False
    if len(tokens) == 2:
        first, second = tokens
        if (
            first in (
                _LOW_INFORMATION_SECTION_MARKER_TOKENS
                | _LOW_INFORMATION_SECTION_MARKER_SINGLE_CHAR_TOKENS
                | _STRUCTURAL_FRAME_CUE_TOKENS
            )
            and (
                second.isdigit()
                or len(second) == 1
                or _is_canonical_roman_numeral(second)
            )
        ):
            return True
    return False


def _status_keyword_from_source_text(text: str) -> str:
    normalized_text = _clean_text(text).lower()
    if not normalized_text:
        return ""
    for keyword in _USCODE_FALLBACK_STATUS_KEYWORDS:
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", normalized_text):
            return keyword
    return ""


def _status_heading_surface_text(text: str, *, status_keyword: str) -> str:
    normalized_text = _clean_text(text)
    normalized_keyword = _clean_text(status_keyword).lower()
    if not normalized_text or not normalized_keyword:
        return ""
    lowered_text = normalized_text.lower()
    if not lowered_text.startswith(normalized_keyword):
        stripped_text = _clean_text(
            _USCODE_STATUS_LEADING_SECTION_LABEL_RE.sub("", normalized_text, count=1)
        )
        stripped_text = _clean_text(
            _USCODE_STATUS_LEADING_SECTION_NUMBERS_RE.sub("", stripped_text, count=1)
        )
        lowered_stripped_text = stripped_text.lower()
        if not stripped_text or not lowered_stripped_text.startswith(normalized_keyword):
            return ""
        normalized_text = stripped_text
        lowered_text = lowered_stripped_text
    if lowered_text == normalized_keyword:
        return normalized_text
    if re.match(
        rf"^{re.escape(normalized_keyword)}\s+from\s+the\s+u(?:\b|\s)",
        lowered_text,
    ):
        return normalized_text.split(maxsplit=1)[0]
    return ""


def _uscode_status_clause_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    max_tokens: int = 48,
) -> str:
    """Return the bounded source clause carrying U.S.C. editorial status."""
    if not _formula_has_uscode_context(formula):
        return ""
    source_text = str(document.normalized_text or "")
    if not source_text:
        return ""
    for keyword in _uscode_status_clause_keywords(
        document=document,
        formula=formula,
    ):
        clause = _status_clause_around_keyword(source_text, keyword)
        if not clause:
            continue
        clause = _clean_status_clause_surface(clause)
        clause = _extend_short_status_clause_with_editorial_tail(
            source_text,
            clause,
            keyword,
            max_tokens=max_tokens,
        )
        tokens = _tokenize_for_similarity(clause)
        if tokens and len(tokens) <= max_tokens:
            return clause
    return ""


def _uscode_status_clause_keywords(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[str]:
    keywords: List[str] = []

    def add(value: str) -> None:
        normalized = _clean_text(value).lower()
        if normalized and normalized in _USCODE_FALLBACK_STATUS_KEYWORDS:
            if normalized not in keywords:
                keywords.append(normalized)

    fallback_rule = _clean_text(formula.metadata.get("fallback_rule") or "")
    add(_derived_status_keyword(formula=formula, fallback_rule=fallback_rule))
    add(_clean_text(formula.metadata.get("status_keyword") or ""))
    predicate_text = _clean_text(formula.predicate.name).replace("_", " ").lower()
    for keyword in _USCODE_FALLBACK_STATUS_KEYWORDS:
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", predicate_text):
            add(keyword)
    add(_status_keyword_from_source_text(str(document.normalized_text or "")))
    return keywords


def _uscode_reclassification_detail_slots(
    text: str,
    *,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    """Extract bounded source/target section details from editorial transfers."""
    normalized = _clean_text(text)
    prefix = _clean_text(slot_prefix).replace(" ", "_")
    if not normalized or not prefix:
        return []

    slots: List[Tuple[str, str]] = []

    def add(slot_suffix: str, value: str) -> None:
        cleaned = _clean_text(value)
        if cleaned:
            slots.append((f"{prefix}_{slot_suffix}", cleaned))
            slots.append((f"uscode_reclassification_{slot_suffix}", cleaned))

    source_match = re.search(
        rf"\bSection\s+(?P<section>{_USCODE_SECTION_TOKEN_PATTERN})\s+"
        r"was\s+editorially\s+reclassified\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if source_match is not None:
        add("source_section", source_match.group("section"))

    target_match = re.search(
        rf"\breclassified\s+as\s+section\s+"
        rf"(?P<section>{_USCODE_SECTION_TOKEN_PATTERN})"
        rf"(?:\s+of\s+(?:(?:this|such)\s+title|Title\s+(?P<title>\d+[A-Za-z]*)))?",
        normalized,
        flags=re.IGNORECASE,
    )
    if target_match is not None:
        target_section = _clean_text(target_match.group("section"))
        target_title = _clean_text(target_match.group("title") or "")
        add("target_section", target_section)
        if target_title:
            add("target_title", target_title)
            add("target_citation", f"{target_title} U.S.C. {target_section}")
        else:
            add("target_citation", f"this title section {target_section}")

    return _unique_slot_values(slots)


def _uscode_editorial_status_detail_slots(
    text: str,
    *,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    """Extract normalized U.S.C. editorial status transition details."""
    normalized = _clean_text(text)
    prefix = _clean_text(slot_prefix).replace(" ", "_")
    if not normalized or not prefix:
        return []

    slots = list(_uscode_reclassification_detail_slots(normalized, slot_prefix=prefix))

    def add(slot_suffix: str, value: str) -> None:
        cleaned = _clean_text(value)
        if cleaned:
            slots.append((f"{prefix}_{slot_suffix}", cleaned))
            slots.append((f"uscode_editorial_status_{slot_suffix}", cleaned))

    status_match = re.search(
        r"\b(?P<keyword>renumbered|reclassified|transferred)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if status_match is not None:
        add("keyword", status_match.group("keyword").lower())

    target_match = re.search(
        rf"\b(?:renumbered|reclassified|transferred)"
        rf"(?:\s+(?:as|to|from))?\s+"
        rf"(?:§{{1,2}}\s*|secs?\.?\s*|sections?\s+)?"
        rf"(?P<section>{_USCODE_SECTION_LIST_PATTERN})"
        rf"(?:\s+of\s+(?:(?:this|such)\s+title|Title\s+(?P<title>\d+[A-Za-z]*)))?",
        normalized,
        flags=re.IGNORECASE,
    )
    if target_match is not None:
        target_section = _clean_text(target_match.group("section"))
        target_title = _clean_text(target_match.group("title") or "")
        add("target_section", target_section)
        if target_title:
            add("target_title", target_title)
            add("target_citation", f"{target_title} U.S.C. {target_section}")
        else:
            add("target_citation", f"this title section {target_section}")

    return _unique_slot_values(slots)


def _status_clause_around_keyword(source_text: str, keyword: str) -> str:
    normalized_keyword = _clean_text(keyword).lower()
    if not normalized_keyword:
        return ""
    match = re.search(
        rf"(?<!\w){re.escape(normalized_keyword)}(?:d|ed|s)?(?!\w)",
        source_text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return ""
    start = _status_clause_start(source_text, match.start())
    end = _status_clause_end(source_text, match.end())
    return _clean_text(source_text[start:end])


def _extend_short_status_clause_with_editorial_tail(
    source_text: str,
    clause: str,
    keyword: str,
    *,
    max_tokens: int,
) -> str:
    """Attach bounded Pub. L./Section context to one-word status headings."""
    cleaned_clause = _clean_text(clause)
    normalized_keyword = _clean_text(keyword).lower()
    if not cleaned_clause or cleaned_clause.lower() != normalized_keyword:
        return cleaned_clause
    match = re.search(
        rf"(?<!\w){re.escape(normalized_keyword)}(?:d|ed|s)?(?!\w)",
        source_text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return cleaned_clause
    first_end = _status_clause_end(source_text, match.end())
    if first_end >= len(source_text):
        return cleaned_clause
    tail = source_text[first_end:].lstrip(" \t\r\n-–—:;,.")
    if not tail:
        return cleaned_clause
    if not re.match(r"(?i)(?:Pub\.?\s+L\.?|Public\s+Law|Section\b|Act\b)", tail):
        return cleaned_clause
    tail_end = _status_clause_end(tail, 0)
    tail_clause = _clean_status_clause_surface(tail[:tail_end])
    if not tail_clause:
        return cleaned_clause
    combined = _clean_text(f"{cleaned_clause} {tail_clause}")
    tokens = _tokenize_for_similarity(combined)
    if not tokens:
        return cleaned_clause
    if len(tokens) <= max_tokens:
        return combined
    return _clean_text(" ".join(tokens[:max_tokens]))


def _status_clause_start(source_text: str, match_start: int) -> int:
    start = 0
    for index in range(match_start - 1, -1, -1):
        if source_text[index] in "\n;":
            start = index + 1
            break
        if source_text[index] == "." and _period_marks_status_clause_boundary(
            source_text,
            index,
        ):
            start = index + 1
            break
    return max(0, start)


def _status_clause_end(source_text: str, match_end: int) -> int:
    for index in range(match_end, len(source_text)):
        if source_text[index] in "\n;":
            return index
        if source_text[index] == "." and _period_marks_status_clause_boundary(
            source_text,
            index,
        ):
            return index + 1
    return len(source_text)


def _period_marks_status_clause_boundary(source_text: str, index: int) -> bool:
    before = source_text[max(0, index - 16) : index]
    token_match = re.search(r"([A-Za-z]+)\s*$", before)
    previous_token = token_match.group(1).lower() if token_match else ""
    return previous_token not in {
        "act",
        "apr",
        "aug",
        "ch",
        "dec",
        "div",
        "feb",
        "jan",
        "jul",
        "jun",
        "l",
        "mar",
        "nov",
        "oct",
        "pub",
        "sec",
        "sep",
        "sept",
        "stat",
    }


def _clean_status_clause_surface(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    cleaned = _clean_text(_USCODE_LEADING_SECTION_REF_RE.sub("", cleaned, count=1))
    cleaned = _strip_uscode_gpo_attribution_fragment(cleaned)
    cleaned = cleaned.lstrip(" \t\r\n-–—:;,.")
    cleaned = _strip_uscode_editorial_status_prefix(cleaned)
    cleaned = _TRAILING_SECTION_PUNCT_RE.sub("", cleaned)
    return _clean_text(cleaned)


def _strip_uscode_editorial_status_prefix(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    status_heading_re = re.compile(
        rf"^(?:{'|'.join(re.escape(keyword) for keyword in _USCODE_FALLBACK_STATUS_KEYWORDS)})"
        r"\s+(?=Editorial Notes|Codification|References in Text|Historical and Revision Notes|"
        r"Prior Provisions|Amendments|Statutory Notes and Related Subsidiaries)\b",
        flags=re.IGNORECASE,
    )
    while True:
        updated = _clean_text(status_heading_re.sub("", cleaned, count=1))
        for label in _USCODE_EDITORIAL_NOTE_LABELS:
            updated = _clean_text(
                re.sub(
                    rf"^{re.escape(label)}\b",
                    "",
                    updated,
                    count=1,
                    flags=re.IGNORECASE,
                )
            )
        updated = updated.lstrip(" \t\r\n-–—:;,.")
        if updated == cleaned:
            return cleaned
        cleaned = updated


def _formula_has_uscode_context(formula: ModalIRFormula) -> bool:
    citation = _clean_text(formula.provenance.citation or "")
    if citation and _USC_CITATION_RE.match(citation):
        return True
    source_id = _clean_text(formula.provenance.source_id or "")
    if source_id and _USCODE_SOURCE_ID_RE.match(source_id):
        return True
    return source_id.lower().startswith("us-code-")


def _strip_uscode_gpo_attribution_fragment(text: str) -> str:
    normalized = _clean_text(text)
    if not normalized:
        return ""
    stripped = _clean_text(_USCODE_GPO_ATTRIBUTION_RE.sub("", normalized))
    if stripped != normalized:
        return stripped
    return _clean_text(_USCODE_GPO_ATTRIBUTION_FRAGMENT_RE.sub("", normalized))


def _source_identifier_phrases(document: ModalIRDocument) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    for source_id in _document_source_ids(document):
        for slot, value in _source_id_slots(source_id):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )
    return phrases


def _document_citation_phrases(document: ModalIRDocument) -> List[DecodedModalPhrase]:
    citation = _clean_text(document.metadata.get("citation") or "")
    if not citation:
        if document.formulas:
            return []
        inferred_citations = _inferred_citations_from_source_ids(
            _document_source_ids(document)
        )
        if not inferred_citations:
            return []
        phrases: List[DecodedModalPhrase] = []
        for inferred_citation in inferred_citations:
            phrases.append(
                DecodedModalPhrase(
                    text=inferred_citation,
                    slot="citation",
                    provenance_only=True,
                )
            )
            phrases.append(
                DecodedModalPhrase(
                    text="source_id_inferred",
                    slot="citation_derivation",
                    provenance_only=True,
                )
            )
            for slot, value in _citation_slots(inferred_citation):
                phrases.append(
                    DecodedModalPhrase(
                        text=value,
                        slot=slot,
                        provenance_only=True,
                    )
                )
        return phrases
    formula_citations = {
        _clean_text(formula.provenance.citation or "")
        for formula in document.formulas
        if _clean_text(formula.provenance.citation or "")
    }
    if citation in formula_citations:
        return []
    phrases: List[DecodedModalPhrase] = [
        DecodedModalPhrase(
            text=citation,
            slot="citation",
            provenance_only=True,
        )
    ]
    for slot, value in _citation_slots(citation):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
    return phrases


def _document_provenance_alignment_phrases(
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    citation = _clean_text(document.metadata.get("citation") or "")
    if not citation and not document.formulas:
        inferred_citations = _inferred_citations_from_source_ids(
            _document_source_ids(document)
        )
        if inferred_citations:
            citation = inferred_citations[0]
    if not citation:
        return []
    phrases: List[DecodedModalPhrase] = []
    seen: set[Tuple[str, str]] = set()
    for source_id in _document_source_ids(document):
        for slot, value in _provenance_alignment_slots(
            source_id=source_id,
            citation=citation,
        ):
            marker = (slot, value)
            if marker in seen:
                continue
            seen.add(marker)
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )
    return phrases


def _document_modal_family_count_phrases(
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    for slot, value in _modal_family_count_slots(
        document.metadata.get("modal_family_counts"),
        formulas=document.formulas,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
    return phrases


def _autoencoder_modal_family_guidance_phrases(
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    for slot, value in _autoencoder_modal_family_guidance_slots(document):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
    return phrases


def _autoencoder_modal_family_guidance_slots(
    document: ModalIRDocument,
) -> List[Tuple[str, str]]:
    slots: List[Tuple[str, str]] = []
    for entry in _autoencoder_guidance_entries(document):
        diagnostics = entry.get("pipeline_stage_diagnostics")
        if isinstance(diagnostics, Mapping):
            mismatch = diagnostics.get("modal_family_cue_mismatch")
            if isinstance(mismatch, bool):
                slots.append(
                    (
                        "autoencoder_modal_family_cue_mismatch",
                        str(mismatch).lower(),
                    )
                )
            gap = _clean_text(diagnostics.get("modal_family_target_probability_gap") or "")
            if gap:
                slots.append(("autoencoder_modal_family_target_probability_gap", gap))
                gap_bucket = _probability_gap_bucket(gap)
                if gap_bucket:
                    slots.append(
                        (
                            "autoencoder_modal_family_target_probability_gap_bucket",
                            gap_bucket,
                        )
                    )
        for stage_slot in (
            "primary_pipeline_stage",
            "pipeline_stage",
        ):
            stage_value = _clean_text(entry.get(stage_slot) or "")
            if stage_value:
                slots.append((f"autoencoder_{stage_slot}", stage_value))
                slots.extend(
                    _typed_identifier_slots(
                        stage_value,
                        slot_prefix=f"autoencoder_{stage_slot}",
                    )
                )
        for focus in _string_list(entry.get("pipeline_stage_focus")):
            slots.append(("autoencoder_pipeline_stage_focus", focus))
            slots.extend(
                _typed_identifier_slots(
                    focus,
                    slot_prefix="autoencoder_pipeline_stage_focus",
                )
            )
        family_features = _modal_family_guidance_features(entry)
        for rank, family in enumerate(family_features, start=1):
            slots.append(("autoencoder_modal_family_prototype", family))
            slots.append(
                ("autoencoder_modal_family_prototype_ranked", f"{rank}:{family}")
            )
            slots.append((f"autoencoder_modal_family_prototype_{family}", str(rank)))
        if len(family_features) >= 2:
            slots.append(
                (
                    "autoencoder_modal_family_prototype_pair",
                    f"{family_features[0]}->{family_features[1]}",
                )
            )
        for rank, view in enumerate(_legal_ir_view_guidance_features(entry), start=1):
            slots.append(("autoencoder_legal_ir_view_prototype", view))
            slots.append(
                ("autoencoder_legal_ir_view_prototype_ranked", f"{rank}:{view}")
            )
            for slot, value in _typed_identifier_slots(
                view.replace(".", "_"),
                slot_prefix="autoencoder_legal_ir_view_prototype",
            ):
                slots.append((slot, value))
        for pair in _family_legal_ir_view_guidance_pairs(entry):
            slots.append(("autoencoder_family_legal_ir_view_pair", pair))
    for pair in _autoencoder_family_pair_guidance_values(document):
        slots.append(("autoencoder_modal_family_guided_pair", pair))
    for family in _autoencoder_target_family_guidance_values(document):
        slots.append(("autoencoder_modal_target_family_guidance", family))
    return _unique_slot_values(slots)


def _autoencoder_guidance_entries(document: ModalIRDocument) -> List[Mapping[str, Any]]:
    entries: List[Mapping[str, Any]] = []

    def add_mapping(value: Any) -> None:
        if isinstance(value, Mapping) and value not in entries:
            entries.append(value)

    metadata_sources: List[Any] = [document.metadata]
    if isinstance(document.frame_logic.metadata, Mapping):
        metadata_sources.append(document.frame_logic.metadata)
    for metadata in metadata_sources:
        if not isinstance(metadata, Mapping):
            continue
        add_mapping(metadata)
        for evidence in _mapping_sequence(metadata.get("hint_evidence")):
            add_mapping(evidence)
        for evidence in _mapping_sequence(metadata.get("evidence")):
            add_mapping(evidence)
        for evidence in _mapping_sequence(metadata.get("evidences")):
            add_mapping(evidence)
    return entries


def _autoencoder_guidance_nested_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text.startswith("{"):
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, Mapping):
            return parsed
    return None


def _autoencoder_family_pair_guidance_values(
    document: ModalIRDocument,
    *,
    source_family: str = "",
) -> List[str]:
    """Return explicit source->target family-pair hints from guidance bundles."""
    normalized_source = _slot_safe_family_key(
        _clean_text(source_family).lower()
    )
    pairs: List[str] = []

    def add_pair(value: Any) -> None:
        text = _clean_text(str(value or "")).lower().replace(" ", "")
        if "->" not in text:
            return
        source, target = text.split("->", 1)
        source = _slot_safe_family_key(source)
        target = _slot_safe_family_key(target)
        if not source or not target:
            return
        if normalized_source and source != normalized_source:
            return
        pair = f"{source}->{target}"
        if pair not in pairs:
            pairs.append(pair)

    for entry in _autoencoder_guidance_entries(document):
        sources: List[Mapping[str, Any]] = [entry]
        for key in ("bundle", "semantic_bundle", "vector_bundle", "program_bundle"):
            nested = _autoencoder_guidance_nested_mapping(entry.get(key))
            if nested is not None:
                sources.append(nested)
        for source in sources:
            for key in (
                "family_pair",
                "family_pairs",
                "target_family_pair",
                "target_family_pairs",
            ):
                value = source.get(key)
                if isinstance(value, str):
                    add_pair(value)
                else:
                    for item in _string_list(value):
                        add_pair(item)
    return pairs


def _autoencoder_family_pair_target_guidance_values(
    document: ModalIRDocument,
    *,
    source_family: str,
) -> List[str]:
    targets: List[str] = []
    for pair in _autoencoder_family_pair_guidance_values(
        document,
        source_family=source_family,
    ):
        _source, target = pair.split("->", 1)
        if target and target not in targets:
            targets.append(target)
    return targets


def _autoencoder_target_family_guidance_values(
    document: ModalIRDocument,
) -> List[str]:
    """Return explicit target-family hints for typed IR reconstruction."""
    targets: List[str] = []

    def add_target(value: Any) -> None:
        family = _slot_safe_family_key(
            _clean_text(str(value or "")).lower()
        )
        if family and family not in targets:
            targets.append(family)

    for entry in _autoencoder_guidance_entries(document):
        for field in ("target_family", "selected_family"):
            add_target(entry.get(field))
        for family in _autoencoder_target_family_distribution_values(entry):
            add_target(family)
        for family in _autoencoder_rule_gap_target_family_values(entry):
            add_target(family)
    return targets


def _autoencoder_target_family_distribution_values(
    entry: Mapping[str, Any],
) -> List[str]:
    """Return target families underrepresented in an introspection distribution."""
    families: List[str] = []
    distributions: List[Mapping[str, Any]] = []

    def add_distribution(value: Any) -> None:
        if isinstance(value, Mapping):
            distributions.append(value)

    add_distribution(entry.get("family_distribution"))
    for key in ("counterexample", "counterexamples", "evidence", "evidences"):
        for nested in _mapping_sequence(entry.get(key)):
            add_distribution(nested.get("family_distribution"))

    for distribution in distributions:
        ranked: List[Tuple[float, str]] = []
        for family, raw_stats in distribution.items():
            if not isinstance(raw_stats, Mapping):
                continue
            normalized_family = _slot_safe_family_key(_clean_text(str(family)).lower())
            if not normalized_family:
                continue
            try:
                target_probability = float(raw_stats.get("target_probability", 0.0))
                predicted_probability = float(
                    raw_stats.get("predicted_probability", 0.0)
                )
            except (TypeError, ValueError):
                continue
            gap = target_probability - predicted_probability
            if target_probability >= 0.001 and gap > 0.0:
                ranked.append((gap, normalized_family))
        for _gap, family in sorted(ranked, reverse=True):
            if family not in families:
                families.append(family)
    return families


def _autoencoder_rule_gap_target_family_values(
    entry: Mapping[str, Any],
) -> List[str]:
    """Extract deterministic target families from accepted rule-gap prose."""
    families: List[str] = []

    def add(value: Any) -> None:
        family = _slot_safe_family_key(_clean_text(str(value or "")).lower())
        if family and family not in families:
            families.append(family)

    text_parts: List[str] = []

    def collect_text(value: Any) -> None:
        if isinstance(value, str):
            cleaned = _clean_text(value)
            if cleaned:
                text_parts.append(cleaned)
        elif isinstance(value, Mapping):
            for key in (
                "missing_semantic_rule",
                "description",
                "expected",
                "observed",
                "objective",
                "normalized_rule_key",
            ):
                collect_text(value.get(key))

    for key in (
        "missing_semantic_rule",
        "description",
        "expected",
        "objective",
        "normalized_rule_key",
    ):
        collect_text(entry.get(key))
    for key in ("counterexample", "counterexamples", "evidence", "evidences"):
        for nested in _mapping_sequence(entry.get(key)):
            collect_text(nested)

    joined = " ".join(text_parts).replace("\\u2192", "->").replace("→", "->")
    lowered = joined.lower()
    for pattern in (
        r"target\s+family\s*\(\s*([a-z_]+)\s*\)",
        r"target_family\s*[:=]\s*['\"]?([a-z_]+)['\"]?",
        r"expected\s+([a-z_]+)\s+family\b",
        r"canonical\s+ir\s+family\s+(?:is|was|=|:)\s+['\"]?([a-z_]+)['\"]?",
        r"canonical\s+(?:modal\s+)?ir\s+(?:hash\s+)?(?:indicates|corresponds\s+to)\s+(?:a\s+)?['\"]?([a-z_]+)['\"]?\s+family\b",
        r"canonical\s+ir\s+specifies\s+['\"]?([a-z_]+)['\"]?\s+semantics",
        r"canonical\s+(?:view|distribution)\s+(?:shows|showed|indicates|indicated)\s+.{0,120}?\b([a-z_]+)\s+probability\b",
        r"target\s+probability\s+(?:is\s+)?[0-9.]+\s+for\s+([a-z_]+)\b",
    ):
        for match in re.finditer(pattern, lowered):
            add(match.group(1))
    return families


def _modal_family_guidance_features(entry: Mapping[str, Any]) -> List[str]:
    families: List[str] = []

    def add(value: str) -> None:
        family = _slot_safe_family_key(_clean_text(value).lower())
        if family and family not in families:
            families.append(family)

    for field in ("family", "predicted_family", "target_family", "selected_family"):
        add(str(entry.get(field) or ""))
    for feature in _guidance_feature_strings(entry):
        normalized = _clean_text(feature)
        lowered = normalized.lower()
        if lowered.startswith("modal-family-prototype:"):
            add(normalized.split(":", 1)[1])
        elif lowered.startswith("family:selected_frame:"):
            add(normalized.rsplit(":", 1)[1])
        elif lowered.startswith("flogic:modal_family:"):
            add(normalized.rsplit(":", 1)[1])
    return families


def _legal_ir_view_guidance_features(entry: Mapping[str, Any]) -> List[str]:
    views: List[str] = []
    for feature in _guidance_feature_strings(entry):
        normalized = _clean_text(feature)
        lowered = normalized.lower()
        if not lowered.startswith("legal-ir-view-prototype:"):
            continue
        view = _clean_text(normalized.split(":", 1)[1])
        if view and view not in views:
            views.append(view)
    return views


def _family_legal_ir_view_guidance_pairs(entry: Mapping[str, Any]) -> List[str]:
    pairs: List[str] = []
    for feature in _guidance_feature_strings(entry):
        normalized = _clean_text(feature)
        lowered = normalized.lower()
        if not lowered.startswith("family-legal-ir-view-prototype:"):
            continue
        pair = _clean_text(normalized.split(":", 1)[1])
        if pair and pair not in pairs:
            pairs.append(pair)
    return pairs


def _guidance_feature_strings(entry: Mapping[str, Any]) -> List[str]:
    features: List[str] = []
    for field in (
        "top_embedding_features",
        "top_family_features",
        "top_embedding_contributions",
        "top_family_contributions",
        "frame_features",
        "feature_keys",
        "features",
    ):
        for feature in _feature_strings(entry.get(field)):
            if feature not in features:
                features.append(feature)
    return features


def _feature_strings(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        feature = _clean_text(value)
        return [feature] if feature else []
    if isinstance(value, Mapping):
        features: List[str] = []
        for key in ("feature", "feature_key", "name", "value"):
            feature = _clean_text(value.get(key) or "")
            if feature and feature not in features:
                features.append(feature)
        return features
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        features: List[str] = []
        for item in value:
            for feature in _feature_strings(item):
                if feature not in features:
                    features.append(feature)
        return features
    return []


def _mapping_sequence(value: Any) -> List[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        cleaned = _clean_text(value)
        return [cleaned] if cleaned else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result: List[str] = []
        for item in value:
            cleaned = _clean_text(item)
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result
    return []


def _probability_gap_bucket(value: str) -> str:
    try:
        gap = abs(float(value))
    except (TypeError, ValueError):
        return ""
    if gap == 0.0:
        return "zero"
    if gap < 0.1:
        return "lt_0_1"
    if gap < 0.25:
        return "0_1_to_0_25"
    if gap < 0.5:
        return "0_25_to_0_5"
    return "gte_0_5"


def _selected_frame_modal_family_phrases(
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    if not _selected_frame(document):
        return []
    phrases: List[DecodedModalPhrase] = []
    for slot, value in _selected_frame_modal_family_slots(
        document.metadata.get("modal_family_counts"),
        formulas=document.formulas,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
    return phrases


def _selected_frame_modal_family_slots(
    raw_counts: Any,
    *,
    formulas: Sequence[ModalIRFormula] = (),
) -> List[Tuple[str, str]]:
    slots: List[Tuple[str, str]] = []
    for rank, (family, count) in enumerate(
        _resolved_modal_family_counts(raw_counts, formulas=formulas),
        start=1,
    ):
        safe_family = _slot_safe_family_key(family)
        if not safe_family:
            continue
        slots.extend(
            (
                ("selected_frame_modal_family", safe_family),
                ("selected_frame_modal_family_ranked", f"{rank}:{safe_family}"),
                ("selected_frame_modal_family_count", f"{safe_family}:{count}"),
                (
                    "selected_frame_modal_family_count_ranked",
                    f"{rank}:{safe_family}:{count}",
                ),
                ("selected_frame_modal_family_count_value", count),
                (f"selected_frame_modal_family_{safe_family}", count),
            )
        )
        slots.extend(
            _numeric_signature_slots(
                count,
                slot_prefix="selected_frame_modal_family_count_value",
            )
        )
        slots.extend(
            _numeric_signature_slots(
                count,
                slot_prefix=f"selected_frame_modal_family_{safe_family}",
            )
        )
    return _unique_slot_values(slots)


def _modal_family_count_slots(
    raw_counts: Any,
    *,
    formulas: Sequence[ModalIRFormula] = (),
) -> List[Tuple[str, str]]:
    slots: List[Tuple[str, str]] = []
    for rank, (family, count) in enumerate(
        _resolved_modal_family_counts(raw_counts, formulas=formulas),
        start=1,
    ):
        safe_family = _slot_safe_family_key(family)
        if not safe_family:
            continue
        slots.extend(
            (
                ("modal_family_count", f"{family}:{count}"),
                ("modal_family_count_ranked", f"{rank}:{family}:{count}"),
                ("modal_family_count_family", family),
                ("modal_family_count_value", count),
                (f"modal_family_count_{safe_family}", count),
            )
        )
        slots.extend(
            _numeric_signature_slots(
                count,
                slot_prefix="modal_family_count_value",
            )
        )
        slots.extend(
            _numeric_signature_slots(
                count,
                slot_prefix=f"modal_family_count_{safe_family}",
            )
        )
    return _unique_slot_values(slots)


def _resolved_modal_family_counts(
    raw_counts: Any,
    *,
    formulas: Sequence[ModalIRFormula] = (),
) -> List[Tuple[str, str]]:
    metadata_counts = _normalized_modal_family_counts(raw_counts)
    if metadata_counts:
        return metadata_counts
    formula_counts: Dict[str, int] = {}
    for formula in formulas:
        family = _slot_safe_family_key(_clean_text(formula.operator.family).lower())
        if not family:
            continue
        formula_counts[family] = formula_counts.get(family, 0) + 1
    return sorted(
        (
            (family, str(count))
            for family, count in formula_counts.items()
        ),
        key=lambda item: item[0],
    )


def _normalized_modal_family_counts(raw_counts: Any) -> List[Tuple[str, str]]:
    if not isinstance(raw_counts, Mapping):
        return []
    normalized: Dict[str, str] = {}
    for raw_family, raw_count in raw_counts.items():
        family = _slot_safe_family_key(_clean_text(raw_family).lower())
        if not family:
            continue
        count = _coerce_non_negative_int(raw_count)
        if count is None:
            continue
        normalized[family] = str(count)
    return sorted(normalized.items(), key=lambda item: item[0])


def _coerce_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        try:
            float_value = float(value)
        except (TypeError, ValueError):
            return None
        if not float_value.is_integer():
            return None
        number = int(float_value)
    if number < 0:
        return None
    return number


def _slot_safe_family_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").lower()).strip("_")
    return normalized


def _slot_safe_family_pair_key(value: str) -> str:
    normalized = _clean_text(value).lower()
    if not normalized:
        return ""
    if "->" in normalized:
        left_raw, right_raw = normalized.split("->", 1)
        left = _slot_safe_family_key(left_raw)
        right = _slot_safe_family_key(right_raw)
        if left and right:
            return f"{left}_{right}"
    return _slot_safe_family_key(normalized)


def _document_source_ids(document: ModalIRDocument) -> List[str]:
    source_ids: List[str] = []
    document_id = _clean_text(document.document_id)
    if document_id:
        source_ids.append(document_id)
    for formula in document.formulas:
        source_id = _clean_text(formula.provenance.source_id)
        if source_id and source_id not in source_ids:
            source_ids.append(source_id)
    return source_ids


def _inferred_citations_from_source_ids(source_ids: Sequence[str]) -> List[str]:
    citations: List[str] = []
    for source_id in source_ids:
        citation = _source_id_inferred_citation(source_id)
        if citation and citation not in citations:
            citations.append(citation)
    return citations


def _source_id_inferred_citation(source_id: str) -> str:
    normalized_source_id = _clean_text(source_id)
    if not normalized_source_id:
        return ""
    source_slot_map = _slot_value_map(_source_id_slots(normalized_source_id))
    title = _clean_text(source_slot_map.get("source_id_title") or "")
    raw_section = _clean_text(
        source_slot_map.get("source_id_section_raw")
        or source_slot_map.get("source_id_section")
        or ""
    )
    if title and raw_section:
        return f"{title} U.S.C. {raw_section}"
    canonical = _clean_text(source_slot_map.get("source_id_citation_canonical") or "")
    if canonical:
        return canonical
    normalized_section = _clean_text(
        source_slot_map.get("source_id_section_normalized")
        or source_slot_map.get("source_id_section")
        or ""
    )
    return _canonical_usc_citation(title, normalized_section)


def _source_id_slots(source_id: str) -> List[Tuple[str, str]]:
    cleaned = _clean_text(source_id)
    if not cleaned:
        return []
    match = _USCODE_SOURCE_ID_RE.match(cleaned)
    if not match:
        return [("source_id", cleaned)]
    scheme = _clean_text(match.group("scheme")).lower()
    title = _clean_text(match.group("title"))
    section = _clean_text(match.group("section"))
    digest = _clean_text(match.group("digest")).lower()
    normalized_section = _TRAILING_SECTION_PUNCT_RE.sub("", section)
    section_trailing_punct = _section_trailing_punct(
        raw_section=section,
        normalized_section=normalized_section,
    )

    slots: List[Tuple[str, str]] = [
        ("source_id", cleaned),
        ("source_id_scheme", scheme),
    ]
    title_number = ""
    if title:
        slots.append(("source_id_title", title))
        slots.extend(_typed_identifier_slots(title, slot_prefix="source_id_title"))
        title_match = _CITATION_SECTION_PART_RE.fullmatch(title)
        if title_match:
            title_number = _clean_text(title_match.group("number"))
            title_suffix = _clean_text(title_match.group("suffix"))
            if title_number:
                slots.append(("source_id_title_number", title_number))
                slots.extend(
                    _numeric_signature_slots(
                        title_number,
                        slot_prefix="source_id_title_number",
                    )
                )
            if title_suffix:
                slots.append(("source_id_title_suffix", title_suffix))

    if section:
        slots.append(("source_id_section", section))
        slots.append(("source_id_section_raw", section))
    if normalized_section:
        slots.append(("source_id_section_normalized", normalized_section))
    if section_trailing_punct:
        slots.append(("source_id_section_trailing_punct", section_trailing_punct))
        slots.append(("source_id_section_has_trailing_punct", "true"))
        slots.append(
            (
                "source_id_section_trailing_punct_count",
                str(len(section_trailing_punct)),
            )
        )
        punct_kind = _section_trailing_punct_kind(section_trailing_punct)
        if punct_kind:
            slots.append(("source_id_section_trailing_punct_kind", punct_kind))
    else:
        slots.append(("source_id_section_has_trailing_punct", "false"))
        slots.append(("source_id_section_trailing_punct_count", "0"))
    section_for_slots = normalized_section or section
    source_id_canonical = _canonical_usc_citation(title, section_for_slots)
    if source_id_canonical:
        slots.append(("source_id_citation_canonical", source_id_canonical))
    source_id_title_section_key = _title_section_coordinate(title, section_for_slots)
    if source_id_title_section_key:
        slots.append(("source_id_title_section_key", source_id_title_section_key))
        slots.append(
            (
                "source_id_title_section_key_normalized",
                source_id_title_section_key.lower(),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                source_id_title_section_key.replace(":", "_"),
                slot_prefix="source_id_title_section_key",
            )
        )
    if section_for_slots:
        section_slots = _source_id_section_slots(section_for_slots)
        slots.extend(section_slots)
        section_slot_map = _slot_value_map(section_slots)
        slots.extend(
            _section_style_slots(
                slot_namespace="source_id",
                section_slot_map=section_slot_map,
                has_trailing_punct=bool(section_trailing_punct),
            )
        )
        source_style_map = _slot_value_map(
            [
                slot
                for slot in slots
                if slot[0] in {"source_id_section_style", "source_id_section_style_canonical"}
            ]
        )
        slots.extend(
            _title_section_style_slots(
                slot_namespace="source_id",
                title=title,
                section_style=_clean_text(
                    source_style_map.get("source_id_section_style") or ""
                ),
                section_style_canonical=_clean_text(
                    source_style_map.get("source_id_section_style_canonical") or ""
                ),
            )
        )
        slots.extend(
            _section_structure_slots(
                slot_namespace="source_id",
                title=title,
                section_signature=_clean_text(
                    section_slot_map.get("source_id_section_signature") or ""
                ),
                section_profile=_clean_text(
                    section_slot_map.get("source_id_section_component_profile") or ""
                ),
            )
        )
        slots.extend(
            _title_section_number_relation_slots(
                slot_namespace="source_id",
                title_number=title_number,
                section_slot_map=section_slot_map,
            )
        )
        slots.extend(
            _typed_identifier_slots(
                section_for_slots,
                slot_prefix="source_id_section",
            )
        )

    if digest:
        slots.append(("source_id_digest", digest))
    return _unique_slot_values(slots)


def _source_id_section_slots(section: str) -> List[Tuple[str, str]]:
    slots: List[Tuple[str, str]] = []
    for slot, value in _citation_section_slots(section):
        if slot.startswith("citation_section"):
            slots.append((slot.replace("citation_section", "source_id_section", 1), value))
    return slots


def _provenance_alignment_slots(
    *,
    source_id: str,
    citation: str,
) -> List[Tuple[str, str]]:
    normalized_source_id = _clean_text(source_id)
    normalized_citation = _clean_text(citation)
    if not normalized_source_id or not normalized_citation:
        return []
    source_slot_map = _slot_value_map(_source_id_slots(normalized_source_id))
    citation_slot_map = _slot_value_map(_citation_slots(normalized_citation))
    source_title = _clean_text(source_slot_map.get("source_id_title") or "")
    citation_title = _clean_text(citation_slot_map.get("citation_title") or "")
    source_section = _clean_text(
        source_slot_map.get("source_id_section_normalized")
        or source_slot_map.get("source_id_section")
        or ""
    )
    citation_section = _clean_text(
        citation_slot_map.get("citation_section_normalized")
        or citation_slot_map.get("citation_section")
        or ""
    )
    source_key = _clean_text(
        source_slot_map.get("source_id_title_section_key_normalized")
        or source_slot_map.get("source_id_title_section_key")
        or ""
    )
    citation_key = _clean_text(
        citation_slot_map.get("citation_title_section_key_normalized")
        or citation_slot_map.get("citation_title_section_key")
        or ""
    )
    source_canonical = _clean_text(
        source_slot_map.get("source_id_citation_canonical") or ""
    )
    citation_canonical = _clean_text(citation_slot_map.get("citation_canonical") or "")
    source_section_raw = _clean_text(
        source_slot_map.get("source_id_section_raw")
        or source_slot_map.get("source_id_section")
        or ""
    )
    citation_section_raw = _clean_text(
        citation_slot_map.get("citation_section_raw")
        or citation_slot_map.get("citation_section")
        or ""
    )
    source_section_trailing_punct = _clean_text(
        source_slot_map.get("source_id_section_trailing_punct") or ""
    )
    citation_section_trailing_punct = _clean_text(
        citation_slot_map.get("citation_section_trailing_punct") or ""
    )
    source_has_trailing_punct = _clean_text(
        source_slot_map.get("source_id_section_has_trailing_punct")
        or ("true" if source_section_trailing_punct else "false")
    ).lower()
    citation_has_trailing_punct = _clean_text(
        citation_slot_map.get("citation_section_has_trailing_punct")
        or ("true" if citation_section_trailing_punct else "false")
    ).lower()
    slots: List[Tuple[str, str]] = []
    if source_section_raw and citation_section_raw:
        slots.append(
            (
                "citation_source_id_section_raw_match",
                "true"
                if source_section_raw.lower() == citation_section_raw.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_raw_pair",
                f"{source_section_raw}|{citation_section_raw}",
            )
        )
    if (
        source_has_trailing_punct in {"true", "false"}
        and citation_has_trailing_punct in {"true", "false"}
    ):
        slots.append(
            (
                "citation_source_id_section_trailing_punct_presence_match",
                "true"
                if source_has_trailing_punct == citation_has_trailing_punct
                else "false",
            )
        )
    if (
        source_section_trailing_punct
        or citation_section_trailing_punct
        or (
            source_has_trailing_punct in {"true", "false"}
            and citation_has_trailing_punct in {"true", "false"}
        )
    ):
        slots.append(
            (
                "citation_source_id_section_trailing_punct_match",
                "true"
                if source_section_trailing_punct == citation_section_trailing_punct
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_trailing_punct_pair",
                f"{source_section_trailing_punct or 'none'}|"
                f"{citation_section_trailing_punct or 'none'}",
            )
        )
    if source_title and citation_title:
        slots.append(
            (
                "citation_source_id_title_pair",
                f"{source_title}|{citation_title}",
            )
        )
    if source_section and citation_section:
        slots.append(
            (
                "citation_source_id_section_pair",
                f"{source_section}|{citation_section}",
            )
        )
    if source_key and citation_key:
        slots.append(
            (
                "citation_source_id_title_section_key_pair",
                f"{source_key}|{citation_key}",
            )
        )
    if source_canonical and citation_canonical:
        slots.append(
            (
                "citation_source_id_canonical_pair",
                f"{source_canonical}|{citation_canonical}",
            )
        )
    source_section_signature = _clean_text(
        source_slot_map.get("source_id_section_signature") or ""
    )
    citation_section_signature = _clean_text(
        citation_slot_map.get("citation_section_signature") or ""
    )
    if source_section_signature or citation_section_signature:
        slots.append(
            (
                "citation_source_id_section_signature_pair",
                f"{source_section_signature or 'none'}|"
                f"{citation_section_signature or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_signature_match",
                "true"
                if source_section_signature.lower()
                == citation_section_signature.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_signature_presence_match",
                "true"
                if bool(source_section_signature) == bool(citation_section_signature)
                else "false",
            )
        )
    source_section_profile = _clean_text(
        source_slot_map.get("source_id_section_component_profile") or ""
    )
    citation_section_profile = _clean_text(
        citation_slot_map.get("citation_section_component_profile") or ""
    )
    if source_section_profile or citation_section_profile:
        slots.append(
            (
                "citation_source_id_section_profile_pair",
                f"{source_section_profile or 'none'}|"
                f"{citation_section_profile or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_profile_match",
                "true"
                if source_section_profile.lower() == citation_section_profile.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_profile_presence_match",
                "true"
                if bool(source_section_profile) == bool(citation_section_profile)
                else "false",
            )
        )
    source_section_style = _clean_text(
        source_slot_map.get("source_id_section_style") or ""
    )
    citation_section_style = _clean_text(
        citation_slot_map.get("citation_section_style") or ""
    )
    if source_section_style or citation_section_style:
        slots.append(
            (
                "citation_source_id_section_style_pair",
                f"{source_section_style or 'none'}|{citation_section_style or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_style_match",
                "true"
                if source_section_style.lower() == citation_section_style.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_style_presence_match",
                "true"
                if bool(source_section_style) == bool(citation_section_style)
                else "false",
            )
        )
    source_section_style_canonical = _clean_text(
        source_slot_map.get("source_id_section_style_canonical") or ""
    )
    citation_section_style_canonical = _clean_text(
        citation_slot_map.get("citation_section_style_canonical") or ""
    )
    if source_section_style_canonical or citation_section_style_canonical:
        slots.append(
            (
                "citation_source_id_section_style_canonical_pair",
                f"{source_section_style_canonical or 'none'}|"
                f"{citation_section_style_canonical or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_style_canonical_match",
                "true"
                if source_section_style_canonical.lower()
                == citation_section_style_canonical.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_style_canonical_presence_match",
                "true"
                if bool(source_section_style_canonical)
                == bool(citation_section_style_canonical)
                else "false",
            )
        )
    source_section_suffix_style = _clean_text(
        source_slot_map.get("source_id_section_suffix_style") or ""
    )
    citation_section_suffix_style = _clean_text(
        citation_slot_map.get("citation_section_suffix_style") or ""
    )
    if source_section_suffix_style or citation_section_suffix_style:
        slots.append(
            (
                "citation_source_id_section_suffix_style_pair",
                f"{source_section_suffix_style or 'none'}|"
                f"{citation_section_suffix_style or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_suffix_style_match",
                "true"
                if source_section_suffix_style.lower()
                == citation_section_suffix_style.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_suffix_style_presence_match",
                "true"
                if bool(source_section_suffix_style)
                == bool(citation_section_suffix_style)
                else "false",
            )
        )
    source_section_punctuation_style = _clean_text(
        source_slot_map.get("source_id_section_punctuation_style") or ""
    )
    citation_section_punctuation_style = _clean_text(
        citation_slot_map.get("citation_section_punctuation_style") or ""
    )
    if source_section_punctuation_style or citation_section_punctuation_style:
        slots.append(
            (
                "citation_source_id_section_punctuation_style_pair",
                f"{source_section_punctuation_style or 'none'}|"
                f"{citation_section_punctuation_style or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_punctuation_style_match",
                "true"
                if source_section_punctuation_style.lower()
                == citation_section_punctuation_style.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_punctuation_style_presence_match",
                "true"
                if bool(source_section_punctuation_style)
                == bool(citation_section_punctuation_style)
                else "false",
            )
        )
    source_title_section_signature = _clean_text(
        source_slot_map.get("source_id_title_section_signature_normalized")
        or source_slot_map.get("source_id_title_section_signature")
        or ""
    )
    citation_title_section_signature = _clean_text(
        citation_slot_map.get("citation_title_section_signature_normalized")
        or citation_slot_map.get("citation_title_section_signature")
        or ""
    )
    if source_title_section_signature or citation_title_section_signature:
        slots.append(
            (
                "citation_source_id_title_section_signature_pair",
                f"{source_title_section_signature or 'none'}|"
                f"{citation_title_section_signature or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_title_section_signature_match",
                "true"
                if source_title_section_signature.lower()
                == citation_title_section_signature.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_title_section_signature_presence_match",
                "true"
                if bool(source_title_section_signature)
                == bool(citation_title_section_signature)
                else "false",
            )
        )
    source_title_section_profile = _clean_text(
        source_slot_map.get("source_id_title_section_profile_normalized")
        or source_slot_map.get("source_id_title_section_profile")
        or ""
    )
    citation_title_section_profile = _clean_text(
        citation_slot_map.get("citation_title_section_profile_normalized")
        or citation_slot_map.get("citation_title_section_profile")
        or ""
    )
    if source_title_section_profile or citation_title_section_profile:
        slots.append(
            (
                "citation_source_id_title_section_profile_pair",
                f"{source_title_section_profile or 'none'}|"
                f"{citation_title_section_profile or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_title_section_profile_match",
                "true"
                if source_title_section_profile.lower()
                == citation_title_section_profile.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_title_section_profile_presence_match",
                "true"
                if bool(source_title_section_profile)
                == bool(citation_title_section_profile)
                else "false",
            )
        )
    source_title_number = _clean_text(source_slot_map.get("source_id_title_number") or "")
    citation_title_number = _clean_text(
        citation_slot_map.get("citation_title_number") or ""
    )
    title_number_relation = _primary_terminal_number_relation(
        primary_number=source_title_number,
        terminal_number=citation_title_number,
    )
    if title_number_relation is not None:
        relation, span = title_number_relation
        span_slot = "citation_source_id_title_number_span"
        profile_slot = "citation_source_id_title_number_distance_profile"
        slots.append(("citation_source_id_title_number_relation", relation))
        slots.append((span_slot, span))
        slots.extend(
            _numeric_span_signature_slots(
                slot_prefix=span_slot,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            slots.append((profile_slot, relation_profile))
            slots.extend(
                _typed_identifier_slots(
                    relation_profile,
                    slot_prefix=profile_slot,
                )
            )
    slots.extend(
        _numeric_signature_alignment_slots(
            source_number=source_title_number,
            citation_number=citation_title_number,
            slot_prefix="citation_source_id_title_number_signature",
        )
    )
    source_section_primary_number = _clean_text(
        source_slot_map.get("source_id_section_primary_number")
        or source_slot_map.get("source_id_section_number")
        or ""
    )
    citation_section_primary_number = _clean_text(
        citation_slot_map.get("citation_section_primary_number")
        or citation_slot_map.get("citation_section_number")
        or ""
    )
    section_number_relation = _primary_terminal_number_relation(
        primary_number=source_section_primary_number,
        terminal_number=citation_section_primary_number,
    )
    if section_number_relation is not None:
        relation, span = section_number_relation
        span_slot = "citation_source_id_section_primary_number_span"
        profile_slot = "citation_source_id_section_primary_number_distance_profile"
        slots.append(("citation_source_id_section_primary_number_relation", relation))
        slots.append((span_slot, span))
        slots.extend(
            _numeric_span_signature_slots(
                slot_prefix=span_slot,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            slots.append((profile_slot, relation_profile))
            slots.extend(
                _typed_identifier_slots(
                    relation_profile,
                    slot_prefix=profile_slot,
                )
            )
    slots.extend(
        _numeric_signature_alignment_slots(
            source_number=source_section_primary_number,
            citation_number=citation_section_primary_number,
            slot_prefix="citation_source_id_section_primary_number_signature",
        )
    )
    source_section_terminal_number = _clean_text(
        source_slot_map.get("source_id_section_terminal_number")
        or source_slot_map.get("source_id_section_number")
        or ""
    )
    citation_section_terminal_number = _clean_text(
        citation_slot_map.get("citation_section_terminal_number")
        or citation_slot_map.get("citation_section_number")
        or ""
    )
    section_terminal_number_relation = _primary_terminal_number_relation(
        primary_number=source_section_terminal_number,
        terminal_number=citation_section_terminal_number,
    )
    if section_terminal_number_relation is not None:
        relation, span = section_terminal_number_relation
        span_slot = "citation_source_id_section_terminal_number_span"
        profile_slot = "citation_source_id_section_terminal_number_distance_profile"
        slots.append(("citation_source_id_section_terminal_number_relation", relation))
        slots.append((span_slot, span))
        slots.extend(
            _numeric_span_signature_slots(
                slot_prefix=span_slot,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            slots.append((profile_slot, relation_profile))
            slots.extend(
                _typed_identifier_slots(
                    relation_profile,
                    slot_prefix=profile_slot,
                )
            )
    slots.extend(
        _numeric_signature_alignment_slots(
            source_number=source_section_terminal_number,
            citation_number=citation_section_terminal_number,
            slot_prefix="citation_source_id_section_terminal_number_signature",
        )
    )
    source_section_primary_suffix = _clean_text(
        source_slot_map.get("source_id_section_primary_suffix_normalized")
        or source_slot_map.get("source_id_section_primary_suffix")
        or ""
    )
    citation_section_primary_suffix = _clean_text(
        citation_slot_map.get("citation_section_primary_suffix_normalized")
        or citation_slot_map.get("citation_section_primary_suffix")
        or ""
    )
    if (
        source_section_primary_suffix
        or citation_section_primary_suffix
        or (
            source_section_primary_number
            and citation_section_primary_number
        )
    ):
        slots.append(
            (
                "citation_source_id_section_primary_suffix_pair",
                f"{source_section_primary_suffix or 'none'}|"
                f"{citation_section_primary_suffix or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_primary_suffix_match",
                "true"
                if source_section_primary_suffix.lower()
                == citation_section_primary_suffix.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_primary_suffix_presence_match",
                "true"
                if bool(source_section_primary_suffix)
                == bool(citation_section_primary_suffix)
                else "false",
            )
        )
    source_section_primary_suffix_kind = _clean_text(
        source_slot_map.get("source_id_section_primary_suffix_kind_coarse")
        or source_slot_map.get("source_id_section_primary_suffix_kind")
        or ""
    )
    citation_section_primary_suffix_kind = _clean_text(
        citation_slot_map.get("citation_section_primary_suffix_kind_coarse")
        or citation_slot_map.get("citation_section_primary_suffix_kind")
        or ""
    )
    if (
        source_section_primary_suffix_kind
        or citation_section_primary_suffix_kind
        or (
            source_section_primary_number
            and citation_section_primary_number
        )
    ):
        slots.append(
            (
                "citation_source_id_section_primary_suffix_kind_pair",
                f"{source_section_primary_suffix_kind or 'none'}|"
                f"{citation_section_primary_suffix_kind or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_primary_suffix_kind_match",
                "true"
                if source_section_primary_suffix_kind.lower()
                == citation_section_primary_suffix_kind.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_primary_suffix_kind_presence_match",
                "true"
                if bool(source_section_primary_suffix_kind)
                == bool(citation_section_primary_suffix_kind)
                else "false",
            )
        )
    source_section_terminal_suffix = _clean_text(
        source_slot_map.get("source_id_section_terminal_suffix_normalized")
        or source_slot_map.get("source_id_section_terminal_suffix")
        or ""
    )
    citation_section_terminal_suffix = _clean_text(
        citation_slot_map.get("citation_section_terminal_suffix_normalized")
        or citation_slot_map.get("citation_section_terminal_suffix")
        or ""
    )
    if (
        source_section_terminal_suffix
        or citation_section_terminal_suffix
        or (
            source_section_terminal_number
            and citation_section_terminal_number
        )
    ):
        slots.append(
            (
                "citation_source_id_section_terminal_suffix_pair",
                f"{source_section_terminal_suffix or 'none'}|"
                f"{citation_section_terminal_suffix or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_terminal_suffix_match",
                "true"
                if source_section_terminal_suffix.lower()
                == citation_section_terminal_suffix.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_terminal_suffix_presence_match",
                "true"
                if bool(source_section_terminal_suffix)
                == bool(citation_section_terminal_suffix)
                else "false",
            )
        )
    source_section_terminal_suffix_kind = _clean_text(
        source_slot_map.get("source_id_section_terminal_suffix_kind_coarse")
        or source_slot_map.get("source_id_section_terminal_suffix_kind")
        or ""
    )
    citation_section_terminal_suffix_kind = _clean_text(
        citation_slot_map.get("citation_section_terminal_suffix_kind_coarse")
        or citation_slot_map.get("citation_section_terminal_suffix_kind")
        or ""
    )
    if (
        source_section_terminal_suffix_kind
        or citation_section_terminal_suffix_kind
        or (
            source_section_terminal_number
            and citation_section_terminal_number
        )
    ):
        slots.append(
            (
                "citation_source_id_section_terminal_suffix_kind_pair",
                f"{source_section_terminal_suffix_kind or 'none'}|"
                f"{citation_section_terminal_suffix_kind or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_terminal_suffix_kind_match",
                "true"
                if source_section_terminal_suffix_kind.lower()
                == citation_section_terminal_suffix_kind.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_terminal_suffix_kind_presence_match",
                "true"
                if bool(source_section_terminal_suffix_kind)
                == bool(citation_section_terminal_suffix_kind)
                else "false",
            )
        )
    source_primary_component_signature = _clean_text(
        source_slot_map.get("source_id_section_primary_component_signature") or ""
    )
    citation_primary_component_signature = _clean_text(
        citation_slot_map.get("citation_section_primary_component_signature") or ""
    )
    if source_primary_component_signature and citation_primary_component_signature:
        slots.append(
            (
                "citation_source_id_section_primary_component_signature_match",
                "true"
                if source_primary_component_signature
                == citation_primary_component_signature
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_primary_component_signature_pair",
                f"{source_primary_component_signature}|"
                f"{citation_primary_component_signature}",
            )
        )
    source_terminal_component_signature = _clean_text(
        source_slot_map.get("source_id_section_terminal_component_signature") or ""
    )
    citation_terminal_component_signature = _clean_text(
        citation_slot_map.get("citation_section_terminal_component_signature") or ""
    )
    if source_terminal_component_signature and citation_terminal_component_signature:
        slots.append(
            (
                "citation_source_id_section_terminal_component_signature_match",
                "true"
                if source_terminal_component_signature
                == citation_terminal_component_signature
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_terminal_component_signature_pair",
                f"{source_terminal_component_signature}|"
                f"{citation_terminal_component_signature}",
            )
        )
    source_section_profile = _clean_text(
        source_slot_map.get("source_id_section_component_profile") or ""
    )
    citation_section_profile = _clean_text(
        citation_slot_map.get("citation_section_component_profile") or ""
    )
    if source_section_profile or citation_section_profile:
        slots.append(
            (
                "citation_source_id_section_component_profile_pair",
                f"{source_section_profile or 'none'}|"
                f"{citation_section_profile or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_component_profile_match",
                "true"
                if source_section_profile.lower() == citation_section_profile.lower()
                else "false",
            )
        )
    source_section_is_range = _clean_text(
        source_slot_map.get("source_id_section_is_range") or ""
    ).lower()
    citation_section_is_range = _clean_text(
        citation_slot_map.get("citation_section_is_range") or ""
    ).lower()
    if (
        source_section_is_range in {"true", "false"}
        or citation_section_is_range in {"true", "false"}
    ):
        slots.append(
            (
                "citation_source_id_section_is_range_pair",
                f"{source_section_is_range or 'none'}|"
                f"{citation_section_is_range or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_is_range_match",
                "true"
                if source_section_is_range == citation_section_is_range
                else "false",
            )
        )
    source_range_start = _clean_text(
        source_slot_map.get("source_id_section_range_start") or ""
    )
    citation_range_start = _clean_text(
        citation_slot_map.get("citation_section_range_start") or ""
    )
    source_range_end = _clean_text(
        source_slot_map.get("source_id_section_range_end") or ""
    )
    citation_range_end = _clean_text(
        citation_slot_map.get("citation_section_range_end") or ""
    )
    source_range_connector = _clean_text(
        source_slot_map.get("source_id_section_range_connector") or ""
    )
    citation_range_connector = _clean_text(
        citation_slot_map.get("citation_section_range_connector") or ""
    )
    if (
        source_section_is_range == "true"
        or citation_section_is_range == "true"
        or source_range_start
        or citation_range_start
        or source_range_end
        or citation_range_end
        or source_range_connector
        or citation_range_connector
    ):
        slots.append(
            (
                "citation_source_id_section_range_start_pair",
                f"{source_range_start or 'none'}|{citation_range_start or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_start_match",
                "true"
                if source_range_start.lower() == citation_range_start.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_start_presence_match",
                "true"
                if bool(source_range_start) == bool(citation_range_start)
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_end_pair",
                f"{source_range_end or 'none'}|{citation_range_end or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_end_match",
                "true"
                if source_range_end.lower() == citation_range_end.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_end_presence_match",
                "true"
                if bool(source_range_end) == bool(citation_range_end)
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_connector_pair",
                f"{source_range_connector or 'none'}|"
                f"{citation_range_connector or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_connector_match",
                "true"
                if source_range_connector.lower() == citation_range_connector.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_connector_presence_match",
                "true"
                if bool(source_range_connector) == bool(citation_range_connector)
                else "false",
            )
        )
    if not source_title or not citation_title or not source_section or not citation_section:
        alignment = "unparsed"
        slots.append(("citation_source_id_alignment", alignment))
        slots.extend(
            _citation_source_id_alignment_profile_slots(
                alignment=alignment,
                source_section_raw=source_section_raw,
                citation_section_raw=citation_section_raw,
                source_has_trailing_punct=source_has_trailing_punct,
                citation_has_trailing_punct=citation_has_trailing_punct,
                source_section_trailing_punct=source_section_trailing_punct,
                citation_section_trailing_punct=citation_section_trailing_punct,
            )
        )
        return _unique_slot_values(slots)

    title_match = source_title.lower() == citation_title.lower()
    section_match = source_section.lower() == citation_section.lower()
    slots.append(
        ("citation_source_id_title_match", "true" if title_match else "false")
    )
    slots.append(
        ("citation_source_id_section_match", "true" if section_match else "false")
    )
    if source_key and citation_key:
        slots.append(
            (
                "citation_source_id_title_section_key_match",
                "true" if source_key.lower() == citation_key.lower() else "false",
            )
        )
    if source_canonical and citation_canonical:
        slots.append(
            (
                "citation_source_id_canonical_match",
                "true"
                if source_canonical.lower() == citation_canonical.lower()
                else "false",
            )
        )
    if title_match and section_match:
        alignment = "exact_match"
    elif title_match:
        alignment = "title_only_match"
    elif section_match:
        alignment = "section_only_match"
    else:
        alignment = "mismatch"
    slots.append(("citation_source_id_alignment", alignment))
    slots.extend(
        _citation_source_id_alignment_profile_slots(
            alignment=alignment,
            source_section_raw=source_section_raw,
            citation_section_raw=citation_section_raw,
            source_has_trailing_punct=source_has_trailing_punct,
            citation_has_trailing_punct=citation_has_trailing_punct,
            source_section_trailing_punct=source_section_trailing_punct,
            citation_section_trailing_punct=citation_section_trailing_punct,
        )
    )
    return _unique_slot_values(slots)


def _citation_source_id_alignment_profile_slots(
    *,
    alignment: str,
    source_section_raw: str,
    citation_section_raw: str,
    source_has_trailing_punct: str,
    citation_has_trailing_punct: str,
    source_section_trailing_punct: str,
    citation_section_trailing_punct: str,
) -> List[Tuple[str, str]]:
    normalized_alignment = _clean_text(alignment).lower() or "unparsed"
    normalized_source_raw = _clean_text(source_section_raw)
    normalized_citation_raw = _clean_text(citation_section_raw)
    normalized_source_punct = _clean_text(source_section_trailing_punct)
    normalized_citation_punct = _clean_text(citation_section_trailing_punct)
    normalized_source_has_punct = _clean_text(source_has_trailing_punct).lower()
    normalized_citation_has_punct = _clean_text(citation_has_trailing_punct).lower()

    if normalized_source_raw and normalized_citation_raw:
        raw_relation = (
            "raw_exact"
            if normalized_source_raw.lower() == normalized_citation_raw.lower()
            else "raw_mismatch"
        )
    elif normalized_source_raw or normalized_citation_raw:
        raw_relation = "raw_partial"
    else:
        raw_relation = "raw_unknown"

    source_has_punct_known = normalized_source_has_punct in {"true", "false"}
    citation_has_punct_known = normalized_citation_has_punct in {"true", "false"}
    if source_has_punct_known and citation_has_punct_known:
        if (
            normalized_source_has_punct == "false"
            and normalized_citation_has_punct == "false"
        ):
            punctuation_relation = "punct_none"
        elif (
            normalized_source_has_punct == "true"
            and normalized_citation_has_punct == "true"
        ):
            punctuation_relation = (
                "punct_exact"
                if normalized_source_punct == normalized_citation_punct
                else "punct_variant"
            )
        else:
            punctuation_relation = "punct_presence_mismatch"
    elif normalized_source_punct or normalized_citation_punct:
        punctuation_relation = "punct_partial"
    else:
        punctuation_relation = "punct_unknown"

    profile = f"{normalized_alignment}_{raw_relation}_{punctuation_relation}"
    slots: List[Tuple[str, str]] = [
        ("citation_source_id_alignment_raw_relation", raw_relation),
        (
            "citation_source_id_alignment_punctuation_relation",
            punctuation_relation,
        ),
        ("citation_source_id_alignment_profile", profile),
    ]
    slots.extend(
        _typed_identifier_slots(
            profile,
            slot_prefix="citation_source_id_alignment_profile",
        )
    )
    return _unique_slot_values(slots)


def _slot_value_map(slots: Sequence[Tuple[str, str]]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for slot, value in slots:
        normalized_slot = _clean_text(slot)
        normalized_value = _clean_text(value)
        if (
            not normalized_slot
            or not normalized_value
            or normalized_slot in values
        ):
            continue
        values[normalized_slot] = normalized_value
    return values


def _frame_candidate_phrases(document: ModalIRDocument) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    ranked_candidates = sorted(
        document.frame_candidates,
        key=lambda candidate: _frame_candidate_sort_key(candidate),
    )
    for rank, candidate in enumerate(ranked_candidates, start=1):
        frame_id = _clean_text(getattr(candidate, "frame_id", "") or "")
        if not frame_id:
            continue
        phrases.append(
            DecodedModalPhrase(
                text=frame_id,
                slot="frame_candidate",
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=str(rank),
                slot="frame_candidate_rank",
                provenance_only=True,
            )
        )
        for slot, value in _numeric_signature_slots(
            str(rank),
            slot_prefix="frame_candidate_rank",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )
        phrases.append(
            DecodedModalPhrase(
                text=f"{rank}:{frame_id}",
                slot="frame_candidate_ranked",
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            f"{rank}:{frame_id}",
            slot_prefix="frame_candidate_ranked",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )
        for slot, value in _typed_identifier_slots(
            frame_id,
            slot_prefix="frame_candidate",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )
        for term in _informative_frame_candidate_terms(
            _phrase_values(getattr(candidate, "matched_terms", ()) or ())
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=term,
                    slot="frame_candidate_term",
                    provenance_only=True,
                )
            )
            for slot, value in _typed_identifier_slots(
                term,
                slot_prefix="frame_candidate_term",
            ):
                phrases.append(
                    DecodedModalPhrase(
                        text=value,
                        slot=slot,
                        provenance_only=True,
                    )
                )
    return phrases


def _informative_frame_candidate_terms(terms: Sequence[str]) -> List[str]:
    informative_terms: List[str] = []
    for raw_term in terms:
        cleaned_term = _clean_text(raw_term)
        if not cleaned_term:
            continue
        # Keep only terms that survive ontology normalization; this drops
        # low-information stopword fragments such as "and"/"the".
        if not normalize_frame_ontology_term(cleaned_term):
            continue
        if cleaned_term not in informative_terms:
            informative_terms.append(cleaned_term)
    return informative_terms


def _frame_ontology_phrases(document: ModalIRDocument) -> List[DecodedModalPhrase]:
    selected_frame = _selected_frame(document)
    frame_terms_by_frame = _frame_ontology_terms_by_frame(document)
    ranked_frame_ids = _ranked_candidate_frame_ids(
        document,
        frame_terms_by_frame=frame_terms_by_frame,
        selected_frame=selected_frame,
    )
    phrases: List[DecodedModalPhrase] = []
    selected_frame_terms: List[str] = []

    for rank, frame_id in enumerate(ranked_frame_ids, start=1):
        phrases.append(
            DecodedModalPhrase(
                text=frame_id,
                slot="candidate_ontology_frame",
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=str(rank),
                slot="candidate_ontology_frame_rank",
                provenance_only=True,
            )
        )
        for slot, value in _numeric_signature_slots(
            str(rank),
            slot_prefix="candidate_ontology_frame_rank",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )
        ranked_value = f"{rank}:{frame_id}"
        phrases.append(
            DecodedModalPhrase(
                text=ranked_value,
                slot="candidate_ontology_frame_ranked",
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            ranked_value,
            slot_prefix="candidate_ontology_frame_ranked",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )
        candidate_terms = frame_terms_by_frame.get(frame_id, [])
        for term in candidate_terms:
            phrases.append(
                DecodedModalPhrase(
                    text=term,
                    slot="candidate_ontology_term",
                    provenance_only=True,
                )
            )
        if selected_frame and frame_id == selected_frame:
            selected_frame_terms = list(candidate_terms)
            for term in selected_frame_terms:
                phrases.append(
                    DecodedModalPhrase(
                        text=term,
                        slot="selected_ontology_term",
                        provenance_only=True,
                    )
                )

    if selected_frame and not selected_frame_terms:
        selected_frame_terms = list(frame_terms_by_frame.get(selected_frame, ()))
        for term in selected_frame_terms:
            phrases.append(
                DecodedModalPhrase(
                    text=term,
                    slot="selected_ontology_term",
                    provenance_only=True,
                )
            )

    if selected_frame:
        for term in _selected_frame_source_grounding_terms(document):
            if term in selected_frame_terms:
                continue
            selected_frame_terms.append(term)
            phrases.append(
                DecodedModalPhrase(
                    text=term,
                    slot="selected_ontology_term",
                    provenance_only=True,
                )
            )
        phrases.append(
            DecodedModalPhrase(
                text=selected_frame,
                slot="selected_ontology_frame",
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=selected_frame,
                slot="interpreted_in_frame",
                provenance_only=True,
            )
        )
        for term in selected_frame_terms:
            phrases.append(
                DecodedModalPhrase(
                    text=term,
                    slot="interpreted_in_frame_term",
                    provenance_only=True,
                )
            )
        for slot, value in _frame_grounding_profile_slots(
            document,
            selected_frame=selected_frame,
            selected_frame_terms=selected_frame_terms,
            ranked_frame_ids=ranked_frame_ids,
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )

    return phrases


def _frame_grounding_profile_slots(
    document: ModalIRDocument,
    *,
    selected_frame: str,
    selected_frame_terms: Sequence[str],
    ranked_frame_ids: Sequence[str],
) -> List[Tuple[str, str]]:
    frame_key = _clean_text(selected_frame)
    if not frame_key:
        return []
    ranked_keys = [_clean_text(frame_id) for frame_id in ranked_frame_ids]
    ranked_keys = [frame_id for frame_id in ranked_keys if frame_id]
    selected_rank = "unranked"
    if frame_key in ranked_keys:
        selected_rank = str(ranked_keys.index(frame_key) + 1)
    candidate_count = str(len(ranked_keys))
    normalized_terms = _unique_preserve_order(selected_frame_terms)
    term_count = str(len(normalized_terms))
    profile = (
        f"{frame_key}|rank:{selected_rank}|terms:{term_count}|"
        f"candidates:{candidate_count}"
    )
    slots: List[Tuple[str, str]] = [
        ("frame_grounding_profile", profile),
        ("frame_grounding_selected_frame", frame_key),
        ("frame_grounding_selected_rank", selected_rank),
        ("frame_grounding_selected_term_count", term_count),
        ("frame_grounding_candidate_count", candidate_count),
    ]
    if selected_rank.isdigit():
        slots.extend(
            _numeric_signature_slots(
                selected_rank,
                slot_prefix="frame_grounding_selected_rank",
            )
        )
    slots.extend(
        _numeric_signature_slots(
            term_count,
            slot_prefix="frame_grounding_selected_term_count",
        )
    )
    slots.extend(
        _numeric_signature_slots(
            candidate_count,
            slot_prefix="frame_grounding_candidate_count",
        )
    )
    slots.extend(
        _typed_identifier_slots(
            profile,
            slot_prefix="frame_grounding_profile",
        )
    )
    for rank, term in enumerate(normalized_terms, start=1):
        slots.append(("frame_grounding_selected_term_ranked", f"{rank}:{term}"))
    for family, count in _resolved_modal_family_counts(
        document.metadata.get("modal_family_counts"),
        formulas=document.formulas,
    ):
        family_key = _slot_safe_family_key(family)
        if not family_key:
            continue
        family_profile = (
            f"{frame_key}|family:{family_key}|count:{count}|"
            f"rank:{selected_rank}|terms:{term_count}"
        )
        slots.extend(
            (
                ("frame_grounding_modal_family", family_key),
                ("frame_grounding_modal_family_count", f"{family_key}:{count}"),
                ("frame_grounding_family_profile", family_profile),
                (f"frame_grounding_family_profile_{family_key}", family_profile),
            )
        )
    return _unique_slot_values(slots)


def _selected_frame_source_grounding_terms(document: ModalIRDocument) -> List[str]:
    values: List[Any] = [
        document.metadata.get("citation"),
        document.metadata.get("source_id"),
        document.metadata.get("sample_id"),
        document.document_id,
    ]
    for source_id in _document_source_ids(document):
        values.append(source_id)
        source_map = _slot_value_map(_source_id_slots(source_id))
        values.extend(
            source_map.get(key)
            for key in (
                "source_id_citation_canonical",
                "source_id_title_section_key",
            )
        )
    for formula in document.formulas:
        values.extend(
            (
                getattr(formula.provenance, "citation", None),
                getattr(formula.provenance, "source_id", None),
                formula.metadata.get("status_keyword"),
                formula.metadata.get("procedural_keyword"),
                formula.metadata.get("statement_hint"),
            )
        )

    terms: List[str] = []
    for value in values:
        for term in _frame_ontology_metadata_terms(value):
            if _is_source_coordinate_frame_ontology_term(term):
                continue
            terms.append(term)
    return _unique_preserve_order(terms)


def _is_source_coordinate_frame_ontology_term(term: str) -> bool:
    normalized = _clean_text(term).lower()
    if not normalized:
        return False
    return re.fullmatch(r"\d+_\d+[a-z0-9_]*", normalized) is not None


def _frame_ontology_terms_by_frame(document: ModalIRDocument) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    metadata_terms = document.metadata.get("frame_ontology_terms")
    if isinstance(metadata_terms, Mapping):
        for frame_id, values in metadata_terms.items():
            frame_key = _clean_text(frame_id)
            if not frame_key:
                continue
            terms = _frame_ontology_metadata_terms(values)
            if terms:
                result[frame_key] = terms

    for frame in document.frame_candidates:
        frame_key = _clean_text(getattr(frame, "frame_id", "") or "")
        if not frame_key:
            continue
        if frame_key in result and result[frame_key]:
            continue
        matched_terms = list(getattr(frame, "matched_terms", ()) or ())
        candidate = FrameCandidate(
            frame_id=frame_key,
            label=frame_key.replace("_", " "),
            terms=tuple(matched_terms),
            domain="general",
        )
        terms = _unique_preserve_order(
            normalize_frame_ontology_term(term)
            for term in frame_ontology_terms(
                candidate,
                matched_terms=matched_terms,
            )
        )
        if terms:
            result[frame_key] = terms
    return result


def _frame_ontology_metadata_terms(value: Any) -> List[str]:
    terms: List[str] = []
    for raw_value in _frame_ontology_metadata_strings(value):
        cleaned = _clean_text(raw_value)
        if not cleaned:
            continue
        if _is_probable_frame_ontology_metadata_identifier(cleaned):
            continue
        source_id_match = _USCODE_SOURCE_ID_RE.match(cleaned)
        if source_id_match:
            source_terms = frame_ontology_terms_from_feature_keys(
                [f"slot:source_id:{cleaned}"],
            )
            if source_terms:
                terms.extend(source_terms)
                continue
        feature_terms = frame_ontology_terms_from_feature_keys([cleaned])
        if feature_terms:
            terms.extend(feature_terms)
            continue
        normalized = normalize_frame_ontology_term(
            cleaned,
            keep_numeric_tokens=True,
        )
        if normalized:
            terms.append(normalized)
    return _unique_preserve_order(terms)


def _frame_ontology_metadata_strings(value: Any) -> List[str]:
    extracted: List[str] = []
    _collect_frame_ontology_metadata_strings(
        value,
        extracted,
        depth=0,
    )
    return extracted


def _collect_frame_ontology_metadata_strings(
    value: Any,
    extracted: List[str],
    *,
    depth: int,
) -> None:
    if (
        value is None
        or depth >= _FRAME_ONTOLOGY_METADATA_MAX_DEPTH
        or len(extracted) >= _FRAME_ONTOLOGY_METADATA_MAX_VALUES
    ):
        return
    if isinstance(value, Mapping):
        for nested_value in value.values():
            _collect_frame_ontology_metadata_strings(
                nested_value,
                extracted,
                depth=depth + 1,
            )
            if len(extracted) >= _FRAME_ONTOLOGY_METADATA_MAX_VALUES:
                return
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested_value in value:
            _collect_frame_ontology_metadata_strings(
                nested_value,
                extracted,
                depth=depth + 1,
            )
            if len(extracted) >= _FRAME_ONTOLOGY_METADATA_MAX_VALUES:
                return
        return
    if isinstance(value, str):
        cleaned = _clean_text(value)
        if cleaned:
            extracted.append(cleaned)


def _is_probable_frame_ontology_metadata_identifier(value: str) -> bool:
    cleaned = _clean_text(value)
    if not cleaned or " " in cleaned:
        return False
    lowered = cleaned.lower()
    if lowered.startswith("modal-synthesis-"):
        return True
    if lowered.startswith("program-"):
        return True
    if _USCODE_SOURCE_ID_RE.match(cleaned):
        return False
    if _FRAME_ONTOLOGY_METADATA_OPAQUE_ID_HEX_RE.search(cleaned) is None:
        return False
    return "-" in cleaned or "_" in cleaned


def _ranked_candidate_frame_ids(
    document: ModalIRDocument,
    *,
    frame_terms_by_frame: Mapping[str, Sequence[str]],
    selected_frame: str,
) -> List[str]:
    ranked_frame_ids: List[str] = []
    seen: set[str] = set()

    for frame in sorted(
        document.frame_candidates,
        key=lambda candidate: _frame_candidate_sort_key(candidate),
    ):
        frame_id = _clean_text(getattr(frame, "frame_id", "") or "")
        if not frame_id or frame_id in seen:
            continue
        seen.add(frame_id)
        ranked_frame_ids.append(frame_id)
    for frame_id in sorted(frame_terms_by_frame):
        cleaned = _clean_text(frame_id)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ranked_frame_ids.append(cleaned)
    normalized_selected = _clean_text(selected_frame)
    if normalized_selected and normalized_selected not in seen:
        ranked_frame_ids.append(normalized_selected)
    return ranked_frame_ids


def _frame_candidate_sort_key(candidate: Any) -> Tuple[float, str]:
    frame_id = _clean_text(getattr(candidate, "frame_id", "") or "")
    try:
        score = float(getattr(candidate, "score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return (-score, frame_id)


def _unique_preserve_order(values: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _operator_phrase(formula: ModalIRFormula) -> str:
    symbol = formula.operator.symbol
    label = formula.operator.label or symbol
    phrase_map = {
        "O": "obligatory",
        "P": "permitted",
        "F": "forbidden",
        "G": "always",
        "X": "next",
        "K": "known",
        "B": "believed",
        "O|": "conditionally obligatory",
        "[a]": "after action",
        "Frame": "framed as",
        "□": "necessary",
        "◇": "possible",
    }
    return phrase_map.get(symbol, label)


def _resolved_modal_operator_label(formula: ModalIRFormula) -> str:
    label = _clean_text(formula.operator.label)
    if label:
        return label
    fallback = _clean_text(_operator_phrase(formula))
    if not fallback or fallback == _clean_text(formula.operator.symbol):
        return ""
    return fallback


def _canonical_modal_operator_label(
    formula: ModalIRFormula,
    *,
    operator_label: str,
) -> str:
    family = _clean_text(formula.operator.family).lower()
    symbol = _clean_text(formula.operator.symbol)
    direct = _CANONICAL_MODAL_OPERATOR_LABELS.get((family, symbol), "")
    if direct:
        return direct
    normalized_label = _clean_text(operator_label).lower()
    if not normalized_label:
        return ""
    return _CANONICAL_MODAL_OPERATOR_LABEL_ALIASES.get(normalized_label, "")


def _modal_operator_signature(
    formula: ModalIRFormula,
    *,
    operator_label: str,
) -> str:
    family = _clean_text(formula.operator.family)
    symbol = _clean_text(formula.operator.symbol)
    label = _clean_text(operator_label)
    if not family or not symbol:
        return ""
    if not label:
        return f"{family}:{symbol}"
    return f"{family}:{symbol}:{label}"


def _predicate_phrase(formula: ModalIRFormula) -> str:
    return _clean_text(formula.predicate.name.replace("_", " "))


def _sentence_from_phrases(phrases: Sequence[DecodedModalPhrase]) -> str:
    words: List[str] = []
    for phrase in phrases:
        if phrase.fixed or phrase.provenance_only:
            continue
        text = _clean_text(phrase.text)
        if not text:
            continue
        words.append(text)
    return _clean_text(" ".join(words))


def _source_reconstruction_phrases(
    document: ModalIRDocument,
) -> Tuple[List[DecodedModalPhrase], float]:
    source_text = str(document.normalized_text or "")
    if not _clean_text(source_text):
        return [], 0.0

    modal_spans = _merged_formula_spans(document.formulas, len(source_text))
    if not modal_spans:
        return [
            DecodedModalPhrase(
                text=source_text,
                slot="source_context_span",
                spans=[[0, len(source_text)]],
            )
        ], 0.0

    phrases: List[DecodedModalPhrase] = []
    cursor = 0
    covered_chars = 0
    for start, end in modal_spans:
        if cursor < start:
            _append_source_phrase(
                phrases,
                source_text,
                cursor,
                start,
                slot="source_context_span",
            )
        _append_source_phrase(
            phrases,
            source_text,
            start,
            end,
            slot="modal_source_span",
        )
        covered_chars += max(0, end - start)
        cursor = max(cursor, end)
    if cursor < len(source_text):
        _append_source_phrase(
            phrases,
            source_text,
            cursor,
            len(source_text),
            slot="source_context_span",
        )

    coverage = covered_chars / len(source_text) if source_text else 0.0
    return phrases, round(min(1.0, max(0.0, coverage)), 6)


def _source_span_slot_phrases(
    source_phrases: Sequence[DecodedModalPhrase],
    *,
    formulas: Sequence[ModalIRFormula] = (),
) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    seen: set[Tuple[str, str, Tuple[Tuple[int, int], ...]]] = set()
    for source_phrase in source_phrases:
        slot_prefix = _clean_text(source_phrase.slot)
        text = _clean_text(source_phrase.text)
        if slot_prefix not in {"modal_source_span", "source_context_span"} or not text:
            continue
        spans = source_phrase.spans
        span_marker = tuple(
            (int(start), int(end))
            for start, end in (
                (span[0], span[1])
                for span in spans
                if isinstance(span, Sequence) and len(span) == 2
            )
            if isinstance(start, int) and isinstance(end, int)
        )
        for slot, value in _typed_identifier_slots(
            text,
            slot_prefix=slot_prefix,
        ):
            marker = (slot, value, span_marker)
            if marker in seen:
                continue
            seen.add(marker)
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        for semantic_phrase in _legal_semantic_atom_phrases(
            text=text,
            slot_prefix=slot_prefix,
            spans=spans,
        ):
            marker = (semantic_phrase.slot, semantic_phrase.text, span_marker)
            if marker in seen:
                continue
            seen.add(marker)
            phrases.append(semantic_phrase)
        for status_slot, status_value in _uscode_editorial_status_detail_slots(
            text,
            slot_prefix=slot_prefix,
        ):
            marker = (status_slot, status_value, span_marker)
            if marker in seen:
                continue
            seen.add(marker)
            phrases.append(
                DecodedModalPhrase(
                    text=status_value,
                    slot=status_slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        for cue in _bridge_cues_from_text(text):
            cue_marker = (f"{slot_prefix}_bridge_cue", cue, span_marker)
            if cue_marker not in seen:
                seen.add(cue_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=cue,
                        slot=f"{slot_prefix}_bridge_cue",
                        spans=spans,
                        provenance_only=True,
                    )
                )
            modal_cue_marker = (f"{slot_prefix}_modal_bridge_cue", cue, span_marker)
            if modal_cue_marker not in seen:
                seen.add(modal_cue_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=cue,
                        slot=f"{slot_prefix}_modal_bridge_cue",
                        spans=spans,
                        provenance_only=True,
                    )
                )
            for bridge_family, bridge_symbol in _cue_bridge_operator_pairs(cue):
                bridge_signature = f"{bridge_family}:{bridge_symbol}:{cue}"
                bridge_value = f"{bridge_symbol}:{cue}"
                for bridge_slot, bridge_value_text in (
                    (f"{slot_prefix}_bridge_modal_family", bridge_family),
                    (f"{slot_prefix}_bridge_modal_operator", bridge_symbol),
                    (f"{slot_prefix}_bridge_modal_signature", bridge_signature),
                    (
                        f"{slot_prefix}_bridge_modal_{bridge_family}",
                        bridge_value,
                    ),
                ):
                    bridge_marker = (bridge_slot, bridge_value_text, span_marker)
                    if bridge_marker in seen:
                        continue
                    seen.add(bridge_marker)
                    phrases.append(
                        DecodedModalPhrase(
                            text=bridge_value_text,
                            slot=bridge_slot,
                            spans=spans,
                            provenance_only=True,
                        )
                    )
            for (
                formula_family,
                formula_symbol,
                formula_signature,
            ) in _span_formula_modal_signatures(
                formulas,
                spans=spans,
            ):
                formula_signature_marker = (
                    f"{slot_prefix}_bridge_modal_formula_signature",
                    formula_signature,
                    span_marker,
                )
                if formula_signature_marker not in seen:
                    seen.add(formula_signature_marker)
                    phrases.append(
                        DecodedModalPhrase(
                            text=formula_signature,
                            slot=f"{slot_prefix}_bridge_modal_formula_signature",
                            spans=spans,
                            provenance_only=True,
                        )
                    )
                for bridge_family, bridge_symbol in _augment_deontic_bridge_pairs(
                    bridge_pairs=_cue_bridge_operator_pairs(cue),
                    formula_family=formula_family,
                    formula_symbol=formula_symbol,
                    cue=cue,
                ):
                    family_pair = f"{formula_family}->{bridge_family}"
                    operator_pair = f"{formula_symbol}->{bridge_symbol}"
                    transition_signature = (
                        f"{formula_family}:{formula_symbol}->"
                        f"{bridge_family}:{bridge_symbol}:{cue}"
                    )
                    pair_cue = f"{family_pair}:{cue}"
                    for transition_slot, transition_value in (
                        (
                            f"{slot_prefix}_bridge_modal_family_pair",
                            family_pair,
                        ),
                        (
                            f"{slot_prefix}_bridge_modal_operator_pair",
                            operator_pair,
                        ),
                        (
                            f"{slot_prefix}_bridge_modal_pair_cue",
                            pair_cue,
                        ),
                        (
                            f"{slot_prefix}_bridge_modal_transition_signature",
                            transition_signature,
                        ),
                    ):
                        transition_marker = (
                            transition_slot,
                            transition_value,
                            span_marker,
                        )
                        if transition_marker in seen:
                            continue
                        seen.add(transition_marker)
                        phrases.append(
                            DecodedModalPhrase(
                                text=transition_value,
                                slot=transition_slot,
                                spans=spans,
                                provenance_only=True,
                            )
                        )
        for formula in formulas:
            for refined_slot, refined_value in _refined_contextual_modal_transition_slots(
                formula,
                text=text,
                slot_prefix=slot_prefix,
            ):
                refined_marker = (refined_slot, refined_value, span_marker)
                if refined_marker in seen:
                    continue
                seen.add(refined_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=refined_value,
                        slot=refined_slot,
                        spans=spans,
                        provenance_only=True,
                    )
                )
    return phrases


def _span_formula_modal_signatures(
    formulas: Sequence[ModalIRFormula],
    *,
    spans: Sequence[Sequence[int]],
) -> List[Tuple[str, str, str]]:
    signatures: List[Tuple[str, str, str]] = []
    if not formulas or not spans:
        return signatures
    normalized_spans: List[Tuple[int, int]] = []
    for span in spans:
        if not isinstance(span, Sequence) or len(span) != 2:
            continue
        try:
            start = int(span[0])
            end = int(span[1])
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        normalized_spans.append((start, end))
    if not normalized_spans:
        return signatures
    for formula in formulas:
        family = _clean_text(formula.operator.family).lower()
        symbol = _clean_text(formula.operator.symbol)
        if not family or not symbol:
            continue
        try:
            formula_start = int(formula.provenance.start_char)
            formula_end = int(formula.provenance.end_char)
        except (TypeError, ValueError):
            continue
        if formula_end <= formula_start:
            continue
        overlaps = any(
            formula_start < span_end and formula_end > span_start
            for span_start, span_end in normalized_spans
        )
        if not overlaps:
            continue
        signature = (family, symbol, f"{family}:{symbol}")
        if signature not in signatures:
            signatures.append(signature)
    return signatures


def _document_span_metric_phrases(
    *,
    document: ModalIRDocument,
    modal_span_coverage: float,
) -> List[DecodedModalPhrase]:
    source_text = str(document.normalized_text or "")
    source_length = len(source_text) if _clean_text(source_text) else 0
    modal_spans = _merged_formula_spans(document.formulas, source_length)
    modal_span_count = len(modal_spans)
    modal_span_char_count = sum(
        max(0, span_end - span_start)
        for span_start, span_end in modal_spans
    )
    source_context_span_count = _source_context_span_count(
        modal_spans=modal_spans,
        source_length=source_length,
    )
    source_context_span_char_count = max(0, source_length - modal_span_char_count)
    support_start, support_end = _support_span(document.formulas)
    support_width = max(0, support_end - support_start)
    coverage_percent = str(int(round(max(0.0, min(1.0, modal_span_coverage)) * 100.0)))

    metric_slots: List[Tuple[str, str]] = [
        ("modal_formula_count", str(len(document.formulas))),
        ("source_text_char_count", str(source_length)),
        ("modal_span_count", str(modal_span_count)),
        ("modal_span_char_count", str(modal_span_char_count)),
        ("source_context_span_count", str(source_context_span_count)),
        ("source_context_span_char_count", str(source_context_span_char_count)),
        ("support_span_start_char", str(support_start)),
        ("support_span_end_char", str(support_end)),
        ("support_span_width", str(support_width)),
        ("modal_span_coverage_percent", coverage_percent),
    ]
    phrases: List[DecodedModalPhrase] = []
    for slot, value in metric_slots:
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
        for signature_slot, signature_value in _numeric_signature_slots(
            value,
            slot_prefix=slot,
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=signature_value,
                    slot=signature_slot,
                    provenance_only=True,
                )
            )

    coverage_bucket = _modal_span_coverage_bucket(
        modal_span_coverage=modal_span_coverage,
        source_length=source_length,
        modal_span_count=modal_span_count,
    )
    phrases.append(
        DecodedModalPhrase(
            text=coverage_bucket,
            slot="modal_span_coverage_bucket",
            provenance_only=True,
        )
    )
    for slot, value in _typed_identifier_slots(
        coverage_bucket,
        slot_prefix="modal_span_coverage_bucket",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
    return phrases


def _source_context_span_count(
    *,
    modal_spans: Sequence[Tuple[int, int]],
    source_length: int,
) -> int:
    if source_length <= 0:
        return 0
    if not modal_spans:
        return 1
    count = 0
    cursor = 0
    for start, end in modal_spans:
        if cursor < start:
            count += 1
        cursor = max(cursor, end)
    if cursor < source_length:
        count += 1
    return count


def _modal_span_coverage_bucket(
    *,
    modal_span_coverage: float,
    source_length: int,
    modal_span_count: int,
) -> str:
    if source_length <= 0:
        return "no_source_text"
    if modal_span_count <= 0:
        return "no_modal_span"
    normalized_coverage = max(0.0, min(1.0, float(modal_span_coverage)))
    if normalized_coverage < 0.25:
        return "sparse_coverage"
    if normalized_coverage < 0.5:
        return "partial_coverage"
    if normalized_coverage < 0.75:
        return "majority_coverage"
    if normalized_coverage < 1.0:
        return "high_coverage"
    return "full_coverage"


def _append_source_phrase(
    phrases: List[DecodedModalPhrase],
    source_text: str,
    start: int,
    end: int,
    *,
    slot: str,
) -> None:
    clamped_start = max(0, min(len(source_text), start))
    clamped_end = max(clamped_start, min(len(source_text), end))
    text = _clean_text(source_text[clamped_start:clamped_end])
    if not text:
        return
    phrases.append(
        DecodedModalPhrase(
            text=text,
            slot=slot,
            spans=[[clamped_start, clamped_end]],
        )
    )


def _merged_formula_spans(
    formulas: Sequence[ModalIRFormula],
    source_length: int,
) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    for formula in formulas:
        start = max(0, min(source_length, int(formula.provenance.start_char)))
        end = max(start, min(source_length, int(formula.provenance.end_char)))
        if end > start:
            spans.append((start, end))
    if not spans:
        return []

    spans.sort()
    merged: List[Tuple[int, int]] = []
    current_start, current_end = spans[0]
    for start, end in spans[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        merged.append((current_start, current_end))
        current_start, current_end = start, end
    merged.append((current_start, current_end))
    return merged


def _support_span(formulas: Sequence[ModalIRFormula]) -> List[int]:
    if not formulas:
        return [0, 0]
    starts: List[int] = []
    ends: List[int] = []
    for formula in formulas:
        try:
            start = int(formula.provenance.start_char)
            end = int(formula.provenance.end_char)
        except (TypeError, ValueError):
            continue
        starts.append(start)
        ends.append(max(start, end))
    if not starts or not ends:
        return [0, 0]
    return [min(starts), max(ends)]


def _fixed_phrase(text: str, slot: str) -> DecodedModalPhrase:
    return DecodedModalPhrase(text=text, slot=slot, fixed=True)


def _span_from_values(start: Any, end: Any) -> List[List[int]]:
    try:
        start_int = int(start)
        end_int = int(end)
    except (TypeError, ValueError):
        return []
    if start_int < 0 or end_int < start_int:
        return []
    return [[start_int, end_int]]


def _clean_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _typed_argument_slot(argument: str) -> Tuple[str, str] | None:
    if ":" not in argument:
        return None
    key, value = argument.split(":", 1)
    key = _clean_text(key).lower()
    value = _clean_text(value).replace("_", " ")
    if not key or not value:
        return None
    key = re.sub(r"[^a-z0-9_]+", "_", key).strip("_")
    if not key:
        return None
    return f"argument_{key}", value


def _typed_clause_phrases(
    clause: str,
    *,
    slot: str,
    spans: List[List[int]],
    formula: ModalIRFormula,
) -> List[DecodedModalPhrase]:
    parsed = _typed_clause_slot(clause, slot=slot)
    if parsed is None:
        return []
    prefix_slot_value, prefix_key, scoped_value = parsed
    scoped_slot = f"{slot}_{prefix_key}"
    phrases = [
        DecodedModalPhrase(
            text=prefix_slot_value,
            slot=f"{slot}_prefix",
            spans=spans,
            provenance_only=True,
        ),
        DecodedModalPhrase(
            text=prefix_key,
            slot=f"{slot}_prefix_key",
            spans=spans,
            provenance_only=True,
        ),
    ]
    temporal_relation = _temporal_clause_prefix_relation(prefix_key)
    if temporal_relation:
        phrases.append(
            DecodedModalPhrase(
                text="temporal",
                slot=f"{slot}_prefix_family",
                spans=spans,
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=temporal_relation,
                slot=f"{slot}_prefix_temporal_relation",
                spans=spans,
                provenance_only=True,
            )
        )
    for modal_slot, modal_value in _modal_lexeme_slots(
        formula,
        cue=prefix_key,
        slot_prefix=f"{slot}_modal",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=modal_value,
                slot=modal_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    phrases.extend(
        _contextual_modal_cue_phrases(
            formula=formula,
            text=prefix_slot_value,
            slot_prefix=f"{slot}_scope",
            spans=spans,
        )
    )
    if scoped_value:
        phrases.append(
            DecodedModalPhrase(
                text=scoped_value,
                slot=scoped_slot,
                spans=spans,
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=scoped_value,
                slot=f"{slot}_scope",
                spans=spans,
                provenance_only=True,
            )
        )
        for typed_slot, typed_value in _typed_identifier_slots(
            scoped_value,
            slot_prefix=f"{slot}_scope",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=typed_value,
                    slot=typed_slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        phrases.extend(
            _contextual_modal_cue_phrases(
                formula=formula,
                text=scoped_value,
                slot_prefix=f"{slot}_scope",
                spans=spans,
            )
        )
        phrases.extend(
            _content_scope_phrases(
                scoped_value,
                slot_prefix=f"{slot}_scope",
                spans=spans,
            )
        )
        phrases.extend(
            _typed_decompiler_role_phrases(
                formula=formula,
                text=scoped_value,
                slot_prefix=f"{slot}_scope",
                spans=spans,
            )
        )
    return phrases


def _typed_clause_slot(
    clause: str,
    *,
    slot: str,
) -> Tuple[str, str, str] | None:
    normalized = _clean_text(clause).lower()
    if not normalized:
        return None
    prefixes = _CONDITION_PREFIXES if slot == "condition" else _EXCEPTION_PREFIXES
    for prefix_text, prefix_key in sorted(
        prefixes,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if not _text_has_prefix(normalized, prefix_text):
            continue
        suffix = _clean_text(normalized[len(prefix_text) :].lstrip(",:;- "))
        return prefix_text, prefix_key, suffix
    return None


def _condition_proxy_phrases_from_exception(
    *,
    exception: str,
    spans: List[List[int]],
    formula: ModalIRFormula,
) -> List[DecodedModalPhrase]:
    scoped_exception = _clean_text(exception)
    if not scoped_exception:
        return []
    phrases: List[DecodedModalPhrase] = [
        DecodedModalPhrase(
            text=scoped_exception,
            slot="condition",
            spans=spans,
            provenance_only=True,
        )
    ]
    for typed_slot, typed_value in _typed_identifier_slots(
        scoped_exception,
        slot_prefix="condition",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=typed_value,
                slot=typed_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    typed_exception = _typed_clause_slot(scoped_exception, slot="exception")
    if typed_exception is None:
        return phrases
    prefix_slot_value, prefix_key, scoped_value = typed_exception
    phrases.extend(
        (
            DecodedModalPhrase(
                text=prefix_slot_value,
                slot="condition_prefix",
                spans=spans,
                provenance_only=True,
            ),
            DecodedModalPhrase(
                text=prefix_key,
                slot="condition_prefix_key",
                spans=spans,
                provenance_only=True,
            ),
        )
    )
    temporal_relation = _temporal_clause_prefix_relation(prefix_key)
    if temporal_relation:
        phrases.extend(
            (
                DecodedModalPhrase(
                    text="temporal",
                    slot="condition_prefix_family",
                    spans=spans,
                    provenance_only=True,
                ),
                DecodedModalPhrase(
                    text=temporal_relation,
                    slot="condition_prefix_temporal_relation",
                    spans=spans,
                    provenance_only=True,
                ),
            )
        )
    for modal_slot, modal_value in _modal_lexeme_slots(
        formula,
        cue=prefix_key,
        slot_prefix="condition_modal",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=modal_value,
                slot=modal_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    if not scoped_value:
        return phrases
    phrases.extend(
        (
            DecodedModalPhrase(
                text=scoped_value,
                slot=f"condition_{prefix_key}",
                spans=spans,
                provenance_only=True,
            ),
            DecodedModalPhrase(
                text=scoped_value,
                slot="condition_scope",
                spans=spans,
                provenance_only=True,
            ),
        )
    )
    for typed_slot, typed_value in _typed_identifier_slots(
        scoped_value,
        slot_prefix="condition_scope",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=typed_value,
                slot=typed_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    phrases.extend(
        _contextual_modal_cue_phrases(
            formula=formula,
            text=scoped_value,
            slot_prefix="condition_scope",
            spans=spans,
        )
    )
    phrases.extend(
        _content_scope_phrases(
            scoped_value,
            slot_prefix="condition_scope",
            spans=spans,
        )
    )
    phrases.extend(
        _typed_decompiler_role_phrases(
            formula=formula,
            text=scoped_value,
            slot_prefix="condition_scope",
            spans=spans,
        )
    )
    return phrases


def _content_scope_phrases(
    text: str,
    *,
    slot_prefix: str,
    spans: List[List[int]],
) -> List[DecodedModalPhrase]:
    content_value = _content_scope_value(text)
    if not content_value:
        return []
    phrases: List[DecodedModalPhrase] = [
        DecodedModalPhrase(
            text=content_value,
            slot=f"{slot_prefix}_content",
            spans=spans,
            provenance_only=True,
        )
    ]
    for slot, value in _typed_identifier_slots(
        content_value,
        slot_prefix=f"{slot_prefix}_content",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    return phrases


def _content_scope_value(text: str) -> str:
    normalized = _clean_text(text)
    if not normalized:
        return ""
    tokens = normalized.split()
    while tokens and tokens[0].lower() in _LOW_INFORMATION_SCOPE_LEADING_TOKENS:
        tokens = tokens[1:]
    if not tokens:
        return ""
    content = _clean_text(" ".join(tokens))
    if not content or content.lower() == normalized.lower():
        return ""
    return content


def _typed_decompiler_role_phrases(
    *,
    formula: ModalIRFormula,
    text: str,
    slot_prefix: str,
    spans: List[List[int]],
) -> List[DecodedModalPhrase]:
    return [
        DecodedModalPhrase(
            text=value,
            slot=slot,
            spans=spans,
            provenance_only=True,
        )
        for slot, value in _typed_decompiler_role_slots(
            formula=formula,
            text=text,
            slot_prefix=slot_prefix,
        )
    ]


def _source_role_anchor_phrases(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    spans: List[List[int]],
) -> List[DecodedModalPhrase]:
    return [
        DecodedModalPhrase(
            text=value,
            slot=slot,
            spans=spans,
            provenance_only=True,
        )
        for slot, value in _source_role_anchor_slots(
            document=document,
            formula=formula,
        )
    ]


def _source_role_anchor_slots(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[Tuple[str, str]]:
    source_span_text = _formula_source_span_text(document=document, formula=formula)
    anchors = _source_role_anchor_values(
        formula=formula,
        source_span_text=source_span_text,
    )
    if not anchors:
        return []
    family = _clean_text(formula.operator.family).lower()
    source_family_pairs = _source_anchor_family_pairs(
        document=document,
        formula=formula,
        source_span_text=source_span_text,
        anchors=anchors,
    )
    predicate_role = _clean_text(formula.predicate.role).lower()
    predicate_head = _slot_safe_family_pair_key(formula.predicate.name)
    slots: List[Tuple[str, str]] = []

    structural_roles = [
        role
        for role in ("subject", "action", "object")
        if _clean_text(anchors.get(role, ""))
    ]
    role_set = "+".join(structural_roles)
    role_path = "->".join(structural_roles)
    if role_set:
        slots.append(("source_role_set", role_set))
        slots.append(("source_surface_role_set", role_set))
        if family:
            slots.append(("source_role_set_family", f"{role_set}:{family}"))
            slots.append(("source_surface_role_set_to_family", f"{role_set}:{family}"))
    if role_path:
        slots.append(("source_role_path", role_path))
        slots.append(("source_role_path_scope", f"{role_path}:unscoped"))
        if family:
            slots.append(("source_role_path_family", f"{role_path}:{family}"))

    for role in ("subject", "action", "object"):
        anchor = _clean_text(anchors.get(role, "")) or "none"
        variable_name = f"v_{role}"
        slots.append(("source_logical_variable_map", f"{role}:{anchor}:{variable_name}"))
        slots.append(
            (
                f"source_{role}_logical_variable_map",
                f"{role}:{anchor}:{variable_name}",
            )
        )

    for role in ("subject", "action", "object", "condition", "exception", "temporal"):
        anchor = _clean_text(anchors.get(role, "")).lower()
        if not anchor:
            continue
        slot_prefix = f"source_{role}_anchor"
        slots.append((slot_prefix, anchor))
        slots.extend(_typed_identifier_slots(anchor, slot_prefix=slot_prefix))
        if family:
            slots.append((f"source_{role}_family", f"{anchor}:{family}"))
            for family_pair in source_family_pairs:
                slots.append((f"source_{role}_family_pair", family_pair))
                slots.append((f"source_{role}_family_pair_anchor", f"{anchor}:{family_pair}"))
        if predicate_role and role in {"subject", "action", "object"}:
            slots.append((f"source_{role}_role", f"{anchor}:{predicate_role}"))
        if predicate_head and role in {"action", "object"}:
            slots.append((f"source_{role}_predicate", f"{anchor}:{predicate_head}"))
    return _unique_slot_values(slots)


def _source_role_anchor_values(
    *,
    formula: ModalIRFormula,
    source_span_text: str,
) -> Dict[str, str]:
    normalized = _clean_text(source_span_text).replace("_", " ").lower()
    raw_tokens = _CUE_TOKEN_RE.findall(normalized)
    if not raw_tokens:
        return {}

    cue_sequences = _source_anchor_cue_sequences(formula)
    cue_tokens = {token for sequence in cue_sequences for token in sequence}
    cue_window = _source_anchor_cue_window(raw_tokens, cue_sequences)
    if cue_window is None:
        cue_start = next(
            (
                index
                for index, token in enumerate(raw_tokens)
                if token in cue_tokens or token in _SOURCE_ANCHOR_MODAL_CUE_TOKENS
            ),
            -1,
        )
        cue_end = cue_start + 1 if cue_start >= 0 else -1
    else:
        cue_start, cue_end = cue_window

    if cue_start >= 0 and cue_end > cue_start:
        subject_candidates = _source_anchor_role_tokens(raw_tokens[:cue_start])
        predicate_candidates = _source_anchor_role_tokens(raw_tokens[cue_end:])
    else:
        subject_candidates = _source_anchor_role_tokens(raw_tokens[:2])
        predicate_candidates = _source_anchor_role_tokens(raw_tokens[1:])

    if cue_start == 0 and cue_end > 0:
        scoped_cue_index = next(
            (
                index
                for index, token in enumerate(raw_tokens[cue_end:], start=cue_end)
                if token in _SOURCE_ANCHOR_MODAL_CUE_TOKENS
            ),
            -1,
        )
        if scoped_cue_index >= cue_end:
            scoped_subject_candidates = _source_anchor_role_tokens(
                raw_tokens[cue_end:scoped_cue_index]
            )
            scoped_predicate_candidates = _source_anchor_role_tokens(
                raw_tokens[scoped_cue_index + 1 :]
            )
            if scoped_predicate_candidates:
                if scoped_subject_candidates:
                    subject_candidates = scoped_subject_candidates
                predicate_candidates = scoped_predicate_candidates

    predicate_tokens = _source_anchor_role_tokens(
        _CUE_TOKEN_RE.findall(_clean_text(formula.predicate.name).replace("_", " ").lower())
    )
    if not subject_candidates and predicate_tokens:
        subject_candidates = predicate_tokens[:1]
    if not predicate_candidates:
        predicate_candidates = list(predicate_tokens)

    subject_anchor = _preferred_source_anchor_candidate(subject_candidates, default_index=-1)
    action_anchor = _preferred_source_anchor_candidate(predicate_candidates, default_index=0)
    object_anchor = _preferred_source_anchor_candidate(predicate_candidates, default_index=1)
    predicate_default_anchor = _preferred_source_anchor_candidate(predicate_tokens)
    if not action_anchor:
        action_anchor = predicate_default_anchor
    if (
        not object_anchor
        or object_anchor == action_anchor
        or _is_temporal_source_anchor_token(object_anchor)
    ):
        object_anchor = _preferred_source_anchor_candidate(
            [token for token in predicate_tokens if token != action_anchor],
            default_index=0,
        )

    condition_values = _phrase_values(formula.conditions)
    exception_values = _phrase_values(formula.exceptions)
    temporal_anchor = _source_anchor_from_clauses(
        clauses=condition_values,
        temporal_only=True,
    ) or _source_anchor_from_clauses(
        clauses=exception_values,
        temporal_only=True,
    )
    anchors = {
        "subject": subject_anchor,
        "action": action_anchor,
        "object": object_anchor,
        "condition": _source_anchor_from_clauses(clauses=condition_values),
        "exception": _source_anchor_from_clauses(clauses=exception_values),
        "temporal": temporal_anchor
        or _source_anchor_first_after(
            tokens=raw_tokens,
            markers=_SOURCE_ANCHOR_TEMPORAL_MARKERS,
        ),
    }
    return {role: value for role, value in anchors.items() if value}


def _source_anchor_cue_sequences(formula: ModalIRFormula) -> List[List[str]]:
    raw_cues = [
        formula.metadata.get("cue"),
        formula.metadata.get("modal_cue"),
        formula.operator.label,
        formula.operator.symbol,
    ]
    sequences: List[List[str]] = []
    for cue in raw_cues:
        cue_tokens = _CUE_TOKEN_RE.findall(_clean_text(cue).replace("_", " ").lower())
        if cue_tokens and cue_tokens not in sequences:
            sequences.append(cue_tokens)
    for cue in _SOURCE_ANCHOR_MODAL_CUE_TOKENS:
        if [cue] not in sequences:
            sequences.append([cue])
    return sequences


def _source_anchor_cue_window(
    tokens: Sequence[str],
    cue_sequences: Sequence[Sequence[str]],
) -> Tuple[int, int] | None:
    best_window: Tuple[int, int] | None = None
    for cue_sequence in sorted(cue_sequences, key=len, reverse=True):
        width = len(cue_sequence)
        if width <= 0 or width > len(tokens):
            continue
        for start in range(0, len(tokens) - width + 1):
            if list(tokens[start : start + width]) != list(cue_sequence):
                continue
            candidate = (start, start + width)
            if best_window is None:
                best_window = candidate
            else:
                current_width = best_window[1] - best_window[0]
                if width > current_width or (
                    width == current_width and start < best_window[0]
                ):
                    best_window = candidate
            break
    return best_window


def _source_anchor_role_tokens(tokens: Sequence[str]) -> List[str]:
    return [
        token
        for token in tokens
        if len(token) > 2
        and token not in _SOURCE_ANCHOR_NOISE_TOKENS
        and token not in _SOURCE_ANCHOR_CONNECTIVE_TOKENS
        and token not in _SOURCE_ANCHOR_QUANTIFIER_TOKENS
        and token not in _LOW_INFORMATION_SCOPE_LEADING_TOKENS
        and token not in _SOURCE_ANCHOR_MODAL_CUE_TOKENS
        and token not in _SOURCE_ANCHOR_CONDITION_MARKERS
        and token not in _SOURCE_ANCHOR_EXCEPTION_MARKERS
        and token not in _SOURCE_ANCHOR_TEMPORAL_MARKERS
        and token not in _SOURCE_ANCHOR_NEGATION_MARKERS
        and not _is_low_information_section_marker(token)
    ]


def _preferred_source_anchor_candidate(
    candidates: Sequence[str],
    *,
    default_index: int = 0,
    prefer_temporal: bool = False,
) -> str:
    normalized_candidates = [
        _clean_text(candidate).lower()
        for candidate in candidates
        if _clean_text(candidate)
    ]
    if not normalized_candidates:
        return ""
    if default_index < 0:
        normalized_index = len(normalized_candidates) + default_index
    else:
        normalized_index = default_index
    normalized_index = min(max(normalized_index, 0), len(normalized_candidates) - 1)
    search_order = [
        normalized_index,
        *range(normalized_index + 1, len(normalized_candidates)),
        *range(normalized_index - 1, -1, -1),
    ]
    default_candidate = normalized_candidates[search_order[0]]
    for index in search_order:
        candidate = normalized_candidates[index]
        is_temporal = _is_temporal_source_anchor_token(candidate)
        if prefer_temporal and is_temporal:
            return candidate
        if not prefer_temporal and not is_temporal:
            return candidate
    return default_candidate


def _is_temporal_source_anchor_token(token: str) -> bool:
    normalized_token = _clean_text(token).lower()
    if not normalized_token:
        return False
    if _TEMPORAL_BRIDGE_YEAR_RE.fullmatch(normalized_token):
        return True
    return normalized_token in _SOURCE_ANCHOR_TEMPORAL_CONTEXT_TOKENS


def _source_anchor_first_after(
    *,
    tokens: Sequence[str],
    markers: frozenset[str],
) -> str:
    for index, token in enumerate(tokens):
        if token not in markers:
            continue
        candidates = _source_anchor_role_tokens(tokens[index + 1 : index + 6])
        if candidates:
            return candidates[0]
    return ""


def _source_anchor_from_clauses(
    *,
    clauses: Sequence[str],
    temporal_only: bool = False,
) -> str:
    for clause in clauses:
        normalized_clause = _clean_text(clause).lower()
        if not normalized_clause:
            continue
        scoped_text = normalized_clause
        prefix_key = ""
        parsed_clause = _typed_clause_slot(normalized_clause, slot="condition")
        if parsed_clause is not None:
            _prefix_text, prefix_key, scoped_value = parsed_clause
            scoped_text = scoped_value or scoped_text
        if temporal_only and not _temporal_clause_prefix_relation(prefix_key):
            continue
        candidates = _source_anchor_role_tokens(_CUE_TOKEN_RE.findall(scoped_text))
        if candidates:
            return _preferred_source_anchor_candidate(
                candidates,
                default_index=0,
                prefer_temporal=temporal_only,
            )
    return ""


def _source_anchor_family_pairs(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    source_span_text: str,
    anchors: Mapping[str, str],
) -> List[str]:
    source_family = _clean_text(formula.operator.family).lower()
    if not source_family:
        return []
    distinct_targets: List[str] = []

    def add(target: str) -> None:
        normalized_target = _clean_text(target).lower()
        if normalized_target and normalized_target not in distinct_targets:
            distinct_targets.append(normalized_target)

    for candidate_formula in document.formulas:
        add(candidate_formula.operator.family)
    if source_family == "frame" and set(distinct_targets or [source_family]) == {"frame"}:
        return ["frame->frame"]

    add(source_family)
    for target in _typed_decompiler_bridge_target_families(
        formula=formula,
        text=source_span_text,
        roles=anchors,
    ):
        add(target)
    for target in _typed_decompiler_directional_target_families(source_family):
        add(target)

    ordered_targets = sorted(
        distinct_targets,
        key=lambda target: (
            0 if target == source_family else 1,
            _CROSS_FAMILY_BRIDGE_FAMILY_PRIORITY.get(
                target,
                len(_CROSS_FAMILY_BRIDGE_FAMILY_PRIORITY),
            ),
            target,
        ),
    )
    return [f"{source_family}->{target}" for target in ordered_targets]


def _typed_deontic_ir_slots(
    *,
    formula: ModalIRFormula,
    document: ModalIRDocument,
    predicate_text: str,
    cue_values: Sequence[str],
    condition_values: Sequence[str],
    exception_values: Sequence[str],
) -> List[Tuple[str, str]]:
    family = _clean_text(formula.operator.family).lower()
    symbol = _clean_text(formula.operator.symbol)
    if not family or not symbol:
        return []

    deontic_candidates = _deontic_ir_candidate_cues(
        formula=formula,
        document=document,
        predicate_text=predicate_text,
        cue_values=cue_values,
    )
    if family != "deontic" and not deontic_candidates:
        return []

    force = _modal_force_label(formula)
    if family != "deontic" and deontic_candidates:
        force = _deontic_force_for_symbol(
            _deontic_symbol_for_cue(deontic_candidates[0], fallback_force=force)
        )
    polarity = _modal_scope_polarity(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
        document=document,
    )
    scope = "conditioned" if condition_values or exception_values else "unconditioned"
    selected_frame = _selected_frame(document)
    slots: List[Tuple[str, str]] = [
        ("typed_ir_view", "deontic.ir"),
        ("typed_ir_family_view", f"{family}:deontic.ir"),
        ("typed_ir_deontic_force", force),
        ("typed_ir_deontic_scope", scope),
        ("typed_ir_deontic_polarity", polarity),
        ("typed_ir_deontic_force_scope", f"{force}:{scope}"),
        ("typed_ir_deontic_force_polarity", f"{force}:{polarity}"),
        (
            "typed_ir_deontic_signature",
            f"{family}:{symbol}:{force}:{polarity}:{scope}",
        ),
    ]
    if family == "deontic":
        slots.extend(
            (
                ("typed_ir_deontic_family", "deontic"),
                ("typed_ir_deontic_operator", symbol),
                ("typed_ir_deontic_operator_signature", f"deontic:{symbol}:{force}"),
            )
        )
    if selected_frame:
        slots.extend(
            (
                ("typed_ir_deontic_frame_context", selected_frame),
                (
                    "typed_ir_deontic_frame_context_signature",
                    f"{family}:{selected_frame}:deontic.ir",
                ),
            )
        )

    for cue in deontic_candidates:
        target_symbol = _deontic_symbol_for_cue(cue, fallback_force=force)
        pair = f"{family}->deontic"
        slots.extend(
            (
                ("typed_ir_deontic_candidate_family", "deontic"),
                ("typed_ir_deontic_candidate_operator", target_symbol),
                ("typed_ir_deontic_candidate_cue", cue),
                (
                    "typed_ir_deontic_candidate_signature",
                    f"deontic:{target_symbol}:{cue}",
                ),
                ("typed_ir_deontic_candidate_family_pair", pair),
                (
                    "typed_ir_deontic_candidate_operator_pair",
                    f"{symbol}->{target_symbol}",
                ),
                (
                    "typed_ir_deontic_candidate_pair_cue",
                    f"{pair}:{cue}",
                ),
                (
                    "typed_ir_family_disambiguation",
                    f"{pair}:{force}:{cue}",
                ),
            )
        )
        if family == "frame":
            slots.extend(
                (
                    ("typed_ir_frame_deontic_bridge", f"Frame->{target_symbol}:{cue}"),
                    ("typed_ir_frame_deontic_bridge_family_pair", pair),
                    (
                        "typed_ir_frame_deontic_bridge_signature",
                        f"frame:Frame->deontic:{target_symbol}:{cue}",
                    ),
                )
            )
    return _unique_slot_values(slots)


def _deontic_ir_candidate_cues(
    *,
    formula: ModalIRFormula,
    document: ModalIRDocument,
    predicate_text: str,
    cue_values: Sequence[str],
) -> List[str]:
    search_segments = [
        predicate_text,
        " ".join(_phrase_values(formula.predicate.arguments)),
        " ".join(_phrase_values(formula.conditions)),
        " ".join(_phrase_values(formula.exceptions)),
        _formula_source_span_text(document=document, formula=formula),
    ]
    cues: List[str] = []
    for cue in cue_values:
        normalized = _clean_text(cue).lower().replace(" ", "_")
        if _is_deontic_bridge_cue(normalized) and normalized not in cues:
            cues.append(normalized)
    for segment in search_segments:
        for cue in _bridge_cues_from_text(segment):
            normalized = _clean_text(cue).lower().replace(" ", "_")
            if _is_deontic_bridge_cue(normalized) and normalized not in cues:
                cues.append(normalized)
    return cues


def _is_deontic_bridge_cue(cue: str) -> bool:
    normalized = _clean_text(cue).lower().replace(" ", "_")
    if not normalized:
        return False
    return any(
        bridge_family == "deontic"
        for bridge_family, _bridge_symbol in _cue_bridge_operator_pairs(normalized)
    )


def _is_conditional_normative_bridge_cue(cue: str) -> bool:
    normalized = _clean_text(cue).lower().replace(" ", "_")
    if not normalized:
        return False
    if normalized in _CLAUSE_PREFIX_BRIDGE_CUES:
        return True
    return any(
        bridge_family == "conditional_normative"
        for bridge_family, _bridge_symbol in _cue_bridge_operator_pairs(normalized)
    )


def _deontic_symbol_for_cue(cue: str, *, fallback_force: str) -> str:
    normalized = _clean_text(cue).lower().replace(" ", "_")
    for bridge_family, bridge_symbol in _cue_bridge_operator_pairs(normalized):
        if bridge_family == "deontic" and bridge_symbol:
            return bridge_symbol
    if fallback_force == "permission":
        return "P"
    if fallback_force == "prohibition":
        return "F"
    return "O"


def _deontic_force_for_symbol(symbol: str) -> str:
    normalized_symbol = _clean_text(symbol)
    if normalized_symbol == "P":
        return "permission"
    if normalized_symbol == "F":
        return "prohibition"
    return "obligation"


def _typed_decompiler_role_slots(
    *,
    formula: ModalIRFormula,
    text: str,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    normalized_text = _clean_text(text).replace("_", " ").lower()
    family = _clean_text(formula.operator.family).lower()
    if not normalized_slot_prefix or not normalized_text or not family:
        return []

    role_values = _semantic_role_values_from_text(normalized_text)
    semantic_atoms = _legal_semantic_atoms_from_text(normalized_text)
    temporal_values = _temporal_transition_context_cues_from_text(normalized_text)
    if not temporal_values:
        temporal_values = [
            cue
            for cue in _bridge_cues_from_text(normalized_text)
            if any(
                bridge_family == "temporal"
                for bridge_family, _bridge_symbol in _cue_bridge_operator_pairs(cue)
            )
        ]
    if temporal_values:
        role_values["temporal"] = "+".join(temporal_values)
    if not role_values and not semantic_atoms:
        return []

    slots: List[Tuple[str, str]] = []
    for role, value in role_values.items():
        slots.append((f"{normalized_slot_prefix}_typed_decompiler_role", role))
        slots.append((f"{normalized_slot_prefix}_typed_decompiler_{role}", value))
        slots.append(("typed_decompiler_role", role))
        slots.append((f"typed_decompiler_{role}", value))
        slots.extend(
            _typed_identifier_slots(
                value,
                slot_prefix=f"{normalized_slot_prefix}_typed_decompiler_{role}",
            )
        )
    if semantic_atoms:
        semantic_value = "+".join(semantic_atoms[:6])
        slots.extend(
            (
                (
                    f"{normalized_slot_prefix}_typed_decompiler_semantic",
                    semantic_value,
                ),
                ("typed_decompiler_semantic", semantic_value),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                semantic_value,
                slot_prefix=f"{normalized_slot_prefix}_typed_decompiler_semantic",
            )
        )
        for atom in semantic_atoms:
            slots.extend(
                (
                    (
                        f"{normalized_slot_prefix}_typed_decompiler_semantic_atom",
                        atom,
                    ),
                    ("typed_decompiler_semantic_atom", atom),
                    (
                        f"{normalized_slot_prefix}_typed_decompiler_family_semantic_atom",
                        f"{family}:{atom}",
                    ),
                    ("typed_decompiler_family_semantic_atom", f"{family}:{atom}"),
                )
            )

    role_signature = "+".join(
        role
        for role in ("subject", "action", "object", "temporal")
        if role in role_values
    )
    if role_signature:
        slots.extend(
            (
                (
                    f"{normalized_slot_prefix}_typed_decompiler_role_signature",
                    role_signature,
                ),
                ("typed_decompiler_role_signature", role_signature),
                (
                    f"{normalized_slot_prefix}_typed_decompiler_family_role_signature",
                    f"{family}:{role_signature}",
                ),
                (
                    "typed_decompiler_family_role_signature",
                    f"{family}:{role_signature}",
                ),
            )
        )
    bridge_targets = _typed_decompiler_bridge_target_families(
        formula=formula,
        text=normalized_text,
        roles=role_values,
    )
    for semantic_target in _typed_decompiler_semantic_atom_target_families(
        semantic_atoms
    ):
        if semantic_target not in bridge_targets:
            bridge_targets.append(semantic_target)
    for bridge_family in bridge_targets:
        pair = f"{family}->{bridge_family}"
        slots.extend(
            (
                (f"{normalized_slot_prefix}_typed_decompiler_family_pair", pair),
                ("typed_decompiler_family_pair", pair),
            )
        )
        for cue in _typed_decompiler_family_pair_cues(
            formula=formula,
            text=normalized_text,
            target_family=bridge_family,
        ):
            pair_cue = f"{pair}:{cue}"
            slots.extend(
                (
                    (
                        f"{normalized_slot_prefix}_typed_decompiler_family_pair_cue",
                        pair_cue,
                    ),
                    ("typed_decompiler_family_pair_cue", pair_cue),
                )
            )
        if role_signature:
            bridge_signature = f"{pair}:{role_signature}"
            slots.extend(
                (
                    (
                        f"{normalized_slot_prefix}_typed_decompiler_family_pair_bridge",
                        bridge_signature,
                    ),
                    ("typed_decompiler_family_pair_bridge", bridge_signature),
                )
            )
        for atom in semantic_atoms:
            slots.extend(
                (
                    (
                        f"{normalized_slot_prefix}_typed_decompiler_family_pair_semantic_atom",
                        f"{atom}:{pair}",
                    ),
                    ("typed_decompiler_family_pair_semantic_atom", f"{atom}:{pair}"),
                )
            )
    return _unique_slot_values(slots)


def _typed_decompiler_semantic_reconstruction_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    predicate_text: str,
    source_span_text: str,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
) -> str:
    """Return the bounded semantic surface used by typed family-pair slots."""
    heading_text = _fallback_section_heading_tail_text(
        document=document,
        formula=formula,
        max_tokens=18,
    )
    fallback_text = _fallback_surface_text(
        document=document,
        formula=formula,
        max_tokens=24,
    )
    return _clean_text(
        " ".join(
            value
            for value in (
                predicate_text,
                source_span_text,
                heading_text,
                fallback_text,
                " ".join(_phrase_values(condition_values)),
                " ".join(_phrase_values(exception_values)),
            )
            if _clean_text(value)
        )
    ).replace("_", " ").lower()


def _typed_decompiler_target_reconstruction_slots(
    *,
    formula: ModalIRFormula,
    document: ModalIRDocument,
    predicate_text: str,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
) -> List[Tuple[str, str]]:
    source_family = _clean_text(formula.operator.family).lower()
    source_symbol = _clean_text(formula.operator.symbol).lower()
    if not source_family:
        return []

    source_span_text = _formula_source_span_text(document=document, formula=formula)
    reconstruction_text = _typed_decompiler_semantic_reconstruction_text(
        document=document,
        formula=formula,
        predicate_text=predicate_text,
        source_span_text=source_span_text,
        condition_values=condition_values,
        exception_values=exception_values,
    )
    if not reconstruction_text:
        return []

    roles = _semantic_role_values_from_text(reconstruction_text)
    for role, value in _semantic_role_values_from_arguments(
        _phrase_values(formula.predicate.arguments)
    ).items():
        roles.setdefault(role, value)
    temporal_cues = _temporal_transition_context_cues_from_text(reconstruction_text)
    if temporal_cues:
        roles["temporal"] = "+".join(temporal_cues)
    elif source_family == "temporal":
        roles.setdefault("temporal", "temporal_operator_scope")
    semantic_atoms = _legal_semantic_atoms_from_text(reconstruction_text)
    status_detail_slots = _typed_decompiler_status_detail_slots(reconstruction_text)
    targets = _typed_decompiler_bridge_target_families(
        formula=formula,
        text=reconstruction_text,
        roles=roles,
    )
    for guided_target in _autoencoder_target_family_guidance_values(document):
        if guided_target not in targets:
            targets.append(guided_target)
    for guided_target in _autoencoder_family_pair_target_guidance_values(
        document,
        source_family=source_family,
    ):
        if guided_target not in targets:
            targets.append(guided_target)
    condition_cues = _typed_decompiler_condition_cues(
        condition_values=condition_values,
        exception_values=exception_values,
        text=reconstruction_text,
    )
    heading_cues = (
        ["heading"]
        if (
            _fallback_section_heading_tail_text(document=document, formula=formula)
            or _fallback_surface_text(document=document, formula=formula)
        )
        else []
    )
    has_conditioned_scope = bool(condition_values or exception_values or condition_cues)
    has_temporal_scope = bool(
        source_family == "temporal"
        or temporal_cues
        or any(_temporal_clause_prefix_relation(cue) for cue in condition_cues)
    )
    if has_conditioned_scope and "conditional_normative" not in targets:
        targets.append("conditional_normative")
    if has_temporal_scope and "temporal" not in targets:
        targets.append("temporal")
    if source_family == "frame" and "frame" not in targets:
        targets.append("frame")
    if (
        source_family in {"frame", "temporal", "conditional_normative"}
        and _has_deontic_reconstruction_cue(formula, reconstruction_text)
        and "deontic" not in targets
    ):
        targets.append("deontic")
    for semantic_target in _typed_decompiler_semantic_atom_target_families(
        semantic_atoms
    ):
        if semantic_target not in targets:
            targets.append(semantic_target)
    if source_family == "frame":
        for status_target in _typed_decompiler_status_atom_target_families(
            semantic_atoms
        ):
            if status_target not in targets:
                targets.append(status_target)
    for status_target in _typed_decompiler_status_detail_target_families(
        status_detail_slots
    ):
        if status_target not in targets:
            targets.append(status_target)
    for directional_target in _typed_decompiler_directional_target_families(
        source_family
    ):
        if directional_target not in targets:
            targets.append(directional_target)

    slots: List[Tuple[str, str]] = []
    scope_parts: List[str] = []
    if has_conditioned_scope:
        scope_parts.append("conditioned")
    if has_temporal_scope:
        scope_parts.append("temporal")
    if not scope_parts and not targets:
        return []

    scope_signature = "+".join(scope_parts) if scope_parts else "unconditioned"
    force = _modal_force_label(formula)
    polarity = _modal_scope_polarity(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
        document=document,
    )
    predicate_key = _slot_safe_family_pair_key(predicate_text)
    semantic_predicate_head = _typed_decompiler_semantic_predicate_head(
        formula=formula,
        reconstruction_text=reconstruction_text,
        semantic_atoms=semantic_atoms,
    )
    semantic_predicate_key = _slot_safe_family_pair_key(semantic_predicate_head)
    source_predicate = _source_predicate_family_pair_value(
        family=source_family,
        predicate_text=predicate_text,
        force=force,
        polarity=polarity,
    )
    for corrected_family, correction_reason in _typed_decompiler_corrected_source_families(
        encoded_family=source_family,
        text=reconstruction_text,
        temporal_cues=temporal_cues,
        condition_cues=condition_cues,
        has_temporal_scope=has_temporal_scope,
    ):
        slots.extend(
            _typed_decompiler_corrected_source_family_slots(
                encoded_family=source_family,
                corrected_family=corrected_family,
                reason=correction_reason,
                targets=targets,
                force=force,
                polarity=polarity,
                predicate_key=predicate_key,
            )
        )
    for target in targets:
        pair = f"{source_family}->{target}"
        slots.extend(
            (
                ("typed-decompiler-target-reconstruction-pair", pair),
                ("typed-decompiler-target-reconstruction-family", target),
                ("typed-decompiler-source-target-family", pair),
            )
        )
        if predicate_key:
            slots.extend(
                (
                    (
                        "typed-decompiler-source-predicate-family-pair",
                        f"{source_family}:{predicate_key}->{target}",
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        (
                            f"{target}||slot:typed-decompiler-source-predicate-family-pair:"
                            f"{source_family}:{predicate_key}->{target}||CEC.native"
                        ),
                    ),
                )
            )
        if source_predicate:
            slots.extend(
                (
                    (
                        "typed-decompiler-source-predicate-force-pair",
                        source_predicate,
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        (
                            f"{target}||slot:typed-decompiler-source-predicate-force-pair:"
                            f"{source_predicate}|typed-decompiler-force-polarity:"
                            f"{force}:{polarity}||CEC.native"
                        ),
                    ),
                )
            )
        slots.extend(
            _typed_decompiler_surface_profile_slots(
                document=document,
                formula=formula,
                source_family=source_family,
                target_family=target,
                pair=pair,
            )
        )
        slots.extend(
            _typed_decompiler_reconstruction_profile_slots(
                document=document,
                formula=formula,
                source_family=source_family,
                target_family=target,
                pair=pair,
                force=force,
                polarity=polarity,
                predicate_key=predicate_key,
                semantic_predicate_key=semantic_predicate_key,
                semantic_atoms=semantic_atoms,
            )
        )
        if semantic_predicate_key and semantic_predicate_key != predicate_key:
            semantic_source_force_value = (
                f"{source_family}:{semantic_predicate_key}|"
                f"typed-decompiler-force-polarity:{force}:{polarity}"
            )
            slots.extend(
                (
                    (
                        "typed-decompiler-semantic-predicate-head",
                        semantic_predicate_key,
                    ),
                    (
                        "typed-decompiler-semantic-predicate-family-pair",
                        f"{source_family}:{semantic_predicate_key}->{target}",
                    ),
                    (
                        "typed-decompiler-source-predicate-force-pair",
                        semantic_source_force_value,
                    ),
                    (
                        "typed-decompiler-source-predicate-force-family-pair",
                        f"{semantic_source_force_value}|typed-decompiler-family-pair:{pair}",
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        (
                            f"{target}||slot:typed-decompiler-semantic-predicate-head:"
                            f"{semantic_predicate_key}||CEC.native"
                        ),
                    ),
                )
            )
            slots.extend(
                _typed_decompiler_source_predicate_force_view_slots(
                    source_family=source_family,
                    target_family=target,
                    source_force_value=semantic_source_force_value,
                    force=force,
                    polarity=polarity,
                )
            )
        slots.extend(
            _typed_decompiler_force_polarity_family_pair_slots(
                source_family=source_family,
                target_family=target,
                force=force,
                polarity=polarity,
            )
        )
        slots.extend(
            _typed_decompiler_force_view_family_pair_slots(
                document=document,
                source_family=source_family,
                target_family=target,
                force=force,
                polarity=polarity,
            )
        )
        slots.append(
            (
                "typed-decompiler-target-reconstruction-scope",
                f"{scope_signature}:{pair}",
            )
        )
        formula_cues = [
            _clean_text(cue).lower().replace(" ", "_")
            for cue in _formula_cues(formula)
            if _clean_text(cue)
        ]
        family_pair_cues = _typed_decompiler_family_pair_cues(
            formula=formula,
            text=reconstruction_text,
            target_family=target,
        )
        source_surface_cues = _unique_text_values(
            (
                *_bridge_cues_from_text(reconstruction_text),
                *_deontic_surface_cues_from_text(reconstruction_text),
            )
        )
        semantic_target_cues = [
            atom
            for atom in semantic_atoms
            if _typed_decompiler_semantic_atom_supports_target(
                atom,
                target_family=target,
                source_family=source_family,
            )
        ]
        reconstruction_cues = _unique_text_values(
            (
                *heading_cues,
                *condition_cues,
                *formula_cues,
                *source_surface_cues,
                *semantic_target_cues,
                *family_pair_cues,
                *source_surface_cues,
            )
        )
        for cue in reconstruction_cues:
            slots.append(
                (
                    "typed_decompiler_target_reconstruction_cue",
                    f"{pair}:{cue}",
                )
            )
            slots.append(
                (
                    "typed-decompiler-target-reconstruction-cue",
                    f"{pair}:{cue}",
                )
            )
            slots.append(
                (
                    "typed-decompiler-target-family-surface-cue",
                    f"{cue}:{target}",
                )
            )
            for view in _source_scope_cue_legal_ir_views(cue):
                slots.extend(
                    (
                        ("legal_ir_view_prototype", view),
                        (
                            "source_scope_cue_legal_ir_view_prototype",
                            f"{cue}||{view}",
                        ),
                        (
                            "family_source_scope_cue_legal_ir_view_prototype",
                            f"{source_family}->{target}||{cue}||{view}",
                        ),
                        (
                            "semantic_slot_legal_ir_view_prototype",
                            f"slot:cue-family:{cue}:{target}||{view}",
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            f"{source_family}||slot:cue-family:{cue}:{target}||{view}",
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            f"{target}||slot:cue-family:{cue}:{target}||{view}",
                        ),
                )
            )
        for condition_index, _condition in enumerate(condition_values):
            typed_condition = _typed_clause_slot(
                _condition,
                slot="condition",
            )
            condition_role_text = (
                typed_condition[2]
                if typed_condition is not None and typed_condition[2]
                else _condition
            )
            condition_role_values = _semantic_role_values_from_text(
                _clean_text(condition_role_text).replace("_", " ").lower()
            )
            temporal_condition_cues = _temporal_transition_context_cues_from_text(
                _condition
            )
            if temporal_condition_cues:
                condition_role_values["temporal"] = "+".join(
                    temporal_condition_cues
                )
            if condition_role_values:
                role_names = [
                    role_name
                    for role_name in ("subject", "action", "object", "temporal")
                    if role_name in condition_role_values
                ]
                if role_names:
                    condition_role_signature = "+".join(role_names)
                    condition_role_slot = (
                        f"slot-pair:conditions:{condition_index}|"
                        f"predicate-role:{condition_role_signature}"
                    )
                    slots.extend(
                        (
                            ("semantic_slot_prototype", condition_role_slot),
                            (
                                "family_semantic_slot_prototype",
                                f"{source_family}||{condition_role_slot}",
                            ),
                            (
                                "family_semantic_slot_prototype",
                                f"{target}||{condition_role_slot}",
                            ),
                            (
                                "semantic_slot_legal_ir_view_prototype",
                                f"{condition_role_slot}||deontic.ir",
                            ),
                            (
                                "family_semantic_slot_legal_ir_view_prototype",
                                f"{source_family}||{condition_role_slot}||deontic.ir",
                            ),
                            (
                                "family_semantic_slot_legal_ir_view_prototype",
                                f"{target}||{condition_role_slot}||deontic.ir",
                            ),
                        )
                    )
                    if target in {"deontic", "temporal"}:
                        slots.extend(
                            (
                                (
                                    "family_semantic_slot_legal_ir_view_prototype",
                                    f"{target}||{condition_role_slot}||TDFOL.prover",
                                ),
                                (
                                    "family_semantic_slot_legal_ir_view_prototype",
                                    f"{target}||{condition_role_slot}||CEC.native",
                                ),
                            )
                        )
                for role_name, role_value in condition_role_values.items():
                    role_slot = (
                        f"slot-pair:conditions:{condition_index}|"
                        f"predicate-role:{role_name}"
                    )
                    role_value_slot = (
                        f"slot-pair:conditions:{condition_index}|"
                        f"predicate-role:{role_name}:{role_value}"
                    )
                    slots.extend(
                        (
                            ("semantic_slot_prototype", role_slot),
                            ("semantic_slot_prototype", role_value_slot),
                            (
                                "family_semantic_slot_prototype",
                                f"{source_family}||{role_slot}",
                            ),
                            (
                                "family_semantic_slot_prototype",
                                f"{target}||{role_slot}",
                            ),
                            (
                                "family_semantic_slot_legal_ir_view_prototype",
                                f"{source_family}||{role_value_slot}||deontic.ir",
                            ),
                            (
                                "family_semantic_slot_legal_ir_view_prototype",
                                f"{target}||{role_value_slot}||deontic.ir",
                            ),
                        )
                    )
            slots.extend(
                (
                    (
                        "semantic_slot_legal_ir_view_prototype",
                        (
                            f"slot-pair:conditions:{condition_index}|"
                            f"typed-decompiler-target-reconstruction-family:{target}||deontic.ir"
                        ),
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        (
                            f"{source_family}||slot-pair:conditions:{condition_index}|"
                            f"typed-decompiler-target-reconstruction-family:{target}||deontic.ir"
                        ),
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        (
                            f"{target}||slot-pair:conditions:{condition_index}|"
                            f"typed-decompiler-target-reconstruction-family:{target}||deontic.ir"
                        ),
                    ),
                )
            )
            if target in {"deontic", "temporal"}:
                slots.append(
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        (
                            f"{target}||slot-pair:conditions:{condition_index}|"
                            "typed-decompiler-target-reconstruction-family:deontic||"
                            "TDFOL.prover"
                        ),
                    )
                )
        for view in _typed_decompiler_family_pair_legal_ir_views(
            source_family,
            target,
        ):
            slots.extend(
                (
                    ("legal_ir_view_prototype", view),
                    (
                        "typed-decompiler-target-reconstruction-view",
                        f"{pair}||{view}",
                    ),
                    (
                        "semantic_slot_legal_ir_view_prototype",
                        f"slot:typed-decompiler-target-reconstruction-pair:{pair}||{view}",
                    ),
                    (
                        "semantic_slot_legal_ir_view_prototype",
                        f"slot:typed-decompiler-target-reconstruction-family:{target}||{view}",
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        f"{source_family}||slot:typed-decompiler-family-pair:{pair}||{view}",
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        f"{target}||slot:typed-decompiler-family-pair:{pair}||{view}",
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        f"{source_family}||slot:typed-decompiler-target-reconstruction-pair:{pair}||{view}",
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        f"{target}||slot:typed-decompiler-target-reconstruction-pair:{pair}||{view}",
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        f"{target}||slot:typed-decompiler-target-reconstruction-family:{target}||{view}",
                    ),
                )
            )
        slots.extend(
            _typed_decompiler_family_pair_predicate_slots(
                source_family=source_family,
                target_family=target,
                text=reconstruction_text,
                semantic_atoms=semantic_atoms,
            )
        )
        slots.extend(
            _typed_decompiler_family_pair_role_topology_slots(
                source_family=source_family,
                target_family=target,
                roles=roles,
                temporal_cues=temporal_cues,
                condition_cues=condition_cues,
                has_temporal_scope=has_temporal_scope,
            )
        )
        slots.extend(
            _typed_decompiler_family_pair_role_value_slots(
                source_family=source_family,
                target_family=target,
                roles=roles,
            )
        )
        for cue in condition_cues:
            slots.append(
                (
                    "typed-decompiler-target-reconstruction-surface-cue",
                    f"{cue}:{pair}",
                )
            )
            for view in _typed_decompiler_target_scope_cue_views(
                cue=cue,
                source_family=source_family,
                target_family=target,
            ):
                slots.extend(
                    (
                        ("legal_ir_view_prototype", view),
                        (
                            "semantic_slot_legal_ir_view_prototype",
                            (
                                f"slot:typed-decompiler-family-pair-cue:{pair}:"
                                f"{cue}||{view}"
                            ),
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            (
                                f"{target}||slot:typed-decompiler-family-pair-cue:"
                                f"{pair}:{cue}||{view}"
                            ),
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            (
                                f"{source_family}||slot:typed-decompiler-family-pair-cue:"
                                f"{pair}:{cue}||{view}"
                            ),
                        ),
                    )
                )
        for cue in reconstruction_cues:
            for view in _typed_decompiler_target_scope_cue_views(
                cue=cue,
                source_family=source_family,
                target_family=target,
            ):
                slots.extend(
                    (
                        ("legal_ir_view_prototype", view),
                        (
                            "semantic_slot_legal_ir_view_prototype",
                            (
                                f"slot:typed-decompiler-family-pair-cue:{pair}:"
                                f"{cue}||{view}"
                            ),
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            (
                                f"{target}||slot:typed-decompiler-family-pair-cue:"
                                f"{pair}:{cue}||{view}"
                            ),
                        ),
                    )
                )
            for view in _source_scope_cue_legal_ir_views(cue):
                slots.extend(
                    (
                        (
                            "semantic_slot_legal_ir_view_prototype",
                            f"slot:typed-decompiler-target-reconstruction-cue:{pair}:{cue}||{view}",
                        ),
                        (
                            "semantic_slot_legal_ir_view_prototype",
                            (
                                f"slot-pair:semantic-reconstruction-cue:{cue}|"
                                f"typed-decompiler-family-pair:{pair}||{view}"
                            ),
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            f"{source_family}||slot:typed-decompiler-target-reconstruction-cue:{pair}:{cue}||{view}",
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            f"{target}||slot:typed-decompiler-target-reconstruction-cue:{pair}:{cue}||{view}",
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            (
                                f"{target}||slot-pair:semantic-reconstruction-cue:{cue}|"
                                f"typed-decompiler-family-pair:{pair}||{view}"
                            ),
                        ),
                    )
                )
        source_scope_cues = _source_scope_reconstruction_cues(reconstruction_text)
        for cue in source_scope_cues:
            slots.extend(
                (
                    (
                        "typed-decompiler-surface-cue-family-pair",
                        f"{cue}:{pair}",
                    ),
                    (
                        "semantic_slot_legal_ir_view_prototype",
                        f"slot:typed-decompiler-surface-cue-family-pair:{cue}:{pair}||TDFOL.prover",
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        f"{target}||slot:typed-decompiler-surface-cue-family-pair:{cue}:{pair}||TDFOL.prover",
                    ),
                )
            )
        for atom in semantic_atoms:
            slots.extend(
                (
                    ("typed-decompiler-target-semantic-atom", atom),
                    (
                        "typed-decompiler-target-semantic-family-pair",
                        f"{atom}:{pair}",
                    ),
                )
            )
            for view in _legal_semantic_atom_legal_ir_views(atom):
                slots.extend(
                    (
                        ("legal_ir_view_prototype", view),
                        (
                            "semantic_slot_legal_ir_view_prototype",
                            f"slot:typed-decompiler-target-semantic-atom:{atom}||{view}",
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            f"{target}||slot:target-semantic-atom:{atom}||{view}",
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            (
                                f"{target}||slot-pair:target-semantic-atom:{atom}|"
                                f"typed-decompiler-family-pair:{pair}||{view}"
                            ),
                        ),
                    )
                )
        for status_slot, status_value in status_detail_slots:
            slots.extend(
                (
                    (status_slot, status_value),
                    (
                        "typed-decompiler-target-status-family-pair",
                        f"{status_slot}:{status_value}:{pair}",
                    ),
                )
            )
            for view in _typed_decompiler_status_detail_legal_ir_views(
                status_slot,
                status_value,
            ):
                slots.extend(
                    (
                        ("legal_ir_view_prototype", view),
                        (
                            "semantic_slot_legal_ir_view_prototype",
                            f"slot:{status_slot}:{status_value}||{view}",
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            (
                                f"{target}||slot-pair:{status_slot}:{status_value}|"
                                f"typed-decompiler-family-pair:{pair}||{view}"
                            ),
                        ),
                    )
                )
            slots.extend(
                _typed_decompiler_status_surface_profile_slots(
                    source_family=source_family,
                    target_family=target,
                    status_slot=status_slot,
                    status_value=status_value,
                )
            )
        if target == "temporal" and has_temporal_scope:
            temporal_symbol = (
                source_symbol if source_family == "temporal" and source_symbol else "f"
            )
            slots.extend(
                (
                    (
                        "defeasible-priority",
                        f"temporal-priority:temporal-guard:none:temporal:{temporal_symbol}:clause",
                    ),
                    (
                        "entity-binding",
                        f"system-binding:ltl:temporal:{temporal_symbol}:temporal-order:clause",
                    ),
                )
            )
            for role in ("subject", "action", "object"):
                if role in roles:
                    slots.append(
                        (
                            "entity-binding",
                            f"source-ir-role:{role}:none:temporal:{temporal_symbol}:clause",
                        )
                    )
        slots.extend(
            _typed_decompiler_temporal_target_role_slots(
                source_family=source_family,
                target_family=target,
                source_symbol=source_symbol,
                roles=roles,
                temporal_cues=temporal_cues,
                condition_cues=condition_cues,
                has_temporal_scope=has_temporal_scope,
            )
        )

    force = _modal_force_label(formula)
    polarity = _modal_scope_polarity(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
        document=document,
    )
    slots.extend(
        _typed_decompiler_force_polarity_reconstruction_slots(
            formula=formula,
            source_family=source_family,
            targets=targets,
            reconstruction_text=reconstruction_text,
            condition_values=condition_values,
            exception_values=exception_values,
            document=document,
        )
    )
    if source_family == "deontic" and force == "permission" and polarity == "positive_scope":
        for target in (
            "conditional_normative",
            "deontic",
            "epistemic",
            "frame",
            "temporal",
        ):
            slots.append(
                (
                    "decompiler-plan",
                    f"force-polarity-family-pair:permission:enabling:deontic->{target}",
                )
            )
    return _unique_slot_values(slots)


def _typed_decompiler_force_polarity_reconstruction_slots(
    *,
    formula: ModalIRFormula,
    source_family: str,
    targets: Sequence[str],
    reconstruction_text: str,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    document: ModalIRDocument,
) -> List[Tuple[str, str]]:
    """Bind deontic force/polarity to target-family reconstruction slots."""
    normalized_source = _clean_text(source_family).lower()
    if not normalized_source or not targets:
        return []

    force = _modal_force_label(formula)
    polarity = _modal_scope_polarity(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
        document=document,
    )
    cues = _typed_decompiler_source_force_cues(
        formula=formula,
        reconstruction_text=reconstruction_text,
        condition_values=condition_values,
        exception_values=exception_values,
    )
    force_values = [force]
    polarity_values = [polarity]
    for cue in cues:
        cue_force = _typed_decompiler_force_for_cue(cue)
        if cue_force and cue_force not in force_values:
            force_values.append(cue_force)
        for cue_polarity in _typed_decompiler_polarities_for_cue(
            cue,
            condition_values=condition_values,
            exception_values=exception_values,
            text=reconstruction_text,
        ):
            if cue_polarity and cue_polarity not in polarity_values:
                polarity_values.append(cue_polarity)

    slots: List[Tuple[str, str]] = []
    for target in targets:
        normalized_target = _clean_text(target).lower()
        if not normalized_target:
            continue
        pair = f"{normalized_source}->{normalized_target}"
        scope_values = _typed_decompiler_force_polarity_scope_values(
            source_family=normalized_source,
            target_family=normalized_target,
            reconstruction_text=reconstruction_text,
            condition_values=condition_values,
            exception_values=exception_values,
        )
        for force_value in force_values:
            for polarity_value in polarity_values:
                signature = f"{force_value}:{polarity_value}:{normalized_target}"
                family_pair_signature = (
                    f"{force_value}:{polarity_value}:{pair}"
                )
                slots.extend(
                    (
                        ("typed-decompiler-force-polarity", signature),
                        (
                            "typed-decompiler-force-polarity-family-pair",
                            family_pair_signature,
                        ),
                        (
                            "decompiler-plan",
                            f"force-polarity-family-pair:{family_pair_signature}",
                        ),
                    )
                )
                slots.extend(
                    _typed_decompiler_force_view_family_pair_slots(
                        document=document,
                        source_family=normalized_source,
                        target_family=normalized_target,
                        force=force_value,
                        polarity=polarity_value,
                    )
                )
                for view in _typed_decompiler_family_pair_legal_ir_views(
                    normalized_source,
                    normalized_target,
                ):
                    slot_value = (
                        "slot:typed-decompiler-force-polarity:"
                        f"{signature}||{view}"
                    )
                    pair_slot_value = (
                        "slot:typed-decompiler-force-polarity-family-pair:"
                        f"{family_pair_signature}||{view}"
                    )
                    slots.extend(
                        (
                            ("semantic_slot_legal_ir_view_prototype", slot_value),
                            (
                                "semantic_slot_legal_ir_view_prototype",
                                pair_slot_value,
                            ),
                            (
                                "family_semantic_slot_legal_ir_view_prototype",
                                f"{normalized_source}||{slot_value}",
                            ),
                            (
                                "family_semantic_slot_legal_ir_view_prototype",
                                f"{normalized_target}||{slot_value}",
                            ),
                            (
                                "family_semantic_slot_legal_ir_view_prototype",
                                f"{normalized_source}||{pair_slot_value}",
                            ),
                            (
                                "family_semantic_slot_legal_ir_view_prototype",
                                f"{normalized_target}||{pair_slot_value}",
                            ),
                        )
                    )
                for scope_value in scope_values:
                    scoped_family_pair_signature = (
                        f"{force_value}:{polarity_value}:{scope_value}:{pair}"
                    )
                    slots.extend(
                        (
                            (
                                "typed-decompiler-force-polarity-scope-family-pair",
                                scoped_family_pair_signature,
                            ),
                            (
                                "decompiler-plan",
                                (
                                    "force-polarity-scope-family-pair:"
                                    f"{scoped_family_pair_signature}"
                                ),
                            ),
                        )
                    )
                    for view in _typed_decompiler_family_pair_legal_ir_views(
                        normalized_source,
                        normalized_target,
                    ):
                        scoped_slot_value = (
                            "slot:typed-decompiler-force-polarity-scope-family-pair:"
                            f"{scoped_family_pair_signature}||{view}"
                        )
                        slots.extend(
                            (
                                (
                                    "semantic_slot_legal_ir_view_prototype",
                                    scoped_slot_value,
                                ),
                                (
                                    "family_semantic_slot_legal_ir_view_prototype",
                                    f"{normalized_source}||{scoped_slot_value}",
                                ),
                                (
                                    "family_semantic_slot_legal_ir_view_prototype",
                                    f"{normalized_target}||{scoped_slot_value}",
                                ),
                            )
                        )
    return _unique_slot_values(slots)


def _typed_decompiler_force_polarity_scope_values(
    *,
    source_family: str,
    target_family: str,
    reconstruction_text: str,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
) -> List[str]:
    """Return semantic scopes that refine force/polarity family-pair slots."""
    normalized_text = _clean_text(reconstruction_text).replace("_", " ").lower()
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    condition_cues = _typed_decompiler_condition_cues(
        condition_values=condition_values,
        exception_values=exception_values,
        text=normalized_text,
    )
    source_scope_cues = _source_scope_reconstruction_cues(normalized_text)
    scope_cues = _unique_text_values((*condition_cues, *source_scope_cues))
    scopes: List[str] = []

    def add(scope: str) -> None:
        normalized_scope = _clean_text(scope).lower().replace(" ", "_")
        if normalized_scope and normalized_scope not in scopes:
            scopes.append(normalized_scope)

    if any(
        cue in _TEMPORAL_BRIDGE_CONTEXT_TOKENS
        or _temporal_clause_prefix_relation(cue)
        or cue
        in {
            "after_conclusion",
            "calendar_year",
            "effective_date",
            "fiscal_year",
            "no_later_than",
            "not_later_than",
            "on_and_after",
            "on_or_after",
            "testing_period",
            "within",
        }
        for cue in scope_cues
    ) or _temporal_transition_context_cues_from_text(normalized_text):
        add("temporal")
    if condition_values or exception_values or any(
        cue in _CLAUSE_PREFIX_BRIDGE_CUES
        or cue.startswith("except")
        or cue in {"provided", "provided_that", "unless", "with_consent"}
        for cue in scope_cues
    ):
        add("conditional")
    if _statutory_scope_slots(normalized_text):
        add("statutory")
    if (
        source == "doxastic"
        or target == "doxastic"
        or _doxastic_bridge_families_from_text(normalized_text)
    ):
        add("mental_state")
    return scopes


def _typed_decompiler_source_reconstruction_slots(
    *,
    formula: ModalIRFormula,
    document: ModalIRDocument,
    predicate_text: str,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
) -> List[Tuple[str, str]]:
    source_family = _clean_text(formula.operator.family).lower()
    source_symbol = _clean_text(formula.operator.symbol).lower()
    if not source_family:
        return []

    source_span_text = _formula_source_span_text(document=document, formula=formula)
    reconstruction_text = _typed_decompiler_semantic_reconstruction_text(
        document=document,
        formula=formula,
        predicate_text=predicate_text,
        source_span_text=source_span_text,
        condition_values=condition_values,
        exception_values=exception_values,
    )
    if not reconstruction_text:
        return []

    roles = _semantic_role_values_from_text(reconstruction_text)
    for role, value in _semantic_role_values_from_arguments(
        _phrase_values(formula.predicate.arguments)
    ).items():
        roles.setdefault(role, value)
    temporal_cues = _temporal_transition_context_cues_from_text(reconstruction_text)
    if temporal_cues:
        roles["temporal"] = "+".join(temporal_cues)
    targets = _typed_decompiler_bridge_target_families(
        formula=formula,
        text=reconstruction_text,
        roles=roles,
    )
    for guided_target in _autoencoder_target_family_guidance_values(document):
        if guided_target not in targets:
            targets.append(guided_target)
    for guided_target in _autoencoder_family_pair_target_guidance_values(
        document,
        source_family=source_family,
    ):
        if guided_target not in targets:
            targets.append(guided_target)
    condition_cues = _typed_decompiler_condition_cues(
        condition_values=condition_values,
        exception_values=exception_values,
        text=reconstruction_text,
    )
    source_scope_cues = _source_scope_reconstruction_cues(reconstruction_text)
    semantic_atoms = _legal_semantic_atoms_from_text(reconstruction_text)
    status_detail_slots = _typed_decompiler_status_detail_slots(reconstruction_text)
    if not source_scope_cues and not semantic_atoms and not status_detail_slots:
        return []
    semantic_topology_atoms = [
        atom
        for atom in semantic_atoms
        if atom
        not in {
            "exception_or_condition",
            "obligation",
            "permission",
            "prohibition",
            "temporal_condition",
        }
    ]

    if (
        condition_values or exception_values or condition_cues
    ) and "conditional_normative" not in targets:
        targets.append("conditional_normative")
    if (
        temporal_cues
        or any(_temporal_clause_prefix_relation(cue) for cue in condition_cues)
    ) and "temporal" not in targets:
        targets.append("temporal")
    if source_family == "frame" and "frame" not in targets:
        targets.append("frame")
    if (
        source_family in {"frame", "temporal", "conditional_normative"}
        and _has_deontic_reconstruction_cue(formula, reconstruction_text)
        and "deontic" not in targets
    ):
        targets.append("deontic")
    for semantic_target in _typed_decompiler_semantic_atom_target_families(
        semantic_atoms
    ):
        if semantic_target not in targets:
            targets.append(semantic_target)
    if source_family == "frame":
        for status_target in _typed_decompiler_status_atom_target_families(
            semantic_atoms
        ):
            if status_target not in targets:
                targets.append(status_target)
    for status_target in _typed_decompiler_status_detail_target_families(
        status_detail_slots
    ):
        if status_target not in targets:
            targets.append(status_target)
    for directional_target in _typed_decompiler_directional_target_families(
        source_family
    ):
        if directional_target not in targets:
            targets.append(directional_target)

    force = _modal_force_label(formula)
    polarity = _modal_scope_polarity(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
        document=document,
    )
    raw_predicate_head = _typed_decompiler_predicate_head(formula)
    predicate_head = _typed_decompiler_semantic_predicate_head(
        formula=formula,
        reconstruction_text=reconstruction_text,
        semantic_atoms=semantic_atoms,
    ) or raw_predicate_head
    topology_parts = [
        part
        for part, present in (
            ("condition", bool(condition_values or condition_cues)),
            ("subject", "subject" in roles),
            ("action", "action" in roles),
            ("object", "object" in roles),
            ("exception", bool(exception_values)),
            ("temporal", bool(temporal_cues)),
            ("semantic", bool(semantic_topology_atoms)),
        )
        if present
    ]
    topology = "+".join(topology_parts) if topology_parts else "unscoped"

    slots: List[Tuple[str, str]] = [
        (
            "typed-decompiler-raw-predicate-head",
            raw_predicate_head,
        ),
        (
            "typed-decompiler-semantic-predicate-head",
            predicate_head,
        ),
        (
            "typed-decompiler-source-predicate-force-pair",
            f"{source_family}:{predicate_head}|typed-decompiler-force-polarity:{force}:{polarity}",
        ),
        (
            "typed-decompiler-source-clause-topology",
            f"{topology}:{source_family}:{source_symbol or 'none'}",
        ),
    ]
    for corrected_family, correction_reason in _typed_decompiler_corrected_source_families(
        encoded_family=source_family,
        text=reconstruction_text,
        temporal_cues=temporal_cues,
        condition_cues=condition_cues,
        has_temporal_scope="temporal" in topology_parts,
    ):
        slots.extend(
            _typed_decompiler_corrected_source_family_slots(
                encoded_family=source_family,
                corrected_family=corrected_family,
                reason=correction_reason,
                targets=targets,
                force=force,
                polarity=polarity,
                predicate_key=predicate_head,
            )
        )
    if raw_predicate_head and raw_predicate_head != predicate_head:
        slots.append(
            (
                "typed-decompiler-source-predicate-force-pair",
                (
                    f"{source_family}:{raw_predicate_head}|"
                    f"typed-decompiler-force-polarity:{force}:{polarity}"
                ),
            )
        )
    source_predicate = _source_predicate_family_pair_value(
        family=source_family,
        predicate_text=predicate_text,
        force=force,
        polarity=polarity,
    )
    for cue in _typed_decompiler_source_force_cues(
        formula=formula,
        reconstruction_text=reconstruction_text,
        condition_values=condition_values,
        exception_values=exception_values,
    ):
        cue_force = _typed_decompiler_force_for_cue(cue)
        if not cue_force:
            continue
        for cue_polarity in _typed_decompiler_polarities_for_cue(
            cue,
            condition_values=condition_values,
            exception_values=exception_values,
            text=reconstruction_text,
        ):
            source_force_value = (
                f"{source_family}:{predicate_head}|"
                f"typed-decompiler-force-polarity:{cue_force}:{cue_polarity}"
            )
            slots.extend(
                (
                    ("typed-decompiler-source-force-cue", cue),
                    (
                        "typed-decompiler-source-predicate-force-pair",
                        source_force_value,
                    ),
                    (
                        "typed-decompiler-source-predicate-force-cue",
                        f"{cue}:{source_force_value}",
                    ),
                )
            )
            raw_source_force_value = ""
            if raw_predicate_head and raw_predicate_head != predicate_head:
                raw_source_force_value = (
                    f"{source_family}:{raw_predicate_head}|"
                    f"typed-decompiler-force-polarity:{cue_force}:{cue_polarity}"
                )
                slots.extend(
                    (
                        (
                            "typed-decompiler-source-predicate-force-pair",
                            raw_source_force_value,
                        ),
                        (
                            "typed-decompiler-source-predicate-force-cue",
                            f"{cue}:{raw_source_force_value}",
                        ),
                    )
                )
            for target in targets or [source_family]:
                pair = f"{source_family}->{target}"
                slots.extend(
                    (
                        (
                            "typed-decompiler-source-predicate-force-family-pair",
                            f"{source_force_value}|typed-decompiler-family-pair:{pair}",
                        ),
                        (
                            "family_semantic_slot_prototype",
                            (
                                f"{target}||slot:typed-decompiler-source-predicate-force-pair:"
                                f"{source_force_value}"
                            ),
                        ),
                    )
                )
                if raw_source_force_value:
                    slots.extend(
                        (
                            (
                                "typed-decompiler-source-predicate-force-family-pair",
                                (
                                    f"{raw_source_force_value}|"
                                    f"typed-decompiler-family-pair:{pair}"
                                ),
                            ),
                            (
                                "family_semantic_slot_prototype",
                                (
                                    f"{target}||slot:typed-decompiler-source-predicate-force-pair:"
                                    f"{raw_source_force_value}"
                                ),
                            ),
                        )
                    )
                for view in _typed_decompiler_family_pair_legal_ir_views(
                    source_family,
                    target,
                ):
                    slots.append(
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            (
                                f"{target}||slot:typed-decompiler-source-predicate-force-pair:"
                                f"{source_force_value}||{view}"
                            ),
                        )
                    )
                    if raw_source_force_value:
                        slots.append(
                            (
                                "family_semantic_slot_legal_ir_view_prototype",
                                (
                                    f"{target}||slot:typed-decompiler-source-predicate-force-pair:"
                                    f"{raw_source_force_value}||{view}"
                                ),
                            )
                        )
                slots.extend(
                    _typed_decompiler_source_predicate_force_view_slots(
                        source_family=source_family,
                        target_family=target,
                        source_force_value=source_force_value,
                        force=cue_force,
                        polarity=cue_polarity,
                    )
                )
                if raw_source_force_value:
                    slots.extend(
                        _typed_decompiler_source_predicate_force_view_slots(
                            source_family=source_family,
                            target_family=target,
                            source_force_value=raw_source_force_value,
                            force=cue_force,
                            polarity=cue_polarity,
                        )
                    )
    if exception_values or any(cue.startswith("except") for cue in condition_cues):
        slots.extend(
            (
                ("family_exception_present", "conditional_normative"),
                (
                    "family_semantic_slot_prototype",
                    "conditional_normative||slot:family-exception-present:conditional_normative",
                ),
            )
        )
    for target in targets:
        pair = f"{source_family}->{target}"
        slots.extend(
            (
                (
                    "typed-decompiler-source-clause-topology-family-pair",
                    f"{topology}:{source_family}|typed-decompiler-family-pair:{pair}",
                ),
                (
                    "typed-decompiler-source-predicate-family-pair",
                    f"{source_family}:{predicate_head}->{target}",
                ),
            )
        )
        if source_predicate:
            slots.append(
                (
                    "typed-decompiler-source-predicate-force-pair",
                    source_predicate,
                )
            )
            slots.extend(
                _typed_decompiler_source_predicate_force_view_slots(
                    source_family=source_family,
                    target_family=target,
                    source_force_value=source_predicate,
                    force=force,
                    polarity=polarity,
                )
            )
        slots.extend(
            _typed_decompiler_force_polarity_family_pair_slots(
                source_family=source_family,
                target_family=target,
                force=force,
                polarity=polarity,
            )
        )
        for view in _typed_decompiler_family_pair_legal_ir_views(
            source_family,
            target,
        ):
            slots.extend(
                (
                    ("legal_ir_view_prototype", view),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        f"{source_family}||slot:typed-decompiler-family-pair:{pair}||{view}",
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        f"{target}||slot:typed-decompiler-family-pair:{pair}||{view}",
                    ),
                )
            )
        slots.extend(
            _typed_decompiler_family_pair_predicate_slots(
                source_family=source_family,
                target_family=target,
                text=reconstruction_text,
                semantic_atoms=semantic_atoms,
            )
        )
        slots.extend(
            _typed_decompiler_family_pair_role_topology_slots(
                source_family=source_family,
                target_family=target,
                roles=roles,
                temporal_cues=temporal_cues,
                condition_cues=condition_cues,
                has_temporal_scope="temporal" in topology_parts,
            )
        )
    for cue in source_scope_cues:
        slots.extend(
            (
                ("typed-decompiler-source-scope-cue", cue),
                (
                    "typed-decompiler-surface-cue-family-pair",
                    f"{cue}:{source_family}->{source_family}",
                ),
                (
                    "typed-decompiler-source-scope-signature",
                    f"{source_family}:{source_symbol or 'none'}:{topology}:{cue}",
                ),
            )
        )
        for target in targets:
            slots.append(
                (
                    "typed-decompiler-surface-cue-family-pair",
                    f"{cue}:{source_family}->{target}",
                )
            )
        for view in _source_scope_cue_legal_ir_views(cue):
            slots.extend(
                (
                    ("legal_ir_view_prototype", view),
                    (
                        "source_scope_cue_legal_ir_view_prototype",
                        f"{cue}||{view}",
                    ),
                    (
                        "family_source_scope_cue_legal_ir_view_prototype",
                        f"{source_family}||{cue}||{view}",
                    ),
                )
            )
    for atom in semantic_atoms:
        slots.extend(
            (
                ("typed-decompiler-source-semantic-atom", atom),
                (
                    "typed-decompiler-source-semantic-atom-family",
                    f"{source_family}:{atom}",
                ),
            )
        )
        for target in targets:
            pair = f"{source_family}->{target}"
            slots.append(
                (
                    "typed-decompiler-source-semantic-family-pair",
                    f"{atom}:{pair}",
                )
            )
            for view in _legal_semantic_atom_legal_ir_views(atom):
                slots.extend(
                    (
                        ("legal_ir_view_prototype", view),
                        (
                            "semantic_slot_legal_ir_view_prototype",
                            f"slot:typed-decompiler-source-semantic-atom:{atom}||{view}",
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            f"{source_family}||slot:source-semantic-atom:{atom}||{view}",
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            (
                                f"{source_family}||slot-pair:source-semantic-atom:{atom}|"
                                f"typed-decompiler-family-pair:{pair}||{view}"
                            ),
                        ),
                    )
                )
    for status_slot, status_value in status_detail_slots:
        slots.extend(
            (
                (status_slot, status_value),
                (
                    "typed-decompiler-source-status-signature",
                    f"{source_family}:{source_symbol or 'none'}:{status_slot}:{status_value}",
                ),
            )
        )
        for target in targets:
            pair = f"{source_family}->{target}"
            slots.append(
                (
                    "typed-decompiler-source-status-family-pair",
                    f"{status_slot}:{status_value}:{pair}",
                )
            )
            for view in _typed_decompiler_status_detail_legal_ir_views(
                status_slot,
                status_value,
            ):
                slots.extend(
                    (
                        ("legal_ir_view_prototype", view),
                        (
                            "semantic_slot_legal_ir_view_prototype",
                            f"slot:{status_slot}:{status_value}||{view}",
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            (
                                f"{source_family}||slot-pair:{status_slot}:{status_value}|"
                                f"typed-decompiler-family-pair:{pair}||{view}"
                            ),
                        ),
                    )
                )
    return _unique_slot_values(slots)


def _typed_decompiler_conditional_normative_preservation_slots(
    *,
    formula: ModalIRFormula,
    document: ModalIRDocument,
    predicate_text: str,
    cue_values: Sequence[str],
    condition_values: Sequence[str],
    exception_values: Sequence[str],
) -> List[Tuple[str, str]]:
    """Expose conditional-normative family evidence with stable slot names."""
    source_family = _clean_text(formula.operator.family).lower()
    source_symbol = _clean_text(formula.operator.symbol)
    if not source_family:
        return []

    source_span_text = _formula_source_span_text(document=document, formula=formula)
    reconstruction_text = _typed_decompiler_semantic_reconstruction_text(
        document=document,
        formula=formula,
        predicate_text=predicate_text,
        source_span_text=source_span_text,
        condition_values=condition_values,
        exception_values=exception_values,
    )
    condition_cues = _typed_decompiler_condition_cues(
        condition_values=condition_values,
        exception_values=exception_values,
        text=reconstruction_text,
    )
    bridge_cues = _unique_text_values(
        (
            *(
                _clean_text(cue).lower().replace(" ", "_")
                for cue in cue_values
                if _clean_text(cue)
            ),
            *_formula_bridge_cues(
                formula,
                extra_clauses=(*condition_values, *exception_values),
            ),
            *_bridge_cues_from_text(reconstruction_text),
            *condition_cues,
        )
    )
    conditional_cues = [
        cue
        for cue in bridge_cues
        if _is_conditional_normative_bridge_cue(cue)
    ]
    has_conditional_scope = bool(
        condition_values
        or exception_values
        or conditional_cues
        or source_symbol == "O|"
        or source_family == "conditional_normative"
    )
    if not has_conditional_scope:
        return []

    target_family = "conditional_normative"
    pair = f"{source_family}->{target_family}"
    force = _modal_force_label(formula)
    polarity = _modal_scope_polarity(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
        document=document,
    )
    predicate_key = _slot_safe_family_pair_key(predicate_text)
    semantic_atoms = _legal_semantic_atoms_from_text(reconstruction_text)
    slots: List[Tuple[str, str]] = [
        ("typed_decompiler_family_pair", pair),
        ("typed_decompiler_conditional_normative_family", target_family),
        ("typed_decompiler_conditional_normative_source_family", source_family),
        (
            "typed_decompiler_conditional_normative_signature",
            f"{pair}:{force}:{polarity}",
        ),
        (
            "typed_decompiler_force_polarity_family_pair",
            f"{force}:{polarity}:{pair}",
        ),
        (
            "decompiler-plan",
            f"conditional-normative-preservation:{force}:{polarity}:{pair}",
        ),
    ]
    if source_family == target_family:
        slots.extend(
            (
                ("typed_decompiler_family_preservation", target_family),
                ("typed_decompiler_family_preservation_pair", pair),
            )
        )
    if predicate_key:
        slots.extend(
            (
                (
                    "typed_decompiler_conditional_normative_predicate_pair",
                    f"{predicate_key}:{pair}",
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        f"{target_family}||slot:typed_decompiler_family_pair:"
                        f"{pair}||CEC.native"
                    ),
                ),
            )
        )
    for cue in conditional_cues or ["conditional_scope"]:
        cue_pair = f"{pair}:{cue}"
        slots.extend(
            (
                ("typed_decompiler_family_pair_cue", cue_pair),
                ("typed_decompiler_conditional_normative_cue", cue),
                (
                    "typed_decompiler_conditional_normative_cue_pair",
                    cue_pair,
                ),
                (
                    "semantic_slot_legal_ir_view_prototype",
                    (
                        f"slot:typed_decompiler_family_pair_cue:"
                        f"{cue_pair}||CEC.native"
                    ),
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        f"{target_family}||slot:typed_decompiler_family_pair_cue:"
                        f"{cue_pair}||CEC.native"
                    ),
                ),
            )
        )
    for atom in semantic_atoms:
        if not _typed_decompiler_semantic_atom_supports_target(
            atom,
            target_family=target_family,
            source_family=source_family,
        ):
            continue
        slots.extend(
            (
                (
                    "typed_decompiler_conditional_normative_semantic_pair",
                    f"{atom}:{pair}",
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        f"{target_family}||slot-pair:semantic-atom:{atom}|"
                        f"typed_decompiler_family_pair:{pair}||CEC.native"
                    ),
                ),
            )
        )
    return _unique_slot_values(slots)


def _typed_decompiler_source_force_cues(
    *,
    formula: ModalIRFormula,
    reconstruction_text: str,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
) -> List[str]:
    cues: List[str] = []

    def add(cue: str) -> None:
        normalized = _clean_text(cue).lower().replace(" ", "_")
        if normalized and normalized not in cues:
            cues.append(normalized)

    for cue in _formula_cues(formula):
        add(cue)
    for cue in _bridge_cues_from_text(reconstruction_text):
        add(cue)
    for cue in _typed_decompiler_condition_cues(
        condition_values=condition_values,
        exception_values=exception_values,
        text=reconstruction_text,
    ):
        add(cue)
    return cues


def _typed_decompiler_source_predicate_force_view_slots(
    *,
    source_family: str,
    target_family: str,
    source_force_value: str,
    force: str,
    polarity: str,
) -> List[Tuple[str, str]]:
    """Bind source predicate/force slots to pair and deontic LegalIR views."""
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    value = _clean_text(source_force_value)
    force_key = _slot_safe_family_pair_key(force)
    polarity_key = _slot_safe_family_pair_key(polarity)
    if not source or not target or not value:
        return []

    pair = f"{source}->{target}"
    views = list(_typed_decompiler_family_pair_legal_ir_views(source, target))

    def add_view(view: str) -> None:
        normalized = _clean_text(view)
        if normalized and normalized not in views:
            views.append(normalized)

    if force_key in {"obligation", "permission", "prohibition"}:
        add_view("deontic.ir")
        add_view("TDFOL.prover")
        add_view("CEC.native")
    if polarity_key in {"conditional", "excepted", "mandatory", "negative_scope"}:
        add_view("deontic.ir")
    if target == "conditional_normative":
        add_view("deontic.ir")
        add_view("TDFOL.prover")

    slots: List[Tuple[str, str]] = [
        (
            "typed-decompiler-source-predicate-force-family-pair",
            f"{value}|typed-decompiler-family-pair:{pair}",
        )
    ]
    for view in views:
        slots.extend(
            (
                ("legal_ir_view_prototype", view),
                (
                    "typed-decompiler-source-predicate-force-view-family-pair",
                    f"{value}||{view}||{pair}",
                ),
                (
                    "semantic_slot_legal_ir_view_prototype",
                    f"slot:typed-decompiler-source-predicate-force-pair:{value}||{view}",
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    f"{source}||slot:typed-decompiler-source-predicate-force-pair:{value}||{view}",
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    f"{target}||slot:typed-decompiler-source-predicate-force-pair:{value}||{view}",
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        f"{target}||slot:typed-decompiler-source-predicate-force-pair:"
                        f"{value}|typed-decompiler-family-pair:{pair}||{view}"
                    ),
                ),
            )
        )
    return _unique_slot_values(slots)


def _legal_semantic_atom_legal_ir_views(atom: str) -> List[str]:
    normalized_atom = _clean_text(atom).lower()
    if not normalized_atom:
        return []
    views: List[str] = []

    def add(view: str) -> None:
        if view and view not in views:
            views.append(view)

    if normalized_atom in {
        "department_office_seal",
        "excise_tax",
        "foreign_service_grievance",
        "former_employee_grievance",
        "judicial_notice",
        "manufacturers_excise_tax",
        "recreational_equipment_tax",
        "statutory_severability",
    }:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")

    if normalized_atom in {
        "judicial_review",
        "presidential_action",
        "presidential_action_judicial_review",
        "presidential_order",
        "receiver_appointment",
        "receiver_duty",
        "receivership_administration",
        "renewable_energy_barrier_study",
        "renewable_energy_project",
        "renewable_energy_tax_rate_treatment",
        "utility_ratemaking_procedure",
    }:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")

    if normalized_atom in {
        "excess_hospital_capacity",
        "excess_hospital_capacity_reduction",
        "excess_resource_reduction",
        "complaint",
        "proposal_prescription_duty",
        "statutory_amendment",
    } or (
        normalized_atom.endswith("_defined")
        or normalized_atom.endswith("_definition")
    ):
        add("CEC.native")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in {
        "excess_hospital_capacity_reduction",
        "excess_resource_reduction",
        "proposal_prescription_duty",
        "program_administration",
        "statutory_amendment",
    }:
        add("deontic.ir")
        add("TDFOL.prover")

    if normalized_atom in {
        "compact_free_association",
        "credit_authority",
        "director_government_actor",
        "director_government_actor_definition",
        "export_credit_authority",
        "federal_financing_bank",
        "freely_associated_state",
        "rail_employee_status",
        "rail_employee_trust_fund",
    }:
        add("CEC.native")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in {
        "compact_free_association",
        "credit_authority",
        "export_credit_authority",
        "federal_financing_bank",
        "freely_associated_state",
        "rail_employee_status",
        "rail_employee_trust_fund",
    }:
        add("deontic.ir")
        add("TDFOL.prover")

    if normalized_atom in _PROGRAM_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _PACKET_000600_USCODE_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _PACKET_000184_USCODE_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _PACKET_000188_USCODE_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _PACKET_000189_FRAME_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _PACKET_000629_USCODE_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _PACKET_000630_USCODE_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _PACKET_000633_USCODE_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _PACKET_000819_SEMANTIC_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _ADMIN_ENFORCEMENT_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _TEMPORAL_STATUTORY_RECONSTRUCTION_ATOMS:
        add("TDFOL.prover")
        add("CEC.native")
        add("modal.frame_logic")
    if normalized_atom in {
        "codification_transition",
        "expert_consultant_service_authority",
        "fiscal_year_appropriation_availability",
        "historic_site_preservation_designation",
        "national_guard_relocation_limit",
        "national_guard_unit_status",
        "national_historic_site_designation",
        "salvage_archeology_administration",
        "salvage_fund_use_authority",
        "state_governor_consent_requirement",
        "unit_relocation_withdrawal_restriction",
    }:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _RESEARCH_ADMINISTRATION_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _PROJECT_LOAN_AWARD_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _MEASUREMENT_ASSIGNMENT_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in _WILDLIFE_STATUS_RECONSTRUCTION_ATOMS:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")

    if normalized_atom in {
        "administration_enforcement",
        "clean_hull_administration_enforcement",
        "admission_fee_collection",
        "appropriated_amount",
        "appropriated_amount_availability",
        "audit_requirement",
        "award_program",
        "board_of_directors",
        "boundary_division_fence",
        "biological_product_interstate_traffic",
        "biological_product_regulation",
        "budget_program_submission",
        "buying_power_account_maintenance",
        "accountability_responsibility",
        "agricultural_commodity_set_aside",
        "civil_action",
        "civil_action_jurisdiction",
        "civil_enforcement",
        "classified_information_procedure",
        "child_abduction_remedy",
        "commodity_set_aside",
        "commodity_value_determination",
        "congressional_budget_allocation",
        "congressional_budget_process",
        "congressional_findings_declaration",
        "consular_officer",
        "consular_officer_duty_liability",
        "consular_officer_powers_duties_liabilities",
        "competitive_award_program",
        "cost_sharing",
        "cost_sharing_credit_treatment",
        "crime_control_law_enforcement",
        "cybersecurity_information_sharing",
        "development_advice_assistance",
        "deceased_veterans_property_disposition",
        "department_business_assignment",
        "department_expenditure_authorization",
        "departmental_property_custody",
        "departmental_record_custody",
        "education_assistance_repayment",
        "expenditure_account_estimate",
        "federal_repayment_obligation",
        "export_promotion",
        "fee_collection_authority",
        "fiscal_year_budget_limitation",
        "fiscal_year_allotment",
        "forest_resource_reservation",
        "formula_grant",
        "fund_establishment_authority",
        "fund_transfer_authority",
        "funding_eligibility",
        "department_fund_administration",
        "health_insurance_reform_implementation",
        "health_insurance_reform_implementation_fund",
        "implementation_fund",
        "implementation_funding",
        "patient_protection_affordable_care_act",
        "exchange_program",
        "foreign_commercial_service",
        "foreign_relations_exchange_program",
        "friendly_foreign_relations",
        "friendly_foreign_relations_preservation",
        "foreign_service_building",
        "foreign_service",
        "false_claim_knowledge",
        "false_fraudulent_claim",
        "false_statement_penalty",
        "predictive_analytics",
        "predictive_analytics_disclosure",
        "waste_fraud_abuse_prevention",
        "scienter_requirement",
        "material_fact_representation",
        "game_bird_preserve_protection",
        "game_preserve",
        "government_claim",
        "government_publication_depository_access",
        "government_publication_purchase_authority",
        "government_property_marking",
        "government_shipment_loss_prevention",
        "governing_body",
        "health_professional_education_assistance",
        "congregate_services_program",
        "historic_area",
        "historic_area_access_road",
        "illegal_sexual_activity",
        "illegal_sexual_activity_transport",
        "information_sharing",
        "information_technology_acquisition",
        "information_technology_management",
        "agency_certification_determination",
        "eligibility_determination",
        "homestead_entry_confirmation",
        "housing_transfer_authority",
        "internal_delivery_fee_collection",
        "interagency_coordination",
        "interinstitutional_discussion",
        "irrigation_project",
        "job_corps_program",
        "reclamation_act_authority",
        "reclamation_act_irrigation_project",
        "international_agreement_authority",
        "international_boundary_water_commission",
        "international_storage_dam_authorization",
        "judicial_sale_execution",
        "jurisdiction_authority",
        "law_enforcement",
        "legal_relationship_override",
        "liability_protection",
        "lie_detector_test",
        "lie_detector_use_prohibition",
        "employee_polygraph_protection",
        "livestock_commerce",
        "air_carrier_service_duty",
        "air_transportation_service_duty",
        "monitoring_enforcement",
        "nato_common_funded_budget_contribution",
        "monument_memorial_administration",
        "management_position_assignment",
        "naval_officer_management_assignment",
        "officer_promotion",
        "officer_election",
        "officer_promotion_retention",
        "officer_retention",
        "prize_proceeds_charge",
        "priority_state",
        "program_administration",
        "philippines_medical_assistance_authority",
        "professional_assessment_committee",
        "per_capita_ranking",
        "postal_mailbox",
        "postal_mailbox_destruction",
        "postal_service",
        "marshal_incapacity",
        "military_commission_procedure",
        "military_defense_counsel_duty",
        "military_trial_counsel_duty",
        "mineral_land_status",
        "mineral_leasing_law",
        "mineral_development_technology",
        "mining_law_application",
        "mining_claim",
        "territorial_jurisdiction",
        "hydraulic_mining",
        "california_debris_commission",
        "clearing_bank_resolution",
        "federal_reserve_board_oversight",
        "technology_transfer",
        "technology_transfer_assessment",
        "technology_transition_assessment",
        "natural_resource_use",
        "national_park_resource",
        "non_federal_cost_share",
        "enforcement_remedy",
        "officer_election",
        "prize_proceeds_charge",
        "remedy",
        "report_contents",
        "research_development_grant_program",
        "research_development_program",
        "public_access_requirement",
        "publication_disposal_authority",
        "congressional_precedents_distribution",
        "official_use_restriction",
        "congressional_committee_report",
        "deadline_report_duty",
        "reserve_active_status_list",
        "resource_availability",
        "related_crime",
        "settler_resource_use",
        "sovereign_debt_conversion",
        "active_status_list",
        "secretary_availability",
        "state_energy_program",
        "state_ranking",
        "statutory_short_title",
        "statutory_applicability",
        "statutory_chapter_applicability",
        "land_withdrawal_restoration_scope",
        "railroad_land_status",
        "state_court_civil_jurisdiction",
        "state_court_jurisdiction",
        "state_conveyance_authority",
        "state_allotment_amount",
        "state_allotment_duty",
        "state_formula_grant",
        "substance_abuse_treatment_program",
        "perishable_agricultural_commodity",
        "human_welfare_resource_program",
        "sustainable_chemistry_research",
        "telemedicine_distance_learning",
        "university_research_grant_program",
        "university_research_program",
        "interstate_air_transportation",
        "national_forest_resource",
        "national_seashore_recreation_area",
        "recreation_area",
        "timber_cutting",
        "timber_cutting_forest_scope",
        "timber_stone_use",
        "treasury_deposit",
        "treasury_payment_source",
        "treasury_requisition_payment",
        "unknown_party_deposit",
        "veterans_personal_property",
        "veterans_medical_care",
        "white_horse_hill_game_preserve",
        "surplus_housing_transfer",
        "workforce_development_program",
        "workforce_performance_accountability",
        "workforce_performance_reporting",
        "perishable_commodity_container_exemption",
        "nonmailable_matter_penalty",
        "workforce_investment_system",
    }:
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in {
        "codification",
        "omitted",
        "reclassified",
        "renumbered",
        "repealed",
        "reserved",
        "terminated",
        "transferred",
        "vacant",
    }:
        add("CEC.native")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in {
        "friendly_foreign_relations",
        "friendly_foreign_relations_preservation",
        "job_corps_program",
        "nonmailable_matter_penalty",
        "workforce_investment_system",
    }:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
    if normalized_atom in {
        "admission_fee_collection",
        "appropriated_amount",
        "appropriated_amount_availability",
        "appropriations_committee_duty",
        "civil_action",
        "civil_action_jurisdiction",
        "congressional_budget_allocation",
        "congressional_budget_process",
        "consular_officer_duty_liability",
        "consular_officer_powers_duties_liabilities",
        "biological_product_interstate_traffic",
        "biological_product_regulation",
        "exchange_program",
        "export_promotion",
        "fee_collection_authority",
        "fiscal_year_allotment",
        "fund_transfer_authority",
        "funding_eligibility",
        "health_insurance_reform_implementation_fund",
        "implementation_fund",
        "implementation_funding",
        "patient_protection_affordable_care_act",
        "foreign_commercial_service",
        "foreign_relations_exchange_program",
        "foreign_service_building",
        "foreign_service",
        "false_claim_knowledge",
        "false_fraudulent_claim",
        "false_statement_penalty",
        "scienter_requirement",
        "material_fact_representation",
        "cybersecurity_information_sharing",
        "child_abduction_remedy",
        "commodity_set_aside",
        "commodity_value_determination",
        "cost_sharing",
        "cost_sharing_credit_treatment",
        "deceased_veterans_property_disposition",
        "department_business_assignment",
        "department_expenditure_authorization",
        "departmental_property_custody",
        "departmental_record_custody",
        "education_assistance_repayment",
        "expenditure_account_estimate",
        "federal_repayment_obligation",
        "forest_resource_reservation",
        "government_publication_purchase_authority",
        "government_claim",
        "government_publication_depository_access",
        "government_property_marking",
        "government_shipment_loss_prevention",
        "agency_certification_determination",
        "eligibility_determination",
        "homestead_entry_confirmation",
        "housing_transfer_authority",
        "air_carrier_service_duty",
        "air_transportation_service_duty",
        "health_professional_education_assistance",
        "human_welfare_resource_program",
        "interagency_coordination",
        "illegal_sexual_activity",
        "illegal_sexual_activity_transport",
        "marine_science_development",
        "interinstitutional_discussion",
        "irrigation_project",
        "international_agreement_authority",
        "international_boundary_water_commission",
        "international_storage_dam_authorization",
        "management_position_assignment",
        "legal_relationship_override",
        "liability_protection",
        "lie_detector_test",
        "lie_detector_use_prohibition",
        "employee_polygraph_protection",
        "mineral_land_status",
        "mineral_leasing_law",
        "mining_law_application",
        "mining_claim",
        "perishable_agricultural_commodity",
        "territorial_jurisdiction",
        "hydraulic_mining",
        "california_debris_commission",
        "clearing_bank_resolution",
        "federal_reserve_board_oversight",
        "technology_transfer_assessment",
        "alternative_fuel_vehicle_program",
        "benefit_cost_information",
        "consumer_information_package",
        "environmental_performance_disclosure",
        "public_information_program",
        "military_commission_procedure",
        "military_defense_counsel_duty",
        "military_trial_counsel_duty",
        "natural_resource_use",
        "national_forest_resource",
        "national_park_resource",
        "non_federal_cost_share",
        "national_seashore_recreation_area",
        "nonirrigable_land_status",
        "permanent_nonirrigable_land_status",
        "jurisdiction_authority",
        "livestock_commerce",
        "naval_officer_management_assignment",
        "prize_proceeds_charge",
        "priority_state",
        "per_capita_ranking",
        "postal_mailbox_destruction",
        "road_conveyance",
        "reserve_active_status_list",
        "resource_availability",
        "research_development_grant_program",
        "research_development_program",
        "related_crime",
        "public_access_requirement",
        "publication_disposal_authority",
        "sea_grant_college",
        "sea_grant_college_program",
        "secretary_availability",
        "service_eligibility",
        "sovereign_debt_conversion",
        "statutory_applicability",
        "statutory_chapter_applicability",
        "settler_resource_use",
        "university_research_grant_program",
        "university_research_program",
        "sustainable_chemistry_research",
        "state_court_civil_jurisdiction",
        "state_court_jurisdiction",
        "state_energy_program",
        "state_ranking",
        "statutory_short_title",
        "state_conveyance_authority",
        "state_allotment_amount",
        "state_allotment_duty",
        "state_formula_grant",
        "substance_abuse_treatment_program",
        "surplus_housing_transfer",
        "workforce_development_program",
        "workforce_performance_accountability",
        "workforce_performance_reporting",
        "timber_cutting",
        "timber_cutting_forest_scope",
        "timber_stone_use",
        "treasury_deposit",
        "treasury_payment_source",
        "treasury_requisition_payment",
        "unknown_party_deposit",
        "joint_infrastructure_operation",
        "loss_damage_risk_mitigation",
        "mexico_bilateral_agreement",
        "regulation_prescription_authority",
        "regulatory_compliance_duty",
        "rio_grande_water_project",
        "valuable_shipment_regulation",
        "veterans_personal_property",
        "veterans_medical_care",
        "commonwealth_army_veteran_benefit",
        "philippines_veteran_assistance",
        "nato_contribution_authority",
        "nato_common_funded_budget",
        "perishable_commodity_container_exemption",
    }:
        add("CEC.native")
    if normalized_atom in {
        "office_seal",
        "official_seal",
        "absent_uniformed_services_voter",
        "border_infrastructure_modernization",
        "capitol_visitor_center",
        "certificate_production_on_entry",
        "chief_executive_officer",
        "customs_entry_documentation",
        "federal_alcohol_law_equal_treatment",
        "financial_disclosure_requirement",
        "fishery_loan_property",
        "fishery_vessel_property_disposition",
        "government_purchasing_authority",
        "overseas_voter",
        "technology_modernization",
        "trust_territory_purchasing_authority",
        "uniformed_services_voter",
        "visitor_center_assistant",
        "plant_variety_protection",
        "plant_variety_protection_office",
    }:
        add("CEC.native")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in {
        "agency_determination",
        "agency_certification_determination",
        "appropriations_committee_duty",
        "classified_information_procedure",
        "child_abduction_remedy",
        "commodity_value_determination",
        "congressional_budget_allocation",
        "congressional_budget_process",
        "congressional_findings_declaration",
        "china_relations_oversight",
        "conservation_area_management",
        "cost_expense_charge",
        "cybersecurity_information_sharing",
        "construction_no_effect",
        "deceased_veterans_property_disposition",
        "development_advice_assistance",
        "examination_cost_payment",
        "departmental_property_custody",
        "departmental_record_custody",
        "department_expenditure_authorization",
        "education_assistance_benefit",
        "education_assistance_repayment",
        "federal_repayment_obligation",
        "faculty_development",
        "false_claim_knowledge",
        "fund_use_authority",
        "former_jeopardy_protection",
        "funding_eligibility",
        "health_insurance_reform_implementation_fund",
        "implementation_fund",
        "implementation_funding",
        "patient_protection_affordable_care_act",
        "grant_contract_award",
        "grant_contract_fund_use",
        "eligibility_determination",
        "professional_assessment_committee",
        "service_eligibility",
        "information_technology_acquisition",
        "information_technology_management",
        "program_administration",
        "telemedicine_distance_learning",
        "health_professional_education_assistance",
        "biological_product_regulation",
        "foreign_relations_exchange_program",
        "foreign_service_building",
        "foreign_service",
        "internal_service_fee",
        "documentation_certificate_requirement",
        "interagency_coordination",
        "interinstitutional_discussion",
        "air_carrier_service_duty",
        "air_transportation_service_duty",
        "illegal_sexual_activity",
        "illegal_sexual_activity_transport",
        "legal_relationship_override",
        "liability_protection",
        "land_acquisition_authority",
        "land_donation_acceptance",
        "land_title_authority",
        "lie_detector_test",
        "lie_detector_use_prohibition",
        "employee_polygraph_protection",
        "monitoring_enforcement",
        "veterans_medical_care",
        "commonwealth_army_veteran_benefit",
        "philippines_veteran_assistance",
        "nato_contribution_authority",
        "nato_common_funded_budget",
        "proposal_examination_payment",
        "proposal_submission",
        "armed_forces_retirement_home",
        "retirement_home_payment",
        "management_position_assignment",
        "military_commission_procedure",
        "military_defense_counsel_duty",
        "military_trial_counsel_duty",
        "natural_resource_use",
        "natural_area_establishment",
        "national_seashore_recreation_area",
        "nonirrigable_land_status",
        "office_seal",
        "official_seal",
        "absent_uniformed_services_voter",
        "border_infrastructure_modernization",
        "capitol_visitor_center",
        "chief_executive_officer",
        "federal_alcohol_law_equal_treatment",
        "fishery_loan_property",
        "fishery_vessel_property_disposition",
        "government_purchasing_authority",
        "overseas_voter",
        "technology_modernization",
        "trust_territory_purchasing_authority",
        "uniformed_services_voter",
        "visitor_center_assistant",
        "permanent_nonirrigable_land_status",
        "perishable_agricultural_commodity",
        "plant_variety_protection",
        "plant_variety_protection_office",
        "prize_proceeds_charge",
        "priority_state",
        "per_capita_ranking",
        "related_crime",
        "settler_resource_use",
        "state_energy_program",
        "state_ranking",
        "participation_eligibility",
        "sovereign_debt_conversion",
        "trade_rule_of_law_compliance",
        "statutory_construction",
        "statutory_force_effect",
        "timber_cutting",
        "timber_cutting_forest_scope",
        "timber_stone_use",
        "treasury_deposit",
        "treasury_requisition_payment",
        "unknown_party_deposit",
        "veterans_personal_property",
        "naval_officer_management_assignment",
        "workforce_development_program",
        "workforce_performance_accountability",
        "workforce_performance_reporting",
        "perishable_commodity_container_exemption",
        "ethics_government_requirement",
        "peacetime_death_compensation",
        "vessel_entry_documentation",
    }:
        add("deontic.ir")
        add("TDFOL.prover")
    if normalized_atom in {
        "agency_determination",
        "annual_report_duty",
        "admission_fee_collection",
        "agricultural_commodity_set_aside",
        "appropriation_authorization",
        "appropriated_amount_availability",
        "appropriations_committee_duty",
        "audit_requirement",
        "award_program",
        "biological_product_interstate_traffic",
        "biological_product_regulation",
        "build_maintain_duty",
        "budget_program_submission",
        "accountability_responsibility",
        "congressional_report_duty",
        "congressional_budget_allocation",
        "congressional_budget_process",
        "china_relations_oversight",
        "classified_information_procedure",
        "conservation_area_management",
        "congressional_findings_declaration",
        "congressional_committee_report",
        "commodity_set_aside",
        "commodity_value_determination",
        "cost_sharing_credit_treatment",
        "construction_no_effect",
        "deadline_report_duty",
        "competitive_award_program",
        "cybersecurity_information_sharing",
        "definition",
        "certificate_production_on_entry",
        "customs_entry_documentation",
        "documentation_certificate_requirement",
        "deceased_veterans_property_disposition",
        "examination_cost_payment",
        "departmental_property_custody",
        "departmental_record_custody",
        "exception_or_condition",
        "exempt_operation",
        "exchange_program",
        "exemption",
        "expenditure_requirement",
        "ethics_government_requirement",
        "facility_operation",
        "faculty_development",
        "fee_collection_authority",
        "fiscal_year_allotment",
        "formula_grant",
        "fund_transfer_authority",
        "fund_use_authority",
        "financial_disclosure_requirement",
        "funding_eligibility",
        "forest_resource_reservation",
        "land_acquisition_authority",
        "land_donation_acceptance",
        "land_title_authority",
        "false_claim_knowledge",
        "false_fraudulent_claim",
        "foreign_relations_exchange_program",
        "grant_contract_award",
        "grant_contract_fund_use",
        "former_jeopardy_protection",
        "government_claim",
        "government_publication_depository_access",
        "government_publication_purchase_authority",
        "government_property_marking",
        "government_shipment_loss_prevention",
        "human_welfare_resource_program",
        "model_demonstration",
        "account_maintenance",
        "development_advice_assistance",
        "active_status_list",
        "legal_relationship_override",
        "liability_protection",
        "lie_detector_test",
        "lie_detector_use_prohibition",
        "employee_polygraph_protection",
        "judicial_sale_execution",
        "marshal_incapacity",
        "military_commission_procedure",
        "military_defense_counsel_duty",
        "military_trial_counsel_duty",
        "natural_resource_use",
        "natural_area_establishment",
        "national_seashore_recreation_area",
        "national_forest_resource",
        "national_park_resource",
        "homestead_entry_confirmation",
        "housing_transfer_authority",
        "interinstitutional_discussion",
        "mining_law_application",
        "territorial_jurisdiction",
        "hydraulic_mining",
        "california_debris_commission",
        "clearing_bank_resolution",
        "federal_reserve_board_oversight",
        "nonirrigable_land_status",
        "office_establishment",
        "office_of_womens_health",
        "absent_uniformed_services_voter",
        "border_infrastructure_modernization",
        "capitol_visitor_center",
        "chief_executive_officer",
        "federal_alcohol_law_equal_treatment",
        "fishery_loan_property",
        "fishery_vessel_property_disposition",
        "government_purchasing_authority",
        "overseas_voter",
        "technology_modernization",
        "trust_territory_purchasing_authority",
        "uniformed_services_voter",
        "visitor_center_assistant",
        "officer_promotion",
        "officer_promotion_retention",
        "officer_retention",
        "obligation",
        "patent_prohibition",
        "peacetime_death_compensation",
        "payment_authorization",
        "armed_forces_retirement_home",
        "proposal_examination_payment",
        "proposal_submission",
        "public_health_agency",
        "permanent_nonirrigable_land_status",
        "perishable_agricultural_commodity",
        "permission",
        "post_term_member_right",
        "post_term_public_document_allotment",
        "priority_state",
        "per_capita_ranking",
        "postal_mailbox_destruction",
        "prohibition",
        "public_access_requirement",
        "public_document_allotment",
        "publication_disposal_authority",
        "congressional_precedents_distribution",
        "official_use_restriction",
        "public_report_duty",
        "promotion_retention",
        "retiring_member_document_right",
        "enforcement_remedy",
        "remedy",
        "report_contents",
        "congressional_committee_report",
        "deadline_report_duty",
        "reserve_active_status_list",
        "resource_availability",
        "research_activity",
        "research_development_grant_program",
        "research_development_program",
        "research_grant",
        "report_duty",
        "retirement_home_payment",
        "road_conveyance",
        "state_allotment_duty",
        "state_formula_grant",
        "secretary_availability",
        "civil_penalty_liability",
        "sovereign_debt_conversion",
        "sea_grant_college_program",
        "settler_resource_use",
        "state_energy_program",
        "state_ranking",
        "statutory_short_title",
        "study_report_duty",
        "submit_or_file",
        "technology_transfer_assessment",
        "technology_transition_assessment",
        "trade_rule_of_law_compliance",
        "alternative_fuel_vehicle_program",
        "benefit_cost_information",
        "consumer_information_package",
        "environmental_performance_disclosure",
        "public_information_program",
        "test_platform",
        "university_research_grant_program",
        "university_research_program",
        "undocumented_trading_penalty",
        "timber_cutting",
        "timber_cutting_forest_scope",
        "timber_stone_use",
        "surplus_housing_transfer",
        "joint_infrastructure_operation",
        "loss_damage_risk_mitigation",
        "regulation_prescription_authority",
        "regulatory_compliance_duty",
        "valuable_shipment_regulation",
        "perishable_commodity_container_exemption",
        "veterans_personal_property",
        "vessel_entry_documentation",
        "special_adapted_housing_assistance",
    }:
        add("deontic.ir")
        add("TDFOL.prover")
    if normalized_atom in {
        "exempt_operation",
        "exemption",
        "facility_operation",
        "perishable_agricultural_commodity",
        "test_platform",
        "perishable_commodity_container_exemption",
    }:
        add("CEC.native")
        add("modal.frame_logic")
    if normalized_atom in {
        "agency_determination",
        "agency_certification_determination",
        "congressional_findings_declaration",
        "definition",
        "development_advice_assistance",
        "ethics_government_requirement",
        "eligibility_determination",
        "deceased_veterans_property_disposition",
        "departmental_property_custody",
        "departmental_record_custody",
        "china_relations_oversight",
        "conservation_area_management",
        "former_jeopardy_protection",
        "monitoring_enforcement",
        "military_commission_procedure",
        "military_defense_counsel_duty",
        "military_trial_counsel_duty",
        "interinstitutional_discussion",
        "nonirrigable_land_status",
        "office_establishment",
        "office_of_womens_health",
        "peacetime_death_compensation",
        "public_health_agency",
        "priority_state",
        "homestead_entry_confirmation",
        "land_acquisition_authority",
        "land_donation_acceptance",
        "land_title_authority",
        "land_withdrawal_restoration_scope",
        "natural_area_establishment",
        "national_seashore_recreation_area",
        "permanent_nonirrigable_land_status",
        "railroad_land_status",
        "state_energy_program",
        "state_ranking",
        "sovereign_debt_conversion",
        "trade_rule_of_law_compliance",
        "statutory_construction",
        "statutory_force_effect",
        "trainee_support",
        "training_program_support",
        "technology_transfer_assessment",
        "technology_transition_assessment",
        "federal_reserve_board_oversight",
        "interagency_coordination",
        "alternative_fuel_vehicle_program",
        "consumer_information_package",
        "environmental_performance_disclosure",
        "international_agreement_authority",
        "international_boundary_water_commission",
        "international_storage_dam_authorization",
        "joint_infrastructure_operation",
        "mexico_bilateral_agreement",
        "public_information_program",
        "rio_grande_water_project",
        "armed_forces_retirement_home",
        "proposal_submission",
        "proposal_examination_payment",
        "public_health_agency",
        "retirement_home_payment",
        "professional_assessment_committee",
        "service_eligibility",
        "civil_penalty_liability",
        "penalty_value_multiplier",
        "statutory_violation_condition",
        "special_adapted_housing_assistance",
        "supplemental_authorization_policy",
    }:
        add("CEC.native")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in {
        "annual_report",
        "annual_report_duty",
        "active_status_list",
        "agricultural_commodity_set_aside",
        "appropriation_authorization",
        "congressional_budget_allocation",
        "budget_program_submission",
        "congressional_committee_report",
        "commodity_set_aside",
        "commodity_value_determination",
        "deadline_report_duty",
        "fiscal_year_allotment",
        "mineral_development_technology",
        "date_range_temporal_scope",
        "fund_transfer_authority",
        "conservation_area_management",
        "funding_eligibility",
        "health_insurance_reform_implementation_fund",
        "implementation_fund",
        "implementation_funding",
        "patient_protection_affordable_care_act",
        "land_acquisition_authority",
        "land_donation_acceptance",
        "land_title_authority",
        "marine_science_development",
        "mineral_land_status",
        "mineral_leasing_law",
        "mining_claim",
        "natural_resource_use",
        "natural_area_establishment",
        "national_seashore_recreation_area",
        "national_forest_resource",
        "sea_grant_college",
        "sea_grant_college_program",
        "no_year_funding_availability",
        "post_term_member_right",
        "post_term_public_document_allotment",
        "public_document_allotment",
        "reserve_active_status_list",
        "retiring_member_document_right",
        "resource_availability",
        "per_capita_ranking",
        "research_activity",
        "research_grant",
        "state_allotment_amount",
        "settler_resource_use",
        "study_report_duty",
        "technology_transfer_assessment",
        "technology_transition_assessment",
        "trade_rule_of_law_compliance",
        "termination_authority",
        "temporal_condition",
        "state_ranking",
        "alternative_fuel_vehicle_program",
        "consumer_information_package",
        "government_shipment_loss_prevention",
        "international_storage_dam_authorization",
        "joint_infrastructure_operation",
        "public_information_program",
        "federal_building_energy_standard",
        "federal_compliance_duty",
        "regulation_prescription_authority",
        "regulatory_compliance_duty",
        "timber_cutting",
        "timber_cutting_forest_scope",
        "timber_stone_use",
        "valuable_shipment_regulation",
        "veterans_medical_care",
        "special_adapted_housing_assistance",
        "supplemental_authorization_policy",
        "commonwealth_army_veteran_benefit",
        "philippines_veteran_assistance",
        "nato_contribution_authority",
        "nato_common_funded_budget",
    }:
        add("TDFOL.prover")
    if normalized_atom in {
        "appeal_bail_rule",
        "education_assistance_program",
        "federal_assistance_administration",
        "federal_payment_formula",
        "income_gap_multiplier",
        "international_space_station",
        "iss_research_utilization",
        "naval_facility_expansion",
        "public_health_surveillance",
        "science_engineering_education_program",
        "space_science_research",
        "seaman_discharge",
        "smart_manufacturing_report",
        "wage_account_discharge",
    }:
        add("deontic.ir")
        add("TDFOL.prover")
        add("CEC.native")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in {
        "advisory_committee",
        "advisory_committee_appointment",
        "appointment_authority",
        "implementation_action_report",
        "museum_board_regents",
        "museum_board_trustees",
        "museum_collection_custody",
        "national_museum_american_indian",
    }:
        add("CEC.native")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in {
        "advisory_committee_appointment",
        "appointment_authority",
        "implementation_action_report",
        "museum_collection_custody",
    }:
        add("deontic.ir")
        add("TDFOL.prover")
    if normalized_atom in {
        "benefit_claim_adjudication",
        "bill_lading_indorsement_negotiation",
        "bill_of_lading",
        "black_lung_benefit_claim",
        "black_lung_benefits",
        "integrated_agency_procedure",
        "mine_safety_health",
        "negotiable_bill_of_lading",
        "order_document_delivery",
        "securities_exchange_commission",
        "securities_trust_indenture",
        "securities_trust_indenture_procedure",
    }:
        add("CEC.native")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in {
        "benefit_claim_adjudication",
        "bill_lading_indorsement_negotiation",
        "black_lung_benefit_claim",
        "black_lung_benefits",
        "integrated_agency_procedure",
        "negotiable_bill_of_lading",
        "order_document_delivery",
        "securities_trust_indenture_procedure",
    }:
        add("deontic.ir")
        add("TDFOL.prover")
    if normalized_atom in {
        "benefit_claim_adjudication",
        "black_lung_benefit_claim",
        "black_lung_benefits",
        "integrated_agency_procedure",
        "securities_trust_indenture_procedure",
    }:
        add("TDFOL.prover")
    if normalized_atom in {
        "clean_hull_administration_enforcement",
        "federal_building_energy_standard",
        "federal_compliance_duty",
        "active_measures_notification",
        "active_measures_campaign",
        "congressional_intelligence_committee",
        "federal_building_compliance",
        "federal_building_energy_standard",
        "federal_compliance_requirement",
        "fiscal_year_budget_limitation",
        "internal_delivery_fee_collection",
        "nato_common_funded_budget_contribution",
        "philippines_medical_assistance_authority",
        "procedure_adoption_duty",
        "veterans_medical_care",
        "public_facility_use",
        "government_facility_use",
        "foreign_government_facility_use",
    }:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in {
        "implementation_noninterference",
        "legal_relationship_noninterference",
        "personal_property_disposition",
        "property_delivery_duty",
        "public_safety_broadband_network",
    }:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in {
        "chapter_administration",
        "architect_capitol_administration",
        "cargo_carriage",
        "common_carrier",
        "common_carrier_cargo_carriage",
        "construction_contract",
        "contracting_authority",
        "cooperative_agreement_authority",
        "deaf_blind_services_registry",
        "developing_institution_program",
        "fund_transfer_authority",
        "helen_keller_national_center_registry",
        "higher_education_student_assistance",
        "rental_rate_authority",
        "reserved_land",
        "reserved_land_lease_authority",
        "revenue_disposition",
        "service_contract",
        "service_contract_suspension",
        "suspended_tariff_operation",
        "suspended_tariff_service_contract",
        "suspended_tariff_service_contract_penalty",
        "tariff_suspension",
        "uscode_registry_record",
    }:
        add("CEC.native")
        add("deontic.ir")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if normalized_atom in {
        "cargo_carriage",
        "common_carrier_cargo_carriage",
        "construction_contract",
        "contracting_authority",
        "cooperative_agreement_authority",
        "fund_transfer_authority",
        "rental_rate_authority",
        "reserved_land_lease_authority",
        "revenue_disposition",
        "service_contract_suspension",
        "suspended_tariff_operation",
        "suspended_tariff_service_contract",
        "suspended_tariff_service_contract_penalty",
        "tariff_suspension",
    }:
        add("TDFOL.prover")
    if normalized_atom in {
        "comptroller_general_audit",
        "deposit_nontaxation",
        "deposit_tax_treatment",
        "design_patent_protection",
        "flood_insurance_program",
        "independent_living_center",
        "independent_living_services",
        "internal_revenue_code",
        "policy_condition_exclusion_disclosure",
        "policy_disclosure_requirement",
        "rehabilitation_services",
        "tax_exemption",
        "tax_treatment",
        "taxable_income_determination",
        "vocational_rehabilitation_services",
        "colorado_river_floodway_report",
        "admission_fee_collection",
        "everglades_national_park",
        "fee_limitation",
        "federal_full_faith_credit_security",
        "federal_security_pledge",
        "generation_skipping_transfer_tax",
        "low_income_housing_project",
        "national_park_resource",
        "obligation_contestability",
        "public_housing_agency",
        "public_housing_agency_obligation",
        "secretary_recommendation_report",
        "tax_computation_rule",
        "taxable_amount_determination",
        "adverse_action_procedure",
        "employee_adverse_action",
        "employee_notice_period",
        "government_agency_equipment_transfer",
        "government_printing_equipment",
        "program_payment_authority",
        "rural_development_grant_program",
        "secretary_payment_adjustment",
        "administrative_coordination_duty",
        "flood_map_certification",
        "flood_mapping_program",
        "labor_dispute_injunction",
        "national_emergency_labor_dispute",
        "national_strategic_uranium_reserve",
        "reserve_establishment_authority",
        "special_adapted_housing_coordination",
        "technical_mapping_advisory_review",
        "uranium_reserve_resource",
        "uscode_omitted_codification_record",
        "uscode_repealed_editorial_record",
        *_PACKET_000626_USCODE_RECONSTRUCTION_ATOMS,
        *_PACKET_000627_USCODE_RECONSTRUCTION_ATOMS,
        *_PACKET_000630_USCODE_RECONSTRUCTION_ATOMS,
        *_PACKET_000633_USCODE_RECONSTRUCTION_ATOMS,
    }:
        add("CEC.native")
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    return views


def _typed_decompiler_semantic_atom_target_families(
    semantic_atoms: Sequence[str],
) -> List[str]:
    targets: List[str] = []

    def add(target: str) -> None:
        if target and target not in targets:
            targets.append(target)

    for atom in semantic_atoms:
        normalized_atom = _clean_text(atom).lower()
        if normalized_atom in {
            "friendly_foreign_relations",
            "friendly_foreign_relations_preservation",
            "job_corps_program",
            "nonmailable_matter_penalty",
            "workforce_investment_system",
        }:
            add("deontic")
            add("frame")
            add("conditional_normative")
        if normalized_atom in {
            "friendly_foreign_relations",
            "friendly_foreign_relations_preservation",
            "job_corps_program",
            "workforce_investment_system",
        }:
            add("temporal")
        if normalized_atom in {
            "department_office_seal",
            "excise_tax",
            "foreign_service_grievance",
            "former_employee_grievance",
            "judicial_notice",
            "manufacturers_excise_tax",
            "recreational_equipment_tax",
            "statutory_severability",
        }:
            add("deontic")
            add("conditional_normative")
            add("frame")
        if normalized_atom in {
            "excise_tax",
            "former_employee_grievance",
            "manufacturers_excise_tax",
            "recreational_equipment_tax",
            "statutory_severability",
        }:
            add("temporal")
        if normalized_atom in {
            "department_office_seal",
            "foreign_service_grievance",
            "former_employee_grievance",
            "judicial_notice",
        }:
            add("epistemic")
        if normalized_atom in {
            "comptroller_general_audit",
            "deposit_nontaxation",
            "deposit_tax_treatment",
            "design_patent_protection",
            "flood_insurance_program",
            "generation_skipping_transfer_tax",
            "independent_living_center",
            "independent_living_services",
            "internal_revenue_code",
            "policy_condition_exclusion_disclosure",
            "policy_disclosure_requirement",
            "rehabilitation_services",
            "tax_exemption",
            "tax_treatment",
            "tax_computation_rule",
            "taxable_amount_determination",
            "taxable_income_determination",
            "vocational_rehabilitation_services",
            "admission_fee_collection",
            "everglades_national_park",
            "fee_limitation",
            "federal_full_faith_credit_security",
            "federal_security_pledge",
            "low_income_housing_project",
            "national_park_resource",
            "obligation_contestability",
            "public_housing_agency",
            "public_housing_agency_obligation",
        }:
            add("deontic")
            add("conditional_normative")
            add("frame")
        if normalized_atom in {
            "comptroller_general_audit",
            "deposit_nontaxation",
            "deposit_tax_treatment",
            "independent_living_center",
            "independent_living_services",
            "internal_revenue_code",
            "rehabilitation_services",
            "tax_exemption",
            "tax_treatment",
            "tax_computation_rule",
            "taxable_amount_determination",
            "taxable_income_determination",
            "vocational_rehabilitation_services",
            "admission_fee_collection",
            "fee_limitation",
            "federal_security_pledge",
            "low_income_housing_project",
            "public_housing_agency_obligation",
        }:
            add("temporal")
        if normalized_atom in {
            "comptroller_general_audit",
            "design_patent_protection",
            "flood_insurance_program",
            "policy_condition_exclusion_disclosure",
            "policy_disclosure_requirement",
        }:
            add("epistemic")
        if normalized_atom in _PROGRAM_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
            add("epistemic")
        if normalized_atom in _PACKET_000600_USCODE_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in _PACKET_000901_USCODE_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in _PACKET_000184_USCODE_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in _PACKET_000188_USCODE_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in _PACKET_000189_FRAME_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in _PACKET_000190_USCODE_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in _PACKET_000626_USCODE_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in _PACKET_000627_USCODE_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in _PACKET_000629_USCODE_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in _PACKET_000630_USCODE_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in _PACKET_000633_USCODE_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in {
            "congressional_member_compensation_allowance",
            "national_military_park_resource",
            "national_security_act_reclassification",
            "uscode_appropriation_authorization_record",
        }:
            add("temporal")
        if normalized_atom in {
            "congressional_member_compensation_allowance",
            "national_security_act_reclassification",
            "uscode_capitol_visitor_center_administration",
        }:
            add("epistemic")
        if normalized_atom in {
            "administrative_coordination_duty",
            "flood_map_certification",
            "flood_mapping_program",
            "labor_dispute_injunction",
            "national_emergency_labor_dispute",
            "technical_mapping_advisory_review",
            "uranium_reserve_resource",
            "uscode_omitted_codification_record",
            "uscode_repealed_editorial_record",
        }:
            add("temporal")
        if normalized_atom in {
            "flood_map_certification",
            "technical_mapping_advisory_review",
            "uscode_omitted_codification_record",
            "uscode_repealed_editorial_record",
        }:
            add("epistemic")
        if normalized_atom in {
            "cuyahoga_valley_national_park_status",
            "uscode_voting_elections_reclassification",
        }:
            add("temporal")
        if normalized_atom in {
            "army_officer_school_detail",
            "marine_corps_medical_officer",
            "marine_corps_headquarters_staff",
            "military_post_school_use",
            "public_housing_agency_assistance",
            "wildlife_conservation_order",
        }:
            add("temporal")
        if normalized_atom in {
            "agreement_military_park_authority",
            "cumulative_remedy_preservation",
            "public_corporation_agreement_authority",
            "remedies_as_cumulative",
            "service_connected_disability_compensation",
            "veterans_compensation_benefit",
        }:
            add("temporal")
        if normalized_atom in _PACKET_000819_SEMANTIC_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in {
            "additional_distribution",
            "board_civil_action_authority",
            "board_enforcement_authority",
            "code_supplement_distribution",
            "district_columbia_code_supplement",
            "rail_carrier_injunction",
            "rail_carrier_violation_enforcement",
            "transportation_order_certificate_enforcement",
            "united_states_code_supplement",
        }:
            add("epistemic")
        if normalized_atom in {
            "code_supplement_distribution",
            "congressional_report_duty",
            "juvenile_delinquency_prevention",
            "juvenile_justice_program",
            "juvenile_justice_system_improvement",
            "justice_system_improvement",
            "nutrition_monitoring_program",
            "state_water_pollution_revolving_fund",
            "treatment_works_construction_assistance",
            "water_pollution_control_program",
            "water_pollution_control_revolving_fund",
            "water_quality_management_program",
            "wetlands_conservation_program",
        }:
            add("temporal")
        if normalized_atom in {
            "program_payment_authority",
            "rural_development_grant_program",
            "secretary_payment_adjustment",
        }:
            add("temporal")
        if normalized_atom in {
            "crisis_counseling_assistance",
            "crisis_counseling_training",
            "disaster_mental_health_service",
            "ready_reserve_muster_duty",
            "reserve_muster_authority",
            "student_assignment_transportation",
            "student_transportation_assignment",
        }:
            add("temporal")
        if normalized_atom in {
            "economic_development_trade_benefit",
            "federal_reclamation_project_advance",
            "government_project_completion_advance",
            "laborer_mechanic_wage_standard",
            "missing_children_advisory_board",
            "project_safe_neighborhoods_grant",
            "public_building_work_contract",
            "service_connected_disability_compensation",
            "sub_saharan_africa_trade_benefit",
            "veterans_compensation_benefit",
        }:
            add("temporal")
        if normalized_atom in {
            "crime_control_enforcement_program",
            "laborer_mechanic_wage_standard",
            "missing_children_advisory_board",
            "project_safe_neighborhoods_grant",
            "public_building_work_contract",
        }:
            add("epistemic")
        if normalized_atom in {
            "adverse_action_procedure",
            "employee_notice_period",
        }:
            add("temporal")
        if normalized_atom in {
            "annual_assessment_report",
            "biennial_assessment_report",
            "congressional_report_duty",
            "migratory_bird_conservation",
            "wetlands_conservation_project",
        }:
            add("epistemic")
        if normalized_atom in _ADMIN_ENFORCEMENT_RECONSTRUCTION_ATOMS:
            add("deontic")
            add("frame")
            add("conditional_normative")
        if normalized_atom in _TEMPORAL_STATUTORY_RECONSTRUCTION_ATOMS:
            add("temporal")
            add("frame")
        if normalized_atom in _RESEARCH_ADMINISTRATION_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
            add("temporal")
            add("epistemic")
        if normalized_atom in _PROJECT_LOAN_AWARD_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in _MEASUREMENT_ASSIGNMENT_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
            add("temporal")
        if normalized_atom in _WILDLIFE_STATUS_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
            add("temporal")
        if normalized_atom in _CATALOG_CONTRACT_RECONSTRUCTION_ATOMS:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in {
            "service_contract_suspension",
            "suspended_tariff_operation",
            "suspended_tariff_service_contract",
            "suspended_tariff_service_contract_penalty",
            "tariff_suspension",
        }:
            add("temporal")
        if normalized_atom in {
            "expert_consultant_service_authority",
            "historic_site_preservation_designation",
            "national_guard_relocation_limit",
            "national_guard_unit_status",
            "national_historic_site_designation",
            "salvage_archeology_administration",
            "salvage_fund_use_authority",
            "state_governor_consent_requirement",
            "unit_relocation_withdrawal_restriction",
        }:
            add("frame")
            add("deontic")
            add("conditional_normative")
        if normalized_atom in {
            "codification_transition",
            "fiscal_year_appropriation_availability",
            "national_guard_relocation_limit",
            "unit_relocation_withdrawal_restriction",
        }:
            add("temporal")
            add("frame")
        if normalized_atom in {
            "judicial_review",
            "presidential_action",
            "presidential_action_judicial_review",
            "presidential_order",
            "receiver_appointment",
            "receiver_duty",
            "receivership_administration",
            "renewable_energy_barrier_study",
            "renewable_energy_project",
            "renewable_energy_tax_rate_treatment",
            "utility_ratemaking_procedure",
        }:
            add("deontic")
            add("conditional_normative")
            add("frame")
        if normalized_atom in {
            "judicial_review",
            "presidential_action",
            "presidential_action_judicial_review",
            "presidential_order",
        }:
            add("temporal")
            add("epistemic")
        if normalized_atom in {
            "renewable_energy_barrier_study",
            "renewable_energy_project",
            "renewable_energy_tax_rate_treatment",
            "utility_ratemaking_procedure",
        }:
            add("temporal")
        if normalized_atom in {
            "excess_hospital_capacity_reduction",
            "excess_resource_reduction",
            "proposal_prescription_duty",
            "program_administration",
            "statutory_amendment",
        } or normalized_atom.endswith("_definition"):
            add("deontic")
            add("conditional_normative")
        if normalized_atom in {
            "excess_hospital_capacity",
            "excess_hospital_capacity_reduction",
            "excess_resource_reduction",
            "complaint",
            "congressional_report_duty",
            "inventory_study_report",
            "report_contents",
            "report_duty",
            "study_report_duty",
            "uranium_inventory_study",
            "statutory_amendment",
        } or (
            normalized_atom.endswith("_defined")
            or normalized_atom.endswith("_definition")
        ):
            add("frame")
        if normalized_atom in {
            "active_status_list",
            "affordable_housing_supply",
            "annual_report_duty",
            "admission_fee_collection",
            "account_maintenance",
            "buying_power_account_maintenance",
            "accountability_responsibility",
            "audit_requirement",
            "award_program",
            "appropriated_amount",
            "appropriated_amount_availability",
            "biological_product_regulation",
            "build_maintain_duty",
            "budget_program_submission",
            "carbon_capture_research",
            "active_measures_notification",
            "child_abduction_remedy",
            "china_relations_oversight",
            "classified_information_procedure",
            "commodity_set_aside",
            "commodity_value_determination",
            "conservation_area_management",
            "congregate_services_program",
            "congressional_budget_allocation",
            "congressional_budget_process",
            "congressional_precedents_distribution",
            "congressional_report_duty",
            "consular_officer_duty_liability",
            "consular_officer_powers_duties_liabilities",
            "cybersecurity_information_sharing",
            "definition",
            "certificate_production_on_entry",
            "customs_entry_documentation",
            "documentation_certificate_requirement",
            "deceased_veterans_property_disposition",
            "clean_hull_administration_enforcement",
            "examination_cost_payment",
            "development_advice_assistance",
            "department_business_assignment",
            "department_expenditure_authorization",
            "departmental_property_custody",
            "departmental_record_custody",
            "education_assistance_repayment",
            "exempt_operation",
            "exchange_program",
            "exemption",
            "expenditure_account_estimate",
            "expenditure_requirement",
            "ethics_government_requirement",
            "federal_building_energy_standard",
            "federal_compliance_duty",
            "federal_building_compliance",
            "federal_building_energy_standard",
            "federal_compliance_requirement",
            "federal_repayment_obligation",
            "facility_operation",
            "fee_collection_authority",
            "fiscal_year_budget_limitation",
            "faculty_development",
            "fiscal_year_allotment",
            "forest_resource_reservation",
            "formula_grant",
            "false_claim_knowledge",
            "false_fraudulent_claim",
            "false_statement_penalty",
            "civil_penalty_liability",
            "penalty_value_multiplier",
            "statutory_violation_condition",
            "foreign_commercial_service",
            "foreign_service",
            "foreign_relations_exchange_program",
            "financial_disclosure_requirement",
            "fund_use_authority",
            "grant_contract_award",
            "grant_contract_fund_use",
            "former_jeopardy_protection",
            "government_claim",
            "government_publication_depository_access",
            "government_publication_purchase_authority",
            "government_property_marking",
            "government_shipment_loss_prevention",
            "fund_establishment_authority",
            "funding_eligibility",
            "department_fund_administration",
            "health_insurance_reform_implementation",
            "health_insurance_reform_implementation_fund",
            "implementation_fund",
            "implementation_funding",
            "patient_protection_affordable_care_act",
            "information_technology_acquisition",
            "information_technology_management",
            "service_eligibility",
            "telemedicine_distance_learning",
            "state_allotment_amount",
            "state_allotment_duty",
            "state_formula_grant",
            "substance_abuse_treatment_program",
            "human_welfare_resource_program",
            "inventory_study_report",
            "air_carrier_service_duty",
            "air_transportation_service_duty",
            "illegal_sexual_activity",
            "illegal_sexual_activity_transport",
            "predictive_analytics",
            "predictive_analytics_disclosure",
            "waste_fraud_abuse_prevention",
            "housing_family_service_investment",
            "housing_investment_authority",
            "housing_transfer_authority",
            "internal_delivery_fee_collection",
            "interagency_coordination",
            "agency_certification_determination",
            "agency_determination",
            "land_acquisition_authority",
            "land_donation_acceptance",
            "land_title_authority",
            "legal_relationship_override",
            "liability_protection",
            "lie_detector_test",
            "lie_detector_use_prohibition",
            "employee_polygraph_protection",
            "military_commission_procedure",
            "military_defense_counsel_duty",
            "military_trial_counsel_duty",
            "mining_law_application",
            "management_position_assignment",
            "clearing_bank_resolution",
            "congressional_committee_report",
            "deadline_report_duty",
            "federal_reserve_board_oversight",
            "material_fact_representation",
            "natural_resource_use",
            "natural_area_establishment",
            "national_seashore_recreation_area",
            "national_forest_resource",
            "national_park_resource",
            "reclamation_act_authority",
            "reclamation_act_irrigation_project",
            "office_establishment",
            "office_of_womens_health",
            "absent_uniformed_services_voter",
            "border_infrastructure_modernization",
            "capitol_visitor_center",
            "chief_executive_officer",
            "federal_alcohol_law_equal_treatment",
            "fishery_loan_property",
            "fishery_vessel_property_disposition",
            "government_purchasing_authority",
            "overseas_voter",
            "technology_modernization",
            "trust_territory_purchasing_authority",
            "uniformed_services_voter",
            "visitor_center_assistant",
            "officer_promotion",
            "officer_promotion_retention",
            "officer_retention",
            "program_administration",
            "naval_officer_management_assignment",
            "nato_common_funded_budget_contribution",
            "obligation",
            "permanent_nonirrigable_land_status",
            "patent_prohibition",
            "perishable_agricultural_commodity",
            "payment_authorization",
            "philippines_medical_assistance_authority",
            "armed_forces_retirement_home",
            "public_facility_use",
            "government_facility_use",
            "foreign_government_facility_use",
            "procedure_adoption_duty",
            "proposal_examination_payment",
            "proposal_submission",
            "public_health_agency",
            "priority_state",
            "open_market_paper_purchase",
            "postal_mailbox_destruction",
            "public_access_requirement",
            "public_information_program",
            "publication_disposal_authority",
            "official_use_restriction",
            "permission",
            "post_term_member_right",
            "post_term_public_document_allotment",
            "per_capita_ranking",
            "interinstitutional_discussion",
            "partnership",
            "partnership_adjustment_notice",
            "prohibition",
            "promotion_retention",
            "public_document_allotment",
            "public_report_duty",
            "reserve_active_status_list",
            "resource_availability",
            "related_crime",
            "research_activity",
            "research_development_grant_program",
            "research_development_program",
            "research_grant",
            "report_contents",
            "retiring_member_document_right",
            "report_duty",
            "retirement_home_payment",
            "road_conveyance",
            "participation_eligibility",
            "scienter_requirement",
            "sea_grant_college_program",
            "secretary_availability",
            "statutory_force_effect",
            "state_energy_program",
            "state_ranking",
            "statutory_short_title",
            "statutory_construction",
            "statutory_applicability",
            "statutory_chapter_applicability",
            "supplemental_authorization_policy",
            "homestead_entry_confirmation",
            "irrigation_project",
            "settler_resource_use",
            "study_report_duty",
            "submit_or_file",
            "state_conveyance_authority",
            "congregate_services_program",
            "sovereign_debt_conversion",
            "cost_sharing",
            "cost_sharing_credit_treatment",
            "technology_transfer_assessment",
            "trade_rule_of_law_compliance",
            "alternative_fuel_vehicle_program",
            "benefit_cost_information",
            "consumer_information_package",
            "environmental_performance_disclosure",
            "treasury_payment_source",
            "treasury_requisition_payment",
            "test_platform",
            "undocumented_trading_penalty",
            "trainee_support",
            "test_platform",
            "training_program_support",
            "perishable_commodity_container_exemption",
            "surplus_housing_transfer",
            "timber_cutting",
            "timber_cutting_forest_scope",
            "timber_stone_use",
            "international_agreement_authority",
            "international_storage_dam_authorization",
            "joint_infrastructure_operation",
            "loss_damage_risk_mitigation",
            "regulation_prescription_authority",
            "regulatory_compliance_duty",
            "valuable_shipment_regulation",
            "veterans_medical_care",
            "veterans_personal_property",
            "veterans_medical_care",
            "special_adapted_housing_assistance",
            "commonwealth_army_veteran_benefit",
            "philippines_veteran_assistance",
            "nato_contribution_authority",
            "nato_common_funded_budget",
            "workforce_development_program",
            "workforce_performance_accountability",
            "workforce_performance_reporting",
            "predictive_analytics",
            "predictive_analytics_disclosure",
            "waste_fraud_abuse_prevention",
        }:
            add("deontic")
        if normalized_atom in {
            "annual_report",
            "annual_report_duty",
            "active_measures_notification",
            "active_measures_campaign",
            "active_status_list",
            "agricultural_commodity_set_aside",
            "appropriation_authorization",
            "appropriated_amount_availability",
            "affordable_housing_supply",
            "biological_product_interstate_traffic",
            "budget_program_submission",
            "carbon_capture_research",
            "certificate_production_on_entry",
            "congressional_budget_allocation",
            "congressional_committee_report",
            "congressional_intelligence_committee",
            "commodity_set_aside",
            "commodity_value_determination",
            "conservation_area_management",
            "deadline_report_duty",
            "examination_cost_payment",
            "proposal_examination_payment",
            "federal_building_energy_standard",
            "federal_compliance_duty",
            "fiscal_year_budget_limitation",
            "fiscal_year_allotment",
            "federal_building_compliance",
            "federal_building_energy_standard",
            "federal_compliance_requirement",
            "housing_family_service_investment",
            "homestead_entry_confirmation",
            "irrigation_project",
            "land_withdrawal_restoration_scope",
            "long_term_housing_supply",
            "exchange_program",
            "foreign_relations_exchange_program",
            "marine_science_development",
            "mineral_development_technology",
            "land_donation_acceptance",
            "land_acquisition_authority",
            "monument_memorial_administration",
            "natural_resource_use",
            "natural_area_establishment",
            "national_seashore_recreation_area",
            "national_forest_resource",
            "national_park_resource",
            "national_seashore_recreation_area",
            "no_year_funding_availability",
            "nato_common_funded_budget",
            "nato_contribution_authority",
            "nato_common_funded_budget_contribution",
            "open_market_paper_purchase",
            "peacetime_death_compensation",
            "post_term_member_right",
            "post_term_public_document_allotment",
            "public_document_allotment",
            "border_infrastructure_modernization",
            "fishery_loan_property",
            "fishery_vessel_property_disposition",
            "government_purchasing_authority",
            "technology_modernization",
            "trust_territory_purchasing_authority",
            "reserve_active_status_list",
            "retiring_member_document_right",
            "resource_availability",
            "retirement_home_payment",
            "public_facility_use",
            "government_facility_use",
            "foreign_government_facility_use",
            "research_activity",
            "research_development_grant_program",
            "research_development_program",
            "research_grant",
            "state_allotment_amount",
            "sea_grant_college",
            "sea_grant_college_program",
            "sovereign_debt_conversion",
            "study_report_duty",
            "technology_transfer_assessment",
            "technology_transition_assessment",
            "trade_rule_of_law_compliance",
            "alternative_fuel_vehicle_program",
            "consumer_information_package",
            "international_storage_dam_authorization",
            "joint_infrastructure_operation",
            "public_information_program",
            "procedure_adoption_duty",
            "regulation_prescription_authority",
            "regulatory_compliance_duty",
            "termination_authority",
            "temporal_condition",
            "information_technology_acquisition",
            "information_technology_management",
            "program_administration",
            "telemedicine_distance_learning",
            "vessel_entry_documentation",
            "workforce_performance_accountability",
            "workforce_performance_reporting",
            "statutory_short_title",
            "timber_cutting",
            "timber_cutting_forest_scope",
        }:
            add("temporal")
        if normalized_atom in {
            "account_maintenance",
            "administration_enforcement",
            "active_measures_notification",
            "active_measures_campaign",
            "clean_hull_administration_enforcement",
            "admission_fee_collection",
            "agricultural_commodity_set_aside",
            "audit_requirement",
            "award_program",
            "board_of_directors",
            "boundary_division_fence",
            "biological_product_interstate_traffic",
            "biological_product_regulation",
            "budget_program_submission",
            "buying_power_account_maintenance",
            "accountability_responsibility",
            "civil_action",
            "civil_action_jurisdiction",
            "civil_enforcement",
            "child_abduction_remedy",
            "china_relations_oversight",
            "classified_information_procedure",
            "commodity_set_aside",
            "commodity_value_determination",
            "congressional_budget_allocation",
            "congressional_budget_process",
            "congressional_committee_report",
            "congressional_intelligence_committee",
            "consultation",
            "consultation_cooperation",
            "congressional_findings_declaration",
            "consular_officer",
            "consular_officer_duty_liability",
            "consular_officer_powers_duties_liabilities",
            "competitive_award_program",
            "conservation_area_management",
            "crime_control_law_enforcement",
            "cybersecurity_information_sharing",
            "definition",
            "documentation_certificate_requirement",
            "deceased_veterans_property_disposition",
            "armed_forces_retirement_home",
            "development_advice_assistance",
            "department_business_assignment",
            "department_expenditure_authorization",
            "departmental_property_custody",
            "departmental_record_custody",
            "education_assistance_repayment",
            "export_promotion",
            "exempt_operation",
            "expenditure_account_estimate",
            "exchange_program",
            "facility_operation",
            "faculty_development",
            "federal_building_compliance",
            "federal_building_energy_standard",
            "federal_compliance_requirement",
            "fee_collection_authority",
            "federal_building_energy_standard",
            "federal_compliance_duty",
            "federal_repayment_obligation",
            "proposal_submission",
            "forest_resource_reservation",
            "formula_grant",
            "fund_transfer_authority",
            "fund_use_authority",
            "foreign_commercial_service",
            "foreign_relations_exchange_program",
            "foreign_service_building",
            "foreign_service",
            "false_claim_knowledge",
            "false_fraudulent_claim",
            "false_statement_penalty",
            "civil_penalty_liability",
            "penalty_value_multiplier",
            "peacetime_death_compensation",
            "game_bird_preserve_protection",
            "game_preserve",
            "grant_contract_award",
            "grant_contract_fund_use",
            "government_claim",
            "government_publication_depository_access",
            "government_property_marking",
            "government_shipment_loss_prevention",
            "office_of_womens_health",
            "public_health_agency",
            "governing_body",
            "housing_family_service_investment",
            "housing_investment_authority",
            "housing_transfer_authority",
            "health_professional_education_assistance",
            "human_welfare_resource_program",
            "illegal_sexual_activity",
            "illegal_sexual_activity_transport",
            "education_assistance_benefit",
            "historic_area",
            "historic_area_access_road",
            "interstate_air_transportation",
            "agency_determination",
            "agency_certification_determination",
            "eligibility_determination",
            "internal_service_fee",
            "internal_delivery_fee_collection",
            "interinstitutional_discussion",
            "interagency_coordination",
            "irrigation_project",
            "international_agreement_authority",
            "international_boundary_water_commission",
            "international_storage_dam_authorization",
            "joint_infrastructure_operation",
            "judicial_sale_execution",
            "land_acquisition_authority",
            "land_donation_acceptance",
            "land_title_authority",
            "marshal_incapacity",
            "program_administration",
            "military_commission_procedure",
            "military_defense_counsel_duty",
            "military_trial_counsel_duty",
            "mineral_land_status",
            "mineral_leasing_law",
            "mining_claim",
            "management_position_assignment",
            "natural_resource_use",
            "natural_area_establishment",
            "national_seashore_recreation_area",
            "nonirrigable_land_status",
            "homestead_entry_confirmation",
            "land_withdrawal_restoration_scope",
            "permanent_nonirrigable_land_status",
            "railroad_land_status",
            "jurisdiction_authority",
            "law_enforcement",
            "legal_relationship_override",
            "liability_protection",
            "lie_detector_test",
            "lie_detector_use_prohibition",
            "employee_polygraph_protection",
            "livestock_commerce",
            "marine_science_development",
            "mineral_development_technology",
            "mining_law_application",
            "territorial_jurisdiction",
            "hydraulic_mining",
            "california_debris_commission",
            "clearing_bank_resolution",
            "federal_reserve_board_oversight",
            "monitoring_enforcement",
            "nato_common_funded_budget_contribution",
            "national_forest_resource",
            "national_seashore_recreation_area",
            "office_establishment",
            "office_of_womens_health",
            "office_seal",
            "absent_uniformed_services_voter",
            "border_infrastructure_modernization",
            "capitol_visitor_center",
            "chief_executive_officer",
            "federal_alcohol_law_equal_treatment",
            "fishery_loan_property",
            "fishery_vessel_property_disposition",
            "government_purchasing_authority",
            "overseas_voter",
            "technology_modernization",
            "trust_territory_purchasing_authority",
            "uniformed_services_voter",
            "visitor_center_assistant",
            "officer_election",
            "officer_promotion",
            "officer_promotion_retention",
            "officer_retention",
            "naval_officer_management_assignment",
            "participating_jurisdiction",
            "philippines_medical_assistance_authority",
            "partnership",
            "partnership_adjustment",
            "partnership_adjustment_notice",
            "partnership_item",
            "partnership_notice_proceeding",
            "partnership_proceeding",
            "official_seal",
            "perishable_agricultural_commodity",
            "plant_variety_protection",
            "plant_variety_protection_office",
            "prize_proceeds_charge",
            "model_demonstration",
            "procedure_adoption_duty",
            "promotion_retention",
            "professional_assessment_committee",
            "priority_state",
            "funding_eligibility",
            "health_insurance_reform_implementation_fund",
            "implementation_fund",
            "implementation_funding",
            "patient_protection_affordable_care_act",
            "participation_eligibility",
            "per_capita_ranking",
            "remedy",
            "report_contents",
            "related_crime",
            "deadline_report_duty",
            "reserve_active_status_list",
            "resource_availability",
            "public_access_requirement",
            "public_facility_use",
            "government_facility_use",
            "foreign_government_facility_use",
            "post_term_member_right",
            "post_term_public_document_allotment",
            "publication_disposal_authority",
            "congressional_precedents_distribution",
            "official_use_restriction",
            "public_document_allotment",
            "road_conveyance",
            "sea_grant_college",
            "sea_grant_college_program",
            "secretary_availability",
            "sovereign_debt_conversion",
            "statutory_construction",
            "statutory_force_effect",
            "statutory_applicability",
            "statutory_chapter_applicability",
            "supplemental_authorization_policy",
            "statutory_short_title",
            "settler_resource_use",
            "sustainable_chemistry_research",
            "technology_transfer",
            "technology_transfer_assessment",
            "technology_transition_assessment",
            "trade_rule_of_law_compliance",
            "alternative_fuel_vehicle_program",
            "benefit_cost_information",
            "consumer_information_package",
            "environmental_performance_disclosure",
            "public_information_program",
            "trainee_support",
            "test_platform",
            "training_program_support",
            "state_court_civil_jurisdiction",
            "state_court_jurisdiction",
            "state_energy_program",
            "state_ranking",
            "state_conveyance_authority",
            "air_carrier_service_duty",
            "air_transportation_service_duty",
            "state_allotment_amount",
            "state_allotment_duty",
            "state_formula_grant",
            "substance_abuse_treatment_program",
            "timber_cutting",
            "timber_cutting_forest_scope",
            "timber_stone_use",
            "treasury_deposit",
            "treasury_payment_source",
            "treasury_requisition_payment",
            "unknown_party_deposit",
            "loss_damage_risk_mitigation",
            "mexico_bilateral_agreement",
            "regulation_prescription_authority",
            "regulatory_compliance_duty",
            "rio_grande_water_project",
            "valuable_shipment_regulation",
            "veterans_personal_property",
            "veterans_medical_care",
            "vessel_entry_documentation",
            "special_adapted_housing_assistance",
            "commonwealth_army_veteran_benefit",
            "philippines_veteran_assistance",
            "nato_contribution_authority",
            "nato_common_funded_budget",
            "white_horse_hill_game_preserve",
            "material_fact_representation",
            "surplus_housing_transfer",
            "workforce_development_program",
            "workforce_performance_accountability",
            "workforce_performance_reporting",
            "retiring_member_document_right",
            "perishable_commodity_container_exemption",
        }:
            add("frame")
        if normalized_atom in {
            "agency_determination",
            "agency_certification_determination",
            "accountability_responsibility",
            "child_abduction_remedy",
            "china_relations_oversight",
            "commodity_value_determination",
            "congressional_findings_declaration",
            "consular_officer_duty_liability",
            "consular_officer_powers_duties_liabilities",
            "development_advice_assistance",
            "eligibility_determination",
            "deceased_veterans_property_disposition",
            "departmental_property_custody",
            "departmental_record_custody",
            "foreign_service_building",
            "false_claim_knowledge",
            "false_statement_penalty",
            "material_fact_representation",
            "scienter_requirement",
            "monitoring_enforcement",
            "military_commission_procedure",
            "interinstitutional_discussion",
            "interagency_coordination",
            "homestead_entry_confirmation",
            "illegal_sexual_activity",
            "illegal_sexual_activity_transport",
            "nonirrigable_land_status",
            "natural_area_establishment",
            "partnership",
            "partnership_adjustment",
            "partnership_adjustment_notice",
            "partnership_item",
            "partnership_notice_proceeding",
            "partnership_proceeding",
            "absent_uniformed_services_voter",
            "chief_executive_officer",
            "federal_alcohol_law_equal_treatment",
            "fishery_loan_property",
            "fishery_vessel_property_disposition",
            "government_purchasing_authority",
            "overseas_voter",
            "technology_modernization",
            "trust_territory_purchasing_authority",
            "uniformed_services_voter",
            "visitor_center_assistant",
            "permanent_nonirrigable_land_status",
            "land_withdrawal_restoration_scope",
            "sovereign_debt_conversion",
            "trade_rule_of_law_compliance",
            "technology_transfer_assessment",
            "technology_transition_assessment",
            "benefit_cost_information",
            "consumer_information_package",
            "environmental_performance_disclosure",
            "federal_reserve_board_oversight",
            "foreign_relations_exchange_program",
            "foreign_service",
            "international_agreement_authority",
            "mexico_bilateral_agreement",
            "philippines_veteran_assistance",
            "nato_contribution_authority",
            "public_information_program",
            "professional_assessment_committee",
            "service_eligibility",
            "related_crime",
        }:
            add("epistemic")
        if normalized_atom in {
            "false_claim_knowledge",
            "false_fraudulent_claim",
            "illegal_sexual_activity",
            "illegal_sexual_activity_transport",
            "related_crime",
            "scienter_requirement",
        }:
            add("doxastic")
        if normalized_atom in {
            "affordable_housing_supply",
            "agency_certification_determination",
            "cost_expense_charge",
            "education_assistance_benefit",
            "education_assistance_repayment",
            "federal_repayment_obligation",
            "health_professional_education_assistance",
            "housing_family_service_investment",
            "housing_investment_authority",
            "homestead_entry_confirmation",
            "housing_transfer_authority",
            "internal_service_fee",
            "land_acquisition_authority",
            "land_donation_acceptance",
            "award_program",
            "officer_promotion",
            "officer_promotion_retention",
            "officer_retention",
            "road_conveyance",
            "office_seal",
            "official_seal",
            "plant_variety_protection",
            "plant_variety_protection_office",
            "prize_proceeds_charge",
            "fund_transfer_authority",
            "competitive_award_program",
            "formula_grant",
            "partnership",
            "partnership_adjustment_notice",
            "partnership_notice_proceeding",
            "research_grant",
            "sea_grant_college_program",
            "state_formula_grant",
            "settler_resource_use",
            "state_conveyance_authority",
            "timber_stone_use",
            "treasury_deposit",
            "treasury_payment_source",
            "treasury_requisition_payment",
            "unknown_party_deposit",
            "permanent_nonirrigable_land_status",
            "perishable_agricultural_commodity",
            "promotion_retention",
            "reserve_active_status_list",
            "resource_availability",
            "secretary_availability",
            "surplus_housing_transfer",
            "veterans_medical_care",
            "special_adapted_housing_assistance",
            "civil_penalty_liability",
            "penalty_value_multiplier",
            "commonwealth_army_veteran_benefit",
            "philippines_veteran_assistance",
            "nato_contribution_authority",
            "perishable_commodity_container_exemption",
        }:
            add("deontic")
        if normalized_atom in {
            "codification",
            "definition",
            "omitted",
            "reclassified",
            "renumbered",
            "repealed",
            "reserved",
            "terminated",
            "transferred",
            "vacant",
            "editorial_transfer_status",
        }:
            add("frame")
        if normalized_atom in {
            "china_relations_oversight",
            "conservation_area_management",
            "definition",
            "exception_or_condition",
            "funding_eligibility",
            "health_insurance_reform_implementation_fund",
            "implementation_fund",
            "implementation_funding",
            "patient_protection_affordable_care_act",
            "construction_no_effect",
            "eligibility_determination",
            "child_abduction_remedy",
            "grant_contract_fund_use",
            "legal_relationship_override",
            "liability_protection",
            "lie_detector_test",
            "lie_detector_use_prohibition",
            "employee_polygraph_protection",
            "military_commission_procedure",
            "livestock_commerce",
            "monitoring_enforcement",
            "interinstitutional_discussion",
            "land_acquisition_authority",
            "land_donation_acceptance",
            "land_title_authority",
            "natural_area_establishment",
            "national_seashore_recreation_area",
            "territorial_jurisdiction",
            "hydraulic_mining",
            "false_statement_penalty",
            "civil_penalty_liability",
            "penalty_value_multiplier",
            "statutory_violation_condition",
            "scienter_requirement",
            "material_fact_representation",
            "absent_uniformed_services_voter",
            "federal_alcohol_law_equal_treatment",
            "government_purchasing_authority",
            "overseas_voter",
            "technology_modernization",
            "trust_territory_purchasing_authority",
            "uniformed_services_voter",
            "partnership",
            "partnership_adjustment",
            "partnership_notice_proceeding",
            "partnership_proceeding",
            "priority_state",
            "post_term_member_right",
            "post_term_public_document_allotment",
            "public_document_allotment",
            "retiring_member_document_right",
            "per_capita_ranking",
            "statutory_construction",
            "statutory_force_effect",
            "perishable_agricultural_commodity",
            "statutory_applicability",
            "statutory_chapter_applicability",
            "supplemental_authorization_policy",
            "state_energy_program",
            "state_ranking",
            "service_eligibility",
            "sovereign_debt_conversion",
            "trade_rule_of_law_compliance",
            "benefit_cost_information",
            "consumer_information_package",
            "government_property_marking",
            "international_agreement_authority",
            "mexico_bilateral_agreement",
            "official_use_restriction",
            "clearing_bank_resolution",
            "federal_reserve_board_oversight",
            "perishable_commodity_container_exemption",
            "special_adapted_housing_assistance",
        }:
            add("conditional_normative")
        if normalized_atom in {
            "education_assistance_program",
            "federal_assistance_administration",
            "federal_payment_formula",
            "income_gap_multiplier",
            "international_space_station",
            "iss_research_utilization",
            "public_health_surveillance",
            "science_engineering_education_program",
            "space_science_research",
            "seaman_discharge",
            "smart_manufacturing_report",
            "wage_account_discharge",
        }:
            add("deontic")
        if normalized_atom in {
            "appeal_bail_rule",
            "federal_assistance_administration",
            "federal_payment_formula",
            "income_gap_multiplier",
            "international_space_station",
            "iss_research_utilization",
            "naval_facility_expansion",
            "public_health_surveillance",
            "space_science_research",
            "smart_manufacturing_report",
        }:
            add("frame")
        if normalized_atom in {
            "appeal_bail_rule",
            "iss_research_utilization",
            "naval_facility_expansion",
            "seaman_discharge",
            "smart_manufacturing_report",
        }:
            add("temporal")
        if normalized_atom in {
            "federal_payment_formula",
            "income_gap_multiplier",
            "international_space_station",
            "iss_research_utilization",
            "space_science_research",
        }:
            add("conditional_normative")
            add("epistemic")
        if normalized_atom in {
            "appeal_bail_rule",
            "education_assistance_program",
            "public_health_surveillance",
            "advisory_committee_appointment",
            "appointment_authority",
            "implementation_action_report",
            "museum_collection_custody",
        }:
            add("deontic")
        if normalized_atom in {
            "advisory_committee",
            "advisory_committee_appointment",
            "appointment_authority",
            "implementation_action_report",
            "museum_board_regents",
            "museum_board_trustees",
            "museum_collection_custody",
            "national_museum_american_indian",
        }:
            add("frame")
        if normalized_atom in {
            "implementation_action_report",
            "museum_collection_custody",
            "museum_board_regents",
            "museum_board_trustees",
        }:
            add("epistemic")
        if normalized_atom in {
            "advisory_committee_appointment",
            "implementation_action_report",
        }:
            add("temporal")
        if normalized_atom in {
            "implementation_action_report",
            "museum_collection_custody",
        }:
            add("conditional_normative")
        if normalized_atom in {
            "colorado_river_floodway_report",
            "congressional_report_duty",
            "report_contents",
            "secretary_recommendation_report",
        }:
            add("deontic")
            add("temporal")
            add("conditional_normative")
            add("frame")
        if normalized_atom in {
            "colorado_river_floodway_report",
            "secretary_recommendation_report",
        }:
            add("epistemic")
        if normalized_atom in {
            "benefit_claim_adjudication",
            "bill_lading_indorsement_negotiation",
            "black_lung_benefit_claim",
            "black_lung_benefits",
            "integrated_agency_procedure",
            "negotiable_bill_of_lading",
            "order_document_delivery",
            "securities_trust_indenture_procedure",
        }:
            add("deontic")
        if normalized_atom in {
            "benefit_claim_adjudication",
            "black_lung_benefit_claim",
            "black_lung_benefits",
            "integrated_agency_procedure",
            "mine_safety_health",
            "securities_exchange_commission",
            "securities_trust_indenture",
            "securities_trust_indenture_procedure",
        }:
            add("frame")
        if normalized_atom in {
            "benefit_claim_adjudication",
            "black_lung_benefit_claim",
            "black_lung_benefits",
            "integrated_agency_procedure",
            "securities_trust_indenture_procedure",
        }:
            add("temporal")
        if normalized_atom in {
            "benefit_claim_adjudication",
            "bill_lading_indorsement_negotiation",
            "black_lung_benefit_claim",
            "black_lung_benefits",
            "integrated_agency_procedure",
            "securities_trust_indenture_procedure",
        }:
            add("conditional_normative")
        if normalized_atom in {
            "compact_free_association",
            "credit_authority",
            "director_government_actor",
            "director_government_actor_definition",
            "export_credit_authority",
            "federal_financing_bank",
            "freely_associated_state",
            "rail_employee_status",
            "rail_employee_trust_fund",
        }:
            add("frame")
        if normalized_atom in {
            "compact_free_association",
            "credit_authority",
            "director_government_actor_definition",
            "export_credit_authority",
            "federal_financing_bank",
            "freely_associated_state",
            "rail_employee_status",
            "rail_employee_trust_fund",
        }:
            add("deontic")
            add("conditional_normative")
        if normalized_atom in {
            "compact_free_association",
            "credit_authority",
            "export_credit_authority",
            "federal_financing_bank",
            "freely_associated_state",
        }:
            add("epistemic")
        if normalized_atom in {
            "credit_authority",
            "export_credit_authority",
            "federal_financing_bank",
        }:
            add("doxastic")
        if normalized_atom in {
            "freely_associated_state",
            "rail_employee_status",
            "rail_employee_trust_fund",
        }:
            add("temporal")
        if normalized_atom in {
            "clean_hull_administration_enforcement",
            "internal_delivery_fee_collection",
            "philippines_medical_assistance_authority",
            "veterans_medical_care",
        }:
            add("deontic")
            add("frame")
            add("conditional_normative")
        if normalized_atom in {
            "fiscal_year_budget_limitation",
            "nato_common_funded_budget_contribution",
        }:
            add("deontic")
            add("temporal")
            add("frame")
            add("conditional_normative")
        if normalized_atom in {
            "implementation_noninterference",
            "legal_relationship_noninterference",
            "personal_property_disposition",
            "property_delivery_duty",
            "public_safety_broadband_network",
        }:
            add("deontic")
            add("frame")
            add("conditional_normative")
        if normalized_atom in {
            "chapter_administration",
            "developing_institution_program",
            "higher_education_student_assistance",
            "rental_rate_authority",
            "reserved_land",
            "reserved_land_lease_authority",
            "revenue_disposition",
        }:
            add("deontic")
            add("frame")
            add("conditional_normative")
        if normalized_atom in {
            "contracting_authority",
            "cooperative_agreement_authority",
            "fund_transfer_authority",
            "generation_skipping_transfer_tax",
            "rental_rate_authority",
            "reserved_land_lease_authority",
            "revenue_disposition",
            "tax_computation_rule",
        }:
            add("deontic")
            add("dynamic")
            add("frame")
            add("conditional_normative")
    return targets


def _typed_decompiler_semantic_atom_supports_target(
    atom: str,
    *,
    target_family: str,
    source_family: str,
) -> bool:
    normalized_atom = _clean_text(atom).lower()
    normalized_target = _clean_text(target_family).lower()
    normalized_source = _clean_text(source_family).lower()
    if not normalized_atom or not normalized_target:
        return False
    target_families = _typed_decompiler_semantic_atom_target_families(
        [normalized_atom]
    )
    if normalized_source == "frame":
        for status_target in _typed_decompiler_status_atom_target_families(
            [normalized_atom]
        ):
            if status_target not in target_families:
                target_families.append(status_target)
    return normalized_target in target_families


def _typed_decompiler_status_atom_target_families(
    semantic_atoms: Sequence[str],
) -> List[str]:
    """Return modal targets carried by U.S.C. editorial status atoms."""
    targets: List[str] = []

    def add(target: str) -> None:
        if target and target not in targets:
            targets.append(target)

    for atom in semantic_atoms:
        normalized_atom = _clean_text(atom).lower()
        if normalized_atom not in {
            "codification",
            "editorial_transfer_status",
            "omitted",
            "reclassified",
            "renumbered",
            "repealed",
            "reserved",
            "terminated",
            "transferred",
            "vacant",
        }:
            continue
        add("frame")
        add("conditional_normative")
        if normalized_atom in {
            "reclassified",
            "renumbered",
            "repealed",
            "terminated",
            "transferred",
            "omitted",
            "vacant",
        }:
            add("deontic")
        if normalized_atom in {
            "omitted",
            "reclassified",
            "renumbered",
            "repealed",
            "terminated",
            "transferred",
            "vacant",
        }:
            add("temporal")
        if normalized_atom == "editorial_transfer_status":
            add("temporal")
    return targets


def _typed_decompiler_status_detail_slots(text: str) -> List[Tuple[str, str]]:
    """Return normalized status transition details for typed reconstruction."""
    slots: List[Tuple[str, str]] = []
    normalized_text = _clean_text(text)
    for slot, value in _uscode_editorial_status_detail_slots(
        normalized_text,
        slot_prefix="typed_decompiler_status",
    ):
        if not slot.startswith("uscode_editorial_status_"):
            continue
        normalized_slot = slot.replace("uscode_editorial_status_", "")
        normalized_value = _clean_text(value)
        if not normalized_slot or not normalized_value:
            continue
        slots.append((f"typed-decompiler-status-{normalized_slot}", normalized_value))
    explicit_target = re.search(
        rf"\b(?:renumbered|reclassified|transferred)"
        rf"(?:"
        rf"(?:\s+(?:as|to|from))?\s+(?:§{{1,2}}\s*|secs?\.?\s*|sections?\s+)"
        rf"|\s+(?:as|to|from)\s+"
        rf")"
        rf"(?P<section>{_USCODE_SECTION_LIST_PATTERN})"
        rf"(?:\s+of\s+(?:(?:this|such)\s+title|Title\s+(?P<title>\d+[A-Za-z]*)))?",
        normalized_text,
        flags=re.IGNORECASE,
    )
    if explicit_target is not None:
        target_section = _clean_text(explicit_target.group("section"))
        target_title = _clean_text(explicit_target.group("title") or "")
        slots = [
            (slot, value)
            for slot, value in slots
            if slot
            not in {
                "typed-decompiler-status-target_section",
                "typed-decompiler-status-target_title",
                "typed-decompiler-status-target_citation",
            }
        ]
        if target_section:
            slots.append(
                ("typed-decompiler-status-target_section", target_section)
            )
            if target_title:
                slots.append(("typed-decompiler-status-target_title", target_title))
                slots.append(
                    (
                        "typed-decompiler-status-target_citation",
                        f"{target_title} U.S.C. {target_section}",
                    )
                )
            else:
                slots.append(
                    (
                        "typed-decompiler-status-target_citation",
                        f"this title section {target_section}",
                    )
                )
    return _unique_slot_values(slots)


def _typed_decompiler_status_detail_target_families(
    status_detail_slots: Sequence[Tuple[str, str]],
) -> List[str]:
    """Route extracted U.S.C. transition details to modal target families."""
    targets: List[str] = []

    def add(target: str) -> None:
        if target and target not in targets:
            targets.append(target)

    keywords = {
        _clean_text(value).lower()
        for slot, value in status_detail_slots
        if slot == "typed-decompiler-status-keyword"
    }
    if status_detail_slots:
        add("frame")
        add("conditional_normative")
    if keywords.intersection(
        {
            "omitted",
            "reclassified",
            "renumbered",
            "repealed",
            "terminated",
            "transferred",
            "vacant",
        }
    ):
        add("temporal")
    if keywords.intersection(
        {
            "omitted",
            "reclassified",
            "renumbered",
            "repealed",
            "terminated",
            "transferred",
            "vacant",
        }
    ):
        add("deontic")
    return targets


def _typed_decompiler_status_detail_legal_ir_views(
    status_slot: str,
    status_value: str,
) -> List[str]:
    """Map U.S.C. status transition slots to LegalIR views."""
    slot = _clean_text(status_slot).lower()
    value = _clean_text(status_value).lower()
    if not slot or not value:
        return []
    views: List[str] = []

    def add(view: str) -> None:
        if view and view not in views:
            views.append(view)

    add("CEC.native")
    add("knowledge_graphs.neo4j_compat")
    add("modal.frame_logic")
    if slot in {
        "typed-decompiler-status-target_citation",
        "typed-decompiler-status-target_section",
        "typed-decompiler-status-target_title",
    }:
        add("TDFOL.prover")
    if value in {
        "omitted",
        "reclassified",
        "renumbered",
        "repealed",
        "terminated",
        "transferred",
        "vacant",
    }:
        add("deontic.ir")
    return views


def _typed_decompiler_status_surface_profile_slots(
    *,
    source_family: str,
    target_family: str,
    status_slot: str,
    status_value: str,
) -> List[Tuple[str, str]]:
    """Emit status detail profiles for typed semantic reconstruction."""
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    slot = _clean_text(status_slot).lower()
    value = _clean_text(status_value)
    if not source or not target or not slot or not value:
        return []

    pair = f"{source}->{target}"
    if slot == "typed-decompiler-status-keyword":
        profile = "editorial_status_surface"
    elif slot in {
        "typed-decompiler-status-target_citation",
        "typed-decompiler-status-target_section",
        "typed-decompiler-status-target_title",
    }:
        profile = "editorial_target_reference"
    else:
        profile = "editorial_notes"

    slots = [
        (
            "typed-decompiler-target-reconstruction-surface-profile",
            f"{profile}:{pair}",
        ),
        (
            "typed-decompiler-target-reconstruction-surface-profile-value",
            f"{profile}:{value}:{pair}",
        ),
        (
            "semantic_slot_prototype",
            f"slot:typed-decompiler-target-reconstruction-surface-profile:{profile}:{pair}",
        ),
    ]
    for view in _typed_decompiler_status_detail_legal_ir_views(slot, value):
        slots.extend(
            (
                (
                    "semantic_slot_legal_ir_view_prototype",
                    (
                        "slot:typed-decompiler-target-reconstruction-surface-profile:"
                        f"{profile}:{pair}||{view}"
                    ),
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        f"{source}||slot:typed-decompiler-target-reconstruction-"
                        f"surface-profile:{profile}:{pair}||{view}"
                    ),
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        f"{target}||slot:typed-decompiler-target-reconstruction-"
                        f"surface-profile:{profile}:{pair}||{view}"
                    ),
                ),
            )
        )
    return slots


def _source_scope_reconstruction_cues(text: str) -> List[str]:
    normalized = _clean_text(text).replace("_", " ").lower()
    if not normalized:
        return []
    cues: List[str] = []

    def add(cue: str) -> None:
        if cue and cue not in cues:
            cues.append(cue)

    statutory_scope_slots = _statutory_scope_slots(normalized)
    if statutory_scope_slots:
        for slot, value in statutory_scope_slots:
            if slot == "statutory_scope_connector":
                add(value.replace(" ", "_"))
    if re.search(r"(?<!\w)within\s+\d+\s+(?:days?|months?|years?)(?!\w)", normalized):
        add("within")
    for phrase, cue in (
        ("no later than", "no_later_than"),
        ("not later than", "not_later_than"),
        ("does not apply", "does_not_apply"),
        ("do not apply", "does_not_apply"),
        ("did not apply", "does_not_apply"),
        ("shall not apply", "shall_not_apply"),
        ("will not operate", "will_not_operate"),
        ("testing period", "testing_period"),
        ("after conclusion", "after_conclusion"),
        ("with their consent", "with_consent"),
        ("with consent", "with_consent"),
        ("thereafter", "thereafter"),
    ):
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized):
            add(cue)
    for value in _definition_condition_support_values(normalized):
        add(value.replace(" ", "_"))
    if re.search(r"\bexempt(?:ed|ion|ions)?\b", normalized):
        add("exempt")
    return cues


def _source_scope_cue_legal_ir_views(cue: str) -> List[str]:
    normalized_cue = _clean_text(cue).lower().replace(" ", "_")
    if not normalized_cue:
        return []
    views: List[str] = []

    def add(view: str) -> None:
        if view and view not in views:
            views.append(view)

    if normalized_cue in {
        "as_defined_in",
        "as_described_in",
        "as_otherwise_provided_in",
        "as_provided_in",
        "as_set_forth_in",
        "defined_in",
        "described_in",
        "for_purposes_of",
        "for_the_purposes_of",
        "in_accordance_with",
        "in_the_case_of",
        "with_consent",
        "defined_term_criteria",
        "definition_condition",
        "definition_relative_condition",
        "eligibility_condition",
        "enumerated_definition_criteria",
        "pursuant_to",
        "ranking_condition",
        "referred_to_in",
        "subject_to",
        "under",
        "with_respect_to",
        "within",
        "heading",
    }:
        add("knowledge_graphs.neo4j_compat")
        add("CEC.native")
        add("modal.frame_logic")
    if normalized_cue in {
        "as_otherwise_provided_in",
        "as_provided_in",
        "heading",
        "in_accordance_with",
        "pursuant_to",
        "subject_to",
        "under",
        "with_consent",
        "with_respect_to",
    }:
        add("deontic.ir")
        add("TDFOL.prover")
    if normalized_cue in {
        "does_not_apply",
        "shall_not_apply",
        "exempt",
        "exemption",
        "will_not_operate",
    }:
        add("deontic.ir")
        add("TDFOL.prover")
        add("CEC.native")
    if normalized_cue in {
        "after",
        "after_conclusion",
        "before",
        "by",
        "no_later_than",
        "not_later_than",
        "thereafter",
        "testing_period",
        "until",
        "when",
        "within",
    }:
        add("TDFOL.prover")
    if normalized_cue in {
        "does_not_apply",
        "exempt",
        "exemption",
        "shall_not_apply",
        "testing_period",
        "will_not_operate",
    }:
        add("modal.frame_logic")
    if normalized_cue.startswith("uscode_residual_span"):
        add("deontic.ir")
        add("CEC.native")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    return views


def _typed_decompiler_family_pair_legal_ir_views(
    source_family: str,
    target_family: str,
) -> List[str]:
    """Return legal-view anchors for typed source/target reconstruction pairs."""
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    pair = f"{source}->{target}"
    views: List[str] = []

    def add(view: str) -> None:
        if view and view not in views:
            views.append(view)

    if target == "deontic" or source == "deontic":
        add("deontic.ir")
        add("CEC.native")
        add("knowledge_graphs.neo4j_compat")
    if target == "conditional_normative":
        add("deontic.ir")
        add("CEC.native")
        add("TDFOL.prover")
    if target == "temporal" or source == "temporal":
        add("TDFOL.prover")
        add("CEC.native")
    if target == "epistemic" or source == "epistemic":
        add("deontic.ir")
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
    if target == "doxastic" or source == "doxastic":
        add("TDFOL.prover")
        add("knowledge_graphs.neo4j_compat")
    if target == "dynamic" or source == "dynamic":
        add("deontic.ir")
        add("TDFOL.prover")
        add("CEC.native")
    if source == "frame" or target == "frame":
        add("knowledge_graphs.neo4j_compat")
        add("modal.frame_logic")
        add("CEC.native")
    if pair in {
        "deontic->conditional_normative",
        "deontic->deontic",
        "frame->deontic",
        "frame->frame",
    }:
        add("CEC.native")
        add("knowledge_graphs.neo4j_compat")
    if pair == "frame->frame":
        add("TDFOL.prover")
    return views


def _typed_decompiler_surface_profile_slots(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    source_family: str,
    target_family: str,
    pair: str,
) -> List[Tuple[str, str]]:
    """Bind typed family-pair reconstruction to recurring U.S.C. surfaces."""
    source_profile = _typed_decompiler_source_surface_profile(document)
    target_profiles = _typed_decompiler_target_surface_profiles(
        document=document,
        formula=formula,
    )
    if not source_profile or not target_profiles:
        return []

    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    if not source or not target or not pair:
        return []

    views = _typed_decompiler_family_pair_legal_ir_views(source, target)
    if not views:
        views = _default_force_view_family_pair_views(
            source_family=source,
            target_family=target,
        )
    slots: List[Tuple[str, str]] = [
        ("typed-decompiler-source-surface-profile", source_profile),
        (
            "typed-decompiler-target-family-surface-profile",
            f"{source_profile}:{target}",
        ),
        (
            "typed-decompiler-target-reconstruction-surface-profile",
            f"{source_profile}:{pair}",
        ),
    ]
    for target_profile in target_profiles:
        transition = f"{source_profile}->{target_profile}"
        slots.extend(
            (
                ("typed-decompiler-target-surface-profile", target_profile),
                ("typed-decompiler-surface-profile-transition", transition),
                (
                    "decompiler-surface",
                    f"uscode-surface-profile-transition:{transition}",
                ),
                (
                    "semantic_slot_prototype",
                    (
                        "slot:typed-decompiler-target-reconstruction-surface-profile:"
                        f"{source_profile}:{pair}"
                    ),
                ),
                (
                    "family_semantic_slot_prototype",
                    (
                        f"{target}||slot:typed-decompiler-target-family-surface-profile:"
                        f"{source_profile}:{target}"
                    ),
                ),
                (
                    "family_semantic_slot_prototype",
                    (
                        f"{target}||slot:typed-decompiler-target-reconstruction-surface-profile:"
                        f"{source_profile}:{pair}"
                    ),
                ),
            )
        )
        for view in views:
            slots.extend(
                (
                    ("legal_ir_view_prototype", view),
                    (
                        "semantic_slot_legal_ir_view_prototype",
                        (
                            "slot:typed-decompiler-target-family-surface-profile:"
                            f"{source_profile}:{target}||{view}"
                        ),
                    ),
                    (
                        "semantic_slot_legal_ir_view_prototype",
                        (
                            "slot:typed-decompiler-target-reconstruction-surface-profile:"
                            f"{source_profile}:{pair}||{view}"
                        ),
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        (
                            f"{target}||slot:typed-decompiler-target-family-surface-profile:"
                            f"{source_profile}:{target}||{view}"
                        ),
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        (
                            f"{target}||slot:typed-decompiler-target-reconstruction-surface-profile:"
                            f"{source_profile}:{pair}||{view}"
                        ),
                    ),
                    (
                        "semantic_slot_legal_ir_view_prototype",
                        (
                            "slot:typed-decompiler-surface-profile-transition:"
                            f"{transition}||{view}"
                        ),
                    ),
                )
            )
    return _unique_slot_values(slots)


def _typed_decompiler_reconstruction_profile_slots(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    source_family: str,
    target_family: str,
    pair: str,
    force: str,
    polarity: str,
    predicate_key: str,
    semantic_predicate_key: str,
    semantic_atoms: Sequence[str],
) -> List[Tuple[str, str]]:
    """Bind typed reconstruction slots to one compact LegalIR surface profile."""
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    if not source or not target or not pair:
        return []

    source_profile = _typed_decompiler_source_surface_profile(document)
    target_profiles = _typed_decompiler_target_surface_profiles(
        document=document,
        formula=formula,
    )
    if not source_profile and not target_profiles:
        return []

    views = _typed_decompiler_family_pair_legal_ir_views(source, target)
    if not views:
        views = _default_force_view_family_pair_views(
            source_family=source,
            target_family=target,
        )
    if not views:
        return []

    predicate = semantic_predicate_key or predicate_key or "unnamed"
    force_value = _slot_safe_family_pair_key(force) or "unspecified"
    polarity_value = _slot_safe_family_pair_key(polarity) or "positive_scope"
    surface_values = target_profiles or ["typed_ir_surface"]
    if source_profile:
        surface_values = [
            f"{source_profile}->{target_profile}"
            for target_profile in surface_values
        ]

    slots: List[Tuple[str, str]] = []
    atom_values = [
        _slot_safe_family_pair_key(atom)
        for atom in semantic_atoms[:4]
        if _slot_safe_family_pair_key(atom)
    ]
    for surface in surface_values:
        surface_key = _slot_safe_family_pair_key(surface)
        if not surface_key:
            continue
        for view in views:
            profile = (
                f"{pair}|view:{view}|surface:{surface_key}|"
                f"force:{force_value}:{polarity_value}|predicate:{predicate}"
            )
            slots.extend(
                (
                    ("typed-decompiler-reconstruction-semantic-profile", profile),
                    (
                        "semantic_slot_legal_ir_view_prototype",
                        (
                            "slot:typed-decompiler-reconstruction-semantic-profile:"
                            f"{pair}:{surface_key}:{predicate}||{view}"
                        ),
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        (
                            f"{source}||slot:typed-decompiler-reconstruction-"
                            f"semantic-profile:{pair}:{surface_key}:{predicate}||{view}"
                        ),
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        (
                            f"{target}||slot:typed-decompiler-reconstruction-"
                            f"semantic-profile:{pair}:{surface_key}:{predicate}||{view}"
                        ),
                    ),
                )
            )
            for atom in atom_values:
                slots.extend(
                    (
                        (
                            "typed-decompiler-reconstruction-semantic-profile-atom",
                            f"{profile}|atom:{atom}",
                        ),
                        (
                            "family_semantic_slot_legal_ir_view_prototype",
                            (
                                f"{target}||slot:typed-decompiler-reconstruction-"
                                f"semantic-profile-atom:{pair}:{atom}||{view}"
                            ),
                        ),
                    )
                )
    return _unique_slot_values(slots)


def _typed_decompiler_source_surface_profile(document: ModalIRDocument) -> str:
    """Classify source document surfaces that recur in U.S.C. samples."""
    source = _clean_text(document.source).lower()
    source_id = _clean_text(document.document_id).lower()
    text = _clean_text(document.normalized_text)
    citation = _clean_text(document.metadata.get("citation") or "")
    if not text:
        return ""
    if (
        source == "us_code"
        or source_id.startswith("us-code-")
        or re.search(r"\bU\.?\s*S\.?\s*C\.?\b", citation, flags=re.IGNORECASE)
        or re.search(r"\bU\.?\s*S\.?\s*C\.?\b", text, flags=re.IGNORECASE)
        or re.search(r"\bUnited States Code\b", text, flags=re.IGNORECASE)
    ):
        return "uscode_catalog_record"
    return ""


def _typed_decompiler_target_surface_profiles(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[str]:
    text = _clean_text(document.normalized_text)
    profiles: List[str] = []

    def add(profile: str) -> None:
        if profile and profile not in profiles:
            profiles.append(profile)

    if _fallback_section_heading_tail_text(document=document, formula=formula):
        add("uscode_section_heading_surface")
    if re.search(
        rf"\b(?:Secs?\.?|§{{1,2}})\s*{_USCODE_SECTION_LIST_PATTERN}\b\s*[-.]\s*"
        r"[A-Z][A-Za-z0-9 ,;:'()/-]+",
        text,
        flags=re.IGNORECASE,
    ):
        add("uscode_section_heading_surface")
    if _uscode_status_clause_keywords(document=document, formula=formula):
        add("uscode_editorial_status_surface")
    lowered = text.lower()
    if re.search(r"\b(?:policy\s+disclosures?|conditions?\s+and\s+exclusions?|national\s+flood\s+insurance)\b", lowered):
        add("uscode_policy_disclosure_surface")
    if re.search(r"\b(?:nontaxation|tax\s+treatment|taxable\s+income|internal\s+revenue\s+code)\b", lowered):
        add("uscode_tax_treatment_surface")
    if re.search(
        r"\b(?:consolidated\s+returns?|graduated\s+corporate\s+rates?|"
        r"accumulated\s+earnings\s+credit|taxable\s+years?\s+beginning)\b",
        lowered,
    ):
        add("uscode_consolidated_return_tax_surface")
    if re.search(r"\b(?:audit(?:s)?\s+by\s+comptroller\s+general|government\s+accountability\s+office)\b", lowered):
        add("uscode_audit_oversight_surface")
    if re.search(r"\b(?:reports?\s+to\s+congress|submit\s+reports?|transmit\s+.+\breport|report\s+on\s+use)\b", lowered):
        add("uscode_report_to_congress_surface")
    if re.search(r"\b(?:relationship\s+to\s+other\s+law|shall\s+not\s+affect|not\s+affect\s+any\s+other\s+provision)\b", lowered):
        add("uscode_law_relationship_surface")
    if re.search(r"\b(?:general\s+eligibility|eligibility\s+requirements?|may\s+be\s+issued\s+under\s+this\s+chapter\s+only\s+if)\b", lowered):
        add("uscode_eligibility_condition_surface")
    if re.search(r"\b(?:eligibility\s+for\s+services|congregate\s+services|professional\s+assessment\s+committee)\b", lowered):
        add("uscode_service_eligibility_surface")
    if re.search(r"\b(?:recreational\s+equipment|sport\s+fishing\s+equipment|manufacturers?\s+excise\s+tax(?:es)?|miscellaneous\s+excise\s+tax(?:es)?)\b", lowered):
        add("uscode_excise_tax_surface")
    if re.search(r"\b(?:grievances?\s+concerning\s+former|former\s+(?:members?|employees?)\s+of\s+the\s+(?:service|department)|foreign\s+service\s+grievance)\b", lowered):
        add("uscode_grievance_review_surface")
    if re.search(r"\b(?:seal\s+of\s+department|seal\s+of\s+office|judicial\s+notice\s+shall\s+be\s+taken|judicial\s+notice)\b", lowered):
        add("uscode_official_seal_surface")
    if re.search(r"\bseverability\b", lowered):
        add("uscode_severability_surface")
    if re.search(r"\b(?:management\s+and\s+disposition\s+of\s+vessels|disposition\s+of\s+vessels\s+and\s+other\s+property|arising\s+out\s+of\s+fishery\s+loans?)\b", lowered):
        add("uscode_property_disposition_surface")
    if re.search(
        r"\b(?:radiotelephone\s+(?:equipped\s+ships?|station|installation)|"
        r"radiotelegraph\s+station|distress\s+and\s+safety\s+of\s+navigation|"
        r"minimum\s+normal\s+range|source\s+of\s+electrical\s+energy)\b",
        lowered,
    ):
        add("uscode_radiotelephone_ship_equipment_surface")
    if re.search(
        r"\b(?:penalt(?:y|ies)|civil\s+penalt(?:y|ies)|liable)\b",
        lowered,
    ) and re.search(
        r"\b(?:vessels?|operated\s+in\s+violation|regulation\s+prescribed|"
        r"violation\s+of\s+this\s+chapter)\b",
        lowered,
    ):
        add("uscode_vessel_violation_penalty_surface")
    if re.search(
        r"\b(?:expand(?:ed|s|ing)?|expansion)\b.{0,100}"
        r"\b(?:naval\s+facilit(?:y|ies)|model\s+basin|carderock)\b|"
        r"\b(?:naval\s+facilit(?:y|ies)|model\s+basin|carderock)\b.{0,100}"
        r"\b(?:expand(?:ed|s|ing)?|expansion|construction|installation)\b",
        lowered,
    ):
        add("uscode_naval_facility_expansion_surface")
    if re.search(
        r"\b(?:higher\s+education\s+resources|student\s+assistance|"
        r"developing\s+institutions?|minority\s+science\s+and\s+engineering)\b",
        lowered,
    ):
        add("uscode_higher_education_program_surface")
    if re.search(
        r"\b(?:education\s+sciences\s+reform|education\s+research|"
        r"education\s+statistics|research,\s+statistics,\s+evaluation,\s+"
        r"information,\s+and\s+dissemination|information\s+and\s+dissemination)\b",
        lowered,
    ):
        add("uscode_education_research_statistics_surface")
    if re.search(r"\b(?:amendments?|struck\s+out|inserted|substituted|redesignated|reclassified)\b", lowered):
        add("uscode_amendment_operation_surface")
    if re.search(r"\b(?:receiving\s+loan\s+from\s+court\s+officer|court\s+officer|receiver|receivership)\b", lowered):
        add("uscode_court_officer_receivership_surface")
    if re.search(r"\b(?:independent\s+living|vocational\s+rehabilitation|rehabilitation\s+services)\b", lowered):
        add("uscode_rehabilitation_service_surface")
    if re.search(r"\b(?:patents?\s+for\s+designs?|ornamental\s+design)\b", lowered):
        add("uscode_design_patent_surface")
    if re.search(
        r"\b(?:suspended\s+tariff|service\s+contract\s+that\s+has\s+been\s+suspended|"
        r"operating\s+under\s+suspended\s+tariff|cargo\s+for\s+carriage)\b",
        lowered,
    ):
        add("uscode_suspended_tariff_service_contract_surface")
    if re.search(
        r"\b(?:registry|helen\s+keller\s+national\s+center|deaf[-\s]+blind)\b",
        lowered,
    ):
        add("uscode_registry_record_surface")
    if re.search(
        r"\b(?:definitions?|defined|means|includes?)\b",
        lowered,
    ) and re.search(
        r"\b(?:child\s+abduction|remed(?:y|ies)|convention|central\s+authority)\b",
        lowered,
    ):
        add("uscode_child_abduction_definition_surface")
    if re.search(
        r"\b(?:construction\s+contracts?|architect\s+of\s+the\s+capitol)\b",
        lowered,
    ):
        add("uscode_construction_contract_surface")
    if re.search(
        r"\b(?:measurement|assign(?:s|ed)?\s+(?:a\s+)?length|"
        r"length\s+means\s+the\s+horizontal\s+distance|"
        r"horizontal\s+distance\s+of\s+the\s+hull|foremost\s+part\s+of\s+the\s+stem|"
        r"aftermost\s+part\s+of\s+the\s+stern)\b",
        lowered,
    ):
        add("uscode_measurement_assignment_surface")
    if re.search(
        r"\b(?:transferred|editorial\s+notes|codification|reclassified)\b",
        lowered,
    ):
        add("uscode_transfer_status_surface")
    if re.search(
        r"\b(?:members?\s+of\s+congress|the\s+congress)\b.{0,120}"
        r"\b(?:compensation|allowances?)\b|"
        r"\b(?:compensation|allowances?)\b.{0,120}"
        r"\b(?:members?\s+of\s+congress|the\s+congress)\b",
        lowered,
    ) and re.search(r"\brepealed\b", lowered):
        add("uscode_congress_member_compensation_repealed_surface")
    if re.search(
        r"\b(?:authorization\s+of\s+appropriations|authorized\s+to\s+be\s+appropriated|"
        r"appropriations\s+are\s+authorized)\b",
        lowered,
    ) and re.search(
        r"\b(?:national\s+military\s+parks?|national\s+parks?|fiscal\s+years?|"
        r"such\s+sums\s+as\s+may\s+be\s+necessary)\b",
        lowered,
    ):
        add("uscode_national_park_appropriation_authorization_surface")
    if re.search(r"\bnational\s+security\s+act\s+of\s+1947\b", lowered) and re.search(
        r"\b(?:reclassified|transferred|codification)\b",
        lowered,
    ):
        add("uscode_national_security_reclassification_surface")
    if re.search(r"\bcapitol\s+visitor\s+center\b", lowered):
        add("uscode_capitol_visitor_center_surface")
    if re.search(r"\b(?:job\s+corps|workforce\s+investment\s+systems?)\b", lowered):
        add("uscode_job_corps_program_status_surface")
    if re.search(
        r"\b(?:north\s+american\s+wetlands\s+conservation|wetlands\s+conservation\s+projects?|"
        r"migratory\s+birds?|waterfowl|report\s+to\s+congress|biennial\s+assessment|"
        r"annual\s+assessment)\b",
        lowered,
    ):
        add("uscode_wetlands_conservation_report_surface")
    if re.search(
        r"\b(?:nutrition\s+monitoring|food\s+intakes?|food\s+consumption\s+survey|"
        r"nutrient\s+data\s+base|nutritional\s+and\s+dietary\s+status)\b",
        lowered,
    ):
        add("uscode_nutrition_monitoring_surface")
    if re.search(
        r"\b(?:endangered\s+species|fish\s+and\s+wildlife|"
        r"protection\s+and\s+conservation\s+of\s+wildlife)\b",
        lowered,
    ) and re.search(r"\b(?:omitted|secs?\.?|sections?)\b", lowered):
        add("uscode_wildlife_omitted_status_surface")
    if re.search(
        r"\b(?:obligations?\s+of\s+public\s+housing\s+agenc(?:y|ies)|"
        r"public\s+housing\s+agenc(?:y|ies)|low[-\s]+income\s+housing\s+projects?)\b",
        lowered,
    ) and re.search(
        r"\b(?:obligations?|full\s+faith\s+and\s+credit|pledged\s+as\s+security|"
        r"contestability|tax\s+exemption|exempt\s+from\s+taxation)\b",
        lowered,
    ):
        add("uscode_public_housing_obligation_security_surface")
    if re.search(
        r"\b(?:everglades\s+national\s+park|national\s+parks?|"
        r"monuments?\s+and\s+seashores?)\b",
        lowered,
    ) and re.search(r"\b(?:limitation\s+(?:of|on)\s+fees?|fees?)\b", lowered):
        add("uscode_national_park_fee_limitation_surface")
    if re.search(
        r"\b(?:preservation\s+of\s+friendly\s+foreign\s+relations|"
        r"friendly\s+foreign\s+relations)\b",
        lowered,
    ):
        add("uscode_friendly_foreign_relations_status_surface")
    if re.search(
        r"\b(?:nonmailable\s+matter|deposits?\s+in\s+(?:the\s+)?mail\s+any\s+matter|"
        r"postal\s+matter)\b",
        lowered,
    ) and re.search(r"\b(?:penalt(?:y|ies)|shall\s+be\s+subject)\b", lowered):
        add("uscode_postal_nonmailable_penalty_surface")
    if re.search(
        r"\b(?:exceptions?\s+from\s+operation|excepted\s+from\s+the\s+operation|"
        r"tracts?\s+or\s+parcels?\s+of\s+land|accretions\s+thereto|"
        r"resources\s+therein|improvements\s+thereon)\b",
        lowered,
    ):
        add("uscode_land_operation_exception_surface")
    if re.search(
        r"\b(?:additional\s+distribution|additional\s+copies\s+of\s+supplements|"
        r"code\s+of\s+laws\s+of\s+the\s+united\s+states|"
        r"district\s+of\s+columbia\s+code)\b",
        lowered,
    ):
        add("uscode_code_supplement_distribution_surface")
    if re.search(
        r"\b(?:enforcement\s+by\s+the\s+board|board\s+may\s+bring\s+a\s+civil\s+action|"
        r"enjoin\s+a\s+rail\s+carrier|rail\s+carrier\s+from\s+violating|"
        r"regulation\s+prescribed\s+or\s+order\s+or\s+certificate\s+issued)\b",
        lowered,
    ):
        add("uscode_board_enforcement_surface")
    if re.search(
        r"\b(?:juvenile\s+justice|delinquency\s+prevention|"
        r"justice\s+system\s+improvement)\b",
        lowered,
    ):
        add("uscode_juvenile_justice_program_surface")
    if re.search(
        r"\b(?:allotments?\s+to\s+(?:eligible\s+)?states?|"
        r"states?\s+to\s+establish\s+programs?|"
        r"health\s+and\s+safety\s+of\s+children|child\s+care\s+services?)\b",
        lowered,
    ) and re.search(r"\b(?:secretary|states?|children|child\s+care)\b", lowered):
        add("uscode_child_care_state_allotment_surface")
    if re.search(
        r"\b(?:coast\s+guard\s+child\s+care|"
        r"coast\s+guard\s+family\s+support,\s+child\s+care,\s+and\s+housing|"
        r"family\s+support,\s+child\s+care,\s+and\s+housing)\b",
        lowered,
    ):
        add("uscode_coast_guard_child_care_surface")
    if re.search(
        r"\b(?:state\s+water\s+pollution\s+control\s+revolving\s+funds?|"
        r"water\s+pollution\s+control\s+revolving\s+fund|"
        r"construction\s+of\s+treatment\s+works|"
        r"implementation\s+of\s+management\s+programs)\b",
        lowered,
    ):
        add("uscode_water_pollution_revolving_fund_surface")
    if re.search(
        r"\b(?:adverse\s+actions?|suspension|removal)\b",
        lowered,
    ) and re.search(
        r"\b(?:employees?|advance\s+written\s+notice|reasonable\s+time\s+to\s+answer|"
        r"represented\s+by\s+an\s+attorney)\b",
        lowered,
    ):
        add("uscode_employee_adverse_action_surface")
    if re.search(
        r"\b(?:machinery|material|equipment|supplies)\b",
        lowered,
    ) and re.search(
        r"\b(?:printing|binding|blank[-\s]+book|lithograph|photolithograph|"
        r"government\s+agenc(?:y|ies))\b",
        lowered,
    ):
        add("uscode_government_printing_equipment_surface")
    if re.search(
        r"\b(?:payments?|payment\s+adjustment|make\s+payments?|"
        r"adjust(?:ment|ed|s)?\s+payments?)\b",
        lowered,
    ) and re.search(
        r"\b(?:secretary|rural\s+development|grants?|program)\b",
        lowered,
    ):
        add("uscode_program_payment_adjustment_surface")
    if re.search(
        r"\b(?:project\s+safe\s+neighborhoods?|crime\s+control\s+and\s+law\s+enforcement|"
        r"law\s+enforcement\s+matters?)\b",
        lowered,
    ):
        add("uscode_project_safe_neighborhoods_surface")
    if re.search(
        r"\b(?:service[-\s]+connected\s+disabilit(?:y|ies)|veterans?'?\s+benefits?|"
        r"compensation\s+for\s+service[-\s]+connected\s+disabilit(?:y|ies))\b",
        lowered,
    ):
        add("uscode_veterans_disability_compensation_surface")
    if re.search(
        r"\b(?:sub[-\s]+saharan\s+africa|trade\s+benefits?|"
        r"economic\s+development\s+related\s+issues?)\b",
        lowered,
    ):
        add("uscode_sub_saharan_trade_benefit_surface")
    if re.search(
        r"\b(?:advisory\s+board\s+on\s+missing\s+children|missing\s+children)\b",
        lowered,
    ) and re.search(r"\b(?:repealed|pub\.|public\s+law)\b", lowered):
        add("uscode_missing_children_repealed_advisory_surface")
    if re.search(
        r"\b(?:advances?\s+by\s+government|complete\s+government\s+reclamation\s+projects?|"
        r"reclamation\s+projects?\s+begun|secretary\s+of\s+the\s+treasury)\b",
        lowered,
    ):
        add("uscode_reclamation_project_advance_surface")
    if re.search(
        r"\b(?:public\s+buildings?\s+and\s+works?|public\s+buildings?,\s+grounds,\s+and\s+parks|"
        r"laborers?\s+and\s+mechanics?|rate\s+of\s+wages?)\b",
        lowered,
    ):
        add("uscode_public_building_wage_standard_surface")
    if re.search(
        r"\b(?:coordination\s+of\s+administration|special(?:ly)?\s+adapted\s+housing)\b",
        lowered,
    ):
        add("uscode_special_housing_coordination_surface")
    if re.search(
        r"\b(?:crisis\s+counseling\s+assistance|crisis\s+counseling\s+training|"
        r"professional\s+counseling\s+services|mental\s+health\s+organizations?)\b",
        lowered,
    ):
        add("uscode_crisis_counseling_assistance_surface")
    if re.search(
        r"\b(?:ready\s+reserve|muster\s+duty|reserve\s+muster)\b",
        lowered,
    ):
        add("uscode_ready_reserve_muster_duty_surface")
    if re.search(
        r"\b(?:racial\s+discrimination|agricultural\s+and\s+mechanical\s+colleges?|"
        r"college[-\s]+aid\s+annual\s+appropriation)\b",
        lowered,
    ):
        add("uscode_college_racial_discrimination_surface")
    if re.search(
        r"\b(?:drug[-\s]+free\s+communities|drug[-\s]+free\s+communities\s+support\s+program|"
        r"national\s+drug\s+control\s+program)\b",
        lowered,
    ):
        add("uscode_drug_free_communities_support_surface")
    if re.search(
        r"\b(?:supplemental\s+grants?|additional\s+preventive\s+health\s+services?|"
        r"preventive\s+health\s+services?|demonstration\s+projects?)\b",
        lowered,
    ) and re.search(r"\b(?:secretary|director|centers?\s+for\s+disease|states?|grants?)\b", lowered):
        add("uscode_preventive_health_grant_surface")
    if re.search(
        r"\b(?:medical\s+officer\s+of\s+the\s+marine\s+corps|"
        r"headquarters,\s+marine\s+corps|marine\s+corps\b.{0,80}\bmedical\s+officer)\b",
        lowered,
    ):
        add("uscode_marine_corps_medical_officer_surface")
    if re.search(
        r"\b(?:vacant\s+military\s+posts?|military\s+posts?\s+or\s+barracks|"
        r"barracks\s+for\s+schools?|detail\s+of\s+army\s+officers?)\b",
        lowered,
    ):
        add("uscode_military_post_school_use_surface")
    if re.search(
        r"\b(?:wildlife|migratory\s+birds?|fish\s+and\s+wildlife|"
        r"conservation\s+order|hunting\s+regulations?)\b",
        lowered,
    ) and re.search(r"\b(?:shall|may|order|secretary|regulations?)\b", lowered):
        add("uscode_wildlife_conservation_order_surface")
    if re.search(
        r"\b(?:public\s+housing\s+agenc(?:y|ies)|low[-\s]+income\s+housing|"
        r"housing\s+assistance|assistance\s+payments?)\b",
        lowered,
    ):
        add("uscode_public_housing_assistance_surface")
    if re.search(
        r"\b(?:public\s+charter\s+schools?|charter\s+school\s+program|"
        r"programs?\s+of\s+national\s+significance)\b",
        lowered,
    ):
        add("uscode_public_charter_school_program_surface")
    if re.search(
        r"\b(?:agreement\s+with\s+murray\s+county|national\s+military\s+park)\b",
        lowered,
    ) and re.search(r"\bagreements?\b", lowered):
        add("uscode_military_park_agreement_surface")
    if re.search(
        r"\bagreements?\b.{0,120}\bpublic\s+corporation\b|"
        r"\bpublic\s+corporation\b.{0,120}\bagreements?\b",
        lowered,
    ):
        add("uscode_public_corporation_agreement_surface")
    if re.search(
        r"\b(?:loan\s+guaranty|loan\s+guarantee|loan\s+guaranty\s+and\s+insurance|"
        r"powers?\s+of\s+secretary)\b",
        lowered,
    ) and re.search(
        r"\b(?:indians?|indian\s+organizations?|secretary|loan)\b",
        lowered,
    ):
        add("uscode_indian_loan_guaranty_power_surface")
    if re.search(
        r"\bremed(?:y|ies)\s+as\s+cumulative\b|"
        r"\bremed(?:y|ies)\s+provided\s+under\s+this\s+part\b|"
        r"\bin\s+addition\s+to\s+remed(?:y|ies)\b|"
        r"\bremed(?:y|ies)\s+existing\s+under\s+another\s+law\b",
        lowered,
    ):
        add("uscode_cumulative_remedies_surface")
    if re.search(
        r"\bcuyahoga\s+valley\s+national\s+park\b",
        lowered,
    ) and re.search(r"\b(?:repealed|editorial\s+notes|codification)\b", lowered):
        add("uscode_cuyahoga_valley_national_park_repealed_surface")
    if re.search(
        r"\b(?:title\s+52,\s+voting\s+and\s+elections|"
        r"editorially\s+reclassified\s+as\s+section\s+20504)\b",
        lowered,
    ):
        add("uscode_voting_elections_reclassification_surface")
    if re.search(
        r"\b(?:flood\s+insurance\s+rate\s+maps?|flood\s+mapping\s+program|"
        r"technical\s+mapping\s+advisory\s+council)\b",
        lowered,
    ):
        add("uscode_flood_map_certification_surface")
    if re.search(
        r"\b(?:national\s+strategic\s+uranium\s+reserve|natural\s+uranium|"
        r"uranium\s+equivalents?|uranium\s+reserve)\b",
        lowered,
    ):
        add("uscode_uranium_reserve_surface")
    if re.search(
        r"\b(?:injunctions?\s+during\s+national\s+emergenc(?:y|ies)|"
        r"conciliation\s+of\s+labor\s+disputes?|labor\s+disputes?)\b",
        lowered,
    ):
        add("uscode_labor_dispute_injunction_surface")
    if re.search(r"\bomitted\b", lowered) and re.search(
        r"\b(?:editorial\s+notes|codification)\b",
        lowered,
    ):
        add("uscode_omitted_codification_surface")
    return profiles


def _typed_decompiler_family_pair_role_topology_slots(
    *,
    source_family: str,
    target_family: str,
    roles: Mapping[str, str],
    temporal_cues: Sequence[str],
    condition_cues: Sequence[str],
    has_temporal_scope: bool,
) -> List[Tuple[str, str]]:
    """Emit pair-specific role topology preserved by the typed decompiler."""
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    if not source or not target:
        return []

    role_parts = [
        role
        for role in ("subject", "action", "object")
        if _clean_text(roles.get(role, ""))
    ]
    normalized_temporal_cues = _unique_text_values(
        _clean_text(cue).lower().replace(" ", "_")
        for cue in (*temporal_cues, *condition_cues)
        if _clean_text(cue)
    )
    temporal_scope_cues = [
        cue
        for cue in normalized_temporal_cues
        if cue in _TEMPORAL_BRIDGE_CONTEXT_TOKENS
        or _temporal_clause_prefix_relation(cue)
        or cue in {
            "calendar_year",
            "effective_date",
            "fiscal_year",
            "no_later_than",
            "not_later_than",
            "on_and_after",
            "on_or_after",
            "thereafter",
            "year_thereafter",
        }
    ]
    if (
        has_temporal_scope
        or _clean_text(roles.get("temporal", ""))
        or temporal_scope_cues
    ) and "temporal" not in role_parts:
        role_parts.append("temporal")
    if not role_parts:
        return []

    pair = f"{source}->{target}"
    role_signature = "+".join(role_parts)
    bridge_value = f"{pair}:{role_signature}"
    slots: List[Tuple[str, str]] = [
        ("typed-decompiler-family-pair-role-topology", bridge_value),
        ("typed-decompiler-family-pair-bridge", bridge_value),
        (
            "typed-decompiler-family-pair-role-count",
            f"{pair}:{len(role_parts)}",
        ),
        (
            "family_semantic_slot_prototype",
            f"{source}||slot:typed-decompiler-family-pair-bridge:{bridge_value}",
        ),
        (
            "family_semantic_slot_prototype",
            f"{target}||slot:typed-decompiler-family-pair-bridge:{bridge_value}",
        ),
    ]
    for role in role_parts:
        role_value = _clean_text(roles.get(role, ""))
        slots.append(("typed-decompiler-family-pair-role", f"{pair}:{role}"))
        if role_value:
            slots.append(
                (
                    "typed-decompiler-family-pair-role-value",
                    f"{pair}:{role}:{role_value}",
                )
            )

    for cue in temporal_scope_cues:
        slots.extend(
            (
                ("typed-decompiler-family-pair-temporal-cue", f"{pair}:{cue}"),
                (
                    "family_semantic_slot_prototype",
                    f"{target}||slot:typed-decompiler-family-pair-temporal-cue:{pair}:{cue}",
                ),
            )
        )

    slots.extend(
        _typed_decompiler_conditional_role_binding_slots(
            source_family=source,
            target_family=target,
            roles=roles,
            has_conditioned_scope=bool(condition_cues),
        )
    )

    for view in _typed_decompiler_family_pair_legal_ir_views(source, target):
        slots.extend(
            (
                ("legal_ir_view_prototype", view),
                (
                    "semantic_slot_legal_ir_view_prototype",
                    f"slot:typed-decompiler-family-pair-bridge:{bridge_value}||{view}",
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    f"{source}||slot:typed-decompiler-family-pair-bridge:{bridge_value}||{view}",
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    f"{target}||slot:typed-decompiler-family-pair-bridge:{bridge_value}||{view}",
                ),
            )
        )
        for cue in temporal_scope_cues:
            slots.extend(
                (
                    (
                        "semantic_slot_legal_ir_view_prototype",
                        f"slot:typed-decompiler-family-pair-temporal-cue:{pair}:{cue}||{view}",
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        f"{target}||slot:typed-decompiler-family-pair-temporal-cue:{pair}:{cue}||{view}",
                    ),
                )
            )
    return _unique_slot_values(slots)


def _typed_decompiler_conditional_role_binding_slots(
    *,
    source_family: str,
    target_family: str,
    roles: Mapping[str, str],
    has_conditioned_scope: bool,
) -> List[Tuple[str, str]]:
    """Bind conditional clauses to role edges for frame-origin reconstruction."""
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    if target != "conditional_normative":
        return []

    pair = f"{source}->{target}"
    slots: List[Tuple[str, str]] = [
        ("family-role", "conditional_normative:clause"),
        ("semantic-slot", "family-role:conditional_normative:clause"),
        ("modal-transition", "conditional_normative->deontic"),
        ("typed-decompiler-family-pair-clause-role", f"{pair}:clause"),
        (
            "semantic_slot_legal_ir_view_prototype",
            "slot:family-role:conditional_normative:clause||TDFOL.prover",
        ),
        (
            "family_semantic_slot_legal_ir_view_prototype",
            (
                "conditional_normative||slot:family-role:"
                "conditional_normative:clause||TDFOL.prover"
            ),
        ),
    ]
    if has_conditioned_scope:
        slots.extend(
            (
                ("logical-variable-map", "condition:none:v_condition"),
                ("clause-topology", "surface-role-edge:condition->action"),
                ("clause-topology", "surface-role-transition:condition->subject"),
                (
                    "semantic_slot_legal_ir_view_prototype",
                    (
                        "slot:clause-topology:surface-role-edge:"
                        "condition->action||TDFOL.prover"
                    ),
                ),
            )
        )

    symbol_by_role = {
        "subject": "s",
        "action": "a",
        "object": "o",
        "temporal": "t",
    }
    for role, symbol in symbol_by_role.items():
        role_value = _slot_safe_family_pair_key(roles.get(role, ""))
        if not role_value:
            continue
        slots.extend(
            (
                (
                    "entity-binding",
                    f"source-ir-role:{role}:none:conditional_normative:{symbol}:clause",
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        "conditional_normative||slot:source-ir-role:"
                        f"{role}:{role_value}:conditional_normative:{symbol}||"
                        "knowledge_graphs.neo4j_compat"
                    ),
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        "conditional_normative||slot:source-ir-role:"
                        f"{role}:{role_value}:conditional_normative:{symbol}||"
                        "TDFOL.prover"
                    ),
                ),
            )
        )
    return _unique_slot_values(slots)


def _typed_decompiler_family_pair_role_value_slots(
    *,
    source_family: str,
    target_family: str,
    roles: Mapping[str, str],
) -> List[Tuple[str, str]]:
    """Bind recovered typed role values to each cross-family reconstruction."""
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    if not source or not target:
        return []

    pair = f"{source}->{target}"
    slots: List[Tuple[str, str]] = []
    for role in ("subject", "action", "object", "temporal"):
        value = _slot_safe_family_pair_key(roles.get(role, ""))
        if not value:
            continue
        role_value = f"{pair}:{role}:{value}"
        slots.extend(
            (
                ("typed-decompiler-family-pair-role-value", role_value),
                (
                    "semantic_slot_prototype",
                    f"slot-pair:typed-role:{role}:{value}|typed-decompiler-family-pair:{pair}",
                ),
                (
                    "family_semantic_slot_prototype",
                    f"{source}||slot-pair:typed-role:{role}:{value}|typed-decompiler-family-pair:{pair}",
                ),
                (
                    "family_semantic_slot_prototype",
                    f"{target}||slot-pair:typed-role:{role}:{value}|typed-decompiler-family-pair:{pair}",
                ),
            )
        )
        for view in _typed_decompiler_family_pair_legal_ir_views(source, target):
            slots.extend(
                (
                    ("legal_ir_view_prototype", view),
                    (
                        "semantic_slot_legal_ir_view_prototype",
                        (
                            f"slot-pair:typed-role:{role}:{value}|"
                            f"typed-decompiler-family-pair:{pair}||{view}"
                        ),
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        (
                            f"{target}||slot-pair:typed-role:{role}:{value}|"
                            f"typed-decompiler-family-pair:{pair}||{view}"
                        ),
                    ),
                )
            )
    return _unique_slot_values(slots)


def _typed_decompiler_family_pair_predicate_slots(
    *,
    source_family: str,
    target_family: str,
    text: str,
    semantic_atoms: Sequence[str],
) -> List[Tuple[str, str]]:
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    if not source or not target:
        return []

    pair = f"{source}->{target}"
    predicate_classes = _typed_decompiler_predicate_classes(
        text=text,
        semantic_atoms=semantic_atoms,
    )
    if not predicate_classes:
        return []

    family_anchors = _typed_decompiler_predicate_family_anchors(
        source_family=source,
        target_family=target,
        predicate_classes=predicate_classes,
        semantic_atoms=semantic_atoms,
    )
    view_anchors = _typed_decompiler_pair_predicate_legal_ir_views(
        source_family=source,
        target_family=target,
        predicate_classes=predicate_classes,
        semantic_atoms=semantic_atoms,
    )

    slots: List[Tuple[str, str]] = []
    for predicate_class in predicate_classes:
        value = f"{pair}:{predicate_class}"
        slots.append(("typed-decompiler-family-pair-predicate", value))
        for family in family_anchors:
            slots.append(
                (
                    "family_semantic_slot_prototype",
                    f"{family}||slot:typed-decompiler-family-pair-predicate:{value}",
                )
            )
        for view in view_anchors:
            slots.append(("legal_ir_view_prototype", view))
            slots.append(
                (
                    "semantic_slot_legal_ir_view_prototype",
                    f"slot:typed-decompiler-family-pair-predicate:{value}||{view}",
                )
            )
            for family in family_anchors:
                slots.append(
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        (
                            f"{family}||slot:typed-decompiler-family-pair-predicate:"
                            f"{value}||{view}"
                        ),
                    )
                )
    return _unique_slot_values(slots)


def _typed_decompiler_predicate_classes(
    *,
    text: str,
    semantic_atoms: Sequence[str],
) -> List[str]:
    normalized = _clean_text(text).replace("_", " ").lower()
    normalized_atoms = {
        _clean_text(atom).lower()
        for atom in semantic_atoms
        if _clean_text(atom)
    }
    classes: List[str] = []

    def add(value: str) -> None:
        if value and value not in classes:
            classes.append(value)

    if normalized_atoms.intersection(
        {
            "excess_hospital_capacity",
            "excess_hospital_capacity_reduction",
            "excess_resource_reduction",
            "complaint",
        }
    ) or any(
        atom.endswith("_defined") or atom.endswith("_definition")
        for atom in normalized_atoms
    ):
        add("statutory")
    if normalized_atoms.intersection(
        {
            "excess_hospital_capacity_reduction",
            "excess_resource_reduction",
            "statutory_amendment",
        }
    ):
        add("authorization")
    if normalized_atoms.intersection(
        {
            "proposal_prescription_duty",
            "statutory_amendment",
        }
    ):
        add("duty")

    if _statutory_scope_slots(normalized) or re.search(
        r"(?<!\w)(?:section|chapter|subchapter|paragraph|subsection|title)s?(?!\w)",
        normalized,
    ):
        add("statutory")
    if normalized_atoms.intersection(
        {
            "exemption",
            "exempt_operation",
            "liability_protection",
            "lie_detector_test",
            "lie_detector_use_prohibition",
            "employee_polygraph_protection",
            "patent_prohibition",
            "perishable_commodity_container_exemption",
            "prohibition",
            "remedy",
            "enforcement_remedy",
            "false_statement_penalty",
            "undocumented_trading_penalty",
            "statutory_violation_condition",
            "former_jeopardy_protection",
        }
    ):
        add("remedy")
    if normalized_atoms.intersection(
        {
            "admission_fee_collection",
            "active_measures_notification",
            "agricultural_commodity_set_aside",
            "appropriation_authorization",
            "commodity_set_aside",
            "commodity_value_determination",
            "cybersecurity_information_sharing",
            "conservation_area_management",
            "departmental_property_custody",
            "departmental_record_custody",
            "documentation_certificate_requirement",
            "fee_collection_authority",
            "forest_resource_reservation",
            "fund_transfer_authority",
            "funding_eligibility",
            "fiscal_year_allotment",
            "formula_grant",
            "government_publication_depository_access",
            "housing_transfer_authority",
            "information_sharing",
            "land_acquisition_authority",
            "land_donation_acceptance",
            "land_title_authority",
            "natural_area_establishment",
            "air_carrier_service_duty",
            "air_transportation_service_duty",
            "national_forest_resource",
            "national_seashore_recreation_area",
            "payment_authorization",
            "examination_cost_payment",
            "proposal_examination_payment",
            "perishable_agricultural_commodity",
            "priority_state",
            "permission",
            "clearing_bank_resolution",
            "federal_reserve_board_oversight",
            "federal_building_energy_standard",
            "technology_transfer",
            "technology_transfer_assessment",
            "trade_rule_of_law_compliance",
            "state_energy_program",
            "procedure_adoption_duty",
            "resource_availability",
            "secretary_availability",
            "retirement_home_payment",
            "state_allotment_amount",
            "state_formula_grant",
            "state_conveyance_authority",
            "surplus_housing_transfer",
            "workforce_development_program",
            "perishable_commodity_container_exemption",
            "receiver_appointment",
            "renewable_energy_tax_rate_treatment",
            "utility_ratemaking_procedure",
        }
    ):
        add("authorization")
    if normalized_atoms.intersection(
        {
            "annual_report_duty",
            "active_measures_notification",
            "accountability_responsibility",
            "budget_program_submission",
            "china_relations_oversight",
            "child_abduction_remedy",
            "consular_officer_duty_liability",
            "consular_officer_powers_duties_liabilities",
            "congressional_report_duty",
            "inventory_study_report",
            "congressional_committee_report",
            "congressional_intelligence_committee",
            "deadline_report_duty",
            "proposal_submission",
            "state_allotment_duty",
            "public_access_requirement",
            "publication_disposal_authority",
            "report_contents",
            "report_duty",
            "uranium_inventory_study",
            "study_report_duty",
            "submit_or_file",
            "interagency_coordination",
            "trade_rule_of_law_compliance",
            "office_establishment",
            "management_position_assignment",
            "naval_officer_management_assignment",
            "workforce_performance_accountability",
            "workforce_performance_reporting",
            "federal_compliance_requirement",
            "federal_building_compliance",
            "procedure_adoption_duty",
            "receiver_duty",
            "receivership_administration",
            "renewable_energy_barrier_study",
        }
    ):
        add("duty")
    if normalized_atoms.intersection(
        {
            "annual_report",
            "annual_report_duty",
            "active_measures_notification",
            "congressional_report_duty",
            "congressional_committee_report",
            "deadline_report_duty",
            "public_report_duty",
            "report_contents",
            "report_duty",
            "study_report_duty",
            "renewable_energy_barrier_study",
        }
    ):
        add("reporting")
    if normalized_atoms.intersection(
        {
            "definition",
            "active_measures_campaign",
            "agency_certification_determination",
            "child_abduction_remedy",
            "public_health_agency",
            "office_of_womens_health",
            "commodity_set_aside",
            "commodity_value_determination",
            "funding_eligibility",
            "eligibility_determination",
            "forest_resource_reservation",
            "homestead_entry_confirmation",
            "land_acquisition_authority",
            "land_donation_acceptance",
            "land_withdrawal_restoration_scope",
            "natural_area_establishment",
            "national_seashore_recreation_area",
            "national_forest_resource",
            "priority_state",
            "per_capita_ranking",
            "perishable_agricultural_commodity",
            "territorial_jurisdiction",
            "hydraulic_mining",
            "california_debris_commission",
            "material_fact_representation",
            "scienter_requirement",
            "state_energy_program",
            "federal_compliance_requirement",
            "federal_building_compliance",
            "federal_building_energy_standard",
            "state_ranking",
            "statutory_applicability",
            "statutory_chapter_applicability",
            "statutory_short_title",
            "trade_rule_of_law_compliance",
            "railroad_land_status",
            "interstate_air_transportation",
            "national_seashore_recreation_area",
            "recreation_area",
            "service_eligibility",
            "perishable_commodity_container_exemption",
            "receiver_appointment",
            "receiver_duty",
            "receivership_administration",
            "renewable_energy_barrier_study",
            "renewable_energy_project",
            "renewable_energy_tax_rate_treatment",
            "utility_ratemaking_procedure",
        }
    ):
        add("statutory")
    if normalized_atoms.intersection(
        {
            "appeal_bail_rule",
            "education_assistance_program",
            "federal_assistance_administration",
            "federal_payment_formula",
            "income_gap_multiplier",
            "international_space_station",
            "iss_research_utilization",
            "public_health_surveillance",
            "science_engineering_education_program",
            "space_science_research",
            "seaman_discharge",
            "smart_manufacturing_report",
            "wage_account_discharge",
        }
    ):
        add("duty")
    if normalized_atoms.intersection(
        {
            "federal_assistance_administration",
            "federal_payment_formula",
            "income_gap_multiplier",
            "international_space_station",
            "iss_research_utilization",
            "space_science_research",
        }
    ):
        add("program")
        add("statutory")
    if normalized_atoms.intersection(
        {
            "naval_facility_expansion",
        }
    ):
        add("authorization")
    if normalized_atoms.intersection(
        {
            "appeal_bail_rule",
            "seaman_discharge",
        }
    ):
        add("remedy")
    if normalized_atoms.intersection(
        {
            "clean_hull_administration_enforcement",
            "internal_delivery_fee_collection",
            "nato_common_funded_budget_contribution",
            "philippines_medical_assistance_authority",
        }
    ):
        add("authorization")
    if normalized_atoms.intersection(_PROGRAM_RECONSTRUCTION_ATOMS):
        add("program")
        add("statutory")
    if normalized_atoms.intersection(_ADMIN_ENFORCEMENT_RECONSTRUCTION_ATOMS):
        add("administration")
        add("duty")
    if normalized_atoms.intersection(_TEMPORAL_STATUTORY_RECONSTRUCTION_ATOMS):
        add("statutory")
        add("temporal")
    if normalized_atoms.intersection(_PROJECT_LOAN_AWARD_RECONSTRUCTION_ATOMS):
        add("authorization")
        add("program")
        add("statutory")
    if normalized_atoms.intersection(_MEASUREMENT_ASSIGNMENT_RECONSTRUCTION_ATOMS):
        add("administration")
        add("authorization")
        add("statutory")
        add("temporal")
    if normalized_atoms.intersection(_WILDLIFE_STATUS_RECONSTRUCTION_ATOMS):
        add("conservation")
        add("statutory")
        add("temporal")
    if normalized_atoms.intersection(_PACKET_000819_SEMANTIC_RECONSTRUCTION_ATOMS):
        add("administration")
        add("duty")
        add("program")
        add("statutory")
    if normalized_atoms.intersection(_PACKET_000184_USCODE_RECONSTRUCTION_ATOMS):
        add("administration")
        add("authorization")
        add("duty")
        add("statutory")
        if normalized_atoms.intersection(
            {
                "crisis_counseling_assistance",
                "crisis_counseling_training",
                "disaster_mental_health_service",
                "ready_reserve_muster_duty",
                "reserve_muster_authority",
                "student_assignment_transportation",
                "student_transportation_assignment",
            }
        ):
            add("temporal")
    if normalized_atoms.intersection(_PACKET_000188_USCODE_RECONSTRUCTION_ATOMS):
        add("authorization")
        add("duty")
        add("program")
        add("statutory")
        if normalized_atoms.intersection(
            {
                "economic_development_trade_benefit",
                "federal_reclamation_project_advance",
                "government_project_completion_advance",
                "laborer_mechanic_wage_standard",
                "missing_children_advisory_board",
                "project_safe_neighborhoods_grant",
                "public_building_work_contract",
                "service_connected_disability_compensation",
                "sub_saharan_africa_trade_benefit",
                "veterans_compensation_benefit",
            }
        ):
            add("temporal")
        if normalized_atoms.intersection(
            {
                "crime_control_enforcement_program",
                "laborer_mechanic_wage_standard",
                "missing_children_advisory_board",
                "project_safe_neighborhoods_grant",
                "public_building_work_contract",
            }
        ):
            add("reporting")
    if normalized_atoms.intersection(_PACKET_000630_USCODE_RECONSTRUCTION_ATOMS):
        add("authorization")
        add("duty")
        add("program")
        add("statutory")
        if normalized_atoms.intersection(
            {
                "army_officer_school_detail",
                "marine_corps_medical_officer",
                "marine_corps_headquarters_staff",
                "military_post_school_use",
                "public_housing_agency_assistance",
                "wildlife_conservation_order",
            }
        ):
            add("temporal")
    if normalized_atoms.intersection(_PACKET_000633_USCODE_RECONSTRUCTION_ATOMS):
        add("authorization")
        add("duty")
        add("program")
        add("statutory")
        if normalized_atoms.intersection(
            {
                "cumulative_remedy_preservation",
                "remedies_as_cumulative",
            }
        ):
            add("remedy")
        if normalized_atoms.intersection(
            {
                "agreement_military_park_authority",
                "cumulative_remedy_preservation",
                "public_corporation_agreement_authority",
                "remedies_as_cumulative",
                "service_connected_disability_compensation",
                "veterans_compensation_benefit",
            }
        ):
            add("temporal")
    if normalized_atoms.intersection(
        {
            "annual_assessment_report",
            "biennial_assessment_report",
            "congressional_report_duty",
            "wetlands_conservation_project",
        }
    ):
        add("report")
        add("epistemic")
    if normalized_atoms.intersection(
        {
            "radiotelephone_installation",
            "radiotelephone_ship_equipment_requirement",
            "reserve_energy_requirement",
        }
    ):
        add("authorization")
    if normalized_atoms.intersection(
        {
            "award_proposal_review",
            "individual_military_award",
            "medal_of_honor_award",
            "military_award_review",
        }
    ):
        add("duty")
    if normalized_atoms.intersection(
        {
            "loan_size_limitation",
            "project_loan_limit",
        }
    ):
        add("remedy")
    if normalized_atoms.intersection(
        {
            "clean_hull_administration_enforcement",
            "veterans_medical_care",
        }
    ):
        add("duty")
    if normalized_atoms.intersection(
        {
            "fiscal_year_budget_limitation",
            "internal_delivery_fee_collection",
            "nato_common_funded_budget_contribution",
            "philippines_medical_assistance_authority",
            "veterans_medical_care",
        }
    ):
        add("statutory")
    if normalized_atoms.intersection(
        {
            "expert_consultant_service_authority",
            "historic_site_preservation_designation",
            "national_historic_site_designation",
            "salvage_archeology_administration",
            "salvage_fund_use_authority",
        }
    ):
        add("authorization")
        add("program")
        add("statutory")
    if normalized_atoms.intersection(
        {
            "state_governor_consent_requirement",
            "national_guard_relocation_limit",
            "unit_relocation_withdrawal_restriction",
        }
    ):
        add("duty")
        add("remedy")
        add("statutory")
    if normalized_atoms.intersection(
        {
            "codification_transition",
            "fiscal_year_appropriation_availability",
        }
    ):
        add("statutory")
        add("reporting")
    return classes


def _typed_decompiler_predicate_family_anchors(
    *,
    source_family: str,
    target_family: str,
    predicate_classes: Sequence[str],
    semantic_atoms: Sequence[str],
) -> List[str]:
    anchors: List[str] = []

    def add(family: str) -> None:
        normalized = _clean_text(family).lower()
        if normalized and normalized not in anchors:
            anchors.append(normalized)

    add(source_family)
    add(target_family)
    for family in _typed_decompiler_semantic_atom_target_families(semantic_atoms):
        add(family)
    if "statutory" in predicate_classes:
        add("frame")
        add("temporal")
    if any(
        predicate_class in {"authorization", "duty", "remedy"}
        for predicate_class in predicate_classes
    ):
        add("deontic")
    return anchors


def _typed_decompiler_pair_predicate_legal_ir_views(
    *,
    source_family: str,
    target_family: str,
    predicate_classes: Sequence[str],
    semantic_atoms: Sequence[str],
) -> List[str]:
    views: List[str] = []

    def add(view: str) -> None:
        if view and view not in views:
            views.append(view)

    for view in _typed_decompiler_family_pair_legal_ir_views(
        source_family,
        target_family,
    ):
        add(view)
    for atom in semantic_atoms:
        for view in _legal_semantic_atom_legal_ir_views(atom):
            add(view)
    if "statutory" in predicate_classes:
        add("modal.frame_logic")
        add("knowledge_graphs.neo4j_compat")
        add("CEC.native")
    if any(
        predicate_class in {"authorization", "duty", "remedy"}
        for predicate_class in predicate_classes
    ):
        add("deontic.ir")
        add("TDFOL.prover")
    return views


def _typed_decompiler_condition_cues(
    *,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    text: str,
) -> List[str]:
    cues: List[str] = []

    def add(cue: str) -> None:
        normalized = _clean_text(cue).lower().replace(" ", "_")
        if normalized and normalized not in cues:
            cues.append(normalized)

    for clause in (*condition_values, *exception_values):
        parsed_clause = _typed_clause_slot(clause, slot="condition")
        if parsed_clause is None:
            parsed_clause = _typed_clause_slot(clause, slot="exception")
        if parsed_clause is None:
            continue
        _slot, prefix_key, _value = parsed_clause
        add(prefix_key)
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if re.search(r"(?<!\w)with\s+(?:their\s+)?consent(?!\w)", normalized_text):
        add("with_consent")
    for prefix, prefix_key in (*_CONDITION_PREFIXES, *_EXCEPTION_PREFIXES):
        if prefix_key == "under":
            continue
        if _text_contains_cue_term(normalized_text, prefix):
            add(prefix_key)
    return cues


def _typed_decompiler_target_scope_cue_views(
    *,
    cue: str,
    source_family: str,
    target_family: str,
) -> List[str]:
    """Return legal-view anchors for a typed target-family scope cue."""
    normalized_cue = _clean_text(cue).lower().replace(" ", "_")
    normalized_source = _clean_text(source_family).lower()
    normalized_target = _clean_text(target_family).lower()
    views: List[str] = []

    def add(view: str) -> None:
        if view and view not in views:
            views.append(view)

    for view in _source_scope_cue_legal_ir_views(normalized_cue):
        add(view)
    if normalized_target in {"conditional_normative", "deontic"}:
        add("deontic.ir")
        add("CEC.native")
    if normalized_target == "conditional_normative":
        add("TDFOL.prover")
    if normalized_source == "frame":
        add("knowledge_graphs.neo4j_compat")
    return views


def _has_deontic_reconstruction_cue(
    formula: ModalIRFormula,
    text: str,
) -> bool:
    force = _modal_force_label(formula)
    if force in {"permission", "obligation", "prohibition"}:
        return True
    normalized = _clean_text(text).replace("_", " ").lower()
    if not normalized:
        return False
    return bool(
        re.search(
            r"(?<!\w)(?:shall|must|may|authorized|required|prohibited|"
            r"obligated|permitted)(?!\w)",
            normalized,
        )
    )


def _semantic_role_values_from_text(text: str) -> Dict[str, str]:
    normalized = _clean_text(text).replace("_", " ").lower()
    postal_roles = _postal_matter_role_values_from_text(normalized)
    tokens = _CUE_TOKEN_RE.findall(normalized)
    if not tokens:
        return postal_roles
    modal_indices = [
        index
        for index, token in enumerate(tokens)
        if token in {"shall", "must", "may", "should", "will"}
    ]
    action_index = -1
    if modal_indices:
        action_index = modal_indices[0] + 1
    else:
        for index, token in enumerate(tokens):
            if token in _LOW_INFORMATION_SCOPE_LEADING_TOKENS:
                continue
            action_index = index
            break
    if action_index < 0 or action_index >= len(tokens):
        return {}

    stop_tokens = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "that",
        "this",
        "to",
        "with",
    }
    auxiliary_action_tokens = {
        "able",
        "allowed",
        "authorized",
        "be",
        "directed",
        "is",
        "not",
        "ordered",
        "permitted",
        "prohibited",
        "required",
        "to",
    }
    substantive_cue_action_tokens = {
        "certifies",
        "classifies",
        "declares",
        "deems",
        "determines",
        "finds",
    }
    object_break_tokens = {
        "after",
        "before",
        "by",
        "except",
        "notwithstanding",
        "section",
        "subject",
        "under",
        "unless",
        "until",
        "when",
        "where",
    }

    cue_indices = [
        index
        for index, token in enumerate(tokens)
        if token in {
            "shall",
            "must",
            "may",
            "should",
            "will",
            "authorized",
            "required",
            "permitted",
            "prohibited",
            "directed",
            "certifies",
            "classifies",
            "declares",
            "deems",
            "determines",
            "finds",
            "ordered",
        }
    ]
    cue_index = cue_indices[0] if cue_indices else -1
    action_index = -1
    if cue_index >= 0:
        if tokens[cue_index] in substantive_cue_action_tokens:
            action_index = cue_index
        else:
            for index in range(cue_index + 1, len(tokens)):
                token = tokens[index]
                if token in auxiliary_action_tokens:
                    continue
                action_index = index
                break
        if action_index < 0 and tokens[cue_index] not in auxiliary_action_tokens:
            action_index = cue_index
    else:
        for index, token in enumerate(tokens):
            if token in _LOW_INFORMATION_SCOPE_LEADING_TOKENS:
                continue
            action_index = index
            break
    if action_index < 0 or action_index >= len(tokens):
        return {}

    values: Dict[str, str] = {}
    subject_end = cue_index if cue_index >= 0 else action_index
    subject_tokens = [
        token
        for token in tokens[: max(0, subject_end)]
        if token not in stop_tokens
        and token not in object_break_tokens
        and token not in auxiliary_action_tokens
    ]
    if subject_tokens:
        values["subject"] = "_".join(subject_tokens[:6])

    action = tokens[action_index]
    if action and action not in stop_tokens:
        values["action"] = action

    object_tokens: List[str] = []
    for token in tokens[action_index + 1 :]:
        if token in object_break_tokens or token in _TEMPORAL_BRIDGE_CONTEXT_TOKENS:
            break
        if _TEMPORAL_BRIDGE_YEAR_RE.fullmatch(token):
            break
        if token in stop_tokens:
            continue
        object_tokens.append(token)
        if len(object_tokens) >= 8:
            break
    if object_tokens:
        values["object"] = "_".join(object_tokens)
    for role, value in postal_roles.items():
        if role in {"action", "object", "temporal"}:
            values[role] = value
        else:
            values.setdefault(role, value)
    return values


def _postal_matter_role_values_from_text(normalized_text: str) -> Dict[str, str]:
    """Recover actor/action/object roles for postal matter offense clauses."""
    if not normalized_text:
        return {}
    if not (
        re.search(r"\bdeposit(?:s|ed|ing)?\b", normalized_text)
        and re.search(r"\bmail\b", normalized_text)
        and re.search(r"\bmatter\b", normalized_text)
    ):
        return {}
    values: Dict[str, str] = {
        "action": "deposit",
        "object": (
            "nonmailable_mail_matter"
            if re.search(r"\bnonmailable\b", normalized_text)
            else "mail_matter"
        ),
    }
    if re.search(r"\bany\s+person\b", normalized_text):
        values["subject"] = "person"
    elif re.search(r"\bwho\b", normalized_text):
        values["subject"] = "covered_person"
    if re.search(r"\b(?:with\s+)?intent\s+to\b", normalized_text):
        values["temporal"] = "intent_scope"
    return values


def _semantic_role_values_from_arguments(arguments: Sequence[str]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    role_keys = {
        "actor": "subject",
        "agent": "subject",
        "subject": "subject",
        "action": "action",
        "verb": "action",
        "object": "object",
        "target": "object",
        "temporal": "temporal",
        "time": "temporal",
        "deadline": "temporal",
    }
    for argument in arguments:
        parsed = _typed_argument_slot(argument)
        if parsed is None:
            continue
        slot, value = parsed
        key = slot.removeprefix("argument_")
        role = role_keys.get(key)
        normalized_value = _clean_text(value).replace(" ", "_").lower()
        if role and normalized_value and role not in values:
            values[role] = normalized_value
    return values


def _typed_decompiler_bridge_target_families(
    *,
    formula: ModalIRFormula,
    text: str,
    roles: Mapping[str, str],
) -> List[str]:
    family = _clean_text(formula.operator.family).lower()
    targets: List[str] = []

    def add(target: str) -> None:
        normalized_target = _clean_text(target).lower()
        if normalized_target and normalized_target not in targets:
            targets.append(normalized_target)

    if family == "conditional_normative":
        add("conditional_normative")
        add("deontic")
    elif family == "deontic":
        add("deontic")
    elif family == "temporal":
        add("temporal")
    temporal_cues = _temporal_transition_context_cues_from_text(text)
    if "temporal" in roles or temporal_cues:
        add("temporal")
    if _dynamic_transition_context_cues_from_text(text):
        add("dynamic")
    if "subject" in roles or "object" in roles:
        add("deontic")
    text_tokens = set(_CUE_TOKEN_RE.findall(text))
    if _has_deontic_reconstruction_cue(formula, text):
        add("deontic")
    if _alethic_scope_cues_from_text(text):
        add("alethic")
    if _statutory_scope_slots(text) or text_tokens.intersection(_STRUCTURAL_FRAME_CUE_TOKENS):
        add("frame")
    for cue in _bridge_cues_from_text(text):
        for bridge_family, _bridge_symbol in _cue_bridge_operator_pairs(cue):
            add(bridge_family)
    for cue in _deontic_surface_cues_from_text(text):
        for bridge_family, _bridge_symbol in _cue_bridge_operator_pairs(cue):
            add(bridge_family)
    for bridge_family in _doxastic_bridge_families_from_text(text):
        add(bridge_family)
    if family in {"deontic", "frame"} and _uscode_residual_fallback_decompiler_cues(
        formula
    ):
        add("conditional_normative")
    if family == "frame" and _uscode_residual_fallback_decompiler_cues(formula):
        add("epistemic")
    return targets


def _source_predicate_family_pair_value(
    *,
    family: str,
    predicate_text: str,
    force: str,
    polarity: str,
) -> str:
    normalized_family = _clean_text(family).lower()
    predicate_key = _slot_safe_family_pair_key(predicate_text)
    force_key = _slot_safe_family_pair_key(force)
    polarity_key = _slot_safe_family_pair_key(polarity)
    if not normalized_family or not predicate_key:
        return ""
    if force_key and polarity_key:
        return f"{normalized_family}:{predicate_key}|{force_key}:{polarity_key}"
    return f"{normalized_family}:{predicate_key}"


def _typed_decompiler_semantic_predicate_head(
    *,
    formula: ModalIRFormula,
    reconstruction_text: str,
    semantic_atoms: Sequence[str],
) -> str:
    """Return a high-signal predicate anchor for typed decompiler slots."""
    raw_head = _typed_decompiler_predicate_head(formula)
    normalized_raw = _slot_safe_family_pair_key(raw_head)
    if normalized_raw and normalized_raw not in _LOW_INFORMATION_PREDICATE_HEAD_TOKENS:
        return normalized_raw

    normalized_text = _clean_text(reconstruction_text).replace("_", " ").lower()
    candidate_atoms = [
        _slot_safe_family_pair_key(atom)
        for atom in semantic_atoms
        if _slot_safe_family_pair_key(atom)
    ]
    for atom in candidate_atoms:
        if atom not in _LOW_INFORMATION_PREDICATE_HEAD_TOKENS:
            return atom

    role_values = _semantic_role_values_from_text(normalized_text)
    for role in ("action", "object", "subject"):
        role_value = _slot_safe_family_pair_key(role_values.get(role, ""))
        if role_value and role_value not in _LOW_INFORMATION_PREDICATE_HEAD_TOKENS:
            return role_value

    return normalized_raw


def _typed_decompiler_force_polarity_family_pair_slots(
    *,
    source_family: str,
    target_family: str,
    force: str,
    polarity: str,
) -> List[Tuple[str, str]]:
    normalized_source = _clean_text(source_family).lower()
    normalized_target = _clean_text(target_family).lower()
    force_key = _slot_safe_family_pair_key(force)
    polarity_key = _slot_safe_family_pair_key(polarity)
    if (
        not normalized_source
        or not normalized_target
        or not force_key
        or not polarity_key
    ):
        return []
    pair = f"{normalized_source}->{normalized_target}"
    force_polarity = f"{force_key}:{polarity_key}"
    return [
        ("typed-decompiler-force-polarity-family-pair", f"{force_polarity}:{pair}"),
        (
            "family_semantic_slot_legal_ir_view_prototype",
            (
                f"{normalized_source}||slot:typed-decompiler-force-polarity-family-pair:"
                f"{force_polarity}:{pair}||TDFOL.prover"
            ),
        ),
        (
            "family_semantic_slot_legal_ir_view_prototype",
            (
                f"{normalized_target}||slot:typed-decompiler-force-polarity-family-pair:"
                f"{force_polarity}:{pair}||TDFOL.prover"
            ),
        ),
        (
            "semantic_slot_legal_ir_view_prototype",
            f"slot:typed-decompiler-force-polarity:{force_polarity}:{normalized_source}||TDFOL.prover",
        ),
    ]


def _typed_decompiler_force_view_family_pair_slots(
    *,
    document: ModalIRDocument,
    source_family: str,
    target_family: str,
    force: str,
    polarity: str,
) -> List[Tuple[str, str]]:
    """Bind force/family-pair slots to legal IR view guidance."""
    normalized_source = _clean_text(source_family).lower()
    normalized_target = _clean_text(target_family).lower()
    force_key = _slot_safe_family_pair_key(force)
    polarity_key = _slot_safe_family_pair_key(polarity)
    if not normalized_source or not normalized_target or not force_key:
        return []

    pair = f"{normalized_source}->{normalized_target}"
    views = _typed_decompiler_force_view_family_pair_views(document)
    if not views:
        views = _default_force_view_family_pair_views(
            source_family=normalized_source,
            target_family=normalized_target,
        )
    if not views:
        return []

    slots: List[Tuple[str, str]] = []
    force_polarity = (
        f"{force_key}:{polarity_key}" if polarity_key else force_key
    )
    for view in views:
        slots.extend(
            (
                ("legal_ir_view_prototype", view),
                (
                    "typed-decompiler-force-view-family-pair",
                    f"{force_key}:{view}:{pair}",
                ),
                (
                    "typed-decompiler-force-polarity-view-family-pair",
                    f"{force_polarity}:{view}:{pair}",
                ),
                (
                    "semantic_slot_legal_ir_view_prototype",
                    (
                        "slot:typed-decompiler-force-view-family-pair:"
                        f"{force_key}:{pair}||{view}"
                    ),
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        f"{normalized_source}||slot:typed-decompiler-force-view-family-pair:"
                        f"{force_key}:{pair}||{view}"
                    ),
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        f"{normalized_target}||slot:typed-decompiler-force-view-family-pair:"
                        f"{force_key}:{pair}||{view}"
                    ),
                ),
            )
        )
    return _unique_slot_values(slots)


def _typed_decompiler_force_view_family_pair_views(
    document: ModalIRDocument,
) -> List[str]:
    views: List[str] = []

    def add(view: str) -> None:
        normalized = _clean_text(view)
        if normalized and normalized not in views:
            views.append(normalized)

    for entry in _autoencoder_guidance_entries(document):
        for field in ("target_view", "predicted_view", "selected_view"):
            add(str(entry.get(field) or ""))
        for view in _legal_ir_view_guidance_features(entry):
            add(view)
        for value in _string_list(entry.get("legal_ir_underrepresented_components")):
            add(value)
        component_gaps = entry.get("legal_ir_component_gaps")
        if isinstance(component_gaps, Mapping):
            ranked_gaps: List[Tuple[float, str]] = []
            for view, gap in component_gaps.items():
                try:
                    gap_value = float(gap)
                except (TypeError, ValueError):
                    continue
                if gap_value > 0:
                    ranked_gaps.append((gap_value, _clean_text(str(view))))
            for _gap, view in sorted(ranked_gaps, reverse=True):
                add(view)
    return views


def _default_force_view_family_pair_views(
    *,
    source_family: str,
    target_family: str,
) -> List[str]:
    families = {source_family, target_family}
    views: List[str] = []

    def add(view: str) -> None:
        if view not in views:
            views.append(view)

    if "deontic" in families:
        add("deontic.ir")
        add("TDFOL.prover")
        add("CEC.native")
    if "deontic" in families and source_family != target_family:
        add("knowledge_graphs.neo4j_compat")
    if "frame" in families:
        add("knowledge_graphs.neo4j_compat")
        add("CEC.native")
    return views


def _typed_decompiler_directional_target_families(source_family: str) -> List[str]:
    """Return portable decoder target families for source-family reconstruction."""
    normalized_source = _clean_text(source_family).lower()
    if not normalized_source:
        return []
    targets: List[str] = []
    for target in _SOURCE_ANCHOR_DIRECTIONAL_FAMILY_PAIR_TARGETS.get(
        normalized_source,
        (),
    ):
        normalized_target = _clean_text(target).lower()
        if normalized_target and normalized_target not in targets:
            targets.append(normalized_target)
    return targets


def _typed_decompiler_corrected_source_families(
    *,
    encoded_family: str,
    text: str,
    temporal_cues: Sequence[str],
    condition_cues: Sequence[str] = (),
    has_temporal_scope: bool = False,
) -> List[Tuple[str, str]]:
    """Classify source semantics from modal cues when a fallback encoded frame drifts."""
    normalized_family = _clean_text(encoded_family).lower()
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_family or not normalized_text:
        return []

    corrections: List[Tuple[str, str]] = []

    def add(family: str, reason: str) -> None:
        normalized_target = _clean_text(family).lower()
        normalized_reason = _slot_safe_family_pair_key(reason)
        if not normalized_target or normalized_target == normalized_family:
            return
        pair = (normalized_target, normalized_reason or normalized_target)
        if pair not in corrections:
            corrections.append(pair)

    alethic_cues = _alethic_scope_cues_from_text(normalized_text)
    if alethic_cues:
        add("alethic", "+".join(alethic_cues[:4]))

    deontic_cues = _deontic_surface_cues_from_text(normalized_text)
    if deontic_cues and normalized_family in {"frame", "temporal", "doxastic"}:
        add("deontic", "+".join(deontic_cues[:4]))

    temporal_reason_values = list(temporal_cues)
    if not temporal_reason_values:
        temporal_reason_values = [
            cue
            for cue in condition_cues
            if _temporal_clause_prefix_relation(cue)
        ]
    if temporal_reason_values or has_temporal_scope:
        add("temporal", "+".join(temporal_reason_values[:4]) or "temporal_scope")

    dynamic_reason_values = _dynamic_transition_context_cues_from_text(normalized_text)
    if dynamic_reason_values:
        add("dynamic", "+".join(dynamic_reason_values[:4]))

    return corrections


def _typed_decompiler_corrected_source_family_slots(
    *,
    encoded_family: str,
    corrected_family: str,
    reason: str,
    targets: Sequence[str],
    force: str,
    polarity: str,
    predicate_key: str,
) -> List[Tuple[str, str]]:
    """Emit source-family correction anchors without removing encoded-family slots."""
    source = _clean_text(encoded_family).lower()
    corrected = _clean_text(corrected_family).lower()
    reason_key = _slot_safe_family_pair_key(reason) or corrected
    if not source or not corrected or source == corrected:
        return []

    corrected_targets: List[str] = []

    def add_target(target: str) -> None:
        normalized = _clean_text(target).lower()
        if normalized and normalized not in corrected_targets:
            corrected_targets.append(normalized)

    add_target(corrected)
    for target in targets:
        add_target(target)
    for target in _typed_decompiler_directional_target_families(corrected):
        add_target(target)

    slots: List[Tuple[str, str]] = [
        ("typed-decompiler-source-semantic-family", corrected),
        ("typed-decompiler-source-family-correction", f"{source}->{corrected}:{reason_key}"),
        ("typed-decompiler-source-family-correction-reason", f"{corrected}:{reason_key}"),
        (
            "family_semantic_slot_prototype",
            f"{corrected}||slot:typed-decompiler-source-family-correction:{source}->{corrected}",
        ),
    ]
    if predicate_key:
        slots.append(
            (
                "typed-decompiler-source-predicate-family-correction",
                f"{source}:{predicate_key}->{corrected}",
            )
        )
    for target in corrected_targets:
        pair = f"{corrected}->{target}"
        slots.extend(
            (
                ("typed-decompiler-target-reconstruction-pair", pair),
                ("typed-decompiler-source-target-family", pair),
                (
                    "typed-decompiler-source-family-corrected-target-pair",
                    f"{source}->{pair}:{reason_key}",
                ),
            )
        )
        if predicate_key:
            slots.append(
                (
                    "typed-decompiler-source-predicate-family-pair",
                    f"{corrected}:{predicate_key}->{target}",
                )
            )
        slots.extend(
            _typed_decompiler_force_polarity_family_pair_slots(
                source_family=corrected,
                target_family=target,
                force=force,
                polarity=polarity,
            )
        )
        for view in _typed_decompiler_family_pair_legal_ir_views(corrected, target):
            slots.extend(
                (
                    ("legal_ir_view_prototype", view),
                    (
                        "typed-decompiler-target-reconstruction-view",
                        f"{pair}||{view}",
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        f"{corrected}||slot:typed-decompiler-family-pair:{pair}||{view}",
                    ),
                    (
                        "family_semantic_slot_legal_ir_view_prototype",
                        f"{target}||slot:typed-decompiler-family-pair:{pair}||{view}",
                    ),
                )
            )
    return _unique_slot_values(slots)


def _typed_decompiler_temporal_target_role_slots(
    *,
    source_family: str,
    target_family: str,
    source_symbol: str,
    roles: Mapping[str, str],
    temporal_cues: Sequence[str],
    condition_cues: Sequence[str],
    has_temporal_scope: bool,
) -> List[Tuple[str, str]]:
    """Emit temporal target anchors from typed role topology, not just cues."""
    source = _clean_text(source_family).lower()
    target = _clean_text(target_family).lower()
    if target != "temporal":
        return []

    role_names = [
        role for role in ("subject", "action", "object", "temporal") if roles.get(role)
    ]
    if not role_names and not temporal_cues and not condition_cues:
        return []

    temporal_symbol = source_symbol if source == "temporal" and source_symbol else "f"
    pair = f"{source}->temporal"
    topology = "+".join(role_names) if role_names else "temporal_scope"
    temporal_signal = "temporal"
    if temporal_cues:
        temporal_signal = "+".join(_unique_text_values(list(temporal_cues))[:4])
    elif condition_cues:
        temporal_signal = "+".join(
            _unique_text_values(
                [
                    cue
                    for cue in condition_cues
                    if _temporal_clause_prefix_relation(cue)
                ]
            )[:4]
        ) or "conditioned_temporal"
    elif has_temporal_scope:
        temporal_signal = "temporal_scope"
    elif roles.get("temporal"):
        temporal_signal = roles["temporal"]
    else:
        temporal_signal = "typed_role_temporal_target"

    slots: List[Tuple[str, str]] = [
        ("decompiler-plan", f"typed-role-temporal-target:{pair}:{topology}"),
        (
            "decompiler-plan",
            f"compiled-role:temporal:{topology}:{temporal_signal}",
        ),
        (
            "decompiler-plan",
            f"compiled-role-shape:temporal:{topology}:a{len(role_names)}",
        ),
        (
            "compiler-contract",
            f"ir-contract:temporal:ltl:{temporal_symbol}:{topology}",
        ),
        (
            "proof-obligation",
            f"decompiler-proof-slot:prove-temporal-order:{pair}:{temporal_signal}",
        ),
        (
            "semantic_slot_legal_ir_view_prototype",
            f"slot:typed-role-temporal-target:{pair}:{topology}||TDFOL.prover",
        ),
        (
            "family_semantic_slot_legal_ir_view_prototype",
            f"temporal||slot:typed-role-temporal-target:{pair}:{topology}||TDFOL.prover",
        ),
        (
            "family_semantic_slot_legal_ir_view_prototype",
            f"temporal||slot:typed-role-temporal-target:{pair}:{topology}||CEC.native",
        ),
    ]
    for role in role_names:
        role_value = _slot_safe_family_pair_key(roles.get(role, ""))
        if not role_value:
            continue
        slots.extend(
            (
                (
                    "entity-binding",
                    f"source-ir-role:{role}:none:temporal:{temporal_symbol}:clause",
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        "temporal||slot:source-ir-role:"
                        f"{role}:{role_value}:temporal:{temporal_symbol}||"
                        "knowledge_graphs.neo4j_compat"
                    ),
                ),
            )
        )
    return _unique_slot_values(slots)


def _doxastic_bridge_families_from_text(text: str) -> List[str]:
    """Detect belief/intent cues whose registry surfaces may be multi-token."""
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    targets: List[str] = []

    def add(target: str) -> None:
        if target and target not in targets:
            targets.append(target)

    if re.search(
        r"(?<!\w)(?:believe|believes|believed|believing|"
        r"knowingly|knowing(?:ly)?|"
        r"reason(?:s)?\s+to\s+believe|reasonably\s+believes|"
        r"intent\s+to|with\s+intent\s+to)(?!\w)",
        normalized_text,
    ):
        add("doxastic")
    return targets


def _typed_decompiler_family_pair_cues(
    *,
    formula: ModalIRFormula,
    text: str,
    target_family: str,
) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    normalized_target = _clean_text(target_family).lower()
    if not normalized_text or not normalized_target:
        return []

    cues: List[str] = []

    def add(cue: str) -> None:
        normalized_cue = _clean_text(cue).lower().replace(" ", "_")
        if normalized_cue and normalized_cue not in cues:
            cues.append(normalized_cue)

    has_frame_scope = bool(_statutory_scope_slots(normalized_text)) or bool(
        set(_CUE_TOKEN_RE.findall(normalized_text)).intersection(
            _STRUCTURAL_FRAME_CUE_TOKENS
        )
    )
    for cue in _deontic_surface_cues_from_text(normalized_text):
        bridge_pairs = _cue_bridge_operator_pairs(cue)
        if any(
            _clean_text(bridge_family).lower() == normalized_target
            for bridge_family, _bridge_symbol in bridge_pairs
        ):
            add(cue)

    for cue in _refined_contextual_modal_cues_from_text(formula, text=normalized_text):
        bridge_pairs = _augment_deontic_bridge_pairs(
            bridge_pairs=_refined_cue_bridge_operator_pairs(cue),
            formula_family=_clean_text(formula.operator.family).lower(),
            formula_symbol=_clean_text(formula.operator.symbol),
            cue=cue,
        )
        if any(
            _clean_text(bridge_family).lower() == normalized_target
            for bridge_family, _bridge_symbol in bridge_pairs
        ):
            add(cue)
            continue
        if normalized_target == "frame" and has_frame_scope:
            # In frame-scoped legal clauses, normative cue words in the same
            # typed span are useful evidence for an epistemic/frame correction.
            if any(
                _clean_text(bridge_family).lower()
                in {"deontic", "conditional_normative"}
                for bridge_family, _bridge_symbol in bridge_pairs
            ):
                add(cue)
        if (
            _clean_text(formula.operator.family).lower() == "frame"
            and normalized_target in {"conditional_normative", "epistemic"}
            and _uscode_residual_fallback_decompiler_cues(formula)
            and cue in _STRUCTURAL_FRAME_CUE_TOKENS
        ):
            add(cue)
    fallback_rule = _clean_text(formula.metadata.get("fallback_rule") or "").lower()
    if fallback_rule:
        add(fallback_rule)
    if (
        _clean_text(formula.operator.family).lower() == "frame"
        and normalized_target in {"conditional_normative", "epistemic"}
    ):
        for residual_cue in _uscode_residual_fallback_decompiler_cues(formula):
            add(residual_cue)
    if normalized_target == "temporal":
        for cue in _temporal_origin_cues_from_text(normalized_text):
            add(cue)
    return cues


def _uscode_residual_fallback_decompiler_cues(formula: ModalIRFormula) -> List[str]:
    metadata = formula.metadata if isinstance(formula.metadata, Mapping) else {}
    raw_values = (
        metadata.get("cue"),
        metadata.get("fallback_rule"),
    )
    cues: List[str] = []
    for raw_value in raw_values:
        cue = _clean_text(raw_value or "").lower().replace(" ", "_").strip("_")
        if not cue or not cue.startswith("uscode_residual_span"):
            continue
        if cue not in cues:
            cues.append(cue)
    return cues


def _typed_decompiler_cue_force_slots(
    *,
    formula: ModalIRFormula,
    document: ModalIRDocument | None = None,
    text: str,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
) -> List[Tuple[str, str]]:
    family = _clean_text(formula.operator.family).lower()
    if not family:
        return []
    normalized_text = _clean_text(text).replace("_", " ").lower()
    clause_text = " ".join(
        _clean_text(value).replace("_", " ").lower()
        for value in (*condition_values, *exception_values)
        if _clean_text(value)
    )
    searchable_text = " ".join(
        value for value in (normalized_text, clause_text) if value
    )
    cues: List[str] = []
    for cue in [
        *(_clean_text(cue).lower().replace(" ", "_") for cue in _formula_cues(formula)),
        *_bridge_cues_from_text(searchable_text),
    ]:
        if cue and cue not in cues:
            cues.append(cue)
    if not cues:
        return []

    role_values = _semantic_role_values_from_text(searchable_text)
    target_families = _typed_decompiler_bridge_target_families(
        formula=formula,
        text=searchable_text,
        roles=role_values,
    )
    if document is not None:
        for guided_target in _autoencoder_family_pair_target_guidance_values(
            document,
            source_family=family,
        ):
            if guided_target not in target_families:
                target_families.append(guided_target)
        for guided_target in _autoencoder_target_family_guidance_values(document):
            if guided_target not in target_families:
                target_families.append(guided_target)
    for directional_target in _typed_decompiler_directional_target_families(family):
        if directional_target not in target_families:
            target_families.append(directional_target)
    if not target_families:
        target_families = [family]
    predicate_head = _typed_decompiler_predicate_head(formula)

    slots: List[Tuple[str, str]] = []
    for cue in cues:
        cue_force = _typed_decompiler_force_for_cue(cue)
        if not cue_force:
            continue
        polarity_values = _typed_decompiler_polarities_for_cue(
            cue,
            condition_values=condition_values,
            exception_values=exception_values,
            text=searchable_text,
        )
        slots.append(("typed_decompiler_cue_force", f"{cue}:{cue_force}"))
        slots.append(("normative_polarity", f"cue-force:{cue}:{cue_force}"))
        for polarity in polarity_values:
            slots.append(
                (
                    "typed_decompiler_cue_force_polarity",
                    f"{cue}:{cue_force}:{polarity}",
                )
            )
            for target_family in target_families:
                pair = f"{family}->{target_family}"
                force_pair = f"{cue_force}:{polarity}:{pair}"
                slots.extend(
                    (
                        (
                            "typed_decompiler_cue_force_polarity_family_pair",
                            f"{cue}:{force_pair}",
                        ),
                        (
                            "typed_decompiler_source_predicate_force_pair",
                            "source-predicate-head:"
                            f"{family}:{predicate_head}|"
                            "typed-decompiler-force-polarity:"
                            f"{force_pair}",
                        ),
                    )
                )
                slots.extend(
                    _typed_decompiler_semantic_reconstruction_family_pair_slots(
                        document=document,
                        source_family=family,
                        target_family=target_family,
                        cue=cue,
                        predicate_head=predicate_head,
                        force=cue_force,
                        polarity=polarity,
                    )
                )
                slots.extend(
                    _typed_decompiler_force_polarity_family_pair_slots(
                        source_family=family,
                        target_family=target_family,
                        force=cue_force,
                        polarity=polarity,
                    )
                )
                if document is not None:
                    slots.extend(
                        _typed_decompiler_force_view_family_pair_slots(
                            document=document,
                            source_family=family,
                            target_family=target_family,
                            force=cue_force,
                            polarity=polarity,
                        )
                    )
    return _unique_slot_values(slots)


def _typed_decompiler_semantic_reconstruction_family_pair_slots(
    *,
    document: ModalIRDocument | None,
    source_family: str,
    target_family: str,
    cue: str,
    predicate_head: str,
    force: str,
    polarity: str,
) -> List[Tuple[str, str]]:
    """Preserve typed source semantics for frame-origin reconstruction."""
    normalized_source = _clean_text(source_family).lower()
    normalized_target = _clean_text(target_family).lower()
    cue_key = _slot_safe_family_pair_key(cue)
    predicate_key = _slot_safe_family_pair_key(predicate_head)
    force_key = _slot_safe_family_pair_key(force)
    polarity_key = _slot_safe_family_pair_key(polarity)
    if (
        not normalized_source
        or not normalized_target
        or not cue_key
        or not predicate_key
        or not force_key
        or not polarity_key
    ):
        return []

    pair = f"{normalized_source}->{normalized_target}"
    signature = f"{pair}:{cue_key}:{predicate_key}:{force_key}:{polarity_key}"
    slots: List[Tuple[str, str]] = [
        ("typed_decompiler_semantic_reconstruction_family_pair", pair),
        ("typed_decompiler_semantic_reconstruction_signature", signature),
        (
            "typed_decompiler_semantic_reconstruction_cue_family_pair",
            f"{pair}:{cue_key}",
        ),
        (
            "typed_decompiler_semantic_reconstruction_predicate_family_pair",
            f"{pair}:{predicate_key}",
        ),
        (
            "typed_decompiler_semantic_reconstruction_force_polarity",
            f"{pair}:{force_key}:{polarity_key}",
        ),
    ]
    if normalized_source == "frame":
        slots.append(
            (
                "frame_typed_decompiler_semantic_reconstruction_target",
                normalized_target,
            )
        )

    views = (
        _typed_decompiler_force_view_family_pair_views(document)
        if document is not None
        else []
    )
    if not views:
        views = _default_force_view_family_pair_views(
            source_family=normalized_source,
            target_family=normalized_target,
        )
    for view in views:
        slots.extend(
            (
                ("legal_ir_view_prototype", view),
                (
                    "semantic_slot_legal_ir_view_prototype",
                    (
                        "slot:typed-decompiler-semantic-reconstruction:"
                        f"{signature}||{view}"
                    ),
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        f"{normalized_source}||slot:typed-decompiler-semantic-reconstruction:"
                        f"{signature}||{view}"
                    ),
                ),
                (
                    "family_semantic_slot_legal_ir_view_prototype",
                    (
                        f"{normalized_target}||slot:typed-decompiler-semantic-reconstruction:"
                        f"{signature}||{view}"
                    ),
                ),
            )
        )
    return _unique_slot_values(slots)


def _typed_decompiler_force_for_cue(cue: str) -> str:
    normalized_cue = _clean_text(cue).lower().replace(" ", "_")
    if not normalized_cue:
        return ""
    for bridge_family, bridge_symbol in _cue_bridge_operator_pairs(normalized_cue):
        if bridge_family == "deontic":
            return _deontic_force_for_symbol(bridge_symbol)
    if normalized_cue in {"if", "unless", "provided", "provided_that"}:
        return "obligation"
    if normalized_cue in _CLAUSE_PREFIX_BRIDGE_CUES:
        return "obligation"
    return ""


def _typed_decompiler_polarities_for_cue(
    cue: str,
    *,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    text: str,
) -> List[str]:
    normalized_cue = _clean_text(cue).lower().replace(" ", "_")
    normalized_text = _clean_text(text).replace("_", " ").lower()
    polarities: List[str] = []

    def add(value: str) -> None:
        if value and value not in polarities:
            polarities.append(value)

    if normalized_cue in {"may", "authorized", "permitted"}:
        add("enabling")
    if normalized_cue in _CLAUSE_PREFIX_BRIDGE_CUES or condition_values:
        add("conditional")
    if exception_values or normalized_cue.startswith("except") or normalized_cue == "unless":
        add("excepted")
    if _has_normative_negative_scope(normalized_text):
        add("negative_scope")
    if normalized_cue in {
        "shall",
        "must",
        "obligation",
        "obligated",
        "required",
        "require",
        "requires",
        "requiring",
    }:
        add("mandatory")
    if not polarities:
        add("positive_scope")
    return polarities


def _typed_decompiler_predicate_head(formula: ModalIRFormula) -> str:
    predicate_name = _clean_text(getattr(formula.predicate, "name", "")).lower()
    tokens = _CUE_TOKEN_RE.findall(predicate_name)
    if tokens:
        return tokens[0]
    return "unnamed"


def _cue_modal_slots(
    formula: ModalIRFormula,
    *,
    cue: str,
) -> List[Tuple[str, str]]:
    return _modal_lexeme_slots(
        formula,
        cue=cue,
        slot_prefix="cue_modal",
    )


def _formula_cues(formula: ModalIRFormula) -> List[str]:
    cues: List[str] = []
    explicit_cue = _clean_text(formula.metadata.get("cue") or "")
    if explicit_cue:
        cues.append(explicit_cue)
    derived_cue = _derived_modal_cue(formula, explicit_cue=explicit_cue)
    if derived_cue:
        normalized_existing = {value.lower() for value in cues}
        if derived_cue.lower() not in normalized_existing:
            cues.append(derived_cue)
    normalized_existing = {value.lower() for value in cues}
    for temporal_prefix_cue in _temporal_prefix_cues(formula):
        if temporal_prefix_cue in normalized_existing:
            continue
        cues.append(temporal_prefix_cue)
        normalized_existing.add(temporal_prefix_cue)
    return cues


def _temporal_prefix_cues(formula: ModalIRFormula) -> List[str]:
    cues: List[str] = []
    for clause in formula.conditions:
        parsed_clause = _typed_clause_slot(clause, slot="condition")
        if parsed_clause is None:
            continue
        _, prefix_key, _ = parsed_clause
        normalized_prefix_key = _clean_text(prefix_key).lower()
        if (
            normalized_prefix_key
            and _temporal_clause_prefix_relation(normalized_prefix_key)
            and normalized_prefix_key not in cues
        ):
            cues.append(normalized_prefix_key)
    for clause in formula.exceptions:
        parsed_clause = _typed_clause_slot(clause, slot="exception")
        if parsed_clause is None:
            continue
        _, prefix_key, _ = parsed_clause
        normalized_prefix_key = _clean_text(prefix_key).lower()
        if (
            normalized_prefix_key
            and _temporal_clause_prefix_relation(normalized_prefix_key)
            and normalized_prefix_key not in cues
        ):
            cues.append(normalized_prefix_key)
    return cues


def _derived_modal_cue(
    formula: ModalIRFormula,
    *,
    explicit_cue: str,
) -> str:
    normalized_explicit = _clean_text(explicit_cue)
    if normalized_explicit and not _is_fallback_modal_cue(normalized_explicit):
        return ""
    cue_terms = _operator_cue_terms(formula)
    source_text = " ".join(
        _clean_text(value).replace("_", " ").lower()
        for value in (
            formula.predicate.name,
            *formula.conditions,
            *formula.exceptions,
        )
        if _clean_text(value)
    )
    for cue_term in cue_terms:
        normalized_term = _clean_text(cue_term).lower()
        if not normalized_term:
            continue
        if _text_contains_cue_term(source_text, normalized_term):
            return normalized_term
    operator_label = _clean_text(_resolved_modal_operator_label(formula)).lower()
    if operator_label:
        label_tokens = _CUE_TOKEN_RE.findall(operator_label)
        if label_tokens:
            return label_tokens[0]
    return ""


def _operator_cue_terms(formula: ModalIRFormula) -> List[str]:
    family = _clean_text(formula.operator.family).lower()
    symbol = _clean_text(formula.operator.symbol)
    if not family or not symbol:
        return []
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        if _clean_text(profile.family.value).lower() != family:
            continue
        for operator in profile.operators:
            if _clean_text(operator.symbol) != symbol:
                continue
            return [
                _clean_text(cue_term)
                for cue_term in operator.cue_terms
                if _clean_text(cue_term)
            ]
    return []


def _canonical_cue_operator_symbol(
    formula: ModalIRFormula,
    *,
    cue: str,
) -> str:
    family = _clean_text(formula.operator.family).lower()
    cue_value = _clean_text(cue).lower()
    if not family or not cue_value:
        return ""
    matching_symbols: List[str] = []
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        if _clean_text(profile.family.value).lower() != family:
            continue
        for operator in profile.operators:
            if any(
                _cue_matches_registry_term(cue_value, cue_term)
                for cue_term in operator.cue_terms
            ):
                symbol = _clean_text(operator.symbol)
                if symbol and symbol not in matching_symbols:
                    matching_symbols.append(symbol)
    if not matching_symbols:
        return ""
    formula_symbol = _clean_text(formula.operator.symbol)
    if formula_symbol and formula_symbol in matching_symbols:
        return formula_symbol
    return matching_symbols[0]


def _registry_cue_operator_match(
    formula: ModalIRFormula,
    *,
    cue: str,
) -> Tuple[str, str]:
    matching_pairs = _registry_cue_operator_matches(cue=cue)
    if not matching_pairs:
        return ("", "")
    formula_family = _clean_text(formula.operator.family).lower()
    formula_symbol = _clean_text(formula.operator.symbol)
    if formula_family and formula_symbol and (formula_family, formula_symbol) in matching_pairs:
        return formula_family, formula_symbol
    if formula_family:
        for profile_family, operator_symbol in matching_pairs:
            if profile_family == formula_family:
                return profile_family, operator_symbol
    return matching_pairs[0]


def _registry_cue_operator_matches(
    *,
    cue: str,
) -> List[Tuple[str, str]]:
    cue_value = _clean_text(cue).lower()
    if not cue_value:
        return []
    matching_pairs: List[Tuple[str, str]] = []
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        profile_family = _clean_text(profile.family.value).lower()
        if profile_family not in _CUE_REGISTRY_BRIDGE_FAMILIES:
            continue
        for operator in profile.operators:
            if not any(
                _cue_matches_registry_term(cue_value, cue_term)
                for cue_term in operator.cue_terms
            ):
                continue
            operator_symbol = _clean_text(operator.symbol)
            if not operator_symbol:
                continue
            pair = (profile_family, operator_symbol)
            if pair not in matching_pairs:
                matching_pairs.append(pair)
    return sorted(
        matching_pairs,
        key=lambda item: (
            _CUE_REGISTRY_BRIDGE_FAMILY_PRIORITY.get(
                item[0],
                len(_CUE_REGISTRY_BRIDGE_FAMILY_PRIORITY),
            ),
            item[0],
            item[1],
        ),
    )


def _cue_bridge_operator_pairs(
    cue: str,
) -> List[Tuple[str, str]]:
    normalized_cue = _clean_text(cue).lower()
    if not normalized_cue:
        return []
    cue_key = normalized_cue.replace(" ", "_")
    candidates: List[Tuple[str, str]] = []
    candidates.extend(_registry_cue_operator_matches(cue=normalized_cue))
    candidates.extend(_CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS.get(cue_key, ()))
    unique_pairs: List[Tuple[str, str]] = []
    for family, symbol in sorted(
        candidates,
        key=lambda item: (
            _CROSS_FAMILY_BRIDGE_FAMILY_PRIORITY.get(
                item[0],
                len(_CROSS_FAMILY_BRIDGE_FAMILY_PRIORITY),
            ),
            item[0],
            item[1],
        ),
    ):
        pair = (_clean_text(family).lower(), _clean_text(symbol))
        if (
            not pair[0]
            or not pair[1]
            or pair in unique_pairs
        ):
            continue
        unique_pairs.append(pair)
    return unique_pairs


def _augment_deontic_bridge_pairs(
    *,
    bridge_pairs: Sequence[Tuple[str, str]],
    formula_family: str,
    formula_symbol: str,
    cue: str,
) -> List[Tuple[str, str]]:
    normalized_family = _clean_text(formula_family).lower()
    normalized_symbol = _clean_text(formula_symbol)
    normalized_cue = _clean_text(cue).lower()
    pairs: List[Tuple[str, str]] = []
    for family, symbol in bridge_pairs:
        normalized_pair = (_clean_text(family).lower(), _clean_text(symbol))
        if (
            not normalized_pair[0]
            or not normalized_pair[1]
            or normalized_pair in pairs
        ):
            continue
        pairs.append(normalized_pair)
    if not normalized_cue:
        return pairs
    cue_key = normalized_cue.replace(" ", "_")
    if cue_key in _DEONTIC_BRIDGE_REINFORCEMENT_CUES:
        deontic_scope_pair = ("deontic", "O")
        if deontic_scope_pair not in pairs:
            pairs.append(deontic_scope_pair)
    if (
        normalized_family == "conditional_normative"
        and normalized_symbol == "O|"
        and cue_key in _CLAUSE_PREFIX_BRIDGE_CUES
    ):
        deontic_scope_pair = ("deontic", "O")
        if deontic_scope_pair not in pairs:
            pairs.append(deontic_scope_pair)
    if (
        normalized_family == "deontic"
        and cue_key in _DEONTIC_EPISTEMIC_BRIDGE_CUES
    ):
        deontic_epistemic_pair = ("epistemic", "K")
        if deontic_epistemic_pair not in pairs:
            pairs.append(deontic_epistemic_pair)
    if (
        normalized_family == "epistemic"
        and cue_key in _EPISTEMIC_DEONTIC_BRIDGE_CUES
    ):
        epistemic_deontic_pair = ("deontic", "O")
        if epistemic_deontic_pair not in pairs:
            pairs.append(epistemic_deontic_pair)
    if (
        normalized_family == "deontic"
        and normalized_symbol in _DEONTIC_BRIDGE_REINFORCEMENT_OPERATORS
        and _temporal_clause_prefix_relation(cue_key)
    ):
        deontic_temporal_pair = ("deontic", normalized_symbol)
        if deontic_temporal_pair not in pairs:
            pairs.append(deontic_temporal_pair)
    return pairs


def _cue_matches_registry_term(
    cue_value: str,
    cue_term: str,
) -> bool:
    normalized_cue_tokens = _CUE_TOKEN_RE.findall(
        _clean_text(cue_value).replace("_", " ").lower()
    )
    normalized_term_tokens = _CUE_TOKEN_RE.findall(
        _clean_text(cue_term).replace("_", " ").lower()
    )
    return bool(normalized_cue_tokens) and normalized_cue_tokens == normalized_term_tokens


def _text_contains_cue_term(text: str, cue_term: str) -> bool:
    normalized_text = _clean_text(text).lower()
    normalized_term = _clean_text(cue_term).lower()
    if not normalized_text or not normalized_term:
        return False
    if " " in normalized_term:
        pattern = re.compile(
            rf"(?<!\w){re.escape(normalized_term)}(?!\w)",
            re.IGNORECASE,
        )
        return pattern.search(normalized_text) is not None
    token_set = set(_CUE_TOKEN_RE.findall(normalized_text))
    if normalized_term in token_set:
        return True
    if normalized_term.endswith("y"):
        plural_variant = f"{normalized_term[:-1]}ies"
        if plural_variant in token_set:
            return True
    return False


def _is_fallback_modal_cue(cue: str) -> bool:
    normalized = _clean_text(cue).lower()
    return normalized.startswith("__") and normalized.endswith("__")


def _cue_alias_slot_name(slot: str) -> str:
    normalized_slot = _clean_text(slot)
    if normalized_slot.startswith("cue_modal_"):
        return f"modal_cue_{normalized_slot[len('cue_modal_') :]}"
    if normalized_slot.startswith("cue_"):
        return f"modal_cue_{normalized_slot[len('cue_') :]}"
    return ""


def _modal_operator_feature_key(symbol: str) -> str:
    normalized_symbol = _clean_text(symbol)
    if not normalized_symbol:
        return ""
    mapped_symbol = _MODAL_OPERATOR_SYMBOL_FEATURE_KEYS.get(normalized_symbol)
    if mapped_symbol:
        return mapped_symbol
    tokens = _CUE_TOKEN_RE.findall(normalized_symbol.lower())
    if not tokens:
        return ""
    return "_".join(tokens)


def _modal_operator_pair_feature_key(
    source_symbol: str,
    target_symbol: str,
) -> str:
    source_key = _modal_operator_feature_key(source_symbol)
    target_key = _modal_operator_feature_key(target_symbol)
    if not source_key or not target_key:
        return ""
    return f"{source_key}_to_{target_key}"


def _modal_lexeme_slots(
    formula: ModalIRFormula,
    *,
    cue: str,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    cue_value = _clean_text(cue).lower()
    family = _clean_text(formula.operator.family).lower()
    symbol = _clean_text(formula.operator.symbol)
    normalized_slot_prefix = _clean_text(slot_prefix)
    if not cue_value or not family or not symbol or not normalized_slot_prefix:
        return []
    alias_prefix = ""
    if normalized_slot_prefix.endswith("_modal"):
        alias_prefix = _clean_text(normalized_slot_prefix[: -len("_modal")])
    cue_key = cue_value.replace(" ", "_")
    reinforce_deontic_self_bridge = (
        family == "deontic"
        and symbol in _DEONTIC_BRIDGE_REINFORCEMENT_OPERATORS
        and (
            cue_key in _DEONTIC_BRIDGE_REINFORCEMENT_CUES
            or bool(_temporal_clause_prefix_relation(cue_key))
        )
    )
    signature = f"{family}:{symbol}:{cue_value}"
    slots: List[Tuple[str, str]] = [
        (f"{normalized_slot_prefix}_signature", signature),
        (f"{normalized_slot_prefix}_family", family),
        (f"{normalized_slot_prefix}_operator", symbol),
        (f"{normalized_slot_prefix}_lexeme", cue_value),
    ]
    canonical_symbol = _canonical_cue_operator_symbol(formula, cue=cue_value)
    if canonical_symbol:
        slots.append(
            (f"{normalized_slot_prefix}_canonical_operator", canonical_symbol)
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_canonical_signature",
                f"{family}:{canonical_symbol}:{cue_value}",
            )
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_operator_alignment",
                "aligned" if canonical_symbol == symbol else "divergent",
            )
        )
    registry_family, registry_symbol = _registry_cue_operator_match(
        formula,
        cue=cue_value,
    )
    if registry_family and registry_symbol:
        registry_signature = f"{registry_family}:{registry_symbol}:{cue_value}"
        if registry_family == family and registry_symbol == symbol:
            registry_alignment = "aligned"
        elif registry_family == family:
            registry_alignment = "operator_shift"
        else:
            registry_alignment = "family_shift"
        slots.append((f"{normalized_slot_prefix}_registry_family", registry_family))
        slots.append((f"{normalized_slot_prefix}_registry_operator", registry_symbol))
        slots.append((f"{normalized_slot_prefix}_registry_signature", registry_signature))
        slots.append((f"{normalized_slot_prefix}_registry_alignment", registry_alignment))
        slots.append(
            (
                f"{normalized_slot_prefix}_registry_family_pair",
                f"{family}->{registry_family}",
            )
        )
        registry_family_pair_key = _slot_safe_family_pair_key(
            f"{family}->{registry_family}"
        )
        if registry_family_pair_key:
            slots.append(
                (
                    f"{normalized_slot_prefix}_registry_family_pair_key",
                    registry_family_pair_key,
                )
            )
        slots.append(
            (
                f"{normalized_slot_prefix}_registry_operator_pair",
                f"{symbol}->{registry_symbol}",
            )
        )
        registry_operator_pair_key = _modal_operator_pair_feature_key(
            symbol,
            registry_symbol,
        )
        if registry_operator_pair_key:
            slots.append(
                (
                    f"{normalized_slot_prefix}_registry_operator_pair_key",
                    registry_operator_pair_key,
                )
            )
        if registry_family != family or registry_symbol != symbol:
            bridged_value = f"{registry_symbol}:{cue_value}"
            slots.append((f"{normalized_slot_prefix}_{registry_family}", bridged_value))
            slots.append(
                (
                    f"{normalized_slot_prefix}_{registry_family}_signature",
                    registry_signature,
                )
            )
            if alias_prefix:
                slots.append(
                    (
                        f"{alias_prefix}_{registry_family}",
                        bridged_value,
                    )
                )
    for bridge_family, bridge_symbol in _augment_deontic_bridge_pairs(
        bridge_pairs=_cue_bridge_operator_pairs(cue_value),
        formula_family=family,
        formula_symbol=symbol,
        cue=cue_value,
    ):
        bridge_signature = f"{bridge_family}:{bridge_symbol}:{cue_value}"
        bridge_family_pair = f"{family}->{bridge_family}"
        bridge_family_pair_key = _slot_safe_family_pair_key(bridge_family_pair)
        bridge_operator_pair = f"{symbol}->{bridge_symbol}"
        slots.append(
            (
                f"{normalized_slot_prefix}_bridge_family_pair",
                bridge_family_pair,
            )
        )
        if bridge_family_pair_key:
            slots.append(
                (
                    f"{normalized_slot_prefix}_bridge_family_pair_key",
                    bridge_family_pair_key,
                )
            )
        slots.append(
            (
                f"{normalized_slot_prefix}_bridge_operator_pair",
                bridge_operator_pair,
            )
        )
        bridge_operator_pair_key = _modal_operator_pair_feature_key(
            symbol,
            bridge_symbol,
        )
        if bridge_operator_pair_key:
            slots.append(
                (
                    f"{normalized_slot_prefix}_bridge_operator_pair_key",
                    bridge_operator_pair_key,
                )
            )
        if alias_prefix:
            slots.append((f"{alias_prefix}_bridge_family_pair", bridge_family_pair))
            if bridge_family_pair_key:
                slots.append(
                    (f"{alias_prefix}_bridge_family_pair_key", bridge_family_pair_key)
                )
            slots.append((f"{alias_prefix}_bridge_operator_pair", bridge_operator_pair))
        if bridge_family == family and bridge_symbol == symbol:
            slots.append((f"{normalized_slot_prefix}_self_bridge_family", bridge_family))
            slots.append((f"{normalized_slot_prefix}_self_bridge_operator", bridge_symbol))
            slots.append((f"{normalized_slot_prefix}_self_bridge_signature", bridge_signature))
            if alias_prefix:
                slots.append((f"{alias_prefix}_self_bridge_family", bridge_family))
                slots.append((f"{alias_prefix}_self_bridge_operator", bridge_symbol))
                slots.append((f"{alias_prefix}_self_bridge_signature", bridge_signature))
            if not reinforce_deontic_self_bridge:
                continue
        bridge_value = f"{bridge_symbol}:{cue_value}"
        slots.append((f"{normalized_slot_prefix}_bridge_family", bridge_family))
        slots.append((f"{normalized_slot_prefix}_bridge_operator", bridge_symbol))
        slots.append((f"{normalized_slot_prefix}_bridge_signature", bridge_signature))
        slots.append((f"{normalized_slot_prefix}_bridge_{bridge_family}", bridge_value))
        if alias_prefix:
            slots.append((f"{alias_prefix}_bridge_family", bridge_family))
            slots.append((f"{alias_prefix}_bridge_operator", bridge_symbol))
            slots.append((f"{alias_prefix}_bridge_signature", bridge_signature))
            slots.append((f"{alias_prefix}_{bridge_family}", bridge_value))
    if symbol == "O|":
        conditional_normative_value = f"{symbol}:{cue_value}"
        slots.append(
            (
                f"{normalized_slot_prefix}_conditional_normative",
                conditional_normative_value,
            )
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_conditional_normative_signature",
                f"conditional_normative:{conditional_normative_value}",
            )
        )
        if alias_prefix:
            slots.append(
                (
                    f"{alias_prefix}_conditional_normative",
                    conditional_normative_value,
                )
            )
    temporal_relation = _temporal_clause_prefix_relation(cue_value)
    if temporal_relation:
        slots.append((f"{normalized_slot_prefix}_temporal_relation", temporal_relation))
    return slots


def _modal_polarity_slots(
    formula: ModalIRFormula,
    *,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    document: ModalIRDocument | None = None,
) -> List[Tuple[str, str]]:
    source_family = _clean_text(formula.operator.family).lower()
    source_operator = _clean_text(formula.operator.symbol)
    if not source_family or not source_operator:
        return []
    force = _modal_force_label(formula)
    polarity = _modal_scope_polarity(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
        document=document,
    )
    scope = "conditioned" if condition_values or exception_values else "unconditioned"
    slots: List[Tuple[str, str]] = [
        ("modal_force", force),
        ("modal_scope_polarity", polarity),
        ("modal_force_scope", f"{force}:{scope}"),
        ("modal_polarity_scope", f"{polarity}:{scope}"),
        ("modal_force_polarity", f"{force}:{polarity}"),
        ("modal_force_polarity_family", f"{force}:{polarity}:{source_family}"),
        (
            "modal_force_polarity_signature",
            f"{force}:{polarity}:{source_family}:{source_operator.lower()}:{scope}",
        ),
    ]
    if polarity == "negative_scope":
        slots.extend(
            (
                ("compiler_contract_force_polarity", f"{force}:negative_scope"),
                (
                    "compiler_contract_force_polarity_family",
                    f"{force}:negative_scope:{source_family}",
                ),
                ("normative_polarity", "negative_scope"),
                ("normative_force_polarity", f"{force}:negative_scope"),
                ("normative_force_scope", f"{force}:{scope}"),
                ("normative_polarity_scope", f"negative_scope:{scope}"),
            )
        )
    if exception_values:
        slots.extend(
            (
                ("modal_exception_scope", "excepted"),
                ("modal_force_exception_scope", f"{force}:excepted"),
                ("modal_polarity_exception_scope", f"{polarity}:excepted"),
                ("normative_polarity_scope", f"{polarity}:excepted"),
                ("normative_force_scope", f"{force}:excepted"),
                ("normative_force_exception_scope", f"{force}:excepted"),
            )
        )
        if force == "obligation":
            slots.extend(
                (
                    ("normative_polarity_scope", "mandatory:excepted"),
                    ("normative_force_scope", "mandatory:excepted"),
                )
            )
        if polarity == "negative_scope":
            slots.extend(
                (
                    (
                        "compiler_contract_force_polarity_exception",
                        f"{force}:negative_scope:excepted",
                    ),
                    (
                        "logic_view_contract_deontic_slot",
                        f"{force}:negative_scope:deontic:{source_operator.lower()}",
                    ),
                    (
                        "logic_view_contract_deontic_slot_exception",
                        f"{force}:negative_scope:excepted:deontic:{source_operator.lower()}",
                    ),
                    ("normative_polarity_scope", "negative_scope:excepted"),
                )
            )
    return _unique_slot_values(slots)


def _modal_force_label(formula: ModalIRFormula) -> str:
    symbol = _clean_text(formula.operator.symbol)
    label = _clean_text(formula.operator.label).lower()
    metadata = formula.metadata if isinstance(formula.metadata, Mapping) else {}
    guided_force = _clean_text(
        metadata.get("compiler_guidance_deontic_force")
        or metadata.get("deontic_force")
        or metadata.get("force")
        or ""
    ).lower()
    if guided_force in {"permission", "obligation", "prohibition"}:
        return guided_force
    if symbol == "P" or label in {"permission", "permitted"}:
        return "permission"
    if symbol == "F" or label in {"prohibition", "prohibited", "forbidden"}:
        return "prohibition"
    if symbol in {"O", "O|"} or label in {
        "obligation",
        "obligatory",
        "conditional_obligation",
        "conditionally obligatory",
    }:
        return "obligation"
    return label.replace(" ", "_") or symbol.lower()


def _modal_scope_polarity(
    formula: ModalIRFormula,
    *,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    document: ModalIRDocument | None = None,
) -> str:
    metadata = formula.metadata if isinstance(formula.metadata, Mapping) else {}
    guided_polarity = _clean_text(
        metadata.get("compiler_guidance_force_polarity")
        or metadata.get("force_polarity")
        or metadata.get("polarity")
        or ""
    ).lower()
    if guided_polarity in {"negative", "negative_scope", "negated"}:
        return "negative_scope"
    if guided_polarity in {"positive", "positive_scope", "affirmative"}:
        return "positive_scope"
    if _clean_text(formula.operator.symbol) == "F":
        return "negative_scope"
    source_span_text = (
        _formula_source_span_text(document=document, formula=formula)
        if document is not None
        else ""
    )
    polarity_text = " ".join(
        value
        for value in (
            _clean_text(formula.operator.label),
            _clean_text(metadata.get("cue") or ""),
            _predicate_phrase(formula),
            " ".join(_phrase_values(condition_values)),
            " ".join(_phrase_values(exception_values)),
            source_span_text,
        )
        if value
    ).lower()
    if _has_normative_negative_scope(polarity_text):
        return "negative_scope"
    return "positive_scope"


def _has_normative_negative_scope(text: str) -> bool:
    """Detect negated duties while treating deadline wording as temporal scope."""
    normalized = _clean_text(text).replace("_", " ").lower()
    if not normalized:
        return False
    temporal_neutral = re.sub(
        r"(?<!\w)(?:not|no)\s+later(?:\s+than)?(?!\w)",
        " deadline ",
        normalized,
    )
    temporal_neutral = re.sub(
        r"(?<!\w)not\s+earlier\s+than(?!\w)",
        " temporal ",
        temporal_neutral,
    )
    return bool(
        re.search(
            r"(?<!\w)(?:not|no|never|without|prohibited|forbidden)(?!\w)",
            temporal_neutral,
        )
    )


def _temporal_clause_prefix_relation(prefix_key: str) -> str:
    normalized_key = _clean_text(prefix_key).lower()
    if not normalized_key:
        return ""
    return _TEMPORAL_CLAUSE_PREFIX_RELATIONS.get(normalized_key, "")


def _text_has_prefix(text: str, prefix: str) -> bool:
    normalized_text = _clean_text(text).lower()
    normalized_prefix = _clean_text(prefix).lower()
    if not normalized_text or not normalized_prefix:
        return False
    if not normalized_text.startswith(normalized_prefix):
        return False
    if len(normalized_text) == len(normalized_prefix):
        return True
    suffix_char = normalized_text[len(normalized_prefix)]
    return not suffix_char.isalnum()


def _formula_bridge_cues(
    formula: ModalIRFormula,
    *,
    extra_clauses: Sequence[str] = (),
) -> List[str]:
    searchable_segments: List[str] = []
    predicate_text = _clean_text(formula.predicate.name).replace("_", " ").lower()
    if predicate_text:
        searchable_segments.append(predicate_text)
    searchable_segments.extend(
        _clean_text(value).replace("_", " ").lower()
        for value in (*formula.conditions, *formula.exceptions, *extra_clauses)
        if _clean_text(value)
    )
    if not searchable_segments:
        return []
    searchable_text = " ".join(searchable_segments)
    cues: List[str] = []
    for cue_key in sorted(
        _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS,
        key=lambda item: (-len(item), item),
    ):
        cue_surface = cue_key.replace("_", " ")
        if not cue_surface:
            continue
        if re.search(rf"(?<!\w){re.escape(cue_surface)}(?!\w)", searchable_text):
            cues.append(cue_key)
    return cues


def _bridge_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    candidate_cue_keys = [
        *sorted(
            _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS,
            key=lambda item: (-len(item), item),
        ),
        *_registry_bridge_cue_keys(),
    ]
    for cue_key in candidate_cue_keys:
        cue_surface = cue_key.replace("_", " ")
        if not cue_surface:
            continue
        if (
            cue_key not in cues
            and re.search(rf"(?<!\w){re.escape(cue_surface)}(?!\w)", normalized_text)
        ):
            cues.append(cue_key)
    return cues


def _deontic_surface_cues_from_text(text: str) -> List[str]:
    """Return short high-signal deontic cues omitted by generic bridge scans."""
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    negative_patterns = (
        ("shall_not", r"(?<!\w)shall\s+not(?!\w)"),
        ("must_not", r"(?<!\w)must\s+not(?!\w)"),
        ("may_not", r"(?<!\w)may\s+not(?!\w)"),
    )
    for cue_key, pattern in negative_patterns:
        if cue_key not in cues and re.search(pattern, normalized_text):
            cues.append(cue_key)
    positive_patterns = (
        ("shall", r"(?<!\w)shall(?!\w)"),
        ("must", r"(?<!\w)must(?!\w)"),
        ("may", r"(?<!\w)may(?!\w)"),
        ("authorized", r"(?<!\w)authorized(?!\w)"),
        ("required", r"(?<!\w)required(?!\w)"),
        ("permitted", r"(?<!\w)permitted(?!\w)"),
        ("prohibited", r"(?<!\w)prohibited(?!\w)"),
    )
    suppressed_positive_cues = {
        "shall" if "shall_not" in cues else "",
        "must" if "must_not" in cues else "",
        "may" if "may_not" in cues else "",
    }
    for cue_key, pattern in positive_patterns:
        if cue_key in suppressed_positive_cues:
            continue
        if cue_key not in cues and re.search(pattern, normalized_text):
            cues.append(cue_key)
    return cues


@lru_cache(maxsize=1)
def _registry_bridge_cue_keys() -> Tuple[str, ...]:
    cue_keys: set[str] = set()
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        family = _clean_text(profile.family.value).lower()
        if family not in _CUE_REGISTRY_BRIDGE_FAMILIES and family != "frame":
            continue
        for operator in profile.operators:
            for cue_term in operator.cue_terms:
                normalized_cue = _clean_text(cue_term).replace("_", " ").lower()
                if not normalized_cue:
                    continue
                cue_key = normalized_cue.replace(" ", "_")
                if cue_key in _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS:
                    continue
                if not _is_high_signal_registry_bridge_cue_key(cue_key):
                    continue
                cue_keys.add(cue_key)
    return tuple(sorted(cue_keys, key=lambda item: (-len(item), item)))


def _is_high_signal_registry_bridge_cue_key(cue_key: str) -> bool:
    if not cue_key:
        return False
    # Keep single-token additions conservative to avoid over-triggering on
    # common short words in long section-heading noise.
    return "_" in cue_key or len(cue_key) >= 6


def _contextual_modal_cues_from_text(
    formula: ModalIRFormula,
    *,
    text: str,
) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []

    candidate_terms: List[str] = []
    candidate_terms.extend(
        _clean_text(term).replace("_", " ").lower()
        for term in _operator_cue_terms(formula)
        if _clean_text(term)
    )
    candidate_terms.extend(
        cue_key.replace("_", " ").lower()
        for cue_key in _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS
        if cue_key
    )
    unique_terms = sorted(
        {
            term
            for term in candidate_terms
            if term
        },
        key=lambda item: (-len(item.split()), -len(item), item),
    )

    cues: List[str] = []
    for cue_term in unique_terms:
        if not _text_contains_cue_term(normalized_text, cue_term):
            continue
        cue_tokens = _CUE_TOKEN_RE.findall(cue_term)
        if not cue_tokens:
            continue
        cue_key = "_".join(cue_tokens)
        if cue_key and cue_key not in cues:
            cues.append(cue_key)
    return cues


def _cue_token_stem(token: str) -> str:
    normalized = _clean_text(token).lower()
    if len(normalized) <= 3:
        return normalized
    if normalized.endswith("ies") and len(normalized) > 4:
        return f"{normalized[:-3]}y"
    if (
        normalized.endswith("es")
        and len(normalized) > 4
        and normalized[-3] in {"s", "x", "z", "h"}
    ):
        return normalized[:-2]
    if normalized.endswith("s") and len(normalized) > 4 and not normalized.endswith("ss"):
        return normalized[:-1]
    return normalized


def _text_contains_cue_term_with_stem(text: str, cue_term: str) -> bool:
    normalized_text = _clean_text(text).lower()
    normalized_term = _clean_text(cue_term).lower()
    if not normalized_text or not normalized_term:
        return False
    if _text_contains_cue_term(normalized_text, normalized_term):
        return True
    term_tokens = _CUE_TOKEN_RE.findall(normalized_term)
    if len(term_tokens) != 1:
        return False
    target_stem = _cue_token_stem(term_tokens[0])
    if not target_stem:
        return False
    token_stems = {
        _cue_token_stem(token)
        for token in _CUE_TOKEN_RE.findall(normalized_text)
        if token
    }
    return target_stem in token_stems


def _stem_refined_modal_cues_from_text(
    formula: ModalIRFormula,
    *,
    text: str,
) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    candidate_terms: List[str] = []
    candidate_terms.extend(
        _clean_text(term).replace("_", " ").lower()
        for term in _operator_cue_terms(formula)
        if _clean_text(term)
    )
    candidate_terms.extend(
        cue_key.replace("_", " ").lower()
        for cue_key in _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS
        if cue_key
    )
    unique_terms = sorted(
        {
            term
            for term in candidate_terms
            if term
        },
        key=lambda item: (-len(item.split()), -len(item), item),
    )
    cues: List[str] = []
    for cue_term in unique_terms:
        if not _text_contains_cue_term_with_stem(normalized_text, cue_term):
            continue
        cue_tokens = _CUE_TOKEN_RE.findall(cue_term)
        if not cue_tokens:
            continue
        cue_key = "_".join(cue_tokens)
        if cue_key and cue_key not in cues:
            cues.append(cue_key)
    return cues


def _structural_frame_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    for token in _CUE_TOKEN_RE.findall(normalized_text):
        if not token:
            continue
        normalized_token = token
        if normalized_token.endswith("s"):
            singular = normalized_token[:-1]
            if singular in _STRUCTURAL_FRAME_CUE_TOKENS:
                normalized_token = singular
        if (
            normalized_token in _STRUCTURAL_FRAME_CUE_TOKENS
            and normalized_token not in cues
        ):
            cues.append(normalized_token)
    return cues


@lru_cache(maxsize=1)
def _bridge_registry_cue_terms() -> tuple[str, ...]:
    terms: set[str] = set()
    supported_families = set(_CUE_REGISTRY_BRIDGE_FAMILIES)
    supported_families.add("frame")
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        profile_family = _clean_text(profile.family.value).lower()
        if profile_family not in supported_families:
            continue
        for operator in profile.operators:
            for cue_term in operator.cue_terms:
                normalized_term = _clean_text(cue_term).replace("_", " ").lower()
                if normalized_term:
                    terms.add(normalized_term)
    return tuple(
        sorted(
            terms,
            key=lambda item: (-len(item.split()), -len(item), item),
        )
    )


def _bridge_registry_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    for cue_term in _bridge_registry_cue_terms():
        if not _text_contains_cue_term(normalized_text, cue_term):
            continue
        cue_tokens = _CUE_TOKEN_RE.findall(cue_term)
        if not cue_tokens:
            continue
        cue_key = "_".join(cue_tokens)
        if cue_key and cue_key not in cues:
            cues.append(cue_key)
    return cues


def _alethic_scope_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    for cue_key in _ALETHIC_SCOPE_CUE_OPERATOR_SYMBOLS:
        cue_term = cue_key.replace("_", " ")
        if not _text_contains_cue_term(normalized_text, cue_term):
            continue
        if cue_key and cue_key not in cues:
            cues.append(cue_key)
    return cues


def _refined_cue_bridge_operator_pairs(
    cue: str,
) -> List[Tuple[str, str]]:
    normalized_cue = _clean_text(cue).lower()
    if not normalized_cue:
        return []
    pairs = _cue_bridge_operator_pairs(normalized_cue)
    alethic_symbol = _ALETHIC_SCOPE_CUE_OPERATOR_SYMBOLS.get(normalized_cue)
    if alethic_symbol and ("alethic", alethic_symbol) not in pairs:
        pairs.append(("alethic", alethic_symbol))
    if (
        normalized_cue in _STRUCTURAL_FRAME_CUE_TOKENS
        and ("frame", "Frame") not in pairs
    ):
        pairs.append(("frame", "Frame"))
    if (
        normalized_cue in _STRUCTURAL_FRAME_CUE_TOKENS
        and ("deontic", "O") not in pairs
    ):
        pairs.append(("deontic", "O"))
    if normalized_cue in _USCODE_FALLBACK_STATUS_KEYWORDS:
        if ("frame", "Frame") not in pairs:
            pairs.append(("frame", "Frame"))
        if ("deontic", "F") not in pairs:
            pairs.append(("deontic", "F"))
    unique_pairs: List[Tuple[str, str]] = []
    for family, symbol in pairs:
        normalized_family = _clean_text(family).lower()
        normalized_symbol = _clean_text(symbol)
        pair = (normalized_family, normalized_symbol)
        if not pair[0] or not pair[1] or pair in unique_pairs:
            continue
        unique_pairs.append(pair)
    return unique_pairs


def _refined_contextual_modal_cues_from_text(
    formula: ModalIRFormula,
    *,
    text: str,
) -> List[str]:
    formula_family = _clean_text(formula.operator.family).lower()
    cues: List[str] = []
    for cue in _contextual_modal_cues_from_text(formula, text=text):
        if cue and cue not in cues:
            cues.append(cue)
    for cue in _stem_refined_modal_cues_from_text(formula, text=text):
        if cue and cue not in cues:
            cues.append(cue)
    if formula_family == "temporal":
        for cue in _temporal_transition_context_cues_from_text(text):
            if cue and cue not in cues:
                cues.append(cue)
    if formula_family == "frame":
        for cue in _bridge_registry_cues_from_text(text):
            if cue and cue not in cues:
                cues.append(cue)
        for cue in _alethic_scope_cues_from_text(text):
            if cue and cue not in cues:
                cues.append(cue)
        for cue in _structural_frame_cues_from_text(text):
            if cue and cue not in cues:
                cues.append(cue)
    return cues


def _refined_contextual_modal_transition_slots(
    formula: ModalIRFormula,
    *,
    text: str,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    formula_family = _clean_text(formula.operator.family).lower()
    formula_symbol = _clean_text(formula.operator.symbol)
    if not normalized_slot_prefix or not formula_family or not formula_symbol:
        return []
    slots: List[Tuple[str, str]] = []
    for cue in _refined_contextual_modal_cues_from_text(formula, text=text):
        normalized_cue = _clean_text(cue).lower()
        if not normalized_cue:
            continue
        source_signature = f"{formula_family}:{formula_symbol}:{normalized_cue}"
        slots.extend(
            (
                (f"{normalized_slot_prefix}_refined_modal_cue", normalized_cue),
                ("refined_modal_cue", normalized_cue),
                (f"{normalized_slot_prefix}_refined_modal_signature", source_signature),
                ("refined_modal_signature", source_signature),
            )
        )
        for bridge_family, bridge_symbol in _augment_deontic_bridge_pairs(
            bridge_pairs=_refined_cue_bridge_operator_pairs(normalized_cue),
            formula_family=formula_family,
            formula_symbol=formula_symbol,
            cue=normalized_cue,
        ):
            pair = f"{formula_family}->{bridge_family}"
            operator_pair = f"{formula_symbol}->{bridge_symbol}"
            operator_pair_key = _modal_operator_pair_feature_key(
                formula_symbol,
                bridge_symbol,
            )
            bridge_signature = f"{bridge_family}:{bridge_symbol}:{normalized_cue}"
            slots.extend(
                (
                    (f"{normalized_slot_prefix}_refined_modal_family_pair", pair),
                    (f"{normalized_slot_prefix}_refined_modal_operator_pair", operator_pair),
                    (
                        f"{normalized_slot_prefix}_refined_modal_pair_cue",
                        f"{pair}:{normalized_cue}",
                    ),
                    (
                        f"{normalized_slot_prefix}_refined_modal_bridge_signature",
                        bridge_signature,
                    ),
                    ("refined_modal_family_pair", pair),
                    ("refined_modal_operator_pair", operator_pair),
                    ("refined_modal_pair_cue", f"{pair}:{normalized_cue}"),
                    ("refined_modal_bridge_signature", bridge_signature),
                    ("refined_modal_context_slot", normalized_slot_prefix),
                    ("refined_modal_context_pair", f"{normalized_slot_prefix}:{pair}"),
                )
            )
            if operator_pair_key:
                slots.extend(
                    (
                        (
                            f"{normalized_slot_prefix}_refined_modal_operator_pair_key",
                            operator_pair_key,
                        ),
                        ("refined_modal_operator_pair_key", operator_pair_key),
                    )
                )
        slots.extend(
            _refined_temporal_transition_slots(
                formula=formula,
                cue=normalized_cue,
                text=text,
                slot_prefix=normalized_slot_prefix,
            )
        )
    return _unique_slot_values(slots)


def _temporal_transition_context_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    for phrase, cue in _TEMPORAL_BRIDGE_CONTEXT_PHRASES:
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized_text):
            if cue not in cues:
                cues.append(cue)
    tokens = _CUE_TOKEN_RE.findall(normalized_text)
    token_set = set(tokens)
    for token in tokens:
        normalized_token = token[:-1] if token.endswith("s") else token
        if (
            normalized_token in _TEMPORAL_BRIDGE_CONTEXT_TOKENS
            and normalized_token not in cues
        ):
            cues.append(normalized_token)
    if _TEMPORAL_BRIDGE_YEAR_RE.search(normalized_text):
        if "year" not in cues:
            cues.append("year")
        if "edition" in token_set and "edition_year" not in cues:
            cues.append("edition_year")
    for cue in _temporal_origin_cues_from_text(normalized_text):
        if cue not in cues:
            cues.append(cue)
    return cues


def _dynamic_transition_context_cues_from_text(text: str) -> List[str]:
    """Return action-transition cues that distinguish dynamic from frame state."""
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    for token in _CUE_TOKEN_RE.findall(normalized_text):
        normalized_token = token[:-1] if token.endswith("s") else token
        for family, _symbol in _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS.get(
            normalized_token,
            (),
        ):
            if family == "dynamic" and normalized_token not in cues:
                cues.append(normalized_token)
    if re.search(
        r"\b(?:undertak(?:e|es|ing)|execut(?:e|es|ed|ing)|hold(?:s|ing)?|"
        r"enjoy(?:s|ed|ing)?)\b.{0,120}\bcontracts?\b|"
        r"\bcontracts?\b.{0,120}\b(?:undertak(?:e|es|ing)|execut(?:e|es|ed|ing)|"
        r"hold(?:s|ing)?|enjoy(?:s|ed|ing)?)\b",
        normalized_text,
    ):
        for cue in ("contract_action", "execute_contract"):
            if cue not in cues:
                cues.append(cue)
    return cues


def _temporal_origin_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    if _TEMPORAL_ORIGIN_FROM_RE.search(normalized_text):
        return ["from"]
    return []


def _refined_temporal_transition_slots(
    *,
    formula: ModalIRFormula,
    cue: str,
    text: str,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    normalized_cue = _clean_text(cue).lower()
    formula_family = _clean_text(formula.operator.family).lower()
    formula_symbol = _clean_text(formula.operator.symbol)
    if (
        not normalized_slot_prefix
        or not normalized_cue
        or not formula_symbol
        or formula_family not in {"deontic", "frame", "temporal"}
    ):
        return []
    context_cues = _temporal_transition_context_cues_from_text(text)
    temporal_relation_context = _temporal_clause_prefix_relation(normalized_cue)
    if temporal_relation_context:
        relation_context = f"{normalized_cue}:{temporal_relation_context}"
        if relation_context not in context_cues:
            context_cues.insert(0, relation_context)
    if not context_cues:
        return []
    if formula_family == "deontic":
        if (
            normalized_cue not in _DEONTIC_TEMPORAL_BRIDGE_CUES
            and not temporal_relation_context
        ):
            return []
        pair_source_family = "deontic"
    elif formula_family == "frame":
        if (
            normalized_cue not in _FRAME_TEMPORAL_BRIDGE_CUES
            and not temporal_relation_context
        ):
            return []
        pair_source_family = "frame"
    else:
        if (
            normalized_cue not in _DEONTIC_TEMPORAL_BRIDGE_CUES
            and normalized_cue not in _TEMPORAL_BRIDGE_CONTEXT_TOKENS
            and normalized_cue not in context_cues
        ):
            return []
        pair_source_family = "temporal"

    pair = f"{pair_source_family}->temporal"
    pair_key = _slot_safe_family_pair_key(pair)
    temporal_symbol = (
        formula_symbol if formula_family == "temporal" and formula_symbol else "F"
    )
    operator_pair = f"{formula_symbol}->{temporal_symbol}"
    operator_pair_key = _modal_operator_pair_feature_key(
        formula_symbol,
        temporal_symbol,
    )
    signature = f"temporal:{temporal_symbol}:{normalized_cue}"
    slots: List[Tuple[str, str]] = [
        (f"{normalized_slot_prefix}_refined_temporal_bridge_family_pair", pair),
        (f"{normalized_slot_prefix}_refined_temporal_bridge_family_pair_key", pair_key),
        (f"{normalized_slot_prefix}_refined_temporal_bridge_family_pair", pair_key),
        (f"{normalized_slot_prefix}_refined_temporal_bridge_operator_pair", operator_pair),
        (f"{normalized_slot_prefix}_refined_temporal_bridge_signature", signature),
        (
            f"{normalized_slot_prefix}_refined_temporal_bridge_pair_cue",
            f"{pair}:{normalized_cue}",
        ),
        ("refined_temporal_bridge_family_pair", pair),
        ("refined_temporal_bridge_family_pair_key", pair_key),
        ("refined_temporal_bridge_family_pair", pair_key),
        ("refined_temporal_bridge_operator_pair", operator_pair),
        ("refined_temporal_bridge_signature", signature),
        ("refined_temporal_bridge_pair_cue", f"{pair}:{normalized_cue}"),
        ("refined_temporal_bridge_context_slot", normalized_slot_prefix),
        (
            "refined_temporal_bridge_context_pair",
            f"{normalized_slot_prefix}:{pair}",
        ),
        (
            "refined_temporal_bridge_context_pair",
            f"{normalized_slot_prefix}_{pair_key}",
        ),
    ]
    if operator_pair_key:
        slots.extend(
            (
                (
                    f"{normalized_slot_prefix}_refined_temporal_bridge_operator_pair_key",
                    operator_pair_key,
                ),
                ("refined_temporal_bridge_operator_pair_key", operator_pair_key),
            )
        )
    for context_cue in context_cues:
        context_slot_alias = normalized_slot_prefix.removesuffix("_scope")
        slots.extend(
            (
                (
                    f"{normalized_slot_prefix}_refined_temporal_bridge_context",
                    context_cue,
                ),
                (
                    f"{normalized_slot_prefix}_refined_temporal_bridge_context_signature",
                    f"{signature}:{context_cue}",
                ),
                ("refined_temporal_bridge_context", context_cue),
                (
                    "refined_temporal_bridge_context",
                    f"{normalized_slot_prefix}:{context_cue}",
                ),
                (
                    "refined_temporal_bridge_context",
                    f"{context_slot_alias}:{context_cue}",
                ),
                (
                    "refined_temporal_bridge_context_signature",
                    f"{signature}:{context_cue}",
                ),
            )
        )
    if (
        formula_family == "temporal"
        and normalized_cue in _DEONTIC_TEMPORAL_BRIDGE_CUES
    ):
        deontic_pair = "deontic->temporal"
        deontic_pair_key = _slot_safe_family_pair_key(deontic_pair)
        slots.extend(
            (
                (
                    f"{normalized_slot_prefix}_refined_temporal_bridge_family_pair",
                    deontic_pair,
                ),
                (
                    f"{normalized_slot_prefix}_refined_temporal_bridge_family_pair_key",
                    deontic_pair_key,
                ),
                (
                    f"{normalized_slot_prefix}_refined_temporal_bridge_family_pair",
                    deontic_pair_key,
                ),
                (
                    f"{normalized_slot_prefix}_refined_temporal_bridge_pair_cue",
                    f"{deontic_pair}:{normalized_cue}",
                ),
                ("refined_temporal_bridge_family_pair", deontic_pair),
                ("refined_temporal_bridge_family_pair_key", deontic_pair_key),
                ("refined_temporal_bridge_family_pair", deontic_pair_key),
                ("refined_temporal_bridge_pair_cue", f"{deontic_pair}:{normalized_cue}"),
                (
                    "refined_temporal_bridge_context_pair",
                    f"{normalized_slot_prefix}:{deontic_pair}",
                ),
                (
                    "refined_temporal_bridge_context_pair",
                    f"{normalized_slot_prefix}_{deontic_pair_key}",
                ),
            )
        )
    return _unique_slot_values(slots)


def _contextual_modal_cue_phrases(
    *,
    formula: ModalIRFormula,
    text: str,
    slot_prefix: str,
    spans: List[List[int]],
) -> List[DecodedModalPhrase]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    if not normalized_slot_prefix:
        return []
    phrases: List[DecodedModalPhrase] = []
    seen: set[Tuple[str, str]] = set()
    for cue in _contextual_modal_cues_from_text(formula, text=text):
        for cue_slot, cue_value in (
            (f"{normalized_slot_prefix}_cue", cue),
            (f"{normalized_slot_prefix}_modal_cue", cue),
        ):
            marker = (cue_slot, cue_value)
            if marker in seen:
                continue
            seen.add(marker)
            phrases.append(
                DecodedModalPhrase(
                    text=cue_value,
                    slot=cue_slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        for modal_slot, modal_value in _modal_lexeme_slots(
            formula,
            cue=cue,
            slot_prefix=f"{normalized_slot_prefix}_modal",
        ):
            marker = (modal_slot, modal_value)
            if marker in seen:
                continue
            seen.add(marker)
            phrases.append(
                DecodedModalPhrase(
                    text=modal_value,
                    slot=modal_slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    for refined_slot, refined_value in _refined_contextual_modal_transition_slots(
        formula,
        text=text,
        slot_prefix=normalized_slot_prefix,
    ):
        marker = (refined_slot, refined_value)
        if marker in seen:
            continue
        seen.add(marker)
        phrases.append(
            DecodedModalPhrase(
                text=refined_value,
                slot=refined_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    return phrases


def _append_statutory_scope_phrases(
    phrases: List[DecodedModalPhrase],
    text: str,
    *,
    spans: List[List[int]],
    emitted: set[Tuple[str, str]],
) -> None:
    for slot, value in _statutory_scope_slots(text):
        marker = (slot, value)
        if marker in emitted:
            continue
        emitted.add(marker)
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    for slot, value in _statutory_condition_grounding_slots(text):
        marker = (slot, value)
        if marker in emitted:
            continue
        emitted.add(marker)
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )


def _statutory_scope_slots(text: str) -> List[Tuple[str, str]]:
    normalized = _clean_text(text).replace("_", " ").lower()
    if not normalized:
        return []
    result: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for match in _STATUTORY_SCOPE_REFERENCE_RE.finditer(normalized):
        connector = _clean_text(match.group("connector")).lower()
        unit_surface = _clean_text(match.group("unit")).lower()
        unit = _canonical_statutory_scope_unit(unit_surface)
        determiner = _clean_text(match.group("determiner")).lower()
        has_determiner = bool(determiner)
        target = _clean_text(match.group("target")).lower()
        if (
            has_determiner
            and target
            and not target.startswith("(")
            and not any(character.isdigit() for character in target)
            and _ROMAN_NUMERAL_RE.fullmatch(target) is None
        ):
            target = ""
        reference_parts = (
            [connector, determiner, unit_surface]
            if has_determiner
            else [connector, unit_surface]
        )
        if target:
            reference_parts.append(target)
        reference = " ".join(reference_parts)
        resolved_target = (
            f"{determiner} {target}".strip() if has_determiner else target
        )
        if has_determiner and not target:
            resolved_target = determiner
        values: List[Tuple[str, str]] = [
            ("statutory_scope_reference", reference),
            ("statutory_scope_connector", connector),
            ("statutory_scope_unit", unit),
            ("reference_dependency", f"direct_reference:{unit}"),
            ("reference_dependency_kind", "direct_reference"),
            ("reference_dependency_target_type", unit),
        ]
        if resolved_target:
            values.append(("statutory_scope_target", resolved_target))
            values.append(
                (
                    "reference_dependency_target",
                    f"{unit}:{resolved_target}",
                )
            )
        for slot in values:
            if slot in seen:
                continue
            seen.add(slot)
            result.append(slot)
    return result


def _statutory_condition_grounding_slots(text: str) -> List[Tuple[str, str]]:
    """Bind statutory references to conditional/deontic reconstruction cues."""
    scope_slots = _statutory_scope_slots(text)
    if not scope_slots:
        return []

    slot_map: Dict[str, List[str]] = {}
    for slot, value in scope_slots:
        slot_map.setdefault(slot, []).append(value)

    references = slot_map.get("statutory_scope_reference", [])
    connectors = slot_map.get("statutory_scope_connector", [])
    units = slot_map.get("statutory_scope_unit", [])
    targets = slot_map.get("statutory_scope_target", [])
    if not references:
        return []

    result: List[Tuple[str, str]] = []
    for index, reference in enumerate(references):
        connector = connectors[index] if index < len(connectors) else ""
        unit = units[index] if index < len(units) else ""
        target = targets[index] if index < len(targets) else ""
        if not unit:
            continue
        cue = _statutory_condition_cue_for_connector(connector)
        reference_key = _slot_safe_family_pair_key(reference)
        target_key = _slot_safe_family_pair_key(target) if target else "implicit"
        unit_key = _slot_safe_family_pair_key(unit)
        cue_key = _slot_safe_family_pair_key(cue)
        result.extend(
            (
                ("statutory_condition_reference", reference),
                ("statutory_condition_cue", cue),
                ("statutory_condition_unit", unit),
                (
                    "statutory_condition_grounding",
                    f"{cue_key}:{unit_key}:{target_key}",
                ),
                (
                    "constraint-grounding",
                    f"cross-reference-grounding:direct:{unit_key}:{target_key}:conditioned",
                ),
                (
                    "quantifier-scope",
                    f"operator-quantifier:deontic:clause:universal:conditioned:{unit_key}",
                ),
                (
                    "semantic_slot_legal_ir_view_prototype",
                    (
                        "slot:statutory-condition-grounding:"
                        f"{cue_key}:{unit_key}:{target_key}||deontic.ir"
                    ),
                ),
                (
                    "semantic_slot_legal_ir_view_prototype",
                    (
                        "slot:statutory-condition-grounding:"
                        f"{cue_key}:{unit_key}:{target_key}||TDFOL.prover"
                    ),
                ),
            )
        )
        if reference_key:
            result.extend(
                (
                    (
                        "statutory_condition_reference_key",
                        reference_key,
                    ),
                    (
                        "semantic_slot_legal_ir_view_prototype",
                        (
                            "slot:statutory-condition-reference:"
                            f"{reference_key}||CEC.native"
                        ),
                    ),
                )
            )
        if connector:
            result.append(
                (
                    "statutory_condition_connector",
                    connector,
                )
            )
        if target:
            result.append(("statutory_condition_target", target))
    return _unique_slot_values(result)


def _statutory_condition_cue_for_connector(connector: str) -> str:
    normalized = _clean_text(connector).lower()
    if normalized.startswith("except"):
        return "exception"
    if normalized in {
        "as otherwise provided in",
        "as provided in",
        "as set forth in",
        "in accordance with",
        "pursuant to",
        "subject to",
        "under",
        "within",
    }:
        return "condition"
    if normalized in {"as described in", "as defined in", "referred to in"}:
        return "definition_reference"
    return "reference"


def _canonical_statutory_scope_unit(unit: str) -> str:
    normalized = _clean_text(unit).lower()
    if normalized.endswith("s"):
        singular = normalized[:-1]
        if singular in _STATUTORY_SCOPE_UNITS:
            return singular
    return normalized


def _alpha_case_kind(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    letters = "".join(character for character in cleaned if character.isalpha())
    if not letters:
        return ""
    if letters.islower():
        return "lower"
    if letters.isupper():
        return "upper"
    return "mixed"


def _suffix_profile(value: str) -> str:
    cleaned = _clean_text(value).lower()
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return "single"
    if len(set(cleaned)) == 1:
        return "repeat"
    return "mixed"


def _suffix_kind(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    if _is_probable_statutory_roman_suffix(cleaned):
        return "roman"
    if cleaned.isalpha():
        return "alpha"
    return "other"


def _is_probable_statutory_roman_suffix(value: str) -> bool:
    cleaned = _clean_text(value)
    if len(cleaned) <= 1:
        return False
    if not _is_canonical_roman_numeral(cleaned):
        return False
    lowered = cleaned.lower()
    if len(set(lowered)) == 1 and lowered[0] != "i":
        return False
    return True


def _is_canonical_roman_numeral(value: str) -> bool:
    cleaned = _clean_text(value)
    if not cleaned:
        return False
    return _STRICT_ROMAN_NUMERAL_RE.fullmatch(cleaned) is not None


def _derived_status_keyword(
    *,
    formula: ModalIRFormula,
    fallback_rule: str,
) -> str:
    explicit = _clean_text(formula.metadata.get("status_keyword") or "").lower()
    if explicit:
        return explicit
    normalized_rule = _clean_text(fallback_rule).lower()
    if normalized_rule not in _USCODE_STATUS_DERIVATION_RULES:
        return ""
    predicate_text = _clean_text(formula.predicate.name).replace("_", " ").lower()
    for keyword in _USCODE_FALLBACK_STATUS_KEYWORDS:
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", predicate_text):
            return keyword
    if normalized_rule in {
        "uscode_transferred_heading_v1",
        "uscode_codification_transfer_heading_v1",
    }:
        return "transferred"
    return ""


def _citation_slots(citation: str) -> List[Tuple[str, str]]:
    cleaned = _clean_text(citation)
    if not cleaned:
        return []
    match = _USC_CITATION_RE.match(cleaned)
    if not match:
        return []
    title = _clean_text(match.group("title"))
    raw_section = _clean_text(match.group("section"))
    section = _TRAILING_SECTION_PUNCT_RE.sub("", raw_section)
    section_trailing_punct = _section_trailing_punct(
        raw_section=raw_section,
        normalized_section=section,
    )
    slots: List[Tuple[str, str]] = []
    title_number = ""
    if title:
        slots.append(("citation_title", title))
        slots.extend(_typed_identifier_slots(title, slot_prefix="citation_title"))
        title_match = _CITATION_SECTION_PART_RE.fullmatch(title)
        if title_match:
            title_number = _clean_text(title_match.group("number"))
            title_suffix = _clean_text(title_match.group("suffix"))
            if title_number:
                slots.append(("citation_title_number", title_number))
                slots.extend(
                    _numeric_signature_slots(
                        title_number,
                        slot_prefix="citation_title_number",
                    )
                )
            if title_suffix:
                slots.append(("citation_title_suffix", title_suffix))
    slots.append(("citation_code", "U.S.C."))
    if section:
        citation_canonical = _canonical_usc_citation(title, section)
        if citation_canonical:
            slots.append(("citation_canonical", citation_canonical))
        citation_title_section_key = _title_section_coordinate(title, section)
        if citation_title_section_key:
            slots.append(("citation_title_section_key", citation_title_section_key))
            slots.append(
                (
                    "citation_title_section_key_normalized",
                    citation_title_section_key.lower(),
                )
            )
            slots.extend(
                _typed_identifier_slots(
                    citation_title_section_key.replace(":", "_"),
                    slot_prefix="citation_title_section_key",
                )
            )
        slots.append(("citation_section", section))
        if raw_section:
            slots.append(("citation_section_raw", raw_section))
        slots.append(("citation_section_normalized", section))
        slots.extend(
            (
                ("reference_dependency", "direct_reference:statutory_section"),
                ("reference_dependency_kind", "direct_reference"),
                ("reference_dependency_target_type", "statutory_section"),
                ("reference_dependency_target", f"statutory_section:{section}"),
                (
                    "citation_reference_dependency",
                    f"direct_reference:statutory_section:{section}",
                ),
            )
        )
        if section_trailing_punct:
            slots.append(("citation_section_trailing_punct", section_trailing_punct))
            slots.append(("citation_section_has_trailing_punct", "true"))
            slots.append(
                (
                    "citation_section_trailing_punct_count",
                    str(len(section_trailing_punct)),
                )
            )
            punct_kind = _section_trailing_punct_kind(section_trailing_punct)
            if punct_kind:
                slots.append(("citation_section_trailing_punct_kind", punct_kind))
        else:
            slots.append(("citation_section_has_trailing_punct", "false"))
            slots.append(("citation_section_trailing_punct_count", "0"))
        section_slots = _citation_section_slots(section)
        slots.extend(section_slots)
        section_slot_map = _slot_value_map(section_slots)
        slots.extend(
            _section_style_slots(
                slot_namespace="citation",
                section_slot_map=section_slot_map,
                has_trailing_punct=bool(section_trailing_punct),
            )
        )
        citation_style_map = _slot_value_map(
            [
                slot
                for slot in slots
                if slot[0] in {"citation_section_style", "citation_section_style_canonical"}
            ]
        )
        slots.extend(
            _title_section_style_slots(
                slot_namespace="citation",
                title=title,
                section_style=_clean_text(
                    citation_style_map.get("citation_section_style") or ""
                ),
                section_style_canonical=_clean_text(
                    citation_style_map.get("citation_section_style_canonical") or ""
                ),
            )
        )
        slots.extend(
            _section_structure_slots(
                slot_namespace="citation",
                title=title,
                section_signature=_clean_text(
                    section_slot_map.get("citation_section_signature") or ""
                ),
                section_profile=_clean_text(
                    section_slot_map.get("citation_section_component_profile") or ""
                ),
            )
        )
        slots.extend(
            _title_section_number_relation_slots(
                slot_namespace="citation",
                title_number=title_number,
                section_slot_map=section_slot_map,
            )
        )
        slots.extend(
            _typed_identifier_slots(
                section,
                slot_prefix="citation_section",
            )
        )
    return _unique_slot_values(slots)


def _section_trailing_punct(
    *,
    raw_section: str,
    normalized_section: str,
) -> str:
    raw = _clean_text(raw_section)
    normalized = _clean_text(normalized_section)
    if not raw or raw == normalized:
        return ""
    if not raw.startswith(normalized):
        return ""
    return _clean_text(raw[len(normalized) :])


def _section_trailing_punct_kind(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    if all(character == "." for character in cleaned):
        return "dot"
    if all(character == ":" for character in cleaned):
        return "colon"
    if all(character == ";" for character in cleaned):
        return "semicolon"
    return "other"


def _canonical_usc_citation(title: str, section: str) -> str:
    normalized_title = _clean_text(title)
    normalized_section = _clean_text(_TRAILING_SECTION_PUNCT_RE.sub("", section))
    if not normalized_title or not normalized_section:
        return ""
    return f"{normalized_title} U.S.C. {normalized_section}"


def _title_section_coordinate(title: str, section: str) -> str:
    normalized_title = _clean_text(title)
    normalized_section = _clean_text(_TRAILING_SECTION_PUNCT_RE.sub("", section))
    if not normalized_title or not normalized_section:
        return ""
    return f"{normalized_title}:{normalized_section}"


def _section_structure_slots(
    *,
    slot_namespace: str,
    title: str,
    section_signature: str,
    section_profile: str,
) -> List[Tuple[str, str]]:
    normalized_namespace = _clean_text(slot_namespace)
    normalized_title = _clean_text(title)
    normalized_signature = _clean_text(section_signature)
    normalized_profile = _clean_text(section_profile)
    if not normalized_namespace:
        return []
    slots: List[Tuple[str, str]] = []
    if normalized_profile and normalized_signature:
        profile_signature = f"{normalized_profile}:{normalized_signature}"
        slots.append((f"{normalized_namespace}_section_profile_signature", profile_signature))
        slots.append(
            (
                f"{normalized_namespace}_section_profile_signature_normalized",
                profile_signature.lower(),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                profile_signature.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_section_profile_signature",
            )
        )
    if normalized_title and normalized_signature:
        title_section_signature = f"{normalized_title}:{normalized_signature}"
        slots.append(
            (f"{normalized_namespace}_title_section_signature", title_section_signature)
        )
        slots.append(
            (
                f"{normalized_namespace}_title_section_signature_normalized",
                title_section_signature.lower(),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                title_section_signature.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_title_section_signature",
            )
        )
    if normalized_title and normalized_profile:
        title_section_profile = f"{normalized_title}:{normalized_profile}"
        slots.append((f"{normalized_namespace}_title_section_profile", title_section_profile))
        slots.append(
            (
                f"{normalized_namespace}_title_section_profile_normalized",
                title_section_profile.lower(),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                title_section_profile.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_title_section_profile",
            )
        )
    return slots


def _title_section_style_slots(
    *,
    slot_namespace: str,
    title: str,
    section_style: str,
    section_style_canonical: str,
) -> List[Tuple[str, str]]:
    normalized_namespace = _clean_text(slot_namespace)
    normalized_title = _clean_text(title)
    normalized_section_style = _clean_text(section_style)
    normalized_section_style_canonical = _clean_text(section_style_canonical)
    if not normalized_namespace or not normalized_title:
        return []
    slots: List[Tuple[str, str]] = []

    if normalized_section_style:
        title_section_style = f"{normalized_title}:{normalized_section_style}"
        slots.append((f"{normalized_namespace}_title_section_style", title_section_style))
        slots.append(
            (
                f"{normalized_namespace}_title_section_style_normalized",
                title_section_style.lower(),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                title_section_style.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_title_section_style",
            )
        )

    if normalized_section_style_canonical:
        title_section_style_canonical = (
            f"{normalized_title}:{normalized_section_style_canonical}"
        )
        slots.append(
            (
                f"{normalized_namespace}_title_section_style_canonical",
                title_section_style_canonical,
            )
        )
        slots.append(
            (
                f"{normalized_namespace}_title_section_style_canonical_normalized",
                title_section_style_canonical.lower(),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                title_section_style_canonical.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_title_section_style_canonical",
            )
        )

    return _unique_slot_values(slots)


def _title_section_number_relation_slots(
    *,
    slot_namespace: str,
    title_number: str,
    section_slot_map: Dict[str, str],
) -> List[Tuple[str, str]]:
    normalized_namespace = _clean_text(slot_namespace)
    normalized_title_number = _clean_text(title_number)
    if not normalized_namespace or not normalized_title_number:
        return []
    primary_number = _clean_text(
        section_slot_map.get(f"{normalized_namespace}_section_primary_number")
        or section_slot_map.get(f"{normalized_namespace}_section_number")
        or ""
    )
    terminal_number = _clean_text(
        section_slot_map.get(f"{normalized_namespace}_section_terminal_number")
        or section_slot_map.get(f"{normalized_namespace}_section_number")
        or ""
    )
    slots: List[Tuple[str, str]] = []
    primary_relation = _primary_terminal_number_relation(
        primary_number=normalized_title_number,
        terminal_number=primary_number,
    )
    if primary_relation is not None:
        relation, span = primary_relation
        span_slot = f"{normalized_namespace}_title_section_primary_number_span"
        profile_slot = f"{normalized_namespace}_title_section_primary_number_distance_profile"
        slots.append(
            (
                f"{normalized_namespace}_title_section_primary_number_relation",
                relation,
            )
        )
        slots.append((span_slot, span))
        slots.extend(
            _numeric_span_signature_slots(
                slot_prefix=span_slot,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            slots.append((profile_slot, relation_profile))
            slots.extend(
                _typed_identifier_slots(
                    relation_profile,
                    slot_prefix=profile_slot,
                )
            )
    terminal_relation = _primary_terminal_number_relation(
        primary_number=normalized_title_number,
        terminal_number=terminal_number,
    )
    if terminal_relation is not None:
        relation, span = terminal_relation
        span_slot = f"{normalized_namespace}_title_section_terminal_number_span"
        profile_slot = f"{normalized_namespace}_title_section_terminal_number_distance_profile"
        slots.append(
            (
                f"{normalized_namespace}_title_section_terminal_number_relation",
                relation,
            )
        )
        slots.append((span_slot, span))
        slots.extend(
            _numeric_span_signature_slots(
                slot_prefix=span_slot,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            slots.append((profile_slot, relation_profile))
            slots.extend(
                _typed_identifier_slots(
                    relation_profile,
                    slot_prefix=profile_slot,
                )
            )
    return slots


def _section_style_slots(
    *,
    slot_namespace: str,
    section_slot_map: Dict[str, str],
    has_trailing_punct: bool,
) -> List[Tuple[str, str]]:
    normalized_namespace = _clean_text(slot_namespace)
    if not normalized_namespace:
        return []
    profile = _clean_text(
        section_slot_map.get(f"{normalized_namespace}_section_component_profile")
        or ""
    )
    if not profile:
        return []
    suffix_kind = _clean_text(
        section_slot_map.get(f"{normalized_namespace}_section_primary_suffix_kind")
        or ""
    )
    suffix_case = _clean_text(
        section_slot_map.get(f"{normalized_namespace}_section_primary_suffix_case")
        or ""
    )
    suffix_style = "none"
    if suffix_kind:
        suffix_style = suffix_kind
        if suffix_case:
            suffix_style = f"{suffix_style}_{suffix_case}"
    punctuation_style = "trailing_punct" if has_trailing_punct else "clean"
    style_parts: List[str] = [profile]
    if suffix_style != "none":
        style_parts.append(suffix_style)
    style_parts.append(punctuation_style)
    style = "_".join(style_parts)
    canonical_style = _section_style_canonical(
        profile=profile,
        suffix_kind=suffix_kind,
        suffix_case=suffix_case,
        punctuation_style=punctuation_style,
    )
    slots: List[Tuple[str, str]] = [
        (f"{normalized_namespace}_section_style", style),
        (f"{normalized_namespace}_section_style_canonical", canonical_style),
        (f"{normalized_namespace}_section_suffix_style", suffix_style),
        (f"{normalized_namespace}_section_style_suffix_kind", suffix_kind or "none"),
        (f"{normalized_namespace}_section_style_suffix_case", suffix_case or "none"),
        (f"{normalized_namespace}_section_punctuation_style", punctuation_style),
    ]
    slots.extend(
        _typed_identifier_slots(
            style,
            slot_prefix=f"{normalized_namespace}_section_style",
        )
    )
    slots.extend(
        _typed_identifier_slots(
            canonical_style,
            slot_prefix=f"{normalized_namespace}_section_style_canonical",
        )
    )
    return _unique_slot_values(slots)


def _section_style_canonical(
    *,
    profile: str,
    suffix_kind: str,
    suffix_case: str,
    punctuation_style: str,
) -> str:
    normalized_profile = _clean_text(profile)
    normalized_punctuation_style = _clean_text(punctuation_style)
    if not normalized_profile or not normalized_punctuation_style:
        return ""
    normalized_suffix_kind = _clean_text(suffix_kind) or "none"
    normalized_suffix_case = _clean_text(suffix_case) or "none"
    return (
        f"{normalized_profile}_{normalized_suffix_kind}_"
        f"{normalized_suffix_case}_{normalized_punctuation_style}"
    )


def _citation_section_slots(section: str) -> List[Tuple[str, str]]:
    cleaned = _clean_text(section)
    if not cleaned:
        return []
    range_match = _CITATION_SECTION_RANGE_RE.fullmatch(cleaned)
    range_start = ""
    range_end = ""
    range_connector = ""
    if range_match:
        range_start = _clean_text(range_match.group("start"))
        range_end = _clean_text(range_match.group("end"))
        range_connector = _clean_text(range_match.group("connector")).lower()
    is_range = bool(range_start and range_end and range_connector)
    if is_range:
        components = [range_start, range_end]
    else:
        components = [
            _clean_text(component)
            for component in _CITATION_SECTION_COMPONENT_SPLIT_RE.split(cleaned)
            if _clean_text(component)
        ]
    if not components:
        return []
    primary_component = components[0]
    terminal_component = components[-1]
    slots: List[Tuple[str, str]] = [
        ("citation_section_primary", primary_component),
        ("citation_section_terminal", terminal_component),
        (
            "citation_section_primary_equals_terminal",
            "true" if primary_component == terminal_component else "false",
        ),
        (
            "citation_section_primary_terminal_pair",
            f"{primary_component}|{terminal_component}",
        ),
        ("citation_section_component_count", str(len(components))),
        ("citation_section_is_range", "true" if is_range else "false"),
    ]
    delimiter_tokens = _citation_section_delimiter_tokens(cleaned)
    delimiter_pattern = ""
    if delimiter_tokens:
        slots.append(("citation_section_has_delimiter", "true"))
        slots.append(("citation_section_delimiter_count", str(len(delimiter_tokens))))
        delimiter_kinds: List[str] = []
        for index, delimiter_token in enumerate(delimiter_tokens, start=1):
            position = str(index)
            kind = _citation_section_delimiter_kind(delimiter_token)
            if kind:
                delimiter_kinds.append(kind)
                slots.append(("citation_section_delimiter", kind))
                slots.append(
                    ("citation_section_delimiter_positioned", f"{position}:{kind}")
                )
            slots.append(("citation_section_delimiter_token", delimiter_token))
            slots.append(
                (
                    "citation_section_delimiter_token_positioned",
                    f"{position}:{delimiter_token}",
                )
            )
            char_count = str(len(delimiter_token))
            slots.append(("citation_section_delimiter_char_count", char_count))
            slots.append(
                (
                    "citation_section_delimiter_char_count_positioned",
                    f"{position}:{char_count}",
                )
            )
        if delimiter_kinds:
            delimiter_pattern = "-".join(delimiter_kinds)
            slots.append(
                ("citation_section_delimiter_pattern", delimiter_pattern)
            )
            slots.append(
                (
                    "citation_section_delimiter_distinct_count",
                    str(len(set(delimiter_kinds))),
                )
            )
    else:
        slots.append(("citation_section_has_delimiter", "false"))
        slots.append(("citation_section_delimiter_count", "0"))
    if is_range:
        slots.extend(
            [
                ("citation_section_range", f"{range_start} {range_connector} {range_end}"),
                ("citation_section_range_start", range_start),
                ("citation_section_range_end", range_end),
                ("citation_section_range_connector", range_connector),
            ]
        )
    component_shapes: List[str] = []
    component_signatures: List[str] = []
    numeric_component_count = 0
    suffix_component_count = 0
    roman_suffix_component_count = 0
    parsed_component_count = 0
    primary_has_suffix: bool | None = None
    terminal_has_suffix: bool | None = None
    primary_suffix_is_roman: bool | None = None
    terminal_suffix_is_roman: bool | None = None
    primary_component_kind = ""
    terminal_component_kind = ""
    primary_number = ""
    terminal_number = ""
    primary_suffix = ""
    terminal_suffix = ""
    primary_suffix_kind = ""
    terminal_suffix_kind = ""
    total_components = len(components)
    for index, component in enumerate(components, start=1):
        position = str(index)
        slots.append(("citation_section_component", component))
        slots.append(("citation_section_component_positioned", f"{position}:{component}"))
        match = _CITATION_SECTION_PART_RE.fullmatch(component)
        if not match:
            component_shapes.append("X")
            component_signature = "X"
            component_signatures.append(component_signature)
            slots.append(("citation_section_component_signature", component_signature))
            slots.append(
                (
                    "citation_section_component_signature_positioned",
                    f"{position}:{component_signature}",
                )
            )
            if index == 1:
                slots.append(
                    ("citation_section_primary_component_signature", component_signature)
                )
            if index == total_components:
                slots.append(
                    ("citation_section_terminal_component_signature", component_signature)
                )
            slots.append(("citation_section_component_kind", "other"))
            slots.append(
                ("citation_section_component_kind_positioned", f"{position}:other")
            )
            if index == 1:
                slots.append(("citation_section_primary_component_kind", "other"))
                primary_component_kind = "other"
            if index == total_components:
                slots.append(("citation_section_terminal_component_kind", "other"))
                terminal_component_kind = "other"
            continue
        number = _clean_text(match.group("number"))
        suffix = _clean_text(match.group("suffix"))
        numeric_component_count += 1
        parsed_component_count += 1
        if index == 1:
            primary_has_suffix = bool(suffix)
            primary_suffix_is_roman = False
        if index == total_components:
            terminal_has_suffix = bool(suffix)
            terminal_suffix_is_roman = False
        if number:
            slots.append(("citation_section_number", number))
            number_digit_count = str(len(number))
            slots.append(("citation_section_number_digit_count", number_digit_count))
            slots.append(
                (
                    "citation_section_number_digit_count_positioned",
                    f"{position}:{number_digit_count}",
                )
            )
            slots.append(("citation_section_number_positioned", f"{position}:{number}"))
            number_suffix_pair = f"{number}|{suffix or 'none'}"
            slots.append(("citation_section_number_suffix_pair", number_suffix_pair))
            slots.append(
                (
                    "citation_section_number_suffix_pair_positioned",
                    f"{position}:{number_suffix_pair}",
                )
            )
            for signature_slot, signature_value in _numeric_signature_slots(
                number,
                slot_prefix="citation_section_number",
            ):
                slots.append((signature_slot, signature_value))
                slots.append(
                    (
                        f"{signature_slot}_positioned",
                        f"{position}:{signature_value}",
                    )
                )
            if index == 1:
                slots.append(("citation_section_primary_number", number))
                primary_number = number
                slots.append(
                    (
                        "citation_section_primary_number_digit_count",
                        number_digit_count,
                    )
                )
                slots.extend(
                    _numeric_signature_slots(
                        number,
                        slot_prefix="citation_section_primary_number",
                    )
                )
                slots.append(
                    (
                        "citation_section_primary_number_suffix_pair",
                        number_suffix_pair,
                    )
                )
            if index == total_components:
                slots.append(("citation_section_terminal_number", number))
                terminal_number = number
                slots.append(
                    (
                        "citation_section_terminal_number_digit_count",
                        number_digit_count,
                    )
                )
                slots.extend(
                    _numeric_signature_slots(
                        number,
                        slot_prefix="citation_section_terminal_number",
                    )
                )
                slots.append(
                    (
                        "citation_section_terminal_number_suffix_pair",
                        number_suffix_pair,
                    )
                )
        suffix_kind = _suffix_kind(suffix) if suffix else ""
        component_signature = _citation_section_component_signature(
            number=number,
            suffix=suffix,
            suffix_kind=suffix_kind,
        )
        component_signatures.append(component_signature)
        slots.append(("citation_section_component_signature", component_signature))
        slots.append(
            (
                "citation_section_component_signature_positioned",
                f"{position}:{component_signature}",
            )
        )
        if index == 1:
            slots.append(("citation_section_primary_component_signature", component_signature))
        if index == total_components:
            slots.append(
                ("citation_section_terminal_component_signature", component_signature)
            )
        if suffix:
            component_shapes.append("NA")
            suffix_component_count += 1
            slots.append(("citation_section_component_kind", "alphanumeric"))
            slots.append(
                (
                    "citation_section_component_kind_positioned",
                    f"{position}:alphanumeric",
                )
            )
            slots.append(("citation_section_suffix", suffix))
            slots.append(("citation_section_suffix_positioned", f"{position}:{suffix}"))
            suffix_char_count = str(len(suffix))
            slots.append(("citation_section_suffix_char_count", suffix_char_count))
            slots.append(
                (
                    "citation_section_suffix_char_count_positioned",
                    f"{position}:{suffix_char_count}",
                )
            )
            suffix_profile = _suffix_profile(suffix)
            if suffix_profile:
                slots.append(("citation_section_suffix_profile", suffix_profile))
                slots.append(
                    (
                        "citation_section_suffix_profile_positioned",
                        f"{position}:{suffix_profile}",
                    )
                )
            normalized_suffix = suffix.lower()
            if normalized_suffix:
                slots.append(("citation_section_suffix_normalized", normalized_suffix))
                if index == 1:
                    slots.append(("citation_section_primary_suffix_normalized", normalized_suffix))
                if index == total_components:
                    slots.append(("citation_section_terminal_suffix_normalized", normalized_suffix))
            suffix_case = _alpha_case_kind(suffix)
            if suffix_case:
                slots.append(("citation_section_suffix_case", suffix_case))
                slots.append(
                    (
                        "citation_section_suffix_case_positioned",
                        f"{position}:{suffix_case}",
                    )
                )
                if index == 1:
                    slots.append(("citation_section_primary_suffix_case", suffix_case))
                if index == total_components:
                    slots.append(("citation_section_terminal_suffix_case", suffix_case))
            for alpha_slot, alpha_value in _alpha_signature_slots(
                suffix,
                slot_prefix="citation_section_suffix",
            ):
                slots.append((alpha_slot, alpha_value))
                slots.append(
                    (
                        f"{alpha_slot}_positioned",
                        f"{position}:{alpha_value}",
                    )
                )
            if suffix_kind:
                slots.append(("citation_section_suffix_kind", suffix_kind))
                slots.append(
                    (
                        "citation_section_suffix_kind_positioned",
                        f"{position}:{suffix_kind}",
                    )
                )
                if index == 1:
                    slots.append(("citation_section_primary_suffix_kind", suffix_kind))
                    primary_suffix_kind = suffix_kind
                if index == total_components:
                    slots.append(("citation_section_terminal_suffix_kind", suffix_kind))
                    terminal_suffix_kind = suffix_kind
            if suffix_kind == "roman":
                roman_suffix_component_count += 1
                if index == 1:
                    primary_suffix_is_roman = True
                if index == total_components:
                    terminal_suffix_is_roman = True
            if index == 1:
                primary_suffix = suffix
                slots.append(("citation_section_primary_suffix", suffix))
                slots.append(("citation_section_primary_suffix_char_count", suffix_char_count))
                if suffix_profile:
                    slots.append(("citation_section_primary_suffix_profile", suffix_profile))
                slots.extend(
                    _alpha_signature_slots(
                        suffix,
                        slot_prefix="citation_section_primary_suffix",
                    )
                )
                slots.append(("citation_section_primary_component_kind", "alphanumeric"))
                primary_component_kind = "alphanumeric"
            if index == total_components:
                terminal_suffix = suffix
                slots.append(("citation_section_terminal_suffix", suffix))
                slots.append(("citation_section_terminal_suffix_char_count", suffix_char_count))
                if suffix_profile:
                    slots.append(("citation_section_terminal_suffix_profile", suffix_profile))
                slots.extend(
                    _alpha_signature_slots(
                        suffix,
                        slot_prefix="citation_section_terminal_suffix",
                    )
                )
                slots.append(("citation_section_terminal_component_kind", "alphanumeric"))
                terminal_component_kind = "alphanumeric"
        else:
            component_shapes.append("N")
            slots.append(("citation_section_component_kind", "numeric"))
            slots.append(
                ("citation_section_component_kind_positioned", f"{position}:numeric")
            )
            if index == 1:
                slots.append(("citation_section_primary_component_kind", "numeric"))
                primary_component_kind = "numeric"
            if index == total_components:
                slots.append(("citation_section_terminal_component_kind", "numeric"))
                terminal_component_kind = "numeric"
    if parsed_component_count:
        slots.append(
            (
                "citation_section_has_suffix",
                "true" if suffix_component_count > 0 else "false",
            )
        )
        slots.append(
            (
                "citation_section_has_roman_suffix",
                "true" if roman_suffix_component_count > 0 else "false",
            )
        )
        primary_suffix_kind_coarse = primary_suffix_kind or "none"
        terminal_suffix_kind_coarse = terminal_suffix_kind or "none"
        slots.extend(
            [
                (
                    "citation_section_primary_suffix_kind_coarse",
                    primary_suffix_kind_coarse,
                ),
                (
                    "citation_section_terminal_suffix_kind_coarse",
                    terminal_suffix_kind_coarse,
                ),
                (
                    "citation_section_primary_terminal_suffix_kind_pair",
                    f"{primary_suffix_kind_coarse}|{terminal_suffix_kind_coarse}",
                ),
                (
                    "citation_section_primary_terminal_suffix_kind_match",
                    "true"
                    if primary_suffix_kind_coarse == terminal_suffix_kind_coarse
                    else "false",
                ),
            ]
        )
    if primary_has_suffix is not None:
        slots.append(
            (
                "citation_section_primary_has_suffix",
                "true" if primary_has_suffix else "false",
            )
        )
    if primary_suffix_is_roman is not None:
        slots.append(
            (
                "citation_section_primary_suffix_is_roman",
                "true" if primary_suffix_is_roman else "false",
            )
        )
    if terminal_has_suffix is not None:
        slots.append(
            (
                "citation_section_terminal_has_suffix",
                "true" if terminal_has_suffix else "false",
            )
        )
    if terminal_suffix_is_roman is not None:
        slots.append(
            (
                "citation_section_terminal_suffix_is_roman",
                "true" if terminal_suffix_is_roman else "false",
            )
        )
    if component_shapes:
        slots.append(("citation_section_shape", "-".join(component_shapes)))
    if component_signatures:
        slots.append(("citation_section_signature", "-".join(component_signatures)))
        primary_signature = component_signatures[0]
        terminal_signature = component_signatures[-1]
        slots.append(
            (
                "citation_section_primary_terminal_component_signature_pair",
                f"{primary_signature}|{terminal_signature}",
            )
        )
        slots.append(
            (
                "citation_section_primary_terminal_component_signature_match",
                "true" if primary_signature == terminal_signature else "false",
            )
        )
    if primary_component_kind and terminal_component_kind:
        slots.append(
            (
                "citation_section_primary_terminal_component_kind_pair",
                f"{primary_component_kind}|{terminal_component_kind}",
            )
        )
        slots.append(
            (
                "citation_section_primary_terminal_component_kind_match",
                "true" if primary_component_kind == terminal_component_kind else "false",
            )
        )
    component_profile = _citation_section_component_profile(
        component_count=total_components,
        suffix_component_count=suffix_component_count,
        is_range=is_range,
    )
    if component_profile:
        slots.append(("citation_section_component_profile", component_profile))
    numeric_relation = _primary_terminal_number_relation(
        primary_number=primary_number,
        terminal_number=terminal_number,
    )
    if numeric_relation is not None:
        relation, span = numeric_relation
        primary_span_slot = "citation_section_primary_terminal_number_span"
        primary_profile_slot = "citation_section_primary_terminal_number_distance_profile"
        slots.append(("citation_section_primary_terminal_number_relation", relation))
        slots.append((primary_span_slot, span))
        slots.extend(
            _numeric_span_signature_slots(
                slot_prefix=primary_span_slot,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            slots.append((primary_profile_slot, relation_profile))
            slots.extend(
                _typed_identifier_slots(
                    relation_profile,
                    slot_prefix=primary_profile_slot,
                )
            )
        if is_range:
            slots.append(("citation_section_range_number_relation", relation))
            range_span_slot = "citation_section_range_number_span"
            range_profile_slot = "citation_section_range_number_distance_profile"
            slots.append((range_span_slot, span))
            slots.extend(
                _numeric_span_signature_slots(
                    slot_prefix=range_span_slot,
                    span=span,
                )
            )
            if relation_profile:
                slots.append((range_profile_slot, relation_profile))
                slots.extend(
                    _typed_identifier_slots(
                        relation_profile,
                        slot_prefix=range_profile_slot,
                    )
                )
    slots.extend(
        _primary_terminal_suffix_relation_slots(
            primary_suffix=primary_suffix,
            terminal_suffix=terminal_suffix,
            slot_prefix="citation_section_primary_terminal_suffix",
            emit_when_absent=is_range,
        )
    )
    if is_range:
        slots.extend(
            _primary_terminal_suffix_relation_slots(
                primary_suffix=primary_suffix,
                terminal_suffix=terminal_suffix,
                slot_prefix="citation_section_range_suffix",
                emit_when_absent=True,
            )
        )
    if is_range:
        slots.append(
            (
                "citation_section_range_has_suffix",
                "true" if suffix_component_count > 0 else "false",
            )
        )
    has_hyphen_subsection = (
        not is_range
        and total_components == 2
        and delimiter_pattern == "hyphen"
        and bool(primary_number)
        and bool(primary_suffix)
        and bool(terminal_number)
        and not terminal_suffix
    )
    slots.append(
        (
            "citation_section_has_hyphen_subsection",
            "true" if has_hyphen_subsection else "false",
        )
    )
    if has_hyphen_subsection:
        normalized_primary_suffix = primary_suffix.lower()
        hyphen_subsection_signature = (
            f"{primary_number}{normalized_primary_suffix}-{terminal_number}"
        )
        slots.append(
            (
                "citation_section_hyphen_subsection_primary_number",
                primary_number,
            )
        )
        slots.append(
            (
                "citation_section_hyphen_subsection_primary_suffix",
                normalized_primary_suffix,
            )
        )
        slots.append(
            (
                "citation_section_hyphen_subsection_terminal_number",
                terminal_number,
            )
        )
        slots.append(
            (
                "citation_section_hyphen_subsection_signature",
                hyphen_subsection_signature,
            )
        )
        slots.extend(
            _typed_identifier_slots(
                hyphen_subsection_signature,
                slot_prefix="citation_section_hyphen_subsection_signature",
            )
        )
    slots.append(
        ("citation_section_numeric_component_count", str(numeric_component_count))
    )
    slots.append(
        ("citation_section_suffix_component_count", str(suffix_component_count))
    )
    slots.append(
        (
            "citation_section_roman_suffix_component_count",
            str(roman_suffix_component_count),
        )
    )
    return slots


def _citation_section_delimiter_tokens(section: str) -> List[str]:
    return [
        delimiter
        for delimiter in (
            _clean_text(token) for token in _CITATION_SECTION_DELIMITER_RE.findall(section)
        )
        if delimiter
    ]


def _citation_section_delimiter_kind(delimiter: str) -> str:
    cleaned = _clean_text(delimiter)
    if not cleaned:
        return ""
    if all(character == "." for character in cleaned):
        return "dot"
    if all(character == "-" for character in cleaned):
        return "hyphen"
    if all(character in ".-" for character in cleaned):
        return "mixed"
    return "other"


def _citation_section_component_signature(
    *,
    number: str,
    suffix: str,
    suffix_kind: str,
) -> str:
    number_text = _clean_text(number)
    suffix_text = _clean_text(suffix)
    number_width = str(len(number_text)) if number_text else "0"
    if not suffix_text:
        return f"N{number_width}"
    kind_key = _clean_text(suffix_kind).lower()
    kind_symbol = "R" if kind_key == "roman" else "A" if kind_key == "alpha" else "O"
    return f"N{number_width}{kind_symbol}{len(suffix_text)}"


def _citation_section_component_profile(
    *,
    component_count: int,
    suffix_component_count: int,
    is_range: bool,
) -> str:
    if component_count <= 0:
        return ""
    if is_range:
        return "range"
    if component_count == 1:
        return "single_alphanumeric" if suffix_component_count else "single_numeric"
    if suffix_component_count == 0:
        return "compound_numeric"
    if suffix_component_count == component_count:
        return "compound_alphanumeric"
    return "compound_mixed"


def _primary_terminal_number_relation(
    *,
    primary_number: str,
    terminal_number: str,
) -> Tuple[str, str] | None:
    primary_text = _clean_text(primary_number)
    terminal_text = _clean_text(terminal_number)
    if not primary_text or not terminal_text:
        return None
    try:
        primary_value = int(primary_text)
        terminal_value = int(terminal_text)
    except (TypeError, ValueError):
        return None
    if primary_value == terminal_value:
        return ("equal", "0")
    if primary_value < terminal_value:
        return ("ascending", str(terminal_value - primary_value))
    return ("descending", str(primary_value - terminal_value))


def _primary_terminal_suffix_relation_slots(
    *,
    primary_suffix: str,
    terminal_suffix: str,
    slot_prefix: str,
    emit_when_absent: bool = False,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    if not normalized_slot_prefix:
        return []
    primary = _clean_text(primary_suffix).lower()
    terminal = _clean_text(terminal_suffix).lower()
    if not primary and not terminal and not emit_when_absent:
        return []
    slots: List[Tuple[str, str]] = [
        (
            f"{normalized_slot_prefix}_pair",
            f"{primary or 'none'}|{terminal or 'none'}",
        ),
        (
            f"{normalized_slot_prefix}_match",
            "true" if primary == terminal else "false",
        ),
        (
            f"{normalized_slot_prefix}_presence_match",
            "true" if bool(primary) == bool(terminal) else "false",
        ),
    ]
    if primary and terminal:
        length_relation = _primary_terminal_number_relation(
            primary_number=str(len(primary)),
            terminal_number=str(len(terminal)),
        )
        if length_relation is not None:
            relation, span = length_relation
            slots.append((f"{normalized_slot_prefix}_length_relation", relation))
            slots.append((f"{normalized_slot_prefix}_length_span", span))
        alpha_relation = _primary_terminal_alpha_relation(
            primary_token=primary,
            terminal_token=terminal,
        )
        if alpha_relation is not None:
            relation, span = alpha_relation
            slots.append((f"{normalized_slot_prefix}_alpha_relation", relation))
            slots.append((f"{normalized_slot_prefix}_alpha_span", span))
    return slots


def _primary_terminal_alpha_relation(
    *,
    primary_token: str,
    terminal_token: str,
) -> Tuple[str, str] | None:
    primary_value = _alpha_token_value(primary_token)
    terminal_value = _alpha_token_value(terminal_token)
    if primary_value is None or terminal_value is None:
        return None
    if primary_value == terminal_value:
        return ("equal", "0")
    if primary_value < terminal_value:
        return ("ascending", str(terminal_value - primary_value))
    return ("descending", str(primary_value - terminal_value))


def _alpha_token_value(value: str) -> int | None:
    cleaned = _clean_text(value).lower()
    if not cleaned or not cleaned.isalpha():
        return None
    numeric_value = 0
    for character in cleaned:
        numeric_value = (numeric_value * 26) + (ord(character) - ord("a") + 1)
    return numeric_value


def _numeric_signature_slots(
    value: str,
    *,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    cleaned = _clean_text(value)
    if not cleaned or not cleaned.isdigit():
        return []
    numeric_value = int(cleaned)
    last_digit = cleaned[-1]
    trailing_two_digits = cleaned[-2:] if len(cleaned) > 1 else cleaned
    parity = "even" if last_digit in {"0", "2", "4", "6", "8"} else "odd"
    zero_digit_count = cleaned.count("0")
    trailing_zero_count = len(cleaned) - len(cleaned.rstrip("0"))
    digit_count_bucket = f"{len(cleaned)}_digit"
    magnitude_bucket = _numeric_magnitude_bucket(numeric_value)
    prefix_two_digits = cleaned[:2] if len(cleaned) > 1 else cleaned
    prefix_three_digits = cleaned[:3] if len(cleaned) > 2 else cleaned
    hundreds_block = str(numeric_value // 100)
    thousands_block = str(numeric_value // 1_000)
    return [
        (f"{slot_prefix}_parity", parity),
        (f"{slot_prefix}_digit_count_bucket", digit_count_bucket),
        (f"{slot_prefix}_magnitude_bucket", magnitude_bucket),
        (f"{slot_prefix}_prefix_two_digits", prefix_two_digits),
        (f"{slot_prefix}_prefix_three_digits", prefix_three_digits),
        (f"{slot_prefix}_hundreds_block", hundreds_block),
        (f"{slot_prefix}_thousands_block", thousands_block),
        (f"{slot_prefix}_leading_digit", cleaned[0]),
        (f"{slot_prefix}_trailing_two_digits", trailing_two_digits),
        (f"{slot_prefix}_zero_digit_count", str(zero_digit_count)),
        (
            f"{slot_prefix}_has_zero_digit",
            "true" if zero_digit_count > 0 else "false",
        ),
        (f"{slot_prefix}_trailing_zero_count", str(trailing_zero_count)),
    ]


def _numeric_span_signature_slots(
    *,
    slot_prefix: str,
    span: str,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    normalized_span = _clean_text(span)
    if not normalized_slot_prefix or not normalized_span.isdigit():
        return []
    return _numeric_signature_slots(normalized_span, slot_prefix=normalized_slot_prefix)


def _numeric_signature_value_map(value: str) -> Dict[str, str]:
    cleaned = _clean_text(value)
    if not cleaned.isdigit():
        return {}
    values: Dict[str, str] = {}
    for slot, slot_value in _numeric_signature_slots(cleaned, slot_prefix="number"):
        key = slot.removeprefix("number_")
        if key:
            values[key] = slot_value
    return values


def _numeric_signature_alignment_slots(
    *,
    source_number: str,
    citation_number: str,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    if not normalized_slot_prefix:
        return []
    source_signature_values = _numeric_signature_value_map(source_number)
    citation_signature_values = _numeric_signature_value_map(citation_number)
    slots: List[Tuple[str, str]] = []
    for signature_name in _PROVENANCE_NUMERIC_ALIGNMENT_SIGNATURES:
        source_value = _clean_text(source_signature_values.get(signature_name) or "")
        citation_value = _clean_text(citation_signature_values.get(signature_name) or "")
        if not source_value and not citation_value:
            continue
        slots.append(
            (
                f"{normalized_slot_prefix}_{signature_name}_pair",
                f"{source_value or 'none'}|{citation_value or 'none'}",
            )
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_{signature_name}_match",
                "true"
                if source_value.lower() == citation_value.lower()
                else "false",
            )
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_{signature_name}_presence_match",
                "true" if bool(source_value) == bool(citation_value) else "false",
            )
        )
    return slots


def _numeric_magnitude_bucket(value: int) -> str:
    if value < 1_000:
        return "lt_1k"
    if value < 10_000:
        return "1k_to_9k"
    if value < 100_000:
        return "10k_to_99k"
    if value < 1_000_000:
        return "100k_to_999k"
    return "1m_plus"


def _relation_span_profile(
    *,
    relation: str,
    span: str,
) -> str:
    normalized_relation = _clean_text(relation).lower()
    normalized_span = _clean_text(span)
    if not normalized_relation:
        return ""
    if not normalized_span.isdigit():
        return normalized_relation
    return f"{normalized_relation}_{_numeric_magnitude_bucket(int(normalized_span))}"


def _alpha_signature_slots(
    value: str,
    *,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    cleaned = _clean_text(value).lower()
    if not cleaned:
        return []
    letters = [character for character in cleaned if character.isalpha()]
    if not letters:
        return []
    initial = letters[0]
    terminal = letters[-1]
    vowel_count = sum(1 for character in letters if character in _VOWEL_CHARS)
    consonant_count = len(letters) - vowel_count
    slots: List[Tuple[str, str]] = [
        (f"{slot_prefix}_initial", initial),
        (f"{slot_prefix}_terminal", terminal),
        (f"{slot_prefix}_vowel_count", str(vowel_count)),
        (f"{slot_prefix}_consonant_count", str(consonant_count)),
        (
            f"{slot_prefix}_has_vowel",
            "true" if vowel_count > 0 else "false",
        ),
        (
            f"{slot_prefix}_has_consonant",
            "true" if consonant_count > 0 else "false",
        ),
        (f"{slot_prefix}_unique_char_count", str(len(set(letters)))),
        (f"{slot_prefix}_repeat_kind", _alpha_repeat_kind(letters)),
        (f"{slot_prefix}_max_run_length", str(_alpha_max_run_length(letters))),
    ]
    initial_ordinal = _alpha_ordinal(initial)
    if initial_ordinal:
        slots.append((f"{slot_prefix}_initial_ordinal", initial_ordinal))
    terminal_ordinal = _alpha_ordinal(terminal)
    if terminal_ordinal:
        slots.append((f"{slot_prefix}_terminal_ordinal", terminal_ordinal))
    return slots


def _alpha_ordinal(value: str) -> str:
    cleaned = _clean_text(value).lower()
    if len(cleaned) != 1 or not ("a" <= cleaned <= "z"):
        return ""
    return str(ord(cleaned) - ord("a") + 1)


def _alpha_repeat_kind(letters: Sequence[str]) -> str:
    if not letters:
        return ""
    if len(letters) == 1:
        return "single"
    unique_count = len(set(letters))
    if unique_count == 1:
        return "uniform_repeat"
    if unique_count == len(letters):
        return "all_distinct"
    return "mixed_repeat"


def _alpha_max_run_length(letters: Sequence[str]) -> int:
    if not letters:
        return 0
    max_run_length = 1
    current_run_length = 1
    previous = letters[0]
    for character in letters[1:]:
        if character == previous:
            current_run_length += 1
        else:
            current_run_length = 1
            previous = character
        if current_run_length > max_run_length:
            max_run_length = current_run_length
    return max_run_length


def _unique_slot_values(values: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    result: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _unique_text_values(values: Sequence[str]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _typed_identifier_slots(
    value: str,
    *,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    normalized = _clean_text(value).replace("-", "_")
    if not normalized:
        return []
    tokens = [
        token
        for token in re.split(r"[_\s]+", normalized.lower())
        if token
    ]
    if not tokens:
        return []
    slots: List[Tuple[str, str]] = [
        (f"{slot_prefix}_token_count", str(len(tokens))),
        (f"{slot_prefix}_token_prefix", tokens[0]),
        (f"{slot_prefix}_token_suffix", tokens[-1]),
    ]
    for token in tokens:
        slots.append((f"{slot_prefix}_token", token))
    mixed_token_count = 0
    alnum_segments: List[str] = []
    for token in tokens:
        if any(character.isdigit() for character in token) and any(
            character.isalpha() for character in token
        ):
            mixed_token_count += 1
        alnum_segments.extend(_alnum_segments(token))
    slots.append(
        (
            f"{slot_prefix}_has_mixed_token",
            "true" if mixed_token_count > 0 else "false",
        )
    )
    slots.append((f"{slot_prefix}_mixed_token_count", str(mixed_token_count)))
    slots.append((f"{slot_prefix}_alnum_segment_count", str(len(alnum_segments))))
    if alnum_segments:
        slots.append((f"{slot_prefix}_alnum_segment_prefix", alnum_segments[0]))
        slots.append((f"{slot_prefix}_alnum_segment_suffix", alnum_segments[-1]))
    for index, segment in enumerate(alnum_segments, start=1):
        position = str(index)
        segment_kind = _alnum_segment_kind(segment)
        slots.append((f"{slot_prefix}_alnum_segment", segment))
        slots.append((f"{slot_prefix}_alnum_segment_positioned", f"{position}:{segment}"))
        slots.append((f"{slot_prefix}_alnum_segment_kind", segment_kind))
        slots.append(
            (
                f"{slot_prefix}_alnum_segment_kind_positioned",
                f"{position}:{segment_kind}",
            )
        )
    if re.fullmatch(r"v\d+", tokens[-1]):
        slots.append((f"{slot_prefix}_version", tokens[-1]))
        stem_tokens = tokens[:-1]
    else:
        stem_tokens = tokens
    if stem_tokens:
        slots.append((f"{slot_prefix}_stem", "_".join(stem_tokens)))
    return _unique_slot_values(slots)


def _phrase_values(values: Sequence[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _alnum_segments(token: str) -> List[str]:
    cleaned = _clean_text(token).lower()
    if not cleaned:
        return []
    return [segment for segment in re.findall(r"[a-z]+|\d+", cleaned) if segment]


def _alnum_segment_kind(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return "other"
    if cleaned.isdigit():
        return "numeric"
    if cleaned.isalpha():
        return "alpha"
    return "other"


def _selected_frame(document: ModalIRDocument) -> str:
    metadata_frame = _clean_text(document.metadata.get("selected_frame") or "")
    if metadata_frame:
        return metadata_frame
    frame_logic = getattr(document, "frame_logic", None)
    if frame_logic is not None:
        frame_logic_frame = _clean_text(getattr(frame_logic, "selected_frame", "") or "")
        if frame_logic_frame:
            return frame_logic_frame
    for frame in getattr(document, "frame_candidates", []):
        frame_id = _clean_text(getattr(frame, "frame_id", "") or "")
        if frame_id:
            return frame_id
    frame_terms_by_frame = _frame_ontology_terms_by_frame(document)
    for frame_id in sorted(frame_terms_by_frame):
        normalized = _clean_text(frame_id)
        if normalized:
            return normalized
    return ""


def _tokenize_for_similarity(text: str) -> List[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_'-]*", str(text or ""))
    ]


__all__ = [
    "DecodedModalPhrase",
    "DecodedModalText",
    "decode_modal_ir_document",
    "decoded_modal_phrase_slot_text_map",
    "modal_formula_to_text",
    "modal_text_token_similarity",
]
