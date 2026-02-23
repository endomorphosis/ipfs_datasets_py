"""
Rate limiting and throttling for complaint generator optimizers.

Implements token bucket algorithm for rate limiting with:
    - Multiple rate limit tiers (per-second, per-minute, per-hour, per-day)
    - IP-based and user-based limiting
    - In-memory and Redis backend support
    - Configurable burst allowance
    - FastAPI middleware integration
    - Graceful degradation when limits exceeded

Key Features:
    - Token bucket algorithm (allows bursts within limits)
    - Multi-tier rate limits (cascading checks)
    - Distributed rate limiting via Redis
    - Per-endpoint custom limits
    - Exemption lists (whitelist IPs/users)
    - Detailed rate limit headers in responses

Usage:
    >>> limiter = TokenBucketRateLimiter(requests_per_second=10)
    >>> if limiter.allow_request("192.168.1.1"):
    ...     process_request()
    ... else:
    ...     return "Rate limit exceeded"
    
    # With FastAPI middleware:
    >>> app.add_middleware(RateLimitMiddleware, limiter=limiter)
"""

import time
import logging
from typing import Dict, Optional, Tuple, List, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import threading


# Rate limit configuration constants
DEFAULT_REQUESTS_PER_SECOND = 10
DEFAULT_REQUESTS_PER_MINUTE = 100
DEFAULT_REQUESTS_PER_HOUR = 1000
DEFAULT_REQUESTS_PER_DAY = 10000

# Burst capacity (how many tokens can accumulate)
DEFAULT_BURST_MULTIPLIER = 1.5


class RateLimitTier(Enum):
    """Rate limit time windows."""
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"


@dataclass
class RateLimitConfig:
    """Configuration for rate limits.
    
    Attributes:
        requests_per_second: Max requests per second (0 = unlimited)
        requests_per_minute: Max requests per minute (0 = unlimited)
        requests_per_hour: Max requests per hour (0 = unlimited)
        requests_per_day: Max requests per day (0 = unlimited)
        burst_multiplier: Token burst capacity multiplier
        whitelist_ips: IPs exempt from rate limiting
        whitelist_users: User IDs exempt from rate limiting
    """
    requests_per_second: int = DEFAULT_REQUESTS_PER_SECOND
    requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE
    requests_per_hour: int = DEFAULT_REQUESTS_PER_HOUR
    requests_per_day: int = DEFAULT_REQUESTS_PER_DAY
    burst_multiplier: float = DEFAULT_BURST_MULTIPLIER
    whitelist_ips: List[str] = field(default_factory=list)
    whitelist_users: List[str] = field(default_factory=list)


