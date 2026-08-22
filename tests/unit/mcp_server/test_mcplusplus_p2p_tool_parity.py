"""SCA-611: P2P tools/list and tools/call parity tests."""

from __future__ import annotations

import asyncio

from ipfs_datasets_py.mcp_server.mcplusplus.p2p_libp2p_transport import (
    LibP2PToolTransport,
    ToolRegistry,
)


def _transport() -> LibP2PToolTransport:
    registry = ToolRegistry()

    def echo(value: str) -> str:
        return f"echo:{value}"

    registry.register(
        "echo",
        echo,
        description="Echo a value",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        handler_id="test:echo",
    )
    return LibP2PToolTransport(registry)


def test_tools_list_returns_exact_registered_catalog() -> None:
    transport = _transport()
    listed = transport.tools_list()
    assert listed["registry_size"] == 1
    assert [tool["name"] for tool in listed["tools"]] == ["echo"]
    assert listed["tools"][0]["handler_id"] == "test:echo"
    # Advertised catalog is non-empty when tools are registered.
    assert listed["tools"]


def test_tools_call_dispatches_registered_tool() -> None:
    transport = _transport()
    result = asyncio.run(transport.tools_call("echo", {"value": "hi"}))
    assert result["ok"] is True
    assert result["result"] == "echo:hi"
    assert result["handler_id"] == "test:echo"
    assert result["path_class"] == "p2p"


def test_unknown_and_schema_invalid_calls_fail_closed() -> None:
    transport = _transport()
    unknown = asyncio.run(transport.tools_call("missing", {}))
    assert unknown["ok"] is False
    assert unknown["error"]["code"] == "unknown_tool"

    invalid = asyncio.run(transport.tools_call("echo", {}))
    assert invalid["ok"] is False
    assert invalid["error"]["code"] == "schema_invalid"

    extra = asyncio.run(transport.tools_call("echo", {"value": "x", "nope": 1}))
    assert extra["ok"] is False
    assert extra["error"]["code"] == "schema_invalid"


def test_jsonrpc_tools_list_and_call_parity() -> None:
    transport = _transport()
    listed = asyncio.run(
        transport.dispatch_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    )
    assert listed["result"]["registry_size"] == 1
    called = asyncio.run(
        transport.dispatch_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"value": "z"}},
            }
        )
    )
    assert called["result"]["ok"] is True
    assert called["result"]["result"] == "echo:z"
    failed = asyncio.run(
        transport.dispatch_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "nope", "arguments": {}},
            }
        )
    )
    assert "error" in failed
