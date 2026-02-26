"""
Batch 337: Exponential Backoff & Retry with Jitter
====================================================

Implements resilient retry strategies with exponential backoff
and jitter to prevent thundering herd and improve success rates.

Goal: Provide:
- Configurable retry policies
- Exponential backoff with jitter
- Max retry limits and timeouts
- Retry metrics and statistics
- Decorators for easy integration
"""

import pytest
import time
import random
from typing import Callable, Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class BackoffStrategy(Enum):
    """Backoff calculation strategies."""
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    FIBONACCI = "fibonacci"


@dataclass
class RetryMetrics:
    """Metrics for retry attempts."""
    total_attempts: int = 0
    successful_attempts: int = 0
    failed_attempts: int = 0
    total_retries: int = 0
    total_backoff_time: float = 0.0
    
    def success_rate(self) -> float:
        """Get success rate."""
        if self.total_attempts == 0:
            return 0.0
        return self.successful_attempts / self.total_attempts
    
    def avg_retries_per_call(self) -> float:
        """Get average retries per call."""
        if self.total_attempts == 0:
            return 0.0
        return self.total_retries / self.total_attempts


# ============================================================================
# RETRY STRATEGIES
# ============================================================================

class RetryPolicy:
    """Configurable retry policy."""
    
    def __init__(self, max_retries: int = 3,
                 initial_delay: float = 1.0,
                 max_delay: float = 60.0,
                 strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL,
                 jitter: bool = True):
        """Initialize retry policy.
        
        Args:
            max_retries: Maximum retry attempts
            initial_delay: Initial delay in seconds
            max_delay: Maximum delay between retries
            strategy: Backoff strategy
            jitter: Add randomness to delays
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.strategy = strategy
        self.jitter = jitter
        self.metrics = RetryMetrics()
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for attempt.
        
        Args:
            attempt: Attempt number (0-indexed)
            
        Returns:
            Delay in seconds
        """
        if self.strategy == BackoffStrategy.LINEAR:
            delay = self.initial_delay * (attempt + 1)
        elif self.strategy == BackoffStrategy.EXPONENTIAL:
            delay = self.initial_delay * (2 ** attempt)
        elif self.strategy == BackoffStrategy.FIBONACCI:
            delay = self.initial_delay * self._fibonacci(attempt + 1)
        else:
            delay = self.initial_delay
        
        # Cap at max delay
        delay = min(delay, self.max_delay)
        
        # Add jitter
        if self.jitter:
            jitter_amount = delay * random.uniform(0, 0.1)
            delay += jitter_amount
        
        return delay
    
    def _fibonacci(self, n: int) -> int:
        """Calculate fibonacci number."""
        if n <= 1:
            return 1
        
        a, b = 1, 1
        for _ in range(n - 1):
            a, b = b, a + b
        return b
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with retries.
        
        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If all retries exhausted
        """
        self.metrics.total_attempts += 1
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                result = func(*args, **kwargs)
                self.metrics.successful_attempts += 1
                return result
            except Exception as e:
                last_exception = e
                
                if attempt < self.max_retries:
                    delay = self.get_delay(attempt)
                    self.metrics.total_retries += 1
                    self.metrics.total_backoff_time += delay
                    time.sleep(delay)
        
        self.metrics.failed_attempts += 1
        raise last_exception


# ============================================================================
# DECORATORS
# ============================================================================

def retry(max_retries: int = 3,
          initial_delay: float = 1.0,
          strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL):
    """Decorator for retry with backoff.
    
    Args:
        max_retries: Max retry attempts
        initial_delay: Initial delay
        strategy: Backoff strategy
        
    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        policy = RetryPolicy(
            max_retries=max_retries,
            initial_delay=initial_delay,
            strategy=strategy
        )
        
        def wrapper(*args, **kwargs):
            return policy.call(func, *args, **kwargs)
        
        wrapper._retry_policy = policy
        return wrapper
    
    return decorator


# ============================================================================
# ADVANCED STRATEGIES
# ============================================================================

