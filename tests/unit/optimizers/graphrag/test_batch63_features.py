"""Batch 63: evaluate_ontology timeout guard, OntologyMediator property tests,
OntologyPipeline negative tests, analyze_batch_parallel structured log.
"""
from __future__ import annotations

import json
import os
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    ExtractionConfig,
    OntologyGenerator,
    OntologyGenerationContext,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(domain: str = "test"):
    return OntologyGenerationContext(data_source="test", data_type="text", domain=domain)


def _score(**kwargs):
    defaults = dict(
        completeness=0.7, consistency=0.7, clarity=0.6, granularity=0.5,
        domain_alignment=0.4, recommendations=[],
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _ontology(n: int = 2):
    return {
        "entities": [
            {"id": f"e{i}", "type": "Person", "text": f"Name{i}", "properties": {}, "confidence": 0.8}
            for i in range(n)
        ],
        "relationships": [],
        "metadata": {},
        "domain": "test",
    }


def _make_mediator():
    gen = OntologyGenerator()
    critic = OntologyCritic(use_llm=False)
    return OntologyMediator(generator=gen, critic=critic, max_rounds=3)


# ---------------------------------------------------------------------------
# evaluate_ontology timeout guard
# ---------------------------------------------------------------------------

class TestEvaluateOntologyTimeout:
    def _critic(self):
        return OntologyCritic(use_llm=False)

    def test_no_timeout_succeeds(self):
        critic = self._critic()
        score = critic.evaluate_ontology(_ontology(), _ctx())
        assert isinstance(score, CriticScore)

    def test_large_timeout_succeeds(self):
        critic = self._critic()
        score = critic.evaluate_ontology(_ontology(), _ctx(), timeout=30.0)
        assert isinstance(score, CriticScore)

    def test_timeout_returns_critic_score_on_time(self):
        critic = self._critic()
        score = critic.evaluate_ontology(_ontology(5), _ctx(), timeout=10.0)
        assert 0.0 <= score.overall <= 1.0

    def test_timeout_none_is_default_behavior(self):
        critic = self._critic()
        score1 = critic.evaluate_ontology(_ontology(), _ctx(), timeout=None)
        score2 = critic.evaluate_ontology(_ontology(), _ctx())
        assert score1.completeness == pytest.approx(score2.completeness)

    def test_very_small_timeout_raises_timeout_error(self):
        """A 0.000001s timeout should fire on any non-trivial evaluation."""
        import unittest.mock as _mock
        import time

        critic = self._critic()

        # Patch _evaluate_ontology_impl to sleep briefly
        original_impl = critic._evaluate_ontology_impl

        def slow_impl(*args, **kwargs):
            time.sleep(0.5)
            return original_impl(*args, **kwargs)

        with _mock.patch.object(critic, "_evaluate_ontology_impl", side_effect=slow_impl):
            with pytest.raises(TimeoutError):
                critic.evaluate_ontology(_ontology(), _ctx(), timeout=0.05)

    def test_timeout_with_source_data(self):
        critic = self._critic()
        score = critic.evaluate_ontology(_ontology(), _ctx(), source_data="test text", timeout=10.0)
        assert isinstance(score, CriticScore)


# ---------------------------------------------------------------------------
# OntologyMediator.refine_ontology property tests (Hypothesis)
# ---------------------------------------------------------------------------

@st.composite
def ontology_strategy(draw):
    n_entities = draw(st.integers(min_value=0, max_value=8))
    n_rels = draw(st.integers(min_value=0, max_value=min(n_entities, 3)))
    entities = [
        {"id": f"e{i}", "type": "Person", "text": f"Entity{i}", "properties": {}, "confidence": 0.8}
        for i in range(n_entities)
    ]
    rels = []
    for i in range(n_rels):
        if n_entities >= 2:
            rels.append({
                "id": f"r{i}",
                "source_id": entities[i % n_entities]["id"],
                "target_id": entities[(i + 1) % n_entities]["id"],
                "type": "related_to",
                "confidence": 0.7,
            })
    return {
        "entities": entities,
        "relationships": rels,
        "metadata": {},
        "domain": "test",
    }


@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(ontology=ontology_strategy())
def test_refine_ontology_preserves_structure(ontology):
    """refine_ontology always returns a dict with 'entities' and 'relationships'."""
    mediator = _make_mediator()
    score = _score()
    ctx = _ctx()
    refined = mediator.refine_ontology(ontology, score, ctx)
    assert isinstance(refined, dict)
    assert "entities" in refined
    assert "relationships" in refined


@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(ontology=ontology_strategy())
def test_refine_ontology_entity_count_does_not_decrease(ontology):
    """refine_ontology never removes existing entities."""
    mediator = _make_mediator()
    score = _score(recommendations=[])
    ctx = _ctx()
    original_count = len(ontology["entities"])
    refined = mediator.refine_ontology(ontology, score, ctx)
    assert len(refined["entities"]) >= original_count


@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(ontology=ontology_strategy())
def test_refine_ontology_returns_metadata(ontology):
    """refine_ontology always tags the result with refinement_actions metadata."""
    mediator = _make_mediator()
    refined = mediator.refine_ontology(ontology, _score(), _ctx())
    assert "refinement_actions" in refined.get("metadata", {})


# ---------------------------------------------------------------------------
# OntologyPipeline negative tests
# ---------------------------------------------------------------------------

class TestOntologyPipelineNegative:
    def test_empty_string_does_not_crash(self):
        pipeline = OntologyPipeline(domain="test")
        result = pipeline.run("", data_source="t")
        assert result is not None

    def test_whitespace_only_does_not_crash(self):
        pipeline = OntologyPipeline(domain="test")
        result = pipeline.run("   \n\t  ", data_source="t")
        assert result is not None

    def test_very_long_text_does_not_crash(self):
        pipeline = OntologyPipeline(domain="test")
        long_text = "Alice works at ACME. " * 200  # ~4000 chars
        result = pipeline.run(long_text, data_source="t")
        assert result is not None

    def test_numeric_data_does_not_crash(self):
        pipeline = OntologyPipeline(domain="test")
        result = pipeline.run(12345, data_source="t")
        assert result is not None

    def test_no_entities_in_garbage_text(self):
        pipeline = OntologyPipeline(domain="test")
        result = pipeline.run("xxxx yyyy zzzz 1234 @#$%", data_source="t")
        assert result is not None

    def test_empty_domain_does_not_crash(self):
        pipeline = OntologyPipeline(domain="")
        result = pipeline.run("Alice works here.", data_source="t")
        assert result is not None

    def test_run_batch_empty_list(self):
        pipeline = OntologyPipeline(domain="test")
        results = pipeline.run_batch([])
        assert results == []

    def test_run_batch_single_empty_doc(self):
        pipeline = OntologyPipeline(domain="test")
        results = pipeline.run_batch([""])
        assert len(results) == 1

    def test_score_is_in_valid_range(self):
        pipeline = OntologyPipeline(domain="test")
        result = pipeline.run("Alice works here.", data_source="t")
        assert 0.0 <= result.score.overall <= 1.0


# ---------------------------------------------------------------------------
# analyze_batch_parallel structured JSON log
# ---------------------------------------------------------------------------

class TestAnalyzeBatchParallelJsonLog:
    def _make_session_result(self, score_val: float = 0.7):
        """Create a minimal session result stub."""
        class _FakeScore:
            overall = score_val

        class _FakeSession:
            critic_scores = [_FakeScore()]

        return _FakeSession()

    def test_json_log_written_when_path_provided(self, tmp_path):
        opt = OntologyOptimizer()
        sessions = [self._make_session_result(0.7), self._make_session_result(0.8)]
        log_path = str(tmp_path / "batch.json")
        opt.analyze_batch_parallel(sessions, json_log_path=log_path)
        assert os.path.exists(log_path)

    def test_json_log_is_valid_json(self, tmp_path):
        opt = OntologyOptimizer()
        sessions = [self._make_session_result(0.6), self._make_session_result(0.9)]
        log_path = str(tmp_path / "batch.json")
        opt.analyze_batch_parallel(sessions, json_log_path=log_path)
        with open(log_path) as fh:
            d = json.load(fh)
        assert isinstance(d, dict)

    def test_json_log_contains_required_keys(self, tmp_path):
        opt = OntologyOptimizer()
        sessions = [self._make_session_result(0.75)]
        log_path = str(tmp_path / "batch.json")
        opt.analyze_batch_parallel(sessions, json_log_path=log_path)
        with open(log_path) as fh:
            d = json.load(fh)
        for key in ("session_count", "average_score", "trend", "duration_ms"):
            assert key in d

    def test_json_log_not_written_without_path(self, tmp_path):
        """No file should be created if json_log_path is None."""
        opt = OntologyOptimizer()
        sessions = [self._make_session_result(0.7)]
        opt.analyze_batch_parallel(sessions)
        # No files should be created in tmp_path
        assert list(tmp_path.iterdir()) == []

    def test_returns_optimization_report(self):
        opt = OntologyOptimizer()
        sessions = [self._make_session_result(0.75)]
        report = opt.analyze_batch_parallel(sessions)
        assert isinstance(report, OptimizationReport)
