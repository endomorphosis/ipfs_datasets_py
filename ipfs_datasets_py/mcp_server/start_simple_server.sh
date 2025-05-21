#!/bin/bash
# Simple script to start the MCP server with the simplified implementation

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Add the parent directory to PYTHONPATH
export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"

# Start the server using the simple_server module
python -c "from ipfs_datasets_py.mcp_server.simple_server import start_simple_server; start_simple_server()"
