Feature: WikipediaEntityImportanceCalculator
  This feature file describes the WikipediaEntityImportanceCalculator callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Background:
    Given a WikipediaEntityImportanceCalculator instance

  Scenario: Initialize with default configuration
    When the calculator is initialized
    Then entity_importance_cache is empty
    And feature_weights contains connection_count as 0.3
    And feature_weights contains reference_count as 0.2
    And feature_weights contains category_importance as 0.2
    And feature_weights contains explicitness as 0.15
    And feature_weights contains recency as 0.15

  Scenario: Calculate importance for entity with connections
    Given entity_data with id entity_1
    And entity_data with 3 inbound_connections
    And entity_data with 2 outbound_connections
    When calculate_entity_importance is called
    Then importance score is between 0.0 and 1.0
    And importance score reflects connection count

  Scenario: Calculate importance for entity with references
    Given entity_data with id entity_1
    And entity_data with 5 references
    When calculate_entity_importance is called
    Then importance score is between 0.0 and 1.0
    And importance score reflects reference count

  Scenario: Calculate importance with category weights
    Given entity_data with id entity_1
    And entity_data with categories Physics, Chemistry
    And category_weights with Physics as 0.9 and Chemistry as 0.8
    When calculate_entity_importance is called with category_weights
    Then importance score reflects category importance
    And importance score is between 0.0 and 1.0

  Scenario: Calculate importance with mention count
    Given entity_data with id entity_1
    And entity_data with mention_count as 25
    When calculate_entity_importance is called
    Then importance score reflects explicitness
    And importance score is between 0.0 and 1.0

  Scenario: Calculate importance with recency
    Given entity_data with id entity_1
    And entity_data with last_modified as 1693958400.0
    When calculate_entity_importance is called
    Then importance score reflects recency
    And importance score is between 0.0 and 1.0

  Scenario: Calculate importance uses cache
    Given entity_data with id entity_1
    And calculate_entity_importance is called once
    When calculate_entity_importance is called with same entity_id
    Then result is retrieved from cache

  Scenario: Calculate importance for entity without optional fields
    Given entity_data with id entity_1
    When calculate_entity_importance is called
    Then importance score is between 0.0 and 1.0
    And default values are used for missing fields

  Scenario: Rank entities by importance
    Given entities list with entity_1, entity_2, entity_3
    And entity_1 has 5 inbound_connections
    And entity_2 has 2 inbound_connections
    And entity_3 has 8 inbound_connections
    When rank_entities_by_importance is called
    Then first entity in result is entity_3
    And second entity in result is entity_1
    And third entity in result is entity_2

  Scenario: Rank entities with category weights
    Given entities list with entity_1, entity_2
    And entity_1 has categories Physics with weight 0.9
    And entity_2 has categories Chemistry with weight 0.5
    And category_weights provided
    When rank_entities_by_importance is called with category_weights
    Then entities are ranked by importance with category consideration

  Scenario: Rank empty entities list
    Given entities list is empty
    When rank_entities_by_importance is called
    Then result is empty list
