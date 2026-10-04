"""Batch 106: worst/median runs, feedback median, last entry, relationship types."""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


class _Entry:
    def __init__(self, score: float):
        self.average_score = score
        self.best_ontology = {}
        self.worst_ontology = {}
        self.trend = "flat"


class TestWorstRun:
    def test_none_when_empty(self):
        assert OntologyPipeline().worst_run() is None

    def test_returns_lowest_scored_run(self):
        p = OntologyPipeline()
        p.run("Alice founded ACME Corp.")
        p.run("x")
        w = p.worst_run()
        assert w is not None
        assert w.score.overall == min(r.score.overall for r in p.history)

    def test_reset_clears(self):
        p = OntologyPipeline()
        p.run("abc")
        p.reset()
        assert p.worst_run() is None

    def test_result_has_score(self):
        p = OntologyPipeline()
        p.run("abc")
        assert hasattr(p.worst_run(), "score")


class TestMedianRunScore:
    def test_empty_zero(self):
        assert OntologyPipeline().median_run_score() == pytest.approx(0.0)

    def test_single(self):
        p = OntologyPipeline()
        p.run("abc")
        assert p.median_run_score() == pytest.approx(p.score_at(0))

    def test_even(self):
        p = OntologyPipeline()
        p.run("abc")
        p.run("def")
        vals = sorted([p.score_at(0), p.score_at(1)])
        assert p.median_run_score() == pytest.approx((vals[0] + vals[1]) / 2.0)

    def test_float(self):
        assert isinstance(OntologyPipeline().median_run_score(), float)


class TestFeedbackMedian:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], 0.0),
            ([0.2, 0.9, 0.4], 0.4),
            ([0.1, 0.3, 0.7, 0.9], 0.5),
        ],
    )
    def test_feedback_median_scenarios(self, scores, expected):
        a = OntologyLearningAdapter()
        for s in scores:
            a.apply_feedback(s)
        assert a.feedback_median() == pytest.approx(expected)

    def test_float(self):
        assert isinstance(OntologyLearningAdapter().feedback_median(), float)


class TestLastEntry:
    @pytest.mark.parametrize(
        "history,expected_is_none,expected_score",
        [
            ([], True, None),
            ([_Entry(0.1), _Entry(0.9)], False, 0.9),
        ],
    )
    def test_last_entry_scenarios(self, history, expected_is_none, expected_score):
        o = OntologyOptimizer()
        o._history.extend(history)
        last = o.last_entry()
        if expected_is_none:
            assert last is None
        else:
            assert last is not None
            assert last.average_score == pytest.approx(expected_score)

    def test_matches_last_score(self):
        o = OntologyOptimizer()
        o._history.extend([_Entry(0.1), _Entry(0.9)])
        assert o.last_entry().average_score == pytest.approx(o.last_score())

    def test_has_average_score(self):
        o = OntologyOptimizer()
        o._history.append(_Entry(0.5))
        assert hasattr(o.last_entry(), "average_score")


class TestRelationshipTypes:
    def test_empty(self):
        assert LogicValidator().relationship_types({}) == []

    def test_dedup_and_sort(self):
        v = LogicValidator()
        ont = {"relationships": [{"type": "B"}, {"type": "A"}, {"type": "A"}]}
        assert v.relationship_types(ont) == ["A", "B"]

    def test_supports_relation_type_key(self):
        v = LogicValidator()
        ont = {"edges": [{"relation_type": "LIKES"}]}
        assert v.relationship_types(ont) == ["LIKES"]

    def test_non_list_returns_empty(self):
        assert LogicValidator().relationship_types({"relationships": "bad"}) == []
