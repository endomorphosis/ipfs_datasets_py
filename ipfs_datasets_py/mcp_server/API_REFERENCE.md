# IPFS Datasets MCP Server API Reference

This document provides a reference for the MCP server API tools available in the IPFS Datasets Python package. These tools can be accessed through the Model Context Protocol by AI assistants like Claude.

## Server Configuration

The IPFS Datasets MCP server can be configured using:

1. **Command line arguments**:
   - `--host`: Host to bind the server to (default: 0.0.0.0)
   - `--port`: Port to bind the server to (default: 8000)
   - `--config`: Path to a configuration YAML file
   - `--ipfs-kit-mcp-url`: URL of an ipfs_kit_py MCP server

2. **Configuration file** (YAML format):
   ```yaml
   server:
     host: "127.0.0.1"
     port: 8000
     log_level: "INFO"
     verbose: true
     tool_timeout: 60
     transport: "stdio"
   
   tools:
     enabled_categories:
       - dataset
       - ipfs
       - vector
       - graph
       - audit
       - security
       - provenance
   
   ipfs_kit:
     integration: "mcp"  # or "direct"
     mcp_url: "http://localhost:8001"
   ```

## Dataset Tools

### load_dataset

Load a dataset from a file or IPFS source.

**Parameters:**
- `source` (str): Source path or identifier of the dataset (local file path or IPFS CID)
- `format` (str, optional): Format of the dataset (json, csv, parquet, etc.; auto-detected if not provided)
- `options` (dict, optional): Additional options for loading the dataset

**Returns:**
```json
{
  "status": "success",
  "dataset_id": "d12345",
  "metadata": {
    "name": "Example Dataset",
    "format": "json",
    "record_count": 100,
    "columns": ["id", "name", "value"]
  }
}
```

### save_dataset

Save a dataset to a destination.

**Parameters:**
- `dataset_id` (str): The ID of the dataset to save
- `destination` (str): Destination path or location to save the dataset
- `format` (str, optional): Format to save the dataset in
- `options` (dict, optional): Additional options for saving the dataset

**Returns:**
- Dictionary containing information about the saved dataset

### process_dataset

Process a dataset with a series of operations.

**Parameters:**
- `dataset_id` (str): The ID of the dataset to process
- `operations` (list): List of operations to apply to the dataset
- `output_id` (str, optional): Optional ID for the resulting dataset

**Returns:**
- Dictionary containing information about the processed dataset

### convert_dataset_format

Convert a dataset to a different format.

**Parameters:**
- `dataset_id` (str): The ID of the dataset to convert
- `target_format` (str): The format to convert the dataset to
- `output_path` (str, optional): Optional path to save the converted dataset
- `options` (dict, optional): Additional options for the conversion

**Returns:**
- Dictionary containing information about the converted dataset

## IPFS Tools

### pin_to_ipfs

Pin a file or directory to IPFS.

**Parameters:**
- `content_path` (str): Path to the file or directory to pin
- `recursive` (bool, optional): Whether to add the directory recursively
- `wrap_with_directory` (bool, optional): Whether to wrap the file(s) in a directory
- `hash_algo` (str, optional): The hash algorithm to use

**Returns:**
- Dictionary containing information about the pinned content

### get_from_ipfs

Get content from IPFS by its CID.

**Parameters:**
- `cid` (str): The Content Identifier (CID) to retrieve
- `output_path` (str, optional): Path where to save the retrieved content
- `timeout_seconds` (int, optional): Timeout for the retrieval operation in seconds

**Returns:**
- Dictionary containing information about the retrieved content

## Vector Tools

### create_vector_index

Create a vector index for similarity search.

**Parameters:**
- `vectors` (list): List of vectors to index
- `dimension` (int, optional): Dimension of the vectors
- `metric` (str, optional): Distance metric to use
- `metadata` (list, optional): Optional metadata for each vector
- `index_id` (str, optional): Optional ID for the index
- `index_name` (str, optional): Optional name for the index

**Returns:**
- Dictionary containing information about the created index

### search_vector_index

Search a vector index for similar vectors.

**Parameters:**
- `index_id` (str): ID of the vector index to search
- `query_vector` (list): The query vector to search for
- `top_k` (int, optional): Number of results to return
- `include_metadata` (bool, optional): Whether to include metadata in the results
- `include_distances` (bool, optional): Whether to include distance values in the results
- `filter_metadata` (dict, optional): Optional filter to apply to metadata

**Returns:**
- Dictionary containing search results

## Graph Tools

### query_knowledge_graph

Query a knowledge graph for information.

**Parameters:**
- `graph_id` (str): ID of the knowledge graph to query
- `query` (str): The query string (SPARQL, Cypher, etc.)
- `query_type` (str, optional): The type of query ('sparql', 'cypher', 'gremlin', etc.)
- `max_results` (int, optional): Maximum number of results to return
- `include_metadata` (bool, optional): Whether to include metadata in the results

**Returns:**
- Dictionary containing query results

## Audit Tools

### record_audit_event

Record an audit event for security, compliance, and operations tracking.

**Parameters:**
- `action` (str): The action being audited
- `resource_id` (str, optional): Optional ID of the resource being acted upon
- `resource_type` (str, optional): Optional type of the resource being acted upon
- `user_id` (str, optional): Optional ID of the user performing the action
- `details` (dict, optional): Optional additional details about the event
- `source_ip` (str, optional): Optional source IP address
- `severity` (str, optional): Severity level ('info', 'warning', 'error', 'critical')
- `tags` (list, optional): Optional tags for categorizing the event

**Returns:**
- Dictionary containing information about the recorded audit event

### generate_audit_report

Generate an audit report based on audit logs.

**Parameters:**
- `report_type` (str, optional): Type of report ('summary', 'detailed', 'security', 'compliance')
- `start_time` (str, optional): Optional start time for the report period (ISO format)
- `end_time` (str, optional): Optional end time for the report period (ISO format)
- `filters` (dict, optional): Optional filters to apply to the audit logs
- `output_format` (str, optional): Format of the report ('json', 'csv', 'html', 'pdf')
- `output_path` (str, optional): Optional path to save the report
- `include_details` (bool, optional): Whether to include detailed information in the report

**Returns:**
- Dictionary containing information about the generated report

## Security Tools

### check_access_permission

Check if a user has permission to access a resource.

**Parameters:**
- `resource_id` (str): ID of the resource to check
- `user_id` (str): ID of the user to check permissions for
- `permission_type` (str, optional): Type of permission to check ('read', 'write', 'delete', 'share', etc.)
- `resource_type` (str, optional): Optional type of the resource

**Returns:**
- Dictionary containing permission information

## Provenance Tools

### record_provenance

Record provenance information for a dataset operation.

**Parameters:**
- `dataset_id` (str): ID of the dataset
- `operation` (str): The operation performed on the dataset
- `inputs` (list, optional): Optional list of input dataset IDs or sources
- `parameters` (dict, optional): Optional parameters used in the operation
- `description` (str, optional): Optional description of the operation
- `agent_id` (str, optional): Optional ID of the agent performing the operation
- `timestamp` (str, optional): Optional timestamp for the operation (ISO format)
- `tags` (list, optional): Optional tags for categorizing the provenance record

**Returns:**
- Dictionary containing information about the recorded provenance
