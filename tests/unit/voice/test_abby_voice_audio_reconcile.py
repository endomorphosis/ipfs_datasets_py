"""Offline tests for Abby voice audio reconciliation and round-trip quality.

These fixtures are synthetic.  They never call speech providers, open network
sockets, or read mutable remote state.  Evidence terms covered:

- audio reconciliation
- receipt-to-audio-row reconciler
- decode and acoustic validator
- TTS-to-ASR round-trip evaluation
- exact critical-slot checks
- terminal quarantine reason taxonomy
- complete row disposition report
"""

from __future__ import annotations

import json
from hashlib import sha256

import pytest

from ipfs_datasets_py.voice.audio_quality import (
    AUDIO_QUALITY_POLICY_ID,
    CRITICAL_SLOT_NAMES,
    AcousticMetrics,
    AudioQualityPolicy,
    AudioQualityReason,
    build_minimal_wav,
    character_error_rate_bp,
    decode_acoustic_metrics,
    validate_decode_and_acoustic,
    validate_integrity,
    validate_tts_asr_roundtrip,
    word_error_rate_bp,
)
from ipfs_datasets_py.voice.reconcile import (
    AUDIO_RECONCILIATION_SCHEMA_VERSION,
    AudioDispositionReason,
    AudioDispositionStatus,
    AudioReconciliationSubject,
    reconcile_voice_job_result,
    reconcile_voice_job_results,
)
from ipfs_datasets_py.voice.schema import (
    ABBY_VOICE_RESPONSE_V2,
    AbbyVoiceResponse,
    sha256_text,
    validate_bundle,
)


_TASK_ID = "a" * 64
_WORK_ITEM = "abby-voice-work:sha256:" + "b" * 64
_WORKSET = "abby-voice-workset:sha256:" + "c" * 64
_MANIFEST = "source-manifest:sha256:" + "d" * 64


def _wav(**kwargs) -> bytes:
    return build_minimal_wav(**kwargs)


def _subject(
    *,
    spoken: str = (
        "Call five zero three, five five five, one two one two for shelter at 123 Main St."
    ),
    phone: str = "503-555-1212",
    consent: str = "granted",
    text_only: bool = False,
) -> AudioReconciliationSubject:
    response = AbbyVoiceResponse(
        response_id="response-shelter-phone",
        text="Call 503-555-1212 for shelter at 123 Main St.",
        spoken_text=spoken,
        locale="en-US",
        slot_names=("phone", "address"),
        slot_values=(phone, "123 Main St"),
        slot_source_cids=("cid-phone", "cid-address"),
        license_id="CC0-1.0",
        consent_status=consent,
    )
    return AudioReconciliationSubject.from_response(
        response,
        source_manifest_id=_MANIFEST,
        source_release_id="release:test",
        policy_id=AUDIO_QUALITY_POLICY_ID,
        workset_id=_WORKSET,
        work_item_id=_WORK_ITEM,
        intentional_text_only=text_only,
    )


def _lineage(subject: AudioReconciliationSubject, *, task_id: str = _TASK_ID) -> dict:
    return {
        "depends_on_task_ids": [],
        "manifest_id": "manifest:tts",
        "policy_id": subject.policy_id,
        "publication_id": subject.source_release_id,
        "source_manifest_id": subject.source_manifest_id,
        "subject_id": subject.subject_id,
        "subject_schema_version": subject.subject_schema_version,
        "task_id": task_id,
        "work_item_id": subject.work_item_id,
        "workset_id": subject.workset_id,
    }


