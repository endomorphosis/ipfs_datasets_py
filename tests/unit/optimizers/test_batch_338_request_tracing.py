"""
Batch 338: Distributed Request ID Tracing
===========================================

Implements distributed tracing with request IDs for observability
and debugging across service boundaries.

Goal: Provide:
- Request ID generation and propagation
- Trace context management
- Span tracking and hierarchies
- Metrics aggregation
- Integration with logging
"""

import pytest
import time
import uuid
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class SpanKind(Enum):
    """Types of spans in trace."""
    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


@dataclass
class Span:
    """A span represents a unit of work."""
    span_id: str
    trace_id: str
    parent_span_id: Optional[str] = None
    operation_name: str = "unknown"
    kind: SpanKind = SpanKind.INTERNAL
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    status: str = "unset"
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    
    def duration_ms(self) -> Optional[float]:
        """Get span duration in milliseconds."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000
    
    def is_root(self) -> bool:
        """Check if this is a root span."""
        return self.parent_span_id is None


@dataclass
class TraceMetrics:
    """Metrics for distributed tracing."""
    total_traces: int = 0
    total_spans: int = 0
    avg_span_duration_ms: float = 0.0
    max_trace_depth: int = 0
    
    def update(self, spans: List[Span]) -> None:
        """Update metrics from spans."""
        if not spans:
            return
        
        self.total_spans = len(spans)
        
        durations = [s.duration_ms() for s in spans if s.duration_ms()]
        if durations:
            self.avg_span_duration_ms = sum(durations) / len(durations)


# ============================================================================
# TRACE CONTEXT
# ============================================================================

class TraceContext:
    """Manages trace context for current execution."""
    
    def __init__(self):
        """Initialize trace context."""
        self.trace_id = str(uuid.uuid4())
        self.current_span_id: Optional[str] = None
        self.spans: Dict[str, Span] = {}
        self.span_stack: List[str] = []
    
    def start_span(self, operation_name: str,
                   kind: SpanKind = SpanKind.INTERNAL,
                   attributes: Optional[Dict] = None) -> Span:
        """Start a new span.
        
        Args:
            operation_name: Name of operation
            kind: Type of span
            attributes: Initial attributes
            
        Returns:
            New span
        """
        span_id = str(uuid.uuid4())
        parent_id = self.span_stack[-1] if self.span_stack else None
        
        span = Span(
            span_id=span_id,
            trace_id=self.trace_id,
            parent_span_id=parent_id,
            operation_name=operation_name,
            kind=kind,
            attributes=attributes or {},
        )
        
        self.spans[span_id] = span
        self.span_stack.append(span_id)
        self.current_span_id = span_id
        
        return span
    
    def end_span(self, span_id: str) -> None:
        """End a span.
        
        Args:
            span_id: ID of span to end
        """
        if span_id in self.spans:
            self.spans[span_id].end_time = time.time()
        
        if self.span_stack and self.span_stack[-1] == span_id:
            self.span_stack.pop()
        
        self.current_span_id = self.span_stack[-1] if self.span_stack else None
    
    def add_event(self, span_id: str, event_name: str,
                  attributes: Optional[Dict] = None) -> None:
        """Add event to span.
        
        Args:
            span_id: Span ID
            event_name: Event name
            attributes: Event attributes
        """
        if span_id in self.spans:
            self.spans[span_id].events.append({
                "name": event_name,
                "timestamp": time.time(),
                "attributes": attributes or {},
            })
    
    def add_attribute(self, span_id: str, key: str, value: Any) -> None:
        """Add attribute to span.
        
        Args:
            span_id: Span ID
            key: Attribute key
            value: Attribute value
        """
        if span_id in self.spans:
            self.spans[span_id].attributes[key] = value
    
    def get_span_tree(self) -> Dict[str, Any]:
        """Get span hierarchy.
        
        Returns:
            Nested span tree
        """
        # Find root spans
        roots = [s for s in self.spans.values() if s.is_root()]
        
        def build_tree(span: Span) -> Dict:
            children = [
                build_tree(self.spans[s.span_id])
                for s in self.spans.values()
                if s.parent_span_id == span.span_id
            ]
            
            return {
                "span_id": span.span_id,
                "operation": span.operation_name,
                "duration_ms": span.duration_ms(),
                "children": children,
            }
        
        return {
            "trace_id": self.trace_id,
            "spans": [build_tree(root) for root in roots],
        }


# ============================================================================
# REQUEST ID PROPAGATION
# ============================================================================

class RequestIDManager:
    """Manages request IDs across service calls."""
    
    _contexts: Dict[int, TraceContext] = {}  # Map thread ID to context
    _lock = __import__('threading').Lock()
    
    @classmethod
    def get_context(cls) -> TraceContext:
        """Get current trace context.
        
        Returns:
            TraceContext for current thread
        """
        thread_id = __import__('threading').current_thread().ident
        
        with cls._lock:
            if thread_id not in cls._contexts:
                cls._contexts[thread_id] = TraceContext()
            
            return cls._contexts[thread_id]
    
    @classmethod
    def get_trace_id(cls) -> str:
        """Get current trace ID.
        
        Returns:
            Current trace ID
        """
        return cls.get_context().trace_id
    
    @classmethod
    def new_trace(cls) -> TraceContext:
        """Create new trace.
        
        Returns:
            New TraceContext
        """
        thread_id = __import__('threading').current_thread().ident
        context = TraceContext()
        
        with cls._lock:
            cls._contexts[thread_id] = context
        
        return context
    
    @classmethod
    def start_span(cls, operation_name: str,
                   kind: SpanKind = SpanKind.INTERNAL) -> str:
        """Start span in current trace.
        
        Args:
            operation_name: Operation name
            kind: Span kind
            
        Returns:
            Span ID
        """
        context = cls.get_context()
        span = context.start_span(operation_name, kind)
        return span.span_id
    
    @classmethod
    def end_span(cls, span_id: str) -> None:
        """End span.
        
        Args:
            span_id: Span ID
        """
        context = cls.get_context()
        context.end_span(span_id)


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestSpan:
    """Test span tracking."""
    
    def test_span_creation(self):
        """Test creating span."""
        span = Span(
            span_id="span1",
            trace_id="trace1",
            parent_span_id="parent1",
            operation_name="test"
        )
        
        assert span.span_id == "span1"
        assert not span.is_root()
    
    def test_root_span(self):
        """Test root span detection."""
        span = Span(
            span_id="span1",
            trace_id="trace1"
        )
        
        assert span.is_root()
    
    def test_span_duration(self):
        """Test span duration calculation."""
        span = Span(
            span_id="span1",
            trace_id="trace1"
        )
        
        time.sleep(0.1)
        span.end_time = time.time()
        
        duration = span.duration_ms()
        assert duration is not None
        assert duration >= 100


class TestTraceContext:
    """Test trace context."""
    
    def test_create_context(self):
        """Test creating context."""
        ctx = TraceContext()
        
        assert ctx.trace_id is not None
        assert ctx.current_span_id is None
    
    def test_start_span(self):
        """Test starting span."""
        ctx = TraceContext()
        
        span = ctx.start_span("operation1")
        
        assert span.operation_name == "operation1"
        assert ctx.current_span_id == span.span_id
    
    def test_span_hierarchy(self):
        """Test parent-child span hierarchy."""
        ctx = TraceContext()
        
        parent = ctx.start_span("parent")
        child = ctx.start_span("child")
        
        assert child.parent_span_id == parent.span_id
    
    def test_end_span(self):
        """Test ending span."""
        ctx = TraceContext()
        
        span = ctx.start_span("operation")
        span_id = span.span_id
        
        ctx.end_span(span_id)
        
        assert ctx.spans[span_id].end_time is not None
    
    def test_add_event(self):
        """Test adding event to span."""
        ctx = TraceContext()
        
        span = ctx.start_span("operation")
        ctx.add_event(span.span_id, "event1")
        
        assert len(span.events) == 1
        assert span.events[0]["name"] == "event1"
    
    def test_add_attribute(self):
        """Test adding attribute to span."""
        ctx = TraceContext()
        
        span = ctx.start_span("operation")
        ctx.add_attribute(span.span_id, "service", "api")
        
        assert span.attributes["service"] == "api"
    
    def test_span_tree(self):
        """Test span hierarchy tree."""
        ctx = TraceContext()
        
        root = ctx.start_span("root")
        child = ctx.start_span("child")
        ctx.end_span(child.span_id)
        ctx.end_span(root.span_id)
        
        tree = ctx.get_span_tree()
        
        assert tree["trace_id"] == ctx.trace_id
        assert len(tree["spans"]) > 0


class TestRequestIDManager:
    """Test request ID manager."""
    
    def test_get_trace_id(self):
        """Test getting trace ID."""
        RequestIDManager.new_trace()
        
        trace_id = RequestIDManager.get_trace_id()
        
        assert trace_id is not None
    
    def test_trace_id_consistency(self):
        """Test trace ID consistency."""
        RequestIDManager.new_trace()
        
        id1 = RequestIDManager.get_trace_id()
        id2 = RequestIDManager.get_trace_id()
        
        assert id1 == id2
    
    def test_new_trace_creates_new_id(self):
        """Test that new trace creates new ID."""
        ctx1 = RequestIDManager.new_trace()
        id1 = ctx1.trace_id
        
        ctx2 = RequestIDManager.new_trace()
        id2 = ctx2.trace_id
        
        assert id1 != id2
    
    def test_start_span(self):
        """Test starting span through manager."""
        RequestIDManager.new_trace()
        
        span_id = RequestIDManager.start_span("operation")
        
        assert span_id is not None
    
    def test_span_lifecycle(self):
        """Test span start and end."""
        RequestIDManager.new_trace()
        
        span_id = RequestIDManager.start_span("operation")
        RequestIDManager.end_span(span_id)
        
        ctx = RequestIDManager.get_context()
        assert ctx.spans[span_id].end_time is not None
    
    def test_multiple_spans(self):
        """Test tracking multiple spans."""
        RequestIDManager.new_trace()
        
        span1 = RequestIDManager.start_span("op1")
        span2 = RequestIDManager.start_span("op2")
        
        ctx = RequestIDManager.get_context()
        
        assert len(ctx.spans) == 2
    
    def test_span_nesting(self):
        """Test nested span tracking."""
        RequestIDManager.new_trace()
        
        parent = RequestIDManager.start_span("parent")
        child = RequestIDManager.start_span("child")
        
        ctx = RequestIDManager.get_context()
        
        assert ctx.spans[child].parent_span_id == parent
