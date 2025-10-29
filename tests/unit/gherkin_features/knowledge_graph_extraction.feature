Feature: Knowledge Graph Extraction
  Extract and construct knowledge graphs from text

  Scenario: Extract entities from text
    Given a text document
    When entity extraction is performed
    Then entities are identified

  Scenario: Extract relationships from text
    Given a text document with entity relationships
    When relationship extraction is performed
    Then relationships are identified

  Scenario: Build knowledge graph from text
    Given a text document
    When knowledge graph construction is requested
    Then a graph with nodes and edges is created

  Scenario: Identify entity types
    Given extracted entities
    When type classification is performed
    Then entity types are assigned

  Scenario: Resolve entity coreferences
    Given text with multiple entity mentions
    When coreference resolution is performed
    Then mentions are linked to entities

  Scenario: Extract temporal information
    Given text with temporal expressions
    When temporal extraction is performed
    Then dates and times are identified

  Scenario: Link entities to knowledge base
    Given extracted entities
    When entity linking is performed
    Then entities are linked to knowledge base IDs

  Scenario: Merge knowledge graphs
    Given multiple knowledge graphs
    When merging is performed
    Then a unified graph is created

  Scenario: Query knowledge graph
    Given a constructed knowledge graph
    When a query is executed
    Then relevant graph data is returned

  Scenario: Export knowledge graph
    Given a knowledge graph
    When export is requested in a format
    Then the graph is serialized to the format
