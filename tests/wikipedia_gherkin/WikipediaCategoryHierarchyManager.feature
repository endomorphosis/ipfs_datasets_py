Feature: WikipediaCategoryHierarchyManager
  This feature file describes the WikipediaCategoryHierarchyManager callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Background:
    Given a WikipediaCategoryHierarchyManager instance

  Scenario: Initialize with empty structures
    When the manager is initialized
    Then category_depth_cache is empty
    And category_specificity is empty
    And category_connections is empty

  Scenario: Register single category connection
    When register_category_connection is called with parent Science and child Physics
    Then category_connections contains Science with child Physics

  Scenario: Register multiple connections for same parent
    When register_category_connection is called with parent Science and child Physics
    And register_category_connection is called with parent Science and child Chemistry
    Then category_connections contains Science with child Physics
    And category_connections contains Science with child Chemistry

  Scenario: Calculate depth for root category
    Given register_category_connection is called with parent Science and child Physics
    When calculate_category_depth is called with Science
    Then the depth is 0

  Scenario: Calculate depth for child category
    Given register_category_connection is called with parent Science and child Physics
    When calculate_category_depth is called with Physics
    Then the depth is 1

  Scenario: Calculate depth for nested category
    Given register_category_connection is called with parent Knowledge and child Science
    And register_category_connection is called with parent Science and child Physics
    And register_category_connection is called with parent Physics and child Quantum Physics
    When calculate_category_depth is called with Quantum Physics
    Then the depth is 3

  Scenario: Calculate depth with cycle detection
    Given register_category_connection is called with parent A and child B
    And register_category_connection is called with parent B and child C
    And register_category_connection is called with parent C and child A
    When calculate_category_depth is called with A
    Then the depth is 0

  Scenario: Calculate depth uses cache
    Given register_category_connection is called with parent Science and child Physics
    And calculate_category_depth is called with Physics
    When calculate_category_depth is called with Physics
    Then the result is retrieved from cache

  Scenario: Assign category weights with depth scores
    Given register_category_connection is called with parent Science and child Physics
    And categories list with Physics, Chemistry
    When assign_category_weights is called with query_vector and categories
    Then weights contains Physics
    And weights contains Chemistry
    And weight for Physics is between 0.5 and 1.5

  Scenario: Assign category weights with similarity scores
    Given categories list with Physics, Chemistry
    And similarity scores with Physics as 0.9 and Chemistry as 0.7
    When assign_category_weights is called with query_vector, categories and similarity_scores
    Then weight for Physics reflects similarity 0.9
    And weight for Chemistry reflects similarity 0.7

  Scenario: Get related categories at distance 1
    Given register_category_connection is called with parent Science and child Physics
    And register_category_connection is called with parent Physics and child Quantum Physics
    When get_related_categories is called with Physics and max_distance 1
    Then result contains Quantum Physics with distance 1
    And result contains Science with distance 1

  Scenario: Get related categories at distance 2
    Given register_category_connection is called with parent Knowledge and child Science
    And register_category_connection is called with parent Science and child Physics
    And register_category_connection is called with parent Physics and child Quantum Physics
    When get_related_categories is called with Physics and max_distance 2
    Then result contains Quantum Physics with distance 1
    And result contains Science with distance 1
    And result contains Knowledge with distance 2

  Scenario: Get related categories excludes source
    Given register_category_connection is called with parent Science and child Physics
    When get_related_categories is called with Physics and max_distance 1
    Then result does not contain Physics
