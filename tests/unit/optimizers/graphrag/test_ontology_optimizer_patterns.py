from __future__ import annotations


def test_identify_patterns_computes_common_types_and_averages() -> None:
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer

    optimizer = OntologyOptimizer()

    ontologies = [
        {
            "entities": [
                {"id": "e1", "type": "Person", "properties": {"age": 30}},
                {"id": "e2", "type": "Person", "properties": {"age": 31}},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"}
            ],
        },
        {
            "entities": [
                {"id": "e3", "type": "Company", "properties": {"name": "Acme"}},
            ],
            "relationships": [],
        },
    ]

    patterns = optimizer.identify_patterns(ontologies)

    assert isinstance(patterns, dict)
    assert patterns.get("sample_size") == 2

    assert patterns.get("avg_entity_count") == 1.5
    assert patterns.get("avg_relationship_count") == 0.5

    common_entity_types = patterns.get("common_entity_types")
    assert isinstance(common_entity_types, list)
    assert set(common_entity_types) >= {"Person", "Company"}

    common_relationship_types = patterns.get("common_relationship_types")
    assert isinstance(common_relationship_types, list)
    assert "knows" in common_relationship_types

    common_properties = patterns.get("common_properties")
    assert isinstance(common_properties, list)
    assert set(common_properties) >= {"age", "name"}
