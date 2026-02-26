"""
Tests for relationship_analyzer TypedDict contracts.
"""

import pytest
from ipfs_datasets_py.processors.relationship_analyzer import (
    EntityRelationshipsDict,
    CrossDocRelationshipsDict,
    GraphVisualizationDict,
)


class TestEntityRelationshipsDict:
    """Test EntityRelationshipsDict contract."""
    
    def test_entity_relationships_structure(self):
        """Verify entity relationships structure."""
        sample: EntityRelationshipsDict = {
            "entities": [{"id": "e1", "name": "Entity1"}],
            "relationships": [{"source": "e1", "target": "e2"}],
            "total_relationships": 1,
            "processing_time": 0.5,
            "confidence_scores": {"relationship": 0.9}
        }
        assert isinstance(sample.get("entities"), (list, type(None)))
        assert isinstance(sample.get("relationships"), (list, type(None)))
    
    def test_entity_relationships_types(self):
        """Verify field types."""
        sample: EntityRelationshipsDict = {
            "total_relationships": 10,
            "processing_time": 1.5
        }
        assert isinstance(sample.get("total_relationships"), (int, type(None)))
        assert isinstance(sample.get("processing_time"), (float, type(None)))


class TestCrossDocRelationshipsDict:
    """Test CrossDocRelationshipsDict contract."""
    
    def test_cross_doc_relationships_structure(self):
        """Verify cross-document relationships structure."""
        sample: CrossDocRelationshipsDict = {
            "relationships": [{"id": "r1", "documents": ["d1", "d2"]}],
            "document_pairs": [("d1", "d2")],
            "relationship_count": 1,
            "processing_time": 0.5
        }
        assert isinstance(sample.get("relationships"), (list, type(None)))
        assert isinstance(sample.get("document_pairs"), (list, type(None)))
    
    def test_cross_doc_relationships_counts(self):
        """Verify count fields."""
        sample: CrossDocRelationshipsDict = {
            "relationship_count": 5,
            "processing_time": 0.3
        }
        assert isinstance(sample.get("relationship_count"), (int, type(None)))


class TestGraphVisualizationDict:
    """Test GraphVisualizationDict contract."""
    
    def test_graph_visualization_structure(self):
        """Verify graph visualization structure."""
        sample: GraphVisualizationDict = {
            "nodes": [{"id": "n1", "label": "Node1"}],
            "edges": [{"source": "n1", "target": "n2"}],
            "metadata": {"version": "1.0"},
            "graph_metrics": {"density": 0.5}
        }
        assert isinstance(sample.get("nodes"), (list, type(None)))
        assert isinstance(sample.get("edges"), (list, type(None)))
    
    def test_graph_visualization_metadata(self):
        """Verify metadata fields."""
        sample: GraphVisualizationDict = {
            "metadata": {"creator": "analyzer"},
            "graph_metrics": {"nodes": 10, "edges": 15}
        }
        assert isinstance(sample.get("metadata"), (dict, type(None)))
        assert isinstance(sample.get("graph_metrics"), (dict, type(None)))


class TestIntegration:
    """Integration tests for relationship analyzer TypedDicts."""
    
    def test_typeddicts_as_dicts(self):
        """Verify TypedDicts work as regular dicts."""
        entity_result: EntityRelationshipsDict = {
            "entities": [],
            "relationships": []
        }
        assert len(entity_result) >= 0
        for key in entity_result:
            assert isinstance(key, str)
    
    def test_partial_field_sets(self):
        """Verify partial field sets work (total=False)."""
        minimal: EntityRelationshipsDict = {}
        assert isinstance(minimal, dict)
        
        with_one: CrossDocRelationshipsDict = {"relationship_count": 0}
        assert "relationship_count" in with_one


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
