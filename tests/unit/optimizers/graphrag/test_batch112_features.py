"""Batch-112 feature tests.

Methods under test:
  - OntologyOptimizer.has_improved(baseline)
  - OntologyGenerator.normalize_confidence(result)
  - OntologyCritic.normalize_scores(scores)
  - OntologyPipeline.is_stable(threshold, window)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, score):
        self.average_score = score
        self.trend = "flat"
        self.best_ontology = {}
        self.worst_ontology = {}
        self.metadata = {}


def _opt_with_history(scores):
    opt = _make_optimizer()
    for s in scores:
        opt._history.append(_FakeEntry(s))
    return opt


def _entity(eid, etype="Person", text="Alice", confidence=0.9):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=text, confidence=confidence)


def _result(entities=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities or [],
        relationships=[],
        confidence=1.0,
    )


def _make_gen():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _make_critic_score(v):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    return CriticScore(completeness=v, consistency=v, clarity=v, granularity=v, domain_alignment=v)


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(pipeline, overall):
    from unittest.mock import MagicMock
    score = MagicMock()
    score.overall = overall
    run = MagicMock()
    run.score = score
    pipeline._run_history.append(run)


# ---------------------------------------------------------------------------
# OntologyOptimizer.has_improved
# ---------------------------------------------------------------------------

class TestHasImproved:
    def test_empty_history_false(self):
        opt = _make_optimizer()
        assert opt.has_improved(0.5) is False

    def test_all_below_baseline_false(self):
        opt = _opt_with_history([0.3, 0.4])
        assert opt.has_improved(0.5) is False

    def test_some_above_true(self):
        opt = _opt_with_history([0.3, 0.7])
        assert opt.has_improved(0.5) is True

    def test_exact_baseline_false(self):
        opt = _opt_with_history([0.5])
        assert opt.has_improved(0.5) is False

    def test_all_above_true(self):
        opt = _opt_with_history([0.8, 0.9])
        assert opt.has_improved(0.5) is True


# ---------------------------------------------------------------------------
# OntologyGenerator.normalize_confidence
# ---------------------------------------------------------------------------

class TestNormalizeConfidence:
    def test_empty_result_unchanged(self):
        gen = _make_gen()
        r = _result()
        normalized = gen.normalize_confidence(r)
        assert normalized.entities == []

    def test_single_entity_unchanged(self):
        gen = _make_gen()
        r = _result([_entity("e1", confidence=0.7)])
        normalized = gen.normalize_confidence(r)
        # With single entity, lo == hi, no change
        assert normalized.entities[0].confidence == pytest.approx(0.7)

    def test_spreads_to_zero_one(self):
        gen = _make_gen()
        r = _result([
            _entity("e1", confidence=0.2),
            _entity("e2", confidence=0.8),
        ])
        normalized = gen.normalize_confidence(r)
        confs = sorted(e.confidence for e in normalized.entities)
        assert confs[0] == pytest.approx(0.0)
        assert confs[1] == pytest.approx(1.0)

    def test_three_entities(self):
        gen = _make_gen()
        r = _result([
            _entity("e1", confidence=0.0),
            _entity("e2", confidence=0.5),
            _entity("e3", confidence=1.0),
        ])
        normalized = gen.normalize_confidence(r)
        confs = {e.id: e.confidence for e in normalized.entities}
        assert confs["e1"] == pytest.approx(0.0)
        assert confs["e2"] == pytest.approx(0.5)
        assert confs["e3"] == pytest.approx(1.0)

    def test_original_unchanged(self):
        gen = _make_gen()
        r = _result([_entity("e1", confidence=0.2), _entity("e2", confidence=0.8)])
        gen.normalize_confidence(r)
        assert r.entities[0].confidence == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# OntologyCritic.normalize_scores
# ---------------------------------------------------------------------------

class TestNormalizeScores:
    def test_empty_returns_empty(self):
        c = _make_critic()
        assert c.normalize_scores([]) == []

    def test_single_score_returned_unchanged(self):
        c = _make_critic()
        s = _make_critic_score(0.7)
        result = c.normalize_scores([s])
        assert len(result) == 1

    def test_all_same_overall_unchanged(self):
        c = _make_critic()
        scores = [_make_critic_score(0.5), _make_critic_score(0.5)]
        result = c.normalize_scores(scores)
        # All same, returned as-is
        assert len(result) == 2

    def test_two_scores_normalized(self):
        c = _make_critic()
        low = _make_critic_score(0.2)
        high = _make_critic_score(0.8)
        result = c.normalize_scores([low, high])
        assert len(result) == 2
        # After normalization, values should be in [0, 1]
        for s in result:
            assert 0.0 <= s.overall <= 1.0

    def test_returns_list(self):
        c = _make_critic()
        scores = [_make_critic_score(0.3), _make_critic_score(0.7)]
        result = c.normalize_scores(scores)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# OntologyPipeline.is_stable
# ---------------------------------------------------------------------------

class TestIsStable:
    def test_too_few_runs_false(self):
        p = _make_pipeline()
        _push_run(p, 0.7)
        _push_run(p, 0.8)
        # need window=3 by default
        assert p.is_stable() is False

    def test_stable_with_identical_scores(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.75)
        assert p.is_stable() is True

    def test_unstable_with_large_variance(self):
        p = _make_pipeline()
        _push_run(p, 0.1)
        _push_run(p, 0.9)
        _push_run(p, 0.1)
        assert p.is_stable(threshold=0.02) is False

    def test_custom_window(self):
        p = _make_pipeline()
        # Push 5 runs: first 3 volatile, last 2 stable
        for v in [0.1, 0.9, 0.1, 0.75, 0.76]:
            _push_run(p, v)
        # window=2 looks only at last 2 (0.75, 0.76) — very stable
        assert p.is_stable(threshold=0.02, window=2) is True