class AdaptiveRetryPolicy(RetryPolicy):
    """Retry policy that adapts based on failure patterns."""
    
    def __init__(self, *args, **kwargs):
        """Initialize adaptive retry policy."""
        super().__init__(*args, **kwargs)
        self.failure_reasons: Dict[str, int] = {}
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute with adaptive retry."""
        self.metrics.total_attempts += 1
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                result = func(*args, **kwargs)
                self.metrics.successful_attempts += 1
                return result
            except Exception as e:
                last_exception = e
                
                # Track failure reason
                reason = str(e)[:50]
                self.failure_reasons[reason] = self.failure_reasons.get(reason, 0) + 1
                
                if attempt < self.max_retries:
                    # Adapt delay based on failure frequency
                    frequency = self.failure_reasons[reason]
                    if frequency > 3:
                        # If same error frequently, increase delay
                        delay = self.get_delay(attempt) * 2
                    else:
                        delay = self.get_delay(attempt)
                    
                    self.metrics.total_retries += 1
                    self.metrics.total_backoff_time += delay
                    time.sleep(delay)
        
        self.metrics.failed_attempts += 1
        raise last_exception


class BudgetedRetryPolicy(RetryPolicy):
    """Retry policy with total time budget."""
    
    def __init__(self, *args, max_total_time: float = 30.0, **kwargs):
        """Initialize budgeted policy.
        
        Args:
            max_total_time: Max total time for all retries
        """
        super().__init__(*args, **kwargs)
        self.max_total_time = max_total_time
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute with time budget."""
        self.metrics.total_attempts += 1
        start_time = time.time()
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                result = func(*args, **kwargs)
                self.metrics.successful_attempts += 1
                return result
            except Exception as e:
                last_exception = e
                
                if attempt < self.max_retries:
                    elapsed = time.time() - start_time
                    remaining = self.max_total_time - elapsed
                    
                    if remaining <= 0:
                        break
                    
                    delay = self.get_delay(attempt)
                    delay = min(delay, remaining)
                    
                    self.metrics.total_retries += 1
                    self.metrics.total_backoff_time += delay
                    time.sleep(delay)
        
        self.metrics.failed_attempts += 1
        raise last_exception


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestRetryPolicy:
    """Test basic retry policy."""
    
    def test_successful_first_attempt(self):
        """Test successful call needs no retries."""
        policy = RetryPolicy()
        
        result = policy.call(lambda: "success")
        
        assert result == "success"
        assert policy.metrics.total_attempts == 1
        assert policy.metrics.total_retries == 0
    
    def test_eventual_success(self):
        """Test eventual success after failures."""
        policy = RetryPolicy(max_retries=3, initial_delay=0.01)
        
        call_count = 0
        
        def sometimes_fail():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Not yet")
            return "success"
        
        result = policy.call(sometimes_fail)
        
        assert result == "success"
        assert call_count == 3
        assert policy.metrics.total_retries == 2
    
    def test_max_retries_exceeded(self):
        """Test failure after max retries."""
        policy = RetryPolicy(max_retries=2, initial_delay=0.01)
        
        with pytest.raises(Exception):
            policy.call(lambda: 1/0)
        
        assert policy.metrics.total_attempts == 1
        assert policy.metrics.failed_attempts == 1
    
    def test_linear_backoff(self):
        """Test linear backoff strategy."""
        policy = RetryPolicy(
            max_retries=2,
            initial_delay=0.1,
            strategy=BackoffStrategy.LINEAR,
            jitter=False
        )
        
        delays = []
        for attempt in range(2):
            delay = policy.get_delay(attempt)
            delays.append(delay)
        
        # Linear should be 0.1, 0.2
        assert delays[0] < delays[1]
    
    def test_exponential_backoff(self):
        """Test exponential backoff strategy."""
        policy = RetryPolicy(
            max_retries=3,
            initial_delay=1.0,
            strategy=BackoffStrategy.EXPONENTIAL,
            jitter=False
        )
        
        delays = []
        for attempt in range(3):
            delay = policy.get_delay(attempt)
            delays.append(delay)
        
        # Exponential: 1, 2, 4
        assert delays[0] < delays[1] < delays[2]
        assert abs(delays[1] - 2.0) < 0.01
    
    def test_fibonacci_backoff(self):
        """Test fibonacci backoff strategy."""
        policy = RetryPolicy(
            max_retries=3,
            initial_delay=1.0,
            strategy=BackoffStrategy.FIBONACCI,
            jitter=False
        )
        
        first = policy.get_delay(0)
        second = policy.get_delay(1)
        third = policy.get_delay(2)
        
        # Fibonacci sequence: 1, 1, 2, 3
        assert first <= second < third
    
    def test_max_delay_cap(self):
        """Test that delays are capped."""
        policy = RetryPolicy(
            max_retries=5,
            initial_delay=1.0,
            max_delay=2.0,
            strategy=BackoffStrategy.EXPONENTIAL,
            jitter=False
        )
        
        delay = policy.get_delay(10)
        
        assert delay <= 2.0
    
    def test_jitter_randomness(self):
        """Test that jitter adds randomness."""
        policy = RetryPolicy(
            max_retries=3,
            initial_delay=1.0,
            strategy=BackoffStrategy.EXPONENTIAL,
            jitter=True
        )
        
        delays = [policy.get_delay(1) for _ in range(10)]
        
        # Should have variance
        assert len(set(delays)) > 1
    
    def test_metrics_collection(self):
        """Test metrics tracking."""
        policy = RetryPolicy(max_retries=2, initial_delay=0.01)
        
        call_count = 0
        
        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Fail")
            return "ok"
        
        policy.call(fail_twice)
        
        assert policy.metrics.total_attempts == 1
        assert policy.metrics.successful_attempts == 1
        assert policy.metrics.total_retries == 2


class TestRetryDecorator:
    """Test retry decorator."""
    
    def test_decorator_success(self):
        """Test decorator on success."""
        @retry(max_retries=2, initial_delay=0.01)
        def func():
            return "ok"
        
        result = func()
        
        assert result == "ok"
    
    def test_decorator_with_retries(self):
        """Test decorator retries on failure."""
        call_count = 0
        
        @retry(max_retries=3, initial_delay=0.01)
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Fail")
            return "success"
        
        result = func()
        
        assert result == "success"
        assert call_count == 3


class TestAdaptiveRetry:
    """Test adaptive retry policy."""
    
    def test_adaptive_tracking(self):
        """Test tracking of failure reasons."""
        policy = AdaptiveRetryPolicy(max_retries=2, initial_delay=0.01)
        
        call_count = 0
        
        def fail_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Network error")
            return "ok"
        
        policy.call(fail_once)
        
        assert "Network error" in policy.failure_reasons


class TestBudgetedRetry:
    """Test budgeted retry policy."""
    
    def test_respects_time_budget(self):
        """Test that policy respects time budget."""
        policy = BudgetedRetryPolicy(
            max_retries=10,
            initial_delay=1.0,
            max_total_time=0.1,
            jitter=False
        )
        
        start = time.time()
        
        with pytest.raises(Exception):
            policy.call(lambda: 1/0)
        
        elapsed = time.time() - start
        
        # Should stop early due to budget
        assert elapsed < 0.5
