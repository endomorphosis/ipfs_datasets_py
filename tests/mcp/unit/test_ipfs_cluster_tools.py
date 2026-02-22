"""Unit tests for ipfs_cluster_tools (Phase B2 session 33).

Covers:
- manage_ipfs_cluster: status, peer management, pin operations
- manage_ipfs_content: add, retrieve, pin, delete
"""
from __future__ import annotations

import asyncio

import pytest


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# manage_ipfs_cluster
# ---------------------------------------------------------------------------

class TestManageIpfsCluster:
    def test_status_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_cluster,
        )
        r = _run(manage_ipfs_cluster("status"))
        assert isinstance(r, dict)

    def test_result_has_action_key(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_cluster,
        )
        r = _run(manage_ipfs_cluster("status"))
        assert "action" in r or "status" in r

    def test_list_nodes_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_cluster,
        )
        r = _run(manage_ipfs_cluster("list_nodes"))
        assert isinstance(r, dict)

    def test_add_peer_with_node_id(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_cluster,
        )
        r = _run(manage_ipfs_cluster("add_peer", node_id="QmPeer123"))
        assert isinstance(r, dict)

    def test_pin_cid_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_cluster,
        )
        r = _run(
            manage_ipfs_cluster(
                "pin", cid="QmTestCID123", replication_factor=2
            )
        )
        assert isinstance(r, dict)

    def test_custom_replication_factor_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_cluster,
        )
        r = _run(manage_ipfs_cluster("pin", cid="Qmtest", replication_factor=5))
        assert isinstance(r, dict)

    def test_filters_param_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_cluster,
        )
        r = _run(
            manage_ipfs_cluster("list_nodes", filters={"status": "active"})
        )
        assert isinstance(r, dict)


# ---------------------------------------------------------------------------
# manage_ipfs_content
# ---------------------------------------------------------------------------

class TestManageIpfsContent:
    def test_add_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_content,
        )
        r = _run(manage_ipfs_content("add", content="hello world"))
        assert isinstance(r, dict)

    def test_result_has_action_key(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_content,
        )
        r = _run(manage_ipfs_content("add", content="data"))
        assert "action" in r or "status" in r

    def test_retrieve_with_cid(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_content,
        )
        r = _run(manage_ipfs_content("retrieve", cid="QmTestCID"))
        assert isinstance(r, dict)

    def test_pin_cid_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_content,
        )
        r = _run(manage_ipfs_content("pin", cid="QmTest"))
        assert isinstance(r, dict)

    def test_delete_cid_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_content,
        )
        r = _run(manage_ipfs_content("delete", cid="QmTest"))
        assert isinstance(r, dict)

    def test_metadata_param_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools.enhanced_ipfs_cluster_tools import (
            manage_ipfs_content,
        )
        r = _run(
            manage_ipfs_content(
                "add",
                content="data",
                metadata={"source": "test"},
                content_type="text/plain",
            )
        )
        assert isinstance(r, dict)
