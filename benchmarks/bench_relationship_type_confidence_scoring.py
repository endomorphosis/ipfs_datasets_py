"""
Performance benchmark for relationship type confidence scoring.

Tests how the type confidence scoring algorithm scales with various
relationship types and pattern matching complexity.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    Entity,
)
from typing import List, Tuple


def _build_entities(n: int) -> List[Entity]:
    """Build n synthetic Entity objects for scoring test."""
    entities = []
    types_cycle = ["Person", "Organization", "Contract", "Obligation"]
    for i in range(n):
        entity_type = types_cycle[i % len(types_cycle)]
        entity = Entity(
            id=f"entity_{i}",
            type=entity_type,
            text=f"Entity{i}",
            confidence=0.95,
            properties={"index": i, "category": entity_type},
        )
        entities.append(entity)
    return entities


def _build_text_for_type(relationship_type: str, entity_count: int) -> str:
    """
    Generate text with various relationship patterns for scoring tests.
    
    Patterns include specific legal verbs, general verbs, and ambiguous phrasings.
    """
    sentences = []
    
    if relationship_type == "obligates":
        # Legal domain: specific obligation patterns
        for i in range(min(entity_count - 1, 10)):
            sentences.append(f"Entity{i} obligates Entity{i+1} to perform duties.")
    elif relationship_type == "employs":
        # Employment relationships
        for i in range(min(entity_count - 1, 10)):
            sentences.append(f"Entity{i} employs Entity{i+1}.")
    elif relationship_type == "owns":
        # Ownership relationships
        for i in range(min(entity_count - 1, 10)):
            sentences.append(f"Entity{i} owns Entity{i+1}.")
    elif relationship_type == "part_of":
        # Compositional (ambiguous) relationships
        for i in range(min(entity_count - 1, 10)):
            sentences.append(f"Entity{i} is part of Entity{i+1}.")
    elif relationship_type == "causes":
        # Causality (general)
        for i in range(min(entity_count - 1, 10)):
            sentences.append(f"Entity{i} causes Entity{i+1}.")
    elif relationship_type == "mixed":
        # Mixed patterns - tests discriminative scoring
        for i in range(min(entity_count - 1, 20)):
            if i % 4 == 0:
                sentences.append(f"Entity{i} obligates Entity{i+1}.")
            elif i % 4 == 1:
                sentences.append(f"Entity{i} employs Entity{i+1}.")
            elif i % 4 == 2:
                sentences.append(f"Entity{i} is part of Entity{i+1}.")
            else:
                sentences.append(f"Entity{i} works with Entity{i+1}.")
    
    return " ".join(sentences)


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
        domain="legal",  # Legal domain for better type confidence scoring
    )


@pytest.mark.parametrize(
    "rel_type,entity_count",
    [
        ("obligates", 20),  # Specific legal type with 20 entities
        ("employs", 20),    # Clear semantic type
        ("part_of", 20),    # Ambiguous type (harder scoring)
        ("mixed", 30),      # Mixed patterns (highest discrimination)
    ]
)
@pytest.mark.benchmark(group="relationship_type_confidence")
def test_relationship_type_confidence_scoring(benchmark, generator, context, rel_type, entity_count):
    """
    Benchmark relationship type confidence scoring across different relationship types.
    
    Tests:
    - Specific legal types (obligates): high confidence, fast matching
    - Clear semantic types (employs): medium-high confidence
    - Ambiguous types (part_of): lower confidence, more complex scoring
    - Mixed patterns: tests pattern discrimination and scoring complexity
    """
    entities = _build_entities(entity_count)
    text = _build_text_for_type(rel_type, entity_count)
    
    # Benchmark the scoring logic via relationship inference
    result = benchmark(lambda: generator.infer_relationships(entities, context, data=text))
    
    # Basic sanity checks
    assert result is not None
    assert isinstance(result, list)
    
    # Validate type confidence values are in valid range
    for rel in result:
        type_conf = getattr(rel, 'type_confidence', None)
        if type_conf is not None:
            assert 0.0 <= type_conf <= 1.0, f"Invalid confidence: {type_conf}"


@pytest.mark.benchmark(group="relationship_type_confidence")
def test_relationship_type_confidence_scoring_profile(benchmark, generator, context):
    """
    Profile confidence scoring across all types in one test.
    
    This helps identify which relationship types have higher scoring overhead.
    """
    all_types = ["obligates", "employs", "owns", "part_of", "causes"]
    results = []
    
    def score_all_types():
        for rel_type in all_types:
            entities = _build_entities(15)
            text = _build_text_for_type(rel_type, 15)
            rels = generator.infer_relationships(entities, context, data=text)
            results.append((rel_type, len(rels)))
        return results
    
    benchmark(score_all_types)
    
    # Verify all types were processed
    assert len(results) == 5
    assert all(count >= 0 for _, count in results)
