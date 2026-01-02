Feature: WikipediaGraphRAGQueryRewriter
  This feature file describes the WikipediaGraphRAGQueryRewriter callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Background:
    Given a WikipediaGraphRAGQueryRewriter instance

  Scenario: Initialize with default configuration
    When the rewriter is initialized
    Then relationship_calculator is set
    And domain_patterns contains topic_lookup
    And domain_patterns contains comparison
    And domain_patterns contains definition
    And domain_patterns contains cause_effect
    And domain_patterns contains list

  Scenario: Rewrite query prioritizes edge types
    Given query with traversal edge_types as mentions, subclass_of
    When rewrite_query is called
    Then traversal edge_types first item is subclass_of
    And traversal edge_types second item is mentions
    And traversal hierarchical_weight is 1.5

  Scenario: Rewrite query with category filter
    Given query with category_filter as Physics, Chemistry
    When rewrite_query is called
    Then vector_params categories contains Physics
    And vector_params categories contains Chemistry

  Scenario: Rewrite query with topic expansion
    Given query with expand_topics as True
    And query with topic_expansion_factor as 1.5
    When rewrite_query is called
    Then traversal expand_topics is True
    And traversal topic_expansion_factor is 1.5

  Scenario: Detect topic lookup pattern
    Given query_text as information about quantum physics
    When _detect_query_pattern is called
    Then pattern_type is topic_lookup
    And entities contains quantum physics

  Scenario: Detect comparison pattern
    Given query_text as compare classical physics and quantum physics
    When _detect_query_pattern is called
    Then pattern_type is comparison
    And entities contains classical physics
    And entities contains quantum physics

  Scenario: Detect definition pattern
    Given query_text as what is quantum entanglement
    When _detect_query_pattern is called
    Then pattern_type is definition
    And entities contains quantum entanglement

  Scenario: Detect cause effect pattern
    Given query_text as effects of global warming
    When _detect_query_pattern is called
    Then pattern_type is cause_effect
    And entities contains global warming

  Scenario: Detect list pattern
    Given query_text as list of quantum physics theories
    When _detect_query_pattern is called
    Then pattern_type is list
    And entities contains quantum physics theories

  Scenario: Apply topic lookup optimization
    Given query with traversal
    And pattern_type as topic_lookup
    And entities as quantum physics
    When _apply_pattern_optimization is called
    Then traversal strategy is topic_focused
    And traversal target_entities contains quantum physics
    And traversal prioritize_relationships is True

  Scenario: Apply comparison optimization
    Given query with traversal
    And pattern_type as comparison
    And entities as classical physics, quantum physics
    When _apply_pattern_optimization is called
    Then traversal strategy is comparison
    And traversal comparison_entities contains both entities
    And traversal find_common_categories is True
    And traversal find_relationships_between is True

  Scenario: Apply definition optimization
    Given query with traversal
    And pattern_type as definition
    When _apply_pattern_optimization is called
    Then traversal strategy is definition
    And traversal prioritize_edge_types contains instance_of
    And traversal prioritize_edge_types contains subclass_of
    And traversal prioritize_edge_types contains defined_as

  Scenario: Apply cause effect optimization
    Given query with traversal
    And pattern_type as cause_effect
    When _apply_pattern_optimization is called
    Then traversal strategy is causal
    And traversal prioritize_edge_types contains causes
    And traversal prioritize_edge_types contains caused_by

  Scenario: Apply list optimization
    Given query with traversal
    And pattern_type as list
    And entities as quantum theories
    When _apply_pattern_optimization is called
    Then traversal strategy is collection
    And traversal prioritize_edge_types contains instance_of
    And traversal collection_target is quantum theories

  Scenario: Rewrite query detects and applies pattern
    Given query with query_text as what is quantum physics
    And query with traversal edge_types as mentions
    When rewrite_query is called
    Then traversal strategy is definition
    And traversal prioritize_edge_types contains instance_of
    And edge_types are prioritized
