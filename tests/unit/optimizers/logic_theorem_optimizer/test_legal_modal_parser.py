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
