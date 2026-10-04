"""Unit tests for additional OntologyCritic score helper methods."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    CriticScore,
    OntologyCritic,
)


def _score(v: float) -> CriticScore:
    return CriticScore(
        completeness=v,
        consistency=v + 0.01,
        clarity=v + 0.02,
        granularity=v + 0.03,
        relationship_coherence=v + 0.04,
        domain_alignment=v + 0.05,
    )


def test_dimension_scores_includes_relationship_coherence_and_overall() -> None:
    critic = OntologyCritic(use_llm=False)
    score = _score(0.5)

    dims = critic.dimension_scores(score)

    assert "relationship_coherence" in dims
    assert dims["relationship_coherence"] == 0.54
    assert "overall" in dims
    assert 0.0 <= dims["overall"] <= 1.0


def test_score_range_returns_expected_bounds_and_empty_fallback() -> None:
    critic = OntologyCritic(use_llm=False)
    s1 = _score(0.2)
    s2 = _score(0.8)

    lo, hi = critic.score_range([s1, s2])
    assert lo == s1.overall
    assert hi == s2.overall
    assert critic.score_range([]) == (0.0, 0.0)
