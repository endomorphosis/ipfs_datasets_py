"""Profile E framing tests for the Profile F ceremony validator."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import trio

from ipfs_datasets_py.mcp_server.p2p_libp2p_transport import (
    MAX_P2P_MESSAGE_SIZE,
    MCPp2pNode,
    dispatch_profile_e_jsonrpc_request,
)


def _fixture() -> dict:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "Mcp-Plus-Plus" / "tests-py" / "fixtures" / "valid" / "profile_f_groth16_mpc_ceremony.json"
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise RuntimeError("shared MCP++ ceremony fixture is unavailable")


def _frame(payload: dict) -> bytes:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return len(encoded).to_bytes(4, "big") + encoded


def _decode_frames(data: bytes) -> list[dict]:
    frames: list[dict] = []
    offset = 0
    while offset < len(data):
        size = int.from_bytes(data[offset : offset + 4], "big")
        offset += 4
        frames.append(json.loads(data[offset : offset + size]))
        offset += size
    return frames


class _FragmentingStream:
    """Minimal libp2p stream double that fragments every read."""

    def __init__(self, inbound: bytes):
        self._inbound = bytearray(inbound)
        self.written = bytearray()
        self.closed = False

    async def read(self, size: int) -> bytes:
        if not self._inbound:
            return b""
        fragment_size = min(size, 2, len(self._inbound))
        fragment = bytes(self._inbound[:fragment_size])
        del self._inbound[:fragment_size]
        return fragment

    async def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def close(self) -> None:
        self.closed = True


def test_profile_e_stream_handles_initialize_tools_and_ceremony_validation() -> None:
    manifest = _fixture()
    stream = _FragmentingStream(
        b"".join(
            [
                _frame(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "capabilities": {
                                "experimental": {
                                    "mcp++/event-dag": True,
                                    "mcp++/groth16-mpc-ceremony": True,
                                }
                            }
                        },
                    }
                ),
                _frame({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                _frame({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
                _frame(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "mcp++/zk/ceremony/validate",
                        "params": {"manifest": manifest},
                    }
                ),
            ]
        )
    )

    asyncio.run(MCPp2pNode()._handle_stream(stream))
    responses = _decode_frames(bytes(stream.written))

    assert stream.closed is True
    assert [response["id"] for response in responses] == [1, 2, 3]
    assert responses[0]["result"]["capabilities"]["mcpPlusPlusProfiles"] == [
        "mcp++/deontic-policy",
        "mcp++/event-dag",
        "mcp++/p2p-transport",
    ]
    assert responses[0]["result"]["capabilities"]["experimental"]["mcp++/groth16-mpc-ceremony"] is True
    assert responses[1]["result"] == {"tools": []}
    assert responses[2]["result"]["production_eligible"] is True
    assert responses[2]["result"]["ceremony_cid"] == "sha256:645338f97ee9f1d17529c4be2b88f928b8bc4c19d906172f0ba0d269780f04b8"


def test_profile_e_dispatch_rejects_invalid_ceremony_params() -> None:
    response = asyncio.run(
        dispatch_profile_e_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "mcp++/zk/ceremony/validate",
                "params": {"manifest": "not-an-object"},
            }
        )
    )

    assert response == {
        "jsonrpc": "2.0",
        "id": 4,
        "error": {"code": -32602, "message": "manifest must be an object"},
    }


def test_profile_e_stream_rejects_oversized_frames_before_allocating() -> None:
    stream = _FragmentingStream((MAX_P2P_MESSAGE_SIZE + 1).to_bytes(4, "big"))

    asyncio.run(MCPp2pNode()._handle_stream(stream))

    assert stream.closed is True
    assert stream.written == b""


def test_profile_e_node_starts_with_the_installed_multiformats_runtime() -> None:
    async def run_node() -> None:
        node = MCPp2pNode(listen_addrs=["/ip4/127.0.0.1/tcp/0"], bootstrap_peers=[])
        async with trio.open_nursery() as nursery:
            with trio.fail_after(20):
                await node.start(nursery)
            assert node.to_dict()["started"] is True
            assert len(node.multiaddrs) == 1
            assert "/p2p/" in node.multiaddrs[0]
            await node.stop()
            nursery.cancel_scope.cancel()

    trio.run(run_node)
