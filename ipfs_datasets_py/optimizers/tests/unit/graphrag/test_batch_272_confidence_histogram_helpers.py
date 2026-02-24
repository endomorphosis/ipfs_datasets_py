"""Batch 272: confidence histogram helper tests."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
)


def _result_with_confidences(values: list[float]) -> EntityExtractionResult:
    entities = [
        Entity(id=f"e{i}", type="Concept", text=f"Entity {i}", confidence=v)
        for i, v in enumerate(values)
    ]
    return EntityExtractionResult(entities=entities, relationships=[], confidence=0.8)


def test_entity_extraction_result_confidence_histogram_bucket_counts() -> None:
    result = _result_with_confidences([0.0, 0.24, 0.25, 0.5, 0.99, 1.0])

    hist = result.confidence_histogram(bins=4)

    assert hist == [2, 1, 1, 2]
    assert sum(hist) == len(result.entities)


def test_entity_extraction_result_confidence_histogram_validates_bins() -> None:
    result = _result_with_confidences([0.4])

    with pytest.raises(ValueError, match="bins must be >= 1"):
        result.confidence_histogram(bins=0)


def test_ontology_generator_confidence_histogram_labelled_buckets() -> None:
    generator = OntologyGenerator()
    result = _result_with_confidences([0.0, 0.24, 0.25, 0.5, 0.99, 1.0])

    hist = generator.confidence_histogram(result, bins=4)

    assert hist == {
        "0.00-0.25": 2,
        "0.25-0.50": 1,
        "0.50-0.75": 1,
        "0.75-1.00": 2,
    }
    assert sum(hist.values()) == len(result.entities)
