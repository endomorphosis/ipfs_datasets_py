"""US Code field-weighted BM25 release adapter (USCIR-015).

This module is the legal-domain projection between:

* admitted canonical corpus chunks from :mod:`uscode_corpus` (USCIR-008);
* the versioned legal tokenizer from :mod:`uscode_tokenizer` (USCIR-013); and
* the domain-neutral sorted BM25 layout from
  :mod:`ipfs_datasets_py.retrieval.hf_graphrag.bm25` (USCIR-014).

Design invariants
-----------------
* Every **admitted** corpus chunk yields exactly one BM25 document row keyed by
  durable ``entry_cid`` (or chunk CID when that is the retrieval key).
* Fields are tokenized independently with the sealed legal tokenizer:
  ``citation``, ``title``, ``heading``, ``hierarchy``, ``body``, ``note``.
* Field weights and filters are explicit configuration, not silent defaults
  inherited from the legacy ``k1=1.5`` monolith.
* Index root is content-bound to the corpus root (roots reconcile).
* Score explanations report per-field TF, weight, and contribution.
* No network I/O; unit tests use compact sealed recipes only.
* Physical Parquet export is delegated to the shared layout; this module owns
  legal field projection only (no graph edge materialization).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import (
    TOKENIZER_ID,
    TOKENIZER_VERSION,
    TokenizerConfig,
    default_tokenizer_config,
    tokenize_legal_text,
    tokenizer_identity,
)
from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import (
    BM25LayoutConfig,
    BM25LayoutSummary,
    DEFAULT_B as SHARED_DEFAULT_B,
    DEFAULT_K1 as SHARED_DEFAULT_K1,
    bm25_term_score,
    build_bm25_layout,
)

# ---------------------------------------------------------------------------
# Identity / pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uscode-bm25-v1"
FIXTURE_SCHEMA_VERSION: Final = "uscode-bm25-expected-v1"
TASK_ID: Final = "USCIR-015"
GOAL_ID: Final = "USCIR-G040"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"
PRODUCER: Final = "uscode_bm25.py"

# Evaluation defaults (plan §4.4). Explicitly *not* the legacy k1=1.5 values.
DEFAULT_K1: Final = 1.2
DEFAULT_B: Final = 0.75
LEGACY_K1: Final = 1.5
LEGACY_B: Final = 0.75

# Physical dual-channel weights used when projecting into the shared layout.
DEFAULT_SHARED_TITLE_WEIGHT: Final = 5.0
DEFAULT_SHARED_BODY_WEIGHT: Final = 1.0

# Legal multi-field weights (evaluation starting point; USCIR-016 may retune).
DEFAULT_FIELD_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "citation": 8.0,
        "title": 5.0,
        "heading": 4.0,
        "hierarchy": 3.0,
        "body": 1.0,
        "note": 0.5,
    }
)

FIELD_ORDER: Final[tuple[str, ...]] = (
    "citation",
    "title",
    "heading",
    "hierarchy",
    "body",
    "note",
)

# Authority fields project into the shared layout "title" channel.
AUTHORITY_FIELDS: Final[frozenset[str]] = frozenset(
    {"citation", "title", "heading", "hierarchy"}
)
# Content fields project into the shared layout "body" channel.
CONTENT_FIELDS: Final[frozenset[str]] = frozenset({"body", "note"})

MAX_DOCUMENTS: Final = 250_000
MAX_TEXT_CHARACTERS: Final = 8 * 1024 * 1024
MAX_QUERY_TERMS: Final = 64
PRIMARY_KEY: Final = "entry_cid"

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UscodeBm25Error(ValueError):
    """Base error for US Code field-weighted BM25 failures."""

    code: str = "uscode_bm25_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class Bm25ConfigError(UscodeBm25Error):
    """Raised when BM25 configuration is incomplete or invalid."""

    code = "config_invalid"


class Bm25CoverageError(UscodeBm25Error):
    """Raised when admitted chunks and BM25 documents do not reconcile."""

    code = "coverage_invalid"


class Bm25RootReconcileError(UscodeBm25Error):
    """Raised when corpus root and index root do not reconcile."""

    code = "root_reconcile_failed"


class Bm25ProjectionError(UscodeBm25Error):
    """Raised when a legal document cannot be projected into BM25 fields."""

    code = "projection_invalid"


class Bm25FixtureError(UscodeBm25Error):
    """Raised when the sealed BM25 expected fixture is malformed."""

    code = "fixture_invalid"


class Bm25FilterError(UscodeBm25Error):
    """Raised when a search filter is malformed."""

    code = "filter_invalid"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class IndexField(str, Enum):
    """Named legal BM25 fields."""

    CITATION = "citation"
    TITLE = "title"
    HEADING = "heading"
    HIERARCHY = "hierarchy"
    BODY = "body"
    NOTE = "note"

    @classmethod
    def coerce(cls, value: Any) -> "IndexField":
        if isinstance(value, IndexField):
            return value
        text = str(value or "").strip().lower()
        for item in cls:
            if item.value == text:
                return item
        raise Bm25ConfigError(f"unknown BM25 field: {value!r}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Bm25ProjectionError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise Bm25ProjectionError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise Bm25ProjectionError(f"{name} exceeds maximum length {maximum}")
    return text


def _optional_str(value: Any, name: str, *, maximum: int = 4096) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name, maximum=maximum)


def _require_positive_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Bm25ConfigError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise Bm25ConfigError(f"{name} must be a positive finite number")
    return number


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Bm25ConfigError(f"{name} must be a non-negative integer")
    return value


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding for content addressing."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_sha256(value: Any) -> str:
    """SHA-256 hex of the canonical JSON (or raw bytes/str) of *value*."""

    if isinstance(value, (bytes, bytearray)):
        payload = bytes(value)
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def content_cid(value: Any) -> str:
    """Stable ``sha256:<hex>`` content address for roots and receipts."""

    return "sha256:" + content_sha256(value)


def legacy_parameter_delta() -> dict[str, Any]:
    """Explicit comparison of evaluation defaults vs legacy monolith values.

    The pinned baseline ``laws_bm25.parquet`` used ``k1=1.5``, ``b=0.75`` with
    un-fielded document term arrays. The v2 plan starts evaluation at
    ``k1=1.2``, ``b=0.75`` with declared multi-field weights. Differences are
    recorded here so they are never silently inherited.
    """

    return {
        "b": {
            "evaluation_default": DEFAULT_B,
            "legacy": LEGACY_B,
            "delta": DEFAULT_B - LEGACY_B,
            "changed": not math.isclose(DEFAULT_B, LEGACY_B, abs_tol=0.0),
        },
        "k1": {
            "evaluation_default": DEFAULT_K1,
            "legacy": LEGACY_K1,
            "delta": DEFAULT_K1 - LEGACY_K1,
            "changed": not math.isclose(DEFAULT_K1, LEGACY_K1, abs_tol=0.0),
        },
        "legacy_field_separation": False,
        "legacy_tokenizer_identity": None,
        "notes": (
            "Legacy US Code BM25 used k1=1.5 with a single unweighted term "
            "array and no tokenizer identity. Evaluation defaults use k1=1.2, "
            "explicit multi-field weights, and the sealed legal tokenizer."
        ),
        "shared_layout_defaults": {
            "b": SHARED_DEFAULT_B,
            "k1": SHARED_DEFAULT_K1,
        },
    }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldWeightConfig:
    """Declared per-field BM25 weights for legal documents."""

    citation: float = DEFAULT_FIELD_WEIGHTS["citation"]
    title: float = DEFAULT_FIELD_WEIGHTS["title"]
    heading: float = DEFAULT_FIELD_WEIGHTS["heading"]
    hierarchy: float = DEFAULT_FIELD_WEIGHTS["hierarchy"]
    body: float = DEFAULT_FIELD_WEIGHTS["body"]
    note: float = DEFAULT_FIELD_WEIGHTS["note"]

    def __post_init__(self) -> None:
        for name in FIELD_ORDER:
            object.__setattr__(
                self, name, _require_positive_float(getattr(self, name), name)
            )

    def weight_for(self, field_name: str | IndexField) -> float:
        name = IndexField.coerce(field_name).value
        return float(getattr(self, name))

    def to_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in FIELD_ORDER}

    @property
    def digest(self) -> str:
        return content_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class UscodeBm25Config:
    """Stable legal BM25 indexing and scoring configuration."""

    k1: float = DEFAULT_K1
    b: float = DEFAULT_B
    field_weights: FieldWeightConfig = field(default_factory=FieldWeightConfig)
    tokenizer: TokenizerConfig = field(default_factory=default_tokenizer_config)
    max_documents: int = MAX_DOCUMENTS
    max_text_characters: int = MAX_TEXT_CHARACTERS
    max_query_terms: int = MAX_QUERY_TERMS
    shared_title_weight: float = DEFAULT_SHARED_TITLE_WEIGHT
    shared_body_weight: float = DEFAULT_SHARED_BODY_WEIGHT
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "k1", _require_positive_float(self.k1, "k1"))
        if (
            isinstance(self.b, bool)
            or not isinstance(self.b, (int, float))
            or not math.isfinite(float(self.b))
            or not 0.0 <= float(self.b) <= 1.0
        ):
            raise Bm25ConfigError("b must be finite and between zero and one")
        object.__setattr__(self, "b", float(self.b))
        if not isinstance(self.field_weights, FieldWeightConfig):
            raise Bm25ConfigError("field_weights must be a FieldWeightConfig")
        if not isinstance(self.tokenizer, TokenizerConfig):
            raise Bm25ConfigError("tokenizer must be a TokenizerConfig")
        for name in ("max_documents", "max_text_characters", "max_query_terms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise Bm25ConfigError(f"{name} must be a positive integer")
        object.__setattr__(
            self,
            "shared_title_weight",
            _require_positive_float(self.shared_title_weight, "shared_title_weight"),
        )
        object.__setattr__(
            self,
            "shared_body_weight",
            _require_positive_float(self.shared_body_weight, "shared_body_weight"),
        )
        if self.schema_version != SCHEMA_VERSION:
            raise Bm25ConfigError(
                f"unsupported schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "b": self.b,
            "field_weights": self.field_weights.to_dict(),
            "k1": self.k1,
            "legacy_parameter_delta": legacy_parameter_delta(),
            "max_documents": self.max_documents,
            "max_query_terms": self.max_query_terms,
            "max_text_characters": self.max_text_characters,
            "schema_version": self.schema_version,
            "shared_body_weight": self.shared_body_weight,
            "shared_title_weight": self.shared_title_weight,
            "tokenizer": self.tokenizer.to_dict(),
            "tokenizer_id": self.tokenizer.tokenizer_id,
        }

    @property
    def digest(self) -> str:
        # Exclude wall-clock / free-form notes; pin only scoring surface.
        payload = {
            "b": self.b,
            "field_weights": self.field_weights.to_dict(),
            "k1": self.k1,
            "max_documents": self.max_documents,
            "max_query_terms": self.max_query_terms,
            "max_text_characters": self.max_text_characters,
            "schema_version": self.schema_version,
            "shared_body_weight": self.shared_body_weight,
            "shared_title_weight": self.shared_title_weight,
            "tokenizer_digest": self.tokenizer.digest,
            "tokenizer_id": self.tokenizer.tokenizer_id,
        }
        return content_sha256(payload)


def default_bm25_config() -> UscodeBm25Config:
    """Return the sealed evaluation-default BM25 configuration."""

    return UscodeBm25Config()


# ---------------------------------------------------------------------------
# Document projection
# ---------------------------------------------------------------------------


def _field_text_from_row(row: Mapping[str, Any], field_name: str) -> str:
    """Extract one legal BM25 field from a corpus / chunk row."""

    if not isinstance(row, Mapping):
        raise Bm25ProjectionError("corpus row must be a mapping")

    if field_name == "citation":
        for key in (
            "citation",
            "canonical_citation",
            "citation_text",
            "bluebook",
        ):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        # Synthesize a stable citation when only structured identity is present.
        title = row.get("title")
        section = row.get("section")
        if title is not None and section is not None:
            return f"{title} U.S.C. § {section}"
        legal_id = row.get("legal_id")
        if isinstance(legal_id, str) and legal_id.strip():
            return legal_id.strip()
        return ""

    if field_name == "title":
        for key in ("title_name", "title_text", "title_label"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        title = row.get("title")
        if title is None or title == "":
            return ""
        # Numeric title codes are indexable identity tokens.
        return str(title).strip()

    if field_name == "heading":
        for key in ("heading", "section_heading", "name", "catchline"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    if field_name == "hierarchy":
        parts: list[str] = []
        for key in (
            "subtitle",
            "chapter",
            "subchapter",
            "part",
            "subpart",
            "section",
            "subsection",
            "hierarchy_path",
            "parent_path",
        ):
            value = row.get(key)
            if value is None or value == "":
                continue
            if isinstance(value, (list, tuple)):
                parts.extend(str(item).strip() for item in value if str(item).strip())
            else:
                text = str(value).strip()
                if text:
                    parts.append(text)
        return " / ".join(parts)

    if field_name == "body":
        for key in ("body", "text", "content", "section_text"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    if field_name == "note":
        for key in ("note", "notes", "editorial_note", "source_credit"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, (list, tuple)):
                joined = " ".join(
                    str(item).strip() for item in value if str(item).strip()
                )
                if joined:
                    return joined
        return ""

    raise Bm25ConfigError(f"unknown field {field_name!r}")


def _document_identity(row: Mapping[str, Any], *, position: int) -> str:
    for key in ("entry_cid", "chunk_cid", "record_id", "cid"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if text.lower().startswith("row-"):
                raise Bm25ProjectionError(
                    f"positional identity is forbidden for BM25 documents: {text!r}"
                )
            return text
    raise Bm25ProjectionError(
        f"corpus row {position} is missing durable entry_cid / chunk_cid"
    )


def _is_admitted_row(row: Mapping[str, Any]) -> bool:
    disposition = row.get("disposition")
    if disposition is not None:
        text = str(disposition).strip().lower()
        if text in {"quarantined", "excluded", "replaced", "recovery"}:
            return False
        if text in {"admitted", "admit", "included", "include"}:
            return True
    admission = row.get("admission_status") or row.get("status")
    if admission is not None:
        text = str(admission).strip().lower()
        if text in {"quarantined", "excluded", "rejected"}:
            return False
    # Recovery rows without CIDs never enter BM25.
    if bool(row.get("is_recovery")) or str(row.get("record_type", "")).lower() in {
        "recovery",
        "workflow",
    }:
        return False
    return True


@dataclass(frozen=True, slots=True)
class FieldTokenStream:
    """Token stream for one legal field of one document."""

    field: str
    text: str
    terms: tuple[str, ...]
    weight: float

    @property
    def length(self) -> int:
        return len(self.terms)

    def term_frequencies(self) -> Counter[str]:
        return Counter(self.terms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "length": self.length,
            "term_count": len(set(self.terms)),
            "text_sha256": content_sha256(self.text),
            "weight": self.weight,
        }


@dataclass(frozen=True, slots=True)
class LegalBm25Document:
    """One field-projected BM25 document for an admitted legal chunk."""

    entry_cid: str
    document_index: int
    fields: Mapping[str, FieldTokenStream]
    legal_id: Optional[str] = None
    chunk_cid: Optional[str] = None
    title_code: Optional[str] = None
    section: Optional[str] = None
    record_type: str = "corpus"
    filters: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "entry_cid", _require_non_empty_str(self.entry_cid, "entry_cid")
        )
        object.__setattr__(
            self,
            "document_index",
            _require_non_negative_int(self.document_index, "document_index"),
        )
        if not isinstance(self.fields, Mapping) or not self.fields:
            raise Bm25ProjectionError("document fields must be a non-empty mapping")
        frozen_fields = {
            IndexField.coerce(name).value: stream
            for name, stream in self.fields.items()
        }
        object.__setattr__(self, "fields", MappingProxyType(frozen_fields))
        object.__setattr__(
            self, "filters", MappingProxyType(dict(self.filters or {}))
        )

    @property
    def total_length(self) -> int:
        return sum(stream.length for stream in self.fields.values())

    def field_length(self, field_name: str) -> int:
        stream = self.fields.get(IndexField.coerce(field_name).value)
        return 0 if stream is None else stream.length

    def field_tf(self, field_name: str, term: str) -> int:
        stream = self.fields.get(IndexField.coerce(field_name).value)
        if stream is None:
            return 0
        return int(stream.term_frequencies().get(term, 0))

    def all_terms(self) -> set[str]:
        terms: set[str] = set()
        for stream in self.fields.values():
            terms.update(stream.terms)
        return terms

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_cid": self.chunk_cid,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "fields": {name: stream.to_dict() for name, stream in self.fields.items()},
            "filters": dict(self.filters),
            "legal_id": self.legal_id,
            "record_type": self.record_type,
            "section": self.section,
            "title_code": self.title_code,
            "total_length": self.total_length,
        }

    def to_shared_layout_row(self) -> dict[str, Any]:
        """Project multi-field legal content into shared title/body channels.

        Authority fields are concatenated into ``title``; content fields into
        ``body``. Term tokens are space-joined so the shared layout tokenizer
        receives the already-legal-normalized term stream as plain text.
        """

        authority_terms: list[str] = []
        content_terms: list[str] = []
        for name in FIELD_ORDER:
            stream = self.fields.get(name)
            if stream is None or not stream.terms:
                continue
            if name in AUTHORITY_FIELDS:
                authority_terms.extend(stream.terms)
            else:
                content_terms.extend(stream.terms)
        if not authority_terms and not content_terms:
            raise Bm25ProjectionError(
                f"document has no searchable tokens: {self.entry_cid}"
            )
        # Shared layout requires non-empty body; fall back to authority terms.
        body_terms = content_terms or authority_terms
        title_terms = authority_terms or body_terms[: min(8, len(body_terms))]
        return {
            "authority": "non_authoritative",
            "body": " ".join(body_terms),
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "record_type": self.record_type,
            "title": " ".join(title_terms),
        }


def project_legal_document(
    row: Mapping[str, Any],
    *,
    document_index: int,
    config: UscodeBm25Config | None = None,
) -> LegalBm25Document:
    """Project one admitted corpus row into a multi-field BM25 document."""

    cfg = config or default_bm25_config()
    if not isinstance(cfg, UscodeBm25Config):
        raise Bm25ConfigError("config must be a UscodeBm25Config")
    if not isinstance(row, Mapping):
        raise Bm25ProjectionError("corpus row must be a mapping")
    if not _is_admitted_row(row):
        raise Bm25ProjectionError(
            "non-admitted rows cannot enter the BM25 index",
            code="not_admitted",
        )

    entry_cid = _document_identity(row, position=document_index)
    fields: dict[str, FieldTokenStream] = {}
    for field_name in FIELD_ORDER:
        text = _field_text_from_row(row, field_name)
        if len(text) > cfg.max_text_characters:
            raise Bm25ProjectionError(
                f"field {field_name} exceeds max_text_characters for {entry_cid}"
            )
        if not text:
            terms: tuple[str, ...] = ()
        else:
            result = tokenize_legal_text(text, config=cfg.tokenizer)
            terms = result.indexable_terms
        fields[field_name] = FieldTokenStream(
            field=field_name,
            text=text,
            terms=terms,
            weight=cfg.field_weights.weight_for(field_name),
        )

    if sum(stream.length for stream in fields.values()) <= 0:
        raise Bm25ProjectionError(
            f"document has no searchable tokens: {entry_cid}"
        )

    title_code = row.get("title")
    title_code_str = (
        str(title_code).strip() if title_code is not None and title_code != "" else None
    )
    section = row.get("section")
    section_str = (
        str(section).strip() if section is not None and section != "" else None
    )
    legal_id = _optional_str(row.get("legal_id"), "legal_id", maximum=256)
    chunk_cid = _optional_str(
        row.get("chunk_cid") or row.get("content_cid"),
        "chunk_cid",
        maximum=512,
    )
    filters: dict[str, str] = {}
    if title_code_str:
        filters["title"] = title_code_str
    if section_str:
        filters["section"] = section_str
    if legal_id:
        filters["legal_id"] = legal_id
    release_point = row.get("release_point") or row.get("source_release_point")
    if isinstance(release_point, str) and release_point.strip():
        filters["release_point"] = release_point.strip()

    return LegalBm25Document(
        entry_cid=entry_cid,
        document_index=document_index,
        fields=fields,
        legal_id=legal_id,
        chunk_cid=chunk_cid,
        title_code=title_code_str,
        section=section_str,
        record_type=str(row.get("record_type") or "corpus"),
        filters=filters,
    )


def project_admitted_documents(
    rows: Sequence[Mapping[str, Any]],
    *,
    config: UscodeBm25Config | None = None,
) -> tuple[LegalBm25Document, ...]:
    """Project admitted rows only; skip recovery/excluded/replaced."""

    cfg = config or default_bm25_config()
    if isinstance(rows, (str, bytes, bytearray)) or not isinstance(rows, Sequence):
        raise Bm25ProjectionError("corpus rows must be a sequence of mappings")
    if not rows:
        raise Bm25ProjectionError("corpus rows must not be empty")
    if len(rows) > cfg.max_documents:
        raise Bm25ProjectionError("corpus rows exceed max_documents")

    documents: list[LegalBm25Document] = []
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise Bm25ProjectionError(f"corpus row {position} must be a mapping")
        if not _is_admitted_row(row):
            continue
        documents.append(
            project_legal_document(row, document_index=len(documents), config=cfg)
        )

    if not documents:
        raise Bm25CoverageError("no admitted corpus rows produced BM25 documents")

    identities = [doc.entry_cid for doc in documents]
    if len(set(identities)) != len(identities):
        raise Bm25CoverageError("duplicate entry_cid values among BM25 documents")

    return tuple(documents)


# ---------------------------------------------------------------------------
# In-memory multi-field BM25 index
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldScoreContribution:
    """One field's contribution to a term score."""

    field: str
    tf: int
    weight: float
    field_length: int
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "field_length": self.field_length,
            "score": self.score,
            "tf": self.tf,
            "weight": self.weight,
        }


