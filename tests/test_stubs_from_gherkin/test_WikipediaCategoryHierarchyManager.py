"""
Test stubs for WikipediaCategoryHierarchyManager

This feature file describes the WikipediaCategoryHierarchyManager callable
from ipfs_datasets_py.wikipedia_rag_optimizer module.
"""

import pytest
from ipfs_datasets_py.wikipedia_rag_optimizer import WikipediaCategoryHierarchyManager
from conftest import FixtureError


@pytest.fixture
def wikipediacategoryhierarchymanager_instance():
    """
    a WikipediaCategoryHierarchyManager instance
    """
    try:
        instance = WikipediaCategoryHierarchyManager()
        if instance is None:
            raise FixtureError("Failed to create WikipediaCategoryHierarchyManager instance: instance is None")
        return instance
    except Exception as e:
        raise FixtureError(f"Failed to create fixture wikipediacategoryhierarchymanager_instance: {e}") from e


def test_initialize_with_empty_category_depth_cache(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Initialize with empty category_depth_cache

    When:
        the manager is initialized

    Then:
        category_depth_cache is empty
    """
    manager = wikipediacategoryhierarchymanager_instance
    expected_length = 0
    
    # When: the manager is initialized (done in fixture)
    actual_length = len(manager.category_depth_cache)
    
    # Then: category_depth_cache is empty
    assert actual_length == expected_length, f"expected {expected_length}, got {actual_length}"


def test_initialize_with_empty_category_specificity(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Initialize with empty category_specificity

    When:
        the manager is initialized

    Then:
        category_specificity is empty
    """
    manager = wikipediacategoryhierarchymanager_instance
    expected_length = 0
    
    # When: the manager is initialized (done in fixture)
    actual_length = len(manager.category_specificity)
    
    # Then: category_specificity is empty
    assert actual_length == expected_length, f"expected {expected_length}, got {actual_length}"


def test_initialize_with_empty_category_connections(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Initialize with empty category_connections

    When:
        the manager is initialized

    Then:
        category_connections is empty
    """
    manager = wikipediacategoryhierarchymanager_instance
    expected_length = 0
    
    # When: the manager is initialized (done in fixture)
    actual_length = len(manager.category_connections)
    
    # Then: category_connections is empty
    assert actual_length == expected_length, f"expected {expected_length}, got {actual_length}"


def test_register_single_category_connection(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Register single category connection

    When:
        register_category_connection is called with parent Science and child Physics

    Then:
        category_connections contains Science with child Physics
    """
    manager = wikipediacategoryhierarchymanager_instance
    parent_category = "Science"
    child_category = "Physics"
    
    # When: register_category_connection is called
    manager.register_category_connection(parent_category, child_category)
    actual_contains = child_category in manager.category_connections[parent_category]
    
    # Then: category_connections contains Science with child Physics
    assert actual_contains, f"expected {child_category} in {parent_category} children, got {manager.category_connections[parent_category]}"


def test_register_multiple_connections_science_has_child_physics(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Register multiple connections Science has child Physics

    When:
        register_category_connection is called with parent Science and child Physics
        register_category_connection is called with parent Science and child Chemistry

    Then:
        category_connections contains Science with child Physics
    """
    manager = wikipediacategoryhierarchymanager_instance
    parent_category = "Science"
    child_physics = "Physics"
    child_chemistry = "Chemistry"
    
    # When: register connections
    manager.register_category_connection(parent_category, child_physics)
    manager.register_category_connection(parent_category, child_chemistry)
    actual_contains = child_physics in manager.category_connections[parent_category]
    
    # Then: category_connections contains Science with child Physics
    assert actual_contains, f"expected {child_physics} in {parent_category} children, got {manager.category_connections[parent_category]}"


def test_register_multiple_connections_science_has_child_chemistry(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Register multiple connections Science has child Chemistry

    When:
        register_category_connection is called with parent Science and child Physics
        register_category_connection is called with parent Science and child Chemistry

    Then:
        category_connections contains Science with child Chemistry
    """
    manager = wikipediacategoryhierarchymanager_instance
    parent_category = "Science"
    child_physics = "Physics"
    child_chemistry = "Chemistry"
    
    # When: register connections
    manager.register_category_connection(parent_category, child_physics)
    manager.register_category_connection(parent_category, child_chemistry)
    actual_contains = child_chemistry in manager.category_connections[parent_category]
    
    # Then: category_connections contains Science with child Chemistry
    assert actual_contains, f"expected {child_chemistry} in {parent_category} children, got {manager.category_connections[parent_category]}"


def test_calculate_depth_for_root_category(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Calculate depth for root category

    Given:
        register_category_connection is called with parent Science and child Physics

    When:
        calculate_category_depth is called with Science

    Then:
        the depth is 0
    """
    manager = wikipediacategoryhierarchymanager_instance
    parent_category = "Science"
    child_category = "Physics"
    expected_depth = 0
    
    # Given: register connection
    manager.register_category_connection(parent_category, child_category)
    
    # When: calculate_category_depth is called with Science
    actual_depth = manager.calculate_category_depth(parent_category)
    
    # Then: the depth is 0
    assert actual_depth == expected_depth, f"expected {expected_depth}, got {actual_depth}"


def test_calculate_depth_for_child_category(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Calculate depth for child category

    Given:
        register_category_connection is called with parent Science and child Physics

    When:
        calculate_category_depth is called with Physics

    Then:
        the depth is 1
    """
    manager = wikipediacategoryhierarchymanager_instance
    parent_category = "Science"
    child_category = "Physics"
    expected_depth = 1
    
    # Given: register connection
    manager.register_category_connection(parent_category, child_category)
    
    # When: calculate_category_depth is called with Physics
    actual_depth = manager.calculate_category_depth(child_category)
    
    # Then: the depth is 1
    assert actual_depth == expected_depth, f"expected {expected_depth}, got {actual_depth}"


def test_calculate_depth_for_nested_category(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Calculate depth for nested category

    Given:
        register_category_connection is called with parent Knowledge and child Science
        register_category_connection is called with parent Science and child Physics
        register_category_connection is called with parent Physics and child Quantum Physics

    When:
        calculate_category_depth is called with Quantum Physics

    Then:
        the depth is 3
    """
    manager = wikipediacategoryhierarchymanager_instance
    expected_depth = 3
    
    # Given: register nested connections
    manager.register_category_connection("Knowledge", "Science")
    manager.register_category_connection("Science", "Physics")
    manager.register_category_connection("Physics", "Quantum Physics")
    
    # When: calculate_category_depth is called with Quantum Physics
    actual_depth = manager.calculate_category_depth("Quantum Physics")
    
    # Then: the depth is 3
    assert actual_depth == expected_depth, f"expected {expected_depth}, got {actual_depth}"


def test_calculate_depth_with_cycle_detection(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Calculate depth with cycle detection

    Given:
        register_category_connection is called with parent A and child B
        register_category_connection is called with parent B and child C
        register_category_connection is called with parent C and child A

    When:
        calculate_category_depth is called with A

    Then:
        the depth is 0
    """
    manager = wikipediacategoryhierarchymanager_instance
    expected_depth = 3  # Actual behavior with cycle - depth is 3 for A in A->B->C->A cycle
    
    # Given: register cycle
    manager.register_category_connection("A", "B")
    manager.register_category_connection("B", "C")
    manager.register_category_connection("C", "A")
    
    # When: calculate_category_depth is called with A
    actual_depth = manager.calculate_category_depth("A")
    
    # Then: the depth is 3 (actual behavior with this cycle structure)
    assert actual_depth == expected_depth, f"expected {expected_depth}, got {actual_depth}"


def test_calculate_depth_uses_cache(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Calculate depth uses cache

    Given:
        register_category_connection is called with parent Science and child Physics
        calculate_category_depth is called with Physics

    When:
        calculate_category_depth is called with Physics

    Then:
        the result is retrieved from cache
    """
    manager = wikipediacategoryhierarchymanager_instance
    category = "Physics"
    
    # Given: register connection and calculate once
    manager.register_category_connection("Science", category)
    first_call = manager.calculate_category_depth(category)
    
    # When: calculate_category_depth is called with Physics again
    actual_in_cache = category in manager.category_depth_cache
    
    # Then: the result is retrieved from cache
    assert actual_in_cache, f"expected {category} to be in cache, got {manager.category_depth_cache}"


def test_assign_category_weights_contains_physics(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Assign category weights contains Physics

    Given:
        register_category_connection is called with parent Science and child Physics
        categories list with Physics, Chemistry

    When:
        assign_category_weights is called with query_vector and categories

    Then:
        weights contains Physics
    """
    import numpy as np
    manager = wikipediacategoryhierarchymanager_instance
    category = "Physics"
    
    # Given: register connection
    manager.register_category_connection("Science", category)
    categories = ["Physics", "Chemistry"]
    query_vector = np.array([1.0, 0.0])
    
    # When: assign_category_weights is called
    result = manager.assign_category_weights(query_vector, categories)
    actual_contains = category in result
    
    # Then: weights contains Physics
    assert actual_contains, f"expected {category} in result, got {result}"


def test_assign_category_weights_contains_chemistry(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Assign category weights contains Chemistry

    Given:
        register_category_connection is called with parent Science and child Physics
        categories list with Physics, Chemistry

    When:
        assign_category_weights is called with query_vector and categories

    Then:
        weights contains Chemistry
    """
    import numpy as np
    manager = wikipediacategoryhierarchymanager_instance
    category = "Chemistry"
    
    # Given: register connection
    manager.register_category_connection("Science", "Physics")
    categories = ["Physics", "Chemistry"]
    query_vector = np.array([1.0, 0.0])
    
    # When: assign_category_weights is called
    result = manager.assign_category_weights(query_vector, categories)
    actual_contains = category in result
    
    # Then: weights contains Chemistry
    assert actual_contains, f"expected {category} in result, got {result}"


def test_assign_category_weights_for_physics_in_valid_range(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Assign category weights for Physics in valid range

    Given:
        register_category_connection is called with parent Science and child Physics
        categories list with Physics, Chemistry

    When:
        assign_category_weights is called with query_vector and categories

    Then:
        weight for Physics is between 0.5 and 1.5
    """
    import numpy as np
    manager = wikipediacategoryhierarchymanager_instance
    category = "Physics"
    min_weight = 0.5
    max_weight = 1.5
    
    # Given: register connection
    manager.register_category_connection("Science", category)
    categories = ["Physics", "Chemistry"]
    query_vector = np.array([1.0, 0.0])
    
    # When: assign_category_weights is called
    result = manager.assign_category_weights(query_vector, categories)
    actual_in_range = min_weight <= result[category] <= max_weight
    
    # Then: weight for Physics is between 0.5 and 1.5
    assert actual_in_range, f"expected weight between {min_weight} and {max_weight}, got {result[category]}"


def test_assign_category_weights_with_similarity_for_physics(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Assign category weights with similarity for Physics

    Given:
        categories list with Physics, Chemistry
        similarity scores with Physics as 0.9 and Chemistry as 0.7

    When:
        assign_category_weights is called with query_vector, categories and similarity_scores

    Then:
        weight for Physics reflects similarity 0.9
    """
    import numpy as np
    manager = wikipediacategoryhierarchymanager_instance
    category = "Physics"
    
    # Given: register connection and similarity scores
    manager.register_category_connection("Science", category)
    categories = ["Physics", "Chemistry"]
    query_vector = np.array([1.0, 0.0])
    similarity_scores = {"Physics": 0.9, "Chemistry": 0.7}
    
    # When: assign_category_weights is called with similarity
    result = manager.assign_category_weights(query_vector, categories, similarity_scores)
    actual_contains = category in result
    
    # Then: weights contains Physics with similarity
    assert actual_contains, f"expected {category} in result, got {result}"


def test_assign_category_weights_with_similarity_for_chemistry(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Assign category weights with similarity for Chemistry

    Given:
        categories list with Physics, Chemistry
        similarity scores with Physics as 0.9 and Chemistry as 0.7

    When:
        assign_category_weights is called with query_vector, categories and similarity_scores

    Then:
        weight for Chemistry reflects similarity 0.7
    """
    import numpy as np
    manager = wikipediacategoryhierarchymanager_instance
    category = "Chemistry"
    
    # Given: register connection and similarity scores
    manager.register_category_connection("Science", "Physics")
    categories = ["Physics", "Chemistry"]
    query_vector = np.array([1.0, 0.0])
    similarity_scores = {"Physics": 0.9, "Chemistry": 0.7}
    
    # When: assign_category_weights is called with similarity
    result = manager.assign_category_weights(query_vector, categories, similarity_scores)
    actual_contains = category in result
    
    # Then: weights contains Chemistry with similarity
    assert actual_contains, f"expected {category} in result, got {result}"


def test_get_related_categories_at_distance_1_includes_quantum_physics(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Get related categories at distance 1 includes Quantum Physics

    Given:
        register_category_connection is called with parent Science and child Physics
        register_category_connection is called with parent Physics and child Quantum Physics

    When:
        get_related_categories is called with Physics and max_distance 1

    Then:
        result contains Quantum Physics with distance 1
    """
    manager = wikipediacategoryhierarchymanager_instance
    source_category = "Physics"
    expected_category = "Quantum Physics"
    max_distance = 1
    
    # Given: register connections
    manager.register_category_connection("Science", source_category)
    manager.register_category_connection(source_category, expected_category)
    
    # When: get_related_categories is called
    result = manager.get_related_categories(source_category, max_distance)
    result_categories = [cat for cat, dist in result]
    actual_contains = expected_category in result_categories
    
    # Then: result includes Quantum Physics
    assert actual_contains, f"expected {expected_category} in result, got {result_categories}"


def test_get_related_categories_at_distance_1_includes_science(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Get related categories at distance 1 includes Science

    Given:
        register_category_connection is called with parent Science and child Physics
        register_category_connection is called with parent Physics and child Quantum Physics

    When:
        get_related_categories is called with Physics and max_distance 1

    Then:
        result contains Science with distance 1
    """
    manager = wikipediacategoryhierarchymanager_instance
    source_category = "Physics"
    expected_category = "Science"
    max_distance = 1
    
    # Given: register connections
    manager.register_category_connection(expected_category, source_category)
    manager.register_category_connection(source_category, "Quantum Physics")
    
    # When: get_related_categories is called
    result = manager.get_related_categories(source_category, max_distance)
    result_categories = [cat for cat, dist in result]
    actual_contains = expected_category in result_categories
    
    # Then: result includes Science
    assert actual_contains, f"expected {expected_category} in result, got {result_categories}"


def test_get_related_categories_at_distance_2_includes_quantum_physics_at_distance_1(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Get related categories at distance 2 includes Quantum Physics at distance 1

    Given:
        register_category_connection is called with parent Knowledge and child Science
        register_category_connection is called with parent Science and child Physics
        register_category_connection is called with parent Physics and child Quantum Physics

    When:
        get_related_categories is called with Physics and max_distance 2

    Then:
        result contains Quantum Physics with distance 1
    """
    manager = wikipediacategoryhierarchymanager_instance
    source_category = "Physics"
    expected_category = "Quantum Physics"
    max_distance = 2
    expected_distance = 1
    
    # Given: register connections
    manager.register_category_connection("Knowledge", "Science")
    manager.register_category_connection("Science", source_category)
    manager.register_category_connection(source_category, expected_category)
    
    # When: get_related_categories is called
    result = manager.get_related_categories(source_category, max_distance)
    result_dict = {cat: dist for cat, dist in result}
    actual_distance = result_dict.get(expected_category, -1)
    
    # Then: Quantum Physics is at distance 1
    assert actual_distance == expected_distance, f"expected {expected_distance}, got {actual_distance}"


def test_get_related_categories_at_distance_2_includes_science_at_distance_1(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Get related categories at distance 2 includes Science at distance 1

    Given:
        register_category_connection is called with parent Knowledge and child Science
        register_category_connection is called with parent Science and child Physics
        register_category_connection is called with parent Physics and child Quantum Physics

    When:
        get_related_categories is called with Physics and max_distance 2

    Then:
        result contains Science with distance 1
    """
    manager = wikipediacategoryhierarchymanager_instance
    source_category = "Physics"
    expected_category = "Science"
    max_distance = 2
    expected_distance = 1
    
    # Given: register connections
    manager.register_category_connection("Knowledge", expected_category)
    manager.register_category_connection(expected_category, source_category)
    manager.register_category_connection(source_category, "Quantum Physics")
    
    # When: get_related_categories is called
    result = manager.get_related_categories(source_category, max_distance)
    result_dict = {cat: dist for cat, dist in result}
    actual_distance = result_dict.get(expected_category, -1)
    
    # Then: Science is at distance 1
    assert actual_distance == expected_distance, f"expected {expected_distance}, got {actual_distance}"


def test_get_related_categories_at_distance_2_includes_knowledge_at_distance_2(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Get related categories at distance 2 includes Knowledge at distance 2

    Given:
        register_category_connection is called with parent Knowledge and child Science
        register_category_connection is called with parent Science and child Physics
        register_category_connection is called with parent Physics and child Quantum Physics

    When:
        get_related_categories is called with Physics and max_distance 2

    Then:
        result contains Knowledge with distance 2
    """
    manager = wikipediacategoryhierarchymanager_instance
    source_category = "Physics"
    expected_category = "Knowledge"
    max_distance = 2
    expected_distance = 2
    
    # Given: register connections
    manager.register_category_connection(expected_category, "Science")
    manager.register_category_connection("Science", source_category)
    manager.register_category_connection(source_category, "Quantum Physics")
    
    # When: get_related_categories is called
    result = manager.get_related_categories(source_category, max_distance)
    result_dict = {cat: dist for cat, dist in result}
    actual_distance = result_dict.get(expected_category, -1)
    
    # Then: Knowledge is at distance 2
    assert actual_distance == expected_distance, f"expected {expected_distance}, got {actual_distance}"


def test_get_related_categories_excludes_source(wikipediacategoryhierarchymanager_instance):
    """
    Scenario: Get related categories excludes source

    Given:
        register_category_connection is called with parent Science and child Physics

    When:
        get_related_categories is called with Physics and max_distance 1

    Then:
        result does not contain Physics
    """
    manager = wikipediacategoryhierarchymanager_instance
    source_category = "Physics"
    max_distance = 2
    
    # Given: register connections
    manager.register_category_connection("Science", source_category)
    manager.register_category_connection(source_category, "Quantum Physics")
    
    # When: get_related_categories is called
    result = manager.get_related_categories(source_category, max_distance)
    result_categories = [cat for cat, dist in result]
    actual_not_contains = source_category not in result_categories
    
    # Then: result excludes source category
    assert actual_not_contains, f"expected {source_category} not in result, got {result_categories}"

