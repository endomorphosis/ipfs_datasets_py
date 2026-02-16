# Processors Architecture

**Last Updated:** 2026-02-16  
**Status:** Production (Phase 5 Complete)

---

## Overview

The processors module uses a **5-layer architecture** with clear dependency rules to maintain modularity, testability, and scalability.

---

## Architecture Layers

### Layer 1: CORE

**Location:** `ipfs_datasets_py/processors/core/`

**Purpose:** Core protocols, registry, and universal processor

**Dependencies:** None (only stdlib, anyio, typing, external libs)

**Key Files:**
- `protocol.py` - ProcessorProtocol interface
- `registry.py` - Processor registration system  
- `universal_processor.py` - Unified entry point
- `input_detector.py` - Input type detection
- `processor_registry.py` - Legacy registry (transitioning)

**Design Principle:** Core defines interfaces and contracts. It should never import from other internal layers.

---

### Layer 2: INFRASTRUCTURE

**Location:** `ipfs_datasets_py/processors/infrastructure/`

**Purpose:** Cross-cutting concerns (monitoring, caching, error handling)

**Dependencies:** CORE only

**Key Files:**
- `monitoring.py` - Health monitoring and metrics
- `profiling.py` - Performance profiling
- `error_handling.py` - Retry logic, circuit breakers
- `caching.py` - Smart caching system
- `debug_tools.py` - Debugging utilities
- `cli.py` - Command-line interface

**Design Principle:** Infrastructure provides utilities that any layer can use, but doesn't depend on domain logic.

---

### Layer 3: ADAPTERS

**Location:** `ipfs_datasets_py/processors/adapters/`

**Purpose:** Adapt specialized processors to ProcessorProtocol

**Dependencies:** CORE + SPECIALIZED

**Key Files:**
- `pdf_adapter.py` - PDF processor adapter
- `graphrag_adapter.py` - GraphRAG adapter
- `batch_adapter.py` - Batch processing adapter
- `multimedia_adapter.py` - Media processing adapter
- `ipfs_adapter.py` - IPFS processor adapter

**Design Principle:** Adapters standardize interfaces. They wrap specialized implementations to match ProcessorProtocol.

**Pattern:**
```python
from ipfs_datasets_py.processors.core.protocol import ProcessorProtocol
from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor

class PDFAdapter(ProcessorProtocol):
    """Adapts PDFProcessor to ProcessorProtocol."""
    
    def __init__(self):
        self.pdf_processor = PDFProcessor()
    
    async def process(self, input_data):
        # Transform input/output to match protocol
        result = await self.pdf_processor.process_pdf(input_data)
        return self._to_processing_result(result)
    
    def can_handle(self, input_data):
        return input_data.endswith('.pdf')
```

---

### Layer 4: SPECIALIZED

**Location:** `ipfs_datasets_py/processors/specialized/`

**Purpose:** Format-specific and task-specific processors

**Dependencies:** CORE + INFRASTRUCTURE

**Subdirectories:**
- `pdf/` - PDF processing (OCR, text extraction, GraphRAG)
- `graphrag/` - Knowledge graph extraction
- `batch/` - Batch processing
- `media/` - Audio/video processing
- `multimodal/` - Multi-format processing
- `web_archive/` - Web archiving (Common Crawl, Wayback)

**Design Principle:** Specialized processors are domain experts. They focus on specific file types or tasks.

**Pattern:**
```python
from ipfs_datasets_py.processors.core.protocol import ProcessorProtocol
from ipfs_datasets_py.processors.infrastructure import monitoring

@monitoring.monitor_performance
class PDFProcessor(ProcessorProtocol):
    """Specialized PDF processor."""
    
    async def process(self, pdf_path):
        # Domain-specific logic
        text = await self.extract_text(pdf_path)
        entities = await self.extract_entities(text)
        return ProcessingResult(text=text, entities=entities)
    
    def can_handle(self, input_data):
        return input_data.endswith('.pdf')
```

---

### Layer 5: DOMAINS

**Location:** `ipfs_datasets_py/processors/domains/`

**Purpose:** Industry-specific processors (patents, geospatial, legal)

