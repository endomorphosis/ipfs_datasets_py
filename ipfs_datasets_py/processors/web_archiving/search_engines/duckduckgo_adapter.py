"""DuckDuckGo Search Engine Adapter.

This adapter provides search capabilities using DuckDuckGo's unofficial API
via the ``ddgs`` library.

Note: DuckDuckGo doesn't require an API key but has rate limiting.
      Use responsibly to avoid being blocked.
"""

import logging
import random
import re
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from .base import (
    SearchEngineAdapter,
    SearchEngineConfig,
    SearchEngineResponse,
    SearchEngineResult,
    SearchEngineError,
    SearchEngineType,
    SearchEngineRateLimitError,
)

logger = logging.getLogger(__name__)

# Try to import ddgs library
try:
    from ddgs import DDGS

    HAVE_DDGS = True
except ImportError:
    HAVE_DDGS = False
    DDGS = None
    logger.warning("ddgs not available. Install with: pip install ddgs")


class DuckDuckGoSearchEngine(SearchEngineAdapter):
    """DuckDuckGo Search engine adapter.

    Uses the ``ddgs`` library to perform searches without requiring an API key.
    Includes rate limiting to avoid blocks.

    Features:
    - No API key required
    - Rate limiting (default: 30 requests/minute)
    - Result caching
    - Automatic retry on failure

    Example:
        >>> from ipfs_datasets_py.processors.web_archiving.search_engines import (
        ...     DuckDuckGoSearchEngine,
        ...     SearchEngineConfig
        ... )
        >>> config = SearchEngineConfig(
        ...     engine_type="duckduckgo",
        ...     rate_limit_per_minute=30,
        ...     cache_enabled=True,
        ... )
        >>> engine = DuckDuckGoSearchEngine(config)
        >>> response = engine.search("EPA regulations California")
        >>> print(f"Found {len(response.results)} results")
    """

    def __init__(self, config: SearchEngineConfig):
        """Initialize DuckDuckGo search engine.

        Args:
            config: Search engine configuration

        Raises:
            SearchEngineError: If ``ddgs`` is not available
        """
        super().__init__(config)

        if not HAVE_DDGS:
            raise SearchEngineError(
                "ddgs library not available. Install with: pip install ddgs"
            )

        self._disabled_until: float = 0.0

        # Set conservative defaults for DuckDuckGo.
        if config.rate_limit_per_minute > 30:
            logger.warning(
                f"DuckDuckGo rate limit {config.rate_limit_per_minute} "
                "may be too high. Clamping to 30 requests/minute."
            )
            config.rate_limit_per_minute = 30

        logger.info("DuckDuckGo search engine initialized")
    
    def search(
        self,
        query: str,
        max_results: int = 20,
        offset: int = 0,
        **kwargs
    ) -> SearchEngineResponse:
        """Execute a DuckDuckGo search query.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return (max 100)
            offset: Result offset (not directly supported, uses pagination)
            **kwargs: Additional DuckDuckGo-specific parameters
                - region: Region code (e.g., "us-en")
                - safesearch: "on", "moderate", or "off"
                - time: Time range ("d", "w", "m", "y")
            
        Returns:
            SearchEngineResponse with normalized results
            
        Raises:
            SearchEngineError: On search failure
        """
        now = time.time()
        if self._disabled_until > now:
            retry_after = max(0.0, self._disabled_until - now)
            raise SearchEngineRateLimitError(
                f"DuckDuckGo search temporarily rate limited; retry after {retry_after:.1f}s"
            )

        # Check cache first
        cache_key = self._get_cache_key(
            query,
            max_results=max_results,
            offset=offset,
            **kwargs
        )
        
        cached_response = self._get_from_cache(cache_key)
        if cached_response:
            logger.debug(f"Cache hit for query: {query[:50]}...")
            return cached_response
        
        # Check rate limit
        self._check_rate_limit()
        
        # Execute search with retry
        start_time = time.time()
        
        for attempt in range(self.config.retry_attempts):
            try:
                results = self._execute_search(query, max_results, offset, **kwargs)
                
                # Create response
                response = SearchEngineResponse(
                    results=results,
                    engine=SearchEngineType.DUCKDUCKGO,
                    query=query,
                    total_results=len(results),
                    page=(offset // max_results) + 1,
                    took_ms=(time.time() - start_time) * 1000,
                    from_cache=False,
                    metadata={
                        "offset": offset,
                        "attempt": attempt + 1,
                    }
                )
                
                # Cache response
                self._save_to_cache(cache_key, response)
                
                logger.info(
                    f"DuckDuckGo search completed: {len(results)} results "
                    f"in {response.took_ms:.0f}ms (attempt {attempt + 1})"
                )
                
                return response
                
            except Exception as e:
                logger.warning(
                    f"DuckDuckGo search attempt {attempt + 1} failed: {e}"
                )

                if self._is_rate_limited_error(e):
                    retry_after = self._extract_retry_after_seconds(e)
                    cooldown_seconds = max(
                        float(self.config.retry_delay_seconds or 0.0),
                        float(retry_after if retry_after is not None else 60.0),
                    )
                    self._disabled_until = max(self._disabled_until, time.time() + cooldown_seconds)
                    raise SearchEngineRateLimitError(
                        f"DuckDuckGo search rate limited; retry after {cooldown_seconds:.1f}s"
                    ) from e
                
                if attempt < self.config.retry_attempts - 1:
                    # Wait before retry
                    base_delay = float(self.config.retry_delay_seconds) * float(attempt + 1)
                    jitter = random.uniform(0.0, float(self.config.retry_delay_seconds))
                    time.sleep(max(0.0, base_delay + jitter))
                else:
                    # Final attempt failed
                    raise SearchEngineError(
                        f"DuckDuckGo search failed after {self.config.retry_attempts} attempts: {e}"
                    ) from e
    
    def _execute_search(
        self,
        query: str,
        max_results: int,
        offset: int,
        **kwargs
    ) -> list[SearchEngineResult]:
        """Execute the actual DuckDuckGo search.
        
        Args:
            query: Search query
            max_results: Maximum results
            offset: Result offset
            **kwargs: Additional parameters
            
        Returns:
            List of normalized results
        """
        results = []
        
        # Create DDGS instance with explicit timeout budget so slow network
        # paths don't block legal scraper daemons indefinitely.
        with DDGS(timeout=max(1, int(self.config.timeout_seconds))) as ddgs:
            # DuckDuckGo doesn't support offset directly
            # We need to fetch more results and slice
            fetch_count = min(max_results + offset, 100)
            
            # Execute search
            region = kwargs.get("region", "us-en")
            safesearch = kwargs.get("safesearch", "moderate")
            timelimit = kwargs.get("time", None)
            
            ddgs_results = list(ddgs.text(
                query=query,
                region=region,
                safesearch=safesearch,
                timelimit=timelimit,
                max_results=fetch_count
            ))
            
            # Apply offset
            ddgs_results = ddgs_results[offset:]
            
            # Normalize results
            for idx, result in enumerate(ddgs_results[:max_results]):
                # Extract domain from URL
                try:
                    domain = urlparse(result.get("href", "")).netloc
                except Exception:
                    domain = None
                
                # Create normalized result
                normalized = SearchEngineResult(
                    title=result.get("title", ""),
                    url=result.get("href", ""),
                    snippet=result.get("body", ""),
                    engine=SearchEngineType.DUCKDUCKGO,
                    score=1.0 - (idx * 0.01),  # Simple ranking score
                    published_date=None,  # DDG doesn't provide this
                    domain=domain,
                    metadata={}
                )
                
                results.append(normalized)
        
        return results

    @staticmethod
    def _is_rate_limited_error(error: Exception) -> bool:
        text = f"{type(error).__name__} {error}".lower()
        return (
            "ratelimit" in text
            or "rate limit" in text
            or "too many requests" in text
            or "http 429" in text
            or "status code 429" in text
        )

    @staticmethod
    def _extract_retry_after_seconds(error: Exception) -> Optional[float]:
        text = str(error or "")
        patterns = (
            r"retry(?:\s|-)?after\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b",
            r"retry(?:\s|-)?after\s*[:=]?\s*(\d+(?:\.\d+)?)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            try:
                return max(0.0, float(match.group(1)))
            except Exception:
                continue
        return None
    
    def test_connection(self) -> bool:
        """Test if DuckDuckGo search is accessible.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Try a simple search
            response = self.search("test", max_results=1)
            return len(response.results) >= 0
        except Exception as e:
            logger.error(f"DuckDuckGo connection test failed: {e}")
            return False
