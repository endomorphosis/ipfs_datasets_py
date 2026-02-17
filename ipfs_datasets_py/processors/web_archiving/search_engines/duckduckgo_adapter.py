"""
DuckDuckGo Search Engine Adapter.

This adapter provides search capabilities using DuckDuckGo's unofficial API
via the duckduckgo_search library.

Note: DuckDuckGo doesn't require an API key but has rate limiting.
      Use responsibly to avoid being blocked.
"""

import logging
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

# Try to import duckduckgo_search library
try:
    from duckduckgo_search import DDGS
    HAVE_DDGS = True
except ImportError:
    HAVE_DDGS = False
    DDGS = None
    logger.warning(
        "duckduckgo_search not available. "
        "Install with: pip install duckduckgo-search"
    )


class DuckDuckGoSearchEngine(SearchEngineAdapter):
    """DuckDuckGo Search engine adapter.
    
    Uses the duckduckgo_search library to perform searches without
    requiring an API key. Includes rate limiting to avoid blocks.
    
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
        ...     rate_limit_per_minute=30,  # Conservative rate limit
        ...     cache_enabled=True
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
            SearchEngineError: If duckduckgo_search not available
        """
        super().__init__(config)
        
        if not HAVE_DDGS:
            raise SearchEngineError(
                "duckduckgo_search library not available. "
                "Install with: pip install duckduckgo-search"
            )
        
        # Set conservative defaults for DuckDuckGo
        if config.rate_limit_per_minute > 30:
            logger.warning(
                f"DuckDuckGo rate limit {config.rate_limit_per_minute} "
                "may be too high. Recommended: 30 or less."
            )
        
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
                
                if attempt < self.config.retry_attempts - 1:
                    # Wait before retry
                    time.sleep(self.config.retry_delay_seconds * (attempt + 1))
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
        
        # Create DDGS instance
        with DDGS() as ddgs:
            # DuckDuckGo doesn't support offset directly
            # We need to fetch more results and slice
            fetch_count = min(max_results + offset, 100)
            
            # Execute search
            region = kwargs.get("region", "us-en")
            safesearch = kwargs.get("safesearch", "moderate")
            timelimit = kwargs.get("time", None)
            
            ddgs_results = list(ddgs.text(
                keywords=query,
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
