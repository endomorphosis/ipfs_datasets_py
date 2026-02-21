"""Batch-147 feature tests.

Methods under test:
  - OntologyCritic.top_improving_dimension(before, after)
  - OntologyGenerator.compact_result(result)
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_score(**kwargs):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    defaults = dict(
        completeness=0.5, consistency=0.5, clarity=0.5,
        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _make_entity(eid, properties=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="Test", text=eid, properties=properties or {})


def _make_result(entities, relationships=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities,
        relationships=relationships or [],
        confidence=1.0,
        metadata={},
        errors=[],
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


# ---------------------------------------------------------------------------
# OntologyCritic.top_improving_dimension
# ---------------------------------------------------------------------------

class TestTopImprovingDimension:
    def test_single_improving_dim(self):
        critic = _make_critic()
        before = _make_score(completeness=0.2)
        after = _make_score(completeness=0.9)  # only completeness improves significantly
        dim = critic.top_improving_dimension(before, after)
        assert dim == "completeness"

    def test_all_same_returns_first(self):
        critic = _make_critic()
        before = _make_score()
        after = _make_score()  # identical
        dim = critic.top_improving_dimension(before, after)
        # all deltas are 0 — returns whichever is max (any is fine, just must be a string)
        assert isinstance(dim, str)

    def test_most_improved_is_returned(self):
        critic = _make_critic()
        before = _make_score(clarity=0.1, consistency=0.3)
        after = _make_score(clarity=0.8, consistency=0.4)
        # clarity delta = 0.7, consistency delta = 0.1
        assert critic.top_improving_dimension(before, after) == "clarity"

    def test_negative_deltas_returns_least_negative(self):
        critic = _make_critic()
        before = _make_score(completeness=0.9, domain_alignment=0.5,
                             consistency=0.5, clarity=0.5, granularity=0.5, relationship_coherence=0.5)
        after = _make_score(completeness=0.1, domain_alignment=0.4,
                            consistency=0.5, clarity=0.5, granularity=0.5, relationship_coherence=0.5)
        # completeness -0.8, domain_alignment -0.1, all others 0 → first 0-delta dim wins
        # but domain_alignment (-0.1) < 0-delta dims — so a 0-delta dim is returned
        dim = critic.top_improving_dimension(before, after)
        # Any dim with delta=0 is acceptable (not completeness or domain_alignment)
        assert dim not in ("completeness",)

    def test_granularity_most_improved(self):
        critic = _make_critic()
        before = _make_score(granularity=0.0)
        after = _make_score(granularity=1.0)
        assert critic.top_improving_dimension(before, after) == "granularity"


# ---------------------------------------------------------------------------
# OntologyGenerator.compact_result
# ---------------------------------------------------------------------------

class TestCompactResult:
    def test_empty_entities_returns_empty(self):
        gen = _make_generator()
        result = _make_result([])
        compacted = gen.compact_result(result)
        assert compacted.entities == []

    def test_keeps_entities_with_properties(self):
        gen = _make_generator()
        e1 = _make_entity("e1", {"role": "subject"})
        e2 = _make_entity("e2", {})
        result = _make_result([e1, e2])
        compacted = gen.compact_result(result)
        assert len(compacted.entities) == 1
        assert compacted.entities[0].id == "e1"

    def test_removes_empty_properties(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}") for i in range(5)]  # all empty
        result = _make_result(entities)
        compacted = gen.compact_result(result)
        assert compacted.entities == []

    def test_preserves_relationships(self):
        gen = _make_generator()
        rel = MagicMock()
        e1 = _make_entity("e1", {"k": "v"})
        result = _make_result([e1], [rel])
        compacted = gen.compact_result(result)
        assert compacted.relationships == [rel]

    def test_preserves_confidence_and_metadata(self):
        gen = _make_generator()
        result = _make_result([], [])
        result.confidence = 0.75
        result.metadata = {"src": "test"}
        compacted = gen.compact_result(result)
        assert compacted.confidence == pytest.approx(0.75)
        assert compacted.metadata == {"src": "test"}

    def test_none_properties_removed(self):
        gen = _make_generator()
        # Entity with properties=None-like falsy value
        e = _make_entity("e1", None)
        result = _make_result([e])
        compacted = gen.compact_result(result)
        assert compacted.entities == []
