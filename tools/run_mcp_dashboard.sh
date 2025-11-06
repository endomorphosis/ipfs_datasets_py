#!/usr/bin/env bash
set -euo pipefail

# Defaults
HOST=${MCP_DASHBOARD_HOST:-127.0.0.1}
PORT=${MCP_DASHBOARD_PORT:-8899}
LOG=${LOG:-mcp_dashboard.out}
BLOCKING=${MCP_DASHBOARD_BLOCKING:-0}

# Change to project directory
cd "$(dirname "$0")/.." || exit 1

# Activate venv if present, otherwise create it
if [ -d ".venv" ]; then
  echo "Activating existing virtual environment..."
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "Creating virtual environment..."
  python3 -m venv .venv
  source .venv/bin/activate
  
  echo "Installing dependencies..."
  pip install --upgrade pip
  pip install -e . 2>/dev/null || pip install -r requirements.txt
  
  # Install dashboard dependencies
  pip install flask dash dash-bootstrap-components plotly
fi

# Export environment variables
export MCP_DASHBOARD_HOST="${HOST}"
export MCP_DASHBOARD_PORT="${PORT}"
export MCP_DASHBOARD_BLOCKING="${BLOCKING}"

echo "Starting MCP Dashboard on ${HOST}:${PORT}..."
python -m ipfs_datasets_py.mcp_dashboard
