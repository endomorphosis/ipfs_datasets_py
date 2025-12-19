Feature: Proxy for Web Scraping
  As a web scraper operator
  I need proxy functionality to rotate IP addresses and headers
  So that I can scrape websites without being blocked

  Background:
    Given the proxy callable is available

  # Proxy Configuration

  Scenario: Create proxy with single HTTP proxy URL
    Given a proxy configuration
    When I call proxy with proxy_url "http://proxy1.example.com:8080"
    Then the proxy contains 1 proxy URL

  Scenario: Create proxy with single HTTPS proxy URL
    Given a proxy configuration
    When I call proxy with proxy_url "https://proxy1.example.com:8443"
    Then the proxy contains 1 proxy URL

  Scenario: Create proxy with single SOCKS5 proxy URL
    Given a proxy configuration
    When I call proxy with proxy_url "socks5://proxy1.example.com:1080"
    Then the proxy contains 1 proxy URL

  Scenario: Create proxy with list of proxy URLs
    Given a proxy configuration
    When I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080", "http://proxy3.example.com:8080"]
    Then the proxy contains 3 proxy URLs

  Scenario: Create proxy with authentication credentials
    Given a proxy configuration
    When I call proxy with proxy_url "http://proxy1.example.com:8080" and username "testuser" and password "testpass"
    Then the proxy URL includes authentication

  Scenario: Create proxy with no proxy URLs
    Given a proxy configuration
    When I call proxy with no proxy URLs
    Then the proxy returns an error

  Scenario: Create proxy with empty proxy URL list
    Given a proxy configuration
    When I call proxy with proxy_urls []
    Then the proxy returns an error

  Scenario: Create proxy with invalid proxy URL format
    Given a proxy configuration
    When I call proxy with proxy_url "not-a-url"
    Then the proxy returns an error

  Scenario: Create proxy with invalid proxy protocol
    Given a proxy configuration
    When I call proxy with proxy_url "ftp://proxy1.example.com:8080"
    Then the proxy returns an error

  # Proxy Rotation

  Scenario: Get proxy from list rotates to first proxy
    Given a proxy configuration
    When I call get_next_proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    Then the proxy returns "http://proxy1.example.com:8080"

  Scenario: Get proxy from list rotates to second proxy
    Given a proxy configuration
    When I call get_next_proxy 2 times with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    Then the proxy returns "http://proxy2.example.com:8080"

  Scenario: Get proxy from list rotates back to first proxy
    Given a proxy configuration
    When I call get_next_proxy 3 times with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
    Then the proxy returns "http://proxy1.example.com:8080"

  Scenario: Get proxy from single URL returns same URL
    Given a proxy configuration
    When I call get_next_proxy 5 times with proxy_url "http://proxy1.example.com:8080"
    Then the proxy returns "http://proxy1.example.com:8080"

  # Request Execution with Proxy

  Scenario: Execute request with single proxy
    Given a proxy configuration
    When I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com"
    Then the request uses proxy "http://proxy1.example.com:8080"

  Scenario: Execute request with rotating proxies
    Given a proxy configuration
    When I call execute_request 2 times with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and url "https://library.municode.com"
    Then the first request uses proxy "http://proxy1.example.com:8080"

  Scenario: Execute request returns response body
    Given a proxy configuration
    When I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com"
    Then the response contains a body field

  Scenario: Execute request returns status code
    Given a proxy configuration
    When I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com"
    Then the response contains a status_code field

  Scenario: Execute request returns headers
    Given a proxy configuration
    When I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com"
    Then the response contains a headers field

  # Custom Headers

  Scenario: Execute request with custom User-Agent header
    Given a proxy configuration
    When I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com" and headers {"User-Agent": "Mozilla/5.0"}
    Then the request includes header "User-Agent" with value "Mozilla/5.0"

  Scenario: Execute request with custom Accept header
    Given a proxy configuration
    When I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com" and headers {"Accept": "text/html"}
    Then the request includes header "Accept" with value "text/html"

  Scenario: Execute request with custom Referer header
    Given a proxy configuration
    When I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com/wa/seattle" and headers {"Referer": "https://library.municode.com"}
    Then the request includes header "Referer" with value "https://library.municode.com"

  Scenario: Execute request with multiple custom headers
    Given a proxy configuration
    When I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com" and headers {"User-Agent": "Mozilla/5.0", "Accept": "text/html", "Accept-Language": "en-US"}
    Then the request includes header "User-Agent" with value "Mozilla/5.0"

  # Header Rotation

  Scenario: Rotate User-Agent headers on each request
    Given a proxy configuration
    When I call execute_request 3 times with proxy_url "http://proxy1.example.com:8080" and user_agents ["Mozilla/5.0 Chrome", "Mozilla/5.0 Firefox", "Mozilla/5.0 Safari"] and url "https://library.municode.com"
    Then the first request uses User-Agent "Mozilla/5.0 Chrome"

  Scenario: Rotate User-Agent headers wraps to first header
    Given a proxy configuration
    When I call execute_request 3 times with proxy_url "http://proxy1.example.com:8080" and user_agents ["Mozilla/5.0 Chrome", "Mozilla/5.0 Firefox"] and url "https://library.municode.com"
    Then the third request uses User-Agent "Mozilla/5.0 Chrome"

  # Retry Logic

  Scenario: Retry request on HTTP 429 error
    Given a proxy configuration
    When I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and url "https://library.municode.com" and first_request_returns HTTP 429
    Then the proxy retries with proxy "http://proxy2.example.com:8080"

  Scenario: Retry request on HTTP 503 error
    Given a proxy configuration
    When I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and url "https://library.municode.com" and first_request_returns HTTP 503
    Then the proxy retries with proxy "http://proxy2.example.com:8080"

  Scenario: Retry request on connection timeout
    Given a proxy configuration
    When I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and url "https://library.municode.com" and first_request_times_out
    Then the proxy retries with proxy "http://proxy2.example.com:8080"

  Scenario: Retry request on DNS resolution failure
    Given a proxy configuration
    When I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and url "https://library.municode.com" and first_request_fails_with_DNS_error
    Then the proxy retries with proxy "http://proxy2.example.com:8080"

  Scenario: Retry request respects max_retries limit
    Given a proxy configuration
    When I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 2 and url "https://library.municode.com" and all_requests_return HTTP 429
    Then the proxy attempts 2 retries

  Scenario: Retry request does not retry on HTTP 404 error
    Given a proxy configuration
    When I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and url "https://library.municode.com/invalid" and first_request_returns HTTP 404
    Then the proxy does not retry

  Scenario: Retry request does not retry on HTTP 200 success
    Given a proxy configuration
    When I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and url "https://library.municode.com" and first_request_returns HTTP 200
    Then the proxy does not retry

  # Retry Backoff Strategy

  Scenario: Retry with exponential backoff waits before retry
    Given a proxy configuration
    When I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and backoff_strategy "exponential" and url "https://library.municode.com" and first_request_returns HTTP 429
    Then the proxy waits before retry

  Scenario: Retry with exponential backoff increases wait time
    Given a proxy configuration
    When I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and backoff_strategy "exponential" and url "https://library.municode.com" and first_two_requests_return HTTP 429
    Then the second retry wait time is greater than first retry wait time

  Scenario: Retry with linear backoff waits before retry
    Given a proxy configuration
    When I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and backoff_strategy "linear" and url "https://library.municode.com" and first_request_returns HTTP 429
    Then the proxy waits before retry

  Scenario: Retry with linear backoff maintains constant wait time
    Given a proxy configuration
    When I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and backoff_strategy "linear" and backoff_delay 2.0 and url "https://library.municode.com" and first_two_requests_return HTTP 429
    Then the first retry waits 2.0 seconds

  # Timeout Configuration

  Scenario: Execute request with custom timeout
    Given a proxy configuration
    When I call execute_request with proxy_url "http://proxy1.example.com:8080" and timeout 30.0 and url "https://library.municode.com"
    Then the request timeout is 30.0 seconds

  Scenario: Execute request with default timeout
    Given a proxy configuration
    When I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com"
    Then the request timeout is 30.0 seconds

  Scenario: Execute request timeout returns error
    Given a proxy configuration
    When I call execute_request with proxy_url "http://proxy1.example.com:8080" and timeout 1.0 and url "https://library.municode.com" and request_takes_longer_than 1.0
    Then the proxy returns an error

  # Connection Pooling

  Scenario: Proxy maintains connection pool
    Given a proxy configuration
    When I create proxy with proxy_url "http://proxy1.example.com:8080" and pool_size 10
    Then the proxy creates a connection pool with 10 connections

  Scenario: Proxy reuses connections from pool
    Given a proxy configuration
    When I call execute_request 5 times with proxy_url "http://proxy1.example.com:8080" and pool_size 10 and url "https://library.municode.com"
    Then the proxy reuses connections from pool

  Scenario: Proxy creates new connection when pool is empty
    Given a proxy configuration
    When I call execute_request 3 times with proxy_url "http://proxy1.example.com:8080" and pool_size 2 and url "https://library.municode.com"
    Then the proxy creates a new connection for third request

  # Session Management

  Scenario: Proxy maintains session with cookies
    Given a proxy configuration
    When I call execute_request 2 times with proxy_url "http://proxy1.example.com:8080" and maintain_session true and urls ["https://library.municode.com", "https://library.municode.com/wa/seattle"] and first_response_sets_cookie "session_id" "abc123"
    Then the second request includes cookie "session_id" with value "abc123"

  Scenario: Proxy does not maintain session when disabled
    Given a proxy configuration
    When I call execute_request 2 times with proxy_url "http://proxy1.example.com:8080" and maintain_session false and urls ["https://library.municode.com", "https://library.municode.com/wa/seattle"] and first_response_sets_cookie "session_id" "abc123"
    Then the second request does not include cookie "session_id"

  # Rate Limiting

  Scenario: Proxy enforces rate limit between requests
    Given a proxy configuration
    When I call execute_request 2 times with proxy_url "http://proxy1.example.com:8080" and rate_limit_delay 2.0 and url "https://library.municode.com"
    Then the proxy waits at least 2.0 seconds between requests

  Scenario: Proxy enforces rate limit with multiple requests
    Given a proxy configuration
    When I call execute_request 5 times with proxy_url "http://proxy1.example.com:8080" and rate_limit_delay 1.0 and url "https://library.municode.com"
    Then the total elapsed time is at least 4.0 seconds

  Scenario: Proxy rate limit with zero delay does not wait
    Given a proxy configuration
    When I call execute_request 3 times with proxy_url "http://proxy1.example.com:8080" and rate_limit_delay 0.0 and url "https://library.municode.com"
    Then the proxy does not wait between requests

  # Proxy Health Monitoring

  Scenario: Mark proxy as unhealthy after failed request
    Given a proxy configuration
    When I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and health_check true and url "https://library.municode.com" and first_request_fails_with_connection_error
    Then the proxy marks "http://proxy1.example.com:8080" as unhealthy

  Scenario: Skip unhealthy proxy on next request
    Given a proxy configuration
    When I call execute_request 2 times with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and health_check true and url "https://library.municode.com" and first_request_fails_with_connection_error
    Then the second request uses proxy "http://proxy2.example.com:8080"

  Scenario: Retry unhealthy proxy after cooldown period
    Given a proxy configuration
    When I call execute_request 3 times with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and health_check true and health_check_cooldown 5.0 and url "https://library.municode.com" and first_request_fails_then_wait 5.0
    Then the proxy attempts to use "http://proxy1.example.com:8080"

  # Statistics and Monitoring

  Scenario: Proxy tracks request count
    Given a proxy configuration
    When I call execute_request 5 times with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com" and get_statistics
    Then the statistics show 5 total requests

  Scenario: Proxy tracks success count
    Given a proxy configuration
    When I call execute_request 5 times with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com" and all_requests_return HTTP 200 and get_statistics
    Then the statistics show 5 successful requests

  Scenario: Proxy tracks failure count
    Given a proxy configuration
    When I call execute_request 5 times with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com" and all_requests_return HTTP 429 and get_statistics
    Then the statistics show 5 failed requests

  Scenario: Proxy tracks requests per proxy
    Given a proxy configuration
    When I call execute_request 4 times with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and url "https://library.municode.com" and get_statistics
    Then the statistics show 2 requests for "http://proxy1.example.com:8080"

  # Context Manager Support

  Scenario: Proxy supports context manager protocol
    Given a proxy configuration
    When I use proxy with proxy_url "http://proxy1.example.com:8080" as context manager
    Then the proxy context manager enters

  Scenario: Proxy cleans up resources on context exit
    Given a proxy configuration
    When I use proxy with proxy_url "http://proxy1.example.com:8080" and pool_size 10 as context manager and exit
    Then the proxy closes all connections

  # Async Support

  Scenario: Proxy supports async execute_request
    Given a proxy configuration
    When I call async execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com"
    Then the request executes asynchronously

  Scenario: Proxy supports concurrent async requests
    Given a proxy configuration
    When I call async execute_request concurrently with proxy_url "http://proxy1.example.com:8080" and urls ["https://library.municode.com", "https://codelibrary.amlegal.com", "https://ecode360.com"]
    Then all 3 requests execute concurrently

  # Integration with Scrapers

  Scenario: Use proxy with municode scraper
    Given a proxy configuration
    When I call municode search_jurisdictions with state "WA" using proxy_url "http://proxy1.example.com:8080"
    Then the request uses proxy "http://proxy1.example.com:8080"

  Scenario: Use proxy with american_legal scraper
    Given a proxy configuration
    When I call american_legal search_jurisdictions with state "WA" using proxy_url "http://proxy1.example.com:8080"
    Then the request uses proxy "http://proxy1.example.com:8080"

  Scenario: Use proxy with ecode360 scraper
    Given a proxy configuration
    When I call ecode360 search_jurisdictions with state "WA" using proxy_url "http://proxy1.example.com:8080"
    Then the request uses proxy "http://proxy1.example.com:8080"