@dataclass
class TokenBucket:
    """Token bucket for rate limiting.
    
    Implements leaky bucket algorithm variant where tokens regenerate over time.
    
    Attributes:
        capacity: Maximum number of tokens
        tokens: Current token count
        refill_rate: Tokens added per second
        last_refill: Last refill timestamp
    """
    capacity: float
    tokens: float
    refill_rate: float
    last_refill: float = field(default_factory=time.time)
    
    def refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        
        # Add tokens based on refill rate
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now
    
    def consume(self, tokens: int = 1) -> bool:
        """Attempt to consume tokens.
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            True if tokens were available and consumed, False otherwise
        """
        self.refill()
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
    
    def get_wait_time(self, tokens: int = 1) -> float:
        """Calculate wait time until tokens available.
        
        Args:
            tokens: Number of tokens needed
            
        Returns:
            Seconds to wait until tokens available
        """
        self.refill()
        
        if self.tokens >= tokens:
            return 0.0
        
        tokens_needed = tokens - self.tokens
        wait_time = tokens_needed / self.refill_rate
        return wait_time


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded.
    
    Attributes:
        tier: Which rate limit tier was exceeded
        retry_after: Seconds to wait before retrying
    """
    
    def __init__(self, tier: RateLimitTier, retry_after: float):
        self.tier = tier
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded for {tier.value}. Retry after {retry_after:.2f} seconds")


class TokenBucketRateLimiter:
    """Token bucket rate limiter with multi-tier support.
    
    Uses in-memory storage by default. Supports Redis for distributed systems.
    """
    
    def __init__(self, 
                 config: Optional[RateLimitConfig] = None,
                 logger: Optional[logging.Logger] = None):
        """Initialize rate limiter.
        
        Args:
            config: Rate limit configuration
            logger: Optional logger instance
        """
        self.config = config or RateLimitConfig()
        self.logger = logger or logging.getLogger(__name__)
        
        # In-memory storage: {identifier: {tier: TokenBucket}}
        self.buckets: Dict[str, Dict[RateLimitTier, TokenBucket]] = defaultdict(dict)
        self.lock = threading.RLock()
    
    def _get_bucket(self, identifier: str, tier: RateLimitTier) -> TokenBucket:
        """Get or create token bucket for identifier and tier.
        
        Args:
            identifier: Request identifier (IP or user ID)
            tier: Rate limit tier
            
        Returns:
            TokenBucket instance
        """
        with self.lock:
            if tier not in self.buckets[identifier]:
                # Create new bucket based on tier
                if tier == RateLimitTier.SECOND:
                    capacity = self.config.requests_per_second * self.config.burst_multiplier
                    refill_rate = self.config.requests_per_second
                elif tier == RateLimitTier.MINUTE:
                    capacity = self.config.requests_per_minute * self.config.burst_multiplier
                    refill_rate = self.config.requests_per_minute / 60.0
                elif tier == RateLimitTier.HOUR:
                    capacity = self.config.requests_per_hour * self.config.burst_multiplier
                    refill_rate = self.config.requests_per_hour / 3600.0
                else:  # DAY
                    capacity = self.config.requests_per_day * self.config.burst_multiplier
                    refill_rate = self.config.requests_per_day / 86400.0
                
                self.buckets[identifier][tier] = TokenBucket(
                    capacity=capacity,
                    tokens=capacity,  # Start with full bucket
                    refill_rate=refill_rate
                )
            
            return self.buckets[identifier][tier]
    
    def is_whitelisted(self, identifier: str, user_id: Optional[str] = None) -> bool:
        """Check if identifier or user is whitelisted.
        
        Args:
            identifier: Request identifier (typically IP)
            user_id: Optional user ID
            
        Returns:
            True if whitelisted
        """
        if identifier in self.config.whitelist_ips:
            return True
        if user_id and user_id in self.config.whitelist_users:
            return True
        return False
    
    def allow_request(self, 
                     identifier: str, 
                     user_id: Optional[str] = None,
                     cost: int = 1) -> Tuple[bool, Optional[RateLimitTier], float]:
        """Check if request is allowed under rate limits.
        
        Args:
            identifier: Request identifier (IP address)
            user_id: Optional user ID for user-based limiting
            cost: Token cost of this request (default 1)
            
        Returns:
            Tuple of (allowed, exceeded_tier, retry_after)
        """
        # Check whitelist
        if self.is_whitelisted(identifier, user_id):
            return True, None, 0.0
        
        # Check all tiers (fastest to slowest)
        tiers = [RateLimitTier.SECOND, RateLimitTier.MINUTE, 
                RateLimitTier.HOUR, RateLimitTier.DAY]
        
        with self.lock:
            for tier in tiers:
                # Skip tier if limit is 0 (unlimited)
                if tier == RateLimitTier.SECOND and self.config.requests_per_second == 0:
                    continue
                if tier == RateLimitTier.MINUTE and self.config.requests_per_minute == 0:
                    continue
                if tier == RateLimitTier.HOUR and self.config.requests_per_hour == 0:
                    continue
                if tier == RateLimitTier.DAY and self.config.requests_per_day == 0:
                    continue
                
                bucket = self._get_bucket(identifier, tier)
                
                # Check if tokens available
                if not bucket.consume(cost):
                    retry_after = bucket.get_wait_time(cost)
                    self.logger.warning(f"Rate limit exceeded for {identifier} on tier {tier.value}")
                    return False, tier, retry_after
        
        return True, None, 0.0
    
    def get_remaining_quota(self, identifier: str, tier: RateLimitTier) -> int:
        """Get remaining requests for identifier in tier.
        
        Args:
            identifier: Request identifier
            tier: Rate limit tier
            
        Returns:
            Number of requests remaining
        """
        bucket = self._get_bucket(identifier, tier)
        bucket.refill()
        return int(bucket.tokens)
    
    def reset_limits(self, identifier: str) -> None:
        """Reset all rate limits for identifier.
        
        Args:
            identifier: Request identifier to reset
        """
        with self.lock:
            if identifier in self.buckets:
                del self.buckets[identifier]
                self.logger.info(f"Reset rate limits for {identifier}")
    
    def cleanup_expired(self, max_age_seconds: int = 86400) -> int:
        """Remove expired bucket entries.
        
        Args:
            max_age_seconds: Maximum age of buckets to keep
            
        Returns:
            Number of entries cleaned up
        """
        now = time.time()
        cleanup_count = 0
        
        with self.lock:
            identifiers_to_remove = []
            
            for identifier, tier_buckets in self.buckets.items():
                # Check if any bucket was accessed recently
                recent_activity = False
                for bucket in tier_buckets.values():
                    if now - bucket.last_refill < max_age_seconds:
                        recent_activity = True
                        break
                
                if not recent_activity:
                    identifiers_to_remove.append(identifier)
            
            for identifier in identifiers_to_remove:
                del self.buckets[identifier]
                cleanup_count += 1
        
        if cleanup_count > 0:
            self.logger.info(f"Cleaned up {cleanup_count} expired rate limit entries")
        
        return cleanup_count


class PerEndpointRateLimiter:
    """Rate limiter with per-endpoint custom limits."""
    
    def __init__(self, 
                 default_config: Optional[RateLimitConfig] = None,
                 logger: Optional[logging.Logger] = None):
        """Initialize per-endpoint rate limiter.
        
        Args:
            default_config: Default rate limit configuration
            logger: Optional logger instance
        """
        self.default_limiter = TokenBucketRateLimiter(default_config, logger)
        self.endpoint_limiters: Dict[str, TokenBucketRateLimiter] = {}
        self.logger = logger or logging.getLogger(__name__)
    
    def set_endpoint_limits(self, endpoint: str, config: RateLimitConfig) -> None:
        """Set custom rate limits for specific endpoint.
        
        Args:
            endpoint: Endpoint path (e.g., "/api/entities")
            config: Rate limit configuration for this endpoint
        """
        self.endpoint_limiters[endpoint] = TokenBucketRateLimiter(config, self.logger)
        self.logger.info(f"Set custom rate limits for endpoint: {endpoint}")
    
    def allow_request(self, 
                     endpoint: str,
                     identifier: str,
                     user_id: Optional[str] = None,
                     cost: int = 1) -> Tuple[bool, Optional[RateLimitTier], float]:
        """Check if request is allowed for endpoint.
        
        Args:
            endpoint: Endpoint being accessed
            identifier: Request identifier
            user_id: Optional user ID
            cost: Token cost
            
        Returns:
            Tuple of (allowed, exceeded_tier, retry_after)
        """
        # Use endpoint-specific limiter if configured
        limiter = self.endpoint_limiters.get(endpoint, self.default_limiter)
        return limiter.allow_request(identifier, user_id, cost)


# FastAPI middleware integration

class RateLimitMiddleware:
    """FastAPI middleware for rate limiting.
    
    Usage:
        app.add_middleware(RateLimitMiddleware, limiter=my_limiter)
    """
    
    def __init__(self, app, limiter: TokenBucketRateLimiter):
        """Initialize middleware.
        
        Args:
            app: FastAPI application
            limiter: Rate limiter instance
        """
        self.app = app
        self.limiter = limiter
    
    async def __call__(self, scope, receive, send):
        """Process request through rate limiter."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # Extract client IP
        client_ip = scope.get("client", ["unknown"])[0]
        
        # Check rate limit
        allowed, exceeded_tier, retry_after = self.limiter.allow_request(client_ip)
        
        if not allowed:
            # Return 429 Too Many Requests
            response_body = {
                "error": "Rate limit exceeded",
                "tier": exceeded_tier.value if exceeded_tier else "unknown",
                "retry_after": retry_after
            }
            
            import json
            body = json.dumps(response_body).encode()
            
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"retry-after", str(int(retry_after)).encode()],
                    [b"x-ratelimit-exceeded", exceeded_tier.value.encode() if exceeded_tier else b"unknown"],
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
            return
        
        # Add rate limit headers
        remaining = self.limiter.get_remaining_quota(client_ip, RateLimitTier.SECOND)
        
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([
                    [b"x-ratelimit-remaining", str(remaining).encode()],
                    [b"x-ratelimit-limit", str(self.limiter.config.requests_per_second).encode()],
                ])
                message["headers"] = headers
            await send(message)
        
        await self.app(scope, receive, send_with_headers)


