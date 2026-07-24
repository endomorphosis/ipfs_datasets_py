"""Deterministic normalization and quality gates for Abby voice datasets.

The normalizer deliberately has no dependency on the monorepo's runtime
scripts, Hugging Face, NumPy, or PyArrow.  It accepts the legacy response
manifests produced by the IndexTTS pipeline and emits the canonical, flat v2
rows from :mod:`ipfs_datasets_py.voice.schema`.

Normalization is non-destructive: input mappings are never changed and every
rejected source row is retained in a quarantine record with a stable source
reference, source digest, and machine-readable reason codes.  No wall-clock
time, input array position, random number, or Python ``hash()`` value affects
the output.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from string import Formatter
from typing import Any
from urllib.parse import quote

from .schema import (
    ABBY_VOICE_AUDIO_V2,
    ABBY_VOICE_PROVENANCE_V2,
    ABBY_VOICE_RESPONSE_V2,
    ABBY_VOICE_TEMPLATE_V2,
    SCHEMA_VERSIONS,
    AbbyVoiceAudio,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    AbbyVoiceSchemaError,
    AbbyVoiceTemplate,
    VoiceRow,
    parse_abby_voice_record,
    sha256_text,
    stable_audio_id,
    stable_provenance_id,
    stable_response_id,
    stable_template_id,
    validate_bundle,
)

NORMALIZATION_VERSION = "2.0.0"
QUALITY_REPORT_VERSION = "abby_voice_quality_v2"


class QuarantineReason(StrEnum):
    """Stable reason codes used in quarantine and quality reports."""

    INVALID_RECORD = "invalid_record"
    EMPTY_TEXT = "empty_text"
    LOW_VALUE_FRAGMENT = "low_value_fragment"
    MALFORMED_SPOKEN_TEXT = "malformed_spoken_text"
    DUPLICATE_TEXT = "duplicate_text"
    DUPLICATE_AUDIO = "duplicate_audio"
    UNGROUNDED_CLAIM = "ungrounded_claim"
    MISSING_AUDIO = "missing_audio"
    INCONSISTENT_SLOTS = "inconsistent_slots"
    AUDIO_HASH_MISMATCH = "audio_hash_mismatch"
    UNSUPPORTED_WRAPPER = "unsupported_wrapper"


# Conventional module-level constants are useful to JSON-oriented callers.
INVALID_RECORD = QuarantineReason.INVALID_RECORD.value
EMPTY_TEXT = QuarantineReason.EMPTY_TEXT.value
LOW_VALUE_FRAGMENT = QuarantineReason.LOW_VALUE_FRAGMENT.value
MALFORMED_SPOKEN_TEXT = QuarantineReason.MALFORMED_SPOKEN_TEXT.value
DUPLICATE_TEXT = QuarantineReason.DUPLICATE_TEXT.value
DUPLICATE_AUDIO = QuarantineReason.DUPLICATE_AUDIO.value
UNGROUNDED_CLAIM = QuarantineReason.UNGROUNDED_CLAIM.value
MISSING_AUDIO = QuarantineReason.MISSING_AUDIO.value
INCONSISTENT_SLOTS = QuarantineReason.INCONSISTENT_SLOTS.value
AUDIO_HASH_MISMATCH = QuarantineReason.AUDIO_HASH_MISMATCH.value

_SPACE_RE = re.compile(r"\s+")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:[^()]|\([^()]*\))+\)")
_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REPLACEMENT_RE = re.compile("\ufffd")
_EMPTY_QUOTE_RE = re.compile(r"[“\"]\s*[”\"]")
_RESIDUAL_MARKUP_RE = re.compile(r"(?:\*\*|__|```|<[^>]+>|\[[^\]]*\]\([^)]*\))")
_REPEATED_CHAR_RE = re.compile(r"([^\W\d_])\1{7,}", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"{([A-Za-z0-9._:/-]+)}")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]*)?\(?(?P<a>\d{3})\)?[\s.-]+"
    r"(?P<b>\d{3})[\s.-]+(?P<c>\d{4})(?!\d)"
)
_GROUNDING_CLAIM_RE = re.compile(
    r"(?i)(?:\b(?:eligib(?:le|ility)|hours?|address|located|open|closed|"
    r"costs?|\$\d|call|phone|appointment|available)\b|"
    r"(?<!\d)\d{3}[\s().-]+\d{3}[\s.-]+\d{4}(?!\d)|"
    r"\b\d{1,6}\s+[A-Za-z][A-Za-z .'-]+\s+"
    r"(?:st(?:reet)?|ave(?:nue)?|rd|road|blvd|boulevard|way|lane|drive)\b)"
)
_DIGITS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}
_LOW_VALUE_TERMS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "at",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "unknown",
        "n/a",
        "none",
        "null",
    }
)
_AUDIO_PATH_FIELDS = (
    "preferredAudioPath",
    "mp3Path",
    "audioPath",
    "preferred_audio_path",
)
_AUDIO_URI_FIELDS = (
    "preferredAudioUrl",
    "mp3Url",
    "audioUrl",
    "uri",
    "bucketMp3Uri",
    "bucketAudioUri",
)
_RECOGNIZED_WRAPPERS = (
    "responses",
    "templates",
    "audio",
    "audios",
    "audio_assets",
    "provenance",
    "records",
    "entries",
    "items",
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted(_json_safe(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def canonical_json(value: Any) -> str:
    """Serialize a JSON-safe value for stable hashing and byte comparisons."""

    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def record_sha256(value: Any) -> str:
    """Return the deterministic digest of one source JSON value."""

    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _strings(value: Any) -> tuple[str, ...]:
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


def _ordered_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = (value,) if isinstance(value, str) else value
    if not isinstance(values, Sequence) or isinstance(values, bytes | bytearray):
        return ()
    result: list[str] = []
    for item in values:
        normalized = _SPACE_RE.sub(" ", str(item)).strip()
        if normalized:
            result.append(normalized)
    return tuple(result)


def _first(record: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in record and record[name] not in (None, ""):
            return record[name]
    return None


def _digits_to_words(value: str) -> str:
    return " ".join(_DIGITS[char] for char in value if char in _DIGITS)


def normalize_indextts_spoken_text(text: str) -> str:
    """Normalize text into a deterministic, TTS-safe spoken representation.

    This is the dependency-light core of the stronger monorepo IndexTTS
    normalizer.  It handles the corpus defects that affect identity and quality
    gating: Unicode/whitespace drift, page markup, links, phone numbers, and
    the emergency/service short codes 911 and 211.
    """

    if not isinstance(text, str):
        text = "" if text is None else str(text)
    spoken = unicodedata.normalize("NFKC", html.unescape(text))
    spoken = _CONTROL_RE.sub(" ", spoken)
    spoken = _MARKDOWN_LINK_RE.sub(r"\1", spoken)
    spoken = re.sub(r"\*\*(.*?)\*\*", r"\1", spoken)
    spoken = re.sub(r"__(.*?)__", r"\1", spoken)
    spoken = re.sub(r"`([^`]*)`", r"\1", spoken)
    spoken = _HTML_TAG_RE.sub(" ", spoken)
    spoken = _URL_RE.sub(" ", spoken)

    def phone_words(match: re.Match[str]) -> str:
        return (
            f"{_digits_to_words(match.group('a'))}, "
            f"{_digits_to_words(match.group('b'))}, "
            f"{_digits_to_words(match.group('c'))}"
        )

    spoken = _PHONE_RE.sub(phone_words, spoken)
    spoken = re.sub(r"(?<!\d)9\s*[- ]\s*1\s*[- ]\s*1(?!\d)", "nine one one", spoken)
    spoken = re.sub(r"(?<!\d)2\s*[- ]\s*1\s*[- ]\s*1(?!\d)", "two one one", spoken)
    spoken = re.sub(r"(?<!\d)911(?!\d)", "nine one one", spoken)
    spoken = re.sub(r"(?<!\d)211(?!\d)", "two one one", spoken)
    spoken = re.sub(r"\s+([.,;:!?])", r"\1", spoken)
    spoken = re.sub(r"(?:\.\s*){2,}", ". ", spoken)
    return _SPACE_RE.sub(" ", spoken).strip(" \t\r\n;,")


normalize_spoken_text = normalize_indextts_spoken_text


def normalized_text_identity(text: str) -> str:
    """Return the order-independent equality key used for text de-duplication."""

    return _SPACE_RE.sub(
        " ", unicodedata.normalize("NFKC", str(text or ""))
    ).strip().casefold()


def deterministic_split(
    key: str,
    *,
    train: int = 8000,
    validation: int = 1000,
    test: int = 1000,
    salt: str = "abby-voice-v2",
) -> str:
    """Assign a stable split using integer SHA-256 buckets.

    Ratios are integer weights and need not sum to 10,000.  Using a content
    family key (preferably a template ID) keeps related rows in one split.
    """

    weights = (train, validation, test)
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in weights):
        raise ValueError("split weights must be non-negative integers")
    total = sum(weights)
    if total <= 0:
        raise ValueError("at least one split weight must be positive")
    bucket = int.from_bytes(
        sha256(f"{salt}\0{key}".encode()).digest()[:8], "big"
    ) % total
    if bucket < train:
        return "train"
    if bucket < train + validation:
        return "validation"
    return "test"


@dataclass(frozen=True, slots=True)
class NormalizationConfig:
    """Policy knobs for deterministic quality gates."""

    locale: str = "en-US"
    license_id: str = "NOASSERTION"
    consent_status: str = "unknown"
    require_audio: bool = False
    require_grounding_for_claims: bool = True
    quarantine_duplicates: bool = True
    reject_bm25_only_vocabulary: bool = True
    minimum_alphanumeric_characters: int = 2
    maximum_spoken_characters: int = 5000
    split_train: int = 8000
    split_validation: int = 1000
    split_test: int = 1000
    split_salt: str = "abby-voice-v2"

    def __post_init__(self) -> None:
        if self.minimum_alphanumeric_characters < 1:
            raise ValueError("minimum_alphanumeric_characters must be positive")
        if self.maximum_spoken_characters < self.minimum_alphanumeric_characters:
            raise ValueError("maximum_spoken_characters is smaller than the minimum")
        deterministic_split(
            "config-validation",
            train=self.split_train,
            validation=self.split_validation,
            test=self.split_test,
            salt=self.split_salt,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "locale": self.locale,
            "license_id": self.license_id,
            "consent_status": self.consent_status,
            "require_audio": self.require_audio,
            "require_grounding_for_claims": self.require_grounding_for_claims,
            "quarantine_duplicates": self.quarantine_duplicates,
            "reject_bm25_only_vocabulary": self.reject_bm25_only_vocabulary,
            "minimum_alphanumeric_characters": self.minimum_alphanumeric_characters,
            "maximum_spoken_characters": self.maximum_spoken_characters,
            "split": {
                "train": self.split_train,
                "validation": self.split_validation,
                "test": self.split_test,
                "salt": self.split_salt,
            },
        }


@dataclass(frozen=True, slots=True)
class QualityIssue:
    """One stable reason and human-readable diagnostic."""

    code: QuarantineReason
    message: str
    field: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.field is not None:
            result["field"] = self.field
        return result


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """Lossless record of one source value rejected by a quality gate."""

    source_ref: str
    source_sha256: str
    source_record: Any
    issues: tuple[QualityIssue, ...]
    candidate_id: str | None = None

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(sorted({issue.code.value for issue in self.issues}))

    def to_dict(self) -> dict[str, Any]:
        result = {
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
            "reason_codes": list(self.reason_codes),
            "issues": [
                issue.to_dict()
                for issue in sorted(
                    self.issues, key=lambda item: (item.code.value, item.field or "", item.message)
                )
            ],
            "source_record": _json_safe(self.source_record),
        }
        if self.candidate_id:
            result["candidate_id"] = self.candidate_id
        return result


@dataclass(frozen=True, slots=True)
class DuplicateLedgerEntry:
    """Deterministic winner/duplicate relationship for one identity group."""

    kind: str
    identity_sha256: str
    survivor_id: str
    survivor_source_ref: str
    duplicate_source_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "identity_sha256": self.identity_sha256,
            "survivor_id": self.survivor_id,
            "survivor_source_ref": self.survivor_source_ref,
            "duplicate_source_refs": list(self.duplicate_source_refs),
        }


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Canonical rows and complete deterministic quality evidence."""

    responses: tuple[AbbyVoiceResponse, ...] = ()
    templates: tuple[AbbyVoiceTemplate, ...] = ()
    audio: tuple[AbbyVoiceAudio, ...] = ()
    provenance: tuple[AbbyVoiceProvenance, ...] = ()
    quarantine: tuple[QuarantineRecord, ...] = ()
    duplicates: tuple[DuplicateLedgerEntry, ...] = ()
    warnings: tuple[QuarantineRecord, ...] = ()
    splits: Mapping[str, str] = field(default_factory=dict)
    input_record_count: int = 0
    source_manifest_count: int = 0
    config: NormalizationConfig = field(default_factory=NormalizationConfig)

    def quality_summary(self) -> dict[str, Any]:
        reasons = Counter(
            code
            for item in (*self.quarantine, *self.warnings)
            for code in item.reason_codes
        )
        accepted = {
            "responses": len(self.responses),
            "templates": len(self.templates),
            "audio": len(self.audio),
            "provenance": len(self.provenance),
        }
        quarantined_sources = len(self.quarantine)
        return {
            "schema_version": QUALITY_REPORT_VERSION,
            "normalization_version": NORMALIZATION_VERSION,
            "policy": self.config.to_dict(),
            "source_manifest_count": self.source_manifest_count,
            "input_record_count": self.input_record_count,
            "accepted_record_count": sum(accepted.values()),
            "accepted": accepted,
            "quarantined_source_count": quarantined_sources,
            "warning_source_count": len(self.warnings),
            "reason_counts": dict(sorted(reasons.items())),
            "deduplication": {
                "text_groups": sum(item.kind == "text" for item in self.duplicates),
                "text_duplicates_removed": sum(
                    len(item.duplicate_source_refs)
                    for item in self.duplicates
                    if item.kind == "text"
                ),
                "audio_groups": sum(item.kind == "audio" for item in self.duplicates),
                "audio_duplicates_removed": sum(
                    len(item.duplicate_source_refs)
                    for item in self.duplicates
                    if item.kind == "audio"
                ),
            },
            "split_counts": dict(sorted(Counter(self.splits.values()).items())),
            "reconciliation": {
                "source_rows_accounted_for": (
                    len(self.responses)
                    + len(self.templates)
                    + len(self.audio)
                    + quarantined_sources
                ),
                "quarantine_is_non_destructive": True,
            },
        }

    summary = quality_summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "responses": [row.to_dict() for row in self.responses],
            "templates": [row.to_dict() for row in self.templates],
            "audio": [row.to_dict() for row in self.audio],
            "provenance": [row.to_dict() for row in self.provenance],
            "quarantine": [row.to_dict() for row in self.quarantine],
            "warnings": [row.to_dict() for row in self.warnings],
            "duplicates": [row.to_dict() for row in self.duplicates],
            "splits": dict(sorted(self.splits.items())),
            "quality_summary": self.quality_summary(),
        }


