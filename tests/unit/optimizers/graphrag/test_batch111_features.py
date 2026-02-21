"""Batch-111 feature tests.

Methods under test:
  - EntityExtractionResult.is_empty()
  - EntityExtractionResult.has_relationships()
  - EntityExtractionResult.entities_of_type(etype)
  - OntologyCritic.percentile_overall(scores, p)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity(eid, etype="Person", text="Alice", confidence=0.9):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=text, confidence=confidence)


def _relationship(rid, src, tgt, rtype="knows"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
    return Relationship(id=rid, source_id=src, target_id=tgt, type=rtype)


def _result(entities=None, relationships=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities or [],
        relationships=relationships or [],
        confidence=1.0,
    )


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _make_critic_score(overall_approx=0.7):
    """Make a CriticScore where all dims are equal (so overall ≈ each dim)."""
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    return CriticScore(
        completeness=overall_approx,
        consistency=overall_approx,
        clarity=overall_approx,
        granularity=overall_approx,
        domain_alignment=overall_approx,
    )


# ---------------------------------------------------------------------------
# EntityExtractionResult.is_empty
# ---------------------------------------------------------------------------

class TestIsEmpty:
    def test_empty_result(self):
        r = _result()
        assert r.is_empty() is True

    def test_has_entities_not_empty(self):
        r = _result([_entity("e1")])
        assert r.is_empty() is False

    def test_has_relationships_not_empty(self):
        r = _result(relationships=[_relationship("r1", "e1", "e2")])
        assert r.is_empty() is False

    def test_both_filled_not_empty(self):
        r = _result([_entity("e1")], [_relationship("r1", "e1", "e2")])
        assert r.is_empty() is False


# ---------------------------------------------------------------------------
# EntityExtractionResult.has_relationships
# ---------------------------------------------------------------------------

class TestHasRelationships:
    def test_no_relationships_false(self):
        r = _result([_entity("e1")])
        assert r.has_relationships() is False

    def test_with_relationship_true(self):
        r = _result(
            [_entity("e1"), _entity("e2")],
            [_relationship("r1", "e1", "e2")],
        )
        assert r.has_relationships() is True

    def test_empty_result_false(self):
        r = _result()
        assert r.has_relationships() is False


# ---------------------------------------------------------------------------
# EntityExtractionResult.entities_of_type
# ---------------------------------------------------------------------------

class TestEntitiesOfType:
    def test_empty_result(self):
        r = _result()
        assert r.entities_of_type("Person") == []

    def test_matching_type(self):
        r = _result([_entity("e1", "Person"), _entity("e2", "Place")])
        result = r.entities_of_type("Person")
        assert len(result) == 1
        assert result[0].id == "e1"

    def test_case_insensitive_by_default(self):
        r = _result([_entity("e1", "Person")])
        result = r.entities_of_type("person")
        assert len(result) == 1

    def test_case_sensitive_mode(self):
        r = _result([_entity("e1", "Person")])
        result = r.entities_of_type("person", case_sensitive=True)
        assert result == []

    def test_multiple_matches(self):
        r = _result([
            _entity("e1", "Person"),
            _entity("e2", "Person"),
            _entity("e3", "Place"),
        ])
        result = r.entities_of_type("Person")
        assert len(result) == 2


# ---------------------------------------------------------------------------
# OntologyCritic.percentile_overall  (new method to add)
# ---------------------------------------------------------------------------

class TestPercentileOverall:
    def test_empty_scores_returns_zero(self):
        c = _make_critic()
        assert c.percentile_overall([], 50) == 0.0

    def test_median(self):
        c = _make_critic()
        scores = [_make_critic_score(v) for v in [0.2, 0.5, 0.8]]
        result = c.percentile_overall(scores, 50)
        assert result == pytest.approx(0.5, abs=0.05)

    def test_p0_returns_min(self):
        c = _make_critic()
        scores = [_make_critic_score(0.3), _make_critic_score(0.7)]
        result = c.percentile_overall(scores, 0)
        assert result == pytest.approx(0.3, abs=0.05)

    def test_p100_returns_max(self):
        c = _make_critic()
        scores = [_make_critic_score(0.3), _make_critic_score(0.7)]
        result = c.percentile_overall(scores, 100)
        assert result == pytest.approx(0.7, abs=0.05)

    def test_raises_out_of_range(self):
        c = _make_critic()
        scores = [_make_critic_score(0.5)]
        with pytest.raises(ValueError):
            c.percentile_overall(scores, 101)
