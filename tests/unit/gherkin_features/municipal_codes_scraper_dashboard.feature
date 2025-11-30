Feature: Municipal Codes Scraper Dashboard Integration Tests
  Pytest-based end-to-end tests for Municipal Codes Scraper MCP tool in Dashboard UI.
  These tests validate UI element rendering, JavaScript SDK integration, MCP tool
  invocation, results display, and error handling.

  Background:
    Given the dashboard URL is http://localhost:8899/mcp

  # Tab Navigation

  Scenario: Municipal Codes tab exists in navigation
    Given the MCP dashboard is loaded
    When I inspect the navigation elements
    Then the Municipal Codes Scraper tab is visible

  Scenario: Navigate to Municipal Codes Scraper section
    Given the MCP dashboard is loaded
    When I click the Municipal Codes Scraper tab
    Then the municipal codes scraper section is displayed

  # Form Elements

  Scenario: All required form elements are present
    Given the Municipal Codes Scraper section is displayed
    When I inspect the form elements
    Then the Jurisdictions input is present
    And the Provider select is present
    And the Output format select is present
    And the Rate limit input is present
    And the Max sections input is present
    And the Scraper type select is present
    And the Include metadata checkbox is present
    And the Include text checkbox is present
    And the Job ID input is present
    And the Resume checkbox is present
    And the Start Scraping button is present
    And the Clear Form button is present

  # Single Jurisdiction Scraping

  Scenario: Scrape single jurisdiction
    Given the Municipal Codes Scraper form
    When I enter jurisdiction "Seattle, WA"
    And I select provider "municode"
    And I click "Start Scraping"
    Then the tool is called via MCP API
    And results display job ID and status

  # Multiple Jurisdictions Scraping

  Scenario: Scrape multiple jurisdictions
    Given the Municipal Codes Scraper form
    When I enter jurisdictions "Seattle, WA; Portland, OR; Austin, TX"
    And I click "Start Scraping"
    Then the tool is called via MCP API
    And results show all 3 jurisdictions

  # Form Validation

  Scenario: Error displayed when submitting without jurisdictions
    Given the Municipal Codes Scraper form
    When I click "Start Scraping" without entering jurisdictions
    Then an error message is displayed
    And the message indicates jurisdictions are required

  # Clear Form

  Scenario: Clear form resets fields to defaults
    Given the Municipal Codes Scraper form with data entered
    When I click "Clear Form"
    Then all form fields reset to default values
    And the results area shows "Form cleared" message

  # Custom Parameters

  Scenario: Configure and submit custom parameters
    Given the Municipal Codes Scraper form
    When I configure:
      | parameter        | value    |
      | Rate limit       | 3.0      |
      | Max sections     | 1000     |
      | Scraper type     | selenium |
      | Include metadata | checked  |
      | Include text     | unchecked|
    And I click "Start Scraping"
    Then the tool is called with these parameters
    And the response reflects the configuration

  # Provider Options

  Scenario: Provider dropdown contains all options
    Given the Municipal Codes Scraper form
    When I check the provider dropdown options
    Then the options include:
      | provider       |
      | Auto-detect    |
      | Municode       |
      | American Legal |
      | General Code   |
      | LexisNexis     |

  # Output Format Options

  Scenario: Output format dropdown contains all options
    Given the Municipal Codes Scraper form
    When I check the output format dropdown options
    Then the options include:
      | format  |
      | JSON    |
      | Parquet |
      | SQL     |

  # Information Panel

  Scenario: Information panel displays tool details
    Given the Municipal Codes Scraper section
    When I check the information panel
    Then the panel displays tool description
    And the panel shows coverage information with ~22,899+ municipalities
    And the panel shows provider statistics
    And the panel describes job management features
    And the panel explains output format details

  # MCP Tool Integration

  Scenario: Tool is correctly invoked via MCP protocol
    Given the following test data:
      | field          | value                      |
      | jurisdictions  | Seattle, WA; Portland, OR  |
      | provider       | municode                   |
      | output_format  | json                       |
      | rate_limit     | 2.0                        |
      | scraper_type   | playwright                 |
      | include_metadata | true                     |
      | include_text   | true                       |
    When the scraping is triggered
    Then the MCP tool returns expected structure:
      | field         | expectation                       |
      | status        | success                           |
      | job_id        | starts with "municipal_codes_"    |
      | jurisdictions | Seattle, WA and Portland, OR      |
      | provider      | municode                          |
      | output_format | json                              |
