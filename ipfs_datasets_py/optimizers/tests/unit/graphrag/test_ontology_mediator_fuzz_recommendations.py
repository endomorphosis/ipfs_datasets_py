"""Fuzz tests for OntologyMediator refinement cycle recommendation handling."""

from __future__ import annotations

import random
import string
from unittest.mock import Mock

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerationContext,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import (
    MediatorState,
    OntologyMediator,
)


def _make_score(recommendations: list[str], overall: float = 0.4) -> CriticScore:
    # Keep all dimensions in [0,1]; overall is computed from them by property.
    return CriticScore(
        completeness=overall,
        consistency=overall,
        clarity=overall,
        granularity=overall,
        relationship_coherence=overall,
        domain_alignment=overall,
        strengths=["baseline"],
        weaknesses=["needs_improvement"],
        recommendations=recommendations,
    )


def test_run_refinement_cycle_handles_random_recommendation_strings() -> None:
    generator = Mock()
    critic = Mock()

    base_ontology = {
        "entities": [{"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.8}],
        "relationships": [],
        "metadata": {},
    }
    generator.generate_ontology.return_value = base_ontology

    mediator = OntologyMediator(
        generator=generator,
        critic=critic,
        max_rounds=2,
        convergence_threshold=0.85,
    )

    context = OntologyGenerationContext(
        data_source="unit-test",
        data_type="text",
        domain="general",
    )
    rnd = random.Random(1337)
    alphabet = string.ascii_letters + string.digits + string.punctuation + " \t\n"

    for _ in range(25):
        rec_count = rnd.randint(0, 12)
        recommendations = []
        for _ in range(rec_count):
            length = rnd.randint(0, 120)
            recommendations.append("".join(rnd.choice(alphabet) for _ in range(length)))

        # Two rounds: initial + one refinement evaluation
        critic.evaluate_ontology.side_effect = [
            _make_score(recommendations, overall=0.4),
            _make_score(recommendations, overall=0.45),
        ]

        state = mediator.run_refinement_cycle("Alice text", context)

        assert isinstance(state, MediatorState)
        assert len(state.refinement_history) >= 1
        assert len(state.critic_scores) >= 1
        assert state.current_ontology is not None
        assert state.total_time_ms >= 0.0
