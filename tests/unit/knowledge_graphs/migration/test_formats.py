"""
Tests for migration data formats
"""

try:
    import pytest
    HAVE_PYTEST = True
except ImportError:
    HAVE_PYTEST = False

import json
import tempfile
import os

from ipfs_datasets_py.knowledge_graphs.migration.formats import (
    NodeData, RelationshipData, SchemaData, GraphData, MigrationFormat
)


class TestNodeData:
    """Test NodeData class."""
    
    def test_node_creation(self):
        """Test creating a node."""
        node = NodeData(
            id="1",
            labels=["Person"],
            properties={"name": "Alice", "age": 30}
        )
        assert node.id == "1"
        assert node.labels == ["Person"]
        assert node.properties == {"name": "Alice", "age": 30}
    
    def test_node_to_dict(self):
        """Test converting node to dict."""
        node = NodeData(id="1", labels=["Person"], properties={"name": "Alice"})
        data = node.to_dict()
        
        assert data['id'] == "1"
        assert data['labels'] == ["Person"]
        assert data['properties'] == {"name": "Alice"}
    
    def test_node_from_dict(self):
        """Test creating node from dict."""
        data = {
            'id': "1",
            'labels': ["Person"],
            'properties': {"name": "Alice"}
        }
        node = NodeData.from_dict(data)
        
        assert node.id == "1"
        assert node.labels == ["Person"]
        assert node.properties == {"name": "Alice"}
    
    def test_node_to_json(self):
        """Test converting node to JSON."""
        node = NodeData(id="1", labels=["Person"], properties={"name": "Alice"})
        json_str = node.to_json()
        
        data = json.loads(json_str)
        assert data['id'] == "1"
        assert data['labels'] == ["Person"]


class TestRelationshipData:
    """Test RelationshipData class."""
    
    def test_relationship_creation(self):
        """Test creating a relationship."""
        rel = RelationshipData(
            id="1",
            type="KNOWS",
            start_node="1",
            end_node="2",
            properties={"since": 2020}
        )
        assert rel.id == "1"
        assert rel.type == "KNOWS"
        assert rel.start_node == "1"
        assert rel.end_node == "2"
        assert rel.properties == {"since": 2020}
    
    def test_relationship_to_dict(self):
        """Test converting relationship to dict."""
        rel = RelationshipData(
            id="1",
            type="KNOWS",
            start_node="1",
            end_node="2"
        )
        data = rel.to_dict()
        
        assert data['id'] == "1"
        assert data['type'] == "KNOWS"
        assert data['start_node'] == "1"
        assert data['end_node'] == "2"
    
    def test_relationship_from_dict(self):
        """Test creating relationship from dict."""
        data = {
            'id': "1",
            'type': "KNOWS",
            'start_node': "1",
            'end_node': "2",
            'properties': {}
        }
        rel = RelationshipData.from_dict(data)
        
        assert rel.id == "1"
        assert rel.type == "KNOWS"


