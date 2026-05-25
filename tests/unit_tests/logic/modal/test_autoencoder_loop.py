"""Tests for the cost-gated legal modal autoencoder loop."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.modal import (
    DEFAULT_LEGAL_IR_BRIDGE_NAMES,
    LegalModalAutoencoderLoop,
    ModalAutoencoderLoopConfig,
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
    assert result.graph_import_report["relationships_imported"] == len(
        result.codec_result.modal_ir.frame_logic.triples
    )
    assert result.prover_signal is not None
    assert result.prover_signal.attempted_count >= 1
    assert result.codex_decision.feature_signature_hash
    assert isinstance(result.available_external_provers, tuple)
    assert result.metadata["loop"] == "legal_modal_autoencoder_loop_v1"


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
