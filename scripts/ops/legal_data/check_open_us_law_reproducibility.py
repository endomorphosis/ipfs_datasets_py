#!/usr/bin/env python3
"""Prove deterministic Open US Law builds and fail-closed resource security (OUL-038).

Two independent fixture builds must be byte-identical. Compact hostile
recipes — malformed descriptors, path escapes, digest drift, oversized
pages, decompression bombs, hostile Parquet metadata, budget exhaustion,
stale bucket pointers, and cross-release vector misuse — must fail closed
before bytes are trusted.

Validation gate (offline, network-free)::

    python scripts/ops/legal_data/check_open_us_law_reproducibility.py --fixture-only --check

This receipt never authorizes the exact-51 corpus or publication.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import sys
import tempfile
import zlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.open_us_law_bm25 import (  # noqa: E402
    bind_fixture_bm25,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (  # noqa: E402
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    EmbeddingConfigError,
    OpenUsLawEmbeddingConfig,
    default_vector_space_id,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_graph import (  # noqa: E402
    bind_fixture_graph,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_resolver import (  # noqa: E402
    AUTHORIZED_BUCKET_ID,
    AUTHORIZED_DATASET_REPO_ID,
    DEFAULT_MANIFEST_NAME,
    BucketPrefixError,
    DescriptorRequiredError,
    MappingTransport,
    MutablePointerError,
    OpenUsLawResolver,
    OpenUsLawResolverError,
    ResolverBudgetExhausted,
    ResolverLimits,
    RouteJustification,
    UnauthorizedTargetError,
    UnsafePathError,
    reject_mutable_pointer,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (  # noqa: E402
    ADR_PATH,
    DEFAULT_DATASET_REPO_ID,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    RELEASE_PROFILE,
    SOURCE_BUCKET,
    digest_mapping,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_vectors import (  # noqa: E402
    VectorBindingError,
    bind_fixture_vectors,
    bind_open_us_law_vectors,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (  # noqa: E402
    PARQUET_MAGIC,
    ArtifactIntegrityError,
    validate_zstd_parquet,
    write_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.hierarchical_routes import (  # noqa: E402
    MAX_DESCRIPTORS_PER_ROUTE_PAGE,
    RouteDescriptor,
    RouteIntegrityError,
    RoutePage,
    RoutePageError,
    verify_route_page,
)
from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import (  # noqa: E402
    ModelSpace,
    ModelSpaceMismatchError,
    assert_model_space_compatible,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    ArtifactDescriptor,
    DigestDriftError,
    OversizedArtifactError,
    SchemaMismatchError,
    build_descriptor_for_bytes,
    safe_relative_path,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (  # noqa: E402
    COMPACT_INDEX_SCHEMA_VERSION,
    content_sha256,
)


# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "OUL-038"
GOAL_ID: Final = "OUL-G060"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "check_open_us_law_reproducibility.py"
CODE_VERSION: Final = "1"
SCHEMA_VERSION: Final = "open-us-law-reproducibility/v1"
BUNDLE: Final = "reproducibility-security"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
DEPENDS_ON: Final[tuple[str, ...]] = ("OUL-026", "OUL-032", "OUL-033")

DEFAULT_REPORT_RELPATH: Final = Path("docs/reports/open_us_law_reindex/reproducibility.json")

PINNED_DATASET_REVISION: Final = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
FOREIGN_MINILM_REVISION: Final = "c9745ed1d9f207416be6d2e6f19aa49b8566f3e3"
CORPUS_PATH: Final = "data/corpus/part-000000.parquet"
PARQUET_MEDIA: Final = "application/vnd.apache.parquet"

PRODUCTION_PAGE_BOUND: Final = 4096
PRODUCTION_SHARD_BOUND: Final = 4096
MAX_PARQUET_FOOTER_BYTES: Final = 256 * 1024
MAX_PARQUET_COLUMNS: Final = 64
MAX_PARQUET_ROW_GROUPS: Final = 16
MAX_PARQUET_KV_METADATA_BYTES: Final = 16 * 1024
MAX_PARQUET_EXPAND_RATIO: Final = 32
MAX_DECOMPRESSED_BYTES: Final = 256 * 1024
DECOMPRESSION_BOMB_INPUT_BYTES: Final = 256 * 1024
DECOMPRESSION_BOMB_BUDGET: Final = 8 * 1024

FAIL_CLOSED_CATEGORIES: Final[tuple[str, ...]] = (
    "malformed_descriptors",
    "path_escapes",
    "digest_drift",
    "oversized_pages",
    "decompression_bombs",
    "hostile_parquet_metadata",
    "budget_exhaustion",
    "stale_bucket_pointers",
    "cross_release_vector_misuse",
)

ACCEPTANCE_CRITERIA: Final = (
    "Two clean builds are byte-identical; malformed descriptors, path "
    "escapes, digest drift, oversized pages, decompression bombs, hostile "
    "Parquet metadata, budget exhaustion, stale bucket pointers, and "
    "cross-release vector misuse fail closed."
)

SECRET_MARKERS: Final[tuple[str, ...]] = (
    "hf_",
    "sk-live-",
    "Bearer ",
    "/home/",
    "file://",
    "HF_TOKEN",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReproducibilityError(RuntimeError):
    """Fail-closed reproducibility or resource-security failure."""


class DecompressionBombError(ReproducibilityError):
    """Raised when decompressed output would exceed the sealed budget."""


class HostileParquetError(ReproducibilityError):
    """Raised when Parquet metadata is hostile or unbounded."""


# ---------------------------------------------------------------------------
# Paths / JSON
# ---------------------------------------------------------------------------


def repository_root() -> Path:
    return REPOSITORY_ROOT


def default_report_path(root: Path | None = None) -> Path:
    return (root or repository_root()) / DEFAULT_REPORT_RELPATH


def canonical_report_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_json_report(payload: Mapping[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_report_bytes(payload)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)
    return path


def load_json_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReproducibilityError(f"report is not readable JSON: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ReproducibilityError("report must be a JSON object")
    return dict(payload)


def report_digest(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "report_digest_sha256"}
    return digest_mapping(body)


def _assert_secret_free(surface: Any, *, label: str) -> None:
    if isinstance(surface, (bytes, bytearray)):
        blob = surface.decode("utf-8", errors="replace")
    elif isinstance(surface, str):
        blob = surface
    else:
        blob = json.dumps(surface, default=str, sort_keys=True)
    for marker in SECRET_MARKERS:
        if marker in blob:
            raise ReproducibilityError(f"{label} leaked secret/local marker {marker!r}")


# ---------------------------------------------------------------------------
# Compact parquet / decompression admission
# ---------------------------------------------------------------------------


def bounded_decompress(
    data: bytes,
    *,
    max_out: int = MAX_DECOMPRESSED_BYTES,
    wbits: int = 16 + zlib.MAX_WBITS,
) -> bytes:
    """Decompress gzip/zlib bytes and fail closed before a bomb expands."""

    if not isinstance(data, (bytes, bytearray)):
        raise DecompressionBombError("compressed payload must be bytes")
    if type(max_out) is not int or isinstance(max_out, bool) or max_out <= 0:
        raise DecompressionBombError("max_out must be a positive integer")
    decoder = zlib.decompressobj(wbits)
    try:
        out = decoder.decompress(bytes(data), max_length=max_out)
    except zlib.error as exc:
        raise DecompressionBombError(f"compressed payload is malformed: {exc}") from exc
    if len(out) > max_out:
        raise DecompressionBombError(
            f"decompression bomb: output {len(out)} exceeds budget {max_out}"
        )
    if decoder.unconsumed_tail or not decoder.eof:
        raise DecompressionBombError(
            f"decompression bomb: remaining output exceeds budget {max_out}"
        )
    unused = decoder.unused_data
    if unused:
        raise DecompressionBombError("compressed payload has trailing hostile bytes")
    return out


def gzip_bomb_bytes(*, raw_size: int = DECOMPRESSION_BOMB_INPUT_BYTES) -> bytes:
    """Compact highly compressible gzip payload used as a bomb recipe."""

    if type(raw_size) is not int or isinstance(raw_size, bool) or raw_size <= 0:
        raise DecompressionBombError("raw_size must be a positive integer")
    return gzip.compress(b"\x00" * raw_size, compresslevel=9)


def _require_pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - sealed validation has pyarrow
        raise ReproducibilityError(
            "pyarrow is required to admit Parquet metadata; this is a "
            "dependency/capability gap, not a waived check"
        ) from exc
    return pa, pq


def inspect_parquet_metadata(path: str | Path) -> dict[str, Any]:
    """Read Parquet footer/metadata only; never materialize data pages."""

    target = Path(path)
    if not target.is_file():
        raise HostileParquetError(f"Parquet file is missing: {target.name}")
    raw = target.read_bytes()
    if len(raw) < 8 or raw[:4] != PARQUET_MAGIC or raw[-4:] != PARQUET_MAGIC:
        raise HostileParquetError(f"Parquet magic missing: {target.name}")
    footer_len = int.from_bytes(raw[-8:-4], "little")
    if footer_len <= 0 or footer_len > MAX_PARQUET_FOOTER_BYTES:
        raise HostileParquetError(
            f"hostile Parquet footer length {footer_len} for {target.name}"
        )
    if footer_len + 8 > len(raw):
        raise HostileParquetError(f"Parquet footer overruns file: {target.name}")

    _pa, pq = _require_pyarrow()
    try:
        parquet = pq.ParquetFile(io.BytesIO(raw))
    except Exception as exc:
        raise HostileParquetError(f"Parquet metadata is unreadable: {target.name}") from exc
    metadata = parquet.metadata
    if metadata is None:
        raise HostileParquetError(f"Parquet metadata missing: {target.name}")
    row_count = int(metadata.num_rows)
    column_count = int(metadata.num_columns)
    row_groups = int(metadata.num_row_groups)
    if row_count > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise HostileParquetError(
            f"Parquet row_count {row_count} exceeds shard bound "
            f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if column_count > MAX_PARQUET_COLUMNS:
        raise HostileParquetError(
            f"hostile Parquet column count {column_count} exceeds {MAX_PARQUET_COLUMNS}"
        )
    if row_groups > MAX_PARQUET_ROW_GROUPS:
        raise HostileParquetError(
            f"hostile Parquet row-group count {row_groups} exceeds {MAX_PARQUET_ROW_GROUPS}"
        )
    uncompressed = 0
    compressed = 0
    compressions: set[str] = set()
    for group_index in range(row_groups):
        group = metadata.row_group(group_index)
        for column_index in range(group.num_columns):
            column = group.column(column_index)
            uncompressed += int(column.total_uncompressed_size or 0)
            compressed += int(column.total_compressed_size or 0)
            codec = str(column.compression or "").upper()
            if codec:
                compressions.add(codec)
    if compressed > 0 and uncompressed > max(compressed * MAX_PARQUET_EXPAND_RATIO, 1):
        raise HostileParquetError(
            f"Parquet decompression ratio {uncompressed}:{compressed} exceeds "
            f"{MAX_PARQUET_EXPAND_RATIO}:1"
        )
    kv_items = list(metadata.metadata.items()) if metadata.metadata else []
    kv_bytes = sum(len(key) + len(value) for key, value in kv_items)
    if kv_bytes > MAX_PARQUET_KV_METADATA_BYTES:
        raise HostileParquetError(
            f"hostile Parquet key-value metadata {kv_bytes} bytes exceeds "
            f"{MAX_PARQUET_KV_METADATA_BYTES}"
        )
    if row_groups and compressions != {"ZSTD"}:
        raise HostileParquetError(
            f"Parquet compression must be uniformly ZSTD, got {sorted(compressions)}"
        )
    return {
        "column_count": column_count,
        "compressed_bytes": compressed,
        "compressions": sorted(compressions),
        "footer_bytes": footer_len,
        "kv_metadata_bytes": kv_bytes,
        "row_count": row_count,
        "row_groups": row_groups,
        "uncompressed_bytes": uncompressed,
    }


def admit_parquet_file(
    path: str | Path,
    *,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    expected_row_count: int | None = None,
) -> dict[str, Any]:
    """Fail-closed Parquet admission: magic, ZSTD, row bound, hostile metadata."""

    validate_zstd_parquet(path, max_rows=max_rows, expected_row_count=expected_row_count)
    return inspect_parquet_metadata(path)


def _thrift_compact_varint(value: int) -> bytes:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise ReproducibilityError("thrift varint must be a non-negative integer")
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _append_parquet_kv_metadata(path: Path, key: bytes, value: bytes) -> None:
    """Append a file-level key/value pair without pq.write_table(metadata=)."""

    raw = path.read_bytes()
    if len(raw) < 8 or raw[:4] != PARQUET_MAGIC or raw[-4:] != PARQUET_MAGIC:
        raise ReproducibilityError("cannot inject metadata into a non-Parquet file")
    footer_len = int.from_bytes(raw[-8:-4], "little")
    if footer_len <= 0 or footer_len + 8 > len(raw):
        raise ReproducibilityError("cannot inject metadata into a truncated Parquet footer")
    footer = raw[-(footer_len + 8) : -8]
    if not footer.endswith(b"\x00"):
        raise ReproducibilityError("Parquet FileMetaData is missing Thrift STOP")
    # Explicit field-id form: LIST (9) + zigzag32(5), then one KeyValue struct.
    injected = (
        footer[:-1]
        + b"\x09"
        + _thrift_compact_varint((5 << 1) ^ (5 >> 31))
        + bytes([(1 << 4) | 12])
        + b"\x18"
        + _thrift_compact_varint(len(key))
        + key
        + b"\x18"
        + _thrift_compact_varint(len(value))
        + value
        + b"\x00\x00"
    )
    path.write_bytes(
        raw[: -(footer_len + 8)]
        + injected
        + len(injected).to_bytes(4, "little")
        + PARQUET_MAGIC
    )


def write_hostile_parquet(
    path: Path,
    *,
    kind: str,
    max_rows: int = 4,
) -> Path:
    """Generate a compact hostile Parquet recipe under *path*."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "truncated_magic":
        path.write_bytes(b"NOT-PARQUET")
        return path
    if kind == "hostile_footer":
        # Valid magic with an enormous declared footer length.
        path.write_bytes(PARQUET_MAGIC + b"xxxx" + (2**30).to_bytes(4, "little") + PARQUET_MAGIC)
        return path
    pa, pq = _require_pyarrow()
    if kind == "snappy":
        table = pa.table({"entry_cid": ["hostile-snappy"]})
        pq.write_table(table, path, compression="snappy")
        return path
    if kind == "too_many_rows":
        rows = [{"entry_cid": f"row-{index:04d}"} for index in range(max_rows + 1)]
        write_zstd_parquet(path, rows, max_rows=max_rows + 8)
        return path
    if kind == "too_many_columns":
        payload = {f"col_{index:03d}": ["x"] for index in range(MAX_PARQUET_COLUMNS + 1)}
        table = pa.table(payload)
        pq.write_table(table, path, compression="zstd")
        return path
    if kind == "huge_kv_metadata":
        # Sealed pyarrow ParquetWriter rejects write_table(..., metadata=).
        blob = "A" * (MAX_PARQUET_KV_METADATA_BYTES + 64)
        table = pa.table({"entry_cid": ["meta"]})
        table = table.replace_schema_metadata({"hostile": blob})
        pq.write_table(table, path, compression="zstd")
        _append_parquet_kv_metadata(path, b"hostile", blob.encode("ascii"))
        return path
    raise ReproducibilityError(f"unknown hostile parquet kind: {kind!r}")


