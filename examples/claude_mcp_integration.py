"""
Example of using the IPFS Datasets MCP server with Claude.

This example demonstrates how Claude can interact with IPFS datasets through the MCP server.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import subprocess
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ipfs_datasets_py.mcp_server import start_server


def start_mcp_server_background():
    """Start the MCP server in the background."""
    print("Starting IPFS Datasets MCP server in the background...")

    # Start the server as a subprocess
    process = subprocess.Popen(
        [sys.executable, "-c", "from ipfs_datasets_py.mcp_server import start_server; start_server(host='localhost', port=8123)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # Give the server some time to start
    time.sleep(3)

    return process


def main():
    """Run the demonstration."""
    # Start the MCP server
    server_process = start_mcp_server_background()

    try:
        print("\nMCP server is now running. Claude can access IPFS datasets through the MCP API.")
        print("You can use the following server URL in your Claude conversations:")
        print("http://localhost:8123")

        print("\nPress Ctrl+C to stop the server and exit...")

        # Wait for user to press Ctrl+C
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping the MCP server...")
    finally:
        # Stop the server
        server_process.terminate()
        server_process.wait()
        print("Server stopped.")


if __name__ == "__main__":
    main()
