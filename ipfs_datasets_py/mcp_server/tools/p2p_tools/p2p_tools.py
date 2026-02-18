"""P2P TaskQueue/cache tools.

These tools expose status and local operations for the in-process libp2p
TaskQueue/cache service (ported from the MCP++ stack).

They are safe to register even when the P2P service is disabled; they operate
against the local DuckDB queue and local cache directories.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata, RUNTIME_TRIO

from ...trio_bridge import run_in_trio


def _ensure_ipfs_accelerate_on_path() -> None:
    try:
        import sys

        submodule_root = Path(__file__).resolve().parents[4]
        candidate = submodule_root / "ipfs_accelerate_py"
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    except Exception:
        pass


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_service",
    priority=8,
    timeout_seconds=10.0,
    mcp_description="Get P2P service status and peer information"
)
def p2p_service_status(include_peers: bool = True, peers_limit: int = 50) -> Dict[str, Any]:
    """Return local P2P service status and (optionally) recently seen peers."""

    out: Dict[str, Any] = {"ok": True, "service": {}, "peers": []}

    _ensure_ipfs_accelerate_on_path()

    try:
        from ipfs_accelerate_py.p2p_tasks.service import get_local_service_state

        out["service"] = get_local_service_state() or {}
    except Exception as e:
        out["ok"] = False
        out["error"] = f"status_unavailable: {e}"
        out["service"] = {}

    if include_peers:
        try:
            from ipfs_accelerate_py.p2p_tasks.service import list_known_peers

            out["peers"] = list_known_peers(alive_only=True, limit=int(peers_limit))
        except Exception:
            out["peers"] = []

    return out


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_cache",
    priority=9,
    timeout_seconds=5.0,
    mcp_description="Get value from P2P cache"
)
def p2p_cache_get(key: str) -> Dict[str, Any]:
    """Get a value from the shared disk TTL cache (local view)."""

    _ensure_ipfs_accelerate_on_path()

    try:
        from ipfs_accelerate_py.p2p_tasks.cache_store import DiskTTLCache, cache_enabled, default_cache_dir

        if not cache_enabled():
            return {"ok": False, "error": "cache_disabled"}

        cache = DiskTTLCache(default_cache_dir())
        value = cache.get(str(key))
        return {"ok": True, "key": str(key), "hit": value is not None, "value": value}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_cache",
    priority=9,
    timeout_seconds=5.0,
    mcp_description="Check if key exists in P2P cache"
)
def p2p_cache_has(key: str) -> Dict[str, Any]:
    """Check if a key exists in the shared disk TTL cache (local view)."""

    _ensure_ipfs_accelerate_on_path()

    try:
        from ipfs_accelerate_py.p2p_tasks.cache_store import DiskTTLCache, cache_enabled, default_cache_dir

        if not cache_enabled():
            return {"ok": False, "error": "cache_disabled"}

        cache = DiskTTLCache(default_cache_dir())
        hit = bool(cache.has(str(key)))
        return {"ok": True, "key": str(key), "hit": hit}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_cache",
    priority=8,
    timeout_seconds=10.0,
    mcp_description="Set value in P2P cache with optional TTL"
)
def p2p_cache_set(key: str, value: Any, ttl_s: Optional[float] = None) -> Dict[str, Any]:
    """Set a value in the shared disk TTL cache (local view)."""

    _ensure_ipfs_accelerate_on_path()

    try:
        from ipfs_accelerate_py.p2p_tasks.cache_store import DiskTTLCache, cache_enabled, default_cache_dir

        if not cache_enabled():
            return {"ok": False, "error": "cache_disabled"}

        cache = DiskTTLCache(default_cache_dir())
        cache.set(str(key), value, ttl_s=float(ttl_s) if ttl_s is not None else None)
        return {"ok": True, "key": str(key)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_cache",
    priority=8,
    timeout_seconds=5.0,
    mcp_description="Delete key from P2P cache"
)
def p2p_cache_delete(key: str) -> Dict[str, Any]:
    """Delete a key from the shared disk TTL cache (local view)."""

    _ensure_ipfs_accelerate_on_path()

    try:
        from ipfs_accelerate_py.p2p_tasks.cache_store import DiskTTLCache, cache_enabled, default_cache_dir

        if not cache_enabled():
            return {"ok": False, "error": "cache_disabled"}

        cache = DiskTTLCache(default_cache_dir())
        deleted = bool(cache.delete(str(key)))
        return {"ok": True, "key": str(key), "deleted": deleted}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_task",
    priority=8,
    timeout_seconds=30.0,
    io_intensive=True,
    mcp_description="Submit task to P2P task queue"
)
def p2p_task_submit(task_type: str, payload: Dict[str, Any], model_name: str = "") -> Dict[str, Any]:
    """Submit a task into the durable DuckDB-backed task queue (local)."""

    _ensure_ipfs_accelerate_on_path()

    try:
        from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue

        q = TaskQueue()
        task_id = q.submit(task_type=str(task_type), model_name=str(model_name or ""), payload=dict(payload or {}))
        return {"ok": True, "task_id": task_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_task",
    priority=9,
    timeout_seconds=10.0,
    mcp_description="Get task status from P2P queue"
)
def p2p_task_get(task_id: str) -> Dict[str, Any]:
    """Get task status/result from the durable DuckDB-backed task queue (local)."""

    _ensure_ipfs_accelerate_on_path()

    try:
        from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue

        q = TaskQueue()
        task = q.get(str(task_id))
        if task is None:
            return {"ok": False, "error": "task_not_found", "task_id": str(task_id)}
        return {"ok": True, "task": task}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_task",
    priority=8,
    timeout_seconds=10.0,
    mcp_description="Delete task from P2P queue"
)
def p2p_task_delete(task_id: str) -> Dict[str, Any]:
    """Delete a task row from the queue (local)."""

    _ensure_ipfs_accelerate_on_path()

    try:
        from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue

        q = TaskQueue()
        deleted = bool(q.delete(task_id=str(task_id)))
        return {"ok": True, "task_id": str(task_id), "deleted": deleted}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _remote_queue(*, peer_id: str = "", multiaddr: str = "") -> Any:
    _ensure_ipfs_accelerate_on_path()
    from ipfs_accelerate_py.p2p_tasks.client import RemoteQueue

    return RemoteQueue(peer_id=str(peer_id or "").strip(), multiaddr=str(multiaddr or "").strip())


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_remote",
    priority=8,
    timeout_seconds=15.0,
    mcp_description="Get status from remote P2P peer"
)
async def p2p_remote_status(
    remote_multiaddr: str = "",
    peer_id: str = "",
    timeout_s: float = 10.0,
    detail: bool = False,
) -> Dict[str, Any]:
    """Query a remote TaskQueue service status over libp2p.

    If `remote_multiaddr` is empty, the client attempts discovery (announce-file,
    configured bootstrap endpoints, rendezvous, DHT, mDNS).
    """

    try:
        _ensure_ipfs_accelerate_on_path()
        from ipfs_accelerate_py.p2p_tasks.client import request_status

        remote = _remote_queue(peer_id=peer_id, multiaddr=remote_multiaddr)
        resp = await run_in_trio(request_status, remote=remote, timeout_s=float(timeout_s), detail=bool(detail))
        return resp if isinstance(resp, dict) else {"ok": False, "error": "invalid_response"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_remote",
    priority=7,
    timeout_seconds=60.0,
    io_intensive=True,
    mcp_description="Call MCP tool on remote P2P peer"
)
async def p2p_remote_call_tool(
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    remote_multiaddr: str = "",
    remote_peer_id: str = "",
    timeout_s: float = 30.0,
) -> Dict[str, Any]:
    """Invoke a tool on a remote TaskQueue service (op=call_tool)."""

    try:
        _ensure_ipfs_accelerate_on_path()
        from ipfs_accelerate_py.p2p_tasks.client import call_tool

        remote = _remote_queue(peer_id=remote_peer_id, multiaddr=remote_multiaddr)
        resp = await run_in_trio(
            call_tool,
            remote=remote,
            tool_name=str(tool_name),
            args=(args if isinstance(args, dict) else {}),
            timeout_s=float(timeout_s),
        )
        return resp if isinstance(resp, dict) else {"ok": False, "error": "invalid_response"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_remote",
    priority=8,
    timeout_seconds=10.0,
    mcp_description="Get value from remote peer cache"
)
async def p2p_remote_cache_get(
    key: str,
    remote_multiaddr: str = "",
    remote_peer_id: str = "",
    timeout_s: float = 10.0,
) -> Dict[str, Any]:
    """Get a cache value from a remote TaskQueue service (op=cache.get)."""

    try:
        _ensure_ipfs_accelerate_on_path()
        from ipfs_accelerate_py.p2p_tasks.client import cache_get

        remote = _remote_queue(peer_id=remote_peer_id, multiaddr=remote_multiaddr)
        resp = await run_in_trio(cache_get, remote=remote, key=str(key), timeout_s=float(timeout_s))
        return resp if isinstance(resp, dict) else {"ok": False, "error": "invalid_response"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_remote",
    priority=7,
    timeout_seconds=15.0,
    mcp_description="Set value in remote peer cache"
)
async def p2p_remote_cache_set(
    key: str,
    value: Any,
    remote_multiaddr: str = "",
    remote_peer_id: str = "",
    timeout_s: float = 10.0,
) -> Dict[str, Any]:
    """Set a cache value on a remote TaskQueue service (op=cache.set)."""

    try:
        _ensure_ipfs_accelerate_on_path()
        from ipfs_accelerate_py.p2p_tasks.client import cache_set

        remote = _remote_queue(peer_id=remote_peer_id, multiaddr=remote_multiaddr)
        resp = await run_in_trio(
            cache_set,
            remote=remote,
            key=str(key),
            value=value,
            timeout_s=float(timeout_s),
        )
        return resp if isinstance(resp, dict) else {"ok": False, "error": "invalid_response"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_remote",
    priority=8,
    timeout_seconds=10.0,
    mcp_description="Check if key exists in remote peer cache"
)
async def p2p_remote_cache_has(
    key: str,
    remote_multiaddr: str = "",
    remote_peer_id: str = "",
    timeout_s: float = 10.0,
) -> Dict[str, Any]:
    """Check for a cache key on a remote TaskQueue service (op=cache.has)."""

    try:
        _ensure_ipfs_accelerate_on_path()
        from ipfs_accelerate_py.p2p_tasks.client import cache_has

        remote = _remote_queue(peer_id=remote_peer_id, multiaddr=remote_multiaddr)
        resp = await run_in_trio(cache_has, remote=remote, key=str(key), timeout_s=float(timeout_s))
        return resp if isinstance(resp, dict) else {"ok": False, "error": "invalid_response"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_remote",
    priority=7,
    timeout_seconds=10.0,
    mcp_description="Delete key from remote peer cache"
)
async def p2p_remote_cache_delete(
    key: str,
    remote_multiaddr: str = "",
    remote_peer_id: str = "",
    timeout_s: float = 10.0,
) -> Dict[str, Any]:
    """Delete a cache key on a remote TaskQueue service (op=cache.delete)."""

    try:
        _ensure_ipfs_accelerate_on_path()
        from ipfs_accelerate_py.p2p_tasks.client import cache_delete

        remote = _remote_queue(peer_id=remote_peer_id, multiaddr=remote_multiaddr)
        resp = await run_in_trio(cache_delete, remote=remote, key=str(key), timeout_s=float(timeout_s))
        return resp if isinstance(resp, dict) else {"ok": False, "error": "invalid_response"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_remote",
    priority=7,
    timeout_seconds=30.0,
    io_intensive=True,
    mcp_description="Submit task to remote peer queue"
)
async def p2p_remote_submit_task(
    task_type: str,
    model_name: str,
    payload: Dict[str, Any],
    remote_multiaddr: str = "",
    remote_peer_id: str = "",
) -> Dict[str, Any]:
    """Submit a task to a remote TaskQueue service (op=submit)."""

    try:
        _ensure_ipfs_accelerate_on_path()
        from ipfs_accelerate_py.p2p_tasks.client import submit_task_with_info

        remote = _remote_queue(peer_id=remote_peer_id, multiaddr=remote_multiaddr)
        resp = await run_in_trio(
            submit_task_with_info,
            remote=remote,
            task_type=str(task_type),
            model_name=str(model_name),
            payload=(payload if isinstance(payload, dict) else {}),
        )
        if isinstance(resp, dict):
            out = {"ok": True}
            out.update(resp)
            return out
        return {"ok": True, "task": resp}
    except Exception as e:
        return {"ok": False, "error": str(e)}
