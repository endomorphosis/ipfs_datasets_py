# Core Operations Guide

## Overview

This guide documents the core_operations module, which provides reusable business logic for IPFS Datasets Python. Core operations are used by MCP tools, CLI commands, and direct Python imports.

## Table of Contents

1. [Introduction](#introduction)
2. [Architecture](#architecture)
3. [Core Modules](#core-modules)
4. [Usage Patterns](#usage-patterns)
5. [Development Guide](#development-guide)
6. [Testing](#testing)

## Introduction

### Purpose

The `core_operations` module centralizes business logic to:
- **Enable code reuse** across MCP, CLI, and Python API
- **Maintain single source of truth** for functionality
- **Simplify testing** with isolated, testable modules
- **Improve maintainability** by separating concerns

### Design Principles

1. **Separation of Concerns**: Business logic isolated from interface code
2. **Interface Agnostic**: Works with MCP, CLI, and Python imports
3. **Testable**: Each module independently testable
4. **Async First**: All operations support async/await
5. **Error Handling**: Standardized error responses

## Architecture

### Module Structure

```
ipfs_datasets_py/
└── core_operations/
    ├── __init__.py              # Module exports
    ├── dataset_loader.py        # Dataset loading operations
    ├── dataset_saver.py         # Dataset saving operations
    ├── dataset_converter.py     # Format conversion
    ├── ipfs_pinner.py           # IPFS pinning operations
    ├── ipfs_getter.py           # IPFS retrieval operations
    ├── knowledge_graph_manager.py  # Knowledge graph operations
    └── data_processor.py        # Data processing operations
```

### Thin Wrapper Pattern

MCP tools are thin wrappers around core operations:

```python
# MCP Tool (thin wrapper)
async def mcp_tool(**params):
    from ipfs_datasets_py.core_operations import CoreModule
    
    # 1. Validate inputs
    # 2. Call core operation
    # 3. Add MCP metadata
    # 4. Return result
    
    core = CoreModule()
    result = await core.operation(**params)
    return result

# CLI Command (uses same core)
def cli_command(**params):
    from ipfs_datasets_py.core_operations import CoreModule
    
    core = CoreModule()
    result = asyncio.run(core.operation(**params))
    print_result(result)

# Python API (direct import)
from ipfs_datasets_py.core_operations import CoreModule

core = CoreModule()
result = await core.operation(**params)
```

## Core Modules

### 1. DatasetLoader

**Purpose**: Load datasets from various sources

**Module**: `dataset_loader.py`

**Usage**:

```python
from ipfs_datasets_py.core_operations import DatasetLoader

loader = DatasetLoader()

# Load from Hugging Face
result = await loader.load_dataset(
    source="squad",
    split="train",
    streaming=False
)

# Load from local file
result = await loader.load_dataset(
    source="local",
    path="/path/to/dataset.json"
)

# Load from IPFS
result = await loader.load_dataset(
    source="ipfs",
    cid="QmHash..."
)
```

**Returns**:
```python
{
    "status": "success",
    "dataset_id": "squad_train_12345",
    "num_rows": 87599,
    "num_columns": 4,
    "splits": ["train"],
    "features": {...},
    "metadata": {...}
}
```

### 2. DatasetSaver

**Purpose**: Save datasets to various formats and destinations

**Module**: `dataset_saver.py`

**Usage**:

```python
from ipfs_datasets_py.core_operations import DatasetSaver

saver = DatasetSaver()

# Save to file
result = await saver.save_dataset(
    dataset_id="dataset_123",
    format="parquet",
    output_path="/path/to/output.parquet"
)

# Save to IPFS
result = await saver.save_dataset(
    dataset_id="dataset_123",
    format="json",
    destination="ipfs",
    pin=True
)
```

### 3. DataProcessor

**Purpose**: Process and transform data

**Module**: `data_processor.py`

**Operations**:

#### Text Chunking

```python
from ipfs_datasets_py.core_operations import DataProcessor

processor = DataProcessor()

# Chunk text with fixed size
result = await processor.chunk_text(
    text="Long document text...",
    strategy="fixed_size",
    chunk_size=1000,
    overlap=100,
    max_chunks=100
)

# Chunk by sentences
result = await processor.chunk_text(
    text="Document text...",
    strategy="sentence",
    chunk_size=5  # sentences per chunk
)

# Semantic chunking
result = await processor.chunk_text(
    text="Document text...",
    strategy="semantic",
    chunk_size=1000
)
```

**Chunking Strategies**:
- `fixed_size`: Fixed character count chunks
- `sentence`: Sentence-based chunking
- `paragraph`: Paragraph-based chunking
- `semantic`: Semantic similarity-based chunking

#### Data Transformation

```python
# Transform data
result = await processor.transform_data(
    data=[{"text": "  Test  ", "value": 100}],
    transformation="normalize_text"
)

# Supported transformations:
# - normalize_text: Trim whitespace, lowercase
# - extract_metadata: Extract metadata fields
# - filter_fields: Keep only specified fields
# - validate_schema: Validate against schema
# - clean_data: Remove nulls, duplicates
# - aggregate_data: Aggregate by fields
```

#### Format Conversion

```python
# Convert between formats
result = await processor.convert_format(
    data=[{"name": "test", "value": 100}],
    source_format="json",
    target_format="csv"
)

# Supported formats:
# - json, csv, parquet, jsonl, txt
```

### 4. IPFSPinner

**Purpose**: Pin content to IPFS

**Module**: `ipfs_pinner.py`

**Usage**:

```python
from ipfs_datasets_py.core_operations import IPFSPinner

pinner = IPFSPinner()

# Pin data
result = await pinner.pin_to_ipfs(
    data="Content to pin",
    pin_name="my-dataset",
    pin_service="local"  # or "pinata", "web3.storage"
)

# Returns:
# {
#     "status": "success",
#     "cid": "QmHash...",
#     "pin_name": "my-dataset",
#     "size_bytes": 1234,
#     "pin_service": "local"
# }
```

### 5. IPFSGetter

**Purpose**: Retrieve content from IPFS

**Module**: `ipfs_getter.py`

**Usage**:

```python
from ipfs_datasets_py.core_operations import IPFSGetter

getter = IPFSGetter()

# Get by CID
result = await getter.get_from_ipfs(
    cid="QmHash...",
    output_format="json",
    cache_locally=True
)
```

### 6. KnowledgeGraphManager

**Purpose**: Manage knowledge graphs

**Module**: `knowledge_graph_manager.py`

**Usage**:

```python
from ipfs_datasets_py.core_operations import KnowledgeGraphManager

manager = KnowledgeGraphManager()

# Create graph
result = await manager.create_graph(
    graph_id="my_graph",
    backend="neo4j"  # or "networkx", "rdflib"
)

# Add entity
result = await manager.add_entity(
    graph_id="my_graph",
    entity_type="Person",
    properties={"name": "Alice", "age": 30}
)

# Add relationship
result = await manager.add_relationship(
    graph_id="my_graph",
    from_entity="person_1",
    to_entity="person_2",
    relationship_type="KNOWS"
)

# Query graph
result = await manager.query_cypher(
    graph_id="my_graph",
    query="MATCH (p:Person) RETURN p"
)

# Hybrid search
result = await manager.search_hybrid(
    graph_id="my_graph",
    query="Find person named Alice",
    search_type="semantic",
    top_k=10
)
```

### 7. DatasetConverter

**Purpose**: Convert between dataset formats

**Module**: `dataset_converter.py`

**Usage**:

```python
from ipfs_datasets_py.core_operations import DatasetConverter

converter = DatasetConverter()

# Convert dataset
result = await converter.convert_dataset(
    dataset_id="dataset_123",
    target_format="parquet",
    compression="snappy"
)
```

## Usage Patterns

### Pattern 1: Error Handling

All core operations return standardized responses:

```python
result = await core_operation(**params)

if result["status"] == "success":
    # Process successful result
    data = result.get("result") or result.get("data")
    process_data(data)
elif result["status"] == "error":
    # Handle error
    error_message = result.get("message")
    logger.error(f"Operation failed: {error_message}")
```

### Pattern 2: Async/Await

All operations are async:

```python
# In async context
result = await processor.chunk_text(text="...")

# In sync context (CLI, scripts)
import asyncio
result = asyncio.run(processor.chunk_text(text="..."))
```

### Pattern 3: Parameter Validation

Core modules validate inputs:

```python
# Invalid input returns error
result = await processor.chunk_text(
    text="",  # Empty text
    chunk_size=-100  # Negative size
)

# Returns:
# {
#     "status": "error",
#     "message": "Text is required and must be a string"
# }
```

### Pattern 4: Graceful Degradation

Core modules handle missing dependencies:

```python
# If optional dependencies are missing, returns error or fallback
result = await loader.load_dataset(source="huggingface:squad")

# May return:
# {
#     "status": "error",
#     "message": "Hugging Face datasets not installed. Install with: pip install datasets"
# }
```

## Development Guide

### Creating a New Core Module

1. **Create module file**: `ipfs_datasets_py/core_operations/new_module.py`

2. **Define class**:

```python
"""
Description of the module.

Used by MCP tools, CLI commands, and Python imports.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class NewModule:
    """
    Brief description.
    
    This class provides reusable business logic for [functionality].
    """
    
    def __init__(self):
        # Initialize module
        pass
    
    async def operation(
        self, 
        param1: str,
        param2: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Operation description.
        
        Args:
            param1: Description
            param2: Description (optional)
            
        Returns:
            Dictionary containing:
            - status: "success" or "error"
            - result: Operation result
            - message: Status message
        """
        try:
            # Validate inputs
            if not param1:
                return {
                    "status": "error",
                    "message": "param1 is required"
                }
            
            # Perform operation
            result = self._internal_operation(param1, param2)
            
            return {
                "status": "success",
                "result": result,
                "message": "Operation completed successfully"
            }
            
        except Exception as e:
            logger.error(f"Operation failed: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def _internal_operation(self, param1, param2):
        """Internal implementation"""
        # Implementation details
        pass
```

3. **Add to __init__.py**:

```python
from .new_module import NewModule

__all__ = [
    # ... existing exports
    "NewModule",
]
```

4. **Create tests**: `tests/unit/core_operations/test_new_module.py`

5. **Create MCP wrapper**: `ipfs_datasets_py/mcp_server/tools/category/tool_name.py`

### Best Practices

1. **Input Validation**: Always validate inputs before processing
2. **Error Handling**: Use try/except and return standardized errors
3. **Async Functions**: All public methods should be async
4. **Type Hints**: Use type hints for all parameters and returns
5. **Docstrings**: Comprehensive docstrings with examples
6. **Logging**: Log important operations and errors
7. **Testing**: Write tests for all public methods
8. **Single Responsibility**: Each module has one clear purpose

## Testing

### Test Structure

```python
import pytest
from ipfs_datasets_py.core_operations import CoreModule


class TestCoreModuleAvailability:
    """Test availability and imports"""
    
    def test_given_core_operations_when_importing_then_succeeds(self):
        """
        GIVEN the core_operations module
        WHEN importing CoreModule
        THEN import should succeed
        """
        assert CoreModule is not None


class TestCoreModuleOperations:
    """Test core operations"""
    
    @pytest.mark.asyncio
    async def test_given_valid_input_when_calling_operation_then_returns_success(self):
        """
        GIVEN valid input parameters
        WHEN calling operation
        THEN it should return success status
        """
        module = CoreModule()
        result = await module.operation(param1="value")
        
        assert result["status"] == "success"
        assert "result" in result
```

### Running Tests

```bash
# Run all core_operations tests
pytest tests/unit/core_operations/ -v

# Run specific module tests
pytest tests/unit/core_operations/test_data_processor.py -v

# Run with coverage
pytest tests/unit/core_operations/ --cov=ipfs_datasets_py.core_operations --cov-report=html
```

## Additional Resources

- [MCP Tools Guide](./MCP_TOOLS_GUIDE.md)
- [Phase 9 Progress Report](./PHASE_9_PROGRESS_REPORT.md)
- [Enhancement 12 Completion](../ENHANCEMENT_12_MCP_COMPLETION.md)
- [Testing Guide](./TESTING_GUIDE.md)

---

**Document Version**: 1.0  
**Date**: 2026-02-17  
**Status**: Complete  
**Maintainer**: IPFS Datasets Python Team
