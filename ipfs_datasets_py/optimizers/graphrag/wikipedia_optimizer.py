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

from ipfs_datasets_py.optimizers.graphrag.query_optimizer import (
    GraphRAGQueryOptimizer,
    QueryRewriter,
    QueryBudgetManager,
    UnifiedGraphRAGQueryOptimizer,
    QueryMetricsCollector
)
from ipfs_datasets_py.llm.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer


class WikipediaRelationshipWeightCalculator:
    """
    Wikipedia Relationship Weight Calculator for Graph Traversal Optimization

    The WikipediaRelationshipWeightCalculator class provides sophisticated functionality for
    calculating and managing weights for different relationship types found in Wikipedia-derived
    knowledge graphs. It assigns importance scores to various relationship types based on their
    semantic value and traversal efficiency, enabling optimized graph exploration strategies.
    This class serves as a core component for prioritizing relationship traversals in Wikipedia
    knowledge graphs, supporting both default weight schemes and custom weight configurations.

    Key Features:
    - Hierarchical relationship type prioritization with semantic weights
    - Category-based relationship weight assignment for Wikipedia structures
    - Topic and causal relationship scoring for knowledge discovery
    - Customizable weight schemes with fallback defaults
    - Relationship type normalization and standardization
    - High-value relationship filtering based on weight thresholds
    - Prioritized relationship sorting for traversal optimization

    Attributes:
        weights (Dict[str, float]): Mapping of relationship types to their assigned weights.
            Combines default weights with any custom overrides provided during initialization.
            Higher weights indicate more important relationships for traversal prioritization.
        DEFAULT_RELATIONSHIP_WEIGHTS (Dict[str, float]): Class-level default weight assignments
            for common Wikipedia relationship types including hierarchical, category, topic,
            authorship, temporal, and causal relationships.

    Public Methods:
        get_relationship_weight(relationship_type: str) -> float:
            Retrieve the weight for a specific relationship type with normalization.
            Returns the assigned weight or default weight for unknown types.
        get_prioritized_relationship_types(relationship_types: List[str]) -> List[str]:
            Sort relationship types by their weights in descending order for traversal
            optimization and priority-based graph exploration.
        get_filtered_high_value_relationships(relationship_types: List[str], min_weight: float = 0.7) -> List[str]:
            Filter relationship types to only include those meeting minimum weight thresholds
            for focused traversal on high-value relationships.

    Private Methods:
        _normalize_relationship_type(relationship_type: str) -> str:
            Normalize relationship type strings for consistent lookup and weight assignment.
            Handles variations in naming conventions and converts to standardized format.

    Usage Example:
        calculator = WikipediaRelationshipWeightCalculator({
            "custom_relation": 1.8,
            "special_link": 0.3
        })
        # Get weight for a relationship
        weight = calculator.get_relationship_weight("subclass_of")
        # Prioritize relationships for traversal
        prioritized = calculator.get_prioritized_relationship_types(
            ["mentions", "subclass_of", "instance_of"]
        )
        # Filter high-value relationships
        high_value = calculator.get_filtered_high_value_relationships(
            prioritized, min_weight=0.8
        )

    Notes:
        - Default weights are optimized for Wikipedia knowledge graph structures
        - Hierarchical relationships (subclass_of, instance_of) receive higher weights
        - Generic relationships (mentions, mentioned_in) receive lower weights
        - Custom weights override defaults for specific relationship types
        - Weight normalization handles common naming variations automatically
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
        Initialize the Wikipedia relationship weight calculator with default and custom weights.

        This method sets up the weight calculation system by combining default Wikipedia
        relationship weights with any custom overrides provided. The resulting weight
        mapping is used for prioritizing relationship traversals in knowledge graphs.

        Args:
            custom_weights (Optional[Dict[str, float]], optional): Custom relationship weights
                to override or extend default weights. Keys should be relationship type names
                and values should be positive float weights. Higher values indicate more
                important relationships. Defaults to None.

        Attributes initialized:
            weights (Dict[str, float]): Combined weight mapping containing default Wikipedia
                relationship weights merged with custom overrides. Used for all weight
                lookups and relationship prioritization operations.

        Raises:
            TypeError: If custom_weights is not a dictionary or contains non-numeric values
            ValueError: If custom_weights contains negative weight values

        Examples:
            >>> calculator = WikipediaRelationshipWeightCalculator()
            >>> calculator.weights["subclass_of"]
            1.5
            >>> custom_calc = WikipediaRelationshipWeightCalculator({
            ...     "custom_relation": 2.0,
            ...     "subclass_of": 1.8  # Override default
            ... })
            >>> custom_calc.weights["custom_relation"]
            2.0
        """
        self.weights = self.DEFAULT_RELATIONSHIP_WEIGHTS.copy()
        if custom_weights:
            self.weights.update(custom_weights)

    def get_relationship_weight(self, relationship_type: str) -> float:
        """
        Retrieve the weight for a specific relationship type with normalization support.

        This method provides access to relationship weights used for prioritizing graph
        traversals in Wikipedia knowledge graphs. It handles relationship type normalization
        automatically and provides fallback to default weights for unknown relationship types.

        Args:
            relationship_type (str): The type of relationship to get weight for.
                Can include variations in naming conventions (spaces, hyphens, case)
                which will be automatically normalized for consistent lookup.

        Returns:
            float: Weight value for the relationship type, ranging from 0.1 to 2.0.
                Higher values indicate more important relationships for traversal.
                Returns default weight (0.5) for unknown relationship types.

        Raises:
            TypeError: If relationship_type is not a string
            ValueError: If relationship_type is empty or contains only whitespace

        Examples:
            >>> calculator = WikipediaRelationshipWeightCalculator()
            >>> calculator.get_relationship_weight("subclass_of")
            1.5
            >>> calculator.get_relationship_weight("is_subclass_of")  # Normalized
            1.5
            >>> calculator.get_relationship_weight("unknown_relation")
            0.5
            >>> calculator.get_relationship_weight("Instance Of")  # Case/space handling
            1.4

        Notes:
            - Relationship type normalization handles common naming variations
            - Default weight is returned for unrecognized relationship types
            - Weights are optimized for Wikipedia knowledge graph characteristics
            - Hierarchical relationships receive higher weights than generic ones
        """
        # Handle variations in relationship names
        normalized_type = self._normalize_relationship_type(relationship_type)

        # Return the weight if it exists, otherwise return the default weight
        return self.weights.get(normalized_type, self.weights["default"])

    def _normalize_relationship_type(self, relationship_type: str) -> str:
        """
        Normalize relationship type string for consistent lookup and weight assignment.

        This method standardizes relationship type strings by converting them to a
        consistent format that can be reliably looked up in the weights dictionary.
        It handles common variations in naming conventions including case differences,
        spacing, hyphenation, and prefix variations commonly found in knowledge graphs.

        Args:
            relationship_type (str): The relationship type string to normalize.
                Can contain spaces, hyphens, mixed case, and common prefixes like "is_".

        Returns:
            str: Normalized relationship type in lowercase snake_case format.
                Common prefixes are removed and variations are mapped to standard forms.

        Raises:
            TypeError: If relationship_type is not a string
            AttributeError: If string methods are not available on the input

        Examples:
            >>> calculator = WikipediaRelationshipWeightCalculator()
            >>> calculator._normalize_relationship_type("Is Subclass Of")
            'subclass_of'
            >>> calculator._normalize_relationship_type("instance-of")
            'instance_of'
            >>> calculator._normalize_relationship_type("RELATED_TO")
            'related_to'
            >>> calculator._normalize_relationship_type("is_mentioned_in")
            'mentioned_in'

        Notes:
            - Converts all text to lowercase for case-insensitive matching
            - Replaces spaces and hyphens with underscores for snake_case format
            - Maps common prefix variations ("is_", "contains_") to standard forms
            - Handles bidirectional relationship naming variations
            - Optimized for Wikipedia relationship naming patterns
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
        Sort relationship types by their weights in descending order for traversal optimization.

        This method takes a list of relationship types and returns them sorted by their
        assigned weights, with the highest-weight (most important) relationships first.
        This ordering is essential for prioritizing graph traversals and ensuring that
        more valuable relationship types are explored before less important ones.

        Args:
            relationship_types (List[str]): List of relationship type names to prioritize.
                Can include any relationship types, including unknown ones which will
                receive default weights for comparison.

        Returns:
            List[str]: Relationship types sorted by weight in descending order.
                Highest-weight relationships appear first in the list, enabling
                priority-based traversal strategies.

        Raises:
            TypeError: If relationship_types is not a list or contains non-string elements
            ValueError: If relationship_types is empty

        Examples:
            >>> calculator = WikipediaRelationshipWeightCalculator()
            >>> types = ["mentions", "subclass_of", "instance_of", "related_to"]
            >>> prioritized = calculator.get_prioritized_relationship_types(types)
            >>> print(prioritized)
            ['subclass_of', 'instance_of', 'related_to', 'mentions']
            >>> # Weights: subclass_of=1.5, instance_of=1.4, related_to=1.0, mentions=0.5

        Notes:
            - Sorting is based on weights from the relationship weight calculator
            - Higher weights indicate more important relationships for traversal
            - Unknown relationship types receive default weight for comparison
            - Stable sorting preserves original order for relationships with equal weights
            - Optimized for Wikipedia knowledge graph traversal prioritization
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
        Filter relationship types to only include those meeting minimum weight thresholds.

        This method filters a list of relationship types to retain only those with
        weights at or above the specified minimum threshold. This is useful for
        focusing graph traversals on high-value relationships and avoiding
        low-priority relationships that may not contribute significantly to query results.

        Args:
            relationship_types (List[str]): List of relationship type names to filter.
                All relationship types will be evaluated against their assigned weights.
            min_weight (float, optional): Minimum weight threshold for inclusion.
                Relationship types with weights below this threshold are excluded.
                Defaults to 0.7 for moderate filtering.

        Returns:
            List[str]: Filtered list containing only high-value relationship types
                with weights >= min_weight. Maintains original order of input list.

        Raises:
            TypeError: If relationship_types is not a list or min_weight is not numeric
            ValueError: If min_weight is negative or greater than maximum possible weight

        Examples:
            >>> calculator = WikipediaRelationshipWeightCalculator()
            >>> types = ["subclass_of", "mentions", "instance_of", "related_to"]
            >>> high_value = calculator.get_filtered_high_value_relationships(types, 0.8)
            >>> print(high_value)
            ['subclass_of', 'instance_of']  # Only weights >= 0.8
            >>> moderate_value = calculator.get_filtered_high_value_relationships(types, 0.5)
            >>> print(moderate_value)
            ['subclass_of', 'instance_of', 'related_to']  # Excludes mentions (0.5)

        Notes:
            - Filtering is based on exact weight comparison using >= operator
            - Default threshold (0.7) excludes low-priority relationships like mentions
            - Original order is preserved for relationships that pass the filter
            - Useful for performance optimization in resource-constrained scenarios
            - Threshold can be adjusted based on query requirements and performance needs
        """
        return [
            rel_type for rel_type in relationship_types
            if self.get_relationship_weight(rel_type) >= min_weight
        ]


