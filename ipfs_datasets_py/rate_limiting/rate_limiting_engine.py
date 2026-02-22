"""
Rate Limiting Engine — reusable core for rate limiting logic.

Domain models, enums, and the mock rate limiter used by MCP tools.
Extracted from mcp_server/tools/rate_limiting_tools/rate_limiting_tools.py
so that tests, CLI tools, and the MCP layer all share the same implementation.

Reusable by:
- MCP server tools: from ipfs_datasets_py.rate_limiting.rate_limiting_engine import ...
- CLI commands
- Direct Python imports
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


class RateLimitStrategy(Enum):
    """Available rate limiting algorithms."""

    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    LEAKY_BUCKET = "leaky_bucket"


@dataclass
class RateLimitConfig:
    """Configuration for a single rate limiting rule."""

    name: str
    strategy: RateLimitStrategy
    requests_per_second: float
    burst_capacity: int
    window_size_seconds: int = 60
    enabled: bool = True
    penalties: Dict[str, Any] = field(default_factory=dict)


class MockRateLimiter:
    """Mock rate limiter for testing and development.

    Supports token-bucket and sliding-window strategies.
    """

    def __init__(self) -> None:
        self.limits: Dict[str, RateLimitConfig] = {}
        self.usage_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "requests": 0,
                "blocked": 0,
                "tokens": 0,
                "last_reset": datetime.now(),
                "request_times": deque(),
            }
        )
        self.global_stats: Dict[str, Any] = {
            "total_requests": 0,
            "total_blocked": 0,
            "active_limits": 0,
            "start_time": datetime.now(),
        }

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def configure_limit(self, config: RateLimitConfig) -> Dict[str, Any]:
        """Register or replace a rate limit rule."""
        self.limits[config.name] = config
        self.global_stats["active_limits"] = len(self.limits)
        return {
            "name": config.name,
            "strategy": config.strategy.value,
            "configured": True,
            "requests_per_second": config.requests_per_second,
            "burst_capacity": config.burst_capacity,
            "enabled": config.enabled,
        }

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    def check_rate_limit(
        self, limit_name: str, identifier: str = "default"
    ) -> Dict[str, Any]:
        """Check whether *identifier* is within the *limit_name* rule."""
        if limit_name not in self.limits:
            return {
                "allowed": True,
                "reason": "No limit configured",
                "remaining": float("inf"),
                "reset_time": None,
            }

        config = self.limits[limit_name]
        if not config.enabled:
            return {
                "allowed": True,
                "reason": "Rate limiting disabled",
                "remaining": float("inf"),
                "reset_time": None,
            }

        stats_key = f"{limit_name}:{identifier}"
        # Initialize token count to burst_capacity on first access for token bucket
        if stats_key not in self.usage_stats and config.strategy == RateLimitStrategy.TOKEN_BUCKET:
            self.usage_stats[stats_key]["tokens"] = config.burst_capacity
        stats = self.usage_stats[stats_key]
        now = datetime.now()
        self.global_stats["total_requests"] += 1

        if config.strategy == RateLimitStrategy.TOKEN_BUCKET:
            return self._check_token_bucket(config, stats, now)
        if config.strategy == RateLimitStrategy.SLIDING_WINDOW:
            return self._check_sliding_window(config, stats, now)

        # Default: allow
        return {
            "allowed": True,
            "reason": "Default allow",
            "remaining": float("inf"),
            "reset_time": None,
        }

    def _check_token_bucket(
        self,
        config: RateLimitConfig,
        stats: Dict[str, Any],
        now: datetime,
    ) -> Dict[str, Any]:
        elapsed = (now - stats["last_reset"]).total_seconds()
        stats["tokens"] = min(
            config.burst_capacity,
            stats["tokens"] + elapsed * config.requests_per_second,
        )
        stats["last_reset"] = now

        if stats["tokens"] >= 1:
            stats["tokens"] -= 1
            stats["requests"] += 1
            return {
                "allowed": True,
                "reason": "Within rate limit",
                "remaining": int(stats["tokens"]),
                "reset_time": None,
            }

        stats["blocked"] += 1
        self.global_stats["total_blocked"] += 1
        return {
            "allowed": False,
            "reason": "Rate limit exceeded",
            "remaining": 0,
            "reset_time": (
                now + timedelta(seconds=1.0 / config.requests_per_second)
            ).isoformat(),
        }

    def _check_sliding_window(
        self,
        config: RateLimitConfig,
        stats: Dict[str, Any],
        now: datetime,
    ) -> Dict[str, Any]:
        window_start = now - timedelta(seconds=config.window_size_seconds)
        req_times: Deque[datetime] = stats["request_times"]

        while req_times and req_times[0] < window_start:
            req_times.popleft()

        capacity = config.requests_per_second * config.window_size_seconds
        if len(req_times) < capacity:
            req_times.append(now)
            stats["requests"] += 1
            return {
                "allowed": True,
                "reason": "Within sliding window",
                "remaining": int(capacity - len(req_times)),
                "reset_time": None,
            }

        stats["blocked"] += 1
        self.global_stats["total_blocked"] += 1
        return {
            "allowed": False,
            "reason": "Sliding window limit exceeded",
            "remaining": 0,
            "reset_time": (
                req_times[0] + timedelta(seconds=config.window_size_seconds)
            ).isoformat(),
        }

    # ------------------------------------------------------------------
    # Stats & reset
    # ------------------------------------------------------------------

    def get_stats(self, limit_name: Optional[str] = None) -> Dict[str, Any]:
        """Return per-limit or global statistics."""
        if limit_name:
            if limit_name not in self.limits:
                return {"error": f"Rate limit '{limit_name}' not found"}
            config = self.limits[limit_name]
            total_req = total_blocked = 0
            for key, stats in self.usage_stats.items():
                if key.startswith(f"{limit_name}:"):
                    total_req += stats["requests"]
                    total_blocked += stats["blocked"]
            return {
                "limit_name": limit_name,
                "strategy": config.strategy.value,
                "requests_per_second": config.requests_per_second,
                "burst_capacity": config.burst_capacity,
                "enabled": config.enabled,
                "total_requests": total_req,
                "total_blocked": total_blocked,
                "block_rate": total_blocked / max(total_req, 1),
                "active_users": sum(
                    1 for k in self.usage_stats if k.startswith(f"{limit_name}:")
                ),
            }

        return {
            "global_stats": self.global_stats,
            "active_limits": list(self.limits.keys()),
            "uptime_seconds": (
                datetime.now() - self.global_stats["start_time"]
            ).total_seconds(),
            "overall_block_rate": self.global_stats["total_blocked"]
            / max(self.global_stats["total_requests"], 1),
        }

    def reset_limits(self, limit_name: Optional[str] = None) -> Dict[str, Any]:
        """Reset usage counters for *limit_name* (or all limits if None)."""
        if limit_name:
            if limit_name not in self.limits:
                return {"error": f"Rate limit '{limit_name}' not found"}
            keys = [k for k in self.usage_stats if k.startswith(f"{limit_name}:")]
            for key in keys:
                del self.usage_stats[key]
            return {
                "reset": True,
                "limit_name": limit_name,
                "reset_count": len(keys),
                "reset_time": datetime.now().isoformat(),
            }

        reset_count = len(self.usage_stats)
        self.usage_stats.clear()
        self.global_stats.update(
            {
                "total_requests": 0,
                "total_blocked": 0,
                "start_time": datetime.now(),
            }
        )
        return {
            "reset": True,
            "reset_count": reset_count,
            "reset_time": datetime.now().isoformat(),
        }


# Module-level singleton.
_default_rate_limiter: Optional[MockRateLimiter] = None


def get_default_rate_limiter() -> MockRateLimiter:
    """Return (creating if needed) the module-level singleton rate limiter."""
    global _default_rate_limiter
    if _default_rate_limiter is None:
        _default_rate_limiter = MockRateLimiter()
    return _default_rate_limiter


__all__ = [
    "RateLimitStrategy",
    "RateLimitConfig",
    "MockRateLimiter",
    "get_default_rate_limiter",
]
