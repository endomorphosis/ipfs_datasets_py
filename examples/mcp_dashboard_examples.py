"""
MCP Dashboard Usage Examples

This file contains practical examples of using the MCP dashboard and JavaScript SDK.
"""

# Example 1: Basic Dashboard Setup
def basic_dashboard_setup():
    """Example of basic dashboard setup and startup."""
    from ipfs_datasets_py.mcp_dashboard import MCPDashboard, MCPDashboardConfig
    
    # Create configuration
    config = MCPDashboardConfig(
        host="localhost",
        port=8080,
        enable_tool_execution=True
    )
    
    # Initialize and start dashboard
    dashboard = MCPDashboard()
    dashboard.configure(config)
    dashboard.start()
    
    print("Dashboard running at http://localhost:8080/mcp")
    return dashboard

# Example 2: Advanced Dashboard Configuration
def advanced_dashboard_setup():
    """Example of advanced dashboard configuration with custom settings."""
    from ipfs_datasets_py.mcp_dashboard import MCPDashboard, MCPDashboardConfig
    
    config = MCPDashboardConfig(
        host="0.0.0.0",                    # Listen on all interfaces
        port=8080,
        mcp_server_host="localhost",
        mcp_server_port=8001,
        enable_tool_execution=True,
        tool_timeout=60.0,                 # 60 second timeout
        max_concurrent_tools=10,           # Allow 10 concurrent executions
        data_dir="/var/mcp_dashboard",     # Custom data directory
        require_auth=True,                 # Enable authentication
        username="admin",
        password="secure_password"
    )
    
    dashboard = MCPDashboard()
    dashboard.configure(config)
    
    # Create custom templates
    dashboard._create_mcp_templates()
    
    dashboard.start()
    return dashboard

# Example 3: Programmatic Tool Discovery and Execution
def programmatic_tool_usage():
    """Example of discovering and executing tools programmatically."""
    from ipfs_datasets_py.mcp_dashboard import MCPDashboard, MCPDashboardConfig
    
    # Setup dashboard
    config = MCPDashboardConfig(enable_tool_execution=True)
    dashboard = MCPDashboard()
    dashboard.configure(config)
    
    # Discover available tools
    tools_info = dashboard._discover_mcp_tools()
    print(f"Discovered {len(tools_info)} tool categories:")
    
    for category, tools in tools_info.items():
        print(f"  {category}: {len(tools)} tools")
        for tool in tools[:3]:  # Show first 3 tools
            print(f"    - {tool['name']}")
    
    # Execute a tool programmatically (simulation)
    try:
        result = dashboard._execute_tool_sync(
            'dataset_tools', 
            'load_dataset',
            {'dataset_name': 'example', 'format': 'json'}
        )
        print(f"Tool execution result: {result}")
    except Exception as e:
        print(f"Tool execution failed: {e}")

# Example 4: Custom Tool Execution Handler
def custom_execution_handler():
    """Example of custom tool execution with monitoring."""
    from ipfs_datasets_py.mcp_dashboard import MCPDashboard, MCPDashboardConfig
    import time
    import json
    
    class MonitoredMCPDashboard(MCPDashboard):
        """Custom dashboard with execution monitoring."""
        
        def _execute_tool_sync(self, category, tool_name, params):
            """Override to add custom monitoring."""
            start_time = time.time()
            print(f"Starting execution: {category}/{tool_name}")
            
            try:
                result = super()._execute_tool_sync(category, tool_name, params)
                duration = time.time() - start_time
                print(f"Execution completed in {duration:.2f}s")
                
                # Log to custom file
                with open("/tmp/mcp_executions.log", "a") as f:
                    log_entry = {
                        "timestamp": time.time(),
                        "category": category,
                        "tool": tool_name,
                        "params": params,
                        "duration": duration,
                        "success": True
                    }
                    f.write(json.dumps(log_entry) + "\n")
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                print(f"Execution failed after {duration:.2f}s: {e}")
                
                # Log failure
                with open("/tmp/mcp_executions.log", "a") as f:
                    log_entry = {
                        "timestamp": time.time(),
                        "category": category,
                        "tool": tool_name,
                        "params": params,
                        "duration": duration,
                        "success": False,
                        "error": str(e)
                    }
                    f.write(json.dumps(log_entry) + "\n")
                
                raise
    
    # Use custom dashboard
    config = MCPDashboardConfig(port=8080)
    dashboard = MonitoredMCPDashboard()
    dashboard.configure(config)
    return dashboard

# Example 5: Integration with Flask App
def integrate_with_flask():
    """Example of integrating MCP dashboard with existing Flask app."""
    from flask import Flask
    from ipfs_datasets_py.mcp_dashboard import MCPDashboard, MCPDashboardConfig
    
    # Create main Flask app
    app = Flask(__name__)
    
    @app.route('/')
    def home():
        return '<h1>Main App</h1><a href="/mcp">MCP Dashboard</a>'
    
    # Initialize MCP dashboard
    config = MCPDashboardConfig(port=None)  # Don't start separate server
    mcp_dashboard = MCPDashboard()
    mcp_dashboard.configure(config)
    
    # Register MCP routes with main app
    @app.route('/mcp')
    def mcp_dashboard_view():
        return mcp_dashboard.app.test_client().get('/mcp').data.decode()
    
    @app.route('/api/mcp/<path:path>', methods=['GET', 'POST'])
    def mcp_api(path):
        # Proxy to MCP dashboard API
        client = mcp_dashboard.app.test_client()
        if request.method == 'GET':
            response = client.get(f'/api/mcp/{path}')
        else:
            response = client.post(f'/api/mcp/{path}', json=request.json)
        
        return response.data, response.status_code
    
    return app

