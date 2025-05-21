#!/bin/bash
# Setup script for IPFS Datasets MCP server

# Print colored output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}Setting up IPFS Datasets MCP server...${NC}"

# Make sure we're in the right directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "$SCRIPT_DIR" || {
  echo -e "${RED}Failed to change to script directory${NC}"
  exit 1
}

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 is not installed. Please install Python 3 first.${NC}"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
MINIMUM_VERSION="3.8"

if [ "$(printf '%s\n' "$MINIMUM_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$MINIMUM_VERSION" ]; then
    echo -e "${RED}Python version must be at least $MINIMUM_VERSION, but found $PYTHON_VERSION${NC}"
    exit 1
fi

# Create a virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo -e "${BLUE}Creating virtual environment...${NC}"
    python3 -m venv .venv || {
        echo -e "${RED}Failed to create virtual environment${NC}"
        exit 1
    }
fi

# Activate the virtual environment
echo -e "${BLUE}Activating virtual environment...${NC}"
source .venv/bin/activate || {
    echo -e "${RED}Failed to activate virtual environment${NC}"
    exit 1
}

# Install dependencies
echo -e "${BLUE}Installing dependencies...${NC}"
pip install -U pip setuptools wheel || {
    echo -e "${RED}Failed to upgrade pip, setuptools, and wheel${NC}"
    exit 1
}

# Install MCP server dependencies
pip install modelcontextprotocol httpx pyyaml || {
    echo -e "${RED}Failed to install MCP server dependencies${NC}"
    exit 1
}

# Install ipfs-datasets-py in development mode
echo -e "${BLUE}Installing ipfs-datasets-py in development mode...${NC}"
pip install -e ../../ || {
    echo -e "${RED}Failed to install ipfs-datasets-py${NC}"
    exit 1
}

# Try importing key modules to verify installation
echo -e "${BLUE}Verifying installation...${NC}"
python3 -c "from modelcontextprotocol.server import FastMCP; from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPServer; print('Installation verified!')" || {
    echo -e "${RED}Failed to verify installation${NC}"
    exit 1
}

echo -e "${GREEN}Setup complete!${NC}"
echo -e "To activate the virtual environment, run:"
echo -e "  ${BLUE}source .venv/bin/activate${NC}"
echo -e "To start the MCP server, run:"
echo -e "  ${BLUE}python -m ipfs_datasets_py.mcp_server.server${NC}"
echo -e "To test the MCP server, run:"
echo -e "  ${BLUE}python -m ipfs_datasets_py.mcp_server.test_mcp_server${NC}"
