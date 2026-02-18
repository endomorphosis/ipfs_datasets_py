import json
import socket
import sys
from pathlib import Path

import pytest


def _prefer_local_ipfs_accelerate_py() -> None:
    root = Path(__file__).resolve().parents[2]
    candidate = root / "ipfs_accelerate_py"
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


_prefer_local_ipfs_accelerate_py()


def _pick_free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


class FakeRegistry:
    def __init__(self) -> None:
        self.tools = {
            "echo": {
                "function": self.echo,
                "description": "Echo a string",
                "input_schema": {},
            }
        }

    async def validate_p2p_message(self, msg: dict) -> bool:
        return True

    async def echo(self, *, text: str = "") -> dict:
        return {"text": text}


def test_mcp_p2p_end_to_end_smoke(monkeypatch, tmp_path):
    libp2p = pytest.importorskip("libp2p")

    from ipfs_accelerate_py.github_cli.libp2p_compat import ensure_libp2p_compatible

    if not ensure_libp2p_compatible():
        pytest.skip("libp2p compatibility patches unavailable")

    from ipfs_accelerate_py.p2p_tasks.mcp_p2p import PROTOCOL_MCP_P2P_V1
    from ipfs_accelerate_py.p2p_tasks.mcp_p2p_client import (
        MCPRemoteError,
        MCPP2PClient,
        open_libp2p_stream_by_multiaddr,
        trio_libp2p_host_listen,
    )
    from ipfs_accelerate_py.p2p_tasks.runtime import TaskQueueP2PServiceRuntime
    from ipfs_accelerate_py.p2p_tasks.service import get_local_service_state

    # Speed up and avoid network-wide discovery during the smoke test.
    monkeypatch.setenv("IPFS_ACCELERATE_PY_TASK_P2P_MDNS", "0")
    monkeypatch.setenv("IPFS_ACCELERATE_PY_TASK_P2P_DHT", "0")
    monkeypatch.setenv("IPFS_ACCELERATE_PY_TASK_P2P_RENDEZVOUS", "0")
    monkeypatch.setenv("IPFS_ACCELERATE_PY_TASK_P2P_AUTONAT", "0")
    monkeypatch.setenv("IPFS_ACCELERATE_PY_TASK_P2P_RELAY", "0")
    monkeypatch.setenv("IPFS_ACCELERATE_PY_TASK_P2P_HOLEPUNCH", "0")
    monkeypatch.setenv("IPFS_ACCELERATE_PY_TASK_P2P_BOOTSTRAP_PEERS", "0")
    monkeypatch.setenv("IPFS_ACCELERATE_PY_TASK_P2P_ANNOUNCE_FILE", "0")
    monkeypatch.setenv("IPFS_ACCELERATE_PY_TASK_P2P_LISTEN_HOST", "127.0.0.1")
    monkeypatch.setenv("IPFS_ACCELERATE_PY_MCP_P2P_MAX_FRAMES", "16")

    listen_port = _pick_free_port()
    runtime = TaskQueueP2PServiceRuntime()
    handle = runtime.start(
        queue_path=str(tmp_path / "task_queue.duckdb"),
        listen_port=listen_port,
        accelerate_instance=FakeRegistry(),
    )

    assert handle.started.wait(2.0) is True

    import trio

    async def _client_roundtrip() -> None:
        # Wait for peer_id publication.
        peer_id = ""
        for _ in range(50):
            st = get_local_service_state() or {}
            peer_id = str(st.get("peer_id") or "")
            if peer_id:
                break
            await trio.sleep(0.05)
        assert peer_id

        async with trio_libp2p_host_listen(listen_multiaddr="/ip4/127.0.0.1/tcp/0") as host:
            ma = f"/ip4/127.0.0.1/tcp/{listen_port}/p2p/{peer_id}"

            # Deterministic negative test: invalid jsonrpc version.
            stream = await open_libp2p_stream_by_multiaddr(
                host,
                peer_multiaddr=ma,
                protocols=[PROTOCOL_MCP_P2P_V1],
            )
            try:
                client = MCPP2PClient(stream, max_frame_bytes=1024 * 1024)
                try:
                    await client.request_raw(
                        {"jsonrpc": "1.0", "id": 99, "method": "initialize", "params": {}}
                    )
                    raise AssertionError("expected invalid_jsonrpc error")
                except MCPRemoteError as exc:
                    assert exc.message == "invalid_jsonrpc"
            finally:
                try:
                    await stream.close()
                except Exception:
                    pass

            stream = await open_libp2p_stream_by_multiaddr(
                host,
                peer_multiaddr=ma,
                protocols=[PROTOCOL_MCP_P2P_V1],
            )
            try:
                client = MCPP2PClient(stream, max_frame_bytes=1024 * 1024)

                # Deterministic negative test: init is required as first message.
                try:
                    await client.request("tools/list", {})
                    raise AssertionError("expected init_required error")
                except MCPRemoteError as exc:
                    assert exc.message == "init_required"

            finally:
                try:
                    await stream.close()
                except Exception:
                    pass

            # Start a fresh session for the positive roundtrip.
            stream = await open_libp2p_stream_by_multiaddr(
                host,
                peer_multiaddr=ma,
                protocols=[PROTOCOL_MCP_P2P_V1],
            )
            try:
                client = MCPP2PClient(stream, max_frame_bytes=1024 * 1024)

                resp = await client.initialize({})
                assert (resp or {}).get("result", {}).get("ok") is True

                tools = await client.tools_list()
                assert any(t.get("name") == "echo" for t in tools if isinstance(t, dict))

                out = await client.tools_call("echo", {"text": "hi"})
                assert out == {"text": "hi"}
            finally:
                try:
                    await stream.close()
                except Exception:
                    pass

    trio.run(_client_roundtrip)

    # stop() uses trio.from_thread, so call it from this (non-Trio) context.
    assert runtime.stop(timeout_s=15.0) is True
