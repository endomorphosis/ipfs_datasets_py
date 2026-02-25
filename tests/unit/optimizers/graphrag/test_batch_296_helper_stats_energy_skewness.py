"""Batch-296 helper-stat regression tests.

Methods under test:
  - OntologyCritic.score_dimension_energy(score)
  - OntologyPipeline.run_score_velocity_skewness()
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic

    return OntologyCritic()


def _make_score(**overrides):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore

    payload = {
        "completeness": 0.0,
        "consistency": 0.0,
        "clarity": 0.0,
        "granularity": 0.0,
        "relationship_coherence": 0.0,
        "domain_alignment": 0.0,
    }
    payload.update(overrides)
    return CriticScore(**payload)


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline

    return OntologyPipeline()


def _set_run_history(pipeline, scores):
    pipeline._run_history = [  # type: ignore[attr-defined]
        SimpleNamespace(score=SimpleNamespace(overall=s)) for s in scores
    ]


class TestScoreDimensionEnergy:
    def test_all_zero_dimensions_returns_zero(self):
        critic = _make_critic()
        score = _make_score()

        assert critic.score_dimension_energy(score) == pytest.approx(0.0)

    def test_sum_of_squares_matches_expected(self):
        critic = _make_critic()
        score = _make_score(
            completeness=0.5,
            consistency=0.5,
            clarity=0.0,
            granularity=1.0,
            relationship_coherence=0.0,
            domain_alignment=0.0,
        )

        # 0.5^2 + 0.5^2 + 1.0^2 = 1.5
        assert critic.score_dimension_energy(score) == pytest.approx(1.5)


class TestRunScoreVelocitySkewness:
    def test_fewer_than_three_runs_returns_zero(self):
        pipeline = _make_pipeline()
        _set_run_history(pipeline, [0.2, 0.5])

        assert pipeline.run_score_velocity_skewness() == pytest.approx(0.0)

    def test_zero_when_velocity_std_is_zero(self):
        pipeline = _make_pipeline()
        _set_run_history(pipeline, [0.1, 0.3, 0.5, 0.7])

        assert pipeline.run_score_velocity_skewness() == pytest.approx(0.0)

    def test_positive_for_right_skewed_velocity_distribution(self):
        pipeline = _make_pipeline()
        # First differences: [0.1, 0.1, 0.5]
        _set_run_history(pipeline, [0.0, 0.1, 0.2, 0.7])

        assert pipeline.run_score_velocity_skewness() > 0.0

