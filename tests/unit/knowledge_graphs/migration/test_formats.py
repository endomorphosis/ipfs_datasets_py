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


if __name__ == "__main__" and HAVE_PYTEST:
    pytest.main([__file__, "-v"])
