Feature: Advanced GraphRAG Website Processor
  Advanced website processing for GraphRAG

  Scenario: Extract structured data from website
    Given a website with structured data
    When structured data extraction is performed
    Then schema.org and other structured data is extracted

  Scenario: Analyze website semantics
    Given a website
    When semantic analysis is performed
    Then semantic relationships are identified

  Scenario: Build hierarchical content structure
    Given a website with hierarchy
    When structure analysis is performed
    Then a hierarchical content graph is created

  Scenario: Extract website metadata
    Given a website
    When metadata extraction is performed
    Then page titles, descriptions, and metadata are extracted

  Scenario: Identify content themes
    Given website content
    When theme identification is performed
    Then main content themes are identified

  Scenario: Link internal and external references
    Given a website with references
    When reference linking is performed
    Then internal and external links are mapped

  Scenario: Generate contextual embeddings
    Given website content
    When embedding generation is requested
    Then context-aware embeddings are created

  Scenario: Optimize website graph for retrieval
    Given a website knowledge graph
    When optimization is applied
    Then the graph is optimized for efficient retrieval
