"""SCA-611: datasets P2P MCP++ tools/list and tools/call parity.

Bounded list/call request/result/error parity over the datasets P2P transport
with exact registry and handler identity. Advertised tools cannot coexist with
an empty registry; unknown/schema-invalid calls fail closed.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional

# Re-export core Profile E transport helpers when available.
try:
    from ipfs_datasets_py.mcp_server.p2p_libp2p_transport import (  # noqa: F401
        MCP_P2P_PROTOCOL,
        MCPp2pNode,
        ensure_libp2p_installed,
    )
except Exception:  # pragma: no cover
    MCP_P2P_PROTOCOL = "/mcp+p2p/1.0.0"
    MCPp2pNode = None  # type: ignore
    ensure_libp2p_installed = None  # type: ignore


class P2PToolTransportError(ValueError):
    """Invalid registry/call boundary for P2P tool parity."""


@dataclass(frozen=True)
class RegisteredTool:
    """One registered tool with exact schema/handler identity."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: Callable[..., Any]
    handler_id: str

    def to_mcp_tool(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": dict(self.input_schema),
            "handler_id": self.handler_id,
        }


@dataclass
class ToolRegistry:
    """Exact bounded tool catalog for tools/list and tools/call."""

    _tools: MutableMapping[str, RegisteredTool] = field(default_factory=dict)

    def register(
        self,
        name: str,
        handler: Callable[..., Any],
        *,
        description: str = "",
        input_schema: Mapping[str, Any] | None = None,
        handler_id: str | None = None,
    ) -> RegisteredTool:
        if not name or not str(name).strip():
            raise P2PToolTransportError("tool name is required")
        if not callable(handler):
            raise P2PToolTransportError("handler must be callable")
        schema = dict(input_schema or {"type": "object", "additionalProperties": True})
        if schema.get("type") != "object":
            raise P2PToolTransportError("input_schema.type must be object")
        tool = RegisteredTool(
            name=str(name).strip(),
            description=str(description or ""),
            input_schema=schema,
            handler=handler,
            handler_id=handler_id or f"{getattr(handler, '__module__', 'unknown')}:{getattr(handler, '__qualname__', repr(handler))}",
        )
        self._tools[tool.name] = tool
        return tool

    def list_tools(self) -> List[Dict[str, Any]]:
        return [tool.to_mcp_tool() for tool in sorted(self._tools.values(), key=lambda t: t.name)]

    def get(self, name: str) -> Optional[RegisteredTool]:
        return self._tools.get(str(name or "").strip())

    @property
    def size(self) -> int:
        return len(self._tools)


def _validate_arguments(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> None:
    if not isinstance(arguments, Mapping):
        raise P2PToolTransportError("arguments must be an object")
    required = schema.get("required") or []
    if isinstance(required, list):
        missing = [key for key in required if key not in arguments]
        if missing:
            raise P2PToolTransportError(f"missing required arguments: {', '.join(missing)}")
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        unknown = [key for key in arguments if key not in properties]
        if unknown and schema.get("additionalProperties") is False:
            raise P2PToolTransportError(f"unexpected arguments: {', '.join(sorted(map(str, unknown)))}")


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class LibP2PToolTransport:
    """In-process P2P tool parity surface (list/call) with fail-closed errors."""

    def __init__(self, registry: ToolRegistry | None = None):
        self.registry = registry or ToolRegistry()
        self.transport_id = "datasets-mcplusplus-p2p-tool-transport@1"

    def tools_list(self) -> Dict[str, Any]:
        tools = self.registry.list_tools()
        return {
            "tools": tools,
            "registry_size": self.registry.size,
            "transport_id": self.transport_id,
            "path_class": "p2p",
        }

    async def tools_call(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        path_class: str = "p2p",
    ) -> Dict[str, Any]:
        tool = self.registry.get(name)
        if tool is None:
            return {
                "ok": False,
                "error": {
                    "code": "unknown_tool",
                    "message": f"tool not registered: {name}",
                },
                "path_class": path_class,
            }
        args = dict(arguments or {})
        try:
            _validate_arguments(tool.input_schema, args)
        except P2PToolTransportError as exc:
            return {
                "ok": False,
                "error": {
                    "code": "schema_invalid",
                    "message": str(exc),
                },
                "path_class": path_class,
                "handler_id": tool.handler_id,
            }
        try:
            result = await _maybe_await(tool.handler(**args))
        except TypeError as exc:
            return {
                "ok": False,
                "error": {
                    "code": "schema_invalid",
                    "message": str(exc),
                },
                "path_class": path_class,
                "handler_id": tool.handler_id,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": {
                    "code": "handler_error",
                    "message": str(exc),
                },
                "path_class": path_class,
                "handler_id": tool.handler_id,
            }
        return {
            "ok": True,
            "result": result,
            "tool": tool.name,
            "handler_id": tool.handler_id,
            "path_class": path_class,
            "direct_effect_traceable": path_class in {"p2p", "direct"},
        }

    async def dispatch_jsonrpc(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        request_id = request.get("id")
        method = str(request.get("method") or "")
        params = request.get("params") if isinstance(request.get("params"), Mapping) else {}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": self.tools_list()}
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), Mapping) else {}
            outcome = await self.tools_call(name, arguments)
            if not outcome.get("ok"):
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32602 if outcome.get("error", {}).get("code") in {
                            "unknown_tool",
                            "schema_invalid",
                        } else -32603,
                        "message": outcome.get("error", {}).get("message", "call failed"),
                        "data": outcome.get("error"),
                    },
                }
            return {"jsonrpc": "2.0", "id": request_id, "result": outcome}
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"unsupported method: {method}"},
        }


__all__ = [
    "MCP_P2P_PROTOCOL",
    "MCPp2pNode",
    "ensure_libp2p_installed",
    "P2PToolTransportError",
    "RegisteredTool",
    "ToolRegistry",
    "LibP2PToolTransport",
]
