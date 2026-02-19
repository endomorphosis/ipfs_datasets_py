"""
Unit tests for the new extraction/ package.

Tests the modular extraction package created in Phase 3 of the knowledge graphs refactoring.
Validates that the new imports work correctly and maintain backward compatibility.

Following GIVEN-WHEN-THEN format as per repository standards.
"""

import pytest
from unittest.mock import Mock
from ipfs_datasets_py.knowledge_graphs.extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor,
    KnowledgeGraphExtractorWithValidation,
)


class TestNewExtractionPackageImports:
    """Test that new extraction package imports work correctly."""
    
    def test_entity_import_from_new_package(self):
        """
        GIVEN the new extraction package
        WHEN importing Entity class
        THEN Entity class is available and functional
        """
        # WHEN
        entity = Entity(entity_type="person", name="Test Person")
        
        # THEN
        assert entity is not None
        assert entity.entity_type == "person"
        assert entity.name == "Test Person"
    
    def test_relationship_import_from_new_package(self):
        """
        GIVEN the new extraction package
        WHEN importing Relationship class
        THEN Relationship class is available and functional
        """
        # GIVEN
        source = Entity(entity_type="person", name="Alice")
        target = Entity(entity_type="person", name="Bob")
        
        # WHEN
        relationship = Relationship(
            source_entity=source,
            target_entity=target,
            relationship_type="knows"
        )
        
        # THEN
        assert relationship is not None
        assert relationship.source_entity == source
        assert relationship.target_entity == target
        assert relationship.relationship_type == "knows"
    
    def test_knowledge_graph_import_from_new_package(self):
        """
        GIVEN the new extraction package
        WHEN importing KnowledgeGraph class
        THEN KnowledgeGraph class is available and functional
        """
        # WHEN
        kg = KnowledgeGraph(name="Test Graph")
        
        # THEN
        assert kg is not None
        assert kg.name == "Test Graph"
        assert len(kg.entities) == 0
        assert len(kg.relationships) == 0
    
    def test_extractor_import_from_new_package(self):
        """
        GIVEN the new extraction package
        WHEN importing KnowledgeGraphExtractor class
        THEN KnowledgeGraphExtractor class is available and functional
        """
        # WHEN
        extractor = KnowledgeGraphExtractor()
        
        # THEN
        assert extractor is not None
        assert hasattr(extractor, 'extract_entities')
        assert hasattr(extractor, 'extract_relationships')
        assert hasattr(extractor, 'extract_knowledge_graph')
    
    def test_validator_import_from_new_package(self):
        """
        GIVEN the new extraction package
        WHEN importing KnowledgeGraphExtractorWithValidation class
        THEN validator class is available and functional
        """
        # WHEN
        validator = KnowledgeGraphExtractorWithValidation()
        
        # THEN
        assert validator is not None
        assert hasattr(validator, 'extract_knowledge_graph')
        assert hasattr(validator, 'validate_against_wikidata')


class TestExtractionPackageBackwardCompatibility:
    """Test backward compatibility with old imports."""
    
    def test_both_import_paths_return_same_class(self):
        """
        GIVEN both old and new import paths
        WHEN importing Entity from both
        THEN both imports reference the same class
        """
        # GIVEN / WHEN
        from ipfs_datasets_py.knowledge_graphs.extraction import Entity as NewEntity
        from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import Entity as OldEntity
        
        # THEN
        assert NewEntity is OldEntity, "Old and new imports should reference the same class"
    
    def test_instances_are_compatible(self):
        """
        GIVEN entities created from old and new imports
        WHEN using them together
        THEN they are fully compatible
        """
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.extraction import Entity as NewEntity
        from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import Entity as OldEntity
        
        # WHEN
        new_entity = NewEntity(entity_type="person", name="New")
        old_entity = OldEntity(entity_type="person", name="Old")
        
        # THEN
        assert type(new_entity) == type(old_entity)
        assert isinstance(new_entity, OldEntity)
        assert isinstance(old_entity, NewEntity)


class TestModularPackageStructure:
    """Test that the modular package structure works correctly."""
    
    def test_extraction_package_has_all_exports(self):
        """
        GIVEN the extraction package
        WHEN checking its exports
        THEN all expected classes are available
        """
        # WHEN
        import ipfs_datasets_py.knowledge_graphs.extraction as extraction_pkg
        
        # THEN
        assert hasattr(extraction_pkg, 'Entity')
        assert hasattr(extraction_pkg, 'Relationship')
        assert hasattr(extraction_pkg, 'KnowledgeGraph')
        assert hasattr(extraction_pkg, 'KnowledgeGraphExtractor')
        assert hasattr(extraction_pkg, 'KnowledgeGraphExtractorWithValidation')
    
    def test_can_import_individual_modules(self):
        """
        GIVEN the extraction package structure
        WHEN importing from individual modules
        THEN imports work correctly
        """
        # WHEN / THEN
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import KnowledgeGraphExtractor
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import KnowledgeGraphExtractorWithValidation
        
        # Create instances to verify
        assert Entity is not None
        assert Relationship is not None
        assert KnowledgeGraph is not None
        assert KnowledgeGraphExtractor is not None
        assert KnowledgeGraphExtractorWithValidation is not None


