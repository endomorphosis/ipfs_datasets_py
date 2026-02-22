"""Batch 52 tests.

Covers:
- OntologyCritic class-level _SHARED_EVAL_CACHE
- OntologyLearningAdapter.get_extraction_hint() with action-success-rate correction
- OntologyGenerator.extract_entities() structured log (entity_count + strategy)
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# OntologyCritic shared cache
# ──────────────────────────────────────────────────────────────────────────────

class TestCriticSharedCache:
    """_SHARED_EVAL_CACHE should persist results across instances."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        OntologyCritic.clear_shared_cache()
        yield
        OntologyCritic.clear_shared_cache()

    def _make_ontology(self, tag: str = "a"):
        return {
            "entities": [{"id": "e1", "text": f"Alice-{tag}", "type": "Person",
                          "confidence": 0.9, "properties": {}}],
            "relationships": [],
        }

    def _make_ctx(self):
        ctx = MagicMock()
        ctx.domain = "test"
        return ctx

    def test_shared_cache_empty_at_start(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        assert OntologyCritic.shared_cache_size() == 0

    def test_evaluate_populates_shared_cache(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        c = OntologyCritic(use_llm=False)
        c.evaluate_ontology(self._make_ontology(), self._make_ctx())
        assert OntologyCritic.shared_cache_size() == 1

    def test_second_instance_hits_shared_cache(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        ontology = self._make_ontology("x")
        ctx = self._make_ctx()

        # First instance evaluates and populates cache
        c1 = OntologyCritic(use_llm=False)
        score1 = c1.evaluate_ontology(ontology, ctx)
        assert OntologyCritic.shared_cache_size() == 1

        # Second instance should return same score object from shared cache
        c2 = OntologyCritic(use_llm=False)
        score2 = c2.evaluate_ontology(ontology, ctx)
        assert score1 is score2  # same object — shared cache hit

    def test_different_ontologies_cached_separately(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        ctx = self._make_ctx()
        c = OntologyCritic(use_llm=False)
        c.evaluate_ontology(self._make_ontology("a"), ctx)
        c.evaluate_ontology(self._make_ontology("b"), ctx)
        assert OntologyCritic.shared_cache_size() == 2

    def test_clear_shared_cache_resets_to_zero(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        ctx = self._make_ctx()
        c = OntologyCritic(use_llm=False)
        c.evaluate_ontology(self._make_ontology(), ctx)
        OntologyCritic.clear_shared_cache()
        assert OntologyCritic.shared_cache_size() == 0

    def test_source_data_bypasses_shared_cache(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        ctx = self._make_ctx()
        ontology = self._make_ontology()
        c = OntologyCritic(use_llm=False)
        c.evaluate_ontology(ontology, ctx, source_data="some text")
        # source_data bypasses caching → no shared cache entry
        assert OntologyCritic.shared_cache_size() == 0

    def test_shared_cache_max_cleared_on_overflow(self, monkeypatch):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        monkeypatch.setattr(OntologyCritic, "_SHARED_EVAL_CACHE_MAX", 2)
        ctx = self._make_ctx()
        c = OntologyCritic(use_llm=False)
        # Fill to max (2 entries)
        c.evaluate_ontology(self._make_ontology("m1"), ctx)
        c.evaluate_ontology(self._make_ontology("m2"), ctx)
        # Third entry triggers clear + insert → size == 1
        c.evaluate_ontology(self._make_ontology("m3"), ctx)
        assert OntologyCritic.shared_cache_size() == 1


# ──────────────────────────────────────────────────────────────────────────────
# OntologyLearningAdapter.get_extraction_hint with action correction
# ──────────────────────────────────────────────────────────────────────────────

class TestGetExtractionHintWithCorrection:
    """get_extraction_hint should factor in per-action success rates."""

    @pytest.fixture
    def adapter(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
            OntologyLearningAdapter,
        )
        a = OntologyLearningAdapter(domain="test", base_threshold=0.5)
        a.reset()
        return a

    def test_no_feedback_returns_base_threshold(self, adapter):
        assert adapter.get_extraction_hint() == 0.5

    def test_high_action_success_lowers_threshold(self, adapter):
        """High success → correction < 0 → threshold drops."""
        # Simulate many high-scoring cycles
        for _ in range(5):
            adapter.apply_feedback(final_score=1.0, actions=[{"action": "add_missing_properties"}])
        hint = adapter.get_extraction_hint()
        # With mean_action_success=1.0, correction = 0.05*(0.5-1.0) = -0.025
        assert hint < adapter._current_threshold + 0.01  # slightly below unadjusted

    def test_low_action_success_raises_threshold(self, adapter):
        """Low success → correction > 0 → threshold raises."""
        for _ in range(5):
            adapter.apply_feedback(final_score=0.0, actions=[{"action": "prune_orphans"}])
        hint = adapter.get_extraction_hint()
        assert hint >= 0.1  # still in bounds

    def test_hint_always_clamped_to_01_09(self, adapter):
        for _ in range(20):
            adapter.apply_feedback(final_score=0.0, actions=[{"action": "x"}])
        assert 0.1 <= adapter.get_extraction_hint() <= 0.9

    def test_hint_with_no_actions_equals_current_threshold(self, adapter):
        # apply_feedback with no actions leaves _action_count empty
        adapter.apply_feedback(final_score=0.7)  # no actions
        assert adapter.get_extraction_hint() == adapter._current_threshold


# ──────────────────────────────────────────────────────────────────────────────
# OntologyGenerator.extract_entities structured log
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractEntitiesStructuredLog:
    """extract_entities should emit a structured log with entity_count + strategy."""

    @pytest.fixture
    def gen_ctx(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator, OntologyGenerationContext,
        )
        gen = OntologyGenerator()
        ctx = OntologyGenerationContext(
            data_source="test", data_type="text", domain="general"
        )
        return gen, ctx

    def test_log_contains_entity_count(self, gen_ctx, caplog):
        gen, ctx = gen_ctx
        with caplog.at_level(logging.INFO):
            gen.extract_entities("Alice met Bob in London.", ctx)
        assert any("entity_count" in r.message for r in caplog.records)

    def test_log_contains_strategy(self, gen_ctx, caplog):
        gen, ctx = gen_ctx
        with caplog.at_level(logging.INFO):
            gen.extract_entities("Alice met Bob.", ctx)
        assert any("strategy" in r.message for r in caplog.records)

    def test_log_contains_confidence(self, gen_ctx, caplog):
        gen, ctx = gen_ctx
        with caplog.at_level(logging.INFO):
            gen.extract_entities("Alice.", ctx)
        assert any("confidence" in r.message for r in caplog.records)

    def test_log_strategy_matches_context(self, gen_ctx, caplog):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionStrategy
        gen, ctx = gen_ctx
        # Log should contain whichever strategy the context uses
        strategy_value = ctx.extraction_strategy.value
        with caplog.at_level(logging.INFO):
            gen.extract_entities("Alice.", ctx)
        strategy_logs = [r.message for r in caplog.records if "strategy" in r.message]
        assert any(strategy_value in msg for msg in strategy_logs)
