# ipfs_datasets_py/mcp_server/grpc_transport.py
"""
L52 — gRPC Transport Adapter (stub)
====================================
Provides a thin gRPC adapter so MCP tool calls can be served over gRPC in
addition to the default HTTP/stdio transports.

**Status:** stub — gRPC server bootstrapping is wired up but the protobuf
service definition and generated code are intentionally omitted here.  Wire
in the real ``grpc`` package and generated stubs when the full integration is
needed.

Usage (once wired)::

    from ipfs_datasets_py.mcp_server.grpc_transport import GRPCTransportAdapter
    from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

    manager = HierarchicalToolManager()
    adapter = GRPCTransportAdapter(manager, port=50051)
    await adapter.start()
    # ... serve requests ...
    await adapter.stop()
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

try:
    import grpc  # type: ignore[import]
    GRPC_AVAILABLE = True
except ImportError:
    grpc = None  # type: ignore[assignment]
    GRPC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Protobuf-like request / response containers
# ---------------------------------------------------------------------------


class GRPCToolRequest:
    """Minimal stand-in for the generated protobuf ``ToolRequest`` message.

    Attributes:
        category:  Tool category name.
        tool:      Tool name within the category.
        params_json: JSON-serialised parameter dict.
        request_id: Optional request correlation ID.
    """

    __slots__ = ("category", "tool", "params_json", "request_id")

    def __init__(
        self,
        category: str,
        tool: str,
        params_json: str = "{}",
        request_id: str = "",
    ) -> None:
        self.category = category
        self.tool = tool
        self.params_json = params_json
        self.request_id = request_id


class GRPCToolResponse:
    """Minimal stand-in for the generated protobuf ``ToolResponse`` message.

    Attributes:
        success:     ``True`` when the tool executed without error.
        result_json: JSON-serialised result dict.
        error:       Error message string (empty when *success* is True).
        request_id:  Echoed correlation ID from the request.
    """

    __slots__ = ("success", "result_json", "error", "request_id")

    def __init__(
        self,
        success: bool = True,
        result_json: str = "{}",
        error: str = "",
        request_id: str = "",
    ) -> None:
        self.success = success
        self.result_json = result_json
        self.error = error
        self.request_id = request_id


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class GRPCTransportAdapter:
    """Wraps a :class:`HierarchicalToolManager` behind a gRPC service.

    The adapter translates incoming ``GRPCToolRequest`` messages into
    :meth:`~HierarchicalToolManager.dispatch` calls and wraps the results in
    ``GRPCToolResponse`` messages.

    Args:
        manager: The tool manager instance to delegate calls to.
        host:    Network host to bind the gRPC server on (default ``"[::]"``).
        port:    TCP port number (default ``50051``).
        max_workers: Thread-pool size passed to the gRPC server executor.
    """

    def __init__(
        self,
        manager: Any,
        *,
        host: str = "[::]",
        port: int = 50051,
        max_workers: int = 10,
    ) -> None:
        self.manager = manager
        self.host = host
        self.port = port
        self.max_workers = max_workers
        self._server: Optional[Any] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the gRPC server.

        Raises:
            ImportError: If the ``grpc`` package is not installed.
            RuntimeError: If the server fails to bind on the requested port.
        """
        if not GRPC_AVAILABLE:
            raise ImportError(
                "grpcio is not installed. "
                "Run `pip install grpcio` to enable the gRPC transport."
            )
        logger.info(
            "Starting gRPC transport adapter on %s:%d (stub — no real service registered)",
            self.host,
            self.port,
        )
        # In a real implementation this would:
        # 1. Create a grpc.aio.server()
        # 2. add_MCPServiceServicer_to_server(MCPServiceImpl(self.manager), server)
        # 3. server.add_insecure_port(f"{self.host}:{self.port}")
        # 4. await server.start()
        self._server = object()  # Placeholder sentinel

    async def stop(self, grace: float = 5.0) -> None:
        """Gracefully stop the gRPC server.

        Args:
            grace: Seconds to wait for in-flight RPCs to complete before
                   forcefully terminating.
        """
        if self._server is None:
            return
        logger.info("Stopping gRPC transport adapter (grace=%.1fs)", grace)
        # In a real implementation: await self._server.stop(grace)
        self._server = None

    @property
    def is_running(self) -> bool:
        """Return ``True`` if the server has been started."""
        return self._server is not None

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    async def handle_request(self, request: GRPCToolRequest) -> GRPCToolResponse:
        """Translate a gRPC request to a manager dispatch call.

        Args:
            request: Incoming :class:`GRPCToolRequest`.

        Returns:
            :class:`GRPCToolResponse` with the serialised result or error.
        """
        import json

        try:
            params = json.loads(request.params_json) if request.params_json else {}
        except json.JSONDecodeError as exc:
            return GRPCToolResponse(
                success=False,
                error=f"Invalid params JSON: {exc}",
                request_id=request.request_id,
            )

        try:
            result = await self.manager.dispatch(request.category, request.tool, params)
            return GRPCToolResponse(
                success=True,
                result_json=json.dumps(result),
                request_id=request.request_id,
            )
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
            logger.warning("gRPC dispatch error: %s", exc)
            return GRPCToolResponse(
                success=False,
                error=str(exc),
                request_id=request.request_id,
            )

    def get_info(self) -> Dict[str, Any]:
        """Return metadata about this adapter instance."""
        return {
            "transport": "grpc",
            "host": self.host,
            "port": self.port,
            "max_workers": self.max_workers,
            "grpc_available": GRPC_AVAILABLE,
            "is_running": self.is_running,
        }
