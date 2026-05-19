"""Tests for the canonical deterministic modal logic codec."""

from __future__ import annotations

from dataclasses import replace
import re

from ipfs_datasets_py.logic.modal import (
    DeterministicModalCompiler,
    DeterministicModalLogicCodec,
    ModalCompilerConfig,
    ModalLogicCodecConfig,
    decode_modal_ir_document,
    decoded_modal_phrase_slot_text_map,
    import_graph_data_to_graph_engine,
    modal_ir_to_flogic_triples,
    modal_formula_to_text,
    modal_text_token_similarity,
    synthesis_hints_from_autoencoder_introspection,
)
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
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoding,
    SpaCyModalCueFeature,
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
    assert all(ambiguity.metadata["family_margin"] < 0.0 for ambiguity in adaptive_ambiguities)


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
                    citation="10 U.S.C. 649j",
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
    assert (
        adaptive_frame.metadata["explicit_ambiguity_type"]
        == "adaptive_hybrid_frame_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_hybrid_frame_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
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
    assert (
        adaptive_temporal.metadata["explicit_ambiguity_type"]
        == "adaptive_frame_temporal_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_temporal_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
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
    assert (
        adaptive_epistemic.metadata["explicit_ambiguity_type"]
        == "adaptive_frame_epistemic_outvoted_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_frame_epistemic_outvoted_margin_low"
        and ambiguity.metadata["signal_free_pair_policy_applied"] is True
        for ambiguity in ambiguities
    )


def test_modal_compiler_surfaces_epistemic_deontic_contested_adaptive_ambiguity() -> None:
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
    assert adaptive_deontic.metadata["adaptive_margin_direction"] == "contested"
    assert adaptive_deontic.metadata["is_priority_policy_pair"] is False
    assert adaptive_deontic.metadata["explicit_ambiguity_type"] == (
        "adaptive_epistemic_deontic_contested_margin_low"
    )
    assert adaptive_deontic.severity == "review"
    assert any(
        ambiguity.ambiguity_type == "adaptive_epistemic_deontic_contested_margin_low"
        and ambiguity.metadata["family_margin"] == 0.0
        for ambiguity in ambiguities
    )


def test_modal_compiler_surfaces_epistemic_self_pair_adaptive_ambiguity_for_low_runner_up_margin() -> None:
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
    assert adaptive_temporal_self.metadata["family_margin"] == 0.0
    assert adaptive_temporal_self.metadata["adaptive_margin_direction"] == "contested"
    assert (
        adaptive_temporal_self.metadata["explicit_ambiguity_type"]
        == "adaptive_temporal_temporal_contested_margin_low"
    )
    assert any(
        ambiguity.ambiguity_type == "adaptive_temporal_temporal_contested_margin_low"
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
            {"family": "temporal", "count": 2, "share": 0.47},
        ],
        family_shares={"frame": 0.53, "temporal": 0.47},
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
    assert adaptive_frame_self.metadata["predicted_margin_to_runner_up"] == 0.06
    assert adaptive_frame_self.metadata["family_margin"] == 0.0
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
    assert adaptive_frame.metadata["family_margin"] == -0.216733
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
        and ambiguity.metadata["family_margin"] == -0.216733
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
    assert conditional_scope.metadata["target_share"] == 0.0
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
    assert temporal_scope.metadata["target_share"] == 0.0
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
    assert "O[deontic:D]" not in result.decoded_text
    assert "obligatory" not in result.decoded_text
    assert modal_text_token_similarity(source, result.decoded_text) == 1.0


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
