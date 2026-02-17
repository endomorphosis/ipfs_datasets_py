# IPFS Datasets MCP Server

This package provides a Model Context Protocol (MCP) server implementation for IPFS Datasets Python, enabling AI models like Claude to interact with IPFS datasets through standardized tools.

## 🚀 MCP++ Integration Project (2026-02-17)

We are actively working on a comprehensive improvement plan to integrate advanced P2P capabilities from the [ipfs_accelerate_py MCP++ module](https://github.com/endomorphosis/ipfs_accelerate_py/tree/main/ipfs_accelerate_py/mcplusplus_module). This will bring:

- **50-70% reduction** in P2P operation latency (from ~200ms to <100ms)
- **20+ new P2P tools** (workflow scheduler, task queue, peer management)
- **Dual-runtime architecture** (FastAPI + Trio) for optimal performance
- **Full backward compatibility** with existing tools

**📖 Documentation:**
- [**MCP Improvement Plan**](./MCP_IMPROVEMENT_PLAN.md) - Complete roadmap (24KB)
- [**Architecture Integration**](./ARCHITECTURE_INTEGRATION.md) - Technical design (28KB)
- [**Implementation Checklist**](./IMPLEMENTATION_CHECKLIST.md) - Task breakdown (15KB)
- [**Quick Start Guide**](./QUICK_START_GUIDE.md) - Developer onboarding (14KB)

## Features

- **MCP Server**: Full Model Context Protocol server implementation
- **Comprehensive Tools**: Access to all IPFS Datasets functionality as MCP tools (370+ tools, 73 categories)
- **Dual Integration**: Support for both direct IPFS Kit usage and MCP-based integration
- **P2P Capabilities**: Basic P2P service integration (advanced features coming with MCP++)
- **Configuration Options**: Flexible configuration via command line, YAML files, or Python
- **Python Client**: Easy-to-use Python client for programmatic access

## Installation

The MCP server is included in the IPFS Datasets Python package. Make sure you have installed the package:

```bash
pip install ipfs-datasets-py
```

For development installation:

```bash
# Clone the repository
git clone https://github.com/yourusername/ipfs_datasets_py.git
cd ipfs_datasets_py

# Install with development dependencies
pip install -e ".[dev]"

# Run the setup script
./ipfs_datasets_py/mcp_server/setup.sh
```

## Quick Start

Start the server with default settings:

```python
from ipfs_datasets_py.mcp_server import start_server
start_server(host="0.0.0.0", port=8000)
```

Or run the provided start script:

```bash
./ipfs_datasets_py/mcp_server/start_server.sh
```

### Using the Python Client

```python
import asyncio
from ipfs_datasets_py.mcp_server.client import IPFSDatasetsMCPClient

async def main():
    # Connect to the server
    client = IPFSDatasetsMCPClient("http://localhost:8000")
    
    # Load a dataset
    dataset_info = await client.load_dataset("/path/to/dataset.json")
    
    # Process the dataset
    processed_info = await client.process_dataset(
        dataset_info["dataset_id"],
        [
            {"type": "filter", "column": "value", "condition": ">", "value": 50}
        ]
    )
    
    # Save the processed dataset
    await client.save_dataset(
        processed_info["dataset_id"],
        "/path/to/output.csv",
        "csv"
    )

# Run the async function
asyncio.run(main())
```

## Configuration

The server can be configured in several ways:

### Command Line Arguments

```bash
./start_server.sh --host 127.0.0.1 --port 5000 --ipfs-kit-mcp http://localhost:8001 --config /path/to/config.yaml
```

### Configuration File

Create a YAML configuration file:

```yaml
# Server settings
server:
  host: 127.0.0.1
  port: 5000

# IPFS Kit integration
ipfs_kit:
  integration: mcp
  mcp_url: http://localhost:8001
```

### Programmatic Configuration

```python
from ipfs_datasets_py.mcp_server import start_server, configs

# Update configuration
configs.host = "127.0.0.1"
configs.port = 5000
configs.ipfs_kit_integration = "mcp"
configs.ipfs_kit_mcp_url = "http://localhost:8001"

# Start server with updated configs
start_server()
```

## Integration with IPFS Kit Python

The server can integrate with IPFS Kit Python in two ways:

1. **Direct Integration**: Import and use IPFS Kit Python functions directly
2. **MCP Client Integration**: Connect to an existing IPFS Kit Python MCP server

### Direct Integration

This is the default mode. The server will import IPFS Kit Python functions directly.

```yaml
ipfs_kit:
  integration: direct
```

### MCP Client Integration

In this mode, the server will connect to an existing IPFS Kit Python MCP server.

```yaml
ipfs_kit:
  integration: mcp
  mcp_url: http://localhost:8001
```

## Available Tools

The server exposes the following tools:

### Dataset Tools
- `load_dataset`: Load a dataset from a source
- `save_dataset`: Save a dataset to a destination
- `process_dataset`: Process a dataset with transformations
- `convert_dataset_format`: Convert a dataset to a different format

### IPFS Tools
- `pin_to_ipfs`: Pin content to IPFS
- `get_from_ipfs`: Get content from IPFS
- `convert_to_car`: Convert content to a CAR file
- `unixfs_operations`: Perform UnixFS operations on IPFS content

### Vector Tools
- (Vector tools will be documented here)

### Graph Tools
- (Graph tools will be documented here)

### Audit Tools
- (Audit tools will be documented here)

### Security Tools
- (Security tools will be documented here)

### Provenance Tools
- (Provenance tools will be documented here)

## Custom Server Configuration

For advanced use cases, you can create and configure your own server instance:

```python
from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPServer
import asyncio

async def run_custom_server():
    # Create server instance
    server = IPFSDatasetsMCPServer()
    
    # Register tools
    server.register_tools()
    
    # Register IPFS Kit tools
    server.register_ipfs_kit_tools(ipfs_kit_mcp_url="http://localhost:8001")
    
    # Start server
    await server.start(host="127.0.0.1", port=5000)

# Run custom server
asyncio.run(run_custom_server())
```
