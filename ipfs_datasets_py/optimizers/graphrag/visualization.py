"""
Visualization Module for Ontology Optimization.

This module provides visualization capabilities for ontologies and optimization
metrics. Creates graph visualizations, metrics dashboards, and trend plots.

Key Features:
    - Ontology graph visualization (entities and relationships)
    - Metrics dashboard generation
    - Quality score trend plotting
    - Export in multiple formats (text, JSON, HTML-ready)
    - Integration with MetricsCollector and session results

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import (
    ...     OntologyVisualizer,
    ...     MetricsVisualizer
    ... )
    >>> 
    >>> # Visualize ontology
    >>> viz = OntologyVisualizer()
    >>> graph_viz = viz.visualize_ontology(ontology)
    >>> viz.export_to_text(graph_viz, 'ontology.txt')
    >>> 
    >>> # Visualize metrics
    >>> metrics_viz = MetricsVisualizer()
    >>> dashboard = metrics_viz.create_dashboard(metrics_collector)
    >>> print(dashboard)

Note:
    This module provides text-based and data-structure visualizations that
    can be easily converted to graphical formats. For graphical output,
    external libraries like matplotlib, networkx, or plotly can be used
    with the data structures provided by this module.

References:
    - Standard visualization patterns for knowledge graphs
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class GraphVisualization:
    """
    Representation of an ontology graph for visualization.
    
    Attributes:
        nodes: List of nodes (entities) with properties
        edges: List of edges (relationships) between nodes
        metadata: Additional metadata about the graph
        layout: Optional layout information for rendering
    """
    
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    layout: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert visualization to dictionary."""
        return {
            'nodes': self.nodes,
            'edges': self.edges,
            'metadata': self.metadata,
            'layout': self.layout,
        }


