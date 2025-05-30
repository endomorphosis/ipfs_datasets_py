"""
Wikipedia-specific RAG Query Optimizer for GraphRAG operations.

This module extends the base RAG Query Optimizer to provide specialized optimizations
for Wikipedia-derived knowledge graphs. It leverages the specific structure and characteristics
of knowledge graphs extracted from Wikipedia pages to improve query performance,
relevance, and resource efficiency.

Key features:
- Hierarchical category-based query planning
- Topic-based query expansion for improved recall
- Entity popularity-based prioritization
- Category filtering and weighting
- Reference-based trustworthiness scoring
- Advanced path filtering for Wikipedia-specific relationships
- Specialized traversal strategies for Wikipedia knowledge structures
"""

import time
import numpy as np
import re
from typing import Dict, List, Any, Optional, Tuple, Callable, Union, Set
from collections import defaultdict

from ipfs_datasets_py.rag_query_optimizer import (
    GraphRAGQueryOptimizer,
    QueryRewriter,
    QueryBudgetManager,
    UnifiedGraphRAGQueryOptimizer,
    QueryMetricsCollector
)
from ipfs_datasets_py.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer


class WikipediaRelationshipWeightCalculator:
    """
    Calculates weights for different Wikipedia relationship types to prioritize traversal.

    This class assigns weights to different relationship types found in Wikipedia-derived
    knowledge graphs based on their importance for query relevance. These weights are used
    to prioritize certain relationship types during graph traversal.
    """

    # Default weights for common Wikipedia relationship types
    DEFAULT_RELATIONSHIP_WEIGHTS = {
        # Hierarchical relationships
        "subclass_of": 1.5,
        "instance_of": 1.4,
        "part_of": 1.3,
        "has_part": 1.2,

        # Category relationships
        "category_contains": 1.3,
        "in_category": 1.3,

        # Topic relationships
        "related_to": 1.0,
        "similar_to": 0.9,
        "refers_to": 0.8,

        # Authorship and creation relationships
        "created_by": 0.7,
        "authored_by": 0.7,
        "developed_by": 0.7,

        # Temporal relationships
        "preceded_by": 0.6,
        "succeeded_by": 0.6,

        # Causal relationships
        "causes": 1.1,
        "caused_by": 1.1,

        # Generic relationships
        "mentions": 0.5,
        "mentioned_in": 0.5,

        # Default for unknown relationships
        "default": 0.5
    }

    def __init__(self, custom_weights: Optional[Dict[str, float]] = None):
        """
        Initialize the relationship weight calculator.

        Args:
            custom_weights (Dict[str, float], optional): Custom relationship weights
        """
        self.weights = self.DEFAULT_RELATIONSHIP_WEIGHTS.copy()
        if custom_weights:
            self.weights.update(custom_weights)

    def get_relationship_weight(self, relationship_type: str) -> float:
        """
        Get the weight for a specific relationship type.

        Args:
            relationship_type (str): The type of relationship

        Returns:
            float: Weight value for the relationship
        """
        # Handle variations in relationship names
        normalized_type = self._normalize_relationship_type(relationship_type)

        # Return the weight if it exists, otherwise return the default weight
        return self.weights.get(normalized_type, self.weights["default"])

    def _normalize_relationship_type(self, relationship_type: str) -> str:
        """
        Normalize relationship type string for consistent lookup.

        Args:
            relationship_type (str): The relationship type to normalize

        Returns:
            str: Normalized relationship type
        """
        # Convert to lowercase
        normalized = relationship_type.lower()

        # Remove spaces and underscores, convert to snake_case
        normalized = re.sub(r'[\s-]+', '_', normalized)

        # Handle common variations
        mapping = {
            "is_subclass_of": "subclass_of",
            "is_instance_of": "instance_of",
            "is_part_of": "part_of",
            "contains_part": "has_part",
            "is_related_to": "related_to",
            "is_similar_to": "similar_to",
            "refers_to": "refers_to",
            "is_created_by": "created_by",
            "is_authored_by": "authored_by",
            "is_developed_by": "developed_by",
            "is_preceded_by": "preceded_by",
            "is_succeeded_by": "succeeded_by",
            "is_mentioned_in": "mentioned_in"
        }

        return mapping.get(normalized, normalized)

    def get_prioritized_relationship_types(self, relationship_types: List[str]) -> List[str]:
        """
        Sort relationship types by their weights in descending order.

        Args:
            relationship_types (List[str]): List of relationship types

        Returns:
            List[str]: Relationship types sorted by weight (highest first)
        """
        return sorted(
            relationship_types,
            key=lambda rel_type: self.get_relationship_weight(rel_type),
            reverse=True
        )

    def get_filtered_high_value_relationships(
        self,
        relationship_types: List[str],
        min_weight: float = 0.7
    ) -> List[str]:
        """
        Filter relationship types to only include those with weight >= min_weight.

        Args:
            relationship_types (List[str]): List of relationship types
            min_weight (float): Minimum weight threshold

        Returns:
            List[str]: Filtered list of high-value relationship types
        """
        return [
            rel_type for rel_type in relationship_types
            if self.get_relationship_weight(rel_type) >= min_weight
        ]