@dataclass(frozen=True, slots=True)
class TermScoreExplanation:
    """Explainable multi-field score for one query term against one document."""

    term: str
    idf: float
    total_score: float
    field_contributions: tuple[FieldScoreContribution, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_contributions": [item.to_dict() for item in self.field_contributions],
            "idf": self.idf,
            "term": self.term,
            "total_score": self.total_score,
        }


@dataclass(frozen=True, slots=True)
class Bm25Hit:
    """One ranked BM25 hit with explain payload."""

    entry_cid: str
    document_index: int
    score: float
    matched_terms: tuple[str, ...]
    explanations: tuple[TermScoreExplanation, ...]
    filters: Mapping[str, str] = field(default_factory=dict)
    legal_id: Optional[str] = None
    authority: str = "context_only"
    proof_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "explanations": [item.to_dict() for item in self.explanations],
            "filters": dict(self.filters),
            "legal_id": self.legal_id,
            "matched_terms": list(self.matched_terms),
            "proof_authority": self.proof_authority,
            "score": self.score,
        }


@dataclass(frozen=True, slots=True)
class UscodeBm25Index:
    """In-memory field-weighted legal BM25 index bound to a corpus root."""

    documents: tuple[LegalBm25Document, ...]
    config: UscodeBm25Config
    corpus_root_cid: str
    index_root_cid: str
    document_frequency: Mapping[str, int]
    average_document_length: float
    average_field_lengths: Mapping[str, float]
    term_count: int
    token_instance_count: int

    def __post_init__(self) -> None:
        if not self.documents:
            raise Bm25CoverageError("BM25 index requires at least one document")
        object.__setattr__(
            self,
            "document_frequency",
            MappingProxyType(dict(self.document_frequency)),
        )
        object.__setattr__(
            self,
            "average_field_lengths",
            MappingProxyType(dict(self.average_field_lengths)),
        )

    @property
    def document_count(self) -> int:
        return len(self.documents)

    def document_by_cid(self, entry_cid: str) -> LegalBm25Document:
        for document in self.documents:
            if document.entry_cid == entry_cid:
                return document
        raise Bm25CoverageError(f"unknown BM25 document: {entry_cid}")

    def idf(self, term: str) -> float:
        """Robertson-Sparck-Jones IDF with floor at zero."""

        df = int(self.document_frequency.get(term, 0))
        if df <= 0:
            return 0.0
        n = self.document_count
        # Standard positive IDF used by the shared layout export.
        raw = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
        return max(0.0, float(raw))

    def explain_term(
        self,
        document: LegalBm25Document,
        term: str,
    ) -> TermScoreExplanation:
        contributions: list[FieldScoreContribution] = []
        total = 0.0
        idf = self.idf(term)
        for field_name in FIELD_ORDER:
            stream = document.fields.get(field_name)
            if stream is None:
                continue
            tf = int(stream.term_frequencies().get(term, 0))
            if tf <= 0:
                continue
            avg_field_len = float(
                self.average_field_lengths.get(
                    field_name, self.average_document_length
                )
            )
            score = bm25_term_score(
                tf=float(tf),
                idf=idf,
                doc_length=float(stream.length),
                avg_doc_length=max(avg_field_len, 1e-12),
                k1=self.config.k1,
                b=self.config.b,
                field_weight=stream.weight,
            )
            contributions.append(
                FieldScoreContribution(
                    field=field_name,
                    tf=tf,
                    weight=stream.weight,
                    field_length=stream.length,
                    score=score,
                )
            )
            total += score
        return TermScoreExplanation(
            term=term,
            idf=idf,
            total_score=total,
            field_contributions=tuple(contributions),
        )

    def score_document(
        self,
        document: LegalBm25Document,
        query_terms: Sequence[str],
    ) -> tuple[float, tuple[str, ...], tuple[TermScoreExplanation, ...]]:
        explanations: list[TermScoreExplanation] = []
        matched: list[str] = []
        total = 0.0
        seen: set[str] = set()
        for term in query_terms:
            if not term or term in seen:
                continue
            seen.add(term)
            explanation = self.explain_term(document, term)
            if explanation.total_score > 0.0:
                matched.append(term)
                explanations.append(explanation)
                total += explanation.total_score
        return total, tuple(matched), tuple(explanations)

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: Mapping[str, str] | None = None,
    ) -> list[Bm25Hit]:
        """Score all documents for *query* with optional equality filters."""

        if not isinstance(query, str):
            raise Bm25ProjectionError("query must be a string")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise Bm25ConfigError("top_k must be a positive integer")
        tokenized = tokenize_legal_text(query, config=self.config.tokenizer)
        query_terms = tokenized.indexable_terms[: self.config.max_query_terms]
        if not query_terms:
            return []

        active_filters = dict(filters or {})
        for key, value in active_filters.items():
            if not isinstance(key, str) or not key.strip():
                raise Bm25FilterError("filter keys must be non-empty strings")
            if not isinstance(value, str) or not value.strip():
                raise Bm25FilterError(f"filter {key!r} must be a non-empty string")

        hits: list[Bm25Hit] = []
        for document in self.documents:
            if active_filters and not _document_matches_filters(
                document, active_filters
            ):
                continue
            score, matched, explanations = self.score_document(document, query_terms)
            if score <= 0.0:
                continue
            hits.append(
                Bm25Hit(
                    entry_cid=document.entry_cid,
                    document_index=document.document_index,
                    score=score,
                    matched_terms=matched,
                    explanations=explanations,
                    filters=document.filters,
                    legal_id=document.legal_id,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.entry_cid))
        return hits[:top_k]

    def to_manifest_fragment(self) -> dict[str, Any]:
        return {
            "bm25": {
                "average_document_length": self.average_document_length,
                "b": self.config.b,
                "config_digest": self.config.digest,
                "corpus_root_cid": self.corpus_root_cid,
                "document_count": self.document_count,
                "field_weights": self.config.field_weights.to_dict(),
                "index_root_cid": self.index_root_cid,
                "k1": self.config.k1,
                "legacy_parameter_delta": legacy_parameter_delta(),
                "primary_key": PRIMARY_KEY,
                "schema_version": SCHEMA_VERSION,
                "term_count": self.term_count,
                "token_instance_count": self.token_instance_count,
                "tokenizer": tokenizer_identity(self.config.tokenizer),
                "tokenizer_id": TOKENIZER_ID,
                "tokenizer_version": TOKENIZER_VERSION,
            },
            "goal_id": GOAL_ID,
            "producer": PRODUCER,
            "release_profile": RELEASE_PROFILE,
            "task_id": TASK_ID,
        }


