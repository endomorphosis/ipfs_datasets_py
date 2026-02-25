"""Batch 310: Stress tests for OntologyMediator.run_agentic_refinement_cycle()."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator


class _StaticGenerator:
    def generate_ontology(self, data, context):
        return {
            "entities": [
                {"id": "e1", "type": "Concept", "text": "alpha"},
                {"id": "e2", "type": "Concept", "text": "beta"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "related_to"}
            ],
            "metadata": {},
        }


class _SequencedCritic:
    def __init__(self, scores: list[CriticScore]):
        self._scores = scores
        self._idx = 0

    def evaluate_ontology(self, ontology, context, source_data=None):
        score = self._scores[min(self._idx, len(self._scores) - 1)]
        self._idx += 1
        return score


def _score(v: float, recommendations: list[str] | None = None) -> CriticScore:
    return CriticScore(
        completeness=v,
        consistency=v,
        clarity=v,
        granularity=v,
        relationship_coherence=v,
        domain_alignment=v,
        recommendations=recommendations or ["Add missing properties"],
    )


def test_agentic_cycle_respects_round_limit_under_many_rounds():
    """Stress: cycle should terminate exactly at max rounds when no early-stop trigger fires."""
    round_limit = 25
    scores = [_score(0.20 + i * 0.01) for i in range(round_limit + 2)]

    mediator = OntologyMediator(
        generator=_StaticGenerator(),
        critic=_SequencedCritic(scores),
        max_rounds=round_limit,
        convergence_threshold=0.99,
    )
    mediator.suggest_refinement_strategy = lambda ontology, score, context: {
        "action": "add_missing_properties",
        "priority": "high",
    }

    state = mediator.run_agentic_refinement_cycle(
        data="sample",
        context=None,
        max_rounds=round_limit,
        min_improvement=0.0,
    )

    assert len(state.refinement_history) == round_limit
    assert state.current_round == round_limit
    assert float(state.metadata["final_score"]) < 0.99


def test_agentic_cycle_stops_when_improvement_stalls():
    """Stress: tiny per-round gains should trigger min_improvement early-stop guard."""
    scores = [_score(0.40 + i * 0.001) for i in range(60)]

    mediator = OntologyMediator(
        generator=_StaticGenerator(),
        critic=_SequencedCritic(scores),
        max_rounds=50,
        convergence_threshold=0.99,
    )
    mediator.suggest_refinement_strategy = lambda ontology, score, context: {
        "action": "normalize_names",
        "priority": "high",
    }

    state = mediator.run_agentic_refinement_cycle(
        data="sample",
        context=None,
        max_rounds=50,
        min_improvement=0.01,
    )

    assert state.current_round < 50
    assert len(state.refinement_history) == state.current_round
    assert state.metadata["score_trend"] in {"stable", "improving", "insufficient_data", "degrading"}
