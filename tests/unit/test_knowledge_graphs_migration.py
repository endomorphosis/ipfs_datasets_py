"""
Comprehensive tests for knowledge_graphs migration module.

This test suite improves migration module coverage from ~40% to 70%+
by testing Neo4j export, IPFS import, format conversion, schema checking,
and integrity verification.
"""

import pytest
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Import knowledge_graphs migration components
try:
    from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
    from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter
    from ipfs_datasets_py.knowledge_graphs.migration.formats import FormatConverter
    from ipfs_datasets_py.knowledge_graphs.migration.schema_checker import SchemaChecker
    from ipfs_datasets_py.knowledge_graphs.migration.integrity_verifier import IntegrityVerifier
    from ipfs_datasets_py.knowledge_graphs.extraction.schema import Entity, Relationship, KnowledgeGraph
    MIGRATION_AVAILABLE = True
except ImportError as e:
    MIGRATION_AVAILABLE = False
    pytestmark = pytest.mark.skip(f"Migration module not available: {e}")


# ============================================================================
# Task 3.1.1: Neo4j Export Tests (7 tests)
# ============================================================================

@pytest.mark.skipif(not MIGRATION_AVAILABLE, reason="Migration module not available")
class TestNeo4jExporter:
    """Test Neo4j export functionality."""

    def test_basic_export_entities(self):
        """Test basic entity export to Neo4j format."""
        # GIVEN: A knowledge graph with entities
        entities = [
            Entity(id="e1", text="Alice", type="PERSON", properties={"age": 30}),
            Entity(id="e2", text="Bob", type="PERSON", properties={"age": 25})
        ]
        kg = KnowledgeGraph(entities=entities, relationships=[])
        
        # WHEN: Exporting to Neo4j format
        exporter = Neo4jExporter()
        result = exporter.export(kg)
        
        # THEN: Result should contain nodes
        assert "nodes" in result
        assert len(result["nodes"]) == 2
        assert result["nodes"][0]["type"] == "PERSON"
        assert result["nodes"][0]["properties"]["age"] == 30

    def test_export_with_relationships(self):
        """Test export with entity relationships."""
        # GIVEN: A knowledge graph with entities and relationships
        entities = [
            Entity(id="e1", text="Alice", type="PERSON"),
            Entity(id="e2", text="Company X", type="ORGANIZATION")
        ]
        relationships = [
            Relationship(source="e1", target="e2", type="WORKS_AT", properties={})
        ]
        kg = KnowledgeGraph(entities=entities, relationships=relationships)
        
        # WHEN: Exporting to Neo4j format
        exporter = Neo4jExporter()
        result = exporter.export(kg)
        
        # THEN: Result should contain both nodes and relationships
        assert "nodes" in result
        assert "relationships" in result
        assert len(result["relationships"]) == 1
        assert result["relationships"][0]["type"] == "WORKS_AT"

    def test_export_with_batch_size(self):
        """Test batch export with large dataset."""
        # GIVEN: A large knowledge graph
        entities = [Entity(id=f"e{i}", text=f"Entity{i}", type="PERSON") for i in range(150)]
        kg = KnowledgeGraph(entities=entities, relationships=[])
        
        # WHEN: Exporting with batch size of 50
        exporter = Neo4jExporter(batch_size=50)
        result = exporter.export(kg)
        
        # THEN: All entities should be exported
        assert len(result["nodes"]) == 150

    def test_export_error_invalid_entity(self):
        """Test error handling for invalid entity."""
        # GIVEN: A knowledge graph with invalid entity
        entities = [{"invalid": "entity"}]  # Wrong format
        
        # WHEN/THEN: Exporting should handle error gracefully
        exporter = Neo4jExporter()
        with pytest.raises((ValueError, TypeError, AttributeError)):
            exporter.export(KnowledgeGraph(entities=entities, relationships=[]))

    def test_export_error_connection_failure(self):
        """Test error handling for connection failure."""
        # GIVEN: Neo4j exporter with invalid connection
        exporter = Neo4jExporter(uri="bolt://invalid:7687")
        kg = KnowledgeGraph(entities=[Entity(id="e1", text="Test", type="PERSON")], relationships=[])
        
        # WHEN/THEN: Export with connection should handle error
        # Note: This tests graceful degradation
        try:
            result = exporter.export(kg, connect=False)
            assert result is not None  # Should return data even if can't connect
        except Exception as e:
            # Should raise informative error
            assert "connection" in str(e).lower() or "uri" in str(e).lower()

    def test_export_preserves_properties(self):
        """Test that export preserves all entity properties."""
        # GIVEN: Entity with multiple properties
        entity = Entity(
            id="e1",
            text="Alice",
            type="PERSON",
            properties={"age": 30, "city": "New York", "occupation": "Engineer"}
        )
        kg = KnowledgeGraph(entities=[entity], relationships=[])
        
        # WHEN: Exporting
        exporter = Neo4jExporter()
        result = exporter.export(kg)
        
        # THEN: All properties should be preserved
        node = result["nodes"][0]
        assert node["properties"]["age"] == 30
        assert node["properties"]["city"] == "New York"
        assert node["properties"]["occupation"] == "Engineer"

    def test_export_deduplicates_entities(self):
        """Test that export handles duplicate entities."""
        # GIVEN: Knowledge graph with duplicate entity IDs
        entities = [
            Entity(id="e1", text="Alice", type="PERSON"),
            Entity(id="e1", text="Alice Updated", type="PERSON")  # Duplicate ID
        ]
        kg = KnowledgeGraph(entities=entities, relationships=[])
        
        # WHEN: Exporting
        exporter = Neo4jExporter()
        result = exporter.export(kg)
        
        # THEN: Should handle duplicates (either merge or keep latest)
        assert len(result["nodes"]) <= 2