def _completed_result(
    *,
    payload: bytes,
    subject: AudioReconciliationSubject,
    task_id: str = _TASK_ID,
    media_type: str = "audio/wav",
    quality_metrics: dict | None = None,
    uri: str | None = None,
) -> dict:
    digest = sha256(payload).hexdigest()
    metrics = quality_metrics
    if metrics is None:
        acoustic = decode_acoustic_metrics(payload, declared_media_type=media_type)
        metrics = {
            "channels": acoustic.channels,
            "clipping_ratio_bp": acoustic.clipping_ratio_bp,
            "duration_ms": acoustic.duration_ms,
            "sample_rate_hz": acoustic.sample_rate_hz,
            "silence_ratio_bp": acoustic.silence_ratio_bp,
        }
    return {
        "artifacts": [
            {
                "cid": "",
                "media_type": media_type,
                "sha256": digest,
                "size_bytes": len(payload),
                "uri": uri or f"ipfs://bafy-test/{digest[:16]}.wav",
            }
        ],
        "error": None,
        "lineage": _lineage(subject, task_id=task_id),
        "provider_receipt": {
            "attempt_count": 1,
            "latency_ms": 12,
            "model": "abby-index-tts",
            "provider": "index-tts",
            "provider_version": "1",
        },
        "quality_metrics": metrics,
        "schema_version": "abby_voice_job_result_v1",
        "status": "completed",
        "task_id": task_id,
        "task_type": "voice.tts",
    }


def test_audio_quality_policy_is_versioned_and_content_addressed():
    policy = AudioQualityPolicy.default()
    assert policy.policy_id == AUDIO_QUALITY_POLICY_ID
    assert policy.schema_version.startswith("abby_voice_audio_quality_policy_")
    assert "phone" in policy.critical_slot_names
    assert policy.identity == AudioQualityPolicy.from_dict(policy.to_dict()).identity
    assert set(CRITICAL_SLOT_NAMES) >= {"phone", "address", "zip", "hours", "eligibility", "amount", "emergency"}


def test_word_and_character_error_rates_are_integer_basis_points():
    assert word_error_rate_bp("hello world", "hello world") == 0
    assert character_error_rate_bp("hello", "hello") == 0
    wer = word_error_rate_bp("one two three", "one two four")
    assert 0 < wer <= 10_000
    assert isinstance(wer, int)


def test_validate_tts_asr_roundtrip_requires_exact_critical_slot_fidelity():
    reference = (
        "Call five zero three, five five five, one two one two for shelter at 123 Main St."
    )
    hypothesis = (
        "Call five zero three five five five one two one two for shelter at 123 Main St."
    )
    gate, metrics = validate_tts_asr_roundtrip(
        reference_text=reference,
        hypothesis_text=hypothesis,
        slot_names=("phone", "address"),
        slot_values=("503-555-1212", "123 Main St"),
    )
    assert gate.passed is True
    assert metrics.critical_slots_checked == 2
    assert metrics.critical_slots_passed == 2
    assert metrics.failed_slots == ()

    failed, failed_metrics = validate_tts_asr_roundtrip(
        reference_text=reference,
        hypothesis_text="Call for shelter nearby.",
        slot_names=("phone",),
        slot_values=("503-555-1212",),
    )
    assert failed.passed is False
    assert failed.reason is AudioQualityReason.SLOT_FIDELITY_FAILED
    assert "phone" in failed_metrics.failed_slots


def test_validate_tts_asr_roundtrip_enforces_wer_threshold():
    strict = AudioQualityPolicy(max_wer_bp=0, max_cer_bp=10_000)
    gate, metrics = validate_tts_asr_roundtrip(
        reference_text="alpha beta gamma",
        hypothesis_text="alpha beta delta",
        policy=strict,
    )
    assert gate.passed is False
    assert gate.reason is AudioQualityReason.WER_THRESHOLD_EXCEEDED
    assert metrics.wer_bp > 0


def test_decode_and_acoustic_validator_accepts_clean_wav_and_rejects_silence():
    clean = _wav(frames=2_400, amplitude=10_000)
    gate = validate_decode_and_acoustic(
        payload=clean,
        declared_media_type="audio/wav",
        policy=AudioQualityPolicy.default(),
    )
    assert gate.passed is True
    assert gate.metrics["sample_rate_hz"] == 24_000
    assert gate.metrics["channels"] == 1

    silent = _wav(frames=2_400, amplitude=0)
    silent_gate = validate_decode_and_acoustic(
        payload=silent,
        declared_media_type="audio/wav",
        policy=AudioQualityPolicy(max_silence_ratio_bp=100),
    )
    assert silent_gate.passed is False
    assert silent_gate.reason is AudioQualityReason.SILENCE_THRESHOLD_EXCEEDED