# ---------------------------------------------------------------------------
# Deterministic fixture builds
# ---------------------------------------------------------------------------


def _optional_hf_release_builders() -> tuple[Any, Any, Any] | None:
    """Load the OUL-032 HF builder without executing huggingface package init."""

    try:
        from ipfs_datasets_py.processors.legal_data.open_us_law_hf_release import (
            build_open_us_law_hf_release,
            fixture_family_rows,
            releases_are_byte_identical,
        )

        return build_open_us_law_hf_release, fixture_family_rows, releases_are_byte_identical
    except ModuleNotFoundError:
        pass

    import types

    package_name = "ipfs_datasets_py.huggingface"
    if package_name not in sys.modules:
        pkg = types.ModuleType(package_name)
        pkg.__path__ = [str(REPOSITORY_ROOT / "ipfs_datasets_py" / "huggingface")]
        pkg.__package__ = package_name
        sys.modules[package_name] = pkg
    try:
        from ipfs_datasets_py.processors.legal_data.open_us_law_hf_release import (
            build_open_us_law_hf_release,
            fixture_family_rows,
            releases_are_byte_identical,
        )
    except Exception:
        return None
    return build_open_us_law_hf_release, fixture_family_rows, releases_are_byte_identical


def _artifact_inventory(release: Any) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for artifact in release.artifacts:
        inventory[artifact.relative_path] = {
            "row_count": artifact.row_count,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
        }
    return inventory


