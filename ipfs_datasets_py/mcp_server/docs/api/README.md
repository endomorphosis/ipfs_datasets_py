# API Documentation

API reference documentation for MCP server tools and interfaces.

## Documents

### [tool-reference.md](./tool-reference.md)
Complete API reference for all MCP server tools. Includes:
- Tool categories and organization
- Tool schemas and parameters
- Return value specifications
- Usage examples

## Tool Categories

The MCP server provides 321+ tools across 49+ categories:
- Dataset tools (loading, saving, processing)
- Search tools (semantic, similarity, faceted)
- Logic tools (FOL, deontic, temporal-deontic)
- Processor tools (data transformation, multimedia)
- And many more...

## Core Module APIs

All MCP tools are thin wrappers around core modules. For programmatic use, import core modules directly:

```python
# Core modules (business logic)
from ipfs_datasets_py.core_operations import DatasetLoader, DatasetSaver
from ipfs_datasets_py.search.search_tools_api import semantic_search_from_parameters
from ipfs_datasets_py.logic.fol import convert_text_to_fol

# Use directly without MCP layer
loader = DatasetLoader()
result = await loader.load("data.json")
```

## Related Documentation

- [Thin Tool Architecture](../../THIN_TOOL_ARCHITECTURE.md) - Tool design principles
- [Tool Development Guide](../development/) - Creating new tools
