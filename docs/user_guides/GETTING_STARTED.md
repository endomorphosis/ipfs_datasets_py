# Getting Started with ipfs_datasets_py

Quick start guide for using ipfs_datasets_py after the MCP server refactoring.

## Installation

```bash
# Basic installation
pip install ipfs_datasets_py

# With all features
pip install -e ".[all]"

# Just for testing
pip install -e ".[test]"
```

## Three Ways to Use

### 1. Python Imports (Recommended)

```python
from ipfs_datasets_py.core_operations import DatasetLoader, IPFSPinner, KnowledgeGraphManager
import asyncio

async def main():
    # Load dataset
    loader = DatasetLoader()
    data = await loader.load("squad")
    
    # Pin to IPFS
    pinner = IPFSPinner()
    result = await pinner.pin({"my": "data"})
    print(f"CID: {result['cid']}")
    
    # Knowledge graph
    kg = KnowledgeGraphManager()
    await kg.create()
    await kg.add_entity("p1", "Person", {"name": "Alice"})

asyncio.run(main())
```

### 2. CLI Commands

```bash
# Dataset operations
ipfs-datasets dataset load squad

# IPFS operations
ipfs-datasets ipfs pin --content "data"

# Graph operations
ipfs-datasets graph create
ipfs-datasets graph add-entity --id p1 --type Person --props '{"name":"Alice"}'
ipfs-datasets graph query --cypher "MATCH (n) RETURN n LIMIT 10"
```

### 3. MCP Server Tools

```python
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

manager = HierarchicalToolManager()

# List categories
categories = manager.list_categories()

# List tools in category
tools = manager.list_tools('graph_tools')

# Execute tool
result = await manager.dispatch_tool(
    'graph_tools',
    'graph_add_entity',
    {'entity_id': 'p1', 'entity_type': 'Person', 'properties': {'name': 'Alice'}}
)
```

## Key Features

- **99% Context Window Reduction**: 4 meta-tools instead of 347
- **Code Reusability**: Same logic for CLI, MCP, Python
- **Knowledge Graphs**: Full CRUD + transactions + indexes
- **IPFS Integration**: Multiple backend support
- **Dataset Loading**: HuggingFace, local files, URLs

## Next Steps

- [API Reference](../api/CORE_OPERATIONS_API.md)
- [CLI Usage Guide](CLI_USAGE.md)
- [Developer Guide](../developer_guides/CREATING_TOOLS.md)
- [Migration Guide](../migration_guides/FLAT_TO_HIERARCHICAL.md)
