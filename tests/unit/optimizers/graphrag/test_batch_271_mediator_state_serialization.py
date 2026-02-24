"""Batch 271: MediatorState serialization round-trip tests."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import MediatorState


def _sample_ontology(suffix: str = "") -> dict:
    return {
        "entities": [
            {
                "id": f"entity_a{suffix}",
                "text": "Alice",
                "type": "Person",
                "confidence": 0.9,
            },
            {
                "id": f"entity_b{suffix}",
                "text": "Acme Corp",
                "type": "Organization",
                "confidence": 0.88,
            },
        ],
        "relationships": [
            {
                "id": f"rel_1{suffix}",
                "source_id": f"entity_a{suffix}",
                "target_id": f"entity_b{suffix}",
                "type": "works_for",
                "confidence": 0.84,
            }
        ],
        "metadata": {"domain": "business"},
    }


def _sample_score(base: float = 0.8) -> CriticScore:
    return CriticScore(
        completeness=base,
        consistency=base - 0.02,
        clarity=base - 0.04,
        granularity=base - 0.06,
        relationship_coherence=base - 0.01,
        domain_alignment=base - 0.03,
        strengths=["good structure"],
        weaknesses=["needs one more relation"],
        recommendations=["add missing relationships"],
        metadata={"source": "test"},
    )


def test_mediator_state_round_trip_preserves_core_fields() -> None:
    state = MediatorState(
        session_id="mediator-test-001",
        domain="graphrag",
        max_rounds=5,
        target_score=0.9,
        convergence_threshold=0.02,
        current_ontology=_sample_ontology("_0"),
    )
    state.add_round(_sample_ontology("_1"), _sample_score(0.75), "initial_generation")
    state.add_round(_sample_ontology("_2"), _sample_score(0.83), "add_missing_relationships")
    state.total_time_ms = 123.45
    state.converged = True
    state.metadata["final_score"] = state.critic_scores[-1].overall

    payload = state.to_dict()
    restored = MediatorState.from_dict(payload)

    assert restored.session_id == state.session_id
    assert restored.domain == state.domain
    assert restored.max_rounds == state.max_rounds
    assert restored.target_score == state.target_score
    assert restored.convergence_threshold == state.convergence_threshold
    assert restored.total_time_ms == state.total_time_ms
    assert restored.converged is True

    assert len(restored.rounds) == len(state.rounds)
    assert len(restored.refinement_history) == len(state.refinement_history)
    assert len(restored.critic_scores) == len(state.critic_scores)

    assert isinstance(restored.critic_scores[0], CriticScore)
    assert restored.critic_scores[-1].overall == state.critic_scores[-1].overall
    assert restored.current_ontology["entities"][0]["id"] == "entity_a_2"


def test_mediator_state_from_dict_handles_minimal_payload() -> None:
    restored = MediatorState.from_dict({"current_ontology": _sample_ontology()})

    assert restored.domain == "graphrag"
    assert restored.max_rounds == 10
    assert restored.refinement_history == []
    assert restored.critic_scores == []
    assert len(restored.rounds) == 0
    assert restored.current_ontology["entities"][0]["id"] == "entity_a"
