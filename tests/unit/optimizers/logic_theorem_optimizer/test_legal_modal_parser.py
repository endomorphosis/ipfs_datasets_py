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
_USCODE_25_422_HEADING_ONLY_TEXT = "Housing voucher benefits and utility allowances."
_USCODE_48_1572_HEADING_ONLY_TEXT = "Administrative notice and hearing."
_USCODE_42_6323_HEADING_ONLY_TEXT = "Notice and hearing requirements."


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


def test_parser_replays_dataset_zero_formula_cases_for_31a_2b_and_8906() -> None:
    parser = LegalModalParser()
    cases = [
        (
            "us-code-2-31a-2b-a99b26c5ad622cfe",
            "2 U.S.C. 31a-2b",
            _USCODE_2_31A_2B_TEXT,
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


def test_parser_replays_symbolic_validity_samples_for_16_6410_16_47a_and_7_614() -> None:
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
            "us-code-7-614-6e310cb5e196544b",
            "7 U.S.C. 614",
            _USCODE_7_614_SYMBOLIC_VALIDITY_TEXT,
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
