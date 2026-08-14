"""Scalable field-weighted term-range BM25 for Open US Law (OUL-027).

This module is the legal-domain adapter between:

* admitted exact-51 corpus chunks;
* the versioned legal tokenizer from :mod:`uscode_tokenizer` (shared by
  build and query);
* domain-neutral external sort from
  :mod:`ipfs_datasets_py.retrieval.hf_graphrag.external_sort` (OUL-026);
* hierarchical term-range routes from
  :mod:`ipfs_datasets_py.retrieval.hf_graphrag.hierarchical_routes` (OUL-026);
  and
* reference BM25 scoring from
  :mod:`ipfs_datasets_py.retrieval.hf_graphrag.bm25`.

Design invariants
-----------------
* One sealed legal tokenizer identity is used for both indexing and query.
* Documents are externally sorted by stable ``document_index`` then
  ``entry_cid``.
* Terms and postings are externally sorted lexicographically
  ``(term, entry_cid)``.
* Every document shard, term-range shard, route page, and posting cell
  has at most 4,096 rows or pointers.
* There is no 250,000-document ceiling. The shared US Code / HF GraphRAG
  layout default of 250,000 would truncate the exact-51 seed
  (1,904,919 rows) and is rejected.
* Sparse retrieval routes through inclusive lexicographic term ranges
  and never through vector centroids.
* No network I/O. Unit tests use compact sealed recipes only.
* This receipt proves the software contract only; it does not claim the
  live exact-51 corpus has been indexed.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    ADR_PATH as SCHEMA_ADR_PATH,
    MAX_POSTING_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    PositionalIdentityError,
    RELEASE_PROFILE,
    reject_positional_durable_identity,
    validate_entry_cid,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import (
    STOPWORD_POLICY_ID,
    TOKENIZER_ID,
    TOKENIZER_VERSION,
    TokenizerConfig,
    default_tokenizer_config,
    tokenize_legal_text,
    tokenizer_identity,
)
from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import bm25_term_score
from ipfs_datasets_py.retrieval.hf_graphrag.external_sort import (
    DEFAULT_MAX_RECORDS_IN_MEMORY,
    ExternalSortReceipt,
    document_sort_key,
    external_sort_to_file,
    iter_jsonl,
    posting_sort_key,
    stream_bounded_partitions,
    term_sort_key,
)
from ipfs_datasets_py.retrieval.hf_graphrag.hierarchical_routes import (
    HIERARCHICAL_ROUTE_SCHEMA_VERSION,
    HierarchicalRouteIndex,
    MissingRouteKeyError,
    RouteDescriptor,
    build_hierarchical_routes,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    canonical_json_bytes,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-bm25-v1"
RECEIPT_SCHEMA_VERSION: Final = "open-us-law-bm25-receipt-v1"
TASK_ID: Final = "OUL-027"
GOAL_ID: Final = "OUL-G040"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "open_us_law_bm25.py"
ADR_PATH: Final = SCHEMA_ADR_PATH
PRIMARY_KEY: Final = "entry_cid"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_RELEASE: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True

RECEIPT_RELATIVE_PATH: Final = "docs/reports/open_us_law_reindex/bm25_receipt.json"
RECEIPT_SEALED_AT: Final = "2026-08-14T00:00:00Z"

DEFAULT_K1: Final = 1.2
DEFAULT_B: Final = 0.75
LEGACY_K1: Final = 1.5
LEGACY_B: Final = 0.75
DEFAULT_SHARED_TITLE_WEIGHT: Final = 5.0
DEFAULT_SHARED_BODY_WEIGHT: Final = 1.0

# Exact-51 seed observation is 1,904,919 rows. The inherited shared-layout
# ceiling of 250,000 would truncate that corpus and is therefore forbidden.
EXACT_51_SEED_ROW_LOWER_BOUND: Final = 1_904_919
FORBIDDEN_DOCUMENT_CEILING: Final = 250_000
DOCUMENT_COUNT_CEILING: Final[int | None] = None
MAX_TEXT_CHARACTERS: Final = 8 * 1024 * 1024
MAX_QUERY_TERMS: Final = 64

DEFAULT_FIELD_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "citation": 8.0,
        "title": 5.0,
        "heading": 4.0,
        "hierarchy": 3.0,
        "jurisdiction": 2.0,
        "body": 1.0,
        "note": 0.5,
    }
)

FIELD_ORDER: Final[tuple[str, ...]] = (
    "citation",
    "title",
    "heading",
    "hierarchy",
    "jurisdiction",
    "body",
    "note",
)

AUTHORITY_FIELDS: Final[frozenset[str]] = frozenset(
    {"citation", "title", "heading", "hierarchy", "jurisdiction"}
)
CONTENT_FIELDS: Final[frozenset[str]] = frozenset({"body", "note"})

DOCUMENTS_SORTED_BY: Final = "document_index_then_entry_cid"
TERMS_SORTED_BY: Final = "lexicographic_term"
POSTINGS_SORTED_BY: Final = "term_then_entry_cid"
TOKENIZER_SHARED_BY: Final = "build_and_query"

DOCUMENT_DATA_DIR: Final = "data/bm25/documents"
POSTING_DATA_DIR: Final = "data/bm25/postings"
DOCUMENT_ROUTE_DIR: Final = "indexes/bm25_document_routes"
TERM_ROUTE_DIR: Final = "indexes/bm25_term_routes"

DEFAULT_TEST_MAX_ROWS_PER_SHARD: Final = 2
DEFAULT_TEST_POSTINGS_PER_CELL: Final = 2
DEFAULT_TEST_ROUTE_PAGE_ROWS: Final = 2
DEFAULT_TEST_MAX_RECORDS_IN_MEMORY: Final = 3

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OpenUsLawBm25Error(ValueError):
    """Base error for Open US Law field-weighted BM25 failures."""

    code: str = "open_us_law_bm25_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class Bm25ConfigError(OpenUsLawBm25Error):
    """Raised when BM25 configuration is incomplete or invalid."""

    code = "config_invalid"


class Bm25CoverageError(OpenUsLawBm25Error):
    """Raised when admitted chunks and BM25 documents do not reconcile."""

    code = "coverage_invalid"


class Bm25ProjectionError(OpenUsLawBm25Error):
    """Raised when a legal document cannot be projected into BM25 fields."""

    code = "projection_invalid"


class Bm25BoundError(OpenUsLawBm25Error):
    """Raised when a shard, cell, or route page exceeds the 4,096 bound."""

    code = "physical_bound_exceeded"


class Bm25CeilingError(OpenUsLawBm25Error):
    """Raised when a 250,000-document ceiling would truncate the corpus."""

    code = "document_ceiling_forbidden"


class Bm25RootReconcileError(OpenUsLawBm25Error):
    """Raised when corpus root and index root do not reconcile."""

    code = "root_reconcile_failed"


class Bm25FilterError(OpenUsLawBm25Error):
    """Raised when a search filter is malformed."""

    code = "filter_invalid"


class Bm25ReceiptError(OpenUsLawBm25Error):
    """Raised when the sealed BM25 receipt is malformed."""

    code = "receipt_invalid"


class Bm25ReleaseAuthorizationError(OpenUsLawBm25Error):
    """Raised when a BM25 receipt would authorize release."""

    code = "release_authorization_forbidden"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class IndexField(str, Enum):
    """Named legal BM25 fields for Open US Law statutes."""

    CITATION = "citation"
    TITLE = "title"
    HEADING = "heading"
    HIERARCHY = "hierarchy"
    JURISDICTION = "jurisdiction"
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
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenUsLawBm25Error(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise OpenUsLawBm25Error(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise OpenUsLawBm25Error(f"{name} exceeds maximum length {maximum}")
    return text


def _optional_str(value: Any, name: str, *, maximum: int = 4096) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name, maximum=maximum)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OpenUsLawBm25Error(f"{name} must be an integer")
    if value < 0:
        raise OpenUsLawBm25Error(f"{name} must be >= 0")
    return value


def _require_positive_int(value: Any, name: str) -> int:
    number = _require_non_negative_int(value, name)
    if number < 1:
        raise OpenUsLawBm25Error(f"{name} must be >= 1")
    return number


def _require_positive_float(value: Any, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise Bm25ConfigError(f"{name} must be a positive finite number")
    return float(value)


def _validate_physical_bound(value: Any, *, name: str, maximum: int) -> int:
    number = _require_positive_int(value, name)
    if number > maximum:
        raise Bm25BoundError(
            f"{name}={number} exceeds physical bound {maximum}"
        )
    return number


def content_cid(value: Any) -> str:
    """Stable ``sha256:<hex>`` content address for roots and receipts."""

    if isinstance(value, (bytes, bytearray)):
        digest = content_sha256(bytes(value))
    elif isinstance(value, str):
        digest = content_sha256(value)
    else:
        digest = content_sha256(canonical_json_bytes(value))
    return f"sha256:{digest}"


def write_bytes_atomic(path: PathLike, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".oul-bm25-",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def write_json_atomic(path: PathLike, payload: Mapping[str, Any]) -> Path:
    text = (
        json.dumps(
            dict(payload),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    return write_bytes_atomic(path, text.encode("utf-8"))


def document_route_key(document_index: int) -> str:
    """Zero-padded document index so lexical order matches sort order."""

    index = _require_non_negative_int(document_index, "document_index")
    return f"{index:012d}"


def part_relative_path(directory: str, shard_id: int) -> str:
    return f"{directory.rstrip('/')}/part-{int(shard_id):06d}.json"


# ---------------------------------------------------------------------------
# Ceiling policy (fail closed on the inherited 250k cap)
# ---------------------------------------------------------------------------


def document_count_ceiling() -> int | None:
    """Return the document-count ceiling, or ``None`` when unbounded."""

    return DOCUMENT_COUNT_CEILING


def assert_no_document_ceiling(config: "OpenUsLawBm25Config | None" = None) -> None:
    """Fail if a document-count cap would truncate the exact-51 seed."""

    ceiling = document_count_ceiling()
    if config is not None:
        ceiling = config.max_documents
    if ceiling is None:
        return
    if ceiling == FORBIDDEN_DOCUMENT_CEILING:
        raise Bm25CeilingError(
            f"document ceiling {ceiling} is the forbidden inherited 250000 cap"
        )
    if ceiling < EXACT_51_SEED_ROW_LOWER_BOUND:
        raise Bm25CeilingError(
            f"document ceiling {ceiling} would truncate the exact-51 seed "
            f"(lower bound {EXACT_51_SEED_ROW_LOWER_BOUND})"
        )


def assert_document_count_admissible(
    count: int,
    config: "OpenUsLawBm25Config | None" = None,
) -> None:
    """Accept any non-negative admitted count; refuse truncating ceilings."""

    number = _require_non_negative_int(count, "document_count")
    assert_no_document_ceiling(config)
    ceiling = document_count_ceiling() if config is None else config.max_documents
    if ceiling is not None and number > ceiling:
        raise Bm25CoverageError(
            f"document count {number} exceeds configured ceiling {ceiling}"
        )


def would_truncate_corpus(
    count: int,
    config: "OpenUsLawBm25Config | None" = None,
) -> bool:
    """Return whether *count* would be truncated by the active ceiling."""

    assert_no_document_ceiling(config)
    ceiling = document_count_ceiling() if config is None else config.max_documents
    if ceiling is None:
        return False
    return int(count) > int(ceiling)


def inherited_shared_layout_would_truncate(count: int) -> bool:
    """True when the shared HF GraphRAG 250k default would drop rows."""

    return int(count) > FORBIDDEN_DOCUMENT_CEILING


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldWeightConfig:
    """Declared per-field BM25 weights for Open US Law statutes."""

    citation: float = DEFAULT_FIELD_WEIGHTS["citation"]
    title: float = DEFAULT_FIELD_WEIGHTS["title"]
    heading: float = DEFAULT_FIELD_WEIGHTS["heading"]
    hierarchy: float = DEFAULT_FIELD_WEIGHTS["hierarchy"]
    jurisdiction: float = DEFAULT_FIELD_WEIGHTS["jurisdiction"]
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
        return content_sha256(canonical_json_bytes(self.to_dict()))


def legacy_parameter_delta() -> dict[str, Any]:
    """Explicit comparison of evaluation defaults vs legacy monolith values."""

    return {
        "b": {
            "changed": not math.isclose(DEFAULT_B, LEGACY_B, abs_tol=0.0),
            "delta": DEFAULT_B - LEGACY_B,
            "evaluation_default": DEFAULT_B,
            "legacy": LEGACY_B,
        },
        "k1": {
            "changed": not math.isclose(DEFAULT_K1, LEGACY_K1, abs_tol=0.0),
            "delta": DEFAULT_K1 - LEGACY_K1,
            "evaluation_default": DEFAULT_K1,
            "legacy": LEGACY_K1,
        },
        "legacy_field_separation": False,
        "legacy_tokenizer_identity": None,
        "notes": (
            "Legacy legal BM25 used k1=1.5 with a single unweighted term "
            "array and no tokenizer identity. Open US Law uses k1=1.2, "
            "explicit multi-field weights, and the sealed legal tokenizer "
            "shared by build and query."
        ),
    }


@dataclass(frozen=True, slots=True)
class OpenUsLawBm25Config:
    """Stable legal BM25 indexing and scoring configuration.

    ``max_documents`` is ``None`` (unbounded) by default. An explicit
    ceiling is allowed only when it is at least the exact-51 seed lower
    bound. The inherited shared-layout value ``250000`` is always
    rejected.
    """

    k1: float = DEFAULT_K1
    b: float = DEFAULT_B
    field_weights: FieldWeightConfig = field(default_factory=FieldWeightConfig)
    tokenizer: TokenizerConfig = field(default_factory=default_tokenizer_config)
    max_documents: int | None = DOCUMENT_COUNT_CEILING
    max_text_characters: int = MAX_TEXT_CHARACTERS
    max_query_terms: int = MAX_QUERY_TERMS
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    postings_per_cell: int = MAX_POSTING_POINTERS_PER_ROW
    max_route_page_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY
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
        if self.tokenizer.tokenizer_id != TOKENIZER_ID:
            raise Bm25ConfigError(
                f"tokenizer_id must be the sealed legal tokenizer {TOKENIZER_ID!r}"
            )
        if self.max_documents is not None:
            ceiling = _require_positive_int(self.max_documents, "max_documents")
            object.__setattr__(self, "max_documents", ceiling)
            assert_no_document_ceiling(self)
        for name in ("max_text_characters", "max_query_terms", "max_records_in_memory"):
            object.__setattr__(
                self, name, _require_positive_int(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "max_rows_per_shard",
            _validate_physical_bound(
                self.max_rows_per_shard,
                name="max_rows_per_shard",
                maximum=MAX_ROWS_PER_PHYSICAL_SHARD,
            ),
        )
        object.__setattr__(
            self,
            "postings_per_cell",
            _validate_physical_bound(
                self.postings_per_cell,
                name="postings_per_cell",
                maximum=MAX_POSTING_POINTERS_PER_ROW,
            ),
        )
        object.__setattr__(
            self,
            "max_route_page_rows",
            _validate_physical_bound(
                self.max_route_page_rows,
                name="max_route_page_rows",
                maximum=MAX_ROWS_PER_PHYSICAL_SHARD,
            ),
        )
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
            "document_count_ceiling": self.max_documents,
            "field_weights": self.field_weights.to_dict(),
            "k1": self.k1,
            "legacy_parameter_delta": legacy_parameter_delta(),
            "max_documents": self.max_documents,
            "max_query_terms": self.max_query_terms,
            "max_records_in_memory": self.max_records_in_memory,
            "max_route_page_rows": self.max_route_page_rows,
            "max_rows_per_shard": self.max_rows_per_shard,
            "max_text_characters": self.max_text_characters,
            "postings_per_cell": self.postings_per_cell,
            "schema_version": self.schema_version,
            "shared_body_weight": self.shared_body_weight,
            "shared_title_weight": self.shared_title_weight,
            "tokenizer": self.tokenizer.to_dict(),
            "tokenizer_id": self.tokenizer.tokenizer_id,
            "tokenizer_shared_by": TOKENIZER_SHARED_BY,
        }

    @property
    def digest(self) -> str:
        payload = {
            "b": self.b,
            "field_weights": self.field_weights.to_dict(),
            "k1": self.k1,
            "max_documents": self.max_documents,
            "max_query_terms": self.max_query_terms,
            "max_records_in_memory": self.max_records_in_memory,
            "max_route_page_rows": self.max_route_page_rows,
            "max_rows_per_shard": self.max_rows_per_shard,
            "max_text_characters": self.max_text_characters,
            "postings_per_cell": self.postings_per_cell,
            "schema_version": self.schema_version,
            "shared_body_weight": self.shared_body_weight,
            "shared_title_weight": self.shared_title_weight,
            "tokenizer_digest": self.tokenizer.digest,
            "tokenizer_id": self.tokenizer.tokenizer_id,
        }
        return content_sha256(canonical_json_bytes(payload))


def default_bm25_config() -> OpenUsLawBm25Config:
    """Return the sealed production BM25 configuration (unbounded corpus)."""

    return OpenUsLawBm25Config()


def fixture_bm25_config(**overrides: Any) -> OpenUsLawBm25Config:
    """Tight physical bounds for unit fixtures (still 4,096-capped)."""

    params: dict[str, Any] = {
        "max_rows_per_shard": DEFAULT_TEST_MAX_ROWS_PER_SHARD,
        "postings_per_cell": DEFAULT_TEST_POSTINGS_PER_CELL,
        "max_route_page_rows": DEFAULT_TEST_ROUTE_PAGE_ROWS,
        "max_records_in_memory": DEFAULT_TEST_MAX_RECORDS_IN_MEMORY,
    }
    params.update(overrides)
    return OpenUsLawBm25Config(**params)


# ---------------------------------------------------------------------------
# Tokenizer (shared by build and query)
# ---------------------------------------------------------------------------


def tokenize_index_text(
    text: str,
    *,
    config: OpenUsLawBm25Config | TokenizerConfig | None = None,
) -> tuple[str, ...]:
    """Tokenize field text with the sealed legal tokenizer (build path)."""

    tokenizer = _tokenizer_from(config)
    if not isinstance(text, str):
        raise Bm25ProjectionError("field text must be a string")
    if not text:
        return ()
    return tokenize_legal_text(text, config=tokenizer).indexable_terms


def tokenize_query(
    query: str,
    *,
    config: OpenUsLawBm25Config | TokenizerConfig | None = None,
    max_query_terms: int | None = None,
) -> tuple[str, ...]:
    """Tokenize a query with the same sealed legal tokenizer as build."""

    tokenizer = _tokenizer_from(config)
    if not isinstance(query, str):
        raise Bm25ProjectionError("query must be a string")
    limit = MAX_QUERY_TERMS if max_query_terms is None else max_query_terms
    if isinstance(config, OpenUsLawBm25Config):
        limit = config.max_query_terms if max_query_terms is None else max_query_terms
    limit = _require_positive_int(limit, "max_query_terms")
    if not query.strip():
        return ()
    terms = tokenize_legal_text(query, config=tokenizer).indexable_terms
    return terms[:limit]


def _tokenizer_from(
    config: OpenUsLawBm25Config | TokenizerConfig | None,
) -> TokenizerConfig:
    if config is None:
        return default_tokenizer_config()
    if isinstance(config, OpenUsLawBm25Config):
        return config.tokenizer
    if isinstance(config, TokenizerConfig):
        return config
    raise Bm25ConfigError("config must be OpenUsLawBm25Config or TokenizerConfig")


def shared_tokenizer_identity(
    config: OpenUsLawBm25Config | TokenizerConfig | None = None,
) -> dict[str, Any]:
    """Pinned tokenizer identity recorded on the index and query path."""

    tokenizer = _tokenizer_from(config)
    identity = tokenizer_identity(tokenizer)
    identity["shared_by"] = TOKENIZER_SHARED_BY
    identity["used_for_build"] = True
    identity["used_for_query"] = True
    return identity


# ---------------------------------------------------------------------------
# Document projection
# ---------------------------------------------------------------------------


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
    if bool(row.get("is_recovery")) or str(row.get("record_type", "")).lower() in {
        "recovery",
        "workflow",
    }:
        return False
    return True


def _document_identity(row: Mapping[str, Any], *, position: int) -> str:
    for key in ("entry_cid", "chunk_cid", "record_id", "cid"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            reject_positional_durable_identity(text, name=key)
            if text.lower().startswith("row-"):
                raise PositionalIdentityError(
                    f"positional identity is forbidden for BM25 documents: {text!r}"
                )
            return validate_entry_cid(text, name=key)
    raise Bm25ProjectionError(
        f"corpus row {position} is missing durable entry_cid / chunk_cid"
    )


def _field_text_from_row(row: Mapping[str, Any], field_name: str) -> str:
    if not isinstance(row, Mapping):
        raise Bm25ProjectionError("corpus row must be a mapping")

    if field_name == "citation":
        for key in ("citation", "canonical_citation", "citation_text", "bluebook"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        jurisdiction = row.get("jurisdiction_code") or row.get("jurisdiction")
        title = row.get("title")
        section = row.get("section")
        if jurisdiction and title is not None and section is not None:
            return f"{jurisdiction} {title} § {section}"
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

    if field_name == "jurisdiction":
        for key in ("jurisdiction_name", "jurisdiction_code", "jurisdiction"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

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
    """One field-projected BM25 document for an admitted statute chunk."""

    entry_cid: str
    document_index: int
    fields: Mapping[str, FieldTokenStream]
    legal_id: Optional[str] = None
    chunk_cid: Optional[str] = None
    jurisdiction_code: Optional[str] = None
    title_code: Optional[str] = None
    section: Optional[str] = None
    record_type: str = "corpus"
    filters: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "entry_cid", validate_entry_cid(self.entry_cid, name="entry_cid")
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
        object.__setattr__(self, "filters", MappingProxyType(dict(self.filters or {})))

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

    def to_document_record(self) -> dict[str, Any]:
        return {
            "chunk_cid": self.chunk_cid,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "field_lengths": {name: self.field_length(name) for name in FIELD_ORDER},
            "filters": dict(self.filters),
            "jurisdiction_code": self.jurisdiction_code,
            "legal_id": self.legal_id,
            "record_type": self.record_type,
            "route_key": document_route_key(self.document_index),
            "section": self.section,
            "title_code": self.title_code,
            "total_length": self.total_length,
        }

    def to_posting_records(self) -> list[dict[str, Any]]:
        per_term: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for field_name, stream in self.fields.items():
            for term, tf in stream.term_frequencies().items():
                per_term[term][field_name] += int(tf)
        records: list[dict[str, Any]] = []
        for term in sorted(per_term):
            field_tf = {name: int(tf) for name, tf in per_term[term].items() if tf > 0}
            records.append(
                {
                    "document_index": self.document_index,
                    "entry_cid": self.entry_cid,
                    "field_tf": field_tf,
                    "term": term,
                    "tf": int(sum(field_tf.values())),
                }
            )
        return records


def project_legal_document(
    row: Mapping[str, Any],
    *,
    document_index: int,
    config: OpenUsLawBm25Config | None = None,
) -> LegalBm25Document:
    """Project one admitted corpus row into a multi-field BM25 document."""

    cfg = config or default_bm25_config()
    if not isinstance(cfg, OpenUsLawBm25Config):
        raise Bm25ConfigError("config must be an OpenUsLawBm25Config")
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
        terms = tokenize_index_text(text, config=cfg) if text else ()
        fields[field_name] = FieldTokenStream(
            field=field_name,
            text=text,
            terms=terms,
            weight=cfg.field_weights.weight_for(field_name),
        )

    if sum(stream.length for stream in fields.values()) <= 0:
        raise Bm25ProjectionError(f"document has no searchable tokens: {entry_cid}")

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
    jurisdiction = _optional_str(
        row.get("jurisdiction_code") or row.get("jurisdiction"),
        "jurisdiction_code",
        maximum=16,
    )
    filters: dict[str, str] = {}
    if jurisdiction:
        filters["jurisdiction"] = jurisdiction
    if title_code_str:
        filters["title"] = title_code_str
    if section_str:
        filters["section"] = section_str
    if legal_id:
        filters["legal_id"] = legal_id
    edition = row.get("edition")
    if isinstance(edition, str) and edition.strip():
        filters["edition"] = edition.strip()

    explicit_index = row.get("document_index")
    assigned = document_index
    if explicit_index is not None:
        assigned = _require_non_negative_int(explicit_index, "document_index")

    return LegalBm25Document(
        entry_cid=entry_cid,
        document_index=assigned,
        fields=fields,
        legal_id=legal_id,
        chunk_cid=chunk_cid,
        jurisdiction_code=jurisdiction,
        title_code=title_code_str,
        section=section_str,
        record_type=str(row.get("record_type") or "corpus"),
        filters=filters,
    )


def iter_projected_documents(
    rows: Iterable[Mapping[str, Any]],
    *,
    config: OpenUsLawBm25Config | None = None,
) -> Iterator[LegalBm25Document]:
    """Stream admitted rows into BM25 documents with no count truncation."""

    cfg = config or default_bm25_config()
    if isinstance(rows, (str, bytes, bytearray)):
        raise Bm25ProjectionError("corpus rows must be an iterable of mappings")
    assert_no_document_ceiling(cfg)
    admitted = 0
    seen: set[str] = set()
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise Bm25ProjectionError(f"corpus row {position} must be a mapping")
        if not _is_admitted_row(row):
            continue
        document = project_legal_document(
            row, document_index=admitted, config=cfg
        )
        if document.entry_cid in seen:
            raise Bm25CoverageError(
                f"duplicate entry_cid among BM25 documents: {document.entry_cid}"
            )
        seen.add(document.entry_cid)
        admitted += 1
        assert_document_count_admissible(admitted, cfg)
        yield document
    if admitted <= 0:
        raise Bm25CoverageError("no admitted corpus rows produced BM25 documents")


def project_admitted_documents(
    rows: Iterable[Mapping[str, Any]],
    *,
    config: OpenUsLawBm25Config | None = None,
) -> tuple[LegalBm25Document, ...]:
    """Materialize the admitted projection. Does not apply a 250k slice."""

    return tuple(iter_projected_documents(rows, config=config))


# ---------------------------------------------------------------------------
# Physical shards, posting cells, term ranges
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PostingPointer:
    """One document pointer inside a posting cell."""

    entry_cid: str
    document_index: int
    field_tf: Mapping[str, int]
    tf: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "entry_cid", validate_entry_cid(self.entry_cid, name="entry_cid")
        )
        object.__setattr__(
            self,
            "document_index",
            _require_non_negative_int(self.document_index, "document_index"),
        )
        frozen = {str(name): int(tf) for name, tf in dict(self.field_tf).items()}
        object.__setattr__(self, "field_tf", MappingProxyType(frozen))
        object.__setattr__(self, "tf", _require_positive_int(self.tf, "tf"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "field_tf": dict(self.field_tf),
            "tf": self.tf,
        }


@dataclass(frozen=True, slots=True)
class PostingCell:
    """At most 4,096 document pointers for one term."""

    pointers: tuple[PostingPointer, ...]

    def __post_init__(self) -> None:
        pointers = tuple(self.pointers)
        if not pointers:
            raise Bm25BoundError("posting cell must contain at least one pointer")
        if len(pointers) > MAX_POSTING_POINTERS_PER_ROW:
            raise Bm25BoundError(
                f"posting cell has {len(pointers)} pointers; "
                f"exceeds bound {MAX_POSTING_POINTERS_PER_ROW}"
            )
        object.__setattr__(self, "pointers", pointers)

    @property
    def pointer_count(self) -> int:
        return len(self.pointers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pointer_count": self.pointer_count,
            "pointers": [item.to_dict() for item in self.pointers],
        }


def split_posting_cells(
    pointers: Sequence[PostingPointer | Mapping[str, Any]],
    *,
    max_pointers: int = MAX_POSTING_POINTERS_PER_ROW,
) -> tuple[PostingCell, ...]:
    """Split a term's pointers into cells of at most *max_pointers*."""

    bound = _validate_physical_bound(
        max_pointers, name="max_pointers", maximum=MAX_POSTING_POINTERS_PER_ROW
    )
    resolved: list[PostingPointer] = []
    for item in pointers:
        if isinstance(item, PostingPointer):
            resolved.append(item)
            continue
        if not isinstance(item, Mapping):
            raise Bm25ProjectionError("posting pointer must be a mapping")
        field_tf = item.get("field_tf") or {}
        if not isinstance(field_tf, Mapping):
            raise Bm25ProjectionError("field_tf must be a mapping")
        resolved.append(
            PostingPointer(
                entry_cid=str(item["entry_cid"]),
                document_index=int(item["document_index"]),
                field_tf={str(name): int(tf) for name, tf in field_tf.items()},
                tf=int(item.get("tf") or sum(int(tf) for tf in field_tf.values())),
            )
        )
    if not resolved:
        raise Bm25CoverageError("cannot split an empty posting pointer list")
    cells: list[PostingCell] = []
    for offset in range(0, len(resolved), bound):
        chunk = tuple(resolved[offset : offset + bound])
        if len(chunk) > bound:
            raise Bm25BoundError("posting cell split exceeded the configured bound")
        cells.append(PostingCell(pointers=chunk))
    return tuple(cells)


