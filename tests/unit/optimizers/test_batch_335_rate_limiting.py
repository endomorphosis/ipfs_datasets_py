"""
Batch 335: Rate Limiting & Throttling
======================================

Implements sophisticated rate limiting strategies for controlling
API call rates, bandwidth throttling, and preventing resource overload.

Goal: Provide:
- Token bucket rate limiting
- Sliding window algorithms
- Adaptive throttling based on load
- Per-client and global rate limits
- Metrics and monitoring
"""

import pytest
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import threading


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class LimitStrategy(Enum):
    """Rate limit strategies."""
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    LEAKY_BUCKET = "leaky_bucket"


@dataclass
class RateLimitMetrics:
    """Metrics for rate limiting."""
    total_requests: int = 0
    allowed_requests: int = 0
    rejected_requests: int = 0
    last_reset_at: float = 0.0
    
    def allow_rate(self) -> float:
        """Get allow rate (0.0-1.0)."""
        if self.total_requests == 0:
            return 0.0
        return self.allowed_requests / self.total_requests
    
    def rejection_rate(self) -> float:
        """Get rejection rate (0.0-1.0)."""
        if self.total_requests == 0:
            return 0.0
        return self.rejected_requests / self.total_requests


# ============================================================================
# RATE LIMITERS
# ============================================================================

class TokenBucketLimiter:
    """Token bucket rate limiter."""
    
    def __init__(self, capacity: float, refill_rate: float):
        """Initialize token bucket.
        
        Args:
            capacity: Maximum tokens in bucket
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill_at = time.time()
        self.metrics = RateLimitMetrics(last_reset_at=time.time())
        self._lock = threading.Lock()
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill_at
        
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill_at = now
    
    def allow_request(self, tokens_needed: float = 1.0) -> bool:
        """Check if request can be allowed.
        
        Args:
            tokens_needed: Tokens required for request
            
        Returns:
            True if request allowed
        """
        with self._lock:
            self._refill()
            
            self.metrics.total_requests += 1
            
            if self.tokens >= tokens_needed:
                self.tokens -= tokens_needed
                self.metrics.allowed_requests += 1
                return True
            else:
                self.metrics.rejected_requests += 1
                return False
    
    def get_metrics(self) -> Dict:
        """Get limiter metrics."""
        with self._lock:
            return {
                "strategy": "token_bucket",
                "tokens": self.tokens,
                "capacity": self.capacity,
                "allow_rate": self.metrics.allow_rate(),
                "rejection_rate": self.metrics.rejection_rate(),
            }


class SlidingWindowLimiter:
    """Sliding window rate limiter."""
    
    def __init__(self, max_requests: int, window_seconds: float):
        """Initialize sliding window.
        
        Args:
            max_requests: Max requests per window
            window_seconds: Window duration in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: list = []  # List of (timestamp, request_id)
        self.metrics = RateLimitMetrics(last_reset_at=time.time())
        self._lock = threading.Lock()
        self._request_counter = 0
    
    def _cleanup_old_requests(self, now: float) -> None:
        """Remove requests outside window."""
        cutoff = now - self.window_seconds
        self.requests = [
            (ts, req_id) for ts, req_id in self.requests
            if ts > cutoff
        ]
    
    def allow_request(self) -> bool:
        """Check if request allowed.
        
        Returns:
            True if request allowed
        """
        with self._lock:
            now = time.time()
            self._cleanup_old_requests(now)
            
            self.metrics.total_requests += 1
            
            if len(self.requests) < self.max_requests:
                self._request_counter += 1
                self.requests.append((now, self._request_counter))
                self.metrics.allowed_requests += 1
                return True
            else:
                self.metrics.rejected_requests += 1
                return False
    
    def get_metrics(self) -> Dict:
        """Get limiter metrics."""
        with self._lock:
            return {
                "strategy": "sliding_window",
                "current_requests": len(self.requests),
                "max_requests": self.max_requests,
                "window_seconds": self.window_seconds,
                "allow_rate": self.metrics.allow_rate(),
                "rejection_rate": self.metrics.rejection_rate(),
            }


