Feature: US Code Scraper Verification
  The US Code scraper verification tool tests the US Code scraper functionality.
  It validates connection to uscode.house.gov, title fetching, section scraping,
  data structure, and rate limiting.

  Background:
    Given the USCodeVerifier class is initialized
    And the scraper can connect to uscode.house.gov

  # Test Result Logging

  Scenario: Test result logging records passed test
    Given a test named "Sample Test"
    When the test passes with message "Test passed"
    Then the test is logged with status "PASS"
    And the passed counter increments by 1
    And the total counter increments by 1

  Scenario: Test result logging records failed test
    Given a test named "Sample Test"
    When the test fails with message "Test failed"
    Then the test is logged with status "FAIL"
    And the failed counter increments by 1
    And the total counter increments by 1

  Scenario: Test result logging records warning
    Given a test named "Sample Test"
    When the test has warning with message "Test warning"
    Then the test is logged with status "WARN"
    And the warnings counter increments by 1
    And the total counter increments by 1

  # Get US Code Titles

  Scenario: Get US Code titles returns all titles
    When I call get_us_code_titles
    Then the result status is "success"
    And the titles dictionary contains at least 50 entries

  Scenario: Get US Code titles returns fewer than expected
    When I call get_us_code_titles
    And the titles count is less than 50
    Then a warning is logged with message containing "Retrieved only"

  Scenario: Get US Code titles fails
    When I call get_us_code_titles
    And the result status is "error"
    Then the test is logged as failed
    And the error message is captured

  # Scrape Single Title

  Scenario: Scrape single US Code title succeeds
    Given title "1" (General Provisions)
    And output_format is "json"
    And include_metadata is true
    And rate_limit_delay is 1.0 second
    And max_sections is 10
    When I call scrape_us_code
    Then the result status is "success"
    And the data array contains at least 1 section
    And each section contains title_number
    And each section contains section_number

  Scenario: Scrape single US Code title returns no sections
    Given title "1"
    When I call scrape_us_code
    And the data array is empty
    Then a warning is logged with message "No sections scraped from Title 1"

  # Scrape Multiple Titles

  Scenario: Scrape multiple US Code titles
    Given titles ["1", "15", "18"]
    And max_sections is 5 per title
    When I call scrape_us_code
    Then the result status is "success" or "partial_success"
    And the data contains sections from at least 2 different titles

  Scenario: Scrape multiple titles partial success
    Given titles ["1", "15", "18"]
    When I call scrape_us_code
    And only 1 title is scraped
    Then a warning is logged with message "Only scraped 1 title"

  # Data Structure Validation

  Scenario: Scraped US Code data has valid structure
    Given title "15" (Commerce and Trade)
    And max_sections is 3
    When I call scrape_us_code
    And the result status is "success" or "partial_success"
    Then each section contains field "title_number"
    And each section contains field "title_name"
    And each section contains field "section_number"

  Scenario: Scraped US Code data missing required fields
    Given title "15"
    When I call scrape_us_code
    And the sample section is missing required fields
    Then a warning is logged with message containing "Missing fields"

  # Search Functionality

  Scenario: Search US Code by keyword
    Given search query "commerce"
    And titles ["15"]
    And limit is 5
    When I call search_us_code
    Then the result status is "success"
    And the results array contains at least 1 match

  Scenario: Search US Code returns no results
    Given search query "commerce"
    When I call search_us_code
    And the results array is empty
    Then a warning is logged with message "No search results found"

  # Metadata Inclusion

  Scenario: Metadata is included when requested
    Given title "1"
    And include_metadata is true
    And max_sections is 2
    When I call scrape_us_code
    Then the result contains a metadata object
    And the test is logged as passed

  Scenario: Metadata is excluded when not requested
    Given title "1"
    And include_metadata is false
    And max_sections is 2
    When I call scrape_us_code
    Then the result metadata is empty or minimal

  # Rate Limiting

  Scenario: Rate limiting is respected
    Given title "1"
    And rate_limit_delay is 2.0 seconds
    And max_sections is 3
    When I call scrape_us_code and measure elapsed time
    Then the elapsed time is at least 2.0 seconds
    And the test is logged as passed

  Scenario: Rate limiting completed too quickly
    Given title "1"
    And rate_limit_delay is 2.0 seconds
    When I call scrape_us_code and measure elapsed time
    And the elapsed time is less than 2.0 seconds
    Then a warning is logged with message "Completed too quickly"
    And the message contains "rate limiting may not be working"

  # Verification Summary

  Scenario: Verification summary shows all results
    When I run all verification tests
    Then the summary shows total test count
    And the summary shows passed count
    And the summary shows failed count
    And the summary shows warnings count
    And the summary shows success rate percentage

  Scenario: Verification results are saved to file
    When I run all verification tests
    Then the results are saved to ~/.ipfs_datasets/us_code/verification_results.json
    And the file contains timestamp
    And the file contains tests array
    And the file contains summary object

  Scenario: Verification exits with code 0 on all tests passed
    When I run all verification tests
    And all tests pass
    Then the exit code is 0

  Scenario: Verification exits with code 1 on any test failed
    When I run all verification tests
    And at least one test fails
    Then the exit code is 1
