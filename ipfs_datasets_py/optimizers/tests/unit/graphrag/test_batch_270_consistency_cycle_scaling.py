"""Batch 270: consistency cycle detection scaling and recursion safety tests."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_critic_consistency import (
    evaluate_consistency,
)


def _build_chain_ontology(entity_count: int, *, with_cycle: bool) -> dict:
    entities = [
        {"id": f"E{i}", "text": f"Entity {i}", "type": "Concept"}
        for i in range(entity_count)
    ]

    relationships = [
        {
            "id": f"R{i}",
            "source_id": f"E{i}",
            "target_id": f"E{i + 1}",
            "type": "is_a",
        }
        for i in range(entity_count - 1)
    ]

    if with_cycle and entity_count >= 3:
        relationships.append(
            {
                "id": "R_cycle",
                "source_id": f"E{entity_count - 1}",
                "target_id": "E0",
                "type": "part_of",
            }
        )

    return {"entities": entities, "relationships": relationships}


def test_deep_acyclic_chain_does_not_raise_recursion_error() -> None:
    ontology = _build_chain_ontology(2500, with_cycle=False)

    score = evaluate_consistency(ontology, context=None)

    assert score == 1.0


def test_deep_cycle_chain_detects_cycle_penalty() -> None:
    ontology = _build_chain_ontology(2500, with_cycle=True)

    score = evaluate_consistency(ontology, context=None)

    # With valid refs + no dup IDs, cycle penalty only impacts the 20% cycle term:
    # 0.5 * 1.0 + 0.3 * 1.0 + 0.2 * (1 - 0.15) = 0.97
    assert score == 0.97
