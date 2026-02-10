#!/usr/bin/env python3
"""
Minimal standalone MCP server for Docker deployment.
This version doesn't rely on the complex ipfs_datasets_py package structure.
"""

import anyio
import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

try:
    from flask import Flask, jsonify, request
    from mcp import server as mcp
    FLASK_AVAILABLE = True
    MCP_AVAILABLE = True
except ImportError as e:
    FLASK_AVAILABLE = False
    MCP_AVAILABLE = False
    logging.warning(f"Dependencies not available: {e}")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import error reporting if available
try:
    from ipfs_datasets_py.error_reporting import (
        install_error_handlers,
        get_global_error_reporter
    )
    from ipfs_datasets_py.error_reporting.api import setup_error_reporting_routes
    ERROR_REPORTING_AVAILABLE = True
except ImportError:
    ERROR_REPORTING_AVAILABLE = False
    logger.info("Error reporting module not available")

class MinimalMCPServer:
    """Minimal MCP server for Docker deployment."""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        self.host = host
        self.port = port
        self.app = Flask(__name__)
        
        # Install error handlers if available
        if ERROR_REPORTING_AVAILABLE:
            install_error_handlers()
            logger.info("Error reporting handlers installed")
        
        self.setup_routes()
        
    def setup_routes(self):
        """Set up basic HTTP routes."""
        
        @self.app.route('/health')
        def health():
            return jsonify({
                "status": "healthy",
                "service": "ipfs-datasets-mcp-server",
                "timestamp": datetime.now().isoformat(),
                "version": "1.0.0"
            })
            
        @self.app.route('/')
        def index():
            return jsonify({
                "name": "IPFS Datasets MCP Server",
                "version": "1.0.0",
                "status": "running",
                "endpoints": {
                    "health": "/health",
                    "tools": "/tools",
                    "execute": "/execute"
                }
            })
            
        @self.app.route('/tools')
        def list_tools():
            return jsonify({
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo back the input text",
                        "parameters": {
                            "text": {
                                "type": "string",
                                "description": "Text to echo back"
                            }
                        }
                    },
                    {
                        "name": "status",
                        "description": "Get server status",
                        "parameters": {}
                    }
                ]
            })
            
        @self.app.route('/execute', methods=['POST'])
        def execute_tool():
            try:
                data = request.get_json()
                tool_name = data.get('tool_name')
                parameters = data.get('parameters', {})
                
                if tool_name == 'echo':
                    text = parameters.get('text', 'No text provided')
                    return jsonify({
                        "result": f"Echo: {text}",
                        "success": True
                    })
                elif tool_name == 'status':
                    return jsonify({
                        "result": {
                            "server": "ipfs-datasets-mcp",
                            "status": "running",
                            "timestamp": datetime.now().isoformat()
                        },
                        "success": True
                    })
                else:
                    return jsonify({
                        "error": f"Unknown tool: {tool_name}",
                        "success": False
                    }), 400
                    
            except Exception as e:
                # Report exception if error reporting is enabled
                if ERROR_REPORTING_AVAILABLE:
                    reporter = get_global_error_reporter()
                    if reporter.enabled:
                        reporter.report_exception(e, source="python", context={
                            'endpoint': '/execute',
                            'tool_name': tool_name,
                            'parameters': parameters
                        })
                
                return jsonify({
                    "error": str(e),
                    "success": False
                }), 500
        
        # Add error reporting routes if available
        if ERROR_REPORTING_AVAILABLE:
            setup_error_reporting_routes(self.app)
            logger.info("Error reporting API routes registered")
                
    def run(self):
        """Run the MCP server."""
        logger.info(f"Starting MCP server on {self.host}:{self.port}")
        self.app.run(host=self.host, port=self.port, debug=False)

