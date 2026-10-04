Feature: WikipediaPathOptimizer
  This feature file describes the WikipediaPathOptimizer callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Background:
    Given a WikipediaPathOptimizer instance

  Scenario: Initialize with default configuration relationship_calculator is set
    When the optimizer is initialized
    Then relationship_calculator is set

  Scenario: Initialize with default configuration traversal_costs contains subclass_of as 0.6
    When the optimizer is initialized
    Then traversal_costs contains subclass_of as 0.6

  Scenario: Initialize with default configuration traversal_costs contains instance_of as 0.6
    When the optimizer is initialized
    Then traversal_costs contains instance_of as 0.6

  Scenario: Initialize with default configuration traversal_costs contains mentions as 1.5
    When the optimizer is initialized
    Then traversal_costs contains mentions as 1.5

  Scenario: Initialize with default configuration traversal_costs contains default as 1.0
    When the optimizer is initialized
    Then traversal_costs contains default as 1.0


  Scenario: Get edge traversal cost for known type
    When get_edge_traversal_cost is called with subclass_of
    Then the cost is 0.6


  Scenario: Get edge traversal cost for unknown type
    When get_edge_traversal_cost is called with unknown_type
    Then the cost is 1.0


  Scenario: Get edge traversal cost with normalization
    When get_edge_traversal_cost is called with Instance Of
    Then the cost is 0.6


  Scenario: Optimize traversal path with basic parameters result contains strategy as wikipedia_hierarchical
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of, instance_of, mentions
    And max_depth as 3
    And budget with max_nodes as 1000
    When optimize_traversal_path is called
    Then result contains strategy as wikipedia_hierarchical

  Scenario: Optimize traversal path with basic parameters result contains relationship_priority
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of, instance_of, mentions
    And max_depth as 3
    And budget with max_nodes as 1000
    When optimize_traversal_path is called
    Then result contains relationship_priority

  Scenario: Optimize traversal path with basic parameters result contains level_budgets
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of, instance_of, mentions
    And max_depth as 3
    And budget with max_nodes as 1000
    When optimize_traversal_path is called
    Then result contains level_budgets

  Scenario: Optimize traversal path with basic parameters result contains relationship_activation
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of, instance_of, mentions
    And max_depth as 3
    And budget with max_nodes as 1000
    When optimize_traversal_path is called
    Then result contains relationship_activation

  Scenario: Optimize traversal path with basic parameters result contains traversal_costs
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of, instance_of, mentions
    And max_depth as 3
    And budget with max_nodes as 1000
    When optimize_traversal_path is called
    Then result contains traversal_costs

  Scenario: Optimize traversal path with basic parameters result contains original_max_depth as 3
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of, instance_of, mentions
    And max_depth as 3
    And budget with max_nodes as 1000
    When optimize_traversal_path is called
    Then result contains original_max_depth as 3


  Scenario: Optimize traversal prioritizes relationships relationship_priority first item is subclass_of
    Given start_entities list with 1 entity
    And relationship_types list with mentions, subclass_of, instance_of
    And max_depth as 2
    And budget with max_nodes as 500
    When optimize_traversal_path is called
    Then relationship_priority first item is subclass_of

  Scenario: Optimize traversal prioritizes relationships relationship_priority second item is instance_of
    Given start_entities list with 1 entity
    And relationship_types list with mentions, subclass_of, instance_of
    And max_depth as 2
    And budget with max_nodes as 500
    When optimize_traversal_path is called
    Then relationship_priority second item is instance_of

  Scenario: Optimize traversal prioritizes relationships relationship_priority third item is mentions
    Given start_entities list with 1 entity
    And relationship_types list with mentions, subclass_of, instance_of
    And max_depth as 2
    And budget with max_nodes as 500
    When optimize_traversal_path is called
    Then relationship_priority third item is mentions


  Scenario: Optimize traversal allocates budget by level level_budgets has 3 items
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of
    And max_depth as 3
    And budget with max_nodes as 1000
    When optimize_traversal_path is called
    Then level_budgets has 3 items

  Scenario: Optimize traversal allocates budget by level level_budgets first item is largest
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of
    And max_depth as 3
    And budget with max_nodes as 1000
    When optimize_traversal_path is called
    Then level_budgets first item is largest

  Scenario: Optimize traversal allocates budget by level level_budgets uses exponential decay
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of
    And max_depth as 3
    And budget with max_nodes as 1000
    When optimize_traversal_path is called
    Then level_budgets uses exponential decay


  Scenario: Optimize traversal sets relationship activation depths relationship_activation for subclass_of is 3
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of, instance_of, mentions
    And max_depth as 3
    And budget with max_nodes as 1000
    When optimize_traversal_path is called
    Then relationship_activation for subclass_of is 3

  Scenario: Optimize traversal sets relationship activation depths relationship_activation for mentions is at most 2
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of, instance_of, mentions
    And max_depth as 3
    And budget with max_nodes as 1000
    When optimize_traversal_path is called
    Then relationship_activation for mentions is at most 2


  Scenario: Optimize traversal with single depth level_budgets has 1 item
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of
    And max_depth as 1
    And budget with max_nodes as 100
    When optimize_traversal_path is called
    Then level_budgets has 1 item

  Scenario: Optimize traversal with single depth relationship_activation for subclass_of is 1
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of
    And max_depth as 1
    And budget with max_nodes as 100
    When optimize_traversal_path is called
    Then relationship_activation for subclass_of is 1


  Scenario: Optimize traversal calculates costs for all types traversal_costs contains subclass_of
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of, mentions, related_to
    And max_depth as 2
    And budget with max_nodes as 500
    When optimize_traversal_path is called
    Then traversal_costs contains subclass_of

  Scenario: Optimize traversal calculates costs for all types traversal_costs contains mentions
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of, mentions, related_to
    And max_depth as 2
    And budget with max_nodes as 500
    When optimize_traversal_path is called
    Then traversal_costs contains mentions

  Scenario: Optimize traversal calculates costs for all types traversal_costs contains related_to
    Given start_entities list with 1 entity
    And relationship_types list with subclass_of, mentions, related_to
    And max_depth as 2
    And budget with max_nodes as 500
    When optimize_traversal_path is called
    Then traversal_costs contains related_to

