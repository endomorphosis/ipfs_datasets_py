"""Batch 327: Benchmark _merge_ontologies on 1000-entity ontologies."""

import time

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator


def _build_ontology(prefix: str, start: int, count: int) -> dict:
    entities = [
        {
            "id": f"e{i}",
            "text": f"{prefix} Entity {i}",
            "type": "Thing",
            "confidence": 0.8,
            "properties": {"source": prefix},
        }
        for i in range(start, start + count)
    ]
    relationships = [
        {
            "id": f"r{prefix}-{i}",
            "source_id": f"e{i}",
            "target_id": f"e{i + 1}",
            "type": "related_to",
            "confidence": 0.75,
        }
        for i in range(start, start + count - 1)
    ]
    return {
        "entities": entities,
        "relationships": relationships,
        "metadata": {"source": prefix},
    }


def test_merge_ontologies_benchmark_1000_entities():
    generator = OntologyGenerator(use_ipfs_accelerate=False)

    # 1000 base entities + 1000 extension entities with 500 ID overlap
    base = _build_ontology("base", start=0, count=1000)
    extension = _build_ontology("ext", start=500, count=1000)

    start = time.perf_counter()
    merged = generator._merge_ontologies(base, extension)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert isinstance(merged, dict)
    assert "entities" in merged
    assert "relationships" in merged
    assert len(merged["entities"]) == 1500  # 500 overlapping entity IDs deduped
    assert elapsed_ms < 5_000, f"_merge_ontologies(1000+1000) took {elapsed_ms:.0f}ms"