class OntologyVisualizer:
    """
    Visualize ontology graphs.
    
    Provides methods to create visualizations of ontology entities and
    relationships in various formats suitable for display or export.
    
    Example:
        >>> visualizer = OntologyVisualizer()
        >>> 
        >>> # Create graph visualization
        >>> graph = visualizer.visualize_ontology(ontology)
        >>> 
        >>> # Export to text
        >>> text = visualizer.export_to_text(graph)
        >>> print(text)
        >>> 
        >>> # Export to JSON for web visualization
        >>> json_str = visualizer.export_to_json(graph)
    """
    
    def __init__(self, max_nodes: int = 100, max_edges: int = 200):
        """
        Initialize the ontology visualizer.
        
        Args:
            max_nodes: Maximum number of nodes to display
            max_edges: Maximum number of edges to display
        """
        self.max_nodes = max_nodes
        self.max_edges = max_edges
        logger.info(
            f"Initialized OntologyVisualizer: max_nodes={max_nodes}, "
            f"max_edges={max_edges}"
        )
    
    def visualize_ontology(
        self,
        ontology: Dict[str, Any],
        highlight_entities: Optional[List[str]] = None
    ) -> GraphVisualization:
        """
        Create a graph visualization from an ontology.
        
        Args:
            ontology: Ontology dictionary with entities and relationships
            highlight_entities: Optional list of entity IDs to highlight
            
        Returns:
            GraphVisualization object
            
        Example:
            >>> graph = visualizer.visualize_ontology(ontology)
            >>> print(f"Nodes: {len(graph.nodes)}, Edges: {len(graph.edges)}")
        """
        logger.info("Creating ontology visualization")
        
        entities = ontology.get('entities', [])
        relationships = ontology.get('relationships', [])
        
        # Limit to max nodes/edges
        if len(entities) > self.max_nodes:
            logger.warning(
                f"Ontology has {len(entities)} entities, limiting to {self.max_nodes}"
            )
            entities = entities[:self.max_nodes]
        
        if len(relationships) > self.max_edges:
            logger.warning(
                f"Ontology has {len(relationships)} relationships, "
                f"limiting to {self.max_edges}"
            )
            relationships = relationships[:self.max_edges]
        
        # Create nodes from entities
        nodes = []
        entity_ids = set()
        
        for entity in entities:
            if isinstance(entity, dict):
                entity_id = entity.get('id', f"entity_{len(nodes)}")
                entity_ids.add(entity_id)
                
                node = {
                    'id': entity_id,
                    'label': entity.get('text', entity.get('type', 'Entity')),
                    'type': entity.get('type', 'Unknown'),
                    'properties': entity.get('properties', {}),
                    'confidence': entity.get('confidence', 1.0),
                    'highlighted': (
                        entity_id in highlight_entities
                        if highlight_entities else False
                    ),
                }
                nodes.append(node)
        
        # Create edges from relationships
        edges = []
        for rel in relationships:
            if isinstance(rel, dict):
                source_id = rel.get('source_id')
                target_id = rel.get('target_id')
                
                # Only include if both entities exist
                if source_id in entity_ids and target_id in entity_ids:
                    edge = {
                        'id': rel.get('id', f"rel_{len(edges)}"),
                        'source': source_id,
                        'target': target_id,
                        'type': rel.get('type', 'related_to'),
                        'properties': rel.get('properties', {}),
                        'confidence': rel.get('confidence', 1.0),
                    }
                    edges.append(edge)
        
        # Create metadata
        metadata = {
            'domain': ontology.get('domain', 'unknown'),
            'num_entities': len(entities),
            'num_relationships': len(relationships),
            'num_nodes': len(nodes),
            'num_edges': len(edges),
            'entity_types': list(set(n['type'] for n in nodes)),
            'relationship_types': list(set(e['type'] for e in edges)),
        }
        
        graph = GraphVisualization(
            nodes=nodes,
            edges=edges,
            metadata=metadata
        )
        
        logger.info(
            f"Created graph: {len(nodes)} nodes, {len(edges)} edges"
        )
        
        return graph
    
    def export_to_text(
        self,
        graph: GraphVisualization,
        include_properties: bool = False
    ) -> str:
        """
        Export graph visualization to text format.
        
        Args:
            graph: GraphVisualization object
            include_properties: Whether to include entity properties
            
        Returns:
            Text representation of the graph
            
        Example:
            >>> text = visualizer.export_to_text(graph, include_properties=True)
            >>> print(text)
        """
        lines = []
        
        # Header
        lines.append("="*60)
        lines.append("Ontology Graph Visualization")
        lines.append("="*60)
        lines.append("")
        
        # Metadata
        lines.append(f"Domain: {graph.metadata.get('domain', 'unknown')}")
        lines.append(f"Nodes: {len(graph.nodes)}")
        lines.append(f"Edges: {len(graph.edges)}")
        lines.append(f"Entity Types: {', '.join(graph.metadata.get('entity_types', []))}")
        lines.append("")
        
        # Nodes
        lines.append("-"*60)
        lines.append("Entities:")
        lines.append("-"*60)
        
        for node in graph.nodes:
            marker = "★" if node.get('highlighted') else "○"
            lines.append(
                f"{marker} {node['id']}: {node['label']} "
                f"[{node['type']}] (conf: {node['confidence']:.2f})"
            )
            
            if include_properties and node.get('properties'):
                for key, value in node['properties'].items():
                    lines.append(f"    - {key}: {value}")
        
        lines.append("")
        
        # Edges
        lines.append("-"*60)
        lines.append("Relationships:")
        lines.append("-"*60)
        
        for edge in graph.edges:
            lines.append(
                f"  {edge['source']} --[{edge['type']}]--> {edge['target']} "
                f"(conf: {edge['confidence']:.2f})"
            )
        
        lines.append("")
        lines.append("="*60)
        
        return "\n".join(lines)
    
    def export_to_json(self, graph: GraphVisualization) -> str:
        """
        Export graph visualization to JSON format.
        
        Args:
            graph: GraphVisualization object
            
        Returns:
            JSON string representation
        """
        return json.dumps(graph.to_dict(), indent=2)
    
    def get_summary_stats(self, graph: GraphVisualization) -> Dict[str, Any]:
        """
        Get summary statistics for a graph visualization.
        
        Args:
            graph: GraphVisualization object
            
        Returns:
            Dictionary with summary statistics
        """
        # Calculate node statistics
        confidences = [n['confidence'] for n in graph.nodes]
        avg_node_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        
        # Calculate edge statistics
        edge_confidences = [e['confidence'] for e in graph.edges]
        avg_edge_confidence = (
            sum(edge_confidences) / len(edge_confidences)
            if edge_confidences else 0.0
        )
        
        # Type distributions
        entity_type_counts = {}
        for node in graph.nodes:
            node_type = node['type']
            entity_type_counts[node_type] = entity_type_counts.get(node_type, 0) + 1
        
        relationship_type_counts = {}
        for edge in graph.edges:
            edge_type = edge['type']
            relationship_type_counts[edge_type] = relationship_type_counts.get(edge_type, 0) + 1
        
        return {
            'num_nodes': len(graph.nodes),
            'num_edges': len(graph.edges),
            'avg_node_confidence': avg_node_confidence,
            'avg_edge_confidence': avg_edge_confidence,
            'entity_type_distribution': entity_type_counts,
            'relationship_type_distribution': relationship_type_counts,
            'density': (
                len(graph.edges) / (len(graph.nodes) * (len(graph.nodes) - 1))
                if len(graph.nodes) > 1 else 0.0
            ),
        }


