"""Tests for typed exception handling in DistributedProcessor worker loop."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.distributed_processor import (
    DistributedProcessor,
    Task,
    TaskStatus,
    WorkerStatus,
)


def test_worker_loop_marks_task_failed_on_typed_processing_error() -> None:
    processor = DistributedProcessor(num_workers=1, max_retries=0, enable_fault_tolerance=False)
    worker_id = "worker_0"
    task_id = "task_1"
    processor.tasks[task_id] = Task(task_id=task_id, data={"x": 1})
    processor.task_queue.put(task_id)

    def _process(_data):
        processor.stop_event.set()
        raise ValueError("bad task data")

    processor._worker_loop(worker_id, _process)

    task = processor.tasks[task_id]
    assert task.status == TaskStatus.FAILED
    assert task.error == "bad task data"
    assert processor.workers[worker_id].status == WorkerStatus.IDLE


def test_worker_loop_marks_worker_failed_on_typed_queue_error() -> None:
    processor = DistributedProcessor(num_workers=1, max_retries=0, enable_fault_tolerance=False)
    worker_id = "worker_0"

    class _BadQueue:
        def get(self, timeout=1.0):
            processor.stop_event.set()
            raise RuntimeError("queue read failure")

    processor.task_queue = _BadQueue()  # type: ignore[assignment]
    processor._worker_loop(worker_id, lambda data: data)

    assert processor.workers[worker_id].status == WorkerStatus.FAILED
