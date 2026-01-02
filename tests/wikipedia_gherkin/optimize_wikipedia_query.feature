Feature: optimize_wikipedia_query
  This feature file describes the optimize_wikipedia_query callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Scenario: Optimize query with all parameters result contains query
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

  Scenario: Optimize query with all parameters result contains budget
    Given query with query_vector as numpy array
    And query with query_text as quantum physics
    And query with max_vector_results as 10
    And graph_processor instance
    And vector_store instance
    And tracer instance
    And metrics_collector instance
    And trace_id as wiki_opt_001
    When optimize_wikipedia_query is called
    Then result contains budget

  Scenario: Optimize query with all parameters result contains weights
    Given query with query_vector as numpy array
    And query with query_text as quantum physics
    And query with max_vector_results as 10
    And graph_processor instance
    And vector_store instance
    And tracer instance
    And metrics_collector instance
    And trace_id as wiki_opt_001
    When optimize_wikipedia_query is called
    Then result contains weights

  Scenario: Optimize query with all parameters result contains expansions
    Given query with query_vector as numpy array
    And query with query_text as quantum physics
    And query with max_vector_results as 10
    And graph_processor instance
    And vector_store instance
    And tracer instance
    And metrics_collector instance
    And trace_id as wiki_opt_001
    When optimize_wikipedia_query is called
    Then result contains expansions


  Scenario: Optimize query with minimal parameters result contains query
    Given query with query_vector as numpy array
    When optimize_wikipedia_query is called
    Then result contains query

  Scenario: Optimize query with minimal parameters result contains budget
    Given query with query_vector as numpy array
    When optimize_wikipedia_query is called
    Then result contains budget

  Scenario: Optimize query with minimal parameters Wikipedia optimizations are applied
    Given query with query_vector as numpy array
    When optimize_wikipedia_query is called
    Then Wikipedia optimizations are applied


  Scenario: Optimize query creates Wikipedia optimizer UnifiedWikipediaGraphRAGQueryOptimizer is created
    Given query with query_vector as numpy array
    When optimize_wikipedia_query is called
    Then UnifiedWikipediaGraphRAGQueryOptimizer is created

  Scenario: Optimize query creates Wikipedia optimizer optimizer is configured with graph_type wikipedia
    Given query with query_vector as numpy array
    When optimize_wikipedia_query is called
    Then optimizer is configured with graph_type wikipedia


  Scenario: Optimize query with graph_processor optimizer receives graph_processor
    Given query with query_vector as numpy array
    And graph_processor instance
    When optimize_wikipedia_query is called with graph_processor
    Then optimizer receives graph_processor

  Scenario: Optimize query with graph_processor graph structure is used for optimization
    Given query with query_vector as numpy array
    And graph_processor instance
    When optimize_wikipedia_query is called with graph_processor
    Then graph structure is used for optimization


  Scenario: Optimize query with vector_store optimizer receives vector_store
    Given query with query_vector as numpy array
    And query with query_text as quantum physics
    And vector_store instance
    When optimize_wikipedia_query is called with vector_store
    Then optimizer receives vector_store

  Scenario: Optimize query with vector_store query expansion uses vector_store
    Given query with query_vector as numpy array
    And query with query_text as quantum physics
    And vector_store instance
    When optimize_wikipedia_query is called with vector_store
    Then query expansion uses vector_store


  Scenario: Optimize query with tracer optimizer is created with tracer
    Given query with query_vector as numpy array
    And tracer instance
    And trace_id as trace_001
    When optimize_wikipedia_query is called with tracer and trace_id
    Then optimizer is created with tracer

  Scenario: Optimize query with tracer optimization is logged with trace_id
    Given query with query_vector as numpy array
    And tracer instance
    And trace_id as trace_001
    When optimize_wikipedia_query is called with tracer and trace_id
    Then optimization is logged with trace_id


  Scenario: Optimize query with metrics collector optimizer is created with metrics_collector
    Given query with query_vector as numpy array
    And metrics_collector instance
    When optimize_wikipedia_query is called with metrics_collector
    Then optimizer is created with metrics_collector

  Scenario: Optimize query with metrics collector query tracking is started
    Given query with query_vector as numpy array
    And metrics_collector instance
    When optimize_wikipedia_query is called with metrics_collector
    Then query tracking is started


  Scenario: Optimize query applies relationship prioritization edge_types are prioritized
    Given query with query_vector as numpy array
    And query with edge_types as mentions, subclass_of
    When optimize_wikipedia_query is called
    Then edge_types are prioritized

  Scenario: Optimize query applies relationship prioritization subclass_of comes before mentions
    Given query with query_vector as numpy array
    And query with edge_types as mentions, subclass_of
    When optimize_wikipedia_query is called
    Then subclass_of comes before mentions


  Scenario: Optimize query applies category hierarchy category hierarchy is leveraged
    Given query with query_vector as numpy array
    And query with query_text as physics research
    When optimize_wikipedia_query is called
    Then category hierarchy is leveraged

  Scenario: Optimize query applies category hierarchy hierarchical relationships are prioritized
    Given query with query_vector as numpy array
    And query with query_text as physics research
    When optimize_wikipedia_query is called
    Then hierarchical relationships are prioritized


  Scenario: Optimize query applies entity importance entity importance calculations are used
    Given query with query_vector as numpy array
    And graph_processor with entity data
    When optimize_wikipedia_query is called with graph_processor
    Then entity importance calculations are used

  Scenario: Optimize query applies entity importance important entities are prioritized
    Given query with query_vector as numpy array
    And graph_processor with entity data
    When optimize_wikipedia_query is called with graph_processor
    Then important entities are prioritized


  Scenario: Optimize query expands query query expansion is performed
    Given query with query_vector as numpy array
    And query with query_text as quantum physics
    And vector_store instance
    When optimize_wikipedia_query is called with vector_store
    Then query expansion is performed

  Scenario: Optimize query expands query result contains expansions with topics
    Given query with query_vector as numpy array
    And query with query_text as quantum physics
    And vector_store instance
    When optimize_wikipedia_query is called with vector_store
    Then result contains expansions with topics

  Scenario: Optimize query expands query result contains expansions with categories
    Given query with query_vector as numpy array
    And query with query_text as quantum physics
    And vector_store instance
    When optimize_wikipedia_query is called with vector_store
    Then result contains expansions with categories


  Scenario: Optimize query without query_text query is optimized without expansion
    Given query with query_vector as numpy array
    And no query_text
    When optimize_wikipedia_query is called
    Then query is optimized without expansion

  Scenario: Optimize query without query_text result contains query
    Given query with query_vector as numpy array
    And no query_text
    When optimize_wikipedia_query is called
    Then result contains query

  Scenario: Optimize query without query_text result contains budget
    Given query with query_vector as numpy array
    And no query_text
    When optimize_wikipedia_query is called
    Then result contains budget

