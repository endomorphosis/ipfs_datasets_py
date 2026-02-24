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

logger = logging.getLogger(__name__)


class LazyLLMBackend:
    """Lazy-loading wrapper for LLM backend.
    
    Defers backend initialization until first access, reducing startup overhead
    when LLM features are disabled (llm_fallback_threshold=0).
    
    Attributes:
        _backend: Cached backend instance (loaded on first access)
        _initialized: Whether backend has been loaded
        _disabled: Whether LLM is disabled via environment variable
    """
    
    def __init__(self, backend_type: str = "auto", enabled: Optional[bool] = None):
        """Initialize lazy loader.
        
        Args:
            backend_type: Type of backend to load ("auto", "accelerate", "mock", "local")
            enabled: Explicitly enable/disable LLM. If None, check LLM_ENABLED env var.
                    Defaults to True if not specified.
        """
        self._backend: Optional[Any] = None
        self._initialized: bool = False
        self._disabled: bool = False
        self._backend_type: str = backend_type
        
        # Check environment variable for explicit disable
        env_enabled = os.environ.get("LLM_ENABLED", "").lower()
        if env_enabled in ("0", "false", "no", "off"):
            self._disabled = True
        
        if enabled is False:
            self._disabled = True
        elif enabled is True:
            self._disabled = False
    
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
        """Forward calls to underlying backend.
        
        Enables usage like: backend(prompt="...", model="gpt-4")
        """
        backend = self.get_backend()
        if backend is None:
            raise RuntimeError("LLM backend is disabled")
        return backend(*args, **kwargs)
    
    def __getattr__(self, name: str) -> Any:
        """Forward attribute access to underlying backend.
        
        Enables usage like: backend.generate(...)
        """
        backend = self.get_backend()
        if backend is None:
            raise RuntimeError(f"LLM backend is disabled, cannot access {name}")
        return getattr(backend, name)


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
def get_global_llm_backend(backend_type: str = "auto") -> LazyLLMBackend:
    """Get or create global LLM backend instance (singleton per type).
    
    Args:
        backend_type: Type of backend ("auto", "accelerate", "mock", "local")
        
    Returns:
        LazyLLMBackend instance.
        
    Example:
        >>> backend = get_global_llm_backend()
        >>> result = backend.generate(prompt="What is AI?")
    """
    return LazyLLMBackend(backend_type=backend_type)


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
