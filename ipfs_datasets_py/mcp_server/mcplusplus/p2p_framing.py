"""Deterministic `mcp+p2p` framing, quotas, correlation, and replay detection.

Implements Profile E layer-T primitives (transport-mcp-p2p.md):

* LengthPrefixedFrame@1 — u32 big-endian length-prefixed UTF-8 JSON frames
* TransportQuota@1 — per-peer stream / in-flight / bandwidth / rate limits
* Request/response correlation with multi-in-flight support and cancel
* Sliding-window replay detection for duplicate frames and response ids
* Idle-timeout tracking for stream recycle decisions

Wire layout (normative default)::

    | length (4 bytes, u32 BE) | payload (N bytes, UTF-8 JSON) |

Default maximum frame body size: 16 MiB. Receivers reject larger declared
lengths fail-closed without allocating attacker-controlled buffers.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from json import JSONDecodeError
import time
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROTOCOL_ID_DEFAULT = "/mcp+p2p/1.0.0"
DEFAULT_MAX_FRAME_BYTES = 16 * 1024 * 1024  # 16 MiB
HEADER_SIZE = 4

DEFAULT_MAX_STREAMS_PER_PEER = 32
DEFAULT_MAX_IN_FLIGHT_PER_PEER = 64
DEFAULT_MAX_BANDWIDTH_BYTES_PER_SEC = 16 * 1024 * 1024
DEFAULT_RATE_CAPACITY = 100.0
DEFAULT_RATE_REFILL_PER_SEC = 50.0
DEFAULT_IDLE_TIMEOUT_SEC = 60.0
DEFAULT_REQUEST_TIMEOUT_SEC = 30.0
DEFAULT_REPLAY_WINDOW_SEC = 300.0
DEFAULT_REPLAY_WINDOW_SIZE = 4096


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FramingError(Exception):
    """Raised when frame encoding/decoding fails."""


class FrameSizeExceededError(FramingError):
    """Raised when a frame exceeds the configured maximum size."""


class CorrelationError(Exception):
    """Raised when request/response correlation fails."""


class QuotaExceededError(Exception):
    """Raised when a transport quota is exceeded."""


class ReplayDetectedError(Exception):
    """Raised when a duplicate frame or response id is observed."""


class IdleTimeoutError(Exception):
    """Raised when a stream exceeds its idle timeout."""


# ---------------------------------------------------------------------------
# Length-prefixed framing (LengthPrefixedFrame@1)
# ---------------------------------------------------------------------------


def encode_jsonrpc_frame(
    payload: Mapping[str, Any],
    *,
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
) -> bytes:
    """Encode a JSON-RPC / P2PMessage object into a u32 length-prefixed frame.

    Encoding is deterministic: compact separators, sorted keys off (insertion
    order preserved), ASCII-safe ``ensure_ascii=True``.
    """
    if not isinstance(payload, Mapping):
        raise FramingError("payload_not_object")
    body = json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    limit = int(max_frame_bytes)
    if len(body) > limit:
        raise FrameSizeExceededError(f"frame_too_large:{len(body)}>{limit}")
    return len(body).to_bytes(HEADER_SIZE, byteorder="big", signed=False) + body


def decode_jsonrpc_frame(
    frame: bytes,
    *,
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
) -> Tuple[Dict[str, Any], int]:
    """Decode a u32 length-prefixed frame; return ``(payload, consumed_bytes)``.

    Raises:
        FramingError: incomplete or invalid frame body.
        FrameSizeExceededError: declared length exceeds *max_frame_bytes*.
    """
    if not isinstance(frame, (bytes, bytearray, memoryview)):
        raise FramingError("frame_not_bytes")
    data = bytes(frame)
    if len(data) < HEADER_SIZE:
        raise FramingError("incomplete_prefix")
    declared = int.from_bytes(data[:HEADER_SIZE], byteorder="big", signed=False)
    limit = int(max_frame_bytes)
    if declared > limit:
        raise FrameSizeExceededError(f"declared_frame_too_large:{declared}>{limit}")
    if len(data) < HEADER_SIZE + declared:
        raise FramingError("incomplete_body")
    body = data[HEADER_SIZE : HEADER_SIZE + declared]
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
    return payload, HEADER_SIZE + declared


@dataclass
class LengthPrefixedFrame:
    """LengthPrefixedFrame@1 — deterministic u32-BE framed JSON messages.

    Parameters
    ----------
    max_frame_bytes:
        Maximum allowed payload size. Default 16 MiB per Profile E.
    """

    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES
    protocol_id: str = PROTOCOL_ID_DEFAULT

    def __post_init__(self) -> None:
        if int(self.max_frame_bytes) < 1:
            raise ValueError("max_frame_bytes must be >= 1")
        self.max_frame_bytes = int(self.max_frame_bytes)

    def encode(self, payload: Mapping[str, Any]) -> bytes:
        """Encode *payload* as a length-prefixed frame."""
        return encode_jsonrpc_frame(payload, max_frame_bytes=self.max_frame_bytes)

    def decode(self, frame: bytes) -> Tuple[Dict[str, Any], int]:
        """Decode *frame*; return payload and bytes consumed."""
        return decode_jsonrpc_frame(frame, max_frame_bytes=self.max_frame_bytes)

    def encode_bytes(self, body: bytes) -> bytes:
        """Wrap raw UTF-8 body bytes with a length prefix (no JSON parse)."""
        if not isinstance(body, (bytes, bytearray, memoryview)):
            raise FramingError("body_not_bytes")
        raw = bytes(body)
        if len(raw) > self.max_frame_bytes:
            raise FrameSizeExceededError(
                f"frame_too_large:{len(raw)}>{self.max_frame_bytes}"
            )
        return len(raw).to_bytes(HEADER_SIZE, byteorder="big", signed=False) + raw

    def peek_declared_length(self, header: bytes) -> int:
        """Read the declared body length from a 4-byte header, enforcing max size."""
        if len(header) < HEADER_SIZE:
            raise FramingError("incomplete_prefix")
        declared = int.from_bytes(header[:HEADER_SIZE], byteorder="big", signed=False)
        if declared > self.max_frame_bytes:
            raise FrameSizeExceededError(
                f"declared_frame_too_large:{declared}>{self.max_frame_bytes}"
            )
        return declared


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


@dataclass
class TokenBucketLimiter:
    """Token-bucket limiter for inbound stream creation / message volume."""

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
        """Return True if *cost* can be consumed under the current budget."""
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


# ---------------------------------------------------------------------------
# Transport quotas (TransportQuota@1)
# ---------------------------------------------------------------------------


@dataclass
class PeerQuotaState:
    """Mutable per-peer counters for TransportQuota@1."""

    open_streams: int = 0
    in_flight: int = 0
    bytes_window: int = 0
    window_started: float = 0.0


@dataclass
class TransportQuota:
    """TransportQuota@1 — stream, in-flight, bandwidth, and rate limits.

    Enforces Profile E §3.5 abuse controls. All checks are fail-closed:
    exceeding a quota raises :class:`QuotaExceededError` or returns False
    depending on the call site.
    """

    max_streams_per_peer: int = DEFAULT_MAX_STREAMS_PER_PEER
    max_in_flight_per_peer: int = DEFAULT_MAX_IN_FLIGHT_PER_PEER
    max_bandwidth_bytes_per_sec: int = DEFAULT_MAX_BANDWIDTH_BYTES_PER_SEC
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES
    rate_capacity: float = DEFAULT_RATE_CAPACITY
    rate_refill_per_sec: float = DEFAULT_RATE_REFILL_PER_SEC
    _peers: Dict[str, PeerQuotaState] = field(default_factory=dict)
    _rate: Dict[str, TokenBucketLimiter] = field(default_factory=dict)

    def _state(self, peer_id: str) -> PeerQuotaState:
        key = str(peer_id or "")
        if key not in self._peers:
            self._peers[key] = PeerQuotaState(window_started=time.monotonic())
        return self._peers[key]

    def _limiter(self, peer_id: str) -> TokenBucketLimiter:
        key = str(peer_id or "")
        if key not in self._rate:
            self._rate[key] = TokenBucketLimiter(
                capacity=self.rate_capacity,
                refill_rate_per_sec=self.rate_refill_per_sec,
            )
        return self._rate[key]

    def _roll_bandwidth(self, state: PeerQuotaState, now: float) -> None:
        if now - state.window_started >= 1.0:
            state.bytes_window = 0
            state.window_started = now

    def open_stream(self, peer_id: str) -> None:
        """Register a new stream for *peer_id*; raise if stream quota exceeded."""
        state = self._state(peer_id)
        if state.open_streams >= int(self.max_streams_per_peer):
            raise QuotaExceededError(
                f"stream_quota_exceeded:{state.open_streams}>={self.max_streams_per_peer}"
            )
        state.open_streams += 1

    def close_stream(self, peer_id: str) -> None:
        """Release one stream slot for *peer_id*."""
        state = self._state(peer_id)
        state.open_streams = max(0, state.open_streams - 1)

    def begin_request(self, peer_id: str) -> None:
        """Reserve an in-flight request slot."""
        state = self._state(peer_id)
        if state.in_flight >= int(self.max_in_flight_per_peer):
            raise QuotaExceededError(
                f"in_flight_quota_exceeded:{state.in_flight}>={self.max_in_flight_per_peer}"
            )
        state.in_flight += 1

    def end_request(self, peer_id: str) -> None:
        """Release an in-flight request slot."""
        state = self._state(peer_id)
        state.in_flight = max(0, state.in_flight - 1)

    def allow_message(
        self,
        peer_id: str,
        *,
        nbytes: int = 0,
        cost: float = 1.0,
        now: float | None = None,
    ) -> bool:
        """Return True if inbound message volume / bandwidth remain within quota."""
        t = time.monotonic() if now is None else float(now)
        state = self._state(peer_id)
        self._roll_bandwidth(state, t)
        size = max(0, int(nbytes))
        if size > int(self.max_frame_bytes):
            return False
        if state.bytes_window + size > int(self.max_bandwidth_bytes_per_sec):
            return False
        if not self._limiter(peer_id).allow(cost=cost, now=t):
            return False
        state.bytes_window += size
        return True

    def snapshot(self, peer_id: str) -> Dict[str, Any]:
        """Return quota counters for *peer_id*."""
        state = self._state(peer_id)
        limiter = self._limiter(peer_id)
        return {
            "peer_id": str(peer_id),
            "open_streams": state.open_streams,
            "in_flight": state.in_flight,
            "bytes_window": state.bytes_window,
            "max_streams_per_peer": self.max_streams_per_peer,
            "max_in_flight_per_peer": self.max_in_flight_per_peer,
            "max_bandwidth_bytes_per_sec": self.max_bandwidth_bytes_per_sec,
            "max_frame_bytes": self.max_frame_bytes,
            "rate": limiter.snapshot(),
        }


# ---------------------------------------------------------------------------
# Correlation + multi-in-flight + cancel
# ---------------------------------------------------------------------------


class RequestState(str, Enum):
    """Lifecycle of a correlated in-flight request."""

    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass
class CorrelatedRequest:
    """One in-flight JSON-RPC request tracked for correlation."""

    request_id: Union[str, int]
    method: str = ""
    started_at: float = 0.0
    state: RequestState = RequestState.IN_FLIGHT
    peer_id: str = ""


@dataclass
class CorrelationTable:
    """Preserve JSON-RPC ``id`` correlation across a multiplexed stream.

    Supports multiple concurrent in-flight requests, cancel of a single id,
    and request-timeout surfacing (failure, not empty success).
    """

    max_in_flight: int = DEFAULT_MAX_IN_FLIGHT_PER_PEER
    request_timeout_sec: float = DEFAULT_REQUEST_TIMEOUT_SEC
    _pending: Dict[Union[str, int], CorrelatedRequest] = field(default_factory=dict)

    def register(
        self,
        request_id: Union[str, int],
        *,
        method: str = "",
        peer_id: str = "",
        now: float | None = None,
    ) -> CorrelatedRequest:
        """Register a new in-flight request id."""
        if request_id is None:
            raise CorrelationError("missing_request_id")
        if request_id in self._pending and self._pending[request_id].state == RequestState.IN_FLIGHT:
            raise CorrelationError(f"duplicate_in_flight_id:{request_id!r}")
        if self.in_flight_count() >= int(self.max_in_flight):
            raise CorrelationError(
                f"in_flight_limit:{self.in_flight_count()}>={self.max_in_flight}"
            )
        t = time.monotonic() if now is None else float(now)
        entry = CorrelatedRequest(
            request_id=request_id,
            method=str(method or ""),
            started_at=t,
            state=RequestState.IN_FLIGHT,
            peer_id=str(peer_id or ""),
        )
        self._pending[request_id] = entry
        return entry

    def complete(self, request_id: Union[str, int]) -> CorrelatedRequest:
        """Mark *request_id* as completed and remove from the pending set."""
        entry = self._pending.pop(request_id, None)
        if entry is None:
            raise CorrelationError(f"unknown_request_id:{request_id!r}")
        if entry.state == RequestState.CANCELLED:
            raise CorrelationError(f"already_cancelled:{request_id!r}")
        entry.state = RequestState.COMPLETED
        return entry

    def cancel(self, request_id: Union[str, int]) -> CorrelatedRequest:
        """Cancel an in-flight request without inventing a success result."""
        entry = self._pending.get(request_id)
        if entry is None:
            raise CorrelationError(f"unknown_request_id:{request_id!r}")
        if entry.state != RequestState.IN_FLIGHT:
            raise CorrelationError(f"not_in_flight:{request_id!r}:{entry.state.value}")
        entry.state = RequestState.CANCELLED
        self._pending.pop(request_id, None)
        return entry

    def match_response(self, response: Mapping[str, Any]) -> CorrelatedRequest:
        """Correlate a response object via its ``id`` field and complete it."""
        if "id" not in response:
            raise CorrelationError("response_missing_id")
        return self.complete(response["id"])

    def expire_timed_out(self, *, now: float | None = None) -> List[CorrelatedRequest]:
        """Mark and remove requests that exceeded *request_timeout_sec*."""
        t = time.monotonic() if now is None else float(now)
        expired: List[CorrelatedRequest] = []
        for rid, entry in list(self._pending.items()):
            if entry.state != RequestState.IN_FLIGHT:
                continue
            if t - entry.started_at >= float(self.request_timeout_sec):
                entry.state = RequestState.TIMED_OUT
                self._pending.pop(rid, None)
                expired.append(entry)
        return expired

    def in_flight_count(self) -> int:
        """Number of currently in-flight requests."""
        return sum(1 for e in self._pending.values() if e.state == RequestState.IN_FLIGHT)

    def in_flight_ids(self) -> List[Union[str, int]]:
        """Return ids of currently in-flight requests."""
        return [e.request_id for e in self._pending.values() if e.state == RequestState.IN_FLIGHT]

    def snapshot(self) -> Dict[str, Any]:
        """Return correlation table state."""
        return {
            "max_in_flight": self.max_in_flight,
            "request_timeout_sec": self.request_timeout_sec,
            "in_flight": self.in_flight_count(),
            "ids": self.in_flight_ids(),
        }


# ---------------------------------------------------------------------------
# Replay detection
# ---------------------------------------------------------------------------


def frame_fingerprint(frame: bytes) -> str:
    """Stable fingerprint of a raw frame for duplicate detection."""
    return hashlib.sha256(bytes(frame)).hexdigest()


def response_id_key(response_id: Union[str, int, None], *, peer_id: str = "") -> str:
    """Build a stable key for response-id replay tracking."""
    return f"{peer_id}|{response_id!r}"


@dataclass
class ReplayWindow:
    """Sliding-window detector for duplicate frames and response ids.

    Profile E §3.4: implementations SHOULD detect duplicate frames or
    duplicate response ``id`` values within a configured window and drop or
    reject them. This does not replace UCAN freshness checks.
    """

    window_sec: float = DEFAULT_REPLAY_WINDOW_SEC
    max_entries: int = DEFAULT_REPLAY_WINDOW_SIZE
    # key -> first-seen monotonic timestamp
    _seen: "OrderedDict[str, float]" = field(default_factory=OrderedDict)

    def __post_init__(self) -> None:
        self.window_sec = float(max(0.0, self.window_sec))
        self.max_entries = int(max(1, self.max_entries))

    def _purge(self, now: float) -> None:
        cutoff = now - self.window_sec
        while self._seen:
            key, ts = next(iter(self._seen.items()))
            if ts >= cutoff and len(self._seen) <= self.max_entries:
                break
            if ts < cutoff:
                self._seen.popitem(last=False)
                continue
            # Over capacity: drop oldest even if still inside time window.
            if len(self._seen) > self.max_entries:
                self._seen.popitem(last=False)
                continue
            break

    def observe(self, key: str, *, now: float | None = None) -> bool:
        """Record *key*. Return True if it is a replay (already seen)."""
        t = time.monotonic() if now is None else float(now)
        self._purge(t)
        if key in self._seen:
            prev = self._seen[key]
            if t - prev <= self.window_sec:
                # Refresh order to keep hot keys.
                self._seen.move_to_end(key)
                return True
        self._seen[key] = t
        self._seen.move_to_end(key)
        self._purge(t)
        return False

    def check_frame(self, frame: bytes, *, now: float | None = None) -> bool:
        """Return True if *frame* is a duplicate within the window."""
        return self.observe(f"frame:{frame_fingerprint(frame)}", now=now)

    def check_response_id(
        self,
        response_id: Union[str, int, None],
        *,
        peer_id: str = "",
        now: float | None = None,
    ) -> bool:
        """Return True if *response_id* is a duplicate within the window."""
        if response_id is None:
            return False
        return self.observe(f"rid:{response_id_key(response_id, peer_id=peer_id)}", now=now)

    def accept_frame(self, frame: bytes, *, now: float | None = None) -> None:
        """Accept *frame* or raise :class:`ReplayDetectedError` on duplicate."""
        if self.check_frame(frame, now=now):
            raise ReplayDetectedError("duplicate_frame")

    def accept_response_id(
        self,
        response_id: Union[str, int, None],
        *,
        peer_id: str = "",
        now: float | None = None,
    ) -> None:
        """Accept *response_id* or raise :class:`ReplayDetectedError` on duplicate."""
        if self.check_response_id(response_id, peer_id=peer_id, now=now):
            raise ReplayDetectedError(f"duplicate_response_id:{response_id!r}")

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self._seen

    def __len__(self) -> int:
        return len(self._seen)

    def snapshot(self) -> Dict[str, Any]:
        """Return window configuration and occupancy."""
        return {
            "window_sec": self.window_sec,
            "max_entries": self.max_entries,
            "size": len(self._seen),
        }


# ---------------------------------------------------------------------------
# Idle timeout
# ---------------------------------------------------------------------------


@dataclass
class IdleTimeoutTracker:
    """Track last activity and enforce idle stream timeout (§3.5)."""

    idle_timeout_sec: float = DEFAULT_IDLE_TIMEOUT_SEC
    last_activity: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.idle_timeout_sec = float(max(0.0, self.idle_timeout_sec))

    def touch(self, *, now: float | None = None) -> None:
        """Record activity (frame read/write)."""
        self.last_activity = time.monotonic() if now is None else float(now)

    def is_idle(self, *, now: float | None = None) -> bool:
        """Return True if idle timeout has elapsed since last activity."""
        t = time.monotonic() if now is None else float(now)
        return (t - self.last_activity) >= self.idle_timeout_sec

    def check(self, *, now: float | None = None) -> None:
        """Raise :class:`IdleTimeoutError` when the stream is idle too long."""
        if self.is_idle(now=now):
            raise IdleTimeoutError(
                f"idle_timeout:{self.idle_timeout_sec}s"
            )

    def snapshot(self) -> Dict[str, float]:
        """Return idle tracker state."""
        return {
            "idle_timeout_sec": self.idle_timeout_sec,
            "last_activity": self.last_activity,
        }


# ---------------------------------------------------------------------------
# Session bundle (convenience facade)
# ---------------------------------------------------------------------------


@dataclass
class P2PFramingSession:
    """Bundle framing, quotas, correlation, replay, and idle controls.

    Suitable for attaching to a single libp2p stream after protocol-id
    negotiation. Layer T only — does not interpret MCP method semantics.
    """

    peer_id: str = ""
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES
    framer: LengthPrefixedFrame = field(init=False)
    quota: TransportQuota = field(default_factory=TransportQuota)
    correlation: CorrelationTable = field(default_factory=CorrelationTable)
    replay: ReplayWindow = field(default_factory=ReplayWindow)
    idle: IdleTimeoutTracker = field(default_factory=IdleTimeoutTracker)
    stream_opened: bool = False

    def __post_init__(self) -> None:
        self.framer = LengthPrefixedFrame(max_frame_bytes=self.max_frame_bytes)
        self.quota.max_frame_bytes = self.max_frame_bytes

    def open(self) -> None:
        """Open the stream under peer quota."""
        self.quota.open_stream(self.peer_id)
        self.stream_opened = True
        self.idle.touch()

    def close(self) -> None:
        """Close the stream and release quota."""
        if self.stream_opened:
            self.quota.close_stream(self.peer_id)
            self.stream_opened = False

    def encode(self, payload: Mapping[str, Any]) -> bytes:
        """Encode *payload*, enforce size, update idle clock."""
        frame = self.framer.encode(payload)
        self.idle.touch()
        return frame

    def decode(self, frame: bytes, *, check_replay: bool = True) -> Dict[str, Any]:
        """Decode *frame*, enforce size/replay/rate, update idle clock."""
        self.idle.check()
        payload, _consumed = self.framer.decode(frame)
        if check_replay:
            self.replay.accept_frame(frame)
        if not self.quota.allow_message(self.peer_id, nbytes=len(frame)):
            raise QuotaExceededError("message_rate_or_bandwidth_exceeded")
        self.idle.touch()
        return payload

    def register_request(
        self,
        request_id: Union[str, int],
        *,
        method: str = "",
        now: float | None = None,
    ) -> CorrelatedRequest:
        """Register an outbound/inbound request under correlation + quota."""
        self.quota.begin_request(self.peer_id)
        try:
            return self.correlation.register(
                request_id, method=method, peer_id=self.peer_id, now=now
            )
        except Exception:
            self.quota.end_request(self.peer_id)
            raise

    def complete_response(
        self,
        response: Mapping[str, Any],
        *,
        now: float | None = None,
    ) -> CorrelatedRequest:
        """Correlate a response, reject id replay, release in-flight slot."""
        rid = response.get("id")
        self.replay.accept_response_id(rid, peer_id=self.peer_id, now=now)
        entry = self.correlation.match_response(response)
        self.quota.end_request(self.peer_id)
        return entry

    def cancel_request(self, request_id: Union[str, int]) -> CorrelatedRequest:
        """Cancel an in-flight request and release quota."""
        entry = self.correlation.cancel(request_id)
        self.quota.end_request(self.peer_id)
        return entry


__all__ = [
    # constants
    "PROTOCOL_ID_DEFAULT",
    "DEFAULT_MAX_FRAME_BYTES",
    "HEADER_SIZE",
    "DEFAULT_MAX_STREAMS_PER_PEER",
    "DEFAULT_MAX_IN_FLIGHT_PER_PEER",
    "DEFAULT_MAX_BANDWIDTH_BYTES_PER_SEC",
    "DEFAULT_RATE_CAPACITY",
    "DEFAULT_RATE_REFILL_PER_SEC",
    "DEFAULT_IDLE_TIMEOUT_SEC",
    "DEFAULT_REQUEST_TIMEOUT_SEC",
    "DEFAULT_REPLAY_WINDOW_SEC",
    "DEFAULT_REPLAY_WINDOW_SIZE",
    # errors
    "FramingError",
    "FrameSizeExceededError",
    "CorrelationError",
    "QuotaExceededError",
    "ReplayDetectedError",
    "IdleTimeoutError",
    # framing
    "encode_jsonrpc_frame",
    "decode_jsonrpc_frame",
    "LengthPrefixedFrame",
    # quotas / rate
    "TokenBucketLimiter",
    "PeerQuotaState",
    "TransportQuota",
    # correlation
    "RequestState",
    "CorrelatedRequest",
    "CorrelationTable",
    # replay
    "frame_fingerprint",
    "response_id_key",
    "ReplayWindow",
    # idle
    "IdleTimeoutTracker",
    # session
    "P2PFramingSession",
]
