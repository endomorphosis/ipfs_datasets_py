"""Lazy-loading wrapper for LLM backend initialization.

This module provides lazy initialization for optional LLM backends,
avoiding unnecessary imports and instantiation when LLM features are disabled.

Usage:
    # Instead of eagerly loading:
    from some_module import LLMBackend
    backend = LLMBackend()  # Imports and initializes immediately
    
    # Use lazy loading:
    from ipfs_datasets_py.optimizers.llm_lazy_loader import LazyLLMBackend
    backend = LazyLLMBackend()  # Doesn't load until first use
    
    # Access like normal:
    result = backend.generate(prompt="...")  # Loads on first access
"""

import os
import logging
from typing import Any, Optional, Callable
from functools import lru_cache

from ipfs_datasets_py.optimizers.common.backend_resilience import (
    BackendCallPolicy,
    execute_with_resilience,
)
from ipfs_datasets_py.optimizers.common.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
)
from ipfs_datasets_py.optimizers.common.exceptions import (
    CircuitBreakerOpenError,
    RetryableBackendError,
)
from ipfs_datasets_py.optimizers.common.log_redaction import redact_sensitive

logger = logging.getLogger(__name__)


def _safe_error_text(error: Exception) -> str:
    """Render exception text with sensitive fragments redacted."""
    return redact_sensitive(str(error))