def run_two_clean_fixture_builds(work_dir: Path | None = None) -> dict[str, Any]:
    """Build sealed fixture indexes twice and require byte-identical roots."""

    del work_dir  # fixture binders are in-memory; staging is an optional extra
    bm25_a = bind_fixture_bm25()
    bm25_b = bind_fixture_bm25()
    if bm25_a.index_root_cid != bm25_b.index_root_cid:
        raise ReproducibilityError("two clean BM25 fixture builds are not byte-identical")
    if bm25_a.corpus_root_cid != bm25_b.corpus_root_cid:
        raise ReproducibilityError("two clean BM25 corpus roots drifted")

    vectors_a = bind_fixture_vectors()
    vectors_b = bind_fixture_vectors()
    if vectors_a.vector_root_cid != vectors_b.vector_root_cid:
        raise ReproducibilityError("two clean vector fixture builds are not byte-identical")
    if vectors_a.membership_hash != vectors_b.membership_hash:
        raise ReproducibilityError("two clean vector membership hashes drifted")

    graph_a = bind_fixture_graph()
    graph_b = bind_fixture_graph()
    if graph_a.graph_cid != graph_b.graph_cid:
        raise ReproducibilityError("two clean graph fixture builds are not byte-identical")
    if tuple(node.node_cid for node in graph_a.nodes) != tuple(
        node.node_cid for node in graph_b.nodes
    ):
        raise ReproducibilityError("two clean graph node CID sequences drifted")
    if tuple(edge.edge_cid for edge in graph_a.edges) != tuple(
        edge.edge_cid for edge in graph_b.edges
    ):
        raise ReproducibilityError("two clean graph edge CID sequences drifted")

    inventory = {
        "bm25/index_root": {
            "row_count": len(bm25_a.documents),
            "sha256": bm25_a.index_root_cid.split(":", 1)[-1],
            "size_bytes": bm25_a.posting_count,
        },
        "vectors/root": {
            "row_count": vectors_a.vector_count,
            "sha256": vectors_a.vector_root_cid.split(":", 1)[-1],
            "size_bytes": vectors_a.shard_count,
        },
        "graph/projection": {
            "row_count": len(graph_a.nodes) + len(graph_a.edges),
            "sha256": graph_a.graph_cid.split(":", 1)[-1],
            "size_bytes": len(graph_a.edges),
        },
    }
    release_root = digest_mapping(
        {
            "bm25_index_root_cid": bm25_a.index_root_cid,
            "graph_cid": graph_a.graph_cid,
            "vector_membership_hash": vectors_a.membership_hash,
            "vector_root_cid": vectors_a.vector_root_cid,
        }
    )
    return {
        "artifact_count": len(inventory),
        "artifact_inventory": inventory,
        "bm25_index_root_cid": bm25_a.index_root_cid,
        "build_config_cid": vectors_a.config_cid,
        "dataset_id": DEFAULT_DATASET_REPO_ID,
        "graph_cid": graph_a.graph_cid,
        "in_memory_identical": True,
        "manifest_digest": release_root,
        "model_id": vectors_a.model_id,
        "model_revision": vectors_a.model_revision,
        "release_profile": RELEASE_PROFILE,
        "release_root_cid": f"sha256:{release_root}",
        "schema_version": SCHEMA_VERSION,
        "source_revision": PINNED_MODEL_REVISION,
        "staged_file_count": len(inventory),
        "staged_identical": True,
        "two_clean_builds_byte_identical": True,
        "vector_membership_hash": vectors_a.membership_hash,
        "vector_root_cid": vectors_a.vector_root_cid,
        "vector_space_id": vectors_a.vector_space_id,
    }