class WikipediaCategoryHierarchyManager:
    """
    Manages Wikipedia category hierarchies for optimizing traversal strategies.

    This class helps navigate and optimize traversals through Wikipedia's category
    structure, which is a key aspect of Wikipedia-derived knowledge graphs.
    """

    def __init__(self):
        """Initialize the category hierarchy manager."""
        # Category depth cache (category_name -> depth)
        self.category_depth_cache = {}

        # Category specificity scores (category_name -> specificity)
        self.category_specificity = {}

        # Category connections (category_name -> [related_categories])
        self.category_connections = defaultdict(set)

    def register_category_connection(self, parent_category: str, child_category: str) -> None:
        """
        Register a connection between two categories.

        Args:
            parent_category (str): The parent category
            child_category (str): The child category
        """
        self.category_connections[parent_category].add(child_category)

    def calculate_category_depth(self, category: str, visited: Optional[Set[str]] = None) -> int:
        """
        Calculate the depth of a category in the hierarchy.

        Args:
            category (str): The category name
            visited (Set[str], optional): Set of already visited categories to avoid cycles

        Returns:
            int: The calculated depth (higher is more specific)
        """
        # Check cache first
        if category in self.category_depth_cache:
            return self.category_depth_cache[category]

        # Initialize visited set if not provided
        if visited is None:
            visited = set()

        # Avoid cycles
        if category in visited:
            return 0

        visited.add(category)

        # If category has no parents, it's a root category (depth 0)
        parents = [
            parent for parent, children in self.category_connections.items()
            if category in children
        ]

        if not parents:
            depth = 0
        else:
            # Get the maximum depth of any parent + 1
            depth = max(self.calculate_category_depth(parent, visited) for parent in parents) + 1

        # Cache the result
        self.category_depth_cache[category] = depth

        return depth

    def assign_category_weights(self, query_vector: np.ndarray, categories: List[str],
                               similarity_scores: Dict[str, float] = None) -> Dict[str, float]:
        """
        Assign weights to categories based on depth and similarity to query.

        Args:
            query_vector (np.ndarray): The query vector
            categories (List[str]): List of category names
            similarity_scores (Dict[str, float], optional): Pre-computed similarity scores

        Returns:
            Dict[str, float]: Category weights (name -> weight)
        """
        weights = {}

        for category in categories:
            # Get depth-based score (normalized to 0.5-1.5 range)
            depth = self.calculate_category_depth(category)
            depth_score = 0.5 + min(depth / 10.0, 1.0)  # Max bonus at depth 10

            # Get similarity score if provided, otherwise default to 1.0
            sim_score = similarity_scores.get(category, 1.0) if similarity_scores else 1.0

            # Combine scores
            weights[category] = depth_score * sim_score

        return weights

    def get_related_categories(self, category: str, max_distance: int = 2) -> List[Tuple[str, int]]:
        """
        Get categories related to the given category within the specified distance.

        Args:
            category (str): The source category
            max_distance (int): Maximum traversal distance

        Returns:
            List[Tuple[str, int]]: List of (category_name, distance) pairs
        """
        result = []
        visited = set()
        queue = [(category, 0)]  # (category, distance)

        while queue:
            current, distance = queue.pop(0)

            if current in visited:
                continue

            visited.add(current)

            if current != category:  # Don't include the source category
                result.append((current, distance))

            if distance < max_distance:
                # Add child categories
                for child in self.category_connections.get(current, set()):
                    if child not in visited:
                        queue.append((child, distance + 1))

                # Add parent categories
                for parent, children in self.category_connections.items():
                    if current in children and parent not in visited:
                        queue.append((parent, distance + 1))

        return result


