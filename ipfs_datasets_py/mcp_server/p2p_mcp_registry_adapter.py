"""Adapter that exposes mcp_server tools in the shape expected by ipfs_accelerate_py.tool_manifest.

The p2p TaskQueue service's `call_tool` handler uses `ipfs_accelerate_py.tool_manifest`
which expects an MCP-like registry exposing a `.tools` attribute.

FastMCP does not expose `.tools` directly, and IPFSDatasetsMCPServer stores tools
as a dict name -> callable. This adapter normalizes that into the expected dict:

  tools[name] = {"function": callable, "description": str, "input_schema": dict}

It also forwards P2P auth validation to the host server.
"""

from __future__ import annotations

from typing import Any, Dict


class P2PMCPRegistryAdapter:
    def __init__(self, host_server: Any) -> None:
        self._host = host_server

    @property
    def accelerate_instance(self) -> Any:
        # Used by the P2P service to pass into ctx.state.accelerate.
        return self._host

    @property
    def tools(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        host_tools = getattr(self._host, "tools", None)
        if not isinstance(host_tools, dict):
            return out

        for name, fn in host_tools.items():
            if not callable(fn):
                continue
            try:
                desc = fn.__doc__ or ""
            except Exception:
                desc = ""
            out[str(name)] = {
                "function": fn,
                "description": str(desc),
                "input_schema": {},
                # tool_manifest.tool_execution_context will treat missing
                # execution_context as unknown; the P2P service embeds a default.
            }
        return out

    async def validate_p2p_message(self, msg: dict) -> bool:
        fn = getattr(self._host, "validate_p2p_message", None)
        if not callable(fn):
            return False
        res = fn(msg)
        if hasattr(res, "__await__"):
            return bool(await res)
        return bool(res)
