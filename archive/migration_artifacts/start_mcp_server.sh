#!/bin/bash
# Start MCP Server for IPFS Datasets
# This script starts the MCP server that VS Code Copilot will connect to

echo "Starting IPFS Datasets MCP Server..."

# Set environment variables
export PYTHONPATH="/home/barberb/ipfs_datasets_py"
export IPFS_DATASETS_CONFIG="/home/barberb/ipfs_datasets_py/config/mcp_config.yaml"

# Change to project directory
cd /home/barberb/ipfs_datasets_py

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
fi

# Start the MCP server
echo "Starting MCP server on localhost:8000..."
python -m ipfs_datasets_py.mcp_server --host 127.0.0.1 --port 8000 --debug

echo "MCP Server stopped."
