# MCP Server Integration for IPFS Datasets Python

This document outlines the integration of the Model Context Protocol (MCP) server with IPFS Datasets Python, allowing AI assistants like Claude to interact directly with decentralized data processing capabilities.

## Overview

The integration brings the claudes_toolbox MCP server functionality into the ipfs_datasets_py package, exposing its features as tools that can be accessed through the MCP protocol. This enables AI assistants to:

- Load, process, and save datasets in various formats
- Interact with IPFS for decentralized storage
- Perform vector search and similarity operations
- Extract and query knowledge graphs
- Utilize security, governance, and audit logging features

## Architecture

```
ipfs_datasets_py/
├── ...existing components...
└── mcp_server/
    ├── __init__.py
    ├── server.py           # Main MCP server adapted from claudes_toolbox
    ├── configs.py          # Configuration handling
    ├── logger.py           # Logging functionality
    └── tools/
        ├── __init__.py
        ├── dataset_tools/  # Tools for dataset operations
        ├── ipfs_tools/     # Tools for IPFS operations  
        ├── vector_tools/   # Tools for vector operations
        ├── graph_tools/    # Tools for graph operations
        ├── audit_tools/    # Tools for audit functionality
        └── security_tools/ # Tools for security features
```

## Installation

To use the MCP server functionality, install with the MCP extras:

```bash
pip install ipfs-datasets-py[mcp]
```

## Starting the Server

There are multiple ways to start the MCP server:

### From Command Line

```bash
# Start with stdio transport (default)
python -m ipfs_datasets_py.mcp_server.server

# Start with HTTP transport
python -m ipfs_datasets_py.mcp_server.server --transport http --port 5000
```

### From Python Code

```python
from ipfs_datasets_py import start_mcp_server

# Start with default settings (stdio transport)
start_mcp_server()

# Or with custom settings
start_mcp_server(
    config_path="config.yaml", 
    host="0.0.0.0", 
    port=8000, 
    transport="http"
)
```

## Available Tools

The MCP server exposes the following tools:

### Dataset Tools

| Tool Name | Description |
|-----------|-------------|
| `load_dataset` | Load a dataset from a source or IPFS CID |
| `save_dataset` | Save a dataset to a specified format |
| `process_dataset` | Apply operations to a dataset |
| `convert_dataset_format` | Convert dataset between formats (Parquet, CAR, etc.) |

### IPFS Tools

| Tool Name | Description |
|-----------|-------------|
| `pin_to_ipfs` | Pin content to IPFS |
| `get_from_ipfs` | Get content from IPFS |
| `convert_to_car` | Convert data to CAR format |
| `unixfs_operations` | Perform UnixFS operations |

### Vector Tools

| Tool Name | Description |
|-----------|-------------|
| `vector_search` | Search for similar vectors in an index |
| `create_vector_index` | Create a new vector search index |
| `add_vectors` | Add vectors to an existing index |
| `visualize_vectors` | Generate visualizations of vector spaces |

### Graph Tools

| Tool Name | Description |
|-----------|-------------|
| `extract_knowledge_graph` | Extract a knowledge graph from text |
| `graph_rag_query` | Query a knowledge graph using RAG |
| `visualize_graph` | Generate visualizations of knowledge graphs |
| `validate_graph_against_wikidata` | Validate graph entities against Wikidata |

### Audit Tools

| Tool Name | Description |
|-----------|-------------|
| `audit_log` | Log audit events |
| `generate_audit_report` | Generate compliance reports |
| `audit_visualization` | Visualize audit data |
| `detect_anomalies` | Detect anomalies in audit logs |

### Security Tools

| Tool Name | Description |
|-----------|-------------|
| `manage_access_control` | Manage access control entries |
| `set_data_classification` | Set data classification levels |
| `verify_security_policy` | Verify compliance with security policies |
| `encrypt_data` | Encrypt sensitive data |

### Data Provenance Tools

| Tool Name | Description |
|-----------|-------------|
| `record_source` | Record a data source |
| `begin_transformation` | Start tracking a data transformation |
| `record_verification` | Record data verification results |
| `visualize_provenance` | Visualize data lineage |
| `export_provenance` | Export provenance data |

## Configuration

The MCP server can be configured using a YAML file:

```yaml
# MCP Server Configuration
server:
  name: "ipfs-datasets-mcp"
  host: "127.0.0.1"
  port: 5000
  transport: "stdio"  # or "http" or "websocket"
  
tools:
  enabled_categories:
    - "dataset"
    - "ipfs"
    - "vector"
    - "graph"
    - "audit"
    - "security"
    - "provenance"
    
  # Tool-specific configurations
  dataset:
    max_dataset_size: 1000000  # Maximum dataset size in records
    
  ipfs:
    timeout: 60  # Seconds to wait for IPFS operations
    
  vector:
    max_dimensions: 1536  # Maximum vector dimensions
```

## Example Usage

Here's an example of how an AI assistant would interact with these tools:

```
Human: Can you help me create a vector index from my dataset and search it?
