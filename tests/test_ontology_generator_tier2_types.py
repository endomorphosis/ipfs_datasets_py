"""Tests for TIER 2 ontology generator typed returns (Item 7).

Tests the type safety of TIER 2 ontology generator methods:
- extraction_statistics() -> ExtractionStatistics
- relationship_coherence_issues() -> RelationshipCoherenceIssues
- generate_synthetic_ontology() -> SyntheticOntologyResult
- Entity.to_dict() -> EntityDictSerialization
- Relationship.to_dict() -> RelationshipDictSerialization
"""

import pytest
from typing import Dict, Any, List, Tuple

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionStrategy,
    DataType,
    ExtractionConfig,
)
from ipfs_datasets_py.optimizers.graphrag.query_optimizer_types import (
    ExtractionStatistics,
    RelationshipCoherenceIssues,
    SyntheticOntologyResult,
    EntityDictSerialization,
    RelationshipDictSerialization,
)


class TestExtractionStatistics:
    """Tests for extraction_statistics() -> ExtractionStatistics."""

    def test_extraction_statistics_required_fields(self):
        """Verify ExtractionStatistics has all required fields present."""
        entities = [
            Entity(id="e1", type="Person", text="Alice", confidence=0.95),
            Entity(id="e2", type="Organization", text="ACME Corp", confidence=0.85),
            Entity(id="e3", type="Date", text="2024-01-15", confidence=0.9),
        ]
        relationships = [
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e2",
                type="works_for",
                confidence=0.8,
            ),
            Relationship(
                id="r2",
                source_id="e1",
                target_id="e3",
                type="dated",
                confidence=0.75,
            ),
        ]
        result = EntityExtractionResult(
            entities=entities, relationships=relationships, confidence=0.85
        )

        stats: ExtractionStatistics = result.extraction_statistics()

        # Verify required fields
        assert isinstance(stats, dict)
        assert "total_entities" in stats
        assert "total_relationships" in stats
        assert "unique_types" in stats
        assert "avg_confidence" in stats
        assert "min_confidence" in stats
        assert "max_confidence" in stats
        assert "entities_by_type" in stats
        assert "relationship_types" in stats
        assert "entities_with_properties" in stats
        assert "avg_text_length" in stats
        assert "dangling_relationships" in stats

    def test_extraction_statistics_field_types(self):
        """Verify ExtractionStatistics fields have correct types."""
        entities = [
            Entity(
                id="e1",
                type="Person",
                text="Bob",
                confidence=0.92,
                properties={"age": 30},
            ),
            Entity(id="e2", type="Person", text="Charlie", confidence=0.88),
        ]
        relationships = [
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e2",
                type="knows",
                confidence=0.85,
            )
        ]
        result = EntityExtractionResult(
            entities=entities, relationships=relationships, confidence=0.9
        )

        stats: ExtractionStatistics = result.extraction_statistics()

        # Type assertions
        assert isinstance(stats["total_entities"], int)
        assert stats["total_entities"] == 2
        assert isinstance(stats["total_relationships"], int)
        assert stats["total_relationships"] == 1
        assert isinstance(stats["unique_types"], int)
        assert stats["unique_types"] == 1  # Both are "Person"
        assert isinstance(stats["avg_confidence"], float)
        assert 0.0 <= stats["avg_confidence"] <= 1.0
        assert isinstance(stats["min_confidence"], float)
        assert isinstance(stats["max_confidence"], float)
        assert isinstance(stats["entities_by_type"], dict)
        assert "Person" in stats["entities_by_type"]
        assert isinstance(stats["entities_by_type"]["Person"], int)
        assert isinstance(stats["relationship_types"], list)
        assert "knows" in stats["relationship_types"]

    def test_extraction_statistics_empty_extraction(self):
        """Test ExtractionStatistics with no entities or relationships."""
        result = EntityExtractionResult(
            entities=[], relationships=[], confidence=0.0
        )

        stats: ExtractionStatistics = result.extraction_statistics()

        assert stats["total_entities"] == 0
        assert stats["total_relationships"] == 0
        assert stats["unique_types"] == 0
        assert stats["entities_by_type"] == {}
        assert stats["avg_confidence"] == 0.0


