"""Plan exact legacy Abby bucket-audio recovery without downloading bytes.

The aggregate Abby response manifest and the historical audio bucket use a
legacy, truncated text hash in object names such as
``abby-tts-0123456789abcdefabcd.mp3``.  Canonical v2 response identity is
different: it is derived from display text, normalized spoken text, locale,
and intent.  This module builds an explicit, auditable alias between those two
identity domains before selecting remote objects.

Planning is deliberately dependency-light and side-effect free.  Discovered
bucket objects may be mappings or objects with ``path``, ``size_bytes`` and
optional ``xet_hash`` attributes.  Xet hashes are retained as opaque storage
metadata only.  They are never exposed as a raw audio SHA-256 and this module
never constructs :class:`~ipfs_datasets_py.voice.legacy_sources.LegacyAudioCandidate`.
Callers must download the selected bytes, calculate their full SHA-256, and
run the existing integrity/decode gates before reconciliation.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any

from .normalize import normalize_indextts_spoken_text, record_sha256
from .schema import AbbyVoiceResponse, stable_response_id

ABBY_VOICE_BUCKET_AUDIO_PLAN_SCHEMA_VERSION = "abby_voice_bucket_audio_plan_v1"
ABBY_VOICE_BUCKET_AUDIO_PLAN_VERSION = "1.0.0"

_HASH20_RE = re.compile(r"^[0-9a-f]{20}$")
_HASH64_RE = re.compile(r"^[0-9a-f]{64}$")
# Response-linkable basenames under the normalized inventory schema.
# Historical production audio is MP3; WAV variants of the same text hash are
# also accepted so residual/re-encoded objects can map after inventory normalize.
_AUDIO_BASENAME_RE = re.compile(
    r"^abby-tts-(?P<text_hash>[0-9a-f]{20})\.(?P<ext>mp3|wav)$",
    re.IGNORECASE,
)
_RUN_ID_RE = re.compile(
    r"^abby-full-preprocess-[0-9]{8}T[0-9]{6}Z$"
)
_PRODUCTION_RUN_RE = re.compile(
    r"(?:^|/)runs/(?P<run_id>abby-full-preprocess-"
    r"(?P<timestamp>[0-9]{8}T[0-9]{6}Z))(?:/|$)"
)
_SPACE_RE = re.compile(r"\s+")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _strict_mapping(
    value: Mapping[str, Any], *, expected: frozenset[str], label: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(
            f"{label} has missing fields {missing!r} and unknown fields {unknown!r}"
        )
    return value


def _json_mapping(value: str | bytes | bytearray, *, label: str) -> Mapping[str, Any]:
    if isinstance(value, bytes | bytearray):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{label} JSON must be UTF-8") from exc
    if not isinstance(value, str):
        raise TypeError(f"{label} JSON must be str or bytes")
    try:
        decoded = json.loads(value)
    except ValueError as exc:
        raise ValueError(f"{label} JSON is invalid: {exc}") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError(f"{label} JSON must encode a mapping")
    return decoded


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


def _optional_text(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, label=label)


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


def _ordered_source_rows(
    manifest: Mapping[str, Any] | Sequence[Any],
) -> tuple[Mapping[str, Any], ...]:
    if isinstance(manifest, Mapping):
        rows: Any = manifest.get("responses")
        if rows is None and all(
            key not in manifest
            for key in ("templates", "audio", "audios", "provenance")
        ):
            rows = (manifest,)
    else:
        rows = manifest
    if (
        isinstance(rows, str | bytes | bytearray | Mapping)
        or not isinstance(rows, Sequence)
    ):
        raise ValueError("source manifest must contain a response sequence")
    if not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("source manifest responses must be mappings")
    return tuple(rows)


def _first(record: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in record and record[name] not in (None, ""):
            return record[name]
    return None


def _sorted_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = (value,) if isinstance(value, str) else value
    if not isinstance(values, Sequence) or isinstance(values, bytes | bytearray):
        return ()
    return tuple(
        sorted(
            {
                _SPACE_RE.sub(" ", str(item)).strip()
                for item in values
                if _SPACE_RE.sub(" ", str(item)).strip()
            }
        )
    )


def _source_response_identity(
    record: Mapping[str, Any], *, default_locale: str
) -> tuple[str, str, str, str | None]:
    """Mirror the canonical response identity fields used by the normalizer."""

    raw_text = str(record.get("text") or record.get("spoken_text") or "").strip()
    originals = record.get("originalTexts")
    display_text = str(
        _first(record, "response_text", "responseText")
        or (
            originals[0]
            if isinstance(originals, Sequence)
            and not isinstance(originals, str | bytes)
            and originals
            else ""
        )
        or raw_text
    ).strip()
    spoken_text = normalize_indextts_spoken_text(raw_text)
    routes = _sorted_strings(_first(record, "route_labels", "routes"))
    intent = (
        str(record.get("intent") or (routes[0] if routes else "")).strip() or None
    )
    locale = str(record.get("locale") or default_locale)
    return display_text, spoken_text, locale, intent


def _source_ref(source_uri: str, source_record_sha256: str) -> str:
    return f"{source_uri}#response-sha256={source_record_sha256}"


def _object_preference(item: BucketAudioDiscoveryObject) -> tuple[int, int, int, int, str]:
    """Rank production, phase4, MP3-over-WAV, newer run, then lexical path."""

    run_match = _PRODUCTION_RUN_RE.search(item.path)
    production_rank = 0 if run_match is not None else 1
    phase4_rank = (
        0
        if any(part == "phase4" or part.startswith("phase4-") for part in PurePosixPath(item.path).parts)
        else 1
    )
    suffix = PurePosixPath(item.path).suffix.casefold()
    media_rank = 0 if suffix == ".mp3" else 1 if suffix == ".wav" else 2
    timestamp = run_match.group("timestamp") if run_match is not None else ""
    timestamp_rank = -int(timestamp.replace("T", "").removesuffix("Z") or "0")
    return production_rank, phase4_rank, media_rank, timestamp_rank, item.path


class SourceAliasExclusionReason(StrEnum):
    """Why a source response was intentionally omitted from audio planning."""

    UNACCEPTED_RESPONSE = "unaccepted_response"
    QUARANTINED_SOURCE = "quarantined_source"
    INVALID_SOURCE_ROW = "invalid_source_row"
    MISSING_LEGACY_TEXT_HASH = "missing_legacy_text_hash"
    LEGACY_TEXT_HASH_MISMATCH = "legacy_text_hash_mismatch"
    AMBIGUOUS_SOURCE_ALIAS = "ambiguous_source_alias"


@dataclass(frozen=True, slots=True)
class BucketAudioDiscoveryObject:
    """Dependency-neutral projection of one object returned by a bucket listing.

    ``xet_hash`` is storage metadata.  It does not assert anything about the
    SHA-256 of the downloaded audio bytes.
    """

    path: str
    size_bytes: int
    xet_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalized_path(self.path))
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("size_bytes must be a non-negative integer")
        object.__setattr__(
            self,
            "xet_hash",
            _optional_text(self.xet_hash, label="xet_hash"),
        )

    @classmethod
    def from_discovered(cls, value: Mapping[str, Any] | object) -> BucketAudioDiscoveryObject:
        """Normalize a mapping or a Hugging Face listing object."""

        if isinstance(value, cls):
            return value
        path = _mapping_or_attribute(value, "path", "key", "name")
        size = _mapping_or_attribute(value, "size_bytes", "size")
        xet_hash = _mapping_or_attribute(value, "xet_hash")
        return cls(path=path, size_bytes=size, xet_hash=xet_hash)

    @property
    def legacy_text_hash(self) -> str | None:
        match = _AUDIO_BASENAME_RE.fullmatch(PurePosixPath(self.path).name)
        return match.group("text_hash").casefold() if match is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "xet_hash": self.xet_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BucketAudioDiscoveryObject:
        value = _strict_mapping(
            value,
            expected=frozenset({"path", "size_bytes", "xet_hash"}),
            label="bucket audio discovery object",
        )
        return cls(
            path=value["path"],
            size_bytes=value["size_bytes"],
            xet_hash=value["xet_hash"],
        )

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> BucketAudioDiscoveryObject:
        return cls.from_dict(
            _json_mapping(value, label="bucket audio discovery object")
        )


@dataclass(frozen=True, slots=True)
class SourceResponseAlias:
    """Exact binding from a canonical response to one legacy source row."""

    response_id: str
    canonical_text_sha256: str
    legacy_text_hash: str
    source_id: str
    source_ref: str
    source_record_sha256: str
    source_record_json: str = field(repr=False)

    def __post_init__(self) -> None:
        _required_text(self.response_id, label="response_id")
        if not _HASH64_RE.fullmatch(self.canonical_text_sha256):
            raise ValueError("canonical_text_sha256 must be a full lowercase SHA-256")
        if not _HASH20_RE.fullmatch(self.legacy_text_hash):
            raise ValueError("legacy_text_hash must be exactly 20 lowercase hexadecimal characters")
        _required_text(self.source_id, label="source_id")
        _required_text(self.source_ref, label="source_ref")
        if not _HASH64_RE.fullmatch(self.source_record_sha256):
            raise ValueError("source_record_sha256 must be a full lowercase SHA-256")
        try:
            record = json.loads(self.source_record_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("source_record_json must be valid JSON") from exc
        if not isinstance(record, Mapping):
            raise ValueError("source_record_json must encode a mapping")
        canonical_record = _canonical_bytes(record).decode("utf-8")
        if canonical_record != self.source_record_json:
            raise ValueError("source_record_json must use canonical JSON serialization")
        if record_sha256(record) != self.source_record_sha256:
            raise ValueError("source_record_sha256 does not match source_record_json")
        if _legacy_text_hash(record.get("text")) != self.legacy_text_hash:
            raise ValueError(
                "legacy_text_hash does not reproduce the source record text"
            )
        spoken_text = normalize_indextts_spoken_text(
            str(record.get("text") or record.get("spoken_text") or "").strip()
        )
        if sha256(spoken_text.encode("utf-8")).hexdigest() != self.canonical_text_sha256:
            raise ValueError(
                "canonical_text_sha256 does not reproduce the source record text"
            )

    @property
    def source_record(self) -> dict[str, Any]:
        return dict(json.loads(self.source_record_json))

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_text_sha256": self.canonical_text_sha256,
            "legacy_text_hash": self.legacy_text_hash,
            "response_id": self.response_id,
            "source_id": self.source_id,
            "source_record": json.loads(self.source_record_json),
            "source_record_sha256": self.source_record_sha256,
            "source_ref": self.source_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SourceResponseAlias:
        value = _strict_mapping(
            value,
            expected=frozenset(
                {
                    "canonical_text_sha256",
                    "legacy_text_hash",
                    "response_id",
                    "source_id",
                    "source_record",
                    "source_record_sha256",
                    "source_ref",
                }
            ),
            label="source response alias",
        )
        record = value["source_record"]
        if not isinstance(record, Mapping):
            raise ValueError("source response alias source_record must be a mapping")
        return cls(
            response_id=value["response_id"],
            canonical_text_sha256=value["canonical_text_sha256"],
            legacy_text_hash=value["legacy_text_hash"],
            source_id=value["source_id"],
            source_ref=value["source_ref"],
            source_record_sha256=value["source_record_sha256"],
            source_record_json=_canonical_bytes(record).decode("utf-8"),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> SourceResponseAlias:
        return cls.from_dict(_json_mapping(value, label="source response alias"))


@dataclass(frozen=True, slots=True)
class SourceAliasExclusion:
    """Auditable disposition for one source row that was not aliased."""

    source_ref: str
    source_record_sha256: str
    reason: SourceAliasExclusionReason
    response_id: str | None = None
    legacy_text_hash: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.source_ref, label="source_ref")
        if not _HASH64_RE.fullmatch(self.source_record_sha256):
            raise ValueError("source_record_sha256 must be a full lowercase SHA-256")
        object.__setattr__(self, "reason", SourceAliasExclusionReason(self.reason))
        if self.response_id is not None:
            _required_text(self.response_id, label="response_id")
        if self.legacy_text_hash is not None and not _HASH20_RE.fullmatch(
            self.legacy_text_hash
        ):
            raise ValueError("legacy_text_hash must be exactly 20 lowercase hexadecimal characters")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legacy_text_hash": self.legacy_text_hash,
            "reason": self.reason.value,
            "response_id": self.response_id,
            "source_record_sha256": self.source_record_sha256,
            "source_ref": self.source_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SourceAliasExclusion:
        value = _strict_mapping(
            value,
            expected=frozenset(
                {
                    "legacy_text_hash",
                    "reason",
                    "response_id",
                    "source_record_sha256",
                    "source_ref",
                }
            ),
            label="source alias exclusion",
        )
        return cls(
            source_ref=value["source_ref"],
            source_record_sha256=value["source_record_sha256"],
            reason=value["reason"],
            response_id=value["response_id"],
            legacy_text_hash=value["legacy_text_hash"],
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> SourceAliasExclusion:
        return cls.from_dict(_json_mapping(value, label="source alias exclusion"))


@dataclass(frozen=True, slots=True)
class BucketAudioSelection:
    """One deterministic remote-object selection awaiting byte verification."""

    response_id: str
    legacy_text_hash: str
    selected: BucketAudioDiscoveryObject
    alternatives: tuple[BucketAudioDiscoveryObject, ...] = ()

    def __post_init__(self) -> None:
        _required_text(self.response_id, label="response_id")
        if not _HASH20_RE.fullmatch(self.legacy_text_hash):
            raise ValueError("legacy_text_hash must be exactly 20 lowercase hexadecimal characters")
        if not isinstance(self.selected, BucketAudioDiscoveryObject):
            raise TypeError("selected must be a BucketAudioDiscoveryObject")
        alternatives = tuple(sorted(self.alternatives, key=_object_preference))
        if any(not isinstance(item, BucketAudioDiscoveryObject) for item in alternatives):
            raise TypeError("alternatives must contain BucketAudioDiscoveryObject values")
        all_objects = (self.selected, *alternatives)
        paths = [item.path for item in all_objects]
        if len(paths) != len(set(paths)):
            raise ValueError("selected and alternate bucket paths must be unique")
        if any(item.legacy_text_hash != self.legacy_text_hash for item in all_objects):
            raise ValueError("every selected object must exactly match the legacy text hash")
        if self.selected != min(all_objects, key=_object_preference):
            raise ValueError("selected object does not satisfy deterministic preference")
        object.__setattr__(self, "alternatives", alternatives)

    @property
    def requires_raw_sha256_verification(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternatives": [item.to_dict() for item in self.alternatives],
            "legacy_text_hash": self.legacy_text_hash,
            "requires_raw_sha256_verification": True,
            "response_id": self.response_id,
            "selected": self.selected.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BucketAudioSelection:
        value = _strict_mapping(
            value,
            expected=frozenset(
                {
                    "alternatives",
                    "legacy_text_hash",
                    "requires_raw_sha256_verification",
                    "response_id",
                    "selected",
                }
            ),
            label="bucket audio selection",
        )
        if value["requires_raw_sha256_verification"] is not True:
            raise ValueError("bucket audio selection must require raw SHA-256 verification")
        raw_alternatives = value["alternatives"]
        if not isinstance(raw_alternatives, list) or not all(
            isinstance(item, Mapping) for item in raw_alternatives
        ):
            raise ValueError("bucket audio selection alternatives must be a list of mappings")
        if not isinstance(value["selected"], Mapping):
            raise ValueError("bucket audio selection selected must be a mapping")
        return cls(
            response_id=value["response_id"],
            legacy_text_hash=value["legacy_text_hash"],
            selected=BucketAudioDiscoveryObject.from_dict(value["selected"]),
            alternatives=tuple(
                BucketAudioDiscoveryObject.from_dict(item)
                for item in raw_alternatives
            ),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> BucketAudioSelection:
        return cls.from_dict(_json_mapping(value, label="bucket audio selection"))


@dataclass(frozen=True, slots=True)
class AbbyVoiceBucketAudioPlan:
    """Stable, content-addressed output of source aliasing and object selection."""

    aliases: tuple[SourceResponseAlias, ...]
    selections: tuple[BucketAudioSelection, ...]
    missing_response_ids: tuple[str, ...]
    unmapped_response_ids: tuple[str, ...]
    exclusions: tuple[SourceAliasExclusion, ...]
    accepted_response_count: int
    discovered_object_count: int
    ignored_object_count: int
    bucket_id: str
    listing_sha256: str
    allowed_run_ids: tuple[str, ...] = ()
    schema_version: str = ABBY_VOICE_BUCKET_AUDIO_PLAN_SCHEMA_VERSION
    planner_version: str = ABBY_VOICE_BUCKET_AUDIO_PLAN_VERSION
    plan_id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        aliases = tuple(sorted(self.aliases, key=lambda item: item.response_id))
        selections = tuple(sorted(self.selections, key=lambda item: item.response_id))
        missing = tuple(sorted(set(self.missing_response_ids)))
        unmapped = tuple(sorted(set(self.unmapped_response_ids)))
        exclusions = tuple(
            sorted(
                self.exclusions,
                key=lambda item: (
                    item.source_ref,
                    item.reason.value,
                    item.response_id or "",
                ),
            )
        )
        if any(not isinstance(item, SourceResponseAlias) for item in aliases):
            raise TypeError("aliases must contain SourceResponseAlias values")
        if any(not isinstance(item, BucketAudioSelection) for item in selections):
            raise TypeError("selections must contain BucketAudioSelection values")
        if any(not isinstance(item, SourceAliasExclusion) for item in exclusions):
            raise TypeError("exclusions must contain SourceAliasExclusion values")
        alias_ids = [item.response_id for item in aliases]
        selected_ids = [item.response_id for item in selections]
        if len(alias_ids) != len(set(alias_ids)):
            raise ValueError("alias response IDs must be unique")
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("selection response IDs must be unique")
        if set(selected_ids) & set(missing):
            raise ValueError("selected and missing response IDs must be disjoint")
        if set(alias_ids) != set(selected_ids) | set(missing):
            raise ValueError("every alias must have exactly one selected or missing disposition")
        alias_by_response = {item.response_id: item for item in aliases}
        for selection in selections:
            alias = alias_by_response[selection.response_id]
            if selection.legacy_text_hash != alias.legacy_text_hash:
                raise ValueError(
                    "selection legacy_text_hash does not match its response alias"
                )
        if set(alias_ids) & set(unmapped):
            raise ValueError("aliased and unmapped response IDs must be disjoint")
        if len(alias_ids) + len(unmapped) != self.accepted_response_count:
            raise ValueError("every accepted response must be aliased or unmapped")
        for count_name in (
            "accepted_response_count",
            "discovered_object_count",
            "ignored_object_count",
        ):
            count = getattr(self, count_name)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError(f"{count_name} must be a non-negative integer")
        if self.ignored_object_count > self.discovered_object_count:
            raise ValueError("ignored_object_count cannot exceed discovered_object_count")
        _required_text(self.bucket_id, label="bucket_id")
        if not _HASH64_RE.fullmatch(self.listing_sha256):
            raise ValueError("listing_sha256 must be a full lowercase SHA-256")
        allowed_runs = tuple(sorted(set(self.allowed_run_ids)))
        if len(allowed_runs) != len(self.allowed_run_ids) or any(
            not isinstance(item, str) or _RUN_ID_RE.fullmatch(item) is None
            for item in allowed_runs
        ):
            raise ValueError(
                "allowed_run_ids must contain unique canonical production run IDs"
            )
        if self.schema_version != ABBY_VOICE_BUCKET_AUDIO_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported bucket audio plan schema")
        if self.planner_version != ABBY_VOICE_BUCKET_AUDIO_PLAN_VERSION:
            raise ValueError("unsupported bucket audio planner version")
        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(self, "selections", selections)
        object.__setattr__(self, "missing_response_ids", missing)
        object.__setattr__(self, "unmapped_response_ids", unmapped)
        object.__setattr__(self, "exclusions", exclusions)
        object.__setattr__(self, "allowed_run_ids", allowed_runs)
        computed = (
            "abby-voice-bucket-audio-plan:sha256:"
            + sha256(_canonical_bytes(self._identity_dict())).hexdigest()
        )
        if self.plan_id and self.plan_id != computed:
            raise ValueError("plan_id does not match deterministic plan content")
        object.__setattr__(self, "plan_id", computed)

    @property
    def listing_id(self) -> str:
        return f"huggingface-bucket-listing:sha256:{self.listing_sha256}"

    def summary(self) -> dict[str, int | str | bool]:
        return {
            "accepted_response_count": self.accepted_response_count,
            "alias_count": len(self.aliases),
            "allowed_run_count": len(self.allowed_run_ids),
            "bucket_id": self.bucket_id,
            "discovered_object_count": self.discovered_object_count,
            "excluded_source_count": len(self.exclusions),
            "ignored_object_count": self.ignored_object_count,
            "listing_id": self.listing_id,
            "listing_sha256": self.listing_sha256,
            "missing_audio_count": len(self.missing_response_ids),
            "planner_version": self.planner_version,
            "raw_sha256_verification_required": True,
            "schema_version": self.schema_version,
            "selected_audio_count": len(self.selections),
            "unmapped_response_count": len(self.unmapped_response_ids),
        }

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "accepted_response_count": self.accepted_response_count,
            "aliases": [item.to_dict() for item in self.aliases],
            "bucket_id": self.bucket_id,
            "discovered_object_count": self.discovered_object_count,
            "exclusions": [item.to_dict() for item in self.exclusions],
            "ignored_object_count": self.ignored_object_count,
            "integrity_policy": {
                "raw_sha256_required_after_download": True,
                "xet_hash_is_raw_sha256": False,
            },
            "listing_id": self.listing_id,
            "listing_sha256": self.listing_sha256,
            "missing_response_ids": list(self.missing_response_ids),
            "planner_version": self.planner_version,
            "schema_version": self.schema_version,
            "selection_policy": {
                "allowed_run_ids": list(self.allowed_run_ids),
                "unlisted_runs_are_eligible": not bool(self.allowed_run_ids),
            },
            "selections": [item.to_dict() for item in self.selections],
            "unmapped_response_ids": list(self.unmapped_response_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._identity_dict(),
            "plan_id": self.plan_id,
            "summary": self.summary(),
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AbbyVoiceBucketAudioPlan:
        value = _strict_mapping(
            value,
            expected=frozenset(
                {
                    "accepted_response_count",
                    "aliases",
                    "bucket_id",
                    "discovered_object_count",
                    "exclusions",
                    "ignored_object_count",
                    "integrity_policy",
                    "listing_id",
                    "listing_sha256",
                    "missing_response_ids",
                    "plan_id",
                    "planner_version",
                    "schema_version",
                    "selection_policy",
                    "selections",
                    "summary",
                    "unmapped_response_ids",
                }
            ),
            label="Abby voice bucket audio plan",
        )
        sequence_fields = (
            "aliases",
            "exclusions",
            "missing_response_ids",
            "selections",
            "unmapped_response_ids",
        )
        if any(not isinstance(value[name], list) for name in sequence_fields):
            raise ValueError("bucket audio plan row collections must be JSON arrays")
        integrity_policy = value["integrity_policy"]
        if integrity_policy != {
            "raw_sha256_required_after_download": True,
            "xet_hash_is_raw_sha256": False,
        }:
            raise ValueError("bucket audio plan integrity policy is unsupported")
        selection_policy = value["selection_policy"]
        unlisted_runs_are_eligible = (
            selection_policy.get("unlisted_runs_are_eligible")
            if isinstance(selection_policy, Mapping)
            else None
        )
        if (
            not isinstance(selection_policy, Mapping)
            or set(selection_policy)
            != {"allowed_run_ids", "unlisted_runs_are_eligible"}
            or not isinstance(selection_policy["allowed_run_ids"], list)
            or not isinstance(unlisted_runs_are_eligible, bool)
            or unlisted_runs_are_eligible
            != (not bool(selection_policy["allowed_run_ids"]))
        ):
            raise ValueError("bucket audio plan selection policy is unsupported")
        if not all(isinstance(item, Mapping) for item in value["aliases"]):
            raise ValueError("bucket audio plan aliases must contain mappings")
        if not all(isinstance(item, Mapping) for item in value["exclusions"]):
            raise ValueError("bucket audio plan exclusions must contain mappings")
        if not all(isinstance(item, Mapping) for item in value["selections"]):
            raise ValueError("bucket audio plan selections must contain mappings")
        result = cls(
            aliases=tuple(
                SourceResponseAlias.from_dict(item) for item in value["aliases"]
            ),
            selections=tuple(
                BucketAudioSelection.from_dict(item) for item in value["selections"]
            ),
            missing_response_ids=tuple(value["missing_response_ids"]),
            unmapped_response_ids=tuple(value["unmapped_response_ids"]),
            exclusions=tuple(
                SourceAliasExclusion.from_dict(item) for item in value["exclusions"]
            ),
            accepted_response_count=value["accepted_response_count"],
            discovered_object_count=value["discovered_object_count"],
            ignored_object_count=value["ignored_object_count"],
            bucket_id=value["bucket_id"],
            listing_sha256=value["listing_sha256"],
            allowed_run_ids=tuple(selection_policy["allowed_run_ids"]),
            schema_version=value["schema_version"],
            planner_version=value["planner_version"],
            plan_id=value["plan_id"],
        )
        if value["listing_id"] != result.listing_id:
            raise ValueError("listing_id does not match listing_sha256")
        if not isinstance(value["summary"], Mapping) or dict(value["summary"]) != result.summary():
            raise ValueError("bucket audio plan summary does not match plan content")
        if result.to_dict() != dict(value):
            raise ValueError("bucket audio plan is not in canonical round-trip form")
        return result

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> AbbyVoiceBucketAudioPlan:
        return cls.from_dict(
            _json_mapping(value, label="Abby voice bucket audio plan")
        )


def _quarantined_digests(
    values: Iterable[str | Mapping[str, Any] | object],
) -> frozenset[str]:
    result: set[str] = set()
    for value in values:
        digest = (
            value
            if isinstance(value, str)
            else _mapping_or_attribute(value, "source_sha256", "source_record_sha256")
        )
        if not isinstance(digest, str) or _HASH64_RE.fullmatch(digest) is None:
            raise ValueError("quarantined source values must provide a full source SHA-256")
        result.add(digest)
    return frozenset(result)


def _legacy_text_hash(text: Any) -> str:
    """Reproduce the historical filename hash from collapsed source text."""

    collapsed = _SPACE_RE.sub(" ", str(text or "")).strip()
    return sha256(collapsed.encode("utf-8")).hexdigest()[:20]


def _normalize_discovered_objects(
    values: Iterable[Mapping[str, Any] | object],
) -> tuple[BucketAudioDiscoveryObject, ...]:
    by_path: dict[str, BucketAudioDiscoveryObject] = {}
    for value in values:
        item = BucketAudioDiscoveryObject.from_discovered(value)
        previous = by_path.get(item.path)
        if previous is not None and previous != item:
            raise ValueError(f"conflicting bucket discovery metadata for path {item.path!r}")
        by_path[item.path] = item
    return tuple(sorted(by_path.values(), key=lambda item: item.path))


def plan_abby_voice_bucket_audio(
    *,
    source_manifest: Mapping[str, Any] | Sequence[Any],
    accepted_responses: Iterable[AbbyVoiceResponse],
    discovered_objects: Iterable[Mapping[str, Any] | object],
    quarantined_sources: Iterable[str | Mapping[str, Any] | object] = (),
    source_uri: str = "memory://abby-voice-source-manifest",
    default_locale: str = "en-US",
    bucket_id: str = "memory://abby-voice-bucket",
    listing_sha256: str | None = None,
    allowed_run_ids: Iterable[str] = (),
) -> AbbyVoiceBucketAudioPlan:
    """Build an exact, deterministic download plan for legacy Abby audio.

    ``accepted_responses`` is the authoritative allowlist.  A source row must
    reproduce an accepted response ID with :func:`stable_response_id`, carry a
    valid legacy ``textHash``, and not appear in ``quarantined_sources``.
    Remote objects are eligible only when their basename is exactly
    ``abby-tts-{textHash}.mp3`` or ``abby-tts-{textHash}.wav`` (normalized
    inventory class ``response_linkable``).  When ``allowed_run_ids`` is
    non-empty, an object must also belong to one of those canonical production
    runs.  The selected object remains untrusted until a later download
    computes and validates the raw audio SHA-256.

    Non-linkable bucket objects (speaker prompts, smoke tests, zips, empty
    stubs, other run debris) are intentionally ignored here; callers should
    also emit :func:`build_bucket_audio_inventory` so those paths remain
    auditable under the inventory schema.
    """

    source_uri = _required_text(source_uri, label="source_uri")
    default_locale = _required_text(default_locale, label="default_locale")
    bucket_id = _required_text(bucket_id, label="bucket_id")
    if listing_sha256 is not None and _HASH64_RE.fullmatch(listing_sha256) is None:
        raise ValueError("listing_sha256 must be a full lowercase SHA-256")
    allowed_runs = tuple(sorted(set(allowed_run_ids)))
    if any(
        not isinstance(item, str) or _RUN_ID_RE.fullmatch(item) is None
        for item in allowed_runs
    ):
        raise ValueError(
            "allowed_run_ids must contain canonical production run IDs"
        )
    accepted_by_id: dict[str, AbbyVoiceResponse] = {}
    for response in accepted_responses:
        if not isinstance(response, AbbyVoiceResponse):
            raise TypeError("accepted_responses must contain AbbyVoiceResponse values")
        expected_id = stable_response_id(
            response.text,
            response.spoken_text,
            response.locale,
            response.intent,
        )
        if response.response_id != expected_id:
            raise ValueError(
                f"accepted response {response.response_id!r} is not a stable canonical response ID"
            )
        previous = accepted_by_id.get(response.response_id)
        if previous is not None and previous != response:
            raise ValueError(f"conflicting accepted response {response.response_id!r}")
        accepted_by_id[response.response_id] = response

    quarantined = _quarantined_digests(quarantined_sources)
    source_candidates: dict[str, list[SourceResponseAlias]] = defaultdict(list)
    exclusions: list[SourceAliasExclusion] = []
    for record in _ordered_source_rows(source_manifest):
        digest = record_sha256(record)
        source_ref = _source_ref(source_uri, digest)
        raw_hash = record.get("textHash")
        legacy_hash = raw_hash if isinstance(raw_hash, str) and _HASH20_RE.fullmatch(raw_hash) else None
        response_id: str | None = None
        try:
            display_text, spoken_text, locale, intent = _source_response_identity(
                record, default_locale=default_locale
            )
            response_id = stable_response_id(
                display_text, spoken_text, locale, intent
            )
        except (TypeError, ValueError):
            exclusions.append(
                SourceAliasExclusion(
                    source_ref=source_ref,
                    source_record_sha256=digest,
                    reason=SourceAliasExclusionReason.INVALID_SOURCE_ROW,
                    legacy_text_hash=legacy_hash,
                )
            )
            continue
        if digest in quarantined:
            exclusions.append(
                SourceAliasExclusion(
                    source_ref=source_ref,
                    source_record_sha256=digest,
                    reason=SourceAliasExclusionReason.QUARANTINED_SOURCE,
                    response_id=response_id,
                    legacy_text_hash=legacy_hash,
                )
            )
            continue
        response = accepted_by_id.get(response_id)
        if response is None:
            exclusions.append(
                SourceAliasExclusion(
                    source_ref=source_ref,
                    source_record_sha256=digest,
                    reason=SourceAliasExclusionReason.UNACCEPTED_RESPONSE,
                    response_id=response_id,
                    legacy_text_hash=legacy_hash,
                )
            )
            continue
        if legacy_hash is None:
            exclusions.append(
                SourceAliasExclusion(
                    source_ref=source_ref,
                    source_record_sha256=digest,
                    reason=SourceAliasExclusionReason.MISSING_LEGACY_TEXT_HASH,
                    response_id=response_id,
                )
            )
            continue
        if legacy_hash != _legacy_text_hash(record.get("text")):
            exclusions.append(
                SourceAliasExclusion(
                    source_ref=source_ref,
                    source_record_sha256=digest,
                    reason=SourceAliasExclusionReason.LEGACY_TEXT_HASH_MISMATCH,
                    response_id=response_id,
                    legacy_text_hash=legacy_hash,
                )
            )
            continue
        source_id = str(record.get("id") or f"abby-tts-{legacy_hash}").strip()
        if not source_id:
            source_id = f"abby-tts-{legacy_hash}"
        source_candidates[response_id].append(
            SourceResponseAlias(
                response_id=response_id,
                canonical_text_sha256=response.content_sha256 or "",
                legacy_text_hash=legacy_hash,
                source_id=source_id,
                source_ref=source_ref,
                source_record_sha256=digest,
                source_record_json=_canonical_bytes(record).decode("utf-8"),
            )
        )

    aliases: list[SourceResponseAlias] = []
    ambiguous_ids: set[str] = set()
    for response_id, candidates in sorted(source_candidates.items()):
        ordered = sorted(
            candidates,
            key=lambda item: (
                item.source_record_sha256,
                item.legacy_text_hash,
                item.source_id,
            ),
        )
        if len(ordered) == 1:
            aliases.append(ordered[0])
            continue
        ambiguous_ids.add(response_id)
        for item in ordered:
            exclusions.append(
                SourceAliasExclusion(
                    source_ref=item.source_ref,
                    source_record_sha256=item.source_record_sha256,
                    reason=SourceAliasExclusionReason.AMBIGUOUS_SOURCE_ALIAS,
                    response_id=item.response_id,
                    legacy_text_hash=item.legacy_text_hash,
                )
            )

    discovered = _normalize_discovered_objects(discovered_objects)
    if listing_sha256 is None:
        listing_sha256 = sha256(
            _canonical_bytes(
                {
                    "bucket_id": bucket_id,
                    "objects": [item.to_dict() for item in discovered],
                }
            )
        ).hexdigest()
    exact_linkable_objects = tuple(
        item
        for item in discovered
        if (
            item.legacy_text_hash is not None
            and (
                not allowed_runs
                or (
                    (run_match := _PRODUCTION_RUN_RE.search(item.path))
                    is not None
                    and run_match.group("run_id") in allowed_runs
                )
            )
        )
    )
    objects_by_hash: dict[str, list[BucketAudioDiscoveryObject]] = defaultdict(list)
    for item in exact_linkable_objects:
        assert item.legacy_text_hash is not None
        objects_by_hash[item.legacy_text_hash].append(item)

    selections: list[BucketAudioSelection] = []
    missing: list[str] = []
    for alias in aliases:
        objects = sorted(objects_by_hash.get(alias.legacy_text_hash, ()), key=_object_preference)
        if not objects:
            missing.append(alias.response_id)
            continue
        selections.append(
            BucketAudioSelection(
                response_id=alias.response_id,
                legacy_text_hash=alias.legacy_text_hash,
                selected=objects[0],
                alternatives=tuple(objects[1:]),
            )
        )

    aliased_ids = {item.response_id for item in aliases}
    unmapped = tuple(sorted(set(accepted_by_id) - aliased_ids))
    if ambiguous_ids - set(unmapped):
        raise AssertionError("ambiguous source aliases must remain unmapped")
    return AbbyVoiceBucketAudioPlan(
        aliases=tuple(aliases),
        selections=tuple(selections),
        missing_response_ids=tuple(missing),
        unmapped_response_ids=unmapped,
        exclusions=tuple(exclusions),
        accepted_response_count=len(accepted_by_id),
        discovered_object_count=len(discovered),
        ignored_object_count=len(discovered) - len(exact_linkable_objects),
        bucket_id=bucket_id,
        listing_sha256=listing_sha256,
        allowed_run_ids=allowed_runs,
    )


__all__ = [
    "ABBY_VOICE_BUCKET_AUDIO_PLAN_SCHEMA_VERSION",
    "ABBY_VOICE_BUCKET_AUDIO_PLAN_VERSION",
    "AbbyVoiceBucketAudioPlan",
    "BucketAudioDiscoveryObject",
    "BucketAudioSelection",
    "SourceAliasExclusion",
    "SourceAliasExclusionReason",
    "SourceResponseAlias",
    "plan_abby_voice_bucket_audio",
]
