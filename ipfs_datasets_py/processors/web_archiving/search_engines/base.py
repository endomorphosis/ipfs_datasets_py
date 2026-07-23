"""
Base classes for search engine adapters.

This module defines the abstract interface that all search engine
adapters must implement, along with common data structures.
"""

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
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
        self._persistent_cache = self._build_persistent_cache()
    
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
        
        if cache_key in self._cache:
            response, timestamp = self._cache[cache_key]

            # Check if cache entry is still valid
            if time.time() - timestamp <= self.config.cache_ttl_seconds:
                response.from_cache = True
                return response

            del self._cache[cache_key]

        persistent_response = self._get_from_persistent_cache(cache_key)
        if persistent_response is not None:
            self._cache[cache_key] = (persistent_response, time.time())
            return persistent_response

        return None
    
    def _save_to_cache(self, cache_key: str, response: SearchEngineResponse) -> None:
        """Save response to cache.
        
        Args:
            cache_key: Cache key
            response: Response to cache
        """
        if not self.config.cache_enabled:
            return
        
        self._cache[cache_key] = (response, time.time())
        self._save_to_persistent_cache(cache_key, response)
    
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
            "persistent_cache_enabled": self._persistent_cache is not None,
        }

    @staticmethod
    def _env_bool(*names: str) -> Optional[bool]:
        for name in names:
            raw = str(os.environ.get(name) or "").strip().lower()
            if not raw:
                continue
            if raw in {"1", "true", "yes", "on"}:
                return True
            if raw in {"0", "false", "no", "off"}:
                return False
        return None

    def _build_persistent_cache(self) -> Any:
        enabled = self._env_bool(
            "IPFS_DATASETS_SEARCH_CACHE_ENABLED",
            "LEGAL_SCRAPER_SEARCH_CACHE_ENABLED",
        )
        if enabled is False:
            return None

        cache_dir = (
            os.environ.get("IPFS_DATASETS_SEARCH_CACHE_DIR")
            or os.environ.get("LEGAL_SCRAPER_SEARCH_CACHE_DIR")
        )
        if not cache_dir and enabled is not True:
            return None

        mirror = self._env_bool(
            "IPFS_DATASETS_SEARCH_CACHE_IPFS_MIRROR",
            "LEGAL_SCRAPER_SEARCH_CACHE_IPFS_MIRROR",
        )
        try:
            from ...legal_scrapers.shared_fetch_cache import SharedFetchCache

            return SharedFetchCache(cache_dir=cache_dir, enable_ipfs_mirroring=bool(mirror))
        except Exception as exc:
            logger.warning("Persistent search cache unavailable: %s", exc)
            return None

    def _persistent_cache_url(self, cache_key: str) -> str:
        engine = str(self.config.engine_type or "search").lower()
        return f"search-cache://{engine}/{cache_key}"

    def _get_from_persistent_cache(self, cache_key: str) -> Optional[SearchEngineResponse]:
        if self._persistent_cache is None:
            return None
        try:
            payload = self._persistent_cache.load(
                namespace="search_results",
                url=self._persistent_cache_url(cache_key),
            )
            if not payload:
                return None

            cached_at = float(payload.get("cached_at_epoch") or 0.0)
            if cached_at and time.time() - cached_at > self.config.cache_ttl_seconds:
                return None

            response = SearchEngineResponse(
                results=[
                    SearchEngineResult(**result)
                    for result in payload.get("results", [])
                    if isinstance(result, dict)
                ],
                engine=str(payload.get("engine") or self.config.engine_type),
                query=str(payload.get("query") or ""),
                total_results=int(payload.get("total_results") or 0),
                page=int(payload.get("page") or 1),
                took_ms=float(payload.get("took_ms") or 0.0),
                from_cache=True,
                metadata=dict(payload.get("metadata") or {}),
            )
            response.metadata.setdefault("persistent_cache", payload.get("_cache") or {})
            return response
        except Exception as exc:
            logger.warning("Persistent search cache read failed for %s: %s", cache_key, exc)
            return None

    def _save_to_persistent_cache(self, cache_key: str, response: SearchEngineResponse) -> None:
        if self._persistent_cache is None:
            return
        try:
            payload = {
                "cached_at_epoch": time.time(),
                "results": [asdict(result) for result in response.results],
                "engine": response.engine,
                "query": response.query,
                "total_results": response.total_results,
                "page": response.page,
                "took_ms": response.took_ms,
                "metadata": dict(response.metadata or {}),
            }
            self._persistent_cache.save(
                namespace="search_results",
                url=self._persistent_cache_url(cache_key),
                payload=payload,
                payload_name=f"search_results_{self.config.engine_type}_{cache_key[:16]}",
            )
        except Exception as exc:
            logger.warning("Persistent search cache write failed for %s: %s", cache_key, exc)