@dataclass(frozen=True, slots=True)
class _Source:
    payload: Any
    source_uri: str
    source_sha256: str
    audio_root: Path | None


@dataclass(frozen=True, slots=True)
class _Candidate:
    row: VoiceRow
    raw: Mapping[str, Any]
    source_ref: str
    source_sha256: str
    source_uri: str
    grounding_refs: tuple[str, ...] = ()
    issues: tuple[QualityIssue, ...] = ()
    audio: AbbyVoiceAudio | None = None
    audio_issues: tuple[QualityIssue, ...] = ()

    @property
    def rank(self) -> tuple[int, int, str, str]:
        return (
            0 if self.audio is not None and not self.audio_issues else 1,
            0 if self.grounding_refs else 1,
            self.source_sha256,
            self.source_ref,
        )


def _source_ref(source_uri: str, record: Mapping[str, Any], family: str) -> str:
    legacy_id = _first(
        record,
        "id",
        "response_id",
        "responseId",
        "template_id",
        "templateId",
        "audio_id",
        "audioId",
        "provenance_id",
        "provenanceId",
    )
    key = quote(str(legacy_id), safe="._-") if legacy_id else record_sha256(record)
    return f"{source_uri}#{family}/{key}"


def _issue(
    code: QuarantineReason, message: str, field_name: str | None = None
) -> QualityIssue:
    return QualityIssue(code=code, message=message, field=field_name)


