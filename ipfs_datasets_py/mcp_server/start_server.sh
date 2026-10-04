#!/bin/bash
# Start the IPFS Datasets MCP server

# Default values
HOST="0.0.0.0"
PORT=8000
IPFS_KIT_MCP_URL=""
CONFIG_PATH=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  key="$1"

  case $key in
    --host)
      HOST="$2"
      shift
      shift
      ;;
    --port)
      PORT="$2"
      shift
      shift
      ;;
    --ipfs-kit-mcp)
      IPFS_KIT_MCP_URL="$2"
      shift
      shift
      ;;
    --config)
      CONFIG_PATH="$2"
      shift
      shift
      ;;
    *)
      # Unknown option
      echo "Unknown option: $1"
      echo "Usage: $0 [--host <host>] [--port <port>] [--ipfs-kit-mcp <url>] [--config <config_path>]"
      exit 1
      ;;
  esac
done

# Build the command
CMD="python -m ipfs_datasets_py.mcp_server.server --host $HOST --port $PORT"

if [ ! -z "$IPFS_KIT_MCP_URL" ]; then
  CMD="$CMD --ipfs-kit-mcp-url $IPFS_KIT_MCP_URL"
fi

if [ ! -z "$CONFIG_PATH" ]; then
  CMD="$CMD --config $CONFIG_PATH"
fi

# Print startup message
echo "Starting IPFS Datasets MCP Server"
echo "Host: $HOST"
echo "Port: $PORT"
if [ ! -z "$IPFS_KIT_MCP_URL" ]; then
  echo "IPFS Kit MCP URL: $IPFS_KIT_MCP_URL"
else
  echo "IPFS Kit Integration: Direct"
fi
if [ ! -z "$CONFIG_PATH" ]; then
  echo "Config Path: $CONFIG_PATH"
else
  echo "Config Path: Default"
fi
echo

# Run the server
echo "Running: $CMD"
exec $CMD
