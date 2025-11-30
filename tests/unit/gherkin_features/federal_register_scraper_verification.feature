Feature: Federal Register Scraper Verification
  The Federal Register scraper verification tool tests the Federal Register
  scraper functionality. It validates connection to federalregister.gov API,
  document searching, agency filtering, date range filtering, and data structure.

  Background:
    Given the FederalRegisterVerifier class is initialized
    And the scraper can connect to federalregister.gov API

  # Test Result Logging

  Scenario: Test result logging records passed test
    Given a test named "Sample Test"
    When the test passes with message "Test passed"
    Then the test is logged with status "PASS"
    And the passed counter increments by 1

  Scenario: Test result logging records failed test
    Given a test named "Sample Test"
    When the test fails with message "Test failed"
    Then the test is logged with status "FAIL"
    And the failed counter increments by 1

  Scenario: Test result logging records warning
    Given a test named "Sample Test"
    When the test has warning with message "Test warning"
    Then the test is logged with status "WARN"
    And the warnings counter increments by 1

  # Search Recent Documents

  Scenario: Search documents from last 7 days
    Given start_date is 7 days ago
    And end_date is today
    And limit is 10
    When I call search_federal_register
    Then the result status is "success"
    And the documents array contains at least 1 document
    And each document is within the date range

  Scenario: Search documents returns no results for date range
    Given start_date is 7 days ago
    And end_date is today
    When I call search_federal_register
    And the documents array is empty
    Then a warning is logged with message "No documents found in last 7 days"

  # Scrape by Agency

  Scenario: Scrape documents from EPA
    Given agencies ["EPA"]
    And start_date is 30 days ago
    And end_date is today
    And output_format is "json"
    And include_full_text is false
    And rate_limit_delay is 1.0 second
    And max_documents is 10
    When I call scrape_federal_register
    Then the result status is "success" or "partial_success"
    And the data contains EPA documents

  Scenario: Scrape from agency returns no documents
    Given agencies ["EPA"]
    And start_date is 30 days ago
    And end_date is today
    When I call scrape_federal_register
    And the data array is empty
    Then a warning is logged with message "No EPA documents found in last 30 days"

  # Scrape Multiple Agencies

  Scenario: Scrape documents from EPA and FDA
    Given agencies ["EPA", "FDA"]
    And start_date is 30 days ago
    And end_date is today
    And max_documents is 10
    When I call scrape_federal_register
    Then the result status is "success" or "partial_success"
    And the data contains documents from multiple agencies

  Scenario: Scrape multiple agencies returns no documents
    Given agencies ["EPA", "FDA"]
    And start_date is 30 days ago
    And end_date is today
    When I call scrape_federal_register
    And the data array is empty
    Then a warning is logged with message "No documents found from EPA or FDA"

  # Filter by Document Types

  Scenario: Filter documents by RULE type
    Given document_types ["RULE"]
    And start_date is 60 days ago
    And end_date is today
    And max_documents is 5
    When I call scrape_federal_register
    Then the result status is "success" or "partial_success"
    And the data contains RULE type documents

  Scenario: Filter by document type returns no documents
    Given document_types ["RULE"]
    And start_date is 60 days ago
    And end_date is today
    When I call scrape_federal_register
    And the data array is empty
    Then a warning is logged with message "No RULE documents found in date range"

  # Data Structure Validation

  Scenario: Scraped Federal Register data has valid structure
    Given start_date is 14 days ago
    And end_date is today
    And output_format is "json"
    And max_documents is 3
    When I call scrape_federal_register
    And the result status is "success" or "partial_success"
    Then each document contains field "document_number"
    And each document contains field "title"
    And each document contains field "publication_date"

  Scenario: Scraped data missing required fields
    When I call scrape_federal_register
    And the sample document is missing required fields
    Then a warning is logged with message containing "Missing fields"

  Scenario: Scraped data has no documents to validate
    When I call scrape_federal_register
    And the data array is empty
    Then a warning is logged with message "No data to validate structure"

  # Search with Keywords

  Scenario: Search Federal Register with keyword "environmental"
    Given keywords "environmental"
    And start_date is 30 days ago
    And end_date is today
    And limit is 5
    When I call search_federal_register
    Then the result status is "success"
    And the documents array contains at least 1 match

  Scenario: Search with keywords returns no results
    Given keywords "environmental"
    When I call search_federal_register
    And the documents array is empty
    Then a warning is logged with message "No documents found matching 'environmental'"

  # Full Text Inclusion

  Scenario: Full text is included when requested
    Given start_date is 7 days ago
    And end_date is today
    And include_full_text is true
    And max_documents is 2
    When I call scrape_federal_register
    Then documents contain full_text or body field
    And the test is logged as passed

  Scenario: Full text is excluded when not requested
    Given start_date is 7 days ago
    And end_date is today
    And include_full_text is false
    And max_documents is 2
    When I call scrape_federal_register
    Then documents do not contain full_text or body field

  Scenario: Full text comparison inconclusive
    Given start_date is 7 days ago
    And end_date is today
    When I call scrape_federal_register with and without full text
    And neither result contains full text
    Then a warning is logged with message "Full text not found in either case"

  # Rate Limiting

  Scenario: Rate limiting is respected
    Given start_date is 7 days ago
    And end_date is today
    And rate_limit_delay is 2.0 seconds
    And max_documents is 3
    When I call scrape_federal_register and measure elapsed time
    Then the elapsed time is at least 2.0 seconds
    And the test is logged as passed

  Scenario: Rate limiting completed too quickly
    Given rate_limit_delay is 2.0 seconds
    When I call scrape_federal_register and measure elapsed time
    And the elapsed time is less than 2.0 seconds
    Then a warning is logged with message "Completed too quickly"
    And the message contains "rate limiting may not be working"

  # Verification Summary

  Scenario: Verification summary shows all results
    When I run all verification tests
    Then the summary shows total test count of 8
    And the summary shows passed count
    And the summary shows failed count
    And the summary shows warnings count
    And the summary shows success rate percentage

  Scenario: Verification results are saved to file
    When I run all verification tests
    Then the results are saved to $HOME/.ipfs_datasets/federal_register/verification_results.json
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
