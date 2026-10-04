Feature: WikipediaGraphRAGBudgetManager
  This feature file describes the WikipediaGraphRAGBudgetManager callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Background:
    Given a WikipediaGraphRAGBudgetManager instance

  Scenario: Initialize with default budget default_budget contains category_traversal_ms as 5000
    When the manager is initialized
    Then default_budget contains category_traversal_ms as 5000

  Scenario: Initialize with default budget default_budget contains topic_expansion_ms as 3000
    When the manager is initialized
    Then default_budget contains topic_expansion_ms as 3000

  Scenario: Initialize with default budget default_budget contains max_categories as 20
    When the manager is initialized
    Then default_budget contains max_categories as 20

  Scenario: Initialize with default budget default_budget contains max_topics as 15
    When the manager is initialized
    Then default_budget contains max_topics as 15


  Scenario: Allocate budget for normal priority budget contains category_traversal_ms
    Given query with traversal strategy as wikipedia_hierarchical
    When allocate_budget is called with priority normal
    Then budget contains category_traversal_ms

  Scenario: Allocate budget for normal priority budget contains topic_expansion_ms
    Given query with traversal strategy as wikipedia_hierarchical
    When allocate_budget is called with priority normal
    Then budget contains topic_expansion_ms

  Scenario: Allocate budget for normal priority budget contains max_categories
    Given query with traversal strategy as wikipedia_hierarchical
    When allocate_budget is called with priority normal
    Then budget contains max_categories

  Scenario: Allocate budget for normal priority budget contains max_topics
    Given query with traversal strategy as wikipedia_hierarchical
    When allocate_budget is called with priority normal
    Then budget contains max_topics


  Scenario: Allocate budget with category focus category_traversal_ms is increased by factor 1.5
    Given query with traversal edge_types including category_contains
    When allocate_budget is called
    Then category_traversal_ms is increased by factor 1.5

  Scenario: Allocate budget with category focus max_categories is increased by factor 1.5
    Given query with traversal edge_types including category_contains
    When allocate_budget is called
    Then max_categories is increased by factor 1.5


  Scenario: Allocate budget with topic expansion topic_expansion_ms is increased by factor 1.5
    Given query with traversal expand_topics as True
    And query with traversal topic_expansion_factor as 1.5
    When allocate_budget is called
    Then topic_expansion_ms is increased by factor 1.5

  Scenario: Allocate budget with topic expansion max_topics is increased by factor 1.5
    Given query with traversal expand_topics as True
    And query with traversal topic_expansion_factor as 1.5
    When allocate_budget is called
    Then max_topics is increased by factor 1.5


  Scenario: Allocate budget for hierarchical strategy graph_traversal_ms is increased by factor 1.3
    Given query with traversal strategy as wikipedia_hierarchical
    When allocate_budget is called
    Then graph_traversal_ms is increased by factor 1.3

  Scenario: Allocate budget for hierarchical strategy max_nodes is increased by factor 1.3
    Given query with traversal strategy as wikipedia_hierarchical
    When allocate_budget is called
    Then max_nodes is increased by factor 1.3


  Scenario: Allocate budget for topic focused strategy
    Given query with traversal strategy as topic_focused
    When allocate_budget is called
    Then vector_search_ms is increased by factor 1.4


  Scenario: Allocate budget for comparison strategy vector_search_ms is increased by factor 1.2
    Given query with traversal strategy as comparison
    When allocate_budget is called
    Then vector_search_ms is increased by factor 1.2

  Scenario: Allocate budget for comparison strategy graph_traversal_ms is increased by factor 1.2
    Given query with traversal strategy as comparison
    When allocate_budget is called
    Then graph_traversal_ms is increased by factor 1.2


  Scenario: Allocate budget with high priority
    Given query with traversal strategy as wikipedia_hierarchical
    When allocate_budget is called with priority high
    Then budget values are higher than normal priority


  Scenario: Allocate budget with low priority
    Given query with traversal strategy as wikipedia_hierarchical
    When allocate_budget is called with priority low
    Then budget values are lower than normal priority


  Scenario: Suggest early stopping with good category matches
    Given results with 5 items
    And 3 results with type category and score 0.9
    And budget_consumed_ratio as 0.7
    When suggest_early_stopping is called
    Then result is True


  Scenario: Suggest early stopping with insufficient category matches
    Given results with 5 items
    And 2 results with type category and score 0.9
    And budget_consumed_ratio as 0.7
    When suggest_early_stopping is called
    Then result is False


  Scenario: Suggest early stopping with low budget consumption
    Given results with 5 items
    And 3 results with type category and score 0.9
    And budget_consumed_ratio as 0.4
    When suggest_early_stopping is called
    Then result is False


  Scenario: Suggest early stopping with duplicate categories
    Given results with 15 items
    And results have 4 unique categories
    And budget_consumed_ratio as 0.8
    When suggest_early_stopping is called
    Then result is True


  Scenario: Suggest early stopping with diverse categories
    Given results with 15 items
    And results have 10 unique categories
    And budget_consumed_ratio as 0.8
    When suggest_early_stopping is called
    Then result is False


  Scenario: Suggest early stopping with empty results
    Given results with 0 items
    And budget_consumed_ratio as 0.5
    When suggest_early_stopping is called
    Then result is based on base class logic