**Dependencies:** CORE + SPECIALIZED + INFRASTRUCTURE (all layers)

**Subdirectories:**
- `patent/` - Patent document processing
- `geospatial/` - Geographic data processing
- `ml/` - Machine learning pipelines
- `legal/` - Legal document scraping and processing

**Design Principle:** Domains compose multiple specialized processors for industry-specific workflows.

**Pattern:**
```python
from ipfs_datasets_py.processors.core.protocol import ProcessorProtocol
from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
from ipfs_datasets_py.processors.specialized.graphrag import GraphRAGProcessor

class PatentProcessor(ProcessorProtocol):
    """Domain-specific processor for patents."""
    
    def __init__(self):
        self.pdf_processor = PDFProcessor()
        self.graphrag_processor = GraphRAGProcessor()
    
    async def process(self, patent_pdf):
        # Domain workflow
        text = await self.pdf_processor.process(patent_pdf)
        claims = self.extract_claims(text)
        graph = await self.graphrag_processor.process(claims)
        return PatentResult(claims=claims, graph=graph)
```

---

## Dependency Rules

### Visual Dependency Graph

```
┌──────────────┐
│   DOMAINS    │  ← Can import from all layers
└──────┬───────┘
       │
       ↓
┌──────────────┐     ┌──────────────┐
│  SPECIALIZED │ ←── │   ADAPTERS   │
└──────┬───────┘     └──────┬───────┘
       │                    │
       ↓                    ↓
┌──────────────────────────────────┐
│    CORE    ←   INFRASTRUCTURE    │
└──────────────────────────────────┘
```

### Dependency Matrix

| Layer | Can Import From |
|-------|----------------|
| CORE | Nothing (only stdlib, anyio, typing, external libs) |
| INFRASTRUCTURE | CORE |
| ADAPTERS | CORE + SPECIALIZED |
| SPECIALIZED | CORE + INFRASTRUCTURE |
| DOMAINS | CORE + INFRASTRUCTURE + SPECIALIZED + ADAPTERS |

### Rules Enforcement

Architecture rules are enforced by tests in `tests/architecture/test_processor_architecture.py`:

```bash
# Run architecture validation
pytest tests/architecture/ -v -m architecture
```

---

## Design Patterns

### 1. ProcessorProtocol Pattern

All processors should implement `ProcessorProtocol`:

```python
from ipfs_datasets_py.processors.core.protocol import ProcessorProtocol

class MyProcessor(ProcessorProtocol):
    async def process(self, input_data):
        """Process input and return ProcessingResult."""
        pass
    
    def can_handle(self, input_data):
        """Check if processor can handle this input."""
        pass
```

### 2. Registry Pattern

Processors register with the global registry:

```python
from ipfs_datasets_py.processors.core.registry import get_global_registry

registry = get_global_registry()
registry.register(MyProcessor(), priority=10)
```

### 3. Adapter Pattern

Adapt existing processors to ProcessorProtocol:

```python
class MyAdapter(ProcessorProtocol):
    def __init__(self, legacy_processor):
        self.processor = legacy_processor
    
    async def process(self, input_data):
        result = self.processor.old_method(input_data)
        return self._convert_to_protocol(result)
```

### 4. Monitoring Decorator

Use infrastructure monitoring:

```python
from ipfs_datasets_py.processors.infrastructure.monitoring import monitor_performance

@monitor_performance
async def expensive_operation():
    # Automatically tracked
    pass
```

---

## Async Framework: AnyIO

**All async code uses anyio** (not asyncio) for consistency and better structured concurrency.

### Common Patterns

```python
import anyio

# Sleep
await anyio.sleep(1.0)

# Task groups (structured concurrency)
async with anyio.create_task_group() as tg:
    tg.start_soon(task1)
    tg.start_soon(task2)

# Timeouts
with anyio.fail_after(30):
    result = await long_operation()

# Concurrency limiting
limiter = anyio.CapacityLimiter(10)
async with limiter:
    await process_item()
```

**Migration Guide:** See `PROCESSORS_ANYIO_QUICK_REFERENCE.md`

---

## Testing Strategy

### Unit Tests

