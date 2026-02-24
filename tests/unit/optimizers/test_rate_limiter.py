"""
Unit tests for rate limiting and throttling.

Tests:
    - Token bucket algorithm
    - Multi-tier rate limits (second/minute/hour/day)
    - Burst capacity handling
    - Whitelist functionality
    - Per-endpoint limits
    - Token refill timing
    - Cleanup of expired entries
    - Wait time calculation
"""

import pytest
import time
from unittest.mock import Mock, patch

from ipfs_datasets_py.optimizers.security.rate_limiter import (
    TokenBucket,
    TokenBucketRateLimiter,
    PerEndpointRateLimiter,
    RateLimitConfig,
    RateLimitTier,
    RateLimitExceeded,
    create_strict_limiter,
    create_generous_limiter,
    create_development_limiter,
)


class TestTokenBucket:
    """Test token bucket algorithm."""
    
    def test_bucket_initialization(self):
        """Test bucket starts with full capacity."""
        bucket = TokenBucket(capacity=10.0, tokens=10.0, refill_rate=1.0)
        assert bucket.capacity == 10.0
        assert bucket.tokens == 10.0
        assert bucket.refill_rate == 1.0
    
    def test_bucket_consume_success(self):
        """Test successful token consumption."""
        bucket = TokenBucket(capacity=10.0, tokens=10.0, refill_rate=1.0)
        assert bucket.consume(5) == True
        assert bucket.tokens == 5.0
    
    def test_bucket_consume_insufficient(self):
        """Test consumption fails when insufficient tokens."""
        bucket = TokenBucket(capacity=10.0, tokens=3.0, refill_rate=1.0)
        assert bucket.consume(5) == False
        assert bucket.tokens == pytest.approx(3.0, abs=0.01)  # Tokens unchanged (allow minor refill)
    
    def test_bucket_refill(self):
        """Test token refill over time."""
        bucket = TokenBucket(capacity=10.0, tokens=0.0, refill_rate=5.0)
        bucket.last_refill = time.time() - 1.0  # 1 second ago
        
        bucket.refill()
        assert bucket.tokens >= 4.5  # Should have refilled ~5 tokens
        assert bucket.tokens <= 5.5
    
    def test_bucket_refill_cap(self):
        """Test refill doesn't exceed capacity."""
        bucket = TokenBucket(capacity=10.0, tokens=8.0, refill_rate=5.0)
        bucket.last_refill = time.time() - 2.0  # 2 seconds ago (would add 10 tokens)
        
        bucket.refill()
        assert bucket.tokens == 10.0  # Capped at capacity
    
    def test_bucket_wait_time(self):
        """Test wait time calculation."""
        bucket = TokenBucket(capacity=10.0, tokens=2.0, refill_rate=2.0)
        
        wait_time = bucket.get_wait_time(5)  # Need 3 more tokens
        expected_wait = 3.0 / 2.0  # 1.5 seconds
        assert 1.4 <= wait_time <= 1.6
    
    def test_bucket_wait_time_zero_when_available(self):
        """Test wait time is zero when tokens available."""
        bucket = TokenBucket(capacity=10.0, tokens=10.0, refill_rate=1.0)
        assert bucket.get_wait_time(5) == 0.0


class TestRateLimitConfig:
    """Test rate limit configuration."""
    
    def test_config_defaults(self):
        """Test default configuration values."""
        config = RateLimitConfig()
        assert config.requests_per_second == 10
        assert config.requests_per_minute == 100
        assert config.requests_per_hour == 1000
        assert config.requests_per_day == 10000
        assert config.burst_multiplier == 1.5
    
    def test_config_custom_values(self):
        """Test custom configuration."""
        config = RateLimitConfig(
            requests_per_second=50,
            requests_per_minute=500,
            whitelist_ips=["127.0.0.1"],
            whitelist_users=["admin"]
        )
        assert config.requests_per_second == 50
        assert "127.0.0.1" in config.whitelist_ips
        assert "admin" in config.whitelist_users


