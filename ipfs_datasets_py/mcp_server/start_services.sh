#!/bin/bash
# Start script for MCP server and dashboard in Docker

set -e

echo "Starting IPFS Datasets MCP Server and Dashboard..."

# Start MCP server in background
echo "Starting MCP server on port 8000..."
python -m ipfs_datasets_py.mcp_server --host 0.0.0.0 --port 8000 --http &
MCP_PID=$!

# Start MCP dashboard in background  
echo "Starting MCP dashboard on port 8080..."
python -c "
import ipfs_datasets_py.mcp_dashboard as dashboard
config = dashboard.MCPDashboardConfig(host='0.0.0.0', port=8080, mcp_server_port=8000)
app = dashboard.start_mcp_dashboard(config)
print('MCP Dashboard running at http://0.0.0.0:8080/mcp')
try:
    import time
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
" &
DASHBOARD_PID=$!

# Wait for either process to exit
wait -n

# Kill the other process if one exits
kill $MCP_PID $DASHBOARD_PID 2>/dev/null || true

echo "Services stopped"