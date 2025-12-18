#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Proxy callable for web scraping.

This module provides proxy functionality to rotate IP addresses and headers
to prevent blocking when scraping websites such as municode, american_legal, and ecode360.
"""
from typing import Any, Dict, List, Optional, Union


class proxy:
    """
    Create proxy manager for web scraping with rotation and retry capabilities.
    
    Provides a proxy-aware HTTP client compatible with municode, american_legal, and
    ecode360 scrapers. Supports HTTP/HTTPS/SOCKS5 proxies with rotation, authentication,
    retry logic with backoff, connection pooling, session management, rate limiting,
    and health monitoring to prevent IP blocking.
    
    Can be used as a context manager (with statement) or as a drop-in replacement
    for aiohttp.ClientSession with proxy support.
    
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
        proxy: Proxy manager instance with methods:
            - get(url, **kwargs): Execute GET request through proxy
            - post(url, **kwargs): Execute POST request through proxy
            - request(method, url, **kwargs): Execute request with specified method
            - __enter__/__exit__: Context manager support
            - get_statistics(): Get proxy usage statistics
    
    Raises:
        ValueError: If proxy_url and proxy_urls are both None or both provided, if proxy URL format is invalid, or if unsupported protocol.
        TypeError: If invalid types provided for arguments.
    
    Example:
        >>> import asyncio
        >>> 
        >>> async def scrape_with_proxy():
        ...     # Configure proxy with rotation and retry
        ...     proxy_manager = proxy(
        ...         proxy_urls=[
        ...             "http://proxy1.example.com:8080",
        ...             "http://proxy2.example.com:8080"
        ...         ],
        ...         max_retries=3,
        ...         backoff_strategy="exponential",
        ...         rate_limit_delay=1.0,
        ...         user_agents=["Mozilla/5.0", "Chrome/90.0"]
        ...     )
        ...     
        ...     # Use as context manager like aiohttp.ClientSession
        ...     async with proxy_manager as session:
        ...         async with session.get("https://library.municode.com") as response:
        ...             html = await response.text()
        ...             print(f"Status: {response.status}")
        ...             print(f"Proxy used: {session.current_proxy}")
        ...             print(f"Response length: {len(html)} characters")
        ...     
        ...     # Get statistics
        ...     stats = proxy_manager.get_statistics()
        ...     print(f"Total requests: {stats['total_requests']}")
        ...     print(f"Success rate: {stats['success_rate']}%")
        ...     return html
        >>> 
        >>> # Example output:
        >>> asyncio.run(scrape_with_proxy())
        Status: 200
        Proxy used: http://proxy1.example.com:8080
        Response length: 42356 characters
        Total requests: 1
        Success rate: 100.0%
    """
    
    def __init__(
        self,
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
    ) -> None:
        """Initialize proxy manager with configuration."""
        pass
    
    async def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any
    ) -> Any:
        """
        Execute GET request through proxy.
        
        Args:
            url (str): Target URL to request.
            headers (dict, optional): Custom HTTP headers.
            **kwargs: Additional arguments passed to underlying HTTP client.
        
        Returns:
            Response object compatible with aiohttp.ClientResponse.
        
        Raises:
            ConnectionError: If all retry attempts fail.
            TimeoutError: If request exceeds timeout.
        """
        pass
    
    async def post(
        self,
        url: str,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any
    ) -> Any:
        """
        Execute POST request through proxy.
        
        Args:
            url (str): Target URL to request.
            data: Request body data.
            headers (dict, optional): Custom HTTP headers.
            **kwargs: Additional arguments passed to underlying HTTP client.
        
        Returns:
            Response object compatible with aiohttp.ClientResponse.
        
        Raises:
            ConnectionError: If all retry attempts fail.
            TimeoutError: If request exceeds timeout.
        """
        pass
    
    async def request(
        self,
        method: str,
        url: str,
        **kwargs: Any
    ) -> Any:
        """
        Execute request with specified HTTP method through proxy.
        
        Args:
            method (str): HTTP method (GET, POST, PUT, DELETE, etc.).
            url (str): Target URL to request.
            **kwargs: Additional arguments passed to underlying HTTP client.
        
        Returns:
            Response object compatible with aiohttp.ClientResponse.
        
        Raises:
            ConnectionError: If all retry attempts fail.
            TimeoutError: If request exceeds timeout.
        """
        pass
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get proxy usage statistics.
        
        Returns:
            dict: Statistics containing:
                - total_requests (int): Total number of requests made
                - successful_requests (int): Number of successful requests
                - failed_requests (int): Number of failed requests
                - success_rate (float): Success rate as percentage
                - per_proxy_stats (dict): Per-proxy statistics
        """
        pass
    
    async def __aenter__(self) -> "proxy":
        """Enter async context manager."""
        pass
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context manager."""
        pass
