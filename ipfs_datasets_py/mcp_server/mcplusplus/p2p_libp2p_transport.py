"""RuntimeP2pAdapter@1 — datasets P2P runtime bound to hardened Profile E.

Binds the datasets MCP++ P2P path to the shared framing rules from
:mod:`p2p_framing` (LengthPrefixedFrame@1, TransportQuota@1, correlation,
replay) and the versioned stream protocol id ``/mcp+p2p/1.0.0``.

Disposition of prior untracked work
-----------------------------------
The existing module ``ipfs_datasets_py.mcp_server.p2p_libp2p_transport``
(node lifecycle, JSON-RPC dispatch, optional libp2p host) is **integrated,
not discarded**: symbols are re-exported when importable, and
:data:`LEGACY_TRANSPORT_DISPOSITION` records the integration status for
audit. Hardened wire handling lives in this module so layer-T framing is
shared with kit and the MCPP-063/064 framing suite.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Set,
    Tuple,
)

from .p2p_framing import (
    PROTOCOL_ID_DEFAULT,
    DEFAULT_MAX_FRAME_BYTES,
    DEFAULT_MAX_STREAMS_PER_PEER,
    CorrelationError,
    CorrelationTable,
    FramingError,
    FrameSizeExceededError,
    LengthPrefixedFrame,
    P2PFramingSession,
    QuotaExceededError,
    ReplayDetectedError,
    ReplayWindow,
    TransportQuota,
    decode_jsonrpc_frame,
    encode_jsonrpc_frame,
)

# ---------------------------------------------------------------------------
# Interface / constants (RuntimeP2pAdapter@1)
# ---------------------------------------------------------------------------

INTERFACE_LABEL = "RuntimeP2pAdapter@1"
RUNTIME_ID = "datasets"

PROTOCOL_ID = PROTOCOL_ID_DEFAULT  # /mcp+p2p/1.0.0
SUPPORTED_PROTOCOL_IDS: frozenset[str] = frozenset({PROTOCOL_ID})

# Accepted MCP application binding versions (layer M metadata only).
CANONICAL_MCP_VERSION = "2026-07-28"
LEGACY_MCP_VERSION = "2024-11-05"
ACCEPTED_MCP_VERSIONS: frozenset[str] = frozenset(
    {CANONICAL_MCP_VERSION, LEGACY_MCP_VERSION}
)

MAX_FRAME_BYTES = DEFAULT_MAX_FRAME_BYTES
MAX_STREAMS_PER_PEER = DEFAULT_MAX_STREAMS_PER_PEER

# Known MCP / MCP++ methods for fail-closed unknown-method checks at the
# runtime adapter boundary (layer M admission, not transport success).
KNOWN_MCP_METHODS: frozenset[str] = frozenset(
    {
        "initialize",
        "notifications/initialized",
        "ping",
        "tools/list",
        "tools/call",
        "resources/list",
        "resources/read",
        "prompts/list",
        "prompts/get",
        "mcp++/artifacts/get",
        "mcp++/policy/evaluate",
        "mcp++/zk/ceremony/validate",
    }
)

# ---------------------------------------------------------------------------
# Legacy transport disposition (do not discard untracked work)
# ---------------------------------------------------------------------------

LEGACY_TRANSPORT_MODULE = "ipfs_datasets_py.mcp_server.p2p_libp2p_transport"
LEGACY_TRANSPORT_PATH = "ipfs_datasets_py/mcp_server/p2p_libp2p_transport.py"

_legacy_exports: Dict[str, Any] = {}
_legacy_error: Optional[str] = None

try:
    from ipfs_datasets_py.mcp_server import p2p_libp2p_transport as _legacy_p2p

    for _name in (
        "MCP_P2P_PROTOCOL",
        "MAX_P2P_MESSAGE_SIZE",
        "MCPp2pNode",
        "PeerInfo",
        "P2PMessage",
        "dispatch_profile_e_jsonrpc_request",
        "get_p2p_node",
        "ensure_libp2p_installed",
        "ensure_libp2p_installed_async",
    ):
        if hasattr(_legacy_p2p, _name):
            _legacy_exports[_name] = getattr(_legacy_p2p, _name)
    LEGACY_TRANSPORT_AVAILABLE = True
except Exception as _exc:  # pragma: no cover - optional during partial installs
    _legacy_p2p = None  # type: ignore[assignment]
    _legacy_error = f"{type(_exc).__name__}: {_exc}"
    LEGACY_TRANSPORT_AVAILABLE = False


LEGACY_TRANSPORT_DISPOSITION: Dict[str, Any] = {
    "module": LEGACY_TRANSPORT_MODULE,
    "path": LEGACY_TRANSPORT_PATH,
    "status": "integrated" if LEGACY_TRANSPORT_AVAILABLE else "recorded_unavailable",
    "action": "re_export_and_harden",
    "discarded": False,
    "exports": sorted(_legacy_exports.keys()),
    "error": _legacy_error,
    "note": (
        "Prior datasets Profile E node/dispatcher is integrated under "
        "RuntimeP2pAdapter@1; wire framing uses mcplusplus.p2p_framing."
    ),
}


def legacy_transport_disposition() -> Dict[str, Any]:
    """Return the audit record for the pre-existing datasets P2P transport."""
    return dict(LEGACY_TRANSPORT_DISPOSITION)


# Re-export legacy symbols at module level when present (disposition, not delete).
MCP_P2P_PROTOCOL = _legacy_exports.get("MCP_P2P_PROTOCOL", PROTOCOL_ID)
MAX_P2P_MESSAGE_SIZE = int(
    _legacy_exports.get("MAX_P2P_MESSAGE_SIZE", MAX_FRAME_BYTES)
)
MCPp2pNode = _legacy_exports.get("MCPp2pNode")
PeerInfo = _legacy_exports.get("PeerInfo")
P2PMessage = _legacy_exports.get("P2PMessage")
dispatch_profile_e_jsonrpc_request = _legacy_exports.get(
    "dispatch_profile_e_jsonrpc_request"
)
get_p2p_node = _legacy_exports.get("get_p2p_node")
ensure_libp2p_installed = _legacy_exports.get("ensure_libp2p_installed")
ensure_libp2p_installed_async = _legacy_exports.get("ensure_libp2p_installed_async")


# ---------------------------------------------------------------------------
# Admission helpers (layer T / A fail-closed)
# ---------------------------------------------------------------------------


def is_supported_protocol_id(protocol_id: Optional[str]) -> bool:
    """Return True when *protocol_id* is a negotiated Profile E stream id."""
    if protocol_id is None:
        return False
    return str(protocol_id) in SUPPORTED_PROTOCOL_IDS


def is_forged_protocol_version(
    protocol_id: Optional[str] = None,
    *,
    mcp_version: Optional[str] = None,
    accepted_protocol_ids: Optional[Set[str]] = None,
    accepted_mcp_versions: Optional[Set[str]] = None,
) -> bool:
    """Detect forged / unsupported transport or MCP versions."""
    accepted_pids = accepted_protocol_ids or set(SUPPORTED_PROTOCOL_IDS)
    accepted_mcp = accepted_mcp_versions or set(ACCEPTED_MCP_VERSIONS)
    if protocol_id is not None and str(protocol_id) not in accepted_pids:
        return True
    if mcp_version is not None and str(mcp_version) not in accepted_mcp:
        return True
    return False


def is_request_before_negotiation(
    *,
    stream_ready: bool,
    protocol_negotiated: bool,
    is_application_request: bool,
) -> bool:
    """Application request before layer-T stream negotiation is ready."""
    if not is_application_request:
        return False
    return not (stream_ready and protocol_negotiated)


def is_unknown_method(method: str) -> bool:
    """Return True when *method* is not a known MCP/MCP++ method."""
    return str(method or "") not in KNOWN_MCP_METHODS


def is_valid_peerid_invalid_ucan(
    *,
    peer_id: Optional[str],
    ucan_valid: bool,
    ucan_present: bool,
) -> bool:
    """PeerID authenticates the network endpoint, not execution authority."""
    if not peer_id:
        return False
    if not ucan_present:
        return True
    return not ucan_valid


def is_stale_fence(fencing_token: int, *, current_fence: int) -> bool:
    """Stale fencing tokens must not complete work."""
    return int(fencing_token) < int(current_fence)


def treat_empty_success_as_failure(
    body: Mapping[str, Any],
    *,
    status: Optional[int] = None,
    transport_error: Optional[str] = None,
    stream_closed: bool = False,
    framing_error: bool = False,
) -> bool:
    """Return True when a success-shaped body must be treated as failure.

    Transport success is not application success; empty success under a
    transport failure MUST fail closed.
    """
    failed = bool(
        framing_error
        or stream_closed
        or transport_error
        or (status is not None and (int(status) < 200 or int(status) >= 300))
    )
    if not failed:
        return False
    if "error" in body and body.get("error") is not None:
        return False
    if "result" in body:
        return True
    if body.get("ok") is True or body.get("success") is True:
        return True
    if body == {}:
        return True
    return True


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class AdapterVerdict:
    """Fail-closed admission decision from the runtime adapter."""

    case_id: str
    admitted: bool
    reasons: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def fail_closed(self) -> bool:
        return (not self.admitted) and len(self.reasons) > 0


def _reject(case_id: str, *reasons: str, **metadata: Any) -> AdapterVerdict:
    return AdapterVerdict(
        case_id=case_id,
        admitted=False,
        reasons=list(reasons),
        metadata=dict(metadata),
    )


def _admit(case_id: str, **metadata: Any) -> AdapterVerdict:
    return AdapterVerdict(
        case_id=case_id, admitted=True, reasons=[], metadata=dict(metadata)
    )


# ---------------------------------------------------------------------------
# Runtime adapter
# ---------------------------------------------------------------------------


@dataclass
class RuntimeP2pAdapter:
    """RuntimeP2pAdapter@1 for the datasets P2P path.

    Layer-T only for framing/quotas; layer-A PeerID≠UCAN and fencing checks
    are fail-closed gates that do not substitute for a full UCAN verifier.
    """

    runtime_id: str = RUNTIME_ID
    protocol_id: str = PROTOCOL_ID
    max_frame_bytes: int = MAX_FRAME_BYTES
    max_streams_per_peer: int = MAX_STREAMS_PER_PEER
    peer_id: str = ""
    stream_ready: bool = False
    protocol_negotiated: bool = False
    framer: LengthPrefixedFrame = field(init=False)
    session: Optional[P2PFramingSession] = field(default=None, init=False)
    _replay: ReplayWindow = field(default_factory=ReplayWindow, init=False)
    _correlation: CorrelationTable = field(default_factory=CorrelationTable, init=False)
    _quota: TransportQuota = field(init=False)
    _open_streams: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.max_frame_bytes = int(self.max_frame_bytes)
        self.max_streams_per_peer = int(self.max_streams_per_peer)
        self.framer = LengthPrefixedFrame(max_frame_bytes=self.max_frame_bytes)
        self._quota = TransportQuota(
            max_streams_per_peer=self.max_streams_per_peer,
            max_frame_bytes=self.max_frame_bytes,
        )

    # -- negotiation -------------------------------------------------------

    def negotiate_protocol(self, protocol_id: str) -> None:
        """Mark the stream protocol as negotiated after multistream-select."""
        if not is_supported_protocol_id(protocol_id):
            raise FramingError(f"unsupported_protocol_id:{protocol_id}")
        self.protocol_id = str(protocol_id)
        self.protocol_negotiated = True
        self.stream_ready = True

    def open_stream(self, peer_id: str = "") -> P2PFramingSession:
        """Open a carriage stream under TransportQuota@1."""
        pid = str(peer_id or self.peer_id or "local")
        self.peer_id = pid
        if not self.protocol_negotiated:
            raise FramingError("protocol_not_negotiated")
        self._quota.open_stream(pid)
        self._open_streams += 1
        self.session = P2PFramingSession(
            peer_id=pid,
            max_frame_bytes=self.max_frame_bytes,
            quota=self._quota,
        )
        # Session already counts open via its own open(); keep quota single-count.
        self.session.stream_opened = True
        self.session.idle.touch()
        self.stream_ready = True
        return self.session

    def close_stream(self) -> None:
        """Release stream quota for the current peer."""
        if self._open_streams > 0:
            self._quota.close_stream(self.peer_id)
            self._open_streams = max(0, self._open_streams - 1)
        if self.session is not None:
            self.session.stream_opened = False
            self.session = None

    # -- framing -----------------------------------------------------------

    def encode_frame(self, payload: Mapping[str, Any]) -> bytes:
        """Encode *payload* with LengthPrefixedFrame@1."""
        return self.framer.encode(payload)

    def decode_frame(self, frame: bytes) -> Dict[str, Any]:
        """Decode a length-prefixed frame; raise on size / framing errors."""
        payload, _consumed = self.framer.decode(frame)
        return payload

    def admit_frame(
        self,
        frame: bytes,
        *,
        check_replay: bool = True,
        now: float | None = None,
    ) -> Dict[str, Any]:
        """Decode and admit a wire frame under quota + replay controls."""
        if not (self.stream_ready and self.protocol_negotiated):
            raise FramingError("request_before_negotiation")
        payload, _ = decode_jsonrpc_frame(frame, max_frame_bytes=self.max_frame_bytes)
        if check_replay:
            self._replay.accept_frame(frame, now=now)
        if not self._quota.allow_message(
            self.peer_id or "local", nbytes=len(frame), now=now
        ):
            raise QuotaExceededError("message_rate_or_bandwidth_exceeded")
        return payload

    # -- authority gates ---------------------------------------------------

    def admit_execution(
        self,
        *,
        peer_id: Optional[str],
        ucan_present: bool,
        ucan_valid: bool,
        fencing_token: Optional[int] = None,
        current_fence: Optional[int] = None,
    ) -> None:
        """Fail closed when PeerID is valid but UCAN/fence is not."""
        if is_valid_peerid_invalid_ucan(
            peer_id=peer_id, ucan_present=ucan_present, ucan_valid=ucan_valid
        ):
            raise PermissionError("valid_peerid_invalid_or_missing_ucan")
        if (
            fencing_token is not None
            and current_fence is not None
            and is_stale_fence(int(fencing_token), current_fence=int(current_fence))
        ):
            raise PermissionError("stale_fence")

    # -- abuse vector evaluation (reuse MCPP-064 recipes) ------------------

    def evaluate_abuse_vector(self, vector: Mapping[str, Any]) -> AdapterVerdict:
        """Evaluate one compact abuse recipe against this runtime adapter.

        Recipe schema matches P2pAbuseVector@1 (MCPP-064). Abusive inputs
        never admit.
        """
        case = str(vector.get("case") or vector.get("case_id") or "")
        max_frame = int(vector.get("max_frame_bytes", self.max_frame_bytes))
        local = RuntimeP2pAdapter(
            runtime_id=self.runtime_id,
            protocol_id=self.protocol_id,
            max_frame_bytes=max_frame,
            max_streams_per_peer=int(
                vector.get("max_streams_per_peer", self.max_streams_per_peer)
            ),
            peer_id=str(vector.get("peer_id") or self.peer_id or "abuse-peer"),
        )

        if case == "oversized":
            return self._eval_oversized(local, vector, max_frame)
        if case == "truncated":
            return self._eval_truncated(local, vector, max_frame)
        if case == "invalid_length":
            return self._eval_invalid_length(local, vector, max_frame)
        if case == "request_before_negotiation":
            return self._eval_request_before_negotiation(vector)
        if case == "forged_version":
            return self._eval_forged_version(vector)
        if case == "unknown_method":
            return self._eval_unknown_method(vector)
        if case == "empty_success_on_transport_failure":
            return self._eval_empty_success(vector)
        if case == "replay":
            return self._eval_replay(local, vector)
        if case == "flood":
            return self._eval_flood(local, vector)
        if case == "excessive_streams":
            return self._eval_excessive_streams(local, vector)
        if case == "valid_peerid_invalid_ucan":
            return self._eval_peerid_invalid_ucan(vector)
        if case == "stale_fence":
            return self._eval_stale_fence(vector)
        if case == "duplicate_response":
            return self._eval_duplicate_response(local, vector)
        if case == "wrong_correlation_id":
            return self._eval_wrong_correlation(local, vector)
        return _reject(case or "unknown", "unknown_abuse_case", raw_case=case)

    # -- private evaluators ------------------------------------------------

    @staticmethod
    def _eval_oversized(
        local: "RuntimeP2pAdapter",
        vector: Mapping[str, Any],
        max_frame: int,
    ) -> AdapterVerdict:
        reasons: List[str] = []
        meta: Dict[str, Any] = {"max_frame_bytes": max_frame, "runtime": RUNTIME_ID}
        if "payload" in vector:
            try:
                local.encode_frame(vector["payload"])  # type: ignore[arg-type]
            except FrameSizeExceededError as exc:
                reasons.append(f"encode_rejected:{exc}")
            except FramingError as exc:
                reasons.append(f"encode_framing:{exc}")
        if "declared_length" in vector:
            declared = int(vector["declared_length"])
            if declared > max_frame:
                reasons.append(f"declared_frame_too_large:{declared}>{max_frame}")
            meta["declared_length"] = declared
        if "frame" in vector:
            try:
                local.decode_frame(bytes(vector["frame"]))
            except (FrameSizeExceededError, FramingError) as exc:
                reasons.append(f"wire:{exc}")
            else:
                reasons.append("oversized_wire_accepted")
        if not reasons:
            reasons.append("oversized_not_enforced")
        return _reject("oversized", *reasons, **meta)

    @staticmethod
    def _eval_truncated(
        local: "RuntimeP2pAdapter",
        vector: Mapping[str, Any],
        max_frame: int,
    ) -> AdapterVerdict:
        frame = bytes(vector.get("frame") or b"")
        try:
            local.decode_frame(frame)
        except FrameSizeExceededError as exc:
            return _reject("truncated", f"size:{exc}", max_frame_bytes=max_frame)
        except FramingError as exc:
            return _reject("truncated", f"framing:{exc}", max_frame_bytes=max_frame)
        return _reject("truncated", "truncated_not_detected")

    @staticmethod
    def _eval_invalid_length(
        local: "RuntimeP2pAdapter",
        vector: Mapping[str, Any],
        max_frame: int,
    ) -> AdapterVerdict:
        reasons: List[str] = []
        if "structural" in vector:
            structural = dict(vector["structural"])  # type: ignore[arg-type]
            length = structural.get("length")
            if not isinstance(length, int) or isinstance(length, bool) or length < 0:
                reasons.append(f"invalid_structural_length:{length!r}")
            elif length > max_frame:
                reasons.append(f"structural_too_large:{length}>{max_frame}")
            else:
                reasons.append("invalid_structural_length_accepted")
        if "frame" in vector:
            try:
                local.decode_frame(bytes(vector["frame"]))
            except (FramingError, FrameSizeExceededError) as exc:
                reasons.append(f"wire:{exc}")
            else:
                reasons.append("invalid_wire_length_accepted")
        if "declared_length" in vector:
            declared = vector["declared_length"]
            if not isinstance(declared, int) or isinstance(declared, bool) or declared < 0:
                reasons.append(f"negative_or_non_int_length:{declared!r}")
            elif int(declared) > max_frame:
                reasons.append(f"declared_too_large:{declared}>{max_frame}")
        if not reasons:
            reasons.append("invalid_length_not_detected")
        return _reject("invalid_length", *reasons)

    @staticmethod
    def _eval_request_before_negotiation(vector: Mapping[str, Any]) -> AdapterVerdict:
        if is_request_before_negotiation(
            stream_ready=bool(vector.get("stream_ready", False)),
            protocol_negotiated=bool(vector.get("protocol_negotiated", False)),
            is_application_request=bool(vector.get("is_application_request", True)),
        ):
            return _reject(
                "request_before_negotiation",
                "application_request_before_layer_t_ready",
                stream_ready=bool(vector.get("stream_ready", False)),
                protocol_negotiated=bool(vector.get("protocol_negotiated", False)),
            )
        return _reject("request_before_negotiation", "negotiation_gate_not_triggered")

    @staticmethod
    def _eval_forged_version(vector: Mapping[str, Any]) -> AdapterVerdict:
        if is_forged_protocol_version(
            vector.get("protocol_id"),  # type: ignore[arg-type]
            mcp_version=vector.get("mcp_version"),  # type: ignore[arg-type]
        ):
            return _reject(
                "forged_version",
                "unsupported_or_forged_version",
                protocol_id=vector.get("protocol_id"),
                mcp_version=vector.get("mcp_version"),
            )
        return _reject("forged_version", "forged_version_not_detected")

    @staticmethod
    def _eval_unknown_method(vector: Mapping[str, Any]) -> AdapterVerdict:
        method = str(vector.get("method") or "")
        if is_unknown_method(method):
            return _reject("unknown_method", "unknown_method", method=method)
        return _reject("unknown_method", "unknown_method_not_detected", method=method)

    @staticmethod
    def _eval_empty_success(vector: Mapping[str, Any]) -> AdapterVerdict:
        body = vector.get("response_body") or {}
        if not isinstance(body, Mapping):
            body = {}
        if treat_empty_success_as_failure(
            body,  # type: ignore[arg-type]
            status=vector.get("status"),  # type: ignore[arg-type]
            transport_error=vector.get("transport_error"),  # type: ignore[arg-type]
            stream_closed=bool(vector.get("stream_closed", False)),
            framing_error=bool(vector.get("framing_error", False)),
        ):
            return _reject(
                "empty_success_on_transport_failure",
                "empty_success_under_transport_failure",
                status=vector.get("status"),
                transport_error=vector.get("transport_error"),
            )
        return _reject(
            "empty_success_on_transport_failure",
            "empty_success_not_detected",
        )

    @staticmethod
    def _eval_replay(
        local: "RuntimeP2pAdapter", vector: Mapping[str, Any]
    ) -> AdapterVerdict:
        frames = list(vector.get("frames") or [])
        if len(frames) < 2:
            return _reject("replay", "insufficient_frames_for_replay")
        try:
            local.negotiate_protocol(PROTOCOL_ID)
            local.open_stream(local.peer_id)
            local.admit_frame(bytes(frames[0]), check_replay=True, now=1.0)
            local.admit_frame(bytes(frames[1]), check_replay=True, now=1.1)
        except ReplayDetectedError as exc:
            return _reject("replay", f"replay:{exc}")
        except (FramingError, FrameSizeExceededError, QuotaExceededError) as exc:
            return _reject("replay", f"transport:{exc}")
        return _reject("replay", "replay_not_detected")

    @staticmethod
    def _eval_flood(
        local: "RuntimeP2pAdapter", vector: Mapping[str, Any]
    ) -> AdapterVerdict:
        capacity = float(vector.get("rate_capacity", 5.0))
        refill = float(vector.get("rate_refill_per_sec", 0.0))
        timestamps = list(vector.get("message_timestamps") or [])
        local._quota = TransportQuota(
            max_streams_per_peer=local.max_streams_per_peer,
            max_frame_bytes=local.max_frame_bytes,
            rate_capacity=capacity,
            rate_refill_per_sec=max(0.0001, refill) if refill > 0 else 0.0001,
        )
        # Force near-zero refill when recipe requests a pure burst.
        if refill <= 0:
            limiter = local._quota._limiter(local.peer_id or "flood")
            limiter.refill_rate_per_sec = 0.0001
            limiter._tokens = capacity
        rejected = 0
        for ts in timestamps:
            ok = local._quota.allow_message(
                local.peer_id or "flood", nbytes=8, cost=1.0, now=float(ts)
            )
            if not ok:
                rejected += 1
        if rejected > 0:
            return _reject(
                "flood",
                "rate_limit_exceeded",
                rejected=rejected,
                attempts=len(timestamps),
            )
        return _reject("flood", "flood_not_detected", attempts=len(timestamps))

    @staticmethod
    def _eval_excessive_streams(
        local: "RuntimeP2pAdapter", vector: Mapping[str, Any]
    ) -> AdapterVerdict:
        attempts = int(vector.get("stream_open_attempts", local.max_streams_per_peer + 1))
        peer = str(vector.get("peer_id") or local.peer_id or "stream-peer")
        local.negotiate_protocol(PROTOCOL_ID)
        opened = 0
        rejected = 0
        for _ in range(attempts):
            try:
                local._quota.open_stream(peer)
                opened += 1
            except QuotaExceededError:
                rejected += 1
        if rejected > 0:
            return _reject(
                "excessive_streams",
                "stream_quota_exceeded",
                opened=opened,
                rejected=rejected,
                max_streams=local.max_streams_per_peer,
            )
        return _reject("excessive_streams", "stream_quota_not_enforced", opened=opened)

    @staticmethod
    def _eval_peerid_invalid_ucan(vector: Mapping[str, Any]) -> AdapterVerdict:
        if is_valid_peerid_invalid_ucan(
            peer_id=vector.get("peer_id"),  # type: ignore[arg-type]
            ucan_present=bool(vector.get("ucan_present", False)),
            ucan_valid=bool(vector.get("ucan_valid", False)),
        ):
            return _reject(
                "valid_peerid_invalid_ucan",
                "peerid_is_not_execution_authority",
                peer_id=vector.get("peer_id"),
            )
        return _reject("valid_peerid_invalid_ucan", "authority_gate_not_triggered")

    @staticmethod
    def _eval_stale_fence(vector: Mapping[str, Any]) -> AdapterVerdict:
        token = int(vector.get("fencing_token", 0))
        current = int(vector.get("current_fence", 0))
        if is_stale_fence(token, current_fence=current):
            return _reject(
                "stale_fence",
                "stale_fence_rejected",
                fencing_token=token,
                current_fence=current,
            )
        return _reject("stale_fence", "stale_fence_not_detected")

    @staticmethod
    def _eval_duplicate_response(
        local: "RuntimeP2pAdapter", vector: Mapping[str, Any]
    ) -> AdapterVerdict:
        response_ids = list(vector.get("response_ids") or [])
        peer = str(vector.get("peer_id") or local.peer_id or "peer")
        if len(response_ids) < 2:
            return _reject("duplicate_response", "insufficient_response_ids")
        try:
            local._replay.accept_response_id(response_ids[0], peer_id=peer, now=1.0)
            local._replay.accept_response_id(response_ids[1], peer_id=peer, now=1.1)
        except ReplayDetectedError as exc:
            return _reject("duplicate_response", f"replay:{exc}")
        return _reject("duplicate_response", "duplicate_response_not_detected")

    @staticmethod
    def _eval_wrong_correlation(
        local: "RuntimeP2pAdapter", vector: Mapping[str, Any]
    ) -> AdapterVerdict:
        requests = list(vector.get("requests") or [])
        responses = list(vector.get("responses") or [])
        if not requests or not responses:
            return _reject("wrong_correlation_id", "missing_request_or_response")
        try:
            for req in requests:
                if not isinstance(req, Mapping) or "id" not in req:
                    return _reject("wrong_correlation_id", "request_missing_id")
                local._correlation.register(
                    req["id"], method=str(req.get("method") or "")
                )
            for resp in responses:
                if not isinstance(resp, Mapping) or "id" not in resp:
                    return _reject("wrong_correlation_id", "response_missing_id")
                local._correlation.match_response(resp)  # type: ignore[arg-type]
        except CorrelationError as exc:
            return _reject("wrong_correlation_id", f"correlation:{exc}")
        return _reject("wrong_correlation_id", "wrong_correlation_not_detected")

    def snapshot(self) -> Dict[str, Any]:
        """Return adapter configuration for diagnostics."""
        return {
            "interface": INTERFACE_LABEL,
            "runtime_id": self.runtime_id,
            "protocol_id": self.protocol_id,
            "supported_protocol_ids": sorted(SUPPORTED_PROTOCOL_IDS),
            "max_frame_bytes": self.max_frame_bytes,
            "max_streams_per_peer": self.max_streams_per_peer,
            "stream_ready": self.stream_ready,
            "protocol_negotiated": self.protocol_negotiated,
            "legacy_disposition": legacy_transport_disposition(),
        }


def handle_framed_jsonrpc_message(
    raw: bytes,
    *,
    max_frame_bytes: int = MAX_FRAME_BYTES,
    framed: bool | None = None,
) -> Tuple[Dict[str, Any], bool]:
    """Decode a wire message that may be length-prefixed or raw JSON.

    Returns ``(payload, was_framed)``. Receivers reject oversized declared
    lengths fail-closed without allocating attacker-controlled buffers.
    """
    data = bytes(raw)
    use_frame = framed
    if use_frame is None:
        use_frame = _looks_length_prefixed(data, max_frame_bytes=max_frame_bytes)
    if use_frame:
        payload, _ = decode_jsonrpc_frame(data, max_frame_bytes=max_frame_bytes)
        return payload, True
    if len(data) > int(max_frame_bytes):
        raise FrameSizeExceededError(
            f"frame_too_large:{len(data)}>{int(max_frame_bytes)}"
        )
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FramingError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise FramingError("payload_not_object")
    return payload, False


def encode_framed_jsonrpc_message(
    payload: Mapping[str, Any],
    *,
    max_frame_bytes: int = MAX_FRAME_BYTES,
    framed: bool = True,
) -> bytes:
    """Encode *payload* as a length-prefixed frame (default) or raw JSON."""
    if framed:
        return encode_jsonrpc_frame(payload, max_frame_bytes=max_frame_bytes)
    body = json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    if len(body) > int(max_frame_bytes):
        raise FrameSizeExceededError(
            f"frame_too_large:{len(body)}>{int(max_frame_bytes)}"
        )
    return body


def _looks_raw_json(data: bytes) -> bool:
    """True when *data* looks like a UTF-8 JSON object/array (legacy body)."""
    if not data:
        return False
    i = 0
    while i < len(data) and data[i] in b" \t\r\n":
        i += 1
    return i < len(data) and data[i : i + 1] in (b"{", b"[")


def _looks_length_prefixed(data: bytes, *, max_frame_bytes: int) -> bool:
    if len(data) < 4:
        return False
    if _looks_raw_json(data):
        return False
    declared = int.from_bytes(data[:4], byteorder="big", signed=False)
    if declared > int(max_frame_bytes):
        # Binary length-prefix attack (not plausible JSON text).
        return True
    return len(data) >= 4 + declared


def get_runtime_adapter(**kwargs: Any) -> RuntimeP2pAdapter:
    """Factory for a datasets RuntimeP2pAdapter@1 instance."""
    return RuntimeP2pAdapter(**kwargs)


# ---------------------------------------------------------------------------
# Bounded MCP tools/list + tools/call parity (SCA-611)
# ---------------------------------------------------------------------------


class P2PToolTransportError(ValueError):
    """Invalid registry or call input at the P2P tool boundary."""


@dataclass(frozen=True)
class RegisteredTool:
    """One registered tool with exact schema and handler identity."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: Callable[..., Any]
    handler_id: str

    def to_mcp_tool(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": dict(self.input_schema),
            "handler_id": self.handler_id,
        }


