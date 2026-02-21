"""Batch-167 feature tests.

Methods under test:
  - OntologyLearningAdapter.feedback_decay_sum(decay)
  - OntologyLearningAdapter.feedback_count_below(threshold)
  - OntologyLearningAdapter.feedback_above_threshold_fraction(threshold)
  - LogicValidator.relationship_diversity(ontology)
  - LogicValidator.entity_pair_count(ontology)
  - OntologyOptimizer.score_plateau_length()
"""
import pytest
from unittest.mock import MagicMock


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _ont(rels):
    return {"entities": [], "relationships": rels}


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_decay_sum
# ---------------------------------------------------------------------------

class TestFeedbackDecaySum:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_decay_sum() == pytest.approx(0.0)

    def test_single_record_no_decay(self):
        a = _make_adapter()
        _push_feedback(a, 0.8)
        assert a.feedback_decay_sum(0.9) == pytest.approx(0.8)

    def test_decay_reduces_old_records(self):
        a = _make_adapter()
        _push_feedback(a, 1.0)  # older
        _push_feedback(a, 1.0)  # newer
        # decayed sum: 1.0*1.0 + 1.0*0.5 = 1.5 (using decay=0.5)
        result = a.feedback_decay_sum(decay=0.5)
        assert result == pytest.approx(1.5)

    def test_no_decay_equals_sum(self):
        a = _make_adapter()
        for v in [0.2, 0.4, 0.6]:
            _push_feedback(a, v)
        # decay=1.0 => no decay, equal to regular sum
        assert a.feedback_decay_sum(decay=1.0) == pytest.approx(1.2)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_count_below
# ---------------------------------------------------------------------------

class TestFeedbackCountBelow:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_count_below(0.5) == 0

    def test_all_below(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.3]:
            _push_feedback(a, v)
        assert a.feedback_count_below(0.5) == 3

    def test_none_below(self):
        a = _make_adapter()
        for v in [0.6, 0.7, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_count_below(0.5) == 0

    def test_equal_not_counted(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_count_below(0.5) == 0


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_above_threshold_fraction
# ---------------------------------------------------------------------------

class TestFeedbackAboveThresholdFraction:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_above_threshold_fraction(0.5) == pytest.approx(0.0)

    def test_all_above(self):
        a = _make_adapter()
        for v in [0.6, 0.7, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_above_threshold_fraction(0.5) == pytest.approx(1.0)

    def test_half_above(self):
        a = _make_adapter()
        for v in [0.3, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_above_threshold_fraction(0.5) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# LogicValidator.relationship_diversity
# ---------------------------------------------------------------------------

class TestRelationshipDiversity:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.relationship_diversity(_ont([])) == pytest.approx(0.0)

    def test_single_type_zero_entropy(self):
        v = _make_validator()
        rels = [{"source": "a", "target": "b", "type": "has"},
                {"source": "c", "target": "d", "type": "has"}]
        assert v.relationship_diversity(_ont(rels)) == pytest.approx(0.0)

    def test_two_equal_types_max_entropy(self):
        v = _make_validator()
        rels = [{"source": "a", "target": "b", "type": "has"},
                {"source": "c", "target": "d", "type": "is"}]
        entropy = v.relationship_diversity(_ont(rels))
        assert entropy == pytest.approx(1.0)  # log2(2) = 1.0

    def test_more_types_higher_entropy(self):
        v = _make_validator()
        rels_2 = [{"source": "a", "target": "b", "type": "A"},
                  {"source": "c", "target": "d", "type": "B"}]
        rels_4 = [{"source": "a", "target": "b", "type": "A"},
                  {"source": "c", "target": "d", "type": "B"},
                  {"source": "e", "target": "f", "type": "C"},
                  {"source": "g", "target": "h", "type": "D"}]
        assert v.relationship_diversity(_ont(rels_4)) > v.relationship_diversity(_ont(rels_2))


# ---------------------------------------------------------------------------
# LogicValidator.entity_pair_count
# ---------------------------------------------------------------------------

class TestEntityPairCount:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.entity_pair_count(_ont([])) == 0

    def test_unique_pairs(self):
        v = _make_validator()
        rels = [{"source": "a", "target": "b", "type": "r"},
                {"source": "b", "target": "c", "type": "r"}]
        assert v.entity_pair_count(_ont(rels)) == 2

    def test_duplicate_pairs_counted_once(self):
        v = _make_validator()
        rels = [{"source": "a", "target": "b", "type": "r"},
                {"source": "a", "target": "b", "type": "s"}]
        assert v.entity_pair_count(_ont(rels)) == 1


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_plateau_length
# ---------------------------------------------------------------------------

class TestScorePlateauLength:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_plateau_length() == 0

    def test_single_entry_returns_one(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_plateau_length() == 1

    def test_all_flat(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.5)
        assert o.score_plateau_length() == 5

    def test_no_flat_streak(self):
        o = _make_optimizer()
        for v in [0.1, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.score_plateau_length() == 1

    def test_longest_flat_wins(self):
        o = _make_optimizer()
        # one flat run of 3, then a gap, then flat run of 2
        for v in [0.5, 0.5, 0.5, 0.9, 0.9]:
            _push_opt(o, v)
        assert o.score_plateau_length() == 3
