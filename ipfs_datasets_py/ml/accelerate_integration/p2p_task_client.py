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

__all__ = [
    "RemoteQueue",
    "submit_task",
    "submit_task_with_info",
    "get_task",
    "wait_task",
]
