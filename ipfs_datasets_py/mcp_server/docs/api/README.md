# API Documentation

API reference documentation for MCP server tools and interfaces.

## Documents

### [tool-reference.md](./tool-reference.md)
Complete API reference for all MCP server tools (~407 callable functions across 51 categories). Includes:
- Tool categories and organization
- Tool schemas and parameters
- Return value specifications
- Usage examples
- MCP++ integration components (UCAN, Event DAG, PubSub, Compliance)

## Tool Categories

The MCP server provides ~407 tool functions across 51 categories:
- Dataset tools (loading, saving, processing, text-to-FOL, legal-to-deontic)
- Graph tools (knowledge graphs, Cypher, GraphQL, visualization, KG completion, explainability)
- Logic tools (FOL, TDFOL, CEC/DCEC theorem proving, deontic, temporal-deontic)
- Media tools (FFmpeg convert/mux/stream/edit/batch, yt-dlp)
- Web archive tools (Common Crawl, Wayback Machine, Brave/Google/GitHub/HuggingFace search)
- Legal dataset tools (US Code, Federal Register, RECAP, CourtListener, municipal codes)
- And 45 more categories...

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
