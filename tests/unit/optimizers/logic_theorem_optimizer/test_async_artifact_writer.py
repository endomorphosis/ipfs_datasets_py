from __future__ import annotations

import json
import hashlib
import threading
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.async_artifact_writer import (
    ASYNC_ARTIFACT_WRITER_SCHEMA_VERSION,
    STATE_DELTA_SCHEMA_VERSION,
    ArtifactFsyncPolicy,
    AsyncArtifactBackpressureTimeout,
    AsyncArtifactWriter,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState,
)


def test_checkpoint_serialization_runs_on_worker_and_renames_atomically(
    tmp_path: Path,
) -> None:
    serialized = threading.Event()

    class ObservableState(ModalAutoencoderTrainingState):
        def copy(self) -> "ObservableState":
            copied = ObservableState(
                decoded_embeddings={
                    key: list(value)
                    for key, value in self.decoded_embeddings.items()
                },
                family_logits={
                    key: dict(value)
                    for key, value in self.family_logits.items()
                },
            )
            return copied

        def to_json(self) -> str:
            serialized.set()
            return super().to_json()

    writer = AsyncArtifactWriter(
        tmp_path / "spool",
        autostart=False,
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    try:
        state = ObservableState(decoded_embeddings={"sample-a": [0.1, 0.2]})
        future = writer.write_state_checkpoint(tmp_path / "state.json", state, cycle=3)

        assert not serialized.is_set()

        state.decoded_embeddings["sample-a"][0] = 99.0
        writer.start()
        receipt = future.result(timeout=2.0)

        assert serialized.is_set()
        assert receipt.kind == "state_checkpoint_full"
        assert receipt.checksum
        assert receipt.bytes_written > 0
        assert not list((tmp_path / "spool").glob("*.manifest.json"))
        payload = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert payload["decoded_embeddings"]["sample-a"] == [0.1, 0.2]
    finally:
        writer.close(cancel_pending=True)


def test_append_jsonl_uses_manifest_replay_without_duplicate_records(
    tmp_path: Path,
) -> None:
    spool = tmp_path / "spool"
    destination = tmp_path / "disagreements.jsonl"
    spool.mkdir()
    destination.write_text(
        json.dumps({"evidence_id": "already", "value": 1}) + "\n",
        encoding="utf-8",
    )
    payload_path = spool / "crashed.payload"
    lines = [
        json.dumps({"evidence_id": "already", "value": 1}, sort_keys=True),
        json.dumps({"evidence_id": "new", "value": 2}, sort_keys=True),
    ]
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    payload_path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    manifest_path = spool / "crashed.manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "append_jsonl": True,
                "checksum": checksum,
                "created_at": "2026-07-21T00:00:00+00:00",
                "dedupe_keys": ["evidence_id"],
                "kind": "disagreement_batch",
                "metadata": {"cycle": 7},
                "path": str(destination),
                "payload_path": str(payload_path),
                "schema_version": ASYNC_ARTIFACT_WRITER_SCHEMA_VERSION,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    writer = AsyncArtifactWriter(
        spool,
        autostart=False,
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    receipts = writer.replay_crash_artifacts()

    assert len(receipts) == 1
    assert receipts[0].replayed is True
    records = [
        json.loads(line)
        for line in destination.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["evidence_id"] for record in records] == ["already", "new"]
    assert not manifest_path.exists()
    assert not payload_path.exists()


def test_bounded_queue_applies_backpressure(tmp_path: Path) -> None:
    writer = AsyncArtifactWriter(
        tmp_path / "spool",
        autostart=False,
        backpressure_timeout_seconds=0.01,
        queue_capacity=1,
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    try:
        writer.write_json_atomic(tmp_path / "one.json", {"value": 1})
        with pytest.raises(AsyncArtifactBackpressureTimeout):
            writer.write_json_atomic(tmp_path / "two.json", {"value": 2}, timeout=0.01)
        summary = writer.summary()
        assert summary["backpressure_timeouts"] == 1
        assert summary["pending_count"] == 1
    finally:
        writer.close(wait=False, cancel_pending=True)


def test_state_delta_is_append_only_with_stable_schema(tmp_path: Path) -> None:
    writer = AsyncArtifactWriter(
        tmp_path / "spool",
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    try:
        receipt = writer.append_state_delta(
            tmp_path / "state-deltas.jsonl",
            {"cycle": 4, "decoded_embedding_count": 2},
            wait=True,
        )
        assert receipt.kind == "state_delta"
        [record] = [
            json.loads(line)
            for line in (tmp_path / "state-deltas.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert record["schema_version"] == STATE_DELTA_SCHEMA_VERSION
        assert record["cycle"] == 4
        assert record["delta_id"].startswith("lir-state-delta-")
    finally:
        writer.close(cancel_pending=True)
