"""Tests for the cost-gated legal modal autoencoder loop."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.modal import (
    DEFAULT_LEGAL_IR_BRIDGE_NAMES,
    LegalModalAutoencoderLoop,
    LeanstralConfig,
    ModalAutoencoderLoopConfig,
    MODAL_INTROSPECTION_MODES,
    ModalLogicCodecConfig,
    validate_frame_logic_patch,
)
from ipfs_datasets_py.optimizers.common.llm_defaults import (
    DEFAULT_CODEX_MODEL,
    DEFAULT_CODEX_PROVIDER,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    CodexCallGateConfig,
)


def test_autoencoder_loop_keeps_frame_logic_graph_and_provers_before_llm() -> None:
    calls: list[str] = []

    def fake_llm(prompt: str, **kwargs) -> str:
        calls.append(prompt)
        return "{}"

    loop = LegalModalAutoencoderLoop(
        ModalAutoencoderLoopConfig(
            codec_config=ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
            allow_llm_repair=False,
            check_external_prover_router=True,
        ),
        llm_generate=fake_llm,
    )

    result = loop.run(
        "The agency must provide notice within 30 days after application.",
        document_id="loop-doc",
        citation="5 U.S.C. 552",
    )

    assert calls == []
    assert result.llm_called is False
    assert result.codec_result.modal_ir.frame_logic.triples
    assert result.graph_import_report["missing_endpoint_relationships"] == 0
    assert result.graph_import_report["relationships_imported"] >= len(
        result.codec_result.modal_ir.frame_logic.triples
    )
    assert result.prover_signal is not None
    assert result.prover_signal.attempted_count >= 1
    assert result.codex_decision.feature_signature_hash
    assert isinstance(result.available_external_provers, tuple)
    assert result.metadata["loop"] == "legal_modal_autoencoder_loop_v1"
    assert result.introspection_summary.mode == "off"
    assert result.introspection is None
    assert result.cache_counters["codex_call_count"] == 0
    assert "codec" in result.phase_timings
    assert "prover" in result.phase_timings
    assert result.state_to_compiler_patch_lag["lag"] >= 0


def test_autoencoder_loop_default_introspection_mode_is_off() -> None:
    config = ModalAutoencoderLoopConfig()

    assert config.introspection_mode == "off"
    assert config.to_dict()["introspection_mode"] == "off"
    assert "enforce" in MODAL_INTROSPECTION_MODES


def test_autoencoder_loop_gate_includes_multiview_legal_ir_losses() -> None:
    loop = LegalModalAutoencoderLoop(
        ModalAutoencoderLoopConfig(
            codec_config=ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
            gate_config=CodexCallGateConfig(
                min_cosine_similarity=0.0,
                max_cross_entropy_loss=10.0,
                max_frame_ranking_loss=10.0,
                max_reconstruction_loss=10.0,
                max_symbolic_validity_penalty=10.0,
                require_prover_compilation=False,
                codex_call_cost=0.0,
            ),
            allow_llm_repair=False,
            evaluate_provers=False,
            legal_ir_bridge_names=("deontic_norms", "fol_tdfol"),
        )
    )

    result = loop.run(
        "The agency must provide notice within 30 days after application.",
        document_id="loop-doc",
        citation="5 U.S.C. 552",
    )

    metrics = result.codex_decision.metrics
    assert result.metadata["legal_ir_bridge_names"] == ["deontic_norms", "fol_tdfol"]
    assert DEFAULT_LEGAL_IR_BRIDGE_NAMES == (
        "modal_frame_logic",
        "deontic_norms",
        "fol_tdfol",
        "cec_dcec",
        "external_prover_router",
        "zkp_attestation",
    )
    assert metrics["legal_ir_target_count"] == 1.0
    assert metrics["legal_ir_multiview_total_loss"] > 0.0
    assert metrics["legal_ir_view_cross_entropy_loss"] > 0.0
    assert "high_legal_ir_multiview_total_loss" in result.codex_decision.reasons
    assert "high_legal_ir_view_cross_entropy_loss" in result.codex_decision.reasons
    assert result.llm_called is False


def test_autoencoder_loop_routes_sparse_codex_repair_through_llm_router_defaults() -> None:
    requests: list[dict[str, object]] = []

    def fake_llm(prompt: str, **kwargs) -> str:
        requests.append({"prompt": prompt, **kwargs})
        return json.dumps(
            {
                "deterministic_rule_hints": [
                    {
                        "action": "add_or_refine_spacy_rule",
                        "rationale": "capture explicit agency actor",
                        "target_component": "modal.compiler",
                    }
                ],
                "frame_logic_triples": [
                    {
                        "subject": "loop-doc",
                        "predicate": "actor",
                        "object": "agency",
                    }
                ],
                "notes": "bounded repair patch",
            }
        )

    loop = LegalModalAutoencoderLoop(
        ModalAutoencoderLoopConfig(
            codec_config=ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
            gate_config=CodexCallGateConfig(
                min_cosine_similarity=2.0,
                codex_call_cost=0.0,
                min_net_benefit=0.0,
                require_prover_compilation=False,
                max_codex_calls=1,
            ),
            allow_llm_repair=True,
            apply_llm_frame_logic_patches=True,
            evaluate_provers=False,
        ),
        llm_generate=fake_llm,
    )

    result = loop.run(
        "The agency must provide notice within 30 days after application.",
        document_id="loop-doc",
        citation="5 U.S.C. 552",
    )

    assert result.llm_called is True
    assert result.llm_patch is not None
    assert result.llm_patch_validation is not None
    assert result.llm_patch_validation.accepted_count == 1
    assert result.llm_patch_validation.rejected_count == 0
    assert result.repaired_modal_ir is not None
    assert result.repaired_modal_ir.metadata["llm_frame_logic_patch_count"] == 1
    assert "ACTOR" in result.repaired_modal_ir.frame_logic.neo4j_relationship_types
    assert loop.cache.codex_call_count == 1
    assert requests[0]["provider"] == DEFAULT_CODEX_PROVIDER
    assert requests[0]["model_name"] == DEFAULT_CODEX_MODEL
    assert requests[0]["allow_local_fallback"] is False
    assert requests[0]["disable_model_retry"] is True
    assert "Return strict JSON only" in str(requests[0]["prompt"])

    repeated = loop.run(
        "The agency must provide notice within 30 days after application.",
        document_id="loop-doc",
        citation="5 U.S.C. 552",
    )
    assert repeated.llm_called is False
    assert "duplicate_text_hash" in repeated.codex_decision.suppressed_reasons
    assert len(requests) == 1


def test_autoencoder_loop_export_mode_honors_scope_and_audit_budget(tmp_path) -> None:
    loop = LegalModalAutoencoderLoop(
        ModalAutoencoderLoopConfig(
            codec_config=ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
            evaluate_provers=False,
            introspection_mode="export",
            max_audits_per_cycle=1,
            max_todos_per_cycle=0,
            target_scope_filters=("deontic",),
            require_prover_confirmation=False,
            introspection_export_path=str(tmp_path),
        )
    )

    result = loop.run(
        "The agency must provide notice within 30 days after application.",
        document_id="loop-doc",
        citation="5 U.S.C. 552",
    )

    summary = result.introspection_summary
    assert summary.mode == "export"
    assert summary.alive is True
    assert summary.productive is True
    assert summary.audits_attempted == 1
    assert summary.todos_seeded == 0
    assert summary.target_scope_matched is True
    assert result.introspection is not None
    assert summary.export_path
    exported = json.loads((tmp_path / "loop-doc.introspection.json").read_text())
    assert exported["sample_id"] == "loop-doc"


def test_autoencoder_loop_enforce_mode_fails_closed_without_prover_confirmation() -> None:
    loop = LegalModalAutoencoderLoop(
        ModalAutoencoderLoopConfig(
            codec_config=ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
            evaluate_provers=False,
            introspection_mode="enforce",
            max_audits_per_cycle=1,
            max_todos_per_cycle=1,
            require_prover_confirmation=True,
        )
    )

    result = loop.run(
        "The agency must provide notice within 30 days after application.",
        document_id="loop-doc",
        citation="5 U.S.C. 552",
    )

    assert result.accepted is False
    assert result.introspection_summary.mode == "enforce"
    assert result.introspection_summary.enforce_allowed is False
    assert "prover_confirmation_required" in result.introspection_summary.blocked_reasons


def test_autoencoder_loop_run_many_applies_per_cycle_audit_budget(tmp_path) -> None:
    loop = LegalModalAutoencoderLoop(
        ModalAutoencoderLoopConfig(
            codec_config=ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
            evaluate_provers=False,
            introspection_mode="export",
            max_audits_per_cycle=1,
            max_todos_per_cycle=0,
            require_prover_confirmation=False,
            introspection_export_path=str(tmp_path),
        )
    )

    results = loop.run_many(
        [
            {
                "document_id": "loop-doc-1",
                "text": "The agency must provide notice within 30 days.",
            },
            {
                "document_id": "loop-doc-2",
                "text": "The Secretary may issue regulations after review.",
            },
        ]
    )

    assert results[0].introspection_summary.audits_attempted == 1
    assert results[1].introspection_summary.audits_attempted == 0
    assert "max_audits_per_cycle_exhausted" in results[1].introspection_summary.blocked_reasons


def test_autoencoder_loop_rejects_ungrounded_llm_frame_logic_triples() -> None:
    def fake_llm(prompt: str, **kwargs) -> str:
        return json.dumps(
            {
                "frame_logic_triples": [
                    {
                        "subject": "loop-doc",
                        "predicate": "actor",
                        "object": "agency",
                    },
                    {
                        "subject": "loop-doc",
                        "predicate": "unsafe-predicate",
                        "object": "agency",
                    },
                    {
                        "subject": "loop-doc",
                        "predicate": "actor",
                        "object": "extraneous ungrounded concept",
                    },
                    {
                        "subject": "fabricated-subject",
                        "predicate": "actor",
                        "object": "agency",
                    },
                ]
            }
        )

    loop = LegalModalAutoencoderLoop(
        ModalAutoencoderLoopConfig(
            codec_config=ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
            gate_config=CodexCallGateConfig(
                min_cosine_similarity=2.0,
                codex_call_cost=0.0,
                min_net_benefit=0.0,
                require_prover_compilation=False,
            ),
            allow_llm_repair=True,
            apply_llm_frame_logic_patches=True,
            evaluate_provers=False,
        ),
        llm_generate=fake_llm,
    )

    result = loop.run(
        "The agency must provide notice within 30 days after application.",
        document_id="loop-doc",
        citation="5 U.S.C. 552",
    )

    assert result.llm_patch_validation is not None
    assert result.llm_patch_validation.accepted_count == 1
    assert result.llm_patch_validation.rejected_count == 3
    rejected_reasons = {
        reason
        for rejected in result.llm_patch_validation.rejected_triples
        for reason in rejected["reasons"]
    }
    assert "unsafe_predicate" in rejected_reasons
    assert "ungrounded_object" in rejected_reasons
    assert "ungrounded_subject" in rejected_reasons
    assert result.repaired_modal_ir is not None
    patched_triples = result.repaired_modal_ir.frame_logic.to_triples()
    assert {
        "subject": "loop-doc",
        "predicate": "actor",
        "object": "agency",
    } in patched_triples
    assert all(triple["object"] != "extraneous ungrounded concept" for triple in patched_triples)


def test_validate_frame_logic_patch_rejects_duplicate_triples() -> None:
    loop = LegalModalAutoencoderLoop(
        ModalAutoencoderLoopConfig(
            codec_config=ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
            evaluate_provers=False,
        )
    )
    result = loop.run(
        "The agency must provide notice within 30 days after application.",
        document_id="loop-doc",
        citation="5 U.S.C. 552",
    )
    existing = result.codec_result.modal_ir.frame_logic.to_triples()[0]

    validation = validate_frame_logic_patch(
        result.codec_result.modal_ir,
        {"frame_logic_triples": [existing]},
    )

    assert validation.accepted_count == 0
    assert validation.rejected_count == 1
    assert "duplicate_triple" in validation.rejected_triples[0]["reasons"]


def test_autoencoder_loop_persists_codex_gate_cache_between_runs(tmp_path) -> None:
    requests: list[dict[str, object]] = []
    cache_path = tmp_path / "codex_gate_cache.json"

    def fake_llm(prompt: str, **kwargs) -> str:
        requests.append({"prompt": prompt, **kwargs})
        return json.dumps({"frame_logic_triples": []})

    config = ModalAutoencoderLoopConfig(
        codec_config=ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
        gate_config=CodexCallGateConfig(
            min_cosine_similarity=2.0,
            codex_call_cost=0.0,
            min_net_benefit=0.0,
            require_prover_compilation=False,
            max_codex_calls=5,
        ),
        allow_llm_repair=True,
        evaluate_provers=False,
        codex_cache_path=str(cache_path),
    )

    first_loop = LegalModalAutoencoderLoop(config, llm_generate=fake_llm)
    first = first_loop.run(
        "The agency must provide notice within 30 days after application.",
        document_id="loop-doc",
        citation="5 U.S.C. 552",
    )

    assert first.llm_called is True
    assert cache_path.exists()
    stored = json.loads(cache_path.read_text(encoding="utf-8"))
    assert stored["codex_call_count"] == 1
    assert stored["codex_text_hashes"]

    second_loop = LegalModalAutoencoderLoop(config, llm_generate=fake_llm)
    second = second_loop.run(
        "The agency must provide notice within 30 days after application.",
        document_id="loop-doc",
        citation="5 U.S.C. 552",
    )

    assert second.llm_called is False
    assert "duplicate_text_hash" in second.codex_decision.suppressed_reasons
    assert "duplicate_feature_signature" in second.codex_decision.suppressed_reasons
    assert second_loop.cache.codex_call_count == 1
    assert len(requests) == 1


def test_autoencoder_loop_run_many_reuses_gate_cache_for_duplicate_records() -> None:
    requests: list[dict[str, object]] = []

    def fake_llm(prompt: str, **kwargs) -> str:
        requests.append({"prompt": prompt, **kwargs})
        return json.dumps({"frame_logic_triples": []})

    loop = LegalModalAutoencoderLoop(
        ModalAutoencoderLoopConfig(
            codec_config=ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
            gate_config=CodexCallGateConfig(
                min_cosine_similarity=2.0,
                codex_call_cost=0.0,
                min_net_benefit=0.0,
                require_prover_compilation=False,
                max_codex_calls=5,
            ),
            allow_llm_repair=True,
            evaluate_provers=False,
        ),
        llm_generate=fake_llm,
    )

    results = loop.run_many(
        [
            {
                "document_id": "loop-doc-a",
                "citation": "5 U.S.C. 552",
                "text": "The agency must provide notice within 30 days after application.",
            },
            {
                "document_id": "loop-doc-b",
                "citation": "5 U.S.C. 552",
                "text": "The agency must provide notice within 30 days after application.",
            },
        ]
    )

    assert len(results) == 2
    assert results[0].llm_called is True
    assert results[1].llm_called is False
    assert "duplicate_text_hash" in results[1].codex_decision.suppressed_reasons
    assert loop.cache.codex_call_count == 1
    assert len(requests) == 1


def test_autoencoder_loop_runs_leanstral_as_a_non_mutating_shadow_lane(tmp_path) -> None:
    requests: list[dict[str, object]] = []

    def fake_leanstral(prompt: str, **kwargs) -> str:
        requests.append({"prompt": prompt, **kwargs})
        task = json.loads(prompt)["task"]
        change_spec = task["compiler_change_spec"]
        proof_obligation_id = task["theorem_registry"]["theorems"][0]["theorem_id"]
        return json.dumps(
            {
                "schema_version": "legal-ir-leanstral-proposal-v1",
                "task_id": task["task_id"],
                "target_modal_ir_hash": task["modal_ir_hash"],
                "compiler_change_spec_id": change_spec["spec_id"],
                "proof": "by unfold wellFormed modalityMatches sourceProvenancePresent; decide",
                "drafted_logic_candidates": [
                    {
                        "candidate": "obligation(agency, provide_notice) before deadline(days_30)",
                        "compiler_surface": change_spec["target_component"],
                        "confidence": 0.8,
                        "intended_use": "guidance_only",
                        "logic_family": "deontic",
                        "proof_obligation_id": proof_obligation_id,
                    }
                ],
            }
        )

    loop = LegalModalAutoencoderLoop(
        ModalAutoencoderLoopConfig(
            codec_config=ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8),
            evaluate_provers=False,
            leanstral_config=LeanstralConfig(
                enabled=True,
                artifact_dir=str(tmp_path / "leanstral"),
            ),
            introspection_export_path=str(tmp_path / "introspection"),
            introspection_mode="export",
            max_audits_per_cycle=1,
            require_prover_confirmation=False,
        ),
        leanstral_generate=fake_leanstral,
    )

    result = loop.run(
        "The agency must provide notice within 30 days after application.",
        document_id="loop-doc",
        citation="5 U.S.C. 552",
    )

    assert result.leanstral_shadow is not None
    assert result.leanstral_shadow.validation.accepted is True
    assert result.leanstral_shadow.artifact_path is not None
    assert result.repaired_modal_ir is None
    assert result.metadata["leanstral_shadow_error"] == ""
    assert requests[0]["provider"] == "leanstral_local"
    exported = json.loads(
        (tmp_path / "introspection" / "loop-doc.introspection.json").read_text(
            encoding="utf-8"
        )
    )
    assert exported["leanstral_guidance"]["trusted"] is True
    assert exported["leanstral_guidance"]["drafted_logic_candidates"][0][
        "guidance_only"
    ] is True
    assert exported["leanstral_guidance"]["proof_obligation_ids"]
