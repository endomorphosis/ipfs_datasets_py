import json

from ipfs_datasets_py.logic.modal import (
    INTROSPECTION_EXPORT_SCHEMA_VERSION,
    IntrospectionPacketExportConfig,
    append_disagreement_packets_jsonl,
    export_introspection_packet,
    export_prioritized_disagreement_packets,
    packet_to_json,
    validate_disagreement_packet,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)


def _sample():
    return build_us_code_sample(
        title="42",
        section="1983",
        text=(
            "The Secretary shall provide notice to each applicant before "
            "denying assistance, except as provided in this section."
        ),
    )


def _introspection(sample_id: str, *, cosine_loss: float = 0.37):
    return {
        "base_decoded_embedding": [0.1] * 32,
        "cosine_loss": cosine_loss,
        "cosine_similarity": 1.0 - cosine_loss,
        "decoded_embedding": [0.2] * 32,
        "family_margin": -0.42,
        "feature_embedding_weights": {"must": [0.5] * 64},
        "legal_ir_component_gaps": {
            "TDFOL.prover": 0.18,
            "deontic.ir": 0.27,
            "knowledge_graphs.neo4j_compat": -0.05,
        },
        "legal_ir_predicted_view_distribution": {
            "TDFOL.prover": 0.62,
            "deontic.ir": 0.11,
        },
        "legal_ir_view_cross_entropy_excess_loss": 0.24,
        "legal_ir_view_cross_entropy_loss": 0.71,
        "legal_ir_view_distribution": {
            "TDFOL.prover": 0.25,
            "deontic.ir": 0.61,
            "knowledge_graphs.neo4j_compat": 0.14,
        },
        "pipeline_stage_diagnostics": {
            "autoencoder_embedding_cosine_gap": cosine_loss,
            "legal_ir_component_gap_max": 0.27,
        },
        "pipeline_stage_focus": ["modal_family_registry", "legal_ir_multiview"],
        "predicted_family": "temporal",
        "predicted_probability": 0.73,
        "reconstruction_loss": 0.19,
        "residual_vector": [0.3] * 32,
        "sample_id": sample_id,
        "sample_memory_used": False,
        "source_decompiled_text_embedding_cosine_loss": 0.31,
        "source_decompiled_text_token_loss": 0.44,
        "synthesis_focus": [
            "refine_modal_family_cue_rules",
            "repair_multiview_legal_ir_loss",
            "audit_frame_logic_terms",
        ],
        "target_family": "deontic",
        "target_probability": 0.31,
        "top_embedding_contributions": [
            {
                "contribution_type": "feature_embedding_weight",
                "feature": "semantic-slot:notice",
                "magnitude": 0.8,
                "metadata": {
                    "alignment_with_residual": 0.91,
                    "raw_dense_weights": [1.0] * 24,
                },
                "value": 0.7,
            },
            {
                "contribution_type": "feature_embedding_weight",
                "feature": "semantic-slot:exception",
                "magnitude": 0.4,
                "value": -0.3,
            },
        ],
        "top_family_contributions": [
            {
                "contribution_type": "feature_family_logit",
                "family": "temporal",
                "feature": "token:before",
                "magnitude": 0.9,
                "metadata": {"supports_target": False},
                "value": 0.9,
            }
        ],
    }


def test_export_introspection_packet_is_compact_deterministic_and_complete():
    sample = _sample()
    introspection = _introspection(sample.sample_id)
    guidance = {
        "family_distribution": {"deontic": 0.22, "temporal": 0.78},
        "ranked_guidance_features": [
            {
                "embedding_weight_norm": 0.25,
                "family_logit_magnitude": 0.75,
                "feature": "compiler-contract:exception-scope",
                "legal_ir_view_logit_magnitude": 0.5,
                "score": 1.5,
            }
        ],
    }
    prover_signal = {
        "attempted_count": 2,
        "details": [
            {
                "compiled": True,
                "formula": "raw formula text must be omitted",
                "formula_id": "f1",
                "overall_valid": True,
                "statuses": ["valid"],
            },
            {
                "compiled": False,
                "formula_id": "f2",
                "overall_valid": False,
                "statuses": ["unavailable"],
            },
        ],
        "failed_count": 1,
        "valid_count": 1,
        "verified_by": ["native-modal"],
    }

    packet = export_introspection_packet(
        sample,
        introspection,
        compiler_guidance=guidance,
        prover_signal=prover_signal,
        config=IntrospectionPacketExportConfig(max_packet_bytes=9000),
    )
    again = export_introspection_packet(
        sample,
        introspection,
        compiler_guidance=guidance,
        prover_signal=prover_signal,
        config=IntrospectionPacketExportConfig(max_packet_bytes=9000),
    )

    payload = packet.to_dict()
    encoded = packet_to_json(packet)
    assert encoded == packet_to_json(again)
    assert len(encoded.encode("utf-8")) <= 9000
    assert payload["schema_version"] == INTROSPECTION_EXPORT_SCHEMA_VERSION
    assert payload["evidence_id"].startswith("lir-disagree-")
    assert payload["versions"]["state_version"]
    assert payload["versions"]["config_version"]
    assert payload["sample_hashes"]["sample_id"] == sample.sample_id
    assert payload["sample_hashes"]["source_span_hashes"]
    assert payload["legal_ir_views"]["canonical"]["modal_ir_hash"] == sample.modal_ir.canonical_hash()
    assert payload["legal_ir_views"]["predicted"]["predicted_family"] == "temporal"
    assert payload["per_family_gaps"][0]["family"] in {"deontic", "temporal"}
    assert payload["compiler_round_trip_gaps"]["source_decompiled_text_token_loss"] == 0.44
    assert payload["ranked_feature_contributions"][0]["feature"] == (
        "compiler-contract:exception-scope"
    )
    assert "repair_multiview_legal_ir_loss" in payload["synthesis_focus"]
    assert payload["proof_route_status"]["route_status"] == "failed"
    assert payload["proof_route_status"]["details"][0]["formula_id"] == "f1"
    assert payload["anti_copy_evidence"]["raw_source_text_included"] is False
    assert payload["anti_copy_evidence"]["dense_weight_tables_included"] is False

    assert "decoded_embedding" not in encoded
    assert "base_decoded_embedding" not in encoded
    assert "residual_vector" not in encoded
    assert "feature_embedding_weights" not in encoded
    assert "raw_dense_weights" not in encoded
    assert "The Secretary shall provide notice" not in encoded
    assert "raw formula text must be omitted" not in encoded


