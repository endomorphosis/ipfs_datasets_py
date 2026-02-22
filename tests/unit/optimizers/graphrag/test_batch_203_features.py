"""
Unit tests for Batch 203 implementations.

Tests cover:
- OntologyGenerator.apply_config(result, config)
- OntologyMediator.retry_last_round(ontology, score, ctx)
- OntologyOptimizer.score_coefficient_of_variation()
- OntologyOptimizer.score_relative_improvement()
- OntologyOptimizer.score_to_mean_ratio()
- OntologyLearningAdapter.feedback_std()
- OntologyLearningAdapter.feedback_coefficient_of_variation()
- OntologyLearningAdapter.feedback_relative_std()
- OntologyPipeline.run_score_relative_improvement()
"""
from __future__ import annotations

import math
import pytest
from unittest.mock import MagicMock

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(
    confidences: list[float] | None = None,
    rels: list | None = None,
) -> EntityExtractionResult:
    if confidences is None:
        confidences = [0.9, 0.7, 0.5]
    entities = [
        Entity(id=f"e{i}", text=f"Ent{i}", type="Person", confidence=c)
        for i, c in enumerate(confidences)
    ]
    if rels is None:
        rels = []
    return EntityExtractionResult(entities=entities, relationships=rels, confidence=0.8)


def _report(score: float = 0.5) -> OptimizationReport:
    return OptimizationReport(average_score=score, trend="stable")


def _adapter_with(scores: list[float]) -> OntologyLearningAdapter:
    adapter = OntologyLearningAdapter(domain="test")
    for s in scores:
        adapter.apply_feedback(final_score=s, actions=[])
    return adapter


def _make_critic_score(overall: float = 0.7) -> CriticScore:
    return CriticScore(
        completeness=overall,
        consistency=overall,
        clarity=overall,
        granularity=overall,
        relationship_coherence=overall,
        domain_alignment=overall,
    )


def _make_mediator() -> OntologyMediator:
    gen = MagicMock()
    critic = MagicMock()
    # Make refine_ontology return a dict
    def _fake_refine(ontology, feedback, context):
        import copy
        result = copy.deepcopy(ontology)
        return result
    m = OntologyMediator(generator=gen, critic=critic)
    return m


def _make_ontology(n: int = 3) -> dict:
    return {
        "entities": [{"id": f"e{i}", "text": f"E{i}", "type": "Person"} for i in range(n)],
        "relationships": [],
    }


def _make_mock_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.domain = "test"
    ctx.data_source = "test_source"
    ctx.data_type = "text"
    return ctx


# ---------------------------------------------------------------------------
# OntologyGenerator.apply_config
# ---------------------------------------------------------------------------

class TestApplyConfig:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_threshold_zero_keeps_all(self):
        config = ExtractionConfig(confidence_threshold=0.0)
        result = _make_result([0.1, 0.5, 0.9])
        filtered = self.gen.apply_config(result, config)
        assert len(filtered.entities) == 3

    def test_threshold_removes_low_confidence(self):
        config = ExtractionConfig(confidence_threshold=0.6)
        result = _make_result([0.3, 0.7, 0.9])
        filtered = self.gen.apply_config(result, config)
        assert len(filtered.entities) == 2
        assert all(e.confidence >= 0.6 for e in filtered.entities)

    def test_threshold_one_removes_all(self):
        config = ExtractionConfig(confidence_threshold=1.0)
        result = _make_result([0.1, 0.5, 0.9])
        filtered = self.gen.apply_config(result, config)
        assert len(filtered.entities) == 0

    def test_exact_threshold_kept(self):
        """Entities at exactly threshold should be kept."""
        config = ExtractionConfig(confidence_threshold=0.7)
        result = _make_result([0.7, 0.8, 0.5])
        filtered = self.gen.apply_config(result, config)
        assert len(filtered.entities) == 2

    def test_relationships_pruned(self):
        """Relationships referencing removed entities should be pruned."""
        entities = [
            Entity(id="e0", text="A", type="Person", confidence=0.9),
            Entity(id="e1", text="B", type="Person", confidence=0.3),
        ]
        rels = [
            Relationship(id="r1", source_id="e0", target_id="e1", type="knows"),
        ]
        result = EntityExtractionResult(entities=entities, relationships=rels, confidence=0.7)
        config = ExtractionConfig(confidence_threshold=0.5)
        filtered = self.gen.apply_config(result, config)
        # e1 removed → r1 pruned
        assert len(filtered.entities) == 1
        assert len(filtered.relationships) == 0

    def test_relationships_kept_when_both_survive(self):
        entities = [
            Entity(id="e0", text="A", type="Person", confidence=0.9),
            Entity(id="e1", text="B", type="Person", confidence=0.8),
        ]
        rels = [
            Relationship(id="r1", source_id="e0", target_id="e1", type="knows"),
        ]
        result = EntityExtractionResult(entities=entities, relationships=rels, confidence=0.8)
        config = ExtractionConfig(confidence_threshold=0.5)
        filtered = self.gen.apply_config(result, config)
        assert len(filtered.entities) == 2
        assert len(filtered.relationships) == 1

    def test_empty_result(self):
        config = ExtractionConfig(confidence_threshold=0.5)
        result = EntityExtractionResult(entities=[], relationships=[], confidence=1.0)
        filtered = self.gen.apply_config(result, config)
        assert filtered.entities == []
        assert filtered.relationships == []

    def test_original_not_mutated(self):
        config = ExtractionConfig(confidence_threshold=0.8)
        result = _make_result([0.5, 0.9])
        original_count = len(result.entities)
        self.gen.apply_config(result, config)
        assert len(result.entities) == original_count

    def test_returns_new_result_object(self):
        config = ExtractionConfig(confidence_threshold=0.0)
        result = _make_result([0.9])
        filtered = self.gen.apply_config(result, config)
        assert filtered is not result