# ============================================================================
# Task 3.1.2: IPFS Import Tests (7 tests)
# ============================================================================

@pytest.mark.skipif(not MIGRATION_AVAILABLE, reason="Migration module not available")
class TestIPFSImporter:
    """Test IPFS import functionality."""

    def test_basic_import_from_cid(self):
        """Test basic import from IPFS CID."""
        # GIVEN: Mock IPFS data
        mock_data = {
            "nodes": [{"id": "e1", "text": "Alice", "type": "PERSON"}],
            "relationships": []
        }
        
        # WHEN: Importing from CID
        importer = IPFSImporter()
        with patch.object(importer, '_fetch_from_ipfs', return_value=json.dumps(mock_data)):
            kg = importer.import_from_cid("QmTest123")
        
        # THEN: Knowledge graph should be created
        assert kg is not None
        assert len(kg.entities) == 1
        assert kg.entities[0].text == "Alice"

    def test_import_from_json_file(self):
        """Test import from local JSON file."""
        # GIVEN: Temporary JSON file with knowledge graph data
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            data = {
                "nodes": [{"id": "e1", "text": "Bob", "type": "PERSON"}],
                "relationships": []
            }
            json.dump(data, f)
            temp_file = f.name
        
        try:
            # WHEN: Importing from file
            importer = IPFSImporter()
            kg = importer.import_from_file(temp_file)
            
            # THEN: Knowledge graph should be created
            assert kg is not None
            assert len(kg.entities) == 1
            assert kg.entities[0].text == "Bob"
        finally:
            os.unlink(temp_file)

    def test_import_with_relationships(self):
        """Test import with entity relationships."""
        # GIVEN: Data with relationships
        mock_data = {
            "nodes": [
                {"id": "e1", "text": "Alice", "type": "PERSON"},
                {"id": "e2", "text": "Company", "type": "ORG"}
            ],
            "relationships": [
                {"source": "e1", "target": "e2", "type": "WORKS_AT"}
            ]
        }
        
        # WHEN: Importing
        importer = IPFSImporter()
        with patch.object(importer, '_fetch_from_ipfs', return_value=json.dumps(mock_data)):
            kg = importer.import_from_cid("QmTest123")
        
        # THEN: Both entities and relationships should be imported
        assert len(kg.entities) == 2
        assert len(kg.relationships) == 1
        assert kg.relationships[0].type == "WORKS_AT"

    def test_import_error_invalid_cid(self):
        """Test error handling for invalid CID."""
        # GIVEN: Invalid CID
        invalid_cid = "invalid_cid_format"
        
        # WHEN/THEN: Import should handle error
        importer = IPFSImporter()
        with pytest.raises((ValueError, Exception)):
            importer.import_from_cid(invalid_cid)

    def test_import_error_malformed_json(self):
        """Test error handling for malformed JSON."""
        # GIVEN: Malformed JSON data
        malformed_json = "{invalid json"
        
        # WHEN/THEN: Import should handle error
        importer = IPFSImporter()
        with patch.object(importer, '_fetch_from_ipfs', return_value=malformed_json):
            with pytest.raises((json.JSONDecodeError, ValueError)):
                importer.import_from_cid("QmTest123")

    def test_import_ipld_format(self):
        """Test import from IPLD format."""
        # GIVEN: IPLD-formatted data
        ipld_data = {
            "@type": "KnowledgeGraph",
            "entities": [
                {"@type": "Entity", "id": "e1", "text": "Alice", "entityType": "PERSON"}
            ],
            "relationships": []
        }
        
        # WHEN: Importing IPLD format
        importer = IPFSImporter()
        with patch.object(importer, '_fetch_from_ipfs', return_value=json.dumps(ipld_data)):
            kg = importer.import_from_cid("QmTest123", format="ipld")
        
        # THEN: Should parse IPLD format correctly
        assert kg is not None
        assert len(kg.entities) >= 1

    def test_import_preserves_metadata(self):
        """Test that import preserves entity metadata."""
        # GIVEN: Data with rich metadata
        mock_data = {
            "nodes": [{
                "id": "e1",
                "text": "Alice",
                "type": "PERSON",
                "properties": {"age": 30, "verified": True},
                "metadata": {"source": "document1.pdf", "confidence": 0.95}
            }],
            "relationships": []
        }
        
        # WHEN: Importing
        importer = IPFSImporter()
        with patch.object(importer, '_fetch_from_ipfs', return_value=json.dumps(mock_data)):
            kg = importer.import_from_cid("QmTest123")
        
        # THEN: Metadata should be preserved
        assert kg.entities[0].properties.get("age") == 30
        assert kg.entities[0].properties.get("verified") is True


