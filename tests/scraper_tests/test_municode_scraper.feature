Feature: Municode Library Webscraper
  As a legal data researcher
  I need to scrape municipal codes from Municode Library
  So that I can access structured municipal legal information

  Background:
    Given the Municode Library is available at "https://library.municode.com"
    And the scraper respects a minimum 2-second delay between requests

  # Search Jurisdictions Callable
  
  Scenario: Search jurisdictions by state code
    Given I have a valid two-letter state code "WA"
    When I call search_jurisdictions with state "WA" and limit 10
    Then the response contains a list of jurisdictions
    And the list contains at most 10 jurisdictions
    And each jurisdiction has a name field
    And each jurisdiction has a state field with value "WA"
    And each jurisdiction has a url field
    And each jurisdiction has a provider field with value "municode"

  Scenario: Search jurisdictions by jurisdiction name
    Given I have a jurisdiction name "Seattle"
    When I call search_jurisdictions with jurisdiction "Seattle"
    Then the response contains a list of jurisdictions
    And each jurisdiction name contains "Seattle"
    And each jurisdiction has a url field
    And each jurisdiction has a provider field with value "municode"

  Scenario: Search jurisdictions by keywords
    Given I have a search keyword "zoning"
    When I call search_jurisdictions with keywords "zoning"
    Then the response contains a list of jurisdictions
    And each jurisdiction has a url field
    And each jurisdiction has a provider field with value "municode"

  Scenario: Search jurisdictions with no results
    Given I have an invalid jurisdiction name "NonexistentCity12345"
    When I call search_jurisdictions with jurisdiction "NonexistentCity12345"
    Then the response contains an empty list of jurisdictions

  Scenario: Search jurisdictions with state and limit
    Given I have a valid two-letter state code "CA"
    And I have a limit of 5
    When I call search_jurisdictions with state "CA" and limit 5
    Then the response contains a list of jurisdictions
    And the list contains at most 5 jurisdictions
    And each jurisdiction has a state field with value "CA"

  # Scrape Jurisdiction Callable

  Scenario: Scrape a single jurisdiction successfully
    Given I have a jurisdiction name "Seattle, WA"
    And I have a valid jurisdiction URL "https://library.municode.com/wa/seattle"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://library.municode.com/wa/seattle"
    Then the response contains a jurisdiction field with value "Seattle, WA"
    And the response contains a sections field
    And the sections field is a list
    And each section has a section_number field
    And each section has a title field
    And each section has a text field
    And each section has a source_url field

  Scenario: Scrape jurisdiction with metadata
    Given I have a jurisdiction name "Seattle, WA"
    And I have a valid jurisdiction URL "https://library.municode.com/wa/seattle"
    And metadata extraction is enabled
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://library.municode.com/wa/seattle" and include_metadata true
    Then the response contains a jurisdiction field with value "Seattle, WA"
    And the response contains a sections field
    And each section has a scraped_at field
    And each section has a source_url field

  Scenario: Scrape jurisdiction with section limit
    Given I have a jurisdiction name "Seattle, WA"
    And I have a valid jurisdiction URL "https://library.municode.com/wa/seattle"
    And I have a max_sections value of 10
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://library.municode.com/wa/seattle" and max_sections 10
    Then the response contains a sections field
    And the sections field contains at most 10 sections

  Scenario: Scrape jurisdiction with invalid URL
    Given I have a jurisdiction name "InvalidCity, XX"
    And I have an invalid jurisdiction URL "https://library.municode.com/invalid/url"
    When I call scrape_jurisdiction with jurisdiction "InvalidCity, XX" and url "https://library.municode.com/invalid/url"
    Then the response contains an error field
    And the sections field is empty or missing

  Scenario: Scrape jurisdiction with network timeout
    Given I have a jurisdiction name "Seattle, WA"
    And I have a valid jurisdiction URL "https://library.municode.com/wa/seattle"
    And the network connection times out
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://library.municode.com/wa/seattle"
    Then the response contains an error field
    And the error field indicates a timeout occurred

  # Batch Scrape Callable

  Scenario: Batch scrape multiple jurisdictions
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"]
    Then the response contains a data field
    And the data field is a list with 2 elements
    And each element has a jurisdiction field
    And each element has a sections field

  Scenario: Batch scrape by state
    Given I have a list of states ["WA"]
    And I have a max_jurisdictions value of 5
    When I call batch_scrape with states ["WA"] and max_jurisdictions 5
    Then the response contains a data field
    And the data field contains at most 5 jurisdiction results
    And each result has a jurisdiction field
    And each result has a sections field

  Scenario: Batch scrape with rate limiting
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    And I have a rate_limit_delay of 3.0 seconds
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"] and rate_limit_delay 3.0
    Then the scraper waits at least 3.0 seconds between requests
    And the response contains a data field with 2 elements

  Scenario: Batch scrape with section limit per jurisdiction
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    And I have a max_sections_per_jurisdiction value of 5
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"] and max_sections_per_jurisdiction 5
    Then the response contains a data field
    And each jurisdiction result has at most 5 sections

  Scenario: Batch scrape with output format JSON
    Given I have a list of jurisdictions ["Seattle, WA"]
    And I have an output_format of "json"
    When I call batch_scrape with jurisdictions ["Seattle, WA"] and output_format "json"
    Then the response contains an output_format field with value "json"
    And the response contains a data field

  Scenario: Batch scrape with output format Parquet
    Given I have a list of jurisdictions ["Seattle, WA"]
    And I have an output_format of "parquet"
    When I call batch_scrape with jurisdictions ["Seattle, WA"] and output_format "parquet"
    Then the response contains an output_format field with value "parquet"
    And the response contains a data field

  Scenario: Batch scrape with no jurisdictions or states
    When I call batch_scrape with no jurisdictions and no states
    Then the response contains an error field
    And the error field indicates that jurisdictions or states are required

  Scenario: Batch scrape with metadata enabled
    Given I have a list of jurisdictions ["Seattle, WA"]
    And metadata extraction is enabled
    When I call batch_scrape with jurisdictions ["Seattle, WA"] and include_metadata true
    Then the response contains a data field
    And the response contains a metadata field
    And the metadata field contains a scraped_at field
    And the metadata field contains a jurisdictions_count field
    And the metadata field contains a provider field with value "municode"

  # Error Handling Scenarios

  Scenario: Handle DNS resolution failure
    Given I have a jurisdiction name "Seattle, WA"
    And I have a valid jurisdiction URL "https://library.municode.com/wa/seattle"
    And DNS resolution fails for "library.municode.com"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://library.municode.com/wa/seattle"
    Then the response contains an error field
    And the error field indicates a DNS resolution failure

  Scenario: Handle HTTP 429 Too Many Requests
    Given I have a jurisdiction name "Seattle, WA"
    And I have a valid jurisdiction URL "https://library.municode.com/wa/seattle"
    And the server returns HTTP 429
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://library.municode.com/wa/seattle"
    Then the response contains an error field
    And the error field indicates rate limiting occurred

  Scenario: Handle HTTP 5xx server error
    Given I have a jurisdiction name "Seattle, WA"
    And I have a valid jurisdiction URL "https://library.municode.com/wa/seattle"
    And the server returns HTTP 500
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://library.municode.com/wa/seattle"
    Then the response contains an error field
    And the error field indicates a server error

  Scenario: Handle invalid HTML structure
    Given I have a jurisdiction name "Seattle, WA"
    And I have a valid jurisdiction URL "https://library.municode.com/wa/seattle"
    And the server returns malformed HTML
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://library.municode.com/wa/seattle"
    Then the response contains a sections field
    And the sections field may be empty
    And no exception is raised

  # Rate Limiting Scenarios

  Scenario: Respect minimum rate limit
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR", "Tacoma, WA"]
    And the minimum rate limit is 2.0 seconds
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR", "Tacoma, WA"]
    Then the scraper waits at least 2.0 seconds between each request
    And the total elapsed time is at least 4.0 seconds

  Scenario: Use custom rate limit delay
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    And I have a rate_limit_delay of 5.0 seconds
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"] and rate_limit_delay 5.0
    Then the scraper waits at least 5.0 seconds between requests
    And the total elapsed time is at least 5.0 seconds