Test individual processors in isolation:

```python
@pytest.mark.anyio
async def test_pdf_processor():
    processor = PDFProcessor()
    result = await processor.process("test.pdf")
    assert result.status == ProcessingStatus.SUCCESS
```

### Integration Tests

Test layer interactions:

```python
@pytest.mark.anyio
async def test_adapter_integration():
    adapter = PDFAdapter()
    processor = UniversalProcessor()
    processor.registry.register(adapter)
    
    result = await processor.process("document.pdf")
    assert result is not None
```

### Architecture Tests

Validate dependency rules:

```python
@pytest.mark.architecture
def test_core_no_internal_dependencies():
    # Fails if core imports from other layers
    pass
```

---

## Migration Guide

### From Old Structure

**Old (deprecated):**
```python
from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
processor = PDFProcessor()
```

**New (recommended):**
```python
from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
processor = PDFProcessor()
```

**Or use UniversalProcessor:**
```python
from ipfs_datasets_py.processors import UniversalProcessor

processor = UniversalProcessor()
result = await processor.process("document.pdf")  # Auto-routes to correct processor
```

---

## Best Practices

### 1. Keep Layers Decoupled
- Don't violate dependency rules
- Use interfaces (ProcessorProtocol) not implementations
- Pass dependencies via constructor

### 2. Use Anyio for All Async
- Replace asyncio with anyio
- Use task groups for structured concurrency
- Use CapacityLimiter for rate limiting

### 3. Register Processors
- Register all processors with registry
- Set appropriate priority
- Implement can_handle() correctly

### 4. Add Monitoring
- Use @monitor_performance decorator
- Log important events
- Track errors with error_handling

### 5. Write Tests
- Unit tests for each processor
- Integration tests for workflows
- Architecture tests for dependencies

---

## Adding a New Processor

1. **Choose Layer** - specialized, domains, or adapters?
2. **Implement Protocol** - extend ProcessorProtocol
3. **Add Tests** - unit + integration
4. **Register** - add to registry
5. **Document** - update this doc

**Example:**
```python
# 1. Create processor (specialized layer)
# ipfs_datasets_py/processors/specialized/my_format/processor.py

from ipfs_datasets_py.processors.core.protocol import ProcessorProtocol

class MyFormatProcessor(ProcessorProtocol):
    async def process(self, input_data):
        # Implementation
        return ProcessingResult(...)
    
    def can_handle(self, input_data):
        return input_data.endswith('.myformat')

# 2. Create adapter
# ipfs_datasets_py/processors/adapters/my_format_adapter.py

class MyFormatAdapter(ProcessorProtocol):
    def __init__(self):
        self.processor = MyFormatProcessor()
    
    async def process(self, input_data):
        return await self.processor.process(input_data)
    
    def can_handle(self, input_data):
        return self.processor.can_handle(input_data)

# 3. Register (in universal_processor.py _initialize_processors)
try:
    from .adapters.my_format_adapter import MyFormatAdapter
    self.registry.register(MyFormatAdapter(), priority=10)
except ImportError:
    pass
```

---

## Troubleshooting

### Import Errors

**Problem:** `ImportError: cannot import name 'X'`

**Solution:** Check layer dependencies. You may be importing from a forbidden layer.

### Circular Dependencies

**Problem:** `ImportError: cannot import ... (circular import)`

**Solution:** 
- Use lazy imports (import inside functions)
- Use TYPE_CHECKING for type hints
- Refactor to follow layer rules

### Architecture Test Failures

**Problem:** `test_core_no_internal_dependencies` fails

**Solution:** Remove the forbidden import or move code to correct layer.

---

## References

- **Protocol:** `ipfs_datasets_py/processors/core/protocol.py`
- **Registry:** `ipfs_datasets_py/processors/core/registry.py`
- **Tests:** `tests/architecture/test_processor_architecture.py`
- **Migration:** `PROCESSORS_REFACTORING_PLAN_2026_02_16.md`
- **AnyIO Guide:** `PROCESSORS_ANYIO_QUICK_REFERENCE.md`

---

**Questions?** See `docs/` or open a GitHub issue with tag `architecture:processors`
