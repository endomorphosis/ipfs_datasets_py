"""Tests for sentence-window limiting in relationship inference."""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    DataType,
    Entity,
    ExtractionConfig,
    OntologyGenerationContext,
    OntologyGenerator,
)


@pytest.fixture
def generator():
    return OntologyGenerator()


def _build_entities():
    return [
        Entity(id="e1", text="Alice", type="Person"),
        Entity(id="e2", text="Carol", type="Organization"),
    ]


def test_sentence_window_blocks_distant_entities(generator):
    text = "Alice. Bob. Carol."
    context = OntologyGenerationContext(
        data_source="test_doc",
        data_type=DataType.TEXT,
        domain="general",
        config=ExtractionConfig(sentence_window=1),
    )

    relationships = generator.infer_relationships(_build_entities(), context, data=text)

    assert relationships == []


def test_sentence_window_allows_nearby_entities(generator):
    text = "Alice. Bob. Carol."
    context = OntologyGenerationContext(
        data_source="test_doc",
        data_type=DataType.TEXT,
        domain="general",
        config=ExtractionConfig(sentence_window=2),
    )

    relationships = generator.infer_relationships(_build_entities(), context, data=text)

    assert len(relationships) >= 1
