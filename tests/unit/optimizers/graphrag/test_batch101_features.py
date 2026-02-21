"""Batch 101: max/min_confidence, best/worst_dimension, has_contradictions, feedback_below."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, conf: float = 0.8) -> Entity:
    return Entity(id=eid, text=f"E{eid}", type="PERSON", confidence=conf)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


# ---------------------------------------------------------------------------
# EntityExtractionResult.max_confidence
# ---------------------------------------------------------------------------


class TestMaxConfidence:
    def test_empty(self):
        assert _make_result().max_confidence() == pytest.approx(0.0)

    def test_single(self):
        r = _make_result(_make_entity("1", 0.7))
        assert r.max_confidence() == pytest.approx(0.7)

    def test_multiple(self):
        r = _make_result(_make_entity("1", 0.4), _make_entity("2", 0.9))
        assert r.max_confidence() == pytest.approx(0.9)

    def test_returns_float(self):
        assert isinstance(_make_result(_make_entity("1")).max_confidence(), float)


# ---------------------------------------------------------------------------
# EntityExtractionResult.min_confidence
# ---------------------------------------------------------------------------


class TestMinConfidence:
    def test_empty(self):
        assert _make_result().min_confidence() == pytest.approx(0.0)

    def test_single(self):
        r = _make_result(_make_entity("1", 0.3))
        assert r.min_confidence() == pytest.approx(0.3)

    def test_multiple(self):
        r = _make_result(_make_entity("1", 0.4), _make_entity("2", 0.9))
        assert r.min_confidence() == pytest.approx(0.4)

    def test_returns_float(self):
        assert isinstance(_make_result(_make_entity("1")).min_confidence(), float)


# ---------------------------------------------------------------------------
# OntologyCritic.best_dimension / worst_dimension
# ---------------------------------------------------------------------------


class TestBestDimension:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_returns_string(self):
        s = CriticScore(completeness=0.5, consistency=0.5, clarity=0.5, granularity=0.5, domain_alignment=0.5)
        assert isinstance(self.critic.best_dimension(s), str)

    def test_identifies_best(self):
        s = CriticScore(completeness=0.9, consistency=0.3, clarity=0.3, granularity=0.3, domain_alignment=0.3)
        assert self.critic.best_dimension(s) == "completeness"

    def test_valid_dimension_name(self):
        s = CriticScore(completeness=0.5, consistency=0.5, clarity=0.5, granularity=0.5, domain_alignment=0.5)
        valid = {"completeness", "consistency", "clarity", "granularity", "domain_alignment"}
        assert self.critic.best_dimension(s) in valid


class TestWorstDimension:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_returns_string(self):
        s = CriticScore(completeness=0.5, consistency=0.5, clarity=0.5, granularity=0.5, domain_alignment=0.5)
        assert isinstance(self.critic.worst_dimension(s), str)

    def test_identifies_worst(self):
        s = CriticScore(completeness=0.1, consistency=0.8, clarity=0.8, granularity=0.8, domain_alignment=0.8)
        assert self.critic.worst_dimension(s) == "completeness"

    def test_valid_dimension_name(self):
        s = CriticScore(completeness=0.5, consistency=0.5, clarity=0.5, granularity=0.5, domain_alignment=0.5)
        valid = {"completeness", "consistency", "clarity", "granularity", "domain_alignment"}
        assert self.critic.worst_dimension(s) in valid


# ---------------------------------------------------------------------------
# LogicValidator.has_contradictions
# ---------------------------------------------------------------------------


class TestHasContradictions:
    def setup_method(self):
        self.v = LogicValidator()

    def test_empty_ontology_no_contradictions(self):
        assert self.v.has_contradictions({"entities": [], "relationships": []}) is False

    def test_returns_bool(self):
        assert isinstance(self.v.has_contradictions({}), bool)

    def test_consistent_ontology(self):
        ont = {"entities": [{"id": "e1", "type": "PERSON"}], "relationships": []}
        assert self.v.has_contradictions(ont) is False


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_below
# ---------------------------------------------------------------------------


class TestFeedbackBelow:
    def test_empty(self):
        assert OntologyLearningAdapter().feedback_below() == []

    def test_filters_below(self):
        a = OntologyLearningAdapter()
        a.apply_feedback(0.3)
        a.apply_feedback(0.8)
        result = a.feedback_below(threshold=0.5)
        assert len(result) == 1
        assert result[0].final_score < 0.5

    def test_exclusive_threshold(self):
        a = OntologyLearningAdapter()
        a.apply_feedback(0.5)
        assert a.feedback_below(threshold=0.5) == []

    def test_returns_list(self):
        assert isinstance(OntologyLearningAdapter().feedback_below(), list)
