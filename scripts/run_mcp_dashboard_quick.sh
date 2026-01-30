#!/usr/bin/env bash
set -euo pipefail

# IPFS Datasets MCP Dashboard - Quick Launcher
# Focuses on essential dependencies for fast startup

# Defaults
HOST=${MCP_DASHBOARD_HOST:-127.0.0.1}
PORT=${MCP_DASHBOARD_PORT:-8899}
BLOCKING=${MCP_DASHBOARD_BLOCKING:-0}

# Change to project directory
cd "$(dirname "$0")/.." || exit 1

# Function to check if a Python package is installed
check_package() {
    python -c "import $1" 2>/dev/null
}

# Function to install critical packages only
install_critical_packages() {
    local missing=()
    
    # Essential web framework packages
    if ! check_package flask; then missing+=("flask"); fi
    if ! check_package dash; then missing+=("dash"); fi
    if ! check_package plotly; then missing+=("plotly"); fi
    if ! check_package dash_bootstrap_components; then missing+=("dash-bootstrap-components"); fi
    
    # Core functionality
    if ! check_package fastapi; then missing+=("fastapi"); fi
    if ! check_package pydantic; then missing+=("pydantic"); fi
    if ! check_package cachetools; then missing+=("cachetools"); fi
    
    if [ ${#missing[@]} -gt 0 ]; then
        echo "Installing critical packages: ${missing[*]}"
        pip install --no-cache-dir "${missing[@]}"
    fi
}

echo "🚀 Starting IPFS Datasets MCP Dashboard..."

# Activate or create virtual environment
if [ -d ".venv" ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
else
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -e . 2>/dev/null || echo "Project installation skipped"
fi

# Install only critical packages for immediate functionality
install_critical_packages

# Set environment variables
export MCP_DASHBOARD_HOST="${HOST}"
export MCP_DASHBOARD_PORT="${PORT}"
export MCP_DASHBOARD_BLOCKING="${BLOCKING}"

echo "✅ Quick setup complete. Starting dashboard on ${HOST}:${PORT}"
echo "💡 Run 'python scripts/utilities/dependency_checker.py' for comprehensive dependency installation (includes FAISS, vector databases, etc.)"

# Start the dashboard
exec python -m ipfs_datasets_py.mcp_dashboard