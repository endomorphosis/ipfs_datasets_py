"""Bridge verified Abby bucket recovery into accelerator revalidation jobs.

This adapter is deliberately one-way:

* it accepts only byte/decode-verified recovery records;
* it imports their Xet-keyed local cache bytes into the accelerator's
  content-addressed artifact store;
* it creates ASR and audio-validation work, never TTS work; and
* it emits explicit legacy critical-fact bindings for later semantic
  reconciliation.

No recovered row becomes an ``AbbyVoiceAudio`` or ordinary legacy candidate at
this boundary. Promotion remains owned by ``voice.reconcile`` after the ASR and
validation receipts pass the pinned policy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from ipfs_accelerate_py.voice_jobs.executor import ArtifactPolicy, ArtifactResolver

from ...voice.audio_quality import (
    LEGACY_CRITICAL_SLOT_EXTRACTOR_VERSION,
    AudioQualityPolicy,
    derive_legacy_critical_slots,
    detect_media_type,
    find_unclassified_legacy_critical_facts,
    media_types_compatible,
)
from ...voice.bucket_audio_recovery import (
    AbbyVoiceBucketAudioRecovery,
    BucketAudioRecoveryError,
    bucket_audio_cache_path,
)
from ...voice.schema import ABBY_VOICE_RESPONSE_V2, stable_audio_id
from ...voice.workset import (
    AudioArtifactDescriptor,
    AudioWorkItem,
    AudioWorkManifest,
    AudioWorkOperation,
    AudioWorkReason,
    VoiceAudioWorkset,
)

BUCKET_AUDIO_REVALIDATION_PLAN_SCHEMA_VERSION = (
    "abby_voice_bucket_audio_revalidation_plan_v1"
)
BUCKET_AUDIO_REVALIDATION_BINDING_SCHEMA_VERSION = (
    "abby_voice_bucket_audio_revalidation_binding_v1"
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def legacy_bucket_audio_quality_policy() -> AudioQualityPolicy:
    """Return the pinned admission policy for historical bucket recordings.

    The historical IndexTTS runs use a mixture of sample rates (the live
    canary is 22.05 kHz), so sample rate remains decoder-reported rather than
    forced to the 24 kHz generation default. Mono audio, byte integrity,
    duration, silence/clipping, WER/CER, and critical slots remain mandatory.
    """

    return AudioQualityPolicy(
        policy_id="abby-voice-legacy-bucket-audio",
        policy_version="1.0.0",
        required_sample_rate_hz=None,
        required_channels=1,
    )


class CriticalFactClassification(StrEnum):
    """Whether the pinned legacy reference contains detected critical facts."""

    BOUND = "critical_facts_bound"
    UNCLASSIFIED = "likely_critical_facts_unclassified"
    NONE_DETECTED = "no_critical_facts_detected"


def classify_legacy_critical_facts(text: str) -> CriticalFactClassification:
    """Classify a legacy response without allowing likely facts to fall through."""

    critical_slots = derive_legacy_critical_slots(text)
    if find_unclassified_legacy_critical_facts(text, critical_slots):
        return CriticalFactClassification.UNCLASSIFIED
    if critical_slots:
        return CriticalFactClassification.BOUND
    return CriticalFactClassification.NONE_DETECTED


@dataclass(frozen=True, slots=True)
class BucketAudioRevalidationBinding:
    """Privacy-conscious binding from one recovery record to scheduled work."""

    record_id: str
    response_id: str
    raw_sha256: str
    audio_id: str
    artifact_uri: str
    artifact_cid: str
    asr_work_id: str
    validation_work_id: str
    critical_fact_classification: CriticalFactClassification
    slot_names: tuple[str, ...] = ()
    slot_values: tuple[str, ...] = ()
    extractor_version: str = LEGACY_CRITICAL_SLOT_EXTRACTOR_VERSION
    schema_version: str = BUCKET_AUDIO_REVALIDATION_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "record_id",
            "response_id",
            "audio_id",
            "artifact_uri",
            "artifact_cid",
            "asr_work_id",
            "validation_work_id",
            "extractor_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value.strip() != value:
                raise ValueError(f"{name} must be a stable non-empty identity")
        if (
            not isinstance(self.raw_sha256, str)
            or len(self.raw_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.raw_sha256)
        ):
            raise ValueError("raw_sha256 must be a full lowercase SHA-256")
        if len(self.slot_names) != len(self.slot_values):
            raise ValueError("slot names and values must have equal lengths")
        classification = CriticalFactClassification(
            self.critical_fact_classification
        )
        if classification is CriticalFactClassification.BOUND and not self.slot_names:
            raise ValueError("bound critical facts require at least one slot")
        if classification is CriticalFactClassification.UNCLASSIFIED:
            raise ValueError(
                "likely-but-unclassified critical facts cannot enter scheduled work"
            )
        if (
            classification is CriticalFactClassification.NONE_DETECTED
            and (self.slot_names or self.slot_values)
        ):
            raise ValueError("no-critical-facts classification must have no slots")
        if self.schema_version != BUCKET_AUDIO_REVALIDATION_BINDING_SCHEMA_VERSION:
            raise ValueError("unsupported bucket audio revalidation binding schema")
        object.__setattr__(self, "critical_fact_classification", classification)
        object.__setattr__(self, "slot_names", tuple(self.slot_names))
        object.__setattr__(self, "slot_values", tuple(self.slot_values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_cid": self.artifact_cid,
            "artifact_uri": self.artifact_uri,
            "asr_work_id": self.asr_work_id,
            "audio_id": self.audio_id,
            "critical_fact_classification": self.critical_fact_classification.value,
            "extractor_version": self.extractor_version,
            "raw_sha256": self.raw_sha256,
            "record_id": self.record_id,
            "response_id": self.response_id,
            "schema_version": self.schema_version,
            "slot_names": list(self.slot_names),
            "slot_values": list(self.slot_values),
            "validation_work_id": self.validation_work_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BucketAudioRevalidationBinding:
        if not isinstance(value, Mapping):
            raise TypeError("revalidation binding must be a mapping")
        return cls(
            record_id=str(value["record_id"]),
            response_id=str(value["response_id"]),
            raw_sha256=str(value["raw_sha256"]),
            audio_id=str(value["audio_id"]),
            artifact_uri=str(value["artifact_uri"]),
            artifact_cid=str(value["artifact_cid"]),
            asr_work_id=str(value["asr_work_id"]),
            validation_work_id=str(value["validation_work_id"]),
            critical_fact_classification=CriticalFactClassification(
                value["critical_fact_classification"]
            ),
            slot_names=tuple(value.get("slot_names") or ()),
            slot_values=tuple(value.get("slot_values") or ()),
            extractor_version=str(
                value.get("extractor_version") or LEGACY_CRITICAL_SLOT_EXTRACTOR_VERSION
            ),
            schema_version=str(
                value.get("schema_version")
                or BUCKET_AUDIO_REVALIDATION_BINDING_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class BucketAudioRevalidationPlan:
    """Deterministic workset plus exact record/work/critical-fact bindings."""

    recovery_id: str
    workset: VoiceAudioWorkset
    policy: AudioQualityPolicy
    bindings: tuple[BucketAudioRevalidationBinding, ...]
    schema_version: str = BUCKET_AUDIO_REVALIDATION_PLAN_SCHEMA_VERSION
    revalidation_plan_id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        if not isinstance(self.recovery_id, str) or not self.recovery_id:
            raise ValueError("recovery_id must be non-empty")
        if self.workset.source_manifest_id != self.recovery_id:
            raise ValueError("workset source manifest must bind the recovery")
        if self.workset.policy_id != self.policy.identity:
            raise ValueError("workset policy does not match the pinned policy")
        bindings = tuple(sorted(self.bindings, key=lambda item: item.response_id))
        if len({item.response_id for item in bindings}) != len(bindings):
            raise ValueError("revalidation response IDs must be unique")
        if {item.response_id for item in bindings} != {
            item.subject_id for item in self.workset.asr_manifest.items
        }:
            raise ValueError("bindings must cover every ASR work item exactly")
        if self.workset.tts_manifest.items:
            raise ValueError("bucket audio revalidation must never schedule TTS")
        if self.schema_version != BUCKET_AUDIO_REVALIDATION_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported bucket audio revalidation plan schema")
        object.__setattr__(self, "bindings", bindings)
        computed = (
            "abby-voice-bucket-audio-revalidation:sha256:"
            + sha256(_canonical_bytes(self.identity_dict())).hexdigest()
        )
        if self.revalidation_plan_id and self.revalidation_plan_id != computed:
            raise ValueError("revalidation_plan_id does not match plan content")
        object.__setattr__(self, "revalidation_plan_id", computed)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "bindings": [item.to_dict() for item in self.bindings],
            "policy": self.policy.to_dict(),
            "recovery_id": self.recovery_id,
            "schema_version": self.schema_version,
            "workset": self.workset.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_dict(),
            "revalidation_plan_id": self.revalidation_plan_id,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BucketAudioRevalidationPlan:
        """Strictly rehydrate a sealed schedule plan from its canonical mapping."""

        if not isinstance(value, Mapping):
            raise TypeError("revalidation plan must be a mapping")
        required = {
            "bindings",
            "policy",
            "recovery_id",
            "schema_version",
            "workset",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(f"revalidation plan missing fields {missing!r}")
        if value.get("schema_version") != BUCKET_AUDIO_REVALIDATION_PLAN_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported revalidation plan schema {value.get('schema_version')!r}"
            )
        bindings_payload = value["bindings"]
        if not isinstance(bindings_payload, list) or not all(
            isinstance(item, Mapping) for item in bindings_payload
        ):
            raise TypeError("revalidation plan bindings must be a list of mappings")
        workset = VoiceAudioWorkset.from_dict(value["workset"])
        policy = AudioQualityPolicy.from_dict(value["policy"])
        plan = cls(
            recovery_id=str(value["recovery_id"]),
            workset=workset,
            policy=policy,
            bindings=tuple(
                BucketAudioRevalidationBinding.from_dict(item)
                for item in bindings_payload
            ),
            schema_version=str(value["schema_version"]),
            revalidation_plan_id=str(value.get("revalidation_plan_id") or ""),
        )
        return plan

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> BucketAudioRevalidationPlan:
        if isinstance(value, bytes | bytearray):
            try:
                value = bytes(value).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("revalidation plan JSON must be UTF-8") from exc
        if not isinstance(value, str):
            raise TypeError("revalidation plan JSON must be str or bytes")
        try:
            payload = json.loads(value)
        except ValueError as exc:
            raise ValueError(f"revalidation plan JSON is invalid: {exc}") from exc
        return cls.from_dict(payload)


_MEDIA_SUFFIX = {
    "audio/flac": "flac",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
}


def build_bucket_audio_revalidation_plan(
    recovery: AbbyVoiceBucketAudioRecovery,
    *,
    cache_dir: str | Path,
    artifact_root: str | Path,
    policy: AudioQualityPolicy | None = None,
    max_artifact_bytes: int = 32 * 1024 * 1024,
) -> BucketAudioRevalidationPlan:
    """Import verified recovery bytes and build ASR/validation-only work.

    ``cache_dir`` is the exact object-cache root passed to
    ``recover_abby_voice_bucket_audio``. Workers must use the same
    ``artifact_root`` so the emitted ``ipfs://`` descriptors resolve through
    the accelerator's content-addressed cache.
    """

    if not isinstance(recovery, AbbyVoiceBucketAudioRecovery):
        raise TypeError("recovery must be an AbbyVoiceBucketAudioRecovery")
    if (
        isinstance(max_artifact_bytes, bool)
        or not isinstance(max_artifact_bytes, int)
        or max_artifact_bytes <= 0
    ):
        raise ValueError("max_artifact_bytes must be a positive integer")
    selected_policy = policy or legacy_bucket_audio_quality_policy()
    cache_root = Path(cache_dir).expanduser().resolve()
    output_root = Path(artifact_root).expanduser().resolve()
    if cache_root == output_root:
        raise ValueError("recovery cache and accelerator artifact roots must differ")

    critical_assessments: list[
        tuple[
            CriticalFactClassification,
            tuple[tuple[str, str], ...],
        ]
    ] = []
    for record in recovery.records:
        critical_slots = derive_legacy_critical_slots(record.spoken_text)
        unclassified_markers = find_unclassified_legacy_critical_facts(
            record.spoken_text,
            critical_slots,
        )
        if unclassified_markers:
            marker_list = ", ".join(unclassified_markers)
            raise BucketAudioRecoveryError(
                f"record {record.response_id!r} is classified "
                f"{CriticalFactClassification.UNCLASSIFIED.value!r} by "
                f"{LEGACY_CRITICAL_SLOT_EXTRACTOR_VERSION}: {marker_list}"
            )
        classification = (
            CriticalFactClassification.BOUND
            if critical_slots
            else CriticalFactClassification.NONE_DETECTED
        )
        critical_assessments.append((classification, critical_slots))

    resolver = ArtifactResolver(
        ArtifactPolicy(
            output_root=output_root,
            max_input_bytes=max_artifact_bytes,
            max_decoded_bytes=max_artifact_bytes,
            max_duration_ms=selected_policy.max_duration_ms,
        )
    )

    asr_items: list[AudioWorkItem] = []
    validation_items: list[AudioWorkItem] = []
    bindings: list[BucketAudioRevalidationBinding] = []
    for record, critical_assessment in zip(
        recovery.records,
        critical_assessments,
        strict=True,
    ):
        critical_classification, critical_slots = critical_assessment
        if (
            record.decode_probe is None
            or not record.decode_probe.passed
            or record.decode_probe.details.get("full_frame_decode") is not True
        ):
            raise BucketAudioRecoveryError(
                f"record {record.response_id!r} lacks passing full-frame decode evidence"
            )
        if record.verified_size_bytes > max_artifact_bytes:
            raise BucketAudioRecoveryError(
                f"record {record.response_id!r} exceeds the artifact byte ceiling"
            )
        cache_path = bucket_audio_cache_path(cache_root, record.xet_hash)
        if cache_path.is_symlink() or not cache_path.is_file():
            raise BucketAudioRecoveryError(
                f"verified cache object is missing or unsafe for {record.response_id!r}"
            )
        payload = cache_path.read_bytes()
        if len(payload) != record.verified_size_bytes:
            raise BucketAudioRecoveryError(
                f"verified cache size changed for {record.response_id!r}"
            )
        if sha256(payload).hexdigest() != record.raw_sha256:
            raise BucketAudioRecoveryError(
                f"verified cache SHA-256 changed for {record.response_id!r}"
            )
        detected_media = detect_media_type(payload)
        if detected_media is None or not media_types_compatible(
            record.media_type, detected_media
        ):
            raise BucketAudioRecoveryError(
                f"verified cache media changed for {record.response_id!r}"
            )
        suffix = _MEDIA_SUFFIX.get(detected_media)
        if suffix is None:
            raise BucketAudioRecoveryError(
                f"unsupported recovery media type {detected_media!r}"
            )
        persisted = resolver.persist(
            payload,
            suffix=suffix,
            media_type=detected_media,
        )
        if (
            persisted["sha256"] != record.raw_sha256
            or persisted["size_bytes"] != record.verified_size_bytes
        ):
            raise BucketAudioRecoveryError(
                f"accelerator artifact import changed {record.response_id!r}"
            )
        descriptor = AudioArtifactDescriptor(
            audio_id=stable_audio_id(record.raw_sha256),
            content_sha256=record.raw_sha256,
            byte_length=record.verified_size_bytes,
            media_type=detected_media,
            uri=str(persisted["uri"]),
            ipfs_cid=str(persisted["cid"]),
        )
        common = {
            "reason": AudioWorkReason.EXPLICIT_REVALIDATION,
            "subject_id": record.response_id,
            "subject_schema_version": ABBY_VOICE_RESPONSE_V2,
            "spoken_text": record.spoken_text,
            "text_sha256": record.canonical_text_sha256,
            "locale": record.locale,
            "source_manifest_id": recovery.recovery_id,
            "policy_id": selected_policy.identity,
            "audio": descriptor,
        }
        asr_item = AudioWorkItem(
            operation=AudioWorkOperation.ASR,
            **common,
        )
        validation_item = AudioWorkItem(
            operation=AudioWorkOperation.VALIDATE,
            depends_on=(asr_item.work_id,),
            **common,
        )
        asr_items.append(asr_item)
        validation_items.append(validation_item)

        bindings.append(
            BucketAudioRevalidationBinding(
                record_id=record.record_id,
                response_id=record.response_id,
                raw_sha256=record.raw_sha256,
                audio_id=descriptor.audio_id,
                artifact_uri=descriptor.uri,
                artifact_cid=descriptor.ipfs_cid,
                asr_work_id=asr_item.work_id,
                validation_work_id=validation_item.work_id,
                critical_fact_classification=critical_classification,
                slot_names=tuple(name for name, _value in critical_slots),
                slot_values=tuple(value for _name, value in critical_slots),
            )
        )

    workset = VoiceAudioWorkset(
        tts_manifest=AudioWorkManifest(AudioWorkOperation.TTS),
        asr_manifest=AudioWorkManifest(
            AudioWorkOperation.ASR, tuple(asr_items)
        ),
        validation_manifest=AudioWorkManifest(
            AudioWorkOperation.VALIDATE, tuple(validation_items)
        ),
        source_manifest_id=recovery.recovery_id,
        policy_id=selected_policy.identity,
    )
    return BucketAudioRevalidationPlan(
        recovery_id=recovery.recovery_id,
        workset=workset,
        policy=selected_policy,
        bindings=tuple(bindings),
    )


__all__ = [
    "BUCKET_AUDIO_REVALIDATION_BINDING_SCHEMA_VERSION",
    "BUCKET_AUDIO_REVALIDATION_PLAN_SCHEMA_VERSION",
    "BucketAudioRevalidationBinding",
    "BucketAudioRevalidationPlan",
    "CriticalFactClassification",
    "build_bucket_audio_revalidation_plan",
    "classify_legacy_critical_facts",
    "legacy_bucket_audio_quality_policy",
]
