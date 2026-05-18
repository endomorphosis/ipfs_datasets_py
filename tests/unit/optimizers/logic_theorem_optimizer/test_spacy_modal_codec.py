"""Tests for spaCy-based modal encoder / IR / decoder workflows."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import ModalTodoSupervisor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoder,
    SpaCyModalCodec,
    SpaCyModalDecoder,
    SpaCyModalIRCompiler,
    modal_ambiguity_signals,
    ranked_modal_families,
)

pytest.importorskip("spacy")

_USCODE_25_422_HEADING_ONLY_TEXT = "Housing voucher benefits and utility allowances."
_USCODE_48_1572_HEADING_ONLY_TEXT = "Administrative notice and hearing."
_USCODE_42_6323_HEADING_ONLY_TEXT = "Notice and hearing requirements."
_USCODE_7_473A_SEC_HEADING_TEXT = "Sec. 473a - Cotton classification services."
_USCODE_20_1067J_SEC_HEADING_TEXT = "Sec. 1067j - Administrative provisions."
_USCODE_15_2501_SEC_HEADING_TEXT = "Sec. 2501 - Congressional findings and policy."
_USCODE_7_431_TODO_TEXT = "Sec. 431 - Declaration of policy."
_USCODE_6_257_TODO_TEXT = "Sec. 257 - National planning scenarios and preparedness targets."
_USCODE_45_81_TO_92_TODO_TEXT = "Secs. 81 to 92. Repealed."
_USCODE_46_55318_TODO_TEXT = (
    "§55318. Effect on other law This subchapter does not affect chapter 5 of title 5. "
    "(Pub. L. 109–304, §8(c), Oct. 6, 2006, 120 Stat. 1648.) Historical and Revision "
    "Notes Revised Section Source (U.S. Code) Source (Statutes at Large) 55318 46 "
    "App.:1241p. Pub. L. 99–198, title XI, §1143, Dec. 23, 1985, 99 Stat. 1496. The "
    "words \"section 1707a(b)(8) of title 7\" are omitted because the provision referred "
    "to has been repealed."
)
_USCODE_8_606_TODO_TEXT = (
    "U.S.C. Title 8 - ALIENS AND NATIONALITY 8 U.S.C. United States Code, 2024 Edition "
    "Title 8 - ALIENS AND NATIONALITY CHAPTER 11 - NATIONALITY SUBCHAPTER II - NATIONALITY "
    "AT BIRTH Sec. 606 - Transferred From the U.S. Government Publishing Office, www.gpo.gov "
    "§606. Transferred Editorial Notes Codification Section transferred to section 1421l of "
    "Title 48, Territories and Insular Possessions. That section was later repealed. See "
    "section 1407 of this title."
)
_USCODE_46_115_TODO_TEXT = (
    "§115. Vessel In this title, the term \"vessel\" has the meaning given that term in "
    "section 3 of title 1. (Pub. L. 109–304, §4, Oct. 6, 2006, 120 Stat. 1487.) Historical "
    "and Revision Notes Revised Section Source (U.S. Code) Source (Statutes at Large) 115 "
    "46:2101(45)."
)
_USCODE_36_110105_TODO_TEXT = (
    "U.S.C. Title 36 - PATRIOTIC AND NATIONAL OBSERVANCES, CEREMONIES, AND ORGANIZATIONS 36 U.S.C. United States Co"
    "de, 2024 Edition Title 36 - PATRIOTIC AND NATIONAL OBSERVANCES, CEREMONIES, AND ORGANIZATIONS Subtitle II - Pa"
    "triotic and National Organizations Part B - Organizations CHAPTER 1101 - JEWISH WAR VETERANS OF THE UNITED STA"
    "TES OF AMERICA, INCORPORATED Sec. 110105 - Governing body From the U.S. Government Publishing Office, www.gpo."
    "gov §110105. Governing body (a) Board of Directors .—The board of directors and the responsibilities of the bo"
    "ard are as provided in the articles of incorporation. (b) Officers .—The officers and the election of officers"
    " are as provided in the articles of incorporation. (Pub. L. 105–225, Aug. 12, 1998, 112 Stat. 1367.) Historica"
    "l and Revision Notes Revised Section Source (U.S. Code) Source (Statutes at Large) 110105(a) 36:2706. Aug. 21,"
    " 1984, Pub. L. 98–391, §§6, 7, 98 Stat. 1359. 110105(b) 36:2707."
)
_USCODE_25_450_TODO_TEXT = (
    "U.S.C. Title 25 - INDIANS 25 U.S.C. United States Code, 2024 Edition Title 25 - INDIANS CHAPTER 14 - MISCELLAN"
    "EOUS SUBCHAPTER II - INDIAN SELF-DETERMINATION AND EDUCATION ASSISTANCE Sec. 450 - Transferred From the U.S. G"
    "overnment Publishing Office, www.gpo.gov §450. Transferred Editorial Notes Codification Section 450 was editor"
    "ially reclassified as section 5301 of this title."
)
_USCODE_25_5396_TODO_TEXT = (
    "U.S.C. Title 25 - INDIANS 25 U.S.C. United States Code, 2024 Edition Title 25 - INDIANS CHAPTER 46 - INDIAN SE"
    "LF-DETERMINATION AND EDUCATION ASSISTANCE SUBCHAPTER V - TRIBAL SELF-GOVERNANCE-INDIAN HEALTH SERVICE Sec. 539"
    "6 - Application of other sections of this chapter From the U.S. Government Publishing Office, www.gpo.gov §539"
    "6. Application of other sections of this chapter (a) Mandatory application All provisions of sections 5305(b),"
    " 5306, 5307, 5321(c) and (d), 5323, 5324(k) and (l), 5325(a) through (k), and 5332 of this title and section 3"
    "14 of Public Law 101–512 (coverage under chapter 171 of title 28, commonly known as the \"Federal Tort Claims A"
    "ct\"), to the extent not in conflict with this subchapter, shall apply to compacts and funding agreements autho"
    "rized by this subchapter. (b) Discretionary application At the request of a participating Indian tribe, any ot"
    "her provision of subchapter I of this chapter, to the extent such provision is not in conflict with this subch"
    "apter, shall be made a part of a funding agreement or compact entered into under this subchapter. The Secretar"
    "y is obligated to include such provision at the option of the participating Indian tribe or tribes. If such pr"
    "ovision is incorporated it shall have the same force and effect as if it were set out in full in this subchapt"
    "er. In the event an Indian tribe requests such incorporation at the negotiation stage of a compact or funding "
    "agreement, such incorporation shall be deemed effective immediately and shall control the negotiation and resu"
    "lting compact and funding agreement. (Pub. L. 93–638, title V, §516, as added Pub. L. 106–260, §4, Aug. 18, 20"
    "00, 114 Stat. 729.) Editorial Notes References in Text Section 314 of Pub. L. 101–512, referred to in subsec. "
    "(a), is section 314 of Pub. L. 101–512, which is set out as a note under section 5321 of this title. Subchapte"
    "r I of this chapter, referred to in subsec. (b), was in the original \"title I\", meaning title I of Pub. L. 93–"
    "638, known as the Indian Self-Determination Act, which is classified principally to subchapter I (§5321 et seq"
    ".) of this chapter. For complete classification of title I to the Code, see Short Title note set out under sec"
    "tion 5301 of this title and Tables. Codification Section was formerly classified to section 458aaa–15 of this "
    "title prior to editorial reclassification and renumbering as this section."
)
_USCODE_25_507_PACKET_519_TEXT = (
    "U.S.C. Title 25 - INDIANS 25 U.S.C. United States Code, 2024 Edition "
    "Title 25 - INDIANS CHAPTER 14 - MISCELLANEOUS SUBCHAPTER VIII - INDIANS "
    "IN OKLAHOMA: PROMOTION OF WELFARE Sec. 507 - Transferred From the U.S. "
    "Government Publishing Office, www.gpo.gov §507. Transferred Editorial "
    "Notes Codification Section 507 was editorially reclassified as section "
    "5207 of this title."
)
_USCODE_10_167_PACKET_519_TEXT = (
    "U.S.C. Title 10 - ARMED FORCES 10 U.S.C. United States Code, 2024 Edition "
    "Title 10 - ARMED FORCES PART I - ORGANIZATION AND GENERAL MILITARY POWERS "
    "CHAPTER 6 - COMBATANT COMMANDS Sec. 167 - Unified combatant command for "
    "special operations forces From the U.S. Government Publishing Office, "
    "www.gpo.gov §167. Unified combatant command for special operations forces "
    "(a) Establishment. With the advice and assistance of the Chairman of the "
    "Joint Chiefs of Staff, the President, through the Secretary of Defense, "
    "shall establish under section 161 of this title a unified combatant "
    "command for special operations forces. (b) Assignment of Forces. Unless "
    "otherwise directed by the Secretary of Defense, all active and reserve "
    "special operations forces of the armed forces stationed in the United "
    "States shall be assigned to the special operations command. (c) Grade of "
    "Commander. The commander of the special operations command shall hold the "
    "grade of general or admiral while serving in that position. (d) Command "
    "of Activity or Mission. Unless otherwise directed by the President or the "
    "Secretary of Defense, a special operations activity or mission shall be "
    "conducted under the command of the commander of the unified combatant "
    "command in whose geographic area the activity or mission is to be "
    "conducted."
)
_USCODE_38_8112_PACKET_519_TEXT = (
    "U.S.C. Title 38 - VETERANS' BENEFITS 38 U.S.C. United States Code, 2024 "
    "Edition Title 38 - VETERANS' BENEFITS PART VI - ACQUISITION AND "
    "DISPOSITION OF PROPERTY CHAPTER 81 - ACQUISITION AND OPERATION OF "
    "HOSPITAL AND DOMICILIARY FACILITIES; PROCUREMENT AND SUPPLY; ENHANCED-USE "
    "LEASES OF REAL PROPERTY SUBCHAPTER I - ACQUISITION AND OPERATION OF "
    "MEDICAL FACILITIES Sec. 8112 - Partial relinquishment of legislative "
    "jurisdiction From the U.S. Government Publishing Office, www.gpo.gov "
    "§8112. Partial relinquishment of legislative jurisdiction The Secretary, "
    "on behalf of the United States, may relinquish to the State in which any "
    "lands or interests under the supervision or control of the Secretary are "
    "situated, such measure of legislative jurisdiction over such lands or "
    "interests as is necessary to establish concurrent jurisdiction between the "
    "Federal Government and the State concerned. Such partial relinquishment "
    "of legislative jurisdiction shall be initiated by filing a notice with the "
    "Governor of the State concerned and shall take effect upon acceptance by "
    "such State. Editorial Notes Prior Provisions Provisions similar to those "
    "comprising this section were contained in former section 5007 of this "
    "title prior to the general revision of this subchapter by Pub. L. 96-22."
)
_USCODE_36_170307_TODO_TEXT = (
    "Administrative notice and hearing procedures are established for this subchapter."
)
_USCODE_10_1095C_TODO_TEXT = (
    "Administrative review procedures are established for health care collection actions."
)
_USCODE_19_2113_TODO_TEXT = (
    "Administrative notice and hearing procedures are established for import petitions."
)
_USCODE_2_5602_SYMBOLIC_VALIDITY_TODO_TEXT = (
    "U.S.C. Title 2 - THE CONGRESS 2 U.S.C. United States Code, 2024 Edition "
    "Title 2 - THE CONGRESS CHAPTER 55 - HOUSE OF REPRESENTATIVES OFFICERS AND "
    "ADMINISTRATION SUBCHAPTER VIII - SERGEANT AT ARMS Sec. 5602 - Tenure of "
    "office of Sergeant at Arms From the U.S. Government Publishing Office, "
    "www.gpo.gov §5602. Tenure of office of Sergeant at Arms Any person duly "
    "elected and qualified as Sergeant at Arms of the House of Representatives "
    "shall continue in said office until his successor is chosen and qualified, "
    "subject however, to removal by the House of Representatives. (Oct. 1, "
    "1890, ch. 1256, §6, 26 Stat. 646.) Editorial Notes Codification Section "
    "was formerly classified to section 83 of this title prior to editorial "
    "reclassification and renumbering as this section."
)
_USCODE_5_5348_SYMBOLIC_VALIDITY_TODO_TEXT = (
    "U.S.C. Title 5 - GOVERNMENT ORGANIZATION AND EMPLOYEES 5 U.S.C. United "
    "States Code, 2024 Edition Title 5 - GOVERNMENT ORGANIZATION AND EMPLOYEES "
    "PART III - EMPLOYEES Subpart D - Pay and Allowances CHAPTER 53 - PAY RATES "
    "AND SYSTEMS SUBCHAPTER IV - PREVAILING RATE SYSTEMS Sec. 5348 - Crews of "
    "vessels From the U.S. Government Publishing Office, www.gpo.gov §5348. "
    "Crews of vessels (a) Except as provided by subsection (b) of this section, "
    "the pay of officers and members of crews of vessels excepted from chapter "
    "51 of this title by section 5102(c)(8) of this title shall be fixed and "
    "adjusted from time to time as nearly as is consistent with the public "
    "interest in accordance with prevailing rates and practices in the maritime "
    "industry. (b) Vessel employees in an area where inadequate maritime "
    "industry practice exists and vessel employees of the Corps of Engineers "
    "shall have their pay fixed and adjusted under the provisions of this "
    "subchapter other than this section, as appropriate. Statutory Notes and "
    "Related Subsidiaries Effective Date of 1972 Amendment Amendment by Pub. L. "
    "92–392 effective on first day of first applicable pay period beginning on "
    "or after 90th day after Aug. 19, 1972, see section 15(a) of Pub. L. "
    "92–392, set out as an Effective Date note under section 5341 of this "
    "title."
)
_USCODE_42_15251_SYMBOLIC_VALIDITY_TODO_TEXT = (
    "§15251. Transferred Editorial Notes Codification Section 15251 was "
    "editorially reclassified as section 50321 of Title 34, Crime Control and "
    "Law Enforcement."
)
_USCODE_2_88B_5_TODO_TEXT = "The administrative notice and hearing procedures."
_USCODE_42_18431_SYMBOLIC_VALIDITY_TODO_TEXT = (
    "The notice and hearing requirements for administrative review."
)
_USCODE_42_12313_SYMBOLIC_VALIDITY_TODO_TEXT = (
    "The administrative notice and hearing procedures for certification."
)
_USCODE_43_2430_PACKET_143_TODO_TEXT = (
    "The administrative notice and hearing procedures for offshore mineral leasing "
    "adjustments and adjudications."
)
_USCODE_2_453_PACKET_39_TEXT = "The oath of office."
_USCODE_9_6_PACKET_39_TEXT = "The application heard as motion."
_USCODE_43_1656_PACKET_39_TEXT = "The withdrawal and reservation of lands."


def _coarse_uscode_heading_noise_text(section: str, heading: str) -> str:
    noise_tokens = " ".join(chr(ord("a") + (index % 26)) for index in range(160))
    return (
        "U S C title archive register digest taxonomy index chapter crosswalk "
        f"sec {section} {heading} "
        f"{noise_tokens}"
    )


def test_spacy_encoder_compiles_modal_ir_without_downloaded_model() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The agency must make records promptly available to any person.",
        document_id="sample-5-552",
        citation="5 U.S.C. 552",
        source="us_code",
    )

    modal_ir = SpaCyModalIRCompiler().compile(encoding)

    assert encoding.used_fallback_model is True
    assert encoding.tokens
    assert encoding.cues[0].family == "deontic"
    assert modal_ir.metadata["llm_call_count"] == 0
    assert modal_ir.formulas[0].operator.family == "deontic"
    assert "records" in modal_ir.formulas[0].predicate.name


def test_spacy_compiler_extracts_condition_and_exception_slots() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "If the application is complete, the agency must issue written notice unless waived.",
        document_id="sample-condition-exception",
    )

    modal_ir = SpaCyModalIRCompiler().compile(encoding)
    deontic_formula = next(
        formula for formula in modal_ir.formulas if formula.operator.family == "deontic"
    )

    assert "if the application is complete" in deontic_formula.conditions
    assert "unless waived" in deontic_formula.exceptions


def test_spacy_encoder_ignores_calendar_month_may_as_permission_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall make the payment after May 13, 2002, and a producer may request review.",
        document_id="sample-may-date-literal",
    )

    may_cues = [cue for cue in encoding.cues if cue.cue.lower() == "may"]

    assert may_cues
    assert len(may_cues) == 1
    assert may_cues[0].family == "deontic"
    assert any(cue.family == "temporal" and cue.cue.lower() == "after" for cue in encoding.cues)


def test_spacy_encoder_treats_non_deadline_by_as_non_temporal_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall provide notice by the Comptroller.",
        document_id="sample-by-non-temporal",
    )

    assert any(cue.family == "deontic" and cue.cue.lower() == "shall" for cue in encoding.cues)
    assert not any(
        cue.family == "temporal" and cue.cue.lower() == "by"
        for cue in encoding.cues
    )


def test_spacy_encoder_treats_deadline_by_as_temporal_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall provide notice by January 1, 2030.",
        document_id="sample-by-deadline",
    )

    assert any(
        cue.family == "temporal" and cue.cue.lower() == "by"
        for cue in encoding.cues
    )


def test_spacy_encoder_treats_within_department_as_non_temporal_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall designate a team within the Department of Agriculture.",
        document_id="sample-within-department-non-temporal",
    )

    assert any(cue.family == "deontic" and cue.cue.lower() == "shall" for cue in encoding.cues)
    assert not any(
        cue.family == "temporal" and cue.cue.lower() == "within"
        for cue in encoding.cues
    )
    signals = modal_ambiguity_signals(encoding)
    assert signals["has_temporal_within_scope"] is False
    assert signals["has_temporal_scope"] is False


def test_spacy_encoder_treats_within_days_as_temporal_cue_and_scope() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall provide notice within 30 days after review.",
        document_id="sample-within-days-temporal",
    )

    assert any(
        cue.family == "temporal" and cue.cue.lower() == "within"
        for cue in encoding.cues
    )
    signals = modal_ambiguity_signals(encoding)
    assert signals["has_temporal_within_scope"] is True
    assert signals["has_temporal_scope"] is True


def test_spacy_encoder_detects_editorial_frame_scope_signals() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        (
            "Editorial Notes Codification Section 5602 was formerly classified to "
            "section 83 of this title prior to editorial reclassification and "
            "renumbering as this section."
        ),
        document_id="sample-editorial-frame-scope",
    )

    signals = modal_ambiguity_signals(encoding)
    assert signals["has_frame_context"] is True
    assert signals["has_frame_scope_phrase"] is True
    assert signals["has_frame_editorial_scope_phrase"] is True


def test_spacy_decoder_promotes_frame_logits_over_hybrid_for_editorial_scope_text() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="2",
        section="5602",
        text=(
            "Editorial Notes Codification Section 5602 was formerly classified to "
            "section 83 of this title prior to editorial reclassification and "
            "renumbering as this section."
        ),
    )

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "hybrid", "temporal"),
    )

    assert logits["frame"] > logits["hybrid"]


def test_spacy_decoder_promotes_frame_logits_over_temporal_for_editorial_scope_text() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="2",
        section="5602",
        text=(
            "Editorial Notes Codification Section 5602 was formerly classified to "
            "section 83 of this title after editorial reclassification and "
            "renumbering as this section."
        ),
    )

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "hybrid", "temporal"),
    )

    assert logits["frame"] > logits["temporal"]


def test_spacy_codec_debiases_generic_frame_cues_when_deontic_force_is_present() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="42",
        section="247b",
        text=(
            "Authority under this section and jurisdiction under this chapter "
            "shall apply."
        ),
    )

    ranking = ranked_modal_families(codec.encode_sample(sample))

    assert ranking[0]["family"] == "deontic"
    assert any(item["family"] == "frame" and item["count"] >= 1 for item in ranking)
    deontic_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "deontic"
    )
    frame_share = next(
        float(item["share"])
        for item in ranking
        if item["family"] == "frame"
    )
    assert deontic_share > frame_share


def test_spacy_decoder_debiases_generic_frame_logits_when_deontic_force_is_present() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="42",
        section="1395w",
        text=(
            "Authority under this section and jurisdiction under this chapter "
            "shall apply."
        ),
    )

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("deontic", "frame", "temporal"),
    )

    assert logits["deontic"] > logits["frame"]


def test_spacy_decoder_debiases_generic_frame_logits_when_conditional_scope_is_present() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="43",
        section="1656",
        text="Authority under this chapter applies pursuant to subsection (b).",
    )

    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("frame", "conditional_normative", "deontic"),
    )

    assert logits["conditional_normative"] > logits["frame"]


def test_spacy_decoder_boosts_temporal_logits_from_scope_without_temporal_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="47",
        section="219",
        text="The agency shall provide written notice before each annual review deadline.",
    )
    encoding = codec.encode_sample(sample)

    assert not any(cue.family == "temporal" for cue in encoding.cues)
    logits = codec.family_logits_for_sample(
        sample,
        modal_families=("deontic", "temporal", "frame"),
    )

    assert logits["deontic"] > logits["temporal"]
    assert logits["temporal"] > -0.25


def test_spacy_encoder_extracts_conditional_terms_and_conditions_cue() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The Secretary shall and must act under such terms and conditions as the Secretary prescribes.",
        document_id="sample-terms-and-conditions-conditional",
    )

    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "under such terms and conditions"
        for cue in encoding.cues
    )


def test_spacy_encoder_treats_the_following_as_non_temporal_list_intro() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The following shall apply: (1) recordkeeping requirements; (2) audit procedures.",
        document_id="sample-following-list-intro",
    )

    assert not any(
        cue.family == "temporal" and cue.cue.lower() == "following"
        for cue in encoding.cues
    )


def test_spacy_encoder_extracts_conditional_cue_except_as_provided_in() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "Except as provided in subsection (b), the Secretary shall issue a determination.",
        document_id="sample-except-as-provided-in",
    )

    assert any(
        cue.family == "conditional_normative"
        and cue.cue.lower() == "except as provided in"
        for cue in encoding.cues
    )


def test_spacy_encoder_extracts_epistemic_cues_for_knowledge_and_belief() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "A person with knowledge of the violation has reason to believe the report is false.",
        document_id="sample-knowledge-belief",
    )

    assert any(
        cue.family == "epistemic"
        and cue.cue.lower() in {"knowledge of", "has reason to believe"}
        for cue in encoding.cues
    )


def test_spacy_compiler_replays_uscode_editorial_status_zero_formula_cases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-2-117j-0f405de004ab24ed",
            "2 U.S.C. 117j",
            "\u00a7117j. Omitted.",
        ),
        (
            "us-code-7-450-759794f8a1f6176f",
            "7 U.S.C. 450",
            "\u00a7450. Omitted.",
        ),
        (
            "us-code-8-71-ba23a2579e9f7282",
            "8 U.S.C. 71",
            "\u00a771. Omitted.",
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_editorial_status_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_editorial_status_heading_v1"
        assert fallback.metadata["status_keyword"] == "omitted"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_sec_prefixed_transferred_heading_zero_formula_cases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-2-123b-a41bd4aaf77abbf3",
            "2 U.S.C. 123b",
            "Sec. 123b - Transferred.",
        ),
        (
            "us-code-25-478-ebbb6cefef299fc2",
            "25 U.S.C. 478",
            "Sec. 478 - Transferred.",
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_sec_prefixed_heading_zero_formula_sample_for_15_1693l() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        "Sec. 1693l - Waiver of rights.",
        document_id="us-code-15-1693l-62b207bc138a3216",
        citation="15 U.S.C. 1693l",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert modal_ir.formulas
    fallback = modal_ir.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
    assert fallback.provenance.citation == "15 U.S.C. 1693l"


def test_spacy_compiler_replays_packet_todo_samples_for_7_431_6_257_and_45_81_to_92() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-7-431-b2d3ec880a4d889f",
            "7 U.S.C. 431",
            _USCODE_7_431_TODO_TEXT,
            "__uscode_section_heading_fallback__",
            "uscode_section_heading_v1",
            "",
        ),
        (
            "us-code-6-257-73184bd2fbf238f5",
            "6 U.S.C. 257",
            _USCODE_6_257_TODO_TEXT,
            "__uscode_section_heading_fallback__",
            "uscode_section_heading_v1",
            "",
        ),
        (
            "us-code-45-81 to 92.-1562d5d82d7f6c80",
            "45 U.S.C. §§ 81 to 92.",
            _USCODE_45_81_TO_92_TODO_TEXT,
            "__uscode_editorial_status_fallback__",
            "uscode_editorial_status_heading_v1",
            "repealed",
        ),
    ]

    for document_id, citation, text, cue, fallback_rule, status_keyword in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == cue
        assert fallback.metadata["fallback_rule"] == fallback_rule
        if status_keyword:
            assert fallback.metadata["status_keyword"] == status_keyword
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_packet_todo_samples_for_46_55318_8_606_and_46_115() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-46-55318.-a7002ab697067d67",
            "46 U.S.C. 55318.",
            _USCODE_46_55318_TODO_TEXT,
            "__uscode_section_heading_fallback__",
            "uscode_section_heading_v1",
        ),
        (
            "us-code-8-606-f7dcbbfb006072f7",
            "8 U.S.C. 606",
            _USCODE_8_606_TODO_TEXT,
            "__uscode_codification_fallback__",
            "uscode_transferred_heading_v1",
        ),
        (
            "us-code-46-115.-286a747a33fe04bb",
            "46 U.S.C. 115.",
            _USCODE_46_115_TODO_TEXT,
            "__uscode_section_heading_fallback__",
            "uscode_section_heading_v1",
        ),
    ]

    for document_id, citation, text, cue, fallback_rule in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == cue
        assert fallback.metadata["fallback_rule"] == fallback_rule
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_packet_todo_samples_for_36_110105_and_25_450() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-36-110105-c16a1da4a57f02ec",
            "36 U.S.C. 110105",
            _USCODE_36_110105_TODO_TEXT,
            "__uscode_section_heading_fallback__",
            "uscode_section_heading_v1",
        ),
        (
            "us-code-25-450-c265a65e885d4655",
            "25 U.S.C. 450",
            _USCODE_25_450_TODO_TEXT,
            "__uscode_codification_fallback__",
            "uscode_transferred_heading_v1",
        ),
    ]

    for document_id, citation, text, cue, fallback_rule in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == cue
        assert fallback.metadata["fallback_rule"] == fallback_rule
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_packet_todo_symbolic_validity_sample_for_25_5396() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_25_5396_TODO_TEXT,
        document_id="us-code-25-5396-17291bf2fa3ae3f6",
        citation="25 U.S.C. 5396",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert modal_ir.formulas
    assert any(formula.operator.family == "deontic" for formula in modal_ir.formulas)
    assert all(
        formula.provenance.citation == "25 U.S.C. 5396"
        for formula in modal_ir.formulas
    )


def test_spacy_compiler_replays_packet_todo_samples_for_25_507_10_167_and_38_8112() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-25-507-e22029a3cea8b735",
            "25 U.S.C. 507",
            _USCODE_25_507_PACKET_519_TEXT,
            True,
        ),
        (
            "us-code-10-167-c04be565137bd57c",
            "10 U.S.C. 167",
            _USCODE_10_167_PACKET_519_TEXT,
            False,
        ),
        (
            "us-code-38-8112-c323ef8fcde15329",
            "38 U.S.C. 8112",
            _USCODE_38_8112_PACKET_519_TEXT,
            False,
        ),
    ]

    for document_id, citation, text, expects_codification_fallback in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.document_id == document_id
        assert modal_ir.formulas
        assert all(formula.provenance.citation == citation for formula in modal_ir.formulas)
        if expects_codification_fallback:
            fallback = modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
        else:
            assert any(formula.operator.family == "deontic" for formula in modal_ir.formulas)


def test_spacy_compiler_replays_packet_todo_samples_for_36_170307_10_1095c_and_19_2113() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-36-170307-8767653c3220e539",
            "36 U.S.C. 170307",
            _USCODE_36_170307_TODO_TEXT,
            "notice",
        ),
        (
            "us-code-10-1095c-95cb9940fa4690f6",
            "10 U.S.C. 1095c",
            _USCODE_10_1095C_TODO_TEXT,
            "review",
        ),
        (
            "us-code-19-2113-bb39dec0898628d3",
            "19 U.S.C. 2113",
            _USCODE_19_2113_TODO_TEXT,
            "notice",
        ),
    ]

    for document_id, citation, text, procedural_keyword in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.document_id == document_id
        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_procedural_clause_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_procedural_clause_v1"
        assert fallback.metadata["procedural_keyword"] == procedural_keyword
        assert fallback.provenance.citation == citation


def test_spacy_compiler_supports_usc_and_section_symbol_citation_variants_for_sec_headings() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-7-473a-02a85f2b18cfe8ee",
            "7 U.S.C. §473a",
            _USCODE_7_473A_SEC_HEADING_TEXT,
        ),
        (
            "us-code-7-473a-02a85f2b18cfe8ee",
            "7 USC 473a",
            _USCODE_7_473A_SEC_HEADING_TEXT,
        ),
        (
            "us-code-20-1067j-13aeda303003f5af",
            "20 U.S.C. §1067j",
            _USCODE_20_1067J_SEC_HEADING_TEXT,
        ),
        (
            "us-code-20-1067j-13aeda303003f5af",
            "20 USC 1067j",
            _USCODE_20_1067J_SEC_HEADING_TEXT,
        ),
        (
            "us-code-15-2501-eb4a7816e81bb710",
            "15 U.S.C. §2501",
            _USCODE_15_2501_SEC_HEADING_TEXT,
        ),
        (
            "us-code-15-2501-eb4a7816e81bb710",
            "15 USC 2501",
            _USCODE_15_2501_SEC_HEADING_TEXT,
        ),
    ]

    for index, (document_id, citation, text) in enumerate(cases, start=1):
        encoding = encoder.encode(
            text,
            document_id=f"{document_id}:citation-variant-{index}",
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_embedded_sec_heading_zero_formula_cases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-10-2672-8dd80f359cdc8c51",
            "10 U.S.C. 2672",
            "Title 10 Armed Forces chapter heading Sec. 2672\u2014 Housing voucher benefits and utility allowances.",
        ),
        (
            "us-code-26-45N-50d302a360db7728",
            "26 U.S.C. 45N",
            "Title 26 Internal Revenue Code chapter heading Sec. 45N\u2014 Clean fuel production credit.",
        ),
        (
            "us-code-12-548-2c44bdc47b86c5f0",
            "12 U.S.C. 548",
            "Title 12 Banks and Banking chapter heading Sec. 548\u2014 State taxation of national banking associations.",
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_symbolic_validity_todo_samples_with_coarse_section_heading_fallback() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-7-3125-7e90453fbb54b8b5",
            "7 U.S.C. 3125",
            "3125",
            "administrative notice hearing procedures",
        ),
        (
            "us-code-15-828-103d21b6b8cb41ed",
            "15 U.S.C. 828",
            "828",
            "administrative notice hearing records",
        ),
        (
            "us-code-22-2878-e0e935df7cbf1b94",
            "22 U.S.C. 2878",
            "2878",
            "administrative notice hearing review",
        ),
    ]

    for document_id, citation, section, heading in cases:
        encoding = encoder.encode(
            _coarse_uscode_heading_noise_text(section, heading),
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_section_heading_coarse_v1"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_symbolic_validity_todo_samples_for_2_5602_5_5348_and_42_15251() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-2-5602-ed23b79794b2e0a4",
            "2 U.S.C. 5602",
            _USCODE_2_5602_SYMBOLIC_VALIDITY_TODO_TEXT,
        ),
        (
            "us-code-5-5348-f0250f870668e53f",
            "5 U.S.C. 5348",
            _USCODE_5_5348_SYMBOLIC_VALIDITY_TODO_TEXT,
        ),
        (
            "us-code-42-15251.-c8bc40200627c975",
            "42 U.S.C. 15251.",
            _USCODE_42_15251_SYMBOLIC_VALIDITY_TODO_TEXT,
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.document_id == document_id
        assert modal_ir.formulas
        assert all(formula.provenance.citation == citation for formula in modal_ir.formulas)
        if citation == "42 U.S.C. 15251.":
            fallback = modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_codification_transfer_heading_v1"


def test_spacy_compiler_replays_packet_todo_samples_for_2_88b_5_42_18431_and_42_12313() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-2-88b-5-94883a45ddc4a6db",
            "2 U.S.C. 88b-5",
            _USCODE_2_88B_5_TODO_TEXT,
        ),
        (
            "us-code-42-18431.-b72b735d11b81b90",
            "42 U.S.C. 18431.",
            _USCODE_42_18431_SYMBOLIC_VALIDITY_TODO_TEXT,
        ),
        (
            "us-code-42-12313.-c1053dbe1a049f60",
            "42 U.S.C. 12313.",
            _USCODE_42_12313_SYMBOLIC_VALIDITY_TODO_TEXT,
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.document_id == document_id
        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_packet_todo_long_heading_sample_for_43_2430() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    encoding = encoder.encode(
        _USCODE_43_2430_PACKET_143_TODO_TEXT,
        document_id="us-code-43-2430.-7bfbe56b01b9ee78",
        citation="43 U.S.C. 2430.",
        source="us_code",
    )
    modal_ir = compiler.compile(encoding)

    assert modal_ir.document_id == "us-code-43-2430.-7bfbe56b01b9ee78"
    assert modal_ir.formulas
    fallback = modal_ir.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
    assert fallback.provenance.citation == "43 U.S.C. 2430."


def test_spacy_compiler_replays_packet_todo_article_prefixed_heading_samples_for_2_453_9_6_and_43_1656() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-2-453-868ad5bf81742f35",
            "2 U.S.C. 453",
            _USCODE_2_453_PACKET_39_TEXT,
        ),
        (
            "us-code-9-6-725aa2302c64ab87",
            "9 U.S.C. 6",
            _USCODE_9_6_PACKET_39_TEXT,
        ),
        (
            "us-code-43-1656.-ee86a662b13291c8",
            "43 U.S.C. 1656.",
            _USCODE_43_1656_PACKET_39_TEXT,
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.document_id == document_id
        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_uscode_declarative_statement_zero_formula_cases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-22-2688-83d45528085ab9e0",
            "22 U.S.C. 2688",
            (
                "U.S.C. Title 22 - FOREIGN RELATIONS AND INTERCOURSE 22 U.S.C. "
                "United States Code, 2024 Edition Title 22 - FOREIGN RELATIONS "
                "AND INTERCOURSE CHAPTER 38 - DEPARTMENT OF STATE Sec. 2688 - "
                "Ambassadors; criteria regarding selection and confirmation From the "
                "U.S. Government Publishing Office, www.gpo.gov \u00a72688. Ambassadors; "
                "criteria regarding selection and confirmation It is the sense of "
                "the Congress that the position of United States ambassador to a "
                "foreign country should be accorded to men and women possessing "
                "clearly demonstrated competence to perform ambassadorial duties. "
                "No individual should be accorded the position of United States "
                "ambassador to a foreign country primarily because of financial "
                "contributions to political campaigns. (Aug. 1, 1956, ch. 841, "
                "title I, \u00a718, as added Pub. L. 94\u2013141, title I, \u00a7104, Nov. 29, "
                "1975, 89 Stat. 757; renumbered title I, Pub. L. 97\u2013241, title II, "
                "\u00a7202(a), Aug. 24, 1982, 96 Stat. 282.)"
            ),
            "sense_of_congress",
        ),
        (
            "us-code-7-7311-017c4d8b52982ca1",
            "7 U.S.C. 7311",
            (
                "U.S.C. Title 7 - AGRICULTURE 7 U.S.C. United States Code, 2024 "
                "Edition Title 7 - AGRICULTURE CHAPTER 100 - AGRICULTURAL MARKET "
                "TRANSITION SUBCHAPTER VII - COMMISSION ON 21st CENTURY PRODUCTION "
                "AGRICULTURE Sec. 7311 - Establishment From the U.S. Government "
                "Publishing Office, www.gpo.gov \u00a77311. Establishment There is "
                "established a commission to be known as the \"Commission on 21st "
                "Century Production Agriculture\" (in this subchapter referred to as "
                "the \"Commission\"). (Pub. L. 104\u2013127, title I, \u00a7181, Apr. 4, "
                "1996, 110 Stat. 938.)"
            ),
            "establishment_clause",
        ),
        (
            "us-code-15-2402-7e27f5e59f9ba39e",
            "15 U.S.C. 2402",
            (
                "U.S.C. Title 15 - COMMERCE AND TRADE 15 U.S.C. United States "
                "Code, 2024 Edition Title 15 - COMMERCE AND TRADE CHAPTER 51 - "
                "NATIONAL PRODUCTIVITY AND QUALITY OF WORKING LIFE SUBCHAPTER I - "
                "FINDINGS, PURPOSE, AND POLICY; DEFINITIONS Sec. 2402 - "
                "Congressional statement of purpose From the U.S. Government "
                "Publishing Office, www.gpo.gov \u00a72402. Congressional statement of "
                "purpose It is the purpose of this chapter\u2014 (1) to establish a "
                "national policy which will encourage productivity growth "
                "consistent with needs of the economy, the natural environment, "
                "and the needs, rights, and best interests of management, the "
                "work force, and consumers; and (2) to establish as an independent "
                "establishment of the executive branch a National Center for "
                "Productivity and Quality of Working Life to focus, coordinate, "
                "and promote efforts to improve the rate of productivity growth. "
                "(Pub. L. 94\u2013136, title I, \u00a7102, Nov. 28, 1975, 89 Stat. 734.)"
            ),
            "purpose_clause",
        ),
    ]

    for document_id, citation, text, statement_hint in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_declarative_statement_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_declarative_statement_v1"
        assert fallback.metadata["statement_hint"] == statement_hint
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_heading_only_zero_formula_cases_for_25_422_48_1572_and_42_6323() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-25-422-f3f166961e45b585",
            "25 U.S.C. 422",
            _USCODE_25_422_HEADING_ONLY_TEXT,
        ),
        (
            "us-code-48-1572.-8711c64e2d6b256c",
            "48 U.S.C. 1572.",
            _USCODE_48_1572_HEADING_ONLY_TEXT,
        ),
        (
            "us-code-42-6323.-1c7e7d2f53c36e15",
            "42 U.S.C. 6323.",
            _USCODE_42_6323_HEADING_ONLY_TEXT,
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
        assert fallback.provenance.citation == citation


def test_spacy_decoder_vector_and_family_logits_are_deterministic() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must make records promptly available.",
    )

    first = codec.decode_sample_embedding(sample, dimensions=6)
    second = codec.decode_sample_embedding(sample, dimensions=6)
    logits = codec.family_logits_for_sample(sample, modal_families=("deontic", "temporal", "hybrid"))

    assert first == second
    assert len(first) == 6
    assert any(value != 0.0 for value in first)
    assert logits["deontic"] > logits["temporal"]


def test_spacy_codec_exposes_text_features_without_sample_ids() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must make records promptly available.",
    )

    features = codec.feature_keys_for_sample(sample)

    assert features
    assert any(feature.startswith("cue:deontic") for feature in features)
    assert all(sample.sample_id not in feature for feature in features)


def test_spacy_codec_ranks_modal_families_from_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall provide notice within 30 days.",
    )

    ranking = ranked_modal_families(codec.encode_sample(sample))

    assert ranking
    assert ranking[0]["family"] in {"deontic", "temporal"}
    assert ranking[0]["count"] >= 1
    assert abs(sum(item["share"] for item in ranking) - 1.0) <= 1e-6


def test_spacy_codec_lowers_initial_family_cross_entropy() -> None:
    sample = build_us_code_sample(
        title="42",
        section="1983",
        text="A person may bring an action when rights are deprived under color of law.",
    )
    plain = AdaptiveModalAutoencoder()
    spacy = AdaptiveModalAutoencoder(
        feature_codec=SpaCyModalCodec(
            encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
        )
    )

    plain_eval = plain.evaluate([sample])
    spacy_eval = spacy.evaluate([sample])

    assert spacy_eval.cross_entropy_loss < plain_eval.cross_entropy_loss


def test_supervisor_with_spacy_codec_improves_loss_and_cosine() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must make records promptly available to any person.",
        embedding_vector=[0.1, 0.2, 0.3, 0.4],
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_codec=SpaCyModalCodec(
            encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
        )
    )
    supervisor = ModalTodoSupervisor()
    before = autoencoder.evaluate([sample])

    run = supervisor.optimize(
        [sample],
        autoencoder=autoencoder,
        max_iterations=2,
        max_items=4,
        learning_rate=0.5,
    )

    assert run.final_evaluation.cross_entropy_loss < before.cross_entropy_loss
    assert run.final_evaluation.reconstruction_loss < before.reconstruction_loss
    assert run.final_evaluation.embedding_cosine_similarity > before.embedding_cosine_similarity
    assert supervisor.queue.status_counts()["completed"] >= 2
