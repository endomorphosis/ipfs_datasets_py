"""Tests for lineage metrics and analysis."""

import pytest
from ipfs_datasets_py.knowledge_graphs.lineage import (
    LineageTracker,
    LineageMetrics,
    ImpactAnalyzer,
    DependencyAnalyzer,
)


class TestLineageMetrics:
    """Tests for LineageMetrics."""
    
    def test_compute_basic_stats(self):
        """Test basic statistics computation."""
        tracker = LineageTracker()
        
        tracker.track_node("ds1", "dataset")
        tracker.track_node("ds2", "dataset")
        tracker.track_link("ds1", "ds2", "derived_from")
        
        metrics = LineageMetrics(tracker.graph)
        stats = metrics.compute_basic_stats()
        
        assert stats['node_count'] == 2
        assert stats['link_count'] == 1
        assert 'density' in stats
        assert 'node_types' in stats
    
    def test_compute_node_metrics(self):
        """Test node-specific metrics."""
        tracker = LineageTracker()
        
        tracker.track_node("ds1", "dataset")
        tracker.track_node("ds2", "dataset")
        tracker.track_node("ds3", "dataset")
        
        tracker.track_link("ds1", "ds2", "derived_from")
        tracker.track_link("ds2", "ds3", "derived_from")
        
        metrics = LineageMetrics(tracker.graph)
        node_metrics = metrics.compute_node_metrics("ds2")
        
        assert node_metrics['in_degree'] == 1
        assert node_metrics['out_degree'] == 1
        assert node_metrics['total_degree'] == 2
    
    def test_find_root_nodes(self):
        """Test finding root nodes."""
        tracker = LineageTracker()
        
        tracker.track_node("root", "dataset")
        tracker.track_node("middle", "dataset")
        tracker.track_node("leaf", "dataset")
        
        tracker.track_link("root", "middle", "derived_from")
        tracker.track_link("middle", "leaf", "derived_from")
        
        metrics = LineageMetrics(tracker.graph)
        roots = metrics.find_root_nodes()
        
        assert "root" in roots
        assert len(roots) == 1
    
    def test_find_leaf_nodes(self):
        """Test finding leaf nodes."""
        tracker = LineageTracker()
        
        tracker.track_node("root", "dataset")
        tracker.track_node("middle", "dataset")
        tracker.track_node("leaf", "dataset")
        
        tracker.track_link("root", "middle", "derived_from")
        tracker.track_link("middle", "leaf", "derived_from")
        
        metrics = LineageMetrics(tracker.graph)
        leaves = metrics.find_leaf_nodes()
        
        assert "leaf" in leaves
        assert len(leaves) == 1


class TestImpactAnalyzer:
    """Tests for ImpactAnalyzer."""
    
    def test_analyze_downstream_impact(self):
        """Test downstream impact analysis."""
        tracker = LineageTracker()
        
        tracker.track_node("ds1", "dataset")
        tracker.track_node("ds2", "dataset")
        tracker.track_node("ds3", "dataset")
        
        tracker.track_link("ds1", "ds2", "derived_from")
        tracker.track_link("ds2", "ds3", "derived_from")
        
        analyzer = ImpactAnalyzer(tracker)
        impact = analyzer.analyze_downstream_impact("ds1")
        
        assert impact['total_downstream'] == 2
        assert 'ds2' in impact['downstream_entities']
        assert 'ds3' in impact['downstream_entities']
    
    def test_analyze_upstream_dependencies(self):
        """Test upstream dependency analysis."""
        tracker = LineageTracker()
        
        tracker.track_node("ds1", "dataset")
        tracker.track_node("ds2", "dataset")
        tracker.track_node("ds3", "dataset")
        
        tracker.track_link("ds1", "ds2", "derived_from")
        tracker.track_link("ds2", "ds3", "derived_from")
        
        analyzer = ImpactAnalyzer(tracker)
        deps = analyzer.analyze_upstream_dependencies("ds3")
        
        assert deps['total_dependencies'] == 2
        assert 'ds1' in deps['upstream_entities']
        assert 'ds2' in deps['upstream_entities']
    
    def test_find_critical_nodes(self):
        """Test finding critical nodes."""
        tracker = LineageTracker()
        
        # Create hub node
        tracker.track_node("hub", "dataset")
        for i in range(5):
            tracker.track_node(f"node_{i}", "dataset")
            tracker.track_link("hub", f"node_{i}", "contains")
        
        analyzer = ImpactAnalyzer(tracker)
        critical = analyzer.find_critical_nodes(threshold=3)
        
        assert len(critical) > 0
        assert critical[0]['node_id'] == "hub"


class TestDependencyAnalyzer:
    """Tests for DependencyAnalyzer."""
    
    def test_find_dependency_chains(self):
        """Test finding dependency chains."""
        tracker = LineageTracker()
        
        tracker.track_node("ds1", "dataset")
        tracker.track_node("ds2", "dataset")
        tracker.track_node("ds3", "dataset")
        
        tracker.track_link("ds1", "ds2", "derived_from")
        tracker.track_link("ds2", "ds3", "derived_from")
        
        analyzer = DependencyAnalyzer(tracker)
        chains = analyzer.find_dependency_chains("ds3", direction='upstream')
        
        assert len(chains) > 0
    
    def test_compute_dependency_depth(self):
        """Test computing dependency depth."""
        tracker = LineageTracker()
        
        tracker.track_node("ds1", "dataset")
        tracker.track_node("ds2", "dataset")
        tracker.track_node("ds3", "dataset")
        
        tracker.track_link("ds1", "ds2", "derived_from")
        tracker.track_link("ds2", "ds3", "derived_from")
        
        analyzer = DependencyAnalyzer(tracker)
        depth = analyzer.compute_dependency_depth("ds3")
        
        assert depth == 2  # Two hops from ds1
