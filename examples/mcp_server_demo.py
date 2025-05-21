#!/usr/bin/env python
"""
Demo script for IPFS Datasets MCP server.

This script demonstrates how to use the IPFS Datasets MCP server with a simple workflow.
"""
import asyncio
import json
import os
import sys
import argparse
import logging
import time
from pathlib import Path
from typing import Dict, List, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mcp_demo")

# Add parent directory to path if needed
parent_dir = Path(__file__).resolve().parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from ipfs_datasets_py.mcp_server import start_server
from modelcontextprotocol.client import MCPClient

# Example data
EXAMPLE_DATA = {
    "metadata": {
        "name": "Demo Dataset",
        "description": "A demo dataset for IPFS Datasets MCP server",
        "version": "0.1.0",
        "created_at": "2023-05-12T12:00:00Z",
    },
    "records": [
        {"id": 1, "title": "Introduction to IPFS", "content": "IPFS is a distributed file system...", "keywords": ["ipfs", "distributed", "web3"]},
        {"id": 2, "title": "Using IPFS with Python", "content": "Python offers several libraries for IPFS...", "keywords": ["python", "ipfs", "programming"]},
        {"id": 3, "title": "IPFS and Big Data", "content": "IPFS can be useful for storing and retrieving big data...", "keywords": ["ipfs", "big data", "storage"]},
        {"id": 4, "title": "Decentralized Applications", "content": "Building decentralized applications with IPFS...", "keywords": ["dapps", "ipfs", "web3"]},
        {"id": 5, "title": "IPFS and AI", "content": "Using IPFS for AI model and dataset storage...", "keywords": ["ai", "ipfs", "machine learning"]},
    ],
}


class MCPDemoRunner:
    """Runner for the MCP server demo."""
    
    def __init__(self):
        """Initialize the demo runner."""
        self.server_process = None
        self.client = None
        self.example_data_path = Path("demo_dataset.json")
        
        # Create example data file
        with open(self.example_data_path, "w") as f:
            json.dump(EXAMPLE_DATA, f, indent=2)
            
        logger.info(f"Created example dataset at {self.example_data_path}")
    
    async def run_demo(self):
        """Run the demo workflow."""
        try:
            # Connect to the server
            self.client = MCPClient("http://localhost:8123")
            
            # Wait for server to be ready
            await self._wait_for_server(timeout=5)
            
            # Run the demo workflow
            await self._workflow()
            
        except Exception as e:
            logger.error(f"Demo failed: {e}")
            
        finally:
            # Clean up
            if self.example_data_path.exists():
                os.remove(self.example_data_path)
            
    async def _wait_for_server(self, timeout=5):
        """Wait for the server to be ready."""
        logger.info(f"Waiting for server to be ready (timeout: {timeout}s)...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Try to get tool list
                await self.client.get_tool_list()
                logger.info("Server is ready")
                return
            except Exception:
                # Wait and try again
                await asyncio.sleep(0.5)
                
        raise TimeoutError("Server did not become ready in time")
            
    async def _workflow(self):
        """Run the demo workflow."""
        # Step 1: List available tools
        logger.info("\n=== Step 1: List Available Tools ===")
        tools = await self.client.get_tool_list()
        tool_names = sorted([tool["name"] for tool in tools])
        logger.info(f"Available tools: {len(tool_names)}")
        for name in tool_names[:10]:  # Show only first 10 tools
            logger.info(f"- {name}")
        if len(tool_names) > 10:
            logger.info(f"...and {len(tool_names) - 10} more")
        
        # Step 2: Load the dataset
        logger.info("\n=== Step 2: Load Dataset ===")
        load_result = await self.client.call_tool("load_dataset", {
            "source": str(self.example_data_path),
            "format": "json"
        })
        logger.info(f"Load result: {json.dumps(load_result, indent=2)}")
        
        if load_result.get("status") != "success":
            logger.error("Failed to load dataset")
            return
            
        dataset_id = load_result["dataset_id"]
        
        # Step 3: Process the dataset
        logger.info("\n=== Step 3: Process Dataset ===")
        process_result = await self.client.call_tool("process_dataset", {
            "dataset_id": dataset_id,
            "operations": [
                {"type": "filter", "column": "id", "condition": ">", "value": 2},
                {"type": "select", "columns": ["id", "title", "keywords"]}
            ]
        })
        logger.info(f"Process result: {json.dumps(process_result, indent=2)}")
        
        if process_result.get("status") != "success":
            logger.error("Failed to process dataset")
            return
            
        processed_id = process_result["dataset_id"]
        
        # Step 4: Save the processed dataset
        logger.info("\n=== Step 4: Save Processed Dataset ===")
        output_path = "processed_dataset.json"
        save_result = await self.client.call_tool("save_dataset", {
            "dataset_id": processed_id,
            "destination": output_path,
            "format": "json"
        })
        logger.info(f"Save result: {json.dumps(save_result, indent=2)}")
        
        if save_result.get("status") != "success":
            logger.error("Failed to save dataset")
            return
        
        # Step 5: Track provenance
        logger.info("\n=== Step 5: Track Provenance ===")
        provenance_result = await self.client.call_tool("record_provenance", {
            "dataset_id": processed_id,
            "operation": "filter_and_select",
            "inputs": [dataset_id],
            "parameters": {
                "filter": "id > 2",
                "columns": ["id", "title", "keywords"]
            },
            "description": "Filtered dataset to only include items with ID > 2 and selected specific columns"
        })
        logger.info(f"Provenance result: {json.dumps(provenance_result, indent=2)}")
        
        # Step 6: Pin to IPFS (optional - may fail if IPFS is not running)
        logger.info("\n=== Step 6: Pin to IPFS (Optional) ===")
        try:
            pin_result = await self.client.call_tool("pin_to_ipfs", {
                "content_path": output_path,
                "recursive": False
            })
            logger.info(f"Pin result: {json.dumps(pin_result, indent=2)}")
            
            if pin_result.get("status") == "success":
                logger.info(f"Dataset pinned to IPFS with CID: {pin_result.get('cid')}")
        except Exception as e:
            logger.warning(f"IPFS pinning skipped (IPFS may not be running): {e}")
        
        logger.info("\n=== Demo Completed Successfully! ===")
        
        # Clean up output file if it exists
        if os.path.exists(output_path):
            os.remove(output_path)
            logger.info(f"Cleaned up {output_path}")


def start_server_in_background():
    """Start the MCP server in a background process."""
    import subprocess
    
    logger.info("Starting MCP server in the background...")
    process = subprocess.Popen(
        [sys.executable, "-m", "ipfs_datasets_py.mcp_server", "--host", "localhost", "--port", "8123"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Give the server some time to start
    time.sleep(2)
    
    return process


async def main():
    """Run the demo."""
    parser = argparse.ArgumentParser(description="Demo for the IPFS Datasets MCP server")
    parser.add_argument("--start-server", action="store_true", help="Start the MCP server as part of the demo")
    parser.add_argument("--host", default="localhost", help="Host of the MCP server")
    parser.add_argument("--port", type=int, default=8123, help="Port of the MCP server")
    
    args = parser.parse_args()
    
    server_process = None
    if args.start_server:
        server_process = start_server_in_background()
    
    try:
        # Run the demo
        runner = MCPDemoRunner()
        await runner.run_demo()
        
    finally:
        # Stop the server if we started it
        if server_process:
            logger.info("Stopping MCP server...")
            server_process.terminate()
            server_process.wait(timeout=5)
            logger.info("MCP server stopped")


if __name__ == "__main__":
    asyncio.run(main())
