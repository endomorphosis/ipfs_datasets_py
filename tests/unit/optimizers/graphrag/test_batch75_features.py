"""Batch-75 feature tests.

Covers:
- OntologyCritic.score_batch_summary(scores)
- OntologyMediator.clear_recommendation_history()
- EntityExtractionResult.entity_type_counts()
- OntologyOptimizer.history_length property
- OntologyPipeline.domain_list property
"""

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
    OntologyGenerationContext,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mediator():
    gen = OntologyGenerator()
    crit = OntologyCritic(use_llm=False)
    return OntologyMediator(generator=gen, critic=crit, max_rounds=3)


def _score(**kw):
    defaults = dict(completeness=0.7, consistency=0.8, clarity=0.6, granularity=0.5, relationship_coherence=0.9, domain_alignment=0.9)
    defaults.update(kw)
    return CriticScore(**defaults)


def _entity(eid="e1", etype="Person", text="Alice", conf=0.9):
    return Entity(id=eid, type=etype, text=text, confidence=conf)


def _result(*entities):
    return EntityExtractionResult(entities=list(entities), relationships=[], confidence=0.8)


def _report(avg=0.7):
    return OptimizationReport(average_score=avg, trend="stable")


# ---------------------------------------------------------------------------
# OntologyCritic.score_batch_summary
# ---------------------------------------------------------------------------

class TestScoreBatchSummary:
    def test_returns_dict(self):
        critic = OntologyCritic(use_llm=False)
        s = _score()
        assert isinstance(critic.score_batch_summary([s]), dict)

    def test_has_required_keys(self):
        critic = OntologyCritic(use_llm=False)
        summary = critic.score_batch_summary([_score()])
        for key in ("count", "mean_overall", "min_overall", "max_overall", "std_overall"):
            assert key in summary

    def test_count_correct(self):
        critic = OntologyCritic(use_llm=False)
        assert critic.score_batch_summary([_score(), _score()])["count"] == 2

    def test_empty_raises(self):
        critic = OntologyCritic(use_llm=False)
        with pytest.raises(ValueError):
            critic.score_batch_summary([])

    def test_single_std_zero(self):
        critic = OntologyCritic(use_llm=False)
        s = _score()
        result = critic.score_batch_summary([s])
        assert result["std_overall"] == 0.0

    def test_mean_correct(self):
        critic = OntologyCritic(use_llm=False)
        s1 = _score(completeness=0.5, consistency=0.5, clarity=0.5, granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5)
        s2 = _score(completeness=1.0, consistency=1.0, clarity=1.0, granularity=1.0, relationship_coherence=1.0, domain_alignment=1.0)
        summary = critic.score_batch_summary([s1, s2])
        assert abs(summary["mean_overall"] - 0.75) < 0.01  # rough check


# ---------------------------------------------------------------------------
# OntologyMediator.clear_recommendation_history
# ---------------------------------------------------------------------------

class TestClearRecommendationHistory:
    def test_returns_int(self):
        assert isinstance(_mediator().clear_recommendation_history(), int)

    def test_returns_zero_when_empty(self):
        assert _mediator().clear_recommendation_history() == 0

    def test_clears_history(self):
        med = _mediator()
        med._recommendation_counts["fix_type"] = 3
        med.clear_recommendation_history()
        assert med.get_recommendation_stats() == {}

    def test_returns_count(self):
        med = _mediator()
        med._recommendation_counts["a"] = 1
        med._recommendation_counts["b"] = 2
        assert med.clear_recommendation_history() == 2

    def test_does_not_clear_action_counts(self):
        med = _mediator()
        med._action_counts["refine"] = 5
        med._recommendation_counts["fix"] = 1
        med.clear_recommendation_history()
        assert med._action_counts["refine"] == 5


# ---------------------------------------------------------------------------
# EntityExtractionResult.entity_type_counts
# ---------------------------------------------------------------------------

class TestEntityTypeCounts:
    def test_returns_dict(self):
        r = _result(_entity())
        assert isinstance(r.entity_type_counts(), dict)

    def test_empty_result(self):
        r = _result()
        assert r.entity_type_counts() == {}

    def test_counts_types(self):
        r = _result(
            _entity("e1", "Person"),
            _entity("e2", "Person"),
            _entity("e3", "Org"),
        )
        counts = r.entity_type_counts()
        assert counts["Person"] == 2
        assert counts["Org"] == 1

    def test_single_entity(self):
        r = _result(_entity(etype="Concept"))
        assert r.entity_type_counts() == {"Concept": 1}

    def test_descending_order(self):
        r = _result(
            _entity("e1", "Org"),
            _entity("e2", "Person"),
            _entity("e3", "Person"),
        )
        items = list(r.entity_type_counts().items())
        assert items[0][0] == "Person"  # highest count first


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_length
# ---------------------------------------------------------------------------

class TestHistoryLength:
    def test_zero_initially(self):
        assert OntologyOptimizer().history_length == 0

    def test_increments(self):
        opt = OntologyOptimizer()
        opt._history.append(_report())
        assert opt.history_length == 1

    def test_returns_int(self):
        assert isinstance(OntologyOptimizer().history_length, int)

    def test_matches_len_history(self):
        opt = OntologyOptimizer()
        for i in range(5):
            opt._history.append(_report(float(i) / 10))
        assert opt.history_length == len(opt._history)


# ---------------------------------------------------------------------------
# OntologyPipeline.domain_list
# ---------------------------------------------------------------------------

class TestDomainList:
    def test_returns_list(self):
        assert isinstance(OntologyPipeline().domain_list, list)

    def test_nonempty(self):
        assert len(OntologyPipeline().domain_list) > 0

    def test_contains_general(self):
        assert "general" in OntologyPipeline().domain_list

    def test_contains_legal(self):
        assert "legal" in OntologyPipeline().domain_list

    def test_all_strings(self):
        for d in OntologyPipeline().domain_list:
            assert isinstance(d, str)

    def test_sorted(self):
        dl = OntologyPipeline().domain_list
        assert dl == sorted(dl)
