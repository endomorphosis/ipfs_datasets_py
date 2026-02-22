"""MCP P2P Transport — Profile E primitives (MCP++ §E transport layer).

Provides the core building blocks for the MCP over libp2p transport profile:

* :class:`TokenBucketRateLimiter` — thread-safe rate limiter
* :class:`LengthPrefixFramer` — big-endian u32 length-prefix codec
* :class:`MCPMessage` — typed MCP method call envelope
* :class:`P2PSessionConfig` — per-session configuration
* :data:`MCP_P2P_PROTOCOL_ID` — canonical libp2p protocol ID
* :data:`MCP_P2P_PUBSUB_TOPICS` — well-known pubsub topic names

Usage::

    from ipfs_datasets_py.mcp_server.mcp_p2p_transport import (
        TokenBucketRateLimiter, MCPMessage, LengthPrefixFramer,
        MCP_P2P_PROTOCOL_ID,
    )

    limiter = TokenBucketRateLimiter(rate=10.0, capacity=20.0)
    if limiter.consume():
        # handle request
        pass

    msg = MCPMessage(method="tools/call", params={"name": "echo", "arguments": {}})
    framer = LengthPrefixFramer()
    encoded = framer.encode(msg.to_bytes())
    decoded_msg, _ = framer.decode(encoded)
"""
from __future__ import annotations

import json
import logging
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Canonical libp2p protocol ID for MCP over P2P transport.
MCP_P2P_PROTOCOL_ID: str = "/mcp+p2p/1.0.0"

#: Well-known pubsub topic names used for MCP++ distributed events.
MCP_P2P_PUBSUB_TOPICS: Dict[str, str] = {
    "interface_announce": "/mcp/interface/announce/1.0.0",
    "receipt_disseminate": "/mcp/receipt/disseminate/1.0.0",
    "decision_disseminate": "/mcp/decision/disseminate/1.0.0",
    "scheduling_signal": "/mcp/scheduling/signal/1.0.0",
}


# ---------------------------------------------------------------------------
# TokenBucketRateLimiter
# ---------------------------------------------------------------------------