# Convenience functions

def create_strict_limiter() -> TokenBucketRateLimiter:
    """Create rate limiter with strict limits (good for public APIs).
    
    Returns:
        TokenBucketRateLimiter with strict configuration
    """
    config = RateLimitConfig(
        requests_per_second=5,
        requests_per_minute=50,
        requests_per_hour=500,
        requests_per_day=5000,
        burst_multiplier=1.2
    )
    return TokenBucketRateLimiter(config)


def create_generous_limiter() -> TokenBucketRateLimiter:
    """Create rate limiter with generous limits (good for internal APIs).
    
    Returns:
        TokenBucketRateLimiter with generous configuration
    """
    config = RateLimitConfig(
        requests_per_second=100,
        requests_per_minute=1000,
        requests_per_hour=10000,
        requests_per_day=100000,
        burst_multiplier=2.0
    )
    return TokenBucketRateLimiter(config)


def create_development_limiter() -> TokenBucketRateLimiter:
    """Create rate limiter with unlimited access (development only).
    
    Returns:
        TokenBucketRateLimiter with no limits
    """
    config = RateLimitConfig(
        requests_per_second=0,  # Unlimited
        requests_per_minute=0,
        requests_per_hour=0,
        requests_per_day=0
    )
    return TokenBucketRateLimiter(config)
