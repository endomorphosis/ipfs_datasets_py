"""End-to-end contract for the legal modal autoencoder/Codex gate loop."""

from __future__ import annotations

from dataclasses import replace

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    ModalLogicCodecConfig,
    import_graph_data_to_graph_engine,
    modal_ir_to_neo4j_graph_data,
)
from ipfs_datasets_py.optimizers.common.llm_defaults import (
    DEFAULT_CODEX_MODEL,
    DEFAULT_CODEX_PROVIDER,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    CodexCallCache,
    evaluate_modal_prover_compilation,
)


def test_spacy_frame_logic_prover_graph_and_codex_gate_loop_contract() -> None:
    """Guard the cheap-first legal IR loop before any expensive Codex call."""
    text = "The agency must provide notice within 30 days after application."
    sample = build_us_code_sample(title="5", section="552", text=text)
    codec_result = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    ).encode(
        text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
    )
    sample = replace(
        sample,
        modal_ir=codec_result.modal_ir,
        frame_candidates=codec_result.frame_candidates,
        selected_frame=codec_result.selected_frame,
        losses=codec_result.losses,
    )
    sample.validate()

    assert codec_result.modal_ir.frame_logic.triples
    assert codec_result.modal_ir.frame_logic.to_triples() == codec_result.kg_triples
    assert codec_result.modal_ir.frame_logic.selected_frame == codec_result.selected_frame
    assert codec_result.modal_ir.frame_logic.graph_id == f"{sample.sample_id}:flogic"
    assert "LegalModalDocument" in codec_result.modal_ir.frame_logic.neo4j_node_labels

    graph_data = modal_ir_to_neo4j_graph_data(codec_result.modal_ir)
    engine, import_report = import_graph_data_to_graph_engine(graph_data)
    assert graph_data.relationship_count == len(codec_result.modal_ir.frame_logic.triples)
    assert import_report["nodes_imported"] == graph_data.node_count
    assert import_report["relationships_imported"] == graph_data.relationship_count
    assert import_report["missing_endpoint_relationships"] == 0
    assert engine.find_nodes(
        labels=["LegalModalDocument"],
        properties={"name": sample.sample_id},
    )

    prover_signal = evaluate_modal_prover_compilation(sample)
    assert prover_signal.attempted_count >= 1

    autoencoder = AdaptiveModalAutoencoder()
    cache = CodexCallCache()
    decision = autoencoder.codex_call_decision(
        sample,
        cache=cache,
        prover_signal=prover_signal,
    )
    assert DEFAULT_CODEX_PROVIDER == "codex"
    assert DEFAULT_CODEX_MODEL == "gpt-5.3-codex"
    assert isinstance(decision.should_call_codex, bool)
    assert decision.prover_signal == prover_signal
    assert decision.feature_signature_hash
    assert decision.metrics["cross_entropy_loss"] >= 0.0

    cache.record_codex_call(decision)
    repeated = autoencoder.codex_call_decision(
        sample,
        cache=cache,
        prover_signal=prover_signal,
    )
    assert repeated.should_call_codex is False
    assert "duplicate_text_hash" in repeated.suppressed_reasons
    assert "duplicate_feature_signature" in repeated.suppressed_reasons
