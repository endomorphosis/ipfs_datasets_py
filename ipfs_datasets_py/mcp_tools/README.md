# MCP Tools - Model Context Protocol Integration

This module provides comprehensive Model Context Protocol (MCP) tool implementations for AI assistant integration with the IPFS Datasets Python library.

## Overview

The MCP tools module implements the Model Context Protocol standard, enabling AI assistants like Claude, GPT, and other language models to directly interact with IPFS datasets, vector stores, and processing capabilities through standardized tool interfaces.

## Components

### Tool Registry (`tool_registry.py`)
Central registry and management system for all MCP tools.

**Key Features:**
- Automatic tool discovery and registration
- Tool validation and capability checking
- Dynamic tool loading and configuration
- Access control and permission management
- Tool versioning and compatibility tracking

**Main Methods:**
- `register_tool()` - Register new MCP tools
- `discover_tools()` - Automatically find available tools
- `get_tool()` - Retrieve tool instances by name
- `validate_tools()` - Check tool functionality and compatibility

### Validators (`validators.py`)
Input validation and safety checking for MCP tool operations.

**Validation Features:**
- Parameter type and format validation
- Security constraint enforcement
- Input sanitization and safety checks
- Rate limiting and quota management
- Error handling and reporting

### Tools Directory (`tools/`)
Collection of specialized MCP tools organized by category:

**Tool Categories:**
- **Dataset Tools** - Dataset loading, conversion, and management
- **Vector Tools** - Embedding and vector search operations
- **Analysis Tools** - Data analysis and processing workflows
- **Admin Tools** - System administration and monitoring
- **Auth Tools** - Authentication and authorization
- **Cache Tools** - Caching and performance optimization
- **Embedding Tools** - Advanced embedding generation
- **Monitoring Tools** - System monitoring and diagnostics
- **Workflow Tools** - Complex workflow orchestration

## Usage Examples

### Basic Tool Registration
```python
from ipfs_datasets_py.mcp_tools import ToolRegistry

# Initialize registry
registry = ToolRegistry()

# Auto-discover and register all tools
await registry.discover_tools()

# List available tools
tools = registry.list_tools()
print(f"Available tools: {[tool.name for tool in tools]}")
```

### Tool Execution
```python
# Get a specific tool
dataset_tool = registry.get_tool("load_dataset")

# Execute tool with parameters
result = await dataset_tool.execute({
    "dataset_name": "my_dataset",
    "format": "parquet",
    "chunk_size": 1000
})
```

### Custom Tool Creation
```python
from ipfs_datasets_py.mcp_tools import BaseMCPTool

class CustomAnalysisTool(BaseMCPTool):
    name = "custom_analysis"
    description = "Perform custom data analysis"
    
    async def execute(self, params):
        # Your custom tool implementation
        return {"status": "success", "result": analysis_result}

# Register custom tool
registry.register_tool(CustomAnalysisTool())
```

## MCP Protocol Integration

### Server Configuration
```python
mcp_config = {
    "server": {
        "name": "ipfs-datasets-mcp",
        "version": "1.0.0",
        "description": "IPFS Datasets MCP Server"
    },
    "tools": {
        "auto_discovery": True,
        "validation_enabled": True,
        "rate_limiting": True
    }
}
```

### Tool Specification Format
```json
{
    "name": "tool_name",
    "description": "Tool description",
    "parameters": {
        "type": "object",
        "properties": {
            "param_name": {
                "type": "string",
                "description": "Parameter description"
            }
        },
        "required": ["param_name"]
    }
}
```

## Available Tool Categories

### Dataset Operations
- `load_dataset` - Load datasets from various sources
- `convert_dataset` - Convert between different formats
- `validate_dataset` - Validate dataset integrity
- `merge_datasets` - Combine multiple datasets

### Vector Operations
- `create_embeddings` - Generate embeddings from text
- `search_vectors` - Perform vector similarity search
- `manage_index` - Vector index management
- `analyze_embeddings` - Embedding quality analysis

### Analysis Tools
- `analyze_data` - Comprehensive data analysis
- `generate_insights` - Extract insights from datasets
- `create_visualizations` - Generate data visualizations
- `quality_assessment` - Assess data quality metrics

### Administrative Tools
- `monitor_system` - System monitoring and health checks
- `manage_resources` - Resource allocation and management
- `configure_settings` - System configuration management
- `backup_data` - Data backup and recovery operations

## Security and Validation

### Input Validation
- Parameter type checking and validation
- Range and format constraint enforcement
- Injection attack prevention
- Resource limit enforcement

### Access Control
- Role-based access control (RBAC)
- Tool-level permission management
- Audit logging for all operations
- Rate limiting and quota enforcement

### Safety Measures
- Sandboxed execution environments
- Resource consumption monitoring
- Automatic timeout handling
- Error containment and recovery

## Performance Optimization

### Caching Strategies
- Tool result caching
- Parameter-based cache keys
- TTL-based cache expiration
- Memory and disk caching options

### Execution Optimization
- Async/await for non-blocking operations
- Connection pooling for database operations
- Batch processing for multiple requests
- Resource pooling and reuse

## Integration

The MCP tools module integrates with:

- **All IPFS Datasets modules** - Provides tool interfaces for every component
- **Vector Stores** - Tool-based vector operations
- **Embeddings** - Embedding generation tools
- **PDF Processing** - Document processing tools
- **RAG Module** - Retrieval and generation tools
- **External AI Systems** - Claude, GPT, and other LLM integration

## Dependencies

- `asyncio` - Asynchronous operations
- `pydantic` - Data validation and serialization
- `jsonschema` - Tool specification validation
- Core IPFS Datasets modules for functionality

## Development

### Creating New Tools
1. Inherit from `BaseMCPTool`
2. Implement required methods (`execute`, `validate`)
3. Define tool schema and parameters
4. Add appropriate validation and error handling
5. Register with the tool registry

### Testing Tools
```python
# Tool testing framework
from ipfs_datasets_py.mcp_tools.testing import ToolTester

tester = ToolTester(tool_instance)
await tester.run_validation_tests()
await tester.run_performance_tests()
```

## See Also

- [MCP Server](../mcp_server/README.md) - MCP server implementation
- [API Reference](../../docs/api_reference.md) - Complete API documentation
- [MCP Tools Catalog](../../MCP_TOOLS_COMPLETE_CATALOG.md) - Complete tool listing
- [Developer Guide](../../docs/developer_guide.md) - Development guidelines
- [Security Guide](../../docs/security_governance.md) - Security implementation details