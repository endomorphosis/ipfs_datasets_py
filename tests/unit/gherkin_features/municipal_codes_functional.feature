Feature: Municipal Codes Dashboard Functional Tests
  Playwright-based end-to-end tests for the Municipal Codes Scraper integration
  in the MCP Dashboard. These tests validate UI elements, form interactions,
  JavaScript SDK integration, and tool invocation.

  Background:
    Given a Chromium browser is launched in headless mode
    And the viewport is 1920x1080 pixels
    And the MCP dashboard is running at http://localhost:8899/mcp
    And the screenshot directory exists at test_screenshots

  # Dashboard Navigation

  Scenario: Dashboard loads successfully
    When I navigate to the dashboard URL
    And I wait for network idle
    Then the page loads without errors
    And I save a screenshot as "01_dashboard_loaded.png"

  Scenario: Municipal Codes Scraper tab exists
    When I navigate to the dashboard URL
    Then the Municipal Codes Scraper tab is present in navigation
    And the tab has data-target attribute "municipal-codes-scraper"

  Scenario: Municipal Codes Scraper tab not found
    When I navigate to the dashboard URL
    And the Municipal Codes Scraper tab is not present
    Then the test fails with message "Municipal Codes Scraper tab not found!"

  Scenario: Click Municipal Codes Scraper tab
    When I navigate to the dashboard URL
    And I click the Municipal Codes Scraper tab
    Then the municipal codes scraper section is displayed
    And I save a screenshot as "02_municipal_codes_tab.png"

  # Form Elements Verification

  Scenario: Verify all form elements are present
    When I navigate to the Municipal Codes Scraper section
    Then the Jurisdictions input is present with selector "input#municipal-jurisdictions"
    And the Provider select is present with selector "select#municipal-provider"
    And the Output format select is present with selector "select#municipal-output-format"
    And the Rate limit input is present with selector "input#municipal-rate-limit"
    And the Max sections input is present with selector "input#municipal-max-sections"
    And the Scraper type select is present with selector "select#municipal-scraper-type"
    And the Include metadata checkbox is present with selector "input#municipal-include-metadata"
    And the Include text checkbox is present with selector "input#municipal-include-text"
    And the Job ID input is present with selector "input#municipal-job-id"
    And the Resume checkbox is present with selector "input#municipal-resume"

  Scenario: Form element missing
    When I navigate to the Municipal Codes Scraper section
    And a required form element is missing
    Then the test fails with message containing "NOT FOUND"

  # Form Filling

  Scenario: Fill form with test data
    When I navigate to the Municipal Codes Scraper section
    And I fill Jurisdictions with "Seattle, WA"
    And I select Provider as "municode"
    And I select Output format as "json"
    And I fill Rate limit with "2.0"
    And I select Scraper type as "playwright"
    Then all form fields contain the entered values
    And I save a screenshot as "03_form_filled.png"

  # Form Validation

  Scenario: Submit form without jurisdictions shows error
    When I navigate to the Municipal Codes Scraper section
    And I clear the Jurisdictions field
    And I invoke scrapeMunicipalCodes JavaScript function
    And I wait 1 second
    Then the results div contains "Error" or "specify at least one jurisdiction"
    And I save a screenshot as "04_validation_error.png"

  Scenario: Validation error not detected without server
    When I navigate to the Municipal Codes Scraper section
    And I submit an empty form
    And no validation error is displayed
    Then a warning is logged "Validation error not detected (might need server running)"

  # Form Submission

  Scenario: Submit form with multiple jurisdictions
    When I navigate to the Municipal Codes Scraper section
    And I fill Jurisdictions with "Seattle, WA; Portland, OR"
    And I select Provider as "municode"
    And I invoke scrapeMunicipalCodes JavaScript function
    And I wait 2 seconds
    Then results are displayed in the municipal-results div
    And the results preview is logged
    And I save a screenshot as "05_scraping_results.png"

  # Clear Form

  Scenario: Clear form resets all fields
    When I navigate to the Municipal Codes Scraper section
    And I fill the form with test data
    And I invoke clearMunicipalForm JavaScript function
    And I wait 500 milliseconds
    Then the Jurisdictions field is empty
    And I save a screenshot as "06_form_cleared.png"

  Scenario: Clear form not fully cleared
    When I invoke clearMunicipalForm JavaScript function
    And the Jurisdictions field still has a value
    Then a warning is logged "Form not fully cleared"

  # Information Panel

  Scenario: Information panel displays expected content
    When I navigate to the Municipal Codes Scraper section
    Then the info panel in #municipal-codes-scraper contains "22,899+"
    And the info panel contains "Municode"

  Scenario: Information panel content incomplete
    When I navigate to the Municipal Codes Scraper section
    And the info panel does not contain expected content
    Then a warning is logged "Information panel content incomplete"

  Scenario: Information panel not found
    When I navigate to the Municipal Codes Scraper section
    And the info panel selector returns no elements
    Then a warning is logged "Information panel not found"

  # Screenshot Documentation

  Scenario: All screenshots are captured on successful test
    When I run the complete integration test
    Then 6 screenshots are saved:
      | filename                    | description           |
      | 01_dashboard_loaded.png     | Dashboard loaded      |
      | 02_municipal_codes_tab.png  | Municipal Codes tab   |
      | 03_form_filled.png          | Form filled           |
      | 04_validation_error.png     | Validation error      |
      | 05_scraping_results.png     | Scraping results      |
      | 06_form_cleared.png         | Form cleared          |

  # Error Handling

  Scenario: Test fails with exception
    When I run the integration test
    And an exception occurs
    Then an error screenshot is saved as "error_screenshot.png"
    And the traceback is printed

  Scenario: Browser is closed after test
    When I run the integration test
    Then the browser is closed regardless of test result

  # Prerequisites Check

  Scenario: MCP dashboard is accessible
    When I check if the dashboard is accessible at http://localhost:8899/mcp
    And the request succeeds within 2 seconds
    Then the message "MCP dashboard is running" is logged

  Scenario: MCP dashboard is not accessible
    When I check if the dashboard is accessible
    And the request times out or fails
    Then a warning is logged "MCP dashboard not accessible"
    And instructions to start the dashboard are displayed
    And tests proceed with expected connection errors

  # Test Exit Status

  Scenario: Integration test passes
    When I run the complete integration test
    And all checks pass
    Then the message "ALL TESTS COMPLETED SUCCESSFULLY" is displayed
    And the exit code is 0

  Scenario: Integration test fails
    When I run the complete integration test
    And any check fails
    Then the message "Integration test FAILED" is displayed
    And the exit code is 1
