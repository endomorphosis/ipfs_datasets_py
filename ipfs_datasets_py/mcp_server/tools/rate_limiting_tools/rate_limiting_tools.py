# rate_limiting_tools.py — thin MCP wrapper
"""
Rate limiting tools for MCP server.

Business logic (RateLimitStrategy, RateLimitConfig, MockRateLimiter) lives in
ipfs_datasets_py.rate_limiting.rate_limiting_engine.  This module is a thin
MCP wrapper that validates inputs, delegates to the engine, and formats responses.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from ipfs_datasets_py.rate_limiting.rate_limiting_engine import (  # noqa: F401
    RateLimitStrategy,
    RateLimitConfig,
    MockRateLimiter,
    get_default_rate_limiter,
)

logger = logging.getLogger(__name__)

# Module-level singleton — shared across calls within one server process.
_rate_limiter = get_default_rate_limiter()

async def configure_rate_limits(
    limits: List[Dict[str, Any]],
    apply_immediately: bool = True,
    backup_current: bool = True
) -> Dict[str, Any]:
    """
    Configure rate limiting rules for API endpoints and operations.
    
    Args:
        limits: List of rate limit configurations
        apply_immediately: Whether to apply limits immediately
        backup_current: Whether to backup current configuration
    
    Returns:
        Dict containing configuration results
    """
    try:
        logger.info(f"Configuring {len(limits)} rate limit rules")
        
        configured_limits = []
        errors = []
        
        # Backup current config if requested
        backup = None
        if backup_current:
            backup = {
                "limits": {name: {
                    "strategy": config.strategy.value,
                    "requests_per_second": config.requests_per_second,
                    "burst_capacity": config.burst_capacity,
                    "enabled": config.enabled
                } for name, config in _rate_limiter.limits.items()},
                "backup_time": datetime.now().isoformat()
            }
        
        # Configure each limit
        for limit_config in limits:
            try:
                config = RateLimitConfig(
                    name=limit_config["name"],
                    strategy=RateLimitStrategy(limit_config.get("strategy", "token_bucket")),
                    requests_per_second=limit_config["requests_per_second"],
                    burst_capacity=limit_config.get("burst_capacity", int(limit_config["requests_per_second"] * 2)),
                    window_size_seconds=limit_config.get("window_size_seconds", 60),
                    enabled=limit_config.get("enabled", True),
                    penalties=limit_config.get("penalties", {})
                )
                
                result = _rate_limiter.configure_limit(config)
                configured_limits.append(result)
                
            except Exception as e:
                error_msg = f"Failed to configure limit '{limit_config.get('name', 'unknown')}': {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        return {
            "configured_count": len(configured_limits),
            "configured_limits": configured_limits,
            "errors": errors,
            "applied_immediately": apply_immediately,
            "backup": backup,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Rate limit configuration failed: {e}")
        raise

async def check_rate_limit(
    limit_name: str,
    identifier: str = "default",
    request_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Check if a request is within rate limits.
    
    Args:
        limit_name: Name of the rate limit rule to check
        identifier: Unique identifier for the requester (user ID, IP, etc.)
        request_metadata: Additional metadata about the request
    
    Returns:
        Dict containing rate limit check results
    """
    try:
        logger.debug(f"Checking rate limit '{limit_name}' for identifier '{identifier}'")
        
        result = _rate_limiter.check_rate_limit(limit_name, identifier)
        
        # Add metadata to result
        result.update({
            "limit_name": limit_name,
            "identifier": identifier,
            "check_time": datetime.now().isoformat(),
            "metadata": request_metadata or {}
        })
        
        if not result["allowed"]:
            logger.warning(f"Rate limit exceeded for {identifier} on {limit_name}: {result['reason']}")
        
        return result
        
    except Exception as e:
        logger.error(f"Rate limit check failed: {e}")
        raise

async def manage_rate_limits(
    action: str,
    limit_name: Optional[str] = None,
    new_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Manage rate limiting configuration and operations.
    
    Args:
        action: Management action to perform
        limit_name: Specific limit to manage (for targeted actions)
        new_config: New configuration data (for update actions)
    
    Returns:
        Dict containing management operation results
    """
    try:
        logger.info(f"Managing rate limits: action={action}, limit={limit_name}")
        
        if action == "list":
            limits_info = []
            for name, config in _rate_limiter.limits.items():
                limits_info.append({
                    "name": name,
                    "strategy": config.strategy.value,
                    "requests_per_second": config.requests_per_second,
                    "burst_capacity": config.burst_capacity,
                    "enabled": config.enabled
                })
            
            return {
                "action": "list",
                "limits": limits_info,
                "total_count": len(limits_info)
            }
        
        elif action == "enable":
            if not limit_name:
                return {"error": "limit_name required for enable action"}
            
            if limit_name not in _rate_limiter.limits:
                return {"error": f"Rate limit '{limit_name}' not found"}
            
            _rate_limiter.limits[limit_name].enabled = True
            return {
                "action": "enable",
                "limit_name": limit_name,
                "enabled": True,
                "timestamp": datetime.now().isoformat()
            }
        
        elif action == "disable":
            if not limit_name:
                return {"error": "limit_name required for disable action"}
            
            if limit_name not in _rate_limiter.limits:
                return {"error": f"Rate limit '{limit_name}' not found"}
            
            _rate_limiter.limits[limit_name].enabled = False
            return {
                "action": "disable",
                "limit_name": limit_name,
                "enabled": False,
                "timestamp": datetime.now().isoformat()
            }
        
        elif action == "delete":
            if not limit_name:
                return {"error": "limit_name required for delete action"}
            
            if limit_name not in _rate_limiter.limits:
                return {"error": f"Rate limit '{limit_name}' not found"}
            
            del _rate_limiter.limits[limit_name]
            _rate_limiter.global_stats["active_limits"] = len(_rate_limiter.limits)
            
            return {
                "action": "delete",
                "limit_name": limit_name,
                "deleted": True,
                "timestamp": datetime.now().isoformat()
            }
        
        elif action == "update":
            if not limit_name or not new_config:
                return {"error": "limit_name and new_config required for update action"}
            
            if limit_name not in _rate_limiter.limits:
                return {"error": f"Rate limit '{limit_name}' not found"}
            
            config = _rate_limiter.limits[limit_name]
            
            # Update configuration
            if "requests_per_second" in new_config:
                config.requests_per_second = new_config["requests_per_second"]
            if "burst_capacity" in new_config:
                config.burst_capacity = new_config["burst_capacity"]
            if "enabled" in new_config:
                config.enabled = new_config["enabled"]
            if "strategy" in new_config:
                config.strategy = RateLimitStrategy(new_config["strategy"])
            
            return {
                "action": "update",
                "limit_name": limit_name,
                "updated_config": {
                    "requests_per_second": config.requests_per_second,
                    "burst_capacity": config.burst_capacity,
                    "enabled": config.enabled,
                    "strategy": config.strategy.value
                },
                "timestamp": datetime.now().isoformat()
            }
        
        elif action == "stats":
            return _rate_limiter.get_stats(limit_name)
        
        elif action == "reset":
            return _rate_limiter.reset_limits(limit_name)
        
        else:
            return {"error": f"Unknown action: {action}"}
        
    except Exception as e:
        logger.error(f"Rate limit management failed: {e}")
        raise
