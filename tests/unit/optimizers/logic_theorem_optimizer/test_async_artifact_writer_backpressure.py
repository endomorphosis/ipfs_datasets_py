from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.async_artifact_writer import (
    ArtifactFsyncPolicy,
    ArtifactSnapshotHandle,
    AsyncArtifactBackpressureTimeout,
    AsyncArtifactWriter,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (
    load_checkpoint,
)


def _writer(tmp_path: Path, **kwargs: object) -> AsyncArtifactWriter:
    return AsyncArtifactWriter(
        tmp_path / "spool",
        fsync_policy=ArtifactFsyncPolicy.disabled(),
        **kwargs,
    )


def test_exact_serialized_bytes_bound_admission_and_are_released(
    tmp_path: Path,
) -> None:
    writer = _writer(
        tmp_path,
        autostart=False,
        queue_capacity=8,
        max_queue_bytes=10,
        backpressure_timeout_seconds=0.01,
    )
    try:
        first = writer.submit_snapshot(
            tmp_path / "first.bin",
            ArtifactSnapshotHandle(b"123456"),
            kind="binary",
        )
        assert writer.pending_bytes == 6

        with pytest.raises(AsyncArtifactBackpressureTimeout, match="bytes=6/10"):
            writer.submit_snapshot(
                tmp_path / "second.bin",
                ArtifactSnapshotHandle(b"abcde"),
                kind="binary",
                timeout=0.01,
            )

        writer.start()
        first.result(timeout=2.0)
        assert writer.wait_until_idle(timeout=2.0)
        assert writer.pending_bytes == 0
        assert writer.summary()["peak_queue_bytes"] == 6
    finally:
        writer.close(wait=False, cancel_pending=True)


def test_single_snapshot_larger_than_byte_budget_fails_without_queueing(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path, autostart=False, max_queue_bytes=4)
    try:
        with pytest.raises(AsyncArtifactBackpressureTimeout, match="byte limit is 4"):
            writer.submit_snapshot(
                tmp_path / "large.bin",
                ArtifactSnapshotHandle(b"12345"),
                kind="binary",
            )
        assert writer.pending_count == 0
        assert writer.pending_bytes == 0
    finally:
        writer.close(wait=False, cancel_pending=True)


def test_queued_summaries_coalesce_to_latest_and_complete_all_futures(
    tmp_path: Path,
) -> None:
    writer = _writer(
        tmp_path,
        autostart=False,
        queue_capacity=1,
        max_queue_bytes=1024,
    )
    destination = tmp_path / "run.summary"
    try:
        futures = [
            writer.write_json_atomic(
                destination,
                {"cycle": cycle, "large_repeated_value": "x" * 100},
                kind="summary",
            )
            for cycle in range(25)
        ]

        queued = writer.summary()
        assert queued["pending_count"] == 1
        assert queued["queue_depth"] == 1
        assert queued["coalesced_count"] == 24
        assert queued["coalesced_bytes"] > queued["pending_bytes"]
        assert queued["pending_bytes"] <= queued["max_queue_bytes"]

        writer.start()
        receipts = [future.result(timeout=2.0) for future in futures]
        assert json.loads(destination.read_text(encoding="utf-8"))["cycle"] == 24
        # Superseded callers observe completion of the replacement rather than
        # hanging or incorrectly claiming their stale bytes were durable.
        assert len({receipt.checksum for receipt in receipts}) == 1
        assert writer.summary()["completed_count"] == 1
    finally:
        writer.close(cancel_pending=True)


def test_write_concurrency_never_exceeds_configured_bound(tmp_path: Path) -> None:
    writer = _writer(
        tmp_path,
        autostart=False,
        queue_capacity=8,
        max_queue_bytes=1024,
        max_write_concurrency=2,
    )
    entered = threading.Barrier(3)
    release = threading.Event()
    call_lock = threading.Lock()
    call_count = 0
    original = writer._write_job

    def blocked_write(job: object):
        nonlocal call_count
        with call_lock:
            call_count += 1
            should_block = call_count <= 2
        if should_block:
            entered.wait(timeout=2.0)
            release.wait(timeout=2.0)
        return original(job)  # type: ignore[arg-type]

    writer._write_job = blocked_write  # type: ignore[method-assign]
    try:
        futures = [
            writer.write_text_atomic(tmp_path / f"artifact-{index}.txt", str(index))
            for index in range(4)
        ]
        writer.start()
        entered.wait(timeout=2.0)
        summary = writer.summary()
        assert summary["active_write_count"] == 2
        assert summary["peak_active_write_count"] == 2
        assert summary["max_write_concurrency"] == 2
        release.set()
        for future in futures:
            future.result(timeout=3.0)
    finally:
        release.set()
        writer.close(cancel_pending=True)


def test_revision_bound_handle_uses_no_state_copy_and_survives_mutation(
    tmp_path: Path,
) -> None:
    class NoCopyState(ModalAutoencoderTrainingState):
        def copy(self) -> "NoCopyState":
            raise AssertionError("checkpoint enqueue must not copy the full state")

    state = NoCopyState(decoded_embeddings={"sample": [0.1, 0.2]})
    writer = _writer(tmp_path, autostart=False)
    try:
        snapshot = writer.snapshot_state_checkpoint(
            state,
            cycle=7,
            full=True,
            compact=True,
        )
        captured_revision = snapshot.revision
        future = writer.write_state_checkpoint(
            tmp_path / "state.checkpoint",
            snapshot,
            cycle=7,
            compact=True,
        )

        state.decoded_embeddings["sample"][0] = 99.0
        assert state.state_revision > captured_revision

        writer.start()
        receipt = future.result(timeout=2.0)
        loaded = load_checkpoint(tmp_path / "state.checkpoint")
        assert loaded.state.decoded_embeddings["sample"] == [0.1, 0.2]
        assert receipt.metadata["revision"] == captured_revision
        assert receipt.metadata["snapshot_identity"] == snapshot.identity
    finally:
        writer.close(cancel_pending=True)


def test_close_flushes_required_checkpoint_even_when_cancelling_optional_work(
    tmp_path: Path,
) -> None:
    state = ModalAutoencoderTrainingState(decoded_embeddings={"sample": [0.25]})
    writer = _writer(tmp_path, autostart=False, queue_capacity=4)
    optional = writer.write_json_atomic(tmp_path / "optional.json", {"value": 1})
    required = writer.write_state_checkpoint(
        tmp_path / "required.checkpoint",
        state,
        cycle=1,
        compact=True,
    )

    writer.close(wait=False, cancel_pending=True)

    assert optional.done()
    receipt = required.result(timeout=0.1)
    assert receipt.kind == "state_checkpoint_full"
    assert load_checkpoint(tmp_path / "required.checkpoint").state.to_dict() == state.to_dict()
    assert writer.summary()["required_pending_count"] == 0


def test_all_persistence_phase_timings_are_exposed(tmp_path: Path) -> None:
    writer = _writer(tmp_path, autostart=False)
    try:
        writer.write_json_atomic(
            tmp_path / "summary.json",
            {"cycle": 1},
            kind="summary",
        )
        future = writer.write_json_atomic(
            tmp_path / "summary.json",
            {"cycle": 2},
            kind="summary",
        )
        writer.start()
        future.result(timeout=2.0)
        summary = writer.summary()
        timings = summary["timings_seconds"]
        assert set(timings) == {
            "enqueue",
            "serialization",
            "write",
            "fsync",
            "coalescing",
            "backpressure",
        }
        assert timings["enqueue"]["count"] == 2
        assert timings["serialization"]["count"] == 2
        assert timings["write"]["count"] == 1
        assert timings["coalescing"]["count"] == 1
        assert timings["fsync"]["count"] == 0
        for metric in timings.values():
            assert metric["total"] >= 0.0
            assert metric["max"] >= metric["last"] >= 0.0
    finally:
        writer.close(cancel_pending=True)


def test_byte_backpressure_wait_timing_is_recorded(tmp_path: Path) -> None:
    writer = _writer(
        tmp_path,
        autostart=False,
        max_queue_bytes=5,
        backpressure_timeout_seconds=0.02,
    )
    try:
        writer.write_text_atomic(tmp_path / "first.txt", "12345")
        started = time.monotonic()
        with pytest.raises(AsyncArtifactBackpressureTimeout):
            writer.write_text_atomic(tmp_path / "second.txt", "x")
        assert time.monotonic() - started >= 0.015
        summary = writer.summary()
        assert summary["backpressure_timeouts"] == 1
        assert summary["timings_seconds"]["backpressure"]["count"] == 1
        assert summary["timings_seconds"]["backpressure"]["total"] >= 0.015
    finally:
        writer.close(wait=False, cancel_pending=True)
