"""State-law field-weighted term-range BM25 (LCR-027).

Adapter between admitted LCR-025 chunks / LCR-024 corpus rows and a
field-aware term-range BM25 index:

* one BM25 document per admitted searchable chunk;
* sealed legal tokenizer shared by build and query;
* jurisdiction-aware fields and census-region sample queries;
* postings sorted lexicographically by ``(term, chunk_cid)``;
* posting cells, term shards, document shards, and route pages bounded
  at 4,096 rows or pointers;
* inclusive lexicographic term-range routing (never vector centroids);
* differential scores equal to the shared reference BM25 formula.

Design invariants
-----------------
* Retrieval identity is the chunk CID. Parent ``entry_cid`` is a join key
  only; multiple chunks of one statute never share a posting pointer.
* Source lineage is never copied onto postings.
* Fixture builds are hermetic. No Hub upload, no tokens, no absolute
  home paths in receipts.
* Shared ``hf_graphrag`` layout/sort/route/score primitives are consumed,
  not duplicated.
* This receipt does not authorize publication.

Depends on LCR-025 (chunker) and LCR-026 (bounded adapter).
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

from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (
    assert_no_secrets_or_home_paths,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    ADR_PATH,
    DEFAULT_DATASET_REPO_ID,
    MAX_POSTING_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    RELEASE_PROFILE,
    PositionalIdentityError,
    digest_mapping,
    reject_positional_durable_identity,
    validate_entry_cid,
    validate_jurisdiction,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    CURRENTNESS_DISCLAIMER,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import (
    STOPWORD_POLICY_ID,
    TOKENIZER_ID as LEGAL_TOKENIZER_ID,
    TOKENIZER_VERSION as LEGAL_TOKENIZER_VERSION,
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

SCHEMA_VERSION: Final = "state-laws-bm25-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-bm25@1"
TASK_ID: Final = "LCR-027"
GOAL_ID: Final = "LCR-G040"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "state_laws_bm25.py"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "sparse-index"
CODE_VERSION: Final = "1"
CHUNKER_TASK_ID: Final = "LCR-025"
ADAPTER_TASK_ID: Final = "LCR-026"

TOKENIZER_ID: Final = "state-laws-bm25-tokenizer/v1"
TOKENIZER_VERSION: Final = "v1"
TOKENIZER_SHARED_BY: Final = "build_and_query"
PRIMARY_KEY: Final = "chunk_cid"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
AUTHORIZES_RELEASE: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True

REPORT_RELATIVE_PATH: Final = Path(
    "docs/reports/legal_corpora_reindex/bm25_evaluation.json"
)
_REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_K1: Final = 1.2
DEFAULT_B: Final = 0.75
LEGACY_K1: Final = 1.5
LEGACY_B: Final = 0.75

DOCUMENT_COUNT_CEILING: Final[int | None] = None
FORBIDDEN_DOCUMENT_CEILING: Final = 250_000
MAX_TEXT_CHARACTERS: Final = 8 * 1024 * 1024
MAX_QUERY_TERMS: Final = 64
SCORE_ABS_TOLERANCE: Final = 1e-12

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

DOCUMENTS_SORTED_BY: Final = "jurisdiction_then_document_index"
TERMS_SORTED_BY: Final = "lexicographic_term"
POSTINGS_SORTED_BY: Final = "term_then_chunk_cid"

DOCUMENT_DATA_DIR: Final = "data/bm25/documents"
POSTING_DATA_DIR: Final = "data/bm25/postings"
DOCUMENT_ROUTE_DIR: Final = "indexes/bm25_document_routes"
TERM_ROUTE_DIR: Final = "indexes/bm25_term_routes"

DEFAULT_TEST_MAX_ROWS_PER_SHARD: Final = 2
DEFAULT_TEST_POSTINGS_PER_CELL: Final = 2
DEFAULT_TEST_ROUTE_PAGE_ROWS: Final = 2
DEFAULT_TEST_MAX_RECORDS_IN_MEMORY: Final = 3

POSTING_LINEAGE_FORBIDDEN_FIELDS: Final = frozenset(
    {
        "acquisition_receipt_id",
        "acquisition_time",
        "attempts",
        "bm25_postings",
        "format_attempts",
        "official_url",
        "parser_version",
        "per_posting_lineage",
        "posting_ids",
        "posting_lineage",
        "postings",
        "source_checksum",
        "source_url",
        "term_postings",
    }
)

# Census regions plus an explicit DC bucket so sample/citation queries
# can prove coverage of all four regions and the District.
CENSUS_REGION_JURISDICTIONS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "northeast": frozenset(
            {"CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA"}
        ),
        "midwest": frozenset(
            {"IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD"}
        ),
        "south": frozenset(
            {
                "DE",
                "FL",
                "GA",
                "MD",
                "NC",
                "SC",
                "VA",
                "WV",
                "AL",
                "KY",
                "MS",
                "TN",
                "AR",
                "LA",
                "OK",
                "TX",
            }
        ),
        "west": frozenset(
            {"AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA"}
        ),
        "dc": frozenset({"DC"}),
    }
)
REQUIRED_QUERY_REGIONS: Final[tuple[str, ...]] = (
    "northeast",
    "midwest",
    "south",
    "west",
    "dc",
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StateLawsBm25Error(ValueError):
    """Base error for state-law field-weighted BM25 failures."""

    code: str = "state_laws_bm25_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class Bm25ConfigError(StateLawsBm25Error):
    """Raised when BM25 configuration is incomplete or invalid."""

    code = "config_invalid"


class Bm25CoverageError(StateLawsBm25Error):
    """Raised when admitted chunks and BM25 documents do not reconcile."""

    code = "coverage_invalid"


class Bm25ProjectionError(StateLawsBm25Error):
    """Raised when a legal document cannot be projected into BM25 fields."""

    code = "projection_invalid"


class Bm25BoundError(StateLawsBm25Error):
    """Raised when a shard, cell, or route page exceeds the 4,096 bound."""

    code = "physical_bound_exceeded"


class Bm25RootReconcileError(StateLawsBm25Error):
    """Raised when corpus root and index root do not reconcile."""

    code = "root_reconcile_failed"


class Bm25FilterError(StateLawsBm25Error):
    """Raised when a search filter is malformed."""

    code = "filter_invalid"


class Bm25ReceiptError(StateLawsBm25Error):
    """Raised when the sealed BM25 evaluation report is malformed."""

    code = "receipt_invalid"


class Bm25ReleaseAuthorizationError(StateLawsBm25Error):
    """Raised when a BM25 report would authorize release or Hub upload."""

    code = "release_authorization_forbidden"


class Bm25ScoreError(StateLawsBm25Error):
    """Raised when index scores diverge from reference BM25."""

    code = "score_mismatch"


class Bm25EvaluationError(StateLawsBm25Error):
    """Raised when fixture evaluation cannot complete fail-closed."""

    code = "evaluation_invalid"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class IndexField(str, Enum):
    """Named state-law BM25 fields."""

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
        raise StateLawsBm25Error(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise StateLawsBm25Error(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise StateLawsBm25Error(f"{name} exceeds maximum length {maximum}")
    return text


def _optional_str(value: Any, name: str, *, maximum: int = 4096) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name, maximum=maximum)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateLawsBm25Error(f"{name} must be an integer")
    if value < 0:
        raise StateLawsBm25Error(f"{name} must be >= 0")
    return value


def _require_positive_int(value: Any, name: str) -> int:
    number = _require_non_negative_int(value, name)
    if number < 1:
        raise StateLawsBm25Error(f"{name} must be >= 1")
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
        raise Bm25BoundError(f"{name}={number} exceeds physical bound {maximum}")
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
        prefix=".sl-bm25-",
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


def posting_part_relative_path(shard_id: int) -> str:
    return f"{POSTING_DATA_DIR}/part-{int(shard_id):06d}.json"


def document_part_relative_path(jurisdiction: str, part_index: int) -> str:
    code = validate_jurisdiction(jurisdiction, name="jurisdiction")
    return f"{DOCUMENT_DATA_DIR}/jurisdiction={code}/part-{int(part_index):06d}.json"


def census_region_for(jurisdiction: str) -> str:
    """Return the census region bucket for a postal code, with DC explicit."""

    code = validate_jurisdiction(jurisdiction, name="jurisdiction")
    if code == "DC":
        return "dc"
    for region, members in CENSUS_REGION_JURISDICTIONS.items():
        if region == "dc":
            continue
        if code in members:
            return region
    raise Bm25ProjectionError(f"jurisdiction {code!r} is not mapped to a census region")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldWeightConfig:
    """Declared per-field BM25 weights for state-law documents."""

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
        "notes": (
            "Legacy legal BM25 used k1=1.5 with a single unweighted term "
            "array. State laws use k1=1.2, explicit multi-field weights "
            "including jurisdiction, and the sealed legal tokenizer shared "
            "by build and query."
        ),
    }


@dataclass(frozen=True, slots=True)
class StateLawsBm25Config:
    """Stable state-law BM25 indexing and scoring configuration."""

    k1: float = DEFAULT_K1
    b: float = DEFAULT_B
    field_weights: FieldWeightConfig = field(default_factory=FieldWeightConfig)
    tokenizer: TokenizerConfig = field(default_factory=default_tokenizer_config)
    tokenizer_id: str = TOKENIZER_ID
    max_documents: int | None = DOCUMENT_COUNT_CEILING
    max_text_characters: int = MAX_TEXT_CHARACTERS
    max_query_terms: int = MAX_QUERY_TERMS
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    postings_per_cell: int = MAX_POSTING_POINTERS_PER_ROW
    max_route_page_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY
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
        if self.tokenizer.tokenizer_id != LEGAL_TOKENIZER_ID:
            raise Bm25ConfigError(
                "legal tokenizer contract must be "
                f"{LEGAL_TOKENIZER_ID!r}, got {self.tokenizer.tokenizer_id!r}"
            )
        object.__setattr__(
            self,
            "tokenizer_id",
            _require_non_empty_str(self.tokenizer_id, "tokenizer_id", maximum=128),
        )
        if self.tokenizer_id != TOKENIZER_ID:
            raise Bm25ConfigError(
                f"tokenizer_id must be the sealed state-laws tokenizer {TOKENIZER_ID!r}"
            )
        if self.max_documents is not None:
            object.__setattr__(
                self,
                "max_documents",
                _require_positive_int(self.max_documents, "max_documents"),
            )
            if self.max_documents == FORBIDDEN_DOCUMENT_CEILING:
                raise Bm25ConfigError(
                    "inherited 250000-document ceiling is forbidden"
                )
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
            "legal_tokenizer_id": LEGAL_TOKENIZER_ID,
            "legacy_parameter_delta": legacy_parameter_delta(),
            "max_documents": self.max_documents,
            "max_query_terms": self.max_query_terms,
            "max_records_in_memory": self.max_records_in_memory,
            "max_route_page_rows": self.max_route_page_rows,
            "max_rows_per_shard": self.max_rows_per_shard,
            "max_text_characters": self.max_text_characters,
            "postings_per_cell": self.postings_per_cell,
            "schema_version": self.schema_version,
            "tokenizer": self.tokenizer.to_dict(),
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_shared_by": TOKENIZER_SHARED_BY,
        }

    @property
    def digest(self) -> str:
        payload = {
            "b": self.b,
            "field_weights": self.field_weights.to_dict(),
            "k1": self.k1,
            "legal_tokenizer_id": LEGAL_TOKENIZER_ID,
            "max_documents": self.max_documents,
            "max_query_terms": self.max_query_terms,
            "max_records_in_memory": self.max_records_in_memory,
            "max_route_page_rows": self.max_route_page_rows,
            "max_rows_per_shard": self.max_rows_per_shard,
            "max_text_characters": self.max_text_characters,
            "postings_per_cell": self.postings_per_cell,
            "schema_version": self.schema_version,
            "tokenizer_digest": self.tokenizer.digest,
            "tokenizer_id": self.tokenizer_id,
        }
        return content_sha256(canonical_json_bytes(payload))


def default_bm25_config() -> StateLawsBm25Config:
    """Return the sealed production BM25 configuration."""

    return StateLawsBm25Config()


def fixture_bm25_config(**overrides: Any) -> StateLawsBm25Config:
    """Tight physical bounds for unit fixtures (still 4,096-capped)."""

    params: dict[str, Any] = {
        "max_rows_per_shard": DEFAULT_TEST_MAX_ROWS_PER_SHARD,
        "postings_per_cell": DEFAULT_TEST_POSTINGS_PER_CELL,
        "max_route_page_rows": DEFAULT_TEST_ROUTE_PAGE_ROWS,
        "max_records_in_memory": DEFAULT_TEST_MAX_RECORDS_IN_MEMORY,
    }
    params.update(overrides)
    return StateLawsBm25Config(**params)


def production_bm25_bounds() -> dict[str, Any]:
    return {
        "document_count_ceiling": DOCUMENT_COUNT_CEILING,
        "forbidden_document_ceiling": FORBIDDEN_DOCUMENT_CEILING,
        "maximum_posting_pointers_per_cell": MAX_POSTING_POINTERS_PER_ROW,
        "maximum_route_page_rows": MAX_ROWS_PER_PHYSICAL_SHARD,
        "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "sort_order_documents": DOCUMENTS_SORTED_BY,
        "sort_order_postings": POSTINGS_SORTED_BY,
        "sort_order_terms": TERMS_SORTED_BY,
    }


# ---------------------------------------------------------------------------
# Tokenizer (shared by build and query)
# ---------------------------------------------------------------------------


def tokenize_index_text(
    text: str,
    *,
    config: StateLawsBm25Config | TokenizerConfig | None = None,
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
    config: StateLawsBm25Config | TokenizerConfig | None = None,
    max_query_terms: int | None = None,
) -> tuple[str, ...]:
    """Tokenize a query with the same sealed legal tokenizer as build."""

    tokenizer = _tokenizer_from(config)
    if not isinstance(query, str):
        raise Bm25ProjectionError("query must be a string")
    limit = MAX_QUERY_TERMS if max_query_terms is None else max_query_terms
    if isinstance(config, StateLawsBm25Config):
        limit = config.max_query_terms if max_query_terms is None else max_query_terms
    limit = _require_positive_int(limit, "max_query_terms")
    if not query.strip():
        return ()
    terms = tokenize_legal_text(query, config=tokenizer).indexable_terms
    return terms[:limit]


def _tokenizer_from(
    config: StateLawsBm25Config | TokenizerConfig | None,
) -> TokenizerConfig:
    if config is None:
        return default_tokenizer_config()
    if isinstance(config, StateLawsBm25Config):
        return config.tokenizer
    if isinstance(config, TokenizerConfig):
        return config
    raise Bm25ConfigError("config must be StateLawsBm25Config or TokenizerConfig")


def shared_tokenizer_identity(
    config: StateLawsBm25Config | TokenizerConfig | None = None,
) -> dict[str, Any]:
    """Pinned tokenizer identity recorded on the index and query path."""

    tokenizer = _tokenizer_from(config)
    identity = tokenizer_identity(tokenizer)
    identity["legal_tokenizer_id"] = LEGAL_TOKENIZER_ID
    identity["shared_by"] = TOKENIZER_SHARED_BY
    identity["state_laws_tokenizer_id"] = TOKENIZER_ID
    identity["tokenizer_id"] = TOKENIZER_ID
    identity["tokenizer_version"] = TOKENIZER_VERSION
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
        if text in {"admitted"}:
            return True
    if bool(row.get("is_recovery")) or str(row.get("record_type", "")).lower() in {
        "recovery",
        "workflow",
    }:
        return False
    return True


def _retrieval_cid(row: Mapping[str, Any], *, position: int) -> str:
    for key in ("chunk_cid", "entry_cid", "record_id", "cid"):
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
        f"corpus row {position} is missing durable chunk_cid / entry_cid"
    )


def _join_sequence(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _field_text_from_row(row: Mapping[str, Any], field_name: str) -> str:
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
            "jurisdiction",
            "jurisdiction_code",
            "code_family",
            "code",
            "title",
            "chapter",
            "part",
            "article",
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
        for key in ("body", "exclusive_text", "text", "content", "section_text"):
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


def _document_sort_tuple(row: Mapping[str, Any], position: int) -> tuple[Any, ...]:
    jurisdiction = str(
        row.get("jurisdiction_code") or row.get("jurisdiction") or ""
    ).upper()
    retrieval = _retrieval_cid(row, position=position)
    chunk_index = row.get("chunk_index")
    if chunk_index is None:
        chunk_index = 0
    return (jurisdiction, int(chunk_index), retrieval)


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
    """One field-projected BM25 document for an admitted searchable chunk."""

    entry_cid: str
    document_index: int
    fields: Mapping[str, FieldTokenStream]
    chunk_cid: str
    parent_entry_cid: Optional[str] = None
    chunk_id: Optional[str] = None
    legal_id: Optional[str] = None
    jurisdiction_code: Optional[str] = None
    census_region: Optional[str] = None
    title_code: Optional[str] = None
    section: Optional[str] = None
    record_type: str = "chunk"
    filters: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "entry_cid", validate_entry_cid(self.entry_cid, name="entry_cid")
        )
        object.__setattr__(
            self, "chunk_cid", validate_entry_cid(self.chunk_cid, name="chunk_cid")
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
        if self.parent_entry_cid is not None:
            object.__setattr__(
                self,
                "parent_entry_cid",
                validate_entry_cid(self.parent_entry_cid, name="parent_entry_cid"),
            )
        if self.jurisdiction_code is not None:
            object.__setattr__(
                self,
                "jurisdiction_code",
                validate_jurisdiction(self.jurisdiction_code, name="jurisdiction_code"),
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

    def to_document_record(self) -> dict[str, Any]:
        return {
            "census_region": self.census_region,
            "chunk_cid": self.chunk_cid,
            "chunk_id": self.chunk_id,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "field_lengths": {name: self.field_length(name) for name in FIELD_ORDER},
            "filters": dict(self.filters),
            "jurisdiction_code": self.jurisdiction_code,
            "legal_id": self.legal_id,
            "parent_entry_cid": self.parent_entry_cid,
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
                    "chunk_cid": self.chunk_cid,
                    "document_index": self.document_index,
                    "entry_cid": self.entry_cid,
                    "field_tf": field_tf,
                    "term": term,
                    "tf": int(sum(field_tf.values())),
                }
            )
        leaked = POSTING_LINEAGE_FORBIDDEN_FIELDS.intersection(
            records[0] if records else {}
        )
        if leaked:
            raise Bm25CoverageError(
                f"posting records must not carry lineage fields {sorted(leaked)}"
            )
        return records


def project_legal_document(
    row: Mapping[str, Any],
    *,
    document_index: int,
    config: StateLawsBm25Config | None = None,
) -> LegalBm25Document:
    """Project one admitted searchable chunk into a multi-field BM25 document."""

    cfg = config or default_bm25_config()
    if not isinstance(cfg, StateLawsBm25Config):
        raise Bm25ConfigError("config must be a StateLawsBm25Config")
    if not isinstance(row, Mapping):
        raise Bm25ProjectionError("corpus row must be a mapping")
    if not _is_admitted_row(row):
        raise Bm25ProjectionError(
            "non-admitted rows cannot enter the BM25 index",
            code="not_admitted",
        )

    retrieval = _retrieval_cid(row, position=document_index)
    chunk_cid = row.get("chunk_cid") or retrieval
    chunk_cid = validate_entry_cid(str(chunk_cid), name="chunk_cid")
    parent = row.get("parent_entry_cid")
    if parent in (None, "", retrieval, chunk_cid):
        raw_parent = row.get("entry_cid")
        if (
            isinstance(raw_parent, str)
            and raw_parent.strip()
            and raw_parent.strip() != chunk_cid
        ):
            parent = raw_parent.strip()
        else:
            parent = None

    fields: dict[str, FieldTokenStream] = {}
    for field_name in FIELD_ORDER:
        text = _field_text_from_row(row, field_name)
        if len(text) > cfg.max_text_characters:
            raise Bm25ProjectionError(
                f"field {field_name} exceeds max_text_characters for {retrieval}"
            )
        terms = tokenize_index_text(text, config=cfg) if text else ()
        fields[field_name] = FieldTokenStream(
            field=field_name,
            text=text,
            terms=terms,
            weight=cfg.field_weights.weight_for(field_name),
        )
    if sum(stream.length for stream in fields.values()) <= 0:
        raise Bm25ProjectionError(f"document has no searchable tokens: {retrieval}")

    title_code = row.get("title")
    title_code_str = (
        str(title_code).strip() if title_code is not None and title_code != "" else None
    )
    section = row.get("section")
    section_str = (
        str(section).strip() if section is not None and section != "" else None
    )
    legal_id = _optional_str(row.get("legal_id") or row.get("parent_legal_id"), "legal_id", maximum=256)
    chunk_id = _optional_str(row.get("chunk_id"), "chunk_id", maximum=256)
    jurisdiction = _optional_str(
        row.get("jurisdiction_code") or row.get("jurisdiction"),
        "jurisdiction_code",
        maximum=16,
    )
    if jurisdiction is not None:
        jurisdiction = validate_jurisdiction(jurisdiction, name="jurisdiction_code")
    region = census_region_for(jurisdiction) if jurisdiction else None

    filters: dict[str, str] = {}
    if jurisdiction:
        filters["jurisdiction"] = jurisdiction
    if region:
        filters["census_region"] = region
    if title_code_str:
        filters["title"] = title_code_str
    if section_str:
        filters["section"] = section_str
    if legal_id:
        filters["legal_id"] = legal_id

    return LegalBm25Document(
        entry_cid=chunk_cid,
        document_index=document_index,
        fields=fields,
        chunk_cid=chunk_cid,
        parent_entry_cid=parent,
        chunk_id=chunk_id,
        legal_id=legal_id,
        jurisdiction_code=jurisdiction,
        census_region=region,
        title_code=title_code_str,
        section=section_str,
        record_type=str(row.get("record_type") or "chunk"),
        filters=filters,
    )


def iter_projected_documents(
    rows: Iterable[Mapping[str, Any]],
    *,
    config: StateLawsBm25Config | None = None,
) -> Iterator[LegalBm25Document]:
    """Stream admitted searchable chunks into BM25 documents."""

    cfg = config or default_bm25_config()
    if isinstance(rows, (str, bytes, bytearray)):
        raise Bm25ProjectionError("corpus rows must be an iterable of mappings")
    admitted_rows = [row for row in rows if _is_admitted_row(row)]
    admitted_rows.sort(key=lambda row: _document_sort_tuple(row, 0))
    seen: set[str] = set()
    for position, row in enumerate(admitted_rows):
        document = project_legal_document(row, document_index=position, config=cfg)
        if document.entry_cid in seen or document.chunk_cid in seen:
            raise Bm25CoverageError(
                f"duplicate chunk_cid among BM25 documents: {document.chunk_cid}"
            )
        seen.add(document.entry_cid)
        seen.add(document.chunk_cid)
        if cfg.max_documents is not None and position + 1 > cfg.max_documents:
            raise Bm25CoverageError(
                f"document count {position + 1} exceeds configured ceiling "
                f"{cfg.max_documents}"
            )
        yield document
    if not seen:
        raise Bm25CoverageError("no admitted corpus rows produced BM25 documents")


def project_admitted_documents(
    rows: Iterable[Mapping[str, Any]],
    *,
    config: StateLawsBm25Config | None = None,
) -> tuple[LegalBm25Document, ...]:
    """Materialize the admitted projection."""

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
    chunk_cid: Optional[str] = None

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
        if self.chunk_cid is not None:
            object.__setattr__(
                self, "chunk_cid", validate_entry_cid(self.chunk_cid, name="chunk_cid")
            )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "chunk_cid": self.chunk_cid or self.entry_cid,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "field_tf": dict(self.field_tf),
            "tf": self.tf,
        }
        leaked = POSTING_LINEAGE_FORBIDDEN_FIELDS.intersection(payload)
        if leaked:
            raise Bm25CoverageError(
                f"posting pointer carries lineage fields {sorted(leaked)}"
            )
        return payload


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
                chunk_cid=str(item.get("chunk_cid") or item["entry_cid"]),
            )
        )
    if not resolved:
        raise Bm25CoverageError("cannot split an empty posting pointer list")
    cells: list[PostingCell] = []
    for offset in range(0, len(resolved), bound):
        chunk = tuple(resolved[offset : offset + bound])
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
    """At most 4,096 document rows in one jurisdiction part."""

    shard_id: int
    documents: tuple[dict[str, Any], ...]
    relative_path: str
    sha256: str
    size_bytes: int
    jurisdiction_code: str
    part_index: int

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
        object.__setattr__(
            self, "part_index", _require_non_negative_int(self.part_index, "part_index")
        )
        object.__setattr__(
            self,
            "jurisdiction_code",
            validate_jurisdiction(self.jurisdiction_code, name="jurisdiction_code"),
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
            metadata={"jurisdiction": self.jurisdiction_code},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_document_index": self.first_document_index,
            "first_key": self.first_key,
            "jurisdiction_code": self.jurisdiction_code,
            "last_document_index": self.last_document_index,
            "last_key": self.last_key,
            "part_index": self.part_index,
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
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for item in records:
        payload = dict(item)
        jurisdiction = str(payload.get("jurisdiction_code") or "")
        if not jurisdiction:
            raise Bm25CoverageError("document record missing jurisdiction_code")
        if jurisdiction not in groups:
            groups[jurisdiction] = []
            order.append(jurisdiction)
        groups[jurisdiction].append(payload)

    shards: list[DocumentShard] = []
    shard_id = 0
    for jurisdiction in order:
        rows = groups[jurisdiction]
        indexes = [int(item["document_index"]) for item in rows]
        if indexes != sorted(indexes):
            raise Bm25CoverageError(
                "document partition is not sorted by document_index"
            )
        for part_index, start in enumerate(range(0, len(rows), bound)):
            part = rows[start : start + bound]
            payload = {
                "documents": part,
                "jurisdiction_code": jurisdiction,
                "schema_version": SCHEMA_VERSION,
                "shard_id": shard_id,
            }
            digest, size = _shard_payload_digest(payload)
            shards.append(
                DocumentShard(
                    shard_id=shard_id,
                    documents=tuple(part),
                    relative_path=document_part_relative_path(jurisdiction, part_index),
                    sha256=digest,
                    size_bytes=size,
                    jurisdiction_code=jurisdiction,
                    part_index=part_index,
                )
            )
            shard_id += 1
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
                relative_path=posting_part_relative_path(shard_id),
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
        raise StateLawsBm25Error("document external sort interrupted before merge")
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
    """Externally sort posting records by ``(term, chunk_cid/entry_cid)``."""

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
        raise StateLawsBm25Error("posting external sort interrupted before merge")
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
        raise StateLawsBm25Error("term external sort interrupted before merge")
    ordered = list(iter_jsonl(output))
    for previous, current in zip(ordered, ordered[1:]):
        if term_sort_key(current) < term_sort_key(previous):
            raise Bm25CoverageError("term stream is not lexicographically sorted")
    return ordered, _sort_receipt_summary(receipt)


def robertson_sparck_jones_idf(document_frequency: int, document_count: int) -> float:
    """Robertson-Sparck-Jones IDF with a floor at zero."""

    df = _require_non_negative_int(document_frequency, "document_frequency")
    n_docs = _require_positive_int(document_count, "document_count")
    if df <= 0:
        return 0.0
    raw = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
    return max(0.0, float(raw))


def group_sorted_postings(
    postings: Sequence[Mapping[str, Any]],
    *,
    document_count: int,
    postings_per_cell: int,
) -> list[TermPosting]:
    """Collapse a ``(term, chunk_cid)``-sorted stream into term rows."""

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
        terms.append(
            TermPosting(
                term=term,
                document_frequency=df,
                idf=robertson_sparck_jones_idf(df, n_docs),
                cells=cells,
            )
        )
    return terms


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
    chunk_cid: Optional[str] = None
    legal_id: Optional[str] = None
    jurisdiction_code: Optional[str] = None
    census_region: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "census_region": self.census_region,
            "chunk_cid": self.chunk_cid or self.entry_cid,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "explanations": [item.to_dict() for item in self.explanations],
            "filters": dict(self.filters),
            "jurisdiction_code": self.jurisdiction_code,
            "legal_id": self.legal_id,
            "matched_terms": list(self.matched_terms),
            "score": self.score,
        }


def reference_field_term_score(
    *,
    tf: int,
    idf: float,
    field_length: int,
    average_field_length: float,
    k1: float,
    b: float,
    field_weight: float,
) -> float:
    """Shared-layout reference BM25 contribution for one field/term."""

    return bm25_term_score(
        tf=float(tf),
        idf=float(idf),
        doc_length=float(field_length),
        avg_doc_length=max(float(average_field_length), 1e-12),
        k1=float(k1),
        b=float(b),
        field_weight=float(field_weight),
    )


@dataclass(frozen=True, slots=True)
class StateLawsBm25Index:
    """Field-weighted term-range BM25 index bound to admitted state-law chunks."""

    documents: tuple[LegalBm25Document, ...]
    document_records: tuple[dict[str, Any], ...]
    document_shards: tuple[DocumentShard, ...]
    term_shards: tuple[TermRangeShard, ...]
    document_routes: HierarchicalRouteIndex
    term_routes: HierarchicalRouteIndex
    config: StateLawsBm25Config
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
            MappingProxyType(
                {key: dict(value) for key, value in self.sort_receipts.items()}
            ),
        )
        assert_shards_bounded(self)

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
        return self.config.tokenizer_id

    def document_by_cid(self, entry_cid: str) -> LegalBm25Document:
        for document in self.documents:
            if document.entry_cid == entry_cid or document.chunk_cid == entry_cid:
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
            score = reference_field_term_score(
                tf=tf,
                idf=idf,
                field_length=stream.length,
                average_field_length=avg_field_len,
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
        """Score documents for *query* via term-range routing."""

        return self._search(query, top_k=top_k, filters=filters, routed=True)

    def search_unsharded(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: Mapping[str, str] | None = None,
    ) -> list[Bm25Hit]:
        """Score every document without term-range pruning (differential)."""

        return self._search(query, top_k=top_k, filters=filters, routed=False)

    def _search(
        self,
        query: str,
        *,
        top_k: int,
        filters: Mapping[str, str] | None,
        routed: bool,
    ) -> list[Bm25Hit]:
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

        if routed:
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
        else:
            for document in self.documents:
                if active_filters and not _document_matches_filters(
                    document, active_filters
                ):
                    continue
                score, terms_hit, expl = self.score_document(document, query_terms)
                if score <= 0.0:
                    continue
                scores[document.entry_cid] = score
                matched[document.entry_cid] = list(terms_hit)
                explanations[document.entry_cid] = list(expl)

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
                    chunk_cid=document.chunk_cid,
                    legal_id=document.legal_id,
                    jurisdiction_code=document.jurisdiction_code,
                    census_region=document.census_region,
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
            if key in {"jurisdiction", "jurisdiction_code"}:
                actual = document.jurisdiction_code
            elif key in {"census_region", "region"}:
                actual = document.census_region
            elif key == "title":
                actual = document.title_code
            elif key == "section":
                actual = document.section
            elif key == "legal_id":
                actual = document.legal_id
            elif key in {"entry_cid", "chunk_cid"}:
                actual = document.chunk_cid
        if actual is None or str(actual) != str(expected):
            return False
    return True


def assert_shards_bounded(index: StateLawsBm25Index) -> None:
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


def assert_externally_sorted(index: StateLawsBm25Index) -> None:
    """Fail closed when documents or terms were not externally sorted."""

    for label in ("documents", "terms", "postings"):
        receipt = index.sort_receipts.get(label) or {}
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


def assert_boundary_terms_route_once(index: StateLawsBm25Index) -> None:
    """Fail closed when a boundary term is covered by more than one shard."""

    for shard in index.term_shards:
        for term in (shard.first_term, shard.last_term):
            covering = [item for item in index.term_shards if item.covers(term)]
            if len(covering) != 1:
                raise Bm25CoverageError(
                    f"boundary term {term!r} routes to {len(covering)} shards"
                )
            routed = index.route_term_shard(term)
            if routed is None or routed.shard_id != covering[0].shard_id:
                raise Bm25CoverageError(
                    f"boundary term {term!r} did not route to its unique shard"
                )


def assert_postings_reconcile(index: StateLawsBm25Index) -> None:
    """Fail closed when posting pointers diverge from document term streams."""

    expected: dict[str, set[str]] = defaultdict(set)
    for document in index.documents:
        for term in document.all_terms():
            expected[term].add(document.entry_cid)
    observed: dict[str, set[str]] = defaultdict(set)
    pointer_total = 0
    for shard in index.term_shards:
        for posting in shard.terms:
            for cell in posting.cells:
                for pointer in cell.pointers:
                    observed[posting.term].add(pointer.entry_cid)
                    pointer_total += 1
            if posting.pointer_count != posting.document_frequency:
                raise Bm25CoverageError(
                    f"term {posting.term!r} pointer/df mismatch"
                )
    if set(expected) != set(observed):
        missing = sorted(set(expected) - set(observed))[:8]
        extra = sorted(set(observed) - set(expected))[:8]
        raise Bm25CoverageError(
            f"posting terms do not reconcile; missing={missing!r} extra={extra!r}"
        )
    for term, cids in expected.items():
        if observed[term] != cids:
            raise Bm25CoverageError(f"posting pointers for {term!r} do not reconcile")
    if pointer_total != index.posting_count:
        raise Bm25CoverageError(
            f"posting_count {index.posting_count} != pointer total {pointer_total}"
        )


def assert_scores_match_reference(
    index: StateLawsBm25Index,
    *,
    sample_terms: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Compare index explanations against the shared reference BM25 formula."""

    fixtures: list[dict[str, Any]] = []
    wanted = set(sample_terms) if sample_terms is not None else None
    seen: set[tuple[str, str]] = set()
    for document in index.documents:
        for term in document.all_terms():
            if wanted is not None and term not in wanted:
                continue
            key = (document.entry_cid, term)
            if key in seen:
                continue
            seen.add(key)
            explanation = index.explain_term(document, term)
            expected_total = 0.0
            for contribution in explanation.field_contributions:
                reference = reference_field_term_score(
                    tf=contribution.tf,
                    idf=explanation.idf,
                    field_length=contribution.field_length,
                    average_field_length=float(
                        index.average_field_lengths.get(
                            contribution.field, index.average_document_length
                        )
                    ),
                    k1=index.config.k1,
                    b=index.config.b,
                    field_weight=contribution.weight,
                )
                if not math.isclose(
                    contribution.score, reference, rel_tol=0.0, abs_tol=SCORE_ABS_TOLERANCE
                ):
                    raise Bm25ScoreError(
                        f"field score mismatch for {term!r} on {document.chunk_cid}"
                    )
                expected_total += reference
            if not math.isclose(
                explanation.total_score,
                expected_total,
                rel_tol=0.0,
                abs_tol=SCORE_ABS_TOLERANCE,
            ):
                raise Bm25ScoreError(
                    f"term score mismatch for {term!r} on {document.chunk_cid}"
                )
            if len(fixtures) < 12:
                fixtures.append(
                    {
                        "chunk_cid": document.chunk_cid,
                        "idf": explanation.idf,
                        "jurisdiction_code": document.jurisdiction_code,
                        "reference_score": expected_total,
                        "score": explanation.total_score,
                        "term": term,
                    }
                )
            if wanted is None and len(fixtures) >= 12:
                return fixtures
    if not fixtures:
        raise Bm25ScoreError("no differential scoring fixtures were produced")
    return fixtures


