#!/bin/bash
set -e

echo "🐳 Starting IPFS Datasets Python in Docker..."

# Change to app directory
cd /app

# Ensure dependency checker is available and run it
if [ -f "tools/dependency_checker.py" ]; then
    echo "🔍 Running dependency checker..."
    python tools/dependency_checker.py --install-optional || {
        echo "⚠️  Some dependencies may be missing, continuing with available packages..."
    }
else
    echo "⚠️  Dependency checker not found, skipping dependency validation"
fi

# Initialize IPFS if not already initialized
if [ ! -d /root/.ipfs ]; then
    echo "🔗 Initializing IPFS..."
    ipfs init
fi

# Configure IPFS for container use
echo "⚙️  Configuring IPFS..."
ipfs config Addresses.API /ip4/0.0.0.0/tcp/5001
ipfs config Addresses.Gateway /ip4/0.0.0.0/tcp/8080
ipfs config --json API.HTTPHeaders.Access-Control-Allow-Origin '["*"]'
ipfs config --json API.HTTPHeaders.Access-Control-Allow-Methods '["PUT", "GET", "POST"]'

# Start IPFS daemon in background if requested
if [ "$1" = "ipfs-datasets-server" ] || [ "$1" = "with-ipfs" ] || [ "$START_IPFS" = "true" ]; then
    echo "🚀 Starting IPFS daemon..."
    ipfs daemon --enable-gc &
    IPFS_PID=$!
    
    # Wait for IPFS to be ready
    echo "⏳ Waiting for IPFS to be ready..."
    until ipfs id > /dev/null 2>&1; do
        sleep 1
    done
    echo "✅ IPFS is ready!"
fi

# Handle different command options
case "$1" in
    "ipfs-datasets-server"|"server")
        echo "🌐 Starting IPFS Datasets Server..."
        exec python -m ipfs_datasets_py.enterprise_api --host 0.0.0.0 --port 8000
        ;;
    "mcp-server")
        echo "🛠️  Starting MCP Server..."
        exec python -m ipfs_datasets_py.mcp_server --host 0.0.0.0 --port 8000
        ;;
    "mcp-dashboard")
        echo "📊 Starting MCP Dashboard..."
        export MCP_DASHBOARD_HOST=0.0.0.0
        export MCP_DASHBOARD_PORT=8899
        export MCP_DASHBOARD_BLOCKING=1
        exec python -m ipfs_datasets_py.mcp_dashboard
        ;;
    "dependency-check")
        echo "🔍 Running comprehensive dependency check..."
        exec python scripts/utilities/dependency_checker.py --install-optional --verbose
        ;;
    "worker")
        echo "⚙️  Starting Background Worker..."
        exec python -m ipfs_datasets_py.enterprise_api --worker-only
        ;;
    "shell"|"bash")
        echo "🐚 Starting interactive shell..."
        exec /bin/bash
        ;;
    *)
        echo "🎯 Executing: $@"
        exec "$@"
        ;;
esac