def _document_matches_filters(
    document: LegalBm25Document,
    filters: Mapping[str, str],
) -> bool:
    for key, expected in filters.items():
        actual = document.filters.get(key)
        if actual is None:
            # Also allow direct attribute filters.
            if key == "title":
                actual = document.title_code
            elif key == "section":
                actual = document.section
            elif key == "legal_id":
                actual = document.legal_id
            elif key == "entry_cid":
                actual = document.entry_cid
        if actual is None or str(actual) != str(expected):
            return False
    return True


def build_corpus_root_cid(rows: Sequence[Mapping[str, Any]]) -> str:
    """Content-address admitted corpus identities (no full text payload)."""

    admitted: list[dict[str, Any]] = []
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise Bm25ProjectionError(f"corpus row {position} must be a mapping")
        if not _is_admitted_row(row):
            continue
        admitted.append(
            {
                "chunk_cid": row.get("chunk_cid") or row.get("content_cid"),
                "entry_cid": _document_identity(row, position=position),
                "legal_id": row.get("legal_id"),
            }
        )
    admitted.sort(key=lambda item: str(item["entry_cid"]))
    return content_cid(
        {
            "admitted_count": len(admitted),
            "identities": admitted,
            "primary_key": PRIMARY_KEY,
            "schema_version": "uscode-corpus-root/v1",
        }
    )