class AdaptiveThrottler:
    """Adaptive throttler based on load."""
    
    def __init__(self, base_requests_per_sec: float, max_queueing: int = 100):
        """Initialize adaptive throttler.
        
        Args:
            base_requests_per_sec: Base request rate
            max_queueing: Max requests waiting
        """
        self.base_rate = base_requests_per_sec
        self.max_queueing = max_queueing
        self.current_rate = base_requests_per_sec
        self.queued_requests = 0
        self.metrics = RateLimitMetrics(last_reset_at=time.time())
        self._lock = threading.Lock()
    
    def update_load(self, current_load: float) -> None:
        """Update throttling based on load.
        
        Args:
            current_load: Load percentage 0.0-1.0
        """
        with self._lock:
            # Increase rate if load low, decrease if high
            if current_load < 0.3:
                self.current_rate = min(
                    self.base_rate * 1.5,
                    self.current_rate * 1.1
                )
            elif current_load > 0.8:
                self.current_rate = max(
                    self.base_rate * 0.5,
                    self.current_rate * 0.9
                )
    
    def allow_request(self) -> Tuple[bool, float]:
        """Check if request allowed and get wait time.
        
        Returns:
            (allowed, wait_time_seconds)
        """
        with self._lock:
            self.metrics.total_requests += 1
            
            if self.queued_requests < self.max_queueing:
                self.queued_requests += 1
                self.metrics.allowed_requests += 1
                
                # Estimate wait time
                wait_time = self.queued_requests / self.current_rate
                return True, wait_time
            else:
                self.metrics.rejected_requests += 1
                return False, 0.0
    
    def complete_request(self) -> None:
        """Mark request as completed."""
        with self._lock:
            self.queued_requests = max(0, self.queued_requests - 1)


class RateLimitManager:
    """Manages multiple rate limiters per client."""
    
    def __init__(self):
        """Initialize rate limit manager."""
        self.limiters: Dict[str, TokenBucketLimiter] = {}
        self.metrics: Dict[str, RateLimitMetrics] = {}
        self._lock = threading.Lock()
    
    def get_or_create_limiter(self, client_id: str,
                              capacity: float = 100.0,
                              refill_rate: float = 10.0) -> TokenBucketLimiter:
        """Get or create limiter for client.
        
        Args:
            client_id: Unique client identifier
            capacity: Token bucket capacity
            refill_rate: Refill rate in tokens/sec
            
        Returns:
            TokenBucketLimiter for client
        """
        with self._lock:
            if client_id not in self.limiters:
                self.limiters[client_id] = TokenBucketLimiter(capacity, refill_rate)
                self.metrics[client_id] = RateLimitMetrics()
            
            return self.limiters[client_id]
    
    def allow_request(self, client_id: str) -> bool:
        """Check if client request allowed.
        
        Args:
            client_id: Client identifier
            
        Returns:
            True if allowed
        """
        limiter = self.get_or_create_limiter(client_id)
        allowed = limiter.allow_request()
        
        with self._lock:
            self.metrics[client_id].total_requests += 1
            if allowed:
                self.metrics[client_id].allowed_requests += 1
            else:
                self.metrics[client_id].rejected_requests += 1
        
        return allowed
    
    def get_client_metrics(self, client_id: str) -> Dict:
        """Get metrics for client.
        
        Args:
            client_id: Client identifier
            
        Returns:
            Metrics dictionary
        """
        with self._lock:
            if client_id in self.metrics:
                return {
                    "client_id": client_id,
                    "total_requests": self.metrics[client_id].total_requests,
                    "allowed": self.metrics[client_id].allowed_requests,
                    "rejected": self.metrics[client_id].rejected_requests,
                    "allow_rate": self.metrics[client_id].allow_rate(),
                }
            return None


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestTokenBucketLimiter:
    """Test token bucket rate limiter."""
    
    def test_basic_allow(self):
        """Test basic request allow."""
        limiter = TokenBucketLimiter(capacity=10.0, refill_rate=1.0)
        
        assert limiter.allow_request()
        assert limiter.tokens == 9.0
    
    def test_capacity_limit(self):
        """Test that tokens capped at capacity."""
        limiter = TokenBucketLimiter(capacity=10.0, refill_rate=1.0)
        limiter.tokens = 10.0
        
        time.sleep(0.2)
        limiter._refill()
        
        # Should not exceed capacity
        assert limiter.tokens <= 10.0
    
    def test_refill_over_time(self):
        """Test tokens refill over time."""
        limiter = TokenBucketLimiter(capacity=10.0, refill_rate=10.0)
        limiter.tokens = 0.0
        
        time.sleep(0.1)
        limiter._refill()
        
        # Should have gained ~1 token
        assert limiter.tokens >= 0.8
    
    def test_exhaustion_and_recovery(self):
        """Test limit exhaustion and recovery."""
        limiter = TokenBucketLimiter(capacity=3.0, refill_rate=10.0)
        
        # Use all tokens
        assert limiter.allow_request()
        assert limiter.allow_request()
        assert limiter.allow_request()
        assert not limiter.allow_request()
        
        # Wait for refill
        time.sleep(0.15)
        assert limiter.allow_request()
    
    def test_metrics_tracking(self):
        """Test metrics collection."""
        limiter = TokenBucketLimiter(capacity=5.0, refill_rate=1.0)
        
        limiter.allow_request()
        limiter.allow_request()
        limiter.allow_request()
        limiter.allow_request()
        limiter.allow_request()
        limiter.allow_request()  # Should fail
        
        metrics = limiter.get_metrics()
        assert metrics["allow_rate"] < 1.0


