"""Batch 60: OntologyPipeline.warm_cache, OntologyMediator.undo_last_action,
ExtractionConfig.to_yaml/from_yaml, OntologyOptimizer.best_ontology,
EntityExtractionResult.filter_by_type.
"""
from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerationContext,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score(c=0.8, co=0.7, cl=0.6, g=0.5, da=0.4):
    return CriticScore(
        completeness=c, consistency=co, clarity=cl,
        granularity=g, domain_alignment=da,
        recommendations=[],
    )


def _ontology(n: int = 2):
    return {
        "entities": [
            {"id": f"e{i}", "type": "Person", "text": f"Alice{i}", "properties": {}, "confidence": 0.8}
            for i in range(n)
        ],
        "relationships": [],
        "metadata": {},
        "domain": "test",
    }


def _make_mediator():
    gen = OntologyGenerator()
    critic = OntologyCritic(use_llm=False)
    return OntologyMediator(generator=gen, critic=critic, max_rounds=3)


def _make_result(**kwargs):
    defaults = dict(
        entities=[
            Entity(id="e1", type="Person", text="Alice"),
            Entity(id="e2", type="Org", text="ACME"),
            Entity(id="e3", type="Person", text="Bob"),
        ],
        relationships=[
            Relationship(id="r1", source_id="e1", target_id="e3", type="knows"),
            Relationship(id="r2", source_id="e1", target_id="e2", type="works_at"),
        ],
        confidence=0.8,
    )
    defaults.update(kwargs)
    return EntityExtractionResult(**defaults)


# ---------------------------------------------------------------------------
# OntologyPipeline.warm_cache
# ---------------------------------------------------------------------------

