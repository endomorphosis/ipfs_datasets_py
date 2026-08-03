"""Fielded BM25, pinned vector, and graph-fusion indexes for patent retrieval.

PATLAW-092 builds three source-linked index families from verified patent /
legal records:

* Field-aware BM25 over title, abstract, claims, description, CPC, IPC,
  citations, numbers, and legal bases.
* Pinned dense vectors with recorded embedding provider/model/config identity.
* Deterministic graph expansion structures for fusion.

Design invariants:

* Legal and patent tokens (U.S.C./C.F.R. citations, CPC/IPC codes, patent and
  application numbers, section symbols) survive tokenization.
* Authority, as-of, disclosure, and tenant filters run *before* any scoring or
  embedding of admitted rows.
* Every index row, graph node, and edge joins to at least one source CID.
* Builds are pure and deterministic: identical inputs always produce identical
  serialized payloads and digests.
* Denied private routes make zero remote embedding provider calls; isolation
  counters record the denials.
* This module owns concrete builders only. Contracts live in
  ``retrieval_contracts``; search/fusion lives in ``hybrid_retrieval``.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.retrieval import (
    hashed_term_projection,
    vector_dot,
)

from .retrieval_contracts import (
    DEFAULT_FIELD_WEIGHTS,
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    AuthorityClaim,
    DisclosureClass,
    EdgeKind,
    EdgeProvenance,
    EmbeddingIdentity,
    FieldWeightConfig,
    GraphEdge,
    IndexField,
    PreRankingFilterViolation,
    PreRankingFilters,
    RetrievalFamily,
    SourceLink,
    SourceLinkedIndexRow,
    SourceSpan,
    VectorIndexRow,
    assert_authority_claim_allowed,
    canonical_json,
    filter_index_rows,
    is_private_disclosure,
    require_pre_ranking_filters,
    requires_quarantine,
)

# ---------------------------------------------------------------------------
# Schema pins
# ---------------------------------------------------------------------------

INDEXING_SCHEMA_VERSION: Final = "patent.indexing.v1"
INDEXING_INTERFACE: Final = "PatentIndexing@1"
TOKENIZER_VERSION: Final = "patent-legal-tokens/v1"
DEFAULT_EMBEDDING_PROVIDER: Final = "local_hash"
DEFAULT_EMBEDDING_MODEL_ID: Final = "hashed-term-patent-v1"
DEFAULT_EMBEDDING_MODEL_VERSION: Final = "1.0.0"
DEFAULT_EMBEDDING_DIMENSION: Final = 256
DEFAULT_EMBEDDING_CONFIG_CID: Final = (
    "bafybeihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"
)
DEFAULT_CORPUS_CID: Final = (
    "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
)

# Remote embedding backends that must never be invoked for denied private rows.
REMOTE_EMBEDDING_PROVIDERS: Final[frozenset[str]] = frozenset(
    {
        "embeddings_router",
        "remote",
        "openai",
        "anthropic",
        "cohere",
        "voyage",
        "huggingface_hub",
        "external",
    }
)

# Field order for deterministic multi-field scoring / serialization.
_FIELD_ORDER: Final[tuple[str, ...]] = tuple(
    f.value for f in (
        IndexField.TITLE,
        IndexField.ABSTRACT,
        IndexField.CLAIMS,
        IndexField.DESCRIPTION,
        IndexField.CPC,
        IndexField.IPC,
        IndexField.CITATIONS,
        IndexField.NUMBERS,
        IndexField.LEGAL_BASES,
    )
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IndexingError(ValueError):
    """Base error for patent index build failures."""


class MissingSourceCIDError(IndexingError):
    """Raised when a row/node/edge lacks a source CID join."""


class RemoteEmbeddingDeniedError(IndexingError):
    """Raised when a remote embedding call is attempted on a denied private route."""


class AtomicChunkError(IndexingError):
    """Raised when atomic chunking would split a protected unit."""


# ---------------------------------------------------------------------------
# Patent / legal tokenization (tokens must survive)
# ---------------------------------------------------------------------------

# 35 U.S.C. § 102(a)(1) / 37 C.F.R. § 1.56 / MPEP § 2106.04(a)
_LEGAL_CITATION_RE = re.compile(
    r"(?:"
    r"(?:\d+\s*U\.?\s*S\.?\s*C\.?(?:A\.?)?\s*(?:§+|section|sec\.?)?\s*"
    r"[\dA-Za-z]+(?:\([a-z0-9]+\))*(?:[.\-][\dA-Za-z]+)*)"
    r"|(?:\d+\s*C\.?\s*F\.?\s*R\.?\s*(?:§+|section|sec\.?)?\s*"
    r"[\d]+(?:\.[\w-]+)*(?:\([a-z0-9]+\))*)"
    r"|(?:MPEP\s*(?:§+|section|sec\.?)?\s*[\d]+(?:\.[\d]+)*(?:\([a-z0-9]+\))*)"
    r")",
    re.IGNORECASE,
)

# CPC / IPC: G06F16/00, H04L 9/32, A61B5/00
_CLASSIFICATION_RE = re.compile(
    r"\b[A-HY]\d{2}[A-Z]\s*\d+(?:/\d+)?(?:\d{2})?\b",
    re.IGNORECASE,
)

# Patent / publication / application numbers
_PATENT_NUMBER_RE = re.compile(
    r"\b(?:"
    r"US\s*[\d,]{5,12}\s*[AB]\d?"
    r"|US\s*\d{2}/\d{3},\d{3}"
    r"|US\s*\d{7,11}"
    r"|PCT/[A-Z]{2}\d{4}/\d{6}"
    r"|EP\s*\d{7,9}"
    r"|WO\s*\d{4}/\d{6}"
    r"|App(?:lication)?\.?\s*(?:No\.?|Number)?\s*[\d/,\-]{5,20}"
    r")\b",
    re.IGNORECASE,
)

# Claim references: claim 1, claims 1-3, Claim 12
_CLAIM_REF_RE = re.compile(
    r"\bclaims?\s+\d+(?:\s*[-–—]\s*\d+)?(?:\s*(?:,|and)\s*\d+)*\b",
    re.IGNORECASE,
)

# Section symbol alone with number: § 102, §§ 101-103
_SECTION_SYMBOL_RE = re.compile(
    r"§+\s*[\dA-Za-z]+(?:\([a-z0-9]+\))*(?:[.\-][\dA-Za-z]+)*",
    re.IGNORECASE,
)

_GENERIC_TOKEN_RE = re.compile(r"[A-Za-z0-9_./\-]+")

# Patterns extracted first (highest priority → longest matches preserved).
_PROTECTED_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    _LEGAL_CITATION_RE,
    _PATENT_NUMBER_RE,
    _CLASSIFICATION_RE,
    _CLAIM_REF_RE,
    _SECTION_SYMBOL_RE,
)


def _normalize_protected_token(raw: str) -> str:
    """Collapse whitespace inside a protected legal/patent token."""
    text = re.sub(r"\s+", " ", raw.strip())
    # Canonical lowercase with internal spaces → underscores for bag-of-words.
    text = text.lower().replace(" ", "_")
    # Normalize common punctuation variants without destroying structure.
    text = text.replace("§§", "§").replace("sec.", "§").replace("section", "§")
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def tokenize_patent_text(text: str) -> list[str]:
    """Tokenize *text* preserving legal/patent protected tokens.

    Protected forms (citations, CPC/IPC, patent numbers, claim refs, section
    symbols) are emitted as single tokens so they survive fielded BM25 and
    local dense projection. Remaining text falls back to alphanumeric tokens.
    """
    source = str(text or "")
    if not source.strip():
        return []

    spans: list[tuple[int, int, str]] = []
    for pattern in _PROTECTED_PATTERNS:
        for match in pattern.finditer(source):
            start, end = match.span()
            # Skip overlaps with already-accepted higher-priority spans.
            if any(not (end <= s or start >= e) for s, e, _ in spans):
                continue
            token = _normalize_protected_token(match.group(0))
            if token:
                spans.append((start, end, token))

    spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    # Resolve residual overlaps after sort (keep first/longest).
    accepted: list[tuple[int, int, str]] = []
    for start, end, token in spans:
        if any(not (end <= s or start >= e) for s, e, _ in accepted):
            continue
        accepted.append((start, end, token))
    accepted.sort(key=lambda item: item[0])

    tokens: list[str] = []
    cursor = 0
    for start, end, token in accepted:
        if cursor < start:
            gap = source[cursor:start]
            tokens.extend(m.group(0).lower() for m in _GENERIC_TOKEN_RE.finditer(gap))
        tokens.append(token)
        cursor = end
    if cursor < len(source):
        gap = source[cursor:]
        tokens.extend(m.group(0).lower() for m in _GENERIC_TOKEN_RE.finditer(gap))
    return tokens


def legal_tokens_present(text: str) -> list[str]:
    """Return protected legal/patent tokens that survive :func:`tokenize_patent_text`.

    Uses the same priority/overlap resolution as the tokenizer so audits match
    the tokens actually stored in fielded BM25 and local projections.
    """
    tokens = tokenize_patent_text(text)
    # Re-detect which emitted tokens came from protected patterns.
    source = str(text or "")
    protected_forms: set[str] = set()
    for pattern in _PROTECTED_PATTERNS:
        for match in pattern.finditer(source):
            token = _normalize_protected_token(match.group(0))
            if token:
                protected_forms.add(token)
    return [t for t in tokens if t in protected_forms]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def content_digest_hex(value: Any) -> str:
    """Return a 64-char lowercase SHA-256 hex digest of canonical JSON."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_source_links(
    links: Sequence[SourceLink | Mapping[str, Any]] | None,
    *,
    field: str,
) -> tuple[SourceLink, ...]:
    if not links:
        raise MissingSourceCIDError(f"{field} must contain at least one source link")
    out: list[SourceLink] = []
    for i, item in enumerate(links):
        if isinstance(item, SourceLink):
            link = item
        elif isinstance(item, Mapping):
            link = SourceLink.from_dict(item)
        else:
            raise TypeError(f"{field}[{i}] must be SourceLink or mapping")
        if not link.source_cid:
            raise MissingSourceCIDError(f"{field}[{i}] missing source_cid")
        out.append(link)
    # Deterministic order.
    out.sort(
        key=lambda link: (
            link.source_cid,
            link.artifact_id,
            -1 if link.span is None else link.span.start,
            -1 if link.span is None else link.span.end,
        )
    )
    return tuple(out)