class TestTokenBucketRateLimiter:
    """Test main rate limiter functionality."""
    
    def test_limiter_initialization(self):
        """Test limiter initialization."""
        limiter = TokenBucketRateLimiter()
        assert limiter.config is not None
        assert len(limiter.buckets) == 0
    
    def test_limiter_allow_request_success(self):
        """Test request allowed when under limit."""
        config = RateLimitConfig(requests_per_second=10)
        limiter = TokenBucketRateLimiter(config)
        
        allowed, tier, retry_after = limiter.allow_request("192.168.1.1")
        assert allowed == True
        assert tier is None
        assert retry_after == 0.0
    
    def test_limiter_deny_request_when_exceeded(self):
        """Test request denied when limit exceeded."""
        config = RateLimitConfig(requests_per_second=2, burst_multiplier=1.0)
        limiter = TokenBucketRateLimiter(config)
        
        # Consume all tokens
        limiter.allow_request("192.168.1.1")
        limiter.allow_request("192.168.1.1")
        
        # Third request should be denied
        allowed, tier, retry_after = limiter.allow_request("192.168.1.1")
        assert allowed == False
        assert tier == RateLimitTier.SECOND
        assert retry_after > 0
    
    def test_limiter_whitelist_ip(self):
        """Test whitelisted IP bypasses limits."""
        config = RateLimitConfig(
            requests_per_second=1,
            whitelist_ips=["192.168.1.1"]
        )
        limiter = TokenBucketRateLimiter(config)
        
        # Should allow many requests from whitelisted IP
        for _ in range(10):
            allowed, _, _ = limiter.allow_request("192.168.1.1")
            assert allowed == True
    
    def test_limiter_whitelist_user(self):
        """Test whitelisted user bypasses limits."""
        config = RateLimitConfig(
            requests_per_second=1,
            whitelist_users=["admin"]
        )
        limiter = TokenBucketRateLimiter(config)
        
        # Should allow many requests from whitelisted user
        for _ in range(10):
            allowed, _, _ = limiter.allow_request("192.168.1.1", user_id="admin")
            assert allowed == True
    
    def test_limiter_separate_identifiers(self):
        """Test different identifiers have separate limits."""
        config = RateLimitConfig(requests_per_second=2, burst_multiplier=1.0)
        limiter = TokenBucketRateLimiter(config)
        
        # Exhaust limit for IP1
        limiter.allow_request("192.168.1.1")
        limiter.allow_request("192.168.1.1")
        
        # IP2 should still be allowed
        allowed, _, _ = limiter.allow_request("192.168.1.2")
        assert allowed == True
    
    def test_limiter_burst_capacity(self):
        """Test burst capacity allows temporary spike."""
        config = RateLimitConfig(requests_per_second=10, burst_multiplier=2.0)
        limiter = TokenBucketRateLimiter(config)
        
        # Should allow burst up to 20 requests initially
        success_count = 0
        for _ in range(25):
            allowed, _, _ = limiter.allow_request("192.168.1.1")
            if allowed:
                success_count += 1
        
        # Should allow burst (20) but not much more
        assert 18 <= success_count <= 22
    
    def test_limiter_token_refill(self):
        """Test tokens refill over time."""
        config = RateLimitConfig(requests_per_second=10, burst_multiplier=1.0)
        limiter = TokenBucketRateLimiter(config)
        
        # Exhaust tokens
        for _ in range(10):
            limiter.allow_request("192.168.1.1")
        
        # Should be denied immediately
        allowed, _, _ = limiter.allow_request("192.168.1.1")
        assert allowed == False
        
        # Wait for refill (0.2 seconds should add ~2 tokens)
        time.sleep(0.2)
        
        # Should be allowed again
        allowed, _, _ = limiter.allow_request("192.168.1.1")
        assert allowed == True
    
    def test_limiter_multi_tier_minute(self):
        """Test minute-level rate limiting."""
        config = RateLimitConfig(
            requests_per_second=100,  # High per-second limit
            requests_per_minute=5,    # Low per-minute limit
            burst_multiplier=1.0
        )
        limiter = TokenBucketRateLimiter(config)
        
        # Exhaust minute limit
        for _ in range(5):
            limiter.allow_request("192.168.1.1")
        
        # Should be denied by minute limit
        allowed, tier, _ = limiter.allow_request("192.168.1.1")
        assert allowed == False
        assert tier == RateLimitTier.MINUTE
    
    def test_limiter_cost_parameter(self):
        """Test custom cost per request."""
        config = RateLimitConfig(requests_per_second=10, burst_multiplier=1.0)
        limiter = TokenBucketRateLimiter(config)
        
        # Make request with cost=5
        limiter.allow_request("192.168.1.1", cost=5)
        
        # Should have consumed 5 tokens, only 5 remaining
        remaining = limiter.get_remaining_quota("192.168.1.1", RateLimitTier.SECOND)
        assert 4 <= remaining <= 6
    
    def test_limiter_get_remaining_quota(self):
        """Test getting remaining quota."""
        config = RateLimitConfig(requests_per_second=10, burst_multiplier=1.0)
        limiter = TokenBucketRateLimiter(config)
        
        # Initial quota should be full
        remaining = limiter.get_remaining_quota("192.168.1.1", RateLimitTier.SECOND)
        assert remaining == 10
        
        # After 3 requests, should have 7 remaining
        for _ in range(3):
            limiter.allow_request("192.168.1.1")
        
        remaining = limiter.get_remaining_quota("192.168.1.1", RateLimitTier.SECOND)
        assert remaining == 7
    
    def test_limiter_reset_limits(self):
        """Test resetting limits for identifier."""
        config = RateLimitConfig(requests_per_second=2, burst_multiplier=1.0)
        limiter = TokenBucketRateLimiter(config)
        
        # Exhaust limits
        limiter.allow_request("192.168.1.1")
        limiter.allow_request("192.168.1.1")
        
        # Should be denied
        allowed, _, _ = limiter.allow_request("192.168.1.1")
        assert allowed == False
        
        # Reset limits
        limiter.reset_limits("192.168.1.1")
        
        # Should be allowed again
        allowed, _, _ = limiter.allow_request("192.168.1.1")
        assert allowed == True
    
    def test_limiter_cleanup_expired(self):
        """Test cleanup of expired entries."""
        config = RateLimitConfig(requests_per_second=10)
        limiter = TokenBucketRateLimiter(config)
        
        # Create entries for multiple IPs
        for i in range(5):
            limiter.allow_request(f"192.168.1.{i}")
        
        assert len(limiter.buckets) == 5
        
        # Mark old entries by manipulating last_refill
        for identifier, tier_buckets in limiter.buckets.items():
            for bucket in tier_buckets.values():
                bucket.last_refill = time.time() - 90000  # Old entry
        
        # Cleanup with 1 day threshold
        cleaned = limiter.cleanup_expired(max_age_seconds=86400)
        assert cleaned == 5
        assert len(limiter.buckets) == 0
    
    def test_limiter_unlimited_tier(self):
        """Test tier with 0 limit (unlimited)."""
        config = RateLimitConfig(
            requests_per_second=0,  # Unlimited
            requests_per_minute=10
        )
        limiter = TokenBucketRateLimiter(config)
        
        # Should allow many requests (per-second unlimited)
        for _ in range(100):
            allowed, _, _ = limiter.allow_request("192.168.1.1")
            # Will eventually hit minute limit, but not second limit
            if not allowed:
                break
        
        # Should have been denied by minute limit, not second
        allowed, tier, _ = limiter.allow_request("192.168.1.1")
        if not allowed:
            assert tier == RateLimitTier.MINUTE


