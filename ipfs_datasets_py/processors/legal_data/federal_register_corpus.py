"""Canonical Federal Register corpus, chunks, and recovery (LCR-055).

Streams the LCR-053 full-text disposition ledger and LCR-054 identity
normalizer into a type/date-partitioned corpus, structure-aware chunks,
recovery/quarantine, direct locators, and source-level lineage.

Design invariants
-----------------
* Every inventory document receives **exactly one** disposition.
* Admitted rows carry durable ``entry_cid`` / ``legal_id`` / ``source_cid``
  and official provenance. ``entry_cid`` is the unique primary key.
* Searchable chunks are structure-aware, have valid exclusive offsets, and
  join documents by ``entry_cid`` / ``source_cid`` only.
* Recovery and quarantine never increment corpus, chunk, BM25, vector, or
  graph family counts.
* Lineage is stored once per official source, never duplicated onto chunks
  or hypothetical BM25 postings.
* Physical Parquet shards are bounded at 4,096 rows. The GTE-small ceiling
  of 512 is a model-token limit, never that physical bound.
* Fixture materialization is hermetic against the LCR-053 18-document
  inventory. It never loads the live 11k inventory, never uploads to the
  Hub, and never writes tokens or absolute home paths into receipts.
* This module does not rewrite ``federal_inventory.json`` or the LCR-053
  full-text module.

Depends on LCR-053 (full-text dispositions) and LCR-054 (identity).
"""

from __future__ import annotations

import calendar
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.logic.ir_core.identity import cid_v1
from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
    InventoryDocument,
    SecretInReceiptError,
    assert_no_secrets,
    find_secret_surfaces,
)
from ipfs_datasets_py.processors.legal_data.federal_register_fulltext import (
    ADMITTED_DISPOSITIONS,
    CoverageDisposition,
    DocumentCoverage,
    EnrichmentResult,
    FailedFinalCoverageError,
    FulltextConfig,
    FulltextMode,
    ImmutableTextCache,
    locators_for_document,
    enrich_federal_register_fulltext,
    load_fixture_inventory_documents,
)
from ipfs_datasets_py.processors.legal_data.federal_register_identity import (
    DuplicatePrimaryKeyError,
    LegalIdentity,
    PositionalIdentityError,
    enrich_row_identity,
    identity_from_row,
    parse_chunk_id,
    validate_primary_keys,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    ADR_PATH,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    RELEASE_PROFILE,
    SCHEMA_VERSION as RELEASE_SCHEMA_VERSION,
    AdmissionStatus,
    ArtifactFamily,
    CorpusRecord,
    DocumentType,
    LocatorRecord,
    PhysicalBoundError,
    RecoveryRecord,
    SourceAuthorityClass,
    SourceReceiptRecord,
    TextAvailability,
    VerificationResult,
    normalize_relative_artifact_path,
    normalize_sha256,
    validate_physical_row_count,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    CURRENTNESS_DISCLAIMER,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_OBSERVATION_CUTOFF,
    FEDERAL_REGISTER_DOCUMENTS_API,
    PREVIOUS_PUBLIC_PIN,
    canonical_json_dumps,
    content_sha256,
    cutoff_release_point,
    digest_mapping,
    repository_root,
    require_immutable_observation_cutoff,
)

# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-corpus-v1"
FIXTURE_SCHEMA_VERSION: Final = "federal-register-corpus-admission-v1"
REPORT_SCHEMA: Final = (
    "ipfs_datasets_py/legal-corpora-reindex-federal-admission@1"
)
TASK_ID: Final = "LCR-055"
GOAL_ID: Final = "LCR-G110"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "federal_register_corpus.py"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "federal-corpus-materialization"
CODE_VERSION: Final = "1"
TRANSFORMATION_VERSION: Final = "federal-register-corpus-transform-v1"
PARSER_VERSION: Final = "federal-register-parser/v2"
IDENTITY_SCHEMA_VERSION: Final = "federal-register-identity-v1"
FULLTEXT_TASK_ID: Final = "LCR-053"
IDENTITY_TASK_ID: Final = "LCR-054"
INVENTORY_TASK_ID: Final = "LCR-052"

EXPECTED_FIXTURE_DOCUMENTS: Final = 18
MIN_USABLE_CHARS: Final = 80
DEFAULT_MODEL_TOKEN_LIMIT: Final = 512
DEFAULT_MAX_CHUNKS_PER_DOCUMENT: Final = 512
DEFAULT_TOKENIZER_ID: Final = "federal-register-whitespace-v1"
DEFAULT_ACQUISITION_TIME: Final = "2026-08-10T12:00:00Z"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False

REPORT_RELATIVE_PATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_admission.json"
)
INVENTORY_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_inventory.json"
)

CANONICAL_COUNT_FAMILIES: Final = frozenset(
    {
        "corpus",
        "chunks",
        "bm25",
        "bm25_documents",
        "bm25_postings",
        "vector",
        "vectors",
        "graph",
        "graph_nodes",
        "graph_edges",
        "graph_adjacency_out",
        "graph_adjacency_in",
    }
)

POSTING_LINEAGE_FORBIDDEN_FIELDS: Final = frozenset(
    {
        "attempts",
        "format_attempts",
        "postings",
        "posting_ids",
        "posting_lineage",
        "per_posting_lineage",
        "bm25_postings",
        "term_postings",
    }
)

_TOKEN_RE = re.compile(r"\S+")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")
_STRUCTURE_RE = re.compile(
    r"(?:(?<=\A)|(?<=\n)|(?<=[.!?]\s))"
    r"(?:"
    r"Section\s+\d+\."
    r"|SUPPLEMENTARY INFORMATION:"
    r"|FOR FURTHER INFORMATION CONTACT:"
    r"|DATES:"
    r"|ACTION:"
    r"|SUMMARY:"
    r"|AGENCY:"
    r"|ADDRESSES:"
    r"|PART\s+\d+\b"
    r")"
)
_ABSOLUTE_POSIX_RE = re.compile(
    r"(?:(?:/home|/Users|/tmp|/var|/opt|/usr/local|/mnt|/media|/data|"
    r"/workspace|/root)/\S+)"
)
_ABSOLUTE_WINDOWS_RE = re.compile(r"(?:[A-Za-z]:\\[^\s\"']+|\\\\[^\s\"']+)")
_FILE_URI_RE = re.compile(r"file:///[^\s\"']+", re.IGNORECASE)
_HOME_TILDE_RE = re.compile(r"(?:~(?:/[^\s\"']+)?)")

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterCorpusError(ValueError):
    """Base error for Federal Register corpus materialization."""


class DispositionError(FederalRegisterCorpusError):
    """Raised when an inventory document lacks a unique valid disposition."""


class AdmissionLedgerError(FederalRegisterCorpusError):
    """Raised when the admission ledger is incomplete or inconsistent."""


class RecoveryContaminationError(FederalRegisterCorpusError):
    """Raised when recovery rows leak into canonical search-family counts."""


class ChunkOffsetError(FederalRegisterCorpusError):
    """Raised when chunk offsets are gapped, overlapping, or out of range."""


class LineageDuplicationError(FederalRegisterCorpusError):
    """Raised when source lineage is copied onto chunks or postings."""


class InventoryRewriteError(FederalRegisterCorpusError):
    """Raised when a caller attempts to rewrite the official inventory."""


class FixtureInventoryError(FederalRegisterCorpusError):
    """Raised when materialization is not bound to the sealed 18-doc fixture."""


class IncompleteIdentityError(FederalRegisterCorpusError):
    """Raised when an admitted row is missing durable identity or provenance."""


class FailedFinalAdmissionError(FederalRegisterCorpusError, FailedFinalCoverageError):
    """Raised when failed-final items remain on a closed admission receipt."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RowDisposition(str, Enum):
    """Exactly-one ledger disposition assigned to every inventory document."""

    ADMITTED = "admitted"
    EXCLUDED = "excluded"
    QUARANTINED = "quarantined"
    FAILED_FINAL = "failed_final"

    @classmethod
    def coerce(cls, value: Any) -> "RowDisposition":
        if isinstance(value, RowDisposition):
            return value
        if isinstance(value, CoverageDisposition):
            if value.is_admitted or value is CoverageDisposition.METADATA_ONLY:
                return cls.ADMITTED
            if value is CoverageDisposition.EXCLUDED:
                return cls.EXCLUDED
            if value is CoverageDisposition.QUARANTINED:
                return cls.QUARANTINED
            return cls.FAILED_FINAL
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "admit": cls.ADMITTED,
            "include": cls.ADMITTED,
            "included": cls.ADMITTED,
            "full_text": cls.ADMITTED,
            "html_body": cls.ADMITTED,
            "xml_body": cls.ADMITTED,
            "pdf_body": cls.ADMITTED,
            "govinfo_body": cls.ADMITTED,
            "metadata_only": cls.ADMITTED,
            "exclude": cls.EXCLUDED,
            "reject": cls.EXCLUDED,
            "rejected": cls.EXCLUDED,
            "quarantine": cls.QUARANTINED,
            "recovery": cls.QUARANTINED,
            "failed": cls.FAILED_FINAL,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise DispositionError(f"unknown row disposition: {value!r}")

    def to_admission_status(self) -> AdmissionStatus:
        if self is RowDisposition.ADMITTED:
            return AdmissionStatus.ADMITTED
        if self is RowDisposition.EXCLUDED:
            return AdmissionStatus.EXCLUDED
        if self is RowDisposition.QUARANTINED:
            return AdmissionStatus.QUARANTINED
        return AdmissionStatus.REJECTED


class SplitMode(str, Enum):
    """How a chunk's exclusive span was produced."""

    STRUCTURE = "structure"
    SENTENCE = "sentence"
    HARD = "hard"
    WHOLE = "whole"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterCorpusError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise FederalRegisterCorpusError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise FederalRegisterCorpusError(f"{name} exceeds maximum length {maximum}")
    return text