def _spoken_quality_issues(
    raw_text: str,
    spoken_text: str,
    record: Mapping[str, Any],
    config: NormalizationConfig,
) -> tuple[QualityIssue, ...]:
    issues: list[QualityIssue] = []
    alphanumeric = "".join(char for char in spoken_text if char.isalnum())
    if not spoken_text or not alphanumeric:
        issues.append(_issue(QuarantineReason.EMPTY_TEXT, "spoken text is empty", "text"))
        return tuple(issues)
    if len(alphanumeric) < config.minimum_alphanumeric_characters:
        issues.append(
            _issue(
                QuarantineReason.LOW_VALUE_FRAGMENT,
                "spoken text has too little alphanumeric content",
                "text",
            )
        )
    source_types = {item.casefold() for item in _strings(record.get("sourceTypes"))}
    candidate_kind = str(record.get("candidateKind") or "").casefold()
    bm25_only = (
        "graphrag.bm25_term" in source_types or candidate_kind == "bm25_term"
    ) and not any(
        item in source_types
        for item in (
            "audio_plan.slot_value",
            "graphrag.phone",
            "graphrag.address",
            "graphrag.entity",
        )
    )
    if (
        config.reject_bm25_only_vocabulary
        and bm25_only
        and (spoken_text.casefold() in _LOW_VALUE_TERMS or len(spoken_text) < 4)
    ):
        issues.append(
            _issue(
                QuarantineReason.LOW_VALUE_FRAGMENT,
                "isolated BM25 vocabulary fragment is not useful spoken content",
                "sourceTypes",
            )
        )
    malformed: list[str] = []
    if _CONTROL_RE.search(raw_text) or _REPLACEMENT_RE.search(raw_text):
        malformed.append("control or replacement character")
    if _EMPTY_QUOTE_RE.search(raw_text):
        malformed.append("empty quoted value")
    if _RESIDUAL_MARKUP_RE.search(spoken_text):
        malformed.append("residual markup")
    if _REPEATED_CHAR_RE.search(spoken_text):
        malformed.append("repeated character run")
    if spoken_text.count("{") != spoken_text.count("}") or _PLACEHOLDER_RE.search(spoken_text):
        malformed.append("unbound or unbalanced placeholder")
    if len(spoken_text) > config.maximum_spoken_characters:
        malformed.append("text exceeds maximum spoken length")
    if malformed:
        issues.append(
            _issue(
                QuarantineReason.MALFORMED_SPOKEN_TEXT,
                ", ".join(sorted(set(malformed))),
                "spoken_text",
            )
        )
    return tuple(issues)


def _extract_slots(
    record: Mapping[str, Any], raw_text: str
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[QualityIssue, ...]]:
    names = list(_ordered_strings(_first(record, "slot_names", "slotNames")))
    values = list(_ordered_strings(_first(record, "slot_values", "slotValues")))
    sources = list(
        _ordered_strings(_first(record, "slot_source_cids", "slotSourceCids"))
    )
    raw_slots = record.get("slots")
    if isinstance(raw_slots, Sequence) and not isinstance(raw_slots, str | bytes):
        names, values, sources = [], [], []
        for slot in raw_slots:
            if not isinstance(slot, Mapping):
                continue
            name = str(_first(slot, "name", "slot", "slotName") or "").strip()
            value = str(_first(slot, "value", "slotValue") or "").strip()
            source = str(
                _first(slot, "source_cid", "sourceCid", "sourceCID") or ""
            ).strip()
            if name or value or source:
                names.append(name)
                values.append(value)
                sources.append(source)
    if not (names or values or sources):
        return (), (), (), ()
    problems: list[str] = []
    if not (len(names) == len(values) == len(sources)):
        problems.append("slot names, values, and source CIDs have different lengths")
    if any(not item for item in names):
        problems.append("slot name is empty")
    if any(not item for item in values):
        problems.append("slot value is empty")
    if any(not item for item in sources):
        problems.append("slot source CID is empty")
    if len(set(names)) != len(names):
        problems.append("slot names are not unique")
    folded_raw = normalized_text_identity(raw_text)
    for name, value in zip(names, values):
        if value and normalized_text_identity(value) not in folded_raw:
            problems.append(f"slot {name!r} value is absent from source text")
    issues = (
        (
            _issue(
                QuarantineReason.INCONSISTENT_SLOTS,
                "; ".join(sorted(set(problems))),
                "slots",
            ),
        )
        if problems
        else ()
    )
    return tuple(names), tuple(values), tuple(sources), issues


def _grounding_refs(record: Mapping[str, Any]) -> tuple[str, ...]:
    return _strings(
        (
            *_strings(_first(record, "source_cids", "sourceCids")),
            *_strings(_first(record, "sourceIds", "source_ids")),
            *_strings(_first(record, "evidenceDocIds", "evidence_doc_ids")),
        )
    )


def _resolve_audio_path(record: Mapping[str, Any], audio_root: Path | None) -> Path | None:
    raw = _first(record, *_AUDIO_PATH_FIELDS)
    if not raw:
        return None
    path = Path(str(raw))
    if not path.is_absolute() and audio_root is not None:
        path = audio_root / path
    return path


