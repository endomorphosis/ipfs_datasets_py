#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cache Manager

Core business logic for cache management, optimization, and statistics.
Reusable by CLI, MCP tools, and third-party packages.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class CacheManager:
    """
    General-purpose cache manager with support for multiple backends and policies.
    
    Provides methods for:
    - Cache operations (get, set, delete, clear)
    - Cache statistics and monitoring
    - Cache optimization (LRU, LFU, size-based, age-based)
    - Namespace management
    - Embeddings caching
    
    Example:
        >>> manager = CacheManager()
        >>> manager.set("key1", "value1", ttl=3600, namespace="app")
        >>> result = manager.get("key1", namespace="app")
        >>> stats = manager.get_stats()
    """
    
    def __init__(self):
        """Initialize the CacheManager with in-memory storage."""
        self.storage: Dict[str, Any] = {}
        self.metadata: Dict[str, Dict[str, Any]] = {}
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "total_operations": 0
        }
    
    def get(self, key: str, namespace: str = "default") -> Dict[str, Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            namespace: Cache namespace
            
        Returns:
            Dictionary with success status and value (if found)
        """
        cache_key = f"{namespace}:{key}"
        timestamp = datetime.now()
        self.stats["total_operations"] += 1
        
        if cache_key in self.storage:
            metadata = self.metadata.get(cache_key, {})
            expires_at = metadata.get("expires_at")
            
            # Check expiration
            if expires_at and datetime.fromisoformat(expires_at) < timestamp:
                del self.storage[cache_key]
                del self.metadata[cache_key]
                self.stats["misses"] += 1
                self.stats["evictions"] += 1
                
                return {
                    "success": True,
                    "key": key,
                    "value": None,
                    "hit": False,
                    "reason": "expired"
                }
            
            # Update access metadata
            self.stats["hits"] += 1
            metadata["last_accessed"] = timestamp.isoformat()
            metadata["access_count"] = metadata.get("access_count", 0) + 1
            
            return {
                "success": True,
                "key": key,
                "value": self.storage[cache_key],
                "hit": True,
                "metadata": metadata
            }
        
        self.stats["misses"] += 1
        return {
            "success": True,
            "key": key,
            "value": None,
            "hit": False,
            "reason": "not_found"
        }
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        namespace: str = "default"
    ) -> Dict[str, Any]:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to store
            ttl: Time to live in seconds
            namespace: Cache namespace
            
        Returns:
            Dictionary with success status
        """
        cache_key = f"{namespace}:{key}"
        timestamp = datetime.now()
        self.stats["total_operations"] += 1
        
        expires_at = None
        if ttl:
            expires_at = (timestamp + timedelta(seconds=ttl)).isoformat()
        
        self.storage[cache_key] = value
        self.metadata[cache_key] = {
            "created_at": timestamp.isoformat(),
            "expires_at": expires_at,
            "ttl": ttl,
            "namespace": namespace,
            "access_count": 0,
            "size_bytes": len(str(value).encode('utf-8'))
        }
        
        return {
            "success": True,
            "key": key,
            "stored": True,
            "expires_at": expires_at,
            "namespace": namespace
        }
    
    def delete(self, key: str, namespace: str = "default") -> Dict[str, Any]:
        """
        Delete value from cache.
        
        Args:
            key: Cache key
            namespace: Cache namespace
            
        Returns:
            Dictionary with success status
        """
        cache_key = f"{namespace}:{key}"
        self.stats["total_operations"] += 1
        
        if cache_key in self.storage:
            del self.storage[cache_key]
            del self.metadata[cache_key]
            
            return {
                "success": True,
                "key": key,
                "deleted": True
            }
        
        return {
            "success": True,
            "key": key,
            "deleted": False,
            "reason": "not_found"
        }
    
    def clear(self, namespace: str = "default") -> Dict[str, Any]:
        """
        Clear cache for namespace.
        
        Args:
            namespace: Cache namespace to clear, or "all" for all namespaces
            
        Returns:
            Dictionary with number of keys cleared
        """
        keys_to_delete = []
        
        if namespace == "all":
            keys_to_delete = list(self.storage.keys())
        else:
            keys_to_delete = [k for k in self.storage.keys() if k.startswith(f"{namespace}:")]
        
        for key in keys_to_delete:
            del self.storage[key]
            if key in self.metadata:
                del self.metadata[key]
        
        return {
            "success": True,
            "namespace": namespace,
            "keys_cleared": len(keys_to_delete)
        }
    
    def get_stats(self, namespace: Optional[str] = None) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Args:
            namespace: Optional namespace to filter stats
            
        Returns:
            Dictionary containing cache statistics
        """
        timestamp = datetime.now()
        
        # Calculate global stats
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        
        total_keys = len(self.storage)
        total_size_bytes = sum(
            self.metadata.get(key, {}).get("size_bytes", 0)
            for key in self.storage.keys()
        )
        
        # Get namespace-specific stats
        namespace_stats = self._get_namespace_stats()
        
        result = {
            "success": True,
            "global_stats": {
                **self.stats,
                "hit_rate_percent": round(hit_rate, 2),
                "total_keys": total_keys,
                "total_size_bytes": total_size_bytes,
                "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
                "active_namespaces": len(namespace_stats)
            },
            "namespace_stats": namespace_stats,
            "timestamp": timestamp.isoformat()
        }
        
        if namespace:
            result["filtered_namespace"] = namespace
            result["namespace_data"] = namespace_stats.get(namespace, {})
        
        return result
    
    def list_keys(self, namespace: Optional[str] = None) -> Dict[str, Any]:
        """
        List cache keys with metadata.
        
        Args:
            namespace: Optional namespace to filter keys
            
        Returns:
            Dictionary containing list of keys with metadata
        """
        timestamp = datetime.now()
        keys_info = []
        
        for cache_key, metadata in self.metadata.items():
            if namespace and not cache_key.startswith(f"{namespace}:"):
                continue
            
            expires_at = metadata.get("expires_at")
            is_expired = expires_at and datetime.fromisoformat(expires_at) < timestamp
            
            keys_info.append({
                "key": cache_key,
                "namespace": metadata.get("namespace", "unknown"),
                "created_at": metadata.get("created_at"),
                "expires_at": metadata.get("expires_at"),
                "is_expired": is_expired,
                "access_count": metadata.get("access_count", 0),
                "size_bytes": metadata.get("size_bytes", 0)
            })
        
        return {
            "success": True,
            "total_keys": len(keys_info),
            "keys": keys_info,
            "namespace_filter": namespace
        }
    
    def optimize(
        self,
        strategy: str = "lru",
        max_size_mb: Optional[int] = None,
        max_age_hours: Optional[int] = None,
        namespace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Optimize cache performance.
        
        Args:
            strategy: Optimization strategy (lru, lfu, size_based, age_based)
            max_size_mb: Maximum cache size in MB
            max_age_hours: Maximum age for entries in hours
            namespace: Optional namespace to optimize
            
        Returns:
            Dictionary containing optimization results
        """
        timestamp = datetime.now()
        keys_to_remove = []
        
        # Filter by namespace if specified
        target_keys = (
            [k for k in self.metadata.keys() if k.startswith(f"{namespace}:")]
            if namespace
            else list(self.metadata.keys())
        )
        
        # Remove expired entries
        for cache_key in target_keys:
            metadata = self.metadata[cache_key]
            expires_at = metadata.get("expires_at")
            
            if expires_at and datetime.fromisoformat(expires_at) < timestamp:
                keys_to_remove.append(cache_key)
        
        # Apply age-based eviction
        if max_age_hours:
            cutoff = timestamp - timedelta(hours=max_age_hours)
            for cache_key in target_keys:
                if cache_key in keys_to_remove:
                    continue
                
                created_at = self.metadata[cache_key].get("created_at")
                if created_at and datetime.fromisoformat(created_at) < cutoff:
                    keys_to_remove.append(cache_key)
        
        # Apply size-based eviction
        if max_size_mb:
            current_size = sum(
                self.metadata[k].get("size_bytes", 0)
                for k in target_keys
                if k not in keys_to_remove
            )
            max_size_bytes = max_size_mb * 1024 * 1024
            
            if current_size > max_size_bytes:
                # Sort by strategy
                candidates = [
                    (k, self.metadata[k])
                    for k in target_keys
                    if k not in keys_to_remove
                ]
                
                if strategy == "lru":
                    candidates.sort(key=lambda x: x[1].get("last_accessed", x[1].get("created_at", "")))
                elif strategy == "lfu":
                    candidates.sort(key=lambda x: x[1].get("access_count", 0))
                elif strategy == "size_based":
                    candidates.sort(key=lambda x: x[1].get("size_bytes", 0), reverse=True)
                else:  # age_based
                    candidates.sort(key=lambda x: x[1].get("created_at", ""))
                
                # Remove keys until under size limit
                for cache_key, metadata in candidates:
                    if current_size <= max_size_bytes:
                        break
                    keys_to_remove.append(cache_key)
                    current_size -= metadata.get("size_bytes", 0)
        
        # Remove identified keys
        for cache_key in keys_to_remove:
            if cache_key in self.storage:
                del self.storage[cache_key]
            if cache_key in self.metadata:
                del self.metadata[cache_key]
            self.stats["evictions"] += 1
        
        return {
            "success": True,
            "strategy": strategy,
            "keys_evicted": len(keys_to_remove),
            "evicted_keys": keys_to_remove[:10],  # Limit output
            "timestamp": timestamp.isoformat()
        }
    
    def cache_embeddings(
        self,
        text: str,
        embeddings: List[float],
        model: str = "default",
        ttl: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Cache embeddings for text.
        
        Args:
            text: Input text
            embeddings: Embedding vector
            model: Model name
            ttl: Time to live in seconds
            
        Returns:
            Dictionary with success status
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        cache_key = f"{model}:{text_hash}"
        
        return self.set(
            key=cache_key,
            value={"text": text, "embeddings": embeddings, "model": model},
            ttl=ttl or 86400,  # Default 24 hours
            namespace="embeddings"
        )
    
    def get_cached_embeddings(
        self,
        text: str,
        model: str = "default"
    ) -> Dict[str, Any]:
        """
        Get cached embeddings for text.
        
        Args:
            text: Input text
            model: Model name
            
        Returns:
            Dictionary with embeddings if found
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        cache_key = f"{model}:{text_hash}"
        
        result = self.get(key=cache_key, namespace="embeddings")
        
        if result.get("hit"):
            value = result.get("value", {})
            return {
                "success": True,
                "cache_hit": True,
                "embeddings": value.get("embeddings"),
                "model": model,
                "text_hash": text_hash
            }
        
        return {
            "success": True,
            "cache_hit": False,
            "reason": result.get("reason", "not_found"),
            "text_hash": text_hash,
            "model": model
        }
    
    def _get_namespace_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for each namespace."""
        namespace_stats = defaultdict(lambda: {
            "key_count": 0,
            "total_size_bytes": 0,
            "total_access_count": 0
        })
        
        for cache_key, metadata in self.metadata.items():
            namespace = metadata.get("namespace", "unknown")
            namespace_stats[namespace]["key_count"] += 1
            namespace_stats[namespace]["total_size_bytes"] += metadata.get("size_bytes", 0)
            namespace_stats[namespace]["total_access_count"] += metadata.get("access_count", 0)
        
        # Add derived stats
        for namespace, stats in namespace_stats.items():
            stats["total_size_mb"] = round(stats["total_size_bytes"] / (1024 * 1024), 2)
            stats["avg_access_count"] = (
                round(stats["total_access_count"] / stats["key_count"], 2)
                if stats["key_count"] > 0 else 0
            )
        
        return dict(namespace_stats)
