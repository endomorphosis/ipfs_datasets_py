Feature: Simple Web Crawler
  Basic web crawling functionality

  Scenario: Crawl single web page
    Given a starting URL
    When crawling is initiated
    Then the page content is retrieved

  Scenario: Follow links to depth
    Given a starting URL and crawl depth
    When crawling is initiated
    Then pages are crawled to specified depth

  Scenario: Respect robots.txt
    Given a website with robots.txt
    When crawling is initiated
    Then robots.txt rules are respected

  Scenario: Handle rate limiting
    Given rate limit settings
    When crawling is initiated
    Then requests are rate limited

  Scenario: Extract links from page
    Given a crawled page
    When link extraction is performed
    Then all links are identified

  Scenario: Store crawled pages
    Given crawled page content
    When storage is requested
    Then pages are stored

  Scenario: Track crawled URLs
    Given ongoing crawling
    When URLs are visited
    Then visited URLs are tracked to avoid duplicates

  Scenario: Handle crawl errors
    Given a URL that returns an error
    When crawling is attempted
    Then the error is logged
    And crawling continues with other URLs
