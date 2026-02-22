"""End-to-end integration test: OntologyGenerator → OntologyCritic → OntologyMediator.

This test exercises the full pipeline with real (no-LLM) components using
rule-based extraction and the default OntologyCritic. It verifies that the
three components integrate correctly without mocking the core logic.
"""
from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    DataType,
    ExtractionStrategy,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import (
    OntologyMediator,
    MediatorState,
)
from ipfs_datasets_py.optimizers.common.base_session import BaseSession


SAMPLE_TEXT = """
Alice is a senior software engineer at TechCorp.
Bob manages Alice and owns several critical patents.
The Platform product belongs to the Engineering division.
TechCorp causes significant disruption in the software industry.
Alice must deliver the Platform project by end of quarter.
Bob employs five contractors to support the Platform rollout.
"""


@pytest.fixture(scope="module")
def generator():
    return OntologyGenerator()


@pytest.fixture(scope="module")
def critic():
    return OntologyCritic()


@pytest.fixture(scope="module")
def ctx():
    return OntologyGenerationContext(
        data_source="e2e_test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


class TestOntologyPipelineE2E:
    """E2E tests: generator → critic → mediator refinement loop."""

    def test_generator_produces_entities(self, generator, ctx):
        ontology = generator.generate_ontology(SAMPLE_TEXT, ctx)
        assert len(ontology["entities"]) > 0

    def test_multi_paragraph_text_extracts_multiple_entities(self, generator, ctx):
        """Multi-paragraph input should extract several entities."""
        multi_paragraph = (
            "Alice joined Contoso as a project manager in 2021.\n\n"
            "Bob leads the Engineering team at Contoso and supervises Alice.\n\n"
            "The Apollo product belongs to the Research division and supports clients."
        )
        ontology = generator.generate_ontology(multi_paragraph, ctx)
        assert len(ontology["entities"]) > 3

    def test_generator_produces_relationships(self, generator, ctx):
        ontology = generator.generate_ontology(SAMPLE_TEXT, ctx)
        assert len(ontology["relationships"]) > 0

    def test_critic_scores_generated_ontology(self, generator, critic, ctx):
        ontology = generator.generate_ontology(SAMPLE_TEXT, ctx)
        score = critic.evaluate_ontology(ontology, ctx, SAMPLE_TEXT)
        assert 0.0 <= score.overall <= 1.0

    def test_critic_returns_feedback(self, generator, critic, ctx):
        ontology = generator.generate_ontology(SAMPLE_TEXT, ctx)
        score = critic.evaluate_ontology(ontology, ctx, SAMPLE_TEXT)
        # Should have either recommendations or strengths
        has_feedback = bool(score.recommendations or score.strengths or score.weaknesses)
        assert has_feedback or score.overall > 0

    def test_mediator_run_refinement_cycle_returns_state(self, generator, critic, ctx):
        mediator = OntologyMediator(
            generator=generator,
            critic=critic,
            max_rounds=2,
            convergence_threshold=0.95,
        )
        state = mediator.run_refinement_cycle(SAMPLE_TEXT, ctx)
        assert isinstance(state, MediatorState)
        assert isinstance(state, BaseSession)

    def test_mediator_state_has_critic_scores(self, generator, critic, ctx):
        mediator = OntologyMediator(
            generator=generator,
            critic=critic,
            max_rounds=2,
            convergence_threshold=0.95,
        )
        state = mediator.run_refinement_cycle(SAMPLE_TEXT, ctx)
        assert len(state.critic_scores) > 0
        assert 0.0 <= state.critic_scores[-1].overall <= 1.0

    def test_mediator_state_has_ontology(self, generator, critic, ctx):
        mediator = OntologyMediator(
            generator=generator,
            critic=critic,
            max_rounds=2,
            convergence_threshold=0.95,
        )
        state = mediator.run_refinement_cycle(SAMPLE_TEXT, ctx)
        assert "entities" in state.current_ontology

    def test_mediator_state_has_refinement_history(self, generator, critic, ctx):
        mediator = OntologyMediator(
            generator=generator,
            critic=critic,
            max_rounds=3,
            convergence_threshold=0.99,  # unlikely to converge
        )
        state = mediator.run_refinement_cycle(SAMPLE_TEXT, ctx)
        assert len(state.refinement_history) > 0
        assert state.current_round == len(state.refinement_history)

    def test_pipeline_entities_have_expected_fields(self, generator, ctx):
        ontology = generator.generate_ontology(SAMPLE_TEXT, ctx)
        for entity in ontology["entities"]:
            assert "id" in entity
            assert "text" in entity
            assert "type" in entity

    def test_pipeline_relationships_have_direction_field(self, generator, ctx):
        ontology = generator.generate_ontology(SAMPLE_TEXT, ctx)
        for rel in ontology["relationships"]:
            assert "direction" in rel
            assert rel["direction"] in ("subject_to_object", "undirected", "unknown")
