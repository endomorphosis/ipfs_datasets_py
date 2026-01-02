Feature: detect_graph_type
  This feature file describes the detect_graph_type callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Scenario: Detect graph type with explicit graph_type attribute
    Given graph_processor with graph_type attribute as wikipedia
    When detect_graph_type is called
    Then result is wikipedia

  Scenario: Detect Wikipedia graph from entity types
    Given graph_processor with 10 entities
    And 8 entities have type containing category
    And 2 entities have type containing ipld
    When detect_graph_type is called
    Then result is wikipedia

  Scenario: Detect IPLD graph from entity types
    Given graph_processor with 10 entities
    And 2 entities have type containing category
    And 7 entities have type containing cid
    When detect_graph_type is called
    Then result is ipld

  Scenario: Detect Wikipedia graph from relationship types
    Given graph_processor with relationship_types
    And relationship_types include subclass_of
    And relationship_types include category_contains
    When detect_graph_type is called
    Then result is wikipedia

  Scenario: Detect IPLD graph from relationship types
    Given graph_processor with relationship_types
    And relationship_types include links_to
    And relationship_types include references
    When detect_graph_type is called
    Then result is ipld

  Scenario: Detect unknown graph type
    Given graph_processor with mixed indicators
    And 3 wikipedia indicators
    And 3 ipld indicators
    When detect_graph_type is called
    Then result is unknown

  Scenario: Detect with no entity access
    Given graph_processor without get_entities method
    And graph_processor without list_entities method
    When detect_graph_type is called
    Then detection continues with relationship analysis

  Scenario: Detect with entity access exception
    Given graph_processor with get_entities method
    And get_entities raises exception
    When detect_graph_type is called
    Then detection continues with relationship analysis

  Scenario: Detect with no relationship access
    Given graph_processor with entities but no relationship methods
    When detect_graph_type is called
    Then detection uses entity analysis only

  Scenario: Detect with sample limit
    Given graph_processor with 100 entities
    When detect_graph_type is called
    Then only 20 entities are analyzed
