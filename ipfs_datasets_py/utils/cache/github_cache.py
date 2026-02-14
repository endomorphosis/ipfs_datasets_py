"""GitHub API-specific cache implementation.

This module provides a specialized cache for GitHub API responses with
ETag support, operation-specific TTLs, and rate limit awareness.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .base import BaseCache, CacheEntry
from .config_loader import get_global_config

logger = logging.getLogger(__name__)


@dataclass
class GitHubCacheEntry(CacheEntry):
    """GitHub API cache entry with ETag support.
    
    Extends CacheEntry with GitHub-specific fields:
    - etag: ETag for conditional requests
    - operation_type: Type of GitHub operation
    """
    etag: Optional[str] = None
    operation_type: Optional[str] = None


class GitHubCache(BaseCache):
    """Specialized cache for GitHub API responses.
    
    Features:
    - ETag support for conditional requests
    - Per-operation TTL configuration
    - Rate limit aware caching
    - Content-addressed keys
    
    Example:
        >>> cache = GitHubCache()
        >>> cache.set("repos/owner/repo", response, etag="abc123", operation_type="get_repo_info")
        >>> cached = cache.get("repos/owner/repo")
        >>> if cached:
        ...     print(f"ETag: {cache.get_etag('repos/owner/repo')}")
    """
    
    def __init__(
        self,
        maxsize: Optional[int] = None,
        default_ttl: Optional[int] = None,
        config_file: Optional[str] = None
    ):
        """Initialize GitHub cache.
        
        Args:
            maxsize: Maximum cache entries (uses config if None)
            default_ttl: Default TTL in seconds (uses config if None)
            config_file: Path to cache-config.yml (auto-detected if None)
        """
        # Load configuration
        if config_file:
            from pathlib import Path
            from .config_loader import CacheConfig
            self._config = CacheConfig(cache_config_file=Path(config_file))
        else:
            self._config = get_global_config()
        
        # Use config values if not provided
        if maxsize is None:
            maxsize = self._config.maxsize
        if default_ttl is None:
            default_ttl = self._config.default_ttl
        
        super().__init__(maxsize=maxsize, default_ttl=default_ttl, name="GitHubCache")
        
        # Storage for entries
        self._entries: Dict[str, GitHubCacheEntry] = {}
        
        logger.info(f"Initialized {self.name} with config from {self._config.config_dir}")
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.
        
        Args:
            key: Cache key (e.g., "repos/owner/repo")
            
        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            try:
                if key in self._entries:
                    entry = self._entries[key]
                    if not entry.is_expired():
                        entry.touch()
                        self._record_hit()
                        return entry.value
                    else:
                        # Remove expired entry
                        del self._entries[key]
                        self._record_eviction()
                
                self._record_miss()
                return None
                
            except Exception as e:
                logger.error(f"Error getting key {key}: {e}")
                self._record_error()
                return None
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        etag: Optional[str] = None,
        operation_type: Optional[str] = None,
        **metadata
    ) -> None:
        """Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses operation-specific or default if None)
            etag: ETag from GitHub API response
            operation_type: Type of operation (e.g., "list_repos", "get_repo_info")
            **metadata: Additional metadata
        """
        with self._lock:
            try:
                # Determine TTL
                if ttl is None:
                    if operation_type:
                        ttl = self._config.get_operation_ttl(operation_type)
                    else:
                        ttl = self.default_ttl
                
                expires_at = datetime.now() + timedelta(seconds=ttl)
                
                # Create entry
                entry = GitHubCacheEntry(
                    key=key,
                    value=value,
                    expires_at=expires_at,
                    etag=etag,
                    operation_type=operation_type,
                    metadata=metadata
                )
                
                # Check if we need to evict
                if len(self._entries) >= self.maxsize and key not in self._entries:
                    # Evict oldest entry
                    oldest_key = min(
                        self._entries.keys(),
                        key=lambda k: self._entries[k].last_accessed
                    )
                    del self._entries[oldest_key]
                    self._record_eviction()
                
                self._entries[key] = entry
                self._record_set()
                
                if operation_type:
                    logger.debug(f"Cached {operation_type}: {key} (ttl={ttl}s)")
                
            except Exception as e:
                logger.error(f"Error setting key {key}: {e}")
                self._record_error()
    
    def delete(self, key: str) -> bool:
        """Delete entry from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            if key in self._entries:
                del self._entries[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._entries.clear()
            logger.info(f"Cleared {self.name}")
    
    def size(self) -> int:
        """Get current cache size.
        
        Returns:
            Number of entries in cache
        """
        with self._lock:
            return len(self._entries)
    
    def get_etag(self, key: str) -> Optional[str]:
        """Get ETag for cached entry.
        
        Args:
            key: Cache key
            
        Returns:
            ETag string or None if not found
        """
        with self._lock:
            if key in self._entries:
                return self._entries[key].etag
            return None
    
    def make_cache_key(self, *parts: str) -> str:
        """Create cache key from parts.
        
        Args:
            *parts: Key components (e.g., "repos", "owner", "repo")
            
        Returns:
            Cache key string
        """
        key = "/".join(str(p) for p in parts)
        # Hash very long keys
        if len(key) > 200:
            return hashlib.sha256(key.encode()).hexdigest()
        return key
    
    def invalidate_by_operation(self, operation_type: str) -> int:
        """Invalidate all entries for an operation type.
        
        Args:
            operation_type: Operation type to invalidate
            
        Returns:
            Number of entries invalidated
        """
        with self._lock:
            to_delete = [
                key for key, entry in self._entries.items()
                if entry.operation_type == operation_type
            ]
            for key in to_delete:
                del self._entries[key]
            
            if to_delete:
                logger.info(f"Invalidated {len(to_delete)} entries for {operation_type}")
            
            return len(to_delete)
