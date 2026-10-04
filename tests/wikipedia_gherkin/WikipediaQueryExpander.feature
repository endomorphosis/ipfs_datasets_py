Feature: WikipediaQueryExpander
  This feature file describes the WikipediaQueryExpander callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Background:
    Given a WikipediaQueryExpander instance

  Scenario: Initialize without tracer similarity_threshold is 0.65
    When the expander is initialized without tracer
    Then similarity_threshold is 0.65

  Scenario: Initialize without tracer max_expansions is 5
    When the expander is initialized without tracer
    Then max_expansions is 5

  Scenario: Initialize without tracer tracer is None
    When the expander is initialized without tracer
    Then tracer is None


  Scenario: Initialize with tracer tracer is set
    Given a WikipediaKnowledgeGraphTracer instance
    When the expander is initialized with tracer
    Then tracer is set

  Scenario: Initialize with tracer similarity_threshold is 0.65
    Given a WikipediaKnowledgeGraphTracer instance
    When the expander is initialized with tracer
    Then similarity_threshold is 0.65

  Scenario: Initialize with tracer max_expansions is 5
    Given a WikipediaKnowledgeGraphTracer instance
    When the expander is initialized with tracer
    Then max_expansions is 5


  Scenario: Expand query with vector store result contains original_query_vector
    Given query_vector as numpy array
    And query_text as quantum physics experiments
    And vector_store with search capability
    And category_hierarchy manager
    When expand_query is called
    Then result contains original_query_vector

  Scenario: Expand query with vector store result contains original_query_text
    Given query_vector as numpy array
    And query_text as quantum physics experiments
    And vector_store with search capability
    And category_hierarchy manager
    When expand_query is called
    Then result contains original_query_text

  Scenario: Expand query with vector store result contains expansions with topics
    Given query_vector as numpy array
    And query_text as quantum physics experiments
    And vector_store with search capability
    And category_hierarchy manager
    When expand_query is called
    Then result contains expansions with topics

  Scenario: Expand query with vector store result contains expansions with categories
    Given query_vector as numpy array
    And query_text as quantum physics experiments
    And vector_store with search capability
    And category_hierarchy manager
    When expand_query is called
    Then result contains expansions with categories

  Scenario: Expand query with vector store result contains has_expansions flag
    Given query_vector as numpy array
    And query_text as quantum physics experiments
    And vector_store with search capability
    And category_hierarchy manager
    When expand_query is called
    Then result contains has_expansions flag


  Scenario: Expand query finds similar topics expansions topics contains 3 items
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store returns 3 topic results with scores 0.8, 0.7, 0.65
    And category_hierarchy manager
    When expand_query is called
    Then expansions topics contains 3 items

  Scenario: Expand query finds similar topics each topic has id, name, and similarity
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store returns 3 topic results with scores 0.8, 0.7, 0.65
    And category_hierarchy manager
    When expand_query is called
    Then each topic has id, name, and similarity


  Scenario: Expand query filters by similarity threshold expansions topics contains 3 items
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store returns 5 topic results with scores 0.9, 0.7, 0.6, 0.5, 0.4
    And category_hierarchy manager
    When expand_query is called
    Then expansions topics contains 3 items

  Scenario: Expand query filters by similarity threshold all topics have similarity >= 0.65
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store returns 5 topic results with scores 0.9, 0.7, 0.6, 0.5, 0.4
    And category_hierarchy manager
    When expand_query is called
    Then all topics have similarity >= 0.65


  Scenario: Expand query limits topics to max_expansions
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store returns 10 topic results all above threshold
    And category_hierarchy manager
    When expand_query is called
    Then expansions topics contains at most 5 items


  Scenario: Expand query finds related categories expansions categories contains Physics
    Given query_vector as numpy array
    And query_text as quantum physics experiments
    And category_hierarchy with Physics category
    And category_hierarchy with Quantum Physics as related to Physics
    When expand_query is called
    Then expansions categories contains Physics

  Scenario: Expand query finds related categories expansions categories may contain Quantum Physics
    Given query_vector as numpy array
    And query_text as quantum physics experiments
    And category_hierarchy with Physics category
    And category_hierarchy with Quantum Physics as related to Physics
    When expand_query is called
    Then expansions categories may contain Quantum Physics


  Scenario: Expand query with category token matching
    Given query_vector as numpy array
    And query_text as quantum mechanics theory
    And category_hierarchy with Quantum Mechanics category
    When expand_query is called
    Then expansions categories contains Quantum Mechanics


  Scenario: Expand query sorts categories by depth categories are sorted by depth descending
    Given query_vector as numpy array
    And query_text as physics
    And category_hierarchy with Science at depth 0
    And category_hierarchy with Physics at depth 1
    And category_hierarchy with Quantum Physics at depth 2
    When expand_query is called
    Then categories are sorted by depth descending

  Scenario: Expand query sorts categories by depth first category has highest depth
    Given query_vector as numpy array
    And query_text as physics
    And category_hierarchy with Science at depth 0
    And category_hierarchy with Physics at depth 1
    And category_hierarchy with Quantum Physics at depth 2
    When expand_query is called
    Then first category has highest depth


  Scenario: Expand query with no vector store expansions topics is empty
    Given query_vector as numpy array
    And query_text as quantum physics
    And no vector_store
    And category_hierarchy manager
    When expand_query is called
    Then expansions topics is empty

  Scenario: Expand query with no vector store expansions categories may not be empty
    Given query_vector as numpy array
    And query_text as quantum physics
    And no vector_store
    And category_hierarchy manager
    When expand_query is called
    Then expansions categories may not be empty


  Scenario: Expand query with tracer logging
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store with search capability
    And category_hierarchy manager
    And tracer is set
    And trace_id as expand_001
    When expand_query is called with trace_id
    Then tracer logs query expansion with trace_id


  Scenario: Expand query handles vector store errors expansions topics is empty
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store raises exception on search
    And category_hierarchy manager
    When expand_query is called
    Then expansions topics is empty

  Scenario: Expand query handles vector store errors no exception is raised
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store raises exception on search
    And category_hierarchy manager
    When expand_query is called
    Then no exception is raised

  Scenario: Expand query handles vector store errors has_expansions reflects actual expansions
    Given query_vector as numpy array
    And query_text as quantum physics
    And vector_store raises exception on search
    And category_hierarchy manager
    When expand_query is called
    Then has_expansions reflects actual expansions

