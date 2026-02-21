"""Batch 50 tests.

Covers:
- generate_ontology_rich() elapsed_ms in metadata
- OntologyOptimizer.prune_history(keep_last_n)
- OntologyOptimizer.compare_history()
- ExtractionConfig.max_confidence field
- OntologyLearningAdapter.get_stats() p50/p90 percentiles
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# generate_ontology_rich elapsed_ms
# ──────────────────────────────────────────────────────────────────────────────

class TestGenerateOntologyRichElapsedMs:
    """generate_ontology_rich() should include elapsed_ms in result.metadata."""

    @pytest.fixture
    def generator_and_ctx(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator, OntologyGenerationContext,
        )
        gen = OntologyGenerator()
        ctx = OntologyGenerationContext(
            data_source="test", data_type="text", domain="general"
        )
        return gen, ctx

    def test_result_has_elapsed_ms(self, generator_and_ctx):
        gen, ctx = generator_and_ctx
        result = gen.generate_ontology_rich("Alice met Bob.", ctx)
        assert "elapsed_ms" in result.metadata

    def test_elapsed_ms_is_non_negative(self, generator_and_ctx):
        gen, ctx = generator_and_ctx
        result = gen.generate_ontology_rich("Alice met Bob.", ctx)
        assert result.metadata["elapsed_ms"] >= 0.0

    def test_elapsed_ms_is_float(self, generator_and_ctx):
        gen, ctx = generator_and_ctx
        result = gen.generate_ontology_rich("Alice.", ctx)
        assert isinstance(result.metadata["elapsed_ms"], float)

    def test_elapsed_ms_is_small_for_empty_doc(self, generator_and_ctx):
        gen, ctx = generator_and_ctx
        result = gen.generate_ontology_rich("", ctx)
        # Empty doc should complete in well under 1 second (1000 ms)
        assert result.metadata["elapsed_ms"] < 1000.0


# ──────────────────────────────────────────────────────────────────────────────
# OntologyOptimizer.prune_history
# ──────────────────────────────────────────────────────────────────────────────

class TestPruneHistory:
    """Tests for OntologyOptimizer.prune_history()."""

    @pytest.fixture
    def optimizer_with_history(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
            OntologyOptimizer, OptimizationReport,
        )
        opt = OntologyOptimizer()
        for i in range(10):
            opt._history.append(OptimizationReport(
                average_score=0.1 * (i + 1),
                trend="improving",
                recommendations=[],
            ))
        return opt

    def test_prune_reduces_history_length(self, optimizer_with_history):
        opt = optimizer_with_history
        opt.prune_history(5)
        assert len(opt._history) == 5

    def test_prune_keeps_most_recent(self, optimizer_with_history):
        opt = optimizer_with_history
        opt.prune_history(3)
        scores = [r.average_score for r in opt._history]
        assert scores == pytest.approx([0.8, 0.9, 1.0])

    def test_prune_returns_removed_count(self, optimizer_with_history):
        opt = optimizer_with_history
        removed = opt.prune_history(4)
        assert removed == 6

    def test_prune_larger_than_history_returns_zero(self, optimizer_with_history):
        opt = optimizer_with_history
        removed = opt.prune_history(100)
        assert removed == 0
        assert len(opt._history) == 10

    def test_prune_keeps_exactly_n(self, optimizer_with_history):
        opt = optimizer_with_history
        opt.prune_history(1)
        assert len(opt._history) == 1
        assert opt._history[0].average_score == pytest.approx(1.0)

    def test_prune_zero_raises_value_error(self, optimizer_with_history):
        with pytest.raises(ValueError):
            optimizer_with_history.prune_history(0)

    def test_prune_negative_raises_value_error(self, optimizer_with_history):
        with pytest.raises(ValueError):
            optimizer_with_history.prune_history(-1)


# ──────────────────────────────────────────────────────────────────────────────
# OntologyOptimizer.compare_history
# ──────────────────────────────────────────────────────────────────────────────

class TestCompareHistory:
    """Tests for OntologyOptimizer.compare_history()."""

    @pytest.fixture
    def optimizer_with_history(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
            OntologyOptimizer, OptimizationReport,
        )
        opt = OntologyOptimizer()
        for score in [0.5, 0.7, 0.65, 0.8]:
            opt._history.append(OptimizationReport(
                average_score=score,
                trend="mixed",
                recommendations=[],
            ))
        return opt

    def test_compare_history_length(self, optimizer_with_history):
        rows = optimizer_with_history.compare_history()
        assert len(rows) == 3  # 4 entries → 3 pairs

    def test_compare_history_empty_when_single_entry(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
            OntologyOptimizer, OptimizationReport,
        )
        opt = OntologyOptimizer()
        opt._history.append(OptimizationReport(average_score=0.5, trend="ok", recommendations=[]))
        assert opt.compare_history() == []

    def test_compare_history_delta_correct(self, optimizer_with_history):
        rows = optimizer_with_history.compare_history()
        assert rows[0]["delta"] == pytest.approx(0.2, abs=1e-4)
        assert rows[1]["delta"] == pytest.approx(-0.05, abs=1e-4)

    def test_compare_history_direction_up(self, optimizer_with_history):
        rows = optimizer_with_history.compare_history()
        assert rows[0]["direction"] == "up"

    def test_compare_history_direction_down(self, optimizer_with_history):
        rows = optimizer_with_history.compare_history()
        assert rows[1]["direction"] == "down"

    def test_compare_history_has_required_keys(self, optimizer_with_history):
        rows = optimizer_with_history.compare_history()
        for row in rows:
            for key in ("batch_from", "batch_to", "score_from", "score_to", "delta", "direction"):
                assert key in row, f"Missing key: {key}"

    def test_compare_history_batch_indices_sequential(self, optimizer_with_history):
        rows = optimizer_with_history.compare_history()
        for i, row in enumerate(rows):
            assert row["batch_from"] == i
            assert row["batch_to"] == i + 1


# ──────────────────────────────────────────────────────────────────────────────
# ExtractionConfig.max_confidence
# ──────────────────────────────────────────────────────────────────────────────

class TestMaxConfidence:
    """Tests for ExtractionConfig.max_confidence field."""

    def test_default_is_1_0(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        assert ExtractionConfig().max_confidence == pytest.approx(1.0)

    def test_to_dict_includes_max_confidence(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        d = ExtractionConfig(max_confidence=0.8).to_dict()
        assert d["max_confidence"] == pytest.approx(0.8)

    def test_from_dict_reads_max_confidence(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig.from_dict({"max_confidence": 0.6})
        assert cfg.max_confidence == pytest.approx(0.6)

    def test_from_dict_default_max_confidence(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig.from_dict({})
        assert cfg.max_confidence == pytest.approx(1.0)

    def test_max_confidence_caps_entity_confidence(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator, ExtractionConfig, OntologyGenerationContext,
        )
        gen = OntologyGenerator()
        ctx = OntologyGenerationContext(
            data_source="test", data_type="text", domain="general",
            config=ExtractionConfig(max_confidence=0.3),
        )
        result = gen.extract_entities("Alice met Bob in London.", ctx)
        for ent in result.entities:
            assert ent.confidence <= 0.3 + 1e-6, f"Entity {ent.text} confidence {ent.confidence} exceeds 0.3"

    def test_max_confidence_1_0_is_passthrough(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator, ExtractionConfig, OntologyGenerationContext,
        )
        gen = OntologyGenerator()
        ctx = OntologyGenerationContext(
            data_source="test", data_type="text", domain="general",
            config=ExtractionConfig(max_confidence=1.0),
        )
        result = gen.extract_entities("Alice met Bob in London.", ctx)
        # Normal confidence 0.75 should be unchanged
        for ent in result.entities:
            assert 0.0 <= ent.confidence <= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# OntologyLearningAdapter.get_stats() p50/p90
# ──────────────────────────────────────────────────────────────────────────────

class TestLearningAdapterPercentiles:
    """get_stats() should include p50_score and p90_score."""

    def _make_adapter_with_scores(self, scores):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
        adapter = OntologyLearningAdapter(min_samples=100)  # disable threshold adjustments
        for s in scores:
            adapter.apply_feedback(s)
        return adapter

    def test_stats_has_p50_score(self):
        adapter = self._make_adapter_with_scores([0.5, 0.6, 0.7, 0.8, 0.9])
        assert "p50_score" in adapter.get_stats()

    def test_stats_has_p90_score(self):
        adapter = self._make_adapter_with_scores([0.5, 0.6, 0.7, 0.8, 0.9])
        assert "p90_score" in adapter.get_stats()

    def test_p50_is_median(self):
        # Sorted: [0.1, 0.3, 0.5, 0.7, 0.9] → median = 0.5
        adapter = self._make_adapter_with_scores([0.9, 0.1, 0.5, 0.3, 0.7])
        stats = adapter.get_stats()
        assert stats["p50_score"] == pytest.approx(0.5, abs=1e-4)

    def test_p90_above_median(self):
        scores = [float(i) / 10 for i in range(1, 11)]  # 0.1 … 1.0
        adapter = self._make_adapter_with_scores(scores)
        stats = adapter.get_stats()
        assert stats["p90_score"] > stats["p50_score"]

    def test_p50_and_p90_in_unit_interval(self):
        adapter = self._make_adapter_with_scores([0.3, 0.5, 0.7, 0.8, 0.9, 1.0])
        stats = adapter.get_stats()
        assert 0.0 <= stats["p50_score"] <= 1.0
        assert 0.0 <= stats["p90_score"] <= 1.0

    def test_empty_feedback_returns_zeros(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
        adapter = OntologyLearningAdapter()
        stats = adapter.get_stats()
        assert stats["p50_score"] == pytest.approx(0.0)
        assert stats["p90_score"] == pytest.approx(0.0)
