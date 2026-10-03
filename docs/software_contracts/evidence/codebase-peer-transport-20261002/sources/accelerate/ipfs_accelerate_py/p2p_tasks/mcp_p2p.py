"""MCP++ mcp+p2p stream handler skeleton.

This implements a minimal libp2p stream handler for the draft MCP++ transport
binding protocol id `/mcp+p2p/1.0.0`.

Scope (intentional):
- Deterministic u32 big-endian length-prefixed framing for JSON messages.
- Enforce that the first JSON-RPC request is `initialize`.
- Reply with a minimal JSON-RPC response to `initialize`.

Non-goals (for now):
- Full MCP JSON-RPC method surface
- Capability negotiation beyond a tiny placeholder
- Concurrency/multiplexing of multiple in-flight requests
"""

from __future__ import annotations

import threading
from typing import Any, Optional, Tuple

from ipfs_accelerate_py.mcp_server.mcplusplus.p2p_framing import (
    FrameSizeExceededError,
    FramingError,
    TokenBucketLimiter,
    decode_jsonrpc_frame,
    encode_jsonrpc_frame,
)

from ipfs_accelerate_py.p2p_tasks.mcp_p2p_protocol import PROTOCOL_MCP_P2P_V1
from ipfs_accelerate_py.p2p_tasks.peer_trust import (
    PeerTrustLevel,
    resolve_peer_trust_level,
    trust_tiers_enabled,
)

_MCP_P2P_PROFILE_ALIASES: dict[str, tuple[str, ...]] = {
    "mcp++/idl": ("mcp++/profile-a-idl",),
    "mcp++/cid-envelope": ("mcp++/profile-b-cid-artifacts",),
    "mcp++/ucan": ("mcp++/profile-c-ucan",),
    "mcp++/p2p-transport": ("mcp++/profile-e-mcp-p2p",),
}


_MCP_P2P_STATS_LOCK = threading.RLock()
_MCP_P2P_STATS: dict[str, int] = {
    "sessions_started": 0,
    "sessions_closed": 0,
    "initialized_sessions": 0,
    "frame_errors": 0,
    "rate_limited": 0,
    "unauthorized": 0,
    "internal_errors": 0,
}


