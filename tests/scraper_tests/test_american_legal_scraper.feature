Feature: American Legal Publishing Webscraper
  As a legal data researcher
  I need to scrape municipal codes from American Legal Publishing
  So that I can access structured municipal legal information

  Background:
    Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"

  # Search Jurisdictions Callable

  Scenario: Search jurisdictions by state returns list
    Given I have a valid two-letter state code "WA"
    When I call search_jurisdictions with state "WA" and limit 10
    Then the response contains a list of jurisdictions

  Scenario: Search jurisdictions by state respects limit
    Given I have a valid two-letter state code "WA"
    When I call search_jurisdictions with state "WA" and limit 10
    Then the list contains at most 10 jurisdictions

  Scenario: Search jurisdictions by state includes name field
    Given I have a valid two-letter state code "WA"
    When I call search_jurisdictions with state "WA" and limit 10
    Then each jurisdiction has a name field

  Scenario: Search jurisdictions by state includes state field
    Given I have a valid two-letter state code "WA"
    When I call search_jurisdictions with state "WA" and limit 10
    Then each jurisdiction has a state field with value "WA"

  Scenario: Search jurisdictions by state includes url field
    Given I have a valid two-letter state code "WA"
    When I call search_jurisdictions with state "WA" and limit 10
    Then each jurisdiction has a url field

  Scenario: Search jurisdictions by state includes provider field
    Given I have a valid two-letter state code "WA"
    When I call search_jurisdictions with state "WA" and limit 10
    Then each jurisdiction has a provider field with value "american_legal"

  Scenario: Search jurisdictions by name returns list
    Given I have a jurisdiction name "Seattle"
    When I call search_jurisdictions with jurisdiction "Seattle"
    Then the response contains a list of jurisdictions

  Scenario: Search jurisdictions by name filters by name
    Given I have a jurisdiction name "Seattle"
    When I call search_jurisdictions with jurisdiction "Seattle"
    Then each jurisdiction name contains "Seattle"

  Scenario: Search jurisdictions by name includes url field
    Given I have a jurisdiction name "Seattle"
    When I call search_jurisdictions with jurisdiction "Seattle"
    Then each jurisdiction has a url field

  Scenario: Search jurisdictions by name includes provider field
    Given I have a jurisdiction name "Seattle"
    When I call search_jurisdictions with jurisdiction "Seattle"
    Then each jurisdiction has a provider field with value "american_legal"

  Scenario: Search jurisdictions by keywords returns list
    Given I have a search keyword "zoning"
    When I call search_jurisdictions with keywords "zoning"
    Then the response contains a list of jurisdictions

  Scenario: Search jurisdictions by keywords includes url field
    Given I have a search keyword "zoning"
    When I call search_jurisdictions with keywords "zoning"
    Then each jurisdiction has a url field

  Scenario: Search jurisdictions by keywords includes provider field
    Given I have a search keyword "zoning"
    When I call search_jurisdictions with keywords "zoning"
    Then each jurisdiction has a provider field with value "american_legal"

  Scenario: Search jurisdictions with no results
    Given I have an invalid jurisdiction name "NonexistentCity12345"
    When I call search_jurisdictions with jurisdiction "NonexistentCity12345"
    Then the response contains an empty list of jurisdictions

  Scenario: Search jurisdictions with state and limit returns list
    Given I have a valid two-letter state code "CA"
    When I call search_jurisdictions with state "CA" and limit 5
    Then the response contains a list of jurisdictions

  Scenario: Search jurisdictions with state and limit respects limit
    Given I have a valid two-letter state code "CA"
    When I call search_jurisdictions with state "CA" and limit 5
    Then the list contains at most 5 jurisdictions

  Scenario: Search jurisdictions with state and limit filters by state
    Given I have a valid two-letter state code "CA"
    When I call search_jurisdictions with state "CA" and limit 5
    Then each jurisdiction has a state field with value "CA"

  # Scrape Jurisdiction Callable

  Scenario: Scrape jurisdiction returns jurisdiction field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the response contains a jurisdiction field with value "Seattle, WA"

  Scenario: Scrape jurisdiction returns sections field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the response contains a sections field

  Scenario: Scrape jurisdiction returns sections as list
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the sections field is a list

  Scenario: Scrape jurisdiction includes section_number field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then each section has a section_number field

  Scenario: Scrape jurisdiction includes title field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then each section has a title field

  Scenario: Scrape jurisdiction includes text field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then each section has a text field

  Scenario: Scrape jurisdiction includes source_url field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then each section has a source_url field

  Scenario: Scrape jurisdiction with metadata returns jurisdiction field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle" and include_metadata true
    Then the response contains a jurisdiction field with value "Seattle, WA"

  Scenario: Scrape jurisdiction with metadata returns sections field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle" and include_metadata true
    Then the response contains a sections field

  Scenario: Scrape jurisdiction with metadata includes scraped_at field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle" and include_metadata true
    Then each section has a scraped_at field

  Scenario: Scrape jurisdiction with metadata includes source_url field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle" and include_metadata true
    Then each section has a source_url field

  Scenario: Scrape jurisdiction with section limit returns sections field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle" and max_sections 10
    Then the response contains a sections field

  Scenario: Scrape jurisdiction with section limit respects limit
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle" and max_sections 10
    Then the sections field contains at most 10 sections

  Scenario: Scrape jurisdiction with invalid URL returns error field
    Given I have a jurisdiction name "InvalidCity, XX"
    When I call scrape_jurisdiction with jurisdiction "InvalidCity, XX" and url "https://codelibrary.amlegal.com/invalid/url"
    Then the response contains an error field

  Scenario: Scrape jurisdiction with invalid URL has empty sections
    Given I have a jurisdiction name "InvalidCity, XX"
    When I call scrape_jurisdiction with jurisdiction "InvalidCity, XX" and url "https://codelibrary.amlegal.com/invalid/url"
    Then the sections field is empty or missing

  Scenario: Scrape jurisdiction with network timeout returns error field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the response contains an error field

  Scenario: Scrape jurisdiction with network timeout indicates timeout
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the error field indicates a timeout occurred

  # Batch Scrape Callable

  Scenario: Batch scrape multiple jurisdictions returns data field
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"]
    Then the response contains a data field

  Scenario: Batch scrape multiple jurisdictions returns correct count
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"]
    Then the data field is a list with 2 elements

  Scenario: Batch scrape multiple jurisdictions includes jurisdiction field
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"]
    Then each element has a jurisdiction field

  Scenario: Batch scrape multiple jurisdictions includes sections field
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"]
    Then each element has a sections field

  Scenario: Batch scrape by state returns data field
    Given I have a list of states ["WA"]
    When I call batch_scrape with states ["WA"] and max_jurisdictions 5
    Then the response contains a data field

  Scenario: Batch scrape by state respects max_jurisdictions
    Given I have a list of states ["WA"]
    When I call batch_scrape with states ["WA"] and max_jurisdictions 5
    Then the data field contains at most 5 jurisdiction results

  Scenario: Batch scrape by state includes jurisdiction field
    Given I have a list of states ["WA"]
    When I call batch_scrape with states ["WA"] and max_jurisdictions 5
    Then each result has a jurisdiction field

  Scenario: Batch scrape by state includes sections field
    Given I have a list of states ["WA"]
    When I call batch_scrape with states ["WA"] and max_jurisdictions 5
    Then each result has a sections field

  Scenario: Batch scrape with rate limiting respects delay
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"] and rate_limit_delay 3.0
    Then the scraper waits at least 3.0 seconds between requests

  Scenario: Batch scrape with rate limiting returns data field
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"] and rate_limit_delay 3.0
    Then the response contains a data field with 2 elements

  Scenario: Batch scrape with section limit returns data field
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"] and max_sections_per_jurisdiction 5
    Then the response contains a data field

  Scenario: Batch scrape with section limit respects limit
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"] and max_sections_per_jurisdiction 5
    Then each jurisdiction result has at most 5 sections

  Scenario: Batch scrape with JSON format returns output_format field
    Given I have a list of jurisdictions ["Seattle, WA"]
    When I call batch_scrape with jurisdictions ["Seattle, WA"] and output_format "json"
    Then the response contains an output_format field with value "json"

  Scenario: Batch scrape with JSON format returns data field
    Given I have a list of jurisdictions ["Seattle, WA"]
    When I call batch_scrape with jurisdictions ["Seattle, WA"] and output_format "json"
    Then the response contains a data field

  Scenario: Batch scrape with Parquet format returns output_format field
    Given I have a list of jurisdictions ["Seattle, WA"]
    When I call batch_scrape with jurisdictions ["Seattle, WA"] and output_format "parquet"
    Then the response contains an output_format field with value "parquet"

  Scenario: Batch scrape with Parquet format returns data field
    Given I have a list of jurisdictions ["Seattle, WA"]
    When I call batch_scrape with jurisdictions ["Seattle, WA"] and output_format "parquet"
    Then the response contains a data field

  Scenario: Batch scrape with no inputs returns error field
    When I call batch_scrape with no jurisdictions and no states
    Then the response contains an error field

  Scenario: Batch scrape with no inputs indicates missing parameters
    When I call batch_scrape with no jurisdictions and no states
    Then the error field indicates that jurisdictions or states are required

  Scenario: Batch scrape with metadata returns data field
    Given I have a list of jurisdictions ["Seattle, WA"]
    When I call batch_scrape with jurisdictions ["Seattle, WA"] and include_metadata true
    Then the response contains a data field

  Scenario: Batch scrape with metadata returns metadata field
    Given I have a list of jurisdictions ["Seattle, WA"]
    When I call batch_scrape with jurisdictions ["Seattle, WA"] and include_metadata true
    Then the response contains a metadata field

  Scenario: Batch scrape with metadata includes scraped_at field
    Given I have a list of jurisdictions ["Seattle, WA"]
    When I call batch_scrape with jurisdictions ["Seattle, WA"] and include_metadata true
    Then the metadata field contains a scraped_at field

  Scenario: Batch scrape with metadata includes jurisdictions_count field
    Given I have a list of jurisdictions ["Seattle, WA"]
    When I call batch_scrape with jurisdictions ["Seattle, WA"] and include_metadata true
    Then the metadata field contains a jurisdictions_count field

  Scenario: Batch scrape with metadata includes provider field
    Given I have a list of jurisdictions ["Seattle, WA"]
    When I call batch_scrape with jurisdictions ["Seattle, WA"] and include_metadata true
    Then the metadata field contains a provider field with value "american_legal"

  # Error Handling Scenarios

  Scenario: DNS resolution failure returns error field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the response contains an error field

  Scenario: DNS resolution failure indicates DNS error
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the error field indicates a DNS resolution failure

  Scenario: HTTP 429 returns error field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the response contains an error field

  Scenario: HTTP 429 indicates rate limiting
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the error field indicates rate limiting occurred

  Scenario: HTTP 500 returns error field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the response contains an error field

  Scenario: HTTP 500 indicates server error
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the error field indicates a server error

  Scenario: Invalid HTML returns sections field
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the response contains a sections field

  Scenario: Invalid HTML allows empty sections
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then the sections field may be empty

  Scenario: Invalid HTML does not raise exception
    Given I have a jurisdiction name "Seattle, WA"
    When I call scrape_jurisdiction with jurisdiction "Seattle, WA" and url "https://codelibrary.amlegal.com/codes/seattle"
    Then no exception is raised

  # Rate Limiting Scenarios

  Scenario: Minimum rate limit enforces delay between requests
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR", "Tacoma, WA"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR", "Tacoma, WA"]
    Then the scraper waits at least 2.0 seconds between each request

  Scenario: Minimum rate limit enforces total elapsed time
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR", "Tacoma, WA"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR", "Tacoma, WA"]
    Then the total elapsed time is at least 4.0 seconds

  Scenario: Custom rate limit enforces delay between requests
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"] and rate_limit_delay 5.0
    Then the scraper waits at least 5.0 seconds between requests

  Scenario: Custom rate limit enforces total elapsed time
    Given I have a list of jurisdictions ["Seattle, WA", "Portland, OR"]
    When I call batch_scrape with jurisdictions ["Seattle, WA", "Portland, OR"] and rate_limit_delay 5.0
    Then the total elapsed time is at least 5.0 seconds
