# Processors Protocol Migration Guide

## Overview

This guide helps you migrate from the old `processors.protocol` (async) to the new `processors.core.protocol` (sync) interface.

**Status:** As of 2026-02-15, the old protocol is deprecated.  
**Timeline:** The old protocol will be removed in a future version.

---

## Why Migrate?

The new protocol offers:
- ✅ **Simpler API** - Synchronous methods are easier to use and debug
- ✅ **Better Performance** - No async overhead for CPU-bound tasks
- ✅ **Type Safety** - Better type hints and IDE support
- ✅ **Unified Interface** - Works seamlessly with UniversalProcessor
- ✅ **Easier Testing** - No need for async test fixtures

---

## Quick Comparison

| Feature | Old Protocol (Deprecated) | New Protocol (Current) |
|---------|---------------------------|------------------------|
| **Location** | `processors.protocol` | `processors.core.protocol` |
| **Async** | Yes (async/await) | No (synchronous) |
| **Input** | Raw input (str, Path) | ProcessingContext |
| **Methods** | `can_process()`, `process()`, `get_supported_types()` | `can_handle()`, `process()`, `get_capabilities()` |
| **KG Format** | `KnowledgeGraph` object | `Dict[str, Any]` |
| **Vectors** | `VectorStore` object | `List[List[float]]` |
| **Metadata** | `ProcessingMetadata` object | Dict in `metadata` field |

---

## Migration Steps

### Step 1: Update Imports

**OLD:**
```python
from ipfs_datasets_py.processors.protocol import (
    ProcessorProtocol,
    ProcessingResult,
    KnowledgeGraph,
    VectorStore,
    Entity,
    Relationship,
    ProcessingMetadata,
    ProcessingStatus,
    InputType
)
```

**NEW:**
```python
from ipfs_datasets_py.processors.core.protocol import (
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType
)
```

### Step 2: Remove Async

**OLD:**
```python
class MyProcessor:
    async def can_process(self, input_source):
        ...
    
    async def process(self, input_source, **options):
        result = await some_async_operation()
        ...
```

**NEW:**
```python
class MyProcessor:
    def can_handle(self, context: ProcessingContext) -> bool:
        ...
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        # If you need async operations, wrap them:
        # import asyncio
        # result = asyncio.run(some_async_operation())
        ...
```

### Step 3: Update Method Signatures

#### `can_process()` → `can_handle()`

**OLD:**
```python
async def can_process(self, input_source: Union[str, Path]) -> bool:
    input_str = str(input_source).lower()
    return input_str.endswith('.pdf')
```

**NEW:**
```python
def can_handle(self, context: ProcessingContext) -> bool:
    # Use context instead of raw input
    fmt = context.get_format()
    return fmt and fmt.lower() == 'pdf'
```

#### `process()` with ProcessingContext

**OLD:**
```python
async def process(self, input_source: Union[str, Path], **options) -> ProcessingResult:
    # Direct access to input
    content = await read_file(input_source)
    
    # Options passed as kwargs
    max_size = options.get('max_size', 1000)
    ...
```

**NEW:**
```python
def process(self, context: ProcessingContext) -> ProcessingResult:
    # Access via context
    content = read_file(context.source)
    
    # Options in context
    max_size = context.options.get('max_size', 1000)
    ...
```

#### `get_*()` → `get_capabilities()`

**OLD:**
```python
def get_supported_types(self) -> list[str]:
    return ["pdf", "file"]

def get_priority(self) -> int:
    return 10

def get_name(self) -> str:
    return "PDFProcessor"
```

**NEW:**
```python
def get_capabilities(self) -> Dict[str, Any]:
    return {
        "name": "PDFProcessor",
        "priority": 10,
        "formats": ["pdf"],
        "input_types": ["file", "url"],
        "outputs": ["knowledge_graph", "text"],
        "features": ["text_extraction", "entity_extraction"]
    }
```

### Step 4: Update Data Structures

#### Knowledge Graph

**OLD:**
```python
from ipfs_datasets_py.processors.protocol import KnowledgeGraph, Entity, Relationship

kg = KnowledgeGraph(source=source)
entity = Entity(
    id="doc_1",
    type="Document",
    label="My Document",
    properties={"key": "value"}
)
kg.add_entity(entity)

return ProcessingResult(
    knowledge_graph=kg,  # KnowledgeGraph object
    ...
)
```

**NEW:**
```python
# Use plain dictionaries
kg = {
    "entities": [
        {
            "id": "doc_1",
            "type": "Document",
            "label": "My Document",
            "properties": {"key": "value"}
        }
    ],
    "relationships": [],
    "source": source
}

return ProcessingResult(
    success=True,
    knowledge_graph=kg,  # Dict
    ...
)
```

#### Vectors

**OLD:**
```python
from ipfs_datasets_py.processors.protocol import VectorStore

vectors = VectorStore()
vectors.add_embedding("doc_1", [0.1, 0.2, 0.3])

return ProcessingResult(
    vectors=vectors,  # VectorStore object
    ...
)
```