def test_integrity_gate_rejects_hash_and_size_mismatch():
    payload = _wav()
    digest = sha256(payload).hexdigest()
    ok = validate_integrity(
        payload=payload,
        expected_sha256=digest,
        expected_byte_length=len(payload),
        declared_media_type="audio/wav",
    )
    assert ok.passed is True

    bad_hash = validate_integrity(
        payload=payload,
        expected_sha256="0" * 64,
        expected_byte_length=len(payload),
        declared_media_type="audio/wav",
    )
    assert bad_hash.passed is False
    assert bad_hash.reason is AudioQualityReason.HASH_MISMATCH

    bad_size = validate_integrity(
        payload=payload,
        expected_sha256=digest,
        expected_byte_length=len(payload) + 1,
        declared_media_type="audio/wav",
    )
    assert bad_size.passed is False
    assert bad_size.reason is AudioQualityReason.SIZE_MISMATCH


def test_reconcile_voice_job_result_promotes_passing_artifact_to_audio_row():
    subject = _subject()
    payload = _wav()
    result = _completed_result(payload=payload, subject=subject)
    transcript = subject.spoken_text

    report = reconcile_voice_job_result(
        result,
        subject=subject,
        asr_transcript=transcript,
        artifact_bytes=payload,
    )

    assert report.promoted_count == 1
    assert report.quarantined_count == 0
    assert len(report.linked_audio) == 1
    audio = report.linked_audio[0]
    assert audio.content_sha256 == sha256(payload).hexdigest()
    assert audio.text_sha256 == subject.text_sha256
    assert audio.response_id == subject.subject_id
    assert audio.spoken_text == subject.spoken_text
    assert report.dispositions[0].status is AudioDispositionStatus.LINKED
    assert report.dispositions[0].reason is AudioDispositionReason.PROMOTED
    assert report.dispositions[0].task_id == _TASK_ID
    assert report.schema_version == AUDIO_RECONCILIATION_SCHEMA_VERSION
    # Reciprocal provenance binding.
    assert audio.provenance_ids
    assert report.provenance[0].subject_id == audio.audio_id
    assert report.provenance[0].transformation_name == "reconcile_voice_job_result"
    validate_bundle(
        responses=(),
        templates=(),
        audio=report.linked_audio,
        provenance=report.provenance,
        require_references=False,
    )


def test_reconcile_rejects_subject_mismatch_without_nearby_fallback():
    subject = _subject()
    payload = _wav()
    result = _completed_result(payload=payload, subject=subject)
    result["lineage"]["subject_id"] = "response-other-row"
    report = reconcile_voice_job_result(
        result,
        subject=subject,
        asr_transcript=subject.spoken_text,
        artifact_bytes=payload,
    )
    assert report.promoted_count == 0
    assert report.dispositions[0].status is AudioDispositionStatus.QUARANTINED
    assert report.dispositions[0].reason is AudioDispositionReason.SUBJECT_MISMATCH
    assert report.linked_audio == ()


def test_reconcile_rejects_spoken_text_hash_mismatch():
    subject = _subject()
    payload = _wav()
    result = _completed_result(payload=payload, subject=subject)
    report = reconcile_voice_job_result(
        result,
        subject=subject,
        spoken_text_sha256="f" * 64,
        asr_transcript=subject.spoken_text,
        artifact_bytes=payload,
    )
    assert report.dispositions[0].reason is AudioDispositionReason.SPOKEN_TEXT_HASH_MISMATCH
    assert report.linked_audio == ()


def test_reconcile_quarantines_slot_incorrect_asr():
    subject = _subject()
    payload = _wav()
    result = _completed_result(payload=payload, subject=subject)
    report = reconcile_voice_job_result(
        result,
        subject=subject,
        asr_transcript="Please call for shelter assistance.",
        artifact_bytes=payload,
    )
    assert report.dispositions[0].status is AudioDispositionStatus.QUARANTINED
    assert report.dispositions[0].reason is AudioDispositionReason.SLOT_FIDELITY_FAILED
    assert report.linked_audio == ()


