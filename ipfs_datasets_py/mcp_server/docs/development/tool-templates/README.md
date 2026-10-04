# Tool Templates

This directory contains templates for creating MCP server tools following the thin wrapper pattern.

## Available Templates

### 1. simple_tool_template.py ⭐ RECOMMENDED
**Use for:** 90% of tools

The simple async function pattern with decorator. This is the recommended approach for most tools.

**Characteristics:**
- <100 lines of code
- Single async function
- `@wrap_function_as_tool` decorator
- Delegates to core modules
- Type hints throughout

**When to use:**
- Standard CRUD operations
- Search/query tools
- Data transformation
- Any stateless operation

### 2. multi_tool_template.py
**Use for:** Multiple related tools sharing core module

Multiple functions in one file, all using the same core module.

**Characteristics:**
- Multiple `@wrap_function_as_tool` decorated functions
- Shared core module import
- Related operations (e.g., search variants)
- Each tool is thin (<50 lines)

**When to use:**
- Related operations (search/semantic, search/vector, search/hybrid)
- Different modes of same operation
- Tools sharing configuration

### 3. stateful_tool_template.py (LEGACY)
**Use for:** Tools requiring persistent state (rare)

Class-based tool for maintaining state across calls.

**Characteristics:**
- Class-based implementation
- Lifecycle management (init, execute, cleanup)
- State tracking
- More verbose (~150 lines)

**When to use (ONLY):**
- Need persistent state between calls
- Resource management (connections, sessions)
- Complex lifecycle requirements

**Note:** Only use when absolutely necessary. Simple template works for 90% of cases.

### 4. test_tool_template.py
**Use for:** Testing your tools

Comprehensive test template with multiple test types.

**Includes:**
- Success/error case tests
- Thinness validation
- Core import checking
- CLI-MCP alignment tests
- Performance tests (<10ms overhead)

## Quick Start

### Creating a New Tool

1. **Copy the appropriate template:**
   ```bash
   cp simple_tool_template.py ../tools/your_category/your_tool.py
   ```

2. **Replace placeholders:**
   - `YourCoreClass` → Your actual core class
   - `your_tool_name` → Your tool name
   - `your_category` → Category (dataset, search, graph, etc.)
   - `your_method` → Core module method name

3. **Implement core logic in core modules:**
   ```python
   # ipfs_datasets_py/your_core_module.py
   class YourCoreClass:
       async def your_method(self, param, **options):
           # ALL business logic goes here
           return result
   ```

4. **Test your tool:**
   ```bash
   cp test_tool_template.py ../tests/test_your_tool.py
   pytest tests/test_your_tool.py
   ```

### Tool Development Checklist

- [ ] Tool is <100 lines (or <150 with documentation)
- [ ] All business logic in core modules
- [ ] Tool only does orchestration
- [ ] Proper error handling
- [ ] Type hints for all parameters
- [ ] Docstring with examples
- [ ] CLI wrapper for alignment (optional)
- [ ] Tests written and passing
- [ ] Performance overhead <10ms

## Architecture Principles

### Thin Wrapper Pattern

```
MCP Tool (orchestration)
    ↓
Core Module (business logic)
    ↓
Third-party libraries
```

**Tool responsibilities:**
- Parameter validation
- Error handling
- Response formatting
- Core module dispatch

**Core module responsibilities:**
- Business logic
- Data processing
- Algorithm implementation
- Integration with libraries

### CLI-MCP Alignment

Both interfaces use the same core modules:

```
CLI → thin wrapper → CORE MODULE ← thin wrapper ← MCP Tool
```

**Benefits:**
- Same logic, different interface
- Easy to maintain
- Third-party reusable
- Consistent behavior

## Tool Naming Convention

### Nested Structure (Phase 3)

Tools are organized hierarchically:

```
category/operation

Examples:
- dataset/load (was load_dataset)
- dataset/save (was save_dataset)
- search/semantic (was semantic_search)
- graph/query (was graph_query)
```

**Benefits:**
- Reduces context window ~90%
- Better organization
- Familiar CLI-style UX
- Easy discovery

### File Organization

```
tools/
├── dataset_tools/
│   ├── load.py          # dataset/load
│   ├── save.py          # dataset/save
│   └── process.py       # dataset/process
├── search_tools/
│   ├── semantic.py      # search/semantic
│   └── vector.py        # search/vector
└── graph_tools/
    ├── query.py         # graph/query
    └── visualize.py     # graph/visualize
```

## Best Practices

### DO ✅

- Keep tools <100 lines
- Import from core modules
- Use type hints
- Handle errors gracefully
- Write comprehensive tests
- Include CLI wrapper for alignment
- Use async/await consistently
- Log errors with context

### DON'T ❌

- Implement business logic in tools
- Create thick tools (>150 lines)
- Duplicate code from core modules
- Skip error handling
- Ignore type hints
- Mix sync and async code
- Forget documentation
- Skip testing

## Examples from Codebase

### Good Example: load_dataset.py (84 lines)

```python
from ipfs_datasets_py.core_operations import DatasetLoader

async def load_dataset(source: str, ...) -> Dict[str, Any]:
    loader = DatasetLoader()  # Core module
    result = await loader.load(source, ...)  # Delegate
    return result
```

**Why it's good:**
- Thin (84 lines)
- Imports from core
- Simple delegation
- Proper error handling

### Bad Example: deontological_reasoning_tools.py (595 lines)

**Why it's bad:**
- Too thick (595 lines)
- Business logic embedded
- Parsing logic in tool
- Should extract to logic module

**Fix:**
```python
# Move parsing to ipfs_datasets_py/logic/deontic/parser.py
# Keep only orchestration in tool (should be ~50 lines)
```

## Migration Guide

See `tool-migration-guide.md` for detailed instructions on:
- Converting legacy tools to new pattern
- Extracting business logic to core
- Refactoring thick tools
- Testing migration

## Support

Questions? See:
- `THIN_TOOL_ARCHITECTURE.md` - Architecture overview
- `tool-patterns.md` - Pattern documentation
- `tool-migration-guide.md` - Migration guide

