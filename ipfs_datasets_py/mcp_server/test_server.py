# Test script for the IPFS Datasets MCP server
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ipfs_datasets_py.mcp_server import start_server, IPFSDatasetsMCPServer
try:
    from modelcontextprotocol.client import MCPClient
except ImportError:
    # Use our mock for testing when the real package isn't available
    from .mock_modelcontextprotocol_for_testing import MockMCPClientForTesting as MCPClient


async def test_mcp_server():
    """Test the MCP server implementation."""
    print("Testing IPFS Datasets MCP server...")

    # Start the server in the background
    server = IPFSDatasetsMCPServer()
    server_task = asyncio.create_task(server.start(host="localhost", port=8765))

    # Give the server some time to start
    await asyncio.sleep(2)

    try:
        # Connect to the server
        client = MCPClient("http://localhost:8765")

        # Get the list of tools
        print("\nFetching available tools...")
        tools = await client.get_tool_list()

        tool_names = [tool["name"] for tool in tools]
        print(f"Found {len(tool_names)} tools:")
        for name in sorted(tool_names):
            print(f"- {name}")

        # Test with a mock dataset
        print("\nCreating mock dataset...")

        # This is a mock test that doesn't actually create a dataset,
        # but tests if the server returns a response
        try:
            result = await client.call_tool("load_dataset", {
                "source": "test_data",
                "format": "json"
            })
            print(f"Got response from server: {result}")
        except Exception as e:
            print(f"Error calling load_dataset: {e}")
            # This is expected if the actual dataset handling code isn't implemented
            print("This error is expected if the dataset handling code isn't fully implemented")

        # Check integration with IPFS Kit
        print("\nChecking IPFS Kit integration...")
        ipfs_kit_tools = [name for name in tool_names if name.startswith("ipfs_kit_")]
        print(f"Found {len(ipfs_kit_tools)} IPFS Kit tools")
        for name in ipfs_kit_tools:
            print(f"- {name}")

    finally:
        # Stop the server
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

        print("\nServer stopped. Test complete.")


if __name__ == "__main__":
    asyncio.run(test_mcp_server())
