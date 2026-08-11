"""Production BM25 index snapshot for the public legal corpus (PATLAW-171).

Builds fielded documents / terms / postings BM25 artifacts from a pinned
public patent-law and regulations corpus root (PATLAW-170) and seals a
snapshot receipt that binds ``corpus_root_cid`` and the content-addressed
index CID.

Design invariants
-----------------
* Repeat builds for the same pinned corpus root are content-address stable.
* Orphan terms (no postings) and orphan postings (no document join) fail
  closed before any staging or CID publication.
* Every document joins the corpus via ``document_cid`` / ``source_cid`` /
  ``record_id`` (builder_bindings from the corpus materializer).
* Snapshot schema matches JusticeDAO / HF release packaging expectations
  (``bm25_documents`` + ``bm25_postings`` join fields and paths).
* Private, mixed, or unknown partitions fail closed.
* No network I/O; no Hub upload. Default mode is dry-run; ``stage=True``
  writes local artifacts only.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ....logic.ir_core.identity import cid_v1_from_digest
from .indexing import (
    TOKENIZER_VERSION,
    tokenize_patent_text,
)
from .public_legal_corpus_materializer import (
    DOCUMENTS_FILENAME as CORPUS_DOCUMENTS_FILENAME,
    MANIFEST_FILENAME as CORPUS_MANIFEST_FILENAME,
    MaterializationMode,
    PrivateOrMixedInputError as CorpusPrivateOrMixedInputError,
    PublicLegalCorpusError,
    PublicLegalCorpusMaterialization,
    PublicLegalCorpusMaterializer,
    PublicLegalDocument,
    assert_public_only_documents,
    build_default_public_legal_recipe,
    load_manifest as load_corpus_manifest,
)
from .retrieval_contracts import (
    DisclosureClass,
    FieldWeightConfig,
    IndexField,
    is_private_disclosure,
    is_public_disclosure,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "patent.public_legal_bm25.v1"
INTERFACE: Final = "PublicLegalBm25Builder@1"
PRODUCER: Final = "producer:public-legal-bm25-builder"
CONFIG_ID: Final = "config:public-legal-bm25/v1"
TASK_ID: Final = "PATLAW-171"
GOAL_ID: Final = "PATLAW-G211"
CODE_VERSION: Final = "1.0.0"

# Staged snapshot filenames (local packaging layout).
MANIFEST_FILENAME: Final = "public-legal-bm25.manifest.json"
DOCUMENTS_FILENAME: Final = "bm25-documents.jsonl"
TERMS_FILENAME: Final = "bm25-terms.jsonl"
POSTINGS_FILENAME: Final = "bm25-postings.jsonl"
RECEIPT_FILENAME: Final = "bm25-snapshot-receipt.json"
INDEX_ROOT_FILENAME: Final = "index-root.json"

# HF / JusticeDAO release packaging expectations (hf_layout_v2 / hf_release_v2).
RELEASE_ROLE: Final = "bm25"
RELEASE_REPOSITORY: Final = "patent-legal-bm25"
RELEASE_CONFIGS: Final[tuple[str, ...]] = ("bm25_documents", "bm25_postings")
RELEASE_DOCUMENTS_PATTERN: Final = "data/bm25/documents/*.parquet"
RELEASE_POSTINGS_PATTERN: Final = "data/bm25/postings/*.parquet"
RELEASE_DOCUMENTS_JOIN_FIELDS: Final[tuple[str, ...]] = (
    "source_cid",
    "record_id",
    "corpus_record_id",
)
RELEASE_POSTINGS_JOIN_FIELDS: Final[tuple[str, ...]] = ("term", "document_id")
RELEASE_DOCUMENTS_FEATURES: Final[tuple[str, ...]] = (
    "record_id",
    "corpus_record_id",
    "source_cid",
    "text_preview",
    "token_count",
)
RELEASE_POSTINGS_FEATURES: Final[tuple[str, ...]] = (
    "term",
    "document_id",
    "tf",
    "df",
)

# Field order for deterministic multi-field tokenization of legal docs.
_FIELD_ORDER: Final[tuple[str, ...]] = (
    IndexField.TITLE.value,
    IndexField.DESCRIPTION.value,
    IndexField.LEGAL_BASES.value,
    IndexField.NUMBERS.value,
    IndexField.ABSTRACT.value,
)

TEXT_PREVIEW_MAX: Final = 240
DEFAULT_TENANT_ID: Final = "public-legal"
DEFAULT_K1: Final = 1.5
DEFAULT_B: Final = 0.75

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")
_RECORD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}$")
_FILE_MODE: Final = 0o600
_DIR_MODE: Final = 0o700

# Fields stripped from content digests so staging timestamps cannot drift CIDs.
_NON_CONTENT_MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "staged_at_utc",
        "notes",
        "mode",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublicLegalBm25Error(ValueError):
    """Base error for public legal BM25 snapshot builds."""

    code: str = "public_legal_bm25_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class OrphanTermError(PublicLegalBm25Error):
    """Raised when a term has no postings or cannot join the vocabulary."""

    code = "orphan_term"


class OrphanPostingError(PublicLegalBm25Error):
    """Raised when a posting does not join an admitted BM25 document."""

    code = "orphan_posting"


class OrphanDocumentError(PublicLegalBm25Error):
    """Raised when a BM25 document cannot join the pinned corpus root."""

    code = "orphan_document"


class CorpusPinError(PublicLegalBm25Error):
    """Raised when the corpus root pin is missing or mismatches the input."""

    code = "corpus_pin_mismatch"


class PrivateOrMixedInputError(PublicLegalBm25Error):
    """Raised when private / mixed / unknown material is present."""

    code = "private_or_mixed_input"


class SnapshotIntegrityError(PublicLegalBm25Error):
    """Raised when counts, digests, or CIDs fail integrity checks."""

    code = "snapshot_integrity"


class SchemaValidationError(PublicLegalBm25Error):
    """Raised when a document, term, posting, or snapshot fails validation."""

    code = "schema_validation"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BuildMode(str, Enum):
    """How the BM25 snapshot is produced."""

    DRY_RUN = "dry_run"
    STAGE = "stage"


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding for content addressing and equality."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest_of(value: Any) -> str:
    """SHA-256 hex of the canonical JSON encoding of *value*."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_cid_of(value: Any) -> str:
    """CIDv1 (dag-pb / sha2-256) of the canonical JSON encoding of *value*."""
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).digest()
    return cid_v1_from_digest(digest)


def content_cid_of_bytes(payload: bytes) -> str:
    """CIDv1 of raw *payload* bytes."""
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes")
    return cid_v1_from_digest(hashlib.sha256(bytes(payload)).digest())


def _require_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise SchemaValidationError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise SchemaValidationError(f"{name} exceeds max length {maximum}")
    return text


def _optional_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if value is None or value == "":
        return ""
    return _require_str(value, name, maximum=maximum)


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_str(value, name, maximum=64).lower()
    if not _SHA256_RE.fullmatch(text):
        raise SchemaValidationError(
            f"{name} must be a lowercase 64-char hex SHA-256"
        )
    return text


def _require_cid(value: Any, name: str = "cid") -> str:
    text = _require_str(value, name, maximum=256)
    if not _CID_RE.fullmatch(text):
        raise SchemaValidationError(f"{name} is not a valid CIDv1: {text!r}")
    return text


def _require_record_id(value: Any, name: str = "record_id") -> str:
    text = _require_str(value, name, maximum=256)
    if not _RECORD_ID_RE.fullmatch(text):
        raise SchemaValidationError(f"{name} is not a valid identifier: {text!r}")
    return text


