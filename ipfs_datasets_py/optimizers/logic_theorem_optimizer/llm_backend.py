"""LLM Backend Integration for Logic Theorem Optimizer.

This module provides integration with ipfs_accelerate_py for real LLM inference,
replacing mock responses with actual model outputs.

Supports:
- Text generation for logic extraction
- Streaming for large inputs
- Batch inference
- Model selection
- Automatic backend selection (local/distributed)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, List, Optional, Protocol, runtime_checkable, cast
from dataclasses import dataclass, replace
from enum import Enum

from ipfs_datasets_py.optimizers.common.backend_resilience import BackendCallPolicy, execute_with_resilience
from ipfs_datasets_py.optimizers.common.circuit_breaker import CircuitBreaker
from ipfs_datasets_py.optimizers.common.exceptions import CircuitBreakerOpenError, RetryableBackendError

logger = logging.getLogger(__name__)


@runtime_checkable
class SupportsGenerate(Protocol):
    """Protocol for backends that provide single-request generation."""

    def generate(self, request: "LLMRequest") -> "LLMResponse":
        """Generate a single response for the request."""


@runtime_checkable
class SupportsGenerateStream(Protocol):
    """Protocol for backends that support streaming generation."""

    def generate_stream(self, request: "LLMRequest") -> Iterator[str]:
        """Yield streaming response chunks."""


@runtime_checkable
class SupportsGenerateBatch(Protocol):
    """Protocol for backends that support batch generation."""

    def generate_batch(self, requests: List["LLMRequest"]) -> List["LLMResponse"]:
        """Generate responses for a batch of requests."""


class LLMBackendType(Enum):
    """Supported LLM backend types."""
    ACCELERATE = "ipfs_accelerate_py"
    MOCK = "mock"
    LOCAL = "local"


@dataclass
class LLMRequest:
    """Request for LLM inference.
    
    Attributes:
        prompt: Input prompt
        model: Model name
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        stream: Whether to stream response
        metadata: Additional metadata
    """
    prompt: str
    model: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int = 1024
    stream: bool = False
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


@dataclass
class LLMResponse:
    """Response from LLM inference.
    
    Attributes:
        text: Generated text
        model: Model used
        tokens_used: Number of tokens used
        finish_reason: Reason for completion
        backend: Backend that generated response
        metadata: Additional metadata
    """
    text: str
    model: str
    tokens_used: int = 0
    finish_reason: str = "stop"
    backend: str = "unknown"
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


class LLMBackendAdapter:
    """Adapter for LLM backends.
    
    This adapter provides a unified interface for different LLM backends,
    with automatic fallback and intelligent backend selection.
    
    Example:
        >>> adapter = LLMBackendAdapter(preferred_backend="accelerate")
        >>> request = LLMRequest(prompt="Extract logic from: All employees must train")
        >>> response = adapter.generate(request)
        >>> print(response.text)
    """
    
    def __init__(
        self,
        preferred_backend: Optional[str] = None,
        fallback_to_mock: bool = True,
        enable_caching: bool = True
    ) -> None:
        """Initialize the LLM backend adapter.
        
        Args:
            preferred_backend: Preferred backend ('accelerate', 'local', 'mock')
            fallback_to_mock: Whether to fall back to mock if preferred unavailable
            enable_caching: Whether to cache responses
        """
        self.preferred_backend = preferred_backend or "accelerate"
        self.fallback_to_mock = fallback_to_mock
        self.enable_caching = enable_caching
        self._backend_call_policy = BackendCallPolicy(
            service_name="logic_theorem_optimizer_backend",
            timeout_seconds=30.0,
            max_retries=2,
            initial_backoff_seconds=0.1,
            backoff_multiplier=2.0,
            max_backoff_seconds=1.0,
            circuit_failure_threshold=5,
            circuit_recovery_timeout=60.0,
        )
        self._backend_circuit_breakers: Dict[str, CircuitBreaker[LLMResponse]] = {}
        
        # Initialize backends
        self.backends: Dict[str, SupportsGenerate] = {}
        self._init_backends()
        
        # Select active backend
        self.active_backend = self._select_backend()
        logger.info(f"LLM backend adapter initialized with: {self.active_backend}")
        
        # Cache for responses
        self.cache: Optional[Dict[str, LLMResponse]] = {} if enable_caching else None
        
        # Statistics
        self.stats: Dict[str, Any] = {
            'requests': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'tokens_used': 0,
            'errors': 0
        }
    
    def _init_backends(self) -> None:
        """Initialize available backends."""
        # Try to initialize ipfs_accelerate_py backend
        try:
            from ipfs_datasets_py.ml.accelerate_integration import AccelerateManager
            self.backends['accelerate'] = AccelerateBackend(AccelerateManager())
            logger.info("Initialized ipfs_accelerate_py backend")
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.warning(f"Could not initialize accelerate backend: {e}")
        
        # Always initialize mock backend
        self.backends['mock'] = MockBackend()
        logger.info("Initialized mock backend")
    
    def _select_backend(self) -> str:
        """Select the active backend.
        
        Returns:
            Name of selected backend
        """
        # Try preferred backend first
        if self.preferred_backend in self.backends:
            return self.preferred_backend
        
        # Try accelerate if available
        if 'accelerate' in self.backends:
            return 'accelerate'
        
        # Fall back to mock
        if self.fallback_to_mock and 'mock' in self.backends:
            return 'mock'
        
        raise RuntimeError("No LLM backend available")
    
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate response for request.
        
        Args:
            request: LLM request
            
        Returns:
            LLM response
        """
        self.stats['requests'] += 1
        
        # Check cache
        if self.cache is not None:
            cache_key = self._get_cache_key(request)
            if cache_key in self.cache:
                self.stats['cache_hits'] += 1
                return self.cache[cache_key]
            self.stats['cache_misses'] += 1
        
        # Generate response
        try:
            backend_name = self.active_backend
            backend = self.backends[backend_name]
            backend_policy, circuit_breaker = self._policy_and_breaker_for_backend(backend_name)

            response = cast(
                LLMResponse,
                execute_with_resilience(
                    lambda: backend.generate(request),
                    backend_policy,
                    circuit_breaker=circuit_breaker,
                ),
            )
            response.backend = backend_name
            
            # Update stats
            self.stats['tokens_used'] += response.tokens_used
            
            # Cache response
            if self.cache is not None:
                self.cache[cache_key] = response
            
            return response
            
        except (
            AttributeError,
            CircuitBreakerOpenError,
            KeyError,
            RetryableBackendError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            self.stats['errors'] += 1
            logger.error(f"Generation error: {e}")
            
            # Try fallback to mock
            if self.active_backend != 'mock' and 'mock' in self.backends:
                logger.info("Falling back to mock backend")
                return self.backends['mock'].generate(request)
            
            raise

    def _policy_and_breaker_for_backend(
        self,
        backend_name: str,
    ) -> tuple[BackendCallPolicy, CircuitBreaker[LLMResponse]]:
        """Return stable resilience policy + circuit breaker for a backend."""
        backend_policy = replace(
            self._backend_call_policy,
            service_name=f"{self._backend_call_policy.service_name}_{backend_name}",
        )
        circuit_breaker = self._backend_circuit_breakers.get(backend_name)
        if circuit_breaker is None:
            circuit_breaker = CircuitBreaker(
                name=backend_policy.service_name,
                failure_threshold=backend_policy.circuit_failure_threshold,
                recovery_timeout=backend_policy.circuit_recovery_timeout,
                expected_exception=Exception,
            )
            self._backend_circuit_breakers[backend_name] = circuit_breaker
        return backend_policy, circuit_breaker
    
    def generate_stream(
        self,
        request: LLMRequest
    ) -> Iterator[str]:
        """Generate streaming response.
        
        Args:
            request: LLM request with stream=True
            
        Yields:
            Text chunks
        """
        request = replace(request, stream=True)
        backend = self.backends[self.active_backend]
        
        if isinstance(backend, SupportsGenerateStream):
            yield from backend.generate_stream(request)
        else:
            # Fallback: return entire response
            response = self.generate(request)
            yield response.text
    
    def generate_batch(
        self,
        requests: List[LLMRequest]
    ) -> List[LLMResponse]:
        """Generate responses for batch of requests.
        
        Args:
            requests: List of LLM requests
            
        Returns:
            List of LLM responses
        """
        backend = self.backends[self.active_backend]
        
        if isinstance(backend, SupportsGenerateBatch):
            backend_policy, circuit_breaker = self._policy_and_breaker_for_backend(self.active_backend)
            responses = cast(
                List[LLMResponse],
                execute_with_resilience(
                    lambda: backend.generate_batch(requests),
                    backend_policy,
                    circuit_breaker=circuit_breaker,
                ),
            )
        else:
            # Fallback: generate one by one
            responses = [self.generate(req) for req in requests]
        
        return responses
    
    def _get_cache_key(self, request: LLMRequest) -> str:
        """Get cache key for request.
        
        Args:
            request: LLM request
            
        Returns:
            Cache key
        """
        import hashlib
        key_str = f"{request.prompt}|{request.model}|{request.temperature}|{request.max_tokens}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get backend statistics.
        
        Returns:
            Statistics dictionary
        """
        stats = self.stats.copy()
        
        # Calculate cache hit rate
        total_lookups = stats['cache_hits'] + stats['cache_misses']
        if total_lookups > 0:
            stats['cache_hit_rate'] = stats['cache_hits'] / total_lookups
        else:
            stats['cache_hit_rate'] = 0.0
        
        stats['active_backend'] = self.active_backend
        stats['available_backends'] = list(self.backends.keys())
        
        return stats


class AccelerateBackend:
    """Backend using ipfs_accelerate_py."""
    
    def __init__(self, manager: Any) -> None:
        """Initialize accelerate backend.
        
        Args:
            manager: AccelerateManager instance
        """
        self.manager = manager
    
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate response using accelerate.
        
        Args:
            request: LLM request
            
        Returns:
            LLM response
        """
        try:
            # Run inference using accelerate manager
            result = self.manager.run_inference(
                model_name=request.model,
                input_data=request.prompt,
                task_type="text-generation",
                temperature=request.temperature,
                max_tokens=request.max_tokens
            )
            if not isinstance(result, dict):
                raise TypeError("run_inference() must return a dict payload")
            payload = cast(Dict[str, Any], result)
            
            # Extract response
            text = str(payload.get('output', payload.get('text', '')))
            tokens = int(payload.get('tokens_used', 0))
            
            return LLMResponse(
                text=text,
                model=request.model,
                tokens_used=tokens,
                finish_reason="stop",
                metadata=payload
            )
            
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as e:
            logger.error(f"Accelerate generation error: {e}")
            raise
    
    def generate_batch(
        self,
        requests: List[LLMRequest]
    ) -> List[LLMResponse]:
        """Generate batch responses.
        
        Args:
            requests: List of requests
            
        Returns:
            List of responses
        """
        # For now, generate one by one
        # In future, can use batch API if available
        return [self.generate(req) for req in requests]


class MockBackend:
    """Mock backend for testing."""
    
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate mock response.
        
        Args:
            request: LLM request
            
        Returns:
            LLM response
        """
        # Generate simple mock response based on prompt patterns
        prompt_lower = request.prompt.lower()
        
        if 'extract' in prompt_lower and 'logic' in prompt_lower:
            text = self._generate_logic_extraction(request.prompt)
        elif 'improve' in prompt_lower or 'refine' in prompt_lower:
            text = self._generate_improvement(request.prompt)
        else:
            text = f"Mock response for: {request.prompt[:50]}..."
        
        return LLMResponse(
            text=text,
            model=request.model,
            tokens_used=len(text.split()),
            finish_reason="stop",
            backend="mock"
        )
    
    def _generate_logic_extraction(self, prompt: str) -> str:
        """Generate mock logic extraction response.
        
        Args:
            prompt: Input prompt
            
        Returns:
            Mock response
        """
        # Extract data section from prompt
        import re
        data_match = re.search(r'Data: (.+?)(?:\n|$)', prompt)
        if data_match:
            data = data_match.group(1)
            
            # Simple pattern matching
            if 'must' in data.lower():
                return f"O(Predicate({data.split('must')[1].strip()}))"
            elif 'may' in data.lower():
                return f"P(Predicate({data.split('may')[1].strip()}))"
            else:
                return f"Predicate({data})"
        
        return "Predicate(unknown)"
    
    def _generate_improvement(self, prompt: str) -> str:
        """Generate mock improvement response.
        
        Args:
            prompt: Input prompt
            
        Returns:
            Mock response
        """
        return "Improve by: Add more specific predicates, clarify temporal constraints, strengthen logical connections."


def get_default_adapter() -> LLMBackendAdapter:
    """Get default LLM backend adapter.
    
    Returns:
        Configured LLMBackendAdapter
    """
    return LLMBackendAdapter(
        preferred_backend="accelerate",
        fallback_to_mock=True,
        enable_caching=True
    )