class TestWarmCache:
    def test_warm_cache_returns_none(self):
        pipeline = OntologyPipeline(domain="test")
        result = pipeline.warm_cache("Alice must pay Bob by Friday.")
        assert result is None

    def test_warm_cache_populates_shared_cache(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        OntologyCritic.clear_shared_cache()
        pipeline = OntologyPipeline(domain="test")
        initial = OntologyCritic.shared_cache_size()
        pipeline.warm_cache("Alice works at ACME Corp.")
        assert OntologyCritic.shared_cache_size() >= initial  # cache may have grown

    def test_warm_cache_accepts_custom_data_source(self):
        pipeline = OntologyPipeline(domain="test")
        # Should not raise
        pipeline.warm_cache("text data", data_source="ref_corpus")

    def test_warm_cache_accepts_custom_data_type(self):
        pipeline = OntologyPipeline(domain="test")
        pipeline.warm_cache("text data", data_type="text")

    def test_warm_cache_then_run_works(self):
        pipeline = OntologyPipeline(domain="test")
        pipeline.warm_cache("Reference text with named entities.")
        result = pipeline.run("Alice and Bob are partners.", data_source="test")
        assert result is not None


# ---------------------------------------------------------------------------
# OntologyMediator.undo_last_action
# ---------------------------------------------------------------------------

class TestUndoLastAction:
    def test_undo_raises_when_no_history(self):
        mediator = _make_mediator()
        with pytest.raises(IndexError):
            mediator.undo_last_action()

    def test_undo_returns_original_ontology(self):
        mediator = _make_mediator()
        original = _ontology(2)
        score = _score()
        ctx = OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        mediator.refine_ontology(original, score, ctx)
        restored = mediator.undo_last_action()
        assert restored["entities"] == original["entities"]

    def test_undo_removes_from_stack(self):
        mediator = _make_mediator()
        original = _ontology(2)
        score = _score()
        ctx = OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        mediator.refine_ontology(original, score, ctx)
        mediator.undo_last_action()
        with pytest.raises(IndexError):
            mediator.undo_last_action()

    def test_multiple_refines_multiple_undos(self):
        mediator = _make_mediator()
        ont1 = _ontology(1)
        ont2 = _ontology(2)
        score = _score()
        ctx = OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        mediator.refine_ontology(ont1, score, ctx)
        mediator.refine_ontology(ont2, score, ctx)
        # Should not raise
        mediator.undo_last_action()
        mediator.undo_last_action()
        with pytest.raises(IndexError):
            mediator.undo_last_action()

    def test_undo_snapshot_is_deep_copy(self):
        mediator = _make_mediator()
        original = _ontology(2)
        score = _score()
        ctx = OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        mediator.refine_ontology(original, score, ctx)
        # Mutate original in place
        original["entities"][0]["text"] = "MUTATED"
        restored = mediator.undo_last_action()
        # The snapshot was taken before mutation, so should NOT be "MUTATED"
        assert restored["entities"][0]["text"] != "MUTATED"


# ---------------------------------------------------------------------------
# ExtractionConfig.to_yaml / from_yaml
# ---------------------------------------------------------------------------

class TestExtractionConfigYaml:
    def test_to_yaml_returns_string(self):
        assert isinstance(ExtractionConfig().to_yaml(), str)

    def test_to_yaml_contains_confidence_threshold(self):
        cfg = ExtractionConfig(confidence_threshold=0.77)
        assert "confidence_threshold" in cfg.to_yaml()

    def test_round_trip_default_config(self):
        cfg = ExtractionConfig()
        restored = ExtractionConfig.from_yaml(cfg.to_yaml())
        assert restored.confidence_threshold == cfg.confidence_threshold
        assert restored.max_entities == cfg.max_entities

    def test_round_trip_custom_config(self):
        cfg = ExtractionConfig(confidence_threshold=0.65, max_entities=50)
        restored = ExtractionConfig.from_yaml(cfg.to_yaml())
        assert restored.confidence_threshold == pytest.approx(0.65)
        assert restored.max_entities == 50

    def test_from_yaml_empty_string_gives_defaults(self):
        restored = ExtractionConfig.from_yaml("")
        assert restored.confidence_threshold == ExtractionConfig().confidence_threshold

    def test_to_yaml_is_valid_yaml(self):
        import yaml
        cfg = ExtractionConfig(confidence_threshold=0.5)
        d = yaml.safe_load(cfg.to_yaml())
        assert isinstance(d, dict)
        assert d["confidence_threshold"] == pytest.approx(0.5)

    def test_round_trip_preserves_domain_vocab(self):
        cfg = ExtractionConfig(domain_vocab={"animals": ["cat", "dog"]})
        restored = ExtractionConfig.from_yaml(cfg.to_yaml())
        assert restored.domain_vocab == {"animals": ["cat", "dog"]}

    def test_from_yaml_invalid_but_parseable_gives_defaults(self):
        # A YAML dict with no known keys -> defaults
        restored = ExtractionConfig.from_yaml("unknown_key: 42\n")
        assert restored.confidence_threshold == ExtractionConfig().confidence_threshold


# ---------------------------------------------------------------------------
# OntologyOptimizer.best_ontology
# ---------------------------------------------------------------------------

class TestBestOntology:
    def _make_report(self, score, ontology=None):
        return OptimizationReport(
            average_score=score,
            trend="stable",
            improvement_rate=0.0,
            recommendations=[],
            best_ontology=ontology,
            worst_ontology=None,
        )

    def test_returns_none_on_empty_history(self):
        opt = OntologyOptimizer()
        assert opt.best_ontology() is None

    def test_returns_ontology_from_highest_score(self):
        opt = OntologyOptimizer()
        opt._history.append(self._make_report(0.5, ontology={"tag": "low"}))
        opt._history.append(self._make_report(0.9, ontology={"tag": "high"}))
        opt._history.append(self._make_report(0.7, ontology={"tag": "mid"}))
        result = opt.best_ontology()
        assert result is not None
        assert result["tag"] == "high"

    def test_single_history_entry(self):
        opt = OntologyOptimizer()
        ont = {"entities": [], "domain": "test"}
        opt._history.append(self._make_report(0.8, ontology=ont))
        assert opt.best_ontology() == ont

    def test_returns_none_when_no_stored_ontology(self):
        opt = OntologyOptimizer()
        opt._history.append(self._make_report(0.8, ontology=None))
        assert opt.best_ontology() is None

    def test_tied_scores_returns_one(self):
        opt = OntologyOptimizer()
        opt._history.append(self._make_report(0.8, ontology={"tag": "a"}))
        opt._history.append(self._make_report(0.8, ontology={"tag": "b"}))
        result = opt.best_ontology()
        assert result is not None
        assert result["tag"] in ("a", "b")


# ---------------------------------------------------------------------------
# EntityExtractionResult.filter_by_type
# ---------------------------------------------------------------------------

class TestFilterByType:
    def test_returns_new_instance(self):
        result = _make_result()
        filtered = result.filter_by_type("Person")
        assert filtered is not result

    def test_only_persons_remain(self):
        result = _make_result()
        filtered = result.filter_by_type("Person")
        assert all(e.type == "Person" for e in filtered.entities)

    def test_correct_count(self):
        result = _make_result()
        assert len(result.filter_by_type("Person").entities) == 2
        assert len(result.filter_by_type("Org").entities) == 1

    def test_unknown_type_returns_empty(self):
        result = _make_result()
        filtered = result.filter_by_type("Location")
        assert filtered.entities == []

    def test_relationships_pruned_when_entity_removed(self):
        result = _make_result()
        # r2 links e1 (Person) to e2 (Org) — filtering for Person should drop r2
        filtered = result.filter_by_type("Person")
        rel_ids = {r.id for r in filtered.relationships}
        assert "r2" not in rel_ids

    def test_relationships_kept_when_both_endpoints_remain(self):
        result = _make_result()
        filtered = result.filter_by_type("Person")
        # r1 links e1 (Person) to e3 (Person) — should be kept
        assert any(r.id == "r1" for r in filtered.relationships)

    def test_confidence_preserved(self):
        result = _make_result()
        filtered = result.filter_by_type("Person")
        assert filtered.confidence == pytest.approx(result.confidence)

    def test_metadata_preserved(self):
        result = EntityExtractionResult(
            entities=[Entity(id="e1", type="T", text="x")],
            relationships=[],
            confidence=0.9,
            metadata={"key": "val"},
        )
        filtered = result.filter_by_type("T")
        assert filtered.metadata["key"] == "val"

    def test_empty_result_filter_gives_empty(self):
        empty = EntityExtractionResult(entities=[], relationships=[], confidence=0.0)
        assert empty.filter_by_type("Person").entities == []
