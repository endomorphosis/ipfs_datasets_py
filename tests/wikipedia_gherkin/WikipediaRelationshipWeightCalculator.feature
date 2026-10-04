Feature: WikipediaRelationshipWeightCalculator
  This feature file describes the WikipediaRelationshipWeightCalculator callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Background:
    Given a WikipediaRelationshipWeightCalculator instance

  Scenario: Initialize calculator with default weights for subclass_of
    When the calculator is initialized without custom weights
    Then the calculator has default weights for subclass_of as 1.5


  Scenario: Initialize calculator with default weights for instance_of
    When the calculator is initialized without custom weights
    Then the calculator has default weights for instance_of as 1.4


  Scenario: Initialize calculator with default weights for mentions
    When the calculator is initialized without custom weights
    Then the calculator has default weights for mentions as 0.5


  Scenario: Initialize calculator with custom weight for custom_relation
    When the calculator is initialized with custom weight for custom_relation as 2.0
    Then the calculator has weight for custom_relation as 2.0


  Scenario: Initialize calculator with custom weights preserves defaults
    When the calculator is initialized with custom weight for custom_relation as 2.0
    Then the calculator has default weights for subclass_of as 1.5


  Scenario: Get weight for known relationship type
    When get_relationship_weight is called with subclass_of
    Then the returned weight is 1.5


  Scenario: Get weight for unknown relationship type
    When get_relationship_weight is called with unknown_type
    Then the returned weight is 0.5


  Scenario: Get weight with normalized relationship type
    When get_relationship_weight is called with Is Subclass Of
    Then the returned weight is 1.5


  Scenario: Prioritize relationship types first is subclass_of
    Given relationship types mentions, subclass_of, instance_of, related_to
    When get_prioritized_relationship_types is called
    Then the first type in result is subclass_of


  Scenario: Prioritize relationship types second is instance_of
    Given relationship types mentions, subclass_of, instance_of, related_to
    When get_prioritized_relationship_types is called
    Then the second type in result is instance_of


  Scenario: Prioritize relationship types third is related_to
    Given relationship types mentions, subclass_of, instance_of, related_to
    When get_prioritized_relationship_types is called
    Then the third type in result is related_to


  Scenario: Prioritize relationship types fourth is mentions
    Given relationship types mentions, subclass_of, instance_of, related_to
    When get_prioritized_relationship_types is called
    Then the fourth type in result is mentions


  Scenario: Filter high value relationships with threshold 0.8 includes subclass_of
    Given relationship types subclass_of, mentions, instance_of, related_to
    When get_filtered_high_value_relationships is called with min_weight 0.8
    Then the result contains subclass_of


  Scenario: Filter high value relationships with threshold 0.8 includes instance_of
    Given relationship types subclass_of, mentions, instance_of, related_to
    When get_filtered_high_value_relationships is called with min_weight 0.8
    Then the result contains instance_of


  Scenario: Filter high value relationships with threshold 0.8 excludes mentions
    Given relationship types subclass_of, mentions, instance_of, related_to
    When get_filtered_high_value_relationships is called with min_weight 0.8
    Then the result does not contain mentions


  Scenario: Filter high value relationships with threshold 0.8 excludes related_to
    Given relationship types subclass_of, mentions, instance_of, related_to
    When get_filtered_high_value_relationships is called with min_weight 0.8
    Then the result does not contain related_to


  Scenario: Filter high value relationships with threshold 0.5 includes subclass_of
    Given relationship types subclass_of, mentions, instance_of
    When get_filtered_high_value_relationships is called with min_weight 0.5
    Then the result contains subclass_of


  Scenario: Filter high value relationships with threshold 0.5 includes instance_of
    Given relationship types subclass_of, mentions, instance_of
    When get_filtered_high_value_relationships is called with min_weight 0.5
    Then the result contains instance_of


  Scenario: Filter high value relationships with threshold 0.5 excludes mentions
    Given relationship types subclass_of, mentions, instance_of
    When get_filtered_high_value_relationships is called with min_weight 0.5
    Then the result does not contain mentions


  Scenario: Normalize relationship type with is_ prefix
    When _normalize_relationship_type is called with is_subclass_of
    Then the result is subclass_of


  Scenario: Normalize relationship type with spaces
    When _normalize_relationship_type is called with Instance Of
    Then the result is instance_of


  Scenario: Normalize relationship type with hyphens
    When _normalize_relationship_type is called with related-to
    Then the result is related_to
