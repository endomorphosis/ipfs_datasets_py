"""
Batch 302 — Factory fixture validation tests.

Tests comprehensive factory fixtures for GraphRAG test infrastructure:
* make_entity — Entity object creation with defaults
* make_relationship — Relationship object creation with defaults
* make_extraction_result — EntityExtractionResult creation
* make_critic_score — CriticScore creation with dimension defaults
* create_test_ontology — Full ontology dictionary creation (pre-existing, validated)

These fixtures consolidate scattered mock creation patterns across ~50 test files,
reducing code duplication and improving test maintainability.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore


class TestMakeEntityFixture:
    """Test make_entity factory fixture."""

    def test_minimal_entity_creation(self, make_entity):
        """Entity created with only ID uses sensible defaults."""
        e = make_entity("e1")
        assert isinstance(e, Entity)
        assert e.id == "e1"
        assert e.text == "e1"  # Defaults to ID
        assert e.type == "T"
        assert e.confidence == 0.8

    def test_custom_confidence(self, make_entity):
        """Entity respects custom confidence."""
        e = make_entity("test", confidence=0.95)
        assert e.confidence == 0.95

    def test_custom_type_and_text(self, make_entity):
        """Entity respects custom type and text."""
        e = make_entity("e1", entity_type="Person", text="John Doe")
        assert e.type == "Person"
        assert e.text == "John Doe"

    def test_optional_properties(self, make_entity):
        """Entity accepts optional properties dict."""
        e = make_entity("e1", properties={"age": 30, "role": "manager"})
        assert e.properties == {"age": 30, "role": "manager"}

    def test_optional_span_and_last_seen(self, make_entity):
        """Entity accepts optional source_span and last_seen."""
        e = make_entity("e1", source_span=(10, 20), last_seen=1640995200.0)
        assert e.source_span == (10, 20)
        assert e.last_seen == 1640995200.0

    def test_all_parameters_together(self, make_entity):
        """Entity created with all parameters at once."""
        e = make_entity(
            "e_full",
            confidence=0.92,
            entity_type="Organization",
            text="Acme Corp",
            properties={"founded": 1990},
            source_span=(0, 9),
            last_seen=1640995200.0,
        )
        assert e.id == "e_full"
        assert e.confidence == 0.92
        assert e.type == "Organization"
        assert e.text == "Acme Corp"
        assert e.properties == {"founded": 1990}
        assert e.source_span == (0, 9)
        assert e.last_seen == 1640995200.0


class TestMakeRelationshipFixture:
    """Test make_relationship factory fixture."""

    def test_minimal_relationship_creation(self, make_relationship):
        """Relationship created with source/target uses defaults."""
        r = make_relationship("e1", "e2")
        assert isinstance(r, Relationship)
        assert r.source_id == "e1"
        assert r.target_id == "e2"
        assert r.id == "rel_e1_e2"  # Auto-generated
        assert r.type == "RELATED"
        assert r.confidence == 0.8

    def test_custom_type_and_confidence(self, make_relationship):
        """Relationship respects custom type and confidence."""
        r = make_relationship("e1", "e2", rel_type="knows", confidence=0.95)
        assert r.type == "knows"
        assert r.confidence == 0.95

    def test_custom_id(self, make_relationship):
        """Relationship respects custom ID."""
        r = make_relationship("e1", "e2", rel_id="custom_rel_123")
        assert r.id == "custom_rel_123"

    def test_optional_properties_and_direction(self, make_relationship):
        """Relationship accepts optional properties and direction."""
        r = make_relationship(
            "e1", "e2",
            properties={"strength": "strong"},
            direction="subject_to_object",
        )
        assert r.properties == {"strength": "strong"}
        assert r.direction == "subject_to_object"

    def test_all_parameters_together(self, make_relationship):
        """Relationship created with all parameters at once."""
        r = make_relationship(
            "e_alice", "e_bob",
            rel_type="works_with",
            rel_id="rel_collaboration",
            confidence=0.88,
            properties={"duration_years": 5},
            direction="undirected",
        )
        assert r.source_id == "e_alice"
        assert r.target_id == "e_bob"
        assert r.id == "rel_collaboration"
        assert r.type == "works_with"
        assert r.confidence == 0.88
        assert r.properties == {"duration_years": 5}
        assert r.direction == "undirected"


class TestMakeExtractionResultFixture:
    """Test make_extraction_result factory fixture."""

    def test_empty_result_creation(self, make_extraction_result):
        """Result created with no args has empty lists."""
        result = make_extraction_result()
        assert isinstance(result, EntityExtractionResult)
        assert result.entities == []
        assert result.relationships == []
        assert result.confidence == 1.0
        assert result.metadata == {}
        assert result.errors == []

    def test_result_with_entities(self, make_extraction_result, make_entity):
        """Result created with entity list."""
        entities = [make_entity("e1"), make_entity("e2")]
        result = make_extraction_result(entities=entities)
        assert len(result.entities) == 2
        assert result.entities[0].id == "e1"
        assert result.entities[1].id == "e2"

    def test_result_with_relationships(self, make_extraction_result, make_relationship):
        """Result created with relationship list."""
        rels = [make_relationship("e1", "e2"), make_relationship("e2", "e3")]
        result = make_extraction_result(relationships=rels)
        assert len(result.relationships) == 2
        assert result.relationships[0].source_id == "e1"

    def test_custom_confidence_and_metadata(self, make_extraction_result):
        """Result respects custom confidence and metadata."""
        result = make_extraction_result(
            confidence=0.75,
            metadata={"strategy": "hybrid", "model": "gpt-4"},
        )
        assert result.confidence == 0.75
        assert result.metadata == {"strategy": "hybrid", "model": "gpt-4"}

    def test_result_with_errors(self, make_extraction_result):
        """Result accepts error list."""
        result = make_extraction_result(errors=["Parse error", "Timeout"])
        assert result.errors == ["Parse error", "Timeout"]

    def test_complete_result(self, make_extraction_result, make_entity, make_relationship):
        """Result created with all parameters."""
        entities = [make_entity("e1", confidence=0.9)]
        rels = [make_relationship("e1", "e2")]
        result = make_extraction_result(
            entities=entities,
            relationships=rels,
            confidence=0.85,
            metadata={"source": "doc.pdf"},
            errors=["Warning: low confidence"],
        )
        assert len(result.entities) == 1
        assert len(result.relationships) == 1
        assert result.confidence == 0.85
        assert result.metadata["source"] == "doc.pdf"
        assert len(result.errors) == 1


class TestMakeCriticScoreFixture:
    """Test make_critic_score factory fixture."""

    def test_default_score_creation(self, make_critic_score):
        """Score created with defaults has all dimensions at 0.5."""
        score = make_critic_score()
        assert isinstance(score, CriticScore)
        assert score.completeness == 0.5
        assert score.consistency == 0.5
        assert score.clarity == 0.5
        assert score.granularity == 0.5
        assert score.relationship_coherence == 0.5
        assert score.domain_alignment == 0.5
        assert score.overall == pytest.approx(0.5, abs=0.01)  # Average of all

    def test_custom_single_dimension(self, make_critic_score):
        """Score with one custom dimension, rest default."""
        score = make_critic_score(completeness=0.9)
        assert score.completeness == 0.9
        assert score.consistency == 0.5  # Still default

    def test_custom_multiple_dimensions(self, make_critic_score):
        """Score with multiple custom dimensions."""
        score = make_critic_score(
            completeness=0.8,
            consistency=0.7,
            clarity=0.9,
        )
        assert score.completeness == 0.8
        assert score.consistency == 0.7
        assert score.clarity == 0.9
        assert score.granularity == 0.5  # Unspecified remain default

    def test_all_dimensions_custom(self, make_critic_score):
        """Score with all dimensions customized."""
        score = make_critic_score(
            completeness=0.8,
            consistency=0.7,
            clarity=0.9,
            granularity=0.6,
            relationship_coherence=0.85,
            domain_alignment=0.75,
        )
        assert score.completeness == 0.8
        assert score.consistency == 0.7
        assert score.clarity == 0.9
        assert score.granularity == 0.6
        assert score.relationship_coherence == 0.85
        assert score.domain_alignment == 0.75

    def test_score_with_metadata(self, make_critic_score):
        """Score accepts optional metadata."""
        score = make_critic_score(
            completeness=0.8,
            metadata={"evaluator": "human", "timestamp": "2026-02-25"},
        )
        assert score.metadata == {"evaluator": "human", "timestamp": "2026-02-25"}

    def test_score_with_recommendations(self, make_critic_score):
        """Score accepts optional recommendations list."""
        score = make_critic_score(
            completeness=0.3,
            recommendations=["Add more entities", "Improve clarity"],
        )
        assert score.recommendations == ["Add more entities", "Improve clarity"]


class TestCreateTestOntologyFixture:
    """Test create_test_ontology factory fixture (pre-existing, validated)."""

    def test_default_ontology_creation(self, create_test_ontology):
        """Ontology created with defaults has 5 entities, 3 relationships."""
        ont = create_test_ontology()
        assert isinstance(ont, dict)
        assert len(ont["entities"]) == 5
        assert len(ont["relationships"]) == 3
        assert ont["id"] == "test_ontology"
        assert ont["metadata"]["domain"] == "legal"

    def test_custom_entity_relationship_counts(self, create_test_ontology):
        """Ontology respects custom counts."""
        ont = create_test_ontology(entity_count=10, relationship_count=7)
        assert len(ont["entities"]) == 10
        assert len(ont["relationships"]) == 7

    def test_custom_prefixes(self, create_test_ontology):
        """Ontology respects custom ID prefixes."""
        ont = create_test_ontology(
            entity_count=3,
            relationship_count=2,
            entity_prefix="person_",
            relationship_prefix="link_",
        )
        assert ont["entities"][0]["id"] == "person_0"
        assert ont["relationships"][0]["id"] == "link_0"

    def test_custom_domain_and_metadata(self, create_test_ontology):
        """Ontology accepts custom domain and metadata."""
        ont = create_test_ontology(
            domain="medical",
            metadata={"version": "1.0", "author": "test"},
        )
        assert ont["metadata"]["domain"] == "medical"
        assert ont["metadata"]["version"] == "1.0"
        assert ont["metadata"]["author"] == "test"

    def test_ontology_without_id(self, create_test_ontology):
        """Ontology created without ID field."""
        ont = create_test_ontology(include_ontology_id=False)
        assert "id" not in ont
        assert "entities" in ont
        assert "relationships" in ont


class TestFixtureIntegration:
    """Test multiple fixtures working together."""

    def test_build_complex_result(self, make_entity, make_relationship, make_extraction_result):
        """Build complex EntityExtractionResult using all fixtures."""
        entities = [
            make_entity("e1", confidence=0.9, entity_type="Person", text="Alice"),
            make_entity("e2", confidence=0.85, entity_type="Organization", text="Acme"),
        ]
        rels = [
            make_relationship("e1", "e2", rel_type="works_for", confidence=0.88),
        ]
        result = make_extraction_result(
            entities=entities,
            relationships=rels,
            confidence=0.87,
            metadata={"source": "contract.pdf"},
        )

        assert len(result.entities) == 2
        assert result.entities[0].text == "Alice"
        assert len(result.relationships) == 1
        assert result.relationships[0].type == "works_for"
        assert result.confidence == 0.87

    def test_score_and_ontology_together(self, make_critic_score, create_test_ontology):
        """Create ontology and score it (fixture usage pattern)."""
        ont = create_test_ontology(entity_count=8, domain="legal")
        score = make_critic_score(
            completeness=0.75,
            consistency=0.8,
            metadata={"ontology_id": ont["id"]},
        )

        assert len(ont["entities"]) == 8
        assert score.completeness == 0.75
        assert score.metadata["ontology_id"] == "test_ontology"