def assert_no_posting_lineage(index: StateLawsBm25Index) -> None:
    """Fail closed when posting cells duplicate source-level lineage."""

    for shard in index.term_shards:
        for term in shard.terms:
            payload = term.to_dict()
            leaked = POSTING_LINEAGE_FORBIDDEN_FIELDS.intersection(payload)
            if leaked:
                raise Bm25CoverageError(
                    f"term {term.term!r} carries lineage fields {sorted(leaked)}"
                )
            for cell in term.cells:
                for pointer in cell.pointers:
                    leaked = POSTING_LINEAGE_FORBIDDEN_FIELDS.intersection(
                        pointer.to_dict()
                    )
                    if leaked:
                        raise Bm25CoverageError(
                            f"posting pointer carries lineage fields {sorted(leaked)}"
                        )


def score_maps_match(
    left: Sequence[Bm25Hit],
    right: Sequence[Bm25Hit],
    *,
    tolerance: float = SCORE_ABS_TOLERANCE,
) -> tuple[bool, float, int]:
    """Compare full score maps for absolute parity."""

    left_map = {hit.entry_cid: hit.score for hit in left}
    right_map = {hit.entry_cid: hit.score for hit in right}
    keys = set(left_map) | set(right_map)
    max_delta = 0.0
    mismatches = 0
    for key in keys:
        a = float(left_map.get(key, 0.0))
        b = float(right_map.get(key, 0.0))
        delta = abs(a - b)
        if delta > max_delta:
            max_delta = delta
        if not math.isclose(a, b, rel_tol=0.0, abs_tol=tolerance):
            mismatches += 1
    return mismatches == 0, max_delta, mismatches