def build_index_root_cid(
    documents: Sequence[LegalBm25Document],
    *,
    config: UscodeBm25Config,
    corpus_root_cid: str,
) -> str:
    """Content-address the BM25 index surface bound to *corpus_root_cid*."""

    structural = {
        "config_digest": config.digest,
        "corpus_root_cid": corpus_root_cid,
        "documents": [
            {
                "document_index": doc.document_index,
                "entry_cid": doc.entry_cid,
                "field_lengths": {
                    name: doc.field_length(name) for name in FIELD_ORDER
                },
                "legal_id": doc.legal_id,
                "total_length": doc.total_length,
            }
            for doc in documents
        ],
        "schema_version": SCHEMA_VERSION,
        "tokenizer_id": config.tokenizer.tokenizer_id,
    }
    return content_cid(structural)


def build_uscode_bm25_index(
    rows: Sequence[Mapping[str, Any]],
    *,
    config: UscodeBm25Config | None = None,
    corpus_root_cid: str | None = None,
) -> UscodeBm25Index:
    """Build the in-memory field-weighted legal BM25 index."""

    cfg = config or default_bm25_config()
    if not isinstance(cfg, UscodeBm25Config):
        raise Bm25ConfigError("config must be a UscodeBm25Config")

    documents = project_admitted_documents(rows, config=cfg)
    root = corpus_root_cid or build_corpus_root_cid(rows)
    root = _require_non_empty_str(root, "corpus_root_cid", maximum=128)

    df: dict[str, int] = defaultdict(int)
    token_instances = 0
    total_length = 0
    field_length_sums: dict[str, int] = {name: 0 for name in FIELD_ORDER}
    vocabulary: set[str] = set()
    for document in documents:
        total_length += document.total_length
        token_instances += document.total_length
        seen_in_doc: set[str] = set()
        for field_name, stream in document.fields.items():
            field_length_sums[field_name] = field_length_sums.get(
                field_name, 0
            ) + stream.length
            for term in stream.terms:
                vocabulary.add(term)
                if term not in seen_in_doc:
                    df[term] += 1
                    seen_in_doc.add(term)

    n_docs = float(len(documents))
    avgdl = float(total_length) / n_docs
    average_field_lengths = {
        name: float(field_length_sums.get(name, 0)) / n_docs for name in FIELD_ORDER
    }
    index_root = build_index_root_cid(
        documents, config=cfg, corpus_root_cid=root
    )
    index = UscodeBm25Index(
        documents=documents,
        config=cfg,
        corpus_root_cid=root,
        index_root_cid=index_root,
        document_frequency=dict(df),
        average_document_length=avgdl,
        average_field_lengths=average_field_lengths,
        term_count=len(vocabulary),
        token_instance_count=token_instances,
    )
    reconcile_roots(index, expected_corpus_root_cid=root)
    assert_every_admitted_chunk_has_document(rows, index)
    return index


