"""Batch 58 tests.

Covers:
- OntologyGenerator.deduplicate_entities()
- OntologyGenerator.filter_entities()
- ExtractionConfig.merge()
- OntologyLearningAdapter.top_actions()
- OntologyOptimizer.score_trend_summary() + rolling_average_score()
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# OntologyGenerator.deduplicate_entities()
# ──────────────────────────────────────────────────────────────────────────────

class TestDeduplicateEntities:
    """deduplicate_entities() should merge entities with identical normalised text."""

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

    def _make_result(self, entities, relationships=None):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            Entity, Relationship, EntityExtractionResult,
        )
        ents = [Entity(id=e["id"], text=e["text"], type=e["type"],
                       confidence=e.get("confidence", 0.8)) for e in entities]
        rels = []
        for r in (relationships or []):
            rels.append(Relationship(id=r["id"], source_id=r["source_id"],
                                     target_id=r["target_id"], type=r["type"],
                                     confidence=0.7, direction="undirected"))
        return EntityExtractionResult(entities=ents, relationships=rels, confidence=0.8)

    def test_no_duplicates_unchanged(self, gen_ctx):
        gen, _ = gen_ctx
        result = self._make_result([
            {"id": "e1", "text": "Alice", "type": "Person"},
            {"id": "e2", "text": "Bob", "type": "Person"},
        ])
        dedup = gen.deduplicate_entities(result)
        assert len(dedup.entities) == 2

    def test_exact_duplicate_merged(self, gen_ctx):
        gen, _ = gen_ctx
        result = self._make_result([
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
            {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.7},
        ])
        dedup = gen.deduplicate_entities(result)
        assert len(dedup.entities) == 1

    def test_highest_confidence_kept(self, gen_ctx):
        gen, _ = gen_ctx
        result = self._make_result([
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.6},
            {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.9},
        ])
        dedup = gen.deduplicate_entities(result)
        assert dedup.entities[0].confidence == 0.9

    def test_case_insensitive_deduplication(self, gen_ctx):
        gen, _ = gen_ctx
        result = self._make_result([
            {"id": "e1", "text": "ALICE", "type": "Person", "confidence": 0.8},
            {"id": "e2", "text": "alice", "type": "Person", "confidence": 0.7},
        ])
        dedup = gen.deduplicate_entities(result)
        assert len(dedup.entities) == 1

    def test_metadata_reports_dedup_count(self, gen_ctx):
        gen, _ = gen_ctx
        result = self._make_result([
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
            {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.7},
        ])
        dedup = gen.deduplicate_entities(result)
        assert dedup.metadata.get("deduplication_count") == 1

    def test_relationships_remapped_after_dedup(self, gen_ctx):
        gen, _ = gen_ctx
        result = self._make_result(
            entities=[
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.7},
                {"id": "e3", "text": "Bob", "type": "Person", "confidence": 0.8},
            ],
            relationships=[
                {"id": "r1", "source_id": "e2", "target_id": "e3", "type": "knows"},
            ],
        )
        dedup = gen.deduplicate_entities(result)
        # e2 is removed, r1 should be remapped to e1→e3
        assert any(r.source_id == "e1" for r in dedup.relationships)


# ──────────────────────────────────────────────────────────────────────────────
# OntologyGenerator.filter_entities()
# ──────────────────────────────────────────────────────────────────────────────

class TestFilterEntities:
    """filter_entities() should apply post-extraction filters."""

    @pytest.fixture
    def gen_ctx(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator, OntologyGenerationContext,
        )
        return OntologyGenerator(), OntologyGenerationContext(
            data_source="test", data_type="text", domain="general"
        )

    def _make_result(self, entities, relationships=None):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            Entity, Relationship, EntityExtractionResult,
        )
        ents = [Entity(id=e["id"], text=e["text"], type=e["type"],
                       confidence=e.get("confidence", 0.8)) for e in entities]
        rels = []
        for r in (relationships or []):
            rels.append(Relationship(id=r["id"], source_id=r["source_id"],
                                     target_id=r["target_id"], type=r["type"],
                                     confidence=0.7, direction="undirected"))
        return EntityExtractionResult(entities=ents, relationships=rels, confidence=0.8)

    def test_min_confidence_filters_low(self, gen_ctx):
        gen, _ = gen_ctx
        result = self._make_result([
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
            {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.3},
        ])
        filtered = gen.filter_entities(result, min_confidence=0.7)
        assert len(filtered.entities) == 1
        assert filtered.entities[0].text == "Alice"

    def test_allowed_types_filters_type(self, gen_ctx):
        gen, _ = gen_ctx
        result = self._make_result([
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
            {"id": "e2", "text": "Acme", "type": "Organization", "confidence": 0.9},
        ])
        filtered = gen.filter_entities(result, allowed_types=["Person"])
        assert len(filtered.entities) == 1
        assert filtered.entities[0].type == "Person"

    def test_text_contains_filters_text(self, gen_ctx):
        gen, _ = gen_ctx
        result = self._make_result([
            {"id": "e1", "text": "Alice Smith", "type": "Person", "confidence": 0.9},
            {"id": "e2", "text": "Bob Jones", "type": "Person", "confidence": 0.9},
        ])
        filtered = gen.filter_entities(result, text_contains="alice")
        assert len(filtered.entities) == 1

    def test_no_criteria_keeps_all(self, gen_ctx):
        gen, _ = gen_ctx
        result = self._make_result([
            {"id": "e1", "text": "Alice", "type": "Person"},
            {"id": "e2", "text": "Bob", "type": "Person"},
        ])
        filtered = gen.filter_entities(result)
        assert len(filtered.entities) == 2

    def test_relationships_involving_removed_entities_dropped(self, gen_ctx):
        gen, _ = gen_ctx
        result = self._make_result(
            entities=[
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.3},
            ],
            relationships=[
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"},
            ],
        )
        filtered = gen.filter_entities(result, min_confidence=0.7)
        assert len(filtered.relationships) == 0  # r1 refs removed e2


# ──────────────────────────────────────────────────────────────────────────────
# ExtractionConfig.merge()
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractionConfigMerge:
    """merge() should overlay non-default values from other onto self."""

    def test_merge_returns_new_config(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        base = ExtractionConfig()
        override = ExtractionConfig()
        merged = base.merge(override)
        assert isinstance(merged, ExtractionConfig)
        assert merged is not base

    def test_override_confidence_threshold(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        base = ExtractionConfig(confidence_threshold=0.5)
        override = ExtractionConfig(confidence_threshold=0.8)
        merged = base.merge(override)
        assert merged.confidence_threshold == 0.8

    def test_base_value_kept_when_override_is_default(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        base = ExtractionConfig(max_entities=100)
        override = ExtractionConfig()  # max_entities stays default 0
        merged = base.merge(override)
        assert merged.max_entities == 100

    def test_override_multiple_fields(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        base = ExtractionConfig(confidence_threshold=0.5, window_size=5)
        override = ExtractionConfig(window_size=10, min_entity_length=3)
        merged = base.merge(override)
        assert merged.window_size == 10
        assert merged.min_entity_length == 3
        assert merged.confidence_threshold == 0.5  # not overridden


# ──────────────────────────────────────────────────────────────────────────────
# OntologyLearningAdapter.top_actions()
# ──────────────────────────────────────────────────────────────────────────────

class TestTopActions:
    """top_actions() should return N best-performing actions by mean success."""

    @pytest.fixture
    def adapter(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
            OntologyLearningAdapter,
        )
        a = OntologyLearningAdapter(domain="test")
        a.apply_feedback(final_score=0.9, actions=[{"action": "merge_duplicates"}])
        a.apply_feedback(final_score=0.5, actions=[{"action": "prune_orphans"}])
        a.apply_feedback(final_score=0.7, actions=[{"action": "add_missing_properties"}])
        return a

    def test_returns_list(self, adapter):
        top = adapter.top_actions(n=3)
        assert isinstance(top, list)

    def test_sorted_by_mean_success_descending(self, adapter):
        top = adapter.top_actions(n=3)
        scores = [t["mean_success"] for t in top]
        assert scores == sorted(scores, reverse=True)

    def test_top_1_is_best(self, adapter):
        top = adapter.top_actions(n=1)
        assert len(top) == 1
        assert top[0]["action"] == "merge_duplicates"

    def test_all_required_keys(self, adapter):
        for entry in adapter.top_actions():
            assert "action" in entry
            assert "count" in entry
            assert "mean_success" in entry

    def test_no_actions_returns_empty(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
            OntologyLearningAdapter,
        )
        a = OntologyLearningAdapter()
        assert a.top_actions() == []


# ──────────────────────────────────────────────────────────────────────────────
# OntologyOptimizer.score_trend_summary() + rolling_average_score()
# ──────────────────────────────────────────────────────────────────────────────

class TestScoreTrendAndRolling:
    """score_trend_summary() and rolling_average_score() should work correctly."""

    def _make_optimizer_with_scores(self, scores):
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
            OntologyOptimizer, OptimizationReport,
        )
        opt = OntologyOptimizer()
        for s in scores:
            r = MagicMock(spec=OptimizationReport)
            r.average_score = s
            opt._history.append(r)
        return opt

    def test_insufficient_data_with_zero_entries(self):
        opt = self._make_optimizer_with_scores([])
        assert opt.score_trend_summary() == "insufficient_data"

    def test_insufficient_data_with_one_entry(self):
        opt = self._make_optimizer_with_scores([0.5])
        assert opt.score_trend_summary() == "insufficient_data"

    def test_improving_trend(self):
        opt = self._make_optimizer_with_scores([0.3, 0.35, 0.7, 0.75])
        assert opt.score_trend_summary() == "improving"

    def test_degrading_trend(self):
        opt = self._make_optimizer_with_scores([0.8, 0.75, 0.4, 0.35])
        assert opt.score_trend_summary() == "degrading"

    def test_stable_trend(self):
        opt = self._make_optimizer_with_scores([0.5, 0.5, 0.5, 0.5])
        assert opt.score_trend_summary() == "stable"

    def test_rolling_average_last_2(self):
        opt = self._make_optimizer_with_scores([0.4, 0.6, 0.8, 1.0])
        avg = opt.rolling_average_score(2)
        assert abs(avg - 0.9) < 1e-9

    def test_rolling_average_clamps_to_history_length(self):
        opt = self._make_optimizer_with_scores([0.5, 0.7])
        avg = opt.rolling_average_score(100)
        assert abs(avg - 0.6) < 1e-9

    def test_rolling_average_empty_history_returns_zero(self):
        opt = self._make_optimizer_with_scores([])
        assert opt.rolling_average_score(3) == 0.0

    def test_rolling_average_raises_on_n_less_than_one(self):
        opt = self._make_optimizer_with_scores([0.5])
        with pytest.raises(ValueError, match="n must be >= 1"):
            opt.rolling_average_score(0)