# ---------------------------------------------------------------------------
# Roots / coverage
# ---------------------------------------------------------------------------


def build_corpus_root_cid(rows: Iterable[Mapping[str, Any]]) -> str:
    """Content-address admitted chunk identities (no full text payload)."""

    admitted: list[dict[str, Any]] = []
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise Bm25ProjectionError(f"corpus row {position} must be a mapping")
        if not _is_admitted_row(row):
            continue
        retrieval = _retrieval_cid(row, position=position)
        admitted.append(
            {
                "chunk_cid": row.get("chunk_cid") or retrieval,
                "chunk_id": row.get("chunk_id"),
                "jurisdiction": row.get("jurisdiction_code") or row.get("jurisdiction"),
                "legal_id": row.get("legal_id") or row.get("parent_legal_id"),
                "parent_entry_cid": row.get("parent_entry_cid"),
            }
        )
    admitted.sort(key=lambda item: str(item["chunk_cid"]))
    return content_cid(
        {
            "admitted_count": len(admitted),
            "identities": admitted,
            "primary_key": PRIMARY_KEY,
            "schema_version": "state-laws-corpus-root/v1",
        }
    )


def build_index_root_cid(
    documents: Sequence[LegalBm25Document],
    *,
    config: StateLawsBm25Config,
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
                "chunk_cid": doc.chunk_cid,
                "document_index": doc.document_index,
                "field_lengths": {
                    name: doc.field_length(name) for name in FIELD_ORDER
                },
                "jurisdiction_code": doc.jurisdiction_code,
                "legal_id": doc.legal_id,
                "total_length": doc.total_length,
            }
            for doc in documents
        ],
        "schema_version": SCHEMA_VERSION,
        "term_shards": [shard.to_dict() for shard in term_shards],
        "tokenizer_id": config.tokenizer_id,
    }
    return content_cid(structural)


