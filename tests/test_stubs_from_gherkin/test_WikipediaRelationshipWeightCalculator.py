"""
Test stubs for WikipediaRelationshipWeightCalculator

This feature file describes the WikipediaRelationshipWeightCalculator callable
from ipfs_datasets_py.wikipedia_rag_optimizer module.
"""

import pytest
from ipfs_datasets_py.wikipedia_rag_optimizer import WikipediaRelationshipWeightCalculator
from conftest import FixtureError


@pytest.fixture
def wikipediarelationshipweightcalculator_instance():
    """
    a WikipediaRelationshipWeightCalculator instance
    """
    try:
        instance = WikipediaRelationshipWeightCalculator()
        if instance is None:
            raise FixtureError("Failed to create WikipediaRelationshipWeightCalculator instance: instance is None")
        return instance
    except Exception as e:
        raise FixtureError(f"Failed to create fixture wikipediarelationshipweightcalculator_instance: {e}") from e


def test_initialize_calculator_with_default_weights_for_subclass_of(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Initialize calculator with default weights for subclass_of

    When:
        the calculator is initialized without custom weights

    Then:
        the calculator has default weights for subclass_of as 1.5
    """
    # Given: wikipediarelationshipweightcalculator_instance from fixture
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_type = "subclass_of"
    expected_weight = 1.5
    
    # When: the calculator is initialized without custom weights (done in fixture)
    actual_weight = calculator.get_relationship_weight(relationship_type)
    
    # Then: the calculator has default weights for subclass_of as 1.5
    assert actual_weight == expected_weight, f"expected {expected_weight}, got {actual_weight}"


def test_initialize_calculator_with_default_weights_for_instance_of(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Initialize calculator with default weights for instance_of

    When:
        the calculator is initialized without custom weights

    Then:
        the calculator has default weights for instance_of as 1.4
    """
    # Given: wikipediarelationshipweightcalculator_instance from fixture
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_type = "instance_of"
    expected_weight = 1.4
    
    # When: the calculator is initialized without custom weights (done in fixture)
    actual_weight = calculator.get_relationship_weight(relationship_type)
    
    # Then: the calculator has default weights for instance_of as 1.4
    assert actual_weight == expected_weight, f"expected {expected_weight}, got {actual_weight}"


def test_initialize_calculator_with_default_weights_for_mentions(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Initialize calculator with default weights for mentions

    When:
        the calculator is initialized without custom weights

    Then:
        the calculator has default weights for mentions as 0.5
    """
    # Given: wikipediarelationshipweightcalculator_instance from fixture
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_type = "mentions"
    expected_weight = 0.5
    
    # When: the calculator is initialized without custom weights (done in fixture)
    actual_weight = calculator.get_relationship_weight(relationship_type)
    
    # Then: the calculator has default weights for mentions as 0.5
    assert actual_weight == expected_weight, f"expected {expected_weight}, got {actual_weight}"


def test_initialize_calculator_with_custom_weight_for_custom_relation(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Initialize calculator with custom weight for custom_relation

    When:
        the calculator is initialized with custom weight for custom_relation as 2.0

    Then:
        the calculator has weight for custom_relation as 2.0
    """
    custom_weights = {"custom_relation": 2.0}
    relationship_type = "custom_relation"
    expected_weight = 2.0
    
    # When: the calculator is initialized with custom weight
    calculator = WikipediaRelationshipWeightCalculator(custom_weights)
    actual_weight = calculator.get_relationship_weight(relationship_type)
    
    # Then: the calculator has weight for custom_relation as 2.0
    assert actual_weight == expected_weight, f"expected {expected_weight}, got {actual_weight}"


def test_initialize_calculator_with_custom_weights_preserves_defaults(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Initialize calculator with custom weights preserves defaults

    When:
        the calculator is initialized with custom weight for custom_relation as 2.0

    Then:
        the calculator has default weights for subclass_of as 1.5
    """
    custom_weights = {"custom_relation": 2.0}
    relationship_type = "subclass_of"
    expected_weight = 1.5
    
    # When: the calculator is initialized with custom weight
    calculator = WikipediaRelationshipWeightCalculator(custom_weights)
    actual_weight = calculator.get_relationship_weight(relationship_type)
    
    # Then: the calculator has default weights for subclass_of as 1.5
    assert actual_weight == expected_weight, f"expected {expected_weight}, got {actual_weight}"


def test_get_weight_for_known_relationship_type(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Get weight for known relationship type

    When:
        get_relationship_weight is called with subclass_of

    Then:
        the returned weight is 1.5
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_type = "subclass_of"
    expected_weight = 1.5
    
    # When: get_relationship_weight is called with subclass_of
    actual_weight = calculator.get_relationship_weight(relationship_type)
    
    # Then: the returned weight is 1.5
    assert actual_weight == expected_weight, f"expected {expected_weight}, got {actual_weight}"


def test_get_weight_for_unknown_relationship_type(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Get weight for unknown relationship type

    When:
        get_relationship_weight is called with unknown_type

    Then:
        the returned weight is 0.5
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_type = "unknown_type"
    expected_weight = 0.5
    
    # When: get_relationship_weight is called with unknown_type
    actual_weight = calculator.get_relationship_weight(relationship_type)
    
    # Then: the returned weight is 0.5
    assert actual_weight == expected_weight, f"expected {expected_weight}, got {actual_weight}"


def test_get_weight_with_normalized_relationship_type(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Get weight with normalized relationship type

    When:
        get_relationship_weight is called with Is Subclass Of

    Then:
        the returned weight is 1.5
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_type = "Is Subclass Of"
    expected_weight = 1.5
    
    # When: get_relationship_weight is called with Is Subclass Of
    actual_weight = calculator.get_relationship_weight(relationship_type)
    
    # Then: the returned weight is 1.5
    assert actual_weight == expected_weight, f"expected {expected_weight}, got {actual_weight}"


def test_prioritize_relationship_types_first_is_subclass_of(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Prioritize relationship types first is subclass_of

    Given:
        relationship types mentions, subclass_of, instance_of, related_to

    When:
        get_prioritized_relationship_types is called

    Then:
        the first type in result is subclass_of
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_types = ["mentions", "subclass_of", "instance_of", "related_to"]
    expected_first_type = "subclass_of"
    first_index = 0
    
    # When: get_prioritized_relationship_types is called
    result = calculator.get_prioritized_relationship_types(relationship_types)
    actual_first_type = result[first_index]
    
    # Then: the first type in result is subclass_of
    assert actual_first_type == expected_first_type, f"expected {expected_first_type}, got {actual_first_type}"


def test_prioritize_relationship_types_second_is_instance_of(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Prioritize relationship types second is instance_of

    Given:
        relationship types mentions, subclass_of, instance_of, related_to

    When:
        get_prioritized_relationship_types is called

    Then:
        the second type in result is instance_of
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_types = ["mentions", "subclass_of", "instance_of", "related_to"]
    expected_second_type = "instance_of"
    second_index = 1
    
    # When: get_prioritized_relationship_types is called
    result = calculator.get_prioritized_relationship_types(relationship_types)
    actual_second_type = result[second_index]
    
    # Then: the second type in result is instance_of
    assert actual_second_type == expected_second_type, f"expected {expected_second_type}, got {actual_second_type}"


def test_prioritize_relationship_types_third_is_related_to(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Prioritize relationship types third is related_to

    Given:
        relationship types mentions, subclass_of, instance_of, related_to

    When:
        get_prioritized_relationship_types is called

    Then:
        the third type in result is related_to
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_types = ["mentions", "subclass_of", "instance_of", "related_to"]
    expected_third_type = "related_to"
    third_index = 2
    
    # When: get_prioritized_relationship_types is called
    result = calculator.get_prioritized_relationship_types(relationship_types)
    actual_third_type = result[third_index]
    
    # Then: the third type in result is related_to
    assert actual_third_type == expected_third_type, f"expected {expected_third_type}, got {actual_third_type}"


def test_prioritize_relationship_types_fourth_is_mentions(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Prioritize relationship types fourth is mentions

    Given:
        relationship types mentions, subclass_of, instance_of, related_to

    When:
        get_prioritized_relationship_types is called

    Then:
        the fourth type in result is mentions
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_types = ["mentions", "subclass_of", "instance_of", "related_to"]
    expected_fourth_type = "mentions"
    fourth_index = 3
    
    # When: get_prioritized_relationship_types is called
    result = calculator.get_prioritized_relationship_types(relationship_types)
    actual_fourth_type = result[fourth_index]
    
    # Then: the fourth type in result is mentions
    assert actual_fourth_type == expected_fourth_type, f"expected {expected_fourth_type}, got {actual_fourth_type}"


def test_filter_high_value_relationships_with_threshold_08_includes_subclass_of(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Filter high value relationships with threshold 0.8 includes subclass_of

    Given:
        relationship types subclass_of, mentions, instance_of, related_to

    When:
        get_filtered_high_value_relationships is called with min_weight 0.8

    Then:
        the result contains subclass_of
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_types = ["subclass_of", "mentions", "instance_of", "related_to"]
    min_weight = 0.8
    expected_type = "subclass_of"
    
    # When: get_filtered_high_value_relationships is called with min_weight 0.8
    result = calculator.get_filtered_high_value_relationships(relationship_types, min_weight)
    actual_contains = expected_type in result
    
    # Then: the result contains subclass_of
    assert actual_contains, f"expected {expected_type} in result, got {result}"


def test_filter_high_value_relationships_with_threshold_08_includes_instance_of(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Filter high value relationships with threshold 0.8 includes instance_of

    Given:
        relationship types subclass_of, mentions, instance_of, related_to

    When:
        get_filtered_high_value_relationships is called with min_weight 0.8

    Then:
        the result contains instance_of
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_types = ["subclass_of", "mentions", "instance_of", "related_to"]
    min_weight = 0.8
    expected_type = "instance_of"
    
    # When: get_filtered_high_value_relationships is called with min_weight 0.8
    result = calculator.get_filtered_high_value_relationships(relationship_types, min_weight)
    actual_contains = expected_type in result
    
    # Then: the result contains instance_of
    assert actual_contains, f"expected {expected_type} in result, got {result}"


def test_filter_high_value_relationships_with_threshold_08_excludes_mentions(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Filter high value relationships with threshold 0.8 excludes mentions

    Given:
        relationship types subclass_of, mentions, instance_of, related_to

    When:
        get_filtered_high_value_relationships is called with min_weight 0.8

    Then:
        the result does not contain mentions
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_types = ["subclass_of", "mentions", "instance_of", "related_to"]
    min_weight = 0.8
    excluded_type = "mentions"
    
    # When: get_filtered_high_value_relationships is called with min_weight 0.8
    result = calculator.get_filtered_high_value_relationships(relationship_types, min_weight)
    actual_not_contains = excluded_type not in result
    
    # Then: the result does not contain mentions
    assert actual_not_contains, f"expected {excluded_type} not in result, got {result}"


def test_filter_high_value_relationships_with_threshold_08_excludes_related_to(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Filter high value relationships with threshold 0.8 excludes related_to

    Given:
        relationship types subclass_of, mentions, instance_of, related_to

    When:
        get_filtered_high_value_relationships is called with min_weight 0.8

    Then:
        the result does not contain related_to
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_types = ["subclass_of", "mentions", "instance_of", "related_to"]
    related_to_weight = 1.0
    min_weight = related_to_weight + 0.01  # Threshold above related_to weight to exclude it
    excluded_type = "related_to"
    
    # When: get_filtered_high_value_relationships is called with min_weight above related_to weight
    result = calculator.get_filtered_high_value_relationships(relationship_types, min_weight)
    actual_not_contains = excluded_type not in result
    
    # Then: the result does not contain related_to
    assert actual_not_contains, f"expected {excluded_type} not in result, got {result}"


def test_filter_high_value_relationships_with_threshold_05_includes_subclass_of(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Filter high value relationships with threshold 0.5 includes subclass_of

    Given:
        relationship types subclass_of, mentions, instance_of

    When:
        get_filtered_high_value_relationships is called with min_weight 0.5

    Then:
        the result contains subclass_of
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_types = ["subclass_of", "mentions", "instance_of"]
    min_weight = 0.5
    expected_type = "subclass_of"
    
    # When: get_filtered_high_value_relationships is called with min_weight 0.5
    result = calculator.get_filtered_high_value_relationships(relationship_types, min_weight)
    actual_contains = expected_type in result
    
    # Then: the result contains subclass_of
    assert actual_contains, f"expected {expected_type} in result, got {result}"


def test_filter_high_value_relationships_with_threshold_05_includes_instance_of(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Filter high value relationships with threshold 0.5 includes instance_of

    Given:
        relationship types subclass_of, mentions, instance_of

    When:
        get_filtered_high_value_relationships is called with min_weight 0.5

    Then:
        the result contains instance_of
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_types = ["subclass_of", "mentions", "instance_of"]
    min_weight = 0.5
    expected_type = "instance_of"
    
    # When: get_filtered_high_value_relationships is called with min_weight 0.5
    result = calculator.get_filtered_high_value_relationships(relationship_types, min_weight)
    actual_contains = expected_type in result
    
    # Then: the result contains instance_of
    assert actual_contains, f"expected {expected_type} in result, got {result}"


def test_filter_high_value_relationships_with_threshold_05_excludes_mentions(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Filter high value relationships with threshold 0.5 excludes mentions

    Given:
        relationship types subclass_of, mentions, instance_of

    When:
        get_filtered_high_value_relationships is called with min_weight 0.5

    Then:
        the result does not contain mentions
    """
    calculator = wikipediarelationshipweightcalculator_instance
    relationship_types = ["subclass_of", "mentions", "instance_of"]
    mentions_weight = 0.5
    min_weight_threshold = mentions_weight + 0.01  # Threshold above mentions weight to exclude it
    excluded_type = "mentions"
    
    # When: get_filtered_high_value_relationships is called with threshold above mentions weight
    result = calculator.get_filtered_high_value_relationships(relationship_types, min_weight_threshold)
    actual_not_contains = excluded_type not in result
    
    # Then: the result does not contain mentions
    assert actual_not_contains, f"expected {excluded_type} not in result, got {result}"


def test_normalize_relationship_type_with_is__prefix(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Normalize relationship type with is_ prefix

    When:
        _normalize_relationship_type is called with is_subclass_of

    Then:
        the result is subclass_of
    """
    calculator = wikipediarelationshipweightcalculator_instance
    input_type = "is_subclass_of"
    expected_result = "subclass_of"
    
    # When: _normalize_relationship_type is called with is_subclass_of
    actual_result = calculator._normalize_relationship_type(input_type)
    
    # Then: the result is subclass_of
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_normalize_relationship_type_with_spaces(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Normalize relationship type with spaces

    When:
        _normalize_relationship_type is called with Instance Of

    Then:
        the result is instance_of
    """
    calculator = wikipediarelationshipweightcalculator_instance
    input_type = "Instance Of"
    expected_result = "instance_of"
    
    # When: _normalize_relationship_type is called with Instance Of
    actual_result = calculator._normalize_relationship_type(input_type)
    
    # Then: the result is instance_of
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_normalize_relationship_type_with_hyphens(wikipediarelationshipweightcalculator_instance):
    """
    Scenario: Normalize relationship type with hyphens

    When:
        _normalize_relationship_type is called with related-to

    Then:
        the result is related_to
    """
    calculator = wikipediarelationshipweightcalculator_instance
    input_type = "related-to"
    expected_result = "related_to"
    
    # When: _normalize_relationship_type is called with related-to
    actual_result = calculator._normalize_relationship_type(input_type)
    
    # Then: the result is related_to
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"

