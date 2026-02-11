"""Compatibility wrapper for the libp2p TaskQueue RPC client.

The canonical implementation now lives in ``ipfs_accelerate_py.p2p_tasks`` so
systemd-deployed MCP services can reuse the same code.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class RemoteQueue:
    peer_id: str
    multiaddr: str


async def submit_task(*, remote: RemoteQueue, task_type: str, model_name: str, payload: Dict[str, Any]) -> str:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_submit_task = getattr(module, "submit_task")

    return await a_submit_task(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        task_type=task_type,
        model_name=model_name,
        payload=payload,
    )


async def submit_task_with_info(
    *, remote: RemoteQueue, task_type: str, model_name: str, payload: Dict[str, Any]
) -> Dict[str, str]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_submit_task_with_info = getattr(module, "submit_task_with_info")

    return await a_submit_task_with_info(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        task_type=task_type,
        model_name=model_name,
        payload=payload,
    )


async def get_task(*, remote: RemoteQueue, task_id: str) -> Optional[Dict[str, Any]]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_get_task = getattr(module, "get_task")

    return await a_get_task(remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr), task_id=task_id)


async def wait_task(*, remote: RemoteQueue, task_id: str, timeout_s: float = 60.0) -> Optional[Dict[str, Any]]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_wait_task = getattr(module, "wait_task")

    return await a_wait_task(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        task_id=task_id,
        timeout_s=timeout_s,
    )


async def get_capabilities(*, remote: RemoteQueue, timeout_s: float = 10.0, detail: bool = False) -> Dict[str, Any]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_get_capabilities = getattr(module, "get_capabilities")

    return await a_get_capabilities(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        timeout_s=timeout_s,
        detail=detail,
    )


def get_capabilities_sync(*, remote: RemoteQueue, timeout_s: float = 10.0, detail: bool = False) -> Dict[str, Any]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_get_capabilities_sync = getattr(module, "get_capabilities_sync")

    return a_get_capabilities_sync(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        timeout_s=timeout_s,
        detail=detail,
    )


async def call_tool(*, remote: RemoteQueue, tool_name: str, args: Optional[Dict[str, Any]] = None, timeout_s: float = 30.0) -> Dict[str, Any]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_call_tool = getattr(module, "call_tool")

    return await a_call_tool(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        tool_name=str(tool_name),
        args=args if isinstance(args, dict) else {},
        timeout_s=timeout_s,
    )


def call_tool_sync(*, remote: RemoteQueue, tool_name: str, args: Optional[Dict[str, Any]] = None, timeout_s: float = 30.0) -> Dict[str, Any]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_call_tool_sync = getattr(module, "call_tool_sync")

    return a_call_tool_sync(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        tool_name=str(tool_name),
        args=args if isinstance(args, dict) else {},
        timeout_s=timeout_s,
    )


async def cache_get(*, remote: RemoteQueue, key: str, timeout_s: float = 10.0) -> Dict[str, Any]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_cache_get = getattr(module, "cache_get")

    return await a_cache_get(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        key=str(key),
        timeout_s=float(timeout_s),
    )


def cache_get_sync(*, remote: RemoteQueue, key: str, timeout_s: float = 10.0) -> Dict[str, Any]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_cache_get_sync = getattr(module, "cache_get_sync")

    return a_cache_get_sync(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        key=str(key),
        timeout_s=float(timeout_s),
    )


async def cache_has(*, remote: RemoteQueue, key: str, timeout_s: float = 10.0) -> Dict[str, Any]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_cache_has = getattr(module, "cache_has")

    return await a_cache_has(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        key=str(key),
        timeout_s=float(timeout_s),
    )


def cache_has_sync(*, remote: RemoteQueue, key: str, timeout_s: float = 10.0) -> Dict[str, Any]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_cache_has_sync = getattr(module, "cache_has_sync")

    return a_cache_has_sync(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        key=str(key),
        timeout_s=float(timeout_s),
    )


async def cache_set(
    *, remote: RemoteQueue, key: str, value: Any, ttl_s: float | None = None, timeout_s: float = 10.0
) -> Dict[str, Any]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_cache_set = getattr(module, "cache_set")

    return await a_cache_set(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        key=str(key),
        value=value,
        ttl_s=ttl_s,
        timeout_s=float(timeout_s),
    )


def cache_set_sync(
    *, remote: RemoteQueue, key: str, value: Any, ttl_s: float | None = None, timeout_s: float = 10.0
) -> Dict[str, Any]:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.client")
    ARemoteQueue = getattr(module, "RemoteQueue")
    a_cache_set_sync = getattr(module, "cache_set_sync")

    return a_cache_set_sync(
        remote=ARemoteQueue(peer_id=remote.peer_id, multiaddr=remote.multiaddr),
        key=str(key),
        value=value,
        ttl_s=ttl_s,
        timeout_s=float(timeout_s),
    )

__all__ = [
    "RemoteQueue",
    "submit_task",
    "submit_task_with_info",
    "get_task",
    "wait_task",
    "get_capabilities",
    "get_capabilities_sync",
    "call_tool",
    "call_tool_sync",
    "cache_get",
    "cache_get_sync",
    "cache_has",
    "cache_has_sync",
    "cache_set",
    "cache_set_sync",
]