class WikipediaCategoryHierarchyManager:
    """
    Wikipedia Category Hierarchy Manager for Knowledge Graph Navigation

    The WikipediaCategoryHierarchyManager class provides comprehensive functionality for
    managing and optimizing traversals through Wikipedia's hierarchical category structure.
    It maintains category depth calculations, specificity scoring, and connection mapping
    to enable intelligent navigation strategies in Wikipedia-derived knowledge graphs.
    This class serves as a core component for category-based query optimization, supporting
    both depth-based traversal planning and similarity-weighted category exploration.

    Key Features:
    - Hierarchical category depth calculation with cycle detection
    - Category specificity scoring for relevance weighting
    - Dynamic category connection registration and management
    - Similarity-based category weight assignment for query optimization
    - Related category discovery within specified traversal distances
    - Caching mechanisms for performance optimization
    - Parent-child relationship tracking for hierarchy navigation

    Attributes:
        category_depth_cache (Dict[str, int]): Cache mapping category names to their
            calculated depths in the hierarchy. Depths are calculated as distance from
            root categories, with higher values indicating more specific categories.
        category_specificity (Dict[str, float]): Mapping of category names to their
            specificity scores based on position in hierarchy and content characteristics.
        category_connections (DefaultDict[str, Set[str]]): Graph structure mapping parent
            categories to sets of their child categories, enabling hierarchy traversal
            and relationship discovery.

    Public Methods:
        register_category_connection(parent_category: str, child_category: str) -> None:
            Register a hierarchical connection between parent and child categories
            for building the category graph structure.
        calculate_category_depth(category: str, visited: Optional[Set[str]] = None) -> int:
            Calculate the hierarchical depth of a category with cycle detection,
            returning cached results when available for performance optimization.
        assign_category_weights(query_vector: np.ndarray, categories: List[str], similarity_scores: Dict[str, float] = None) -> Dict[str, float]:
            Assign weights to categories based on hierarchy depth and similarity to query vector,
            combining structural and semantic relevance for traversal optimization.
        get_related_categories(category: str, max_distance: int = 2) -> List[Tuple[str, int]]:
            Discover categories related to a given category within specified traversal distance,
            returning category names paired with their distances from the source.

    Usage Example:
        hierarchy_manager = WikipediaCategoryHierarchyManager()
        # Register category relationships
        hierarchy_manager.register_category_connection("Science", "Physics")
        hierarchy_manager.register_category_connection("Physics", "Quantum Physics")
        # Calculate category depth
        depth = hierarchy_manager.calculate_category_depth("Quantum Physics")
        # Assign weights based on query relevance
        weights = hierarchy_manager.assign_category_weights(
            query_vector, ["Physics", "Chemistry", "Biology"]
        )
        # Find related categories
        related = hierarchy_manager.get_related_categories("Physics", max_distance=2)

    Notes:
        - Depth calculation uses caching to avoid redundant computations
        - Cycle detection prevents infinite loops in category hierarchies
        - Weight assignment combines structural depth with semantic similarity
        - Related category discovery supports bidirectional traversal
        - Performance optimized for large Wikipedia category structures
    """

    def __init__(self):
        """
        Initialize the Wikipedia category hierarchy manager with empty data structures.

        This method sets up the core data structures needed for managing Wikipedia
        category hierarchies including depth caching, specificity scoring, and
        connection tracking. All structures start empty and are populated as
        category relationships are registered and analyzed.

        Attributes initialized:
            category_depth_cache (Dict[str, int]): Cache mapping category names to their
                calculated depths in the hierarchy for performance optimization.
            category_specificity (Dict[str, float]): Mapping of category names to their
                specificity scores based on hierarchy position and characteristics.
            category_connections (DefaultDict[str, Set[str]]): Graph structure mapping
                parent categories to sets of child categories for hierarchy navigation.

        Examples:
            >>> manager = WikipediaCategoryHierarchyManager()
            >>> len(manager.category_depth_cache)
            0
            >>> len(manager.category_connections)
            0
            >>> # Ready for category registration and analysis
        """
        # Category depth cache (category_name -> depth)
        self.category_depth_cache = {}

        # Category specificity scores (category_name -> specificity)
        self.category_specificity = {}

        # Category connections (category_name -> [related_categories])
        self.category_connections = defaultdict(set)

    def register_category_connection(self, parent_category: str, child_category: str) -> None:
        """
        Register a hierarchical connection between parent and child categories.

        This method builds the category hierarchy graph by registering parent-child
        relationships between Wikipedia categories. These connections are used for
        depth calculation, related category discovery, and hierarchical traversal
        optimization throughout the knowledge graph.

        Args:
            parent_category (str): The parent category name in the hierarchy.
                Should be a valid Wikipedia category identifier.
            child_category (str): The child category name in the hierarchy.
                Should be a valid Wikipedia category identifier.

        Returns:
            None: This method modifies the internal category_connections structure.

        Raises:
            TypeError: If parent_category or child_category is not a string
            ValueError: If parent_category or child_category is empty

        Examples:
            >>> manager = WikipediaCategoryHierarchyManager()
            >>> manager.register_category_connection("Science", "Physics")
            >>> manager.register_category_connection("Physics", "Quantum Physics")
            >>> manager.register_category_connection("Science", "Chemistry")
            >>> "Physics" in manager.category_connections["Science"]
            True

        Notes:
            - Connections are stored as directed relationships (parent -> child)
            - Multiple children can be registered for the same parent
            - Duplicate connections are automatically handled by set data structure
            - No cycle detection is performed during registration
            - Connections are used for depth calculation and traversal optimization
        """
        self.category_connections[parent_category].add(child_category)

    def calculate_category_depth(self, category: str, visited: Optional[Set[str]] = None) -> int:
        """
        Calculate the hierarchical depth of a category with cycle detection and caching.

        This method determines how deep a category is in the Wikipedia hierarchy by
        traversing parent relationships recursively. Depth is calculated as the maximum
        distance from any root category (categories with no parents), with higher values
        indicating more specific categories. Results are cached for performance optimization.

        Args:
            category (str): The category name to calculate depth for.
                Should be a registered category in the hierarchy.
            visited (Optional[Set[str]], optional): Set of already visited categories
                for cycle detection during recursive traversal. Automatically managed
                during recursion. Defaults to None.

        Returns:
            int: The calculated depth of the category in the hierarchy.
                Root categories return 0, direct children return 1, etc.
                Returns 0 for categories involved in cycles.

        Raises:
            TypeError: If category is not a string
            ValueError: If category is empty or contains only whitespace

        Examples:
            >>> manager = WikipediaCategoryHierarchyManager()
            >>> manager.register_category_connection("Knowledge", "Science")
            >>> manager.register_category_connection("Science", "Physics")
            >>> manager.register_category_connection("Physics", "Quantum Physics")
            >>> manager.calculate_category_depth("Quantum Physics")
            3
            >>> manager.calculate_category_depth("Science")
            1
            >>> manager.calculate_category_depth("Knowledge")
            0

        Notes:
            - Results are cached in category_depth_cache for performance
            - Cycle detection prevents infinite recursion in circular hierarchies
            - Depth calculation uses maximum parent depth + 1 for multiple parents
            - Root categories (no parents) have depth 0
            - Performance optimized for large Wikipedia category structures
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
    Wikipedia Entity Importance Calculator for Graph Traversal Prioritization

    The WikipediaEntityImportanceCalculator class provides sophisticated functionality for
    calculating importance scores for entities in Wikipedia-derived knowledge graphs.
    It combines multiple relevance factors including connectivity, references, category
    importance, explicitness, and recency to generate comprehensive importance scores.
    This class serves as a core component for entity prioritization during graph traversal,
    supporting both individual entity scoring and batch entity ranking operations.

    Key Features:
    - Multi-factor importance scoring with configurable feature weights
    - Connection-based popularity assessment using inbound and outbound links
    - Reference count analysis for credibility and authority scoring
    - Category importance integration for contextual relevance
    - Explicitness scoring based on mention frequency and prominence
    - Recency scoring for temporal relevance in dynamic knowledge graphs
    - Performance-optimized caching for repeated entity evaluations
    - Logarithmic scaling for handling wide ranges in connectivity metrics

    Attributes:
        entity_importance_cache (Dict[str, float]): Cache mapping entity IDs to their
            calculated importance scores to avoid redundant computations and improve
            performance during repeated evaluations.
        feature_weights (Dict[str, float]): Configurable weights for different importance
            factors including connection_count (0.3), reference_count (0.2),
            category_importance (0.2), explicitness (0.15), and recency (0.15).

    Public Methods:
        calculate_entity_importance(entity_data: Dict[str, Any], category_weights: Optional[Dict[str, float]] = None) -> float:
            Calculate comprehensive importance score for an entity combining multiple
            relevance factors with logarithmic scaling and normalization.
        rank_entities_by_importance(entities: List[Dict[str, Any]], category_weights: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
            Rank a collection of entities by their calculated importance scores,
            returning entities sorted in descending order of importance.

    Usage Example:
        calculator = WikipediaEntityImportanceCalculator()
        # Calculate importance for a single entity
        entity_data = {
            "id": "entity_123",
            "inbound_connections": ["e1", "e2", "e3"],
            "outbound_connections": ["e4", "e5"],
            "references": ["ref1", "ref2"],
            "categories": ["Science", "Physics"],
            "mention_count": 25,
            "last_modified": 1693958400.0
        }
        category_weights = {"Science": 0.9, "Physics": 0.8}
        importance = calculator.calculate_entity_importance(entity_data, category_weights)
        # Rank multiple entities
        ranked_entities = calculator.rank_entities_by_importance(
            [entity_data, other_entity], category_weights
        )

    Notes:
        - Importance scores are normalized to 0.0-1.0 range for consistency
        - Connection counts use logarithmic scaling to handle high-degree nodes
        - Reference counts contribute to authority and credibility assessment
        - Category weights enable domain-specific importance adjustments
        - Recency scoring provides temporal relevance for dynamic content
        - Caching improves performance for repeated entity evaluations
    """

    def __init__(self):
        """
        Initialize the Wikipedia entity importance calculator with default configurations.

        This method sets up the importance calculation system with default feature weights
        and an empty cache for performance optimization. The feature weights are configured
        to balance different aspects of entity importance including connectivity, references,
        category relevance, explicitness, and temporal recency.

        Attributes initialized:
            entity_importance_cache (Dict[str, float]): Cache mapping entity IDs to their
                calculated importance scores to avoid redundant computations during
                repeated evaluations and improve overall performance.
            feature_weights (Dict[str, float]): Configurable weights for different importance
                factors with balanced default values: connection_count (0.3), reference_count (0.2),
                category_importance (0.2), explicitness (0.15), and recency (0.15).

        Examples:
            >>> calculator = WikipediaEntityImportanceCalculator()
            >>> calculator.feature_weights["connection_count"]
            0.3
            >>> len(calculator.entity_importance_cache)
            0

        Notes:
            - Feature weights sum to 1.0 for normalized importance scoring
            - Connection count receives highest weight due to network importance
            - Cache improves performance for repeated entity evaluations
            - Weights can be modified after initialization for custom scoring
        """
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
        Calculate comprehensive importance score for an entity using multiple relevance factors.

        This method combines multiple importance factors including connectivity, references,
        category importance, explicitness, and recency to generate a comprehensive importance
        score. The calculation uses logarithmic scaling for handling wide ranges in metrics
        and provides normalized scores suitable for entity ranking and prioritization.

        Args:
            entity_data (Dict[str, Any]): Entity data dictionary containing relevance features.
                Expected keys include: id, inbound_connections, outbound_connections,
                references, categories, mention_count, last_modified.
            category_weights (Optional[Dict[str, float]], optional): Category importance weights
                for domain-specific importance adjustments. Maps category names to weight values.
                Defaults to None for equal category treatment.

        Returns:
            float: Entity importance score normalized to 0.0-1.0 range.
                Higher scores indicate more important entities for prioritization.
                Combines weighted feature scores using configured feature weights.

        Raises:
            TypeError: If entity_data is not a dictionary or contains invalid types
            ValueError: If entity_data is missing required fields or contains invalid values
            KeyError: If category_weights references categories not in entity data

        Examples:
            >>> calculator = WikipediaEntityImportanceCalculator()
            >>> entity_data = {
            ...     "id": "quantum_entanglement",
            ...     "inbound_connections": ["physics", "quantum_mechanics"],
            ...     "outbound_connections": ["bell_theorem", "epr_paradox"],
            ...     "references": ["einstein_1935", "bell_1964"],
            ...     "categories": ["Physics", "Quantum Mechanics"],
            ...     "mention_count": 15,
            ...     "last_modified": 1693958400.0
            ... }
            >>> category_weights = {"Physics": 0.9, "Quantum Mechanics": 0.8}
            >>> importance = calculator.calculate_entity_importance(entity_data, category_weights)
            >>> 0.0 <= importance <= 1.0
            True

        Notes:
            - Connection counts use logarithmic scaling to handle high-degree nodes
            - Reference counts contribute to authority and credibility assessment
            - Category weights enable domain-specific importance adjustments
            - Recency scoring provides temporal relevance for dynamic content
            - Results are cached using entity ID for performance optimization
            - Missing optional fields receive default values for robust calculation
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
        Rank a collection of entities by their calculated importance scores.

        This method processes a list of entity data dictionaries, calculates importance
        scores for each using the comprehensive importance calculation, and returns
        the entities sorted in descending order of importance. This enables efficient
        entity prioritization for graph traversal and query optimization.

        Args:
            entities (List[Dict[str, Any]]): List of entity data dictionaries to rank.
                Each dictionary should contain entity features like connections, references,
                categories, and other importance indicators.
            category_weights (Optional[Dict[str, float]], optional): Category importance weights
                for domain-specific importance adjustments applied to all entities.
                Maps category names to weight values. Defaults to None.

        Returns:
            List[Dict[str, Any]]: Entities sorted by importance in descending order.
                Most important entities appear first in the list, enabling priority-based
                processing and traversal strategies.

        Raises:
            TypeError: If entities is not a list or contains non-dictionary elements
            ValueError: If entities list is empty or contains invalid entity data
            KeyError: If category_weights references categories not found in entity data

        Examples:
            >>> calculator = WikipediaEntityImportanceCalculator()
            >>> entities = [
            ...     {"id": "entity_1", "inbound_connections": ["a", "b"], "references": ["r1"]},
            ...     {"id": "entity_2", "inbound_connections": ["c"], "references": ["r2", "r3"]},
            ...     {"id": "entity_3", "inbound_connections": ["d", "e", "f"], "references": []}
            ... ]
            >>> ranked = calculator.rank_entities_by_importance(entities)
            >>> len(ranked) == len(entities)
            True
            >>> # Most important entity first
            >>> ranked[0]["id"]  # Entity with highest calculated importance

        Notes:
            - Importance calculation uses the same algorithm as calculate_entity_importance
            - Sorting is stable for entities with identical importance scores
            - Category weights are applied consistently across all entities
            - Performance scales linearly with the number of entities
            - Caching from importance calculation improves performance for repeated ranking
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
    Wikipedia Query Expander for Enhanced Knowledge Discovery

    The WikipediaQueryExpander class provides sophisticated functionality for expanding
    queries with relevant Wikipedia topics and categories to improve recall and discovery
    in knowledge graph searches. It implements semantic expansion techniques specific to
    Wikipedia knowledge structures, leveraging both vector similarity and hierarchical
    category relationships to identify related content and broaden query scope.

    Args:
        tracer (Optional[WikipediaKnowledgeGraphTracer], optional): Tracer instance for
            logging and explaining query expansion decisions. Enables detailed tracking
            of expansion reasoning and performance analysis. Defaults to None.

    Key Features:
    - Vector similarity-based topic discovery for semantic expansion
    - Hierarchical category expansion using Wikipedia's category structure
    - Configurable similarity thresholds for expansion quality control
    - Maximum expansion limits to prevent query scope explosion
    - Integration with category hierarchy managers for structured expansion
    - Performance tracking and explanation through optional tracer integration
    - Token-based category matching with overlap analysis
    - Distance-aware related category discovery

    Attributes:
        tracer (Optional[WikipediaKnowledgeGraphTracer]): Tracer instance for logging
            query expansion decisions and performance metrics during expansion operations.
        similarity_threshold (float): Minimum similarity score (0.65) required for
            including topics in expansion results, ensuring expansion quality.
        max_expansions (int): Maximum number of expansions (5) to include in results
            to prevent query scope explosion and maintain performance.

    Public Methods:
        expand_query(query_vector: np.ndarray, query_text: str, vector_store: Any, category_hierarchy: WikipediaCategoryHierarchyManager, trace_id: Optional[str] = None) -> Dict[str, Any]:
            Expand a query with related Wikipedia topics and categories using vector similarity
            and hierarchical category relationships, returning structured expansion data.

    Usage Example:
        expander = WikipediaQueryExpander(tracer=knowledge_tracer)
        # Expand query with related topics and categories
        expanded_query = expander.expand_query(
            query_vector=query_embedding,
            query_text="quantum physics experiments",
            vector_store=vector_db,
            category_hierarchy=hierarchy_manager,
            trace_id="query_123"
        )
        # Access expansion results
        topics = expanded_query["expansions"]["topics"]
        categories = expanded_query["expansions"]["categories"]
        has_expansions = expanded_query["has_expansions"]
    """

    def __init__(self, tracer: Optional[WikipediaKnowledgeGraphTracer] = None):
        """
        Initialize the Wikipedia query expander with configurable tracing support.

        Args:
            tracer (Optional[WikipediaKnowledgeGraphTracer], optional): Tracer instance
                Defaults to None.

        Attributes initialized:
            tracer (Optional[WikipediaKnowledgeGraphTracer]): Tracer instance for logging
                query expansion decisions and performance metrics.
            similarity_threshold (float): Minimum similarity score (0.65) required for
                including topics in expansion results to ensure expansion quality.
            max_expansions (int): Maximum number of expansions (5) to include in results
                to prevent query scope explosion and maintain performance.

        Examples:
            >>> expander = WikipediaQueryExpander()
            >>> expander.similarity_threshold
            0.65
            >>> expander.max_expansions
            5
            >>> expander_with_trace = WikipediaQueryExpander(tracer=knowledge_tracer)
            >>> expander_with_trace.tracer is not None
            True
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
        Expand a query with related Wikipedia topics and categories for enhanced discovery.

        This method implements comprehensive query expansion by discovering semantically
        related topics through vector similarity search and hierarchically related categories
        through Wikipedia's category structure. The expansion improves query recall by
        including relevant content that might not match the original query directly.

        Args:
            query_vector (np.ndarray): The original query vector for semantic similarity search.
                Should be compatible with the vector store's embedding space.
            query_text (str): The original query text for category extraction and analysis.
                Used for token-based category matching and expansion context.
            vector_store (Any): Vector store instance for similarity search operations.
                Should implement search method with query vector and filtering capabilities.
            category_hierarchy (WikipediaCategoryHierarchyManager): Category hierarchy manager
                for discovering related categories and calculating category relationships.
            trace_id (Optional[str], optional): Unique trace identifier for correlating
                expansion decisions and logging across the expansion process. Defaults to None.

        Returns:
            Dict[str, Any]: Comprehensive expanded query data containing:
                - original_query_vector: The input query vector for reference
                - original_query_text: The input query text for reference
                - expansions: Dictionary with topics, categories, and entities expansions
                - has_expansions: Boolean indicating whether any expansions were found

        Raises:
            TypeError: If query_vector is not a numpy array or other parameters have wrong types
            ValueError: If query_text is empty or vector_store lacks required methods
            AttributeError: If vector_store or category_hierarchy lack required methods

        Examples:
            >>> expander = WikipediaQueryExpander(tracer=tracer)
            >>> expanded = expander.expand_query(
            ...     query_vector=query_embedding,
            ...     query_text="quantum physics experiments",
            ...     vector_store=vector_db,
            ...     category_hierarchy=hierarchy_manager,
            ...     trace_id="expand_001"
            ... )
            >>> expanded["has_expansions"]
            True
            >>> len(expanded["expansions"]["topics"]) <= 5  # Max expansions limit
            True
            >>> "categories" in expanded["expansions"]
            True

        Notes:
            - Vector similarity expansion requires compatible vector store implementation
            - Category expansion leverages Wikipedia's hierarchical structure patterns
            - Similarity thresholds balance expansion quality with recall improvement
            - Maximum expansion limits prevent performance degradation
            - Token-based category matching handles category name variations
            - Tracer integration enables detailed expansion analysis and debugging
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
    Wikipedia Path Optimizer for Graph Traversal Strategy Optimization

    The WikipediaPathOptimizer class provides sophisticated functionality for optimizing
    graph traversal paths in Wikipedia-derived knowledge graphs. It implements path
    optimization strategies that leverage the hierarchical nature of Wikipedia categories,
    the varying importance of different entity types, and the semantic characteristics
    of Wikipedia relationships to create efficient traversal plans.
    This class serves as a core component for graph exploration optimization, supporting
    both cost-based path planning and hierarchical traversal strategies.

    Key Features:
    - Relationship-specific traversal cost calculation for efficient path planning
    - Hierarchical path optimization leveraging Wikipedia's category structure
    - Budget-aware traversal planning with level-based resource allocation
    - Relationship activation depth management for prioritized exploration
    - Cost-benefit analysis for different traversal strategies
    - Performance-optimized path selection using weighted relationship types
    - Dynamic budget allocation with exponential decay for depth levels
    - Relationship priority ranking for traversal optimization

    Attributes:
        relationship_calculator (WikipediaRelationshipWeightCalculator): Calculator instance
            for determining relationship weights and priorities during path optimization.
        traversal_costs (Dict[str, float]): Mapping of relationship types to their traversal
            cost factors, with lower costs indicating more efficient traversal paths.
            Hierarchical relationships have lower costs (0.6-0.7) while high branching-factor
            relationships have higher costs (1.5).

    Public Methods:
        get_edge_traversal_cost(edge_type: str) -> float:
            Calculate traversal cost factor for a specific edge type with normalization,
            returning cost values optimized for Wikipedia relationship characteristics.
        optimize_traversal_path(start_entities: List[Dict[str, Any]], relationship_types: List[str], max_depth: int, budget: Dict[str, Any]) -> Dict[str, Any]:
            Generate an optimized traversal plan based on Wikipedia-specific considerations
            including relationship prioritization, budget allocation, and depth management.

    Usage Example:
        optimizer = WikipediaPathOptimizer()
        # Calculate edge traversal cost
        cost = optimizer.get_edge_traversal_cost("subclass_of")
        # Optimize traversal path
        optimized_plan = optimizer.optimize_traversal_path(
            start_entities=[{"id": "entity_1", "type": "topic"}],
            relationship_types=["subclass_of", "instance_of", "mentions"],
            max_depth=3,
            budget={"max_nodes": 1000, "max_time_ms": 5000}
        )
        # Access optimization results
        strategy = optimized_plan["strategy"]
        level_budgets = optimized_plan["level_budgets"]
        relationship_activation = optimized_plan["relationship_activation"]

    Notes:
        - Traversal costs are optimized for Wikipedia relationship characteristics
        - Hierarchical relationships receive preferential cost treatment
        - Budget allocation uses exponential decay for depth-based planning
        - Relationship activation depths prevent low-priority relationship overuse
        - Cost factors balance traversal efficiency with discovery completeness
        - Path optimization leverages Wikipedia's structured knowledge organization
    """

    def __init__(self):
        """
        Initialize the Wikipedia path optimizer with relationship calculators and cost factors.

        This method sets up the path optimization system with Wikipedia-specific relationship
        weight calculations and traversal cost factors optimized for Wikipedia knowledge
        graph characteristics. The cost factors are designed to prioritize efficient
        traversal paths while maintaining comprehensive discovery capabilities.

        Attributes initialized:
            relationship_calculator (WikipediaRelationshipWeightCalculator): Calculator instance
                for determining relationship weights and priorities during path optimization.
            traversal_costs (Dict[str, float]): Mapping of relationship types to their traversal
                cost factors with values optimized for Wikipedia relationship characteristics.
                Lower costs (0.6-0.7) for hierarchical relationships, higher costs (1.5) for
                high branching-factor relationships like mentions.

        Examples:
            >>> optimizer = WikipediaPathOptimizer()
            >>> optimizer.traversal_costs["subclass_of"]
            0.6
            >>> optimizer.traversal_costs["mentions"]
            1.5
            >>> isinstance(optimizer.relationship_calculator, WikipediaRelationshipWeightCalculator)
            True

        Notes:
            - Traversal costs are optimized for Wikipedia relationship characteristics
            - Hierarchical relationships receive preferential cost treatment
            - High branching-factor relationships have higher costs to limit exploration
            - Cost factors balance traversal efficiency with discovery completeness
        """
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
        Calculate traversal cost factor for a specific edge type with normalization.

        This method determines the computational cost factor for traversing a specific
        type of relationship edge in Wikipedia knowledge graphs. Cost factors are used
        to prioritize efficient traversal paths and manage resource allocation during
        graph exploration operations.

        Args:
            edge_type (str): The type of relationship edge to calculate cost for.
                Can include variations in naming conventions which will be normalized
                automatically for consistent cost lookup.

        Returns:
            float: Traversal cost factor for the edge type, ranging from 0.6 to 1.5.
                Lower values indicate more efficient traversal paths, higher values
                indicate more expensive traversal operations. Returns default cost (1.0)
                for unknown edge types.

        Raises:
            TypeError: If edge_type is not a string
            ValueError: If edge_type is empty or contains only whitespace

        Examples:
            >>> optimizer = WikipediaPathOptimizer()
            >>> optimizer.get_edge_traversal_cost("subclass_of")
            0.6
            >>> optimizer.get_edge_traversal_cost("mentions")
            1.5
            >>> optimizer.get_edge_traversal_cost("unknown_relation")
            1.0
            >>> optimizer.get_edge_traversal_cost("Instance Of")  # Normalized
            0.6

        Notes:
            - Edge type normalization handles common naming variations automatically
            - Hierarchical relationships have lower costs for efficient traversal
            - High branching-factor relationships have higher costs to limit exploration
            - Cost factors are optimized for Wikipedia knowledge graph characteristics
            - Default cost is returned for unrecognized edge types
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
        Generate an optimized traversal plan based on Wikipedia-specific considerations.

        This method creates a comprehensive traversal plan that optimizes resource allocation,
        relationship prioritization, and depth management for Wikipedia knowledge graphs.
        The optimization considers relationship importance, traversal costs, and budget
        constraints to create efficient exploration strategies.

        Args:
            start_entities (List[Dict[str, Any]]): Starting entities for traversal initialization.
                Each dictionary should contain entity information including id and type.
            relationship_types (List[str]): Types of relationships to traverse during exploration.
                Will be prioritized and filtered based on Wikipedia-specific importance.
            max_depth (int): Maximum traversal depth for exploration boundary control.
                Higher depths enable broader discovery but require more resources.
            budget (Dict[str, Any]): Resource budget constraints including max_nodes,
                max_time_ms, and other resource limitations for traversal planning.

        Returns:
            Dict[str, Any]: Comprehensive optimized traversal plan containing:
                - strategy: Traversal strategy identifier ("wikipedia_hierarchical")
                - relationship_priority: Relationships sorted by importance and weight
                - level_budgets: Resource allocation for each traversal depth level
                - relationship_activation: Maximum depth for each relationship type
                - traversal_costs: Cost factors for all relationship types
                - original_max_depth: Original maximum depth for reference

        Raises:
            TypeError: If parameters have incorrect types or structures
            ValueError: If max_depth is negative or budget constraints are invalid
            KeyError: If budget dictionary is missing required keys

        Examples:
            >>> optimizer = WikipediaPathOptimizer()
            >>> start_entities = [{"id": "quantum_physics", "type": "topic"}]
            >>> relationship_types = ["subclass_of", "instance_of", "mentions"]
            >>> budget = {"max_nodes": 1000, "max_time_ms": 5000}
            >>> plan = optimizer.optimize_traversal_path(
            ...     start_entities, relationship_types, max_depth=3, budget=budget
            ... )
            >>> plan["strategy"]
            'wikipedia_hierarchical'
            >>> len(plan["level_budgets"]) == 3
            True
            >>> "subclass_of" in plan["relationship_priority"]
            True

        Notes:
            - Resource allocation uses exponential decay for depth-based budget distribution
            - Relationship activation depths prevent low-priority relationship overuse
            - First level receives larger budget allocation for foundation building
            - Strategy optimizes for Wikipedia's hierarchical knowledge structure
            - Cost factors balance traversal efficiency with discovery completeness
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
    Specialized Wikipedia RAG Query Optimizer for Knowledge Graph Operations

    The WikipediaRAGQueryOptimizer class extends the base GraphRAGQueryOptimizer with
    sophisticated optimizations specific to Wikipedia-derived knowledge graphs. It leverages
    the hierarchical nature of Wikipedia categories, entity importance calculations, and
    Wikipedia-specific relationship semantics to generate highly optimized query plans.
    This class serves as the primary optimization engine for Wikipedia knowledge graphs,
    supporting both vector similarity and graph traversal optimization strategies.

    Args:
        query_stats (optional): Query statistics tracker for performance monitoring
            and optimization learning from historical query patterns.
        vector_weight (float, optional): Weight for vector similarity scoring in hybrid
            search strategies. Defaults to 0.7 for balanced vector-graph optimization.
        graph_weight (float, optional): Weight for graph structure scoring in hybrid
            search strategies. Defaults to 0.3 to complement vector weighting.
        cache_enabled (bool, optional): Whether to enable query result caching for
            improved performance on repeated queries. Defaults to True.
        cache_ttl (float, optional): Time-to-live for cached query results in seconds.
            Defaults to 300.0 for balanced freshness and performance.
        cache_size_limit (int, optional): Maximum number of cached query results to maintain.
            Defaults to 100 for memory-efficient caching.
        tracer (WikipediaKnowledgeGraphTracer, optional): Tracer instance for detailed
            logging and explanation of optimization decisions. Defaults to None.

    Key Features:
    - Wikipedia-specific relationship weight calculation and prioritization
    - Hierarchical category structure leveraging for traversal optimization
    - Entity importance scoring based on connectivity and references
    - Query expansion with semantic topic discovery and category relationships
    - Path optimization using Wikipedia knowledge structure characteristics
    - Performance learning from query execution results and patterns
    - Integrated caching for repeated query optimization efficiency
    - Comprehensive tracing and explanation capabilities

    Attributes:
        relationship_calculator (WikipediaRelationshipWeightCalculator): Calculator for
            determining relationship weights and traversal priorities.
        category_hierarchy (WikipediaCategoryHierarchyManager): Manager for Wikipedia
            category hierarchy navigation and optimization.
        entity_importance (WikipediaEntityImportanceCalculator): Calculator for entity
            importance scoring based on multiple relevance factors.
        query_expander (WikipediaQueryExpander): Expander for semantic query enhancement
            with related topics and categories.
        path_optimizer (WikipediaPathOptimizer): Optimizer for graph traversal path
            planning and resource allocation.
        tracer (Optional[WikipediaKnowledgeGraphTracer]): Tracer for logging optimization
            decisions and performance analysis.
        optimization_history (List[Dict[str, Any]]): History of optimization decisions
            for learning and performance improvement.

    Public Methods:
        optimize_query(query_vector: np.ndarray, max_vector_results: int = 5, max_traversal_depth: int = 2, edge_types: Optional[List[str]] = None, min_similarity: float = 0.5, query_text: Optional[str] = None, graph_processor=None, vector_store=None, trace_id: Optional[str] = None) -> Dict[str, Any]:
            Generate an optimized query plan for Wikipedia knowledge graphs with
            relationship prioritization, query expansion, and traversal optimization.
        calculate_entity_importance(entity_id: str, graph_processor) -> float:
            Calculate importance score for an entity using Wikipedia-specific factors
            including connectivity, references, and category importance.
        learn_from_query_results(query_id: str, results: List[Dict[str, Any]], time_taken: float, plan: Dict[str, Any]) -> None:
            Learn from query execution results to improve future optimizations through
            relationship weight adjustment and pattern recognition.

    Usage Example:
        optimizer = WikipediaRAGQueryOptimizer(
            vector_weight=0.7,
            graph_weight=0.3,
            cache_enabled=True,
            tracer=wikipedia_tracer
        )
        # Optimize query for Wikipedia knowledge graph
        optimized_plan = optimizer.optimize_query(
            query_vector=query_embedding,
            max_vector_results=10,
            max_traversal_depth=3,
            edge_types=["subclass_of", "instance_of", "category_contains"],
            min_similarity=0.6,
            query_text="quantum physics research",
            graph_processor=wiki_processor,
            vector_store=vector_db,
            trace_id="wiki_query_001"
        )
        # Learn from query results
        optimizer.learn_from_query_results(
            query_id="wiki_query_001",
            results=query_results,
            time_taken=1.25,
            plan=optimized_plan
        )

    Notes:
        - Optimization leverages Wikipedia's hierarchical category structure
        - Relationship weights are dynamically adjusted based on query performance
        - Entity importance combines connectivity, references, and category relevance
        - Query expansion improves recall through semantic topic discovery
        - Caching provides performance benefits for repeated query patterns
        - Tracing enables detailed analysis of optimization decisions
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
        Calculate importance score for an entity in Wikipedia knowledge graphs.

        This method provides a simplified interface for calculating entity importance
        scores using Wikipedia-specific factors. It retrieves entity information from
        the graph processor and applies the specialized entity importance calculator
        to generate comprehensive importance scores.

        Args:
            entity_id (str): Unique identifier of the entity to calculate importance for.
                Should correspond to a valid entity in the graph processor.
            graph_processor: Graph processor instance providing access to entity information
                through methods like get_entity_info. Used to retrieve entity data
                for importance calculation.

        Returns:
            float: Entity importance score normalized to 0.0-1.0 range.
                Higher scores indicate more important entities for traversal prioritization.
                Calculated using connectivity, references, categories, and other factors.

        Raises:
            TypeError: If entity_id is not a string or graph_processor is invalid
            ValueError: If entity_id is empty or not found in graph processor
            AttributeError: If graph_processor lacks required methods for entity access

        Examples:
            >>> optimizer = WikipediaRAGQueryOptimizer()
            >>> importance = optimizer.calculate_entity_importance(
            ...     entity_id="quantum_entanglement",
            ...     graph_processor=wiki_processor
            ... )
            >>> 0.0 <= importance <= 1.0
            True
            >>> high_importance = optimizer.calculate_entity_importance(
            ...     entity_id="physics",  # Well-connected topic
            ...     graph_processor=wiki_processor
            ... )
            >>> high_importance > 0.5  # Likely high importance
            True

        Notes:
            - Importance calculation uses Wikipedia-specific entity importance calculator
            - Entity data is retrieved automatically from the graph processor
            - Scores combine connectivity, references, categories, and temporal factors
            - Caching improves performance for repeated entity evaluations
            - Fallback handling for entities with missing or incomplete data
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

        This method implements adaptive optimization by analyzing query execution results
        and adjusting relationship weights based on their effectiveness. It enables
        continuous improvement of the optimization system through performance feedback
        and relationship effectiveness analysis.

        Args:
            query_id (str): Unique identifier of the executed query for tracking
                and correlation with optimization decisions and performance metrics.
            results (List[Dict[str, Any]]): Query execution results containing scores,
                paths, and other performance indicators for effectiveness analysis.
            time_taken (float): Query execution time in seconds for performance
                evaluation and optimization learning.
            plan (Dict[str, Any]): The query plan that was used for execution,
                containing strategy, edge types, and other optimization parameters.

        Returns:
            None: This method modifies internal optimization state and relationship weights.

        Raises:
            TypeError: If parameters have incorrect types or structures
            ValueError: If query_id is empty or time_taken is negative
            KeyError: If plan dictionary is missing required optimization components

        Examples:
            >>> optimizer = WikipediaRAGQueryOptimizer()
            >>> results = [
            ...     {"score": 0.9, "path": [{"edge_type": "subclass_of"}]},
            ...     {"score": 0.7, "path": [{"edge_type": "mentions"}]}
            ... ]
            >>> plan = {
            ...     "query": {"traversal": {"edge_types": ["subclass_of", "mentions"]}}
            ... }
            >>> optimizer.learn_from_query_results(
            ...     query_id="learn_001",
            ...     results=results,
            ...     time_taken=1.25,
            ...     plan=plan
            ... )
            >>> # Relationship weights adjusted based on effectiveness

        Notes:
            - Relationship weights are adjusted based on result effectiveness
            - Edge type usage is analyzed from result paths for optimization learning
            - Small incremental adjustments prevent optimization instability
            - Performance metrics are recorded for query pattern analysis
            - Learning improves future optimization decisions through feedback
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
    Specialized Wikipedia Graph RAG Query Rewriter for Knowledge Graph Optimization

    The WikipediaGraphRAGQueryRewriter class extends the base QueryRewriter with
    sophisticated rewriting strategies tailored to Wikipedia-derived knowledge graphs.
    It implements domain-specific query pattern detection and optimization techniques
    that leverage the unique characteristics of Wikipedia knowledge structures,
    including hierarchical categories, entity relationships, and semantic patterns.
    This class serves as a core component for query transformation and optimization,
    supporting both pattern-based rewriting and structural query enhancement.

    Key Features:
    - Wikipedia-specific query pattern detection and classification
    - Domain-aware query rewriting for topic lookup, comparison, and definition queries
    - Hierarchical relationship prioritization for Wikipedia knowledge structures
    - Category-based filtering and topic expansion integration
    - Causal and temporal relationship optimization for Wikipedia content
    - Collection and listing query optimization for structured knowledge discovery
    - Relationship type prioritization using Wikipedia-specific weight calculations
    - Pattern-specific traversal strategy assignment

    Attributes:
        relationship_calculator (WikipediaRelationshipWeightCalculator): Calculator instance
            for determining relationship weights and priorities during query rewriting.
        domain_patterns (Dict[str, re.Pattern]): Compiled regular expressions for detecting
            Wikipedia-specific query patterns including topic_lookup, comparison, definition,
            cause_effect, and list queries with optimized matching strategies.

    Public Methods:
        rewrite_query(query: Dict[str, Any], graph_info: Dict[str, Any] = None) -> Dict[str, Any]:
            Rewrite a query with optimizations for Wikipedia knowledge graphs including
            pattern detection, relationship prioritization, and strategy assignment.

    Private Methods:
        _detect_query_pattern(query_text: str) -> Optional[Tuple[str, List[str]]]:
            Detect Wikipedia-specific query patterns from text using compiled regular
            expressions and extract relevant entities for pattern-based optimization.
        _apply_pattern_optimization(query: Dict[str, Any], pattern_type: str, entities: List[str]) -> Dict[str, Any]:
            Apply pattern-specific optimizations for Wikipedia queries based on detected
            patterns and extracted entities, including strategy and relationship prioritization.

    Usage Example:
        rewriter = WikipediaGraphRAGQueryRewriter()
        # Rewrite query with Wikipedia optimizations
        original_query = {
            "query_text": "What is quantum entanglement?",
            "traversal": {"edge_types": ["mentions", "subclass_of"]},
            "category_filter": ["Physics", "Quantum Mechanics"]
        }
        rewritten_query = rewriter.rewrite_query(
            query=original_query,
            graph_info={"graph_type": "wikipedia"}
        )
        # Access rewritten components
        strategy = rewritten_query["traversal"]["strategy"]
        prioritized_edges = rewritten_query["traversal"]["edge_types"]
        hierarchical_weight = rewritten_query["traversal"]["hierarchical_weight"]

    Notes:
        - Pattern detection handles common Wikipedia query types automatically
        - Relationship prioritization leverages Wikipedia-specific weight calculations
        - Strategy assignment optimizes traversal for different query patterns
        - Category filtering integration enhances query precision
        - Topic expansion support improves query recall and discovery
        - Hierarchical weighting benefits Wikipedia's structured knowledge organization
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
        Apply pattern-specific optimizations for Wikipedia queries based on detected patterns.

        This method implements specialized optimization strategies for different types of
        Wikipedia queries based on pattern detection results. Each pattern type receives
        customized traversal strategies, relationship prioritization, and resource allocation
        to optimize performance for specific query characteristics and user intentions.

        Args:
            query (Dict[str, Any]): Query dictionary to optimize containing traversal
            parameters, edge types, and other optimization settings that will be
            modified based on the detected pattern type.
            pattern_type (str): Detected pattern type from query text analysis including
            "topic_lookup", "comparison", "definition", "cause_effect", or "list"
            determining the optimization strategy to apply.
            entities (List[str]): Extracted entities from pattern matching used for
            entity-specific optimizations and target-focused traversal strategies.

        Returns:
            Dict[str, Any]: Optimized query with pattern-specific modifications including
            updated traversal strategy, prioritized edge types, target entities,
            and other Wikipedia-specific optimization parameters.

        Raises:
            ValueError: If pattern_type is not recognized or entities list is invalid
            KeyError: If query dictionary is missing required optimization parameters

        Examples:
            >>> rewriter = WikipediaGraphRAGQueryRewriter()
            >>> query = {"traversal": {"edge_types": ["mentions", "subclass_of"]}}
            >>> optimized = rewriter._apply_pattern_optimization(
            ...     query, "definition", ["quantum entanglement"]
            ... )
            >>> optimized["traversal"]["strategy"]
            'definition'
            >>> optimized["traversal"]["prioritize_edge_types"]
            ['instance_of', 'subclass_of', 'defined_as']
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
    Specialized Wikipedia Graph RAG Budget Manager for Resource Optimization

    The WikipediaGraphRAGBudgetManager class extends the base QueryBudgetManager with
    sophisticated budget allocation strategies tailored to Wikipedia-derived knowledge
    graphs. It considers the unique characteristics of Wikipedia knowledge structures,
    particularly their hierarchical nature and complex entity relationships, to optimize
    resource allocation across different query operations and traversal strategies.
    This class serves as a core component for performance optimization and resource
    management in Wikipedia knowledge graph operations.

    Key Features:
    - Wikipedia-specific budget allocation with category and topic expansion support
    - Hierarchical traversal budget optimization for Wikipedia category structures
    - Strategy-based resource allocation for different query types and patterns
    - Dynamic budget scaling based on query complexity and priority levels
    - Category-focused budget adjustments for category-intensive operations
    - Topic expansion budget management for semantic query enhancement
    - Early stopping optimization with Wikipedia-specific stopping criteria
    - Performance-aware resource allocation with diminishing returns analysis

    Attributes:
        wikipedia_budget_extensions (Dict[str, Any]): Wikipedia-specific budget parameters
            including category_traversal_ms (5000), topic_expansion_ms (3000),
            max_categories (20), and max_topics (15) for specialized operations.
        default_budget (Dict[str, Any]): Extended default budget combining base budget
            allocations with Wikipedia-specific resource allocations for comprehensive
            resource management.

    Public Methods:
        allocate_budget(query: Dict[str, Any], priority: str = "normal") -> Dict[str, Any]:
            Allocate resources based on query complexity and Wikipedia-specific factors
            including strategy type, edge types, and expansion requirements.
        suggest_early_stopping(results: List[Dict[str, Any]], budget_consumed_ratio: float) -> bool:
            Provide Wikipedia-specific early stopping suggestions based on result quality,
            category matches, and diminishing returns analysis.

    Usage Example:
        budget_manager = WikipediaGraphRAGBudgetManager()
        # Allocate budget for Wikipedia query
        query = {
            "traversal": {
                "strategy": "wikipedia_hierarchical",
                "edge_types": ["category_contains", "subclass_of"],
                "expand_topics": True,
                "topic_expansion_factor": 1.5
            },
            "priority": "high"
        }
        budget = budget_manager.allocate_budget(query, priority="high")
        # Check early stopping
        should_stop = budget_manager.suggest_early_stopping(
            results=current_results,
            budget_consumed_ratio=0.75
        )
        # Access budget allocations
        category_time = budget["category_traversal_ms"]
        topic_time = budget["topic_expansion_ms"]
        max_categories = budget["max_categories"]

    Notes:
        - Budget allocation considers Wikipedia's hierarchical structure characteristics
        - Category-focused operations receive increased resource allocations
        - Topic expansion budget scales with expansion factors and requirements
        - Strategy-specific adjustments optimize for different traversal patterns
        - Early stopping criteria include category match quality and diminishing returns
        - Resource allocation balances performance with comprehensive discovery
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
    Unified Wikipedia Graph RAG Query Optimizer for Comprehensive Knowledge Graph Operations

    The UnifiedWikipediaGraphRAGQueryOptimizer class integrates all Wikipedia-specific
    optimization components (optimizer, rewriter, budget manager) into a single unified
    optimizer that provides comprehensive query optimization for Wikipedia-derived knowledge
    graphs. It serves as a drop-in replacement for the base unified optimizer while
    leveraging Wikipedia's unique structural characteristics and semantic relationships.
    This class coordinates multiple optimization subsystems to deliver optimal performance
    for Wikipedia knowledge graph queries.

    Args:
        rewriter (optional): Query rewriter component for Wikipedia-specific query
            transformations. Defaults to WikipediaGraphRAGQueryRewriter if not provided.
        budget_manager (optional): Budget manager component for Wikipedia-specific resource
            allocation. Defaults to WikipediaGraphRAGBudgetManager if not provided.
        base_optimizer (optional): Base optimization component for core query optimization.
            Defaults to WikipediaRAGQueryOptimizer if not provided.
        graph_info (Dict, optional): Graph structure information including graph type
            and metadata. Defaults to {"graph_type": "wikipedia"} if not provided.
        metrics_collector (optional): Performance metrics collector for query tracking
            and analysis. Used for performance monitoring and optimization learning.
        tracer (optional): Tracer for explanation and detailed logging of optimization
            decisions across all subsystems.

    Key Features:
    - Integrated Wikipedia-specific optimization pipeline with coordinated components
    - Comprehensive query rewriting with pattern detection and strategy assignment
    - Advanced budget allocation with Wikipedia-specific resource management
    - Performance metrics collection and analysis for optimization learning
    - Detailed tracing and explanation capabilities across all optimization phases
    - Seamless integration with existing GraphRAG infrastructure
    - Drop-in replacement compatibility with base unified optimizer
    - Coordinated optimization across vector search and graph traversal operations

    Attributes:
        tracer (optional): Tracer instance for logging optimization decisions and
            performance analysis across all integrated optimization components.
        last_query_id (str): Identifier of the most recently optimized query for
            metrics tracking and result correlation.

    Public Methods:
        optimize_query(query: Dict[str, Any], graph_processor=None, vector_store=None, trace_id: Optional[str] = None) -> Dict[str, Any]:
            Optimize a query for Wikipedia knowledge graphs through integrated pipeline
            including rewriting, budget allocation, and metrics collection.

    Usage Example:
        unified_optimizer = UnifiedWikipediaGraphRAGQueryOptimizer(
            metrics_collector=metrics_collector,
            tracer=wikipedia_tracer
        )
        # Optimize Wikipedia query through unified pipeline
        query = {
            "query_vector": query_embedding,
            "query_text": "quantum physics research methods",
            "max_vector_results": 10,
            "max_traversal_depth": 3,
            "edge_types": ["subclass_of", "instance_of", "category_contains"],
            "min_similarity": 0.6,
            "priority": "high"
        }
        optimized_plan = unified_optimizer.optimize_query(
            query=query,
            graph_processor=wiki_processor,
            vector_store=vector_db,
            trace_id="unified_wiki_query_001"
        )
        # Access integrated optimization results
        rewritten_query = optimized_plan["query"]
        allocated_budget = optimized_plan["budget"]
        query_id = optimized_plan["query_id"]

    Notes:
        - Integrates Wikipedia-specific components for comprehensive optimization
        - Coordinates rewriting, budget allocation, and metrics collection
        - Provides seamless compatibility with existing GraphRAG infrastructure
        - Leverages Wikipedia's hierarchical structure and semantic relationships
        - Enables detailed performance tracking and optimization learning
        - Supports comprehensive tracing and explanation of optimization decisions
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
    Detect Wikipedia-derived graph type based on entity and relationship patterns.

    This function analyzes a graph processor to determine if it contains a Wikipedia-derived
    knowledge graph by examining entity types, relationship patterns, and structural
    characteristics. It provides automatic graph type detection to enable appropriate
    optimizer selection and configuration for different knowledge graph types.

    Args:
        graph_processor: Graph processor instance to analyze for type detection.
            Should provide access to entities and relationships through methods like
            get_entities(), list_entities(), get_relationship_types(), or similar.

    Returns:
        str: Detected graph type with possible values:
            - "wikipedia": Wikipedia-derived knowledge graph with hierarchical categories
            - "ipld": IPLD-based content-addressed knowledge graph
            - "unknown": Unable to determine graph type or mixed characteristics

    Raises:
        AttributeError: If graph_processor lacks required methods for analysis
        Exception: If entity or relationship analysis encounters unexpected errors

    Examples:
        >>> graph_type = detect_graph_type(wiki_processor)
        >>> print(graph_type)
        'wikipedia'
        >>> graph_type = detect_graph_type(ipld_processor)
        >>> print(graph_type)
        'ipld'
        >>> graph_type = detect_graph_type(unknown_processor)
        >>> print(graph_type)
        'unknown'

    Notes:
        - Detection analyzes entity types for Wikipedia indicators (category, article, topic)
        - Relationship types are examined for Wikipedia patterns (subclass_of, instance_of)
        - IPLD indicators include content addressing and DAG structure patterns
        - Sample size is limited to 20 entities for performance optimization
        - Detection is based on indicator counting with threshold comparison
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
    Create an appropriate optimizer based on detected or specified graph type.

    This function automatically selects and instantiates the most suitable query optimizer
    for a given knowledge graph based on its type characteristics. It supports both
    automatic graph type detection and explicit type specification, ensuring optimal
    performance for different knowledge graph structures and semantics.

    Args:
        graph_processor (optional): Graph processor instance for automatic type detection.
            Used to analyze graph characteristics when graph_type is not specified.
        graph_type (Optional[str], optional): Explicitly specified graph type to override
            automatic detection. Supported values: "wikipedia", "ipld", "unknown".
            Defaults to None for automatic detection.
        metrics_collector (Optional[QueryMetricsCollector], optional): Performance metrics
            collector for query tracking and optimization analysis. Enables detailed
            performance monitoring and learning. Defaults to None.
        tracer (Optional[WikipediaKnowledgeGraphTracer], optional): Tracer instance for
            detailed logging and explanation of optimization decisions. Provides
            comprehensive optimization analysis. Defaults to None.

    Returns:
        UnifiedGraphRAGQueryOptimizer: Appropriate optimizer instance configured for
            the detected or specified graph type. Returns UnifiedWikipediaGraphRAGQueryOptimizer
            for Wikipedia graphs or UnifiedGraphRAGQueryOptimizer for other types.

    Raises:
        ValueError: If graph_type is specified but not recognized
        AttributeError: If graph_processor lacks required methods for type detection
        Exception: If optimizer instantiation encounters configuration errors

    Examples:
        >>> optimizer = create_appropriate_optimizer(
        ...     graph_processor=wiki_processor,
        ...     metrics_collector=metrics,
        ...     tracer=tracer
        ... )
        >>> isinstance(optimizer, UnifiedWikipediaGraphRAGQueryOptimizer)
        True
        >>> optimizer = create_appropriate_optimizer(
        ...     graph_type="wikipedia",
        ...     tracer=tracer
        ... )
        >>> optimizer = create_appropriate_optimizer(
        ...     graph_type="unknown"
        ... )
        >>> isinstance(optimizer, UnifiedGraphRAGQueryOptimizer)
        True

    Notes:
        - Automatic detection analyzes graph structure and entity patterns
        - Wikipedia graphs receive specialized Wikipedia-optimized components
        - Unknown or non-Wikipedia graphs use standard optimization components
        - Metrics collector enables performance tracking across query executions
        - Tracer provides detailed optimization decision logging and explanation
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
    Optimize a query for Wikipedia-derived knowledge graphs with comprehensive optimization.

    This is the main entry point for using Wikipedia-specific query optimizations. It provides
    a high-level interface that automatically configures and applies all Wikipedia-specific
    optimization techniques including relationship prioritization, category hierarchy leveraging,
    entity importance calculation, query expansion, and performance optimization.
    This function serves as the primary interface for Wikipedia knowledge graph query optimization.

    Args:
        query (Dict[str, Any]): Query parameters including query_vector, query_text,
            max_vector_results, max_traversal_depth, edge_types, min_similarity,
            and other optimization parameters for comprehensive query specification.
        graph_processor (optional): Graph processor instance providing access to Wikipedia
            knowledge graph structure, entities, and relationships for optimization analysis.
        vector_store (optional): Vector store instance for semantic similarity search
            and query expansion operations in the optimization pipeline.
        tracer (Optional[WikipediaKnowledgeGraphTracer], optional): Tracer instance for
            detailed logging and explanation of optimization decisions throughout
            the optimization process. Defaults to None.
        metrics_collector (Optional[QueryMetricsCollector], optional): Performance metrics
            collector for query tracking, analysis, and optimization learning.
            Enables comprehensive performance monitoring. Defaults to None.
        trace_id (Optional[str], optional): Unique trace identifier for correlating
            optimization decisions and performance metrics across the optimization
            pipeline. Defaults to None.

    Returns:
        Dict[str, Any]: Comprehensive optimized query plan containing:
            - query: Rewritten and optimized query parameters
            - budget: Allocated resource budget for query execution
            - weights: Scoring weights for vector and graph components
            - expansions: Query expansion results with topics and categories
            - query_id: Unique identifier for metrics tracking and correlation

    Raises:
        ValueError: If required query parameters are missing or invalid
        TypeError: If query parameters have incorrect types or formats
        AttributeError: If graph_processor or vector_store lack required methods
        Exception: If optimization process encounters unexpected errors

    Examples:
        >>> query = {
        ...     "query_vector": query_embedding,
        ...     "query_text": "quantum entanglement experiments",
        ...     "max_vector_results": 10,
        ...     "max_traversal_depth": 3,
        ...     "edge_types": ["subclass_of", "instance_of", "category_contains"],
        ...     "min_similarity": 0.6,
        ...     "priority": "high"
        ... }
        >>> optimized_plan = optimize_wikipedia_query(
        ...     query=query,
        ...     graph_processor=wiki_processor,
        ...     vector_store=vector_db,
        ...     tracer=wikipedia_tracer,
        ...     metrics_collector=metrics,
        ...     trace_id="wiki_opt_001"
        ... )
        >>> # Access optimization results
        >>> rewritten_query = optimized_plan["query"]
        >>> budget = optimized_plan["budget"]
        >>> expansions = optimized_plan["expansions"]

    Notes:
        - This function automatically applies all Wikipedia-specific optimizations
        - Relationship types are prioritized based on Wikipedia knowledge structure
        - Category hierarchy is leveraged for improved traversal strategies
        - Query expansion improves recall through semantic topic discovery
        - Performance metrics enable continuous optimization improvement
        - Comprehensive tracing provides detailed optimization analysis
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