class MinimalMCPDashboard:
    """Minimal MCP dashboard for Docker deployment."""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8080, mcp_server_url: str = "http://localhost:8000"):
        self.host = host
        self.port = port
        self.mcp_server_url = mcp_server_url
        self.app = Flask(__name__, static_folder='../static', static_url_path='/static')
        
        # Install error handlers if available
        if ERROR_REPORTING_AVAILABLE:
            install_error_handlers()
        
        self.setup_routes()
        
    def setup_routes(self):
        """Set up dashboard routes."""
        
        @self.app.route('/health')
        def health():
            return jsonify({
                "status": "healthy",
                "service": "ipfs-datasets-mcp-dashboard",
                "timestamp": datetime.now().isoformat(),
                "mcp_server": self.mcp_server_url
            })
            
        @self.app.route('/')
        def index():
            # Read error reporting configuration
            error_reporting_enabled = 'true' if ERROR_REPORTING_AVAILABLE else 'false'
            
            return f'''
            <!DOCTYPE html>
            <html>
            <head>
                <title>IPFS Datasets MCP Dashboard</title>
                <script>
                    // Set error reporting configuration
                    window.ERROR_REPORTING_ENABLED = {error_reporting_enabled};
                </script>
                <script src="/static/js/error-reporter.js"></script>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; }}
                    .container {{ max-width: 800px; margin: 0 auto; }}
                    .status {{ padding: 10px; margin: 10px 0; border-radius: 5px; }}
                    .healthy {{ background-color: #d4edda; color: #155724; }}
                    .error {{ background-color: #f8d7da; color: #721c24; }}
                    button {{ padding: 10px 20px; margin: 5px; }}
                    #output {{ background: #f8f9fa; padding: 10px; margin: 10px 0; border-radius: 5px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>IPFS Datasets MCP Dashboard</h1>
                    <div id="status" class="status">Loading...</div>
                    
                    <h2>Available Tools</h2>
                    <button onclick="testEcho()">Test Echo Tool</button>
                    <button onclick="testStatus()">Test Status Tool</button>
                    <button onclick="checkHealth()">Check Server Health</button>
                    
                    <h2>Output</h2>
                    <div id="output">Ready to execute tools...</div>
                </div>
                
                <script>
                async function checkHealth() {{
                    try {{
                        const response = await fetch('/api/health');
                        const data = await response.json();
                        document.getElementById('status').className = 'status healthy';
                        document.getElementById('status').textContent = 'Dashboard: ' + data.status;
                        document.getElementById('output').textContent = JSON.stringify(data, null, 2);
                    }} catch (error) {{
                        document.getElementById('status').className = 'status error';
                        document.getElementById('status').textContent = 'Error: ' + error.message;
                    }}
                }}
                
                async function testEcho() {{
                    try {{
                        const response = await fetch('/api/execute', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{
                                tool_name: 'echo',
                                parameters: {{ text: 'Hello from MCP Dashboard!' }}
                            }})
                        }});
                        const data = await response.json();
                        document.getElementById('output').textContent = JSON.stringify(data, null, 2);
                    }} catch (error) {{
                        document.getElementById('output').textContent = 'Error: ' + error.message;
                    }}
                }}
                
                async function testStatus() {{
                    try {{
                        const response = await fetch('/api/execute', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{
                                tool_name: 'status',
                                parameters: {{}}
                            }})
                        }});
                        const data = await response.json();
                        document.getElementById('output').textContent = JSON.stringify(data, null, 2);
                    }} catch (error) {{
                        document.getElementById('output').textContent = 'Error: ' + error.message;
                    }}
                }}
                
                // Check status on load
                checkHealth();
                </script>
            </body>
            </html>
            '''
            
        @self.app.route('/api/health')
        def api_health():
            return jsonify({
                "dashboard_status": "healthy",
                "mcp_server": self.mcp_server_url,
                "timestamp": datetime.now().isoformat()
            })
            
        @self.app.route('/api/execute', methods=['POST'])
        def api_execute():
            """Proxy tool execution to MCP server."""
            try:
                import requests
                data = request.get_json()
                
                response = requests.post(
                    f"{self.mcp_server_url}/execute",
                    json=data,
                    timeout=30
                )
                
                return jsonify(response.json())
                
            except Exception as e:
                return jsonify({
                    "error": f"Failed to connect to MCP server: {str(e)}",
                    "success": False
                }), 500
                
    def run(self):
        """Run the MCP dashboard."""
        logger.info(f"Starting MCP dashboard on {self.host}:{self.port}")
        self.app.run(host=self.host, port=self.port, debug=False)

def main():
    """Main entry point."""
    import sys
    import threading
    import time
    
    if len(sys.argv) > 1 and sys.argv[1] == '--dashboard-only':
        # Run dashboard only
        dashboard = MinimalMCPDashboard()
        dashboard.run()
    elif len(sys.argv) > 1 and sys.argv[1] == '--server-only':
        # Run server only
        server = MinimalMCPServer()
        server.run()
    else:
        # Run both server and dashboard
        server = MinimalMCPServer()
        dashboard = MinimalMCPDashboard()
        
        # Start server in a thread
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        
        # Give server time to start
        time.sleep(2)
        
        # Start dashboard (blocks)
        dashboard.run()

if __name__ == "__main__":
    main()