class TestGraphData:
    """Test GraphData class."""
    
    def test_graph_creation(self):
        """Test creating graph data."""
        nodes = [
            NodeData(id="1", labels=["Person"], properties={"name": "Alice"}),
            NodeData(id="2", labels=["Person"], properties={"name": "Bob"})
        ]
        rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2")
        ]
        
        graph = GraphData(nodes=nodes, relationships=rels)
        assert len(graph.nodes) == 2
        assert len(graph.relationships) == 1
    
    def test_graph_statistics(self):
        """Test graph statistics."""
        nodes = [
            NodeData(id="1", labels=["Person"], properties={"name": "Alice"}),
            NodeData(id="2", labels=["Person", "Manager"], properties={"name": "Bob"})
        ]
        rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2"),
            RelationshipData(id="2", type="KNOWS", start_node="2", end_node="1")
        ]
        
        graph = GraphData(nodes=nodes, relationships=rels)
        stats = graph.get_statistics()
        
        assert stats['node_count'] == 2
        assert stats['relationship_count'] == 2
        assert stats['label_counts']['Person'] == 2
        assert stats['label_counts']['Manager'] == 1
        assert stats['relationship_type_counts']['KNOWS'] == 2
    
    def test_graph_to_json(self):
        """Test converting graph to JSON."""
        nodes = [NodeData(id="1", labels=["Person"], properties={"name": "Alice"})]
        graph = GraphData(nodes=nodes)
        
        json_str = graph.to_json()
        data = json.loads(json_str)
        
        assert 'nodes' in data
        assert len(data['nodes']) == 1
        assert data['nodes'][0]['id'] == "1"
    
    def test_graph_from_json(self):
        """Test creating graph from JSON."""
        json_str = '''
        {
            "nodes": [
                {"id": "1", "labels": ["Person"], "properties": {"name": "Alice"}}
            ],
            "relationships": [],
            "schema": null,
            "metadata": {}
        }
        '''
        
        graph = GraphData.from_json(json_str)
        assert len(graph.nodes) == 1
        assert graph.nodes[0].id == "1"
    
    def test_graph_save_load_dag_json(self):
        """Test saving and loading graph in DAG-JSON format."""
        nodes = [
            NodeData(id="1", labels=["Person"], properties={"name": "Alice"}),
            NodeData(id="2", labels=["Person"], properties={"name": "Bob"})
        ]
        rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2")
        ]
        
        graph = GraphData(nodes=nodes, relationships=rels)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
        
        try:
            # Save
            graph.save_to_file(filepath, MigrationFormat.DAG_JSON)
            
            # Load
            loaded_graph = GraphData.load_from_file(filepath, MigrationFormat.DAG_JSON)
            
            assert len(loaded_graph.nodes) == 2
            assert len(loaded_graph.relationships) == 1
            assert loaded_graph.nodes[0].id == "1"
            assert loaded_graph.relationships[0].type == "KNOWS"
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_graph_save_load_jsonlines(self):
        """Test saving and loading graph in JSON Lines format."""
        nodes = [NodeData(id="1", labels=["Person"], properties={"name": "Alice"})]
        rels = [RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2")]
        
        graph = GraphData(nodes=nodes, relationships=rels)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            filepath = f.name
        
        try:
            # Save
            graph.save_to_file(filepath, MigrationFormat.JSON_LINES)
            
            # Load
            loaded_graph = GraphData.load_from_file(filepath, MigrationFormat.JSON_LINES)
            
            assert len(loaded_graph.nodes) == 1
            assert len(loaded_graph.relationships) == 1
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)