class TestRelationshipCoherenceIssues:
    """Tests for relationship_coherence_issues() -> RelationshipCoherenceIssues."""

    def test_relationship_coherence_issues_required_fields(self):
        """Verify RelationshipCoherenceIssues has all required fields."""
        entities = [
            Entity(id="e1", type="Person", text="Alice", confidence=0.95),
            Entity(id="e2", type="Person", text="Bob", confidence=0.1),  # Low confidence
        ]
        relationships = [
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e2",
                type="knows",
                confidence=0.3,  # Low confidence
            ),
            Relationship(
                id="r2",
                source_id="e2",
                target_id="e2",
                type="self_ref",
                confidence=0.5,  # Self-relationship
            ),
        ]
        result = EntityExtractionResult(
            entities=entities, relationships=relationships, confidence=0.5
        )

        issues: RelationshipCoherenceIssues = result.relationship_coherence_issues()

        # Verify required fields
        assert isinstance(issues, dict)
        assert "low_confidence_relationships" in issues
        assert "dangling_relationships" in issues
        assert "self_relationships" in issues
        assert "duplicate_relationships" in issues
        assert "high_degree_entities" in issues
        assert "total_issues" in issues

    def test_relationship_coherence_issues_detects_low_confidence(self):
        """Test detection of low confidence relationships."""
        entities = [
            Entity(id="e1", type="Entity", text="Entity1", confidence=0.9),
            Entity(id="e2", type="Entity", text="Entity2", confidence=0.9),
        ]
        relationships = [
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e2",
                type="rel1",
                confidence=0.3,  # Below threshold
            ),
            Relationship(
                id="r2",
                source_id="e1",
                target_id="e2",
                type="rel2",
                confidence=0.8,  # Above threshold
            ),
        ]
        result = EntityExtractionResult(
            entities=entities, relationships=relationships, confidence=0.65
        )

        issues: RelationshipCoherenceIssues = result.relationship_coherence_issues()

        # Should detect exactly 1 low confidence relationship
        assert len(issues["low_confidence_relationships"]) == 1
        assert issues["low_confidence_relationships"][0][0] == "r1"

    def test_relationship_coherence_issues_detects_self_relationships(self):
        """Test detection of self-referencing relationships."""
        entities = [Entity(id="e1", type="Entity", text="Entity1", confidence=0.9)]
        relationships = [
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e1",
                type="self_loop",
                confidence=0.8,
            )
        ]
        result = EntityExtractionResult(
            entities=entities, relationships=relationships, confidence=0.8
        )

        issues: RelationshipCoherenceIssues = result.relationship_coherence_issues()

        # Should detect the self-relationship
        assert len(issues["self_relationships"]) == 1
        assert issues["self_relationships"][0][0] == "r1"

    def test_relationship_coherence_issues_empty_result(self):
        """Test with no issues present."""
        entities = [
            Entity(id="e1", type="Entity", text="Entity1", confidence=0.9),
            Entity(id="e2", type="Entity", text="Entity2", confidence=0.9),
        ]
        relationships = [
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e2",
                type="rel",
                confidence=0.9,  # High confidence
            )
        ]
        result = EntityExtractionResult(
            entities=entities, relationships=relationships, confidence=0.9
        )

        issues: RelationshipCoherenceIssues = result.relationship_coherence_issues()

        assert len(issues["low_confidence_relationships"]) == 0
        assert len(issues["dangling_relationships"]) == 0
        assert len(issues["self_relationships"]) == 0
        assert issues["total_issues"] == 0


class TestSyntheticOntologyGeneration:
    """Tests for generate_synthetic_ontology() -> SyntheticOntologyResult."""

    def test_generate_synthetic_ontology_legal_domain(self):
        """Test synthetic ontology generation for legal domain."""
        generator = OntologyGenerator()

        result: SyntheticOntologyResult = generator.generate_synthetic_ontology(
            "legal", n_entities=3
        )

        # Verify structure
        assert isinstance(result, dict)
        assert "entities" in result
        assert "relationships" in result
        assert "metadata" in result
        assert "domain" in result

        # Verify content
        assert result["domain"] == "legal"
        assert len(result["entities"]) == 3
        assert result["metadata"]["synthetic"] is True
        assert result["metadata"]["domain"] == "legal"
        assert result["metadata"]["n_entities"] == 3

    def test_generate_synthetic_ontology_entity_structure(self):
        """Test that generated entities have correct structure."""
        generator = OntologyGenerator()

        result: SyntheticOntologyResult = generator.generate_synthetic_ontology(
            "medical", n_entities=2
        )

        # Check entity structure
        for entity_dict in result["entities"]:
            assert "id" in entity_dict
            assert "type" in entity_dict
            assert "text" in entity_dict
            assert "properties" in entity_dict
            assert "confidence" in entity_dict
            assert entity_dict["confidence"] == 0.9

    def test_generate_synthetic_ontology_relationship_structure(self):
        """Test that generated relationships have correct structure."""
        generator = OntologyGenerator()

        result: SyntheticOntologyResult = generator.generate_synthetic_ontology(
            "finance", n_entities=5
        )

        # Check relationship structure
        for rel_dict in result["relationships"]:
            assert "id" in rel_dict
            assert "source_id" in rel_dict
            assert "target_id" in rel_dict
            assert "type" in rel_dict
            assert "confidence" in rel_dict

    def test_generate_synthetic_ontology_default_domain(self):
        """Test synthetic ontology with invalid domain uses general templates."""
        generator = OntologyGenerator()

        result: SyntheticOntologyResult = generator.generate_synthetic_ontology(
            "unknown_domain", n_entities=4
        )

        assert result["domain"] == "unknown_domain"
        assert len(result["entities"]) == 4
        # Should use general domain types as fallback


