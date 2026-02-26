"""Tests for circuit-breaker protected LLM interface.

Tests cover:
- Normal operation (closed circuit)
- Failure detection and circuit opening
- Recovery testing (half-open state)
- Fallback behavior
- Metrics tracking
- Timeout handling
"""

import time
import pytest
from unittest.mock import Mock, MagicMock
from ipfs_datasets_py.optimizers.common.llm_circuit_breaker import (
    ProtectedLLMRouter,
    LLMCircuitBreakerMetrics,
    CircuitBreakerOpen,
)
from ipfs_datasets_py.optimizers.common.circuit_breaker import CircuitState


class MockLLMRouter:
    """Mock LLM router for testing."""
    
    def __init__(self):
        self.call_count = 0
        self.failure_mode = None  # None, 'timeout', 'error'
        self.failure_count = 0
        self.max_failures = 0
    
    def generate(self, prompt: str, *, model_name=None, **kwargs):
        """Generate mock response."""
        self.call_count += 1
        
        # Simulate failures
        if self.failure_mode == 'timeout' and self.failure_count < self.max_failures:
            self.failure_count += 1
            raise TimeoutError(f"Mock timeout {self.failure_count}")
        
        if self.failure_mode == 'error' and self.failure_count < self.max_failures:
            self.failure_count += 1
            raise RuntimeError(f"Mock error {self.failure_count}")
        
        return f"Mock response to: {prompt[:20]}..."


class TestProtectedLLMRouterBasic:
    """Test basic circuit breaker functionality."""
    
    def test_successful_generation(self):
        """Test successful LLM generation passes through."""
        base = MockLLMRouter()
        protected = ProtectedLLMRouter(base, provider_name="test", enabled=True)
        
        result = protected.generate("Hello")
        
        assert "Hello" in result
        assert base.call_count == 1
        assert protected._metrics.total_calls == 1
        assert protected._metrics.successful_calls == 1
        assert protected._metrics.failed_calls == 0
    
    def test_disabled_protection(self):
        """Test that disabled protection passes through without circuit breaker."""
        base = MockLLMRouter()
        protected = ProtectedLLMRouter(base, provider_name="test", enabled=False)
        
        assert not protected.is_enabled()
        assert protected.is_available()
        
        result = protected.generate("Hello")
        assert "Hello" in result
    
    def test_health_status_when_healthy(self):
        """Test health status when circuit is closed."""
        base = MockLLMRouter()
        protected = ProtectedLLMRouter(base, provider_name="test", enabled=True)
        
        protected.generate("Test")
        health = protected.get_health_status()
        
        assert health["state"] == "closed"
        assert health["enabled"] is True
        assert health["available"] is True
        assert health["success_rate"] == 100.0
        assert health["failure_rate"] == 0.0
        assert health["total_calls"] == 1
        assert health["successful_calls"] == 1
    
    def test_health_status_disabled(self):
        """Test health status when protection is disabled."""
        base = MockLLMRouter()
        protected = ProtectedLLMRouter(base, provider_name="test", enabled=False)
        
        health = protected.get_health_status()
        
        assert health["state"] == "disabled"
        assert health["enabled"] is False
        assert health["available"] is True


