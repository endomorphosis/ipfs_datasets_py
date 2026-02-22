"""Tests for OntologyLearningAdapter (batch 31).

Covers: apply_feedback, get_extraction_hint, threshold adaptation,
per-action success rates, reset, and edge cases.
"""
from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    FeedbackRecord,
    OntologyLearningAdapter,
)


class TestOntologyLearningAdapterInit:
    def test_default_threshold_is_base_threshold(self):
        adapter = OntologyLearningAdapter(base_threshold=0.5)
        assert adapter.get_extraction_hint() == 0.5

    def test_custom_domain_stored(self):
        adapter = OntologyLearningAdapter(domain="legal")
        assert adapter.domain == "legal"

    def test_initial_stats_empty(self):
        adapter = OntologyLearningAdapter()
        stats = adapter.get_stats()
        assert stats["sample_count"] == 0
        assert stats["mean_score"] == 0.0
        assert stats["action_success_rates"] == {}


class TestApplyFeedback:
    def test_feedback_increments_sample_count(self):
        adapter = OntologyLearningAdapter(min_samples=10)
        adapter.apply_feedback(final_score=0.8)
        adapter.apply_feedback(final_score=0.7)
        assert adapter.get_stats()["sample_count"] == 2

    def test_feedback_updates_mean_score(self):
        adapter = OntologyLearningAdapter(min_samples=10)
        adapter.apply_feedback(final_score=0.6)
        adapter.apply_feedback(final_score=0.8)
        stats = adapter.get_stats()
        assert abs(stats["mean_score"] - 0.7) < 1e-9

    def test_feedback_clips_score_to_one(self):
        adapter = OntologyLearningAdapter(min_samples=10)
        adapter.apply_feedback(final_score=2.5)
        assert adapter._feedback[0].final_score == 1.0

    def test_feedback_clips_score_to_zero(self):
        adapter = OntologyLearningAdapter(min_samples=10)
        adapter.apply_feedback(final_score=-0.3)
        assert adapter._feedback[0].final_score == 0.0

    def test_action_types_recorded(self):
        adapter = OntologyLearningAdapter(min_samples=10)
        adapter.apply_feedback(
            final_score=0.9,
            actions=[{"action": "normalize_types"}, {"action": "add_properties"}],
        )
        stats = adapter.get_stats()
        assert "normalize_types" in stats["action_success_rates"]
        assert "add_properties" in stats["action_success_rates"]

    def test_action_success_rate_correct(self):
        adapter = OntologyLearningAdapter(min_samples=10)
        adapter.apply_feedback(final_score=0.8, actions=[{"action": "normalize_types"}])
        adapter.apply_feedback(final_score=0.4, actions=[{"action": "normalize_types"}])
        rates = adapter.get_stats()["action_success_rates"]
        expected = (0.8 + 0.4) / 2
        assert abs(rates["normalize_types"] - expected) < 1e-9

    def test_no_actions_is_valid(self):
        adapter = OntologyLearningAdapter(min_samples=10)
        adapter.apply_feedback(final_score=0.7, actions=[])
        assert adapter.get_stats()["sample_count"] == 1


class TestThresholdAdaptation:
    def test_threshold_decreases_after_high_scores(self):
        """High quality feedback should loosen threshold (lower value)."""
        adapter = OntologyLearningAdapter(base_threshold=0.5, min_samples=3, ema_alpha=1.0)
        initial = adapter.get_extraction_hint()
        for _ in range(3):
            adapter.apply_feedback(final_score=0.95)
        assert adapter.get_extraction_hint() < initial

    def test_threshold_increases_after_low_scores(self):
        """Low quality feedback should tighten threshold (higher value)."""
        adapter = OntologyLearningAdapter(base_threshold=0.5, min_samples=3, ema_alpha=1.0)
        initial = adapter.get_extraction_hint()
        for _ in range(3):
            adapter.apply_feedback(final_score=0.1)
        assert adapter.get_extraction_hint() > initial

    def test_threshold_clamped_to_01_09(self):
        adapter = OntologyLearningAdapter(min_samples=1, ema_alpha=1.0)
        # Push to extreme
        adapter.apply_feedback(final_score=0.0)
        assert 0.1 <= adapter.get_extraction_hint() <= 0.9
        adapter.reset()
        adapter.apply_feedback(final_score=1.0)
        assert 0.1 <= adapter.get_extraction_hint() <= 0.9

    def test_threshold_unchanged_below_min_samples(self):
        """Should not adjust threshold until min_samples are collected."""
        adapter = OntologyLearningAdapter(base_threshold=0.5, min_samples=5, ema_alpha=1.0)
        for _ in range(4):
            adapter.apply_feedback(final_score=0.01)
        # Extreme scores but min_samples not reached
        assert adapter.get_extraction_hint() == 0.5


class TestReset:
    def test_reset_clears_feedback(self):
        adapter = OntologyLearningAdapter()
        adapter.apply_feedback(final_score=0.8)
        adapter.reset()
        assert adapter.get_stats()["sample_count"] == 0

    def test_reset_restores_base_threshold(self):
        adapter = OntologyLearningAdapter(base_threshold=0.6, min_samples=1, ema_alpha=1.0)
        adapter.apply_feedback(final_score=1.0)
        adapter.reset()
        assert adapter.get_extraction_hint() == 0.6


class TestGetStats:
    def test_stats_has_expected_keys(self):
        adapter = OntologyLearningAdapter()
        stats = adapter.get_stats()
        for key in ("domain", "current_threshold", "base_threshold", "sample_count", "mean_score", "action_success_rates"):
            assert key in stats

    def test_stats_domain_matches(self):
        adapter = OntologyLearningAdapter(domain="medical")
        assert adapter.get_stats()["domain"] == "medical"


class TestPublicImport:
    def test_importable_from_graphrag_package(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyLearningAdapter, FeedbackRecord  # noqa: F401
        assert OntologyLearningAdapter is not None
        assert FeedbackRecord is not None
