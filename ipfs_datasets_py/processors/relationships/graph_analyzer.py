#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Graph Analyzer

Core business logic for graph analysis including clustering, metrics, and entity focusing.
Reusable by CLI, MCP tools, and third-party packages.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Set, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class GraphAnalyzer:
    """
    Analyzes relationship graphs and calculates graph metrics.
    
    Provides methods for:
    - Graph clustering detection
    - Graph metrics calculation
    - Entity focusing and filtering
    
    Example:
        >>> analyzer = GraphAnalyzer()
        >>> clusters = analyzer.detect_clusters(entities, relationships)
        >>> metrics = analyzer.calculate_metrics(entities, relationships)
    """
    
    def __init__(self):
        """Initialize the GraphAnalyzer."""
        pass
    
    def focus_on_entity(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        focus_entity: str,
        max_depth: int
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Focus relationship mapping around a specific entity.
        
        Args:
            entities: List of all entities
            relationships: List of all relationships
            focus_entity: Entity ID to focus on
            max_depth: Maximum relationship depth to include
            
        Returns:
            Tuple of (filtered entities, filtered relationships)
        """
        # Build adjacency map
        adjacency = defaultdict(set)
        for rel in relationships:
            adjacency[rel["source_entity"]].add(rel["target_entity"])
            adjacency[rel["target_entity"]].add(rel["source_entity"])
        
        # BFS to find entities within max_depth
        visited = set()
        queue = [(focus_entity, 0)]
        focused_entities = set()
        
        while queue:
            current_entity, depth = queue.pop(0)
            
            if current_entity in visited or depth > max_depth:
                continue
            
            visited.add(current_entity)
            focused_entities.add(current_entity)
            
            # Add neighbors to queue
            for neighbor in adjacency.get(current_entity, []):
                if neighbor not in visited:
                    queue.append((neighbor, depth + 1))
        
        # Filter entities and relationships
        filtered_entities = [e for e in entities if e["id"] in focused_entities]
        filtered_relationships = [
            r for r in relationships
            if r["source_entity"] in focused_entities and r["target_entity"] in focused_entities
        ]
        
        return filtered_entities, filtered_relationships
    
    def detect_relationship_clusters(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Detect clusters of highly connected entities.
        
        Args:
            entities: List of entities
            relationships: List of relationships
            
        Returns:
            List of cluster dictionaries
        """
        # Build adjacency map
        adjacency = defaultdict(set)
        for rel in relationships:
            adjacency[rel["source_entity"]].add(rel["target_entity"])
            adjacency[rel["target_entity"]].add(rel["source_entity"])
        
        # Find connected components using DFS
        visited = set()
        clusters = []
        
        for entity in entities:
            entity_id = entity["id"]
            if entity_id not in visited:
                cluster_entities = []
                self._dfs_cluster(entity_id, adjacency, visited, cluster_entities)
                
                if cluster_entities:
                    cluster_density = self._calculate_cluster_density(cluster_entities, relationships)
                    clusters.append({
                        "cluster_id": f"cluster_{len(clusters)}",
                        "entity_count": len(cluster_entities),
                        "entities": cluster_entities,
                        "density": cluster_density,
                        "cohesion_score": cluster_density * len(cluster_entities)
                    })
        
        # Sort clusters by size
        clusters.sort(key=lambda c: c["entity_count"], reverse=True)
        
        return clusters
    
    def _dfs_cluster(
        self,
        entity: str,
        adjacency: Dict[str, set],
        visited: set,
        cluster: List[str]
    ):
        """Depth-first search for cluster detection."""
        if entity in visited:
            return
        
        visited.add(entity)
        cluster.append(entity)
        
        for neighbor in adjacency.get(entity, []):
            if neighbor not in visited:
                self._dfs_cluster(neighbor, adjacency, visited, cluster)
    
    def _calculate_cluster_density(
        self,
        cluster_entities: List[str],
        relationships: List[Dict[str, Any]]
    ) -> float:
        """Calculate density of a cluster."""
        if len(cluster_entities) < 2:
            return 0.0
        
        entity_set = set(cluster_entities)
        internal_edges = sum(
            1 for rel in relationships
            if rel["source_entity"] in entity_set and rel["target_entity"] in entity_set
        )
        
        max_possible_edges = len(cluster_entities) * (len(cluster_entities) - 1) / 2
        return internal_edges / max_possible_edges if max_possible_edges > 0 else 0.0
    
    def calculate_graph_metrics(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive graph metrics.
        
        Args:
            entities: List of entities
            relationships: List of relationships
            
        Returns:
            Dictionary of graph metrics
        """
        if not entities:
            return {}
        
        # Basic counts
        entity_count = len(entities)
        relationship_count = len(relationships)
        
        # Calculate degree distribution
        degree_map = defaultdict(int)
        for rel in relationships:
            degree_map[rel["source_entity"]] += 1
            degree_map[rel["target_entity"]] += 1
        
        degrees = list(degree_map.values())
        avg_degree = sum(degrees) / len(degrees) if degrees else 0
        max_degree = max(degrees) if degrees else 0
        
        # Calculate density
        max_possible_edges = entity_count * (entity_count - 1) / 2
        density = relationship_count / max_possible_edges if max_possible_edges > 0 else 0
        
        return {
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "average_degree": avg_degree,
            "max_degree": max_degree,
            "graph_density": density,
            "connected_components": len(self.detect_relationship_clusters(entities, relationships))
        }
