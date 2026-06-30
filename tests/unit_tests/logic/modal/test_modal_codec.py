"""Tests for the canonical deterministic modal logic codec."""

from __future__ import annotations

import importlib
from dataclasses import replace
import re
import sys

from ipfs_datasets_py.logic.modal import (
    DeterministicModalCompiler,
    DeterministicModalLogicCodec,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
    ModalLogicCodecConfig,
    decode_modal_ir_document,
    decoded_modal_phrase_slot_text_map,
    flogic_triples_to_graph_data,
    import_graph_data_to_graph_engine,
    modal_ir_to_flogic_triples,
    modal_ir_to_neo4j_graph_data,
    modal_formula_to_text,
    modal_text_token_similarity,
    synthesis_hints_from_autoencoder_introspection,
)
from ipfs_datasets_py.logic.modal.synthesis import residual_signature_for_hint
from ipfs_datasets_py.logic.modal.codec import (
    _frame_decoder_audit_features,
    _frame_ontology_audit_feature_keys,
    _frame_ontology_audit_terms,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    BM25FrameSelector,
    FrameCandidate,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import LegalModalParser
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIRFrame,
    ModalIRFrameLogic,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_000111_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000205_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000964_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_001514_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_002300_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_002680_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_003624_FAMILY_PAIRS,
    COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR,
    COMPILER_REFINED_PACKET_000593_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000001_RESCUE_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000043_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000044_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000112_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_003148_FAMILY_PAIRS,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoding,
    SpaCyModalCueFeature,
    _apply_conditional_competing_scope_soft_cap,
    _is_generic_frame_cue_debias_context,
    modal_ambiguity_signals,
    ranked_modal_families,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
    DataType,
    LogicExtractionContext,
    LogicExtractor,
)

_USCODE_2_31A_2B_TEXT = (
    "U.S.C. Title 2 - THE CONGRESS 2 U.S.C. United States Code, 2024 Edition "
    "Title 2 - THE CONGRESS CHAPTER 3 - COMPENSATION AND ALLOWANCES OF MEMBERS "
    "Sec. 31a-2b - Transferred From the U.S. Government Publishing Office, "
    "www.gpo.gov §31a–2b. Transferred Editorial Notes Codification Section "
    "31a–2b was editorially reclassified as section 6137 of this title."
)
_USCODE_46_8906_TEXT = (
    "§8906. Penalty An owner, charterer, managing operator, agent, master, or "
    "individual in charge of a vessel operated in violation of this chapter or "
    "a regulation prescribed under this chapter is liable to the United States "
    "Government for a civil penalty of not more than $25,000. The vessel also "
    "is liable in rem for the penalty. (Pub. L. 98–89, Aug. 26, 1983, 97 Stat. "
    "556; Pub. L. 104–324, title III, §306(b), Oct. 19, 1996, 110 Stat. 3918.) "
    "Historical and Revision Notes Revised section Source section (U.S. Code) "
    "8906 46:390d Section 8906 prescribes the penalties for violations of this "
    "chapter. Editorial Notes Amendments 1996 —Pub. L. 104–324 substituted "
    "\"not more than $25,000\" for \"$1,000\"."
)


def test_modal_registry_packet_001514_refines_family_cue_policy_pairs() -> None:
    """Packet 001514 pairs remain explicit compiler-registry policy entries."""
    expected_pairs = {
        ("deontic", "frame"),
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
        ("temporal", "conditional_normative"),
        ("temporal", "frame"),
    }

    assert set(COMPILER_AMBIGUITY_PACKET_001514_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_modal_registry_packet_001514_statutory_cues_are_family_specific() -> None:
    parser = LegalModalParser()
    text = (
        "Severability. If any provision is held invalid, the remainder of this "
        "section shall not be affected. Authorization of appropriations for fiscal "
        "years 2025 through 2027 is provided. The Secretary shall pay benefits."
    )

    cues_by_family: dict[str, set[str]] = {}
    for cue in parser.extract_cues(text):
        cues_by_family.setdefault(cue.family.value, set()).add(cue.cue.lower())

    assert {
        "severability",
        "held invalid",
        "remainder of this",
        "shall not be affected",
    } <= cues_by_family["conditional_normative"]
    assert {
        "authorization of appropriations",
        "for fiscal years",
    } <= cues_by_family["temporal"]
    assert {"shall pay"} <= cues_by_family["deontic"]


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
_USCODE_25_478_1_TEXT = (
    "U.S.C. Title 25 - INDIANS 25 U.S.C. United States Code, 2024 Edition Title 25 - INDIANS "
    "CHAPTER 14 - MISCELLANEOUS SUBCHAPTER V - PROTECTION OF INDIANS AND CONSERVATION OF "
    "RESOURCES Sec. 478-1 - Transferred From the U.S. Government Publishing Office, www.gpo.gov "
    "§478–1. Transferred Editorial Notes Codification Section 478–1 was editorially reclassified "
    "as section 5126 of this title."
)
_USCODE_42_6930_TEXT = (
    "§6930. Effective date (a) Preliminary notification Not later than ninety days after "
    "promulgation of regulations under section 6921 of this title identifying by its "
    "characteristics or listing any substance as hazardous waste subject to this subchapter, any "
    "person generating or transporting such substance or owning or operating a facility for "
    "treatment, storage, or disposal of such substance shall file with the Administrator (or with "
    "States having authorized hazardous waste permit programs under section 6926 of this title) a "
    "notification stating the location and general description of such activity and the "
    "identified or listed hazardous wastes handled by such person. Not later than fifteen months "
    "after November 8, 1984— (1) the owner or operator of any facility which produces a fuel (A) "
    "from any hazardous waste identified or listed under section 6921 of this title, (B) from "
    "such hazardous waste identified or listed under section 6921 of this title and any other "
    "material, (C) from used oil, or (D) from used oil and any other material; (2) the owner or "
    "operator of any facility (other than a single- or two-family residence) which burns for "
    "purposes of energy recovery any fuel produced as provided in paragraph (1) or any fuel which "
    "otherwise contains used oil or any hazardous waste identified or listed under section 6921 "
    "of this title; and (3) any person who distributes or markets any fuel which is produced as "
    "provided in paragraph (1) or any fuel which otherwise contains used oil or any hazardous "
    "waste identified or listed under section 6921 of this title 1 shall file with the "
    "Administrator (and with the State in the case of a State with an authorized hazardous waste "
    "program) a notification stating the location and general description of the facility, "
    "together with a description of the identified or listed hazardous waste involved and, in the "
    "case of a facility referred to in paragraph (1) or (2), a description of the production or "
    "energy recovery activity carried out at the facility and such other information as the "
    "Administrator deems necessary. For purposes of the preceding provisions, the term \"hazardous "
    "waste listed under section 6921 of this title\" also includes any commercial chemical product "
    "which is listed under section 6921 of this title and which, in lieu of its original intended "
    "use, is (i) produced for use as (or as a component of) a fuel, (ii) distributed for use as a "
    "fuel, or (iii) burned as a fuel. Notification shall not be required under the second "
    "sentence of this subsection in the case of facilities (such as residential boilers) where "
    "the Administrator determines that such notification is not necessary in order for the "
    "Administrator to obtain sufficient information respecting current practices of facilities "
    "using hazardous waste for energy recovery. Nothing in this subsection shall be construed to "
    "affect or impair the provisions of section 6921(b)(3) of this title. Nothing in this "
    "subsection shall affect regulatory determinations under section 6935 of this title. In "
    "revising any regulation under section 6921 of this title identifying additional "
    "characteristics of hazardous waste or listing any additional substance as hazardous waste "
    "subject to this subchapter, the Administrator may require any person referred to in the "
    "preceding provisions to file with the Administrator (or with States having authorized "
    "hazardous waste permit programs under section 6926 of this title) the notification described "
    "in the preceding provisions. Not more than one such notification shall be required to be "
    "filed with respect to the same substance. No identified or listed hazardous waste subject to "
    "this subchapter may be transported, treated, stored, or disposed of unless notification has "
    "been given as required under this subsection. (b) Effective date of regulation The "
    "regulations under this subchapter respecting requirements applicable to the generation, "
    "transportation, treatment, storage, or disposal of hazardous waste (including requirements "
    "respecting permits for such treatment, storage, or disposal) shall take effect on the date "
    "six months after the date of promulgation thereof (or six months after the date of revision "
    "in the case of any regulation which is revised after the date required for promulgation "
    "thereof). At the time a regulation is promulgated, the Administrator may provide for a "
    "shorter period prior to the effective date, or an immediate effective date for: (1) a "
    "regulation with which the Administrator finds the regulated community does not need six "
    "months to come into compliance; (2) a regulation which responds to an emergency situation; "
    "or (3) other good cause found and published with the regulation. (Pub. L. 89–272, title II, "
    "§3010, as added Pub. L. 94–580, §2, Oct. 21, 1976, 90 Stat. 2812; amended Pub. L. 96–482, "
    "§15, Oct. 21, 1980, 94 Stat. 2342; Pub. L. 98–616, title II, §§204(a), 234, Nov. 8, 1984, 98 "
    "Stat. 3235, 3258.) Editorial Notes Amendments 1984 —Subsec. (a). Pub. L. 98–616, §204(a), "
    "inserted provisions after first sentence relating to burning and blending of hazardous "
    "wastes and substituted \"the preceding provisions\" for \"the preceding sentence\" in three "
    "places. Subsec. (b). Pub. L. 98–616, §234, inserted provision that at the time a regulation "
    "is promulgated, the Administrator may provide for a shorter period prior to the effective "
    "date, or an immediate effective date for a regulation with which the Administrator finds the "
    "regulated community does not need six months to come into compliance, a regulation which "
    "responds to an emergency situation, or other good cause found and published with the "
    "regulation. 1980 —Subsec. (a). Pub. L. 96–482 struck out \"or revision\" after \"after "
    "promulgation or revision of regulations\" and inserted provision for filing of notification "
    "when revising any regulation identifying additional characteristics of hazardous waste or "
    "listing any additional substance as hazardous waste subject to this subchapter. Executive "
    "Documents Transfer of Functions For transfer of certain enforcement functions of "
    "Administrator or other official of Environmental Protection Agency under this chapter to "
    "Federal Inspector, Office of Federal Inspector for the Alaska Natural Gas Transportation "
    "System, and subsequent transfer to Secretary of Energy, then to Federal Coordinator for "
    "Alaska Natural Gas Transportation Projects, see note set out under section 6903 of this "
    "title. 1 So in original. Probably should be followed by a semicolon."
)
_USCODE_46_60101_TEXT = (
    "§60101. Boarding arriving vessels before inspection (a) Regulations .—The Secretary of "
    "Homeland Security shall prescribe and enforce regulations on the boarding of a vessel "
    "arriving at a port of the United States before the vessel has been inspected and secured. "
    "(b) Criminal Penalty .—A person violating a regulation prescribed under this section shall "
    "be fined under title 18, imprisoned for not more than 6 months, or both. (c) Relationship to "
    "Other law .—This section shall be construed as supplementary to section 2279 of title 18. "
    "(Pub. L. 109–304, §9(b), Oct. 6, 2006, 120 Stat. 1674.) Historical and Revision Notes "
    "Revised Section Source (U.S. Code) Source (Statutes at Large) 60101 46 App.:163. Mar. 31, "
    "1900, ch. 120, §§1–3, 31 Stat. 58. In subsection (a), the Secretary of Homeland Security is "
    "substituted for the Commissioner of Customs because the functions of the Customs Service and "
    "of the Secretary of the Treasury relating thereto were transferred to the Secretary of "
    "Homeland Security by section 403(1) of the Homeland Security Act of 2002 (Pub. L. 107–296, "
    "116 Stat. 2178). The functions of the Commissioner of Customs previously were vested in the "
    "Secretary of the Treasury under section 321(c) of title 31. For prior related transfers of "
    "functions, see the transfer of functions note under 46 App. U.S.C. 163. The word \"shall\" is "
    "substituted for \"is authorized and directed to\" for consistency in the revised title and to "
    "eliminate unnecessary words. The word \"port\" is substituted for \"seaports\" for consistency "
    "in the revised title. The word \"secured\" is substituted for \"placed in security\" to "
    "eliminate unnecessary words. The words \"from time to time\", \"properly\", and \"and for that "
    "purpose to employ any of the officers of the United States Customs Service\" are omitted as "
    "unnecessary. In subsection (b), the words \"fined under title 18, imprisoned for not more "
    "than 6 months, or both\" are substituted for \"subject to a penalty of not more than $100 or "
    "imprisonment not to exceed six months, or both\" because of chapter 227 of title 18. The "
    "words \"in the discretion of the court\" are omitted as unnecessary. In subsection (c), the "
    "words \"section 2279 of title 18\" are substituted for \"section forty-six hundred and six of "
    "the Revised Statutes\" in the Act of Mar. 31, 1900, because R.S. §4606 (formerly classified "
    "to 46 U.S.C. 708 (1946 ed.)) was replaced by 18 U.S.C. 2279 in the codification of title 18 "
    "by the Act of June 25, 1948 (ch. 645, 62 Stat. 683). The words \"section 9 of act August 2, "
    "1882 (22 Stat. 189)\" are omitted because that law was repealed by section 4(b) of Public Law "
    "98–89 (Aug. 26, 1983, 97 Stat. 600)."
)
_USCODE_25_422_HEADING_ONLY_TEXT = "Housing voucher benefits and utility allowances."
_USCODE_48_1572_HEADING_ONLY_TEXT = "Administrative notice and hearing."
_USCODE_42_6323_HEADING_ONLY_TEXT = "Notice and hearing requirements."
_USCODE_43_2430_PACKET_143_TODO_TEXT = (
    "The administrative notice and hearing procedures for offshore mineral leasing "
    "adjustments and adjudications."
)
_USCODE_7_431_TODO_TEXT = "Sec. 431 - Declaration of policy."
_USCODE_6_257_TODO_TEXT = "Sec. 257 - National planning scenarios and preparedness targets."
_USCODE_45_81_TO_92_TODO_TEXT = "Secs. 81 to 92. Repealed."
_USCODE_6_314_TODO_TEXT = "National planning scenarios, preparedness targets, and implementation guidance."
_USCODE_35_4_TODO_TEXT = "Officers, employees, and attorneys."
_USCODE_7_7316_TODO_TEXT = "Report."
_USCODE_2_453_PACKET_39_TEXT = "The oath of office."
_USCODE_9_6_PACKET_39_TEXT = "The application heard as motion."
_USCODE_43_1656_PACKET_39_TEXT = "The withdrawal and reservation of lands."
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
_USCODE_LONG_SUBSECTION_BODY = (
    "general program coordination reporting documentation verification auditing review "
    "management data cataloging compliance mapping operations planning record indexing "
    "partner communication protocol tracking archive retention intake routing portfolio "
    "monitoring case reconciliation metrics alignment oversight administration workflow "
    "continuity guidance taxonomy harmonization standards integration"
)
_USCODE_42_15362_LONG_SUBSECTION_HEADING_TEXT = (
    "Section 15362 Administrative notice and hearing procedures (a) "
    + _USCODE_LONG_SUBSECTION_BODY
)
_USCODE_26_3201_LONG_SUBSECTION_HEADING_TEXT = (
    "Section 3201 Lien for taxes and related enforcement administration (a) "
    + _USCODE_LONG_SUBSECTION_BODY
)
_USCODE_42_3796FF_LONG_SUBSECTION_HEADING_TEXT = (
    "Section 3796ff Public safety officer benefit administration and definitions (a) "
    + _USCODE_LONG_SUBSECTION_BODY
)
_USCODE_16_6410_SYMBOLIC_VALIDITY_TEXT = (
    "U.S.C. Title 16 - CONSERVATION 16 U.S.C. United States Code, 2024 Edition "
    "Title 16 - CONSERVATION CHAPTER 83 - CORAL REEF CONSERVATION Sec. 6410 - "
    "Ruth D. Gates Coral Reef Conservation Grant Program From the U.S. Government "
    "Publishing Office, www.gpo.gov §6410. Ruth D. Gates Coral Reef "
    "Conservation Grant Program (a) In general Subject to the availability of "
    "appropriations, the Administrator shall establish a program to provide "
    "grants for projects for the conservation and restoration of coral reef "
    "ecosystems. (b) Matching requirements for grants Federal funds for a coral "
    "reef project may not exceed 50 percent of the total cost of the project, and "
    "the non-Federal share may be provided by in-kind contributions."
)
_USCODE_16_47A_SYMBOLIC_VALIDITY_TEXT = (
    "U.S.C. Title 16 - CONSERVATION 16 U.S.C. United States Code, 2024 Edition "
    "Title 16 - CONSERVATION CHAPTER 1 - NATIONAL PARKS, MILITARY PARKS, "
    "MONUMENTS, AND SEASHORES SUBCHAPTER VI - SEQUOIA AND YOSEMITE NATIONAL PARKS "
    "Sec. 47a - Addition of certain lands to park authorized From the U.S. "
    "Government Publishing Office, www.gpo.gov §47a. Addition of certain "
    "lands to park authorized For the purpose of preserving and consolidating "
    "timber stands along the western boundary of the Yosemite National Park the "
    "President of the United States is authorized, upon the joint recommendation "
    "of the Secretaries of Interior and Agriculture, to add to the Yosemite "
    "National Park."
)
_USCODE_7_614_SYMBOLIC_VALIDITY_TEXT = (
    "U.S.C. Title 7 - AGRICULTURE 7 U.S.C. United States Code, 2024 Edition "
    "Title 7 - AGRICULTURE CHAPTER 26 - AGRICULTURAL ADJUSTMENT SUBCHAPTER III - "
    "COMMODITY BENEFITS Sec. 614 - Separability From the U.S. Government "
    "Publishing Office, www.gpo.gov §614. Separability If any provision of "
    "this chapter is declared unconstitutional, or the applicability thereof to "
    "any person, circumstance, or commodity is held invalid the validity of the "
    "remainder of this chapter and the applicability thereof to other persons, "
    "circumstances, or commodities shall not be affected thereby."
)
_USCODE_2_60A_2_TEXT = (
    "U.S.C. Title 2 - THE CONGRESS 2 U.S.C. United States Code, 2024 Edition Title 2 "
    "- THE CONGRESS CHAPTER 4 - OFFICERS AND EMPLOYEES OF SENATE AND HOUSE OF "
    "REPRESENTATIVES Sec. 60a-2 - Transferred From the U.S. Government Publishing "
    "Office, www.gpo.gov §60a–2. Transferred Editorial Notes Codification Section "
    "60a–2 was editorially reclassified as section 4531 of this title."
)
_USCODE_2_130A_TEXT = (
    "U.S.C. Title 2 - THE CONGRESS 2 U.S.C. United States Code, 2024 Edition Title 2 - "
    "THE CONGRESS CHAPTER 4 - OFFICERS AND EMPLOYEES OF SENATE AND HOUSE OF "
    "REPRESENTATIVES Sec. 130a - Transferred From the U.S. Government Publishing "
    "Office, www.gpo.gov §130a. Transferred Editorial Notes Codification Section 130a "
    "was editorially reclassified as section 4504 of this title."
)
_USCODE_2_59B_PACKET_144_TEXT = (
    "U.S.C. Title 2 - THE CONGRESS 2 U.S.C. United States Code, 2024 Edition Title 2 - "
    "THE CONGRESS CHAPTER 3 - COMPENSATION AND ALLOWANCES OF MEMBERS Sec. 59b - "
    "Transferred From the U.S. Government Publishing Office, www.gpo.gov §59b. "
    "Transferred Editorial Notes Codification Section 59b was editorially reclassified "
    "as section 6320 of this title."
)
_USCODE_4_123_SYMBOLIC_VALIDITY_TEXT = (
    "U.S.C. Title 4 - FLAG AND SEAL, SEAT OF GOVERNMENT, AND THE STATES 4 U.S.C. United States Code, "
    "2024 Edition Title 4 - FLAG AND SEAL, SEAT OF GOVERNMENT, AND THE STATES CHAPTER 4 - THE STATES "
    "Sec. 123 - Scope; special rules From the U.S. Government Publishing Office, www.gpo.gov §123. "
    "Scope; special rules (a) Act Does Not Supersede Customer's Liability to Taxing Jurisdiction "
    ".—Nothing in sections 116 through 126 modifies, impairs, supersedes, or authorizes the "
    "modification, impairment, or supersession of, any law allowing a taxing jurisdiction to collect "
    "a tax, charge, or fee from a customer that has failed to provide its place of primary use. (b) "
    "Additional Taxable Charges .—If a taxing jurisdiction does not otherwise subject charges for "
    "mobile telecommunications services to taxation and if these charges are aggregated with and not "
    "separately stated from charges that are subject to taxation, then the charges for nontaxable "
    "mobile telecommunications services may be subject to taxation unless the home service provider "
    "can reasonably identify charges not subject to such tax, charge, or fee from its books and "
    "records that are kept in the regular course of business. (c) Nontaxable Charges .—If a taxing "
    "jurisdiction does not subject charges for mobile telecommunications services to taxation, a "
    "customer may not rely upon the nontaxability of charges for mobile telecommunications services "
    "unless the customer's home service provider separately states the charges for nontaxable mobile "
    "telecommunications services from taxable charges or the home service provider elects, after "
    "receiving a written request from the customer in the form required by the provider, to provide "
    "verifiable data based upon the home service provider's books and records that are kept in the "
    "regular course of business that reasonably identifies the nontaxable charges. (Added Pub. L. "
    "106–252, §2(a), July 28, 2000, 114 Stat. 630.)"
)
_USCODE_5_5564_SYMBOLIC_VALIDITY_TEXT = (
    "U.S.C. Title 5 - GOVERNMENT ORGANIZATION AND EMPLOYEES 5 U.S.C. United States Code, 2024 Edition "
    "Title 5 - GOVERNMENT ORGANIZATION AND EMPLOYEES PART III - EMPLOYEES Subpart D - Pay and "
    "Allowances CHAPTER 55 - PAY ADMINISTRATION SUBCHAPTER VII - PAYMENTS TO MISSING EMPLOYEES Sec. "
    "5564 - Travel and transportation; dependents; household and personal effects; motor vehicles; "
    "sale of bulky items; claims for proceeds; appropriation chargeable From the U.S. Government "
    "Publishing Office, www.gpo.gov §5564. Travel and transportation; dependents; household and "
    "personal effects; motor vehicles; sale of bulky items; claims for proceeds; appropriation "
    "chargeable (a) For the purpose of this section, \"household and personal effects\" and "
    "\"household effects\" may include, in addition to other authorized weight allowances, one "
    "privately owned motor vehicle which may be shipped at United States expense. (b) Transportation "
    "(including packing, crating, draying, temporarily storing, and unpacking of household and "
    "personal effects) may be provided for the dependents and household and personal effects of an "
    "employee in active service (without regard to pay grade) who is officially reported as dead, "
    "injured, or absent for more than 29 days in a status listed in section 5561(5) (A)–(E) of this "
    "title to— (1) the official residence of record for the employee; (2) the residence of his "
    "dependent, next of kin, or other person entitled to the effects under regulations prescribed by "
    "the head of the agency concerned; or (3) another location determined in advance or later "
    "approved by the head of the agency concerned or his designee on request of the employee (if "
    "injured) or his dependent, next of kin, or other person described in paragraph (2) of this "
    "subsection. (c) When an employee described in subsection (b) of this section is in an injured "
    "status, transportation of dependents and household and personal effects may be provided under "
    "this section only when prolonged hospitalization or treatment is anticipated. (d) Transportation "
    "on request of a dependent may be authorized under this section only when there is a reasonable "
    "relationship between the circumstances of the dependent and the destination requested. (e) "
    "Instead of providing transportation for dependents under this section, when the travel has been "
    "completed the head of the agency concerned may authorize— (1) reimbursement for the commercial "
    "cost of the transportation; or (2) a monetary allowance, instead of transportation, as "
    "authorized by statute for the whole or that part of the travel for which transportation in kind "
    "was not furnished. (i) This section does not amend or repeal— (1) section 2575, 2733, 4712, "
    "6522, or 9712 of title 10; (2) section 507 1 of title 14; or (3) chapter 171 of title 28."
)
_USCODE_16_6808_SYMBOLIC_VALIDITY_TEXT = (
    "U.S.C. Title 16 - CONSERVATION 16 U.S.C. United States Code, 2024 Edition Title "
    "16 - CONSERVATION CHAPTER 87 - FEDERAL LANDS RECREATION ENHANCEMENT Sec. 6808 - "
    "Reports From the U.S. Government Publishing Office, www.gpo.gov §6808. Reports "
    "Not later than May 1, 2006, and every 3 years thereafter, the Secretary shall "
    "submit to Congress a report detailing the status of the recreation fee program "
    "conducted for Federal recreational lands and waters, including an evaluation of "
    "the recreation fee program, examples of projects that were funded using such "
    "fees, and future projects and programs for funding with fees, and containing any "
    "recommendations for changes in the overall fee system. (Pub. L. 108–447, div. J, "
    "title VIII, §809, Dec. 8, 2004, 118 Stat. 3389.)"
)
_USCODE_16_773B_SYMBOLIC_VALIDITY_TODO_TEXT = "Sec. 773b - Transferred."
_USCODE_16_460VV_17_SYMBOLIC_VALIDITY_TODO_TEXT = "Sec. 460vv–17 - Transferred."
_USCODE_7_7656_SYMBOLIC_VALIDITY_TEXT = (
    "U.S.C. Title 7 - AGRICULTURE 7 U.S.C. United States Code, 2024 Edition Title 7 - "
    "AGRICULTURE CHAPTER 103 - AGRICULTURAL RESEARCH, EXTENSION, AND EDUCATION REFORM "
    "SUBCHAPTER III - MISCELLANEOUS PROVISIONS Part B - General Sec. 7656 - "
    "Designation of Crisis Management Team within Department From the U.S. Government "
    "Publishing Office, www.gpo.gov §7656. Designation of Crisis Management Team "
    "within Department (a) Designation of Crisis Management Team The Secretary of "
    "Agriculture shall designate a Crisis Management Team within the Department of "
    "Agriculture, which shall be— (1) composed of senior departmental personnel with "
    "strong subject matter expertise selected from each relevant agency of the "
    "Department; and (2) headed by a team leader with management and communications "
    "skills. (b) Duties of Crisis Management Team The Crisis Management Team shall be "
    "responsible for the following: (1) Developing a Department-wide crisis "
    "management plan, taking into account similar plans developed by other government "
    "agencies and other large organizations, and developing written procedures for "
    "the implementation of the crisis management plan. (2) Conducting periodic "
    "reviews and revisions of the crisis management plan and procedures developed "
    "under paragraph (1). (3) Ensuring compliance with crisis management procedures "
    "by personnel of the Department and ensuring that appropriate Department "
    "personnel are familiar with the crisis management plan and procedures and are "
    "encouraged to bring information regarding crises or potential crises to the "
    "attention of members of the Crisis Management Team. (4) Coordinating the "
    "Department's information gathering and dissemination activities concerning "
    "issues managed by the Crisis Management Team. (5) Ensuring that Department "
    "spokespersons convey accurate, timely, and scientifically sound information "
    "regarding crises or potential crises that can be easily understood by the "
    "general public. (6) Cooperating with, and coordinating among, other Federal "
    "agencies, States, local governments, industry, and public interest groups, "
    "Department activities regarding a crisis. (c) Role in prioritizing certain "
    "research The Crisis Management Team shall cooperate with the Advisory Board in "
    "the prioritization of agricultural research conducted or funded by the "
    "Department regarding animal health, natural disasters, food safety, and other "
    "agricultural issues. (d) Cooperative agreements The Secretary shall seek to "
    "enter into cooperative agreements with other Federal departments and agencies "
    "that have related programs or activities to help ensure consistent, accurate, "
    "and coordinated dissemination of information throughout the executive branch in "
    "the event of a crisis, such as, in the case of a threat to human health from "
    "food-borne pathogens, developing a rapid and coordinated response among the "
    "Department, the Centers for Disease Control, and the Food and Drug "
    "Administration. (Pub. L. 105–185, title VI, §618, June 23, 1998, 112 Stat. 607.)"
)
_USCODE_8_1365B_SYMBOLIC_VALIDITY_TEXT = (
    "U S C Title 8 ALIENS AND NATIONALITY 8 U S C United States Code 2024 Edition "
    "Title 8 ALIENS AND NATIONALITY chapter reference register digest archive ledger "
    "taxonomy matrix sec 1365b criminal penalty framework national enforcement "
    "catalog profile record coordination protocol annex supplement schedule digest "
    "index narrative glossary appendix mapping table registry ledger profile catalog "
    "workflow archive coordination matrix record taxonomy annex supplement schedule "
    "registry digest table profile catalog narrative appendix mapping index ledger "
    "coordination protocol record workflow archive taxonomy matrix"
)
_USCODE_34_50108_SYMBOLIC_VALIDITY_TEXT = (
    "U S C Title 34 CRIME CONTROL AND LAW ENFORCEMENT 34 U S C United States Code "
    "2024 Edition Title 34 chapter reference digest archive ledger taxonomy matrix "
    "section 50108 criminal penalty administration framework enforcement registry "
    "catalog profile record coordination protocol annex supplement schedule digest "
    "index narrative glossary appendix mapping table registry ledger profile catalog "
    "workflow archive coordination matrix record taxonomy annex supplement schedule "
    "registry digest table profile catalog narrative appendix mapping index ledger "
    "coordination protocol record workflow archive taxonomy matrix"
)
_USCODE_19_3702_SYMBOLIC_VALIDITY_TEXT = (
    "U S C Title 19 CUSTOMS DUTIES 19 U S C United States Code 2024 Edition Title 19 "
    "chapter reference digest archive ledger taxonomy matrix sec 3702 congressional "
    "statement of purpose policy coordination framework community alignment program "
    "registry catalog profile record coordination protocol annex supplement schedule "
    "digest index narrative glossary appendix mapping table registry ledger profile "
    "catalog workflow archive coordination matrix record taxonomy annex supplement "
    "schedule registry digest table profile catalog narrative appendix mapping index "
    "ledger coordination protocol record workflow archive taxonomy matrix"
)


def _coarse_uscode_procedural_heading_noise_text(section: str, heading: str) -> str:
    noise_tokens = " ".join(chr(ord("k") + (index % 10)) for index in range(180))
    return (
        "U S C title archive register digest taxonomy index chapter crosswalk "
        f"sec {section} {heading} is archive "
        f"{noise_tokens}"
    )


def test_modal_registry_exports_packet_002300_compiler_ambiguity_policy_pairs() -> None:
    assert {
        ("deontic", "deontic"),
        ("deontic", "temporal"),
        ("frame", "alethic"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    } == set(COMPILER_AMBIGUITY_PACKET_002300_FAMILY_PAIRS)
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_002300_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)


def test_modal_codec_encodes_all_modal_families_with_frame_logic() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )

    result = codec.encode(
        "The agency must provide notice within 30 days after application.",
        document_id="sample-doc",
        citation="5 U.S.C. 552",
        source="us_code",
    )

    families = {formula.operator.family for formula in result.modal_ir.formulas}
    assert {"deontic", "temporal"}.issubset(families)
    assert result.modal_ir.metadata["llm_call_count"] == 0
    assert result.selected_frame == "administrative_notice_hearing"
    assert result.modal_ir.frame_candidates
    assert len(result.decoded_embedding) == 8
    assert result.losses["cross_entropy_loss"] >= 0.0
    assert "flogic_similarity_loss" in result.losses
    assert result.losses["text_reconstruction_loss"] == 0.0
    assert result.losses["modal_span_coverage_loss"] == 0.0
    assert -1.0 <= result.losses["cosine_similarity"] <= 1.0
    assert result.flogic_result is not None
    assert result.flogic_result.ontology_consistent is True
    assert result.kg_triples
    assert all(triple["predicate"] for triple in result.kg_triples)
    assert result.modal_ir.frame_logic.triples
    assert result.modal_ir.frame_logic.to_triples() == result.kg_triples
    assert result.modal_ir.frame_logic.selected_frame == result.selected_frame
    assert result.modal_ir.frame_logic.graph_id == "sample-doc:flogic"
    assert "LegalModalDocument" in result.modal_ir.frame_logic.neo4j_node_labels
    assert result.modal_ir.metadata["flogic_triple_count"] == len(result.kg_triples)
    assert result.modal_ir.metadata["flogic_triples"] == result.kg_triples
    assert result.flogic_ontology.frames
    assert result.neo4j_graph_data.metadata["neo4j_compatible"] is True
    assert result.neo4j_graph_data.node_count > 0
    assert result.neo4j_graph_data.relationship_count == len(result.kg_triples)
    assert "LegalModalDocument" in result.neo4j_graph_data.schema.node_labels
    engine, import_report = import_graph_data_to_graph_engine(result.neo4j_graph_data)
    assert import_report["nodes_imported"] == result.neo4j_graph_data.node_count
    assert import_report["relationships_imported"] == result.neo4j_graph_data.relationship_count
    assert engine.find_nodes(labels=["LegalModalDocument"], properties={"name": "sample-doc"})
    assert any(
        relationship.type == "BELONGS_TO_DOCUMENT"
        for relationship in engine._relationship_cache.values()
        if hasattr(relationship, "type")
    )
    assert modal_formula_to_text(result.modal_ir.formulas[0])
    assert result.metadata["deterministic_decompiler"] == "modal_decompiler_v2"
    assert result.decoded_text == result.normalized_text
    assert result.decoded_modal_text.reconstruction_similarity == 1.0
    assert result.decoded_modal_text.modal_span_coverage == 1.0
    assert _token_overlap_ratio(result.normalized_text, result.decoded_text) == 1.0
    assert "[" not in result.decoded_text
    assert "actor:" not in result.decoded_text
    slot_texts = decoded_modal_phrase_slot_text_map(result.decoded_modal_text)
    assert "obligatory" in slot_texts["operator"]
    assert any("provide notice" in text for text in slot_texts["predicate"])
    semantic_slot_texts = decoded_modal_phrase_slot_text_map(
        result.decoded_modal_text,
        include_provenance_only=False,
    )
    assert semantic_slot_texts == {"modal_source_span": [result.normalized_text]}


def test_modal_compiler_decompiler_are_explainable_and_deterministic() -> None:
    frame_selector = BM25FrameSelector(
        (
            FrameCandidate(
                frame_id="agency_notice_a",
                label="Agency notice",
                terms=("agency", "notice"),
            ),
            FrameCandidate(
                frame_id="agency_notice_b",
                label="Agency notice duplicate",
                terms=("agency", "notice"),
            ),
        )
    )
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(parser_backend="regex", frame_score_margin=1.0),
        frame_selector=frame_selector,
    )

    compiled = compiler.compile(
        "The agency must provide notice.",
        document_id="compiler-doc",
        citation="5 U.S.C. 552",
        source="us_code",
    )
    decoded = decode_modal_ir_document(compiled.modal_ir)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert compiled.modal_ir.document_id == "compiler-doc"
    assert compiled.modal_ir.metadata["deterministic_compiler"] == "modal_compiler_v1"
    assert compiled.modal_ir.metadata["llm_call_count"] == 0
    assert compiled.ambiguities
    assert any(
        ambiguity.ambiguity_type == "close_bm25_frame_scores"
        for ambiguity in compiled.ambiguities
    )
    assert decoded.source_id == "compiler-doc"
    assert decoded.text == "The agency must provide notice."
    assert decoded.reconstruction_similarity == 1.0
    assert decoded.modal_span_coverage == 1.0
    assert decoded.formulas[0].startswith("O[deontic:D]")
    assert slot_texts["operator"] == ["obligatory"]
    assert slot_texts["cue"] == ["must"]
    assert decoded_modal_phrase_slot_text_map(decoded, include_provenance_only=False) == {
        "modal_source_span": ["The agency must provide notice."]
    }


def test_modal_decompiler_surfaces_autoencoder_modal_family_guidance_slots() -> None:
    modal_ir = ModalIRDocument(
        document_id="guidance-doc",
        source="us_code",
        normalized_text="The agency must provide notice.",
        metadata={
            "hint_evidence": [
                {
                    "primary_pipeline_stage": "modal_family_registry",
                    "pipeline_stage_focus": ["modal_family_registry"],
                    "pipeline_stage_diagnostics": {
                        "modal_family_cue_mismatch": True,
                        "modal_family_target_probability_gap": 0.366001885428,
                    },
                    "top_embedding_features": [
                        "modal-family-prototype:temporal",
                        "legal-ir-view-prototype:modal.frame_logic",
                        "modal-family-prototype:frame",
                        "family-legal-ir-view-prototype:frame||modal.frame_logic",
                    ],
                }
            ],
        },
    )

    decoded = decode_modal_ir_document(modal_ir)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert decoded.text == modal_ir.normalized_text
    assert slot_texts["autoencoder_modal_family_cue_mismatch"] == ["true"]
    assert slot_texts["autoencoder_modal_family_target_probability_gap"] == [
        "0.366001885428"
    ]
    assert slot_texts["autoencoder_modal_family_target_probability_gap_bucket"] == [
        "0_25_to_0_5"
    ]
    assert slot_texts["autoencoder_primary_pipeline_stage"] == [
        "modal_family_registry"
    ]
    assert slot_texts["autoencoder_modal_family_prototype"] == ["temporal", "frame"]
    assert slot_texts["autoencoder_modal_family_prototype_pair"] == ["temporal->frame"]
    assert slot_texts["autoencoder_legal_ir_view_prototype"] == ["modal.frame_logic"]
    assert slot_texts["autoencoder_family_legal_ir_view_pair"] == [
        "frame||modal.frame_logic"
    ]


def test_flogic_graph_projection_metadata_tracks_frame_logic_alignment() -> None:
    graph_data = flogic_triples_to_graph_data(
        [
            {"subject": "sample-doc", "predicate": "type", "object": "legal_modal_document"},
            {
                "subject": "sample-doc",
                "predicate": "selected_ontology_frame",
                "object": "administrative_notice_hearing",
            },
            {"subject": "sample-doc", "predicate": "source", "object": "us_code"},
            {"subject": "sample-doc", "predicate": "ignored", "object": ""},
            {"subject": "", "predicate": "ignored", "object": "x"},
        ],
        graph_id="sample-doc:flogic",
    )

    assert graph_data.relationship_count == 3
    assert graph_data.node_count >= 2
    assert graph_data.metadata["flogic_input_triple_count"] == 5
    assert graph_data.metadata["flogic_triple_count"] == 3
    assert graph_data.metadata["flogic_invalid_triple_count"] == 2
    assert graph_data.metadata["frame_logic_projection_aligned"] is True
    assert graph_data.metadata["frame_logic_projection_normalized_aligned"] is True
    assert graph_data.metadata["frame_logic_projection_input_aligned"] is False
    assert graph_data.metadata["frame_logic_projection_input_relationship_gap"] == 2
    assert (
        graph_data.metadata["frame_logic_projection_relationship_count"]
        == graph_data.relationship_count
    )
    assert graph_data.metadata["frame_logic_projection_node_count"] == graph_data.node_count
    assert graph_data.metadata["frame_logic_projection_view_count"] == 3
    assert graph_data.metadata["frame_logic_projection_views"] == [
        "document_scope",
        "frame_link",
        "type_assertion",
    ]
    assert graph_data.metadata["frame_logic_projection_view_distribution"] == {
        "document_scope": 1,
        "frame_link": 1,
        "type_assertion": 1,
    }
    assert graph_data.metadata["frame_logic_selected_frame"] == "administrative_notice_hearing"


def test_flogic_graph_projection_classifies_structured_predicates_into_projection_views() -> None:
    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "sample-doc",
                "predicate": "candidate_ontology_frame_ranked_token",
                "object": "administrative",
            },
            {
                "subject": "sample-doc",
                "predicate": "selected_frame_modal_family_count_value",
                "object": "2",
            },
            {
                "subject": "sample-doc",
                "predicate": "citation_source_id_alignment_profile_token",
                "object": "usc",
            },
            {
                "subject": "sample-doc",
                "predicate": "support_span_start_char",
                "object": "0",
            },
            {
                "subject": "sample-doc",
                "predicate": "source_text_char_count",
                "object": "128",
            },
            {"subject": "sample-doc", "predicate": "custom_fact", "object": "x"},
        ],
        graph_id="sample-doc:flogic",
    )

    view_by_predicate = {
        rel.properties["flogic_predicate"]: rel.properties["frame_logic_projection_view"]
        for rel in graph_data.relationships
    }
    assert view_by_predicate["candidate_ontology_frame_ranked_token"] == "frame_link"
    assert view_by_predicate["selected_frame_modal_family_count_value"] == "modal_semantics"
    assert view_by_predicate["citation_source_id_alignment_profile_token"] == "citation_structure"
    assert view_by_predicate["support_span_start_char"] == "provenance"
    assert view_by_predicate["source_text_char_count"] == "document_scope"
    assert view_by_predicate["custom_fact"] == "fact"

    assert graph_data.metadata["frame_logic_projection_view_distribution"] == {
        "citation_structure": 1,
        "document_scope": 1,
        "fact": 1,
        "frame_link": 1,
        "modal_semantics": 1,
        "provenance": 1,
    }


def test_modal_ir_graph_projection_metadata_keeps_frame_logic_selected_frame() -> None:
    document = ModalIRDocument(
        document_id="sample-doc",
        source="us_code",
        normalized_text="The agency must provide notice.",
        frame_logic=ModalIRFrameLogic.from_triples(
            [
                {"subject": "sample-doc", "predicate": "type", "object": "legal_modal_document"}
            ],
            ontology_name="sample_flogic",
            selected_frame="administrative_notice_hearing",
        ),
    )

    graph_data = modal_ir_to_neo4j_graph_data(document)

    assert graph_data.metadata["frame_logic_ontology_name"] == "sample_flogic"
    assert graph_data.metadata["frame_logic_selected_frame"] == "administrative_notice_hearing"


def test_flogic_graph_projection_canonicalizes_relationship_order_and_reports_duplicates() -> None:
    triples_a = [
        {"subject": "sample-doc", "predicate": "source", "object": "us_code"},
        {
            "subject": "sample-doc",
            "predicate": "selected_ontology_frame",
            "object": "administrative_notice_hearing",
        },
        {"subject": "sample-doc", "predicate": "source", "object": "us_code"},
        {"subject": "sample-doc", "predicate": "type", "object": "legal_modal_document"},
        {
            "subject": "sample-doc",
            "predicate": "selected_ontology_frame",
            "object": "administrative_notice_hearing",
        },
    ]
    triples_b = [
        {"subject": "sample-doc", "predicate": "source", "object": "us_code"},
        {"subject": "sample-doc", "predicate": "type", "object": "legal_modal_document"},
        {
            "subject": "sample-doc",
            "predicate": "selected_ontology_frame",
            "object": "administrative_notice_hearing",
        },
        {"subject": "sample-doc", "predicate": "source", "object": "us_code"},
        {
            "subject": "sample-doc",
            "predicate": "selected_ontology_frame",
            "object": "administrative_notice_hearing",
        },
    ]

    graph_a = flogic_triples_to_graph_data(triples_a, graph_id="sample-doc:flogic")
    graph_b = flogic_triples_to_graph_data(triples_b, graph_id="sample-doc:flogic")

    assert graph_a.relationship_count == 5
    assert graph_a.metadata["flogic_input_triple_count"] == 5
    assert graph_a.metadata["flogic_invalid_triple_count"] == 0
    assert graph_a.metadata["flogic_normalized_triple_count"] == 5
    assert graph_a.metadata["flogic_duplicate_triple_count"] == 2
    assert graph_a.metadata["flogic_unique_triple_count"] == 3
    assert graph_a.metadata["frame_logic_projection_aligned"] is True
    assert graph_a.metadata["frame_logic_projection_normalized_aligned"] is True
    assert graph_a.metadata["frame_logic_projection_input_aligned"] is True
    assert graph_a.metadata["frame_logic_projection_input_relationship_gap"] == 0
    assert graph_a.metadata["frame_logic_projection_has_duplicate_facts"] is True
    assert graph_a.metadata["frame_logic_projection_relationship_count"] == 5
    assert graph_a.metadata["frame_logic_projection_view_distribution"] == {
        "document_scope": 2,
        "frame_link": 2,
        "type_assertion": 1,
    }
    assert graph_a.metadata["frame_logic_selected_frame"] == "administrative_notice_hearing"

    rel_signature_a = [
        (
            rel.id,
            rel.properties["triple_index"],
            rel.properties["flogic_triple_key"],
            rel.properties["frame_logic_projection_view"],
        )
        for rel in graph_a.relationships
    ]
    rel_signature_b = [
        (
            rel.id,
            rel.properties["triple_index"],
            rel.properties["flogic_triple_key"],
            rel.properties["frame_logic_projection_view"],
        )
        for rel in graph_b.relationships
    ]
    assert rel_signature_a == rel_signature_b
    assert all(
        rel.properties["flogic_triple_key"]
        == "\x1f".join(
            (
                rel.properties["flogic_subject"],
                rel.properties["flogic_predicate"],
                rel.properties["flogic_object"],
            )
        )
        for rel in graph_a.relationships
    )


def test_modal_compiler_handles_transferred_heading_for_uscode_15_688() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))

    compiled = compiler.compile(
        "\u00a7688. Transferred.",
        document_id="us-code-15-688-3977b0476c11fbf1",
        citation="15 U.S.C. 688",
        source="us_code",
    )

    assert compiled.modal_ir.formulas
    assert all(
        ambiguity.ambiguity_type != "missing_modal_formula"
        for ambiguity in compiled.ambiguities
    )
    fallback = compiled.modal_ir.formulas[-1]
    assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
    assert fallback.provenance.citation == "15 U.S.C. 688"


def test_modal_compiler_handles_spaced_transferred_headings_for_known_uscode_samples() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    cases = [
        (
            "us-code-48-2169.-816da61b9d4f3363",
            "48 U.S.C. 2169.",
            "\u00a7 2169 Transferred.",
        ),
        (
            "us-code-3-21-4ce508fff75e0824",
            "3 U.S.C. 21",
            "\u00a7 21 Transferred.",
        ),
        (
            "us-code-16-469i-bc1e2d2974a2257d",
            "16 U.S.C. 469i",
            "\u00a7 469i Transferred.",
        ),
    ]

    for document_id, citation, text in cases:
        compiled = compiler.compile(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )

        assert compiled.modal_ir.formulas
        assert all(
            ambiguity.ambiguity_type != "missing_modal_formula"
            for ambiguity in compiled.ambiguities
        )
        fallback = compiled.modal_ir.formulas[-1]
        assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
        assert fallback.provenance.citation == citation


def test_modal_compiler_handles_sec_prefixed_transferred_headings_for_known_uscode_samples() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
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
        compiled = compiler.compile(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )

        assert compiled.modal_ir.formulas
        assert all(
            ambiguity.ambiguity_type != "missing_modal_formula"
            for ambiguity in compiled.ambiguities
        )
        fallback = compiled.modal_ir.formulas[-1]
        assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
        assert fallback.provenance.citation == citation


def test_modal_compiler_handles_embedded_sec_headings_for_known_uscode_samples() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
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
        compiled = compiler.compile(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )

        assert compiled.modal_ir.formulas
        assert all(
            ambiguity.ambiguity_type != "missing_modal_formula"
            for ambiguity in compiled.ambiguities
        )
        fallback = compiled.modal_ir.formulas[-1]
        assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
        assert fallback.provenance.citation == citation


def test_modal_compiler_replays_dataset_zero_formula_cases_for_59b_130a_31a_2b_60a_2_and_8906() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    cases = [
        (
            "us-code-2-59b-8902f0eb9b420bbe",
            "2 U.S.C. 59b",
            _USCODE_2_59B_PACKET_144_TEXT,
            "uscode_transferred_heading_v1",
        ),
        (
            "us-code-2-130a-a14e984db7a8af87",
            "2 U.S.C. 130a",
            _USCODE_2_130A_TEXT,
            "uscode_transferred_heading_v1",
        ),
        (
            "us-code-2-31a-2b-a99b26c5ad622cfe",
            "2 U.S.C. 31a-2b",
            _USCODE_2_31A_2B_TEXT,
            "uscode_transferred_heading_v1",
        ),
        (
            "us-code-2-60a-2-ee0af9802f887e89",
            "2 U.S.C. 60a-2",
            _USCODE_2_60A_2_TEXT,
            "uscode_transferred_heading_v1",
        ),
        (
            "us-code-46-8906.-ebe08e6d737c3c40",
            "46 U.S.C. 8906.",
            _USCODE_46_8906_TEXT,
            "uscode_section_heading_v1",
        ),
    ]

    for document_id, citation, text, fallback_rule in cases:
        compiled = compiler.compile(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )

        assert compiled.modal_ir.formulas
        assert all(
            ambiguity.ambiguity_type != "missing_modal_formula"
            for ambiguity in compiled.ambiguities
        )
        fallback = compiled.modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["fallback_rule"] == fallback_rule
        assert fallback.provenance.citation == citation


def test_modal_compiler_replays_packet_todo_zero_formula_sample_for_2_59b() -> None:
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        compiled = compiler.compile(
            _USCODE_2_59B_PACKET_144_TEXT,
            document_id="us-code-2-59b-8902f0eb9b420bbe",
            citation="2 U.S.C. 59b",
            source="us_code",
        )

        assert compiled.modal_ir.formulas
        assert all(
            ambiguity.ambiguity_type != "missing_modal_formula"
            for ambiguity in compiled.ambiguities
        )
        fallback = compiled.modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
        assert fallback.provenance.citation == "2 U.S.C. 59b"


def test_modal_compiler_replays_packet_todo_samples_for_36_110105_and_25_450() -> None:
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
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for document_id, citation, text, cue, fallback_rule in cases:
            compiled = compiler.compile(
                text,
                document_id=document_id,
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            fallback = compiled.modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == cue
            assert fallback.metadata["fallback_rule"] == fallback_rule
            assert fallback.provenance.citation == citation


def test_modal_compiler_replays_packet_todo_symbolic_validity_sample_for_25_5396() -> None:
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        compiled = compiler.compile(
            _USCODE_25_5396_TODO_TEXT,
            document_id="us-code-25-5396-17291bf2fa3ae3f6",
            citation="25 U.S.C. 5396",
            source="us_code",
        )

        assert compiled.modal_ir.formulas
        assert all(
            ambiguity.ambiguity_type != "missing_modal_formula"
            for ambiguity in compiled.ambiguities
        )
        assert any(
            formula.operator.family == "deontic"
            for formula in compiled.modal_ir.formulas
        )
        assert all(
            formula.provenance.citation == "25 U.S.C. 5396"
            for formula in compiled.modal_ir.formulas
        )


def test_modal_compiler_replays_packet_todo_samples_for_7_431_6_257_and_45_81_to_92() -> None:
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
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for document_id, citation, text, cue, fallback_rule, status_keyword in cases:
            compiled = compiler.compile(
                text,
                document_id=document_id,
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            fallback = compiled.modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == cue
            assert fallback.metadata["fallback_rule"] == fallback_rule
            if status_keyword:
                assert fallback.metadata["status_keyword"] == status_keyword
            assert fallback.provenance.citation == citation


def test_modal_compiler_replays_packet_todo_heading_only_samples_for_6_314_35_4_and_7_7316() -> None:
    cases = [
        (
            "us-code-6-314-afaf3a4084d6428b",
            "6 U.S.C. 314",
            _USCODE_6_314_TODO_TEXT,
        ),
        (
            "us-code-35-4-50bdd346f6009649",
            "35 U.S.C. 4",
            _USCODE_35_4_TODO_TEXT,
        ),
        (
            "us-code-7-7316-85781f95eae6399d",
            "7 U.S.C. 7316",
            _USCODE_7_7316_TODO_TEXT,
        ),
    ]
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for document_id, citation, text in cases:
            compiled = compiler.compile(
                text,
                document_id=document_id,
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            fallback = compiled.modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
            assert fallback.provenance.citation == citation


def test_modal_compiler_replays_packet_todo_article_prefixed_heading_samples_for_2_453_9_6_and_43_1656() -> None:
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
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for document_id, citation, text in cases:
            compiled = compiler.compile(
                text,
                document_id=document_id,
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            fallback = compiled.modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
            assert fallback.provenance.citation == citation


def test_modal_compiler_replays_packet_todo_samples_for_46_55318_8_606_and_46_115() -> None:
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
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for document_id, citation, text, cue, fallback_rule in cases:
            compiled = compiler.compile(
                text,
                document_id=document_id,
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            fallback = compiled.modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == cue
            assert fallback.metadata["fallback_rule"] == fallback_rule
            assert fallback.provenance.citation == citation


def test_modal_compiler_replays_dataset_samples_for_478_1_6930_and_60101() -> None:
    cases = [
        (
            "us-code-25-478-1-c2fe462e0462e875",
            "25 U.S.C. 478-1",
            _USCODE_25_478_1_TEXT,
            "uscode_transferred_heading_v1",
            {"frame"},
        ),
        (
            "us-code-42-6930.-5842e7569af665c8",
            "42 U.S.C. 6930.",
            _USCODE_42_6930_TEXT,
            None,
            {"deontic", "temporal"},
        ),
        (
            "us-code-46-60101.-6bea2346c1c5229c",
            "46 U.S.C. 60101.",
            _USCODE_46_60101_TEXT,
            None,
            {"deontic", "temporal"},
        ),
    ]
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for document_id, citation, text, fallback_rule, expected_families in cases:
            compiled = compiler.compile(
                text,
                document_id=document_id,
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            assert all(
                formula.provenance.citation == citation
                for formula in compiled.modal_ir.formulas
            )
            modal_families = {
                formula.operator.family
                for formula in compiled.modal_ir.formulas
            }
            assert expected_families.issubset(modal_families)
            if fallback_rule is not None:
                fallback = compiled.modal_ir.formulas[-1]
                assert fallback.operator.family == "frame"
                assert fallback.metadata["fallback_rule"] == fallback_rule


def test_modal_compiler_replays_heading_only_zero_formula_cases_for_25_422_48_1572_and_42_6323() -> None:
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
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for document_id, citation, text in cases:
            compiled = compiler.compile(
                text,
                document_id=document_id,
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            fallback = compiled.modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
            assert fallback.provenance.citation == citation


def test_modal_compiler_replays_packet_todo_long_heading_sample_for_43_2430() -> None:
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        compiled = compiler.compile(
            _USCODE_43_2430_PACKET_143_TODO_TEXT,
            document_id="us-code-43-2430.-7bfbe56b01b9ee78",
            citation="43 U.S.C. 2430.",
            source="us_code",
        )

        assert compiled.modal_ir.formulas
        assert all(
            ambiguity.ambiguity_type != "missing_modal_formula"
            for ambiguity in compiled.ambiguities
        )
        fallback = compiled.modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
        assert fallback.provenance.citation == "43 U.S.C. 2430."


def test_modal_compiler_replays_long_subsection_heading_zero_formula_cases_for_15362_3201_and_3796ff() -> None:
    cases = [
        (
            "us-code-42-15362.-c7a145faec5f2ad6",
            "42 U.S.C. 15362.",
            _USCODE_42_15362_LONG_SUBSECTION_HEADING_TEXT,
        ),
        (
            "us-code-26-3201-bd4f34df4d869df4",
            "26 U.S.C. 3201",
            _USCODE_26_3201_LONG_SUBSECTION_HEADING_TEXT,
        ),
        (
            "us-code-42-3796ff-59f170d1c742e9af",
            "42 U.S.C. 3796ff",
            _USCODE_42_3796FF_LONG_SUBSECTION_HEADING_TEXT,
        ),
    ]
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for document_id, citation, text in cases:
            compiled = compiler.compile(
                text,
                document_id=document_id,
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            fallback = compiled.modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
            assert fallback.provenance.citation == citation


def test_modal_compiler_ignores_calendar_month_may_permission_noise() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    compiled = compiler.compile(
        "The Secretary shall make the payment after May 13, 2002, and a producer may request review.",
        document_id="sample-calendar-may-cue",
        citation="7 U.S.C. 7913",
        source="us_code",
    )

    deontic_may_formulas = [
        formula
        for formula in compiled.modal_ir.formulas
        if formula.operator.family == "deontic"
        and str(formula.metadata.get("cue", "")).lower() == "may"
    ]
    assert len(deontic_may_formulas) == 1
    assert "request_review" in deontic_may_formulas[0].predicate.name


def test_modal_compiler_spacy_replays_editorial_status_zero_formula_samples() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="spacy",
            spacy_model_name="definitely_missing_legal_model",
        )
    )
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
        compiled = compiler.compile(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )

        assert compiled.modal_ir.formulas
        assert all(
            ambiguity.ambiguity_type != "missing_modal_formula"
            for ambiguity in compiled.ambiguities
        )
        fallback = compiled.modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["fallback_rule"] == "uscode_editorial_status_heading_v1"
        assert fallback.metadata["status_keyword"] == "omitted"
        assert fallback.provenance.citation == citation


def test_modal_compiler_spacy_replays_sec_prefixed_heading_zero_formula_sample_for_15_1693l() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="spacy",
            spacy_model_name="definitely_missing_legal_model",
        )
    )
    compiled = compiler.compile(
        "Sec. 1693l - Waiver of rights.",
        document_id="us-code-15-1693l-62b207bc138a3216",
        citation="15 U.S.C. 1693l",
        source="us_code",
    )

    assert compiled.modal_ir.formulas
    assert all(
        ambiguity.ambiguity_type != "missing_modal_formula"
        for ambiguity in compiled.ambiguities
    )
    fallback = compiled.modal_ir.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
    assert fallback.provenance.citation == "15 U.S.C. 1693l"


def test_modal_compiler_replays_sec_prefixed_heading_samples_with_usc_citation_variants() -> None:
    cases = [
        (
            "us-code-7-473a-02a85f2b18cfe8ee",
            "7 U.S.C. §473a",
            "Sec. 473a - Cotton classification services.",
        ),
        (
            "us-code-7-473a-02a85f2b18cfe8ee",
            "7 USC 473a",
            "Sec. 473a - Cotton classification services.",
        ),
        (
            "us-code-20-1067j-13aeda303003f5af",
            "20 U.S.C. §1067j",
            "Sec. 1067j - Administrative provisions.",
        ),
        (
            "us-code-20-1067j-13aeda303003f5af",
            "20 USC 1067j",
            "Sec. 1067j - Administrative provisions.",
        ),
        (
            "us-code-15-2501-eb4a7816e81bb710",
            "15 U.S.C. §2501",
            "Sec. 2501 - Congressional findings and policy.",
        ),
        (
            "us-code-15-2501-eb4a7816e81bb710",
            "15 USC 2501",
            "Sec. 2501 - Congressional findings and policy.",
        ),
    ]
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for index, (document_id, citation, text) in enumerate(cases, start=1):
            compiled = compiler.compile(
                text,
                document_id=f"{document_id}:citation-variant-{index}",
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            fallback = compiled.modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
            assert fallback.provenance.citation == citation


def test_modal_compiler_replays_packet_todo_symbolic_validity_samples_for_16_773b_and_16_460vv_17() -> None:
    cases = [
        (
            "us-code-16-773b-d418534f697a23b1",
            "16 U.S.C. 773b",
            _USCODE_16_773B_SYMBOLIC_VALIDITY_TODO_TEXT,
        ),
        (
            "us-code-16-460vv-17-9b754fd1c1a1e8a7",
            "16 U.S.C. 460vv-17",
            _USCODE_16_460VV_17_SYMBOLIC_VALIDITY_TODO_TEXT,
        ),
    ]
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for document_id, citation, text in cases:
            compiled = compiler.compile(
                text,
                document_id=document_id,
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            fallback = compiled.modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
            assert fallback.provenance.citation == citation


def test_modal_compiler_replays_symbolic_validity_samples_for_4_123_5_5564_16_6410_16_47a_16_6808_7_614_and_7_7656() -> None:
    cases = [
        (
            "us-code-4-123-d46eff3eecad7d48",
            "4 U.S.C. 123",
            _USCODE_4_123_SYMBOLIC_VALIDITY_TEXT,
        ),
        (
            "us-code-5-5564-bdff7b035cd4f4cc",
            "5 U.S.C. 5564",
            _USCODE_5_5564_SYMBOLIC_VALIDITY_TEXT,
        ),
        (
            "us-code-16-6410-7cc9d1ff88340f35",
            "16 U.S.C. 6410",
            _USCODE_16_6410_SYMBOLIC_VALIDITY_TEXT,
        ),
        (
            "us-code-16-47a-26c452e74b52db99",
            "16 U.S.C. 47a",
            _USCODE_16_47A_SYMBOLIC_VALIDITY_TEXT,
        ),
        (
            "us-code-16-6808-655096c0f6deada6",
            "16 U.S.C. 6808",
            _USCODE_16_6808_SYMBOLIC_VALIDITY_TEXT,
        ),
        (
            "us-code-7-614-6e310cb5e196544b",
            "7 U.S.C. 614",
            _USCODE_7_614_SYMBOLIC_VALIDITY_TEXT,
        ),
        (
            "us-code-7-7656-ba2dced7f1b0e6ea",
            "7 U.S.C. 7656",
            _USCODE_7_7656_SYMBOLIC_VALIDITY_TEXT,
        ),
    ]
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for document_id, citation, text in cases:
            compiled = compiler.compile(
                text,
                document_id=document_id,
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            assert all(
                formula.provenance.citation == citation
                for formula in compiled.modal_ir.formulas
            )


def test_modal_compiler_replays_long_embedded_section_heading_samples_for_8_1365b_34_50108_and_19_3702() -> None:
    cases = [
        (
            "us-code-8-1365b-a825991ce12b9ec4",
            "8 U.S.C. 1365b",
            _USCODE_8_1365B_SYMBOLIC_VALIDITY_TEXT,
        ),
        (
            "us-code-34-50108-df98f803ad179a0b",
            "34 U.S.C. 50108",
            _USCODE_34_50108_SYMBOLIC_VALIDITY_TEXT,
        ),
        (
            "us-code-19-3702-fb4c53c1694c688a",
            "19 U.S.C. 3702",
            _USCODE_19_3702_SYMBOLIC_VALIDITY_TEXT,
        ),
    ]
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for document_id, citation, text in cases:
            compiled = compiler.compile(
                text,
                document_id=document_id,
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            fallback = compiled.modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
            assert fallback.provenance.citation == citation


def test_modal_compiler_replays_packet_todo_samples_for_7_425_10_2639_and_20_107e_1_with_coarse_procedural_headings() -> None:
    heading = (
        "administrative notice and hearing procedures for eligibility review and petition records"
    )
    cases = [
        (
            "us-code-7-425-90644d368be3f381",
            "7 U.S.C. 425",
            "425",
        ),
        (
            "us-code-10-2639-47081112474a8f75",
            "10 U.S.C. 2639",
            "2639",
        ),
        (
            "us-code-20-107e-1-43ac50498bf68122",
            "20 U.S.C. 107e-1",
            "107e-1",
        ),
    ]
    for backend in ("regex", "spacy"):
        compiler = DeterministicModalCompiler(
            ModalCompilerConfig(
                parser_backend=backend,
                spacy_model_name="definitely_missing_legal_model",
            )
        )
        for document_id, citation, section in cases:
            compiled = compiler.compile(
                _coarse_uscode_procedural_heading_noise_text(section, heading),
                document_id=document_id,
                citation=citation,
                source="us_code",
            )

            assert compiled.modal_ir.formulas
            assert all(
                ambiguity.ambiguity_type != "missing_modal_formula"
                for ambiguity in compiled.ambiguities
            )
            fallback = compiled.modal_ir.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_section_heading_coarse_v1"
            assert fallback.provenance.citation == citation


def test_modal_compiler_surfaces_modal_family_ambiguity_when_cues_overlap() -> None:
    frame_selector = BM25FrameSelector(
        (
            FrameCandidate(
                frame_id="deadline_notice",
                label="Deadline notice",
                terms=("agency", "notice", "within", "days", "written"),
            ),
            FrameCandidate(
                frame_id="import_tariff",
                label="Import tariff",
                terms=("tariff", "customs", "import"),
            ),
        )
    )
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_family_share_margin=0.34,
            modal_family_secondary_share_floor=0.2,
        ),
        frame_selector=frame_selector,
    )

    compiled = compiler.compile(
        "If an application is denied, the agency shall issue written notice within 30 days."
    )

    ambiguity_types = {ambiguity.ambiguity_type for ambiguity in compiled.ambiguities}
    assert "close_modal_family_shares" in ambiguity_types
    assert "temporal_normative_overlap" in ambiguity_types
    temporal_normative = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_normative_overlap"
    )
    assert "temporal" in temporal_normative.candidate_ids
    assert (
        "deontic" in temporal_normative.candidate_ids
        or "conditional_normative" in temporal_normative.candidate_ids
    )
    assert compiled.modal_ir.metadata["modal_family_counts"]["temporal"] >= 1


def test_modal_compiler_surfaces_primary_family_margin_ambiguity_when_outvoted() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_family_share_margin=0.34,
            modal_family_secondary_share_floor=0.2,
            modal_primary_family_margin=0.15,
        )
    )

    compiled = compiler.compile(
        "Within 30 days, the agency must, shall, and is required and obligated and must provide written notice."
    )

    assert compiled.modal_ir.formulas
    assert compiled.modal_ir.formulas[0].operator.family == "temporal"
    low_margin_ambiguity = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "low_primary_modal_family_margin"
    )
    outvoted_ambiguity = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "primary_modal_family_outvoted"
    )
    assert low_margin_ambiguity.candidate_ids == ["temporal", "deontic"]
    assert low_margin_ambiguity.metadata["primary_family"] == "temporal"
    assert low_margin_ambiguity.metadata["best_other_family"] == "deontic"
    assert low_margin_ambiguity.metadata["family_margin"] < 0.0
    assert outvoted_ambiguity.candidate_ids == ["temporal", "deontic"]
    assert outvoted_ambiguity.metadata["primary_family"] == "temporal"
    assert outvoted_ambiguity.metadata["best_other_family"] == "deontic"
    assert outvoted_ambiguity.metadata["family_margin"] < 0.0


def test_modal_compiler_surfaces_frame_family_margin_ambiguity_when_outvoted() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_primary_family_margin=0.15,
        )
    )

    compiled = compiler.compile(
        "The authority must, shall, and is required to issue written notice."
    )

    frame_margin_ambiguity = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "low_frame_modal_family_margin"
    )
    frame_outvoted_ambiguity = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "frame_modal_family_outvoted"
    )
    assert frame_margin_ambiguity.candidate_ids == ["frame", "deontic"]
    assert frame_margin_ambiguity.metadata["competing_family"] == "deontic"
    assert frame_margin_ambiguity.metadata["family_margin"] < 0.0
    assert frame_margin_ambiguity.metadata["frame_share"] > 0.0
    assert frame_outvoted_ambiguity.candidate_ids == ["frame", "deontic"]
    assert frame_outvoted_ambiguity.metadata["competing_family"] == "deontic"
    assert frame_outvoted_ambiguity.metadata["family_margin"] < 0.0


def test_modal_compiler_surfaces_adaptive_family_margin_ambiguity_for_temporal_conflicts() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    compiled = compiler.compile(
        "Notwithstanding subsection (b), within 30 days after review, the secretary shall submit the report."
    )

    adaptive_ambiguities = [
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
    ]
    pairs = {tuple(ambiguity.candidate_ids) for ambiguity in adaptive_ambiguities}
    explicit_types = {
        tuple(ambiguity.candidate_ids): str(ambiguity.metadata["explicit_ambiguity_type"])
        for ambiguity in adaptive_ambiguities
    }
    explicit_adaptive_ambiguities = {
        ambiguity.ambiguity_type: ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
    }
    temporal_frame_pair = next(
        ambiguity
        for ambiguity in adaptive_ambiguities
        if tuple(ambiguity.candidate_ids) == ("temporal", "frame")
    )

    assert ("temporal", "conditional_normative") in pairs
    assert ("temporal", "deontic") in pairs
    assert ("temporal", "frame") in pairs
    assert (
        explicit_types[("temporal", "conditional_normative")]
        == "adaptive_temporal_conditional_normative_outvoted_margin_low"
    )
    assert (
        explicit_types[("temporal", "deontic")]
        == "adaptive_temporal_deontic_outvoted_margin_low"
    )
    assert (
        explicit_types[("temporal", "frame")]
        == "adaptive_temporal_frame_outvoted_margin_low"
    )
    assert "adaptive_temporal_conditional_normative_outvoted_margin_low" in explicit_adaptive_ambiguities
    assert "adaptive_temporal_deontic_outvoted_margin_low" in explicit_adaptive_ambiguities
    assert "adaptive_temporal_frame_outvoted_margin_low" in explicit_adaptive_ambiguities
    assert temporal_frame_pair.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert temporal_frame_pair.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert all(
        ambiguity.metadata["adaptive_base_ambiguity_type"] == "adaptive_family_margin_low"
        for ambiguity in explicit_adaptive_ambiguities.values()
    )
    assert all(
        ambiguity.metadata["adaptive_family_margin_threshold"] == 0.15
        for ambiguity in adaptive_ambiguities
    )
    assert all(
        ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        for ambiguity in adaptive_ambiguities
    )
    assert all(ambiguity.metadata["family_margin"] <= 0.0 for ambiguity in adaptive_ambiguities)


def test_modal_compiler_backfills_missing_explicit_adaptive_ambiguity_from_base_record() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    base_ambiguity = ModalCompilationAmbiguity(
        ambiguity_type="adaptive_family_margin_low",
        message="base adaptive ambiguity",
        candidate_ids=["frame", "deontic"],
        severity="requires_rule",
        metadata={
            "adaptive_policy_pair": "frame->deontic",
            "adaptive_predicted_family_source": "ranked_modal_families",
            "explicit_ambiguity_type": "adaptive_frame_deontic_outvoted_margin_low",
            "is_self_pair": False,
        },
    )

    ambiguities = compiler._ensure_explicit_adaptive_ambiguities([base_ambiguity])

    explicit = [
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_frame_deontic_outvoted_margin_low"
    ]
    assert len(explicit) == 1
    assert explicit[0].candidate_ids == ["frame", "deontic"]
    assert explicit[0].severity == "requires_rule"
    assert explicit[0].metadata["adaptive_base_ambiguity_type"] == (
        "adaptive_family_margin_low"
    )


def test_modal_compiler_derives_missing_explicit_adaptive_ambiguity_type_from_policy_pair() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    base_ambiguity = ModalCompilationAmbiguity(
        ambiguity_type="adaptive_family_margin_low",
        message="base adaptive ambiguity",
        candidate_ids=["conditional_normative", "temporal"],
        severity="requires_rule",
        metadata={
            "adaptive_margin_direction": "outvoted",
            "adaptive_policy_pair": "conditional_normative->temporal",
            "adaptive_predicted_family_source": "ranked_modal_families",
            "family_margin": -0.146643,
            "is_self_pair": False,
        },
    )

    ambiguities = compiler._ensure_explicit_adaptive_ambiguities([base_ambiguity])

    explicit = [
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type
        == "adaptive_conditional_normative_temporal_outvoted_margin_low"
    ]
    assert len(explicit) == 1
    assert explicit[0].candidate_ids == ["conditional_normative", "temporal"]
    assert explicit[0].severity == "requires_rule"
    assert explicit[0].metadata["adaptive_base_ambiguity_type"] == (
        "adaptive_family_margin_low"
    )


def test_modal_compiler_canonicalizes_policy_pair_families_when_backfilling_explicit_adaptive_ambiguity() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    base_ambiguity = ModalCompilationAmbiguity(
        ambiguity_type="adaptive_family_margin_low",
        message="base adaptive ambiguity",
        candidate_ids=[],
        severity="requires_rule",
        metadata={
            "adaptive_margin_direction": "outvoted",
            "adaptive_policy_pair": "ModalLogicFamily.FRAME->DEONTIC",
            "adaptive_predicted_family_source": "ranked_modal_families",
            "is_self_pair": False,
        },
    )

    ambiguities = compiler._ensure_explicit_adaptive_ambiguities([base_ambiguity])

    explicit = [
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_frame_deontic_outvoted_margin_low"
    ]
    assert len(explicit) == 1
    assert explicit[0].candidate_ids == ["frame", "deontic"]
    assert explicit[0].metadata["predicted_family"] == "frame"
    assert explicit[0].metadata["target_family"] == "deontic"
    assert explicit[0].metadata["adaptive_base_ambiguity_type"] == (
        "adaptive_family_margin_low"
    )


def test_modal_compiler_prefers_directional_target_side_when_backfilling_explicit_adaptive_ambiguity() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    base_ambiguity = ModalCompilationAmbiguity(
        ambiguity_type="adaptive_family_margin_low",
        message="base adaptive ambiguity",
        candidate_ids=["frame", "deontic"],
        severity="requires_rule",
        metadata={
            "adaptive_margin_direction": "outvoted",
            "adaptive_policy_pair": "frame->deontic",
            "adaptive_predicted_family_source": "ranked_modal_families",
            "predicted_family": "frame",
            "target_family": "frame->deontic",
            "is_self_pair": False,
        },
    )

    ambiguities = compiler._ensure_explicit_adaptive_ambiguities([base_ambiguity])

    explicit = [
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_frame_deontic_outvoted_margin_low"
    ]
    assert len(explicit) == 1
    assert explicit[0].candidate_ids == ["frame", "deontic"]
    assert explicit[0].metadata["predicted_family"] == "frame"
    assert explicit[0].metadata["target_family"] == "deontic"
    assert explicit[0].metadata["adaptive_base_ambiguity_type"] == (
        "adaptive_family_margin_low"
    )


def test_modal_compiler_does_not_duplicate_existing_explicit_adaptive_ambiguity_record() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    base_ambiguity = ModalCompilationAmbiguity(
        ambiguity_type="adaptive_family_margin_low",
        message="base adaptive ambiguity",
        candidate_ids=["frame", "deontic"],
        severity="requires_rule",
        metadata={
            "adaptive_policy_pair": "frame->deontic",
            "adaptive_predicted_family_source": "ranked_modal_families",
            "explicit_ambiguity_type": "adaptive_frame_deontic_outvoted_margin_low",
            "is_self_pair": False,
        },
    )
    explicit_ambiguity = ModalCompilationAmbiguity(
        ambiguity_type="adaptive_frame_deontic_outvoted_margin_low",
        message="explicit adaptive ambiguity",
        candidate_ids=["frame", "deontic"],
        severity="requires_rule",
        metadata={
            "adaptive_base_ambiguity_type": "adaptive_family_margin_low",
            "adaptive_policy_pair": "frame->deontic",
            "adaptive_predicted_family_source": "ranked_modal_families",
        },
    )

    ambiguities = compiler._ensure_explicit_adaptive_ambiguities(
        [base_ambiguity, explicit_ambiguity]
    )

    assert (
        sum(
            1
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type
            == "adaptive_frame_deontic_outvoted_margin_low"
        )
        == 1
    )


def test_modal_compiler_backfills_explicit_adaptive_ambiguity_when_metadata_is_missing() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    base_ambiguity = ModalCompilationAmbiguity(
        ambiguity_type="adaptive_family_margin_low",
        message="base adaptive ambiguity",
        candidate_ids=["frame", "deontic"],
        severity="requires_rule",
        metadata=None,  # type: ignore[arg-type]
    )

    ambiguities = compiler._ensure_explicit_adaptive_ambiguities([base_ambiguity])

    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_deontic_outvoted_margin_low"
        and ambiguity.candidate_ids == ["frame", "deontic"]
        and ambiguity.metadata["adaptive_base_ambiguity_type"]
        == "adaptive_family_margin_low"
        for ambiguity in ambiguities
    )


def test_modal_compiler_backfills_explicit_adaptive_ambiguity_from_direct_adaptive_emitter_when_explicit_type_degrades(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    call_counts: dict[tuple[str, str, str], int] = {}

    def _degrade_temporal_self_once(
        self,
        predicted_family: str,
        target_family: str,
        margin_direction: str,
    ) -> str:
        key = (predicted_family, target_family, margin_direction)
        call_counts[key] = call_counts.get(key, 0) + 1
        if (
            key == ("temporal", "temporal", "contested")
            and call_counts[key] == 1
        ):
            return "adaptive_family_margin_low"
        return (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}"
            "_margin_low"
        )

    monkeypatch.setattr(
        DeterministicModalCompiler,
        "_adaptive_margin_explicit_type",
        _degrade_temporal_self_once,
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-explicit-backfill-direct-emitter-doc",
        text="Within 30 days the filing deadline applies.",
        normalized_text="Within 30 days the filing deadline applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-explicit-backfill-direct-emitter-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="filing_deadline",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-explicit-backfill-direct-emitter-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="10 U.S.C. 12645",
                ),
            ),
        ],
    )

    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "temporal", "count": 2, "share": 0.52},
            {"family": "frame", "count": 2, "share": 0.48},
        ],
        family_shares={"temporal": 0.52, "frame": 0.48},
    )

    adaptive_temporal_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal"]
    )
    assert adaptive_temporal_self.metadata["explicit_ambiguity_type"] == (
        "adaptive_family_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_temporal_contested_margin_low"
        and ambiguity.candidate_ids == ["temporal"]
        and ambiguity.metadata["adaptive_base_ambiguity_type"]
        == "adaptive_family_margin_low"
        and ambiguity.metadata["adaptive_policy_pair"] == "temporal->temporal"
        for ambiguity in ambiguities
    )


def test_modal_compiler_emits_adaptive_logits_ambiguity_for_same_top_low_margin(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.ranked_modal_families",
        lambda _: [
            {"family": "deontic", "count": 2, "share_raw": 0.74, "share": 0.74},
            {"family": "frame", "count": 1, "share_raw": 0.11, "share": 0.11},
        ],
    )
    monkeypatch.setattr(
        compiler,
        "_adaptive_family_ranking_from_logits",
        lambda _: [
            {"family": "deontic", "count": 0, "share_raw": 0.51, "share": 0.51},
            {"family": "frame", "count": 0, "share_raw": 0.49, "share": 0.49},
        ],
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-same-top-low-margin-doc",
        text="The agency shall issue notice.",
        normalized_text="The agency shall issue notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-same-top-low-margin-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="issue_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-same-top-low-margin-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )

    ambiguities = compiler._family_ambiguities(encoding, modal_ir=modal_ir)

    adaptive_logits_pair = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "frame"]
        and ambiguity.metadata["adaptive_predicted_family_source"] == "adaptive_logits"
    )
    assert adaptive_logits_pair.metadata["explicit_ambiguity_type"] == (
        "adaptive_deontic_frame_outvoted_margin_low"
    )
    assert adaptive_logits_pair.metadata["family_margin"] == -0.02
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_frame_outvoted_margin_low"
        and ambiguity.candidate_ids == ["deontic", "frame"]
        and ambiguity.metadata["adaptive_predicted_family_source"] == "adaptive_logits"
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_compiled_family_as_adaptive_ambiguity_signal(monkeypatch) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {
            "has_alethic_cue": False,
            "has_alethic_scope": False,
            "has_alethic_scope_phrase": False,
            "has_calendar_date_scope": False,
            "has_condition_clause": False,
            "has_condition_or_exception_scope": False,
            "has_conditional_scope_phrase": False,
            "has_conditional_scope_token": False,
            "has_deontic_cue": False,
            "has_deontic_scope": False,
            "has_deontic_scope_phrase": False,
            "has_dynamic_cue": False,
            "has_dynamic_scope": False,
            "has_dynamic_scope_phrase": False,
            "has_exception_clause": False,
            "has_frame_context": False,
            "has_frame_cue": False,
            "has_frame_scope_phrase": False,
            "has_statutory_scope_reference": False,
            "has_temporal_scope": False,
            "has_temporal_scope_phrase": False,
        },
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-formula-signal-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-formula-signal-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-formula-signal-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="20 U.S.C. 7261",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "temporal", "count": 1, "share": 1.0}],
        family_shares={"temporal": 1.0},
    )

    adaptive_deontic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "deontic"]
    )
    assert adaptive_deontic.metadata["has_compiled_target_family_formula"] is True
    assert adaptive_deontic.metadata["target_share"] == 0.0
    assert adaptive_deontic.metadata["lexical_signals"]["has_deontic_scope"] is False
    assert adaptive_deontic.metadata["compiled_modal_families"] == ["deontic"]
    assert (
        adaptive_deontic.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_deontic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_deontic_outvoted_margin_low"
        and ambiguity.metadata["has_compiled_target_family_formula"] is True
        for ambiguity in ambiguities
    )
    compiled_primary_pair = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "temporal"]
    )
    assert compiled_primary_pair.metadata["adaptive_predicted_family_source"] == (
        "compiled_primary_family"
    )
    assert compiled_primary_pair.metadata["predicted_family"] == "deontic"
    assert compiled_primary_pair.metadata["target_family"] == "temporal"
    assert compiled_primary_pair.metadata["family_margin"] < 0.0
    assert (
        compiled_primary_pair.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_temporal_outvoted_margin_low"
        and ambiguity.metadata["adaptive_predicted_family_source"]
        == "compiled_primary_family"
        for ambiguity in ambiguities
    )


def test_modal_compiler_emits_compiled_primary_self_pair_ambiguity_for_low_margin(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-compiled-primary-self-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-compiled-primary-self-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-compiled-primary-self-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="20 U.S.C. 7261",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "temporal", "count": 1, "share": 0.52},
            {"family": "deontic", "count": 1, "share": 0.48},
        ],
        family_shares={"temporal": 0.52, "deontic": 0.48},
    )

    compiled_primary_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic"]
        and ambiguity.metadata["adaptive_predicted_family_source"]
        == "compiled_primary_family"
    )
    assert (
        sum(
            1
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == ["deontic"]
            and ambiguity.metadata["adaptive_predicted_family_source"]
            == "compiled_primary_family"
        )
        == 1
    )
    assert compiled_primary_self.metadata["is_self_pair"] is True
    assert compiled_primary_self.metadata["adaptive_policy_pair"] == "deontic->deontic"
    assert compiled_primary_self.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert compiled_primary_self.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert compiled_primary_self.metadata["runner_up_family"] == "temporal"
    assert (
        compiled_primary_self.metadata["runner_up_is_compiler_ambiguity_bundle_pair"]
        is True
    )
    assert (
        compiled_primary_self.metadata["effective_compiler_ambiguity_policy_pair"]
        == "deontic->temporal"
    )
    assert (
        compiled_primary_self.metadata["effective_ambiguity_policy_bundle"]
        == "compiler_ambiguity"
    )
    assert compiled_primary_self.metadata["family_margin"] == -0.04
    assert compiled_primary_self.metadata["adaptive_margin_direction"] == "outvoted"
    assert (
        compiled_primary_self.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_deontic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_deontic_outvoted_margin_low"
        and ambiguity.metadata["adaptive_predicted_family_source"]
        == "compiled_primary_family"
        for ambiguity in ambiguities
    )
    assert (
        sum(
            1
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type
            == "adaptive_deontic_deontic_outvoted_margin_low"
            and ambiguity.metadata["adaptive_predicted_family_source"]
            == "compiled_primary_family"
        )
        == 1
    )


def test_modal_compiler_marks_temporal_self_pair_as_compiler_required_policy(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-temporal-self-policy-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-temporal-self-policy-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-temporal-self-policy-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="20 U.S.C. 7261",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "temporal", "count": 1, "share": 0.5},
            {"family": "frame", "count": 1, "share": 0.5},
        ],
        family_shares={"temporal": 0.5, "frame": 0.5},
    )

    temporal_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal"]
        and ambiguity.metadata["adaptive_policy_pair"] == "temporal->temporal"
    )
    assert temporal_self.metadata["family_margin"] == 0.0
    assert temporal_self.metadata["adaptive_margin_direction"] == "outvoted"
    assert temporal_self.metadata["is_compiler_required_policy_pair"] is True
    assert temporal_self.metadata["runner_up_is_compiler_required_policy_pair"] is True
    assert temporal_self.metadata["explicit_ambiguity_type"] == (
        "adaptive_temporal_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_temporal_outvoted_margin_low"
        and ambiguity.candidate_ids == ["temporal"]
        for ambiguity in ambiguities
    )


def test_modal_compiler_marks_conditional_self_pair_as_compiler_required_policy(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-conditional-self-policy-doc",
        text="Provided that notice applies.",
        normalized_text="Provided that notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="conditional_normative",
                system="KD",
                symbol="O|",
                label="conditional_obligation",
                cue="provided that",
                start_char=0,
                end_char=13,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-conditional-self-policy-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-conditional-1",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="KD",
                    symbol="O|",
                    label="conditional_obligation",
                ),
                predicate=ModalIRPredicate(
                    name="conditional_notice_applies",
                    arguments=["actor:agency"],
                    role="conditional_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-conditional-self-policy-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="42 U.S.C. 300aa-22",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "conditional_normative", "count": 1, "share": 0.5},
            {"family": "deontic", "count": 1, "share": 0.5},
        ],
        family_shares={"conditional_normative": 0.5, "deontic": 0.5},
    )

    conditional_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative"]
        and ambiguity.metadata["adaptive_policy_pair"]
        == "conditional_normative->conditional_normative"
    )
    assert conditional_self.metadata["family_margin"] == 0.0
    assert conditional_self.metadata["adaptive_margin_direction"] == "outvoted"
    assert conditional_self.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert conditional_self.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert conditional_self.metadata["is_compiler_required_policy_pair"] is True
    assert conditional_self.metadata["runner_up_is_compiler_required_policy_pair"] is True
    assert conditional_self.severity == "requires_rule"
    assert conditional_self.metadata["explicit_ambiguity_type"] == (
        "adaptive_conditional_normative_conditional_normative_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_conditional_normative_conditional_normative_outvoted_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative"]
        for ambiguity in ambiguities
    )


def test_modal_compiler_includes_temporal_self_pair_when_margin_is_threshold_with_float_noise(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-temporal-self-float-noise-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-temporal-self-float-noise-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-temporal-self-float-noise-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="20 U.S.C. 7261",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "temporal", "count": 1, "share": 0.5750000000000001},
            {"family": "frame", "count": 1, "share": 0.425},
        ],
        family_shares={"temporal": 0.5750000000000001, "frame": 0.425},
    )

    temporal_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal"]
        and ambiguity.metadata["adaptive_policy_pair"] == "temporal->temporal"
    )
    assert temporal_self.metadata["adaptive_margin_direction"] == "contested"
    assert temporal_self.metadata["is_compiler_required_policy_pair"] is True
    assert temporal_self.metadata["explicit_ambiguity_type"] == (
        "adaptive_temporal_temporal_contested_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_temporal_contested_margin_low"
        and ambiguity.candidate_ids == ["temporal"]
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_temporal_deontic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-temporal-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-temporal-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-temporal-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 607",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "temporal", "count": 1, "share": 1.0}],
        family_shares={"temporal": 1.0},
    )

    adaptive_deontic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "deontic"]
    )
    assert adaptive_deontic.metadata["has_target_signal_evidence"] is False
    assert adaptive_deontic.metadata["signal_free_pair_policy_applied"] is True
    assert (
        adaptive_deontic.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_deontic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_deontic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_deontic_cue_signal_for_temporal_deontic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {"has_deontic_cue": True},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signaled-temporal-deontic-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signaled-temporal-deontic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signaled-temporal-deontic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 607",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "temporal", "count": 1, "share": 1.0}],
        family_shares={"temporal": 1.0},
    )

    adaptive_deontic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "deontic"]
    )
    assert adaptive_deontic.metadata["has_target_signal_evidence"] is True
    assert adaptive_deontic.metadata["signal_free_pair_policy_applied"] is False
    assert (
        adaptive_deontic.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_deontic_outvoted_margin_low"
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_temporal_alethic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-temporal-alethic-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-temporal-alethic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-temporal-alethic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="29 U.S.C. 161",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "temporal", "count": 1, "share": 1.0}],
        family_shares={"temporal": 1.0},
    )

    adaptive_alethic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "alethic"]
    )
    assert adaptive_alethic.metadata["has_target_signal_evidence"] is False
    assert adaptive_alethic.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_alethic.metadata["is_priority_policy_pair"] is True
    assert adaptive_alethic.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_alethic.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_alethic.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_alethic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_alethic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        and ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_conditional_temporal_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-conditional-doc",
        text="Provided that notice applies.",
        normalized_text="Provided that notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="conditional_normative",
                system="STIT",
                symbol="O_if",
                label="conditional_obligation",
                cue="provided that",
                start_char=0,
                end_char=13,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-conditional-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-conditional-1",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="STIT",
                    symbol="O_if",
                    label="conditional_obligation",
                ),
                predicate=ModalIRPredicate(
                    name="conditional_notice_obligation",
                    arguments=["actor:agency"],
                    role="conditional_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-conditional-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="42 U.S.C. 300aa-22",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "conditional_normative", "count": 1, "share": 0.5},
            {"family": "deontic", "count": 1, "share": 0.5},
        ],
        family_shares={
            "conditional_normative": 0.5,
            "deontic": 0.5,
        },
    )

    adaptive_conditional_temporal = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative", "temporal"]
    )
    assert adaptive_conditional_temporal.metadata["adaptive_policy_pair"] == (
        "conditional_normative->temporal"
    )
    assert adaptive_conditional_temporal.metadata["has_target_signal_evidence"] is False
    assert adaptive_conditional_temporal.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_conditional_temporal.metadata["family_margin"] == -0.5
    assert adaptive_conditional_temporal.metadata["adaptive_margin_direction"] == "outvoted"
    assert (
        adaptive_conditional_temporal.metadata["explicit_ambiguity_type"]
        == "adaptive_conditional_normative_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_conditional_normative_temporal_outvoted_margin_low"
        and ambiguity.metadata["adaptive_policy_pair"]
        == "conditional_normative->temporal"
        for ambiguity in ambiguities
    )


def test_modal_compiler_emits_contested_deontic_self_adaptive_ambiguity_for_positive_low_margin(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-contested-deontic-self-doc",
        text="The agency shall provide notice.",
        normalized_text="The agency shall provide notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-contested-deontic-self-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-contested-deontic-self-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="42 U.S.C. 300x-12",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "deontic", "count": 1, "share": 0.521786},
            {"family": "temporal", "count": 1, "share": 0.478214},
        ],
        family_shares={
            "deontic": 0.521786,
            "temporal": 0.478214,
        },
    )

    adaptive_deontic_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic"]
    )
    assert adaptive_deontic_self.metadata["adaptive_policy_pair"] == "deontic->deontic"
    assert adaptive_deontic_self.metadata["adaptive_margin_direction"] == "contested"
    assert 0.0 < adaptive_deontic_self.metadata["family_margin"] < 0.15
    assert adaptive_deontic_self.severity == "review"
    assert (
        adaptive_deontic_self.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_deontic_contested_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_deontic_contested_margin_low"
        and ambiguity.metadata["adaptive_policy_pair"] == "deontic->deontic"
        for ambiguity in ambiguities
    )


def test_modal_compiler_emits_explicit_adaptive_ambiguity_for_recurrent_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        (
            "deontic",
            "D",
            "O",
            "shall",
            [
                {"family": "deontic", "count": 1, "share": 0.5},
                {"family": "temporal", "count": 1, "share": 0.5},
            ],
            {
                "deontic": 0.5,
                "temporal": 0.5,
            },
            (
                "deontic->deontic",
                "deontic->conditional_normative",
                "deontic->frame",
                "deontic->temporal",
                "deontic->dynamic",
                "deontic->epistemic",
            ),
        ),
        (
            "frame",
            "FRAME_BM25",
            "Frame",
            "authority",
            [{"family": "frame", "count": 1, "share": 1.0}],
            {"frame": 1.0},
            (
                "frame->conditional_normative",
                "frame->deontic",
                "frame->alethic",
                "frame->epistemic",
                "frame->temporal",
            ),
        ),
        (
            "alethic",
            "S5",
            "□",
            "necessary",
            [{"family": "alethic", "count": 1, "share": 1.0}],
            {"alethic": 1.0},
            (
                "alethic->deontic",
                "alethic->conditional_normative",
                "alethic->epistemic",
                "alethic->temporal",
                "alethic->frame",
            ),
        ),
        (
            "temporal",
            "LTL",
            "F",
            "within",
            [
                {"family": "temporal", "count": 1, "share": 0.5},
                {"family": "deontic", "count": 1, "share": 0.5},
            ],
            {
                "temporal": 0.5,
                "deontic": 0.5,
            },
            (
                "temporal->deontic",
                "temporal->alethic",
                "temporal->epistemic",
                "temporal->conditional_normative",
                "temporal->frame",
                "temporal->dynamic",
                "temporal->temporal",
            ),
        ),
    )

    for index, (
        predicted_family,
        system,
        symbol,
        cue,
        ranking,
        family_shares,
        expected_policy_pairs,
    ) in enumerate(scenarios, start=1):
        doc_id = f"adaptive-policy-pairs-{predicted_family}-{index}"
        encoding = SpaCyLegalEncoding(
            document_id=doc_id,
            text=f"Synthetic {predicted_family} clause.",
            normalized_text=f"Synthetic {predicted_family} clause.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=system,
                    symbol=symbol,
                    label=f"{predicted_family}-label",
                    cue=cue,
                    start_char=0,
                    end_char=max(1, len(cue)),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=doc_id,
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-1",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=system,
                        symbol=symbol,
                        label=f"{predicted_family}-label",
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=doc_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="42 U.S.C. 1983",
                    ),
                ),
            ],
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
        )
        adaptive_base_ambiguities = [
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        ]
        by_policy_pair = {
            str(ambiguity.metadata["adaptive_policy_pair"]): ambiguity
            for ambiguity in adaptive_base_ambiguities
        }
        assert set(expected_policy_pairs).issubset(by_policy_pair)
        for policy_pair in expected_policy_pairs:
            predicted, target = policy_pair.split("->", maxsplit=1)
            expected_explicit_type = by_policy_pair[policy_pair].metadata[
                "explicit_ambiguity_type"
            ]
            if predicted == target:
                assert expected_explicit_type.startswith(
                    f"adaptive_{predicted}_{target}_"
                )
            else:
                assert (
                    expected_explicit_type
                    == f"adaptive_{predicted}_{target}_outvoted_margin_low"
                )
            assert any(
                ambiguity.ambiguity_type == expected_explicit_type
                and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
                and ambiguity.metadata["adaptive_base_ambiguity_type"]
                == "adaptive_family_margin_low"
                for ambiguity in ambiguities
            )


def test_modal_compiler_resolves_compiler_ambiguity_targets_from_current_module_after_reload(
    monkeypatch,
) -> None:
    module_name = "ipfs_datasets_py.logic.modal.compiler"
    old_module = importlib.import_module(module_name)
    old_compiler_class = old_module.DeterministicModalCompiler

    sys.modules.pop(module_name, None)
    reloaded_module = importlib.import_module(module_name)
    monkeypatch.setattr(
        reloaded_module,
        "priority_signal_free_adaptive_ambiguity_targets",
        lambda _: (),
    )
    monkeypatch.setattr(
        reloaded_module,
        "compiler_required_adaptive_ambiguity_targets",
        lambda _: (),
    )
    monkeypatch.setattr(
        reloaded_module,
        "compiler_ambiguity_policy_targets",
        lambda _: ("hybrid",),
    )
    monkeypatch.setattr(
        reloaded_module,
        "signal_free_adaptive_ambiguity_targets",
        lambda _: (),
    )

    compiler = old_compiler_class(ModalCompilerConfig(parser_backend="regex"))
    assert compiler._ordered_policy_target_families("deontic") == ["hybrid"]


def test_modal_compiler_resolves_signal_free_pair_hook_from_current_module_after_reload(
    monkeypatch,
) -> None:
    module_name = "ipfs_datasets_py.logic.modal.compiler"
    old_module = importlib.import_module(module_name)
    old_compiler_class = old_module.DeterministicModalCompiler

    sys.modules.pop(module_name, None)
    reloaded_module = importlib.import_module(module_name)
    monkeypatch.setattr(
        reloaded_module,
        "priority_signal_free_adaptive_ambiguity_targets",
        lambda _: (),
    )
    monkeypatch.setattr(
        reloaded_module,
        "compiler_required_adaptive_ambiguity_targets",
        lambda _: (),
    )
    monkeypatch.setattr(
        reloaded_module,
        "compiler_ambiguity_policy_targets",
        lambda _: (),
    )
    monkeypatch.setattr(
        reloaded_module,
        "signal_free_adaptive_ambiguity_targets",
        lambda _: (),
    )
    monkeypatch.setattr(
        reloaded_module,
        "is_compiler_ambiguity_policy_pair",
        lambda _predicted_family, _target_family: False,
    )
    monkeypatch.setattr(
        reloaded_module,
        "is_signal_free_adaptive_ambiguity_pair",
        lambda predicted_family, target_family: (
            predicted_family == "hybrid" and target_family == "doxastic"
        ),
    )

    compiler = old_compiler_class(ModalCompilerConfig(parser_backend="regex"))
    assert compiler._supports_signal_free_adaptive_pair("frame", "deontic") is False
    assert compiler._supports_signal_free_adaptive_pair("hybrid", "doxastic") is True


def test_modal_registry_resolves_dot_value_family_tokens_for_policy_pairs() -> None:
    assert (
        supports_signal_free_adaptive_ambiguity_pair(
            "ModalLogicFamily.FRAME.value",
            "ModalLogicFamily.TEMPORAL.value",
        )
        is True
    )
    assert (
        is_compiler_ambiguity_policy_pair(
            "ModalLogicFamily.TEMPORAL.value",
            "ModalLogicFamily.DEONTIC.value",
        )
        is True
    )


def test_modal_registry_supports_todo_compiler_ambiguity_family_pairs() -> None:
    todo_pairs = (
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
        ("temporal", "frame"),
        ("frame", "frame"),
        ("temporal", "conditional_normative"),
        ("temporal", "dynamic"),
        ("temporal", "deontic"),
        ("deontic", "doxastic"),
        ("deontic", "deontic"),
        ("doxastic", "epistemic"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("temporal", "conditional_normative"),
        ("temporal", "frame"),
        ("temporal", "dynamic"),
    )
    for predicted_family, target_family in todo_pairs:
        assert (
            supports_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            is_compiler_ambiguity_policy_pair(
                predicted_family,
                target_family,
            )
            is True
        )


def test_modal_registry_applies_refined_cue_margin_buffer_for_packet_001558_pairs() -> None:
    packet_pairs = (
        ("conditional_normative", "frame"),
        ("deontic", "temporal"),
        ("epistemic", "conditional_normative"),
    )
    for predicted_family, target_family in packet_pairs:
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - 0.0015
            )
            < 1e-12
        )


def test_modal_registry_applies_refined_cue_margin_buffer_for_packet_001257_pairs() -> None:
    packet_pairs = (
        ("conditional_normative", "frame"),
        ("conditional_normative", "deontic"),
        ("deontic", "frame"),
        ("deontic", "temporal"),
        ("epistemic", "conditional_normative"),
        ("temporal", "deontic"),
    )
    for predicted_family, target_family in packet_pairs:
        assert (
            supports_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            is_compiler_ambiguity_policy_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - 0.0015
            )
            < 1e-12
        )


def test_modal_registry_applies_refined_cue_margin_buffer_for_packet_001605_pairs() -> None:
    packet_pairs = (
        ("deontic", "conditional_normative"),
        ("temporal", "deontic"),
        ("conditional_normative", "deontic"),
        ("deontic", "deontic"),
        ("deontic", "frame"),
        ("deontic", "temporal"),
    )
    for predicted_family, target_family in packet_pairs:
        assert (
            supports_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            is_compiler_ambiguity_policy_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - 0.0015
            )
            < 1e-12
        )


def test_modal_registry_applies_refined_cue_margin_buffer_for_packet_001759_pairs() -> None:
    packet_pairs = (
        ("conditional_normative", "deontic"),
        ("deontic", "frame"),
        ("deontic", "temporal"),
    )
    for predicted_family, target_family in packet_pairs:
        assert (
            supports_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            is_compiler_ambiguity_policy_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - 0.0015
            )
            < 1e-12
        )


def test_modal_registry_applies_refined_cue_margin_buffer_for_packet_003252_pairs() -> None:
    packet_pairs = (
        ("deontic", "frame"),
        ("temporal", "deontic"),
        ("temporal", "epistemic"),
        ("deontic", "deontic"),
        ("deontic", "temporal"),
        ("epistemic", "deontic"),
        ("conditional_normative", "deontic"),
    )
    for predicted_family, target_family in packet_pairs:
        assert (
            supports_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            is_compiler_ambiguity_policy_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - 0.0015
            )
            < 1e-12
        )


def test_modal_registry_applies_refined_cue_margin_buffer_for_packet_003148_pairs() -> None:
    packet_pairs = (
        ("deontic", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    )
    assert tuple(COMPILER_REFINED_PACKET_003148_FAMILY_PAIRS) == packet_pairs
    expected_buffers = {
        ("deontic", "conditional_normative"): 0.0015,
        ("frame", "deontic"): 0.0015,
        ("frame", "temporal"): 0.002,
    }
    for predicted_family, target_family in packet_pairs:
        assert (
            supports_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            is_compiler_ambiguity_policy_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - expected_buffers[(predicted_family, target_family)]
            )
            < 1e-12
        )


def test_modal_registry_applies_refined_cue_margin_buffer_for_packet_000043_pairs() -> None:
    packet_pairs = (
        ("frame", "deontic"),
        ("frame", "frame"),
        ("frame", "temporal"),
        ("temporal", "conditional_normative"),
    )
    assert tuple(COMPILER_REFINED_PACKET_000043_FAMILY_PAIRS) == packet_pairs
    expected_buffers = {
        ("frame", "deontic"): 0.0015,
        ("frame", "frame"): 0.135,
        ("frame", "temporal"): 0.002,
        ("temporal", "conditional_normative"): 0.0015,
    }
    for predicted_family, target_family in packet_pairs:
        assert (
            supports_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            is_compiler_ambiguity_policy_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - expected_buffers[(predicted_family, target_family)]
            )
            < 1e-12
        )


def test_modal_registry_applies_refined_cue_margin_buffer_for_packet_000044_pairs() -> None:
    packet_pairs = (
        ("deontic", "deontic"),
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
        ("temporal", "frame"),
    )
    assert tuple(COMPILER_REFINED_PACKET_000044_FAMILY_PAIRS) == packet_pairs
    expected_buffers = {
        ("deontic", "deontic"): 0.0015,
        ("deontic", "temporal"): 0.0015,
        ("frame", "conditional_normative"): 0.0015,
        ("frame", "deontic"): 0.0015,
        ("frame", "temporal"): 0.002,
        ("temporal", "frame"): 0.0015,
    }
    for predicted_family, target_family in packet_pairs:
        assert (
            supports_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            is_compiler_ambiguity_policy_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - expected_buffers[(predicted_family, target_family)]
            )
            < 1e-12
        )


def test_modal_registry_applies_refined_cue_margin_buffer_for_packet_000112_pairs() -> None:
    packet_pairs = (
        ("deontic", "deontic"),
        ("deontic", "temporal"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    )
    assert tuple(COMPILER_REFINED_PACKET_000112_FAMILY_PAIRS) == packet_pairs
    expected_buffers = {
        ("deontic", "deontic"): 0.0015,
        ("deontic", "temporal"): 0.0015,
        ("frame", "deontic"): 0.0015,
        ("frame", "temporal"): 0.002,
    }
    for predicted_family, target_family in packet_pairs:
        assert (
            supports_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            is_compiler_ambiguity_policy_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - expected_buffers[(predicted_family, target_family)]
            )
            < 1e-12
        )


def test_modal_registry_applies_refined_cue_margin_buffer_for_packet_003624_pairs() -> None:
    packet_pairs = (
        ("conditional_normative", "temporal"),
        ("deontic", "deontic"),
        ("temporal", "frame"),
        ("temporal", "temporal"),
    )
    assert tuple(COMPILER_AMBIGUITY_PACKET_003624_FAMILY_PAIRS) == packet_pairs
    for predicted_family, target_family in packet_pairs:
        assert (
            supports_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            is_compiler_ambiguity_policy_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - 0.0015
            )
            < 1e-12
        )


def test_modal_registry_applies_refined_cue_margin_buffer_for_packet_000593_pairs() -> None:
    packet_pairs = (
        ("conditional_normative", "deontic"),
        ("deontic", "frame"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "epistemic"),
        ("frame", "temporal"),
        ("temporal", "frame"),
    )
    assert tuple(COMPILER_REFINED_PACKET_000593_FAMILY_PAIRS) == packet_pairs
def test_modal_registry_applies_refined_cue_policy_for_packet_002680_pairs() -> None:
    packet_pairs = (
        ("deontic", "alethic"),
        ("deontic", "conditional_normative"),
        ("frame", "alethic"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "doxastic"),
        ("frame", "temporal"),
    )
    assert tuple(COMPILER_AMBIGUITY_PACKET_002680_FAMILY_PAIRS) == packet_pairs
    for predicted_family, target_family in packet_pairs:
        assert (
            supports_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            is_compiler_ambiguity_policy_pair(
                predicted_family,
                target_family,
            )
            is True
        )
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR[
                    (predicted_family, target_family)
                ]
            )
            < 1e-12
        )
        assert compiler_refined_modal_family_cue_margin_buffer(
            predicted_family,
            target_family,
        ) >= 0.0015


def test_modal_registry_refined_cue_margin_buffer_keys_are_pair_shaped() -> None:
    assert all(
        isinstance(pair, tuple) and len(pair) == 2
        for pair in COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR
    )


def test_modal_registry_packet_000001_rescue_keeps_signal_free_frame_policy() -> None:
    rescue_pair_buffers = (
        (("deontic", "conditional_normative"), 0.0015),
        (("frame", "alethic"), 0.0015),
        (("frame", "conditional_normative"), 0.0015),
        (("frame", "deontic"), 0.0015),
        (("frame", "doxastic"), 0.0015),
        (("frame", "epistemic"), 0.002),
        (("frame", "temporal"), 0.002),
    )

    for rescue_pair, expected_buffer in rescue_pair_buffers:
        assert rescue_pair in COMPILER_REFINED_PACKET_000001_RESCUE_FAMILY_PAIRS
        assert is_compiler_ambiguity_policy_pair(*rescue_pair) is True
        assert supports_signal_free_adaptive_ambiguity_pair(*rescue_pair) is True
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(*rescue_pair)
                - expected_buffer
            )
            < 1e-12
        )
    assert ("frame", "dynamic") not in COMPILER_REFINED_PACKET_000001_RESCUE_FAMILY_PAIRS
    assert is_compiler_ambiguity_policy_pair("frame", "dynamic") is True
    assert supports_signal_free_adaptive_ambiguity_pair("frame", "dynamic") is True


def test_modal_compiler_preserves_packet_000606_compiler_ambiguity_policy_for_evidence_margins(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    cases = (
        {
            "predicted_family": "temporal",
            "target_family": "conditional_normative",
            "expected_margin": -0.310097711398,
        },
        {
            "predicted_family": "deontic",
            "target_family": "frame",
            "expected_margin": -0.572699518562,
        },
        {
            "predicted_family": "temporal",
            "target_family": "deontic",
            "expected_margin": -0.574217822078,
        },
        {
            "predicted_family": "frame",
            "target_family": "alethic",
            "expected_margin": -0.455240440084,
        },
        {
            "predicted_family": "temporal",
            "target_family": "frame",
            "expected_margin": -0.535757207108,
        },
        {
            "predicted_family": "frame",
            "target_family": "frame",
            "expected_margin": 0.123236195005,
        },
        {
            "predicted_family": "frame",
            "target_family": "temporal",
            "expected_margin": -0.041067209039,
        },
        {
            "predicted_family": "frame",
            "target_family": "deontic",
            "expected_margin": -0.833024721921,
        },
        {
            "predicted_family": "temporal",
            "target_family": "deontic",
            "expected_margin": 0.0,
        },
        {
            "predicted_family": "temporal",
            "target_family": "frame",
            "expected_margin": 0.0,
        },
        {
            "predicted_family": "temporal",
            "target_family": "conditional_normative",
            "expected_margin": 0.0,
        },
        {
            "predicted_family": "frame",
            "target_family": "temporal",
            "expected_margin": -0.131176293653,
        },
    )

    for index, case in enumerate(cases, start=1):
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        expected_margin = float(case["expected_margin"])
        if predicted_family == target_family:
            predicted_share = (1.0 + expected_margin) / 2.0
            runner_up_family = "temporal" if predicted_family != "temporal" else "deontic"
            runner_up_share = predicted_share - expected_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 0,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        else:
            predicted_share = 0.9
            target_share = predicted_share + expected_margin
            if target_share < 0.0:
                predicted_share = min(0.99, abs(expected_margin) + 0.05)
                target_share = predicted_share + expected_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": target_family,
                    "count": 0,
                    "share_raw": target_share,
                    "share": target_share,
                },
            ]

        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000606-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} policy evidence.",
            normalized_text=f"Synthetic {predicted_family} policy evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system="LTL" if predicted_family == "temporal" else "D",
                    symbol="F" if predicted_family == "temporal" else "O",
                    label=f"{predicted_family}-label",
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000606-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system="LTL" if predicted_family == "temporal" else "D",
                        symbol="F" if predicted_family == "temporal" else "O",
                        label=f"{predicted_family}-label",
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-000606-adaptive-evidence-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="42 U.S.C. 1983",
                    ),
                ),
            ],
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        margin_direction = "contested" if expected_margin > 0.0 else "outvoted"
        expected_type = (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
        )
        expected_priority = (
            0.15 - expected_margin
            if expected_margin > 0.0
            else abs(expected_margin) + 0.15
        )
        matching = [
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == expected_type
            and ambiguity.metadata.get("adaptive_predicted_family_source")
            == "adaptive_logits"
            and ambiguity.metadata.get("predicted_family") == predicted_family
            and ambiguity.metadata.get("target_family") == target_family
        ]
        assert matching, (predicted_family, target_family, expected_margin)
        ambiguity = matching[0]
        assert ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert ambiguity.metadata["adaptive_margin_direction"] == margin_direction
        assert abs(float(ambiguity.metadata["family_margin_raw"]) - expected_margin) <= 1e-12
        assert abs(float(ambiguity.metadata["priority"]) - expected_priority) <= 1e-12
        assert (
            abs(float(ambiguity.metadata["adaptive_priority"]) - expected_priority)
            <= 1e-12
        )
        if margin_direction == "outvoted":
            assert ambiguity.severity == "requires_rule"
        else:
            assert ambiguity.severity == "review"


def test_modal_compiler_preserves_packet_001809_frame_compiler_ambiguity_policy_for_evidence_margins(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    cases = (
        {
            "predicted_family": "frame",
            "target_family": "deontic",
            "expected_margin": -0.833024721921,
            "sample_id": "us-code-36-190108-ff0dfc16e2f9c817",
        },
        {
            "predicted_family": "frame",
            "target_family": "temporal",
            "expected_margin": -0.392582607602,
            "sample_id": "us-code-22-951-38b335dd92c2b66a",
        },
        {
            "predicted_family": "frame",
            "target_family": "conditional_normative",
            "expected_margin": -0.466401324928,
            "sample_id": "us-code-25-689-561e54f60ffd510c",
        },
    )

    for index, case in enumerate(cases, start=1):
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        expected_margin = float(case["expected_margin"])
        predicted_share = 0.9
        target_share = predicted_share + expected_margin
        if target_share < 0.0:
            predicted_share = min(0.99, abs(expected_margin) + 0.05)
            target_share = predicted_share + expected_margin

        ranking = [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": target_family,
                "count": 0,
                "share_raw": target_share,
                "share": target_share,
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001809-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} policy evidence for {case['sample_id']}.",
            normalized_text=(
                f"Synthetic {predicted_family} policy evidence for {case['sample_id']}."
            ),
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system="FRAME_BM25",
                    symbol="Frame",
                    label=f"{predicted_family}-label",
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-001809-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system="FRAME_BM25",
                        symbol="Frame",
                        label=f"{predicted_family}-label",
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-001809-adaptive-evidence-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="42 U.S.C. 1983",
                    ),
                ),
            ],
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        expected_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        expected_priority = abs(expected_margin) + 0.15
        matching = [
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == expected_type
            and ambiguity.metadata.get("adaptive_predicted_family_source")
            == "adaptive_logits"
            and ambiguity.metadata.get("predicted_family") == predicted_family
            and ambiguity.metadata.get("target_family") == target_family
        ]
        assert matching, (predicted_family, target_family, expected_margin)
        ambiguity = matching[0]
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert abs(float(ambiguity.metadata["family_margin_raw"]) - expected_margin) <= 1e-12
        assert abs(float(ambiguity.metadata["priority"]) - expected_priority) <= 1e-12
        assert (
            abs(float(ambiguity.metadata["adaptive_priority"]) - expected_priority)
            <= 1e-12
        )
        assert ambiguity.metadata["adaptive_policy_pair"] == (
            f"{predicted_family}->{target_family}"
        )


def test_modal_compiler_preserves_packet_003168_compiler_ambiguity_policy_for_evidence_margins(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    cases = (
        {
            "sample_id": "us-code-10-9341-a1ba61f56b6fac7a",
            "predicted_family": "temporal",
            "target_family": "conditional_normative",
            "expected_margin": -0.661683139112,
            "expected_priority": 0.811683139112,
            "expected_system": "LTL",
            "expected_symbol": "F",
        },
        {
            "sample_id": "us-code-18-1992-c530d4994fa34b32",
            "predicted_family": "doxastic",
            "target_family": "epistemic",
            "expected_margin": -0.865659257659,
            "expected_priority": 1.015659257659,
            "expected_system": "KD45",
            "expected_symbol": "B",
        },
        {
            "sample_id": "us-code-20-1098c-af520c0414439cb7",
            "predicted_family": "temporal",
            "target_family": "frame",
            "expected_margin": -0.347073873575,
            "expected_priority": 0.497073873575,
            "expected_system": "LTL",
            "expected_symbol": "F",
        },
    )

    for case in cases:
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        expected_margin = float(case["expected_margin"])
        expected_priority = float(case["expected_priority"])
        predicted_share = min(0.99, abs(expected_margin) + 0.05)
        target_share = max(0.0, predicted_share + expected_margin)
        ranking = [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": target_family,
                "count": 0,
                "share_raw": target_share,
                "share": target_share,
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        sample_id = str(case["sample_id"])
        encoding = SpaCyLegalEncoding(
            document_id=sample_id,
            text=f"Synthetic {predicted_family} policy evidence.",
            normalized_text=f"Synthetic {predicted_family} policy evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(case["expected_system"]),
                    symbol=str(case["expected_symbol"]),
                    label=f"{predicted_family}-label",
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=sample_id,
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{sample_id}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(case["expected_system"]),
                        symbol=str(case["expected_symbol"]),
                        label=f"{predicted_family}-label",
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="42 U.S.C. 1983",
                    ),
                ),
            ],
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        expected_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        matching = [
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == expected_type
            and ambiguity.metadata.get("adaptive_predicted_family_source")
            == "adaptive_logits"
            and ambiguity.metadata.get("predicted_family") == predicted_family
            and ambiguity.metadata.get("target_family") == target_family
        ]
        assert matching, (sample_id, predicted_family, target_family, expected_margin)
        ambiguity = matching[0]
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert abs(float(ambiguity.metadata["family_margin_raw"]) - expected_margin) <= 1e-12
        assert abs(float(ambiguity.metadata["priority"]) - expected_priority) <= 1e-12
        assert (
            abs(float(ambiguity.metadata["adaptive_priority"]) - expected_priority)
            <= 1e-12
        )
        assert ambiguity.metadata["adaptive_policy_pair"] == (
            f"{predicted_family}->{target_family}"
        )


def test_modal_compiler_normalizes_dot_value_compiler_ambiguity_targets(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.priority_signal_free_adaptive_ambiguity_targets",
        lambda _: (),
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.compiler_required_adaptive_ambiguity_targets",
        lambda _: (),
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.compiler_ambiguity_policy_targets",
        lambda _: ("ModalLogicFamily.TEMPORAL.value",),
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.signal_free_adaptive_ambiguity_targets",
        lambda _: (),
    )
    assert compiler._ordered_policy_target_families("frame") == ["temporal"]

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-dot-value-policy-targets-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-dot-value-policy-targets-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-dot-value-policy-targets-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="5 U.S.C. 552",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "frame", "count": 1, "share": 1.0}],
        family_shares={"frame": 1.0},
    )

    adaptive_temporal = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "temporal"]
    )
    assert adaptive_temporal.metadata["adaptive_policy_pair"] == "frame->temporal"
    assert adaptive_temporal.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_temporal.metadata["explicit_ambiguity_type"] == (
        "adaptive_frame_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_temporal_outvoted_margin_low"
        and ambiguity.metadata["adaptive_policy_pair"] == "frame->temporal"
        for ambiguity in ambiguities
    )


def test_modal_compiler_normalizes_directional_compiler_ambiguity_targets(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.priority_signal_free_adaptive_ambiguity_targets",
        lambda _: (),
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.compiler_required_adaptive_ambiguity_targets",
        lambda _: (),
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.compiler_ambiguity_policy_targets",
        lambda _: ("frame->temporal",),
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.signal_free_adaptive_ambiguity_targets",
        lambda _: (),
    )
    assert compiler._ordered_policy_target_families("frame") == ["temporal"]

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-directional-policy-targets-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-directional-policy-targets-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-directional-policy-targets-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="5 U.S.C. 552",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "frame", "count": 1, "share": 1.0}],
        family_shares={"frame": 1.0},
    )

    adaptive_temporal = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "temporal"]
    )
    assert adaptive_temporal.metadata["adaptive_policy_pair"] == "frame->temporal"
    assert adaptive_temporal.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_temporal.metadata["explicit_ambiguity_type"] == (
        "adaptive_frame_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_temporal_outvoted_margin_low"
        and ambiguity.metadata["adaptive_policy_pair"] == "frame->temporal"
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_alethic_scope_as_temporal_adaptive_target_signal(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {
            "has_alethic_cue": False,
            "has_alethic_scope": True,
        },
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-scope-temporal-alethic-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-scope-temporal-alethic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-scope-temporal-alethic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="10 U.S.C. 4901",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "temporal", "count": 1, "share": 1.0}],
        family_shares={"temporal": 1.0},
    )

    adaptive_alethic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "alethic"]
    )
    assert adaptive_alethic.metadata["has_target_signal_evidence"] is True
    assert adaptive_alethic.metadata["signal_free_pair_policy_applied"] is False
    assert adaptive_alethic.metadata["lexical_signals"]["has_alethic_scope"] is True
    assert (
        adaptive_alethic.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_alethic_outvoted_margin_low"
    )


def test_modal_compiler_surfaces_compiled_primary_deontic_conditional_policy_ambiguity_when_cues_predict_temporal(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-compiled-primary-deontic-conditional-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-compiled-primary-deontic-conditional-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-compiled-primary-deontic-conditional-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="20 U.S.C. 7261",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "temporal", "count": 1, "share": 1.0}],
        family_shares={"temporal": 1.0},
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["adaptive_predicted_family_source"] == (
        "compiled_primary_family"
    )
    assert adaptive_conditional.metadata["predicted_family"] == "deontic"
    assert adaptive_conditional.metadata["target_family"] == "conditional_normative"
    assert adaptive_conditional.metadata["has_target_signal_evidence"] is False
    assert adaptive_conditional.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_conditional.metadata["family_margin"] == 0.0
    assert adaptive_conditional.metadata["adaptive_margin_direction"] == "outvoted"
    assert (
        adaptive_conditional.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_conditional_normative_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_deontic_conditional_normative_outvoted_margin_low"
        and ambiguity.metadata["adaptive_predicted_family_source"]
        == "compiled_primary_family"
        for ambiguity in ambiguities
    )


def test_modal_compiler_surfaces_compiled_primary_deontic_self_pair_adaptive_ambiguity_when_ranking_prefers_temporal(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-compiled-primary-deontic-self-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-compiled-primary-deontic-self-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-compiled-primary-deontic-self-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="20 U.S.C. 7261",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "temporal", "count": 2, "share": 0.55},
            {"family": "deontic", "count": 2, "share": 0.45},
        ],
        family_shares={"temporal": 0.55, "deontic": 0.45},
    )

    adaptive_deontic_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic"]
    )
    assert adaptive_deontic_self.metadata["adaptive_predicted_family_source"] == (
        "compiled_primary_family"
    )
    assert adaptive_deontic_self.metadata["predicted_family"] == "deontic"
    assert adaptive_deontic_self.metadata["target_family"] == "deontic"
    assert adaptive_deontic_self.metadata["runner_up_family"] == "temporal"
    assert adaptive_deontic_self.metadata["is_self_pair"] is True
    assert adaptive_deontic_self.metadata["family_margin"] == -0.1
    assert adaptive_deontic_self.metadata["predicted_margin_to_runner_up"] == -0.1
    assert adaptive_deontic_self.metadata["adaptive_margin_direction"] == "outvoted"
    assert (
        adaptive_deontic_self.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_deontic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_deontic_outvoted_margin_low"
        and ambiguity.metadata["adaptive_predicted_family_source"]
        == "compiled_primary_family"
        and ambiguity.metadata["is_self_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_runner_up_priority_pair_for_compiled_primary_self_pair_zero_margin(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "doc_id": "adaptive-compiled-primary-frame-self-vs-deontic-doc",
            "compiled_primary_family": "frame",
            "compiled_primary_system": "FRAME_BM25",
            "compiled_primary_symbol": "Frame",
            "compiled_primary_label": "frame",
            "compiled_primary_role": "frame_scope",
            "compiled_primary_predicate": "editorial_transfer",
            "runner_up_family": "deontic",
            "runner_up_cue": SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
            "expected_explicit_type": "adaptive_frame_frame_outvoted_margin_low",
            "citation": "22 U.S.C. 283k",
        },
        {
            "doc_id": "adaptive-compiled-primary-frame-self-vs-conditional-doc",
            "compiled_primary_family": "frame",
            "compiled_primary_system": "FRAME_BM25",
            "compiled_primary_symbol": "Frame",
            "compiled_primary_label": "frame",
            "compiled_primary_role": "frame_scope",
            "compiled_primary_predicate": "editorial_transfer",
            "runner_up_family": "conditional_normative",
            "runner_up_cue": SpaCyModalCueFeature(
                family="conditional_normative",
                system="STIT",
                symbol="O_if",
                label="conditional_obligation",
                cue="provided that",
                start_char=0,
                end_char=13,
                token_indices=[],
            ),
            "expected_explicit_type": "adaptive_frame_frame_outvoted_margin_low",
            "citation": "20 U.S.C. 7351d",
        },
        {
            "doc_id": "adaptive-compiled-primary-temporal-self-vs-deontic-doc",
            "compiled_primary_family": "temporal",
            "compiled_primary_system": "LTL",
            "compiled_primary_symbol": "F",
            "compiled_primary_label": "eventually",
            "compiled_primary_role": "temporal_scope",
            "compiled_primary_predicate": "deadline_applies",
            "runner_up_family": "deontic",
            "runner_up_cue": SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
            "expected_explicit_type": "adaptive_temporal_temporal_outvoted_margin_low",
            "citation": "18 U.S.C. 607",
        },
        {
            "doc_id": "adaptive-compiled-primary-conditional-self-vs-deontic-doc",
            "compiled_primary_family": "conditional_normative",
            "compiled_primary_system": "STIT",
            "compiled_primary_symbol": "O_if",
            "compiled_primary_label": "conditional_obligation",
            "compiled_primary_role": "conditional_scope",
            "compiled_primary_predicate": "conditional_notice_obligation",
            "runner_up_family": "deontic",
            "runner_up_cue": SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
            "expected_explicit_type": "adaptive_conditional_normative_conditional_normative_outvoted_margin_low",
            "citation": "42 U.S.C. 300aa-22",
        },
    )

    for scenario in scenarios:
        encoding = SpaCyLegalEncoding(
            document_id=str(scenario["doc_id"]),
            text="Provided that the agency shall provide written notice.",
            normalized_text="Provided that the agency shall provide written notice.",
            tokens=[],
            sentences=[],
            cues=[scenario["runner_up_cue"]],
        )
        modal_ir = ModalIRDocument(
            document_id=str(scenario["doc_id"]),
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{scenario['compiled_primary_family']}-1",
                    operator=ModalIROperator(
                        family=str(scenario["compiled_primary_family"]),
                        system=str(scenario["compiled_primary_system"]),
                        symbol=str(scenario["compiled_primary_symbol"]),
                        label=str(scenario["compiled_primary_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=str(scenario["compiled_primary_predicate"]),
                        arguments=["actor:agency"],
                        role=str(scenario["compiled_primary_role"]),
                    ),
                    provenance=ModalIRProvenance(
                        source_id=str(scenario["doc_id"]),
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation=str(scenario["citation"]),
                    ),
                ),
            ],
        )
        ranking = [
            {"family": str(scenario["runner_up_family"]), "count": 1, "share": 0.5},
            {
                "family": str(scenario["compiled_primary_family"]),
                "count": 1,
                "share": 0.5,
            },
        ]
        family_shares = {
            str(scenario["runner_up_family"]): 0.5,
            str(scenario["compiled_primary_family"]): 0.5,
        }

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
        )
        compiled_primary_self = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [str(scenario["compiled_primary_family"])]
            and ambiguity.metadata["adaptive_predicted_family_source"]
            == "compiled_primary_family"
        )
        assert compiled_primary_self.metadata["family_margin"] == 0.0
        assert compiled_primary_self.metadata["runner_up_family"] == str(
            scenario["runner_up_family"]
        )
        assert compiled_primary_self.metadata["adaptive_policy_pair"] == (
            f"{scenario['compiled_primary_family']}->{scenario['compiled_primary_family']}"
        )
        assert compiled_primary_self.metadata["adaptive_runner_up_policy_pair"] == (
            f"{scenario['compiled_primary_family']}->{scenario['runner_up_family']}"
        )
        assert (
            compiled_primary_self.metadata["runner_up_is_compiler_ambiguity_bundle_pair"]
            is True
        )
        assert (
            compiled_primary_self.metadata["effective_compiler_ambiguity_policy_pair"]
            == f"{scenario['compiled_primary_family']}->{scenario['runner_up_family']}"
        )
        assert (
            compiled_primary_self.metadata["effective_ambiguity_policy_bundle"]
            == "compiler_ambiguity"
        )
        assert compiled_primary_self.metadata["runner_up_is_priority_policy_pair"] is True
        assert compiled_primary_self.metadata["is_priority_policy_pair"] is True
        assert compiled_primary_self.metadata["adaptive_margin_direction"] == "outvoted"
        assert (
            compiled_primary_self.metadata["explicit_ambiguity_type"]
            == scenario["expected_explicit_type"]
        )
        assert compiled_primary_self.severity == "requires_rule"
        assert any(
            ambiguity.ambiguity_type == scenario["expected_explicit_type"]
            and ambiguity.metadata["adaptive_predicted_family_source"]
            == "compiled_primary_family"
            and ambiguity.metadata["adaptive_runner_up_policy_pair"]
            == f"{scenario['compiled_primary_family']}->{scenario['runner_up_family']}"
            and ambiguity.metadata["runner_up_is_priority_policy_pair"] is True
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_compiled_primary_deontic_alethic_adaptive_ambiguity_from_signal_targets(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {
            "has_alethic_cue": True,
            "has_alethic_scope": True,
        },
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-compiled-primary-deontic-alethic-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-compiled-primary-deontic-alethic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-compiled-primary-deontic-alethic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="20 U.S.C. 7261",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "temporal", "count": 1, "share": 1.0}],
        family_shares={"temporal": 1.0},
    )

    adaptive_alethic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "alethic"]
    )
    assert adaptive_alethic.metadata["adaptive_predicted_family_source"] == (
        "compiled_primary_family"
    )
    assert adaptive_alethic.metadata["predicted_family"] == "deontic"
    assert adaptive_alethic.metadata["target_family"] == "alethic"
    assert adaptive_alethic.metadata["has_target_signal_evidence"] is True
    assert adaptive_alethic.metadata["signal_free_pair_policy_applied"] is False
    assert adaptive_alethic.metadata["family_margin"] == 0.0
    assert adaptive_alethic.metadata["adaptive_margin_direction"] == "contested"
    assert (
        adaptive_alethic.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_alethic_contested_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_alethic_contested_margin_low"
        and ambiguity.metadata["adaptive_predicted_family_source"]
        == "compiled_primary_family"
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_temporal_conditional_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-temporal-conditional-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-temporal-conditional-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-temporal-conditional-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 607",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "temporal", "count": 1, "share": 1.0}],
        family_shares={"temporal": 1.0},
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["has_target_signal_evidence"] is False
    assert adaptive_conditional.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_conditional.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_conditional.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_conditional.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_conditional_normative_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_temporal_conditional_normative_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_temporal_conditional_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-temporal-conditional-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-temporal-conditional-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-temporal-conditional-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 607",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "temporal", "count": 1, "share": 0.5},
            {"family": "conditional_normative", "count": 1, "share": 0.5},
        ],
        family_shares={"temporal": 0.5, "conditional_normative": 0.5},
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["family_margin"] == 0.0
    assert adaptive_conditional.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_conditional.metadata["is_priority_policy_pair"] is True
    assert adaptive_conditional.metadata["adaptive_priority"] == 0.15
    assert adaptive_conditional.metadata["explicit_ambiguity_type"] == (
        "adaptive_temporal_conditional_normative_outvoted_margin_low"
    )
    assert adaptive_conditional.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_temporal_conditional_normative_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_temporal_frame_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-temporal-frame-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-temporal-frame-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-temporal-frame-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 607",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "temporal", "count": 1, "share": 1.0}],
        family_shares={"temporal": 1.0},
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "frame"]
    )
    assert adaptive_frame.metadata["has_target_signal_evidence"] is False
    assert adaptive_frame.metadata["signal_free_pair_policy_applied"] is True
    assert (
        adaptive_frame.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_frame_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_frame_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_temporal_epistemic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-temporal-epistemic-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-temporal-epistemic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-temporal-epistemic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 607",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "temporal", "count": 1, "share": 1.0}],
        family_shares={"temporal": 1.0},
    )

    adaptive_epistemic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "epistemic"]
    )
    assert adaptive_epistemic.metadata["has_target_signal_evidence"] is False
    assert adaptive_epistemic.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_epistemic.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_epistemic.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_epistemic.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_epistemic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_epistemic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        and ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_temporal_dynamic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-temporal-dynamic-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-temporal-dynamic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-temporal-dynamic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 607",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "temporal", "count": 1, "share": 1.0}],
        family_shares={"temporal": 1.0},
    )

    adaptive_dynamic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "dynamic"]
    )
    assert adaptive_dynamic.metadata["has_target_signal_evidence"] is False
    assert adaptive_dynamic.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_dynamic.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_dynamic.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_dynamic.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_dynamic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_dynamic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        and ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-temporal-frame-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-temporal-frame-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-temporal-frame-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="25 U.S.C. 171",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "temporal", "count": 1, "share": 0.5},
            {"family": "frame", "count": 1, "share": 0.5},
        ],
        family_shares={"temporal": 0.5, "frame": 0.5},
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "frame"]
    )
    assert adaptive_frame.metadata["family_margin"] == 0.0
    assert adaptive_frame.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_frame.metadata["is_priority_policy_pair"] is True
    assert adaptive_frame.metadata["adaptive_policy_pair"] == "temporal->frame"
    assert adaptive_frame.metadata["adaptive_priority"] == 0.15
    assert adaptive_frame.metadata["priority"] == 0.15
    assert adaptive_frame.metadata["explicit_ambiguity_type"] == (
        "adaptive_temporal_frame_outvoted_margin_low"
    )
    assert adaptive_frame.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_frame_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_hybrid_frame_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-hybrid-frame-doc",
        text="Composite interpretation applies.",
        normalized_text="Composite interpretation applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="hybrid",
                system="HYBRID",
                symbol="H",
                label="hybrid",
                cue="composite",
                start_char=0,
                end_char=9,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-hybrid-frame-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-hybrid-1",
                operator=ModalIROperator(
                    family="hybrid",
                    system="HYBRID",
                    symbol="H",
                    label="hybrid",
                ),
                predicate=ModalIRPredicate(
                    name="composite_interpretation",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-hybrid-frame-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="2 U.S.C. 60e-3",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "hybrid", "count": 1, "share": 0.5},
            {"family": "frame", "count": 1, "share": 0.5},
        ],
        family_shares={"hybrid": 0.5, "frame": 0.5},
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["hybrid", "frame"]
    )
    assert adaptive_frame.metadata["family_margin"] == 0.0
    assert adaptive_frame.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_frame.metadata["is_priority_policy_pair"] is True
    assert adaptive_frame.metadata["explicit_ambiguity_type"] == (
        "adaptive_hybrid_frame_outvoted_margin_low"
    )
    assert adaptive_frame.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_hybrid_frame_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_hybrid_frame_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-hybrid-frame-doc",
        text="Composite interpretation applies.",
        normalized_text="Composite interpretation applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="hybrid",
                system="HYBRID",
                symbol="H",
                label="hybrid",
                cue="composite",
                start_char=0,
                end_char=9,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-hybrid-frame-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-hybrid-1",
                operator=ModalIROperator(
                    family="hybrid",
                    system="HYBRID",
                    symbol="H",
                    label="hybrid",
                ),
                predicate=ModalIRPredicate(
                    name="composite_interpretation",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-hybrid-frame-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="43 U.S.C. 1501",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "hybrid", "count": 1, "share": 1.0}],
        family_shares={"hybrid": 1.0},
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["hybrid", "frame"]
    )
    assert adaptive_frame.metadata["has_target_signal_evidence"] is False
    assert adaptive_frame.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_frame.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_frame.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_frame.metadata["explicit_ambiguity_type"]
        == "adaptive_hybrid_frame_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_hybrid_frame_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        and ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_frame_deontic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-frame-deontic-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-frame-deontic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-frame-deontic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="42 U.S.C. 1395w",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "frame", "count": 1, "share": 1.0}],
        family_shares={"frame": 1.0},
    )

    adaptive_deontic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "deontic"]
    )
    assert adaptive_deontic.metadata["has_target_signal_evidence"] is False
    assert adaptive_deontic.metadata["signal_free_pair_policy_applied"] is True
    assert (
        adaptive_deontic.metadata["explicit_ambiguity_type"]
        == "adaptive_frame_deontic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_deontic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_frame_deontic_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-frame-deontic-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-frame-deontic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-frame-deontic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="5 U.S.C. 552",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "frame", "count": 1, "share": 0.5},
            {"family": "deontic", "count": 1, "share": 0.5},
        ],
        family_shares={"frame": 0.5, "deontic": 0.5},
    )

    adaptive_deontic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "deontic"]
    )
    assert adaptive_deontic.metadata["family_margin"] == 0.0
    assert adaptive_deontic.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_deontic.metadata["is_priority_policy_pair"] is True
    assert adaptive_deontic.metadata["explicit_ambiguity_type"] == (
        "adaptive_frame_deontic_outvoted_margin_low"
    )
    assert adaptive_deontic.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_deontic_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_frame_conditional_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-frame-conditional-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-frame-conditional-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-frame-conditional-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="33 U.S.C. 3853",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "frame", "count": 1, "share": 1.0}],
        family_shares={"frame": 1.0},
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["has_target_signal_evidence"] is False
    assert adaptive_conditional.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_conditional.metadata["adaptive_policy_pair"] == (
        "frame->conditional_normative"
    )
    assert (
        adaptive_conditional.metadata["explicit_ambiguity_type"]
        == "adaptive_frame_conditional_normative_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_frame_conditional_normative_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_frame_conditional_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-frame-conditional-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-frame-conditional-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-frame-conditional-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="20 U.S.C. 7351d",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "frame", "count": 1, "share": 0.5},
            {"family": "conditional_normative", "count": 1, "share": 0.5},
        ],
        family_shares={"frame": 0.5, "conditional_normative": 0.5},
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["family_margin"] == 0.0
    assert adaptive_conditional.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_conditional.metadata["is_priority_policy_pair"] is True
    assert adaptive_conditional.metadata["explicit_ambiguity_type"] == (
        "adaptive_frame_conditional_normative_outvoted_margin_low"
    )
    assert adaptive_conditional.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_frame_conditional_normative_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_frame_temporal_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-frame-temporal-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-frame-temporal-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-frame-temporal-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="7 U.S.C. 136c",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "frame", "count": 1, "share": 1.0}],
        family_shares={"frame": 1.0},
    )

    adaptive_temporal = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "temporal"]
    )
    assert adaptive_temporal.metadata["has_target_signal_evidence"] is False
    assert adaptive_temporal.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_temporal.metadata["is_priority_policy_pair"] is True
    assert adaptive_temporal.metadata["adaptive_policy_pair"] == "frame->temporal"
    assert (
        adaptive_temporal.metadata["explicit_ambiguity_type"]
        == "adaptive_frame_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_temporal_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_frame_dynamic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-frame-dynamic-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-frame-dynamic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-frame-dynamic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="11 U.S.C. 1025",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "frame", "count": 1, "share": 1.0}],
        family_shares={"frame": 1.0},
    )

    adaptive_dynamic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "dynamic"]
    )
    assert adaptive_dynamic.metadata["has_target_signal_evidence"] is False
    assert adaptive_dynamic.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_dynamic.metadata["is_priority_policy_pair"] is False
    assert adaptive_dynamic.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_dynamic.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_dynamic.metadata["explicit_ambiguity_type"]
        == "adaptive_frame_dynamic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_dynamic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_emits_explicit_frame_policy_pair_ambiguities_for_evidence_margins(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-evidence-frame-policy-pairs-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-evidence-frame-policy-pairs-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-evidence-frame-policy-pairs-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="43 U.S.C. 156",
                ),
            ),
        ],
    )

    temporal_ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {
                "family": "frame",
                "count": 1,
                "share_raw": 0.563068740844,
                "share": 0.563069,
            },
            {
                "family": "temporal",
                "count": 1,
                "share_raw": 0.15,
                "share": 0.15,
            },
        ],
        family_shares={"frame": 0.563068740844, "temporal": 0.15},
    )
    adaptive_temporal = next(
        ambiguity
        for ambiguity in temporal_ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "temporal"]
    )
    assert adaptive_temporal.metadata["adaptive_policy_pair"] == "frame->temporal"
    assert adaptive_temporal.metadata["family_margin"] == -0.413069
    assert abs(adaptive_temporal.metadata["family_margin_raw"] + 0.413068740844) < 1e-12
    assert adaptive_temporal.metadata["explicit_ambiguity_type"] == (
        "adaptive_frame_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_temporal_outvoted_margin_low"
        and ambiguity.metadata["adaptive_policy_pair"] == "frame->temporal"
        for ambiguity in temporal_ambiguities
    )

    conditional_ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {
                "family": "frame",
                "count": 1,
                "share_raw": 0.735177285536,
                "share": 0.735177,
            },
        ],
        family_shares={"frame": 0.735177285536},
    )
    adaptive_conditional = next(
        ambiguity
        for ambiguity in conditional_ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["adaptive_policy_pair"] == (
        "frame->conditional_normative"
    )
    assert adaptive_conditional.metadata["family_margin"] == -0.735177
    assert abs(
        adaptive_conditional.metadata["family_margin_raw"] + 0.735177285536
    ) < 1e-12
    assert adaptive_conditional.metadata["explicit_ambiguity_type"] == (
        "adaptive_frame_conditional_normative_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_frame_conditional_normative_outvoted_margin_low"
        and ambiguity.metadata["adaptive_policy_pair"]
        == "frame->conditional_normative"
        for ambiguity in conditional_ambiguities
    )


def test_modal_compiler_treats_zero_margin_frame_temporal_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-frame-temporal-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-frame-temporal-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-frame-temporal-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="5 U.S.C. 552",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "frame", "count": 1, "share": 0.5},
            {"family": "temporal", "count": 1, "share": 0.5},
        ],
        family_shares={"frame": 0.5, "temporal": 0.5},
    )

    adaptive_temporal = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "temporal"]
    )
    assert adaptive_temporal.metadata["family_margin"] == 0.0
    assert adaptive_temporal.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_temporal.metadata["is_priority_policy_pair"] is True
    assert adaptive_temporal.metadata["explicit_ambiguity_type"] == (
        "adaptive_frame_temporal_outvoted_margin_low"
    )
    assert adaptive_temporal.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_temporal_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_conditional_temporal_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-conditional-temporal-doc",
        text="Provided that the filing is complete, notice applies.",
        normalized_text="Provided that the filing is complete, notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="conditional_normative",
                system="STIT",
                symbol="O_if",
                label="conditional_obligation",
                cue="provided that",
                start_char=0,
                end_char=13,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-conditional-temporal-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-conditional-1",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="STIT",
                    symbol="O_if",
                    label="conditional_obligation",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="conditional_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-conditional-temporal-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="11 U.S.C. 547",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "conditional_normative", "count": 1, "share": 1.0}],
        family_shares={"conditional_normative": 1.0},
    )

    adaptive_temporal = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative", "temporal"]
    )
    assert adaptive_temporal.metadata["has_target_signal_evidence"] is False
    assert adaptive_temporal.metadata["signal_free_pair_policy_applied"] is True
    assert (
        adaptive_temporal.metadata["explicit_ambiguity_type"]
        == "adaptive_conditional_normative_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_conditional_normative_temporal_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_temporal_signal_for_conditional_temporal_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {
            "has_temporal_scope": True,
        },
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signaled-conditional-temporal-doc",
        text="Provided that the filing is complete, notice applies.",
        normalized_text="Provided that the filing is complete, notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="conditional_normative",
                system="STIT",
                symbol="O_if",
                label="conditional_obligation",
                cue="provided that",
                start_char=0,
                end_char=13,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signaled-conditional-temporal-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-conditional-1",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="STIT",
                    symbol="O_if",
                    label="conditional_obligation",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="conditional_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signaled-conditional-temporal-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="11 U.S.C. 547",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "conditional_normative", "count": 1, "share": 1.0}],
        family_shares={"conditional_normative": 1.0},
    )

    adaptive_temporal = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative", "temporal"]
    )
    assert adaptive_temporal.metadata["has_target_signal_evidence"] is True
    assert adaptive_temporal.metadata["signal_free_pair_policy_applied"] is False
    assert adaptive_temporal.metadata["lexical_signals"]["has_temporal_scope"] is True
    assert (
        adaptive_temporal.metadata["explicit_ambiguity_type"]
        == "adaptive_conditional_normative_temporal_outvoted_margin_low"
    )


def test_modal_compiler_treats_zero_margin_conditional_temporal_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-conditional-temporal-doc",
        text="Provided that the filing is complete, notice applies.",
        normalized_text="Provided that the filing is complete, notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="conditional_normative",
                system="STIT",
                symbol="O_if",
                label="conditional_obligation",
                cue="provided that",
                start_char=0,
                end_char=13,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-conditional-temporal-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-conditional-1",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="STIT",
                    symbol="O_if",
                    label="conditional_obligation",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="conditional_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-conditional-temporal-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="11 U.S.C. 547",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "conditional_normative", "count": 1, "share": 0.5},
            {"family": "temporal", "count": 1, "share": 0.5},
        ],
        family_shares={"conditional_normative": 0.5, "temporal": 0.5},
    )

    adaptive_temporal = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative", "temporal"]
    )
    assert adaptive_temporal.metadata["family_margin"] == 0.0
    assert adaptive_temporal.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_temporal.metadata["is_priority_policy_pair"] is True
    assert adaptive_temporal.metadata["explicit_ambiguity_type"] == (
        "adaptive_conditional_normative_temporal_outvoted_margin_low"
    )
    assert adaptive_temporal.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_conditional_normative_temporal_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_temporal_conditional_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-temporal-conditional-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-temporal-conditional-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-temporal-conditional-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 607",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "temporal", "count": 1, "share": 0.5},
            {"family": "conditional_normative", "count": 1, "share": 0.5},
        ],
        family_shares={"temporal": 0.5, "conditional_normative": 0.5},
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["family_margin"] == 0.0
    assert adaptive_conditional.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_conditional.metadata["is_priority_policy_pair"] is True
    assert adaptive_conditional.metadata["explicit_ambiguity_type"] == (
        "adaptive_temporal_conditional_normative_outvoted_margin_low"
    )
    assert adaptive_conditional.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_temporal_conditional_normative_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_conditional_deontic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-conditional-deontic-doc",
        text="Provided that the filing is complete, notice applies.",
        normalized_text="Provided that the filing is complete, notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="conditional_normative",
                system="STIT",
                symbol="O_if",
                label="conditional_obligation",
                cue="provided that",
                start_char=0,
                end_char=13,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-conditional-deontic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-conditional-1",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="STIT",
                    symbol="O_if",
                    label="conditional_obligation",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="conditional_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-conditional-deontic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="11 U.S.C. 547",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "conditional_normative", "count": 1, "share": 1.0}],
        family_shares={"conditional_normative": 1.0},
    )

    adaptive_deontic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative", "deontic"]
    )
    assert adaptive_deontic.metadata["has_target_signal_evidence"] is False
    assert adaptive_deontic.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_deontic.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_deontic.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_deontic.metadata["explicit_ambiguity_type"]
        == "adaptive_conditional_normative_deontic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_conditional_normative_deontic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_conditional_frame_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-conditional-frame-doc",
        text="Provided that the filing is complete, notice applies.",
        normalized_text="Provided that the filing is complete, notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="conditional_normative",
                system="STIT",
                symbol="O_if",
                label="conditional_obligation",
                cue="provided that",
                start_char=0,
                end_char=13,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-conditional-frame-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-conditional-1",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="STIT",
                    symbol="O_if",
                    label="conditional_obligation",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="conditional_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-conditional-frame-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="11 U.S.C. 547",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "conditional_normative", "count": 1, "share": 1.0}],
        family_shares={"conditional_normative": 1.0},
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative", "frame"]
    )
    assert adaptive_frame.metadata["has_target_signal_evidence"] is False
    assert adaptive_frame.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_frame.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_frame.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_frame.metadata["explicit_ambiguity_type"]
        == "adaptive_conditional_normative_frame_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_conditional_normative_frame_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_frame_signal_for_conditional_frame_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {
            "has_frame_context": True,
        },
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signaled-conditional-frame-doc",
        text="Provided that the filing is complete, notice applies.",
        normalized_text="Provided that the filing is complete, notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="conditional_normative",
                system="STIT",
                symbol="O_if",
                label="conditional_obligation",
                cue="provided that",
                start_char=0,
                end_char=13,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signaled-conditional-frame-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-conditional-1",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="STIT",
                    symbol="O_if",
                    label="conditional_obligation",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="conditional_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signaled-conditional-frame-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="11 U.S.C. 547",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "conditional_normative", "count": 1, "share": 1.0}],
        family_shares={"conditional_normative": 1.0},
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative", "frame"]
    )
    assert adaptive_frame.metadata["has_target_signal_evidence"] is True
    assert adaptive_frame.metadata["signal_free_pair_policy_applied"] is False
    assert adaptive_frame.metadata["lexical_signals"]["has_frame_context"] is True
    assert (
        adaptive_frame.metadata["explicit_ambiguity_type"]
        == "adaptive_conditional_normative_frame_outvoted_margin_low"
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_conditional_epistemic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-conditional-epistemic-doc",
        text="Provided that the filing is complete, notice applies.",
        normalized_text="Provided that the filing is complete, notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="conditional_normative",
                system="STIT",
                symbol="O_if",
                label="conditional_obligation",
                cue="provided that",
                start_char=0,
                end_char=13,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-conditional-epistemic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-conditional-1",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="STIT",
                    symbol="O_if",
                    label="conditional_obligation",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="conditional_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-conditional-epistemic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="11 U.S.C. 547",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "conditional_normative", "count": 1, "share": 1.0}],
        family_shares={"conditional_normative": 1.0},
    )

    adaptive_epistemic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative", "epistemic"]
    )
    assert adaptive_epistemic.metadata["has_target_signal_evidence"] is False
    assert adaptive_epistemic.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_epistemic.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_epistemic.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_epistemic.metadata["explicit_ambiguity_type"]
        == "adaptive_conditional_normative_epistemic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_conditional_normative_epistemic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        and ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_conditional_dynamic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-conditional-dynamic-doc",
        text="Provided that the filing is complete, notice applies.",
        normalized_text="Provided that the filing is complete, notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="conditional_normative",
                system="STIT",
                symbol="O_if",
                label="conditional_obligation",
                cue="provided that",
                start_char=0,
                end_char=13,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-conditional-dynamic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-conditional-1",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="STIT",
                    symbol="O_if",
                    label="conditional_obligation",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="conditional_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-conditional-dynamic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="11 U.S.C. 547",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "conditional_normative", "count": 1, "share": 1.0}],
        family_shares={"conditional_normative": 1.0},
    )

    adaptive_dynamic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative", "dynamic"]
    )
    assert adaptive_dynamic.metadata["has_target_signal_evidence"] is False
    assert adaptive_dynamic.metadata["signal_free_pair_policy_applied"] is True
    assert (
        adaptive_dynamic.metadata["explicit_ambiguity_type"]
        == "adaptive_conditional_normative_dynamic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_conditional_normative_dynamic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_dynamic_signal_for_conditional_dynamic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {
            "has_dynamic_scope": True,
        },
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signaled-conditional-dynamic-doc",
        text="Provided that the filing is complete, notice applies.",
        normalized_text="Provided that the filing is complete, notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="conditional_normative",
                system="STIT",
                symbol="O_if",
                label="conditional_obligation",
                cue="provided that",
                start_char=0,
                end_char=13,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signaled-conditional-dynamic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-conditional-1",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="STIT",
                    symbol="O_if",
                    label="conditional_obligation",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="conditional_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signaled-conditional-dynamic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="11 U.S.C. 547",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "conditional_normative", "count": 1, "share": 1.0}],
        family_shares={"conditional_normative": 1.0},
    )

    adaptive_dynamic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative", "dynamic"]
    )
    assert adaptive_dynamic.metadata["has_target_signal_evidence"] is True
    assert adaptive_dynamic.metadata["signal_free_pair_policy_applied"] is False
    assert (
        adaptive_dynamic.metadata["explicit_ambiguity_type"]
        == "adaptive_conditional_normative_dynamic_outvoted_margin_low"
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_frame_epistemic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-frame-epistemic-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-frame-epistemic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-frame-epistemic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="7 U.S.C. 136c",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "frame", "count": 1, "share": 1.0}],
        family_shares={"frame": 1.0},
    )

    adaptive_epistemic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "epistemic"]
    )
    assert adaptive_epistemic.metadata["has_target_signal_evidence"] is False
    assert adaptive_epistemic.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_epistemic.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_epistemic.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_epistemic.metadata["explicit_ambiguity_type"]
        == "adaptive_frame_epistemic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_epistemic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        and ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_epistemic_signal_for_frame_epistemic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {
            "has_epistemic_cue": True,
        },
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signaled-frame-epistemic-doc",
        text="Authority finds.",
        normalized_text="Authority finds.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="authority",
                start_char=0,
                end_char=9,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signaled-frame-epistemic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="authority_findings",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signaled-frame-epistemic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="20 U.S.C. 80e",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "frame", "count": 1, "share": 1.0}],
        family_shares={"frame": 1.0},
    )

    adaptive_epistemic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "epistemic"]
    )
    assert adaptive_epistemic.metadata["has_target_signal_evidence"] is True
    assert adaptive_epistemic.metadata["signal_free_pair_policy_applied"] is False
    assert adaptive_epistemic.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_epistemic.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_epistemic.metadata["explicit_ambiguity_type"]
        == "adaptive_frame_epistemic_outvoted_margin_low"
    )


def test_modal_compiler_treats_zero_margin_frame_epistemic_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-frame-epistemic-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-frame-epistemic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-frame-epistemic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="5 U.S.C. 552",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "frame", "count": 1, "share": 0.5},
            {"family": "epistemic", "count": 1, "share": 0.5},
        ],
        family_shares={"frame": 0.5, "epistemic": 0.5},
    )

    adaptive_epistemic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "epistemic"]
    )
    assert adaptive_epistemic.metadata["family_margin"] == 0.0
    assert adaptive_epistemic.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_epistemic.metadata["is_priority_policy_pair"] is True
    assert adaptive_epistemic.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_epistemic.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert adaptive_epistemic.metadata["explicit_ambiguity_type"] == (
        "adaptive_frame_epistemic_outvoted_margin_low"
    )
    assert adaptive_epistemic.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_epistemic_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_emits_explicit_frame_bundle_ambiguities_for_autoencoder_margins(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-frame-margin-bundle-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-frame-margin-bundle-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-frame-margin-bundle-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="40 U.S.C. 6501",
                ),
            ),
        ],
    )

    scenarios = (
        {
            "target_family": "conditional_normative",
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.994306102841},
                {"family": "conditional_normative", "count": 1, "share": 0.005693897159},
            ),
            "expected_margin": -0.988612205682,
            "expected_priority": 1.138612205682,
            "expected_explicit_type": (
                "adaptive_frame_conditional_normative_outvoted_margin_low"
            ),
        },
        {
            "target_family": "epistemic",
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.990483348015},
                {"family": "epistemic", "count": 1, "share": 0.009516651985},
            ),
            "expected_margin": -0.98096669603,
            "expected_priority": 1.13096669603,
            "expected_explicit_type": "adaptive_frame_epistemic_outvoted_margin_low",
        },
    )

    for scenario in scenarios:
        target_family = str(scenario["target_family"])
        ranking = [dict(item) for item in tuple(scenario["ranking"])]
        family_shares = {
            str(item["family"]): float(item["share"]) for item in ranking
        }
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
        )

        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == ["frame", target_family]
        )
        assert base_ambiguity.metadata["adaptive_policy_pair"] == (
            f"frame->{target_family}"
        )
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert (
            abs(
                float(base_ambiguity.metadata["family_margin_raw"])
                - float(scenario["expected_margin"])
            )
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["expected_priority"])
            )
            < 1e-12
        )
        assert (
            base_ambiguity.metadata["explicit_ambiguity_type"]
            == scenario["expected_explicit_type"]
        )
        assert base_ambiguity.severity == "requires_rule"
        assert any(
            ambiguity.ambiguity_type == scenario["expected_explicit_type"]
            and ambiguity.candidate_ids == ["frame", target_family]
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_treats_zero_margin_epistemic_deontic_priority_pair_as_outvoted_adaptive_ambiguity(
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-contested-epistemic-deontic-doc",
        text="The agency knows and shall report.",
        normalized_text="The agency knows and shall report.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="epistemic",
                system="S5",
                symbol="K",
                label="knowledge",
                cue="knows",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-contested-epistemic-deontic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-epistemic-1",
                operator=ModalIROperator(
                    family="epistemic",
                    system="S5",
                    symbol="K",
                    label="knowledge",
                ),
                predicate=ModalIRPredicate(
                    name="report",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-contested-epistemic-deontic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="33 U.S.C. 3035",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "epistemic", "count": 1, "share": 0.5},
            {"family": "deontic", "count": 1, "share": 0.5},
        ],
        family_shares={"epistemic": 0.5, "deontic": 0.5},
    )

    adaptive_deontic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["epistemic", "deontic"]
    )
    assert adaptive_deontic.metadata["family_margin"] == 0.0
    assert adaptive_deontic.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_deontic.metadata["is_priority_policy_pair"] is True
    assert adaptive_deontic.metadata["explicit_ambiguity_type"] == (
        "adaptive_epistemic_deontic_outvoted_margin_low"
    )
    assert adaptive_deontic.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_epistemic_deontic_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_epistemic_conditional_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-epistemic-conditional-doc",
        text="The agency knows the notice applies.",
        normalized_text="The agency knows the notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="epistemic",
                system="S5",
                symbol="K",
                label="knowledge",
                cue="knows",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-epistemic-conditional-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-epistemic-1",
                operator=ModalIROperator(
                    family="epistemic",
                    system="S5",
                    symbol="K",
                    label="knowledge",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-epistemic-conditional-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="7 U.S.C. 136s",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "epistemic", "count": 1, "share": 1.0}],
        family_shares={"epistemic": 1.0},
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["epistemic", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["has_target_signal_evidence"] is False
    assert adaptive_conditional.metadata["signal_free_pair_policy_applied"] is True
    assert (
        adaptive_conditional.metadata["explicit_ambiguity_type"]
        == "adaptive_epistemic_conditional_normative_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_epistemic_conditional_normative_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_conditional_scope_signal_for_epistemic_conditional_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {"has_condition_or_exception_scope": True},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signaled-epistemic-conditional-doc",
        text="The agency knows the notice applies.",
        normalized_text="The agency knows the notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="epistemic",
                system="S5",
                symbol="K",
                label="knowledge",
                cue="knows",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signaled-epistemic-conditional-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-epistemic-1",
                operator=ModalIROperator(
                    family="epistemic",
                    system="S5",
                    symbol="K",
                    label="knowledge",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signaled-epistemic-conditional-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="7 U.S.C. 136s",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "epistemic", "count": 1, "share": 1.0}],
        family_shares={"epistemic": 1.0},
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["epistemic", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["has_target_signal_evidence"] is True
    assert adaptive_conditional.metadata["signal_free_pair_policy_applied"] is False
    assert (
        adaptive_conditional.metadata["explicit_ambiguity_type"]
        == "adaptive_epistemic_conditional_normative_outvoted_margin_low"
    )


def test_modal_compiler_surfaces_epistemic_self_pair_adaptive_ambiguity_for_zero_margin_tie(
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-epistemic-self-doc",
        text="The agency knows the duty applies.",
        normalized_text="The agency knows the duty applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="epistemic",
                system="S5",
                symbol="K",
                label="knowledge",
                cue="knows",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-epistemic-self-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-epistemic-1",
                operator=ModalIROperator(
                    family="epistemic",
                    system="S5",
                    symbol="K",
                    label="knowledge",
                ),
                predicate=ModalIRPredicate(
                    name="report",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-epistemic-self-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="5 U.S.C. 552",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "epistemic", "count": 1, "share": 0.5},
            {"family": "deontic", "count": 1, "share": 0.5},
        ],
        family_shares={"epistemic": 0.5, "deontic": 0.5},
    )

    adaptive_epistemic_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["epistemic"]
    )
    assert adaptive_epistemic_self.metadata["predicted_family"] == "epistemic"
    assert adaptive_epistemic_self.metadata["target_family"] == "epistemic"
    assert adaptive_epistemic_self.metadata["is_self_pair"] is True
    assert adaptive_epistemic_self.metadata["predicted_margin_to_runner_up"] == 0.0
    assert adaptive_epistemic_self.metadata["family_margin"] == 0.0
    assert adaptive_epistemic_self.metadata["adaptive_margin_direction"] == "contested"
    assert (
        adaptive_epistemic_self.metadata["explicit_ambiguity_type"]
        == "adaptive_epistemic_epistemic_contested_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_epistemic_epistemic_contested_margin_low"
        and ambiguity.metadata["is_self_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_surfaces_deontic_self_pair_adaptive_ambiguity_for_low_runner_up_margin() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-deontic-self-doc",
        text="The agency shall provide the report.",
        normalized_text="The agency shall provide the report.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-deontic-self-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_report",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-deontic-self-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="5 U.S.C. 552",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "deontic", "count": 2, "share": 0.57265},
            {"family": "temporal", "count": 2, "share": 0.42735},
        ],
        family_shares={"deontic": 0.57265, "temporal": 0.42735},
    )

    adaptive_deontic_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic"]
    )
    assert adaptive_deontic_self.metadata["predicted_family"] == "deontic"
    assert adaptive_deontic_self.metadata["target_family"] == "deontic"
    assert adaptive_deontic_self.metadata["is_self_pair"] is True
    assert adaptive_deontic_self.metadata["predicted_margin_to_runner_up"] == 0.1453
    assert adaptive_deontic_self.metadata["family_margin"] == 0.1453
    assert adaptive_deontic_self.metadata["adaptive_margin_direction"] == "contested"
    assert (
        adaptive_deontic_self.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_deontic_contested_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_deontic_contested_margin_low"
        and ambiguity.metadata["is_self_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_deontic_self_pair_as_outvoted_adaptive_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-deontic-self-doc",
        text="The agency shall provide the report.",
        normalized_text="The agency shall provide the report.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-deontic-self-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_report",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-deontic-self-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="5 U.S.C. 552",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "deontic", "count": 1, "share": 0.5},
            {"family": "temporal", "count": 1, "share": 0.5},
        ],
        family_shares={"deontic": 0.5, "temporal": 0.5},
    )

    adaptive_deontic_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic"]
    )
    assert adaptive_deontic_self.metadata["family_margin"] == 0.0
    assert adaptive_deontic_self.metadata["is_self_pair"] is True
    assert adaptive_deontic_self.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_deontic_self.metadata["is_priority_policy_pair"] is True
    assert adaptive_deontic_self.metadata["explicit_ambiguity_type"] == (
        "adaptive_deontic_deontic_outvoted_margin_low"
    )
    assert adaptive_deontic_self.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_deontic_outvoted_margin_low"
        and ambiguity.metadata["is_self_pair"] is True
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_deontic_self_pair_as_outvoted_adaptive_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-deontic-self-doc",
        text="The agency shall provide the report.",
        normalized_text="The agency shall provide the report.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-deontic-self-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_report",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-deontic-self-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="5 U.S.C. 552",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "deontic", "count": 2, "share": 0.5},
            {"family": "temporal", "count": 2, "share": 0.5},
        ],
        family_shares={"deontic": 0.5, "temporal": 0.5},
    )

    adaptive_deontic_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic"]
    )
    assert adaptive_deontic_self.metadata["predicted_family"] == "deontic"
    assert adaptive_deontic_self.metadata["target_family"] == "deontic"
    assert adaptive_deontic_self.metadata["is_self_pair"] is True
    assert adaptive_deontic_self.metadata["is_priority_policy_pair"] is True
    assert adaptive_deontic_self.metadata["predicted_margin_to_runner_up"] == 0.0
    assert adaptive_deontic_self.metadata["family_margin"] == 0.0
    assert adaptive_deontic_self.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_deontic_self.metadata["adaptive_priority"] == 0.15
    assert adaptive_deontic_self.metadata["explicit_ambiguity_type"] == (
        "adaptive_deontic_deontic_outvoted_margin_low"
    )
    assert adaptive_deontic_self.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_deontic_outvoted_margin_low"
        and ambiguity.metadata["is_self_pair"] is True
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_surfaces_temporal_self_pair_adaptive_ambiguity_for_low_runner_up_margin() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-temporal-self-doc",
        text="Within 30 days after review, the filing deadline applies.",
        normalized_text="Within 30 days after review, the filing deadline applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-temporal-self-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="file_report",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-temporal-self-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="5 U.S.C. 552",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "temporal", "count": 2, "share": 0.52},
            {"family": "frame", "count": 2, "share": 0.48},
        ],
        family_shares={"temporal": 0.52, "frame": 0.48},
    )

    adaptive_temporal_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal"]
    )
    assert adaptive_temporal_self.metadata["predicted_family"] == "temporal"
    assert adaptive_temporal_self.metadata["target_family"] == "temporal"
    assert adaptive_temporal_self.metadata["is_self_pair"] is True
    assert adaptive_temporal_self.metadata["predicted_margin_to_runner_up"] == 0.04
    assert adaptive_temporal_self.metadata["family_margin"] == 0.04
    assert adaptive_temporal_self.metadata["adaptive_margin_direction"] == "contested"
    assert abs(adaptive_temporal_self.metadata["adaptive_priority"] - 0.11) < 1e-12
    assert (
        adaptive_temporal_self.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_temporal_contested_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_temporal_contested_margin_low"
        and ambiguity.metadata["is_self_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_temporal_self_pair_with_priority_runner_up_as_outvoted_adaptive_ambiguity(
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-temporal-self-doc",
        text="Within 30 days the filing deadline applies.",
        normalized_text="Within 30 days the filing deadline applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-temporal-self-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="filing_deadline",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-temporal-self-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="10 U.S.C. 12645",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "temporal", "count": 1, "share": 0.5},
            {"family": "deontic", "count": 1, "share": 0.5},
        ],
        family_shares={"temporal": 0.5, "deontic": 0.5},
    )

    adaptive_temporal_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal"]
    )
    assert adaptive_temporal_self.metadata["predicted_family"] == "temporal"
    assert adaptive_temporal_self.metadata["target_family"] == "temporal"
    assert adaptive_temporal_self.metadata["is_self_pair"] is True
    assert adaptive_temporal_self.metadata["predicted_margin_to_runner_up"] == 0.0
    assert adaptive_temporal_self.metadata["family_margin"] == 0.0
    assert adaptive_temporal_self.metadata["runner_up_family"] == "deontic"
    assert adaptive_temporal_self.metadata["runner_up_is_priority_policy_pair"] is True
    assert adaptive_temporal_self.metadata["adaptive_margin_direction"] == "outvoted"
    assert (
        adaptive_temporal_self.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_temporal_outvoted_margin_low"
        and ambiguity.metadata["runner_up_is_priority_policy_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_temporal_self_pair_as_outvoted_when_self_pair_is_priority(
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-temporal-self-priority-doc",
        text="Within 30 days the filing deadline applies.",
        normalized_text="Within 30 days the filing deadline applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-temporal-self-priority-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="filing_deadline",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-temporal-self-priority-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="10 U.S.C. 12645",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "temporal", "count": 1, "share": 0.5},
            {"family": "dynamic", "count": 1, "share": 0.5},
        ],
        family_shares={"temporal": 0.5, "dynamic": 0.5},
    )

    adaptive_temporal_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal"]
    )
    assert adaptive_temporal_self.metadata["predicted_family"] == "temporal"
    assert adaptive_temporal_self.metadata["target_family"] == "temporal"
    assert adaptive_temporal_self.metadata["is_self_pair"] is True
    assert adaptive_temporal_self.metadata["predicted_margin_to_runner_up"] == 0.0
    assert adaptive_temporal_self.metadata["family_margin"] == 0.0
    assert adaptive_temporal_self.metadata["runner_up_family"] == "dynamic"
    assert adaptive_temporal_self.metadata["runner_up_is_priority_policy_pair"] is True
    assert adaptive_temporal_self.metadata["is_priority_policy_pair"] is True
    assert adaptive_temporal_self.metadata["adaptive_margin_direction"] == "outvoted"
    assert (
        adaptive_temporal_self.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_temporal_outvoted_margin_low"
    )
    assert adaptive_temporal_self.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_temporal_outvoted_margin_low"
        and ambiguity.metadata["runner_up_family"] == "dynamic"
        for ambiguity in ambiguities
    )


def test_modal_compiler_surfaces_epistemic_self_pair_adaptive_ambiguity_for_low_runner_up_margin(
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-epistemic-self-doc",
        text="The agency knows the report is false.",
        normalized_text="The agency knows the report is false.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="epistemic",
                system="S5",
                symbol="K",
                label="knowledge",
                cue="knows",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-epistemic-self-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-epistemic-1",
                operator=ModalIROperator(
                    family="epistemic",
                    system="S5",
                    symbol="K",
                    label="knowledge",
                ),
                predicate=ModalIRPredicate(
                    name="knowledge_report_false",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-epistemic-self-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="2 U.S.C. 1612",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "epistemic", "count": 2, "share": 0.55},
            {"family": "deontic", "count": 2, "share": 0.45},
        ],
        family_shares={"epistemic": 0.55, "deontic": 0.45},
    )

    adaptive_epistemic_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["epistemic"]
    )
    assert adaptive_epistemic_self.metadata["predicted_family"] == "epistemic"
    assert adaptive_epistemic_self.metadata["target_family"] == "epistemic"
    assert adaptive_epistemic_self.metadata["is_self_pair"] is True
    assert adaptive_epistemic_self.metadata["predicted_margin_to_runner_up"] == 0.1
    assert adaptive_epistemic_self.metadata["family_margin"] == 0.1
    assert adaptive_epistemic_self.metadata["adaptive_margin_direction"] == "contested"
    assert (
        adaptive_epistemic_self.metadata["explicit_ambiguity_type"]
        == "adaptive_epistemic_epistemic_contested_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_epistemic_epistemic_contested_margin_low"
        and ambiguity.metadata["is_self_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_surfaces_frame_self_pair_adaptive_ambiguity_for_low_runner_up_margin() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-frame-self-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-frame-self-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-frame-self-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="33 U.S.C. 866",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "frame", "count": 2, "share": 0.5655881468265},
            {"family": "temporal", "count": 2, "share": 0.4344118531735},
        ],
        family_shares={
            "frame": 0.5655881468265,
            "temporal": 0.4344118531735,
        },
    )

    adaptive_frame_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame"]
    )
    assert adaptive_frame_self.metadata["predicted_family"] == "frame"
    assert adaptive_frame_self.metadata["target_family"] == "frame"
    assert adaptive_frame_self.metadata["is_self_pair"] is True
    assert adaptive_frame_self.metadata["adaptive_policy_pair"] == "frame->frame"
    assert adaptive_frame_self.metadata["runner_up_family"] == "temporal"
    assert adaptive_frame_self.metadata["predicted_margin_to_runner_up"] == 0.131176
    assert adaptive_frame_self.metadata["family_margin"] == 0.131176
    assert abs(adaptive_frame_self.metadata["family_margin_raw"] - 0.131176293653) < 1e-12
    assert abs(adaptive_frame_self.metadata["adaptive_priority"] - 0.018823706347) < 1e-12
    assert abs(adaptive_frame_self.metadata["priority"] - 0.018823706347) < 1e-12
    assert adaptive_frame_self.metadata["adaptive_margin_direction"] == "contested"
    assert (
        adaptive_frame_self.metadata["explicit_ambiguity_type"]
        == "adaptive_frame_frame_contested_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_frame_contested_margin_low"
        and ambiguity.metadata["is_self_pair"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_strongest_runner_up_for_unsorted_frame_self_pair_margin() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    encoding = SpaCyLegalEncoding(
        document_id="adaptive-frame-self-unsorted-runner-up-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-frame-self-unsorted-runner-up-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-frame-self-unsorted-runner-up-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="42 U.S.C. 1395w",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "frame", "count": 2, "share": 0.53},
            {"family": "alethic", "count": 1, "share": 0.2},
            {"family": "temporal", "count": 2, "share": 0.47},
        ],
        family_shares={"frame": 0.53, "alethic": 0.2, "temporal": 0.47},
    )

    adaptive_frame_self = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame"]
    )
    assert adaptive_frame_self.metadata["runner_up_family"] == "temporal"
    assert adaptive_frame_self.metadata["runner_up_share"] == 0.47
    assert adaptive_frame_self.metadata["predicted_margin_to_runner_up"] == 0.06
    assert adaptive_frame_self.metadata["family_margin"] == 0.06
    assert adaptive_frame_self.metadata["adaptive_margin_direction"] == "contested"
    assert (
        adaptive_frame_self.metadata["explicit_ambiguity_type"]
        == "adaptive_frame_frame_contested_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_frame_contested_margin_low"
        and ambiguity.metadata["runner_up_family"] == "temporal"
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_logit_fallback_ranking_for_hybrid_frame_adaptive_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    compiled = compiler.compile("Definitions and construction.")

    adaptive_frame = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["hybrid", "frame"]
    )
    assert adaptive_frame.metadata["predicted_family"] == "hybrid"
    assert adaptive_frame.metadata["target_family"] == "frame"
    assert adaptive_frame.metadata["family_margin"] == round(
        adaptive_frame.metadata["family_margin_raw"],
        6,
    )
    assert abs(adaptive_frame.metadata["family_margin_raw"] + 0.216733561973) < 1e-12
    assert adaptive_frame.metadata["predicted_share_raw"] > adaptive_frame.metadata["target_share_raw"]
    assert adaptive_frame.metadata["predicted_share"] == round(
        adaptive_frame.metadata["predicted_share_raw"],
        6,
    )
    assert adaptive_frame.metadata["target_share"] == round(
        adaptive_frame.metadata["target_share_raw"],
        6,
    )
    assert adaptive_frame.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_frame.metadata["is_priority_policy_pair"] is True
    assert adaptive_frame.metadata["family_ranking"][0]["source"] == "logit_softmax_fallback"
    assert (
        adaptive_frame.metadata["explicit_ambiguity_type"]
        == "adaptive_hybrid_frame_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_hybrid_frame_outvoted_margin_low"
        and ambiguity.metadata["family_margin"]
        == round(ambiguity.metadata["family_margin_raw"], 6)
        and abs(ambiguity.metadata["family_margin_raw"] + 0.216733561973) < 1e-12
        for ambiguity in compiled.ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_deontic_conditional_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-deontic-doc",
        text="The agency shall provide written notice.",
        normalized_text="The agency shall provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-deontic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-deontic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "deontic", "count": 1, "share": 1.0}],
        family_shares={"deontic": 1.0},
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["has_target_signal_evidence"] is False
    assert adaptive_conditional.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_conditional.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_conditional.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_conditional.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_conditional_normative_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_deontic_conditional_normative_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_deontic_frame_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-deontic-frame-doc",
        text="The agency shall provide written notice.",
        normalized_text="The agency shall provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-deontic-frame-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-deontic-frame-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "deontic", "count": 1, "share": 1.0}],
        family_shares={"deontic": 1.0},
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "frame"]
    )
    assert adaptive_frame.metadata["has_target_signal_evidence"] is False
    assert adaptive_frame.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_frame.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_frame.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_frame.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_frame_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_frame_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_deontic_frame_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-deontic-frame-doc",
        text="The agency shall provide written notice.",
        normalized_text="The agency shall provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-deontic-frame-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-deontic-frame-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "deontic", "count": 1, "share": 0.5},
            {"family": "frame", "count": 1, "share": 0.5},
        ],
        family_shares={"deontic": 0.5, "frame": 0.5},
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "frame"]
    )
    assert adaptive_frame.metadata["family_margin"] == 0.0
    assert adaptive_frame.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_frame.metadata["is_priority_policy_pair"] is True
    assert adaptive_frame.metadata["explicit_ambiguity_type"] == (
        "adaptive_deontic_frame_outvoted_margin_low"
    )
    assert adaptive_frame.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_frame_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_deontic_temporal_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-deontic-temporal-doc",
        text="The agency shall provide written notice.",
        normalized_text="The agency shall provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-deontic-temporal-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-deontic-temporal-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "deontic", "count": 1, "share": 1.0}],
        family_shares={"deontic": 1.0},
    )

    adaptive_temporal = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "temporal"]
    )
    assert adaptive_temporal.metadata["has_target_signal_evidence"] is False
    assert adaptive_temporal.metadata["signal_free_pair_policy_applied"] is True
    assert (
        adaptive_temporal.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_temporal_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_deontic_temporal_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-deontic-temporal-doc",
        text="The agency shall provide written notice.",
        normalized_text="The agency shall provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-deontic-temporal-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-deontic-temporal-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "deontic", "count": 1, "share": 0.5},
            {"family": "temporal", "count": 1, "share": 0.5},
        ],
        family_shares={"deontic": 0.5, "temporal": 0.5},
    )

    adaptive_temporal = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "temporal"]
    )
    assert adaptive_temporal.metadata["family_margin"] == 0.0
    assert adaptive_temporal.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_temporal.metadata["is_priority_policy_pair"] is True
    assert adaptive_temporal.metadata["adaptive_priority"] == 0.15
    assert adaptive_temporal.metadata["explicit_ambiguity_type"] == (
        "adaptive_deontic_temporal_outvoted_margin_low"
    )
    assert adaptive_temporal.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_temporal_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_emits_adaptive_priority_metadata_for_frame_deontic_policy_margin(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-priority-frame-deontic-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-priority-frame-deontic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-priority-frame-deontic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="22 U.S.C. 283k",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {
                "family": "frame",
                "count": 1,
                "share_raw": 0.99003245694,
                "share": 0.990032,
            }
        ],
        family_shares={"frame": 0.99003245694},
    )

    adaptive_deontic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "deontic"]
    )
    assert abs(adaptive_deontic.metadata["family_margin_raw"] + 0.99003245694) < 1e-12
    assert abs(adaptive_deontic.metadata["adaptive_margin_abs"] - 0.99003245694) < 1e-12
    assert abs(adaptive_deontic.metadata["adaptive_priority"] - 1.14003245694) < 1e-12
    assert abs(adaptive_deontic.metadata["priority"] - 1.14003245694) < 1e-12
    assert adaptive_deontic.metadata["priority"] == adaptive_deontic.metadata["adaptive_priority"]
    assert adaptive_deontic.metadata["explicit_ambiguity_type"] == (
        "adaptive_frame_deontic_outvoted_margin_low"
    )


def test_modal_compiler_canonicalizes_frame_family_tokens_for_priority_policy_margins(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-priority-frame-canonical-token-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-priority-frame-canonical-token-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-1",
                operator=ModalIROperator(
                    family="ModalLogicFamily.FRAME",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="editorial_transfer",
                    arguments=["section:ref"],
                    role="frame_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-priority-frame-canonical-token-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="22 U.S.C. 283k",
                ),
            ),
        ],
    )

    scenarios = (
        (
            "deontic",
            0.999908575942,
            1.149908575942,
            "adaptive_frame_deontic_outvoted_margin_low",
        ),
        (
            "epistemic",
            0.631226929562,
            0.781226929562,
            "adaptive_frame_epistemic_outvoted_margin_low",
        ),
        (
            "temporal",
            0.998544042424,
            1.148544042424,
            "adaptive_frame_temporal_outvoted_margin_low",
        ),
    )
    for target_family, predicted_share, expected_priority, explicit_type in scenarios:
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=[
                {
                    "family": "ModalLogicFamily.FRAME",
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": round(predicted_share, 6),
                }
            ],
            family_shares={"ModalLogicFamily.FRAME": predicted_share},
        )
        adaptive_pair = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == ["frame", target_family]
        )
        assert adaptive_pair.metadata["adaptive_policy_pair"] == (
            f"frame->{target_family}"
        )
        assert abs(adaptive_pair.metadata["family_margin_raw"] + predicted_share) < 1e-12
        assert abs(adaptive_pair.metadata["adaptive_priority"] - expected_priority) < 1e-12
        assert abs(adaptive_pair.metadata["priority"] - expected_priority) < 1e-12
        assert adaptive_pair.metadata["priority"] == adaptive_pair.metadata["adaptive_priority"]
        assert adaptive_pair.metadata["explicit_ambiguity_type"] == explicit_type
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and ambiguity.candidate_ids == ["frame", target_family]
            and abs(ambiguity.metadata["priority"] - expected_priority) < 1e-12
            for ambiguity in ambiguities
        )


def test_modal_compiler_canonicalizes_compiled_primary_family_shares_for_policy_margin_filtering(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-compiled-primary-canonical-share-doc",
        text="Transferred editorial notes.",
        normalized_text="Transferred editorial notes.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="transferred",
                start_char=0,
                end_char=11,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-compiled-primary-canonical-share-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="obligation_scope",
                    arguments=["scope:test"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-compiled-primary-canonical-share-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="15 U.S.C. 7106",
                ),
            ),
        ],
    )

    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {
                "family": "ModalLogicFamily.FRAME",
                "count": 1,
                "share_raw": 0.95,
                "share": 0.95,
            },
            {
                "family": "DEONTIC",
                "count": 1,
                "share_raw": 0.90,
                "share": 0.90,
            },
            {
                "family": "TEMPORAL",
                "count": 1,
                "share_raw": 0.10,
                "share": 0.10,
            },
        ],
        family_shares={
            "ModalLogicFamily.FRAME": 0.95,
            "DEONTIC": 0.90,
            "TEMPORAL": 0.10,
        },
    )

    assert any(
        ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.metadata["adaptive_predicted_family_source"]
        == "compiled_primary_family"
        and ambiguity.metadata["adaptive_policy_pair"] == "deontic->frame"
        and ambiguity.candidate_ids == ["deontic", "frame"]
        for ambiguity in ambiguities
    )
    assert not any(
        ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.metadata["adaptive_predicted_family_source"]
        == "compiled_primary_family"
        and ambiguity.metadata["adaptive_policy_pair"] == "deontic->temporal"
        for ambiguity in ambiguities
    )


def test_modal_compiler_emits_priority_alias_for_temporal_signal_free_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-priority-temporal-policy-doc",
        text="Within 30 days notice applies.",
        normalized_text="Within 30 days notice applies.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="within",
                start_char=0,
                end_char=6,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-priority-temporal-policy-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="notice_applies",
                    arguments=["actor:agency"],
                    role="temporal_scope",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-priority-temporal-policy-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="12 U.S.C. 2121",
                ),
            ),
        ],
    )
    policy_cases = (
        (
            "conditional_normative",
            0.879553798991,
            1.029553798991,
            "adaptive_temporal_conditional_normative_outvoted_margin_low",
        ),
        (
            "deontic",
            0.999862926894,
            1.149862926894,
            "adaptive_temporal_deontic_outvoted_margin_low",
        ),
    )
    for target_family, predicted_share, expected_priority, explicit_type in policy_cases:
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=[
                {
                    "family": "temporal",
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": round(predicted_share, 6),
                }
            ],
            family_shares={"temporal": predicted_share},
        )
        adaptive_pair = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == ["temporal", target_family]
        )
        assert abs(adaptive_pair.metadata["family_margin_raw"] + predicted_share) < 1e-12
        assert abs(adaptive_pair.metadata["adaptive_priority"] - expected_priority) < 1e-12
        assert abs(adaptive_pair.metadata["priority"] - expected_priority) < 1e-12
        assert adaptive_pair.metadata["priority"] == adaptive_pair.metadata["adaptive_priority"]
        assert adaptive_pair.metadata["explicit_ambiguity_type"] == explicit_type
        assert any(
            ambiguity.ambiguity_type == explicit_type
            and abs(ambiguity.metadata["priority"] - expected_priority) < 1e-12
            for ambiguity in ambiguities
        )


def test_modal_compiler_uses_signal_free_pair_policy_for_deontic_epistemic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-deontic-epistemic-doc",
        text="The agency shall provide written notice.",
        normalized_text="The agency shall provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-deontic-epistemic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-deontic-epistemic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "deontic", "count": 1, "share": 1.0}],
        family_shares={"deontic": 1.0},
    )

    adaptive_epistemic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "epistemic"]
    )
    assert adaptive_epistemic.metadata["has_target_signal_evidence"] is False
    assert adaptive_epistemic.metadata["signal_free_pair_policy_applied"] is True
    assert (
        adaptive_epistemic.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_epistemic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_epistemic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_epistemic_cue_signal_for_deontic_epistemic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {"has_epistemic_cue": True},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signaled-deontic-epistemic-doc",
        text="The agency shall provide written notice.",
        normalized_text="The agency shall provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signaled-deontic-epistemic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signaled-deontic-epistemic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "deontic", "count": 1, "share": 1.0}],
        family_shares={"deontic": 1.0},
    )

    adaptive_epistemic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "epistemic"]
    )
    assert adaptive_epistemic.metadata["has_target_signal_evidence"] is True
    assert adaptive_epistemic.metadata["signal_free_pair_policy_applied"] is False
    assert (
        adaptive_epistemic.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_epistemic_outvoted_margin_low"
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_deontic_dynamic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-deontic-dynamic-doc",
        text="The agency shall provide written notice.",
        normalized_text="The agency shall provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-deontic-dynamic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-deontic-dynamic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "deontic", "count": 1, "share": 1.0}],
        family_shares={"deontic": 1.0},
    )

    adaptive_dynamic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "dynamic"]
    )
    assert adaptive_dynamic.metadata["has_target_signal_evidence"] is False
    assert adaptive_dynamic.metadata["signal_free_pair_policy_applied"] is True
    assert (
        adaptive_dynamic.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_dynamic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_dynamic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_deontic_dynamic_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-deontic-dynamic-doc",
        text="The agency shall provide written notice.",
        normalized_text="The agency shall provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-deontic-dynamic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-deontic-dynamic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "deontic", "count": 1, "share": 0.5},
            {"family": "dynamic", "count": 1, "share": 0.5},
        ],
        family_shares={"deontic": 0.5, "dynamic": 0.5},
    )

    adaptive_dynamic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "dynamic"]
    )
    assert adaptive_dynamic.metadata["family_margin"] == 0.0
    assert adaptive_dynamic.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_dynamic.metadata["is_priority_policy_pair"] is True
    assert adaptive_dynamic.metadata["adaptive_priority"] == 0.15
    assert adaptive_dynamic.metadata["explicit_ambiguity_type"] == (
        "adaptive_deontic_dynamic_outvoted_margin_low"
    )
    assert adaptive_dynamic.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_dynamic_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_alethic_epistemic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-alethic-epistemic-doc",
        text="It is possible to provide written notice.",
        normalized_text="It is possible to provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="alethic",
                system="S5",
                symbol="◇",
                label="possible",
                cue="possible",
                start_char=6,
                end_char=14,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-alethic-epistemic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-alethic-1",
                operator=ModalIROperator(
                    family="alethic",
                    system="S5",
                    symbol="◇",
                    label="possible",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-alethic-epistemic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "alethic", "count": 1, "share": 1.0}],
        family_shares={"alethic": 1.0},
    )

    adaptive_epistemic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["alethic", "epistemic"]
    )
    assert adaptive_epistemic.metadata["has_target_signal_evidence"] is False
    assert adaptive_epistemic.metadata["signal_free_pair_policy_applied"] is True
    assert (
        adaptive_epistemic.metadata["explicit_ambiguity_type"]
        == "adaptive_alethic_epistemic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_alethic_epistemic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_alethic_deontic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-alethic-deontic-doc",
        text="It is possible to provide written notice.",
        normalized_text="It is possible to provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="alethic",
                system="S5",
                symbol="◇",
                label="possible",
                cue="possible",
                start_char=6,
                end_char=14,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-alethic-deontic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-alethic-1",
                operator=ModalIROperator(
                    family="alethic",
                    system="S5",
                    symbol="◇",
                    label="possible",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-alethic-deontic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "alethic", "count": 1, "share": 1.0}],
        family_shares={"alethic": 1.0},
    )

    adaptive_deontic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["alethic", "deontic"]
    )
    assert adaptive_deontic.metadata["has_target_signal_evidence"] is False
    assert adaptive_deontic.metadata["signal_free_pair_policy_applied"] is True
    assert (
        adaptive_deontic.metadata["explicit_ambiguity_type"]
        == "adaptive_alethic_deontic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_alethic_deontic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_alethic_conditional_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-alethic-conditional-doc",
        text="It is possible to provide written notice.",
        normalized_text="It is possible to provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="alethic",
                system="S5",
                symbol="◇",
                label="possible",
                cue="possible",
                start_char=6,
                end_char=14,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-alethic-conditional-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-alethic-1",
                operator=ModalIROperator(
                    family="alethic",
                    system="S5",
                    symbol="◇",
                    label="possible",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-alethic-conditional-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "alethic", "count": 1, "share": 1.0}],
        family_shares={"alethic": 1.0},
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["alethic", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["has_target_signal_evidence"] is False
    assert adaptive_conditional.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_conditional.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_conditional.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_conditional.metadata["explicit_ambiguity_type"]
        == "adaptive_alethic_conditional_normative_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_alethic_conditional_normative_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_alethic_temporal_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-alethic-temporal-doc",
        text="It is possible to provide written notice.",
        normalized_text="It is possible to provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="alethic",
                system="S5",
                symbol="◇",
                label="possible",
                cue="possible",
                start_char=6,
                end_char=14,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-alethic-temporal-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-alethic-1",
                operator=ModalIROperator(
                    family="alethic",
                    system="S5",
                    symbol="◇",
                    label="possible",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-alethic-temporal-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "alethic", "count": 1, "share": 1.0}],
        family_shares={"alethic": 1.0},
    )

    adaptive_temporal = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["alethic", "temporal"]
    )
    assert adaptive_temporal.metadata["has_target_signal_evidence"] is False
    assert adaptive_temporal.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_temporal.metadata["is_priority_policy_pair"] is True
    assert (
        adaptive_temporal.metadata["explicit_ambiguity_type"]
        == "adaptive_alethic_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_alethic_temporal_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_temporal_signal_for_alethic_temporal_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {
            "has_temporal_scope": True,
        },
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signaled-alethic-temporal-doc",
        text="It is possible to provide written notice.",
        normalized_text="It is possible to provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="alethic",
                system="S5",
                symbol="◇",
                label="possible",
                cue="possible",
                start_char=6,
                end_char=14,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signaled-alethic-temporal-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-alethic-1",
                operator=ModalIROperator(
                    family="alethic",
                    system="S5",
                    symbol="◇",
                    label="possible",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signaled-alethic-temporal-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "alethic", "count": 1, "share": 1.0}],
        family_shares={"alethic": 1.0},
    )

    adaptive_temporal = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["alethic", "temporal"]
    )
    assert adaptive_temporal.metadata["has_target_signal_evidence"] is True
    assert adaptive_temporal.metadata["signal_free_pair_policy_applied"] is False
    assert adaptive_temporal.metadata["lexical_signals"]["has_temporal_scope"] is True
    assert (
        adaptive_temporal.metadata["explicit_ambiguity_type"]
        == "adaptive_alethic_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_alethic_temporal_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is False
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_conditional_signal_for_alethic_conditional_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {
            "has_condition_or_exception_scope": True,
        },
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signaled-alethic-conditional-doc",
        text="It is possible to provide written notice.",
        normalized_text="It is possible to provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="alethic",
                system="S5",
                symbol="◇",
                label="possible",
                cue="possible",
                start_char=6,
                end_char=14,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signaled-alethic-conditional-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-alethic-1",
                operator=ModalIROperator(
                    family="alethic",
                    system="S5",
                    symbol="◇",
                    label="possible",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signaled-alethic-conditional-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "alethic", "count": 1, "share": 1.0}],
        family_shares={"alethic": 1.0},
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["alethic", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["has_target_signal_evidence"] is True
    assert adaptive_conditional.metadata["signal_free_pair_policy_applied"] is False
    assert (
        adaptive_conditional.metadata["lexical_signals"]["has_condition_or_exception_scope"]
        is True
    )
    assert (
        adaptive_conditional.metadata["explicit_ambiguity_type"]
        == "adaptive_alethic_conditional_normative_outvoted_margin_low"
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_alethic_dynamic_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-alethic-dynamic-doc",
        text="It is possible to provide written notice.",
        normalized_text="It is possible to provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="alethic",
                system="S5",
                symbol="◇",
                label="possible",
                cue="possible",
                start_char=6,
                end_char=14,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-alethic-dynamic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-alethic-1",
                operator=ModalIROperator(
                    family="alethic",
                    system="S5",
                    symbol="◇",
                    label="possible",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-alethic-dynamic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "alethic", "count": 1, "share": 1.0}],
        family_shares={"alethic": 1.0},
    )

    adaptive_dynamic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["alethic", "dynamic"]
    )
    assert adaptive_dynamic.metadata["has_target_signal_evidence"] is False
    assert adaptive_dynamic.metadata["signal_free_pair_policy_applied"] is True
    assert (
        adaptive_dynamic.metadata["explicit_ambiguity_type"]
        == "adaptive_alethic_dynamic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_alethic_dynamic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_signal_free_pair_policy_for_alethic_frame_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signal-free-alethic-frame-doc",
        text="It is possible to provide written notice.",
        normalized_text="It is possible to provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="alethic",
                system="S5",
                symbol="◇",
                label="possible",
                cue="possible",
                start_char=6,
                end_char=14,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signal-free-alethic-frame-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-alethic-1",
                operator=ModalIROperator(
                    family="alethic",
                    system="S5",
                    symbol="◇",
                    label="possible",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signal-free-alethic-frame-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "alethic", "count": 1, "share": 1.0}],
        family_shares={"alethic": 1.0},
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["alethic", "frame"]
    )
    assert adaptive_frame.metadata["has_target_signal_evidence"] is False
    assert adaptive_frame.metadata["signal_free_pair_policy_applied"] is True
    assert adaptive_frame.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_frame.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_frame.metadata["explicit_ambiguity_type"]
        == "adaptive_alethic_frame_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_alethic_frame_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_uses_frame_signal_for_alethic_frame_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {
            "has_frame_context": True,
        },
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-signaled-alethic-frame-doc",
        text="It is possible to provide written notice.",
        normalized_text="It is possible to provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="alethic",
                system="S5",
                symbol="◇",
                label="possible",
                cue="possible",
                start_char=6,
                end_char=14,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-signaled-alethic-frame-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-alethic-1",
                operator=ModalIROperator(
                    family="alethic",
                    system="S5",
                    symbol="◇",
                    label="possible",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-signaled-alethic-frame-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[{"family": "alethic", "count": 1, "share": 1.0}],
        family_shares={"alethic": 1.0},
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["alethic", "frame"]
    )
    assert adaptive_frame.metadata["has_target_signal_evidence"] is True
    assert adaptive_frame.metadata["signal_free_pair_policy_applied"] is False
    assert adaptive_frame.metadata["lexical_signals"]["has_frame_context"] is True
    assert (
        adaptive_frame.metadata["explicit_ambiguity_type"]
        == "adaptive_alethic_frame_outvoted_margin_low"
    )


def test_modal_compiler_treats_zero_margin_alethic_frame_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-alethic-frame-doc",
        text="It is possible to provide written notice.",
        normalized_text="It is possible to provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="alethic",
                system="S5",
                symbol="◇",
                label="possible",
                cue="possible",
                start_char=6,
                end_char=14,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-alethic-frame-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-alethic-1",
                operator=ModalIROperator(
                    family="alethic",
                    system="S5",
                    symbol="◇",
                    label="possible",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-alethic-frame-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="18 U.S.C. 930",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "alethic", "count": 1, "share": 0.5},
            {"family": "frame", "count": 1, "share": 0.5},
        ],
        family_shares={"alethic": 0.5, "frame": 0.5},
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["alethic", "frame"]
    )
    assert adaptive_frame.metadata["family_margin"] == 0.0
    assert adaptive_frame.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_frame.metadata["is_priority_policy_pair"] is True
    assert adaptive_frame.metadata["is_compiler_required_policy_pair"] is True
    assert adaptive_frame.metadata["explicit_ambiguity_type"] == (
        "adaptive_alethic_frame_outvoted_margin_low"
    )
    assert adaptive_frame.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_alethic_frame_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_zero_margin_deontic_epistemic_priority_pair_as_outvoted_adaptive_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-zero-margin-deontic-epistemic-doc",
        text="The agency shall provide written notice.",
        normalized_text="The agency shall provide written notice.",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="deontic",
                system="D",
                symbol="O",
                label="obligation",
                cue="shall",
                start_char=11,
                end_char=16,
                token_indices=[],
            ),
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-zero-margin-deontic-epistemic-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-deontic-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["actor:agency"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-zero-margin-deontic-epistemic-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                    citation="5 U.S.C. 552",
                ),
            ),
        ],
    )
    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "deontic", "count": 1, "share": 0.5},
            {"family": "epistemic", "count": 1, "share": 0.5},
        ],
        family_shares={"deontic": 0.5, "epistemic": 0.5},
    )

    adaptive_epistemic = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "epistemic"]
    )
    assert adaptive_epistemic.metadata["family_margin"] == 0.0
    assert adaptive_epistemic.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_epistemic.metadata["is_priority_policy_pair"] is True
    assert adaptive_epistemic.metadata["explicit_ambiguity_type"] == (
        "adaptive_deontic_epistemic_outvoted_margin_low"
    )
    assert adaptive_epistemic.severity == "requires_rule"
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_epistemic_outvoted_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_treats_transferred_as_frame_scope_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    compiled = compiler.compile(
        "Within 30 days after review, the section is transferred."
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "frame"]
    )
    assert adaptive_frame.metadata["lexical_signals"]["has_frame_context"] is True
    assert adaptive_frame.metadata["lexical_signals"]["has_frame_scope_phrase"] is True


def test_modal_compiler_uses_bm25_frame_support_for_temporal_adaptive_frame_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    compiled = compiler.compile(
        "Within 30 days after review, the offense penalty applies."
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "frame"]
    )
    assert adaptive_frame.metadata["lexical_signals"]["has_frame_context"] is False
    assert adaptive_frame.metadata["has_frame_bm25_support"] is True
    assert (
        adaptive_frame.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_frame_outvoted_margin_low"
    )


def test_modal_compiler_treats_under_this_section_as_deontic_frame_adaptive_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    compiled = compiler.compile(
        "Applicants shall and must provide notice under this section."
    )

    adaptive_frame = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "frame"]
    )
    assert adaptive_frame.metadata["predicted_family"] == "deontic"
    assert adaptive_frame.metadata["target_family"] == "frame"
    assert adaptive_frame.metadata["family_margin"] < 0.0
    assert adaptive_frame.metadata["adaptive_margin_direction"] == "outvoted"
    assert (
        adaptive_frame.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_frame_outvoted_margin_low"
    )
    assert (
        adaptive_frame.metadata["lexical_signals"]["has_statutory_scope_reference"]
        is True
    )


def test_modal_codec_caps_repeated_generic_frame_cues_against_deontic_scope() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "The authority, authority, authority, authority, authority may act."
    )
    ranking = ranked_modal_families(encoding)

    assert ranking[0]["family"] == "deontic"
    assert ranking[1]["family"] == "frame"
    assert ranking[0]["share"] == 0.5
    assert ranking[1]["share"] == 0.5


def test_modal_codec_caps_repeated_generic_frame_cues_against_conditional_scope() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "The authority, authority, authority, authority, authority, subject to subsection (b)."
    )
    ranking = ranked_modal_families(encoding)

    assert ranking[0]["family"] == "conditional_normative"
    assert ranking[1]["family"] == "frame"
    assert ranking[0]["share"] == 0.5
    assert ranking[1]["share"] == 0.5


def test_modal_codec_does_not_generic_frame_debias_for_statutory_reference_only_scope() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "The authority under this section, authority under this section, authority under this section."
    )
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_condition_or_exception_scope"] is True
    assert signals["has_conditional_scope_phrase"] is False
    assert signals["has_conditional_scope_token"] is False
    assert _is_generic_frame_cue_debias_context(encoding, signals) is False


def test_modal_codec_tightens_conditional_soft_cap_for_strong_deontic_statutory_competition() -> None:
    counts = {
        "conditional_normative": 5.0,
        "deontic": 1.0,
    }
    signals = {
        "has_condition_clause": False,
        "has_condition_or_exception_scope": True,
        "has_conditional_scope_phrase": False,
        "has_conditional_scope_token": False,
        "has_deontic_cue": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_frame_context": False,
        "has_frame_editorial_scope_phrase": False,
        "has_frame_scope_phrase": False,
        "has_statutory_scope_reference": True,
        "has_temporal_scope": False,
    }

    _apply_conditional_competing_scope_soft_cap(counts, signals)

    conditional_count = float(counts["conditional_normative"])
    assert conditional_count > 3.0
    assert conditional_count < 3.6


def test_modal_codec_upgrades_generic_frame_temporal_scope_backfill_floor() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "The authority, authority, authority annual deadline applies."
    )
    ranking = ranked_modal_families(encoding)

    assert ranking[0]["family"] == "frame"
    assert ranking[1]["family"] == "temporal"
    assert ranking[0]["share"] == 0.631579
    assert ranking[1]["share"] == 0.368421


def test_modal_codec_upgrades_generic_frame_deontic_scope_backfill_floor() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "The authority, authority, authority liability for violations applies."
    )
    ranking = ranked_modal_families(encoding)

    assert ranking[0]["family"] == "frame"
    assert ranking[1]["family"] == "deontic"
    assert ranking[0]["share"] == 0.631579
    assert ranking[1]["share"] == 0.368421


def test_modal_codec_upgrades_generic_frame_conditional_and_temporal_backfill_floor() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "The authority, authority, authority before each annual review deadline."
    )
    ranking = ranked_modal_families(encoding)

    assert ranking[0]["family"] == "frame"
    assert ranking[1]["family"] == "conditional_normative"
    assert ranking[2]["family"] == "temporal"
    assert ranking[0]["share"] == 0.461538
    assert ranking[1]["share"] == 0.269231
    assert ranking[2]["share"] == 0.269231


def test_modal_codec_treats_powers_and_duties_as_deontic_scope_phrase() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "The powers and duties of the Corporation are as provided in this section."
    )
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_deontic_scope"] is True
    assert signals["has_deontic_scope_phrase"] is True


def test_modal_codec_treats_policy_of_phrase_as_deontic_scope_phrase() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "It is the policy of the United States to protect children."
    )
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_deontic_scope"] is True
    assert signals["has_deontic_scope_phrase"] is True


def test_modal_codec_treats_any_person_who_as_conditional_scope_phrase() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "Any person who knowingly violates this requirement shall be fined."
    )
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_condition_or_exception_scope"] is True
    assert signals["has_conditional_scope_phrase"] is True


def test_modal_codec_treats_under_this_subchapter_as_statutory_scope_reference() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "Benefits under this subchapter are available to qualifying applicants."
    )
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_condition_or_exception_scope"] is True


def test_modal_codec_treats_deemed_to_as_epistemic_scope_phrase_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "The Secretary deems necessary that the plan is deemed to satisfy this section."
    )
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_epistemic_scope"] is True
    assert signals["has_epistemic_scope_phrase"] is True


def test_modal_codec_backfills_epistemic_share_under_dense_deontic_scope() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "The agency shall and must, and shall and must, issue the order as the Secretary deems necessary."
    )
    ranking = ranked_modal_families(encoding)
    shares = {row["family"]: float(row["share"]) for row in ranking}

    assert shares["deontic"] > 0.0
    assert shares["epistemic"] > 0.0


def test_modal_codec_treats_date_of_enactment_as_temporal_scope_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "This authority expires on the date of enactment."
    )
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_temporal_scope"] is True
    assert signals["has_temporal_scope_phrase"] is True


def test_modal_codec_marks_at_any_time_phrase_as_temporal_scope_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode("The authority may act at any time.")
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_temporal_scope_phrase"] is True
    assert signals["has_temporal_scope"] is True


def test_modal_codec_treats_month_day_without_year_as_temporal_scope_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "The authority may act on January 6th."
    )
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_calendar_date_scope"] is True
    assert signals["has_temporal_scope"] is True


def test_modal_codec_treats_insofar_as_as_conditional_scope_phrase() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "The authority may act insofar as this section applies."
    )
    signals = modal_ambiguity_signals(encoding)
    ranking = ranked_modal_families(encoding)
    shares = {row["family"]: float(row["share"]) for row in ranking}

    assert signals["has_conditional_scope_phrase"] is True
    assert signals["has_condition_or_exception_scope"] is True
    assert shares["conditional_normative"] > 0.0


def test_modal_codec_marks_requires_token_as_deontic_scope_signal_without_cue() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode("The authority requires filing records.")
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_deontic_cue"] is False
    assert signals["has_deontic_scope"] is True


def test_modal_codec_treats_is_entitled_to_as_deontic_scope_phrase_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "A claimant is entitled to recover the amount due."
    )
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_deontic_scope"] is True
    assert signals["has_deontic_scope_phrase"] is True


def test_modal_codec_treats_as_otherwise_provided_in_as_conditional_scope_phrase() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "As otherwise provided in this section, the Secretary may act."
    )
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_condition_or_exception_scope"] is True
    assert signals["has_conditional_scope_phrase"] is True


def test_modal_codec_treats_as_provided_under_as_conditional_scope_phrase() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "As provided under section 5, this authority applies."
    )
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_statutory_scope_reference"] is True
    assert signals["has_condition_or_exception_scope"] is True
    assert signals["has_conditional_scope_phrase"] is True


def test_modal_codec_treats_for_fiscal_years_as_temporal_scope_phrase_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
        )
    )

    encoding = compiler.encoder.encode(
        "Appropriations are authorized for fiscal years 2025 through 2027."
    )
    signals = modal_ambiguity_signals(encoding)

    assert signals["has_temporal_scope"] is True
    assert signals["has_temporal_scope_phrase"] is True


def test_modal_compiler_surfaces_deontic_temporal_adaptive_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    compiled = compiler.compile(
        "The agency shall and must provide written notice before each annual review deadline."
    )

    adaptive_temporal = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "temporal"]
    )
    assert adaptive_temporal.metadata["predicted_family"] == "deontic"
    assert adaptive_temporal.metadata["target_family"] == "temporal"
    assert adaptive_temporal.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_temporal.metadata["family_margin"] < 0.0
    assert (
        adaptive_temporal.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_temporal_outvoted_margin_low"
    )
    assert adaptive_temporal.metadata["lexical_signals"]["has_temporal_scope"] is True
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_temporal_outvoted_margin_low"
        for ambiguity in compiled.ambiguities
    )


def test_modal_compiler_surfaces_deontic_conditional_adaptive_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    compiled = compiler.compile(
        "Before issuing a permit, the agency shall and must provide written notice."
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "conditional_normative"]
    )
    assert adaptive_conditional.metadata["predicted_family"] == "deontic"
    assert adaptive_conditional.metadata["target_family"] == "conditional_normative"
    assert adaptive_conditional.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_conditional.metadata["family_margin"] < 0.0
    assert adaptive_conditional.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_conditional.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_conditional.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_conditional_normative_outvoted_margin_low"
    )
    assert (
        adaptive_conditional.metadata["lexical_signals"]["has_condition_or_exception_scope"]
        is True
    )
    assert any(
        ambiguity.ambiguity_type
        == "adaptive_deontic_conditional_normative_outvoted_margin_low"
        for ambiguity in compiled.ambiguities
    )


def test_modal_compiler_surfaces_deontic_alethic_adaptive_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    compiled = compiler.compile(
        "The agency shall and must be unable to deny access to the record."
    )

    adaptive_alethic = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["deontic", "alethic"]
    )
    assert adaptive_alethic.metadata["predicted_family"] == "deontic"
    assert adaptive_alethic.metadata["target_family"] == "alethic"
    assert adaptive_alethic.metadata["adaptive_margin_direction"] == "outvoted"
    assert adaptive_alethic.metadata["family_margin"] < 0.0
    assert (
        adaptive_alethic.metadata["explicit_ambiguity_type"]
        == "adaptive_deontic_alethic_outvoted_margin_low"
    )
    assert adaptive_alethic.metadata["lexical_signals"]["has_alethic_scope"] is True
    assert any(
        ambiguity.ambiguity_type == "adaptive_deontic_alethic_outvoted_margin_low"
        for ambiguity in compiled.ambiguities
    )


def test_modal_compiler_surfaces_temporal_conditional_family_outvote_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_temporal_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "Unless waived, the agency must provide written notice within 30 days after review."
    )

    temporal_conditional = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_conditional_normative_family_outvoted"
    )
    assert temporal_conditional.candidate_ids == ["temporal", "conditional_normative"]
    assert temporal_conditional.metadata["predicted_family"] == "temporal"
    assert temporal_conditional.metadata["target_family"] == "conditional_normative"
    assert temporal_conditional.metadata["family_margin"] < 0.0
    assert temporal_conditional.metadata["lexical_signals"]["has_condition_or_exception_scope"] is True


def test_modal_compiler_treats_notwithstanding_as_temporal_conditional_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_temporal_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "Notwithstanding subsection (b), within 30 days after review the agency publishes the report."
    )

    temporal_conditional = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_conditional_normative_family_outvoted"
    )
    assert temporal_conditional.candidate_ids == ["temporal", "conditional_normative"]
    assert temporal_conditional.metadata["predicted_family"] == "temporal"
    assert temporal_conditional.metadata["target_family"] == "conditional_normative"
    assert temporal_conditional.metadata["target_share"] > 0.0
    assert (
        temporal_conditional.metadata["lexical_signals"]["has_condition_or_exception_scope"]
        is True
    )
    assert (
        temporal_conditional.metadata["lexical_signals"]["has_conditional_scope_phrase"]
        is True
    )
    assert (
        temporal_conditional.metadata["lexical_signals"]["has_conditional_scope_token"]
        is True
    )


def test_modal_compiler_treats_in_the_case_of_as_conditional_scope_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_temporal_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "In the case of a reviewed year adjustment, interest shall be computed after the due date and by the adjustment year return."
    )

    temporal_conditional = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_conditional_normative_family_outvoted"
    )
    assert temporal_conditional.metadata["predicted_family"] == "temporal"
    assert temporal_conditional.metadata["target_family"] == "conditional_normative"
    assert temporal_conditional.metadata["target_share"] > 0.0
    assert (
        temporal_conditional.metadata["lexical_signals"]["has_condition_or_exception_scope"]
        is True
    )
    assert (
        temporal_conditional.metadata["lexical_signals"]["has_conditional_scope_phrase"]
        is True
    )


def test_modal_compiler_treats_as_provided_in_as_conditional_scope_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_conditional_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "The agency shall and must provide written notice as provided in subsection (b)."
    )

    conditional_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "conditional_scope_family_outvoted"
    )
    assert conditional_scope.candidate_ids == ["deontic", "conditional_normative"]
    assert conditional_scope.metadata["predicted_family"] == "deontic"
    assert conditional_scope.metadata["target_family"] == "conditional_normative"
    assert conditional_scope.metadata["target_share"] > 0.0
    assert (
        conditional_scope.metadata["lexical_signals"]["has_statutory_scope_reference"]
        is True
    )
    assert (
        conditional_scope.metadata["lexical_signals"]["has_condition_or_exception_scope"]
        is True
    )


def test_modal_compiler_treats_as_provided_by_as_conditional_scope_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_conditional_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "The agency shall and must provide written notice as provided by subsection (b)."
    )

    conditional_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "conditional_scope_family_outvoted"
    )
    assert conditional_scope.candidate_ids == ["deontic", "conditional_normative"]
    assert conditional_scope.metadata["predicted_family"] == "deontic"
    assert conditional_scope.metadata["target_family"] == "conditional_normative"
    assert conditional_scope.metadata["target_share"] > 0.0
    assert (
        conditional_scope.metadata["lexical_signals"]["has_statutory_scope_reference"]
        is True
    )
    assert (
        conditional_scope.metadata["lexical_signals"]["has_condition_or_exception_scope"]
        is True
    )


def test_modal_compiler_treats_terms_and_conditions_as_conditional_scope_cue() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_conditional_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "The Secretary shall and must act under such terms and conditions as the Secretary prescribes."
    )

    conditional_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "conditional_scope_family_outvoted"
    )
    assert conditional_scope.candidate_ids == ["deontic", "conditional_normative"]
    assert conditional_scope.metadata["predicted_family"] == "deontic"
    assert conditional_scope.metadata["target_family"] == "conditional_normative"
    assert conditional_scope.metadata["target_share"] > 0.0
    assert (
        conditional_scope.metadata["lexical_signals"]["has_condition_or_exception_scope"]
        is True
    )


def test_modal_compiler_treats_for_purposes_of_as_conditional_scope_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_temporal_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "For purposes of this section, the agency publishes the annual report within 30 days after review."
    )

    temporal_conditional = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_conditional_normative_family_outvoted"
    )
    assert temporal_conditional.metadata["predicted_family"] == "temporal"
    assert temporal_conditional.metadata["target_family"] == "conditional_normative"
    assert temporal_conditional.metadata["target_share"] > 0.0
    assert (
        temporal_conditional.metadata["lexical_signals"]["has_condition_or_exception_scope"]
        is True
    )
    assert (
        temporal_conditional.metadata["lexical_signals"]["has_conditional_scope_phrase"]
        is True
    )


def test_modal_compiler_treats_with_respect_to_as_conditional_scope_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_temporal_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "Within 30 days after review and following consultation, the agency shall issue the annual notice with respect to each assessed amount."
    )

    temporal_conditional = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_conditional_normative_family_outvoted"
    )
    assert temporal_conditional.metadata["predicted_family"] == "temporal"
    assert temporal_conditional.metadata["target_family"] == "conditional_normative"
    assert temporal_conditional.metadata["target_share"] > 0.0
    assert (
        temporal_conditional.metadata["lexical_signals"]["has_condition_or_exception_scope"]
        is True
    )
    assert (
        temporal_conditional.metadata["lexical_signals"]["has_conditional_scope_phrase"]
        is True
    )


def test_modal_compiler_surfaces_temporal_frame_family_outvote_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_temporal_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "The authority shall by regulation issue written notice within 30 days after review."
    )

    temporal_frame = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_frame_family_outvoted"
    )
    assert temporal_frame.candidate_ids == ["temporal", "frame"]
    assert temporal_frame.metadata["predicted_family"] == "temporal"
    assert temporal_frame.metadata["target_family"] == "frame"
    assert temporal_frame.metadata["family_margin"] < 0.0
    assert temporal_frame.metadata["lexical_signals"]["has_frame_context"] is True


def test_modal_compiler_surfaces_temporal_scope_family_outvote_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_temporal_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "The agency shall and must provide written notice before each annual review deadline."
    )

    temporal_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_scope_family_outvoted"
    )
    assert temporal_scope.candidate_ids == ["deontic", "temporal"]
    assert temporal_scope.metadata["predicted_family"] == "deontic"
    assert temporal_scope.metadata["target_family"] == "temporal"
    assert temporal_scope.metadata["family_margin"] < 0.0
    assert temporal_scope.metadata["lexical_signals"]["has_temporal_scope"] is True


def test_modal_compiler_surfaces_frame_scope_family_outvote_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_frame_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "The secretary shall and must provide written notice."
    )

    frame_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "frame_scope_family_outvoted"
    )
    assert frame_scope.candidate_ids == ["deontic", "frame"]
    assert frame_scope.metadata["predicted_family"] == "deontic"
    assert frame_scope.metadata["target_family"] == "frame"
    assert frame_scope.metadata["family_margin"] < 0.0
    assert frame_scope.metadata["lexical_signals"]["has_frame_context"] is True


def test_modal_compiler_treats_court_as_frame_scope_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_frame_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "The court shall and must issue the order."
    )

    frame_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "frame_scope_family_outvoted"
    )
    assert frame_scope.candidate_ids == ["deontic", "frame"]
    assert frame_scope.metadata["predicted_family"] == "deontic"
    assert frame_scope.metadata["target_family"] == "frame"
    assert frame_scope.metadata["target_share"] == 0.0
    assert frame_scope.metadata["lexical_signals"]["has_frame_context"] is True


def test_modal_compiler_surfaces_conditional_scope_family_outvote_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_conditional_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "Before issuing a permit, the agency shall and must provide written notice."
    )

    conditional_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "conditional_scope_family_outvoted"
    )
    assert conditional_scope.candidate_ids == ["deontic", "conditional_normative"]
    assert conditional_scope.metadata["predicted_family"] == "deontic"
    assert conditional_scope.metadata["target_family"] == "conditional_normative"
    assert conditional_scope.metadata["family_margin"] < 0.0
    assert (
        conditional_scope.metadata["lexical_signals"]["has_condition_or_exception_scope"]
        is True
    )


def test_modal_compiler_treats_notwithstanding_as_conditional_scope_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_conditional_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "Notwithstanding subsection (b), the agency shall issue written notice."
    )

    adaptive_conditional = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["conditional_normative", "deontic"]
    )
    assert adaptive_conditional.metadata["predicted_family"] == "conditional_normative"
    assert adaptive_conditional.metadata["target_family"] == "deontic"
    assert adaptive_conditional.metadata["target_share"] > 0.0
    assert (
        adaptive_conditional.metadata["lexical_signals"]["has_condition_or_exception_scope"]
        is True
    )
    assert (
        adaptive_conditional.metadata["lexical_signals"]["has_conditional_scope_phrase"]
        is True
    )
    assert (
        adaptive_conditional.metadata["lexical_signals"]["has_conditional_scope_token"]
        is True
    )


def test_modal_compiler_surfaces_deontic_scope_family_outvote_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_deontic_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "Within 30 days after review, the agency shall submit an annual report."
    )

    deontic_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "deontic_scope_family_outvoted"
    )
    assert deontic_scope.candidate_ids == ["temporal", "deontic"]
    assert deontic_scope.metadata["predicted_family"] == "temporal"
    assert deontic_scope.metadata["target_family"] == "deontic"
    assert deontic_scope.metadata["family_margin"] < 0.0
    assert deontic_scope.metadata["lexical_signals"]["has_deontic_cue"] is True
    temporal_deontic = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_deontic_scope_family_outvoted"
    )
    assert temporal_deontic.candidate_ids == ["temporal", "deontic"]
    assert temporal_deontic.metadata["predicted_family"] == "temporal"
    assert temporal_deontic.metadata["target_family"] == "deontic"
    assert temporal_deontic.metadata["family_margin"] < 0.0


def test_modal_compiler_treats_deontic_scope_phrase_as_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_deontic_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "Within 30 days after review, the agency is under an obligation to file the report."
    )

    deontic_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "deontic_scope_family_outvoted"
    )
    assert deontic_scope.candidate_ids == ["temporal", "deontic"]
    assert deontic_scope.metadata["predicted_family"] == "temporal"
    assert deontic_scope.metadata["target_family"] == "deontic"
    assert deontic_scope.metadata["target_share"] > 0.0
    assert deontic_scope.metadata["lexical_signals"]["has_deontic_cue"] is True
    assert deontic_scope.metadata["lexical_signals"]["has_deontic_scope"] is True
    assert deontic_scope.metadata["lexical_signals"]["has_deontic_scope_phrase"] is True


def test_modal_compiler_treats_prohibition_heading_as_adaptive_deontic_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    compiled = compiler.compile(
        "Within 30 days after review, prohibition on denial of access applies."
    )

    adaptive_deontic = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal", "deontic"]
    )
    assert adaptive_deontic.metadata["predicted_family"] == "temporal"
    assert adaptive_deontic.metadata["target_family"] == "deontic"
    assert adaptive_deontic.metadata["target_share"] == 0.0
    assert adaptive_deontic.metadata["family_margin"] < 0.0
    assert adaptive_deontic.metadata["lexical_signals"]["has_deontic_cue"] is False
    assert adaptive_deontic.metadata["lexical_signals"]["has_deontic_scope"] is True
    assert adaptive_deontic.metadata["lexical_signals"]["has_deontic_scope_phrase"] is True
    assert adaptive_deontic.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert adaptive_deontic.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert (
        adaptive_deontic.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_deontic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_deontic_outvoted_margin_low"
        for ambiguity in compiled.ambiguities
    )


def test_modal_compiler_surfaces_dynamic_scope_family_outvote_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_dynamic_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "Within 30 days after review, the agency files the report by certified mail."
    )

    dynamic_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "dynamic_scope_family_outvoted"
    )
    assert dynamic_scope.candidate_ids == ["temporal", "dynamic"]
    assert dynamic_scope.metadata["predicted_family"] == "temporal"
    assert dynamic_scope.metadata["target_family"] == "dynamic"
    assert dynamic_scope.metadata["family_margin"] < 0.0
    assert dynamic_scope.metadata["target_share"] > 0.0
    assert dynamic_scope.metadata["lexical_signals"]["has_dynamic_cue"] is True


def test_modal_compiler_treats_filed_as_dynamic_scope_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_dynamic_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "Within 30 days after review, the agency filed the report."
    )

    dynamic_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "dynamic_scope_family_outvoted"
    )
    assert dynamic_scope.candidate_ids == ["temporal", "dynamic"]
    assert dynamic_scope.metadata["predicted_family"] == "temporal"
    assert dynamic_scope.metadata["target_family"] == "dynamic"
    assert dynamic_scope.metadata["target_share"] == 0.0
    assert dynamic_scope.metadata["lexical_signals"]["has_dynamic_cue"] is False
    assert dynamic_scope.metadata["lexical_signals"]["has_dynamic_scope"] is True


def test_modal_compiler_surfaces_alethic_scope_family_outvote_ambiguity() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_alethic_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "It is possible that the agency will provide notice within 30 days after review."
    )

    alethic_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "alethic_scope_family_outvoted"
    )
    assert alethic_scope.candidate_ids == ["temporal", "alethic"]
    assert alethic_scope.metadata["predicted_family"] == "temporal"
    assert alethic_scope.metadata["target_family"] == "alethic"
    assert alethic_scope.metadata["family_margin"] < 0.0
    assert alethic_scope.metadata["target_share"] > 0.0
    assert alethic_scope.metadata["lexical_signals"]["has_alethic_cue"] is True


def test_modal_compiler_treats_unable_to_as_alethic_scope_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_alethic_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "The agency shall and must be unable to deny access to the record."
    )

    alethic_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "alethic_scope_family_outvoted"
    )
    assert alethic_scope.candidate_ids == ["deontic", "alethic"]
    assert alethic_scope.metadata["predicted_family"] == "deontic"
    assert alethic_scope.metadata["target_family"] == "alethic"
    assert alethic_scope.metadata["family_margin"] < 0.0
    assert alethic_scope.metadata["target_share"] == 0.0
    assert alethic_scope.metadata["lexical_signals"]["has_alethic_scope"] is True
    assert alethic_scope.metadata["lexical_signals"]["has_alethic_cue"] is False


def test_modal_compiler_treats_not_later_than_scope_as_temporal_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_temporal_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "The agency shall and must provide written notice not later than 30 days."
    )

    temporal_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_scope_family_outvoted"
    )
    assert temporal_scope.candidate_ids == ["deontic", "temporal"]
    assert temporal_scope.metadata["predicted_family"] == "deontic"
    assert temporal_scope.metadata["target_family"] == "temporal"
    assert temporal_scope.metadata["family_margin"] < 0.0
    assert temporal_scope.metadata["target_share"] > 0.0
    assert temporal_scope.metadata["lexical_signals"]["has_temporal_scope"] is True
    temporal_deontic = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_deontic_scope_family_outvoted"
    )
    assert temporal_deontic.candidate_ids == ["deontic", "temporal"]
    assert temporal_deontic.metadata["predicted_family"] == "deontic"
    assert temporal_deontic.metadata["target_family"] == "temporal"
    assert temporal_deontic.metadata["family_margin"] < 0.0


def test_modal_compiler_treats_period_beginning_with_calendar_date_as_temporal_scope_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_temporal_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "The agency shall provide notice for the period beginning on January 1, 2030 and ending on December 31, 2030."
    )

    temporal_scope = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_scope_family_outvoted"
    )
    assert temporal_scope.candidate_ids == ["deontic", "temporal"]
    assert temporal_scope.metadata["predicted_family"] == "deontic"
    assert temporal_scope.metadata["target_family"] == "temporal"
    assert temporal_scope.metadata["target_share"] > 0.0
    assert temporal_scope.metadata["lexical_signals"]["has_temporal_scope"] is True
    assert temporal_scope.metadata["lexical_signals"]["has_temporal_scope_phrase"] is True
    assert temporal_scope.metadata["lexical_signals"]["has_calendar_date_scope"] is True


def test_modal_compiler_treats_before_scope_as_temporal_conditional_ambiguity_signal() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_temporal_target_family_outvote_margin=0.0,
        )
    )

    compiled = compiler.compile(
        "Before a removal takes effect, the agency shall provide written notice within 30 days after review and following consultation."
    )

    temporal_conditional = next(
        ambiguity
        for ambiguity in compiled.ambiguities
        if ambiguity.ambiguity_type == "temporal_conditional_normative_family_outvoted"
    )
    assert temporal_conditional.metadata["predicted_family"] == "temporal"
    assert temporal_conditional.metadata["target_family"] == "conditional_normative"
    assert temporal_conditional.metadata["family_margin"] < 0.0
    assert temporal_conditional.metadata["lexical_signals"]["has_condition_clause"] is True


def test_modal_decompiler_preserves_context_without_formula_style_text() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="regex", embedding_dimensions=8)
    )
    source = (
        "Section 1 contains definitions. "
        "The agency must provide notice within 30 days."
    )

    result = codec.encode(source, document_id="context-doc")
    slot_texts = decoded_modal_phrase_slot_text_map(result.decoded_modal_text)
    semantic_slot_texts = decoded_modal_phrase_slot_text_map(
        result.decoded_modal_text,
        include_provenance_only=False,
    )

    assert result.decoded_text == result.normalized_text
    assert result.decoded_modal_text.reconstruction_similarity == 1.0
    assert result.losses["text_reconstruction_loss"] == 0.0
    assert 0.0 < result.decoded_modal_text.modal_span_coverage < 1.0
    assert result.losses["modal_span_coverage_loss"] > 0.0
    assert semantic_slot_texts["source_context_span"] == [
        "Section 1 contains definitions."
    ]
    assert semantic_slot_texts["modal_source_span"] == [
        "The agency must provide notice within 30 days."
    ]
    assert slot_texts["modal_source_span_token_prefix"] == ["the"]
    assert slot_texts["modal_source_span_token_suffix"] == ["days."]
    assert "must" in slot_texts["modal_source_span_token"]
    assert "definitions." in slot_texts["source_context_span_token"]
    assert "must" in slot_texts["modal_source_span_bridge_cue"]
    assert "within" in slot_texts["modal_source_span_bridge_cue"]
    assert "deontic:O:must" in slot_texts["modal_source_span_bridge_modal_signature"]
    assert "temporal:F:within" in slot_texts["modal_source_span_bridge_modal_signature"]
    assert "O[deontic:D]" not in result.decoded_text
    assert "obligatory" not in result.decoded_text
    assert modal_text_token_similarity(source, result.decoded_text) == 1.0


def test_modal_decompiler_surfaces_source_span_modal_transition_slots() -> None:
    source_id = "us-code-5-552-source-span-transitions"
    source_text = (
        "The Secretary shall issue payments on or after January 1, 2030, "
        "subject to section 552."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="shall_issue_payments"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="5 U.S.C. 552",
        ),
        metadata={"cue": "shall"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert "deontic:O" in slot_texts["modal_source_span_bridge_modal_formula_signature"]
    assert "deontic->temporal" in slot_texts["modal_source_span_bridge_modal_family_pair"]
    assert (
        "deontic->conditional_normative"
        in slot_texts["modal_source_span_bridge_modal_family_pair"]
    )
    assert "deontic->frame" in slot_texts["modal_source_span_bridge_modal_family_pair"]
    assert (
        "deontic:O->temporal:F:on_or_after"
        in slot_texts["modal_source_span_bridge_modal_transition_signature"]
    )
    assert (
        "deontic:O->frame:Frame:subject_to"
        in slot_texts["modal_source_span_bridge_modal_transition_signature"]
    )
def test_modal_decompiler_source_spans_emit_refined_directional_family_pairs() -> None:
    source = (
        "Authorities shall determine findings before certification for this section."
    )
    span_end = len(source)
    modal_ir = ModalIRDocument(
        document_id="refined-family-pairs-source-span",
        source="us_code",
        normalized_text=source,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame",
                operator=ModalIROperator(
                    family="frame",
                    system="frame",
                    symbol="Frame",
                    label="framed as",
                ),
                predicate=ModalIRPredicate(name="governance_context"),
                provenance=ModalIRProvenance(
                    source_id="refined-family-pairs-source-span",
                    start_char=0,
                    end_char=span_end,
                    citation="2 U.S.C. 6622",
                ),
            ),
            ModalIRFormula(
                formula_id="f-deontic",
                operator=ModalIROperator(
                    family="deontic",
                    system="kd",
                    symbol="O",
                    label="obligatory",
                ),
                predicate=ModalIRPredicate(name="perform_certification"),
                provenance=ModalIRProvenance(
                    source_id="refined-family-pairs-source-span",
                    start_char=0,
                    end_char=span_end,
                    citation="2 U.S.C. 6622",
                ),
            ),
            ModalIRFormula(
                formula_id="f-conditional",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="dyadic",
                    symbol="O|",
                    label="conditionally obligatory",
                ),
                predicate=ModalIRPredicate(name="determine_certification_scope"),
                provenance=ModalIRProvenance(
                    source_id="refined-family-pairs-source-span",
                    start_char=0,
                    end_char=span_end,
                    citation="2 U.S.C. 6622",
                ),
            ),
        ],
    )

    decoded = decode_modal_ir_document(modal_ir)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert {
        "frame->deontic",
        "deontic->temporal",
        "conditional_normative->epistemic",
    }.issubset(set(slot_texts["modal_source_span_refined_modal_family_pair"]))


def test_modal_decompiler_surfaces_typed_role_and_reference_dependency_slots() -> None:
    source_id = "us-code-43-337.-typed-decompiler-roles"
    source = (
        "Where it shall appear to the satisfaction of the Secretary after "
        "expenditures, the Secretary shall perfect the homestead entry under "
        "section 337."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="frame",
            system="frame_bm25",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(name="secretary_shall_perfect_homestead_entry"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source),
            citation="43 U.S.C. 337",
        ),
        conditions=["under section 337"],
        metadata={"cue": "section"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert "subject+action+object+temporal" in slot_texts[
        "modal_source_span_typed_decompiler_role_signature"
    ]
    assert "frame->temporal" in slot_texts[
        "modal_source_span_typed_decompiler_family_pair"
    ]
    assert "frame->deontic:subject+action+object+temporal" in slot_texts[
        "modal_source_span_typed_decompiler_family_pair_bridge"
    ]
    assert "direct_reference:statutory_section" in slot_texts["reference_dependency"]
    assert "statutory_section:337" in slot_texts["reference_dependency_target"]
    assert "direct_reference:section" in slot_texts["reference_dependency"]


def test_modal_decompiler_surfaces_frame_to_deontic_typed_ir_slots() -> None:
    source_id = "frame-deontic-typed-ir-slots"
    source = "The Secretary shall tax costs under section 1920."
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="frame",
            system="frame_bm25",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(name="secretary_shall_tax_costs"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source),
            citation="28 U.S.C. 1920",
        ),
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source,
        formulas=[formula],
        frame_candidates=[
            ModalIRFrame(
                frame_id="taxation_of_costs",
                score=2.0,
                matched_terms=["tax costs"],
            )
        ],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert decoded.formulas == ["Frame[frame:frame_bm25](secretary_shall_tax_costs)"]
    assert "obligation" in slot_texts["typed_ir_deontic_force"]
    assert "frame->deontic" in slot_texts["typed_ir_deontic_candidate_family_pair"]
    assert "shall" in slot_texts["typed_ir_deontic_candidate_cue"]
    assert (
        "frame:Frame->deontic:O:shall"
        in slot_texts["typed_ir_frame_deontic_bridge_signature"]
    )
    assert "taxation_of_costs" in slot_texts["typed_ir_deontic_frame_context"]


def test_modal_decompiler_recovers_condition_exception_and_citation_slots() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    compiled = compiler.compile(
        "If the application is complete, the agency must issue written notice unless waived.",
        citation="5 U.S.C. 552",
        source="us_code",
    )

    decoded = decode_modal_ir_document(compiled.modal_ir)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(compiled.modal_ir)

    assert "if the application is complete" in slot_texts["condition"]
    assert "unless waived" in slot_texts["exception"]
    assert slot_texts["condition_prefix"] == ["if"]
    assert slot_texts["condition_if"] == ["the application is complete"]
    assert slot_texts["exception_prefix"] == ["unless"]
    assert slot_texts["exception_unless"] == ["waived"]
    assert "deontic:O:must" in slot_texts["cue_modal_registry_signature"]
    assert "conditional_normative:O|:if" in slot_texts["condition_modal_registry_signature"]
    assert "conditional_normative:O|:unless" in slot_texts[
        "exception_modal_registry_signature"
    ]
    assert "conditional_normative:O|:if" in slot_texts["condition_modal_bridge_signature"]
    assert "conditional_normative" in slot_texts["condition_modal_bridge_family"]
    assert "conditional_normative:O|:unless" in slot_texts[
        "exception_modal_bridge_signature"
    ]
    assert "conditional_normative" in slot_texts["exception_modal_bridge_family"]
    assert "family_shift" in slot_texts["condition_modal_registry_alignment"]
    assert "family_shift" in slot_texts["exception_modal_registry_alignment"]
    assert slot_texts["citation"] == ["5 U.S.C. 552"]
    assert slot_texts["citation_canonical"] == ["5 U.S.C. 552"]
    assert slot_texts["citation_title"] == ["5"]
    assert slot_texts["citation_code"] == ["U.S.C."]
    assert slot_texts["citation_section"] == ["552"]
    assert slot_texts["citation_section_primary"] == ["552"]
    assert slot_texts["citation_section_component_count"] == ["1"]
    assert slot_texts["citation_section_component"] == ["552"]
    assert slot_texts["citation_section_number"] == ["552"]
    assert any(
        triple["predicate"] == "condition"
        and triple["object"] == "if the application is complete"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "exception"
        and triple["object"] == "unless waived"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation"
        and triple["object"] == "5 U.S.C. 552"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_canonical"
        and triple["object"] == "5 U.S.C. 552"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_prefix"
        and triple["object"] == "if"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_if"
        and triple["object"] == "the application is complete"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "cue_modal_registry_signature"
        and triple["object"] == "deontic:O:must"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_modal_registry_signature"
        and triple["object"] == "conditional_normative:O|:if"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "exception_modal_registry_signature"
        and triple["object"] == "conditional_normative:O|:unless"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "conditional_normative:O|:if"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "exception_modal_bridge_signature"
        and triple["object"] == "conditional_normative:O|:unless"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_modal_registry_alignment"
        and triple["object"] == "family_shift"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "exception_modal_registry_alignment"
        and triple["object"] == "family_shift"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "exception_prefix"
        and triple["object"] == "unless"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "exception_unless"
        and triple["object"] == "waived"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_title"
        and triple["object"] == "5"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_code"
        and triple["object"] == "U.S.C."
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section"
        and triple["object"] == "552"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_primary"
        and triple["object"] == "552"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_component_count"
        and triple["object"] == "1"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_component"
        and triple["object"] == "552"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_number"
        and triple["object"] == "552"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_temporal_for_purposes_bridge_slots() -> None:
    source_id = "us-code-42-1395rr-fd726267510ffffe"
    source_text = (
        "For purposes of this section, benefits are available during fiscal years 2025 "
        "through 2027."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="temporal",
            system="ltl",
            symbol="F",
            label="eventually",
        ),
        predicate=ModalIRPredicate(name="authorize_benefits"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="42 U.S.C. 1395rr",
        ),
        conditions=["for purposes of this section"],
        metadata={"cue": "fiscal years"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert slot_texts["condition_modal_signature"] == ["temporal:F:for_purposes_of"]
    assert slot_texts["condition_modal_bridge_signature"] == [
        "conditional_normative:O|:for_purposes_of",
        "frame:Frame:for_purposes_of",
    ]
    assert slot_texts["condition_modal_bridge_family"] == [
        "conditional_normative",
        "frame",
    ]
    assert slot_texts["condition_modal_bridge_operator"] == ["O|", "Frame"]
    assert slot_texts["condition_modal_bridge_operator_pair"] == ["F->O|", "F->Frame"]
    assert slot_texts["condition_bridge_operator_pair"] == ["F->O|", "F->Frame"]
    assert "for_purposes_of" in slot_texts["bridge_cue"]
    assert slot_texts["bridge_modal_bridge_signature"] == [
        "conditional_normative:O|:for_purposes_of",
        "frame:Frame:for_purposes_of",
    ]
    assert slot_texts["bridge_bridge_operator_pair"] == ["F->O|", "F->Frame"]
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "frame:Frame:for_purposes_of"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_bridge_operator_pair"
        and triple["object"] == "F->Frame"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "bridge_modal_bridge_signature"
        and triple["object"] == "conditional_normative:O|:for_purposes_of"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "bridge_bridge_operator_pair"
        and triple["object"] == "F->O|"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_temporal_after_cross_family_bridge_slots() -> None:
    source_id = "us-code-42-7385s-359864d4338b98ff"
    source_text = "After transfer, benefits are paid."
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="temporal",
            system="ltl",
            symbol="F",
            label="eventually",
        ),
        predicate=ModalIRPredicate(name="pay_benefits"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="42 U.S.C. 7385s",
        ),
        conditions=["after transfer"],
        metadata={"cue": "after"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "after" in slot_texts["condition_prefix_key"]
    assert "after" in slot_texts["condition_prefix_temporal_relation"]
    assert "temporal:X:after" in slot_texts["condition_modal_bridge_signature"]
    assert "conditional_normative:O|:after" in slot_texts[
        "condition_modal_bridge_signature"
    ]
    assert "dynamic:[a]:after" in slot_texts["condition_modal_bridge_signature"]
    assert "temporal->temporal" in slot_texts["condition_modal_bridge_family_pair"]
    assert "temporal->conditional_normative" in slot_texts[
        "condition_modal_bridge_family_pair"
    ]
    assert "temporal->dynamic" in slot_texts["condition_modal_bridge_family_pair"]
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "conditional_normative:O|:after"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "dynamic:[a]:after"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_operator_pair_keys_for_temporal_conditional_bridges() -> None:
    source_id = "us-code-42-7385x-operator-pair-conditional"
    source_text = "If a transfer occurs, benefits follow."
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="temporal",
            system="ltl",
            symbol="X",
            label="next",
        ),
        predicate=ModalIRPredicate(name="follow_benefits"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="42 U.S.C. 7385x",
        ),
        conditions=["if a transfer occurs"],
        metadata={"cue": "after"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "X->O|" in slot_texts["condition_modal_registry_operator_pair"]
    assert "x_to_o_pipe" in slot_texts["condition_modal_registry_operator_pair_key"]
    assert "x_to_o_pipe" in slot_texts["condition_modal_bridge_operator_pair_key"]
    assert any(
        triple["predicate"] == "condition_modal_registry_operator_pair_key"
        and triple["object"] == "x_to_o_pipe"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_modal_bridge_operator_pair_key"
        and triple["object"] == "x_to_o_pipe"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_operator_pair_keys_for_temporal_deontic_bridges() -> None:
    source_id = "us-code-42-7385y-operator-pair-deontic"
    source_text = "Required transfer follows."
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="temporal",
            system="ltl",
            symbol="X",
            label="next",
        ),
        predicate=ModalIRPredicate(name="required_transfer_follows"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="42 U.S.C. 7385y",
        ),
        metadata={"cue": "after"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "required" in slot_texts["bridge_cue"]
    assert "X->O" in slot_texts["bridge_modal_bridge_operator_pair"]
    assert "x_to_o" in slot_texts["bridge_modal_bridge_operator_pair_key"]
    assert any(
        triple["predicate"] == "bridge_modal_bridge_operator_pair_key"
        and triple["object"] == "x_to_o"
        for triple in triples
    )


def test_modal_decompiler_and_triples_reinforce_deontic_bridge_for_temporal_condition_cues() -> None:
    source_id = "us-code-42-7385t-90217fde9b59d41a"
    source_text = "After transfer, the Secretary shall pay benefits."
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="shall_pay_benefits"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="42 U.S.C. 7385t",
        ),
        conditions=["after transfer"],
        metadata={"cue": "shall"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "after" in slot_texts["condition_prefix_key"]
    assert "deontic:O:after" in slot_texts["condition_modal_bridge_signature"]
    assert "deontic->deontic" in slot_texts["condition_modal_bridge_family_pair"]
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "deontic:O:after"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_deontic_epistemic_bridge_for_believed_cues() -> None:
    source_id = "us-code-42-2000dd-bridge-believed-8fcb91f1595a3cde"
    source_text = (
        "A person may be penalized if the agency believed the report was false."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="P",
            label="permitted",
        ),
        predicate=ModalIRPredicate(name="may_penalize_person"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="42 U.S.C. 2000dd",
        ),
        conditions=["if the agency believed the report was false"],
        metadata={"cue": "may"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "deontic:P:may" in slot_texts["cue_modal_bridge_signature"]
    assert "believed" in slot_texts["bridge_cue"]
    assert "epistemic:K:believed" in slot_texts["bridge_modal_bridge_signature"]
    assert "doxastic:B:believed" in slot_texts["bridge_modal_bridge_signature"]
    assert "deontic->epistemic" in slot_texts["bridge_modal_bridge_family_pair"]
    assert any(
        triple["predicate"] == "cue_modal_bridge_signature"
        and triple["object"] == "deontic:P:may"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "bridge_modal_bridge_signature"
        and triple["object"] == "epistemic:K:believed"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "bridge_modal_bridge_signature"
        and triple["object"] == "doxastic:B:believed"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_subject_to_frame_and_scope_bridge_slots() -> None:
    source_id = "us-code-6-314-a0a9a6dc41d25a7f"
    source_text = (
        "The Secretary shall award grants for fiscal year 2027 subject to the Secretary "
        "determines that compliance is adequate."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="shall_award_grants_for_fiscal_year"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="6 U.S.C. 314",
        ),
        conditions=["subject to the secretary determines that compliance is adequate"],
        metadata={"cue": "shall"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "subject_to" in slot_texts["condition_prefix_key"]
    assert "frame:Frame:subject_to" in slot_texts["condition_modal_bridge_signature"]
    assert slot_texts["condition_scope_content"] == [
        "secretary determines that compliance is adequate"
    ]
    assert slot_texts["condition_scope_content_token_prefix"] == ["secretary"]
    assert "fiscal_year" in slot_texts["bridge_cue"]
    assert "determines" in slot_texts["bridge_cue"]
    assert "temporal:F:fiscal_year" in slot_texts["bridge_modal_bridge_signature"]
    assert "epistemic:K:determines" in slot_texts["bridge_modal_bridge_signature"]
    assert "doxastic:B:determines" in slot_texts["bridge_modal_bridge_signature"]
    assert "deontic->temporal" in slot_texts[
        "predicate_refined_temporal_bridge_family_pair"
    ]
    assert "temporal:F:shall" in slot_texts[
        "predicate_refined_temporal_bridge_signature"
    ]
    assert "fiscal_year" in slot_texts["predicate_refined_temporal_bridge_context"]
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "frame:Frame:subject_to"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_scope_content"
        and triple["object"] == "secretary determines that compliance is adequate"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "bridge_modal_bridge_signature"
        and triple["object"] == "temporal:F:fiscal_year"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "bridge_modal_bridge_signature"
        and triple["object"] == "epistemic:K:determines"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "bridge_modal_bridge_signature"
        and triple["object"] == "doxastic:B:determines"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "predicate_refined_temporal_bridge_family_pair"
        and triple["object"] == "deontic->temporal"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "predicate_refined_temporal_bridge_context"
        and triple["object"] == "fiscal_year"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_frame_to_temporal_snapshot_bridge_slots() -> None:
    source_id = "us-code-12-630-frame-to-temporal-bridge"
    source_text = (
        "U.S.C. Title 12 - BANKS AND BANKING 12 U.S.C. United States Code, 2024 Edition "
        "Title 12 - BANKS AND BANKING CHAPTER 6 - FOREIGN BANKING."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="frame",
            system="frame_bm25",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(name="title_12_2024_edition_chapter_6_scope"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="12 U.S.C. 630",
        ),
        metadata={"cue": "__uscode_residual_span_fallback__"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "frame->temporal" in slot_texts[
        "predicate_refined_temporal_bridge_family_pair"
    ]
    assert "temporal:F:title" in slot_texts["predicate_refined_temporal_bridge_signature"]
    assert "edition_year" in slot_texts["predicate_refined_temporal_bridge_context"]
    assert any(
        triple["predicate"] == "predicate_refined_temporal_bridge_family_pair"
        and triple["object"] == "frame->temporal"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "predicate_refined_temporal_bridge_context"
        and triple["object"] == "edition_year"
        for triple in triples
    )


def test_modal_decompiler_surfaces_frame_to_alethic_scope_bridge_slots() -> None:
    source_id = "us-code-29-3221-frame-to-alethic-bridge"
    source_text = (
        "Sec. 3221 - Native American programs. The program plan includes "
        "services necessary to carry out this section."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="frame",
            system="frame_bm25",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(name="native_american_programs_section_scope"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="29 U.S.C. 3221",
        ),
        metadata={"cue": "__uscode_section_heading_fallback__"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert "frame->alethic" in slot_texts["typed_decompiler_family_pair"]
    assert "frame->alethic" in slot_texts[
        "modal_source_span_typed_decompiler_family_pair"
    ]
    assert "frame->alethic" in slot_texts[
        "modal_source_span_refined_modal_family_pair"
    ]
    assert "alethic:□:necessary" in slot_texts[
        "modal_source_span_refined_modal_bridge_signature"
    ]


def test_modal_decompiler_surfaces_frame_residual_clause_family_pair_cues() -> None:
    source_id = "us-code-36-152701-frame-residual-clause"
    source_text = (
        "Sec. 152701 - Charter. This clause applies to the organization "
        "under this chapter."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="frame",
            system="frame_bm25",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(name="clause"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="36 U.S.C. 152701",
        ),
        metadata={
            "cue": "__uscode_residual_span_fallback__",
            "fallback_rule": "uscode_residual_span_coverage_v1",
        },
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert "frame->conditional_normative" in slot_texts[
        "typed_decompiler_family_pair"
    ]
    assert "frame->epistemic" in slot_texts["typed_decompiler_family_pair"]
    assert "frame->conditional_normative:clause" in slot_texts[
        "typed_decompiler_family_pair_cue"
    ]
    assert "frame->epistemic:clause" in slot_texts[
        "typed_decompiler_family_pair_cue"
    ]
    assert "frame->conditional_normative:uscode_residual_span_fallback" in slot_texts[
        "typed_decompiler_family_pair_cue"
    ]
    assert "frame->epistemic:uscode_residual_span_coverage_v1" in slot_texts[
        "typed_decompiler_family_pair_cue"
    ]


def test_modal_decompiler_surfaces_deontic_to_temporal_snapshot_bridge_slots() -> None:
    source_id = "us-code-25-155-deontic-to-temporal-bridge"
    source_text = (
        "U.S.C. Title 25 - INDIANS 25 U.S.C. United States Code, 2024 Edition "
        "Title 25 - INDIANS CHAPTER 4 - PERFORMANCE BY UNITED STATES OF "
        "OBLIGATIONS TO INDIANS SUBCHAPTER III - DEPOSIT, CARE, AND INVESTMENT "
        "OF INDIAN MONEYS Sec. 155 - Disposal of funds."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="temporal",
            system="LTL",
            symbol="F",
            label="eventually",
        ),
        predicate=ModalIRPredicate(
            name="united_states_of_obligations_to_indians",
            role="clause",
        ),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="25 U.S.C. 155",
        ),
        metadata={"cue": "by"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert "deontic->temporal" in slot_texts[
        "modal_source_span_refined_temporal_bridge_family_pair"
    ]
    assert "temporal:F:obligation" in slot_texts[
        "modal_source_span_refined_temporal_bridge_signature"
    ]
    assert "edition_year" in slot_texts[
        "modal_source_span_refined_temporal_bridge_context"
    ]


def test_modal_decompiler_and_triples_surface_subject_to_section_specific_bridge_slots() -> None:
    source_id = "us-code-6-314-subject-to-section"
    source_text = (
        "The Secretary shall provide notice subject to section 314 of this title."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="shall_provide_notice"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="6 U.S.C. 314",
        ),
        conditions=["subject to section 314 of this title"],
        metadata={"cue": "shall"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert slot_texts["condition_prefix_key"] == ["subject_to_section"]
    assert slot_texts["condition_modal_signature"] == [
        "deontic:O:subject_to_section"
    ]
    assert slot_texts["condition_modal_bridge_signature"] == [
        "conditional_normative:O|:subject_to_section",
        "frame:Frame:subject_to_section",
    ]
    assert "subject_to_section" in slot_texts["bridge_cue"]
    assert any(
        triple["predicate"] == "condition_prefix_key"
        and triple["object"] == "subject_to_section"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "conditional_normative:O|:subject_to_section"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "frame:Frame:subject_to_section"
        for triple in triples
    )


def test_modal_decompiler_inferred_frame_condition_surfaces_conditional_bridge_slots() -> None:
    source_id = "us-code-29-1400-frame-conditional-scope"
    source_text = (
        "The multiemployer plan provision is subject to section 1401 of this title."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="frame",
            system="flogic",
            symbol="Frame",
            label="frame",
        ),
        predicate=ModalIRPredicate(name="multiemployer_plan_provision"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="29 U.S.C. 1400",
        ),
        metadata={"cue": "section"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_texts["condition_prefix_key"] == ["subject_to_section"]
    assert "subject_to_section" in slot_texts["bridge_cue"]
    assert "frame->conditional_normative" in slot_texts[
        "condition_modal_bridge_family_pair"
    ]
    assert "conditional_normative:O|:subject_to_section" in slot_texts[
        "condition_modal_bridge_signature"
    ]
    assert "frame->conditional_normative" in slot_texts[
        "bridge_modal_bridge_family_pair"
    ]


def test_modal_decompiler_and_triples_surface_in_accordance_with_bridge_slots() -> None:
    source_id = "us-code-42-12835.-efafc5db287e34c3"
    source_text = (
        "The Secretary shall ensure compliance in accordance with section 12707 "
        "of this title."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="temporal",
            system="ltl",
            symbol="F",
            label="eventually",
        ),
        predicate=ModalIRPredicate(name="ensure_compliance"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="42 U.S.C. 12835.",
        ),
        conditions=["in accordance with section 12707 of this title"],
        metadata={"cue": "shall"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "in_accordance_with" in slot_texts["condition_prefix_key"]
    assert "in_accordance_with" in slot_texts["bridge_cue"]
    assert "conditional_normative:O|:in_accordance_with" in slot_texts[
        "condition_modal_bridge_signature"
    ]
    assert "deontic:O:in_accordance_with" in slot_texts[
        "condition_modal_bridge_signature"
    ]
    assert "frame:Frame:in_accordance_with" in slot_texts[
        "condition_modal_bridge_signature"
    ]
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "frame:Frame:in_accordance_with"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "bridge_modal_bridge_signature"
        and triple["object"] == "conditional_normative:O|:in_accordance_with"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "deontic:O:in_accordance_with"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_as_described_in_bridge_slots() -> None:
    source_id = "us-code-5-552-as-described-bridge"
    source_text = "The agency shall comply as described in section 552(a)(1)."
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="shall_comply"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="5 U.S.C. 552",
        ),
        conditions=["as described in section 552(a)(1)"],
        metadata={"cue": "shall"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "as_described_in" in slot_texts["condition_prefix_key"]
    assert "section 552(a)(1)" in slot_texts["condition_scope"]
    assert "as_described_in" in slot_texts["bridge_cue"]
    assert "conditional_normative:O|:as_described_in" in slot_texts[
        "condition_modal_bridge_signature"
    ]
    assert "frame:Frame:as_described_in" in slot_texts["condition_modal_bridge_signature"]
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "conditional_normative:O|:as_described_in"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "frame:Frame:as_described_in"
        for triple in triples
    )


def test_modal_decompiler_and_triples_infer_condition_slots_from_source_span_when_missing() -> None:
    source_id = "us-code-42-5189h-inferred-condition"
    source_text = (
        "Not later than 5 days after an award of a public assistance grant is made under "
        "section 5172, the Administrator shall post notice."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="post_notice"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="42 U.S.C. 5189h",
        ),
        metadata={"cue": "shall"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "made" in slot_texts["condition_scope_token"]
    assert "after" in slot_texts["condition_prefix_key"]
    assert "deontic->conditional_normative" in slot_texts[
        "condition_modal_bridge_family_pair"
    ]
    assert any(
        triple["predicate"] == "condition_scope_token"
        and triple["object"] == "made"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_modal_bridge_family_pair"
        and triple["object"] == "deontic->conditional_normative"
        for triple in triples
    )


def test_modal_decompiler_surfaces_suspension_as_deontic_dynamic_bridge() -> None:
    source_id = "us-code-15-1693j-48f8e1ec46a9aac8"
    source_text = (
        "15 U.S.C. 1693j: U.S.C. Title 15 - COMMERCE AND TRADE "
        "Sec. 1693j - Suspension of obligations From the U.S. Government "
        "Publishing Office, www.gpo.gov."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="suspension_of_obligations", role="clause"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="15 U.S.C. 1693j",
        ),
        metadata={"cue": "obligations"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert "deontic->dynamic" in slot_texts["bridge_modal_bridge_family_pair"]
    assert "deontic->dynamic" in slot_texts[
        "modal_source_span_typed_decompiler_family_pair"
    ]
    assert "dynamic:[a]:suspension" in slot_texts[
        "modal_source_span_refined_modal_bridge_signature"
    ]


def test_modal_decompiler_and_triples_prefer_longest_condition_prefix_match() -> None:
    source_id = "us-code-5-552-longest-prefix"
    source_text = (
        "The agency shall provide records to the extent provided in section 552(a)(1)."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="shall_provide_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="5 U.S.C. 552",
        ),
        conditions=["to the extent provided in section 552(a)(1)"],
        metadata={"cue": "shall"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "to_the_extent_provided" in slot_texts["condition_prefix_key"]
    assert slot_texts["condition_to_the_extent_provided"] == ["in section 552(a)(1)"]
    assert "deontic:O:to_the_extent_provided" in slot_texts["condition_modal_signature"]
    assert "conditional_normative:O|:to_the_extent_provided" in slot_texts[
        "condition_modal_bridge_signature"
    ]
    assert any(
        triple["predicate"] == "condition_prefix_key"
        and triple["object"] == "to_the_extent_provided"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_to_the_extent_provided"
        and triple["object"] == "in section 552(a)(1)"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "condition_modal_bridge_signature"
        and triple["object"] == "conditional_normative:O|:to_the_extent_provided"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_authority_and_required_bridge_cues() -> None:
    source_id = "us-code-16-580f-d159c17cca2fb07b"
    source_text = (
        "Transfer authority is required for approval by the Secretary."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="temporal",
            system="ltl",
            symbol="F",
            label="eventually",
        ),
        predicate=ModalIRPredicate(name="transfer_authority_for_approval"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="16 U.S.C. 580f",
        ),
        conditions=["required for approval"],
        metadata={"cue": "authority"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "authority" in slot_texts["cue"]
    assert "frame:Frame:authority" in slot_texts["cue_modal_bridge_signature"]
    assert "required" in slot_texts["bridge_cue"]
    assert "deontic:O:required" in slot_texts["bridge_modal_bridge_signature"]
    assert any(
        triple["predicate"] == "cue_modal_bridge_signature"
        and triple["object"] == "frame:Frame:authority"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "bridge_modal_bridge_signature"
        and triple["object"] == "deontic:O:required"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_inflected_bridge_cue_variants() -> None:
    source_id = "us-code-34-50502-aa628c288d18dc00"
    source_text = (
        "Provided that the authority determine eligibility, the agency requires "
        "action on the effective dates."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="conditional_normative",
            system="kd",
            symbol="O|",
            label="conditional_obligation",
        ),
        predicate=ModalIRPredicate(
            name="determine_eligibility_requires_action_on_effective_dates"
        ),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="34 U.S.C. 50502",
        ),
        conditions=["provided that the authority determine eligibility"],
        metadata={"cue": "provided that"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "determine" in slot_texts["bridge_cue"]
    assert "requires" in slot_texts["bridge_cue"]
    assert "effective_dates" in slot_texts["bridge_cue"]
    assert "epistemic:K:determine" in slot_texts["bridge_modal_bridge_signature"]
    assert "doxastic:B:determine" in slot_texts["bridge_modal_bridge_signature"]
    assert "deontic:O:requires" in slot_texts["bridge_modal_bridge_signature"]
    assert "temporal:F:effective_dates" in slot_texts["bridge_modal_bridge_signature"]
    assert any(
        triple["predicate"] == "bridge_modal_bridge_signature"
        and triple["object"] == "epistemic:K:determine"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "bridge_modal_bridge_signature"
        and triple["object"] == "deontic:O:requires"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "bridge_modal_bridge_signature"
        and triple["object"] == "temporal:F:effective_dates"
        for triple in triples
    )


def test_modal_decompiler_and_triples_bridge_epistemic_determinations_to_deontic_slots() -> None:
    source_id = "us-code-15-78j-1-fa54b11a0d51e53f"
    source_text = (
        "If the Commission determines that an issuer failed to comply, the "
        "issuer shall retain audit records."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="epistemic",
            system="s5",
            symbol="K",
            label="known",
        ),
        predicate=ModalIRPredicate(
            name="determine_issuer_compliance",
            arguments=["issuer shall retain audit records"],
            role="clause",
        ),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="15 U.S.C. 78j-1",
        ),
        conditions=["if the Commission determines that an issuer failed to comply"],
        metadata={"cue": "determines"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))
    triples = modal_ir_to_flogic_triples(document)

    assert "epistemic->deontic" in slot_texts["cue_modal_bridge_family_pair"]
    assert "epistemic_deontic" in slot_texts["cue_modal_bridge_family_pair_key"]
    assert "deontic:O:determines" in slot_texts["cue_modal_bridge_signature"]
    assert "epistemic->deontic" in slot_texts["typed_decompiler_family_pair"]
    assert any(
        triple["predicate"] == "cue_modal_bridge_family_pair"
        and triple["object"] == "epistemic->deontic"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "cue_modal_bridge_family_pair_key"
        and triple["object"] == "epistemic_deontic"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_predicate_and_argument_contextual_bridge_slots() -> None:
    source_id = "us-code-43-1467a-49e61664c350948a"
    source_text = (
        "The Secretary must issue refunds on and after October 11, 2000, "
        "in accordance with section 552, and on or after approval."
    )
    formula = ModalIRFormula(
        formula_id=f"{source_id}:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(
            name="must_issue_refunds_on_and_after_effective_dates",
            arguments=[
                "scope:in_accordance_with_section_552",
                "timing:on_or_after_approval",
            ],
        ),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(source_text),
            citation="43 U.S.C. 1467a",
        ),
        metadata={"cue": "must"},
    )
    document = ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "temporal:F:on_and_after" in slot_texts["predicate_modal_bridge_signature"]
    assert "temporal:F:effective_dates" in slot_texts["predicate_modal_bridge_signature"]
    assert "temporal:F:on_or_after" in slot_texts["argument_modal_bridge_signature"]
    assert "frame:Frame:in_accordance_with" in slot_texts[
        "argument_modal_bridge_signature"
    ]
    assert "conditional_normative:O|:in_accordance_with" in slot_texts[
        "argument_modal_bridge_signature"
    ]
    assert any(
        triple["predicate"] == "predicate_modal_bridge_signature"
        and triple["object"] == "temporal:F:on_and_after"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "argument_modal_bridge_signature"
        and triple["object"] == "frame:Frame:in_accordance_with"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "argument_modal_bridge_signature"
        and triple["object"] == "temporal:F:on_or_after"
        for triple in triples
    )


def test_modal_decompiler_surfaces_metadata_citation_slots_without_formulas() -> None:
    document = ModalIRDocument(
        document_id="metadata-citation-only-doc",
        source="us_code",
        normalized_text="Editorial Notes.",
        metadata={"citation": "45 U.S.C. 431 to 447."},
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert slot_texts["citation"] == ["45 U.S.C. 431 to 447."]
    assert slot_texts["citation_canonical"] == ["45 U.S.C. 431 to 447"]
    assert slot_texts["citation_title"] == ["45"]
    assert slot_texts["citation_section"] == ["431 to 447"]
    assert slot_texts["citation_section_range"] == ["431 to 447"]
    assert slot_texts["citation_section_range_start"] == ["431"]
    assert slot_texts["citation_section_range_end"] == ["447"]
    assert slot_texts["citation_section_range_connector"] == ["to"]
    assert slot_texts["citation_section_component_profile"] == ["range"]
    assert any(
        triple["predicate"] == "citation_section_range"
        and triple["object"] == "431 to 447"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_component_profile"
        and triple["object"] == "range"
        for triple in triples
    )


def test_modal_decompiler_and_triples_expand_alphanumeric_citation_section_slots() -> None:
    formula = ModalIRFormula(
        formula_id="citation-shape-doc:f0001",
        operator=ModalIROperator(
            family="frame",
            system="F",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(
            name="section_heading_example",
            role="frame",
        ),
        provenance=ModalIRProvenance(
            source_id="citation-shape-doc",
            start_char=0,
            end_char=28,
            citation="2 U.S.C. 31a-2b",
        ),
        metadata={"fallback_rule": "uscode_section_heading_v1"},
    )
    secondary_formula = ModalIRFormula(
        formula_id="citation-shape-doc:f0002",
        operator=ModalIROperator(
            family="frame",
            system="F",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(
            name="section_heading_example_two",
            role="frame",
        ),
        provenance=ModalIRProvenance(
            source_id="citation-shape-doc",
            start_char=29,
            end_char=57,
            citation="26 U.S.C. 6050K",
        ),
        metadata={"fallback_rule": "uscode_section_heading_v1"},
    )
    tertiary_formula = ModalIRFormula(
        formula_id="citation-shape-doc:f0003",
        operator=ModalIROperator(
            family="frame",
            system="F",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(
            name="section_heading_example_three",
            role="frame",
        ),
        provenance=ModalIRProvenance(
            source_id="citation-shape-doc",
            start_char=58,
            end_char=84,
            citation="51 U.S.C. 60604.",
        ),
        metadata={"fallback_rule": "uscode_section_heading_v1"},
    )
    document = ModalIRDocument(
        document_id="citation-shape-doc",
        source="us_code",
        normalized_text=(
            "Sec. 31a-2b. Example heading. "
            "Sec. 6050K. Another heading. "
            "Sec. 60604. Final heading."
        ),
        formulas=[formula, secondary_formula, tertiary_formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "31a-2b" in slot_texts["citation_section"]
    assert "6050K" in slot_texts["citation_section"]
    assert "60604" in slot_texts["citation_section"]
    assert "2 U.S.C. 31a-2b" in slot_texts["citation_canonical"]
    assert "26 U.S.C. 6050K" in slot_texts["citation_canonical"]
    assert "51 U.S.C. 60604" in slot_texts["citation_canonical"]
    assert "60604." in slot_texts["citation_section_raw"]
    assert "60604" in slot_texts["citation_section_normalized"]
    assert slot_texts["citation_section_trailing_punct"] == ["."]
    assert slot_texts["citation_section_has_trailing_punct"] == ["false", "true"]
    assert slot_texts["citation_section_trailing_punct_count"] == ["0", "1"]
    assert slot_texts["citation_section_trailing_punct_kind"] == ["dot"]
    assert "31a" in slot_texts["citation_section_primary"]
    assert "6050K" in slot_texts["citation_section_primary"]
    assert "2" in slot_texts["citation_section_component_count"]
    assert "1" in slot_texts["citation_section_component_count"]
    assert "31a" in slot_texts["citation_section_component"]
    assert "2b" in slot_texts["citation_section_component"]
    assert "6050K" in slot_texts["citation_section_component"]
    assert "31" in slot_texts["citation_section_number"]
    assert "2" in slot_texts["citation_section_number"]
    assert "6050" in slot_texts["citation_section_number"]
    assert "a" in slot_texts["citation_section_suffix"]
    assert "b" in slot_texts["citation_section_suffix"]
    assert "K" in slot_texts["citation_section_suffix"]
    assert "a" in slot_texts["citation_section_suffix_normalized"]
    assert "b" in slot_texts["citation_section_suffix_normalized"]
    assert "k" in slot_texts["citation_section_suffix_normalized"]
    assert "lower" in slot_texts["citation_section_suffix_case"]
    assert "upper" in slot_texts["citation_section_suffix_case"]
    assert "1:lower" in slot_texts["citation_section_suffix_case_positioned"]
    assert "2:lower" in slot_texts["citation_section_suffix_case_positioned"]
    assert "1:upper" in slot_texts["citation_section_suffix_case_positioned"]
    assert "2" in slot_texts["citation_section_token_count"]
    assert "1" in slot_texts["citation_section_token_count"]
    assert "31a" in slot_texts["citation_section_token_prefix"]
    assert "6050k" in slot_texts["citation_section_token_prefix"]
    assert "2b" in slot_texts["citation_section_token_suffix"]
    assert "6050k" in slot_texts["citation_section_token_suffix"]
    assert "31a_2b" in slot_texts["citation_section_stem"]
    assert "6050k" in slot_texts["citation_section_stem"]
    assert "NA-NA" in slot_texts["citation_section_shape"]
    assert "NA" in slot_texts["citation_section_shape"]
    assert "N" in slot_texts["citation_section_shape"]
    assert slot_texts["citation_section_numeric_component_count"] == ["2", "1"]
    assert slot_texts["citation_section_suffix_component_count"] == ["2", "1", "0"]
    assert "alphanumeric" in slot_texts["citation_section_component_kind"]
    assert "numeric" in slot_texts["citation_section_component_kind"]
    assert "2" in slot_texts["citation_section_number_digit_count"]
    assert "1" in slot_texts["citation_section_number_digit_count"]
    assert "4" in slot_texts["citation_section_number_digit_count"]
    assert "5" in slot_texts["citation_section_number_digit_count"]
    assert any(
        triple["predicate"] == "citation_section_component"
        and triple["object"] == "2b"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_suffix"
        and triple["object"] == "K"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_suffix_normalized"
        and triple["object"] == "k"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_suffix_case"
        and triple["object"] == "upper"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_suffix_case_positioned"
        and triple["object"] == "1:upper"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_token_suffix"
        and triple["object"] == "6050k"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_raw"
        and triple["object"] == "60604."
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_trailing_punct"
        and triple["object"] == "."
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_has_trailing_punct"
        and triple["object"] == "true"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_has_trailing_punct"
        and triple["object"] == "false"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_trailing_punct_count"
        and triple["object"] == "1"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_trailing_punct_count"
        and triple["object"] == "0"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_trailing_punct_kind"
        and triple["object"] == "dot"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_canonical"
        and triple["object"] == "51 U.S.C. 60604"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_shape"
        and triple["object"] == "NA-NA"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "citation_section_number_digit_count"
        and triple["object"] == "5"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_uscode_source_id_slots() -> None:
    primary_source_id = "us-code-42-10145.-cdf17e327d28e2de"
    secondary_source_id = "us-code-42-2000e-87b0a223ec2f555f"
    formula = ModalIRFormula(
        formula_id="source-id-doc:f0001",
        operator=ModalIROperator(
            family="frame",
            system="F",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(
            name="section_heading_example",
            role="frame",
        ),
        provenance=ModalIRProvenance(
            source_id=primary_source_id,
            start_char=0,
            end_char=16,
            citation=None,
        ),
        metadata={"fallback_rule": "uscode_section_heading_v1"},
    )
    secondary_formula = ModalIRFormula(
        formula_id="source-id-doc:f0002",
        operator=ModalIROperator(
            family="frame",
            system="F",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(
            name="section_heading_example_two",
            role="frame",
        ),
        provenance=ModalIRProvenance(
            source_id=secondary_source_id,
            start_char=17,
            end_char=38,
            citation=None,
        ),
        metadata={"fallback_rule": "uscode_section_heading_v1"},
    )
    document = ModalIRDocument(
        document_id=primary_source_id,
        source="us_code",
        normalized_text="Sec. 10145. Repealed. Sec. 2000e. Definitions.",
        formulas=[formula, secondary_formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert slot_texts["source_id_scheme"] == ["us-code"]
    assert slot_texts["source_id_title"] == ["42"]
    assert slot_texts["source_id_title_number"] == ["42"]
    assert "10145." in slot_texts["source_id_section"]
    assert "2000e" in slot_texts["source_id_section"]
    assert "42 U.S.C. 10145" in slot_texts["source_id_citation_canonical"]
    assert "42 U.S.C. 2000e" in slot_texts["source_id_citation_canonical"]
    assert "10145" in slot_texts["source_id_section_normalized"]
    assert slot_texts["source_id_section_trailing_punct"] == ["."]
    assert slot_texts["source_id_section_has_trailing_punct"] == ["true", "false"]
    assert slot_texts["source_id_section_trailing_punct_count"] == ["1", "0"]
    assert slot_texts["source_id_section_trailing_punct_kind"] == ["dot"]
    assert "10145" in slot_texts["source_id_section_primary"]
    assert "2000e" in slot_texts["source_id_section_primary"]
    assert "10145" in slot_texts["source_id_section_number"]
    assert "2000" in slot_texts["source_id_section_number"]
    assert "e" in slot_texts["source_id_section_suffix"]
    assert slot_texts["source_id_section_suffix_normalized"] == ["e"]
    assert slot_texts["source_id_section_suffix_case"] == ["lower"]
    assert slot_texts["source_id_section_suffix_case_positioned"] == ["1:lower"]
    assert slot_texts["source_id_section_shape"] == ["N", "NA"]
    assert slot_texts["source_id_section_numeric_component_count"] == ["1"]
    assert slot_texts["source_id_section_suffix_component_count"] == ["0", "1"]
    assert "numeric" in slot_texts["source_id_section_component_kind"]
    assert "alphanumeric" in slot_texts["source_id_section_component_kind"]
    assert "5" in slot_texts["source_id_section_number_digit_count"]
    assert "4" in slot_texts["source_id_section_number_digit_count"]
    assert "cdf17e327d28e2de" in slot_texts["source_id_digest"]
    assert "87b0a223ec2f555f" in slot_texts["source_id_digest"]
    assert any(
        triple["predicate"] == "source_id_section"
        and triple["object"] == "10145."
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_normalized"
        and triple["object"] == "10145"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_trailing_punct"
        and triple["object"] == "."
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_has_trailing_punct"
        and triple["object"] == "true"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_has_trailing_punct"
        and triple["object"] == "false"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_trailing_punct_count"
        and triple["object"] == "1"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_trailing_punct_count"
        and triple["object"] == "0"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_trailing_punct_kind"
        and triple["object"] == "dot"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_suffix"
        and triple["object"] == "e"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_suffix_normalized"
        and triple["object"] == "e"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_suffix_case"
        and triple["object"] == "lower"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_suffix_case_positioned"
        and triple["object"] == "1:lower"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_citation_canonical"
        and triple["object"] == "42 U.S.C. 10145"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_shape"
        and triple["object"] == "NA"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_section_suffix_component_count"
        and triple["object"] == "1"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "source_id_digest"
        and triple["object"] == "87b0a223ec2f555f"
        for triple in triples
    )


def test_modal_flogic_triples_and_decompiler_slots_include_typed_predicate_arguments() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide written notice within 30 days.",
        document_id="typed-argument-doc",
        citation="5 U.S.C. 552",
        source="us_code",
    )

    slot_texts = decoded_modal_phrase_slot_text_map(result.decoded_modal_text)

    assert "argument" in slot_texts
    assert any(text.startswith("actor:") for text in slot_texts["argument"])
    assert any(text.startswith("scope:") for text in slot_texts["argument"])
    assert "argument_actor" in slot_texts
    assert "argument_scope" in slot_texts
    assert any(
        triple["predicate"] == "predicate_argument"
        and triple["object"].startswith("actor:")
        for triple in result.kg_triples
    )
    assert any(
        triple["predicate"] == "predicate_argument_actor"
        for triple in result.kg_triples
    )
    assert any(
        triple["predicate"] == "predicate_argument_scope"
        for triple in result.kg_triples
    )
    assert any(
        triple["predicate"] == "modal_cue"
        for triple in result.kg_triples
    )


def test_modal_decompiler_and_triples_include_statutory_scope_reference_slots() -> None:
    formula = ModalIRFormula(
        formula_id="statutory-doc:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="D",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(
            name="must_under_this_section_provide_notice",
            arguments=[
                "scope:pursuant_to_subsection_(b)",
                "authority:as_provided_in_paragraph_(1)",
            ],
            role="clause",
        ),
        provenance=ModalIRProvenance(
            source_id="statutory-doc",
            start_char=0,
            end_char=86,
            citation="5 U.S.C. 552",
        ),
        conditions=["under section 552(a)(1)"],
    )
    document = ModalIRDocument(
        document_id="statutory-doc",
        source="us_code",
        normalized_text="The agency must under this section provide notice.",
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "under this section" in slot_texts["statutory_scope_reference"]
    assert "pursuant to subsection (b)" in slot_texts["statutory_scope_reference"]
    assert "as provided in paragraph (1)" in slot_texts["statutory_scope_reference"]
    assert "under section 552(a)(1)" in slot_texts["statutory_scope_reference"]
    assert slot_texts["statutory_scope_connector"] == [
        "under",
        "pursuant to",
        "as provided in",
    ]
    assert slot_texts["statutory_scope_unit"] == [
        "section",
        "subsection",
        "paragraph",
    ]
    assert slot_texts["statutory_scope_target"] == ["this", "(b)", "(1)", "552(a)(1)"]
    assert slot_texts["predicate_token_count"] == ["6"]
    assert slot_texts["predicate_token_prefix"] == ["must"]
    assert slot_texts["predicate_token_suffix"] == ["notice"]
    assert slot_texts["predicate_stem"] == ["must_under_this_section_provide_notice"]
    assert "section" in slot_texts["predicate_token"]
    assert any(
        triple["predicate"] == "statutory_scope_reference"
        and triple["object"] == "under this section"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "statutory_scope_reference"
        and triple["object"] == "pursuant to subsection (b)"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "statutory_scope_connector"
        and triple["object"] == "as provided in"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "statutory_scope_unit"
        and triple["object"] == "paragraph"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "statutory_scope_target"
        and triple["object"] == "552(a)(1)"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "predicate_token_suffix"
        and triple["object"] == "notice"
        for triple in triples
    )


def test_modal_decompiler_and_triples_expand_statutory_scope_units_and_connectors() -> None:
    formula = ModalIRFormula(
        formula_id="statutory-extended-doc:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="D",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(
            name="must_within_subchapter_ii_comply",
            arguments=[
                "scope:in_part_a",
                "authority:under_this_subchapter_ii",
                "cross_ref:as_provided_in_sections_552(a)(1)",
            ],
            role="clause",
        ),
        provenance=ModalIRProvenance(
            source_id="statutory-extended-doc",
            start_char=0,
            end_char=112,
            citation="5 U.S.C. 552",
        ),
        conditions=["under clause (i)"],
        exceptions=["pursuant to subclause (ii)"],
    )
    document = ModalIRDocument(
        document_id="statutory-extended-doc",
        source="us_code",
        normalized_text="The agency must within subchapter II comply.",
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "within subchapter ii" in slot_texts["statutory_scope_reference"]
    assert "in part a" in slot_texts["statutory_scope_reference"]
    assert "under this subchapter ii" in slot_texts["statutory_scope_reference"]
    assert "as provided in sections 552(a)(1)" in slot_texts["statutory_scope_reference"]
    assert "under clause (i)" in slot_texts["statutory_scope_reference"]
    assert "pursuant to subclause (ii)" in slot_texts["statutory_scope_reference"]
    assert "within" in slot_texts["statutory_scope_connector"]
    assert "in" in slot_texts["statutory_scope_connector"]
    assert "subchapter" in slot_texts["statutory_scope_unit"]
    assert "part" in slot_texts["statutory_scope_unit"]
    assert "section" in slot_texts["statutory_scope_unit"]
    assert "clause" in slot_texts["statutory_scope_unit"]
    assert "subclause" in slot_texts["statutory_scope_unit"]
    assert "ii" in slot_texts["statutory_scope_target"]
    assert "this ii" in slot_texts["statutory_scope_target"]
    assert "a" in slot_texts["statutory_scope_target"]
    assert "552(a)(1)" in slot_texts["statutory_scope_target"]
    assert "(i)" in slot_texts["statutory_scope_target"]
    assert "(ii)" in slot_texts["statutory_scope_target"]
    assert any(
        triple["predicate"] == "statutory_scope_reference"
        and triple["object"] == "as provided in sections 552(a)(1)"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "statutory_scope_connector"
        and triple["object"] == "within"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "statutory_scope_unit"
        and triple["object"] == "subclause"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "statutory_scope_target"
        and triple["object"] == "this ii"
        for triple in triples
    )


def test_modal_decompiler_and_triples_capture_extended_statutory_scope_connectors() -> None:
    formula = ModalIRFormula(
        formula_id="statutory-connector-doc:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="D",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(
            name="must_as_described_in_section_552(a)(1)_comply",
            arguments=[
                "authority:as_defined_in_subsection_(b)",
                "cross_ref:referred_to_in_paragraph_(1)",
            ],
            role="clause",
        ),
        provenance=ModalIRProvenance(
            source_id="statutory-connector-doc",
            start_char=0,
            end_char=160,
            citation="5 U.S.C. 552",
        ),
        conditions=["as set forth in subparagraph (A)"],
        exceptions=["except as provided in clause (ii)"],
    )
    document = ModalIRDocument(
        document_id="statutory-connector-doc",
        source="us_code",
        normalized_text="The agency must comply with the statutory cross-references.",
        formulas=[formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "as described in section 552(a)(1)" in slot_texts["statutory_scope_reference"]
    assert "as defined in subsection (b)" in slot_texts["statutory_scope_reference"]
    assert "referred to in paragraph (1)" in slot_texts["statutory_scope_reference"]
    assert "as set forth in subparagraph (a)" in slot_texts["statutory_scope_reference"]
    assert "except as provided in clause (ii)" in slot_texts["statutory_scope_reference"]
    assert "as described in" in slot_texts["statutory_scope_connector"]
    assert "as defined in" in slot_texts["statutory_scope_connector"]
    assert "referred to in" in slot_texts["statutory_scope_connector"]
    assert "as set forth in" in slot_texts["statutory_scope_connector"]
    assert "except as provided in" in slot_texts["statutory_scope_connector"]
    assert "section" in slot_texts["statutory_scope_unit"]
    assert "subsection" in slot_texts["statutory_scope_unit"]
    assert "paragraph" in slot_texts["statutory_scope_unit"]
    assert "subparagraph" in slot_texts["statutory_scope_unit"]
    assert "clause" in slot_texts["statutory_scope_unit"]
    assert "552(a)(1)" in slot_texts["statutory_scope_target"]
    assert "(b)" in slot_texts["statutory_scope_target"]
    assert "(1)" in slot_texts["statutory_scope_target"]
    assert "(a)" in slot_texts["statutory_scope_target"]
    assert "(ii)" in slot_texts["statutory_scope_target"]
    assert any(
        triple["predicate"] == "statutory_scope_connector"
        and triple["object"] == "as described in"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "statutory_scope_connector"
        and triple["object"] == "referred to in"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "statutory_scope_connector"
        and triple["object"] == "except as provided in"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_transferred_status_keyword_slot() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    compiled = compiler.compile(
        "\u00a7688. Transferred.",
        document_id="us-code-15-688-3977b0476c11fbf1",
        citation="15 U.S.C. 688",
        source="us_code",
    )

    decoded = decode_modal_ir_document(compiled.modal_ir)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(compiled.modal_ir)

    assert "uscode_transferred_heading_v1" in slot_texts["fallback_rule"]
    assert slot_texts["status_keyword"] == ["transferred"]
    assert slot_texts["status_keyword_token_count"] == ["1"]
    assert slot_texts["status_keyword_token"] == ["transferred"]
    assert slot_texts["status_keyword_stem"] == ["transferred"]
    assert any(
        triple["predicate"] == "status_keyword"
        and triple["object"] == "transferred"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_editorial_fallback_slots() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    compiled = compiler.compile(
        "\u00a73008. Repealed.",
        document_id="us-code-18-3008-62db8e945327b1ec",
        citation="18 U.S.C. 3008",
        source="us_code",
    )

    decoded = decode_modal_ir_document(compiled.modal_ir)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(compiled.modal_ir)

    assert slot_texts["fallback_rule"] == ["uscode_editorial_status_heading_v1"]
    assert slot_texts["fallback_rule_token_count"] == ["5"]
    assert slot_texts["fallback_rule_token_prefix"] == ["uscode"]
    assert slot_texts["fallback_rule_token_suffix"] == ["v1"]
    assert slot_texts["fallback_rule_version"] == ["v1"]
    assert slot_texts["fallback_rule_stem"] == ["uscode_editorial_status_heading"]
    assert "editorial" in slot_texts["fallback_rule_token"]
    assert "status" in slot_texts["fallback_rule_token"]
    assert slot_texts["status_keyword"] == ["repealed"]
    assert slot_texts["status_keyword_token_count"] == ["1"]
    assert slot_texts["status_keyword_token"] == ["repealed"]
    assert slot_texts["status_keyword_stem"] == ["repealed"]
    assert any(
        triple["predicate"] == "fallback_rule"
        and triple["object"] == "uscode_editorial_status_heading_v1"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "fallback_rule_token"
        and triple["object"] == "editorial"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "fallback_rule_version"
        and triple["object"] == "v1"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "status_keyword"
        and triple["object"] == "repealed"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "status_keyword_token_count"
        and triple["object"] == "1"
        for triple in triples
    )


def test_modal_decompiler_normalizes_secs_status_fallback_surface_text() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    compiled = compiler.compile(
        "Secs. 435, 436 - Repealed.",
        document_id="us-code-2-435-range-fallback",
        citation="2 U.S.C. 435",
        source="us_code",
    )

    decoded = decode_modal_ir_document(compiled.modal_ir)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(compiled.modal_ir)

    assert slot_texts["status_keyword"] == ["repealed"]
    assert len(slot_texts["fallback_surface_text"]) == 1
    assert slot_texts["fallback_surface_text"][0].lower() == "repealed"
    assert "436" not in slot_texts["fallback_surface_text"][0]
    assert any(
        triple["predicate"] == "fallback_surface_text"
        and triple["object"].lower() == "repealed"
        for triple in triples
    )


def test_modal_decompiler_and_triples_skip_low_information_numeric_fallback_surface_text() -> None:
    source_text = "U.S.C. Title 5 - GOVERNMENT ORGANIZATION CHAPTER 4 -"
    chapter_digit_start = source_text.index("4")
    chapter_digit_end = chapter_digit_start + 1
    document = ModalIRDocument(
        document_id="us-code-5-409-793df5caffd4b933",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="us-code-5-409-793df5caffd4b933:f0001",
                operator=ModalIROperator(
                    family="frame",
                    system="F",
                    symbol="Frame",
                    label="ontology_frame",
                ),
                predicate=ModalIRPredicate(name="uscode_residual_span_fallback"),
                provenance=ModalIRProvenance(
                    source_id="us-code-5-409-793df5caffd4b933",
                    start_char=chapter_digit_start,
                    end_char=chapter_digit_end,
                    citation="5 U.S.C. 409",
                ),
                metadata={
                    "cue": "__uscode_residual_span_fallback__",
                    "fallback_rule": "uscode_residual_span_coverage_v1",
                },
            )
        ],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "fallback_surface_text" not in slot_texts
    assert "fallback_surface_text_token" not in slot_texts
    assert all(
        triple.get("predicate") != "fallback_surface_text"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_declarative_statement_hint_slot() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    compiled = compiler.compile(
        "Sec. 2232. It is the sense of the Congress that agency coordination improves administration.",
        document_id="us-code-2-2232-d2b7eed159c634a0",
        citation="2 U.S.C. 2232",
        source="us_code",
    )

    decoded = decode_modal_ir_document(compiled.modal_ir)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(compiled.modal_ir)

    assert slot_texts["fallback_rule"] == ["uscode_declarative_statement_v1"]
    assert slot_texts["statement_hint"] == ["sense_of_congress"]
    assert slot_texts["statement_hint_token_count"] == ["3"]
    assert slot_texts["statement_hint_token_prefix"] == ["sense"]
    assert slot_texts["statement_hint_token_suffix"] == ["congress"]
    assert slot_texts["statement_hint_stem"] == ["sense_of_congress"]
    assert any(
        triple["predicate"] == "statement_hint"
        and triple["object"] == "sense_of_congress"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "statement_hint_token"
        and triple["object"] == "sense"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "statement_hint_token"
        and triple["object"] == "congress"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_section_heading_tail_slots() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    compiled = compiler.compile(
        "\u00a73121. Definitions and purposes.",
        document_id="us-code-29-3121-da7d5224c3804b0e",
        citation="29 U.S.C. 3121",
        source="us_code",
    )

    fallback = compiled.modal_ir.formulas[-1]
    assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"

    decoded = decode_modal_ir_document(compiled.modal_ir)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(compiled.modal_ir)

    assert slot_texts["section_heading_tail"] == ["Definitions and purposes"]
    assert slot_texts["fallback_surface_text"] == ["Definitions and purposes"]
    assert slot_texts["section_heading_tail_token_count"] == ["3"]
    assert slot_texts["section_heading_tail_token_prefix"] == ["definitions"]
    assert slot_texts["section_heading_tail_token_suffix"] == ["purposes"]
    assert slot_texts["section_heading_tail_stem"] == ["definitions_and_purposes"]
    assert slot_texts["fallback_surface_text_token_count"] == ["3"]
    assert slot_texts["fallback_surface_text_token_suffix"] == ["purposes"]
    assert "and" in slot_texts["section_heading_tail_token"]
    assert any(
        triple["predicate"] == "section_heading_tail"
        and triple["object"] == "Definitions and purposes"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "fallback_surface_text"
        and triple["object"] == "Definitions and purposes"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "section_heading_tail_token"
        and triple["object"] == "definitions"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "section_heading_tail_token_suffix"
        and triple["object"] == "purposes"
        for triple in triples
    )


def test_modal_decompiler_and_triples_surface_fallback_text_for_heading_without_section_reference() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    compiled = compiler.compile(
        "Housing voucher benefits and utility allowances.",
        document_id="us-code-25-422-f3f166961e45b585",
        citation="25 U.S.C. 422",
        source="us_code",
    )

    fallback = compiled.modal_ir.formulas[-1]
    assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"

    decoded = decode_modal_ir_document(compiled.modal_ir)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(compiled.modal_ir)

    assert slot_texts["fallback_surface_text"] == ["Housing voucher benefits and utility allowances"]
    assert slot_texts["fallback_surface_text_token_count"] == ["6"]
    assert slot_texts["fallback_surface_text_token_prefix"] == ["housing"]
    assert slot_texts["fallback_surface_text_token_suffix"] == ["allowances"]
    assert (
        slot_texts["fallback_surface_text_stem"]
        == ["housing_voucher_benefits_and_utility_allowances"]
    )
    assert "voucher" in slot_texts["fallback_surface_text_token"]
    assert any(
        triple["predicate"] == "fallback_surface_text"
        and triple["object"] == "Housing voucher benefits and utility allowances"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "fallback_surface_text_token_suffix"
        and triple["object"] == "allowances"
        for triple in triples
    )


def test_modal_decompiler_and_triples_keep_compilation_fallback_slots_without_inline_section_ref() -> None:
    heading_span = (
        " United States Code, 2024 Edition Title 16 - CONSERVATION CHAPTER 30 - "
        "WILD HORSES AND BURROS:"
    )
    chapter_span = (
        " United States Code, 2024 Edition Title 22 - FOREIGN RELATIONS AND "
        "INTERCOURSE CHAPTER 64 - UNITED STATES RESPONSE TO TERRORISM AFFECTING "
        "AMERICANS ABROAD Sec."
    )
    source_text = f"Prefix.{heading_span} Middle.{chapter_span} 5505 - Training."
    heading_start = source_text.index(heading_span)
    heading_end = heading_start + len(heading_span)
    chapter_start = source_text.index(chapter_span)
    chapter_end = chapter_start + len(chapter_span)
    formulas = [
        ModalIRFormula(
            formula_id="compilation-fallback-doc:f0001",
            operator=ModalIROperator(
                family="frame",
                system="F",
                symbol="Frame",
                label="ontology_frame",
            ),
            predicate=ModalIRPredicate(
                name="united_states_code_edition_title_conservation",
                role="clause",
            ),
            provenance=ModalIRProvenance(
                source_id="compilation-fallback-doc",
                start_char=heading_start,
                end_char=heading_end,
                citation="16 U.S.C. 1332",
            ),
            metadata={
                "cue": "__uscode_residual_span_fallback__",
                "fallback_rule": "uscode_residual_span_coverage_v1",
            },
        ),
        ModalIRFormula(
            formula_id="compilation-fallback-doc:f0002",
            operator=ModalIROperator(
                family="frame",
                system="F",
                symbol="Frame",
                label="ontology_frame",
            ),
            predicate=ModalIRPredicate(
                name="united_states_code_edition_title_foreign_relations",
                role="clause",
            ),
            provenance=ModalIRProvenance(
                source_id="compilation-fallback-doc",
                start_char=chapter_start,
                end_char=chapter_end,
                citation="22 U.S.C. 5505",
            ),
            metadata={
                "cue": "__uscode_residual_span_fallback__",
                "fallback_rule": "uscode_residual_span_coverage_v1",
            },
        ),
    ]
    document = ModalIRDocument(
        document_id="compilation-fallback-doc",
        source="us_code",
        normalized_text=source_text,
        formulas=formulas,
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "13:and" in slot_texts["fallback_surface_text_alnum_segment_positioned"]
    assert "20:alpha" in slot_texts["fallback_surface_text_alnum_segment_kind_positioned"]
    assert any(
        triple["predicate"] == "fallback_surface_text_alnum_segment_positioned"
        and triple["object"] == "13:and"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "fallback_surface_text_alnum_segment_kind_positioned"
        and triple["object"] == "20:alpha"
        for triple in triples
    )


def test_modal_decompiler_falls_back_to_frame_logic_selected_frame() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    compiled = compiler.compile("The agency must provide notice.")
    assert compiled.selected_frame

    frame_only_modal_ir = replace(
        compiled.modal_ir,
        frame_logic=ModalIRFrameLogic(selected_frame=compiled.selected_frame),
        metadata={**compiled.modal_ir.metadata, "selected_frame": ""},
    )
    decoded = decode_modal_ir_document(frame_only_modal_ir)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_texts["selected_frame"] == [compiled.selected_frame]


def test_modal_decompiler_and_triples_surface_selected_frame_modal_family_count_slots() -> None:
    formulas = [
        ModalIRFormula(
            formula_id="selected-frame-family-doc:f0001",
            operator=ModalIROperator(
                family="deontic",
                system="D",
                symbol="O",
                label="obligatory",
            ),
            predicate=ModalIRPredicate(
                name="must_provide_notice",
                role="clause",
            ),
            provenance=ModalIRProvenance(
                source_id="selected-frame-family-doc",
                start_char=0,
                end_char=24,
                citation="5 U.S.C. 552",
            ),
        ),
        ModalIRFormula(
            formula_id="selected-frame-family-doc:f0002",
            operator=ModalIROperator(
                family="epistemic",
                system="S5",
                symbol="K",
                label="known",
            ),
            predicate=ModalIRPredicate(
                name="knows_compliance_status",
                role="clause",
            ),
            provenance=ModalIRProvenance(
                source_id="selected-frame-family-doc",
                start_char=25,
                end_char=58,
                citation="5 U.S.C. 552",
            ),
        ),
    ]
    document = ModalIRDocument(
        document_id="selected-frame-family-doc",
        source="us_code",
        normalized_text=(
            "The agency must provide notice and knows compliance status."
        ),
        formulas=formulas,
        metadata={"selected_frame": "administrative_notice_hearing"},
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_texts["selected_frame"] == ["administrative_notice_hearing"]
    assert slot_texts["selected_frame_modal_family"] == ["deontic", "epistemic"]
    assert slot_texts["selected_frame_modal_family_ranked"] == [
        "1:deontic",
        "2:epistemic",
    ]
    assert slot_texts["selected_frame_modal_family_count"] == [
        "deontic:1",
        "epistemic:1",
    ]
    assert slot_texts["selected_frame_modal_family_count_value"] == ["1"]
    assert slot_texts["selected_frame_modal_family_count_value_digit_count_bucket"] == [
        "1_digit"
    ]
    assert slot_texts["selected_frame_modal_family_count_value_parity"] == ["odd"]
    assert slot_texts["selected_frame_modal_family_deontic"] == ["1"]
    assert slot_texts["selected_frame_modal_family_epistemic"] == ["1"]

    triple_values: dict[str, list[str]] = {}
    for triple in modal_ir_to_flogic_triples(document):
        predicate = str(triple.get("predicate", "")).strip()
        value = str(triple.get("object", "")).strip()
        if not predicate or not value:
            continue
        values = triple_values.setdefault(predicate, [])
        if value not in values:
            values.append(value)

    assert triple_values["selected_ontology_frame"] == ["administrative_notice_hearing"]
    assert triple_values["selected_frame_modal_family"] == ["deontic", "epistemic"]
    assert triple_values["selected_frame_modal_family_ranked"] == [
        "1:deontic",
        "2:epistemic",
    ]
    assert triple_values["selected_frame_modal_family_count"] == [
        "deontic:1",
        "epistemic:1",
    ]
    assert triple_values["selected_frame_modal_family_count_value"] == ["1"]
    assert triple_values["selected_frame_modal_family_count_value_digit_count_bucket"] == [
        "1_digit"
    ]
    assert triple_values["selected_frame_modal_family_count_value_parity"] == ["odd"]
    assert triple_values["selected_frame_modal_family_deontic"] == ["1"]
    assert triple_values["selected_frame_modal_family_epistemic"] == ["1"]


def test_modal_decompiler_surfaces_ranked_frame_candidate_slots() -> None:
    formula = ModalIRFormula(
        formula_id="frame-candidate-doc:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="D",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(
            name="must_provide_notice",
            role="clause",
        ),
        provenance=ModalIRProvenance(
            source_id="frame-candidate-doc",
            start_char=0,
            end_char=32,
            citation="5 U.S.C. 552",
        ),
    )
    document = ModalIRDocument(
        document_id="frame-candidate-doc",
        source="us_code",
        normalized_text="The agency must provide notice.",
        formulas=[formula],
        frame_candidates=[
            ModalIRFrame(
                frame_id="criminal_penalty_enforcement",
                score=0.61,
                matched_terms=["criminal penalty", "enforcement"],
            ),
            ModalIRFrame(
                frame_id="administrative_notice_hearing",
                score=0.93,
                matched_terms=["notice", "hearing"],
            ),
        ],
        metadata={"selected_frame": "administrative_notice_hearing"},
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_texts["frame_candidate"] == [
        "administrative_notice_hearing",
        "criminal_penalty_enforcement",
    ]
    assert slot_texts["frame_candidate_rank"] == ["1", "2"]
    assert slot_texts["frame_candidate_ranked"] == [
        "1:administrative_notice_hearing",
        "2:criminal_penalty_enforcement",
    ]
    assert "administrative" in slot_texts["frame_candidate_token"]
    assert "penalty" in slot_texts["frame_candidate_token"]
    assert slot_texts["frame_candidate_token_count"] == ["3"]
    assert slot_texts["frame_candidate_term"] == [
        "notice",
        "hearing",
        "criminal penalty",
        "enforcement",
    ]
    assert "criminal" in slot_texts["frame_candidate_term_token"]
    assert "administrative_notice_hearing" in slot_texts["selected_frame"]
    assert slot_texts["selected_frame_stem"] == ["administrative_notice_hearing"]


def test_modal_decompiler_filters_non_informative_frame_candidate_terms() -> None:
    formula = ModalIRFormula(
        formula_id="frame-candidate-filter-doc:f0001",
        operator=ModalIROperator(
            family="deontic",
            system="D",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(
            name="must_provide_notice",
            role="clause",
        ),
        provenance=ModalIRProvenance(
            source_id="frame-candidate-filter-doc",
            start_char=0,
            end_char=32,
            citation="5 U.S.C. 552",
        ),
    )
    document = ModalIRDocument(
        document_id="frame-candidate-filter-doc",
        source="us_code",
        normalized_text="The agency must provide notice.",
        formulas=[formula],
        frame_candidates=[
            ModalIRFrame(
                frame_id="administrative_notice_hearing",
                score=0.93,
                matched_terms=["notice", "and", "the", "hearing"],
            ),
        ],
        metadata={"selected_frame": "administrative_notice_hearing"},
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_texts["frame_candidate_term"] == ["notice", "hearing"]
    assert "and" not in slot_texts["frame_candidate_term_token"]
    assert "the" not in slot_texts["frame_candidate_term_token"]


def test_modal_codec_supports_autoencoder_feature_codec_protocol() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )

    assert codec.encode_sample(sample).cues
    assert codec.compile_sample_ir(sample).frame_candidates
    assert len(codec.decode_sample_embedding(sample, dimensions=8)) == 8
    assert codec.family_logits_for_sample(
        sample,
        modal_families=["deontic", "temporal", "frame"],
    )["deontic"] > 0.0
    feature_keys = codec.feature_keys_for_sample(sample)
    assert "frame:administrative_notice_hearing" in feature_keys
    assert any(feature.startswith("frame-term:") for feature in feature_keys)
    assert any(feature.startswith("selected-frame-term:") for feature in feature_keys)
    assert any(feature.startswith("family:selected_frame:") for feature in feature_keys)
    assert any(feature.startswith("flogic:modal_family:") for feature in feature_keys)
    assert "slot:modal_family" in feature_keys
    assert "slot:modal_operator" in feature_keys
    assert "slot:citation_title:5" in feature_keys
    assert "slot:citation_section:552" in feature_keys


def test_modal_codec_emits_frame_ontology_term_triples() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide notice within 30 days.",
        document_id="frame-term-doc",
        citation="5 U.S.C. 552",
        source="us_code",
    )

    assert any(
        triple["predicate"] == "candidate_ontology_term"
        for triple in result.kg_triples
    )
    assert any(
        triple["predicate"] == "selected_ontology_term"
        for triple in result.kg_triples
    )
    assert any(
        triple["predicate"] == "interpreted_in_frame_term"
        for triple in result.kg_triples
    )
    assert result.flogic_result is not None
    assert result.flogic_result.metadata["frame_ontology_term_count"] > 0


def test_modal_codec_normalizes_legacy_slot_positioned_frame_audit_terms() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "Administrative notice and hearing.",
        document_id="frame-term-positioned-slot-doc",
        citation="48 U.S.C. 1572.",
        source="us_code",
    )

    assert result.flogic_result is not None
    feature_terms = result.flogic_result.metadata["frame_ontology_terms_from_feature_keys"]
    merged_terms = result.flogic_result.metadata["frame_ontology_terms"]

    assert "1572" in feature_terms
    assert "numeric" in feature_terms
    assert "4" in feature_terms
    assert not any(term.startswith("1_") for term in feature_terms)
    assert not any(term.startswith("1_") for term in merged_terms)


def test_modal_codec_audits_frame_terms_when_metadata_is_partial() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide notice and a hearing before a final order.",
        document_id="frame-term-partial-metadata-doc",
        source="us_code",
    )
    assert result.selected_frame is not None
    assert len(result.modal_ir.frame_candidates) >= 2

    selected_frame = result.selected_frame
    alternate_frame = next(
        frame.frame_id
        for frame in result.modal_ir.frame_candidates
        if frame.frame_id != selected_frame
    )
    patched_modal_ir = replace(
        result.modal_ir,
        frame_logic=ModalIRFrameLogic(selected_frame=selected_frame),
        metadata={
            **result.modal_ir.metadata,
            "frame_ontology_terms": {
                selected_frame: ["and"],
                alternate_frame: ["housing_voucher_benefits"],
            },
        },
    )

    triples = modal_ir_to_flogic_triples(
        patched_modal_ir,
        selected_frame=selected_frame,
    )
    selected_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "selected_ontology_term"
    }

    assert selected_frame in selected_terms
    assert "and" not in selected_terms


def test_modal_codec_audits_frame_terms_when_metadata_contains_weight_maps() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide notice and a hearing before a final order.",
        document_id="frame-term-weighted-metadata-doc",
        source="us_code",
    )
    assert result.selected_frame is not None
    assert len(result.modal_ir.frame_candidates) >= 2

    selected_frame = result.selected_frame
    alternate_frame = next(
        frame.frame_id
        for frame in result.modal_ir.frame_candidates
        if frame.frame_id != selected_frame
    )
    patched_modal_ir = replace(
        result.modal_ir,
        frame_logic=ModalIRFrameLogic(selected_frame=selected_frame),
        metadata={
            **result.modal_ir.metadata,
            "frame_ontology_terms": {
                selected_frame: {
                    "hearing rights": 1.0,
                    "and": 0.25,
                },
                alternate_frame: {
                    "t-1": "final order",
                },
            },
        },
    )

    triples = modal_ir_to_flogic_triples(
        patched_modal_ir,
        selected_frame=selected_frame,
    )
    selected_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "selected_ontology_term"
    }
    candidate_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "candidate_ontology_term"
    }

    assert "hearing_rights" in selected_terms
    assert "and" not in selected_terms
    assert "final_order" in candidate_terms


def test_modal_codec_audits_frame_terms_when_metadata_contains_structured_entries() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide notice and a hearing before a final order.",
        document_id="frame-term-structured-metadata-doc",
        source="us_code",
    )
    assert result.selected_frame is not None
    assert len(result.modal_ir.frame_candidates) >= 2

    selected_frame = result.selected_frame
    alternate_frame = next(
        frame.frame_id
        for frame in result.modal_ir.frame_candidates
        if frame.frame_id != selected_frame
    )
    patched_modal_ir = replace(
        result.modal_ir,
        frame_logic=ModalIRFrameLogic(selected_frame=selected_frame),
        metadata={
            **result.modal_ir.metadata,
            "frame_ontology_terms": {
                selected_frame: [
                    {"term": "hearing rights", "weight": 1.0},
                    {"text": "final order", "confidence": 0.9},
                ],
                alternate_frame: {
                    "terms": [
                        {"label": "housing voucher benefits"},
                        {"value": "and"},
                    ],
                    "weights": {"t-1": "administrative notice"},
                },
            },
        },
    )

    triples = modal_ir_to_flogic_triples(
        patched_modal_ir,
        selected_frame=selected_frame,
    )
    selected_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "selected_ontology_term"
    }
    candidate_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "candidate_ontology_term"
    }

    assert "hearing_rights" in selected_terms
    assert "final_order" in selected_terms
    assert "housing_voucher_benefits" in candidate_terms
    assert "and" not in candidate_terms
    assert "term_hearing_rights_weight" not in candidate_terms
    assert "text_final_order_confidence" not in candidate_terms


def test_modal_codec_audits_citation_coordinates_from_frame_term_metadata() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide notice and a hearing before a final order.",
        document_id="frame-term-citation-metadata-doc",
        source="us_code",
    )
    assert result.selected_frame is not None

    selected_frame = result.selected_frame
    patched_modal_ir = replace(
        result.modal_ir,
        frame_logic=ModalIRFrameLogic(selected_frame=selected_frame),
        metadata={
            **result.modal_ir.metadata,
            "frame_ontology_terms": {
                selected_frame: [
                    "42 U.S.C. 6932.",
                    "us-code-25-564m-dee77e626d5d85a3",
                ]
            },
        },
    )

    triples = modal_ir_to_flogic_triples(
        patched_modal_ir,
        selected_frame=selected_frame,
    )
    selected_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "selected_ontology_term"
    }

    assert "42_6932" in selected_terms
    assert "25_564m" in selected_terms
    assert "us_code_564m_dee77e626d5d85a3" not in selected_terms


def test_modal_codec_audits_slot_normalized_source_ids_from_frame_term_metadata() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide notice and a hearing before a final order.",
        document_id="frame-term-slot-normalized-source-id-metadata-doc",
        source="us_code",
    )
    assert result.selected_frame is not None

    selected_frame = result.selected_frame
    patched_modal_ir = replace(
        result.modal_ir,
        frame_logic=ModalIRFrameLogic(selected_frame=selected_frame),
        metadata={
            **result.modal_ir.metadata,
            "frame_ontology_terms": {
                selected_frame: [
                    "us_code_54_101920_2a8a1acc9abc25ac",
                    "us_code_38_1720d_93b4ea776e53aa1a",
                ]
            },
        },
    )

    triples = modal_ir_to_flogic_triples(
        patched_modal_ir,
        selected_frame=selected_frame,
    )
    selected_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "selected_ontology_term"
    }

    assert "54_101920" in selected_terms
    assert "38_1720d" in selected_terms
    assert not any(term.startswith("us_code_") for term in selected_terms)


def test_modal_codec_audits_matched_terms_metadata_without_key_noise() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide notice and a hearing before a final order.",
        document_id="frame-term-matched-terms-metadata-doc",
        source="us_code",
    )
    assert result.selected_frame is not None

    selected_frame = result.selected_frame
    patched_modal_ir = replace(
        result.modal_ir,
        frame_logic=ModalIRFrameLogic(selected_frame=selected_frame),
        metadata={
            **result.modal_ir.metadata,
            "frame_ontology_terms": {
                selected_frame: {
                    "matched_terms": ["hearing rights", "final order"],
                    "score": 0.99,
                }
            },
        },
    )

    triples = modal_ir_to_flogic_triples(
        patched_modal_ir,
        selected_frame=selected_frame,
    )
    selected_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "selected_ontology_term"
    }

    assert "hearing_rights" in selected_terms
    assert "final_order" in selected_terms
    assert "matched_terms" not in selected_terms


def test_modal_codec_audits_citation_and_sample_metadata_without_structural_key_noise() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide notice and a hearing before a final order.",
        document_id="frame-term-citation-sample-metadata-doc",
        source="us_code",
    )
    assert result.selected_frame is not None

    selected_frame = result.selected_frame
    patched_modal_ir = replace(
        result.modal_ir,
        frame_logic=ModalIRFrameLogic(selected_frame=selected_frame),
        metadata={
            **result.modal_ir.metadata,
            "frame_ontology_terms": {
                selected_frame: {
                    "citations": [
                        "43 U.S.C. 641.",
                        "42 U.S.C. 295.",
                    ],
                    "sample_ids": [
                        "us-code-21-619-6c53879113090cdf",
                    ],
                    "hint_ids": [
                        "modal-synthesis-77aa1da71a3c8c76",
                    ],
                    "score": 0.99,
                }
            },
        },
    )

    triples = modal_ir_to_flogic_triples(
        patched_modal_ir,
        selected_frame=selected_frame,
    )
    selected_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "selected_ontology_term"
    }

    assert "43_641" in selected_terms
    assert "42_295" in selected_terms
    assert "21_619" in selected_terms
    assert "citations" not in selected_terms
    assert "sample_ids" not in selected_terms
    assert "hint_ids" not in selected_terms
    assert not any(term.startswith("modal_synthesis") for term in selected_terms)


def test_modal_codec_audits_frame_feature_keys_from_term_metadata() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide notice and a hearing before a final order.",
        document_id="frame-term-feature-key-metadata-doc",
        source="us_code",
    )
    assert result.selected_frame is not None

    selected_frame = result.selected_frame
    patched_modal_ir = replace(
        result.modal_ir,
        frame_logic=ModalIRFrameLogic(selected_frame=selected_frame),
        metadata={
            **result.modal_ir.metadata,
            "frame_ontology_terms": {
                selected_frame: [
                    {"feature": "selected-frame-term:42 U.S.C. 6932."},
                    {"feature_key": "cue:frame:Frame:transferred"},
                    {"feature": "flogic:source_id:us-code-5-552-deadbeefdeadbeef"},
                ]
            },
        },
    )

    triples = modal_ir_to_flogic_triples(
        patched_modal_ir,
        selected_frame=selected_frame,
    )
    selected_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "selected_ontology_term"
    }

    assert "42_6932" in selected_terms
    assert "transferred" in selected_terms
    assert "5_552" in selected_terms
    assert "feature" not in selected_terms
    assert not any(term.startswith("selected_frame_term") for term in selected_terms)


def test_modal_codec_audits_structured_hint_evidence_from_term_metadata_without_key_noise() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide notice and a hearing before a final order.",
        document_id="frame-term-hint-evidence-metadata-doc",
        source="us_code",
    )
    assert result.selected_frame is not None

    selected_frame = result.selected_frame
    patched_modal_ir = replace(
        result.modal_ir,
        frame_logic=ModalIRFrameLogic(selected_frame=selected_frame),
        metadata={
            **result.modal_ir.metadata,
            "frame_ontology_terms": {
                selected_frame: {
                    "matched_terms": ["hearing rights"],
                    "hint_evidence": [
                        {
                            "hint_id": "modal-synthesis-5c028bc1799b3abf",
                            "sample_id": "us-code-7-1595-3023e94b951ca7a0",
                        }
                    ],
                    "frame_features": [
                        "selected-frame-term:42 U.S.C. 6932.",
                        "cue:frame:Frame:transferred",
                    ],
                    "top_family_features": [
                        "family:selected_frame:deontic",
                    ],
                    "hint_ids": ["modal-synthesis-6191fcb2398f9edb"],
                    "score": 0.99,
                }
            },
        },
    )

    triples = modal_ir_to_flogic_triples(
        patched_modal_ir,
        selected_frame=selected_frame,
    )
    selected_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "selected_ontology_term"
    }

    assert "hearing_rights" in selected_terms
    assert "7_1595" in selected_terms
    assert "42_6932" in selected_terms
    assert "transferred" in selected_terms
    assert "deontic" in selected_terms
    assert "hint_evidence" not in selected_terms
    assert "frame_features" not in selected_terms
    assert "top_family_features" not in selected_terms
    assert not any(term.startswith("modal_synthesis") for term in selected_terms)


def test_modal_codec_audits_structured_evidence_from_term_metadata_without_key_noise() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide notice and a hearing before a final order.",
        document_id="frame-term-evidence-metadata-doc",
        source="us_code",
    )
    assert result.selected_frame is not None

    selected_frame = result.selected_frame
    patched_modal_ir = replace(
        result.modal_ir,
        frame_logic=ModalIRFrameLogic(selected_frame=selected_frame),
        metadata={
            **result.modal_ir.metadata,
            "frame_ontology_terms": {
                selected_frame: {
                    "matched_terms": ["hearing rights"],
                    "evidence": [
                        {
                            "hint_id": "modal-synthesis-5c028bc1799b3abf",
                            "sample_id": "us-code-7-1595-3023e94b951ca7a0",
                            "frame_features": [
                                "selected-frame-term:42 U.S.C. 6932.",
                                "cue:frame:Frame:transferred",
                            ],
                        }
                    ],
                    "hint_ids": ["modal-synthesis-6191fcb2398f9edb"],
                    "score": 0.99,
                }
            },
        },
    )

    triples = modal_ir_to_flogic_triples(
        patched_modal_ir,
        selected_frame=selected_frame,
    )
    selected_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "selected_ontology_term"
    }

    assert "hearing_rights" in selected_terms
    assert "7_1595" in selected_terms
    assert "42_6932" in selected_terms
    assert "transferred" in selected_terms
    assert "evidence" not in selected_terms
    assert "frame_features" not in selected_terms
    assert not any(term.startswith("modal_synthesis") for term in selected_terms)


def test_modal_codec_frame_ontology_audit_feature_keys_include_evidence_payloads() -> None:
    modal_ir = ModalIRDocument(
        document_id="frame-audit-evidence-doc",
        source="us_code",
        normalized_text="The agency may issue a final order.",
        frame_logic=ModalIRFrameLogic(
            metadata={
                "evidence": [
                    {
                        "sample_id": "us-code-46-2104.-968c80c773abaeae",
                        "frame_features": [
                            "family:selected_frame:deontic",
                            "token:agency",
                        ],
                    }
                ]
            }
        ),
        metadata={
            "evidence": [
                {
                    "sample_id": "us-code-10-986-edca8f211d40c8ce",
                    "frame_features": [
                        "flogic:modal_cue:authority",
                        "token:agency",
                    ],
                }
            ]
        },
    )

    keys = _frame_ontology_audit_feature_keys(
        modal_ir=modal_ir,
        selected_frame=None,
        kg_triples=[],
    )

    assert "us-code-10-986-edca8f211d40c8ce" in keys
    assert "us-code-46-2104.-968c80c773abaeae" in keys
    assert "flogic:modal_cue:authority" in keys
    assert "family:selected_frame:deontic" in keys
    assert "token:agency" not in keys


def test_modal_codec_frame_ontology_audit_feature_keys_include_autoencoder_contributions() -> None:
    modal_ir = ModalIRDocument(
        document_id="frame-audit-contrib-doc",
        source="us_code",
        normalized_text="The agency may issue a final order.",
        frame_logic=ModalIRFrameLogic(
            metadata={
                "top_family_contributions": [
                    {
                        "feature": "family:selected_frame:deontic",
                        "magnitude": 0.82,
                        "value": 0.91,
                    },
                    {
                        "feature": "token:agency",
                        "magnitude": 0.11,
                        "value": 0.12,
                    },
                ]
            }
        ),
        metadata={
            "top_embedding_contributions": [
                {
                    "feature": "slot:selected_frame:administrative_notice_hearing",
                    "magnitude": 0.73,
                    "value": 0.66,
                },
                {
                    "feature": "flogic:source_id:us-code-49-47126.-2322d39a63b9ba2d",
                    "magnitude": 0.45,
                    "value": 0.42,
                },
                {
                    "feature": "lemma:notice",
                    "magnitude": 0.09,
                    "value": 0.11,
                },
            ]
        },
    )

    keys = _frame_ontology_audit_feature_keys(
        modal_ir=modal_ir,
        selected_frame=None,
        kg_triples=[],
    )
    terms = _frame_ontology_audit_terms(
        frame_feature_keys=keys,
        kg_triples=[],
    )

    assert "family:selected_frame:deontic" in keys
    assert "slot:selected_frame:administrative_notice_hearing" in keys
    assert "flogic:source_id:us-code-49-47126.-2322d39a63b9ba2d" in keys
    assert "token:agency" not in keys
    assert "lemma:notice" not in keys
    assert "deontic" in terms
    assert "administrative_notice_hearing" in terms
    assert "49_47126" in terms


def test_modal_codec_frame_ontology_audit_feature_keys_include_family_scoring_metadata_fields() -> None:
    modal_ir = ModalIRDocument(
        document_id="frame-audit-family-fields-doc",
        source="us_code",
        normalized_text="The agency may issue a final order.",
        frame_logic=ModalIRFrameLogic(
            metadata={
                "family": "deontic",
                "selected_family": "temporal",
            }
        ),
        metadata={
            "predicted_family": "frame",
            "target_family": "epistemic",
            "top_family_features": ["token:agency"],
        },
    )

    keys = _frame_ontology_audit_feature_keys(
        modal_ir=modal_ir,
        selected_frame=None,
        kg_triples=[],
    )
    terms = _frame_ontology_audit_terms(
        frame_feature_keys=keys,
        kg_triples=[],
    )

    assert "family:selected_frame:deontic" in keys
    assert "family:selected_frame:temporal" in keys
    assert "family:selected_frame:frame" in keys
    assert "family:selected_frame:epistemic" in keys
    assert "token:agency" not in keys
    assert "deontic" in terms
    assert "temporal" in terms
    assert "frame" in terms
    assert "epistemic" in terms


def test_modal_codec_audits_alphanumeric_usc_frame_term_feature_keys() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    result = codec.encode(
        "The agency must provide notice and a hearing before a final order.",
        document_id="frame-term-alnum-citation-metadata-doc",
        source="us_code",
    )
    assert result.selected_frame is not None

    selected_frame = result.selected_frame
    patched_modal_ir = replace(
        result.modal_ir,
        frame_logic=ModalIRFrameLogic(selected_frame=selected_frame),
        metadata={
            **result.modal_ir.metadata,
            "frame_ontology_terms": {
                selected_frame: [
                    {"feature": "selected-frame-term:42 U.S.C. 1437q."},
                    {"feature": "candidate-frame-term:20 U.S.C. 1087j"},
                    {"feature_key": "slot:candidate_ontology_term:16 U.S.C. 460l-11"},
                    {"feature": "flogic:selected_ontology_term:42 U.S.C. 2981 to 2981c."},
                    {"feature_key": "flogic:interpreted_in_frame_term:22 U.S.C. 2349aa-4"},
                ]
            },
        },
    )

    triples = modal_ir_to_flogic_triples(
        patched_modal_ir,
        selected_frame=selected_frame,
    )
    selected_terms = {
        triple["object"]
        for triple in triples
        if triple["predicate"] == "selected_ontology_term"
    }

    assert "42_1437q" in selected_terms
    assert "20_1087j" in selected_terms
    assert "16_460l_11" in selected_terms
    assert "42_2981_2981c" in selected_terms
    assert "22_2349aa_4" in selected_terms


def test_modal_codec_filters_non_informative_frame_ontology_terms() -> None:
    frame_selector = BM25FrameSelector(
        (
            FrameCandidate(
                frame_id="noisy_admin_frame",
                label="The Notice and Hearing",
                terms=("and", "the", "hearing rights", "agency"),
                domain="general",
            ),
        )
    )
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
        frame_selector=frame_selector,
    )
    result = codec.encode(
        "The agency must provide notice and hearing.",
        document_id="frame-term-filter-doc",
        source="us_code",
    )

    term_objects = {
        triple["object"]
        for triple in result.kg_triples
        if triple["predicate"] in {
            "candidate_ontology_term",
            "selected_ontology_term",
            "interpreted_in_frame_term",
        }
    }
    assert "and" not in term_objects
    assert "the" not in term_objects
    assert "hearing_rights" in term_objects

    sample = build_us_code_sample(
        title="5",
        section="555",
        text="The agency must provide notice and hearing.",
    )
    feature_keys = codec.feature_keys_for_sample(sample)
    assert "selected-frame-term:and" not in feature_keys
    assert "selected-frame-term:the" not in feature_keys
    assert "selected-frame-term:hearing_rights" in feature_keys


def test_modal_codec_frame_decoder_audit_features_use_canonical_feature_parser() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    encoding = codec.encode_sample(sample)

    class _StubDecoder:
        def _feature_stream(self, _encoding):  # pragma: no cover - helper only
            return iter(
                [
                    "token:agency",
                    "modal-family:frame:2",
                    "cue:frame:Frame:authority",
                    "slot:selected_frame:administrative_notice_hearing",
                    "cue:deontic:O:must",
                ]
            )

    assert _frame_decoder_audit_features(encoding, _StubDecoder()) == [
        "modal-family:frame:2",
        "cue:frame:Frame:authority",
        "slot:selected_frame:administrative_notice_hearing",
    ]


def test_modal_codec_frame_ontology_audit_tracks_frame_semantic_slot_features() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    sample = build_us_code_sample(
        title="15",
        section="3722a",
        text="Sec. 3722a. The Secretary may transfer authority under section 3722a.",
    )
    result = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
    )
    assert result.flogic_result is not None

    audit_feature_keys = result.flogic_result.metadata["frame_audit_feature_keys"]
    assert "slot:operator:framed_as" in audit_feature_keys
    assert "slot:role:frame" in audit_feature_keys
    assert "frame" in result.flogic_result.metadata["frame_ontology_terms"]


def test_modal_codec_frame_ontology_audit_tracks_selected_frame_modal_families() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    result = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
    )
    assert result.flogic_result is not None

    expected_families = sorted(
        {
            formula.operator.family
            for formula in result.modal_ir.formulas
        }
    )
    assert expected_families

    audit_feature_keys = result.flogic_result.metadata["frame_audit_feature_keys"]
    feature_terms = result.flogic_result.metadata["frame_ontology_terms_from_feature_keys"]
    for family in expected_families:
        assert f"family:selected_frame:{family}" in audit_feature_keys
        assert family in feature_terms


def test_modal_codec_frame_ontology_audit_tracks_slot_normalized_source_id_features() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    sample = build_us_code_sample(
        title="2",
        section="31a-2b",
        text="Sec. 31a-2b. Transferred.",
    )
    result = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
    )
    assert result.flogic_result is not None

    source_id_slot_feature = f"slot:source_id:{sample.sample_id.replace('-', '_')}"
    audit_feature_keys = result.flogic_result.metadata["frame_audit_feature_keys"]
    feature_terms = result.flogic_result.metadata["frame_ontology_terms_from_feature_keys"]
    assert source_id_slot_feature in audit_feature_keys
    assert "2_31a_2b" in feature_terms


def test_modal_codec_frame_ontology_audit_normalizes_truncated_citation_source_pair_terms() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    sample = build_us_code_sample(
        title="49",
        section="1101.",
        text="Sec. 1101. Administrative notice and hearing procedures.",
    )
    result = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
    )

    raw_terms = result.modal_ir.metadata["frame_ontology_term_audit_terms"]
    assert "49_1101" in raw_terms
    assert "49_1101_49" not in raw_terms


def test_modal_codec_frame_ontology_audit_prioritizes_decoder_frame_features() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    sample = build_us_code_sample(
        title="50",
        section="3031.",
        text="Sec. 3031. Intelligence policy and duties.",
    )
    result = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
    )

    labels = [
        f"{left}{right}"
        for left in "abcdefghijklmnopqrstuvwxyz"
        for right in "abcdefghijklmnopqrstuvwxyz"
    ]
    dense_triples = [
        {
            "subject": sample.sample_id,
            "predicate": "selected_ontology_term",
            "object": f"term {label}",
        }
        for label in labels[:140]
    ]
    frame_feature_keys = _frame_ontology_audit_feature_keys(
        modal_ir=result.modal_ir,
        selected_frame=result.selected_frame,
        kg_triples=dense_triples,
        extra_feature_keys=[
            "cue:frame:transferred",
            "family:selected_frame:deontic",
        ],
    )
    frame_terms = _frame_ontology_audit_terms(
        frame_feature_keys=frame_feature_keys,
        kg_triples=dense_triples,
    )

    assert "transferred" in frame_terms
    assert "deontic" in frame_terms
    assert "term_fj" in frame_terms
    assert len(frame_terms) > 64


def test_modal_codec_frame_ontology_audit_reports_high_signal_terms() -> None:
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    )
    sample = build_us_code_sample(
        title="42",
        section="291.",
        text="Sec. 291. Findings and declaration of policy.",
    )
    result = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
    )

    raw_terms = result.modal_ir.metadata["frame_ontology_term_audit_terms"]
    high_signal_terms = result.modal_ir.metadata[
        "frame_ontology_high_signal_term_audit_terms"
    ]
    assert "42_291" in high_signal_terms
    assert "0" in raw_terms
    assert "0" not in high_signal_terms
    assert "false" in raw_terms
    assert "false" not in high_signal_terms
    assert result.modal_ir.metadata["frame_ontology_high_signal_term_audit_count"] == len(
        high_signal_terms
    )


def test_frame_ontology_audit_terms_contextualize_low_signal_frame_features() -> None:
    frame_terms = _frame_ontology_audit_terms(
        frame_feature_keys=[
            "flogic:citation_title_number_parity:even",
            "flogic:citation_title_section_primary_number_span_trailing_zero_count:0",
            "flogic:modal_cue:by",
            "flogic:predicate_token:c",
            "flogic:predicate_token:pub",
            "flogic:citation_section_number_magnitude_bucket:lt_1k",
        ],
        kg_triples=[
            {
                "subject": "doc-1",
                "predicate": "source_id_title_number_parity",
                "object": "odd",
            }
        ],
    )

    assert "even" in frame_terms
    assert "citation_title_number_parity_even" in frame_terms
    assert (
        "citation_title_section_primary_number_span_trailing_zero_count_0"
        in frame_terms
    )
    assert "by" in frame_terms
    assert "predicate_token_c" in frame_terms
    assert "predicate_token_pub" in frame_terms
    assert "citation_section_number_magnitude_bucket_lt_1k" in frame_terms
    assert "source_id_title_number_parity_odd" in frame_terms


def test_autoencoder_introspection_guides_typed_synthesis_hints() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice within 30 days.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    todo = type(
        "Todo",
        (),
        {
            "action": "improve_encoder_decoder_reconstruction",
            "loss_name": "cosine_loss",
            "sample_ids": [sample.sample_id],
            "todo_id": "cos-synthesis",
        },
    )()
    autoencoder.apply_todos([todo], {sample.sample_id: sample}, learning_rate=0.5)

    introspection = autoencoder.introspect_sample(sample).to_dict()
    hints = synthesis_hints_from_autoencoder_introspection(introspection)

    actions = {hint.action for hint in hints}
    assert "refine_typed_ir_or_decompiler_slots" in actions
    assert "audit_frame_logic_terms" in actions
    assert all(hint.target_component.startswith("modal.") for hint in hints)
    assert hints[0].hint_id.startswith("modal-synthesis-")
    assert hints[0].to_dict()["status"] == "proposed"


def test_autoencoder_synthesis_hint_extracts_frame_linked_feature_variants() -> None:
    hints = synthesis_hints_from_autoencoder_introspection(
        {
            "sample_id": "us-code-5-552-deadbeefdeadbeef",
            "synthesis_focus": ["audit_frame_logic_terms"],
            "reconstruction_loss": 0.42,
            "family_margin": 0.5,
            "top_family_contributions": [
                {"feature": "slot:selected_frame:administrative_notice_hearing"},
                {"feature": "selected-frame-term:final_order"},
                {"feature": "family:selected_frame:deontic"},
                {"feature": "token:agency"},
            ],
            "top_embedding_contributions": [
                {"feature": "cue:frame:Frame:transferred"},
                {"feature": "flogic:source_id:us-code-5-552-deadbeefdeadbeef"},
                {"feature": "flogic:belongs_to_document:us-code-46-30525.-99a6422ab828fa0c"},
                {"feature": "lemma:notice"},
            ],
        }
    )

    audit_hint = next(hint for hint in hints if hint.action == "audit_frame_logic_terms")
    assert audit_hint.evidence["frame_features"] == [
        "slot:selected_frame:administrative_notice_hearing",
        "selected-frame-term:final_order",
        "family:selected_frame:deontic",
        "cue:frame:Frame:transferred",
        "flogic:source_id:us-code-5-552-deadbeefdeadbeef",
        "flogic:belongs_to_document:us-code-46-30525.-99a6422ab828fa0c",
    ]


def test_autoencoder_legal_ir_hint_signatures_include_component_gap_lane() -> None:
    hints = synthesis_hints_from_autoencoder_introspection(
        {
            "sample_id": "us-code-5-552-deadbeefdeadbeef",
            "synthesis_focus": ["repair_tdfol_bridge_parse"],
            "legal_ir_component_gaps": {
                "TDFOL.prover": 0.24,
                "CEC.native": 0.01,
            },
            "legal_ir_predicted_view_distribution": {
                "TDFOL.prover": 0.02,
                "CEC.native": 0.10,
            },
            "legal_ir_underrepresented_components": ["TDFOL.prover"],
            "legal_ir_view_cross_entropy_loss": 1.2,
            "legal_ir_view_distribution": {
                "TDFOL.prover": 0.26,
                "CEC.native": 0.11,
            },
        }
    )

    hint = next(hint for hint in hints if hint.action == "repair_tdfol_bridge_parse")
    base_signature = residual_signature_for_hint(hint)
    shifted_hint = type(hint)(
        hint_id=hint.hint_id,
        action=hint.action,
        target_component=hint.target_component,
        rationale=hint.rationale,
        priority=hint.priority,
        evidence={
            **hint.evidence,
            "target_file_lane": "cec",
        },
    )

    assert hint.evidence["bridge_failure_name"] == "tdfol_parse_failure_ratio"
    assert hint.evidence["target_file_lane"] == "tdfol"
    assert hint.evidence["target_view"] == "TDFOL.prover"
    assert hint.evidence["predicted_view"] == "TDFOL.prover"
    assert hint.evidence["primary_legal_ir_component_gap"] == 0.24
    assert residual_signature_for_hint(shifted_hint) != base_signature

    failure_routed = synthesis_hints_from_autoencoder_introspection(
        {
            "sample_id": "us-code-5-552-deadbeefdeadbeef",
            "legal_ir_losses": {"legal_ir_multiview_proof_failure_ratio": 0.5},
        }
    )

    assert any(
        hint.action == "repair_multiview_legal_ir_prover_gate"
        for hint in failure_routed
    )


def test_logic_extractor_uses_logic_layer_modal_codec_without_llm() -> None:
    class FailingBackend:
        def generate(self, request):  # pragma: no cover - should never be called
            raise AssertionError("LLM backend should not be called for modal codec extraction")

    extractor = LogicExtractor(
        backend=FailingBackend(),
        use_ipfs_accelerate=False,
        enable_formula_translation=False,
        enable_kg_integration=False,
        enable_rag_integration=False,
    )
    context = LogicExtractionContext(
        data="The agency must make records promptly available to any person.",
        data_type=DataType.TEXT,
        domain="legal",
        config={"extraction_mode": "modal", "modal_profile": "spacy"},
        hints=["5 U.S.C. 552"],
    )

    result = extractor.extract(context)

    assert result.success is True
    assert result.statements
    assert result.metrics["llm_call_count"] == 0
    assert result.metrics["deterministic_parser"] == "spacy_modal_codec_v1"
    assert result.metrics["frame_logic_selected_frame"] == "administrative_notice_hearing"
    assert result.metrics["flogic_ontology_consistent"] is True
    assert result.metrics["cross_entropy_loss"] >= 0.0
    assert result.statements[0].formula.startswith("O[deontic:D]")
    assert result.statements[0].metadata["selected_frame"] == "administrative_notice_hearing"


def test_modal_compiler_orders_priority_adaptive_targets_before_non_priority_targets() -> None:
    ordered_targets = DeterministicModalCompiler._ordered_adaptive_target_families(
        predicted_family="frame",
        target_signal_by_family={
            "conditional_normative": False,
            "deontic": False,
            "epistemic": True,
            "temporal": False,
            "frame": False,
        },
    )

    assert ordered_targets == [
        "conditional_normative",
        "deontic",
        "epistemic",
        "temporal",
        "doxastic",
        "frame",
        "alethic",
        "dynamic",
    ]


def test_modal_compiler_includes_priority_adaptive_targets_even_when_signal_map_is_sparse() -> None:
    ordered_targets = DeterministicModalCompiler._ordered_adaptive_target_families(
        predicted_family="frame",
        target_signal_by_family={
            "frame": False,
        },
    )

    assert ordered_targets[:4] == [
        "conditional_normative",
        "deontic",
        "epistemic",
        "temporal",
    ]
    assert "frame" in ordered_targets


def test_modal_compiler_includes_compiler_required_targets_when_priority_targets_are_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.priority_signal_free_adaptive_ambiguity_targets",
        lambda _family: (),
    )

    ordered_targets = DeterministicModalCompiler._ordered_adaptive_target_families(
        predicted_family="frame",
        target_signal_by_family={
            "frame": False,
        },
    )

    assert ordered_targets[:5] == [
        "conditional_normative",
        "deontic",
        "alethic",
        "epistemic",
        "temporal",
    ]
    assert "frame" in ordered_targets


def test_modal_compiler_maps_dynamic_family_target_signals() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    target_signal_by_family = compiler._adaptive_target_signal_by_family(
        "dynamic",
        signals={
            "has_temporal_scope": True,
            "has_deontic_scope": False,
            "has_deontic_cue": True,
            "has_condition_or_exception_scope": False,
        },
        has_frame_scope=True,
    )

    assert target_signal_by_family == {
        "temporal": True,
        "deontic": True,
        "conditional_normative": False,
        "frame": True,
    }


def test_modal_compiler_maps_temporal_family_target_signals_including_dynamic() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    target_signal_by_family = compiler._adaptive_target_signal_by_family(
        "temporal",
        signals={
            "has_frame_context": False,
            "has_condition_or_exception_scope": False,
            "has_deontic_scope": False,
            "has_deontic_cue": True,
            "has_alethic_scope": False,
            "has_alethic_cue": False,
            "has_epistemic_scope": False,
            "has_epistemic_cue": False,
            "has_doxastic_scope": False,
            "has_doxastic_cue": False,
            "has_dynamic_scope": False,
            "has_dynamic_cue": True,
        },
        has_frame_scope=False,
    )

    assert target_signal_by_family["dynamic"] is True


def test_modal_compiler_surfaces_compiler_ambiguity_pairs_when_other_target_tables_are_sparse(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.signal_free_adaptive_ambiguity_targets",
        lambda _family: (),
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.priority_signal_free_adaptive_ambiguity_targets",
        lambda _family: (),
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.compiler_required_adaptive_ambiguity_targets",
        lambda _family: (),
    )

    scenarios = (
        {
            "predicted_family": "alethic",
            "system": "S5",
            "symbol": "□",
            "label": "necessary",
            "target_family": "deontic",
        },
        {
            "predicted_family": "deontic",
            "system": "D",
            "symbol": "O",
            "label": "obligation",
            "target_family": "conditional_normative",
        },
        {
            "predicted_family": "deontic",
            "system": "D",
            "symbol": "O",
            "label": "obligation",
            "target_family": "epistemic",
        },
        {
            "predicted_family": "deontic",
            "system": "D",
            "symbol": "O",
            "label": "obligation",
            "target_family": "temporal",
        },
        {
            "predicted_family": "dynamic",
            "system": "PDL",
            "symbol": "Act",
            "label": "action",
            "target_family": "temporal",
        },
        {
            "predicted_family": "frame",
            "system": "FRAME_BM25",
            "symbol": "Frame",
            "label": "frame",
            "target_family": "conditional_normative",
        },
        {
            "predicted_family": "frame",
            "system": "FRAME_BM25",
            "symbol": "Frame",
            "label": "frame",
            "target_family": "epistemic",
        },
        {
            "predicted_family": "frame",
            "system": "FRAME_BM25",
            "symbol": "Frame",
            "label": "frame",
            "target_family": "temporal",
        },
        {
            "predicted_family": "frame",
            "system": "FRAME_BM25",
            "symbol": "Frame",
            "label": "frame",
            "target_family": "doxastic",
        },
        {
            "predicted_family": "doxastic",
            "system": "KD45",
            "symbol": "B",
            "label": "belief",
            "target_family": "epistemic",
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        encoding = SpaCyLegalEncoding(
            document_id=f"compiler-ambiguity-target-fallback-{index}",
            text=f"{predicted_family} policy ambiguity evidence.",
            normalized_text=f"{predicted_family} policy ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["system"]),
                    symbol=str(scenario["symbol"]),
                    label=str(scenario["label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"compiler-ambiguity-target-fallback-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["system"]),
                        symbol=str(scenario["symbol"]),
                        label=str(scenario["label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"compiler-ambiguity-target-fallback-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=[{"family": predicted_family, "count": 1, "share": 1.0}],
            family_shares={predicted_family: 1.0},
        )

        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_compiled_primary_policy_pairs_cover_compiler_ambiguity_bundle(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    policy_scenarios = (
        {
            "compiled_primary_family": "frame",
            "family_shares": {"conditional_normative": 0.81, "frame": 0.19},
            "expected_pair": "frame->conditional_normative",
            "expected_explicit_type": "adaptive_frame_conditional_normative_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "frame",
            "family_shares": {"deontic": 0.85, "frame": 0.15},
            "expected_pair": "frame->deontic",
            "expected_explicit_type": "adaptive_frame_deontic_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "frame",
            "family_shares": {"alethic": 0.78, "frame": 0.22},
            "expected_pair": "frame->alethic",
            "expected_explicit_type": "adaptive_frame_alethic_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "frame",
            "family_shares": {"epistemic": 0.79, "frame": 0.21},
            "expected_pair": "frame->epistemic",
            "expected_explicit_type": "adaptive_frame_epistemic_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "frame",
            "family_shares": {"deontic": 0.57, "frame": 0.43},
            "expected_pair": "frame->frame",
            "expected_explicit_type": "adaptive_frame_frame_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "deontic",
            "family_shares": {"epistemic": 0.73, "deontic": 0.27},
            "expected_pair": "deontic->epistemic",
            "expected_explicit_type": "adaptive_deontic_epistemic_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "deontic",
            "family_shares": {"frame": 0.83, "deontic": 0.17},
            "expected_pair": "deontic->frame",
            "expected_explicit_type": "adaptive_deontic_frame_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "conditional_normative",
            "family_shares": {"dynamic": 0.76, "conditional_normative": 0.22},
            "expected_pair": "conditional_normative->dynamic",
            "expected_explicit_type": "adaptive_conditional_normative_dynamic_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "conditional_normative",
            "family_shares": {"deontic": 0.64, "conditional_normative": 0.51},
            "expected_pair": "conditional_normative->conditional_normative",
            "expected_explicit_type": "adaptive_conditional_normative_conditional_normative_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "frame",
            "family_shares": {"temporal": 0.58, "frame": 0.54},
            "expected_pair": "frame->temporal",
            "expected_explicit_type": "adaptive_frame_temporal_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "frame",
            "family_shares": {"doxastic": 0.77, "frame": 0.23},
            "expected_pair": "frame->doxastic",
            "expected_explicit_type": "adaptive_frame_doxastic_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "temporal",
            "family_shares": {"frame": 0.73, "temporal": 0.27},
            "expected_pair": "temporal->frame",
            "expected_explicit_type": "adaptive_temporal_frame_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "dynamic",
            "family_shares": {"temporal": 0.58, "dynamic": 0.42},
            "expected_pair": "dynamic->temporal",
            "expected_explicit_type": "adaptive_dynamic_temporal_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "alethic",
            "family_shares": {"conditional_normative": 0.88, "alethic": 0.03},
            "expected_pair": "alethic->conditional_normative",
            "expected_explicit_type": "adaptive_alethic_conditional_normative_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "alethic",
            "family_shares": {"temporal": 0.91, "alethic": 0.02},
            "expected_pair": "alethic->temporal",
            "expected_explicit_type": "adaptive_alethic_temporal_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "alethic",
            "family_shares": {"deontic": 0.84, "alethic": 0.06},
            "expected_pair": "alethic->deontic",
            "expected_explicit_type": "adaptive_alethic_deontic_outvoted_margin_low",
        },
        {
            "compiled_primary_family": "deontic",
            "family_shares": {"frame": 0.61, "deontic": 0.15},
            "expected_pair": "deontic->deontic",
            "expected_explicit_type": "adaptive_deontic_deontic_outvoted_margin_low",
        },
    )

    for scenario in policy_scenarios:
        compiled_primary_family = str(scenario["compiled_primary_family"])
        family_shares = {
            str(family): float(share)
            for family, share in dict(scenario["family_shares"]).items()
        }
        ranking = [
            {"family": family, "count": 1, "share": share}
            for family, share in sorted(
                family_shares.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]
        encoding = SpaCyLegalEncoding(
            document_id=f"compiled-primary-policy-{compiled_primary_family}-doc",
            text=f"{compiled_primary_family} scope test text.",
            normalized_text=f"{compiled_primary_family} scope test text.",
            tokens=[],
            sentences=[],
            cues=[],
        )
        modal_ir = ModalIRDocument(
            document_id=f"compiled-primary-policy-{compiled_primary_family}-doc",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{compiled_primary_family}-1",
                    operator=ModalIROperator(
                        family=compiled_primary_family,
                        system="D",
                        symbol="O",
                        label=compiled_primary_family,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{compiled_primary_family}_policy_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"compiled-primary-policy-{compiled_primary_family}-doc",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
        )

        explicit_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == scenario["expected_explicit_type"]
            and ambiguity.metadata["adaptive_predicted_family_source"]
            == "compiled_primary_family"
            and ambiguity.metadata["adaptive_policy_pair"] == scenario["expected_pair"]
        )
        assert explicit_ambiguity.metadata["adaptive_base_ambiguity_type"] == (
            "adaptive_family_margin_low"
        )


def test_modal_compiler_emits_explicit_ambiguity_for_required_margin_bundle_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "doc_id": "required-alethic-temporal-margin-doc",
            "predicted_family": "alethic",
            "predicted_system": "S5",
            "predicted_symbol": "◇",
            "predicted_label": "possible",
            "target_family": "temporal",
            "ranking": (
                {"family": "alethic", "count": 1, "share": 0.977709660314},
                {"family": "temporal", "count": 1, "share": 0.022290339686},
            ),
            "family_margin": -0.955419320628,
            "adaptive_priority": 1.105419320628,
            "expected_explicit_type": "adaptive_alethic_temporal_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-alethic-deontic-margin-doc",
            "predicted_family": "alethic",
            "predicted_system": "S5",
            "predicted_symbol": "◇",
            "predicted_label": "possible",
            "target_family": "deontic",
            "ranking": (
                {"family": "alethic", "count": 1, "share": 0.91},
                {"family": "deontic", "count": 1, "share": 0.09},
            ),
            "family_margin": -0.82,
            "adaptive_priority": 0.97,
            "expected_explicit_type": "adaptive_alethic_deontic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-alethic-conditional-margin-doc",
            "predicted_family": "alethic",
            "predicted_system": "S5",
            "predicted_symbol": "◇",
            "predicted_label": "possible",
            "target_family": "conditional_normative",
            "ranking": (
                {"family": "alethic", "count": 1, "share": 0.999999793443},
                {
                    "family": "conditional_normative",
                    "count": 1,
                    "share": 0.000000206557,
                },
            ),
            "family_margin": -0.999999586886,
            "adaptive_priority": 1.149999586886,
            "expected_explicit_type": (
                "adaptive_alethic_conditional_normative_outvoted_margin_low"
            ),
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-alethic-epistemic-margin-doc",
            "predicted_family": "alethic",
            "predicted_system": "S5",
            "predicted_symbol": "◇",
            "predicted_label": "possible",
            "target_family": "epistemic",
            "ranking": (
                {"family": "alethic", "count": 1, "share": 0.663243323138},
                {"family": "epistemic", "count": 1, "share": 0.336756676862},
            ),
            "family_margin": -0.326486646276,
            "adaptive_priority": 0.476486646276,
            "expected_explicit_type": "adaptive_alethic_epistemic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-alethic-frame-margin-doc",
            "predicted_family": "alethic",
            "predicted_system": "S5",
            "predicted_symbol": "◇",
            "predicted_label": "possible",
            "target_family": "frame",
            "ranking": (
                {"family": "alethic", "count": 1, "share": 0.873489298146},
                {"family": "frame", "count": 1, "share": 0.126510701854},
            ),
            "family_margin": -0.746978596292,
            "adaptive_priority": 0.896978596292,
            "expected_explicit_type": "adaptive_alethic_frame_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-conditional-deontic-margin-doc",
            "predicted_family": "conditional_normative",
            "predicted_system": "STIT",
            "predicted_symbol": "O_if",
            "predicted_label": "conditional_obligation",
            "target_family": "deontic",
            "ranking": (
                {"family": "conditional_normative", "count": 1, "share": 0.590486507},
                {"family": "deontic", "count": 1, "share": 0.409513493},
            ),
            "family_margin": -0.180973014,
            "adaptive_priority": 0.330973014,
            "expected_explicit_type": (
                "adaptive_conditional_normative_deontic_outvoted_margin_low"
            ),
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-temporal-deontic-margin-doc",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "ranking": (
                {"family": "temporal", "count": 1, "share": 0.620580769566},
                {"family": "deontic", "count": 1, "share": 0.379419230433},
            ),
            "family_margin": -0.241161539133,
            "adaptive_priority": 0.391161539133,
            "expected_explicit_type": "adaptive_temporal_deontic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-temporal-conditional-margin-doc",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "conditional_normative",
            "ranking": (
                {"family": "temporal", "count": 1, "share": 1.0},
                {"family": "conditional_normative", "count": 1, "share": 0.760266802459},
            ),
            "family_margin": -0.239733197541,
            "adaptive_priority": 0.389733197541,
            "expected_explicit_type": (
                "adaptive_temporal_conditional_normative_outvoted_margin_low"
            ),
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-temporal-conditional-margin-sample-0909a1e0af9b1e3b",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "conditional_normative",
            "ranking": (
                {"family": "temporal", "count": 1, "share": 0.594370104256},
                {
                    "family": "conditional_normative",
                    "count": 1,
                    "share": 0.405629895743,
                },
            ),
            "family_margin": -0.188740208513,
            "adaptive_priority": 0.338740208513,
            "expected_explicit_type": (
                "adaptive_temporal_conditional_normative_outvoted_margin_low"
            ),
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-temporal-conditional-margin-sample-adb2f85bc55b98ec",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "conditional_normative",
            "ranking": (
                {"family": "temporal", "count": 1, "share": 0.522768537761},
                {
                    "family": "conditional_normative",
                    "count": 1,
                    "share": 0.477231462239,
                },
            ),
            "family_margin": -0.045537075522,
            "adaptive_priority": 0.195537075522,
            "expected_explicit_type": (
                "adaptive_temporal_conditional_normative_outvoted_margin_low"
            ),
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-temporal-frame-margin-doc",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "frame",
            "ranking": (
                {"family": "temporal", "count": 1, "share": 0.6786708848205},
                {"family": "frame", "count": 1, "share": 0.3213291151795},
            ),
            "family_margin": -0.357341769641,
            "adaptive_priority": 0.507341769641,
            "expected_explicit_type": "adaptive_temporal_frame_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-deontic-conditional-margin-doc",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "conditional_normative",
            "ranking": (
                {"family": "deontic", "count": 1, "share": 0.615603838423},
                {"family": "conditional_normative", "count": 1, "share": 0.384396161578},
            ),
            "family_margin": -0.231207676845,
            "adaptive_priority": 0.381207676845,
            "expected_explicit_type": (
                "adaptive_deontic_conditional_normative_outvoted_margin_low"
            ),
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-deontic-dynamic-margin-doc",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "dynamic",
            "ranking": (
                {"family": "deontic", "count": 1, "share": 0.715539558963},
                {"family": "dynamic", "count": 1, "share": 0.284460441037},
            ),
            "family_margin": -0.431079117926,
            "adaptive_priority": 0.581079117926,
            "expected_explicit_type": "adaptive_deontic_dynamic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-deontic-epistemic-margin-doc",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "epistemic",
            "ranking": (
                {"family": "deontic", "count": 1, "share": 0.663964931589},
                {"family": "epistemic", "count": 1, "share": 0.336035068411},
            ),
            "family_margin": -0.327929863178,
            "adaptive_priority": 0.477929863178,
            "expected_explicit_type": "adaptive_deontic_epistemic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-deontic-self-margin-doc",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "deontic",
            "ranking": (
                {"family": "deontic", "count": 1, "share": 0.515852321787},
                {"family": "temporal", "count": 1, "share": 0.484147678213},
            ),
            "family_margin": 0.031704643574,
            "adaptive_priority": 0.118295356426,
            "expected_explicit_type": "adaptive_deontic_deontic_contested_margin_low",
            "expected_severity": "review",
            "is_self_pair": True,
        },
        {
            "doc_id": "required-deontic-temporal-margin-doc",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "temporal",
            "ranking": (
                {"family": "deontic", "count": 1, "share": 0.740130573968},
                {"family": "temporal", "count": 1, "share": 0.259869426031},
            ),
            "family_margin": -0.480261147937,
            "adaptive_priority": 0.630261147937,
            "expected_explicit_type": "adaptive_deontic_temporal_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-deontic-frame-margin-doc",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "frame",
            "ranking": (
                {"family": "deontic", "count": 1, "share": 0.777987422874},
                {"family": "frame", "count": 1, "share": 0.222012577126},
            ),
            "family_margin": -0.555974845748,
            "adaptive_priority": 0.705974845748,
            "expected_explicit_type": "adaptive_deontic_frame_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-frame-deontic-margin-doc",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.999983184018},
                {"family": "deontic", "count": 1, "share": 0.000016815982},
            ),
            "family_margin": -0.999966368036,
            "adaptive_priority": 1.149966368036,
            "expected_explicit_type": "adaptive_frame_deontic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-frame-alethic-margin-doc",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "alethic",
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.803},
                {"family": "alethic", "count": 1, "share": 0.197},
            ),
            "family_margin": -0.606,
            "adaptive_priority": 0.756,
            "expected_explicit_type": "adaptive_frame_alethic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-frame-conditional-margin-doc",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "conditional_normative",
            "ranking": (
                {"family": "frame", "count": 1, "share": 1.0},
                {"family": "conditional_normative", "count": 1, "share": 0.742899391998},
            ),
            "family_margin": -0.257100608002,
            "adaptive_priority": 0.407100608002,
            "expected_explicit_type": (
                "adaptive_frame_conditional_normative_outvoted_margin_low"
            ),
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-frame-epistemic-margin-doc",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "epistemic",
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.726803583105},
                {"family": "epistemic", "count": 1, "share": 0.273196416896},
            ),
            "family_margin": -0.453607166209,
            "adaptive_priority": 0.603607166209,
            "expected_explicit_type": "adaptive_frame_epistemic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-frame-temporal-margin-doc",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "temporal",
            "ranking": (
                {"family": "frame", "count": 1, "share": 1.0},
                {"family": "temporal", "count": 1, "share": 0.004924258631},
            ),
            "family_margin": -0.995075741369,
            "adaptive_priority": 1.145075741369,
            "expected_explicit_type": "adaptive_frame_temporal_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
        },
        {
            "doc_id": "required-frame-self-margin-doc",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "frame",
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.522970476002},
                {"family": "temporal", "count": 1, "share": 0.477029523998},
            ),
            "family_margin": 0.045940952004,
            "adaptive_priority": 0.104059047996,
            "expected_explicit_type": "adaptive_frame_frame_contested_margin_low",
            "expected_severity": "review",
            "is_self_pair": True,
        },
    )
    for scenario in scenarios:
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        ranking = [dict(item) for item in tuple(scenario["ranking"])]
        family_shares = {
            str(item["family"]): float(item["share"]) for item in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=str(scenario["doc_id"]),
            text=f"{predicted_family} ambiguity evidence.",
            normalized_text=f"{predicted_family} ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=str(scenario["doc_id"]),
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-1",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=str(scenario["doc_id"]),
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
        )

        expected_candidate_ids = (
            [predicted_family]
            if bool(scenario["is_self_pair"])
            else [predicted_family, target_family]
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"]
            == f"{predicted_family}->{target_family}"
        )
        assert base_ambiguity.metadata["is_compiler_required_policy_pair"] is True
        assert (
            abs(
                float(base_ambiguity.metadata["family_margin_raw"])
                - float(scenario["family_margin"])
            )
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["adaptive_priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.severity == str(scenario["expected_severity"])
        assert (
            base_ambiguity.metadata["explicit_ambiguity_type"]
            == scenario["expected_explicit_type"]
        )
        assert any(
            ambiguity.ambiguity_type == scenario["expected_explicit_type"]
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            and ambiguity.metadata["is_compiler_required_policy_pair"] is True
            for ambiguity in ambiguities
        )


def test_modal_compiler_emits_explicit_ambiguity_for_todo_evidence_margin_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    evidence_scenarios = (
        {
            "predicted_family": "frame",
            "predicted_label": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "target_family": "temporal",
            "family_margin": -0.999907091831,
            "priority": 1.149907091831,
        },
        {
            "predicted_family": "alethic",
            "predicted_label": "possible",
            "predicted_system": "S5",
            "predicted_symbol": "◇",
            "target_family": "temporal",
            "family_margin": -0.795219252903,
            "priority": 0.945219252903,
        },
        {
            "predicted_family": "alethic",
            "predicted_label": "possible",
            "predicted_system": "S5",
            "predicted_symbol": "◇",
            "target_family": "conditional_normative",
            "family_margin": -0.896839706151,
            "priority": 1.046839706151,
        },
        {
            "predicted_family": "alethic",
            "predicted_label": "possible",
            "predicted_system": "S5",
            "predicted_symbol": "◇",
            "target_family": "epistemic",
            "family_margin": -0.326486646276,
            "priority": 0.476486646276,
        },
        {
            "predicted_family": "frame",
            "predicted_label": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "target_family": "deontic",
            "family_margin": -0.99240219376,
            "priority": 1.14240219376,
        },
        {
            "predicted_family": "frame",
            "predicted_label": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "target_family": "epistemic",
            "family_margin": -0.957919173467,
            "priority": 1.107919173467,
        },
        {
            "predicted_family": "temporal",
            "predicted_label": "eventually",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "target_family": "deontic",
            "family_margin": -0.137812866903,
            "priority": 0.287812866903,
        },
        {
            "predicted_family": "frame",
            "predicted_label": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "target_family": "deontic",
            "family_margin": -0.228446639842,
            "priority": 0.378446639842,
        },
        {
            "predicted_family": "frame",
            "predicted_label": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "target_family": "conditional_normative",
            "family_margin": -0.963281367381,
            "priority": 1.113281367381,
        },
        {
            "predicted_family": "conditional_normative",
            "predicted_label": "conditional_obligation",
            "predicted_system": "KD",
            "predicted_symbol": "O|",
            "target_family": "deontic",
            "family_margin": -0.132081408712,
            "priority": 0.282081408712,
        },
        {
            "predicted_family": "conditional_normative",
            "predicted_label": "conditional_obligation",
            "predicted_system": "KD",
            "predicted_symbol": "O|",
            "target_family": "temporal",
            "family_margin": -0.284224385856,
            "priority": 0.434224385856,
        },
        {
            "predicted_family": "frame",
            "predicted_label": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "target_family": "deontic",
            "family_margin": -0.9045986346,
            "priority": 1.0545986346,
        },
        {
            "predicted_family": "deontic",
            "predicted_label": "obligation",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "target_family": "epistemic",
            "family_margin": -0.663964931589,
            "priority": 0.813964931589,
        },
        {
            "predicted_family": "deontic",
            "predicted_label": "obligation",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "target_family": "conditional_normative",
            "family_margin": -0.914900774437,
            "priority": 1.064900774437,
        },
        {
            "predicted_family": "frame",
            "predicted_label": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "target_family": "conditional_normative",
            "family_margin": -0.988780738882,
            "priority": 1.138780738882,
        },
        {
            "predicted_family": "deontic",
            "predicted_label": "obligation",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "target_family": "temporal",
            "family_margin": -0.75246836579,
            "priority": 0.90246836579,
        },
        {
            "predicted_family": "alethic",
            "predicted_label": "necessary",
            "predicted_system": "S5",
            "predicted_symbol": "□",
            "target_family": "deontic",
            "family_margin": -0.360131386457,
            "priority": 0.510131386457,
        },
        {
            "predicted_family": "frame",
            "predicted_label": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "target_family": "temporal",
            "family_margin": -0.617309325395,
            "priority": 0.767309325395,
        },
        {
            "predicted_family": "temporal",
            "predicted_label": "eventually",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "target_family": "frame",
            "family_margin": -0.323976645241,
            "priority": 0.473976645241,
        },
        {
            "predicted_family": "deontic",
            "predicted_label": "obligation",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "target_family": "frame",
            "family_margin": -0.519826174925,
            "priority": 0.669826174925,
        },
        {
            "predicted_family": "temporal",
            "predicted_label": "eventually",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "target_family": "dynamic",
            "family_margin": -0.355497544709,
            "priority": 0.505497544709,
        },
        {
            "predicted_family": "temporal",
            "predicted_label": "eventually",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "target_family": "deontic",
            "family_margin": -0.480606797373,
            "priority": 0.630606797373,
        },
    )

    for index, scenario in enumerate(evidence_scenarios):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        predicted_share = abs(float(scenario["family_margin"]))
        ranking = [
            {
                "family": predicted_family,
                "count": 1,
                "share_raw": predicted_share,
                "share": predicted_share,
            }
        ]
        family_shares = {predicted_family: predicted_share}
        encoding = SpaCyLegalEncoding(
            document_id=f"todo-evidence-margin-doc-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"todo-evidence-margin-doc-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-1",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"todo-evidence-margin-doc-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"]
            == f"{predicted_family}->{target_family}"
        )
        assert (
            abs(
                float(base_ambiguity.metadata["family_margin_raw"])
                - float(scenario["family_margin"])
            )
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_emits_explicit_temporal_self_pair_for_todo_margin_evidence(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    predicted_share = 0.5510995070365
    runner_up_share = 0.4489004929635
    expected_margin = 0.102199014073
    expected_priority = 0.047800985927
    encoding = SpaCyLegalEncoding(
        document_id="todo-evidence-margin-temporal-self-doc",
        text="temporal ambiguity evidence",
        normalized_text="temporal ambiguity evidence",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="temporal",
                system="LTL",
                symbol="F",
                label="eventually",
                cue="evidence",
                start_char=0,
                end_char=8,
                token_indices=[],
            )
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="todo-evidence-margin-temporal-self-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-temporal-1",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="temporal_scope",
                    arguments=["scope:test"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="todo-evidence-margin-temporal-self-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                ),
            )
        ],
    )

    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {
                "family": "temporal",
                "count": 1,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": "deontic",
                "count": 1,
                "share_raw": runner_up_share,
                "share": runner_up_share,
            },
        ],
        family_shares={
            "temporal": predicted_share,
            "deontic": runner_up_share,
        },
        predicted_family_source="adaptive_logits_fallback",
    )

    base_ambiguity = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["temporal"]
        and ambiguity.metadata["adaptive_policy_pair"] == "temporal->temporal"
    )
    assert (
        abs(float(base_ambiguity.metadata["family_margin_raw"]) - expected_margin)
        < 1e-12
    )
    assert (
        abs(float(base_ambiguity.metadata["adaptive_priority"]) - expected_priority)
        < 1e-12
    )
    assert (
        base_ambiguity.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_temporal_contested_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_temporal_contested_margin_low"
        and ambiguity.candidate_ids == ["temporal"]
        and ambiguity.metadata["adaptive_base_ambiguity_type"]
        == "adaptive_family_margin_low"
        for ambiguity in ambiguities
    )


def test_modal_compiler_surfaces_packet_001757_temporal_policy_explicit_ambiguities(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    evidence_scenarios = (
        {
            "sample_id": "us-code-15-1157-05e893471f1ae618",
            "target_family": "deontic",
            "family_margin": -0.586281164377,
            "priority": 0.736281164377,
        },
        {
            "sample_id": "us-code-43-2433.-113e10b590ccab47",
            "target_family": "deontic",
            "family_margin": 0.0,
            "priority": 0.15,
        },
        {
            "sample_id": "us-code-42-1778.-dcb7b7781a0537fc",
            "target_family": "deontic",
            "family_margin": -0.403348242824,
            "priority": 0.553348242824,
        },
        {
            "sample_id": "us-code-20-105-3bc06fa3f2129cb5",
            "target_family": "temporal",
            "family_margin": 0.0,
            "priority": 0.15,
        },
    )

    for scenario in evidence_scenarios:
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        predicted_share = abs(family_margin)
        competing_share = max(0.0, predicted_share + family_margin)
        ranking = [
            {
                "family": "temporal",
                "count": 1,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": "deontic",
                "count": 1,
                "share_raw": competing_share,
                "share": competing_share,
            },
        ]
        family_shares = {
            "temporal": predicted_share,
            "deontic": competing_share,
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001757-{scenario['sample_id']}",
            text="temporal ambiguity evidence",
            normalized_text="temporal ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-001757-{scenario['sample_id']}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id="f-temporal-1",
                    operator=ModalIROperator(
                        family="temporal",
                        system="LTL",
                        symbol="F",
                        label="eventually",
                    ),
                    predicate=ModalIRPredicate(
                        name="temporal_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-001757-{scenario['sample_id']}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        if target_family == "temporal":
            expected_policy_pair = "temporal->temporal"
            expected_candidate_ids = ["temporal"]
            expected_explicit_type = "adaptive_temporal_temporal_outvoted_margin_low"
        else:
            expected_policy_pair = "temporal->deontic"
            expected_candidate_ids = ["temporal", "deontic"]
            expected_explicit_type = "adaptive_temporal_deontic_outvoted_margin_low"

        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.metadata["adaptive_policy_pair"] == expected_policy_pair
        )
        assert base_ambiguity.candidate_ids == expected_candidate_ids
        assert base_ambiguity.severity == "requires_rule"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.metadata["adaptive_policy_pair"] == expected_policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_003180_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-7-1442-9c3eb758f9c3d50a",
            "predicted_family": "conditional_normative",
            "predicted_system": "KD",
            "predicted_symbol": "O|",
            "predicted_label": "conditional_obligation",
            "runner_up_family": "deontic",
            "predicted_share": 0.5028255615515,
            "runner_up_share": 0.4971744384485,
            "target_family": "conditional_normative",
            "expected_margin": 0.005651123103,
            "expected_priority": 0.144348876897,
            "expected_direction": "contested",
            "expected_severity": "review",
        },
        {
            "sample_id": "us-code-20-7801-2cb1416418ce0f8b",
            "predicted_family": "conditional_normative",
            "predicted_system": "KD",
            "predicted_symbol": "O|",
            "predicted_label": "conditional_obligation",
            "runner_up_family": "deontic",
            "predicted_share": 0.5729236462175,
            "runner_up_share": 0.4270763537825,
            "target_family": "conditional_normative",
            "expected_margin": 0.145847292435,
            "expected_priority": 0.004152707565,
            "expected_direction": "contested",
            "expected_severity": "review",
        },
        {
            "sample_id": "us-code-22-1965-5d11565285d697d5",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "runner_up_family": "temporal",
            "predicted_share": 0.5097609258485,
            "runner_up_share": 0.4902390741515,
            "target_family": "deontic",
            "expected_margin": 0.019521851697,
            "expected_priority": 0.130478148303,
            "expected_direction": "contested",
            "expected_severity": "review",
        },
        {
            "sample_id": "us-code-52-21072.-fdd5f01270342a32",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "runner_up_family": "temporal",
            "predicted_share": 0.535811295923,
            "runner_up_share": 0.464188704077,
            "target_family": "deontic",
            "expected_margin": 0.071622591846,
            "expected_priority": 0.078377408154,
            "expected_direction": "contested",
            "expected_severity": "review",
        },
        {
            "sample_id": "us-code-28-1694-26ba8fda6cf59f72",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "runner_up_family": "deontic",
            "predicted_share": 0.586405449861,
            "runner_up_share": 0.413594550139,
            "target_family": "deontic",
            "expected_margin": -0.172810899722,
            "expected_priority": 0.322810899722,
            "expected_direction": "outvoted",
            "expected_severity": "requires_rule",
        },
    )

    for scenario in scenarios:
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        runner_up_family = str(scenario["runner_up_family"])
        predicted_share = float(scenario["predicted_share"])
        runner_up_share = float(scenario["runner_up_share"])
        expected_policy_pair = f"{predicted_family}->{target_family}"
        expected_is_self_pair = predicted_family == target_family
        expected_candidate_ids = (
            [predicted_family]
            if expected_is_self_pair
            else [predicted_family, target_family]
        )
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{scenario['expected_direction']}_margin_low"
        )

        ranking = [
            {
                "family": predicted_family,
                "count": 1,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": runner_up_family,
                "count": 1,
                "share_raw": runner_up_share,
                "share": runner_up_share,
            },
        ]
        family_shares = {
            predicted_family: predicted_share,
            runner_up_family: runner_up_share,
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-003180-{scenario['sample_id']}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-003180-{scenario['sample_id']}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-1",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-003180-{scenario['sample_id']}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == expected_policy_pair
        )
        assert base_ambiguity.metadata["adaptive_margin_direction"] == str(
            scenario["expected_direction"]
        )
        assert base_ambiguity.severity == str(scenario["expected_severity"])
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(
                float(base_ambiguity.metadata["family_margin_raw"])
                - float(scenario["expected_margin"])
            )
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["expected_priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_marks_todo_policy_pairs_as_compiler_ambiguity_bundle(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "temporal",
            "family_margin": -0.87157850633,
            "priority": 1.02157850633,
        },
        {
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "frame",
            "family_margin": -0.58228743692,
            "priority": 0.73228743692,
        },
        {
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.99126278774,
            "priority": 1.14126278774,
        },
        {
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "epistemic",
            "family_margin": -0.957919173467,
            "priority": 1.107919173467,
        },
        {
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "temporal",
            "family_margin": -0.356459015591,
            "priority": 0.506459015591,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        predicted_share = abs(family_margin)
        encoding = SpaCyLegalEncoding(
            document_id=f"todo-policy-pair-compiler-bundle-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"todo-policy-pair-compiler-bundle-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"todo-policy-pair-compiler-bundle-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=[
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                }
            ],
            family_shares={predicted_family: predicted_share},
            predicted_family_source="adaptive_logits_fallback",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000472_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-42-629c.-0c65fdd9d705e10f",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "conditional_normative",
            "family_margin": -0.993831777206,
            "priority": 1.143831777206,
            "is_self_pair": False,
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.993831777206},
            ),
        },
        {
            "sample_id": "us-code-42-1462 to 1464.-d3f2aa981c9b2a49",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "conditional_normative",
            "family_margin": -0.997248992505,
            "priority": 1.147248992505,
            "is_self_pair": False,
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.997248992505},
            ),
        },
        {
            "sample_id": "us-code-5-3322-9e1940d99b2f959b",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "conditional_normative",
            "family_margin": -0.100948406036,
            "priority": 0.250948406036,
            "is_self_pair": False,
            "ranking": (
                {"family": "temporal", "count": 1, "share": 0.100948406036},
            ),
        },
        {
            "sample_id": "us-code-7-7938-2cfe2905ba85c147",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "conditional_normative",
            "family_margin": -0.855052736961,
            "priority": 1.005052736961,
            "is_self_pair": False,
            "ranking": (
                {"family": "deontic", "count": 1, "share": 0.855052736961},
            ),
        },
        {
            "sample_id": "us-code-16-3839bb-4-2e2cffbbcd871d5d",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "conditional_normative",
            "family_margin": -0.257220043655,
            "priority": 0.407220043655,
            "is_self_pair": False,
            "ranking": (
                {"family": "deontic", "count": 1, "share": 0.257220043655},
            ),
        },
        {
            "sample_id": "us-code-49-47145.-6f26cd3923bc5e97",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.963701676952,
            "priority": 1.113701676952,
            "is_self_pair": False,
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.963701676952},
            ),
        },
        {
            "sample_id": "us-code-43-3206.-3d30a15d59827936",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "deontic",
            "family_margin": 0.0,
            "priority": 0.15,
            "is_self_pair": True,
            "ranking": (
                {"family": "deontic", "count": 1, "share": 0.5},
                {"family": "temporal", "count": 1, "share": 0.5},
            ),
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        ranking = [dict(item) for item in tuple(scenario["ranking"])]
        family_shares = {
            str(item["family"]): float(item["share"]) for item in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000472-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000472-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-000472-policy-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        expected_candidate_ids = (
            [predicted_family]
            if bool(scenario["is_self_pair"])
            else [predicted_family, target_family]
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(
                float(base_ambiguity.metadata["family_margin_raw"])
                - float(scenario["family_margin"])
            )
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.severity == "requires_rule"
        assert (
            base_ambiguity.metadata["explicit_ambiguity_type"]
            == expected_explicit_type
        )
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000566_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-15-1693i-c5b32e9682c65bf6",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "dynamic",
            "family_margin": -0.494646959627,
            "priority": 0.644646959627,
            "is_self_pair": False,
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.494646959627},
            ),
        },
        {
            "sample_id": "us-code-25-2105-2805749f4deed141",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "deontic",
            "family_margin": 0.0,
            "priority": 0.15,
            "is_self_pair": True,
            "ranking": (
                {"family": "deontic", "count": 1, "share": 0.5},
                {"family": "temporal", "count": 1, "share": 0.5},
            ),
        },
        {
            "sample_id": "us-code-36-230504-78cb5c6be6527fc3",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "conditional_normative",
            "family_margin": -0.697957799282,
            "priority": 0.847957799282,
            "is_self_pair": False,
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.697957799282},
            ),
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        ranking = [dict(item) for item in tuple(scenario["ranking"])]
        family_shares = {
            str(item["family"]): float(item["share"]) for item in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000566-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000566-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-000566-policy-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        expected_candidate_ids = (
            [predicted_family]
            if bool(scenario["is_self_pair"])
            else [predicted_family, target_family]
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(
                float(base_ambiguity.metadata["family_margin_raw"])
                - float(scenario["family_margin"])
            )
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert (
            float(base_ambiguity.metadata["family_margin"])
            == round(float(scenario["family_margin"]), 6)
        )
        assert base_ambiguity.severity == "requires_rule"
        assert (
            base_ambiguity.metadata["explicit_ambiguity_type"]
            == expected_explicit_type
        )
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000571_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-12-5707-a20569681a642369",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "conditional_normative",
            "family_margin": -0.930605805155,
            "priority": 1.080605805155,
            "is_self_pair": False,
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.930605805155},
            ),
        },
        {
            "sample_id": "us-code-10-687-62134f1eaa130df9",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "temporal",
            "family_margin": -0.823053456348,
            "priority": 0.973053456348,
            "is_self_pair": False,
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.823053456348},
            ),
        },
        {
            "sample_id": "us-code-6-924-46b4e91da16607f0",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "temporal",
            "family_margin": 0.0,
            "priority": 0.15,
            "is_self_pair": True,
            "ranking": (
                {"family": "temporal", "count": 1, "share": 0.5},
                {"family": "frame", "count": 1, "share": 0.5},
            ),
        },
        {
            "sample_id": "us-code-42-10225.-8bd3296ec2ba451b",
            "predicted_family": "conditional_normative",
            "predicted_system": "KD",
            "predicted_symbol": "O|",
            "predicted_label": "conditional_obligation",
            "target_family": "temporal",
            "family_margin": -0.469089453834,
            "priority": 0.619089453834,
            "is_self_pair": False,
            "ranking": (
                {
                    "family": "conditional_normative",
                    "count": 1,
                    "share": 0.469089453834,
                },
            ),
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        ranking = [dict(item) for item in tuple(scenario["ranking"])]
        family_shares = {
            str(item["family"]): float(item["share"]) for item in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000571-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000571-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-000571-policy-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        expected_candidate_ids = (
            [predicted_family]
            if bool(scenario["is_self_pair"])
            else [predicted_family, target_family]
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(
                float(base_ambiguity.metadata["family_margin_raw"])
                - float(scenario["family_margin"])
            )
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert (
            float(base_ambiguity.metadata["family_margin"])
            == round(float(scenario["family_margin"]), 6)
        )
        assert base_ambiguity.severity == "requires_rule"
        assert (
            base_ambiguity.metadata["explicit_ambiguity_type"]
            == expected_explicit_type
        )
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000352_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-15-4407-784d592040b9b0e4",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.848833625479,
            "priority": 0.998833625479,
            "margin_direction": "outvoted",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.848833625479},
            ),
        },
        {
            "sample_id": "us-code-16-423i-2b07507e97aa7637",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "temporal",
            "family_margin": -0.605183972302,
            "priority": 0.755183972302,
            "margin_direction": "outvoted",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.605183972302},
            ),
        },
        {
            "sample_id": "us-code-26-241-490b4fbe06272fbe",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "temporal",
            "family_margin": -0.430679318188,
            "priority": 0.580679318188,
            "margin_direction": "outvoted",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
            "ranking": (
                {"family": "deontic", "count": 1, "share": 0.430679318188},
            ),
        },
        {
            "sample_id": "us-code-48-1392b.-2fa16cf7562506ec",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "frame",
            "family_margin": -0.646104845658,
            "priority": 0.796104845658,
            "margin_direction": "outvoted",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
            "ranking": (
                {"family": "temporal", "count": 1, "share": 0.646104845658},
            ),
        },
        {
            "sample_id": "us-code-42-6250d.-3dd017ccfa5d3f72",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "conditional_normative",
            "family_margin": -0.647754849127,
            "priority": 0.797754849127,
            "margin_direction": "outvoted",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
            "ranking": (
                {"family": "temporal", "count": 1, "share": 0.647754849127},
            ),
        },
        {
            "sample_id": "us-code-15-2305-83f6a735e1c266af",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.193521012315,
            "priority": 0.343521012315,
            "margin_direction": "outvoted",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
            "ranking": (
                {"family": "temporal", "count": 1, "share": 0.193521012315},
            ),
        },
        {
            "sample_id": "us-code-42-9858p.-eaedff6fc6633cf1",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "conditional_normative",
            "family_margin": -0.733952923504,
            "priority": 0.883952923504,
            "margin_direction": "outvoted",
            "expected_severity": "requires_rule",
            "is_self_pair": False,
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.733952923504},
            ),
        },
        {
            "sample_id": "us-code-19-536-014e91bc0d5b97af",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "frame",
            "family_margin": 0.068272092928,
            "priority": 0.081727907072,
            "margin_direction": "contested",
            "expected_severity": "review",
            "is_self_pair": True,
            "ranking": (
                {"family": "frame", "count": 1, "share": 0.534136046464},
                {"family": "temporal", "count": 1, "share": 0.465863953536},
            ),
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        ranking = [dict(item) for item in tuple(scenario["ranking"])]
        family_shares = {
            str(item["family"]): float(item["share"]) for item in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000352-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000352-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-000352-policy-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        expected_candidate_ids = (
            [predicted_family]
            if bool(scenario["is_self_pair"])
            else [predicted_family, target_family]
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_"
            f"{scenario['margin_direction']}_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(
                float(base_ambiguity.metadata["family_margin_raw"])
                - float(scenario["family_margin"])
            )
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert (
            float(base_ambiguity.metadata["family_margin"])
            == round(float(scenario["family_margin"]), 6)
        )
        assert (
            base_ambiguity.metadata["adaptive_margin_direction"]
            == scenario["margin_direction"]
        )
        assert base_ambiguity.severity == scenario["expected_severity"]
        assert (
            base_ambiguity.metadata["explicit_ambiguity_type"]
            == expected_explicit_type
        )
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_001621_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "alethic",
            "family_margin": -0.803655911749,
            "priority": 0.953655911749,
            "is_self_pair": False,
        },
        {
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.513840333453,
            "priority": 0.663840333453,
            "is_self_pair": False,
        },
        {
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": 0.0,
            "priority": 0.15,
            "is_self_pair": False,
        },
        {
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "frame",
            "family_margin": 0.068272092928,
            "priority": 0.081727907072,
            "is_self_pair": True,
            "runner_up_family": "temporal",
        },
        {
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "temporal",
            "family_margin": 0.021625387389,
            "priority": 0.128374612611,
            "is_self_pair": True,
            "runner_up_family": "frame",
        },
        {
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "frame",
            "family_margin": -0.726815054768,
            "priority": 0.876815054768,
            "is_self_pair": False,
        },
        {
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "frame",
            "family_margin": -0.788356373082,
            "priority": 0.938356373082,
            "is_self_pair": False,
        },
        {
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "epistemic",
            "family_margin": -0.432748136878,
            "priority": 0.582748136878,
            "is_self_pair": False,
        },
        {
            "predicted_family": "conditional_normative",
            "predicted_system": "KD",
            "predicted_symbol": "O_if",
            "predicted_label": "conditional_obligation",
            "target_family": "deontic",
            "family_margin": -0.088931098247,
            "priority": 0.238931098247,
            "is_self_pair": False,
        },
        {
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "temporal",
            "family_margin": -0.23602129703,
            "priority": 0.38602129703,
            "is_self_pair": False,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        is_self_pair = bool(scenario["is_self_pair"])

        if is_self_pair:
            runner_up_family = str(
                scenario.get(
                    "runner_up_family",
                    "frame" if predicted_family != "frame" else "temporal",
                )
            )
            predicted_share = (1.0 + family_margin) / 2.0
            runner_up_share = predicted_share - family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 1,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        elif abs(family_margin) <= 1e-12:
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": 0.5,
                    "share": 0.5,
                },
                {
                    "family": target_family,
                    "count": 1,
                    "share_raw": 0.5,
                    "share": 0.5,
                },
            ]
        else:
            predicted_share = abs(family_margin)
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                }
            ]

        family_shares = {
            str(item["family"]): float(item["share_raw"])
            for item in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001621-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-001621-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-001621-policy-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        expected_candidate_ids = (
            [predicted_family]
            if is_self_pair
            else [predicted_family, target_family]
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_direction = (
            "contested"
            if is_self_pair and family_margin > 0.0
            else "outvoted"
        )
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{expected_direction}_margin_low"
        )
        expected_severity = (
            "review" if expected_direction == "contested" else "requires_rule"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.metadata["adaptive_margin_direction"] == expected_direction
        assert base_ambiguity.severity == expected_severity
        assert (
            base_ambiguity.metadata["explicit_ambiguity_type"]
            == expected_explicit_type
        )
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_001641_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-42-11252.-bb7ec95ecc8adbf3",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.904974304478,
            "priority": 1.054974304478,
        },
        {
            "sample_id": "us-code-42-14405.-c06094e9910d2533",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "conditional_normative",
            "family_margin": -0.250089436097,
            "priority": 0.400089436097,
        },
        {
            "sample_id": "us-code-25-979-07371ce01209ba3d",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.858681399333,
            "priority": 1.008681399333,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        predicted_share = abs(family_margin)
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001641-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-001641-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-001641-policy-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=[
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                }
            ],
            family_shares={predicted_family: predicted_share},
            predicted_family_source="adaptive_logits_fallback",
        )

        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000299_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-33-59mm-33bd4ff213f99d95",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "frame",
            "family_margin": -0.316297484827,
            "priority": 0.466297484827,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-28-2076-3ab0224fce7cccbd",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.470313266998,
            "priority": 0.620313266998,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-43-1575.-0446863694a59614",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "frame",
            "family_margin": -0.417264868021,
            "priority": 0.567264868021,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-6-677e-913e7e8d6372a46e",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.122728879651,
            "priority": 0.272728879651,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-26-261-c77fe5cc3f37fb3e",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.123887098881,
            "priority": 0.273887098881,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-25-788h-1673b9c4bfef0366",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.424665787791,
            "priority": 0.574665787791,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-30-904-18ba3651624db13e",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "temporal",
            "family_margin": 0.021625387389,
            "priority": 0.128374612611,
            "is_self_pair": True,
            "runner_up_family": "frame",
        },
        {
            "sample_id": "us-code-48-1546.-4b597f14550c1a93",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.101064443893,
            "priority": 0.251064443893,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-42-1873a.-b5818cea2f063e06",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "frame",
            "family_margin": 0.067291518423,
            "priority": 0.082708481577,
            "is_self_pair": True,
            "runner_up_family": "temporal",
        },
        {
            "sample_id": "us-code-42-274i-67107d58997fb573",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "conditional_normative",
            "family_margin": -0.557177056654,
            "priority": 0.707177056654,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-42-13386.-68c4e3a1a7a191a8",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.519813142775,
            "priority": 0.669813142775,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-48-1423g.-054fc7aa5d0c9c94",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "deontic",
            "family_margin": 0.135865240604,
            "priority": 0.014134759396,
            "is_self_pair": True,
            "runner_up_family": "temporal",
        },
        {
            "sample_id": "us-code-22-6084-e8751dc281ee386d",
            "predicted_family": "conditional_normative",
            "predicted_system": "KD",
            "predicted_symbol": "O_if",
            "predicted_label": "conditional_obligation",
            "target_family": "deontic",
            "family_margin": -0.08933000104,
            "priority": 0.23933000104,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-21-391-fe5599a7592ce0fa",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "conditional_normative",
            "family_margin": -0.456199169676,
            "priority": 0.606199169676,
            "is_self_pair": False,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        is_self_pair = bool(scenario["is_self_pair"])

        if is_self_pair:
            runner_up_family = str(
                scenario.get(
                    "runner_up_family",
                    "frame" if predicted_family != "frame" else "temporal",
                )
            )
            predicted_share = (1.0 + family_margin) / 2.0
            runner_up_share = predicted_share - family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 1,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        elif abs(family_margin) <= 1e-12:
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": 0.5,
                    "share": 0.5,
                },
                {
                    "family": target_family,
                    "count": 1,
                    "share_raw": 0.5,
                    "share": 0.5,
                },
            ]
        else:
            predicted_share = abs(family_margin)
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                }
            ]

        family_shares = {
            str(item["family"]): float(item["share_raw"])
            for item in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000299-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000299-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-000299-policy-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        expected_candidate_ids = (
            [predicted_family]
            if is_self_pair
            else [predicted_family, target_family]
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_direction = (
            "contested"
            if is_self_pair and family_margin > 0.0
            else "outvoted"
        )
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{expected_direction}_margin_low"
        )
        expected_severity = (
            "review" if expected_direction == "contested" else "requires_rule"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.metadata["adaptive_margin_direction"] == expected_direction
        assert base_ambiguity.severity == expected_severity
        assert (
            base_ambiguity.metadata["explicit_ambiguity_type"]
            == expected_explicit_type
        )
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_001093_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-42-12711.-39d00b6d6f15c30a",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "frame",
            "family_margin": -0.455124861399,
            "priority": 0.605124861399,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-15-1365-6cf0259aacb3f970",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "temporal",
            "family_margin": -0.173215467246,
            "priority": 0.323215467246,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-25-1743-6b335875b4a80ea1",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "temporal",
            "family_margin": -0.85135540315,
            "priority": 1.00135540315,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-43-641a.-2bb066ee98228a28",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.160785242787,
            "priority": 0.310785242787,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-15-2905-93068e73e79bb8df",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "frame",
            "family_margin": 0.067291518423,
            "priority": 0.082708481577,
            "is_self_pair": True,
            "runner_up_family": "temporal",
        },
        {
            "sample_id": "us-code-7-7812-bb63b1e67e356e32",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.402900370167,
            "priority": 0.552900370167,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-19-60-535ad319b502b77b",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.468877638999,
            "priority": 0.618877638999,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-7-450h-ca4b03be437fbbde",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "temporal",
            "family_margin": -0.605183972302,
            "priority": 0.755183972302,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-25-1300d-22-db2df97a1bd58206",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "frame",
            "family_margin": -0.627631105885,
            "priority": 0.777631105885,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-12-4213-a3f33b8276c59592",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.402900370167,
            "priority": 0.552900370167,
            "is_self_pair": False,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        is_self_pair = bool(scenario["is_self_pair"])

        if is_self_pair:
            runner_up_family = str(
                scenario.get(
                    "runner_up_family",
                    "frame" if predicted_family != "frame" else "temporal",
                )
            )
            predicted_share = (1.0 + family_margin) / 2.0
            runner_up_share = predicted_share - family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 1,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        elif abs(family_margin) <= 1e-12:
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": 0.5,
                    "share": 0.5,
                },
                {
                    "family": target_family,
                    "count": 1,
                    "share_raw": 0.5,
                    "share": 0.5,
                },
            ]
        else:
            predicted_share = abs(family_margin)
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                }
            ]

        family_shares = {
            str(item["family"]): float(item["share_raw"])
            for item in ranking
        }
        sample_id = str(scenario["sample_id"])
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001093-policy-{index}",
            text=f"{predicted_family} ambiguity evidence for {sample_id}",
            normalized_text=f"{predicted_family} ambiguity evidence for {sample_id}",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-001093-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-001093-policy-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        expected_candidate_ids = (
            [predicted_family]
            if is_self_pair
            else [predicted_family, target_family]
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_direction = (
            "contested"
            if is_self_pair and family_margin > 0.0
            else "outvoted"
        )
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{expected_direction}_margin_low"
        )
        expected_severity = (
            "review" if expected_direction == "contested" else "requires_rule"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.metadata["adaptive_margin_direction"] == expected_direction
        assert base_ambiguity.severity == expected_severity
        assert (
            base_ambiguity.metadata["explicit_ambiguity_type"]
            == expected_explicit_type
        )
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_003453_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-36-240111-45b5b66b064bd19b",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "temporal",
            "family_margin": 0.102199014073,
            "priority": 0.047800985927,
            "is_self_pair": True,
            "runner_up_family": "deontic",
        },
        {
            "sample_id": "us-code-15-1720-600aa17736b4695c",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.266817941277,
            "priority": 0.416817941277,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-18-3435-2abd445ee1afb2c0",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "temporal",
            "family_margin": -0.524271290662,
            "priority": 0.674271290662,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-27-218-a1d96990f3bb7a1d",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.107959072818,
            "priority": 0.257959072818,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-42-13013a.-7106b3d53d3b00f8",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.518545682385,
            "priority": 0.668545682385,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-16-468c-8d735559822f32c1",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "frame",
            "family_margin": 0.063288565802,
            "priority": 0.086711434198,
            "is_self_pair": True,
            "runner_up_family": "deontic",
        },
        {
            "sample_id": "us-code-33-557a-feba82bcbe006794",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "deontic",
            "family_margin": 0.098836078398,
            "priority": 0.051163921602,
            "is_self_pair": True,
            "runner_up_family": "temporal",
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        is_self_pair = bool(scenario["is_self_pair"])

        if is_self_pair:
            runner_up_family = str(
                scenario.get(
                    "runner_up_family",
                    "frame" if predicted_family != "frame" else "temporal",
                )
            )
            predicted_share = (1.0 + family_margin) / 2.0
            runner_up_share = predicted_share - family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 1,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        elif abs(family_margin) <= 1e-12:
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": 0.5,
                    "share": 0.5,
                },
                {
                    "family": target_family,
                    "count": 1,
                    "share_raw": 0.5,
                    "share": 0.5,
                },
            ]
        else:
            predicted_share = abs(family_margin)
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                }
            ]

        family_shares = {
            str(item["family"]): float(item["share_raw"])
            for item in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-003453-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-003453-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-003453-policy-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        expected_candidate_ids = (
            [predicted_family]
            if is_self_pair
            else [predicted_family, target_family]
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_direction = (
            "contested"
            if is_self_pair and family_margin > 0.0
            else "outvoted"
        )
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{expected_direction}_margin_low"
        )
        expected_severity = (
            "review" if expected_direction == "contested" else "requires_rule"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.metadata["adaptive_margin_direction"] == expected_direction
        assert base_ambiguity.severity == expected_severity
        assert (
            base_ambiguity.metadata["explicit_ambiguity_type"]
            == expected_explicit_type
        )
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_002693_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-46-5111.-09e5ed0fb70ee981",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.833024721921,
            "priority": 0.983024721921,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-20-7822-a3eae3a5d5a43491",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "dynamic",
            "family_margin": -0.363347095794,
            "priority": 0.513347095794,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-7-7812-bb63b1e67e356e32",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.469020760716,
            "priority": 0.619020760716,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-19-105-de0bddaa1cfa3265",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "frame",
            "family_margin": 0.0,
            "priority": 0.15,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-22-1625-ba29e3e11b29e2fa",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "conditional_normative",
            "family_margin": -0.518545682385,
            "priority": 0.668545682385,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-16-690g-e9ef1b72099c2fe6",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.728674957452,
            "priority": 0.878674957452,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-24-132-9d9b939d40ce8dcf",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": 0.0,
            "priority": 0.15,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-7-6512-26f77ae9069edd30",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "conditional_normative",
            "family_margin": -0.270147087145,
            "priority": 0.420147087145,
            "is_self_pair": False,
        },
        {
            "sample_id": "us-code-25-1488-0418c7d50c4ad027",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "deontic",
            "family_margin": 0.133581965568,
            "priority": 0.016418034432,
            "is_self_pair": True,
            "runner_up_family": "temporal",
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        is_self_pair = bool(scenario["is_self_pair"])

        if is_self_pair:
            runner_up_family = str(
                scenario.get(
                    "runner_up_family",
                    "frame" if predicted_family != "frame" else "temporal",
                )
            )
            predicted_share = (1.0 + family_margin) / 2.0
            runner_up_share = predicted_share - family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 1,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        elif abs(family_margin) <= 1e-12:
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": 0.5,
                    "share": 0.5,
                },
                {
                    "family": target_family,
                    "count": 1,
                    "share_raw": 0.5,
                    "share": 0.5,
                },
            ]
        else:
            predicted_share = abs(family_margin)
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                }
            ]

        family_shares = {
            str(item["family"]): float(item["share_raw"])
            for item in ranking
        }
        sample_id = str(scenario["sample_id"])
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-002693-policy-{index}",
            text=f"{predicted_family} ambiguity evidence for {sample_id}",
            normalized_text=f"{predicted_family} ambiguity evidence for {sample_id}",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-002693-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=f"packet-002693-policy-{index}",
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        expected_candidate_ids = (
            [predicted_family]
            if is_self_pair
            else [predicted_family, target_family]
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_direction = (
            "contested"
            if is_self_pair and family_margin > 0.0
            else "outvoted"
        )
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{expected_direction}_margin_low"
        )
        expected_severity = (
            "review" if expected_direction == "contested" else "requires_rule"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )

        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.metadata["adaptive_margin_direction"] == expected_direction
        assert base_ambiguity.severity == expected_severity
        assert (
            base_ambiguity.metadata["explicit_ambiguity_type"]
            == expected_explicit_type
        )
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_rounds_non_self_family_margin_from_raw_delta(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    predicted_share = 0.33333349
    target_share = 0.11111151
    raw_margin = target_share - predicted_share
    encoding = SpaCyLegalEncoding(
        document_id="adaptive-round-raw-margin-doc",
        text="frame ambiguity evidence",
        normalized_text="frame ambiguity evidence",
        tokens=[],
        sentences=[],
        cues=[
            SpaCyModalCueFeature(
                family="frame",
                system="FRAME_BM25",
                symbol="Frame",
                label="frame",
                cue="evidence",
                start_char=0,
                end_char=8,
                token_indices=[],
            )
        ],
    )
    modal_ir = ModalIRDocument(
        document_id="adaptive-round-raw-margin-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-frame-round-margin",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="frame_scope",
                    arguments=["scope:test"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="adaptive-round-raw-margin-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                ),
            )
        ],
    )

    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "frame", "count": 1, "share": predicted_share},
            {"family": "dynamic", "count": 1, "share": target_share},
        ],
        family_shares={"frame": predicted_share, "dynamic": target_share},
        predicted_family_source="adaptive_logits_fallback",
    )

    base_ambiguity = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_family_margin_low"
        and ambiguity.candidate_ids == ["frame", "dynamic"]
        and ambiguity.metadata["adaptive_policy_pair"] == "frame->dynamic"
    )
    assert abs(float(base_ambiguity.metadata["family_margin_raw"]) - raw_margin) < 1e-12
    assert float(base_ambiguity.metadata["family_margin"]) == round(raw_margin, 6)


def test_modal_compiler_adaptive_policy_normalizes_prefixed_family_tokens(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    encoding = SpaCyLegalEncoding(
        document_id="prefixed-family-policy-doc",
        text="prefixed family policy evidence",
        normalized_text="prefixed family policy evidence",
        tokens=[],
        sentences=[],
        cues=[],
    )
    modal_ir = ModalIRDocument(
        document_id="prefixed-family-policy-doc",
        source="us_code",
        normalized_text=encoding.normalized_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-prefixed-frame",
                operator=ModalIROperator(
                    family="flogic:modal_family:frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(
                    name="frame_scope",
                    arguments=["scope:test"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="prefixed-family-policy-doc",
                    start_char=0,
                    end_char=len(encoding.normalized_text),
                ),
            )
        ],
    )

    ambiguities = compiler._adaptive_family_margin_ambiguities(
        encoding,
        modal_ir=modal_ir,
        ranking=[
            {"family": "flogic:modal_family:temporal", "count": 1, "share": 0.72},
            {"family": "ModalLogicFamily.FRAME", "count": 1, "share": 0.28},
        ],
        family_shares={
            "flogic:modal_family:temporal": 0.72,
            "ModalLogicFamily.FRAME": 0.28,
        },
    )

    compiled_primary_explicit = next(
        ambiguity
        for ambiguity in ambiguities
        if ambiguity.ambiguity_type == "adaptive_frame_temporal_outvoted_margin_low"
        and ambiguity.candidate_ids == ["frame", "temporal"]
        and ambiguity.metadata["adaptive_predicted_family_source"]
        == "compiled_primary_family"
        and ambiguity.metadata["adaptive_policy_pair"] == "frame->temporal"
    )
    assert (
        compiled_primary_explicit.metadata["adaptive_base_ambiguity_type"]
        == "adaptive_family_margin_low"
    )


def test_modal_compiler_supports_signal_free_pairs_for_enum_style_target_tokens() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    assert compiler._supports_signal_free_adaptive_pair(
        "alethic",
        "ModalLogicFamily.DYNAMIC",
    )


def test_modal_compiler_supports_signal_free_pairs_for_directional_target_tokens() -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )

    assert compiler._supports_signal_free_adaptive_pair(
        "frame",
        "frame->deontic",
    )
    assert compiler._supports_signal_free_adaptive_pair(
        "deontic",
        "deontic->temporal",
    )
    assert compiler._supports_signal_free_adaptive_pair(
        "temporal",
        "temporal->frame",
    )


def test_modal_compiler_surfaces_packet_001206_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-42-12897.-55f8bd0d77d09422",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.289369987536,
            "priority": 0.439369987536,
        },
        {
            "sample_id": "us-code-51-71102.-0da2ef1ed6bed196",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.443379822999,
            "priority": 0.593379822999,
        },
        {
            "sample_id": "us-code-43-2602.-cd86b6edb4f89658",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.18771949257,
            "priority": 0.33771949257,
        },
        {
            "sample_id": "us-code-25-2208-bf0a5d9e8825e37b",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "frame",
            "family_margin": -0.523217104595,
            "priority": 0.673217104595,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        predicted_share = abs(family_margin)
        sample_id = str(scenario["sample_id"])
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001206-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-001206-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=[
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                }
            ],
            family_shares={predicted_family: predicted_share},
            predicted_family_source="adaptive_logits_fallback",
        )

        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_001158_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-48-1413.-6a0ec8c95e66d4f7",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "conditional_normative",
            "family_margin": -0.823068294259,
            "priority": 0.973068294259,
        },
        {
            "sample_id": "us-code-43-900.-afed8adba1cc4a10",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "temporal",
            "family_margin": -0.597857285401,
            "priority": 0.747857285401,
        },
        {
            "sample_id": "us-code-51-31503.-e1023d45bb9b1ef6",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.833024721921,
            "priority": 0.983024721921,
        },
        {
            "sample_id": "us-code-16-450oo-8-3be6a8a9cc244196",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "conditional_normative",
            "family_margin": -0.548560166116,
            "priority": 0.698560166116,
        },
        {
            "sample_id": "us-code-13-81-f308cbccabdd1e60",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.586281164377,
            "priority": 0.736281164377,
        },
        {
            "sample_id": "us-code-21-158-8c90bd4887386165",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.700998303126,
            "priority": 0.850998303126,
        },
        {
            "sample_id": "us-code-33-467o-4f0ea3fc1a5e6fe7",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "frame",
            "family_margin": 0.131176293653,
            "priority": 0.018823706347,
        },
        {
            "sample_id": "us-code-36-70311-f643b8802728dab9",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "temporal",
            "family_margin": -0.027148002684,
            "priority": 0.177148002684,
        },
        {
            "sample_id": "us-code-16-410z-3-3bd8e579ffa0927b",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "deontic",
            "family_margin": -0.25340797613,
            "priority": 0.40340797613,
        },
        {
            "sample_id": "us-code-15-161-1e936f212bab2822",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "frame",
            "family_margin": -0.345999657573,
            "priority": 0.495999657573,
        },
        {
            "sample_id": "us-code-42-16276.-fa3bc9b5922be1b5",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.879221966852,
            "priority": 1.029221966852,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])
        if predicted_family == target_family:
            predicted_share = (1.0 + family_margin) / 2.0
            runner_up_family = (
                "deontic"
                if predicted_family != "deontic"
                else "temporal"
            )
            runner_up_share = predicted_share - family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 1,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
            family_shares = {
                predicted_family: predicted_share,
                runner_up_family: runner_up_share,
            }
        else:
            predicted_share = abs(family_margin)
            ranking = [
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                }
            ]
            family_shares = {predicted_family: predicted_share}
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001158-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-001158-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits_fallback",
        )

        policy_pair = f"{predicted_family}->{target_family}"
        margin_direction = "contested" if family_margin > 0.0 else "outvoted"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
        )
        expected_candidate_ids = (
            [predicted_family]
            if predicted_family == target_family
            else [predicted_family, target_family]
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == margin_direction
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        if margin_direction == "outvoted":
            assert base_ambiguity.severity == "requires_rule"
        else:
            assert base_ambiguity.severity == "review"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == expected_candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_003558_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-43-599.-397165e8925277e6",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "conditional_normative",
            "family_margin": -0.466401324928,
            "priority": 0.616401324928,
        },
        {
            "sample_id": "us-code-42-5778.-464f274b893d6e7d",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "frame",
            "family_margin": 0.0,
            "priority": 0.15,
        },
        {
            "sample_id": "us-code-12-953-fe7db7d96084239e",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "frame",
            "family_margin": 0.131176293653,
            "priority": 0.018823706347,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        predicted_share = abs(family_margin)
        sample_id = str(scenario["sample_id"])
        candidate_ids = (
            [predicted_family]
            if predicted_family == target_family
            else [predicted_family, target_family]
        )
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-003558-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-003558-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=[
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                }
            ],
            family_shares={predicted_family: predicted_share},
            predicted_family_source="adaptive_logits_fallback",
        )

        policy_pair = f"{predicted_family}->{target_family}"
        margin_direction = "contested" if family_margin > 0.0 else "outvoted"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert (
            base_ambiguity.severity
            == ("review" if margin_direction == "contested" else "requires_rule")
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_004030_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-42-6003.-8065a6372d768590",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "temporal",
            "family_margin": -0.131176293653,
            "priority": 0.281176293653,
        },
        {
            "sample_id": "us-code-25-750-666152ba487ffae9",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "conditional_normative",
            "family_margin": -0.466401324928,
            "priority": 0.616401324928,
        },
        {
            "sample_id": "us-code-51-70507.-0f963bc1d3472634",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.395548377717,
            "priority": 0.545548377717,
        },
        {
            "sample_id": "us-code-16-777i-eb850ac0b005ecea",
            "predicted_family": "conditional_normative",
            "predicted_system": "KD",
            "predicted_symbol": "O|",
            "predicted_label": "conditional_obligation",
            "target_family": "deontic",
            "family_margin": -0.219268331102,
            "priority": 0.369268331102,
        },
        {
            "sample_id": "us-code-25-1300d-23-6c2b84a35a5b5e9a",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "frame",
            "family_margin": -0.627631105885,
            "priority": 0.777631105885,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        predicted_share = abs(family_margin)
        sample_id = str(scenario["sample_id"])
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-004030-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-004030-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=[
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                }
            ],
            family_shares={predicted_family: predicted_share},
            predicted_family_source="adaptive_logits_fallback",
        )

        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000028_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    scenarios = (
        {
            "sample_id": "us-code-42-16824.-bea8e4de2ca3eb5e",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.774467193444,
            "priority": 0.924467193444,
        },
        {
            "sample_id": "us-code-36-21110-e10464bdc5e2ba17",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "deontic",
            "family_margin": -0.833024721921,
            "priority": 0.983024721921,
        },
        {
            "sample_id": "us-code-20-46a-b7ca5e58f6b7a2fa",
            "predicted_family": "deontic",
            "predicted_system": "D",
            "predicted_symbol": "O",
            "predicted_label": "obligation",
            "target_family": "temporal",
            "family_margin": -0.021099529553,
            "priority": 0.171099529553,
        },
        {
            "sample_id": "us-code-42-603a.-bc940094855a0b55",
            "predicted_family": "frame",
            "predicted_system": "FRAME_BM25",
            "predicted_symbol": "Frame",
            "predicted_label": "frame",
            "target_family": "temporal",
            "family_margin": -0.863731220265,
            "priority": 1.013731220265,
        },
        {
            "sample_id": "us-code-48-2169.-816da61b9d4f3363",
            "predicted_family": "temporal",
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
            "target_family": "frame",
            "family_margin": -0.348086071481,
            "priority": 0.498086071481,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        predicted_share = abs(family_margin)
        sample_id = str(scenario["sample_id"])
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000028-policy-{index}",
            text=f"{predicted_family} ambiguity evidence",
            normalized_text=f"{predicted_family} ambiguity evidence",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue="evidence",
                    start_char=0,
                    end_char=8,
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000028-policy-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_scope",
                        arguments=["scope:test"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                    ),
                )
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=[
                {
                    "family": predicted_family,
                    "count": 1,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                }
            ],
            family_shares={predicted_family: predicted_share},
            predicted_family_source="adaptive_logits_fallback",
        )

        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_001424_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-2-117a-c0775188333b7a3d",
            "predicted_family": "frame",
            "target_family": "temporal",
            "family_margin": -0.66555142127,
            "priority": 0.81555142127,
        },
        {
            "sample_id": "us-code-16-590q-2-2125be046fee1939",
            "predicted_family": "temporal",
            "target_family": "conditional_normative",
            "family_margin": -0.2372903686,
            "priority": 0.3872903686,
        },
        {
            "sample_id": "us-code-46-3712.-2ad58a4014255f63",
            "predicted_family": "frame",
            "target_family": "deontic",
            "family_margin": -0.700998303126,
            "priority": 0.850998303126,
        },
        {
            "sample_id": "us-code-43-31j.-d00cfaaa000291a2",
            "predicted_family": "temporal",
            "target_family": "temporal",
            "family_margin": 0.0,
            "priority": 0.15,
        },
        {
            "sample_id": "us-code-42-11047.-6a7c0f0398de36ee",
            "predicted_family": "temporal",
            "target_family": "conditional_normative",
            "family_margin": -0.266961573086,
            "priority": 0.416961573086,
        },
        {
            "sample_id": "us-code-43-336d.-7801c7434f3cdcfd",
            "predicted_family": "temporal",
            "target_family": "conditional_normative",
            "family_margin": -0.021131512289,
            "priority": 0.171131512289,
        },
        {
            "sample_id": "us-code-42-13013a.-7106b3d53d3b00f8",
            "predicted_family": "frame",
            "target_family": "deontic",
            "family_margin": -0.879221966852,
            "priority": 1.029221966852,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])
        if predicted_family == target_family:
            predicted_share = (1.0 + family_margin) / 2.0
            runner_up_family = (
                "deontic" if predicted_family != "deontic" else "temporal"
            )
            runner_up_share = predicted_share - family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 0,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        else:
            predicted_share = 0.9
            target_share = predicted_share + family_margin
            if target_share < 0.0:
                predicted_share = min(0.99, abs(family_margin) + 0.05)
                target_share = predicted_share + family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": target_family,
                    "count": 0,
                    "share_raw": target_share,
                    "share": target_share,
                },
            ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001424-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} policy evidence.",
            normalized_text=f"Synthetic {predicted_family} policy evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system="LTL" if predicted_family == "temporal" else "D",
                    symbol="F" if predicted_family == "temporal" else "O",
                    label=f"{predicted_family}-label",
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-001424-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system="LTL" if predicted_family == "temporal" else "D",
                        symbol="F" if predicted_family == "temporal" else "O",
                        label=f"{predicted_family}-label",
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="42 U.S.C. 1983",
                    ),
                ),
            ],
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        margin_direction = "contested" if family_margin > 0.0 else "outvoted"
        expected_type = (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
        )
        expected_priority = (
            0.15 - family_margin
            if family_margin > 0.0
            else abs(family_margin) + 0.15
        )
        policy_pair = f"{predicted_family}->{target_family}"
        matching = [
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == expected_type
            and ambiguity.metadata.get("adaptive_predicted_family_source")
            == "adaptive_logits"
            and ambiguity.metadata.get("predicted_family") == predicted_family
            and ambiguity.metadata.get("target_family") == target_family
            and ambiguity.metadata.get("adaptive_policy_pair") == policy_pair
        ]
        assert matching, (sample_id, predicted_family, target_family, family_margin)
        ambiguity = matching[0]
        assert ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert ambiguity.metadata["adaptive_margin_direction"] == margin_direction
        assert abs(float(ambiguity.metadata["family_margin_raw"]) - family_margin) <= 1e-12
        assert abs(float(ambiguity.metadata["priority"]) - expected_priority) <= 1e-12
        assert (
            abs(float(ambiguity.metadata["adaptive_priority"]) - expected_priority)
            <= 1e-12
        )


def test_modal_compiler_surfaces_packet_000697_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-43-2621.-4dd8204ca83e15e8",
            "predicted_family": "deontic",
            "target_family": "temporal",
            "family_margin": -0.235919325579,
            "priority": 0.385919325579,
        },
        {
            "sample_id": "us-code-7-6309-1144458ea7c01b87",
            "predicted_family": "deontic",
            "target_family": "conditional_normative",
            "family_margin": -0.830844862843,
            "priority": 0.980844862843,
        },
        {
            "sample_id": "us-code-18-4002-8785e18f0558d131",
            "predicted_family": "deontic",
            "target_family": "frame",
            "family_margin": -0.708987916916,
            "priority": 0.858987916916,
        },
        {
            "sample_id": "us-code-10-188-6a1ae8c1e11e0257",
            "predicted_family": "conditional_normative",
            "target_family": "temporal",
            "family_margin": -0.282363755341,
            "priority": 0.432363755341,
        },
        {
            "sample_id": "us-code-7-1433-95e9e4fbdf8b32d5",
            "predicted_family": "temporal",
            "target_family": "doxastic",
            "family_margin": -0.34506609321,
            "priority": 0.49506609321,
        },
        {
            "sample_id": "us-code-47-252.-c6634f17d18802f6",
            "predicted_family": "deontic",
            "target_family": "conditional_normative",
            "family_margin": -0.201635090594,
            "priority": 0.351635090594,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])

        predicted_share = 0.9
        target_share = predicted_share + family_margin
        if target_share < 0.0:
            predicted_share = min(0.99, abs(family_margin) + 0.05)
            target_share = predicted_share + family_margin
        ranking = [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": target_family,
                "count": 0,
                "share_raw": target_share,
                "share": target_share,
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000697-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} policy evidence.",
            normalized_text=f"Synthetic {predicted_family} policy evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system="LTL" if predicted_family == "temporal" else "D",
                    symbol="F" if predicted_family == "temporal" else "O",
                    label=f"{predicted_family}-label",
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000697-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system="LTL" if predicted_family == "temporal" else "D",
                        symbol="F" if predicted_family == "temporal" else "O",
                        label=f"{predicted_family}-label",
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="42 U.S.C. 1983",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["priority"]) - float(scenario["priority"]))
            < 1e-12
        )
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000152_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-14-3714-d45c1663b6bedf67",
            "predicted_family": "temporal",
            "target_family": "deontic",
            "family_margin": -0.371029362368,
            "priority": 0.521029362368,
        },
        {
            "sample_id": "us-code-26-181-7460590b2fa466b8",
            "predicted_family": "conditional_normative",
            "target_family": "deontic",
            "family_margin": -0.247387012755,
            "priority": 0.397387012755,
        },
        {
            "sample_id": "us-code-42-1395b-cb3e58cb7c7bbe53",
            "predicted_family": "deontic",
            "target_family": "temporal",
            "family_margin": -0.357704583307,
            "priority": 0.507704583307,
        },
        {
            "sample_id": "us-code-46-53303.-a6230d6f2a0563f0",
            "predicted_family": "conditional_normative",
            "target_family": "deontic",
            "family_margin": -0.039205541898,
            "priority": 0.189205541898,
        },
        {
            "sample_id": "us-code-34-20915-3ce5f713b3796c62",
            "predicted_family": "conditional_normative",
            "target_family": "deontic",
            "family_margin": -0.034293957414,
            "priority": 0.184293957414,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])

        if predicted_family == "temporal":
            predicted_system = "LTL"
            predicted_symbol = "F"
            predicted_label = "eventually"
        elif predicted_family == "conditional_normative":
            predicted_system = "KD"
            predicted_symbol = "O|"
            predicted_label = "conditional_obligation"
        else:
            predicted_system = "D"
            predicted_symbol = "O"
            predicted_label = "obligation"

        predicted_share = 0.9
        target_share = predicted_share + family_margin
        if target_share < 0.0:
            predicted_share = min(0.99, abs(family_margin) + 0.05)
            target_share = predicted_share + family_margin
        ranking = [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": target_family,
                "count": 0,
                "share_raw": target_share,
                "share": target_share,
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000152-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} ambiguity evidence.",
            normalized_text=f"Synthetic {predicted_family} ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000152-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="42 U.S.C. 1983",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["priority"]) - float(scenario["priority"]))
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_effective_family_margin_threshold"])
                - 0.1515
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["adaptive_pair_margin_buffer"]) - 0.0015)
            < 1e-12
        )
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000749_refined_modal_family_cue_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-42-1395rr-fd726267510ffffe",
            "predicted_family": "conditional_normative",
            "target_family": "conditional_normative",
            "family_margin": 0.0,
            "expected_explicit_type": "adaptive_conditional_normative_conditional_normative_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-6-321n-44569aef9ca9fde1",
            "predicted_family": "deontic",
            "target_family": "frame",
            "family_margin": -0.733254282087,
            "expected_explicit_type": "adaptive_deontic_frame_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-8-1154-5929e1172cf7f303",
            "predicted_family": "doxastic",
            "target_family": "conditional_normative",
            "family_margin": -0.94,
            "expected_explicit_type": "adaptive_doxastic_conditional_normative_outvoted_margin_low",
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])
        if predicted_family == target_family:
            predicted_share = (1.0 + family_margin) / 2.0
            runner_up_family = (
                "deontic" if predicted_family != "deontic" else "temporal"
            )
            runner_up_share = predicted_share - family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 0,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        else:
            predicted_share = 0.9
            target_share = predicted_share + family_margin
            if target_share < 0.0:
                predicted_share = min(0.99, abs(family_margin) + 0.05)
                target_share = predicted_share + family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": target_family,
                    "count": 0,
                    "share_raw": target_share,
                    "share": target_share,
                },
            ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        if predicted_family == "temporal":
            predicted_system = "LTL"
            predicted_symbol = "F"
            predicted_label = "eventually"
        elif predicted_family == "conditional_normative":
            predicted_system = "KD"
            predicted_symbol = "O|"
            predicted_label = "conditional_obligation"
        elif predicted_family == "doxastic":
            predicted_system = "KD45"
            predicted_symbol = "B"
            predicted_label = "belief"
        else:
            predicted_system = "D"
            predicted_symbol = "O"
            predicted_label = "obligation"
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000749-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} policy evidence.",
            normalized_text=f"Synthetic {predicted_family} policy evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000749-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="42 U.S.C. 1983",
                    ),
                ),
            ],
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_effective_family_margin_threshold"])
                - 0.1515
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["adaptive_pair_margin_buffer"]) - 0.0015)
            < 1e-12
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == str(
            scenario["expected_explicit_type"]
        )
        assert any(
            ambiguity.ambiguity_type == str(scenario["expected_explicit_type"])
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000112_refined_modal_family_cue_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-22-290k-5-2914184e2690e597",
            "predicted_family": "frame",
            "target_family": "deontic",
            "family_margin": -0.301410337201,
            "expected_threshold": 0.1515,
            "expected_pair_buffer": 0.0015,
            "expected_weak_buffer": 0.0,
        },
        {
            "sample_id": "us-code-10-2515-cb1304b3980adf2a",
            "predicted_family": "frame",
            "target_family": "temporal",
            "family_margin": -0.070156195233,
            "expected_threshold": 0.152,
            "expected_pair_buffer": 0.002,
            "expected_weak_buffer": 0.0,
        },
        {
            "sample_id": "us-code-43-328.-9093cbf7e12bac04",
            "predicted_family": "deontic",
            "target_family": "deontic",
            "family_margin": 0.201850892765,
            "expected_threshold": 0.2865,
            "expected_pair_buffer": 0.1365,
            "expected_weak_buffer": 0.135,
        },
        {
            "sample_id": "us-code-10-233a-8bed7fafbdc4039d",
            "predicted_family": "deontic",
            "target_family": "temporal",
            "family_margin": -0.099920506436,
            "expected_threshold": 0.1515,
            "expected_pair_buffer": 0.0015,
            "expected_weak_buffer": 0.0,
        },
    )
    expected_pairs = {
        (str(scenario["predicted_family"]), str(scenario["target_family"]))
        for scenario in scenarios
    }
    assert expected_pairs == set(COMPILER_REFINED_PACKET_000112_FAMILY_PAIRS)

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])
        if predicted_family == "frame":
            predicted_system = "FRAME_BM25"
            predicted_symbol = "Frame"
            predicted_label = "frame"
        else:
            predicted_system = "D"
            predicted_symbol = "O"
            predicted_label = "obligation"

        if predicted_family == target_family:
            predicted_share = 0.488555185933
            runner_up_share = predicted_share - family_margin
            runner_up_family = "temporal"
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 0,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        else:
            predicted_share = 0.9
            target_share = predicted_share + family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": target_family,
                    "count": 0,
                    "share_raw": target_share,
                    "share": target_share,
                },
            ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000112-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} refined cue evidence.",
            normalized_text=f"Synthetic {predicted_family} refined cue evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000112-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-000112",
                    ),
                ),
            ],
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        candidate_ids = (
            [predicted_family]
            if predicted_family == target_family
            else [predicted_family, target_family]
        )
        margin_direction = "contested" if family_margin > 0.0 else "outvoted"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == margin_direction
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_effective_family_margin_threshold"])
                - float(scenario["expected_threshold"])
            )
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_pair_margin_buffer"])
                - float(scenario["expected_pair_buffer"])
            )
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["weak_typed_self_family_margin_buffer"])
                - float(scenario["expected_weak_buffer"])
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            base_ambiguity.severity
            == ("review" if margin_direction == "contested" else "requires_rule")
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000346_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-7-7772-3972803050f441b6",
            "predicted_family": "temporal",
            "target_family": "frame",
            "family_margin": -0.470146801118,
            "priority": 0.620146801118,
        },
        {
            "sample_id": "us-code-43-422h.-9986ac691c9a0f9c",
            "predicted_family": "deontic",
            "target_family": "conditional_normative",
            "family_margin": -0.506689798037,
            "priority": 0.656689798037,
        },
        {
            "sample_id": "us-code-48-1690.-c4d0c9517b5a1bdc",
            "predicted_family": "temporal",
            "target_family": "deontic",
            "family_margin": -0.14903616881,
            "priority": 0.29903616881,
        },
        {
            "sample_id": "us-code-50-3912.-f5ce5698da24afaf",
            "predicted_family": "deontic",
            "target_family": "frame",
            "family_margin": -0.455101080975,
            "priority": 0.605101080975,
        },
        {
            "sample_id": "us-code-50-3714.-8184e03a7bf2b936",
            "predicted_family": "deontic",
            "target_family": "doxastic",
            "family_margin": -0.612457764076,
            "priority": 0.762457764076,
        },
        {
            "sample_id": "us-code-29-3361-80d5442eb2f152f6",
            "predicted_family": "deontic",
            "target_family": "conditional_normative",
            "family_margin": -0.033638069677,
            "priority": 0.183638069677,
        },
        {
            "sample_id": "us-code-42-7511.-5d2a6316ba0793d5",
            "predicted_family": "conditional_normative",
            "target_family": "conditional_normative",
            "family_margin": 0.129155763182,
            "priority": 0.020844236818,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])

        if predicted_family == "temporal":
            predicted_system = "LTL"
            predicted_symbol = "F"
            predicted_label = "eventually"
        elif predicted_family == "conditional_normative":
            predicted_system = "KD"
            predicted_symbol = "O|"
            predicted_label = "conditional_obligation"
        elif predicted_family == "frame":
            predicted_system = "FRAME_BM25"
            predicted_symbol = "Frame"
            predicted_label = "frame"
        elif predicted_family == "doxastic":
            predicted_system = "KD45"
            predicted_symbol = "B"
            predicted_label = "belief"
        else:
            predicted_system = "D"
            predicted_symbol = "O"
            predicted_label = "obligation"

        if predicted_family == target_family and family_margin > 0.0:
            predicted_share = 0.9
            runner_up_share = predicted_share - family_margin
            runner_up_family = "deontic" if predicted_family != "deontic" else "temporal"
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 0,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        else:
            predicted_share = 0.9
            target_share = predicted_share + family_margin
            if target_share < 0.0:
                predicted_share = min(0.99, abs(family_margin) + 0.05)
                target_share = predicted_share + family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": target_family,
                    "count": 0,
                    "share_raw": target_share,
                    "share": target_share,
                },
            ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        candidate_ids = (
            [predicted_family]
            if predicted_family == target_family
            else [predicted_family, target_family]
        )
        margin_direction = "contested" if family_margin > 0.0 else "outvoted"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
        )
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000346-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} ambiguity evidence.",
            normalized_text=f"Synthetic {predicted_family} ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000346-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="42 U.S.C. 1983",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == margin_direction
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["priority"]) - float(scenario["priority"]))
            < 1e-12
        )
        assert (
            base_ambiguity.severity
            == ("review" if margin_direction == "contested" else "requires_rule")
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_001605_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-42-12835.-efafc5db287e34c3",
            "predicted_family": "temporal",
            "target_family": "deontic",
            "family_margin": -0.521562587937,
            "priority": 0.671562587937,
        },
        {
            "sample_id": "us-code-10-9036-b188256a0ae94c4c",
            "predicted_family": "temporal",
            "target_family": "deontic",
            "family_margin": -0.53395633729,
            "priority": 0.68395633729,
        },
        {
            "sample_id": "us-code-16-580f-d159c17cca2fb07b",
            "predicted_family": "deontic",
            "target_family": "conditional_normative",
            "family_margin": -0.589255873094,
            "priority": 0.739255873094,
        },
        {
            "sample_id": "us-code-26-2010-1d49b3824d22c29f",
            "predicted_family": "conditional_normative",
            "target_family": "deontic",
            "family_margin": -0.209571057872,
            "priority": 0.359571057872,
        },
        {
            "sample_id": "us-code-16-541d-51a25c2b99077421",
            "predicted_family": "deontic",
            "target_family": "temporal",
            "family_margin": -0.470339471359,
            "priority": 0.620339471359,
        },
        {
            "sample_id": "us-code-42-4013.-7f2638fdc6147057",
            "predicted_family": "deontic",
            "target_family": "deontic",
            "family_margin": 0.007698763314,
            "priority": 0.142301236686,
        },
        {
            "sample_id": "us-code-12-2267-8408290dceb95197",
            "predicted_family": "deontic",
            "target_family": "frame",
            "family_margin": -0.419635253045,
            "priority": 0.569635253045,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])

        if predicted_family == "temporal":
            predicted_system = "LTL"
            predicted_symbol = "F"
            predicted_label = "eventually"
        elif predicted_family == "conditional_normative":
            predicted_system = "KD"
            predicted_symbol = "O|"
            predicted_label = "conditional_obligation"
        elif predicted_family == "frame":
            predicted_system = "FRAME_BM25"
            predicted_symbol = "Frame"
            predicted_label = "frame"
        else:
            predicted_system = "D"
            predicted_symbol = "O"
            predicted_label = "obligation"

        if predicted_family == target_family and family_margin > 0.0:
            predicted_share = 0.9
            runner_up_share = predicted_share - family_margin
            runner_up_family = "temporal" if predicted_family != "temporal" else "deontic"
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 0,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        else:
            predicted_share = 0.9
            target_share = predicted_share + family_margin
            if target_share < 0.0:
                predicted_share = min(0.99, abs(family_margin) + 0.05)
                target_share = predicted_share + family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": target_family,
                    "count": 0,
                    "share_raw": target_share,
                    "share": target_share,
                },
            ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        candidate_ids = (
            [predicted_family]
            if predicted_family == target_family
            else [predicted_family, target_family]
        )
        margin_direction = "contested" if family_margin > 0.0 else "outvoted"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
        )
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-001605-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} ambiguity evidence.",
            normalized_text=f"Synthetic {predicted_family} ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-001605-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="42 U.S.C. 1983",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == margin_direction
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_effective_family_margin_threshold"])
                - 0.1515
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["adaptive_pair_margin_buffer"]) - 0.0015)
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["priority"]) - float(scenario["priority"]))
            < 1e-12
        )
        assert (
            base_ambiguity.severity
            == ("review" if margin_direction == "contested" else "requires_rule")
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_002993_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-26-529-5768ffa99b942174",
            "predicted_family": "conditional_normative",
            "target_family": "deontic",
            "family_margin": -0.09616716178,
            "priority": 0.24616716178,
            "predicted_system": "KD",
            "predicted_symbol": "O|",
            "predicted_label": "conditional_obligation",
        },
        {
            "sample_id": "us-code-24-16-244f147750bf2156",
            "predicted_family": "temporal",
            "target_family": "deontic",
            "family_margin": -0.168714079505,
            "priority": 0.318714079505,
            "predicted_system": "LTL",
            "predicted_symbol": "F",
            "predicted_label": "eventually",
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])
        predicted_share = abs(family_margin)
        target_share = predicted_share + family_margin
        ranking = [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": target_family,
                "count": 0,
                "share_raw": target_share,
                "share": target_share,
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }

        encoding = SpaCyLegalEncoding(
            document_id=f"packet-002993-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} ambiguity evidence.",
            normalized_text=f"Synthetic {predicted_family} ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=str(scenario["predicted_system"]),
                    symbol=str(scenario["predicted_symbol"]),
                    label=str(scenario["predicted_label"]),
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-002993-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=str(scenario["predicted_system"]),
                        symbol=str(scenario["predicted_symbol"]),
                        label=str(scenario["predicted_label"]),
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="26 U.S.C. 529",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        expected_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        policy_pair = f"{predicted_family}->{target_family}"
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata.get("adaptive_policy_pair") == policy_pair
        )
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin) <= 1e-12
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            <= 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["priority"]) - float(scenario["priority"]))
            <= 1e-12
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_type
        assert any(
            ambiguity.ambiguity_type == expected_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata.get("adaptive_policy_pair") == policy_pair
            and ambiguity.metadata.get("adaptive_base_ambiguity_type")
            == "adaptive_family_margin_low"
            and ambiguity.metadata.get("adaptive_predicted_family_source")
            == "adaptive_logits"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_003252_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-16-6551-10034197b0128141",
            "predicted_family": "temporal",
            "target_family": "epistemic",
            "family_margin": -0.296211378448,
            "priority": 0.446211378448,
        },
        {
            "sample_id": "us-code-22-8111-c264b86e0b4203ab",
            "predicted_family": "deontic",
            "target_family": "frame",
            "family_margin": -0.530485835159,
            "priority": 0.680485835159,
        },
        {
            "sample_id": "us-code-25-416j-94e3a257b7bdc1c9",
            "predicted_family": "temporal",
            "target_family": "deontic",
            "family_margin": -0.633215650895,
            "priority": 0.783215650895,
        },
        {
            "sample_id": "us-code-15-2609-779e9b9bd42b41ce",
            "predicted_family": "deontic",
            "target_family": "frame",
            "family_margin": -0.93192212073,
            "priority": 1.08192212073,
        },
        {
            "sample_id": "us-code-25-161a-0ad18935e7e66c88",
            "predicted_family": "deontic",
            "target_family": "temporal",
            "family_margin": -0.608483280117,
            "priority": 0.758483280117,
        },
        {
            "sample_id": "us-code-42-7548.-cf5b403516795f91",
            "predicted_family": "deontic",
            "target_family": "deontic",
            "family_margin": 0.006839236661,
            "priority": 0.143160763339,
        },
        {
            "sample_id": "us-code-16-577-e948c18513940d18",
            "predicted_family": "deontic",
            "target_family": "temporal",
            "family_margin": -0.159881814606,
            "priority": 0.309881814606,
        },
        {
            "sample_id": "us-code-14-2732-1f6e3444b9eaadb3",
            "predicted_family": "temporal",
            "target_family": "deontic",
            "family_margin": -0.288118476192,
            "priority": 0.438118476192,
        },
        {
            "sample_id": "us-code-22-9423-71ff0923ec99503f",
            "predicted_family": "epistemic",
            "target_family": "deontic",
            "family_margin": -0.374500567509,
            "priority": 0.524500567509,
        },
        {
            "sample_id": "us-code-54-100754.-262391721b1a3d83",
            "predicted_family": "deontic",
            "target_family": "frame",
            "family_margin": -0.801841083901,
            "priority": 0.951841083901,
        },
        {
            "sample_id": "us-code-26-529-5768ffa99b942174",
            "predicted_family": "conditional_normative",
            "target_family": "deontic",
            "family_margin": -0.09616716178,
            "priority": 0.24616716178,
        },
        {
            "sample_id": "us-code-24-16-244f147750bf2156",
            "predicted_family": "temporal",
            "target_family": "deontic",
            "family_margin": -0.168714079505,
            "priority": 0.318714079505,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])

        if predicted_family == "temporal":
            predicted_system = "LTL"
            predicted_symbol = "F"
            predicted_label = "eventually"
        elif predicted_family == "conditional_normative":
            predicted_system = "KD"
            predicted_symbol = "O|"
            predicted_label = "conditional_obligation"
        elif predicted_family == "frame":
            predicted_system = "FRAME_BM25"
            predicted_symbol = "Frame"
            predicted_label = "frame"
        elif predicted_family == "epistemic":
            predicted_system = "S5"
            predicted_symbol = "K"
            predicted_label = "knowledge"
        else:
            predicted_system = "D"
            predicted_symbol = "O"
            predicted_label = "obligation"

        if predicted_family == target_family and family_margin > 0.0:
            predicted_share = 0.9
            runner_up_share = predicted_share - family_margin
            runner_up_family = "temporal" if predicted_family != "temporal" else "deontic"
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 0,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        else:
            predicted_share = 0.9
            target_share = predicted_share + family_margin
            if target_share < 0.0:
                predicted_share = min(0.99, abs(family_margin) + 0.05)
                target_share = predicted_share + family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": target_family,
                    "count": 0,
                    "share_raw": target_share,
                    "share": target_share,
                },
            ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        candidate_ids = (
            [predicted_family]
            if predicted_family == target_family
            else [predicted_family, target_family]
        )
        margin_direction = "contested" if family_margin > 0.0 else "outvoted"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
        )
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-003252-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} ambiguity evidence.",
            normalized_text=f"Synthetic {predicted_family} ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-003252-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="42 U.S.C. 1983",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == margin_direction
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_effective_family_margin_threshold"])
                - 0.1515
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["adaptive_pair_margin_buffer"]) - 0.0015)
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["priority"]) - float(scenario["priority"]))
            < 1e-12
        )
        assert (
            base_ambiguity.severity
            == ("review" if margin_direction == "contested" else "requires_rule")
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000964_frame_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    assert COMPILER_AMBIGUITY_PACKET_000964_FAMILY_PAIRS == (
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "doxastic"),
        ("frame", "frame"),
        ("frame", "temporal"),
    )
    scenarios = (
        {
            "sample_id": "us-code-18-1914-bcaaee62392caeab",
            "target_family": "temporal",
            "family_margin": -0.99641111483,
            "priority": 1.14641111483,
            "pair_buffer": 0.002,
        },
        {
            "sample_id": "us-code-26-5671-ae1c0f1582e272b5",
            "target_family": "doxastic",
            "family_margin": -0.66424057129,
            "priority": 0.81424057129,
            "pair_buffer": 0.0015,
        },
        {
            "sample_id": "us-code-33-2213a-a015499eddb1f5f6",
            "target_family": "conditional_normative",
            "family_margin": -0.999996093656,
            "priority": 1.149996093656,
            "pair_buffer": 0.0015,
        },
        {
            "sample_id": "us-code-29-556-58afd11326e7f4da",
            "target_family": "deontic",
            "family_margin": -0.270106769328,
            "priority": 0.420106769328,
            "pair_buffer": 0.0015,
        },
        {
            "sample_id": "us-code-7-2009aa-6-1eaf249f86c04deb",
            "target_family": "frame",
            "family_margin": 0.113541349777,
            "priority": 0.036458650223,
            "pair_buffer": 0.135,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = "frame"
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])
        if target_family == predicted_family:
            predicted_share = 0.9
            runner_up_share = predicted_share - family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": "deontic",
                    "count": 0,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
            candidate_ids = [predicted_family]
            margin_direction = "contested"
        else:
            predicted_share = 0.9
            target_share = predicted_share + family_margin
            if target_share < 0.0:
                predicted_share = min(0.99, abs(family_margin) + 0.05)
                target_share = predicted_share + family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": target_family,
                    "count": 0,
                    "share_raw": target_share,
                    "share": target_share,
                },
            ]
            candidate_ids = [predicted_family, target_family]
            margin_direction = "outvoted"
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
        )
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000964-adaptive-evidence-{index}",
            text="Synthetic frame ambiguity evidence.",
            normalized_text="Synthetic frame ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="frame",
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                )
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000964-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-packet-000964-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system="FRAME_BM25",
                        symbol="Frame",
                        label="frame",
                    ),
                    predicate=ModalIRPredicate(
                        name="frame_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation=sample_id,
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == margin_direction
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_pair_margin_buffer"])
                - float(scenario["pair_buffer"])
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.severity == (
            "review" if margin_direction == "contested" else "requires_rule"
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_004179_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-50-42.-665c7c7be93a2efb",
            "predicted_family": "temporal",
            "target_family": "temporal",
            "family_margin": 0.056860653465,
            "priority": 0.093139346535,
        },
        {
            "sample_id": "us-code-23-211-603aa21444235f4c",
            "predicted_family": "temporal",
            "target_family": "frame",
            "family_margin": -0.294900910575,
            "priority": 0.444900910575,
        },
        {
            "sample_id": "us-code-43-865.-accc0d9373411518",
            "predicted_family": "deontic",
            "target_family": "temporal",
            "family_margin": -0.898763768022,
            "priority": 1.048763768022,
        },
        {
            "sample_id": "us-code-16-539m-9-773b0e2200077606",
            "predicted_family": "deontic",
            "target_family": "deontic",
            "family_margin": 0.038429045525,
            "priority": 0.111570954475,
        },
        {
            "sample_id": "us-code-26-6071-40357f1b21882f9e",
            "predicted_family": "temporal",
            "target_family": "temporal",
            "family_margin": 0.075764931006,
            "priority": 0.074235068994,
        },
        {
            "sample_id": "us-code-48-1408.-f543c41139afcd79",
            "predicted_family": "deontic",
            "target_family": "frame",
            "family_margin": -0.718788984161,
            "priority": 0.868788984161,
        },
    )

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])

        if predicted_family == "temporal":
            predicted_system = "LTL"
            predicted_symbol = "F"
            predicted_label = "eventually"
        elif predicted_family == "frame":
            predicted_system = "FRAME_BM25"
            predicted_symbol = "Frame"
            predicted_label = "frame"
        else:
            predicted_system = "D"
            predicted_symbol = "O"
            predicted_label = "obligation"

        if predicted_family == target_family and family_margin > 0.0:
            predicted_share = 0.9
            runner_up_share = predicted_share - family_margin
            runner_up_family = "temporal" if predicted_family != "temporal" else "deontic"
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 0,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        else:
            predicted_share = 0.9
            target_share = predicted_share + family_margin
            if target_share < 0.0:
                predicted_share = min(0.99, abs(family_margin) + 0.05)
                target_share = predicted_share + family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": target_family,
                    "count": 0,
                    "share_raw": target_share,
                    "share": target_share,
                },
            ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        candidate_ids = (
            [predicted_family]
            if predicted_family == target_family
            else [predicted_family, target_family]
        )
        margin_direction = "contested" if family_margin > 0.0 else "outvoted"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
        )
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-004179-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} ambiguity evidence.",
            normalized_text=f"Synthetic {predicted_family} ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-004179-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="42 U.S.C. 1983",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == margin_direction
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_effective_family_margin_threshold"])
                - 0.1515
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["adaptive_pair_margin_buffer"]) - 0.0015)
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["priority"]) - float(scenario["priority"]))
            < 1e-12
        )
        assert (
            base_ambiguity.severity
            == ("review" if margin_direction == "contested" else "requires_rule")
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000111_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-33-3803-ac8f8e7ef6c14117",
            "predicted_family": "deontic",
            "target_family": "conditional_normative",
            "family_margin": -0.15381837787,
            "priority": 0.30381837787,
        },
        {
            "sample_id": "us-code-10-2263-571407a5044f94b2",
            "predicted_family": "temporal",
            "target_family": "frame",
            "family_margin": -0.602948048611,
            "priority": 0.752948048611,
        },
        {
            "sample_id": "us-code-38-1731-7736f9e2e50472ec",
            "predicted_family": "temporal",
            "target_family": "deontic",
            "family_margin": -0.020147733483,
            "priority": 0.170147733483,
        },
        {
            "sample_id": "us-code-2-5541-462165e82b6b68ce",
            "predicted_family": "frame",
            "target_family": "conditional_normative",
            "family_margin": -0.06766595464,
            "priority": 0.21766595464,
        },
    )
    expected_pairs = {
        (str(scenario["predicted_family"]), str(scenario["target_family"]))
        for scenario in scenarios
    }
    assert expected_pairs.issubset(set(COMPILER_AMBIGUITY_PACKET_000111_FAMILY_PAIRS))

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])

        if predicted_family == "temporal":
            predicted_system = "LTL"
            predicted_symbol = "F"
            predicted_label = "eventually"
        elif predicted_family == "frame":
            predicted_system = "FRAME_BM25"
            predicted_symbol = "Frame"
            predicted_label = "frame"
        else:
            predicted_system = "D"
            predicted_symbol = "O"
            predicted_label = "obligation"

        predicted_share = 0.9
        target_share = predicted_share + family_margin
        if target_share < 0.0:
            predicted_share = min(0.99, abs(family_margin) + 0.05)
            target_share = predicted_share + family_margin
        ranking = [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": predicted_share,
            },
            {
                "family": target_family,
                "count": 0,
                "share_raw": target_share,
                "share": target_share,
            },
        ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        policy_pair = f"{predicted_family}->{target_family}"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000111-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} ambiguity evidence.",
            normalized_text=f"Synthetic {predicted_family} ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000111-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-000111",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.severity == "requires_rule"
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_effective_family_margin_threshold"])
                - 0.1515
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["adaptive_pair_margin_buffer"]) - 0.0015)
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == [predicted_family, target_family]
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )


def test_modal_compiler_surfaces_packet_000205_compiler_ambiguity_policy_pairs(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        ModalCompilerConfig(
            parser_backend="regex",
            frame_score_margin=0.0,
            modal_adaptive_family_margin=0.15,
        )
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    scenarios = (
        {
            "sample_id": "us-code-45-916.-bab48ead3b1dd179",
            "predicted_family": "frame",
            "target_family": "conditional_normative",
            "family_margin": -0.992292762601,
            "priority": 1.142292762601,
        },
        {
            "sample_id": "us-code-15-7609-a6c624371927ff8b",
            "predicted_family": "temporal",
            "target_family": "deontic",
            "family_margin": -0.522202249443,
            "priority": 0.672202249443,
        },
        {
            "sample_id": "us-code-36-220314-f81a9efb8f36f101",
            "predicted_family": "deontic",
            "target_family": "frame",
            "family_margin": -0.218077315288,
            "priority": 0.368077315288,
        },
        {
            "sample_id": "us-code-20-7291-bf8ffbef55c6755e",
            "predicted_family": "deontic",
            "target_family": "deontic",
            "family_margin": 0.040912542968,
            "priority": 0.109087457032,
        },
        {
            "sample_id": "us-code-21-2371-5928235dfbd9d934",
            "predicted_family": "frame",
            "target_family": "frame",
            "family_margin": 0.057770921239,
            "priority": 0.092229078761,
        },
        {
            "sample_id": "us-code-42-11923.-129b791c64413e4d",
            "predicted_family": "conditional_normative",
            "target_family": "deontic",
            "family_margin": -0.067457917465,
            "priority": 0.217457917465,
        },
        {
            "sample_id": "us-code-49-44301.-632df503bf6b0c75",
            "predicted_family": "frame",
            "target_family": "deontic",
            "family_margin": -0.299413801472,
            "priority": 0.449413801472,
        },
    )
    expected_pairs = {
        (str(scenario["predicted_family"]), str(scenario["target_family"]))
        for scenario in scenarios
    }
    assert expected_pairs.issubset(set(COMPILER_AMBIGUITY_PACKET_000205_FAMILY_PAIRS))

    for index, scenario in enumerate(scenarios, start=1):
        predicted_family = str(scenario["predicted_family"])
        target_family = str(scenario["target_family"])
        family_margin = float(scenario["family_margin"])
        sample_id = str(scenario["sample_id"])

        if predicted_family == "temporal":
            predicted_system = "LTL"
            predicted_symbol = "F"
            predicted_label = "eventually"
        elif predicted_family == "conditional_normative":
            predicted_system = "KD"
            predicted_symbol = "O|"
            predicted_label = "conditional_obligation"
        elif predicted_family == "frame":
            predicted_system = "FRAME_BM25"
            predicted_symbol = "Frame"
            predicted_label = "frame"
        else:
            predicted_system = "D"
            predicted_symbol = "O"
            predicted_label = "obligation"

        if predicted_family == target_family and family_margin > 0.0:
            predicted_share = 0.9
            runner_up_share = predicted_share - family_margin
            runner_up_family = "temporal" if predicted_family != "temporal" else "deontic"
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": runner_up_family,
                    "count": 0,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                },
            ]
        else:
            predicted_share = 0.9
            target_share = predicted_share + family_margin
            if target_share < 0.0:
                predicted_share = min(0.99, abs(family_margin) + 0.05)
                target_share = predicted_share + family_margin
            ranking = [
                {
                    "family": predicted_family,
                    "count": 0,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                },
                {
                    "family": target_family,
                    "count": 0,
                    "share_raw": target_share,
                    "share": target_share,
                },
            ]
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        candidate_ids = (
            [predicted_family]
            if predicted_family == target_family
            else [predicted_family, target_family]
        )
        margin_direction = "contested" if family_margin > 0.0 else "outvoted"
        expected_explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
        )
        encoding = SpaCyLegalEncoding(
            document_id=f"packet-000205-adaptive-evidence-{index}",
            text=f"Synthetic {predicted_family} ambiguity evidence.",
            normalized_text=f"Synthetic {predicted_family} ambiguity evidence.",
            tokens=[],
            sentences=[],
            cues=[
                SpaCyModalCueFeature(
                    family=predicted_family,
                    system=predicted_system,
                    symbol=predicted_symbol,
                    label=predicted_label,
                    cue=predicted_family,
                    start_char=0,
                    end_char=len(predicted_family),
                    token_indices=[],
                ),
            ],
        )
        modal_ir = ModalIRDocument(
            document_id=f"packet-000205-adaptive-evidence-{index}",
            source="us_code",
            normalized_text=encoding.normalized_text,
            formulas=[
                ModalIRFormula(
                    formula_id=f"f-{predicted_family}-{index}",
                    operator=ModalIROperator(
                        family=predicted_family,
                        system=predicted_system,
                        symbol=predicted_symbol,
                        label=predicted_label,
                    ),
                    predicate=ModalIRPredicate(
                        name=f"{predicted_family}_predicate",
                        arguments=["actor:agency"],
                        role="clause",
                    ),
                    provenance=ModalIRProvenance(
                        source_id=sample_id,
                        start_char=0,
                        end_char=len(encoding.normalized_text),
                        citation="packet-000205",
                    ),
                ),
            ],
        )

        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        policy_pair = f"{predicted_family}->{target_family}"
        base_ambiguity = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == "adaptive_family_margin_low"
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
        )
        assert base_ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert base_ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert base_ambiguity.metadata["adaptive_margin_direction"] == margin_direction
        assert (
            abs(float(base_ambiguity.metadata["family_margin_raw"]) - family_margin)
            < 1e-12
        )
        assert (
            abs(
                float(base_ambiguity.metadata["adaptive_priority"])
                - float(scenario["priority"])
            )
            < 1e-12
        )
        assert (
            abs(float(base_ambiguity.metadata["priority"]) - float(scenario["priority"]))
            < 1e-12
        )
        assert (
            base_ambiguity.severity
            == ("review" if margin_direction == "contested" else "requires_rule")
        )
        assert base_ambiguity.metadata["explicit_ambiguity_type"] == expected_explicit_type
        assert any(
            ambiguity.ambiguity_type == expected_explicit_type
            and ambiguity.candidate_ids == candidate_ids
            and ambiguity.metadata["adaptive_policy_pair"] == policy_pair
            and ambiguity.metadata["adaptive_base_ambiguity_type"]
            == "adaptive_family_margin_low"
            for ambiguity in ambiguities
        )
def _single_formula_document(
    *,
    family: str,
    symbol: str,
    label: str,
    text: str,
    predicate: str,
    conditions: list[str] | None = None,
) -> ModalIRDocument:
    return ModalIRDocument(
        document_id=f"typed-target-reconstruction-{family}",
        source="unit",
        normalized_text=text,
        formulas=[
            ModalIRFormula(
                formula_id="f1",
                operator=ModalIROperator(
                    family=family,
                    system="unit",
                    symbol=symbol,
                    label=label,
                ),
                predicate=ModalIRPredicate(name=predicate),
                provenance=ModalIRProvenance(
                    source_id="unit",
                    start_char=0,
                    end_char=len(text),
                    citation="1 U.S.C. 1",
                ),
                conditions=conditions or [],
            )
        ],
        metadata={"citation": "1 U.S.C. 1"},
    )


def test_decompiler_emits_frame_target_reconstruction_slots_for_conditioned_temporal_scope() -> None:
    document = _single_formula_document(
        family="frame",
        symbol="Frame",
        label="frame",
        text=(
            "After August 8, 2005, the Secretary shall not designate a facility "
            "that is not listed in section 15801 as a National Laboratory."
        ),
        predicate="national_laboratory_designation",
        conditions=["after August 8, 2005"],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(document)
    )

    assert "conditioned+temporal:frame->temporal" in slot_texts[
        "typed-decompiler-target-reconstruction-scope"
    ]
    assert (
        "temporal-priority:temporal-guard:none:temporal:f:clause"
        in slot_texts["defeasible-priority"]
    )
    assert (
        "system-binding:ltl:temporal:f:temporal-order:clause"
        in slot_texts["entity-binding"]
    )


def test_decompiler_emits_provided_that_target_reconstruction_surface_cues() -> None:
    document = _single_formula_document(
        family="frame",
        symbol="Frame",
        label="frame",
        text=(
            "Fees may be charged provided that the amounts remain available "
            "for each fiscal year."
        ),
        predicate="internal_service_fee",
        conditions=[
            "provided that the amounts remain available for each fiscal year"
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(document)
    )

    assert "conditioned+temporal:frame->conditional_normative" in slot_texts[
        "typed-decompiler-target-reconstruction-scope"
    ]
    assert "provided_that:frame->conditional_normative" in slot_texts[
        "typed-decompiler-target-reconstruction-surface-cue"
    ]
    assert "provided_that:frame->temporal" in slot_texts[
        "typed-decompiler-target-reconstruction-surface-cue"
    ]


def test_decompiler_emits_permission_enabling_and_temporal_to_deontic_slots() -> None:
    deontic_document = _single_formula_document(
        family="deontic",
        symbol="P",
        label="permission",
        text=(
            "The Director may provide grants for independent living services "
            "during fiscal year 2026."
        ),
        predicate="director_may_provide_grants",
    )
    temporal_document = _single_formula_document(
        family="temporal",
        symbol="F",
        label="eventuality",
        text=(
            "The Center may provide services during fiscal year 2026 under "
            "this section."
        ),
        predicate="center_may_provide_services",
    )

    deontic_slots = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(deontic_document)
    )
    temporal_slots = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(temporal_document)
    )

    assert (
        "force-polarity-family-pair:permission:enabling:deontic->temporal"
        in deontic_slots["decompiler-plan"]
    )
    assert "conditioned+temporal:temporal->deontic" not in temporal_slots.get(
        "typed-decompiler-target-reconstruction-scope",
        [],
    )
    assert "temporal:temporal->deontic" in temporal_slots[
        "typed-decompiler-target-reconstruction-scope"
    ]
    assert "under" in temporal_slots["typed-decompiler-source-scope-cue"]
    assert (
        "source-ir-role:action:none:temporal:f:clause"
        in temporal_slots["entity-binding"]
    )


def test_decompiler_emits_source_scope_slots_for_within_and_deadline_cues() -> None:
    document = _single_formula_document(
        family="deontic",
        symbol="O",
        label="obligation",
        text=(
            "The agency must provide notice within 30 days and no later than "
            "45 days after review."
        ),
        predicate="agency_must_provide_notice",
    )

    slot_texts = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(document)
    )

    assert "within" in slot_texts["typed-decompiler-source-scope-cue"]
    assert "no_later_than" in slot_texts["typed-decompiler-source-scope-cue"]
    assert any(
        value.startswith("deontic:")
        and "|typed-decompiler-force-polarity:obligation:" in value
        for value in slot_texts["typed-decompiler-source-predicate-force-pair"]
    )
    assert any(
        value.startswith("condition+subject+action+object+temporal:deontic|")
        for value in slot_texts[
            "typed-decompiler-source-clause-topology-family-pair"
        ]
    )


def _token_overlap_ratio(left: str, right: str) -> float:
    left_tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_'-]*", left)
    }
    right_tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_'-]*", right)
    }
    if not left_tokens:
        return 1.0 if not right_tokens else 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)
