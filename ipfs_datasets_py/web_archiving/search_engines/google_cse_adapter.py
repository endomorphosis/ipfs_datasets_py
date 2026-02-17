"""
Google Custom Search Engine (CSE) Adapter.

This adapter provides search capabilities using Google's Custom Search JSON API.
Requires a Google Cloud API key and a Custom Search Engine ID.

Documentation: https://developers.google.com/custom-search/v1/overview
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
    SearchEngineQuotaExceededError,
)

logger = logging.getLogger(__name__)

# Try to import Google API client
try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    HAVE_GOOGLE_CLIENT = True
except ImportError:
    HAVE_GOOGLE_CLIENT = False
    build = None
    HttpError = Exception
    logger.warning(
        "Google API client not available. "
        "Install with: pip install google-api-python-client"
    )


class GoogleCSESearchEngine(SearchEngineAdapter):
    """Google Custom Search Engine adapter.
    
    Uses Google's Custom Search JSON API to perform searches.
    Requires both an API key and a Custom Search Engine (CSE) ID.
    
    Features:
    - Requires API key and CSE ID
    - 100 free queries per day (paid plans available)
    - Rate limiting and quota management
    - Result caching
    - Automatic retry on failure
    
    Setup:
    1. Get API key: https://console.cloud.google.com/apis/credentials
    2. Create CSE: https://programmablesearchengine.google.com/
    3. Configure CSE to search the entire web or specific sites
    
    Example:
        >>> from ipfs_datasets_py.web_archiving.search_engines import (
        ...     GoogleCSESearchEngine,
        ...     SearchEngineConfig
        ... )
        >>> config = SearchEngineConfig(
        ...     engine_type="google_cse",
        ...     api_key="your_api_key",
        ...     rate_limit_per_minute=60,
        ...     extra_params={"cse_id": "your_cse_id"}
        ... )
        >>> engine = GoogleCSESearchEngine(config)
        >>> response = engine.search("EPA regulations California")
        >>> print(f"Found {len(response.results)} results")
    """
    
    def __init__(self, config: SearchEngineConfig):
        """Initialize Google CSE search engine.
        
        Args:
            config: Search engine configuration
                Must include "cse_id" in extra_params
            
        Raises:
            SearchEngineError: If Google API client not available or CSE ID missing
        """
        super().__init__(config)
        
        if not HAVE_GOOGLE_CLIENT:
            raise SearchEngineError(
                "Google API client not available. "
                "Install with: pip install google-api-python-client"
            )
        
        if not config.api_key:
            raise SearchEngineError(
                "Google CSE requires an API key. "
                "Set in config or GOOGLE_API_KEY env var."
            )
        
        # Get CSE ID from config
        self.cse_id = config.extra_params.get("cse_id")
        if not self.cse_id:
            raise SearchEngineError(
                "Google CSE requires a Custom Search Engine ID. "
                "Set in config.extra_params['cse_id']"
            )
        
        # Initialize Google API client
        try:
            self.service = build(
                "customsearch",
                "v1",
                developerKey=config.api_key
            )
        except Exception as e:
            raise SearchEngineError(f"Failed to initialize Google API client: {e}") from e
        
        logger.info(f"Google CSE search engine initialized (CSE ID: {self.cse_id[:10]}...)")
    
    def search(
        self,
        query: str,
        max_results: int = 20,
        offset: int = 0,
        **kwargs
    ) -> SearchEngineResponse:
        """Execute a Google CSE search query.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return (max 10 per request)
            offset: Result offset for pagination (max 100)
            **kwargs: Additional Google CSE-specific parameters
                - dateRestrict: Restrict results by date (e.g., "d7", "m3", "y1")
                - siteSearch: Limit to specific site
                - fileType: Filter by file type
                - lr: Language restrict (e.g., "lang_en")
                - gl: Geolocation (e.g., "us")
            
        Returns:
            SearchEngineResponse with normalized results
            
        Raises:
            SearchEngineError: On search failure
            SearchEngineQuotaExceededError: If daily quota exceeded
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
        
        # Google CSE has a limit of 10 results per request
        # We need to make multiple requests for more results
        start_time = time.time()
        all_results = []
        
        try:
            # Calculate number of requests needed
            requests_needed = (max_results + 9) // 10  # Ceiling division
            
            for i in range(requests_needed):
                # Calculate start index (1-based)
                start_index = offset + (i * 10) + 1
                
                # Don't exceed Google's 100 result limit
                if start_index > 100:
                    logger.warning("Google CSE limits results to 100")
                    break
                
                # Calculate count for this request
                remaining = max_results - len(all_results)
                count = min(remaining, 10)
                
                # Execute search
                results = self._execute_search(
                    query,
                    start_index,
                    count,
                    **kwargs
                )
                
                all_results.extend(results)
                
                # If we got fewer results than requested, no more are available
                if len(results) < count:
                    break
            
            # Create response
            response = SearchEngineResponse(
                results=all_results,
                engine=SearchEngineType.GOOGLE_CSE,
                query=query,
                total_results=len(all_results),
                page=(offset // max_results) + 1,
                took_ms=(time.time() - start_time) * 1000,
                from_cache=False,
                metadata={
                    "offset": offset,
                    "requests": requests_needed,
                    "cse_id": self.cse_id,
                }
            )
            
            # Cache response
            self._save_to_cache(cache_key, response)
            
            logger.info(
                f"Google CSE search completed: {len(all_results)} results "
                f"in {response.took_ms:.0f}ms ({requests_needed} requests)"
            )
            
            return response
            
        except HttpError as e:
            # Check for quota exceeded
            if e.resp.status == 429 or "quota" in str(e).lower():
                raise SearchEngineQuotaExceededError(
                    f"Google CSE quota exceeded: {e}"
                ) from e
            else:
                raise SearchEngineError(f"Google CSE API error: {e}") from e
        
        except Exception as e:
            logger.error(f"Google CSE search failed: {e}")
            raise SearchEngineError(f"Google CSE search error: {e}") from e
    
    def _execute_search(
        self,
        query: str,
        start: int,
        num: int,
        **kwargs
    ) -> list[SearchEngineResult]:
        """Execute a single Google CSE search request.
        
        Args:
            query: Search query
            start: Start index (1-based)
            num: Number of results (max 10)
            **kwargs: Additional parameters
            
        Returns:
            List of normalized results
        """
        # Build request parameters
        request_params = {
            "q": query,
            "cx": self.cse_id,
            "start": start,
            "num": num,
        }
        
        # Add optional parameters
        for param in ["dateRestrict", "siteSearch", "fileType", "lr", "gl"]:
            if param in kwargs:
                request_params[param] = kwargs[param]
        
        # Execute request
        result = self.service.cse().list(**request_params).execute()
        
        # Normalize results
        results = []
        items = result.get("items", [])
        
        for idx, item in enumerate(items):
            # Extract domain from URL
            try:
                domain = urlparse(item.get("link", "")).netloc
            except Exception:
                domain = None
            
            # Create normalized result
            normalized = SearchEngineResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                engine=SearchEngineType.GOOGLE_CSE,
                score=1.0 - (idx * 0.01),  # Simple ranking score
                published_date=None,  # Not directly provided
                domain=domain,
                metadata={
                    "displayLink": item.get("displayLink", ""),
                    "formattedUrl": item.get("formattedUrl", ""),
                    "mime": item.get("mime", None),
                    "fileFormat": item.get("fileFormat", None),
                }
            )
            
            results.append(normalized)
        
        return results
    
    def test_connection(self) -> bool:
        """Test if Google CSE API is accessible.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Try a simple search
            response = self.search("test", max_results=1)
            return len(response.results) >= 0
        except SearchEngineQuotaExceededError:
            # Quota exceeded means connection works but no quota
            logger.warning("Google CSE quota exceeded")
            return True
        except Exception as e:
            logger.error(f"Google CSE connection test failed: {e}")
            return False
