"""Tests for batch-45 features: stopwords, compare_versions, get_history_summary."""
from __future__ import annotations

import pytest


# ── ExtractionConfig.stopwords ────────────────────────────────────────────────

class TestStopwordsFilter:
    @pytest.fixture
    def gen(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        return OntologyGenerator(use_ipfs_accelerate=False)

    def _ctx(self, stopwords=None):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            ExtractionConfig, OntologyGenerationContext, DataType, ExtractionStrategy,
        )
        cfg = ExtractionConfig(stopwords=stopwords or [])
        return OntologyGenerationContext(
            data_source="t", data_type=DataType.TEXT, domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED, config=cfg,
        )

    def test_stopword_filters_entity(self, gen):
        ctx = self._ctx(stopwords=["Alice"])
        result = gen.extract_entities("Alice and Bob went to London.", ctx)
        texts = [e.text.lower() for e in result.entities]
        assert "alice" not in texts

    def test_empty_stopwords_no_effect(self, gen):
        ctx_no_stop = self._ctx(stopwords=[])
        ctx_stop = self._ctx(stopwords=["Alice"])
        r1 = gen.extract_entities("Alice and Bob", ctx_no_stop)
        r2 = gen.extract_entities("Alice and Bob", ctx_stop)
        assert len(r1.entities) >= len(r2.entities)

    def test_stopwords_case_insensitive(self, gen):
        ctx = self._ctx(stopwords=["alice"])  # lowercase stop
        result = gen.extract_entities("Alice visited London.", ctx)
        texts = [e.text.lower() for e in result.entities]
        assert "alice" not in texts

    def test_to_dict_includes_stopwords(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(stopwords=["the", "a"])
        assert cfg.to_dict()["stopwords"] == ["the", "a"]

    def test_from_dict_reads_stopwords(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig.from_dict({"stopwords": ["is", "was"]})
        assert cfg.stopwords == ["is", "was"]

    def test_from_dict_defaults_to_empty(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        assert ExtractionConfig.from_dict({}).stopwords == []


# ── ExtractionConfig round-trip ───────────────────────────────────────────────

class TestExtractionConfigRoundTrip:
    def test_all_fields_survive_round_trip(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        original = ExtractionConfig(
            confidence_threshold=0.7,
            max_entities=50,
            max_relationships=20,
            window_size=8,
            include_properties=False,
            domain_vocab={"legal": ["contract", "party"]},
            custom_rules=[("\\bFoo\\b", "Concept")],
            llm_fallback_threshold=0.3,
            min_entity_length=3,
            stopwords=["the", "a"],
        )
        restored = ExtractionConfig.from_dict(original.to_dict())
        assert restored.confidence_threshold == original.confidence_threshold
        assert restored.max_entities == original.max_entities
        assert restored.max_relationships == original.max_relationships
        assert restored.window_size == original.window_size
        assert restored.include_properties == original.include_properties
        assert restored.domain_vocab == original.domain_vocab
        assert restored.llm_fallback_threshold == original.llm_fallback_threshold
        assert restored.min_entity_length == original.min_entity_length
        assert restored.stopwords == original.stopwords


# ── OntologyCritic.compare_versions ──────────────────────────────────────────

class TestCompareVersions:
    @pytest.fixture
    def critic(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        return OntologyCritic()

    @pytest.fixture
    def ctx(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerationContext, DataType, ExtractionStrategy,
        )
        return OntologyGenerationContext(
            data_source="t", data_type=DataType.TEXT, domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )

    def _ent(self, eid, text="entity", etype="T", props=None):
        e = {"id": eid, "text": text, "type": etype}
        if props:
            e["properties"] = props
        return e

    def test_returns_dict_with_delta_keys(self, critic, ctx):
        v1 = {"entities": [self._ent("e1")], "relationships": []}
        v2 = {"entities": [self._ent("e1"), self._ent("e2")], "relationships": []}
        result = critic.compare_versions(v1, v2, ctx)
        assert "delta_overall" in result
        assert "delta_completeness" in result

    def test_delta_overall_positive_for_richer_ontology(self, critic, ctx):
        v1 = {"entities": [self._ent("e1")], "relationships": []}
        v2 = {
            "entities": [self._ent(f"e{i}", props={"k": "v"}) for i in range(10)],
            "relationships": [{"id": "r1", "source_id": "e0", "target_id": "e1", "type": "rel"}],
        }
        result = critic.compare_versions(v1, v2, ctx)
        assert result["delta_overall"] > 0

    def test_delta_keys_sum_approximately(self, critic, ctx):
        v1 = {"entities": [self._ent("e1")], "relationships": []}
        v2 = {"entities": [self._ent("e1")], "relationships": []}
        result = critic.compare_versions(v1, v2, ctx)
        # Same ontologies → deltas should all be zero
        for key in ("delta_completeness", "delta_consistency", "delta_clarity"):
            assert abs(result[key]) < 1e-4


# ── OntologyOptimizer.get_history_summary ────────────────────────────────────

class TestGetHistorySummary:
    @pytest.fixture
    def optimizer(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
        return OntologyOptimizer()

    def test_empty_history_returns_zero_count(self, optimizer):
        s = optimizer.get_history_summary()
        assert s["count"] == 0
        assert s["mean_score"] == 0.0

    def test_summary_after_one_report(self, optimizer):
        # Inject a fake report via the internal _history list
        from unittest.mock import MagicMock
        r = MagicMock()
        r.average_score = 0.75
        r.improvement_rate = 0.05
        optimizer._history.append(r)
        s = optimizer.get_history_summary()
        assert s["count"] == 1
        assert s["mean_score"] == pytest.approx(0.75)
        assert s["std_score"] == 0.0

    def test_trend_improving(self, optimizer):
        from unittest.mock import MagicMock
        for score in [0.5, 0.6, 0.75]:
            r = MagicMock()
            r.average_score = score
            r.improvement_rate = 0.05
            optimizer._history.append(r)
        s = optimizer.get_history_summary()
        assert s["trend"] == "improving"

    def test_trend_degrading(self, optimizer):
        from unittest.mock import MagicMock
        for score in [0.8, 0.6, 0.5]:
            r = MagicMock()
            r.average_score = score
            r.improvement_rate = -0.05
            optimizer._history.append(r)
        s = optimizer.get_history_summary()
        assert s["trend"] == "degrading"

    def test_summary_keys_present(self, optimizer):
        s = optimizer.get_history_summary()
        for key in ("count", "mean_score", "std_score", "min_score", "max_score",
                    "mean_improvement_rate", "trend"):
            assert key in s