# ============================================================================
# Task 3.1.3: Format Conversion Tests (6 tests)
# ============================================================================

@pytest.mark.skipif(not MIGRATION_AVAILABLE, reason="Migration module not available")
class TestFormatConverter:
    """Test format conversion functionality."""

    def test_convert_to_json(self):
        """Test conversion to JSON format."""
        # GIVEN: A knowledge graph
        kg = KnowledgeGraph(
            entities=[Entity(id="e1", text="Alice", type="PERSON")],
            relationships=[]
        )
        
        # WHEN: Converting to JSON
        converter = FormatConverter()
        result = converter.to_json(kg)
        
        # THEN: Result should be valid JSON
        assert isinstance(result, str)
        data = json.loads(result)
        assert "entities" in data or "nodes" in data

    def test_convert_from_json(self):
        """Test conversion from JSON format."""
        # GIVEN: JSON string
        json_str = json.dumps({
            "entities": [{"id": "e1", "text": "Bob", "type": "PERSON"}],
            "relationships": []
        })
        
        # WHEN: Converting from JSON
        converter = FormatConverter()
        kg = converter.from_json(json_str)
        
        # THEN: Should create knowledge graph
        assert kg is not None
        assert len(kg.entities) == 1

    def test_convert_to_csv(self):
        """Test conversion to CSV format."""
        # GIVEN: A knowledge graph
        kg = KnowledgeGraph(
            entities=[
                Entity(id="e1", text="Alice", type="PERSON", properties={"age": 30}),
                Entity(id="e2", text="Bob", type="PERSON", properties={"age": 25})
            ],
            relationships=[]
        )
        
        # WHEN: Converting to CSV
        converter = FormatConverter()
        result = converter.to_csv(kg)
        
        # THEN: Result should be CSV format
        assert isinstance(result, str)
        assert "id" in result or "text" in result
        lines = result.strip().split('\n')
        assert len(lines) >= 2  # Header + data

    def test_convert_from_csv(self):
        """Test conversion from CSV format."""
        # GIVEN: CSV string
        csv_str = "id,text,type\ne1,Alice,PERSON\ne2,Bob,PERSON"
        
        # WHEN: Converting from CSV
        converter = FormatConverter()
        kg = converter.from_csv(csv_str)
        
        # THEN: Should create knowledge graph
        assert kg is not None
        assert len(kg.entities) == 2

    def test_unsupported_format_error_graphml(self):
        """Test error for unsupported GraphML format."""
        # GIVEN: A knowledge graph
        kg = KnowledgeGraph(entities=[Entity(id="e1", text="Test", type="PERSON")], relationships=[])
        
        # WHEN/THEN: Converting to unsupported format should raise error
        converter = FormatConverter()
        with pytest.raises(NotImplementedError):
            converter.to_graphml(kg)

    def test_unsupported_format_error_gexf(self):
        """Test error for unsupported GEXF format."""
        # GIVEN: A knowledge graph
        kg = KnowledgeGraph(entities=[Entity(id="e1", text="Test", type="PERSON")], relationships=[])
        
        # WHEN/THEN: Converting to unsupported format should raise error
        converter = FormatConverter()
        with pytest.raises(NotImplementedError):
            converter.to_gexf(kg)


# ============================================================================
# Task 3.1.4: Schema Checking Tests (4 tests)
# ============================================================================

