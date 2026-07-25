"""Fail-closed reconciliation of legacy Abby audio candidates.

Legacy paths, basenames, and fuzzy text are discovery hints, never identity.
Only an exact canonical subject/text match whose downloaded bytes satisfy the
pinned inventory, media, and decode gates can produce an audio row.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any

from ..huggingface.bucket import HuggingFaceBucketInventory, HuggingFaceBucketObject
from .normalize import normalize_indextts_spoken_text, normalized_text_identity
from .schema import (
    AbbyVoiceAudio,
    AbbyVoiceResponse,
    AbbyVoiceTemplate,
    sha256_text,
    stable_audio_id,
)

LEGACY_AUDIO_RECONCILIATION_SCHEMA_VERSION = "abby_voice_legacy_audio_reconciliation_v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MEDIA = frozenset({"audio/mpeg", "audio/wav", "audio/x-wav", "audio/ogg", "audio/flac"})


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _spoken_identity(value: str) -> str:
    return normalized_text_identity(normalize_indextts_spoken_text(value))


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be non-empty without surrounding whitespace")
    return value


def _path(value: str) -> str:
    value = _text("path", value)
    parsed = PurePosixPath(value)
    if "\\" in value or parsed.is_absolute() or parsed.as_posix() != value or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise ValueError("legacy audio paths must be normalized root-relative POSIX paths")
    return value


class LegacyDispositionStatus(StrEnum):
    LINKED = "linked"
    REVIEW = "review"
    QUARANTINED = "quarantined"
    UNCLAIMED = "unclaimed"


class LegacyDispositionReason(StrEnum):
    EXACT_VERIFIED_LINK = "exact_verified_link"
    FUZZY_MATCH_REVIEW_REQUIRED = "fuzzy_match_review_required"
    AMBIGUOUS_PATH_REVIEW_REQUIRED = "ambiguous_path_review_required"
    UNKNOWN_SUBJECT = "unknown_subject"
    TEXT_IDENTITY_MISMATCH = "text_identity_mismatch"
    INVENTORY_OBJECT_MISSING = "inventory_object_missing"
    SHA256_MISMATCH = "sha256_mismatch"
    SIZE_MISMATCH = "size_mismatch"
    UNSUPPORTED_MEDIA = "unsupported_media"
    MEDIA_MISMATCH = "media_mismatch"
    DECODE_FAILED = "decode_failed"
    BYTES_UNAVAILABLE = "bytes_unavailable"
    NON_AUDIO_INVENTORY_OBJECT = "non_audio_inventory_object"
    UNCLAIMED_AUDIO_OBJECT = "unclaimed_audio_object"


@dataclass(frozen=True, slots=True)
class LegacyAudioCandidate:
    candidate_id: str
    subject_id: str
    spoken_text: str
    paths: tuple[str, ...]
    expected_sha256: str
    media_type: str
    locale: str = "en-US"

    def __post_init__(self) -> None:
        _text("candidate_id", self.candidate_id)
        _text("subject_id", self.subject_id)
        _text("spoken_text", self.spoken_text)
        paths = tuple(sorted({_path(item) for item in self.paths}))
        if not paths:
            raise ValueError("legacy audio candidate requires at least one path")
        if (
            not isinstance(self.expected_sha256, str)
            or re.fullmatch(r"[0-9a-f]{8,64}", self.expected_sha256) is None
        ):
            raise ValueError("expected_sha256 must be a lowercase hexadecimal hash candidate")
        media = self.media_type.casefold()
        if media not in _ALLOWED_MEDIA:
            raise ValueError("media_type is not a supported audio type")
        object.__setattr__(self, "paths", paths)
        object.__setattr__(self, "media_type", media)

    @property
    def source_ref(self) -> str:
        return f"legacy-candidate:{self.candidate_id}"

    @property
    def text_sha256(self) -> str:
        return sha256_text(_spoken_identity(self.spoken_text))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "expected_sha256": self.expected_sha256,
            "locale": self.locale,
            "media_type": self.media_type,
            "paths": list(self.paths),
            "spoken_text": self.spoken_text,
            "subject_id": self.subject_id,
            "text_sha256": self.text_sha256,
        }


@dataclass(frozen=True, slots=True)
class LegacyAudioDisposition:
    source_ref: str
    source_sha256: str
    status: LegacyDispositionStatus
    reason: LegacyDispositionReason
    candidate_id: str = ""
    subject_id: str = ""
    inventory_path: str = ""
    audio_id: str = ""

    def __post_init__(self) -> None:
        _text("source_ref", self.source_ref)
        if not _SHA256_RE.fullmatch(self.source_sha256):
            raise ValueError("source_sha256 must be a full lowercase SHA-256")
        object.__setattr__(self, "status", LegacyDispositionStatus(self.status))
        object.__setattr__(self, "reason", LegacyDispositionReason(self.reason))

    def to_dict(self) -> dict[str, str]:
        return {
            "audio_id": self.audio_id,
            "candidate_id": self.candidate_id,
            "inventory_path": self.inventory_path,
            "reason": self.reason.value,
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
            "status": self.status.value,
            "subject_id": self.subject_id,
        }


@dataclass(frozen=True, slots=True)
class LegacyAudioReconciliation:
    linked_audio: tuple[AbbyVoiceAudio, ...] = ()
    dispositions: tuple[LegacyAudioDisposition, ...] = ()
    inventory_sha256: str = ""
    schema_version: str = LEGACY_AUDIO_RECONCILIATION_SCHEMA_VERSION
    reconciliation_id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        linked = tuple(sorted(self.linked_audio, key=lambda row: row.audio_id))
        dispositions = tuple(sorted(self.dispositions, key=lambda item: item.source_ref))
        refs = [item.source_ref for item in dispositions]
        if len(refs) != len(set(refs)):
            raise ValueError("every legacy source must have exactly one disposition")
        if not _SHA256_RE.fullmatch(self.inventory_sha256):
            raise ValueError("inventory_sha256 must be a full lowercase SHA-256")
        if self.schema_version != LEGACY_AUDIO_RECONCILIATION_SCHEMA_VERSION:
            raise ValueError("unsupported legacy reconciliation schema")
        object.__setattr__(self, "linked_audio", linked)
        object.__setattr__(self, "dispositions", dispositions)
        identity = {
            "dispositions": [item.to_dict() for item in dispositions],
            "inventory_sha256": self.inventory_sha256,
            "linked_audio": [row.to_dict() for row in linked],
            "schema_version": self.schema_version,
        }
        computed = f"abby-voice-legacy:sha256:{sha256(_canonical_bytes(identity)).hexdigest()}"
        if self.reconciliation_id and self.reconciliation_id != computed:
            raise ValueError("reconciliation_id does not match deterministic content")
        object.__setattr__(self, "reconciliation_id", computed)

    @property
    def review_quarantine(self) -> tuple[LegacyAudioDisposition, ...]:
        return tuple(
            item for item in self.dispositions
            if item.status in {LegacyDispositionStatus.REVIEW, LegacyDispositionStatus.QUARANTINED}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dispositions": [item.to_dict() for item in self.dispositions],
            "inventory_sha256": self.inventory_sha256,
            "linked_audio": [row.to_dict() for row in self.linked_audio],
            "reconciliation_id": self.reconciliation_id,
            "schema_version": self.schema_version,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())


def _detected_media(payload: bytes) -> str | None:
    if payload.startswith(b"RIFF") and payload[8:12] == b"WAVE":
        return "audio/wav"
    if payload.startswith(b"ID3") or payload.startswith((b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
        return "audio/mpeg"
    if payload.startswith(b"OggS"):
        return "audio/ogg"
    if payload.startswith(b"fLaC"):
        return "audio/flac"
    return None


def _inventory_ref(inventory: HuggingFaceBucketInventory, item: HuggingFaceBucketObject) -> str:
    return f"bucket-object:{inventory.bucket_id}:{item.path}"


def reconcile_legacy_audio_candidates(
    *,
    subjects: Iterable[AbbyVoiceResponse | AbbyVoiceTemplate],
    candidates: Iterable[LegacyAudioCandidate],
    inventory: HuggingFaceBucketInventory,
    byte_resolver: Callable[[str], bytes | bytearray | memoryview | None],
    decode_validator: Callable[[bytes, str], bool] | None = None,
) -> LegacyAudioReconciliation:
    """Reconcile candidates without inference, network access, or fuzzy promotion."""

    subject_map: dict[str, tuple[str, str, str, str]] = {}
    for row in subjects:
        if isinstance(row, AbbyVoiceResponse):
            values = (row.schema_version, row.spoken_text, row.locale, "response")
            subject_id = row.response_id
        elif isinstance(row, AbbyVoiceTemplate):
            values = (row.schema_version, row.spoken_template or row.template_text, row.locale, "template")
            subject_id = row.template_id
        else:
            raise TypeError("subjects must contain canonical response or template rows")
        if subject_id in subject_map:
            raise ValueError(f"duplicate subject ID {subject_id!r}")
        subject_map[subject_id] = values
    candidate_rows = tuple(sorted(candidates, key=lambda item: item.candidate_id))
    if len({item.candidate_id for item in candidate_rows}) != len(candidate_rows):
        raise ValueError("candidate IDs must be unique")
    candidate_groups: dict[tuple[str, str], list[LegacyAudioCandidate]] = {}
    for candidate in candidate_rows:
        candidate_groups.setdefault(
            (candidate.subject_id, _spoken_identity(candidate.spoken_text)), []
        ).append(candidate)
    ambiguous_candidate_ids = {
        candidate.candidate_id
        for group in candidate_groups.values()
        if len(group) > 1
        for candidate in group
    }
    objects = {item.path: item for item in inventory.objects}
    dispositions: dict[str, LegacyAudioDisposition] = {}
    linked: list[AbbyVoiceAudio] = []
    def candidate_disposition(
        candidate: LegacyAudioCandidate,
        status: LegacyDispositionStatus,
        reason: LegacyDispositionReason,
        *,
        path: str = "",
        audio_id: str = "",
    ) -> None:
        dispositions[candidate.source_ref] = LegacyAudioDisposition(
            source_ref=candidate.source_ref,
            source_sha256=sha256(_canonical_bytes(candidate.to_dict())).hexdigest(),
            status=status,
            reason=reason,
            candidate_id=candidate.candidate_id,
            subject_id=candidate.subject_id,
            inventory_path=path,
            audio_id=audio_id,
        )

    for candidate in candidate_rows:
        subject = subject_map.get(candidate.subject_id)
        if subject is None:
            candidate_disposition(candidate, LegacyDispositionStatus.REVIEW, LegacyDispositionReason.UNKNOWN_SUBJECT)
            continue
        _, subject_text, locale, subject_kind = subject
        if _spoken_identity(candidate.spoken_text) != _spoken_identity(subject_text):
            candidate_disposition(candidate, LegacyDispositionStatus.REVIEW, LegacyDispositionReason.FUZZY_MATCH_REVIEW_REQUIRED)
            continue
        if len(candidate.paths) != 1 or candidate.candidate_id in ambiguous_candidate_ids:
            candidate_disposition(candidate, LegacyDispositionStatus.REVIEW, LegacyDispositionReason.AMBIGUOUS_PATH_REVIEW_REQUIRED)
            continue
        path = candidate.paths[0]
        item = objects.get(path)
        if item is None:
            basename_matches = [
                inventory_path
                for inventory_path in objects
                if PurePosixPath(inventory_path).name == PurePosixPath(path).name
            ]
            if basename_matches:
                candidate_disposition(
                    candidate,
                    LegacyDispositionStatus.REVIEW,
                    LegacyDispositionReason.FUZZY_MATCH_REVIEW_REQUIRED,
                    path=path,
                )
            else:
                candidate_disposition(candidate, LegacyDispositionStatus.QUARANTINED, LegacyDispositionReason.INVENTORY_OBJECT_MISSING, path=path)
            continue
        if not _SHA256_RE.fullmatch(candidate.expected_sha256) or candidate.expected_sha256 != item.sha256:
            candidate_disposition(candidate, LegacyDispositionStatus.REVIEW, LegacyDispositionReason.FUZZY_MATCH_REVIEW_REQUIRED, path=path)
            continue
        if item.media_type not in _ALLOWED_MEDIA or candidate.media_type not in _ALLOWED_MEDIA:
            candidate_disposition(candidate, LegacyDispositionStatus.QUARANTINED, LegacyDispositionReason.UNSUPPORTED_MEDIA, path=path)
            continue
        if candidate.media_type != item.media_type and {candidate.media_type, item.media_type} != {"audio/wav", "audio/x-wav"}:
            candidate_disposition(candidate, LegacyDispositionStatus.QUARANTINED, LegacyDispositionReason.MEDIA_MISMATCH, path=path)
            continue
        try:
            resolved = byte_resolver(path)
            payload = bytes(resolved) if resolved is not None else b""
        except Exception:
            payload = b""
        if not payload:
            candidate_disposition(candidate, LegacyDispositionStatus.QUARANTINED, LegacyDispositionReason.BYTES_UNAVAILABLE, path=path)
            continue
        digest = sha256(payload).hexdigest()
        if digest != item.sha256:
            candidate_disposition(candidate, LegacyDispositionStatus.QUARANTINED, LegacyDispositionReason.SHA256_MISMATCH, path=path)
            continue
        if len(payload) != item.size_bytes:
            candidate_disposition(candidate, LegacyDispositionStatus.QUARANTINED, LegacyDispositionReason.SIZE_MISMATCH, path=path)
            continue
        detected = _detected_media(payload)
        if detected is None or (
            detected != item.media_type and {detected, item.media_type} != {"audio/wav", "audio/x-wav"}
        ):
            candidate_disposition(candidate, LegacyDispositionStatus.QUARANTINED, LegacyDispositionReason.MEDIA_MISMATCH, path=path)
            continue
        if decode_validator is not None:
            try:
                decoded = decode_validator(payload, detected)
            except Exception:
                decoded = False
            if decoded is not True:
                candidate_disposition(candidate, LegacyDispositionStatus.QUARANTINED, LegacyDispositionReason.DECODE_FAILED, path=path)
                continue
        kwargs = {
            "spoken_text": subject_text,
            "content_sha256": digest,
            "locale": locale,
            "uri": f"hf://buckets/{inventory.bucket_id}/{path}?inventory_sha256={inventory.inventory_sha256}",
            "mime_type": detected,
            "byte_length": len(payload),
            "segment_kind": "response" if subject_kind == "response" else "template_shell",
            "response_id": candidate.subject_id if subject_kind == "response" else None,
            "template_id": candidate.subject_id if subject_kind == "template" else None,
        }
        audio = AbbyVoiceAudio(
            audio_id=stable_audio_id(digest, segment_kind=kwargs["segment_kind"]),
            **kwargs,
        )
        linked.append(audio)
        candidate_disposition(
            candidate, LegacyDispositionStatus.LINKED,
            LegacyDispositionReason.EXACT_VERIFIED_LINK, path=path, audio_id=audio.audio_id,
        )

    by_path_status: dict[str, tuple[LegacyDispositionStatus, LegacyDispositionReason, str, str]] = {}
    for item in dispositions.values():
        if item.inventory_path:
            by_path_status[item.inventory_path] = (item.status, item.reason, item.candidate_id, item.audio_id)
    for item in inventory.objects:
        ref = _inventory_ref(inventory, item)
        if item.path in by_path_status:
            status, reason, candidate_id, audio_id = by_path_status[item.path]
        elif not item.media_type.startswith("audio/"):
            status, reason, candidate_id, audio_id = (
                LegacyDispositionStatus.UNCLAIMED,
                LegacyDispositionReason.NON_AUDIO_INVENTORY_OBJECT,
                "",
                "",
            )
        else:
            status, reason, candidate_id, audio_id = (
                LegacyDispositionStatus.UNCLAIMED,
                LegacyDispositionReason.UNCLAIMED_AUDIO_OBJECT,
                "",
                "",
            )
        dispositions[ref] = LegacyAudioDisposition(
            source_ref=ref,
            source_sha256=item.sha256,
            status=status,
            reason=reason,
            candidate_id=candidate_id,
            inventory_path=item.path,
            audio_id=audio_id,
        )
    return LegacyAudioReconciliation(
        linked_audio=tuple(linked),
        dispositions=tuple(dispositions.values()),
        inventory_sha256=inventory.inventory_sha256,
    )


__all__ = [
    "LegacyAudioCandidate",
    "LegacyAudioDisposition",
    "LegacyAudioReconciliation",
    "LegacyDispositionReason",
    "LegacyDispositionStatus",
    "reconcile_legacy_audio_candidates",
]
