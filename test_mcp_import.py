import sys
import os
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).resolve().parents[1] # Adjust based on actual project structure
sys.path.insert(0, str(project_root))

print(f"Python path: {sys.path}")
print(f"Current directory: {os.getcwd()}")

# Try importing the module directly
# try:
#     print("Trying to import modelcontextprotocol...")
#     import modelcontextprotocol
#     print(f"Successfully imported modelcontextprotocol version: {getattr(modelcontextprotocol, '__version__', 'unknown')}")
# except ImportError as e:
#     print(f"Failed to import modelcontextprotocol: {e}")

# Try importing from ipfs_datasets_py
try:
    print("\nTrying to import MCP server parts from ipfs_datasets_py...")
    import ipfs_datasets_py
    print(f"Successfully imported ipfs_datasets_py version: {getattr(ipfs_datasets_py, '__version__', 'unknown')}")
    
    # Try importing the mcp_server module
    print("Trying to import ipfs_datasets_py.mcp_server...")
    from ipfs_datasets_py import mcp_server
    print("Successfully imported mcp_server module")
    
    # Check for specific classes and functions
    print("Checking for MCP server components...")
    server_elements = dir(mcp_server)
    print(f"Found: {server_elements}")
    
    if hasattr(mcp_server, 'IPFSDatasetsMCPServer'):
        print("IPFSDatasetsMCPServer class is available")
    else:
        print("IPFSDatasetsMCPServer class is NOT available")
        
    if hasattr(mcp_server, 'start_server'):
        print("start_server function is available")
    else:
        print("start_server function is NOT available")
        
except ImportError as e:
    print(f"Failed to import MCP server from ipfs_datasets_py: {e}")
