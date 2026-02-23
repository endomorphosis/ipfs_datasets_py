"""Tests for optimizer and related protocols."""

import pytest
from typing import Any, Tuple, List
from ipfs_datasets_py.optimizers.common.protocols import (
    IOptimizer,
    IMetricsCollector,
    ILLMBackend,
    ICache,
)
from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig
from ipfs_datasets_py.optimizers.common.base_optimizer import OptimizationContext


class ConcreteOptimizer:
    """Concrete implementation of IOptimizer for testing."""
    
    def __init__(self, config: OptimizerConfig = None):
        self.config = config or OptimizerConfig()
    
    def generate(self, input_data: Any, context: OptimizationContext) -> Any:
        return f"generated: {input_data}"
    
    def critique(
        self,
        artifact: Any,
        context: OptimizationContext,
    ) -> Tuple[float, List[str]]:
        return 0.85, ["improve clarity", "add examples"]
    
    def optimize(
        self,
        artifact: Any,
        score: float,
        feedback: List[str],
        context: OptimizationContext,
    ) -> Any:
        return f"optimized: {artifact}"
    
    def validate(self, artifact: Any, context: OptimizationContext) -> bool:
        return True


class PartialOptimizer:
    """Incomplete implementation - missing some methods."""
    
    def __init__(self):
        self.config = OptimizerConfig()
    
    def generate(self, input_data: Any, context: OptimizationContext) -> Any:
        return input_data
    
    def critique(self, artifact: Any, context: OptimizationContext) -> Tuple[float, List[str]]:
        return 0.5, []
    
    # Missing optimize() and validate()


class TestIOptimizerProtocol:
    """Test IOptimizer protocol and runtime checking."""
    
    def test_concrete_optimizer_is_instance_of_protocol(self):
        """Test that concrete implementation passes isinstance check."""
        optimizer = ConcreteOptimizer()
        
        assert isinstance(optimizer, IOptimizer)
    
    def test_partial_optimizer_not_instance_of_protocol(self):
        """Test that incomplete implementation fails isinstance check."""
        optimizer = PartialOptimizer()
        
        # Should fail because it doesn't have all required methods
        assert not isinstance(optimizer, IOptimizer)
    
    def test_protocol_methods_are_callable(self):
        """Test that protocol methods can be called."""
        optimizer = ConcreteOptimizer()
        context = OptimizationContext(
            session_id="test_session",
            input_data="test",
            domain="legal",
        )
        
        # Generate
        generated = optimizer.generate("input", context)
        assert generated == "generated: input"
        
        # Critique
        score, feedback = optimizer.critique(generated, context)
        assert score == 0.85
        assert len(feedback) == 2
        
        # Optimize
        optimized = optimizer.optimize(generated, score, feedback, context)
        assert "optimized:" in optimized
        
        # Validate
        is_valid = optimizer.validate(optimized, context)
        assert is_valid is True
    
    def test_protocol_config_property(self):
        """Test that config property is accessible."""
        config = OptimizerConfig(domain="medical", max_rounds=10)
        optimizer = ConcreteOptimizer(config=config)
        
        assert optimizer.config.domain == "medical"
        assert optimizer.config.max_rounds == 10
    
    def test_protocol_with_type_annotation(self):
        """Test using protocol in type annotations."""
        def run_optimizer(opt: IOptimizer, input_data: Any) -> Any:
            context = OptimizationContext(
                session_id="session",
                input_data=input_data,
                domain="general",
            )
            artifact = opt.generate(input_data, context)
            score, feedback = opt.critique(artifact, context)
            return score
        
        optimizer = ConcreteOptimizer()
        result = run_optimizer(optimizer, "test input")
        
        assert result == 0.85
    
    def test_protocol_docs(self):
        """Test that protocol has documentation."""
        assert IOptimizer.__doc__ is not None
        assert "runtime_checkable" in IOptimizer.__doc__.lower()
        
        # Check method docstrings
        assert IOptimizer.generate.__doc__ is not None
        assert IOptimizer.critique.__doc__ is not None
        assert IOptimizer.optimize.__doc__ is not None
        assert IOptimizer.validate.__doc__ is not None