# ---------------------------------------------------------------------------
# OntologyMediator.retry_last_round
# ---------------------------------------------------------------------------

class TestRetryLastRound:
    def test_empty_undo_stack_refines_current(self):
        """With no undo stack, refines the ontology as-is."""
        mediator = _make_mediator()
        ont = _make_ontology()
        score = _make_critic_score(0.5)
        ctx = _make_mock_ctx()
        result = mediator.retry_last_round(ont, score, ctx)
        assert isinstance(result, dict)

    def test_with_undo_stack_rolls_back(self):
        """With a snapshot in the undo stack, the rollback is used."""
        mediator = _make_mediator()
        import copy
        snapshot = _make_ontology(n=2)
        mediator._undo_stack.append(copy.deepcopy(snapshot))
        ont = _make_ontology(n=5)
        score = _make_critic_score(0.4)
        ctx = _make_mock_ctx()
        result = mediator.retry_last_round(ont, score, ctx)
        assert isinstance(result, dict)

    def test_returns_dict(self):
        mediator = _make_mediator()
        result = mediator.retry_last_round(
            _make_ontology(), _make_critic_score(0.6), _make_mock_ctx()
        )
        assert isinstance(result, dict)

    def test_does_not_mutate_original(self):
        mediator = _make_mediator()
        ont = _make_ontology(n=3)
        original_len = len(ont["entities"])
        mediator.retry_last_round(ont, _make_critic_score(0.5), _make_mock_ctx())
        assert len(ont["entities"]) == original_len


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_coefficient_of_variation
# ---------------------------------------------------------------------------

class TestScoreCoefficientOfVariation:
    def test_empty_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.score_coefficient_of_variation() == 0.0

    def test_single_returns_zero(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.7))
        assert opt.score_coefficient_of_variation() == 0.0

    def test_uniform_returns_zero(self):
        opt = OntologyOptimizer()
        for _ in range(3):
            opt._history.append(_report(0.6))
        assert opt.score_coefficient_of_variation() == pytest.approx(0.0, abs=1e-9)

    def test_diverse_positive(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.2))
        opt._history.append(_report(0.8))
        cv = opt.score_coefficient_of_variation()
        assert cv > 0.0

    def test_zero_mean_returns_zero(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.0))
        assert opt.score_coefficient_of_variation() == 0.0

    def test_returns_float(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.5))
        opt._history.append(_report(0.6))
        assert isinstance(opt.score_coefficient_of_variation(), float)


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_relative_improvement
# ---------------------------------------------------------------------------

class TestScoreRelativeImprovement:
    def test_empty_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.score_relative_improvement() == 0.0

    def test_single_returns_zero(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.5))
        assert opt.score_relative_improvement() == 0.0

    def test_improvement(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.5))
        opt._history.append(_report(0.75))
        # (0.75 - 0.5) / 0.5 = 0.5
        assert opt.score_relative_improvement() == pytest.approx(0.5)

    def test_decline(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.8))
        opt._history.append(_report(0.4))
        # (0.4 - 0.8) / 0.8 = -0.5
        assert opt.score_relative_improvement() == pytest.approx(-0.5)

    def test_no_change(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.6))
        opt._history.append(_report(0.6))
        assert opt.score_relative_improvement() == pytest.approx(0.0)

    def test_zero_first_returns_zero(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.0))
        opt._history.append(_report(0.7))
        assert opt.score_relative_improvement() == 0.0

    def test_returns_float(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.5))
        opt._history.append(_report(0.8))
        assert isinstance(opt.score_relative_improvement(), float)


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_to_mean_ratio
# ---------------------------------------------------------------------------

