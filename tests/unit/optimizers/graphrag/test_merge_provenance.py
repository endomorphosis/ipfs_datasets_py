"""Tests for OntologyGenerator.generate_merge_provenance_report method."""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator


class TestGenerateMergeProvenanceReport:
    """Test suite for merge provenance report generation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.generator = OntologyGenerator()

    def test_empty_ontology(self):
        """Test with empty ontology."""
        ontology = {"entities": [], "relationships": [], "metadata": {}}
        report = self.generator.generate_merge_provenance_report(ontology)

        assert report["total_entities"] == 0
        assert report["total_relationships"] == 0
        assert report["unique_sources"] == []
        assert report["entity_counts_by_source"] == {}
        assert report["relationship_counts_by_source"] == {}

    def test_single_source_entities(self):
        """Test ontology with entities from single source."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice"},
                {"id": "e2", "type": "Organization", "text": "ACME"},
            ],
            "relationships": [],
            "metadata": {"source": "doc1"},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        assert report["total_entities"] == 2
        assert "base" in report["unique_sources"]  # Implicit provenance
        assert report["entities_by_source"]["base"] == ["e1", "e2"]

    def test_multiple_sources(self):
        """Test ontology with entities from multiple sources."""
        ontology = {
            "entities": [
                {
                    "id": "e1",
                    "type": "Person",
                    "text": "Alice",
                    "provenance": ["doc1"],
                },
                {
                    "id": "e2",
                    "type": "Organization",
                    "text": "ACME",
                    "provenance": ["doc2"],
                },
                {
                    "id": "e3",
                    "type": "Location",
                    "text": "CA",
                    "provenance": ["doc1", "doc3"],
                },
            ],
            "relationships": [],
            "metadata": {"merged_from": ["doc1", "doc2", "doc3"]},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        assert report["total_entities"] == 3
        assert set(report["unique_sources"]) == {"doc1", "doc2", "doc3"}
        assert report["entity_counts_by_source"]["doc1"] == 2  # e1, e3
        assert report["entity_counts_by_source"]["doc2"] == 1  # e2
        assert report["entity_counts_by_source"]["doc3"] == 1  # e3

    def test_merged_entities_tracking(self):
        """Test tracking of merged vs new entities."""
        ontology = {
            "entities": [
                {"id": "e1", "provenance": ["doc1"]},  # New entity
                {"id": "e2", "provenance": ["doc1", "doc2"]},  # Merged entity
                {"id": "e3", "provenance": ["doc2"]},  # New entity
            ],
            "relationships": [],
            "metadata": {},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        assert report["integration_stats"]["merged_entities"] == 1
        assert report["integration_stats"]["new_entities"] == 2
        assert report["integration_stats"]["total_entities"] == 3

    def test_relationship_provenance(self):
        """Test relationship provenance tracking."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Organization"},
            ],
            "relationships": [
                {
                    "id": "r1",
                    "source_id": "e1",
                    "target_id": "e2",
                    "type": "works_at",
                    "provenance": ["doc1"],
                },
                {
                    "id": "r2",
                    "source_id": "e2",
                    "target_id": "e1",
                    "type": "employs",
                    "provenance": ["doc2"],
                },
            ],
            "metadata": {},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        assert report["total_relationships"] == 2
        assert report["relationship_counts_by_source"]["doc1"] == 1
        assert report["relationship_counts_by_source"]["doc2"] == 1
        assert report["relationships_by_source"]["doc1"] == ["r1"]
        assert report["relationships_by_source"]["doc2"] == ["r2"]

    def test_implicit_provenance_fallback(self):
        """Test fallback to 'base' provenance when not specified."""
        ontology = {
            "entities": [
                {"id": "e1"},  # No provenance specified
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e1"},  # No provenance
            ],
            "metadata": {},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        assert "base" in report["unique_sources"]
        assert report["entity_counts_by_source"]["base"] == 1
        assert report["relationship_counts_by_source"]["base"] == 1

    def test_complex_merge_scenario(self):
        """Test complex real-world merge scenario."""
        ontology = {
            "entities": [
                # From doc1
                {
                    "id": "person_alice",
                    "type": "Person",
                    "text": "Alice",
                    "provenance": ["doc1"],
                },
                # From doc2
                {
                    "id": "org_acme",
                    "type": "Organization",
                    "text": "ACME Corp",
                    "provenance": ["doc2"],
                },
                # Merged: appeared in both doc1 and doc2
                {
                    "id": "location_sf",
                    "type": "Location",
                    "text": "San Francisco",
                    "provenance": ["doc1", "doc2"],
                },
                # From doc3
                {
                    "id": "role_ceo",
                    "type": "Role",
                    "text": "CEO",
                    "provenance": ["doc3"],
                },
            ],
            "relationships": [
                {
                    "id": "rel1",
                    "source_id": "person_alice",
                    "target_id": "org_acme",
                    "type": "works_at",
                    "provenance": ["doc1", "doc2"],  # Merged relationship
                },
                {
                    "id": "rel2",
                    "source_id": "org_acme",
                    "target_id": "location_sf",
                    "type": "located_in",
                    "provenance": ["doc2"],
                },
            ],
            "metadata": {"merged_from": ["doc1", "doc2", "doc3"]},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        # Check summary stats
        assert report["total_entities"] == 4
        assert report["total_relationships"] == 2
        assert set(report["unique_sources"]) == {"doc1", "doc2", "doc3"}

        # Check entity distribution
        assert report["entity_counts_by_source"]["doc1"] == 2  # person_alice, location_sf
        assert report["entity_counts_by_source"]["doc2"] == 2  # org_acme, location_sf
        assert report["entity_counts_by_source"]["doc3"] == 1  # role_ceo

        # Check merged vs new
        assert report["integration_stats"]["merged_entities"] == 1  # location_sf
        assert report["integration_stats"]["new_entities"] == 3
        assert report["integration_stats"]["merged_relationships"] == 1  # rel1
        assert report["integration_stats"]["new_relationships"] == 1  # rel2

    def test_entity_id_list_no_duplicates(self):
        """Test that entity ID lists don't contain duplicates."""
        ontology = {
            "entities": [
                {
                    "id": "e1",
                    "provenance": ["doc1", "doc1"],  # Duplicate source in provenance
                },
            ],
            "relationships": [],
            "metadata": {},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        # Even with duplicate provenance, entity should only appear once in the list
        assert report["entities_by_source"]["doc1"].count("e1") == 1

    def test_report_structure(self):
        """Test report structure contains all expected keys."""
        ontology = {
            "entities": [{"id": "e1"}],
            "relationships": [{"id": "r1", "source_id": "e1", "target_id": "e1"}],
            "metadata": {},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        required_keys = {
            "merged_from",
            "entity_counts_by_source",
            "relationship_counts_by_source",
            "entities_by_source",
            "relationships_by_source",
            "total_entities",
            "total_relationships",
            "unique_sources",
            "integration_stats",
        }
        assert required_keys.issubset(set(report.keys()))

    def test_integration_stats_structure(self):
        """Test integration stats structure."""
        ontology = {
            "entities": [{"id": "e1", "provenance": ["doc1", "doc2"]}],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e1", "provenance": ["doc1"]}
            ],
            "metadata": {},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        stats = report["integration_stats"]
        required_stat_keys = {
            "merged_entities",
            "new_entities",
            "total_entities",
            "merged_relationships",
            "new_relationships",
            "total_relationships",
        }
        assert required_stat_keys.issubset(set(stats.keys()))

    def test_metadata_merged_from(self):
        """Test extraction of merged_from metadata."""
        ontology = {
            "entities": [],
            "relationships": [],
            "metadata": {"merged_from": ["source1", "source2", "source3"]},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        assert report["merged_from"] == ["source1", "source2", "source3"]

    def test_invalid_entities_skipped(self):
        """Test that invalid entity structures are skipped."""
        ontology = {
            "entities": [
                {"id": "e1"},  # Valid
                "invalid_entity",  # Invalid: not a dict
                None,  # Invalid: None
                {"id": "e2"},  # Valid
            ],
            "relationships": [],
            "metadata": {},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        assert report["total_entities"] == 2  # Only valid entities counted

    def test_missing_metadata(self):
        """Test handling of missing or empty metadata."""
        ontology = {
            "entities": [{"id": "e1"}],
            "relationships": [],
            # No metadata key
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        assert report["merged_from"] == []  # Falls back to empty list
        assert len(report["unique_sources"]) > 0  # Still tracks provenance from entities

    def test_unique_sources_sorted(self):
        """Test that unique sources are sorted."""
        ontology = {
            "entities": [
                {"id": "e1", "provenance": ["zebra"]},
                {"id": "e2", "provenance": ["alpha"]},
                {"id": "e3", "provenance": ["bravo"]},
            ],
            "relationships": [],
            "metadata": {},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        assert report["unique_sources"] == ["alpha", "bravo", "zebra"]

    def test_large_ontology_performance(self):
        """Test report generation on a large ontology."""
        # Create a large ontology
        entities = [
            {
                "id": f"e{i}",
                "type": f"Type{i % 5}",
                "provenance": [f"doc{i % 10}"],
            }
            for i in range(100)
        ]
        relationships = [
            {
                "id": f"r{i}",
                "source_id": f"e{i}",
                "target_id": f"e{(i + 1) % 100}",
                "type": "related_to",
                "provenance": [f"doc{i % 10}"],
            }
            for i in range(100)
        ]

        ontology = {
            "entities": entities,
            "relationships": relationships,
            "metadata": {"merged_from": [f"doc{i}" for i in range(10)]},
        }

        report = self.generator.generate_merge_provenance_report(ontology)

        assert report["total_entities"] == 100
        assert report["total_relationships"] == 100
        assert len(report["unique_sources"]) == 10

    def test_report_with_explicit_entity_ids(self):
        """Test report includes correct entity IDs."""
        ontology = {
            "entities": [
                {"id": "person_001", "type": "Person", "provenance": ["doc1"]},
                {"id": "org_002", "type": "Organization", "provenance": ["doc2"]},
                {"id": "loc_003", "type": "Location", "provenance": ["doc1", "doc2"]},
            ],
            "relationships": [],
            "metadata": {},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        assert "person_001" in report["entities_by_source"]["doc1"]
        assert "org_002" in report["entities_by_source"]["doc2"]
        assert "loc_003" in report["entities_by_source"]["doc1"]
        assert "loc_003" in report["entities_by_source"]["doc2"]

    def test_relationship_with_missing_id(self):
        """Test handling of relationships with missing ID field."""
        ontology = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [
                {
                    "source_id": "e1",
                    "target_id": "e2",
                    "type": "rel1",
                    # No 'id' field
                    "provenance": ["doc1"],
                },
            ],
            "metadata": {},
        }
        report = self.generator.generate_merge_provenance_report(ontology)

        # Should still track the relationship
        assert report["total_relationships"] == 1
        assert report["relationship_counts_by_source"]["doc1"] == 1