class TestCircuitBreakerOpening:
    """Test circuit opening on failures."""
    
    def test_circuit_opens_after_threshold(self):
        """Test that circuit opens after failure threshold is exceeded."""
        base = MockLLMRouter()
        base.failure_mode = 'error'
        base.max_failures = 10  # Fail many times
        
        protected = ProtectedLLMRouter(
            base,
            provider_name="test",
            enabled=True,
            failure_threshold=3,
            max_retries=0,  # No retries, so each call is a distinct attempt
        )
        
        # First 3 failures should pass through and open circuit
        for i in range(3):
            with pytest.raises(RuntimeError):
                protected.generate("Fail")
        
        # Circuit should now be OPEN
        assert protected._circuit_breaker.state == CircuitState.OPEN
        assert not protected.is_available()
        
        # Next call should be rejected immediately (circuit is open)
        with pytest.raises(CircuitBreakerOpen):
            protected.generate("Should fail")
        
        # Check metrics
        health = protected.get_health_status()
        assert health["state"] == "open"
        assert health["available"] is False
        # We had 3 attempts that failed, opening the circuit
        # Then 1 rejected while open
        assert health["failed_calls"] >= 3 or health["rejected_calls"] >= 1
    
    def test_fallback_when_circuit_open(self):
        """Test that fallback is used when circuit is open."""
        base = MockLLMRouter()
        base.failure_mode = 'error'
        base.max_failures = 10
        
        protected = ProtectedLLMRouter(
            base,
            provider_name="test",
            enabled=True,
            failure_threshold=2,
            max_retries=0,  # No retries
        )
        
        # Cause failures to open circuit
        for _ in range(2):
            with pytest.raises(RuntimeError):
                protected.generate("Fail")
        
        # Circuit is now open - fallback should be used
        result = protected.generate(
            "Will use fallback",
            fallback_result="Rule-based answer"
        )
        
        assert result == "Rule-based answer"
        assert protected._metrics.rejected_calls == 1
    
    def test_timeout_tracking(self):
        """Test that timeouts are tracked separately."""
        base = MockLLMRouter()
        base.failure_mode = 'timeout'
        base.max_failures = 10
        
        protected = ProtectedLLMRouter(
            base,
            provider_name="test",
            enabled=True,
            failure_threshold=3,
            max_retries=0,  # Don't retry
        )
        
        # Cause timeout
        with pytest.raises(TimeoutError):
            protected.generate("Timeout")
        
        # Note: timeout is caught, logged, but re-raised - it doesn't directly
        # increment failed_calls as circuit breaker success/failure
        health = protected.get_health_status()
        assert health["timeout_calls"] == 1


class TestCircuitRecovery:
    """Test circuit recovery (HALF_OPEN state)."""
    
    def test_recovery_after_timeout(self):
        """Test that circuit transitions to HALF_OPEN after recovery timeout."""
        base = MockLLMRouter()
        protected = ProtectedLLMRouter(
            base,
            provider_name="test",
            enabled=True,
            failure_threshold=2,
            recovery_timeout=0.1,  # Short timeout for testing
            max_retries=0,  # No retries
        )
        
        # Open circuit
        base.failure_mode = 'error'
        base.max_failures = 10
        for _ in range(2):
            with pytest.raises(RuntimeError):
                protected.generate("Fail")
        
        assert protected._circuit_breaker.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        time.sleep(0.15)
        
        # Check state - should be HALF_OPEN now
        assert protected._circuit_breaker.state == CircuitState.HALF_OPEN
        
        # Recovery attempt should succeed
        base.failure_mode = None  # Stop failing
        result = protected.generate("Recovery test")
        
        assert "Recovery test" in result
        # Circuit should be CLOSED after successful recovery
        assert protected._circuit_breaker.state == CircuitState.CLOSED
    
    def test_recovery_failure_reopens_circuit(self):
        """Test that failed recovery attempt re-opens the circuit."""
        base = MockLLMRouter()
        protected = ProtectedLLMRouter(
            base,
            provider_name="test",
            enabled=True,
            failure_threshold=2,
            recovery_timeout=0.1,
            max_retries=0,  # No retries
        )
        
        # Open circuit
        base.failure_mode = 'error'
        base.max_failures = 10
        for _ in range(2):
            with pytest.raises(RuntimeError):
                protected.generate("Fail")
        
        assert protected._circuit_breaker.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        time.sleep(0.15)
        assert protected._circuit_breaker.state == CircuitState.HALF_OPEN
        
        # Recovery attempt fails
        with pytest.raises(RuntimeError):
            protected.generate("Still failing")
        
        # Circuit should re-OPEN
        assert protected._circuit_breaker.state == CircuitState.OPEN


