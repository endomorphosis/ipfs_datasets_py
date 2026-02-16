"""
Lineage metrics and analysis.

Provides metrics computation and impact analysis for lineage graphs.
"""

import logging
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict

from .core import LineageGraph, LineageTracker

logger = logging.getLogger(__name__)


class LineageMetrics:
    """
    Computes metrics for lineage graphs.
    
    Provides various metrics including:
    - Graph statistics (nodes, edges, density)
    - Node centrality measures
    - Path statistics
    - Complexity measures
    """
    
    def __init__(self, graph: LineageGraph):
        """
        Initialize metrics computer.
        
        Args:
            graph: LineageGraph to analyze
        """
        self.graph = graph
    
    def compute_basic_stats(self) -> Dict[str, Any]:
        """
        Compute basic graph statistics.
        
        Returns:
            Dictionary with statistics
        """
        node_count = self.graph.node_count
        link_count = self.graph.link_count
        
        # Calculate density
        max_edges = node_count * (node_count - 1)
        density = link_count / max_edges if max_edges > 0 else 0.0
        
        # Node type distribution
        node_types = defaultdict(int)
        for node in self.graph._nodes.values():
            node_types[node.node_type] += 1
        
        return {
            'node_count': node_count,
            'link_count': link_count,
            'density': density,
            'node_types': dict(node_types),
            'avg_degree': (2 * link_count / node_count) if node_count > 0 else 0
        }
    
    def compute_node_metrics(self, node_id: str) -> Dict[str, Any]:
        """
        Compute metrics for a specific node.
        
        Args:
            node_id: Node to analyze
            
        Returns:
            Dictionary with node metrics
        """
        if node_id not in self.graph._graph:
            return {}
        
        # In-degree and out-degree
        in_degree = len(self.graph.get_neighbors(node_id, direction="in"))
        out_degree = len(self.graph.get_neighbors(node_id, direction="out"))
        
        return {
            'node_id': node_id,
            'in_degree': in_degree,
            'out_degree': out_degree,
            'total_degree': in_degree + out_degree
        }
    
    def find_root_nodes(self) -> List[str]:
        """
        Find root nodes (nodes with no predecessors).
        
        Returns:
            List of root node IDs
        """
        roots = []
        for node_id in self.graph._nodes.keys():
            if len(self.graph.get_neighbors(node_id, direction="in")) == 0:
                roots.append(node_id)
        return roots
    
    def find_leaf_nodes(self) -> List[str]:
        """
        Find leaf nodes (nodes with no successors).
        
        Returns:
            List of leaf node IDs
        """
        leaves = []
        for node_id in self.graph._nodes.keys():
            if len(self.graph.get_neighbors(node_id, direction="out")) == 0:
                leaves.append(node_id)
        return leaves
    
    def compute_path_statistics(self) -> Dict[str, Any]:
        """
        Compute statistics about paths in the graph.
        
        Returns:
            Dictionary with path statistics
        """
        roots = self.find_root_nodes()
        leaves = self.find_leaf_nodes()
        
        path_lengths = []
        
        # Compute paths from roots to leaves
        for root in roots[:10]:  # Limit to first 10 roots for performance
            for leaf in leaves[:10]:  # Limit to first 10 leaves
                path = self.graph.find_path(root, leaf)
                if path:
                    path_lengths.append(len(path) - 1)  # Number of hops
        
        if path_lengths:
            return {
                'min_path_length': min(path_lengths),
                'max_path_length': max(path_lengths),
                'avg_path_length': sum(path_lengths) / len(path_lengths),
                'total_paths_analyzed': len(path_lengths)
            }
        else:
            return {
                'min_path_length': 0,
                'max_path_length': 0,
                'avg_path_length': 0.0,
                'total_paths_analyzed': 0
            }


