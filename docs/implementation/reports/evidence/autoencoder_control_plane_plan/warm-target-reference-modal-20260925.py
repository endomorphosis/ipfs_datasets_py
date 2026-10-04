"""Historical helper definitions for a controlled diagnostic performance ablation.

Load these exact definitions into a copy of the canonical decompiler globals.
This reference is not a production implementation or an admission artifact.
"""
from __future__ import annotations

# Source: ipfs_datasets_py/logic/modal/decompiler.py
# Original source SHA-256: 2aa99133971449edbb66d1f9b4023b7a97d9d2a2df3cb4f4ca7de0c481b15213

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
    if re.search(r"\bfiscal\s+years?\b", normalized) and re.search(
        r"\b(?:allotments?|appropriat(?:e|ed|ion|ions))\b",
        normalized,
    ):
        add("fiscal_year_allotment")
    if re.search(r"\bnational\s+military\s+parks?\b", normalized):
        add("national_military_park_resource")
    if re.search(
        r"\b(?:national\s+and\s+international\s+monuments?\s+and\s+memorials?|"
        r"international\s+monuments?\s+and\s+memorials?)\b",
        normalized,
    ):
        add("monument_memorial_administration")
        add("national_international_memorial_resource")
    if re.search(
        r"\b(?:special\s+agents?\s+and\s+commissioners?|"
        r"officers?\s+of\s+indian\s+affairs|indian\s+affairs)\b",
        normalized,
    ) and re.search(r"\b(?:appoint|appointed|agents?|commissioners?)\b", normalized):
        add("special_agent_appointment")
        add("indian_affairs_commissioner_authority")
    if re.search(r"\binvestigat(?:e|ion|ing)\b.{0,80}\bindian\s+affairs\b", normalized):
        add("indian_affairs_investigation")
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
        r"\b(?:payments?|fees?)\b.{0,40}\b(?:or|and)\b.{0,40}\b(?:payments?|fees?)\b|"
        r"\b(?:payments?\s+or\s+fees?|fees?\s+or\s+payments?)\b",
        normalized,
    ):
        add("payment_or_fee_remedy")
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
    if (
        re.search(
            r"\b(?:transfer|transferred|transferring)\b.{0,80}\bfunds?\b",
            normalized,
        )
        or re.search(
            r"\b(?:amounts?|appropriation|appropriated)\b.{0,120}"
            r"\b(?:transfer|transferred|transferring)\b.{0,120}"
            r"\b(?:account|appropriation|funds?)\b",
            normalized,
        )
        or re.search(
            r"\b(?:transfer|transferred|transferring)\b.{0,120}"
            r"\b(?:amounts?|appropriation|appropriated|account|funds?)\b",
            normalized,
        )
    ):
        add("fund_transfer_authority")
    if re.search(
        r"\b(?:carry\s+out|establish(?:ing)?|administer(?:ing)?)\b.{0,120}"
        r"\b(?:program|activities|awards?)\b",
        normalized,
    ):
        add("program_activity_implementation")
    if re.search(
        r"\b(?:university[-\s]+based\b.{0,120}\bpolicy\s+collaboration\s+program|"
        r"defense\s+nuclear\s+policy\s+collaboration\s+program)\b",
        normalized,
    ):
        add("defense_nuclear_policy_collaboration")
    if re.search(
        r"\bpolicy\s+research\s+consortium\b|"
        r"\bconsortium\b.{0,80}\binstitutions?\s+of\s+higher\s+education\b",
        normalized,
    ):
        add("policy_research_consortium")
        add("university_policy_research_consortium")
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
        if cue_key not in cues and re.search(
            rf"(?<!\w){re.escape(cue_surface)}(?!\w)", normalized_text
        ):
            cues.append(cue_key)
    return cues
