# IPFS Datasets MCP Server Integration

This document outlines the Model Context Protocol (MCP) server implementation for IPFS Datasets Python.

## Overview

The IPFS Datasets MCP server provides a standardized interface for AI models to interact with IPFS datasets. It implements the Model Context Protocol, allowing AI assistants to perform operations like:

- Loading datasets from various sources
- Saving datasets to IPFS
- Converting dataset formats
- Processing datasets with transformations
- Querying dataset content
- Managing IPFS interactions
- Vector search operations
- Knowledge graph interactions
- Audit logging
- Security operations
- Provenance tracking

## Architecture

The MCP server implementation consists of:

1. **Core Server**: Implements the MCP protocol using either the `modelcontextprotocol` package or a simplified Flask-based implementation.

2. **Tool Categories**:
   - `dataset_tools`: Tools for dataset operations
   - `ipfs_tools`: Tools for IPFS interactions
   - `vector_tools`: Tools for vector operations and similarity search
   - `graph_tools`: Tools for knowledge graph operations
   - `audit_tools`: Tools for audit logging
   - `security_tools`: Tools for security operations
   - `provenance_tools`: Tools for tracking provenance
   - `cli`: Command-line interface tools
   - `functions`: Function execution tools

3. **Configuration System**: Flexible configuration via YAML files

4. **IPFS Kit Integration**: Built-in integration with `ipfs_kit_py`

## Getting Started

### Installation

The MCP server is included in the IPFS Datasets Python package.

```bash
pip install ipfs-datasets-py
```

### Running the Server

You can start the server using:

```bash
cd /path/to/ipfs_datasets_py
./ipfs_datasets_py/mcp_server/start_server.sh
```

Or for the simplified implementation:

```bash
cd /path/to/ipfs_datasets_py
./ipfs_datasets_py/mcp_server/start_simple_server.sh
```

### Demo Script

We provide a demo script that starts the server and tests its functionality:

```bash
./demo_mcp_server.py
```

## Available Tools

The server provides tools in the following categories:

1. **Dataset Tools**:
   - `load_dataset`: Load a dataset from a source
   - `save_dataset`: Save a dataset to a destination
   - `convert_dataset_format`: Convert a dataset between formats
   - `process_dataset`: Apply transformations to a dataset

2. **IPFS Tools**:
   - `get_from_ipfs`: Get content from IPFS
   - `pin_to_ipfs`: Pin content to IPFS

3. **Vector Tools**:
   - `create_vector_index`: Create a vector index from dataset
   - `search_vector_index`: Search a vector index

4. **Graph Tools**:
   - `query_knowledge_graph`: Query a knowledge graph

5. **Audit Tools**:
   - `record_audit_event`: Record an audit event
   - `generate_audit_report`: Generate an audit report

6. **Security Tools**:
   - `check_access_permission`: Check access permissions

7. **Provenance Tools**:
   - `record_provenance`: Record provenance information

8. **CLI Tools**:
   - `execute_command`: Execute a command

9. **Function Tools**:
   - `execute_python_snippet`: Execute a Python code snippet

## Integration Tests

To run the integration tests:

```bash
python test_mcp_integration.py
```

This will verify:
- The server component structure
- Core functionality
- Tool availability
- IPFS Kit integration

## Integration with AI Assistants

AI assistants like Claude can interact with datasets through this MCP server implementation, enabling capabilities like:

- Loading and analyzing data from IPFS
- Processing datasets with specified transformations
- Performing similarity searches using vector indices
- Querying knowledge graphs
- Generating data visualizations
- Recording audit events and provenance information