def assert_every_admitted_chunk_has_document(
    rows: Sequence[Mapping[str, Any]],
    index: UscodeBm25Index,
) -> None:
    """Fail closed when admitted rows and BM25 documents diverge."""

    admitted_ids: list[str] = []
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise Bm25CoverageError(f"corpus row {position} must be a mapping")
        if not _is_admitted_row(row):
            continue
        admitted_ids.append(_document_identity(row, position=position))
    index_ids = [doc.entry_cid for doc in index.documents]
    if sorted(admitted_ids) != sorted(index_ids):
        missing = sorted(set(admitted_ids) - set(index_ids))
        extra = sorted(set(index_ids) - set(admitted_ids))
        raise Bm25CoverageError(
            "BM25 documents do not match admitted corpus rows; "
            f"missing={missing[:5]!r} extra={extra[:5]!r}"
        )
    if len(index_ids) != len(set(index_ids)):
        raise Bm25CoverageError("BM25 documents contain duplicate entry_cid values")


def reconcile_roots(
    index: UscodeBm25Index,
    *,
    expected_corpus_root_cid: str,
) -> dict[str, Any]:
    """Prove index root is bound to the expected corpus root."""

    expected = _require_non_empty_str(
        expected_corpus_root_cid, "expected_corpus_root_cid", maximum=128
    )
    if index.corpus_root_cid != expected:
        raise Bm25RootReconcileError(
            "corpus_root_cid mismatch: "
            f"index={index.corpus_root_cid!r} expected={expected!r}"
        )
    recomputed = build_index_root_cid(
        index.documents,
        config=index.config,
        corpus_root_cid=index.corpus_root_cid,
    )
    if recomputed != index.index_root_cid:
        raise Bm25RootReconcileError(
            "index_root_cid does not recompute from documents and corpus root"
        )
    return {
        "corpus_root_cid": index.corpus_root_cid,
        "index_root_cid": index.index_root_cid,
        "reconciled": True,
        "document_count": index.document_count,
    }