**NEW:**
```python
# Use plain lists
vectors = [
    [0.1, 0.2, 0.3],  # First embedding
    [0.4, 0.5, 0.6],  # Second embedding
]

return ProcessingResult(
    success=True,
    vectors=vectors,  # List[List[float]]
    ...
)
```

#### ProcessingResult

**OLD:**
```python
from ipfs_datasets_py.processors.protocol import (
    ProcessingResult, ProcessingMetadata, ProcessingStatus
)

metadata = ProcessingMetadata(
    processor_name="MyProcessor",
    processor_version="1.0",
    input_type=InputType.FILE,
    status=ProcessingStatus.SUCCESS,
    processing_time_seconds=1.5
)

return ProcessingResult(
    knowledge_graph=kg,
    vectors=vectors,
    content={"text": "..."},
    metadata=metadata
)
```

**NEW:**
```python
from ipfs_datasets_py.processors.core.protocol import ProcessingResult

return ProcessingResult(
    success=True,
    knowledge_graph=kg,
    vectors=vectors,
    metadata={
        "processor": "MyProcessor",
        "processing_time": 1.5,
        "text_length": 1000,
        # Add any custom metadata
    },
    errors=[],  # List of error strings
    warnings=[]  # List of warning strings
)
```

---

## Complete Example

### OLD CODE (Deprecated)

```python
"""Old async processor using deprecated protocol."""

from ipfs_datasets_py.processors.protocol import (
    ProcessorProtocol,
    ProcessingResult,
    KnowledgeGraph,
    VectorStore,
    Entity,
    Relationship,
    ProcessingMetadata,
    ProcessingStatus,
    InputType
)
from pathlib import Path
from typing import Union
import time

class OldPDFProcessor:
    """Deprecated async processor."""
    
    async def can_process(self, input_source: Union[str, Path]) -> bool:
        input_str = str(input_source).lower()
        return input_str.endswith('.pdf')
    
    async def process(
        self, 
        input_source: Union[str, Path],
        **options
    ) -> ProcessingResult:
        start_time = time.time()
        
        # Create metadata
        metadata = ProcessingMetadata(
            processor_name="PDFProcessor",
            processor_version="1.0",
            input_type=InputType.FILE
        )
        
        try:
            # Process file
            text = f"Content from {input_source}"
            
            # Build knowledge graph
            kg = KnowledgeGraph(source=str(input_source))
            entity = Entity(
                id="doc_1",
                type="Document",
                label=Path(input_source).name,
                properties={"pages": 10}
            )
            kg.add_entity(entity)
            
            # Create vectors
            vectors = VectorStore()
            vectors.add_embedding("doc_1", [0.1, 0.2, 0.3])
            
            # Set metadata
            elapsed = time.time() - start_time
            metadata.processing_time_seconds = elapsed
            metadata.status = ProcessingStatus.SUCCESS
            
            return ProcessingResult(
                knowledge_graph=kg,
                vectors=vectors,
                content={"text": text},
                metadata=metadata
            )
        
        except Exception as e:
            elapsed = time.time() - start_time
            metadata.processing_time_seconds = elapsed
            metadata.status = ProcessingStatus.FAILED
            metadata.add_error(str(e))
            
            return ProcessingResult(
                knowledge_graph=KnowledgeGraph(source=str(input_source)),
                vectors=VectorStore(),
                content={"error": str(e)},
                metadata=metadata
            )
    
    def get_supported_types(self) -> list[str]:
        return ["pdf", "file"]
    
    def get_priority(self) -> int:
        return 10
    
    def get_name(self) -> str:
        return "PDFProcessor"
```

### NEW CODE (Recommended)

```python
"""New sync processor using core protocol."""

from ipfs_datasets_py.processors.core.protocol import (
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType
)
from pathlib import Path
from typing import Dict, Any, List
import time

class NewPDFProcessor:
    """Modern synchronous processor."""
    
    def __init__(self):
        """Initialize processor."""
        self._name = "PDFProcessor"
        self._priority = 10
    
    def can_handle(self, context: ProcessingContext) -> bool:
        """Check if we can handle this input."""
        # Use context methods
        fmt = context.get_format()
        if fmt and fmt.lower() == 'pdf':
            return True
        
        # Check input type
        if context.input_type == InputType.FILE:
            source_str = str(context.source).lower()
            return source_str.endswith('.pdf')
        
        return False
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        """Process the input."""
        start_time = time.time()
        source = context.source
        
        try:
            # Process file
            text = f"Content from {source}"
            
            # Build knowledge graph as dict
            kg = {
                "entities": [
                    {
                        "id": "doc_1",
                        "type": "Document",
                        "label": Path(source).name,
                        "properties": {"pages": 10}
                    }
                ],
                "relationships": [],
                "source": str(source)
            }
            
            # Create vectors as list
            vectors = [
                [0.1, 0.2, 0.3]  # Embedding for doc_1
            ]
            
            # Calculate elapsed time
            elapsed = time.time() - start_time
            
            return ProcessingResult(
                success=True,
                knowledge_graph=kg,
                vectors=vectors,
                metadata={
                    "processor": self._name,
                    "processing_time": elapsed,
                    "text_length": len(text),
                    "pages": 10
                }
            )
        
        except Exception as e:
            elapsed = time.time() - start_time
            
            return ProcessingResult(
                success=False,
                knowledge_graph={},
                vectors=[],
                metadata={
                    "processor": self._name,
                    "processing_time": elapsed
                },
                errors=[f"Processing failed: {str(e)}"]
            )
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Return processor capabilities."""
        return {
            "name": self._name,
            "priority": self._priority,
            "formats": ["pdf"],
            "input_types": ["file", "url"],
            "outputs": ["knowledge_graph", "vectors", "text"],
            "features": [
                "text_extraction",
                "entity_extraction",
                "document_metadata"
            ]
        }
```

