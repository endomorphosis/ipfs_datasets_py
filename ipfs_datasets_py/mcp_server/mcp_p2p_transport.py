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
from typing import Any, Dict, List, NamedTuple, Optional, Union

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


class PublishAsyncResult(NamedTuple):
    """Result of a :meth:`PubSubBus.publish_async` call.

    Attributes:
        notified: Number of handlers that completed successfully.
        timed_out: Number of handlers that were cancelled due to timeout.
    """

    notified: int
    timed_out: int

    def __int__(self) -> int:
        """Return *notified* for backward-compatible int comparisons."""
        return self.notified

    def __eq__(self, other: object) -> bool:  # type: ignore[override]
        """Compare with int or another :class:`PublishAsyncResult`.

        ``result == 3`` compares against :attr:`notified`, so legacy callers
        that used ``publish_async() == N`` continue to work.
        """
        if isinstance(other, int):
            return self.notified == other
        if isinstance(other, tuple):
            return tuple.__eq__(self, other)
        return NotImplemented


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
        self._next_sid: int = 1
        self._sid_map: Dict[int, Any] = {}  # sid -> (topic_key, handler)

    def subscribe(self, topic: Union[str, "PubSubEventType"], handler: Any, *, priority: int = 0) -> int:
        """Register *handler* to receive messages on *topic*.

        Args:
            topic: A :class:`PubSubEventType` value or raw topic string.
            handler: Callable ``(topic: str, payload: dict) -> None``.
            priority: Numeric priority for this handler.  Higher values cause
                the handler to run before lower-priority handlers inside
                :meth:`publish_async`.  Stored as ``handler.__mcp_priority__``
                (only for this registration; existing attributes are not
                overwritten if higher).

        Returns:
            An integer subscription ID that can be passed to
            :meth:`unsubscribe_by_id` to remove this specific registration
            without needing a reference to the handler callable.
        """
        key = str(topic)
        self._subscribers.setdefault(key, [])
        if handler not in self._subscribers[key]:
            # Store priority as a handler attribute so publish_async can sort.
            # We only upgrade (never downgrade): if the handler has no priority
            # yet (None sentinel), set it; if it already has one, only raise it.
            existing = getattr(handler, "__mcp_priority__", None)
            if existing is None or priority > existing:
                try:
                    handler.__mcp_priority__ = priority
                except (AttributeError, TypeError):
                    pass  # built-ins or other non-writable callables
            self._subscribers[key].append(handler)
        sid = self._next_sid
        self._next_sid += 1
        self._sid_map[sid] = (key, handler)
        return sid

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

    def unsubscribe_by_id(self, sid: int) -> bool:
        """Remove the subscription identified by *sid*.

        *sid* is the integer returned by :meth:`subscribe`.  This allows
        targeted removal without retaining a reference to the handler callable.

        Args:
            sid: Subscription ID previously returned by :meth:`subscribe`.

        Returns:
            ``True`` if the subscription was found and removed; ``False`` if
            *sid* is unknown or the handler had already been removed.
        """
        entry = self._sid_map.pop(sid, None)
        if entry is None:
            return False
        key, handler = entry
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

    def subscription_count(self, topic: "Optional[Union[str, PubSubEventType]]" = None) -> int:
        """Return the total number of active subscriptions.

        Args:
            topic: When provided, count only subscriptions for that specific
                topic.  When ``None`` (default), count subscriptions across
                **all** topics.  Each unique handler object registered on a
                topic counts once per topic, not per :meth:`subscribe` call
                (duplicate-handler registrations are deduplicated at subscribe
                time).

        Returns:
            Total subscription count.
        """
        if topic is not None:
            return len(self._subscribers.get(str(topic), []))
        return sum(len(handlers) for handlers in self._subscribers.values())

    def topics(self) -> List[str]:
        """Return a sorted list of topic strings that have at least one subscriber.

        Returns:
            Sorted list of topic key strings.  Empty list when no subscriptions
            exist.
        """
        return sorted(k for k, v in self._subscribers.items() if v)

    def clear_topic(self, topic: Union[str, "PubSubEventType"]) -> int:
        """Remove all subscribers for *topic* in a single bulk operation.

        Removes every handler registered on the topic, cleans up their
        corresponding ``_sid_map`` entries, and returns the number of handlers
        removed.

        Args:
            topic: A :class:`PubSubEventType` value or raw topic string.

        Returns:
            Number of handlers removed.  ``0`` if the topic had no
            subscribers or did not exist.
        """
        key = str(topic)
        handlers = list(self._subscribers.pop(key, []))
        # Remove corresponding sid_map entries for these handlers
        stale_sids = [
            sid for sid, (k, h) in self._sid_map.items()
            if k == key and h in handlers
        ]
        for sid in stale_sids:
            self._sid_map.pop(sid, None)
        return len(handlers)

    def clear_all(self) -> int:
        """Remove every subscriber from every topic at once.

        Clears :attr:`_subscribers` and :attr:`_sid_map` completely.  Returns
        the total number of handlers removed across all topics.

        Useful for test teardown and graceful shutdown::

            removed = bus.clear_all()
            assert bus.subscription_count() == 0

        Returns:
            Total handlers removed.
        """
        total = sum(len(v) for v in self._subscribers.values())
        self._subscribers.clear()
        self._sid_map.clear()
        return total

    def snapshot(self) -> Dict[str, int]:
        """Return a snapshot of current subscriber counts per topic.

        Maps each active topic key to the number of handlers currently
        subscribed.  Topics with zero subscribers are excluded.  Useful for
        health-check endpoints and monitoring dashboards::

            counts = bus.snapshot()
            # {"receipt_disseminate": 2, "delegation_add": 1}

        Returns:
            Dict mapping topic key string → subscriber count (≥ 1).
        """
        return {k: len(v) for k, v in self._subscribers.items() if v}

    def handler_topics(self, handler: Any) -> List[str]:
        """Return the list of topic keys on which *handler* is registered.

        Useful for introspection and debugging — lets callers ask "which
        topics is this callback listening to?" without iterating manually::

            def my_cb(topic, payload): ...
            bus.subscribe("receipts", my_cb)
            bus.subscribe("audit", my_cb)
            assert bus.handler_topics(my_cb) == ["audit", "receipts"]

        Args:
            handler: The callable originally passed to :meth:`subscribe`.

        Returns:
            Sorted list of topic key strings.  Empty list if *handler* is not
            subscribed to any topic.
        """
        return sorted(
            k for k, handlers in self._subscribers.items()
            if handler in handlers
        )

    def handler_count(self) -> int:
        """Return the number of *unique* handlers across all topics.

        A handler subscribed to multiple topics is counted only once::

            def cb(t, p): pass
            bus.subscribe("a", cb)
            bus.subscribe("b", cb)
            assert bus.handler_count() == 1  # cb appears twice but is 1 unique

        Returns:
            Non-negative integer — 0 when no handlers are registered.
        """
        seen: set = set()
        for handlers in self._subscribers.values():
            for h in handlers:
                seen.add(id(h))
        return len(seen)

    def topic_handler_map(self) -> Dict[str, List]:
        """Return a shallow-copy snapshot of the subscriber registry.

        Each key is a topic string; the value is a *copy* of the list of
        handlers currently subscribed to that topic.  Modifying the returned
        dict or its lists does not affect the live registry::

            m = bus.topic_handler_map()
            m["receipts"].clear()          # does NOT unsubscribe handlers
            assert bus.subscription_count("receipts") > 0  # still registered

        Only topics with at least one handler are included.

        Returns:
            ``Dict[str, List]`` — ``{topic: [handler, ...]}`` (shallow copy).
        """
        return {k: list(v) for k, v in self._subscribers.items() if v}

    def resubscribe(
        self,
        old_handler: Any,
        new_handler: Any,
        topic: Optional[Union[str, "PubSubEventType"]] = None,
    ) -> int:
        """Replace a registered handler without disrupting subscription order.

        Scans ``_subscribers`` for *old_handler* and replaces each occurrence
        with *new_handler* in-place.  When ``topic`` is specified only that
        topic is scanned; when ``topic=None`` all topics are scanned.

        The ``__mcp_priority__`` attribute of *old_handler* is **not** copied
        to *new_handler* — callers should set it on *new_handler* before
        calling this method if priority must be preserved.

        ``_sid_map`` is updated: any SID previously mapped to *old_handler* is
        remapped to *new_handler*.

        Args:
            old_handler: The handler currently registered.
            new_handler: The replacement handler.
            topic: If given, only replace within that topic's handler list.
                   If ``None``, replace across all topics.

        Returns:
            Number of replacements made (0 if *old_handler* was not found).
        """
        replaced = 0
        keys: List[str]
        if topic is not None:
            key = topic.value if hasattr(topic, "value") else str(topic)
            keys = [key]
        else:
            keys = list(self._subscribers.keys())

        for key in keys:
            handlers = self._subscribers.get(key, [])
            for i, h in enumerate(handlers):
                if h is old_handler:
                    handlers[i] = new_handler
                    replaced += 1

        # Update sid_map
        for sid, (k, h) in list(self._sid_map.items()):
            if h is old_handler:
                self._sid_map[sid] = (k, new_handler)

        return replaced

    def subscriber_ids(self, topic: Union[str, "PubSubEventType"]) -> List[int]:
        """Return a sorted list of subscription IDs (SIDs) for *topic*.

        Queries ``_sid_map`` for every SID registered against the given topic
        key, enabling targeted :meth:`unsubscribe_by_id` calls::

            sids = bus.subscriber_ids("receipts")
            for sid in sids:
                bus.unsubscribe_by_id(sid)

        Args:
            topic: Topic string or :class:`PubSubEventType` enum member.

        Returns:
            Sorted list of integer SIDs subscribed to *topic*.  Empty list
            when no subscriptions exist for that topic.
        """
        key = topic.value if hasattr(topic, "value") else str(topic)
        return sorted(
            sid for sid, (k, _h) in self._sid_map.items() if k == key
        )

    def topic_sid_map(self) -> Dict[str, List[int]]:
        """Return a mapping of topic key → sorted list of SIDs.

        The SID-based analogue of :meth:`topic_handler_map`.  Useful for
        auditing which subscriptions are active per topic without exposing
        handler callables directly::

            m = bus.topic_sid_map()
            # {"receipts": [1, 3], "audit": [2]}

        Only topics with at least one subscriber are included.

        Returns:
            ``Dict[str, List[int]]`` — ``{topic_key: sorted_sid_list}``.
        """
        result: Dict[str, List[int]] = {}
        for sid, (k, _h) in self._sid_map.items():
            result.setdefault(k, [])
            result[k].append(sid)
        # Sort each SID list and drop empty topics
        return {k: sorted(v) for k, v in result.items() if v}

    def total_subscriptions(self) -> int:
        """Return the total number of active subscription registrations.

        Unlike :meth:`handler_count` (which counts *unique* handlers),
        this method counts every SID in ``_sid_map`` — so a single handler
        subscribed to three topics contributes 3::

            def cb(t, p): pass
            bus.subscribe("a", cb)
            bus.subscribe("b", cb)
            assert bus.total_subscriptions() == 2  # two SIDs
            assert bus.handler_count() == 1         # one unique handler

        Returns:
            Non-negative integer — ``len(_sid_map)``.
        """
        return len(self._sid_map)

    async def publish_async(
        self,
        topic: Union[str, "PubSubEventType"],
        payload: Dict[str, Any],
        *,
        timeout_seconds: float = 5.0,
        priority: int = 0,
    ) -> "PublishAsyncResult":
        """Async variant of :meth:`publish`.

        Invokes each handler concurrently inside an *anyio* task group so
        async handlers can ``await`` without blocking others.  Falls back to
        synchronous :meth:`publish` (with a ``UserWarning``) when *anyio* is
        not installed.

        Each handler is cancelled after *timeout_seconds* via
        ``anyio.move_on_after()`` if it does not complete in time.

        Handlers are sorted by their ``__mcp_priority__`` attribute (descending)
        before the task group is started; handlers without the attribute are
        treated as priority 0.  Within the same priority bucket, subscription
        order is preserved.

        Args:
            topic: A :class:`PubSubEventType` value or raw topic string.
            payload: JSON-serialisable event payload.
            timeout_seconds: Maximum seconds to wait for each handler.
                Defaults to ``5.0``.  Set to ``0`` to use no timeout.
            priority: Unused by the current implementation — reserved for
                future use.  Handlers are sorted by their own
                ``__mcp_priority__`` attribute (higher values = higher
                priority); this parameter does **not** filter which handlers
                are called.  Defaults to ``0``.

        Returns:
            A :class:`PublishAsyncResult` namedtuple with ``notified`` (count
            of handlers that completed) and ``timed_out`` (count of handlers
            cancelled by timeout).
        """
        try:
            import anyio  # noqa: PLC0415
        except ImportError:
            import warnings  # noqa: PLC0415

            warnings.warn(
                "anyio is not installed; publish_async() falling back to synchronous publish()",
                UserWarning,
                stacklevel=2,
            )
            n = self.publish(topic, payload)
            return PublishAsyncResult(notified=n, timed_out=0)

        key = str(topic)
        all_handlers = list(self._subscribers.get(key, []))
        # Sort by handler priority: handlers with __mcp_priority__ >= priority
        # are moved to the front.  Stable sort preserves insertion order within
        # each bucket.
        def _handler_priority(h: Any) -> int:
            return getattr(h, "__mcp_priority__", 0)

        handlers = sorted(all_handlers, key=_handler_priority, reverse=True)
        # Track per-handler outcome: True=notified, False=error/timeout
        results: Dict[int, bool] = {}
        timed_out_flags: Dict[int, bool] = {}

        async def _call(idx: int, h: Any) -> None:
            results[idx] = False  # default covers timeout (move_on_after exits silently)
            timed_out_flags[idx] = False
            try:
                if timeout_seconds > 0:
                    with anyio.move_on_after(timeout_seconds) as cancel_scope:
                        result = h(key, payload)
                        # Support both sync and async handlers.
                        if hasattr(result, "__await__"):
                            await result
                        results[idx] = True
                    if cancel_scope.cancelled_caught:
                        timed_out_flags[idx] = True
                else:
                    result = h(key, payload)
                    if hasattr(result, "__await__"):
                        await result
                    results[idx] = True
            except Exception as exc:  # pragma: no cover
                logger.debug("publish_async handler %d raised: %s", idx, exc)
                # results[idx] stays False (set as default above)

        async with anyio.create_task_group() as tg:
            for i, handler in enumerate(handlers):
                tg.start_soon(_call, i, handler)

        notified = sum(1 for v in results.values() if v)
        timed_out = sum(1 for v in timed_out_flags.values() if v)
        return PublishAsyncResult(notified=notified, timed_out=timed_out)

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
