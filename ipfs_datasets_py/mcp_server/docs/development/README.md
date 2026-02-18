# Development Documentation

Documentation for developers working on the MCP server or creating new tools.

## Core Principles

All development should follow these principles:
1. **Business logic in core modules** - Never in tools
2. **Tools are thin wrappers** - Typically <100 lines
3. **Third-party reusable** - Core modules are independently usable
4. **CLI-MCP aligned** - Same core code for both interfaces

See [Thin Tool Architecture](../../THIN_TOOL_ARCHITECTURE.md) for comprehensive guidelines.

## Coming Soon

### Tool Development Guide
- Creating new tools
- Tool development patterns
- Testing strategies
- Integration with core modules

### Testing Guide
- Running tests
- Writing new tests
- Test coverage requirements
- Integration testing

### Debugging Guide
- Common debugging scenarios
- Logging configuration
- Performance profiling
- P2P-specific debugging

## Developer Resources

### Core Module APIs
All tools should import from core modules:
- `ipfs_datasets_py.core_operations` - Dataset management
- `ipfs_datasets_py.search` - Search functionality
- `ipfs_datasets_py.logic` - Logic processing
- `ipfs_datasets_py.processors` - Data processing
- `ipfs_datasets_py.knowledge_graphs` - Graph operations

### Tool Examples
See existing tools for patterns:
- `tools/dataset_tools/load_dataset.py` - Simple function-based tool
- `tools/search_tools/search_tools.py` - Class-based tools
- `tools/dataset_tools/text_to_fol.py` - Logic integration tool

## Related Documentation

- [Thin Tool Architecture](../../THIN_TOOL_ARCHITECTURE.md) - **Start here**
- [API Reference](../api/) - Tool API documentation
- [Architecture](../architecture/) - Technical design
