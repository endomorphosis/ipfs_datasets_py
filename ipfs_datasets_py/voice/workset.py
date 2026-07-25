"""Deterministic, execution-free audio work planning for Abby voice.

The workset is a data-plane plan only.  It never submits work or contains
audio bytes.  Separate TTS, ASR, and validation manifests make the downstream
contract explicit while retaining one content-addressed workset identity.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Any

from .schema import AbbyVoiceAudio, AbbyVoiceResponse, AbbyVoiceTemplate, sha256_text

VOICE_AUDIO_WORKSET_SCHEMA_VERSION = "abby_voice_audio_workset_v1"
VOICE_AUDIO_WORK_MANIFEST_SCHEMA_VERSION = "abby_voice_audio_work_manifest_v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    return f"{prefix}:sha256:{sha256(_canonical_bytes(value)).hexdigest()}"


def _require_identity(name: str, value: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be a stable non-empty identity")
    return value


class AudioWorkReason(StrEnum):
    MISSING = "missing"
    CORRUPT = "corrupt"
    STALE_POLICY = "stale_policy"
    EXPLICIT_REVALIDATION = "explicit_revalidation"


class AudioWorkOperation(StrEnum):
    TTS = "tts"
    ASR = "asr"
    VALIDATE = "audio_validation"


@dataclass(frozen=True, slots=True)
class AudioArtifactDescriptor:
    """Immutable audio identity; raw or base64 audio is deliberately absent."""

    audio_id: str
    content_sha256: str
    byte_length: int
    media_type: str
    uri: str = ""
    ipfs_cid: str = ""

    def __post_init__(self) -> None:
        _require_identity("audio_id", self.audio_id)
        if not _SHA256_RE.fullmatch(self.content_sha256):
            raise ValueError("content_sha256 must be a full lowercase SHA-256")
        if isinstance(self.byte_length, bool) or not isinstance(self.byte_length, int) or self.byte_length < 0:
            raise ValueError("byte_length must be a non-negative integer")
        if not isinstance(self.media_type, str) or not self.media_type.startswith("audio/"):
            raise ValueError("media_type must be audio/*")
        if not self.uri and not self.ipfs_cid:
            raise ValueError("audio descriptor requires uri or ipfs_cid")

    @classmethod
    def from_audio(cls, row: AbbyVoiceAudio) -> "AudioArtifactDescriptor":
        if row.byte_length is None:
            raise ValueError(f"audio {row.audio_id!r} has no verified byte_length")
        return cls(
            audio_id=row.audio_id,
            content_sha256=row.content_sha256,
            byte_length=row.byte_length,
            media_type=row.mime_type,
            uri=row.uri or "",
            ipfs_cid=row.ipfs_cid or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "audio_id": self.audio_id,
            "byte_length": self.byte_length,
            "content_sha256": self.content_sha256,
            "ipfs_cid": self.ipfs_cid,
            "media_type": self.media_type,
            "uri": self.uri,
        }


@dataclass(frozen=True, slots=True)
class AudioWorkItem:
    operation: AudioWorkOperation
    reason: AudioWorkReason
    subject_id: str
    subject_schema_version: str
    spoken_text: str
    text_sha256: str
    locale: str
    source_manifest_id: str
    policy_id: str
    audio: AudioArtifactDescriptor | None = None
    depends_on: tuple[str, ...] = ()
    work_id: str = ""

    def __post_init__(self) -> None:
        operation = AudioWorkOperation(self.operation)
        reason = AudioWorkReason(self.reason)
        for name in ("subject_id", "subject_schema_version", "locale", "source_manifest_id", "policy_id"):
            _require_identity(name, getattr(self, name))
        if not isinstance(self.spoken_text, str) or not self.spoken_text.strip():
            raise ValueError("spoken_text must not be empty")
        if self.text_sha256 != sha256_text(self.spoken_text):
            raise ValueError("text_sha256 must equal SHA-256(spoken_text UTF-8)")
        dependencies = tuple(sorted(set(self.depends_on)))
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "depends_on", dependencies)
        computed = _stable_id("abby-voice-work", self.identity_dict())
        if self.work_id and self.work_id != computed:
            raise ValueError("work_id does not match deterministic work content")
        object.__setattr__(self, "work_id", computed)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "audio": self.audio.to_dict() if self.audio else None,
            "depends_on": list(self.depends_on),
            "locale": self.locale,
            "operation": self.operation.value,
            "policy_id": self.policy_id,
            "reason": self.reason.value,
            "source_manifest_id": self.source_manifest_id,
            "spoken_text": self.spoken_text,
            "subject_id": self.subject_id,
            "subject_schema_version": self.subject_schema_version,
            "text_sha256": self.text_sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.identity_dict()
        result["work_id"] = self.work_id
        return result


@dataclass(frozen=True, slots=True)
class AudioWorkManifest:
    operation: AudioWorkOperation
    items: tuple[AudioWorkItem, ...] = ()
    schema_version: str = VOICE_AUDIO_WORK_MANIFEST_SCHEMA_VERSION
    manifest_id: str = ""

    def __post_init__(self) -> None:
        operation = AudioWorkOperation(self.operation)
        items = tuple(sorted(self.items, key=lambda item: item.work_id))
        if any(item.operation is not operation for item in items):
            raise ValueError("manifest contains a different work operation")
        if len({item.work_id for item in items}) != len(items):
            raise ValueError("manifest work IDs must be unique")
        if self.schema_version != VOICE_AUDIO_WORK_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported audio work manifest schema")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "items", items)
        computed = _stable_id("abby-voice-work-manifest", self.identity_dict())
        if self.manifest_id and self.manifest_id != computed:
            raise ValueError("manifest_id does not match deterministic content")
        object.__setattr__(self, "manifest_id", computed)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "operation": self.operation.value,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.identity_dict()
        result["manifest_id"] = self.manifest_id
        return result

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class VoiceAudioWorkset:
    """One deterministic envelope containing TTS, ASR, and validation plans."""

    tts_manifest: AudioWorkManifest
    asr_manifest: AudioWorkManifest
    validation_manifest: AudioWorkManifest
    source_manifest_id: str
    policy_id: str
    schema_version: str = VOICE_AUDIO_WORKSET_SCHEMA_VERSION
    workset_id: str = ""

    def __post_init__(self) -> None:
        _require_identity("source_manifest_id", self.source_manifest_id)
        _require_identity("policy_id", self.policy_id)
        expected = (
            (self.tts_manifest, AudioWorkOperation.TTS),
            (self.asr_manifest, AudioWorkOperation.ASR),
            (self.validation_manifest, AudioWorkOperation.VALIDATE),
        )
        if any(manifest.operation is not operation for manifest, operation in expected):
            raise ValueError("workset manifest operation mismatch")
        if self.schema_version != VOICE_AUDIO_WORKSET_SCHEMA_VERSION:
            raise ValueError("unsupported voice audio workset schema")
        computed = _stable_id("abby-voice-workset", self.identity_dict())
        if self.workset_id and self.workset_id != computed:
            raise ValueError("workset_id does not match deterministic content")
        object.__setattr__(self, "workset_id", computed)

    @classmethod
    def build(
        cls,
        *,
        responses: Iterable[AbbyVoiceResponse] = (),
        templates: Iterable[AbbyVoiceTemplate] = (),
        audio: Iterable[AbbyVoiceAudio] = (),
        source_manifest_id: str,
        policy_id: str,
        corrupt_subject_ids: Iterable[str] = (),
        stale_policy_subject_ids: Iterable[str] = (),
        revalidate_subject_ids: Iterable[str] = (),
        intentionally_text_only_subject_ids: Iterable[str] = (),
    ) -> "VoiceAudioWorkset":
        subjects = [
            (row.response_id, row.schema_version, row.spoken_text, row.locale)
            for row in responses
        ] + [
            (row.template_id, row.schema_version, row.spoken_template or row.template_text, row.locale)
            for row in templates
        ]
        subjects.sort(key=lambda item: (item[1], item[0]))
        by_subject: dict[str, list[AbbyVoiceAudio]] = {}
        for row in audio:
            subject_id = row.response_id or row.template_id
            if subject_id:
                by_subject.setdefault(subject_id, []).append(row)
        corrupt = set(corrupt_subject_ids)
        stale = set(stale_policy_subject_ids)
        revalidate = set(revalidate_subject_ids)
        text_only = set(intentionally_text_only_subject_ids)
        unknown = (corrupt | stale | revalidate | text_only) - {item[0] for item in subjects}
        if unknown:
            raise ValueError(f"work policy names unknown subject IDs: {sorted(unknown)}")

        tts: list[AudioWorkItem] = []
        asr: list[AudioWorkItem] = []
        validation: list[AudioWorkItem] = []
        for subject_id, schema_version, spoken_text, locale in subjects:
            if subject_id in text_only:
                continue
            existing = sorted(by_subject.get(subject_id, ()), key=lambda row: row.audio_id)
            descriptor: AudioArtifactDescriptor | None = None
            for row in existing:
                try:
                    descriptor = AudioArtifactDescriptor.from_audio(row)
                    break
                except ValueError:
                    continue
            if subject_id in corrupt:
                reason = AudioWorkReason.CORRUPT
            elif subject_id in stale:
                reason = AudioWorkReason.STALE_POLICY
            elif descriptor is None:
                reason = AudioWorkReason.MISSING
            elif subject_id in revalidate:
                reason = AudioWorkReason.EXPLICIT_REVALIDATION
            else:
                continue

            text_digest = sha256_text(spoken_text)
            if reason is AudioWorkReason.EXPLICIT_REVALIDATION:
                asr_item = AudioWorkItem(
                    AudioWorkOperation.ASR, reason, subject_id, schema_version,
                    spoken_text, text_digest, locale, source_manifest_id, policy_id,
                    audio=descriptor,
                )
            else:
                tts_item = AudioWorkItem(
                    AudioWorkOperation.TTS, reason, subject_id, schema_version,
                    spoken_text, text_digest, locale, source_manifest_id, policy_id,
                )
                tts.append(tts_item)
                asr_item = AudioWorkItem(
                    AudioWorkOperation.ASR, reason, subject_id, schema_version,
                    spoken_text, text_digest, locale, source_manifest_id, policy_id,
                    depends_on=(tts_item.work_id,),
                )
            asr.append(asr_item)
            validation.append(
                AudioWorkItem(
                    AudioWorkOperation.VALIDATE, reason, subject_id, schema_version,
                    spoken_text, text_digest, locale, source_manifest_id, policy_id,
                    audio=descriptor if reason is AudioWorkReason.EXPLICIT_REVALIDATION else None,
                    depends_on=(asr_item.work_id,),
                )
            )
        return cls(
            tts_manifest=AudioWorkManifest(AudioWorkOperation.TTS, tuple(tts)),
            asr_manifest=AudioWorkManifest(AudioWorkOperation.ASR, tuple(asr)),
            validation_manifest=AudioWorkManifest(AudioWorkOperation.VALIDATE, tuple(validation)),
            source_manifest_id=source_manifest_id,
            policy_id=policy_id,
        )

    @property
    def items(self) -> tuple[AudioWorkItem, ...]:
        return (
            *self.tts_manifest.items,
            *self.asr_manifest.items,
            *self.validation_manifest.items,
        )

    def identity_dict(self) -> dict[str, Any]:
        return {
            "asr_manifest": self.asr_manifest.to_dict(),
            "policy_id": self.policy_id,
            "schema_version": self.schema_version,
            "source_manifest_id": self.source_manifest_id,
            "tts_manifest": self.tts_manifest.to_dict(),
            "validation_manifest": self.validation_manifest.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.identity_dict()
        result["workset_id"] = self.workset_id
        return result

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())


WorkManifest = AudioWorkManifest
WorkReason = AudioWorkReason

__all__ = [
    "AudioArtifactDescriptor",
    "AudioWorkItem",
    "AudioWorkManifest",
    "AudioWorkOperation",
    "AudioWorkReason",
    "VoiceAudioWorkset",
    "WorkManifest",
    "WorkReason",
]
