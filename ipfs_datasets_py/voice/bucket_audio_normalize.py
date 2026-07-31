"""Normalize every HF bucket object into a closed entry schema.

The recovery *plan* selects one preferred recording per accepted response
(~13.7k).  The bucket still holds tens of thousands of additional objects:
alternate run/phase copies, unmapped ``abby-tts-*`` files, speaker prompts,
smoke assets, and metadata.  This module emits one auditable normalized row
per discovered object so nothing is silently dropped.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any

from .bucket_audio_inventory import (
    ABBY_VOICE_BUCKET_AUDIO_INVENTORY_SCHEMA_VERSION,
    AbbyVoiceBucketAudioInventory,
    BucketAudioObjectClass,
    NormalizedBucketAudioObject,
    build_bucket_audio_inventory,
)
from .bucket_audio_plan import (
    AbbyVoiceBucketAudioPlan,
    BucketAudioSelection,
    SourceResponseAlias,
)

ABBY_VOICE_BUCKET_AUDIO_ENTRY_SCHEMA_VERSION = (
    "abby_voice_bucket_audio_entry_v1"
)
ABBY_VOICE_BUCKET_AUDIO_NORMALIZED_SCHEMA_VERSION = (
    "abby_voice_bucket_audio_normalized_v1"
)
ABBY_VOICE_BUCKET_AUDIO_NORMALIZED_VERSION = "1.0.0"

_HASH20_RE = __import__("re").compile(r"^[0-9a-f]{20}$")
_HASH64_RE = __import__("re").compile(r"^[0-9a-f]{64}$")


class BucketAudioMappingStatus(StrEnum):
    """How one bucket object relates to the accepted response corpus."""

    SELECTED_FOR_RESPONSE = "selected_for_response"
    ALTERNATE_FOR_RESPONSE = "alternate_for_response"
    UNMAPPED_LINKABLE = "unmapped_linkable"
    # Deterministic / ASR rescues for previously unmapped linkable audio.
    MAPPED_TO_VOCABULARY = "mapped_to_vocabulary"
    MAPPED_TO_QUARANTINED_RESPONSE = "mapped_to_quarantined_response"
    ASR_RESCUED_RESPONSE = "asr_rescued_response"
    ASR_RESCUED_VOCABULARY = "asr_rescued_vocabulary"
    ASR_UNMATCHED = "asr_unmatched"
    NON_RESPONSE_AUDIO = "non_response_audio"
    EMPTY_OR_ARCHIVE = "empty_or_archive"
    METADATA_ONLY = "metadata_only"
    NON_AUDIO = "non_audio"


class BucketAudioSubjectKind(StrEnum):
    """Semantic subject bound to a normalized bucket entry."""

    RESPONSE = "response"
    VOCABULARY = "vocabulary"
    BM25_TERM = "bm25_term"
    NONE = "none"


class BucketAudioMappingMethod(StrEnum):
    """How the subject binding was established."""

    PLAN_ALIAS = "plan_alias"
    PLAN_SELECTION = "plan_selection"
    BM25_TEXT_HASH = "bm25_text_hash"
    VOCABULARY_TEXT_HASH = "vocabulary_text_hash"
    QUARANTINED_SOURCE_HASH = "quarantined_source_hash"
    ASR_EXACT_NORMALIZED = "asr_exact_normalized"
    ASR_WER_THRESHOLD = "asr_wer_threshold"
    NONE = "none"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _required_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{label} must be non-empty without surrounding whitespace")
    if "\x00" in value:
        raise ValueError(f"{label} must not contain NUL")
    return value


def _stable_entry_id(path: str, listing_sha256: str) -> str:
    digest = sha256(
        _canonical_bytes({"listing_sha256": listing_sha256, "path": path})
    ).hexdigest()
    return f"bucket-audio-entry:sha256:{digest}"


def _mapping_status_for_class(
    object_class: BucketAudioObjectClass,
) -> BucketAudioMappingStatus:
    if object_class is BucketAudioObjectClass.RESPONSE_LINKABLE:
        return BucketAudioMappingStatus.UNMAPPED_LINKABLE
    if object_class in {
        BucketAudioObjectClass.SPEAKER_PROMPT,
        BucketAudioObjectClass.DIAGNOSTIC_SMOKE,
        BucketAudioObjectClass.UNKNOWN_AUDIO,
        BucketAudioObjectClass.PRODUCTION_RUN_OTHER,
    }:
        return BucketAudioMappingStatus.NON_RESPONSE_AUDIO
    if object_class in {
        BucketAudioObjectClass.EMPTY_PLACEHOLDER,
        BucketAudioObjectClass.ARCHIVE_BUNDLE,
    }:
        return BucketAudioMappingStatus.EMPTY_OR_ARCHIVE
    if object_class is BucketAudioObjectClass.LOG_OR_METADATA:
        return BucketAudioMappingStatus.METADATA_ONLY
    return BucketAudioMappingStatus.NON_AUDIO


@dataclass(frozen=True, slots=True)
class NormalizedBucketAudioEntry:
    """One normalized row for a single bucket object path."""

    entry_id: str
    path: str
    size_bytes: int
    object_class: BucketAudioObjectClass
    mapping_status: BucketAudioMappingStatus
    listing_sha256: str
    bucket_id: str
    xet_hash: str | None = None
    media_extension: str | None = None
    legacy_text_hash: str | None = None
    run_id: str | None = None
    phase: str | None = None
    response_id: str | None = None
    canonical_text_sha256: str | None = None
    source_id: str | None = None
    source_ref: str | None = None
    is_preferred_selection: bool = False
    alternate_rank: int | None = None
    subject_kind: BucketAudioSubjectKind = BucketAudioSubjectKind.NONE
    subject_id: str | None = None
    mapping_method: BucketAudioMappingMethod = BucketAudioMappingMethod.NONE
    source_text: str | None = None
    asr_wer_bp: int | None = None
    schema_version: str = ABBY_VOICE_BUCKET_AUDIO_ENTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _required_text(self.entry_id, label="entry_id")
        _required_text(self.path, label="path")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("size_bytes must be a non-negative integer")
        object.__setattr__(self, "object_class", BucketAudioObjectClass(self.object_class))
        object.__setattr__(
            self, "mapping_status", BucketAudioMappingStatus(self.mapping_status)
        )
        object.__setattr__(
            self, "subject_kind", BucketAudioSubjectKind(self.subject_kind)
        )
        object.__setattr__(
            self, "mapping_method", BucketAudioMappingMethod(self.mapping_method)
        )
        if not _HASH64_RE.fullmatch(self.listing_sha256):
            raise ValueError("listing_sha256 must be a full lowercase SHA-256")
        _required_text(self.bucket_id, label="bucket_id")
        if self.legacy_text_hash is not None and not _HASH20_RE.fullmatch(
            self.legacy_text_hash
        ):
            raise ValueError("legacy_text_hash must be 20 lowercase hex characters")
        if self.canonical_text_sha256 is not None and not _HASH64_RE.fullmatch(
            self.canonical_text_sha256
        ):
            raise ValueError("canonical_text_sha256 must be a full lowercase SHA-256")
        if not isinstance(self.is_preferred_selection, bool):
            raise TypeError("is_preferred_selection must be boolean")
        if self.alternate_rank is not None and (
            isinstance(self.alternate_rank, bool)
            or not isinstance(self.alternate_rank, int)
            or self.alternate_rank < 1
        ):
            raise ValueError("alternate_rank must be a positive integer when set")
        if self.asr_wer_bp is not None and (
            isinstance(self.asr_wer_bp, bool)
            or not isinstance(self.asr_wer_bp, int)
            or self.asr_wer_bp < 0
            or self.asr_wer_bp > 10_000
        ):
            raise ValueError("asr_wer_bp must be an integer basis point in 0..10000")
        if self.source_text is not None and (
            not isinstance(self.source_text, str) or "\x00" in self.source_text
        ):
            raise ValueError("source_text must be text without NUL")
        if self.schema_version != ABBY_VOICE_BUCKET_AUDIO_ENTRY_SCHEMA_VERSION:
            raise ValueError("unsupported bucket audio entry schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternate_rank": self.alternate_rank,
            "asr_wer_bp": self.asr_wer_bp,
            "bucket_id": self.bucket_id,
            "canonical_text_sha256": self.canonical_text_sha256,
            "entry_id": self.entry_id,
            "is_preferred_selection": self.is_preferred_selection,
            "legacy_text_hash": self.legacy_text_hash,
            "listing_sha256": self.listing_sha256,
            "mapping_method": self.mapping_method.value,
            "mapping_status": self.mapping_status.value,
            "media_extension": self.media_extension,
            "object_class": self.object_class.value,
            "path": self.path,
            "phase": self.phase,
            "response_id": self.response_id,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "size_bytes": self.size_bytes,
            "source_id": self.source_id,
            "source_ref": self.source_ref,
            "source_text": self.source_text,
            "subject_id": self.subject_id,
            "subject_kind": self.subject_kind.value,
            "xet_hash": self.xet_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> NormalizedBucketAudioEntry:
        if not isinstance(value, Mapping):
            raise TypeError("normalized bucket audio entry must be a mapping")
        return cls(
            entry_id=str(value["entry_id"]),
            path=str(value["path"]),
            size_bytes=int(value["size_bytes"]),
            object_class=BucketAudioObjectClass(value["object_class"]),
            mapping_status=BucketAudioMappingStatus(value["mapping_status"]),
            listing_sha256=str(value["listing_sha256"]),
            bucket_id=str(value["bucket_id"]),
            xet_hash=value.get("xet_hash"),
            media_extension=value.get("media_extension"),
            legacy_text_hash=value.get("legacy_text_hash"),
            run_id=value.get("run_id"),
            phase=value.get("phase"),
            response_id=value.get("response_id"),
            canonical_text_sha256=value.get("canonical_text_sha256"),
            source_id=value.get("source_id"),
            source_ref=value.get("source_ref"),
            is_preferred_selection=bool(value.get("is_preferred_selection")),
            alternate_rank=value.get("alternate_rank"),
            subject_kind=BucketAudioSubjectKind(
                value.get("subject_kind") or BucketAudioSubjectKind.NONE
            ),
            subject_id=value.get("subject_id"),
            mapping_method=BucketAudioMappingMethod(
                value.get("mapping_method") or BucketAudioMappingMethod.NONE
            ),
            source_text=value.get("source_text"),
            asr_wer_bp=value.get("asr_wer_bp"),
            schema_version=str(
                value.get("schema_version")
                or ABBY_VOICE_BUCKET_AUDIO_ENTRY_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class AbbyVoiceBucketAudioNormalizedBundle:
    """Content-addressed bundle of every normalized bucket entry."""

    entries: tuple[NormalizedBucketAudioEntry, ...]
    bucket_id: str
    listing_sha256: str
    plan_id: str | None = None
    inventory_id: str | None = None
    schema_version: str = ABBY_VOICE_BUCKET_AUDIO_NORMALIZED_SCHEMA_VERSION
    normalized_version: str = ABBY_VOICE_BUCKET_AUDIO_NORMALIZED_VERSION
    normalized_id: str = ""

    def __post_init__(self) -> None:
        _required_text(self.bucket_id, label="bucket_id")
        if not _HASH64_RE.fullmatch(self.listing_sha256):
            raise ValueError("listing_sha256 must be a full lowercase SHA-256")
        entries = tuple(sorted(self.entries, key=lambda item: item.path))
        paths = [item.path for item in entries]
        if len(paths) != len(set(paths)):
            raise ValueError("normalized entry paths must be unique")
        if any(
            item.listing_sha256 != self.listing_sha256
            or item.bucket_id != self.bucket_id
            for item in entries
        ):
            raise ValueError("every entry must bind the same bucket listing")
        if self.schema_version != ABBY_VOICE_BUCKET_AUDIO_NORMALIZED_SCHEMA_VERSION:
            raise ValueError("unsupported normalized bucket audio schema")
        object.__setattr__(self, "entries", entries)
        computed = (
            "abby-voice-bucket-audio-normalized:sha256:"
            + sha256(_canonical_bytes(self.identity_dict())).hexdigest()
        )
        if self.normalized_id and self.normalized_id != computed:
            raise ValueError("normalized_id does not match bundle content")
        object.__setattr__(self, "normalized_id", computed)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "bucket_id": self.bucket_id,
            "entries": [item.to_dict() for item in self.entries],
            "inventory_id": self.inventory_id,
            "listing_sha256": self.listing_sha256,
            "normalized_version": self.normalized_version,
            "plan_id": self.plan_id,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        counts = Counter(item.mapping_status.value for item in self.entries)
        class_counts = Counter(item.object_class.value for item in self.entries)
        mapped = sum(
            1
            for item in self.entries
            if item.mapping_status
            in {
                BucketAudioMappingStatus.SELECTED_FOR_RESPONSE,
                BucketAudioMappingStatus.ALTERNATE_FOR_RESPONSE,
            }
        )
        return {
            **self.identity_dict(),
            "class_counts": dict(sorted(class_counts.items())),
            "entry_count": len(self.entries),
            "mapped_to_response_count": mapped,
            "mapping_status_counts": dict(sorted(counts.items())),
            "normalized_id": self.normalized_id,
            "preferred_selection_count": sum(
                1 for item in self.entries if item.is_preferred_selection
            ),
            "response_linkable_count": sum(
                1
                for item in self.entries
                if item.object_class is BucketAudioObjectClass.RESPONSE_LINKABLE
            ),
            "unmapped_linkable_count": sum(
                1
                for item in self.entries
                if item.mapping_status is BucketAudioMappingStatus.UNMAPPED_LINKABLE
            ),
        }

    def summary(self) -> dict[str, Any]:
        payload = self.to_dict()
        return {
            "bucket_id": self.bucket_id,
            "class_counts": payload["class_counts"],
            "entry_count": payload["entry_count"],
            "inventory_id": self.inventory_id,
            "listing_sha256": self.listing_sha256,
            "mapped_to_response_count": payload["mapped_to_response_count"],
            "mapping_status_counts": payload["mapping_status_counts"],
            "normalized_id": self.normalized_id,
            "plan_id": self.plan_id,
            "preferred_selection_count": payload["preferred_selection_count"],
            "response_linkable_count": payload["response_linkable_count"],
            "schema_version": self.schema_version,
            "unmapped_linkable_count": payload["unmapped_linkable_count"],
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_jsonl_bytes(self) -> bytes:
        return b"".join(
            json.dumps(
                item.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
            for item in self.entries
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AbbyVoiceBucketAudioNormalizedBundle:
        if not isinstance(value, Mapping):
            raise TypeError("normalized bundle must be a mapping")
        raw_entries = value.get("entries")
        if not isinstance(raw_entries, Sequence) or isinstance(
            raw_entries, (str, bytes, bytearray)
        ):
            raise TypeError("normalized bundle entries must be a sequence")
        # Always recompute content-addressed id so additive entry fields
        # (rescue metadata) do not fail closed on older bundle payloads.
        return cls(
            entries=tuple(
                NormalizedBucketAudioEntry.from_dict(item) for item in raw_entries
            ),
            bucket_id=str(value["bucket_id"]),
            listing_sha256=str(value["listing_sha256"]),
            plan_id=value.get("plan_id"),
            inventory_id=value.get("inventory_id"),
            schema_version=str(
                value.get("schema_version")
                or ABBY_VOICE_BUCKET_AUDIO_NORMALIZED_SCHEMA_VERSION
            ),
            normalized_version=str(
                value.get("normalized_version")
                or ABBY_VOICE_BUCKET_AUDIO_NORMALIZED_VERSION
            ),
            normalized_id="",
        )


def normalize_bucket_audio_entries(
    *,
    inventory: AbbyVoiceBucketAudioInventory | Iterable[Mapping[str, Any] | object],
    plan: AbbyVoiceBucketAudioPlan | None = None,
    aliases: Iterable[SourceResponseAlias] = (),
    selections: Iterable[BucketAudioSelection] = (),
    bucket_id: str | None = None,
    listing_sha256: str | None = None,
    plan_id: str | None = None,
) -> AbbyVoiceBucketAudioNormalizedBundle:
    """Normalize every inventory object, joining plan aliases when present.

    * Every discovered path becomes one entry (no silent drops).
    * Preferred plan selections are marked ``selected_for_response``.
    * Other paths sharing a selected legacy hash are ``alternate_for_response``.
    * Response-linkable paths without an accepted alias are ``unmapped_linkable``.
    """

    if isinstance(inventory, AbbyVoiceBucketAudioInventory):
        inv = inventory
    else:
        if not bucket_id or not listing_sha256:
            raise ValueError(
                "bucket_id and listing_sha256 are required when inventory is raw objects"
            )
        inv = build_bucket_audio_inventory(
            inventory,
            bucket_id=bucket_id,
            listing_sha256=listing_sha256,
        )

    alias_by_hash: dict[str, SourceResponseAlias] = {}
    alias_source = (
        tuple(plan.aliases)
        if plan is not None
        else tuple(aliases)
    )
    for alias in alias_source:
        if not isinstance(alias, SourceResponseAlias):
            raise TypeError("aliases must contain SourceResponseAlias values")
        previous = alias_by_hash.get(alias.legacy_text_hash)
        if previous is not None and previous.response_id != alias.response_id:
            raise ValueError(
                f"conflicting aliases for legacy hash {alias.legacy_text_hash!r}"
            )
        alias_by_hash[alias.legacy_text_hash] = alias

    selection_by_path: dict[str, tuple[BucketAudioSelection, bool, int | None]] = {}
    selection_source = (
        tuple(plan.selections)
        if plan is not None
        else tuple(selections)
    )
    for selection in selection_source:
        if not isinstance(selection, BucketAudioSelection):
            raise TypeError("selections must contain BucketAudioSelection values")
        selection_by_path[selection.selected.path] = (selection, True, None)
        for rank, alt in enumerate(selection.alternatives, start=1):
            selection_by_path[alt.path] = (selection, False, rank)

    entries: list[NormalizedBucketAudioEntry] = []
    for obj in inv.objects:
        selection_hit = selection_by_path.get(obj.path)
        alias = (
            alias_by_hash.get(obj.legacy_text_hash)
            if obj.legacy_text_hash is not None
            else None
        )
        subject_kind = BucketAudioSubjectKind.NONE
        subject_id: str | None = None
        mapping_method = BucketAudioMappingMethod.NONE
        if selection_hit is not None:
            selection, preferred, rank = selection_hit
            mapping_status = (
                BucketAudioMappingStatus.SELECTED_FOR_RESPONSE
                if preferred
                else BucketAudioMappingStatus.ALTERNATE_FOR_RESPONSE
            )
            response_id = selection.response_id
            legacy_hash = selection.legacy_text_hash
            subject_kind = BucketAudioSubjectKind.RESPONSE
            subject_id = response_id
            mapping_method = BucketAudioMappingMethod.PLAN_SELECTION
            if alias is None:
                # Selection implies an alias existed at plan time; still join if
                # available via hash for canonical text metadata.
                alias = alias_by_hash.get(legacy_hash)
        elif (
            obj.object_class is BucketAudioObjectClass.RESPONSE_LINKABLE
            and alias is not None
        ):
            # Linkable + aliased but not chosen (should be rare if plan complete).
            mapping_status = BucketAudioMappingStatus.ALTERNATE_FOR_RESPONSE
            response_id = alias.response_id
            legacy_hash = obj.legacy_text_hash
            preferred = False
            rank = None
            subject_kind = BucketAudioSubjectKind.RESPONSE
            subject_id = response_id
            mapping_method = BucketAudioMappingMethod.PLAN_ALIAS
        else:
            mapping_status = _mapping_status_for_class(obj.object_class)
            response_id = alias.response_id if alias is not None else None
            legacy_hash = obj.legacy_text_hash
            preferred = False
            rank = None
            if response_id is not None:
                subject_kind = BucketAudioSubjectKind.RESPONSE
                subject_id = response_id
                mapping_method = BucketAudioMappingMethod.PLAN_ALIAS

        entries.append(
            NormalizedBucketAudioEntry(
                entry_id=_stable_entry_id(obj.path, inv.listing_sha256),
                path=obj.path,
                size_bytes=obj.size_bytes,
                object_class=obj.object_class,
                mapping_status=mapping_status,
                listing_sha256=inv.listing_sha256,
                bucket_id=inv.bucket_id,
                xet_hash=obj.xet_hash,
                media_extension=obj.media_extension,
                legacy_text_hash=legacy_hash,
                run_id=obj.run_id,
                phase=obj.phase,
                response_id=response_id,
                canonical_text_sha256=(
                    alias.canonical_text_sha256 if alias is not None else None
                ),
                source_id=alias.source_id if alias is not None else None,
                source_ref=alias.source_ref if alias is not None else None,
                is_preferred_selection=preferred,
                alternate_rank=rank,
                subject_kind=subject_kind,
                subject_id=subject_id,
                mapping_method=mapping_method,
            )
        )

    return AbbyVoiceBucketAudioNormalizedBundle(
        entries=tuple(entries),
        bucket_id=inv.bucket_id,
        listing_sha256=inv.listing_sha256,
        plan_id=plan_id or (plan.plan_id if plan is not None else None),
        inventory_id=inv.inventory_id,
    )


__all__ = [
    "ABBY_VOICE_BUCKET_AUDIO_ENTRY_SCHEMA_VERSION",
    "ABBY_VOICE_BUCKET_AUDIO_NORMALIZED_SCHEMA_VERSION",
    "ABBY_VOICE_BUCKET_AUDIO_NORMALIZED_VERSION",
    "AbbyVoiceBucketAudioNormalizedBundle",
    "BucketAudioMappingMethod",
    "BucketAudioMappingStatus",
    "BucketAudioSubjectKind",
    "NormalizedBucketAudioEntry",
    "normalize_bucket_audio_entries",
]
