"""Datasets bridge integration tests, including complete lineage propagation."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ipfs_accelerate_py.voice_jobs.contracts import (
    ArtifactDescriptor,
    VoiceJobResult,
)
from ipfs_datasets_py.ml.accelerate_integration.voice_jobs import (
    VoiceJobBridge,
    VoiceJobConflictError,
    VoiceJobReceiptError,
    jobs_from_voice_workset,
    submit_voice_workset,
)
from ipfs_datasets_py.voice.schema import sha256_text
from ipfs_datasets_py.voice.workset import (
    AudioArtifactDescriptor,
    AudioWorkItem,
    AudioWorkManifest,
    AudioWorkOperation,
    AudioWorkReason,
    VoiceAudioWorkset,
)


def _generated_audio_workset() -> VoiceAudioWorkset:
    common = {
        "reason": AudioWorkReason.MISSING,
        "subject_id": "response:welcome",
        "subject_schema_version": "abby_voice_response_v2",
        "spoken_text": "Welcome to Abby.",
        "text_sha256": sha256_text("Welcome to Abby."),
        "locale": "en-US",
        "source_manifest_id": "source-manifest:sha256:" + "a" * 64,
        "policy_id": "voice-policy:sha256:" + "b" * 64,
    }
    tts = AudioWorkItem(operation=AudioWorkOperation.TTS, **common)
    asr = AudioWorkItem(
        operation=AudioWorkOperation.ASR,
        depends_on=(tts.work_id,),
        **common,
    )
    validation = AudioWorkItem(
        operation=AudioWorkOperation.VALIDATE,
        depends_on=(asr.work_id,),
        **common,
    )
    return VoiceAudioWorkset(
        tts_manifest=AudioWorkManifest(AudioWorkOperation.TTS, (tts,)),
        asr_manifest=AudioWorkManifest(AudioWorkOperation.ASR, (asr,)),
        validation_manifest=AudioWorkManifest(
            AudioWorkOperation.VALIDATE,
            (validation,),
        ),
        source_manifest_id=common["source_manifest_id"],
        policy_id=common["policy_id"],
    )


def _existing_audio_workset() -> VoiceAudioWorkset:
    common = {
        "reason": AudioWorkReason.EXPLICIT_REVALIDATION,
        "subject_id": "response:existing",
        "subject_schema_version": "abby_voice_response_v2",
        "spoken_text": "Existing audio.",
        "text_sha256": sha256_text("Existing audio."),
        "locale": "en-US",
        "source_manifest_id": "source-manifest:sha256:" + "1" * 64,
        "policy_id": "voice-policy:sha256:" + "2" * 64,
        "audio": AudioArtifactDescriptor(
            audio_id="audio:existing",
            content_sha256="3" * 64,
            byte_length=512,
            media_type="audio/wav",
            uri="ipfs://bafybeigdyrzt/existing.wav",
        ),
    }
    asr = AudioWorkItem(operation=AudioWorkOperation.ASR, **common)
    validation = AudioWorkItem(
        operation=AudioWorkOperation.VALIDATE,
        depends_on=(asr.work_id,),
        **common,
    )
    return VoiceAudioWorkset(
        tts_manifest=AudioWorkManifest(AudioWorkOperation.TTS),
        asr_manifest=AudioWorkManifest(AudioWorkOperation.ASR, (asr,)),
        validation_manifest=AudioWorkManifest(
            AudioWorkOperation.VALIDATE,
            (validation,),
        ),
        source_manifest_id=common["source_manifest_id"],
        policy_id=common["policy_id"],
    )


def _assert_lineage_propagation(workset: VoiceAudioWorkset, jobs) -> None:
    """Prove lineage propagation from each G013 manifest into each G014 job."""

    items = workset.items
    manifests = (
        workset.tts_manifest,
        workset.asr_manifest,
        workset.validation_manifest,
    )
    assert len(jobs) == len(items) == len(manifests)
    task_id_by_work_id: dict[str, str] = {}
    for item, manifest, job in zip(items, manifests, jobs, strict=True):
        lineage = job.lineage
        expected_dependencies = {
            task_id_by_work_id[dependency] for dependency in item.depends_on
        }
        if getattr(job, "source_task_id", ""):
            expected_dependencies.add(job.source_task_id)
        assert lineage.workset_id == workset.workset_id
        assert lineage.source_manifest_id == workset.source_manifest_id
        assert lineage.policy_id == workset.policy_id
        assert lineage.manifest_id == manifest.manifest_id
        assert lineage.work_item_id == item.work_id
        assert lineage.subject_id == item.subject_id
        assert lineage.subject_schema_version == item.subject_schema_version
        assert lineage.depends_on_task_ids == tuple(sorted(expected_dependencies))
        assert lineage.task_id == job.task_id
        assert job.to_payload()["lineage"] == job.to_payload()["_lineage"]
        task_id_by_work_id[item.work_id] = job.task_id


def test_jobs_from_workset_preserve_complete_lineage_and_dependency_dag():
    workset = _generated_audio_workset()
    jobs = jobs_from_voice_workset(workset)

    _assert_lineage_propagation(workset, jobs)
    assert [job.task_type for job in jobs] == [
        "voice.tts",
        "voice.asr",
        "voice.audio-validate",
    ]
    assert jobs[1].source_task_id == jobs[0].task_id
    assert jobs[2].source_task_id == jobs[0].task_id
    assert jobs[2].lineage.depends_on_task_ids == tuple(
        sorted((jobs[0].task_id, jobs[1].task_id))
    )


def test_existing_audio_descriptor_crosses_bridge_without_bytes_or_local_path():
    jobs = jobs_from_voice_workset(_existing_audio_workset())

    assert len(jobs) == 2
    assert jobs[0].source_task_id == ""
    assert jobs[1].source_task_id == ""
    for job in jobs:
        assert job.source_audio == ArtifactDescriptor(
            uri="ipfs://bafybeigdyrzt/existing.wav",
            sha256="3" * 64,
            size_bytes=512,
            media_type="audio/wav",
        )
        payload = json.dumps(job.to_payload(), sort_keys=True)
        assert "audio_bytes" not in payload
        assert "audio_base64" not in payload
        assert "file://" not in payload


def test_canonical_duckdb_bridge_integration_is_submit_once_and_ingests_lineage(
    tmp_path,
):
    """True datasets bridge integration test over the canonical DuckDB queue."""

    pytest.importorskip("duckdb")
    from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue

    queue = TaskQueue(str(tmp_path / "voice-jobs.duckdb"))
    bridge = VoiceJobBridge(queue=queue, poll_interval_s=0.001)
    workset = _generated_audio_workset()
    jobs = jobs_from_voice_workset(workset)

    first = submit_voice_workset(workset, bridge=bridge)
    second = submit_voice_workset(workset, bridge=bridge)

    assert first.task_ids_by_work_item == second.task_ids_by_work_item
    assert all(not receipt.replayed for receipt in first.jobs)
    assert all(receipt.replayed for receipt in second.jobs)
    rows = queue.list(task_types=["voice.tts", "voice.asr", "voice.audio-validate"])
    assert len(rows) == 3
    assert {row["task_id"] for row in rows} == {job.task_id for job in jobs}
    _assert_lineage_propagation(
        workset,
        [jobs_from_voice_workset(workset)[index] for index in range(3)],
    )

    serialized_rows = json.dumps(rows, sort_keys=True)
    for forbidden in (
        "audio_base64",
        "audio_bytes",
        "base64_audio",
        "data:audio",
        "file://",
        "/tmp/",
        "private_transcript",
    ):
        assert forbidden not in serialized_rows

    # The bridge fails closed if an existing deterministic ID resolves to
    # different physical work, without widening this objective into TaskQueue.
    class ConflictingQueue:
        def get(self, task_id):
            return {
                "task_id": task_id,
                "task_type": jobs[0].task_type,
                "model_name": jobs[0].model_name,
                "payload": {**jobs[0].to_payload(), "locale": "fr-FR"},
                "status": "queued",
            }

        def submit(self, **_kwargs):
            raise AssertionError("conflicting content must not be submitted")

        def cancel(self, **_kwargs):
            return False

    with pytest.raises(VoiceJobConflictError, match="different canonical content"):
        VoiceJobBridge(queue=ConflictingQueue()).submit(jobs[0])

    artifact = ArtifactDescriptor(
        uri="ipfs://bafybeigdyrzt/audio.wav",
        sha256="c" * 64,
        size_bytes=128,
    )
    result = VoiceJobResult.from_job(
        jobs[0],
        artifacts=(artifact,),
        quality_metrics={"duration_ms": 1200},
        provider_receipt={"provider_request_id_sha256": "d" * 64},
    )
    assert queue.complete(
        task_id=jobs[0].task_id,
        status="completed",
        result=result.to_payload(),
    )
    waited = bridge.wait(jobs[0].task_id, timeout_s=0.1)
    assert waited is not None
    assert waited["status"] == "completed"
    ingested = bridge.ingest_receipt(jobs[0].task_id)
    assert ingested.task_id == jobs[0].task_id
    assert ingested.lineage.to_dict() == jobs[0].lineage.to_dict()
    assert ingested.artifacts == (artifact,)

    assert bridge.cancel(jobs[1].task_id, reason="test cancellation")
    assert bridge.status(jobs[1].task_id)["status"] == "cancelled"

    mismatched_result = VoiceJobResult.from_job(jobs[0])
    assert queue.complete(
        task_id=jobs[2].task_id,
        status="completed",
        result=mismatched_result.to_payload(),
    )
    with pytest.raises(VoiceJobReceiptError, match="does not match"):
        bridge.ingest_receipt(jobs[2].task_id)
    queue.close()


def test_canonical_duckdb_bridge_concurrent_replay_creates_one_row(tmp_path):
    pytest.importorskip("duckdb")
    from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue

    queue_path = str(tmp_path / "concurrent-voice-jobs.duckdb")
    queues = (TaskQueue(queue_path), TaskQueue(queue_path))
    bridges = tuple(VoiceJobBridge(queue=queue) for queue in queues)
    job = jobs_from_voice_workset(_generated_audio_workset())[0]
    barrier = threading.Barrier(2)

    def submit(bridge):
        barrier.wait()
        return bridge.submit(job)

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = tuple(executor.map(submit, bridges))

    assert sorted(receipt.replayed for receipt in receipts) == [False, True]
    assert len(queues[0].list(task_types=[job.task_type])) == 1
    for queue in queues:
        queue.close()


def test_receipt_ingestion_rejects_queue_and_result_status_mismatch():
    job = jobs_from_voice_workset(_generated_audio_workset())[0]
    result = VoiceJobResult.from_job(job, status="completed")

    class MismatchedStatusQueue:
        def get(self, task_id):
            return {
                "task_id": task_id,
                "task_type": job.task_type,
                "model_name": job.model_name,
                "payload": job.to_payload(),
                "status": "failed",
                "result": result.to_payload(),
            }

        def submit(self, **_kwargs):
            raise AssertionError("receipt ingestion must not submit")

        def cancel(self, **_kwargs):
            return False

    bridge = VoiceJobBridge(queue=MismatchedStatusQueue())
    with pytest.raises(VoiceJobReceiptError, match="does not match"):
        bridge.ingest_receipt(job.task_id)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("task_id", "f" * 64),
        ("task_type", "voice.asr"),
        ("model_name", "different-model"),
    ),
)
def test_receipt_ingestion_binds_outer_queue_envelope(field, value):
    job = jobs_from_voice_workset(_generated_audio_workset())[0]
    result = VoiceJobResult.from_job(job)
    row = {
        "task_id": job.task_id,
        "task_type": job.task_type,
        "model_name": job.model_name,
        "payload": job.to_payload(),
        "status": "completed",
        "result": result.to_payload(),
    }
    row[field] = value

    class TamperedEnvelopeQueue:
        def get(self, _task_id):
            return row

        def submit(self, **_kwargs):
            raise AssertionError("receipt ingestion must not submit")

        def cancel(self, **_kwargs):
            return False

    with pytest.raises(VoiceJobReceiptError, match="does not match"):
        VoiceJobBridge(queue=TamperedEnvelopeQueue()).ingest_receipt(job.task_id)


def test_receipt_ingestion_accepts_verified_worker_result_envelope():
    job = jobs_from_voice_workset(_generated_audio_workset())[0]
    canonical = VoiceJobResult.from_job(job).to_payload()
    worker_id = "abby-voice-worker-1"
    result_payload = {
        **canonical,
        "executor_worker_id": worker_id,
        "logs": [
            {
                "message": "voice job completed",
                "stream": "stdout",
                "ts": 1_721_000_001.0,
            }
        ],
        "model_id": job.model_name,
        "progress": {
            "heartbeat_ts": 1_721_000_000.5,
            "phase": "completed",
            "task_type": job.task_type,
            "ts": 1_721_000_000.0,
            "worker_id": worker_id,
        },
        "session_id": "abby-voice-canary",
    }
    result_payload["lineage"] = {
        **canonical["lineage"],
        "model_id": job.model_name,
    }
    row = {
        "assigned_worker": worker_id,
        "model_name": job.model_name,
        "payload": job.to_payload(),
        "result": result_payload,
        "status": "completed",
        "task_id": job.task_id,
        "task_type": job.task_type,
    }

    class WorkerEnvelopeQueue:
        def get(self, _task_id):
            return row

        def submit(self, **_kwargs):
            raise AssertionError("receipt ingestion must not submit")

        def cancel(self, **_kwargs):
            return False

    ingested = VoiceJobBridge(queue=WorkerEnvelopeQueue()).ingest_receipt(
        job.task_id
    )
    assert ingested.to_payload() == canonical


@pytest.mark.parametrize(
    "location",
    ("result", "lineage", "progress"),
)
def test_receipt_ingestion_rejects_unknown_worker_envelope_fields(location):
    job = jobs_from_voice_workset(_generated_audio_workset())[0]
    result_payload = VoiceJobResult.from_job(job).to_payload()
    if location == "result":
        result_payload["unreviewed_extension"] = True
    elif location == "lineage":
        result_payload["lineage"] = {
            **result_payload["lineage"],
            "unreviewed_extension": True,
        }
    else:
        result_payload["progress"] = {
            "task_type": job.task_type,
            "unreviewed_extension": True,
        }
    row = {
        "model_name": job.model_name,
        "payload": job.to_payload(),
        "result": result_payload,
        "status": "completed",
        "task_id": job.task_id,
        "task_type": job.task_type,
    }

    class ExtendedEnvelopeQueue:
        def get(self, _task_id):
            return row

        def submit(self, **_kwargs):
            raise AssertionError("receipt ingestion must not submit")

        def cancel(self, **_kwargs):
            return False

    with pytest.raises(VoiceJobReceiptError, match="invalid voice receipt"):
        VoiceJobBridge(queue=ExtendedEnvelopeQueue()).ingest_receipt(job.task_id)


@pytest.mark.parametrize(
    "binding",
    (
        "model_id",
        "lineage_model_id",
        "progress_task_type",
        "executor_worker_id",
        "progress_worker_id",
    ),
)
def test_receipt_ingestion_rejects_mismatched_worker_envelope_bindings(binding):
    job = jobs_from_voice_workset(_generated_audio_workset())[0]
    result_payload = VoiceJobResult.from_job(job).to_payload()
    worker_id = "abby-voice-worker-1"
    result_payload.update(
        {
            "executor_worker_id": worker_id,
            "model_id": job.model_name,
            "progress": {
                "task_type": job.task_type,
                "worker_id": worker_id,
            },
        }
    )
    result_payload["lineage"] = {
        **result_payload["lineage"],
        "model_id": job.model_name,
    }
    assigned_worker = worker_id
    if binding == "model_id":
        result_payload["model_id"] = "different-model"
    elif binding == "lineage_model_id":
        result_payload["lineage"]["model_id"] = "different-model"
    elif binding == "progress_task_type":
        result_payload["progress"]["task_type"] = "voice.asr"
    elif binding == "executor_worker_id":
        result_payload["executor_worker_id"] = ""
    else:
        result_payload["progress"]["worker_id"] = "different-worker"
    row = {
        "assigned_worker": assigned_worker,
        "model_name": job.model_name,
        "payload": job.to_payload(),
        "result": result_payload,
        "status": "completed",
        "task_id": job.task_id,
        "task_type": job.task_type,
    }

    class MismatchedWorkerEnvelopeQueue:
        def get(self, _task_id):
            return row

        def submit(self, **_kwargs):
            raise AssertionError("receipt ingestion must not submit")

        def cancel(self, **_kwargs):
            return False

    with pytest.raises(VoiceJobReceiptError, match="invalid voice receipt"):
        VoiceJobBridge(queue=MismatchedWorkerEnvelopeQueue()).ingest_receipt(
            job.task_id
        )


@pytest.mark.parametrize(
    "canonical_field",
    ("status", "task_id", "task_type", "lineage_task_id"),
)
def test_receipt_ingestion_rejects_canonical_result_tampering(canonical_field):
    job = jobs_from_voice_workset(_generated_audio_workset())[0]
    result_payload = VoiceJobResult.from_job(job).to_payload()
    if canonical_field == "status":
        result_payload["status"] = "cancelled"
    elif canonical_field == "task_id":
        result_payload["task_id"] = "f" * 64
    elif canonical_field == "task_type":
        result_payload["task_type"] = "voice.asr"
    else:
        result_payload["lineage"] = {
            **result_payload["lineage"],
            "task_id": "f" * 64,
        }
    row = {
        "model_name": job.model_name,
        "payload": job.to_payload(),
        "result": result_payload,
        "status": "completed",
        "task_id": job.task_id,
        "task_type": job.task_type,
    }

    class TamperedResultQueue:
        def get(self, _task_id):
            return row

        def submit(self, **_kwargs):
            raise AssertionError("receipt ingestion must not submit")

        def cancel(self, **_kwargs):
            return False

    with pytest.raises(VoiceJobReceiptError):
        VoiceJobBridge(queue=TamperedResultQueue()).ingest_receipt(job.task_id)


def test_receipt_ingestion_normalizes_non_mapping_payload_errors():
    job = jobs_from_voice_workset(_generated_audio_workset())[0]
    result = VoiceJobResult.from_job(job)

    class MalformedPayloadQueue:
        def get(self, task_id):
            return {
                "task_id": task_id,
                "task_type": job.task_type,
                "model_name": job.model_name,
                "payload": None,
                "status": "completed",
                "result": result.to_payload(),
            }

        def submit(self, **_kwargs):
            raise AssertionError("receipt ingestion must not submit")

        def cancel(self, **_kwargs):
            return False

    with pytest.raises(VoiceJobReceiptError, match="structured request payload"):
        VoiceJobBridge(queue=MalformedPayloadQueue()).ingest_receipt(job.task_id)
