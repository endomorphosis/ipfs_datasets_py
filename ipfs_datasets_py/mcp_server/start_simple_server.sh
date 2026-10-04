#!/bin/bash
# Start the MCP server (stdio mode — the only supported access method).
#
# DEPRECATED: This script previously started the Flask-based simple_server.
# Flask is no longer supported.  The MCP stdio server is the canonical way
# to access ipfs_datasets tools.
#
# Migration guide:
#   AI assistants / VS Code: python -m ipfs_datasets_py.mcp_server
#   Shell users:              ipfs-datasets <command>
#   Programmatic:             from ipfs_datasets_py import DatasetManager

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Add the parent directory to PYTHONPATH
export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"

# Start the MCP stdio server
exec python -m ipfs_datasets_py.mcp_server "$@"
