"""Coverage for remaining optimizer/pipeline/alias helper methods."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def test_ontology_optimizer_rolling_best_plateau_and_min_max_helpers() -> None:
    optimizer = OntologyOptimizer(enable_tracing=False)
    optimizer._history = [  # type: ignore[attr-defined]
        OptimizationReport(average_score=0.20, trend="declining"),
        OptimizationReport(average_score=0.21, trend="improving"),
        OptimizationReport(average_score=0.205, trend="flat"),
        OptimizationReport(average_score=0.50, trend="improving"),
    ]

    assert optimizer.rolling_best(window=2).average_score == pytest.approx(0.50)
    assert optimizer.rolling_best(window=3).average_score == pytest.approx(0.50)
    assert optimizer.plateau_count(tol=0.01) == 2
    assert optimizer.min_score() == pytest.approx(0.20)
    assert optimizer.max_score() == pytest.approx(0.50)

    with pytest.raises(ValueError, match="window must be >= 1"):
        optimizer.rolling_best(window=0)


def test_ontology_pipeline_run_helpers_top_n_and_convergence_metrics() -> None:
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    pipeline._run_history = [  # type: ignore[attr-defined]
        SimpleNamespace(score=SimpleNamespace(overall=0.20), run_id="a"),
        SimpleNamespace(score=SimpleNamespace(overall=0.65), run_id="b"),
        SimpleNamespace(score=SimpleNamespace(overall=0.60), run_id="c"),
    ]

    assert pipeline.run_ids() == [0, 1, 2]
    assert [r.score.overall for r in pipeline.top_n_runs(2)] == [0.65, 0.60]
    assert pipeline.run_improvement() == pytest.approx(0.40)
    expected_mean_abs_delta = (abs(0.65 - 0.20) + abs(0.60 - 0.65)) / 2
    assert pipeline.stabilization_index(window=3) == pytest.approx(1.0 - expected_mean_abs_delta)


def test_critic_mediator_and_learning_adapter_alias_helpers() -> None:
    critic = OntologyCritic(use_llm=False)
    scores = [CriticScore(0.2, 0.2, 0.2, 0.2, 0.2, 0.2), CriticScore(0.7, 0.7, 0.7, 0.7, 0.7, 0.7)]
    assert critic.passing_rate(scores, threshold=0.6) == pytest.approx(0.5)

    mediator = OntologyMediator(generator=Mock(), critic=Mock())
    mediator.apply_action_bulk(["merge", "merge", "split"])
    assert mediator.most_used_action() == "merge"
    assert mediator.least_used_action() == "split"

    adapter = OntologyLearningAdapter()
    adapter.apply_feedback(0.1, actions=[])
    adapter.apply_feedback(0.3, actions=[])
    adapter.apply_feedback(0.9, actions=[])
    assert adapter.above_threshold_fraction(0.25) == pytest.approx(2 / 3)
    assert adapter.score_range() == pytest.approx((0.1, 0.9))
    assert adapter.improvement_trend(window=3) == pytest.approx((0.2 + 0.6) / 2)
