"""Deterministic parser regressions for citation-bound U.S. Code edge cases."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import (  # noqa: E402
    LegalModalParser,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    ModalLogicFamily,
)


def _missing_modal_formula_count(result) -> int:
    return sum(
        1
        for ambiguity in result.ambiguities
        if ambiguity.ambiguity_type == "missing_modal_formula"
    )


def _has_adaptive_explicit_pair(
    result,
    *,
    predicted_family: str,
    target_family: str,
) -> bool:
    return any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.metadata.get("predicted_family") == predicted_family
        and ambiguity.metadata.get("target_family") == target_family
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        for ambiguity in result.ambiguities
    )


def _has_adaptive_explicit_pair_from_source(
    result,
    *,
    predicted_family: str,
    target_family: str,
    predicted_family_source: str,
) -> bool:
    return any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.metadata.get("predicted_family") == predicted_family
        and ambiguity.metadata.get("target_family") == target_family
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == predicted_family_source
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        for ambiguity in result.ambiguities
    )


def _adaptive_explicit_ambiguity_from_source(
    result,
    *,
    predicted_family: str,
    target_family: str,
    predicted_family_source: str,
):
    for ambiguity in result.ambiguities:
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        if ambiguity.metadata.get("adaptive_predicted_family_source") != predicted_family_source:
            continue
        if ambiguity.metadata.get("predicted_family") != predicted_family:
            continue
        if ambiguity.metadata.get("target_family") != target_family:
            continue
        return ambiguity
    return None
def _adaptive_ranking_with_shares(
    family_shares,
):
    ranking = []
    for index, (family, share_raw) in enumerate(
        sorted(
            family_shares.items(),
            key=lambda item: (-float(item[1]), str(item[0])),
        )
    ):
        ranking.append(
            {
                "family": str(family),
                "count": 0,
                "logit": round(2.0 - (index * 0.1), 6),
                "share_raw": float(share_raw),
                "share": round(float(share_raw), 6),
                "source": "logit_softmax_fallback",
            }
        )
    return ranking


def test_parser_recovers_article_prefixed_commission_heading() -> None:
    parser = LegalModalParser()

    modal_ir = parser.parse(
        "The Election Assistance Commission",
        document_id="us-code-2-121f-6dce78c9ec9c6d4b",
        citation="2 U.S.C. 121f",
    )

    assert len(modal_ir.formulas) == 1
    formula = modal_ir.formulas[0]
    assert formula.operator.family == ModalLogicFamily.FRAME.value
    assert formula.metadata.get("fallback_rule") == "uscode_heading_without_section_reference_v1"


def test_parser_recovers_terms_and_conditions_heading() -> None:
    parser = LegalModalParser()

    modal_ir = parser.parse(
        "The terms and conditions",
        document_id="us-code-16-820-e78ad24dbc049dea",
        citation="16 U.S.C. 820",
    )

    assert len(modal_ir.formulas) == 1
    formula = modal_ir.formulas[0]
    assert formula.operator.family == ModalLogicFamily.FRAME.value
    assert formula.metadata.get("fallback_rule") == "uscode_heading_without_section_reference_v1"


def test_parser_recovers_standalone_establishment_clause() -> None:
    parser = LegalModalParser()

    modal_ir = parser.parse(
        "There is established in the Department of Health and Human Services an office for policy coordination.",
        document_id="us-code-42-290aa-a8d1719e0c2a8388",
        citation="42 U.S.C. 290aa",
    )

    assert len(modal_ir.formulas) == 1
    formula = modal_ir.formulas[0]
    assert formula.operator.family == ModalLogicFamily.FRAME.value
    assert formula.metadata.get("fallback_rule") == "uscode_declarative_statement_v1"
    assert formula.metadata.get("statement_hint") == "establishment_clause"


def test_compiler_spacy_backend_no_longer_emits_missing_formula_for_regression_cases() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    cases = [
        (
            "us-code-2-121f-6dce78c9ec9c6d4b",
            "2 U.S.C. 121f",
            "The Election Assistance Commission",
        ),
        (
            "us-code-42-290aa-a8d1719e0c2a8388",
            "42 U.S.C. 290aa",
            "There is established in the Department of Health and Human Services an office for policy coordination.",
        ),
        (
            "us-code-16-820-e78ad24dbc049dea",
            "16 U.S.C. 820",
            "The terms and conditions",
        ),
    ]

    for document_id, citation, text in cases:
        result = compiler.compile(
            text,
            document_id=document_id,
            citation=citation,
        )
        assert result.modal_ir.formulas, document_id
        assert _missing_modal_formula_count(result) == 0, document_id


def test_parser_adds_residual_span_coverage_formula_for_untyped_uscode_segment() -> None:
    parser = LegalModalParser()
    modal_ir = parser.parse(
        (
            "The Secretary shall publish the annual report. "
            "Additional implementation details are provided for regional offices and contractors."
        ),
        document_id="us-code-25-640d-28-dd2e0dfae14b7385",
        citation="25 U.S.C. 640d-28",
    )

    residual_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    assert residual_formulas
    assert all(formula.operator.family == ModalLogicFamily.FRAME.value for formula in residual_formulas)
    assert all(formula.provenance.citation == "25 U.S.C. 640d-28" for formula in residual_formulas)


def test_compiler_spacy_backend_adds_residual_span_coverage_formula_for_untyped_uscode_segment() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )
    result = compiler.compile(
        (
            "The Secretary shall publish the annual report. "
            "Additional implementation details are provided for regional offices and contractors."
        ),
        document_id="us-code-25-640d-28-dd2e0dfae14b7385",
        citation="25 U.S.C. 640d-28",
    )

    residual_formulas = [
        formula
        for formula in result.modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]
    assert residual_formulas
    assert all(formula.operator.family == ModalLogicFamily.FRAME.value for formula in residual_formulas)
    assert all(formula.provenance.citation == "25 U.S.C. 640d-28" for formula in residual_formulas)


def test_parser_adds_residual_span_coverage_after_residual_fallback_formula() -> None:
    parser = LegalModalParser()
    modal_ir = parser.parse(
        (
            "The Secretary shall publish the annual report. "
            "Administrative notice and hearing procedures apply to petitions under this section. "
            "Additional implementation details are provided for regional offices and contractors."
        ),
        document_id="us-code-15-1431-ae0d9e64b8a5c0a7",
        citation="15 U.S.C. 1431",
    )

    procedural_fallbacks = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_procedural_clause_v1"
    ]
    residual_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]

    assert procedural_fallbacks
    assert residual_formulas
    assert modal_ir.formulas[-1].metadata.get("fallback_rule") == "uscode_procedural_clause_v1"


def test_compiler_spacy_backend_adds_residual_span_coverage_after_residual_fallback_formula() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )
    result = compiler.compile(
        (
            "The Secretary shall publish the annual report. "
            "Administrative notice and hearing procedures apply to petitions under this section. "
            "Additional implementation details are provided for regional offices and contractors."
        ),
        document_id="us-code-15-1431-ae0d9e64b8a5c0a7",
        citation="15 U.S.C. 1431",
    )

    procedural_fallbacks = [
        formula
        for formula in result.modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_procedural_clause_v1"
    ]
    residual_formulas = [
        formula
        for formula in result.modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]

    assert procedural_fallbacks
    assert residual_formulas
    assert result.modal_ir.formulas[-1].metadata.get("fallback_rule") == "uscode_procedural_clause_v1"


def test_parser_types_compact_uncovered_uscode_topic_headings_as_frame_spans() -> None:
    parser = LegalModalParser()
    modal_ir = parser.parse(
        (
            "The Secretary shall issue guidance. "
            "Congressional declaration of purpose. "
            "Authorization of appropriations. "
            "Notification and information sharing."
        ),
        document_id="us-code-42-300ff-compact-topic-headings",
        citation="42 U.S.C. 300ff",
    )

    residual_formulas = [
        formula
        for formula in modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]

    assert residual_formulas
    residual_text = " ".join(
        modal_ir.normalized_text[
            formula.provenance.start_char : formula.provenance.end_char
        ].lower()
        for formula in residual_formulas
    )
    frame_text = " ".join(
        modal_ir.normalized_text[
            formula.provenance.start_char : formula.provenance.end_char
        ].lower()
        for formula in modal_ir.formulas
        if formula.operator.family == ModalLogicFamily.FRAME.value
    )
    assert "congressional declaration of purpose" in frame_text
    assert "authorization of appropriations" in residual_text
    assert "notification and information sharing" in residual_text
    assert all(formula.operator.family == ModalLogicFamily.FRAME.value for formula in residual_formulas)


def test_compiler_spacy_backend_types_compact_uncovered_uscode_topic_headings_as_frame_spans() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )
    result = compiler.compile(
        (
            "The Secretary shall issue guidance. "
            "Congressional declaration of purpose. "
            "Authorization of appropriations. "
            "Notification and information sharing."
        ),
        document_id="us-code-42-300ff-compact-topic-headings",
        citation="42 U.S.C. 300ff",
    )

    residual_formulas = [
        formula
        for formula in result.modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_residual_span_coverage_v1"
    ]

    assert residual_formulas
    residual_text = " ".join(
        result.modal_ir.normalized_text[
            formula.provenance.start_char : formula.provenance.end_char
        ].lower()
        for formula in residual_formulas
    )
    frame_text = " ".join(
        result.modal_ir.normalized_text[
            formula.provenance.start_char : formula.provenance.end_char
        ].lower()
        for formula in result.modal_ir.formulas
        if formula.operator.family == ModalLogicFamily.FRAME.value
    )
    assert "congressional declaration of purpose" in frame_text
    assert "authorization of appropriations" in residual_text
    assert "notification and information sharing" in residual_text
    assert all(formula.operator.family == ModalLogicFamily.FRAME.value for formula in residual_formulas)


def test_compiler_spacy_backend_recovers_editorial_status_fallback_when_strict_fallback_is_cue_blocked() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )
    result = compiler.compile(
        (
            "U.S.C. Title 16 - CONSERVATION 16 U.S.C. United States Code, 2024 Edition "
            "Title 16 - CONSERVATION CHAPTER 1 - NATIONAL PARKS, MILITARY PARKS, MONUMENTS, "
            "AND SEASHORES SUBCHAPTER LXII - MISCELLANEOUS Sec. 452a - Repealed. Pub. L. 113-287, "
            "§7, Dec. 19, 2014, 128 Stat. 3272 From the U.S. Government Publishing Office, www.gpo.gov "
            "§452a. Repealed. Pub. L. 113–287, §7, Dec. 19, 2014, 128 Stat. 3272 Section, act Aug. 31, "
            "1954, ch. 1163, 68 Stat. 1037, related to acquisition of non-Federal land within existing "
            "boundaries of any National Park. See section 101102 of Title 54, National Park Service "
            "and Related Programs."
        ),
        document_id="us-code-16-452a-3794c1a091ab6acb",
        citation="16 U.S.C. 452a",
    )

    editorial_formulas = [
        formula
        for formula in result.modal_ir.formulas
        if formula.metadata.get("fallback_rule") == "uscode_editorial_status_heading_v1"
    ]
    assert editorial_formulas
    assert _missing_modal_formula_count(result) == 0
    assert all(formula.operator.family == ModalLogicFamily.FRAME.value for formula in editorial_formulas)
    assert all(formula.provenance.citation == "16 U.S.C. 452a" for formula in editorial_formulas)


def test_compiler_emits_explicit_frame_to_conditional_and_temporal_adaptive_pairs() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    conditional_result = compiler.compile(
        "As provided in section 3, this authority applies.",
        document_id="compiler-ambiguity-frame-conditional",
    )
    assert _has_adaptive_explicit_pair(
        conditional_result,
        predicted_family=ModalLogicFamily.FRAME.value,
        target_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    )

    temporal_result = compiler.compile(
        "For the period beginning on January 1, 2030, this authority applies.",
        document_id="compiler-ambiguity-frame-temporal",
    )
    assert _has_adaptive_explicit_pair(
        temporal_result,
        predicted_family=ModalLogicFamily.FRAME.value,
        target_family=ModalLogicFamily.TEMPORAL.value,
    )
    assert _has_adaptive_explicit_pair(
        temporal_result,
        predicted_family=ModalLogicFamily.TEMPORAL.value,
        target_family=ModalLogicFamily.DEONTIC.value,
    )
    assert _has_adaptive_explicit_pair(
        conditional_result,
        predicted_family=ModalLogicFamily.FRAME.value,
        target_family=ModalLogicFamily.EPISTEMIC.value,
    )


def test_compiler_emits_explicit_frame_to_alethic_adaptive_pair_from_low_margin_logits() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.FRAME.value,
                "count": 0,
                "logit": 1.3,
                "share_raw": 0.54,
                "share": 0.54,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.ALETHIC.value,
                "count": 0,
                "logit": 1.1,
                "share_raw": 0.46,
                "share": 0.46,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "As provided in section 3, this authority applies.",
        document_id="compiler-ambiguity-frame-alethic-logits",
    )

    assert _has_adaptive_explicit_pair_from_source(
        result,
        predicted_family=ModalLogicFamily.FRAME.value,
        target_family=ModalLogicFamily.ALETHIC.value,
        predicted_family_source="adaptive_logits",
    )


def test_compiler_emits_explicit_deontic_to_frame_and_temporal_adaptive_pairs() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    frame_result = compiler.compile(
        "The agency shall administer this program under section 3 of this title.",
        document_id="compiler-ambiguity-deontic-frame",
    )
    assert _has_adaptive_explicit_pair(
        frame_result,
        predicted_family=ModalLogicFamily.DEONTIC.value,
        target_family=ModalLogicFamily.FRAME.value,
    )

    temporal_result = compiler.compile(
        "The Secretary shall submit the report by June 1, 2030.",
        document_id="compiler-ambiguity-deontic-temporal",
    )
    assert _has_adaptive_explicit_pair(
        temporal_result,
        predicted_family=ModalLogicFamily.DEONTIC.value,
        target_family=ModalLogicFamily.TEMPORAL.value,
    )
    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("predicted_family") == ModalLogicFamily.DEONTIC.value
        and ambiguity.metadata.get("target_family") == ModalLogicFamily.TEMPORAL.value
        and ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        and ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        for ambiguity in temporal_result.ambiguities
    )


def test_compiler_emits_explicit_deontic_to_conditional_normative_adaptive_pair() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        "The Secretary shall submit the report when the committee approves.",
        document_id="compiler-ambiguity-deontic-conditional",
    )
    assert _has_adaptive_explicit_pair(
        result,
        predicted_family=ModalLogicFamily.DEONTIC.value,
        target_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    )


def test_compiler_emits_explicit_temporal_to_deontic_adaptive_pair() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        "Within 30 days after June 1, 2030, and before the end of the fiscal year, the Secretary may issue guidance.",
        document_id="compiler-ambiguity-temporal-deontic",
    )
    assert _has_adaptive_explicit_pair(
        result,
        predicted_family=ModalLogicFamily.TEMPORAL.value,
        target_family=ModalLogicFamily.DEONTIC.value,
    )


def test_compiler_preserves_temporal_to_deontic_adaptive_logits_evidence_margins() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )
    evidence_cases = (
        (
            "us-code-33-2607-b8ef0bc32f81c11c",
            -0.405328772342,
            0.555328772342,
        ),
        (
            "us-code-42-14713-to-14715-589d92b207fe177e",
            -0.386346721929,
            0.536346721929,
        ),
    )

    for document_id, expected_margin, expected_priority in evidence_cases:
        predicted_share = 0.70
        target_share = predicted_share + expected_margin

        def _mock_adaptive_family_ranking_from_logits(_encoding):
            return [
                {
                    "family": ModalLogicFamily.TEMPORAL.value,
                    "count": 0,
                    "logit": 1.3,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                    "source": "logit_softmax_fallback",
                },
                {
                    "family": ModalLogicFamily.DEONTIC.value,
                    "count": 0,
                    "logit": 0.9,
                    "share_raw": target_share,
                    "share": target_share,
                    "source": "logit_softmax_fallback",
                },
            ]

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            (
                "Within 30 days after June 1, 2030, and before the end of the "
                "fiscal year, annual publication occurs."
            ),
            document_id=f"compiler-ambiguity-temporal-deontic-{document_id}",
        )
        matches = [
            ambiguity
            for ambiguity in result.ambiguities
            if ambiguity.ambiguity_type == "adaptive_temporal_deontic_outvoted_margin_low"
            and ambiguity.metadata.get("adaptive_predicted_family_source")
            == "adaptive_logits"
        ]
        assert matches, document_id
        ambiguity = matches[0]
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("predicted_family") == ModalLogicFamily.TEMPORAL.value
        assert ambiguity.metadata.get("target_family") == ModalLogicFamily.DEONTIC.value
        assert abs(float(ambiguity.metadata["family_margin_raw"]) - expected_margin) <= 1e-12
        assert abs(float(ambiguity.metadata["priority"]) - expected_priority) <= 1e-12
        assert abs(float(ambiguity.metadata["adaptive_priority"]) - expected_priority) <= 1e-12


def test_compiler_marks_temporal_to_alethic_pair_as_compiler_ambiguity_bundle_from_adaptive_logits() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )
    expected_margin = -0.087783806913
    expected_priority = 0.237783806913
    predicted_share = 0.6
    target_share = predicted_share + expected_margin

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.TEMPORAL.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": predicted_share,
                "share": predicted_share,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.ALETHIC.value,
                "count": 0,
                "logit": 1.1,
                "share_raw": target_share,
                "share": target_share,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "Within 30 days after June 1, 2030, annual publication occurs.",
        document_id="compiler-ambiguity-temporal-alethic-policy",
    )
    matches = [
        ambiguity
        for ambiguity in result.ambiguities
        if ambiguity.ambiguity_type == "adaptive_temporal_alethic_outvoted_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "adaptive_logits"
    ]
    assert matches
    ambiguity = matches[0]
    assert ambiguity.severity == "requires_rule"
    assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
    assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
    assert ambiguity.metadata.get("predicted_family") == ModalLogicFamily.TEMPORAL.value
    assert ambiguity.metadata.get("target_family") == ModalLogicFamily.ALETHIC.value
    assert abs(float(ambiguity.metadata["family_margin_raw"]) - expected_margin) <= 1e-12
    assert abs(float(ambiguity.metadata["priority"]) - expected_priority) <= 1e-12
    assert abs(float(ambiguity.metadata["adaptive_priority"]) - expected_priority) <= 1e-12


def test_compiler_marks_frame_to_deontic_pair_as_compiler_ambiguity_bundle_from_adaptive_logits_evidence_margins() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )
    expected_margin = -0.424665787791
    expected_priority = 0.574665787791
    ranking = _adaptive_ranking_with_shares(
        {
            ModalLogicFamily.FRAME.value: 0.6,
            ModalLogicFamily.DEONTIC.value: 0.175334212209,
            ModalLogicFamily.TEMPORAL.value: 0.12,
            ModalLogicFamily.EPISTEMIC.value: 0.104665787791,
        }
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return list(ranking)

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "As provided in section 5, this authority applies.",
        document_id="compiler-ambiguity-frame-deontic-evidence",
    )

    ambiguity = _adaptive_explicit_ambiguity_from_source(
        result,
        predicted_family=ModalLogicFamily.FRAME.value,
        target_family=ModalLogicFamily.DEONTIC.value,
        predicted_family_source="adaptive_logits",
    )
    assert ambiguity is not None
    assert ambiguity.ambiguity_type == "adaptive_frame_deontic_outvoted_margin_low"
    assert ambiguity.severity == "requires_rule"
    assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
    assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
    assert (
        abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - expected_margin)
        <= 1e-12
    )
    assert (
        abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
        <= 1e-12
    )
    assert (
        abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - expected_priority)
        <= 1e-12
    )


def test_compiler_preserves_packet_002937_compiler_ambiguity_policy_pair_margins(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )
    cases = (
        {
            "sample_id": "us-code-42-9167.-1ffd68617594a74f",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.896586131543,
            "priority": 1.046586131543,
        },
        {
            "sample_id": "us-code-42-7232.-2f3932bfd46b43d0",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.677392318488,
            "priority": 0.827392318488,
        },
        {
            "sample_id": "us-code-22-1760a-733a6b447d5166f8",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.068004744728,
            "priority": 0.218004744728,
        },
    )

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        expected_margin = float(case["family_margin"])
        expected_priority = float(case["priority"])
        predicted_share = abs(expected_margin) + 0.2
        target_share = predicted_share + expected_margin
        ranking = _adaptive_ranking_with_shares(
            {
                predicted_family: predicted_share,
                target_family: target_share,
                ModalLogicFamily.EPISTEMIC.value: 0.05,
            }
        )

        def _mock_adaptive_family_ranking_from_logits(_encoding, _ranking=ranking):
            return list(_ranking)

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            "As provided in section 3, the Secretary shall act.",
            document_id=f"compiler-ambiguity-packet-002937-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits",
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - expected_margin)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - expected_priority)
            <= 1e-12
        )


def test_compiler_preserves_compiler_ambiguity_bundle_evidence_for_target_policy_pairs() -> None:
    cases = (
        {
            "document_id": "compiler-ambiguity-frame-deontic-evidence",
            "text": "As provided in section 5, this authority applies.",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "expected_margin": -0.424665787791,
            "expected_priority": 0.574665787791,
            "shares": {
                ModalLogicFamily.FRAME.value: 0.6,
                ModalLogicFamily.DEONTIC.value: 0.175334212209,
                ModalLogicFamily.TEMPORAL.value: 0.12,
                ModalLogicFamily.EPISTEMIC.value: 0.104665787791,
            },
        },
        {
            "document_id": "compiler-ambiguity-temporal-epistemic-evidence",
            "text": "Within 30 days after June 1, 2030, annual publication occurs.",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.EPISTEMIC.value,
            "expected_type": "adaptive_temporal_epistemic_outvoted_margin_low",
            "expected_margin": -0.469232881675,
            "expected_priority": 0.619232881675,
            "shares": {
                ModalLogicFamily.TEMPORAL.value: 0.62,
                ModalLogicFamily.EPISTEMIC.value: 0.150767118325,
                ModalLogicFamily.DEONTIC.value: 0.12,
                ModalLogicFamily.FRAME.value: 0.109232881675,
            },
        },
        {
            "document_id": "compiler-ambiguity-deontic-self-evidence",
            "text": "The Secretary shall issue guidance.",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "expected_margin": 0.126749475428,
            "expected_priority": 0.023250524572,
            "shares": {
                ModalLogicFamily.DEONTIC.value: 0.526749475428,
                ModalLogicFamily.TEMPORAL.value: 0.4,
                ModalLogicFamily.FRAME.value: 0.04,
                ModalLogicFamily.EPISTEMIC.value: 0.033250524572,
            },
        },
    )

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        ranking = _adaptive_ranking_with_shares(case["shares"])

        def _mock_adaptive_family_ranking_from_logits(_encoding, _ranking=ranking):
            return list(_ranking)

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            str(case["text"]),
            document_id=f"compiler-ambiguity-bundle-{case['document_id']}",
        )

        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=str(case["predicted_family"]),
            target_family=str(case["target_family"]),
            predicted_family_source="adaptive_logits",
        )
        assert ambiguity is not None, case["document_id"]
        assert ambiguity.ambiguity_type == str(case["expected_type"])
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert (
            abs(
                float(ambiguity.metadata.get("family_margin_raw", 0.0))
                - float(case["expected_margin"])
            )
            <= 1e-12
        )
        assert (
            abs(
                float(ambiguity.metadata.get("priority", 0.0))
                - float(case["expected_priority"])
            )
            <= 1e-12
        )
        assert (
            abs(
                float(ambiguity.metadata.get("adaptive_priority", 0.0))
                - float(case["expected_priority"])
            )
            <= 1e-12
        )


def test_compiler_preserves_packet_001186_compiler_ambiguity_policy_pair_margins() -> None:
    cases = (
        {
            "sample_id": "us-code-45-1110.-78b953ff4e2ad0b5",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": 0.131176293653,
            "priority": 0.018823706347,
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
        },
        {
            "sample_id": "us-code-48-1508.-5bb17b9ac0c6cc29",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.015538233588,
            "priority": 0.165538233588,
        },
        {
            "sample_id": "us-code-12-1715i-12755f90d17b6de9",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.417640674808,
            "priority": 0.567640674808,
        },
        {
            "sample_id": "us-code-25-1300j-3-e61050557327b3ac",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.826182368661,
            "priority": 0.976182368661,
        },
        {
            "sample_id": "us-code-44-1720.-0fa4e1c8e80d950e",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.780481397627,
            "priority": 0.930481397627,
        },
    )

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        expected_margin = float(case["family_margin"])
        expected_priority = float(case["priority"])

        if predicted_family == target_family:
            predicted_share = (1.0 + expected_margin) / 2.0
            runner_up_family = str(
                case.get("runner_up_family", ModalLogicFamily.DEONTIC.value)
            )
            runner_up_share = predicted_share - expected_margin
            ranking = _adaptive_ranking_with_shares(
                {
                    predicted_family: predicted_share,
                    runner_up_family: runner_up_share,
                    ModalLogicFamily.EPISTEMIC.value: 0.03,
                }
            )
        else:
            predicted_share = abs(expected_margin) + 0.2
            target_share = predicted_share + expected_margin
            ranking = _adaptive_ranking_with_shares(
                {
                    predicted_family: predicted_share,
                    target_family: target_share,
                    ModalLogicFamily.EPISTEMIC.value: 0.03,
                }
            )

        def _mock_adaptive_family_ranking_from_logits(_encoding, _ranking=ranking):
            return list(_ranking)

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            "As provided in section 3, the Secretary shall act by June 1, 2030.",
            document_id=f"compiler-ambiguity-packet-001186-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits",
        )
        assert ambiguity is not None, case["sample_id"]
        expected_direction = "contested" if expected_margin > 0.0 else "outvoted"
        assert ambiguity.ambiguity_type == (
            f"adaptive_{predicted_family}_{target_family}_{expected_direction}_margin_low"
        )
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - expected_margin)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - expected_priority)
            <= 1e-12
        )


def test_compiler_emits_explicit_temporal_to_epistemic_adaptive_pair_from_low_margin_logits() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.TEMPORAL.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.53,
                "share": 0.53,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.EPISTEMIC.value,
                "count": 0,
                "logit": 1.0,
                "share_raw": 0.47,
                "share": 0.47,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "Within 30 days after June 1, 2030, annual publication occurs.",
        document_id="compiler-ambiguity-temporal-epistemic-logits",
    )

    assert _has_adaptive_explicit_pair_from_source(
        result,
        predicted_family=ModalLogicFamily.TEMPORAL.value,
        target_family=ModalLogicFamily.EPISTEMIC.value,
        predicted_family_source="adaptive_logits",
    )


def test_compiler_emits_explicit_temporal_to_doxastic_adaptive_pair_from_low_margin_logits() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.TEMPORAL.value,
                "count": 0,
                "logit": 1.3,
                "share_raw": 0.56,
                "share": 0.56,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DOXASTIC.value,
                "count": 0,
                "logit": 1.05,
                "share_raw": 0.44,
                "share": 0.44,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "Within 30 days after June 1, 2030, annual publication occurs.",
        document_id="compiler-ambiguity-temporal-doxastic-logits",
    )

    assert _has_adaptive_explicit_pair_from_source(
        result,
        predicted_family=ModalLogicFamily.TEMPORAL.value,
        target_family=ModalLogicFamily.DOXASTIC.value,
        predicted_family_source="adaptive_logits",
    )


def test_compiler_emits_explicit_conditional_normative_to_frame_adaptive_pair() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        "In the event that the authority under section 5 applies, the Administrator acts.",
        document_id="compiler-ambiguity-conditional-frame",
    )
    assert _has_adaptive_explicit_pair(
        result,
        predicted_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        target_family=ModalLogicFamily.FRAME.value,
    )
    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.CONDITIONAL_NORMATIVE.value
        and ambiguity.metadata.get("target_family") == ModalLogicFamily.FRAME.value
        and ambiguity.metadata.get("is_priority_policy_pair") is True
        for ambiguity in result.ambiguities
    )


def test_compiler_emits_explicit_conditional_normative_to_epistemic_adaptive_pair() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        "In the event that the Secretary determines eligibility, this authority applies.",
        document_id="compiler-ambiguity-conditional-epistemic",
    )
    assert _has_adaptive_explicit_pair(
        result,
        predicted_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        target_family=ModalLogicFamily.EPISTEMIC.value,
    )


def test_compiler_emits_explicit_conditional_normative_to_deontic_adaptive_pair() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        "In the event that this authority applies, the Secretary shall act.",
        document_id="compiler-ambiguity-conditional-deontic",
    )
    assert _has_adaptive_explicit_pair(
        result,
        predicted_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        target_family=ModalLogicFamily.DEONTIC.value,
    )


def test_compiler_emits_explicit_conditional_normative_to_temporal_adaptive_pair() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        "In the event that this authority applies, the Administrator acts.",
        document_id="compiler-ambiguity-conditional-temporal",
    )
    assert _has_adaptive_explicit_pair(
        result,
        predicted_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        target_family=ModalLogicFamily.TEMPORAL.value,
    )


def test_compiler_emits_explicit_conditional_normative_to_dynamic_adaptive_pair() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.53,
                "share": 0.53,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DYNAMIC.value,
                "count": 0,
                "logit": 1.1,
                "share_raw": 0.47,
                "share": 0.47,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "In the event that this authority applies, publication follows.",
        document_id="compiler-ambiguity-conditional-dynamic",
    )
    assert _has_adaptive_explicit_pair(
        result,
        predicted_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        target_family=ModalLogicFamily.DYNAMIC.value,
    )
    assert any(
        ambiguity.metadata.get("adaptive_predicted_family_source") == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.CONDITIONAL_NORMATIVE.value
        and ambiguity.metadata.get("target_family") == ModalLogicFamily.DYNAMIC.value
        for ambiguity in result.ambiguities
        if ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
    )


def test_compiler_emits_explicit_deontic_to_dynamic_adaptive_pair() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        "The Secretary shall file the notice upon service.",
        document_id="compiler-ambiguity-deontic-dynamic",
    )
    assert _has_adaptive_explicit_pair(
        result,
        predicted_family=ModalLogicFamily.DEONTIC.value,
        target_family=ModalLogicFamily.DYNAMIC.value,
    )
    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("predicted_family") == ModalLogicFamily.DEONTIC.value
        and ambiguity.metadata.get("target_family") == ModalLogicFamily.DYNAMIC.value
        and ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        and ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        for ambiguity in result.ambiguities
    )


def test_compiler_emits_explicit_pair_from_adaptive_logits_disagreement() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.25,
                "share_raw": 0.56,
                "share": 0.56,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DYNAMIC.value,
                "count": 0,
                "logit": 1.05,
                "share_raw": 0.44,
                "share": 0.44,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "As provided in section 3, this authority applies.",
        document_id="compiler-ambiguity-adaptive-logits-disagreement",
    )

    assert _has_adaptive_explicit_pair(
        result,
        predicted_family=ModalLogicFamily.DEONTIC.value,
        target_family=ModalLogicFamily.DYNAMIC.value,
    )
    assert any(
        ambiguity.metadata.get("adaptive_predicted_family_source") == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family") == ModalLogicFamily.DEONTIC.value
        and ambiguity.metadata.get("target_family") == ModalLogicFamily.DYNAMIC.value
        for ambiguity in result.ambiguities
        if ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
    )


def test_compiler_preserves_frame_to_conditional_and_deontic_pairs_from_compiled_primary_policy() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.TEMPORAL.value,
                "count": 0,
                "logit": 1.6,
                "share_raw": 0.38,
                "share": 0.38,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.4,
                "share_raw": 0.36,
                "share": 0.36,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
                "count": 0,
                "logit": 1.35,
                "share_raw": 0.35,
                "share": 0.35,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.FRAME.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.30,
                "share": 0.30,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "As provided in section 3, this authority applies.",
        document_id="compiler-ambiguity-frame-compiled-primary-policy",
    )

    assert _has_adaptive_explicit_pair_from_source(
        result,
        predicted_family=ModalLogicFamily.FRAME.value,
        target_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        predicted_family_source="compiled_primary_family",
    )
    assert _has_adaptive_explicit_pair_from_source(
        result,
        predicted_family=ModalLogicFamily.FRAME.value,
        target_family=ModalLogicFamily.DEONTIC.value,
        predicted_family_source="compiled_primary_family",
    )
    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "compiled_primary_family"
        and ambiguity.metadata.get("predicted_family") == ModalLogicFamily.FRAME.value
        and ambiguity.metadata.get("target_family") == ModalLogicFamily.DEONTIC.value
        and ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        and ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        for ambiguity in result.ambiguities
    )


def test_compiler_preserves_temporal_to_deontic_pair_from_compiled_primary_policy() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.FRAME.value,
                "count": 0,
                "logit": 1.7,
                "share_raw": 0.44,
                "share": 0.44,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.5,
                "share_raw": 0.32,
                "share": 0.32,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.TEMPORAL.value,
                "count": 0,
                "logit": 1.4,
                "share_raw": 0.24,
                "share": 0.24,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "Within 30 days after review, annual publication occurs.",
        document_id="compiler-ambiguity-temporal-compiled-primary-policy",
    )

    assert _has_adaptive_explicit_pair_from_source(
        result,
        predicted_family=ModalLogicFamily.TEMPORAL.value,
        target_family=ModalLogicFamily.DEONTIC.value,
        predicted_family_source="compiled_primary_family",
    )


def test_compiler_preserves_temporal_to_frame_pair_from_compiled_primary_policy() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.7,
                "share_raw": 0.44,
                "share": 0.44,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.FRAME.value,
                "count": 0,
                "logit": 1.5,
                "share_raw": 0.32,
                "share": 0.32,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.TEMPORAL.value,
                "count": 0,
                "logit": 1.4,
                "share_raw": 0.24,
                "share": 0.24,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "Within 30 days after review, annual publication occurs.",
        document_id="compiler-ambiguity-temporal-frame-compiled-primary-policy",
    )

    assert _has_adaptive_explicit_pair_from_source(
        result,
        predicted_family=ModalLogicFamily.TEMPORAL.value,
        target_family=ModalLogicFamily.FRAME.value,
        predicted_family_source="compiled_primary_family",
    )


def test_compiler_preserves_conditional_to_deontic_pair_from_compiled_primary_policy() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.FRAME.value,
                "count": 0,
                "logit": 1.65,
                "share_raw": 0.45,
                "share": 0.45,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.45,
                "share_raw": 0.31,
                "share": 0.31,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
                "count": 0,
                "logit": 1.35,
                "share_raw": 0.24,
                "share": 0.24,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "In the event that the authority applies, publication follows.",
        document_id="compiler-ambiguity-conditional-compiled-primary-policy",
    )

    assert _has_adaptive_explicit_pair_from_source(
        result,
        predicted_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        target_family=ModalLogicFamily.DEONTIC.value,
        predicted_family_source="compiled_primary_family",
    )


def test_compiler_preserves_conditional_to_temporal_pair_from_compiled_primary_policy() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.FRAME.value,
                "count": 0,
                "logit": 1.65,
                "share_raw": 0.45,
                "share": 0.45,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.TEMPORAL.value,
                "count": 0,
                "logit": 1.55,
                "share_raw": 0.35,
                "share": 0.35,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.45,
                "share_raw": 0.31,
                "share": 0.31,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
                "count": 0,
                "logit": 1.35,
                "share_raw": 0.24,
                "share": 0.24,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "In the event that the authority applies, publication follows.",
        document_id="compiler-ambiguity-conditional-temporal-compiled-primary-policy",
    )

    assert _has_adaptive_explicit_pair_from_source(
        result,
        predicted_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        target_family=ModalLogicFamily.TEMPORAL.value,
        predicted_family_source="compiled_primary_family",
    )


def test_compiler_preserves_conditional_to_dynamic_pair_from_compiled_primary_policy() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.FRAME.value,
                "count": 0,
                "logit": 1.65,
                "share_raw": 0.45,
                "share": 0.45,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.TEMPORAL.value,
                "count": 0,
                "logit": 1.55,
                "share_raw": 0.35,
                "share": 0.35,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.45,
                "share_raw": 0.31,
                "share": 0.31,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
                "count": 0,
                "logit": 1.35,
                "share_raw": 0.24,
                "share": 0.24,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DYNAMIC.value,
                "count": 0,
                "logit": 1.30,
                "share_raw": 0.18,
                "share": 0.18,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "In the event that the authority applies, publication follows.",
        document_id="compiler-ambiguity-conditional-dynamic-compiled-primary-policy",
    )

    assert _has_adaptive_explicit_pair_from_source(
        result,
        predicted_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        target_family=ModalLogicFamily.DYNAMIC.value,
        predicted_family_source="compiled_primary_family",
    )


def test_compiler_preserves_compiled_primary_outvote_margins_for_frame_and_temporal_policy_pairs() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    frame_share = 0.30
    frame_to_deontic_margin = -0.424665787791
    temporal_share = 0.40
    temporal_to_deontic_margin = -0.526475969873
    temporal_to_conditional_margin = -0.323598375724
    temporal_to_frame_margin = -0.306628581084

    def _mock_frame_compiled_primary_ranking(_encoding):
        return [
            {
                "family": ModalLogicFamily.ALETHIC.value,
                "count": 0,
                "logit": 1.8,
                "share_raw": 0.97,
                "share": 0.97,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.FRAME.value,
                "count": 0,
                "logit": 1.6,
                "share_raw": frame_share,
                "share": frame_share,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.3,
                "share_raw": frame_share - frame_to_deontic_margin,
                "share": frame_share - frame_to_deontic_margin,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_frame_compiled_primary_ranking  # type: ignore[method-assign]

    frame_result = compiler.compile(
        "As provided in section 3, this authority applies.",
        document_id="compiler-ambiguity-frame-compiled-primary-evidence-margins",
    )
    frame_ambiguity = _adaptive_explicit_ambiguity_from_source(
        frame_result,
        predicted_family=ModalLogicFamily.FRAME.value,
        target_family=ModalLogicFamily.DEONTIC.value,
        predicted_family_source="compiled_primary_family",
    )
    assert frame_ambiguity is not None
    assert frame_ambiguity.ambiguity_type == "adaptive_frame_deontic_outvoted_margin_low"
    assert frame_ambiguity.severity == "requires_rule"
    assert abs(float(frame_ambiguity.metadata["family_margin_raw"]) - frame_to_deontic_margin) <= 1e-12
    assert abs(float(frame_ambiguity.metadata["priority"]) - 0.574665787791) <= 1e-12
    assert frame_ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
    assert frame_ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"

    def _mock_temporal_compiled_primary_ranking(_encoding):
        return [
            {
                "family": ModalLogicFamily.ALETHIC.value,
                "count": 0,
                "logit": 1.8,
                "share_raw": 0.97,
                "share": 0.97,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.TEMPORAL.value,
                "count": 0,
                "logit": 1.7,
                "share_raw": temporal_share,
                "share": temporal_share,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.3,
                "share_raw": temporal_share - temporal_to_deontic_margin,
                "share": temporal_share - temporal_to_deontic_margin,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": temporal_share - temporal_to_conditional_margin,
                "share": temporal_share - temporal_to_conditional_margin,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.FRAME.value,
                "count": 0,
                "logit": 1.1,
                "share_raw": temporal_share - temporal_to_frame_margin,
                "share": temporal_share - temporal_to_frame_margin,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_temporal_compiled_primary_ranking  # type: ignore[method-assign]

    temporal_result = compiler.compile(
        "Within 30 days after review, annual publication occurs.",
        document_id="compiler-ambiguity-temporal-compiled-primary-evidence-margins",
    )
    temporal_cases = (
        (
            ModalLogicFamily.DEONTIC.value,
            temporal_to_deontic_margin,
            0.676475969873,
            "adaptive_temporal_deontic_outvoted_margin_low",
        ),
        (
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            temporal_to_conditional_margin,
            0.473598375724,
            "adaptive_temporal_conditional_normative_outvoted_margin_low",
        ),
        (
            ModalLogicFamily.FRAME.value,
            temporal_to_frame_margin,
            0.456628581084,
            "adaptive_temporal_frame_outvoted_margin_low",
        ),
    )
    for target_family, expected_margin, expected_priority, expected_type in temporal_cases:
        temporal_ambiguity = _adaptive_explicit_ambiguity_from_source(
            temporal_result,
            predicted_family=ModalLogicFamily.TEMPORAL.value,
            target_family=target_family,
            predicted_family_source="compiled_primary_family",
        )
        assert temporal_ambiguity is not None, target_family
        assert temporal_ambiguity.ambiguity_type == expected_type
        assert temporal_ambiguity.severity == "requires_rule"
        assert abs(float(temporal_ambiguity.metadata["family_margin_raw"]) - expected_margin) <= 1e-12
        assert abs(float(temporal_ambiguity.metadata["priority"]) - expected_priority) <= 1e-12
        assert temporal_ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert temporal_ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"


def test_compiler_preserves_frame_self_pair_margin_priority_from_adaptive_logits_evidence() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )
    expected_margin = 0.067291518423
    expected_priority = 0.082708481577

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.FRAME.value,
                "count": 0,
                "logit": 1.5,
                "share_raw": 0.567291518423,
                "share": 0.567291518423,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.4,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "As provided in section 3, this authority applies.",
        document_id="compiler-ambiguity-frame-self-evidence-margin",
    )
    ambiguity = _adaptive_explicit_ambiguity_from_source(
        result,
        predicted_family=ModalLogicFamily.FRAME.value,
        target_family=ModalLogicFamily.FRAME.value,
        predicted_family_source="adaptive_logits",
    )
    assert ambiguity is not None
    assert ambiguity.ambiguity_type == "adaptive_frame_frame_contested_margin_low"
    assert ambiguity.severity == "review"
    assert abs(float(ambiguity.metadata["family_margin_raw"]) - expected_margin) <= 1e-12
    assert abs(float(ambiguity.metadata["priority"]) - expected_priority) <= 1e-12
    assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
    assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"


def test_compiler_emits_explicit_alethic_to_epistemic_adaptive_pair() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        "It is necessary that the Secretary act.",
        document_id="compiler-ambiguity-alethic-epistemic",
    )
    assert _has_adaptive_explicit_pair(
        result,
        predicted_family=ModalLogicFamily.ALETHIC.value,
        target_family=ModalLogicFamily.EPISTEMIC.value,
    )


def test_compiler_marks_alethic_to_deontic_pair_as_compiler_ambiguity_bundle_from_adaptive_logits() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.ALETHIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "It is necessary that the Secretary shall act.",
        document_id="compiler-ambiguity-alethic-deontic-policy",
    )

    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.ALETHIC.value
        and ambiguity.metadata.get("target_family")
        == ModalLogicFamily.DEONTIC.value
        and ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        and ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        for ambiguity in result.ambiguities
    )


def test_compiler_marks_alethic_to_epistemic_pair_as_compiler_ambiguity_bundle_from_adaptive_logits() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.ALETHIC.value,
                "count": 0,
                "logit": 1.35,
                "share_raw": 0.91,
                "share": 0.91,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.EPISTEMIC.value,
                "count": 0,
                "logit": 0.35,
                "share_raw": 0.09,
                "share": 0.09,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "It is necessary that the Secretary act.",
        document_id="compiler-ambiguity-alethic-epistemic-policy",
    )

    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.ALETHIC.value
        and ambiguity.metadata.get("target_family")
        == ModalLogicFamily.EPISTEMIC.value
        and ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        and ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        for ambiguity in result.ambiguities
    )


def test_compiler_emits_explicit_deontic_self_pair_for_low_family_margin() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        "The Secretary shall submit the report by June 1, 2030.",
        document_id="compiler-ambiguity-deontic-self",
    )
    assert _has_adaptive_explicit_pair(
        result,
        predicted_family=ModalLogicFamily.DEONTIC.value,
        target_family=ModalLogicFamily.DEONTIC.value,
    )


def test_compiler_marks_dynamic_self_pair_as_compiler_required_policy() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.DYNAMIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "The Secretary shall file the notice upon service.",
        document_id="compiler-ambiguity-dynamic-self-policy",
    )

    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.DYNAMIC.value
        and ambiguity.metadata.get("target_family")
        == ModalLogicFamily.DYNAMIC.value
        and ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        for ambiguity in result.ambiguities
    )


def test_compiler_marks_temporal_self_pair_as_compiler_ambiguity_bundle_from_adaptive_logits() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.TEMPORAL.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "Within 30 days after June 1, 2030, annual publication occurs.",
        document_id="compiler-ambiguity-temporal-self-policy",
    )

    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.TEMPORAL.value
        and ambiguity.metadata.get("target_family")
        == ModalLogicFamily.TEMPORAL.value
        and ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        and ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        for ambiguity in result.ambiguities
    )


def test_compiler_emits_compiler_ambiguity_pairs_for_evidence_family_margins() -> None:
    cases = [
        {
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "predicted_share": 0.644659040534,
            "runner_up_share": 0.355340959466,
            "expected_margin": -0.289318081068,
            "expected_priority": 0.439318081068,
            "expected_severity": "requires_rule",
            "expected_type": "adaptive_temporal_conditional_normative_outvoted_margin_low",
        },
        {
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "predicted_share": 0.70819068546,
            "runner_up_share": 0.29180931454,
            "expected_margin": -0.41638137092,
            "expected_priority": 0.56638137092,
            "expected_severity": "requires_rule",
            "expected_type": "adaptive_frame_conditional_normative_outvoted_margin_low",
        },
        {
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "predicted_share": 0.541751294331,
            "runner_up_share": 0.458248705669,
            "expected_margin": 0.083502588662,
            "expected_priority": 0.066497411338,
            "expected_severity": "review",
            "expected_type": "adaptive_temporal_temporal_contested_margin_low",
        },
        {
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "predicted_share": 0.565750328631,
            "runner_up_share": 0.434249671369,
            "expected_margin": 0.131500657262,
            "expected_priority": 0.018499342738,
            "expected_severity": "review",
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
        },
    ]

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        predicted_share = float(case["predicted_share"])
        runner_up_share = float(case["runner_up_share"])
        second_family = (
            target_family
            if target_family != predicted_family
            else ModalLogicFamily.DEONTIC.value
        )
        if second_family == predicted_family:
            second_family = ModalLogicFamily.FRAME.value

        def _mock_adaptive_family_ranking_from_logits(
            _encoding,
            *,
            predicted_family: str = predicted_family,
            second_family: str = second_family,
            predicted_share: float = predicted_share,
            runner_up_share: float = runner_up_share,
        ):
            return [
                {
                    "family": predicted_family,
                    "count": 0,
                    "logit": 1.2,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                    "source": "logit_softmax_fallback",
                },
                {
                    "family": second_family,
                    "count": 0,
                    "logit": 0.8,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                    "source": "logit_softmax_fallback",
                },
            ]

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            "As provided in section 3, the Secretary shall act by June 1, 2030.",
            document_id=(
                f"compiler-ambiguity-evidence-{predicted_family}-{target_family}"
            ),
        )

        matching_ambiguities = [
            ambiguity
            for ambiguity in result.ambiguities
            if ambiguity.ambiguity_type.startswith("adaptive_")
            and ambiguity.ambiguity_type != "adaptive_family_margin_low"
            and ambiguity.metadata.get("adaptive_predicted_family_source")
            == "adaptive_logits"
            and ambiguity.metadata.get("predicted_family") == predicted_family
            and ambiguity.metadata.get("target_family") == target_family
        ]
        assert matching_ambiguities, (
            predicted_family,
            target_family,
            [ambiguity.to_dict() for ambiguity in result.ambiguities],
        )
        ambiguity = matching_ambiguities[0]
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.severity == case["expected_severity"]
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert (
            abs(
                float(ambiguity.metadata.get("family_margin_raw", 0.0))
                - float(case["expected_margin"])
            )
            <= 1e-12
        )
        assert (
            abs(
                float(ambiguity.metadata.get("priority", 0.0))
                - float(case["expected_priority"])
            )
            <= 1e-12
        )


def test_compiler_preserves_compiler_ambiguity_policy_for_packet_003596_evidence_margins() -> None:
    cases = [
        {
            "sample_id": "us-code-2-179s-c5e01db705c7c4c6",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "expected_margin": -0.519813142775,
            "expected_priority": 0.669813142775,
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-25-1300h-8-fbcddc1d397c98ea",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "expected_margin": -0.44531569797,
            "expected_priority": 0.59531569797,
            "expected_type": "adaptive_conditional_normative_frame_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-16-6607-8a28505704f4f887",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "expected_margin": -0.18094009928,
            "expected_priority": 0.33094009928,
            "expected_type": "adaptive_conditional_normative_temporal_outvoted_margin_low",
        },
    ]

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        expected_margin = float(case["expected_margin"])
        predicted_share = 0.70
        target_share = predicted_share + expected_margin

        def _mock_adaptive_family_ranking_from_logits(
            _encoding,
            *,
            predicted_family: str = predicted_family,
            target_family: str = target_family,
            predicted_share: float = predicted_share,
            target_share: float = target_share,
        ):
            return [
                {
                    "family": predicted_family,
                    "count": 0,
                    "logit": 1.3,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                    "source": "logit_softmax_fallback",
                },
                {
                    "family": target_family,
                    "count": 0,
                    "logit": 1.1,
                    "share_raw": target_share,
                    "share": target_share,
                    "source": "logit_softmax_fallback",
                },
            ]

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            "As provided in section 3, the Secretary shall act by June 1, 2030.",
            document_id=f"compiler-ambiguity-packet-003596-{case['sample_id']}",
        )

        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits",
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert (
            abs(
                float(ambiguity.metadata.get("family_margin_raw", 0.0))
                - expected_margin
            )
            <= 1e-12
        )
        assert (
            abs(
                float(ambiguity.metadata.get("priority", 0.0))
                - float(case["expected_priority"])
            )
            <= 1e-12
        )
        assert (
            abs(
                float(ambiguity.metadata.get("adaptive_priority", 0.0))
                - float(case["expected_priority"])
            )
            <= 1e-12
        )


def test_compiler_preserves_compiler_ambiguity_policy_for_packet_001970_evidence_margins() -> None:
    cases = [
        {
            "sample_id": "us-code-7-2270c-eb915fac2e5136af",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.ALETHIC.value,
            "expected_margin": -0.188889491499,
            "expected_priority": 0.338889491499,
            "expected_type": "adaptive_conditional_normative_alethic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-45-669.-46dd0166b78d10fd",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "expected_margin": -0.549080069697,
            "expected_priority": 0.699080069697,
            "expected_type": "adaptive_frame_conditional_normative_outvoted_margin_low",
        },
    ]

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        expected_margin = float(case["expected_margin"])
        predicted_share = 0.70
        target_share = predicted_share + expected_margin

        def _mock_adaptive_family_ranking_from_logits(
            _encoding,
            *,
            predicted_family: str = predicted_family,
            target_family: str = target_family,
            predicted_share: float = predicted_share,
            target_share: float = target_share,
        ):
            return [
                {
                    "family": predicted_family,
                    "count": 0,
                    "logit": 1.3,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                    "source": "logit_softmax_fallback",
                },
                {
                    "family": target_family,
                    "count": 0,
                    "logit": 1.1,
                    "share_raw": target_share,
                    "share": target_share,
                    "source": "logit_softmax_fallback",
                },
            ]

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            "As provided in section 3, the Secretary shall act by June 1, 2030.",
            document_id=f"compiler-ambiguity-packet-001970-{case['sample_id']}",
        )

        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits",
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert (
            abs(
                float(ambiguity.metadata.get("family_margin_raw", 0.0))
                - expected_margin
            )
            <= 1e-12
        )
        assert (
            abs(
                float(ambiguity.metadata.get("priority", 0.0))
                - float(case["expected_priority"])
            )
            <= 1e-12
        )
        assert (
            abs(
                float(ambiguity.metadata.get("adaptive_priority", 0.0))
                - float(case["expected_priority"])
            )
            <= 1e-12
        )


def test_compiler_marks_epistemic_self_pair_as_compiler_required_policy() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.EPISTEMIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "The Secretary determines eligibility.",
        document_id="compiler-ambiguity-epistemic-self-policy",
    )

    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.EPISTEMIC.value
        and ambiguity.metadata.get("target_family")
        == ModalLogicFamily.EPISTEMIC.value
        and ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        for ambiguity in result.ambiguities
    )


def test_compiler_marks_epistemic_to_deontic_pair_as_compiler_required_policy() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.EPISTEMIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "The Secretary determines eligibility.",
        document_id="compiler-ambiguity-epistemic-deontic-policy",
    )

    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.EPISTEMIC.value
        and ambiguity.metadata.get("target_family")
        == ModalLogicFamily.DEONTIC.value
        and ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        for ambiguity in result.ambiguities
    )


def test_compiler_marks_epistemic_to_temporal_pair_as_compiler_required_policy_without_target_evidence() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.EPISTEMIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "The Secretary determines eligibility.",
        document_id="compiler-ambiguity-epistemic-temporal-policy",
    )

    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.EPISTEMIC.value
        and ambiguity.metadata.get("target_family")
        == ModalLogicFamily.TEMPORAL.value
        and ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        and ambiguity.metadata.get("signal_free_pair_policy_applied") is True
        for ambiguity in result.ambiguities
    )


def test_compiler_marks_epistemic_to_conditional_normative_pair_as_compiler_required_policy_without_target_evidence() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.EPISTEMIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "The Secretary determines eligibility.",
        document_id="compiler-ambiguity-epistemic-conditional-policy",
    )

    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.EPISTEMIC.value
        and ambiguity.metadata.get("target_family")
        == ModalLogicFamily.CONDITIONAL_NORMATIVE.value
        and ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        and ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        and ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        and ambiguity.metadata.get("signal_free_pair_policy_applied") is True
        for ambiguity in result.ambiguities
    )


def test_compiler_marks_frame_to_temporal_pair_as_compiler_required_policy_without_target_evidence() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.FRAME.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "As provided in section 3, this authority applies.",
        document_id="compiler-ambiguity-frame-temporal-policy",
    )

    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.FRAME.value
        and ambiguity.metadata.get("target_family")
        == ModalLogicFamily.TEMPORAL.value
        and ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        and ambiguity.metadata.get("signal_free_pair_policy_applied") is True
        for ambiguity in result.ambiguities
    )


def test_compiler_marks_conditional_to_frame_pair_as_compiler_required_policy_without_target_evidence() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "If approved, publication occurs.",
        document_id="compiler-ambiguity-conditional-frame-policy",
    )

    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.CONDITIONAL_NORMATIVE.value
        and ambiguity.metadata.get("target_family") == ModalLogicFamily.FRAME.value
        and ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        and ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        and ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        and ambiguity.metadata.get("signal_free_pair_policy_applied") is True
        for ambiguity in result.ambiguities
    )


def test_compiler_marks_frame_to_dynamic_pair_as_compiler_ambiguity_signal_free_policy_without_target_evidence() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    def _mock_adaptive_family_ranking_from_logits(_encoding):
        return [
            {
                "family": ModalLogicFamily.FRAME.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
            {
                "family": ModalLogicFamily.DEONTIC.value,
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.5,
                "share": 0.5,
                "source": "logit_softmax_fallback",
            },
        ]

    compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

    result = compiler.compile(
        "As provided in section 3, this authority applies.",
        document_id="compiler-ambiguity-frame-dynamic-policy",
    )

    assert any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == "adaptive_logits"
        and ambiguity.metadata.get("predicted_family")
        == ModalLogicFamily.FRAME.value
        and ambiguity.metadata.get("target_family")
        == ModalLogicFamily.DYNAMIC.value
        and ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        and ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        and ambiguity.metadata.get("signal_free_pair_policy_applied") is True
        for ambiguity in result.ambiguities
    )
