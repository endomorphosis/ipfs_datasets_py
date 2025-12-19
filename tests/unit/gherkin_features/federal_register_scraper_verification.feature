Feature: Federal Register Scraper Verification
  Verifies Federal Register scraper by running 8 tests that check API connectivity,
  document searching, agency filtering, document type filtering, data structure,
  keyword search, full text inclusion, and rate limiting. The verifier exits with
  code 0 when failed count equals 0, and exits with code 1 when failed count is
  greater than 0.

  Background:
    Given the FederalRegisterVerifier is initialized with empty results dictionary
    And the summary counters are set to total=0, passed=0, failed=0, warnings=0

  # Test 1: Search Recent Documents - Searches for documents from last 7 days

  Scenario: Search Recent Documents test passes when documents are returned
    When search_federal_register(start_date=7_days_ago, end_date=today, limit=10) is called
    And the result["status"] equals "success"
    And len(result["documents"]) is greater than 0
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Search Recent Documents test warns when no documents are returned
    When search_federal_register(start_date=7_days_ago, end_date=today, limit=10) is called
    And the result["status"] equals "success"
    And len(result["documents"]) equals 0
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Search Recent Documents test fails when API returns error status
    When search_federal_register(start_date=7_days_ago, end_date=today, limit=10) is called
    And the result["status"] does not equal "success"
    Then log_test is called with status "FAIL"
    And summary["failed"] increments by 1

  Scenario: Search Recent Documents test fails when exception is raised
    When search_federal_register() raises an exception
    Then log_test is called with status "FAIL" and exception message
    And summary["failed"] increments by 1

  # Test 2: Scrape by Agency - Scrapes EPA documents from last 30 days

  Scenario: Scrape by Agency test passes when EPA documents are returned
    When scrape_federal_register(agencies=["EPA"], start_date=30_days_ago, max_documents=10) is called
    And the result["status"] is in ["success", "partial_success"]
    And len(result["data"]) is greater than 0
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Scrape by Agency test warns when no documents are returned
    When scrape_federal_register(agencies=["EPA"], start_date=30_days_ago, max_documents=10) is called
    And the result["status"] is in ["success", "partial_success"]
    And len(result["data"]) equals 0
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Scrape by Agency test fails when status is error
    When scrape_federal_register(agencies=["EPA"], start_date=30_days_ago, max_documents=10) is called
    And the result["status"] is not in ["success", "partial_success"]
    Then log_test is called with status "FAIL"
    And summary["failed"] increments by 1

  Scenario: Scrape by Agency test fails when exception is raised
    When scrape_federal_register() raises an exception
    Then log_test is called with status "FAIL" and exception message
    And summary["failed"] increments by 1

  # Test 3: Scrape Multiple Agencies - Scrapes EPA and FDA documents

  Scenario: Scrape Multiple Agencies test passes when documents are returned
    When scrape_federal_register(agencies=["EPA","FDA"], start_date=30_days_ago, max_documents=10) is called
    And the result["status"] is in ["success", "partial_success"]
    And len(result["data"]) is greater than 0
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Scrape Multiple Agencies test warns when no documents are returned
    When scrape_federal_register(agencies=["EPA","FDA"], start_date=30_days_ago, max_documents=10) is called
    And the result["status"] is in ["success", "partial_success"]
    And len(result["data"]) equals 0
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Scrape Multiple Agencies test fails when status is error
    When scrape_federal_register(agencies=["EPA","FDA"]) is called
    And the result["status"] is not in ["success", "partial_success"]
    Then log_test is called with status "FAIL"
    And summary["failed"] increments by 1

  # Test 4: Filter by Document Types - Filters for RULE type documents

  Scenario: Document Types test passes when RULE documents are returned
    When scrape_federal_register(document_types=["RULE"], start_date=60_days_ago, max_documents=5) is called
    And the result["status"] is in ["success", "partial_success"]
    And len(result["data"]) is greater than 0
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Document Types test warns when no RULE documents are returned
    When scrape_federal_register(document_types=["RULE"], start_date=60_days_ago, max_documents=5) is called
    And the result["status"] is in ["success", "partial_success"]
    And len(result["data"]) equals 0
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Document Types test fails when status is error
    When scrape_federal_register(document_types=["RULE"]) is called
    And the result["status"] is not in ["success", "partial_success"]
    Then log_test is called with status "FAIL"
    And summary["failed"] increments by 1

  # Test 5: Validate Data Structure - Checks for required fields in scraped data

  Scenario: Data Structure test passes when all required fields exist
    When scrape_federal_register(start_date=14_days_ago, max_documents=3) is called
    And the result["status"] is in ["success", "partial_success"]
    And result["data"][0] contains "document_number"
    And result["data"][0] contains "title"
    And result["data"][0] contains "publication_date"
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Data Structure test warns when required fields are missing
    When scrape_federal_register(start_date=14_days_ago, max_documents=3) is called
    And the result["status"] is in ["success", "partial_success"]
    And result["data"][0] is missing one or more of ["document_number", "title", "publication_date"]
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Data Structure test warns when data array is empty
    When scrape_federal_register(start_date=14_days_ago, max_documents=3) is called
    And the result["status"] is in ["success", "partial_success"]
    And len(result["data"]) equals 0
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Data Structure test fails when scrape returns error status
    When scrape_federal_register(start_date=14_days_ago, max_documents=3) is called
    And the result["status"] is not in ["success", "partial_success"]
    Then log_test is called with status "FAIL"
    And summary["failed"] increments by 1

  # Test 6: Search with Keywords - Searches for "environmental" keyword

  Scenario: Keyword Search test passes when results are returned
    When search_federal_register(keywords="environmental", start_date=30_days_ago, limit=5) is called
    And the result["status"] equals "success"
    And len(result["documents"]) is greater than 0
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Keyword Search test warns when no results are returned
    When search_federal_register(keywords="environmental", start_date=30_days_ago, limit=5) is called
    And the result["status"] equals "success"
    And len(result["documents"]) equals 0
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Keyword Search test warns when status is not success
    When search_federal_register(keywords="environmental", start_date=30_days_ago, limit=5) is called
    And the result["status"] does not equal "success"
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Keyword Search test fails when exception is raised
    When search_federal_register() raises an exception
    Then log_test is called with status "FAIL" and exception message
    And summary["failed"] increments by 1

  # Test 7: Full Text Inclusion - Verifies full_text or body field inclusion

  Scenario: Full Text test passes when full_text or body field exists
    When scrape_federal_register(include_full_text=True, max_documents=2) is called
    And any document in result["data"] contains "full_text" or "body"
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Full Text test passes when exclusion removes full_text field
    When scrape_federal_register(include_full_text=True) returns data with full_text
    And scrape_federal_register(include_full_text=False) returns data without full_text
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Full Text test warns when neither call has full_text field
    When scrape_federal_register(include_full_text=True) returns data
    And no document contains "full_text" or "body"
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Full Text test warns when insufficient data to test
    When scrape_federal_register(include_full_text=True) returns empty data
    Or scrape_federal_register(include_full_text=False) returns empty data
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Full Text test fails when exception is raised
    When scrape_federal_register() raises an exception
    Then log_test is called with status "FAIL" and exception message
    And summary["failed"] increments by 1

  # Test 8: Rate Limiting - Verifies delay between requests is honored

  Scenario: Rate Limiting test passes when elapsed time meets threshold
    When scrape_federal_register(rate_limit_delay=2.0, max_documents=3) is called
    And the elapsed time is greater than or equal to 2.0 seconds
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Rate Limiting test warns when elapsed time is below threshold
    When scrape_federal_register(rate_limit_delay=2.0, max_documents=3) is called
    And the elapsed time is less than 2.0 seconds
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Rate Limiting test fails when exception is raised
    When scrape_federal_register() raises an exception
    Then log_test is called with status "FAIL" and exception message
    And summary["failed"] increments by 1

  # Exit Code Determination

  Scenario: Verifier exits with code 0 when failed count equals 0
    When all 8 tests complete
    And summary["failed"] equals 0
    Then run_all_tests() returns 0
    And sys.exit(0) is called

  Scenario: Verifier exits with code 1 when failed count is greater than 0
    When all 8 tests complete
    And summary["failed"] is greater than 0
    Then run_all_tests() returns 1
    And sys.exit(1) is called

  Scenario: Verifier exits with code 1 when KeyboardInterrupt is caught
    When asyncio.run(main()) raises KeyboardInterrupt
    Then sys.exit(1) is called

  Scenario: Verifier exits with code 1 when unhandled exception is caught
    When asyncio.run(main()) raises Exception
    Then traceback is printed
    And sys.exit(1) is called
