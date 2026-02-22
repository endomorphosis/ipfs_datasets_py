"""Profile E: ``mcp+p2p`` Transport Binding (libp2p).

This module implements the constants and helpers defined in the MCP++
``docs/spec/transport-mcp-p2p.md`` spec chapter.

The binding is intentionally **carriage-only**: it defines how to move MCP
JSON-RPC messages between peers without changing MCP method semantics or tool
definitions.

Key constants
-------------
``MCP_P2P_PROTOCOL_ID``
    Canonical libp2p stream protocol identifier for MCP session streams.
``MCP_P2P_PUBSUB_TOPICS``
    Standard pubsub topic names for event dissemination (receipts, interfaces).
``DEFAULT_MAX_FRAME_BYTES``
    Maximum allowed frame size (default 16 MiB, configurable per deployment).

Key helpers
-----------
``LengthPrefixFramer``
    Encodes and decodes MCP JSON-RPC messages using a u32 big-endian length
    prefix as recommended by the spec.
``P2PSessionConfig``
    Dataclass holding per-session configuration.
``MCPMessage``
    Lightweight wrapper around a raw JSON-RPC dict for type-safety.
``P2PSessionState``
    Enum representing the lifecycle of a ``mcp+p2p`` session.

References
----------
- https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/spec/transport-mcp-p2p.md
"""

from __future__ import annotations

import json
import logging
import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normative constants
# ---------------------------------------------------------------------------

#: Canonical libp2p protocol ID for MCP session streams.
#: (Section 3.1.1 of transport-mcp-p2p.md — normative; the '+' is required
#: by the spec and is standard in libp2p protocol ID strings.)
MCP_P2P_PROTOCOL_ID: str = "/mcp+p2p/1.0.0"

#: Optional sub-protocol IDs (non-normative).
MCP_P2P_SESSION_PROTOCOL_ID: str = "/mcp+p2p/session/1.0.0"
MCP_P2P_EVENTS_PROTOCOL_ID: str = "/mcp+p2p/events/1.0.0"

#: Maximum frame size in bytes (recommended default 16 MiB).
#: Receivers SHOULD reject frames larger than this.
DEFAULT_MAX_FRAME_BYTES: int = 16 * 1024 * 1024  # 16 MiB

#: Minimum max-frame-size (1 MiB) to prevent trivially small limits.
MIN_MAX_FRAME_BYTES: int = 1024 * 1024  # 1 MiB

# ---------------------------------------------------------------------------
# Pubsub topic names (non-normative)
# ---------------------------------------------------------------------------

MCP_P2P_PUBSUB_TOPICS: dict[str, str] = {
    "interface_announce": "/mcp+p2p/topics/interface_cid/1.0.0",
    "receipt_disseminate": "/mcp+p2p/topics/receipt_cid/1.0.0",
    "decision_disseminate": "/mcp+p2p/topics/decision_cid/1.0.0",
    "scheduling_signal": "/mcp+p2p/topics/scheduling/1.0.0",
}

# ---------------------------------------------------------------------------
# Session lifecycle states
# ---------------------------------------------------------------------------


