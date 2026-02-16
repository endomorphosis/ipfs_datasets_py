"""
Tests for core lineage tracking functionality.

Tests LineageGraph and LineageTracker classes.
"""

import pytest
import time
from ipfs_datasets_py.knowledge_graphs.lineage import (
    LineageGraph,
    LineageTracker,
    LineageNode,
    LineageLink,
)


class TestLineageGraph:
    """Tests for LineageGraph class."""
    
    def test_create_empty_graph(self):
        """Test creating an empty graph."""
        graph = LineageGraph()
        assert graph.node_count == 0
        assert graph.link_count == 0
    
    def test_add_node(self):
        """Test adding a node to the graph."""
        graph = LineageGraph()
        node = LineageNode(node_id="node_1", node_type="dataset")
        
        node_id = graph.add_node(node)
        
        assert node_id == "node_1"
        assert graph.node_count == 1
        assert graph.get_node("node_1") is not None
    
    def test_add_link(self):
        """Test adding a link between nodes."""
        graph = LineageGraph()
        
        # Add two nodes
        node1 = LineageNode(node_id="node_1", node_type="dataset")
        node2 = LineageNode(node_id="node_2", node_type="dataset")
        graph.add_node(node1)
        graph.add_node(node2)
        
        # Add link
        link = LineageLink(
            source_id="node_1",
            target_id="node_2",
            relationship_type="derived_from"
        )
        link_id = graph.add_link(link)
        
        assert link_id == "node_1:node_2:derived_from"
        assert graph.link_count == 1
    
    def test_get_neighbors_out(self):
        """Test getting outgoing neighbors."""
        graph = LineageGraph()
        
        # Create simple chain: node1 -> node2 -> node3
        for i in range(1, 4):
            node = LineageNode(node_id=f"node_{i}", node_type="dataset")
            graph.add_node(node)
        
        graph.add_link(LineageLink("node_1", "node_2", "derived_from"))
        graph.add_link(LineageLink("node_2", "node_3", "derived_from"))
        
        neighbors = graph.get_neighbors("node_1", direction="out")
        assert "node_2" in neighbors
        assert len(neighbors) == 1
    
    def test_get_neighbors_in(self):
        """Test getting incoming neighbors."""
        graph = LineageGraph()
        
        # Create simple chain
        for i in range(1, 4):
            node = LineageNode(node_id=f"node_{i}", node_type="dataset")
            graph.add_node(node)
        
        graph.add_link(LineageLink("node_1", "node_2", "derived_from"))
        graph.add_link(LineageLink("node_2", "node_3", "derived_from"))
        
        neighbors = graph.get_neighbors("node_3", direction="in")
        assert "node_2" in neighbors
    
    def test_find_path(self):
        """Test finding path between nodes."""
        graph = LineageGraph()
        
        # Create path: node1 -> node2 -> node3
        for i in range(1, 4):
            node = LineageNode(node_id=f"node_{i}", node_type="dataset")
            graph.add_node(node)
        
        graph.add_link(LineageLink("node_1", "node_2", "derived_from"))
        graph.add_link(LineageLink("node_2", "node_3", "derived_from"))
        
        path = graph.find_path("node_1", "node_3")
        assert path == ["node_1", "node_2", "node_3"]
    
    def test_find_path_no_connection(self):
        """Test finding path when no connection exists."""
        graph = LineageGraph()
        
        # Create disconnected nodes
        graph.add_node(LineageNode("node_1", "dataset"))
        graph.add_node(LineageNode("node_2", "dataset"))
        
        path = graph.find_path("node_1", "node_2")
        assert path is None
    
    def test_get_subgraph(self):
        """Test extracting a subgraph."""
        graph = LineageGraph()
        
        # Create graph with 4 nodes
        for i in range(1, 5):
            graph.add_node(LineageNode(f"node_{i}", "dataset"))
        
        graph.add_link(LineageLink("node_1", "node_2", "derived_from"))
        graph.add_link(LineageLink("node_2", "node_3", "derived_from"))
        graph.add_link(LineageLink("node_3", "node_4", "derived_from"))
        
        # Extract subgraph with nodes 1,2,3
        subgraph = graph.get_subgraph(["node_1", "node_2", "node_3"])
        
        assert subgraph.node_count == 3
        assert subgraph.link_count == 2  # Links between included nodes


