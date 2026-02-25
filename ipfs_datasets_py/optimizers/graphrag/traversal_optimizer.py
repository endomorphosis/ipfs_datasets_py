"""Traversal optimization module for query optimization.

This module handles Wikipedia and IPLD-specific traversal strategies,
entity importance scoring, and relationship weighting.
"""

import logging
from typing import Dict, Any, Set
from collections import defaultdict

logging.basicConfig(level=logging.INFO)


class TraversalOptimizer:
    """Optimizes query traversal strategies for different graph types.
    
    Handles traversal parameter optimization for Wikipedia and IPLD graphs,
    entity importance scoring, and relationship weighting.
    """

    # Class-level cache for entity importance scores
    _entity_importance_cache: Dict[str, float] = {}
    _cache_max_size = 1000
    
    # Wikipedia relation importance hierarchy
    WIKIPEDIA_RELATION_IMPORTANCE = {
        # Taxonomic relationships - highest value (0.9+)
        "instance_of": 0.95,
        "subclass_of": 0.92,
        "type_of": 0.90,
        "category": 0.90,
        
        # Compositional relationships - high value (0.8+)
        "part_of": 0.88,
        "has_part": 0.85,
        "contains": 0.85,
        "component_of": 0.83,
        "member_of": 0.82,
        "has_member": 0.82,
        
        # Spatial relationships - high value (0.7+)
        "located_in": 0.79,
        "capital_of": 0.78,
        "headquarters_in": 0.78,
        "geographical_location": 0.75,
        "neighbor_of": 0.72,
        
        # Causal and temporal relationships - medium-high value (0.6+)
        "created_by": 0.69,
        "developer": 0.68,
        "author": 0.67,
        "invented_by": 0.65,
        "founder": 0.65,
        "preceded_by": 0.62,
        "followed_by": 0.62,
        "influenced": 0.60,
        
        # Functional relationships - medium value (0.5+)
        "function": 0.58,
        "used_for": 0.57,
        "works_on": 0.55,
        "employed_by": 0.55,
        "opposite_of": 0.53,
        "similar_to": 0.52,
        
        # General associative relationships - lower value (0.4+)
        "related_to": 0.45,
        "associated_with": 0.42,
        "see_also": 0.40,
        
        # Weak relationships - lowest value (<0.4)
        "different_from": 0.35,
        "same_as": 0.35,
        "externally_linked": 0.32,
        "link": 0.30,
        "described_by": 0.30
    }
    
    # IPLD relation importance hierarchy (content-addressed graph specific)
    IPLD_RELATION_IMPORTANCE = {
        # Content relationship (most important for IPLD)
        "content_hash": 0.95,
        "references": 0.92,
        "links_to": 0.88,
        
        # Structural relationships
        "part_of_dataset": 0.85,
        "version_of": 0.83,
        "derived_from": 0.80,
        
        # Semantic relationships
        "semantic_link": 0.75,
        "related_to": 0.60,
        "associated_with": 0.55,
        
        # Temporal relationships
        "created_at": 0.70,
        "modified_at": 0.65,
        "archived_at": 0.50,
        
        # Verification relationships
        "verified_by": 0.90,
        "signed_by": 0.88,
        "attested_by": 0.85,
        
        # Metadata relationships
        "has_metadata": 0.60,
        "described_by": 0.55
    }

    def __init__(self):
        """Initialize traversal optimizer with relation importance scores."""
        # Statistics tracking
        self.traversal_stats = {
            "paths_explored": [],
            "path_scores": {},
            "entity_frequency": defaultdict(int),
            "entity_connectivity": {},
            "relation_usefulness": defaultdict(float)
        }

    @staticmethod
    def calculate_entity_importance(entity_id: str, graph_processor: Any) -> float:
        """Calculate the importance score of an entity in the knowledge graph.
        
        Uses various metrics like centrality, inbound/outbound connections,
        and semantic richness to determine entity importance for traversal.
        
        Args:
            entity_id: ID of the entity to evaluate
            graph_processor: GraphRAG processor with graph access
            
        Returns:
            float: Importance score (0.0-1.0)
        """
        # Check cache first
        if entity_id in TraversalOptimizer._entity_importance_cache:
            return TraversalOptimizer._entity_importance_cache[entity_id]
        
        # Base score
        importance = 0.5
        
        try:
            # Get entity information
            entity_info = graph_processor.get_entity_info(entity_id)
            
            if entity_info:
                # Factor 1: Connection count (normalized)
                inbound_connections = len(entity_info.get("inbound_connections", []))
                outbound_connections = len(entity_info.get("outbound_connections", []))
                total_connections = inbound_connections + outbound_connections
                connection_score = min(1.0, total_connections / 20.0)
                
                # Factor 2: Connection diversity (unique relation types)
                relation_types = set()
                for conn in entity_info.get("inbound_connections", []) + entity_info.get("outbound_connections", []):
                    relation_types.add(conn.get("relation_type", ""))
                diversity_score = min(1.0, len(relation_types) / 10.0)
                
                # Factor 3: Semantic richness (properties count)
                property_count = len(entity_info.get("properties", {}))
                property_score = min(1.0, property_count / 15.0)
                
                # Factor 4: Entity type importance
                entity_type = entity_info.get("type", "").lower()
                type_score = 0.5  # Default
                if entity_type in ["concept", "topic", "category"]:
                    type_score = 0.9
                elif entity_type in ["person", "organization", "location"]:
                    type_score = 0.8
                elif entity_type in ["event", "work"]:
                    type_score = 0.7
                
                # Calculate weighted importance
                importance = (
                    connection_score * 0.4 +
                    diversity_score * 0.25 +
                    property_score * 0.15 +
                    type_score * 0.2
                )
        
        except (ValueError, TypeError, AttributeError, KeyError, RuntimeError, OSError) as e:
            logging.warning(f"Error calculating entity importance for {entity_id}: {e}")
        
        # Cache the result (with size management)
        if len(TraversalOptimizer._entity_importance_cache) < TraversalOptimizer._cache_max_size:
            TraversalOptimizer._entity_importance_cache[entity_id] = importance
        
        return importance

    @staticmethod
    def optimize_wikipedia_traversal(
        query: Dict[str, Any],
        entity_scores: Dict[str, float]
    ) -> Dict[str, Any]:
        """Apply Wikipedia-specific traversal optimizations.
        
        Uses statistical analysis and entity importance to optimize
        traversal for Wikipedia-derived knowledge graphs.
        
        Args:
            query: Original query parameters
            entity_scores: Dictionary of entity importance scores
            
        Returns:
            Dict: Optimized query parameters with Wikipedia traversal settings
        """
        optimized_query = query.copy()
        
        # Ensure traversal section exists
        if "traversal" not in optimized_query:
            optimized_query["traversal"] = {}
        
        traversal = optimized_query["traversal"]
        query_text = query.get("query_text", "")
        
        # Detect relation types from query
        query_relations = TraversalOptimizer._detect_query_relations(query_text)
        if query_relations:
            traversal["detected_relations"] = query_relations
        
        # If edge types are specified, reorder by importance
        if "edge_types" in traversal:
            edge_types = traversal["edge_types"]
            
            def get_edge_score(edge_type):
                if query_relations and edge_type in query_relations:
                    return 1.0 + TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE.get(edge_type, 0.5)
                return TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE.get(edge_type, 0.5)
            
            prioritized_edges = sorted(edge_types, key=get_edge_score, reverse=True)
            traversal["edge_types"] = prioritized_edges
            traversal["edge_importance_scores"] = {edge: get_edge_score(edge) for edge in edge_types}
        
        # Set hierarchical weighting
        traversal["hierarchical_weight"] = 1.5
        
        # Adaptive parameters based on query complexity
        query_complexity = TraversalOptimizer._estimate_query_complexity(optimized_query)
        if query_complexity == "high":
            traversal["max_breadth_per_level"] = 5
            traversal["use_importance_pruning"] = True
            traversal["importance_threshold"] = 0.4
        elif query_complexity == "medium":
            traversal["max_breadth_per_level"] = 7
            traversal["use_importance_pruning"] = True
            traversal["importance_threshold"] = 0.3
        else:
            traversal["max_breadth_per_level"] = 10
            traversal["use_importance_pruning"] = False
        
        # Add entity scores for prioritization
        traversal["entity_scores"] = entity_scores
        
        # Set Wikipedia-specific options
        traversal["wikipedia_traversal_options"] = {
            "follow_redirects": True,
            "resolve_disambiguation": True,
            "use_category_hierarchy": True,
            "include_infobox_data": True,
            "confidence_weighting": True,
            "popularity_bias": 0.3,
            "recency_bias": 0.2,
            "reference_count_boost": True,
            "trusted_source_boost": True,
            "quality_class_awareness": True
        }
        
        return optimized_query

    @staticmethod
    def optimize_ipld_traversal(
        query: Dict[str, Any],
        entity_scores: Dict[str, float]
    ) -> Dict[str, Any]:
        """Apply IPLD-specific traversal optimizations.
        
        Optimizes traversal for IPLD (content-addressed) graphs with
        focus on hash verification and structural navigation.
        
        Args:
            query: Original query parameters
            entity_scores: Dictionary of entity importance scores
            
        Returns:
            Dict: Optimized query parameters with IPLD traversal settings
        """
        optimized_query = query.copy()
        
        # Ensure traversal section exists
        if "traversal" not in optimized_query:
            optimized_query["traversal"] = {}
        
        traversal = optimized_query["traversal"]
        
        # Detect and prioritize content relationships
        if "edge_types" in traversal:
            edge_types = traversal["edge_types"]
            
            def get_ipld_edge_score(edge_type):
                return TraversalOptimizer.IPLD_RELATION_IMPORTANCE.get(edge_type, 0.4)
            
            prioritized_edges = sorted(edge_types, key=get_ipld_edge_score, reverse=True)
            traversal["edge_types"] = prioritized_edges
            traversal["edge_importance_scores"] = {edge: get_ipld_edge_score(edge) for edge in edge_types}
        
        # IPLD-specific traversal settings
        traversal["ipld_traversal_options"] = {
            "verify_content_hash": True,
            "follow_references": True,
            "include_version_history": True,
            "check_signatures": True,
            "validate_attestations": True,
            "use_merkle_proofs": True,
            "support_dag_navigation": True,
            "include_metadata": True,
            "preserve_content_addressing": True
        }
        
        # Add entity scores
        traversal["entity_scores"] = entity_scores
        
        return optimized_query

    @staticmethod
    def optimize_traversal_path(
        query: Dict[str, Any],
        current_path: list,
        target_entity_id: str
    ) -> Dict[str, Any]:
        """Optimize traversal path for reaching a target entity.
        
        Determines best path and parameters for traversing to target entity.
        
        Args:
            query: Current query parameters
            current_path: Current traversal path
            target_entity_id: Target entity to reach
            
        Returns:
            Dict: Optimized traversal parameters
        """
        optimized = query.copy()
        
        if "traversal" not in optimized:
            optimized["traversal"] = {}
        
        traversal = optimized["traversal"]
        
        # Path optimization
        path_length = len(current_path)
        traversal["current_path_length"] = path_length
        traversal["target_entity"] = target_entity_id
        
        # Adaptive depth based on current path
        if path_length >= 2:
            traversal["max_depth"] = max(1, traversal.get("max_depth", 3) - 1)
        
        return optimized

    @staticmethod
    def update_relation_usefulness(
        relation_type: str,
        query_success: float,
        relation_usefulness_stats: Dict[str, float]
    ) -> None:
        """Update relation usefulness score based on query success.
        
        Dynamically adjusts relation importance based on historical success.
        
        Args:
            relation_type: Type of relation to update
            query_success: Success score for the query (0.0-1.0)
            relation_usefulness_stats: Dictionary to update with usefulness scores
        """
        if relation_type not in relation_usefulness_stats:
            relation_usefulness_stats[relation_type] = 0.5
        
        # Exponential moving average update
        alpha = 0.3  # Learning rate
        current = relation_usefulness_stats[relation_type]
        relation_usefulness_stats[relation_type] = (
            alpha * query_success + (1 - alpha) * current
        )

    @staticmethod
    def _detect_query_relations(query_text: str) -> list:
        """Detect relation types mentioned in query text.
        
        Args:
            query_text: The query text to analyze
            
        Returns:
            list: Detected relation types
        """
        query_relations = []
        if not query_text:
            return query_relations
        
        query_text_lower = query_text.lower()
        
        # Relation detection patterns
        patterns = {
            "instance_of": ["type", "instance", "is a", "example of"],
            "part_of": ["part", "component", "contain", "within", "inside"],
            "located_in": ["located", "where", "place", "location"],
            "created_by": ["created", "made", "developed", "authored", "wrote"],
            "similar_to": ["similar", "like", "analogous"],
            "subclass_of": ["kind of", "sort of", "class of"],
            "member_of": ["member", "part of group"],
            "works_on": ["works on", "employed by"],
            "related_to": ["related", "associated", "connected"]
        }
        
        for relation, keywords in patterns.items():
            if any(term in query_text_lower for term in keywords):
                query_relations.append(relation)
        
        return query_relations

    @staticmethod
    def _estimate_query_complexity(query: Dict[str, Any]) -> str:
        """Estimate query complexity as low/medium/high.
        
        Args:
            query: Query parameters
            
        Returns:
            str: Complexity level ("low", "medium", or "high")
        """
        complexity_score = 0
        
        # Traversal depth factor
        traversal = query.get("traversal", {})
        max_depth = traversal.get("max_depth", 2)
        if max_depth > 3:
            complexity_score += 2
        elif max_depth > 2:
            complexity_score += 1
        
        # Entity count factor
        entity_ids = query.get("entity_ids", [])
        if len(entity_ids) > 3:
            complexity_score += 2
        elif len(entity_ids) > 1:
            complexity_score += 1
        
        # Vector search factor
        vector_params = query.get("vector_params", {})
        if vector_params:
            top_k = vector_params.get("top_k", 5)
            if top_k > 10:
                complexity_score += 1
        
        # Filters factor
        if "filters" in query:
            complexity_score += 1
        
        # Multi-pass factor
        if query.get("multi_pass", False):
            complexity_score += 2
        
        # Determine complexity level
        if complexity_score >= 4:
            return "high"
        elif complexity_score >= 2:
            return "medium"
        else:
            return "low"
