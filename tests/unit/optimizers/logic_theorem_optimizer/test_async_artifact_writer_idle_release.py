"""Completed work must not stay rooted by an open, idle worker thread."""

from __future__ import annotations

import gc
import json
import threading
import weakref

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.async_artifact_writer import (
    ArtifactFsyncPolicy,
    AsyncArtifactWriter,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState,
)


class _WriteFailure(RuntimeError):
    pass


class _BlockedObserver:
    def __init__(self, started, release, *, fail=False):
        self.started = started
        self.release = release
        self.fail = fail
        self.graph = {"retained_until_write": bytearray(1024)}

    def __call__(self):
        self.started.set()
        assert self.release.wait(5), "test did not release the active write"
        if self.fail:
            raise _WriteFailure("original observer failure")


def _assert_original_failure(future):
    original = future._error
    assert type(original) is _WriteFailure
    assert str(original) == "original observer failure"
    names = []
    frame = original.__traceback__
    while frame is not None:
        names.append(frame.tb_frame.f_code.co_name)
        frame = frame.tb_next
    assert "_run" in names
    assert "_write_job" in names
    assert "__call__" in names
    try:
        future.result(1)
    except _WriteFailure as caught:
        assert caught is original
    else:
        pytest.fail("the original write error was suppressed")


def _assert_open_idle(writer):
    assert writer.pending_count == 0
    assert writer.pending_bytes == 0
    assert not writer._closed
    assert all(thread.is_alive() for thread in writer._threads)


@pytest.mark.parametrize("workers", [1, 2])
@pytest.mark.parametrize("fail", [False, True])
def test_completed_handles_observers_and_futures_are_released_while_idle(
    tmp_path, workers, fail,
):
    writer = AsyncArtifactWriter(
        tmp_path / "spool", max_write_concurrency=workers,
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    releases = [threading.Event() for _ in range(workers)]
    started = [threading.Event() for _ in range(workers)]
    handle_refs, observer_refs, future_refs, futures = [], [], [], []
    try:
        for index in range(workers):
            handle = writer.snapshot_bytes(bytes([index + 1]) * 4096)
            observer = _BlockedObserver(started[index], releases[index], fail=fail)
            future = writer.submit_snapshot(
                tmp_path / f"artifact-{index}", handle, kind="fixture",
                worker_observer=observer,
            )
            handle_refs.append(weakref.ref(handle))
            observer_refs.append(weakref.ref(observer))
            future_refs.append(weakref.ref(future))
            futures.append(future)
        del handle, observer, future
        assert all(event.wait(5) for event in started)
        gc.collect()
        assert all(reference() is not None for reference in handle_refs + observer_refs)
        assert writer.pending_bytes == workers * 4096
        assert writer.summary()["active_write_count"] == workers

        for event in releases:
            event.set()
        assert writer.wait_until_idle(5)
        _assert_open_idle(writer)
        for future in futures:
            if fail:
                _assert_original_failure(future)
            else:
                assert future.result(1).bytes_written == 4096
        del future
        # Caller-retained error tracebacks legitimately retain the failed job.
        if fail:
            gc.collect()
            assert all(reference() is not None for reference in handle_refs + observer_refs)
        futures.clear()
        gc.collect()
        assert all(reference() is None for reference in handle_refs + observer_refs + future_refs)
        _assert_open_idle(writer)
        assert writer.summary()["failed_count" if fail else "completed_count"] == workers
    finally:
        for event in releases:
            event.set()
        writer.close(cancel_pending=True)


def test_legacy_bound_to_json_observer_releases_native_state_after_write(tmp_path):
    started, release = threading.Event(), threading.Event()

    class ObservedState(ModalAutoencoderTrainingState):
        def to_json(self):
            started.set()
            assert release.wait(5)
            return super().to_json()

    writer = AsyncArtifactWriter(
        tmp_path / "spool", fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    try:
        state = ObservedState(decoded_embeddings={"sample": [0.25, -0.0]})
        reference = weakref.ref(state)
        future = writer.write_state_checkpoint(tmp_path / "state.json", state, cycle=1)
        del state
        assert started.wait(5)
        gc.collect()
        assert reference() is not None
        release.set()
        assert writer.wait_until_idle(5)
        assert future.result(1).kind == "state_checkpoint_full"
        gc.collect()
        assert reference() is None
        assert json.loads((tmp_path / "state.json").read_text())["decoded_embeddings"] == {
            "sample": [0.25, -0.0],
        }
        _assert_open_idle(writer)
    finally:
        release.set()
        writer.close(cancel_pending=True)


def test_failed_coalesced_followers_do_not_root_the_completed_job(tmp_path):
    writer = AsyncArtifactWriter(
        tmp_path / "spool", autostart=False,
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    started, release = threading.Event(), threading.Event()
    try:
        first = writer.snapshot_bytes(b"superseded")
        first_ref = weakref.ref(first)
        old_future = writer.submit_snapshot(
            tmp_path / "summary", first, kind="summary", coalesce_key="summary",
        )
        last = writer.snapshot_bytes(b"accepted")
        observer = _BlockedObserver(started, release, fail=True)
        last_future = writer.submit_snapshot(
            tmp_path / "summary", last, kind="summary", coalesce_key="summary",
            worker_observer=observer,
        )
        refs = [weakref.ref(value) for value in (last, observer, old_future, last_future)]
        del first, last, observer
        gc.collect()
        assert first_ref() is None
        assert writer.summary()["coalesced_count"] == 1
        writer.start()
        assert started.wait(5)
        release.set()
        assert writer.wait_until_idle(5)
        assert old_future._error is last_future._error
        _assert_original_failure(old_future)
        _assert_original_failure(last_future)
        del old_future, last_future
        gc.collect()
        assert all(reference() is None for reference in refs)
        _assert_open_idle(writer)
    finally:
        release.set()
        writer.close(cancel_pending=True)