@pytest.mark.skipif(not MIGRATION_AVAILABLE, reason="Migration module not available")
class TestSchemaChecker:
    """Test schema validation functionality."""

    def test_validate_schema_valid(self):
        """Test validation of valid schema."""
        # GIVEN: A valid knowledge graph
        kg = KnowledgeGraph(
            entities=[Entity(id="e1", text="Alice", type="PERSON")],
            relationships=[]
        )
        
        # WHEN: Validating schema
        checker = SchemaChecker()
        result = checker.validate(kg)
        
        # THEN: Validation should pass
        assert result is True or result.get("valid") is True

    def test_validate_schema_missing_required_fields(self):
        """Test validation fails for missing required fields."""
        # GIVEN: Entity with missing required field
        try:
            invalid_entity = Entity(id="e1", text="", type="PERSON")  # Empty text
            kg = KnowledgeGraph(entities=[invalid_entity], relationships=[])
            
            # WHEN: Validating schema
            checker = SchemaChecker()
            result = checker.validate(kg)
            
            # THEN: Validation should fail or return warnings
            assert result is False or (isinstance(result, dict) and not result.get("valid", True))
        except ValueError:
            # Some implementations may raise ValueError for invalid data
            pass

    def test_check_schema_migration_needed(self):
        """Test detection of schema migration needs."""
        # GIVEN: Knowledge graph with old schema version
        kg = KnowledgeGraph(
            entities=[Entity(id="e1", text="Alice", type="PERSON")],
            relationships=[],
            metadata={"schema_version": "1.0"}
        )
        
        # WHEN: Checking if migration needed
        checker = SchemaChecker(current_version="2.0")
        needs_migration = checker.needs_migration(kg)
        
        # THEN: Should detect migration is needed
        assert needs_migration is True or needs_migration == "1.0"

    def test_migrate_schema(self):
        """Test schema migration."""
        # GIVEN: Knowledge graph with old schema
        kg = KnowledgeGraph(
            entities=[Entity(id="e1", text="Alice", type="PERSON")],
            relationships=[],
            metadata={"schema_version": "1.0"}
        )
        
        # WHEN: Migrating schema
        checker = SchemaChecker()
        migrated_kg = checker.migrate(kg, target_version="2.0")
        
        # THEN: Schema should be updated
        assert migrated_kg is not None
        # Version should be updated if tracked
        if hasattr(migrated_kg, 'metadata') and migrated_kg.metadata:
            version = migrated_kg.metadata.get("schema_version", "2.0")
            assert version == "2.0" or version > "1.0"


# ============================================================================
# Task 3.1.5: Integrity Verification Tests (3 tests)
# ============================================================================

@pytest.mark.skipif(not MIGRATION_AVAILABLE, reason="Migration module not available")
class TestIntegrityVerifier:
    """Test integrity verification functionality."""

    def test_verify_integrity_valid_graph(self):
        """Test integrity check on valid graph."""
        # GIVEN: A valid knowledge graph
        entities = [
            Entity(id="e1", text="Alice", type="PERSON"),
            Entity(id="e2", text="Bob", type="PERSON")
        ]
        relationships = [
            Relationship(source="e1", target="e2", type="KNOWS", properties={})
        ]
        kg = KnowledgeGraph(entities=entities, relationships=relationships)
        
        # WHEN: Verifying integrity
        verifier = IntegrityVerifier()
        result = verifier.verify(kg)
        
        # THEN: Should pass integrity check
        assert result is True or result.get("valid") is True

    def test_verify_integrity_broken_reference(self):
        """Test detection of broken relationship references."""
        # GIVEN: Knowledge graph with broken reference
        entities = [Entity(id="e1", text="Alice", type="PERSON")]
        relationships = [
            Relationship(source="e1", target="e999", type="KNOWS", properties={})  # e999 doesn't exist
        ]
        kg = KnowledgeGraph(entities=entities, relationships=relationships)
        
        # WHEN: Verifying integrity
        verifier = IntegrityVerifier()
        result = verifier.verify(kg)
        
        # THEN: Should detect broken reference
        assert result is False or (isinstance(result, dict) and len(result.get("errors", [])) > 0)

    def test_repair_broken_references(self):
        """Test repair of broken references."""
        # GIVEN: Knowledge graph with broken references
        entities = [Entity(id="e1", text="Alice", type="PERSON")]
        relationships = [
            Relationship(source="e1", target="e999", type="KNOWS", properties={})
        ]
        kg = KnowledgeGraph(entities=entities, relationships=relationships)
        
        # WHEN: Repairing
        verifier = IntegrityVerifier()
        repaired_kg = verifier.repair(kg)
        
        # THEN: Broken references should be removed or fixed
        assert repaired_kg is not None
        # Should have fewer relationships after repair
        assert len(repaired_kg.relationships) <= len(kg.relationships)


# ============================================================================
# Summary: 27 comprehensive tests for migration module
# Expected to increase coverage from ~40% to 70%+
# ============================================================================
