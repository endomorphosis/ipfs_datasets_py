"""Unified caching infrastructure.

This module provides a unified caching system with support for local TTL-based
caching, distributed P2P caching, and GitHub API-specific caching.

Public API:
- LocalCache: Thread-safe TTL-based local cache
- GitHubCache: GitHub API-specific cache with ETag support
- P2PCache: Distributed P2P cache (stub, falls back to local)
- CacheConfig: Configuration loader
- BaseCache: Abstract base for custom caches

Example:
    >>> from ipfs_datasets_py.utils.cache import LocalCache, GitHubCache
    >>> 
    >>> # Local cache
    >>> cache = LocalCache(maxsize=100, default_ttl=300)
    >>> cache.set("key", "value")
    >>> value = cache.get("key")
    >>> 
    >>> # GitHub API cache
    >>> gh_cache = GitHubCache()
    >>> gh_cache.set("repos/owner/repo", response, etag="abc", operation_type="get_repo_info")
"""

# Base classes
from .base import (
    BaseCache,
    DistributedCache,
    CacheBackend,
    CacheEntry,
    CacheStats,
)

# Implementations
from .local import LocalCache, QueryCache
from .github_cache import GitHubCache, GitHubCacheEntry
from .p2p import P2PCache

# Configuration
from .config_loader import (
    CacheConfig,
    get_global_config,
    set_global_config,
)

__all__ = [
    # Base classes
    'BaseCache',
    'DistributedCache',
    'CacheBackend',
    'CacheEntry',
    'CacheStats',
    
    # Implementations
    'LocalCache',
    'QueryCache',  # Backward compatibility
    'GitHubCache',
    'GitHubCacheEntry',
    'P2PCache',
    
    # Configuration
    'CacheConfig',
    'get_global_config',
    'set_global_config',
]
