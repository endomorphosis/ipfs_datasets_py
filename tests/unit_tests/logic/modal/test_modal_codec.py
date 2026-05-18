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
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import ModalIRFrameLogic
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
    assert all(
        ambiguity.metadata["adaptive_family_margin_threshold"] == 0.15
        for ambiguity in adaptive_ambiguities
    )
    assert all(
        ambiguity.metadata["adaptive_margin_direction"] == "outvoted"
        for ambiguity in adaptive_ambiguities
    )
    assert all(ambiguity.metadata["family_margin"] < 0.0 for ambiguity in adaptive_ambiguities)


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
    assert slot_texts["citation"] == ["5 U.S.C. 552"]
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
    assert any(feature.startswith("flogic:modal_family:") for feature in feature_keys)


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