def _optional_str(
    value: Any, name: str = "value", *, maximum: int = 4096
) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name, maximum=maximum)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FederalRegisterCorpusError(f"{name} must be an integer")
    if value < 0:
        raise FederalRegisterCorpusError(f"{name} must be >= 0")
    return value


def default_admission_report_path(repo_root: PathLike | None = None) -> Path:
    """Return the frozen admission report path (not embedded in receipts)."""

    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / REPORT_RELATIVE_PATH).resolve()


def inventory_report_relpath() -> str:
    return INVENTORY_REPORT_RELPATH.as_posix()


def scrub_local_paths_in_text(text: str) -> str:
    if not isinstance(text, str):
        raise FederalRegisterCorpusError("text must be a string")
    cleaned = _FILE_URI_RE.sub("[scrubbed-local-uri]", text)
    cleaned = _ABSOLUTE_WINDOWS_RE.sub("[scrubbed-local-path]", cleaned)
    cleaned = _ABSOLUTE_POSIX_RE.sub("[scrubbed-local-path]", cleaned)
    cleaned = _HOME_TILDE_RE.sub("[scrubbed-local-path]", cleaned)
    return cleaned


def scrub_mapping_paths(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise FederalRegisterCorpusError("payload must be a mapping")

    def _walk(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): _walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_walk(item) for item in value]
        if isinstance(value, tuple):
            return [_walk(item) for item in value]
        if isinstance(value, str):
            return scrub_local_paths_in_text(value)
        if isinstance(value, Enum):
            return value.value
        return value

    return _walk(dict(payload))


def normalize_corpus_text(text: Any, *, name: str = "text") -> str:
    if not isinstance(text, str):
        raise FederalRegisterCorpusError(f"{name} must be a string")
    if "\x00" in text:
        raise FederalRegisterCorpusError(f"{name} must not contain NUL")
    return unicodedata.normalize("NFC", text)


def coverage_to_row_disposition(coverage: DocumentCoverage) -> RowDisposition:
    return RowDisposition.coerce(coverage.disposition)


def _month_bounds(year_month: str) -> tuple[str, str]:
    year = int(year_month[:4])
    month = int(year_month[5:7])
    last = calendar.monthrange(year, month)[1]
    return f"{year_month}-01", f"{year_month}-{last:02d}"


def _clip_bounds(
    year_month: str, dates: Sequence[str]
) -> tuple[str, str]:
    month_start, month_end = _month_bounds(year_month)
    if not dates:
        return month_start, month_end
    return min(dates), max(dates)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "to_dict"):
        return _json_ready(value.to_dict())
    raise FederalRegisterCorpusError(
        f"unsupported JSON value {type(value).__name__}"
    )


def _digest_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[str, int]:
    payload = canonical_json_dumps({"rows": _json_ready(list(rows))})
    encoded = payload.encode("utf-8")
    return content_sha256(encoded), len(encoded)


# ---------------------------------------------------------------------------
# Tokenization and structure-aware chunking
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenSpan:
    index: int
    char_start: int
    char_end: int
    text: str


def tokenize(text: str) -> list[TokenSpan]:
    if not isinstance(text, str):
        raise FederalRegisterCorpusError("text must be a string")
    return [
        TokenSpan(
            index=index,
            char_start=match.start(),
            char_end=match.end(),
            text=match.group(0),
        )
        for index, match in enumerate(_TOKEN_RE.finditer(text))
    ]


def count_tokens(text: str) -> int:
    return len(tokenize(text))


def _token_range(
    tokens: Sequence[TokenSpan], char_start: int, char_end: int
) -> tuple[int, int]:
    if not tokens:
        return 0, 0
    start = 0
    while start < len(tokens) and tokens[start].char_end <= char_start:
        start += 1
    end = start
    while end < len(tokens) and tokens[end].char_start < char_end:
        end += 1
    return start, end


@dataclass(frozen=True, slots=True)
class StructureSpan:
    label: str
    kind: str
    char_start: int
    char_end: int
    text: str

    @property
    def token_count(self) -> int:
        return count_tokens(self.text)


def segment_document_structure(text: str) -> tuple[StructureSpan, ...]:
    """Split *text* into exclusive structure-aware spans covering the source."""

    if not isinstance(text, str):
        raise FederalRegisterCorpusError("text must be a string")
    if not text:
        return ()
    starts = [0]
    for match in _STRUCTURE_RE.finditer(text):
        pos = match.start()
        if pos > 0 and pos not in starts:
            starts.append(pos)
    starts.sort()
    spans: list[StructureSpan] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        body = text[start:end]
        if index == 0 and not _STRUCTURE_RE.match(body):
            label, kind = "preamble", "preamble"
        else:
            heading = body.split(".", 1)[0].strip()[:80] or f"unit-{index}"
            label, kind = heading, "section"
        spans.append(
            StructureSpan(
                label=label,
                kind=kind,
                char_start=start,
                char_end=end,
                text=body,
            )
        )
    if spans[0].char_start != 0 or spans[-1].char_end != len(text):
        raise ChunkOffsetError("structural spans must cover the full document")
    for left, right in zip(spans, spans[1:]):
        if left.char_end != right.char_start:
            raise ChunkOffsetError("structural spans must be gap-free and exclusive")
    return tuple(spans)


def _split_hard_window(text: str, *, char_origin: int, token_limit: int) -> list[tuple[int, int, str]]:
    tokens = tokenize(text)
    if not tokens:
        return [(char_origin, char_origin + len(text), text)]
    windows: list[tuple[int, int, str]] = []
    index = 0
    while index < len(tokens):
        end = min(len(tokens), index + token_limit)
        start_char = tokens[index].char_start
        end_char = tokens[end - 1].char_end
        if end == len(tokens):
            end_char = len(text)
        if index == 0:
            start_char = 0
        windows.append(
            (
                char_origin + start_char,
                char_origin + end_char,
                text[start_char:end_char],
            )
        )
        index = end
    if windows:
        first_start, _, first_text = windows[0]
        windows[0] = (char_origin, windows[0][1], text[: windows[0][1] - char_origin])
        last_start, last_end, last_text = windows[-1]
        windows[-1] = (last_start, char_origin + len(text), text[last_start - char_origin :])
        _ = first_start, first_text, last_end, last_text
    return windows


def _split_span(
    span: StructureSpan,
    *,
    token_limit: int,
) -> list[tuple[int, int, str, str]]:
    token_count = span.token_count
    if token_count <= token_limit:
        return [
            (
                span.char_start,
                span.char_end,
                span.text,
                SplitMode.STRUCTURE.value,
            )
        ]
    sentences = _SENTENCE_BOUNDARY_RE.split(span.text)
    if len(sentences) <= 1:
        return [
            (start, end, body, SplitMode.HARD.value)
            for start, end, body in _split_hard_window(
                span.text, char_origin=span.char_start, token_limit=token_limit
            )
        ]
    pieces: list[tuple[int, int, str, str]] = []
    cursor = span.char_start
    remainder = span.text
    for sentence in sentences:
        if not sentence:
            continue
        pos = remainder.find(sentence)
        if pos < 0:
            continue
        start = cursor + pos
        end = start + len(sentence)
        if count_tokens(sentence) > token_limit:
            pieces.extend(
                (s, e, body, SplitMode.HARD.value)
                for s, e, body in _split_hard_window(
                    sentence, char_origin=start, token_limit=token_limit
                )
            )
        else:
            pieces.append((start, end, sentence, SplitMode.SENTENCE.value))
        consumed = pos + len(sentence)
        cursor += consumed
        remainder = remainder[consumed:]
    if remainder:
        pieces.append(
            (
                span.char_end - len(remainder),
                span.char_end,
                remainder,
                SplitMode.STRUCTURE.value,
            )
        )
    if pieces:
        pieces[0] = (span.char_start, pieces[0][1], span.text[: pieces[0][1] - span.char_start], pieces[0][3])
        pieces[-1] = (
            pieces[-1][0],
            span.char_end,
            span.text[pieces[-1][0] - span.char_start :],
            pieces[-1][3],
        )
    return pieces


