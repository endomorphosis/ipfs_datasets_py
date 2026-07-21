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
    ArtifactWriteFuture,
    AsyncArtifactBackpressureTimeout,
    AsyncArtifactWriteError,
    AsyncArtifactWriter,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    export_canonical_state_disagreement_packets,
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


def test_nonblocking_disagreement_batch_returns_future_until_worker_commits(
    tmp_path: Path,
) -> None:
    writer = AsyncArtifactWriter(
        tmp_path / "spool",
        autostart=False,
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    try:
        future = writer.append_jsonl(
            tmp_path / "disagreements.jsonl",
            [{"evidence_id": "packet-a", "cycle": 1}],
            kind="disagreement_batch",
            dedupe_keys=("evidence_id",),
        )

        assert isinstance(future, ArtifactWriteFuture)
        assert not future.done()
        assert not (tmp_path / "disagreements.jsonl").exists()

        writer.start()
        receipt = future.result(timeout=2.0)

        assert receipt.kind == "disagreement_batch"
        assert receipt.bytes_written > 0
        assert receipt.checksum
        records = [
            json.loads(line)
            for line in (tmp_path / "disagreements.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert records == [{"cycle": 1, "evidence_id": "packet-a"}]
    finally:
        writer.close(cancel_pending=True)


def test_waited_disagreement_batch_is_durable_before_return(tmp_path: Path) -> None:
    writer = AsyncArtifactWriter(
        tmp_path / "spool",
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    try:
        receipt = writer.append_jsonl(
            tmp_path / "promotion-evidence.jsonl",
            [{"evidence_id": "promotion-a", "cycle": 5}],
            kind="promotion_disagreement_batch",
            dedupe_keys=("evidence_id",),
            wait=True,
        )

        assert receipt.kind == "promotion_disagreement_batch"
        assert receipt.replayed is False
        assert (tmp_path / "promotion-evidence.jsonl").exists()
        assert not list((tmp_path / "spool").glob("*.manifest.json"))
        assert not list((tmp_path / "spool").glob("*.payload"))
    finally:
        writer.close(cancel_pending=True)


def test_replay_updates_summary_and_removes_stale_temp_files(tmp_path: Path) -> None:
    spool = tmp_path / "spool"
    destination = tmp_path / "summary.json"
    spool.mkdir()
    stale_payload_tmp = spool / ".orphan.payload.tmp-123"
    stale_manifest_tmp = spool / ".orphan.manifest.json.tmp-123"
    stale_payload_tmp.write_text("stale", encoding="utf-8")
    stale_manifest_tmp.write_text("stale", encoding="utf-8")

    payload = json.dumps({"cycle": 9, "status": "ok"}, sort_keys=True).encode(
        "utf-8"
    ) + b"\n"
    payload_path = spool / "summary.payload"
    payload_path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    manifest_path = spool / "summary.manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "append_jsonl": False,
                "checksum": checksum,
                "created_at": "2026-07-21T00:00:00+00:00",
                "dedupe_keys": [],
                "kind": "summary",
                "metadata": {"cycle": 9},
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
    summary = writer.summary()

    assert len(receipts) == 1
    assert receipts[0].replayed is True
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "cycle": 9,
        "status": "ok",
    }
    assert summary["replayed_count"] == 1
    assert summary["bytes_written"] == len(payload)
    assert not stale_payload_tmp.exists()
    assert not stale_manifest_tmp.exists()
    assert not manifest_path.exists()
    assert not payload_path.exists()


def test_close_cancels_unstarted_pending_futures(tmp_path: Path) -> None:
    writer = AsyncArtifactWriter(
        tmp_path / "spool",
        autostart=False,
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    future = writer.write_json_atomic(tmp_path / "queued.json", {"value": 1})

    drained = writer.close(wait=False, cancel_pending=True)

    assert drained is True
    assert future.done()
    with pytest.raises(AsyncArtifactWriteError):
        future.result(timeout=0.01)
    assert writer.summary()["pending_count"] == 0


def test_runner_disagreement_export_enqueues_without_waiting_for_write(
    tmp_path: Path,
) -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall provide notice before denying a request.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    autoencoder.evaluate([sample], use_sample_memory=False)
    metrics = {
        "autoencoder_guidance_enabled": False,
        "cross_entropy_loss": 0.42,
        "cosine_similarity": 0.76,
        "evaluated_count": 1,
        "sample_count": 1,
        "sample_metric_records": [
            {
                "compiler_guidance_applied": False,
                "metric_sample_id": sample.sample_id,
                "metrics": {
                    "cross_entropy_loss": 0.42,
                    "cosine_similarity": 0.76,
                    "source_decompiled_text_embedding_cosine_loss": 0.24,
                    "source_decompiled_text_token_loss": 0.31,
                },
                "sample_id": sample.sample_id,
            }
        ],
    }
    writer = AsyncArtifactWriter(
        tmp_path / "spool",
        autostart=False,
        fsync_policy=ArtifactFsyncPolicy.disabled(),
    )
    try:
        report = export_canonical_state_disagreement_packets(
            artifact_writer=writer,
            autoencoder=autoencoder,
            compiler_ir_validation=metrics,
            compiler_ir_guided_validation={},
            cycle=2,
            export_mode="export",
            root=tmp_path,
            run_id="async-runner",
            samples=[sample],
            state=autoencoder.state,
            summary_path=tmp_path / "run.summary",
            validation_indices=[11],
            validation_mode="fixed_canary",
            evaluate_provers=False,
            wait_for_durable=False,
        )

        destination = tmp_path / "run.canonical-disagreements.jsonl"
        assert report["packet_count"] == 1
        assert report["writer_durable"] is False
        assert report["writer_future_id"].startswith("lir-artifact-")
        assert not destination.exists()

        writer.start()
        assert writer.wait_until_idle(timeout=2.0)
        records = [
            json.loads(line)
            for line in destination.read_text(encoding="utf-8").splitlines()
        ]
        assert records[0]["run_context"]["cycle"] == 2
        assert records[0]["run_context"]["frozen_canary"]["index"] == 11
    finally:
        writer.close(cancel_pending=True)
