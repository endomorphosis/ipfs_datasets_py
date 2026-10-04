"""Normalize every object in the Abby HF bucket under a closed inventory schema.

The Publicus/abby-voice bucket mixes:

* production IndexTTS MP3s under ``runs/abby-full-preprocess-*/phase*/audio/``
* residual phase folders, smoke tests, speaker prompts, zips, and empty stubs

Only ``abby-tts-{legacy_text_hash}.{mp3,wav}`` objects can bind to a response
via the legacy text-hash alias. Everything else still needs a deterministic,
auditable inventory row so bulk recovery can see *why* tens of thousands of
files are not response-mapped and so later stages can process orphans under an
explicit policy instead of silently ignoring them.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any

ABBY_VOICE_BUCKET_AUDIO_INVENTORY_SCHEMA_VERSION = (
    "abby_voice_bucket_audio_inventory_v1"
)
ABBY_VOICE_BUCKET_AUDIO_INVENTORY_VERSION = "1.0.0"

_HASH20_RE = re.compile(r"^[0-9a-f]{20}$")
_HASH64_RE = re.compile(r"^[0-9a-f]{64}$")
_RESPONSE_LINKABLE_BASENAME_RE = re.compile(
    r"^abby-tts-(?P<text_hash>[0-9a-f]{20})\.(?P<ext>mp3|wav)$",
    re.IGNORECASE,
)
_PRODUCTION_RUN_RE = re.compile(
    r"(?:^|/)runs/(?P<run_id>abby-full-preprocess-"
    r"(?P<timestamp>[0-9]{8}T[0-9]{6}Z))(?:/|$)"
)
_RUN_ID_RE = re.compile(r"^abby-full-preprocess-[0-9]{8}T[0-9]{6}Z$")
_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"})
_ARCHIVE_EXTENSIONS = frozenset({".zip", ".tar", ".gz", ".tgz", ".7z"})
_LOG_EXTENSIONS = frozenset({".log", ".txt", ".json", ".jsonl", ".md", ".csv"})


class BucketAudioObjectClass(StrEnum):
    """Closed classification for one discovered bucket object."""

    RESPONSE_LINKABLE = "response_linkable"
    PRODUCTION_RUN_OTHER = "production_run_other"
    DIAGNOSTIC_SMOKE = "diagnostic_smoke"
    SPEAKER_PROMPT = "speaker_prompt"
    ARCHIVE_BUNDLE = "archive_bundle"
    EMPTY_PLACEHOLDER = "empty_placeholder"
    LOG_OR_METADATA = "log_or_metadata"
    UNKNOWN_AUDIO = "unknown_audio"
    NON_AUDIO = "non_audio"


def _required_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{label} must be non-empty without surrounding whitespace")
    if "\x00" in value:
        raise ValueError(f"{label} must not contain NUL")
    return value


def _normalized_path(value: Any) -> str:
    path = _required_text(value, label="path")
    parsed = PurePosixPath(path)
    if (
        "\\" in path
        or parsed.is_absolute()
        or parsed.as_posix() != path
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ValueError("path must be a normalized root-relative POSIX path")
    return path


def _mapping_or_attribute(value: Any, *names: str) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
    else:
        for name in names:
            if hasattr(value, name):
                return getattr(value, name)
    return None


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def discover_production_run_ids(
    discovered_objects: Iterable[Mapping[str, Any] | object],
) -> tuple[str, ...]:
    """Return sorted unique production run IDs observed in object paths."""

    run_ids: set[str] = set()
    for value in discovered_objects:
        path = _mapping_or_attribute(value, "path", "key", "name")
        if not isinstance(path, str) or not path:
            continue
        match = _PRODUCTION_RUN_RE.search(path)
        if match is not None:
            run_ids.add(match.group("run_id"))
    return tuple(sorted(run_ids))


def _phase_from_path(path: str) -> str | None:
    for part in PurePosixPath(path).parts:
        if part == "phase4" or part.startswith("phase4-"):
            return part
        if part.startswith("phase") and any(character.isdigit() for character in part):
            return part
    return None


def classify_bucket_audio_object(
    *,
    path: str,
    size_bytes: int,
) -> tuple[BucketAudioObjectClass, str | None, str | None, str | None, str | None]:
    """Classify one path into the inventory schema.

    Returns ``(object_class, media_extension, legacy_text_hash, run_id, phase)``.
    """

    path = _normalized_path(path)
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes < 0
    ):
        raise ValueError("size_bytes must be a non-negative integer")

    parsed = PurePosixPath(path)
    suffix = parsed.suffix.casefold()
    media_extension = suffix.lstrip(".") if suffix else None
    basename = parsed.name
    run_match = _PRODUCTION_RUN_RE.search(path)
    run_id = run_match.group("run_id") if run_match is not None else None
    phase = _phase_from_path(path)

    linkable = _RESPONSE_LINKABLE_BASENAME_RE.fullmatch(basename)
    if size_bytes == 0 and (
        suffix in _AUDIO_EXTENSIONS or linkable is not None or basename.endswith(".zip")
    ):
        return (
            BucketAudioObjectClass.EMPTY_PLACEHOLDER,
            media_extension,
            linkable.group("text_hash").casefold() if linkable else None,
            run_id,
            phase,
        )
    if linkable is not None:
        return (
            BucketAudioObjectClass.RESPONSE_LINKABLE,
            linkable.group("ext").casefold(),
            linkable.group("text_hash").casefold(),
            run_id,
            phase,
        )
    if suffix in _ARCHIVE_EXTENSIONS:
        return BucketAudioObjectClass.ARCHIVE_BUNDLE, media_extension, None, run_id, phase
    if suffix in _LOG_EXTENSIONS or basename.endswith(".log"):
        return BucketAudioObjectClass.LOG_OR_METADATA, media_extension, None, run_id, phase

    lowered = path.casefold()
    if basename.casefold().startswith("spk_") or "/spk_" in lowered:
        return BucketAudioObjectClass.SPEAKER_PROMPT, media_extension, None, run_id, phase
    if any(
        token in lowered
        for token in (
            "smoke",
            "helper-",
            "space-e2e",
            "live-batch",
            "manifest-batch",
            "phone_dialog",
            "tmp/",
            "tasks/",
        )
    ) or basename.casefold().startswith("test_"):
        if suffix in _AUDIO_EXTENSIONS:
            return (
                BucketAudioObjectClass.DIAGNOSTIC_SMOKE,
                media_extension,
                None,
                run_id,
                phase,
            )
        return BucketAudioObjectClass.NON_AUDIO, media_extension, None, run_id, phase

    if run_id is not None:
        if suffix in _AUDIO_EXTENSIONS:
            return (
                BucketAudioObjectClass.PRODUCTION_RUN_OTHER,
                media_extension,
                None,
                run_id,
                phase,
            )
        return BucketAudioObjectClass.NON_AUDIO, media_extension, None, run_id, phase

    if suffix in _AUDIO_EXTENSIONS:
        return BucketAudioObjectClass.UNKNOWN_AUDIO, media_extension, None, run_id, phase
    return BucketAudioObjectClass.NON_AUDIO, media_extension, None, run_id, phase


@dataclass(frozen=True, slots=True)
class NormalizedBucketAudioObject:
    """One inventory row for a discovered bucket object under the v1 schema."""

    path: str
    size_bytes: int
    object_class: BucketAudioObjectClass
    xet_hash: str | None = None
    media_extension: str | None = None
    legacy_text_hash: str | None = None
    run_id: str | None = None
    phase: str | None = None
    schema_version: str = ABBY_VOICE_BUCKET_AUDIO_INVENTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalized_path(self.path))
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("size_bytes must be a non-negative integer")
        object.__setattr__(self, "object_class", BucketAudioObjectClass(self.object_class))
        if self.xet_hash is not None:
            _required_text(self.xet_hash, label="xet_hash")
        if self.media_extension is not None:
            ext = _required_text(self.media_extension, label="media_extension").casefold()
            object.__setattr__(self, "media_extension", ext)
        if self.legacy_text_hash is not None and not _HASH20_RE.fullmatch(
            self.legacy_text_hash
        ):
            raise ValueError("legacy_text_hash must be 20 lowercase hex characters")
        if self.run_id is not None and _RUN_ID_RE.fullmatch(self.run_id) is None:
            raise ValueError("run_id must be a canonical production run id")
        if self.phase is not None:
            _required_text(self.phase, label="phase")
        if self.schema_version != ABBY_VOICE_BUCKET_AUDIO_INVENTORY_SCHEMA_VERSION:
            raise ValueError("unsupported bucket audio inventory object schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legacy_text_hash": self.legacy_text_hash,
            "media_extension": self.media_extension,
            "object_class": self.object_class.value,
            "path": self.path,
            "phase": self.phase,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "size_bytes": self.size_bytes,
            "xet_hash": self.xet_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> NormalizedBucketAudioObject:
        if not isinstance(value, Mapping):
            raise TypeError("inventory object must be a mapping")
        return cls(
            path=value["path"],
            size_bytes=int(value["size_bytes"]),
            object_class=BucketAudioObjectClass(value["object_class"]),
            xet_hash=value.get("xet_hash"),
            media_extension=value.get("media_extension"),
            legacy_text_hash=value.get("legacy_text_hash"),
            run_id=value.get("run_id"),
            phase=value.get("phase"),
            schema_version=str(
                value.get("schema_version")
                or ABBY_VOICE_BUCKET_AUDIO_INVENTORY_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_discovered(
        cls, value: Mapping[str, Any] | object
    ) -> NormalizedBucketAudioObject:
        path = _mapping_or_attribute(value, "path", "key", "name")
        size = _mapping_or_attribute(value, "size_bytes", "size")
        xet_hash = _mapping_or_attribute(value, "xet_hash")
        path = _normalized_path(path)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("size_bytes must be a non-negative integer")
        object_class, media_extension, legacy_hash, run_id, phase = (
            classify_bucket_audio_object(path=path, size_bytes=size)
        )
        return cls(
            path=path,
            size_bytes=size,
            object_class=object_class,
            xet_hash=xet_hash if isinstance(xet_hash, str) and xet_hash else None,
            media_extension=media_extension,
            legacy_text_hash=legacy_hash,
            run_id=run_id,
            phase=phase,
        )


@dataclass(frozen=True, slots=True)
class AbbyVoiceBucketAudioInventory:
    """Content-addressed inventory over every discovered bucket object."""

    objects: tuple[NormalizedBucketAudioObject, ...]
    bucket_id: str
    listing_sha256: str
    schema_version: str = ABBY_VOICE_BUCKET_AUDIO_INVENTORY_SCHEMA_VERSION
    inventory_version: str = ABBY_VOICE_BUCKET_AUDIO_INVENTORY_VERSION
    inventory_id: str = ""

    def __post_init__(self) -> None:
        _required_text(self.bucket_id, label="bucket_id")
        if not _HASH64_RE.fullmatch(self.listing_sha256):
            raise ValueError("listing_sha256 must be a full lowercase SHA-256")
        objects = tuple(sorted(self.objects, key=lambda item: item.path))
        paths = [item.path for item in objects]
        if len(paths) != len(set(paths)):
            raise ValueError("inventory object paths must be unique")
        if self.schema_version != ABBY_VOICE_BUCKET_AUDIO_INVENTORY_SCHEMA_VERSION:
            raise ValueError("unsupported bucket audio inventory schema")
        object.__setattr__(self, "objects", objects)
        computed = (
            "abby-voice-bucket-audio-inventory:sha256:"
            + sha256(_canonical_bytes(self.identity_dict())).hexdigest()
        )
        if self.inventory_id and self.inventory_id != computed:
            raise ValueError("inventory_id does not match inventory content")
        object.__setattr__(self, "inventory_id", computed)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "bucket_id": self.bucket_id,
            "inventory_version": self.inventory_version,
            "listing_sha256": self.listing_sha256,
            "objects": [item.to_dict() for item in self.objects],
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        counts = Counter(item.object_class.value for item in self.objects)
        linkable = sum(
            1
            for item in self.objects
            if item.object_class is BucketAudioObjectClass.RESPONSE_LINKABLE
        )
        return {
            **self.identity_dict(),
            "class_counts": dict(sorted(counts.items())),
            "inventory_id": self.inventory_id,
            "object_count": len(self.objects),
            "production_run_ids": list(self.production_run_ids),
            "response_linkable_count": linkable,
        }

    def summary(self) -> dict[str, Any]:
        payload = self.to_dict()
        return {
            "class_counts": payload["class_counts"],
            "inventory_id": self.inventory_id,
            "object_count": payload["object_count"],
            "production_run_count": len(self.production_run_ids),
            "response_linkable_count": payload["response_linkable_count"],
            "schema_version": self.schema_version,
        }

    @property
    def production_run_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.run_id
                    for item in self.objects
                    if item.run_id is not None
                }
            )
        )

    @property
    def response_linkable_objects(self) -> tuple[NormalizedBucketAudioObject, ...]:
        return tuple(
            item
            for item in self.objects
            if item.object_class is BucketAudioObjectClass.RESPONSE_LINKABLE
        )

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
            for item in self.objects
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AbbyVoiceBucketAudioInventory:
        if not isinstance(value, Mapping):
            raise TypeError("inventory must be a mapping")
        objects_payload = value.get("objects")
        if not isinstance(objects_payload, Sequence) or isinstance(
            objects_payload, (str, bytes, bytearray)
        ):
            raise TypeError("inventory objects must be a sequence")
        return cls(
            objects=tuple(
                NormalizedBucketAudioObject.from_dict(item)
                for item in objects_payload
            ),
            bucket_id=str(value["bucket_id"]),
            listing_sha256=str(value["listing_sha256"]),
            schema_version=str(
                value.get("schema_version")
                or ABBY_VOICE_BUCKET_AUDIO_INVENTORY_SCHEMA_VERSION
            ),
            inventory_version=str(
                value.get("inventory_version")
                or ABBY_VOICE_BUCKET_AUDIO_INVENTORY_VERSION
            ),
            inventory_id=str(value.get("inventory_id") or ""),
        )


def build_bucket_audio_inventory(
    discovered_objects: Iterable[Mapping[str, Any] | object],
    *,
    bucket_id: str,
    listing_sha256: str,
) -> AbbyVoiceBucketAudioInventory:
    """Normalize every discovered object into the closed inventory schema."""

    by_path: dict[str, NormalizedBucketAudioObject] = {}
    for value in discovered_objects:
        item = NormalizedBucketAudioObject.from_discovered(value)
        previous = by_path.get(item.path)
        if previous is not None and previous != item:
            raise ValueError(
                f"conflicting bucket inventory metadata for path {item.path!r}"
            )
        by_path[item.path] = item
    return AbbyVoiceBucketAudioInventory(
        objects=tuple(by_path.values()),
        bucket_id=bucket_id,
        listing_sha256=listing_sha256,
    )


__all__ = [
    "ABBY_VOICE_BUCKET_AUDIO_INVENTORY_SCHEMA_VERSION",
    "ABBY_VOICE_BUCKET_AUDIO_INVENTORY_VERSION",
    "AbbyVoiceBucketAudioInventory",
    "BucketAudioObjectClass",
    "NormalizedBucketAudioObject",
    "build_bucket_audio_inventory",
    "classify_bucket_audio_object",
    "discover_production_run_ids",
]
