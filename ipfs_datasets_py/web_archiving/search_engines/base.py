"""
Base classes for search engine adapters.

This module defines the abstract interface that all search engine
adapters must implement, along with common data structures.
"""

import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class SearchEngineType(str, Enum):
    """Supported search engine types."""
    BRAVE = "brave"
    DUCKDUCKGO = "duckduckgo"
    GOOGLE_CSE = "google_cse"


@dataclass
class SearchEngineResult:
    """Normalized search result from any engine."""
    title: str
    url: str
    snippet: str
    engine: str
    score: float = 1.0
    published_date: Optional[str] = None
    domain: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchEngineResponse:
    """Complete search response with metadata."""
    results: List[SearchEngineResult]
    engine: str
    query: str
    total_results: int = 0
    page: int = 1
    took_ms: float = 0.0
    from_cache: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchEngineConfig:
    """Configuration for a search engine adapter."""
    engine_type: str
    api_key: Optional[str] = None
    rate_limit_per_minute: int = 60
    timeout_seconds: int = 30
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600
    max_results_per_request: int = 20
    retry_attempts: int = 3
    retry_delay_seconds: float = 1.0
    extra_params: Dict[str, Any] = field(default_factory=dict)


class SearchEngineError(Exception):
    """Base exception for search engine errors."""
    pass


class SearchEngineRateLimitError(SearchEngineError):
    """Raised when rate limit is exceeded."""
    pass


class SearchEngineQuotaExceededError(SearchEngineError):
    """Raised when API quota is exceeded."""
    pass


class SearchEngineAdapter(ABC):
    """Abstract base class for search engine adapters.
    
    All search engine implementations must inherit from this class
    and implement the required methods.
    
    Attributes:
        config: Engine configuration
        _last_request_time: Timestamp of last API request
        _request_count: Number of requests made
    """
    
    def __init__(self, config: SearchEngineConfig):
        """Initialize the search engine adapter.
        
        Args:
            config: Engine configuration
        """
        self.config = config
        self._last_request_time: float = 0.0
        self._request_count: int = 0
        self._cache: Dict[str, tuple] = {}  # (response, timestamp)
    
    @abstractmethod
    def search(
        self,
        query: str,
        max_results: int = 20,
        offset: int = 0,
        **kwargs
    ) -> SearchEngineResponse:
        """Execute a search query.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            offset: Result offset for pagination
            **kwargs: Engine-specific parameters
            
        Returns:
            SearchEngineResponse with normalized results
            
        Raises:
            SearchEngineError: On search failure
            SearchEngineRateLimitError: If rate limit exceeded
        """
        pass
    
    @abstractmethod
    def test_connection(self) -> bool:
        """Test if the search engine API is accessible.
        
        Returns:
            True if connection successful, False otherwise
        """
        pass
    
    def _check_rate_limit(self) -> None:
        """Check and enforce rate limiting.
        
        Raises:
            SearchEngineRateLimitError: If rate limit would be exceeded
        """
        if self.config.rate_limit_per_minute <= 0:
            return
        
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        
        # Calculate minimum time between requests
        min_interval = 60.0 / self.config.rate_limit_per_minute
        
        if time_since_last < min_interval:
            wait_time = min_interval - time_since_last
            logger.debug(f"Rate limiting: waiting {wait_time:.2f}s")
            time.sleep(wait_time)
        
        self._last_request_time = time.time()
        self._request_count += 1
    
    def _get_cache_key(self, query: str, **kwargs) -> str:
        """Generate cache key for a query.
        
        Args:
            query: Search query
            **kwargs: Additional parameters
            
        Returns:
            Cache key string
        """
        import hashlib
        import json
        
        cache_data = {"query": query, **kwargs}
        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.md5(cache_str.encode()).hexdigest()
    
    def _get_from_cache(self, cache_key: str) -> Optional[SearchEngineResponse]:
        """Get response from cache if valid.
        
        Args:
            cache_key: Cache key
            
        Returns:
            Cached response or None
        """
        if not self.config.cache_enabled:
            return None
        
        if cache_key not in self._cache:
            return None
        
        response, timestamp = self._cache[cache_key]
        
        # Check if cache entry is still valid
        if time.time() - timestamp > self.config.cache_ttl_seconds:
            del self._cache[cache_key]
            return None
        
        # Mark as from cache
        response.from_cache = True
        return response
    
    def _save_to_cache(self, cache_key: str, response: SearchEngineResponse) -> None:
        """Save response to cache.
        
        Args:
            cache_key: Cache key
            response: Response to cache
        """
        if not self.config.cache_enabled:
            return
        
        self._cache[cache_key] = (response, time.time())
    
    def clear_cache(self) -> None:
        """Clear all cached responses."""
        self._cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get adapter statistics.
        
        Returns:
            Dictionary with stats (requests, cache hits, etc.)
        """
        cache_entries = len(self._cache)
        return {
            "engine": self.config.engine_type,
            "requests": self._request_count,
            "cache_entries": cache_entries,
            "cache_enabled": self.config.cache_enabled,
            "rate_limit": self.config.rate_limit_per_minute,
        }
