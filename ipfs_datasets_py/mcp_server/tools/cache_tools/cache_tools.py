# ipfs_datasets_py/mcp_server/tools/cache_tools/cache_tools.py
"""
Cache management and optimization tools.
Migrated from ipfs_embeddings_py project.
"""

import logging
import anyio
import hashlib
import json
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Global cache storage for demonstration
CACHE_STORAGE = {}
CACHE_METADATA = {}
CACHE_STATS = {
    "hits": 0,
    "misses": 0,
    "evictions": 0,
    "total_operations": 0
}


async def manage_cache(
    operation: str,
    key: Optional[str] = None,
    value: Optional[Any] = None,
    ttl: Optional[int] = None,
    namespace: str = "default"
) -> Dict[str, Any]:
    """
    Manage cache operations including get, set, delete, and clear.
    
    Args:
        operation: Cache operation (get, set, delete, clear, stats, list)
        key: Cache key for get/set/delete operations
        value: Value to store (for set operation)
        ttl: Time to live in seconds (for set operation)
        namespace: Cache namespace for organization
        
    Returns:
        Dict containing operation results
    """
    try:
        timestamp = datetime.now()
        cache_key = f"{namespace}:{key}" if key else None
        
        CACHE_STATS["total_operations"] += 1
        
        if operation == "get":
            if not key:
                return {
                    "success": False,
                    "operation": operation,
                    "error": "Key is required for get operation"
                }
                
            # Check if key exists and is not expired
            if cache_key in CACHE_STORAGE:
                metadata = CACHE_METADATA.get(cache_key, {})
                expires_at = metadata.get("expires_at")
                
                if expires_at and datetime.fromisoformat(expires_at) < timestamp:
                    # Key has expired, remove it
                    del CACHE_STORAGE[cache_key]
                    del CACHE_METADATA[cache_key]
                    CACHE_STATS["misses"] += 1
                    CACHE_STATS["evictions"] += 1
                    
                    return {
                        "success": True,
                        "operation": operation,
                        "key": key,
                        "value": None,
                        "hit": False,
                        "reason": "expired"
                    }
                else:
                    # Key exists and is valid
                    CACHE_STATS["hits"] += 1
                    metadata["last_accessed"] = timestamp.isoformat()
                    metadata["access_count"] = metadata.get("access_count", 0) + 1
                    
                    return {
                        "success": True,
                        "operation": operation,
                        "key": key,
                        "value": CACHE_STORAGE[cache_key],
                        "hit": True,
                        "metadata": metadata
                    }
            else:
                # Key not found
                CACHE_STATS["misses"] += 1
                return {
                    "success": True,
                    "operation": operation,
                    "key": key,
                    "value": None,
                    "hit": False,
                    "reason": "not_found"
                }
                
        elif operation == "set":
            if not key or value is None:
                return {
                    "success": False,
                    "operation": operation,
                    "error": "Key and value are required for set operation"
                }
                
            # Calculate expiration time
            expires_at = None
            if ttl:
                expires_at = (timestamp + timedelta(seconds=ttl)).isoformat()
                
            # Store value and metadata
            CACHE_STORAGE[cache_key] = value
            CACHE_METADATA[cache_key] = {
                "created_at": timestamp.isoformat(),
                "expires_at": expires_at,
                "ttl": ttl,
                "namespace": namespace,
                "access_count": 0,
                "size_bytes": len(str(value).encode('utf-8'))
            }
            
            return {
                "success": True,
                "operation": operation,
                "key": key,
                "stored": True,
                "expires_at": expires_at,
                "namespace": namespace
            }
            
        elif operation == "delete":
            if not key:
                return {
                    "success": False,
                    "operation": operation,
                    "error": "Key is required for delete operation"
                }
                
            if cache_key in CACHE_STORAGE:
                del CACHE_STORAGE[cache_key]
                del CACHE_METADATA[cache_key]
                
                return {
                    "success": True,
                    "operation": operation,
                    "key": key,
                    "deleted": True
                }
            else:
                return {
                    "success": True,
                    "operation": operation,
                    "key": key,
                    "deleted": False,
                    "reason": "not_found"
                }
                
        elif operation == "clear":
            # Clear cache for specific namespace or all
            keys_to_delete = []
            
            if namespace == "all":
                keys_to_delete = list(CACHE_STORAGE.keys())
            else:
                keys_to_delete = [k for k in CACHE_STORAGE.keys() if k.startswith(f"{namespace}:")]
                
            for key_to_delete in keys_to_delete:
                del CACHE_STORAGE[key_to_delete]
                if key_to_delete in CACHE_METADATA:
                    del CACHE_METADATA[key_to_delete]
                    
            return {
                "success": True,
                "operation": operation,
                "namespace": namespace,
                "keys_cleared": len(keys_to_delete),
                "cleared_keys": keys_to_delete[:10]  # Limit output
            }
            
        elif operation == "stats":
            # Calculate cache statistics
            total_size = sum(meta.get("size_bytes", 0) for meta in CACHE_METADATA.values())
            expired_keys = []
            
            for cache_key, metadata in CACHE_METADATA.items():
                expires_at = metadata.get("expires_at")
                if expires_at and datetime.fromisoformat(expires_at) < timestamp:
                    expired_keys.append(cache_key)
                    
            # Calculate hit rate
            total_gets = CACHE_STATS["hits"] + CACHE_STATS["misses"]
            hit_rate = (CACHE_STATS["hits"] / total_gets * 100) if total_gets > 0 else 0
            
            return {
                "success": True,
                "operation": operation,
                "cache_stats": {
                    "total_keys": len(CACHE_STORAGE),
                    "total_size_bytes": total_size,
                    "total_size_mb": round(total_size / (1024 * 1024), 2),
                    "expired_keys": len(expired_keys),
                    "hit_rate_percent": round(hit_rate, 2),
                    "total_hits": CACHE_STATS["hits"],
                    "total_misses": CACHE_STATS["misses"],
                    "total_evictions": CACHE_STATS["evictions"],
                    "total_operations": CACHE_STATS["total_operations"]
                },
                "namespaces": _get_namespace_stats()
            }
            
        elif operation == "list":
            # List cache keys with optional filtering
            namespace_filter = namespace if namespace != "default" else None
            
            keys_info = []
            for cache_key, metadata in CACHE_METADATA.items():
                if namespace_filter and not cache_key.startswith(f"{namespace_filter}:"):
                    continue
                    
                # Check if expired
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
                "operation": operation,
                "total_keys": len(keys_info),
                "keys": keys_info[:50],  # Limit to first 50 keys
                "namespace_filter": namespace_filter
            }
            
        else:
            return {
                "success": False,
                "operation": operation,
                "error": f"Unknown operation: {operation}",
                "valid_operations": ["get", "set", "delete", "clear", "stats", "list"]
            }
            
    except Exception as e:
        logger.error(f"Cache operation '{operation}' failed: {e}")
        return {
            "success": False,
            "operation": operation,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def optimize_cache(
    strategy: str = "lru",
    max_size_mb: Optional[int] = None,
    max_age_hours: Optional[int] = None
) -> Dict[str, Any]:
    """
    Optimize cache performance through cleanup and reorganization.
    
    Args:
        strategy: Optimization strategy (lru, lfu, size_based, age_based)
        max_size_mb: Maximum cache size in MB
        max_age_hours: Maximum age for cache entries in hours
        
    Returns:
        Dict containing optimization results
    """
    try:
        timestamp = datetime.now()
        optimization_stats = {
            "strategy": strategy,
            "keys_before": len(CACHE_STORAGE),
            "size_before_mb": 0,
            "keys_removed": 0,
            "size_freed_mb": 0,
            "operations": []
        }
        
        # Calculate initial cache size
        initial_size = sum(meta.get("size_bytes", 0) for meta in CACHE_METADATA.values())
        optimization_stats["size_before_mb"] = round(initial_size / (1024 * 1024), 2)
        
        keys_to_remove = []
        
        # Remove expired keys first
        for cache_key, metadata in CACHE_METADATA.items():
            expires_at = metadata.get("expires_at")
            if expires_at and datetime.fromisoformat(expires_at) < timestamp:
                keys_to_remove.append(cache_key)
                
        if keys_to_remove:
            optimization_stats["operations"].append(f"Removed {len(keys_to_remove)} expired keys")
            
        # Apply age-based cleanup
        if max_age_hours:
            cutoff_time = timestamp - timedelta(hours=max_age_hours)
            for cache_key, metadata in CACHE_METADATA.items():
                created_at = metadata.get("created_at")
                if created_at and datetime.fromisoformat(created_at) < cutoff_time:
                    keys_to_remove.append(cache_key)
                    
            optimization_stats["operations"].append(f"Applied age-based cleanup (max_age: {max_age_hours}h)")
            
        # Apply strategy-based optimization
        if strategy == "lru":  # Least Recently Used
            # Sort by last_accessed (oldest first)
            sorted_keys = sorted(
                CACHE_METADATA.items(),
                key=lambda x: x[1].get("last_accessed", x[1].get("created_at", ""))
            )
            
            # Remove oldest 10% if cache is large
            if len(sorted_keys) > 100:
                remove_count = max(1, len(sorted_keys) // 10)
                for cache_key, _ in sorted_keys[:remove_count]:
                    keys_to_remove.append(cache_key)
                optimization_stats["operations"].append(f"LRU: Removed {remove_count} least recently used keys")
                
        elif strategy == "lfu":  # Least Frequently Used
            # Sort by access_count (lowest first)
            sorted_keys = sorted(
                CACHE_METADATA.items(),
                key=lambda x: x[1].get("access_count", 0)
            )
            
            # Remove least used 10% if cache is large
            if len(sorted_keys) > 100:
                remove_count = max(1, len(sorted_keys) // 10)
                for cache_key, _ in sorted_keys[:remove_count]:
                    keys_to_remove.append(cache_key)
                optimization_stats["operations"].append(f"LFU: Removed {remove_count} least frequently used keys")
                
        elif strategy == "size_based":
            # Remove largest entries if max_size_mb is set
            if max_size_mb:
                max_size_bytes = max_size_mb * 1024 * 1024
                current_size = sum(meta.get("size_bytes", 0) for meta in CACHE_METADATA.values())
                
                if current_size > max_size_bytes:
                    # Sort by size (largest first)
                    sorted_keys = sorted(
                        CACHE_METADATA.items(),
                        key=lambda x: x[1].get("size_bytes", 0),
                        reverse=True
                    )
                    
                    freed_size = 0
                    for cache_key, metadata in sorted_keys:
                        if current_size - freed_size <= max_size_bytes:
                            break
                        keys_to_remove.append(cache_key)
                        freed_size += metadata.get("size_bytes", 0)
                        
                    optimization_stats["operations"].append(f"Size-based: Removed large entries to fit under {max_size_mb}MB")
                    
        # Remove duplicate keys from removal list
        keys_to_remove = list(set(keys_to_remove))
        
        # Calculate freed space
        freed_size = 0
        for key in keys_to_remove:
            if key in CACHE_METADATA:
                freed_size += CACHE_METADATA[key].get("size_bytes", 0)
                
        # Actually remove the keys
        for key in keys_to_remove:
            if key in CACHE_STORAGE:
                del CACHE_STORAGE[key]
            if key in CACHE_METADATA:
                del CACHE_METADATA[key]
                
        CACHE_STATS["evictions"] += len(keys_to_remove)
        
        # Update optimization stats
        optimization_stats["keys_removed"] = len(keys_to_remove)
        optimization_stats["size_freed_mb"] = round(freed_size / (1024 * 1024), 2)
        optimization_stats["keys_after"] = len(CACHE_STORAGE)
        
        final_size = sum(meta.get("size_bytes", 0) for meta in CACHE_METADATA.values())
        optimization_stats["size_after_mb"] = round(final_size / (1024 * 1024), 2)
        
        return {
            "success": True,
            "optimization_stats": optimization_stats,
            "cache_health": {
                "total_keys": len(CACHE_STORAGE),
                "total_size_mb": optimization_stats["size_after_mb"],
                "optimization_time": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Cache optimization failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def cache_embeddings(
    text: str,
    model: str,
    embeddings: List[float],
    metadata: Optional[Dict[str, Any]] = None,
    ttl: int = 3600
) -> Dict[str, Any]:
    """
    Cache embedding results for text and model combinations.
    
    Args:
        text: Input text that was embedded
        model: Model used for embedding
        embeddings: Embedding vector
        metadata: Additional metadata to store
        ttl: Time to live in seconds
        
    Returns:
        Dict containing caching results
    """
    try:
        # Create cache key from text and model
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        cache_key = f"embeddings:{model}:{text_hash}"
        
        # Store embedding with metadata
        cache_value = {
            "embeddings": embeddings,
            "text_preview": text[:100] + "..." if len(text) > 100 else text,
            "model": model,
            "dimension": len(embeddings),
            "metadata": metadata or {},
            "cached_at": datetime.now().isoformat()
        }
        
        # Use cache management function
        result = await manage_cache(
            operation="set",
            key=cache_key,
            value=cache_value,
            ttl=ttl,
            namespace="embeddings"
        )
        
        if result["success"]:
            return {
                "success": True,
                "cache_key": cache_key,
                "text_hash": text_hash,
                "model": model,
                "dimension": len(embeddings),
                "ttl": ttl,
                "message": "Embeddings cached successfully"
            }
        else:
            return result
            
    except Exception as e:
        logger.error(f"Failed to cache embeddings: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def get_cached_embeddings(
    text: str,
    model: str
) -> Dict[str, Any]:
    """
    Retrieve cached embeddings for text and model combination.
    
    Args:
        text: Input text to find embeddings for
        model: Model used for embedding
        
    Returns:
        Dict containing cached embeddings or miss result
    """
    try:
        # Create cache key from text and model
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        cache_key = f"embeddings:{model}:{text_hash}"
        
        # Try to get from cache
        result = await manage_cache(
            operation="get",
            key=cache_key,
            namespace="embeddings"
        )
        
        if result["success"] and result["hit"]:
            cached_data = result["value"]
            return {
                "success": True,
                "cache_hit": True,
                "embeddings": cached_data["embeddings"],
                "model": cached_data["model"],
                "dimension": cached_data["dimension"],
                "cached_at": cached_data["cached_at"],
                "metadata": cached_data.get("metadata", {})
            }
        else:
            return {
                "success": True,
                "cache_hit": False,
                "reason": result.get("reason", "not_found"),
                "text_hash": text_hash,
                "model": model
            }
            
    except Exception as e:
        logger.error(f"Failed to get cached embeddings: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


def _get_namespace_stats() -> Dict[str, Any]:
    """Get statistics for each namespace."""
    namespace_stats = {}
    
    for cache_key, metadata in CACHE_METADATA.items():
        namespace = metadata.get("namespace", "unknown")
        
        if namespace not in namespace_stats:
            namespace_stats[namespace] = {
                "key_count": 0,
                "total_size_bytes": 0,
                "total_access_count": 0
            }
            
        namespace_stats[namespace]["key_count"] += 1
        namespace_stats[namespace]["total_size_bytes"] += metadata.get("size_bytes", 0)
        namespace_stats[namespace]["total_access_count"] += metadata.get("access_count", 0)
        
    # Convert to MB and add derived stats
    for namespace, stats in namespace_stats.items():
        stats["total_size_mb"] = round(stats["total_size_bytes"] / (1024 * 1024), 2)
        stats["avg_access_count"] = round(stats["total_access_count"] / stats["key_count"], 2) if stats["key_count"] > 0 else 0
        
    return namespace_stats


async def cache_stats(namespace: Optional[str] = None) -> Dict[str, Any]:
    """
    Get detailed cache statistics and performance metrics.
    
    Args:
        namespace: Optional namespace to filter stats. If None, returns global stats.
        
    Returns:
        Dict containing cache statistics and performance metrics
    """
    try:
        global_stats = CACHE_STATS.copy()
        
        # Calculate hit rate
        total_requests = global_stats["hits"] + global_stats["misses"]
        hit_rate = (global_stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        
        # Get memory usage stats
        total_keys = len(CACHE_STORAGE)
        total_size_bytes = sum(
            CACHE_METADATA.get(key, {}).get("size_bytes", 0) 
            for key in CACHE_STORAGE.keys()
        )
        
        # Get namespace-specific stats
        namespace_stats = _get_namespace_stats()
        
        result = {
            "success": True,
            "global_stats": {
                **global_stats,
                "hit_rate_percent": round(hit_rate, 2),
                "total_keys": total_keys,
                "total_size_bytes": total_size_bytes,
                "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
                "active_namespaces": len(namespace_stats)
            },
            "namespace_stats": namespace_stats,
            "timestamp": datetime.now().isoformat()
        }
        
        # Filter by namespace if specified
        if namespace:
            result["filtered_namespace"] = namespace
            result["namespace_data"] = namespace_stats.get(namespace, {
                "key_count": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0,
                "total_access_count": 0,
                "avg_access_count": 0
            })
            
        return result
        
    except Exception as e:
        logger.error(f"Cache stats retrieval failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