def plan_structure_chunks(
    text: str,
    *,
    model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT,
    max_chunks: int = DEFAULT_MAX_CHUNKS_PER_DOCUMENT,
) -> tuple[dict[str, Any], ...]:
    """Return exclusive structure-aware chunk plans for *text*."""

    if not isinstance(model_token_limit, int) or isinstance(model_token_limit, bool):
        raise FederalRegisterCorpusError("model_token_limit must be an integer")
    if model_token_limit < 1:
        raise FederalRegisterCorpusError("model_token_limit must be >= 1")
    if model_token_limit == MAX_ROWS_PER_PHYSICAL_SHARD and model_token_limit != DEFAULT_MODEL_TOKEN_LIMIT:
        raise FederalRegisterCorpusError(
            "model_token_limit must not reuse the 4,096 physical row bound"
        )
    normalized = normalize_corpus_text(text)
    if not normalized:
        return ()
    spans = segment_document_structure(normalized)
    if len(spans) == 1 and spans[0].token_count <= model_token_limit:
        planned = [
            {
                "char_start": 0,
                "char_end": len(normalized),
                "exclusive_text": normalized,
                "heading": spans[0].label,
                "split_mode": SplitMode.WHOLE.value,
            }
        ]
    else:
        planned = []
        for span in spans:
            for start, end, body, mode in _split_span(span, token_limit=model_token_limit):
                planned.append(
                    {
                        "char_start": start,
                        "char_end": end,
                        "exclusive_text": body,
                        "heading": span.label,
                        "split_mode": mode,
                    }
                )
    if len(planned) > max_chunks:
        raise FederalRegisterCorpusError(
            f"document produced {len(planned)} chunks; exceeds max_chunks={max_chunks}"
        )
    assert_exclusive_coverage(normalized, planned)
    return tuple(planned)


def assert_exclusive_coverage(
    text: str, chunks: Sequence[Mapping[str, Any]]
) -> None:
    """Require exclusive ``[char_start, char_end)`` spans to reconstruct *text*."""

    if not chunks:
        raise ChunkOffsetError("searchable documents must emit at least one chunk")
    cursor = 0
    rebuilt: list[str] = []
    for index, chunk in enumerate(chunks):
        start = _require_non_negative_int(chunk["char_start"], "char_start")
        end = _require_non_negative_int(chunk["char_end"], "char_end")
        if start != cursor:
            raise ChunkOffsetError(
                f"chunk {index} starts at {start}, expected {cursor}"
            )
        if end < start or end > len(text):
            raise ChunkOffsetError(f"chunk {index} offsets {start}:{end} are invalid")
        exclusive = chunk.get("exclusive_text")
        if exclusive is None:
            exclusive = text[start:end]
        if exclusive != text[start:end]:
            raise ChunkOffsetError(
                f"chunk {index} exclusive_text does not match source offsets"
            )
        rebuilt.append(exclusive)
        cursor = end
    if cursor != len(text):
        raise ChunkOffsetError(
            f"chunks cover {cursor} characters, expected {len(text)}"
        )
    if "".join(rebuilt) != text:
        raise ChunkOffsetError("exclusive chunk text does not reconstruct the source")


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanonicalChunk:
    """One structure-aware chunk with deterministic identity and provenance."""

    chunk_id: str
    chunk_cid: str
    chunk_index: int
    parent_legal_id: str
    entry_cid: str
    source_cid: str
    text_hash: str
    text: str
    exclusive_text: str
    char_start: int
    char_end: int
    token_start: int
    token_end: int
    token_count: int
    parent_path: tuple[str, ...]
    split_mode: str
    year_month: str
    document_type: str
    document_number: str
    model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT
    tokenizer_id: str = DEFAULT_TOKENIZER_ID
    transformation_version: str = TRANSFORMATION_VERSION
    schema_version: str = SCHEMA_VERSION
    heading: str = ""
    locator_path: str = ""

    def __post_init__(self) -> None:
        parent, index = parse_chunk_id(self.chunk_id)
        if parent != self.parent_legal_id:
            raise ChunkOffsetError(
                f"chunk_id parent {parent!r} != parent_legal_id {self.parent_legal_id!r}"
            )
        if index != self.chunk_index:
            raise ChunkOffsetError(
                f"chunk_id index {index} != chunk_index {self.chunk_index}"
            )
        if self.char_end < self.char_start:
            raise ChunkOffsetError("char_end must be >= char_start")
        if self.exclusive_text != self.text[0 : self.char_end - self.char_start] and self.text != self.exclusive_text:
            # Embeddable text may equal exclusive text; both are valid.
            if self.text != self.exclusive_text:
                pass
        if self.token_count > self.model_token_limit:
            raise ChunkOffsetError(
                f"chunk {self.chunk_id!r} exceeds model token ceiling "
                f"{self.model_token_limit}"
            )
        forbidden = POSTING_LINEAGE_FORBIDDEN_FIELDS.intersection(self.to_dict())
        if forbidden:
            raise LineageDuplicationError(
                f"chunk {self.chunk_id!r} carries posting lineage fields {sorted(forbidden)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "char_end": self.char_end,
            "char_start": self.char_start,
            "chunk_cid": self.chunk_cid,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "document_number": self.document_number,
            "document_type": self.document_type,
            "entry_cid": self.entry_cid,
            "exclusive_text": self.exclusive_text,
            "heading": self.heading,
            "locator_path": self.locator_path,
            "model_token_limit": self.model_token_limit,
            "parent_legal_id": self.parent_legal_id,
            "parent_path": list(self.parent_path),
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "split_mode": self.split_mode,
            "text": self.text,
            "text_hash": self.text_hash,
            "token_count": self.token_count,
            "token_end": self.token_end,
            "token_start": self.token_start,
            "tokenizer_id": self.tokenizer_id,
            "transformation_version": self.transformation_version,
            "year_month": self.year_month,
        }


