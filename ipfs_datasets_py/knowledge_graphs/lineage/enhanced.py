"""
Enhanced lineage tracking features.

This module provides advanced features for lineage tracking including:
- Semantic relationship analysis
- Boundary detection and classification
- Confidence scoring and uncertainty propagation
- Cross-domain lineage tracking

Extracted from cross_document_lineage_enhanced.py.
"""

import logging
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict

from .core import LineageTracker, LineageGraph
from .types import LineageNode, LineageLink, LineageBoundary

logger = logging.getLogger(__name__)


class SemanticAnalyzer:
    """
    Analyzes semantic relationships in lineage graphs.
    
    Provides methods for detecting semantic patterns, relationships,
    and categorizing lineage links based on their semantic meaning.
    """
    
    def __init__(self):
        """Initialize semantic analyzer."""
        self.relationship_categories = {
            'derived_from': 'transformation',
            'contains': 'composition',
            'similar_to': 'similarity',
            'related_to': 'association',
            'version_of': 'versioning',
            'replaces': 'replacement',
        }
    
    def categorize_relationship(self, relationship_type: str) -> str:
        """
        Categorize a relationship type.
        
        Args:
            relationship_type: Type of relationship
            
        Returns:
            Category name
        """
        return self.relationship_categories.get(
            relationship_type,
            'unknown'
        )
    
    def detect_semantic_patterns(
        self,
        graph: LineageGraph,
        node_id: str
    ) -> Dict[str, List[str]]:
        """
        Detect semantic patterns around a node.
        
        Args:
            graph: LineageGraph to analyze
            node_id: Node to analyze patterns for
            
        Returns:
            Dictionary of pattern_type -> [related_node_ids]
        """
        patterns = defaultdict(list)
        
        # Get node
        node = graph.get_node(node_id)
        if not node:
            return {}
        
        # Analyze outgoing relationships
        for neighbor_id in graph.get_neighbors(node_id, direction="out"):
            # Get edge data
            if hasattr(graph._graph, 'edges'):
                edge_data = graph._graph.edges.get((node_id, neighbor_id), {})
                rel_type = edge_data.get('relationship_type', 'unknown')
                category = self.categorize_relationship(rel_type)
                patterns[category].append(neighbor_id)
        
        return dict(patterns)
    
    def calculate_semantic_similarity(
        self,
        node1: LineageNode,
        node2: LineageNode
    ) -> float:
        """
        Calculate semantic similarity between two nodes.
        
        Args:
            node1: First node
            node2: Second node
            
        Returns:
            Similarity score (0.0-1.0)
        """
        score = 0.0
        
        # Same type increases similarity
        if node1.node_type == node2.node_type:
            score += 0.3
        
        # Same entity increases similarity
        if node1.entity_id and node1.entity_id == node2.entity_id:
            score += 0.3
        
        # Metadata overlap
        if node1.metadata and node2.metadata:
            common_keys = set(node1.metadata.keys()) & set(node2.metadata.keys())
            if common_keys:
                matching = sum(
                    1 for k in common_keys
                    if node1.metadata[k] == node2.metadata[k]
                )
                score += 0.4 * (matching / len(common_keys))
        
        return min(score, 1.0)


class BoundaryDetector:
    """
    Detects and classifies boundaries in lineage graphs.
    
    Identifies transitions between different systems, organizations,
    security contexts, or data formats.
    """
    
    def __init__(self):
        """Initialize boundary detector."""
        self.boundary_types = [
            'system', 'organization', 'security',
            'format', 'domain', 'temporal'
        ]
    
    def detect_boundary(
        self,
        source_node: LineageNode,
        target_node: LineageNode
    ) -> Optional[str]:
        """
        Detect if a boundary exists between two nodes.
        
        Args:
            source_node: Source node
            target_node: Target node
            
        Returns:
            Boundary type if detected, None otherwise
        """
        # Check metadata for boundary indicators
        source_meta = source_node.metadata
        target_meta = target_node.metadata
        
        # System boundary
        if (source_meta.get('system') and target_meta.get('system') and
            source_meta['system'] != target_meta['system']):
            return 'system'
        
        # Organization boundary
        if (source_meta.get('organization') and target_meta.get('organization') and
            source_meta['organization'] != target_meta['organization']):
            return 'organization'
        
        # Format boundary
        if (source_meta.get('format') and target_meta.get('format') and
            source_meta['format'] != target_meta['format']):
            return 'format'
        
        # Temporal boundary (significant time gap)
        time_gap = abs(target_node.timestamp - source_node.timestamp)
        if time_gap > 86400:  # 1 day
            return 'temporal'
        
        return None
    
    def classify_boundary_risk(self, boundary_type: str) -> str:
        """
        Classify risk level of a boundary crossing.
        
        Args:
            boundary_type: Type of boundary
            
        Returns:
            Risk level ('low', 'medium', 'high')
        """
        high_risk = ['organization', 'security']
        medium_risk = ['system', 'domain']
        
        if boundary_type in high_risk:
            return 'high'
        elif boundary_type in medium_risk:
            return 'medium'
        else:
            return 'low'


