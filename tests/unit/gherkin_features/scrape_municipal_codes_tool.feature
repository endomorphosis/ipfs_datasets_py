Feature: Scrape Municipal Codes MCP Tool
  Unit tests for the ScrapeMunicipalCodesTool MCP tool that integrates
  the scrape_the_law_mk3 submodule. Tests cover tool initialization,
  schema validation, parameter handling, job management, and fallback methods.

  Background:
    Given the ScrapeMunicipalCodesTool class is imported from legal_dataset_mcp_tools

  # Tool Initialization

  Scenario: Tool instance is created successfully
    When I instantiate ScrapeMunicipalCodesTool
    Then the instance is created without errors

  Scenario: Tool has correct name
    Given a ScrapeMunicipalCodesTool instance
    Then the tool name is "scrape_municipal_codes"

  Scenario: Tool has correct description
    Given a ScrapeMunicipalCodesTool instance
    Then the description contains "municipal"
    And the description contains "scrape_the_law_mk3"

  Scenario: Tool has correct category
    Given a ScrapeMunicipalCodesTool instance
    Then the category is "legal_datasets"

  Scenario: Tool has correct tags
    Given a ScrapeMunicipalCodesTool instance
    Then the tags include "municipal"
    And the tags include "codes"

  # Input Schema Structure

  Scenario: Input schema is object type
    Given a ScrapeMunicipalCodesTool instance
    Then the input schema type is "object"

  Scenario: Input schema has all required properties
    Given a ScrapeMunicipalCodesTool instance
    When I examine the input schema properties
    Then the schema includes "jurisdiction"
    And the schema includes "jurisdictions"
    And the schema includes "provider"
    And the schema includes "output_format"
    And the schema includes "include_metadata"
    And the schema includes "include_text"
    And the schema includes "rate_limit_delay"
    And the schema includes "max_sections"
    And the schema includes "scraper_type"
    And the schema includes "job_id"
    And the schema includes "resume"

  # Get Schema Method

  Scenario: Get schema returns complete tool metadata
    Given a ScrapeMunicipalCodesTool instance
    When I call get_schema()
    Then the result contains name "scrape_municipal_codes"
    And the result contains description
    And the result contains input_schema
    And the result contains category "legal_datasets"
    And the result contains tags
    And the result contains version

  # Execute with Single Jurisdiction

  Scenario: Execute with single jurisdiction string
    Given a ScrapeMunicipalCodesTool instance
    And parameters with jurisdiction "New York, NY"
    And provider "auto"
    And output_format "json"
    When I execute the tool
    Then the result status is "success"
    And the result contains job_id
    And the jurisdictions list contains "New York, NY"
    And the provider is "auto"
    And the output_format is "json"

  # Execute with Multiple Jurisdictions

  Scenario: Execute with multiple jurisdictions array
    Given a ScrapeMunicipalCodesTool instance
    And parameters with jurisdictions ["New York, NY", "Los Angeles, CA", "Chicago, IL"]
    And provider "municode"
    And output_format "parquet"
    When I execute the tool
    Then the result status is "success"
    And the result contains job_id
    And the jurisdictions list has 3 entries
    And the jurisdictions list contains "New York, NY"
    And the jurisdictions list contains "Los Angeles, CA"
    And the jurisdictions list contains "Chicago, IL"

  # Execute without Jurisdiction

  Scenario: Execute without specifying jurisdictions returns error
    Given a ScrapeMunicipalCodesTool instance
    And parameters with only provider "auto"
    When I execute the tool
    Then the result status is "error"
    And the error message contains "No jurisdictions specified"

  # Custom Job ID

  Scenario: Execute with custom job_id uses provided ID
    Given a ScrapeMunicipalCodesTool instance
    And parameters with jurisdiction "Boston, MA"
    And job_id "custom_job_123"
    When I execute the tool
    Then the result status is "success"
    And the job_id is "custom_job_123"

  # All Parameters

  Scenario: Execute with all possible parameters
    Given a ScrapeMunicipalCodesTool instance
    And parameters:
      | parameter        | value                                    |
      | jurisdiction     | Seattle, WA                              |
      | provider         | general_code                             |
      | output_format    | sql                                      |
      | include_metadata | true                                     |
      | include_text     | true                                     |
      | rate_limit_delay | 3.0                                      |
      | max_sections     | 1000                                     |
      | scraper_type     | selenium                                 |
      | enable_fallbacks | true                                     |
      | fallback_methods | wayback_machine, common_crawl, playwright|
      | job_id           | full_test_job                            |
      | resume           | false                                    |
    When I execute the tool
    Then the result status is "success"
    And the job_id is "full_test_job"
    And the provider is "general_code"
    And the scraper_type is "selenium"
    And the output_format is "sql"
    And enable_fallbacks is true
    And fallback_methods contains 3 methods

  # Auto Job ID Generation

  Scenario: Execute without job_id generates auto job_id
    Given a ScrapeMunicipalCodesTool instance
    And parameters with jurisdiction "Portland, OR"
    When I execute the tool
    Then the result status is "success"
    And the job_id starts with "municipal_codes_"

  # Resume Capability

  Scenario: Execute with resume capability
    Given a ScrapeMunicipalCodesTool instance
    And parameters with jurisdiction "Austin, TX"
    And job_id "resume_test_job"
    And resume is true
    When I execute the tool
    Then the result status is "success"
    And the job_id is "resume_test_job"

  # Tool Registration in MCP

  Scenario: Tool is included in LEGAL_DATASET_MCP_TOOLS list
    When I import LEGAL_DATASET_MCP_TOOLS
    Then the list contains a tool named "scrape_municipal_codes"

  Scenario: Tool is accessible via TemporalDeonticMCPServer
    When I instantiate TemporalDeonticMCPServer
    Then the server tools include "scrape_municipal_codes"
    And the tool name is "scrape_municipal_codes"

  # Fallback Methods Enabled

  Scenario: Execute with fallback methods enabled
    Given a ScrapeMunicipalCodesTool instance
    And parameters with jurisdiction "Portland, OR"
    And enable_fallbacks is true
    And fallback_methods ["wayback_machine", "archive_is", "common_crawl"]
    When I execute the tool
    Then the result status is "success"
    And enable_fallbacks is true
    And fallback_methods contains 3 entries
    And fallback_methods contains "wayback_machine"
    And fallback_methods contains "archive_is"
    And fallback_methods contains "common_crawl"
    And metadata contains "fallback_strategy"

  # Fallback Methods Disabled

  Scenario: Execute with fallbacks disabled
    Given a ScrapeMunicipalCodesTool instance
    And parameters with jurisdiction "Denver, CO"
    And enable_fallbacks is false
    When I execute the tool
    Then the result status is "success"
    And enable_fallbacks is false
    And fallback_methods is an empty list
