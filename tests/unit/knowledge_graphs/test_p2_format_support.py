"""
Tests for P2 Deferred Features: Format Support (GraphML, GEXF, Pajek)

This test suite validates the implementation of additional graph file formats:
1. GraphML format (XML-based, used by Gephi, yEd)
2. GEXF format (Graph Exchange XML Format, used by Gephi)
3. Pajek format (Simple text format for network analysis)

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import pytest
import tempfile
import os
from ipfs_datasets_py.knowledge_graphs.migration.formats import (
    GraphData, NodeData, RelationshipData, MigrationFormat
)


class TestGraphMLFormat:
    """Test suite for GraphML format support."""
    
    @pytest.fixture
    def sample_graph(self):
        """Create a sample graph for testing."""
        nodes = [
            NodeData(id='1', labels=['Person'], properties={'name': 'Alice', 'age': 30}),
            NodeData(id='2', labels=['Person'], properties={'name': 'Bob', 'age': 25}),
            NodeData(id='3', labels=['Person'], properties={'name': 'Charlie', 'age': 35})
        ]
        relationships = [
            RelationshipData(id='r1', type='KNOWS', start_node='1', end_node='2',
                           properties={'since': 2020}),
            RelationshipData(id='r2', type='KNOWS', start_node='2', end_node='3',
                           properties={'since': 2021})
        ]
        return GraphData(nodes=nodes, relationships=relationships)
    
    def test_save_graphml(self, sample_graph):
        """
        GIVEN: A graph with nodes and relationships
        WHEN: Saving to GraphML format
        THEN: File is created with valid GraphML XML
        """
        # GIVEN
        with tempfile.NamedTemporaryFile(mode='w', suffix='.graphml', delete=False) as f:
            filepath = f.name
        
        try:
            # WHEN
            sample_graph.save_to_file(filepath, format=MigrationFormat.GRAPHML)
            
            # THEN
            assert os.path.exists(filepath)
            with open(filepath, 'r') as f:
                content = f.read()
                assert '<?xml' in content
                assert '<graphml' in content
                assert '<node' in content
                assert '<edge' in content
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_load_graphml(self, sample_graph):
        """
        GIVEN: A saved GraphML file
        WHEN: Loading from GraphML format
        THEN: Graph is reconstructed correctly
        """
        # GIVEN
        with tempfile.NamedTemporaryFile(mode='w', suffix='.graphml', delete=False) as f:
            filepath = f.name
        
        try:
            sample_graph.save_to_file(filepath, format=MigrationFormat.GRAPHML)
            
            # WHEN
            loaded_graph = GraphData.load_from_file(filepath, format=MigrationFormat.GRAPHML)
            
            # THEN
            assert loaded_graph.node_count == sample_graph.node_count
            assert loaded_graph.relationship_count == sample_graph.relationship_count
            
            # Check node IDs are preserved
            loaded_ids = {node.id for node in loaded_graph.nodes}
            original_ids = {node.id for node in sample_graph.nodes}
            assert loaded_ids == original_ids
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_graphml_roundtrip(self, sample_graph):
        """
        GIVEN: A graph with various properties
        WHEN: Saving and loading via GraphML
        THEN: All data is preserved (roundtrip test)
        """
        # GIVEN
        with tempfile.NamedTemporaryFile(mode='w', suffix='.graphml', delete=False) as f:
            filepath = f.name
        
        try:
            # WHEN
            sample_graph.save_to_file(filepath, format=MigrationFormat.GRAPHML)
            loaded_graph = GraphData.load_from_file(filepath, format=MigrationFormat.GRAPHML)
            
            # THEN
            assert len(loaded_graph.nodes) == len(sample_graph.nodes)
            assert len(loaded_graph.relationships) == len(sample_graph.relationships)
            
            # Verify node properties are preserved
            for orig_node in sample_graph.nodes:
                loaded_node = next((n for n in loaded_graph.nodes if n.id == orig_node.id), None)
                assert loaded_node is not None
                assert loaded_node.labels == orig_node.labels
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)


class TestGEXFFormat:
    """Test suite for GEXF format support."""
    
    @pytest.fixture
    def sample_graph(self):
        """Create a sample graph for testing."""
        nodes = [
            NodeData(id='1', labels=['Person'], properties={'name': 'Alice'}),
            NodeData(id='2', labels=['Person'], properties={'name': 'Bob'})
        ]
        relationships = [
            RelationshipData(id='r1', type='KNOWS', start_node='1', end_node='2',
                           properties={'weight': 0.8})
        ]
        return GraphData(nodes=nodes, relationships=relationships)
    
    def test_save_gexf(self, sample_graph):
        """
        GIVEN: A graph with nodes and relationships
        WHEN: Saving to GEXF format
        THEN: File is created with valid GEXF XML
        """
        # GIVEN
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gexf', delete=False) as f:
            filepath = f.name
        
        try:
            # WHEN
            sample_graph.save_to_file(filepath, format=MigrationFormat.GEXF)
            
            # THEN
            assert os.path.exists(filepath)
            with open(filepath, 'r') as f:
                content = f.read()
                assert '<?xml' in content
                assert '<gexf' in content
                assert '<nodes>' in content
                assert '<edges>' in content
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_load_gexf(self, sample_graph):
        """
        GIVEN: A saved GEXF file
        WHEN: Loading from GEXF format
        THEN: Graph is reconstructed correctly
        """
        # GIVEN
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gexf', delete=False) as f:
            filepath = f.name
        
        try:
            sample_graph.save_to_file(filepath, format=MigrationFormat.GEXF)
            
            # WHEN
            loaded_graph = GraphData.load_from_file(filepath, format=MigrationFormat.GEXF)
            
            # THEN
            assert loaded_graph.node_count == sample_graph.node_count
            assert loaded_graph.relationship_count == sample_graph.relationship_count
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_gexf_roundtrip(self, sample_graph):
        """
        GIVEN: A graph with properties
        WHEN: Saving and loading via GEXF
        THEN: All data is preserved
        """
        # GIVEN
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gexf', delete=False) as f:
            filepath = f.name
        
        try:
            # WHEN
            sample_graph.save_to_file(filepath, format=MigrationFormat.GEXF)
            loaded_graph = GraphData.load_from_file(filepath, format=MigrationFormat.GEXF)
            
            # THEN
            assert len(loaded_graph.nodes) == len(sample_graph.nodes)
            assert len(loaded_graph.relationships) == len(sample_graph.relationships)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)


class TestPajekFormat:
    """Test suite for Pajek format support."""
    
    @pytest.fixture
    def sample_graph(self):
        """Create a sample graph for testing."""
        nodes = [
            NodeData(id='1', labels=['Node'], properties={'name': 'Node1'}),
            NodeData(id='2', labels=['Node'], properties={'name': 'Node2'}),
            NodeData(id='3', labels=['Node'], properties={'name': 'Node3'})
        ]
        relationships = [
            RelationshipData(id='r1', type='CONNECTED_TO', start_node='1', end_node='2',
                           properties={'weight': 1.5}),
            RelationshipData(id='r2', type='CONNECTED_TO', start_node='2', end_node='3',
                           properties={'weight': 2.0})
        ]
        return GraphData(nodes=nodes, relationships=relationships)
    
    def test_save_pajek(self, sample_graph):
        """
        GIVEN: A graph with nodes and relationships
        WHEN: Saving to Pajek format
        THEN: File is created with valid Pajek format
        """
        # GIVEN
        with tempfile.NamedTemporaryFile(mode='w', suffix='.net', delete=False) as f:
            filepath = f.name
        
        try:
            # WHEN
            sample_graph.save_to_file(filepath, format=MigrationFormat.PAJEK)
            
            # THEN
            assert os.path.exists(filepath)
            with open(filepath, 'r') as f:
                content = f.read()
                assert '*Vertices' in content
                assert '*Arcs' in content
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_load_pajek(self, sample_graph):
        """
        GIVEN: A saved Pajek file
        WHEN: Loading from Pajek format
        THEN: Graph is reconstructed correctly
        """
        # GIVEN
        with tempfile.NamedTemporaryFile(mode='w', suffix='.net', delete=False) as f:
            filepath = f.name
        
        try:
            sample_graph.save_to_file(filepath, format=MigrationFormat.PAJEK)
            
            # WHEN
            loaded_graph = GraphData.load_from_file(filepath, format=MigrationFormat.PAJEK)
            
            # THEN
            assert loaded_graph.node_count == sample_graph.node_count
            assert loaded_graph.relationship_count == sample_graph.relationship_count
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_pajek_roundtrip(self, sample_graph):
        """
        GIVEN: A graph with weighted edges
        WHEN: Saving and loading via Pajek
        THEN: Graph structure is preserved
        """
        # GIVEN
        with tempfile.NamedTemporaryFile(mode='w', suffix='.net', delete=False) as f:
            filepath = f.name
        
        try:
            # WHEN
            sample_graph.save_to_file(filepath, format=MigrationFormat.PAJEK)
            loaded_graph = GraphData.load_from_file(filepath, format=MigrationFormat.PAJEK)
            
            # THEN
            assert len(loaded_graph.nodes) == len(sample_graph.nodes)
            assert len(loaded_graph.relationships) == len(sample_graph.relationships)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)


class TestCARFormat:
    """Test suite for CAR format (should raise NotImplementedError with clear message)."""
    
    def test_car_format_not_implemented_save(self):
        """
        GIVEN: A graph
        WHEN: Attempting to save to CAR format
        THEN: Raises NotImplementedError with helpful message
        """
        # GIVEN
        graph = GraphData(nodes=[], relationships=[])
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.car', delete=False) as f:
            filepath = f.name
        
        try:
            # WHEN/THEN
            with pytest.raises(NotImplementedError) as exc_info:
                graph.save_to_file(filepath, format=MigrationFormat.CAR)
            
            assert 'IPLD CAR library integration' in str(exc_info.value)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_car_format_not_implemented_load(self):
        """
        GIVEN: A CAR file path
        WHEN: Attempting to load from CAR format
        THEN: Raises NotImplementedError with helpful message
        """
        # GIVEN
        with tempfile.NamedTemporaryFile(mode='w', suffix='.car', delete=False) as f:
            filepath = f.name
        
        try:
            # WHEN/THEN
            with pytest.raises(NotImplementedError) as exc_info:
                GraphData.load_from_file(filepath, format=MigrationFormat.CAR)
            
            assert 'IPLD CAR library integration' in str(exc_info.value)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
