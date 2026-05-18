"""Tests for F-logic frame-ontology audit metadata."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic.flogic_optimizer import (
    FLogicOptimizerConfig,
    FLogicSemanticOptimizer,
)


def test_flogic_optimizer_reports_frame_feature_keys_and_context_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:modal_family:temporal",
            "flogic:predicate_role:temporal_scope",
            "family:frame:1",
            "token:agency",
            "",
        ],
    )

    assert result.metadata["frame_feature_key_count"] == 4
    assert result.metadata["frame_feature_keys"] == [
        "family:frame:1",
        "flogic:modal_family:temporal",
        "flogic:predicate_role:temporal_scope",
        "token:agency",
    ]
    assert result.metadata["frame_audit_feature_key_count"] == 3
    assert result.metadata["frame_audit_feature_keys"] == [
        "family:frame:1",
        "flogic:modal_family:temporal",
        "flogic:predicate_role:temporal_scope",
    ]
    assert result.metadata["frame_ontology_terms"] == [
        "frame",
        "temporal",
        "temporal_scope",
    ]


def test_flogic_optimizer_tracks_fallback_surface_text_frame_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:fallback_surface_text:Housing voucher benefits and utility allowances",
            "flogic:fallback_surface_text_token_suffix:allowances",
        ],
    )

    assert result.metadata["frame_audit_feature_key_count"] == 2
    assert result.metadata["frame_ontology_term_count"] == 2
    assert result.metadata["frame_ontology_terms"] == [
        "allowances",
        "housing_voucher_benefits_utility_allowances",
    ]