class P2PSessionState(Enum):
    """Lifecycle states for a ``mcp+p2p`` session.

    Corresponds to the session lifecycle in Section 3.2 of the spec.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"


# ---------------------------------------------------------------------------
# Message wrapper
# ---------------------------------------------------------------------------


@dataclass
class MCPMessage:
    """Lightweight wrapper around a single MCP JSON-RPC message.

    Parameters
    ----------
    payload:
        The raw JSON-RPC dict (``{"jsonrpc": "2.0", "method": ..., ...}``).
    message_id:
        Optional application-level ID for correlation tracking.

    Notes
    -----
    This class does *not* validate JSON-RPC semantics — it is purely a
    container for use by the framer and transport layer.
    """

    payload: dict[str, Any]
    message_id: int | str | None = None

    def to_bytes(self) -> bytes:
        """Serialize payload to UTF-8 JSON bytes."""
        return json.dumps(self.payload, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes, message_id: int | str | None = None) -> "MCPMessage":
        """Deserialize from UTF-8 JSON bytes.

        Parameters
        ----------
        data:
            Raw UTF-8 JSON bytes.
        message_id:
            Optional ID to attach.

        Raises
        ------
        ValueError
            If *data* is not valid UTF-8 or not valid JSON.
        """
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"MCPMessage.from_bytes: invalid UTF-8: {exc}") from exc
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"MCPMessage.from_bytes: invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(
                f"MCPMessage.from_bytes: expected JSON object, got {type(payload).__name__}"
            )
        return cls(payload=payload, message_id=message_id)

    def is_request(self) -> bool:
        """Return True if this message looks like a JSON-RPC request."""
        return "method" in self.payload and "id" in self.payload

    def is_notification(self) -> bool:
        """Return True if this message looks like a JSON-RPC notification (no id)."""
        return "method" in self.payload and "id" not in self.payload

    def is_response(self) -> bool:
        """Return True if this message looks like a JSON-RPC response."""
        return "id" in self.payload and ("result" in self.payload or "error" in self.payload)


# ---------------------------------------------------------------------------
# Length-prefix framer
# ---------------------------------------------------------------------------


class FrameTooBigError(Exception):
    """Raised when a frame exceeds the configured maximum size."""


class LengthPrefixFramer:
    """Encodes and decodes MCP JSON-RPC messages with a u32 big-endian length prefix.

    This implements the framing strategy recommended in Section 5.1 of
    ``transport-mcp-p2p.md``.

    Wire format::

        +------------------+---------------------------+
        | length (4 bytes) |  JSON-RPC payload (N bytes)|
        |  u32 big-endian  |  UTF-8 encoded JSON text   |
        +------------------+---------------------------+

    Parameters
    ----------
    max_frame_bytes:
        Maximum allowed frame body size in bytes.  Frames larger than this
        will raise :class:`FrameTooBigError` on both encode and decode.
    """

    #: Struct format for the 4-byte unsigned big-endian length prefix.
    _HEADER_FORMAT: str = "!I"  # network byte order (big-endian) unsigned int
    #: Number of bytes in the length prefix.
    HEADER_SIZE: int = 4

    def __init__(self, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> None:
        if max_frame_bytes < MIN_MAX_FRAME_BYTES:
            raise ValueError(
                f"max_frame_bytes must be >= {MIN_MAX_FRAME_BYTES}, got {max_frame_bytes}"
            )
        self.max_frame_bytes = max_frame_bytes

    def encode(self, message: MCPMessage) -> bytes:
        """Encode a :class:`MCPMessage` into a length-prefixed byte frame.

        Parameters
        ----------
        message:
            The message to encode.

        Returns
        -------
        bytes
            ``<4-byte length><JSON body>``.

        Raises
        ------
        FrameTooBigError
            If the encoded JSON body exceeds *max_frame_bytes*.
        """
        body = message.to_bytes()
        if len(body) > self.max_frame_bytes:
            raise FrameTooBigError(
                f"Encoded message is {len(body)} bytes, "
                f"exceeds max_frame_bytes={self.max_frame_bytes}"
            )
        header = struct.pack(self._HEADER_FORMAT, len(body))
        return header + body

    def decode_header(self, header_bytes: bytes) -> int:
        """Decode the 4-byte length prefix from a raw byte buffer.

        Parameters
        ----------
        header_bytes:
            Exactly 4 bytes containing the u32 big-endian length.

        Returns
        -------
        int
            The declared body length.

        Raises
        ------
        ValueError
            If *header_bytes* is not exactly 4 bytes.
        FrameTooBigError
            If the declared length exceeds *max_frame_bytes*.
        """
        if len(header_bytes) != self.HEADER_SIZE:
            raise ValueError(
                f"decode_header expects {self.HEADER_SIZE} bytes, got {len(header_bytes)}"
            )
        (length,) = struct.unpack(self._HEADER_FORMAT, header_bytes)
        if length > self.max_frame_bytes:
            raise FrameTooBigError(
                f"Declared frame size {length} bytes exceeds "
                f"max_frame_bytes={self.max_frame_bytes}"
            )
        return length

    def decode_body(self, body_bytes: bytes, message_id: int | str | None = None) -> MCPMessage:
        """Decode a raw body byte buffer into a :class:`MCPMessage`.

        Parameters
        ----------
        body_bytes:
            The raw body (without the 4-byte length prefix).
        message_id:
            Optional correlation ID.

        Returns
        -------
        MCPMessage

        Raises
        ------
        ValueError
            If the bytes are not valid UTF-8 JSON.
        """
        return MCPMessage.from_bytes(body_bytes, message_id=message_id)

    def decode(self, frame_bytes: bytes, message_id: int | str | None = None) -> MCPMessage:
        """Decode a complete length-prefixed frame.

        Parameters
        ----------
        frame_bytes:
            The full frame: ``<4-byte header><body>``.
        message_id:
            Optional correlation ID.

        Returns
        -------
        MCPMessage

        Raises
        ------
        ValueError
            If the frame is too short or the body is invalid JSON.
        FrameTooBigError
            If the declared or actual body size exceeds *max_frame_bytes*.
        """
        if len(frame_bytes) < self.HEADER_SIZE:
            raise ValueError(
                f"Frame too short: {len(frame_bytes)} bytes, need at least {self.HEADER_SIZE}"
            )
        declared_len = self.decode_header(frame_bytes[: self.HEADER_SIZE])
        body = frame_bytes[self.HEADER_SIZE :]
        if len(body) != declared_len:
            raise ValueError(
                f"Frame body length mismatch: declared {declared_len}, got {len(body)}"
            )
        return self.decode_body(body, message_id=message_id)


# ---------------------------------------------------------------------------
# Session config
# ---------------------------------------------------------------------------


@dataclass
class P2PSessionConfig:
    """Configuration for a single ``mcp+p2p`` session.

    Parameters
    ----------
    protocol_id:
        libp2p stream protocol ID to negotiate.
    max_frame_bytes:
        Maximum frame size for this session.
    peer_id:
        Optional remote PeerID string (for logging/tracing).
    multiaddrs:
        Optional list of multiaddrs for the remote peer.
    enable_pubsub:
        Whether event dissemination over pubsub is enabled.
    pubsub_topics:
        Pubsub topics to subscribe/publish to.
    """

    protocol_id: str = MCP_P2P_PROTOCOL_ID
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES
    peer_id: str | None = None
    multiaddrs: list[str] = field(default_factory=list)
    enable_pubsub: bool = False
    pubsub_topics: list[str] = field(default_factory=list)

    def make_framer(self) -> LengthPrefixFramer:
        """Create a :class:`LengthPrefixFramer` configured for this session."""
        return LengthPrefixFramer(max_frame_bytes=self.max_frame_bytes)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "protocol_id": self.protocol_id,
            "max_frame_bytes": self.max_frame_bytes,
            "peer_id": self.peer_id,
            "multiaddrs": list(self.multiaddrs),
            "enable_pubsub": self.enable_pubsub,
            "pubsub_topics": list(self.pubsub_topics),
        }


# ---------------------------------------------------------------------------
# Rate limiting token-bucket stub
# ---------------------------------------------------------------------------


class TokenBucketRateLimiter:
    """Simple token-bucket rate limiter for per-peer message rate limiting.

    This implements the *concept* described in Section 7 of the spec
    ("Peers SHOULD rate-limit and validate incoming messages").  It is
    intentionally minimal — production deployments SHOULD use a more robust
    implementation tied to actual clock sources.

    Parameters
    ----------
    capacity:
        Maximum number of tokens (burst limit).
    refill_rate:
        Tokens added per ``consume()`` call (represents refill logic).
        In a real implementation this would be tokens-per-second.
    """

    def __init__(self, capacity: int = 100, refill_rate: int = 10) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be > 0, got {capacity}")
        if refill_rate < 0:
            raise ValueError(f"refill_rate must be >= 0, got {refill_rate}")
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens: int = capacity

    @property
    def tokens(self) -> int:
        """Current token count."""
        return self._tokens

    def consume(self, count: int = 1) -> bool:
        """Attempt to consume *count* tokens.

        Refills by ``refill_rate`` tokens (up to ``capacity``) before
        consuming, simulating a time-based refill.

        Returns
        -------
        bool
            True if the tokens were consumed successfully; False if there
            were not enough tokens.
        """
        if count <= 0:
            raise ValueError(f"count must be > 0, got {count}")
        # Simulate refill
        self._tokens = min(self.capacity, self._tokens + self.refill_rate)
        if self._tokens >= count:
            self._tokens -= count
            return True
        return False

    def reset(self) -> None:
        """Reset token count to full capacity."""
        self._tokens = self.capacity


# ---------------------------------------------------------------------------
# PubSub integration
# ---------------------------------------------------------------------------


class PubSubEventType(str, Enum):
    """Event types published over the MCP++ pubsub transport.

    These map directly to the topic names in :data:`MCP_P2P_PUBSUB_TOPICS`
    and represent the canonical event categories defined in Section 6 of the
    MCP++ transport spec.

    Values match the corresponding topic strings so they can be used
    interchangeably with raw string topic names.
    """

    INTERFACE_ANNOUNCE = MCP_P2P_PUBSUB_TOPICS["interface_announce"]
    RECEIPT_DISSEMINATE = MCP_P2P_PUBSUB_TOPICS["receipt_disseminate"]
    DECISION_DISSEMINATE = MCP_P2P_PUBSUB_TOPICS["decision_disseminate"]
    SCHEDULING_SIGNAL = MCP_P2P_PUBSUB_TOPICS["scheduling_signal"]


class PubSubBus:
    """Lightweight in-process pubsub bus for MCP++ transport events.

    This class provides ``publish`` / ``subscribe`` / ``unsubscribe`` hooks
    that mirror the libp2p GossipSub API shape described in the MCP++ spec
    Section 6 ("Event Dissemination via PubSub").

    In production the bus should be replaced with a real GossipSub bridge;
    this implementation is intended for testing, local development, and
    in-process peer notification.

    Usage
    -----
    ::

        bus = PubSubBus()
        received = []

        def on_event(topic, payload):
            received.append((topic, payload))

        bus.subscribe(PubSubEventType.TOOL_INVOKED, on_event)
        bus.publish(PubSubEventType.TOOL_INVOKED, {"tool": "ipfs_add"})
        assert len(received) == 1
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Any]] = {}

    def subscribe(self, topic: Union[str, "PubSubEventType"], handler: Any) -> None:
        """Register *handler* to receive messages on *topic*.

        Args:
            topic: A :class:`PubSubEventType` value or raw topic string.
            handler: Callable ``(topic: str, payload: dict) -> None``.
        """
        key = str(topic)
        self._subscribers.setdefault(key, [])
        if handler not in self._subscribers[key]:
            self._subscribers[key].append(handler)

    def unsubscribe(self, topic: Union[str, "PubSubEventType"], handler: Any) -> bool:
        """Remove *handler* from *topic*.

        Returns:
            ``True`` if the handler was found and removed; ``False`` otherwise.
        """
        key = str(topic)
        subs = self._subscribers.get(key, [])
        if handler in subs:
            subs.remove(handler)
            return True
        return False

    def publish(self, topic: Union[str, "PubSubEventType"], payload: Dict[str, Any]) -> int:
        """Broadcast *payload* to all subscribers of *topic*.

        Args:
            topic: A :class:`PubSubEventType` value or raw topic string.
            payload: JSON-serialisable event payload.

        Returns:
            The number of handlers notified.
        """
        key = str(topic)
        count = 0
        for handler in list(self._subscribers.get(key, [])):
            try:
                handler(key, payload)
                count += 1
            except Exception:  # pragma: no cover
                pass
        return count

    def topic_count(self, topic: Union[str, "PubSubEventType"]) -> int:
        """Return the number of subscribers for *topic*."""
        return len(self._subscribers.get(str(topic), []))

    def clear(self, topic: Optional[Union[str, "PubSubEventType"]] = None) -> None:
        """Clear all subscribers, optionally for a single *topic*."""
        if topic is None:
            self._subscribers.clear()
        else:
            self._subscribers.pop(str(topic), None)

    def __repr__(self) -> str:  # pragma: no cover
        topics = list(self._subscribers)
        return f"PubSubBus(topics={topics!r})"


