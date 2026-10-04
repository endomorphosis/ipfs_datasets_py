Feature: Enhanced RAG Visualization
  Enhanced visualization for RAG systems

  Scenario: Visualize retrieval results
    Given RAG retrieval results
    When visualization is requested
    Then retrieval results are displayed graphically

  Scenario: Display attention patterns
    Given generation with attention weights
    When attention visualization is requested
    Then attention patterns are visualized

  Scenario: Show knowledge graph context
    Given retrieved knowledge graph context
    When graph visualization is requested
    Then the context graph is displayed

  Scenario: Visualize embedding space
    Given vector embeddings
    When embedding visualization is requested
    Then embeddings are projected and displayed

  Scenario: Display retrieval relevance scores
    Given retrieval results with scores
    When score visualization is requested
    Then relevance scores are displayed

  Scenario: Visualize generation process
    Given a generation trace
    When process visualization is requested
    Then the generation steps are visualized

  Scenario: Compare retrieval strategies
    Given results from different strategies
    When comparison visualization is requested
    Then strategy differences are displayed

  Scenario: Export visualization
    Given a visualization
    When export is requested
    Then the visualization is saved as image or data
