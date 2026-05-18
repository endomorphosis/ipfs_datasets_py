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
    assert temporal_conditional.metadata["target_share"] == 0.0
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
    assert temporal_conditional.metadata["target_share"] == 0.0
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
    assert temporal_conditional.metadata["target_share"] == 0.0
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
    assert temporal_conditional.metadata["target_share"] == 0.0
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
        conditional_scope.metadata["lexical_signals"]["has_condition_or_exception_scope"]
        is True
    )
    assert conditional_scope.metadata["lexical_signals"]["has_conditional_scope_phrase"] is True
    assert conditional_scope.metadata["lexical_signals"]["has_conditional_scope_token"] is True


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
    assert deontic_scope.metadata["target_share"] == 0.0
    assert deontic_scope.metadata["lexical_signals"]["has_deontic_cue"] is False
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
    assert temporal_scope.metadata["target_share"] == 0.0
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
    document = ModalIRDocument(
        document_id="citation-shape-doc",
        source="us_code",
        normalized_text="Sec. 31a-2b. Example heading. Sec. 6050K. Another heading.",
        formulas=[formula, secondary_formula],
    )

    decoded = decode_modal_ir_document(document)
    slot_texts = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)

    assert "31a-2b" in slot_texts["citation_section"]
    assert "6050K" in slot_texts["citation_section"]
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
    assert slot_texts["status_keyword"] == ["repealed"]
    assert any(
        triple["predicate"] == "fallback_rule"
        and triple["object"] == "uscode_editorial_status_heading_v1"
        for triple in triples
    )
    assert any(
        triple["predicate"] == "status_keyword"
        and triple["object"] == "repealed"
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
    assert any(
        triple["predicate"] == "statement_hint"
        and triple["object"] == "sense_of_congress"
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
