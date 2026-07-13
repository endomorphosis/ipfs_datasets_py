"""End-to-end contract for the legal modal autoencoder/Codex gate loop."""

from __future__ import annotations

import json
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
    export_canonical_state_disagreement_packets,
    update_leanstral_projection_summary,
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


def test_modal_supervisor_health_exposes_executor_pressure_and_seed_blocks() -> None:
    health = build_modal_supervisor_health_report(
        {
            "cycles": 3,
            "latest_queue_counts": {"pending": 8, "claimed": 2},
            "latest_leanstral_projection": {
                "executor_health": {
                    "available": False,
                    "throttled": True,
                    "transient_failure_count": 4,
                },
                "queue_pressure": 0.8,
                "seed_block_reasons": [
                    "executor_unavailable",
                    "transient_failure_rate_above_cap",
                ],
                "transient_failure_rate": 0.4,
            },
            "program_synthesis_pending_cap": 10,
        }
    ).to_dict()

    assert health["executor_health"]["available"] is False
    assert health["executor_health"]["throttled"] is True
    assert health["queue_pressure"] == 0.8
    assert health["transient_failure_rate"] == 0.4
    assert health["seed_block_reasons"] == [
        "executor_unavailable",
        "transient_failure_rate_above_cap",
    ]

    summary: dict[str, object] = {}
    update_leanstral_projection_summary(
        summary,
        {
            "budget_blocked_count": 2,
            "deduped_count": 3,
            "report_only_count": 4,
            "seeded_count": 1,
            "stale_count": 5,
            "seeded_todo_ids": ["program-leanstral-a"],
        },
    )
    assert summary["latest_leanstral_projection_seeded_count"] == 1
    assert summary["latest_leanstral_projection_deduped_count"] == 3
    assert summary["latest_leanstral_projection_stale_count"] == 5
    assert summary["latest_leanstral_projection_budget_blocked_count"] == 2
    assert summary["latest_leanstral_projection_report_only_count"] == 4


def test_production_runner_exports_canonical_disagreement_packets(
    tmp_path,
    monkeypatch,
) -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall provide notice before denying a request.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    autoencoder.evaluate([sample], use_sample_memory=False)
    compiler_metrics = {
        "autoencoder_guidance_enabled": False,
        "cross_entropy_loss": 0.42,
        "cosine_similarity": 0.76,
        "evaluated_count": 1,
        "sample_count": 1,
        "sample_metric_records": [
            {
                "compiler_guidance_applied": False,
                "metric_sample_id": sample.sample_id,
                "metrics": {
                    "cross_entropy_loss": 0.42,
                    "cosine_similarity": 0.76,
                    "source_decompiled_text_embedding_cosine_loss": 0.24,
                    "source_decompiled_text_token_loss": 0.31,
                },
                "sample_id": sample.sample_id,
            }
        ],
    }
    guided_metrics = {
        **compiler_metrics,
        "autoencoder_guidance_enabled": True,
        "autoencoder_guidance_applied_count": 1,
        "sample_metric_records": [
            {
                "compiler_guidance_applied": True,
                "metric_sample_id": sample.sample_id,
                "metrics": {
                    "cross_entropy_loss": 0.37,
                    "cosine_similarity": 0.8,
                    "source_decompiled_text_embedding_cosine_loss": 0.2,
                    "source_decompiled_text_token_loss": 0.29,
                },
                "sample_id": sample.sample_id,
            }
        ],
    }

    calls = {"guidance": 0, "introspection": 0}
    original_guidance = autoencoder.compiler_guidance_for_sample
    original_introspection = autoencoder.introspect_sample

    def counting_guidance(*args, **kwargs):
        calls["guidance"] += 1
        return original_guidance(*args, **kwargs)

    def counting_introspection(*args, **kwargs):
        calls["introspection"] += 1
        return original_introspection(*args, **kwargs)

    monkeypatch.setattr(autoencoder, "compiler_guidance_for_sample", counting_guidance)
    monkeypatch.setattr(autoencoder, "introspect_sample", counting_introspection)

    summary_path = tmp_path / "run.summary"
    report = export_canonical_state_disagreement_packets(
        autoencoder=autoencoder,
        compiler_ir_validation=compiler_metrics,
        compiler_ir_guided_validation=guided_metrics,
        cycle=3,
        export_mode="export",
        root=tmp_path,
        run_id="contract-run",
        samples=[sample],
        state=autoencoder.state,
        summary_path=summary_path,
        validation_indices=[17],
        validation_mode="fixed_canary",
        evaluate_provers=False,
    )

    assert report["enabled"] is True
    assert report["packet_count"] == 2
    assert report["shared_sample_analysis_count"] == 1
    assert report["shared_sample_analysis_cache_hit_count"] == 1
    assert report["schema_failure_count"] == 0
    # Guidance performs one internal introspection. Both calls are shared by
    # the guided and unguided export roles instead of being repeated per role.
    assert calls == {"guidance": 1, "introspection": 2}
    assert report["paths"] == [str(tmp_path / "run.canonical-disagreements.jsonl")]
    lines = (tmp_path / "run.canonical-disagreements.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 2
    packets = [json.loads(line) for line in lines]
    assert {packet["run_context"]["evaluation_role"] for packet in packets} == {
        "guided",
        "unguided",
    }
    for packet in packets:
        assert packet["run_context"]["cycle"] == 3
        assert packet["run_context"]["sample_role"] == "frozen_canary"
        assert packet["run_context"]["frozen_canary"]["index"] == 17
        assert packet["evidence_hashes"]["state_hash"] == report["state_hash"]
        assert packet["compiler_decompiler_metrics"]["cross_entropy_loss"] > 0.0
        assert packet["proof_route_status"]["route_status"] == "not_evaluated"
        encoded = json.dumps(packet, sort_keys=True)
        assert "decoded_embedding" not in encoded
        assert "feature_embedding_weights" not in encoded
