Feature: Jsonnet Configuration
  Template-based configuration using Jsonnet

  Scenario: Parse Jsonnet template
    Given a valid Jsonnet template
    When the template is parsed
    Then a JSON object is returned

  Scenario: Evaluate Jsonnet with variables
    Given a Jsonnet template with variables
    And variable values are provided
    When the template is evaluated
    Then variables are substituted

  Scenario: Import external Jsonnet files
    Given a Jsonnet template with imports
    When the template is evaluated
    Then imported files are included

  Scenario: Handle Jsonnet functions
    Given a Jsonnet template with custom functions
    When the template is evaluated
    Then functions are executed

  Scenario: Validate Jsonnet syntax
    Given a Jsonnet template
    When syntax validation is performed
    Then syntax errors are detected

  Scenario: Generate configuration from template
    Given a Jsonnet configuration template
    When configuration generation is requested
    Then a configuration object is created

  Scenario: Handle Jsonnet errors
    Given an invalid Jsonnet template
    When evaluation is attempted
    Then an error is raised with details

  Scenario: Support Jsonnet conditionals
    Given a Jsonnet template with conditionals
    When the template is evaluated
    Then conditional logic is applied

  Scenario: Merge Jsonnet configurations
    Given multiple Jsonnet templates
    When merging is performed
    Then a combined configuration is created
