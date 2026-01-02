Feature: WikipediaQueryExpander
  This feature file describes the WikipediaQueryExpander callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Background:
    Given a WikipediaQueryExpander instance

  Scenario: Initialize without tracer
    When the expander is initialized without tracer
    Then similarity_threshold is 0.65
    And max_expansions is 5
    And tracer is None

  Scenario: Initialize with tracer
    Given a WikipediaKnowledgeGraphTracer instance
    When the expander is initialized with tracer
    Then tracer is set
    And similarity_threshold is 0.65
    And max_expansions is 5

  Scenario: Expand query with vector store
    Given query_vector as numpy array
    And query_text as quantum physics experiments
    And vector_store with search capability
    And category_hierarchy manager
    When expand_query is called
    Then result contains original_query_vector
    And result contains original_query_text
    And result contains expansions with topics
    And result contains expansions with categories
    And result contains has_expansions flag

  Scenario: Expand query finds similar topics
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store returns 3 topic results with scores 0.8, 0.7, 0.65
    And category_hierarchy manager
    When expand_query is called
    Then expansions topics contains 3 items
    And each topic has id, name, and similarity

  Scenario: Expand query filters by similarity threshold
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store returns 5 topic results with scores 0.9, 0.7, 0.6, 0.5, 0.4
    And category_hierarchy manager
    When expand_query is called
    Then expansions topics contains 3 items
    And all topics have similarity >= 0.65

  Scenario: Expand query limits topics to max_expansions
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store returns 10 topic results all above threshold
    And category_hierarchy manager
    When expand_query is called
    Then expansions topics contains at most 5 items

  Scenario: Expand query finds related categories
    Given query_vector as numpy array
    And query_text as quantum physics experiments
    And category_hierarchy with Physics category
    And category_hierarchy with Quantum Physics as related to Physics
    When expand_query is called
    Then expansions categories contains Physics
    And expansions categories may contain Quantum Physics

  Scenario: Expand query with category token matching
    Given query_vector as numpy array
    And query_text as quantum mechanics theory
    And category_hierarchy with Quantum Mechanics category
    When expand_query is called
    Then expansions categories contains Quantum Mechanics

  Scenario: Expand query sorts categories by depth
    Given query_vector as numpy array
    And query_text as physics
    And category_hierarchy with Science at depth 0
    And category_hierarchy with Physics at depth 1
    And category_hierarchy with Quantum Physics at depth 2
    When expand_query is called
    Then categories are sorted by depth descending
    And first category has highest depth

  Scenario: Expand query with no vector store
    Given query_vector as numpy array
    And query_text as quantum physics
    And no vector_store
    And category_hierarchy manager
    When expand_query is called
    Then expansions topics is empty
    And expansions categories may not be empty

  Scenario: Expand query with tracer logging
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store with search capability
    And category_hierarchy manager
    And tracer is set
    And trace_id as expand_001
    When expand_query is called with trace_id
    Then tracer logs query expansion with trace_id

  Scenario: Expand query handles vector store errors
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store raises exception on search
    And category_hierarchy manager
    When expand_query is called
    Then expansions topics is empty
    And no exception is raised
    And has_expansions reflects actual expansions