class TestSlidingWindowLimiter:
    """Test sliding window rate limiter."""
    
    def test_within_limit(self):
        """Test requests within limit."""
        limiter = SlidingWindowLimiter(max_requests=3, window_seconds=1.0)
        
        assert limiter.allow_request()
        assert limiter.allow_request()
        assert limiter.allow_request()
    
    def test_exceed_limit(self):
        """Test exceeding limit."""
        limiter = SlidingWindowLimiter(max_requests=2, window_seconds=1.0)
        
        assert limiter.allow_request()
        assert limiter.allow_request()
        assert not limiter.allow_request()
    
    def test_window_reset(self):
        """Test window resets after timeout."""
        limiter = SlidingWindowLimiter(max_requests=1, window_seconds=0.1)
        
        assert limiter.allow_request()
        assert not limiter.allow_request()
        
        time.sleep(0.15)
        
        # Should allow after window reset
        assert limiter.allow_request()
    
    def test_metrics(self):
        """Test sliding window metrics."""
        limiter = SlidingWindowLimiter(max_requests=2, window_seconds=1.0)
        
        limiter.allow_request()
        limiter.allow_request()
        limiter.allow_request()  # Fails
        
        metrics = limiter.get_metrics()
        assert metrics["current_requests"] == 2
        assert metrics["rejection_rate"] > 0.0


class TestAdaptiveThrottler:
    """Test adaptive throttling."""
    
    def test_initial_rate(self):
        """Test initial throttler rate."""
        throttler = AdaptiveThrottler(base_requests_per_sec=10.0)
        
        assert throttler.current_rate == 10.0
    
    def test_allow_request(self):
        """Test allowing requests."""
        throttler = AdaptiveThrottler(base_requests_per_sec=100.0)
        
        allowed, wait_time = throttler.allow_request()
        
        assert allowed
        assert wait_time >= 0.0
    
    def test_queue_limit(self):
        """Test max queueing limit."""
        throttler = AdaptiveThrottler(
            base_requests_per_sec=10.0,
            max_queueing=2
        )
        
        assert throttler.allow_request()[0]
        assert throttler.allow_request()[0]
        assert not throttler.allow_request()[0]
    
    def test_adaptive_decrease(self):
        """Test rate decrease under high load."""
        throttler = AdaptiveThrottler(base_requests_per_sec=10.0)
        
        initial_rate = throttler.current_rate
        throttler.update_load(0.9)  # High load
        
        assert throttler.current_rate < initial_rate
    
    def test_adaptive_increase(self):
        """Test rate increase under low load."""
        throttler = AdaptiveThrottler(base_requests_per_sec=10.0)
        
        initial_rate = throttler.current_rate
        throttler.update_load(0.2)  # Low load
        
        assert throttler.current_rate > initial_rate


class TestRateLimitManager:
    """Test rate limit manager."""
    
    def test_create_limiter_for_client(self):
        """Test creating limiter for new client."""
        manager = RateLimitManager()
        
        limiter = manager.get_or_create_limiter("client1")
        
        assert limiter is not None
    
    def test_reuse_limiter(self):
        """Test reusing limiter for same client."""
        manager = RateLimitManager()
        
        limiter1 = manager.get_or_create_limiter("client1")
        limiter2 = manager.get_or_create_limiter("client1")
        
        assert limiter1 is limiter2
    
    def test_per_client_limits(self):
        """Test per-client rate limiting."""
        manager = RateLimitManager()
        
        # Fill client1
        for _ in range(100):
            manager.allow_request("client1")
        
        # client2 should still be allowed
        assert manager.allow_request("client2")
    
    def test_client_metrics(self):
        """Test client metrics tracking."""
        manager = RateLimitManager()
        
        manager.allow_request("client1")
        manager.allow_request("client1")
        
        metrics = manager.get_client_metrics("client1")
        
        assert metrics is not None
        assert metrics["total_requests"] == 2
        assert metrics["allowed"] == 2