@dataclass(frozen=True, slots=True)
class TermPosting:
    """One lexicographic term with bounded posting cells."""

    term: str
    document_frequency: int
    idf: float
    cells: tuple[PostingCell, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "term", _require_non_empty_str(self.term, "term"))
        object.__setattr__(
            self,
            "document_frequency",
            _require_positive_int(self.document_frequency, "document_frequency"),
        )
        if (
            isinstance(self.idf, bool)
            or not isinstance(self.idf, (int, float))
            or not math.isfinite(float(self.idf))
        ):
            raise Bm25ProjectionError("idf must be a finite number")
        object.__setattr__(self, "idf", float(self.idf))
        cells = tuple(self.cells)
        if not cells:
            raise Bm25CoverageError(f"term {self.term!r} has no posting cells")
        pointer_total = sum(cell.pointer_count for cell in cells)
        if pointer_total != self.document_frequency:
            raise Bm25CoverageError(
                f"term {self.term!r} pointer count {pointer_total} != df "
                f"{self.document_frequency}"
            )
        object.__setattr__(self, "cells", cells)

    @property
    def pointer_count(self) -> int:
        return sum(cell.pointer_count for cell in self.cells)

    @property
    def cell_count(self) -> int:
        return len(self.cells)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_count": self.cell_count,
            "cells": [cell.to_dict() for cell in self.cells],
            "document_frequency": self.document_frequency,
            "idf": self.idf,
            "pointer_count": self.pointer_count,
            "term": self.term,
        }