class TestErrorHandling:
    """Test error handling in migration formats."""
    
    def test_car_format_not_implemented_save(self):
        """Test that CAR format raises NotImplementedError on save."""
        graph = GraphData(nodes=[NodeData(id="1", labels=["Test"])])
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.car') as f:
            filepath = f.name
        
        try:
            with pytest.raises(NotImplementedError, match="CAR format"):
                graph.save_to_file(filepath, MigrationFormat.CAR)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_car_format_not_implemented_load(self):
        """Test that CAR format raises NotImplementedError on load."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.car') as f:
            filepath = f.name
            f.write("dummy content")
        
        try:
            with pytest.raises(NotImplementedError, match="CAR format"):
                GraphData.load_from_file(filepath, MigrationFormat.CAR)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_malformed_json_input(self):
        """Test that malformed JSON raises appropriate error."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
            f.write("{invalid json}")
        
        try:
            with pytest.raises(json.JSONDecodeError):
                GraphData.load_from_file(filepath, MigrationFormat.DAG_JSON)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_empty_graph_export_import(self):
        """Test exporting and importing an empty graph."""
        empty_graph = GraphData(nodes=[], relationships=[])
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
        
        try:
            # Save empty graph
            empty_graph.save_to_file(filepath, MigrationFormat.DAG_JSON)
            
            # Load and verify
            loaded_graph = GraphData.load_from_file(filepath, MigrationFormat.DAG_JSON)
            assert len(loaded_graph.nodes) == 0
            assert len(loaded_graph.relationships) == 0
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_missing_file_error(self):
        """Test that loading non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            GraphData.load_from_file("/nonexistent/path/file.json", MigrationFormat.DAG_JSON)
    
    def test_invalid_json_structure(self):
        """Test that JSON with invalid structure is handled gracefully."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
            # Valid JSON but wrong structure (missing required fields)
            f.write('{"wrong": "structure"}')
        
        try:
            # The from_dict method should handle missing keys gracefully
            # by using default values from dataclass fields
            loaded_graph = GraphData.load_from_file(filepath, MigrationFormat.DAG_JSON)
            # Should create empty graph since required fields have defaults
            assert len(loaded_graph.nodes) == 0
            assert len(loaded_graph.relationships) == 0
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_corrupted_jsonlines_file(self):
        """Test handling corrupted JSON Lines file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            filepath = f.name
            f.write('{"type": "node", "data": {"id": "1"}}\n')
            f.write('{invalid json line}\n')  # Corrupted line
            f.write('{"type": "node", "data": {"id": "2"}}\n')
        
        try:
            with pytest.raises(json.JSONDecodeError):
                GraphData.load_from_file(filepath, MigrationFormat.JSON_LINES)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_invalid_node_missing_id(self):
        """Test creating node without required ID field."""
        # NodeData requires 'id' parameter
        with pytest.raises(TypeError):
            NodeData(labels=["Test"])  # Missing id
    
    def test_invalid_relationship_missing_fields(self):
        """Test creating relationship without required fields."""
        # RelationshipData requires id, type, start_node, end_node
        with pytest.raises(TypeError):
            RelationshipData(id="1", type="KNOWS")  # Missing start_node and end_node
    
    def test_invalid_property_type_handling(self):
        """Test that complex property types are handled gracefully."""
        # Test with function as property (should convert to string or handle)
        node = NodeData(
            id="1",
            labels=["Test"],
            properties={"func": lambda x: x}  # Invalid property type
        )
        # Should be able to create node, but serialization might fail
        assert node.id == "1"
        
        # Serialization may convert to string or raise error
        try:
            json_str = node.to_json()
            # If it succeeds, verify it's a valid JSON
            data = json.loads(json_str)
        except (TypeError, ValueError):
            # Expected for non-serializable types
            pass


class TestEdgeCases:
    """Test edge cases in migration formats."""
    
    def test_large_graph(self):
        """Test handling large graphs with many nodes and relationships."""
        # Create a graph with 1000 nodes and 5000 relationships
        nodes = [
            NodeData(id=str(i), labels=["Node"], properties={"index": i})
            for i in range(1000)
        ]
        
        relationships = [
            RelationshipData(
                id=str(i),
                type="CONNECTS",
                start_node=str(i % 1000),
                end_node=str((i + 1) % 1000),
                properties={"weight": i * 0.1}
            )
            for i in range(5000)
        ]
        
        graph = GraphData(nodes=nodes, relationships=relationships)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
        
        try:
            # Save and load
            graph.save_to_file(filepath, MigrationFormat.DAG_JSON)
            loaded_graph = GraphData.load_from_file(filepath, MigrationFormat.DAG_JSON)
            
            assert len(loaded_graph.nodes) == 1000
            assert len(loaded_graph.relationships) == 5000
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_unicode_in_names(self):
        """Test handling Unicode characters in entity names."""
        nodes = [
            NodeData(id="1", labels=["人物"], properties={"name": "李明", "city": "北京"}),
            NodeData(id="2", labels=["Persönlich"], properties={"name": "Müller", "beschreibung": "Größe"})
        ]
        
        graph = GraphData(nodes=nodes)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
        
        try:
            graph.save_to_file(filepath, MigrationFormat.DAG_JSON)
            loaded_graph = GraphData.load_from_file(filepath, MigrationFormat.DAG_JSON)
            
            assert loaded_graph.nodes[0].labels[0] == "人物"
            assert loaded_graph.nodes[0].properties["name"] == "李明"
            assert loaded_graph.nodes[1].labels[0] == "Persönlich"
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_special_characters_in_relationship_types(self):
        """Test handling special characters in relationship types."""
        nodes = [
            NodeData(id="1", labels=["Node"]),
            NodeData(id="2", labels=["Node"])
        ]
        rels = [
            RelationshipData(id="1", type="KNOWS-WELL", start_node="1", end_node="2"),
            RelationshipData(id="2", type="IS_A", start_node="1", end_node="2"),
            RelationshipData(id="3", type="HAS:PROPERTY", start_node="1", end_node="2")
        ]
        
        graph = GraphData(nodes=nodes, relationships=rels)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            filepath = f.name
        
        try:
            graph.save_to_file(filepath, MigrationFormat.JSON_LINES)
            loaded_graph = GraphData.load_from_file(filepath, MigrationFormat.JSON_LINES)
            
            assert len(loaded_graph.relationships) == 3
            assert loaded_graph.relationships[0].type == "KNOWS-WELL"
            assert loaded_graph.relationships[2].type == "HAS:PROPERTY"
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_empty_properties_dict(self):
        """Test nodes and relationships with empty properties."""
        node = NodeData(id="1", labels=["Empty"], properties={})
        rel = RelationshipData(id="1", type="EMPTY", start_node="1", end_node="1", properties={})
        
        graph = GraphData(nodes=[node], relationships=[rel])
        
        json_str = graph.to_json()
        loaded_graph = GraphData.from_json(json_str)
        
        assert len(loaded_graph.nodes[0].properties) == 0
        assert len(loaded_graph.relationships[0].properties) == 0
    
    def test_numeric_property_values(self):
        """Test handling numeric property values (int, float)."""
        node = NodeData(
            id="1",
            labels=["Numeric"],
            properties={
                "age": 30,
                "score": 95.5,
                "count": 1000000,
                "ratio": 0.00001
            }
        )
        
        graph = GraphData(nodes=[node])
        json_str = graph.to_json()
        loaded_graph = GraphData.from_json(json_str)
        
        assert loaded_graph.nodes[0].properties["age"] == 30
        assert loaded_graph.nodes[0].properties["score"] == 95.5
    
    def test_boolean_property_values(self):
        """Test handling boolean property values."""
        node = NodeData(
            id="1",
            labels=["Boolean"],
            properties={"active": True, "verified": False}
        )
        
        graph = GraphData(nodes=[node])
        json_str = graph.to_json()
        loaded_graph = GraphData.from_json(json_str)
        
        assert loaded_graph.nodes[0].properties["active"] is True
        assert loaded_graph.nodes[0].properties["verified"] is False
    
    def test_list_property_values(self):
        """Test handling list/array property values."""
        node = NodeData(
            id="1",
            labels=["List"],
            properties={"tags": ["python", "graph", "database"], "scores": [1, 2, 3]}
        )
        
        graph = GraphData(nodes=[node])
        json_str = graph.to_json()
        loaded_graph = GraphData.from_json(json_str)
        
        assert loaded_graph.nodes[0].properties["tags"] == ["python", "graph", "database"]
        assert loaded_graph.nodes[0].properties["scores"] == [1, 2, 3]
    
    def test_nested_dict_property_values(self):
        """Test handling nested dictionary property values."""
        node = NodeData(
            id="1",
            labels=["Nested"],
            properties={
                "address": {
                    "street": "123 Main St",
                    "city": "Boston",
                    "zip": "02101"
                }
            }
        )
        
        graph = GraphData(nodes=[node])
        json_str = graph.to_json()
        loaded_graph = GraphData.from_json(json_str)
        
        assert loaded_graph.nodes[0].properties["address"]["city"] == "Boston"
    
    def test_node_with_no_labels(self):
        """Test node with no labels (empty list)."""
        node = NodeData(id="1", labels=[], properties={"type": "unlabeled"})
        
        graph = GraphData(nodes=[node])
        json_str = graph.to_json()
        loaded_graph = GraphData.from_json(json_str)
        
        assert len(loaded_graph.nodes[0].labels) == 0
    
    def test_relationship_with_no_properties(self):
        """Test relationship with no properties (empty dict)."""
        nodes = [NodeData(id="1"), NodeData(id="2")]
        rel = RelationshipData(id="1", type="LINKED", start_node="1", end_node="2")
        
        graph = GraphData(nodes=nodes, relationships=[rel])
        json_str = graph.to_json()
        loaded_graph = GraphData.from_json(json_str)
        
        assert len(loaded_graph.relationships[0].properties) == 0
    
    def test_self_referencing_relationship(self):
        """Test relationship that references same node."""
        node = NodeData(id="1", labels=["Self"])
        rel = RelationshipData(id="1", type="SELF_REF", start_node="1", end_node="1")
        
        graph = GraphData(nodes=[node], relationships=[rel])
        json_str = graph.to_json()
        loaded_graph = GraphData.from_json(json_str)
        
        rel = loaded_graph.relationships[0]
        assert rel.start_node == rel.end_node == "1"
    
    def test_null_values_in_properties(self):
        """Test handling None/null values in properties."""
        node = NodeData(
            id="1",
            labels=["Null"],
            properties={"value": None, "optional": None}
        )
        
        graph = GraphData(nodes=[node])
        json_str = graph.to_json()
        loaded_graph = GraphData.from_json(json_str)
        
        # None values should be preserved
        assert loaded_graph.nodes[0].properties["value"] is None


class TestFormatConversions:
    """Test format conversions and round-trips."""
    
    def test_graphml_save_load_roundtrip(self):
        """Test GraphML format save and load round-trip."""
        nodes = [
            NodeData(id="1", labels=["Person"], properties={"name": "Alice", "age": 30}),
            NodeData(id="2", labels=["Person"], properties={"name": "Bob", "age": 25})
        ]
        rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2", properties={"since": 2020})
        ]
        
        graph = GraphData(nodes=nodes, relationships=rels)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.graphml') as f:
            filepath = f.name
        
        try:
            # Save to GraphML
            graph.save_to_file(filepath, MigrationFormat.GRAPHML)
            
            # Load from GraphML
            loaded_graph = GraphData.load_from_file(filepath, MigrationFormat.GRAPHML)
            
            assert len(loaded_graph.nodes) == 2
            assert len(loaded_graph.relationships) == 1
            assert loaded_graph.nodes[0].labels == ["Person"]
            assert loaded_graph.relationships[0].type == "KNOWS"
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_gexf_save_load_roundtrip(self):
        """Test GEXF format save and load round-trip."""
        nodes = [
            NodeData(id="1", labels=["City"], properties={"population": 1000000}),
            NodeData(id="2", labels=["City"], properties={"population": 500000})
        ]
        rels = [
            RelationshipData(id="1", type="CONNECTED_TO", start_node="1", end_node="2")
        ]
        
        graph = GraphData(nodes=nodes, relationships=rels)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.gexf') as f:
            filepath = f.name
        
        try:
            # Save to GEXF
            graph.save_to_file(filepath, MigrationFormat.GEXF)
            
            # Load from GEXF
            loaded_graph = GraphData.load_from_file(filepath, MigrationFormat.GEXF)
            
            assert len(loaded_graph.nodes) == 2
            assert len(loaded_graph.relationships) == 1
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_pajek_save_load_roundtrip(self):
        """Test Pajek format save and load round-trip."""
        nodes = [
            NodeData(id="1", labels=["Node"]),
            NodeData(id="2", labels=["Node"]),
            NodeData(id="3", labels=["Node"])
        ]
        rels = [
            RelationshipData(id="1", type="LINK", start_node="1", end_node="2"),
            RelationshipData(id="2", type="LINK", start_node="2", end_node="3")
        ]
        
        graph = GraphData(nodes=nodes, relationships=rels)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.net') as f:
            filepath = f.name
        
        try:
            # Save to Pajek
            graph.save_to_file(filepath, MigrationFormat.PAJEK)
            
            # Load from Pajek
            loaded_graph = GraphData.load_from_file(filepath, MigrationFormat.PAJEK)
            
            assert len(loaded_graph.nodes) == 3
            assert len(loaded_graph.relationships) == 2
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_graphml_with_complex_attributes(self):
        """Test GraphML with multiple attributes."""
        nodes = [
            NodeData(
                id="1",
                labels=["Person", "Employee"],
                properties={
                    "name": "Alice",
                    "age": 30,
                    "department": "Engineering",
                    "salary": 100000
                }
            )
        ]
        
        graph = GraphData(nodes=nodes)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.graphml') as f:
            filepath = f.name
        
        try:
            graph.save_to_file(filepath, MigrationFormat.GRAPHML)
            loaded_graph = GraphData.load_from_file(filepath, MigrationFormat.GRAPHML)
            
            assert len(loaded_graph.nodes) == 1
            assert "Person" in loaded_graph.nodes[0].labels
            assert "Employee" in loaded_graph.nodes[0].labels
            assert loaded_graph.nodes[0].properties["name"] == "Alice"
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)


class TestSchemaAndMetadata:
    """Test schema and metadata handling."""
    
    def test_schema_data_serialization(self):
        """Test SchemaData serialization and deserialization."""
        schema = SchemaData(
            indexes=[{"label": "Person", "property": "name"}],
            constraints=[{"label": "Person", "property": "id", "type": "unique"}],
            node_labels=["Person", "Organization"],
            relationship_types=["KNOWS", "WORKS_AT"]
        )
        
        schema_dict = schema.to_dict()
        loaded_schema = SchemaData.from_dict(schema_dict)
        
        assert len(loaded_schema.indexes) == 1
        assert len(loaded_schema.constraints) == 1
        assert len(loaded_schema.node_labels) == 2
        assert len(loaded_schema.relationship_types) == 2
    
    def test_metadata_preservation(self):
        """Test metadata preservation across save/load."""
        nodes = [NodeData(id="1", labels=["Test"])]
        metadata = {
            "version": "1.0",
            "exported_at": "2026-02-18",
            "source": "Neo4j"
        }
        
        graph = GraphData(nodes=nodes, metadata=metadata)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
        
        try:
            graph.save_to_file(filepath, MigrationFormat.DAG_JSON)
            loaded_graph = GraphData.load_from_file(filepath, MigrationFormat.DAG_JSON)
            
            assert loaded_graph.metadata["version"] == "1.0"
            assert loaded_graph.metadata["source"] == "Neo4j"
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_schema_with_graph_data(self):
        """Test graph with schema information."""
        schema = SchemaData(
            node_labels=["Person"],
            relationship_types=["KNOWS"]
        )
        
        nodes = [NodeData(id="1", labels=["Person"])]
        rels = [RelationshipData(id="1", type="KNOWS", start_node="1", end_node="1")]
        
        graph = GraphData(nodes=nodes, relationships=rels, schema=schema)
        
        json_str = graph.to_json()
        loaded_graph = GraphData.from_json(json_str)
        
        assert loaded_graph.schema is not None
        assert "Person" in loaded_graph.schema.node_labels
        assert "KNOWS" in loaded_graph.schema.relationship_types


if __name__ == "__main__" and HAVE_PYTEST:
    pytest.main([__file__, "-v"])
