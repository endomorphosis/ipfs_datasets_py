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
    @pytest.mark.parametrize(
        "scores,n,expected_len,expected_prefix",
        [
            ([], 3, 0, []),
            ([0.8, 0.2, 0.5], 2, 2, [0.2, 0.5]),
            ([0.4, 0.6], 10, 2, [0.4, 0.6]),
            ([0.1, 0.2, 0.3, 0.4, 0.5], 3, 3, [0.1, 0.2, 0.3]),
        ],
    )
    def test_worst_n_feedback_scenarios(self, scores, n, expected_len, expected_prefix):
        a = _make_adapter()
        _push_adapter(a, *scores)
        result = a.worst_n_feedback(n=n)
        assert len(result) == expected_len
        for idx, expected in enumerate(expected_prefix):
            assert result[idx].final_score == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_score_range
# ---------------------------------------------------------------------------

class TestFeedbackScoreRange:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], (0.0, 0.0)),
            ([0.5], (0.5, 0.5)),
            ([0.2, 0.8], (0.2, 0.8)),
        ],
    )
    def test_feedback_score_range_scenarios(self, scores, expected):
        a = _make_adapter()
        _push_adapter(a, *scores)
        assert a.feedback_score_range() == pytest.approx(expected)

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
    @pytest.mark.parametrize(
        "ontology,expected",
        [
            ({}, 0),
            (_ont(num_entities=4, num_rels=0), 4),
            ({"relationships": []}, 0),
        ],
    )
    def test_entity_count_scenarios(self, ontology, expected):
        v = _make_validator()
        assert v.entity_count(ontology) == expected

    def test_returns_int(self):
        v = _make_validator()
        assert isinstance(v.entity_count(_ont()), int)


# ---------------------------------------------------------------------------
# LogicValidator.relationship_count
# ---------------------------------------------------------------------------

class TestRelationshipCount:
    @pytest.mark.parametrize(
        "ontology,expected",
        [
            ({}, 0),
            (_ont(num_rels=3), 3),
            ({"entities": [{"id": "e1"}]}, 0),
        ],
    )
    def test_relationship_count_scenarios(self, ontology, expected):
        v = _make_validator()
        assert v.relationship_count(ontology) == expected


# ---------------------------------------------------------------------------
# LogicValidator.entity_to_relationship_ratio
# ---------------------------------------------------------------------------

class TestEntityToRelationshipRatio:
    @pytest.mark.parametrize(
        "ontology,expected",
        [
            (_ont(num_entities=5, num_rels=0), 5.0),
            (_ont(num_entities=6, num_rels=3), 2.0),
            ({}, 0.0),
        ],
    )
    def test_entity_to_relationship_ratio_scenarios(self, ontology, expected):
        v = _make_validator()
        assert v.entity_to_relationship_ratio(ontology) == pytest.approx(expected)

    def test_returns_float(self):
        v = _make_validator()
        assert isinstance(v.entity_to_relationship_ratio(_ont()), float)
