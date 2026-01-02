Feature: WikipediaRAGQueryOptimizer
  This feature file describes the WikipediaRAGQueryOptimizer callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Background:
    Given a WikipediaRAGQueryOptimizer instance

  Scenario: Initialize with default parameters relationship_calculator is set
    When the optimizer is initialized
    Then relationship_calculator is set

  Scenario: Initialize with default parameters category_hierarchy is set
    When the optimizer is initialized
    Then category_hierarchy is set

  Scenario: Initialize with default parameters entity_importance is set
    When the optimizer is initialized
    Then entity_importance is set

  Scenario: Initialize with default parameters query_expander is set
    When the optimizer is initialized
    Then query_expander is set

  Scenario: Initialize with default parameters path_optimizer is set
    When the optimizer is initialized
    Then path_optimizer is set

  Scenario: Initialize with default parameters optimization_history is empty
    When the optimizer is initialized
    Then optimization_history is empty


  Scenario: Initialize with custom weights vector_weight is 0.8
    When the optimizer is initialized with vector_weight 0.8 and graph_weight 0.2
    Then vector_weight is 0.8

  Scenario: Initialize with custom weights graph_weight is 0.2
    When the optimizer is initialized with vector_weight 0.8 and graph_weight 0.2
    Then graph_weight is 0.2


  Scenario: Initialize with tracer tracer is set in optimizer
    Given a WikipediaKnowledgeGraphTracer instance
    When the optimizer is initialized with tracer
    Then tracer is set in optimizer

  Scenario: Initialize with tracer tracer is set in query_expander
    Given a WikipediaKnowledgeGraphTracer instance
    When the optimizer is initialized with tracer
    Then tracer is set in query_expander


  Scenario: Optimize query with basic parameters result contains query with vector_params
    Given query_vector as numpy array
    And max_vector_results as 5
    And max_traversal_depth as 2
    When optimize_query is called
    Then result contains query with vector_params

  Scenario: Optimize query with basic parameters result contains query with traversal
    Given query_vector as numpy array
    And max_vector_results as 5
    And max_traversal_depth as 2
    When optimize_query is called
    Then result contains query with traversal

  Scenario: Optimize query with basic parameters result contains weights
    Given query_vector as numpy array
    And max_vector_results as 5
    And max_traversal_depth as 2
    When optimize_query is called
    Then result contains weights

  Scenario: Optimize query with basic parameters query traversal strategy is wikipedia_hierarchical
    Given query_vector as numpy array
    And max_vector_results as 5
    And max_traversal_depth as 2
    When optimize_query is called
    Then query traversal strategy is wikipedia_hierarchical


  Scenario: Optimize query prioritizes edge types query traversal edge_types first item is subclass_of
    Given query_vector as numpy array
    And edge_types as mentions, subclass_of, instance_of
    When optimize_query is called
    Then query traversal edge_types first item is subclass_of

  Scenario: Optimize query prioritizes edge types query traversal edge_types second item is instance_of
    Given query_vector as numpy array
    And edge_types as mentions, subclass_of, instance_of
    When optimize_query is called
    Then query traversal edge_types second item is instance_of

  Scenario: Optimize query prioritizes edge types query traversal edge_types third item is mentions
    Given query_vector as numpy array
    And edge_types as mentions, subclass_of, instance_of
    When optimize_query is called
    Then query traversal edge_types third item is mentions


  Scenario: Optimize query with query text expands query expansions are included in result
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store with search capability
    When optimize_query is called
    Then expansions are included in result

  Scenario: Optimize query with query text expands query expansions contain topics or categories
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store with search capability
    When optimize_query is called
    Then expansions contain topics or categories


  Scenario: Optimize query without query text
    Given query_vector as numpy array
    And no query_text
    When optimize_query is called
    Then expansions is None


  Scenario: Optimize query calculates relationship depths query traversal relationship_depths contains subclass_of
    Given query_vector as numpy array
    And edge_types as subclass_of, mentions, related_to
    And max_traversal_depth as 3
    When optimize_query is called
    Then query traversal relationship_depths contains subclass_of

  Scenario: Optimize query calculates relationship depths relationship_depths for subclass_of is 3
    Given query_vector as numpy array
    And edge_types as subclass_of, mentions, related_to
    And max_traversal_depth as 3
    When optimize_query is called
    Then relationship_depths for subclass_of is 3

  Scenario: Optimize query calculates relationship depths relationship_depths for mentions is less than 3
    Given query_vector as numpy array
    And edge_types as subclass_of, mentions, related_to
    And max_traversal_depth as 3
    When optimize_query is called
    Then relationship_depths for mentions is less than 3


  Scenario: Optimize query with trace_id logs optimization
    Given query_vector as numpy array
    And tracer is set
    And trace_id as opt_001
    When optimize_query is called with trace_id
    Then tracer logs optimization with trace_id


  Scenario: Optimize query records optimization history optimization_history has 1 entry
    Given query_vector as numpy array
    When optimize_query is called
    Then optimization_history has 1 entry

  Scenario: Optimize query records optimization history history entry contains timestamp
    Given query_vector as numpy array
    When optimize_query is called
    Then history entry contains timestamp

  Scenario: Optimize query records optimization history history entry contains input_params
    Given query_vector as numpy array
    When optimize_query is called
    Then history entry contains input_params

  Scenario: Optimize query records optimization history history entry contains optimized_plan
    Given query_vector as numpy array
    When optimize_query is called
    Then history entry contains optimized_plan


  Scenario: Optimize query uses default edge types query traversal edge_types includes subclass_of
    Given query_vector as numpy array
    And no edge_types provided
    When optimize_query is called
    Then query traversal edge_types includes subclass_of

  Scenario: Optimize query uses default edge types query traversal edge_types includes instance_of
    Given query_vector as numpy array
    And no edge_types provided
    When optimize_query is called
    Then query traversal edge_types includes instance_of

  Scenario: Optimize query uses default edge types query traversal edge_types includes category_contains
    Given query_vector as numpy array
    And no edge_types provided
    When optimize_query is called
    Then query traversal edge_types includes category_contains


  Scenario: Calculate entity importance for entity
    Given entity_id as quantum_entanglement
    And graph_processor with entity data
    When calculate_entity_importance is called
    Then importance score is between 0.0 and 1.0


  Scenario: Calculate entity importance without graph processor importance score is between 0.0 and 1.0
    Given entity_id as test_entity
    And no graph_processor
    When calculate_entity_importance is called
    Then importance score is between 0.0 and 1.0

  Scenario: Calculate entity importance without graph processor default entity data is used
    Given entity_id as test_entity
    And no graph_processor
    When calculate_entity_importance is called
    Then default entity data is used


  Scenario: Learn from query results updates weights relationship weights are adjusted
    Given query_id as learn_001
    And results with 2 items
    And results contain path with edge_type subclass_of
    And time_taken as 1.25
    And plan with traversal edge_types
    When learn_from_query_results is called
    Then relationship weights are adjusted

  Scenario: Learn from query results updates weights query time is recorded
    Given query_id as learn_001
    And results with 2 items
    And results contain path with edge_type subclass_of
    And time_taken as 1.25
    And plan with traversal edge_types
    When learn_from_query_results is called
    Then query time is recorded

  Scenario: Learn from query results updates weights query pattern is recorded
    Given query_id as learn_001
    And results with 2 items
    And results contain path with edge_type subclass_of
    And time_taken as 1.25
    And plan with traversal edge_types
    When learn_from_query_results is called
    Then query pattern is recorded


  Scenario: Learn from query results analyzes edge effectiveness weight adjustment for subclass_of is positive
    Given query_id as learn_002
    And results with path containing subclass_of 3 times
    And results with path containing mentions 1 time
    And time_taken as 0.8
    And plan with traversal edge_types
    When learn_from_query_results is called
    Then weight adjustment for subclass_of is positive

  Scenario: Learn from query results analyzes edge effectiveness weight adjustment for mentions may be negative
    Given query_id as learn_002
    And results with path containing subclass_of 3 times
    And results with path containing mentions 1 time
    And time_taken as 0.8
    And plan with traversal edge_types
    When learn_from_query_results is called
    Then weight adjustment for mentions may be negative


  Scenario: Learn from query results with no results weights are adjusted with avg_score 0
    Given query_id as learn_003
    And empty results list
    And time_taken as 2.0
    And plan with traversal edge_types
    When learn_from_query_results is called
    Then weights are adjusted with avg_score 0

  Scenario: Learn from query results with no results query statistics are recorded
    Given query_id as learn_003
    And empty results list
    And time_taken as 2.0
    And plan with traversal edge_types
    When learn_from_query_results is called
    Then query statistics are recorded

