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
