"""Tests for merge_provenance tracking during ontology merges."""

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator


def test_merge_tracks_extension_provenance_for_new_items():
    """New entities/relationships from extension should record source provenance."""
    generator = OntologyGenerator()

    base = {
        "entities": [
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.9, "properties": {}},
        ],
        "relationships": [],
        "metadata": {"source": "base_doc"},
    }
    extension = {
        "entities": [
            {"id": "e2", "type": "Organization", "text": "Acme", "confidence": 0.8, "properties": {}},
        ],
        "relationships": [
            {
                "id": "r1",
                "source_id": "e1",
                "target_id": "e2",
                "type": "works_for",
                "confidence": 0.7,
                "properties": {},
            }
        ],
        "metadata": {"source": "doc2"},
    }

    merged = generator._merge_ontologies(base, extension)

    entity_e2 = next(e for e in merged["entities"] if e.get("id") == "e2")
    assert entity_e2.get("provenance") == ["doc2"]

    rel_r1 = next(r for r in merged["relationships"] if r.get("id") == "r1")
    assert rel_r1.get("provenance") == ["doc2"]

    assert merged["metadata"]["merged_from"] == ["doc2"]


def test_merge_appends_provenance_for_existing_entity():
    """Existing entity should record extension provenance when merged."""
    generator = OntologyGenerator()

    base = {
        "entities": [
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.5, "properties": {"role": "staff"}},
        ],
        "relationships": [],
        "metadata": {},
    }
    extension = {
        "entities": [
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.9, "properties": {"team": "legal"}},
        ],
        "relationships": [],
        "metadata": {"source": "doc2"},
    }

    merged = generator._merge_ontologies(base, extension)

    entity_e1 = next(e for e in merged["entities"] if e.get("id") == "e1")
    assert entity_e1.get("confidence") == 0.9
    assert entity_e1.get("properties", {}).get("role") == "staff"
    assert entity_e1.get("properties", {}).get("team") == "legal"
    assert entity_e1.get("provenance") == ["doc2"]


def test_merge_provenance_report_assigns_base_when_missing():
    """Report should treat missing provenance as base source."""
    generator = OntologyGenerator()

    ontology = {
        "entities": [
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.9, "properties": {}},
        ],
        "relationships": [],
        "metadata": {},
    }

    report = generator.generate_merge_provenance_report(ontology)

    assert "base" in report["unique_sources"]
    assert report["entity_counts_by_source"]["base"] == 1
    assert report["total_entities"] == 1