class ConcreteMetricsCollector:
    """Concrete implementation of IMetricsCollector."""
    
    def __init__(self):
        self.scores = []
        self.rounds = 0
        self.errors = []
    
    def record_score(self, score: float) -> None:
        self.scores.append(score)
    
    def record_round_completion(self) -> None:
        self.rounds += 1
    
    def record_error(self, error_type: str) -> None:
        self.errors.append(error_type)


class TestIMetricsCollectorProtocol:
    """Test IMetricsCollector protocol."""
    
    def test_concrete_metrics_collector_is_instance(self):
        """Test that concrete implementation passes isinstance check."""
        collector = ConcreteMetricsCollector()
        
        assert isinstance(collector, IMetricsCollector)
    
    def test_metrics_collection_workflow(self):
        """Test metrics collection workflow."""
        collector = ConcreteMetricsCollector()
        
        collector.record_score(0.75)
        collector.record_score(0.85)
        collector.record_round_completion()
        collector.record_round_completion()
        collector.record_error("validation")
        
        assert collector.scores == [0.75, 0.85]
        assert collector.rounds == 2
        assert collector.errors == ["validation"]


class ConcreteLLMBackend:
    """Concrete implementation of ILLMBackend."""
    
    def __init__(self, available: bool = True):
        self._available = available
    
    def generate(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        return f"Response to: {prompt}"
    
    def is_available(self) -> bool:
        return self._available


class TestILLMBackendProtocol:
    """Test ILLMBackend protocol."""
    
    def test_concrete_llm_backend_is_instance(self):
        """Test that concrete implementation passes isinstance check."""
        backend = ConcreteLLMBackend()
        
        assert isinstance(backend, ILLMBackend)
    
    def test_llm_backend_generation(self):
        """Test LLM backend generation."""
        backend = ConcreteLLMBackend(available=True)
        
        assert backend.is_available() is True
        
        response = backend.generate("prompt")
        assert "Response to: prompt" in response
    
    def test_llm_backend_unavailable(self):
        """Test unavailable backend."""
        backend = ConcreteLLMBackend(available=False)
        
        assert backend.is_available() is False


class ConcreteCache:
    """Concrete implementation of ICache."""
    
    def __init__(self):
        self._data = {}
    
    def get(self, key: str):
        return self._data.get(key)
    
    def put(self, key: str, value, ttl_seconds=None) -> None:
        self._data[key] = value
    
    def clear(self) -> None:
        self._data.clear()


class TestICacheProtocol:
    """Test ICache protocol."""
    
    def test_concrete_cache_is_instance(self):
        """Test that concrete implementation passes isinstance check."""
        cache = ConcreteCache()
        
        assert isinstance(cache, ICache)
    
    def test_cache_operations(self):
        """Test cache get/put/clear operations."""
        cache = ConcreteCache()
        
        # Test put and get
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"
        
        # Test missing key
        assert cache.get("missing") is None
        
        # Test clear
        cache.clear()
        assert cache.get("key1") is None
    
    def test_cache_with_ttl(self):
        """Test cache put with TTL."""
        cache = ConcreteCache()
        
        # Should not raise, even though concrete impl ignores ttl
        cache.put("key", "value", ttl_seconds=60)
        assert cache.get("key") == "value"


class TestProtocolComposition:
    """Test combining multiple protocols."""
    
    def test_optimizer_with_metrics_collector(self):
        """Test optimizer using metrics collector."""
        optimizer = ConcreteOptimizer()
        collector = ConcreteMetricsCollector()
        
        assert isinstance(optimizer, IOptimizer)
        assert isinstance(collector, IMetricsCollector)
        
        # Simulate workflow
        collector.record_score(0.85)
        collector.record_round_completion()
        
        assert len(collector.scores) == 1
        assert collector.rounds == 1
    
    def test_optimizer_with_llm_backend(self):
        """Test optimizer using LLM backend."""
        optimizer = ConcreteOptimizer()
        backend = ConcreteLLMBackend(available=True)
        
        assert isinstance(optimizer, IOptimizer)
        assert isinstance(backend, ILLMBackend)
        
        # Both should be usable
        assert backend.is_available()