class ImpactAnalyzer:
    """
    Analyzes impact and dependencies in lineage graphs.
    
    Provides methods to understand how changes to one entity
    affect others in the lineage.
    """
    
    def __init__(self, tracker: LineageTracker):
        """
        Initialize impact analyzer.
        
        Args:
            tracker: LineageTracker instance
        """
        self.tracker = tracker
    
    def analyze_downstream_impact(
        self,
        node_id: str,
        max_depth: int = -1
    ) -> Dict[str, Any]:
        """
        Analyze downstream impact of a node.
        
        Args:
            node_id: Node to analyze impact for
            max_depth: Maximum depth to analyze (-1 for unlimited)
            
        Returns:
            Dictionary with impact analysis
        """
        downstream = self.tracker.get_downstream_entities(node_id, max_hops=max_depth)
        
        # Categorize by type
        by_type = defaultdict(list)
        for entity_id in downstream:
            node = self.tracker.graph.get_node(entity_id)
            if node:
                by_type[node.node_type].append(entity_id)
        
        return {
            'node_id': node_id,
            'total_downstream': len(downstream),
            'downstream_by_type': dict(by_type),
            'downstream_entities': downstream
        }
    
    def analyze_upstream_dependencies(
        self,
        node_id: str,
        max_depth: int = -1
    ) -> Dict[str, Any]:
        """
        Analyze upstream dependencies of a node.
        
        Args:
            node_id: Node to analyze dependencies for
            max_depth: Maximum depth to analyze (-1 for unlimited)
            
        Returns:
            Dictionary with dependency analysis
        """
        upstream = self.tracker.get_upstream_entities(node_id, max_hops=max_depth)
        
        # Categorize by type
        by_type = defaultdict(list)
        for entity_id in upstream:
            node = self.tracker.graph.get_node(entity_id)
            if node:
                by_type[node.node_type].append(entity_id)
        
        return {
            'node_id': node_id,
            'total_dependencies': len(upstream),
            'dependencies_by_type': dict(by_type),
            'upstream_entities': upstream
        }
    
    def find_critical_nodes(self, threshold: int = 3) -> List[Dict[str, Any]]:
        """
        Find nodes that are critical (high degree or many dependencies).
        
        Args:
            threshold: Minimum degree to be considered critical
            
        Returns:
            List of dictionaries with critical node info
        """
        critical = []
        
        for node_id in self.tracker.graph._nodes.keys():
            downstream = self.tracker.get_downstream_entities(node_id, max_hops=1)
            upstream = self.tracker.get_upstream_entities(node_id, max_hops=1)
            
            total_connections = len(downstream) + len(upstream)
            
            if total_connections >= threshold:
                critical.append({
                    'node_id': node_id,
                    'connections': total_connections,
                    'upstream_count': len(upstream),
                    'downstream_count': len(downstream)
                })
        
        # Sort by connections (descending)
        critical.sort(key=lambda x: x['connections'], reverse=True)
        
        return critical


class DependencyAnalyzer:
    """
    Analyzes dependency relationships in lineage graphs.
    
    Identifies dependency patterns, circular dependencies, and
    dependency chains.
    """
    
    def __init__(self, tracker: LineageTracker):
        """
        Initialize dependency analyzer.
        
        Args:
            tracker: LineageTracker instance
        """
        self.tracker = tracker
    
    def detect_circular_dependencies(self) -> List[List[str]]:
        """
        Detect circular dependencies in the graph.
        
        Returns:
            List of cycles (each cycle is a list of node IDs)
        """
        try:
            import networkx as nx
            
            # Find cycles
            cycles = list(nx.simple_cycles(self.tracker.graph._graph))
            return cycles
        except ImportError:
            logger.warning("NetworkX required for cycle detection")
            return []
    
    def find_dependency_chains(
        self,
        node_id: str,
        direction: str = 'upstream'
    ) -> List[List[str]]:
        """
        Find all dependency chains starting from a node.
        
        Args:
            node_id: Starting node
            direction: 'upstream' or 'downstream'
            
        Returns:
            List of chains (each chain is a list of node IDs)
        """
        chains = []
        
        def explore_chain(current_id: str, path: List[str]):
            """Recursively explore dependency chain."""
            if current_id in path:  # Avoid cycles
                return
            
            new_path = path + [current_id]
            
            # Get neighbors
            if direction == 'upstream':
                neighbors = self.tracker.graph.get_neighbors(current_id, direction="in")
            else:
                neighbors = self.tracker.graph.get_neighbors(current_id, direction="out")
            
            if not neighbors:
                # End of chain
                chains.append(new_path)
            else:
                for neighbor in neighbors:
                    explore_chain(neighbor, new_path)
        
        explore_chain(node_id, [])
        
        return chains
    
    def compute_dependency_depth(self, node_id: str) -> int:
        """
        Compute maximum dependency depth for a node.
        
        Args:
            node_id: Node to analyze
            
        Returns:
            Maximum depth (number of hops to furthest dependency)
        """
        upstream = self.tracker.get_upstream_entities(node_id)
        
        if not upstream:
            return 0
        
        # Find maximum path length
        max_depth = 0
        for upstream_id in upstream:
            path = self.tracker.find_lineage_path(upstream_id, node_id)
            if path:
                depth = len(path) - 1
                max_depth = max(max_depth, depth)
        
        return max_depth
