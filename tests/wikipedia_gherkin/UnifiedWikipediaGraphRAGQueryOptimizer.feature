Feature: UnifiedWikipediaGraphRAGQueryOptimizer
  This feature file describes the UnifiedWikipediaGraphRAGQueryOptimizer callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Background:
    Given a UnifiedWikipediaGraphRAGQueryOptimizer instance

  Scenario: Initialize with default components
    When the optimizer is initialized
    Then rewriter is WikipediaGraphRAGQueryRewriter
    And budget_manager is WikipediaGraphRAGBudgetManager
    And base_optimizer is WikipediaRAGQueryOptimizer
    And graph_info contains graph_type as wikipedia

  Scenario: Initialize with custom components
    Given custom rewriter instance
    And custom budget_manager instance
    And custom base_optimizer instance
    When the optimizer is initialized with custom components
    Then rewriter is custom instance
    And budget_manager is custom instance
    And base_optimizer is custom instance

  Scenario: Initialize with tracer
    Given a WikipediaKnowledgeGraphTracer instance
    When the optimizer is initialized with tracer
    Then tracer is set in unified optimizer
    And tracer is set in base_optimizer

  Scenario: Optimize query with all parameters
    Given query with query_vector as numpy array
    And query with query_text as quantum physics
    And query with max_vector_results as 10
    And query with max_traversal_depth as 3
    And query with edge_types as subclass_of, instance_of
    And query with min_similarity as 0.6
    And query with priority as high
    When optimize_query is called
    Then result contains query
    And result contains budget
    And result contains query_id

  Scenario: Optimize query applies base optimization
    Given query with query_vector as numpy array
    When optimize_query is called
    Then base optimizer optimize_query is called
    And result includes base optimization

  Scenario: Optimize query applies rewriting
    Given query with query_vector as numpy array
    And query with query_text as what is quantum physics
    When optimize_query is called
    Then rewriter rewrite_query is called
    And query is rewritten with Wikipedia optimizations

  Scenario: Optimize query allocates budget
    Given query with query_vector as numpy array
    And query with priority as high
    When optimize_query is called
    Then budget_manager allocate_budget is called
    And budget is allocated with priority high

  Scenario: Optimize query with metrics collector
    Given query with query_vector as numpy array
    And metrics_collector is set
    When optimize_query is called
    Then metrics_collector starts query tracking
    And query_id is included in result

  Scenario: Optimize query with trace_id
    Given query with query_vector as numpy array
    And tracer is set
    And trace_id as unified_001
    When optimize_query is called with trace_id
    Then tracer logs unified optimization
    And trace_id is unified_001

  Scenario: Optimize query without query_vector raises error
    Given query without query_vector
    When optimize_query is called
    Then ValueError is raised with message Query vector is required

  Scenario: Optimize query with graph_processor
    Given query with query_vector as numpy array
    And graph_processor instance
    When optimize_query is called with graph_processor
    Then base optimizer receives graph_processor

  Scenario: Optimize query with vector_store
    Given query with query_vector as numpy array
    And vector_store instance
    When optimize_query is called with vector_store
    Then base optimizer receives vector_store

  Scenario: Optimize query stores last_query_id
    Given query with query_vector as numpy array
    And metrics_collector is set
    When optimize_query is called
    Then last_query_id is set
    And last_query_id matches result query_id

  Scenario: Optimize query uses default parameters
    Given query with query_vector as numpy array
    When optimize_query is called
    Then max_vector_results defaults to 5
    And max_traversal_depth defaults to 2
    And min_similarity defaults to 0.5
