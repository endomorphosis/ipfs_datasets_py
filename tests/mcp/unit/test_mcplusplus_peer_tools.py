"""
Phase B2 — Unit tests for mcplusplus_peer_tools.py

6 tools: peer_discover, peer_connect, peer_disconnect,
         peer_list, peer_metrics, bootstrap_network
All are async Trio-native wrappers around PeerEngine.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Helpers — mock PeerEngine at module level
# ---------------------------------------------------------------------------
def _make_engine(extra_keys=None):
    engine = MagicMock()
    base = {"success": True, "peers": [], "discovered_count": 0}
    if extra_keys:
        base.update(extra_keys)
    for method in ("discover", "connect", "disconnect", "list", "get_metrics", "bootstrap"):
        am = AsyncMock(return_value={**base})
        setattr(engine, method, am)
    return engine


# ---------------------------------------------------------------------------
# TestPeerDiscover
# ---------------------------------------------------------------------------
class TestPeerDiscover:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_discover
        result = _run(peer_discover(max_peers=2))
        assert isinstance(result, dict)

    def test_has_success_key(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_discover
        result = _run(peer_discover(max_peers=2))
        assert "success" in result or "error" in result or "peers" in result

    def test_capability_filter_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_discover
        result = _run(peer_discover(capability_filter=["storage"], max_peers=1))
        assert isinstance(result, dict)

    def test_include_metrics_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_discover
        result = _run(peer_discover(include_metrics=True, max_peers=1))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestPeerConnect / Disconnect
# ---------------------------------------------------------------------------
class TestPeerConnect:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_connect
        result = _run(peer_connect("peer123", "/ip4/127.0.0.1/tcp/4001"))
        assert isinstance(result, dict)

    def test_timeout_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_connect
        result = _run(peer_connect("p1", "/ip4/127.0.0.1/tcp/4001", timeout=5))
        assert isinstance(result, dict)

    def test_retry_count_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_connect
        result = _run(peer_connect("p2", "/ip4/127.0.0.1/tcp/4001", retry_count=1, persist=False))
        assert isinstance(result, dict)


class TestPeerDisconnect:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_disconnect
        result = _run(peer_disconnect("peer123"))
        assert isinstance(result, dict)

    def test_graceful_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_disconnect
        result = _run(peer_disconnect("peer123", reason="timeout", graceful=False))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestPeerList
# ---------------------------------------------------------------------------
class TestPeerList:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_list
        result = _run(peer_list())
        assert isinstance(result, dict)

    def test_capability_filter_and_limit_params(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_list
        result = _run(peer_list(capability_filter=["storage"], limit=5))
        assert isinstance(result, dict)

    def test_filter_params(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_list
        result = _run(peer_list(status_filter="connected", capability_filter=["storage"]))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestPeerMetrics
# ---------------------------------------------------------------------------
class TestPeerMetrics:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_metrics
        result = _run(peer_metrics("peer123"))
        assert isinstance(result, dict)

    def test_include_history_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_metrics
        result = _run(peer_metrics("peer123", include_history=True, history_hours=12))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestBootstrapNetwork
# ---------------------------------------------------------------------------
class TestBootstrapNetwork:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import bootstrap_network
        result = _run(bootstrap_network())
        assert isinstance(result, dict)

    def test_bootstrap_nodes_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import bootstrap_network
        result = _run(bootstrap_network(bootstrap_nodes=["/ip4/127.0.0.1/tcp/4001"]))
        assert isinstance(result, dict)

    def test_min_max_connections(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import bootstrap_network
        result = _run(bootstrap_network(min_connections=1, max_connections=5))
        assert isinstance(result, dict)
