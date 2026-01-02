Feature: optimize_wikipedia_query
  This feature file describes the optimize_wikipedia_query callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Scenario: Optimize query with all parameters
    Given query with query_vector as numpy array
    And query with query_text as quantum physics
    And query with max_vector_results as 10
    And graph_processor instance
    And vector_store instance
    And tracer instance
    And metrics_collector instance
    And trace_id as wiki_opt_001
    When optimize_wikipedia_query is called
    Then result contains query
    And result contains budget
    And result contains weights
    And result contains expansions

  Scenario: Optimize query with minimal parameters
    Given query with query_vector as numpy array
    When optimize_wikipedia_query is called
    Then result contains query
    And result contains budget
    And Wikipedia optimizations are applied

  Scenario: Optimize query creates Wikipedia optimizer
    Given query with query_vector as numpy array
    When optimize_wikipedia_query is called
    Then UnifiedWikipediaGraphRAGQueryOptimizer is created
    And optimizer is configured with graph_type wikipedia

  Scenario: Optimize query with graph_processor
    Given query with query_vector as numpy array
    And graph_processor instance
    When optimize_wikipedia_query is called with graph_processor
    Then optimizer receives graph_processor
    And graph structure is used for optimization

  Scenario: Optimize query with vector_store
    Given query with query_vector as numpy array
    And query with query_text as quantum physics
    And vector_store instance
    When optimize_wikipedia_query is called with vector_store
    Then optimizer receives vector_store
    And query expansion uses vector_store

  Scenario: Optimize query with tracer
    Given query with query_vector as numpy array
    And tracer instance
    And trace_id as trace_001
    When optimize_wikipedia_query is called with tracer and trace_id
    Then optimizer is created with tracer
    And optimization is logged with trace_id

  Scenario: Optimize query with metrics collector
    Given query with query_vector as numpy array
    And metrics_collector instance
    When optimize_wikipedia_query is called with metrics_collector
    Then optimizer is created with metrics_collector
    And query tracking is started

  Scenario: Optimize query applies relationship prioritization
    Given query with query_vector as numpy array
    And query with edge_types as mentions, subclass_of
    When optimize_wikipedia_query is called
    Then edge_types are prioritized
    And subclass_of comes before mentions

  Scenario: Optimize query applies category hierarchy
    Given query with query_vector as numpy array
    And query with query_text as physics research
    When optimize_wikipedia_query is called
    Then category hierarchy is leveraged
    And hierarchical relationships are prioritized

  Scenario: Optimize query applies entity importance
    Given query with query_vector as numpy array
    And graph_processor with entity data
    When optimize_wikipedia_query is called with graph_processor
    Then entity importance calculations are used
    And important entities are prioritized

  Scenario: Optimize query expands query
    Given query with query_vector as numpy array
    And query with query_text as quantum physics
    And vector_store instance
    When optimize_wikipedia_query is called with vector_store
    Then query expansion is performed
    And result contains expansions with topics
    And result contains expansions with categories

  Scenario: Optimize query without query_text
    Given query with query_vector as numpy array
    And no query_text
    When optimize_wikipedia_query is called
    Then query is optimized without expansion
    And result contains query
    And result contains budget
