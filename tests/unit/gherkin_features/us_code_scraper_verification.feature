Feature: US Code Scraper Verification
  Verifies US Code scraper by running 7 tests that check API connectivity,
  data retrieval, structure validation, search, metadata, and rate limiting.
  The verifier exits with code 0 when failed count equals 0, and exits with
  code 1 when failed count is greater than 0.

  Background:
    Given the USCodeVerifier is initialized with empty results dictionary
    And the summary counters are set to total=0, passed=0, failed=0, warnings=0

  # Test 1: Get US Code Titles - Verifies title list retrieval from uscode.house.gov

  Scenario: Get Titles test passes when API returns 50+ titles
    When get_us_code_titles() is called
    And the result["status"] equals "success"
    And len(result["titles"]) is greater than or equal to 50
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Get Titles test warns when API returns fewer than 50 titles
    When get_us_code_titles() is called
    And the result["status"] equals "success"
    And len(result["titles"]) is less than 50
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Get Titles test fails when API returns error status
    When get_us_code_titles() is called
    And the result["status"] does not equal "success"
    Then log_test is called with status "FAIL"
    And summary["failed"] increments by 1

  Scenario: Get Titles test fails when exception is raised
    When get_us_code_titles() raises an exception
    Then log_test is called with status "FAIL" and exception message
    And summary["failed"] increments by 1

  # Test 2: Scrape Single Title - Verifies scraping Title 1 with max_sections=10

  Scenario: Scrape Single Title test passes when data array has entries
    When scrape_us_code(titles=["1"], max_sections=10) is called
    And the result["status"] equals "success"
    And len(result["data"]) is greater than 0
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Scrape Single Title test warns when data array is empty
    When scrape_us_code(titles=["1"], max_sections=10) is called
    And the result["status"] equals "success"
    And len(result["data"]) equals 0
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Scrape Single Title test fails when status is not success
    When scrape_us_code(titles=["1"], max_sections=10) is called
    And the result["status"] does not equal "success"
    Then log_test is called with status "FAIL"
    And summary["failed"] increments by 1

  Scenario: Scrape Single Title test fails when exception is raised
    When scrape_us_code() raises an exception
    Then log_test is called with status "FAIL" and exception message
    And summary["failed"] increments by 1

  # Test 3: Scrape Multiple Titles - Verifies scraping titles ["1","15","18"] with max_sections=5

  Scenario: Scrape Multiple Titles test passes when 2+ titles are found
    When scrape_us_code(titles=["1","15","18"], max_sections=5) is called
    And the result["status"] is in ["success", "partial_success"]
    And sections contain title_number values from 2 or more different titles
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Scrape Multiple Titles test warns when only 1 title is found
    When scrape_us_code(titles=["1","15","18"], max_sections=5) is called
    And the result["status"] is in ["success", "partial_success"]
    And sections contain title_number values from only 1 title
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Scrape Multiple Titles test warns when no title_number field exists
    When scrape_us_code(titles=["1","15","18"], max_sections=5) is called
    And the result["status"] is in ["success", "partial_success"]
    And no section contains title_number field
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Scrape Multiple Titles test fails when status is error
    When scrape_us_code(titles=["1","15","18"]) is called
    And the result["status"] is not in ["success", "partial_success"]
    Then log_test is called with status "FAIL"
    And summary["failed"] increments by 1

  # Test 4: Validate Data Structure - Checks for required fields in scraped data

  Scenario: Data Structure test passes when all required fields exist
    When scrape_us_code(titles=["15"], max_sections=3) is called
    And the result["status"] is in ["success", "partial_success"]
    And result["data"][0] contains "title_number"
    And result["data"][0] contains "title_name"
    And result["data"][0] contains "section_number"
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Data Structure test warns when required fields are missing
    When scrape_us_code(titles=["15"], max_sections=3) is called
    And the result["status"] is in ["success", "partial_success"]
    And result["data"][0] is missing one or more of ["title_number", "title_name", "section_number"]
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Data Structure test warns when data array is empty
    When scrape_us_code(titles=["15"], max_sections=3) is called
    And the result["status"] is in ["success", "partial_success"]
    And len(result["data"]) equals 0
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Data Structure test fails when scrape returns error status
    When scrape_us_code(titles=["15"], max_sections=3) is called
    And the result["status"] is not in ["success", "partial_success"]
    Then log_test is called with status "FAIL"
    And summary["failed"] increments by 1

  # Test 5: Search Functionality - Searches for "commerce" in Title 15

  Scenario: Search test passes when results are returned
    When search_us_code(query="commerce", titles=["15"], limit=5) is called
    And the result["status"] equals "success"
    And len(result["results"]) is greater than 0
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Search test warns when no results are returned
    When search_us_code(query="commerce", titles=["15"], limit=5) is called
    And the result["status"] equals "success"
    And len(result["results"]) equals 0
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Search test warns when status is not success
    When search_us_code(query="commerce", titles=["15"], limit=5) is called
    And the result["status"] does not equal "success"
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Search test fails when exception is raised
    When search_us_code() raises an exception
    Then log_test is called with status "FAIL" and exception message
    And summary["failed"] increments by 1

  # Test 6: Metadata Inclusion - Verifies metadata field is present when requested

  Scenario: Metadata test passes when metadata object exists
    When scrape_us_code(titles=["1"], include_metadata=True, max_sections=2) is called
    And bool(result["metadata"]) is True
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Metadata test warns when metadata object is empty or missing
    When scrape_us_code(titles=["1"], include_metadata=True, max_sections=2) is called
    And bool(result["metadata"]) is False
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Metadata test fails when exception is raised
    When scrape_us_code() raises an exception
    Then log_test is called with status "FAIL" and exception message
    And summary["failed"] increments by 1

  # Test 7: Rate Limiting - Verifies delay between requests is honored

  Scenario: Rate Limiting test passes when elapsed time meets threshold
    When scrape_us_code(titles=["1"], rate_limit_delay=2.0, max_sections=3) is called
    And the elapsed time is greater than or equal to 2.0 seconds
    Then log_test is called with status "PASS"
    And summary["passed"] increments by 1

  Scenario: Rate Limiting test warns when elapsed time is below threshold
    When scrape_us_code(titles=["1"], rate_limit_delay=2.0, max_sections=3) is called
    And the elapsed time is less than 2.0 seconds
    Then log_test is called with status "WARN"
    And summary["warnings"] increments by 1

  Scenario: Rate Limiting test fails when exception is raised
    When scrape_us_code() raises an exception
    Then log_test is called with status "FAIL" and exception message
    And summary["failed"] increments by 1

  # Exit Code Determination

  Scenario: Verifier exits with code 0 when failed count equals 0
    When all 7 tests complete
    And summary["failed"] equals 0
    Then run_all_tests() returns 0
    And sys.exit(0) is called

  Scenario: Verifier exits with code 1 when failed count is greater than 0
    When all 7 tests complete
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
