"""Deterministic BM25 shards for the CVEfixes Hugging Face release.

The base CVEfixes release owns the canonical corpus Parquet files.  This module
adds the two lexical data configurations and their SkillCenter-compatible meta
indexes without coupling the BM25 builder to the rest of the release writer:

* ``data/bm25/documents/*.parquet`` binds corpus CIDs to BM25 lengths;
* ``data/bm25/postings/*.parquet`` stores bounded logical posting lists;
* ``indexes/bm25_document_chunks.parquet`` binds document shards; and
* ``indexes/bm25_keyword_shards.parquet`` routes term ranges remotely.

Inputs are normalized public corpus rows.  A row may use either
``entry_cid``/``body`` or the existing CVEfixes release aliases
``record_id``/``record_json``.  Source bodies and credentials must already have
been removed by the public release policy before calling this module.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1_from_digest


CVEFIXES_HF_BM25_LAYOUT_SCHEMA_VERSION: Final = (
    "cvefixes-hf-bm25-layout/v1"
)
CVEFIXES_HF_BM25_DOCUMENT_SCHEMA_VERSION: Final = (
    "cvefixes-hf-bm25-document/v1"
)
CVEFIXES_HF_BM25_POSTING_SCHEMA_VERSION: Final = (
    "cvefixes-hf-bm25-posting/v1"
)
CVEFIXES_HF_META_SCHEMA_VERSION: Final = "cvefixes-hf-shard-meta/v1"
CVEFIXES_BM25_TOKENIZER: Final = (
    "cvefixes-ascii-code-nfkc-casefold/v1"
)

DEFAULT_ROWS_PER_SHARD: Final = 4096
DEFAULT_TERMS_PER_SHARD: Final = 4096
DEFAULT_POSTINGS_PER_ROW: Final = 4096
DEFAULT_K1: Final = 1.2
DEFAULT_B: Final = 0.75
DEFAULT_TITLE_WEIGHT: Final = 5.0
DEFAULT_BODY_WEIGHT: Final = 1.0
PARQUET_COMPRESSION: Final = "zstd"
PARQUET_COMPRESSION_LEVEL: Final = 6

_TOKEN_RE: Final = re.compile(
    r"[a-z0-9]+(?:[-_./:][a-z0-9]+)*"
)
_TOKEN_SPLIT_RE: Final = re.compile(r"[-_./:]")
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
_PART_RE: Final = re.compile(r"part-\d{6}\.parquet")
_INT32_MAX: Final = 2_147_483_647


class CVEfixesBM25LayoutError(ValueError):
    """Raised when BM25 inputs or staged artifacts violate the layout."""


@dataclass(frozen=True, slots=True)
class CVEfixesBM25LayoutConfig:
    """Bounded, reproducible BM25 export settings."""

    max_documents: int = 250_000
    max_text_characters: int = 8 * 1024 * 1024
    max_rows_per_shard: int = DEFAULT_ROWS_PER_SHARD
    terms_per_shard: int = DEFAULT_TERMS_PER_SHARD
    postings_per_row: int = DEFAULT_POSTINGS_PER_ROW
    max_query_terms: int = 64
    k1: float = DEFAULT_K1
    b: float = DEFAULT_B
    title_weight: float = DEFAULT_TITLE_WEIGHT
    body_weight: float = DEFAULT_BODY_WEIGHT
    tokenizer: str = CVEFIXES_BM25_TOKENIZER
    schema_version: str = CVEFIXES_HF_BM25_LAYOUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "max_documents",
            "max_text_characters",
            "max_rows_per_shard",
            "terms_per_shard",
            "postings_per_row",
            "max_query_terms",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise CVEfixesBM25LayoutError(
                    f"{name} must be a positive integer"
                )
        if self.max_documents > _INT32_MAX:
            raise CVEfixesBM25LayoutError(
                "max_documents exceeds the int32 posting identifier limit"
            )
        if self.max_rows_per_shard > _INT32_MAX:
            raise CVEfixesBM25LayoutError(
                "max_rows_per_shard exceeds the int32 limit"
            )
        if (
            self.terms_per_shard > _INT32_MAX
            or self.postings_per_row > _INT32_MAX
        ):
            raise CVEfixesBM25LayoutError(
                "term and posting bounds must fit int32"
            )
        for name in ("k1", "title_weight", "body_weight"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0.0
            ):
                raise CVEfixesBM25LayoutError(
                    f"{name} must be a positive finite number"
                )
        if (
            isinstance(self.b, bool)
            or not isinstance(self.b, (int, float))
            or not math.isfinite(float(self.b))
            or not 0.0 <= float(self.b) <= 1.0
        ):
            raise CVEfixesBM25LayoutError(
                "b must be finite and between zero and one"
            )
        if self.tokenizer != CVEFIXES_BM25_TOKENIZER:
            raise CVEfixesBM25LayoutError(
                "unsupported CVEfixes BM25 tokenizer"
            )
        if self.schema_version != CVEFIXES_HF_BM25_LAYOUT_SCHEMA_VERSION:
            raise CVEfixesBM25LayoutError(
                "unsupported CVEfixes BM25 layout schema"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "b": float(self.b),
            "body_weight": float(self.body_weight),
            "k1": float(self.k1),
            "max_documents": self.max_documents,
            "max_query_terms": self.max_query_terms,
            "max_rows_per_shard": self.max_rows_per_shard,
            "max_text_characters": self.max_text_characters,
            "postings_per_row": self.postings_per_row,
            "schema_version": self.schema_version,
            "terms_per_shard": self.terms_per_shard,
            "title_weight": float(self.title_weight),
            "tokenizer": self.tokenizer,
        }


@dataclass(frozen=True, slots=True)
class BM25ArtifactDescriptor:
    """Content address and physical facts for one staged file."""

    relative_path: str
    sha256: str
    cid: str
    size_bytes: int
    row_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "cid": self.cid,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class CVEfixesBM25LayoutSummary:
    """Manifest-ready result returned by the standalone BM25 builder."""

    output_dir: str
    document_count: int
    document_shard_count: int
    posting_count: int
    posting_row_count: int
    posting_shard_count: int
    term_count: int
    token_instance_count: int
    average_document_length: float
    document_index: BM25ArtifactDescriptor
    keyword_index: BM25ArtifactDescriptor
    config: CVEfixesBM25LayoutConfig
    schema_version: str = CVEFIXES_HF_BM25_LAYOUT_SCHEMA_VERSION

    @property
    def indexes(self) -> dict[str, dict[str, Any]]:
        return {
            "bm25_document_chunks": self.document_index.to_dict(),
            "bm25_keyword_shards": self.keyword_index.to_dict(),
        }

    @property
    def data_configs(self) -> dict[str, str]:
        return {
            "bm25_documents": "data/bm25/documents/*.parquet",
            "bm25_postings": "data/bm25/postings/*.parquet",
        }

    @property
    def remote_index_configs(self) -> dict[str, str]:
        return {
            "bm25_keyword_index": (
                "indexes/bm25_keyword_shards.parquet"
            ),
        }

    @property
    def counts(self) -> dict[str, int]:
        return {
            "bm25_document_chunks": self.document_shard_count,
            "bm25_documents": self.document_count,
            "bm25_keyword_shards": self.posting_shard_count,
            "bm25_posting_rows": self.posting_row_count,
            "bm25_postings": self.posting_count,
            "bm25_terms": self.term_count,
            "bm25_token_instances": self.token_instance_count,
        }

    def to_manifest_fragment(self) -> dict[str, Any]:
        """Return JSON-ready values for the parent release manifest."""

        return {
            "bm25": {
                "average_document_length": self.average_document_length,
                "b": float(self.config.b),
                "body_weight": float(self.config.body_weight),
                "k1": float(self.config.k1),
                "max_query_terms": self.config.max_query_terms,
                "posting_rows_per_record": self.config.postings_per_row,
                "terms_per_shard": self.config.terms_per_shard,
                "title_weight": float(self.config.title_weight),
                "tokenizer": self.config.tokenizer,
            },
            "configs": {
                **self.data_configs,
                **self.remote_index_configs,
            },
            "counts": self.counts,
            "indexes": self.indexes,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class _Document:
    entry_cid: str
    document_index: int
    record_type: str
    authority: str
    title: str
    body: str


def tokenize_cvefixes_bm25(value: str) -> tuple[str, ...]:
    """Tokenize text using the release's fixed code-aware lexical profile.

    A compound such as ``CVE-2026-0042`` emits both the full compound and the
    components ``cve``, ``2026``, and ``0042``.  Simple tokens are emitted once.
    NFKC and case-folding happen before the intentionally ASCII-only grammar,
    avoiding locale or platform dependent token boundaries.
    """

    if not isinstance(value, str):
        raise CVEfixesBM25LayoutError("BM25 text must be a string")
    try:
        normalized = unicodedata.normalize("NFKC", value).casefold()
    except (TypeError, ValueError) as exc:
        raise CVEfixesBM25LayoutError(
            "BM25 text cannot be Unicode-normalized"
        ) from exc
    result: list[str] = []
    for match in _TOKEN_RE.findall(normalized):
        result.append(match)
        if _TOKEN_SPLIT_RE.search(match):
            result.extend(
                part for part in _TOKEN_SPLIT_RE.split(match) if part
            )
    return tuple(result)


def _clean_text(
    value: Any,
    label: str,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise CVEfixesBM25LayoutError(f"{label} must be a string")
    if "\x00" in value or len(value) > maximum:
        raise CVEfixesBM25LayoutError(
            f"{label} is not bounded clean text"
        )
    if not allow_empty and (not value or value != value.strip()):
        raise CVEfixesBM25LayoutError(
            f"{label} must be non-empty trimmed text"
        )
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CVEfixesBM25LayoutError(
            f"{label} is not valid UTF-8 text"
        ) from exc
    return value


def _aliased_text(
    row: Mapping[str, Any],
    aliases: Sequence[str],
    label: str,
    *,
    maximum: int,
) -> str:
    present = [(name, row[name]) for name in aliases if name in row]
    if not present:
        raise CVEfixesBM25LayoutError(
            f"{label} requires one of: {', '.join(aliases)}"
        )
    first = present[0][1]
    if any(value != first for _, value in present[1:]):
        raise CVEfixesBM25LayoutError(
            f"{label} aliases contain different values"
        )
    return _clean_text(first, label, maximum=maximum)


def _normalize_documents(
    rows: Sequence[Mapping[str, Any]],
    config: CVEfixesBM25LayoutConfig,
) -> tuple[_Document, ...]:
    if isinstance(rows, (str, bytes, bytearray)) or not isinstance(
        rows, Sequence
    ):
        raise CVEfixesBM25LayoutError(
            "corpus rows must be a sequence of mappings"
        )
    if not rows:
        raise CVEfixesBM25LayoutError("corpus rows must not be empty")
    if len(rows) > config.max_documents:
        raise CVEfixesBM25LayoutError(
            "corpus rows exceed max_documents"
        )
    for position, raw_row in enumerate(rows):
        if not isinstance(raw_row, Mapping):
            raise CVEfixesBM25LayoutError(
                f"corpus row {position} must be a mapping"
            )
    explicit_indexes = tuple("document_index" in row for row in rows)
    if any(explicit_indexes) and not all(explicit_indexes):
        raise CVEfixesBM25LayoutError(
            "document_index must be present on every row or no rows"
        )

    pending: list[tuple[int | None, str, str, str, str, str]] = []
    for position, raw_row in enumerate(rows):
        entry_cid = _aliased_text(
            raw_row,
            ("entry_cid", "record_id"),
            f"corpus row {position} identity",
            maximum=256,
        )
        body = _aliased_text(
            raw_row,
            ("body", "text", "record_json"),
            f"corpus row {position} body",
            maximum=config.max_text_characters,
        )
        record_type = _clean_text(
            raw_row.get("record_type", "corpus"),
            f"corpus row {position} record_type",
            maximum=128,
        )
        authority = _clean_text(
            raw_row.get("authority", "non_authoritative"),
            f"corpus row {position} authority",
            maximum=128,
        )
        title_value = raw_row.get(
            "title", f"{record_type} {entry_cid}"
        )
        title = _clean_text(
            title_value,
            f"corpus row {position} title",
            maximum=4096,
        )
        document_index: int | None = None
        if explicit_indexes[position]:
            value = raw_row["document_index"]
            if (
                type(value) is not int
                or value < 0
                or value > _INT32_MAX
            ):
                raise CVEfixesBM25LayoutError(
                    "document_index must be a non-negative int32"
                )
            document_index = value
        pending.append(
            (
                document_index,
                entry_cid,
                record_type,
                authority,
                title,
                body,
            )
        )

    if len({item[1] for item in pending}) != len(pending):
        raise CVEfixesBM25LayoutError(
            "corpus rows contain duplicate entry CIDs"
        )
    if all(explicit_indexes):
        pending.sort(key=lambda item: int(item[0]))
        if [item[0] for item in pending] != list(range(len(pending))):
            raise CVEfixesBM25LayoutError(
                "document_index values must be contiguous from zero"
            )
    else:
        pending.sort(key=lambda item: (item[2], item[1]))

    return tuple(
        _Document(
            entry_cid=item[1],
            document_index=index,
            record_type=item[2],
            authority=item[3],
            title=item[4],
            body=item[5],
        )
        for index, item in enumerate(pending)
    )


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - project release extra
        raise CVEfixesBM25LayoutError(
            "pyarrow is required for the CVEfixes BM25 layout"
        ) from exc
    return pa, pq


def _document_schema(pa: Any, config: CVEfixesBM25LayoutConfig) -> Any:
    return pa.schema(
        [
            ("authority", pa.string(), False),
            ("body_length", pa.int32(), False),
            ("body_sha256", pa.string(), False),
            ("document_index", pa.int32(), False),
            ("document_length", pa.int32(), False),
            ("entry_cid", pa.string(), False),
            ("record_type", pa.string(), False),
            ("schema_version", pa.string(), False),
            ("title", pa.string(), False),
            ("title_length", pa.int32(), False),
            ("token_input_sha256", pa.string(), False),
        ],
        metadata={
            b"primary_key": b"entry_cid",
            b"schema_version": (
                CVEFIXES_HF_BM25_DOCUMENT_SCHEMA_VERSION.encode("ascii")
            ),
            b"tokenizer": config.tokenizer.encode("ascii"),
        },
    )


def _posting_schema(pa: Any, config: CVEfixesBM25LayoutConfig) -> Any:
    return pa.schema(
        [
            ("body_frequencies", pa.list_(pa.int32()), False),
            ("corpus_frequency", pa.int64(), False),
            ("document_frequency", pa.int32(), False),
            ("document_indices", pa.list_(pa.int32()), False),
            ("document_lengths", pa.list_(pa.int32()), False),
            ("idf", pa.float64(), False),
            ("posting_chunk_count", pa.int32(), False),
            ("posting_chunk_index", pa.int32(), False),
            ("schema_version", pa.string(), False),
            ("term", pa.string(), False),
            ("title_frequencies", pa.list_(pa.int32()), False),
        ],
        metadata={
            b"b": repr(float(config.b)).encode("ascii"),
            b"body_weight": repr(float(config.body_weight)).encode("ascii"),
            b"k1": repr(float(config.k1)).encode("ascii"),
            b"schema_version": (
                CVEFIXES_HF_BM25_POSTING_SCHEMA_VERSION.encode("ascii")
            ),
            b"title_weight": repr(
                float(config.title_weight)
            ).encode("ascii"),
            b"tokenizer": config.tokenizer.encode("ascii"),
        },
    )


def _meta_schema(pa: Any, *, postings: bool) -> Any:
    fields = [
        ("cid", pa.string(), False),
        ("end_document_index", pa.int64(), False),
        ("first_key", pa.string(), False),
        ("kind", pa.string(), False),
        ("last_key", pa.string(), False),
        ("relative_path", pa.string(), False),
        ("row_count", pa.int64(), False),
        ("schema_version", pa.string(), False),
        ("sha256", pa.string(), False),
        ("shard_id", pa.int32(), False),
        ("size_bytes", pa.int64(), False),
        ("start_document_index", pa.int64(), False),
    ]
    if postings:
        fields.extend(
            [
                ("posting_count", pa.int64(), False),
                ("term_count", pa.int32(), False),
                ("token_instance_count", pa.int64(), False),
            ]
        )
    return pa.schema(
        fields,
        metadata={
            b"schema_version": CVEFIXES_HF_META_SCHEMA_VERSION.encode(
                "ascii"
            )
        },
    )


def _write_parquet(
    path: Path,
    table: Any,
    config: CVEfixesBM25LayoutConfig,
    *,
    enforce_row_limit: bool = True,
) -> None:
    _, pq = _pyarrow()
    if table.num_rows <= 0:
        raise CVEfixesBM25LayoutError(
            f"cannot write an empty Parquet file: {path.name}"
        )
    if enforce_row_limit and table.num_rows > config.max_rows_per_shard:
        raise CVEfixesBM25LayoutError(
            f"Parquet shard exceeds row limit: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    pq.write_table(
        table,
        partial,
        compression=PARQUET_COMPRESSION,
        compression_level=PARQUET_COMPRESSION_LEVEL,
        data_page_version="1.0",
        row_group_size=min(
            config.max_rows_per_shard, max(1, table.num_rows)
        ),
        use_dictionary=False,
        version="2.6",
        write_statistics=True,
    )
    parquet = pq.ParquetFile(partial)
    if parquet.metadata.num_rows != table.num_rows:
        partial.unlink(missing_ok=True)
        raise CVEfixesBM25LayoutError(
            f"Parquet row count changed while writing: {path}"
        )
    compressions = {
        parquet.metadata.row_group(group).column(column).compression
        for group in range(parquet.num_row_groups)
        for column in range(
            parquet.metadata.row_group(group).num_columns
        )
    }
    if compressions and compressions != {"ZSTD"}:
        partial.unlink(missing_ok=True)
        raise CVEfixesBM25LayoutError(
            f"Parquet shard is not uniformly ZSTD compressed: {path}"
        )
    os.replace(partial, path)


def _file_descriptor(
    path: Path,
    *,
    root: Path,
    row_count: int,
) -> BM25ArtifactDescriptor:
    content = path.read_bytes()
    digest = hashlib.sha256(content).digest()
    return BM25ArtifactDescriptor(
        relative_path=path.relative_to(root).as_posix(),
        sha256=digest.hex(),
        cid=cid_v1_from_digest(digest),
        size_bytes=len(content),
        row_count=row_count,
    )


def _meta_row(
    descriptor: BM25ArtifactDescriptor,
    *,
    shard_id: int,
    first_key: str,
    last_key: str,
    start_document_index: int,
    end_document_index: int,
    kind: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "cid": descriptor.cid,
        "end_document_index": end_document_index,
        "first_key": first_key,
        "kind": kind,
        "last_key": last_key,
        "relative_path": descriptor.relative_path,
        "row_count": descriptor.row_count,
        "schema_version": CVEFIXES_HF_META_SCHEMA_VERSION,
        "sha256": descriptor.sha256,
        "shard_id": shard_id,
        "size_bytes": descriptor.size_bytes,
        "start_document_index": start_document_index,
        **extra,
    }


def _document_rows(
    documents: Sequence[_Document],
) -> tuple[list[dict[str, Any]], tuple[tuple[int, int, int], ...]]:
    rows: list[dict[str, Any]] = []
    lengths: list[tuple[int, int, int]] = []
    for document in documents:
        title_length = len(tokenize_cvefixes_bm25(document.title))
        body_length = len(tokenize_cvefixes_bm25(document.body))
        document_length = title_length + body_length
        if document_length <= 0:
            raise CVEfixesBM25LayoutError(
                f"document has no searchable tokens: {document.entry_cid}"
            )
        body_digest = hashlib.sha256(
            document.body.encode("utf-8")
        ).hexdigest()
        token_input_digest = hashlib.sha256(
            canonical_json_bytes(
                {
                    "body": document.body,
                    "title": document.title,
                    "tokenizer": CVEFIXES_BM25_TOKENIZER,
                }
            )
        ).hexdigest()
        rows.append(
            {
                "authority": document.authority,
                "body_length": body_length,
                "body_sha256": body_digest,
                "document_index": document.document_index,
                "document_length": document_length,
                "entry_cid": document.entry_cid,
                "record_type": document.record_type,
                "schema_version": (
                    CVEFIXES_HF_BM25_DOCUMENT_SCHEMA_VERSION
                ),
                "title": document.title,
                "title_length": title_length,
                "token_input_sha256": token_input_digest,
            }
        )
        lengths.append((title_length, body_length, document_length))
    return rows, tuple(lengths)


def _export_documents(
    documents: Sequence[_Document],
    root: Path,
    config: CVEfixesBM25LayoutConfig,
) -> tuple[list[dict[str, Any]], tuple[tuple[int, int, int], ...]]:
    pa, _ = _pyarrow()
    rows, lengths = _document_rows(documents)
    destination = root / "data" / "bm25" / "documents"
    metadata: list[dict[str, Any]] = []
    for shard_id, start in enumerate(
        range(0, len(rows), config.max_rows_per_shard)
    ):
        chunk = rows[start : start + config.max_rows_per_shard]
        path = destination / f"part-{shard_id:06d}.parquet"
        table = pa.Table.from_pylist(
            chunk, schema=_document_schema(pa, config)
        )
        _write_parquet(path, table, config)
        descriptor = _file_descriptor(
            path, root=root, row_count=table.num_rows
        )
        metadata.append(
            _meta_row(
                descriptor,
                shard_id=shard_id,
                first_key=str(chunk[0]["entry_cid"]),
                last_key=str(chunk[-1]["entry_cid"]),
                start_document_index=start,
                end_document_index=start + len(chunk) - 1,
                kind="bm25_documents",
            )
        )
    return metadata, lengths


def _fts5_idf(document_count: int, document_frequency: int) -> float:
    if (
        document_count <= 0
        or document_frequency <= 0
        or document_frequency > document_count
    ):
        raise CVEfixesBM25LayoutError(
            "invalid BM25 document frequency"
        )
    value = math.log(
        (document_count - document_frequency + 0.5)
        / (document_frequency + 0.5)
    )
    return value if value > 0.0 else 1.0e-6


def _posting_groups(
    documents: Sequence[_Document],
    lengths: Sequence[tuple[int, int, int]],
    config: CVEfixesBM25LayoutConfig,
) -> tuple[tuple[str, tuple[dict[str, Any], ...]], ...]:
    postings: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for document in documents:
        title_frequencies = Counter(
            tokenize_cvefixes_bm25(document.title)
        )
        body_frequencies = Counter(
            tokenize_cvefixes_bm25(document.body)
        )
        for term in sorted(title_frequencies.keys() | body_frequencies.keys()):
            postings[term].append(
                (
                    document.document_index,
                    int(title_frequencies[term]),
                    int(body_frequencies[term]),
                )
            )

    groups: list[tuple[str, tuple[dict[str, Any], ...]]] = []
    document_count = len(documents)
    for term in sorted(postings):
        values = postings[term]
        document_frequency = len(values)
        corpus_frequency = sum(
            title_frequency + body_frequency
            for _, title_frequency, body_frequency in values
        )
        chunk_count = math.ceil(
            document_frequency / config.postings_per_row
        )
        rows: list[dict[str, Any]] = []
        for chunk_index, start in enumerate(
            range(0, document_frequency, config.postings_per_row)
        ):
            selected = values[
                start : start + config.postings_per_row
            ]
            document_indices = [item[0] for item in selected]
            rows.append(
                {
                    "body_frequencies": [
                        item[2] for item in selected
                    ],
                    "corpus_frequency": corpus_frequency,
                    "document_frequency": document_frequency,
                    "document_indices": document_indices,
                    "document_lengths": [
                        lengths[index][2] for index in document_indices
                    ],
                    "idf": _fts5_idf(
                        document_count, document_frequency
                    ),
                    "posting_chunk_count": chunk_count,
                    "posting_chunk_index": chunk_index,
                    "schema_version": (
                        CVEFIXES_HF_BM25_POSTING_SCHEMA_VERSION
                    ),
                    "term": term,
                    "title_frequencies": [
                        item[1] for item in selected
                    ],
                }
            )
        if len(rows) > config.max_rows_per_shard:
            raise CVEfixesBM25LayoutError(
                f"one term exceeds the Parquet row limit: {term!r}"
            )
        groups.append((term, tuple(rows)))
    if not groups:
        raise CVEfixesBM25LayoutError(
            "corpus does not produce any BM25 terms"
        )
    return tuple(groups)


def _partition_posting_groups(
    groups: Sequence[tuple[str, Sequence[Mapping[str, Any]]]],
    config: CVEfixesBM25LayoutConfig,
) -> tuple[tuple[Mapping[str, Any], ...], ...]:
    result: list[tuple[Mapping[str, Any], ...]] = []
    pending: list[Mapping[str, Any]] = []
    pending_terms = 0
    for _, group in groups:
        if (
            pending
            and (
                pending_terms >= config.terms_per_shard
                or len(pending) + len(group)
                > config.max_rows_per_shard
            )
        ):
            result.append(tuple(pending))
            pending = []
            pending_terms = 0
        pending.extend(group)
        pending_terms += 1
    if pending:
        result.append(tuple(pending))
    return tuple(result)


def _export_postings(
    documents: Sequence[_Document],
    lengths: Sequence[tuple[int, int, int]],
    root: Path,
    config: CVEfixesBM25LayoutConfig,
) -> tuple[list[dict[str, Any]], dict[str, int | float]]:
    pa, _ = _pyarrow()
    groups = _posting_groups(documents, lengths, config)
    parts = _partition_posting_groups(groups, config)
    destination = root / "data" / "bm25" / "postings"
    metadata: list[dict[str, Any]] = []
    total_postings = 0
    total_instances = 0
    for shard_id, part in enumerate(parts):
        terms = tuple(dict.fromkeys(str(row["term"]) for row in part))
        posting_count = sum(
            len(row["document_indices"]) for row in part
        )
        token_instances = sum(
            sum(row["title_frequencies"])
            + sum(row["body_frequencies"])
            for row in part
        )
        table = pa.Table.from_pylist(
            list(part), schema=_posting_schema(pa, config)
        )
        table = table.replace_schema_metadata(
            {
                **dict(table.schema.metadata or {}),
                b"first_term": terms[0].encode("utf-8"),
                b"last_term": terms[-1].encode("utf-8"),
                b"posting_count": str(posting_count).encode("ascii"),
                b"term_count": str(len(terms)).encode("ascii"),
                b"token_instance_count": str(
                    token_instances
                ).encode("ascii"),
            }
        )
        path = destination / f"part-{shard_id:06d}.parquet"
        _write_parquet(path, table, config)
        descriptor = _file_descriptor(
            path, root=root, row_count=table.num_rows
        )
        metadata.append(
            _meta_row(
                descriptor,
                shard_id=shard_id,
                first_key=terms[0],
                last_key=terms[-1],
                start_document_index=-1,
                end_document_index=-1,
                kind="bm25_postings",
                posting_count=posting_count,
                term_count=len(terms),
                token_instance_count=token_instances,
            )
        )
        total_postings += posting_count
        total_instances += token_instances
    return metadata, {
        "average_document_length": (
            sum(item[2] for item in lengths) / len(lengths)
        ),
        "posting_count": total_postings,
        "posting_row_count": sum(
            int(row["row_count"]) for row in metadata
        ),
        "term_count": len(groups),
        "token_instance_count": total_instances,
    }


def _write_meta_indexes(
    root: Path,
    document_meta: Sequence[Mapping[str, Any]],
    posting_meta: Sequence[Mapping[str, Any]],
    config: CVEfixesBM25LayoutConfig,
) -> tuple[BM25ArtifactDescriptor, BM25ArtifactDescriptor]:
    pa, _ = _pyarrow()
    index_dir = root / "indexes"
    document_path = index_dir / "bm25_document_chunks.parquet"
    keyword_path = index_dir / "bm25_keyword_shards.parquet"
    document_table = pa.Table.from_pylist(
        list(document_meta), schema=_meta_schema(pa, postings=False)
    )
    keyword_table = pa.Table.from_pylist(
        list(posting_meta), schema=_meta_schema(pa, postings=True)
    )
    _write_parquet(
        document_path,
        document_table,
        config,
        enforce_row_limit=False,
    )
    _write_parquet(
        keyword_path,
        keyword_table,
        config,
        enforce_row_limit=False,
    )
    return (
        _file_descriptor(
            document_path,
            root=root,
            row_count=document_table.num_rows,
        ),
        _file_descriptor(
            keyword_path,
            root=root,
            row_count=keyword_table.num_rows,
        ),
    )


def _install_staged_files(temporary: Path, output: Path) -> None:
    relative_directories = (
        Path("data/bm25/documents"),
        Path("data/bm25/postings"),
    )
    for relative in relative_directories:
        source = temporary / relative
        target = output / relative
        if target.is_symlink():
            raise CVEfixesBM25LayoutError(
                f"refusing to replace symlinked BM25 directory: {target}"
            )
        target.mkdir(parents=True, exist_ok=True)
        for existing in target.iterdir():
            if (
                existing.is_symlink()
                or not existing.is_file()
                or not _PART_RE.fullmatch(existing.name)
            ):
                raise CVEfixesBM25LayoutError(
                    f"unexpected file in owned BM25 directory: {existing}"
                )
        for existing in target.iterdir():
            existing.unlink()
        for staged in sorted(source.iterdir()):
            os.replace(staged, target / staged.name)

    for name in (
        "bm25_document_chunks.parquet",
        "bm25_keyword_shards.parquet",
    ):
        source = temporary / "indexes" / name
        target = output / "indexes" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise CVEfixesBM25LayoutError(
                f"refusing to replace unsafe BM25 index: {target}"
            )
        os.replace(source, target)


def build_cvefixes_bm25_hf_layout(
    corpus_rows: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
    *,
    config: CVEfixesBM25LayoutConfig | None = None,
) -> CVEfixesBM25LayoutSummary:
    """Build and validate the standalone BM25 portion of a Hub release.

    Rows with explicit ``document_index`` values must cover ``0..N-1``.
    Without explicit indices, rows are ordered by ``(record_type, entry_cid)``,
    matching the canonical config/record ordering of the base CVEfixes release.
    """

    selected = config or CVEfixesBM25LayoutConfig()
    if not isinstance(selected, CVEfixesBM25LayoutConfig):
        raise CVEfixesBM25LayoutError(
            "config must be CVEfixesBM25LayoutConfig"
        )
    documents = _normalize_documents(corpus_rows, selected)
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and (output.is_symlink() or not output.is_dir()):
        raise CVEfixesBM25LayoutError(
            "output_dir must be a real directory"
        )
    output.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".cvefixes-bm25-", dir=output)
    )
    try:
        document_meta, lengths = _export_documents(
            documents, temporary, selected
        )
        posting_meta, stats = _export_postings(
            documents, lengths, temporary, selected
        )
        document_index, keyword_index = _write_meta_indexes(
            temporary, document_meta, posting_meta, selected
        )
        temporary_summary = CVEfixesBM25LayoutSummary(
            output_dir=str(output),
            document_count=len(documents),
            document_shard_count=len(document_meta),
            posting_count=int(stats["posting_count"]),
            posting_row_count=int(stats["posting_row_count"]),
            posting_shard_count=len(posting_meta),
            term_count=int(stats["term_count"]),
            token_instance_count=int(stats["token_instance_count"]),
            average_document_length=float(
                stats["average_document_length"]
            ),
            document_index=document_index,
            keyword_index=keyword_index,
            config=selected,
        )
        _install_staged_files(temporary, output)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    validated = validate_cvefixes_bm25_hf_layout(
        output, config=selected
    )
    if (
        validated.counts != temporary_summary.counts
        or not math.isclose(
            validated.average_document_length,
            temporary_summary.average_document_length,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise CVEfixesBM25LayoutError(
            "installed BM25 layout differs from the completed build"
        )
    return validated


def _read_index(
    root: Path,
    name: str,
    *,
    postings: bool,
) -> tuple[Path, list[dict[str, Any]]]:
    _, pq = _pyarrow()
    path = root / "indexes" / name
    if path.is_symlink() or not path.is_file():
        raise CVEfixesBM25LayoutError(
            f"BM25 meta-index is missing: {name}"
        )
    table = pq.read_table(path)
    expected = _meta_schema(_pyarrow()[0], postings=postings)
    if not table.schema.equals(expected, check_metadata=True):
        raise CVEfixesBM25LayoutError(
            f"BM25 meta-index schema differs: {name}"
        )
    if table.num_rows <= 0:
        raise CVEfixesBM25LayoutError(
            f"BM25 meta-index is empty: {name}"
        )
    return path, [dict(row) for row in table.to_pylist()]


def _verified_shard(root: Path, row: Mapping[str, Any]) -> Path:
    relative = str(row.get("relative_path") or "")
    path = root.joinpath(*Path(relative).parts)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CVEfixesBM25LayoutError(
            "BM25 shard path escapes the release"
        ) from exc
    if (
        not relative
        or Path(relative).is_absolute()
        or path.is_symlink()
        or not path.is_file()
    ):
        raise CVEfixesBM25LayoutError(
            f"BM25 shard path is unsafe or missing: {relative!r}"
        )
    content = path.read_bytes()
    digest = hashlib.sha256(content).digest()
    if (
        row.get("sha256") != digest.hex()
        or row.get("cid") != cid_v1_from_digest(digest)
        or row.get("size_bytes") != len(content)
    ):
        raise CVEfixesBM25LayoutError(
            f"BM25 shard descriptor differs: {relative}"
        )
    return path


def _validate_document_shards(
    root: Path,
    meta_rows: Sequence[Mapping[str, Any]],
    config: CVEfixesBM25LayoutConfig,
) -> tuple[list[dict[str, Any]], set[str]]:
    _, pq = _pyarrow()
    result: list[dict[str, Any]] = []
    paths: set[str] = set()
    expected_index = 0
    for shard_id, row in enumerate(meta_rows):
        if (
            row.get("schema_version") != CVEFIXES_HF_META_SCHEMA_VERSION
            or row.get("kind") != "bm25_documents"
            or row.get("shard_id") != shard_id
            or row.get("start_document_index") != expected_index
        ):
            raise CVEfixesBM25LayoutError(
                "BM25 document meta-index is not contiguous"
            )
        path = _verified_shard(root, row)
        relative = path.relative_to(root).as_posix()
        if relative in paths:
            raise CVEfixesBM25LayoutError(
                "duplicate BM25 document shard pointer"
            )
        paths.add(relative)
        table = pq.read_table(path)
        expected_schema = _document_schema(_pyarrow()[0], config)
        if not table.schema.equals(expected_schema, check_metadata=True):
            raise CVEfixesBM25LayoutError(
                f"BM25 document schema differs: {relative}"
            )
        rows = [dict(item) for item in table.to_pylist()]
        if (
            not rows
            or len(rows) > config.max_rows_per_shard
            or row.get("row_count") != len(rows)
            or row.get("end_document_index")
            != expected_index + len(rows) - 1
            or row.get("first_key") != rows[0]["entry_cid"]
            or row.get("last_key") != rows[-1]["entry_cid"]
        ):
            raise CVEfixesBM25LayoutError(
                f"BM25 document shard metadata differs: {relative}"
            )
        if [item["document_index"] for item in rows] != list(
            range(expected_index, expected_index + len(rows))
        ):
            raise CVEfixesBM25LayoutError(
                f"BM25 document indices differ: {relative}"
            )
        for item in rows:
            if (
                item["schema_version"]
                != CVEFIXES_HF_BM25_DOCUMENT_SCHEMA_VERSION
                or item["document_length"]
                != item["title_length"] + item["body_length"]
                or item["document_length"] <= 0
                or not _SHA256_RE.fullmatch(item["body_sha256"])
                or not _SHA256_RE.fullmatch(
                    item["token_input_sha256"]
                )
            ):
                raise CVEfixesBM25LayoutError(
                    f"invalid BM25 document row: {relative}"
                )
        result.extend(rows)
        expected_index += len(rows)
    if len({row["entry_cid"] for row in result}) != len(result):
        raise CVEfixesBM25LayoutError(
            "BM25 documents contain duplicate entry CIDs"
        )
    return result, paths


def _validate_posting_shards(
    root: Path,
    meta_rows: Sequence[Mapping[str, Any]],
    documents: Sequence[Mapping[str, Any]],
    config: CVEfixesBM25LayoutConfig,
) -> tuple[dict[str, int], set[str]]:
    _, pq = _pyarrow()
    paths: set[str] = set()
    all_terms: list[str] = []
    posting_count = 0
    posting_rows = 0
    token_instances = 0
    lengths = {
        int(row["document_index"]): int(row["document_length"])
        for row in documents
    }
    previous_last = ""
    for shard_id, meta in enumerate(meta_rows):
        if (
            meta.get("schema_version") != CVEFIXES_HF_META_SCHEMA_VERSION
            or meta.get("kind") != "bm25_postings"
            or meta.get("shard_id") != shard_id
            or meta.get("start_document_index") != -1
            or meta.get("end_document_index") != -1
        ):
            raise CVEfixesBM25LayoutError(
                "BM25 keyword meta-index is malformed"
            )
        path = _verified_shard(root, meta)
        relative = path.relative_to(root).as_posix()
        if relative in paths:
            raise CVEfixesBM25LayoutError(
                "duplicate BM25 posting shard pointer"
            )
        paths.add(relative)
        table = pq.read_table(path)
        schema = _posting_schema(_pyarrow()[0], config)
        required_metadata = dict(schema.metadata or {})
        actual_metadata = dict(table.schema.metadata or {})
        if any(
            actual_metadata.get(key) != value
            for key, value in required_metadata.items()
        ):
            raise CVEfixesBM25LayoutError(
                f"BM25 posting schema metadata differs: {relative}"
            )
        if table.schema.remove_metadata() != schema.remove_metadata():
            raise CVEfixesBM25LayoutError(
                f"BM25 posting schema differs: {relative}"
            )
        rows = [dict(item) for item in table.to_pylist()]
        if (
            not rows
            or len(rows) > config.max_rows_per_shard
            or meta.get("row_count") != len(rows)
        ):
            raise CVEfixesBM25LayoutError(
                f"BM25 posting shard row count differs: {relative}"
            )
        raw_terms = [str(row["term"]) for row in rows]
        if raw_terms != sorted(raw_terms):
            raise CVEfixesBM25LayoutError(
                f"BM25 posting terms are not ordered: {relative}"
            )
        terms = list(dict.fromkeys(raw_terms))
        if (
            terms != sorted(terms)
            or meta.get("first_key") != terms[0]
            or meta.get("last_key") != terms[-1]
            or (previous_last and previous_last >= terms[0])
        ):
            raise CVEfixesBM25LayoutError(
                "BM25 keyword ranges overlap or are not ordered"
            )
        previous_last = terms[-1]
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[str(row["term"])].append(row)
        shard_postings = 0
        shard_instances = 0
        for term in terms:
            group = groups[term]
            chunk_count = len(group)
            if [row["posting_chunk_index"] for row in group] != list(
                range(chunk_count)
            ):
                raise CVEfixesBM25LayoutError(
                    f"BM25 posting chunks are incomplete: {term!r}"
                )
            document_indices: list[int] = []
            title_frequencies: list[int] = []
            body_frequencies: list[int] = []
            for row in group:
                ids = [int(item) for item in row["document_indices"]]
                field_lengths = {
                    len(ids),
                    len(row["document_lengths"]),
                    len(row["title_frequencies"]),
                    len(row["body_frequencies"]),
                }
                if (
                    row["schema_version"]
                    != CVEFIXES_HF_BM25_POSTING_SCHEMA_VERSION
                    or row["posting_chunk_count"] != chunk_count
                    or len(field_lengths) != 1
                    or not ids
                    or len(ids) > config.postings_per_row
                    or ids != sorted(ids)
                    or len(ids) != len(set(ids))
                ):
                    raise CVEfixesBM25LayoutError(
                        f"invalid BM25 posting row: {term!r}"
                    )
                if [lengths.get(index) for index in ids] != list(
                    row["document_lengths"]
                ):
                    raise CVEfixesBM25LayoutError(
                        f"BM25 posting lengths differ: {term!r}"
                    )
                document_indices.extend(ids)
                title_frequencies.extend(row["title_frequencies"])
                body_frequencies.extend(row["body_frequencies"])
            if (
                document_indices != sorted(document_indices)
                or len(document_indices) != len(set(document_indices))
                or any(
                    title_frequency < 0
                    or body_frequency < 0
                    or title_frequency + body_frequency <= 0
                    for title_frequency, body_frequency in zip(
                        title_frequencies, body_frequencies
                    )
                )
            ):
                raise CVEfixesBM25LayoutError(
                    f"BM25 posting coverage differs: {term!r}"
                )
            document_frequency = len(document_indices)
            corpus_frequency = sum(
                title_frequencies
            ) + sum(body_frequencies)
            expected_idf = _fts5_idf(
                len(documents), document_frequency
            )
            for row in group:
                if (
                    row["document_frequency"] != document_frequency
                    or row["corpus_frequency"] != corpus_frequency
                    or not math.isclose(
                        float(row["idf"]),
                        expected_idf,
                        rel_tol=0.0,
                        abs_tol=1e-15,
                    )
                ):
                    raise CVEfixesBM25LayoutError(
                        f"BM25 term statistics differ: {term!r}"
                    )
            shard_postings += document_frequency
            shard_instances += corpus_frequency
        if (
            meta.get("term_count") != len(terms)
            or meta.get("posting_count") != shard_postings
            or meta.get("token_instance_count") != shard_instances
            or actual_metadata.get(b"first_term")
            != terms[0].encode("utf-8")
            or actual_metadata.get(b"last_term")
            != terms[-1].encode("utf-8")
            or actual_metadata.get(b"posting_count")
            != str(shard_postings).encode("ascii")
            or actual_metadata.get(b"term_count")
            != str(len(terms)).encode("ascii")
            or actual_metadata.get(b"token_instance_count")
            != str(shard_instances).encode("ascii")
        ):
            raise CVEfixesBM25LayoutError(
                f"BM25 posting shard metadata differs: {relative}"
            )
        all_terms.extend(terms)
        posting_count += shard_postings
        posting_rows += len(rows)
        token_instances += shard_instances
    if len(all_terms) != len(set(all_terms)):
        raise CVEfixesBM25LayoutError(
            "BM25 terms occur in more than one keyword shard"
        )
    if token_instances != sum(
        int(row["document_length"]) for row in documents
    ):
        raise CVEfixesBM25LayoutError(
            "BM25 token instances differ from document lengths"
        )
    return {
        "posting_count": posting_count,
        "posting_row_count": posting_rows,
        "term_count": len(all_terms),
        "token_instance_count": token_instances,
    }, paths


def validate_cvefixes_bm25_hf_layout(
    output_dir: str | Path,
    *,
    config: CVEfixesBM25LayoutConfig | None = None,
) -> CVEfixesBM25LayoutSummary:
    """Validate CIDs, hashes, schemas, ranges, and complete posting coverage."""

    selected = config or CVEfixesBM25LayoutConfig()
    if not isinstance(selected, CVEfixesBM25LayoutConfig):
        raise CVEfixesBM25LayoutError(
            "config must be CVEfixesBM25LayoutConfig"
        )
    root = Path(output_dir).expanduser().resolve()
    if root.is_symlink() or not root.is_dir():
        raise CVEfixesBM25LayoutError(
            "BM25 output directory does not exist"
        )
    document_index_path, document_meta = _read_index(
        root, "bm25_document_chunks.parquet", postings=False
    )
    keyword_index_path, posting_meta = _read_index(
        root, "bm25_keyword_shards.parquet", postings=True
    )
    documents, document_paths = _validate_document_shards(
        root, document_meta, selected
    )
    stats, posting_paths = _validate_posting_shards(
        root, posting_meta, documents, selected
    )
    actual_document_paths = {
        path.relative_to(root).as_posix()
        for path in (root / "data" / "bm25" / "documents").glob(
            "*.parquet"
        )
        if path.is_file() and not path.is_symlink()
    }
    actual_posting_paths = {
        path.relative_to(root).as_posix()
        for path in (root / "data" / "bm25" / "postings").glob(
            "*.parquet"
        )
        if path.is_file() and not path.is_symlink()
    }
    if (
        document_paths != actual_document_paths
        or posting_paths != actual_posting_paths
    ):
        raise CVEfixesBM25LayoutError(
            "BM25 meta-index pointers do not cover data shards exactly"
        )
    return CVEfixesBM25LayoutSummary(
        output_dir=str(root),
        document_count=len(documents),
        document_shard_count=len(document_meta),
        posting_count=stats["posting_count"],
        posting_row_count=stats["posting_row_count"],
        posting_shard_count=len(posting_meta),
        term_count=stats["term_count"],
        token_instance_count=stats["token_instance_count"],
        average_document_length=(
            sum(int(row["document_length"]) for row in documents)
            / len(documents)
        ),
        document_index=_file_descriptor(
            document_index_path,
            root=root,
            row_count=len(document_meta),
        ),
        keyword_index=_file_descriptor(
            keyword_index_path,
            root=root,
            row_count=len(posting_meta),
        ),
        config=selected,
    )


__all__ = [
    "BM25ArtifactDescriptor",
    "CVEFIXES_BM25_TOKENIZER",
    "CVEFIXES_HF_BM25_DOCUMENT_SCHEMA_VERSION",
    "CVEFIXES_HF_BM25_LAYOUT_SCHEMA_VERSION",
    "CVEFIXES_HF_BM25_POSTING_SCHEMA_VERSION",
    "CVEFIXES_HF_META_SCHEMA_VERSION",
    "CVEfixesBM25LayoutConfig",
    "CVEfixesBM25LayoutError",
    "CVEfixesBM25LayoutSummary",
    "build_cvefixes_bm25_hf_layout",
    "tokenize_cvefixes_bm25",
    "validate_cvefixes_bm25_hf_layout",
]