class MetricsVisualizer:
    """
    Visualize optimization metrics and dashboards.
    
    Creates visualizations for metrics collected during ontology optimization,
    including quality scores, convergence trends, and performance statistics.
    
    Example:
        >>> visualizer = MetricsVisualizer()
        >>> 
        >>> # Create dashboard
        >>> dashboard = visualizer.create_dashboard(metrics_collector)
        >>> print(dashboard)
        >>> 
        >>> # Plot quality trend
        >>> trend_plot = visualizer.plot_quality_trend(metrics_collector)
        >>> print(trend_plot)
    """
    
    def __init__(self):
        """Initialize the metrics visualizer."""
        logger.info("Initialized MetricsVisualizer")
    
    def create_dashboard(
        self,
        metrics_collector: Any,  # MetricsCollector
        width: int = 80
    ) -> str:
        """
        Create a text-based metrics dashboard.
        
        Args:
            metrics_collector: MetricsCollector instance
            width: Width of the dashboard in characters
            
        Returns:
            Text dashboard with metrics summary
            
        Example:
            >>> dashboard = visualizer.create_dashboard(collector)
            >>> print(dashboard)
        """
        stats = metrics_collector.get_statistics()
        
        lines = []
        
        # Header
        lines.append("="*width)
        lines.append("Optimization Metrics Dashboard".center(width))
        lines.append("="*width)
        lines.append("")
        
        # Overview
        lines.append("Overview".center(width))
        lines.append("-"*width)
        lines.append(f"Total Sessions: {stats.get('total_sessions', 0)}")
        lines.append(f"Convergence Rate: {stats.get('convergence_rate', 0.0):.1%}")
        lines.append(f"Average Time: {stats.get('average_time_seconds', 0.0):.2f}s")
        lines.append(f"Sessions/Hour: {stats.get('sessions_per_hour', 0.0):.1f}")
        lines.append("")
        
        # Quality Metrics
        lines.append("Quality Scores".center(width))
        lines.append("-"*width)
        lines.append(
            f"Average: {stats.get('average_quality_score', 0.0):.3f} "
            f"(min: {stats.get('min_quality_score', 0.0):.3f}, "
            f"max: {stats.get('max_quality_score', 0.0):.3f})"
        )
        lines.append(f"Validation: {stats.get('average_validation_score', 0.0):.3f}")
        lines.append("")
        
        # Performance
        lines.append("Performance".center(width))
        lines.append("-"*width)
        lines.append(f"Average Rounds: {stats.get('average_rounds', 0.0):.1f}")
        lines.append(f"Average Entities: {stats.get('average_entities', 0.0):.1f}")
        lines.append(f"Average Relationships: {stats.get('average_relationships', 0.0):.1f}")
        lines.append("")
        
        # Domain Breakdown
        domains = stats.get('domains', {})
        if domains:
            lines.append("Domain Distribution".center(width))
            lines.append("-"*width)
            for domain, count in sorted(domains.items(), key=lambda x: x[1], reverse=True):
                bar_length = int(count / max(domains.values()) * 40)
                bar = "█" * bar_length
                lines.append(f"{domain:15s} {bar} {count}")
            lines.append("")
        
        lines.append("="*width)
        
        return "\n".join(lines)
    
    def plot_quality_trend(
        self,
        metrics_collector: Any,  # MetricsCollector
        window_size: int = 50,
        height: int = 20
    ) -> str:
        """
        Create a text-based plot of quality score trends.
        
        Args:
            metrics_collector: MetricsCollector instance
            window_size: Number of recent sessions to plot
            height: Height of the plot in characters
            
        Returns:
            Text-based plot of quality trends
            
        Example:
            >>> plot = visualizer.plot_quality_trend(collector, window_size=20)
            >>> print(plot)
        """
        time_series = metrics_collector.get_time_series('quality_score')
        
        if not time_series:
            return "No quality score data available"
        
        # Get recent data
        recent_data = time_series[-window_size:] if len(time_series) > window_size else time_series
        
        if not recent_data:
            return "No data to plot"
        
        # Extract scores
        scores = [score for _, score in recent_data]
        
        # Create plot
        lines = []
        lines.append("="*80)
        lines.append("Quality Score Trend (Recent Sessions)".center(80))
        lines.append("="*80)
        lines.append("")
        
        # Y-axis range
        min_score = min(scores)
        max_score = max(scores)
        score_range = max_score - min_score if max_score > min_score else 1.0
        
        # Plot each line
        for i in range(height, -1, -1):
            threshold = min_score + (i / height) * score_range
            line = f"{threshold:4.2f} │"
            
            for score in scores:
                if score >= threshold:
                    line += "█"
                else:
                    line += " "
            
            lines.append(line)
        
        # X-axis
        lines.append("     └" + "─" * len(scores))
        lines.append(f"      Sessions: {len(scores)} (most recent)")
        lines.append("")
        
        # Statistics
        avg_score = sum(scores) / len(scores)
        lines.append(f"Average: {avg_score:.3f}")
        lines.append(f"Min: {min_score:.3f}, Max: {max_score:.3f}")
        lines.append(f"Range: {max_score - min_score:.3f}")
        
        # Trend
        if len(scores) >= 2:
            trend = "↗ Improving" if scores[-1] > scores[0] else "↘ Degrading"
            lines.append(f"Trend: {trend}")
        
        lines.append("")
        lines.append("="*80)
        
        return "\n".join(lines)
    
    def create_session_summary(
        self,
        session_result: Any,  # SessionResult
        width: int = 80
    ) -> str:
        """
        Create a visual summary for a single session result.
        
        Args:
            session_result: SessionResult object
            width: Width of the summary in characters
            
        Returns:
            Text summary with visual elements
        """
        lines = []
        
        # Header
        lines.append("="*width)
        lines.append("Session Summary".center(width))
        lines.append("="*width)
        lines.append("")
        
        # Basic info
        lines.append(f"Rounds: {session_result.num_rounds}")
        lines.append(f"Converged: {'✓ Yes' if session_result.converged else '✗ No'}")
        lines.append(f"Time: {session_result.time_elapsed:.2f}s")
        lines.append("")
        
        # Quality score
        if hasattr(session_result, 'critic_score') and session_result.critic_score:
            score = session_result.critic_score
            overall = score.overall if hasattr(score, 'overall') else 0.0
            
            lines.append("Quality Score:")
            lines.append(self._create_bar("Overall", overall))
            
            if hasattr(score, 'completeness'):
                lines.append(self._create_bar("Completeness", score.completeness))
            if hasattr(score, 'consistency'):
                lines.append(self._create_bar("Consistency", score.consistency))
            if hasattr(score, 'clarity'):
                lines.append(self._create_bar("Clarity", score.clarity))
            
            lines.append("")
        
        # Validation
        if hasattr(session_result, 'validation_result') and session_result.validation_result:
            val = session_result.validation_result
            consistent = getattr(val, 'is_consistent', False)
            lines.append(f"Logical Consistency: {'✓ Valid' if consistent else '✗ Invalid'}")
            
            if hasattr(val, 'contradictions') and val.contradictions:
                lines.append(f"Contradictions: {len(val.contradictions)}")
            
            lines.append("")
        
        # Ontology stats
        if hasattr(session_result, 'ontology'):
            ont = session_result.ontology
            lines.append(f"Entities: {len(ont.get('entities', []))}")
            lines.append(f"Relationships: {len(ont.get('relationships', []))}")
            lines.append(f"Domain: {ont.get('domain', 'unknown')}")
        
        lines.append("")
        lines.append("="*width)
        
        return "\n".join(lines)
    
    def _create_bar(self, label: str, value: float, width: int = 60) -> str:
        """Create a horizontal bar chart."""
        label_width = 20
        bar_width = width - label_width
        filled = int(value * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        return f"  {label:>{label_width}s} │{bar}│ {value:.3f}"


# Export public API
__all__ = [
    'OntologyVisualizer',
    'MetricsVisualizer',
    'GraphVisualization',
]
