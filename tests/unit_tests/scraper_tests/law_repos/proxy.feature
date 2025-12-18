Feature: Proxy for Web Scraping
  As a web scraper operator
  I need proxy functionality to rotate IP addresses and headers
  So that I can scrape websites without being blocked

  Background:
    Given the proxy callable is available

  # Proxy Configuration

  Scenario: Create proxy with single HTTP proxy URL
    Given I have a proxy URL "http://proxy1.example.com:8080"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    Then the proxy contains 1 proxy URL

  Scenario: Create proxy with single HTTPS proxy URL
    Given I have a proxy URL "https://proxy1.example.com:8443"
    When I call proxy with proxy_url "https://proxy1.example.com:8443"
    Then the proxy contains 1 proxy URL

  Scenario: Create proxy with single SOCKS5 proxy URL
    Given I have a proxy URL "socks5://proxy1.example.com:1080"
    When I call proxy with proxy_url "socks5://proxy1.example.com:1080"
    Then the proxy contains 1 proxy URL

  Scenario: Create proxy with list of proxy URLs
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080", "http://proxy3.example.com:8080"]
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080", "http://proxy3.example.com:8080"]
    Then the proxy contains 3 proxy URLs

  Scenario: Create proxy with authentication credentials
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have username "testuser"
    And I have password "testpass"
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and username "testuser" and password "testpass"
    Then the proxy URL includes authentication

  Scenario: Create proxy with no proxy URLs
    When I call proxy with no proxy URLs
    Then the proxy returns an error
    And the error indicates proxy URLs are required

  Scenario: Create proxy with empty proxy URL list
    Given I have an empty list of proxy URLs
    When I call proxy with proxy_urls []
    Then the proxy returns an error
    And the error indicates proxy URLs are required

  Scenario: Create proxy with invalid proxy URL format
    Given I have a proxy URL "not-a-url"
    When I call proxy with proxy_url "not-a-url"
    Then the proxy returns an error
    And the error indicates invalid URL format

  Scenario: Create proxy with invalid proxy protocol
    Given I have a proxy URL "ftp://proxy1.example.com:8080"
    When I call proxy with proxy_url "ftp://proxy1.example.com:8080"
    Then the proxy returns an error
    And the error indicates unsupported protocol

  # Proxy Rotation

  Scenario: Get proxy from list rotates to first proxy
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I call get_next_proxy
    Then the proxy returns "http://proxy1.example.com:8080"

  Scenario: Get proxy from list rotates to second proxy
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I call get_next_proxy 2 times
    Then the proxy returns "http://proxy2.example.com:8080"

  Scenario: Get proxy from list rotates back to first proxy
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I call get_next_proxy 3 times
    Then the proxy returns "http://proxy1.example.com:8080"

  Scenario: Get proxy from single URL returns same URL
    Given I have a proxy URL "http://proxy1.example.com:8080"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call get_next_proxy 5 times
    Then the proxy returns "http://proxy1.example.com:8080"

  # Request Execution with Proxy

  Scenario: Execute request with single proxy
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call execute_request with url "https://library.municode.com"
    Then the request uses proxy "http://proxy1.example.com:8080"

  Scenario: Execute request with rotating proxies
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I call execute_request with url "https://library.municode.com" 2 times
    Then the first request uses proxy "http://proxy1.example.com:8080"
    And the second request uses proxy "http://proxy2.example.com:8080"

  Scenario: Execute request returns response body
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call execute_request with url "https://library.municode.com"
    Then the response contains a body field

  Scenario: Execute request returns status code
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call execute_request with url "https://library.municode.com"
    Then the response contains a status_code field

  Scenario: Execute request returns headers
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call execute_request with url "https://library.municode.com"
    Then the response contains a headers field

  # Custom Headers

  Scenario: Execute request with custom User-Agent header
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    And I have a User-Agent header "Mozilla/5.0"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call execute_request with url "https://library.municode.com" and headers {"User-Agent": "Mozilla/5.0"}
    Then the request includes header "User-Agent" with value "Mozilla/5.0"

  Scenario: Execute request with custom Accept header
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    And I have an Accept header "text/html"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call execute_request with url "https://library.municode.com" and headers {"Accept": "text/html"}
    Then the request includes header "Accept" with value "text/html"

  Scenario: Execute request with custom Referer header
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com/wa/seattle"
    And I have a Referer header "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call execute_request with url "https://library.municode.com/wa/seattle" and headers {"Referer": "https://library.municode.com"}
    Then the request includes header "Referer" with value "https://library.municode.com"

  Scenario: Execute request with multiple custom headers
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    And I have headers {"User-Agent": "Mozilla/5.0", "Accept": "text/html", "Accept-Language": "en-US"}
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call execute_request with url "https://library.municode.com" and headers {"User-Agent": "Mozilla/5.0", "Accept": "text/html", "Accept-Language": "en-US"}
    Then the request includes header "User-Agent" with value "Mozilla/5.0"
    And the request includes header "Accept" with value "text/html"
    And the request includes header "Accept-Language" with value "en-US"

  # Header Rotation

  Scenario: Rotate User-Agent headers on each request
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    And I have User-Agent headers ["Mozilla/5.0 Chrome", "Mozilla/5.0 Firefox", "Mozilla/5.0 Safari"]
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and user_agents ["Mozilla/5.0 Chrome", "Mozilla/5.0 Firefox", "Mozilla/5.0 Safari"]
    And I call execute_request with url "https://library.municode.com" 3 times
    Then the first request uses User-Agent "Mozilla/5.0 Chrome"
    And the second request uses User-Agent "Mozilla/5.0 Firefox"
    And the third request uses User-Agent "Mozilla/5.0 Safari"

  Scenario: Rotate User-Agent headers wraps to first header
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    And I have User-Agent headers ["Mozilla/5.0 Chrome", "Mozilla/5.0 Firefox"]
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and user_agents ["Mozilla/5.0 Chrome", "Mozilla/5.0 Firefox"]
    And I call execute_request with url "https://library.municode.com" 3 times
    Then the third request uses User-Agent "Mozilla/5.0 Chrome"

  # Retry Logic

  Scenario: Retry request on HTTP 429 error
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3
    And I call execute_request with url "https://library.municode.com"
    And the first request returns HTTP 429
    Then the proxy retries with proxy "http://proxy2.example.com:8080"

  Scenario: Retry request on HTTP 503 error
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3
    And I call execute_request with url "https://library.municode.com"
    And the first request returns HTTP 503
    Then the proxy retries with proxy "http://proxy2.example.com:8080"

  Scenario: Retry request on connection timeout
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3
    And I call execute_request with url "https://library.municode.com"
    And the first request times out
    Then the proxy retries with proxy "http://proxy2.example.com:8080"

  Scenario: Retry request on DNS resolution failure
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3
    And I call execute_request with url "https://library.municode.com"
    And the first request fails with DNS error
    Then the proxy retries with proxy "http://proxy2.example.com:8080"

  Scenario: Retry request respects max_retries limit
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 2
    And I call execute_request with url "https://library.municode.com"
    And all requests return HTTP 429
    Then the proxy attempts 2 retries
    And the proxy returns an error
    And the error indicates max retries exceeded

  Scenario: Retry request does not retry on HTTP 404 error
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com/invalid"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3
    And I call execute_request with url "https://library.municode.com/invalid"
    And the first request returns HTTP 404
    Then the proxy does not retry
    And the response has status_code 404

  Scenario: Retry request does not retry on HTTP 200 success
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3
    And I call execute_request with url "https://library.municode.com"
    And the first request returns HTTP 200
    Then the proxy does not retry
    And the response has status_code 200

  # Retry Backoff Strategy

  Scenario: Retry with exponential backoff waits before retry
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and backoff_strategy "exponential"
    And I call execute_request with url "https://library.municode.com"
    And the first request returns HTTP 429
    Then the proxy waits before retry

  Scenario: Retry with exponential backoff increases wait time
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and backoff_strategy "exponential"
    And I call execute_request with url "https://library.municode.com"
    And the first request returns HTTP 429
    And the second request returns HTTP 429
    Then the second retry wait time is greater than first retry wait time

  Scenario: Retry with linear backoff waits before retry
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and backoff_strategy "linear"
    And I call execute_request with url "https://library.municode.com"
    And the first request returns HTTP 429
    Then the proxy waits before retry

  Scenario: Retry with linear backoff maintains constant wait time
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and backoff_strategy "linear" and backoff_delay 2.0
    And I call execute_request with url "https://library.municode.com"
    And the first request returns HTTP 429
    And the second request returns HTTP 429
    Then the first retry waits 2.0 seconds
    And the second retry waits 2.0 seconds

  # Timeout Configuration

  Scenario: Execute request with custom timeout
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and timeout 30.0
    And I call execute_request with url "https://library.municode.com"
    Then the request timeout is 30.0 seconds

  Scenario: Execute request with default timeout
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call execute_request with url "https://library.municode.com"
    Then the request timeout is 30.0 seconds

  Scenario: Execute request timeout returns error
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and timeout 1.0
    And I call execute_request with url "https://library.municode.com"
    And the request takes longer than 1.0 seconds
    Then the proxy returns an error
    And the error indicates timeout

  # Connection Pooling

  Scenario: Proxy maintains connection pool
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and pool_size 10
    Then the proxy creates a connection pool with 10 connections

  Scenario: Proxy reuses connections from pool
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and pool_size 10
    And I call execute_request with url "https://library.municode.com" 5 times
    Then the proxy reuses connections from pool

  Scenario: Proxy creates new connection when pool is empty
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and pool_size 2
    And I call execute_request with url "https://library.municode.com" 3 times
    Then the proxy creates a new connection for third request

  # Session Management

  Scenario: Proxy maintains session with cookies
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and maintain_session true
    And I call execute_request with url "https://library.municode.com"
    And the response sets cookie "session_id" with value "abc123"
    And I call execute_request with url "https://library.municode.com/wa/seattle"
    Then the second request includes cookie "session_id" with value "abc123"

  Scenario: Proxy does not maintain session when disabled
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and maintain_session false
    And I call execute_request with url "https://library.municode.com"
    And the response sets cookie "session_id" with value "abc123"
    And I call execute_request with url "https://library.municode.com/wa/seattle"
    Then the second request does not include cookie "session_id"

  # Rate Limiting

  Scenario: Proxy enforces rate limit between requests
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and rate_limit_delay 2.0
    And I call execute_request with url "https://library.municode.com" 2 times
    Then the proxy waits at least 2.0 seconds between requests

  Scenario: Proxy enforces rate limit with multiple requests
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and rate_limit_delay 1.0
    And I call execute_request with url "https://library.municode.com" 5 times
    Then the total elapsed time is at least 4.0 seconds

  Scenario: Proxy rate limit with zero delay does not wait
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and rate_limit_delay 0.0
    And I call execute_request with url "https://library.municode.com" 3 times
    Then the proxy does not wait between requests

  # Proxy Health Monitoring

  Scenario: Mark proxy as unhealthy after failed request
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and health_check true
    And I call execute_request with url "https://library.municode.com"
    And the first request fails with connection error
    Then the proxy marks "http://proxy1.example.com:8080" as unhealthy

  Scenario: Skip unhealthy proxy on next request
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and health_check true
    And I call execute_request with url "https://library.municode.com"
    And the first request fails with connection error
    And I call execute_request with url "https://library.municode.com"
    Then the second request uses proxy "http://proxy2.example.com:8080"

  Scenario: Retry unhealthy proxy after cooldown period
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and health_check true and health_check_cooldown 5.0
    And I call execute_request with url "https://library.municode.com"
    And the first request fails with connection error
    And 5.0 seconds pass
    And I call execute_request with url "https://library.municode.com" 2 times
    Then the proxy attempts to use "http://proxy1.example.com:8080"

  # Statistics and Monitoring

  Scenario: Proxy tracks request count
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call execute_request with url "https://library.municode.com" 5 times
    And I call get_statistics
    Then the statistics show 5 total requests

  Scenario: Proxy tracks success count
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call execute_request with url "https://library.municode.com" 5 times
    And all requests return HTTP 200
    And I call get_statistics
    Then the statistics show 5 successful requests

  Scenario: Proxy tracks failure count
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call execute_request with url "https://library.municode.com" 5 times
    And all requests return HTTP 429
    And I call get_statistics
    Then the statistics show 5 failed requests

  Scenario: Proxy tracks requests per proxy
    Given I have proxy URLs ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    And I call execute_request with url "https://library.municode.com" 4 times
    And I call get_statistics
    Then the statistics show 2 requests for "http://proxy1.example.com:8080"
    And the statistics show 2 requests for "http://proxy2.example.com:8080"

  # Context Manager Support

  Scenario: Proxy supports context manager protocol
    Given I have a proxy URL "http://proxy1.example.com:8080"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I use proxy as context manager
    Then the proxy context manager enters
    And the proxy context manager exits

  Scenario: Proxy cleans up resources on context exit
    Given I have a proxy URL "http://proxy1.example.com:8080"
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and pool_size 10
    And I use proxy as context manager
    And the context manager exits
    Then the proxy closes all connections

  # Async Support

  Scenario: Proxy supports async execute_request
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have a target URL "https://library.municode.com"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call async execute_request with url "https://library.municode.com"
    Then the request executes asynchronously
    And the response contains a body field

  Scenario: Proxy supports concurrent async requests
    Given I have a proxy URL "http://proxy1.example.com:8080"
    And I have target URLs ["https://library.municode.com", "https://codelibrary.amlegal.com", "https://ecode360.com"]
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call async execute_request with urls ["https://library.municode.com", "https://codelibrary.amlegal.com", "https://ecode360.com"] concurrently
    Then all 3 requests execute concurrently
    And all responses contain a body field

  # Integration with Scrapers

  Scenario: Use proxy with municode scraper
    Given I have a proxy URL "http://proxy1.example.com:8080"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call municode search_jurisdictions with state "WA" using proxy
    Then the request uses proxy "http://proxy1.example.com:8080"
    And the response contains a list of jurisdictions

  Scenario: Use proxy with american_legal scraper
    Given I have a proxy URL "http://proxy1.example.com:8080"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call american_legal search_jurisdictions with state "WA" using proxy
    Then the request uses proxy "http://proxy1.example.com:8080"
    And the response contains a list of jurisdictions

  Scenario: Use proxy with ecode360 scraper
    Given I have a proxy URL "http://proxy1.example.com:8080"
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    And I call ecode360 search_jurisdictions with state "WA" using proxy
    Then the request uses proxy "http://proxy1.example.com:8080"
    And the response contains a list of jurisdictions
