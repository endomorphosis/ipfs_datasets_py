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
        >>> from ipfs_datasets_py.web_archiving.search_engines import (
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
            # Call Brave API
            brave_results = self.client.search(
                query=query,
                count=max_results,
                offset=offset,
                **kwargs
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
            logger.error(f"Brave search failed: {e}")
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
        brave_results: Dict[str, Any]
    ) -> list[SearchEngineResult]:
        """Normalize Brave API results to standard format.
        
        Args:
            brave_results: Raw Brave API response
            
        Returns:
            List of normalized SearchEngineResult objects
        """
        results = []
        
        # Extract web results
        web_results = brave_results.get("web", {}).get("results", [])
        
        for idx, result in enumerate(web_results):
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