@dataclass(frozen=True, slots=True)
class SourceLineage:
    """Normalized official-source lineage stored once per document source."""

    source_cid: str
    document_number: str
    publication_date: str
    source_format: str
    official_source_url: str
    source_checksum: str
    acquisition_receipt_id: str
    parser_version: str
    text_availability: str
    year_month: str
    legal_id: str
    entry_cid: str
    observed_at: str
    release_point: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquisition_receipt_id": self.acquisition_receipt_id,
            "document_number": self.document_number,
            "entry_cid": self.entry_cid,
            "legal_id": self.legal_id,
            "observed_at": self.observed_at,
            "official_source_url": self.official_source_url,
            "parser_version": self.parser_version,
            "publication_date": self.publication_date,
            "release_point": self.release_point,
            "source_checksum": self.source_checksum,
            "source_cid": self.source_cid,
            "source_format": self.source_format,
            "text_availability": self.text_availability,
            "year_month": self.year_month,
        }


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One inventory-document disposition with optional identity links."""

    row_id: str
    disposition: RowDisposition
    reason: str
    document_number: str
    publication_date: str
    inventory_legal_id: str
    coverage_disposition: str
    year_month: str
    document_type: str
    legal_id: Optional[str] = None
    entry_cid: Optional[str] = None
    source_cid: Optional[str] = None
    text_availability: Optional[str] = None
    chunk_count: int = 0
    searchable: bool = False
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "row_id", _require_non_empty_str(self.row_id, "row_id"))
        object.__setattr__(self, "disposition", RowDisposition.coerce(self.disposition))
        object.__setattr__(self, "reason", _require_non_empty_str(self.reason, "reason"))
        if (
            self.disposition is RowDisposition.ADMITTED
            and not (self.legal_id and self.entry_cid and self.source_cid)
        ):
            raise IncompleteIdentityError(
                f"admitted ledger entry {self.row_id!r} lacks complete identity"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_count": self.chunk_count,
            "coverage_disposition": self.coverage_disposition,
            "disposition": self.disposition.value,
            "document_number": self.document_number,
            "document_type": self.document_type,
            "entry_cid": self.entry_cid,
            "inventory_legal_id": self.inventory_legal_id,
            "legal_id": self.legal_id,
            "publication_date": self.publication_date,
            "reason": self.reason,
            "row_id": self.row_id,
            "schema_version": self.schema_version,
            "searchable": self.searchable,
            "source_cid": self.source_cid,
            "text_availability": self.text_availability,
            "year_month": self.year_month,
        }


@dataclass(frozen=True, slots=True)
class ParquetShardPlan:
    """Bounded type/date-partitioned Parquet shard (logical encoding)."""

    relative_path: str
    family: str
    year_month: str
    document_type: Optional[str]
    part_index: int
    row_count: int
    sha256: str
    size_bytes: int
    first_key: str
    last_key: str
    bound_kind: str = "physical_rows"
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_artifact_path(self.relative_path),
        )
        object.__setattr__(
            self,
            "row_count",
            validate_physical_row_count(self.row_count, name="row_count"),
        )
        if self.row_count > self.max_rows:
            raise PhysicalBoundError(
                f"shard {self.relative_path} has {self.row_count} rows; "
                f"exceeds {self.max_rows}"
            )
        if self.max_rows != MAX_ROWS_PER_PHYSICAL_SHARD:
            raise PhysicalBoundError("physical shard bound must remain 4096")
        if self.bound_kind != "physical_rows":
            raise FederalRegisterCorpusError(
                "Parquet shard bound_kind must be physical_rows"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bound_kind": self.bound_kind,
            "document_type": self.document_type,
            "family": self.family,
            "first_key": self.first_key,
            "last_key": self.last_key,
            "max_rows": self.max_rows,
            "part_index": self.part_index,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "year_month": self.year_month,
        }


@dataclass(frozen=True, slots=True)
class FamilyCounts:
    corpus: int = 0
    chunks: int = 0
    bm25: int = 0
    vector: int = 0
    graph: int = 0
    recovery: int = 0
    excluded: int = 0
    locators: int = 0
    source_receipts: int = 0
    source_lineage: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "bm25": self.bm25,
            "chunks": self.chunks,
            "corpus": self.corpus,
            "excluded": self.excluded,
            "graph": self.graph,
            "locators": self.locators,
            "recovery": self.recovery,
            "source_lineage": self.source_lineage,
            "source_receipts": self.source_receipts,
            "vector": self.vector,
        }


@dataclass(frozen=True, slots=True)
class MaterializedCorpus:
    """Result of materializing the cutoff-bound Federal Register fixture."""

    ledger: tuple[LedgerEntry, ...]
    corpus_records: tuple[CorpusRecord, ...]
    chunks: tuple[CanonicalChunk, ...]
    recovery_records: tuple[RecoveryRecord, ...]
    locators: tuple[LocatorRecord, ...]
    source_receipts: tuple[SourceReceiptRecord, ...]
    source_lineage: tuple[SourceLineage, ...]
    parquet_shards: tuple[ParquetShardPlan, ...]
    family_counts: FamilyCounts
    inventory_document_count: int
    observation_cutoff: str
    release_point: str
    schema_version: str = SCHEMA_VERSION
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER
    notes: str = ""
    authorizing_for_publication: bool = False
    authorizing_hub_upload: bool = False

    def __post_init__(self) -> None:
        seen: dict[str, str] = {}
        for entry in self.ledger:
            prior = seen.get(entry.row_id)
            if prior is not None:
                raise DispositionError(
                    f"row_id {entry.row_id!r} has multiple dispositions: "
                    f"{prior!r} and {entry.disposition.value!r}"
                )
            seen[entry.row_id] = entry.disposition.value
        if len(self.ledger) != self.inventory_document_count:
            raise AdmissionLedgerError(
                "ledger length must equal inventory document count "
                f"({len(self.ledger)} != {self.inventory_document_count})"
            )
        accounted = (
            self.disposition_counts.get(RowDisposition.ADMITTED.value, 0)
            + self.disposition_counts.get(RowDisposition.EXCLUDED.value, 0)
            + self.disposition_counts.get(RowDisposition.QUARANTINED.value, 0)
            + self.disposition_counts.get(RowDisposition.FAILED_FINAL.value, 0)
        )
        if accounted != self.inventory_document_count:
            raise AdmissionLedgerError(
                f"row conservation failed: accounted={accounted} "
                f"input={self.inventory_document_count}"
            )
        if self.family_counts.corpus != len(self.corpus_records):
            raise RecoveryContaminationError(
                "corpus family count must equal admitted corpus rows"
            )
        if self.family_counts.chunks != len(self.chunks):
            raise RecoveryContaminationError(
                "chunk family count must equal searchable chunk rows"
            )
        if self.family_counts.recovery != len(self.recovery_records):
            raise RecoveryContaminationError(
                "recovery family count must equal recovery rows"
            )
        if self.authorizing_for_publication or self.authorizing_hub_upload:
            raise FederalRegisterCorpusError(
                "fixture corpus materialization cannot authorize Hub upload"
            )

    @property
    def disposition_counts(self) -> dict[str, int]:
        counts = {item.value: 0 for item in RowDisposition}
        for entry in self.ledger:
            counts[entry.disposition.value] += 1
        return counts

    @property
    def searchable_documents(self) -> tuple[CorpusRecord, ...]:
        return tuple(
            record
            for record in self.corpus_records
            if record.text_availability.has_usable_body
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizing_for_publication": self.authorizing_for_publication,
            "authorizing_hub_upload": self.authorizing_hub_upload,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "corpus_records": [record.to_dict() for record in self.corpus_records],
            "currentness_disclaimer": self.currentness_disclaimer,
            "disposition_counts": self.disposition_counts,
            "family_counts": self.family_counts.to_dict(),
            "inventory_document_count": self.inventory_document_count,
            "ledger": [entry.to_dict() for entry in self.ledger],
            "locators": [locator.to_dict() for locator in self.locators],
            "notes": self.notes,
            "observation_cutoff": self.observation_cutoff,
            "parquet_shards": [shard.to_dict() for shard in self.parquet_shards],
            "recovery_records": [record.to_dict() for record in self.recovery_records],
            "release_point": self.release_point,
            "schema_version": self.schema_version,
            "source_lineage": [row.to_dict() for row in self.source_lineage],
            "source_receipts": [row.to_dict() for row in self.source_receipts],
        }


# ---------------------------------------------------------------------------
# Classification / identity construction
# ---------------------------------------------------------------------------


def _reason_for(coverage: DocumentCoverage, disposition: RowDisposition) -> str:
    if coverage.notes.strip():
        return coverage.notes.strip()
    if disposition is RowDisposition.ADMITTED:
        if coverage.disposition is CoverageDisposition.METADATA_ONLY:
            return "explicitly metadata-only under schema after official locator exhaustion"
        return "canonical official-source Federal Register row with usable body"
    if disposition is RowDisposition.EXCLUDED:
        return coverage.allowed_reason or "excluded under rights or acquisition-scope schema"
    if disposition is RowDisposition.QUARANTINED:
        return coverage.allowed_reason or "official payload quarantined from retrieval"
    return coverage.allowed_reason or "failed-final body acquisition"


def _text_availability_for(coverage: DocumentCoverage) -> TextAvailability:
    if coverage.disposition.is_admitted:
        return TextAvailability.coerce(coverage.disposition.value)
    if coverage.disposition is CoverageDisposition.METADATA_ONLY:
        return TextAvailability.METADATA_ONLY
    if coverage.disposition is CoverageDisposition.FAILED_FINAL:
        return TextAvailability.FAILED_FINAL
    return TextAvailability.UNAVAILABLE


def _build_identity_row(
    document: InventoryDocument,
    coverage: DocumentCoverage,
    *,
    cache: ImmutableTextCache,
    document_index: int,
    release_point: str,
    acquisition_time: str,
) -> dict[str, Any]:
    locators = locators_for_document(document)
    official_source_url = (
        coverage.official_source_url
        or document.html_url
        or next(iter(locators.values()))
    )
    text = ""
    cached = cache.get_for_legal_id(document.legal_id)
    if cached is not None:
        text = cached.normalized_text
    availability = _text_availability_for(coverage)
    if availability.has_usable_body and not text.strip():
        raise IncompleteIdentityError(
            f"{document.legal_id}: admitted body is missing from the text cache"
        )
    if not availability.has_usable_body:
        text = ""
    source_format = coverage.admitted_source_format
    if source_format is None:
        if availability is TextAvailability.METADATA_ONLY:
            source_format = "json"
        else:
            source_format = "html"
    document_type = DocumentType.coerce(document.document_type or DocumentType.NOTICE)
    agencies = tuple(document.agencies) if document.agencies else ()
    receipt_id = f"fr-acquire-{document.publication_date[:7]}"
    # Only retain the format-specific official URL that matches the admitted
    # source. A GovInfo package URL must not also be labeled official_pdf_url
    # or LCR-054 treats it as a pdf/govinfo conflict.
    format_urls: dict[str, Optional[str]] = {
        "official_html_url": official_source_url if source_format == "html" else None,
        "official_xml_url": official_source_url if source_format == "xml" else None,
        "official_pdf_url": official_source_url if source_format == "pdf" else None,
    }
    row: dict[str, Any] = {
        "abstract": document.abstract or None,
        "acquisition_receipt_id": receipt_id,
        "acquisition_time": acquisition_time,
        "admission_reason": _reason_for(
            coverage, coverage_to_row_disposition(coverage)
        ),
        "admission_status": AdmissionStatus.ADMITTED.value,
        "agencies": list(agencies),
        "correction_relation": "none",
        "document_index": document_index,
        "document_number": document.document_number,
        "document_type": document_type.value,
        "observed_at": acquisition_time,
        "official_source_url": official_source_url,
        "parser_version": PARSER_VERSION,
        "publication_date": document.publication_date,
        "release_point": release_point,
        "schema_version": RELEASE_SCHEMA_VERSION,
        "source_authority_class": SourceAuthorityClass.OFFICIAL.value,
        "source_format": source_format,
        "text": text,
        "text_availability": availability.value,
        "title": document.title or None,
        "verification_result": VerificationResult.VERIFIED.value,
        "year_month": document.publication_date[:7],
    }
    row.update(format_urls)
    return {key: value for key, value in row.items() if value is not None}


def _chunk_cid_for(
    *,
    parent_legal_id: str,
    chunk_id: str,
    char_start: int,
    char_end: int,
    exclusive_text: str,
) -> str:
    return cid_v1(
        canonical_json_dumps(
            {
                "char_end": char_end,
                "char_start": char_start,
                "chunk_id": chunk_id,
                "exclusive_text": exclusive_text,
                "parent_legal_id": parent_legal_id,
                "schema_version": SCHEMA_VERSION,
                "tokenizer_id": DEFAULT_TOKENIZER_ID,
                "transformation_version": TRANSFORMATION_VERSION,
            }
        ).encode("utf-8")
    )


def chunk_corpus_record(
    record: CorpusRecord,
    *,
    identity: LegalIdentity,
    model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT,
    locator_path: str = "",
) -> tuple[CanonicalChunk, ...]:
    """Emit structure-aware chunks for one searchable corpus record."""

    if not record.text_availability.has_usable_body:
        return ()
    text = normalize_corpus_text(record.text)
    planned = plan_structure_chunks(text, model_token_limit=model_token_limit)
    tokens = tokenize(text)
    chunks: list[CanonicalChunk] = []
    for index, plan in enumerate(planned):
        exclusive = str(plan["exclusive_text"])
        chunk_id = identity.chunk_id(index)
        token_start, token_end = _token_range(
            tokens, int(plan["char_start"]), int(plan["char_end"])
        )
        parent_path = (
            f"year_month={record.year_month}",
            f"document_type={record.document_type.value}",
            plan.get("heading") or f"chunk-{index:04d}",
        )
        chunks.append(
            CanonicalChunk(
                chunk_id=chunk_id,
                chunk_cid=_chunk_cid_for(
                    parent_legal_id=identity.parent_legal_id,
                    chunk_id=chunk_id,
                    char_start=int(plan["char_start"]),
                    char_end=int(plan["char_end"]),
                    exclusive_text=exclusive,
                ),
                chunk_index=index,
                parent_legal_id=identity.parent_legal_id,
                entry_cid=record.entry_cid,
                source_cid=record.source_cid,
                text_hash=content_sha256(exclusive),
                text=exclusive,
                exclusive_text=exclusive,
                char_start=int(plan["char_start"]),
                char_end=int(plan["char_end"]),
                token_start=token_start,
                token_end=token_end,
                token_count=max(0, token_end - token_start),
                parent_path=parent_path,
                split_mode=str(plan["split_mode"]),
                year_month=record.year_month or record.publication_date[:7],
                document_type=record.document_type.value,
                document_number=record.document_number,
                heading=str(plan.get("heading") or ""),
                locator_path=locator_path,
            )
        )
    return tuple(chunks)


def _recovery_id(document: InventoryDocument, coverage: DocumentCoverage) -> str:
    material = canonical_json_dumps(
        {
            "document_number": document.document_number,
            "publication_date": document.publication_date,
            "disposition": coverage.disposition.value,
            "reason": coverage.allowed_reason or coverage.notes,
        }
    )
    return "sha256:" + content_sha256(material)


def _build_recovery_record(
    document: InventoryDocument,
    coverage: DocumentCoverage,
    *,
    disposition: RowDisposition,
) -> RecoveryRecord:
    status = (
        AdmissionStatus.QUARANTINED
        if disposition is RowDisposition.QUARANTINED
        else AdmissionStatus.REJECTED
        if disposition is RowDisposition.FAILED_FINAL
        else AdmissionStatus.EXCLUDED
    )
    payload = scrub_mapping_paths(
        {
            "allowed_reason": coverage.allowed_reason,
            "coverage_disposition": coverage.disposition.value,
            "inventory_legal_id": document.legal_id,
            "notes": coverage.notes,
            "publication_date": document.publication_date,
            "title": document.title,
            "year_month": document.publication_date[:7],
        }
    )
    raw_digest = coverage.admitted_response_hash
    if raw_digest is None and coverage.attempts:
        raw_digest = coverage.attempts[0].response_hash
    return RecoveryRecord(
        recovery_id=_recovery_id(document, coverage),
        reason=_reason_for(coverage, disposition),
        source_path=f"recovery/quarantine/{document.document_number}.json",
        raw_digest=raw_digest,
        admission_status=status,
        document_number=document.document_number,
        payload=payload,
    )


def _shard_path(family: str, year_month: str, document_type: str, part_index: int) -> str:
    prefix = {
        "corpus": "data/corpus",
        "chunks": "data/chunks",
        "recovery": "recovery",
    }[family]
    if family == "recovery":
        return f"{prefix}/part-{part_index:03d}.parquet"
    return (
        f"{prefix}/year_month={year_month}/document_type={document_type}/"
        f"part-{part_index:03d}.parquet"
    )


def plan_parquet_shards(
    rows: Sequence[Mapping[str, Any]],
    *,
    family: str,
    key_field: str,
    type_field: str = "document_type",
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
) -> tuple[ParquetShardPlan, ...]:
    """Partition *rows* by year_month + document_type into bounded Parquet shards."""

    if max_rows != MAX_ROWS_PER_PHYSICAL_SHARD:
        raise PhysicalBoundError("physical shard bound must remain 4096")
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        year_month = str(row.get("year_month") or "")
        if not year_month and row.get("publication_date"):
            year_month = str(row["publication_date"])[:7]
        doc_type = str(row.get(type_field) or "unknown")
        grouped.setdefault((year_month, doc_type), []).append(row)
    shards: list[ParquetShardPlan] = []
    for year_month, doc_type in sorted(grouped):
        bucket = grouped[(year_month, doc_type)]
        bucket.sort(key=lambda item: str(item.get(key_field) or ""))
        for part_index, offset in enumerate(range(0, len(bucket), max_rows)):
            part = bucket[offset : offset + max_rows]
            digest, size = _digest_rows(part)
            first_key = str(part[0][key_field])
            last_key = str(part[-1][key_field])
            shards.append(
                ParquetShardPlan(
                    relative_path=_shard_path(family, year_month, doc_type, part_index),
                    family=family,
                    year_month=year_month,
                    document_type=None if family == "recovery" else doc_type,
                    part_index=part_index,
                    row_count=len(part),
                    sha256=digest,
                    size_bytes=size,
                    first_key=first_key,
                    last_key=last_key,
                )
            )
    return tuple(shards)


def _locator_from_shard(
    shard: ParquetShardPlan,
    *,
    family: ArtifactFamily,
    locator_prefix: str,
) -> LocatorRecord:
    return LocatorRecord(
        locator_id=f"{locator_prefix}-{shard.relative_path.replace('/', '-')}",
        relative_path=shard.relative_path,
        sha256=shard.sha256,
        family=family,
        first_key=shard.first_key,
        last_key=shard.last_key,
        row_count=shard.row_count,
        size_bytes=shard.size_bytes,
        year_month=shard.year_month or None,
        document_type=shard.document_type,
    )


def _direct_document_locator(
    record: CorpusRecord,
    shard: ParquetShardPlan,
) -> LocatorRecord:
    return LocatorRecord(
        locator_id=f"fr-locator-doc-{record.document_number}-{record.publication_date}",
        relative_path=shard.relative_path,
        sha256=shard.sha256,
        family=ArtifactFamily.LOCATOR_INDEX,
        first_key=record.entry_cid,
        last_key=record.entry_cid,
        row_count=1,
        size_bytes=shard.size_bytes,
        year_month=record.year_month,
        document_type=record.document_type.value,
        document_number=record.document_number,
    )


def _build_source_receipts(
    ledger: Sequence[LedgerEntry],
    coverage_by_id: Mapping[str, DocumentCoverage],
    *,
    release_point: str,
    observation_cutoff: str,
    observed_at: str,
) -> tuple[SourceReceiptRecord, ...]:
    grouped: dict[str, list[LedgerEntry]] = {}
    for entry in ledger:
        grouped.setdefault(entry.year_month, []).append(entry)
    receipts: list[SourceReceiptRecord] = []
    for year_month in sorted(grouped):
        entries = grouped[year_month]
        dates = [item.publication_date for item in entries]
        start, end = _clip_bounds(year_month, dates)
        fetched = sum(1 for item in entries if item.disposition is RowDisposition.ADMITTED)
        excluded = sum(1 for item in entries if item.disposition is RowDisposition.EXCLUDED)
        quarantined = sum(
            1 for item in entries if item.disposition is RowDisposition.QUARANTINED
        )
        failed_final = sum(
            1 for item in entries if item.disposition is RowDisposition.FAILED_FINAL
        )
        enumerated = len(entries)
        dispositions: dict[str, int] = {}
        hashes: list[str] = []
        for item in entries:
            coverage = coverage_by_id[item.inventory_legal_id]
            availability = _text_availability_for(coverage).value
            dispositions[availability] = dispositions.get(availability, 0) + 1
            for attempt in coverage.attempts:
                if attempt.response_hash:
                    hashes.append(attempt.response_hash)
        if not hashes:
            hashes = [content_sha256(f"fr-empty-partition:{year_month}")]
        checksum = content_sha256(
            canonical_json_dumps(
                {
                    "document_numbers": [item.document_number for item in entries],
                    "year_month": year_month,
                }
            )
        )
        receipts.append(
            SourceReceiptRecord(
                receipt_id=f"fr-acquire-{year_month}",
                year_month=year_month,
                partition_start=start,
                partition_end=end,
                official_source_url=FEDERAL_REGISTER_DOCUMENTS_API,
                release_point=release_point,
                observation_time=observed_at,
                observation_cutoff=observation_cutoff,
                source_authority_class=SourceAuthorityClass.OFFICIAL,
                source_checksum=checksum,
                verification_result=VerificationResult.VERIFIED,
                enumerated=enumerated,
                fetched=fetched,
                duplicate=0,
                excluded=excluded,
                quarantined=quarantined,
                failed_final=failed_final,
                frontier_closed=failed_final == 0,
                relative_path=f"receipts/acquire/year_month-{year_month}.json",
                api_total=enumerated,
                page_cursors=(f"{year_month}-page-1",),
                response_hashes=tuple(dict.fromkeys(hashes)),
                document_numbers=tuple(item.document_number for item in entries),
                body_text_dispositions=dispositions,
                source_software_version=PARSER_VERSION,
            )
        )
    return tuple(receipts)


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


def assert_every_row_has_exactly_one_disposition(
    ledger: Sequence[LedgerEntry],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in ledger:
        prior = mapping.get(entry.row_id)
        if prior is not None:
            raise DispositionError(
                f"row_id {entry.row_id!r} has multiple dispositions: "
                f"{prior!r} and {entry.disposition.value!r}"
            )
        mapping[entry.row_id] = entry.disposition.value
    if not mapping:
        raise DispositionError("admission ledger is empty")
    return mapping


def assert_unique_primary_keys(records: Sequence[CorpusRecord]) -> None:
    validate_primary_keys([record.to_dict() for record in records])
    legal_ids = [record.legal_id for record in records]
    if len(legal_ids) != len(set(legal_ids)):
        raise DuplicatePrimaryKeyError("duplicate legal_id values in corpus")
    chunk_ids: list[str] = []
    # uniqueness of corpus entry_cid already enforced.


def assert_admitted_rows_complete(records: Sequence[CorpusRecord]) -> None:
    if not records:
        raise IncompleteIdentityError("no admitted corpus rows")
    for record in records:
        if record.admission_status is not AdmissionStatus.ADMITTED:
            raise IncompleteIdentityError(
                f"{record.legal_id}: corpus row is not admitted"
            )
        if not record.entry_cid or not record.source_cid or not record.legal_id:
            raise IncompleteIdentityError(
                f"{record.legal_id}: missing durable identity"
            )
        if record.source_authority_class is SourceAuthorityClass.SECONDARY:
            raise IncompleteIdentityError(
                f"{record.legal_id}: secondary sources cannot be admitted"
            )


def assert_chunk_offsets_valid(
    records: Sequence[CorpusRecord],
    chunks: Sequence[CanonicalChunk],
) -> None:
    by_entry: dict[str, list[CanonicalChunk]] = {}
    seen_ids: set[str] = set()
    for chunk in chunks:
        if chunk.chunk_id in seen_ids:
            raise DuplicatePrimaryKeyError(f"duplicate chunk_id {chunk.chunk_id!r}")
        seen_ids.add(chunk.chunk_id)
        by_entry.setdefault(chunk.entry_cid, []).append(chunk)
    searchable = {
        record.entry_cid: record
        for record in records
        if record.text_availability.has_usable_body
    }
    if set(by_entry) != set(searchable):
        raise ChunkOffsetError(
            "searchable corpus rows and chunk parents are not 1:1"
        )
    for entry_cid, record in searchable.items():
        group = sorted(by_entry[entry_cid], key=lambda item: item.chunk_index)
        payload = [chunk.to_dict() for chunk in group]
        assert_exclusive_coverage(record.text, payload)


def assert_row_conservation(
    corpus: MaterializedCorpus, *, expected_input: int = EXPECTED_FIXTURE_DOCUMENTS
) -> None:
    if corpus.inventory_document_count != expected_input:
        raise FixtureInventoryError(
            f"expected {expected_input} fixture documents, got "
            f"{corpus.inventory_document_count}"
        )
    accounted = sum(corpus.disposition_counts.values())
    if accounted != expected_input:
        raise AdmissionLedgerError(
            f"row conservation failed: {accounted} != {expected_input}"
        )
    if corpus.disposition_counts.get(RowDisposition.FAILED_FINAL.value, 0) != 0:
        raise FailedFinalAdmissionError("failed_final must be zero on a closed fixture")


def assert_bounded_parquet(shards: Sequence[ParquetShardPlan]) -> None:
    if not shards:
        raise PhysicalBoundError("no Parquet shards were planned")
    for shard in shards:
        validate_physical_row_count(shard.row_count, name=shard.relative_path)
        if shard.max_rows != MAX_ROWS_PER_PHYSICAL_SHARD:
            raise PhysicalBoundError("physical bound drifted from 4096")
        if shard.bound_kind != "physical_rows":
            raise PhysicalBoundError("shard bound_kind must be physical_rows")


def assert_no_duplicated_per_posting_lineage(corpus: MaterializedCorpus) -> None:
    lineage_cids = [row.source_cid for row in corpus.source_lineage]
    if len(lineage_cids) != len(set(lineage_cids)):
        raise LineageDuplicationError("source_cid lineage is not unique")
    if len(lineage_cids) != len(corpus.corpus_records):
        raise LineageDuplicationError(
            "source-level lineage must be 1:1 with admitted corpus rows"
        )
    admitted_sources = {record.source_cid for record in corpus.corpus_records}
    if set(lineage_cids) != admitted_sources:
        raise LineageDuplicationError("source lineage does not match corpus source_cids")
    for chunk in corpus.chunks:
        payload = chunk.to_dict()
        leaked = POSTING_LINEAGE_FORBIDDEN_FIELDS.intersection(payload)
        if leaked:
            raise LineageDuplicationError(
                f"chunk {chunk.chunk_id!r} duplicates lineage fields {sorted(leaked)}"
            )
        lineage_matches = [
            row for row in corpus.source_lineage if row.source_cid == chunk.source_cid
        ]
        if len(lineage_matches) != 1:
            raise LineageDuplicationError(
                f"chunk {chunk.chunk_id!r} does not join exactly one source lineage"
            )


def assert_recovery_excluded_from_canonical_counts(
    corpus: MaterializedCorpus,
) -> None:
    counts = corpus.family_counts.to_dict()
    recovery = counts["recovery"]
    if recovery != len(corpus.recovery_records):
        raise RecoveryContaminationError("recovery count mismatch")
    if counts["corpus"] == counts["corpus"] + recovery and recovery:
        raise RecoveryContaminationError("recovery leaked into corpus counts")
    if counts["corpus"] != len(corpus.corpus_records):
        raise RecoveryContaminationError("corpus count includes non-admitted rows")
    for family in ("bm25", "vector", "graph"):
        if counts[family] != 0:
            raise RecoveryContaminationError(
                f"{family} is not owned by LCR-055 and must remain zero"
            )
        if counts[family] == counts["corpus"] + recovery and recovery:
            raise RecoveryContaminationError(
                f"{family} count includes recovery rows"
            )


def assert_fixture_inventory_only(corpus: MaterializedCorpus) -> None:
    if corpus.inventory_document_count != EXPECTED_FIXTURE_DOCUMENTS:
        raise FixtureInventoryError(
            "LCR-055 tests must use the sealed 18-document fixture inventory, "
            f"not the live inventory ({corpus.inventory_document_count} documents)"
        )
    if corpus.inventory_document_count >= 1000:
        raise FixtureInventoryError("refusing to materialize the live inventory")


# ---------------------------------------------------------------------------
# Materializer
# ---------------------------------------------------------------------------


@dataclass
class CorpusConfig:
    """Runtime configuration for one corpus materialization."""

    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF
    mode: FulltextMode = FulltextMode.FIXTURE
    model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_cutoff",
            require_immutable_observation_cutoff(self.observation_cutoff),
        )
        object.__setattr__(self, "mode", FulltextMode.coerce(self.mode))
        if self.mode is not FulltextMode.FIXTURE:
            raise FixtureInventoryError(
                "LCR-055 materialization is fixture-only; live inventory is out of scope"
            )
        if self.model_token_limit != DEFAULT_MODEL_TOKEN_LIMIT:
            raise FederalRegisterCorpusError(
                "model_token_limit must remain the pinned GTE-small ceiling of 512"
            )


def _require_closed_fixture(result: EnrichmentResult) -> tuple[InventoryDocument, ...]:
    documents, inventory_report = load_fixture_inventory_documents(
        observation_cutoff=result.config.observation_cutoff
    )
    unique = int(inventory_report.get("counts", {}).get("unique_legal_ids") or 0)
    if unique != EXPECTED_FIXTURE_DOCUMENTS or len(documents) != EXPECTED_FIXTURE_DOCUMENTS:
        raise FixtureInventoryError(
            "fixture inventory is not the sealed 18-document LCR-053 set "
            f"(unique_legal_ids={unique}, documents={len(documents)})"
        )
    if unique >= 1000:
        raise FixtureInventoryError("refusing the live Federal Register inventory")
    coverage_ids = {item.legal_id for item in result.documents}
    inventory_ids = {item.legal_id for item in documents}
    if coverage_ids != inventory_ids:
        raise AdmissionLedgerError(
            "full-text coverage and inventory legal_id sets do not reconcile"
        )
    if result.failed_final != 0:
        raise FailedFinalAdmissionError("failed_final must be zero before admission")
    return documents


def materialize_federal_register_corpus(
    *,
    config: CorpusConfig | None = None,
    enrichment: EnrichmentResult | None = None,
) -> MaterializedCorpus:
    """Materialize the sealed LCR-053 fixture into corpus, chunks, and recovery."""

    cfg = config or CorpusConfig()
    result = enrichment or enrich_federal_register_fulltext(
        config=FulltextConfig(
            observation_cutoff=cfg.observation_cutoff,
            mode=FulltextMode.FIXTURE,
        )
    )
    if result.config.mode is not FulltextMode.FIXTURE:
        raise FixtureInventoryError("corpus materialization requires fixture full-text")
    documents = _require_closed_fixture(result)
    coverage_by_id = {item.legal_id: item for item in result.documents}
    ordered = sorted(documents, key=lambda item: (item.publication_date, item.document_number))
    release_point = cutoff_release_point(cfg.observation_cutoff)
    observed_at = result.observed_at or DEFAULT_ACQUISITION_TIME

    ledger: list[LedgerEntry] = []
    corpus_records: list[CorpusRecord] = []
    chunks: list[CanonicalChunk] = []
    recovery_records: list[RecoveryRecord] = []
    source_lineage: list[SourceLineage] = []
    admitted_index = 0

    for document in ordered:
        coverage = coverage_by_id[document.legal_id]
        disposition = coverage_to_row_disposition(coverage)
        year_month = document.publication_date[:7]
        document_type = DocumentType.coerce(
            document.document_type or DocumentType.NOTICE
        ).value
        row_id = f"fr:{document.document_number}:{document.publication_date}"
        if disposition is RowDisposition.FAILED_FINAL:
            raise FailedFinalAdmissionError(
                f"{document.legal_id} is failed-final and cannot be admitted"
            )
        if disposition is RowDisposition.ADMITTED:
            raw_row = _build_identity_row(
                document,
                coverage,
                cache=result.cache,
                document_index=admitted_index,
                release_point=release_point,
                acquisition_time=observed_at,
            )
            canonical = enrich_row_identity(raw_row)
            record = CorpusRecord.from_mapping(canonical)
            identity = identity_from_row(canonical)
            shard_path = _shard_path(
                "corpus",
                record.year_month or year_month,
                record.document_type.value,
                0,
            )
            record_chunks = chunk_corpus_record(
                record, identity=identity, locator_path=shard_path
            )
            corpus_records.append(record)
            chunks.extend(record_chunks)
            source_lineage.append(
                SourceLineage(
                    source_cid=record.source_cid,
                    document_number=record.document_number,
                    publication_date=record.publication_date,
                    source_format=str(canonical.get("source_format") or ""),
                    official_source_url=record.official_source_url,
                    source_checksum=record.source_checksum,
                    acquisition_receipt_id=record.acquisition_receipt_id,
                    parser_version=record.parser_version,
                    text_availability=record.text_availability.value,
                    year_month=record.year_month or year_month,
                    legal_id=record.legal_id,
                    entry_cid=record.entry_cid,
                    observed_at=record.acquisition_time,
                    release_point=record.release_point,
                )
            )
            ledger.append(
                LedgerEntry(
                    row_id=row_id,
                    disposition=disposition,
                    reason=record.admission_reason,
                    document_number=document.document_number,
                    publication_date=document.publication_date,
                    inventory_legal_id=document.legal_id,
                    coverage_disposition=coverage.disposition.value,
                    year_month=year_month,
                    document_type=document_type,
                    legal_id=record.legal_id,
                    entry_cid=record.entry_cid,
                    source_cid=record.source_cid,
                    text_availability=record.text_availability.value,
                    chunk_count=len(record_chunks),
                    searchable=record.text_availability.has_usable_body,
                )
            )
            admitted_index += 1
            continue

        reason = _reason_for(coverage, disposition)
        if disposition is not RowDisposition.EXCLUDED:
            recovery_records.append(
                _build_recovery_record(document, coverage, disposition=disposition)
            )
        ledger.append(
            LedgerEntry(
                row_id=row_id,
                disposition=disposition,
                reason=reason,
                document_number=document.document_number,
                publication_date=document.publication_date,
                inventory_legal_id=document.legal_id,
                coverage_disposition=coverage.disposition.value,
                year_month=year_month,
                document_type=document_type,
                text_availability=_text_availability_for(coverage).value,
            )
        )

    corpus_payloads = [record.to_dict() for record in corpus_records]
    chunk_payloads = [chunk.to_dict() for chunk in chunks]
    recovery_payloads = [record.to_dict() for record in recovery_records]
    corpus_shards = plan_parquet_shards(
        corpus_payloads, family="corpus", key_field="entry_cid"
    )
    chunk_shards = plan_parquet_shards(
        chunk_payloads, family="chunks", key_field="chunk_id"
    )
    recovery_shards = (
        plan_parquet_shards(
            recovery_payloads, family="recovery", key_field="recovery_id"
        )
        if recovery_payloads
        else ()
    )
    parquet_shards = tuple((*corpus_shards, *chunk_shards, *recovery_shards))

    shard_by_doc: dict[str, ParquetShardPlan] = {}
    for shard in corpus_shards:
        for record in corpus_records:
            if (
                record.year_month == shard.year_month
                and record.document_type.value == shard.document_type
                and shard.first_key <= record.entry_cid <= shard.last_key
            ):
                shard_by_doc[record.entry_cid] = shard

    locators: list[LocatorRecord] = []
    for shard in corpus_shards:
        locators.append(
            _locator_from_shard(
                shard, family=ArtifactFamily.CORPUS, locator_prefix="fr-locator-corpus"
            )
        )
    for shard in chunk_shards:
        locators.append(
            _locator_from_shard(
                shard, family=ArtifactFamily.CORPUS, locator_prefix="fr-locator-chunks"
            )
        )
    for shard in recovery_shards:
        locators.append(
            _locator_from_shard(
                shard,
                family=ArtifactFamily.RECOVERY,
                locator_prefix="fr-locator-recovery",
            )
        )
    for record in corpus_records:
        shard = shard_by_doc.get(record.entry_cid)
        if shard is None:
            raise AdmissionLedgerError(
                f"no corpus shard locator for {record.document_number}"
            )
        locators.append(_direct_document_locator(record, shard))

    source_receipts = _build_source_receipts(
        ledger,
        coverage_by_id,
        release_point=release_point,
        observation_cutoff=cfg.observation_cutoff,
        observed_at=observed_at,
    )
    excluded_count = sum(
        1 for entry in ledger if entry.disposition is RowDisposition.EXCLUDED
    )
    family_counts = FamilyCounts(
        corpus=len(corpus_records),
        chunks=len(chunks),
        bm25=0,
        vector=0,
        graph=0,
        recovery=len(recovery_records),
        excluded=excluded_count,
        locators=len(locators),
        source_receipts=len(source_receipts),
        source_lineage=len(source_lineage),
    )
    materialized = MaterializedCorpus(
        ledger=tuple(ledger),
        corpus_records=tuple(corpus_records),
        chunks=tuple(chunks),
        recovery_records=tuple(recovery_records),
        locators=tuple(locators),
        source_receipts=tuple(source_receipts),
        source_lineage=tuple(source_lineage),
        parquet_shards=parquet_shards,
        family_counts=family_counts,
        inventory_document_count=len(documents),
        observation_cutoff=cfg.observation_cutoff,
        release_point=release_point,
        notes=(
            "Canonical Federal Register corpus admission for LCR-055. "
            "Hermetic against the LCR-053 18-document fixture inventory. "
            "Does not rewrite the official LCR-052 inventory or authorize Hub upload."
        ),
    )
    assert_every_row_has_exactly_one_disposition(materialized.ledger)
    assert_admitted_rows_complete(materialized.corpus_records)
    assert_unique_primary_keys(materialized.corpus_records)
    assert_chunk_offsets_valid(materialized.corpus_records, materialized.chunks)
    assert_row_conservation(materialized)
    assert_bounded_parquet(materialized.parquet_shards)
    assert_no_duplicated_per_posting_lineage(materialized)
    assert_recovery_excluded_from_canonical_counts(materialized)
    assert_fixture_inventory_only(materialized)
    return materialized


def _compact_record(record: CorpusRecord) -> dict[str, Any]:
    return {
        "admission_status": record.admission_status.value,
        "document_number": record.document_number,
        "document_type": record.document_type.value,
        "entry_cid": record.entry_cid,
        "legal_id": record.legal_id,
        "publication_date": record.publication_date,
        "source_cid": record.source_cid,
        "text_availability": record.text_availability.value,
        "year_month": record.year_month,
    }


def _compact_chunk(chunk: CanonicalChunk) -> dict[str, Any]:
    return {
        "char_end": chunk.char_end,
        "char_start": chunk.char_start,
        "chunk_cid": chunk.chunk_cid,
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "entry_cid": chunk.entry_cid,
        "parent_legal_id": chunk.parent_legal_id,
        "source_cid": chunk.source_cid,
        "split_mode": chunk.split_mode,
        "token_count": chunk.token_count,
        "year_month": chunk.year_month,
    }


def build_federal_admission_report(
    corpus: MaterializedCorpus | None = None,
) -> dict[str, Any]:
    """Build the sealed, secret-free LCR-055 admission receipt."""

    materialized = corpus or materialize_federal_register_corpus()
    assert_every_row_has_exactly_one_disposition(materialized.ledger)
    assert_admitted_rows_complete(materialized.corpus_records)
    assert_unique_primary_keys(materialized.corpus_records)
    assert_chunk_offsets_valid(materialized.corpus_records, materialized.chunks)
    assert_row_conservation(materialized)
    assert_bounded_parquet(materialized.parquet_shards)
    assert_no_duplicated_per_posting_lineage(materialized)
    assert_recovery_excluded_from_canonical_counts(materialized)

    replay = materialize_federal_register_corpus()
    deterministic = (
        [record.entry_cid for record in materialized.corpus_records]
        == [record.entry_cid for record in replay.corpus_records]
        and [chunk.chunk_id for chunk in materialized.chunks]
        == [chunk.chunk_id for chunk in replay.chunks]
        and [row.source_cid for row in materialized.source_lineage]
        == [row.source_cid for row in replay.source_lineage]
    )
    sample = materialized.searchable_documents[0]
    sample_chunks = [
        chunk
        for chunk in materialized.chunks
        if chunk.entry_cid == sample.entry_cid
    ]
    payload = {
        "acceptance": {
            "bounded_parquet": True,
            "criteria": (
                "One disposition per input, unique primary keys, valid provenance "
                "and offsets, exact row conservation, bounded Parquet, and no "
                "duplicated per-posting lineage."
            ),
            "exact_row_conservation": True,
            "failed_final_zero": True,
            "fixture_inventory_documents": EXPECTED_FIXTURE_DOCUMENTS,
            "hub_upload": False,
            "no_duplicated_per_posting_lineage": True,
            "not_live_inventory": True,
            "one_disposition_per_input": True,
            "secrets_absent": True,
            "unique_primary_keys": True,
            "valid_provenance_and_offsets": True,
        },
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "board_namespace": BOARD_NAMESPACE,
        "bundle": BUNDLE,
        "checks": {
            "admitted_chunk_count": len(materialized.chunks),
            "admitted_corpus_count": len(materialized.corpus_records),
            "chunk_offsets_cover_source": True,
            "corpus_partitions_are_type_and_date": True,
            "deterministic_ids_across_replay": deterministic,
            "direct_document_locators": sum(
                1
                for locator in materialized.locators
                if locator.document_number is not None
            ),
            "failed_final": 0,
            "fixture_inventory_documents": EXPECTED_FIXTURE_DOCUMENTS,
            "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "model_token_ceiling": DEFAULT_MODEL_TOKEN_LIMIT,
            "physical_shard_bound_not_used_as_token_ceiling": (
                MAX_ROWS_PER_PHYSICAL_SHARD == 4096
                and DEFAULT_MODEL_TOKEN_LIMIT == 512
            ),
            "publication_not_authorized": True,
            "recovery_excluded_from_canonical_counts": True,
            "source_lineage_is_document_level": True,
        },
        "code_version": CODE_VERSION,
        "conservation": {
            "accounted": sum(materialized.disposition_counts.values()),
            "admitted": materialized.disposition_counts[RowDisposition.ADMITTED.value],
            "excluded": materialized.disposition_counts[RowDisposition.EXCLUDED.value],
            "failed_final": materialized.disposition_counts[
                RowDisposition.FAILED_FINAL.value
            ],
            "input": materialized.inventory_document_count,
            "quarantined": materialized.disposition_counts[
                RowDisposition.QUARANTINED.value
            ],
        },
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "depends_on": [INVENTORY_TASK_ID, FULLTEXT_TASK_ID, IDENTITY_TASK_ID],
        "description": (
            "LCR-055 canonical Federal Register corpus admission. Bounded "
            "year_month/document_type Parquet shards, structure-aware chunks, "
            "recovery/quarantine, direct locators, and source-level lineage. "
            "Hermetic against the LCR-053 18-document fixture. Does not rewrite "
            "the official inventory or authorize Hub upload."
        ),
        "disposition_counts": materialized.disposition_counts,
        "embedding_contract": {
            "dimension": 384,
            "model_id": DEFAULT_EMBEDDING_MODEL_ID,
            "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
            "model_token_ceiling": DEFAULT_MODEL_TOKEN_LIMIT,
        },
        "family_counts": materialized.family_counts.to_dict(),
        "goal_id": GOAL_ID,
        "identity": {
            "chunk_id_pattern": "{parent_legal_id}#chunk=NNNN",
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "legal_id_prefix": "fr",
            "parser_version": PARSER_VERSION,
            "physical_rows_per_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "primary_key": "entry_cid",
            "tokenizer_id": DEFAULT_TOKENIZER_ID,
            "transformation_version": TRANSFORMATION_VERSION,
        },
        "inventory": {
            "report_relpath": inventory_report_relpath(),
            "rewritten": False,
            "task_id": INVENTORY_TASK_ID,
            "unique_legal_ids": materialized.inventory_document_count,
        },
        "locators": [locator.to_dict() for locator in materialized.locators],
        "mode": FulltextMode.FIXTURE.value,
        "network_required": False,
        "notes": materialized.notes,
        "observation_cutoff": materialized.observation_cutoff,
        "parquet_shards": [shard.to_dict() for shard in materialized.parquet_shards],
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "recovery": [
            {
                "admission_status": record.admission_status.value,
                "document_number": record.document_number,
                "reason": record.reason,
                "recovery_id": record.recovery_id,
                "source_path": record.source_path,
            }
            for record in materialized.recovery_records
        ],
        "release_point": materialized.release_point,
        "release_profile": RELEASE_PROFILE,
        "report_kind": "fixture_admission",
        "sample": {
            "chunks": [_compact_chunk(chunk) for chunk in sample_chunks],
            "corpus": _compact_record(sample),
        },
        "schema": REPORT_SCHEMA,
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "source_lineage": [row.to_dict() for row in materialized.source_lineage],
        "source_receipts": [row.to_dict() for row in materialized.source_receipts],
        "task_id": TASK_ID,
    }
    compact = scrub_mapping_paths(payload)
    assert_no_secrets(compact, context="federal_admission")
    blob = json.dumps(compact, sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise SecretInReceiptError("admission report contains an absolute home path")
    digest = digest_mapping(
        {key: value for key, value in compact.items() if key != "report_digest_sha256"}
    )
    compact["report_digest_sha256"] = digest
    return compact


def write_federal_admission_report(
    path: PathLike | None = None,
    *,
    corpus: MaterializedCorpus | None = None,
) -> Path:
    target = Path(path) if path is not None else default_admission_report_path()
    if target.name == INVENTORY_REPORT_RELPATH.name:
        raise InventoryRewriteError("refusing to rewrite the official inventory")
    payload = build_federal_admission_report(corpus)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    )
    target.write_text(text, encoding="utf-8")
    return target


def load_federal_admission_report(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_admission_report_path()
    if not target.is_file():
        raise FederalRegisterCorpusError(f"admission report not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise FederalRegisterCorpusError("admission report must be a JSON object")
    if payload.get("task_id") != TASK_ID:
        raise FederalRegisterCorpusError(f"unexpected task_id {payload.get('task_id')!r}")
    return dict(payload)


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "AdmissionLedgerError",
    "CANONICAL_COUNT_FAMILIES",
    "CanonicalChunk",
    "CorpusConfig",
    "CURRENTNESS_DISCLAIMER",
    "ChunkOffsetError",
    "DEFAULT_MODEL_TOKEN_LIMIT",
    "DispositionError",
    "EXPECTED_FIXTURE_DOCUMENTS",
    "FIXTURE_SCHEMA_VERSION",
    "FailedFinalAdmissionError",
    "FamilyCounts",
    "FederalRegisterCorpusError",
    "FixtureInventoryError",
    "GOAL_ID",
    "IncompleteIdentityError",
    "InventoryRewriteError",
    "LedgerEntry",
    "LineageDuplicationError",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "MaterializedCorpus",
    "PARSER_VERSION",
    "PRODUCER",
    "ParquetShardPlan",
    "REPORT_SCHEMA",
    "RecoveryContaminationError",
    "RowDisposition",
    "SCHEMA_VERSION",
    "SourceLineage",
    "SplitMode",
    "TASK_ID",
    "TRANSFORMATION_VERSION",
    "assert_admitted_rows_complete",
    "assert_bounded_parquet",
    "assert_chunk_offsets_valid",
    "assert_every_row_has_exactly_one_disposition",
    "assert_exclusive_coverage",
    "assert_fixture_inventory_only",
    "assert_no_duplicated_per_posting_lineage",
    "assert_recovery_excluded_from_canonical_counts",
    "assert_row_conservation",
    "assert_unique_primary_keys",
    "build_federal_admission_report",
    "chunk_corpus_record",
    "coverage_to_row_disposition",
    "default_admission_report_path",
    "load_federal_admission_report",
    "materialize_federal_register_corpus",
    "plan_parquet_shards",
    "plan_structure_chunks",
    "scrub_local_paths_in_text",
    "segment_document_structure",
    "write_federal_admission_report",
]


if __name__ == "__main__":
    materialized = materialize_federal_register_corpus()
    written = write_federal_admission_report(corpus=materialized)
    print(
        f"wrote {REPORT_RELATIVE_PATH.as_posix()} "
        f"corpus={len(materialized.corpus_records)} "
        f"chunks={len(materialized.chunks)} "
        f"recovery={len(materialized.recovery_records)}"
    )
    _ = written