def _audio_candidate(
    record: Mapping[str, Any],
    *,
    spoken_text: str,
    response_id: str | None,
    audio_root: Path | None,
    config: NormalizationConfig,
) -> tuple[AbbyVoiceAudio | None, tuple[QualityIssue, ...]]:
    raw_path = _first(record, *_AUDIO_PATH_FIELDS)
    path = _resolve_audio_path(record, audio_root)
    uri_value = _first(record, *_AUDIO_URI_FIELDS)
    uri = (
        str(uri_value).strip()
        if uri_value
        else (str(raw_path).strip() if raw_path else None)
    )
    explicit_digest = str(
        _first(record, "audioSha256", "audio_sha256", "sha256") or ""
    ).strip().lower()
    digest = explicit_digest if re.fullmatch(r"[0-9a-f]{64}", explicit_digest) else ""
    issues: list[QualityIssue] = []
    actual_length: int | None = None
    if path is not None:
        try:
            data = path.read_bytes()
        except OSError:
            data = b""
        if not data:
            issues.append(
                _issue(
                    QuarantineReason.MISSING_AUDIO,
                    f"audio path is missing, unreadable, or empty: {path}",
                    "audio",
                )
            )
        else:
            actual_length = len(data)
            actual_digest = sha256(data).hexdigest()
            if digest and digest != actual_digest:
                issues.append(
                    _issue(
                        QuarantineReason.AUDIO_HASH_MISMATCH,
                        "declared audio SHA-256 does not match audio bytes",
                        "audioSha256",
                    )
                )
            digest = actual_digest
    has_audio_fields = bool(path or uri or explicit_digest)
    if not has_audio_fields:
        issues.append(
            _issue(
                QuarantineReason.MISSING_AUDIO,
                "response has no audio locator or bytes",
                "audio",
            )
        )
        return None, tuple(issues)
    if not uri or not digest:
        issues.append(
            _issue(
                QuarantineReason.MISSING_AUDIO,
                "audio requires a locator and a full SHA-256 of its bytes",
                "audio",
            )
        )
        return None, tuple(issues)
    if issues:
        return None, tuple(issues)
    mime = str(
        _first(
            record,
            "preferredMimeType",
            "mp3MimeType",
            "mimeType",
            "mime_type",
        )
        or ("audio/wav" if str(uri).lower().endswith(".wav") else "audio/mpeg")
    )
    byte_length = _first(
        record, "preferredBytes", "mp3Bytes", "audioBytes", "byte_length"
    )
    if actual_length is not None:
        byte_length = actual_length
    try:
        return (
            AbbyVoiceAudio(
                audio_id=stable_audio_id(digest),
                spoken_text=spoken_text,
                content_sha256=digest,
                locale=str(record.get("locale") or config.locale),
                uri=uri,
                ipfs_cid=_first(record, "ipfs_cid", "cid"),
                response_id=response_id,
                template_id=_first(record, "template_id", "templateId"),
                segment_kind=str(record.get("segment_kind") or "response"),
                slot_name=_first(record, "slot_name", "slotName"),
                slot_value=_first(record, "slot_value", "slotValue"),
                mime_type=mime,
                codec=_first(record, "codec"),
                byte_length=int(byte_length) if byte_length is not None else None,
                duration_ms=_first(record, "duration_ms", "durationMs"),
                sample_rate_hz=_first(record, "sample_rate_hz", "sampleRateHz"),
                channels=record.get("channels"),
                provider=record.get("provider"),
                model=record.get("model"),
                voice=_first(record, "voice", "voiceDescription"),
                source_cids=_strings(_first(record, "source_cids", "sourceCids")),
                safety_labels=_strings(
                    _first(record, "safety_labels", "safetyLabels")
                ),
                license_id=str(record.get("license_id") or config.license_id),
                consent_status=str(
                    record.get("consent_status") or config.consent_status
                ),
                created_at=_first(record, "created_at", "createdAt"),
            ),
            (),
        )
    except (AbbyVoiceSchemaError, TypeError, ValueError) as exc:
        return None, (
            _issue(QuarantineReason.INVALID_RECORD, str(exc), "audio"),
        )


def _standalone_audio_candidate(
    record: Mapping[str, Any],
    source: _Source,
    config: NormalizationConfig,
) -> _Candidate | QuarantineRecord:
    source_ref = _source_ref(source.source_uri, record, "audio")
    source_digest = record_sha256(record)
    raw_text = str(
        _first(record, "spoken_text", "spokenText", "text") or ""
    ).strip()
    spoken = normalize_indextts_spoken_text(raw_text)
    quality_issues = list(_spoken_quality_issues(raw_text, spoken, record, config))
    audio, audio_issues = _audio_candidate(
        record,
        spoken_text=spoken,
        response_id=_first(record, "response_id", "responseId"),
        audio_root=source.audio_root,
        config=config,
    )
    quality_issues.extend(audio_issues)
    if audio is None or quality_issues:
        return QuarantineRecord(
            source_ref=source_ref,
            source_sha256=source_digest,
            source_record=dict(record),
            candidate_id=audio.audio_id if audio else None,
            issues=tuple(quality_issues)
            or (
                _issue(
                    QuarantineReason.INVALID_RECORD,
                    "legacy audio could not be normalized",
                    "audio",
                ),
            ),
        )
    return _Candidate(
        row=audio,
        raw=dict(record),
        source_ref=source_ref,
        source_sha256=source_digest,
        source_uri=source.source_uri,
        grounding_refs=_grounding_refs(record),
        audio=audio,
    )


def _response_candidate(
    record: Mapping[str, Any],
    source: _Source,
    config: NormalizationConfig,
) -> _Candidate | QuarantineRecord:
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
    spoken = normalize_indextts_spoken_text(raw_text)
    source_ref = _source_ref(source.source_uri, record, "responses")
    source_digest = record_sha256(record)
    issues = list(_spoken_quality_issues(raw_text, spoken, record, config))
    names, values, slot_sources, slot_issues = _extract_slots(record, display_text or raw_text)
    issues.extend(slot_issues)
    refs = _grounding_refs(record)
    if (
        config.require_grounding_for_claims
        and _GROUNDING_CLAIM_RE.search(display_text or raw_text)
        and not refs
    ):
        issues.append(
            _issue(
                QuarantineReason.UNGROUNDED_CLAIM,
                "factual response claim has no source ID, evidence document, or source CID",
                "sourceIds",
            )
        )
    route_labels = _strings(_first(record, "route_labels", "routes"))
    intent = str(record.get("intent") or (route_labels[0] if route_labels else "")).strip() or None
    locale = str(record.get("locale") or config.locale)
    try:
        response_id = stable_response_id(display_text, spoken, locale, intent)
        row = AbbyVoiceResponse(
            response_id=response_id,
            text=display_text,
            spoken_text=spoken,
            locale=locale,
            template_id=_first(record, "template_id", "templateId"),
            intent=intent,
            utterance=_first(record, "utterance", "query"),
            slot_names=names,
            slot_values=values,
            slot_source_cids=slot_sources,
            source_cids=_strings(_first(record, "source_cids", "sourceCids")),
            route_labels=route_labels,
            service_tags=_strings(_first(record, "service_tags", "serviceTags")),
            location_tags=_strings(
                _first(record, "location_tags", "locationTags")
            ),
            safety_labels=_strings(
                _first(record, "safety_labels", "safetyLabels")
            ),
            license_id=str(record.get("license_id") or config.license_id),
            consent_status=str(
                record.get("consent_status") or config.consent_status
            ),
            created_at=_first(record, "created_at", "createdAt"),
        )
    except (AbbyVoiceSchemaError, TypeError, ValueError) as exc:
        issues.append(_issue(QuarantineReason.INVALID_RECORD, str(exc)))
        return QuarantineRecord(
            source_ref=source_ref,
            source_sha256=source_digest,
            source_record=dict(record),
            issues=tuple(issues),
        )
    audio, audio_issues = _audio_candidate(
        record,
        spoken_text=spoken,
        response_id=row.response_id,
        audio_root=source.audio_root,
        config=config,
    )
    if config.require_audio:
        issues.extend(audio_issues)
    return _Candidate(
        row=row,
        raw=dict(record),
        source_ref=source_ref,
        source_sha256=source_digest,
        source_uri=source.source_uri,
        grounding_refs=refs,
        issues=tuple(issues),
        audio=audio,
        audio_issues=audio_issues,
    )