class LazyLLMBackend:
    """Lazy-loading wrapper for LLM backend with circuit-breaker resilience.
    
    Defers backend initialization until first access, reducing startup overhead
    when LLM features are disabled (llm_fallback_threshold=0).
    
    Attributes:
        _backend: Cached backend instance (loaded on first access)
        _initialized: Whether backend has been loaded
        _disabled: Whether LLM is disabled via environment variable
        _circuit_breaker: Circuit-breaker for backend calls (failure resilience)
    """
    
    def __init__(self, backend_type: str = "auto", enabled: Optional[bool] = None,
                 circuit_breaker_enabled: bool = True,
                 failure_threshold: int = 5,
                 recovery_timeout: float = 60.0):
        """Initialize lazy loader with optional circuit-breaker.
        
        Args:
            backend_type: Type of backend to load ("auto", "accelerate", "mock", "local")
            enabled: Explicitly enable/disable LLM. If None, check LLM_ENABLED env var.
                    Defaults to True if not specified.
            circuit_breaker_enabled: Whether to enable circuit-breaker protection
            failure_threshold: Number of failures before circuit opens
            recovery_timeout: Seconds to wait before testing recovery
        """
        self._backend: Optional[Any] = None
        self._initialized: bool = False
        self._disabled: bool = False
        self._backend_type: str = backend_type
        self._circuit_breaker_enabled: bool = circuit_breaker_enabled
        
        # Check environment variable for explicit disable first
        env_enabled = os.environ.get("LLM_ENABLED", "").lower()
        if env_enabled in ("0", "false", "no", "off"):
            self._disabled = True
        
        if enabled is False:
            self._disabled = True
        elif enabled is True:
            self._disabled = False
        
        # Only create circuit-breaker if LLM is enabled AND circuit breaker is requested
        self._circuit_breaker: Optional[CircuitBreaker] = None
        if not self._disabled and circuit_breaker_enabled:
            self._circuit_breaker = CircuitBreaker(
                name=f"llm_backend_{backend_type}",
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                expected_exception=Exception,
            )
        self._backend_call_policy = BackendCallPolicy(
            service_name=f"lazy_llm_backend_{backend_type}",
            timeout_seconds=30.0,
            max_retries=2,
            initial_backoff_seconds=0.1,
            backoff_multiplier=2.0,
            max_backoff_seconds=1.0,
            circuit_failure_threshold=max(1, int(failure_threshold)),
            circuit_recovery_timeout=float(recovery_timeout),
        )
    
    def is_enabled(self) -> bool:
        """Check if LLM backend is enabled.
        
        Returns:
            True if backend is enabled and can be used, False otherwise.
        """
        return not self._disabled
    
    def is_initialized(self) -> bool:
        """Check if backend has been loaded.
        
        Returns:
            True if backend has been lazy-loaded from disk.
        """
        return self._initialized
    
    def is_circuit_breaker_open(self) -> bool:
        """Check if circuit-breaker is currently OPEN.
        
        Returns:
            True if circuit is open (service temporarily unavailable), False otherwise.
        """
        if self._circuit_breaker is None:
            return False
        from ipfs_datasets_py.optimizers.common.circuit_breaker import CircuitState
        return self._circuit_breaker.state == CircuitState.OPEN
    
    def get_circuit_breaker_metrics(self) -> Optional[dict]:
        """Get circuit-breaker metrics if enabled.
        
        Returns:
            Dict with success_rate, failure_rate, total_calls, etc., or None if disabled.
        """
        if self._circuit_breaker is None:
            return None
        
        metrics = self._circuit_breaker.metrics()
        return {
            "success_rate": metrics.success_rate,
            "failure_rate": metrics.failure_rate,
            "total_calls": metrics.total_calls,
            "successful_calls": metrics.successful_calls,
            "failed_calls": metrics.failed_calls,
            "rejected_calls": metrics.rejected_calls,
            "state_changes": metrics.state_changes,
        }
    
    @lru_cache(maxsize=1)
    def get_backend(self) -> Optional[Any]:
        """Load and return LLM backend (cached on first call).
        
        Returns:
            Initialized backend instance, or None if disabled.
            
        Raises:
            ImportError: If backend module is not available.
            RuntimeError: If backend initialization fails.
        """
        if self._disabled:
            logger.debug("LLM backend is disabled (LLM_ENABLED=0 or enabled=False)")
            return None
        
        if not self._initialized:
            logger.debug("Lazy-loading LLM backend (type=%s)", self._backend_type)
            self._backend = self._load_backend()
            self._initialized = True
        
        return self._backend
    
    def _load_backend(self) -> Optional[Any]:
        """Load backend based on type.
        
        Returns:
            Initialized backend or None.
            
        Raises:
            ImportError: If required modules are not available.
        """
        backend_type = self._backend_type.lower()
        
        if backend_type == "auto":
            return self._load_auto()
        elif backend_type == "accelerate":
            return self._load_accelerate()
        elif backend_type == "mock":
            return self._load_mock()
        elif backend_type == "local":
            return self._load_local()
        else:
            raise ValueError(f"Unknown backend type: {backend_type}")
    
    def _load_auto(self) -> Optional[Any]:
        """Auto-detect and load optimal backend.
        
        Priority: accelerate > local > mock
        """
        try:
            return self._load_accelerate()
        except ImportError:
            logger.debug("ipfs_accelerate_py not available, trying local backend")
            try:
                return self._load_local()
            except ImportError:
                logger.debug("Local backend not available, falling back to mock")
                return self._load_mock()
    
    def _load_accelerate(self) -> Optional[Any]:
        """Load ipfs_accelerate_py backend.
        
        Raises:
            ImportError: If ipfs_accelerate_py is not installed.
        """
        try:
            # Try importing accelerate backend
            from ipfs_accelerate_py import Client
            logger.info("Loaded ipfs_accelerate_py backend")
            return Client()
        except ImportError as e:
            logger.warning("ipfs_accelerate_py not available: %s", e)
            raise ImportError("ipfs_accelerate_py backend not available") from e
    
    def _load_local(self) -> Optional[Any]:
        """Load local backend (transformers-based).
        
        Raises:
            ImportError: If transformers or torch not available.
        """
        try:
            # Try importing local backend
            import transformers
            import torch
            logger.info("Loaded local transformer backend")
            # Return a simple client wrapper
            return LocalBackendClient()
        except ImportError as e:
            logger.warning("Local backend not available: %s", e)
            raise ImportError("Local backend requires transformers and torch") from e
    
    def _load_mock(self) -> Optional[Any]:
        """Load mock backend (for testing).
        
        Returns:
            Mock backend instance.
        """
        logger.info("Loaded mock backend")
        return MockBackendClient()
    
    def __call__(self, *args, **kwargs) -> Any:
        """Forward calls to underlying backend with circuit-breaker protection.
        
        Enables usage like: backend(prompt="...", model="gpt-4")
        """
        backend = self.get_backend()
        if backend is None:
            raise RuntimeError("LLM backend is disabled")
        
        # If circuit-breaker is enabled, protect the call
        if self._circuit_breaker is not None:
            try:
                return self._execute_with_optional_resilience(backend.__call__, args, kwargs)
            except (CircuitBreakerOpen, CircuitBreakerOpenError) as e:
                logger.warning("Circuit-breaker is open: %s", e)
                raise RuntimeError(f"LLM backend temporarily unavailable: {e}") from e
            except RetryableBackendError as e:
                details = e.details if isinstance(e.details, dict) else {}
                last_error = _safe_error_text(Exception(str(details.get("last_error", str(e)))))
                logger.warning("LLM backend call failed: %s", last_error)
                raise RuntimeError(f"LLM backend error: {last_error}") from e
            except (
                RuntimeError,
                ValueError,
                TypeError,
                AttributeError,
                OSError,
                TimeoutError,
            ) as e:
                safe_error = _safe_error_text(e)
                logger.warning("LLM backend call failed: %s", safe_error)
                raise RuntimeError(f"LLM backend error: {safe_error}") from e
        
        return backend(*args, **kwargs)
    
    def __getattr__(self, name: str) -> Any:
        """Forward attribute access to underlying backend.
        
        Enables usage like: backend.generate(...)
        This returns the actual method/attribute, which preserves circuit-breaker
        wrapping if needed during actual call time.
        """
        backend = self.get_backend()
        if backend is None:
            raise RuntimeError(f"LLM backend is disabled, cannot access {name}")
        
        attr = getattr(backend, name)
        
        # Wrap method calls with circuit-breaker if it's a callable
        if callable(attr) and self._circuit_breaker is not None:
            def wrapped_method(*args, **kwargs) -> Any:
                try:
                    return self._execute_with_optional_resilience(attr, args, kwargs)
                except (CircuitBreakerOpen, CircuitBreakerOpenError) as e:
                    logger.warning("Circuit-breaker is open during %s call: %s", name, e)
                    raise RuntimeError(
                        f"LLM backend temporarily unavailable during {name}: {e}"
                    ) from e
                except RetryableBackendError as e:
                    details = e.details if isinstance(e.details, dict) else {}
                    last_error = _safe_error_text(Exception(str(details.get("last_error", str(e)))))
                    logger.warning("LLM backend method '%s' failed: %s", name, last_error)
                    raise RuntimeError(f"LLM backend error during {name}: {last_error}") from e
                except (
                    RuntimeError,
                    ValueError,
                    TypeError,
                    AttributeError,
                    OSError,
                    TimeoutError,
                ) as e:
                    safe_error = _safe_error_text(e)
                    logger.warning("LLM backend method '%s' failed: %s", name, safe_error)
                    raise RuntimeError(f"LLM backend error during {name}: {safe_error}") from e
            return wrapped_method
        
        return attr

    def _execute_with_optional_resilience(
        self,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Execute through shared resilience wrapper when breaker supports it."""
        if self._circuit_breaker is None:
            return fn(*args, **kwargs)

        # Compatibility path for tests/stubs that expose only `_execute`.
        if not hasattr(self._circuit_breaker, "call"):
            return self._circuit_breaker._execute(fn, args, kwargs)

        return execute_with_resilience(
            lambda: self._circuit_breaker._execute(fn, args, kwargs),
            self._backend_call_policy,
            circuit_breaker=self._circuit_breaker,
        )


class MockBackendClient:
    """Mock LLM backend for testing (no external dependencies)."""
    
    def __call__(self, prompt: str, **kwargs) -> str:
        """Generate mock response."""
        return f"Mock response to: {prompt[:50]}..."
    
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate mock response (callable interface)."""
        return self(prompt, **kwargs)
    
    def stream(self, prompt: str, **kwargs):
        """Mock streaming response (yields words)."""
        response = self(prompt, **kwargs)
        for word in response.split():
            yield word


class LocalBackendClient:
    """Simple wrapper for local transformer-based backend.
    
    This is a placeholder that would be connected to actual transformers
    or similar library.
    """
    
    def __call__(self, prompt: str, **kwargs) -> str:
        """Generate response using local model."""
        # Placeholder: would call actual model
        return f"Local model response to: {prompt[:50]}..."
    
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate response."""
        return self(prompt, **kwargs)


@lru_cache(maxsize=4)
def get_global_llm_backend(
    backend_type: str = "auto",
    circuit_breaker_enabled: bool = True
) -> LazyLLMBackend:
    """Get or create global LLM backend instance (singleton per type and config).
    
    Args:
        backend_type: Type of backend ("auto", "accelerate", "mock", "local")
        circuit_breaker_enabled: Whether to enable circuit-breaker protection
        
    Returns:
        LazyLLMBackend instance.
        
    Example:
        >>> backend = get_global_llm_backend()
        >>> result = backend.generate(prompt="What is AI?")
        
        # With circuit-breaker disabled for testing:
        >>> backend = get_global_llm_backend(circuit_breaker_enabled=False)
    """
    return LazyLLMBackend(
        backend_type=backend_type,
        circuit_breaker_enabled=circuit_breaker_enabled
    )


def disable_llm_backend():
    """Globally disable LLM backend.
    
    Useful for testing or when LLM features should not be available.
    """
    os.environ["LLM_ENABLED"] = "0"
    logger.info("LLM backend globally disabled via environment variable")


def enable_llm_backend():
    """Globally enable LLM backend.
    
    Enables LLM features (if configured).
    """
    os.environ["LLM_ENABLED"] = "1"
    logger.info("LLM backend globally enabled via environment variable")


if __name__ == "__main__":
    # Example usage
    print("=== Mock Backend ===")
    backend = LazyLLMBackend("mock")
    print(f"Enabled: {backend.is_enabled()}")
    print(f"Initialized: {backend.is_initialized()}")
    result = backend.generate(prompt="Hello")
    print(f"Result: {result}")
    print(f"Initialized after use: {backend.is_initialized()}")
    
    print("\n=== Disabled Backend ===")
    disabled = LazyLLMBackend("mock", enabled=False)
    print(f"Enabled: {disabled.is_enabled()}")
    try:
        disabled.generate(prompt="Hello")
    except RuntimeError as e:
        print(f"Error (expected): {e}")
    
    print("\n=== Global Backend ===")
    global_backend = get_global_llm_backend()
    print(f"Global backend type: {type(global_backend)}")
    print(f"Global backend enabled: {global_backend.is_enabled()}")