@dataclass(frozen=True, slots=True)
class DocumentShard:
    """At most 4,096 document rows sorted by document index."""

    shard_id: int
    documents: tuple[dict[str, Any], ...]
    relative_path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        documents = tuple(dict(item) for item in self.documents)
        if not documents:
            raise Bm25BoundError("document shard must contain at least one row")
        if len(documents) > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise Bm25BoundError(
                f"document shard has {len(documents)} rows; "
                f"exceeds bound {MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        object.__setattr__(self, "documents", documents)
        object.__setattr__(
            self, "shard_id", _require_non_negative_int(self.shard_id, "shard_id")
        )

    @property
    def row_count(self) -> int:
        return len(self.documents)

    @property
    def first_document_index(self) -> int:
        return int(self.documents[0]["document_index"])

    @property
    def last_document_index(self) -> int:
        return int(self.documents[-1]["document_index"])

    @property
    def first_key(self) -> str:
        return document_route_key(self.first_document_index)

    @property
    def last_key(self) -> str:
        return document_route_key(self.last_document_index)

    def to_route_descriptor(self) -> RouteDescriptor:
        return RouteDescriptor(
            first_key=self.first_key,
            last_key=self.last_key,
            relative_path=self.relative_path,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            row_count=self.row_count,
            shard_id=self.shard_id,
            kind="bm25_documents",
            start_document_index=self.first_document_index,
            end_document_index=self.last_document_index,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_document_index": self.first_document_index,
            "first_key": self.first_key,
            "last_document_index": self.last_document_index,
            "last_key": self.last_key,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "shard_id": self.shard_id,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class TermRangeShard:
    """At most 4,096 lexicographic term rows with bounded posting cells."""

    shard_id: int
    terms: tuple[TermPosting, ...]
    relative_path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        terms = tuple(self.terms)
        if not terms:
            raise Bm25BoundError("term-range shard must contain at least one term")
        if len(terms) > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise Bm25BoundError(
                f"term-range shard has {len(terms)} rows; "
                f"exceeds bound {MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        names = [item.term for item in terms]
        if names != sorted(names):
            raise Bm25CoverageError("term-range shard is not lexicographically sorted")
        object.__setattr__(self, "terms", terms)
        object.__setattr__(
            self, "shard_id", _require_non_negative_int(self.shard_id, "shard_id")
        )

    @property
    def row_count(self) -> int:
        return len(self.terms)

    @property
    def first_term(self) -> str:
        return self.terms[0].term

    @property
    def last_term(self) -> str:
        return self.terms[-1].term

    def covers(self, term: str) -> bool:
        return self.first_term <= term <= self.last_term

    def term_row(self, term: str) -> TermPosting | None:
        for item in self.terms:
            if item.term == term:
                return item
        return None

    def to_route_descriptor(self) -> RouteDescriptor:
        return RouteDescriptor(
            first_key=self.first_term,
            last_key=self.last_term,
            relative_path=self.relative_path,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            row_count=self.row_count,
            shard_id=self.shard_id,
            kind="bm25_postings",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_key": self.first_term,
            "first_term": self.first_term,
            "last_key": self.last_term,
            "last_term": self.last_term,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "shard_id": self.shard_id,
            "size_bytes": self.size_bytes,
        }


def _shard_payload_digest(payload: Mapping[str, Any]) -> tuple[str, int]:
    blob = canonical_json_bytes(dict(payload))
    return content_sha256(blob), len(blob)


def shard_document_records(
    records: Sequence[Mapping[str, Any]],
    *,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
) -> tuple[DocumentShard, ...]:
    bound = _validate_physical_bound(
        max_rows, name="max_rows", maximum=MAX_ROWS_PER_PHYSICAL_SHARD
    )
    if not records:
        raise Bm25CoverageError("cannot shard an empty document stream")
    shards: list[DocumentShard] = []
    for shard_id, start in enumerate(range(0, len(records), bound)):
        rows = [dict(item) for item in records[start : start + bound]]
        if len(rows) > bound:
            raise Bm25BoundError("document shard split exceeded the configured bound")
        indexes = [int(item["document_index"]) for item in rows]
        if indexes != sorted(indexes):
            raise Bm25CoverageError("document shard is not sorted by document_index")
        payload = {
            "documents": rows,
            "schema_version": SCHEMA_VERSION,
            "shard_id": shard_id,
        }
        digest, size = _shard_payload_digest(payload)
        shards.append(
            DocumentShard(
                shard_id=shard_id,
                documents=tuple(rows),
                relative_path=part_relative_path(DOCUMENT_DATA_DIR, shard_id),
                sha256=digest,
                size_bytes=size,
            )
        )
    return tuple(shards)


def shard_term_records(
    terms: Sequence[TermPosting],
    *,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
) -> tuple[TermRangeShard, ...]:
    bound = _validate_physical_bound(
        max_rows, name="max_rows", maximum=MAX_ROWS_PER_PHYSICAL_SHARD
    )
    if not terms:
        raise Bm25CoverageError("cannot shard an empty term stream")
    shards: list[TermRangeShard] = []
    for shard_id, start in enumerate(range(0, len(terms), bound)):
        rows = tuple(terms[start : start + bound])
        if len(rows) > bound:
            raise Bm25BoundError("term shard split exceeded the configured bound")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "shard_id": shard_id,
            "terms": [item.to_dict() for item in rows],
        }
        digest, size = _shard_payload_digest(payload)
        shards.append(
            TermRangeShard(
                shard_id=shard_id,
                terms=rows,
                relative_path=part_relative_path(POSTING_DATA_DIR, shard_id),
                sha256=digest,
                size_bytes=size,
            )
        )
    return tuple(shards)


# ---------------------------------------------------------------------------
# External sort
# ---------------------------------------------------------------------------


def _sort_receipt_summary(receipt: ExternalSortReceipt) -> dict[str, Any]:
    return {
        "externally_sorted": receipt.status == "complete" and not receipt.interrupted,
        "family": receipt.family,
        "max_records_in_memory": receipt.max_records_in_memory,
        "peak_resident_records": receipt.peak_resident_records,
        "records_consumed": receipt.records_consumed,
        "row_count": receipt.row_count,
        "run_count": receipt.run_count,
        "status": receipt.status,
    }


def external_sort_documents(
    records: Iterable[Mapping[str, Any]],
    *,
    work_dir: PathLike,
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Externally sort document records by ``(document_index, entry_cid)``."""

    work = Path(work_dir)
    output = work / "documents.sorted.jsonl"
    receipt = external_sort_to_file(
        records,
        output,
        work_dir=work / "documents-sort",
        key_fn=document_sort_key,
        family="documents",
        max_records_in_memory=max_records_in_memory,
        resume=False,
    )
    if receipt.interrupted:
        raise OpenUsLawBm25Error("document external sort interrupted before merge")
    ordered = list(iter_jsonl(output))
    for previous, current in zip(ordered, ordered[1:]):
        if document_sort_key(current) < document_sort_key(previous):
            raise Bm25CoverageError("document stream is not externally sorted")
    return ordered, _sort_receipt_summary(receipt)


def external_sort_postings(
    records: Iterable[Mapping[str, Any]],
    *,
    work_dir: PathLike,
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Externally sort posting records by ``(term, entry_cid)``."""

    work = Path(work_dir)
    output = work / "postings.sorted.jsonl"
    receipt = external_sort_to_file(
        records,
        output,
        work_dir=work / "postings-sort",
        key_fn=posting_sort_key,
        family="postings",
        max_records_in_memory=max_records_in_memory,
        resume=False,
    )
    if receipt.interrupted:
        raise OpenUsLawBm25Error("posting external sort interrupted before merge")
    ordered = list(iter_jsonl(output))
    for previous, current in zip(ordered, ordered[1:]):
        if posting_sort_key(current) < posting_sort_key(previous):
            raise Bm25CoverageError("posting stream is not externally sorted")
    return ordered, _sort_receipt_summary(receipt)


def external_sort_terms(
    records: Iterable[Mapping[str, Any]],
    *,
    work_dir: PathLike,
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Externally sort term-range records lexicographically."""

    work = Path(work_dir)
    output = work / "terms.sorted.jsonl"
    receipt = external_sort_to_file(
        records,
        output,
        work_dir=work / "terms-sort",
        key_fn=term_sort_key,
        family="terms",
        max_records_in_memory=max_records_in_memory,
        resume=False,
    )
    if receipt.interrupted:
        raise OpenUsLawBm25Error("term external sort interrupted before merge")
    ordered = list(iter_jsonl(output))
    for previous, current in zip(ordered, ordered[1:]):
        if term_sort_key(current) < term_sort_key(previous):
            raise Bm25CoverageError("term stream is not lexicographically sorted")
    return ordered, _sort_receipt_summary(receipt)


def group_sorted_postings(
    postings: Sequence[Mapping[str, Any]],
    *,
    document_count: int,
    postings_per_cell: int,
) -> list[TermPosting]:
    """Collapse a ``(term, entry_cid)``-sorted stream into term rows."""

    n_docs = _require_positive_int(document_count, "document_count")
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    order: list[str] = []
    for record in postings:
        term = _require_non_empty_str(record.get("term"), "term")
        if term not in grouped:
            grouped[term] = []
            order.append(term)
        grouped[term].append(record)
    terms: list[TermPosting] = []
    for term in order:
        rows = grouped[term]
        cells = split_posting_cells(rows, max_pointers=postings_per_cell)
        df = sum(cell.pointer_count for cell in cells)
        idf = robertson_sparck_jones_idf(df, n_docs)
        terms.append(
            TermPosting(
                term=term,
                document_frequency=df,
                idf=idf,
                cells=cells,
            )
        )
    return terms


def robertson_sparck_jones_idf(document_frequency: int, document_count: int) -> float:
    """Robertson-Sparck-Jones IDF with a floor at zero."""

    df = _require_non_negative_int(document_frequency, "document_frequency")
    n_docs = _require_positive_int(document_count, "document_count")
    if df <= 0:
        return 0.0
    raw = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
    return max(0.0, float(raw))


# ---------------------------------------------------------------------------
# Scoring / index
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
    routed_shard_id: int
    routed_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_contributions": [item.to_dict() for item in self.field_contributions],
            "idf": self.idf,
            "routed_path": self.routed_path,
            "routed_shard_id": self.routed_shard_id,
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
class OpenUsLawBm25Index:
    """Field-weighted term-range BM25 index bound to a corpus root."""

    documents: tuple[LegalBm25Document, ...]
    document_records: tuple[dict[str, Any], ...]
    document_shards: tuple[DocumentShard, ...]
    term_shards: tuple[TermRangeShard, ...]
    document_routes: HierarchicalRouteIndex
    term_routes: HierarchicalRouteIndex
    config: OpenUsLawBm25Config
    corpus_root_cid: str
    index_root_cid: str
    average_document_length: float
    average_field_lengths: Mapping[str, float]
    term_count: int
    token_instance_count: int
    posting_count: int
    sort_receipts: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        if not self.documents:
            raise Bm25CoverageError("BM25 index requires at least one document")
        object.__setattr__(
            self,
            "average_field_lengths",
            MappingProxyType(dict(self.average_field_lengths)),
        )
        object.__setattr__(
            self,
            "sort_receipts",
            MappingProxyType({key: dict(value) for key, value in self.sort_receipts.items()}),
        )
        assert_shards_bounded(self)
        assert_no_document_ceiling(self.config)

    @property
    def document_count(self) -> int:
        return len(self.documents)

    @property
    def document_shard_count(self) -> int:
        return len(self.document_shards)

    @property
    def term_shard_count(self) -> int:
        return len(self.term_shards)

    @property
    def tokenizer_id(self) -> str:
        return self.config.tokenizer.tokenizer_id

    def document_by_cid(self, entry_cid: str) -> LegalBm25Document:
        for document in self.documents:
            if document.entry_cid == entry_cid:
                return document
        raise Bm25CoverageError(f"unknown BM25 document: {entry_cid}")

    def document_frequency(self, term: str) -> int:
        posting = self.term_posting(term)
        return 0 if posting is None else posting.document_frequency

    def idf(self, term: str) -> float:
        posting = self.term_posting(term)
        if posting is None:
            return 0.0
        return posting.idf

    def term_posting(self, term: str) -> TermPosting | None:
        shard = self.route_term_shard(term)
        if shard is None:
            return None
        return shard.term_row(term)

    def route_term_shard(self, term: str) -> TermRangeShard | None:
        """Return the unique term-range shard covering *term*, or ``None``."""

        if not self.term_routes.covers(term):
            return None
        try:
            hit = self.term_routes.locate(term)
        except MissingRouteKeyError:
            return None
        shard = self.term_shards[hit.leaf.shard_id]
        if not shard.covers(term):
            return None
        return shard

    def route_query_terms(self, terms: Sequence[str]) -> tuple[TermRangeShard, ...]:
        """Fetch only shards whose inclusive term ranges cover *terms*."""

        seen: dict[int, TermRangeShard] = {}
        for term in terms:
            shard = self.route_term_shard(term)
            if shard is None:
                continue
            seen[shard.shard_id] = shard
        return tuple(seen[key] for key in sorted(seen))

    def explain_term(
        self,
        document: LegalBm25Document,
        term: str,
        *,
        routed_shard: TermRangeShard | None = None,
    ) -> TermScoreExplanation:
        shard = routed_shard or self.route_term_shard(term)
        idf = 0.0 if shard is None else self.idf(term)
        contributions: list[FieldScoreContribution] = []
        total = 0.0
        for field_name in FIELD_ORDER:
            stream = document.fields.get(field_name)
            if stream is None:
                continue
            tf = int(stream.term_frequencies().get(term, 0))
            if tf <= 0:
                continue
            avg_field_len = float(
                self.average_field_lengths.get(field_name, self.average_document_length)
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
            routed_shard_id=-1 if shard is None else shard.shard_id,
            routed_path="" if shard is None else shard.relative_path,
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: Mapping[str, str] | None = None,
    ) -> list[Bm25Hit]:
        """Score documents for *query* via term-range routing and the shared tokenizer."""

        if not isinstance(query, str):
            raise Bm25ProjectionError("query must be a string")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise Bm25ConfigError("top_k must be a positive integer")
        query_terms = tokenize_query(query, config=self.config)
        if not query_terms:
            return []

        active_filters = dict(filters or {})
        for key, value in active_filters.items():
            if not isinstance(key, str) or not key.strip():
                raise Bm25FilterError("filter keys must be non-empty strings")
            if not isinstance(value, str) or not value.strip():
                raise Bm25FilterError(f"filter {key!r} must be a non-empty string")

        by_cid = {document.entry_cid: document for document in self.documents}
        scores: dict[str, float] = defaultdict(float)
        matched: dict[str, list[str]] = defaultdict(list)
        explanations: dict[str, list[TermScoreExplanation]] = defaultdict(list)
        routed_shards = self.route_query_terms(query_terms)
        routed_ids = {shard.shard_id for shard in routed_shards}

        seen_terms: set[str] = set()
        for term in query_terms:
            if term in seen_terms:
                continue
            seen_terms.add(term)
            shard = self.route_term_shard(term)
            if shard is None or shard.shard_id not in routed_ids:
                continue
            posting = shard.term_row(term)
            if posting is None:
                continue
            for cell in posting.cells:
                if cell.pointer_count > self.config.postings_per_cell:
                    raise Bm25BoundError(
                        f"posting cell for {term!r} exceeds postings_per_cell"
                    )
                for pointer in cell.pointers:
                    document = by_cid.get(pointer.entry_cid)
                    if document is None:
                        continue
                    if active_filters and not _document_matches_filters(
                        document, active_filters
                    ):
                        continue
                    explanation = self.explain_term(
                        document, term, routed_shard=shard
                    )
                    if explanation.total_score <= 0.0:
                        continue
                    scores[document.entry_cid] += explanation.total_score
                    matched[document.entry_cid].append(term)
                    explanations[document.entry_cid].append(explanation)

        hits: list[Bm25Hit] = []
        for entry_cid, score in scores.items():
            document = by_cid[entry_cid]
            hits.append(
                Bm25Hit(
                    entry_cid=document.entry_cid,
                    document_index=document.document_index,
                    score=score,
                    matched_terms=tuple(matched[entry_cid]),
                    explanations=tuple(explanations[entry_cid]),
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
                "average_field_lengths": dict(self.average_field_lengths),
                "b": self.config.b,
                "config_digest": self.config.digest,
                "corpus_root_cid": self.corpus_root_cid,
                "document_count": self.document_count,
                "document_shard_count": self.document_shard_count,
                "documents_sorted_by": DOCUMENTS_SORTED_BY,
                "field_weights": self.config.field_weights.to_dict(),
                "index_root_cid": self.index_root_cid,
                "k1": self.config.k1,
                "legacy_parameter_delta": legacy_parameter_delta(),
                "max_documents": self.config.max_documents,
                "postings_sorted_by": POSTINGS_SORTED_BY,
                "primary_key": PRIMARY_KEY,
                "schema_version": SCHEMA_VERSION,
                "term_count": self.term_count,
                "term_shard_count": self.term_shard_count,
                "terms_sorted_by": TERMS_SORTED_BY,
                "token_instance_count": self.token_instance_count,
                "tokenizer": shared_tokenizer_identity(self.config),
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
            if key == "title":
                actual = document.title_code
            elif key == "section":
                actual = document.section
            elif key == "legal_id":
                actual = document.legal_id
            elif key == "entry_cid":
                actual = document.entry_cid
            elif key == "jurisdiction":
                actual = document.jurisdiction_code
        if actual is None or str(actual) != str(expected):
            return False
    return True


def assert_shards_bounded(index: OpenUsLawBm25Index) -> None:
    """Fail closed when any shard or posting cell exceeds 4,096."""

    for shard in index.document_shards:
        if shard.row_count > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise Bm25BoundError(
                f"document shard {shard.shard_id} has {shard.row_count} rows"
            )
        if shard.row_count > index.config.max_rows_per_shard:
            raise Bm25BoundError(
                f"document shard {shard.shard_id} exceeds configured max_rows_per_shard"
            )
    for shard in index.term_shards:
        if shard.row_count > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise Bm25BoundError(
                f"term shard {shard.shard_id} has {shard.row_count} rows"
            )
        if shard.row_count > index.config.max_rows_per_shard:
            raise Bm25BoundError(
                f"term shard {shard.shard_id} exceeds configured max_rows_per_shard"
            )
        for term in shard.terms:
            for cell in term.cells:
                if cell.pointer_count > MAX_POSTING_POINTERS_PER_ROW:
                    raise Bm25BoundError(
                        f"posting cell for {term.term!r} has {cell.pointer_count} pointers"
                    )
                if cell.pointer_count > index.config.postings_per_cell:
                    raise Bm25BoundError(
                        f"posting cell for {term.term!r} exceeds postings_per_cell"
                    )
    for page in index.document_routes.pages:
        if len(page) > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise Bm25BoundError(
                f"document route page exceeds 4096 descriptors: {page.relative_path}"
            )
    for page in index.term_routes.pages:
        if len(page) > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise Bm25BoundError(
                f"term route page exceeds 4096 descriptors: {page.relative_path}"
            )


def assert_externally_sorted(index: OpenUsLawBm25Index) -> None:
    """Fail closed when documents or terms were not externally sorted."""

    documents = index.sort_receipts.get("documents") or {}
    terms = index.sort_receipts.get("terms") or {}
    postings = index.sort_receipts.get("postings") or {}
    for label, receipt in (
        ("documents", documents),
        ("terms", terms),
        ("postings", postings),
    ):
        if receipt.get("externally_sorted") is not True:
            raise Bm25CoverageError(f"{label} were not externally sorted")
    indexes = [doc.document_index for doc in index.documents]
    if indexes != sorted(indexes):
        raise Bm25CoverageError("documents are not sorted by document_index")
    names: list[str] = []
    for shard in index.term_shards:
        names.extend(item.term for item in shard.terms)
    if names != sorted(names):
        raise Bm25CoverageError("term ranges are not lexicographically sorted")


# ---------------------------------------------------------------------------
# Roots / coverage
# ---------------------------------------------------------------------------


def build_corpus_root_cid(rows: Iterable[Mapping[str, Any]]) -> str:
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
            "schema_version": "open-us-law-corpus-root/v1",
        }
    )


def build_index_root_cid(
    documents: Sequence[LegalBm25Document],
    *,
    config: OpenUsLawBm25Config,
    corpus_root_cid: str,
    document_shards: Sequence[DocumentShard],
    term_shards: Sequence[TermRangeShard],
) -> str:
    """Content-address the BM25 index surface bound to *corpus_root_cid*."""

    structural = {
        "config_digest": config.digest,
        "corpus_root_cid": corpus_root_cid,
        "document_shards": [shard.to_dict() for shard in document_shards],
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
        "term_shards": [shard.to_dict() for shard in term_shards],
        "tokenizer_id": config.tokenizer.tokenizer_id,
    }
    return content_cid(structural)


def assert_every_admitted_chunk_has_document(
    rows: Iterable[Mapping[str, Any]],
    index: OpenUsLawBm25Index,
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
    index: OpenUsLawBm25Index,
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
        document_shards=index.document_shards,
        term_shards=index.term_shards,
    )
    if recomputed != index.index_root_cid:
        raise Bm25RootReconcileError(
            "index_root_cid does not recompute from documents and corpus root"
        )
    return {
        "corpus_root_cid": index.corpus_root_cid,
        "document_count": index.document_count,
        "index_root_cid": index.index_root_cid,
        "reconciled": True,
    }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_open_us_law_bm25_index(
    rows: Iterable[Mapping[str, Any]],
    *,
    config: OpenUsLawBm25Config | None = None,
    corpus_root_cid: str | None = None,
    work_dir: PathLike | None = None,
) -> OpenUsLawBm25Index:
    """Build the scalable field-weighted term-range BM25 index."""

    cfg = config or default_bm25_config()
    if not isinstance(cfg, OpenUsLawBm25Config):
        raise Bm25ConfigError("config must be an OpenUsLawBm25Config")
    assert_no_document_ceiling(cfg)

    materialized = list(rows)
    documents = project_admitted_documents(materialized, config=cfg)
    by_cid = {document.entry_cid: document for document in documents}

    own_temp = work_dir is None
    work = Path(work_dir) if work_dir is not None else Path(
        tempfile.mkdtemp(prefix="oul-bm25-")
    )
    work.mkdir(parents=True, exist_ok=True)
    try:
        document_records, document_sort = external_sort_documents(
            (document.to_document_record() for document in documents),
            work_dir=work / "documents",
            max_records_in_memory=cfg.max_records_in_memory,
        )
        posting_records, posting_sort = external_sort_postings(
            (
                record
                for document in documents
                for record in document.to_posting_records()
            ),
            work_dir=work / "postings",
            max_records_in_memory=cfg.max_records_in_memory,
        )
        ordered_documents = tuple(
            by_cid[str(record["entry_cid"])] for record in document_records
        )

        document_shards = shard_document_records(
            document_records, max_rows=cfg.max_rows_per_shard
        )
        # Confirm the same bound when streaming partitions (production path).
        streamed = list(
            stream_bounded_partitions(
                document_records, max_rows=cfg.max_rows_per_shard
            )
        )
        if len(streamed) != len(document_shards):
            raise Bm25BoundError("document partition count does not match shards")

        n_docs = len(ordered_documents)
        assert_document_count_admissible(n_docs, cfg)
        token_instances = sum(document.total_length for document in ordered_documents)
        field_length_sums = {name: 0 for name in FIELD_ORDER}
        for document in ordered_documents:
            for name in FIELD_ORDER:
                field_length_sums[name] += document.field_length(name)
        avgdl = float(token_instances) / float(n_docs)
        average_field_lengths = {
            name: float(field_length_sums[name]) / float(n_docs) for name in FIELD_ORDER
        }

        grouped_terms = group_sorted_postings(
            posting_records,
            document_count=n_docs,
            postings_per_cell=cfg.postings_per_cell,
        )
        term_payloads = [item.to_dict() for item in grouped_terms]
        sorted_term_payloads, term_sort = external_sort_terms(
            term_payloads,
            work_dir=work / "terms",
            max_records_in_memory=cfg.max_records_in_memory,
        )
        terms_by_name = {item.term: item for item in grouped_terms}
        ordered_terms = [terms_by_name[str(item["term"])] for item in sorted_term_payloads]
        term_shards = shard_term_records(ordered_terms, max_rows=cfg.max_rows_per_shard)

        document_routes = build_hierarchical_routes(
            [shard.to_route_descriptor() for shard in document_shards],
            kind="bm25_documents",
            max_rows_per_page=cfg.max_route_page_rows,
            route_dir=DOCUMENT_ROUTE_DIR,
        )
        term_routes = build_hierarchical_routes(
            [shard.to_route_descriptor() for shard in term_shards],
            kind="bm25_postings",
            max_rows_per_page=cfg.max_route_page_rows,
            route_dir=TERM_ROUTE_DIR,
        )
    finally:
        if own_temp:
            # Sorted JSONL lives only for the build; shards are in memory.
            try:
                import shutil

                shutil.rmtree(work, ignore_errors=True)
            except OSError:
                pass

    root = corpus_root_cid or build_corpus_root_cid(materialized)
    root = _require_non_empty_str(root, "corpus_root_cid", maximum=128)
    index_root = build_index_root_cid(
        ordered_documents,
        config=cfg,
        corpus_root_cid=root,
        document_shards=document_shards,
        term_shards=term_shards,
    )
    posting_count = sum(
        term.pointer_count for shard in term_shards for term in shard.terms
    )
    index = OpenUsLawBm25Index(
        documents=ordered_documents,
        document_records=tuple(document_records),
        document_shards=document_shards,
        term_shards=term_shards,
        document_routes=document_routes,
        term_routes=term_routes,
        config=cfg,
        corpus_root_cid=root,
        index_root_cid=index_root,
        average_document_length=avgdl,
        average_field_lengths=average_field_lengths,
        term_count=len(ordered_terms),
        token_instance_count=token_instances,
        posting_count=posting_count,
        sort_receipts={
            "documents": document_sort,
            "postings": posting_sort,
            "terms": term_sort,
        },
    )
    reconcile_roots(index, expected_corpus_root_cid=root)
    assert_every_admitted_chunk_has_document(materialized, index)
    assert_externally_sorted(index)
    return index


# ---------------------------------------------------------------------------
# Fixture recipe (compact; no bulk golden dumps)
# ---------------------------------------------------------------------------


def _cid(nibble: str) -> str:
    return f"sha256:{nibble.lower() * 64}"


def fixture_bm25_chunks() -> list[dict[str, Any]]:
    """Compact admitted exact-51-style statute sample for sealed unit fixtures."""

    return [
        {
            "entry_cid": _cid("a"),
            "chunk_cid": _cid("b"),
            "legal_id": "oul:or:174:010",
            "jurisdiction_code": "OR",
            "jurisdiction_name": "Oregon",
            "title": "174",
            "title_name": "Construction of Statutes",
            "chapter": "174",
            "section": "010",
            "heading": "General rule for construction of statutes",
            "citation": "OR 174 § 010",
            "body": (
                "In the construction of a statute, the office of the judge is "
                "simply to ascertain and declare what is, in terms or in "
                "substance, contained therein. Unique token oregonconstruction."
            ),
            "note": "Oregon statute construction.",
            "disposition": "admitted",
            "document_index": 3,
            "edition": "2024",
        },
        {
            "entry_cid": _cid("c"),
            "chunk_cid": _cid("d"),
            "legal_id": "oul:ca:1:1",
            "jurisdiction_code": "CA",
            "jurisdiction_name": "California",
            "title": "1",
            "title_name": "Preliminary Provisions",
            "chapter": "1",
            "section": "1",
            "heading": "Title of act",
            "citation": "CA 1 § 1",
            "body": (
                "This act shall be known as the Civil Code of the State of "
                "California. Unique token californiaevidence. The statute "
                "governs civil obligations."
            ),
            "disposition": "admitted",
            "document_index": 0,
            "edition": "2024",
        },
        {
            "entry_cid": _cid("e"),
            "chunk_cid": _cid("f"),
            "legal_id": "oul:dc:2:531",
            "jurisdiction_code": "DC",
            "jurisdiction_name": "District of Columbia",
            "title": "2",
            "title_name": "Government Administration",
            "chapter": "5",
            "section": "531",
            "heading": "Open meetings",
            "citation": "DC 2 § 531",
            "body": (
                "All meetings of public bodies shall be open to the public. "
                "Unique token dcopenmeetings. The statute requires notice."
            ),
            "disposition": "admitted",
            "document_index": 1,
            "edition": "2024",
        },
        {
            "entry_cid": _cid("1"),
            "chunk_cid": _cid("2"),
            "legal_id": "oul:ny:5:86",
            "jurisdiction_code": "NY",
            "jurisdiction_name": "New York",
            "title": "5",
            "title_name": "Public Officers Law",
            "chapter": "47",
            "section": "86",
            "heading": "Definitions",
            "citation": "NY 5 § 86",
            "body": (
                "As used in this article, agency means any state or municipal "
                "department, board, bureau, or public body. Unique token "
                "newyorkfoil. The statute defines public records."
            ),
            "disposition": "admitted",
            "document_index": 2,
            "edition": "2024",
        },
        {
            "entry_cid": _cid("3"),
            "chunk_cid": _cid("4"),
            "legal_id": "oul:tx:552:001",
            "jurisdiction_code": "TX",
            "jurisdiction_name": "Texas",
            "title": "552",
            "title_name": "Public Information",
            "chapter": "552",
            "section": "001",
            "heading": "Policy; construction",
            "citation": "TX 552 § 001",
            "body": (
                "Under the fundamental philosophy of the American "
                "constitutional form of representative government, each person "
                "is entitled to complete information about the affairs of "
                "government. Unique token texaspublicinfo. The statute "
                "declares a public information policy."
            ),
            "disposition": "admitted",
            "document_index": 4,
            "edition": "2024",
        },
        {
            "entry_cid": _cid("5"),
            "chunk_cid": _cid("6"),
            "legal_id": "oul:wa:42:56:030",
            "jurisdiction_code": "WA",
            "jurisdiction_name": "Washington",
            "title": "42",
            "title_name": "Public Officers and Agencies",
            "chapter": "56",
            "section": "030",
            "heading": "Findings",
            "citation": "WA 42.56 § 030",
            "body": (
                "The people of this state do not yield their sovereignty to "
                "the agencies that serve them. Unique token washingtonpra. "
                "The statute favors disclosure of public records."
            ),
            "disposition": "admitted",
            "document_index": 5,
            "edition": "2024",
        },
        {
            "entry_cid": _cid("7"),
            "chunk_cid": _cid("8"),
            "legal_id": "oul:fl:119:01",
            "jurisdiction_code": "FL",
            "jurisdiction_name": "Florida",
            "title": "119",
            "title_name": "Public Records",
            "chapter": "119",
            "section": "01",
            "heading": "General state policy on public records",
            "citation": "FL 119 § 01",
            "body": (
                "It is the policy of this state that all state, county, and "
                "municipal records are open for personal inspection. Unique "
                "token floridasunshine. The statute is a public records act."
            ),
            "disposition": "admitted",
            "document_index": 6,
            "edition": "2024",
        },
        {
            "entry_cid": _cid("9"),
            "chunk_cid": _cid("0"),
            "legal_id": "oul:il:5:140:1",
            "jurisdiction_code": "IL",
            "jurisdiction_name": "Illinois",
            "title": "5",
            "title_name": "General Provisions",
            "chapter": "140",
            "section": "1",
            "heading": "Public policy",
            "citation": "IL 5 ILCS 140/1",
            "body": (
                "Pursuant to the fundamental philosophy of the American "
                "constitutional form of government, it is declared to be the "
                "public policy of the State of Illinois that all persons are "
                "entitled to full and complete information. Unique token "
                "illinoisfia. The statute is a public records law."
            ),
            "disposition": "admitted",
            "document_index": 7,
            "edition": "2024",
        },
        {
            "entry_cid": "",
            "row_id": "recovery-src-01",
            "disposition": "quarantined",
            "is_recovery": True,
            "body": "workflow recovery payload must not enter BM25",
        },
        {
            "entry_cid": _cid("f"),
            "disposition": "excluded",
            "body": "excluded incomplete provenance row",
            "title": "99",
            "section": "999",
            "jurisdiction_code": "PR",
        },
    ]


def bind_fixture_bm25(
    chunks: Sequence[Mapping[str, Any]] | None = None,
    **overrides: Any,
) -> OpenUsLawBm25Index:
    """Bind the compact fixture recipe with tight physical test bounds."""

    rows = list(chunks) if chunks is not None else fixture_bm25_chunks()
    config = overrides.pop("config", None) or fixture_bm25_config(**overrides)
    work_dir = overrides.pop("work_dir", None)
    corpus_root = overrides.pop("corpus_root_cid", None)
    return build_open_us_law_bm25_index(
        rows,
        config=config,
        corpus_root_cid=corpus_root,
        work_dir=work_dir,
    )


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def default_bm25_receipt_path() -> Path:
    return Path(__file__).resolve().parents[3] / RECEIPT_RELATIVE_PATH


def software_contract_flags() -> dict[str, Any]:
    return {
        "authorizing_for_publication": AUTHORIZES_PUBLICATION,
        "authorizing_for_release": AUTHORIZES_RELEASE,
        "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
    }


def production_bm25_bounds() -> dict[str, Any]:
    return {
        "document_count_ceiling": DOCUMENT_COUNT_CEILING,
        "exact_51_seed_row_lower_bound": EXACT_51_SEED_ROW_LOWER_BOUND,
        "forbidden_document_ceiling": FORBIDDEN_DOCUMENT_CEILING,
        "maximum_posting_pointers_per_cell": MAX_POSTING_POINTERS_PER_ROW,
        "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "maximum_route_page_rows": MAX_ROWS_PER_PHYSICAL_SHARD,
        "shared_layout_document_ceiling": FORBIDDEN_DOCUMENT_CEILING,
        "sort_order_documents": DOCUMENTS_SORTED_BY,
        "sort_order_postings": POSTINGS_SORTED_BY,
        "sort_order_terms": TERMS_SORTED_BY,
    }


def _acceptance_block() -> dict[str, bool]:
    return {
        "documents_and_term_ranges_externally_sorted": True,
        "every_shard_and_posting_cell_at_most_4096": True,
        "no_250000_document_ceiling": True,
        "one_versioned_legal_tokenizer_shared_by_build_and_query": True,
    }


def build_bm25_receipt(
    *,
    index: OpenUsLawBm25Index | None = None,
) -> dict[str, Any]:
    """Build the sealed software-contract BM25 receipt."""

    demo = index if index is not None else bind_fixture_bm25()
    query_terms = tokenize_query("public records statute", config=demo.config)
    build_terms = tokenize_index_text("public records statute", config=demo.config)
    hits = demo.search("public records statute", top_k=5)
    max_doc_rows = max(shard.row_count for shard in demo.document_shards)
    max_term_rows = max(shard.row_count for shard in demo.term_shards)
    max_cell = max(
        (cell.pointer_count for shard in demo.term_shards for term in shard.terms for cell in term.cells),
        default=0,
    )
    max_route = max(
        max((len(page) for page in demo.document_routes.pages), default=0),
        max((len(page) for page in demo.term_routes.pages), default=0),
    )
    payload: dict[str, Any] = {
        "acceptance": _acceptance_block(),
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "bounds": production_bm25_bounds(),
        "checks": {
            "build_query_tokenizer_terms_equal": list(build_terms) == list(query_terms),
            "demo_document_count": demo.document_count,
            "demo_document_shard_count": demo.document_shard_count,
            "demo_max_document_shard_rows": max_doc_rows,
            "demo_max_posting_cell_pointers": max_cell,
            "demo_max_route_page_rows": max_route,
            "demo_max_term_shard_rows": max_term_rows,
            "demo_posting_count": demo.posting_count,
            "demo_term_count": demo.term_count,
            "demo_term_shard_count": demo.term_shard_count,
            "documents_externally_sorted": bool(
                (demo.sort_receipts.get("documents") or {}).get("externally_sorted")
            ),
            "every_admitted_chunk_has_document": True,
            "forbidden_ceiling_would_truncate_exact_51_seed": inherited_shared_layout_would_truncate(
                EXACT_51_SEED_ROW_LOWER_BOUND
            ),
            "hierarchical_term_routes_present": demo.term_routes.page_count >= 1,
            "no_document_count_ceiling": demo.config.max_documents is None,
            "postings_externally_sorted": bool(
                (demo.sort_receipts.get("postings") or {}).get("externally_sorted")
            ),
            "production_max_posting_pointers": MAX_POSTING_POINTERS_PER_ROW,
            "production_max_rows_per_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "query_uses_legal_tokenizer": demo.tokenizer_id == TOKENIZER_ID,
            "term_range_routing_used": all(
                explanation.routed_path.startswith(POSTING_DATA_DIR)
                for hit in hits
                for explanation in hit.explanations
            ),
            "terms_externally_sorted": bool(
                (demo.sort_receipts.get("terms") or {}).get("externally_sorted")
            ),
            "tokenizer_id": TOKENIZER_ID,
            "tokenizer_shared_by": TOKENIZER_SHARED_BY,
            "tokenizer_version": TOKENIZER_VERSION,
        },
        "demo": {
            "authorizing_for_release": False,
            "average_document_length": demo.average_document_length,
            "config_digest": demo.config.digest,
            "corpus_root_cid": demo.corpus_root_cid,
            "document_count": demo.document_count,
            "document_route_page_count": demo.document_routes.page_count,
            "document_shard_count": demo.document_shard_count,
            "entry_cids": [doc.entry_cid for doc in demo.documents],
            "index_root_cid": demo.index_root_cid,
            "k1": demo.config.k1,
            "posting_count": demo.posting_count,
            "query_hit_count": len(hits),
            "sort_receipts": {
                name: dict(receipt) for name, receipt in demo.sort_receipts.items()
            },
            "term_count": demo.term_count,
            "term_route_height": demo.term_routes.height,
            "term_route_page_count": demo.term_routes.page_count,
            "term_shard_count": demo.term_shard_count,
            "tokenizer_id": demo.tokenizer_id,
        },
        "description": (
            "Software-contract receipt for OUL-027. One versioned legal "
            "tokenizer is shared by build and query. Documents and "
            "lexicographic term ranges are externally sorted. Every shard "
            "and posting cell has at most 4096 rows or pointers. No "
            "250000-document ceiling truncates the corpus. This receipt "
            "does not claim the live exact-51 corpus has been indexed."
        ),
        "exact_51_seed_row_lower_bound": EXACT_51_SEED_ROW_LOWER_BOUND,
        "field_weights": demo.config.field_weights.to_dict(),
        "goal_id": GOAL_ID,
        "parameters": {
            "b": DEFAULT_B,
            "k1": DEFAULT_K1,
            "legacy_parameter_delta": legacy_parameter_delta(),
            "stopword_policy_id": STOPWORD_POLICY_ID,
            "tokenizer_id": TOKENIZER_ID,
            "tokenizer_version": TOKENIZER_VERSION,
        },
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "repairs": {
            "area_id": "field_weighted_term_range_bm25",
            "owner_task": TASK_ID,
            "required": [
                (
                    "Use one versioned legal tokenizer for both BM25 build "
                    "and query, and record tokenizer revision, stopword "
                    "policy, k1, b, field weights, and average lengths."
                ),
                (
                    "Externally sort documents by stable document index and "
                    "terms/postings by lexicographic (term, entry_cid)."
                ),
                (
                    "Cap every document shard, term-range shard, route page, "
                    "and posting cell at 4096 rows or pointers."
                ),
                (
                    "Reject the inherited 250000-document ceiling so the "
                    "exact-51 seed (1904919 rows) is not truncated."
                ),
            ],
        },
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "sealed_at": RECEIPT_SEALED_AT,
        "stopword_policy_id": STOPWORD_POLICY_ID,
        "task_id": TASK_ID,
        "tokenizer": shared_tokenizer_identity(demo.config),
    }
    payload.update(software_contract_flags())
    payload["receipt_sha256"] = content_sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "receipt_sha256"}
        )
    )
    return payload


def write_bm25_receipt(path: PathLike | None = None) -> Path:
    target = Path(path) if path is not None else default_bm25_receipt_path()
    payload = build_bm25_receipt()
    write_json_atomic(target, payload)
    return target


def load_bm25_receipt(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_bm25_receipt_path()
    if not target.is_file():
        raise Bm25ReceiptError(f"BM25 receipt not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise Bm25ReceiptError("BM25 receipt root must be an object")
    return dict(payload)


def assert_bm25_receipt(payload: Mapping[str, Any]) -> None:
    """Fail closed if the receipt would authorize release or weaken the contract."""

    if payload.get("task_id") != TASK_ID:
        raise Bm25ReceiptError(f"receipt task_id must be {TASK_ID!r}")
    if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise Bm25ReceiptError(
            f"receipt schema_version must be {RECEIPT_SCHEMA_VERSION!r}"
        )
    if payload.get("authorizing_for_release") is True:
        raise Bm25ReleaseAuthorizationError("BM25 receipt cannot authorize release")
    if payload.get("authorizing_for_publication") is True:
        raise Bm25ReleaseAuthorizationError(
            "BM25 receipt cannot authorize publication"
        )
    bounds = payload.get("bounds") or {}
    if not isinstance(bounds, Mapping):
        raise Bm25ReceiptError("receipt bounds must be a mapping")
    if bounds.get("maximum_rows_per_physical_shard") != MAX_ROWS_PER_PHYSICAL_SHARD:
        raise Bm25ReceiptError("receipt physical shard bound must be 4096")
    if bounds.get("maximum_posting_pointers_per_cell") != MAX_POSTING_POINTERS_PER_ROW:
        raise Bm25ReceiptError("receipt posting-cell bound must be 4096")
    if bounds.get("document_count_ceiling") is not None:
        raise Bm25ReceiptError("receipt must not declare a document-count ceiling")
    if bounds.get("forbidden_document_ceiling") != FORBIDDEN_DOCUMENT_CEILING:
        raise Bm25ReceiptError("receipt must record the forbidden 250000 ceiling")
    acceptance = payload.get("acceptance") or {}
    if not isinstance(acceptance, Mapping):
        raise Bm25ReceiptError("receipt acceptance must be a mapping")
    for key, expected in _acceptance_block().items():
        if acceptance.get(key) is not expected:
            raise Bm25ReceiptError(f"receipt acceptance.{key} must be {expected}")
    parameters = payload.get("parameters") or {}
    if not isinstance(parameters, Mapping):
        raise Bm25ReceiptError("receipt parameters must be a mapping")
    if parameters.get("tokenizer_id") != TOKENIZER_ID:
        raise Bm25ReceiptError("receipt tokenizer_id is not the sealed legal tokenizer")
    if payload.get("proves_software_contract_only") is not True:
        raise Bm25ReceiptError("receipt must prove the software contract only")
    checks = payload.get("checks") or {}
    if not isinstance(checks, Mapping):
        raise Bm25ReceiptError("receipt checks must be a mapping")
    if checks.get("no_document_count_ceiling") is not True:
        raise Bm25ReceiptError("receipt must record that no document ceiling is set")
    if checks.get("forbidden_ceiling_would_truncate_exact_51_seed") is not True:
        raise Bm25ReceiptError(
            "receipt must record that 250000 would truncate the exact-51 seed"
        )


__all__ = [
    "AUTHORITY_FIELDS",
    "CONTENT_FIELDS",
    "DEFAULT_B",
    "DEFAULT_FIELD_WEIGHTS",
    "DEFAULT_K1",
    "DOCUMENT_COUNT_CEILING",
    "DOCUMENTS_SORTED_BY",
    "EXACT_51_SEED_ROW_LOWER_BOUND",
    "FIELD_ORDER",
    "FORBIDDEN_DOCUMENT_CEILING",
    "GOAL_ID",
    "MAX_POSTING_POINTERS_PER_ROW",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "POSTINGS_SORTED_BY",
    "PRIMARY_KEY",
    "PRODUCER",
    "PROGRAM_ID",
    "RECEIPT_SCHEMA_VERSION",
    "RELEASE_PROFILE",
    "SCHEMA_VERSION",
    "TASK_ID",
    "TERMS_SORTED_BY",
    "TOKENIZER_ID",
    "TOKENIZER_SHARED_BY",
    "Bm25BoundError",
    "Bm25CeilingError",
    "Bm25ConfigError",
    "Bm25CoverageError",
    "Bm25FilterError",
    "Bm25Hit",
    "Bm25ProjectionError",
    "Bm25ReceiptError",
    "Bm25ReleaseAuthorizationError",
    "Bm25RootReconcileError",
    "DocumentShard",
    "FieldScoreContribution",
    "FieldTokenStream",
    "FieldWeightConfig",
    "IndexField",
    "LegalBm25Document",
    "OpenUsLawBm25Config",
    "OpenUsLawBm25Error",
    "OpenUsLawBm25Index",
    "PostingCell",
    "PostingPointer",
    "TermPosting",
    "TermRangeShard",
    "TermScoreExplanation",
    "assert_bm25_receipt",
    "assert_document_count_admissible",
    "assert_every_admitted_chunk_has_document",
    "assert_externally_sorted",
    "assert_no_document_ceiling",
    "assert_shards_bounded",
    "bind_fixture_bm25",
    "build_bm25_receipt",
    "build_corpus_root_cid",
    "build_index_root_cid",
    "build_open_us_law_bm25_index",
    "default_bm25_config",
    "default_bm25_receipt_path",
    "document_count_ceiling",
    "external_sort_documents",
    "external_sort_postings",
    "external_sort_terms",
    "fixture_bm25_chunks",
    "fixture_bm25_config",
    "inherited_shared_layout_would_truncate",
    "iter_projected_documents",
    "legacy_parameter_delta",
    "load_bm25_receipt",
    "production_bm25_bounds",
    "project_admitted_documents",
    "project_legal_document",
    "reconcile_roots",
    "robertson_sparck_jones_idf",
    "shared_tokenizer_identity",
    "shard_document_records",
    "shard_term_records",
    "split_posting_cells",
    "tokenize_index_text",
    "tokenize_query",
    "would_truncate_corpus",
    "write_bm25_receipt",
]
