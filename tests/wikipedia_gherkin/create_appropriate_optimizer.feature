Feature: create_appropriate_optimizer
  This feature file describes the create_appropriate_optimizer callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Scenario: Create optimizer with Wikipedia graph type
    Given graph_type as wikipedia
    When create_appropriate_optimizer is called
    Then result is UnifiedWikipediaGraphRAGQueryOptimizer

  Scenario: Create optimizer with unknown graph type
    Given graph_type as unknown
    When create_appropriate_optimizer is called
    Then result is UnifiedGraphRAGQueryOptimizer

  Scenario: Create optimizer with IPLD graph type
    Given graph_type as ipld
    When create_appropriate_optimizer is called
    Then result is UnifiedGraphRAGQueryOptimizer

  Scenario: Create optimizer with automatic detection
    Given graph_processor with wikipedia characteristics
    And no graph_type specified
    When create_appropriate_optimizer is called with graph_processor
    Then graph_type is detected as wikipedia
    And result is UnifiedWikipediaGraphRAGQueryOptimizer

  Scenario: Create optimizer with metrics collector
    Given graph_type as wikipedia
    And metrics_collector instance
    When create_appropriate_optimizer is called with metrics_collector
    Then result has metrics_collector set
    And result is UnifiedWikipediaGraphRAGQueryOptimizer

  Scenario: Create optimizer with tracer
    Given graph_type as wikipedia
    And tracer instance
    When create_appropriate_optimizer is called with tracer
    Then result has tracer set
    And result is UnifiedWikipediaGraphRAGQueryOptimizer

  Scenario: Create optimizer with all parameters
    Given graph_processor with wikipedia characteristics
    And metrics_collector instance
    And tracer instance
    When create_appropriate_optimizer is called with all parameters
    Then result is UnifiedWikipediaGraphRAGQueryOptimizer
    And result has metrics_collector set
    And result has tracer set

  Scenario: Create optimizer without graph_processor or graph_type
    Given no graph_processor
    And no graph_type
    When create_appropriate_optimizer is called
    Then graph_type defaults to unknown
    And result is UnifiedGraphRAGQueryOptimizer

  Scenario: Create optimizer with explicit Wikipedia overrides detection
    Given graph_processor with ipld characteristics
    And graph_type as wikipedia
    When create_appropriate_optimizer is called
    Then result is UnifiedWikipediaGraphRAGQueryOptimizer
    And automatic detection is not used