class ConfidenceScorer:
    """
    Calculates and propagates confidence scores in lineage graphs.
    
    Handles uncertainty propagation through transformation chains.
    """
    
    def __init__(self, default_confidence: float = 1.0):
        """
        Initialize confidence scorer.
        
        Args:
            default_confidence: Default confidence for new relationships
        """
        self.default_confidence = default_confidence
    
    def calculate_path_confidence(
        self,
        graph: LineageGraph,
        path: List[str]
    ) -> float:
        """
        Calculate overall confidence for a path.
        
        Args:
            graph: LineageGraph
            path: List of node IDs forming path
            
        Returns:
            Overall confidence score (0.0-1.0)
        """
        if len(path) < 2:
            return 1.0
        
        confidences = []
        
        # Get confidence for each edge in path
        for i in range(len(path) - 1):
            source_id = path[i]
            target_id = path[i + 1]
            
            # Get edge data
            if hasattr(graph._graph, 'edges'):
                edge_data = graph._graph.edges.get((source_id, target_id), {})
                confidence = edge_data.get('confidence', self.default_confidence)
                confidences.append(confidence)
        
        # Multiply confidences (uncertainty compounds)
        if confidences:
            result = 1.0
            for c in confidences:
                result *= c
            return result
        
        return 1.0
    
    def propagate_confidence(
        self,
        tracker: LineageTracker,
        source_id: str,
        max_hops: int = 3
    ) -> Dict[str, float]:
        """
        Propagate confidence scores from a source node.
        
        Args:
            tracker: LineageTracker instance
            source_id: Source node ID
            max_hops: Maximum hops to propagate
            
        Returns:
            Dictionary of node_id -> confidence_score
        """
        confidences = {source_id: 1.0}
        visited = {source_id}
        queue = [(source_id, 1.0, 0)]
        
        while queue:
            current_id, current_conf, depth = queue.pop(0)
            
            if depth >= max_hops:
                continue
            
            # Get downstream neighbors
            neighbors = tracker.graph.get_neighbors(current_id, direction="out")
            
            for neighbor_id in neighbors:
                if neighbor_id not in visited:
                    # Get edge confidence
                    if hasattr(tracker.graph._graph, 'edges'):
                        edge_data = tracker.graph._graph.edges.get(
                            (current_id, neighbor_id), {}
                        )
                        edge_conf = edge_data.get('confidence', self.default_confidence)
                        
                        # Propagated confidence
                        new_conf = current_conf * edge_conf
                        confidences[neighbor_id] = new_conf
                        visited.add(neighbor_id)
                        queue.append((neighbor_id, new_conf, depth + 1))
        
        return confidences


class EnhancedLineageTracker(LineageTracker):
    """
    Enhanced lineage tracker with semantic analysis and boundary detection.
    
    Extends LineageTracker with advanced features:
    - Semantic relationship analysis
    - Automatic boundary detection
    - Confidence scoring and propagation
    """
    
    def __init__(self, **kwargs):
        """Initialize enhanced tracker."""
        super().__init__(**kwargs)
        self.semantic_analyzer = SemanticAnalyzer()
        self.boundary_detector = BoundaryDetector()
        self.confidence_scorer = ConfidenceScorer()
    
    def track_link_with_analysis(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        confidence: Optional[float] = None,
        auto_detect_boundary: bool = True,
        **kwargs
    ) -> str:
        """
        Track a link with automatic semantic analysis and boundary detection.
        
        Args:
            source_id: Source node ID
            target_id: Target node ID
            relationship_type: Relationship type
            confidence: Optional confidence score
            auto_detect_boundary: Whether to auto-detect boundaries
            **kwargs: Additional arguments passed to track_link
            
        Returns:
            Link ID
        """
        # Get nodes
        source_node = self.graph.get_node(source_id)
        target_node = self.graph.get_node(target_id)
        
        if not source_node or not target_node:
            raise ValueError("Both nodes must exist")
        
        # Detect boundary if enabled
        metadata = kwargs.get('metadata', {})
        if auto_detect_boundary:
            boundary_type = self.boundary_detector.detect_boundary(
                source_node, target_node
            )
            if boundary_type:
                metadata['boundary_type'] = boundary_type
                metadata['boundary_risk'] = self.boundary_detector.classify_boundary_risk(
                    boundary_type
                )
        
        # Categorize relationship
        metadata['relationship_category'] = self.semantic_analyzer.categorize_relationship(
            relationship_type
        )
        
        # Use provided confidence or default
        if confidence is None:
            confidence = 1.0
        
        kwargs['metadata'] = metadata
        
        return self.track_link(
            source_id, target_id, relationship_type,
            confidence=confidence, **kwargs
        )
    
    def analyze_node_patterns(self, node_id: str) -> Dict[str, Any]:
        """
        Analyze semantic patterns around a node.
        
        Args:
            node_id: Node to analyze
            
        Returns:
            Dictionary with analysis results
        """
        patterns = self.semantic_analyzer.detect_semantic_patterns(
            self.graph, node_id
        )
        
        # Get confidence propagation
        confidences = self.confidence_scorer.propagate_confidence(self, node_id)
        
        return {
            'semantic_patterns': patterns,
            'confidence_scores': confidences,
            'node_id': node_id
        }
    
    def find_similar_nodes(
        self,
        node_id: str,
        threshold: float = 0.7
    ) -> List[Tuple[str, float]]:
        """
        Find nodes similar to the given node.
        
        Args:
            node_id: Node to find similar nodes for
            threshold: Minimum similarity threshold
            
        Returns:
            List of (node_id, similarity_score) tuples
        """
        node = self.graph.get_node(node_id)
        if not node:
            return []
        
        similar = []
        
        for other_id, other_node in self.graph._nodes.items():
            if other_id == node_id:
                continue
            
            similarity = self.semantic_analyzer.calculate_semantic_similarity(
                node, other_node
            )
            
            if similarity >= threshold:
                similar.append((other_id, similarity))
        
        # Sort by similarity (descending)
        similar.sort(key=lambda x: x[1], reverse=True)
        
        return similar