def _coerce_disclosure(value: Any) -> DisclosureClass:
    if isinstance(value, DisclosureClass):
        return value
    if isinstance(value, str):
        return DisclosureClass(value.strip())
    raise TypeError(f"disclosure must be DisclosureClass or str, got {type(value).__name__}")


def _field_text_map(fields: Mapping[str, Any] | None) -> dict[str, str]:
    if not fields:
        return {}
    out: dict[str, str] = {}
    for key, raw in fields.items():
        name = str(key).strip()
        if not name:
            continue
        if isinstance(raw, (list, tuple)):
            text = " ".join(str(item).strip() for item in raw if str(item).strip())
        else:
            text = str(raw or "").strip()
        if text:
            out[name] = text
    return dict(sorted(out.items()))


def _row_admission_kwargs(row_like: Any) -> dict[str, Any]:
    return {
        "disclosure": getattr(row_like, "disclosure"),
        "tenant_id": getattr(row_like, "tenant_id"),
        "effective_from_utc": getattr(row_like, "effective_from_utc", None),
        "effective_to_utc": getattr(row_like, "effective_to_utc", None),
    }


# ---------------------------------------------------------------------------
# Document input and atomic chunking
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatentIndexDocument:
    """One source-linked patent/legal document admitted into index builds."""

    document_id: str
    field_values: Mapping[str, str]
    source_links: tuple[SourceLink, ...]
    disclosure: DisclosureClass
    tenant_id: str
    effective_from_utc: str | None = None
    effective_to_utc: str | None = None
    publication_utc: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})
    # Optional structured claim units for atomic chunking (1-based claim text).
    claim_units: tuple[str, ...] = ()
    # Optional legal-section / event units (each unit is one atomic chunk).
    section_units: tuple[str, ...] = ()
    event_units: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", str(self.document_id).strip())
        if not self.document_id:
            raise IndexingError("document_id must be non-empty")
        fields = _field_text_map(dict(self.field_values or {}))
        object.__setattr__(self, "field_values", MappingProxyType(fields))
        object.__setattr__(
            self,
            "source_links",
            _require_source_links(self.source_links, field="source_links"),
        )
        object.__setattr__(self, "disclosure", _coerce_disclosure(self.disclosure))
        object.__setattr__(self, "tenant_id", str(self.tenant_id).strip())
        if not self.tenant_id:
            raise IndexingError("tenant_id must be non-empty")
        meta = {
            str(k): str(v)
            for k, v in dict(self.metadata or {}).items()
            if str(k).strip() and str(v).strip()
        }
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(sorted(meta.items())))
        )
        claims = tuple(str(c).strip() for c in (self.claim_units or ()) if str(c).strip())
        sections = tuple(
            str(s).strip() for s in (self.section_units or ()) if str(s).strip()
        )
        events = tuple(
            str(e).strip() for e in (self.event_units or ()) if str(e).strip()
        )
        object.__setattr__(self, "claim_units", claims)
        object.__setattr__(self, "section_units", sections)
        object.__setattr__(self, "event_units", events)

    @property
    def content_digest(self) -> str:
        payload = {
            "document_id": self.document_id,
            "field_values": dict(self.field_values),
            "claim_units": list(self.claim_units),
            "section_units": list(self.section_units),
            "event_units": list(self.event_units),
            "source_links": [link.to_dict() for link in self.source_links],
            "disclosure": self.disclosure.value,
            "tenant_id": self.tenant_id,
            "effective_from_utc": self.effective_from_utc,
            "effective_to_utc": self.effective_to_utc,
            "publication_utc": self.publication_utc,
            "metadata": dict(self.metadata),
        }
        return content_digest_hex(payload)

    def combined_text(self, *, fields: Sequence[str] | None = None) -> str:
        order = list(fields) if fields is not None else list(_FIELD_ORDER)
        parts: list[str] = []
        for name in order:
            value = self.field_values.get(name)
            if value:
                parts.append(value)
        # Include residual free-form fields deterministically.
        for name, value in self.field_values.items():
            if name not in order and value:
                parts.append(value)
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_units": list(self.claim_units),
            "disclosure": self.disclosure.value,
            "document_id": self.document_id,
            "effective_from_utc": self.effective_from_utc,
            "effective_to_utc": self.effective_to_utc,
            "event_units": list(self.event_units),
            "field_values": dict(self.field_values),
            "metadata": dict(self.metadata),
            "publication_utc": self.publication_utc,
            "section_units": list(self.section_units),
            "source_links": [link.to_dict() for link in self.source_links],
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PatentIndexDocument":
        if not isinstance(value, Mapping):
            raise TypeError("PatentIndexDocument.from_dict expects a mapping")
        return cls(
            document_id=str(value.get("document_id") or ""),
            field_values=value.get("field_values") or {},
            source_links=tuple(value.get("source_links") or ()),
            disclosure=value.get("disclosure") or DisclosureClass.UNKNOWN.value,
            tenant_id=str(value.get("tenant_id") or ""),
            effective_from_utc=value.get("effective_from_utc"),
            effective_to_utc=value.get("effective_to_utc"),
            publication_utc=value.get("publication_utc"),
            metadata=value.get("metadata") or {},
            claim_units=tuple(value.get("claim_units") or ()),
            section_units=tuple(value.get("section_units") or ()),
            event_units=tuple(value.get("event_units") or ()),
        )


