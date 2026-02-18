# ipfs_datasets_py/mcp_server/tools/cache_tools/cache_tools.py
"""
Cache management and optimization tools (Thin Wrapper).

Thin MCP wrapper that delegates to CacheManager core module.
"""

import logging
from typing import Dict, Any, List, Optional, Union
from ipfs_datasets_py.caching import CacheManager

logger = logging.getLogger(__name__)
_cache_manager = None

def get_cache_manager() -> CacheManager:
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager

async def cache_get(key: str, namespace: str = "default") -> Dict[str, Any]:
    result = get_cache_manager().get(key, namespace)
    result.setdefault("status", "success" if result.get("success", True) else "error")
    return result

async def cache_set(key: str, value: Any, ttl: Optional[int] = None, namespace: str = "default") -> Dict[str, Any]:
    result = get_cache_manager().set(key, value, ttl, namespace)
    result.setdefault("status", "success" if result.get("success", True) else "error")
    return result

async def cache_delete(key: str, namespace: str = "default") -> Dict[str, Any]:
    result = get_cache_manager().delete(key, namespace)
    result.setdefault("status", "success" if result.get("success", True) else "error")
    return result

async def cache_clear(namespace: str = "default") -> Dict[str, Any]:
    result = get_cache_manager().clear(namespace)
    result.setdefault("status", "success" if result.get("success", True) else "error")
    return result

async def manage_cache(operation: Optional[str] = None, key: Optional[str] = None, value: Optional[Any] = None, 
                      ttl: Optional[int] = None, namespace: str = "default", action: Optional[str] = None, 
                      cache_type: Optional[str] = None) -> Dict[str, Any]:
    """Manage cache operations. Delegates to CacheManager."""
    try:
        operation = operation or action
        namespace = cache_type if cache_type and namespace == "default" else namespace
        
        if not operation:
            return {"success": False, "error": "Operation is required", 
                   "valid_operations": ["get", "set", "delete", "clear", "stats", "list"]}
        
        manager = get_cache_manager()
        
        if operation == "get":
            return {**manager.get(key, namespace), "operation": operation} if key else {"success": False, "error": "Key required"}
        elif operation == "set":
            return {**manager.set(key, value, ttl, namespace), "operation": operation} if key and value is not None else {"success": False, "error": "Key/value required"}
        elif operation == "delete":
            return {**manager.delete(key, namespace), "operation": operation} if key else {"success": False, "error": "Key required"}
        elif operation == "clear":
            return {**manager.clear(namespace), "operation": operation}
        elif operation == "stats":
            result = manager.get_stats(namespace if namespace != "default" else None)
            return {**result, "operation": operation, "status": "success", "cache_stats": result["global_stats"], 
                   "stats": result["global_stats"], "namespaces": result["namespace_stats"]}
        elif operation == "list":
            return {**manager.list_keys(namespace if namespace != "default" else None), "operation": operation}
        else:
            return {"success": False, "error": f"Unknown operation: {operation}", 
                   "valid_operations": ["get", "set", "delete", "clear", "stats", "list"]}
    except Exception as e:
        logger.error(f"Cache operation failed: {e}")
        return {"success": False, "operation": operation, "error": str(e)}

async def optimize_cache(cache_type: Optional[str] = None, strategy: str = "lru", 
                        max_size_mb: Optional[int] = None, max_age_hours: Optional[int] = None) -> Dict[str, Any]:
    """Optimize cache. Delegates to CacheManager."""
    try:
        namespace = cache_type if cache_type and cache_type != "default" else None
        result = get_cache_manager().optimize(strategy, max_size_mb, max_age_hours, namespace)
        result.update({"status": "success", "optimization_strategy": strategy})
        if max_size_mb: result["max_size_mb"] = max_size_mb
        if max_age_hours: result["max_age_hours"] = max_age_hours
        return result
    except Exception as e:
        logger.error(f"Cache optimization failed: {e}")
        return {"success": False, "error": str(e)}

async def cache_embeddings(text: str, embeddings: Union[List[float], str], model: str = "default", 
                          ttl: Optional[int] = None) -> Dict[str, Any]:
    """Cache embeddings. Delegates to CacheManager."""
    try:
        if isinstance(embeddings, str):
            import json
            embeddings = json.loads(embeddings)
        result = get_cache_manager().cache_embeddings(text, embeddings, model, ttl)
        return {**result, "status": "success", "cache_operation": "set"}
    except Exception as e:
        logger.error(f"Failed to cache embeddings: {e}")
        return {"success": False, "status": "error", "error": str(e)}

async def get_cached_embeddings(text: str, model: str = "default") -> Dict[str, Any]:
    """Get cached embeddings. Delegates to CacheManager."""
    try:
        result = get_cache_manager().get_cached_embeddings(text, model)
        result["status"] = "found" if result.get("cache_hit") else "not_found"
        return result
    except Exception as e:
        logger.error(f"Failed to get cached embeddings: {e}")
        return {"success": False, "status": "error", "error": str(e)}

async def cache_stats(namespace: Optional[str] = None) -> Dict[str, Any]:
    """Get cache stats. Delegates to CacheManager."""
    try:
        result = get_cache_manager().get_stats(namespace)
        return {**result, "status": "success", "stats": result["global_stats"]}
    except Exception as e:
        logger.error(f"Cache stats failed: {e}")
        return {"success": False, "error": str(e)}