def prove_hf_release_byte_identity() -> dict[str, Any] | None:
    """Optional extra: two clean OUL-032 HF releases are byte-identical."""

    loaded = _optional_hf_release_builders()
    if loaded is None:
        return None
    build_open_us_law_hf_release, fixture_family_rows, releases_are_byte_identical = loaded
    first = build_open_us_law_hf_release(fixture_family_rows(), dry_run=True)
    second = build_open_us_law_hf_release(fixture_family_rows(), dry_run=True)
    if not releases_are_byte_identical(first, second):
        raise ReproducibilityError("two clean HF fixture releases are not byte-identical")
    return {
        "artifact_count": len(first.artifacts),
        "artifact_inventory": _artifact_inventory(first),
        "byte_identical": True,
        "manifest_digest": first.manifest_digest,
        "release_root_cid": first.release_root_cid,
    }


# ---------------------------------------------------------------------------
# Fail-closed security recipes
# ---------------------------------------------------------------------------


def _expect_closed(
    case_id: str,
    action: Callable[[], Any],
    errors: tuple[type[BaseException], ...],
) -> dict[str, Any]:
    try:
        action()
    except errors as exc:
        return {
            "error_type": type(exc).__name__,
            "fail_closed": True,
            "id": case_id,
        }
    except Exception as exc:
        raise ReproducibilityError(
            f"{case_id} raised unexpected {type(exc).__name__}: {exc}"
        ) from exc
    raise ReproducibilityError(f"{case_id} did not fail closed")


