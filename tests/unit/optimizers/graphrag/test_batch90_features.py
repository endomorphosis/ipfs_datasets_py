"""Batch 90: score_at, rename_entity, median_score, latest_feedback, reset."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
    FeedbackRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, text: str, etype: str = "PERSON") -> Entity:
    return Entity(id=eid, text=text, type=etype, confidence=0.8)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


def _make_score(c=0.8, con=0.7, cl=0.6, g=0.5, da=0.9) -> CriticScore:
    return CriticScore(completeness=c, consistency=con, clarity=cl, granularity=g, domain_alignment=da)


class _FakeEntry:
    def __init__(self, score: float):
        self.average_score = score


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_at
# ---------------------------------------------------------------------------


class TestScoreAt:
    def test_raises_on_empty(self):
        opt = OntologyOptimizer()
        with pytest.raises(IndexError):
            opt.score_at(0)

    def test_first_entry(self):
        opt = OntologyOptimizer()
        opt._history.append(_FakeEntry(0.7))
        assert opt.score_at(0) == pytest.approx(0.7)

    def test_negative_index(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.3), _FakeEntry(0.8)])
        assert opt.score_at(-1) == pytest.approx(0.8)

    def test_out_of_range_raises(self):
        opt = OntologyOptimizer()
        opt._history.append(_FakeEntry(0.5))
        with pytest.raises(IndexError):
            opt.score_at(5)

    def test_returns_float(self):
        opt = OntologyOptimizer()
        opt._history.append(_FakeEntry(0.5))
        assert isinstance(opt.score_at(0), float)


# ---------------------------------------------------------------------------
# OntologyGenerator.rename_entity
# ---------------------------------------------------------------------------


class TestRenameEntity:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_renames_entity(self):
        e = _make_entity("e1", "Alice")
        result = _make_result(e)
        r2 = self.gen.rename_entity(result, "e1", "Alice Smith")
        assert r2.entities[0].text == "Alice Smith"

    def test_other_entities_unchanged(self):
        e1 = _make_entity("e1", "Alice")
        e2 = _make_entity("e2", "Bob")
        result = _make_result(e1, e2)
        r2 = self.gen.rename_entity(result, "e1", "Alice Smith")
        assert r2.entities[1].text == "Bob"

    def test_raises_on_missing_id(self):
        result = _make_result()
        with pytest.raises(KeyError):
            self.gen.rename_entity(result, "ghost", "X")

    def test_original_unchanged(self):
        e = _make_entity("e1", "Alice")
        result = _make_result(e)
        self.gen.rename_entity(result, "e1", "Alice Smith")
        assert result.entities[0].text == "Alice"

    def test_returns_extraction_result(self):
        e = _make_entity("e1", "Alice")
        result = _make_result(e)
        assert isinstance(self.gen.rename_entity(result, "e1", "X"), EntityExtractionResult)


# ---------------------------------------------------------------------------
# OntologyCritic.median_score
# ---------------------------------------------------------------------------


class TestMedianScore:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty_returns_zero(self):
        assert self.critic.median_score([]) == pytest.approx(0.0)

    def test_single_score(self):
        s = _make_score(c=0.8, con=0.8, cl=0.8, g=0.8, da=0.8)
        assert self.critic.median_score([s]) == pytest.approx(s.overall)

    def test_odd_count(self):
        high = _make_score(c=1.0, con=1.0, cl=1.0, g=1.0, da=1.0)
        low = _make_score(c=0.0, con=0.0, cl=0.0, g=0.0, da=0.0)
        mid = _make_score()
        result = self.critic.median_score([low, high, mid])
        assert 0.0 < result < 1.0

    def test_even_count_average(self):
        high = _make_score(c=1.0, con=1.0, cl=1.0, g=1.0, da=1.0)
        low = _make_score(c=0.0, con=0.0, cl=0.0, g=0.0, da=0.0)
        result = self.critic.median_score([high, low])
        assert 0.0 < result < 1.0

    def test_returns_float(self):
        assert isinstance(self.critic.median_score([_make_score()]), float)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.latest_feedback
# ---------------------------------------------------------------------------


class TestLatestFeedback:
    def test_none_when_empty(self):
        adapter = OntologyLearningAdapter()
        assert adapter.latest_feedback() is None

    def test_returns_last(self):
        adapter = OntologyLearningAdapter()
        r1 = FeedbackRecord(final_score=0.3)
        r2 = FeedbackRecord(final_score=0.9)
        adapter._feedback.extend([r1, r2])
        assert adapter.latest_feedback() is r2

    def test_returns_feedback_record(self):
        adapter = OntologyLearningAdapter()
        adapter._feedback.append(FeedbackRecord(final_score=0.5))
        assert isinstance(adapter.latest_feedback(), FeedbackRecord)


# ---------------------------------------------------------------------------
# OntologyPipeline.reset
# ---------------------------------------------------------------------------


class TestPipelineReset:
    def test_zero_when_no_runs(self):
        p = OntologyPipeline()
        assert p.reset() == 0

    def test_clears_history(self):
        p = OntologyPipeline()
        p.run("Alice.")
        p.run("Bob.")
        p.reset()
        assert p.total_runs() == 0

    def test_returns_count_cleared(self):
        p = OntologyPipeline()
        p.run("Alice.")
        assert p.reset() == 1

    def test_returns_int(self):
        p = OntologyPipeline()
        assert isinstance(p.reset(), int)

    def test_last_score_zero_after_reset(self):
        p = OntologyPipeline()
        p.run("Alice.")
        p.reset()
        assert p.last_score() == pytest.approx(0.0)
