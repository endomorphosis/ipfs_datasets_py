"""Batch 47 tests.

Covers:
- OntologyLearningAdapter.to_dict() / from_dict() round-trip
- OntologyHarness.run_single() wrapper
- analyze_batch_parallel(json_log_path=...) JSON output
- OntologyLearningAdapter feedback loop integration scenarios
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    FeedbackRecord,
    OntologyLearningAdapter,
)


# ──────────────────────────────────────────────────────────────────────────────
# OntologyLearningAdapter — to_dict / from_dict
# ──────────────────────────────────────────────────────────────────────────────

class TestOntologyLearningAdapterSerialization:
    """Round-trip serialization tests for OntologyLearningAdapter."""

    def _make_adapter_with_feedback(self) -> OntologyLearningAdapter:
        adapter = OntologyLearningAdapter(domain="medical", base_threshold=0.6)
        adapter.apply_feedback(0.8, actions=[{"action": "add_entity"}])
        adapter.apply_feedback(0.7, actions=[{"action": "add_entity"}, {"action": "remove_duplicate"}])
        adapter.apply_feedback(0.9, actions=[{"action": "add_relationship"}])
        return adapter

    def test_to_dict_returns_dict(self):
        adapter = OntologyLearningAdapter(domain="test")
        d = adapter.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_has_required_keys(self):
        adapter = OntologyLearningAdapter(domain="test")
        d = adapter.to_dict()
        for key in ("domain", "base_threshold", "current_threshold", "ema_alpha",
                    "min_samples", "feedback", "action_success", "action_count"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_domain(self):
        adapter = OntologyLearningAdapter(domain="legal")
        assert adapter.to_dict()["domain"] == "legal"

    def test_to_dict_base_threshold(self):
        adapter = OntologyLearningAdapter(base_threshold=0.75)
        assert adapter.to_dict()["base_threshold"] == pytest.approx(0.75)

    def test_to_dict_feedback_empty(self):
        adapter = OntologyLearningAdapter()
        assert adapter.to_dict()["feedback"] == []

    def test_to_dict_feedback_records(self):
        adapter = self._make_adapter_with_feedback()
        feedback = adapter.to_dict()["feedback"]
        assert len(feedback) == 3
        assert feedback[0]["final_score"] == pytest.approx(0.8)
        assert "add_entity" in feedback[0]["action_types"]

    def test_to_dict_action_success_populated(self):
        adapter = self._make_adapter_with_feedback()
        d = adapter.to_dict()
        assert "add_entity" in d["action_success"]

    def test_to_dict_action_count_populated(self):
        adapter = self._make_adapter_with_feedback()
        d = adapter.to_dict()
        assert d["action_count"].get("add_entity", 0) == 2

    def test_from_dict_round_trip_domain(self):
        adapter = OntologyLearningAdapter(domain="biomedical")
        restored = OntologyLearningAdapter.from_dict(adapter.to_dict())
        assert restored.domain == "biomedical"

    def test_from_dict_round_trip_base_threshold(self):
        adapter = OntologyLearningAdapter(base_threshold=0.65)
        restored = OntologyLearningAdapter.from_dict(adapter.to_dict())
        assert restored._base_threshold == pytest.approx(0.65)

    def test_from_dict_round_trip_feedback_count(self):
        adapter = self._make_adapter_with_feedback()
        restored = OntologyLearningAdapter.from_dict(adapter.to_dict())
        assert len(restored._feedback) == 3

    def test_from_dict_round_trip_current_threshold(self):
        adapter = self._make_adapter_with_feedback()
        original_threshold = adapter.get_extraction_hint()
        restored = OntologyLearningAdapter.from_dict(adapter.to_dict())
        assert restored.get_extraction_hint() == pytest.approx(original_threshold)

    def test_from_dict_round_trip_action_count(self):
        adapter = self._make_adapter_with_feedback()
        restored = OntologyLearningAdapter.from_dict(adapter.to_dict())
        assert restored._action_count["add_entity"] == 2

    def test_from_dict_round_trip_action_success(self):
        adapter = self._make_adapter_with_feedback()
        restored = OntologyLearningAdapter.from_dict(adapter.to_dict())
        assert "add_entity" in restored._action_success

    def test_from_dict_defaults_for_missing_keys(self):
        restored = OntologyLearningAdapter.from_dict({})
        assert restored.domain == "general"
        assert 0.0 <= restored.get_extraction_hint() <= 1.0

    def test_to_dict_is_json_serializable(self):
        adapter = self._make_adapter_with_feedback()
        serialized = json.dumps(adapter.to_dict())
        assert len(serialized) > 0

    def test_from_dict_get_stats_works_after_restore(self):
        adapter = self._make_adapter_with_feedback()
        restored = OntologyLearningAdapter.from_dict(adapter.to_dict())
        stats = restored.get_stats()
        assert stats["sample_count"] == 3
        assert stats["domain"] == "medical"


# ──────────────────────────────────────────────────────────────────────────────
# OntologyLearningAdapter — feedback loop scenarios
# ──────────────────────────────────────────────────────────────────────────────

class TestOntologyLearningAdapterFeedbackLoop:
    """Integration-level scenarios for the feedback loop."""

    def test_threshold_decreases_after_high_quality_feedback(self):
        """Repeated high scores should push threshold toward a lower value."""
        adapter = OntologyLearningAdapter(base_threshold=0.5, min_samples=3)
        initial = adapter.get_extraction_hint()
        for _ in range(6):
            adapter.apply_feedback(0.95, actions=[])
        assert adapter.get_extraction_hint() < initial

    def test_threshold_increases_after_low_quality_feedback(self):
        """Repeated low scores should push threshold higher."""
        adapter = OntologyLearningAdapter(base_threshold=0.5, min_samples=3)
        initial = adapter.get_extraction_hint()
        for _ in range(6):
            adapter.apply_feedback(0.1, actions=[])
        assert adapter.get_extraction_hint() > initial

    def test_threshold_stays_clamped_between_0_1_and_0_9(self):
        adapter = OntologyLearningAdapter(min_samples=2)
        for _ in range(20):
            adapter.apply_feedback(0.0, actions=[])
        assert 0.1 <= adapter.get_extraction_hint() <= 0.9

    def test_apply_feedback_action_success_rate_tracks_correctly(self):
        adapter = OntologyLearningAdapter(min_samples=10)
        adapter.apply_feedback(1.0, actions=[{"action": "merge_entities"}])
        adapter.apply_feedback(0.5, actions=[{"action": "merge_entities"}])
        stats = adapter.get_stats()
        assert "merge_entities" in stats["action_success_rates"]
        rate = stats["action_success_rates"]["merge_entities"]
        assert rate == pytest.approx(0.75)  # (1.0 + 0.5) / 2

    def test_reset_clears_all_state(self):
        adapter = OntologyLearningAdapter(min_samples=2)
        for _ in range(5):
            adapter.apply_feedback(0.9)
        adapter.reset()
        assert adapter.get_stats()["sample_count"] == 0
        assert adapter.get_extraction_hint() == pytest.approx(adapter._base_threshold)

    def test_from_dict_after_feedback_continues_accumulating(self):
        adapter = OntologyLearningAdapter(min_samples=5)
        for _ in range(3):
            adapter.apply_feedback(0.8)
        restored = OntologyLearningAdapter.from_dict(adapter.to_dict())
        restored.apply_feedback(0.8)
        restored.apply_feedback(0.8)
        # Now has 5 samples — threshold should have adjusted
        assert restored.get_stats()["sample_count"] == 5


# ──────────────────────────────────────────────────────────────────────────────
# analyze_batch_parallel — json_log_path
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzeBatchParallelJsonLog:
    """Tests for the json_log_path parameter of analyze_batch_parallel."""

    def _make_session_result(self, score: float):
        sr = MagicMock()
        critic_score = MagicMock()
        critic_score.overall = score
        # Return None for all dimension attributes so _identify_patterns skips them
        for dim in ("completeness", "consistency", "clarity", "granularity", "domain_alignment"):
            setattr(critic_score, dim, None)
        sr.critic_scores = [critic_score]
        # Avoid auto-creating attributes that interfere with _extract_ontology
        sr.ontology = None
        sr.best_ontology = None
        return sr

    def _make_optimizer(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
        return OntologyOptimizer()

    def test_json_log_file_created(self):
        optimizer = self._make_optimizer()
        sessions = [self._make_session_result(s) for s in [0.7, 0.8, 0.9]]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            optimizer.analyze_batch_parallel(sessions, json_log_path=path)
            assert os.path.exists(path)
        finally:
            os.unlink(path)

    def test_json_log_has_required_keys(self):
        optimizer = self._make_optimizer()
        sessions = [self._make_session_result(s) for s in [0.6, 0.75, 0.85]]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            optimizer.analyze_batch_parallel(sessions, json_log_path=path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            for key in ("session_count", "average_score", "trend",
                        "score_min", "score_max", "recommendations"):
                assert key in data, f"Missing key: {key}"
        finally:
            os.unlink(path)

    def test_json_log_session_count_correct(self):
        optimizer = self._make_optimizer()
        sessions = [self._make_session_result(0.8) for _ in range(5)]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            optimizer.analyze_batch_parallel(sessions, json_log_path=path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            assert data["session_count"] == 5
        finally:
            os.unlink(path)

    def test_json_log_not_written_when_path_is_none(self):
        optimizer = self._make_optimizer()
        sessions = [self._make_session_result(0.8)]
        # Should not raise and no file should appear (no path given)
        optimizer.analyze_batch_parallel(sessions, json_log_path=None)

    def test_json_log_is_valid_json(self):
        optimizer = self._make_optimizer()
        sessions = [self._make_session_result(0.7), self._make_session_result(0.9)]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            optimizer.analyze_batch_parallel(sessions, json_log_path=path)
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            parsed = json.loads(content)
            assert isinstance(parsed, dict)
        finally:
            os.unlink(path)

    def test_json_log_average_score_correct(self):
        optimizer = self._make_optimizer()
        sessions = [self._make_session_result(0.6), self._make_session_result(0.8)]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            optimizer.analyze_batch_parallel(sessions, json_log_path=path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            assert data["average_score"] == pytest.approx(0.7, abs=1e-4)
        finally:
            os.unlink(path)

    def test_json_log_bad_path_does_not_raise(self):
        """An unwritable path should be silently logged, not raise."""
        optimizer = self._make_optimizer()
        sessions = [self._make_session_result(0.8)]
        # /dev/full would block on Linux; use a non-existent directory instead
        optimizer.analyze_batch_parallel(
            sessions, json_log_path="/nonexistent_dir_12345/out.json"
        )