class TestScoreToMeanRatio:
    def test_empty_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.score_to_mean_ratio() == 0.0

    def test_single_entry(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.6))
        assert opt.score_to_mean_ratio() == pytest.approx(1.0)

    def test_above_mean(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.4))
        opt._history.append(_report(0.6))
        opt._history.append(_report(0.8))
        # mean = 0.6, last = 0.8 → ratio = 0.8/0.6
        assert opt.score_to_mean_ratio() == pytest.approx(0.8 / 0.6)

    def test_below_mean(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.8))
        opt._history.append(_report(0.6))
        opt._history.append(_report(0.4))
        # mean = 0.6, last = 0.4 → ratio = 0.4/0.6
        assert opt.score_to_mean_ratio() == pytest.approx(0.4 / 0.6)

    def test_zero_mean_returns_zero(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.0))
        assert opt.score_to_mean_ratio() == 0.0

    def test_returns_float(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.7))
        opt._history.append(_report(0.9))
        assert isinstance(opt.score_to_mean_ratio(), float)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_std
# ---------------------------------------------------------------------------

class TestFeedbackStd:
    def test_no_feedback(self):
        adapter = OntologyLearningAdapter(domain="test")
        assert adapter.feedback_std() == 0.0

    def test_single_feedback(self):
        adapter = _adapter_with([0.7])
        assert adapter.feedback_std() == 0.0

    def test_uniform_scores(self):
        adapter = _adapter_with([0.5, 0.5, 0.5])
        assert adapter.feedback_std() == pytest.approx(0.0)

    def test_varied_scores(self):
        adapter = _adapter_with([0.0, 1.0])
        # var = 0.25, std = 0.5
        assert adapter.feedback_std() == pytest.approx(0.5)

    def test_returns_float(self):
        adapter = _adapter_with([0.3, 0.7])
        assert isinstance(adapter.feedback_std(), float)

    def test_non_negative(self):
        adapter = _adapter_with([0.2, 0.4, 0.6, 0.8])
        assert adapter.feedback_std() >= 0.0


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_coefficient_of_variation
# ---------------------------------------------------------------------------

class TestFeedbackCoefficientOfVariation:
    def test_no_feedback(self):
        adapter = OntologyLearningAdapter(domain="test")
        assert adapter.feedback_coefficient_of_variation() == 0.0

    def test_uniform_scores_zero_cv(self):
        adapter = _adapter_with([0.6, 0.6, 0.6])
        assert adapter.feedback_coefficient_of_variation() == pytest.approx(0.0, abs=1e-9)

    def test_zero_mean_returns_zero(self):
        adapter = _adapter_with([0.0, 0.0])
        assert adapter.feedback_coefficient_of_variation() == 0.0

    def test_positive_cv_for_varied_scores(self):
        adapter = _adapter_with([0.3, 0.7])
        assert adapter.feedback_coefficient_of_variation() > 0.0

    def test_returns_float(self):
        adapter = _adapter_with([0.4, 0.6])
        assert isinstance(adapter.feedback_coefficient_of_variation(), float)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_relative_std (alias)
# ---------------------------------------------------------------------------

class TestFeedbackRelativeStd:
    def test_alias_matches_cv(self):
        adapter = _adapter_with([0.4, 0.6, 0.8])
        assert adapter.feedback_relative_std() == adapter.feedback_coefficient_of_variation()

    def test_returns_float(self):
        adapter = _adapter_with([0.5, 0.7])
        assert isinstance(adapter.feedback_relative_std(), float)


# ---------------------------------------------------------------------------
# OntologyPipeline.run_score_relative_improvement
# ---------------------------------------------------------------------------

class TestRunScoreRelativeImprovement:
    def _pipeline_with_scores(self, scores: list[float]):
        from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
        pipeline = OntologyPipeline()
        for s in scores:
            score = _make_critic_score(s)
            run = MagicMock()
            run.score = score
            pipeline._run_history.append(run)
        return pipeline

    def test_no_runs(self):
        pipeline = self._pipeline_with_scores([])
        assert pipeline.run_score_relative_improvement() == 0.0

    def test_single_run(self):
        pipeline = self._pipeline_with_scores([0.7])
        assert pipeline.run_score_relative_improvement() == 0.0

    def test_improvement(self):
        pipeline = self._pipeline_with_scores([0.5, 0.75])
        # (0.75 - 0.5) / 0.5 = 0.5
        assert pipeline.run_score_relative_improvement() == pytest.approx(0.5)

    def test_decline(self):
        pipeline = self._pipeline_with_scores([0.8, 0.4])
        # (0.4 - 0.8) / 0.8 = -0.5
        assert pipeline.run_score_relative_improvement() == pytest.approx(-0.5)

    def test_zero_first_returns_zero(self):
        pipeline = self._pipeline_with_scores([0.0, 0.8])
        assert pipeline.run_score_relative_improvement() == 0.0

    def test_returns_float(self):
        pipeline = self._pipeline_with_scores([0.6, 0.9])
        assert isinstance(pipeline.run_score_relative_improvement(), float)
