# rate_limiting_tools.py

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Union
from datetime import datetime, timedelta
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# Mock implementation classes for rate limiting
class RateLimitStrategy(Enum):
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    LEAKY_BUCKET = "leaky_bucket"

@dataclass
class RateLimitConfig:
    """Configuration for rate limiting rules."""
    name: str
    strategy: RateLimitStrategy
    requests_per_second: float
    burst_capacity: int
    window_size_seconds: int = 60
    enabled: bool = True
    penalties: Dict[str, Any] = field(default_factory=dict)

class MockRateLimiter:
    """Mock rate limiter for testing and development."""
    
    def __init__(self):
        self.limits: Dict[str, RateLimitConfig] = {}
        self.usage_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "requests": 0,
            "blocked": 0,
            "tokens": 0,
            "last_reset": datetime.now(),
            "request_times": deque()
        })
        self.global_stats = {
            "total_requests": 0,
            "total_blocked": 0,
            "active_limits": 0,
            "start_time": datetime.now()
        }
    
    def configure_limit(self, config: RateLimitConfig) -> Dict[str, Any]:
        """Configure a rate limit rule."""
        self.limits[config.name] = config
        self.global_stats["active_limits"] = len(self.limits)
        
        return {
            "name": config.name,
            "strategy": config.strategy.value,
            "configured": True,
            "requests_per_second": config.requests_per_second,
            "burst_capacity": config.burst_capacity,
            "enabled": config.enabled
        }
    
    def check_rate_limit(self, limit_name: str, identifier: str = "default") -> Dict[str, Any]:
        """Check if request is within rate limits."""
        if limit_name not in self.limits:
            return {
                "allowed": True,
                "reason": "No limit configured",
                "remaining": float('inf'),
                "reset_time": None
            }
        
        config = self.limits[limit_name]
        if not config.enabled:
            return {
                "allowed": True,
                "reason": "Rate limiting disabled",
                "remaining": float('inf'),
                "reset_time": None
            }
        
        stats_key = f"{limit_name}:{identifier}"
        stats = self.usage_stats[stats_key]
        current_time = datetime.now()
        
        # Update global stats
        self.global_stats["total_requests"] += 1
        
        # Simple token bucket implementation
        if config.strategy == RateLimitStrategy.TOKEN_BUCKET:
            time_passed = (current_time - stats["last_reset"]).total_seconds()
            tokens_to_add = time_passed * config.requests_per_second
            stats["tokens"] = min(config.burst_capacity, stats["tokens"] + tokens_to_add)
            stats["last_reset"] = current_time
            
            if stats["tokens"] >= 1:
                stats["tokens"] -= 1
                stats["requests"] += 1
                return {
                    "allowed": True,
                    "reason": "Within rate limit",
                    "remaining": int(stats["tokens"]),
                    "reset_time": None
                }
            else:
                stats["blocked"] += 1
                self.global_stats["total_blocked"] += 1
                return {
                    "allowed": False,
                    "reason": "Rate limit exceeded",
                    "remaining": 0,
                    "reset_time": (current_time + timedelta(seconds=1/config.requests_per_second)).isoformat()
                }
        
        # Sliding window implementation
        elif config.strategy == RateLimitStrategy.SLIDING_WINDOW:
            window_start = current_time - timedelta(seconds=config.window_size_seconds)
            # Remove old requests
            while stats["request_times"] and stats["request_times"][0] < window_start:
                stats["request_times"].popleft()
            
            if len(stats["request_times"]) < config.requests_per_second * config.window_size_seconds:
                stats["request_times"].append(current_time)
                stats["requests"] += 1
                return {
                    "allowed": True,
                    "reason": "Within sliding window",
                    "remaining": int(config.requests_per_second * config.window_size_seconds - len(stats["request_times"])),
                    "reset_time": None
                }
            else:
                stats["blocked"] += 1
                self.global_stats["total_blocked"] += 1
                return {
                    "allowed": False,
                    "reason": "Sliding window limit exceeded",
                    "remaining": 0,
                    "reset_time": (stats["request_times"][0] + timedelta(seconds=config.window_size_seconds)).isoformat()
                }
        
        # Default fallback - allow all
        return {
            "allowed": True,
            "reason": "Default allow",
            "remaining": float('inf'),
            "reset_time": None
        }
    
    def get_stats(self, limit_name: Optional[str] = None) -> Dict[str, Any]:
        """Get rate limiting statistics."""
        if limit_name:
            if limit_name not in self.limits:
                return {"error": f"Rate limit '{limit_name}' not found"}
            
            config = self.limits[limit_name]
            limit_stats = {}
            
            # Aggregate stats for this limit
            total_requests = 0
            total_blocked = 0
            
            for key, stats in self.usage_stats.items():
                if key.startswith(f"{limit_name}:"):
                    total_requests += stats["requests"]
                    total_blocked += stats["blocked"]
            
            return {
                "limit_name": limit_name,
                "strategy": config.strategy.value,
                "requests_per_second": config.requests_per_second,
                "burst_capacity": config.burst_capacity,
                "enabled": config.enabled,
                "total_requests": total_requests,
                "total_blocked": total_blocked,
                "block_rate": total_blocked / max(total_requests, 1),
                "active_users": len([k for k in self.usage_stats.keys() if k.startswith(f"{limit_name}:")])
            }
        else:
            # Global stats
            return {
                "global_stats": self.global_stats,
                "active_limits": list(self.limits.keys()),
                "uptime_seconds": (datetime.now() - self.global_stats["start_time"]).total_seconds(),
                "overall_block_rate": self.global_stats["total_blocked"] / max(self.global_stats["total_requests"], 1)
            }
    
    def reset_limits(self, limit_name: Optional[str] = None) -> Dict[str, Any]:
        """Reset rate limiting counters."""
        if limit_name:
            if limit_name not in self.limits:
                return {"error": f"Rate limit '{limit_name}' not found"}
            
            # Reset stats for specific limit
            keys_to_reset = [k for k in self.usage_stats.keys() if k.startswith(f"{limit_name}:")]
            for key in keys_to_reset:
                del self.usage_stats[key]
            
            return {
                "reset": True,
                "limit_name": limit_name,
                "reset_count": len(keys_to_reset),
                "reset_time": datetime.now().isoformat()
            }
        else:
            # Reset all
            reset_count = len(self.usage_stats)
            self.usage_stats.clear()
            self.global_stats.update({
                "total_requests": 0,
                "total_blocked": 0,
                "start_time": datetime.now()
            })
            
            return {
                "reset": True,
                "reset_count": reset_count,
                "reset_time": datetime.now().isoformat()
            }

# Global rate limiter instance
_rate_limiter = MockRateLimiter()

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