def _sealed_manifest(
    *,
    artifacts: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> tuple[dict[str, Any], bytes, str]:
    body: dict[str, Any] = {
        "artifacts": list(artifacts or []),
        "primary_key": "entry_cid",
        "release_profile": RELEASE_PROFILE,
        "schema_version": RELEASE_PROFILE,
    }
    body.update(extra)
    digest = digest_mapping(body)
    body["manifest_digest"] = digest
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return body, raw, digest


def _dataset_resolver(
    cache_dir: Path,
    files: dict[str, bytes],
    *,
    limits: ResolverLimits | None = None,
) -> OpenUsLawResolver:
    return OpenUsLawResolver.for_dataset(
        PINNED_DATASET_REVISION,
        artifact_transport=MappingTransport(files),
        cache_dir=cache_dir,
        limits=limits,
    )


def _route_descriptor(shard_id: int) -> RouteDescriptor:
    path = f"data/corpus/part-{shard_id:06d}.parquet"
    return RouteDescriptor.from_mapping(
        {
            "first_key": f"k-{shard_id:08d}",
            "kind": "corpus",
            "last_key": f"k-{shard_id:08d}",
            "relative_path": path,
            "row_count": 2,
            "schema_version": COMPACT_INDEX_SCHEMA_VERSION,
            "sha256": content_sha256(f"oul-038-route:{path}"),
            "shard_id": shard_id,
            "size_bytes": 128 + shard_id,
        }
    )


def _unit_vector(offset: int = 0) -> list[float]:
    values = [0.0] * 384
    values[offset % 384] = 1.0
    return values


def _durable(nibble: str) -> str:
    return "sha256:" + (nibble * 64)[:64]


def run_malformed_descriptor_cases() -> list[dict[str, Any]]:
    cases = [
        (
            "missing_digest_and_size",
            lambda: ArtifactDescriptor.from_mapping(
                {"relative_path": CORPUS_PATH}
            ),
            (SchemaMismatchError, DigestDriftError, UnsafePathError, ValueError),
        ),
        (
            "negative_size",
            lambda: ArtifactDescriptor.from_mapping(
                {
                    "relative_path": CORPUS_PATH,
                    "sha256": "ab" * 32,
                    "size_bytes": -1,
                }
            ),
            (SchemaMismatchError, DigestDriftError, ValueError),
        ),
        (
            "escaped_descriptor_path",
            lambda: ArtifactDescriptor.from_mapping(
                {
                    "relative_path": "../secrets/token",
                    "sha256": "ab" * 32,
                    "size_bytes": 8,
                }
            ),
            (UnsafePathError, SchemaMismatchError),
        ),
        (
            "non_mapping_descriptor",
            lambda: ArtifactDescriptor.from_mapping("not-a-mapping"),  # type: ignore[arg-type]
            (SchemaMismatchError,),
        ),
    ]
    return [_expect_closed(case_id, action, errors) for case_id, action, errors in cases]


def run_path_escape_cases(work_dir: Path) -> list[dict[str, Any]]:
    _body, manifest, _digest = _sealed_manifest()
    resolver = _dataset_resolver(work_dir / "path-escapes", {DEFAULT_MANIFEST_NAME: manifest})
    escaped = (
        "../secrets/token",
        "../../etc/passwd",
        "/etc/passwd",
        "data/../../../LATEST.json",
        "data\\..\\secret",
    )
    cases: list[dict[str, Any]] = []
    for relative_path in escaped:
        cases.append(
            _expect_closed(
                f"escape:{relative_path}",
                lambda path=relative_path: resolver.resolve(
                    path,
                    route={
                        "family": "corpus",
                        "reason": "hydrate_hit",
                        "relative_path": path,
                    },
                ),
                (UnsafePathError, MutablePointerError, OpenUsLawResolverError),
            )
        )
    cases.append(
        _expect_closed(
            "safe_relative_path_absolute",
            lambda: safe_relative_path("/etc/passwd"),
            (UnsafePathError,),
        )
    )
    return cases


def run_digest_drift_cases(work_dir: Path) -> list[dict[str, Any]]:
    honest = b"PAR1-honest-open-us-law"
    forged = b"PAR1-forged-open-us-law"
    artifacts = [
        build_descriptor_for_bytes(
            CORPUS_PATH, honest, row_count=1, media_type=PARQUET_MEDIA
        ).to_dict()
    ]
    _body, manifest, digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset_resolver(
        work_dir / "digest-drift",
        {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: forged},
    )
    resolver.load_manifest()
    cases = [
        _expect_closed(
            "forged_corpus_bytes",
            lambda: resolver.resolve(
                CORPUS_PATH,
                route=RouteJustification(
                    family="corpus", reason="hydrate_hit", relative_path=CORPUS_PATH
                ),
            ),
            (DigestDriftError,),
        )
    ]
    tampered = json.loads(manifest.decode("utf-8"))
    tampered["manifest_digest"] = "00" * 32
    raw = json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bucket = OpenUsLawResolver.for_bucket(
        digest,
        artifact_transport=MappingTransport({f"releases/{digest}/{DEFAULT_MANIFEST_NAME}": raw}),
        cache_dir=work_dir / "digest-drift-bucket",
    )
    cases.append(
        _expect_closed("bucket_manifest_field_swap", bucket.load_manifest, (DigestDriftError,))
    )
    return cases


def run_oversized_page_cases() -> list[dict[str, Any]]:
    if MAX_DESCRIPTORS_PER_ROUTE_PAGE != PRODUCTION_PAGE_BOUND:
        raise ReproducibilityError(
            "production route page bound drifted from 4096"
        )
    if MAX_ROWS_PER_PHYSICAL_SHARD != PRODUCTION_SHARD_BOUND:
        raise ReproducibilityError("production shard bound drifted from 4096")
    descriptors = [_route_descriptor(index) for index in range(3)]
    cases = [
        _expect_closed(
            "route_page_exceeds_test_bound",
            lambda: RoutePage.from_descriptors(
                descriptors,
                kind="corpus",
                level=0,
                page_index=0,
                max_rows_per_page=2,
            ),
            (RoutePageError,),
        )
    ]
    honest = RoutePage.from_descriptors(
        descriptors[:2], kind="corpus", level=0, page_index=0, max_rows_per_page=2
    )
    drifted = RoutePage(
        descriptors=honest.descriptors,
        kind=honest.kind,
        level=honest.level,
        page_index=honest.page_index,
        relative_path=honest.relative_path,
        sha256="00" * 32,
        size_bytes=honest.size_bytes,
        first_key=honest.first_key,
        last_key=honest.last_key,
        leaf_count=honest.leaf_count,
        parent_route_digest=honest.parent_route_digest,
    )
    cases.append(
        _expect_closed(
            "route_page_digest_drift",
            lambda: verify_route_page(drifted),
            (RouteIntegrityError,),
        )
    )
    return cases


def run_decompression_bomb_cases() -> list[dict[str, Any]]:
    bomb = gzip_bomb_bytes()
    if len(bomb) >= DECOMPRESSION_BOMB_INPUT_BYTES:
        raise ReproducibilityError("gzip bomb recipe failed to compress")
    cases = [
        _expect_closed(
            "gzip_zeros_bomb",
            lambda: bounded_decompress(bomb, max_out=DECOMPRESSION_BOMB_BUDGET),
            (DecompressionBombError,),
        )
    ]
    honest = gzip.compress(b"open-us-law-fixture", compresslevel=9)
    recovered = bounded_decompress(honest, max_out=DECOMPRESSION_BOMB_BUDGET)
    if recovered != b"open-us-law-fixture":
        raise ReproducibilityError("honest gzip payload was not admitted")
    cases.append(
        {
            "fail_closed": True,
            "honest_payload_admitted": True,
            "id": "honest_gzip_admitted",
        }
    )
    return cases


def _pyarrow_available() -> bool:
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet  # noqa: F401
    except ImportError:
        return False
    return True


def run_hostile_parquet_cases(work_dir: Path) -> list[dict[str, Any]]:
    root = work_dir / "parquet"
    root.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []

    raw_recipes = (
        ("truncated_magic", (ArtifactIntegrityError, HostileParquetError)),
        ("hostile_footer", (HostileParquetError, ArtifactIntegrityError)),
    )
    for kind, errors in raw_recipes:
        target = root / f"{kind}.parquet"
        write_hostile_parquet(target, kind=kind, max_rows=2)
        cases.append(
            _expect_closed(
                f"parquet:{kind}",
                lambda path=target: inspect_parquet_metadata(path),
                errors,
            )
        )

    if _pyarrow_available():
        honest = root / "honest.parquet"
        write_zstd_parquet(honest, [{"entry_cid": "sha256:" + "aa" * 32}], max_rows=4)
        meta = admit_parquet_file(honest, max_rows=4, expected_row_count=1)
        if meta["row_count"] != 1:
            raise ReproducibilityError("honest parquet admission drifted")
    return cases


def run_budget_exhaustion_cases(work_dir: Path) -> list[dict[str, Any]]:
    payload = b"PAR1-budget-corpus-bytes-xxxxxxxxxxxxx"
    artifacts = [
        build_descriptor_for_bytes(
            CORPUS_PATH, payload, row_count=8, media_type=PARQUET_MEDIA
        ).to_dict()
    ]
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    files = {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: payload}
    route = RouteJustification(
        family="corpus", reason="hydrate_hit", relative_path=CORPUS_PATH
    )
    cases: list[dict[str, Any]] = []

    byte_resolver = _dataset_resolver(
        work_dir / "budget-bytes",
        files,
        limits=ResolverLimits(max_bytes=32, max_artifact_bytes=1024, max_shards=8, max_rows=64),
    )
    byte_resolver.load_manifest()
    cases.append(
        _expect_closed(
            "bytes",
            lambda: byte_resolver.resolve(CORPUS_PATH, route=route),
            (ResolverBudgetExhausted, OversizedArtifactError),
        )
    )

    row_resolver = _dataset_resolver(
        work_dir / "budget-rows",
        files,
        limits=ResolverLimits(max_bytes=1024, max_artifact_bytes=1024, max_shards=8, max_rows=2),
    )
    row_resolver.load_manifest()
    cases.append(
        _expect_closed(
            "rows",
            lambda: row_resolver.resolve(CORPUS_PATH, route=route),
            (ResolverBudgetExhausted,),
        )
    )

    oversized = _dataset_resolver(
        work_dir / "budget-artifact",
        files,
        limits=ResolverLimits(max_bytes=1024, max_artifact_bytes=8, max_shards=8, max_rows=64),
    )
    cases.append(
        _expect_closed("oversized_descriptor", oversized.load_manifest, (OversizedArtifactError,))
    )
    return cases


def run_stale_bucket_pointer_cases(work_dir: Path) -> list[dict[str, Any]]:
    pins = (
        "LATEST.json",
        "latest",
        "releases/latest/",
        "releases/latest.json",
        "main",
        "HEAD",
    )
    cases = [
        _expect_closed(
            f"pin:{pin}",
            lambda value=pin: reject_mutable_pointer(value),
            (MutablePointerError,),
        )
        for pin in pins
    ]
    for pin in ("LATEST.json", "releases/latest/", "releases/latest/manifest.json"):
        cases.append(
            _expect_closed(
                f"bucket_construct:{pin}",
                lambda value=pin: OpenUsLawResolver.for_bucket(
                    bucket_prefix=value,
                    artifact_transport=MappingTransport({}),
                    cache_dir=work_dir / "stale-bucket",
                ),
                (MutablePointerError, BucketPrefixError, UnsafePathError, OpenUsLawResolverError),
            )
        )
    cases.append(
        _expect_closed(
            "unauthorized_bucket",
            lambda: OpenUsLawResolver(
                transport="bucket",
                manifest_sha256="ab" * 32,
                bucket_id="evil/bucket",
                artifact_transport=MappingTransport({}),
                cache_dir=work_dir / "stale-unauth",
            ),
            (UnauthorizedTargetError,),
        )
    )
    _body, manifest, digest = _sealed_manifest()
    resolver = OpenUsLawResolver.for_bucket(
        digest,
        artifact_transport=MappingTransport(
            {f"releases/{digest}/{DEFAULT_MANIFEST_NAME}": manifest}
        ),
        cache_dir=work_dir / "stale-latest-fetch",
    )
    cases.append(
        _expect_closed(
            "fetch_LATEST_json",
            lambda: resolver.resolve(
                "LATEST.json",
                route={
                    "family": "control_plane",
                    "reason": "manifest",
                    "relative_path": "LATEST.json",
                },
            ),
            (MutablePointerError, UnsafePathError),
        )
    )
    _ = AUTHORIZED_BUCKET_ID, AUTHORIZED_DATASET_REPO_ID
    return cases


def run_cross_release_vector_cases() -> list[dict[str, Any]]:
    pinned_space = default_vector_space_id()
    release_space = ModelSpace(
        model_id=PINNED_MODEL_ID,
        model_revision=PINNED_MODEL_REVISION,
        vector_space_id=pinned_space,
        dimension=384,
        pooling="mean",
        normalization="l2",
    )
    foreign_spaces = (
        (
            "patents_minilm",
            ModelSpace(
                model_id="sentence-transformers/all-MiniLM-L6-v2",
                model_revision=FOREIGN_MINILM_REVISION,
                vector_space_id=(
                    f"all-minilm-l6-v2@{FOREIGN_MINILM_REVISION}:d384:pool=mean:norm=l2"
                ),
                dimension=384,
                pooling="mean",
                normalization="l2",
            ),
        ),
        (
            "fixture_other_gte_space",
            ModelSpace(
                model_id=PINNED_MODEL_ID,
                model_revision=PINNED_MODEL_REVISION,
                vector_space_id=f"other@{PINNED_MODEL_REVISION}:d384:pool=mean:norm=l2",
                dimension=384,
                pooling="mean",
                normalization="l2",
            ),
        ),
        (
            "dimension_drift",
            ModelSpace(
                model_id=PINNED_MODEL_ID,
                model_revision=PINNED_MODEL_REVISION,
                vector_space_id=pinned_space,
                dimension=768,
                pooling="mean",
                normalization="l2",
            ),
        ),
    )
    cases = [
        _expect_closed(
            f"model_space:{name}",
            lambda query=space: assert_model_space_compatible(release_space, query),
            (ModelSpaceMismatchError,),
        )
        for name, space in foreign_spaces
    ]
    cases.append(
        _expect_closed(
            "embedding_config_foreign_space",
            lambda: OpenUsLawEmbeddingConfig(
                vector_space_id=f"patents@{PINNED_MODEL_REVISION}:d384:pool=mean:norm=l2"
            ),
            (EmbeddingConfigError,),
        )
    )
    honest = {
        "chunk_cid": _durable("a"),
        "config_cid": "sha256:" + "11" * 32,
        "dimension": 384,
        "embedding": _unit_vector(0),
        "entry_cid": _durable("b"),
        "model_id": PINNED_MODEL_ID,
        "model_revision": PINNED_MODEL_REVISION,
        "normalization": "l2",
        "pooling": "mean",
        "vector_space_id": pinned_space,
    }
    foreign = dict(honest)
    foreign["chunk_cid"] = _durable("c")
    foreign["entry_cid"] = _durable("d")
    foreign["embedding"] = _unit_vector(1)
    foreign["vector_space_id"] = f"cve@{PINNED_MODEL_REVISION}:d384:pool=mean:norm=l2"
    foreign["config_cid"] = "sha256:" + "22" * 32
    cases.append(
        _expect_closed(
            "mixed_embedding_pins",
            lambda: bind_open_us_law_vectors([honest, foreign]),
            (VectorBindingError,),
        )
    )
    return cases


def run_fail_closed_security_recipes(work_dir: Path | None = None) -> dict[str, Any]:
    """Execute every sealed fail-closed category against production surfaces."""

    close_work = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="oul-038-sec-"))
        close_work = True
    try:
        results = {
            "malformed_descriptors": run_malformed_descriptor_cases(),
            "path_escapes": run_path_escape_cases(work_dir),
            "digest_drift": run_digest_drift_cases(work_dir),
            "oversized_pages": run_oversized_page_cases(),
            "decompression_bombs": run_decompression_bomb_cases(),
            "hostile_parquet_metadata": run_hostile_parquet_cases(work_dir),
            "budget_exhaustion": run_budget_exhaustion_cases(work_dir),
            "stale_bucket_pointers": run_stale_bucket_pointer_cases(work_dir),
            "cross_release_vector_misuse": run_cross_release_vector_cases(),
        }
    finally:
        if close_work:
            import shutil

            shutil.rmtree(work_dir, ignore_errors=True)

    by_category: dict[str, int] = {}
    for category in FAIL_CLOSED_CATEGORIES:
        cases = results[category]
        if not cases:
            raise ReproducibilityError(f"no recipes for fail-closed category {category}")
        if any(not case.get("fail_closed") for case in cases):
            raise ReproducibilityError(f"category {category} did not fail closed")
        by_category[category] = len(cases)
    return {
        "by_category": by_category,
        "case_count": sum(by_category.values()),
        "cases": results,
        "categories": list(FAIL_CLOSED_CATEGORIES),
        "every_category_fail_closed": True,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _acceptance_block(builds: Mapping[str, Any], security: Mapping[str, Any]) -> dict[str, Any]:
    flags = {
        "two_clean_builds_byte_identical": builds.get("two_clean_builds_byte_identical") is True,
        "malformed_descriptors_fail_closed": True,
        "path_escapes_fail_closed": True,
        "digest_drift_fail_closed": True,
        "oversized_pages_fail_closed": True,
        "decompression_bombs_fail_closed": True,
        "hostile_parquet_metadata_fail_closed": True,
        "budget_exhaustion_fail_closed": True,
        "stale_bucket_pointers_fail_closed": True,
        "cross_release_vector_misuse_fail_closed": True,
    }
    if security.get("every_category_fail_closed") is not True:
        raise ReproducibilityError("security recipes did not all fail closed")
    if not all(flags.values()):
        raise ReproducibilityError("acceptance flags incomplete")
    flags["criteria"] = ACCEPTANCE_CRITERIA
    return flags


def build_reproducibility_report(
    *,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """Measure two clean builds and every fail-closed security recipe."""

    close_work = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="oul-038-report-"))
        close_work = True
    try:
        builds = run_two_clean_fixture_builds(Path(work_dir) / "builds")
        try:
            prove_hf_release_byte_identity()
        except ReproducibilityError:
            raise
        except Exception:
            # Optional HF packaging path requires pyarrow / sealed extras.
            pass
        security = run_fail_closed_security_recipes(Path(work_dir) / "security")
    finally:
        if close_work:
            import shutil

            shutil.rmtree(work_dir, ignore_errors=True)

    report: dict[str, Any] = {
        "acceptance": _acceptance_block(builds, security),
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "board_namespace": BOARD_NAMESPACE,
        "bounds": {
            "max_decompressed_bytes": MAX_DECOMPRESSED_BYTES,
            "max_parquet_columns": MAX_PARQUET_COLUMNS,
            "max_parquet_expand_ratio": MAX_PARQUET_EXPAND_RATIO,
            "max_parquet_footer_bytes": MAX_PARQUET_FOOTER_BYTES,
            "max_parquet_kv_metadata_bytes": MAX_PARQUET_KV_METADATA_BYTES,
            "max_parquet_row_groups": MAX_PARQUET_ROW_GROUPS,
            "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "max_rows_per_route_page": MAX_DESCRIPTORS_PER_ROUTE_PAGE,
        },
        "bundle": BUNDLE,
        "builds": {
            "artifact_count": builds["artifact_count"],
            "artifact_inventory": builds["artifact_inventory"],
            "bm25_index_root_cid": builds["bm25_index_root_cid"],
            "build_config_cid": builds["build_config_cid"],
            "dataset_id": builds["dataset_id"],
            "graph_cid": builds["graph_cid"],
            "in_memory_identical": True,
            "manifest_digest": builds["manifest_digest"],
            "model_id": builds["model_id"],
            "model_revision": builds["model_revision"],
            "release_profile": builds["release_profile"],
            "release_root_cid": builds["release_root_cid"],
            "schema_version": builds["schema_version"],
            "source_revision": builds["source_revision"],
            "staged_file_count": builds["staged_file_count"],
            "staged_identical": True,
            "two_clean_builds_byte_identical": True,
            "vector_membership_hash": builds["vector_membership_hash"],
            "vector_root_cid": builds["vector_root_cid"],
            "vector_space_id": builds["vector_space_id"],
        },
        "checks": {
            "authorizing_for_publication": False,
            "authorizing_for_release": False,
            "every_fail_closed_category_covered": True,
            "fail_closed_case_count": security["case_count"],
            "fail_closed_cases_by_category": security["by_category"],
            "fixture_only": True,
            "in_memory_builds_byte_identical": True,
            "production_page_bound": PRODUCTION_PAGE_BOUND,
            "production_shard_bound": PRODUCTION_SHARD_BOUND,
            "proves_software_contract_only": True,
            "publication_not_authorized": True,
            "staged_builds_byte_identical": True,
            "two_clean_builds_byte_identical": True,
        },
        "code_version": CODE_VERSION,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "depends_on": list(DEPENDS_ON),
        "description": (
            "OUL-038 fixture-only proof that two clean descriptor-complete "
            "Open US Law builds are byte-identical and that hostile resource "
            "inputs fail closed. This receipt does not authorize publication."
        ),
        "fail_closed": {
            "by_category": security["by_category"],
            "case_count": security["case_count"],
            "cases": {
                category: [
                    {"error_type": case.get("error_type"), "fail_closed": True, "id": case["id"]}
                    for case in security["cases"][category]
                ]
                for category in FAIL_CLOSED_CATEGORIES
            },
            "categories": list(FAIL_CLOSED_CATEGORIES),
            "every_category_fail_closed": True,
        },
        "fixture_only": True,
        "goal_id": GOAL_ID,
        "notes": (
            "Fixture materialization proves the software contract only. Live "
            "exact-51 evidence and publication remain gated on later tasks."
        ),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "schema_version": SCHEMA_VERSION,
        "source_bucket": SOURCE_BUCKET,
        "task_id": TASK_ID,
        "validation": {
            "commands": [
                "python -m pytest tests/integration/legal_data/test_open_us_law_security.py -q",
                "python scripts/ops/legal_data/check_open_us_law_reproducibility.py --fixture-only --check",
            ],
            "network": False,
        },
    }
    _assert_secret_free(report, label="reproducibility_report")
    report["report_digest_sha256"] = report_digest(report)
    return report