# ---------------------------------------------------------------------------
# PubSubBus ↔ P2PServiceManager bridge (session 56)
# ---------------------------------------------------------------------------

class PubSubBridge:
    """Bridge between :class:`PubSubBus` and a :class:`P2PServiceManager`.

    When the P2P service starts it can call :meth:`connect` to wire the
    in-process :class:`PubSubBus` to the real libp2p announcement hooks.
    Published events are forwarded to the service manager's
    :meth:`~P2PServiceManager.announce_capability` method (if present).

    This class is intentionally agnostic about the concrete type of
    *service_manager* so it works with stubs and mocks in tests.

    Args:
        bus: The :class:`PubSubBus` to bridge.  Defaults to the module-level
            ``_GLOBAL_BUS`` singleton.
    """

    def __init__(self, bus: Optional["PubSubBus"] = None) -> None:
        self._bus = bus
        self._service_manager: Any = None
        self._connected = False

    # ------------------------------------------------------------------

    def connect(self, service_manager: Any) -> None:
        """Wire the bus to *service_manager*.

        Registers a handler on every canonical topic that forwards each
        published event to ``service_manager.announce_capability(topic,
        payload)`` (if the method exists) and logs the rest.

        Args:
            service_manager: A :class:`~p2p_service_manager.P2PServiceManager`
                instance (or any object with an optional
                ``announce_capability`` method).
        """
        if self._connected:
            logger.warning("PubSubBridge already connected; ignoring duplicate connect()")
            return
        self._service_manager = service_manager
        bus = self._bus or _get_global_bus()

        for event_type in PubSubEventType:
            topic = event_type.value
            # Each handler receives (topic_key, payload) from PubSubBus.publish().
            def _make_handler() -> Any:
                def _handler(topic_key: str, payload: Any) -> None:
                    if hasattr(service_manager, "announce_capability"):
                        try:
                            service_manager.announce_capability(topic_key, payload)
                        except Exception as exc:  # pragma: no cover
                            logger.warning("announce_capability(%s) failed: %s", topic_key, exc)
                    else:
                        logger.debug("PubSubBridge forwarding %s: %s", topic_key, payload)
                return _handler
            bus.subscribe(topic, _make_handler())

        self._connected = True
        logger.info("PubSubBridge connected to P2PServiceManager")

    def disconnect(self) -> None:
        """Remove all bridge handlers and detach from the service manager."""
        if not self._connected:
            return
        bus = self._bus or _get_global_bus()
        for event_type in PubSubEventType:
            bus.clear(event_type.value)
        self._service_manager = None
        self._connected = False
        logger.info("PubSubBridge disconnected")

    @property
    def is_connected(self) -> bool:
        """``True`` while the bridge is wired to a service manager."""
        return self._connected


# Module-level global bus singleton (lazy-init)
_GLOBAL_BUS: Optional["PubSubBus"] = None


def _get_global_bus() -> "PubSubBus":
    """Return (or create) the module-level :class:`PubSubBus` singleton."""
    global _GLOBAL_BUS
    if _GLOBAL_BUS is None:
        _GLOBAL_BUS = PubSubBus()
    return _GLOBAL_BUS


def get_global_bus() -> "PubSubBus":
    """Public accessor for the module-level :class:`PubSubBus` singleton."""
    return _get_global_bus()
