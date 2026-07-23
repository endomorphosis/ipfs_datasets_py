"""Regression tests for the MCP++ dataset p2p compatibility facade."""

from __future__ import annotations

import asyncio


def test_dataset_libp2p_node_starts_without_raw_host() -> None:
    from ipfs_datasets_py.p2p_networking.libp2p_kit_full import LibP2PNode

    async def run_case():
        node = LibP2PNode(
            node_id="local-node",
            bootstrap_peers=["/ip4/127.0.0.1/tcp/4001/p2p/remote-node"],
        )
        await node.start()
        try:
            assert node.running is True
            assert node.host is None
            assert node.peer_id == "local-node"
            assert node.get_connected_peers() == ["remote-node"]
        finally:
            await node.stop()
        assert node.running is False

    asyncio.run(run_case())


def test_dataset_libp2p_node_health_uses_mcplusplus_status(monkeypatch) -> None:
    from ipfs_accelerate_py.mcp_server.tools.p2p import native_p2p_tools
    from ipfs_datasets_py.p2p_networking.libp2p_kit_full import LibP2PNode, NetworkProtocol

    calls = {}

    async def fake_status(**kwargs):
        calls.update(kwargs)
        return {"ok": True, "service": {"running": True}}

    monkeypatch.setattr(native_p2p_tools, "p2p_taskqueue_status", fake_status)

    async def run_case():
        node = LibP2PNode(
            node_id="local-node",
            bootstrap_peers=["/ip4/127.0.0.1/tcp/4001/p2p/remote-node"],
        )
        await node.start()
        try:
            return await node.send_message(
                peer_id="remote-node",
                protocol=NetworkProtocol.HEALTH_CHECK,
                data={"action": "health_check"},
                timeout_ms=2500,
            )
        finally:
            await node.stop()

    response = asyncio.run(run_case())

    assert response["status"] == "healthy"
    assert response["transport"] == "mcpplusplus-p2p"
    assert calls["peer_id"] == "remote-node"
    assert calls["remote_multiaddr"] == "/ip4/127.0.0.1/tcp/4001/p2p/remote-node"
    assert calls["timeout_s"] == 2.5


def test_dataset_libp2p_node_refuses_unsupported_legacy_protocols() -> None:
    from ipfs_datasets_py.p2p_networking.libp2p_kit_full import LibP2PNode, NetworkProtocol

    async def run_case():
        node = LibP2PNode(node_id="local-node")
        await node.start()
        try:
            return await node.send_message(
                peer_id="remote-node",
                protocol=NetworkProtocol.SHARD_TRANSFER,
                data={"action": "accept_shard"},
            )
        finally:
            await node.stop()

    response = asyncio.run(run_case())

    assert response["status"] == "unsupported"
    assert response["transport"] == "mcpplusplus-p2p"
    assert "raw libp2p stream fallback is disabled" in response["error"]


def test_dataset_libp2p_node_raw_keypair_creation_disabled() -> None:
    from ipfs_datasets_py.p2p_networking.libp2p_kit_full import (
        LibP2PNode,
        LibP2PNotAvailableError,
    )

    node = LibP2PNode(node_id="local-node")
    try:
        node._load_or_create_key_pair()
    except LibP2PNotAvailableError as exc:
        assert "MCP++ p2p runtime" in str(exc)
    else:
        raise AssertionError("raw keypair creation unexpectedly succeeded")
