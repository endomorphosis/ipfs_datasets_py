### Calling the MCP Server

1. **Run the Server**: You can run the server by executing the `server.py` script. This will start the MCP server and register all the tools defined in the script.

   ```bash
   python /home/barberb/ipfs_datasets_py/claudes_toolbox/server.py
   ```

2. **Interact with the Server**: Once the server is running, you can interact with it using the registered tools. You can send requests to the server using the appropriate transport method (e.g., `stdio`, HTTP, etc.).

### Importing the Package

If you want to import the package in another Python script, you can do so by following these steps:

1. **Ensure the Package is in Your Python Path**: Make sure that the directory containing the `server.py` file is included in your Python path. You can do this by adding the directory to your `PYTHONPATH` environment variable or by modifying `sys.path` in your script.

   ```python
   import sys
   sys.path.append('/home/barberb/ipfs_datasets_py/claudes_toolbox')
   ```

2. **Import the Necessary Classes/Functions**: You can import the `FastMCP` server and any tools you need directly from the package.

   ```python
   from modelcontextprotocol.server import FastMCP
   from your_tool_module import your_tool_function  # Replace with actual tool imports
   ```

3. **Initialize and Use the Server**: You can create an instance of the `FastMCP` server and register tools as needed.

   ```python
   mcp = FastMCP("your_toolbox_name")
   mcp.add_tool(your_tool_function, name="your_tool_name", description="Your tool description")
   ```

### Example Usage

Here’s a simple example of how you might set up and use the server in another script:

```python
from modelcontextprotocol.server import FastMCP
from your_tool_module import your_tool_function  # Replace with actual tool imports

# Initialize the MCP server
mcp = FastMCP("my_toolbox")

# Register a tool
mcp.add_tool(your_tool_function, name="my_tool", description="This is my tool.")

# Run the server
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

### Conclusion

You can either run the server as a standalone application or import it into another script to use its functionalities. Make sure to replace placeholders with actual tool names and paths as needed. If you have specific questions or need further assistance with a particular aspect of the code, feel free to ask!