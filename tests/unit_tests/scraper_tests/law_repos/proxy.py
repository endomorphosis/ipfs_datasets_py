#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Proxy callable for web scraping.

This module provides proxy functionality to rotate IP addresses and headers
to prevent blocking when scraping websites such as municode, american_legal, and ecode360.
"""
from typing import Any, Dict, List, Optional, Union


def proxy(
    proxy_url: Optional[str] = None,
    proxy_urls: Optional[List[str]] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_strategy: str = "exponential",
    backoff_delay: float = 1.0,
    pool_size: int = 10,
    maintain_session: bool = False,
    rate_limit_delay: float = 0.0,
    health_check: bool = False,
    health_check_cooldown: float = 60.0,
    user_agents: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Create a proxy configuration for web scraping with rotation and retry capabilities.
    
    Configures proxy settings for HTTP/HTTPS/SOCKS5 proxies with support for rotation,
    authentication, retry logic with backoff, connection pooling, session management,
    rate limiting, and health monitoring. Used to prevent IP blocking when scraping
    websites like municode, american_legal, and ecode360.
    
    Args:
        proxy_url (str, optional): Single proxy URL (e.g., "http://proxy1.example.com:8080").
        proxy_urls (list, optional): List of proxy URLs for rotation.
        username (str, optional): Proxy authentication username.
        password (str, optional): Proxy authentication password.
        timeout (float, optional): Request timeout in seconds. Defaults to 30.0.
        max_retries (int, optional): Maximum retry attempts for failed requests. Defaults to 3.
        backoff_strategy (str, optional): Retry backoff strategy ("exponential" or "linear"). Defaults to "exponential".
        backoff_delay (float, optional): Initial delay for backoff in seconds. Defaults to 1.0.
        pool_size (int, optional): Connection pool size. Defaults to 10.
        maintain_session (bool, optional): Maintain session with cookies. Defaults to False.
        rate_limit_delay (float, optional): Delay between requests in seconds. Defaults to 0.0.
        health_check (bool, optional): Enable proxy health monitoring. Defaults to False.
        health_check_cooldown (float, optional): Cooldown period for unhealthy proxies in seconds. Defaults to 60.0.
        user_agents (list, optional): List of User-Agent strings to rotate.
    
    Returns:
        dict: Proxy configuration containing:
            - proxy_count (int): Number of configured proxies
            - rotation_enabled (bool): Whether proxy rotation is enabled
            - timeout (float): Request timeout in seconds
            - max_retries (int): Maximum retry attempts
            - backoff_strategy (str): Retry backoff strategy
            - pool_size (int): Connection pool size
            - session_enabled (bool): Whether session management is enabled
            - rate_limit_delay (float): Delay between requests
            - health_check_enabled (bool): Whether health monitoring is enabled
            - execute_request (callable): Method to execute HTTP requests with proxy
            - get_next_proxy (callable): Method to get next proxy from rotation
            - get_statistics (callable): Method to get proxy usage statistics
    
    Raises:
        ValueError: If proxy_url and proxy_urls are both None or both provided, if proxy URL format is invalid, or if unsupported protocol.
        TypeError: If invalid types provided for arguments.
    
    Example:
        >>> # Configure proxy with rotation and retry
        >>> proxy_config = proxy(
        ...     proxy_urls=[
        ...         "http://proxy1.example.com:8080",
        ...         "http://proxy2.example.com:8080"
        ...     ],
        ...     max_retries=3,
        ...     backoff_strategy="exponential",
        ...     rate_limit_delay=1.0
        ... )
        >>> print(f"Configured {proxy_config['proxy_count']} proxies")
        Configured 2 proxies
        >>> print(f"Rotation enabled: {proxy_config['rotation_enabled']}")
        Rotation enabled: True
        >>> # Execute request through proxy
        >>> response = proxy_config['execute_request'](url="https://library.municode.com")
        >>> print(f"Status: {response['status_code']}, Proxy: {response['proxy_used']}")
        Status: 200, Proxy: http://proxy1.example.com:8080
    """
    pass


