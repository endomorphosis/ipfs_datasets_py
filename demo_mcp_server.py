#!/usr/bin/env python3
"""
Demo script for starting and testing the IPFS Datasets MCP Server.

This script demonstrates how to start the MCP server and make a sample request to it.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
import signal
import subprocess
import threading

try:
    import requests
    has_requests = True
except ImportError:
    print("Warning: 'requests' package not found. Installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests
    has_requests = True

# Add project root to path
# sys.path.insert(0, str(Path(__file__).resolve().parent)) # Removed this line

def start_server_process():
    """Start the MCP server as a separate process."""
    print("Starting MCP server...")
    
    # Determine server script path
    server_script_path = Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "server.py"
    
    # Check if the MCP server script exists
    if not server_script_path.exists():
        print(f"Error: MCP server script not found at {server_script_path}")
        return None
    
    # Start the standard server by executing the script file directly
    print(f"Starting standard server from: {server_script_path}")
    cmd = [
        sys.executable, # Use the Python executable from the activated venv
        str(server_script_path) # Execute the server script file directly
    ]
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    # Print server output in a separate thread
    def print_output():
        # Ensure process.stdout is not None before iterating
        if process.stdout:
            for line in iter(process.stdout.readline, ''):
                print(f"[SERVER] {line.strip()}")
        
        output_thread = threading.Thread(target=print_output)
        output_thread.daemon = True
        output_thread.start()
        
        return process

def test_server_tools():
    """Make requests to the server to test its tools."""
    print("\nTesting server tools...")
    
    # List available tools
    try:
        # Note: This test function is designed for the simplified HTTP server.
        # It will not work with the standard stdio MCP server.
        # We will rely on the system's MCP connection status instead.
        print("Skipping HTTP tool tests as standard MCP server uses stdio transport.")
        
    except Exception as e:
        print(f"Error testing server: {e}")


def main():
    """Main function to start and test the server."""
    parser = argparse.ArgumentParser(description="Start and test the IPFS Datasets MCP Server")
    parser.add_argument("--test-only", action="store_true", help="Only test an already running server")
    args = parser.parse_args()
    
    server_process = None
    exit_code = 0
    
    try:
        if not args.test_only:
            print("=" * 60)
            print("IPFS Datasets MCP Server Demo")
            print("=" * 60)
            
            server_process = start_server_process()
            if not server_process:
                print("Failed to start server process")
                return 1
            
            # Wait for server to start (This check might not work for stdio server)
            print("Waiting for server to start...")
            # We will rely on the system's "Connected MCP Servers" list instead
            print("Please check 'Connected MCP Servers' in the environment details.")
            print("Press Ctrl+C to stop the server once it's running or you see errors.")
            
            # Keep the main thread alive while the server runs in the background
            while True:
                time.sleep(1)

        else:
            print("Testing pre-existing server...")
            # This test logic is for the simplified HTTP server and is now obsolete
            print("Test-only mode for HTTP server is not applicable to standard MCP server.")
        
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        exit_code = 130
    except Exception as e:
        print(f"Error in main: {e}")
        exit_code = 1
    finally:
        if server_process:
            print("\nStopping server...")
            try:
                server_process.terminate()
                server_process.wait(timeout=5)
                print("Server stopped")
            except subprocess.TimeoutExpired:
                print("Server did not exit gracefully, killing...")
                server_process.kill()

    return exit_code

if __name__ == "__main__":
    sys.exit(main())
