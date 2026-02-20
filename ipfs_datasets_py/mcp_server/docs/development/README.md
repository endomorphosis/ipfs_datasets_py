# Development Documentation

Documentation for developers working on the MCP server or creating new tools.

## Core Principles

All development should follow these principles:
1. **Business logic in core modules** — Never in tools
2. **Tools are thin wrappers** — Typically <100 lines
3. **Third-party reusable** — Core modules are independently usable
4. **CLI-MCP aligned** — Same core code for both interfaces

See [Thin Tool Architecture](../../THIN_TOOL_ARCHITECTURE.md) for comprehensive guidelines.

## Tool Development Guide

### Creating a New Tool

1. **Identify the core module** — Business logic goes in `ipfs_datasets_py/<domain>/`
2. **Choose the right category** — Browse `tools/` for the appropriate category folder
3. **Use a template** — See [tool-templates/](./tool-templates/) for starting points
4. **Write the thin wrapper** — <100 lines: validate → call core → format response
5. **Add tests** — Follow GIVEN-WHEN-THEN format in `tests/mcp/`
6. **Register the tool** — Add to `tool_registry.py`

### Tool Template (function-based, recommended)

```python
"""Tool: [name] — [one line description]."""
from typing import Any
from ..exceptions import MCPServerError


async def my_tool(param: str) -> dict[str, Any]:
    """[One-line description].

    Args:
        param: Description of parameter.

    Returns:
        dict with 'status', 'result' keys.

    Raises:
        MCPServerError: If operation fails.
    """
    from ipfs_datasets_py.core_operations import my_module

    try:
        result = await my_module.do_work(param)
        return {"status": "success", "result": result}
    except ValueError as exc:
        raise MCPServerError(f"Invalid input: {exc}") from exc
```

### Patterns Reference
See [tool-patterns.md](./tool-patterns.md) for:
- Function-based tools (72% of tools — recommended)
- Class-based tools (10% — legacy, still works)
- Stateful tools with engine classes (18% — for complex operations)

## Testing Guide

### Running Tests
```bash
# All MCP tests
pytest tests/mcp/ -v

# Unit tests only (fast feedback loop)
pytest tests/mcp/unit/ -v

# Integration tests
pytest tests/mcp/integration/ -v

# With coverage
pytest tests/mcp/ --cov=ipfs_datasets_py.mcp_server --cov-report=html
```

### Writing Tests

Follow the GIVEN-WHEN-THEN format:

```python
def test_my_tool_success():
    """Test that my_tool returns expected result."""
    # GIVEN: A valid input
    input_param = "valid_value"

    # WHEN: The tool is called
    result = my_tool(input_param)

    # THEN: The result is correct
    assert result["status"] == "success"
    assert "result" in result
```

### Test Coverage Requirements
- New tools must have ≥80% coverage
- Core server files maintain 85-90% coverage
- Use `pytest.mark.skip` (with reason) for tests requiring external services

### Test Templates
See [tool-templates/test_tool_template.py](./tool-templates/test_tool_template.py) for a complete test template.

## Debugging Guide

### Common Issues

**Import errors:**
```bash
pip install -e ".[dev,test]"
```

**Trio not available:**
```bash
pip install trio>=0.22.0
```

**SECRET_KEY not set (FastAPI):**
```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

**P2P features show as unavailable:**
This is normal when `ipfs_accelerate_py` is not installed. The server gracefully degrades to mock implementations.

### Logging Configuration

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# MCP server logger
logger = logging.getLogger("ipfs_datasets_py.mcp_server")
logger.setLevel(logging.DEBUG)
```

### Performance Profiling

```bash
# Profile a test run
pytest tests/mcp/ --profile -v

# Check schema cache hit rate
python -c "
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
m = HierarchicalToolManager()
m.discover_tools()
cat = m.get_category('dataset_tools')
print(cat.cache_info())
"
```

## Developer Resources

### Core Module APIs
All tools should import from core modules:
- `ipfs_datasets_py.core_operations` — Dataset management
- `ipfs_datasets_py.search` — Search functionality
- `ipfs_datasets_py.logic` — Logic processing
- `ipfs_datasets_py.processors` — Data processing
- `ipfs_datasets_py.knowledge_graphs` — Graph operations

### Tool Examples
See existing tools for patterns:
- `tools/dataset_tools/load_dataset.py` — Simple function-based tool
- `tools/search_tools/search_tools.py` — Class-based tools
- `tools/dataset_tools/text_to_fol.py` — Logic integration tool
- `tools/mcplusplus/taskqueue_engine.py` — Engine class (thick tool extracted)

## Related Documentation

- [Thin Tool Architecture](../../THIN_TOOL_ARCHITECTURE.md) — **Start here**
- [API Reference](../api/) — Tool API documentation
- [Architecture](../architecture/) — Technical design
- [Quick Start](../../QUICKSTART.md) — Server setup and running