class TestEntityDictSerialization:
    """Tests for Entity.to_dict() -> EntityDictSerialization."""

    def test_entity_to_dict_required_fields(self):
        """Test that Entity.to_dict() returns all required fields."""
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.95,
            properties={"age": 30, "location": "NYC"},
            source_span=(0, 5),
            last_seen=1234567890.0,
        )

        result: EntityDictSerialization = entity.to_dict()

        # Verify required fields
        assert isinstance(result, dict)
        assert "id" in result
        assert "type" in result
        assert "text" in result
        assert "confidence" in result
        assert "properties" in result
        assert "source_span" in result
        assert "last_seen" in result

    def test_entity_to_dict_field_types(self):
        """Test that Entity.to_dict() returns correct field types."""
        entity = Entity(
            id="e1",
            type="Organization",
            text="ACME Corp",
            confidence=0.85,
            properties={"founded": 2000},
            source_span=(10, 19),
        )

        result: EntityDictSerialization = entity.to_dict()

        assert isinstance(result["id"], str)
        assert result["id"] == "e1"
        assert isinstance(result["type"], str)
        assert result["type"] == "Organization"
        assert isinstance(result["text"], str)
        assert isinstance(result["confidence"], float)
        assert result["confidence"] == 0.85
        assert isinstance(result["properties"], dict)
        assert result["properties"]["founded"] == 2000
        assert isinstance(result["source_span"], (list, type(None)))
        if result["source_span"] is not None:
            assert len(result["source_span"]) == 2

    def test_entity_to_dict_none_source_span(self):
        """Test Entity.to_dict() with None source_span."""
        entity = Entity(
            id="e1", type="Concept", text="Concept1", confidence=0.7, source_span=None
        )

        result: EntityDictSerialization = entity.to_dict()

        assert result["source_span"] is None

    def test_entity_to_dict_preserves_properties(self):
        """Test that Entity.to_dict() preserves custom properties."""
        props = {"key1": "value1", "key2": [1, 2, 3], "key3": {"nested": "dict"}}
        entity = Entity(id="e1", type="Entity", text="Test", properties=props)

        result: EntityDictSerialization = entity.to_dict()

        assert result["properties"] == props


class TestRelationshipDictSerialization:
    """Tests for Relationship.to_dict() -> RelationshipDictSerialization."""

    def test_relationship_to_dict_required_fields(self):
        """Test that Relationship.to_dict() returns all required fields."""
        rel = Relationship(
            id="r1",
            source_id="e1",
            target_id="e2",
            type="knows",
            confidence=0.85,
            direction="bidirectional",
            properties={"intensity": "strong"},
        )

        result: RelationshipDictSerialization = rel.to_dict()

        # Verify required fields
        assert isinstance(result, dict)
        assert "id" in result
        assert "source_id" in result
        assert "target_id" in result
        assert "type" in result
        assert "confidence" in result
        assert "direction" in result
        assert "properties" in result

    def test_relationship_to_dict_field_types(self):
        """Test that Relationship.to_dict() returns correct field types."""
        rel = Relationship(
            id="r1",
            source_id="e1",
            target_id="e2",
            type="works_for",
            confidence=0.9,
            direction="subject_to_object",
        )

        result: RelationshipDictSerialization = rel.to_dict()

        assert isinstance(result["id"], str)
        assert result["id"] == "r1"
        assert isinstance(result["source_id"], str)
        assert result["source_id"] == "e1"
        assert isinstance(result["target_id"], str)
        assert result["target_id"] == "e2"
        assert isinstance(result["type"], str)
        assert result["type"] == "works_for"
        assert isinstance(result["confidence"], float)
        assert result["confidence"] == 0.9
        assert isinstance(result["direction"], str)

    def test_relationship_to_dict_preserves_properties(self):
        """Test that Relationship.to_dict() preserves custom properties."""
        props = {"weight": 0.5, "metadata": {"source": "inference"}}
        rel = Relationship(
            id="r1",
            source_id="e1",
            target_id="e2",
            type="related_to",
            properties=props,
        )

        result: RelationshipDictSerialization = rel.to_dict()

        assert result["properties"] == props

    def test_relationship_to_dict_default_direction(self):
        """Test Relationship.to_dict() with default direction."""
        rel = Relationship(
            id="r1", source_id="e1", target_id="e2", type="rel"
        )

        result: RelationshipDictSerialization = rel.to_dict()

        assert result["direction"] == "unknown"  # Default if not specified


