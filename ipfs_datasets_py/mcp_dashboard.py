#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MCP Dashboard for IPFS Datasets Python.

This module extends the admin dashboard to provide MCP-specific functionality,
including MCP tool discovery, execution, and real-time monitoring.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Web server
try:
    from flask import Flask, jsonify, request, render_template, send_from_directory
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# Import existing dashboard functionality
from .admin_dashboard import AdminDashboard, DashboardConfig

# Import MCP server components
try:
    from .mcp_server.simple_server import SimpleIPFSDatasetsMCPServer
    from .mcp_server.configs import configs
    MCP_SERVER_AVAILABLE = True
except ImportError:
    MCP_SERVER_AVAILABLE = False


class MCPDashboardConfig(DashboardConfig):
    """Configuration for MCP Dashboard."""
    
    def __init__(
        self,
        mcp_server_port: int = 8001,
        mcp_server_host: str = "localhost",
        enable_tool_execution: bool = True,
        tool_timeout: float = 30.0,
        max_concurrent_tools: int = 5,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.mcp_server_port = mcp_server_port
        self.mcp_server_host = mcp_server_host
        self.enable_tool_execution = enable_tool_execution
        self.tool_timeout = tool_timeout
        self.max_concurrent_tools = max_concurrent_tools


class MCPDashboard(AdminDashboard):
    """
    MCP Dashboard extending AdminDashboard with MCP-specific functionality.
    
    This dashboard provides:
    - MCP tool discovery and listing
    - Real-time MCP server status monitoring
    - Tool execution interface with results
    - JavaScript SDK endpoints
    """
    
    def __init__(self):
        """Initialize the MCP dashboard."""
        super().__init__()
        self.mcp_server = None
        self.mcp_config = None
        self.tool_execution_history = []
        self.active_tool_executions = {}
        
    def configure(self, config: MCPDashboardConfig) -> None:
        """Configure the MCP dashboard.
        
        Args:
            config: MCP dashboard configuration
        """
        super().configure(config)
        self.mcp_config = config
        
        # Initialize MCP server if available
        if MCP_SERVER_AVAILABLE:
            try:
                self.mcp_server = SimpleIPFSDatasetsMCPServer(configs)
                self._discover_mcp_tools()
            except Exception as e:
                self.logger.error(f"Failed to initialize MCP server: {e}")
                
    def _discover_mcp_tools(self) -> Dict[str, Any]:
        """Discover available MCP tools."""
        if not self.mcp_server:
            return {}
            
        tools_info = {}
        tools_dir = Path(__file__).parent / "mcp_server" / "tools"
        
        if tools_dir.exists():
            for tool_category in tools_dir.iterdir():
                if tool_category.is_dir() and not tool_category.name.startswith('_'):
                    category_tools = self._scan_tool_category(tool_category)
                    if category_tools:
                        tools_info[tool_category.name] = category_tools
        
        self.logger.info(f"Discovered {len(tools_info)} tool categories")
        return tools_info
        
    def _scan_tool_category(self, category_path: Path) -> List[Dict[str, Any]]:
        """Scan a tool category directory for available tools."""
        tools = []
        
        for tool_file in category_path.glob("*.py"):
            if tool_file.name.startswith('_') or tool_file.name == '__init__.py':
                continue
                
            tool_info = {
                "name": tool_file.stem,
                "file": str(tool_file),
                "category": category_path.name,
                "description": "MCP Tool",  # Will be updated when tool is loaded
                "parameters": [],
                "last_modified": datetime.fromtimestamp(tool_file.stat().st_mtime).isoformat()
            }
            tools.append(tool_info)
            
        return tools
        
    def _setup_routes(self) -> None:
        """Set up Flask routes for the MCP dashboard."""
        # Set up parent routes first
        super()._setup_routes()
        
        if not self.app:
            return
            
        # MCP-specific routes
        @self.app.route('/mcp')
        def mcp_dashboard():
            """Render the MCP dashboard page."""
            tools_info = self._discover_mcp_tools()
            server_status = self._get_mcp_server_status()
            
            dashboard_data = {
                "tools_info": tools_info,
                "server_status": server_status,
                "execution_history": self.tool_execution_history[-50:],  # Last 50 executions
                "active_executions": len(self.active_tool_executions),
                "dashboard_config": self.mcp_config.__dict__ if self.mcp_config else {},
                "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            return render_template('mcp_dashboard.html', **dashboard_data)
            
        @self.app.route('/api/mcp/tools')
        def api_mcp_tools():
            """API endpoint to get available MCP tools."""
            return jsonify(self._discover_mcp_tools())
            
        @self.app.route('/api/mcp/tools/<category>/<tool_name>')
        def api_mcp_tool_info(category, tool_name):
            """Get detailed information about a specific tool."""
            tools_info = self._discover_mcp_tools()
            
            if category not in tools_info:
                return jsonify({"error": f"Category '{category}' not found"}), 404
                
            tool = next((t for t in tools_info[category] if t['name'] == tool_name), None)
            if not tool:
                return jsonify({"error": f"Tool '{tool_name}' not found in category '{category}'"}), 404
                
            return jsonify(tool)
            
        @self.app.route('/api/mcp/tools/<category>/<tool_name>/execute', methods=['POST'])
        def api_execute_mcp_tool(category, tool_name):
            """Execute an MCP tool with given parameters."""
            if not self.mcp_config or not self.mcp_config.enable_tool_execution:
                return jsonify({"error": "Tool execution is disabled"}), 403
                
            if len(self.active_tool_executions) >= self.mcp_config.max_concurrent_tools:
                return jsonify({"error": "Maximum concurrent tool executions reached"}), 429
                
            # Get parameters from request
            params = request.json or {}
            execution_id = f"{category}_{tool_name}_{int(time.time() * 1000)}"
            
            # Start tool execution
            execution_record = {
                "id": execution_id,
                "category": category,
                "tool_name": tool_name,
                "parameters": params,
                "start_time": datetime.now().isoformat(),
                "status": "running",
                "result": None,
                "error": None
            }
            
            self.active_tool_executions[execution_id] = execution_record
            
            try:
                # In a real implementation, this would be async
                # For now, we'll simulate tool execution
                result = self._execute_tool_sync(category, tool_name, params)
                
                execution_record.update({
                    "status": "completed",
                    "result": result,
                    "end_time": datetime.now().isoformat()
                })
                
            except Exception as e:
                execution_record.update({
                    "status": "failed",
                    "error": str(e),
                    "end_time": datetime.now().isoformat()
                })
                
            # Move to history
            self.tool_execution_history.append(execution_record.copy())
            del self.active_tool_executions[execution_id]
            
            return jsonify(execution_record)
            
        @self.app.route('/api/mcp/executions/<execution_id>')
        def api_get_execution_status(execution_id):
            """Get the status of a tool execution."""
            # Check active executions
            if execution_id in self.active_tool_executions:
                return jsonify(self.active_tool_executions[execution_id])
                
            # Check history
            for execution in self.tool_execution_history:
                if execution['id'] == execution_id:
                    return jsonify(execution)
                    
            return jsonify({"error": "Execution not found"}), 404
            
        @self.app.route('/api/mcp/status')
        def api_mcp_status():
            """Get MCP server status."""
            return jsonify(self._get_mcp_server_status())
            
        @self.app.route('/api/mcp/history')
        def api_execution_history():
            """Get tool execution history."""
            limit = request.args.get('limit', 50, type=int)
            return jsonify({
                "executions": self.tool_execution_history[-limit:],
                "total": len(self.tool_execution_history)
            })
            
        # JavaScript SDK endpoint
        @self.app.route('/static/js/mcp-sdk.js')
        def mcp_sdk():
            """Serve the MCP JavaScript SDK."""
            return send_from_directory(
                self.app.static_folder,
                'js/mcp-sdk.js',
                mimetype='application/javascript'
            )
            
    def _execute_tool_sync(self, category: str, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool synchronously (placeholder implementation)."""
        # This is a placeholder - in a real implementation, this would
        # call the actual MCP tool execution logic
        
        # Simulate some processing time
        time.sleep(0.5)
        
        return {
            "message": f"Tool {category}/{tool_name} executed successfully",
            "parameters_received": params,
            "execution_time": 0.5,
            "timestamp": datetime.now().isoformat()
        }
        
    def _get_mcp_server_status(self) -> Dict[str, Any]:
        """Get the current status of the MCP server."""
        if not self.mcp_server:
            return {
                "status": "unavailable",
                "message": "MCP server not initialized"
            }
            
        return {
            "status": "running",
            "server_type": "SimpleIPFSDatasetsMCPServer",
            "tools_available": len(self._discover_mcp_tools()),
            "active_executions": len(self.active_tool_executions),
            "total_executions": len(self.tool_execution_history),
            "uptime": time.time() - self.start_time,
            "config": {
                "host": self.mcp_config.mcp_server_host if self.mcp_config else "localhost",
                "port": self.mcp_config.mcp_server_port if self.mcp_config else 8001,
                "tool_execution_enabled": self.mcp_config.enable_tool_execution if self.mcp_config else False
            }
        }
        
    def create_mcp_dashboard_template(self) -> str:
        """Create the MCP dashboard HTML template."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IPFS Datasets MCP Dashboard</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/bootstrap.min.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/dashboard.css') }}">
</head>
<body>
    <div class="container-fluid">
        <div class="row">
            <nav class="col-md-2 d-none d-md-block bg-light sidebar">
                <div class="sidebar-sticky">
                    <ul class="nav flex-column">
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('index') }}">
                                Main Dashboard
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link active" href="{{ url_for('mcp_dashboard') }}">
                                MCP Dashboard
                            </a>
                        </li>
                    </ul>
                </div>
            </nav>

            <main role="main" class="col-md-9 ml-sm-auto col-lg-10 px-4">
                <div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
                    <h1 class="h2">MCP Server Dashboard</h1>
                    <div class="btn-toolbar mb-2 mb-md-0">
                        <button class="btn btn-sm btn-outline-secondary" onclick="refreshDashboard()">
                            Refresh
                        </button>
                    </div>
                </div>

                <!-- Server Status -->
                <div class="row mb-4">
                    <div class="col-md-12">
                        <div class="card">
                            <div class="card-header">
                                <h5>MCP Server Status</h5>
                            </div>
                            <div class="card-body">
                                <div class="row">
                                    <div class="col-md-3">
                                        <strong>Status:</strong>
                                        <span class="badge badge-{{ 'success' if server_status.status == 'running' else 'danger' }}">
                                            {{ server_status.status }}
                                        </span>
                                    </div>
                                    <div class="col-md-3">
                                        <strong>Tools Available:</strong> {{ server_status.tools_available }}
                                    </div>
                                    <div class="col-md-3">
                                        <strong>Active Executions:</strong> {{ active_executions }}
                                    </div>
                                    <div class="col-md-3">
                                        <strong>Total Executions:</strong> {{ server_status.total_executions }}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Tools Grid -->
                <div class="row mb-4">
                    <div class="col-md-12">
                        <div class="card">
                            <div class="card-header">
                                <h5>Available Tools</h5>
                            </div>
                            <div class="card-body">
                                <div id="tools-container">
                                    {% for category, tools in tools_info.items() %}
                                    <div class="mb-4">
                                        <h6>{{ category.replace('_', ' ').title() }}</h6>
                                        <div class="row">
                                            {% for tool in tools %}
                                            <div class="col-md-4 mb-3">
                                                <div class="card tool-card" data-category="{{ category }}" data-tool="{{ tool.name }}">
                                                    <div class="card-body">
                                                        <h6 class="card-title">{{ tool.name }}</h6>
                                                        <p class="card-text small">{{ tool.description }}</p>
                                                        <button class="btn btn-sm btn-primary execute-tool-btn">
                                                            Execute
                                                        </button>
                                                    </div>
                                                </div>
                                            </div>
                                            {% endfor %}
                                        </div>
                                    </div>
                                    {% endfor %}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Execution History -->
                <div class="row">
                    <div class="col-md-12">
                        <div class="card">
                            <div class="card-header">
                                <h5>Execution History</h5>
                            </div>
                            <div class="card-body">
                                <div class="table-responsive">
                                    <table class="table table-sm">
                                        <thead>
                                            <tr>
                                                <th>Tool</th>
                                                <th>Status</th>
                                                <th>Start Time</th>
                                                <th>Duration</th>
                                                <th>Actions</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {% for execution in execution_history %}
                                            <tr>
                                                <td>{{ execution.category }}/{{ execution.tool_name }}</td>
                                                <td>
                                                    <span class="badge badge-{{ 'success' if execution.status == 'completed' else 'danger' if execution.status == 'failed' else 'warning' }}">
                                                        {{ execution.status }}
                                                    </span>
                                                </td>
                                                <td>{{ execution.start_time }}</td>
                                                <td>{{ execution.get('end_time', 'N/A') }}</td>
                                                <td>
                                                    <button class="btn btn-sm btn-outline-primary view-execution-btn" data-id="{{ execution.id }}">
                                                        View
                                                    </button>
                                                </td>
                                            </tr>
                                            {% endfor %}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    </div>

    <!-- Tool Execution Modal -->
    <div class="modal fade" id="toolExecutionModal" tabindex="-1">
        <div class="modal-dialog modal-lg">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Execute Tool</h5>
                    <button type="button" class="close" data-dismiss="modal">
                        <span>&times;</span>
                    </button>
                </div>
                <div class="modal-body">
                    <form id="toolExecutionForm">
                        <div class="form-group">
                            <label>Tool:</label>
                            <input type="text" class="form-control" id="toolName" readonly>
                        </div>
                        <div class="form-group">
                            <label>Parameters (JSON):</label>
                            <textarea class="form-control" id="toolParameters" rows="5" placeholder='{"param1": "value1"}'></textarea>
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-primary" id="executeToolBtn">Execute</button>
                </div>
            </div>
        </div>
    </div>

    <script src="{{ url_for('static', filename='js/jquery.min.js') }}"></script>
    <script src="{{ url_for('static', filename='js/bootstrap.bundle.min.js') }}"></script>
    <script src="{{ url_for('static', filename='js/mcp-sdk.js') }}"></script>
    <script>
        $(document).ready(function() {
            // Initialize MCP SDK
            window.mcpSDK = new MCPClient('{{ request.host_url }}api/mcp');
            
            // Tool execution handlers
            $('.execute-tool-btn').click(function() {
                const card = $(this).closest('.tool-card');
                const category = card.data('category');
                const tool = card.data('tool');
                
                $('#toolName').val(category + '/' + tool);
                $('#toolExecutionModal').modal('show');
            });
            
            $('#executeToolBtn').click(function() {
                const toolName = $('#toolName').val().split('/');
                const category = toolName[0];
                const tool = toolName[1];
                const parameters = $('#toolParameters').val();
                
                try {
                    const params = parameters ? JSON.parse(parameters) : {};
                    window.mcpSDK.executeTool(category, tool, params)
                        .then(result => {
                            alert('Tool executed successfully!');
                            $('#toolExecutionModal').modal('hide');
                            location.reload();
                        })
                        .catch(error => {
                            alert('Tool execution failed: ' + error.message);
                        });
                } catch (e) {
                    alert('Invalid JSON parameters: ' + e.message);
                }
            });
        });
        
        function refreshDashboard() {
            location.reload();
        }
    </script>
</body>
</html>"""

    def _create_mcp_templates(self) -> None:
        """Create MCP-specific template files."""
        if not self.app:
            return

        templates_dir = Path(self.app.template_folder)
        static_dir = Path(self.app.static_folder)
        templates_dir.mkdir(parents=True, exist_ok=True)
        static_dir.mkdir(parents=True, exist_ok=True)

        # Create MCP dashboard template in Flask templates folder
        mcp_template_path = templates_dir / "mcp_dashboard.html"
        if not mcp_template_path.exists():
            with open(mcp_template_path, 'w') as f:
                f.write(self.create_mcp_dashboard_template())

        # Ensure MCP JavaScript SDK exists in static/js
        js_dir = static_dir / "js"
        js_dir.mkdir(parents=True, exist_ok=True)
        mcp_sdk_path = js_dir / "mcp-sdk.js"
        if not mcp_sdk_path.exists():
            mcp_sdk_path.write_text(
                """
// Minimal MCP JavaScript SDK stub
class MCPError extends Error {
    constructor(message, status = 500, data = null) {
        super(message);
        this.name = 'MCPError';
        this.status = status;
        this.data = data;
    }
}

class MCPClient {
    constructor(baseUrl, options = {}) {
        this.baseUrl = baseUrl.replace(/\/$/, '');
        this.timeout = options.timeout || 30000;
    }

    async _request(path, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), this.timeout);
        try {
            const res = await fetch(`${this.baseUrl}${path}`, { ...options, signal: controller.signal });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new MCPError(data.error || res.statusText, res.status, data);
            return data;
        } finally {
            clearTimeout(timer);
        }
    }

    getServerStatus() { return this._request('/status'); }
    getTools() { return this._request('/tools'); }
    getTool(category, tool) { return this._request(`/tools/${encodeURIComponent(category)}/${encodeURIComponent(tool)}`); }
    executeTool(category, tool, params = {}) {
        return this._request(`/tools/${encodeURIComponent(category)}/${encodeURIComponent(tool)}/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params)
        });
    }

    startStatusPolling(intervalMs = 5000, cb = () => {}) {
        let stopped = false;
        const tick = async () => {
            if (stopped) return;
            try { cb(null, await this.getServerStatus()); } catch (e) { cb(e); }
            setTimeout(tick, intervalMs);
        };
        setTimeout(tick, 0);
        return () => { stopped = true; };
    }
}

window.MCPClient = MCPClient;
window.MCPError = MCPError;
                """.strip()
            )


def start_mcp_dashboard(config: Optional[MCPDashboardConfig] = None) -> MCPDashboard:
    """
    Start the MCP dashboard with the given configuration.
    
    Args:
        config: MCP dashboard configuration
        
    Returns:
        MCPDashboard: The dashboard instance
    """
    dashboard = MCPDashboard()
    dashboard.configure(config or MCPDashboardConfig())
    dashboard._create_mcp_templates()
    dashboard.start()
    return dashboard


if __name__ == "__main__":
    # Start the MCP dashboard
    host = os.environ.get("MCP_DASHBOARD_HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("MCP_DASHBOARD_PORT", "8080"))
    except ValueError:
        port = 8080

    config = MCPDashboardConfig(host=host, port=port, mcp_server_port=8001)
    
    dashboard = start_mcp_dashboard(config)
    if dashboard and dashboard.get_status().get("running"):
        print(f"MCP Dashboard running at http://{config.host}:{config.port}/mcp")
    else:
        print(
            f"Failed to start MCP Dashboard on http://{config.host}:{config.port}. "
            "Check logs for details or choose a different port via MCP_DASHBOARD_PORT."
        )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass