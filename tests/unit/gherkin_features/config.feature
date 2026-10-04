Feature: Configuration Management
  Configuration loading and override functionality for the system

  Scenario: Load configuration from default location
    Given a valid config.toml file exists in the default path
    When the configuration is initialized
    Then the configuration is loaded

  Scenario: Load configuration from custom path
    Given a valid config.toml file exists at a custom path
    When the configuration is initialized with the custom path
    Then the configuration is loaded from the custom path

  Scenario: Override configuration with dictionary
    Given a base configuration is loaded
    And override values are provided as a dictionary
    When the override is applied
    Then the base configuration is updated with override values

  Scenario: Override configuration with file
    Given a base configuration is loaded
    And an override file exists
    When the override file is applied
    Then the base configuration is updated with values from the override file

  Scenario: Find configuration in standard locations
    Given configuration files exist in multiple standard paths
    When the configuration search is executed
    Then the first valid configuration file is found

  Scenario: Handle missing configuration file
    Given no configuration file exists
    When the configuration is required
    Then the system exits with an error

  Scenario: Validate configuration structure
    Given a configuration file with valid TOML structure
    When the configuration is loaded
    Then the configuration contains expected sections

  Scenario: Handle nested configuration overrides
    Given a base configuration with nested sections
    And override values for nested keys
    When the override is applied
    Then only specified nested values are updated
