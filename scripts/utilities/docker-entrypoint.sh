#!/usr/bin/env bash
set -e

# Docker entrypoint script for GraphRAG Website Processor
# Handles initialization, health checks, and graceful shutdown

echo "Starting GraphRAG Website Processor..."

# Initialize IPFS if not already initialized
if [ ! -f /root/.ipfs/config ]; then
    echo "Initializing IPFS..."
    ipfs init --profile server
fi

# Configure IPFS for container environment
echo "Configuring IPFS..."
ipfs config Addresses.API /ip4/0.0.0.0/tcp/5001
ipfs config Addresses.Gateway /ip4/0.0.0.0/tcp/8080
ipfs config --json Addresses.Swarm '["/ip4/0.0.0.0/tcp/4001", "/ip4/0.0.0.0/udp/4001/quic"]'

# Start IPFS daemon in background
echo "Starting IPFS daemon..."
ipfs daemon --migrate=true --agent-version-suffix=docker &
IPFS_PID=$!

# Wait for IPFS to be ready
echo "Waiting for IPFS to be ready..."
for i in {1..30}; do
    if ipfs id > /dev/null 2>&1; then
        echo "IPFS is ready"
        break
    fi
    echo "Waiting for IPFS... ($i/30)"
    sleep 2
done

# Function to cleanup on exit
cleanup() {
    echo "Shutting down gracefully..."
    if [ ! -z "$IPFS_PID" ]; then
        kill $IPFS_PID 2>/dev/null || true
    fi
    if [ ! -z "$APP_PID" ]; then
        kill $APP_PID 2>/dev/null || true
    fi
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# Initialize database if needed
if [ "$INIT_DB" = "true" ]; then
    echo "Initializing database..."
    python -m ipfs_datasets_py.scripts.init_database
fi

# Determine what to run based on command
case "$1" in
    "ipfs-datasets-server")
        echo "Starting GraphRAG API server..."
        python -m ipfs_datasets_py.enterprise_api &
        APP_PID=$!
        ;;
    "worker")
        echo "Starting background job worker..."
        python -m ipfs_datasets_py.enterprise_api --worker-only &
        APP_PID=$!
        ;;
    "shell")
        echo "Starting interactive shell..."
        exec /bin/bash
        ;;
    *)
        echo "Starting custom command: $@"
        exec "$@"
        ;;
esac

# Wait for the application to finish
if [ ! -z "$APP_PID" ]; then
    wait $APP_PID
fi

# Clean up
cleanup