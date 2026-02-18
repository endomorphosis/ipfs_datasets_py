import asyncio
import json
import struct
import sys
from pathlib import Path

import pytest


def _prefer_local_ipfs_accelerate_py() -> None:
    root = Path(__file__).resolve().parents[2]
    candidate = root / "ipfs_accelerate_py"
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


_prefer_local_ipfs_accelerate_py()


from ipfs_accelerate_py.p2p_tasks.mcp_p2p import write_u32_framed_json  # noqa: E402
from ipfs_accelerate_py.p2p_tasks.mcp_p2p_client import (  # noqa: E402
    MCPFramingError,
    MCPRemoteError,
    MCPP2PClient,
)


class FakeStream:
    def __init__(self, read_chunks: list[bytes]) -> None:
        self._chunks = list(read_chunks)
        self.writes: list[bytes] = []

    async def read(self, n: int) -> bytes:
        await asyncio.sleep(0)
        if not self._chunks:
            return b""
        chunk = self._chunks[0]
        if len(chunk) <= n:
            self._chunks.pop(0)
            return chunk
        self._chunks[0] = chunk[n:]
        return chunk[:n]

    async def write(self, data: bytes) -> None:
        await asyncio.sleep(0)
        self.writes.append(bytes(data))


def _frame(obj: dict) -> bytes:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return struct.pack(">I", len(payload)) + payload


def test_client_detects_mismatched_response_id() -> None:
    # Client sends id=1, but remote responds with id=2.
    stream = FakeStream([
        _frame({"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}),
    ])

    async def _go() -> None:
        client = MCPP2PClient(stream)
        with pytest.raises(MCPFramingError) as excinfo:
            await client.request("initialize", {}, id_value=1)
        assert "mismatched_id" in str(excinfo.value)

    asyncio.run(_go())


def test_client_raises_remote_error() -> None:
    stream = FakeStream([
        _frame({"jsonrpc": "2.0", "id": 7, "error": {"code": -32601, "message": "method_not_found"}}),
    ])

    async def _go() -> None:
        client = MCPP2PClient(stream)
        with pytest.raises(MCPRemoteError) as excinfo:
            await client.request("nope/not-a-method", {}, id_value=7)
        assert excinfo.value.code == -32601
        assert excinfo.value.message == "method_not_found"
        assert excinfo.value.id_value == 7

    asyncio.run(_go())


def test_client_notify_writes_frame_without_id() -> None:
    # Ensure notify sends a frame and doesn't require a response.
    stream = FakeStream([])

    async def _go() -> None:
        client = MCPP2PClient(stream)
        await client.notify("tools/list", {})

    asyncio.run(_go())

    assert stream.writes
    # Decode the frame written.
    data = b"".join(stream.writes)
    ln = struct.unpack(">I", data[:4])[0]
    msg = json.loads(data[4 : 4 + ln].decode("utf-8"))
    assert msg.get("jsonrpc") == "2.0"
    assert msg.get("method") == "tools/list"
    assert "id" not in msg