@dataclass
class ToolRegistry:
    """Exact bounded tool catalog shared by tools/list and tools/call."""

    _tools: MutableMapping[str, RegisteredTool] = field(default_factory=dict)

    def register(
        self,
        name: str,
        handler: Callable[..., Any],
        *,
        description: str = "",
        input_schema: Mapping[str, Any] | None = None,
        handler_id: str | None = None,
    ) -> RegisteredTool:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise P2PToolTransportError("tool name is required")
        if not callable(handler):
            raise P2PToolTransportError("handler must be callable")
        schema = dict(
            input_schema or {"type": "object", "additionalProperties": True}
        )
        if schema.get("type") != "object":
            raise P2PToolTransportError("input_schema.type must be object")
        tool = RegisteredTool(
            name=normalized_name,
            description=str(description or ""),
            input_schema=schema,
            handler=handler,
            handler_id=handler_id
            or (
                f"{getattr(handler, '__module__', 'unknown')}:"
                f"{getattr(handler, '__qualname__', repr(handler))}"
            ),
        )
        self._tools[tool.name] = tool
        return tool

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            tool.to_mcp_tool()
            for tool in sorted(self._tools.values(), key=lambda item: item.name)
        ]

    def get(self, name: str) -> Optional[RegisteredTool]:
        return self._tools.get(str(name or "").strip())

    @property
    def size(self) -> int:
        return len(self._tools)


