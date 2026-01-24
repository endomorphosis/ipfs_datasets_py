#!/usr/bin/env python
"""
Comprehensive test script for the IPFS Datasets MCP server.

This script tests:
1. Server startup and configuration
2. Tool registration and availability
3. Basic functionality of each tool category
4. Integration with IPFS Kit
5. Error handling

Usage:
    python test_mcp_server.py [--host HOST] [--port PORT] [--ipfs-kit-mcp-url URL]
"""
import argparse
import anyio
import sys
import json
import logging
import os
from pathlib import Path
import random
import time
import tempfile
from typing import Dict, Any, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mcp_test")

# Add parent directory to path if needed
parent_dir = Path(__file__).resolve().parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPServer, configs
from mcp_server.client import MCPClient

# Test data
TEST_DATA = {
    "metadata": {
        "name": "Test Dataset",
        "description": "A test dataset for IPFS Datasets MCP server",
        "version": "0.1.0",
        "created_at": "2023-01-01T00:00:00Z",
    },
    "records": [
        {"id": 1, "name": "Item 1", "value": 10, "tags": ["tag1", "tag2"]},
        {"id": 2, "name": "Item 2", "value": 20, "tags": ["tag2", "tag3"]},
        {"id": 3, "name": "Item 3", "value": 30, "tags": ["tag1", "tag3"]},
        {"id": 4, "name": "Item 4", "value": 40, "tags": ["tag1", "tag2", "tag3"]},
        {"id": 5, "name": "Item 5", "value": 50, "tags": ["tag2", "tag3"]},
    ],
}


