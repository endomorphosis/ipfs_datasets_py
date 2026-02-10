# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/test_mcp_server.py'

Files last updated: 1751763414.1747205

Stub file last updated: 2025-07-07 02:35:43

## MCPServerTester

```python
class MCPServerTester:
    """
    Test suite for the IPFS Datasets MCP server.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, host: str = "localhost", port: int = 8765, ipfs_kit_mcp_url: str = None):
    """
    Initialize the tester with server settings.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MCPServerTester

## main

```python
async def main():
    """
    Run the tests with command-line arguments.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## run_all_tests

```python
async def run_all_tests(self):
    """
    Run all tests.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MCPServerTester

## start_server

```python
async def start_server(self):
    """
    Start the MCP server in the background.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MCPServerTester

## stop_server

```python
async def stop_server(self):
    """
    Stop the MCP server.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MCPServerTester

## test_dataset_tools

```python
async def test_dataset_tools(self):
    """
    Test the dataset tools.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MCPServerTester

## test_ipfs_tools

```python
async def test_ipfs_tools(self):
    """
    Test the IPFS tools.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MCPServerTester

## test_tool_availability

```python
async def test_tool_availability(self):
    """
    Test that all expected tools are available.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MCPServerTester

## test_vector_tools

```python
async def test_vector_tools(self):
    """
    Test the vector tools.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MCPServerTester
