"""
Example of using the IPFS Datasets MCP Server.

This example demonstrates:
1. Starting the MCP server
2. Setting up a client to interact with it
3. Using the MCP tools to work with IPFS datasets
"""
import asyncio
from modelcontextprotocol.client import MCPClient


async def example_mcp_client():
    """Example of using an MCP client to interact with the IPFS Datasets MCP server."""
    print("Connecting to IPFS Datasets MCP server...")

    # Create MCP client
    client = MCPClient("http://localhost:8000")

    # Get the list of available tools
    tools = await client.get_tool_list()
    print(f"Available tools: {[tool['name'] for tool in tools]}")

    # Example 1: Pin a file to IPFS
    print("\nPinning a file to IPFS...")
    result = await client.call_tool("pin_to_ipfs", {
        "content_path": "example_data/sample.json",
        "recursive": False
    })
    print(f"Pin result: {result}")

    # Get the CID from the result
    if result.get("status") == "success":
        cid = result["cid"]

        # Example 2: Retrieve the content
        print("\nRetrieving content from IPFS...")
        content_result = await client.call_tool("get_from_ipfs", {
            "cid": cid,
            "output_path": None  # Return content directly
        })
        print(f"Retrieved content type: {content_result.get('content_type')}")
        print(f"Content preview: {content_result.get('content')[:100]}...")

        # Example 3: Load the content as a dataset
        print("\nLoading content as a dataset...")
        dataset_result = await client.call_tool("load_dataset", {
            "source": f"ipfs://{cid}",
            "format": "json"
        })
        print(f"Dataset loaded: {dataset_result}")

        # Example 4: Process the dataset
        if dataset_result.get("status") == "success":
            dataset_id = dataset_result["dataset_id"]

            print("\nProcessing the dataset...")
            process_result = await client.call_tool("process_dataset", {
                "dataset_id": dataset_id,
                "operations": [
                    {"type": "filter", "column": "size", "condition": ">", "value": 100},
                    {"type": "select", "columns": ["name", "size", "type"]}
                ]
            })
            print(f"Processed dataset: {process_result}")

            # Example 5: Save the dataset back to IPFS
            if process_result.get("status") == "success":
                processed_id = process_result.get("dataset_id", dataset_id)

                print("\nSaving processed dataset to IPFS...")
                save_result = await client.call_tool("save_dataset", {
                    "dataset_id": processed_id,
                    "destination": "ipfs://",
                    "format": "parquet"
                })
                print(f"Saved dataset: {save_result}")


def start_server_in_background():
    """Start the MCP server in a separate process."""
    import subprocess
    import sys
    import time

    print("Starting IPFS Datasets MCP server in the background...")

    # Start the server
    process = subprocess.Popen(
        [sys.executable, "-m", "ipfs_datasets_py.mcp_server", "--host", "localhost", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # Give the server time to start
    time.sleep(2)

    return process


def main():
    """Main function to run the example."""
    # Start the server in the background
    server_process = start_server_in_background()

    try:
        # Run the client example
        asyncio.run(example_mcp_client())
    finally:
        # Stop the server
        print("\nStopping IPFS Datasets MCP server...")
        server_process.terminate()
        server_process.wait()


if __name__ == "__main__":
    main()
