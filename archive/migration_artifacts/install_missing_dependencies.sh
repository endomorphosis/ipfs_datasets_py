#!/bin/bash
# Script to install missing dependencies for MCP tools

echo "Installing missing dependencies for IPFS datasets MCP tools..."

# For vector tools (requires FAISS or similar)
pip install faiss-cpu numpy

# For IPFS tools  
pip install ipfshttpclient

# For graph tools
pip install networkx rdflib

# For security tools
pip install cryptography pyjwt

# For web archive tools
pip install warcio beautifulsoup4 requests

# For additional dependencies
pip install aiofiles aiohttp

echo "Dependencies installation complete!"
