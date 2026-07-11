import json

import pytest

from ipfs_datasets_py.logic.modal import (
    INTROSPECTION_ANALYSIS_CONFIG_VERSION,
    INTROSPECTION_ANALYSIS_SCHEMA_VERSION,
    REQUIRED_LEGAL_IR_GAP_FAMILIES,
    IntrospectionAnalysisConfig,
    IntrospectionAnalysisSchemaError,
    LegalIRGapAnalysis,
    analysis_to_json,
    analyze_introspection_disagreements,
    cluster_legal_ir_disagreements,
    cluster_legal_ir_gaps,
    normalize_legal_ir_gaps,
)


def _packet(
    evidence_id: str,
    *,
    sample_id: str = "sample-1",
    target_family: str = "deontic",
    predicted_family: str = "temporal",
    raw_deontic_gap: float = 0.4,
    heldout: float = 0.2,
    confidence: float = 0.8,
    proof_failure: float = 0.0,
):
    return {
        "evidence_id": evidence_id,
        "heldout_impact_by_surface": {
            "TDFOL.prover": min(1.0, heldout + 0.05),
            "deontic.ir": heldout,
            "external_provers.router": min(1.0, heldout + 0.1),
            "knowledge_graphs.neo4j_compat": max(0.0, heldout - 0.05),
            "modal.frame_logic": heldout,
            "modal.ir_decompiler": max(0.0, heldout - 0.02),
            "modal.source_provenance": heldout,
            "modal.temporal": heldout,
            "event_calculus.core": heldout,
        },
        "legal_ir_component_gaps": {
            "TDFOL.prover.quantifier_scope": 0.31,
            "deontic.ir.obligation_scope": raw_deontic_gap,
            "event_calculus.fluent_interval": 0.33,
            "knowledge_graphs.neo4j_compat.edge_role": 0.28,
            "modal.frame_logic.slot_alignment": 0.35,
            "modal.source_provenance.span_hash": 0.22,
            "modal.temporal.deadline_order": 0.27,
        },
        "legal_ir_views": {
            "canonical": {"family_distribution": {target_family: 1.0}},
            "predicted": {
                "family_distribution": {
                    predicted_family: confidence,
                    target_family: max(0.0, 1.0 - confidence),
                },
                "predicted_family": predicted_family,
                "target_family": target_family,
            },
        },
        "compiler_round_trip_gaps": {
            "component_gaps": {},
            "reconstruction_loss": 0.18,
            "source_decompiled_text_embedding_cosine_loss": 0.24,
            "source_decompiled_text_token_loss": 0.26,
        },
        "per_family_gaps": [
            {
                "family": "deontic",
                "probability_gap": 0.7,
                "predicted_probability": 1.0 - confidence,
                "target_probability": 1.0,
            }
        ],
        "proof_route_status": {
            "attempted_count": 2,
            "compiles": proof_failure == 0.0,
            "failure_ratio": proof_failure,
            "route_status": "failed" if proof_failure else "compiled",
            "valid_count": 2 if proof_failure == 0.0 else 1,
        },
        "sample_hashes": {"sample_id": sample_id},
    }


def test_normalize_legal_ir_gaps_covers_required_families_and_surfaces():
    packet = _packet("evidence-all-families", proof_failure=0.5)
    packet["anti_copy"] = {"anti_copy_penalty": 0.2, "source_span_copy_ratio": 0.1}

    gaps = normalize_legal_ir_gaps(packet)
    families = {gap.semantic_family for gap in gaps}

    assert set(REQUIRED_LEGAL_IR_GAP_FAMILIES).issubset(families)
    assert {gap.schema_version for gap in gaps} == {INTROSPECTION_ANALYSIS_SCHEMA_VERSION}
    assert all(gap.gap_id == gap.expected_gap_id() for gap in gaps)
    assert all(gap.owned_code_paths for gap in gaps)
    assert any(
        gap.semantic_family == "decompiler"
        and gap.compiler_surface == "modal.ir_decompiler"
        and gap.metric_name == "source_decompiled_text_token_loss"
        for gap in gaps
    )
    assert any(
        gap.semantic_family == "prover"
        and gap.compiler_surface == "external_provers.router"
        and gap.formal_severity == 1.0
        for gap in gaps
    )


