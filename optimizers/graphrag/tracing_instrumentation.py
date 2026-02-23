"""Distributed tracing infrastructure for GraphRAG optimization phases.

This module provides OpenTelemetry instrumentation for measuring and monitoring
GraphRAG optimization pipeline performance across distributed systems.

Features:
- Automatic span creation for extraction, critique, and optimization phases
- Context propagation across async boundaries
- Performance metrics aggregation
- Jaeger/Zipkin exporter support for trace visualization
- Custom span attributes for domain-specific insights

Usage::

    from tracing_instrumentation import TracingConfig, setup_tracing
    
    # Configure tracing
    config = TracingConfig(
        service_name="graphrag-optimizer",
        jaeger_host="localhost",
        jaeger_port=6831,
        enable_console_exporter=True,
    )
    
    # Setup instrumentations
    setup_tracing(config)
    
    # Now all OntologyGenerator/OntologyCritic/OntologyMediator calls are traced
    ontology = ontology_generator.extract_entities(text, context)  # Automatically traced
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable
from functools import wraps
import time
import inspect

# OpenTelemetry imports
try:
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    from opentelemetry.exporter.trace.console_span_exporter import ConsoleSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.urllib3 import URLLib3Instrumentor
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False


@dataclass
class TracingConfig:
    """Configuration for distributed tracing.
    
    Attributes:
        service_name: Identifier for this service in traces (default: "graphrag-optimizer")
        environment: Deployment environment: development, staging, production (default: "development")
        jaeger_host: Jaeger collector hostname (default: "localhost")
        jaeger_port: Jaeger collector port (default: 6831)
        enable_console_exporter: Print spans to console (default: False)
        enable_jaeger_exporter: Send spans to Jaeger (default: True)
        resource_attributes: Additional resource attributes to tag all spans
    """
    
    service_name: str = "graphrag-optimizer"
    environment: str = "development"
    jaeger_host: str = "localhost"
    jaeger_port: int = 6831
    enable_console_exporter: bool = False
    enable_jaeger_exporter: bool = True
    resource_attributes: Optional[Dict[str, str]] = None


class TracingInstrumentation:
    """Main instrumentation class for managing OpenTelemetry setup.
    
    Handles creation of spans, decoration of functions with automatic tracing,
    and management of tracer lifecycle.
    """
    
    def __init__(self, config: TracingConfig):
        """Initialize instrumentation with given configuration.
        
        Args:
            config: TracingConfig with all settings
        """
        self.config = config
        self.enabled = HAS_OTEL
        self._tracer_provider = None
        self._tracer = None
        
        if self.enabled:
            self._setup_otel()
    
    def _setup_otel(self):
        """Setup OpenTelemetry infrastructure with configured exporters."""
        if not HAS_OTEL:
            return
        
        # Create resource with service name
        resource_attrs = {SERVICE_NAME: self.config.service_name}
        if self.config.resource_attributes:
            resource_attrs.update(self.config.resource_attributes)
        resource = Resource.create(resource_attrs)
        
        # Create tracer provider
        self._tracer_provider = TracerProvider(resource=resource)
        
        # Add Jaeger exporter if enabled
        if self.config.enable_jaeger_exporter:
            jaeger_exporter = JaegerExporter(
                agent_host_name=self.config.jaeger_host,
                agent_port=self.config.jaeger_port,
            )
            self._tracer_provider.add_span_processor(
                BatchSpanProcessor(jaeger_exporter)
            )
        
        # Add console exporter if enabled
        if self.config.enable_console_exporter:
            console_exporter = ConsoleSpanExporter()
            self._tracer_provider.add_span_processor(
                BatchSpanProcessor(console_exporter)
            )
        
        # Set as global tracer provider
        trace.set_tracer_provider(self._tracer_provider)
        
        # Get tracer instance
        self._tracer = trace.get_tracer(__name__)
        
        # Instrument third-party libraries
        RequestsInstrumentor().instrument()
        URLLib3Instrumentor().instrument()
    
    def create_span(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """Create a new span with given name and attributes.
        
        Args:
            name: Span operation name
            attributes: Optional dictionary of span attributes
            
        Returns:
            OpenTelemetry span context or None if tracing disabled
        """
        if not self.enabled or self._tracer is None:
            return None
        
        span = self._tracer.start_as_current_span(name)
        if attributes:
            for key, value in attributes.items():
                try:
                    span.set_attribute(key, value)
                except (AttributeError, TypeError):
                    pass
        return span
    
    def trace_method(self, func: Callable) -> Callable:
        """Decorator to automatically trace a method.
        
        Args:
            func: Function to wrap with tracing
            
        Returns:
            Wrapped function with automatic span creation
        """
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not self.enabled:
                return func(*args, **kwargs)
            
            span_name = f"{func.__module__}.{func.__qualname__}"
            with self._tracer.start_as_current_span(span_name):
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    # Record exception in span
                    if self._tracer:
                        span = trace.get_current_span()
                        span.record_exception(e)
                        span.set_attribute("error", True)
                    raise
        
        return wrapper if self.enabled else func


class OntologyGeneratorTracer:
    """Tracer for OntologyGenerator extraction and relationship inference."""
    
    def __init__(self, tracer: Optional[TracingInstrumentation] = None):
        """Initialize generator tracer.
        
        Args:
            tracer: Optional TracingInstrumentation instance
        """
        self.tracer = tracer
    
    def trace_extract_entities(self, func: Callable) -> Callable:
        """Wrap extract_entities with automatic tracing.
        
        Args:
            func: extract_entities method to wrap
            
        Returns:
            Wrapped function with span creation
        """
        @wraps(func)
        def wrapper(self_arg, text: str, context):
            if not self.tracer or not self.tracer.enabled:
                return func(self_arg, text, context)
            
            with self.tracer._tracer.start_as_current_span("extract_entities") as span:
                span.set_attribute("text_length", len(text))
                span.set_attribute("domain", getattr(context, "domain", "unknown"))
                
                start_time = time.time()
                try:
                    result = func(self_arg, text, context)
                    elapsed_ms = (time.time() - start_time) * 1000
                    span.set_attribute("duration_ms", elapsed_ms)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("error", True)
                    raise
        
        return wrapper
    
    def trace_infer_relationships(self, func: Callable) -> Callable:
        """Wrap infer_relationships with automatic tracing.
        
        Args:
            func: infer_relationships method to wrap
            
        Returns:
            Wrapped function with span creation
        """
        @wraps(func)
        def wrapper(self_arg, entities):
            if not self.tracer or not self.tracer.enabled:
                return func(self_arg, entities)
            
            with self.tracer._tracer.start_as_current_span("infer_relationships") as span:
                span.set_attribute("entity_count", len(entities) if entities else 0)
                
                start_time = time.time()
                try:
                    result = func(self_arg, entities)
                    elapsed_ms = (time.time() - start_time) * 1000
                    span.set_attribute("duration_ms", elapsed_ms)
                    span.set_attribute("relationship_count", len(result) if result else 0)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("error", True)
                    raise
        
        return wrapper


class OntologyCriticTracer:
    """Tracer for OntologyCritic evaluation methods."""
    
    def __init__(self, tracer: Optional[TracingInstrumentation] = None):
        """Initialize critic tracer.
        
        Args:
            tracer: Optional TracingInstrumentation instance
        """
        self.tracer = tracer
    
    def trace_evaluate_ontology(self, func: Callable) -> Callable:
        """Wrap evaluate_ontology with automatic tracing.
        
        Args:
            func: evaluate_ontology method to wrap
            
        Returns:
            Wrapped function with span creation
        """
        @wraps(func)
        def wrapper(self_arg, result):
            if not self.tracer or not self.tracer.enabled:
                return func(self_arg, result)
            
            with self.tracer._tracer.start_as_current_span("evaluate_ontology") as span:
                start_time = time.time()
                try:
                    score_result = func(self_arg, result)
                    elapsed_ms = (time.time() - start_time) * 1000
                    span.set_attribute("duration_ms", elapsed_ms)
                    if hasattr(score_result, "overall_score"):
                        span.set_attribute("overall_score", score_result.overall_score)
                    return score_result
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("error", True)
                    raise
        
        return wrapper
    
    def trace_evaluate_completeness(self, func: Callable) -> Callable:
        """Wrap _evaluate_completeness with automatic tracing.
        
        Args:
            func: _evaluate_completeness method to wrap
            
        Returns:
            Wrapped function with span creation
        """
        @wraps(func)
        def wrapper(self_arg, result):
            if not self.tracer or not self.tracer.enabled:
                return func(self_arg, result)
            
            with self.tracer._tracer.start_as_current_span("evaluate_completeness") as span:
                start_time = time.time()
                try:
                    score = func(self_arg, result)
                    elapsed_ms = (time.time() - start_time) * 1000
                    span.set_attribute("duration_ms", elapsed_ms)
                    span.set_attribute("completeness_score", score)
                    return score
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("error", True)
                    raise
        
        return wrapper


class OntologyMediatorTracer:
    """Tracer for OntologyMediator refinement suggestions."""
    
    def __init__(self, tracer: Optional[TracingInstrumentation] = None):
        """Initialize mediator tracer.
        
        Args:
            tracer: Optional TracingInstrumentation instance
        """
        self.tracer = tracer
    
    def trace_suggest_refinement_strategy(self, func: Callable) -> Callable:
        """Wrap suggest_refinement_strategy with automatic tracing.
        
        Args:
            func: suggest_refinement_strategy method to wrap
            
        Returns:
            Wrapped function with span creation
        """
        @wraps(func)
        def wrapper(self_arg, result):
            if not self.tracer or not self.tracer.enabled:
                return func(self_arg, result)
            
            with self.tracer._tracer.start_as_current_span("suggest_refinement_strategy") as span:
                start_time = time.time()
                try:
                    strategy = func(self_arg, result)
                    elapsed_ms = (time.time() - start_time) * 1000
                    span.set_attribute("duration_ms", elapsed_ms)
                    if hasattr(strategy, "action"):
                        span.set_attribute("action", strategy.action)
                    if hasattr(strategy, "estimated_impact"):
                        span.set_attribute("estimated_impact", strategy.estimated_impact)
                    return strategy
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("error", True)
                    raise
        
        return wrapper


# Global instrumentation instance
_instrumentation: Optional[TracingInstrumentation] = None


def setup_tracing(config: Optional[TracingConfig] = None) -> TracingInstrumentation:
    """Setup global tracing instrumentation.
    
    Args:
        config: Optional TracingConfig. Uses defaults if not provided.
        
    Returns:
        Configured TracingInstrumentation instance
        
    Example::
    
        config = TracingConfig(service_name="my-service")
        setup_tracing(config)
        tracer = get_tracer()
    """
    global _instrumentation
    if config is None:
        config = TracingConfig()
    _instrumentation = TracingInstrumentation(config)
    return _instrumentation


def get_tracer() -> Optional[TracingInstrumentation]:
    """Get global tracing instrumentation instance.
    
    Returns:
        TracingInstrumentation or None if not configured
    """
    return _instrumentation


def instrument_ontology_generator(generator_class):
    """Instrument OntologyGenerator class with tracing.
    
    Args:
        generator_class: OntologyGenerator class to instrument
        
    Returns:
        Instrumented class (or original if tracing unavailable)
    """
    if not get_tracer():
        return generator_class
    
    tracer = OntologyGeneratorTracer(get_tracer())
    if hasattr(generator_class, 'extract_entities'):
        original = generator_class.extract_entities
        generator_class.extract_entities = tracer.trace_extract_entities(original)
    if hasattr(generator_class, 'infer_relationships'):
        original = generator_class.infer_relationships
        generator_class.infer_relationships = tracer.trace_infer_relationships(original)
    
    return generator_class


def instrument_ontology_critic(critic_class):
    """Instrument OntologyCritic class with tracing.
    
    Args:
        critic_class: OntologyCritic class to instrument
        
    Returns:
        Instrumented class (or original if tracing unavailable)
    """
    if not get_tracer():
        return critic_class
    
    tracer = OntologyCriticTracer(get_tracer())
    if hasattr(critic_class, 'evaluate_ontology'):
        original = critic_class.evaluate_ontology
        critic_class.evaluate_ontology = tracer.trace_evaluate_ontology(original)
    if hasattr(critic_class, '_evaluate_completeness'):
        original = critic_class._evaluate_completeness
        critic_class._evaluate_completeness = tracer.trace_evaluate_completeness(original)
    
    return critic_class


def instrument_ontology_mediator(mediator_class):
    """Instrument OntologyMediator class with tracing.
    
    Args:
        mediator_class: OntologyMediator class to instrument
        
    Returns:
        Instrumented class (or original if tracing unavailable)
    """
    if not get_tracer():
        return mediator_class
    
    tracer = OntologyMediatorTracer(get_tracer())
    if hasattr(mediator_class, 'suggest_refinement_strategy'):
        original = mediator_class.suggest_refinement_strategy
        mediator_class.suggest_refinement_strategy = tracer.trace_suggest_refinement_strategy(original)
    
    return mediator_class


def auto_instrument_all():
    """Attempt to automatically instrument all GraphRAG classes.
    
    Tries to import and instrument OntologyGenerator, OntologyCritic,
    and OntologyMediator. Gracefully degrades if classes not available.
    """
    if not get_tracer():
        return
    
    try:
        from ..graphrag.ontology_generator import OntologyGenerator
        instrument_ontology_generator(OntologyGenerator)
    except (ImportError, AttributeError):
        pass
    
    try:
        from ..graphrag.ontology_critic import OntologyCritic
        instrument_ontology_critic(OntologyCritic)
    except (ImportError, AttributeError):
        pass
    
    try:
        from ..graphrag.ontology_mediator import OntologyMediator
        instrument_ontology_mediator(OntologyMediator)
    except (ImportError, AttributeError):
        pass
