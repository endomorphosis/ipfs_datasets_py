# MCP Server Dashboard and JavaScript SDK

This document describes the MCP (Model Context Protocol) server dashboard and JavaScript SDK implementation for IPFS Datasets Python.

## Overview

The MCP Dashboard provides a web-based interface for:
- Monitoring MCP server status
- Discovering and executing available tools
- Viewing execution history and results
- Real-time server monitoring

The JavaScript SDK enables web applications to interact with the MCP server programmatically.

## Architecture

```
ipfs_datasets_py/
├── mcp_dashboard.py              # Main dashboard implementation
├── static/admin/
│   ├── js/mcp-sdk.js            # JavaScript SDK
│   └── css/mcp-dashboard.css    # Dashboard styles
├── templates/admin/
│   └── mcp_dashboard.html       # Dashboard template (auto-generated)
└── mcp_server/                  # Existing MCP server implementation
    ├── tools/                   # Available MCP tools
    └── simple_server.py         # MCP server
```

## Features

### Dashboard Features
- **Tool Discovery**: Automatically discovers available MCP tools by category
- **Server Status**: Real-time monitoring of MCP server health and statistics
- **Tool Execution**: Web interface for executing tools with parameters
- **Execution History**: View and track all tool executions
- **REST API**: Full REST API for programmatic access

### JavaScript SDK Features
- **Simple API**: Easy-to-use client for MCP server communication
- **Error Handling**: Built-in retry logic and error management
- **Async Support**: Promise-based API with async/await support
- **Event System**: Event listeners for monitoring operations
- **Fluent API**: Builder pattern for complex tool executions
- **Caching**: Intelligent caching of tool discovery results

## Quick Start

### Starting the Dashboard

```python
from ipfs_datasets_py.dashboards.mcp_dashboard import start_mcp_dashboard, MCPDashboardConfig

# Basic configuration
config = MCPDashboardConfig(
    host="localhost",
    port=8080,
    enable_tool_execution=True
)

# Start dashboard
dashboard = start_mcp_dashboard(config)

# Dashboard available at: http://localhost:8080/mcp
```

### Using the JavaScript SDK

```javascript
// Initialize client
const client = new MCPClient('http://localhost:8080/api/mcp');

// Get server status
const status = await client.getServerStatus();
console.log('Server status:', status);

// Discover tools
const tools = await client.getTools();
console.log('Available tools:', tools);

// Execute a tool
const result = await client.executeTool('dataset_tools', 'load_dataset', {
    dataset_name: 'my_dataset',
    format: 'parquet'
});
console.log('Execution result:', result);
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/mcp/status` | Get MCP server status |
| GET | `/api/mcp/tools` | List all available tools |
| GET | `/api/mcp/tools/{category}/{tool}` | Get tool information |
| POST | `/api/mcp/tools/{category}/{tool}/execute` | Execute a tool |
| GET | `/api/mcp/executions/{id}` | Get execution status |
| GET | `/api/mcp/history` | Get execution history |
| GET | `/static/js/mcp-sdk.js` | JavaScript SDK |

## Configuration

### Dashboard Configuration

```python
config = MCPDashboardConfig(
    host="0.0.0.0",                    # Host to bind to
    port=8080,                         # Port to listen on
    mcp_server_host="localhost",       # MCP server host
    mcp_server_port=8001,             # MCP server port
    enable_tool_execution=True,        # Allow tool execution
    tool_timeout=30.0,                # Tool execution timeout
    max_concurrent_tools=5,           # Max concurrent executions
    data_dir="/tmp/mcp_dashboard"     # Data storage directory
)
```

### SDK Configuration

```javascript
const client = new MCPClient('http://localhost:8080/api/mcp', {
    timeout: 30000,    // Request timeout (30s)
    retries: 3,        // Number of retries
    retryDelay: 1000   // Delay between retries
});
```

## Advanced Usage

### Fluent API

```javascript
const result = await client
    .tool('analysis_tools', 'analyze_data')
    .withParams({
        data: 'sample data',
        analysis_type: 'statistical'
    })
    .withOptions({
        timeout: 60000
    })
    .execute();
```

### Batch Execution