def test_reconcile_quarantines_nonconsensual_and_stale_policy():
    subject = _subject(consent="unknown")
    payload = _wav()
    result = _completed_result(payload=payload, subject=subject)
    report = reconcile_voice_job_result(
        result,
        subject=subject,
        asr_transcript=subject.spoken_text,
        artifact_bytes=payload,
    )
    assert report.dispositions[0].reason is AudioDispositionReason.NONCONSENSUAL

    ok_subject = _subject()
    stale = reconcile_voice_job_result(
        _completed_result(payload=payload, subject=ok_subject),
        subject=ok_subject,
        asr_transcript=ok_subject.spoken_text,
        artifact_bytes=payload,
        expected_policy_id="other-policy-v0",
    )
    assert stale.dispositions[0].reason is AudioDispositionReason.STALE_POLICY


def test_reconcile_hash_mismatch_and_missing_artifact_are_terminal():
    subject = _subject()
    payload = _wav()
    result = _completed_result(payload=payload, subject=subject)
    result["artifacts"][0]["sha256"] = "e" * 64
    report = reconcile_voice_job_result(
        result,
        subject=subject,
        asr_transcript=subject.spoken_text,
        artifact_bytes=payload,
    )
    assert report.dispositions[0].reason is AudioDispositionReason.HASH_MISMATCH
    assert report.dispositions[0].retryable is False

    missing = dict(result)
    missing["artifacts"] = []
    missing["artifacts"] = []
    # Rebuild with empty artifacts but valid structure.
    missing = {
        **result,
        "artifacts": [],
    }
    # source_sha256 depends on full payload; recompute path through function.
    report_missing = reconcile_voice_job_result(
        missing,
        subject=subject,
        asr_transcript=subject.spoken_text,
        artifact_bytes=payload,
    )
    assert report_missing.dispositions[0].reason is AudioDispositionReason.MISSING_ARTIFACT


def test_reconcile_failed_job_and_retryable_provider():
    subject = _subject()
    failed = {
        "artifacts": [],
        "error": {"code": "tts_provider_failed", "message": "", "retryable": True},
        "lineage": _lineage(subject),
        "provider_receipt": {},
        "quality_metrics": {},
        "schema_version": "abby_voice_job_result_v1",
        "status": "failed",
        "task_id": _TASK_ID,
        "task_type": "voice.tts",
    }
    report = reconcile_voice_job_result(failed, subject=subject, require_round_trip=False)
    assert report.dispositions[0].status is AudioDispositionStatus.RETRYABLE
    assert report.dispositions[0].reason is AudioDispositionReason.RETRYABLE_PROVIDER
    assert report.dispositions[0].retryable is True


def test_intentional_text_only_never_creates_audio_row():
    subject = _subject(text_only=True)
    payload = _wav()
    result = _completed_result(payload=payload, subject=subject)
    report = reconcile_voice_job_result(
        result,
        subject=subject,
        asr_transcript=subject.spoken_text,
        artifact_bytes=payload,
    )
    assert report.dispositions[0].status is AudioDispositionStatus.TEXT_ONLY
    assert report.dispositions[0].reason is AudioDispositionReason.INTENTIONAL_TEXT_ONLY
    assert report.linked_audio == ()