class TokenBucketRateLimiter:
    """Thread-safe token-bucket rate limiter.

    The bucket starts full.  Tokens are replenished at *rate* tokens/second up
    to *capacity*.  Each call to :meth:`consume` removes *tokens* from the
    bucket.  If insufficient tokens are available, :meth:`consume` returns
    *False* without blocking.

    Parameters
    ----------
    rate:
        Token replenishment rate in tokens per second.
    capacity:
        Maximum number of tokens in the bucket.

    Example::

        limiter = TokenBucketRateLimiter(rate=5.0, capacity=10.0)
        allowed = limiter.consume(1.0)   # True if tokens available
    """

    def __init__(self, rate: float, capacity: float) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.rate = rate
        self.capacity = capacity
        self._tokens: float = capacity
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def consume(self, tokens: float = 1.0) -> bool:
        """Attempt to consume *tokens* from the bucket.

        Returns *True* if the tokens were available and consumed, *False*
        otherwise (non-blocking).
        """
        with self._lock:
            self._refill_locked()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def available(self) -> float:
        """Return the current number of available tokens (after refill)."""
        with self._lock:
            self._refill_locked()
            return self._tokens

    def refill(self) -> None:
        """Force a refill computation (useful in tests)."""
        with self._lock:
            self._refill_locked()

    def reset(self) -> None:
        """Reset the bucket to full capacity."""
        with self._lock:
            self._tokens = self.capacity
            self._last_refill = time.monotonic()

    def get_info(self) -> Dict[str, Any]:
        """Return a dict describing the current limiter state."""
        return {
            "rate": self.rate,
            "capacity": self.capacity,
            "available": self.available(),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refill_locked(self) -> None:
        """Refill tokens based on elapsed time.  Must be called under *_lock*."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def __repr__(self) -> str:
        return (
            f"TokenBucketRateLimiter(rate={self.rate}, capacity={self.capacity}, "
            f"available≈{self._tokens:.2f})"
        )


# ---------------------------------------------------------------------------
# LengthPrefixFramer
# ---------------------------------------------------------------------------


class LengthPrefixFramer:
    """Big-endian unsigned 32-bit length-prefix codec for MCP P2P frames.

    Wire format::

        [4 bytes: uint32 big-endian length][<length> bytes: payload]

    Example::

        framer = LengthPrefixFramer()
        wire = framer.encode(b"hello")
        payload, remainder = framer.decode(wire)
        assert payload == b"hello"
        assert remainder == b""
    """

    HEADER_SIZE: int = 4  # struct.calcsize(">I")

    def encode(self, data: bytes) -> bytes:
        """Prepend a 4-byte big-endian length header to *data*."""
        header = struct.pack(">I", len(data))
        return header + data

    def decode(self, data: bytes) -> Tuple[bytes, bytes]:
        """Strip the length header and return ``(payload, remainder)``.

        Raises
        ------
        ValueError
            If *data* is shorter than the declared payload length.
        """
        if len(data) < self.HEADER_SIZE:
            raise ValueError(
                f"Frame too short: {len(data)} < {self.HEADER_SIZE} header bytes"
            )
        (length,) = struct.unpack_from(">I", data, 0)
        end = self.HEADER_SIZE + length
        if len(data) < end:
            raise ValueError(
                f"Incomplete frame: declared length {length} "
                f"but only {len(data) - self.HEADER_SIZE} payload bytes available"
            )
        return data[self.HEADER_SIZE : end], data[end:]

    def __repr__(self) -> str:
        return f"LengthPrefixFramer(header_size={self.HEADER_SIZE})"


# ---------------------------------------------------------------------------
# MCPMessage
# ---------------------------------------------------------------------------


@dataclass
class MCPMessage:
    """Typed envelope for a single MCP JSON-RPC 2.0 method call.

    Attributes
    ----------
    method:
        MCP method name, e.g. ``"tools/call"``.
    params:
        Method parameters dict.
    id:
        Request ID.  Defaults to a new UUID4 hex string.
    jsonrpc:
        JSON-RPC version string (always ``"2.0"``).
    """

    method: str
    params: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    jsonrpc: str = "2.0"

    def to_dict(self) -> Dict[str, Any]:
        """Return the message as a JSON-serialisable dict."""
        return {
            "jsonrpc": self.jsonrpc,
            "method": self.method,
            "params": self.params,
            "id": self.id,
        }

    def to_bytes(self) -> bytes:
        """Serialise to UTF-8 JSON bytes."""
        return json.dumps(self.to_dict(), separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> "MCPMessage":
        """Deserialise from UTF-8 JSON bytes.

        Raises
        ------
        ValueError
            If *data* is not valid JSON or missing required fields.
        """
        try:
            obj = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"Invalid MCPMessage bytes: {exc}") from exc
        method = obj.get("method")
        if not method:
            raise ValueError("MCPMessage missing 'method' field")
        return cls(
            method=method,
            params=obj.get("params") or {},
            id=obj.get("id") or uuid.uuid4().hex,
            jsonrpc=obj.get("jsonrpc", "2.0"),
        )

    @classmethod
    def from_dict(cls, obj: Dict[str, Any]) -> "MCPMessage":
        """Construct from a plain dict."""
        return cls(
            method=obj["method"],
            params=obj.get("params") or {},
            id=obj.get("id") or uuid.uuid4().hex,
            jsonrpc=obj.get("jsonrpc", "2.0"),
        )

    def __repr__(self) -> str:
        return f"MCPMessage(method={self.method!r}, id={self.id!r})"


# ---------------------------------------------------------------------------
# P2PSessionConfig
# ---------------------------------------------------------------------------


@dataclass
class P2PSessionConfig:
    """Configuration for a single P2P MCP session.

    Attributes
    ----------
    max_connections:
        Maximum simultaneous connections this node accepts.
    timeout_seconds:
        Read/write timeout in seconds.
    rate_limit:
        Token replenishment rate (tokens/second) for this session.
    capacity:
        Token bucket capacity.
    protocol_id:
        libp2p protocol ID string.
    enable_pubsub:
        Whether to enable pubsub for this session.
    """

    max_connections: int = 10
    timeout_seconds: float = 30.0
    rate_limit: float = 100.0
    capacity: float = 100.0
    protocol_id: str = MCP_P2P_PROTOCOL_ID
    enable_pubsub: bool = True

    def make_rate_limiter(self) -> TokenBucketRateLimiter:
        """Create a :class:`TokenBucketRateLimiter` from this config."""
        return TokenBucketRateLimiter(rate=self.rate_limit, capacity=self.capacity)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "max_connections": self.max_connections,
            "timeout_seconds": self.timeout_seconds,
            "rate_limit": self.rate_limit,
            "capacity": self.capacity,
            "protocol_id": self.protocol_id,
            "enable_pubsub": self.enable_pubsub,
        }
