"""Unified GitHub API integration with caching, rate limiting, and call tracking.

DEPRECATED: This module is being phased out in favor of:
- ipfs_datasets_py.utils.cache for caching functionality
- ipfs_datasets_py.utils.github for GitHub operations

This module now re-exports from the unified utils modules while maintaining
backward compatibility for existing optimizer code.

Original functionality consolidated from:
- optimizers/agentic/github_control.py (GitHubAPICache, AdaptiveRateLimiter)
- .github/scripts/github_api_counter.py (API call tracking)

Provides a single source of truth for all GitHub API interactions used by:
- Optimizer workflows (agentic optimization)
- GitHub Actions workflows (.github/workflows/)
- Workflow helper scripts (.github/scripts/)
"""

import json
import logging
import subprocess
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Import from unified utils modules
from ...utils.cache import CacheBackend, CacheEntry, GitHubCache
from ...utils.github import APICounter, APICallRecord

logger = logging.getLogger(__name__)

# Issue deprecation warning
warnings.warn(
    "optimizers.agentic.github_api_unified is deprecated. "
    "Use ipfs_datasets_py.utils.cache.GitHubCache and "
    "ipfs_datasets_py.utils.github.APICounter instead.",
    DeprecationWarning,
    stacklevel=2
)



class UnifiedGitHubAPICache:
    """Unified GitHub API cache with call tracking and statistics.
    
    DEPRECATED: Use GitHubCache from utils.cache and APICounter from utils.github instead.
    
    This is a compatibility wrapper that combines GitHubCache and APICounter
    to maintain backward compatibility with existing optimizer code.
    
    Example:
        >>> # New recommended approach:
        >>> from ipfs_datasets_py.utils.cache import GitHubCache
        >>> from ipfs_datasets_py.utils.github import APICounter
        >>> cache = GitHubCache()
        >>> counter = APICounter()
        
        >>> # Old approach (deprecated but still works):
        >>> cache = UnifiedGitHubAPICache()
    """
    
    def __init__(
        self,
        backend = None,  # Ignored, uses GitHubCache defaults
        cache_dir: Optional[Path] = None,
        default_ttl: int = 300,
        config_file: Optional[Path] = None,
    ):
        """Initialize unified GitHub API cache.
        
        Args:
            backend: DEPRECATED - Ignored, GitHubCache handles backend selection
            cache_dir: DEPRECATED - Configured via .github/cache-config.yml
            default_ttl: Default cache TTL in seconds
            config_file: Optional cache-config.yml file path
        """
        # Use new unified modules
        self._github_cache = GitHubCache(
            maxsize=5000,
            default_ttl=default_ttl,
            config_file=str(config_file) if config_file else None
        )
        self._api_counter = APICounter()
        
        # Store config for backward compatibility
        self.default_ttl = default_ttl
        self.cache_dir = cache_dir or Path(".cache/github-api")
    
    def get(self, key: str, operation_type: Optional[str] = None) -> Optional[Tuple[Any, Optional[str]]]:
        """Get value from cache.
        
        Args:
            key: Cache key
            operation_type: Optional operation type for TTL lookup
            
        Returns:
            Tuple of (cached_value, etag) if found and not expired, None otherwise
        """
        # Delegate to GitHubCache
        value = self._github_cache.get(key)
        if value is not None:
            # GitHubCache returns value directly, wrap for compatibility
            etag = getattr(value, 'etag', None) if hasattr(value, '__dict__') else None
            return (value, etag)
        return None
    
    def set(
        self,
        key: str,
        value: Any,
        etag: Optional[str] = None,
        ttl: Optional[int] = None,
        operation_type: Optional[str] = None,
    ) -> None:
        """Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            etag: Optional ETag for conditional requests
            ttl: Optional custom TTL (overrides operation_type and default)
            operation_type: Optional operation type for TTL lookup
        """
        # Delegate to GitHubCache
        self._github_cache.set(key, value, etag=etag, operation_type=operation_type)
    
    def invalidate(self, key: str) -> None:
        """Invalidate cache entry.
        
        Args:
            key: Cache key to invalidate
        """
        # Delegate to GitHubCache
        self._github_cache.delete(key)
    
    def clear(self) -> None:
        """Clear all cache entries."""
        # Delegate to GitHubCache
        self._github_cache.clear()
    
    def count_api_call(
        self,
        call_type: str,
        count: int = 1,
        metadata: Optional[Dict] = None,
        cached: bool = False,
    ) -> None:
        """Count an API call.
        
        Args:
            call_type: Type of API call
            count: Number of calls (default 1)
            metadata: Additional metadata about the call
            cached: Whether this call was served from cache
        """
        # Delegate to APICounter
        self._api_counter.count_call(
            call_type, 
            count=count, 
            cached=cached, 
            **(metadata or {})
        )
    
    def run_gh_command(self, command, timeout: int = 60, check: bool = True):
        """Run a GitHub CLI command and count the API call.
        
        Args:
            command: Command to run
            timeout: Timeout in seconds
            check: Whether to raise on non-zero exit
        
        Returns:
            CompletedProcess instance
        """
        # Delegate to APICounter
        return self._api_counter.run_gh_command(command, timeout=timeout, check=check)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get cache and API call statistics.
        
        Returns:
            Dictionary with statistics
        """
        # Combine statistics from both components
        api_stats = self._api_counter.get_statistics()
        cache_stats = self._github_cache.get_statistics()
        
        return {
            **api_stats,
            'cache_stats': cache_stats,
        }
    
    def save_metrics(self, file_path: Optional[Path] = None) -> None:
        """Save metrics to file.
        
        Args:
            file_path: Optional custom file path
        """
        # Delegate to APICounter
        self._api_counter.save_metrics(file_path)
    
    def report(self) -> str:
        """Generate a human-readable report.
        
        Returns:
            Formatted report string
        """
        # Delegate to APICounter
        return self._api_counter.report()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - save metrics."""
        try:
            self.save_metrics()
        except Exception as e:
            logger.warning(f"Failed to save metrics on exit: {e}")
        return False


# Backward compatibility aliases
GitHubAPICache = UnifiedGitHubAPICache
GitHubAPICounter = UnifiedGitHubAPICache
