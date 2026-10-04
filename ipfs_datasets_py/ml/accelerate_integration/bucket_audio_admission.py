"""Semantic admission for verified Abby bucket-audio revalidation receipts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any

from ipfs_accelerate_py.voice_jobs.contracts import (
    VoiceASRJob,
    VoiceAudioValidationJob,
    VoiceJobResult,
)

from ...voice.bucket_audio_recovery import (
    AbbyVoiceBucketAudioRecovery,
    BucketAudioRecoveryError,
    VerifiedBucketAudioRecord,
)
from ...voice.reconcile import (
    AudioDisposition,
    AudioDispositionReason,
    AudioDispositionStatus,
    AudioReconciliationResult,
    AudioReconciliationSubject,
    reconcile_voice_job_result,
)
from .bucket_audio import BucketAudioRevalidationBinding, BucketAudioRevalidationPlan


def _job_result_matches(job: Any, result: VoiceJobResult) -> bool:
    return bool(
        result.task_id == job.task_id
        and result.task_type == job.task_type
        and result.lineage.to_dict() == job.lineage.to_dict()
    )


def _verified_transcript(
    *,
    result: VoiceJobResult,
    transcript_bytes: bytes,
) -> str:
    if result.status != "completed" or result.task_type != "voice.asr":
        raise BucketAudioRecoveryError("ASR result is not completed")
    if len(result.artifacts) != 1:
        raise BucketAudioRecoveryError(
            "retained dataset ASR result requires exactly one transcript artifact"
        )
    artifact = result.artifacts[0]
    if not artifact.media_type.casefold().startswith("text/plain"):
        raise BucketAudioRecoveryError("ASR result artifact is not plain text")
    if (
        len(transcript_bytes) != artifact.size_bytes
        or sha256(transcript_bytes).hexdigest() != artifact.sha256
    ):
        raise BucketAudioRecoveryError(
            "ASR transcript bytes do not match their result descriptor"
        )
    try:
        transcript = transcript_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BucketAudioRecoveryError("ASR transcript must be UTF-8") from exc
    if not transcript.strip() or "\x00" in transcript:
        raise BucketAudioRecoveryError("ASR transcript must be non-empty text")
    return transcript


def _source_ref(record: VerifiedBucketAudioRecord) -> str:
    return f"recovery:{record.record_id}"


def _incomplete_disposition(
    *,
    record: VerifiedBucketAudioRecord,
    binding: BucketAudioRevalidationBinding,
    policy_identity: str,
    reason: AudioDispositionReason,
    detail: str,
    task_id: str = "",
    work_item_id: str = "",
    retryable: bool = True,
) -> AudioDisposition:
    """Emit one per-row disposition without aborting the admission batch."""

    status = (
        AudioDispositionStatus.RETRYABLE
        if retryable
        else AudioDispositionStatus.QUARANTINED
    )
    return AudioDisposition(
        source_ref=_source_ref(record),
        source_sha256=record.raw_sha256,
        status=status,
        reason=reason,
        subject_id=record.response_id,
        task_id=task_id,
        work_item_id=work_item_id or binding.validation_work_id,
        artifact_sha256=record.raw_sha256,
        policy_identity=policy_identity,
        retryable=retryable,
        detail=detail,
    )


def admit_bucket_audio_revalidation(
    recovery: AbbyVoiceBucketAudioRecovery,
    revalidation_plan: BucketAudioRevalidationPlan,
    *,
    jobs: Sequence[Any],
    results_by_task_id: Mapping[str, VoiceJobResult],
    transcript_bytes_by_asr_task_id: Mapping[str, bytes],
    audio_bytes_by_sha256: Mapping[str, bytes],
    license_id: str = "MIT",
    consent_status: str = "not_required",
) -> AudioReconciliationResult:
    """Bind ASR and validation receipts to recovered bytes and admit safe rows.

    The caller must obtain ``results_by_task_id`` through the strict
    ``VoiceJobBridge.ingest_receipt`` path. This function then proves that each
    ASR and validation request names the same recovered raw SHA-256, verifies
    the retained transcript artifact bytes, and invokes the canonical dataset
    reconciler. Raw ASR text is used only in memory.

    Incomplete or missing receipts produce **per-row** retryable/quarantine
    dispositions so successful siblings still admit. True integrity failures
    (hash/size mismatch, plan/recovery binding errors, job payload corruption)
    still raise and fail closed.
    """

    if not isinstance(recovery, AbbyVoiceBucketAudioRecovery):
        raise TypeError("recovery must be an AbbyVoiceBucketAudioRecovery")
    if not isinstance(revalidation_plan, BucketAudioRevalidationPlan):
        raise TypeError("revalidation_plan must be a BucketAudioRevalidationPlan")
    if revalidation_plan.recovery_id != recovery.recovery_id:
        raise BucketAudioRecoveryError("revalidation plan does not bind recovery")
    if not isinstance(license_id, str) or not license_id.strip():
        raise ValueError("license_id must be non-empty")
    if not isinstance(consent_status, str) or not consent_status.strip():
        raise ValueError("consent_status must be non-empty")

    records = {item.response_id: item for item in recovery.records}
    jobs_by_work_id = {job.lineage.work_item_id: job for job in jobs}
    linked_audio = []
    provenance = []
    dispositions = []
    item_reports: list[dict[str, Any]] = []
    policy_identity = revalidation_plan.policy.identity

    for binding in revalidation_plan.bindings:
        record = records.get(binding.response_id)
        if record is None or record.record_id != binding.record_id:
            raise BucketAudioRecoveryError(
                f"binding {binding.response_id!r} has no exact recovery record"
            )
        asr_job = jobs_by_work_id.get(binding.asr_work_id)
        validation_job = jobs_by_work_id.get(binding.validation_work_id)
        if not isinstance(asr_job, VoiceASRJob) or not isinstance(
            validation_job, VoiceAudioValidationJob
        ):
            raise BucketAudioRecoveryError(
                f"binding {binding.response_id!r} has incomplete canonical jobs"
            )
        if (
            asr_job.source_audio is None
            or validation_job.source_audio is None
            or asr_job.source_audio.sha256 != record.raw_sha256
            or validation_job.source_audio.sha256 != record.raw_sha256
        ):
            raise BucketAudioRecoveryError(
                f"jobs for {binding.response_id!r} do not bind recovered audio"
            )

        asr_result = results_by_task_id.get(asr_job.task_id)
        validation_result = results_by_task_id.get(validation_job.task_id)
        if not isinstance(asr_result, VoiceJobResult):
            dispositions.append(
                _incomplete_disposition(
                    record=record,
                    binding=binding,
                    policy_identity=policy_identity,
                    reason=AudioDispositionReason.JOB_NOT_COMPLETED,
                    detail="ASR receipt is missing",
                    task_id=asr_job.task_id,
                    work_item_id=asr_job.lineage.work_item_id,
                    retryable=True,
                )
            )
            continue
        if not isinstance(validation_result, VoiceJobResult):
            dispositions.append(
                _incomplete_disposition(
                    record=record,
                    binding=binding,
                    policy_identity=policy_identity,
                    reason=AudioDispositionReason.JOB_NOT_COMPLETED,
                    detail="audio-validation receipt is missing",
                    task_id=validation_job.task_id,
                    work_item_id=validation_job.lineage.work_item_id,
                    retryable=True,
                )
            )
            continue
        if not _job_result_matches(asr_job, asr_result) or not _job_result_matches(
            validation_job, validation_result
        ):
            dispositions.append(
                _incomplete_disposition(
                    record=record,
                    binding=binding,
                    policy_identity=policy_identity,
                    reason=AudioDispositionReason.TASK_IDENTITY_MISMATCH,
                    detail="receipt lineage does not match scheduled jobs",
                    task_id=validation_job.task_id,
                    work_item_id=validation_job.lineage.work_item_id,
                    retryable=False,
                )
            )
            continue

        transcript_payload = transcript_bytes_by_asr_task_id.get(asr_job.task_id)
        if not isinstance(transcript_payload, bytes):
            dispositions.append(
                _incomplete_disposition(
                    record=record,
                    binding=binding,
                    policy_identity=policy_identity,
                    reason=AudioDispositionReason.MISSING_TRANSCRIPT,
                    detail="retained ASR transcript is unavailable",
                    task_id=asr_job.task_id,
                    work_item_id=asr_job.lineage.work_item_id,
                    retryable=True,
                )
            )
            continue
        if asr_result.status != "completed" or asr_result.task_type != "voice.asr":
            dispositions.append(
                _incomplete_disposition(
                    record=record,
                    binding=binding,
                    policy_identity=policy_identity,
                    reason=AudioDispositionReason.JOB_NOT_COMPLETED,
                    detail=f"ASR result status is {asr_result.status!r}",
                    task_id=asr_job.task_id,
                    work_item_id=asr_job.lineage.work_item_id,
                    retryable=True,
                )
            )
            continue
        # Transcript hash/size/UTF-8 failures are integrity errors and fail closed.
        transcript = _verified_transcript(
            result=asr_result,
            transcript_bytes=transcript_payload,
        )

        audio_payload = audio_bytes_by_sha256.get(record.raw_sha256)
        if not isinstance(audio_payload, bytes):
            dispositions.append(
                _incomplete_disposition(
                    record=record,
                    binding=binding,
                    policy_identity=policy_identity,
                    reason=AudioDispositionReason.BYTES_UNAVAILABLE,
                    detail="verified audio bytes are unavailable",
                    task_id=validation_job.task_id,
                    work_item_id=validation_job.lineage.work_item_id,
                    retryable=True,
                )
            )
            continue
        if (
            len(audio_payload) != record.verified_size_bytes
            or sha256(audio_payload).hexdigest() != record.raw_sha256
        ):
            # Integrity failure: do not continue with corrupt bytes for this or
            # any later row that might share process-level assumptions.
            raise BucketAudioRecoveryError(
                f"verified audio bytes changed for {binding.response_id!r}"
            )

        subject = AudioReconciliationSubject(
            subject_id=record.response_id,
            subject_schema_version=asr_job.lineage.subject_schema_version,
            spoken_text=record.spoken_text,
            text_sha256=record.canonical_text_sha256,
            locale=record.locale,
            license_id=license_id,
            consent_status=consent_status,
            source_manifest_id=recovery.recovery_id,
            policy_id=revalidation_plan.policy.identity,
            workset_id=revalidation_plan.workset.workset_id,
            work_item_id=validation_job.lineage.work_item_id,
            slot_names=binding.slot_names,
            slot_values=binding.slot_values,
            response_id=record.response_id,
            segment_kind="response",
        )
        item = reconcile_voice_job_result(
            validation_result,
            subject=subject,
            asr_transcript=transcript,
            artifact_bytes=audio_payload,
            policy=revalidation_plan.policy,
            expected_task_id=validation_job.task_id,
            expected_policy_id=revalidation_plan.policy.identity,
            provider="legacy-bucket-recovery",
            model="historical-indextts",
        )
        linked_audio.extend(item.linked_audio)
        provenance.extend(item.provenance)
        dispositions.extend(item.dispositions)
        item_reports.append(
            {
                "critical_fact_classification": (
                    binding.critical_fact_classification.value
                ),
                "critical_slot_count": len(binding.slot_names),
                "quality_report": dict(item.quality_report),
                "reconciliation_id": item.reconciliation_id,
                "response_id": binding.response_id,
            }
        )

    return AudioReconciliationResult(
        linked_audio=tuple(linked_audio),
        provenance=tuple(provenance),
        dispositions=tuple(dispositions),
        quality_report={
            "item_reports": sorted(
                item_reports, key=lambda item: str(item["response_id"])
            ),
            "recovery_id": recovery.recovery_id,
            "revalidation_plan_id": revalidation_plan.revalidation_plan_id,
        },
        policy_identity=revalidation_plan.policy.identity,
    )


__all__ = ["admit_bucket_audio_revalidation"]
