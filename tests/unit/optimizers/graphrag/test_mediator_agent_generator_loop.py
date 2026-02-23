"""Integration test: mediator -> agent -> generator loop.

Validates that OntologyMediator.run_llm_refinement_cycle() calls the agent for
feedback, passes it into the generator, and applies feedback to the ontology.
"""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    DataType,
    ExtractionStrategy,
)


def _score(value: float) -> CriticScore:
    return CriticScore(
        completeness=value,
        consistency=value,
        clarity=value,
        granularity=value,
        relationship_coherence=value,
        domain_alignment=value,
    )


class _StubGenerator(OntologyGenerator):
    def __init__(self) -> None:
        super().__init__(use_ipfs_accelerate=False)

    def generate_ontology(self, data, context):
        return {
            "entities": [
                {
                    "id": "e1",
                    "type": "Concept",
                    "text": "alpha",
                    "confidence": 0.4,
                },
                {
                    "id": "e2",
                    "type": "Concept",
                    "text": "beta",
                    "confidence": 0.9,
                },
            ],
            "relationships": [],
            "metadata": {},
        }


class _StubCritic:
    def __init__(self):
        self._scores = [_score(0.4), _score(0.9)]
        self._idx = 0

    def evaluate_ontology(self, ontology, context, source_data=None):
        score = self._scores[min(self._idx, len(self._scores) - 1)]
        self._idx += 1
        return score


class _StubAgent:
    def propose_feedback(self, ontology, score, context):
        return {"confidence_floor": 0.6}


def test_mediator_agent_generator_loop_applies_feedback():
    generator = _StubGenerator()
    critic = _StubCritic()
    mediator = OntologyMediator(
        generator=generator,
        critic=critic,
        max_rounds=3,
        convergence_threshold=0.85,
    )

    context = OntologyGenerationContext(
        data_source="test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )

    state = mediator.run_llm_refinement_cycle(
        data="sample",
        context=context,
        agent=_StubAgent(),
    )

    assert state.converged is True
    assert len(state.refinement_history) == 2
    assert state.refinement_history[-1]["agent_feedback"] == {"confidence_floor": 0.6}

    # Feedback should remove the low-confidence entity
    assert len(state.current_ontology["entities"]) == 1
    assert state.current_ontology["entities"][0]["id"] == "e2"
    assert state.current_ontology["metadata"]["feedback_applied"] is True
