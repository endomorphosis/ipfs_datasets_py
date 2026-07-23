"""Regression tests for compact modal-autoencoder checkpoints and deltas."""

from __future__ import annotations

import json
import math
import os
import random
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.async_artifact_writer import (
    ArtifactFsyncPolicy,
    AsyncArtifactWriter,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (
    CHECKPOINT_MAGIC,
    DELTA_MAGIC,
    MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION,
    CheckpointCorruptionError,
    CheckpointLineageError,
    append_delta_segment,
    deserialize_checkpoint,
    iter_delta_segments,
    load_checkpoint,
    quantize_float,
    serialize_checkpoint,
    serialize_delta,
    write_checkpoint_atomic,
)


METRIC_LINEAGE = {
    "metric_schema": "legal-ir-checkpoint-test-metrics-v1",
    "suite": "canonical",
}


def _canonical_state(rows: int = 800, width: int = 64) -> ModalAutoencoderTrainingState:
    randomizer = random.Random(103)
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={
            f"sample-{row:05d}": [
                randomizer.uniform(-1.0, 1.0) for _ in range(width)
            ]
            for row in range(rows)
        },
        family_logits={
            f"sample-{row:05d}": {
                family: randomizer.uniform(-2.0, 2.0)
                for family in ("cec", "deontic", "flogic", "kg", "tdfol")
            }
            for row in range(rows)
        },
        feature_embedding_weights={
            f"feature-{row:04d}": [
                math.sin((row + 1) * (column + 1) / 37.0)
                for column in range(width)
            ]
            for row in range(100)
        },
        feature_family_logits={
            "shall": {"deontic": 0.875, "kg": -0.125},
            "unless": {"cec": 0.625, "tdfol": 0.375},
        },
        proof_auxiliary_head_logits={
            "obligation_family": {
                "__global__": {"mandatory": 0.75, "permissive": -0.25}
            }
        },
        proof_feedback_version_fingerprint="hammer-toolchain-v1",
        applied_proof_feedback_ids=["proof-a"],
        applied_leanstral_guidance_ids=["guidance-a"],
        applied_todo_ids=["todo-a"],
    )
    # Give the fixture a meaningful durable operational revision.
    state.legal_ir_view_logits["deontic"] = 0.25
    return state


def test_full_checkpoint_is_typed_checksummed_and_sixty_percent_smaller() -> None:
    state = _canonical_state()
    encoded = serialize_checkpoint(state, metric_lineage=METRIC_LINEAGE)
    loaded = deserialize_checkpoint(
        encoded,
        expected_state_schema_version=MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
        expected_metric_lineage=METRIC_LINEAGE,
        expected_revision=state.state_revision,
    )

    assert encoded.startswith(CHECKPOINT_MAGIC)
    assert loaded.manifest.schema_version == MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION
    assert loaded.manifest.table_count >= 4
    assert loaded.manifest.numeric_value_count > 50_000
    assert loaded.manifest.float_precision == "float64"
    assert loaded.state.to_dict() == state.to_dict()
    assert loaded.state.state_revision == state.state_revision
    assert loaded.state.state_identity(metric_lineage=METRIC_LINEAGE) == (
        state.state_identity(metric_lineage=METRIC_LINEAGE)
    )
    json_size = len((state.to_json() + "\n").encode("utf-8"))
    assert len(encoded) <= int(json_size * 0.40)


def test_float32_round_trip_is_exact_at_declared_precision() -> None:
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample": [0.123456789, -0.987654321, 1.0 / 3.0]},
        family_logits={"sample": {"deontic": 0.777777777}},
    )
    loaded = deserialize_checkpoint(
        serialize_checkpoint(state, float_precision="float32")
    )

    expected = [quantize_float(value, "float32") for value in state.decoded_embeddings["sample"]]
    assert loaded.manifest.float_precision == "float32"
    assert loaded.state.decoded_embeddings["sample"] == expected
    assert loaded.state.family_logits["sample"]["deontic"] == quantize_float(
        state.family_logits["sample"]["deontic"], "float32"
    )


def test_current_json_state_remains_loadable(tmp_path: Path) -> None:
    state = _canonical_state(rows=2, width=4)
    path = tmp_path / "legacy.state.json"
    state.save_json(path)

    loaded = load_checkpoint(
        path,
        expected_state_schema_version=MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
        expected_metric_lineage=METRIC_LINEAGE,
    )

    assert loaded.format == "json"
    assert loaded.manifest.metadata["legacy_json"] is True
    assert loaded.state.to_dict() == state.to_dict()


