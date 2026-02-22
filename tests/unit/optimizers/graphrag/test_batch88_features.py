"""Batch 88: explain_entity, clear_history, percentile_score, rebuild_result, domain setter, run_batch, top_n_scores."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, text: str, etype: str = "PERSON", conf: float = 0.8) -> Entity:
    return Entity(id=eid, text=text, type=etype, confidence=conf)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


# ---------------------------------------------------------------------------
# OntologyGenerator.explain_entity
# ---------------------------------------------------------------------------


class TestExplainEntity:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_returns_string(self):
        e = _make_entity("1", "Alice", "PERSON", 0.9)
        assert isinstance(self.gen.explain_entity(e), str)

    def test_contains_text(self):
        e = _make_entity("1", "Alice", "PERSON", 0.9)
        assert "Alice" in self.gen.explain_entity(e)

    def test_contains_type(self):
        e = _make_entity("1", "Alice", "PERSON", 0.9)
        assert "PERSON" in self.gen.explain_entity(e)

    def test_contains_confidence(self):
        e = _make_entity("1", "Alice", "PERSON", 0.9)
        assert "0.90" in self.gen.explain_entity(e)

    def test_non_empty(self):
        e = _make_entity("1", "X", "T", 0.5)
        assert len(self.gen.explain_entity(e)) > 0


# ---------------------------------------------------------------------------
# OntologyGenerator.rebuild_result
# ---------------------------------------------------------------------------


class TestRebuildResult:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_wraps_entities(self):
        entities = [_make_entity("1", "A"), _make_entity("2", "B")]
        result = self.gen.rebuild_result(entities)
        assert len(result.entities) == 2

    def test_empty_rels_by_default(self):
        result = self.gen.rebuild_result([])
        assert result.relationships == []

    def test_custom_relationships(self):
        rels = [Relationship(id="r1", source_id="e1", target_id="e2", type="X")]
        result = self.gen.rebuild_result([], relationships=rels)
        assert len(result.relationships) == 1

    def test_returns_extraction_result(self):
        assert isinstance(self.gen.rebuild_result([]), EntityExtractionResult)

    def test_confidence_passed(self):
        result = self.gen.rebuild_result([], confidence=0.75)
        assert result.confidence == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# OntologyOptimizer.clear_history
# ---------------------------------------------------------------------------


class TestClearHistory:
    def test_empty_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.clear_history() == 0

    def test_returns_count_cleared(self):
        opt = OntologyOptimizer()
        # Manually inject history items
        class _FakeEntry:
            average_score = 0.5
        opt._history.extend([_FakeEntry(), _FakeEntry(), _FakeEntry()])
        assert opt.clear_history() == 3

    def test_history_empty_after(self):
        opt = OntologyOptimizer()
        class _FakeEntry:
            average_score = 0.5
        opt._history.append(_FakeEntry())
        opt.clear_history()
        assert opt.score_history() == []

    def test_returns_int(self):
        assert isinstance(OntologyOptimizer().clear_history(), int)


# ---------------------------------------------------------------------------
# OntologyOptimizer.percentile_score
# ---------------------------------------------------------------------------


class TestPercentileScore:
    def test_empty_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.percentile_score(50) == pytest.approx(0.0)

    def test_single_entry_any_percentile(self):
        opt = OntologyOptimizer()
        class _FakeEntry:
            average_score = 0.7
        opt._history.append(_FakeEntry())
        assert opt.percentile_score(0) == pytest.approx(0.7)
        assert opt.percentile_score(100) == pytest.approx(0.7)

    def test_median_of_three(self):
        opt = OntologyOptimizer()
        for s in [0.2, 0.5, 0.8]:
            class _FE:
                average_score = s
            opt._history.append(_FE())
        assert opt.percentile_score(50) == pytest.approx(0.5)

    def test_returns_float(self):
        assert isinstance(OntologyOptimizer().percentile_score(50), float)


# ---------------------------------------------------------------------------
# OntologyOptimizer.top_n_scores
# ---------------------------------------------------------------------------


class TestTopNScores:
    def test_empty(self):
        assert OntologyOptimizer().top_n_scores() == []

    def test_returns_descending(self):
        opt = OntologyOptimizer()
        for s in [0.3, 0.9, 0.6]:
            class _FE:
                average_score = s
            opt._history.append(_FE())
        scores = opt.top_n_scores(3)
        assert scores == sorted(scores, reverse=True)

    def test_respects_n(self):
        opt = OntologyOptimizer()
        for s in [0.1, 0.5, 0.9, 0.7]:
            class _FE:
                average_score = s
            opt._history.append(_FE())
        assert len(opt.top_n_scores(2)) == 2

    def test_returns_list(self):
        assert isinstance(OntologyOptimizer().top_n_scores(), list)


# ---------------------------------------------------------------------------
# OntologyPipeline.domain setter
# ---------------------------------------------------------------------------


class TestDomainSetter:
    def test_get_default(self):
        p = OntologyPipeline()
        assert p.domain == "general"

    def test_set_domain(self):
        p = OntologyPipeline()
        p.domain = "legal"
        assert p.domain == "legal"

    def test_run_uses_new_domain(self):
        p = OntologyPipeline()
        p.domain = "medical"
        result = p.run("Alice")
        assert result is not None

    def test_set_and_reset(self):
        p = OntologyPipeline()
        p.domain = "finance"
        p.domain = "general"
        assert p.domain == "general"


# ---------------------------------------------------------------------------
# OntologyPipeline.run_batch
# ---------------------------------------------------------------------------


class TestRunBatch:
    def test_empty_input(self):
        p = OntologyPipeline()
        assert p.run_batch([]) == []

    def test_length_matches(self):
        p = OntologyPipeline()
        results = p.run_batch(["Alice.", "Bob."])
        assert len(results) == 2

    def test_updates_history(self):
        p = OntologyPipeline()
        p.run_batch(["Alice.", "Bob.", "Carol."])
        assert p.total_runs() == 3

    def test_returns_list(self):
        p = OntologyPipeline()
        assert isinstance(p.run_batch([]), list)
