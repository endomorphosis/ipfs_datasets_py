"""
Brave Search Engine Adapter.

This adapter wraps the existing BraveSearchClient to conform to the
unified SearchEngineAdapter interface.
"""

import logging
import time
from typing import Dict, Optional, Any
from urllib.parse import urlparse

from .base import (
    SearchEngineAdapter,
    SearchEngineConfig,
    SearchEngineResponse,
    SearchEngineResult,
    SearchEngineError,
    SearchEngineQuotaExceededError,
    SearchEngineRateLimitError,
    SearchEngineType,
)

logger = logging.getLogger(__name__)

# Import existing Brave client from same module
try:
    from ..brave_search_client import BraveSearchClient
    HAVE_BRAVE_CLIENT = True
except ImportError:
    HAVE_BRAVE_CLIENT = False
    BraveSearchClient = None
    logger.warning("BraveSearchClient not available")


class BraveSearchEngine(SearchEngineAdapter):
    """Brave Search engine adapter.
    
    Wraps the existing BraveSearchClient to provide a unified interface
    compatible with the multi-engine search orchestrator.
    
    Example:
        >>> from ipfs_datasets_py.processors.web_archiving.search_engines import (
        ...     BraveSearchEngine,
        ...     SearchEngineConfig
        ... )
        >>> config = SearchEngineConfig(
        ...     engine_type="brave",
        ...     api_key="your_api_key",
        ...     rate_limit_per_minute=60
        ... )
        >>> engine = BraveSearchEngine(config)
        >>> response = engine.search("EPA regulations California")
        >>> print(f"Found {len(response.results)} results")
    """
    
    def __init__(self, config: SearchEngineConfig):
        """Initialize Brave search engine.
        
        Args:
            config: Search engine configuration
            
        Raises:
            SearchEngineError: If Brave client not available
        """
        super().__init__(config)
        
        if not HAVE_BRAVE_CLIENT:
            raise SearchEngineError(
                "BraveSearchClient not available. "
                "Install web_archiving dependencies."
            )
        
        # Initialize Brave client
        api_key = config.api_key or None
        self.client = BraveSearchClient(api_key=api_key)
        self._disabled_until: float = 0.0
        self._quota_exhausted: bool = False
        
        logger.info("Brave search engine initialized")
    
    def search(
        self,
        query: str,
        max_results: int = 20,
        offset: int = 0,
        **kwargs
    ) -> SearchEngineResponse:
        """Execute a Brave search query.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            offset: Result offset for pagination
            **kwargs: Additional Brave-specific parameters
            
        Returns:
            SearchEngineResponse with normalized results
            
        Raises:
            SearchEngineError: On search failure
        """
        now = time.time()
        if self._quota_exhausted:
            raise SearchEngineQuotaExceededError("Brave search quota already exhausted for this process")
        if self._disabled_until > now:
            retry_after = max(0.0, self._disabled_until - now)
            raise SearchEngineRateLimitError(f"Brave search temporarily rate limited; retry after {retry_after:.1f}s")

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
        
        # Execute search
        start_time = time.time()
        
        try:
            client_kwargs = {}
            safesearch = kwargs.get("safesearch")
            country = kwargs.get("country")
            if safesearch is not None:
                client_kwargs["safesearch"] = safesearch
            if country is not None:
                client_kwargs["country"] = country

            # Call Brave API
            brave_results = self.client.search(
                query=query,
                count=max_results,
                offset=offset,
                **client_kwargs,
            )
            
            # Normalize results
            results = self._normalize_results(brave_results)
            
            # Create response
            response = SearchEngineResponse(
                results=results,
                engine=SearchEngineType.BRAVE,
                query=query,
                total_results=len(results),
                page=(offset // max_results) + 1,
                took_ms=(time.time() - start_time) * 1000,
                from_cache=False,
                metadata={
                    "offset": offset,
                    "raw_response": brave_results
                }
            )
            
            # Cache response
            self._save_to_cache(cache_key, response)
            
            logger.info(
                f"Brave search completed: {len(results)} results "
                f"in {response.took_ms:.0f}ms"
            )
            
            return response
            
        except Exception as e:
            self._update_backoff_state(e)
            logger.error(f"Brave search failed: {e}")
            if self._quota_exhausted:
                raise SearchEngineQuotaExceededError(f"Brave search quota exhausted: {e}") from e
            if self._disabled_until > time.time():
                retry_after = max(0.0, self._disabled_until - time.time())
                raise SearchEngineRateLimitError(
                    f"Brave search rate limited: retry after {retry_after:.1f}s; {e}"
                ) from e
            raise SearchEngineError(f"Brave search error: {e}") from e
    
    def test_connection(self) -> bool:
        """Test if Brave Search API is accessible.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Try a simple search
            response = self.search("test", max_results=1)
            return len(response.results) >= 0
        except Exception as e:
            logger.error(f"Brave connection test failed: {e}")
            return False
    
    def _normalize_results(
        self,
        brave_results: Any
    ) -> list[SearchEngineResult]:
        """Normalize Brave API results to standard format.
        
        Args:
            brave_results: Raw Brave API response
            
        Returns:
            List of normalized SearchEngineResult objects
        """
        results = []
        web_results = self._extract_web_results(brave_results)

        for idx, result in enumerate(web_results):
            if not isinstance(result, dict):
                continue
            # Extract domain from URL
            try:
                domain = urlparse(result.get("url", "")).netloc
            except Exception:
                domain = None
            
            # Create normalized result
            normalized = SearchEngineResult(
                title=result.get("title", ""),
                url=result.get("url", ""),
                snippet=result.get("description", ""),
                engine=SearchEngineType.BRAVE,
                score=1.0 - (idx * 0.01),  # Simple ranking score
                published_date=result.get("page_age", None),
                domain=domain,
                metadata={
                    "extra_snippets": result.get("extra_snippets", []),
                    "language": result.get("language", None),
                    "family_friendly": result.get("family_friendly", True),
                }
            )
            
            results.append(normalized)
        
        return results

    @staticmethod
    def _extract_web_results(brave_results: Any) -> list[dict[str, Any]]:
        """Extract result objects from the Brave client response.

        The Brave client is not perfectly stable here: depending on code path,
        it may return either a raw list of result dicts or a dict payload with
        `web.results`.
        """
        if isinstance(brave_results, list):
            return [item for item in brave_results if isinstance(item, dict)]

        if not isinstance(brave_results, dict):
            return []

        web_payload = brave_results.get("web", {})
        if isinstance(web_payload, dict):
            nested_results = web_payload.get("results", [])
            if isinstance(nested_results, list):
                return [item for item in nested_results if isinstance(item, dict)]

        if isinstance(web_payload, list):
            return [item for item in web_payload if isinstance(item, dict)]

        direct_results = brave_results.get("results", [])
        if isinstance(direct_results, list):
            return [item for item in direct_results if isinstance(item, dict)]

        return []

    def _update_backoff_state(self, error: Exception) -> None:
        """Track quota/rate-limit failures so future calls fail fast."""
        message = str(error)
        upper_message = message.upper()
        if "QUOTA_LIMITED" in upper_message or "QUOTA LIMIT" in upper_message:
            self._quota_exhausted = True
            self._disabled_until = float("inf")
            return
        if "RATE_LIMITED" in upper_message or "RATE LIMIT" in upper_message or "HTTP 429" in upper_message:
            self._disabled_until = max(self._disabled_until, time.time() + 300.0)
