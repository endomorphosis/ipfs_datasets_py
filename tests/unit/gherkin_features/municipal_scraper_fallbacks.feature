Feature: Municipal Scraper Fallback Methods
  The municipal scraper fallback system provides multiple strategies to retrieve
  municipal codes when primary sources are unavailable. It tries methods in sequence
  until data retrieval succeeds.

  Background:
    Given the MunicipalScraperFallbacks class is initialized
    And 6 fallback methods are supported

  # Supported Methods

  Scenario: List of supported fallback methods
    When I list supported methods
    Then the list contains "common_crawl"
    And the list contains "wayback_machine"
    And the list contains "archive_is"
    And the list contains "autoscraper"
    And the list contains "ipwb"
    And the list contains "playwright"

  Scenario: Get method info for common_crawl
    When I get method info for "common_crawl"
    Then the description is "Query Common Crawl archives for historical municipal website data"
    And the method is marked as supported

  Scenario: Get method info for wayback_machine
    When I get method info for "wayback_machine"
    Then the description is "Retrieve archived snapshots from Internet Archive's Wayback Machine"
    And the method is marked as supported

  Scenario: Get method info for archive_is
    When I get method info for "archive_is"
    Then the description is "Access webpage archives from Archive.is service"
    And the method is marked as supported

  Scenario: Get method info for autoscraper
    When I get method info for "autoscraper"
    Then the description is "Use AutoScraper for pattern-based data extraction"
    And the method is marked as supported

  Scenario: Get method info for ipwb
    When I get method info for "ipwb"
    Then the description is "Query InterPlanetary Wayback for decentralized web archives"
    And the method is marked as supported

  Scenario: Get method info for playwright
    When I get method info for "playwright"
    Then the description is "Direct browser automation as final fallback"
    And the method is marked as supported

  Scenario: Get method info for unknown method
    When I get method info for "unknown_method"
    Then the result contains an error message "Unknown method: unknown_method"

  # Scraping with Fallbacks

  Scenario: Scrape with fallbacks returns jurisdiction and URL
    Given a target URL "https://library.municode.com/seattle"
    And a jurisdiction "Seattle, WA"
    And fallback methods ["common_crawl", "wayback_machine"]
    When I scrape with fallbacks
    Then the result contains jurisdiction "Seattle, WA"
    And the result contains url "https://library.municode.com/seattle"

  Scenario: Scrape with fallbacks records all attempts
    Given a target URL "https://library.municode.com/portland"
    And a jurisdiction "Portland, OR"
    And fallback methods ["common_crawl", "wayback_machine", "archive_is"]
    When I scrape with fallbacks
    Then the attempts list contains 3 entries
    And each attempt contains method name
    And each attempt contains success status
    And each attempt contains timestamp

  Scenario: Scrape with fallbacks stops on first success
    Given a target URL "https://library.municode.com/austin"
    And a jurisdiction "Austin, TX"
    And the "wayback_machine" method returns success
    And fallback methods ["common_crawl", "wayback_machine", "playwright"]
    When I scrape with fallbacks
    Then the result success is true
    And the successful_method in metadata is "wayback_machine"
    And the attempts list contains 2 entries

  Scenario: Scrape with fallbacks skips unknown methods
    Given a target URL "https://library.municode.com/denver"
    And a jurisdiction "Denver, CO"
    And fallback methods ["invalid_method", "common_crawl"]
    When I scrape with fallbacks
    Then the attempts list contains 1 entry
    And the attempt method is "common_crawl"

  Scenario: Scrape with fallbacks handles exceptions
    Given a target URL "https://library.municode.com/miami"
    And a jurisdiction "Miami, FL"
    And the "common_crawl" method throws an exception
    And fallback methods ["common_crawl", "wayback_machine"]
    When I scrape with fallbacks
    Then the first attempt success is false
    And the first attempt contains error message
    And the attempts list contains 2 entries

  # Individual Fallback Methods

  Scenario: Common Crawl fallback returns expected structure
    Given a target URL "https://library.municode.com/boston"
    And a jurisdiction "Boston, MA"
    When I call the common_crawl fallback method
    Then the result contains success status
    And the result contains message
    And the result contains metadata with method "common_crawl"

  Scenario: Wayback Machine fallback returns expected structure
    Given a target URL "https://library.municode.com/chicago"
    And a jurisdiction "Chicago, IL"
    When I call the wayback_machine fallback method
    Then the result contains success status
    And the result contains message
    And the result contains metadata with method "wayback_machine"

  Scenario: Archive.is fallback returns expected structure
    Given a target URL "https://library.municode.com/houston"
    And a jurisdiction "Houston, TX"
    When I call the archive_is fallback method
    Then the result contains success status
    And the result contains message
    And the result contains metadata with method "archive_is"

  Scenario: AutoScraper fallback returns expected structure
    Given a target URL "https://library.municode.com/phoenix"
    And a jurisdiction "Phoenix, AZ"
    When I call the autoscraper fallback method
    Then the result contains success status
    And the result contains message
    And the result contains metadata with method "autoscraper"

  Scenario: IPWB fallback returns expected structure
    Given a target URL "https://library.municode.com/dallas"
    And a jurisdiction "Dallas, TX"
    When I call the ipwb fallback method
    Then the result contains success status
    And the result contains message
    And the result contains metadata with method "ipwb"

  Scenario: Playwright fallback returns expected structure
    Given a target URL "https://library.municode.com/san-jose"
    And a jurisdiction "San Jose, CA"
    When I call the playwright fallback method
    Then the result contains success status
    And the result contains message
    And the result contains metadata with method "playwright"

  # Default Fallback Order

  Scenario: Default fallback order when no methods specified
    Given a target URL "https://library.municode.com/atlanta"
    And a jurisdiction "Atlanta, GA"
    When I scrape with fallbacks using default methods
    Then the first attempted method is "wayback_machine"
    And the second attempted method is "archive_is"
    And the third attempted method is "common_crawl"
    And the fourth attempted method is "ipwb"
    And the fifth attempted method is "autoscraper"
    And the sixth attempted method is "playwright"
