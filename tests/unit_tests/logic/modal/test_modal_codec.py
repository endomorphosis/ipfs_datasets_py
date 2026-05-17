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
    assert compiled.ambiguities[0].ambiguity_type == "close_bm25_frame_scores"
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
    assert low_margin_ambiguity.candidate_ids == ["temporal", "deontic"]
    assert low_margin_ambiguity.metadata["primary_family"] == "temporal"
    assert low_margin_ambiguity.metadata["best_other_family"] == "deontic"
    assert low_margin_ambiguity.metadata["family_margin"] < 0.0


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
    assert frame_margin_ambiguity.candidate_ids == ["frame", "deontic"]
    assert frame_margin_ambiguity.metadata["competing_family"] == "deontic"
    assert frame_margin_ambiguity.metadata["family_margin"] < 0.0
    assert frame_margin_ambiguity.metadata["frame_share"] > 0.0


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