class TestExtractionFunctionality:
    """Test that extraction functionality works with new package."""
    
    def test_basic_extraction_workflow(self):
        """
        GIVEN text to extract knowledge from
        WHEN using the new extraction package
        THEN extraction works correctly
        """
        # GIVEN
        text = "Marie Curie was a physicist who won the Nobel Prize."
        extractor = KnowledgeGraphExtractor()
        
        # WHEN
        kg = extractor.extract_knowledge_graph(text)
        
        # THEN
        assert kg is not None
        assert isinstance(kg, KnowledgeGraph)
        assert len(kg.entities) > 0

    def test_validator_extract_from_documents_includes_error_class(self):
        """Validator returns structured error metadata on unexpected failures."""
        validator = KnowledgeGraphExtractorWithValidation(
            use_tracer=False,
            validate_during_extraction=False,
        )
        validator.extractor.extract_from_documents = Mock(side_effect=RuntimeError("boom"))

        result = validator.extract_from_documents([{"text": "hi"}])

        assert result["knowledge_graph"] is None
        assert result.get("error")
        assert result.get("error_class") == "RuntimeError"
    
    def test_entity_relationship_integration(self):
        """
        GIVEN entities and relationships
        WHEN adding them to a knowledge graph
        THEN they integrate correctly
        """
        # GIVEN
        kg = KnowledgeGraph(name="Test Integration")
        entity1 = Entity(entity_type="person", name="Alice")
        entity2 = Entity(entity_type="person", name="Bob")
        
        # WHEN
        kg.add_entity(entity1)
        kg.add_entity(entity2)
        
        relationship = Relationship(
            source_entity=entity1,
            target_entity=entity2,
            relationship_type="knows"
        )
        kg.add_relationship(relationship)
        
        # THEN
        assert len(kg.entities) == 2
        assert len(kg.relationships) == 1
        assert entity1.entity_id in kg.entities
        assert entity2.entity_id in kg.entities
    
    def test_knowledge_graph_merge(self):
        """
        GIVEN two knowledge graphs
        WHEN merging them
        THEN entities and relationships are combined correctly
        """
        # GIVEN
        kg1 = KnowledgeGraph(name="Graph 1")
        kg2 = KnowledgeGraph(name="Graph 2")
        
        entity1 = Entity(entity_type="person", name="Alice")
        entity2 = Entity(entity_type="person", name="Bob")
        
        kg1.add_entity(entity1)
        kg2.add_entity(entity2)
        
        # WHEN
        kg1.merge(kg2)
        
        # THEN
        assert len(kg1.entities) == 2
        assert entity1.entity_id in kg1.entities
        assert entity2.entity_id in kg1.entities
    
    def test_knowledge_graph_serialization(self):
        """
        GIVEN a knowledge graph with entities
        WHEN serializing to JSON and back
        THEN data is preserved correctly
        """
        # GIVEN
        kg = KnowledgeGraph(name="Test Serialization")
        entity = Entity(entity_type="person", name="Test", properties={"age": "30"})
        kg.add_entity(entity)
        
        # WHEN
        json_str = kg.to_json()
        kg_restored = KnowledgeGraph.from_json(json_str)
        
        # THEN
        assert kg_restored.name == kg.name
        assert len(kg_restored.entities) == len(kg.entities)
        restored_entity = list(kg_restored.entities.values())[0]
        assert restored_entity.name == entity.name
        assert restored_entity.entity_type == entity.entity_type
        assert restored_entity.properties == entity.properties


class TestValidationExtractor:
    """Test the validation extractor functionality."""
    
    def test_validation_extractor_initialization(self):
        """
        GIVEN validation extractor parameters
        WHEN creating a validation extractor
        THEN it initializes correctly
        """
        # WHEN
        validator = KnowledgeGraphExtractorWithValidation(
            validate_during_extraction=True,
            auto_correct_suggestions=True
        )
        
        # THEN
        assert validator is not None
        assert validator.validate_during_extraction is True
        assert validator.auto_correct_suggestions is True
    
    def test_validation_extractor_returns_validation_results(self):
        """
        GIVEN text to extract with validation
        WHEN extracting with validation enabled
        THEN validation results are included
        """
        # GIVEN
        text = "Albert Einstein developed the theory of relativity."
        validator = KnowledgeGraphExtractorWithValidation(
            validate_during_extraction=True
        )
        
        # WHEN
        result = validator.extract_knowledge_graph(
            text,
            validation_depth=1
        )
        
        # THEN
        assert isinstance(result, dict)
        assert "knowledge_graph" in result
        assert "validation_results" in result or "validation_metrics" in result
        
        kg = result["knowledge_graph"]
        assert isinstance(kg, KnowledgeGraph)


