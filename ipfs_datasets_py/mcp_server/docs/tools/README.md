# Tool-Specific Documentation

This directory is reserved for tool-specific documentation and guides.

## Coming Soon

Individual tool documentation will be organized here by category:
- Legal dataset tools guide
- Finance data tools guide
- Media processing tools guide
- And more...

## Current Tool Documentation

For now, tool documentation is available in:
- [API Reference](../api/tool-reference.md) - Complete API documentation for all tools
- [Tool Categories](../../tools/) - Source code and inline documentation

## Tool Discovery

To discover available tools:

```bash
# Using CLI
ipfs-datasets tools list-categories
ipfs-datasets tools list --category dataset_tools

# Programmatically
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

manager = HierarchicalToolManager()
categories = manager.list_categories()
tools = manager.list_tools("dataset_tools")
```

## Related Documentation

- [Thin Tool Architecture](../../THIN_TOOL_ARCHITECTURE.md) - Tool design principles
- [API Reference](../api/tool-reference.md) - Complete API documentation
- [Development Guide](../development/) - Creating new tools