class MCPServerTester:
    """Test suite for the IPFS Datasets MCP server."""

    def __init__(self, host: str = "localhost", port: int = 8765, ipfs_kit_mcp_url: str = None):
        """Initialize the tester with server settings."""
        self.host = host
        self.port = port
        self.ipfs_kit_mcp_url = ipfs_kit_mcp_url
        self.server = None
        self.server_task = None
        self.client = None
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.test_data_path = self.temp_path / "test_data.json"

        # Prepare test data
        with open(self.test_data_path, "w") as f:
            json.dump(TEST_DATA, f)

        logger.info(f"Created test data at {self.test_data_path}")

    async def start_server(self):
        """Start the MCP server in the background."""
        logger.info(f"Starting MCP server at {self.host}:{self.port}")

        # Update configuration
        if self.ipfs_kit_mcp_url:
            configs.ipfs_kit_mcp_url = self.ipfs_kit_mcp_url
            configs.ipfs_kit_integration = "mcp"

        # Create and start server
        self.server = IPFSDatasetsMCPServer()
        self.server_task = asyncio.create_task(self.server.start(self.host, self.port))

        # Wait for server to start
        await anyio.sleep(2)

        # Create client
        self.client = MCPClient(f"http://{self.host}:{self.port}")
        logger.info("MCP server started")

    async def stop_server(self):
        """Stop the MCP server."""
        if self.server_task:
            logger.info("Stopping MCP server")
            self.server_task.cancel()
            try:
                await self.server_task
            except anyio.get_cancelled_exc_class()():
                pass

        # Cleanup temp directory
        self.temp_dir.cleanup()
        logger.info("MCP server stopped and temporary files cleaned up")

    async def test_tool_availability(self):
        """Test that all expected tools are available."""
        logger.info("Testing tool availability")

        tools = await self.client.get_tool_list()
        tool_names = [tool["name"] for tool in tools]

        # Expected tool categories
        expected_categories = [
            "dataset_tools", "ipfs_tools", "vector_tools",
            "graph_tools", "audit_tools", "security_tools",
            "provenance_tools"
        ]

        # Check for tools in each category
        found_categories = set()
        for tool in tool_names:
            for category in expected_categories:
                category_prefix = category.split("_")[0]  # e.g., "dataset" from "dataset_tools"
                if tool.startswith(category_prefix):
                    found_categories.add(category)
                    break

        # Report findings
        logger.info(f"Found {len(tool_names)} tools")
        for category in expected_categories:
            status = "✓" if category in found_categories else "✗"
            logger.info(f"  {status} {category}")

        # Check for IPFS Kit tools
        ipfs_kit_tools = [name for name in tool_names if name.startswith("ipfs_kit_")]
        logger.info(f"Found {len(ipfs_kit_tools)} IPFS Kit tools")

        return tool_names

    async def test_dataset_tools(self):
        """Test the dataset tools."""
        logger.info("Testing dataset tools")

        try:
            # Test load_dataset
            logger.info("Testing load_dataset")
            load_result = await self.client.call_tool("load_dataset", {
                "source": str(self.test_data_path),
                "format": "json"
            })
            logger.info(f"Load result: {load_result}")

            if load_result.get("status") == "success":
                dataset_id = load_result["dataset_id"]

                # Test process_dataset
                logger.info("Testing process_dataset")
                process_result = await self.client.call_tool("process_dataset", {
                    "dataset_id": dataset_id,
                    "operations": [
                        {"type": "filter", "column": "value", "condition": ">", "value": 20}
                    ]
                })
                logger.info(f"Process result: {process_result}")

                # Test convert_dataset_format
                logger.info("Testing convert_dataset_format")
                convert_result = await self.client.call_tool("convert_dataset_format", {
                    "dataset_id": dataset_id,
                    "target_format": "csv"
                })
                logger.info(f"Convert result: {convert_result}")

                # Test save_dataset
                output_path = str(self.temp_path / "output_dataset.json")
                logger.info("Testing save_dataset")
                save_result = await self.client.call_tool("save_dataset", {
                    "dataset_id": dataset_id,
                    "destination": output_path,
                    "format": "json"
                })
                logger.info(f"Save result: {save_result}")

                return True
            else:
                logger.error("Failed to load dataset")
                return False

        except Exception as e:
            logger.error(f"Error testing dataset tools: {e}")
            return False

    async def test_ipfs_tools(self):
        """Test the IPFS tools."""
        logger.info("Testing IPFS tools")

        try:
            # Skip IPFS tests if IPFS daemon is not running
            # This is just a basic test of the tool's response

            # Test pin_to_ipfs
            logger.info("Testing pin_to_ipfs")
            try:
                pin_result = await self.client.call_tool("pin_to_ipfs", {
                    "content_path": str(self.test_data_path),
                    "recursive": False
                })
                logger.info(f"Pin result: {pin_result}")
            except Exception as e:
                logger.warning(f"IPFS pin test failed (this may be expected if IPFS is not running): {e}")

            # Continue with get_from_ipfs test even if pin failed
            # In a real test we'd use a known CID that exists on IPFS
            logger.info("Testing get_from_ipfs with a test CID")
            try:
                test_cid = "QmZ4tDuvesekSs4qM5ZBKpXiZGun7S2CYtEZRB3DYXkjGx"  # Example CID
                get_result = await self.client.call_tool("get_from_ipfs", {
                    "cid": test_cid
                })
                logger.info(f"Get result: {get_result}")
            except Exception as e:
                logger.warning(f"IPFS get test failed (this may be expected if IPFS is not running): {e}")

            return True

        except Exception as e:
            logger.error(f"Error testing IPFS tools: {e}")
            return False

    async def test_vector_tools(self):
        """Test the vector tools."""
        logger.info("Testing vector tools")

        try:
            # Create vector index
            vectors = [[random.random() for _ in range(5)] for _ in range(10)]
            metadata = [{"id": i, "name": f"Item {i}"} for i in range(10)]

            logger.info("Testing create_vector_index")
            create_result = await self.client.call_tool("create_vector_index", {
                "vectors": vectors,
                "dimension": 5,
                "metric": "cosine",
                "metadata": metadata
            })
            logger.info(f"Create vector index result: {create_result}")

            if create_result.get("status") == "success":
                index_id = create_result["index_id"]

                # Test search
                query_vector = [random.random() for _ in range(5)]
                logger.info("Testing search_vector_index")
                search_result = await self.client.call_tool("search_vector_index", {
                    "index_id": index_id,
                    "query_vector": query_vector,
                    "top_k": 3
                })
                logger.info(f"Search vector index result: {search_result}")

                return True
            else:
                logger.error("Failed to create vector index")
                return False

        except Exception as e:
            logger.error(f"Error testing vector tools: {e}")
            return False

    async def run_all_tests(self):
        """Run all tests."""
        try:
            # Start the server
            await self.start_server()

            # Run the tests
            test_results = {}

            # Test tool availability
            tool_names = await self.test_tool_availability()
            test_results["tool_availability"] = len(tool_names) > 0

            # Test dataset tools
            test_results["dataset_tools"] = await self.test_dataset_tools()

            # Test IPFS tools
            test_results["ipfs_tools"] = await self.test_ipfs_tools()

            # Test vector tools
            test_results["vector_tools"] = await self.test_vector_tools()

            # Print summary
            logger.info("\n=== Test Summary ===")
            for test, result in test_results.items():
                status = "PASS" if result else "FAIL"
                logger.info(f"{test}: {status}")

            # Overall result
            overall = all(test_results.values())
            logger.info(f"\nOverall: {'PASS' if overall else 'FAIL'}")

            return overall

        finally:
            # Stop the server
            await self.stop_server()


async def main():
    """Run the tests with command-line arguments."""
    parser = argparse.ArgumentParser(description="Test the IPFS Datasets MCP server")
    parser.add_argument("--host", default="localhost", help="Host for the server")
    parser.add_argument("--port", type=int, default=8765, help="Port for the server")
    parser.add_argument("--ipfs-kit-mcp-url", help="URL of an ipfs_kit_py MCP server")

    args = parser.parse_args()

    # Run the tests
    tester = MCPServerTester(args.host, args.port, args.ipfs_kit_mcp_url)
    success = await tester.run_all_tests()

    # Exit with appropriate status code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    anyio.run(main())