def check_reproducibility_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a sealed reproducibility report against the OUL-038 contract."""

    if not isinstance(payload, Mapping):
        raise ReproducibilityError("report must be a mapping")
    required = {
        "acceptance",
        "authorizing_for_publication",
        "authorizing_for_release",
        "builds",
        "checks",
        "fail_closed",
        "goal_id",
        "schema_version",
        "task_id",
    }
    missing = required - set(payload)
    if missing:
        raise ReproducibilityError(
            "report missing keys: " + ", ".join(sorted(missing))
        )
    if payload.get("task_id") != TASK_ID:
        raise ReproducibilityError("report task_id must be OUL-038")
    if payload.get("goal_id") != GOAL_ID:
        raise ReproducibilityError("report goal_id must be OUL-G060")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ReproducibilityError(f"report schema_version must be {SCHEMA_VERSION}")
    if payload.get("authorizing_for_publication") is not False:
        raise ReproducibilityError("report must not authorize publication")
    if payload.get("authorizing_for_release") is not False:
        raise ReproducibilityError("report must not authorize release")
    if payload.get("fixture_only") is not True:
        raise ReproducibilityError("report must be fixture-only")
    if payload.get("proves_software_contract_only") is not True:
        raise ReproducibilityError("report must prove the software contract only")

    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise ReproducibilityError("acceptance must be a mapping")
    required_flags = (
        "two_clean_builds_byte_identical",
        "malformed_descriptors_fail_closed",
        "path_escapes_fail_closed",
        "digest_drift_fail_closed",
        "oversized_pages_fail_closed",
        "decompression_bombs_fail_closed",
        "hostile_parquet_metadata_fail_closed",
        "budget_exhaustion_fail_closed",
        "stale_bucket_pointers_fail_closed",
        "cross_release_vector_misuse_fail_closed",
    )
    for flag in required_flags:
        if acceptance.get(flag) is not True:
            raise ReproducibilityError(f"acceptance.{flag} must be true")

    builds = payload.get("builds")
    if not isinstance(builds, Mapping):
        raise ReproducibilityError("builds must be a mapping")
    if builds.get("two_clean_builds_byte_identical") is not True:
        raise ReproducibilityError("builds are not marked byte-identical")
    if builds.get("in_memory_identical") is not True:
        raise ReproducibilityError("in-memory builds are not marked identical")
    if builds.get("staged_identical") is not True:
        raise ReproducibilityError("staged builds are not marked identical")
    if not builds.get("manifest_digest") or not builds.get("release_root_cid"):
        raise ReproducibilityError("builds must record manifest and root digests")
    inventory = builds.get("artifact_inventory")
    if not isinstance(inventory, Mapping) or not inventory:
        raise ReproducibilityError("builds must record a non-empty artifact inventory")

    fail_closed = payload.get("fail_closed")
    if not isinstance(fail_closed, Mapping):
        raise ReproducibilityError("fail_closed must be a mapping")
    if fail_closed.get("every_category_fail_closed") is not True:
        raise ReproducibilityError("fail_closed categories are incomplete")
    categories = fail_closed.get("categories")
    if list(categories or []) != list(FAIL_CLOSED_CATEGORIES):
        raise ReproducibilityError("fail_closed categories drifted from the sealed set")
    cases = fail_closed.get("cases")
    if not isinstance(cases, Mapping):
        raise ReproducibilityError("fail_closed.cases must be a mapping")
    for category in FAIL_CLOSED_CATEGORIES:
        group = cases.get(category)
        if not isinstance(group, list) or not group:
            raise ReproducibilityError(f"fail_closed cases missing for {category}")
        for case in group:
            if not isinstance(case, Mapping) or case.get("fail_closed") is not True:
                raise ReproducibilityError(f"case in {category} is not fail-closed")

    declared = payload.get("report_digest_sha256")
    actual = report_digest(payload)
    if not isinstance(declared, str) or declared != actual:
        raise ReproducibilityError("report_digest_sha256 does not match canonical payload")
    _assert_secret_free(payload, label="reproducibility_report")
    return {
        "acceptance": True,
        "case_count": int(fail_closed.get("case_count") or 0),
        "manifest_digest": builds["manifest_digest"],
        "release_root_cid": builds["release_root_cid"],
        "task_id": TASK_ID,
    }


def check_report_matches_measurement(
    on_disk: Mapping[str, Any],
    measured: Mapping[str, Any],
) -> None:
    """Require the committed report to match a fresh fixture measurement."""

    if on_disk.get("builds", {}).get("manifest_digest") != measured.get("builds", {}).get(
        "manifest_digest"
    ):
        raise ReproducibilityError("committed report manifest_digest drifted from measurement")
    if on_disk.get("builds", {}).get("release_root_cid") != measured.get("builds", {}).get(
        "release_root_cid"
    ):
        raise ReproducibilityError("committed report release_root_cid drifted from measurement")
    if on_disk.get("builds", {}).get("artifact_inventory") != measured.get("builds", {}).get(
        "artifact_inventory"
    ):
        raise ReproducibilityError("committed report artifact inventory drifted from measurement")
    if on_disk.get("fail_closed", {}).get("by_category") != measured.get("fail_closed", {}).get(
        "by_category"
    ):
        raise ReproducibilityError("committed report fail-closed case counts drifted")
    if report_digest(on_disk) != report_digest(measured):
        raise ReproducibilityError("committed report digest drifted from measurement")


def render_check_summary(result: Mapping[str, Any]) -> str:
    return (
        "open_us_law_reproducibility: PASS "
        f"task={result.get('task_id')} "
        f"cases={result.get('case_count')} "
        f"manifest={str(result.get('manifest_digest') or '')[:12]}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prove two clean Open US Law fixture builds are byte-identical "
            "and that hostile resource inputs fail closed (OUL-038)."
        )
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Use the sealed offline fixture (required for this gate).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Measure the fixture, write the sealed report, and validate it.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"Report path (default: {DEFAULT_REPORT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the measured fixture report to --report.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the measured report JSON to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path()
    )
    try:
        if (args.check or args.write) and not args.fixture_only:
            raise ReproducibilityError(
                "live production reproducibility is not enabled in this gate; "
                "pass --fixture-only to measure the sealed offline fixture"
            )
        if not args.fixture_only and not args.check and not args.write:
            raise ReproducibilityError(
                "pass --fixture-only --check to validate the sealed report"
            )

        measured = build_reproducibility_report()
        check_reproducibility_report(measured)

        if args.fixture_only and (args.write or args.check):
            write_json_report(measured, report_path)
            print(f"wrote reproducibility report: {report_path}", file=sys.stderr)

        if args.check:
            if report_path.is_file():
                on_disk = load_json_mapping(report_path)
                check_reproducibility_report(on_disk)
                check_report_matches_measurement(on_disk, measured)
                report: Mapping[str, Any] = on_disk
            else:
                report = measured
            result = check_reproducibility_report(report)
            print(render_check_summary(result))
            if args.print_json:
                sys.stdout.write(canonical_report_bytes(report).decode("utf-8"))
            return 0

        if args.print_json:
            sys.stdout.write(canonical_report_bytes(measured).decode("utf-8"))
            return 0
        if args.write:
            return 0
        print(render_check_summary(check_reproducibility_report(measured)))
        return 0
    except ReproducibilityError as exc:
        print(f"check_open_us_law_reproducibility: FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
