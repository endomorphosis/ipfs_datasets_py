"""Persisted-baseline writer fixtures; no optimizer or native training runs."""

from dataclasses import FrozenInstanceError
import gc
import hashlib
import json
from pathlib import Path
import weakref

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import async_artifact_writer as writer_module
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.async_artifact_writer import (
    ArtifactFsyncPolicy,
    ArtifactSnapshotHandle,
    AsyncArtifactBackpressureTimeout,
    AsyncArtifactWriter,
    ConcurrentArtifactMutationError,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (
    CheckpointBaseline,
    checkpoint_baseline,
    deserialize_checkpoint,
    load_checkpoint,
    serialize_checkpoint,
    serialize_delta,
)


def _writer(tmp_path, **kwargs):
    return AsyncArtifactWriter(tmp_path / "spool", autostart=False,
                               fsync_policy=ArtifactFsyncPolicy.disabled(), **kwargs)


def _state():
    return ModalAutoencoderTrainingState(
        decoded_embeddings={"sample": [-0.0, 0.1]},
        feature_embedding_weights={"shall": [0.25, -0.5], "obsolete": [0.0]},
        applied_todo_ids=["first", "first"],
    )


@pytest.mark.parametrize("precision", ["float64", "float32"])
@pytest.mark.parametrize("lineage", [None, {"suite": "synthetic-writer-parity"}])
def test_full_snapshot_token_matches_persisted_bytes_not_source_normalization(tmp_path, precision, lineage):
    state = _state()
    writer = _writer(tmp_path)
    try:
        source_identity = str(state.state_identity(metric_lineage=lineage))
        snapshot = writer.snapshot_state_checkpoint(state, cycle=3, float_precision=precision,
                                                    metric_lineage=lineage, metadata={"fixture": True})
        assert snapshot.payload == serialize_checkpoint(state, float_precision=precision,
            metric_lineage=lineage, metadata={"cycle": 3, "fixture": True}, revision=state.state_revision)
        loaded = deserialize_checkpoint(snapshot.payload, expected_metric_lineage=lineage)
        assert type(snapshot.checkpoint_baseline) is CheckpointBaseline
        assert snapshot.checkpoint_baseline == checkpoint_baseline(loaded.state,
            float_precision=precision, metric_lineage=lineage)
        assert snapshot.checkpoint_baseline.state_digest == loaded.manifest.state_digest
        assert snapshot.checkpoint_baseline.revision == loaded.state.state_revision == snapshot.revision
        assert snapshot.identity == source_identity
        if precision == "float32":
            assert snapshot.identity != snapshot.checkpoint_baseline.state_digest
        assert snapshot.byte_size == len(snapshot.payload)
        assert writer.summary()["timings"]["serialization"]["count"] == 1
    finally:
        writer.close(cancel_pending=True)


@pytest.mark.parametrize("precision", ["float64", "float32"])
def test_baseline_and_legacy_delta_snapshots_have_identical_bytes_and_tokens(tmp_path, precision):
    base = _state()
    state = base.copy()
    state._state_identity_tracker.restore_revision(base.state_revision)
    state.feature_embedding_weights.pop("obsolete")
    state.feature_embedding_weights["shall"][0] = 0.3
    state.applied_todo_ids.extend(["second", "first"])
    lineage = {"suite": "synthetic-delta"}
    writer = _writer(tmp_path)
    try:
        baseline = writer.snapshot_state_checkpoint(base, cycle=0, float_precision=precision,
                                                     metric_lineage=lineage).checkpoint_baseline
        options = dict(cycle=1, full=False, float_precision=precision, metric_lineage=lineage)
        old = writer.snapshot_state_checkpoint(state, base_state=base, **options)
        new = writer.snapshot_state_checkpoint(state, base_baseline=baseline, **options)
        expected = serialize_delta(base, state, float_precision=precision, metric_lineage=lineage,
            metadata={"cycle": 1}, base_revision=base.state_revision, revision=state.state_revision)
        assert old.payload == new.payload == expected
        assert old.identity == new.identity == str(state.state_identity(metric_lineage=lineage))
        assert old.checkpoint_baseline == new.checkpoint_baseline == checkpoint_baseline(
            state, float_precision=precision, metric_lineage=lineage)
        assert baseline.revision == base.state_revision
    finally:
        writer.close(cancel_pending=True)


def test_handle_positional_compatibility_and_noncompact_baseline_absence(tmp_path):
    original = ArtifactSnapshotHandle(b"original", 7, "identity", "timestamp", 0.125)
    assert (original.payload, original.revision, original.identity, original.created_at,
            original.serialization_seconds, original.checkpoint_baseline) == (
                b"original", 7, "identity", "timestamp", 0.125, None)
    writer = _writer(tmp_path)
    try:
        state = _state()
        plain = writer.snapshot_state_checkpoint(state, cycle=2, compact=False)
        assert plain.checkpoint_baseline is None
        assert json.loads(plain.payload) == state.to_dict()
        assert writer.snapshot_bytes(b"plain").checkpoint_baseline is None
        compact = writer.snapshot_state_checkpoint(state, cycle=2)
        with pytest.raises(FrozenInstanceError):
            compact.checkpoint_baseline.revision = 8
        with pytest.raises(TypeError, match="CheckpointBaseline"):
            ArtifactSnapshotHandle(b"bad", checkpoint_baseline=state)
    finally:
        writer.close(cancel_pending=True)


@pytest.mark.parametrize("options", [
    {"full": True}, {"full": False, "compact": False}, {"full": False, "base_state": "present"},
])
def test_baseline_argument_rejects_inapplicable_modes_before_reading_state(tmp_path, options):
    writer = _writer(tmp_path)
    try:
        baseline = checkpoint_baseline(_state())
        with pytest.raises(ValueError, match="base_baseline"):
            writer.snapshot_state_checkpoint(object(), cycle=0, base_baseline=baseline, **options)
        assert writer.pending_count == 0
        assert writer.summary()["timings"]["serialization"]["count"] == 0
    finally:
        writer.close(cancel_pending=True)


def test_compact_handle_does_not_retain_source_graph_and_payload_is_immutable(tmp_path):
    class NoCopyState(ModalAutoencoderTrainingState):
        def copy(self):
            raise AssertionError("baseline capture must not retain a state copy")

    writer = _writer(tmp_path)
    try:
        state = NoCopyState(decoded_embeddings={"sample": [-0.0, 0.125]})
        ref = weakref.ref(state)
        snapshot = writer.snapshot_state_checkpoint(state, cycle=0)
        original = snapshot.payload
        token = snapshot.checkpoint_baseline
        state.decoded_embeddings["sample"][1] = 99.0
        del state
        gc.collect()
        assert ref() is None
        assert snapshot.payload == original
        assert snapshot.checkpoint_baseline is token
        loaded = deserialize_checkpoint(original)
        assert loaded.state.decoded_embeddings["sample"] == [-0.0, 0.125]
        assert snapshot.checkpoint_baseline.state_digest == loaded.manifest.state_digest
    finally:
        writer.close(cancel_pending=True)


@pytest.mark.parametrize("mode", ["full", "legacy_delta", "baseline_delta"])
def test_source_revision_change_during_capture_still_rejected(tmp_path, monkeypatch, mode):
    writer = _writer(tmp_path)
    base, state = _state(), _state()
    state.applied_todo_ids.append("change")
    options = {}
    function = "serialize_checkpoint_snapshot"
    if mode == "legacy_delta":
        options = {"full": False, "base_state": base}
        function = "serialize_delta_snapshot"
    elif mode == "baseline_delta":
        options = {"full": False, "base_baseline": checkpoint_baseline(base)}
        function = "serialize_delta_from_baseline"
    original = getattr(writer_module, function)

    def serialize_then_mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        state.applied_todo_ids.append("concurrent-mutation")
        return result

    monkeypatch.setattr(writer_module, function, serialize_then_mutate)
    try:
        with pytest.raises(ConcurrentArtifactMutationError, match="state mutated"):
            writer.snapshot_state_checkpoint(state, cycle=1, **options)
        assert writer.pending_count == 0
    finally:
        writer.close(cancel_pending=True)


def test_legacy_base_revision_change_during_delta_capture_still_rejected(tmp_path, monkeypatch):
    writer = _writer(tmp_path)
    base, state = _state(), _state()
    state.applied_todo_ids.append("change")
    original = writer_module.serialize_delta_snapshot

    def serialize_then_mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        base.applied_todo_ids.append("concurrent-base-mutation")
        return result

    monkeypatch.setattr(writer_module, "serialize_delta_snapshot", serialize_then_mutate)
    try:
        with pytest.raises(ConcurrentArtifactMutationError, match="base state mutated"):
            writer.snapshot_state_checkpoint(state, cycle=1, full=False, base_state=base)
        assert writer.pending_count == 0
    finally:
        writer.close(cancel_pending=True)


def test_rejected_delta_enqueue_retains_token_and_retry_replays_exact_chain(tmp_path):
    writer = _writer(tmp_path, queue_capacity=1, backpressure_timeout_seconds=0.01)
    checkpoint, deltas = tmp_path / "state.checkpoint", tmp_path / "state.deltas"
    state = _state()
    try:
        full = writer.snapshot_state_checkpoint(state, cycle=0)
        initial = writer.write_state_checkpoint(checkpoint, full, cycle=0, compact=True)
        baseline = full.checkpoint_baseline
        state.applied_todo_ids.append("accepted-later")
        delta = writer.snapshot_state_checkpoint(state, cycle=1, full=False, base_baseline=baseline)
        with pytest.raises(AsyncArtifactBackpressureTimeout):
            writer.write_state_checkpoint(deltas, delta, cycle=1, full=False, compact=True, timeout=0.01)
        assert full.checkpoint_baseline is baseline
        assert baseline.revision == full.revision < delta.checkpoint_baseline.revision
        assert writer.pending_count == 1
        assert not deltas.exists()
        writer.start()
        initial.result(timeout=3)
        retry = writer.snapshot_state_checkpoint(state, cycle=1, full=False, base_baseline=baseline)
        assert retry.payload == delta.payload
        writer.write_state_checkpoint(deltas, retry, cycle=1, full=False, compact=True, wait=True)
        state.feature_embedding_weights.pop("obsolete")
        final = writer.snapshot_state_checkpoint(state, cycle=2, full=False,
                                                 base_baseline=retry.checkpoint_baseline)
        writer.write_state_checkpoint(deltas, final, cycle=2, full=False, compact=True, wait=True)
        loaded = load_checkpoint(checkpoint, delta_path=deltas, recover=False)
        assert loaded.state.to_dict() == state.to_dict()
        assert loaded.state.state_revision == state.state_revision == final.checkpoint_baseline.revision
        assert loaded.applied_delta_count == 2
        assert checkpoint.read_bytes() == full.payload
    finally:
        writer.close(cancel_pending=True)


def test_failed_delta_write_retains_existing_spool_format_and_replays_without_token(tmp_path, monkeypatch):
    writer = _writer(tmp_path)
    checkpoint, deltas = tmp_path / "state.checkpoint", tmp_path / "state.deltas"
    state = _state()
    full = writer.snapshot_state_checkpoint(state, cycle=0)
    checkpoint.write_bytes(full.payload)
    state.applied_todo_ids.append("pending-delta")
    delta = writer.snapshot_state_checkpoint(state, cycle=1, full=False,
                                              base_baseline=full.checkpoint_baseline)

    def fail_after_spooling(*args, **kwargs):
        raise OSError("synthetic destination failure")

    monkeypatch.setattr(writer, "_apply_manifest", fail_after_spooling)
    try:
        future = writer.write_state_checkpoint(deltas, delta, cycle=1, full=False, compact=True)
        writer.start()
        with pytest.raises(OSError, match="synthetic destination failure"):
            future.result(timeout=3)
        assert writer.wait_until_idle(timeout=3)
        assert writer.summary()["failed_count"] == 1
        [manifest_path] = (tmp_path / "spool").glob("*.manifest.json")
        manifest = json.loads(manifest_path.read_text())
        assert "checkpoint_baseline" not in manifest
        assert "checkpoint_baseline" not in manifest["metadata"]
        assert Path(manifest["payload_path"]).read_bytes() == delta.payload
        assert manifest["checksum"] == hashlib.sha256(delta.payload).hexdigest()
        assert not deltas.exists()
    finally:
        writer.close(cancel_pending=True)
    recovered = _writer(tmp_path)
    try:
        receipts = recovered.replay_crash_artifacts()
        assert len(receipts) == 1 and receipts[0].replayed is True
        assert recovered.replay_crash_artifacts() == []
        loaded = load_checkpoint(checkpoint, delta_path=deltas, recover=False)
        assert loaded.state.to_dict() == state.to_dict()
        assert loaded.state.state_revision == delta.checkpoint_baseline.revision
        assert loaded.applied_delta_count == 1
    finally:
        recovered.close(cancel_pending=True)