def _validate_tool_arguments(
    schema: Mapping[str, Any], arguments: Mapping[str, Any]
) -> None:
    if not isinstance(arguments, Mapping):
        raise P2PToolTransportError("arguments must be an object")
    required = schema.get("required") or []
    if isinstance(required, list):
        missing = [key for key in required if key not in arguments]
        if missing:
            raise P2PToolTransportError(
                f"missing required arguments: {', '.join(missing)}"
            )
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        unknown = [key for key in arguments if key not in properties]
        if unknown and schema.get("additionalProperties") is False:
            raise P2PToolTransportError(
                f"unexpected arguments: {', '.join(sorted(map(str, unknown)))}"
            )


async def _maybe_await_tool_result(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class LibP2PToolTransport:
    """In-process tools/list and tools/call surface with fail-closed errors."""

    def __init__(self, registry: ToolRegistry | None = None):
        self.registry = registry or ToolRegistry()
        self.transport_id = "datasets-mcplusplus-p2p-tool-transport@1"

    def tools_list(self) -> Dict[str, Any]:
        tools = self.registry.list_tools()
        return {
            "tools": tools,
            "registry_size": self.registry.size,
            "transport_id": self.transport_id,
            "path_class": "p2p",
        }

    async def tools_call(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        path_class: str = "p2p",
    ) -> Dict[str, Any]:
        tool = self.registry.get(name)
        if tool is None:
            return {
                "ok": False,
                "error": {
                    "code": "unknown_tool",
                    "message": f"tool not registered: {name}",
                },
                "path_class": path_class,
            }
        args = dict(arguments or {})
        try:
            _validate_tool_arguments(tool.input_schema, args)
        except P2PToolTransportError as exc:
            return {
                "ok": False,
                "error": {"code": "schema_invalid", "message": str(exc)},
                "path_class": path_class,
                "handler_id": tool.handler_id,
            }
        try:
            result = await _maybe_await_tool_result(tool.handler(**args))
        except TypeError as exc:
            return {
                "ok": False,
                "error": {"code": "schema_invalid", "message": str(exc)},
                "path_class": path_class,
                "handler_id": tool.handler_id,
            }
        except Exception as exc:  # pragma: no cover - handler-defined failure
            return {
                "ok": False,
                "error": {"code": "handler_error", "message": str(exc)},
                "path_class": path_class,
                "handler_id": tool.handler_id,
            }
        return {
            "ok": True,
            "result": result,
            "tool": tool.name,
            "handler_id": tool.handler_id,
            "path_class": path_class,
            "direct_effect_traceable": path_class in {"p2p", "direct"},
        }

    async def dispatch_jsonrpc(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        request_id = request.get("id")
        method = str(request.get("method") or "")
        params = (
            request.get("params")
            if isinstance(request.get("params"), Mapping)
            else {}
        )
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": self.tools_list()}
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = (
                params.get("arguments")
                if isinstance(params.get("arguments"), Mapping)
                else {}
            )
            outcome = await self.tools_call(name, arguments)
            if not outcome.get("ok"):
                error_code = (outcome.get("error") or {}).get("code")
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": (
                            -32602
                            if error_code in {"unknown_tool", "schema_invalid"}
                            else -32603
                        ),
                        "message": (outcome.get("error") or {}).get(
                            "message", "call failed"
                        ),
                        "data": outcome.get("error"),
                    },
                }
            return {"jsonrpc": "2.0", "id": request_id, "result": outcome}
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"unsupported method: {method}"},
        }


