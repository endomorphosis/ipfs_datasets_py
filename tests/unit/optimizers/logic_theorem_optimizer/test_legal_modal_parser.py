"""Tests for the deterministic legal modal parser scaffold."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import LegalModalParser
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
    DataType,
    LogicExtractionContext,
    LogicExtractor,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_critic import LogicCritic


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
_USCODE_50_2523B_RESIDUAL_SPAN_TEXT = (
    "Sec. 2523b - Transfer authority and procedures. Administrative notice and hearing "
    "procedures are established for this section. Editorial Notes Codification Section "
    "2523b was editorially reclassified as section 3373b of this title."
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
_USCODE_36_21110_TODO_TEXT = (
    "Sec. 21110 - Administrative notice and hearing activities. "
    "Historical and Revision Notes."
)
_USCODE_10_1095C_TODO_TEXT = (
    "Administrative review procedures are established for health care collection actions."
)
_USCODE_19_2113_TODO_TEXT = (
    "Administrative notice and hearing procedures are established for import petitions."
)
_USCODE_7_7913_TEXT = (
    "U.S.C. Title 7 - AGRICULTURE 7 U.S.C. United States Code, 2024 Edition "
    "Title 7 - AGRICULTURE CHAPTER 106 - COMMODITY PROGRAMS SUBCHAPTER I - "
    "DIRECT PAYMENTS AND COUNTER-CYCLICAL PAYMENTS Sec. 7913 - Availability of "
    "direct payments From the U.S. Government Publishing Office, www.gpo.gov "
    "§7913. Availability of direct payments (a) Payment required For each of "
    "the 2002 through 2007 crop years of each covered commodity, the Secretary "
    "shall make direct payments to producers on farms for which payment yields "
    "and base acres are established. (b) Payment rate The payment rates used "
    "to make direct payments with respect to covered commodities for a crop "
    "year are as follows: (1) Wheat, $0.52 per bushel. (2) Corn, $0.28 per "
    "bushel. (3) Grain sorghum, $0.35 per bushel. (4) Barley, $0.24 per bushel. "
    "(5) Oats, $0.024 per bushel. (6) Upland cotton, $0.0667 per pound. (7) "
    "Rice, $2.35 per hundredweight. (8) Soybeans, $0.44 per bushel. (9) Other "
    "oilseeds, $0.0080 per pound. (c) Payment amount The amount of the direct "
    "payment to be paid to the producers on a farm for a covered commodity for "
    "a crop year shall be equal to the product of the following: (1) The "
    "payment rate specified in subsection (b). (2) The payment acres of the "
    "covered commodity on the farm. (3) The payment yield for the covered "
    "commodity for the farm. (d) Time for payment (1) In general The Secretary "
    "shall make direct payments— (A) in the case of the 2002 crop year, as soon "
    "as practicable after May 13, 2002; and (B) in the case of each of the 2003 "
    "through 2007 crop years, not before October 1 of the calendar year in "
    "which the crop of the covered commodity is harvested. (2) Advance payments "
    "At the option of the producers on a farm, up to 50 percent of the direct "
    "payment for a covered commodity for any of the 2003 through 2005 crop "
    "years, up to 40 percent of the direct payment for a covered commodity for "
    "the 2006 crop year, and up to 22 percent of the direct payment for a "
    "covered commodity for the 2007 crop year, shall be paid to the producers "
    "in advance. The producers shall select the month within which the advance "
    "payment for a crop year will be made. The month selected may be any month "
    "during the period beginning on December 1 of the calendar year before the "
    "calendar year in which the crop of the covered commodity is harvested "
    "through the month within which the direct payment would otherwise be made. "
    "The producers may change the selected month for a subsequent advance pay "
    "ment by providing advance notice to the Secretary. (3) Repayment of "
    "advance payments If a producer on a farm that receives an advance direct "
    "payment for a crop year ceases to be a producer on that farm, or the "
    "extent to which the producer shares in the risk of producing a crop "
    "changes, before the date the remainder of the direct payment is made, the "
    "producer shall be responsible for repaying the Secretary the applicable "
    "amount of the advance payment, as determined by the Secretary. (Pub. L. "
    "107–171, title I, §1103, May 13, 2002, 116 Stat. 149; Pub. L. 109–171, "
    "title I, §1102(a), Feb. 8, 2006, 120 Stat. 5.) Editorial Notes Amendments "
    "2006 —Subsec. (d)(2). Pub. L. 109–171 substituted \"2005 crop years, up "
    "to 40 percent of the direct payment for a covered commodity for the 2006 "
    "crop year, and up to 22 percent of the direct payment for a covered "
    "commodity for the 2007 crop year,\" for \"2007 crop years\"."
)
_USCODE_16_6410_SYMBOLIC_VALIDITY_TEXT = (
    "U.S.C. Title 16 - CONSERVATION 16 U.S.C. United States Code, 2024 Edition "
    "Title 16 - CONSERVATION CHAPTER 83 - CORAL REEF CONSERVATION Sec. 6410 - "
    "Ruth D. Gates Coral Reef Conservation Grant Program From the U.S. Government "
    "Publishing Office, www.gpo.gov \u00a76410. Ruth D. Gates Coral Reef "
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
    "Government Publishing Office, www.gpo.gov \u00a747a. Addition of certain "
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
    "Publishing Office, www.gpo.gov \u00a7614. Separability If any provision of "
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
_USCODE_25_422_HEADING_ONLY_TEXT = "Housing voucher benefits and utility allowances."
_USCODE_48_1572_HEADING_ONLY_TEXT = "Administrative notice and hearing."
_USCODE_42_6323_HEADING_ONLY_TEXT = "Notice and hearing requirements."
_USCODE_42_18791_TODO_TEXT = "Sec. 18791 - Administrative provisions. Additional provisions."
_USCODE_7_431_TODO_TEXT = "Sec. 431 - Declaration of policy."
_USCODE_6_257_TODO_TEXT = "Sec. 257 - National planning scenarios and preparedness targets."
_USCODE_45_81_TO_92_TODO_TEXT = "Secs. 81 to 92. Repealed."
_USCODE_6_314_TODO_TEXT = "National planning scenarios, preparedness targets, and implementation guidance."
_USCODE_35_4_TODO_TEXT = "Officers, employees, and attorneys."
_USCODE_7_7316_TODO_TEXT = "Report."
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


def _coarse_uscode_heading_noise_text(section: str, heading: str) -> str:
    noise_tokens = " ".join(chr(ord("a") + (index % 26)) for index in range(160))
    return (
        "U S C title archive register digest taxonomy index chapter crosswalk "
        f"sec {section} {heading} "
        f"{noise_tokens}"
    )


def _coarse_uscode_procedural_heading_noise_text(section: str, heading: str) -> str:
    noise_tokens = " ".join(chr(ord("k") + (index % 10)) for index in range(180))
    return (
        "U S C title archive register digest taxonomy index chapter crosswalk "
        f"sec {section} {heading} is archive "
        f"{noise_tokens}"
    )


def test_parser_normalizes_and_segments_legal_text() -> None:
    parser = LegalModalParser()
    text = "  The agency   must provide notice. Unless waived, the applicant may appeal. "

    segments = parser.segment(text)

    assert [segment.text for segment in segments] == [
        "The agency must provide notice.",
        "Unless waived, the applicant may appeal.",
    ]
    assert segments[1].role == "condition"


def test_parser_extracts_deontic_and_temporal_cues() -> None:
    parser = LegalModalParser()

    cues = parser.extract_cues("The agency must respond within 30 days.")
    families = {cue.family.value for cue in cues}
    cue_terms = {cue.cue for cue in cues}

    assert "deontic" in families
    assert "temporal" in families
    assert {"must", "within"}.issubset(cue_terms)


def test_parser_compiles_cues_to_modal_ir_with_provenance() -> None:
    parser = LegalModalParser()

    document = parser.parse(
        "The agency must provide notice before termination.",
        document_id="sample-doc",
        source="us_code",
        citation="5 U.S.C. 552",
    )

    assert document.document_id == "sample-doc"
    assert document.metadata["deterministic_parser"] == "legal_modal_parser_v1"
    assert document.formulas
    assert document.formulas[0].operator.family == "deontic"
    assert document.formulas[0].provenance.citation == "5 U.S.C. 552"
    assert document.formulas[0].predicate.name.startswith("provide_notice")
    assert document.canonical_hash() == document.canonical_hash()


def test_parser_extracts_condition_and_exception_slots() -> None:
    parser = LegalModalParser()

    document = parser.parse(
        "If the application is complete, the agency must issue written notice unless waived.",
        citation="5 U.S.C. 552",
    )

    deontic_formula = next(
        formula for formula in document.formulas if formula.operator.family == "deontic"
    )
    assert "if the application is complete" in deontic_formula.conditions
    assert "unless waived" in deontic_formula.exceptions


def test_parser_document_id_is_deterministic_from_normalized_text() -> None:
    parser = LegalModalParser()

    first = parser.parse("The applicant may appeal.")
    second = parser.parse(" The   applicant may appeal. ")

    assert first.document_id == second.document_id
    assert first.to_json() == second.to_json()


def test_parser_adds_uscode_codification_fallback_for_known_zero_formula_case() -> None:
    sample = build_us_code_sample(
        title="42",
        section="5668.",
        citation="42 U.S.C. 5668.",
        text=(
            "\u00a75668. Transferred Editorial Notes Codification Section 5668 was editorially "
            "reclassified as section 11174 of Title 34, Crime Control and Law Enforcement."
        ),
    )

    assert sample.sample_id == "us-code-42-5668.-a3bbd3be7319f8a1"
    assert sample.modal_ir.formulas
    fallback = sample.modal_ir.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_codification_transfer_heading_v1"


def test_parser_adds_residual_span_coverage_before_codification_fallback_for_50_2523b_style_text() -> None:
    parser = LegalModalParser()
    document = parser.parse(
        _USCODE_50_2523B_RESIDUAL_SPAN_TEXT,
        document_id="us-code-50-2523b.-9372ed91908bfe9a",
        source="us_code",
        citation="50 U.S.C. 2523b.",
    )

    assert document.formulas
    assert len({formula.formula_id for formula in document.formulas}) == len(document.formulas)
    fallback = document.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
    residual_formulas = [
        formula
        for formula in document.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    assert residual_formulas
    assert all(
        formula.provenance.citation == "50 U.S.C. 2523b."
        for formula in document.formulas
    )


def test_parser_replays_transferred_heading_zero_formula_sample_for_15_688() -> None:
    parser = LegalModalParser()
    document = parser.parse(
        "\u00a7688. Transferred.",
        document_id="us-code-15-688-3977b0476c11fbf1",
        source="us_code",
        citation="15 U.S.C. 688",
    )

    assert document.document_id == "us-code-15-688-3977b0476c11fbf1"
    assert document.formulas
    fallback = document.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
    assert fallback.provenance.citation == "15 U.S.C. 688"


def test_parser_replays_transferred_heading_zero_formula_sample_for_10_7082() -> None:
    parser = LegalModalParser()
    document = parser.parse(
        "\u00a77082. Transferred.",
        document_id="us-code-10-7082-9e036c2a899ad874",
        source="us_code",
        citation="10 U.S.C. 7082",
    )

    assert document.document_id == "us-code-10-7082-9e036c2a899ad874"
    assert document.formulas
    fallback = document.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
    assert fallback.provenance.citation == "10 U.S.C. 7082"


def test_parser_replays_spaced_transferred_heading_zero_formula_samples() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
        assert fallback.provenance.citation == citation


def test_parser_replays_sec_prefixed_transferred_heading_zero_formula_samples() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
        assert fallback.provenance.citation == citation


def test_parser_replays_sec_prefixed_heading_zero_formula_sample_for_15_1693l() -> None:
    parser = LegalModalParser()
    document = parser.parse(
        "Sec. 1693l - Waiver of rights.",
        document_id="us-code-15-1693l-62b207bc138a3216",
        source="us_code",
        citation="15 U.S.C. 1693l",
    )

    assert document.document_id == "us-code-15-1693l-62b207bc138a3216"
    assert document.formulas
    fallback = document.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
    assert fallback.provenance.citation == "15 U.S.C. 1693l"


def test_parser_replays_embedded_sec_heading_zero_formula_samples() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
        assert fallback.provenance.citation == citation


def test_parser_replays_editorial_status_zero_formula_sample_for_18_3008() -> None:
    parser = LegalModalParser()
    document = parser.parse(
        "\u00a73008. Repealed.",
        document_id="us-code-18-3008-62db8e945327b1ec",
        source="us_code",
        citation="18 U.S.C. 3008",
    )

    assert document.document_id == "us-code-18-3008-62db8e945327b1ec"
    assert document.formulas
    fallback = document.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_editorial_status_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_editorial_status_heading_v1"
    assert fallback.metadata["status_keyword"] == "repealed"
    assert fallback.provenance.citation == "18 U.S.C. 3008"


def test_parser_replays_packet_todo_samples_for_7_431_6_257_and_45_81_to_92() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == cue
        assert fallback.metadata["fallback_rule"] == fallback_rule
        if status_keyword:
            assert fallback.metadata["status_keyword"] == status_keyword
        assert fallback.provenance.citation == citation


def test_parser_replays_packet_todo_heading_only_samples_for_6_314_35_4_and_7_7316() -> None:
    parser = LegalModalParser()
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

    for document_id, citation, text in cases:
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
        assert fallback.provenance.citation == citation


def test_parser_replays_packet_todo_samples_for_46_55318_8_606_and_46_115() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == cue
        assert fallback.metadata["fallback_rule"] == fallback_rule
        assert fallback.provenance.citation == citation


def test_parser_replays_uscode_declarative_statement_zero_formula_cases() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_declarative_statement_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_declarative_statement_v1"
        assert fallback.metadata["statement_hint"] == statement_hint
        assert fallback.provenance.citation == citation


def test_parser_replays_dataset_zero_formula_cases_for_59b_130a_31a_2b_60a_2_and_8906() -> None:
    parser = LegalModalParser()
    cases = [
        (
            "us-code-2-59b-8902f0eb9b420bbe",
            "2 U.S.C. 59b",
            _USCODE_2_59B_PACKET_144_TEXT,
            "__uscode_codification_fallback__",
            "uscode_transferred_heading_v1",
        ),
        (
            "us-code-2-130a-a14e984db7a8af87",
            "2 U.S.C. 130a",
            _USCODE_2_130A_TEXT,
            "__uscode_codification_fallback__",
            "uscode_transferred_heading_v1",
        ),
        (
            "us-code-2-31a-2b-a99b26c5ad622cfe",
            "2 U.S.C. 31a-2b",
            _USCODE_2_31A_2B_TEXT,
            "__uscode_codification_fallback__",
            "uscode_transferred_heading_v1",
        ),
        (
            "us-code-2-60a-2-ee0af9802f887e89",
            "2 U.S.C. 60a-2",
            _USCODE_2_60A_2_TEXT,
            "__uscode_codification_fallback__",
            "uscode_transferred_heading_v1",
        ),
        (
            "us-code-46-8906.-ebe08e6d737c3c40",
            "46 U.S.C. 8906.",
            _USCODE_46_8906_TEXT,
            "__uscode_section_heading_fallback__",
            "uscode_section_heading_v1",
        ),
    ]

    for document_id, citation, text, cue, fallback_rule in cases:
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == cue
        assert fallback.metadata["fallback_rule"] == fallback_rule
        assert fallback.provenance.citation == citation


def test_parser_replays_packet_todo_samples_for_36_110105_and_25_450() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == cue
        assert fallback.metadata["fallback_rule"] == fallback_rule
        assert fallback.provenance.citation == citation


def test_parser_replays_packet_todo_symbolic_validity_sample_for_25_5396() -> None:
    parser = LegalModalParser()
    document = parser.parse(
        _USCODE_25_5396_TODO_TEXT,
        document_id="us-code-25-5396-17291bf2fa3ae3f6",
        source="us_code",
        citation="25 U.S.C. 5396",
    )

    assert document.document_id == "us-code-25-5396-17291bf2fa3ae3f6"
    assert document.formulas
    assert any(formula.operator.family == "deontic" for formula in document.formulas)
    assert all(
        formula.provenance.citation == "25 U.S.C. 5396"
        for formula in document.formulas
    )


def test_parser_replays_packet_todo_samples_for_25_507_10_167_and_38_8112() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        assert all(formula.provenance.citation == citation for formula in document.formulas)
        if expects_codification_fallback:
            fallback = document.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_transferred_heading_v1"
        else:
            assert any(formula.operator.family == "deontic" for formula in document.formulas)


def test_parser_replays_packet_todo_samples_for_36_170307_10_1095c_and_19_2113() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_procedural_clause_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_procedural_clause_v1"
        assert fallback.metadata["procedural_keyword"] == procedural_keyword
        assert fallback.provenance.citation == citation


def test_parser_adds_short_residual_heading_span_coverage_for_36_21110_todo_shape() -> None:
    parser = LegalModalParser()
    document = parser.parse(
        _USCODE_36_21110_TODO_TEXT,
        document_id="us-code-36-21110-e10464bdc5e2ba17",
        source="us_code",
        citation="36 U.S.C. 21110",
    )

    assert document.document_id == "us-code-36-21110-e10464bdc5e2ba17"
    assert document.formulas
    fallback = document.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
    residual_formulas = [
        formula
        for formula in document.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    assert residual_formulas
    residual_text_spans = {
        document.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in residual_formulas
    }
    assert "Historical and Revision Notes." in residual_text_spans


def test_parser_adds_short_residual_heading_span_coverage_for_42_18791_todo_shape() -> None:
    parser = LegalModalParser()
    document = parser.parse(
        _USCODE_42_18791_TODO_TEXT,
        document_id="us-code-42-18791.-fa3f6f298b46c6e4",
        source="us_code",
        citation="42 U.S.C. 18791.",
    )

    assert document.document_id == "us-code-42-18791.-fa3f6f298b46c6e4"
    assert document.formulas
    fallback = document.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
    residual_formulas = [
        formula
        for formula in document.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    assert residual_formulas
    residual_text_spans = {
        document.normalized_text[
            int(formula.provenance.start_char) : int(formula.provenance.end_char)
        ].strip()
        for formula in residual_formulas
    }
    assert "Additional provisions." in residual_text_spans


def test_parser_replays_heading_only_zero_formula_cases_for_25_422_48_1572_and_42_6323() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
        assert fallback.provenance.citation == citation


def test_parser_adds_residual_heading_fallback_when_modal_cues_cover_other_segments() -> None:
    parser = LegalModalParser()
    document = parser.parse(
        (
            "Sec. 124 - Administrative notice and hearing procedures. "
            "The Secretary shall issue a decision within 30 days."
        ),
        document_id="us-code-25-124-d6ef602ae0d2e2b8",
        source="us_code",
        citation="25 U.S.C. 124",
    )

    assert document.formulas
    assert any(formula.operator.family == "deontic" for formula in document.formulas)
    fallback = document.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
    assert fallback.provenance.citation == "25 U.S.C. 124"


def test_parser_treats_may_date_literals_as_temporal_context_for_7_7913() -> None:
    parser = LegalModalParser()
    document = parser.parse(
        _USCODE_7_7913_TEXT,
        document_id="us-code-7-7913-1aaa3fd59c5ff146",
        source="us_code",
        citation="7 U.S.C. 7913",
    )

    assert document.document_id == "us-code-7-7913-1aaa3fd59c5ff146"
    assert document.formulas
    deontic_may_formulas = [
        formula
        for formula in document.formulas
        if formula.operator.family == "deontic"
        and str(formula.metadata.get("cue", "")).lower() == "may"
    ]
    # `May 13, 2002` should not be parsed as permission cues.
    assert len(deontic_may_formulas) == 2
    assert all("be_any_month_during_the_period" in formula.predicate.name or "change_the_selected_month_for_a" in formula.predicate.name for formula in deontic_may_formulas)


def test_parser_replays_symbolic_validity_samples_for_16_6410_16_47a_16_6808_7_614_and_7_7656() -> None:
    parser = LegalModalParser()
    cases = [
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

    for document_id, citation, text in cases:
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        assert all(
            formula.provenance.citation == citation
            for formula in document.formulas
        )


def test_parser_replays_long_embedded_section_heading_samples_for_8_1365b_34_50108_and_19_3702() -> None:
    parser = LegalModalParser()
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

    for document_id, citation, text in cases:
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_section_heading_v1"
        assert fallback.provenance.citation == citation


def test_parser_replays_symbolic_validity_todo_samples_with_coarse_section_heading_fallback() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            _coarse_uscode_heading_noise_text(section, heading),
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_section_heading_coarse_v1"
        assert fallback.provenance.citation == citation


def test_parser_replays_packet_todo_samples_for_7_425_10_2639_and_20_107e_1_with_coarse_procedural_headings() -> None:
    parser = LegalModalParser()
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

    for document_id, citation, section in cases:
        document = parser.parse(
            _coarse_uscode_procedural_heading_noise_text(section, heading),
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_section_heading_coarse_v1"
        assert fallback.provenance.citation == citation


def test_parser_replays_symbolic_validity_todo_samples_for_2_5602_5_5348_and_42_15251() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        assert all(formula.provenance.citation == citation for formula in document.formulas)
        if citation == "42 U.S.C. 15251.":
            fallback = document.formulas[-1]
            assert fallback.operator.family == "frame"
            assert fallback.metadata["cue"] == "__uscode_codification_fallback__"
            assert fallback.metadata["fallback_rule"] == "uscode_codification_transfer_heading_v1"


def test_parser_replays_packet_todo_samples_for_2_88b_5_42_18431_and_42_12313() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
        assert fallback.provenance.citation == citation


def test_parser_replays_packet_todo_long_heading_sample_for_43_2430() -> None:
    parser = LegalModalParser()
    document = parser.parse(
        _USCODE_43_2430_PACKET_143_TODO_TEXT,
        document_id="us-code-43-2430.-7bfbe56b01b9ee78",
        source="us_code",
        citation="43 U.S.C. 2430.",
    )

    assert document.document_id == "us-code-43-2430.-7bfbe56b01b9ee78"
    assert document.formulas
    fallback = document.formulas[-1]
    assert fallback.operator.family == "frame"
    assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
    assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
    assert fallback.provenance.citation == "43 U.S.C. 2430."


def test_parser_replays_packet_todo_article_prefixed_heading_samples_for_2_453_9_6_and_43_1656() -> None:
    parser = LegalModalParser()
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
        document = parser.parse(
            text,
            document_id=document_id,
            source="us_code",
            citation=citation,
        )

        assert document.document_id == document_id
        assert document.formulas
        fallback = document.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_section_heading_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_heading_without_section_reference_v1"
        assert fallback.provenance.citation == citation


def test_logic_extractor_uses_deterministic_modal_parser_without_llm() -> None:
    class FailingBackend:
        def generate(self, request):  # pragma: no cover - should never be called
            raise AssertionError("LLM backend should not be called for deterministic modal parsing")

    extractor = LogicExtractor(
        backend=FailingBackend(),
        use_ipfs_accelerate=False,
        enable_formula_translation=False,
        enable_kg_integration=False,
        enable_rag_integration=False,
    )
    context = LogicExtractionContext(
        data="The agency must provide notice within 30 days.",
        data_type=DataType.TEXT,
        domain="legal",
        config={"extraction_mode": "modal", "modal_profile": "deontic:D"},
        hints=["5 U.S.C. 552"],
    )

    result = extractor.extract(context)

    assert result.success is True
    assert result.statements
    assert result.metrics["llm_call_count"] == 0
    assert result.metrics["deterministic_coverage_ratio"] == 1.0
    assert result.metrics["modal_profile"] == "deontic:D"
    assert result.metrics["modal_families"] == ["deontic", "temporal"]
    assert all(statement.formalism == "modal" for statement in result.statements)
    assert all(statement.metadata["deterministic_parser"] == "legal_modal_parser_v1" for statement in result.statements)
    assert {statement.metadata["modal_family"] for statement in result.statements} >= {"deontic", "temporal"}


def test_logic_critic_collects_modal_extraction_metrics() -> None:
    extractor = LogicExtractor(
        use_ipfs_accelerate=False,
        enable_formula_translation=False,
        enable_kg_integration=False,
        enable_rag_integration=False,
    )
    context = LogicExtractionContext(
        data="The agency must provide notice within 30 days.",
        data_type=DataType.TEXT,
        domain="legal",
        config={"extraction_mode": "modal", "modal_profile": "deontic:D"},
    )
    result = extractor.extract(context)

    score = LogicCritic(enable_prover_integration=False).evaluate(result)

    assert score.metrics["llm_call_count"] == 0
    assert score.metrics["deterministic_coverage_ratio"] == 1.0
    assert score.metrics["modal_family_accuracy"] == 1.0
    assert score.metrics["modal_system_accuracy"] == 1.0
    assert score.metrics["symbolic_validity"] == 1.0
