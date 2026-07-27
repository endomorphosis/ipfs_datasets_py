"""Resumable, byte-verified recovery of planned Abby bucket audio.

This module is the integrity boundary between mutable bucket discovery and
legacy-audio reconciliation.  It has no default client and performs no
network access at import time: callers must provide an explicitly configured
read-only :class:`HuggingFaceBucketStore`.

The storage-layer Xet hash is used only as a cache key.  Every cache hit and
download is independently checked for listed size, raw SHA-256, and audio
magic before a verified inventory object or explicitly pending recovery
candidate can be emitted.  Pending candidates are intentionally not legacy
reconciliation candidates: semantic ASR and critical-slot admission must
happen first.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from ..huggingface.bucket import (
    HuggingFaceBucketError,
    HuggingFaceBucketInventory,
    HuggingFaceBucketListingObject,
    HuggingFaceBucketObject,
    HuggingFaceBucketStore,
)
from .audio_quality import detect_media_type, media_types_compatible
from .bucket_audio_plan import (
    AbbyVoiceBucketAudioPlan,
    BucketAudioSelection,
    SourceResponseAlias,
)
from .normalize import normalize_indextts_spoken_text
from .schema import sha256_text

ABBY_VOICE_BUCKET_AUDIO_RECOVERY_SCHEMA_VERSION = (
    "abby_voice_bucket_audio_recovery_v2"
)
VERIFIED_BUCKET_AUDIO_RECORD_SCHEMA_VERSION = "verified_bucket_audio_record_v1"
BUCKET_AUDIO_RECOVERY_FAILURE_SCHEMA_VERSION = "bucket_audio_recovery_failure_v2"
PENDING_BUCKET_AUDIO_CANDIDATE_SCHEMA_VERSION = (
    "pending_bucket_audio_candidate_v1"
)
PENDING_BUCKET_AUDIO_ADMISSION_STATUS = (
    "pending_semantic_asr_and_critical_slot_validation"
)
_HASH20_RE = re.compile(r"^[0-9a-f]{20}$")
_HASH64_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MEDIA = frozenset(
    {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/ogg", "audio/flac"}
)


class BucketAudioRecoveryError(ValueError):
    """Raised when recovery evidence is incomplete, stale, or unsafe."""


class BucketAudioFailureStage(StrEnum):
    """Operational stage that failed for one planned response."""

    FETCH_AND_VERIFY = "fetch_and_verify"
    DECODE_PROBE = "decode_probe"


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BucketAudioRecoveryError(
            f"value is not canonical JSON data: {exc}"
        ) from exc


def _strict_mapping(
    value: Mapping[str, Any], *, expected: frozenset[str], label: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BucketAudioRecoveryError(f"{label} must be a mapping")
    actual = frozenset(value)
    if actual != expected:
        raise BucketAudioRecoveryError(
            f"{label} has missing fields {sorted(expected - actual)!r} "
            f"and unknown fields {sorted(actual - expected)!r}"
        )
    return value


def _json_mapping(
    value: str | bytes | bytearray, *, label: str
) -> Mapping[str, Any]:
    if isinstance(value, bytes | bytearray):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BucketAudioRecoveryError(f"{label} JSON must be UTF-8") from exc
    if not isinstance(value, str):
        raise TypeError(f"{label} JSON must be str or bytes")
    try:
        decoded = json.loads(value)
    except ValueError as exc:
        raise BucketAudioRecoveryError(f"{label} JSON is invalid: {exc}") from exc
    if not isinstance(decoded, Mapping):
        raise BucketAudioRecoveryError(f"{label} JSON must encode a mapping")
    return decoded


def _required_text(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
    ):
        raise BucketAudioRecoveryError(
            f"{label} must be non-empty without surrounding whitespace or NUL"
        )
    return value


def _full_hash(value: Any, *, label: str) -> str:
    value = _required_text(value, label=label)
    if _HASH64_RE.fullmatch(value) is None:
        raise BucketAudioRecoveryError(
            f"{label} must be a full lowercase SHA-256"
        )
    return value


def _positive_size(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BucketAudioRecoveryError(f"{label} must be a positive integer")
    return value


def _canonical_details(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BucketAudioRecoveryError("decode probe details must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise BucketAudioRecoveryError(
            "decode probe detail keys must be strings"
        )
    decoded = json.loads(_canonical_bytes(dict(value)))
    if not isinstance(decoded, dict):
        raise AssertionError("canonical details must remain a mapping")
    return MappingProxyType(decoded)


@dataclass(frozen=True, slots=True)
class DecodeProbeEvidence:
    """Pinned evidence returned by an optional injected decoder probe."""

    probe_name: str
    probe_version: str
    passed: bool
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "probe_name", _required_text(self.probe_name, label="probe_name")
        )
        object.__setattr__(
            self,
            "probe_version",
            _required_text(self.probe_version, label="probe_version"),
        )
        if not isinstance(self.passed, bool):
            raise BucketAudioRecoveryError("decode probe passed must be boolean")
        object.__setattr__(self, "details", _canonical_details(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "details": dict(self.details),
            "passed": self.passed,
            "probe_name": self.probe_name,
            "probe_version": self.probe_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DecodeProbeEvidence:
        value = _strict_mapping(
            value,
            expected=frozenset(
                {"details", "passed", "probe_name", "probe_version"}
            ),
            label="decode probe evidence",
        )
        if not isinstance(value["details"], Mapping):
            raise BucketAudioRecoveryError(
                "decode probe evidence details must be a mapping"
            )
        return cls(
            probe_name=value["probe_name"],
            probe_version=value["probe_version"],
            passed=value["passed"],
            details=value["details"],
        )


@dataclass(frozen=True, slots=True)
class PendingBucketAudioCandidate:
    """Byte-verified recovery input that is not semantically admitted audio.

    Field names deliberately differ from ``LegacyAudioCandidate``.  In
    particular, this contract has no ``candidate_id``, ``subject_id``,
    ``paths``, or ``expected_sha256`` attributes, so it cannot be accidentally
    fed to the legacy linker as if ASR and critical-slot validation had passed.
    """

    plan_id: str
    listing_sha256: str
    bucket_id: str
    verified_record_id: str
    response_id: str
    canonical_text_sha256: str
    spoken_text: str
    locale: str
    bucket_path: str
    xet_hash: str
    byte_length: int
    raw_sha256: str
    media_type: str
    admission_status: str = PENDING_BUCKET_AUDIO_ADMISSION_STATUS
    schema_version: str = PENDING_BUCKET_AUDIO_CANDIDATE_SCHEMA_VERSION
    pending_candidate_id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        _required_text(self.plan_id, label="plan_id")
        _full_hash(self.listing_sha256, label="listing_sha256")
        _required_text(self.bucket_id, label="bucket_id")
        _required_text(self.verified_record_id, label="verified_record_id")
        _required_text(self.response_id, label="response_id")
        _full_hash(self.canonical_text_sha256, label="canonical_text_sha256")
        spoken_text = _required_text(self.spoken_text, label="spoken_text")
        _required_text(self.locale, label="locale")
        _required_text(self.bucket_path, label="bucket_path")
        _full_hash(self.xet_hash, label="xet_hash")
        _positive_size(self.byte_length, label="byte_length")
        _full_hash(self.raw_sha256, label="raw_sha256")
        media = _required_text(self.media_type, label="media_type").casefold()
        if media not in _ALLOWED_MEDIA:
            raise BucketAudioRecoveryError("media_type is not supported audio")
        if sha256_text(spoken_text) != self.canonical_text_sha256:
            raise BucketAudioRecoveryError(
                "spoken_text does not match canonical_text_sha256"
            )
        if self.admission_status != PENDING_BUCKET_AUDIO_ADMISSION_STATUS:
            raise BucketAudioRecoveryError(
                "pending bucket audio candidate must require semantic admission"
            )
        if self.schema_version != PENDING_BUCKET_AUDIO_CANDIDATE_SCHEMA_VERSION:
            raise BucketAudioRecoveryError(
                "unsupported pending bucket audio candidate schema"
            )
        object.__setattr__(self, "media_type", media)
        computed = (
            "pending-bucket-audio:sha256:"
            + sha256(_canonical_bytes(self._identity_dict())).hexdigest()
        )
        if self.pending_candidate_id and self.pending_candidate_id != computed:
            raise BucketAudioRecoveryError(
                "pending_candidate_id does not match pending candidate content"
            )
        object.__setattr__(self, "pending_candidate_id", computed)

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "admission_status": self.admission_status,
            "bucket_id": self.bucket_id,
            "bucket_path": self.bucket_path,
            "byte_length": self.byte_length,
            "canonical_text_sha256": self.canonical_text_sha256,
            "listing_sha256": self.listing_sha256,
            "locale": self.locale,
            "media_type": self.media_type,
            "plan_id": self.plan_id,
            "raw_sha256": self.raw_sha256,
            "response_id": self.response_id,
            "schema_version": self.schema_version,
            "spoken_text": self.spoken_text,
            "verified_record_id": self.verified_record_id,
            "xet_hash": self.xet_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._identity_dict(),
            "pending_candidate_id": self.pending_candidate_id,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> PendingBucketAudioCandidate:
        value = _strict_mapping(
            value,
            expected=frozenset(
                {
                    "admission_status",
                    "bucket_id",
                    "bucket_path",
                    "byte_length",
                    "canonical_text_sha256",
                    "listing_sha256",
                    "locale",
                    "media_type",
                    "pending_candidate_id",
                    "plan_id",
                    "raw_sha256",
                    "response_id",
                    "schema_version",
                    "spoken_text",
                    "verified_record_id",
                    "xet_hash",
                }
            ),
            label="pending bucket audio candidate",
        )
        result = cls(
            plan_id=value["plan_id"],
            listing_sha256=value["listing_sha256"],
            bucket_id=value["bucket_id"],
            verified_record_id=value["verified_record_id"],
            response_id=value["response_id"],
            canonical_text_sha256=value["canonical_text_sha256"],
            spoken_text=value["spoken_text"],
            locale=value["locale"],
            bucket_path=value["bucket_path"],
            xet_hash=value["xet_hash"],
            byte_length=value["byte_length"],
            raw_sha256=value["raw_sha256"],
            media_type=value["media_type"],
            admission_status=value["admission_status"],
            schema_version=value["schema_version"],
            pending_candidate_id=value["pending_candidate_id"],
        )
        if result.to_dict() != dict(value):
            raise BucketAudioRecoveryError(
                "pending bucket audio candidate is not canonical"
            )
        return result

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> PendingBucketAudioCandidate:
        return cls.from_dict(
            _json_mapping(value, label="pending bucket audio candidate")
        )


@dataclass(frozen=True, slots=True)
class VerifiedBucketAudioRecord:
    """Strict resumable evidence for one response/object/cache binding."""

    plan_id: str
    listing_sha256: str
    bucket_id: str
    response_id: str
    canonical_text_sha256: str
    spoken_text: str
    locale: str
    legacy_text_hash: str
    source_ref: str
    source_record_sha256: str
    bucket_path: str
    xet_hash: str
    listed_size_bytes: int
    verified_size_bytes: int
    raw_sha256: str
    media_type: str
    decode_probe: DecodeProbeEvidence | None = None
    schema_version: str = VERIFIED_BUCKET_AUDIO_RECORD_SCHEMA_VERSION
    record_id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        _required_text(self.plan_id, label="plan_id")
        _full_hash(self.listing_sha256, label="listing_sha256")
        _required_text(self.bucket_id, label="bucket_id")
        _required_text(self.response_id, label="response_id")
        _full_hash(self.canonical_text_sha256, label="canonical_text_sha256")
        spoken_text = _required_text(self.spoken_text, label="spoken_text")
        _required_text(self.locale, label="locale")
        if _HASH20_RE.fullmatch(self.legacy_text_hash) is None:
            raise BucketAudioRecoveryError(
                "legacy_text_hash must be 20 lowercase hexadecimal characters"
            )
        _required_text(self.source_ref, label="source_ref")
        _full_hash(self.source_record_sha256, label="source_record_sha256")
        _required_text(self.bucket_path, label="bucket_path")
        _full_hash(self.xet_hash, label="xet_hash")
        listed_size = _positive_size(
            self.listed_size_bytes, label="listed_size_bytes"
        )
        verified_size = _positive_size(
            self.verified_size_bytes, label="verified_size_bytes"
        )
        if listed_size != verified_size:
            raise BucketAudioRecoveryError(
                "verified size does not match planned listing size"
            )
        _full_hash(self.raw_sha256, label="raw_sha256")
        media = _required_text(self.media_type, label="media_type").casefold()
        if media not in _ALLOWED_MEDIA:
            raise BucketAudioRecoveryError("media_type is not supported audio")
        if sha256_text(spoken_text) != self.canonical_text_sha256:
            raise BucketAudioRecoveryError(
                "spoken_text does not match canonical_text_sha256"
            )
        if self.decode_probe is not None:
            if not isinstance(self.decode_probe, DecodeProbeEvidence):
                raise TypeError("decode_probe must be DecodeProbeEvidence or None")
            if not self.decode_probe.passed:
                raise BucketAudioRecoveryError(
                    "failed decode probe evidence cannot verify an audio record"
                )
        if self.schema_version != VERIFIED_BUCKET_AUDIO_RECORD_SCHEMA_VERSION:
            raise BucketAudioRecoveryError(
                "unsupported verified bucket audio record schema"
            )
        object.__setattr__(self, "media_type", media)
        computed = (
            "verified-bucket-audio:sha256:"
            + sha256(_canonical_bytes(self._identity_dict())).hexdigest()
        )
        if self.record_id and self.record_id != computed:
            raise BucketAudioRecoveryError(
                "record_id does not match verified record content"
            )
        object.__setattr__(self, "record_id", computed)

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "bucket_id": self.bucket_id,
            "bucket_path": self.bucket_path,
            "canonical_text_sha256": self.canonical_text_sha256,
            "decode_probe": (
                self.decode_probe.to_dict() if self.decode_probe is not None else None
            ),
            "legacy_text_hash": self.legacy_text_hash,
            "listed_size_bytes": self.listed_size_bytes,
            "listing_sha256": self.listing_sha256,
            "locale": self.locale,
            "media_type": self.media_type,
            "plan_id": self.plan_id,
            "raw_sha256": self.raw_sha256,
            "response_id": self.response_id,
            "schema_version": self.schema_version,
            "source_record_sha256": self.source_record_sha256,
            "source_ref": self.source_ref,
            "spoken_text": self.spoken_text,
            "verified_size_bytes": self.verified_size_bytes,
            "xet_hash": self.xet_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._identity_dict(), "record_id": self.record_id}

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> VerifiedBucketAudioRecord:
        value = _strict_mapping(
            value,
            expected=frozenset(
                {
                    "bucket_id",
                    "bucket_path",
                    "canonical_text_sha256",
                    "decode_probe",
                    "legacy_text_hash",
                    "listed_size_bytes",
                    "listing_sha256",
                    "locale",
                    "media_type",
                    "plan_id",
                    "raw_sha256",
                    "record_id",
                    "response_id",
                    "schema_version",
                    "source_record_sha256",
                    "source_ref",
                    "spoken_text",
                    "verified_size_bytes",
                    "xet_hash",
                }
            ),
            label="verified bucket audio record",
        )
        raw_probe = value["decode_probe"]
        if raw_probe is not None and not isinstance(raw_probe, Mapping):
            raise BucketAudioRecoveryError(
                "verified bucket audio decode_probe must be a mapping or null"
            )
        result = cls(
            plan_id=value["plan_id"],
            listing_sha256=value["listing_sha256"],
            bucket_id=value["bucket_id"],
            response_id=value["response_id"],
            canonical_text_sha256=value["canonical_text_sha256"],
            spoken_text=value["spoken_text"],
            locale=value["locale"],
            legacy_text_hash=value["legacy_text_hash"],
            source_ref=value["source_ref"],
            source_record_sha256=value["source_record_sha256"],
            bucket_path=value["bucket_path"],
            xet_hash=value["xet_hash"],
            listed_size_bytes=value["listed_size_bytes"],
            verified_size_bytes=value["verified_size_bytes"],
            raw_sha256=value["raw_sha256"],
            media_type=value["media_type"],
            decode_probe=(
                DecodeProbeEvidence.from_dict(raw_probe)
                if raw_probe is not None
                else None
            ),
            schema_version=value["schema_version"],
            record_id=value["record_id"],
        )
        if result.to_dict() != dict(value):
            raise BucketAudioRecoveryError(
                "verified bucket audio record is not canonical"
            )
        return result

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> VerifiedBucketAudioRecord:
        return cls.from_dict(
            _json_mapping(value, label="verified bucket audio record")
        )

    def to_inventory_object(self) -> HuggingFaceBucketObject:
        return HuggingFaceBucketObject(
            path=self.bucket_path,
            size_bytes=self.verified_size_bytes,
            sha256=self.raw_sha256,
            etag=f"hf-xet:{self.xet_hash}",
            media_type=self.media_type,
        )

    def to_pending_candidate(self) -> PendingBucketAudioCandidate:
        """Return a fail-closed candidate for semantic admission."""

        return PendingBucketAudioCandidate(
            plan_id=self.plan_id,
            listing_sha256=self.listing_sha256,
            bucket_id=self.bucket_id,
            verified_record_id=self.record_id,
            response_id=self.response_id,
            canonical_text_sha256=self.canonical_text_sha256,
            spoken_text=self.spoken_text,
            locale=self.locale,
            bucket_path=self.bucket_path,
            xet_hash=self.xet_hash,
            byte_length=self.verified_size_bytes,
            raw_sha256=self.raw_sha256,
            media_type=self.media_type,
        )


@dataclass(frozen=True, slots=True)
class BucketAudioRecoveryFailure:
    """Deterministic per-response failure that does not authorize an audio link."""

    plan_id: str
    listing_sha256: str
    bucket_id: str
    response_id: str
    legacy_text_hash: str
    selected_bucket_path: str
    xet_hash: str | None
    listed_size_bytes: int
    attempted_bucket_paths: tuple[str, ...]
    stage: BucketAudioFailureStage
    detail: str
    retryable: bool
    schema_version: str = BUCKET_AUDIO_RECOVERY_FAILURE_SCHEMA_VERSION
    failure_id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        _required_text(self.plan_id, label="plan_id")
        _full_hash(self.listing_sha256, label="listing_sha256")
        _required_text(self.bucket_id, label="bucket_id")
        _required_text(self.response_id, label="response_id")
        if _HASH20_RE.fullmatch(self.legacy_text_hash) is None:
            raise BucketAudioRecoveryError(
                "legacy_text_hash must be 20 lowercase hexadecimal characters"
            )
        selected_path = _required_text(
            self.selected_bucket_path, label="selected_bucket_path"
        )
        xet_hash = (
            None
            if self.xet_hash is None
            else _full_hash(self.xet_hash, label="xet_hash")
        )
        _positive_size(self.listed_size_bytes, label="listed_size_bytes")
        attempted = tuple(
            _required_text(item, label="attempted_bucket_path")
            for item in self.attempted_bucket_paths
        )
        if not attempted or len(attempted) != len(set(attempted)):
            raise BucketAudioRecoveryError(
                "attempted_bucket_paths must be non-empty and unique"
            )
        if selected_path not in attempted:
            raise BucketAudioRecoveryError(
                "selected_bucket_path must appear in attempted_bucket_paths"
            )
        try:
            stage = BucketAudioFailureStage(self.stage)
        except (TypeError, ValueError) as exc:
            raise BucketAudioRecoveryError(
                "unsupported bucket audio recovery failure stage"
            ) from exc
        detail = " ".join(_required_text(self.detail, label="detail").split())
        if len(detail) > 512:
            detail = detail[:509] + "..."
        if not isinstance(self.retryable, bool):
            raise BucketAudioRecoveryError("retryable must be boolean")
        if self.schema_version != BUCKET_AUDIO_RECOVERY_FAILURE_SCHEMA_VERSION:
            raise BucketAudioRecoveryError(
                "unsupported bucket audio recovery failure schema"
            )
        object.__setattr__(self, "attempted_bucket_paths", attempted)
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "detail", detail)
        object.__setattr__(self, "xet_hash", xet_hash)
        computed = (
            "bucket-audio-recovery-failure:sha256:"
            + sha256(_canonical_bytes(self._identity_dict())).hexdigest()
        )
        if self.failure_id and self.failure_id != computed:
            raise BucketAudioRecoveryError(
                "failure_id does not match bucket audio failure content"
            )
        object.__setattr__(self, "failure_id", computed)

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "attempted_bucket_paths": list(self.attempted_bucket_paths),
            "bucket_id": self.bucket_id,
            "detail": self.detail,
            "legacy_text_hash": self.legacy_text_hash,
            "listed_size_bytes": self.listed_size_bytes,
            "listing_sha256": self.listing_sha256,
            "plan_id": self.plan_id,
            "response_id": self.response_id,
            "retryable": self.retryable,
            "schema_version": self.schema_version,
            "selected_bucket_path": self.selected_bucket_path,
            "stage": self.stage.value,
            "xet_hash": self.xet_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._identity_dict(), "failure_id": self.failure_id}

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> BucketAudioRecoveryFailure:
        value = _strict_mapping(
            value,
            expected=frozenset(
                {
                    "attempted_bucket_paths",
                    "bucket_id",
                    "detail",
                    "failure_id",
                    "legacy_text_hash",
                    "listed_size_bytes",
                    "listing_sha256",
                    "plan_id",
                    "response_id",
                    "retryable",
                    "schema_version",
                    "selected_bucket_path",
                    "stage",
                    "xet_hash",
                }
            ),
            label="bucket audio recovery failure",
        )
        if not isinstance(value["attempted_bucket_paths"], list):
            raise BucketAudioRecoveryError(
                "attempted_bucket_paths must be a JSON array"
            )
        result = cls(
            plan_id=value["plan_id"],
            listing_sha256=value["listing_sha256"],
            bucket_id=value["bucket_id"],
            response_id=value["response_id"],
            legacy_text_hash=value["legacy_text_hash"],
            selected_bucket_path=value["selected_bucket_path"],
            xet_hash=value["xet_hash"],
            listed_size_bytes=value["listed_size_bytes"],
            attempted_bucket_paths=tuple(value["attempted_bucket_paths"]),
            stage=value["stage"],
            detail=value["detail"],
            retryable=value["retryable"],
            schema_version=value["schema_version"],
            failure_id=value["failure_id"],
        )
        if result.to_dict() != dict(value):
            raise BucketAudioRecoveryError(
                "bucket audio recovery failure is not canonical"
            )
        return result

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> BucketAudioRecoveryFailure:
        return cls.from_dict(
            _json_mapping(value, label="bucket audio recovery failure")
        )


def _ordered_records(
    records: Iterable[VerifiedBucketAudioRecord],
) -> tuple[VerifiedBucketAudioRecord, ...]:
    raw_values = tuple(records)
    if any(
        not isinstance(item, VerifiedBucketAudioRecord) for item in raw_values
    ):
        raise TypeError(
            "records must contain VerifiedBucketAudioRecord values"
        )
    values = tuple(sorted(raw_values, key=lambda item: item.response_id))
    for label, identities in (
        ("response IDs", [item.response_id for item in values]),
        ("record IDs", [item.record_id for item in values]),
        ("bucket paths", [item.bucket_path for item in values]),
    ):
        if len(identities) != len(set(identities)):
            raise BucketAudioRecoveryError(
                f"verified bucket audio {label} must be unique"
            )
    if values:
        bindings = {
            (item.plan_id, item.listing_sha256, item.bucket_id)
            for item in values
        }
        if len(bindings) != 1:
            raise BucketAudioRecoveryError(
                "verified records must share one plan/listing/bucket binding"
            )
    return values


def _ordered_failures(
    failures: Iterable[BucketAudioRecoveryFailure],
) -> tuple[BucketAudioRecoveryFailure, ...]:
    raw_values = tuple(failures)
    if any(
        not isinstance(item, BucketAudioRecoveryFailure) for item in raw_values
    ):
        raise TypeError(
            "failures must contain BucketAudioRecoveryFailure values"
        )
    values = tuple(sorted(raw_values, key=lambda item: item.response_id))
    for label, identities in (
        ("response IDs", [item.response_id for item in values]),
        ("failure IDs", [item.failure_id for item in values]),
    ):
        if len(identities) != len(set(identities)):
            raise BucketAudioRecoveryError(
                f"bucket audio recovery failure {label} must be unique"
            )
    return values


def verified_bucket_audio_jsonl_bytes(
    records: Iterable[VerifiedBucketAudioRecord],
) -> bytes:
    """Serialize a canonical, response-sorted recovery ledger."""

    ordered = _ordered_records(records)
    return b"".join(item.canonical_bytes() + b"\n" for item in ordered)


def parse_verified_bucket_audio_jsonl(
    value: str | bytes | bytearray,
) -> tuple[VerifiedBucketAudioRecord, ...]:
    """Parse only canonical JSONL produced by this module."""

    if isinstance(value, str):
        raw = value.encode("utf-8")
    elif isinstance(value, bytes | bytearray):
        raw = bytes(value)
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BucketAudioRecoveryError(
                "verified bucket audio JSONL must be UTF-8"
            ) from exc
    else:
        raise TypeError("verified bucket audio JSONL must be str or bytes")
    if not raw:
        return ()
    if not raw.endswith(b"\n"):
        raise BucketAudioRecoveryError(
            "verified bucket audio JSONL must end with a newline"
        )
    lines = raw[:-1].split(b"\n")
    if any(not line for line in lines):
        raise BucketAudioRecoveryError(
            "verified bucket audio JSONL must not contain blank lines"
        )
    records = tuple(VerifiedBucketAudioRecord.from_json(line) for line in lines)
    ordered = _ordered_records(records)
    if records != ordered or verified_bucket_audio_jsonl_bytes(records) != raw:
        raise BucketAudioRecoveryError(
            "verified bucket audio JSONL is not canonical"
        )
    return records


def read_verified_bucket_audio_jsonl(
    path: str | Path,
) -> tuple[VerifiedBucketAudioRecord, ...]:
    """Read a strict ledger without following a final-path symlink."""

    ledger = Path(path)
    if ledger.is_symlink():
        raise BucketAudioRecoveryError("recovery ledger must not be a symlink")
    if not ledger.exists():
        return ()
    if not ledger.is_file():
        raise BucketAudioRecoveryError("recovery ledger must be a regular file")
    return parse_verified_bucket_audio_jsonl(ledger.read_bytes())


def write_verified_bucket_audio_jsonl(
    path: str | Path,
    records: Iterable[VerifiedBucketAudioRecord],
) -> Path:
    """Atomically persist a canonical resumable recovery ledger."""

    ledger = Path(path)
    if ledger.exists() and (ledger.is_symlink() or not ledger.is_file()):
        raise BucketAudioRecoveryError(
            "recovery ledger destination must be a regular file"
        )
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if ledger.parent.is_symlink():
        raise BucketAudioRecoveryError(
            "recovery ledger parent must not be a symlink"
        )
    payload = verified_bucket_audio_jsonl_bytes(records)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{ledger.name}.", suffix=".partial", dir=ledger.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, ledger)
    except Exception:
        try:
            Path(temporary_name).unlink()
        except FileNotFoundError:
            pass
        raise
    return ledger


def bucket_audio_cache_path(cache_dir: str | Path, xet_hash: str) -> Path:
    """Return the content-cache path keyed solely by a full Xet hash."""

    digest = _full_hash(xet_hash, label="xet_hash")
    return Path(cache_dir) / "xet" / digest[:2] / f"{digest}.blob"


@dataclass(frozen=True, slots=True)
class AbbyVoiceBucketAudioRecovery:
    """Deterministic targeted subset of an Abby bucket-audio plan."""

    plan_id: str
    listing_sha256: str
    bucket_id: str
    planned_selection_count: int
    target_response_ids: tuple[str, ...]
    records: tuple[VerifiedBucketAudioRecord, ...]
    failures: tuple[BucketAudioRecoveryFailure, ...]
    schema_version: str = ABBY_VOICE_BUCKET_AUDIO_RECOVERY_SCHEMA_VERSION
    recovery_id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        _required_text(self.plan_id, label="plan_id")
        _full_hash(self.listing_sha256, label="listing_sha256")
        _required_text(self.bucket_id, label="bucket_id")
        if (
            isinstance(self.planned_selection_count, bool)
            or not isinstance(self.planned_selection_count, int)
            or self.planned_selection_count < 0
        ):
            raise BucketAudioRecoveryError(
                "planned_selection_count must be a non-negative integer"
            )
        targets = tuple(sorted(set(self.target_response_ids)))
        if len(targets) != len(self.target_response_ids):
            raise BucketAudioRecoveryError("target response IDs must be unique")
        if len(targets) > self.planned_selection_count:
            raise BucketAudioRecoveryError(
                "target count cannot exceed planned selection count"
            )
        records = _ordered_records(self.records)
        failures = _ordered_failures(self.failures)
        record_ids = {item.response_id for item in records}
        failure_ids = {item.response_id for item in failures}
        if record_ids & failure_ids:
            raise BucketAudioRecoveryError(
                "a target response cannot be both verified and failed"
            )
        if record_ids | failure_ids != set(targets):
            raise BucketAudioRecoveryError(
                "every target response must have exactly one verified or failed disposition"
            )
        if any(
            (
                item.plan_id != self.plan_id
                or item.listing_sha256 != self.listing_sha256
                or item.bucket_id != self.bucket_id
            )
            for item in records
        ):
            raise BucketAudioRecoveryError(
                "recovery records do not match result binding"
            )
        if any(
            (
                item.plan_id != self.plan_id
                or item.listing_sha256 != self.listing_sha256
                or item.bucket_id != self.bucket_id
            )
            for item in failures
        ):
            raise BucketAudioRecoveryError(
                "recovery failures do not match result binding"
            )
        if self.schema_version != ABBY_VOICE_BUCKET_AUDIO_RECOVERY_SCHEMA_VERSION:
            raise BucketAudioRecoveryError(
                "unsupported Abby bucket audio recovery schema"
            )
        object.__setattr__(self, "target_response_ids", targets)
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "failures", failures)
        computed = (
            "abby-voice-bucket-audio-recovery:sha256:"
            + sha256(_canonical_bytes(self._identity_dict())).hexdigest()
        )
        if self.recovery_id and self.recovery_id != computed:
            raise BucketAudioRecoveryError(
                "recovery_id does not match recovery content"
            )
        object.__setattr__(self, "recovery_id", computed)

    @property
    def inventory(self) -> HuggingFaceBucketInventory:
        return HuggingFaceBucketInventory(
            bucket_id=self.bucket_id,
            objects=tuple(item.to_inventory_object() for item in self.records),
        )

    @property
    def candidates(self) -> tuple[PendingBucketAudioCandidate, ...]:
        """Return byte-verified candidates that still require semantic gates."""

        return tuple(item.to_pending_candidate() for item in self.records)

    @property
    def target_complete(self) -> bool:
        """Whether every response in this invocation's target was verified."""

        return not self.failures

    @property
    def plan_complete(self) -> bool:
        """Whether this successful target covered every selection in the plan."""

        return (
            self.target_complete
            and len(self.target_response_ids) == self.planned_selection_count
        )

    def summary(self) -> dict[str, int | str | bool]:
        return {
            "bucket_id": self.bucket_id,
            "decode_probe_count": sum(
                item.decode_probe is not None for item in self.records
            ),
            "failed_record_count": len(self.failures),
            "inventory_object_count": self.inventory.object_count,
            "listing_sha256": self.listing_sha256,
            "pending_candidate_count": len(self.candidates),
            "plan_id": self.plan_id,
            "plan_complete": self.plan_complete,
            "planned_selection_count": self.planned_selection_count,
            "raw_sha256_verified": True,
            "publishable": False,
            "retryable_failure_count": sum(
                item.retryable for item in self.failures
            ),
            "schema_version": self.schema_version,
            "semantic_asr_and_critical_slot_validation_required": True,
            "staged_pending_asr_count": len(self.records),
            "target_complete": self.target_complete,
            "target_selection_count": len(self.target_response_ids),
            "total_verified_size_bytes": sum(
                item.verified_size_bytes for item in self.records
            ),
            "verified_record_count": len(self.records),
            "xet_hash_used_as_raw_sha256": False,
        }

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "bucket_id": self.bucket_id,
            "integrity_policy": {
                "cache_key": "xet_hash",
                "raw_sha256_required": True,
                "recovery_records_are_publishable": False,
                "semantic_asr_and_critical_slot_validation_required": True,
                "xet_hash_is_raw_sha256": False,
            },
            "failures": [item.to_dict() for item in self.failures],
            "listing_sha256": self.listing_sha256,
            "plan_id": self.plan_id,
            "planned_selection_count": self.planned_selection_count,
            "records": [item.to_dict() for item in self.records],
            "schema_version": self.schema_version,
            "target_response_ids": list(self.target_response_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._identity_dict(),
            "recovery_id": self.recovery_id,
            "summary": self.summary(),
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> AbbyVoiceBucketAudioRecovery:
        value = _strict_mapping(
            value,
            expected=frozenset(
                {
                    "bucket_id",
                    "failures",
                    "integrity_policy",
                    "listing_sha256",
                    "plan_id",
                    "planned_selection_count",
                    "records",
                    "recovery_id",
                    "schema_version",
                    "summary",
                    "target_response_ids",
                }
            ),
            label="Abby voice bucket audio recovery",
        )
        if value["integrity_policy"] != {
            "cache_key": "xet_hash",
            "raw_sha256_required": True,
            "recovery_records_are_publishable": False,
            "semantic_asr_and_critical_slot_validation_required": True,
            "xet_hash_is_raw_sha256": False,
        }:
            raise BucketAudioRecoveryError(
                "unsupported bucket audio recovery integrity policy"
            )
        if not isinstance(value["records"], list) or not all(
            isinstance(item, Mapping) for item in value["records"]
        ):
            raise BucketAudioRecoveryError(
                "bucket audio recovery records must be a list of mappings"
            )
        if not isinstance(value["failures"], list) or not all(
            isinstance(item, Mapping) for item in value["failures"]
        ):
            raise BucketAudioRecoveryError(
                "bucket audio recovery failures must be a list of mappings"
            )
        if not isinstance(value["target_response_ids"], list):
            raise BucketAudioRecoveryError(
                "target_response_ids must be a JSON array"
            )
        result = cls(
            plan_id=value["plan_id"],
            listing_sha256=value["listing_sha256"],
            bucket_id=value["bucket_id"],
            planned_selection_count=value["planned_selection_count"],
            target_response_ids=tuple(value["target_response_ids"]),
            records=tuple(
                VerifiedBucketAudioRecord.from_dict(item)
                for item in value["records"]
            ),
            failures=tuple(
                BucketAudioRecoveryFailure.from_dict(item)
                for item in value["failures"]
            ),
            schema_version=value["schema_version"],
            recovery_id=value["recovery_id"],
        )
        if (
            not isinstance(value["summary"], Mapping)
            or dict(value["summary"]) != result.summary()
            or result.to_dict() != dict(value)
        ):
            raise BucketAudioRecoveryError(
                "bucket audio recovery summary or canonical content is invalid"
            )
        return result

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> AbbyVoiceBucketAudioRecovery:
        return cls.from_dict(
            _json_mapping(value, label="Abby voice bucket audio recovery")
        )


DecodeProbe = Callable[
    [bytes, str],
    DecodeProbeEvidence | bool,
]


def _alias_spoken_text(
    alias: SourceResponseAlias, *, default_locale: str
) -> tuple[str, str]:
    source = alias.source_record
    raw_text = str(source.get("text") or source.get("spoken_text") or "").strip()
    spoken_text = normalize_indextts_spoken_text(raw_text)
    if not spoken_text or sha256_text(spoken_text) != alias.canonical_text_sha256:
        raise BucketAudioRecoveryError(
            f"source alias {alias.response_id!r} no longer reproduces canonical spoken text"
        )
    locale = str(source.get("locale") or default_locale).strip()
    _required_text(locale, label="locale")
    return spoken_text, locale


def _validate_record_binding(
    record: VerifiedBucketAudioRecord,
    *,
    plan: AbbyVoiceBucketAudioPlan,
    alias: SourceResponseAlias,
    selection: BucketAudioSelection,
    default_locale: str,
) -> None:
    if selection.response_id != alias.response_id:
        raise BucketAudioRecoveryError(
            "selection response does not match its source alias"
        )
    if selection.legacy_text_hash != alias.legacy_text_hash:
        raise BucketAudioRecoveryError(
            "selection legacy hash does not match its source alias"
        )
    spoken_text, locale = _alias_spoken_text(
        alias, default_locale=default_locale
    )
    selected = selection.selected
    equivalent_paths = {
        item.path
        for item in (selection.selected, *selection.alternatives)
        if (
            item.xet_hash == selected.xet_hash
            and item.size_bytes == selected.size_bytes
        )
    }
    expected = {
        "plan_id": plan.plan_id,
        "listing_sha256": plan.listing_sha256,
        "bucket_id": plan.bucket_id,
        "response_id": alias.response_id,
        "canonical_text_sha256": alias.canonical_text_sha256,
        "spoken_text": spoken_text,
        "locale": locale,
        "legacy_text_hash": alias.legacy_text_hash,
        "source_ref": alias.source_ref,
        "source_record_sha256": alias.source_record_sha256,
        "xet_hash": selected.xet_hash,
        "listed_size_bytes": selected.size_bytes,
    }
    for name, value in expected.items():
        if getattr(record, name) != value:
            raise BucketAudioRecoveryError(
                f"resumable record {record.response_id!r} has stale {name}"
            )
    if record.bucket_path not in equivalent_paths:
        raise BucketAudioRecoveryError(
            f"resumable record {record.response_id!r} has stale bucket_path"
        )


def _probe(
    callback: DecodeProbe | None, payload: bytes, media_type: str
) -> DecodeProbeEvidence | None:
    if callback is None:
        return None
    try:
        result = callback(payload, media_type)
    except Exception as exc:
        raise BucketAudioRecoveryError(f"decode probe failed: {exc}") from exc
    evidence = (
        DecodeProbeEvidence(
            probe_name="injected_decode_probe",
            probe_version="unspecified",
            passed=result,
        )
        if isinstance(result, bool)
        else result
    )
    if not isinstance(evidence, DecodeProbeEvidence):
        raise BucketAudioRecoveryError(
            "decode probe must return DecodeProbeEvidence or bool"
        )
    if not evidence.passed:
        raise BucketAudioRecoveryError("decode probe rejected recovered audio")
    return evidence


def _selection_failure(
    *,
    plan: AbbyVoiceBucketAudioPlan,
    selection: BucketAudioSelection,
    stage: BucketAudioFailureStage,
    detail: str,
    retryable: bool,
) -> BucketAudioRecoveryFailure:
    selected = selection.selected
    usable_xet_hash = (
        selected.xet_hash
        if (
            isinstance(selected.xet_hash, str)
            and _HASH64_RE.fullmatch(selected.xet_hash) is not None
        )
        else None
    )
    attempted_paths = (
        tuple(
            item.path
            for item in (selected, *selection.alternatives)
            if (
                item.xet_hash == usable_xet_hash
                and item.size_bytes == selected.size_bytes
            )
        )
        if usable_xet_hash is not None
        else (selected.path,)
    )
    return BucketAudioRecoveryFailure(
        plan_id=plan.plan_id,
        listing_sha256=plan.listing_sha256,
        bucket_id=plan.bucket_id,
        response_id=selection.response_id,
        legacy_text_hash=selection.legacy_text_hash,
        selected_bucket_path=selected.path,
        xet_hash=usable_xet_hash,
        listed_size_bytes=selected.size_bytes,
        attempted_bucket_paths=attempted_paths,
        stage=stage,
        detail=detail,
        retryable=retryable,
    )


def _operational_failure_detail(exc: BaseException) -> str:
    """Return a non-empty, deterministic detail for a row-local failure."""

    detail = " ".join(str(exc).split())
    return detail or type(exc).__name__


def _materialize_selection(
    *,
    store: HuggingFaceBucketStore,
    selection: BucketAudioSelection,
    cache_dir: Path,
    expected_raw_sha256: str | None,
    preferred_bucket_path: str | None = None,
) -> tuple[HuggingFaceBucketObject, bytes, Path]:
    selected = selection.selected
    if selected.xet_hash is None:
        raise BucketAudioRecoveryError(
            f"selected object {selected.path!r} has no Xet hash"
        )
    xet_hash = _full_hash(selected.xet_hash, label="selected xet_hash")
    _positive_size(selected.size_bytes, label="selected size_bytes")
    cache_path = bucket_audio_cache_path(cache_dir, xet_hash)
    if cache_path.is_symlink():
        raise BucketAudioRecoveryError("bucket audio cache object must not be a symlink")
    equivalent = tuple(
        item
        for item in (selection.selected, *selection.alternatives)
        if item.xet_hash == selected.xet_hash
        and item.size_bytes == selected.size_bytes
    )
    if preferred_bucket_path is not None:
        equivalent = tuple(
            sorted(
                equivalent,
                key=lambda item: (
                    0 if item.path == preferred_bucket_path else 1,
                    item.path,
                ),
            )
        )
    if not equivalent:
        raise BucketAudioRecoveryError(
            "selection has no exact Xet-and-size-bound recovery object"
        )
    if cache_path.exists() and not cache_path.is_file():
        raise BucketAudioRecoveryError(
            "bucket audio cache object must be a regular file"
        )
    if expected_raw_sha256 is not None:
        _full_hash(expected_raw_sha256, label="expected_raw_sha256")
    # A filename derived from mutable discovery metadata is not integrity
    # evidence.  Only a validated ledger can authorize a cache hit.
    if cache_path.exists() and expected_raw_sha256 is None:
        cache_path.unlink()

    def _declared_media_type(path: str) -> str:
        suffix = PurePosixPath(path).suffix.casefold()
        if suffix == ".wav":
            return "audio/wav"
        if suffix == ".flac":
            return "audio/flac"
        if suffix == ".ogg":
            return "audio/ogg"
        # Default production container for abby-tts-* linkable objects.
        return "audio/mpeg"

    if cache_path.exists():
        try:
            listing = HuggingFaceBucketListingObject(
                path=equivalent[0].path,
                size_bytes=selected.size_bytes,
                xet_hash=xet_hash,
                media_type=_declared_media_type(equivalent[0].path),
            )
            verified = store.verify_discovered_file(
                listing,
                cache_path,
                expected_sha256=expected_raw_sha256 or "",
            )
        except HuggingFaceBucketError:
            cache_path.unlink()
            verified = None
    else:
        verified = None
    last_error: HuggingFaceBucketError | None = None
    if verified is None:
        for item in equivalent:
            listing = HuggingFaceBucketListingObject(
                path=item.path,
                size_bytes=item.size_bytes,
                xet_hash=xet_hash,
                media_type=_declared_media_type(item.path),
            )
            try:
                verified = store.fetch_discovered(listing, cache_path)
                break
            except HuggingFaceBucketError as exc:
                last_error = exc
        if verified is None:
            raise BucketAudioRecoveryError(
                "every exact Xet-and-size-bound bucket path failed"
            ) from last_error
    payload = cache_path.read_bytes()
    digest = sha256(payload).hexdigest()
    equivalent_paths = {item.path for item in equivalent}
    if (
        len(payload) != selected.size_bytes
        or verified.size_bytes != selected.size_bytes
        or verified.sha256 != digest
        or verified.path not in equivalent_paths
    ):
        raise BucketAudioRecoveryError(
            "recovered cache bytes do not match verified listing evidence"
        )
    if (
        expected_raw_sha256 is not None
        and digest != expected_raw_sha256
    ):
        raise BucketAudioRecoveryError(
            "refetched raw SHA-256 does not match the recovery ledger"
        )
    detected = detect_media_type(payload)
    if detected is None or not media_types_compatible(verified.media_type, detected):
        raise BucketAudioRecoveryError(
            "recovered object does not contain the declared audio media"
        )
    if detected != verified.media_type:
        verified = HuggingFaceBucketObject(
            path=verified.path,
            size_bytes=verified.size_bytes,
            sha256=verified.sha256,
            etag=verified.etag,
            media_type=detected,
        )
    return verified, payload, cache_path


def recover_abby_voice_bucket_audio(
    *,
    plan: AbbyVoiceBucketAudioPlan,
    store: HuggingFaceBucketStore,
    cache_dir: str | Path,
    ledger_path: str | Path | None = None,
    decode_probe: DecodeProbe | None = None,
    limit: int | None = None,
    default_locale: str = "en-US",
    checkpoint_interval: int = 100,
    fail_fast: bool = False,
) -> AbbyVoiceBucketAudioRecovery:
    """Fetch or resume a deterministic verified prefix of ``plan.selections``.

    ``limit`` is a total canary target, not an additional-work count.  Raising
    it on a later invocation resumes from the same response-sorted prefix.
    The ledger is atomically checkpointed every ``checkpoint_interval`` changed
    records and once more at the end of a successful invocation. A crash can
    therefore lose at most that many ledger rows. Unledgered cache bytes are
    deliberately
    redownloaded because an Xet-derived filename is not raw-content evidence.
    By default an operational failure becomes a per-response retry disposition
    and later selections continue.  Set ``fail_fast`` only for diagnostics.
    """

    if not isinstance(plan, AbbyVoiceBucketAudioPlan):
        raise TypeError("plan must be an AbbyVoiceBucketAudioPlan")
    if not isinstance(store, HuggingFaceBucketStore):
        raise TypeError("store must be an injected HuggingFaceBucketStore")
    if store.bucket_id != plan.bucket_id:
        raise BucketAudioRecoveryError("bucket store does not match recovery plan")
    _required_text(default_locale, label="default_locale")
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
    ):
        raise BucketAudioRecoveryError("limit must be a non-negative integer or None")
    if (
        isinstance(checkpoint_interval, bool)
        or not isinstance(checkpoint_interval, int)
        or checkpoint_interval <= 0
    ):
        raise BucketAudioRecoveryError(
            "checkpoint_interval must be a positive integer"
        )
    if not isinstance(fail_fast, bool):
        raise BucketAudioRecoveryError("fail_fast must be boolean")

    selections = tuple(sorted(plan.selections, key=lambda item: item.response_id))
    target = selections if limit is None else selections[:limit]
    target_ids = tuple(item.response_id for item in target)
    alias_by_id = {item.response_id: item for item in plan.aliases}
    selection_by_id = {item.response_id: item for item in selections}
    if len({item.selected.path for item in target}) != len(target):
        raise BucketAudioRecoveryError(
            "canary selection paths must be unique across responses"
        )
    xet_bindings: dict[str, tuple[int, str]] = {}
    for item in target:
        xet_hash = item.selected.xet_hash
        if xet_hash is None:
            # Missing row-local discovery metadata is a retry disposition, not
            # a reason to discard safe progress on unrelated selections.
            continue
        binding = (item.selected.size_bytes, item.response_id)
        previous = xet_bindings.get(xet_hash)
        if previous is not None and previous != binding:
            raise BucketAudioRecoveryError(
                "one Xet cache key is ambiguously bound to multiple responses"
            )
        xet_bindings[xet_hash] = binding

    existing = (
        read_verified_bucket_audio_jsonl(ledger_path)
        if ledger_path is not None
        else ()
    )
    working = {item.response_id: item for item in existing}
    for record in existing:
        selection = selection_by_id.get(record.response_id)
        alias = alias_by_id.get(record.response_id)
        if selection is None or alias is None:
            raise BucketAudioRecoveryError(
                f"ledger record {record.response_id!r} is absent from the plan"
            )
        _validate_record_binding(
            record,
            plan=plan,
            alias=alias,
            selection=selection,
            default_locale=default_locale,
        )

    cache_root = Path(cache_dir)
    if cache_root.is_symlink():
        raise BucketAudioRecoveryError("cache_dir must not be a symlink")
    changed_records = 0
    checkpointed_records = 0
    successful_ids: set[str] = set()
    failures: dict[str, BucketAudioRecoveryFailure] = {}
    for selection in target:
        alias = alias_by_id.get(selection.response_id)
        if alias is None:
            raise BucketAudioRecoveryError(
                f"selection {selection.response_id!r} has no source alias"
            )
        existing_record = working.get(selection.response_id)
        try:
            verified, payload, _ = _materialize_selection(
                store=store,
                selection=selection,
                cache_dir=cache_root,
                expected_raw_sha256=(
                    existing_record.raw_sha256
                    if existing_record is not None
                    else None
                ),
                preferred_bucket_path=(
                    existing_record.bucket_path
                    if existing_record is not None
                    else None
                ),
            )
            if existing_record is not None:
                if (
                    existing_record.raw_sha256 != verified.sha256
                    or existing_record.verified_size_bytes != verified.size_bytes
                    or not media_types_compatible(
                        existing_record.media_type, verified.media_type
                    )
                ):
                    raise BucketAudioRecoveryError(
                        "cached bytes changed for verified response "
                        f"{selection.response_id!r}"
                    )
                if decode_probe is None or (
                    existing_record.decode_probe is not None
                    and existing_record.decode_probe.details.get(
                        "full_frame_decode"
                    )
                    is True
                ):
                    successful_ids.add(selection.response_id)
                    continue
        except (
            BucketAudioRecoveryError,
            HuggingFaceBucketError,
            OSError,
        ) as exc:
            if fail_fast:
                raise
            failures[selection.response_id] = _selection_failure(
                plan=plan,
                selection=selection,
                stage=BucketAudioFailureStage.FETCH_AND_VERIFY,
                detail=_operational_failure_detail(exc),
                retryable=True,
            )
            continue

        try:
            spoken_text, locale = _alias_spoken_text(
                alias, default_locale=default_locale
            )
            evidence = _probe(decode_probe, payload, verified.media_type)
        except BucketAudioRecoveryError as exc:
            if fail_fast:
                raise
            failures[selection.response_id] = _selection_failure(
                plan=plan,
                selection=selection,
                stage=BucketAudioFailureStage.DECODE_PROBE,
                detail=_operational_failure_detail(exc),
                retryable=True,
            )
            continue
        record = VerifiedBucketAudioRecord(
            plan_id=plan.plan_id,
            listing_sha256=plan.listing_sha256,
            bucket_id=plan.bucket_id,
            response_id=selection.response_id,
            canonical_text_sha256=alias.canonical_text_sha256,
            spoken_text=spoken_text,
            locale=locale,
            legacy_text_hash=alias.legacy_text_hash,
            source_ref=alias.source_ref,
            source_record_sha256=alias.source_record_sha256,
            bucket_path=verified.path,
            xet_hash=selection.selected.xet_hash or "",
            listed_size_bytes=selection.selected.size_bytes,
            verified_size_bytes=verified.size_bytes,
            raw_sha256=verified.sha256,
            media_type=verified.media_type,
            decode_probe=evidence,
        )
        working[record.response_id] = record
        successful_ids.add(record.response_id)
        changed_records += 1
        if (
            ledger_path is not None
            and changed_records % checkpoint_interval == 0
        ):
            write_verified_bucket_audio_jsonl(ledger_path, working.values())
            checkpointed_records = changed_records

    if ledger_path is not None and changed_records != checkpointed_records:
        write_verified_bucket_audio_jsonl(ledger_path, working.values())
    result_records = tuple(
        working[item] for item in target_ids if item in successful_ids
    )
    result_failures = tuple(
        failures[item] for item in target_ids if item in failures
    )
    return AbbyVoiceBucketAudioRecovery(
        plan_id=plan.plan_id,
        listing_sha256=plan.listing_sha256,
        bucket_id=plan.bucket_id,
        planned_selection_count=len(selections),
        target_response_ids=target_ids,
        records=result_records,
        failures=result_failures,
    )


__all__ = [
    "ABBY_VOICE_BUCKET_AUDIO_RECOVERY_SCHEMA_VERSION",
    "BUCKET_AUDIO_RECOVERY_FAILURE_SCHEMA_VERSION",
    "PENDING_BUCKET_AUDIO_ADMISSION_STATUS",
    "PENDING_BUCKET_AUDIO_CANDIDATE_SCHEMA_VERSION",
    "VERIFIED_BUCKET_AUDIO_RECORD_SCHEMA_VERSION",
    "AbbyVoiceBucketAudioRecovery",
    "BucketAudioFailureStage",
    "BucketAudioRecoveryFailure",
    "BucketAudioRecoveryError",
    "DecodeProbe",
    "DecodeProbeEvidence",
    "PendingBucketAudioCandidate",
    "VerifiedBucketAudioRecord",
    "bucket_audio_cache_path",
    "parse_verified_bucket_audio_jsonl",
    "read_verified_bucket_audio_jsonl",
    "recover_abby_voice_bucket_audio",
    "verified_bucket_audio_jsonl_bytes",
    "write_verified_bucket_audio_jsonl",
]