def _template_candidate(
    record: Mapping[str, Any], source: _Source, config: NormalizationConfig
) -> _Candidate | QuarantineRecord:
    source_ref = _source_ref(source.source_uri, record, "templates")
    source_digest = record_sha256(record)
    text = str(_first(record, "template_text", "templateText", "text") or "").strip()
    spoken = normalize_indextts_spoken_text(
        str(_first(record, "spoken_template", "spokenTemplate") or text)
    )
    intent = str(record.get("intent") or "general").strip()
    names = _strings(_first(record, "slot_names", "slotNames", "slots"))
    if not names:
        try:
            names = tuple(
                sorted(
                    {
                        name
                        for _, name, spec, conversion in Formatter().parse(text)
                        if name and not spec and not conversion
                    }
                )
            )
        except ValueError:
            names = ()
    try:
        row = AbbyVoiceTemplate(
            template_id=stable_template_id(
                text, spoken, str(record.get("locale") or config.locale), intent
            ),
            template_text=text,
            spoken_template=spoken,
            intent=intent,
            locale=str(record.get("locale") or config.locale),
            slot_names=names,
            required_slot_names=_strings(
                _first(record, "required_slot_names", "requiredSlotNames")
            ),
            factual_slot_names=_strings(
                _first(record, "factual_slot_names", "factualSlotNames")
            ),
            source_cids=_strings(_first(record, "source_cids", "sourceCids")),
            safety_labels=_strings(
                _first(record, "safety_labels", "safetyLabels")
            ),
            license_id=str(record.get("license_id") or config.license_id),
            consent_status=str(
                record.get("consent_status") or config.consent_status
            ),
            created_at=_first(record, "created_at", "createdAt"),
        )
        return _Candidate(
            row=row,
            raw=dict(record),
            source_ref=source_ref,
            source_sha256=source_digest,
            source_uri=source.source_uri,
            grounding_refs=_grounding_refs(record),
        )
    except (AbbyVoiceSchemaError, TypeError, ValueError) as exc:
        return QuarantineRecord(
            source_ref=source_ref,
            source_sha256=source_digest,
            source_record=dict(record),
            issues=(
                _issue(
                    QuarantineReason.INCONSISTENT_SLOTS
                    if "slot" in str(exc).lower() or "placeholder" in str(exc).lower()
                    else QuarantineReason.INVALID_RECORD,
                    str(exc),
                ),
            ),
        )


def _canonical_candidate(
    record: Mapping[str, Any], source: _Source
) -> _Candidate | QuarantineRecord:
    schema_version = str(record.get("schema_version") or "unknown")
    source_ref = _source_ref(source.source_uri, record, schema_version)
    source_digest = record_sha256(record)
    try:
        row = parse_abby_voice_record(record)
        return _Candidate(
            row=row,
            raw=dict(record),
            source_ref=source_ref,
            source_sha256=source_digest,
            source_uri=source.source_uri,
            grounding_refs=_grounding_refs(record),
            audio=row if isinstance(row, AbbyVoiceAudio) else None,
        )
    except (AbbyVoiceSchemaError, TypeError, ValueError) as exc:
        code = (
            QuarantineReason.INCONSISTENT_SLOTS
            if "slot" in str(exc).lower() or "placeholder" in str(exc).lower()
            else QuarantineReason.INVALID_RECORD
        )
        return QuarantineRecord(
            source_ref=source_ref,
            source_sha256=source_digest,
            source_record=dict(record),
            issues=(_issue(code, str(exc)),),
        )


def _family_for_wrapper(wrapper: str, record: Mapping[str, Any]) -> str:
    if record.get("schema_version") in SCHEMA_VERSIONS:
        version = str(record["schema_version"])
        if version == ABBY_VOICE_TEMPLATE_V2:
            return "templates"
        if version == ABBY_VOICE_AUDIO_V2:
            return "audio"
        if version == ABBY_VOICE_PROVENANCE_V2:
            return "provenance"
        return "responses"
    if wrapper == "templates":
        return "templates"
    if wrapper in {"audio", "audios", "audio_assets"}:
        return "audio"
    if wrapper == "provenance":
        return "provenance"
    kind = str(record.get("kind") or record.get("type") or "").casefold()
    if "template" in kind:
        return "templates"
    if "audio" in kind:
        return "audio"
    if "provenance" in kind:
        return "provenance"
    return "responses"


def _iter_source_rows(source: _Source) -> tuple[list[tuple[str, Mapping[str, Any]]], list[QuarantineRecord]]:
    payload = source.payload
    rows: list[tuple[str, Mapping[str, Any]]] = []
    rejected: list[QuarantineRecord] = []
    if isinstance(payload, Sequence) and not isinstance(payload, str | bytes | bytearray):
        wrappers = (("responses", payload),)
    elif isinstance(payload, Mapping) and payload.get("schema_version") in SCHEMA_VERSIONS:
        wrappers = (("records", (payload,)),)
    elif isinstance(payload, Mapping):
        wrappers = tuple(
            (key, payload[key])
            for key in _RECOGNIZED_WRAPPERS
            if key in payload and isinstance(payload[key], Sequence)
            and not isinstance(payload[key], str | bytes | bytearray)
        )
        if not wrappers:
            rejected.append(
                QuarantineRecord(
                    source_ref=f"{source.source_uri}#wrapper/{source.source_sha256}",
                    source_sha256=source.source_sha256,
                    source_record=_json_safe(payload),
                    issues=(
                        _issue(
                            QuarantineReason.UNSUPPORTED_WRAPPER,
                            "manifest has no recognized row wrapper",
                        ),
                    ),
                )
            )
            return rows, rejected
    else:
        wrappers = ()
        rejected.append(
            QuarantineRecord(
                source_ref=f"{source.source_uri}#wrapper/{source.source_sha256}",
                source_sha256=source.source_sha256,
                source_record=_json_safe(payload),
                issues=(
                    _issue(
                        QuarantineReason.UNSUPPORTED_WRAPPER,
                        "manifest root must be a mapping or list",
                    ),
                ),
            )
        )
    seen: set[tuple[str, str]] = set()
    for wrapper, values in wrappers:
        for value in values:
            if not isinstance(value, Mapping):
                digest = record_sha256(value)
                rejected.append(
                    QuarantineRecord(
                        source_ref=f"{source.source_uri}#{wrapper}/{digest}",
                        source_sha256=digest,
                        source_record=_json_safe(value),
                        issues=(
                            _issue(
                                QuarantineReason.INVALID_RECORD,
                                "row must be a mapping",
                            ),
                        ),
                    )
                )
                continue
            family = _family_for_wrapper(wrapper, value)
            identity = (family, record_sha256(value))
            # The same list can be aliased by two recognized wrapper names.
            if identity in seen:
                continue
            seen.add(identity)
            rows.append((family, dict(value)))
    return rows, rejected


def _merge_response_rows(candidates: Sequence[_Candidate], winner: _Candidate) -> AbbyVoiceResponse:
    row = winner.row
    assert isinstance(row, AbbyVoiceResponse)
    response_rows = [item.row for item in candidates if isinstance(item.row, AbbyVoiceResponse)]
    return replace(
        row,
        source_cids=tuple(sorted({value for item in response_rows for value in item.source_cids})),
        route_labels=tuple(sorted({value for item in response_rows for value in item.route_labels})),
        service_tags=tuple(sorted({value for item in response_rows for value in item.service_tags})),
        location_tags=tuple(sorted({value for item in response_rows for value in item.location_tags})),
        safety_labels=tuple(sorted({value for item in response_rows for value in item.safety_labels})),
    )


