Feature: Website GraphRAG Processor
  Process websites for GraphRAG system

  Scenario: Extract content from website
    Given a website URL
    When content extraction is requested
    Then website content is extracted

  Scenario: Build site structure graph
    Given a website
    When structure analysis is performed
    Then a site structure graph is created

  Scenario: Extract entities from website
    Given website content
    When entity extraction is performed
    Then entities are identified across pages

  Scenario: Link related pages
    Given multiple website pages
    When page linking is performed
    Then semantic relationships between pages are identified

  Scenario: Generate site knowledge graph
    Given a processed website
    When knowledge graph generation is requested
    Then a website knowledge graph is created

  Scenario: Index website for RAG
    Given a processed website
    When RAG indexing is performed
    Then the site is indexed for retrieval

  Scenario: Query website knowledge
    Given an indexed website
    And a user query
    When query processing is performed
    Then relevant website knowledge is retrieved

  Scenario: Update website graph incrementally
    Given an existing website graph
    And new website content
    When incremental update is performed
    Then the graph is updated with new content
