# VSCode CLI Integration Examples

This directory contains example scripts demonstrating the VSCode CLI integration in the IPFS Datasets Python library.

## Running the Examples

```bash
# Run all examples
python examples/vscode_cli_example.py

# Or run from the repository root
cd /path/to/ipfs_datasets_py
python examples/vscode_cli_example.py
```

## What's Demonstrated

The example script shows:

1. **Check Status** - Get VSCode CLI installation status
2. **Custom Install Directory** - Use a custom directory for installation
3. **Get Download URL** - Retrieve the download URL for the current platform
4. **MCP Tool** - Use the VSCode CLI through MCP tools
5. **MCP Server Function** - Use the VSCode CLI through MCP server functions

## Expected Output

When you run the examples, you should see output like:

```
VSCode CLI Integration Examples
==================================================

=== Example: Check Status ===
Installed: False
Version: N/A
Install Directory: /home/user/.vscode-cli
Platform: linux
Architecture: x64

=== Example: Custom Install Directory ===
Custom install directory: /tmp/tmp_xxxxx
Installed: False

=== Example: Get Download URL ===
Download URL: https://vscode.download.prss.microsoft.com/dbazure/download/stable/...

=== Example: MCP Tool ===
Tool name: vscode_cli_status
Result: {
  "success": true,
  "status": {
    "installed": false,
    ...
  }
}

=== Example: MCP Server Function ===
Result: {
  "success": true,
  "status": {
    "installed": false,
    ...
  }
}

==================================================
Examples completed!
```

## More Examples

For more comprehensive usage examples, see the [VSCode CLI Integration Documentation](../docs/VSCODE_CLI_INTEGRATION.md).
