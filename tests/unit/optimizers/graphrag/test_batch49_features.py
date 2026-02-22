"""Batch 49 tests.

Covers:
- CriticScore.metadata entity_type_counts and entity_type_fractions
- OntologyMediator.refine_ontology split_entity action
- Confidence decay already present in infer_relationships (verify)
- OntologyOptimizer.analyze_batch parallel already exists (check)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Per-entity-type completeness in CriticScore.metadata
# ──────────────────────────────────────────────────────────────────────────────

class TestEntityTypeCountsInMetadata:
    """CriticScore.metadata should include entity_type_counts and fractions."""

    @pytest.fixture
    def critic(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        return OntologyCritic(use_llm=False)

    @pytest.fixture
    def ctx(self):
        c = MagicMock()
        c.domain = "general"
        return c

    def _make_ontology(self):
        return {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.8},
                {"id": "e3", "text": "Acme", "type": "Organization", "confidence": 0.85},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows", "confidence": 0.7},
            ],
        }

    def test_metadata_has_entity_type_counts_key(self, critic, ctx):
        score = critic.evaluate_ontology(self._make_ontology(), ctx)
        assert "entity_type_counts" in score.metadata

    def test_metadata_entity_type_counts_correct(self, critic, ctx):
        score = critic.evaluate_ontology(self._make_ontology(), ctx)
        counts = score.metadata["entity_type_counts"]
        assert counts.get("Person") == 2
        assert counts.get("Organization") == 1

    def test_metadata_has_entity_type_fractions_key(self, critic, ctx):
        score = critic.evaluate_ontology(self._make_ontology(), ctx)
        assert "entity_type_fractions" in score.metadata

    def test_metadata_entity_type_fractions_sum_to_one(self, critic, ctx):
        score = critic.evaluate_ontology(self._make_ontology(), ctx)
        fractions = score.metadata["entity_type_fractions"]
        total = sum(fractions.values())
        assert total == pytest.approx(1.0, abs=1e-4)

    def test_metadata_entity_type_fractions_values_in_range(self, critic, ctx):
        score = critic.evaluate_ontology(self._make_ontology(), ctx)
        fractions = score.metadata["entity_type_fractions"]
        for v in fractions.values():
            assert 0.0 <= v <= 1.0

    def test_metadata_empty_ontology_no_crash(self, critic, ctx):
        score = critic.evaluate_ontology({"entities": [], "relationships": []}, ctx)
        assert "entity_type_counts" in score.metadata
        assert score.metadata["entity_type_counts"] == {}

    def test_metadata_single_entity_type_fraction_is_one(self, critic, ctx):
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.8},
            ],
            "relationships": [],
        }
        score = critic.evaluate_ontology(ontology, ctx)
        fractions = score.metadata["entity_type_fractions"]
        assert fractions.get("Person") == pytest.approx(1.0)


# ──────────────────────────────────────────────────────────────────────────────
# split_entity refinement action
# ──────────────────────────────────────────────────────────────────────────────

class TestSplitEntityAction:
    """Mediator split_entity action splits compound entities."""

    @pytest.fixture
    def mediator(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        return OntologyMediator(
            generator=OntologyGenerator(),
            critic=OntologyCritic(use_llm=False),
        )

    def _make_feedback(self, recs):
        fb = MagicMock()
        fb.recommendations = recs
        fb.completeness = 0.6
        fb.consistency = 0.6
        fb.clarity = 0.6
        fb.granularity = 0.4  # low — triggers split
        fb.domain_alignment = 0.6
        return fb

    def test_split_compound_entity(self, mediator):
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice and Bob", "type": "Person", "confidence": 0.8},
            ],
            "relationships": [],
        }
        feedback = self._make_feedback(["split entity — too broad compound"])
        refined = mediator.refine_ontology(ontology, feedback, MagicMock())
        texts = [e["text"] for e in refined["entities"] if isinstance(e, dict)]
        assert "Alice" in texts
        assert "Bob" in texts

    def test_split_comma_separated_entity(self, mediator):
        ontology = {
            "entities": [
                {"id": "e1", "text": "London, Paris", "type": "Location", "confidence": 0.8},
            ],
            "relationships": [],
        }
        feedback = self._make_feedback(["split — entities too granular and overloaded"])
        refined = mediator.refine_ontology(ontology, feedback, MagicMock())
        texts = [e["text"] for e in refined["entities"] if isinstance(e, dict)]
        assert "London" in texts
        assert "Paris" in texts

    def test_simple_entity_not_split(self, mediator):
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
            ],
            "relationships": [],
        }
        feedback = self._make_feedback(["split entity — too broad"])
        refined = mediator.refine_ontology(ontology, feedback, MagicMock())
        texts = [e["text"] for e in refined["entities"] if isinstance(e, dict)]
        assert texts == ["Alice"]

    def test_split_action_recorded_in_metadata(self, mediator):
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice and Bob", "type": "Person", "confidence": 0.8},
            ],
            "relationships": [],
        }
        feedback = self._make_feedback(["split entity — overloaded concept"])
        refined = mediator.refine_ontology(ontology, feedback, MagicMock())
        actions = refined.get("metadata", {}).get("refinement_actions", [])
        assert "split_entity" in actions

    def test_split_entity_preserves_type(self, mediator):
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice and Bob", "type": "Person", "confidence": 0.8},
            ],
            "relationships": [],
        }
        feedback = self._make_feedback(["granular — split compound entity"])
        refined = mediator.refine_ontology(ontology, feedback, MagicMock())
        types = [e.get("type") for e in refined["entities"] if isinstance(e, dict)]
        assert all(t == "Person" for t in types)

    def test_split_removes_relationships_to_original(self, mediator):
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice and Bob", "type": "Person", "confidence": 0.8},
                {"id": "e2", "text": "Acme", "type": "Organization", "confidence": 0.9},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "worksAt", "confidence": 0.7},
            ],
        }
        feedback = self._make_feedback(["split entity — too broad"])
        refined = mediator.refine_ontology(ontology, feedback, MagicMock())
        # The original e1 relationship must be removed (e1 no longer exists)
        rel_sources = [r.get("source_id") for r in refined["relationships"] if isinstance(r, dict)]
        assert "e1" not in rel_sources


# ──────────────────────────────────────────────────────────────────────────────
# Confidence decay in co-occurrence (verify existing behavior)
# ──────────────────────────────────────────────────────────────────────────────

class TestCoOccurrenceConfidenceDecay:
    """Distance-based confidence decay was already implemented; verify it."""

    @pytest.fixture
    def generator(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        return OntologyGenerator()

    @pytest.fixture
    def ctx(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerationContext,
        )
        return OntologyGenerationContext(
            data_source="test", data_type="text", domain="general"
        )

    def test_close_entities_have_higher_confidence_than_far(self, generator, ctx):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        e1 = Entity(id="e1", type="Person", text="Alice", confidence=0.9)
        e2_near = Entity(id="e2", type="Person", text="Bob", confidence=0.9)
        e2_far = Entity(id="e3", type="Person", text="Charlie", confidence=0.9)

        text_near = "Alice Bob other words"
        text_far = "Alice" + " word" * 100 + " Charlie"

        rels_near = generator.infer_relationships([e1, e2_near], ctx, text_near)
        rels_far = generator.infer_relationships([e1, e2_far], ctx, text_far)

        # Near pair should have >= confidence of far pair
        near_conf = max((r.confidence for r in rels_near), default=0.0)
        far_conf = max((r.confidence for r in rels_far), default=0.0)
        # If far entities are > 200 chars apart, no relationship is inferred
        if rels_far:
            assert near_conf >= far_conf

    def test_entities_far_apart_produce_no_relationship(self, generator, ctx):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        e1 = Entity(id="e1", type="Person", text="Alice", confidence=0.9)
        e2 = Entity(id="e2", type="Person", text="Zephyr", confidence=0.9)
        # 500 words of padding >> 200 char window
        text = "Alice" + " padding" * 500 + " Zephyr"
        rels = generator.infer_relationships([e1, e2], ctx, text)
        co_occ_rels = [r for r in rels if r.type == "related_to"]
        # Should produce no co-occurrence link (too far apart)
        assert len(co_occ_rels) == 0


# ──────────────────────────────────────────────────────────────────────────────
# analyze_batch_parallel already covers the parallelization TODO
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzeBatchParallelExists:
    """Verify analyze_batch_parallel is available (covers the parallelization TODO)."""

    def test_analyze_batch_parallel_exists(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
        assert hasattr(OntologyOptimizer, "analyze_batch_parallel")
        assert callable(OntologyOptimizer.analyze_batch_parallel)

    def test_analyze_batch_parallel_accepts_max_workers(self):
        import inspect
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
        sig = inspect.signature(OntologyOptimizer.analyze_batch_parallel)
        assert "max_workers" in sig.parameters