def assert_every_admitted_chunk_has_document(
    rows: Iterable[Mapping[str, Any]],
    index: StateLawsBm25Index,
) -> None:
    """Fail closed when admitted searchable chunks and BM25 documents diverge."""

    admitted_ids: list[str] = []
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise Bm25CoverageError(f"corpus row {position} must be a mapping")
        if not _is_admitted_row(row):
            continue
        admitted_ids.append(_retrieval_cid(row, position=position))
    index_ids = [doc.chunk_cid for doc in index.documents]
    if sorted(admitted_ids) != sorted(index_ids):
        missing = sorted(set(admitted_ids) - set(index_ids))
        extra = sorted(set(index_ids) - set(admitted_ids))
        raise Bm25CoverageError(
            "BM25 documents do not match admitted searchable chunks; "
            f"missing={missing[:5]!r} extra={extra[:5]!r}"
        )
    if len(index_ids) != len(set(index_ids)):
        raise Bm25CoverageError("BM25 documents contain duplicate chunk_cid values")


def assert_row_conservation(
    rows: Iterable[Mapping[str, Any]],
    index: StateLawsBm25Index,
) -> dict[str, Any]:
    """Prove document/posting counts equal the admitted chunk projection."""

    materialized = list(rows)
    admitted = [row for row in materialized if _is_admitted_row(row)]
    assert_every_admitted_chunk_has_document(materialized, index)
    assert_postings_reconcile(index)
    if index.document_count != len(admitted):
        raise Bm25CoverageError(
            f"row conservation failed: documents={index.document_count} "
            f"admitted={len(admitted)}"
        )
    return {
        "admitted_count": len(admitted),
        "document_count": index.document_count,
        "posting_count": index.posting_count,
        "conserved": True,
    }