@pytest.mark.parametrize("location", [80, -1])
def test_checkpoint_rejects_manifest_and_payload_corruption(location: int) -> None:
    encoded = bytearray(serialize_checkpoint(_canonical_state(rows=2, width=4)))
    encoded[location] ^= 0x01

    with pytest.raises(CheckpointCorruptionError, match="checksum"):
        deserialize_checkpoint(bytes(encoded))


def test_delta_log_applies_only_touched_components_and_verifies_revision(
    tmp_path: Path,
) -> None:
    base = _canonical_state(rows=4, width=8)
    checkpoint_path = tmp_path / "state.checkpoint"
    delta_path = tmp_path / "state.deltas"
    write_checkpoint_atomic(
        checkpoint_path,
        base,
        metric_lineage=METRIC_LINEAGE,
    )

    changed = base.copy()
    changed._state_identity_tracker.restore_revision(base.state_revision)
    changed.feature_embedding_weights["feature-0000"][2] = 0.8125
    changed.applied_todo_ids.append("todo-b")
    segment = serialize_delta(base, changed, metric_lineage=METRIC_LINEAGE)
    assert segment.startswith(DELTA_MAGIC)
    [(manifest, _payload)], _offset, recovered = iter_delta_segments(segment)
    assert recovered == 0
    assert set(manifest.changed_components) == {
        "applied_todo_ids",
        "feature_embedding_weights",
    }
    append_delta_segment(delta_path, segment)

    loaded = load_checkpoint(
        checkpoint_path,
        delta_path=delta_path,
        expected_metric_lineage=METRIC_LINEAGE,
        expected_revision=changed.state_revision,
    )
    assert loaded.applied_delta_count == 1
    assert loaded.state.to_dict() == changed.to_dict()
    assert loaded.state.state_revision == changed.state_revision


def test_metadata_only_unchanged_delta_is_bounded_and_idempotent(tmp_path: Path) -> None:
    state = _canonical_state(rows=20, width=16)
    delta_path = tmp_path / "state.deltas"
    segment = serialize_delta(
        state,
        state,
        metadata={"cycle": 7, "run_id": "bounded-test"},
    )
    [(manifest, _payload)], _offset, _recovered = iter_delta_segments(segment)

    assert manifest.changed_components == ()
    assert manifest.numeric_value_count == 0
    assert len(segment) < 8_192
    assert append_delta_segment(delta_path, segment) == len(segment)
    assert append_delta_segment(delta_path, segment) == 0
    assert delta_path.stat().st_size == len(segment)