def execute_request(
    url: str,
    proxy_url: Optional[str] = None,
    proxy_urls: Optional[List[str]] = None,
    headers: Optional[Dict[str, str]] = None,
    method: str = "GET",
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_strategy: str = "exponential"
) -> Dict[str, Any]:
    """
    Execute HTTP request through configured proxy with retry logic.
    
    Performs an HTTP request using the specified proxy configuration with automatic
    retry on failures (429, 503, timeout, DNS errors), rotating proxies if multiple
    are configured. Supports custom headers, various HTTP methods, and configurable
    timeout and retry behavior.
    
    Args:
        url (str): Target URL to request.
        proxy_url (str, optional): Single proxy URL to use.
        proxy_urls (list, optional): List of proxy URLs for rotation.
        headers (dict, optional): Custom HTTP headers to include in request.
        method (str, optional): HTTP method to use. Defaults to "GET".
        timeout (float, optional): Request timeout in seconds. Defaults to 30.0.
        max_retries (int, optional): Maximum retry attempts. Defaults to 3.
        backoff_strategy (str, optional): Retry backoff strategy. Defaults to "exponential".
    
    Returns:
        dict: Response containing:
            - status_code (int): HTTP status code
            - body (str): Response body content
            - headers (dict): Response headers
            - proxy_used (str): Proxy URL that was used for successful request
            - retry_count (int): Number of retries performed
            - elapsed_time (float): Total request time in seconds
    
    Raises:
        ConnectionError: If all retry attempts fail or proxy is unreachable.
        TimeoutError: If request exceeds timeout limit.
        ValueError: If URL or proxy configuration is invalid.
    
    Example:
        >>> # Execute request with proxy rotation
        >>> response = execute_request(
        ...     url="https://library.municode.com",
        ...     proxy_urls=["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"],
        ...     headers={"User-Agent": "Mozilla/5.0"},
        ...     max_retries=3
        ... )
        >>> print(f"Status: {response['status_code']}")
        Status: 200
        >>> print(f"Proxy used: {response['proxy_used']}")
        Proxy used: http://proxy1.example.com:8080
        >>> print(f"Response body length: {len(response['body'])} characters")
        Response body length: 42356 characters
    """
    pass


def get_next_proxy(
    proxy_url: Optional[str] = None,
    proxy_urls: Optional[List[str]] = None
) -> str:
    """
    Get next proxy URL from rotation list using round-robin selection.
    
    Returns the next proxy URL in the rotation sequence. For a single proxy,
    always returns the same URL. For multiple proxies, rotates through the list
    using round-robin algorithm, wrapping back to the first proxy after reaching
    the end of the list.
    
    Args:
        proxy_url (str, optional): Single proxy URL (returns same URL every time).
        proxy_urls (list, optional): List of proxy URLs to rotate through.
    
    Returns:
        str: Next proxy URL in rotation sequence.
    
    Raises:
        ValueError: If both proxy_url and proxy_urls are None or both provided.
    
    Example:
        >>> # Rotate through multiple proxies
        >>> proxies = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        >>> proxy1 = get_next_proxy(proxy_urls=proxies)
        >>> print(f"First proxy: {proxy1}")
        First proxy: http://proxy1.example.com:8080
        >>> proxy2 = get_next_proxy(proxy_urls=proxies)
        >>> print(f"Second proxy: {proxy2}")
        Second proxy: http://proxy2.example.com:8080
        >>> proxy3 = get_next_proxy(proxy_urls=proxies)
        >>> print(f"Third proxy (wrapped): {proxy3}")
        Third proxy (wrapped): http://proxy1.example.com:8080
    """
    pass


def get_statistics(
    proxy_url: Optional[str] = None,
    proxy_urls: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Get proxy usage statistics including request counts and success rates.
    
    Returns statistics for proxy usage including total requests, successful requests,
    failed requests, and per-proxy breakdown. Useful for monitoring proxy health
    and performance.
    
    Args:
        proxy_url (str, optional): Single proxy URL to get statistics for.
        proxy_urls (list, optional): List of proxy URLs to get statistics for.
    
    Returns:
        dict: Statistics containing:
            - total_requests (int): Total number of requests made
            - successful_requests (int): Number of successful requests
            - failed_requests (int): Number of failed requests
            - success_rate (float): Success rate as percentage
            - per_proxy_stats (dict): Per-proxy statistics with proxy URL as key
    
    Raises:
        ValueError: If no proxy configuration provided.
    
    Example:
        >>> # Get statistics after making requests
        >>> stats = get_statistics(
        ...     proxy_urls=["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        ... )
        >>> print(f"Total requests: {stats['total_requests']}")
        Total requests: 10
        >>> print(f"Success rate: {stats['success_rate']}%")
        Success rate: 80.0%
        >>> print(f"Proxy 1 requests: {stats['per_proxy_stats']['http://proxy1.example.com:8080']['requests']}")
        Proxy 1 requests: 5
    """
    pass
