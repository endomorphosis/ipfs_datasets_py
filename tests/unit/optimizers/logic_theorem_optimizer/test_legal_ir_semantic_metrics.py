"""Tests for LegalIR semantic-equivalence promotion metrics."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_semantic_metrics import (
    COUNTEREXAMPLE_EQUIVALENCE,
    DECOMPILER_ROUND_TRIP_PRESERVATION,
    GRAPH_ISOMORPHISM,
    LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION,
    OBLIGATION_EQUIVALENCE,
    PROOF_OBLIGATION_DELTA,
    PROOF_OBLIGATION_DELTA_SCORE,
    SEMANTIC_EQUIVALENCE_METRICS,
    STRUCTURAL_EQUIVALENCE,
    TEMPORAL_WINDOW_AGREEMENT,
    SemanticEquivalenceConfig,
    compare_legal_ir_semantic_equivalence,
    evaluate_legal_ir_semantic_equivalence,
    semantic_equivalence_from_metrics,
    semantic_equivalence_promotion_gate,
)


def _reference_ir() -> dict:
    return {
        "rules": [
            {
                "id": "rule-a",
                "modality": "obligation",
                "subject": "Agency",
                "action": "provide notice",
                "condition": "within 30 days",
                "proof_obligation_ids": ["po-notice"],
                "temporal_window": {"start": "2026-01-01", "duration": "30 days"},
            }
        ],
        "graph": {
            "nodes": [
                {"id": "n1", "label": "Agency", "type": "actor"},
                {"id": "n2", "label": "Notice", "type": "document"},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "label": "must_provide"},
            ],
        },
        "counterexamples": [{"assignment": {"notice": False}, "violates": "po-notice"}],
        "round_trip": {
            "decompiled": "O(agency, provide_notice)",
            "recompiled_ir": "O(agency, provide_notice)",
        },
    }


def _isomorphic_ir() -> dict:
    return {
        "rules": [
            {
                "id": "renumbered",
                "modality": "obligation",
                "subject": "Agency",
                "action": "provide notice",
                "condition": "within 30 days",
                "proof_obligation_ids": ["po-notice"],
                "temporal_window": {"start": "2026-01-01", "duration": "30 days"},
            }
        ],
        "graph": {
            "nodes": [
                {"id": "x", "label": "Notice", "type": "document"},
                {"id": "y", "label": "Agency", "type": "actor"},
            ],
            "edges": [
                {"source": "y", "target": "x", "label": "must_provide"},
            ],
        },
        "counterexamples": [{"assignment": {"notice": False}, "violates": "po-notice"}],
        "round_trip": {
            "decompiled": "O(agency, provide_notice)",
            "recompiled_ir": "O(agency, provide_notice)",
        },
    }


def _regressed_ir() -> dict:
    changed = _isomorphic_ir()
    changed["rules"][0].update(
        {
            "modality": "permission",
            "condition": "within 60 days",
            "proof_obligation_ids": ["po-permit"],
            "temporal_window": {"start": "2026-01-01", "duration": "60 days"},
        }
    )
    changed["graph"]["edges"][0]["label"] = "may_provide"
    changed["counterexamples"] = [
        {"assignment": {"notice": True}, "violates": "po-permit"}
    ]
    changed["round_trip"]["recompiled_ir"] = "P(agency, provide_notice)"
    return changed


def _all_semantic_scores(score: float = 1.0) -> dict[str, float]:
    values = {metric: score for metric in SEMANTIC_EQUIVALENCE_METRICS}
    values[PROOF_OBLIGATION_DELTA] = 0.0 if score == 1.0 else 1.0
    return values


def test_raw_ir_pair_scores_semantic_equivalence_beyond_ids_and_order() -> None:
    result = evaluate_legal_ir_semantic_equivalence(
        _reference_ir(),
        _isomorphic_ir(),
        family="deontic",
    )

    assert result.complete is True
    assert result.scores[STRUCTURAL_EQUIVALENCE] == pytest.approx(1.0)
    assert result.scores[OBLIGATION_EQUIVALENCE] == pytest.approx(1.0)
    assert result.scores[COUNTEREXAMPLE_EQUIVALENCE] == pytest.approx(1.0)
    assert result.scores[GRAPH_ISOMORPHISM] == pytest.approx(1.0)
    assert result.scores[TEMPORAL_WINDOW_AGREEMENT] == pytest.approx(1.0)
    assert result.scores[DECOMPILER_ROUND_TRIP_PRESERVATION] == pytest.approx(1.0)
    assert result.scores[PROOF_OBLIGATION_DELTA_SCORE] == pytest.approx(1.0)
    assert result.raw_deltas[PROOF_OBLIGATION_DELTA] == pytest.approx(0.0)


def test_semantic_metrics_detect_obligation_graph_temporal_and_proof_delta() -> None:
    result = evaluate_legal_ir_semantic_equivalence(
        _reference_ir(),
        _regressed_ir(),
        family="deontic",
    )

    assert result.scores[OBLIGATION_EQUIVALENCE] < 1.0
    assert result.scores[COUNTEREXAMPLE_EQUIVALENCE] < 1.0
    assert result.scores[GRAPH_ISOMORPHISM] < 1.0
    assert result.scores[TEMPORAL_WINDOW_AGREEMENT] < 1.0
    assert result.scores[DECOMPILER_ROUND_TRIP_PRESERVATION] < 1.0
    assert result.scores[PROOF_OBLIGATION_DELTA_SCORE] == pytest.approx(0.0)
    assert result.raw_deltas[PROOF_OBLIGATION_DELTA] == pytest.approx(2.0)


def test_explicit_metric_payload_accepts_delta_alias_and_fails_closed_on_missing() -> None:
    complete = semantic_equivalence_from_metrics(
        {
            **_all_semantic_scores(),
            "proof_obligation_delta_count": 0,
        },
        family="kg",
    )
    incomplete = semantic_equivalence_from_metrics(
        {
            STRUCTURAL_EQUIVALENCE: 1.0,
            OBLIGATION_EQUIVALENCE: 1.0,
        },
        family="kg",
    )

    assert complete.family == "knowledge_graphs"
    assert complete.missing_metrics == ()
    assert incomplete.missing_metrics == (
        COUNTEREXAMPLE_EQUIVALENCE,
        GRAPH_ISOMORPHISM,
        TEMPORAL_WINDOW_AGREEMENT,
        DECOMPILER_ROUND_TRIP_PRESERVATION,
        PROOF_OBLIGATION_DELTA_SCORE,
    )


def test_comparison_reports_disagreement_when_ce_cosine_improve_but_semantics_regress() -> None:
    baseline = {
        "view_family_metrics": {
            "deontic": {
                **_all_semantic_scores(),
                "autoencoder_cross_entropy_loss": 0.80,
                "autoencoder_cosine_similarity": 0.70,
                "ir_cross_entropy_loss": 0.85,
                "ir_cosine_similarity": 0.68,
            }
        }
    }
    candidate = {
        "view_family_metrics": {
            "deontic": {
                **_all_semantic_scores(),
                OBLIGATION_EQUIVALENCE: 0.50,
                "autoencoder_cross_entropy_loss": 0.30,
                "autoencoder_cosine_similarity": 0.90,
                "ir_cross_entropy_loss": 0.35,
                "ir_cosine_similarity": 0.88,
            }
        }
    }

    report = compare_legal_ir_semantic_equivalence(
        baseline,
        candidate,
        config=SemanticEquivalenceConfig(families=("deontic",)),
    )
    payload = report.to_dict()

    assert report.accepted is False
    assert report.schema_version == LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION
    assert report.disagreements == (
        "deontic:ce_cosine_improved_semantic_equivalence_regressed",
    )
    assert "deontic:ce_cosine_semantic_disagreement" in report.block_reasons
    assert payload["family_results"]["deontic"]["disagreement"] is True


def test_raw_family_payload_can_drive_hard_promotion_gate() -> None:
    baseline = {
        "view_family_metrics": {
            "deontic": {
                "reference_ir": _reference_ir(),
                "candidate_ir": _isomorphic_ir(),
                "autoencoder_cross_entropy_loss": 0.80,
                "autoencoder_cosine_similarity": 0.70,
            }
        }
    }
    candidate = {
        "view_family_metrics": {
            "deontic": {
                "reference_ir": _reference_ir(),
                "candidate_ir": _regressed_ir(),
                "autoencoder_cross_entropy_loss": 0.30,
                "autoencoder_cosine_similarity": 0.90,
            }
        }
    }

    gate = semantic_equivalence_promotion_gate(
        baseline,
        candidate,
        config=SemanticEquivalenceConfig(families=("deontic",)),
    )

    assert gate["accepted"] is False
    assert gate["hard_promotion_gate"] is True
    assert gate["failed_families"] == ["deontic"]
    assert "deontic:semantic_equivalence_regressed" in gate["block_reasons"]
