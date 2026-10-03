"""`mcp+p2p` framing and abuse-resistance helpers.

Implements deterministic length-prefixed framing and simple inbound
rate-limiting primitives used by transport conformance tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from json import JSONDecodeError
import time
from typing import Any, Dict, Tuple


class FramingError(Exception):
    """Raised when frame encoding/decoding fails."""


class FrameSizeExceededError(FramingError):
    """Raised when a frame exceeds configured maximum."""


def encode_jsonrpc_frame(
    payload: Dict[str, Any], *, max_frame_bytes: int = 16 * 1024 * 1024
) -> bytes:
    """Encode JSON-RPC payload into u32 length-prefixed frame."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(body) > int(max_frame_bytes):
        raise FrameSizeExceededError(f"frame_too_large:{len(body)}>{int(max_frame_bytes)}")
    return len(body).to_bytes(4, byteorder="big", signed=False) + body


def decode_jsonrpc_frame(
    frame: bytes, *, max_frame_bytes: int = 16 * 1024 * 1024
) -> Tuple[Dict[str, Any], int]:
    """Decode u32 length-prefixed frame and return payload + consumed bytes."""
    if len(frame) < 4:
        raise FramingError("incomplete_prefix")
    declared = int.from_bytes(frame[:4], byteorder="big", signed=False)
    if declared > int(max_frame_bytes):
        raise FrameSizeExceededError(f"declared_frame_too_large:{declared}>{int(max_frame_bytes)}")
    if len(frame) < 4 + declared:
        raise FramingError("incomplete_body")
    body = frame[4 : 4 + declared]
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FramingError("invalid_utf8") from exc

    try:
        payload = json.loads(decoded)
    except JSONDecodeError as exc:
        raise FramingError("invalid_json") from exc

    if not isinstance(payload, dict):
        raise FramingError("payload_not_object")
    return payload, 4 + declared


@dataclass
class TokenBucketLimiter:
    """Simple token-bucket limiter for inbound sessions/message volume."""

    capacity: float
    refill_rate_per_sec: float
    _tokens: float = 0.0
    _last_ts: float = 0.0

    def __post_init__(self) -> None:
        self.capacity = float(max(1.0, self.capacity))
        self.refill_rate_per_sec = float(max(0.0001, self.refill_rate_per_sec))
        self._tokens = self.capacity
        self._last_ts = time.monotonic()

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._last_ts)
        self._last_ts = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate_per_sec)

    def allow(self, cost: float = 1.0, *, now: float | None = None) -> bool:
        """Return True if request cost can be consumed under current budget."""
        t = time.monotonic() if now is None else float(now)
        c = float(max(0.0, cost))
        self._refill(t)
        if self._tokens >= c:
            self._tokens -= c
            return True
        return False

    def snapshot(self) -> Dict[str, float]:
        """Return current limiter state."""
        return {
            "capacity": self.capacity,
            "refill_rate_per_sec": self.refill_rate_per_sec,
            "tokens": self._tokens,
        }


__all__ = [
    "FramingError",
    "FrameSizeExceededError",
    "TokenBucketLimiter",
    "decode_jsonrpc_frame",
    "encode_jsonrpc_frame",
]
