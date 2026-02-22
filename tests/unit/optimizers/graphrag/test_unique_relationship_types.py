"""Unit tests for OntologyGenerator.unique_relationship_types().

Tests cover:
- Empty results
- Single relationship type
- Multiple  relationship types
- Duplicate types (deduplication)
- Ordering (alphabetical sort)
- Integration with extraction results
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    Entity,
    Relationship,
    EntityExtractionResult,
)


class TestUniqueRelationshipTypes:
    """Test OntologyGenerator.unique_relationship_types()."""

    @pytest.fixture
    def generator(self):
        """Provide an OntologyGenerator instance."""
        return OntologyGenerator()

    @pytest.fixture
    def sample_entities(self):
        """Provide sample entities for testing."""
        return [
            Entity(id="e1", text="Alice", type="Person", confidence=0.9),
            Entity(id="e2", text="Bob", type="Person", confidence=0.8),
            Entity(id="e3", text="Company X", type="Organization", confidence=0.85),
        ]

    def test_empty_result_returns_empty_list(self, generator):
        """Empty result should return empty list."""
        result = EntityExtractionResult(
            entities=[],
            relationships=[],
            confidence=1.0,
        )
        
        types = generator.unique_relationship_types(result)
        
        assert types == []
        assert isinstance(types, list)

    def test_single_relationship_type(self, generator, sample_entities):
        """Result with one relationship type should return single-item list."""
        result = EntityExtractionResult(
            entities=sample_entities,
            relationships=[
                Relationship(
                    id="r1",
                    source_id="e1",
                    target_id="e2",
                    type="knows",
                    confidence=0.7,
                    direction="bidirectional",
                ),
            ],
            confidence=0.8,
        )
        
        types = generator.unique_relationship_types(result)
        
        assert types == ["knows"]

    def test_multiple_distinct_types(self, generator, sample_entities):
        """Multiple distinct types should all be returned."""
        result = EntityExtractionResult(
            entities=sample_entities,
            relationships=[
                Relationship("r1", "e1", "e2", "knows", 0.7, "bidirectional"),
                Relationship("r2", "e1", "e3", "works_for", 0.8, "directional"),
                Relationship("r3", "e2", "e3", "employed_by", 0.75, "directional"),
            ],
            confidence=0.75,
        )
        
        types = generator.unique_relationship_types(result)
        
        assert set(types) == {"knows", "works_for", "employed_by"}
        assert len(types) == 3

    def test_duplicate_types_are_deduplicated(self, generator, sample_entities):
        """Duplicate types should appear only once."""
        result = EntityExtractionResult(
            entities=sample_entities,
            relationships=[
                Relationship("r1", "e1", "e2", "knows", 0.7, "bidirectional"),
                Relationship("r2", "e1", "e3", "knows", 0.6, "bidirectional"),
                Relationship("r3", "e2", "e3", "works_for", 0.8, "directional"),
                Relationship("r4", "e3", "e1", "works_for", 0.75, "directional"),
            ],
            confidence=0.75,
        )
        
        types = generator.unique_relationship_types(result)
        
        assert set(types) == {"knows", "works_for"}
        assert len(types) == 2

    def test_types_are_sorted_alphabetically(self, generator, sample_entities):
        """Types should be returned in sorted order."""
        result = EntityExtractionResult(
            entities=sample_entities,
            relationships=[
                Relationship("r1", "e1", "e2", "zebra_relation", 0.7, "bidirectional"),
                Relationship("r2", "e1", "e3", "alpha_relation", 0.8, "directional"),
                Relationship("r3", "e2", "e3", "beta_relation", 0.75, "directional"),
            ],
            confidence=0.75,
        )
        
        types = generator.unique_relationship_types(result)
        
        assert types == ["alpha_relation", "beta_relation", "zebra_relation"]

    def test_type_with_special_characters(self, generator, sample_entities):
        """Types with special characters should be handled."""
        result = EntityExtractionResult(
            entities=sample_entities,
            relationships=[
                Relationship("r1", "e1", "e2", "type_with_underscore", 0.7, "bidirectional"),
                Relationship("r2", "e1", "e3", "type-with-dash", 0.8, "directional"),
                Relationship("r3", "e2", "e3", "TYPE123", 0.75, "directional"),
            ],
            confidence=0.75,
        )
        
        types = generator.unique_relationship_types(result)
        
        assert set(types) == {"type_with_underscore", "type-with-dash", "TYPE123"}
        assert len(types) == 3

    def test_many_relationships_same_type(self, generator, sample_entities):
        """Many relationships with the same type should return single entry."""
        relationships = [
            Relationship(f"r{i}", "e1", "e2", "common_type", 0.7, "bidirectional")
            for i in range(100)
        ]
        result = EntityExtractionResult(
            entities=sample_entities,
            relationships=relationships,
            confidence=0.7,
        )
        
        types = generator.unique_relationship_types(result)
        
        assert types == ["common_type"]
        assert len(types) == 1

    def test_integration_with_extraction_result_metadata(self, generator, sample_entities):
        """Method should work with results containing metadata and errors."""
        result = EntityExtractionResult(
            entities=sample_entities,
            relationships=[
                Relationship("r1", "e1", "e2", "rel_type_a", 0.7, "bidirectional"),
                Relationship("r2", "e1", "e3", "rel_type_b", 0.8, "directional"),
            ],
            confidence=0.75,
            metadata={"source": "test", "version": "1.0"},
            errors=["warning: low confidence"],
        )
        
        types = generator.unique_relationship_types(result)
        
        assert set(types) == {"rel_type_a", "rel_type_b"}
        # Metadata and errors should not affect the result
        assert result.metadata["source"] == "test"
        assert len(result.errors) == 1

    def test_return_type_is_list(self, generator, sample_entities):
        """Return type should always be a list."""
        result = EntityExtractionResult(
            entities=sample_entities,
            relationships=[
                Relationship("r1", "e1", "e2", "type_a", 0.7, "bidirectional"),
            ],
            confidence=0.75,
        )
        
        types = generator.unique_relationship_types(result)
        
        assert isinstance(types, list)
        assert not isinstance(types, set)
        assert not isinstance(types, tuple)

    def test_case_sensitivity(self, generator, sample_entities):
        """Types should be case-sensitive."""
        result = EntityExtractionResult(
            entities=sample_entities,
            relationships=[
                Relationship("r1", "e1", "e2", "TypeA", 0.7, "bidirectional"),
                Relationship("r2", "e1", "e3", "typea", 0.8, "directional"),
                Relationship("r3", "e2", "e3", "TYPEA", 0.75, "directional"),
            ],
            confidence=0.75,
        )
        
        types = generator.unique_relationship_types(result)
        
        assert set(types) == {"TypeA", "typea", "TYPEA"}
        assert len(types) == 3

    def test_result_immutability(self, generator, sample_entities):
        """Original result should not be modified."""
        result = EntityExtractionResult(
            entities=sample_entities,
            relationships=[
                Relationship("r1", "e1", "e2", "type_a", 0.7, "bidirectional"),
                Relationship("r2", "e1", "e3", "type_b", 0.8, "directional"),
            ],
            confidence=0.75,
        )
        original_rel_count = len(result.relationships)
        original_types = {r.type for r in result.relationships}
        
        types = generator.unique_relationship_types(result)
        
        # Original result should be unchanged
        assert len(result.relationships) == original_rel_count
        assert {r.type for r in result.relationships} == original_types
        assert set(types) == {"type_a", "type_b"}
