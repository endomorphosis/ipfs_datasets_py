"""Batch 97: filter_result_by_confidence, score_distribution, entity_count, top_k_feedback."""

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
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
    FeedbackRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, conf: float = 0.8, etype: str = "PERSON") -> Entity:
    return Entity(id=eid, text=f"E{eid}", type=etype, confidence=conf)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


def _make_score(v: float) -> CriticScore:
    return CriticScore(completeness=v, consistency=v, clarity=v, granularity=v, domain_alignment=v)


# ---------------------------------------------------------------------------
# OntologyGenerator.filter_result_by_confidence
# ---------------------------------------------------------------------------


class TestFilterResultByConfidence:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty_result(self):
        r = _make_result()
        assert self.gen.filter_result_by_confidence(r) == r

    def test_filters_low_confidence(self):
        r = _make_result(_make_entity("1", 0.3), _make_entity("2", 0.9))
        out = self.gen.filter_result_by_confidence(r, min_conf=0.5)
        assert len(out.entities) == 1
        assert out.entities[0].id == "2"

    def test_default_threshold_0_5(self):
        r = _make_result(_make_entity("1", 0.5), _make_entity("2", 0.4))
        out = self.gen.filter_result_by_confidence(r)
        assert len(out.entities) == 1

    def test_returns_extraction_result(self):
        r = _make_result(_make_entity("1", 0.9))
        assert isinstance(self.gen.filter_result_by_confidence(r), EntityExtractionResult)

    def test_returns_new_instance(self):
        r = _make_result(_make_entity("1", 0.9))
        out = self.gen.filter_result_by_confidence(r)
        assert out is not r


# ---------------------------------------------------------------------------
# OntologyCritic.score_distribution
# ---------------------------------------------------------------------------


class TestScoreDistribution:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty(self):
        d = self.critic.score_distribution([])
        assert d["count"] == 0
        assert d["mean"] == 0.0

    def test_single(self):
        d = self.critic.score_distribution([_make_score(0.7)])
        assert d["count"] == 1
        assert d["mean"] == pytest.approx(0.7)
        assert d["std"] == pytest.approx(0.0)
        assert d["min"] == pytest.approx(0.7)
        assert d["max"] == pytest.approx(0.7)

    def test_returns_dict(self):
        assert isinstance(self.critic.score_distribution([]), dict)

    def test_has_required_keys(self):
        d = self.critic.score_distribution([_make_score(0.5)])
        for key in ("mean", "std", "min", "max", "count"):
            assert key in d

    def test_mean_correct(self):
        scores = [_make_score(v) for v in [0.2, 0.4, 0.6]]
        d = self.critic.score_distribution(scores)
        assert d["mean"] == pytest.approx(0.4, abs=0.01)


# ---------------------------------------------------------------------------
# LogicValidator.entity_count
# ---------------------------------------------------------------------------


class TestValidatorEntityCount:
    def setup_method(self):
        self.v = LogicValidator()

    def test_empty_entities(self):
        assert self.v.entity_count({"entities": []}) == 0

    def test_counts_entities(self):
        ont = {"entities": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}]}
        assert self.v.entity_count(ont) == 3

    def test_fallback_to_nodes(self):
        ont = {"nodes": [{"id": "n1"}]}
        assert self.v.entity_count(ont) == 1

    def test_no_key_returns_zero(self):
        assert self.v.entity_count({}) == 0

    def test_returns_int(self):
        assert isinstance(self.v.entity_count({"entities": []}), int)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.top_k_feedback
# ---------------------------------------------------------------------------


class TestTopKFeedback:
    def setup_method(self):
        self.adapter = OntologyLearningAdapter()

    def test_empty(self):
        assert self.adapter.top_k_feedback() == []

    def test_returns_top_by_score(self):
        for score in [0.3, 0.9, 0.6]:
            self.adapter.apply_feedback(score)
        top1 = self.adapter.top_k_feedback(k=1)
        assert len(top1) == 1
        assert top1[0].final_score == pytest.approx(0.9)

    def test_descending_order(self):
        for score in [0.2, 0.8, 0.5]:
            self.adapter.apply_feedback(score)
        result = self.adapter.top_k_feedback(k=3)
        assert result[0].final_score >= result[1].final_score >= result[2].final_score

    def test_returns_list(self):
        assert isinstance(self.adapter.top_k_feedback(), list)

    def test_k_larger_than_records(self):
        self.adapter.apply_feedback(0.7)
        assert len(self.adapter.top_k_feedback(k=10)) == 1
