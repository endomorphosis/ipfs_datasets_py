"""End-to-end contract for the legal modal autoencoder/Codex gate loop."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    LegalModalAutoencoderLoop,
    ModalAutoencoderLoopConfig,
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
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_reporting import (
    build_modal_supervisor_health_report,
    state_to_compiler_patch_lag,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    autoencoder_enforce_fail_closed_reason,
    autoencoder_rollout_control,
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
    assert graph_data.relationship_count >= len(codec_result.modal_ir.frame_logic.triples)
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
    assert DEFAULT_CODEX_MODEL == "gpt-5.5"
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


def test_modal_loop_contract_exposes_alive_vs_productive_summary() -> None:
    loop = LegalModalAutoencoderLoop(
        ModalAutoencoderLoopConfig(
            codec_config=ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
            evaluate_provers=False,
            introspection_mode="shadow",
            max_audits_per_cycle=1,
            require_prover_confirmation=False,
        )
    )

    result = loop.run(
        "The agency must provide notice within 30 days after application.",
        document_id="contract-doc",
        citation="5 U.S.C. 552",
    )
    data = result.to_dict()

    assert data["introspection_summary"]["alive"] is True
    assert data["introspection_summary"]["productive"] is True
    assert data["cache_counters"]["autoencoder_sample_feature_cache_entries"] >= 1
    assert data["phase_timings"]["codec"] >= 0.0
    assert data["state_to_compiler_patch_lag"]["lag"] >= 0


def test_daemon_rollout_control_defaults_off_and_enforce_fails_closed() -> None:
    defaults = autoencoder_rollout_control(SimpleNamespace())

    assert defaults["introspection_mode"] == "off"
    assert defaults["max_audits_per_cycle"] == 0
    assert defaults["max_todos_per_cycle"] == 0

    enforce = autoencoder_rollout_control(
        SimpleNamespace(
            autoencoder_introspection_mode="enforce",
            autoencoder_max_audits_per_cycle=1,
            autoencoder_max_todos_per_cycle=2,
            autoencoder_require_prover_confirmation=True,
            autoencoder_target_scope_filters="modal.compiler,deontic",
        )
    )

    assert enforce["introspection_mode"] == "enforce"
    assert enforce["target_scope_filters"] == ["modal.compiler", "deontic"]
    assert (
        autoencoder_enforce_fail_closed_reason(
            enforce,
            bridge_evaluate_provers=False,
        )
        == "enforce_requires_prover_confirmation"
    )
    assert (
        autoencoder_enforce_fail_closed_reason(
            enforce,
            bridge_evaluate_provers=True,
        )
        == ""
    )


def test_modal_supervisor_health_distinguishes_alive_from_productive_loop() -> None:
    alive = build_modal_supervisor_health_report(
        {
            "active_cycle_phase": "sampling",
            "cycles": 1,
            "latest_cycle_phase_timings": {"sampling": 0.25},
            "latest_queue_counts": {"pending": 3},
        }
    ).to_dict()

    assert alive["alive"] is True
    assert alive["productive"] is False

    productive = build_modal_supervisor_health_report(
        {
            "cycles": 2,
            "latest_autoencoder_state_telemetry": {
                "applied_todo_count": 1,
                "generalizable_entry_count": 5,
            },
            "program_synthesis_seeded": 2,
            "latest_program_synthesis_seeded_count": 1,
        }
    ).to_dict()

    assert productive["alive"] is True
    assert productive["productive"] is True
    assert productive["state_to_compiler_patch_lag"] == {
        "compiler_patch_count": 1,
        "lag": 5,
        "state_update_count": 6,
    }
    assert state_to_compiler_patch_lag(
        state_update_count=3,
        compiler_patch_count=1,
    )["lag"] == 2
