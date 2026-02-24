"""Unit tests for OntologyCritic.score_batch_summary()."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    CriticScore,
    OntologyCritic,
)


def _score(v: float) -> CriticScore:
    return CriticScore(
        completeness=v,
        consistency=v,
        clarity=v,
        granularity=v,
        relationship_coherence=v,
        domain_alignment=v,
    )


def test_score_batch_summary_returns_expected_statistics() -> None:
    critic = OntologyCritic(use_llm=False)
    summary = critic.score_batch_summary([_score(0.2), _score(0.8)])

    assert summary == {
        "count": 2,
        "mean_overall": 0.5,
        "min_overall": 0.2,
        "max_overall": 0.8,
        "std_overall": 0.3,
    }


def test_score_batch_summary_requires_non_empty_input() -> None:
    critic = OntologyCritic(use_llm=False)
    with pytest.raises(ValueError, match="requires at least one score"):
        critic.score_batch_summary([])
