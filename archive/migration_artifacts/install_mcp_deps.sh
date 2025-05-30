#!/bin/bash
# Script to install all required dependencies for MCP server

echo "Installing dependencies for the MCP server..."

# Install modelcontextprotocol and required dependencies
pip install --upgrade pip setuptools wheel
pip install --force-reinstall modelcontextprotocol==0.1.0
pip install httpx pyyaml httpcore

# Install other possibly required packages
pip install fastapi uvicorn pydantic

# Install project in development mode
pip install -e .

echo "Installation complete. Running a test import..."
python -c "import modelcontextprotocol; print(f'modelcontextprotocol version: {getattr(modelcontextprotocol, \"__version__\", \"unknown\")}')"

echo "Done!"