class TestPerEndpointRateLimiter:
    """Test per-endpoint rate limiting."""
    
    def test_per_endpoint_initialization(self):
        """Test per-endpoint limiter initialization."""
        limiter = PerEndpointRateLimiter()
        assert limiter.default_limiter is not None
        assert len(limiter.endpoint_limiters) == 0
    
    def test_per_endpoint_custom_limits(self):
        """Test setting custom limits for endpoint."""
        limiter = PerEndpointRateLimiter()
        
        # Set strict limits for specific endpoint
        strict_config = RateLimitConfig(requests_per_second=1)
        limiter.set_endpoint_limits("/api/expensive", strict_config)
        
        # Default endpoint should have different limits
        allowed, _, _ = limiter.allow_request("/api/cheap", "192.168.1.1")
        assert allowed == True
        
        # Expensive endpoint should have strict limits
        limiter.allow_request("/api/expensive", "192.168.1.1")
        allowed, _, _ = limiter.allow_request("/api/expensive", "192.168.1.1")
        assert allowed == False  # Exceeded 1 req/s limit
    
    def test_per_endpoint_separate_quotas(self):
        """Test endpoints have separate quotas."""
        default_config = RateLimitConfig(requests_per_second=5, burst_multiplier=1.0)
        limiter = PerEndpointRateLimiter(default_config)
        
        endpoint1_config = RateLimitConfig(requests_per_second=2, burst_multiplier=1.0)
        limiter.set_endpoint_limits("/api/endpoint1", endpoint1_config)
        
        # Exhaust endpoint1 limit
        limiter.allow_request("/api/endpoint1", "192.168.1.1")
        limiter.allow_request("/api/endpoint1", "192.168.1.1")
        
        # endpoint1 should be denied
        allowed, _, _ = limiter.allow_request("/api/endpoint1", "192.168.1.1")
        assert allowed == False
        
        # endpoint2 should still be allowed (using default limit)
        allowed, _, _ = limiter.allow_request("/api/endpoint2", "192.168.1.1")
        assert allowed == True


