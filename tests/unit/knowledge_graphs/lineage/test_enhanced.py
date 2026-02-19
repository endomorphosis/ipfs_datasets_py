"""Tests for enhanced lineage features."""

import pytest

networkx = pytest.importorskip("networkx", reason="NetworkX required for lineage tests")

from ipfs_datasets_py.knowledge_graphs.lineage import (
    EnhancedLineageTracker,
    SemanticAnalyzer,
    BoundaryDetector,
    ConfidenceScorer,
    LineageNode,
)


class TestSemanticAnalyzer:
    """Tests for SemanticAnalyzer."""
    
    def test_categorize_relationship(self):
        """Test relationship categorization."""
        analyzer = SemanticAnalyzer()
        
        assert analyzer.categorize_relationship('derived_from') == 'transformation'
        assert analyzer.categorize_relationship('contains') == 'composition'
        assert analyzer.categorize_relationship('unknown_type') == 'unknown'
    
    def test_calculate_semantic_similarity(self):
        """Test semantic similarity calculation."""
        analyzer = SemanticAnalyzer()
        
        node1 = LineageNode("n1", "dataset", metadata={"name": "data"})
        node2 = LineageNode("n2", "dataset", metadata={"name": "data"})
        
        similarity = analyzer.calculate_semantic_similarity(node1, node2)
        assert similarity > 0.5  # Same type + matching metadata


class TestBoundaryDetector:
    """Tests for BoundaryDetector."""
    
    def test_detect_system_boundary(self):
        """Test system boundary detection."""
        detector = BoundaryDetector()
        
        node1 = LineageNode("n1", "dataset", metadata={"system": "system_a"})
        node2 = LineageNode("n2", "dataset", metadata={"system": "system_b"})
        
        boundary = detector.detect_boundary(node1, node2)
        assert boundary == 'system'
    
    def test_classify_boundary_risk(self):
        """Test boundary risk classification."""
        detector = BoundaryDetector()
        
        assert detector.classify_boundary_risk('organization') == 'high'
        assert detector.classify_boundary_risk('system') == 'medium'
        assert detector.classify_boundary_risk('format') == 'low'


class TestConfidenceScorer:
    """Tests for ConfidenceScorer."""
    
    def test_default_confidence(self):
        """Test default confidence value."""
        scorer = ConfidenceScorer(default_confidence=0.9)
        assert scorer.default_confidence == 0.9


class TestEnhancedLineageTracker:
    """Tests for EnhancedLineageTracker."""
    
    def test_create_enhanced_tracker(self):
        """Test creating enhanced tracker."""
        tracker = EnhancedLineageTracker()
        
        assert tracker.semantic_analyzer is not None
        assert tracker.boundary_detector is not None
        assert tracker.confidence_scorer is not None
    
    def test_track_link_with_analysis(self):
        """Test tracking link with automatic analysis."""
        tracker = EnhancedLineageTracker()
        
        # Add nodes with system metadata
        tracker.track_node("ds1", "dataset", metadata={"system": "A"})
        tracker.track_node("ds2", "dataset", metadata={"system": "B"})
        
        # Track link with auto-analysis
        link_id = tracker.track_link_with_analysis(
            "ds1", "ds2", "derived_from",
            auto_detect_boundary=True
        )
        
        assert link_id is not None
    
    def test_analyze_node_patterns(self):
        """Test node pattern analysis."""
        tracker = EnhancedLineageTracker()
        
        tracker.track_node("ds1", "dataset")
        tracker.track_node("ds2", "dataset")
        tracker.track_link("ds1", "ds2", "derived_from")
        
        analysis = tracker.analyze_node_patterns("ds1")
        
        assert 'semantic_patterns' in analysis
        assert 'confidence_scores' in analysis
    
    def test_find_similar_nodes(self):
        """Test finding similar nodes."""
        tracker = EnhancedLineageTracker()
        
        tracker.track_node("ds1", "dataset", metadata={"name": "data"})
        tracker.track_node("ds2", "dataset", metadata={"name": "data"})
        tracker.track_node("ds3", "transformation")
        
        similar = tracker.find_similar_nodes("ds1", threshold=0.5)
        
        # ds2 should be similar (same type + metadata)
        assert len(similar) > 0
        assert any(node_id == "ds2" for node_id, _ in similar)
