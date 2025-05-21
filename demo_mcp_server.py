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
sys.path.insert(0, str(Path(__file__).resolve().parent))

def start_server_process():
    """Start the MCP server as a separate process."""
    print("Starting MCP server...")
    
    # Determine if we can use the standard or simplified server
    try:
        import modelcontextprotocol
        has_mcp = True
        print("Using standard MCP server implementation")
    except ImportError:
        has_mcp = False
        print("Using simplified MCP server implementation (modelcontextprotocol not found)")
    
    # Determine server script path
    server_dir = Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server"
    
    # Check if the MCP server directory exists
    if not server_dir.exists():
        print(f"Error: MCP server directory not found at {server_dir}")
        parent_dir = server_dir.parent
        if parent_dir.exists():
            print(f"Contents of {parent_dir}:")
            for item in parent_dir.iterdir():
                print(f"  {item.name}")
        return None
    
    # Start the server as a module
    try:
        if not has_mcp:
            print("Starting simplified server directly...")
            cmd = [
                sys.executable, 
                "-c", 
                "import sys; sys.path.insert(0, '.'); "
                "from ipfs_datasets_py.mcp_server.simple_server import start_simple_server; "
                "start_simple_server()"
            ]
        else:
            print("Starting standard server...")
            cmd = [
                sys.executable, 
                "-c", 
                "import sys; sys.path.insert(0, '.'); "
                "from ipfs_datasets_py.mcp_server.server import start_server; "
                "start_server()"
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
            for line in iter(process.stdout.readline, ''):
                print(f"[SERVER] {line.strip()}")
        
        output_thread = threading.Thread(target=print_output)
        output_thread.daemon = True
        output_thread.start()
        
        return process
    except Exception as e:
        print(f"Error starting server process: {e}")
        return None
    
    return process

def test_server_tools():
    """Make requests to the server to test its tools."""
    print("\nTesting server tools...")
    
    # List available tools
    try:
        response = requests.get("http://127.0.0.1:5000/tools")
        if response.status_code == 200:
            tools_data = response.json()
            tools = tools_data.get("tools", {})
            print(f"Found {len(tools)} available tools:")
            for tool_name in tools:
                print(f"  - {tool_name}")
            
            # Create examples directory if it doesn't exist
            examples_dir = Path(__file__).resolve().parent / "examples"
            examples_dir.mkdir(exist_ok=True)
            
            # Test dataset tools if available
            test_dataset_path = examples_dir / "sample_data.json"
            if not test_dataset_path.exists():
                print(f"Creating sample dataset at {test_dataset_path}")
                with open(test_dataset_path, "w") as f:
                    json.dump({
                        "name": "Sample Dataset",
                        "data": [
                            {"id": 1, "value": 10},
                            {"id": 2, "value": 20},
                            {"id": 3, "value": 30}
                        ]
                    }, f)
            
            # Try a few tool requests based on what we found
            for tool_name in ["load_dataset", "search_vector_index", "record_audit_event"]:
                if tool_name in tools:
                    print(f"\nTesting {tool_name}...")
                    
                    # Prepare parameters based on the tool
                    if tool_name == "load_dataset":
                        params = {
                            "source": str(test_dataset_path),
                            "format": "json"
                        }
                    elif tool_name == "search_vector_index":
                        params = {
                            "query": "Sample vector search",
                            "top_k": 3
                        }
                    elif tool_name == "record_audit_event":
                        params = {
                            "event_type": "MCP_SERVER_TEST",
                            "description": "Testing MCP server audit logging",
                            "level": "INFO"
                        }
                    else:
                        params = {}
                    
                    # Call the tool
                    try:
                        response = requests.post(
                            f"http://127.0.0.1:5000/tools/{tool_name}",
                            json=params
                        )
                        print(f"Response status: {response.status_code}")
                        if response.status_code == 200:
                            print(json.dumps(response.json(), indent=2))
                        else:
                            print(f"Error: {response.text}")
                    except Exception as e:
                        print(f"Error calling {tool_name}: {e}")
        else:
            print(f"Error listing tools: {response.status_code}")
            if response.text:
                print(response.text)
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
            
            # Wait for server to start
            print("Waiting for server to start...")
            max_retries = 30
            for i in range(max_retries):
                try:
                    response = requests.get("http://127.0.0.1:5000")
                    if response.status_code == 200:
                        print(f"Server started successfully! ({i+1} attempts)")
                        server_info = response.json()
                        print(f"Server info: {json.dumps(server_info, indent=2)}")
                        break
                except Exception as e:
                    if i == max_retries - 1:
                        print(f"Timed out waiting for server to start: {e}")
                        return 1
                    print(f"Waiting for server... ({i+1}/{max_retries})")
                    time.sleep(1)
        else:
            print("Testing pre-existing server...")
        
        # Test the server's tools
        test_server_tools()
        
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