class WikipediaEntityImportanceCalculator:
    """
    Calculates importance scores for Wikipedia entities to prioritize traversal.

    This class assigns importance scores to entities in Wikipedia-derived knowledge
    graphs based on factors like popularity, connections, reference count, etc.
    These scores help prioritize which entities to explore during graph traversal.
    """

    def __init__(self):
        """Initialize the entity importance calculator."""
        # Entity importance score cache
        self.entity_importance_cache = {}

        # Feature weights for importance calculation
        self.feature_weights = {
            "connection_count": 0.3,
            "reference_count": 0.2,
            "category_importance": 0.2,
            "explicitness": 0.15,
            "recency": 0.15
        }

    def calculate_entity_importance(
        self,
        entity_data: Dict[str, Any],
        category_weights: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Calculate importance score for an entity.

        Args:
            entity_data (Dict): Entity data with relevant features
            category_weights (Dict[str, float], optional): Category importance weights

        Returns:
            float: Entity importance score (0.0-1.0)
        """
        # Check cache first
        entity_id = entity_data.get("id", "")
        if entity_id and entity_id in self.entity_importance_cache:
            return self.entity_importance_cache[entity_id]

        # Calculate feature scores
        scores = {}

        # 1. Connection count (inbound and outbound links)
        inbound = len(entity_data.get("inbound_connections", []))
        outbound = len(entity_data.get("outbound_connections", []))
        total_connections = inbound + outbound
        # Normalize with diminishing returns (log scale)
        scores["connection_count"] = min(1.0, np.log1p(total_connections) / np.log1p(100))

        # 2. Reference count (citations)
        references = entity_data.get("references", [])
        ref_count = len(references) if isinstance(references, list) else 0
        scores["reference_count"] = min(1.0, np.log1p(ref_count) / np.log1p(20))

        # 3. Category importance
        if category_weights:
            entity_categories = entity_data.get("categories", [])
            if entity_categories:
                # Average of category weights
                category_score = sum(category_weights.get(cat, 0.5) for cat in entity_categories)
                category_score /= len(entity_categories)
                scores["category_importance"] = min(1.0, category_score)
            else:
                scores["category_importance"] = 0.5
        else:
            scores["category_importance"] = 0.5

        # 4. Explicitness (how explicitly the entity is mentioned)
        mentions = entity_data.get("mention_count", 0)
        scores["explicitness"] = min(1.0, np.log1p(mentions) / np.log1p(50))

        # 5. Recency (if available)
        if "last_modified" in entity_data:
            # Convert to timestamp if string
            timestamp = entity_data["last_modified"]
            if isinstance(timestamp, str):
                try:
                    timestamp = time.mktime(time.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ"))
                except ValueError:
                    timestamp = time.time()  # Default to current time if parsing fails

            # Calculate recency score (1.0 for newest, decreasing with age)
            now = time.time()
            age_days = (now - timestamp) / (24 * 3600)
            scores["recency"] = max(0.0, min(1.0, 1.0 - (age_days / 365)))  # Linear decay over a year
        else:
            scores["recency"] = 0.5  # Default if no timestamp

        # Combine feature scores with weights
        importance = sum(scores[feature] * weight for feature, weight in self.feature_weights.items())

        # Cache the result
        if entity_id:
            self.entity_importance_cache[entity_id] = importance

        return importance

    def rank_entities_by_importance(
        self,
        entities: List[Dict[str, Any]],
        category_weights: Optional[Dict[str, float]] = None
    ) -> List[Dict[str, Any]]:
        """
        Rank entities by their calculated importance.

        Args:
            entities (List[Dict]): List of entity data dictionaries
            category_weights (Dict[str, float], optional): Category importance weights

        Returns:
            List[Dict]: Entities sorted by importance (highest first)
        """
        # Calculate importance for each entity
        entities_with_scores = [
            (entity, self.calculate_entity_importance(entity, category_weights))
            for entity in entities
        ]

        # Sort by importance score (descending)
        sorted_entities = [
            entity for entity, _ in sorted(entities_with_scores, key=lambda x: x[1], reverse=True)
        ]

        return sorted_entities


class WikipediaQueryExpander:
    """
    Expands queries with relevant Wikipedia topics and categories.

    This class implements query expansion techniques specific to Wikipedia knowledge
    structures, helping to improve recall by including related topics and categories.
    """

    def __init__(self, tracer: Optional[WikipediaKnowledgeGraphTracer] = None):
        """
        Initialize the query expander.

        Args:
            tracer (WikipediaKnowledgeGraphTracer, optional): Tracer for explanation
        """
        self.tracer = tracer

        # Topic similarity threshold for expansion
        self.similarity_threshold = 0.65

        # Maximum number of expansions
        self.max_expansions = 5

    def expand_query(
        self,
        query_vector: np.ndarray,
        query_text: str,
        vector_store: Any,
        category_hierarchy: WikipediaCategoryHierarchyManager,
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Expand a query with related Wikipedia topics and categories.

        Args:
            query_vector (np.ndarray): The original query vector
            query_text (str): The original query text
            vector_store: Vector store for similarity search
            category_hierarchy: Category hierarchy manager
            trace_id (str, optional): Trace ID for logging

        Returns:
            Dict: Expanded query parameters
        """
        expansions = {
            "topics": [],
            "categories": [],
            "entities": []
        }

        # 1. Find related topics via vector search
        if vector_store and hasattr(vector_store, 'search'):
            try:
                topic_results = vector_store.search(
                    query_vector,
                    top_k=self.max_expansions * 2,  # Get more candidates
                    filter_fn=lambda x: x.get("metadata", {}).get("type") == "topic"
                )

                # Filter by similarity threshold
                similar_topics = [
                    result for result in topic_results
                    if result.get("score", 0) >= self.similarity_threshold
                ]

                # Limit to max_expansions
                similar_topics = similar_topics[:self.max_expansions]

                # Extract topic information
                expansions["topics"] = [
                    {
                        "id": result.get("id", ""),
                        "name": result.get("metadata", {}).get("name", ""),
                        "similarity": result.get("score", 0)
                    }
                    for result in similar_topics
                ]
            except Exception as e:
                # Log error but continue with other expansions
                if self.tracer:
                    self.tracer.log_error(f"Topic expansion error: {str(e)}", trace_id)

        # 2. Find related categories
        # Extract categories from query text using simple keyword matching
        query_tokens = set(query_text.lower().split())
        potential_categories = []

        for category in category_hierarchy.category_connections.keys():
            # Normalize category name for matching
            category_name = category.lower().replace('_', ' ')
            category_tokens = set(category_name.split())

            # Check overlap with query
            overlap = query_tokens.intersection(category_tokens)
            if overlap and len(overlap) / len(category_tokens) >= 0.5:
                potential_categories.append(category)

        # If direct matches found, add related categories
        all_categories = set(potential_categories)
        for category in potential_categories:
            related = category_hierarchy.get_related_categories(category, max_distance=1)
            for related_cat, distance in related:
                all_categories.add(related_cat)

        # Sort categories by depth (more specific first)
        sorted_categories = sorted(
            all_categories,
            key=lambda cat: category_hierarchy.calculate_category_depth(cat),
            reverse=True
        )

        # Limit to max_expansions
        expansions["categories"] = [
            {"name": category, "depth": category_hierarchy.calculate_category_depth(category)}
            for category in sorted_categories[:self.max_expansions]
        ]

        # 3. Create expanded query parameters
        expanded_query = {
            "original_query_vector": query_vector,
            "original_query_text": query_text,
            "expansions": expansions,
            "has_expansions": bool(expansions["topics"] or expansions["categories"])
        }

        # Log expansion details if tracer is available
        if self.tracer and trace_id:
            self.tracer.log_query_expansion(
                trace_id=trace_id,
                query_text=query_text,
                expansions=expansions
            )

        return expanded_query


class WikipediaPathOptimizer:
    """
    Optimizes graph traversal paths for Wikipedia-derived knowledge graphs.

    This class implements path optimization strategies specific to Wikipedia
    knowledge structures, leveraging the hierarchical nature of categories,
    the importance of different entity types, and relationship semantics.
    """

    def __init__(self):
        """Initialize the path optimizer."""
        # Initialize relationship weight calculator
        self.relationship_calculator = WikipediaRelationshipWeightCalculator()

        # Edge traversal cost factors
        self.traversal_costs = {
            # Hierarchical relationships (efficient to traverse)
            "subclass_of": 0.6,
            "instance_of": 0.6,
            "part_of": 0.7,
            "has_part": 0.7,

            # Category relationships (efficient to traverse)
            "category_contains": 0.7,
            "in_category": 0.7,

            # Topic relationships (moderate cost)
            "related_to": 1.0,
            "similar_to": 1.0,
            "refers_to": 1.1,

            # Authorship and creation relationships (higher cost)
            "created_by": 1.2,
            "authored_by": 1.2,
            "developed_by": 1.2,

            # High branching-factor relationships (expensive)
            "mentions": 1.5,
            "mentioned_in": 1.5,

            # Default cost
            "default": 1.0
        }

    def get_edge_traversal_cost(self, edge_type: str) -> float:
        """
        Get traversal cost for an edge type.

        Args:
            edge_type (str): The type of relationship edge

        Returns:
            float: Traversal cost factor
        """
        normalized_type = self.relationship_calculator._normalize_relationship_type(edge_type)
        return self.traversal_costs.get(normalized_type, self.traversal_costs["default"])

    def optimize_traversal_path(
        self,
        start_entities: List[Dict[str, Any]],
        relationship_types: List[str],
        max_depth: int,
        budget: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Optimize a traversal path based on Wikipedia-specific considerations.

        Args:
            start_entities (List[Dict]): Starting entities for traversal
            relationship_types (List[str]): Types of relationships to traverse
            max_depth (int): Maximum traversal depth
            budget (Dict): Resource budget constraints

        Returns:
            Dict: Optimized traversal plan
        """
        # Calculate total budget
        total_budget = budget.get("max_nodes", 1000)

        # 1. Prioritize relationship types
        prioritized_relationships = self.relationship_calculator.get_prioritized_relationship_types(
            relationship_types
        )

        # 2. Calculate traversal costs for each level
        level_costs = []
        remaining_budget = total_budget

        for depth in range(max_depth):
            # For each level, calculate the appropriate budget allocation
            if depth == 0:
                # First level gets more budget since we want a good foundation
                level_budget = min(remaining_budget, int(total_budget * 0.4))
            else:
                # Later levels get progressively less budget
                decay_factor = 0.7 ** depth  # Exponential decay
                level_budget = min(remaining_budget, int(total_budget * 0.2 * decay_factor))

            level_costs.append(level_budget)
            remaining_budget -= level_budget

        # 3. Calculate relationship activation thresholds
        # Higher priority relationships are active at all depths
        # Lower priority relationships are only active at lower depths
        relationship_activation = {}
        for i, rel_type in enumerate(prioritized_relationships):
            # Calculate the maximum depth this relationship should be used
            # Higher priority (lower index) = higher max depth
            priority_rank = i / max(1, len(prioritized_relationships) - 1)  # 0.0 to 1.0
            active_depth = max(1, int((1.0 - priority_rank) * max_depth))
            relationship_activation[rel_type] = min(active_depth, max_depth)

        # 4. Create the optimized traversal plan
        optimized_plan = {
            "strategy": "wikipedia_hierarchical",
            "relationship_priority": prioritized_relationships,
            "level_budgets": level_costs,
            "relationship_activation": relationship_activation,
            "traversal_costs": {rel: self.get_edge_traversal_cost(rel) for rel in relationship_types},
            "original_max_depth": max_depth
        }

        return optimized_plan


class WikipediaRAGQueryOptimizer(GraphRAGQueryOptimizer):
    """
    Specialized query optimizer for Wikipedia-derived knowledge graphs.

    This class extends the base GraphRAGQueryOptimizer with optimizations specific
    to Wikipedia knowledge structures, leveraging hierarchical categories, entity
    importance, and Wikipedia-specific relationship semantics.
    """

    def __init__(
        self,
        query_stats=None,
        vector_weight=0.7,
        graph_weight=0.3,
        cache_enabled=True,
        cache_ttl=300.0,
        cache_size_limit=100,
        tracer=None
    ):
        """
        Initialize the Wikipedia RAG Query Optimizer.

        Args:
            query_stats: Query statistics tracker
            vector_weight (float): Weight for vector similarity
            graph_weight (float): Weight for graph structure
            cache_enabled (bool): Whether to enable query caching
            cache_ttl (float): Time-to-live for cached results
            cache_size_limit (int): Maximum number of cached queries
            tracer (WikipediaKnowledgeGraphTracer, optional): Tracer for explanation
        """
        super().__init__(
            query_stats=query_stats,
            vector_weight=vector_weight,
            graph_weight=graph_weight,
            cache_enabled=cache_enabled,
            cache_ttl=cache_ttl,
            cache_size_limit=cache_size_limit
        )

        # Initialize Wikipedia-specific components
        self.relationship_calculator = WikipediaRelationshipWeightCalculator()
        self.category_hierarchy = WikipediaCategoryHierarchyManager()
        self.entity_importance = WikipediaEntityImportanceCalculator()
        self.query_expander = WikipediaQueryExpander(tracer)
        self.path_optimizer = WikipediaPathOptimizer()

        # Tracer for explanation
        self.tracer = tracer

        # Optimization history for learning
        self.optimization_history = []

    def optimize_query(
        self,
        query_vector: np.ndarray,
        max_vector_results: int = 5,
        max_traversal_depth: int = 2,
        edge_types: Optional[List[str]] = None,
        min_similarity: float = 0.5,
        query_text: Optional[str] = None,
        graph_processor=None,
        vector_store=None,
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate an optimized query plan for Wikipedia knowledge graphs.

        Args:
            query_vector (np.ndarray): Query vector
            max_vector_results (int): Maximum number of initial vector similarity matches
            max_traversal_depth (int): Maximum traversal depth
            edge_types (List[str], optional): Types of edges to follow
            min_similarity (float): Minimum similarity score
            query_text (str, optional): Original query text
            graph_processor: Graph processor instance
            vector_store: Vector store instance
            trace_id (str, optional): Trace ID for logging

        Returns:
            Dict: Optimized query parameters
        """
        # Start with parent class optimization
        base_plan = super().optimize_query(
            query_vector,
            max_vector_results,
            max_traversal_depth,
            edge_types,
            min_similarity
        )

        # Get optimized parameters
        optimized_params = base_plan["params"]

        # Ensure edge_types is a list
        if edge_types is None:
            edge_types = ["subclass_of", "instance_of", "part_of", "related_to", "mentions", "category_contains", "similar_to"]

        # 1. Apply query expansion if query text is provided
        expanded_query = None
        if query_text and vector_store:
            expanded_query = self.query_expander.expand_query(
                query_vector=query_vector,
                query_text=query_text,
                vector_store=vector_store,
                category_hierarchy=self.category_hierarchy,
                trace_id=trace_id
            )

        # 2. Prioritize relationship types for traversal
        prioritized_edge_types = self.relationship_calculator.get_prioritized_relationship_types(edge_types)

        # 3. Calculate relationship activation depths
        relationship_depths = {}
        for i, edge_type in enumerate(prioritized_edge_types):
            priority = 1.0 - (i / len(prioritized_edge_types))
            max_depth = int(max_traversal_depth * (0.5 + 0.5 * priority))
            relationship_depths[edge_type] = max(1, max_depth)

        # 4. Get entity importance calculation strategy
        entity_importance_strategy = "hierarchical_and_reference_based"

        # 5. Create optimized Wikipedia-specific traversal plan
        wiki_traversal_plan = {
            "strategy": "wikipedia_hierarchical",
            "edge_types": prioritized_edge_types,
            "relationship_depths": relationship_depths,
            "entity_importance_strategy": entity_importance_strategy,
            "hierarchical_weight": 1.5  # Boost for hierarchical relationships
        }

        # 6. Create final optimized plan
        wiki_optimized_plan = {
            "query": {
                "vector_params": {
                    "top_k": optimized_params["max_vector_results"],
                    "min_score": optimized_params["min_similarity"]
                },
                "traversal": wiki_traversal_plan
            },
            "weights": {
                "vector": self.vector_weight,
                "graph": self.graph_weight,
                "hierarchical_bonus": 0.2  # Extra weight for hierarchical relationships
            },
            "expansions": expanded_query["expansions"] if expanded_query else None
        }

        # 7. Record optimization for learning
        self.optimization_history.append({
            "timestamp": time.time(),
            "input_params": {
                "max_vector_results": max_vector_results,
                "max_traversal_depth": max_traversal_depth,
                "edge_types": edge_types,
                "min_similarity": min_similarity
            },
            "optimized_plan": wiki_optimized_plan,
            "query_expanded": expanded_query is not None
        })

        # 8. Log optimization details if tracer is available
        if self.tracer and trace_id:
            self.tracer.log_optimization(
                trace_id=trace_id,
                original_params={
                    "max_vector_results": max_vector_results,
                    "max_traversal_depth": max_traversal_depth,
                    "edge_types": edge_types,
                    "min_similarity": min_similarity
                },
                optimized_plan=wiki_optimized_plan
            )

        return wiki_optimized_plan

    def calculate_entity_importance(self, entity_id: str, graph_processor) -> float:
        """
        Calculate importance score for an entity in a Wikipedia knowledge graph.

        Args:
            entity_id (str): Entity ID
            graph_processor: Graph processor instance

        Returns:
            float: Entity importance score (0.0-1.0)
        """
        # Get entity data from graph processor
        entity_data = (
            graph_processor.get_entity_info(entity_id)
            if graph_processor and hasattr(graph_processor, 'get_entity_info')
            else {"id": entity_id}
        )

        # Calculate importance score using the specialized calculator
        return self.entity_importance.calculate_entity_importance(entity_data)

    def learn_from_query_results(
        self,
        query_id: str,
        results: List[Dict[str, Any]],
        time_taken: float,
        plan: Dict[str, Any]
    ) -> None:
        """
        Learn from query execution results to improve future optimizations.

        Args:
            query_id (str): ID of the executed query
            results (List[Dict]): Query results
            time_taken (float): Query execution time
            plan (Dict): The query plan used
        """
        # Extract information for learning
        result_count = len(results)
        avg_score = sum(result.get("score", 0) for result in results) / max(1, result_count)

        # Extract plan components
        traversal = plan.get("query", {}).get("traversal", {})
        edge_types = traversal.get("edge_types", [])
        strategy = traversal.get("strategy", "")

        # Analyze edge type effectiveness
        edge_type_counts = defaultdict(int)
        for result in results:
            # Count edge types in the path that led to this result
            path = result.get("path", [])
            for step in path:
                edge = step.get("edge_type", "")
                if edge:
                    edge_type_counts[edge] += 1

        # Calculate edge type effectiveness (normalized by result count)
        edge_effectiveness = {
            edge: count / max(1, result_count)
            for edge, count in edge_type_counts.items()
        }

        # Record learning data
        learning_data = {
            "query_id": query_id,
            "time_taken": time_taken,
            "result_count": result_count,
            "avg_score": avg_score,
            "edge_effectiveness": edge_effectiveness,
            "strategy": strategy
        }

        # Update relationship weights based on effectiveness
        for edge_type, effectiveness in edge_effectiveness.items():
            # Get current weight
            current_weight = self.relationship_calculator.get_relationship_weight(edge_type)

            # Adjust weight based on effectiveness (small adjustment)
            adjustment = 0.05 * (effectiveness - 0.5)  # -0.025 to +0.025
            new_weight = max(0.1, min(2.0, current_weight + adjustment))

            # Update weight
            self.relationship_calculator.weights[edge_type] = new_weight

        # Record query statistics
        super().record_query_time(time_taken)

        # Record query pattern
        pattern = {
            "edge_types": edge_types,
            "max_depth": traversal.get("original_max_depth", 2),
            "strategy": strategy
        }
        super().record_query_pattern(pattern)


class WikipediaGraphRAGQueryRewriter(QueryRewriter):
    """
    Specialized query rewriter for Wikipedia-derived knowledge graphs.

    This class extends the base QueryRewriter with optimizations specific to
    Wikipedia knowledge structures, implementing more effective query rewriting
    strategies tailored to the characteristics of Wikipedia-derived graphs.
    """

    def __init__(self):
        """Initialize the Wikipedia graph query rewriter."""
        super().__init__()

        # Initialize relationship weight calculator
        self.relationship_calculator = WikipediaRelationshipWeightCalculator()

        # Initialize domain-specific rewriting patterns
        self.domain_patterns = {
            "topic_lookup": re.compile(r'(?:about|information|details)\s+(?:on|about)\s+([a-zA-Z0-9\s]+)'),
            "comparison": re.compile(r'(?:compare|comparison|differences?|similarities?)\s+(?:between|of)\s+([a-zA-Z0-9\s]+)\s+(?:and|vs\.?|versus)\s+([a-zA-Z0-9\s]+)'),
            "definition": re.compile(r'(?:what\s+is|define|definition\s+of|meaning\s+of)\s+([a-zA-Z0-9\s]+)'),
            "cause_effect": re.compile(r'(?:causes?|effects?|impact|influence|results?)\s+of\s+([a-zA-Z0-9\s]+)'),
            "list": re.compile(r'(?:list|enumerate|types|kinds|categories|examples)\s+of\s+([a-zA-Z0-9\s]+)')
        }

    def rewrite_query(self, query: Dict[str, Any], graph_info: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Rewrite a query with optimizations for Wikipedia knowledge graphs.

        Args:
            query (Dict): Original query parameters
            graph_info (Dict, optional): Graph structure information

        Returns:
            Dict: Rewritten query with Wikipedia-specific optimizations
        """
        # Start with base class rewriting
        rewritten_query = super().rewrite_query(query, graph_info)

        # Extract query text if present
        query_text = query.get("query_text", "")

        # Apply Wikipedia-specific rewriting strategies
        if query_text:
            # 1. Detect query patterns and apply specialized optimizations
            pattern_match = self._detect_query_pattern(query_text)
            if pattern_match:
                pattern_type, entities = pattern_match
                rewritten_query = self._apply_pattern_optimization(rewritten_query, pattern_type, entities)

        # 2. Prioritize edge types for Wikipedia
        if "traversal" in rewritten_query and "edge_types" in rewritten_query["traversal"]:
            edge_types = rewritten_query["traversal"]["edge_types"]
            rewritten_query["traversal"]["edge_types"] = self.relationship_calculator.get_prioritized_relationship_types(edge_types)

            # Add hierarchical weight for Wikipedia graphs
            rewritten_query["traversal"]["hierarchical_weight"] = 1.5

        # 3. Apply category-based filtering
        if "category_filter" in query:
            if "vector_params" not in rewritten_query:
                rewritten_query["vector_params"] = {}

            rewritten_query["vector_params"]["categories"] = query["category_filter"]

        # 4. Apply topic expansion if requested
        if query.get("expand_topics", False):
            if "traversal" not in rewritten_query:
                rewritten_query["traversal"] = {}

            rewritten_query["traversal"]["expand_topics"] = True
            rewritten_query["traversal"]["topic_expansion_factor"] = query.get("topic_expansion_factor", 1.0)

        return rewritten_query

    def _detect_query_pattern(self, query_text: str) -> Optional[Tuple[str, List[str]]]:
        """
        Detect Wikipedia-specific query patterns from text.

        Args:
            query_text (str): The query text

        Returns:
            Optional[Tuple[str, List[str]]]: (pattern_type, entities) or None
        """
        for pattern_name, pattern in self.domain_patterns.items():
            match = pattern.search(query_text.lower())
            if match:
                if pattern_name == "comparison":
                    entities = [match.group(1).strip(), match.group(2).strip()]
                else:
                    entities = [match.group(1).strip()]
                return pattern_name, entities

        return None

    def _apply_pattern_optimization(
        self,
        query: Dict[str, Any],
        pattern_type: str,
        entities: List[str]
    ) -> Dict[str, Any]:
        """
        Apply pattern-specific optimizations for Wikipedia queries.

        Args:
            query (Dict): Query to optimize
            pattern_type (str): Detected pattern type
            entities (List[str]): Extracted entities

        Returns:
            Dict: Optimized query
        """
        # Ensure traversal section exists
        if "traversal" not in query:
            query["traversal"] = {}

        # Apply optimizations based on pattern type
        if pattern_type == "topic_lookup":
            # Focus on deep exploration of a specific topic
            query["traversal"]["strategy"] = "topic_focused"
            query["traversal"]["target_entities"] = entities
            query["traversal"]["prioritize_relationships"] = True

        elif pattern_type == "comparison":
            # Set up comparison between entities
            query["traversal"]["strategy"] = "comparison"
            query["traversal"]["comparison_entities"] = entities
            query["traversal"]["find_common_categories"] = True
            query["traversal"]["find_relationships_between"] = True

        elif pattern_type == "definition":
            # Focus on definition relationships
            query["traversal"]["strategy"] = "definition"
            query["traversal"]["prioritize_edge_types"] = ["instance_of", "subclass_of", "defined_as"]

        elif pattern_type == "cause_effect":
            # Focus on causal relationships
            query["traversal"]["strategy"] = "causal"
            query["traversal"]["prioritize_edge_types"] = ["causes", "caused_by", "affects", "affected_by"]

        elif pattern_type == "list":
            # Focus on collecting instances or examples
            query["traversal"]["strategy"] = "collection"
            query["traversal"]["prioritize_edge_types"] = ["instance_of", "subclass_of", "example_of", "has_example"]
            query["traversal"]["collection_target"] = entities[0]

        return query


class WikipediaGraphRAGBudgetManager(QueryBudgetManager):
    """
    Specialized budget manager for Wikipedia-derived knowledge graphs.

    This class extends the base QueryBudgetManager with Wikipedia-specific
    budget allocation strategies that consider the unique characteristics
    of Wikipedia knowledge structures, particularly their hierarchical nature
    and entity relationships.
    """

    def __init__(self):
        """Initialize the Wikipedia-specific budget manager."""
        super().__init__()

        # Wikipedia-specific default budget extensions
        self.wikipedia_budget_extensions = {
            "category_traversal_ms": 5000,  # Allocated time for category traversal
            "topic_expansion_ms": 3000,     # Allocated time for topic expansion
            "max_categories": 20,           # Maximum number of categories to explore
            "max_topics": 15                # Maximum number of topics to explore
        }

        # Update default budget with Wikipedia extensions
        self.default_budget.update(self.wikipedia_budget_extensions)

    def allocate_budget(self, query: Dict[str, Any], priority: str = "normal") -> Dict[str, Any]:
        """
        Allocate resources based on query complexity and Wikipedia-specific factors.

        Args:
            query (Dict): Query parameters
            priority (str): Priority level ("low", "normal", "high")

        Returns:
            Dict: Allocated budget
        """
        # Start with base allocation
        budget = super().allocate_budget(query, priority)

        # Extract Wikipedia-specific query aspects
        traversal = query.get("traversal", {})
        strategy = traversal.get("strategy", "")
        edge_types = traversal.get("edge_types", [])

        # Category-focused budget adjustments
        if any(edge in ["category_contains", "in_category"] for edge in edge_types):
            # Increase category-specific budget
            category_focus = 1.5  # Multiplier for category operations
            budget["category_traversal_ms"] = int(self.default_budget["category_traversal_ms"] * category_focus)
            budget["max_categories"] = int(self.default_budget["max_categories"] * category_focus)

        # Topic expansion budget adjustments
        if traversal.get("expand_topics", False):
            expansion_factor = traversal.get("topic_expansion_factor", 1.0)
            budget["topic_expansion_ms"] = int(self.default_budget["topic_expansion_ms"] * expansion_factor)
            budget["max_topics"] = int(self.default_budget["max_topics"] * expansion_factor)

        # Strategy-specific budget adjustments
        if strategy == "wikipedia_hierarchical":
            # Hierarchical strategy needs more graph traversal resources
            budget["graph_traversal_ms"] = int(budget["graph_traversal_ms"] * 1.3)
            budget["max_nodes"] = int(budget["max_nodes"] * 1.3)
        elif strategy == "topic_focused":
            # Topic-focused needs more vector search resources
            budget["vector_search_ms"] = int(budget["vector_search_ms"] * 1.4)
        elif strategy == "comparison":
            # Comparison needs balanced resources
            budget["vector_search_ms"] = int(budget["vector_search_ms"] * 1.2)
            budget["graph_traversal_ms"] = int(budget["graph_traversal_ms"] * 1.2)

        return budget

    def suggest_early_stopping(self, results: List[Dict[str, Any]], budget_consumed_ratio: float) -> bool:
        """
        Provide Wikipedia-specific early stopping suggestions.

        Args:
            results (List[Dict]): Current results
            budget_consumed_ratio (float): Portion of budget consumed

        Returns:
            bool: Whether to stop early
        """
        # Basic early stopping from parent class
        base_suggestion = super().suggest_early_stopping(results, budget_consumed_ratio)

        # Wikipedia-specific stopping rules
        if len(results) > 0:
            # Check if we have high-confidence category matches
            category_matches = [
                r for r in results
                if r.get("metadata", {}).get("type") == "category" and r.get("score", 0) > 0.85
            ]

            # If we have good category matches, we can stop early to save resources
            if len(category_matches) >= 3 and budget_consumed_ratio > 0.6:
                return True

            # Check for diminishing returns in category hierarchy
            # If we're seeing many similar categories, we can stop
            if len(results) > 10:
                categories = [r.get("metadata", {}).get("category") for r in results]
                unique_categories = set(cat for cat in categories if cat)
                if len(unique_categories) < len(categories) * 0.3 and budget_consumed_ratio > 0.7:
                    return True

        return base_suggestion


class UnifiedWikipediaGraphRAGQueryOptimizer(UnifiedGraphRAGQueryOptimizer):
    """
    Unified optimizer for Wikipedia-derived knowledge graphs.

    This class integrates all Wikipedia-specific optimization components
    (optimizer, rewriter, budget manager) into a single unified optimizer
    that can be used as a drop-in replacement for the base unified optimizer.
    """

    def __init__(
        self,
        rewriter=None,
        budget_manager=None,
        base_optimizer=None,
        graph_info=None,
        metrics_collector=None,
        tracer=None
    ):
        """
        Initialize the unified Wikipedia graph optimizer.

        Args:
            rewriter: Query rewriter component
            budget_manager: Budget manager component
            base_optimizer: Base optimization component
            graph_info (Dict, optional): Graph structure information
            metrics_collector: Performance metrics collector
            tracer: Tracer for explanation
        """
        # Initialize Wikipedia-specific components if not provided
        if rewriter is None:
            rewriter = WikipediaGraphRAGQueryRewriter()

        if budget_manager is None:
            budget_manager = WikipediaGraphRAGBudgetManager()

        if base_optimizer is None:
            base_optimizer = WikipediaRAGQueryOptimizer(tracer=tracer)

        if graph_info is None:
            graph_info = {"graph_type": "wikipedia"}

        # Initialize parent class
        super().__init__(
            rewriter=rewriter,
            budget_manager=budget_manager,
            base_optimizer=base_optimizer,
            graph_info=graph_info,
            metrics_collector=metrics_collector,
            visualizer=None
        )

        # Set tracer
        self.tracer = tracer

    def optimize_query(
        self,
        query: Dict[str, Any],
        graph_processor=None,
        vector_store=None,
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Optimize a query for Wikipedia knowledge graphs.

        Args:
            query (Dict): Query parameters
            graph_processor: Graph processor instance
            vector_store: Vector store instance
            trace_id (str, optional): Trace ID for logging

        Returns:
            Dict: Optimized query plan
        """
        # Extract query parameters
        query_vector = query.get("query_vector")
        if query_vector is None:
            raise ValueError("Query vector is required for optimization")

        query_text = query.get("query_text", "")
        max_vector_results = query.get("max_vector_results", 5)
        max_traversal_depth = query.get("max_traversal_depth", 2)
        edge_types = query.get("edge_types")
        min_similarity = query.get("min_similarity", 0.5)

        # 1. Start with Wikipedia-specific base optimization
        if isinstance(self.base_optimizer, WikipediaRAGQueryOptimizer):
            optimized_plan = self.base_optimizer.optimize_query(
                query_vector=query_vector,
                max_vector_results=max_vector_results,
                max_traversal_depth=max_traversal_depth,
                edge_types=edge_types,
                min_similarity=min_similarity,
                query_text=query_text,
                graph_processor=graph_processor,
                vector_store=vector_store,
                trace_id=trace_id
            )
        else:
            # Fall back to standard optimization if not using Wikipedia optimizer
            optimized_plan = self.base_optimizer.optimize_query(
                query_vector=query_vector,
                max_vector_results=max_vector_results,
                max_traversal_depth=max_traversal_depth,
                edge_types=edge_types,
                min_similarity=min_similarity
            )

        # 2. Apply query rewriting
        rewritten_query = self.rewriter.rewrite_query(
            query=optimized_plan["query"],
            graph_info=self.graph_info
        )
        optimized_plan["query"] = rewritten_query

        # 3. Allocate budget
        budget = self.budget_manager.allocate_budget(
            query=rewritten_query,
            priority=query.get("priority", "normal")
        )
        optimized_plan["budget"] = budget

        # 4. Begin metrics collection if metrics collector is available
        query_id = None
        if self.metrics_collector:
            query_id = self.metrics_collector.start_query_tracking(
                query_params=query,
                query_id=trace_id
            )

            # Record optimization phase
            with self.metrics_collector.time_phase("optimization"):
                # This phase has already completed, just recording it
                pass

            # Store query ID for later reference
            self.last_query_id = query_id
            optimized_plan["query_id"] = query_id

        # 5. Log optimization details if tracer is available
        if self.tracer and trace_id:
            self.tracer.log_unified_optimization(
                trace_id=trace_id,
                original_query=query,
                optimized_plan=optimized_plan
            )

        return optimized_plan


# Utility functions for working with Wikipedia knowledge graphs

def detect_graph_type(graph_processor) -> str:
    """
    Detect if a graph is Wikipedia-derived based on entity/relationship patterns.

    Args:
        graph_processor: Graph processor to analyze

    Returns:
        str: "wikipedia" if Wikipedia-derived, "ipld" if IPLD graph, or "unknown"
    """
    # Check if graph processor has type information
    if hasattr(graph_processor, 'graph_type'):
        return graph_processor.graph_type

    # Check entity and relationship types as indicators
    wiki_indicators = 0
    ipld_indicators = 0

    # Try to get a sample of entities
    sample_entities = []
    try:
        if hasattr(graph_processor, 'get_entities'):
            sample_entities = graph_processor.get_entities(limit=20)
        elif hasattr(graph_processor, 'list_entities'):
            sample_entities = graph_processor.list_entities(limit=20)
    except Exception:
        pass

    # Analyze entity types
    for entity in sample_entities:
        entity_type = entity.get('type', '')

        # Wikipedia indicators
        if any(t in entity_type.lower() for t in ['category', 'article', 'wikidata', 'topic']):
            wiki_indicators += 1

        # IPLD indicators
        if any(t in entity_type.lower() for t in ['ipld', 'cid', 'dag', 'content_addressed']):
            ipld_indicators += 1

    # Check for relationship types
    relationship_types = set()
    try:
        if hasattr(graph_processor, 'get_relationship_types'):
            relationship_types = set(graph_processor.get_relationship_types())
        elif hasattr(graph_processor, 'list_relationship_types'):
            relationship_types = set(graph_processor.list_relationship_types())
    except Exception:
        pass

    # Wikipedia relationship indicators
    wiki_rel_indicators = ['subclass_of', 'instance_of', 'category_contains', 'article_in_category']
    for rel in wiki_rel_indicators:
        if any(rel.lower() in r.lower() for r in relationship_types):
            wiki_indicators += 1

    # IPLD relationship indicators
    ipld_rel_indicators = ['links_to', 'references', 'contains_hash', 'content_references']
    for rel in ipld_rel_indicators:
        if any(rel.lower() in r.lower() for r in relationship_types):
            ipld_indicators += 1

    # Determine type based on indicators
    if wiki_indicators > ipld_indicators:
        return "wikipedia"
    elif ipld_indicators > wiki_indicators:
        return "ipld"
    else:
        return "unknown"


def create_appropriate_optimizer(
    graph_processor=None,
    graph_type: Optional[str] = None,
    metrics_collector: Optional[QueryMetricsCollector] = None,
    tracer: Optional[WikipediaKnowledgeGraphTracer] = None
) -> UnifiedGraphRAGQueryOptimizer:
    """
    Create an appropriate optimizer based on the detected graph type.

    Args:
        graph_processor: Graph processor instance
        graph_type (str, optional): Explicitly specified graph type
        metrics_collector: Performance metrics collector
        tracer: Tracer for explanation

    Returns:
        UnifiedGraphRAGQueryOptimizer: Appropriate optimizer instance
    """
    # Detect graph type if not specified
    if graph_type is None and graph_processor is not None:
        graph_type = detect_graph_type(graph_processor)

    # Default to unknown if still not determined
    if graph_type is None:
        graph_type = "unknown"

    # Create appropriate optimizer
    if graph_type.lower() == "wikipedia":
        return UnifiedWikipediaGraphRAGQueryOptimizer(
            metrics_collector=metrics_collector,
            tracer=tracer
        )
    else:
        # Default to standard optimizer for other graph types
        return UnifiedGraphRAGQueryOptimizer(
            metrics_collector=metrics_collector
        )


# Main integration function
def optimize_wikipedia_query(
    query: Dict[str, Any],
    graph_processor=None,
    vector_store=None,
    tracer: Optional[WikipediaKnowledgeGraphTracer] = None,
    metrics_collector: Optional[QueryMetricsCollector] = None,
    trace_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Optimize a query for Wikipedia-derived knowledge graphs.

    This is the main entry point for using the Wikipedia-specific optimizations.

    Args:
        query (Dict): Query parameters
        graph_processor: Graph processor instance
        vector_store: Vector store instance
        tracer: Tracer for explanation
        metrics_collector: Performance metrics collector
        trace_id (str, optional): Trace ID for logging

    Returns:
        Dict: Optimized query plan
    """
    # Create appropriate optimizer
    optimizer = create_appropriate_optimizer(
        graph_processor=graph_processor,
        graph_type="wikipedia",
        metrics_collector=metrics_collector,
        tracer=tracer
    )

    # Optimize query
    optimized_plan = optimizer.optimize_query(
        query=query,
        graph_processor=graph_processor,
        vector_store=vector_store,
        trace_id=trace_id
    )

    return optimized_plan