class AbbyVoiceDatasetNormalizer:
    """Batch normalizer for legacy and canonical Abby voice records."""

    def __init__(self, config: NormalizationConfig | None = None):
        self.config = config or NormalizationConfig()

    def normalize_manifest(
        self,
        manifest: Mapping[str, Any] | Sequence[Any],
        *,
        source_uri: str = "memory://abby-voice-manifest",
        source_sha256: str | None = None,
        audio_root: str | Path | None = None,
    ) -> NormalizationResult:
        """Normalize one manifest without mutating it."""

        return self.normalize_sources(
            (
                (
                    manifest,
                    source_uri,
                    source_sha256,
                    audio_root,
                ),
            )
        )

    def normalize_sources(
        self,
        sources: Iterable[
            tuple[
                Mapping[str, Any] | Sequence[Any],
                str,
                str | None,
                str | Path | None,
            ]
        ],
    ) -> NormalizationResult:
        """Normalize multiple manifests as one order-independent corpus."""

        loaded = [
            _Source(
                payload=payload,
                source_uri=str(source_uri),
                source_sha256=source_sha256 or record_sha256(payload),
                audio_root=Path(audio_root) if audio_root is not None else None,
            )
            for payload, source_uri, source_sha256, audio_root in sources
        ]
        loaded.sort(key=lambda item: (item.source_uri, item.source_sha256))
        candidates: list[_Candidate] = []
        quarantine: list[QuarantineRecord] = []
        input_count = 0
        for source in loaded:
            source_rows, wrapper_quarantine = _iter_source_rows(source)
            quarantine.extend(wrapper_quarantine)
            input_count += len(source_rows) + len(wrapper_quarantine)
            for family, record in source_rows:
                if record.get("schema_version") in SCHEMA_VERSIONS:
                    result = _canonical_candidate(record, source)
                elif family == "templates":
                    result = _template_candidate(record, source, self.config)
                elif family == "audio":
                    result = _standalone_audio_candidate(
                        record, source, self.config
                    )
                elif family == "provenance":
                    result = _canonical_candidate(record, source)
                else:
                    result = _response_candidate(record, source, self.config)
                if isinstance(result, QuarantineRecord):
                    quarantine.append(result)
                elif result.issues:
                    quarantine.append(
                        QuarantineRecord(
                            source_ref=result.source_ref,
                            source_sha256=result.source_sha256,
                            source_record=result.raw,
                            issues=result.issues,
                            candidate_id=getattr(result.row, result.row.ID_FIELD),
                        )
                    )
                else:
                    candidates.append(result)

        templates: list[AbbyVoiceTemplate] = []
        standalone_audio: list[_Candidate] = []
        standalone_provenance: list[_Candidate] = []
        duplicate_ledger: list[DuplicateLedgerEntry] = []
        warnings: list[QuarantineRecord] = []

        response_groups: dict[str, list[_Candidate]] = defaultdict(list)
        template_groups: dict[str, list[_Candidate]] = defaultdict(list)
        for item in candidates:
            if isinstance(item.row, AbbyVoiceResponse):
                response_groups[normalized_text_identity(item.row.spoken_text)].append(item)
            elif isinstance(item.row, AbbyVoiceTemplate):
                template_groups[normalized_text_identity(item.row.spoken_template or "")].append(item)
            elif isinstance(item.row, AbbyVoiceAudio):
                standalone_audio.append(item)
            elif isinstance(item.row, AbbyVoiceProvenance):
                standalone_provenance.append(item)

        accepted_response_candidates: list[tuple[_Candidate, AbbyVoiceResponse, list[_Candidate]]] = []
        for identity, group in sorted(response_groups.items()):
            ordered = sorted(group, key=lambda item: item.rank)
            winner = ordered[0]
            merged = _merge_response_rows(ordered, winner)
            accepted_response_candidates.append((winner, merged, ordered))
            if len(ordered) > 1:
                identity_digest = sha256_text(identity)
                duplicate_ledger.append(
                    DuplicateLedgerEntry(
                        kind="text",
                        identity_sha256=identity_digest,
                        survivor_id=merged.response_id,
                        survivor_source_ref=winner.source_ref,
                        duplicate_source_refs=tuple(
                            sorted(item.source_ref for item in ordered[1:])
                        ),
                    )
                )
                target = quarantine if self.config.quarantine_duplicates else warnings
                for duplicate in ordered[1:]:
                    target.append(
                        QuarantineRecord(
                            source_ref=duplicate.source_ref,
                            source_sha256=duplicate.source_sha256,
                            source_record=duplicate.raw,
                            candidate_id=merged.response_id,
                            issues=(
                                _issue(
                                    QuarantineReason.DUPLICATE_TEXT,
                                    f"duplicate of survivor {winner.source_ref}",
                                    "spoken_text",
                                ),
                            ),
                        )
                    )

        for _, group in sorted(template_groups.items()):
            ordered = sorted(group, key=lambda item: item.rank)
            templates.append(ordered[0].row)  # type: ignore[arg-type]
            if len(ordered) > 1:
                for duplicate in ordered[1:]:
                    quarantine.append(
                        QuarantineRecord(
                            source_ref=duplicate.source_ref,
                            source_sha256=duplicate.source_sha256,
                            source_record=duplicate.raw,
                            candidate_id=getattr(ordered[0].row, ordered[0].row.ID_FIELD),
                            issues=(
                                _issue(
                                    QuarantineReason.DUPLICATE_TEXT,
                                    f"duplicate template of {ordered[0].source_ref}",
                                    "spoken_template",
                                ),
                            ),
                        )
                    )

        # Build provenance only after stable de-duplication so every subject
        # reference points to the surviving canonical row.
        available_template_ids = {row.template_id for row in templates}
        provenance: list[AbbyVoiceProvenance] = []
        response_audio_candidates: list[tuple[_Candidate, AbbyVoiceAudio]] = []
        final_responses: list[AbbyVoiceResponse] = []
        legacy_response_ids: dict[tuple[str, str], str] = {}
        for winner, row, whole_group in accepted_response_candidates:
            if row.template_id and row.template_id not in available_template_ids:
                for item in whole_group:
                    quarantine.append(
                        QuarantineRecord(
                            source_ref=item.source_ref,
                            source_sha256=item.source_sha256,
                            source_record=item.raw,
                            candidate_id=row.response_id,
                            issues=(
                                _issue(
                                    QuarantineReason.INVALID_RECORD,
                                    f"response references missing template {row.template_id!r}",
                                    "template_id",
                                ),
                            ),
                        )
                    )
                continue
            for item in whole_group:
                legacy_id = _first(item.raw, "id", "response_id", "responseId")
                if legacy_id:
                    legacy_response_ids[(item.source_uri, str(legacy_id))] = (
                        row.response_id
                    )
            provenance_rows: list[AbbyVoiceProvenance] = []
            for item in whole_group:
                provenance_id = stable_provenance_id(
                    row.response_id,
                    item.source_ref,
                    "normalize_abby_voice_dataset_v2",
                    item.source_sha256,
                )
                provenance_rows.append(
                    AbbyVoiceProvenance(
                        provenance_id=provenance_id,
                        subject_id=row.response_id,
                        subject_schema_version=ABBY_VOICE_RESPONSE_V2,
                        transformation_name="normalize_abby_voice_dataset_v2",
                        transformation_version=NORMALIZATION_VERSION,
                        source_uri=item.source_ref,
                        source_revision=item.source_sha256,
                        source_sha256=item.source_sha256,
                        locale=row.locale,
                        license_id=row.license_id,
                        consent_status=row.consent_status,
                        safety_labels=row.safety_labels,
                    )
                )
            provenance.extend(provenance_rows)
            selected_audio: tuple[_Candidate, AbbyVoiceAudio] | None = None
            for item in sorted(whole_group, key=lambda candidate: candidate.rank):
                if item.audio is not None:
                    selected_audio = (
                        item,
                        replace(item.audio, response_id=row.response_id),
                    )
                    break
            audio_ids = (selected_audio[1].audio_id,) if selected_audio else ()
            final_responses.append(
                replace(
                    row,
                    audio_ids=audio_ids,
                    provenance_ids=tuple(
                        sorted(item.provenance_id for item in provenance_rows)
                    ),
                )
            )
            if selected_audio:
                response_audio_candidates.append(selected_audio)
            elif winner.audio_issues and not self.config.require_audio:
                warnings.append(
                    QuarantineRecord(
                        source_ref=winner.source_ref,
                        source_sha256=winner.source_sha256,
                        source_record=winner.raw,
                        candidate_id=row.response_id,
                        issues=winner.audio_issues,
                    )
                )

        accepted_response_ids = {row.response_id for row in final_responses}
        valid_standalone_audio: list[_Candidate] = []
        for item in standalone_audio:
            assert isinstance(item.row, AbbyVoiceAudio)
            row = item.row
            mapped_response_id = (
                legacy_response_ids.get((item.source_uri, row.response_id))
                if row.response_id
                else None
            )
            if mapped_response_id:
                row = replace(row, response_id=mapped_response_id)
                item = replace(item, row=row, audio=row)
            missing_response = row.response_id and row.response_id not in accepted_response_ids
            missing_template = row.template_id and row.template_id not in available_template_ids
            if missing_response or missing_template:
                missing = row.response_id if missing_response else row.template_id
                quarantine.append(
                    QuarantineRecord(
                        source_ref=item.source_ref,
                        source_sha256=item.source_sha256,
                        source_record=item.raw,
                        candidate_id=row.audio_id,
                        issues=(
                            _issue(
                                QuarantineReason.INVALID_RECORD,
                                f"audio references missing subject {missing!r}",
                                "response_id" if missing_response else "template_id",
                            ),
                        ),
                    )
                )
            else:
                valid_standalone_audio.append(item)
        standalone_audio = valid_standalone_audio

        audio_groups: dict[str, list[tuple[_Candidate, AbbyVoiceAudio]]] = defaultdict(list)
        for item, audio_row in response_audio_candidates:
            audio_groups[audio_row.content_sha256].append((item, audio_row))
        for item in standalone_audio:
            assert isinstance(item.row, AbbyVoiceAudio)
            audio_groups[item.row.content_sha256].append((item, item.row))

        final_audio: list[AbbyVoiceAudio] = []
        duplicate_audio_ids: set[str] = set()
        for digest, group in sorted(audio_groups.items()):
            ordered = sorted(group, key=lambda pair: pair[0].rank)
            winner_source, winner_audio = ordered[0]
            final_audio.append(winner_audio)
            if len(ordered) > 1:
                duplicate_ledger.append(
                    DuplicateLedgerEntry(
                        kind="audio",
                        identity_sha256=digest,
                        survivor_id=winner_audio.audio_id,
                        survivor_source_ref=winner_source.source_ref,
                        duplicate_source_refs=tuple(
                            sorted(pair[0].source_ref for pair in ordered[1:])
                        ),
                    )
                )
                for duplicate_source, duplicate_audio in ordered[1:]:
                    duplicate_audio_ids.add(duplicate_audio.audio_id)
                    quarantine.append(
                        QuarantineRecord(
                            source_ref=duplicate_source.source_ref,
                            source_sha256=duplicate_source.source_sha256,
                            source_record=duplicate_source.raw,
                            candidate_id=winner_audio.audio_id,
                            issues=(
                                _issue(
                                    QuarantineReason.DUPLICATE_AUDIO,
                                    f"audio bytes duplicate {winner_source.source_ref}",
                                    "audio",
                                ),
                            ),
                        )
                    )

        # Provenance for accepted templates and audio rows is local and stable.
        final_templates: list[AbbyVoiceTemplate] = []
        template_candidate_by_id = {
            item.row.template_id: item
            for group in template_groups.values()
            for item in sorted(group, key=lambda candidate: candidate.rank)[:1]
            if isinstance(item.row, AbbyVoiceTemplate)
        }
        for row in templates:
            source_item = template_candidate_by_id[row.template_id]
            prov = AbbyVoiceProvenance(
                provenance_id=stable_provenance_id(
                    row.template_id,
                    source_item.source_ref,
                    "normalize_abby_voice_dataset_v2",
                    source_item.source_sha256,
                ),
                subject_id=row.template_id,
                subject_schema_version=ABBY_VOICE_TEMPLATE_V2,
                transformation_name="normalize_abby_voice_dataset_v2",
                transformation_version=NORMALIZATION_VERSION,
                source_uri=source_item.source_ref,
                source_revision=source_item.source_sha256,
                source_sha256=source_item.source_sha256,
                locale=row.locale,
                license_id=row.license_id,
                consent_status=row.consent_status,
                safety_labels=row.safety_labels,
            )
            provenance.append(prov)
            final_templates.append(replace(row, provenance_ids=(prov.provenance_id,)))

        final_audio_with_provenance: list[AbbyVoiceAudio] = []
        audio_source_by_id = {
            audio_row.audio_id: source_item
            for source_item, audio_row in (
                response_audio_candidates
                + [
                    (item, item.row)
                    for item in standalone_audio
                    if isinstance(item.row, AbbyVoiceAudio)
                ]
            )
        }
        for row in final_audio:
            source_item = audio_source_by_id[row.audio_id]
            prov = AbbyVoiceProvenance(
                provenance_id=stable_provenance_id(
                    row.audio_id,
                    source_item.source_ref,
                    "normalize_abby_voice_dataset_v2",
                    source_item.source_sha256,
                ),
                subject_id=row.audio_id,
                subject_schema_version=ABBY_VOICE_AUDIO_V2,
                transformation_name="normalize_abby_voice_dataset_v2",
                transformation_version=NORMALIZATION_VERSION,
                source_uri=source_item.source_ref,
                source_revision=source_item.source_sha256,
                source_sha256=source_item.source_sha256,
                locale=row.locale,
                license_id=row.license_id,
                consent_status=row.consent_status,
                safety_labels=row.safety_labels,
            )
            provenance.append(prov)
            final_audio_with_provenance.append(
                replace(row, provenance_ids=(prov.provenance_id,))
            )

        # Attach every accepted one-way audio relationship to its response and
        # remove references to non-surviving byte duplicates.
        audio_by_response: dict[str, set[str]] = defaultdict(set)
        for item in final_audio_with_provenance:
            if item.response_id:
                audio_by_response[item.response_id].add(item.audio_id)
        final_responses = [
            replace(
                row,
                audio_ids=tuple(sorted(audio_by_response.get(row.response_id, ()))),
            )
            for row in final_responses
        ]

        # Preserve canonical lineage only when both its subject and every
        # declared parent are present in this build.
        subject_ids = {
            ABBY_VOICE_RESPONSE_V2: {row.response_id for row in final_responses},
            ABBY_VOICE_TEMPLATE_V2: {row.template_id for row in final_templates},
            ABBY_VOICE_AUDIO_V2: {
                row.audio_id for row in final_audio_with_provenance
            },
        }
        eligible_by_id = {
            item.row.provenance_id: item
            for item in standalone_provenance
            if isinstance(item.row, AbbyVoiceProvenance)
            and item.row.subject_id
            in subject_ids.get(item.row.subject_schema_version, set())
        }
        generated_ids = {item.provenance_id for item in provenance}
        while True:
            eligible_ids = generated_ids | set(eligible_by_id)
            retained = {
                identity: item
                for identity, item in eligible_by_id.items()
                if isinstance(item.row, AbbyVoiceProvenance)
                and all(
                    parent in eligible_ids
                    for parent in item.row.parent_provenance_ids
                )
            }
            if retained.keys() == eligible_by_id.keys():
                break
            eligible_by_id = retained
        for item in standalone_provenance:
            assert isinstance(item.row, AbbyVoiceProvenance)
            row = item.row
            subject_present = row.subject_id in subject_ids.get(
                row.subject_schema_version, set()
            )
            if subject_present and row.provenance_id in eligible_by_id:
                provenance.append(row)
            else:
                quarantine.append(
                    QuarantineRecord(
                        source_ref=item.source_ref,
                        source_sha256=item.source_sha256,
                        source_record=item.raw,
                        candidate_id=row.provenance_id,
                        issues=(
                            _issue(
                                QuarantineReason.INVALID_RECORD,
                                "provenance references a missing subject or parent",
                                "subject_id",
                            ),
                        ),
                    )
                )

        final_responses.sort(key=lambda row: row.response_id)
        final_templates.sort(key=lambda row: row.template_id)
        final_audio_with_provenance.sort(key=lambda row: row.audio_id)
        provenance_by_id = {row.provenance_id: row for row in provenance}
        final_provenance = sorted(
            provenance_by_id.values(), key=lambda row: row.provenance_id
        )
        quarantine.sort(key=lambda row: (row.source_ref, row.reason_codes, row.source_sha256))
        warnings.sort(key=lambda row: (row.source_ref, row.reason_codes, row.source_sha256))
        duplicate_ledger.sort(
            key=lambda row: (row.kind, row.identity_sha256, row.survivor_source_ref)
        )

        # Structural validation is the final internal gate.  Externally
        # referenced templates on response rows are not invented here.
        validate_bundle(
            responses=final_responses,
            templates=final_templates,
            audio=final_audio_with_provenance,
            provenance=final_provenance,
            require_references=True,
        )

        splits: dict[str, str] = {}
        for row in final_responses:
            key = row.template_id or row.content_sha256 or row.response_id
            splits[row.response_id] = deterministic_split(
                key,
                train=self.config.split_train,
                validation=self.config.split_validation,
                test=self.config.split_test,
                salt=self.config.split_salt,
            )
        for row in final_templates:
            splits[row.template_id] = deterministic_split(
                row.template_id,
                train=self.config.split_train,
                validation=self.config.split_validation,
                test=self.config.split_test,
                salt=self.config.split_salt,
            )
        for row in final_audio_with_provenance:
            if row.response_id and row.response_id in splits:
                splits[row.audio_id] = splits[row.response_id]
            elif row.template_id and row.template_id in splits:
                splits[row.audio_id] = splits[row.template_id]
            else:
                splits[row.audio_id] = deterministic_split(
                    row.audio_id,
                    train=self.config.split_train,
                    validation=self.config.split_validation,
                    test=self.config.split_test,
                    salt=self.config.split_salt,
                )
        for row in final_provenance:
            splits[row.provenance_id] = splits.get(
                row.subject_id,
                deterministic_split(
                    row.subject_id,
                    train=self.config.split_train,
                    validation=self.config.split_validation,
                    test=self.config.split_test,
                    salt=self.config.split_salt,
                ),
            )

        return NormalizationResult(
            responses=tuple(final_responses),
            templates=tuple(final_templates),
            audio=tuple(final_audio_with_provenance),
            provenance=tuple(final_provenance),
            quarantine=tuple(quarantine),
            warnings=tuple(warnings),
            duplicates=tuple(duplicate_ledger),
            splits=dict(sorted(splits.items())),
            input_record_count=input_count,
            source_manifest_count=len(loaded),
            config=self.config,
        )


