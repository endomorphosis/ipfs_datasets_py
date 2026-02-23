"""Tests for OntologyPipeline refine_mode options."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import MediatorState
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


def test_pipeline_agentic_refine_mode_uses_mediator_state():
    pipeline = OntologyPipeline()

    initial_ontology = {
        "entities": [{"id": "e1", "type": "Concept", "text": "alpha"}],
        "relationships": [],
        "metadata": {},
    }
    refined_ontology = {
        "entities": [{"id": "e1", "type": "Concept", "text": "alpha"}],
        "relationships": [],
        "metadata": {},
    }

    state = MediatorState(current_ontology=initial_ontology, max_rounds=3, target_score=0.85)
    state.add_round(initial_ontology, _score(0.4), "initial_generation")
    state.add_round(refined_ontology, _score(0.9), "agentic_round_1:test")
    state.converged = True

    class _StubMediator:
        max_rounds = 3

        def run_agentic_refinement_cycle(self, data, context):
            return state

    pipeline._mediator = _StubMediator()

    result = pipeline.run("sample", refine=True, refine_mode="agentic")

    assert result.ontology == refined_ontology
    assert result.actions_applied == ["agentic_round_1:test"]
