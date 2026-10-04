from __future__ import annotations

import os

import pytest


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.mark.skipif(
    not _truthy_env("IPFS_DATASETS_PY_RUN_HF_INTEGRATION_TESTS"),
    reason="Set IPFS_DATASETS_PY_RUN_HF_INTEGRATION_TESTS=1 to run HF/accelerate integration tests",
)
def test_duckdb_task_queue_local_end_to_end(tmp_path) -> None:
    """End-to-end: submit -> worker -> get (DuckDB queue)."""

    queue_path = tmp_path / "task_queue.duckdb"

    from ipfs_datasets_py import llm_router
    from ipfs_datasets_py.ml.accelerate_integration.worker import run_worker

    task_id = llm_router.submit_task(
        prompt="Say hello in one short sentence.",
        model_name=os.environ.get("IPFS_DATASETS_PY_LLM_MODEL", "gpt2"),
        queue_path=str(queue_path),
        max_new_tokens=32,
        temperature=0.2,
    )

    # Process exactly one queued task.
    rc = run_worker(queue_path=str(queue_path), worker_id="worker-test", once=True)
    assert rc == 0

    task = llm_router.get_task(task_id, queue_path=str(queue_path))
    assert isinstance(task, dict)
    assert task.get("status") == "completed"
    result = task.get("result")
    assert isinstance(result, dict)
    assert isinstance(result.get("text"), str)
    assert result.get("text")