__all__ = [
    "INTERFACE_LABEL",
    "RUNTIME_ID",
    "PROTOCOL_ID",
    "SUPPORTED_PROTOCOL_IDS",
    "CANONICAL_MCP_VERSION",
    "LEGACY_MCP_VERSION",
    "ACCEPTED_MCP_VERSIONS",
    "MAX_FRAME_BYTES",
    "MAX_STREAMS_PER_PEER",
    "KNOWN_MCP_METHODS",
    "LEGACY_TRANSPORT_MODULE",
    "LEGACY_TRANSPORT_PATH",
    "LEGACY_TRANSPORT_AVAILABLE",
    "LEGACY_TRANSPORT_DISPOSITION",
    "legacy_transport_disposition",
    "MCP_P2P_PROTOCOL",
    "MAX_P2P_MESSAGE_SIZE",
    "MCPp2pNode",
    "PeerInfo",
    "P2PMessage",
    "dispatch_profile_e_jsonrpc_request",
    "get_p2p_node",
    "ensure_libp2p_installed",
    "ensure_libp2p_installed_async",
    "is_supported_protocol_id",
    "is_forged_protocol_version",
    "is_request_before_negotiation",
    "is_unknown_method",
    "is_valid_peerid_invalid_ucan",
    "is_stale_fence",
    "treat_empty_success_as_failure",
    "AdapterVerdict",
    "RuntimeP2pAdapter",
    "handle_framed_jsonrpc_message",
    "encode_framed_jsonrpc_message",
    "get_runtime_adapter",
    "P2PToolTransportError",
    "RegisteredTool",
    "ToolRegistry",
    "LibP2PToolTransport",
    # framing re-exports used by tests / kit alignment
    "LengthPrefixedFrame",
    "TransportQuota",
    "P2PFramingSession",
    "FramingError",
    "FrameSizeExceededError",
    "QuotaExceededError",
    "ReplayDetectedError",
    "CorrelationError",
    "encode_jsonrpc_frame",
    "decode_jsonrpc_frame",
]
