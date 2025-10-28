Feature: Advanced Knowledge Extractor
  Advanced knowledge extraction from text

  Scenario: Extract entities with deep learning
    Given text content
    When deep learning extraction is applied
    Then entities are extracted with high accuracy

  Scenario: Extract complex relationships
    Given text with complex relationships
    When relationship extraction is performed
    Then multi-hop relationships are identified

  Scenario: Perform event extraction
    Given text describing events
    When event extraction is requested
    Then events with participants and times are extracted

  Scenario: Extract causal relationships
    Given text with causal statements
    When causal extraction is performed
    Then cause-effect relationships are identified

  Scenario: Build ontology from text
    Given domain-specific text
    When ontology construction is requested
    Then a domain ontology is built

  Scenario: Extract numerical facts
    Given text with numerical information
    When numerical extraction is performed
    Then quantities and measurements are extracted

  Scenario: Resolve entity ambiguity
    Given ambiguous entity mentions
    When disambiguation is performed
    Then entities are resolved to specific references

  Scenario: Extract temporal relations
    Given text with temporal information
    When temporal relation extraction is performed
    Then time-based relationships are identified
