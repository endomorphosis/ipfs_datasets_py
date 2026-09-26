"""Schedule Hugging Face autoformal todos onto the accelerate supervisor queue.

JSONL is not an input. Callers pass a release pointer or locator.json.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def schedule_from_pointer(
    pointer: str | Path,
    *,
    repo_root: str | Path,
    board: str | Path,
    queue_path: str | Path,
    package_root: str | Path | None = None,
    max_tokens: int | None = None,
    max_validation_seconds: int | None = None,
    locate: Any | None = None,
    queue: Any | None = None,
) -> dict[str, Any]:
    """Load a Hugging Face todo pointer and register ready work."""

    pointer_path = Path(pointer)
    board_path = Path(board)
    queue_file = Path(queue_path)
    if locate is None:
        try:
            from ipfs_accelerate_py.agent_supervisor.task_sources.huggingface_todo_locator import (
                locate_and_schedule_huggingface_todos,
            )
            from ipfs_accelerate_py.agent_supervisor.task_sources.persistent_task_queue import (
                PersistentTaskQueue,
            )
        except ImportError as exc:
            raise ImportError(
                "pin an ipfs_accelerate_py checkout that includes "
                "agent_supervisor.task_sources.huggingface_todo_locator"
            ) from exc

        locate = locate_and_schedule_huggingface_todos
        if queue is None:
            queue_file.parent.mkdir(parents=True, exist_ok=True)
            queue = PersistentTaskQueue.load(queue_file)
    receipt = locate(
        pointer_path,
        repo_root=Path(repo_root),
        board_destination=board_path,
        package_root=package_root,
        queue=queue,
        max_tokens=max_tokens,
        max_validation_seconds=max_validation_seconds,
    )
    materialized = Path(receipt.get("board_path") or board_path)
    if not materialized.is_file():
        raise FileNotFoundError(f"scheduled Hugging Face todo board is missing: {materialized}")
    from ipfs_datasets_py.logic.autoformal.supervisor_todo import validate_supervisor_board

    validate_supervisor_board(materialized.read_text(encoding="utf-8"))
    save = getattr(queue, "save", None)
    if callable(save):
        save()
    return {
        "board_path": receipt.get("board_path") or str(board_path),
        "dataset_repo_id": receipt.get("dataset_repo_id") or "",
        "enqueued_task_ids": list(receipt.get("enqueued_task_ids") or []),
        "jsonl_written": False,
        "scheduled_task_ids": list(receipt.get("scheduled_task_ids") or []),
        "task_count": int(receipt.get("task_count") or 0),
        "time_management": dict(receipt.get("time_management") or {}),
        "wrote_compiler": False,
    }
