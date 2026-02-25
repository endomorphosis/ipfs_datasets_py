"""Batch 302: Fuzz tests for OntologyMediator.refine_ontology recommendation handling.

These tests stress recommendation parsing with randomized text payloads and ensure
refinement remains stable, non-mutating, and structurally valid.
"""

from __future__ import annotations

import copy

from hypothesis import given, settings, strategies as st

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator


def _score(recommendations: list[str]) -> CriticScore:
    return CriticScore(
        completeness=0.5,
        consistency=0.5,
        clarity=0.5,
        granularity=0.5,
        relationship_coherence=0.5,
        domain_alignment=0.5,
        recommendations=recommendations,
    )


def _base_ontology() -> dict:
    return {
        "entities": [
            {"id": "e0", "text": "Alice", "type": "Person", "confidence": 0.9},
            {"id": "e1", "text": "Bob", "type": "Person", "confidence": 0.8},
            {"id": "e2", "text": "Contract", "type": "Concept", "confidence": 0.7},
        ],
        "relationships": [
            {"id": "r0", "source_id": "e0", "target_id": "e1", "type": "knows", "confidence": 0.7}
        ],
        "metadata": {"source": "fuzz-test"},
        "domain": "general",
    }


def _mediator() -> OntologyMediator:
    return OntologyMediator(generator=OntologyGenerator(use_ipfs_accelerate=False), critic=OntologyCritic(use_llm=False))


@settings(max_examples=60, deadline=None)
@given(
    recommendations=st.lists(
        st.text(min_size=0, max_size=200),
        min_size=0,
        max_size=12,
    )
)
def test_refine_ontology_fuzz_recommendations_structural_invariants(recommendations: list[str]) -> None:
    """Random recommendation strings should not break structural output invariants."""
    mediator = _mediator()
    ontology = _base_ontology()

    refined = mediator.refine_ontology(ontology, _score(recommendations), context=None)

    assert isinstance(refined, dict)
    assert "entities" in refined and isinstance(refined["entities"], list)
    assert "relationships" in refined and isinstance(refined["relationships"], list)
    assert "metadata" in refined and isinstance(refined["metadata"], dict)
    assert "refinement_actions" in refined["metadata"]
    assert isinstance(refined["metadata"]["refinement_actions"], list)


@settings(max_examples=40, deadline=None)
@given(
    recommendations=st.lists(
        st.text(min_size=0, max_size=120),
        min_size=0,
        max_size=8,
    )
)
def test_refine_ontology_fuzz_does_not_mutate_input(recommendations: list[str]) -> None:
    """Random recommendation strings should not mutate input ontology in place."""
    mediator = _mediator()
    ontology = _base_ontology()
    original = copy.deepcopy(ontology)

    _ = mediator.refine_ontology(ontology, _score(recommendations), context=None)

    assert ontology == original


@settings(max_examples=30, deadline=None)
@given(
    recommendations=st.lists(
        st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=80),
        min_size=0,
        max_size=10,
    )
)
def test_refine_ontology_fuzz_actions_are_strings(recommendations: list[str]) -> None:
    """Refinement action entries should always be strings under random recommendation text."""
    mediator = _mediator()

    refined = mediator.refine_ontology(_base_ontology(), _score(recommendations), context=None)
    actions = refined.get("metadata", {}).get("refinement_actions", [])

    assert all(isinstance(action, str) for action in actions)
