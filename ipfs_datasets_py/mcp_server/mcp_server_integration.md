# IPFS Datasets MCP Server Integration

This document outlines the integration between Claude's Toolbox MCP server and IPFS Datasets Python.

## Overview

The integration provides a Model Context Protocol (MCP) server for IPFS Datasets Python, enabling AI agents like Claude to interact with IPFS datasets through standardized tools. The server exposes various IPFS Datasets functionality as tools that can be used by AI agents.

## Implementation Status

### Completed
- Core server implementation
  - Server setup and configuration
  - Tool registration system
  - Integration with IPFS Kit Python (both direct and via MCP)
  - Error handling and logging
- Tool implementations
  - Dataset tools: load_dataset, save_dataset, process_dataset, convert_dataset_format
  - IPFS tools: pin_to_ipfs, get_from_ipfs
  - Vector tools: create_vector_index, search_vector_index
  - Graph tools: query_knowledge_graph
  - Audit tools: record_audit_event, generate_audit_report
  - Security tools: check_access_permission
  - Provenance tools: record_provenance
- Configuration system
  - YAML configuration support
  - Command-line arguments
  - Programmatic configuration
- Documentation
  - README with usage examples
  - Server configuration documentation
  - API reference documentation
- Examples and testing
  - Basic MCP client example
  - Comprehensive test script
  - Interactive demo script
  - Integration guide for Claude
- Deployment
  - Setup script for easy installation
  - Server launcher script

### Future Enhancements
- Performance optimization for large datasets
- Security and authentication enhancements
- Additional tool implementations
- Integration with more IPFS services
- CI/CD pipeline for automated testing
- Dashboard for monitoring server status

## Integration with IPFS Kit Python

The server supports two integration methods with IPFS Kit Python:

1. **Direct Integration**: Import and use IPFS Kit Python functions directly
2. **MCP Client Integration**: Connect to an existing IPFS Kit Python MCP server

This flexibility allows users to:
- Use IPFS Datasets and IPFS Kit Python together directly for maximum efficiency
- Connect to an existing IPFS Kit Python MCP server for distributed deployments

## Directory Structure

```
ipfs_datasets_py/mcp_server/
├── __init__.py           # Package initialization and exports
├── server.py             # Main server implementation
├── configs.py            # Configuration management
├── logger.py             # Logging utilities
├── start_server.sh       # Convenience script for starting the server
├── README.md             # Documentation
├── config/               # Configuration files
│   └── default_config.yaml  # Default configuration
└── tools/                # Tool implementations
    ├── __init__.py       # Tool registration
    ├── dataset_tools/    # Dataset-related tools
    ├── ipfs_tools/       # IPFS-related tools
    ├── vector_tools/     # Vector search tools
    ├── graph_tools/      # Graph processing tools
    ├── audit_tools/      # Audit logging tools
    ├── security_tools/   # Security-related tools
    └── provenance_tools/ # Data provenance tools
```

## Usage

```python
# Start the server
from ipfs_datasets_py.mcp_server import start_server
start_server(host="0.0.0.0", port=8000)

# Use with an existing IPFS Kit MCP server
start_server(host="0.0.0.0", port=8000, ipfs_kit_mcp_url="http://localhost:8001")

# Advanced configuration
from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPServer, load_config_from_yaml
configs = load_config_from_yaml("/path/to/config.yaml")
server = IPFSDatasetsMCPServer(configs)
server.register_tools()
await server.start()
```

## Client Usage

```python
from modelcontextprotocol.client import MCPClient

# Create client
client = MCPClient("http://localhost:8000")

# Get available tools
tools = await client.get_tool_list()

# Call a tool
result = await client.call_tool("load_dataset", {
    "source": "ipfs://bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
    "format": "json"
})
```
