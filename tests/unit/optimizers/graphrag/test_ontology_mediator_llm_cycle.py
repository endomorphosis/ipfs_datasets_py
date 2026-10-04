"""Tests for OntologyMediator.run_llm_refinement_cycle()."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore


def _score(value: float) -> CriticScore:
    return CriticScore(
        completeness=value,
        consistency=value,
        clarity=value,
        granularity=value,
        relationship_coherence=value,
        domain_alignment=value,
    )


class _MockGenerator:
    def generate_ontology(self, data, context):
        return {
            "entities": [{"id": "e1", "type": "Concept", "text": "alpha"}],
            "relationships": [],
            "metadata": {},
        }

    def generate_with_feedback(self, data, context, feedback=None, critic=None):
        result = self.generate_ontology(data, context)
        result["metadata"]["feedback_applied"] = bool(feedback)
        result["metadata"]["feedback"] = feedback or {}
        return result


class _MockCritic:
    def __init__(self):
        self._scores = [_score(0.4), _score(0.9)]
        self._idx = 0

    def evaluate_ontology(self, ontology, context, source_data=None):
        score = self._scores[min(self._idx, len(self._scores) - 1)]
        self._idx += 1
        return score


class _MockAgent:
    def propose_feedback(self, ontology, score, context):
        return {"confidence_floor": 0.5}


def test_llm_refinement_cycle_converges_and_records_feedback():
    mediator = OntologyMediator(
        generator=_MockGenerator(),
        critic=_MockCritic(),
        max_rounds=3,
        convergence_threshold=0.85,
    )

    state = mediator.run_llm_refinement_cycle(
        data="sample",
        context=None,
        agent=_MockAgent(),
    )

    assert state.converged is True
    assert len(state.refinement_history) == 2
    assert state.refinement_history[-1]["agent_feedback"] == {"confidence_floor": 0.5}