def _coerce_bool(value: Any, *, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return bool(default)


def _normalize_profiles(raw_profiles: Any) -> list[str]:
    profiles: list[str] = []
    seen: set[str] = set()
    if not isinstance(raw_profiles, (list, tuple)):
        return profiles
    for candidate in raw_profiles:
        text = str(candidate or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        profiles.append(text)
    return profiles


def _with_profile_aliases(profiles: list[str]) -> list[str]:
    """Append backward-compatible MCP++ profile aliases without changing order."""

    out = list(profiles)
    seen = set(out)
    for profile in list(profiles):
        for alias in _MCP_P2P_PROFILE_ALIASES.get(profile, ()):
            if alias and alias not in seen:
                seen.add(alias)
                out.append(alias)
    return out


def _normalize_profile_negotiation(raw_negotiation: Any, profiles: list[str]) -> dict[str, Any]:
    payload = dict(raw_negotiation) if isinstance(raw_negotiation, dict) else {}
    mode = str(payload.get("mode") or "").strip() or "optional_additive"
    return {
        "supports_profile_negotiation": _coerce_bool(
            payload.get("supports_profile_negotiation", True), default=True
        ),
        "mode": mode,
        "profiles": list(profiles),
    }


def _resolve_profile_negotiation(registry: Any | None) -> tuple[list[str], dict[str, Any]]:
    """Resolve profile negotiation metadata from registry or unified defaults."""

    profiles: list[str] = []
    raw_negotiation: Any = None

    if registry is not None:
        try:
            profiles = _normalize_profiles(getattr(registry, "_unified_supported_profiles", None))
        except Exception:
            profiles = []

        try:
            raw_negotiation = getattr(registry, "_unified_profile_negotiation", None)
        except Exception:
            raw_negotiation = None

    if not profiles:
        # Lazy import to avoid pulling unified server at module import time.
        try:
            from ipfs_accelerate_py.mcp_server.server import get_unified_supported_profiles

            profiles = _normalize_profiles(get_unified_supported_profiles())
        except Exception:
            profiles = []

    profiles = _with_profile_aliases(profiles)
    negotiation = _normalize_profile_negotiation(raw_negotiation, profiles)
    return profiles, negotiation


def _select_profile(params: Any, supported_profiles: list[str]) -> str:
    """Select an active profile from client initialize params and supported list."""

    if not supported_profiles:
        return ""

    if isinstance(params, dict):
        requested = str(params.get("profile") or "").strip()
        if requested and requested in supported_profiles:
            return requested
        requested_many = params.get("profiles")
        if isinstance(requested_many, list):
            for candidate in requested_many:
                text = str(candidate or "").strip()
                if text and text in supported_profiles:
                    return text

    return str(supported_profiles[0])


def _inc_stat(key: str, amount: int = 1) -> None:
    with _MCP_P2P_STATS_LOCK:
        _MCP_P2P_STATS[key] = int(_MCP_P2P_STATS.get(key, 0)) + int(amount)


def get_mcp_p2p_stats() -> dict[str, int]:
    """Return cumulative transport handler counters."""
    with _MCP_P2P_STATS_LOCK:
        return dict(_MCP_P2P_STATS)


def reset_mcp_p2p_stats() -> None:
    """Reset cumulative transport handler counters."""
    with _MCP_P2P_STATS_LOCK:
        for key in list(_MCP_P2P_STATS.keys()):
            _MCP_P2P_STATS[key] = 0


def _env_int(name: str, default: int) -> int:
    try:
        import os

        raw = os.environ.get(name)
        if raw is None:
            return int(default)
        return int(str(raw).strip())
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        import os

        raw = os.environ.get(name)
        if raw is None:
            return float(default)
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _env_int_compat(primary: str, compat: str, default: int) -> int:
    try:
        import os

        raw = os.environ.get(primary)
        if raw is None:
            raw = os.environ.get(compat)
        if raw is None:
            return int(default)
        return int(str(raw).strip())
    except Exception:
        return int(default)


def _env_float_compat(primary: str, compat: str, default: float) -> float:
    try:
        import os

        raw = os.environ.get(primary)
        if raw is None:
            raw = os.environ.get(compat)
        if raw is None:
            return float(default)
        return float(str(raw).strip())
    except Exception:
        return float(default)


async def _read_exact(stream: Any, n: int, *, chunk_size: int = 4096) -> bytes:
    """Best-effort read exactly n bytes from a libp2p stream.

    Raises EOFError if the stream ends before n bytes are read.
    """

    remaining = int(n)
    if remaining <= 0:
        return b""

    parts: list[bytes] = []
    while remaining > 0:
        to_read = min(remaining, max(1, int(chunk_size)))
        chunk = await stream.read(to_read)
        if not chunk:
            raise EOFError("unexpected_eof")
        parts.append(bytes(chunk))
        remaining -= len(chunk)
    return b"".join(parts)


async def read_u32_framed_json(
    stream: Any,
    *,
    max_frame_bytes: int = 1024 * 1024,
    chunk_size: int = 4096,
) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
    """Read a single u32 length-prefixed JSON object.

    Returns (obj, None) on success, else (None, error_code).

    error_code is one of: empty, frame_too_large, invalid_json, invalid_message, eof
    """

    max_b = int(max_frame_bytes)
    if max_b < 1:
        max_b = 1

    try:
        header = await _read_exact(stream, 4, chunk_size=chunk_size)
    except EOFError:
        return None, "empty"
    except Exception:
        return None, "eof"

    # Parse declared frame size first to avoid unbounded reads.
    try:
        declared = int.from_bytes(header, byteorder="big", signed=False)
    except Exception:
        return None, "invalid_message"

    if declared > max_b:
        return None, "frame_too_large"

    try:
        payload = await _read_exact(stream, declared, chunk_size=chunk_size)
    except EOFError:
        return None, "eof"
    except Exception:
        return None, "eof"

    try:
        obj, _consumed = decode_jsonrpc_frame(header + payload, max_frame_bytes=max_b)
        return obj, None
    except FrameSizeExceededError:
        return None, "frame_too_large"
    except FramingError as exc:
        code = str(exc)
        if code in {"incomplete_prefix", "incomplete_body"}:
            return None, "eof"
        if code == "payload_not_object":
            return None, "invalid_message"
        if code in {"invalid_utf8", "invalid_json"}:
            return None, "invalid_json"
        return None, "invalid_message"
    except Exception:
        return None, "invalid_json"


async def write_u32_framed_json(
    stream: Any,
    obj: dict[str, Any],
    *,
    max_frame_bytes: int = 16 * 1024 * 1024,
) -> None:
    await stream.write(encode_jsonrpc_frame(obj, max_frame_bytes=int(max_frame_bytes)))


def _jsonrpc_error(*, id_value: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": id_value,
        "error": {
            "code": int(code),
            "message": str(message),
        },
    }


def _get_registry_tools(registry: Any | None) -> dict[str, dict[str, Any]]:
    if registry is None:
        return {}
    tools = getattr(registry, "tools", None)
    if isinstance(tools, dict):
        return tools
    # Some adapters expose tools via a property which can raise; best-effort.
    try:
        tools = registry.tools  # type: ignore[attr-defined]
        if isinstance(tools, dict):
            return tools
    except Exception:
        pass
    return {}


async def _maybe_validate(registry: Any | None, msg: dict[str, Any]) -> bool:
    if registry is None:
        return True
    fn = getattr(registry, "validate_p2p_message", None)
    if not callable(fn):
        return True
    try:
        res = fn(msg)
        if hasattr(res, "__await__"):
            return bool(await res)
        return bool(res)
    except Exception:
        return False


async def _call_tool(registry: Any | None, *, name: str, arguments: Any) -> tuple[bool, Any]:
    tools = _get_registry_tools(registry)
    desc = tools.get(str(name)) if isinstance(tools, dict) else None
    fn = None
    if isinstance(desc, dict):
        fn = desc.get("function")
    if not callable(fn):
        return False, {"error": "unknown_tool"}

    kwargs = arguments if isinstance(arguments, dict) else {}
    try:
        out = fn(**kwargs)
        if hasattr(out, "__await__"):
            out = await out
        return True, out
    except TypeError as exc:
        return False, {"error": "invalid_params", "detail": str(exc)}
    except Exception as exc:
        return False, {"error": "tool_error", "detail": str(exc)}


async def handle_mcp_p2p_stream(
    stream: Any,
    *,
    local_peer_id: str,
    registry: Any | None = None,
    max_frame_bytes: int = 1024 * 1024,
) -> None:
    """Minimal `/mcp+p2p/1.0.0` handler.

    Must not raise; libp2p swarm can stop listening if exceptions escape.
    """

    closed = False
    _inc_stat("sessions_started")

    try:
        max_frames = _env_int_compat(
            "IPFS_ACCELERATE_PY_MCP_P2P_MAX_FRAMES",
            "IPFS_DATASETS_PY_MCP_P2P_MAX_FRAMES",
            128,
        )
        if max_frames < 1:
            max_frames = 1
        rate_capacity = _env_int_compat(
            "IPFS_ACCELERATE_PY_MCP_P2P_RATE_CAPACITY",
            "IPFS_DATASETS_PY_MCP_P2P_RATE_CAPACITY",
            max_frames,
        )
        if rate_capacity < 1:
            rate_capacity = 1
        rate_refill_per_sec = _env_float_compat(
            "IPFS_ACCELERATE_PY_MCP_P2P_RATE_REFILL_PER_SEC",
            "IPFS_DATASETS_PY_MCP_P2P_RATE_REFILL_PER_SEC",
            float(max_frames),
        )
        if rate_refill_per_sec <= 0.0:
            rate_refill_per_sec = float(max_frames)
        limiter = TokenBucketLimiter(
            capacity=float(rate_capacity),
            refill_rate_per_sec=float(rate_refill_per_sec),
        )
        supported_profiles, profile_negotiation = _resolve_profile_negotiation(registry)

        initialized = False
        profile_g_negotiated = False
        frames_seen = 0
        while True:
            msg, err = await read_u32_framed_json(stream, max_frame_bytes=max_frame_bytes)
            if msg is None:
                # empty/eof -> end session
                if err in {None, "empty", "eof"}:
                    break
                # deterministic framing errors
                _inc_stat("frame_errors")
                await write_u32_framed_json(
                    stream,
                    _jsonrpc_error(
                        id_value=None, code=-32003, message=str(err or "invalid_message")
                    ),
                )
                break

            frames_seen += 1
            if frames_seen > max_frames:
                # Notifications must not receive a response.
                if "id" not in msg:
                    break
                _inc_stat("rate_limited")
                await write_u32_framed_json(
                    stream,
                    _jsonrpc_error(id_value=msg.get("id"), code=-32010, message="rate_limited"),
                )
                break

            if not limiter.allow(cost=1.0):
                # Notifications must not receive a response.
                if "id" not in msg:
                    break
                _inc_stat("rate_limited")
                await write_u32_framed_json(
                    stream,
                    _jsonrpc_error(id_value=msg.get("id"), code=-32010, message="rate_limited"),
                )
                break

            if not await _maybe_validate(registry, msg):
                # Notifications must not receive a response.
                if "id" not in msg:
                    break
                _inc_stat("unauthorized")
                await write_u32_framed_json(
                    stream,
                    _jsonrpc_error(id_value=msg.get("id"), code=-32001, message="unauthorized"),
                )
                break

            method = str(msg.get("method") or "")
            id_value = msg.get("id")
            jsonrpc = str(msg.get("jsonrpc") or "")
            is_notification = "id" not in msg

            if jsonrpc != "2.0":
                # Ignore invalid notifications; deterministically error for requests.
                if is_notification:
                    continue
                await write_u32_framed_json(
                    stream,
                    _jsonrpc_error(id_value=id_value, code=-32600, message="invalid_jsonrpc"),
                )
                break

            if not initialized:
                if method != "initialize":
                    # Notifications must not receive responses; ignore and keep waiting.
                    if is_notification:
                        continue
                    await write_u32_framed_json(
                        stream,
                        _jsonrpc_error(id_value=id_value, code=-32000, message="init_required"),
                    )
                    break
                # `initialize` as a notification is ignored; the session is not initialized.
                if is_notification:
                    continue
                initialized = True
                init_params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
                requested_experimental = (
                    init_params.get("capabilities", {}).get("experimental", {})
                    if isinstance(init_params.get("capabilities"), dict)
                    else {}
                )
                requested_profiles = init_params.get("profiles", [])
                profile_g_negotiated = (
                    bool(
                        isinstance(requested_experimental, dict)
                        and requested_experimental.get("mcp++/risk-scheduling")
                    )
                    or (
                        isinstance(requested_profiles, list)
                        and "mcp++/risk-scheduling" in requested_profiles
                    )
                    or init_params.get("profile") == "mcp++/risk-scheduling"
                )

                # Resolve peer trust level from initialize params and scale rate
                # limits accordingly: trusted peers receive a 2x capacity/refill
                # multiplier; elevated peers receive 1.5x; baseline is unchanged.
                if trust_tiers_enabled():
                    _event_dag = (
                        getattr(registry, "_event_dag", None) if registry is not None else None
                    )
                    peer_trust = resolve_peer_trust_level(init_params, event_dag=_event_dag)
                    if peer_trust == PeerTrustLevel.TRUSTED:
                        trust_multiplier = 2.0
                    elif peer_trust == PeerTrustLevel.ELEVATED:
                        trust_multiplier = 1.5
                    else:
                        trust_multiplier = 1.0
                    limiter = TokenBucketLimiter(
                        capacity=float(rate_capacity) * trust_multiplier,
                        refill_rate_per_sec=float(rate_refill_per_sec) * trust_multiplier,
                    )
                    max_frames = max(max_frames, int(float(max_frames) * trust_multiplier))

                _inc_stat("initialized_sessions")
                await write_u32_framed_json(
                    stream,
                    {
                        "jsonrpc": "2.0",
                        "id": id_value,
                        "result": {
                            "ok": True,
                            "protocolVersion": "2024-11-05",
                            "serverInfo": {
                                "name": "ipfs-accelerate-mcppp",
                                "version": "1.0.0",
                            },
                            "capabilities": {
                                "tools": {"listChanged": True},
                                "mcpPlusPlusProfiles": list(supported_profiles),
                                "experimental": {
                                    "mcp++/mcp-idl": "mcp++/idl" in supported_profiles,
                                    "mcp++/cid-envelope": "mcp++/cid-envelope"
                                    in supported_profiles,
                                    "mcp++/ucan": "mcp++/ucan" in supported_profiles,
                                    "mcp++/deontic-policy": "mcp++/deontic-policy"
                                    in supported_profiles,
                                    "mcp++/p2p-transport": "mcp++/p2p-transport"
                                    in supported_profiles,
                                    "mcp++/risk-scheduling": (
                                        __import__(
                                            "ipfs_accelerate_py.mcp_server.mcplusplus.profile_g_transport",
                                            fromlist=["profile_metadata"],
                                        ).profile_metadata()
                                        if "mcp++/risk-scheduling" in supported_profiles
                                        else False
                                    ),
                                },
                            },
                            "transport": PROTOCOL_MCP_P2P_V1,
                            "server": {"peer_id": str(local_peer_id or "")},
                            "profile_negotiation": dict(profile_negotiation),
                            "active_profile": _select_profile(
                                msg.get("params"), supported_profiles
                            ),
                            "limits": {
                                "max_frame_bytes": int(max_frame_bytes),
                                "max_frames": int(max_frames),
                                "rate_capacity": int(rate_capacity),
                                "rate_refill_per_sec": float(rate_refill_per_sec),
                            },
                        },
                    },
                )
                continue

            if method in {"tools/list", "tools.list"}:
                if is_notification:
                    continue
                tools = _get_registry_tools(registry)
                items: list[dict[str, Any]] = []
                for name, desc in tools.items():
                    if not isinstance(desc, dict):
                        continue
                    items.append(
                        {
                            "name": str(name),
                            "description": str(desc.get("description") or ""),
                            "inputSchema": desc.get("input_schema") or {},
                        }
                    )
                items.sort(key=lambda x: x.get("name") or "")
                await write_u32_framed_json(
                    stream,
                    {"jsonrpc": "2.0", "id": id_value, "result": {"tools": items}},
                )
                continue

            if method == "mcp++/policy/evaluate":
                if is_notification:
                    continue
                params = msg.get("params")
                if not isinstance(params, dict):
                    await write_u32_framed_json(
                        stream,
                        _jsonrpc_error(id_value=id_value, code=-32602, message="invalid_params"),
                    )
                    continue
                try:
                    from ipfs_accelerate_py.mcp_server.mcplusplus.policy_engine import (
                        evaluate_profile_d_execution_policy,
                    )

                    result = evaluate_profile_d_execution_policy(
                        actor=params.get("actor", ""),
                        action=params.get("action", ""),
                        resource=params.get("resource"),
                        policy=params.get("policy")
                        if isinstance(params.get("policy"), dict)
                        else None,
                        policy_text=params.get("policy_text"),
                        evaluated_at=params.get("evaluated_at"),
                        intent_cid=params.get("intent_cid"),
                        request_zkp_certificate=bool(params.get("request_zkp_certificate", False)),
                    )
                except ValueError as error:
                    await write_u32_framed_json(
                        stream,
                        _jsonrpc_error(id_value=id_value, code=-32602, message=str(error)),
                    )
                    continue
                except Exception:
                    await write_u32_framed_json(
                        stream,
                        _jsonrpc_error(
                            id_value=id_value,
                            code=-32603,
                            message="profile_d_evaluator_unavailable",
                        ),
                    )
                    continue
                await write_u32_framed_json(
                    stream,
                    {"jsonrpc": "2.0", "id": id_value, "result": result},
                )
                continue

            if method.startswith(
                (
                    "mcp++/goals/",
                    "mcp++/tasks/",
                    "mcp++/risk/",
                    "mcp++/neighborhood/",
                    "mcp++/schedule/",
                )
            ):
                if is_notification:
                    continue
                from ipfs_accelerate_py.mcp_server.mcplusplus.profile_g_transport import (
                    ProfileGTransportError,
                    get_profile_g_dispatcher,
                    jsonrpc_error,
                )

                params = msg.get("params")
                if not profile_g_negotiated:
                    error = ProfileGTransportError(
                        "G_CAPABILITY_NOT_NEGOTIATED", "Profile G was not negotiated"
                    )
                    await write_u32_framed_json(stream, jsonrpc_error(id_value, error))
                    continue
                if not isinstance(params, dict):
                    await write_u32_framed_json(
                        stream,
                        _jsonrpc_error(id_value=id_value, code=-32602, message="invalid_params"),
                    )
                    continue
                try:
                    response = {
                        "jsonrpc": "2.0",
                        "id": id_value,
                        "result": get_profile_g_dispatcher().dispatch(method, params),
                    }
                except ProfileGTransportError as error:
                    response = jsonrpc_error(id_value, error)
                await write_u32_framed_json(stream, response)
                continue

            if method in {"tools/call", "tools.call"}:
                if is_notification:
                    continue
                params = msg.get("params")
                if not isinstance(params, dict):
                    await write_u32_framed_json(
                        stream,
                        _jsonrpc_error(id_value=id_value, code=-32602, message="invalid_params"),
                    )
                    continue
                tool_name = params.get("name")
                arguments = params.get("arguments")
                ok, out = await _call_tool(registry, name=str(tool_name or ""), arguments=arguments)
                if not ok:
                    await write_u32_framed_json(
                        stream,
                        _jsonrpc_error(
                            id_value=id_value,
                            code=-32002,
                            message=str((out or {}).get("error") or "tool_error"),
                        ),
                    )
                    continue
                await write_u32_framed_json(
                    stream,
                    {"jsonrpc": "2.0", "id": id_value, "result": {"content": out}},
                )
                continue

            if is_notification:
                continue

            await write_u32_framed_json(
                stream,
                _jsonrpc_error(id_value=id_value, code=-32601, message="method_not_found"),
            )
            continue

        try:
            await stream.close()
            closed = True
        except Exception:
            pass
    except Exception:
        _inc_stat("internal_errors")
        try:
            await stream.close()
            closed = True
        except Exception:
            pass
    finally:
        if closed:
            _inc_stat("sessions_closed")


__all__ = [
    "PROTOCOL_MCP_P2P_V1",
    "read_u32_framed_json",
    "write_u32_framed_json",
    "handle_mcp_p2p_stream",
    "get_mcp_p2p_stats",
    "reset_mcp_p2p_stats",
]
