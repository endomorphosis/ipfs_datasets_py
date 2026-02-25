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
    @pytest.mark.parametrize(
        "before,after,predicate",
        [
            (
                _make_score(completeness=0.2),
                _make_score(completeness=0.9),
                lambda dim: dim == "completeness",
            ),
            (
                _make_score(),
                _make_score(),
                lambda dim: isinstance(dim, str),
            ),
            (
                _make_score(clarity=0.1, consistency=0.3),
                _make_score(clarity=0.8, consistency=0.4),
                lambda dim: dim == "clarity",
            ),
            (
                _make_score(
                    completeness=0.9,
                    domain_alignment=0.5,
                    consistency=0.5,
                    clarity=0.5,
                    granularity=0.5,
                    relationship_coherence=0.5,
                ),
                _make_score(
                    completeness=0.1,
                    domain_alignment=0.4,
                    consistency=0.5,
                    clarity=0.5,
                    granularity=0.5,
                    relationship_coherence=0.5,
                ),
                lambda dim: dim not in ("completeness",),
            ),
            (
                _make_score(granularity=0.0),
                _make_score(granularity=1.0),
                lambda dim: dim == "granularity",
            ),
        ],
    )
    def test_top_improving_dimension_scenarios(self, before, after, predicate):
        critic = _make_critic()
        assert predicate(critic.top_improving_dimension(before, after))


# ---------------------------------------------------------------------------
# OntologyGenerator.compact_result
# ---------------------------------------------------------------------------

class TestCompactResult:
    @pytest.mark.parametrize(
        "entities,predicate",
        [
            ([], lambda compacted: compacted.entities == []),
            (
                [_make_entity("e1", {"role": "subject"}), _make_entity("e2", {})],
                lambda compacted: len(compacted.entities) == 1 and compacted.entities[0].id == "e1",
            ),
            (
                [_make_entity("e0"), _make_entity("e1"), _make_entity("e2"), _make_entity("e3"), _make_entity("e4")],
                lambda compacted: compacted.entities == [],
            ),
            (
                [_make_entity("e1", None)],
                lambda compacted: compacted.entities == [],
            ),
        ],
    )
    def test_compact_result_entity_scenarios(self, entities, predicate):
        gen = _make_generator()
        result = _make_result(entities)
        compacted = gen.compact_result(result)
        assert predicate(compacted)

    def test_compact_result_preserves_relationships(self):
        gen = _make_generator()
        rel = MagicMock()
        e1 = _make_entity("e1", {"k": "v"})
        result = _make_result([e1], [rel])
        compacted = gen.compact_result(result)
        assert compacted.relationships == [rel]

    def test_compact_result_preserves_confidence_and_metadata(self):
        gen = _make_generator()
        result = _make_result([], [])
        result.confidence = 0.75
        result.metadata = {"src": "test"}
        compacted = gen.compact_result(result)
        assert compacted.confidence == pytest.approx(0.75)
        assert compacted.metadata == {"src": "test"}
