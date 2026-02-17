"""P2P networking CLI.

Minimal CLI surface for `ipfs_datasets_py.p2p_networking`.

This CLI intentionally routes through the existing MCP tool functions under
`ipfs_datasets_py.mcp_server.tools.p2p_tools` so behavior stays aligned with the
server tool surface.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional

import anyio


def _print(data: Any, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data)


def _json_obj(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    val = json.loads(raw)
    if val is None:
        return None
    if not isinstance(val, dict):
        raise ValueError("expected JSON object")
    return val


def _json_list(raw: Optional[str]) -> Optional[List[Any]]:
    if raw is None:
        return None
    val = json.loads(raw)
    if val is None:
        return None
    if not isinstance(val, list):
        raise ValueError("expected JSON array")
    return val


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs-datasets p2p-networking",
        description="P2P networking helpers (local cache/queue + remote calls)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")

    subp = parser.add_subparsers(dest="command", required=True)

    p_status = subp.add_parser("status", help="Local P2P service status")
    p_status.add_argument("--no-peers", action="store_true", help="Do not include peers")
    p_status.add_argument("--peers-limit", type=int, default=50)

    p_cache = subp.add_parser("cache", help="Local shared disk TTL cache")
    cache_sub = p_cache.add_subparsers(dest="cache_cmd", required=True)
    p_cache_get = cache_sub.add_parser("get")
    p_cache_get.add_argument("key")
    p_cache_has = cache_sub.add_parser("has")
    p_cache_has.add_argument("key")
    p_cache_set = cache_sub.add_parser("set")
    p_cache_set.add_argument("key")
    p_cache_set.add_argument("value_json", help="JSON value")
    p_cache_set.add_argument("--ttl-s", type=float, default=None)
    p_cache_del = cache_sub.add_parser("delete")
    p_cache_del.add_argument("key")

    p_task = subp.add_parser("task", help="Local durable DuckDB-backed task queue")
    task_sub = p_task.add_subparsers(dest="task_cmd", required=True)
    p_task_submit = task_sub.add_parser("submit")
    p_task_submit.add_argument("task_type")
    p_task_submit.add_argument("payload_json", help="JSON object payload")
    p_task_submit.add_argument("--model-name", default="")
    p_task_get = task_sub.add_parser("get")
    p_task_get.add_argument("task_id")
    p_task_delete = task_sub.add_parser("delete")
    p_task_delete.add_argument("task_id")

    p_remote = subp.add_parser("remote", help="Remote TaskQueue service operations over libp2p")
    remote_sub = p_remote.add_subparsers(dest="remote_cmd", required=True)

    def add_remote_target(p: argparse.ArgumentParser) -> None:
        p.add_argument("--multiaddr", default="", help="Remote multiaddr (optional)")
        p.add_argument("--peer-id", default="", help="Remote peer id (optional)")
        p.add_argument("--timeout-s", type=float, default=10.0)

    p_r_status = remote_sub.add_parser("status")
    add_remote_target(p_r_status)
    p_r_status.add_argument("--detail", action="store_true")

    p_r_call = remote_sub.add_parser("call-tool")
    add_remote_target(p_r_call)
    p_r_call.add_argument("tool_name")
    p_r_call.add_argument("--args-json", default=None, help="Optional JSON object args")
    p_r_call.set_defaults(timeout_s=30.0)

    p_r_cget = remote_sub.add_parser("cache-get")
    add_remote_target(p_r_cget)
    p_r_cget.add_argument("key")

    p_r_chas = remote_sub.add_parser("cache-has")
    add_remote_target(p_r_chas)
    p_r_chas.add_argument("key")

    p_r_cdel = remote_sub.add_parser("cache-delete")
    add_remote_target(p_r_cdel)
    p_r_cdel.add_argument("key")

    p_r_cset = remote_sub.add_parser("cache-set")
    add_remote_target(p_r_cset)
    p_r_cset.add_argument("key")
    p_r_cset.add_argument("value_json")

    p_r_submit = remote_sub.add_parser("submit-task")
    p_r_submit.add_argument("task_type")
    p_r_submit.add_argument("model_name")
    p_r_submit.add_argument("payload_json")
    p_r_submit.add_argument("--multiaddr", default="")
    p_r_submit.add_argument("--peer-id", default="")

    p_sched = subp.add_parser("scheduler", help="In-process P2P workflow scheduler (local)")
    sched_sub = p_sched.add_subparsers(dest="sched_cmd", required=True)

    p_s_init = sched_sub.add_parser("init")
    p_s_init.add_argument("peer_id")
    p_s_init.add_argument("--bootstrap-peers-json", default=None, help="JSON array of peer IDs")
    p_s_init.add_argument("--force", action="store_true")

    sched_sub.add_parser("status")

    p_s_submit = sched_sub.add_parser("submit-task")
    p_s_submit.add_argument("task_id")
    p_s_submit.add_argument("workflow_id")
    p_s_submit.add_argument("name")
    p_s_submit.add_argument("--tags-json", default=None, help="JSON array of tag strings")
    p_s_submit.add_argument("--priority", type=int, default=5)

    sched_sub.add_parser("get-next")

    p_s_complete = sched_sub.add_parser("mark-complete")
    p_s_complete.add_argument("task_id")

    return parser


async def _run_async(ns: argparse.Namespace) -> Dict[str, Any]:
    from ipfs_datasets_py.mcp_server.tools.p2p_tools.p2p_tools import (
        p2p_cache_delete,
        p2p_cache_get,
        p2p_cache_has,
        p2p_cache_set,
        p2p_remote_cache_delete,
        p2p_remote_cache_get,
        p2p_remote_cache_has,
        p2p_remote_cache_set,
        p2p_remote_call_tool,
        p2p_remote_status,
        p2p_remote_submit_task,
        p2p_service_status,
        p2p_task_delete,
        p2p_task_get,
        p2p_task_submit,
    )
    from ipfs_datasets_py.mcp_server.tools.p2p_tools.workflow_scheduler_tools import (
        p2p_scheduler_get_next_task,
        p2p_scheduler_init,
        p2p_scheduler_mark_complete,
        p2p_scheduler_status,
        p2p_scheduler_submit_task,
    )

    if ns.command == "status":
        return p2p_service_status(include_peers=not bool(ns.no_peers), peers_limit=int(ns.peers_limit))

    if ns.command == "cache":
        if ns.cache_cmd == "get":
            return p2p_cache_get(ns.key)
        if ns.cache_cmd == "has":
            return p2p_cache_has(ns.key)
        if ns.cache_cmd == "set":
            value = json.loads(ns.value_json)
            return p2p_cache_set(ns.key, value=value, ttl_s=ns.ttl_s)
        if ns.cache_cmd == "delete":
            return p2p_cache_delete(ns.key)
        raise ValueError(f"unknown cache command: {ns.cache_cmd}")

    if ns.command == "task":
        if ns.task_cmd == "submit":
            payload = _json_obj(ns.payload_json) or {}
            return p2p_task_submit(task_type=ns.task_type, payload=payload, model_name=str(ns.model_name or ""))
        if ns.task_cmd == "get":
            return p2p_task_get(ns.task_id)
        if ns.task_cmd == "delete":
            return p2p_task_delete(ns.task_id)
        raise ValueError(f"unknown task command: {ns.task_cmd}")

    if ns.command == "remote":
        if ns.remote_cmd == "status":
            return await p2p_remote_status(
                remote_multiaddr=str(ns.multiaddr or ""),
                peer_id=str(ns.peer_id or ""),
                timeout_s=float(ns.timeout_s),
                detail=bool(ns.detail),
            )
        if ns.remote_cmd == "call-tool":
            args = _json_obj(ns.args_json) if ns.args_json else None
            return await p2p_remote_call_tool(
                tool_name=str(ns.tool_name),
                args=args,
                remote_multiaddr=str(ns.multiaddr or ""),
                remote_peer_id=str(ns.peer_id or ""),
                timeout_s=float(ns.timeout_s),
            )
        if ns.remote_cmd == "cache-get":
            return await p2p_remote_cache_get(
                key=str(ns.key),
                remote_multiaddr=str(ns.multiaddr or ""),
                remote_peer_id=str(ns.peer_id or ""),
                timeout_s=float(ns.timeout_s),
            )
        if ns.remote_cmd == "cache-has":
            return await p2p_remote_cache_has(
                key=str(ns.key),
                remote_multiaddr=str(ns.multiaddr or ""),
                remote_peer_id=str(ns.peer_id or ""),
                timeout_s=float(ns.timeout_s),
            )
        if ns.remote_cmd == "cache-delete":
            return await p2p_remote_cache_delete(
                key=str(ns.key),
                remote_multiaddr=str(ns.multiaddr or ""),
                remote_peer_id=str(ns.peer_id or ""),
                timeout_s=float(ns.timeout_s),
            )
        if ns.remote_cmd == "cache-set":
            value = json.loads(ns.value_json)
            return await p2p_remote_cache_set(
                key=str(ns.key),
                value=value,
                remote_multiaddr=str(ns.multiaddr or ""),
                remote_peer_id=str(ns.peer_id or ""),
                timeout_s=float(ns.timeout_s),
            )
        if ns.remote_cmd == "submit-task":
            payload = _json_obj(ns.payload_json) or {}
            return await p2p_remote_submit_task(
                task_type=str(ns.task_type),
                model_name=str(ns.model_name),
                payload=payload,
                remote_multiaddr=str(ns.multiaddr or ""),
                remote_peer_id=str(ns.peer_id or ""),
            )
        raise ValueError(f"unknown remote command: {ns.remote_cmd}")

    if ns.command == "scheduler":
        if ns.sched_cmd == "init":
            peers = _json_list(ns.bootstrap_peers_json) if ns.bootstrap_peers_json else None
            peers_str = [str(p) for p in (peers or [])]
            return p2p_scheduler_init(peer_id=str(ns.peer_id), bootstrap_peers=peers_str, force=bool(ns.force))
        if ns.sched_cmd == "status":
            return p2p_scheduler_status()
        if ns.sched_cmd == "submit-task":
            tags = _json_list(ns.tags_json) if ns.tags_json else None
            tags_str = [str(t) for t in (tags or [])]
            return p2p_scheduler_submit_task(
                task_id=str(ns.task_id),
                workflow_id=str(ns.workflow_id),
                name=str(ns.name),
                tags=tags_str,
                priority=int(ns.priority),
            )
        if ns.sched_cmd == "get-next":
            return p2p_scheduler_get_next_task()
        if ns.sched_cmd == "mark-complete":
            return p2p_scheduler_mark_complete(str(ns.task_id))
        raise ValueError(f"unknown scheduler command: {ns.sched_cmd}")

    raise ValueError(f"unknown command: {ns.command}")


def main(argv: Optional[List[str]] = None) -> int:
    ns = create_parser().parse_args(argv)
    try:
        data = anyio.run(_run_async, ns)
        _print(data, json_output=bool(ns.json))
        return 0
    except KeyboardInterrupt:
        return 1
    except Exception as e:
        _print({"status": "error", "error": str(e)}, json_output=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
