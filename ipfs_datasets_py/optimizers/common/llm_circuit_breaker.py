"""Circuit-breaker protected LLM interface for safety and resilience.

This module provides a production-grade wrapper around LLM providers that:
- Applies circuit-breaker pattern to detect and respond to LLM failures
- Tracks success/failure metrics for monitoring
- Gracefully degrades when LLM service is unavailable
- Provides timeouts to prevent hanging requests
- Logs all LLM interactions with structured format

Features:
- Per-provider circuit breakers (different failure thresholds per provider)
- Fallback to rule-based extraction when LLM fails
- Detailed metrics and health status
- Feature-flagged enabling/disabling
- Configurable failure thresholds and recovery timeouts

Environment variables:
- LLM_CIRCUIT_BREAKER_ENABLED: Enable circuit breaker (default: true)
- LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD: Number of failures before opening (default: 5)
- LLM_CIRCUIT_BREAKER_RECOVERY_TIMEOUT: Recovery test delay in seconds (default: 60)
- LLM_CIRCUIT_BREAKER_TIMEOUT: LLM call timeout in seconds (default: 120)
- LLM_CIRCUIT_BREAKER_MAX_RETRIES: Retry attempts on transient failures (default: 2)

Example:
    from ipfs_datasets_py.optimizers.common.llm_circuit_breaker import ProtectedLLMRouter
    
    # Create protected router (wraps existing LLMRouter)
    from ipfs_datasets_py.llm_router import get_default_router
    base_router = get_default_router()
    protected = ProtectedLLMRouter(base_router)
    
    # Use like normal - circuit breaker is transparent
    try:
        result = protected.generate("Some prompt")
    except CircuitBreakerOpen as e:
        # LLM temporarily unavailable
        result = rule_based_fallback()
    
    # Check health
    health = protected.get_health_status()
    print(f"LLM status: {health['state']}, success_rate: {health['success_rate']}%")
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from functools import wraps

from .circuit_breaker import CircuitBreaker, CircuitBreakerOpen, CircuitState

_logger = logging.getLogger(__name__)


class LLMProviderProtocol(Protocol):
    """Protocol for LLM provider backends."""
    
    def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
        """Generate text from prompt.
        
        Args:
            prompt: Input prompt text
            model_name: Optional model override
            **kwargs: Provider-specific options (temperature, max_tokens, etc.)
            
        Returns:
            Generated text
            
        Raises:
            Exception: Various exceptions depending on provider
        """
        ...


@dataclass
class LLMCircuitBreakerMetrics:
    """Metrics for a circuit-breaker protected LLM provider."""
    provider_name: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0  # Rejected while circuit OPEN
    timeout_calls: int = 0
    retried_calls: int = 0
    state_changes: int = 0
    last_error: Optional[str] = None
    last_error_time: Optional[float] = None
    
    @property
    def success_rate(self) -> float:
        """Success rate as percentage."""
        if self.total_calls == 0:
            return 0.0
        return 100.0 * self.successful_calls / self.total_calls
    
    @property
    def failure_rate(self) -> float:
        """Failure rate as percentage."""
        if self.total_calls == 0:
            return 0.0
        return 100.0 * self.failed_calls / self.total_calls
    
    @property
    def rejection_rate(self) -> float:
        """Rejection rate as percentage (rejected while circuit open)."""
        if self.total_calls == 0:
            return 0.0
        return 100.0 * self.rejected_calls / self.total_calls


class ProtectedLLMRouter:
    """Wraps any LLM provider with circuit-breaker protection and monitoring.
    
    This class acts as a transparent proxy that adds:
    - Circuit-breaker failure detection
    - Automatic retry with exponential backoff
    - Request timeout protection
    - Structured logging of all interactions
    - Health monitoring and metrics
    
    Attributes:
        _base_router: Underlying LLM provider
        _circuit_breaker: Circuit-breaker instance
        _metrics: Health metrics tracking
        _enabled: Whether protection is enabled
    """
    
    def __init__(
        self,
        base_router: Any,  # Would be LLMRouter type but avoid circular import
        provider_name: str = "default",
        enabled: Optional[bool] = None,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        call_timeout: float = 120.0,
        max_retries: int = 2,
    ):
        """Initialize protected LLM router.
        
        Args:
            base_router: Base LLM router to wrap
            provider_name: Name for this provider (for logging/metrics)
            enabled: Explicitly enable/disable circuit breaker. If None, check LLM_CIRCUIT_BREAKER_ENABLED env.
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Time to wait before testing recovery
            call_timeout: Timeout for individual LLM calls
            max_retries: Max retry attempts for transient failures
        """
        import os
        
        self._base_router = base_router
        self._provider_name = provider_name
        self._call_timeout = call_timeout
        self._max_retries = max_retries
        
        # Check environment variable
        env_enabled = os.environ.get("LLM_CIRCUIT_BREAKER_ENABLED", "true").lower()
        if enabled is None:
            self._enabled = env_enabled not in ("0", "false", "no", "off")
        else:
            self._enabled = enabled
        
        # Read config from environment
        env_threshold = os.environ.get("LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD")
        if env_threshold:
            try:
                failure_threshold = int(env_threshold)
            except ValueError:
                _logger.warning(f"Invalid LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD: {env_threshold}, using default")
        
        env_timeout = os.environ.get("LLM_CIRCUIT_BREAKER_RECOVERY_TIMEOUT")
        if env_timeout:
            try:
                recovery_timeout = float(env_timeout)
            except ValueError:
                _logger.warning(f"Invalid LLM_CIRCUIT_BREAKER_RECOVERY_TIMEOUT: {env_timeout}, using default")
        
        env_call_timeout = os.environ.get("LLM_CIRCUIT_BREAKER_TIMEOUT")
        if env_call_timeout:
            try:
                self._call_timeout = float(env_call_timeout)
            except ValueError:
                _logger.warning(f"Invalid LLM_CIRCUIT_BREAKER_TIMEOUT: {env_call_timeout}, using default")
        
        env_max_retries = os.environ.get("LLM_CIRCUIT_BREAKER_MAX_RETRIES")
        if env_max_retries:
            try:
                self._max_retries = int(env_max_retries)
            except ValueError:
                _logger.warning(f"Invalid LLM_CIRCUIT_BREAKER_MAX_RETRIES: {env_max_retries}, using default")
        
        # Create circuit breaker
        self._circuit_breaker = CircuitBreaker(
            name=f"llm_{provider_name}",
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            expected_exception=Exception,
        ) if self._enabled else None
        
        self._metrics = LLMCircuitBreakerMetrics(provider_name=provider_name)
    
    def is_enabled(self) -> bool:
        """Check if circuit breaker protection is enabled."""
        return self._enabled and self._circuit_breaker is not None
    
    def is_available(self) -> bool:
        """Check if LLM service is currently available.
        
        Returns:
            False if circuit is OPEN, True otherwise.
        """
        if not self.is_enabled():
            return True  # No protection = always available
        
        return self._circuit_breaker.state != CircuitState.OPEN
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get current health status and metrics.
        
        Returns:
            Dict with keys:
            - state: 'closed', 'open', 'half_open', or 'disabled'
            - enabled: Whether circuit breaker is enabled
            - available: Whether calls are currently being accepted
            - success_rate: Percentage of successful calls
            - failure_rate: Percentage of failed calls
            - rejection_rate: Percentage of rejected calls (while open)
            - total_calls: Total number of calls attempted
            - successful_calls: Number of successful calls
            - failed_calls: Number of failed calls
            - rejected_calls: Number of rejected calls
            - timeout_calls: Number of timeout failures
            - last_error: Description of last error
            - last_error_time: Timestamp of last error
        """
        if not self.is_enabled():
            return {
                "state": "disabled",
                "enabled": False,
                "available": True,
                "success_rate": 0.0,
                "failure_rate": 0.0,
                "rejection_rate": 0.0,
                "total_calls": self._metrics.total_calls,
                "successful_calls": self._metrics.successful_calls,
                "failed_calls": self._metrics.failed_calls,
                "rejected_calls": self._metrics.rejected_calls,
                "timeout_calls": self._metrics.timeout_calls,
                "last_error": self._metrics.last_error,
                "last_error_time": self._metrics.last_error_time,
            }
        
        state = self._circuit_breaker.state.value
        metrics = self._circuit_breaker.metrics()
        
        return {
            "state": state,
            "enabled": True,
            "available": state != "open",
            "success_rate": metrics.success_rate,
            "failure_rate": metrics.failure_rate,
            "rejection_rate": self._metrics.rejection_rate,
            "total_calls": metrics.total_calls,
            "successful_calls": metrics.successful_calls,
            "failed_calls": metrics.failed_calls,
            "rejected_calls": metrics.rejected_calls,
            "timeout_calls": self._metrics.timeout_calls,
            "last_error": self._metrics.last_error,
            "last_error_time": self._metrics.last_error_time,
        }
    
    def generate(
        self,
        prompt: str,
        *,
        model_name: Optional[str] = None,
        fallback_result: Optional[str] = None,
        **kwargs: object,
    ) -> str:
        """Generate text from prompt with circuit-breaker protection.
        
        Args:
            prompt: Input prompt
            model_name: Optional model override
            fallback_result: Optional fallback text if LLM unavailable
            **kwargs: Provider-specific options
            
        Returns:
            Generated text or fallback_result if LLM unavailable
            
        Raises:
            CircuitBreakerOpen: If circuit is OPEN and no fallback provided
            TimeoutError: If call times out and no fallback provided
            Exception: Other LLM-specific exceptions if no fallback provided
        """
        # Record call attempt
        self._metrics.total_calls += 1
        
        if not self.is_enabled():
            # No protection - pass through directly
            return self._base_router.generate(
                prompt,
                model_name=model_name,
                **kwargs,
            )
        
        # Check if circuit is open
        if not self.is_available():
            self._metrics.rejected_calls += 1
            recovery_time = (
                self._circuit_breaker.recovery_timeout
                if self._circuit_breaker._opened_at is None
                else max(0, self._circuit_breaker.recovery_timeout - (time.time() - self._circuit_breaker._opened_at))
            )
            error_msg = (
                f"LLM service temporarily unavailable ({self._provider_name}). "
                f"Will retry in ~{recovery_time:.1f}s"
            )
            _logger.warning(error_msg)
            
            if fallback_result is not None:
                _logger.info(f"Using fallback result for {self._provider_name}")
                return fallback_result
            
            raise CircuitBreakerOpen(self._provider_name, recovery_time)
        
        # Attempt with retries
        last_error: Optional[Exception] = None
        
        for attempt in range(1, self._max_retries + 2):  # +2 because we count from 1
            try:
                # Apply timeout if supported
                call_kwargs = dict(kwargs)
                if "timeout" not in call_kwargs:
                    call_kwargs["timeout"] = self._call_timeout
                
                # Define the function to call
                def _make_llm_call() -> str:
                    return self._base_router.generate(
                        prompt,
                        model_name=model_name,
                        **call_kwargs,
                    )
                
                # Execute through circuit breaker using its decorator mechanism
                wrapped_func = self._circuit_breaker.call(_make_llm_call)
                result = wrapped_func()
                
                # Success
                self._metrics.successful_calls += 1
                _logger.debug(
                    f"LLM call successful ({self._provider_name}, attempt {attempt}/{self._max_retries + 1})"
                )
                return result
                
            except TimeoutError as e:
                last_error = e
                self._metrics.timeout_calls += 1
                _logger.warning(
                    f"LLM call timeout ({self._provider_name}, attempt {attempt}/{self._max_retries + 1}): {e}"
                )
                
                if attempt > self._max_retries:
                    break
                
                # Exponential backoff: 0.1s, 0.2s, 0.4s, etc.
                backoff = 0.1 * (2 ** (attempt - 1))
                time.sleep(backoff)
                
            except CircuitBreakerOpen as e:
                # Circuit is now open - re-raise
                if fallback_result is not None:
                    _logger.info(f"Using fallback result for {self._provider_name}")
                    return fallback_result
                raise
                
            except Exception as e:
                last_error = e
                self._metrics.failed_calls += 1
                _logger.warning(
                    f"LLM call failed ({self._provider_name}, attempt {attempt}/{self._max_retries + 1}): {e}"
                )
                
                if attempt > self._max_retries:
                    break
                
                # Small backoff before retry
                time.sleep(0.05 * attempt)
        
        # All retries exhausted
        if last_error:
            self._metrics.last_error = str(last_error)
            self._metrics.last_error_time = time.time()
        
        _logger.error(
            f"LLM call failed after {self._max_retries} retries ({self._provider_name})"
        )
        
        if fallback_result is not None:
            _logger.info(f"Using fallback result for {self._provider_name}")
            return fallback_result
        
        # Re-raise last error
        if last_error:
            raise last_error
        
        raise RuntimeError(f"LLM call failed ({self._provider_name})")