def reconcile_roots(
    index: StateLawsBm25Index,
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


def build_state_laws_bm25_index(
    source: Iterable[Mapping[str, Any]],
    *,
    config: StateLawsBm25Config | None = None,
    corpus_root_cid: str | None = None,
    work_dir: PathLike | None = None,
) -> StateLawsBm25Index:
    """Build the field-weighted term-range BM25 index over admitted chunks."""

    cfg = config or default_bm25_config()
    if not isinstance(cfg, StateLawsBm25Config):
        raise Bm25ConfigError("config must be a StateLawsBm25Config")

    materialized_rows = list(source)
    documents = project_admitted_documents(materialized_rows, config=cfg)
    by_cid = {document.entry_cid: document for document in documents}

    own_temp = work_dir is None
    work = Path(work_dir) if work_dir is not None else Path(
        tempfile.mkdtemp(prefix="sl-bm25-")
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
        streamed = list(
            stream_bounded_partitions(
                document_records, max_rows=cfg.max_rows_per_shard
            )
        )
        if sum(len(part) for part in streamed) != len(document_records):
            raise Bm25BoundError("document partition count does not match records")

        n_docs = len(ordered_documents)
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
        ordered_terms = [
            terms_by_name[str(item["term"])] for item in sorted_term_payloads
        ]
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
            try:
                import shutil

                shutil.rmtree(work, ignore_errors=True)
            except OSError:
                pass

    root = corpus_root_cid or build_corpus_root_cid(materialized_rows)
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
    index = StateLawsBm25Index(
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
    assert_row_conservation(materialized_rows, index)
    assert_externally_sorted(index)
    assert_boundary_terms_route_once(index)
    assert_no_posting_lineage(index)
    assert_scores_match_reference(index)
    return index


# ---------------------------------------------------------------------------
# Fixture recipe (compact; no bulk golden dumps)
# ---------------------------------------------------------------------------


def _cid(nibble: str) -> str:
    text = nibble.lower()
    if len(text) == 1 and all(ch in "0123456789abcdef" for ch in text):
        return f"sha256:{text * 64}"
    return f"sha256:{content_sha256(text)}"


def fixture_bm25_chunks() -> list[dict[str, Any]]:
    """Compact admitted chunks spanning all census regions and DC."""

    return [
        {
            "chunk_cid": _cid("3"),
            "parent_entry_cid": _cid("4"),
            "entry_cid": _cid("4"),
            "chunk_id": "tx:552:001#chunk=0000",
            "chunk_index": 0,
            "legal_id": "sl:tx:552:001",
            "jurisdiction_code": "TX",
            "jurisdiction_name": "Texas",
            "title": "552",
            "title_name": "Public Information",
            "chapter": "552",
            "section": "001",
            "heading": "Policy; construction",
            "citation": "TX 552 § 001",
            "body": (
                "Under the fundamental philosophy of representative government, "
                "each person is entitled to complete information about the "
                "affairs of government. Unique token texaspublicinfo. The "
                "statute declares a public information policy."
            ),
            "note": "Texas public information statute.",
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("a"),
            "parent_entry_cid": _cid("b"),
            "entry_cid": _cid("b"),
            "chunk_id": "or:174:010#chunk=0000",
            "chunk_index": 0,
            "legal_id": "sl:or:174:010",
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
                "simply to ascertain and declare what is contained therein. "
                "Unique token oregonconstruction. The statute is a public "
                "records construction rule."
            ),
            "note": "Oregon statute construction.",
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("e"),
            "parent_entry_cid": _cid("0"),
            "entry_cid": _cid("0"),
            "chunk_id": "dc:2:531#chunk=0000",
            "chunk_index": 0,
            "legal_id": "sl:dc:2:531",
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
                "Unique token dcopenmeetings. The statute requires notice "
                "and is a public records open-meetings law."
            ),
            "note": "District of Columbia open meetings.",
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("1"),
            "parent_entry_cid": _cid("2"),
            "entry_cid": _cid("2"),
            "chunk_id": "ny:5:86#chunk=0000",
            "chunk_index": 0,
            "legal_id": "sl:ny:5:86",
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
            "note": "New York FOIL definitions.",
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("c"),
            "parent_entry_cid": _cid("d"),
            "entry_cid": _cid("d"),
            "chunk_id": "ca:1:1#chunk=0000",
            "chunk_index": 0,
            "legal_id": "sl:ca:1:1",
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
                "governs civil obligations and public records construction."
            ),
            "note": "California civil code title.",
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("5"),
            "parent_entry_cid": _cid("6"),
            "entry_cid": _cid("6"),
            "chunk_id": "il:5:140:1#chunk=0000",
            "chunk_index": 0,
            "legal_id": "sl:il:5:140:1",
            "jurisdiction_code": "IL",
            "jurisdiction_name": "Illinois",
            "title": "5",
            "title_name": "General Provisions",
            "chapter": "140",
            "section": "1",
            "heading": "Public policy",
            "citation": "IL 5 ILCS 140/1",
            "body": (
                "It is declared to be the public policy of the State of "
                "Illinois that all persons are entitled to full and complete "
                "information. Unique token illinoisfia. The statute is a "
                "public records law."
            ),
            "note": "Illinois Freedom of Information Act.",
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("7"),
            "parent_entry_cid": _cid("8"),
            "entry_cid": _cid("8"),
            "chunk_id": "fl:119:01#chunk=0000",
            "chunk_index": 0,
            "legal_id": "sl:fl:119:01",
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
            "note": "Florida Sunshine Law.",
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("9"),
            "parent_entry_cid": _cid("aa"),
            "entry_cid": _cid("aa"),
            "chunk_id": "wa:42:56:030#chunk=0000",
            "chunk_index": 0,
            "legal_id": "sl:wa:42:56:030",
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
            "note": "Washington Public Records Act.",
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("bb"),
            "parent_entry_cid": _cid("cc"),
            "entry_cid": _cid("cc"),
            "chunk_id": "ma:66:10#chunk=0000",
            "chunk_index": 0,
            "legal_id": "sl:ma:66:10",
            "jurisdiction_code": "MA",
            "jurisdiction_name": "Massachusetts",
            "title": "66",
            "title_name": "Public Records",
            "chapter": "66",
            "section": "10",
            "heading": "Public inspection and copies of records",
            "citation": "MA 66 § 10",
            "body": (
                "Every person having custody of any public record shall, at "
                "reasonable times, permit it to be inspected. Unique token "
                "masspublicrecords. The statute is a public records law."
            ),
            "note": "Massachusetts public records.",
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("dd"),
            "parent_entry_cid": _cid("ee"),
            "entry_cid": _cid("ee"),
            "chunk_id": "oh:149:43#chunk=0000",
            "chunk_index": 0,
            "legal_id": "sl:oh:149:43",
            "jurisdiction_code": "OH",
            "jurisdiction_name": "Ohio",
            "title": "149",
            "title_name": "Documents, Reports, and Records",
            "chapter": "149",
            "section": "43",
            "heading": "Availability of public records for inspection",
            "citation": "OH 149 § 43",
            "body": (
                "Upon request, all public records responsive to the request "
                "shall be promptly prepared and made available. Unique token "
                "ohiopublicrecords. The statute is a public records law."
            ),
            "note": "Ohio public records.",
            "disposition": "admitted",
        },
        {
            "entry_cid": "",
            "chunk_cid": "",
            "row_id": "recovery-src-01",
            "disposition": "quarantined",
            "is_recovery": True,
            "body": "workflow recovery payload must not enter BM25",
        },
        {
            "chunk_cid": _cid("f"),
            "entry_cid": _cid("f"),
            "disposition": "excluded",
            "body": "excluded incomplete provenance row",
            "title": "99",
            "section": "999",
            "jurisdiction_code": "PR",
        },
    ]


