Feature: Cross-Document Lineage Enhanced
  Enhanced cross-document lineage tracking

  Scenario: Track complex document relationships
    Given documents with complex relationships
    When enhanced lineage tracking is enabled
    Then all relationship types are captured

  Scenario: Build temporal lineage graph
    Given documents with temporal dependencies
    When temporal graph construction is requested
    Then a temporal lineage graph is built

  Scenario: Detect circular dependencies
    Given document lineage data
    When circular dependency detection runs
    Then circular references are identified

  Scenario: Compute transitive relationships
    Given direct document relationships
    When transitive closure is computed
    Then all indirect relationships are derived

  Scenario: Validate lineage integrity
    Given a lineage graph
    When integrity validation is performed
    Then lineage consistency is verified

  Scenario: Query lineage with path constraints
    Given lineage data and path constraints
    When constrained query is executed
    Then matching paths are returned

  Scenario: Visualize complex lineage
    Given complex document lineage
    When enhanced visualization is requested
    Then an interactive lineage graph is displayed

  Scenario: Export lineage metadata
    Given lineage information
    When metadata export is requested
    Then lineage metadata is exported
