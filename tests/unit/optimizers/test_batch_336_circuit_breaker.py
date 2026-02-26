"""
Batch 336: Circuit Breaker Pattern
===================================

Implements circuit breaker pattern for graceful fault handling,
preventing cascading failures and enabling automatic recovery.

Goal: Provide:
- Circuit breaker with open/closed/half-open states
- Configurable failure thresholds and timeouts
- Automatic state transitions
- Metrics and monitoring
- Event callbacks for state changes
"""

import pytest
import time
from typing import Callable, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
import threading


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"           # Normal operation
    OPEN = "open"               # Failing, reject requests
    HALF_OPEN = "half_open"     # Testing recovery


@dataclass
class CircuitBreakerMetrics:
    """Metrics for circuit breaker."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    state_changes: int = 0
    
    def success_rate(self) -> float:
        """Get success rate."""
        if self.total_calls == 0:
            return 0.0
        return self.successful_calls / self.total_calls
    
    def failure_rate(self) -> float:
        """Get failure rate."""
        if self.total_calls == 0:
            return 0.0
        return self.failed_calls / self.total_calls


class CircuitBreaker:
    """Circuit breaker for fault tolerance."""
    
    def __init__(self, failure_threshold: int = 5,
                 success_threshold: int = 2,
                 timeout_seconds: float = 60.0,
                 on_state_change: Optional[Callable] = None):
        """Initialize circuit breaker.
        
        Args:
            failure_threshold: Failures before opening
            success_threshold: Successes to close from half-open
            timeout_seconds: Time before trying recovery
            on_state_change: Callback on state changes
        """
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout_seconds = timeout_seconds
        self.on_state_change = on_state_change
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.last_state_change_time = time.time()
        self.metrics = CircuitBreakerMetrics()
        
        self._lock = threading.Lock()
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function through circuit breaker.
        
        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If circuit open or function fails
        """
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                    self._notify_state_change()
                else:
                    self.metrics.rejected_calls += 1
                    raise Exception(f"Circuit breaker is OPEN")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        """Check if should attempt recovery."""
        if self.last_failure_time is None:
            return False
        
        elapsed = time.time() - self.last_failure_time
        return elapsed > self.timeout_seconds
    
    def _on_success(self) -> None:
        """Handle successful call."""
        with self._lock:
            self.metrics.total_calls += 1
            self.metrics.successful_calls += 1
            self.failure_count = 0
            
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                
                if self.success_count >= self.success_threshold:
                    self.state = CircuitState.CLOSED
                    self._notify_state_change()
    
    def _on_failure(self) -> None:
        """Handle failed call."""
        with self._lock:
            self.metrics.total_calls += 1
            self.metrics.failed_calls += 1
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.state == CircuitState.CLOSED:
                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    self._notify_state_change()
            
            elif self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self._notify_state_change()
    
    def _notify_state_change(self) -> None:
        """Notify on state change."""
        self.metrics.state_changes += 1
        self.last_state_change_time = time.time()
        
        if self.on_state_change:
            self.on_state_change(self.state)
    
    def get_state(self) -> CircuitState:
        """Get current state."""
        with self._lock:
            return self.state
    
    def reset(self) -> None:
        """Manually reset circuit breaker."""
        with self._lock:
            old_state = self.state
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time = None
            
            if old_state != CircuitState.CLOSED:
                self._notify_state_change()


