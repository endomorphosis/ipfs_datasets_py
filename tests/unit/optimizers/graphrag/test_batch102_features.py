"""Batch 102: average_run_score, score_at, action_types, feedback_above, summary_dict."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter


# ---------------------------------------------------------------------------
# OntologyPipeline.average_run_score
# ---------------------------------------------------------------------------


class TestAverageRunScore:
    def test_zero_before_runs(self):
        assert OntologyPipeline().average_run_score() == pytest.approx(0.0)

    def test_returns_float(self):
        assert isinstance(OntologyPipeline().average_run_score(), float)

    def test_after_runs(self):
        p = OntologyPipeline()
        p.run("Alice founded ACME Corp.")
        avg = p.average_run_score()
        assert 0.0 <= avg <= 1.0

    def test_zero_after_reset(self):
        p = OntologyPipeline()
        p.run("text")
        p.reset()
        assert p.average_run_score() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# OntologyPipeline.score_at
# ---------------------------------------------------------------------------


class TestPipelineScoreAt:
    def test_raises_on_empty(self):
        p = OntologyPipeline()
        with pytest.raises(IndexError):
            p.score_at(0)

    def test_returns_float(self):
        p = OntologyPipeline()
        p.run("Alice.")
        assert isinstance(p.score_at(0), float)

    def test_negative_index(self):
        p = OntologyPipeline()
        p.run("Alice.")
        p.run("Bob.")
        # -1 should give last run
        assert p.score_at(-1) == p.score_at(1)


# ---------------------------------------------------------------------------
# OntologyMediator.action_types
# ---------------------------------------------------------------------------


class TestMediatorActionTypes:
    def test_empty(self):
        gen = OntologyGenerator()
        critic = OntologyCritic()
        m = OntologyMediator(gen, critic)
        assert m.action_types() == []

    def test_returns_list(self):
        gen = OntologyGenerator()
        critic = OntologyCritic()
        m = OntologyMediator(gen, critic)
        assert isinstance(m.action_types(), list)

    def test_sorted(self):
        gen = OntologyGenerator()
        critic = OntologyCritic()
        m = OntologyMediator(gen, critic)
        m._action_counts["z_action"] = 1
        m._action_counts["a_action"] = 1
        types = m.action_types()
        assert types == sorted(types)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_above
# ---------------------------------------------------------------------------


class TestFeedbackAbove:
    def test_empty(self):
        assert OntologyLearningAdapter().feedback_above() == []

    def test_filters_above(self):
        a = OntologyLearningAdapter()
        a.apply_feedback(0.3)
        a.apply_feedback(0.9)
        result = a.feedback_above(threshold=0.6)
        assert len(result) == 1
        assert result[0].final_score > 0.6

    def test_exclusive_threshold(self):
        a = OntologyLearningAdapter()
        a.apply_feedback(0.6)
        assert a.feedback_above(threshold=0.6) == []

    def test_returns_list(self):
        assert isinstance(OntologyLearningAdapter().feedback_above(), list)


# ---------------------------------------------------------------------------
# LogicValidator.summary_dict
# ---------------------------------------------------------------------------


class TestSummaryDict:
    def setup_method(self):
        self.v = LogicValidator()

    def test_empty_ontology(self):
        d = self.v.summary_dict({"entities": [], "relationships": []})
        assert d["entity_count"] == 0
        assert d["relationship_count"] == 0
        assert d["has_contradictions"] is False

    def test_with_entities(self):
        ont = {"entities": [{"id": "e1"}, {"id": "e2"}], "relationships": []}
        d = self.v.summary_dict(ont)
        assert d["entity_count"] == 2

    def test_has_required_keys(self):
        d = self.v.summary_dict({})
        assert "entity_count" in d
        assert "relationship_count" in d
        assert "has_contradictions" in d

    def test_returns_dict(self):
        assert isinstance(self.v.summary_dict({}), dict)
