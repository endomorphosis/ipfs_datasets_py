"""Tests for distributed tracing instrumentation.

Tests the OpenTelemetry integration for GraphRAG optimizer phases.

Run with::

    pytest tests/unit/optimizers/graphrag/test_tracing_instrumentation.py -v
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from ipfs_datasets_py.optimizers.graphrag.tracing_instrumentation import (
    TracingConfig,
    TracingInstrumentation,
    get_tracer,
    setup_tracing,
    OntologyGeneratorTracer,
    OntologyCriticTracer,
    OntologyMediatorTracer,
)


class TestTracingConfig:
    """Tests for TracingConfig."""
    
    def test_create_default_config(self):
        """Test creating default tracing config."""
        config = TracingConfig()
        assert config.service_name == "graphrag-optimizer"
        assert config.environment == "development"
        assert config.jaeger_host == "localhost"
        assert config.jaeger_port == 6831
        assert config.enable_console_exporter == False
        assert config.enable_jaeger_exporter == True
    
    def test_create_custom_config(self):
        """Test creating custom tracing config."""
        config = TracingConfig(
            service_name="custom-service",
            environment="production",
            jaeger_host="jaeger.example.com",
            jaeger_port=6832,
            enable_console_exporter=True,
        )
        assert config.service_name == "custom-service"
        assert config.environment == "production"
        assert config.jaeger_host == "jaeger.example.com"
        assert config.jaeger_port == 6832
        assert config.enable_console_exporter == True


class TestTracingInstrumentation:
    """Tests for TracingInstrumentation."""
    
    def test_instrumentation_creation(self):
        """Test creating instrumentation without OpenTelemetry."""
        config = TracingConfig(enable_jaeger_exporter=False, enable_console_exporter=False)
        instr = TracingInstrumentation(config)
        assert instr.config == config
    
    def test_setup_tracing_creates_instance(self):
        """Test setup_tracing creates global instance."""
        config = TracingConfig(enable_jaeger_exporter=False, enable_console_exporter=False)
        tracer = setup_tracing(config)
        assert tracer is not None
        assert tracer.config == config
    
    def test_create_span_graceful_degradation(self):
        """Test that create_span handles disabled tracing gracefully."""
        config = TracingConfig(enable_jaeger_exporter=False, enable_console_exporter=False)
        instr = TracingInstrumentation(config)
        span = instr.create_span("test_span", {"key": "value"})
        # Should return None when tracing disabled
        assert span is None


class TestGeneratorTracer:
    """Tests for OntologyGeneratorTracer."""
    
    def test_tracer_creation(self):
        """Test creating generator tracer."""
        tracer = OntologyGeneratorTracer()
        assert tracer is not None
    
    def test_tracer_with_instrumentation(self):
        """Test tracer with instrumentation instance."""
        config = TracingConfig(enable_jaeger_exporter=False, enable_console_exporter=False)
        instr = TracingInstrumentation(config)
        tracer = OntologyGeneratorTracer(instr)
        assert tracer.tracer == instr


class TestCriticTracer:
    """Tests for OntologyCriticTracer."""
    
    def test_tracer_creation(self):
        """Test creating critic tracer."""
        tracer = OntologyCriticTracer()
        assert tracer is not None


class TestMediatorTracer:
    """Tests for OntologyMediatorTracer."""
    
    def test_tracer_creation(self):
        """Test creating mediator tracer."""
        tracer = OntologyMediatorTracer()
        assert tracer is not None


class TestTracingDecoration:
    """Tests for tracing decorators."""
    
    def test_trace_method_decorator_disabled(self):
        """Test trace_method decorator when tracing is disabled."""
        config = TracingConfig(enable_jaeger_exporter=False, enable_console_exporter=False)
        instr = TracingInstrumentation(config)
        
        @instr.trace_method
        def sample_func(x):
            return x * 2
        
        result = sample_func(5)
        assert result == 10


class TestTracingWorkflow:
    """End-to-end tracing workflow tests."""
    
    def test_setup_and_retrieve_tracer(self):
        """Test setup_tracing workflow."""
        config = TracingConfig(
            service_name="test-service",
            enable_jaeger_exporter=False,
            enable_console_exporter=False,
        )
        tracer = setup_tracing(config)
        
        retrieved_tracer = get_tracer()
        assert retrieved_tracer is tracer
        assert retrieved_tracer.config.service_name == "test-service"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