```javascript
const toolSpecs = [
    { category: 'dataset_tools', toolName: 'load_dataset', parameters: { name: 'dataset1' }},
    { category: 'dataset_tools', toolName: 'load_dataset', parameters: { name: 'dataset2' }},
];

const results = await client.batchExecuteTools(toolSpecs, {
    maxConcurrent: 2,
    failFast: false
});
```

### Event Monitoring

```javascript
// Listen for tool execution events
client.on('toolExecutionStart', (data) => {
    console.log('Tool execution started:', data);
});

client.on('toolExecutionComplete', (data) => {
    console.log('Tool execution completed:', data);
});

// Start status polling
const stopPolling = client.startStatusPolling(5000, (error, status) => {
    if (error) {
        console.error('Status error:', error);
    } else {
        console.log('Server status:', status);
    }
});
```

## Tool Categories

The dashboard automatically discovers tools in the following categories:

- **dataset_tools**: Dataset loading, saving, and manipulation
- **embedding_tools**: Text and data embedding generation
- **vector_tools**: Vector operations and similarity search
- **analysis_tools**: Data analysis and statistics
- **workflow_tools**: Workflow orchestration and automation
- **monitoring_tools**: System monitoring and metrics
- **admin_tools**: Administrative operations
- **security_tools**: Security and authentication
- **audit_tools**: Audit logging and compliance
- **And many more...**

## Error Handling

### Dashboard Errors

The dashboard provides comprehensive error handling:

```python
try:
    dashboard = start_mcp_dashboard(config)
except Exception as e:
    print(f"Failed to start dashboard: {e}")
```

### SDK Errors

The SDK includes custom error types:

```javascript
try {
    const result = await client.executeTool('invalid_category', 'invalid_tool');
} catch (error) {
    if (error instanceof MCPError) {
        console.error('MCP Error:', error.message);
        console.error('Status:', error.status);
        console.error('Data:', error.data);
    } else {
        console.error('Network Error:', error.message);
    }
}
```

## Security Considerations

1. **Authentication**: The dashboard can be configured with authentication
2. **CORS**: Configure CORS settings for production deployments
3. **Input Validation**: All tool parameters are validated before execution
4. **Rate Limiting**: Built-in rate limiting prevents abuse
5. **Error Sanitization**: Errors are sanitized to prevent information leakage

## Integration Examples

### React Component

```jsx
import React, { useState, useEffect } from 'react';

function MCPDashboard() {
    const [client] = useState(() => new MCPClient('/api/mcp'));
    const [status, setStatus] = useState(null);
    const [tools, setTools] = useState({});

    useEffect(() => {
        const loadData = async () => {
            try {
                const [statusData, toolsData] = await Promise.all([
                    client.getServerStatus(),
                    client.getTools()
                ]);
                setStatus(statusData);
                setTools(toolsData);
            } catch (error) {
                console.error('Failed to load dashboard data:', error);
            }
        };

        loadData();
        
        // Start polling for status updates
        const stopPolling = client.startStatusPolling(5000, (error, statusData) => {
            if (!error) setStatus(statusData);
        });

        return stopPolling;
    }, [client]);

    return (
        <div>
            <h1>MCP Dashboard</h1>
            {status && (
                <div>Status: {status.status}</div>
            )}
            {/* Tool display and execution UI */}
        </div>
    );
}
```

### jQuery Plugin

```javascript
// Use the included jQuery plugin
$('.mcp-tool-button').mcpToolExecutor({
    baseUrl: '/api/mcp',
    onResult: (result, element) => {
        console.log('Tool executed:', result);
        element.addClass('success');
    },
    onError: (error, element) => {
        console.error('Tool failed:', error);
        element.addClass('error');
    }
});
```

## Testing

Run the test suite:

```bash
python test_mcp_dashboard.py
```

Run the demo:

```bash
python demo_mcp_dashboard.py
```

## Troubleshooting

### Common Issues

1. **Dashboard won't start**: Check that the port is not already in use
2. **Tools not discovered**: Verify MCP server tools directory exists
3. **JavaScript SDK 404**: Ensure static files are in the correct directory
4. **Tool execution fails**: Check tool parameters and server logs

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

config = MCPDashboardConfig(debug=True)
dashboard = start_mcp_dashboard(config)
```

## License

This implementation is part of the IPFS Datasets Python project and follows the same license terms.