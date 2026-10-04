"""Batch 326: Profile OntologyCritic consistency evaluation on large ontologies."""

import time

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic


def _make_large_ontology(entity_count: int = 600, cyclic: bool = False) -> dict:
    entities = [
        {"id": f"e{i}", "text": f"Entity {i}", "type": "Thing", "confidence": 0.9}
        for i in range(entity_count)
    ]

    relationships = [
        {
            "id": f"r{i}",
            "source_id": f"e{i}",
            "target_id": f"e{i + 1}",
            "type": "is_a",
            "confidence": 0.8,
        }
        for i in range(entity_count - 1)
    ]

    if cyclic and entity_count > 2:
        relationships.append(
            {
                "id": "r-cycle",
                "source_id": f"e{entity_count - 1}",
                "target_id": "e0",
                "type": "is_a",
                "confidence": 0.8,
            }
        )

    return {"entities": entities, "relationships": relationships}


def test_profile_evaluate_consistency_large_acyclic_ontology():
    critic = OntologyCritic()
    ontology = _make_large_ontology(entity_count=600, cyclic=False)

    start = time.perf_counter()
    score = critic._evaluate_consistency(ontology, context=None)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert 0.0 <= score <= 1.0
    assert score > 0.9
    assert elapsed_ms < 2_000, f"_evaluate_consistency(600 acyclic) took {elapsed_ms:.0f}ms"


def test_profile_evaluate_consistency_large_cyclic_ontology():
    critic = OntologyCritic()
    ontology = _make_large_ontology(entity_count=600, cyclic=True)

    start = time.perf_counter()
    score = critic._evaluate_consistency(ontology, context=None)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert 0.0 <= score <= 1.0
    assert score < 1.0
    assert elapsed_ms < 2_000, f"_evaluate_consistency(600 cyclic) took {elapsed_ms:.0f}ms"