@dataclass(frozen=True, slots=True)
class AtomicChunk:
    """One atomic chunk (claim, legal section, or event) with source join."""

    chunk_id: str
    document_id: str
    kind: str  # claim | section | event | field
    text: str
    source_links: tuple[SourceLink, ...]
    field_name: str | None = None
    ordinal: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "field_name": self.field_name,
            "kind": self.kind,
            "ordinal": self.ordinal,
            "source_links": [link.to_dict() for link in self.source_links],
            "text": self.text,
        }


def chunk_document_atomically(document: PatentIndexDocument) -> tuple[AtomicChunk, ...]:
    """Chunk claims, legal sections, and events as atomic units.

    Claim units, section units, and event units are never mid-split. When no
    structured units are present, each non-empty index field becomes one chunk.
    """
    if not isinstance(document, PatentIndexDocument):
        raise TypeError("document must be PatentIndexDocument")
    chunks: list[AtomicChunk] = []
    links = document.source_links

    def _add(kind: str, units: Sequence[str], field_name: str | None) -> None:
        for i, text in enumerate(units, start=1):
            if not text.strip():
                continue
            # Reject accidental mid-claim markers that indicate a bad split.
            if kind == "claim" and text.strip().endswith("..."):
                raise AtomicChunkError(
                    f"claim unit {i} for {document.document_id} appears truncated"
                )
            chunk_id = f"{document.document_id}:{kind}:{i}"
            chunks.append(
                AtomicChunk(
                    chunk_id=chunk_id,
                    document_id=document.document_id,
                    kind=kind,
                    text=text.strip(),
                    source_links=links,
                    field_name=field_name,
                    ordinal=i,
                )
            )

    _add("claim", document.claim_units, IndexField.CLAIMS.value)
    _add("section", document.section_units, IndexField.LEGAL_BASES.value)
    _add("event", document.event_units, None)

    if not chunks:
        for name in _FIELD_ORDER:
            value = document.field_values.get(name)
            if value:
                chunks.append(
                    AtomicChunk(
                        chunk_id=f"{document.document_id}:field:{name}",
                        document_id=document.document_id,
                        kind="field",
                        text=value,
                        source_links=links,
                        field_name=name,
                        ordinal=1,
                    )
                )
        # Residual free-form fields.
        for name, value in document.field_values.items():
            if name in _FIELD_ORDER or not value:
                continue
            chunks.append(
                AtomicChunk(
                    chunk_id=f"{document.document_id}:field:{name}",
                    document_id=document.document_id,
                    kind="field",
                    text=value,
                    source_links=links,
                    field_name=name,
                    ordinal=1,
                )
            )

    chunks.sort(key=lambda c: (c.document_id, c.kind, c.ordinal, c.chunk_id))
    return tuple(chunks)


# ---------------------------------------------------------------------------
# Fielded BM25
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldedTermStats:
    """Per-field term frequency statistics for one document row."""

    field: str
    document_length: int
    term_frequencies: tuple[tuple[str, int], ...]  # sorted (term, tf)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_length": self.document_length,
            "field": self.field,
            "term_frequencies": [
                {"term": term, "tf": tf} for term, tf in self.term_frequencies
            ],
        }


@dataclass(frozen=True, slots=True)
class FieldedBm25Document:
    """One fielded BM25 document payload with source CID join."""

    row_id: str
    document_id: str
    fields: tuple[FieldedTermStats, ...]
    source_links: tuple[SourceLink, ...]
    disclosure: str
    tenant_id: str
    content_digest: str
    effective_from_utc: str | None = None
    effective_to_utc: str | None = None
    field_weights_config_cid: str | None = None
    matched_token_samples: tuple[str, ...] = ()  # protected tokens that survived

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "disclosure": self.disclosure,
            "document_id": self.document_id,
            "effective_from_utc": self.effective_from_utc,
            "effective_to_utc": self.effective_to_utc,
            "field_weights_config_cid": self.field_weights_config_cid,
            "fields": [f.to_dict() for f in self.fields],
            "matched_token_samples": list(self.matched_token_samples),
            "row_id": self.row_id,
            "source_links": [link.to_dict() for link in self.source_links],
            "tenant_id": self.tenant_id,
        }