def test_interrupted_final_delta_is_truncated_and_prior_segments_survive(
    tmp_path: Path,
) -> None:
    base = _canonical_state(rows=3, width=8)
    checkpoint_path = tmp_path / "state.checkpoint"
    delta_path = tmp_path / "state.deltas"
    write_checkpoint_atomic(checkpoint_path, base)
    changed = base.copy()
    changed._state_identity_tracker.restore_revision(base.state_revision)
    changed.legal_ir_view_logits["deontic"] = 0.875
    complete = serialize_delta(base, changed)
    later = changed.copy()
    later._state_identity_tracker.restore_revision(changed.state_revision)
    later.legal_ir_view_logits["kg"] = -0.25
    torn = serialize_delta(changed, later)
    delta_path.write_bytes(complete + torn[: len(torn) // 2])

    loaded = load_checkpoint(checkpoint_path, delta_path=delta_path, recover=True)

    assert loaded.applied_delta_count == 1
    assert loaded.recovered_tail_bytes == len(torn) // 2
    assert loaded.state.to_dict() == changed.to_dict()
    assert delta_path.read_bytes() == complete


def test_delta_rejects_wrong_metric_lineage_and_revision_gap(tmp_path: Path) -> None:
    base = _canonical_state(rows=2, width=4)
    checkpoint_path = tmp_path / "state.checkpoint"
    delta_path = tmp_path / "state.deltas"
    write_checkpoint_atomic(checkpoint_path, base, metric_lineage=METRIC_LINEAGE)
    changed = base.copy()
    changed._state_identity_tracker.restore_revision(base.state_revision)
    changed.legal_ir_view_logits["kg"] = 0.5
    delta_path.write_bytes(
        serialize_delta(
            base,
            changed,
            metric_lineage={"metric_schema": "wrong"},
        )
    )

    with pytest.raises(CheckpointLineageError, match="metric lineage"):
        load_checkpoint(
            checkpoint_path,
            delta_path=delta_path,
            expected_metric_lineage=METRIC_LINEAGE,
        )

    delta_path.write_bytes(
        serialize_delta(
            base,
            changed,
            metric_lineage=METRIC_LINEAGE,
            base_revision=base.state_revision + 1,
            revision=changed.state_revision + 1,
        )
    )
    with pytest.raises(CheckpointLineageError, match="revision"):
        load_checkpoint(
            checkpoint_path,
            delta_path=delta_path,
            expected_metric_lineage=METRIC_LINEAGE,
        )


def test_atomic_checkpoint_ignores_interrupted_temporary_file(tmp_path: Path) -> None:
    state = _canonical_state(rows=2, width=4)
    path = tmp_path / "state.checkpoint"
    first = write_checkpoint_atomic(path, state)
    interrupted = path.with_name(f".{path.name}.tmp-{os.getpid()}-interrupted")
    interrupted.write_bytes(b"partial-new-checkpoint")

    loaded = load_checkpoint(path)

    assert loaded.manifest.checkpoint_id == first.checkpoint_id
    assert loaded.state.to_dict() == state.to_dict()


def test_async_writer_compact_checkpoint_and_delta_round_trip(tmp_path: Path) -> None:
    base = _canonical_state(rows=5, width=8)
    changed = base.copy()
    changed._state_identity_tracker.restore_revision(base.state_revision)
    changed.family_logits["sample-00000"]["deontic"] = -0.75
    checkpoint_path = tmp_path / "state.checkpoint"
    delta_path = tmp_path / "state.deltas"
    writer = AsyncArtifactWriter(
        tmp_path / "spool",
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    try:
        full_receipt = writer.write_state_checkpoint(
            checkpoint_path,
            base,
            cycle=1,
            metric_lineage=METRIC_LINEAGE,
            wait=True,
        )
        delta_receipt = writer.append_state_delta(
            delta_path,
            changed,
            base_state=base,
            cycle=2,
            metric_lineage=METRIC_LINEAGE,
            wait=True,
        )
    finally:
        writer.close(cancel_pending=True)

    assert full_receipt.metadata["compact"] is True
    assert delta_receipt.kind == "state_checkpoint_delta"
    assert checkpoint_path.read_bytes().startswith(CHECKPOINT_MAGIC)
    assert delta_path.read_bytes().startswith(DELTA_MAGIC)
    loaded = load_checkpoint(
        checkpoint_path,
        delta_path=delta_path,
        expected_metric_lineage=METRIC_LINEAGE,
    )
    assert loaded.state.to_dict() == changed.to_dict()


def test_async_compact_snapshot_is_immutable_after_enqueue(tmp_path: Path) -> None:
    state = _canonical_state(rows=2, width=4)
    expected = state.to_dict()
    writer = AsyncArtifactWriter(
        tmp_path / "spool",
        autostart=False,
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    try:
        future = writer.write_state_checkpoint(
            tmp_path / "state.checkpoint",
            state,
            cycle=3,
        )
        state.decoded_embeddings["sample-00000"][0] = 99.0
        writer.start()
        future.result(timeout=2.0)
        loaded = load_checkpoint(tmp_path / "state.checkpoint")
        assert loaded.state.to_dict() == expected
    finally:
        writer.close(cancel_pending=True)


def test_complete_delta_checksum_corruption_is_not_silently_recovered() -> None:
    state = _canonical_state(rows=2, width=4)
    segment = bytearray(serialize_delta(state, state))
    segment[-1] ^= 0x01

    with pytest.raises(CheckpointCorruptionError, match="checksum"):
        iter_delta_segments(bytes(segment), recover_truncated_tail=True)


def test_manifest_is_small_and_non_executable() -> None:
    state = _canonical_state(rows=10, width=8)
    encoded = serialize_checkpoint(state)
    # The fixed header stores the manifest length immediately after magic,
    # version, and flags.  It must remain bounded independently of table rows.
    manifest_length = int.from_bytes(encoded[12:16], "big")
    manifest = json.loads(encoded[88 : 88 + manifest_length])

    assert manifest_length < 4_096
    assert manifest["compression"] == "zlib"
    assert manifest["table_schema_version"].endswith("v1")
    assert b"pickle" not in encoded[: 88 + manifest_length].lower()