def test_clusters_repeat_by_semantic_signature_and_owned_surface():
    first = _packet(
        "evidence-repeat-1",
        sample_id="sample-a",
        raw_deontic_gap=0.4,
        heldout=0.7,
        confidence=0.9,
    )
    second = _packet(
        "evidence-repeat-2",
        sample_id="sample-b",
        raw_deontic_gap=0.2,
        heldout=0.75,
        confidence=0.88,
    )
    different_surface_same_family = {
        "evidence_id": "evidence-frame",
        "heldout_impact_by_surface": {"modal.frame_logic": 0.9},
        "legal_ir_component_gaps": {"modal.frame_logic.obligation_scope": 0.5},
        "predicted_family": "temporal",
        "sample_id": "sample-c",
        "target_family": "deontic",
    }

    gaps = []
    for packet in (first, second, different_surface_same_family):
        gaps.extend(normalize_legal_ir_gaps(packet))
    deontic_obligation = [
        gap
        for gap in gaps
        if gap.semantic_signature.endswith("obligation_scope")
        and gap.compiler_surface == "deontic.ir"
    ]

    clusters = cluster_legal_ir_gaps(gaps)
    repeated = [
        cluster
        for cluster in clusters
        if cluster.compiler_surface == "deontic.ir"
        and cluster.semantic_signature == deontic_obligation[0].semantic_signature
    ][0]
    frame_clusters = [
        cluster
        for cluster in clusters
        if cluster.compiler_surface == "modal.frame_logic"
        and cluster.semantic_signature.endswith("obligation_scope")
    ]

    assert repeated.recurrence == 2
    assert repeated.evidence_ids == ("evidence-repeat-1", "evidence-repeat-2")
    assert repeated.sample_ids == ("sample-a", "sample-b")
    assert frame_clusters
    assert frame_clusters[0].semantic_signature.endswith("obligation_scope")
    assert frame_clusters[0].semantic_family == "frame_logic"
    assert frame_clusters[0].compiler_surface != repeated.compiler_surface


def test_cluster_ranking_uses_impact_recurrence_confidence_and_severity_not_raw_loss():
    high_raw_low_impact = {
        "evidence_id": "raw-loss-only",
        "heldout_impact_by_surface": {"modal.ir_decompiler": 0.01},
        "legal_ir_component_gaps": {"modal.ir_decompiler.reconstruction": 5.0},
        "sample_id": "raw-loss-only-sample",
        "confidence": 0.1,
    }
    recurring_formal = [
        {
            "evidence_id": f"formal-{index}",
            "heldout_impact_by_surface": {"external_provers.router": 0.85},
            "proof_route_status": {
                "attempted_count": 4,
                "compiles": False,
                "failure_ratio": 0.25,
                "route_status": "failed",
                "valid_count": 3,
            },
            "sample_id": f"formal-sample-{index}",
            "confidence": 0.92,
        }
        for index in range(3)
    ]

    analysis = analyze_introspection_disagreements([high_raw_low_impact, *recurring_formal])
    top = analysis.clusters[0]

    assert top.compiler_surface == "external_provers.router"
    assert top.recurrence == 3
    assert top.max_raw_loss < 5.0
    assert top.ranking_breakdown["heldout_impact"] == 0.85
    assert top.ranking_breakdown["recurrence_norm"] == 1.0


def test_analysis_output_is_stable_versioned_json():
    config = IntrospectionAnalysisConfig(max_gaps_per_cluster=4)
    analysis = analyze_introspection_disagreements(
        [_packet("stable-a"), _packet("stable-b", sample_id="sample-2")],
        config=config,
    )
    encoded = analysis_to_json(analysis)
    again = analysis_to_json(
        analyze_introspection_disagreements(
            [_packet("stable-a"), _packet("stable-b", sample_id="sample-2")],
            config=config,
        )
    )
    payload = json.loads(encoded)

    assert encoded == again
    assert payload["schema_version"] == INTROSPECTION_ANALYSIS_SCHEMA_VERSION
    assert payload["config"]["config_version"] == INTROSPECTION_ANALYSIS_CONFIG_VERSION
    assert payload["required_gap_families"] == list(REQUIRED_LEGAL_IR_GAP_FAMILIES)
    assert payload["clusters"][0]["cluster_id"].startswith("lir-cluster-")
    assert LegalIRGapAnalysis(
        clusters=analysis.clusters,
        gaps=analysis.gaps,
        config=config,
    ).to_json() == encoded


def test_cluster_records_alias_and_unknown_config_fail_closed():
    clusters = cluster_legal_ir_disagreements([_packet("alias-a"), _packet("alias-b")])

    assert clusters
    with pytest.raises(IntrospectionAnalysisSchemaError, match="config_version"):
        IntrospectionAnalysisConfig.from_mapping(
            {"config_version": "legal-ir-introspection-analysis-config-v999"}
        )