# JavaScript SDK Usage Examples

js_examples = """
// Example 1: Basic SDK Usage
const client = new MCPClient('http://localhost:8080/api/mcp');

// Get server status
client.getServerStatus().then(status => {
    console.log('Server status:', status);
});

// Example 2: Tool Discovery
async function discoverTools() {
    try {
        const tools = await client.getTools();
        
        // Display tools by category
        for (const [category, toolList] of Object.entries(tools)) {
            console.log(`${category}:`);
            toolList.forEach(tool => {
                console.log(`  - ${tool.name}: ${tool.description}`);
            });
        }
    } catch (error) {
        console.error('Failed to discover tools:', error);
    }
}

// Example 3: Tool Execution with Error Handling
async function executeToolSafely(category, toolName, params) {
    try {
        console.log(`Executing ${category}/${toolName}...`);
        
        const result = await client.executeTool(category, toolName, params);
        
        if (result.status === 'completed') {
            console.log('Success:', result.result);
            return result.result;
        } else {
            console.error('Tool execution failed:', result.error);
            return null;
        }
    } catch (error) {
        if (error instanceof MCPError) {
            console.error('MCP Error:', error.message);
            if (error.status === 404) {
                console.error('Tool not found');
            } else if (error.status >= 500) {
                console.error('Server error - retrying might help');
            }
        } else {
            console.error('Network error:', error.message);
        }
        return null;
    }
}

// Example 4: Fluent API Usage
async function fluentApiExample() {
    const result = await client
        .tool('dataset_tools', 'load_dataset')
        .withParams({
            dataset_name: 'my_dataset',
            format: 'parquet'
        })
        .withOptions({
            timeout: 30000
        })
        .execute();
    
    console.log('Dataset loaded:', result);
}

// Example 5: Real-time Monitoring
function startMonitoring() {
    // Monitor tool executions
    client.on('toolExecutionStart', (data) => {
        console.log(`Started: ${data.category}/${data.toolName}`);
        updateUI('started', data);
    });
    
    client.on('toolExecutionComplete', (data) => {
        console.log(`Completed: ${data.category}/${data.toolName}`);
        updateUI('completed', data);
    });
    
    client.on('toolExecutionError', (data) => {
        console.error(`Failed: ${data.category}/${data.toolName}`, data.error);
        updateUI('failed', data);
    });
    
    // Start status polling
    const stopPolling = client.startStatusPolling(5000, (error, status) => {
        if (!error) {
            updateStatusDisplay(status);
        }
    });
    
    return stopPolling;
}

// Example 6: Batch Tool Execution
async function batchProcessing() {
    const datasets = ['dataset1', 'dataset2', 'dataset3'];
    
    const toolSpecs = datasets.map(name => ({
        category: 'dataset_tools',
        toolName: 'load_dataset',
        parameters: { dataset_name: name }
    }));
    
    const results = await client.batchExecuteTools(toolSpecs, {
        maxConcurrent: 2,
        failFast: false
    });
    
    console.log(`Processed ${results.successful} datasets successfully`);
    console.log(`Failed: ${results.failed}`);
    
    return results;
}

// Example 7: Custom Event Handler
class MCPDashboardWidget {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.client = new MCPClient('/api/mcp');
        this.setupEventHandlers();
    }
    
    setupEventHandlers() {
        this.client.on('toolExecutionStart', (data) => {
            this.showNotification(`Executing ${data.toolName}...`, 'info');
        });
        
        this.client.on('toolExecutionComplete', (data) => {
            this.showNotification(`${data.toolName} completed!`, 'success');
        });
        
        this.client.on('toolExecutionError', (data) => {
            this.showNotification(`${data.toolName} failed: ${data.error.message}`, 'error');
        });
    }
    
    async executeTool(category, toolName, params) {
        return await this.client.executeTool(category, toolName, params);
    }
    
    showNotification(message, type) {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;
        this.container.appendChild(notification);
        
        setTimeout(() => notification.remove(), 5000);
    }
}

// Usage: const widget = new MCPDashboardWidget('notifications');

function updateUI(status, data) {
    // Implementation depends on your UI framework
    console.log('UI Update:', status, data);
}

function updateStatusDisplay(status) {
    // Update status display in UI
    console.log('Status Update:', status);
}
"""

# Save JavaScript examples to file
def save_js_examples():
    """Save JavaScript examples to file."""
    with open('/tmp/mcp_sdk_examples.js', 'w') as f:
        f.write(js_examples)
    print("JavaScript examples saved to /tmp/mcp_sdk_examples.js")

if __name__ == "__main__":
    print("MCP Dashboard Usage Examples")
    print("=" * 40)
    
    # Run Python examples
    print("\n1. Basic Dashboard Setup:")
    try:
        # Note: These are examples - don't actually start servers in example file
        print("✓ Example functions defined")
        print("  - basic_dashboard_setup()")
        print("  - advanced_dashboard_setup()")
        print("  - programmatic_tool_usage()")
        print("  - custom_execution_handler()")
        print("  - integrate_with_flask()")
    except Exception as e:
        print(f"✗ Error: {e}")
    
    # Save JavaScript examples
    print("\n2. JavaScript SDK Examples:")
    save_js_examples()
    
    print("\nTo run the examples:")
    print("  python -c 'from mcp_dashboard_examples import basic_dashboard_setup; basic_dashboard_setup()'")