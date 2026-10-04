Feature: Website GraphRAG System
  Complete GraphRAG system for websites

  Scenario: Initialize website GraphRAG system
    Given system configuration
    When the system is initialized
    Then the system is ready to process websites

  Scenario: Process website end-to-end
    Given a website URL
    When end-to-end processing is requested
    Then the website is crawled, processed, and indexed

  Scenario: Answer questions about website
    Given a processed website
    And a user question
    When question answering is requested
    Then an answer based on website content is generated

  Scenario: Generate website summary
    Given a processed website
    When summarization is requested
    Then a comprehensive summary is generated

  Scenario: Compare multiple websites
    Given multiple processed websites
    When comparison is requested
    Then similarities and differences are identified

  Scenario: Track website changes over time
    Given multiple snapshots of a website
    When change tracking is enabled
    Then changes over time are identified

  Scenario: Extract key topics from website
    Given a processed website
    When topic extraction is requested
    Then main topics are identified

  Scenario: Visualize website knowledge graph
    Given a website knowledge graph
    When visualization is requested
    Then the graph is rendered visually