class TestExtractionPerformance:
    """Test performance characteristics of extraction package."""
    
    def test_extraction_completes_in_reasonable_time(self):
        """
        GIVEN a moderate-sized text
        WHEN extracting knowledge graph
        THEN extraction completes in reasonable time
        """
        # GIVEN
        text = "Python is a programming language. " * 20  # Moderate text
        extractor = KnowledgeGraphExtractor()
        
        # WHEN
        import time
        start = time.time()
        kg = extractor.extract_knowledge_graph(text)
        elapsed = time.time() - start
        
        # THEN
        assert kg is not None
        assert elapsed < 5.0, f"Extraction took {elapsed}s, expected < 5s"
    
    def test_multiple_extractions_are_efficient(self):
        """
        GIVEN multiple texts to extract
        WHEN performing batch extraction
        THEN extractions are reasonably efficient
        """
        # GIVEN
        texts = [
            "Text 1: Sample content.",
            "Text 2: More sample content.",
            "Text 3: Additional content."
        ]
        extractor = KnowledgeGraphExtractor()
        
        # WHEN
        import time
        start = time.time()
        graphs = [extractor.extract_knowledge_graph(text) for text in texts]
        elapsed = time.time() - start
        
        # THEN
        assert len(graphs) == 3
        assert all(isinstance(kg, KnowledgeGraph) for kg in graphs)
        assert elapsed < 10.0, f"Batch extraction took {elapsed}s, expected < 10s"


class TestExtractionEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_text_extraction(self):
        """
        GIVEN empty text
        WHEN extracting knowledge graph
        THEN returns empty graph without errors
        """
        # GIVEN
        text = ""
        extractor = KnowledgeGraphExtractor()
        
        # WHEN
        kg = extractor.extract_knowledge_graph(text)
        
        # THEN
        assert kg is not None
        assert isinstance(kg, KnowledgeGraph)
        assert len(kg.entities) == 0
    
    def test_very_short_text_extraction(self):
        """
        GIVEN very short text
        WHEN extracting knowledge graph
        THEN handles gracefully
        """
        # GIVEN
        text = "Hi."
        extractor = KnowledgeGraphExtractor()
        
        # WHEN
        kg = extractor.extract_knowledge_graph(text)
        
        # THEN
        assert kg is not None
        assert isinstance(kg, KnowledgeGraph)
    
    def test_special_characters_in_text(self):
        """
        GIVEN text with special characters
        WHEN extracting knowledge graph
        THEN handles special characters correctly
        """
        # GIVEN
        text = "Test with émojis 🎉 and spëcial çharacters!"
        extractor = KnowledgeGraphExtractor()
        
        # WHEN
        kg = extractor.extract_knowledge_graph(text)
        
        # THEN
        assert kg is not None
        assert isinstance(kg, KnowledgeGraph)
    
    def test_duplicate_entity_handling(self):
        """
        GIVEN a knowledge graph with duplicate entities
        WHEN adding entities with same ID
        THEN duplicates are handled appropriately
        """
        # GIVEN
        kg = KnowledgeGraph()
        entity1 = Entity(entity_id="same_id", entity_type="person", name="Alice")
        entity2 = Entity(entity_id="same_id", entity_type="person", name="Alice")
        
        # WHEN
        kg.add_entity(entity1)
        kg.add_entity(entity2)  # Same ID
        
        # THEN
        assert len(kg.entities) == 1, "Duplicate entities should be handled"


# Test fixtures
@pytest.fixture
def sample_entity():
    """Provide a sample entity for testing."""
    return Entity(
        entity_id="test_123",
        entity_type="person",
        name="John Doe",
        properties={"age": "30", "occupation": "Engineer"},
        confidence=0.9
    )


@pytest.fixture
def sample_relationship(sample_entity):
    """Provide a sample relationship for testing."""
    target = Entity(entity_type="organization", name="Tech Corp")
    return Relationship(
        source_entity=sample_entity,
        target_entity=target,
        relationship_type="works_at",
        confidence=0.85
    )


@pytest.fixture
def sample_knowledge_graph(sample_entity, sample_relationship):
    """Provide a sample knowledge graph for testing."""
    kg = KnowledgeGraph(name="Sample Graph")
    kg.add_entity(sample_entity)
    kg.add_entity(sample_relationship.target_entity)
    kg.add_relationship(sample_relationship)
    return kg
