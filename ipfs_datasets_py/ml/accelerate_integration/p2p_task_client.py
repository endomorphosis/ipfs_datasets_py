"""libp2p client for the TaskQueue RPC service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional


def _have_libp2p() -> bool:
    try:
        import libp2p  # noqa: F401
        return True
    except Exception:
        return False


@dataclass
class RemoteQueue:
    peer_id: str
    multiaddr: str


async def _dial_and_request(*, remote: RemoteQueue, message: Dict[str, Any]) -> Dict[str, Any]:
    if not _have_libp2p():
        raise RuntimeError("libp2p is not installed; install ipfs_datasets_py[p2p]")

    import anyio
    import inspect
    from libp2p import new_host
    from multiaddr import Multiaddr
    from libp2p.peer.peerinfo import info_from_p2p_addr

    from .p2p_task_protocol import PROTOCOL_V1, get_shared_token

    host_obj = new_host()
    host = await host_obj if inspect.isawaitable(host_obj) else host_obj

    token = get_shared_token()
    if token and "token" not in message:
        message = dict(message)
        message["token"] = token

    peer_info = info_from_p2p_addr(Multiaddr(remote.multiaddr))

    # In py-libp2p, Swarm.listen() is a long-running coroutine and is required
    # to start the internal swarm tasks, even for outbound dials.
    async with anyio.create_task_group() as tg:
        tg.start_soon(host.get_network().listen, Multiaddr("/ip4/0.0.0.0/tcp/0"))
        await anyio.sleep(0)

        with anyio.fail_after(20.0):
            await host.connect(peer_info)
            stream = await host.new_stream(peer_info.peer_id, [PROTOCOL_V1])
            await stream.write(json.dumps(message).encode("utf-8"))
            raw = await stream.read()
            await stream.close()

        tg.cancel_scope.cancel()

    try:
        await host.close()
    except Exception:
        pass

    try:
        return json.loads((raw or b"{}").decode("utf-8"))
    except Exception:
        return {"ok": False, "error": "invalid_json_response"}


async def submit_task(*, remote: RemoteQueue, task_type: str, model_name: str, payload: Dict[str, Any]) -> str:
    resp = await _dial_and_request(
        remote=remote,
        message={
            "op": "submit",
            "task_type": task_type,
            "model_name": model_name,
            "payload": payload,
        },
    )
    if not resp.get("ok"):
        raise RuntimeError(f"submit failed: {resp}")
    return str(resp.get("task_id"))


async def get_task(*, remote: RemoteQueue, task_id: str) -> Optional[Dict[str, Any]]:
    resp = await _dial_and_request(remote=remote, message={"op": "get", "task_id": task_id})
    if not resp.get("ok"):
        raise RuntimeError(f"get failed: {resp}")
    return resp.get("task")


async def wait_task(*, remote: RemoteQueue, task_id: str, timeout_s: float = 60.0) -> Optional[Dict[str, Any]]:
    resp = await _dial_and_request(
        remote=remote,
        message={"op": "wait", "task_id": task_id, "timeout_s": float(timeout_s)},
    )
    if not resp.get("ok"):
        raise RuntimeError(f"wait failed: {resp}")
    return resp.get("task")
