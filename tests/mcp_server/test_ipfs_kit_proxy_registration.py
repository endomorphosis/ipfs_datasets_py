"""Regression tests for ipfs_kit MCP proxy registration.

The MCP server supports proxying tools to an external ipfs_kit_py MCP server
when `ipfs_kit_mcp_url` is configured. Historically this path referenced a
non-existent `mcp.client.MCPClient` import and also treated async APIs as sync.

This test ensures the proxy registration path is:
- Importable
- Able to discover tools via an async MCP client
- Able to register proxy tools and forward calls
"""

import pytest


@pytest.mark.anyio
async def test_register_ipfs_kit_tools_via_mcp_url(monkeypatch):
    from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
    from ipfs_datasets_py.mcp_server import client as mcp_client_module

    class FakeMCPClient:
        def __init__(self, server_url: str):
            self.server_url = server_url

        async def get_tool_list(self):
            return [{"name": "add"}, {"name": "cat"}]

        async def call_tool(self, tool_name, params):
            return {"tool": tool_name, "params": params, "server_url": self.server_url}

    class MockFastMCP:
        def __init__(self):
            self.registered = {}

        def add_tool(self, func, name: str):
            self.registered[name] = func

    monkeypatch.setattr(mcp_client_module, "MCPClient", FakeMCPClient)

    server = IPFSDatasetsMCPServer()
    server.mcp = MockFastMCP()

    await server.register_ipfs_kit_tools("http://example.invalid:8001")

    assert "ipfs_kit_add" in server.tools
    assert "ipfs_kit_cat" in server.tools

    result = await server.tools["ipfs_kit_add"](path="/tmp/foo")
    assert result["tool"] == "add"
    assert result["params"] == {"path": "/tmp/foo"}