class TestConvenienceFunctions:
    """Test convenience limiter creation functions."""
    
    def test_create_strict_limiter(self):
        """Test strict limiter creation."""
        limiter = create_strict_limiter()
        assert limiter.config.requests_per_second == 5
        assert limiter.config.requests_per_minute == 50
    
    def test_create_generous_limiter(self):
        """Test generous limiter creation."""
        limiter = create_generous_limiter()
        assert limiter.config.requests_per_second == 100
        assert limiter.config.requests_per_minute == 1000
    
    def test_create_development_limiter(self):
        """Test development limiter (unlimited)."""
        limiter = create_development_limiter()
        assert limiter.config.requests_per_second == 0  # Unlimited
        
        # Should allow many requests
        for _ in range(1000):
            allowed, _, _ = limiter.allow_request("192.168.1.1")
            assert allowed == True


class TestRateLimitScenarios:
    """Test real-world rate limiting scenarios."""
    
    def test_api_burst_handling(self):
        """Test handling of API burst traffic."""
        config = RateLimitConfig(requests_per_second=10, burst_multiplier=2.0)
        limiter = TokenBucketRateLimiter(config)
        
        # Simulate burst of 15 requests
        allowed_count = 0
        for _ in range(15):
            allowed, _, _ = limiter.allow_request("192.168.1.1")
            if allowed:
                allowed_count += 1
        
        # Should allow burst of ~20 requests
        assert allowed_count >= 15
    
    def test_sustained_load(self):
        """Test sustained load over time."""
        config = RateLimitConfig(requests_per_second=10, burst_multiplier=1.0)
        limiter = TokenBucketRateLimiter(config)
        
        total_allowed = 0
        duration = 0.5  # 0.5 second test
        start_time = time.time()
        
        while time.time() - start_time < duration:
            allowed, _, _ = limiter.allow_request("192.168.1.1")
            if allowed:
                total_allowed += 1
            time.sleep(0.01)  # Small delay between requests
        
        # Should allow roughly 10 req/s * 0.5s = 5 requests
        # Allow some variance due to timing
        assert 4 <= total_allowed <= 15
    
    def test_ddos_protection(self):
        """Test protection against DDoS patterns."""
        config = RateLimitConfig(requests_per_second=5, burst_multiplier=1.0)
        limiter = TokenBucketRateLimiter(config)
        
        # Simulate DDoS: rapid fire requests
        denied_count = 0
        for _ in range(20):
            allowed, _, _ = limiter.allow_request("192.168.1.1")
            if not allowed:
                denied_count += 1
        
        # Should deny most requests beyond limit
        assert denied_count >= 10
    
    def test_multi_user_fairness(self):
        """Test fair distribution across multiple users."""
        config = RateLimitConfig(requests_per_second=10, burst_multiplier=1.0)
        limiter = TokenBucketRateLimiter(config)
        
        # Multiple users making requests
        users = ["192.168.1.1", "192.168.1.2", "192.168.1.3"]
        
        # Each user should get their own quota
        for user in users:
            for _ in range(10):
                allowed, _, _ = limiter.allow_request(user)
                assert allowed == True  # Each user gets full quota
            
            # 11th request should be denied for each user
            allowed, _, _ = limiter.allow_request(user)
            assert allowed == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