def normalize_manifest(
    manifest: Mapping[str, Any] | Sequence[Any],
    *,
    source_uri: str = "memory://abby-voice-manifest",
    source_sha256: str | None = None,
    audio_root: str | Path | None = None,
    config: NormalizationConfig | None = None,
) -> NormalizationResult:
    """Functional wrapper around :class:`AbbyVoiceDatasetNormalizer`."""

    return AbbyVoiceDatasetNormalizer(config).normalize_manifest(
        manifest,
        source_uri=source_uri,
        source_sha256=source_sha256,
        audio_root=audio_root,
    )


def deduplicate_voice_response_chunks(
    responses: Iterable[AbbyVoiceResponse | Mapping[str, Any]],
    *,
    maximum_characters: int = 220,
) -> dict[str, Any]:
    """Build a deterministic exact sentence-chunk de-duplication report."""

    if maximum_characters < 1:
        raise ValueError("maximum_characters must be positive")
    boundary = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
    groups: dict[str, dict[str, Any]] = {}
    response_count = 0
    source_count = 0
    for value in responses:
        row = (
            value
            if isinstance(value, AbbyVoiceResponse)
            else parse_abby_voice_record(value)
        )
        if not isinstance(row, AbbyVoiceResponse):
            raise TypeError("deduplicate_voice_response_chunks accepts responses only")
        response_count += 1
        raw_parts = boundary.split(row.spoken_text)
        chunks: list[str] = []
        for part in raw_parts:
            part = _SPACE_RE.sub(" ", part).strip()
            if len(part) <= maximum_characters:
                if part:
                    chunks.append(part)
            else:
                chunks.extend(
                    part[index : index + maximum_characters].strip()
                    for index in range(0, len(part), maximum_characters)
                )
        for index, chunk in enumerate(chunks):
            identity = normalized_text_identity(chunk)
            item = groups.setdefault(
                identity,
                {
                    "chunk_id": f"chunk-{sha256_text(identity)[:24]}",
                    "text": chunk,
                    "response_ids": set(),
                    "positions": [],
                },
            )
            item["text"] = min(item["text"], chunk)
            item["response_ids"].add(row.response_id)
            item["positions"].append(
                {"response_id": row.response_id, "chunk_index": index}
            )
            source_count += 1
    chunks = [
        {
            "chunk_id": item["chunk_id"],
            "text": item["text"],
            "response_ids": sorted(item["response_ids"]),
            "positions": sorted(
                item["positions"],
                key=lambda position: (
                    position["response_id"],
                    position["chunk_index"],
                ),
            ),
            "reuse_count": len(item["positions"]),
        }
        for item in groups.values()
    ]
    chunks.sort(key=lambda item: (-item["reuse_count"], item["chunk_id"]))
    return {
        "response_count": response_count,
        "source_chunk_count": source_count,
        "unique_chunk_count": len(chunks),
        "duplicate_chunk_count": source_count - len(chunks),
        "chunks": chunks,
    }


