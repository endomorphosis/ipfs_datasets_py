Feature: GraphRAG Website Example
  Example implementation of GraphRAG for websites

  Scenario: Run website processing example
    Given an example website URL
    When the example is executed
    Then the website is processed successfully

  Scenario: Demonstrate entity extraction
    Given example website content
    When entity extraction example runs
    Then entities are extracted and displayed

  Scenario: Show knowledge graph construction
    Given example processing results
    When graph construction example runs
    Then a knowledge graph is built and displayed

  Scenario: Demonstrate question answering
    Given an example knowledge graph
    And example questions
    When QA example runs
    Then answers are generated and displayed

  Scenario: Show retrieval visualization
    Given example retrieval results
    When visualization example runs
    Then retrieval process is visualized

  Scenario: Demonstrate incremental updates
    Given an existing example graph
    And new content
    When update example runs
    Then the graph is updated incrementally

  Scenario: Show performance metrics
    Given example processing run
    When metrics example runs
    Then performance metrics are displayed

  Scenario: Demonstrate error handling
    Given example with errors
    When error handling example runs
    Then errors are handled and reported