# ---------------------------------------------------------------------------
# Shared layout export
# ---------------------------------------------------------------------------


def export_shared_bm25_layout(
    index: UscodeBm25Index,
    output_dir: PathLike,
    *,
    layout_config: BM25LayoutConfig | None = None,
) -> BM25LayoutSummary:
    """Export the legal projection through the shared 4,096-bound BM25 layout.

    Legal multi-field weights remain authoritative for in-memory scoring.
    The shared layout receives dual-channel title/body projections with the
    configured shared channel weights for physical artifact packaging.
    """

    rows = [document.to_shared_layout_row() for document in index.documents]
    cfg = layout_config or BM25LayoutConfig(
        k1=index.config.k1,
        b=index.config.b,
        title_weight=index.config.shared_title_weight,
        body_weight=index.config.shared_body_weight,
        max_documents=index.config.max_documents,
        max_text_characters=index.config.max_text_characters,
        max_query_terms=index.config.max_query_terms,
    )
    return build_bm25_layout(rows, output_dir, config=cfg)


# ---------------------------------------------------------------------------
# Fixture recipe (compact; no bulk golden dumps)
# ---------------------------------------------------------------------------


def _sample_corpus_rows() -> list[dict[str, Any]]:
    """Compact admitted corpus sample for sealed unit fixtures."""

    return [
        {
            "entry_cid": "sha256:" + ("a" * 64),
            "chunk_cid": "sha256:" + ("b" * 64),
            "legal_id": "usc:us:5:552",
            "title": "5",
            "section": "552",
            "heading": "Public information; agency rules, opinions, orders, records, and proceedings",
            "chapter": "5",
            "citation": "5 U.S.C. § 552",
            "body": (
                "Each agency shall make available to the public information "
                "as follows: final opinions and orders made in the adjudication "
                "of cases."
            ),
            "note": "Known as the Freedom of Information Act.",
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("c" * 64),
            "chunk_cid": "sha256:" + ("d" * 64),
            "legal_id": "usc:us:5:552a",
            "title": "5",
            "section": "552a",
            "heading": "Records maintained on individuals",
            "chapter": "5",
            "citation": "5 U.S.C. § 552a",
            "body": (
                "No agency shall disclose any record which is contained in a "
                "system of records by any means of communication to any person."
            ),
            "note": "Privacy Act of 1974.",
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("e" * 64),
            "chunk_cid": "sha256:" + ("f" * 64),
            "legal_id": "usc:us:35:101",
            "title": "35",
            "section": "101",
            "heading": "Inventions patentable",
            "chapter": "10",
            "citation": "35 U.S.C. § 101",
            "body": (
                "Whoever invents or discovers any new and useful process, "
                "machine, manufacture, or composition of matter may obtain a patent."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("1" * 64),
            "chunk_cid": "sha256:" + ("2" * 64),
            "legal_id": "usc:us:35:103",
            "title": "35",
            "section": "103",
            "heading": "Conditions for patentability; non-obvious subject matter",
            "chapter": "10",
            "citation": "35 U.S.C. § 103",
            "body": (
                "A patent for a claimed invention may not be obtained if the "
                "differences between the claimed invention and the prior art "
                "would have been obvious."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("3" * 64),
            "chunk_cid": "sha256:" + ("4" * 64),
            "legal_id": "usc:us:17:107",
            "title": "17",
            "section": "107",
            "heading": "Limitations on exclusive rights: Fair use",
            "chapter": "1",
            "citation": "17 U.S.C. § 107",
            "body": (
                "Notwithstanding the provisions of sections 106 and 106A, the "
                "fair use of a copyrighted work is not an infringement of copyright."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        # Non-admitted rows must never produce BM25 documents.
        {
            "entry_cid": "",
            "row_id": "recovery-src-01",
            "disposition": "quarantined",
            "is_recovery": True,
            "body": "workflow recovery payload must not enter BM25",
        },
        {
            "entry_cid": "sha256:" + ("9" * 64),
            "disposition": "excluded",
            "body": "excluded incomplete provenance row",
            "title": "99",
            "section": "999",
        },
    ]


def build_default_bm25_expected_fixture_payload() -> dict[str, Any]:
    """Compact sealed recipe for USCIR-015 (no bulk posting dumps)."""

    return {
        "acceptance": {
            "every_admitted_chunk_has_one_bm25_document": True,
            "field_scores_are_explainable": True,
            "legacy_k1_b_differences_are_explicit": True,
            "source_corpus_roots_reconcile": True,
        },
        "cases": [
            {
                "case_id": "one-document-per-admitted-chunk",
                "expect": {
                    "admitted_count": 5,
                    "document_count": 5,
                    "unique_entry_cids": True,
                },
                "kind": "coverage",
            },
            {
                "case_id": "roots-reconcile",
                "expect": {"reconciled": True},
                "kind": "reconcile",
            },
            {
                "case_id": "field-score-explanation",
                "expect": {
                    "min_field_contributions": 1,
                    "query": "freedom of information agency records",
                    "top_legal_id_prefix": "usc:us:5:552",
                },
                "kind": "explain",
            },
            {
                "case_id": "title-filter",
                "expect": {
                    "filter": {"title": "35"},
                    "query": "patent invention",
                    "result_titles_only": "35",
                },
                "kind": "filter",
            },
            {
                "case_id": "legacy-parameter-delta",
                "expect": {
                    "k1_changed": True,
                    "legacy_k1": LEGACY_K1,
                    "evaluation_k1": DEFAULT_K1,
                },
                "kind": "legacy_delta",
            },
            {
                "case_id": "quarantine-excluded",
                "expect": {
                    "recovery_documents": 0,
                    "excluded_documents": 0,
                },
                "kind": "quarantine",
            },
        ],
        "default_parameters": {
            "b": DEFAULT_B,
            "field_weights": dict(DEFAULT_FIELD_WEIGHTS),
            "k1": DEFAULT_K1,
            "tokenizer_id": TOKENIZER_ID,
        },
        "field_order": list(FIELD_ORDER),
        "goal_id": GOAL_ID,
        "legacy_parameter_delta": legacy_parameter_delta(),
        "primary_key": PRIMARY_KEY,
        "producer": PRODUCER,
        "release_profile": RELEASE_PROFILE,
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "task_id": TASK_ID,
    }


def default_bm25_expected_fixture_path() -> Path:
    """Path to the sealed on-disk fixture relative to the tests tree."""

    # ipfs_datasets_py/processors/legal_data/this_file.py → repo root
    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "legal_ir"
        / "uscode_bm25_expected.json"
    )


def load_bm25_expected_fixture_payload(
    path: PathLike | None = None,
) -> dict[str, Any]:
    """Load and lightly validate the sealed BM25 expected fixture."""

    target = Path(path) if path is not None else default_bm25_expected_fixture_path()
    if not target.is_file():
        raise Bm25FixtureError(f"BM25 fixture missing: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Bm25FixtureError(f"BM25 fixture is unreadable: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise Bm25FixtureError("BM25 fixture root must be a mapping")
    if payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise Bm25FixtureError(
            f"unexpected fixture schema_version: {payload.get('schema_version')!r}"
        )
    if payload.get("task_id") != TASK_ID:
        raise Bm25FixtureError(f"unexpected fixture task_id: {payload.get('task_id')!r}")
    if not isinstance(payload.get("cases"), list) or not payload["cases"]:
        raise Bm25FixtureError("BM25 fixture cases must be a non-empty list")
    return dict(payload)


def run_fixture_case(
    case: Mapping[str, Any],
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
    config: UscodeBm25Config | None = None,
) -> dict[str, Any]:
    """Execute one sealed fixture case and return a result envelope."""

    if not isinstance(case, Mapping):
        raise Bm25FixtureError("fixture case must be a mapping")
    case_id = str(case.get("case_id") or "")
    kind = str(case.get("kind") or "")
    expect = dict(case.get("expect") or {})
    sample = list(rows) if rows is not None else _sample_corpus_rows()
    cfg = config or default_bm25_config()
    index = build_uscode_bm25_index(sample, config=cfg)

    if kind == "coverage":
        admitted = sum(1 for row in sample if _is_admitted_row(row))
        ok = (
            index.document_count == int(expect.get("document_count", admitted))
            and admitted == int(expect.get("admitted_count", admitted))
            and len({doc.entry_cid for doc in index.documents})
            == index.document_count
        )
        return {
            "case_id": case_id,
            "kind": kind,
            "ok": ok,
            "document_count": index.document_count,
            "admitted_count": admitted,
        }

    if kind == "reconcile":
        receipt = reconcile_roots(
            index, expected_corpus_root_cid=index.corpus_root_cid
        )
        return {
            "case_id": case_id,
            "kind": kind,
            "ok": bool(receipt.get("reconciled")),
            "receipt": receipt,
        }

    if kind == "explain":
        query = str(expect.get("query") or "")
        hits = index.search(query, top_k=3)
        if not hits:
            return {"case_id": case_id, "kind": kind, "ok": False, "hits": []}
        top = hits[0]
        field_contribs = sum(
            len(expl.field_contributions) for expl in top.explanations
        )
        prefix = str(expect.get("top_legal_id_prefix") or "")
        legal_ok = (
            not prefix
            or (top.legal_id is not None and top.legal_id.startswith(prefix))
        )
        ok = (
            field_contribs >= int(expect.get("min_field_contributions", 1))
            and legal_ok
            and top.score > 0.0
        )
        return {
            "case_id": case_id,
            "kind": kind,
            "ok": ok,
            "top_entry_cid": top.entry_cid,
            "top_legal_id": top.legal_id,
            "field_contributions": field_contribs,
            "score": top.score,
            "explanation": top.explanations[0].to_dict() if top.explanations else None,
        }

    if kind == "filter":
        query = str(expect.get("query") or "")
        filt = dict(expect.get("filter") or {})
        hits = index.search(query, top_k=10, filters=filt)
        expected_title = str(expect.get("result_titles_only") or filt.get("title") or "")
        ok = bool(hits) and all(
            (hit.filters.get("title") == expected_title) for hit in hits
        )
        return {
            "case_id": case_id,
            "kind": kind,
            "ok": ok,
            "hit_count": len(hits),
            "titles": [hit.filters.get("title") for hit in hits],
        }

    if kind == "legacy_delta":
        delta = legacy_parameter_delta()
        ok = (
            bool(delta["k1"]["changed"]) == bool(expect.get("k1_changed", True))
            and math.isclose(delta["k1"]["legacy"], float(expect.get("legacy_k1", LEGACY_K1)))
            and math.isclose(
                delta["k1"]["evaluation_default"],
                float(expect.get("evaluation_k1", DEFAULT_K1)),
            )
        )
        return {"case_id": case_id, "kind": kind, "ok": ok, "delta": delta}

    if kind == "quarantine":
        recovery_docs = sum(
            1
            for doc in index.documents
            if doc.record_type in {"recovery", "workflow"}
        )
        # Excluded rows never appear because project_admitted_documents skips them.
        excluded_present = any(
            doc.entry_cid == "sha256:" + ("9" * 64) for doc in index.documents
        )
        ok = recovery_docs == int(expect.get("recovery_documents", 0)) and (
            not excluded_present
        ) == (int(expect.get("excluded_documents", 0)) == 0)
        return {
            "case_id": case_id,
            "kind": kind,
            "ok": ok,
            "recovery_documents": recovery_docs,
            "excluded_present": excluded_present,
        }

    raise Bm25FixtureError(f"unknown fixture case kind: {kind!r}")


def run_all_fixture_cases(
    path: PathLike | None = None,
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Run every sealed fixture case and return result envelopes."""

    payload = load_bm25_expected_fixture_payload(path)
    sample = list(rows) if rows is not None else _sample_corpus_rows()
    return [run_fixture_case(case, rows=sample) for case in payload["cases"]]


__all__ = [
    "AUTHORITY_FIELDS",
    "CONTENT_FIELDS",
    "DEFAULT_B",
    "DEFAULT_FIELD_WEIGHTS",
    "DEFAULT_K1",
    "FIELD_ORDER",
    "FIXTURE_SCHEMA_VERSION",
    "GOAL_ID",
    "LEGACY_B",
    "LEGACY_K1",
    "PRIMARY_KEY",
    "PRODUCER",
    "RELEASE_PROFILE",
    "SCHEMA_VERSION",
    "TASK_ID",
    "Bm25ConfigError",
    "Bm25CoverageError",
    "Bm25FilterError",
    "Bm25FixtureError",
    "Bm25Hit",
    "Bm25ProjectionError",
    "Bm25RootReconcileError",
    "FieldScoreContribution",
    "FieldTokenStream",
    "FieldWeightConfig",
    "IndexField",
    "LegalBm25Document",
    "TermScoreExplanation",
    "UscodeBm25Config",
    "UscodeBm25Error",
    "UscodeBm25Index",
    "assert_every_admitted_chunk_has_document",
    "build_corpus_root_cid",
    "build_default_bm25_expected_fixture_payload",
    "build_index_root_cid",
    "build_uscode_bm25_index",
    "content_cid",
    "content_sha256",
    "default_bm25_config",
    "default_bm25_expected_fixture_path",
    "export_shared_bm25_layout",
    "legacy_parameter_delta",
    "load_bm25_expected_fixture_payload",
    "project_admitted_documents",
    "project_legal_document",
    "reconcile_roots",
    "run_all_fixture_cases",
    "run_fixture_case",
]
