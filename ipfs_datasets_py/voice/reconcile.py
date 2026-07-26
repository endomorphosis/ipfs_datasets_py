"""Receipt-to-row reconciliation for completed Abby voice audio jobs.

This module turns immutable TTS / validation / ASR job results into either:

1. reciprocal canonical ``AbbyVoiceAudio`` + ``AbbyVoiceProvenance`` rows that
   are safe to promote into a release, or
2. stable terminal / retryable quarantine dispositions that preserve the
   failed artifact as immutable evidence (never deleted, never silently
   remapped onto a nearby subject).

Every admission decision is bound to the exact workset subject, task identity,
source release, spoken-text hash, provider policy, and stored artifact hash.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Any

from .audio_quality import (
    AUDIO_QUALITY_POLICY_ID,
    AudioQualityGate,
    AudioQualityPolicy,
    AudioQualityReason,
    QualityGateResult,
    validate_decode_and_acoustic,
    validate_integrity,
    validate_tts_asr_roundtrip,
)
from .schema import (
    ABBY_VOICE_AUDIO_V2,
    ABBY_VOICE_RESPONSE_V2,
    ABBY_VOICE_TEMPLATE_V2,
    AbbyVoiceAudio,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    AbbyVoiceTemplate,
    sha256_text,
    stable_audio_id,
    stable_provenance_id,
)

AUDIO_RECONCILIATION_SCHEMA_VERSION = "abby_voice_audio_reconciliation_v1"
AUDIO_RECONCILIATION_VERSION = "1.0.0"
TRANSFORMATION_NAME = "reconcile_voice_job_result"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PUBLISHABLE_CONSENT = frozenset({"granted", "not_required"})


class AudioDispositionStatus(StrEnum):
    """Terminal subject disposition after reconciliation."""

    LINKED = "linked"
    QUARANTINED = "quarantined"
    RETRYABLE = "retryable"
    TEXT_ONLY = "text_only"
    FAILED = "failed"


class AudioDispositionReason(StrEnum):
    """Stable terminal / retryable reason taxonomy for audio reconciliation."""

    PROMOTED = "promoted"
    INTENTIONAL_TEXT_ONLY = "intentional_text_only"
    MISSING_ARTIFACT = "missing_artifact"
    HASH_MISMATCH = "hash_mismatch"
    SIZE_MISMATCH = "size_mismatch"
    MEDIA_MISMATCH = "media_mismatch"
    UNSUPPORTED_MEDIA = "unsupported_media"
    DECODE_FAILED = "decode_failed"
    METADATA_MISMATCH = "metadata_mismatch"
    DURATION_OUT_OF_RANGE = "duration_out_of_range"
    SILENCE_THRESHOLD_EXCEEDED = "silence_threshold_exceeded"
    CLIPPING_THRESHOLD_EXCEEDED = "clipping_threshold_exceeded"
    WER_THRESHOLD_EXCEEDED = "wer_threshold_exceeded"
    CER_THRESHOLD_EXCEEDED = "cer_threshold_exceeded"
    SLOT_FIDELITY_FAILED = "slot_fidelity_failed"
    STALE_POLICY = "stale_policy"
    NONCONSENSUAL = "nonconsensual"
    SUBJECT_MISMATCH = "subject_mismatch"
    TASK_IDENTITY_MISMATCH = "task_identity_mismatch"
    SPOKEN_TEXT_HASH_MISMATCH = "spoken_text_hash_mismatch"
    SOURCE_RELEASE_MISMATCH = "source_release_mismatch"
    JOB_NOT_COMPLETED = "job_not_completed"
    JOB_FAILED = "job_failed"
    BYTES_UNAVAILABLE = "bytes_unavailable"
    MISSING_TRANSCRIPT = "missing_transcript"
    MISSING_REFERENCE_TEXT = "missing_reference_text"
    MISSING_SUBJECT = "missing_subject"
    RETRYABLE_PROVIDER = "retryable_provider"
    UNKNOWN_RESULT = "unknown_result"


_REASON_FROM_QUALITY: dict[AudioQualityReason, AudioDispositionReason] = {
    AudioQualityReason.PASSED: AudioDispositionReason.PROMOTED,
    AudioQualityReason.MISSING_ARTIFACT: AudioDispositionReason.MISSING_ARTIFACT,
    AudioQualityReason.HASH_MISMATCH: AudioDispositionReason.HASH_MISMATCH,
    AudioQualityReason.SIZE_MISMATCH: AudioDispositionReason.SIZE_MISMATCH,
    AudioQualityReason.MEDIA_MISMATCH: AudioDispositionReason.MEDIA_MISMATCH,
    AudioQualityReason.UNSUPPORTED_MEDIA: AudioDispositionReason.UNSUPPORTED_MEDIA,
    AudioQualityReason.DECODE_FAILED: AudioDispositionReason.DECODE_FAILED,
    AudioQualityReason.METADATA_MISMATCH: AudioDispositionReason.METADATA_MISMATCH,
    AudioQualityReason.DURATION_OUT_OF_RANGE: AudioDispositionReason.DURATION_OUT_OF_RANGE,
    AudioQualityReason.SILENCE_THRESHOLD_EXCEEDED: AudioDispositionReason.SILENCE_THRESHOLD_EXCEEDED,
    AudioQualityReason.CLIPPING_THRESHOLD_EXCEEDED: AudioDispositionReason.CLIPPING_THRESHOLD_EXCEEDED,
    AudioQualityReason.WER_THRESHOLD_EXCEEDED: AudioDispositionReason.WER_THRESHOLD_EXCEEDED,
    AudioQualityReason.CER_THRESHOLD_EXCEEDED: AudioDispositionReason.CER_THRESHOLD_EXCEEDED,
    AudioQualityReason.SLOT_FIDELITY_FAILED: AudioDispositionReason.SLOT_FIDELITY_FAILED,
    AudioQualityReason.STALE_POLICY: AudioDispositionReason.STALE_POLICY,
    AudioQualityReason.NONCONSENSUAL: AudioDispositionReason.NONCONSENSUAL,
    AudioQualityReason.MISSING_TRANSCRIPT: AudioDispositionReason.MISSING_TRANSCRIPT,
    AudioQualityReason.MISSING_REFERENCE_TEXT: AudioDispositionReason.MISSING_REFERENCE_TEXT,
    AudioQualityReason.BYTES_UNAVAILABLE: AudioDispositionReason.BYTES_UNAVAILABLE,
    AudioQualityReason.RETRYABLE_PROVIDER: AudioDispositionReason.RETRYABLE_PROVIDER,
}

_RETRYABLE_REASONS = frozenset(
    {
        AudioDispositionReason.BYTES_UNAVAILABLE,
        AudioDispositionReason.RETRYABLE_PROVIDER,
        AudioDispositionReason.MISSING_TRANSCRIPT,
    }
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _require_sha256(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be a full lowercase SHA-256")
    return value


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    raise TypeError("expected a mapping or object with to_dict()")


def _result_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    if hasattr(result, "to_dict"):
        payload = result.to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    if hasattr(result, "to_payload"):
        payload = result.to_payload()
        if isinstance(payload, Mapping):
            return dict(payload)
    raise TypeError("voice job result must be a mapping or contract object")


@dataclass(frozen=True, slots=True)
class AudioReconciliationSubject:
    """Exact workset subject binding required before an audio row can exist."""

    subject_id: str
    subject_schema_version: str
    spoken_text: str
    text_sha256: str
    locale: str = "en-US"
    license_id: str = "NOASSERTION"
    consent_status: str = "unknown"
    source_manifest_id: str = ""
    source_release_id: str = ""
    policy_id: str = AUDIO_QUALITY_POLICY_ID
    workset_id: str = ""
    work_item_id: str = ""
    slot_names: tuple[str, ...] = ()
    slot_values: tuple[str, ...] = ()
    response_id: str | None = None
    template_id: str | None = None
    segment_kind: str = "response"
    intentional_text_only: bool = False

    def __post_init__(self) -> None:
        for name in ("subject_id", "subject_schema_version", "spoken_text", "locale"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value.strip() != value:
                raise ValueError(f"{name} must be a non-empty canonical string")
        _require_sha256("text_sha256", self.text_sha256)
        if self.text_sha256 != sha256_text(self.spoken_text):
            raise ValueError("text_sha256 must equal SHA-256(spoken_text UTF-8)")
        if len(self.slot_names) != len(self.slot_values):
            raise ValueError("slot_names and slot_values must have equal lengths")
        names = tuple(str(item) for item in self.slot_names)
        values = tuple(str(item) for item in self.slot_values)
        object.__setattr__(self, "slot_names", names)
        object.__setattr__(self, "slot_values", values)
        if self.subject_schema_version == ABBY_VOICE_RESPONSE_V2 and not self.response_id:
            object.__setattr__(self, "response_id", self.subject_id)
        if self.subject_schema_version == ABBY_VOICE_TEMPLATE_V2 and not self.template_id:
            object.__setattr__(self, "template_id", self.subject_id)
            object.__setattr__(self, "segment_kind", "template_shell")

    @classmethod
    def from_response(
        cls,
        row: AbbyVoiceResponse,
        *,
        source_manifest_id: str = "",
        source_release_id: str = "",
        policy_id: str = AUDIO_QUALITY_POLICY_ID,
        workset_id: str = "",
        work_item_id: str = "",
        intentional_text_only: bool = False,
    ) -> AudioReconciliationSubject:
        return cls(
            subject_id=row.response_id,
            subject_schema_version=row.schema_version,
            spoken_text=row.spoken_text,
            text_sha256=row.content_sha256 or sha256_text(row.spoken_text),
            locale=row.locale,
            license_id=row.license_id,
            consent_status=row.consent_status,
            source_manifest_id=source_manifest_id,
            source_release_id=source_release_id,
            policy_id=policy_id,
            workset_id=workset_id,
            work_item_id=work_item_id,
            slot_names=row.slot_names,
            slot_values=row.slot_values,
            response_id=row.response_id,
            segment_kind="response",
            intentional_text_only=intentional_text_only,
        )

    @classmethod
    def from_template(
        cls,
        row: AbbyVoiceTemplate,
        *,
        source_manifest_id: str = "",
        source_release_id: str = "",
        policy_id: str = AUDIO_QUALITY_POLICY_ID,
        workset_id: str = "",
        work_item_id: str = "",
        intentional_text_only: bool = False,
    ) -> AudioReconciliationSubject:
        spoken = row.spoken_template or row.template_text
        return cls(
            subject_id=row.template_id,
            subject_schema_version=row.schema_version,
            spoken_text=spoken,
            text_sha256=row.content_sha256 or sha256_text(spoken),
            locale=row.locale,
            license_id=row.license_id,
            consent_status=row.consent_status,
            source_manifest_id=source_manifest_id,
            source_release_id=source_release_id,
            policy_id=policy_id,
            workset_id=workset_id,
            work_item_id=work_item_id,
            slot_names=(),
            slot_values=(),
            template_id=row.template_id,
            segment_kind="template_shell",
            intentional_text_only=intentional_text_only,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "consent_status": self.consent_status,
            "intentional_text_only": self.intentional_text_only,
            "license_id": self.license_id,
            "locale": self.locale,
            "policy_id": self.policy_id,
            "response_id": self.response_id,
            "segment_kind": self.segment_kind,
            "slot_names": list(self.slot_names),
            "slot_values": list(self.slot_values),
            "source_manifest_id": self.source_manifest_id,
            "source_release_id": self.source_release_id,
            "spoken_text": self.spoken_text,
            "subject_id": self.subject_id,
            "subject_schema_version": self.subject_schema_version,
            "template_id": self.template_id,
            "text_sha256": self.text_sha256,
            "work_item_id": self.work_item_id,
            "workset_id": self.workset_id,
        }


@dataclass(frozen=True, slots=True)
class AudioDisposition:
    """One immutable disposition for a subject / job result pair."""

    source_ref: str
    source_sha256: str
    status: AudioDispositionStatus
    reason: AudioDispositionReason
    subject_id: str = ""
    task_id: str = ""
    work_item_id: str = ""
    audio_id: str = ""
    artifact_sha256: str = ""
    policy_identity: str = ""
    retryable: bool = False
    gates: tuple[QualityGateResult, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.source_ref, str) or not self.source_ref:
            raise ValueError("source_ref must be non-empty")
        _require_sha256("source_sha256", self.source_sha256)
        object.__setattr__(self, "status", AudioDispositionStatus(self.status))
        object.__setattr__(self, "reason", AudioDispositionReason(self.reason))
        if not isinstance(self.retryable, bool):
            raise TypeError("retryable must be boolean")
        object.__setattr__(self, "gates", tuple(self.gates))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "audio_id": self.audio_id,
            "detail": self.detail,
            "gates": [gate.to_dict() for gate in self.gates],
            "policy_identity": self.policy_identity,
            "reason": self.reason.value,
            "retryable": self.retryable,
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
            "status": self.status.value,
            "subject_id": self.subject_id,
            "task_id": self.task_id,
            "work_item_id": self.work_item_id,
        }


@dataclass(frozen=True, slots=True)
class AudioReconciliationResult:
    """Complete row disposition report for one or more voice job results."""

    linked_audio: tuple[AbbyVoiceAudio, ...] = ()
    provenance: tuple[AbbyVoiceProvenance, ...] = ()
    dispositions: tuple[AudioDisposition, ...] = ()
    quality_report: Mapping[str, Any] = field(default_factory=dict)
    policy_identity: str = ""
    schema_version: str = AUDIO_RECONCILIATION_SCHEMA_VERSION
    reconciliation_id: str = ""

    def __post_init__(self) -> None:
        linked = tuple(sorted(self.linked_audio, key=lambda row: row.audio_id))
        provenance = tuple(sorted(self.provenance, key=lambda row: row.provenance_id))
        dispositions = tuple(sorted(self.dispositions, key=lambda item: item.source_ref))
        audio_ids = [row.audio_id for row in linked]
        if len(audio_ids) != len(set(audio_ids)):
            raise ValueError("linked audio IDs must be unique")
        provenance_ids = {row.provenance_id for row in provenance}
        for row in linked:
            missing = set(row.provenance_ids) - provenance_ids
            if missing:
                raise ValueError(f"linked audio {row.audio_id!r} has missing provenance")
        refs = [item.source_ref for item in dispositions]
        if len(refs) != len(set(refs)):
            raise ValueError("every source must have exactly one disposition")
        if self.schema_version != AUDIO_RECONCILIATION_SCHEMA_VERSION:
            raise ValueError("unsupported audio reconciliation schema")
        object.__setattr__(self, "linked_audio", linked)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "dispositions", dispositions)
        object.__setattr__(self, "quality_report", dict(self.quality_report))
        identity = {
            "dispositions": [item.to_dict() for item in dispositions],
            "linked_audio": [row.to_dict() for row in linked],
            "policy_identity": self.policy_identity,
            "provenance": [row.to_dict() for row in provenance],
            "quality_report": dict(self.quality_report),
            "schema_version": self.schema_version,
        }
        computed = f"abby-voice-audio-reconcile:sha256:{sha256(_canonical_bytes(identity)).hexdigest()}"
        if self.reconciliation_id and self.reconciliation_id != computed:
            raise ValueError("reconciliation_id does not match deterministic content")
        object.__setattr__(self, "reconciliation_id", computed)

    @property
    def promoted_count(self) -> int:
        return sum(1 for item in self.dispositions if item.status == AudioDispositionStatus.LINKED)

    @property
    def quarantined_count(self) -> int:
        return sum(1 for item in self.dispositions if item.status == AudioDispositionStatus.QUARANTINED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dispositions": [item.to_dict() for item in self.dispositions],
            "linked_audio": [row.to_dict() for row in self.linked_audio],
            "policy_identity": self.policy_identity,
            "provenance": [row.to_dict() for row in self.provenance],
            "quality_report": dict(self.quality_report),
            "reconciliation_id": self.reconciliation_id,
            "schema_version": self.schema_version,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_jsonl_lines(self) -> list[str]:
        """Emit one JSON object per disposition for ``audio-reconciliation.jsonl``."""

        return [
            json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for item in self.dispositions
        ]

    def quality_report_document(self) -> dict[str, Any]:
        """Emit the aggregate quality report for ``audio-quality-report.json``."""

        reason_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for item in self.dispositions:
            reason_counts[item.reason.value] = reason_counts.get(item.reason.value, 0) + 1
            status_counts[item.status.value] = status_counts.get(item.status.value, 0) + 1
        return {
            "policy_identity": self.policy_identity,
            "promoted_count": self.promoted_count,
            "quarantined_count": self.quarantined_count,
            "reason_counts": reason_counts,
            "reconciliation_id": self.reconciliation_id,
            "schema_version": self.schema_version,
            "status_counts": status_counts,
            "subject_count": len(self.dispositions),
            "version": AUDIO_RECONCILIATION_VERSION,
            **dict(self.quality_report),
        }


def _artifact_from_result(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    artifacts = payload.get("artifacts") or ()
    if not artifacts:
        return None
    first = artifacts[0]
    if hasattr(first, "to_dict"):
        first = first.to_dict()
    if not isinstance(first, Mapping):
        return None
    return {
        "uri": str(first.get("uri") or ""),
        "cid": str(first.get("cid") or first.get("ipfs_cid") or ""),
        "sha256": str(first.get("sha256") or first.get("content_sha256") or ""),
        "size_bytes": first.get("size_bytes", first.get("byte_length")),
        "media_type": str(first.get("media_type") or first.get("mime_type") or "audio/wav"),
    }


def _lineage_from_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    lineage = payload.get("lineage") or payload.get("_lineage") or {}
    if hasattr(lineage, "to_dict"):
        lineage = lineage.to_dict()
    if not isinstance(lineage, Mapping):
        return {}
    return dict(lineage)


def _provider_from_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    receipt = payload.get("provider_receipt") or {}
    if hasattr(receipt, "keys"):
        return dict(receipt)
    return {}


def _quality_metrics(payload: Mapping[str, Any]) -> dict[str, int]:
    metrics = payload.get("quality_metrics") or {}
    if not isinstance(metrics, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        result[str(key)] = value
    return result


def _error_from_result(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    error = payload.get("error")
    if error is None:
        return None
    if hasattr(error, "to_dict"):
        error = error.to_dict()
    if isinstance(error, Mapping):
        return dict(error)
    return {"code": str(error), "retryable": False}


def _source_ref(task_id: str, subject_id: str) -> str:
    return f"voice-job:{task_id or 'unknown'}:{subject_id or 'unknown'}"


def _disposition_from_quality(
    *,
    source_ref: str,
    source_sha256: str,
    subject: AudioReconciliationSubject | None,
    task_id: str,
    work_item_id: str,
    policy_identity: str,
    gate: QualityGateResult,
    artifact_sha256: str = "",
    detail: str = "",
) -> AudioDisposition:
    reason = _REASON_FROM_QUALITY.get(gate.reason, AudioDispositionReason.UNKNOWN_RESULT)
    retryable = gate.retryable or reason in _RETRYABLE_REASONS
    if gate.passed:
        status = AudioDispositionStatus.LINKED
    elif retryable:
        status = AudioDispositionStatus.RETRYABLE
    else:
        status = AudioDispositionStatus.QUARANTINED
    return AudioDisposition(
        source_ref=source_ref,
        source_sha256=source_sha256,
        status=status,
        reason=reason,
        subject_id=subject.subject_id if subject else "",
        task_id=task_id,
        work_item_id=work_item_id,
        artifact_sha256=artifact_sha256,
        policy_identity=policy_identity,
        retryable=retryable,
        gates=(gate,),
        detail=detail or gate.detail,
    )


def _bind_identity(
    *,
    subject: AudioReconciliationSubject,
    payload: Mapping[str, Any],
    expected_task_id: str | None,
    expected_policy_identity: str,
    policy: AudioQualityPolicy,
) -> QualityGateResult | None:
    """Return a failing gate when identity bindings disagree; else None."""

    lineage = _lineage_from_result(payload)
    task_id = str(payload.get("task_id") or lineage.get("task_id") or "")
    if expected_task_id and task_id and task_id != expected_task_id:
        return QualityGateResult(
            gate=AudioQualityGate.POLICY,
            passed=False,
            reason=AudioQualityReason.STALE_POLICY,
            detail="task_id does not match the expected workset task identity",
            metrics={"expected_task_id": expected_task_id, "task_id": task_id},
        )
    if subject.work_item_id and lineage.get("work_item_id") and lineage["work_item_id"] != subject.work_item_id:
        return QualityGateResult(
            gate=AudioQualityGate.POLICY,
            passed=False,
            reason=AudioQualityReason.STALE_POLICY,
            detail="work_item_id does not match the expected workset subject binding",
            metrics={
                "expected_work_item_id": subject.work_item_id,
                "work_item_id": str(lineage.get("work_item_id") or ""),
            },
        )
    if subject.subject_id and lineage.get("subject_id") and lineage["subject_id"] != subject.subject_id:
        return QualityGateResult(
            gate=AudioQualityGate.POLICY,
            passed=False,
            reason=AudioQualityReason.STALE_POLICY,
            detail="result subject_id does not match the bound workset subject",
            metrics={
                "expected_subject_id": subject.subject_id,
                "subject_id": str(lineage.get("subject_id") or ""),
            },
        )
    if (
        subject.subject_schema_version
        and lineage.get("subject_schema_version")
        and lineage["subject_schema_version"] != subject.subject_schema_version
    ):
        return QualityGateResult(
            gate=AudioQualityGate.POLICY,
            passed=False,
            reason=AudioQualityReason.STALE_POLICY,
            detail="subject schema version disagrees with the bound subject",
        )
    if subject.workset_id and lineage.get("workset_id") and lineage["workset_id"] != subject.workset_id:
        return QualityGateResult(
            gate=AudioQualityGate.POLICY,
            passed=False,
            reason=AudioQualityReason.STALE_POLICY,
            detail="workset_id does not match the bound subject",
        )
    if (
        subject.source_manifest_id
        and lineage.get("source_manifest_id")
        and lineage["source_manifest_id"] != subject.source_manifest_id
    ):
        return QualityGateResult(
            gate=AudioQualityGate.POLICY,
            passed=False,
            reason=AudioQualityReason.STALE_POLICY,
            detail="source_manifest_id / source release binding disagrees",
        )
    if (
        subject.source_release_id
        and lineage.get("publication_id")
        and lineage["publication_id"]
        and lineage["publication_id"] != subject.source_release_id
    ):
        return QualityGateResult(
            gate=AudioQualityGate.POLICY,
            passed=False,
            reason=AudioQualityReason.STALE_POLICY,
            detail="publication / source release identity disagrees",
        )
    lineage_policy = str(lineage.get("policy_id") or "")
    if lineage_policy and lineage_policy not in {subject.policy_id, policy.policy_id, policy.identity, expected_policy_identity}:
        return QualityGateResult(
            gate=AudioQualityGate.POLICY,
            passed=False,
            reason=AudioQualityReason.STALE_POLICY,
            detail="provider / quality policy identity is stale relative to admission policy",
            metrics={
                "expected_policy": expected_policy_identity,
                "lineage_policy_id": lineage_policy,
            },
        )
    return None


def reconcile_voice_job_result(
    result: Any,
    *,
    subject: AudioReconciliationSubject | AbbyVoiceResponse | AbbyVoiceTemplate | None = None,
    spoken_text: str | None = None,
    spoken_text_sha256: str | None = None,
    asr_transcript: str | None = None,
    artifact_bytes: bytes | bytearray | memoryview | None = None,
    byte_resolver: Callable[[str], bytes | bytearray | memoryview | None] | None = None,
    policy: AudioQualityPolicy | None = None,
    expected_task_id: str | None = None,
    expected_policy_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    voice: str | None = None,
    require_round_trip: bool = True,
    slot_names: Sequence[str] | None = None,
    slot_values: Sequence[str] | None = None,
) -> AudioReconciliationResult:
    """Ingest one completed audio-job receipt and promote or quarantine it.

    Parameters
    ----------
    result:
        A :class:`VoiceJobResult` contract object or its JSON payload.
    subject:
        Exact workset subject binding.  When omitted, *spoken_text* must be
        supplied and the lineage subject fields become authoritative.
    asr_transcript:
        Dataset validation ASR text used for TTS → ASR round-trip evaluation.
    artifact_bytes / byte_resolver:
        Optional artifact payload.  When absent, integrity fails closed unless
        the subject is intentionally text-only.
    require_round_trip:
        When true (default), dataset promotion requires ASR fidelity gates.
    """

    selected = policy or AudioQualityPolicy.default()
    policy_identity = selected.identity
    if expected_policy_id and expected_policy_id not in {
        selected.policy_id,
        selected.policy_version,
        policy_identity,
    }:
        # Explicit stale-policy short circuit before any promotion.
        payload_probe = {}
        try:
            payload_probe = _result_payload(result)
        except Exception:
            payload_probe = {}
        task_id = str(payload_probe.get("task_id") or "")
        source_ref = _source_ref(task_id, getattr(subject, "subject_id", "") if subject else "")
        source_sha256 = sha256(_canonical_bytes({"task_id": task_id, "stale": True})).hexdigest()
        disposition = AudioDisposition(
            source_ref=source_ref,
            source_sha256=source_sha256,
            status=AudioDispositionStatus.QUARANTINED,
            reason=AudioDispositionReason.STALE_POLICY,
            subject_id=getattr(subject, "subject_id", "") if subject else "",
            task_id=task_id,
            policy_identity=policy_identity,
            detail="admission policy identity does not match the expected policy",
            gates=(
                QualityGateResult(
                    gate=AudioQualityGate.POLICY,
                    passed=False,
                    reason=AudioQualityReason.STALE_POLICY,
                    detail="expected_policy_id is stale",
                    metrics={"expected_policy_id": expected_policy_id, "policy_identity": policy_identity},
                ),
            ),
        )
        return AudioReconciliationResult(
            dispositions=(disposition,),
            policy_identity=policy_identity,
            quality_report={"stale_policy": True},
        )

    bound_subject = _coerce_subject(
        subject,
        spoken_text=spoken_text,
        spoken_text_sha256=spoken_text_sha256,
        slot_names=slot_names,
        slot_values=slot_values,
        policy_id=selected.policy_id,
        result=result,
    )

    try:
        payload = _result_payload(result)
    except Exception:
        disposition = AudioDisposition(
            source_ref=_source_ref("", bound_subject.subject_id if bound_subject else ""),
            source_sha256=sha256(b"unknown-result").hexdigest(),
            status=AudioDispositionStatus.QUARANTINED,
            reason=AudioDispositionReason.UNKNOWN_RESULT,
            subject_id=bound_subject.subject_id if bound_subject else "",
            policy_identity=policy_identity,
            detail="voice job result could not be parsed",
        )
        return AudioReconciliationResult(
            dispositions=(disposition,),
            policy_identity=policy_identity,
        )

    lineage = _lineage_from_result(payload)
    task_id = str(payload.get("task_id") or lineage.get("task_id") or "")
    work_item_id = str(lineage.get("work_item_id") or (bound_subject.work_item_id if bound_subject else "") or "")
    source_ref = _source_ref(task_id, bound_subject.subject_id if bound_subject else str(lineage.get("subject_id") or ""))
    source_sha256 = sha256(_canonical_bytes(payload)).hexdigest()
    status = str(payload.get("status") or "")
    gates: list[QualityGateResult] = []

    if bound_subject is None:
        disposition = AudioDisposition(
            source_ref=source_ref,
            source_sha256=source_sha256,
            status=AudioDispositionStatus.QUARANTINED,
            reason=AudioDispositionReason.MISSING_SUBJECT,
            task_id=task_id,
            work_item_id=work_item_id,
            policy_identity=policy_identity,
            detail="no exact workset subject binding was supplied",
        )
        return AudioReconciliationResult(
            dispositions=(disposition,),
            policy_identity=policy_identity,
        )

    if bound_subject.intentional_text_only:
        disposition = AudioDisposition(
            source_ref=source_ref,
            source_sha256=source_sha256,
            status=AudioDispositionStatus.TEXT_ONLY,
            reason=AudioDispositionReason.INTENTIONAL_TEXT_ONLY,
            subject_id=bound_subject.subject_id,
            task_id=task_id,
            work_item_id=work_item_id,
            policy_identity=policy_identity,
            detail="subject is intentionally text-only; no audio row is created",
        )
        return AudioReconciliationResult(
            dispositions=(disposition,),
            policy_identity=policy_identity,
            quality_report={"text_only_subjects": 1},
        )

    if status == "failed":
        error = _error_from_result(payload) or {}
        retryable = bool(error.get("retryable"))
        disposition = AudioDisposition(
            source_ref=source_ref,
            source_sha256=source_sha256,
            status=AudioDispositionStatus.RETRYABLE if retryable else AudioDispositionStatus.FAILED,
            reason=(
                AudioDispositionReason.RETRYABLE_PROVIDER
                if retryable
                else AudioDispositionReason.JOB_FAILED
            ),
            subject_id=bound_subject.subject_id,
            task_id=task_id,
            work_item_id=work_item_id,
            policy_identity=policy_identity,
            retryable=retryable,
            detail=str(error.get("code") or "job failed"),
        )
        return AudioReconciliationResult(
            dispositions=(disposition,),
            policy_identity=policy_identity,
        )

    if status != "completed":
        disposition = AudioDisposition(
            source_ref=source_ref,
            source_sha256=source_sha256,
            status=AudioDispositionStatus.QUARANTINED,
            reason=AudioDispositionReason.JOB_NOT_COMPLETED,
            subject_id=bound_subject.subject_id,
            task_id=task_id,
            work_item_id=work_item_id,
            policy_identity=policy_identity,
            detail=f"job status {status!r} is not completed",
        )
        return AudioReconciliationResult(
            dispositions=(disposition,),
            policy_identity=policy_identity,
        )

    identity_gate = _bind_identity(
        subject=bound_subject,
        payload=payload,
        expected_task_id=expected_task_id,
        expected_policy_identity=policy_identity,
        policy=selected,
    )
    if identity_gate is not None:
        gates.append(identity_gate)
        # Map identity failures onto the stable subject/task reason codes.
        detail = identity_gate.detail
        metrics = dict(identity_gate.metrics)
        if "expected_subject_id" in metrics or detail.startswith("result subject_id"):
            reason = AudioDispositionReason.SUBJECT_MISMATCH
        elif "expected_task_id" in metrics or detail.startswith("task_id"):
            reason = AudioDispositionReason.TASK_IDENTITY_MISMATCH
        elif "source_manifest" in detail or "publication" in detail or "source release" in detail:
            reason = AudioDispositionReason.SOURCE_RELEASE_MISMATCH
        else:
            reason = AudioDispositionReason.STALE_POLICY
        disposition = AudioDisposition(
            source_ref=source_ref,
            source_sha256=source_sha256,
            status=AudioDispositionStatus.QUARANTINED,
            reason=reason,
            subject_id=bound_subject.subject_id,
            task_id=task_id,
            work_item_id=work_item_id,
            policy_identity=policy_identity,
            gates=tuple(gates),
            detail=identity_gate.detail,
        )
        return AudioReconciliationResult(
            dispositions=(disposition,),
            policy_identity=policy_identity,
        )

    if spoken_text_sha256 and spoken_text_sha256 != bound_subject.text_sha256:
        gate = QualityGateResult(
            gate=AudioQualityGate.POLICY,
            passed=False,
            reason=AudioQualityReason.STALE_POLICY,
            detail="spoken-text hash does not match the bound subject",
            metrics={
                "expected": bound_subject.text_sha256,
                "provided": spoken_text_sha256,
            },
        )
        disposition = AudioDisposition(
            source_ref=source_ref,
            source_sha256=source_sha256,
            status=AudioDispositionStatus.QUARANTINED,
            reason=AudioDispositionReason.SPOKEN_TEXT_HASH_MISMATCH,
            subject_id=bound_subject.subject_id,
            task_id=task_id,
            work_item_id=work_item_id,
            policy_identity=policy_identity,
            gates=(gate,),
            detail=gate.detail,
        )
        return AudioReconciliationResult(
            dispositions=(disposition,),
            policy_identity=policy_identity,
        )

    consent = bound_subject.consent_status.casefold()
    if consent not in selected.publishable_consent and consent not in _PUBLISHABLE_CONSENT:
        gate = QualityGateResult(
            gate=AudioQualityGate.CONSENT,
            passed=False,
            reason=AudioQualityReason.NONCONSENSUAL,
            detail="consent_status is not publishable; artifact is quarantined",
            metrics={"consent_status": bound_subject.consent_status},
        )
        disposition = AudioDisposition(
            source_ref=source_ref,
            source_sha256=source_sha256,
            status=AudioDispositionStatus.QUARANTINED,
            reason=AudioDispositionReason.NONCONSENSUAL,
            subject_id=bound_subject.subject_id,
            task_id=task_id,
            work_item_id=work_item_id,
            policy_identity=policy_identity,
            gates=(gate,),
            detail=gate.detail,
        )
        return AudioReconciliationResult(
            dispositions=(disposition,),
            policy_identity=policy_identity,
        )

    artifact = _artifact_from_result(payload)
    if artifact is None:
        gate = QualityGateResult(
            gate=AudioQualityGate.INTEGRITY,
            passed=False,
            reason=AudioQualityReason.MISSING_ARTIFACT,
            detail="completed job result has no artifact descriptor",
        )
        disposition = _disposition_from_quality(
            source_ref=source_ref,
            source_sha256=source_sha256,
            subject=bound_subject,
            task_id=task_id,
            work_item_id=work_item_id,
            policy_identity=policy_identity,
            gate=gate,
        )
        return AudioReconciliationResult(
            dispositions=(disposition,),
            policy_identity=policy_identity,
        )

    artifact_sha = str(artifact.get("sha256") or "")
    size_bytes = artifact.get("size_bytes")
    media_type = str(artifact.get("media_type") or "audio/wav")
    uri = str(artifact.get("uri") or "")
    cid = str(artifact.get("cid") or "")

    payload_bytes: bytes | None = None
    if artifact_bytes is not None:
        payload_bytes = bytes(artifact_bytes)
    elif byte_resolver is not None and (uri or cid):
        try:
            resolved = byte_resolver(uri or cid)
            payload_bytes = bytes(resolved) if resolved is not None else None
        except Exception:
            payload_bytes = None

    integrity = validate_integrity(
        payload=payload_bytes,
        expected_sha256=artifact_sha,
        expected_byte_length=int(size_bytes) if isinstance(size_bytes, int) else None,
        declared_media_type=media_type,
        policy=selected,
    )
    gates.append(integrity)
    if not integrity.passed:
        # Descriptor-only path: still admit hash binding when bytes are absent
        # only if the caller explicitly disables byte verification by providing
        # precomputed quality metrics AND no resolver.  Default is fail-closed.
        disposition = _disposition_from_quality(
            source_ref=source_ref,
            source_sha256=source_sha256,
            subject=bound_subject,
            task_id=task_id,
            work_item_id=work_item_id,
            policy_identity=policy_identity,
            gate=integrity,
            artifact_sha256=artifact_sha,
        )
        return AudioReconciliationResult(
            dispositions=(disposition,),
            policy_identity=policy_identity,
            quality_report={"integrity": integrity.to_dict()},
        )

    quality_metrics = _quality_metrics(payload)
    acoustic = validate_decode_and_acoustic(
        payload=payload_bytes,
        declared_media_type=media_type,
        declared_sample_rate_hz=quality_metrics.get("sample_rate_hz"),
        declared_channels=quality_metrics.get("channels"),
        declared_duration_ms=quality_metrics.get("duration_ms"),
        precomputed_metrics=quality_metrics or None,
        policy=selected,
    )
    gates.append(acoustic)
    if not acoustic.passed:
        disposition = _disposition_from_quality(
            source_ref=source_ref,
            source_sha256=source_sha256,
            subject=bound_subject,
            task_id=task_id,
            work_item_id=work_item_id,
            policy_identity=policy_identity,
            gate=acoustic,
            artifact_sha256=artifact_sha,
        )
        return AudioReconciliationResult(
            dispositions=(disposition,),
            policy_identity=policy_identity,
            quality_report={"acoustic": acoustic.to_dict()},
        )

    round_trip_metrics: dict[str, Any] = {}
    if require_round_trip:
        if asr_transcript is None:
            gate = QualityGateResult(
                gate=AudioQualityGate.ROUND_TRIP,
                passed=False,
                reason=AudioQualityReason.MISSING_TRANSCRIPT,
                detail="dataset ASR transcript is required for promotion",
                retryable=True,
            )
            gates.append(gate)
            disposition = _disposition_from_quality(
                source_ref=source_ref,
                source_sha256=source_sha256,
                subject=bound_subject,
                task_id=task_id,
                work_item_id=work_item_id,
                policy_identity=policy_identity,
                gate=gate,
                artifact_sha256=artifact_sha,
            )
            return AudioReconciliationResult(
                dispositions=(disposition,),
                policy_identity=policy_identity,
            )
        round_trip_gate, metrics = validate_tts_asr_roundtrip(
            reference_text=bound_subject.spoken_text,
            hypothesis_text=asr_transcript,
            slot_names=bound_subject.slot_names,
            slot_values=bound_subject.slot_values,
            policy=selected,
        )
        gates.append(round_trip_gate)
        round_trip_metrics = metrics.to_dict()
        if not round_trip_gate.passed:
            disposition = _disposition_from_quality(
                source_ref=source_ref,
                source_sha256=source_sha256,
                subject=bound_subject,
                task_id=task_id,
                work_item_id=work_item_id,
                policy_identity=policy_identity,
                gate=round_trip_gate,
                artifact_sha256=artifact_sha,
            )
            return AudioReconciliationResult(
                dispositions=(disposition,),
                policy_identity=policy_identity,
                quality_report={"round_trip": round_trip_metrics},
            )

    # Promote: create reciprocal audio + provenance rows.
    content_sha = artifact_sha.casefold()
    audio_id = stable_audio_id(content_sha, segment_kind=bound_subject.segment_kind)
    source_uri = uri or (f"ipfs://{cid}" if cid else f"voice-job://{task_id}")
    provenance_id = stable_provenance_id(
        audio_id,
        source_uri,
        TRANSFORMATION_NAME,
        content_sha,
    )
    provider_receipt = _provider_from_result(payload)
    acoustic_metrics = dict(acoustic.metrics)
    provenance_row = AbbyVoiceProvenance(
        provenance_id=provenance_id,
        subject_id=audio_id,
        subject_schema_version=ABBY_VOICE_AUDIO_V2,
        transformation_name=TRANSFORMATION_NAME,
        transformation_version=AUDIO_RECONCILIATION_VERSION,
        source_uri=source_uri,
        source_revision=bound_subject.source_manifest_id or bound_subject.source_release_id or task_id,
        source_sha256=content_sha,
        locale=bound_subject.locale,
        license_id=bound_subject.license_id,
        consent_status=bound_subject.consent_status,
        parent_provenance_ids=(),
        source_cids=(cid,) if cid else (),
    )
    audio_row = AbbyVoiceAudio(
        audio_id=audio_id,
        spoken_text=bound_subject.spoken_text,
        content_sha256=content_sha,
        text_sha256=bound_subject.text_sha256,
        locale=bound_subject.locale,
        uri=uri or None,
        ipfs_cid=cid or None,
        response_id=bound_subject.response_id,
        template_id=bound_subject.template_id,
        segment_kind=bound_subject.segment_kind,
        mime_type=str(acoustic_metrics.get("detected_media_type") or media_type),
        codec=_codec_from_media(str(acoustic_metrics.get("detected_media_type") or media_type)),
        byte_length=int(size_bytes) if isinstance(size_bytes, int) else (len(payload_bytes) if payload_bytes else None),
        duration_ms=float(acoustic_metrics["duration_ms"]) if "duration_ms" in acoustic_metrics else None,
        sample_rate_hz=int(acoustic_metrics["sample_rate_hz"]) if "sample_rate_hz" in acoustic_metrics else None,
        channels=int(acoustic_metrics["channels"]) if "channels" in acoustic_metrics else None,
        provider=provider or str(provider_receipt.get("provider") or "") or None,
        model=model or str(provider_receipt.get("model") or "") or None,
        voice=voice,
        provenance_ids=(provenance_id,),
        source_cids=(cid,) if cid else (),
        license_id=bound_subject.license_id,
        consent_status=bound_subject.consent_status,
    )
    disposition = AudioDisposition(
        source_ref=source_ref,
        source_sha256=source_sha256,
        status=AudioDispositionStatus.LINKED,
        reason=AudioDispositionReason.PROMOTED,
        subject_id=bound_subject.subject_id,
        task_id=task_id,
        work_item_id=work_item_id,
        audio_id=audio_id,
        artifact_sha256=content_sha,
        policy_identity=policy_identity,
        gates=tuple(gates),
        detail="artifact passed integrity, acoustic, and round-trip gates",
    )
    quality_report = {
        "acoustic": acoustic.to_dict(),
        "integrity": integrity.to_dict(),
        "promoted_audio_id": audio_id,
        "round_trip": round_trip_metrics,
    }
    return AudioReconciliationResult(
        linked_audio=(audio_row,),
        provenance=(provenance_row,),
        dispositions=(disposition,),
        quality_report=quality_report,
        policy_identity=policy_identity,
    )


def reconcile_voice_job_results(
    results: Iterable[Any],
    *,
    subjects_by_task_id: Mapping[str, AudioReconciliationSubject] | None = None,
    subjects_by_work_item_id: Mapping[str, AudioReconciliationSubject] | None = None,
    asr_transcripts_by_task_id: Mapping[str, str] | None = None,
    artifact_bytes_by_sha256: Mapping[str, bytes] | None = None,
    byte_resolver: Callable[[str], bytes | bytearray | memoryview | None] | None = None,
    policy: AudioQualityPolicy | None = None,
    require_round_trip: bool = True,
) -> AudioReconciliationResult:
    """Reconcile many job results into one complete row disposition report."""

    selected = policy or AudioQualityPolicy.default()
    linked: list[AbbyVoiceAudio] = []
    provenance: list[AbbyVoiceProvenance] = []
    dispositions: list[AudioDisposition] = []
    quality_reports: list[dict[str, Any]] = []
    by_task = dict(subjects_by_task_id or {})
    by_work = dict(subjects_by_work_item_id or {})
    transcripts = dict(asr_transcripts_by_task_id or {})
    bytes_by_hash = dict(artifact_bytes_by_sha256 or {})

    for result in results:
        payload = _result_payload(result)
        lineage = _lineage_from_result(payload)
        task_id = str(payload.get("task_id") or lineage.get("task_id") or "")
        work_item_id = str(lineage.get("work_item_id") or "")
        subject = by_task.get(task_id) or by_work.get(work_item_id)
        artifact = _artifact_from_result(payload)
        artifact_sha = str((artifact or {}).get("sha256") or "")
        payload_bytes = bytes_by_hash.get(artifact_sha)
        item = reconcile_voice_job_result(
            result,
            subject=subject,
            asr_transcript=transcripts.get(task_id),
            artifact_bytes=payload_bytes,
            byte_resolver=byte_resolver,
            policy=selected,
            require_round_trip=require_round_trip,
        )
        linked.extend(item.linked_audio)
        provenance.extend(item.provenance)
        dispositions.extend(item.dispositions)
        if item.quality_report:
            quality_reports.append(dict(item.quality_report))

    return AudioReconciliationResult(
        linked_audio=tuple(linked),
        provenance=tuple(provenance),
        dispositions=tuple(dispositions),
        quality_report={
            "item_reports": quality_reports,
            "result_count": len(dispositions),
        },
        policy_identity=selected.identity,
    )


def _codec_from_media(media_type: str) -> str | None:
    media = str(media_type or "").casefold()
    if media in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return "wav"
    if media == "audio/mpeg":
        return "mp3"
    if media == "audio/ogg":
        return "ogg"
    if media == "audio/flac":
        return "flac"
    if media.startswith("audio/"):
        return media.split("/", 1)[1]
    return None


def _coerce_subject(
    subject: AudioReconciliationSubject | AbbyVoiceResponse | AbbyVoiceTemplate | None,
    *,
    spoken_text: str | None,
    spoken_text_sha256: str | None,
    slot_names: Sequence[str] | None,
    slot_values: Sequence[str] | None,
    policy_id: str,
    result: Any,
) -> AudioReconciliationSubject | None:
    if isinstance(subject, AudioReconciliationSubject):
        return subject
    if isinstance(subject, AbbyVoiceResponse):
        return AudioReconciliationSubject.from_response(subject, policy_id=policy_id)
    if isinstance(subject, AbbyVoiceTemplate):
        return AudioReconciliationSubject.from_template(subject, policy_id=policy_id)
    if subject is not None:
        raise TypeError("subject must be an AudioReconciliationSubject, response, or template")

    payload: dict[str, Any] = {}
    try:
        payload = _result_payload(result)
    except Exception:
        payload = {}
    lineage = _lineage_from_result(payload)
    text = spoken_text
    if not text:
        return None
    text_hash = spoken_text_sha256 or sha256_text(text)
    names = tuple(slot_names or ())
    values = tuple(slot_values or ())
    schema = str(lineage.get("subject_schema_version") or ABBY_VOICE_RESPONSE_V2)
    subject_id = str(lineage.get("subject_id") or f"subject:{text_hash[:16]}")
    return AudioReconciliationSubject(
        subject_id=subject_id,
        subject_schema_version=schema,
        spoken_text=text,
        text_sha256=text_hash,
        locale="en-US",
        source_manifest_id=str(lineage.get("source_manifest_id") or ""),
        source_release_id=str(lineage.get("publication_id") or ""),
        policy_id=str(lineage.get("policy_id") or policy_id),
        workset_id=str(lineage.get("workset_id") or ""),
        work_item_id=str(lineage.get("work_item_id") or ""),
        slot_names=names,
        slot_values=values,
        response_id=subject_id if schema == ABBY_VOICE_RESPONSE_V2 else None,
        template_id=subject_id if schema == ABBY_VOICE_TEMPLATE_V2 else None,
        segment_kind="template_shell" if schema == ABBY_VOICE_TEMPLATE_V2 else "response",
    )


__all__ = [
    "AUDIO_RECONCILIATION_SCHEMA_VERSION",
    "AUDIO_RECONCILIATION_VERSION",
    "AudioDisposition",
    "AudioDispositionReason",
    "AudioDispositionStatus",
    "AudioReconciliationResult",
    "AudioReconciliationSubject",
    "reconcile_voice_job_result",
    "reconcile_voice_job_results",
]