class TestLineageTracker:
    """Tests for LineageTracker class."""
    
    def test_create_tracker(self):
        """Test creating a lineage tracker."""
        tracker = LineageTracker()
        stats = tracker.get_stats()
        
        assert stats['node_count'] == 0
        assert stats['link_count'] == 0
    
    def test_track_node(self):
        """Test tracking a node."""
        tracker = LineageTracker()
        
        node_id = tracker.track_node(
            "dataset_1",
            "dataset",
            metadata={"name": "users", "size": 1000}
        )
        
        assert node_id == "dataset_1"
        
        # Verify node was added
        node = tracker.graph.get_node("dataset_1")
        assert node is not None
        assert node.node_type == "dataset"
        assert node.metadata["name"] == "users"
    
    def test_track_link(self):
        """Test tracking a link between nodes."""
        tracker = LineageTracker()
        
        # Track two nodes
        tracker.track_node("ds_1", "dataset")
        tracker.track_node("ds_2", "dataset")
        
        # Track link
        link_id = tracker.track_link("ds_1", "ds_2", "derived_from", confidence=0.95)
        
        assert link_id == "ds_1:ds_2:derived_from"
        assert tracker.get_stats()['link_count'] == 1
    
    def test_track_link_missing_source(self):
        """Test tracking link with missing source node."""
        tracker = LineageTracker()
        tracker.track_node("ds_2", "dataset")
        
        with pytest.raises(ValueError, match="Source node .* does not exist"):
            tracker.track_link("ds_1", "ds_2", "derived_from")
    
    def test_track_link_missing_target(self):
        """Test tracking link with missing target node."""
        tracker = LineageTracker()
        tracker.track_node("ds_1", "dataset")
        
        with pytest.raises(ValueError, match="Target node .* does not exist"):
            tracker.track_link("ds_1", "ds_2", "derived_from")
    
    def test_track_transformation(self):
        """Test tracking transformation details."""
        tracker = LineageTracker()
        
        detail_id = tracker.track_transformation(
            "trans_1",
            "filter",
            inputs=[{"field": "age"}],
            outputs=[{"field": "age_filtered"}],
            parameters={"condition": "age > 18"}
        )
        
        assert detail_id is not None
        assert len(tracker._transformation_details) == 1
    
    def test_track_version(self):
        """Test tracking entity versions."""
        tracker = LineageTracker()
        
        version_id = tracker.track_version(
            "entity_1",
            "1.0.0",
            changes="Initial version"
        )
        
        assert version_id is not None
        assert len(tracker._versions) == 1
    
    def test_find_lineage_path(self):
        """Test finding lineage path."""
        tracker = LineageTracker()
        
        # Create chain: ds1 -> ds2 -> ds3
        tracker.track_node("ds_1", "dataset")
        tracker.track_node("ds_2", "dataset")
        tracker.track_node("ds_3", "dataset")
        
        tracker.track_link("ds_1", "ds_2", "derived_from")
        tracker.track_link("ds_2", "ds_3", "derived_from")
        
        path = tracker.find_lineage_path("ds_1", "ds_3")
        assert path == ["ds_1", "ds_2", "ds_3"]
    
    def test_get_upstream_entities(self):
        """Test getting upstream entities."""
        tracker = LineageTracker()
        
        # Create: ds1 -> ds2 -> ds3 -> ds4
        for i in range(1, 5):
            tracker.track_node(f"ds_{i}", "dataset")
        
        tracker.track_link("ds_1", "ds_2", "derived_from")
        tracker.track_link("ds_2", "ds_3", "derived_from")
        tracker.track_link("ds_3", "ds_4", "derived_from")
        
        # Get upstream of ds4
        upstream = tracker.get_upstream_entities("ds_4")
        assert set(upstream) == {"ds_1", "ds_2", "ds_3"}
    
    def test_get_upstream_entities_limited(self):
        """Test getting upstream entities with hop limit."""
        tracker = LineageTracker()
        
        # Create: ds1 -> ds2 -> ds3 -> ds4
        for i in range(1, 5):
            tracker.track_node(f"ds_{i}", "dataset")
        
        tracker.track_link("ds_1", "ds_2", "derived_from")
        tracker.track_link("ds_2", "ds_3", "derived_from")
        tracker.track_link("ds_3", "ds_4", "derived_from")
        
        # Get upstream with 1 hop
        upstream = tracker.get_upstream_entities("ds_4", max_hops=1)
        assert set(upstream) == {"ds_3"}
    
    def test_get_downstream_entities(self):
        """Test getting downstream entities."""
        tracker = LineageTracker()
        
        # Create: ds1 -> ds2 -> ds3 -> ds4
        for i in range(1, 5):
            tracker.track_node(f"ds_{i}", "dataset")
        
        tracker.track_link("ds_1", "ds_2", "derived_from")
        tracker.track_link("ds_2", "ds_3", "derived_from")
        tracker.track_link("ds_3", "ds_4", "derived_from")
        
        # Get downstream of ds1
        downstream = tracker.get_downstream_entities("ds_1")
        assert set(downstream) == {"ds_2", "ds_3", "ds_4"}
    
    def test_query_by_node_type(self):
        """Test querying nodes by type."""
        tracker = LineageTracker()
        
        tracker.track_node("ds_1", "dataset")
        tracker.track_node("ds_2", "dataset")
        tracker.track_node("trans_1", "transformation")
        
        datasets = tracker.query(node_type="dataset")
        assert len(datasets) == 2
        assert all(n.node_type == "dataset" for n in datasets)
    
    def test_query_by_entity_id(self):
        """Test querying nodes by entity ID."""
        tracker = LineageTracker()
        
        tracker.track_node("node_1", "dataset", entity_id="entity_123")
        tracker.track_node("node_2", "dataset", entity_id="entity_456")
        
        results = tracker.query(entity_id="entity_123")
        assert len(results) == 1
        assert results[0].entity_id == "entity_123"
    
    def test_temporal_consistency_enabled(self):
        """Test temporal consistency checking when enabled."""
        tracker = LineageTracker(enable_temporal_consistency=True)
        
        # Track nodes with explicit timestamps
        tracker.track_node("ds_1", "dataset")
        time.sleep(0.01)  # Small delay
        tracker.track_node("ds_2", "dataset")
        
        # Link should be temporally consistent (ds_1 before ds_2)
        link_id = tracker.track_link("ds_1", "ds_2", "derived_from")
        assert link_id is not None
    
    def test_get_stats(self):
        """Test getting tracker statistics."""
        tracker = LineageTracker()
        
        tracker.track_node("ds_1", "dataset")
        tracker.track_node("ds_2", "dataset")
        tracker.track_link("ds_1", "ds_2", "derived_from")
        
        stats = tracker.get_stats()
        assert stats['node_count'] == 2
        assert stats['link_count'] == 1
        assert 'has_cycles' in stats


# Test integration between classes
def test_lineage_workflow():
    """Test complete lineage tracking workflow."""
    tracker = LineageTracker()
    
    # Track data pipeline
    tracker.track_node("raw_data", "dataset", metadata={"source": "api"})
    tracker.track_node("cleaned_data", "dataset", metadata={"source": "pipeline"})
    tracker.track_node("aggregated_data", "dataset", metadata={"source": "pipeline"})
    
    tracker.track_link("raw_data", "cleaned_data", "derived_from")
    tracker.track_link("cleaned_data", "aggregated_data", "derived_from")
    
    # Track transformation
    tracker.track_transformation(
        "trans_1",
        "filter",
        inputs=[{"field": "timestamp"}],
        outputs=[{"field": "filtered_timestamp"}]
    )
    
    # Query the lineage
    path = tracker.find_lineage_path("raw_data", "aggregated_data")
    assert len(path) == 3
    
    # Get stats
    stats = tracker.get_stats()
    assert stats['node_count'] == 3
    assert stats['link_count'] == 2
    assert stats['transformation_count'] == 1