def fixture_sample_queries() -> tuple[dict[str, Any], ...]:
    """Citation and unique-token queries covering all regions and DC."""

    return (
        {
            "query_id": "citation-northeast-ny",
            "query_text": "NY 5 § 86",
            "kind": "citation",
            "region": "northeast",
            "jurisdiction": "NY",
            "expected_chunk_cid": _cid("1"),
            "expected_unique_token": "newyorkfoil",
        },
        {
            "query_id": "sample-northeast-ma",
            "query_text": "masspublicrecords",
            "kind": "sample",
            "region": "northeast",
            "jurisdiction": "MA",
            "expected_chunk_cid": _cid("bb"),
            "expected_unique_token": "masspublicrecords",
        },
        {
            "query_id": "citation-midwest-il",
            "query_text": "IL 5 ILCS 140/1",
            "kind": "citation",
            "region": "midwest",
            "jurisdiction": "IL",
            "expected_chunk_cid": _cid("5"),
            "expected_unique_token": "illinoisfia",
        },
        {
            "query_id": "sample-midwest-oh",
            "query_text": "ohiopublicrecords",
            "kind": "sample",
            "region": "midwest",
            "jurisdiction": "OH",
            "expected_chunk_cid": _cid("dd"),
            "expected_unique_token": "ohiopublicrecords",
        },
        {
            "query_id": "citation-south-tx",
            "query_text": "TX 552 § 001",
            "kind": "citation",
            "region": "south",
            "jurisdiction": "TX",
            "expected_chunk_cid": _cid("3"),
            "expected_unique_token": "texaspublicinfo",
        },
        {
            "query_id": "sample-south-fl",
            "query_text": "floridasunshine",
            "kind": "sample",
            "region": "south",
            "jurisdiction": "FL",
            "expected_chunk_cid": _cid("7"),
            "expected_unique_token": "floridasunshine",
        },
        {
            "query_id": "citation-west-or",
            "query_text": "OR 174 § 010",
            "kind": "citation",
            "region": "west",
            "jurisdiction": "OR",
            "expected_chunk_cid": _cid("a"),
            "expected_unique_token": "oregonconstruction",
        },
        {
            "query_id": "sample-west-ca",
            "query_text": "californiaevidence",
            "kind": "sample",
            "region": "west",
            "jurisdiction": "CA",
            "expected_chunk_cid": _cid("c"),
            "expected_unique_token": "californiaevidence",
        },
        {
            "query_id": "citation-dc",
            "query_text": "DC 2 § 531",
            "kind": "citation",
            "region": "dc",
            "jurisdiction": "DC",
            "expected_chunk_cid": _cid("e"),
            "expected_unique_token": "dcopenmeetings",
        },
        {
            "query_id": "sample-dc",
            "query_text": "dcopenmeetings",
            "kind": "sample",
            "region": "dc",
            "jurisdiction": "DC",
            "expected_chunk_cid": _cid("e"),
            "expected_unique_token": "dcopenmeetings",
        },
    )