@dataclass(frozen=True, slots=True)
class FieldedBm25Index:
    """Deterministic fielded BM25 index payload."""

    schema_version: str
    backend: str
    tokenizer_version: str
    field_weights: FieldWeightConfig
    documents: tuple[FieldedBm25Document, ...]
    document_frequency: Mapping[str, Mapping[str, int]]  # field -> term -> df
    stats: Mapping[str, Any]
    corpus_cid: str
    index_cid: str
    content_digest: str
    filters_receipt: Mapping[str, Any]
    denied_provider_call_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        df_out = {
            field_name: dict(sorted(terms.items()))
            for field_name, terms in sorted(self.document_frequency.items())
        }
        return {
            "backend": self.backend,
            "content_digest": self.content_digest,
            "corpus_cid": self.corpus_cid,
            "denied_provider_call_count": self.denied_provider_call_count,
            "document_frequency": df_out,
            "documents": [d.to_dict() for d in self.documents],
            "field_weights": self.field_weights.to_dict(),
            "filters_receipt": dict(self.filters_receipt),
            "index_cid": self.index_cid,
            "schema_version": self.schema_version,
            "stats": dict(self.stats),
            "tokenizer_version": self.tokenizer_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FieldedBm25Index":
        docs_raw = value.get("documents") or []
        documents: list[FieldedBm25Document] = []
        for raw in docs_raw:
            fields = tuple(
                FieldedTermStats(
                    field=str(f["field"]),
                    document_length=int(f["document_length"]),
                    term_frequencies=tuple(
                        (str(t["term"]), int(t["tf"]))
                        for t in (f.get("term_frequencies") or [])
                    ),
                )
                for f in (raw.get("fields") or [])
            )
            documents.append(
                FieldedBm25Document(
                    row_id=str(raw["row_id"]),
                    document_id=str(raw["document_id"]),
                    fields=fields,
                    source_links=tuple(
                        SourceLink.from_dict(s) for s in (raw.get("source_links") or [])
                    ),
                    disclosure=str(raw["disclosure"]),
                    tenant_id=str(raw["tenant_id"]),
                    content_digest=str(raw["content_digest"]),
                    effective_from_utc=raw.get("effective_from_utc"),
                    effective_to_utc=raw.get("effective_to_utc"),
                    field_weights_config_cid=raw.get("field_weights_config_cid"),
                    matched_token_samples=tuple(raw.get("matched_token_samples") or ()),
                )
            )
        df_raw = value.get("document_frequency") or {}
        document_frequency = {
            str(fname): {str(t): int(df) for t, df in dict(terms).items()}
            for fname, terms in df_raw.items()
        }
        return cls(
            schema_version=str(value.get("schema_version") or INDEXING_SCHEMA_VERSION),
            backend=str(value.get("backend") or "fielded_bm25"),
            tokenizer_version=str(
                value.get("tokenizer_version") or TOKENIZER_VERSION
            ),
            field_weights=FieldWeightConfig.from_dict(value.get("field_weights") or {}),
            documents=tuple(documents),
            document_frequency=MappingProxyType(
                {k: MappingProxyType(v) for k, v in sorted(document_frequency.items())}
            ),
            stats=MappingProxyType(dict(value.get("stats") or {})),
            corpus_cid=str(value.get("corpus_cid") or ""),
            index_cid=str(value.get("index_cid") or ""),
            content_digest=str(value.get("content_digest") or ""),
            filters_receipt=MappingProxyType(dict(value.get("filters_receipt") or {})),
            denied_provider_call_count=int(
                value.get("denied_provider_call_count") or 0
            ),
        )


def _build_source_linked_rows(
    documents: Sequence[PatentIndexDocument],
    *,
    family: RetrievalFamily,
    field_weights_config_cid: str | None,
) -> tuple[SourceLinkedIndexRow, ...]:
    rows: list[SourceLinkedIndexRow] = []
    for doc in documents:
        if not isinstance(doc, PatentIndexDocument):
            raise TypeError("documents must contain PatentIndexDocument instances")
        row = SourceLinkedIndexRow(
            schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
            row_id=f"{family.value}:{doc.document_id}",
            document_id=doc.document_id,
            family=family,
            field_values=dict(doc.field_values),
            source_links=doc.source_links,
            disclosure=doc.disclosure,
            tenant_id=doc.tenant_id,
            content_digest=doc.content_digest,
            effective_from_utc=doc.effective_from_utc,
            effective_to_utc=doc.effective_to_utc,
            publication_utc=doc.publication_utc,
            field_weights_config_cid=field_weights_config_cid,
            metadata=dict(doc.metadata),
        )
        rows.append(row)
    # Deterministic document order.
    rows.sort(key=lambda r: (r.document_id, r.row_id))
    return tuple(rows)


def _admit_documents(
    documents: Sequence[PatentIndexDocument],
    filters: PreRankingFilters,
    *,
    family: RetrievalFamily,
    field_weights_config_cid: str | None,
) -> tuple[tuple[PatentIndexDocument, ...], tuple[SourceLinkedIndexRow, ...], PreRankingFilters]:
    """Apply mandatory pre-ranking filters before any scoring/embedding.

    Filters must already be marked ``applied=True`` (fail closed). Use
    ``filters.mark_applied()`` at the call site after composing the gate.
    """
    require_pre_ranking_filters(filters)
    rows = _build_source_linked_rows(
        documents,
        family=family,
        field_weights_config_cid=field_weights_config_cid,
    )
    admitted_rows = filter_index_rows(rows, filters)
    admitted_ids = {row.document_id for row in admitted_rows}
    admitted_docs = tuple(
        sorted(
            (d for d in documents if d.document_id in admitted_ids),
            key=lambda d: d.document_id,
        )
    )
    return admitted_docs, admitted_rows, filters


def build_fielded_bm25_index(
    documents: Sequence[PatentIndexDocument],
    *,
    filters: PreRankingFilters,
    field_weights: FieldWeightConfig | None = None,
    corpus_cid: str = DEFAULT_CORPUS_CID,
) -> FieldedBm25Index:
    """Build a deterministic fielded BM25 index after pre-ranking filters.

    Filters (authority via disclosure classes, as-of, tenant) always run first.
    """
    weights = field_weights or FieldWeightConfig.default(
        config_cid=DEFAULT_EMBEDDING_CONFIG_CID
    )
    admitted_docs, _admitted_rows, applied = _admit_documents(
        documents,
        filters,
        family=RetrievalFamily.BM25,
        field_weights_config_cid=weights.config_cid,
    )

    field_df: dict[str, Counter[str]] = defaultdict(Counter)
    field_total_len: Counter[str] = Counter()
    field_doc_count: Counter[str] = Counter()
    built_docs: list[FieldedBm25Document] = []

    for doc in admitted_docs:
        field_stats: list[FieldedTermStats] = []
        protected_samples: list[str] = []
        for field_name in _FIELD_ORDER:
            text = doc.field_values.get(field_name, "")
            if not text:
                continue
            tokens = tokenize_patent_text(text)
            if not tokens:
                continue
            for token in legal_tokens_present(text):
                if token not in protected_samples:
                    protected_samples.append(token)
            counts = Counter(tokens)
            field_stats.append(
                FieldedTermStats(
                    field=field_name,
                    document_length=sum(counts.values()),
                    term_frequencies=tuple(sorted(counts.items())),
                )
            )
            field_df[field_name].update(counts.keys())
            field_total_len[field_name] += sum(counts.values())
            field_doc_count[field_name] += 1

        # Residual free-form fields beyond the closed IndexField set.
        for field_name, text in doc.field_values.items():
            if field_name in _FIELD_ORDER or not text:
                continue
            tokens = tokenize_patent_text(text)
            if not tokens:
                continue
            counts = Counter(tokens)
            field_stats.append(
                FieldedTermStats(
                    field=field_name,
                    document_length=sum(counts.values()),
                    term_frequencies=tuple(sorted(counts.items())),
                )
            )
            field_df[field_name].update(counts.keys())
            field_total_len[field_name] += sum(counts.values())
            field_doc_count[field_name] += 1

        if not field_stats:
            continue

        field_stats.sort(key=lambda s: s.field)
        protected_samples.sort()
        built_docs.append(
            FieldedBm25Document(
                row_id=f"bm25:{doc.document_id}",
                document_id=doc.document_id,
                fields=tuple(field_stats),
                source_links=doc.source_links,
                disclosure=doc.disclosure.value,
                tenant_id=doc.tenant_id,
                content_digest=doc.content_digest,
                effective_from_utc=doc.effective_from_utc,
                effective_to_utc=doc.effective_to_utc,
                field_weights_config_cid=weights.config_cid,
                matched_token_samples=tuple(protected_samples[:32]),
            )
        )

    built_docs.sort(key=lambda d: d.document_id)
    avgdl: dict[str, float] = {}
    for fname, total in field_total_len.items():
        count = max(1, field_doc_count[fname])
        avgdl[fname] = total / count

    document_frequency = {
        fname: MappingProxyType(dict(sorted(counter.items())))
        for fname, counter in sorted(field_df.items())
    }
    stats = {
        "average_document_tokens_by_field": dict(sorted(avgdl.items())),
        "b": weights.b,
        "document_count": len(built_docs),
        "field_document_counts": dict(sorted(field_doc_count.items())),
        "k1": weights.k1,
        "tokenizer_version": TOKENIZER_VERSION,
        "unique_term_count_by_field": {
            fname: len(terms) for fname, terms in document_frequency.items()
        },
    }
    payload_for_digest = {
        "documents": [d.to_dict() for d in built_docs],
        "document_frequency": {
            f: dict(t) for f, t in document_frequency.items()
        },
        "field_weights": weights.to_dict(),
        "schema_version": INDEXING_SCHEMA_VERSION,
        "stats": stats,
        "tokenizer_version": TOKENIZER_VERSION,
    }
    digest = content_digest_hex(payload_for_digest)
    index_cid = f"bafybei{digest[:50]}"

    return FieldedBm25Index(
        schema_version=INDEXING_SCHEMA_VERSION,
        backend="fielded_bm25",
        tokenizer_version=TOKENIZER_VERSION,
        field_weights=weights,
        documents=tuple(built_docs),
        document_frequency=MappingProxyType(document_frequency),
        stats=MappingProxyType(stats),
        corpus_cid=corpus_cid,
        index_cid=index_cid,
        content_digest=digest,
        filters_receipt=MappingProxyType(applied.to_dict()),
        denied_provider_call_count=applied.denied_provider_call_count,
    )


def score_fielded_bm25(
    query: str,
    index: FieldedBm25Index,
    *,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Score *query* against a fielded BM25 index (no remote I/O)."""
    query_tokens = tokenize_patent_text(query)
    if not query_tokens or not index.documents:
        return []
    k1 = float(index.field_weights.k1)
    b = float(index.field_weights.b)
    avgdl_map = dict(index.stats.get("average_document_tokens_by_field") or {})
    scored: list[dict[str, Any]] = []

    for doc in index.documents:
        score = 0.0
        matched_fields: list[str] = []
        matched_terms: set[str] = set()
        for field_stats in doc.fields:
            try:
                weight = index.field_weights.weight_for(field_stats.field)
            except KeyError:
                weight = DEFAULT_FIELD_WEIGHTS.get(field_stats.field, 1.0)
            if weight <= 0.0:
                continue
            term_counts = dict(field_stats.term_frequencies)
            df_map = dict(index.document_frequency.get(field_stats.field) or {})
            total_docs = max(
                1, int((index.stats.get("field_document_counts") or {}).get(field_stats.field, 1))
            )
            avgdl = float(avgdl_map.get(field_stats.field) or field_stats.document_length or 1.0)
            field_score = 0.0
            field_matched = False
            for term in query_tokens:
                tf = int(term_counts.get(term) or 0)
                if tf <= 0:
                    continue
                field_matched = True
                matched_terms.add(term)
                df = max(1, int(df_map.get(term) or 0))
                idf = math.log(1.0 + ((total_docs - df + 0.5) / (df + 0.5)))
                denom = tf + k1 * (
                    1.0 - b + b * (field_stats.document_length / max(1.0, avgdl))
                )
                field_score += idf * ((tf * (k1 + 1.0)) / max(1e-9, denom))
            if field_matched and field_score > 0.0:
                score += weight * field_score
                matched_fields.append(field_stats.field)
        if score <= 0.0:
            continue
        scored.append(
            {
                "document_id": doc.document_id,
                "row_id": doc.row_id,
                "score": score,
                "matched_fields": sorted(matched_fields),
                "matched_terms": sorted(matched_terms),
                "source_links": [link.to_dict() for link in doc.source_links],
                "content_digest": doc.content_digest,
                "disclosure": doc.disclosure,
                "tenant_id": doc.tenant_id,
                "family": RetrievalFamily.BM25.value,
                "backend": index.backend,
            }
        )

    scored.sort(key=lambda item: (-float(item["score"]), str(item["document_id"])))
    for rank, item in enumerate(scored[: max(1, int(top_k))], start=1):
        item["rank"] = rank
    return scored[: max(1, int(top_k))]


# ---------------------------------------------------------------------------
# Pinned vector index
# ---------------------------------------------------------------------------


EmbeddingFn = Callable[[Sequence[str]], tuple[list[list[float]], Mapping[str, Any]]]


@dataclass
class EmbeddingCallLedger:
    """Tracks remote vs local embedding attempts for private-route isolation."""

    remote_call_count: int = 0
    local_call_count: int = 0
    denied_remote_count: int = 0
    last_backend: str = "local_hash"
    last_provider: str = DEFAULT_EMBEDDING_PROVIDER
    last_model_id: str = DEFAULT_EMBEDDING_MODEL_ID

    def record_local(self, *, count: int = 1) -> None:
        self.local_call_count += max(0, int(count))
        self.last_backend = "local_hashed_term_projection"
        self.last_provider = DEFAULT_EMBEDDING_PROVIDER
        self.last_model_id = DEFAULT_EMBEDDING_MODEL_ID

    def record_remote(self, *, provider: str, model_id: str, count: int = 1) -> None:
        self.remote_call_count += max(0, int(count))
        self.last_backend = "embeddings_router"
        self.last_provider = provider
        self.last_model_id = model_id

    def record_denied(self, *, count: int = 1) -> None:
        self.denied_remote_count += max(0, int(count))

    def to_dict(self) -> dict[str, Any]:
        return {
            "denied_remote_count": self.denied_remote_count,
            "last_backend": self.last_backend,
            "last_model_id": self.last_model_id,
            "last_provider": self.last_provider,
            "local_call_count": self.local_call_count,
            "remote_call_count": self.remote_call_count,
        }


def default_local_embedder(
    texts: Sequence[str],
    *,
    dimension: int = DEFAULT_EMBEDDING_DIMENSION,
    ledger: EmbeddingCallLedger | None = None,
) -> tuple[list[list[float]], Mapping[str, Any]]:
    """Deterministic local hashed-term embedding (never remote)."""
    vectors = [
        hashed_term_projection(
            " ".join(tokenize_patent_text(text)),
            dimension=dimension,
        )
        for text in texts
    ]
    if ledger is not None:
        ledger.record_local(count=len(texts))
    return vectors, {
        "backend": "local_hashed_term_projection",
        "provider": DEFAULT_EMBEDDING_PROVIDER,
        "model_name": DEFAULT_EMBEDDING_MODEL_ID,
        "is_mock": False,
        "dimension": dimension,
    }


def _is_remote_provider(provider: str | None, backend: str | None = None) -> bool:
    candidates = {
        str(provider or "").strip().lower(),
        str(backend or "").strip().lower(),
    }
    return bool(candidates & REMOTE_EMBEDDING_PROVIDERS) or any(
        c.startswith("remote") or c.endswith("_remote") for c in candidates if c
    )


def embed_texts_for_index(
    texts: Sequence[str],
    *,
    embedding: EmbeddingIdentity,
    allow_remote: bool,
    private_route: bool,
    ledger: EmbeddingCallLedger | None = None,
    remote_embedder: EmbeddingFn | None = None,
) -> tuple[list[list[float]], Mapping[str, Any], int]:
    """Embed texts with fail-closed private-route isolation.

    Returns ``(vectors, metadata, denied_remote_count_delta)``.

    When *private_route* is True and the configured provider is remote (or
    remote is otherwise not allowed), this function makes **zero** remote
    embedding calls and records denials on the ledger.
    """
    items = [str(t or "") for t in texts]
    if not items:
        return [], {"backend": "empty", "provider": embedding.provider}, 0

    remote_requested = _is_remote_provider(embedding.provider, embedding.backend)
    denied_delta = 0

    if private_route and (remote_requested or not allow_remote):
        # Fail closed: never call remote for private/denied routes.
        denied_delta = len(items) if remote_requested or remote_embedder is not None else 0
        if ledger is not None and denied_delta:
            ledger.record_denied(count=denied_delta)
        vectors, meta = default_local_embedder(
            items, dimension=embedding.dimension, ledger=ledger
        )
        meta = dict(meta)
        meta["denied_private_route"] = True
        meta["remote_calls"] = 0
        return vectors, meta, denied_delta

    if remote_requested and allow_remote and remote_embedder is not None:
        vectors, meta = remote_embedder(items)
        if ledger is not None:
            ledger.record_remote(
                provider=embedding.provider,
                model_id=embedding.model_id,
                count=len(items),
            )
        meta = dict(meta)
        meta["remote_calls"] = len(items)
        return vectors, meta, 0

    # Default pinned local path (also used when remote is requested but no
    # remote embedder is injected — still zero remote calls).
    if remote_requested and remote_embedder is None:
        # Count as denied remote attempts that never left the process.
        denied_delta = len(items)
        if ledger is not None:
            ledger.record_denied(count=denied_delta)
    vectors, meta = default_local_embedder(
        items, dimension=embedding.dimension, ledger=ledger
    )
    meta = dict(meta)
    meta["remote_calls"] = 0
    return vectors, meta, denied_delta


@dataclass(frozen=True, slots=True)
class PinnedVectorDocument:
    """One pinned vector row with embedding identity and source join."""

    row: VectorIndexRow
    vector: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row.to_dict(),
            "vector": list(self.vector),
            "vector_digest": self.row.vector_digest,
        }


@dataclass(frozen=True, slots=True)
class PinnedVectorIndex:
    """Pinned vector index with recorded embedding provider/model/config."""

    schema_version: str
    embedding: EmbeddingIdentity
    documents: tuple[PinnedVectorDocument, ...]
    corpus_cid: str
    index_cid: str
    content_digest: str
    filters_receipt: Mapping[str, Any]
    embedding_call_ledger: Mapping[str, Any]
    denied_provider_call_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "corpus_cid": self.corpus_cid,
            "denied_provider_call_count": self.denied_provider_call_count,
            "documents": [d.to_dict() for d in self.documents],
            "embedding": self.embedding.to_dict(),
            "embedding_call_ledger": dict(self.embedding_call_ledger),
            "filters_receipt": dict(self.filters_receipt),
            "index_cid": self.index_cid,
            "schema_version": self.schema_version,
        }


def default_embedding_identity(
    *,
    config_cid: str = DEFAULT_EMBEDDING_CONFIG_CID,
    model_cid: str | None = None,
    dimension: int = DEFAULT_EMBEDDING_DIMENSION,
    provider: str = DEFAULT_EMBEDDING_PROVIDER,
    model_id: str = DEFAULT_EMBEDDING_MODEL_ID,
    model_version: str = DEFAULT_EMBEDDING_MODEL_VERSION,
    backend: str = "pinned",
) -> EmbeddingIdentity:
    """Return a pinned EmbeddingIdentity for local deterministic vectors."""
    return EmbeddingIdentity(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        provider=provider,
        model_id=model_id,
        model_version=model_version,
        dimension=dimension,
        config_cid=config_cid,
        model_cid=model_cid,
        backend=backend,
        normalize=True,
    )


def build_pinned_vector_index(
    documents: Sequence[PatentIndexDocument],
    *,
    filters: PreRankingFilters,
    embedding: EmbeddingIdentity | None = None,
    corpus_cid: str = DEFAULT_CORPUS_CID,
    allow_remote: bool = False,
    remote_embedder: EmbeddingFn | None = None,
    ledger: EmbeddingCallLedger | None = None,
) -> PinnedVectorIndex:
    """Build a pinned vector index after pre-ranking filters.

    Private/denied routes never invoke remote embedding providers. The embedding
    provider, model, and config identity are always recorded on the index and
    each row.
    """
    identity = embedding or default_embedding_identity()
    call_ledger = ledger or EmbeddingCallLedger()
    admitted_docs, _rows, applied = _admit_documents(
        documents,
        filters,
        family=RetrievalFamily.VECTOR,
        field_weights_config_cid=identity.config_cid,
    )

    # Partition public vs private for fail-closed remote policy.
    public_docs: list[PatentIndexDocument] = []
    private_docs: list[PatentIndexDocument] = []
    for doc in admitted_docs:
        if is_private_disclosure(doc.disclosure) or requires_quarantine(doc.disclosure):
            private_docs.append(doc)
        else:
            public_docs.append(doc)

    built: list[PinnedVectorDocument] = []
    total_denied = int(applied.denied_provider_call_count)

    def _embed_batch(
        batch: Sequence[PatentIndexDocument], *, private_route: bool
    ) -> None:
        nonlocal total_denied
        if not batch:
            return
        texts = [doc.combined_text() for doc in batch]
        vectors, _meta, denied = embed_texts_for_index(
            texts,
            embedding=identity,
            allow_remote=allow_remote and not private_route,
            private_route=private_route,
            ledger=call_ledger,
            remote_embedder=remote_embedder if not private_route else None,
        )
        total_denied += denied
        for doc, vector in zip(batch, vectors):
            vec_tuple = tuple(float(v) for v in vector)
            vector_digest = _sha256_bytes(
                canonical_json(list(vec_tuple)).encode("utf-8")
            )
            row = VectorIndexRow(
                schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
                row_id=f"vec:{doc.document_id}",
                document_id=doc.document_id,
                embedding=identity,
                vector_digest=vector_digest,
                source_links=doc.source_links,
                disclosure=doc.disclosure,
                tenant_id=doc.tenant_id,
                content_digest=doc.content_digest,
                effective_from_utc=doc.effective_from_utc,
                effective_to_utc=doc.effective_to_utc,
                metadata={
                    "provider": identity.provider,
                    "model_id": identity.model_id,
                    "model_version": identity.model_version,
                    "config_cid": identity.config_cid,
                    **(
                        {"model_cid": identity.model_cid}
                        if identity.model_cid
                        else {}
                    ),
                },
            )
            built.append(PinnedVectorDocument(row=row, vector=vec_tuple))

    _embed_batch(public_docs, private_route=False)
    _embed_batch(private_docs, private_route=True)

    built.sort(key=lambda d: d.row.document_id)
    payload = {
        "documents": [
            {
                "document_id": d.row.document_id,
                "vector_digest": d.row.vector_digest,
                "content_digest": d.row.content_digest,
                "source_links": [s.to_dict() for s in d.row.source_links],
            }
            for d in built
        ],
        "embedding": identity.to_dict(),
        "schema_version": INDEXING_SCHEMA_VERSION,
    }
    digest = content_digest_hex(payload)
    index_cid = f"bafybei{digest[:50]}"

    return PinnedVectorIndex(
        schema_version=INDEXING_SCHEMA_VERSION,
        embedding=identity,
        documents=tuple(built),
        corpus_cid=corpus_cid,
        index_cid=index_cid,
        content_digest=digest,
        filters_receipt=MappingProxyType(applied.to_dict()),
        embedding_call_ledger=MappingProxyType(call_ledger.to_dict()),
        denied_provider_call_count=total_denied,
    )


def score_pinned_vectors(
    query: str,
    index: PinnedVectorIndex,
    *,
    top_k: int = 10,
    query_vector: Sequence[float] | None = None,
) -> list[dict[str, Any]]:
    """Score *query* (or *query_vector*) against a pinned vector index."""
    if not index.documents:
        return []
    if query_vector is None:
        vectors, _meta = default_local_embedder(
            [query], dimension=index.embedding.dimension
        )
        qvec = vectors[0]
    else:
        qvec = [float(v) for v in query_vector]
    scored: list[dict[str, Any]] = []
    for doc in index.documents:
        score = float(vector_dot(qvec, doc.vector))
        if score <= 0.0:
            continue
        scored.append(
            {
                "document_id": doc.row.document_id,
                "row_id": doc.row.row_id,
                "score": score,
                "source_links": [link.to_dict() for link in doc.row.source_links],
                "content_digest": doc.row.content_digest,
                "vector_digest": doc.row.vector_digest,
                "disclosure": doc.row.disclosure.value,
                "tenant_id": doc.row.tenant_id,
                "family": RetrievalFamily.VECTOR.value,
                "embedding": doc.row.embedding.to_dict(),
            }
        )
    scored.sort(key=lambda item: (-float(item["score"]), str(item["document_id"])))
    for rank, item in enumerate(scored[: max(1, int(top_k))], start=1):
        item["rank"] = rank
    return scored[: max(1, int(top_k))]


# ---------------------------------------------------------------------------
# Graph-fusion index
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphIndexNode:
    """Source-linked graph node used for expansion ranking."""

    node_id: str
    document_id: str
    kind: str
    label: str
    source_links: tuple[SourceLink, ...]
    disclosure: str
    tenant_id: str
    content_digest: str
    effective_from_utc: str | None = None
    effective_to_utc: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "disclosure": self.disclosure,
            "document_id": self.document_id,
            "effective_from_utc": self.effective_from_utc,
            "effective_to_utc": self.effective_to_utc,
            "kind": self.kind,
            "label": self.label,
            "metadata": dict(self.metadata),
            "node_id": self.node_id,
            "source_links": [link.to_dict() for link in self.source_links],
            "tenant_id": self.tenant_id,
        }


@dataclass(frozen=True, slots=True)
class GraphFusionIndex:
    """Deterministic graph structure for expansion + fusion."""

    schema_version: str
    nodes: tuple[GraphIndexNode, ...]
    edges: tuple[GraphEdge, ...]
    adjacency: Mapping[str, tuple[str, ...]]  # node_id -> sorted neighbor edge_ids
    corpus_cid: str
    index_cid: str
    content_digest: str
    filters_receipt: Mapping[str, Any]
    denied_provider_call_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjacency": {k: list(v) for k, v in sorted(self.adjacency.items())},
            "content_digest": self.content_digest,
            "corpus_cid": self.corpus_cid,
            "denied_provider_call_count": self.denied_provider_call_count,
            "edges": [e.to_dict() for e in self.edges],
            "filters_receipt": dict(self.filters_receipt),
            "index_cid": self.index_cid,
            "nodes": [n.to_dict() for n in self.nodes],
            "schema_version": self.schema_version,
        }


def _document_to_graph_node(doc: PatentIndexDocument) -> GraphIndexNode:
    label = (
        doc.field_values.get(IndexField.TITLE.value)
        or doc.field_values.get(IndexField.NUMBERS.value)
        or doc.document_id
    )
    return GraphIndexNode(
        node_id=f"node:{doc.document_id}",
        document_id=doc.document_id,
        kind="document",
        label=label,
        source_links=doc.source_links,
        disclosure=doc.disclosure.value,
        tenant_id=doc.tenant_id,
        content_digest=doc.content_digest,
        effective_from_utc=doc.effective_from_utc,
        effective_to_utc=doc.effective_to_utc,
        metadata=dict(doc.metadata),
    )


def build_graph_fusion_index(
    documents: Sequence[PatentIndexDocument],
    *,
    filters: PreRankingFilters,
    edges: Sequence[GraphEdge | Mapping[str, Any]] = (),
    extra_nodes: Sequence[GraphIndexNode | Mapping[str, Any]] = (),
    corpus_cid: str = DEFAULT_CORPUS_CID,
) -> GraphFusionIndex:
    """Build a deterministic graph index after pre-ranking filters.

    Document nodes are projected from admitted documents. Additional nodes and
    edges may be supplied (e.g. from PATLAW-091 projection). Every node and
    source-derived edge must join to a source CID.
    """
    admitted_docs, _rows, applied = _admit_documents(
        documents,
        filters,
        family=RetrievalFamily.GRAPH,
        field_weights_config_cid=None,
    )

    nodes_by_id: dict[str, GraphIndexNode] = {}
    for doc in admitted_docs:
        node = _document_to_graph_node(doc)
        nodes_by_id[node.node_id] = node

    for raw in extra_nodes:
        if isinstance(raw, GraphIndexNode):
            node = raw
        elif isinstance(raw, Mapping):
            links = _require_source_links(
                raw.get("source_links") or (), field="extra_nodes.source_links"
            )
            # Admission for extra nodes
            try:
                applied.admit_row(
                    disclosure=raw.get("disclosure") or DisclosureClass.UNKNOWN.value,
                    tenant_id=str(raw.get("tenant_id") or applied.tenant_id),
                    effective_from_utc=raw.get("effective_from_utc"),
                    effective_to_utc=raw.get("effective_to_utc"),
                )
            except PreRankingFilterViolation:
                continue
            node = GraphIndexNode(
                node_id=str(raw["node_id"]),
                document_id=str(raw.get("document_id") or raw["node_id"]),
                kind=str(raw.get("kind") or "entity"),
                label=str(raw.get("label") or raw["node_id"]),
                source_links=links,
                disclosure=str(
                    raw.get("disclosure") or DisclosureClass.PUBLIC_OFFICIAL.value
                ),
                tenant_id=str(raw.get("tenant_id") or applied.tenant_id),
                content_digest=str(
                    raw.get("content_digest")
                    or content_digest_hex({"node_id": raw["node_id"]})
                ),
                effective_from_utc=raw.get("effective_from_utc"),
                effective_to_utc=raw.get("effective_to_utc"),
                metadata=dict(raw.get("metadata") or {}),
            )
        else:
            raise TypeError("extra_nodes items must be GraphIndexNode or mapping")
        if not node.source_links:
            raise MissingSourceCIDError(f"node {node.node_id} missing source links")
        nodes_by_id[node.node_id] = node

    admitted_edges: list[GraphEdge] = []
    for raw in edges:
        if isinstance(raw, GraphEdge):
            edge = raw
        elif isinstance(raw, Mapping):
            edge = GraphEdge.from_dict(raw)
        else:
            raise TypeError("edges items must be GraphEdge or mapping")
        # Filter edges by disclosure/tenant/as-of of the edge itself.
        try:
            applied.admit_row(
                disclosure=edge.disclosure,
                tenant_id=edge.tenant_id,
                effective_from_utc=edge.effective_from_utc,
                effective_to_utc=edge.effective_to_utc,
            )
        except PreRankingFilterViolation:
            continue
        if edge.provenance is EdgeProvenance.SOURCE_DERIVED and not edge.source_links:
            raise MissingSourceCIDError(
                f"source-derived edge {edge.edge_id} missing source links"
            )
        # Endpoints should exist when both are in this index; skip dangling
        # edges quietly only if neither endpoint is present.
        if (
            edge.subject_id not in nodes_by_id
            and edge.object_id not in nodes_by_id
        ):
            continue
        admitted_edges.append(edge)

    admitted_edges.sort(key=lambda e: e.edge_id)
    nodes = tuple(sorted(nodes_by_id.values(), key=lambda n: n.node_id))

    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in admitted_edges:
        adjacency[edge.subject_id].append(edge.edge_id)
        adjacency[edge.object_id].append(edge.edge_id)
    adjacency_frozen = MappingProxyType(
        {
            node_id: tuple(sorted(set(edge_ids)))
            for node_id, edge_ids in sorted(adjacency.items())
        }
    )

    payload = {
        "edges": [e.to_dict() for e in admitted_edges],
        "nodes": [n.to_dict() for n in nodes],
        "schema_version": INDEXING_SCHEMA_VERSION,
    }
    digest = content_digest_hex(payload)
    index_cid = f"bafybei{digest[:50]}"

    return GraphFusionIndex(
        schema_version=INDEXING_SCHEMA_VERSION,
        nodes=nodes,
        edges=tuple(admitted_edges),
        adjacency=adjacency_frozen,
        corpus_cid=corpus_cid,
        index_cid=index_cid,
        content_digest=digest,
        filters_receipt=MappingProxyType(applied.to_dict()),
        denied_provider_call_count=applied.denied_provider_call_count,
    )


def expand_graph(
    seed_document_ids: Sequence[str],
    index: GraphFusionIndex,
    *,
    top_k: int = 10,
    max_hops: int = 2,
) -> list[dict[str, Any]]:
    """Deterministic multi-hop graph expansion ranked by edge weight / hop."""
    if not seed_document_ids or not index.nodes:
        return []
    node_by_doc = {n.document_id: n for n in index.nodes}
    node_by_id = {n.node_id: n for n in index.nodes}
    edge_by_id = {e.edge_id: e for e in index.edges}

    seeds = [node_by_doc[d] for d in seed_document_ids if d in node_by_doc]
    if not seeds:
        # Also accept raw node ids as seeds.
        seeds = [node_by_id[d] for d in seed_document_ids if d in node_by_id]
    if not seeds:
        return []

    # BFS with accumulative score: weight / (hop + 1)
    best: dict[str, dict[str, Any]] = {}
    queue: list[tuple[str, int, float, tuple[str, ...]]] = []
    for seed in seeds:
        queue.append((seed.node_id, 0, 1.0, ()))
        best[seed.node_id] = {
            "node_id": seed.node_id,
            "document_id": seed.document_id,
            "score": 1.0,
            "path_edge_ids": (),
            "source_links": seed.source_links,
            "authority_claim": AuthorityClaim.SOURCE_BOUND,
        }

    head = 0
    while head < len(queue):
        node_id, hop, score, path = queue[head]
        head += 1
        if hop >= max_hops:
            continue
        for edge_id in index.adjacency.get(node_id, ()):
            edge = edge_by_id.get(edge_id)
            if edge is None:
                continue
            # Prefer source-derived edges for authority-bound expansion.
            if edge.provenance is EdgeProvenance.CANDIDATE:
                edge_weight = float(edge.weight) * 0.25
                claim = AuthorityClaim.REVIEW_ONLY
            elif edge.provenance is EdgeProvenance.GENERATED_SUMMARY:
                edge_weight = float(edge.weight) * 0.1
                claim = AuthorityClaim.NONE
            else:
                edge_weight = float(edge.weight)
                claim = edge.authority_claim
            neighbor = (
                edge.object_id if edge.subject_id == node_id else edge.subject_id
            )
            if neighbor not in node_by_id:
                continue
            new_score = score * edge_weight / float(hop + 1)
            new_path = path + (edge_id,)
            prev = best.get(neighbor)
            if prev is None or new_score > float(prev["score"]):
                neighbor_node = node_by_id[neighbor]
                links = neighbor_node.source_links
                if edge.source_links:
                    # Prefer edge source links when present (more specific span).
                    links = edge.source_links
                best[neighbor] = {
                    "node_id": neighbor,
                    "document_id": neighbor_node.document_id,
                    "score": new_score,
                    "path_edge_ids": new_path,
                    "source_links": links,
                    "authority_claim": claim,
                }
                queue.append((neighbor, hop + 1, new_score, new_path))

    # Drop pure seeds if expansion produced neighbors; keep seeds with score.
    ranked = sorted(
        best.values(),
        key=lambda item: (-float(item["score"]), str(item["document_id"])),
    )
    results: list[dict[str, Any]] = []
    for rank, item in enumerate(ranked[: max(1, int(top_k))], start=1):
        links = item["source_links"]
        results.append(
            {
                "node_id": item["node_id"],
                "document_id": item["document_id"],
                "score": float(item["score"]),
                "rank": rank,
                "path_edge_ids": list(item["path_edge_ids"]),
                "source_links": [
                    link.to_dict() if isinstance(link, SourceLink) else link
                    for link in links
                ],
                "authority_claim": (
                    item["authority_claim"].value
                    if isinstance(item["authority_claim"], AuthorityClaim)
                    else str(item["authority_claim"])
                ),
                "family": RetrievalFamily.GRAPH.value,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Combined bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatentIndexBundle:
    """Combined BM25 + vector + graph index build with shared filters receipt."""

    schema_version: str
    bm25: FieldedBm25Index
    vector: PinnedVectorIndex
    graph: GraphFusionIndex
    filters: PreRankingFilters
    corpus_cid: str
    config_cid: str
    model_cid: str | None
    bundle_digest: str
    atomic_chunks: tuple[AtomicChunk, ...] = ()
    index_cids: Mapping[str, str] = MappingProxyType({})

    def to_dict(self) -> dict[str, Any]:
        return {
            "atomic_chunks": [c.to_dict() for c in self.atomic_chunks],
            "bm25": self.bm25.to_dict(),
            "bundle_digest": self.bundle_digest,
            "config_cid": self.config_cid,
            "corpus_cid": self.corpus_cid,
            "filters": self.filters.to_dict(),
            "graph": self.graph.to_dict(),
            "index_cids": dict(self.index_cids),
            "model_cid": self.model_cid,
            "schema_version": self.schema_version,
            "vector": self.vector.to_dict(),
        }


def build_patent_indexes(
    documents: Sequence[PatentIndexDocument],
    *,
    filters: PreRankingFilters,
    edges: Sequence[GraphEdge | Mapping[str, Any]] = (),
    extra_nodes: Sequence[GraphIndexNode | Mapping[str, Any]] = (),
    field_weights: FieldWeightConfig | None = None,
    embedding: EmbeddingIdentity | None = None,
    corpus_cid: str = DEFAULT_CORPUS_CID,
    allow_remote: bool = False,
    remote_embedder: EmbeddingFn | None = None,
    ledger: EmbeddingCallLedger | None = None,
) -> PatentIndexBundle:
    """Build all three index families after a single pre-ranking filter pass.

    Repeat builds with identical inputs yield identical digests and payloads.
    """
    require_pre_ranking_filters(filters)
    weights = field_weights or FieldWeightConfig.default(
        config_cid=DEFAULT_EMBEDDING_CONFIG_CID
    )
    identity = embedding or default_embedding_identity(
        config_cid=weights.config_cid or DEFAULT_EMBEDDING_CONFIG_CID
    )
    call_ledger = ledger or EmbeddingCallLedger()

    # Atomic chunks for all admitted documents (claims/sections/events).
    admitted_docs, _, _ = _admit_documents(
        documents,
        filters,
        family=RetrievalFamily.BM25,
        field_weights_config_cid=weights.config_cid,
    )
    chunks: list[AtomicChunk] = []
    for doc in admitted_docs:
        chunks.extend(chunk_document_atomically(doc))
    chunks.sort(key=lambda c: (c.document_id, c.kind, c.ordinal, c.chunk_id))

    bm25 = build_fielded_bm25_index(
        documents,
        filters=filters,
        field_weights=weights,
        corpus_cid=corpus_cid,
    )
    vector = build_pinned_vector_index(
        documents,
        filters=filters,
        embedding=identity,
        corpus_cid=corpus_cid,
        allow_remote=allow_remote,
        remote_embedder=remote_embedder,
        ledger=call_ledger,
    )
    graph = build_graph_fusion_index(
        documents,
        filters=filters,
        edges=edges,
        extra_nodes=extra_nodes,
        corpus_cid=corpus_cid,
    )

    # Propagate max denied count into shared filter receipt metadata.
    denied = max(
        bm25.denied_provider_call_count,
        vector.denied_provider_call_count,
        graph.denied_provider_call_count,
        call_ledger.denied_remote_count,
    )
    filters_out = PreRankingFilters(
        schema_version=filters.schema_version,
        tenant_id=filters.tenant_id,
        as_of_utc=filters.as_of_utc,
        allowed_disclosures=filters.allowed_disclosures,
        applied=True,
        denied_provider_call_count=denied,
        filter_receipt_id=filters.filter_receipt_id,
        metadata=dict(filters.metadata),
    )
    index_cids = {
        "bm25": bm25.index_cid,
        "vector": vector.index_cid,
        "graph": graph.index_cid,
    }
    bundle_digest = content_digest_hex(
        {
            "bm25": bm25.content_digest,
            "vector": vector.content_digest,
            "graph": graph.content_digest,
            "filters": filters_out.to_dict(),
            "index_cids": index_cids,
            "schema_version": INDEXING_SCHEMA_VERSION,
        }
    )
    return PatentIndexBundle(
        schema_version=INDEXING_SCHEMA_VERSION,
        bm25=bm25,
        vector=vector,
        graph=graph,
        filters=filters_out,
        corpus_cid=corpus_cid,
        config_cid=identity.config_cid,
        model_cid=identity.model_cid,
        bundle_digest=bundle_digest,
        atomic_chunks=tuple(chunks),
        index_cids=MappingProxyType(index_cids),
    )


__all__ = [
    "INDEXING_INTERFACE",
    "INDEXING_SCHEMA_VERSION",
    "TOKENIZER_VERSION",
    "DEFAULT_CORPUS_CID",
    "DEFAULT_EMBEDDING_CONFIG_CID",
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_MODEL_ID",
    "DEFAULT_EMBEDDING_MODEL_VERSION",
    "DEFAULT_EMBEDDING_PROVIDER",
    "REMOTE_EMBEDDING_PROVIDERS",
    "AtomicChunk",
    "AtomicChunkError",
    "EmbeddingCallLedger",
    "EmbeddingFn",
    "FieldedBm25Document",
    "FieldedBm25Index",
    "FieldedTermStats",
    "GraphFusionIndex",
    "GraphIndexNode",
    "IndexingError",
    "MissingSourceCIDError",
    "PatentIndexBundle",
    "PatentIndexDocument",
    "PinnedVectorDocument",
    "PinnedVectorIndex",
    "RemoteEmbeddingDeniedError",
    "build_fielded_bm25_index",
    "build_graph_fusion_index",
    "build_patent_indexes",
    "build_pinned_vector_index",
    "chunk_document_atomically",
    "content_digest_hex",
    "default_embedding_identity",
    "default_local_embedder",
    "embed_texts_for_index",
    "expand_graph",
    "legal_tokens_present",
    "score_fielded_bm25",
    "score_pinned_vectors",
    "tokenize_patent_text",
]
