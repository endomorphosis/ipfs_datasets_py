"""
Rate Limiting Tools for IPFS Datasets MCP Server

Provides token-bucket rate limiting for MCP tool calls: configure per-client
or global rate limits, check current quota, and consume tokens. Integrated
with the RateLimiter engine for in-memory and Redis-backed operation.

Core functions: configure_rate_limits, check_rate_limit,
consume_rate_limit_token, get_rate_limit_status.
"""
# rate_limiting_tools/__init__.py

from .rate_limiting_tools import (
    configure_rate_limits,
    check_rate_limit,
    manage_rate_limits,
    RateLimitStrategy,
    RateLimitConfig,
    MockRateLimiter
)

__all__ = [
    "configure_rate_limits",
    "check_rate_limit", 
    "manage_rate_limits",
    "RateLimitStrategy",
    "RateLimitConfig",
    "MockRateLimiter"
]