def _require_nonneg_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{name} must be an int")
    if value < 0:
        raise SchemaValidationError(f"{name} must be non-negative")
    return value


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, _DIR_MODE)
    except OSError:
        pass
    return path


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        tmp.write_bytes(payload)
        try:
            os.chmod(tmp, _FILE_MODE)
        except OSError:
            pass
        tmp.replace(path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _idf(document_count: int, document_frequency: int) -> float:
    """Standard Okapi BM25 IDF with +1 smoothing."""
    if document_count < 1:
        return 0.0
    df = max(1, int(document_frequency))
    return math.log(1.0 + ((document_count - df + 0.5) / (df + 0.5)))


def _text_preview(text: str, *, maximum: int = TEXT_PREVIEW_MAX) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= maximum:
        return cleaned
    return cleaned[: maximum - 1].rstrip() + "…"


def default_field_weight_config(
    *,
    config_cid: str | None = None,
    k1: float = DEFAULT_K1,
    b: float = DEFAULT_B,
) -> FieldWeightConfig:
    """Field weights tailored for public legal corpus fields."""
    # Reuse default weights; legal body text maps onto DESCRIPTION.
    base = FieldWeightConfig.default(config_cid=config_cid)
    return FieldWeightConfig.from_dict(
        {
            **base.to_dict(),
            "k1": k1,
            "b": b,
        }
    )


def legal_field_values(doc: PublicLegalDocument) -> dict[str, str]:
    """Map a public legal document onto fielded BM25 text fields."""
    fields: dict[str, str] = {}
    title = str(doc.title or "").strip()
    body = str(doc.text or "").strip()
    citation = str(doc.citation or "").strip()
    section_id = str(doc.section_id or "").strip()
    if title:
        fields[IndexField.TITLE.value] = title
    if body:
        fields[IndexField.DESCRIPTION.value] = body
    if citation:
        fields[IndexField.LEGAL_BASES.value] = citation
    if section_id:
        fields[IndexField.NUMBERS.value] = section_id
    # Authority kind / family as weak abstract cues for retrieval.
    cues = " ".join(
        part
        for part in (
            str(doc.family.value if hasattr(doc.family, "value") else doc.family),
            str(doc.authority_kind or ""),
        )
        if part
    ).strip()
    if cues:
        fields[IndexField.ABSTRACT.value] = cues
    return fields


def public_legal_document_to_tokens(
    doc: PublicLegalDocument,
) -> tuple[dict[str, Counter[str]], int, list[str]]:
    """Tokenize *doc* into per-field term counters.

    Returns ``(field_counts, total_tokens, field_order_used)``.
    """
    field_values = legal_field_values(doc)
    field_counts: dict[str, Counter[str]] = {}
    total = 0
    used: list[str] = []
    # Stable field order first, then residual keys.
    ordered = list(_FIELD_ORDER)
    for name in field_values:
        if name not in ordered:
            ordered.append(name)
    for field_name in ordered:
        text = field_values.get(field_name) or ""
        if not text:
            continue
        tokens = tokenize_patent_text(text)
        if not tokens:
            continue
        counts = Counter(tokens)
        field_counts[field_name] = counts
        total += sum(counts.values())
        used.append(field_name)
    return field_counts, total, used


# ---------------------------------------------------------------------------
# Record models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Bm25DocumentRecord:
    """One BM25 document row, release-packaging compatible."""

    record_id: str
    corpus_record_id: str
    source_cid: str
    document_cid: str
    document_sha256: str
    classification: str
    family: str
    title: str
    citation: str
    text_preview: str
    token_count: int
    document_length: int
    field_lengths: Mapping[str, int]
    source_root_id: str
    authority_kind: str
    authority_claim: str

    def __post_init__(self) -> None:
        record_id = _require_record_id(self.record_id, "record_id")
        corpus_record_id = _require_record_id(
            self.corpus_record_id, "corpus_record_id"
        )
        source_cid = _require_cid(self.source_cid, "source_cid")
        document_cid = _require_cid(self.document_cid, "document_cid")
        document_sha256 = _require_sha256(self.document_sha256, "document_sha256")
        classification = _require_str(self.classification, "classification", maximum=64)
        if is_private_disclosure(classification) or classification == "unknown":
            raise PrivateOrMixedInputError(
                f"private/unknown classification rejected: {classification!r}"
            )
        if not is_public_disclosure(classification):
            raise PrivateOrMixedInputError(
                f"classification is not public: {classification!r}"
            )
        token_count = _require_nonneg_int(self.token_count, "token_count")
        document_length = _require_nonneg_int(self.document_length, "document_length")
        if token_count < 1 or document_length < 1:
            raise SchemaValidationError(
                f"document {record_id!r} has no tokens after tokenization"
            )
        field_lengths = {
            str(k): int(v)
            for k, v in sorted((self.field_lengths or {}).items())
            if int(v) > 0
        }
        object.__setattr__(self, "record_id", record_id)
        object.__setattr__(self, "corpus_record_id", corpus_record_id)
        object.__setattr__(self, "source_cid", source_cid)
        object.__setattr__(self, "document_cid", document_cid)
        object.__setattr__(self, "document_sha256", document_sha256)
        object.__setattr__(self, "classification", classification)
        object.__setattr__(
            self, "family", _require_str(self.family, "family", maximum=64)
        )
        object.__setattr__(self, "title", _optional_str(self.title, "title", maximum=1024))
        object.__setattr__(
            self, "citation", _optional_str(self.citation, "citation", maximum=1024)
        )
        object.__setattr__(
            self,
            "text_preview",
            _optional_str(self.text_preview, "text_preview", maximum=TEXT_PREVIEW_MAX + 8),
        )
        object.__setattr__(self, "token_count", token_count)
        object.__setattr__(self, "document_length", document_length)
        object.__setattr__(self, "field_lengths", MappingProxyType(field_lengths))
        object.__setattr__(
            self,
            "source_root_id",
            _require_str(self.source_root_id, "source_root_id", maximum=256),
        )
        object.__setattr__(
            self,
            "authority_kind",
            _optional_str(self.authority_kind, "authority_kind", maximum=64),
        )
        object.__setattr__(
            self,
            "authority_claim",
            _optional_str(self.authority_claim, "authority_claim", maximum=64),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_claim": self.authority_claim,
            "authority_kind": self.authority_kind,
            "citation": self.citation,
            "classification": self.classification,
            "corpus_record_id": self.corpus_record_id,
            "document_cid": self.document_cid,
            "document_length": self.document_length,
            "document_sha256": self.document_sha256,
            "family": self.family,
            "field_lengths": dict(self.field_lengths),
            "record_id": self.record_id,
            "source_cid": self.source_cid,
            "source_root_id": self.source_root_id,
            "text_preview": self.text_preview,
            "title": self.title,
            "token_count": self.token_count,
        }

    def to_release_row(self) -> dict[str, Any]:
        """Compact row matching ``bm25_documents`` release features."""
        return {
            "corpus_record_id": self.corpus_record_id,
            "record_id": self.record_id,
            "source_cid": self.source_cid,
            "text_preview": self.text_preview,
            "token_count": self.token_count,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Bm25DocumentRecord":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("document must be a mapping")
        return cls(
            record_id=str(value.get("record_id") or ""),
            corpus_record_id=str(
                value.get("corpus_record_id") or value.get("record_id") or ""
            ),
            source_cid=str(value.get("source_cid") or ""),
            document_cid=str(value.get("document_cid") or ""),
            document_sha256=str(value.get("document_sha256") or ""),
            classification=str(value.get("classification") or "public_official"),
            family=str(value.get("family") or ""),
            title=str(value.get("title") or ""),
            citation=str(value.get("citation") or ""),
            text_preview=str(value.get("text_preview") or ""),
            token_count=int(value.get("token_count") or 0),
            document_length=int(
                value.get("document_length") or value.get("token_count") or 0
            ),
            field_lengths=dict(value.get("field_lengths") or {}),
            source_root_id=str(value.get("source_root_id") or ""),
            authority_kind=str(value.get("authority_kind") or ""),
            authority_claim=str(value.get("authority_claim") or ""),
        )


@dataclass(frozen=True, slots=True)
class Bm25TermRecord:
    """One vocabulary term with document frequency and IDF."""

    term: str
    term_id: int
    document_frequency: int
    corpus_frequency: int
    idf: float
    fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        term = _require_str(self.term, "term", maximum=512)
        term_id = _require_nonneg_int(self.term_id, "term_id")
        document_frequency = _require_nonneg_int(
            self.document_frequency, "document_frequency"
        )
        corpus_frequency = _require_nonneg_int(
            self.corpus_frequency, "corpus_frequency"
        )
        if document_frequency < 1:
            raise OrphanTermError(f"term {term!r} has document_frequency < 1")
        if corpus_frequency < 1:
            raise OrphanTermError(f"term {term!r} has corpus_frequency < 1")
        if not isinstance(self.idf, (int, float)) or isinstance(self.idf, bool):
            raise SchemaValidationError("idf must be a number")
        fields = tuple(
            sorted({str(f).strip() for f in (self.fields or ()) if str(f).strip()})
        )
        object.__setattr__(self, "term", term)
        object.__setattr__(self, "term_id", term_id)
        object.__setattr__(self, "document_frequency", document_frequency)
        object.__setattr__(self, "corpus_frequency", corpus_frequency)
        object.__setattr__(self, "idf", float(self.idf))
        object.__setattr__(self, "fields", fields)

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_frequency": self.corpus_frequency,
            "document_frequency": self.document_frequency,
            "fields": list(self.fields),
            "idf": self.idf,
            "term": self.term,
            "term_id": self.term_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Bm25TermRecord":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("term must be a mapping")
        return cls(
            term=str(value.get("term") or ""),
            term_id=int(value.get("term_id") or 0),
            document_frequency=int(value.get("document_frequency") or 0),
            corpus_frequency=int(value.get("corpus_frequency") or 0),
            idf=float(value.get("idf") or 0.0),
            fields=tuple(value.get("fields") or ()),
        )


@dataclass(frozen=True, slots=True)
class Bm25PostingRecord:
    """One term→document posting with field and TF."""

    term: str
    term_id: int
    document_id: str
    corpus_record_id: str
    field: str
    tf: int
    df: int
    document_length: int
    source_cid: str = ""

    def __post_init__(self) -> None:
        term = _require_str(self.term, "term", maximum=512)
        term_id = _require_nonneg_int(self.term_id, "term_id")
        document_id = _require_record_id(self.document_id, "document_id")
        corpus_record_id = _require_record_id(
            self.corpus_record_id, "corpus_record_id"
        )
        field = _require_str(self.field, "field", maximum=64)
        tf = _require_nonneg_int(self.tf, "tf")
        df = _require_nonneg_int(self.df, "df")
        document_length = _require_nonneg_int(self.document_length, "document_length")
        if tf < 1:
            raise SchemaValidationError(
                f"posting for term {term!r} / document {document_id!r} has tf < 1"
            )
        if df < 1:
            raise SchemaValidationError(
                f"posting for term {term!r} has df < 1"
            )
        source_cid = _optional_str(self.source_cid, "source_cid", maximum=256)
        if source_cid and not _CID_RE.fullmatch(source_cid):
            raise SchemaValidationError(f"source_cid is not a valid CIDv1: {source_cid!r}")
        object.__setattr__(self, "term", term)
        object.__setattr__(self, "term_id", term_id)
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "corpus_record_id", corpus_record_id)
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "tf", tf)
        object.__setattr__(self, "df", df)
        object.__setattr__(self, "document_length", document_length)
        object.__setattr__(self, "source_cid", source_cid)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "corpus_record_id": self.corpus_record_id,
            "df": self.df,
            "document_id": self.document_id,
            "document_length": self.document_length,
            "field": self.field,
            "term": self.term,
            "term_id": self.term_id,
            "tf": self.tf,
        }
        if self.source_cid:
            payload["source_cid"] = self.source_cid
        return payload

    def to_release_row(self) -> dict[str, Any]:
        """Compact row matching ``bm25_postings`` release features."""
        return {
            "df": self.df,
            "document_id": self.document_id,
            "term": self.term,
            "tf": self.tf,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Bm25PostingRecord":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("posting must be a mapping")
        return cls(
            term=str(value.get("term") or ""),
            term_id=int(value.get("term_id") or 0),
            document_id=str(value.get("document_id") or ""),
            corpus_record_id=str(
                value.get("corpus_record_id") or value.get("document_id") or ""
            ),
            field=str(value.get("field") or "description"),
            tf=int(value.get("tf") or value.get("term_frequency") or 0),
            df=int(value.get("df") or value.get("document_frequency") or 0),
            document_length=int(value.get("document_length") or 0),
            source_cid=str(value.get("source_cid") or ""),
        )


@dataclass(frozen=True, slots=True)
class PublicLegalBm25Counts:
    """Aggregate counts bound into the BM25 snapshot manifest."""

    document_count: int
    term_count: int
    posting_count: int
    total_tokens: int
    by_family: Mapping[str, int]
    by_field: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "document_count",
            _require_nonneg_int(self.document_count, "document_count"),
        )
        object.__setattr__(
            self, "term_count", _require_nonneg_int(self.term_count, "term_count")
        )
        object.__setattr__(
            self,
            "posting_count",
            _require_nonneg_int(self.posting_count, "posting_count"),
        )
        object.__setattr__(
            self,
            "total_tokens",
            _require_nonneg_int(self.total_tokens, "total_tokens"),
        )
        object.__setattr__(
            self, "by_family", MappingProxyType(dict(self.by_family or {}))
        )
        object.__setattr__(
            self, "by_field", MappingProxyType(dict(self.by_field or {}))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "by_family": dict(self.by_family),
            "by_field": dict(self.by_field),
            "document_count": self.document_count,
            "posting_count": self.posting_count,
            "term_count": self.term_count,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicLegalBm25Counts":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("counts must be a mapping")
        return cls(
            document_count=int(value.get("document_count") or 0),
            term_count=int(value.get("term_count") or 0),
            posting_count=int(value.get("posting_count") or 0),
            total_tokens=int(value.get("total_tokens") or 0),
            by_family=dict(value.get("by_family") or {}),
            by_field=dict(value.get("by_field") or {}),
        )


def release_packaging_bindings() -> dict[str, Any]:
    """Snapshot schema fragment matching HF / JusticeDAO BM25 packaging."""
    return {
        "configs": [
            {
                "config_name": "bm25_documents",
                "data_files_pattern": RELEASE_DOCUMENTS_PATTERN,
                "description": "BM25 document table joined to public corpus CIDs",
                "features": list(RELEASE_DOCUMENTS_FEATURES),
                "join_fields": list(RELEASE_DOCUMENTS_JOIN_FIELDS),
                "role": RELEASE_ROLE,
            },
            {
                "config_name": "bm25_postings",
                "data_files_pattern": RELEASE_POSTINGS_PATTERN,
                "description": "BM25 postings / dictionary shards",
                "features": list(RELEASE_POSTINGS_FEATURES),
                "join_fields": list(RELEASE_POSTINGS_JOIN_FIELDS),
                "role": RELEASE_ROLE,
            },
        ],
        "repository": RELEASE_REPOSITORY,
        "required_configs": list(RELEASE_CONFIGS),
        "role": RELEASE_ROLE,
    }


@dataclass(frozen=True, slots=True)
class PublicLegalBm25Manifest:
    """Content-addressed BM25 snapshot manifest bound to a corpus root.

    Downstream HF release packaging (PATLAW-174) consumes:
    * ``index_cid`` / ``index_digest_sha256`` as the BM25 pin;
    * ``corpus_root_cid`` as the corpus join pin;
    * ``release_packaging`` for Viewer layout config names / join fields;
    * ``counts`` for parity checks.
    """

    schema_version: str
    interface: str
    task_id: str
    goal_id: str
    producer: str
    config_id: str
    code_version: str
    partition: str
    corpus_root_cid: str
    corpus_digest_sha256: str
    index_cid: str
    index_digest_sha256: str
    tokenizer_version: str
    field_weights: Mapping[str, Any]
    counts: PublicLegalBm25Counts
    average_document_length: float
    k1: float
    b: float
    release_packaging: Mapping[str, Any]
    corpus_document_count: int
    mode: str = BuildMode.DRY_RUN.value
    staged_at_utc: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaValidationError(
                f"unsupported schema_version: {self.schema_version!r}"
            )
        if self.interface != INTERFACE:
            raise SchemaValidationError(f"unsupported interface: {self.interface!r}")
        if self.task_id != TASK_ID:
            raise SchemaValidationError(f"task_id must be {TASK_ID}")
        if self.goal_id != GOAL_ID:
            raise SchemaValidationError(f"goal_id must be {GOAL_ID}")
        if self.partition != "public":
            raise PrivateOrMixedInputError(
                f"partition must be 'public', got {self.partition!r}"
            )
        corpus_root_cid = _require_cid(self.corpus_root_cid, "corpus_root_cid")
        corpus_digest_sha256 = _require_sha256(
            self.corpus_digest_sha256, "corpus_digest_sha256"
        )
        if not isinstance(self.counts, PublicLegalBm25Counts):
            raise SchemaValidationError("counts must be PublicLegalBm25Counts")
        if self.counts.document_count < 1:
            raise SnapshotIntegrityError("document_count must be >= 1")
        if self.counts.term_count < 1:
            raise SnapshotIntegrityError("term_count must be >= 1")
        if self.counts.posting_count < 1:
            raise SnapshotIntegrityError("posting_count must be >= 1")
        packaging = dict(self.release_packaging or {})
        required = set(packaging.get("required_configs") or ())
        if not RELEASE_CONFIGS[0] in required or not RELEASE_CONFIGS[1] in required:
            # Allow empty packaging only if we re-bind defaults below.
            packaging = release_packaging_bindings()
        configs = packaging.get("configs") or []
        config_names = {
            str(item.get("config_name") or "")
            for item in configs
            if isinstance(item, Mapping)
        }
        for name in RELEASE_CONFIGS:
            if name not in config_names:
                raise SchemaValidationError(
                    f"release_packaging missing required config {name!r}"
                )
        object.__setattr__(self, "corpus_root_cid", corpus_root_cid)
        object.__setattr__(self, "corpus_digest_sha256", corpus_digest_sha256)
        object.__setattr__(
            self,
            "tokenizer_version",
            _require_str(self.tokenizer_version, "tokenizer_version", maximum=128),
        )
        object.__setattr__(
            self, "field_weights", MappingProxyType(dict(self.field_weights or {}))
        )
        object.__setattr__(
            self, "release_packaging", MappingProxyType(dict(packaging))
        )
        object.__setattr__(
            self,
            "corpus_document_count",
            _require_nonneg_int(self.corpus_document_count, "corpus_document_count"),
        )
        object.__setattr__(self, "average_document_length", float(self.average_document_length))
        object.__setattr__(self, "k1", float(self.k1))
        object.__setattr__(self, "b", float(self.b))
        # Content address (index pin) over the content body.
        body = self._content_body()
        digest = content_digest_of(body)
        cid = content_cid_of(body)
        if self.index_digest_sha256 and self.index_digest_sha256 != digest:
            raise SnapshotIntegrityError("index_digest_sha256 mismatch")
        if self.index_cid and self.index_cid != cid:
            raise SnapshotIntegrityError("index_cid mismatch")
        object.__setattr__(self, "index_digest_sha256", digest)
        object.__setattr__(self, "index_cid", cid)

    def _content_body(self) -> dict[str, Any]:
        # Mode / staging timestamps intentionally excluded so dry-run and
        # staged builds of the same corpus remain content-address stable.
        return {
            "average_document_length": self.average_document_length,
            "b": self.b,
            "code_version": self.code_version,
            "config_id": self.config_id,
            "corpus_digest_sha256": self.corpus_digest_sha256,
            "corpus_document_count": self.corpus_document_count,
            "corpus_root_cid": self.corpus_root_cid,
            "counts": self.counts.to_dict(),
            "field_weights": dict(self.field_weights),
            "goal_id": self.goal_id,
            "interface": self.interface,
            "k1": self.k1,
            "partition": self.partition,
            "producer": self.producer,
            "release_packaging": dict(self.release_packaging),
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "tokenizer_version": self.tokenizer_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._content_body()
        payload["index_cid"] = self.index_cid
        payload["index_digest_sha256"] = self.index_digest_sha256
        payload["mode"] = self.mode
        if self.staged_at_utc:
            payload["staged_at_utc"] = self.staged_at_utc
        if self.notes:
            payload["notes"] = self.notes
        return payload

    def to_canonical_bytes(self) -> bytes:
        return canonical_json(self.to_dict()).encode("utf-8")

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def to_receipt(self) -> dict[str, Any]:
        """Compact snapshot receipt binding corpus root and index CID."""
        return {
            "corpus_digest_sha256": self.corpus_digest_sha256,
            "corpus_root_cid": self.corpus_root_cid,
            "counts": self.counts.to_dict(),
            "goal_id": self.goal_id,
            "index_cid": self.index_cid,
            "index_digest_sha256": self.index_digest_sha256,
            "interface": self.interface,
            "partition": self.partition,
            "release_packaging": {
                "configs": list(RELEASE_CONFIGS),
                "repository": RELEASE_REPOSITORY,
                "role": RELEASE_ROLE,
            },
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "tokenizer_version": self.tokenizer_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicLegalBm25Manifest":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("manifest must be a mapping")
        return cls(
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            interface=str(value.get("interface") or INTERFACE),
            task_id=str(value.get("task_id") or TASK_ID),
            goal_id=str(value.get("goal_id") or GOAL_ID),
            producer=str(value.get("producer") or PRODUCER),
            config_id=str(value.get("config_id") or CONFIG_ID),
            code_version=str(value.get("code_version") or CODE_VERSION),
            partition=str(value.get("partition") or "public"),
            corpus_root_cid=str(value.get("corpus_root_cid") or ""),
            corpus_digest_sha256=str(value.get("corpus_digest_sha256") or ""),
            index_cid=str(value.get("index_cid") or ""),
            index_digest_sha256=str(value.get("index_digest_sha256") or ""),
            tokenizer_version=str(
                value.get("tokenizer_version") or TOKENIZER_VERSION
            ),
            field_weights=dict(value.get("field_weights") or {}),
            counts=PublicLegalBm25Counts.from_dict(value.get("counts") or {}),
            average_document_length=float(
                value.get("average_document_length") or 0.0
            ),
            k1=float(value.get("k1") if value.get("k1") is not None else DEFAULT_K1),
            b=float(value.get("b") if value.get("b") is not None else DEFAULT_B),
            release_packaging=dict(
                value.get("release_packaging") or release_packaging_bindings()
            ),
            corpus_document_count=int(value.get("corpus_document_count") or 0),
            mode=str(value.get("mode") or BuildMode.DRY_RUN.value),
            staged_at_utc=str(value.get("staged_at_utc") or ""),
            notes=str(value.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class PublicLegalBm25Snapshot:
    """Full BM25 snapshot: documents, terms, postings, and binding manifest."""

    documents: tuple[Bm25DocumentRecord, ...]
    terms: tuple[Bm25TermRecord, ...]
    postings: tuple[Bm25PostingRecord, ...]
    manifest: PublicLegalBm25Manifest
    mode: BuildMode = BuildMode.DRY_RUN
    output_dir: Optional[str] = None

    def __post_init__(self) -> None:
        verify_zero_orphans(
            documents=self.documents,
            terms=self.terms,
            postings=self.postings,
            corpus_document_count=self.manifest.corpus_document_count,
        )
        if len(self.documents) != self.manifest.counts.document_count:
            raise SnapshotIntegrityError(
                "document count does not match manifest counts"
            )
        if len(self.terms) != self.manifest.counts.term_count:
            raise SnapshotIntegrityError("term count does not match manifest counts")
        if len(self.postings) != self.manifest.counts.posting_count:
            raise SnapshotIntegrityError(
                "posting count does not match manifest counts"
            )
        if self.manifest.corpus_root_cid == "":
            raise CorpusPinError("snapshot requires corpus_root_cid pin")

    @property
    def index_cid(self) -> str:
        return self.manifest.index_cid

    @property
    def index_digest_sha256(self) -> str:
        return self.manifest.index_digest_sha256

    @property
    def corpus_root_cid(self) -> str:
        return self.manifest.corpus_root_cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_root_cid": self.corpus_root_cid,
            "documents": [d.to_dict() for d in self.documents],
            "index_cid": self.index_cid,
            "index_digest_sha256": self.index_digest_sha256,
            "manifest": self.manifest.to_dict(),
            "mode": self.mode.value
            if isinstance(self.mode, BuildMode)
            else str(self.mode),
            "output_dir": self.output_dir,
            "postings": [p.to_dict() for p in self.postings],
            "terms": [t.to_dict() for t in self.terms],
        }

    def to_canonical_bytes(self) -> bytes:
        # Content address excludes output_dir and mode presentation noise.
        manifest_body = self.manifest._content_body()
        manifest_body["index_cid"] = self.manifest.index_cid
        manifest_body["index_digest_sha256"] = self.manifest.index_digest_sha256
        payload = {
            "documents": [d.to_dict() for d in self.documents],
            "manifest": manifest_body,
            "postings": [p.to_dict() for p in self.postings],
            "terms": [t.to_dict() for t in self.terms],
        }
        return canonical_json(payload).encode("utf-8")

    def release_document_rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(d.to_release_row() for d in self.documents)

    def release_posting_rows(self) -> tuple[dict[str, Any], ...]:
        # Collapse fielded postings to release shape (term, document_id, tf, df)
        # by summing TF across fields for the same (term, document_id).
        collapsed: dict[tuple[str, str], dict[str, Any]] = {}
        for posting in self.postings:
            key = (posting.term, posting.document_id)
            existing = collapsed.get(key)
            if existing is None:
                collapsed[key] = {
                    "df": posting.df,
                    "document_id": posting.document_id,
                    "term": posting.term,
                    "tf": posting.tf,
                }
            else:
                existing["tf"] = int(existing["tf"]) + int(posting.tf)
                # df is term-level and must agree.
                if int(existing["df"]) != int(posting.df):
                    raise SnapshotIntegrityError(
                        f"df mismatch for term {posting.term!r}"
                    )
        return tuple(
            collapsed[key]
            for key in sorted(collapsed.keys(), key=lambda k: (k[0], k[1]))
        )


# ---------------------------------------------------------------------------
# Integrity gates
# ---------------------------------------------------------------------------


def verify_zero_orphans(
    *,
    documents: Sequence[Bm25DocumentRecord],
    terms: Sequence[Bm25TermRecord],
    postings: Sequence[Bm25PostingRecord],
    corpus_document_count: int | None = None,
    corpus_record_ids: Sequence[str] | None = None,
) -> None:
    """Fail closed on orphan terms, postings, or corpus joins.

    * Every posting.document_id must exist in documents.
    * Every term must appear in at least one posting.
    * Every posting.term must exist in the term vocabulary.
    * Every document must have at least one posting.
    * When *corpus_record_ids* is provided, every document.corpus_record_id
      must be in that set (and vice-versa when counts match).
    """
    if not documents:
        raise SnapshotIntegrityError("BM25 snapshot requires at least one document")
    if not terms:
        raise SnapshotIntegrityError("BM25 snapshot requires at least one term")
    if not postings:
        raise SnapshotIntegrityError("BM25 snapshot requires at least one posting")

    doc_ids = {d.record_id for d in documents}
    if len(doc_ids) != len(documents):
        raise SchemaValidationError("duplicate BM25 document record_id")
    term_ids = {t.term for t in terms}
    if len(term_ids) != len(terms):
        raise SchemaValidationError("duplicate BM25 term")
    term_id_by_term = {t.term: t.term_id for t in terms}

    corpus_ids = {d.corpus_record_id for d in documents}
    if corpus_record_ids is not None:
        allowed = set(corpus_record_ids)
        orphans = sorted(corpus_ids - allowed)
        if orphans:
            raise OrphanDocumentError(
                "BM25 documents do not join corpus record_ids: "
                + ", ".join(orphans[:8])
            )
        # Every corpus record should have a BM25 document when counts match.
        if corpus_document_count is not None and corpus_document_count == len(allowed):
            missing = sorted(allowed - corpus_ids)
            if missing:
                raise OrphanDocumentError(
                    "corpus records missing BM25 documents: "
                    + ", ".join(missing[:8])
                )

    for doc in documents:
        if not doc.source_cid or not doc.document_cid:
            raise OrphanDocumentError(
                f"document {doc.record_id!r} missing source/document CID join"
            )

    postings_doc_ids: set[str] = set()
    postings_terms: set[str] = set()
    for posting in postings:
        if posting.document_id not in doc_ids:
            raise OrphanPostingError(
                f"posting term={posting.term!r} document_id="
                f"{posting.document_id!r} is not in bm25 documents (orphan)"
            )
        if posting.term not in term_ids:
            raise OrphanTermError(
                f"posting term={posting.term!r} is not in vocabulary (orphan)"
            )
        expected_tid = term_id_by_term[posting.term]
        if posting.term_id != expected_tid:
            raise SnapshotIntegrityError(
                f"posting term_id mismatch for {posting.term!r}: "
                f"{posting.term_id} != {expected_tid}"
            )
        if posting.corpus_record_id not in corpus_ids:
            raise OrphanPostingError(
                f"posting document_id={posting.document_id!r} "
                f"corpus_record_id={posting.corpus_record_id!r} is orphan"
            )
        postings_doc_ids.add(posting.document_id)
        postings_terms.add(posting.term)

    orphan_docs = sorted(doc_ids - postings_doc_ids)
    if orphan_docs:
        raise OrphanDocumentError(
            "BM25 documents with no postings: " + ", ".join(orphan_docs[:8])
        )
    orphan_terms = sorted(term_ids - postings_terms)
    if orphan_terms:
        raise OrphanTermError(
            "vocabulary terms with no postings: " + ", ".join(orphan_terms[:8])
        )


def verify_release_packaging_schema(manifest: PublicLegalBm25Manifest) -> dict[str, Any]:
    """Assert snapshot release_packaging matches HF layout expectations."""
    packaging = dict(manifest.release_packaging)
    if packaging.get("role") != RELEASE_ROLE:
        raise SchemaValidationError(
            f"release role must be {RELEASE_ROLE!r}, got {packaging.get('role')!r}"
        )
    if packaging.get("repository") != RELEASE_REPOSITORY:
        raise SchemaValidationError(
            f"release repository must be {RELEASE_REPOSITORY!r}"
        )
    required = set(packaging.get("required_configs") or ())
    for name in RELEASE_CONFIGS:
        if name not in required:
            raise SchemaValidationError(
                f"required release config missing: {name!r}"
            )
    by_name = {
        str(item.get("config_name")): item
        for item in (packaging.get("configs") or [])
        if isinstance(item, Mapping)
    }
    docs_cfg = by_name.get("bm25_documents") or {}
    post_cfg = by_name.get("bm25_postings") or {}
    for field in RELEASE_DOCUMENTS_JOIN_FIELDS:
        if field not in (docs_cfg.get("join_fields") or []):
            raise SchemaValidationError(
                f"bm25_documents join_fields missing {field!r}"
            )
    for field in RELEASE_POSTINGS_JOIN_FIELDS:
        if field not in (post_cfg.get("join_fields") or []):
            raise SchemaValidationError(
                f"bm25_postings join_fields missing {field!r}"
            )
    if docs_cfg.get("data_files_pattern") != RELEASE_DOCUMENTS_PATTERN:
        raise SchemaValidationError(
            "bm25_documents data_files_pattern does not match release layout"
        )
    if post_cfg.get("data_files_pattern") != RELEASE_POSTINGS_PATTERN:
        raise SchemaValidationError(
            "bm25_postings data_files_pattern does not match release layout"
        )
    return {
        "configs": list(RELEASE_CONFIGS),
        "ok": True,
        "repository": RELEASE_REPOSITORY,
        "role": RELEASE_ROLE,
    }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@dataclass
class PublicLegalBm25Builder:
    """Build a production BM25 index snapshot from a public legal corpus.

    Parameters
    ----------
    k1, b:
        Okapi BM25 parameters recorded in the snapshot (scoring uses the same).
    field_weights:
        Optional field-weight config; defaults to patent legal field weights.
    code_version:
        Builder code pin recorded in the manifest.
    """

    k1: float = DEFAULT_K1
    b: float = DEFAULT_B
    field_weights: FieldWeightConfig | None = None
    code_version: str = CODE_VERSION
    tenant_id: str = DEFAULT_TENANT_ID

    def build(
        self,
        materialization: PublicLegalCorpusMaterialization,
        *,
        stage: bool = False,
        output_dir: PathLike | None = None,
        notes: str = "",
        expected_corpus_root_cid: str | None = None,
    ) -> PublicLegalBm25Snapshot:
        """Build a BM25 snapshot from an admitted public legal materialization."""
        if not isinstance(materialization, PublicLegalCorpusMaterialization):
            raise SchemaValidationError(
                "materialization must be PublicLegalCorpusMaterialization"
            )
        assert_public_only_documents(materialization.documents)
        corpus_root_cid = materialization.corpus_root_cid
        corpus_digest = materialization.corpus_digest_sha256
        if expected_corpus_root_cid is not None:
            expected = _require_cid(expected_corpus_root_cid, "expected_corpus_root_cid")
            if expected != corpus_root_cid:
                raise CorpusPinError(
                    f"corpus_root_cid pin mismatch: expected {expected}, "
                    f"got {corpus_root_cid}"
                )
        if not corpus_root_cid or not corpus_digest:
            raise CorpusPinError("materialization missing corpus root pin")

        weights = self.field_weights or FieldWeightConfig.default(
            config_cid=None
        )
        # Force k1/b from builder settings for stable pins.
        weights = FieldWeightConfig.from_dict(
            {
                **weights.to_dict(),
                "k1": self.k1,
                "b": self.b,
            }
        )

        corpus_docs = tuple(
            sorted(materialization.documents, key=lambda d: d.record_id)
        )
        corpus_record_ids = [d.record_id for d in corpus_docs]
        if len(corpus_record_ids) != len(set(corpus_record_ids)):
            raise SchemaValidationError("duplicate corpus record_id")

        # ---- tokenize ----
        prepared: list[
            tuple[PublicLegalDocument, dict[str, Counter[str]], int]
        ] = []
        for doc in corpus_docs:
            try:
                classification = doc.classification
                if is_private_disclosure(classification) or classification not in {
                    DisclosureClass.PUBLIC_OFFICIAL.value,
                    DisclosureClass.PUBLIC_USER.value,
                    "public_official",
                    "public_user",
                }:
                    raise PrivateOrMixedInputError(
                        f"document {doc.record_id!r} classification "
                        f"{classification!r} fails closed"
                    )
            except PrivateOrMixedInputError:
                raise
            field_counts, total_tokens, _used = public_legal_document_to_tokens(doc)
            if total_tokens < 1 or not field_counts:
                raise SchemaValidationError(
                    f"document {doc.record_id!r} produced no BM25 tokens"
                )
            prepared.append((doc, field_counts, total_tokens))

        document_count = len(prepared)
        if document_count < 1:
            raise SnapshotIntegrityError("no documents admitted for BM25 indexing")

        # ---- document frequency (term appears in doc if any field has it) ----
        doc_df: Counter[str] = Counter()
        corpus_tf: Counter[str] = Counter()
        term_fields: dict[str, set[str]] = defaultdict(set)
        for _doc, field_counts, _total in prepared:
            terms_in_doc: set[str] = set()
            for field_name, counts in field_counts.items():
                for term, tf in counts.items():
                    terms_in_doc.add(term)
                    corpus_tf[term] += int(tf)
                    term_fields[term].add(field_name)
            doc_df.update(terms_in_doc)

        vocabulary = sorted(doc_df.keys())
        if not vocabulary:
            raise SnapshotIntegrityError("empty BM25 vocabulary")
        term_id_by_value = {term: idx for idx, term in enumerate(vocabulary)}

        term_records: list[Bm25TermRecord] = []
        for term in vocabulary:
            df = int(doc_df[term])
            term_records.append(
                Bm25TermRecord(
                    term=term,
                    term_id=term_id_by_value[term],
                    document_frequency=df,
                    corpus_frequency=int(corpus_tf[term]),
                    idf=_idf(document_count, df),
                    fields=tuple(sorted(term_fields[term])),
                )
            )

        # ---- documents + postings ----
        document_records: list[Bm25DocumentRecord] = []
        posting_records: list[Bm25PostingRecord] = []
        family_counts: Counter[str] = Counter()
        field_posting_counts: Counter[str] = Counter()
        total_tokens = 0

        for doc, field_counts, doc_total in prepared:
            family_value = (
                doc.family.value if hasattr(doc.family, "value") else str(doc.family)
            )
            family_counts[family_value] += 1
            total_tokens += doc_total
            field_lengths = {
                fname: int(sum(counts.values()))
                for fname, counts in field_counts.items()
            }
            preview_source = " ".join(
                part
                for part in (doc.title, doc.citation, doc.text)
                if part
            )
            document_records.append(
                Bm25DocumentRecord(
                    record_id=doc.record_id,
                    corpus_record_id=doc.record_id,
                    source_cid=doc.source_cid,
                    document_cid=doc.document_cid,
                    document_sha256=doc.document_sha256,
                    classification=doc.classification,
                    family=family_value,
                    title=doc.title,
                    citation=doc.citation,
                    text_preview=_text_preview(preview_source),
                    token_count=doc_total,
                    document_length=doc_total,
                    field_lengths=field_lengths,
                    source_root_id=doc.source_root_id,
                    authority_kind=doc.authority_kind,
                    authority_claim=(
                        doc.authority_claim.value
                        if hasattr(doc.authority_claim, "value")
                        else str(doc.authority_claim)
                    ),
                )
            )
            for field_name, counts in sorted(field_counts.items()):
                for term, tf in sorted(counts.items()):
                    term_id = term_id_by_value[term]
                    df = int(doc_df[term])
                    posting_records.append(
                        Bm25PostingRecord(
                            term=term,
                            term_id=term_id,
                            document_id=doc.record_id,
                            corpus_record_id=doc.record_id,
                            field=field_name,
                            tf=int(tf),
                            df=df,
                            document_length=doc_total,
                            source_cid=doc.source_cid,
                        )
                    )
                    field_posting_counts[field_name] += 1

        posting_records.sort(
            key=lambda p: (p.term_id, p.document_id, p.field, p.term)
        )
        document_records.sort(key=lambda d: d.record_id)
        term_records.sort(key=lambda t: t.term_id)

        verify_zero_orphans(
            documents=document_records,
            terms=term_records,
            postings=posting_records,
            corpus_document_count=len(corpus_docs),
            corpus_record_ids=corpus_record_ids,
        )

        avgdl = total_tokens / max(1, document_count)
        counts = PublicLegalBm25Counts(
            document_count=len(document_records),
            term_count=len(term_records),
            posting_count=len(posting_records),
            total_tokens=total_tokens,
            by_family=dict(sorted(family_counts.items())),
            by_field=dict(sorted(field_posting_counts.items())),
        )

        mode = BuildMode.STAGE if stage else BuildMode.DRY_RUN
        manifest = PublicLegalBm25Manifest(
            schema_version=SCHEMA_VERSION,
            interface=INTERFACE,
            task_id=TASK_ID,
            goal_id=GOAL_ID,
            producer=PRODUCER,
            config_id=CONFIG_ID,
            code_version=self.code_version,
            partition="public",
            corpus_root_cid=corpus_root_cid,
            corpus_digest_sha256=corpus_digest,
            index_cid="",
            index_digest_sha256="",
            tokenizer_version=TOKENIZER_VERSION,
            field_weights=weights.to_dict(),
            counts=counts,
            average_document_length=avgdl,
            k1=float(weights.k1),
            b=float(weights.b),
            release_packaging=release_packaging_bindings(),
            corpus_document_count=len(corpus_docs),
            mode=mode.value,
            notes=str(notes or ""),
        )
        verify_release_packaging_schema(manifest)

        snapshot = PublicLegalBm25Snapshot(
            documents=tuple(document_records),
            terms=tuple(term_records),
            postings=tuple(posting_records),
            manifest=manifest,
            mode=mode,
            output_dir=None,
        )

        if stage:
            if output_dir is None:
                raise PublicLegalBm25Error(
                    "output_dir is required when stage=True",
                    code="missing_output_dir",
                )
            return self.stage(snapshot, output_dir=output_dir)
        return snapshot

    def build_from_corpus_dir(
        self,
        corpus_dir: PathLike,
        *,
        stage: bool = False,
        output_dir: PathLike | None = None,
        notes: str = "",
        expected_corpus_root_cid: str | None = None,
    ) -> PublicLegalBm25Snapshot:
        """Load a staged public legal corpus directory and build BM25."""
        materialization = load_corpus_materialization(corpus_dir)
        return self.build(
            materialization,
            stage=stage,
            output_dir=output_dir,
            notes=notes,
            expected_corpus_root_cid=expected_corpus_root_cid,
        )

    def build_from_recipe(
        self,
        recipe: Mapping[str, Any] | None = None,
        *,
        require_all_families: bool = True,
        stage: bool = False,
        output_dir: PathLike | None = None,
        notes: str = "",
        expected_corpus_root_cid: str | None = None,
    ) -> PublicLegalBm25Snapshot:
        """Materialize a public legal corpus from *recipe* and build BM25."""
        recipe_payload = recipe or build_default_public_legal_recipe()
        materializer = PublicLegalCorpusMaterializer(
            require_all_families=require_all_families
        )
        materialization = materializer.materialize_from_recipe(recipe_payload)
        return self.build(
            materialization,
            stage=stage,
            output_dir=output_dir,
            notes=notes,
            expected_corpus_root_cid=expected_corpus_root_cid,
        )

    def stage(
        self,
        snapshot: PublicLegalBm25Snapshot,
        *,
        output_dir: PathLike,
    ) -> PublicLegalBm25Snapshot:
        """Write BM25 artifacts to *output_dir* atomically."""
        verify_zero_orphans(
            documents=snapshot.documents,
            terms=snapshot.terms,
            postings=snapshot.postings,
            corpus_document_count=snapshot.manifest.corpus_document_count,
        )
        verify_release_packaging_schema(snapshot.manifest)

        root = Path(output_dir)
        _ensure_dir(root)

        documents_blob = (
            "\n".join(canonical_json(d.to_dict()) for d in snapshot.documents) + "\n"
        ).encode("utf-8")
        terms_blob = (
            "\n".join(canonical_json(t.to_dict()) for t in snapshot.terms) + "\n"
        ).encode("utf-8")
        postings_blob = (
            "\n".join(canonical_json(p.to_dict()) for p in snapshot.postings) + "\n"
        ).encode("utf-8")

        manifest_payload = snapshot.manifest.to_dict()
        receipt = snapshot.manifest.to_receipt()
        index_root = {
            "corpus_root_cid": snapshot.corpus_root_cid,
            "counts": snapshot.manifest.counts.to_dict(),
            "index_cid": snapshot.index_cid,
            "index_digest_sha256": snapshot.index_digest_sha256,
            "release_packaging": {
                "configs": list(RELEASE_CONFIGS),
                "repository": RELEASE_REPOSITORY,
                "role": RELEASE_ROLE,
            },
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
            "tokenizer_version": snapshot.manifest.tokenizer_version,
        }

        _atomic_write_text(
            root / MANIFEST_FILENAME, canonical_json(manifest_payload) + "\n"
        )
        _atomic_write_bytes(root / DOCUMENTS_FILENAME, documents_blob)
        _atomic_write_bytes(root / TERMS_FILENAME, terms_blob)
        _atomic_write_bytes(root / POSTINGS_FILENAME, postings_blob)
        _atomic_write_text(
            root / RECEIPT_FILENAME, canonical_json(receipt) + "\n"
        )
        _atomic_write_text(
            root / INDEX_ROOT_FILENAME, canonical_json(index_root) + "\n"
        )

        return PublicLegalBm25Snapshot(
            documents=snapshot.documents,
            terms=snapshot.terms,
            postings=snapshot.postings,
            manifest=snapshot.manifest,
            mode=BuildMode.STAGE,
            output_dir=str(root.resolve()),
        )


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_corpus_materialization(
    corpus_dir: PathLike,
) -> PublicLegalCorpusMaterialization:
    """Load a staged public legal corpus directory into a materialization."""
    root = Path(corpus_dir)
    if not root.is_dir():
        raise PublicLegalBm25Error(f"corpus directory not found: {root}")
    manifest_path = root / CORPUS_MANIFEST_FILENAME
    documents_path = root / CORPUS_DOCUMENTS_FILENAME
    if not manifest_path.is_file():
        raise PublicLegalBm25Error(f"corpus manifest not found: {manifest_path}")
    if not documents_path.is_file():
        raise PublicLegalBm25Error(f"corpus documents not found: {documents_path}")
    try:
        manifest = load_corpus_manifest(manifest_path)
    except PublicLegalCorpusError as exc:
        raise PublicLegalBm25Error(f"invalid corpus manifest: {exc}") from exc
    docs: list[PublicLegalDocument] = []
    for line_no, line in enumerate(
        documents_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PublicLegalBm25Error(
                f"invalid documents.jsonl on line {line_no}: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise PublicLegalBm25Error(
                f"documents.jsonl line {line_no} must be an object"
            )
        docs.append(PublicLegalDocument.from_dict(payload))
    docs_sorted = tuple(sorted(docs, key=lambda d: d.record_id))
    try:
        assert_public_only_documents(docs_sorted)
    except CorpusPrivateOrMixedInputError as exc:
        raise PrivateOrMixedInputError(str(exc)) from exc
    mode_raw = str(manifest.mode or MaterializationMode.STAGE.value)
    try:
        mode = MaterializationMode(mode_raw)
    except ValueError:
        mode = MaterializationMode.STAGE
    materialization = PublicLegalCorpusMaterialization(
        documents=docs_sorted,
        manifest=manifest,
        mode=mode,
        output_dir=str(root.resolve()),
    )
    return materialization


def load_bm25_manifest(path: PathLike) -> PublicLegalBm25Manifest:
    """Load and validate a staged BM25 snapshot manifest."""
    target = Path(path)
    if not target.is_file():
        raise PublicLegalBm25Error(f"manifest not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PublicLegalBm25Error(f"invalid manifest JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PublicLegalBm25Error("manifest must be a JSON object")
    return PublicLegalBm25Manifest.from_dict(payload)


def load_bm25_snapshot(snapshot_dir: PathLike) -> PublicLegalBm25Snapshot:
    """Load a staged BM25 snapshot directory."""
    root = Path(snapshot_dir)
    if not root.is_dir():
        raise PublicLegalBm25Error(f"snapshot directory not found: {root}")
    manifest = load_bm25_manifest(root / MANIFEST_FILENAME)

    def _load_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
        if not path.is_file():
            raise PublicLegalBm25Error(f"{label} not found: {path}")
        rows: list[dict[str, Any]] = []
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PublicLegalBm25Error(
                    f"{label} invalid JSONL on line {line_no}: {exc}"
                ) from exc
            if not isinstance(value, Mapping):
                raise PublicLegalBm25Error(
                    f"{label} line {line_no} must be an object"
                )
            rows.append(dict(value))
        return rows

    documents = tuple(
        Bm25DocumentRecord.from_dict(row)
        for row in _load_jsonl(root / DOCUMENTS_FILENAME, "documents")
    )
    terms = tuple(
        Bm25TermRecord.from_dict(row)
        for row in _load_jsonl(root / TERMS_FILENAME, "terms")
    )
    postings = tuple(
        Bm25PostingRecord.from_dict(row)
        for row in _load_jsonl(root / POSTINGS_FILENAME, "postings")
    )
    return PublicLegalBm25Snapshot(
        documents=documents,
        terms=terms,
        postings=postings,
        manifest=manifest,
        mode=BuildMode.STAGE,
        output_dir=str(root.resolve()),
    )


def validate_snapshot(snapshot: PublicLegalBm25Snapshot) -> dict[str, Any]:
    """Return a structured validation receipt for a BM25 snapshot."""
    verify_zero_orphans(
        documents=snapshot.documents,
        terms=snapshot.terms,
        postings=snapshot.postings,
        corpus_document_count=snapshot.manifest.corpus_document_count,
        corpus_record_ids=[d.corpus_record_id for d in snapshot.documents],
    )
    packaging = verify_release_packaging_schema(snapshot.manifest)
    # Rebuild from documents alone is not possible without corpus text; prove
    # that re-binding the manifest is content-address stable.
    restored = PublicLegalBm25Manifest.from_dict(snapshot.manifest.to_dict())
    if restored.index_cid != snapshot.index_cid:
        raise SnapshotIntegrityError("manifest round-trip changed index_cid")
    if restored.index_digest_sha256 != snapshot.index_digest_sha256:
        raise SnapshotIntegrityError("manifest round-trip changed digest")
    return {
        "corpus_root_cid": snapshot.corpus_root_cid,
        "document_count": len(snapshot.documents),
        "index_cid": snapshot.index_cid,
        "index_digest_sha256": snapshot.index_digest_sha256,
        "ok": True,
        "partition": "public",
        "posting_count": len(snapshot.postings),
        "release_packaging": packaging,
        "task_id": TASK_ID,
        "term_count": len(snapshot.terms),
        "tokenizer_version": snapshot.manifest.tokenizer_version,
    }


def snapshots_are_byte_identical(
    left: PublicLegalBm25Snapshot,
    right: PublicLegalBm25Snapshot,
) -> bool:
    """Return True when two snapshots share identical content bytes."""
    return left.to_canonical_bytes() == right.to_canonical_bytes()


def build_public_legal_bm25_index(
    materialization: PublicLegalCorpusMaterialization | None = None,
    *,
    recipe: Mapping[str, Any] | None = None,
    corpus_dir: PathLike | None = None,
    stage: bool = False,
    output_dir: PathLike | None = None,
    require_all_families: bool = True,
    notes: str = "",
    expected_corpus_root_cid: str | None = None,
    k1: float = DEFAULT_K1,
    b: float = DEFAULT_B,
) -> PublicLegalBm25Snapshot:
    """Module-level convenience wrapper for :class:`PublicLegalBm25Builder`."""
    builder = PublicLegalBm25Builder(k1=k1, b=b)
    if materialization is not None:
        return builder.build(
            materialization,
            stage=stage,
            output_dir=output_dir,
            notes=notes,
            expected_corpus_root_cid=expected_corpus_root_cid,
        )
    if corpus_dir is not None:
        return builder.build_from_corpus_dir(
            corpus_dir,
            stage=stage,
            output_dir=output_dir,
            notes=notes,
            expected_corpus_root_cid=expected_corpus_root_cid,
        )
    return builder.build_from_recipe(
        recipe,
        require_all_families=require_all_families,
        stage=stage,
        output_dir=output_dir,
        notes=notes,
        expected_corpus_root_cid=expected_corpus_root_cid,
    )


# Alias matching objectives AST query.
BM25IndexSnapshot = PublicLegalBm25Snapshot


__all__ = [
    "BM25IndexSnapshot",
    "CODE_VERSION",
    "CONFIG_ID",
    "DEFAULT_B",
    "DEFAULT_K1",
    "DOCUMENTS_FILENAME",
    "GOAL_ID",
    "INDEX_ROOT_FILENAME",
    "INTERFACE",
    "MANIFEST_FILENAME",
    "POSTINGS_FILENAME",
    "PRODUCER",
    "RECEIPT_FILENAME",
    "RELEASE_CONFIGS",
    "RELEASE_DOCUMENTS_FEATURES",
    "RELEASE_DOCUMENTS_JOIN_FIELDS",
    "RELEASE_DOCUMENTS_PATTERN",
    "RELEASE_POSTINGS_FEATURES",
    "RELEASE_POSTINGS_JOIN_FIELDS",
    "RELEASE_POSTINGS_PATTERN",
    "RELEASE_REPOSITORY",
    "RELEASE_ROLE",
    "SCHEMA_VERSION",
    "TASK_ID",
    "TERMS_FILENAME",
    "Bm25DocumentRecord",
    "Bm25PostingRecord",
    "Bm25TermRecord",
    "BuildMode",
    "CorpusPinError",
    "OrphanDocumentError",
    "OrphanPostingError",
    "OrphanTermError",
    "PrivateOrMixedInputError",
    "PublicLegalBm25Builder",
    "PublicLegalBm25Counts",
    "PublicLegalBm25Error",
    "PublicLegalBm25Manifest",
    "PublicLegalBm25Snapshot",
    "SchemaValidationError",
    "SnapshotIntegrityError",
    "build_public_legal_bm25_index",
    "canonical_json",
    "content_cid_of",
    "content_digest_of",
    "legal_field_values",
    "load_bm25_manifest",
    "load_bm25_snapshot",
    "load_corpus_materialization",
    "public_legal_document_to_tokens",
    "release_packaging_bindings",
    "snapshots_are_byte_identical",
    "validate_snapshot",
    "verify_release_packaging_schema",
    "verify_zero_orphans",
]