class TestTIER2Integration:
    """Integration tests for all TIER 2 typed methods."""

    def test_full_extraction_with_tier2_types(self):
        """Test complete workflow using all TIER 2 typed methods."""
        # Create extraction result with meaningful data
        entities = [
            Entity(
                id="e1",
                type="Person",
                text="Alice Johnson",
                confidence=0.95,
                properties={"title": "CEO"},
                source_span=(0, 13),
            ),
            Entity(
                id="e2",
                type="Organization",
                text="Tech Corp",
                confidence=0.85,
                properties={"industry": "technology"},
                source_span=(30, 39),
            ),
            Entity(
                id="e3",
                type="Date",
                text="2024-01-15",
                confidence=0.9,
                source_span=(45, 55),
            ),
        ]

        relationships = [
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e2",
                type="works_for",
                confidence=0.9,
            ),
            Relationship(
                id="r2",
                source_id="e1",
                target_id="e3",
                type="dated",
                confidence=0.85,
            ),
        ]

        result = EntityExtractionResult(
            entities=entities, relationships=relationships, confidence=0.88
        )

        # Test extraction_statistics() -> ExtractionStatistics
        stats: ExtractionStatistics = result.extraction_statistics()
        assert stats["total_entities"] == 3
        assert stats["total_relationships"] == 2
        assert stats["unique_types"] == 3
        assert stats["avg_confidence"] > 0.8

        # Test relationship_coherence_issues() -> RelationshipCoherenceIssues
        issues: RelationshipCoherenceIssues = result.relationship_coherence_issues()
        assert issues["total_issues"] == 0  # No issues in clean data

        # Test Entity.to_dict() -> EntityDictSerialization for each entity
        for entity in entities:
            entity_dict: EntityDictSerialization = entity.to_dict()
            assert entity_dict["id"]
            assert entity_dict["type"]
            assert entity_dict["text"]

        # Test Relationship.to_dict() -> RelationshipDictSerialization
        for rel in relationships:
            rel_dict: RelationshipDictSerialization = rel.to_dict()
            assert rel_dict["id"]
            assert rel_dict["source_id"]
            assert rel_dict["target_id"]
            assert rel_dict["type"]

        # Test generate_synthetic_ontology() -> SyntheticOntologyResult
        generator = OntologyGenerator()
        synthetic: SyntheticOntologyResult = generator.generate_synthetic_ontology(
            "general", n_entities=5
        )
        assert len(synthetic["entities"]) == 5
        assert "relationships" in synthetic

    def test_tier2_type_consistency(self):
        """Verify TIER 2 types work consistently across multiple calls."""
        generator = OntologyGenerator()

        # Create multiple synthetic ontologies
        for domain in ["legal", "medical", "finance"]:
            result: SyntheticOntologyResult = generator.generate_synthetic_ontology(
                domain, n_entities=3
            )
            assert result["domain"] == domain
            assert len(result["entities"]) == 3

            # Verify all entities are serializable
            for entity_dict in result["entities"]:
                # This simulates the EntityDictSerialization type
                assert "id" in entity_dict
                assert "type" in entity_dict
                assert "text" in entity_dict

        # Create extraction result
        entities = [
            Entity(id=f"e{i}", type="Entity", text=f"Entity{i}", confidence=0.8 + i * 0.05)
            for i in range(3)
        ]
        relationships = [
            Relationship(
                id="r1",
                source_id="e0",
                target_id="e1",
                type="rel",
                confidence=0.85,
            )
        ]
        result = EntityExtractionResult(
            entities=entities, relationships=relationships, confidence=0.82
        )

        # Verify statistics are consistent
        stats1: ExtractionStatistics = result.extraction_statistics()
        stats2: ExtractionStatistics = result.extraction_statistics()

        assert stats1["total_entities"] == stats2["total_entities"]
        assert stats1["total_relationships"] == stats2["total_relationships"]