class CircuitBreakerFactory:
    """Factory for creating and managing circuit breakers."""
    
    def __init__(self):
        """Initialize factory."""
        self.breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()
    
    def get_or_create(self, name: str,
                      failure_threshold: int = 5,
                      success_threshold: int = 2,
                      timeout_seconds: float = 60.0) -> CircuitBreaker:
        """Get or create breaker.
        
        Args:
            name: Breaker name
            failure_threshold: Failure threshold
            success_threshold: Success threshold
            timeout_seconds: Timeout
            
        Returns:
            CircuitBreaker
        """
        with self._lock:
            if name not in self.breakers:
                self.breakers[name] = CircuitBreaker(
                    failure_threshold=failure_threshold,
                    success_threshold=success_threshold,
                    timeout_seconds=timeout_seconds,
                )
            
            return self.breakers[name]
    
    def get_all_metrics(self) -> Dict[str, Dict]:
        """Get metrics for all breakers.
        
        Returns:
            Dict of metrics by breaker name
        """
        with self._lock:
            return {
                name: {
                    "state": breaker.get_state().value,
                    "total_calls": breaker.metrics.total_calls,
                    "successful": breaker.metrics.successful_calls,
                    "failed": breaker.metrics.failed_calls,
                    "rejected": breaker.metrics.rejected_calls,
                    "success_rate": breaker.metrics.success_rate(),
                }
                for name, breaker in self.breakers.items()
            }


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestCircuitBreaker:
    """Test circuit breaker."""
    
    def test_closed_state_success(self):
        """Test closed state allows successes."""
        breaker = CircuitBreaker()
        
        def success_func():
            return "success"
        
        result = breaker.call(success_func)
        
        assert result == "success"
        assert breaker.get_state() == CircuitState.CLOSED
    
    def test_closed_state_failures(self):
        """Test closed state tracks failures."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        def fail_func():
            raise Exception("Error")
        
        # First 2 failures don't open
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.call(fail_func)
        
        assert breaker.get_state() == CircuitState.CLOSED
        
        # 3rd failure opens
        with pytest.raises(Exception):
            breaker.call(fail_func)
        
        assert breaker.get_state() == CircuitState.OPEN
    
    def test_open_state_rejects(self):
        """Test open state rejects requests."""
        breaker = CircuitBreaker(failure_threshold=1)
        
        def fail_func():
            raise Exception("Error")
        
        # Open the circuit
        with pytest.raises(Exception):
            breaker.call(fail_func)
        
        # Should reject subsequent calls
        with pytest.raises(Exception, match="Circuit breaker is OPEN"):
            breaker.call(lambda: "success")
        
        assert breaker.metrics.rejected_calls > 0
    
    def test_half_open_on_timeout(self):
        """Test transition to half-open after timeout."""
        breaker = CircuitBreaker(
            failure_threshold=1,
            timeout_seconds=0.1
        )
        
        # Open the circuit
        with pytest.raises(Exception):
            breaker.call(lambda: 1/0)
        
        assert breaker.get_state() == CircuitState.OPEN
        
        # Wait for timeout
        time.sleep(0.2)
        
        # Next call should transition to half-open
        def success_func():
            return "success"
        
        result = breaker.call(success_func)
        assert result == "success"
        # Should be in half-open now (but could auto-close after success)
        assert breaker.get_state() in [CircuitState.HALF_OPEN, CircuitState.CLOSED]
    
    def test_half_open_success_closes(self):
        """Test half-open transitions to closed on success."""
        breaker = CircuitBreaker(
            failure_threshold=1,
            success_threshold=1,
            timeout_seconds=0.1
        )
        
        # Open circuit
        with pytest.raises(Exception):
            breaker.call(lambda: 1/0)
        
        assert breaker.get_state() == CircuitState.OPEN
        
        # Wait and let it transition
        time.sleep(0.15)
        
        # Successful call should close
        breaker.call(lambda: "success")
        
        assert breaker.get_state() == CircuitState.CLOSED
    
    def test_half_open_failure_reopens(self):
        """Test half-open failure reopens circuit."""
        breaker = CircuitBreaker(
            failure_threshold=1,
            timeout_seconds=0.1
        )
        
        # Open circuit
        with pytest.raises(Exception):
            breaker.call(lambda: 1/0)
        
        # Wait for timeout
        time.sleep(0.15)
        
        # Fail in half-open should reopen
        with pytest.raises(Exception):
            breaker.call(lambda: 1/0)
        
        assert breaker.get_state() == CircuitState.OPEN
    
    def test_manual_reset(self):
        """Test manual reset."""
        breaker = CircuitBreaker(failure_threshold=1)
        
        # Open circuit
        with pytest.raises(Exception):
            breaker.call(lambda: 1/0)
        
        assert breaker.get_state() == CircuitState.OPEN
        
        # Manual reset
        breaker.reset()
        
        assert breaker.get_state() == CircuitState.CLOSED
    
    def test_metrics_tracking(self):
        """Test metrics collection."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        # 2 successes
        breaker.call(lambda: "ok")
        breaker.call(lambda: "ok")
        
        # 3 failures to open
        for _ in range(3):
            try:
                breaker.call(lambda: 1/0)
            except:
                pass
        
        # 1 rejection
        try:
            breaker.call(lambda: "never")
        except:
            pass
        
        metrics = breaker.metrics
        assert metrics.total_calls >= 5
        assert metrics.successful_calls >= 2
        assert metrics.failed_calls >= 3
        assert metrics.rejected_calls == 1
    
    def test_state_change_callback(self):
        """Test state change callback."""
        state_changes = []
        
        def on_change(state):
            state_changes.append(state)
        
        breaker = CircuitBreaker(
            failure_threshold=1,
            on_state_change=on_change
        )
        
        # Open circuit
        with pytest.raises(Exception):
            breaker.call(lambda: 1/0)
        
        assert CircuitState.OPEN in state_changes
    
    def test_success_rate(self):
        """Test success rate calculation."""
        breaker = CircuitBreaker()
        
        breaker.call(lambda: "ok")
        breaker.call(lambda: "ok")
        
        try:
            breaker.call(lambda: 1/0)
        except:
            pass
        
        rate = breaker.metrics.success_rate()
        assert 0.0 < rate < 1.0


class TestCircuitBreakerFactory:
    """Test circuit breaker factory."""
    
    def test_create_breaker(self):
        """Test creating breaker."""
        factory = CircuitBreakerFactory()
        
        breaker = factory.get_or_create("api")
        
        assert breaker is not None
    
    def test_reuse_breaker(self):
        """Test reusing breaker by name."""
        factory = CircuitBreakerFactory()
        
        breaker1 = factory.get_or_create("api")
        breaker2 = factory.get_or_create("api")
        
        assert breaker1 is breaker2
    
    def test_multiple_breakers(self):
        """Test managing multiple breakers."""
        factory = CircuitBreakerFactory()
        
        api_breaker = factory.get_or_create("api")
        db_breaker = factory.get_or_create("db")
        
        assert api_breaker is not db_breaker
    
    def test_get_all_metrics(self):
        """Test getting metrics for all breakers."""
        factory = CircuitBreakerFactory()
        
        breaker1 = factory.get_or_create("service1")
        breaker2 = factory.get_or_create("service2")
        
        breaker1.call(lambda: "ok")
        try:
            breaker2.call(lambda: 1/0)
        except:
            pass
        
        metrics = factory.get_all_metrics()
        
        assert "service1" in metrics
        assert "service2" in metrics
        assert metrics["service1"]["successful"] == 1
        assert metrics["service2"]["failed"] >= 1