---

## Usage with UniversalProcessor

The new protocol integrates seamlessly with UniversalProcessor:

```python
from ipfs_datasets_py.processors.core import UniversalProcessor, get_global_registry
from my_module import NewPDFProcessor

# Register your processor
registry = get_global_registry()
registry.register(
    processor=NewPDFProcessor(),
    priority=10,  # Also in get_capabilities()
    name="PDFProcessor"
)

# Use UniversalProcessor
processor = UniversalProcessor()
result = processor.process("document.pdf")

if result.success:
    print(f"Success! {len(result.knowledge_graph['entities'])} entities found")
else:
    print(f"Failed: {result.errors}")
```

---

## Testing

### OLD (Async)

```python
import pytest

@pytest.mark.asyncio
async def test_old_processor():
    processor = OldPDFProcessor()
    can_process = await processor.can_process("test.pdf")
    assert can_process
    
    result = await processor.process("test.pdf")
    assert result.metadata.status == ProcessingStatus.SUCCESS
```

### NEW (Sync)

```python
def test_new_processor():
    from ipfs_datasets_py.processors.core import ProcessingContext, InputType
    
    processor = NewPDFProcessor()
    
    context = ProcessingContext(
        input_type=InputType.FILE,
        source="test.pdf",
        metadata={"format": "pdf"}
    )
    
    can_handle = processor.can_handle(context)
    assert can_handle
    
    result = processor.process(context)
    assert result.success
```

---

## FAQ

### Q: Can I still use async operations inside my processor?

**A:** Yes! While the protocol methods are synchronous, you can still call async functions inside:

```python
import asyncio

def process(self, context: ProcessingContext) -> ProcessingResult:
    # Wrap async calls
    result = asyncio.run(my_async_function())
    # Or use run_until_complete
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(my_async_function())
    ...
```

### Q: What if my processor needs to call another async processor?

**A:** Use the same pattern - wrap it in `asyncio.run()`:

```python
def process(self, context: ProcessingContext) -> ProcessingResult:
    # Call async processor
    other_processor = SomeAsyncProcessor()
    result = asyncio.run(other_processor.process_async(context.source))
    ...
```

### Q: When will the old protocol be removed?

**A:** The old protocol is deprecated as of 2026-02-15. It will remain available with deprecation warnings for at least 3 months (until 2026-05-15), then will be removed in a major version update.

### Q: Do I need to update my existing code immediately?

**A:** No rush, but we recommend migrating soon:
- **Immediate:** You'll see deprecation warnings
- **Next 3 months:** Old protocol still works
- **After May 2026:** Old protocol will be removed

### Q: Can I use both protocols in the same codebase?

**A:** Yes, during the migration period you can use both. However, they are not compatible - don't mix them in the same processor class.

---

## Troubleshooting

### Issue: `ImportError: cannot import name 'ProcessingContext'`

**Solution:** Update your imports to use `processors.core.protocol`:
```python
from ipfs_datasets_py.processors.core.protocol import ProcessingContext
```

### Issue: `TypeError: can_handle() takes 2 positional arguments but 3 were given`

**Problem:** You're passing raw input instead of ProcessingContext  
**Solution:** Wrap your input in ProcessingContext:
```python
from ipfs_datasets_py.processors.core import ProcessingContext, InputType

context = ProcessingContext(
    input_type=InputType.FILE,
    source="your_input.pdf"
)
result = processor.can_handle(context)
```

### Issue: `AttributeError: 'dict' object has no attribute 'add_entity'`

**Problem:** Knowledge graph is now a dict, not a KnowledgeGraph object  
**Solution:** Use dict operations:
```python
# OLD
kg.add_entity(entity)

# NEW
kg["entities"].append(entity_dict)
```

---

## Support

- **Documentation:** See `PROCESSORS_*` files
- **Examples:** Check `examples/processors/` directory
- **Issues:** Report migration issues on GitHub

**Last Updated:** 2026-02-15