def build_slotted_response_dag(
    responses: Iterable[AbbyVoiceResponse | Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a small deterministic intent/template/response relationship DAG.

    This normalization-time DAG is intentionally metadata-only.  G007 owns the
    searchable GraphRAG implementation.
    """

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    for value in responses:
        row = (
            value
            if isinstance(value, AbbyVoiceResponse)
            else parse_abby_voice_record(value)
        )
        if not isinstance(row, AbbyVoiceResponse):
            raise TypeError("build_slotted_response_dag accepts responses only")
        intent = row.intent or "general"
        intent_id = f"intent-{sha256_text(intent)[:24]}"
        nodes[intent_id] = {"id": intent_id, "kind": "intent", "intent": intent}
        nodes[row.response_id] = {
            "id": row.response_id,
            "kind": "response",
            "slot_names": list(row.slot_names),
            "source_cids": list(row.source_cids),
        }
        edges.append(
            {
                "id": f"edge-{sha256_text(intent_id + chr(0) + row.response_id)[:24]}",
                "source": intent_id,
                "target": row.response_id,
                "kind": "intent_to_response",
            }
        )
        if row.template_id:
            nodes.setdefault(
                row.template_id, {"id": row.template_id, "kind": "template"}
            )
            edges.append(
                {
                    "id": f"edge-{sha256_text(row.template_id + chr(0) + row.response_id)[:24]}",
                    "source": row.template_id,
                    "target": row.response_id,
                    "kind": "template_to_response",
                }
            )
    return {
        "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
        "edges": sorted(edges, key=lambda item: item["id"]),
    }


__all__ = [
    "AUDIO_HASH_MISMATCH",
    "DUPLICATE_AUDIO",
    "DUPLICATE_TEXT",
    "EMPTY_TEXT",
    "INCONSISTENT_SLOTS",
    "INVALID_RECORD",
    "LOW_VALUE_FRAGMENT",
    "MALFORMED_SPOKEN_TEXT",
    "MISSING_AUDIO",
    "NORMALIZATION_VERSION",
    "QUALITY_REPORT_VERSION",
    "UNGROUNDED_CLAIM",
    "AbbyVoiceDatasetNormalizer",
    "DuplicateLedgerEntry",
    "NormalizationConfig",
    "NormalizationResult",
    "QualityIssue",
    "QuarantineReason",
    "QuarantineRecord",
    "build_slotted_response_dag",
    "canonical_json",
    "deduplicate_voice_response_chunks",
    "deterministic_split",
    "normalize_indextts_spoken_text",
    "normalize_manifest",
    "normalize_spoken_text",
    "normalized_text_identity",
    "record_sha256",
]