def bind_fixture_bm25(
    chunks: Sequence[Mapping[str, Any]] | None = None,
    **overrides: Any,
) -> StateLawsBm25Index:
    """Bind the compact fixture recipe with tight physical test bounds."""

    rows = list(chunks) if chunks is not None else fixture_bm25_chunks()
    config = overrides.pop("config", None) or fixture_bm25_config(**overrides)
    work_dir = overrides.pop("work_dir", None)
    corpus_root = overrides.pop("corpus_root_cid", None)
    return build_state_laws_bm25_index(
        rows,
        config=config,
        corpus_root_cid=corpus_root,
        work_dir=work_dir,
    )


def evaluate_sample_queries(
    index: StateLawsBm25Index,
    *,
    queries: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run sealed sample/citation queries and prove region/DC coverage."""

    selected = list(queries) if queries is not None else list(fixture_sample_queries())
    if not selected:
        raise Bm25EvaluationError("sample query set is empty")
    regions = {str(item.get("region") or "") for item in selected}
    missing_regions = [name for name in REQUIRED_QUERY_REGIONS if name not in regions]
    if missing_regions:
        raise Bm25EvaluationError(
            f"sample queries must span all regions/DC; missing={missing_regions!r}"
        )

    traces: list[dict[str, Any]] = []
    max_delta = 0.0
    mismatches = 0
    for query in selected:
        text = str(query.get("query_text") or "").strip()
        if not text:
            raise Bm25EvaluationError(f"query {query.get('query_id')!r} has empty text")
        expected_cid = str(query.get("expected_chunk_cid") or "")
        routed = index.search(text, top_k=max(index.document_count, 1))
        unsharded = index.search_unsharded(text, top_k=max(index.document_count, 1))
        ok, delta, count = score_maps_match(unsharded, routed)
        max_delta = max(max_delta, delta)
        mismatches += count
        if not routed:
            raise Bm25EvaluationError(f"query {query.get('query_id')!r} returned no hits")
        top = routed[0]
        if expected_cid and top.chunk_cid != expected_cid:
            raise Bm25EvaluationError(
                f"query {query.get('query_id')!r} ranked {top.chunk_cid!r} "
                f"ahead of expected {expected_cid!r}"
            )
        if str(query.get("jurisdiction")) and top.jurisdiction_code != query.get(
            "jurisdiction"
        ):
            raise Bm25EvaluationError(
                f"query {query.get('query_id')!r} did not land in "
                f"{query.get('jurisdiction')!r}"
            )
        traces.append(
            {
                "expected_chunk_cid": expected_cid,
                "jurisdiction": query.get("jurisdiction"),
                "kind": query.get("kind"),
                "query_id": query.get("query_id"),
                "query_text": text,
                "region": query.get("region"),
                "score_delta": delta,
                "top_chunk_cid": top.chunk_cid,
                "top_score": top.score,
            }
        )
        if not ok:
            raise Bm25ScoreError(
                f"routed/unsharded score mismatch for {query.get('query_id')!r}"
            )
    return {
        "max_score_delta": max_delta,
        "parity_within_tolerance": mismatches == 0 and max_delta <= SCORE_ABS_TOLERANCE,
        "query_count": len(selected),
        "regions_covered": sorted(regions),
        "score_mismatch_count": mismatches,
        "spans_all_regions_and_dc": missing_regions == [],
        "traces": traces,
    }


# ---------------------------------------------------------------------------
# Evaluation report
# ---------------------------------------------------------------------------


def default_bm25_report_path(repo_root: PathLike | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    return (root / REPORT_RELATIVE_PATH).resolve()


def _acceptance_block() -> dict[str, Any]:
    return {
        "boundary_terms_route_once": True,
        "criteria": (
            "Row conservation and exact scoring pass; every admitted chunk "
            "has a document record, posting routes are lexicographic, each "
            "cell/page is at most 4096, and sample/citation queries span all "
            "regions/DC."
        ),
        "documents_equal_admitted_searchable_chunks": True,
        "exact_scoring_parity_within_tolerance": True,
        "hub_upload": False,
        "physical_bounds_hold": True,
        "posting_routes_lexicographic": True,
        "postings_reconcile": True,
        "row_conservation": True,
        "sample_queries_span_all_regions_and_dc": True,
        "scores_match_reference_bm25": True,
        "secrets_absent": True,
    }


def build_bm25_evaluation_report(
    *,
    index: StateLawsBm25Index | None = None,
    rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the sealed, secret-free LCR-027 BM25 evaluation receipt."""

    source_rows = list(rows) if rows is not None else fixture_bm25_chunks()
    demo = index if index is not None else bind_fixture_bm25(source_rows)
    conservation = assert_row_conservation(source_rows, demo)
    query = "public records statute"
    query_terms = tokenize_query(query, config=demo.config)
    build_terms = tokenize_index_text(query, config=demo.config)
    hits = demo.search(query, top_k=5)
    sample = evaluate_sample_queries(demo)
    fixtures = assert_scores_match_reference(
        demo,
        sample_terms=[
            "oregonconstruction",
            "dcopenmeetings",
            "newyorkfoil",
            "texaspublicinfo",
            "illinoisfia",
        ],
    )
    max_doc_rows = max(shard.row_count for shard in demo.document_shards)
    max_term_rows = max(shard.row_count for shard in demo.term_shards)
    max_cell = max(
        (
            cell.pointer_count
            for shard in demo.term_shards
            for term in shard.terms
            for cell in term.cells
        ),
        default=0,
    )
    max_route = max(
        max((len(page) for page in demo.document_routes.pages), default=0),
        max((len(page) for page in demo.term_routes.pages), default=0),
    )
    jurisdictions = sorted(
        {
            doc.jurisdiction_code
            for doc in demo.documents
            if doc.jurisdiction_code
        }
    )
    regions = sorted(
        {doc.census_region for doc in demo.documents if doc.census_region}
    )
    payload: dict[str, Any] = {
        "acceptance": _acceptance_block(),
        "adr_path": ADR_PATH,
        "admitted": {
            "chunk_count": conservation["admitted_count"],
            "document_count": demo.document_count,
            "index_root_cid": demo.index_root_cid,
            "posting_count": demo.posting_count,
            "term_count": demo.term_count,
            "term_shard_count": demo.term_shard_count,
        },
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "authorizing_for_release": False,
        "board_namespace": BOARD_NAMESPACE,
        "bounds": production_bm25_bounds(),
        "bundle": BUNDLE,
        "checks": {
            "admitted_chunk_count": conservation["admitted_count"],
            "admitted_documents_equal_chunks": demo.document_count
            == conservation["admitted_count"],
            "boundary_terms_route_once": True,
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
            "hierarchical_term_routes_present": demo.term_routes.page_count >= 1,
            "legal_tokenizer_id": LEGAL_TOKENIZER_ID,
            "no_document_count_ceiling": demo.config.max_documents is None,
            "no_hub_upload": True,
            "posting_routes_lexicographic": True,
            "postings_externally_sorted": bool(
                (demo.sort_receipts.get("postings") or {}).get("externally_sorted")
            ),
            "production_max_posting_pointers": MAX_POSTING_POINTERS_PER_ROW,
            "production_max_rows_per_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "query_uses_legal_tokenizer": True,
            "recovery_excluded_from_bm25": True,
            "row_conservation": True,
            "sample_queries_span_all_regions_and_dc": sample["spans_all_regions_and_dc"],
            "scores_match_reference_bm25": True,
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
        },
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "demo": {
            "average_document_length": demo.average_document_length,
            "census_regions": regions,
            "chunk_cids": [doc.chunk_cid for doc in demo.documents],
            "config_digest": demo.config.digest,
            "corpus_root_cid": demo.corpus_root_cid,
            "document_count": demo.document_count,
            "document_route_page_count": demo.document_routes.page_count,
            "document_shard_count": demo.document_shard_count,
            "index_root_cid": demo.index_root_cid,
            "jurisdictions": jurisdictions,
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
        "depends_on": [CHUNKER_TASK_ID, ADAPTER_TASK_ID],
        "description": (
            "LCR-027 state-law term-range BM25. Jurisdiction-aware legal "
            "tokenization, field-weighted documents, sorted postings, bounded "
            "cells/term shards, lexicographic term-range routes, explanations, "
            "and differential reference scores. Hermetic fixture evaluation "
            "only. Does not authorize Hub upload."
        ),
        "differential": {
            "fixtures": fixtures,
            "sample_queries": sample,
            "score_abs_tolerance": SCORE_ABS_TOLERANCE,
            "scores_match_reference_bm25": True,
        },
        "family_counts": {
            "bm25": demo.document_count,
            "bm25_documents": demo.document_count,
            "bm25_postings": demo.posting_count,
            "chunks": conservation["admitted_count"],
        },
        "field_weights": demo.config.field_weights.to_dict(),
        "goal_id": GOAL_ID,
        "network_required": False,
        "parameters": {
            "b": DEFAULT_B,
            "k1": DEFAULT_K1,
            "legal_tokenizer_id": LEGAL_TOKENIZER_ID,
            "legacy_parameter_delta": legacy_parameter_delta(),
            "stopword_policy_id": STOPWORD_POLICY_ID,
            "tokenizer_id": TOKENIZER_ID,
            "tokenizer_version": TOKENIZER_VERSION,
        },
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "report_kind": "fixture_bm25",
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "tokenizer": shared_tokenizer_identity(demo.config),
    }
    compact = dict(payload)
    assert_no_secrets_or_home_paths(compact)
    blob = json.dumps(compact, sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise Bm25ReceiptError("BM25 report contains an absolute home path")
    compact["report_digest_sha256"] = digest_mapping(
        {key: value for key, value in compact.items() if key != "report_digest_sha256"}
    )
    return compact


def write_bm25_evaluation_report(
    path: PathLike | None = None,
    *,
    index: StateLawsBm25Index | None = None,
) -> Path:
    target = Path(path) if path is not None else default_bm25_report_path()
    payload = build_bm25_evaluation_report(index=index)
    write_json_atomic(target, payload)
    return target


def load_bm25_evaluation_report(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_bm25_report_path()
    if not target.is_file():
        raise Bm25ReceiptError(f"BM25 evaluation report not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise Bm25ReceiptError("BM25 evaluation report root must be an object")
    return dict(payload)


def assert_bm25_evaluation_report(payload: Mapping[str, Any]) -> None:
    """Fail closed if the report would authorize release or weaken the contract."""

    if payload.get("task_id") != TASK_ID:
        raise Bm25ReceiptError(f"report task_id must be {TASK_ID!r}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise Bm25ReceiptError(
            f"report schema_version must be {SCHEMA_VERSION!r}"
        )
    if payload.get("schema") != REPORT_SCHEMA:
        raise Bm25ReceiptError(f"report schema must be {REPORT_SCHEMA!r}")
    if payload.get("authorizing_hub_upload") is True:
        raise Bm25ReleaseAuthorizationError("BM25 report cannot authorize Hub upload")
    if payload.get("authorizing_for_publication") is True:
        raise Bm25ReleaseAuthorizationError(
            "BM25 report cannot authorize publication"
        )
    acceptance = payload.get("acceptance") or {}
    if not isinstance(acceptance, Mapping):
        raise Bm25ReceiptError("report acceptance must be a mapping")
    if acceptance.get("hub_upload") is not False:
        raise Bm25ReceiptError("report must not claim Hub upload")
    if acceptance.get("documents_equal_admitted_searchable_chunks") is not True:
        raise Bm25ReceiptError("report must prove documents equal admitted chunks")
    if acceptance.get("row_conservation") is not True:
        raise Bm25ReceiptError("report must prove row conservation")
    if acceptance.get("postings_reconcile") is not True:
        raise Bm25ReceiptError("report must prove postings reconcile")
    if acceptance.get("physical_bounds_hold") is not True:
        raise Bm25ReceiptError("report must prove physical bounds")
    if acceptance.get("posting_routes_lexicographic") is not True:
        raise Bm25ReceiptError("report must prove lexicographic posting routes")
    if acceptance.get("sample_queries_span_all_regions_and_dc") is not True:
        raise Bm25ReceiptError("report must prove region/DC query coverage")
    if acceptance.get("scores_match_reference_bm25") is not True:
        raise Bm25ReceiptError("report must prove reference BM25 scores")
    if acceptance.get("exact_scoring_parity_within_tolerance") is not True:
        raise Bm25ReceiptError("report must prove exact scoring parity")
    bounds = payload.get("bounds") or {}
    if not isinstance(bounds, Mapping):
        raise Bm25ReceiptError("report bounds must be a mapping")
    if bounds.get("maximum_rows_per_physical_shard") != MAX_ROWS_PER_PHYSICAL_SHARD:
        raise Bm25ReceiptError("report physical shard bound must be 4096")
    if bounds.get("maximum_posting_pointers_per_cell") != MAX_POSTING_POINTERS_PER_ROW:
        raise Bm25ReceiptError("report posting-cell bound must be 4096")
    parameters = payload.get("parameters") or {}
    if not isinstance(parameters, Mapping):
        raise Bm25ReceiptError("report parameters must be a mapping")
    if parameters.get("tokenizer_id") != TOKENIZER_ID:
        raise Bm25ReceiptError("report tokenizer_id is not the sealed state-laws tokenizer")
    sample = (payload.get("differential") or {}).get("sample_queries") or {}
    covered = set(sample.get("regions_covered") or ())
    missing = [name for name in REQUIRED_QUERY_REGIONS if name not in covered]
    if missing:
        raise Bm25ReceiptError(f"sample queries missing regions {missing!r}")
    blob = json.dumps(dict(payload), sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise Bm25ReceiptError("BM25 report contains an absolute home path")
    assert_no_secrets_or_home_paths(payload)


def check_evaluation_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a report object against sealed LCR-027 acceptance."""

    assert_bm25_evaluation_report(payload)
    sample = (payload.get("differential") or {}).get("sample_queries") or {}
    return {
        "ok": True,
        "document_count": (payload.get("admitted") or {}).get("document_count"),
        "max_score_delta": sample.get("max_score_delta"),
        "query_count": sample.get("query_count"),
        "regions_covered": sample.get("regions_covered"),
        "task_id": TASK_ID,
    }


__all__ = [
    "AUTHORITY_FIELDS",
    "CONTENT_FIELDS",
    "DEFAULT_B",
    "DEFAULT_FIELD_WEIGHTS",
    "DEFAULT_K1",
    "DOCUMENT_COUNT_CEILING",
    "DOCUMENTS_SORTED_BY",
    "FIELD_ORDER",
    "FORBIDDEN_DOCUMENT_CEILING",
    "GOAL_ID",
    "LEGAL_TOKENIZER_ID",
    "MAX_POSTING_POINTERS_PER_ROW",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "POSTINGS_SORTED_BY",
    "PRIMARY_KEY",
    "PRODUCER",
    "PROGRAM_ID",
    "REPORT_SCHEMA",
    "REQUIRED_QUERY_REGIONS",
    "SCHEMA_VERSION",
    "TASK_ID",
    "TERMS_SORTED_BY",
    "TOKENIZER_ID",
    "TOKENIZER_SHARED_BY",
    "Bm25BoundError",
    "Bm25ConfigError",
    "Bm25CoverageError",
    "Bm25EvaluationError",
    "Bm25FilterError",
    "Bm25Hit",
    "Bm25ProjectionError",
    "Bm25ReceiptError",
    "Bm25ReleaseAuthorizationError",
    "Bm25RootReconcileError",
    "Bm25ScoreError",
    "DocumentShard",
    "FieldScoreContribution",
    "FieldTokenStream",
    "FieldWeightConfig",
    "IndexField",
    "LegalBm25Document",
    "PostingCell",
    "PostingPointer",
    "StateLawsBm25Config",
    "StateLawsBm25Error",
    "StateLawsBm25Index",
    "TermPosting",
    "TermRangeShard",
    "TermScoreExplanation",
    "assert_bm25_evaluation_report",
    "assert_boundary_terms_route_once",
    "assert_every_admitted_chunk_has_document",
    "assert_externally_sorted",
    "assert_no_posting_lineage",
    "assert_postings_reconcile",
    "assert_row_conservation",
    "assert_scores_match_reference",
    "assert_shards_bounded",
    "bind_fixture_bm25",
    "build_bm25_evaluation_report",
    "build_corpus_root_cid",
    "build_index_root_cid",
    "build_state_laws_bm25_index",
    "census_region_for",
    "check_evaluation_report",
    "default_bm25_config",
    "default_bm25_report_path",
    "evaluate_sample_queries",
    "fixture_bm25_chunks",
    "fixture_bm25_config",
    "fixture_sample_queries",
    "iter_projected_documents",
    "legacy_parameter_delta",
    "load_bm25_evaluation_report",
    "production_bm25_bounds",
    "project_admitted_documents",
    "project_legal_document",
    "reconcile_roots",
    "reference_field_term_score",
    "shared_tokenizer_identity",
    "shard_document_records",
    "shard_term_records",
    "split_posting_cells",
    "tokenize_index_text",
    "tokenize_query",
    "write_bm25_evaluation_report",
]


if __name__ == "__main__":
    written = write_bm25_evaluation_report()
    payload = load_bm25_evaluation_report(written)
    print(
        f"wrote {REPORT_RELATIVE_PATH.as_posix()} "
        f"admitted_documents={payload['admitted']['document_count']}"
    )
