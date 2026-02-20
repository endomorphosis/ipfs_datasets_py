"""
MCP++ Peer Management Tools — thin MCP wrappers for P2P peer operations.

6 tools:
  1. peer_discover  — Discover peers via DHT
  2. peer_connect   — Connect to a specific peer
  3. peer_disconnect — Disconnect from a peer
  4. peer_list      — List connected peers
  5. peer_metrics   — Get peer performance metrics
  6. bootstrap_network — Bootstrap to the P2P network

Business logic lives in ``tools/mcplusplus/peer_engine.py``.
All tools are Trio-native (_mcp_runtime='trio').
"""

import logging
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tools.mcplusplus.peer_engine import PeerEngine

logger = logging.getLogger(__name__)
_engine = PeerEngine()


async def peer_discover(
    capability_filter: Optional[List[str]] = None,
    max_peers: int = 10,
    timeout: int = 30,
    include_metrics: bool = False,
) -> Dict[str, Any]:
    """Discover peers in the P2P network via DHT."""
    return await _engine.discover(capability_filter, max_peers, timeout, include_metrics)

peer_discover._mcp_runtime = "trio"  # type: ignore[attr-defined]


async def peer_connect(
    peer_id: str,
    multiaddr: str,
    timeout: int = 30,
    retry_count: int = 3,
    persist: bool = True,
) -> Dict[str, Any]:
    """Connect to a specific peer in the P2P network."""
    return await _engine.connect(peer_id, multiaddr, timeout, retry_count, persist)

peer_connect._mcp_runtime = "trio"  # type: ignore[attr-defined]


async def peer_disconnect(
    peer_id: str,
    reason: Optional[str] = None,
    graceful: bool = True,
) -> Dict[str, Any]:
    """Disconnect from a peer in the P2P network."""
    return await _engine.disconnect(peer_id, reason, graceful)

peer_disconnect._mcp_runtime = "trio"  # type: ignore[attr-defined]


async def peer_list(
    status_filter: Optional[str] = None,
    capability_filter: Optional[List[str]] = None,
    sort_by: str = "last_seen",
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """List connected peers with filtering and sorting."""
    return await _engine.list_peers(status_filter, capability_filter, sort_by, limit, offset)

peer_list._mcp_runtime = "trio"  # type: ignore[attr-defined]


async def peer_metrics(
    peer_id: str,
    include_history: bool = False,
    history_hours: int = 24,
) -> Dict[str, Any]:
    """Get comprehensive performance metrics for a peer."""
    return await _engine.get_metrics(peer_id, include_history, history_hours)

peer_metrics._mcp_runtime = "trio"  # type: ignore[attr-defined]


async def bootstrap_network(
    bootstrap_nodes: Optional[List[str]] = None,
    timeout: int = 60,
    min_connections: int = 3,
    max_connections: int = 10,
) -> Dict[str, Any]:
    """Bootstrap to the P2P network via bootstrap nodes."""
    return await _engine.bootstrap(bootstrap_nodes, timeout, min_connections, max_connections)

bootstrap_network._mcp_runtime = "trio"  # type: ignore[attr-defined]


# MCP tool registration
TOOLS = [
    {"function": peer_discover, "description": "Discover peers in P2P network via DHT",
     "input_schema": {"type": "object", "properties": {
         "capability_filter": {"type": "array", "items": {"type": "string"}},
         "max_peers": {"type": "integer"}, "timeout": {"type": "integer"},
         "include_metrics": {"type": "boolean"}}}},
    {"function": peer_connect, "description": "Connect to a specific peer",
     "input_schema": {"type": "object", "properties": {
         "peer_id": {"type": "string"}, "multiaddr": {"type": "string"},
         "timeout": {"type": "integer"}, "retry_count": {"type": "integer"},
         "persist": {"type": "boolean"}}, "required": ["peer_id", "multiaddr"]}},
    {"function": peer_disconnect, "description": "Disconnect from a peer",
     "input_schema": {"type": "object", "properties": {
         "peer_id": {"type": "string"}, "reason": {"type": "string"},
         "graceful": {"type": "boolean"}}, "required": ["peer_id"]}},
    {"function": peer_list, "description": "List connected peers with filtering",
     "input_schema": {"type": "object", "properties": {
         "status_filter": {"type": "string"},
         "capability_filter": {"type": "array", "items": {"type": "string"}},
         "sort_by": {"type": "string"}, "limit": {"type": "integer"},
         "offset": {"type": "integer"}}}},
    {"function": peer_metrics, "description": "Get peer performance metrics",
     "input_schema": {"type": "object", "properties": {
         "peer_id": {"type": "string"}, "include_history": {"type": "boolean"},
         "history_hours": {"type": "integer"}}, "required": ["peer_id"]}},
    {"function": bootstrap_network, "description": "Bootstrap to P2P network",
     "input_schema": {"type": "object", "properties": {
         "bootstrap_nodes": {"type": "array", "items": {"type": "string"}},
         "timeout": {"type": "integer"}, "min_connections": {"type": "integer"},
         "max_connections": {"type": "integer"}}}},
]