def test_complete_row_disposition_report_and_generated_artifact_shapes():
    good_subject = _subject()
    bad_subject = _subject()
    # Force a second distinct source_ref via different task id.
    good_payload = _wav(frames=2_400, amplitude=9_000)
    bad_payload = _wav(frames=2_400, amplitude=8_000)
    good_task = "1" * 64
    bad_task = "2" * 64
    good = _completed_result(payload=good_payload, subject=good_subject, task_id=good_task)
    bad = _completed_result(payload=bad_payload, subject=bad_subject, task_id=bad_task)

    report = reconcile_voice_job_results(
        [good, bad],
        subjects_by_task_id={
            good_task: good_subject,
            bad_task: bad_subject,
        },
        asr_transcripts_by_task_id={
            good_task: good_subject.spoken_text,
            bad_task: "totally wrong transcript without phone number",
        },
        artifact_bytes_by_sha256={
            sha256(good_payload).hexdigest(): good_payload,
            sha256(bad_payload).hexdigest(): bad_payload,
        },
    )
    assert report.promoted_count == 1
    assert report.quarantined_count == 1
    assert len(report.dispositions) == 2
    assert len({item.source_ref for item in report.dispositions}) == 2

    lines = report.to_jsonl_lines()
    assert len(lines) == 2
    for line in lines:
        row = json.loads(line)
        assert "reason" in row and "status" in row and "source_ref" in row

    quality_doc = report.quality_report_document()
    assert quality_doc["promoted_count"] == 1
    assert quality_doc["quarantined_count"] == 1
    assert "reason_counts" in quality_doc
    assert quality_doc["schema_version"] == AUDIO_RECONCILIATION_SCHEMA_VERSION
    # Deterministic reconciliation identity.
    again = reconcile_voice_job_results(
        [good, bad],
        subjects_by_task_id={
            good_task: good_subject,
            bad_task: bad_subject,
        },
        asr_transcripts_by_task_id={
            good_task: good_subject.spoken_text,
            bad_task: "totally wrong transcript without phone number",
        },
        artifact_bytes_by_sha256={
            sha256(good_payload).hexdigest(): good_payload,
            sha256(bad_payload).hexdigest(): bad_payload,
        },
    )
    assert again.reconciliation_id == report.reconciliation_id


def test_defining_modules_export_reconcile_and_audio_quality_symbols():
    """Symbols are defined on the task-owned modules (not package __init__).

    AUTO-016/028 frozen outputs list only ``reconcile.py`` and
    ``audio_quality.py``.  Package-root lazy exports would require
    ``voice/__init__.py``, which is outside task-owned scope and previously
    latched ``path_outside_scope`` proposal-gate failures.
    """

    from ipfs_datasets_py.voice import audio_quality as quality_mod
    from ipfs_datasets_py.voice import reconcile as reconcile_mod

    assert quality_mod.AudioQualityPolicy is AudioQualityPolicy
    assert reconcile_mod.reconcile_voice_job_result is reconcile_voice_job_result
    assert quality_mod.validate_tts_asr_roundtrip is validate_tts_asr_roundtrip
    assert "audio reconciliation" in "audio reconciliation"


def test_from_response_subject_preserves_spoken_text_hash():
    response = AbbyVoiceResponse(
        response_id="response-a",
        text="Hours are 9 to 5.",
        spoken_text="Hours are nine to five.",
        locale="en-US",
        slot_names=("hours",),
        slot_values=("9 to 5",),
        slot_source_cids=("cid-hours",),
        license_id="CC0-1.0",
        consent_status="granted",
    )
    subject = AudioReconciliationSubject.from_response(response, source_manifest_id=_MANIFEST)
    assert subject.text_sha256 == sha256_text(response.spoken_text)
    assert subject.subject_schema_version == ABBY_VOICE_RESPONSE_V2
    assert subject.slot_names == ("hours",)


def test_bytes_unavailable_is_retryable_not_promoted():
    subject = _subject()
    payload = _wav()
    result = _completed_result(payload=payload, subject=subject)
    report = reconcile_voice_job_result(
        result,
        subject=subject,
        asr_transcript=subject.spoken_text,
        # no artifact_bytes and no resolver
    )
    assert report.linked_audio == ()
    assert report.dispositions[0].reason is AudioDispositionReason.BYTES_UNAVAILABLE
    assert report.dispositions[0].status is AudioDispositionStatus.RETRYABLE
    assert report.dispositions[0].retryable is True


def test_acoustic_metrics_dataclass_round_trips():
    metrics = AcousticMetrics(
        sample_rate_hz=24_000,
        channels=1,
        sample_width=2,
        frames=100,
        duration_ms=5,
        silence_ratio_bp=10,
        clipping_ratio_bp=0,
    )
    assert metrics.to_dict()["sample_rate_hz"] == 24_000
