"""Tests for OntologyMediator.run_agentic_refinement_cycle()."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore


def _score(
    completeness: float,
    consistency: float,
    clarity: float,
    granularity: float,
    relationship_coherence: float,
    domain_alignment: float,
    recommendations: list[str] | None = None,
) -> CriticScore:
    return CriticScore(
        completeness=completeness,
        consistency=consistency,
        clarity=clarity,
        granularity=granularity,
        relationship_coherence=relationship_coherence,
        domain_alignment=domain_alignment,
        recommendations=recommendations or [],
    )


class _MockGenerator:
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


class _MockCritic:
    def __init__(self, scores: list[CriticScore]):
        self._scores = scores
        self._idx = 0

    def evaluate_ontology(self, ontology, context, source_data=None):
        score = self._scores[min(self._idx, len(self._scores) - 1)]
        self._idx += 1
        return score


def test_agentic_cycle_converges_and_records_strategy():
    scores = [
        _score(
            completeness=0.4,
            consistency=0.4,
            clarity=0.4,
            granularity=0.4,
            relationship_coherence=0.4,
            domain_alignment=0.4,
            recommendations=[
                "Improve clarity by adding property definitions",
                "Add property details to entities",
            ],
        ),
        _score(
            completeness=0.9,
            consistency=0.9,
            clarity=0.9,
            granularity=0.9,
            relationship_coherence=0.9,
            domain_alignment=0.9,
        ),
    ]

    mediator = OntologyMediator(
        generator=_MockGenerator(),
        critic=_MockCritic(scores),
        max_rounds=3,
        convergence_threshold=0.85,
    )

    state = mediator.run_agentic_refinement_cycle(data="sample", context=None)

    assert state.converged is True
    assert len(state.refinement_history) >= 2

    last_round = state.refinement_history[-1]
    assert last_round["action"].startswith("agentic_round_1:")
    assert last_round["strategy"]["action"] == "add_missing_properties"
