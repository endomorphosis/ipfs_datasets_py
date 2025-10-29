Feature: SPARQL Query Templates
  Template-based SPARQL query generation

  Scenario: Load query template
    Given a SPARQL query template file
    When the template is loaded
    Then the template is available for use

  Scenario: Fill template with parameters
    Given a query template and parameters
    When parameter substitution is performed
    Then a complete SPARQL query is generated

  Scenario: Validate template syntax
    Given a SPARQL template
    When syntax validation is performed
    Then syntax errors are identified

  Scenario: Execute parameterized query
    Given a filled query template
    When query execution is requested
    Then the query is executed against the endpoint

  Scenario: Generate query from pattern
    Given a query pattern
    When query generation is requested
    Then a SPARQL query is created

  Scenario: Combine multiple templates
    Given multiple query templates
    When combination is requested
    Then a unified query is generated

  Scenario: Optimize generated query
    Given a generated SPARQL query
    When optimization is applied
    Then an optimized query is returned

  Scenario: Validate query results
    Given query results
    When validation is performed
    Then result correctness is verified
