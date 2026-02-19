"""P2P workflow scheduler tools.

These tools wrap the standalone `ipfs_accelerate_py.p2p_workflow_scheduler` module
so workflows can be scheduled/assigned deterministically (locally) and exposed
through the MCP server tool surface.

Note: This scheduler is currently an in-process coordinator (no libp2p transport
integration in this wrapper). It is intended as the minimal integration layer
mirroring the MCP++ pattern of exposing concrete primitives as tools.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _ensure_ipfs_accelerate_on_path() -> None:
    try:
        import sys

        submodule_root = Path(__file__).resolve().parents[4]
        candidate = submodule_root / "ipfs_accelerate_py"
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    except (OSError, ValueError):
        pass


def _reset_scheduler_for_test() -> None:
    global _SCHEDULER
    _SCHEDULER = None


def _require_scheduler() -> Any:
    if _SCHEDULER is None:
        raise RuntimeError("scheduler_not_initialized")
    return _SCHEDULER


def _load_scheduler_types() -> Any:
    _ensure_ipfs_accelerate_on_path()
    from ipfs_accelerate_py.p2p_workflow_scheduler import (  # type: ignore
        P2PTask,
        P2PWorkflowScheduler,
        WorkflowTag,
    )

    return P2PWorkflowScheduler, P2PTask, WorkflowTag


def _coerce_tags(tag_strings: Optional[List[str]], WorkflowTag: Any) -> List[Any]:
    if not tag_strings:
        return []

    out: List[Any] = []
    for raw in tag_strings:
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue

        # Accept exact enum values, enum names, and underscore/hyphen variants.
        candidates = [s, s.lower(), s.upper(), s.replace("_", "-"), s.replace("-", "_")]
        hit = None
        for c in candidates:
            try:
                hit = WorkflowTag(c)
                break
            except (ValueError, KeyError):
                pass
            try:
                hit = WorkflowTag[c]
                break
            except (ValueError, KeyError):
                pass

        if hit is None:
            raise ValueError(f"unknown_tag: {s}")
        out.append(hit)

    return out


def _serialize_task(task: Any) -> Dict[str, Any]:
    return {
        "task_id": getattr(task, "task_id", ""),
        "workflow_id": getattr(task, "workflow_id", ""),
        "name": getattr(task, "name", ""),
        "priority": getattr(task, "priority", None),
        "created_at": getattr(task, "created_at", None),
        "task_hash": getattr(task, "task_hash", ""),
        "assigned_peer": getattr(task, "assigned_peer", None),
        "tags": [getattr(t, "value", str(t)) for t in (getattr(task, "tags", []) or [])],
    }


def p2p_scheduler_init(peer_id: str, bootstrap_peers: Optional[List[str]] = None, force: bool = False) -> Dict[str, Any]:
    """Initialize an in-process P2P workflow scheduler.

    Args:
        peer_id: Local peer ID (string identifier).
        bootstrap_peers: Optional list of known peer IDs to seed the scheduler.
        force: If true, replaces any existing scheduler instance.

    Returns:
        Dict containing scheduler status.
    """

    global _SCHEDULER

    if _SCHEDULER is not None and not bool(force):
        return {"ok": True, "already_initialized": True, "status": _SCHEDULER.get_status()}

    P2PWorkflowScheduler, _, _ = _load_scheduler_types()
    _SCHEDULER = P2PWorkflowScheduler(peer_id=str(peer_id), bootstrap_peers=list(bootstrap_peers or []))
    return {"ok": True, "already_initialized": False, "status": _SCHEDULER.get_status()}


def p2p_scheduler_status() -> Dict[str, Any]:
    """Return scheduler status if initialized."""

    try:
        scheduler = _require_scheduler()
        return {"ok": True, "status": scheduler.get_status()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def p2p_scheduler_submit_task(
    task_id: str,
    workflow_id: str,
    name: str,
    tags: Optional[List[str]] = None,
    priority: int = 5,
) -> Dict[str, Any]:
    """Submit a task into the in-process scheduler.

    Args:
        task_id: Unique task identifier.
        workflow_id: Identifier of the workflow this task belongs to.
        name: Human-readable task name.
        tags: List of tag strings (e.g. "p2p-only", "p2p-eligible").
        priority: 1-10, higher means more important.

    Returns:
        Dict with submission result and serialized task.
    """

    try:
        scheduler = _require_scheduler()
        _, P2PTask, WorkflowTag = _load_scheduler_types()

        p = int(priority)
        if p < 1 or p > 10:
            return {"ok": False, "error": "priority_out_of_range", "min": 1, "max": 10}

        task = P2PTask(
            task_id=str(task_id),
            workflow_id=str(workflow_id),
            name=str(name),
            tags=_coerce_tags(tags, WorkflowTag),
            priority=p,
            created_at=float(time.time()),
        )
        accepted = bool(scheduler.submit_task(task))
        return {"ok": accepted, "accepted": accepted, "task": _serialize_task(task)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def p2p_scheduler_get_next_task() -> Dict[str, Any]:
    """Pop the next runnable task for this peer (if any)."""

    try:
        scheduler = _require_scheduler()
        task = scheduler.get_next_task()
        return {"ok": True, "task": (_serialize_task(task) if task is not None else None)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def p2p_scheduler_mark_complete(task_id: str) -> Dict[str, Any]:
    """Mark an assigned task as completed."""

    try:
        scheduler = _require_scheduler()
        completed = bool(scheduler.mark_task_complete(str(task_id)))
        return {"ok": completed, "task_id": str(task_id), "completed": completed}
    except Exception as e:
        return {"ok": False, "error": str(e)}
