"""Rescue unmapped bucket audio via source-hash joins and ASR matching.

Most ``unmapped_linkable`` objects under Publicus/abby-voice are phase1 BM25
vocabulary terms whose ``abby-tts-{textHash}`` basenames are absent from the
accepted response manifest.  This module:

1. Deterministically remaps those hashes to BM25/vocabulary (and optionally
   quarantined response) source catalogs.
2. Matches ASR transcripts against response spoken text and vocabulary terms
   for the residual set that has no hash join.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from .audio_quality import word_error_rate_bp
from .bucket_audio_normalize import (
    AbbyVoiceBucketAudioNormalizedBundle,
    BucketAudioMappingMethod,
    BucketAudioMappingStatus,
    BucketAudioSubjectKind,
    NormalizedBucketAudioEntry,
)
from .normalize import normalize_indextts_spoken_text, normalized_text_identity
from .schema import sha256_text

DEFAULT_ASR_WER_BP = 2_500  # 25%


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _legacy_text_hash(text: str) -> str:
    collapsed = " ".join(str(text or "").split())
    return sha256(collapsed.encode("utf-8")).hexdigest()[:20]


def _rows_from_manifest(payload: Mapping[str, Any] | Sequence[Any]) -> tuple[Mapping[str, Any], ...]:
    if isinstance(payload, Mapping):
        for key in ("responses", "items", "entries", "records", "vocabulary"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                rows = value
                break
        else:
            rows = (payload,)
    else:
        rows = payload
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("catalog must contain a row sequence")
    if not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("catalog rows must be mappings")
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class TextHashCatalogEntry:
    """One source row keyed by legacy 20-hex text hash."""

    legacy_text_hash: str
    text: str
    source_id: str
    source_ref: str
    subject_kind: BucketAudioSubjectKind
    subject_id: str
    catalog_name: str

    def __post_init__(self) -> None:
        if len(self.legacy_text_hash) != 20:
            raise ValueError("legacy_text_hash must be 20 hex characters")
        object.__setattr__(self, "subject_kind", BucketAudioSubjectKind(self.subject_kind))


def load_text_hash_catalog(
    path: str | Path,
    *,
    catalog_name: str,
    subject_kind: BucketAudioSubjectKind,
    source_uri_prefix: str | None = None,
) -> dict[str, TextHashCatalogEntry]:
    """Load a BM25/vocabulary/response manifest into a textHash index."""

    raw_path = Path(path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    rows = _rows_from_manifest(payload)
    prefix = source_uri_prefix or f"repo://{raw_path.as_posix()}"
    by_hash: dict[str, TextHashCatalogEntry] = {}
    for row in rows:
        text = str(row.get("text") or row.get("spoken_text") or "").strip()
        if not text:
            continue
        raw_hash = row.get("textHash") or row.get("text_hash")
        if isinstance(raw_hash, str) and len(raw_hash) == 20:
            legacy = raw_hash.casefold()
        else:
            legacy = _legacy_text_hash(text)
        source_id = str(row.get("id") or f"abby-tts-{legacy}").strip() or f"abby-tts-{legacy}"
        if subject_kind is BucketAudioSubjectKind.RESPONSE:
            subject_id = str(row.get("response_id") or source_id)
        else:
            subject_id = source_id
        digest = sha256(_canonical_bytes(dict(row))).hexdigest()
        entry = TextHashCatalogEntry(
            legacy_text_hash=legacy,
            text=text,
            source_id=source_id,
            source_ref=f"{prefix}#row-sha256={digest}",
            subject_kind=subject_kind,
            subject_id=subject_id,
            catalog_name=catalog_name,
        )
        previous = by_hash.get(legacy)
        if previous is not None and previous.text != entry.text:
            # Prefer longer / first stable text; skip conflicting hashes.
            continue
        by_hash[legacy] = entry
    return by_hash


def rescue_unmapped_by_text_hash(
    bundle: AbbyVoiceBucketAudioNormalizedBundle,
    catalogs: Sequence[tuple[dict[str, TextHashCatalogEntry], BucketAudioMappingStatus, BucketAudioMappingMethod]],
) -> tuple[AbbyVoiceBucketAudioNormalizedBundle, dict[str, int]]:
    """Remap ``unmapped_linkable`` entries using ordered textHash catalogs.

    Catalogs are tried in order; the first hit wins. Already-mapped entries are
    left unchanged.
    """

    if not isinstance(bundle, AbbyVoiceBucketAudioNormalizedBundle):
        raise TypeError("bundle must be an AbbyVoiceBucketAudioNormalizedBundle")
    updated: list[NormalizedBucketAudioEntry] = []
    stats = {
        "considered": 0,
        "rescued": 0,
        "still_unmapped": 0,
    }
    for entry in bundle.entries:
        if entry.mapping_status is not BucketAudioMappingStatus.UNMAPPED_LINKABLE:
            updated.append(entry)
            continue
        stats["considered"] += 1
        legacy = entry.legacy_text_hash
        hit: TextHashCatalogEntry | None = None
        status = BucketAudioMappingStatus.UNMAPPED_LINKABLE
        method = BucketAudioMappingMethod.NONE
        if legacy is not None:
            for catalog, map_status, map_method in catalogs:
                candidate = catalog.get(legacy)
                if candidate is not None:
                    hit = candidate
                    status = map_status
                    method = map_method
                    break
        if hit is None:
            stats["still_unmapped"] += 1
            updated.append(entry)
            continue
        stats["rescued"] += 1
        spoken = normalize_indextts_spoken_text(hit.text)
        updated.append(
            replace(
                entry,
                mapping_status=status,
                mapping_method=method,
                subject_kind=hit.subject_kind,
                subject_id=hit.subject_id,
                response_id=(
                    hit.subject_id
                    if hit.subject_kind is BucketAudioSubjectKind.RESPONSE
                    else entry.response_id
                ),
                source_id=hit.source_id,
                source_ref=hit.source_ref,
                source_text=hit.text,
                canonical_text_sha256=sha256_text(spoken) if spoken else None,
            )
        )
    return (
        AbbyVoiceBucketAudioNormalizedBundle(
            entries=tuple(updated),
            bucket_id=bundle.bucket_id,
            listing_sha256=bundle.listing_sha256,
            plan_id=bundle.plan_id,
            inventory_id=bundle.inventory_id,
        ),
        stats,
    )


@dataclass(frozen=True, slots=True)
class AsrRescueCandidate:
    """One ASR observation to match against catalogs."""

    path: str
    transcript: str
    entry_id: str | None = None


def _best_asr_match(
    transcript: str,
    *,
    response_texts: Mapping[str, tuple[str, str]],
    vocabulary_texts: Mapping[str, tuple[str, str]],
    max_wer_bp: int,
) -> tuple[
    BucketAudioMappingStatus,
    BucketAudioMappingMethod,
    BucketAudioSubjectKind,
    str,
    str,
    str,
    int | None,
] | None:
    """Return mapping fields for the best ASR match, if any.

    ``response_texts`` / ``vocabulary_texts`` map subject_id -> (display_text, spoken_or_normalized).
    """

    hyp = normalized_text_identity(normalize_indextts_spoken_text(transcript))
    if not hyp:
        return None

    # Exact normalized identity against vocabulary first (short phrases).
    for subject_id, (display, spoken) in vocabulary_texts.items():
        ref = normalized_text_identity(spoken)
        if ref and ref == hyp:
            return (
                BucketAudioMappingStatus.ASR_RESCUED_VOCABULARY,
                BucketAudioMappingMethod.ASR_EXACT_NORMALIZED,
                BucketAudioSubjectKind.VOCABULARY,
                subject_id,
                subject_id,
                display,
                0,
            )

    for subject_id, (display, spoken) in response_texts.items():
        ref = normalized_text_identity(spoken)
        if ref and ref == hyp:
            return (
                BucketAudioMappingStatus.ASR_RESCUED_RESPONSE,
                BucketAudioMappingMethod.ASR_EXACT_NORMALIZED,
                BucketAudioSubjectKind.RESPONSE,
                subject_id,
                subject_id,
                display,
                0,
            )

    # WER threshold match; prefer vocabulary then responses.
    best: tuple[int, str, str, str, BucketAudioSubjectKind, BucketAudioMappingStatus] | None = None
    for subject_id, (display, spoken) in vocabulary_texts.items():
        wer = word_error_rate_bp(spoken, transcript)
        if wer > max_wer_bp:
            continue
        if best is None or wer < best[0]:
            best = (
                wer,
                subject_id,
                subject_id,
                display,
                BucketAudioSubjectKind.VOCABULARY,
                BucketAudioMappingStatus.ASR_RESCUED_VOCABULARY,
            )
    for subject_id, (display, spoken) in response_texts.items():
        wer = word_error_rate_bp(spoken, transcript)
        if wer > max_wer_bp:
            continue
        if best is None or wer < best[0]:
            best = (
                wer,
                subject_id,
                subject_id,
                display,
                BucketAudioSubjectKind.RESPONSE,
                BucketAudioMappingStatus.ASR_RESCUED_RESPONSE,
            )
    if best is None:
        return None
    wer_bp, subject_id, source_id, display, kind, status = best
    return (
        status,
        BucketAudioMappingMethod.ASR_WER_THRESHOLD,
        kind,
        subject_id,
        source_id,
        display,
        wer_bp,
    )


def rescue_unmapped_by_asr(
    bundle: AbbyVoiceBucketAudioNormalizedBundle,
    candidates: Sequence[AsrRescueCandidate],
    *,
    response_texts: Mapping[str, tuple[str, str]],
    vocabulary_texts: Mapping[str, tuple[str, str]],
    max_wer_bp: int = DEFAULT_ASR_WER_BP,
) -> tuple[AbbyVoiceBucketAudioNormalizedBundle, dict[str, int]]:
    """Apply ASR transcripts to still-unmapped linkable entries.

    Matches are computed on candidate paths, then propagated to every
    still-unmapped entry that shares the same ``legacy_text_hash``.
    """

    by_path = {item.path: item for item in candidates}
    entry_by_path = {item.path: item for item in bundle.entries}
    # path -> match fields or None for explicit unmatch
    path_match: dict[str, tuple | None] = {}
    stats = {
        "considered": 0,
        "matched": 0,
        "unmatched": 0,
        "propagated": 0,
        "skipped_not_unmapped": 0,
    }
    for candidate in candidates:
        entry = entry_by_path.get(candidate.path)
        if entry is None:
            continue
        if entry.mapping_status not in {
            BucketAudioMappingStatus.UNMAPPED_LINKABLE,
            BucketAudioMappingStatus.ASR_UNMATCHED,
        }:
            stats["skipped_not_unmapped"] += 1
            continue
        stats["considered"] += 1
        match = _best_asr_match(
            candidate.transcript,
            response_texts=response_texts,
            vocabulary_texts=vocabulary_texts,
            max_wer_bp=max_wer_bp,
        )
        path_match[candidate.path] = match
        if match is None:
            stats["unmatched"] += 1
        else:
            stats["matched"] += 1

    # Propagate successful matches by legacy text hash.
    hash_match: dict[str, tuple] = {}
    for path, match in path_match.items():
        if match is None:
            continue
        entry = entry_by_path[path]
        if entry.legacy_text_hash:
            hash_match[entry.legacy_text_hash] = match

    updated: list[NormalizedBucketAudioEntry] = []
    for entry in bundle.entries:
        if entry.mapping_status not in {
            BucketAudioMappingStatus.UNMAPPED_LINKABLE,
            BucketAudioMappingStatus.ASR_UNMATCHED,
        }:
            updated.append(entry)
            continue
        match = path_match.get(entry.path)
        if match is None and entry.legacy_text_hash in hash_match:
            match = hash_match[entry.legacy_text_hash]
            if entry.path not in path_match:
                stats["propagated"] += 1
        if entry.path in path_match and path_match[entry.path] is None and match is None:
            updated.append(
                replace(
                    entry,
                    mapping_status=BucketAudioMappingStatus.ASR_UNMATCHED,
                    mapping_method=BucketAudioMappingMethod.NONE,
                    source_text=None,
                )
            )
            continue
        if match is None:
            updated.append(entry)
            continue
        status, method, kind, subject_id, source_id, display, wer_bp = match
        spoken = normalize_indextts_spoken_text(display)
        updated.append(
            replace(
                entry,
                mapping_status=status,
                mapping_method=method,
                subject_kind=kind,
                subject_id=subject_id,
                response_id=(
                    subject_id if kind is BucketAudioSubjectKind.RESPONSE else entry.response_id
                ),
                source_id=source_id,
                source_text=display,
                canonical_text_sha256=sha256_text(spoken) if spoken else None,
                asr_wer_bp=wer_bp,
            )
        )
    return (
        AbbyVoiceBucketAudioNormalizedBundle(
            entries=tuple(updated),
            bucket_id=bundle.bucket_id,
            listing_sha256=bundle.listing_sha256,
            plan_id=bundle.plan_id,
            inventory_id=bundle.inventory_id,
        ),
        stats,
    )


def preferred_unmapped_for_asr(
    bundle: AbbyVoiceBucketAudioNormalizedBundle,
    *,
    limit: int | None = None,
) -> tuple[NormalizedBucketAudioEntry, ...]:
    """Pick one preferred path per unmapped legacy hash for ASR rescue."""

    by_hash: dict[str, list[NormalizedBucketAudioEntry]] = {}
    for entry in bundle.entries:
        if entry.mapping_status is not BucketAudioMappingStatus.UNMAPPED_LINKABLE:
            continue
        if not entry.legacy_text_hash:
            continue
        by_hash.setdefault(entry.legacy_text_hash, []).append(entry)

    def rank(item: NormalizedBucketAudioEntry) -> tuple[int, int, str]:
        phase_rank = 0 if item.phase and item.phase.startswith("phase4") else 1
        media_rank = 0 if item.media_extension == "mp3" else 1
        return phase_rank, media_rank, item.path

    chosen = [sorted(group, key=rank)[0] for group in by_hash.values()]
    chosen.sort(key=lambda item: item.path)
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        chosen = chosen[:limit]
    return tuple(chosen)


__all__ = [
    "AsrRescueCandidate",
    "DEFAULT_ASR_WER_BP",
    "TextHashCatalogEntry",
    "load_text_hash_catalog",
    "preferred_unmapped_for_asr",
    "rescue_unmapped_by_asr",
    "rescue_unmapped_by_text_hash",
]
