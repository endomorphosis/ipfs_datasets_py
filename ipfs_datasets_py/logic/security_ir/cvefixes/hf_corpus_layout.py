"""Deterministic, remotely indexable CVEfixes Hugging Face corpus shards.

This module owns only the corpus portion of the complete CVEfixes Security IR
release:

* normalized retrieval rows are written below ``data/corpus``;
* every physical shard is bound by ``indexes/corpus_chunks.parquet``;
* document indices remain dense across shard boundaries; and
* all identities, hashes, schemas, authority flags, and pointers are verified
  before a build is returned to its caller.

The builder is deliberately independent of the graph, BM25, vector, release,
and publication modules.  It stages its files separately and replaces only the
corpus paths it owns, allowing a complete release builder to compose the
layouts without hidden cross-module writes.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.identity import cid_v1_from_digest


CVEFIXES_HF_CORPUS_LAYOUT_SCHEMA_VERSION: Final = (
    "cvefixes-hf-corpus-layout/v1"
)
CVEFIXES_HF_CORPUS_SCHEMA_VERSION: Final = "cvefixes-hf-corpus/v1"
CVEFIXES_HF_CORPUS_META_SCHEMA_VERSION: Final = (
    "cvefixes-hf-shard-meta/v1"
)

CORPUS_COLUMNS: Final[tuple[str, ...]] = (
    "document_index",
    "entry_cid",
    "node_cid",
    "title",
    "text",
    "partition",
    "shard_key",
    "kind",
    "authority",
    "source_cids",
    "cwes",
    "languages",
    "code_facts",
    "actions",
    "effects",
    "policies",
    "graph_node",
    "grants_execution_authority",
    "text_sha256",
    "schema_version",
)
CORPUS_META_COLUMNS: Final[tuple[str, ...]] = (
    "cid",
    "end_document_index",
    "first_key",
    "kind",
    "last_key",
    "relative_path",
    "row_count",
    "schema_version",
    "sha256",
    "shard_id",
    "size_bytes",
    "start_document_index",
)

CORPUS_CONFIG_NAME: Final = "corpus"
CORPUS_INDEX_CONFIG_NAME: Final = "corpus_chunk_index"
CORPUS_DATA_PATTERN: Final = "data/corpus/*.parquet"
CORPUS_INDEX_PATH: Final = "indexes/corpus_chunks.parquet"
PARQUET_MEDIA_TYPE: Final = "application/vnd.apache.parquet"
PARQUET_COMPRESSION: Final = "zstd"
PARQUET_COMPRESSION_LEVEL: Final = 6

DEFAULT_MAX_DOCUMENTS: Final = 250_000
DEFAULT_MAX_ROWS_PER_SHARD: Final = 4_096
DEFAULT_MAX_SHARDS: Final = 4_096
DEFAULT_MAX_TEXT_CHARACTERS: Final = 4_096
DEFAULT_MAX_TEXT_UTF8_BYTES: Final = 16_384
DEFAULT_MAX_SHARD_BYTES: Final = 128 * 1024 * 1024
DEFAULT_MAX_LIST_ITEMS: Final = 128
DEFAULT_MAX_LIST_ITEM_CHARACTERS: Final = 512

_CID_RE: Final = re.compile(r"b[a-z2-7]{58}")
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
_PART_RE: Final = re.compile(r"part-(\d{6})\.parquet")
_INT32_MAX: Final = 2_147_483_647
_CID_PREFIX: Final = bytes((0x01, 0x55, 0x12, 0x20))
_AUTHORITIES: Final = frozenset({"candidate", "non_authoritative"})
_LIST_COLUMNS: Final = (
    "source_cids",
    "cwes",
    "languages",
    "code_facts",
    "actions",
    "effects",
    "policies",
)


class CVEfixesHFCorpusLayoutError(ValueError):
    """Raised when corpus inputs or staged artifacts violate the layout."""


class CVEfixesHFCorpusIntegrityError(CVEfixesHFCorpusLayoutError):
    """Raised when a corpus artifact differs from its content binding."""


class CVEfixesHFCorpusLimitError(CVEfixesHFCorpusLayoutError):
    """Raised when a corpus input or artifact exceeds a release bound."""


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise CVEfixesHFCorpusLayoutError(
            f"{label} must be a positive integer"
        )
    return value


@dataclass(frozen=True, slots=True)
class CVEfixesHFCorpusLayoutConfig:
    """Explicit resource and physical-layout bounds for the corpus."""

    max_documents: int = DEFAULT_MAX_DOCUMENTS
    max_rows_per_shard: int = DEFAULT_MAX_ROWS_PER_SHARD
    max_shards: int = DEFAULT_MAX_SHARDS
    max_text_characters: int = DEFAULT_MAX_TEXT_CHARACTERS
    max_text_utf8_bytes: int = DEFAULT_MAX_TEXT_UTF8_BYTES
    max_shard_bytes: int = DEFAULT_MAX_SHARD_BYTES
    max_list_items: int = DEFAULT_MAX_LIST_ITEMS
    max_list_item_characters: int = DEFAULT_MAX_LIST_ITEM_CHARACTERS
    compression: str = PARQUET_COMPRESSION
    compression_level: int = PARQUET_COMPRESSION_LEVEL
    schema_version: str = CVEFIXES_HF_CORPUS_LAYOUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "max_documents",
            "max_rows_per_shard",
            "max_shards",
            "max_text_characters",
            "max_text_utf8_bytes",
            "max_shard_bytes",
            "max_list_items",
            "max_list_item_characters",
            "compression_level",
        ):
            _positive_int(getattr(self, name), name)
        if self.max_documents > _INT32_MAX:
            raise CVEfixesHFCorpusLimitError(
                "max_documents exceeds the int32 document-index limit"
            )
        if self.max_rows_per_shard > _INT32_MAX:
            raise CVEfixesHFCorpusLimitError(
                "max_rows_per_shard exceeds the int32 limit"
            )
        if self.max_shard_bytes > DEFAULT_MAX_SHARD_BYTES:
            raise CVEfixesHFCorpusLimitError(
                "max_shard_bytes exceeds the publisher artifact limit"
            )
        if self.compression != PARQUET_COMPRESSION:
            raise CVEfixesHFCorpusLayoutError(
                "CVEfixes Hugging Face corpus shards require zstd"
            )
        if self.schema_version != CVEFIXES_HF_CORPUS_LAYOUT_SCHEMA_VERSION:
            raise CVEfixesHFCorpusLayoutError(
                "unsupported corpus layout schema version"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "compression": self.compression,
            "compression_level": self.compression_level,
            "max_documents": self.max_documents,
            "max_list_item_characters": self.max_list_item_characters,
            "max_list_items": self.max_list_items,
            "max_rows_per_shard": self.max_rows_per_shard,
            "max_shard_bytes": self.max_shard_bytes,
            "max_shards": self.max_shards,
            "max_text_characters": self.max_text_characters,
            "max_text_utf8_bytes": self.max_text_utf8_bytes,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class CorpusArtifactDescriptor:
    """Content address and physical facts for one corpus Parquet file."""

    relative_path: str
    sha256: str
    cid: str
    size_bytes: int
    row_count: int
    config_name: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative_path)
        if (
            not self.relative_path
            or path.is_absolute()
            or path.as_posix() != self.relative_path
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise CVEfixesHFCorpusLayoutError(
                "corpus descriptor has an unsafe path"
            )
        if not _SHA256_RE.fullmatch(self.sha256):
            raise CVEfixesHFCorpusLayoutError(
                "corpus descriptor has an invalid SHA-256"
            )
        _validate_cid(self.cid, "corpus descriptor CID")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise CVEfixesHFCorpusLayoutError(
                "corpus descriptor size must be positive"
            )
        if type(self.row_count) is not int or self.row_count <= 0:
            raise CVEfixesHFCorpusLayoutError(
                "corpus descriptor row_count must be positive"
            )
        expected_config = (
            CORPUS_INDEX_CONFIG_NAME
            if self.relative_path == CORPUS_INDEX_PATH
            else CORPUS_CONFIG_NAME
        )
        if self.config_name != expected_config:
            raise CVEfixesHFCorpusLayoutError(
                "corpus descriptor config does not match its path"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return the compact descriptor used in ``manifest.indexes``."""

        return {
            "cid": self.cid,
            "config_name": self.config_name,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    def to_artifact_dict(self) -> dict[str, Any]:
        """Return the canonical descriptor used in ``manifest.artifacts``."""

        return {
            "byte_length": self.size_bytes,
            "config_name": self.config_name,
            "content_id": self.cid,
            "media_type": PARQUET_MEDIA_TYPE,
            "path": self.relative_path,
            "row_count": self.row_count,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class CVEfixesHFCorpusLayoutSummary:
    """Manifest-ready result of building or verifying the corpus layout."""

    output_dir: str
    corpus_rows: int
    corpus_chunks: int
    first_entry_cid: str
    last_entry_cid: str
    data_shards: tuple[CorpusArtifactDescriptor, ...]
    corpus_index: CorpusArtifactDescriptor
    config: CVEfixesHFCorpusLayoutConfig
    schema_version: str = CVEFIXES_HF_CORPUS_LAYOUT_SCHEMA_VERSION

    @property
    def counts(self) -> dict[str, int]:
        return {
            "corpus_chunks": self.corpus_chunks,
            "corpus_rows": self.corpus_rows,
        }

    @property
    def configs(self) -> dict[str, str]:
        return {
            CORPUS_CONFIG_NAME: CORPUS_DATA_PATTERN,
            CORPUS_INDEX_CONFIG_NAME: CORPUS_INDEX_PATH,
        }

    @property
    def indexes(self) -> dict[str, dict[str, Any]]:
        return {"corpus_chunks": self.corpus_index.to_dict()}

    @property
    def artifacts(self) -> tuple[CorpusArtifactDescriptor, ...]:
        return (*self.data_shards, self.corpus_index)

    @property
    def artifact_inventory(self) -> tuple[dict[str, Any], ...]:
        return tuple(item.to_artifact_dict() for item in self.artifacts)

    def to_manifest_fragment(self) -> dict[str, Any]:
        """Return fields that can be merged into the complete release manifest."""

        return {
            "configs": self.configs,
            "counts": self.counts,
            "indexes": self.indexes,
            "parquet": {
                "compression": self.config.compression,
                "compression_level": self.config.compression_level,
                "corpus_max_rows_per_chunk": (
                    self.config.max_rows_per_shard
                ),
                "corpus_schema_version": (
                    CVEFIXES_HF_CORPUS_SCHEMA_VERSION
                ),
            },
        }


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - release dependency
        raise CVEfixesHFCorpusLayoutError(
            "pyarrow is required for the CVEfixes corpus layout"
        ) from exc
    return pa, pq


def _corpus_schema(pa: Any) -> Any:
    list_string = pa.list_(pa.string())
    return pa.schema(
        [
            ("document_index", pa.int32(), False),
            ("entry_cid", pa.string(), False),
            ("node_cid", pa.string(), False),
            ("title", pa.string(), False),
            ("text", pa.large_string(), False),
            ("partition", pa.string(), False),
            ("shard_key", pa.string(), False),
            ("kind", pa.string(), False),
            ("authority", pa.string(), False),
            ("source_cids", list_string, False),
            ("cwes", list_string, False),
            ("languages", list_string, False),
            ("code_facts", list_string, False),
            ("actions", list_string, False),
            ("effects", list_string, False),
            ("policies", list_string, False),
            ("graph_node", pa.bool_(), False),
            ("grants_execution_authority", pa.bool_(), False),
            ("text_sha256", pa.string(), False),
            ("schema_version", pa.string(), False),
        ],
        metadata={
            b"primary_key": b"entry_cid",
            b"schema_version": (
                CVEFIXES_HF_CORPUS_SCHEMA_VERSION.encode("ascii")
            ),
        },
    )


def _meta_schema(pa: Any) -> Any:
    return pa.schema(
        [
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
        ],
        metadata={
            b"schema_version": (
                CVEFIXES_HF_CORPUS_META_SCHEMA_VERSION.encode("ascii")
            )
        },
    )


def _validate_cid(value: Any, label: str) -> str:
    if not isinstance(value, str) or _CID_RE.fullmatch(value) is None:
        raise CVEfixesHFCorpusLayoutError(
            f"{label} must be a CIDv1(raw, sha2-256) string"
        )
    encoded = value[1:]
    padded = encoded.upper() + "=" * ((8 - len(encoded) % 8) % 8)
    try:
        payload = base64.b32decode(padded, casefold=False)
    except (ValueError, base64.binascii.Error) as exc:
        raise CVEfixesHFCorpusLayoutError(
            f"{label} is not valid base32 CID text"
        ) from exc
    if (
        len(payload) != len(_CID_PREFIX) + 32
        or payload[: len(_CID_PREFIX)] != _CID_PREFIX
        or cid_v1_from_digest(payload[len(_CID_PREFIX) :]) != value
    ):
        raise CVEfixesHFCorpusLayoutError(
            f"{label} must use the release CID profile"
        )
    return value


def _clean_text(
    value: Any,
    label: str,
    *,
    maximum_characters: int,
    maximum_utf8_bytes: int | None = None,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise CVEfixesHFCorpusLayoutError(f"{label} must be a string")
    if (
        "\x00" in value
        or len(value) > maximum_characters
        or (not allow_empty and not value)
        or (value and value != value.strip())
    ):
        raise CVEfixesHFCorpusLayoutError(
            f"{label} must be bounded clean text"
        )
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CVEfixesHFCorpusLayoutError(
            f"{label} is not valid UTF-8 text"
        ) from exc
    if maximum_utf8_bytes is not None and len(encoded) > maximum_utf8_bytes:
        raise CVEfixesHFCorpusLimitError(
            f"{label} exceeds its UTF-8 byte limit"
        )
    return value


def _string_list(
    value: Any,
    label: str,
    *,
    config: CVEfixesHFCorpusLayoutConfig,
    cids: bool = False,
    require_nonempty: bool = False,
) -> list[str]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise CVEfixesHFCorpusLayoutError(
            f"{label} must be a sequence of strings"
        )
    if len(value) > config.max_list_items:
        raise CVEfixesHFCorpusLimitError(
            f"{label} exceeds {config.max_list_items} items"
        )
    result = [
        (
            _validate_cid(item, f"{label} item")
            if cids
            else _clean_text(
                item,
                f"{label} item",
                maximum_characters=config.max_list_item_characters,
            )
        )
        for item in value
    ]
    if require_nonempty and not result:
        raise CVEfixesHFCorpusLayoutError(
            f"{label} must not be empty"
        )
    if len(result) != len(set(result)):
        raise CVEfixesHFCorpusLayoutError(
            f"{label} must not contain duplicate values"
        )
    expected = sorted(result, key=lambda item: (item.casefold(), item))
    if result != expected:
        raise CVEfixesHFCorpusLayoutError(
            f"{label} must be in canonical sorted order"
        )
    return result


def _strict_row_fields(row: Mapping[str, Any], position: int) -> None:
    actual = set(row)
    expected = set(CORPUS_COLUMNS)
    if actual != expected or any(not isinstance(key, str) for key in row):
        missing = sorted(expected - actual)
        extra = sorted(
            (key for key in actual - expected),
            key=lambda item: repr(item),
        )
        detail: list[str] = []
        if missing:
            detail.append(f"missing: {', '.join(missing)}")
        if extra:
            detail.append(
                "unexpected: " + ", ".join(repr(item) for item in extra)
            )
        raise CVEfixesHFCorpusLayoutError(
            f"corpus row {position} fields differ"
            + (f" ({'; '.join(detail)})" if detail else "")
        )


def _normalize_row(
    raw: Mapping[str, Any],
    position: int,
    config: CVEfixesHFCorpusLayoutConfig,
) -> dict[str, Any]:
    _strict_row_fields(raw, position)
    document_index = raw["document_index"]
    if (
        type(document_index) is not int
        or document_index < 0
        or document_index > _INT32_MAX
    ):
        raise CVEfixesHFCorpusLayoutError(
            "document_index must be a non-negative int32"
        )
    entry_cid = _validate_cid(
        raw["entry_cid"], f"corpus row {position} entry_cid"
    )
    node_cid = _validate_cid(
        raw["node_cid"], f"corpus row {position} node_cid"
    )
    title = _clean_text(
        raw["title"],
        f"corpus row {position} title",
        maximum_characters=4_096,
        maximum_utf8_bytes=16_384,
    )
    text = _clean_text(
        raw["text"],
        f"corpus row {position} text",
        maximum_characters=config.max_text_characters,
        maximum_utf8_bytes=config.max_text_utf8_bytes,
        allow_empty=True,
    )
    text_sha256 = raw["text_sha256"]
    expected_text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if (
        not isinstance(text_sha256, str)
        or _SHA256_RE.fullmatch(text_sha256) is None
        or text_sha256 != expected_text_sha256
    ):
        raise CVEfixesHFCorpusIntegrityError(
            f"corpus row {position} text_sha256 differs from text"
        )
    values = {
        name: _clean_text(
            raw[name],
            f"corpus row {position} {name}",
            maximum_characters=512,
            maximum_utf8_bytes=2_048,
        )
        for name in ("partition", "shard_key", "kind", "authority")
    }
    if values["authority"] not in _AUTHORITIES:
        raise CVEfixesHFCorpusLayoutError(
            "corpus authority must be candidate or non_authoritative"
        )
    graph_node = raw["graph_node"]
    if type(graph_node) is not bool:
        raise CVEfixesHFCorpusLayoutError(
            "graph_node must be a boolean"
        )
    if raw["grants_execution_authority"] is not False:
        raise CVEfixesHFCorpusLayoutError(
            "corpus rows can never grant execution authority"
        )
    if raw["schema_version"] != CVEFIXES_HF_CORPUS_SCHEMA_VERSION:
        raise CVEfixesHFCorpusLayoutError(
            "unsupported corpus row schema version"
        )
    lists = {
        name: _string_list(
            raw[name],
            f"corpus row {position} {name}",
            config=config,
            cids=name == "source_cids",
            require_nonempty=name == "source_cids",
        )
        for name in _LIST_COLUMNS
    }
    return {
        "document_index": document_index,
        "entry_cid": entry_cid,
        "node_cid": node_cid,
        "title": title,
        "text": text,
        "partition": values["partition"],
        "shard_key": values["shard_key"],
        "kind": values["kind"],
        "authority": values["authority"],
        "source_cids": lists["source_cids"],
        "cwes": lists["cwes"],
        "languages": lists["languages"],
        "code_facts": lists["code_facts"],
        "actions": lists["actions"],
        "effects": lists["effects"],
        "policies": lists["policies"],
        "graph_node": graph_node,
        "grants_execution_authority": False,
        "text_sha256": text_sha256,
        "schema_version": CVEFIXES_HF_CORPUS_SCHEMA_VERSION,
    }


def _normalize_rows(
    rows: Sequence[Mapping[str, Any]],
    config: CVEfixesHFCorpusLayoutConfig,
) -> tuple[dict[str, Any], ...]:
    if isinstance(rows, (str, bytes, bytearray)) or not isinstance(
        rows, Sequence
    ):
        raise CVEfixesHFCorpusLayoutError(
            "corpus rows must be a sequence of mappings"
        )
    if not rows:
        raise CVEfixesHFCorpusLayoutError(
            "corpus rows must not be empty"
        )
    if len(rows) > config.max_documents:
        raise CVEfixesHFCorpusLimitError(
            "corpus rows exceed max_documents"
        )
    normalized: list[dict[str, Any]] = []
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise CVEfixesHFCorpusLayoutError(
                f"corpus row {position} must be a mapping"
            )
        normalized.append(_normalize_row(row, position, config))
    normalized.sort(key=lambda row: int(row["document_index"]))
    if [row["document_index"] for row in normalized] != list(
        range(len(normalized))
    ):
        raise CVEfixesHFCorpusLayoutError(
            "document_index values must be dense from zero"
        )
    entry_cids = [str(row["entry_cid"]) for row in normalized]
    if len(entry_cids) != len(set(entry_cids)):
        raise CVEfixesHFCorpusLayoutError(
            "corpus rows contain duplicate entry CIDs"
        )
    return tuple(normalized)


def _write_parquet(
    path: Path,
    table: Any,
    config: CVEfixesHFCorpusLayoutConfig,
    *,
    enforce_row_limit: bool,
) -> None:
    _, pq = _pyarrow()
    if table.num_rows <= 0:
        raise CVEfixesHFCorpusLayoutError(
            f"cannot write an empty Parquet file: {path.name}"
        )
    if enforce_row_limit and table.num_rows > config.max_rows_per_shard:
        raise CVEfixesHFCorpusLimitError(
            f"corpus shard exceeds its row limit: {path.name}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    try:
        pq.write_table(
            table,
            partial,
            compression=config.compression,
            compression_level=config.compression_level,
            data_page_version="1.0",
            row_group_size=min(
                config.max_rows_per_shard, max(1, table.num_rows)
            ),
            use_dictionary=False,
            version="2.6",
            write_statistics=True,
        )
        _validate_parquet_encoding(
            partial,
            max_rows=(
                config.max_rows_per_shard
                if enforce_row_limit
                else None
            ),
        )
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)


def _validate_parquet_encoding(
    path: Path,
    *,
    max_rows: int | None,
) -> None:
    _, pq = _pyarrow()
    try:
        parquet = pq.ParquetFile(path)
    except Exception as exc:
        raise CVEfixesHFCorpusIntegrityError(
            f"corpus Parquet is unreadable: {path.name}"
        ) from exc
    if (
        max_rows is not None
        and parquet.metadata.num_rows > max_rows
    ):
        raise CVEfixesHFCorpusLimitError(
            f"corpus Parquet exceeds its row limit: {path.name}"
        )
    compressions = {
        parquet.metadata.row_group(group).column(column).compression
        for group in range(parquet.num_row_groups)
        for column in range(
            parquet.metadata.row_group(group).num_columns
        )
    }
    if compressions and compressions != {"ZSTD"}:
        raise CVEfixesHFCorpusIntegrityError(
            f"corpus Parquet is not uniformly ZSTD-compressed: {path.name}"
        )


def _descriptor(
    path: Path,
    *,
    root: Path,
    row_count: int,
    config_name: str,
) -> CorpusArtifactDescriptor:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise CVEfixesHFCorpusIntegrityError(
            f"cannot read corpus artifact: {path.name}"
        ) from exc
    digest = hashlib.sha256(content).digest()
    return CorpusArtifactDescriptor(
        relative_path=path.relative_to(root).as_posix(),
        sha256=digest.hex(),
        cid=cid_v1_from_digest(digest),
        size_bytes=len(content),
        row_count=row_count,
        config_name=config_name,
    )


def _meta_row(
    descriptor: CorpusArtifactDescriptor,
    *,
    shard_id: int,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "cid": descriptor.cid,
        "end_document_index": int(rows[-1]["document_index"]),
        "first_key": str(rows[0]["entry_cid"]),
        "kind": CORPUS_CONFIG_NAME,
        "last_key": str(rows[-1]["entry_cid"]),
        "relative_path": descriptor.relative_path,
        "row_count": descriptor.row_count,
        "schema_version": CVEFIXES_HF_CORPUS_META_SCHEMA_VERSION,
        "sha256": descriptor.sha256,
        "shard_id": shard_id,
        "size_bytes": descriptor.size_bytes,
        "start_document_index": int(rows[0]["document_index"]),
    }


def _write_data_shards(
    rows: Sequence[Mapping[str, Any]],
    root: Path,
    config: CVEfixesHFCorpusLayoutConfig,
) -> tuple[list[dict[str, Any]], tuple[CorpusArtifactDescriptor, ...]]:
    pa, _ = _pyarrow()
    destination = root / "data" / "corpus"
    destination.mkdir(parents=True, exist_ok=True)
    metadata: list[dict[str, Any]] = []
    descriptors: list[CorpusArtifactDescriptor] = []

    def write_group(group: Sequence[Mapping[str, Any]]) -> None:
        if len(descriptors) >= config.max_shards:
            raise CVEfixesHFCorpusLimitError(
                "corpus requires more than max_shards"
            )
        shard_id = len(descriptors)
        path = destination / f"part-{shard_id:06d}.parquet"
        table = pa.Table.from_pylist(
            [dict(row) for row in group],
            schema=_corpus_schema(pa),
        )
        _write_parquet(
            path,
            table,
            config,
            enforce_row_limit=True,
        )
        if path.stat().st_size > config.max_shard_bytes:
            path.unlink()
            if len(group) == 1:
                raise CVEfixesHFCorpusLimitError(
                    "one corpus row exceeds max_shard_bytes"
                )
            midpoint = len(group) // 2
            write_group(group[:midpoint])
            write_group(group[midpoint:])
            return
        descriptor = _descriptor(
            path,
            root=root,
            row_count=len(group),
            config_name=CORPUS_CONFIG_NAME,
        )
        descriptors.append(descriptor)
        metadata.append(
            _meta_row(
                descriptor,
                shard_id=shard_id,
                rows=group,
            )
        )

    for start in range(0, len(rows), config.max_rows_per_shard):
        write_group(rows[start : start + config.max_rows_per_shard])
    return metadata, tuple(descriptors)


def _write_meta_index(
    rows: Sequence[Mapping[str, Any]],
    root: Path,
    config: CVEfixesHFCorpusLayoutConfig,
) -> CorpusArtifactDescriptor:
    pa, _ = _pyarrow()
    path = root / CORPUS_INDEX_PATH
    table = pa.Table.from_pylist(list(rows), schema=_meta_schema(pa))
    _write_parquet(
        path,
        table,
        config,
        enforce_row_limit=False,
    )
    if path.stat().st_size > config.max_shard_bytes:
        path.unlink()
        raise CVEfixesHFCorpusLimitError(
            "corpus meta-index exceeds max_shard_bytes"
        )
    return _descriptor(
        path,
        root=root,
        row_count=table.num_rows,
        config_name=CORPUS_INDEX_CONFIG_NAME,
    )


def _root_path(
    value: str | Path,
    *,
    require_existing: bool,
) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_symlink():
        raise CVEfixesHFCorpusLayoutError(
            "corpus output directory must not be a symlink"
        )
    try:
        root = candidate.resolve(strict=require_existing)
    except OSError as exc:
        raise CVEfixesHFCorpusLayoutError(
            "corpus output directory does not exist"
        ) from exc
    if require_existing and not root.is_dir():
        raise CVEfixesHFCorpusLayoutError(
            "corpus output directory does not exist"
        )
    if not require_existing and root.exists() and not root.is_dir():
        raise CVEfixesHFCorpusLayoutError(
            "corpus output must be a directory"
        )
    return root


def _assert_safe_owned_targets(output: Path) -> None:
    data_parent = output / "data"
    index_parent = output / "indexes"
    target = data_parent / "corpus"
    index = output / CORPUS_INDEX_PATH
    for parent in (data_parent, index_parent):
        if parent.is_symlink() or (
            parent.exists() and not parent.is_dir()
        ):
            raise CVEfixesHFCorpusLayoutError(
                f"corpus parent path is unsafe: {parent}"
            )
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise CVEfixesHFCorpusLayoutError(
            "owned corpus data path is unsafe"
        )
    if target.exists():
        for item in target.iterdir():
            if (
                item.is_symlink()
                or not item.is_file()
                or _PART_RE.fullmatch(item.name) is None
            ):
                raise CVEfixesHFCorpusLayoutError(
                    f"unexpected file in owned corpus directory: {item}"
                )
    if index.is_symlink() or (index.exists() and not index.is_file()):
        raise CVEfixesHFCorpusLayoutError(
            "owned corpus meta-index path is unsafe"
        )


def _install_staged_files(temporary: Path, output: Path) -> None:
    """Replace only the two paths owned by this standalone layout."""

    _assert_safe_owned_targets(output)
    data_parent = output / "data"
    index_parent = output / "indexes"
    data_parent.mkdir(parents=True, exist_ok=True)
    index_parent.mkdir(parents=True, exist_ok=True)
    staged_data = temporary / "data" / "corpus"
    staged_index = temporary / CORPUS_INDEX_PATH
    target_data = data_parent / "corpus"
    target_index = output / CORPUS_INDEX_PATH
    backup_root = temporary / ".replaced"
    backup_data = backup_root / "corpus"
    backup_index = backup_root / "corpus_chunks.parquet"
    backup_root.mkdir()
    had_data = target_data.exists()
    had_index = target_index.exists()
    installed_data = False
    installed_index = False
    try:
        if had_data:
            os.replace(target_data, backup_data)
        if had_index:
            os.replace(target_index, backup_index)
        os.replace(staged_data, target_data)
        installed_data = True
        os.replace(staged_index, target_index)
        installed_index = True
    except Exception:
        if installed_index and target_index.exists():
            os.replace(target_index, staged_index)
        if installed_data and target_data.exists():
            os.replace(target_data, staged_data)
        if had_index and backup_index.exists():
            os.replace(backup_index, target_index)
        if had_data and backup_data.exists():
            os.replace(backup_data, target_data)
        raise
    finally:
        if installed_data and installed_index:
            shutil.rmtree(backup_root, ignore_errors=True)


def build_cvefixes_hf_corpus_layout(
    corpus_rows: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
    *,
    config: CVEfixesHFCorpusLayoutConfig | None = None,
) -> CVEfixesHFCorpusLayoutSummary:
    """Build, install, and verify the standalone corpus release layout."""

    selected = config or CVEfixesHFCorpusLayoutConfig()
    if not isinstance(selected, CVEfixesHFCorpusLayoutConfig):
        raise CVEfixesHFCorpusLayoutError(
            "config must be CVEfixesHFCorpusLayoutConfig"
        )
    rows = _normalize_rows(corpus_rows, selected)
    output = _root_path(output_dir, require_existing=False)
    output.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".cvefixes-corpus-", dir=output)
    )
    try:
        metadata, _ = _write_data_shards(rows, temporary, selected)
        _write_meta_index(metadata, temporary, selected)
        staged = validate_cvefixes_hf_corpus_layout(
            temporary, config=selected
        )
        _install_staged_files(temporary, output)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    installed = validate_cvefixes_hf_corpus_layout(
        output, config=selected
    )
    if (
        installed.counts != staged.counts
        or [item.sha256 for item in installed.artifacts]
        != [item.sha256 for item in staged.artifacts]
    ):
        raise CVEfixesHFCorpusIntegrityError(
            "installed corpus layout differs from completed staging"
        )
    return installed


def _read_meta_index(
    root: Path,
    config: CVEfixesHFCorpusLayoutConfig,
) -> tuple[Path, list[dict[str, Any]]]:
    _, pq = _pyarrow()
    path = root / CORPUS_INDEX_PATH
    if path.is_symlink() or not path.is_file():
        raise CVEfixesHFCorpusIntegrityError(
            "corpus_chunks meta-index is missing"
        )
    if path.stat().st_size > config.max_shard_bytes:
        raise CVEfixesHFCorpusLimitError(
            "corpus meta-index exceeds max_shard_bytes"
        )
    _validate_parquet_encoding(path, max_rows=None)
    try:
        table = pq.read_table(path)
    except Exception as exc:
        raise CVEfixesHFCorpusIntegrityError(
            "cannot read corpus_chunks meta-index"
        ) from exc
    expected = _meta_schema(_pyarrow()[0])
    if (
        tuple(table.column_names) != CORPUS_META_COLUMNS
        or table.schema.remove_metadata() != expected.remove_metadata()
        or dict(table.schema.metadata or {})
        != dict(expected.metadata or {})
        or table.num_rows <= 0
        or table.num_rows > config.max_shards
    ):
        raise CVEfixesHFCorpusIntegrityError(
            "corpus_chunks meta-index schema is malformed"
        )
    return path, [dict(row) for row in table.to_pylist()]


def _verify_meta_row(
    root: Path,
    row: Mapping[str, Any],
    shard_id: int,
    config: CVEfixesHFCorpusLayoutConfig,
) -> tuple[Path, CorpusArtifactDescriptor]:
    if set(row) != set(CORPUS_META_COLUMNS):
        raise CVEfixesHFCorpusIntegrityError(
            "corpus meta-index row fields differ"
        )
    expected_relative = f"data/corpus/part-{shard_id:06d}.parquet"
    if (
        row.get("relative_path") != expected_relative
        or row.get("shard_id") != shard_id
        or row.get("kind") != CORPUS_CONFIG_NAME
        or row.get("schema_version")
        != CVEFIXES_HF_CORPUS_META_SCHEMA_VERSION
        or type(row.get("row_count")) is not int
        or not 1 <= row["row_count"] <= config.max_rows_per_shard
        or type(row.get("start_document_index")) is not int
        or type(row.get("end_document_index")) is not int
        or type(row.get("size_bytes")) is not int
        or not 0 < row["size_bytes"] <= config.max_shard_bytes
        or not isinstance(row.get("sha256"), str)
        or _SHA256_RE.fullmatch(row["sha256"]) is None
    ):
        raise CVEfixesHFCorpusIntegrityError(
            f"corpus meta-index row {shard_id} is malformed"
        )
    _validate_cid(row.get("cid"), f"corpus meta row {shard_id} CID")
    _validate_cid(
        row.get("first_key"),
        f"corpus meta row {shard_id} first_key",
    )
    _validate_cid(
        row.get("last_key"),
        f"corpus meta row {shard_id} last_key",
    )
    path = root.joinpath(*PurePosixPath(expected_relative).parts)
    if path.is_symlink() or not path.is_file():
        raise CVEfixesHFCorpusIntegrityError(
            f"corpus shard is missing: {expected_relative}"
        )
    descriptor = _descriptor(
        path,
        root=root,
        row_count=row["row_count"],
        config_name=CORPUS_CONFIG_NAME,
    )
    if (
        descriptor.cid != row["cid"]
        or descriptor.sha256 != row["sha256"]
        or descriptor.size_bytes != row["size_bytes"]
    ):
        raise CVEfixesHFCorpusIntegrityError(
            f"corpus shard descriptor differs: {expected_relative}"
        )
    return path, descriptor


def _read_verified_rows(
    root: Path,
    metadata: Sequence[Mapping[str, Any]],
    config: CVEfixesHFCorpusLayoutConfig,
) -> tuple[tuple[dict[str, Any], ...], tuple[CorpusArtifactDescriptor, ...]]:
    _, pq = _pyarrow()
    expected_schema = _corpus_schema(_pyarrow()[0])
    rows: list[dict[str, Any]] = []
    descriptors: list[CorpusArtifactDescriptor] = []
    expected_document_index = 0
    for shard_id, meta in enumerate(metadata):
        path, descriptor = _verify_meta_row(
            root, meta, shard_id, config
        )
        _validate_parquet_encoding(
            path, max_rows=config.max_rows_per_shard
        )
        try:
            table = pq.read_table(path)
        except Exception as exc:
            raise CVEfixesHFCorpusIntegrityError(
                f"cannot read corpus shard: {descriptor.relative_path}"
            ) from exc
        if (
            tuple(table.column_names) != CORPUS_COLUMNS
            or table.schema.remove_metadata()
            != expected_schema.remove_metadata()
            or dict(table.schema.metadata or {})
            != dict(expected_schema.metadata or {})
            or table.num_rows != descriptor.row_count
        ):
            raise CVEfixesHFCorpusIntegrityError(
                f"corpus shard schema differs: {descriptor.relative_path}"
            )
        shard_rows = [dict(row) for row in table.to_pylist()]
        normalized = tuple(
            _normalize_row(row, position, config)
            for position, row in enumerate(shard_rows)
        )
        if tuple(shard_rows) != normalized:
            raise CVEfixesHFCorpusIntegrityError(
                f"corpus shard rows are not normalized: "
                f"{descriptor.relative_path}"
            )
        documents = [int(row["document_index"]) for row in shard_rows]
        expected_documents = list(
            range(
                expected_document_index,
                expected_document_index + len(shard_rows),
            )
        )
        if (
            documents != expected_documents
            or meta["start_document_index"] != documents[0]
            or meta["end_document_index"] != documents[-1]
            or meta["first_key"] != shard_rows[0]["entry_cid"]
            or meta["last_key"] != shard_rows[-1]["entry_cid"]
        ):
            raise CVEfixesHFCorpusIntegrityError(
                f"corpus shard ranges differ: {descriptor.relative_path}"
            )
        expected_document_index += len(shard_rows)
        rows.extend(shard_rows)
        descriptors.append(descriptor)
    if len(rows) > config.max_documents:
        raise CVEfixesHFCorpusLimitError(
            "installed corpus exceeds max_documents"
        )
    if len({str(row["entry_cid"]) for row in rows}) != len(rows):
        raise CVEfixesHFCorpusIntegrityError(
            "installed corpus repeats an entry CID"
        )
    return tuple(rows), tuple(descriptors)


def _actual_data_paths(root: Path) -> set[str]:
    directory = root / "data" / "corpus"
    if directory.is_symlink() or not directory.is_dir():
        raise CVEfixesHFCorpusIntegrityError(
            "corpus data directory is missing"
        )
    result: set[str] = set()
    for path in directory.iterdir():
        if (
            path.is_symlink()
            or not path.is_file()
            or _PART_RE.fullmatch(path.name) is None
        ):
            raise CVEfixesHFCorpusIntegrityError(
                f"unexpected corpus data artifact: {path.name}"
            )
        result.add(path.relative_to(root).as_posix())
    return result


def validate_cvefixes_hf_corpus_layout(
    output_dir: str | Path,
    *,
    config: CVEfixesHFCorpusLayoutConfig | None = None,
) -> CVEfixesHFCorpusLayoutSummary:
    """Verify exact schemas, ranges, identities, hashes, and shard coverage."""

    selected = config or CVEfixesHFCorpusLayoutConfig()
    if not isinstance(selected, CVEfixesHFCorpusLayoutConfig):
        raise CVEfixesHFCorpusLayoutError(
            "config must be CVEfixesHFCorpusLayoutConfig"
        )
    root = _root_path(output_dir, require_existing=True)
    index_path, metadata = _read_meta_index(root, selected)
    rows, descriptors = _read_verified_rows(
        root, metadata, selected
    )
    pointed = {item.relative_path for item in descriptors}
    if pointed != _actual_data_paths(root):
        raise CVEfixesHFCorpusIntegrityError(
            "corpus meta-index does not cover data shards exactly"
        )
    index_descriptor = _descriptor(
        index_path,
        root=root,
        row_count=len(metadata),
        config_name=CORPUS_INDEX_CONFIG_NAME,
    )
    return CVEfixesHFCorpusLayoutSummary(
        output_dir=str(root),
        corpus_rows=len(rows),
        corpus_chunks=len(descriptors),
        first_entry_cid=str(rows[0]["entry_cid"]),
        last_entry_cid=str(rows[-1]["entry_cid"]),
        data_shards=descriptors,
        corpus_index=index_descriptor,
        config=selected,
    )


def read_cvefixes_hf_corpus_layout(
    output_dir: str | Path,
    *,
    config: CVEfixesHFCorpusLayoutConfig | None = None,
) -> tuple[Mapping[str, Any], ...]:
    """Return immutable row mappings after full local layout verification."""

    selected = config or CVEfixesHFCorpusLayoutConfig()
    validate_cvefixes_hf_corpus_layout(output_dir, config=selected)
    root = _root_path(output_dir, require_existing=True)
    _, metadata = _read_meta_index(root, selected)
    rows, _ = _read_verified_rows(root, metadata, selected)
    return tuple(MappingProxyType(dict(row)) for row in rows)


def read_cvefixes_hf_corpus_index(
    output_dir: str | Path,
    *,
    config: CVEfixesHFCorpusLayoutConfig | None = None,
) -> tuple[Mapping[str, Any], ...]:
    """Read the compact shard-routing index after verifying the full layout."""

    selected = config or CVEfixesHFCorpusLayoutConfig()
    validate_cvefixes_hf_corpus_layout(output_dir, config=selected)
    root = _root_path(output_dir, require_existing=True)
    _, rows = _read_meta_index(root, selected)
    return tuple(MappingProxyType(dict(row)) for row in rows)


# Naming aliases keep the standalone module easy to compose with both the
# ``build_cvefixes_bm25_hf_layout`` and ``build_cvefixes_hf_vector_layout``
# conventions already present in this package.
build_cvefixes_corpus_hf_layout = build_cvefixes_hf_corpus_layout
verify_cvefixes_hf_corpus_layout = validate_cvefixes_hf_corpus_layout


__all__ = [
    "CORPUS_COLUMNS",
    "CORPUS_CONFIG_NAME",
    "CORPUS_DATA_PATTERN",
    "CORPUS_INDEX_CONFIG_NAME",
    "CORPUS_INDEX_PATH",
    "CORPUS_META_COLUMNS",
    "CVEFIXES_HF_CORPUS_LAYOUT_SCHEMA_VERSION",
    "CVEFIXES_HF_CORPUS_META_SCHEMA_VERSION",
    "CVEFIXES_HF_CORPUS_SCHEMA_VERSION",
    "CVEfixesHFCorpusIntegrityError",
    "CVEfixesHFCorpusLayoutConfig",
    "CVEfixesHFCorpusLayoutError",
    "CVEfixesHFCorpusLayoutSummary",
    "CVEfixesHFCorpusLimitError",
    "CorpusArtifactDescriptor",
    "build_cvefixes_corpus_hf_layout",
    "build_cvefixes_hf_corpus_layout",
    "read_cvefixes_hf_corpus_index",
    "read_cvefixes_hf_corpus_layout",
    "validate_cvefixes_hf_corpus_layout",
    "verify_cvefixes_hf_corpus_layout",
]
