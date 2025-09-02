#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MCP Dashboard Demo Script

This script demonstrates the MCP server dashboard functionality by:
1. Starting the MCP dashboard server
2. Showing how to use the JavaScript SDK programmatically
3. Displaying available tools and server status
"""
import sys
import time
import threading
import webbrowser
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from ipfs_datasets_py.mcp_dashboard import MCPDashboard, MCPDashboardConfig
    print("✓ Successfully imported MCP dashboard")
except ImportError as e:
    print(f"✗ Failed to import MCP dashboard: {e}")
    sys.exit(1)

def start_dashboard_demo():
    """Start the MCP dashboard demo."""
    print("\n=== MCP Dashboard Demo ===")
    
    # Configure the dashboard
    config = MCPDashboardConfig(
        host="0.0.0.0",
        port=8080,
        mcp_server_host="localhost",
        mcp_server_port=8001,
        enable_tool_execution=True,
        data_dir="/tmp/mcp_dashboard_demo"
    )
    
    # Initialize dashboard
    dashboard = MCPDashboard()
    dashboard.configure(config)
    
    # Create templates and static files
    dashboard._create_mcp_templates()
    
    print(f"Starting dashboard on http://{config.host}:{config.port}")
    print("Available endpoints:")
    print(f"  - Main Dashboard: http://{config.host}:{config.port}/")
    print(f"  - MCP Dashboard: http://{config.host}:{config.port}/mcp")
    print(f"  - API Status: http://{config.host}:{config.port}/api/mcp/status")
    print(f"  - API Tools: http://{config.host}:{config.port}/api/mcp/tools")
    print(f"  - JavaScript SDK: http://{config.host}:{config.port}/static/js/mcp-sdk.js")
    
    # Show discovered tools
    tools_info = dashboard._discover_mcp_tools()
    print(f"\nDiscovered {len(tools_info)} tool categories:")
    for category, tools in sorted(tools_info.items()):
        print(f"  - {category}: {len(tools)} tools")
    
    # Show server status
    server_status = dashboard._get_mcp_server_status()
    print(f"\nMCP Server Status: {server_status['status']}")
    print(f"Tools available: {server_status.get('tools_available', 0)}")
    
    # Start the dashboard server in a thread
    def run_dashboard():
        try:
            dashboard.start()
        except Exception as e:
            print(f"Dashboard server error: {e}")
    
    dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()
    
    # Wait a moment for server to start
    time.sleep(2)
    
    print(f"\n🚀 Dashboard is running!")
    print("Press Ctrl+C to stop the server")
    
    # Open browser (optional)
    try:
        webbrowser.open(f"http://localhost:{config.port}/mcp")
        print("✓ Opened browser to MCP dashboard")
    except Exception as e:
        print(f"Could not open browser: {e}")
    
    return dashboard

def demo_javascript_sdk():
    """Demonstrate JavaScript SDK usage."""
    print("\n=== JavaScript SDK Usage Demo ===")
    
    # Create example HTML page showing SDK usage
    html_example = """<!DOCTYPE html>
<html>
<head>
    <title>MCP SDK Demo</title>
    <script src="http://localhost:8080/static/js/mcp-sdk.js"></script>
</head>
<body>
    <h1>MCP JavaScript SDK Demo</h1>
    <div id="status"></div>
    <div id="tools"></div>
    <div id="results"></div>
    
    <script>
        // Initialize MCP client
        const client = new MCPClient('http://localhost:8080/api/mcp');
        
        // Get server status
        client.getServerStatus().then(status => {
            document.getElementById('status').innerHTML = 
                '<h2>Server Status</h2><pre>' + JSON.stringify(status, null, 2) + '</pre>';
        });
        
        // Get available tools
        client.getTools().then(tools => {
            document.getElementById('tools').innerHTML = 
                '<h2>Available Tools</h2><pre>' + JSON.stringify(tools, null, 2) + '</pre>';
        });
        
        // Example tool execution (commented out to avoid errors)
        /*
        client.executeTool('dataset_tools', 'load_dataset', {
            dataset_name: 'example'
        }).then(result => {
            document.getElementById('results').innerHTML = 
                '<h2>Execution Result</h2><pre>' + JSON.stringify(result, null, 2) + '</pre>';
        }).catch(error => {
            console.error('Tool execution failed:', error);
        });
        */
    </script>
</body>
</html>"""
    
    demo_file = Path("/tmp/mcp_sdk_demo.html")
    with open(demo_file, 'w') as f:
        f.write(html_example)
    
    print(f"Created SDK demo file: {demo_file}")
    print("You can open this file in a browser to test the JavaScript SDK")
    
    # Show JavaScript SDK usage patterns
    print("\nJavaScript SDK Usage Examples:")
    print("""
    // Initialize client
    const client = new MCPClient('http://localhost:8080/api/mcp');
    
    // Get server status
    const status = await client.getServerStatus();
    
    // Get available tools
    const tools = await client.getTools();
    
    // Execute a tool
    const result = await client.executeTool('dataset_tools', 'load_dataset', {
        dataset_name: 'my_dataset'
    });
    
    // Use fluent API
    const result2 = await client
        .tool('analysis_tools', 'analyze_data')
        .withParams({ data: 'some data' })
        .withOptions({ timeout: 60000 })
        .execute();
    
    // Start status polling
    const stopPolling = client.startStatusPolling(5000, (error, status) => {
        if (error) {
            console.error('Status polling error:', error);
        } else {
            console.log('Server status:', status);
        }
    });
    """)

def show_api_endpoints():
    """Show available API endpoints."""
    print("\n=== Available API Endpoints ===")
    
    endpoints = [
        ("GET", "/api/mcp/tools", "List all available tools"),
        ("GET", "/api/mcp/tools/{category}/{tool_name}", "Get tool information"),
        ("POST", "/api/mcp/tools/{category}/{tool_name}/execute", "Execute a tool"),
        ("GET", "/api/mcp/executions/{execution_id}", "Get execution status"),
        ("GET", "/api/mcp/status", "Get MCP server status"),
        ("GET", "/api/mcp/history", "Get execution history"),
        ("GET", "/static/js/mcp-sdk.js", "JavaScript SDK"),
    ]
    
    print("Method | Endpoint | Description")
    print("-" * 70)
    for method, endpoint, description in endpoints:
        print(f"{method:6} | {endpoint:35} | {description}")
    
    print("\nExample curl commands:")
    print("curl http://localhost:8080/api/mcp/status")
    print("curl http://localhost:8080/api/mcp/tools")
    print("curl -X POST -H 'Content-Type: application/json' \\")
    print("     -d '{\"param1\": \"value1\"}' \\")
    print("     http://localhost:8080/api/mcp/tools/dataset_tools/load_dataset/execute")

def main():
    """Run the MCP dashboard demo."""
    print("🚀 IPFS Datasets MCP Dashboard Demo")
    print("=" * 50)
    
    try:
        # Start dashboard
        dashboard = start_dashboard_demo()
        
        # Show SDK demo
        demo_javascript_sdk()
        
        # Show API endpoints
        show_api_endpoints()
        
        print("\n" + "=" * 50)
        print("Dashboard is running. Visit http://localhost:8080/mcp")
        print("Press Ctrl+C to stop")
        
        # Keep running until interrupted
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n✓ Dashboard stopped")
            dashboard.stop()
            
    except Exception as e:
        print(f"Demo failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()