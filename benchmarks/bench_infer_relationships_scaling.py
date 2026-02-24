"""
Parametrized performance benchmark for OntologyGenerator.infer_relationships() scaling.

Tests how infer_relationships() scales with varying numbers of input entities.
Covers sizes [10, 25, 50, 100] to measure algorithm complexity.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    Entity,
)
from typing import List, Tuple


def _build_entities(n: int) -> List[Entity]:
    """Build n synthetic Entity objects with alternating types."""
    entities = []
    for i in range(n):
        entity_type = "Person" if i % 2 == 0 else "Organization"
        entity = Entity(
            id=f"entity_{i}",
            type=entity_type,
            text=f"Entity{i}",
            confidence=0.9,
            properties={"index": i},
        )
        entities.append(entity)
    return entities


def _build_text(n: int) -> str:
    """Generate n-1 relationship sentences for n entities."""
    sentences = []
    for i in range(n - 1):
        sentences.append(f"Entity{i} works for Entity{i+1}.")
    return " ".join(sentences)


def _case(size: int) -> Tuple[List[Entity], str]:
    """Generate entities and text for a given scaling case size."""
    entities = _build_entities(size)
    text = _build_text(size)
    return entities, text


@pytest.fixture
def generator():
    """Provide a configured OntologyGenerator instance."""
    return OntologyGenerator()


@pytest.fixture
def context():
    """Provide a configured OntologyGenerationContext instance."""
    return OntologyGenerationContext(
        data_source="benchmark_dataset",
        data_type="text",
        domain="general",
    )


@pytest.mark.parametrize("size", [10, 25, 50, 100])
@pytest.mark.parametrize("prefilter", [True, False])
@pytest.mark.benchmark(group="infer_relationships_scaling")
def test_infer_relationships_scaling(benchmark, generator, context, size, prefilter):
    """
    Benchmark infer_relationships() across different entity count scales.
    
    Tests scaling from 10 to 100 entities to measure algorithm complexity
    and compare pre-filtered vs unfiltered type-pair evaluation.
    """
    entities, text = _case(size)

    if not prefilter:
        original = generator._is_impossible_type_pair
        generator._is_impossible_type_pair = lambda *_args, **_kwargs: False

    try:
        result = benchmark(lambda: generator.infer_relationships(entities, context, data=text))
    finally:
        if not prefilter:
            generator._is_impossible_type_pair = original
    
    # Basic sanity check: should succeed
    assert result is not None
    assert isinstance(result, list)
