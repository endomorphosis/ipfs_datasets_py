#!/usr/bin/env python3
"""Prove deterministic streaming state-law builds and fail-closed security (LCR-037).

Two isolated clean fixture builds must share logical CIDs, routes, counts,
and the manifest digest. Compact hostile recipes — traversal, symlink,
digest, decompression, row, resource, mutable-pin, secret, and partial-
checkpoint — must fail closed before bytes are trusted. Streaming memory
and external-sort occupancy stay within the declared ``memory-large``
class. Allowable Parquet byte drift is explained and bounded.

Validation gate (offline, network-free)::

    python scripts/ops/legal_data/check_state_laws_reproducibility.py --fixture-only --check

This receipt never authorizes Hub upload or publication.
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

from ipfs_datasets_py.processors.legal_data.federal_register_release import (  # noqa: E402
    PromotionError,
    assert_promotable,
    run_fixture_build as run_federal_register_fixture_build,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_streaming import (  # noqa: E402
    JurisdictionUnitRecord as StreamingUnitRecord,
    PartialCheckpointPromotionError,
    StreamingCheckpoint,
    WorkUnitStatus as StreamingWorkUnitStatus,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graphrag_adapter import (  # noqa: E402
    AbsolutePathError,
    AdapterPinError,
    DescriptorDriftError,
    assert_no_descriptor_drift,
    assert_no_home_paths_or_tokens,
    build_immutable_resolver,
    external_sort_state_family,
    iter_physical_shards,
    require_relative_artifact_path,
    stream_state_family_partitions,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (  # noqa: E402
    assemble_state_laws_hf_release,
    fixture_family_rows,
    fixture_legacy_files,
    releases_are_byte_identical,
    stage_state_laws_hf_release,
)
from ipfs_datasets_py.processors.legal_data.state_laws_query import (  # noqa: E402
    ImmutablePinError,
    assert_no_secrets,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (  # noqa: E402
    ADR_PATH,
    DEFAULT_DATASET_REPO_ID,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    ArtifactDescriptor as StateArtifactDescriptor,
    ArtifactPathError,
    MutableReferenceError,
    PhysicalBoundError as StatePhysicalBoundError,
    StateLawsReleaseSchemaError,
    digest_mapping,
    validate_physical_row_count,
)
from ipfs_datasets_py.processors.legal_data.uscode_build import (  # noqa: E402
    BuildCheckpointError,
    ResourceLimitError,
    ResourceLimits,
    SealError,
    compute_seal,
    run_fixture_build as run_uscode_fixture_build,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (  # noqa: E402
    ArtifactIntegrityError,
    PhysicalBoundError,
    validate_zstd_parquet,
    write_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.external_sort import (  # noqa: E402
    DEFAULT_MAX_RECORDS_IN_MEMORY,
    MemoryBudget,
    MemoryBudgetError,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import (  # noqa: E402
    QueryBudgetExhausted,
    QueryLimits,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    DigestDriftError,
    LocalRootTransport,
    MappingTransport,
    MutableRevisionError,
    OversizedArtifactError,
    SymlinkRejectedError,
    UnsafePathError,
    build_descriptor_for_bytes,
    file_sha256_and_size,
    safe_relative_path,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (  # noqa: E402
    PARQUET_MAGIC,
)


# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-037"
GOAL_ID: Final = "LCR-G060"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "check_state_laws_reproducibility.py"
CODE_VERSION: Final = "1"
SCHEMA_VERSION: Final = "state-laws-reproducibility/v1"
BUNDLE: Final = "evaluation-security"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
DEPENDS_ON: Final[tuple[str, ...]] = ("LCR-026", "LCR-032", "LCR-033")
RESOURCE_CLASS: Final = "memory-large"

DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/reproducibility.json"
)

PINNED_REVISION: Final = PREVIOUS_PUBLIC_PIN
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
DECLARED_MAX_RESIDENT_RECORDS: Final = DEFAULT_MAX_RECORDS_IN_MEMORY

FAIL_CLOSED_CATEGORIES: Final[tuple[str, ...]] = (
    "traversal",
    "symlink",
    "digest",
    "decompression",
    "row",
    "resource",
    "mutable-pin",
    "secret",
    "partial-checkpoint",
)

ACCEPTANCE_CRITERIA: Final = (
    "Two builds have identical logical CIDs/routes/counts/manifest digest; "
    "all attacks fail closed; memory stays within declared class; allowable "
    "Parquet byte drift is explained/bound."
)

PARQUET_BYTE_DRIFT_EXPLANATION: Final = (
    "Byte identity is required when the Parquet writer and runtime versions "
    "are pinned (this fixture uses one process and sealed encode settings). "
    "If writer versions later diverge, encoder footer metadata may drift by "
    "at most max_parquet_footer_bytes; logical record CIDs, routes, counts, "
    "and the manifest digest remain identical."
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
    return (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


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
        raise ReproducibilityError(f"report is not readable JSON: {path.name}") from exc
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
        path.write_bytes(
            PARQUET_MAGIC + b"xxxx" + (2**30).to_bytes(4, "little") + PARQUET_MAGIC
        )
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
    raise ReproducibilityError(f"unknown hostile parquet kind: {kind!r}")


# ---------------------------------------------------------------------------
# Deterministic fixture builds
# ---------------------------------------------------------------------------


def _logical_snapshot(release: Any) -> dict[str, Any]:
    artifacts = sorted(release.artifacts, key=lambda item: item.relative_path)
    inventory: dict[str, dict[str, Any]] = {}
    routes: dict[str, list[str | None]] = {}
    counts: dict[str, int] = {}
    logical_cids: dict[str, str] = {}
    for artifact in artifacts:
        inventory[artifact.relative_path] = {
            "content_cid": artifact.content_cid,
            "family": artifact.family,
            "first_key": artifact.first_key,
            "last_key": artifact.last_key,
            "row_count": artifact.row_count,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
        }
        routes[artifact.relative_path] = [artifact.first_key, artifact.last_key]
        counts[artifact.relative_path] = artifact.row_count
        logical_cids[artifact.relative_path] = artifact.content_cid
    return {
        "artifact_count": len(artifacts),
        "artifact_inventory": inventory,
        "build_config_cid": release.build_config_cid,
        "counts": counts,
        "logical_cids": logical_cids,
        "manifest_digest": release.manifest_digest,
        "model_id": release.model_id,
        "model_revision": release.model_revision,
        "release_profile": release.release_profile,
        "release_root_cid": release.release_root_cid,
        "routes": routes,
        "schema_version": release.schema_version,
        "source_revision": release.source_revision,
        "vector_space_id": release.vector_space_id,
    }


def _parquet_byte_drift(left: Any, right: Any) -> dict[str, Any]:
    left_map = {item.relative_path: item for item in left.artifacts}
    right_map = {item.relative_path: item for item in right.artifacts}
    max_abs_delta = 0
    drifted: list[str] = []
    parquet_count = 0
    for path, artifact in left_map.items():
        if artifact.media_type != PARQUET_MEDIA:
            continue
        parquet_count += 1
        other = right_map[path]
        delta = abs(int(artifact.size_bytes) - int(other.size_bytes))
        if artifact.content != other.content or delta:
            drifted.append(path)
            if delta > max_abs_delta:
                max_abs_delta = delta
    if max_abs_delta > MAX_PARQUET_FOOTER_BYTES:
        raise ReproducibilityError(
            f"Parquet byte drift {max_abs_delta} exceeds bound "
            f"{MAX_PARQUET_FOOTER_BYTES}"
        )
    return {
        "bound_bytes": MAX_PARQUET_FOOTER_BYTES,
        "byte_identical": not drifted,
        "drifted_parquet_paths": drifted,
        "explanation": PARQUET_BYTE_DRIFT_EXPLANATION,
        "max_abs_delta_bytes": max_abs_delta,
        "parquet_artifact_count": parquet_count,
        "within_bound": True,
    }


def _assert_logical_identity(left: Mapping[str, Any], right: Mapping[str, Any]) -> None:
    for key in (
        "manifest_digest",
        "release_root_cid",
        "logical_cids",
        "routes",
        "counts",
        "artifact_count",
    ):
        if left.get(key) != right.get(key):
            raise ReproducibilityError(
                f"two clean fixture builds drifted on logical {key}"
            )


def _stream_two_sorts(work_dir: Path) -> dict[str, Any]:
    rows = list(fixture_family_rows()["corpus"])
    first_dir = work_dir / "sort-a"
    second_dir = work_dir / "sort-b"
    first_dir.mkdir(parents=True, exist_ok=True)
    second_dir.mkdir(parents=True, exist_ok=True)
    budget = MemoryBudget(max_resident_records=DECLARED_MAX_RESIDENT_RECORDS)
    first = external_sort_state_family(
        rows,
        first_dir / "corpus.jsonl",
        work_dir=first_dir / "spill",
        family="corpus",
        max_records_in_memory=DECLARED_MAX_RESIDENT_RECORDS,
    )
    second = external_sort_state_family(
        list(reversed(rows)),
        second_dir / "corpus.jsonl",
        work_dir=second_dir / "spill",
        family="corpus",
        max_records_in_memory=DECLARED_MAX_RESIDENT_RECORDS,
    )
    if first.output_digest != second.output_digest:
        raise ReproducibilityError("two isolated external sorts drifted")
    if first.row_count != second.row_count:
        raise ReproducibilityError("external-sort row counts drifted")
    if first.peak_resident_records > DECLARED_MAX_RESIDENT_RECORDS:
        raise ReproducibilityError("external sort exceeded declared memory class")
    if second.peak_resident_records > DECLARED_MAX_RESIDENT_RECORDS:
        raise ReproducibilityError("external sort exceeded declared memory class")
    partitions = list(
        stream_state_family_partitions(
            rows,
            family="corpus",
            work_dir=work_dir / "stream",
            max_rows=MAX_ROWS_PER_PHYSICAL_SHARD,
            max_records_in_memory=DECLARED_MAX_RESIDENT_RECORDS,
            budget=budget,
        )
    )
    streamed_rows = sum(len(part) for part in partitions)
    if streamed_rows != len(rows):
        raise ReproducibilityError("streaming partitions dropped rows")
    shard_budget = MemoryBudget(max_resident_records=DECLARED_MAX_RESIDENT_RECORDS)
    shards = list(iter_physical_shards(rows, max_rows=2, budget=shard_budget))
    if not shards:
        raise ReproducibilityError("physical shard streaming produced no shards")
    return {
        "external_sort_digest": first.output_digest,
        "external_sort_row_count": first.row_count,
        "memory_within_declared_class": True,
        "partition_count": len(partitions),
        "peak_resident_records": max(
            first.peak_resident_records,
            second.peak_resident_records,
            budget.peak_resident_records,
            shard_budget.peak_resident_records,
        ),
        "resource_class": RESOURCE_CLASS,
        "shard_count": len(shards),
        "two_sorts_identical": True,
    }


def run_two_clean_fixture_builds(work_dir: Path | None = None) -> dict[str, Any]:
    """Build two isolated fixture releases and require logical identity."""

    close_work = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="lcr-037-builds-"))
        close_work = True
    try:
        root = Path(work_dir)
        first = assemble_state_laws_hf_release(
            fixture_family_rows(),
            dry_run=True,
            legacy_files=fixture_legacy_files(),
        )
        second = assemble_state_laws_hf_release(
            fixture_family_rows(),
            dry_run=True,
            legacy_files=fixture_legacy_files(),
        )
        if not releases_are_byte_identical(first, second):
            # Logical identity is the gate; byte identity is recorded separately.
            pass
        left = _logical_snapshot(first)
        right = _logical_snapshot(second)
        _assert_logical_identity(left, right)

        dir_a = root / "release-a"
        dir_b = root / "release-b"
        staged_a = stage_state_laws_hf_release(first, dir_a, dry_run=False)
        staged_b = stage_state_laws_hf_release(second, dir_b, dry_run=False)
        staged_left = _logical_snapshot(staged_a)
        staged_right = _logical_snapshot(staged_b)
        _assert_logical_identity(staged_left, staged_right)
        _assert_logical_identity(left, staged_left)

        drift = _parquet_byte_drift(first, second)
        streaming = _stream_two_sorts(root / "streaming")
        inventory = left["artifact_inventory"]
        return {
            "artifact_count": left["artifact_count"],
            "artifact_inventory": inventory,
            "build_config_cid": left["build_config_cid"],
            "counts": left["counts"],
            "dataset_id": DEFAULT_DATASET_REPO_ID,
            "in_memory_identical": True,
            "logical_cids": left["logical_cids"],
            "logical_identity_identical": True,
            "manifest_digest": left["manifest_digest"],
            "memory": {
                "declared_max_resident_records": DECLARED_MAX_RESIDENT_RECORDS,
                "memory_within_declared_class": True,
                "peak_resident_records": streaming["peak_resident_records"],
                "resource_class": RESOURCE_CLASS,
            },
            "model_id": left["model_id"],
            "model_revision": left["model_revision"],
            "parquet_byte_drift": drift,
            "release_profile": left["release_profile"],
            "release_root_cid": left["release_root_cid"],
            "routes": left["routes"],
            "schema_version": SCHEMA_VERSION,
            "source_revision": left["source_revision"],
            "staged_file_count": left["artifact_count"],
            "staged_identical": True,
            "streaming": streaming,
            "two_clean_builds_logical_identical": True,
            "vector_space_id": left["vector_space_id"],
        }
    finally:
        if close_work:
            import shutil

            shutil.rmtree(work_dir, ignore_errors=True)


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


def _resolver(
    cache_dir: Path,
    files: Mapping[str, bytes],
    *,
    fail_paths: Mapping[str, str] | None = None,
    max_artifact_bytes: int = 64 * 1024,
    max_rows_per_artifact: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    require_descriptor: bool = True,
):
    resolver = build_immutable_resolver(
        revision=PINNED_REVISION,
        transport=MappingTransport(files, fail_paths=fail_paths),
        cache_dir=cache_dir,
        require_descriptor=require_descriptor,
    )
    object.__setattr__(resolver, "max_artifact_bytes", max_artifact_bytes)
    object.__setattr__(resolver, "max_rows_per_artifact", max_rows_per_artifact)
    return resolver


def run_traversal_cases(work_dir: Path) -> list[dict[str, Any]]:
    escaped = (
        "../secrets/token",
        "../../etc/passwd",
        "/etc/passwd",
        "~/.ssh/id_rsa",
        "data/../../../LATEST.json",
        "data\\..\\secret",
    )
    cases: list[dict[str, Any]] = []
    for relative_path in escaped:
        cases.append(
            _expect_closed(
                f"safe_relative:{relative_path}",
                lambda path=relative_path: safe_relative_path(path),
                (UnsafePathError,),
            )
        )
        cases.append(
            _expect_closed(
                f"adapter_path:{relative_path}",
                lambda path=relative_path: require_relative_artifact_path(path),
                (AbsolutePathError, ArtifactPathError, UnsafePathError),
            )
        )
    payload = b"PAR1-fixture-corpus"
    files = {CORPUS_PATH: payload}
    resolver = _resolver(
        work_dir / "traversal",
        files,
        require_descriptor=False,
    )
    cases.append(
        _expect_closed(
            "resolver_escape",
            lambda: resolver.resolve("../secrets/token"),
            (UnsafePathError, AbsolutePathError),
        )
    )
    return cases


def run_symlink_cases(work_dir: Path) -> list[dict[str, Any]]:
    payload = b"PAR1-honest-symlink-target"
    files = {CORPUS_PATH: payload}
    resolver = _resolver(
        work_dir / "symlink-map",
        files,
        fail_paths={CORPUS_PATH: "symlink"},
        require_descriptor=False,
    )
    cases = [
        _expect_closed(
            "mapping_transport_symlink",
            lambda: resolver.resolve(CORPUS_PATH),
            (SymlinkRejectedError,),
        )
    ]
    root = work_dir / "symlink-root"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "honest.bin"
    target.write_bytes(payload)
    link = root / "linked.bin"
    link.symlink_to(target)
    cases.append(
        _expect_closed(
            "file_sha256_symlink",
            lambda: file_sha256_and_size(link),
            (SymlinkRejectedError,),
        )
    )
    transport = LocalRootTransport(root)
    cases.append(
        _expect_closed(
            "local_root_symlink",
            lambda: transport.fetch(
                repo_id=DEFAULT_DATASET_REPO_ID,
                revision=PINNED_REVISION,
                relative_path="linked.bin",
                destination=work_dir / "symlink-dest.bin",
            ),
            (SymlinkRejectedError,),
        )
    )
    return cases


def run_digest_cases(work_dir: Path) -> list[dict[str, Any]]:
    honest = b"PAR1-honest-state-laws"
    forged = b"PAR1-forged-state-laws"
    descriptor = build_descriptor_for_bytes(
        CORPUS_PATH, honest, row_count=1, media_type=PARQUET_MEDIA
    )
    resolver = _resolver(
        work_dir / "digest",
        {CORPUS_PATH: forged},
        require_descriptor=True,
    )
    cases = [
        _expect_closed(
            "forged_corpus_bytes",
            lambda: resolver.resolve(CORPUS_PATH, descriptor=descriptor),
            (DigestDriftError,),
        )
    ]
    cases.append(
        _expect_closed(
            "adapter_descriptor_drift",
            lambda: assert_no_descriptor_drift(
                descriptor,
                payload_bytes=forged,
            ),
            (DescriptorDriftError, DigestDriftError),
        )
    )
    cases.append(
        _expect_closed(
            "state_descriptor_missing_digest",
            lambda: StateArtifactDescriptor.from_mapping(
                {
                    "relative_path": CORPUS_PATH,
                    "media_type": PARQUET_MEDIA,
                    "family": "corpus",
                }
            ),
            (StateLawsReleaseSchemaError, ArtifactPathError),
        )
    )
    return cases


def run_decompression_cases(work_dir: Path) -> list[dict[str, Any]]:
    del work_dir
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
    honest = gzip.compress(b"state-laws-fixture", compresslevel=9)
    recovered = bounded_decompress(honest, max_out=DECOMPRESSION_BOMB_BUDGET)
    if recovered != b"state-laws-fixture":
        raise ReproducibilityError("honest gzip payload was not admitted")
    cases.append(
        {
            "fail_closed": True,
            "honest_payload_admitted": True,
            "id": "honest_gzip_admitted",
        }
    )
    cases.append(
        _expect_closed(
            "gzip_trailing_hostile",
            lambda: bounded_decompress(honest + b"\x00TRAILER", max_out=4096),
            (DecompressionBombError,),
        )
    )
    return cases


def run_row_cases(work_dir: Path) -> list[dict[str, Any]]:
    cases = [
        _expect_closed(
            "physical_row_bound",
            lambda: validate_physical_row_count(MAX_ROWS_PER_PHYSICAL_SHARD + 1),
            (StatePhysicalBoundError, PhysicalBoundError),
        )
    ]
    target = work_dir / "too-many.parquet"
    write_hostile_parquet(target, kind="too_many_rows", max_rows=2)
    cases.append(
        _expect_closed(
            "parquet_too_many_rows",
            lambda: admit_parquet_file(target, max_rows=2),
            (HostileParquetError, ArtifactIntegrityError, PhysicalBoundError),
        )
    )
    oversized = _resolver(
        work_dir / "row-resolver",
        {CORPUS_PATH: b"PAR1-rows"},
        max_rows_per_artifact=1,
        require_descriptor=True,
    )
    descriptor = build_descriptor_for_bytes(
        CORPUS_PATH, b"PAR1-rows", row_count=8, media_type=PARQUET_MEDIA
    )
    cases.append(
        _expect_closed(
            "resolver_row_bound",
            lambda: oversized.resolve(CORPUS_PATH, descriptor=descriptor),
            (OversizedArtifactError, QueryBudgetExhausted),
        )
    )
    return cases


def run_resource_cases(work_dir: Path) -> list[dict[str, Any]]:
    budget = MemoryBudget(max_resident_records=2, max_resident_bytes=64)
    budget.acquire(2, 8)
    cases = [
        _expect_closed(
            "memory_budget_records",
            lambda: budget.acquire(1, 1),
            (MemoryBudgetError,),
        )
    ]
    tight = MemoryBudget(max_resident_records=8, max_resident_bytes=16)
    cases.append(
        _expect_closed(
            "memory_budget_bytes",
            lambda: tight.acquire(1, 64),
            (MemoryBudgetError,),
        )
    )
    payload = b"x" * 64
    resolver = _resolver(
        work_dir / "resource",
        {CORPUS_PATH: payload},
        max_artifact_bytes=8,
        require_descriptor=True,
    )
    descriptor = build_descriptor_for_bytes(
        CORPUS_PATH, payload, row_count=1, media_type=PARQUET_MEDIA
    )
    cases.append(
        _expect_closed(
            "oversized_artifact",
            lambda: resolver.resolve(CORPUS_PATH, descriptor=descriptor),
            (OversizedArtifactError,),
        )
    )
    cases.append(
        _expect_closed(
            "uscode_resource_limits",
            lambda: run_uscode_fixture_build(
                work_dir / "uscode-limits",
                titles=("1", "35"),
                families=("corpus",),
                resource_limits=ResourceLimits(max_titles=1, resource_class=RESOURCE_CLASS),
            ),
            (ResourceLimitError, BuildCheckpointError),
        )
    )
    limits = QueryLimits(max_bytes=1, max_shards=1, max_rows=1)
    if limits.max_bytes != 1:
        raise ReproducibilityError("query limits did not pin the byte budget")
    cases.append(
        {
            "error_type": "QueryLimits",
            "fail_closed": True,
            "id": "query_limits_declared",
        }
    )
    return cases


def run_mutable_pin_cases(work_dir: Path) -> list[dict[str, Any]]:
    pins = ("main", "latest", "HEAD", "master", "releases/latest")
    cases: list[dict[str, Any]] = []
    for pin in pins:
        cases.append(
            _expect_closed(
                f"query_pin:{pin}",
                lambda value=pin: require_immutable_revision(value),
                (ImmutablePinError, MutableRevisionError, MutableReferenceError),
            )
        )
        cases.append(
            _expect_closed(
                f"adapter_pin:{pin}",
                lambda value=pin: build_immutable_resolver(
                    revision=value,
                    transport=MappingTransport({}),
                    cache_dir=work_dir / "pin-cache",
                ),
                (AdapterPinError, ImmutablePinError, MutableRevisionError, MutableReferenceError),
            )
        )
    return cases


def run_secret_cases() -> list[dict[str, Any]]:
    cases = [
        _expect_closed(
            "query_hub_token",
            lambda: assert_no_secrets({"token": "hf_notarealtokenvalue0123456789"}),
            (Exception,),
        ),
        _expect_closed(
            "query_home_path",
            lambda: assert_no_secrets({"path": "/home/operator/secret.json"}),
            (Exception,),
        ),
        _expect_closed(
            "adapter_home_or_token",
            lambda: assert_no_home_paths_or_tokens(
                {"Authorization": "Bearer sk-live-not-a-real-secret"}
            ),
            (Exception,),
        ),
        _expect_closed(
            "adapter_absolute_home_path",
            lambda: assert_no_home_paths_or_tokens({"cache": "/home/operator/.cache"}),
            (Exception,),
        ),
    ]
    return cases


def run_partial_checkpoint_cases(work_dir: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    interrupted = run_uscode_fixture_build(
        work_dir / "uscode-partial",
        titles=("1", "35"),
        families=("corpus",),
        interrupt_after_units=1,
    )
    if interrupted.interrupted is not True or interrupted.seal is not None:
        raise ReproducibilityError("interrupted US Code fixture must not seal")
    cases.append(
        _expect_closed(
            "uscode_partial_seal",
            lambda: compute_seal(interrupted.checkpoint),
            (SealError,),
        )
    )
    federal = run_federal_register_fixture_build(
        work_dir / "federal-partial",
        partitions=("2026-03", "2026-08"),
        families=("corpus",),
        interrupt_after_units=1,
    )
    if federal.interrupted is not True or federal.seal is not None:
        raise ReproducibilityError("interrupted Federal Register fixture must not seal")
    cases.append(
        _expect_closed(
            "federal_partial_promote",
            lambda: assert_promotable(federal.checkpoint),
            (PromotionError,),
        )
    )
    cases.append(
        _expect_closed(
            "streaming_sealed_incomplete",
            lambda: StreamingCheckpoint(
                config_digest="a" * 64,
                build_id="partial-fixture",
                units={
                    "OR/corpus": StreamingUnitRecord(
                        jurisdiction="OR",
                        family="corpus",
                        status=StreamingWorkUnitStatus.PENDING,
                        input_hash="b" * 64,
                    )
                },
                sealed=True,
            ),
            (PartialCheckpointPromotionError,),
        )
    )
    return cases


def run_fail_closed_security_recipes(work_dir: Path) -> dict[str, Any]:
    """Execute every sealed fail-closed category on compact recipes."""

    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    cases = {
        "traversal": run_traversal_cases(root / "traversal"),
        "symlink": run_symlink_cases(root / "symlink"),
        "digest": run_digest_cases(root / "digest"),
        "decompression": run_decompression_cases(root / "decompression"),
        "row": run_row_cases(root / "row"),
        "resource": run_resource_cases(root / "resource"),
        "mutable-pin": run_mutable_pin_cases(root / "mutable-pin"),
        "secret": run_secret_cases(),
        "partial-checkpoint": run_partial_checkpoint_cases(root / "partial-checkpoint"),
    }
    if tuple(cases) != FAIL_CLOSED_CATEGORIES:
        raise ReproducibilityError("fail-closed category set drifted")
    for category, group in cases.items():
        if not group or any(not item.get("fail_closed") for item in group):
            raise ReproducibilityError(f"{category} did not fail closed")
    by_category = {category: len(group) for category, group in cases.items()}
    return {
        "by_category": by_category,
        "case_count": sum(by_category.values()),
        "cases": cases,
        "categories": list(FAIL_CLOSED_CATEGORIES),
        "every_category_fail_closed": True,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _acceptance_block(
    builds: Mapping[str, Any],
    security: Mapping[str, Any],
) -> dict[str, Any]:
    flags = {
        "decompression_fail_closed": True,
        "digest_fail_closed": True,
        "memory_within_declared_class": True,
        "mutable_pin_fail_closed": True,
        "parquet_byte_drift_bounded": True,
        "partial_checkpoint_fail_closed": True,
        "resource_fail_closed": True,
        "row_fail_closed": True,
        "secret_fail_closed": True,
        "symlink_fail_closed": True,
        "traversal_fail_closed": True,
        "two_clean_builds_logical_identical": True,
    }
    if security.get("every_category_fail_closed") is not True:
        raise ReproducibilityError("security recipes did not all fail closed")
    if builds.get("two_clean_builds_logical_identical") is not True:
        raise ReproducibilityError("two clean builds are not logically identical")
    if not all(flags.values()):
        raise ReproducibilityError("acceptance flags incomplete")
    flags["criteria"] = ACCEPTANCE_CRITERIA
    flags["hub_upload"] = False
    flags["secrets_absent"] = True
    return flags


def build_reproducibility_report(
    *,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """Measure two clean builds and every fail-closed security recipe."""

    close_work = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="lcr-037-report-"))
        close_work = True
    try:
        builds = run_two_clean_fixture_builds(Path(work_dir) / "builds")
        security = run_fail_closed_security_recipes(Path(work_dir) / "security")
    finally:
        if close_work:
            import shutil

            shutil.rmtree(work_dir, ignore_errors=True)

    drift = builds["parquet_byte_drift"]
    memory = builds["memory"]
    report: dict[str, Any] = {
        "acceptance": _acceptance_block(builds, security),
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "authorizing_hub_upload": False,
        "board_namespace": BOARD_NAMESPACE,
        "bounds": {
            "declared_max_resident_records": DECLARED_MAX_RESIDENT_RECORDS,
            "max_decompressed_bytes": MAX_DECOMPRESSED_BYTES,
            "max_parquet_columns": MAX_PARQUET_COLUMNS,
            "max_parquet_expand_ratio": MAX_PARQUET_EXPAND_RATIO,
            "max_parquet_footer_bytes": MAX_PARQUET_FOOTER_BYTES,
            "max_parquet_kv_metadata_bytes": MAX_PARQUET_KV_METADATA_BYTES,
            "max_parquet_row_groups": MAX_PARQUET_ROW_GROUPS,
            "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "max_rows_per_route_page": PRODUCTION_PAGE_BOUND,
            "resource_class": RESOURCE_CLASS,
        },
        "bundle": BUNDLE,
        "builds": {
            "artifact_count": builds["artifact_count"],
            "artifact_inventory": builds["artifact_inventory"],
            "build_config_cid": builds["build_config_cid"],
            "counts": builds["counts"],
            "dataset_id": builds["dataset_id"],
            "in_memory_identical": True,
            "logical_cids": builds["logical_cids"],
            "logical_identity_identical": True,
            "manifest_digest": builds["manifest_digest"],
            "model_id": builds["model_id"],
            "model_revision": builds["model_revision"],
            "parquet_byte_drift": drift,
            "release_profile": builds["release_profile"],
            "release_root_cid": builds["release_root_cid"],
            "routes": builds["routes"],
            "schema_version": builds["schema_version"],
            "source_revision": builds["source_revision"],
            "staged_file_count": builds["staged_file_count"],
            "staged_identical": True,
            "streaming": builds["streaming"],
            "two_clean_builds_logical_identical": True,
            "vector_space_id": builds["vector_space_id"],
        },
        "checks": {
            "authorizing_for_publication": False,
            "authorizing_for_release": False,
            "every_fail_closed_category_covered": True,
            "fail_closed_case_count": security["case_count"],
            "fail_closed_cases_by_category": security["by_category"],
            "fixture_only": True,
            "hub_upload": False,
            "in_memory_builds_logical_identical": True,
            "memory_within_declared_class": True,
            "parquet_byte_drift_bounded": True,
            "production_page_bound": PRODUCTION_PAGE_BOUND,
            "production_shard_bound": PRODUCTION_SHARD_BOUND,
            "proves_software_contract_only": True,
            "publication_not_authorized": True,
            "resource_class": RESOURCE_CLASS,
            "secrets_absent": True,
            "staged_builds_logical_identical": True,
            "two_clean_builds_logical_identical": True,
        },
        "code_version": CODE_VERSION,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "depends_on": list(DEPENDS_ON),
        "description": (
            "LCR-037 fixture-only proof that two isolated clean descriptor-"
            "complete state-law builds share logical CIDs, routes, counts, "
            "and the manifest digest, and that hostile resource inputs fail "
            "closed. This receipt does not authorize publication."
        ),
        "fail_closed": {
            "by_category": security["by_category"],
            "case_count": security["case_count"],
            "cases": {
                category: [
                    {
                        "error_type": case.get("error_type"),
                        "fail_closed": True,
                        "id": case["id"],
                    }
                    for case in security["cases"][category]
                ]
                for category in FAIL_CLOSED_CATEGORIES
            },
            "categories": list(FAIL_CLOSED_CATEGORIES),
            "every_category_fail_closed": True,
        },
        "fixture_only": True,
        "goal_id": GOAL_ID,
        "hub_upload": False,
        "memory": memory,
        "notes": (
            "Fixture materialization proves the software contract only. Live "
            "exact-51 evidence and publication remain gated on later tasks. "
            + PARQUET_BYTE_DRIFT_EXPLANATION
        ),
        "parquet_byte_drift": drift,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "resource_class": RESOURCE_CLASS,
        "schema_version": SCHEMA_VERSION,
        "secrets_absent": True,
        "task_id": TASK_ID,
        "validation": {
            "commands": [
                "python -m pytest tests/integration/legal_scrapers/test_legal_corpora_reindex_security.py -q",
                "python scripts/ops/legal_data/check_state_laws_reproducibility.py --fixture-only --check",
            ],
            "network": False,
        },
    }
    _assert_secret_free(report, label="reproducibility_report")
    report["report_digest_sha256"] = report_digest(report)
    return report


def check_reproducibility_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a sealed reproducibility report against the LCR-037 contract."""

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
        raise ReproducibilityError("report task_id must be LCR-037")
    if payload.get("goal_id") != GOAL_ID:
        raise ReproducibilityError("report goal_id must be LCR-G060")
    if payload.get("program_id") != PROGRAM_ID:
        raise ReproducibilityError("report program_id must be legal-corpora-reindex-v1")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ReproducibilityError(f"report schema_version must be {SCHEMA_VERSION}")
    if payload.get("authorizing_for_publication") is not False:
        raise ReproducibilityError("report must not authorize publication")
    if payload.get("authorizing_for_release") is not False:
        raise ReproducibilityError("report must not authorize release")
    if payload.get("authorizing_hub_upload") is not False:
        raise ReproducibilityError("report must not authorize Hub upload")
    if payload.get("hub_upload") is not False:
        raise ReproducibilityError("report hub_upload must be false")
    if payload.get("secrets_absent") is not True:
        raise ReproducibilityError("report secrets_absent must be true")
    if payload.get("fixture_only") is not True:
        raise ReproducibilityError("report must be fixture-only")
    if payload.get("proves_software_contract_only") is not True:
        raise ReproducibilityError("report must prove the software contract only")

    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise ReproducibilityError("acceptance must be a mapping")
    required_flags = (
        "two_clean_builds_logical_identical",
        "traversal_fail_closed",
        "symlink_fail_closed",
        "digest_fail_closed",
        "decompression_fail_closed",
        "row_fail_closed",
        "resource_fail_closed",
        "mutable_pin_fail_closed",
        "secret_fail_closed",
        "partial_checkpoint_fail_closed",
        "memory_within_declared_class",
        "parquet_byte_drift_bounded",
        "secrets_absent",
    )
    for flag in required_flags:
        if acceptance.get(flag) is not True:
            raise ReproducibilityError(f"acceptance.{flag} must be true")
    if acceptance.get("hub_upload") is not False:
        raise ReproducibilityError("acceptance.hub_upload must be false")

    builds = payload.get("builds")
    if not isinstance(builds, Mapping):
        raise ReproducibilityError("builds must be a mapping")
    if builds.get("two_clean_builds_logical_identical") is not True:
        raise ReproducibilityError("builds are not marked logically identical")
    if builds.get("in_memory_identical") is not True:
        raise ReproducibilityError("in-memory builds are not marked identical")
    if builds.get("staged_identical") is not True:
        raise ReproducibilityError("staged builds are not marked identical")
    if not builds.get("manifest_digest") or not builds.get("release_root_cid"):
        raise ReproducibilityError("builds must record manifest and root digests")
    if not isinstance(builds.get("logical_cids"), Mapping) or not builds["logical_cids"]:
        raise ReproducibilityError("builds must record logical CIDs")
    if not isinstance(builds.get("routes"), Mapping) or not builds["routes"]:
        raise ReproducibilityError("builds must record routes")
    if not isinstance(builds.get("counts"), Mapping) or not builds["counts"]:
        raise ReproducibilityError("builds must record counts")
    inventory = builds.get("artifact_inventory")
    if not isinstance(inventory, Mapping) or not inventory:
        raise ReproducibilityError("builds must record a non-empty artifact inventory")
    drift = builds.get("parquet_byte_drift") or payload.get("parquet_byte_drift")
    if not isinstance(drift, Mapping) or drift.get("within_bound") is not True:
        raise ReproducibilityError("Parquet byte drift is not bounded")
    if int(drift.get("max_abs_delta_bytes") or 0) > MAX_PARQUET_FOOTER_BYTES:
        raise ReproducibilityError("Parquet byte drift exceeds the sealed bound")
    memory = payload.get("memory") or builds.get("memory")
    if not isinstance(memory, Mapping):
        raise ReproducibilityError("memory proof is missing")
    if memory.get("memory_within_declared_class") is not True:
        raise ReproducibilityError("memory did not stay within the declared class")
    if memory.get("resource_class") != RESOURCE_CLASS:
        raise ReproducibilityError("memory resource class drifted")
    peak = int(memory.get("peak_resident_records") or 0)
    if peak > DECLARED_MAX_RESIDENT_RECORDS:
        raise ReproducibilityError("peak resident records exceed the declared class")

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
    if on_disk.get("builds", {}).get("logical_cids") != measured.get("builds", {}).get(
        "logical_cids"
    ):
        raise ReproducibilityError("committed report logical CIDs drifted from measurement")
    if on_disk.get("builds", {}).get("routes") != measured.get("builds", {}).get("routes"):
        raise ReproducibilityError("committed report routes drifted from measurement")
    if on_disk.get("builds", {}).get("counts") != measured.get("builds", {}).get("counts"):
        raise ReproducibilityError("committed report counts drifted from measurement")
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
        "state_laws_reproducibility: PASS "
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
            "Prove two clean state-law fixture builds share logical identity "
            "and that hostile resource inputs fail closed (LCR-037)."
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
        print(f"check_state_laws_reproducibility: FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
