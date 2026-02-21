"""Batch-142 feature tests.

Methods under test:
  - OntologyLearningAdapter.worst_n_feedback(n)
  - OntologyLearningAdapter.feedback_score_range()
  - LogicValidator.entity_count(ontology)
  - LogicValidator.relationship_count(ontology)
  - LogicValidator.entity_to_relationship_ratio(ontology)
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _fr(score):
    r = MagicMock()
    r.final_score = score
    return r


def _push_adapter(a, *scores):
    for s in scores:
        a._feedback.append(_fr(s))


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _ont(num_entities=3, num_rels=2):
    ents = [{"id": f"e{i}", "type": "T"} for i in range(num_entities)]
    rels = [{"source_id": f"e{i}", "target_id": f"e{i+1}"} for i in range(num_rels)]
    return {"entities": ents, "relationships": rels}


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.worst_n_feedback
# ---------------------------------------------------------------------------

class TestWorstNFeedback:
    def test_empty_returns_empty(self):
        a = _make_adapter()
        assert a.worst_n_feedback() == []

    def test_returns_lowest_first(self):
        a = _make_adapter()
        _push_adapter(a, 0.8, 0.2, 0.5)
        result = a.worst_n_feedback(n=2)
        assert len(result) == 2
        assert result[0].final_score == pytest.approx(0.2)
        assert result[1].final_score == pytest.approx(0.5)

    def test_n_larger_than_records(self):
        a = _make_adapter()
        _push_adapter(a, 0.4, 0.6)
        assert len(a.worst_n_feedback(n=10)) == 2

    def test_default_n_is_three(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.3, 0.4, 0.5]:
            _push_adapter(a, v)
        assert len(a.worst_n_feedback()) == 3


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_score_range
# ---------------------------------------------------------------------------

class TestFeedbackScoreRange:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_score_range() == (0.0, 0.0)

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_adapter(a, 0.5)
        assert a.feedback_score_range() == (0.5, 0.5)

    def test_known_range(self):
        a = _make_adapter()
        _push_adapter(a, 0.2, 0.8)
        lo, hi = a.feedback_score_range()
        assert lo == pytest.approx(0.2)
        assert hi == pytest.approx(0.8)

    def test_non_negative(self):
        a = _make_adapter()
        _push_adapter(a, 0.7, 0.3, 0.5)
        lo, hi = a.feedback_score_range()
        assert lo >= 0.0
        assert hi >= 0.0


# ---------------------------------------------------------------------------
# LogicValidator.entity_count
# ---------------------------------------------------------------------------

class TestEntityCount:
    def test_empty_ontology(self):
        v = _make_validator()
        assert v.entity_count({}) == 0

    def test_with_entities(self):
        v = _make_validator()
        assert v.entity_count(_ont(num_entities=4, num_rels=0)) == 4

    def test_no_entities_key(self):
        v = _make_validator()
        ont = {"relationships": []}
        assert v.entity_count(ont) == 0

    def test_returns_int(self):
        v = _make_validator()
        assert isinstance(v.entity_count(_ont()), int)


# ---------------------------------------------------------------------------
# LogicValidator.relationship_count
# ---------------------------------------------------------------------------

class TestRelationshipCount:
    def test_empty_ontology(self):
        v = _make_validator()
        assert v.relationship_count({}) == 0

    def test_with_relationships(self):
        v = _make_validator()
        assert v.relationship_count(_ont(num_rels=3)) == 3

    def test_no_relationships_key(self):
        v = _make_validator()
        ont = {"entities": [{"id": "e1"}]}
        assert v.relationship_count(ont) == 0


# ---------------------------------------------------------------------------
# LogicValidator.entity_to_relationship_ratio
# ---------------------------------------------------------------------------

class TestEntityToRelationshipRatio:
    def test_no_relationships_returns_entity_count(self):
        v = _make_validator()
        ont = _ont(num_entities=5, num_rels=0)
        assert v.entity_to_relationship_ratio(ont) == pytest.approx(5.0)

    def test_known_ratio(self):
        v = _make_validator()
        ont = _ont(num_entities=6, num_rels=3)
        assert v.entity_to_relationship_ratio(ont) == pytest.approx(2.0)

    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.entity_to_relationship_ratio({}) == pytest.approx(0.0)

    def test_returns_float(self):
        v = _make_validator()
        assert isinstance(v.entity_to_relationship_ratio(_ont()), float)
