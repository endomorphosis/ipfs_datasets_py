Feature: GraphRAG Integration
  Retrieval-Augmented Generation with knowledge graphs

  Scenario: Initialize GraphRAG system
    Given a knowledge graph and language model
    When GraphRAG is initialized
    Then the system is ready for queries

  Scenario: Query knowledge graph for context
    Given a user query
    When graph retrieval is performed
    Then relevant graph context is retrieved

  Scenario: Generate response with graph context
    Given a query and retrieved graph context
    When response generation is requested
    Then a context-aware response is generated

  Scenario: Update knowledge graph from text
    Given new text content
    When graph update is requested
    Then entities and relationships are added to graph

  Scenario: Perform hybrid search
    Given vector and graph indexes
    When hybrid search is executed
    Then results from both indexes are combined

  Scenario: Rank retrieval results
    Given retrieved graph nodes
    When ranking is applied
    Then results are ordered by relevance

  Scenario: Generate graph-aware summaries
    Given a graph subgraph
    When summarization is requested
    Then a summary incorporating graph structure is generated

  Scenario: Handle multi-hop reasoning
    Given a query requiring multi-hop reasoning
    When graph traversal is performed
    Then multi-hop paths are explored
