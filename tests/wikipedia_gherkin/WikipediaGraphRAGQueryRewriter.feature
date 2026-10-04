Feature: WikipediaGraphRAGQueryRewriter
  This feature file describes the WikipediaGraphRAGQueryRewriter callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Background:
    Given a WikipediaGraphRAGQueryRewriter instance

  Scenario: Initialize with default configuration relationship_calculator is set
    When the rewriter is initialized
    Then relationship_calculator is set

  Scenario: Initialize with default configuration domain_patterns contains topic_lookup
    When the rewriter is initialized
    Then domain_patterns contains topic_lookup

  Scenario: Initialize with default configuration domain_patterns contains comparison
    When the rewriter is initialized
    Then domain_patterns contains comparison

  Scenario: Initialize with default configuration domain_patterns contains definition
    When the rewriter is initialized
    Then domain_patterns contains definition

  Scenario: Initialize with default configuration domain_patterns contains cause_effect
    When the rewriter is initialized
    Then domain_patterns contains cause_effect

  Scenario: Initialize with default configuration domain_patterns contains list
    When the rewriter is initialized
    Then domain_patterns contains list


  Scenario: Rewrite query prioritizes edge types traversal edge_types first item is subclass_of
    Given query with traversal edge_types as mentions, subclass_of
    When rewrite_query is called
    Then traversal edge_types first item is subclass_of

  Scenario: Rewrite query prioritizes edge types traversal edge_types second item is mentions
    Given query with traversal edge_types as mentions, subclass_of
    When rewrite_query is called
    Then traversal edge_types second item is mentions

  Scenario: Rewrite query prioritizes edge types traversal hierarchical_weight is 1.5
    Given query with traversal edge_types as mentions, subclass_of
    When rewrite_query is called
    Then traversal hierarchical_weight is 1.5


  Scenario: Rewrite query with category filter vector_params categories contains Physics
    Given query with category_filter as Physics, Chemistry
    When rewrite_query is called
    Then vector_params categories contains Physics

  Scenario: Rewrite query with category filter vector_params categories contains Chemistry
    Given query with category_filter as Physics, Chemistry
    When rewrite_query is called
    Then vector_params categories contains Chemistry


  Scenario: Rewrite query with topic expansion traversal expand_topics is True
    Given query with expand_topics as True
    And query with topic_expansion_factor as 1.5
    When rewrite_query is called
    Then traversal expand_topics is True

  Scenario: Rewrite query with topic expansion traversal topic_expansion_factor is 1.5
    Given query with expand_topics as True
    And query with topic_expansion_factor as 1.5
    When rewrite_query is called
    Then traversal topic_expansion_factor is 1.5


  Scenario: Detect topic lookup pattern pattern_type is topic_lookup
    Given query_text as information about quantum physics
    When _detect_query_pattern is called
    Then pattern_type is topic_lookup

  Scenario: Detect topic lookup pattern entities contains quantum physics
    Given query_text as information about quantum physics
    When _detect_query_pattern is called
    Then entities contains quantum physics


  Scenario: Detect comparison pattern pattern_type is comparison
    Given query_text as compare classical physics and quantum physics
    When _detect_query_pattern is called
    Then pattern_type is comparison

  Scenario: Detect comparison pattern entities contains classical physics
    Given query_text as compare classical physics and quantum physics
    When _detect_query_pattern is called
    Then entities contains classical physics

  Scenario: Detect comparison pattern entities contains quantum physics
    Given query_text as compare classical physics and quantum physics
    When _detect_query_pattern is called
    Then entities contains quantum physics


  Scenario: Detect definition pattern pattern_type is definition
    Given query_text as what is quantum entanglement
    When _detect_query_pattern is called
    Then pattern_type is definition

  Scenario: Detect definition pattern entities contains quantum entanglement
    Given query_text as what is quantum entanglement
    When _detect_query_pattern is called
    Then entities contains quantum entanglement


  Scenario: Detect cause effect pattern pattern_type is cause_effect
    Given query_text as effects of global warming
    When _detect_query_pattern is called
    Then pattern_type is cause_effect

  Scenario: Detect cause effect pattern entities contains global warming
    Given query_text as effects of global warming
    When _detect_query_pattern is called
    Then entities contains global warming


  Scenario: Detect list pattern pattern_type is list
    Given query_text as list of quantum physics theories
    When _detect_query_pattern is called
    Then pattern_type is list

  Scenario: Detect list pattern entities contains quantum physics theories
    Given query_text as list of quantum physics theories
    When _detect_query_pattern is called
    Then entities contains quantum physics theories


  Scenario: Apply topic lookup optimization traversal strategy is topic_focused
    Given query with traversal
    And pattern_type as topic_lookup
    And entities as quantum physics
    When _apply_pattern_optimization is called
    Then traversal strategy is topic_focused

  Scenario: Apply topic lookup optimization traversal target_entities contains quantum physics
    Given query with traversal
    And pattern_type as topic_lookup
    And entities as quantum physics
    When _apply_pattern_optimization is called
    Then traversal target_entities contains quantum physics

  Scenario: Apply topic lookup optimization traversal prioritize_relationships is True
    Given query with traversal
    And pattern_type as topic_lookup
    And entities as quantum physics
    When _apply_pattern_optimization is called
    Then traversal prioritize_relationships is True


  Scenario: Apply comparison optimization traversal strategy is comparison
    Given query with traversal
    And pattern_type as comparison
    And entities as classical physics, quantum physics
    When _apply_pattern_optimization is called
    Then traversal strategy is comparison

  Scenario: Apply comparison optimization traversal comparison_entities contains both entities
    Given query with traversal
    And pattern_type as comparison
    And entities as classical physics, quantum physics
    When _apply_pattern_optimization is called
    Then traversal comparison_entities contains both entities

  Scenario: Apply comparison optimization traversal find_common_categories is True
    Given query with traversal
    And pattern_type as comparison
    And entities as classical physics, quantum physics
    When _apply_pattern_optimization is called
    Then traversal find_common_categories is True

  Scenario: Apply comparison optimization traversal find_relationships_between is True
    Given query with traversal
    And pattern_type as comparison
    And entities as classical physics, quantum physics
    When _apply_pattern_optimization is called
    Then traversal find_relationships_between is True


  Scenario: Apply definition optimization traversal strategy is definition
    Given query with traversal
    And pattern_type as definition
    When _apply_pattern_optimization is called
    Then traversal strategy is definition

  Scenario: Apply definition optimization traversal prioritize_edge_types contains instance_of
    Given query with traversal
    And pattern_type as definition
    When _apply_pattern_optimization is called
    Then traversal prioritize_edge_types contains instance_of

  Scenario: Apply definition optimization traversal prioritize_edge_types contains subclass_of
    Given query with traversal
    And pattern_type as definition
    When _apply_pattern_optimization is called
    Then traversal prioritize_edge_types contains subclass_of

  Scenario: Apply definition optimization traversal prioritize_edge_types contains defined_as
    Given query with traversal
    And pattern_type as definition
    When _apply_pattern_optimization is called
    Then traversal prioritize_edge_types contains defined_as


  Scenario: Apply cause effect optimization traversal strategy is causal
    Given query with traversal
    And pattern_type as cause_effect
    When _apply_pattern_optimization is called
    Then traversal strategy is causal

  Scenario: Apply cause effect optimization traversal prioritize_edge_types contains causes
    Given query with traversal
    And pattern_type as cause_effect
    When _apply_pattern_optimization is called
    Then traversal prioritize_edge_types contains causes

  Scenario: Apply cause effect optimization traversal prioritize_edge_types contains caused_by
    Given query with traversal
    And pattern_type as cause_effect
    When _apply_pattern_optimization is called
    Then traversal prioritize_edge_types contains caused_by


  Scenario: Apply list optimization traversal strategy is collection
    Given query with traversal
    And pattern_type as list
    And entities as quantum theories
    When _apply_pattern_optimization is called
    Then traversal strategy is collection

  Scenario: Apply list optimization traversal prioritize_edge_types contains instance_of
    Given query with traversal
    And pattern_type as list
    And entities as quantum theories
    When _apply_pattern_optimization is called
    Then traversal prioritize_edge_types contains instance_of

  Scenario: Apply list optimization traversal collection_target is quantum theories
    Given query with traversal
    And pattern_type as list
    And entities as quantum theories
    When _apply_pattern_optimization is called
    Then traversal collection_target is quantum theories


  Scenario: Rewrite query detects and applies pattern traversal strategy is definition
    Given query with query_text as what is quantum physics
    And query with traversal edge_types as mentions
    When rewrite_query is called
    Then traversal strategy is definition

  Scenario: Rewrite query detects and applies pattern traversal prioritize_edge_types contains instance_of
    Given query with query_text as what is quantum physics
    And query with traversal edge_types as mentions
    When rewrite_query is called
    Then traversal prioritize_edge_types contains instance_of

  Scenario: Rewrite query detects and applies pattern edge_types are prioritized
    Given query with query_text as what is quantum physics
    And query with traversal edge_types as mentions
    When rewrite_query is called
    Then edge_types are prioritized

