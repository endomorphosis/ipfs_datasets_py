"""Integration test: OntologyGenerator → OntologyCritic → OntologyMediator loop.

This exercises the real refinement loop end-to-end without requiring any LLM
backend by using rule-based extraction and heuristic scoring.
"""

from __future__ import annotations


def test_generator_critic_mediator_refinement_cycle_runs():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
        DataType,
        ExtractionConfig,
        ExtractionStrategy,
        OntologyGenerationContext,
        OntologyGenerator,
    )
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator

    generator = OntologyGenerator(use_ipfs_accelerate=False)
    critic = OntologyCritic(use_llm=False)
    mediator = OntologyMediator(
        generator=generator,
        critic=critic,
        max_rounds=3,
        convergence_threshold=0.99,
    )

    context = OntologyGenerationContext(
        data_source="integration_test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(),
    )
    data = (
        "Dr. Alice Smith met Bob Johnson at Acme Corp on January 1, 2024 in New York City. "
        "USD 1,000.00 was paid to Acme Corp. The obligation of Alice is to file the report."
    )

    state = mediator.run_refinement_cycle(data=data, context=context)

    assert state.refinement_history
    assert state.critic_scores
    assert len(state.refinement_history) == len(state.critic_scores)
    assert 1 <= len(state.refinement_history) <= mediator.max_rounds

    # Basic invariants for the final ontology structure.
    assert isinstance(state.current_ontology, dict)
    assert isinstance(state.current_ontology.get("entities"), list)
    assert isinstance(state.current_ontology.get("relationships"), list)

    # Ensure scores look sane.
    for score in state.critic_scores:
        overall = float(score.overall)
        assert 0.0 <= overall <= 1.0
