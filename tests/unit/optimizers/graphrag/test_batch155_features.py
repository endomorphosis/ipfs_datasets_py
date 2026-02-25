"""Batch-155 feature tests.

Methods under test:
  - OntologyPipeline.scores_above_mean()
  - OntologyGenerator.entity_count_by_type(result)
  - OntologyLearningAdapter.best_domain()
  - OntologyOptimizer.score_momentum_delta(window)
"""
import pytest
from unittest.mock import MagicMock


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, overall):
    score = MagicMock()
    score.overall = overall
    run = MagicMock()
    run.score = score
    p._run_history.append(run)


def _make_entity(eid, etype="Person"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=eid)


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=[], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score, domain=None):
    r = MagicMock()
    r.final_score = score
    r.domain = domain
    a._feedback.append(r)


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


# ---------------------------------------------------------------------------
# OntologyPipeline.scores_above_mean
# ---------------------------------------------------------------------------

class TestScoresAboveMean:
    @pytest.mark.parametrize(
        "scores,predicate",
        [
            ([], lambda result: result == []),
            ([0.5, 0.5, 0.5], lambda result: result == []),
            # mean=0.575; above: 0.8, 0.9
            ([0.2, 0.4, 0.8, 0.9], lambda result: len(result) == 2),
            ([0.2, 0.8], lambda result: all(r.score.overall > 0.5 for r in result)),
        ],
    )
    def test_scores_above_mean_scenarios(self, scores, predicate):
        p = _make_pipeline()
        for v in scores:
            _push_run(p, v)
        assert predicate(p.scores_above_mean())


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_count_by_type
# ---------------------------------------------------------------------------

class TestEntityCountByType:
    @pytest.mark.parametrize(
        "entities,predicate",
        [
            ([], lambda counts: counts == {}),
            (
                [_make_entity("e1", "Person"), _make_entity("e2", "Person")],
                lambda counts: counts == {"Person": 2},
            ),
            (
                [_make_entity("e1", "Person"), _make_entity("e2", "Org"), _make_entity("e3", "Person")],
                lambda counts: counts["Person"] == 2 and counts["Org"] == 1,
            ),
            (
                [_make_entity(f"e{i}", f"T{i % 3}") for i in range(9)],
                lambda counts: sum(counts.values()) == 9,
            ),
        ],
    )
    def test_entity_count_by_type_scenarios(self, entities, predicate):
        gen = _make_generator()
        result = _make_result(entities)
        assert predicate(gen.entity_count_by_type(result))


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.best_domain
# ---------------------------------------------------------------------------

class TestBestDomain:
    @pytest.mark.parametrize(
        "records,expected",
        [
            ([], ""),
            ([(0.7, "tech")], "tech"),
            # law avg=0.85, medicine avg=0.3 -> best is law
            ([(0.3, "medicine"), (0.9, "law"), (0.8, "law")], "law"),
        ],
    )
    def test_best_domain_scenarios(self, records, expected):
        a = _make_adapter()
        for score, domain in records:
            _push_feedback(a, score, domain=domain)
        assert a.best_domain() == expected


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_momentum_delta
# ---------------------------------------------------------------------------

class TestScoreMomentumDelta:
    @pytest.mark.parametrize(
        "scores,window,predicate",
        [
            ([], 3, lambda value: value == pytest.approx(0.0)),
            ([0.5, 0.6, 0.7], 3, lambda value: value == pytest.approx(0.0)),
            ([0.1, 0.2, 0.3, 0.7, 0.8, 0.9], 3, lambda value: value > 0),
            ([0.8, 0.9, 1.0, 0.1, 0.2, 0.3], 3, lambda value: value < 0),
            ([0.5, 0.5, 0.5, 0.5, 0.5, 0.5], 3, lambda value: value == pytest.approx(0.0)),
        ],
    )
    def test_score_momentum_delta_scenarios(self, scores, window, predicate):
        o = _make_optimizer()
        for v in scores:
            _push_opt(o, v)
        assert predicate(o.score_momentum_delta(window=window))