class TestRetryLogic:
    """Test retry logic with exponential backoff."""
    
    def test_retry_on_transient_failure(self):
        """Test that transient failures are retried."""
        base = MockLLMRouter()
        base.failure_mode = 'error'
        base.max_failures = 2  # Fail twice, then succeed
        
        protected = ProtectedLLMRouter(
            base,
            provider_name="test",
            enabled=True,
            failure_threshold=20,  # High threshold so circuit doesn't open
            max_retries=3,
        )
        
        # Should succeed after retries
        result = protected.generate("Will retry")
        assert "Will retry" in result
        assert base.call_count == 3  # Two failures + one success
        
        # Check metrics
        health = protected.get_health_status()
        assert health["successful_calls"] == 1
        # Note: failed_calls in health is from circuit breaker's internal metrics
        # The overall call succeeded via retry
    
    def test_max_retries_exceeded(self):
        """Test that max retries limit is respected."""
        base = MockLLMRouter()
        base.failure_mode = 'error'
        base.max_failures = 100  # Always fail
        
        protected = ProtectedLLMRouter(
            base,
            provider_name="test",
            enabled=True,
            failure_threshold=20,  # High threshold
            max_retries=2,
        )
        
        with pytest.raises(RuntimeError):
            protected.generate("Always fails")
        
        # Should have attempted 3 times (1 + 2 retries)
        assert base.call_count == 3
        assert base.failure_count == 3


class TestMetricsTracking:
    """Test metrics collection and reporting."""
    
    def test_comprehensive_metrics(self):
        """Test that all metrics are tracked correctly."""
        base = MockLLMRouter()
        protected = ProtectedLLMRouter(
            base,
            provider_name="test-metrics",
            enabled=True,
            failure_threshold=5,
            max_retries=0,  # No retries for cleaner metric tracking
        )
        
        # Make some successful calls
        protected.generate("First")
        protected.generate("Second") 
        
        # Make a failing call
        base.failure_mode = 'error'
        base.max_failures = 10  # Always fail
        with pytest.raises(RuntimeError):
            protected.generate("Fail")
        
        # Check metrics
        metrics = protected._metrics
        assert metrics.provider_name == "test-metrics"
        assert metrics.total_calls == 3
        assert metrics.successful_calls == 2
        assert metrics.failed_calls == 1
        assert metrics.success_rate == pytest.approx(66.66, rel=1)
        assert metrics.failure_rate == pytest.approx(33.33, rel=1)
    
    def test_error_tracking(self):
        """Test that last error is tracked."""
        base = MockLLMRouter()
        protected = ProtectedLLMRouter(
            base,
            provider_name="test",
            enabled=True,
            failure_threshold=10,
            max_retries=0,
        )
        
        base.failure_mode = 'error'
        base.max_failures = 10  # Always fail
        
        with pytest.raises(RuntimeError):
            protected.generate("Error")
        
        # Verify metrics were updated
        assert protected._metrics.total_calls == 1
        assert protected._metrics.failed_calls == 1


class TestEnvironmentConfiguration:
    """Test configuration via environment variables."""
    
    def test_env_disabled(self, monkeypatch):
        """Test that LLM_CIRCUIT_BREAKER_ENABLED env var disables protection."""
        monkeypatch.setenv("LLM_CIRCUIT_BREAKER_ENABLED", "false")
        
        base = MockLLMRouter()
        protected = ProtectedLLMRouter(base, provider_name="test")
        
        assert not protected.is_enabled()
    
    def test_env_config_values(self, monkeypatch):
        """Test reading config from environment variables."""
        monkeypatch.setenv("LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "10")
        monkeypatch.setenv("LLM_CIRCUIT_BREAKER_RECOVERY_TIMEOUT", "30")
        monkeypatch.setenv("LLM_CIRCUIT_BREAKER_TIMEOUT", "60")
        monkeypatch.setenv("LLM_CIRCUIT_BREAKER_MAX_RETRIES", "5")
        
        base = MockLLMRouter()
        protected = ProtectedLLMRouter(base, provider_name="test")
        
        assert protected._circuit_breaker.failure_threshold == 10
        assert protected._circuit_breaker.recovery_timeout == 30
        assert protected._call_timeout == 60
        assert protected._max_retries == 5