def test_export_introspection_packet_caps_size_deterministically():
    sample = _sample()
    introspection = _introspection(sample.sample_id)
    introspection["top_embedding_contributions"] = [
        {
            "contribution_type": "feature_embedding_weight",
            "feature": f"feature-{index:03d}",
            "magnitude": 1.0 / (index + 1),
            "metadata": {"alignment_with_residual": 0.1, "note": "trim me"},
            "value": 1.0 / (index + 1),
        }
        for index in range(60)
    ]

    config = IntrospectionPacketExportConfig(
        max_packet_bytes=2600,
        max_ranked_features=60,
        max_source_span_hashes=8,
    )
    packet = export_introspection_packet(sample, introspection, config=config)
    payload = packet.to_dict()
    encoded = packet.to_json()

    assert len(encoded.encode("utf-8")) <= config.max_packet_bytes
    assert payload["truncation"]["truncated"] is True
    assert payload["truncation"]["original_ranked_feature_count"] >= 60
    assert len(payload["ranked_feature_contributions"]) < 60
    json.loads(encoded)


def test_export_prioritized_disagreement_packets_orders_by_priority():
    sample = _sample()
    low = _introspection(sample.sample_id, cosine_loss=0.05)
    low["family_margin"] = 0.8
    low["predicted_family"] = "deontic"
    low["predicted_probability"] = 0.9
    low["target_probability"] = 0.9
    high = _introspection(sample.sample_id, cosine_loss=0.67)
    packets = export_prioritized_disagreement_packets(
        [
            {"sample": sample, "introspection": low},
            {"sample": sample, "introspection": high},
        ],
        config=IntrospectionPacketExportConfig(max_packet_bytes=6000),
    )

    assert len(packets) == 2
    assert packets[0].payload["priority_score"] >= packets[1].payload["priority_score"]
    assert packets[0].payload["compiler_round_trip_gaps"]["embedding_cosine_gap"] == 0.67


def test_export_packet_accepts_production_context_and_appends_jsonl(tmp_path):
    sample = _sample()
    introspection = _introspection(sample.sample_id)
    packet = export_introspection_packet(
        sample,
        introspection,
        compiler_guidance={
            "legal_ir_view_gap_distribution": {"deontic.ir": 0.4},
            "ranked_guidance_features": [
                {"feature": "compiler-contract:notice", "score": 0.7}
            ],
        },
        compiler_metrics={
            "compiler_guidance_applied": True,
            "metrics": {
                "cross_entropy_loss": 0.32,
                "cosine_similarity": 0.81,
                "source_decompiled_text_embedding_cosine_loss": 0.19,
                "source_decompiled_text_token_loss": 0.27,
            },
            "metric_sample_id": sample.sample_id,
            "sample_id": sample.sample_id,
        },
        export_context={
            "compiler_commit": "abc123",
            "cycle": 7,
            "evaluation_role": "guided",
            "export_mode": "shadow",
            "frozen_canary": {
                "canary_set_hash": "canary-hash",
                "enabled": True,
                "index": 42,
                "sample_id": sample.sample_id,
            },
            "run_id": "run-1",
            "sample_role": "frozen_canary",
            "state_hash": "state-hash",
        },
        config=IntrospectionPacketExportConfig(max_packet_bytes=9000),
    )

    payload = packet.to_dict()
    assert validate_disagreement_packet(packet) == []
    assert payload["run_context"]["compiler_commit"] == "abc123"
    assert payload["run_context"]["cycle"] == 7
    assert payload["run_context"]["sample_role"] == "frozen_canary"
    assert payload["run_context"]["frozen_canary"]["index"] == 42
    assert payload["evidence_hashes"]["state_hash"] == "state-hash"
    assert payload["compiler_decompiler_metrics"]["cross_entropy_loss"] == 0.32
    assert payload["learned_view_gaps"]["view_gap_distribution"]["deontic.ir"] == 0.4

    export_path = tmp_path / "packets.jsonl"
    report = append_disagreement_packets_jsonl(export_path, [packet])
    assert report["packet_count"] == 1
    assert report["schema_failure_count"] == 0
    lines = export_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    decoded = json.loads(lines[0])
    assert decoded["evidence_id"] == payload["evidence_id"]
    encoded = lines[0]
    assert "decoded_embedding" not in encoded
    assert "feature_embedding_weights" not in encoded
