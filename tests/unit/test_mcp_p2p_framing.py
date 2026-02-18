import asyncio
import json
import struct
import sys
from pathlib import Path


def _prefer_local_ipfs_accelerate_py() -> None:
    root = Path(__file__).resolve().parents[2]
    candidate = root / "ipfs_accelerate_py"
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


_prefer_local_ipfs_accelerate_py()


from ipfs_accelerate_py.p2p_tasks.mcp_p2p import (  # noqa: E402
    PROTOCOL_MCP_P2P_V1,
    handle_mcp_p2p_stream,
    read_u32_framed_json,
)


class FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.writes: list[bytes] = []
        self.closed = False

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

    async def close(self) -> None:
        await asyncio.sleep(0)
        self.closed = True


def _frame(obj: dict) -> bytes:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return struct.pack(">I", len(payload)
    ) + payload


def _parse_first_write(stream: FakeStream) -> dict:
    data = b"".join(stream.writes)
    length = struct.unpack(">I", data[:4])[0]
    payload = data[4 : 4 + length]
    return json.loads(payload.decode("utf-8"))


class FakeRegistry:
    def __init__(self) -> None:
        self.tools = {
            "echo": {
                "function": self.echo,
                "description": "Echo arguments",
                "input_schema": {},
            }
        }

    async def validate_p2p_message(self, msg: dict) -> bool:
        return True

    async def echo(self, *, text: str = "") -> dict:
        return {"text": text}


class DenyRegistry(FakeRegistry):
    async def validate_p2p_message(self, msg: dict) -> bool:
        return False


def test_protocol_id_constant() -> None:
    assert PROTOCOL_MCP_P2P_V1 == "/mcp+p2p/1.0.0"


def test_read_u32_framed_json_ok() -> None:
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    stream = FakeStream([_frame(msg)])

    out, err = asyncio.run(read_u32_framed_json(stream, max_frame_bytes=1024))
    assert err is None
    assert out == msg


def test_mcp_p2p_handler_requires_initialize_first() -> None:
    msg = {"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}}
    stream = FakeStream([_frame(msg)])

    asyncio.run(handle_mcp_p2p_stream(stream, local_peer_id="peer", max_frame_bytes=1024))
    assert stream.closed is True
    assert stream.writes, "expected an error response"

    resp = _parse_first_write(stream)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 7
    assert resp["error"]["message"] == "init_required"


def test_mcp_p2p_handler_initialize_ack() -> None:
    msg = {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}}
    stream = FakeStream([_frame(msg)])

    asyncio.run(handle_mcp_p2p_stream(stream, local_peer_id="peer", max_frame_bytes=1024))
    assert stream.closed is True
    resp = _parse_first_write(stream)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 2
    assert resp["result"]["ok"] is True
    assert resp["result"]["transport"] == "/mcp+p2p/1.0.0"


def test_mcp_p2p_tools_list_after_initialize() -> None:
    registry = FakeRegistry()
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    lst = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    stream = FakeStream([_frame(init), _frame(lst)])

    asyncio.run(handle_mcp_p2p_stream(stream, local_peer_id="peer", registry=registry, max_frame_bytes=4096))
    assert len(stream.writes) >= 2


def test_mcp_p2p_tools_call_after_initialize() -> None:
    registry = FakeRegistry()
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    call = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"text": "hi"}},
    }
    stream = FakeStream([_frame(init), _frame(call)])

    asyncio.run(handle_mcp_p2p_stream(stream, local_peer_id="peer", registry=registry, max_frame_bytes=4096))
    assert len(stream.writes) >= 2


def test_mcp_p2p_rejects_oversize_frame() -> None:
    oversized_len = 100
    header = struct.pack(">I", oversized_len)
    stream = FakeStream([header])

    asyncio.run(handle_mcp_p2p_stream(stream, local_peer_id="peer", max_frame_bytes=16))
    assert stream.closed is True
    assert stream.writes
    resp = _parse_first_write(stream)
    assert resp["error"]["message"] == "frame_too_large"


def test_mcp_p2p_unauthorized_closes() -> None:
    registry = DenyRegistry()
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    stream = FakeStream([_frame(init)])

    asyncio.run(handle_mcp_p2p_stream(stream, local_peer_id="peer", registry=registry, max_frame_bytes=4096))
    assert stream.closed is True
    assert stream.writes
    resp = _parse_first_write(stream)
    assert resp["error"]["message"] == "unauthorized"
