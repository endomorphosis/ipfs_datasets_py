"""
Tests for lineage tracking data types.

This module tests the core dataclasses used in lineage tracking.
"""

import pytest
import time
from ipfs_datasets_py.knowledge_graphs.lineage.types import (
    LineageNode,
    LineageLink,
    LineageDomain,
    LineageBoundary,
    LineageTransformationDetail,
    LineageVersion,
    LineageSubgraph,
)


class TestLineageNode:
    """Tests for LineageNode dataclass."""
    
    def test_create_basic_node(self):
        """Test creating a basic lineage node."""
        node = LineageNode(node_id="node_1", node_type="dataset")
        
        assert node.node_id == "node_1"
        assert node.node_type == "dataset"
        assert node.entity_id is None
        assert node.metadata == {}
        assert isinstance(node.timestamp, float)
    
    def test_create_node_with_metadata(self):
        """Test creating a node with metadata."""
        metadata = {"name": "user_data", "size": 1000}
        node = LineageNode(
            node_id="node_2",
            node_type="transformation",
            entity_id="entity_123",
            metadata=metadata
        )
        
        assert node.metadata == metadata
        assert node.entity_id == "entity_123"
    
    def test_node_to_dict(self):
        """Test converting node to dictionary."""
        node = LineageNode(node_id="node_3", node_type="entity")
        node_dict = node.to_dict()
        
        assert isinstance(node_dict, dict)
        assert node_dict["node_id"] == "node_3"
        assert node_dict["node_type"] == "entity"
        assert "timestamp" in node_dict


class TestLineageLink:
    """Tests for LineageLink dataclass."""
    
    def test_create_basic_link(self):
        """Test creating a basic lineage link."""
        link = LineageLink(
            source_id="node_1",
            target_id="node_2",
            relationship_type="derived_from"
        )
        
        assert link.source_id == "node_1"
        assert link.target_id == "node_2"
        assert link.relationship_type == "derived_from"
        assert link.confidence == 1.0
        assert link.direction == "forward"
    
    def test_create_link_with_confidence(self):
        """Test creating a link with confidence score."""
        link = LineageLink(
            source_id="node_1",
            target_id="node_2",
            relationship_type="similar_to",
            confidence=0.85
        )
        
        assert link.confidence == 0.85
    
    def test_link_to_dict(self):
        """Test converting link to dictionary."""
        link = LineageLink(
            source_id="node_1",
            target_id="node_2",
            relationship_type="contains"
        )
        link_dict = link.to_dict()
        
        assert isinstance(link_dict, dict)
        assert link_dict["source_id"] == "node_1"
        assert link_dict["target_id"] == "node_2"


class TestLineageDomain:
    """Tests for LineageDomain dataclass."""
    
    def test_create_basic_domain(self):
        """Test creating a basic domain."""
        domain = LineageDomain(
            domain_id="domain_ml",
            name="Machine Learning Pipeline"
        )
        
        assert domain.domain_id == "domain_ml"
        assert domain.name == "Machine Learning Pipeline"
        assert domain.domain_type == "generic"
    
    def test_create_hierarchical_domain(self):
        """Test creating a domain with parent."""
        parent = LineageDomain(domain_id="parent", name="Parent Domain")
        child = LineageDomain(
            domain_id="child",
            name="Child Domain",
            parent_domain_id="parent"
        )
        
        assert child.parent_domain_id == "parent"


class TestLineageBoundary:
    """Tests for LineageBoundary dataclass."""
    
    def test_create_basic_boundary(self):
        """Test creating a basic boundary."""
        boundary = LineageBoundary(
            boundary_id="boundary_1",
            source_domain_id="domain_a",
            target_domain_id="domain_b",
            boundary_type="api_call"
        )
        
        assert boundary.boundary_id == "boundary_1"
        assert boundary.source_domain_id == "domain_a"
        assert boundary.target_domain_id == "domain_b"
        assert boundary.boundary_type == "api_call"


class TestLineageTransformationDetail:
    """Tests for LineageTransformationDetail dataclass."""
    
    def test_create_transformation_detail(self):
        """Test creating transformation detail."""
        detail = LineageTransformationDetail(
            detail_id="detail_1",
            transformation_id="trans_1",
            operation_type="filter",
            parameters={"condition": "age > 18"}
        )
        
        assert detail.detail_id == "detail_1"
        assert detail.transformation_id == "trans_1"
        assert detail.operation_type == "filter"
        assert detail.parameters["condition"] == "age > 18"
        assert detail.confidence == 1.0


class TestLineageVersion:
    """Tests for LineageVersion dataclass."""
    
    def test_create_version(self):
        """Test creating a version."""
        version = LineageVersion(
            version_id="v1",
            entity_id="entity_1",
            version_number="1.0.0",
            changes="Initial version"
        )
        
        assert version.version_id == "v1"
        assert version.entity_id == "entity_1"
        assert version.version_number == "1.0.0"
        assert version.changes == "Initial version"


class TestLineageSubgraph:
    """Tests for LineageSubgraph dataclass."""
    
    def test_create_subgraph(self):
        """Test creating a subgraph."""
        subgraph = LineageSubgraph(
            subgraph_id="sub_1",
            name="ML Pipeline Subgraph",
            node_ids=["node_1", "node_2", "node_3"],
            link_ids=["link_1", "link_2"]
        )
        
        assert subgraph.subgraph_id == "sub_1"
        assert subgraph.name == "ML Pipeline Subgraph"
        assert len(subgraph.node_ids) == 3
        assert len(subgraph.link_ids) == 2


# Test module can be imported
def test_types_module_import():
    """Test that types module can be imported."""
    from ipfs_datasets_py.knowledge_graphs.lineage import types
    assert hasattr(types, 'LineageNode')
    assert hasattr(types, 'LineageLink')
