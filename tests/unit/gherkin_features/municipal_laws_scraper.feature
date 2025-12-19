Feature: Municipal Laws Scraper
  The municipal laws scraper searches and scrapes municipal codes and ordinances
  from major US cities for building municipal code datasets.

  Background:
    Given the municipal laws scraper module is loaded
    And the list of major cities includes 23 US cities

  # Search Municipal Codes

  Scenario: Search municipal codes for a valid city by name
    Given a city name "New York City"
    When I search municipal codes for that city
    Then the search returns status "success"
    And the search returns one ordinance
    And the ordinance city is "New York City"
    And the ordinance state is "NY"

  Scenario: Search municipal codes for a city using partial name match
    Given a city name "los angeles"
    When I search municipal codes for that city
    Then the search returns status "success"
    And the matching city code is "LAX"
    And the matching city name is "Los Angeles"

  Scenario: Search municipal codes for an unknown city
    Given a city name "Unknown City XYZ"
    When I search municipal codes for that city
    Then the search returns status "error"
    And the error message contains "not found in database"
    And the ordinances list is empty
    And the count is 0

  Scenario: Search municipal codes without specifying a city
    When I search municipal codes without a city name
    Then the search returns status "success"
    And the ordinances list is empty

  # Scrape Municipal Laws

  Scenario: Scrape municipal laws for a single city by code
    Given a list of cities containing "NYC"
    And output format is "json"
    And include_metadata is true
    When I scrape municipal laws
    Then the scrape returns status "success"
    And the data contains one city entry
    And the city code is "NYC"
    And the city name is "New York City"
    And the state is "NY"
    And the metadata includes cities_count of 1
    And the metadata includes ordinances_count greater than 0

  Scenario: Scrape municipal laws for multiple cities
    Given a list of cities containing "NYC", "LAX", "CHI"
    When I scrape municipal laws
    Then the scrape returns status "success"
    And the data contains 3 city entries
    And the metadata cities_scraped list has 3 items

  Scenario: Scrape municipal laws with city name instead of code
    Given a list of cities containing "Seattle"
    When I scrape municipal laws
    Then the scrape returns status "success"
    And the data contains the city "Seattle"

  Scenario: Scrape municipal laws for all cities
    Given a list of cities containing "all"
    When I scrape municipal laws
    Then the scrape returns status "success"
    And the data contains all 23 major cities

  Scenario: Scrape municipal laws with no valid cities
    Given a list of cities containing "InvalidCity123"
    When I scrape municipal laws
    Then the scrape returns status "error"
    And the error message contains "No valid cities specified"

  Scenario: Scrape municipal laws respects rate limiting
    Given a list of cities containing "NYC", "LAX"
    And rate_limit_delay is 2.0 seconds
    When I scrape municipal laws
    Then the elapsed time is at least 2.0 seconds

  Scenario: Scrape municipal laws respects max_ordinances limit
    Given a list of cities containing "all"
    And max_ordinances is 5
    When I scrape municipal laws
    Then the total ordinances count is at most 5

  Scenario: Scrape municipal laws includes metadata when requested
    Given a list of cities containing "NYC"
    And include_metadata is true
    When I scrape municipal laws
    Then each ordinance contains enacted_date
    And each ordinance contains effective_date
    And each ordinance contains last_amended
    And each ordinance contains sponsor

  Scenario: Scrape municipal laws excludes metadata when not requested
    Given a list of cities containing "NYC"
    And include_metadata is false
    When I scrape municipal laws
    Then ordinance enacted_date is null
    And ordinance effective_date is null
    And ordinance last_amended is null
    And ordinance sponsor is null

  # Data Structure Validation

  Scenario: Scraped ordinance data has required fields
    Given a list of cities containing "NYC"
    When I scrape municipal laws
    Then each city entry contains city_code
    And each city entry contains city_name
    And each city entry contains state
    And each city entry contains title
    And each city entry contains source
    And each city entry contains source_url
    And each city entry contains scraped_at
    And each city entry contains ordinances list

  Scenario: Scraped ordinance entry has required fields
    Given a list of cities containing "NYC"
    When I scrape municipal laws
    Then each ordinance contains ordinance_number
    And each ordinance contains chapter
    And each ordinance contains title
    And each ordinance contains text
    And each ordinance contains type

  # Output Format

  Scenario: Scrape returns JSON format indicator
    Given output format is "json"
    When I scrape municipal laws for "NYC"
    Then the output_format field is "json"

  Scenario: Scrape returns Parquet format indicator
    Given output format is "parquet"
    When I scrape municipal laws for "NYC"
    Then the output_format field is "parquet"
