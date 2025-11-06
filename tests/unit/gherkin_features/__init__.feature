Feature: Package Initialization
  Python package initialization and exports

  Scenario: Import package
    Given the package is installed
    When the package is imported
    Then the package loads successfully

  Scenario: Access exported modules
    Given the package is imported
    When modules are accessed
    Then all exported modules are available

  Scenario: Check package version
    Given the package is imported
    When version is accessed
    Then the version is returned

  Scenario: Access package metadata
    Given the package is imported
    When metadata is accessed
    Then package information is available

  Scenario: Initialize package resources
    Given the package is imported
    When initialization completes
    Then package resources are ready

  Scenario: Handle import errors
    Given missing dependencies
    When import is attempted
    Then appropriate error is raised

  Scenario: Lazy load heavy dependencies
    Given optional heavy dependencies
    When package is imported
    Then heavy dependencies are loaded on demand

  Scenario: Configure package on import
    Given package configuration
    When package is imported
    Then configuration is applied
