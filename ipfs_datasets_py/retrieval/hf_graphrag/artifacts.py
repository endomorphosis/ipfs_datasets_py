"""Shared bounded artifact writers for Hugging Face GraphRAG releases (USCIR-009).

Domain-neutral helpers that consolidate the strongest CVEfixes and SkillCenter
patterns:

* deterministic sort + stable tie-breakers;
* physical sharding at most 4,096 rows/pointers;
* confined release-relative paths;
* ZSTD Parquet with fixed row-group size;
* row/byte/hash descriptors and compact routing indexes;
* atomic local staging with cleanup on failure; and
* deterministic fixture output for unit tests.

Domain builders (US Code, SkillCenter, CVEfixes) wrap these helpers; this
module owns no domain ontology.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Final, Optional

from ipfs_datasets_py.logic.ir_core.identity import cid_v1_from_digest

from .schema import (
    COMPACT_INDEX_SCHEMA_VERSION,
    DESCRIPTOR_SCHEMA_VERSION,
    MAX_POINTERS_PER_ROW,
    MAX_ROUTING_ROWS_PER_INDEX,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    PARQUET_COMPRESSION,
    PARQUET_COMPRESSION_LEVEL,
    PARQUET_MAGIC,
    PARQUET_MEDIA_TYPE,
    ArtifactDescriptor,
    ArtifactFamily,
    ArtifactPathError,
    CompactIndexRow,
    HfGraphragSchemaError,
    PhysicalBoundError,
    canonical_json_bytes,
    chunk_pointers,
    normalize_relative_artifact_path,
    part_filename,
    physical_bounds_policy,
    shard_sequence,
    stable_sort_rows,
    validate_physical_pointer_count,
    validate_physical_row_count,
)

# ---------------------------------------------------------------------------
# Module identity
# ---------------------------------------------------------------------------

ARTIFACT_WRITER_SCHEMA_VERSION: Final = "hf-graphrag-artifact-writer/v1"
DEFAULT_PART_WIDTH: Final = 6
_STAGING_PREFIX: Final = ".hf-graphrag-stage-"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HfGraphragArtifactError(HfGraphragSchemaError):
    """Raised when a bounded artifact writer cannot complete safely."""


class ArtifactIntegrityError(HfGraphragArtifactError):
    """Raised when on-disk bytes disagree with a descriptor."""


class ArtifactStagingError(HfGraphragArtifactError):
    """Raised when atomic staging or cleanup fails."""


# ---------------------------------------------------------------------------
# Writer configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArtifactWriterConfig:
    """Explicit physical bounds and Parquet writer settings."""

    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    max_pointers_per_row: int = MAX_POINTERS_PER_ROW
    max_routing_rows: int = MAX_ROUTING_ROWS_PER_INDEX
    compression: str = PARQUET_COMPRESSION
    compression_level: int = PARQUET_COMPRESSION_LEVEL
    part_width: int = DEFAULT_PART_WIDTH
    schema_version: str = ARTIFACT_WRITER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_rows_per_shard, int)
            or isinstance(self.max_rows_per_shard, bool)
            or self.max_rows_per_shard <= 0
        ):
            raise PhysicalBoundError("max_rows_per_shard must be a positive integer")
        if self.max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise PhysicalBoundError(
                f"max_rows_per_shard={self.max_rows_per_shard} exceeds "
                f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        if (
            not isinstance(self.max_pointers_per_row, int)
            or isinstance(self.max_pointers_per_row, bool)
            or self.max_pointers_per_row <= 0
        ):
            raise PhysicalBoundError(
                "max_pointers_per_row must be a positive integer"
            )
        if self.max_pointers_per_row > MAX_POINTERS_PER_ROW:
            raise PhysicalBoundError(
                f"max_pointers_per_row={self.max_pointers_per_row} exceeds "
                f"{MAX_POINTERS_PER_ROW}"
            )
        if (
            not isinstance(self.max_routing_rows, int)
            or isinstance(self.max_routing_rows, bool)
            or self.max_routing_rows <= 0
        ):
            raise PhysicalBoundError("max_routing_rows must be a positive integer")
        if self.max_routing_rows > MAX_ROUTING_ROWS_PER_INDEX:
            raise PhysicalBoundError(
                f"max_routing_rows={self.max_routing_rows} exceeds "
                f"{MAX_ROUTING_ROWS_PER_INDEX}"
            )
        if self.compression != PARQUET_COMPRESSION:
            raise HfGraphragArtifactError(
                "bounded artifact writers require zstd compression"
            )
        if (
            not isinstance(self.compression_level, int)
            or isinstance(self.compression_level, bool)
            or self.compression_level <= 0
        ):
            raise HfGraphragArtifactError(
                "compression_level must be a positive integer"
            )
        if (
            not isinstance(self.part_width, int)
            or isinstance(self.part_width, bool)
            or self.part_width < 1
        ):
            raise HfGraphragArtifactError("part_width must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "compression": self.compression,
            "compression_level": self.compression_level,
            "max_pointers_per_row": self.max_pointers_per_row,
            "max_routing_rows": self.max_routing_rows,
            "max_rows_per_shard": self.max_rows_per_shard,
            "part_width": self.part_width,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ShardWriteResult:
    """Outcome of writing one ordered family of bounded shards."""

    data_descriptors: tuple[ArtifactDescriptor, ...]
    compact_index_rows: tuple[CompactIndexRow, ...]
    compact_index_descriptor: Optional[ArtifactDescriptor]
    total_rows: int
    config: ArtifactWriterConfig

    def to_dict(self) -> dict[str, Any]:
        return {
            "compact_index": (
                self.compact_index_descriptor.to_dict()
                if self.compact_index_descriptor is not None
                else None
            ),
            "compact_index_rows": [row.to_dict() for row in self.compact_index_rows],
            "config": self.config.to_dict(),
            "data_descriptors": [item.to_dict() for item in self.data_descriptors],
            "total_rows": self.total_rows,
        }


# ---------------------------------------------------------------------------
# Path confinement and digests
# ---------------------------------------------------------------------------


def resolve_release_root(root: str | Path, *, must_exist: bool = False) -> Path:
    """Resolve *root* to an absolute directory path (no symlink roots)."""

    candidate = Path(root).expanduser()
    if candidate.is_symlink():
        raise ArtifactPathError("release root must not be a symlink")
    try:
        resolved = candidate.resolve(strict=must_exist)
    except OSError as exc:
        raise ArtifactPathError(f"release root does not exist: {root}") from exc
    if must_exist and not resolved.is_dir():
        raise ArtifactPathError(f"release root is not a directory: {root}")
    if not must_exist and resolved.exists() and not resolved.is_dir():
        raise ArtifactPathError(f"release root must be a directory: {root}")
    return resolved


def confine_path(root: str | Path, relative_path: str | Path) -> Path:
    """Join *relative_path* under *root* and fail closed on escape."""

    root_path = resolve_release_root(root, must_exist=False)
    relative = normalize_relative_artifact_path(
        relative_path if isinstance(relative_path, str) else relative_path.as_posix()
    )
    target = root_path.joinpath(*PurePosixPath(relative).parts)
    try:
        # resolve(strict=False) so parents need not exist yet, then re-check.
        resolved = target.resolve(strict=False)
        resolved.relative_to(root_path.resolve(strict=False))
    except ValueError as exc:
        raise ArtifactPathError(
            f"path escapes release root: {relative!r}"
        ) from exc
    if target.is_symlink():
        raise ArtifactPathError(f"artifact path must not be a symlink: {relative!r}")
    return target


def file_digest(path: str | Path) -> tuple[int, bytes]:
    """Return ``(byte_length, sha256_digest_bytes)`` for a regular file."""

    target = Path(path)
    if target.is_symlink() or not target.is_file():
        raise ArtifactIntegrityError(f"not a regular file: {target}")
    digest = sha256()
    size = 0
    with target.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.digest()


def manifest_descriptor(descriptor: ArtifactDescriptor) -> dict[str, Any]:
    """Return the shared manifest form, including the resolver's CID alias."""

    payload = descriptor.to_dict()
    if descriptor.content_cid is not None:
        payload["cid"] = descriptor.content_cid
    return payload


def describe_file(
    path: str | Path,
    *,
    root: str | Path,
    row_count: int = 0,
    family: ArtifactFamily | str = ArtifactFamily.CORPUS,
    media_type: str = PARQUET_MEDIA_TYPE,
    schema_id: str = DESCRIPTOR_SCHEMA_VERSION,
    first_key: Optional[str] = None,
    last_key: Optional[str] = None,
    shard_id: Optional[int] = None,
    metadata: Mapping[str, Any] | None = None,
) -> ArtifactDescriptor:
    """Build a verified :class:`ArtifactDescriptor` for *path* under *root*."""

    root_path = resolve_release_root(root, must_exist=True)
    file_path = Path(path).expanduser().resolve()
    try:
        relative = file_path.relative_to(root_path).as_posix()
    except ValueError as exc:
        raise ArtifactPathError(f"path escapes release root: {file_path}") from exc
    size_bytes, digest = file_digest(file_path)
    return ArtifactDescriptor(
        relative_path=relative,
        sha256=digest.hex(),
        size_bytes=size_bytes,
        row_count=row_count,
        media_type=media_type,
        schema_id=schema_id,
        family=family,
        content_cid=cid_v1_from_digest(digest),
        first_key=first_key,
        last_key=last_key,
        shard_id=shard_id,
        key_range=(
            (first_key, last_key)
            if first_key is not None and last_key is not None
            else None
        ),
        metadata=metadata or {},
    )


def verify_descriptor(
    root: str | Path,
    descriptor: ArtifactDescriptor | Mapping[str, Any],
) -> Path:
    """Rehash *descriptor* on disk and fail closed on any mismatch."""

    desc = (
        descriptor
        if isinstance(descriptor, ArtifactDescriptor)
        else ArtifactDescriptor.from_mapping(descriptor)
    )
    path = confine_path(root, desc.relative_path)
    if path.is_symlink() or not path.is_file():
        raise ArtifactIntegrityError(
            f"descriptor path is missing or unsafe: {desc.relative_path}"
        )
    size_bytes, digest = file_digest(path)
    if size_bytes != desc.size_bytes or digest.hex() != desc.sha256:
        raise ArtifactIntegrityError(
            f"descriptor failed size/sha256 verification: {desc.relative_path}"
        )
    if desc.content_cid is not None:
        expected = cid_v1_from_digest(digest)
        if desc.content_cid != expected:
            raise ArtifactIntegrityError(
                f"descriptor failed CID verification: {desc.relative_path}"
            )
    return path


# ---------------------------------------------------------------------------
# Atomic staging with cleanup on failure
# ---------------------------------------------------------------------------


@dataclass
class StagingSession:
    """Tracks a temporary staging directory under a release root."""

    root: Path
    staging_dir: Path
    _committed: bool = False
    _cleaned: bool = False

    @property
    def path(self) -> Path:
        return self.staging_dir

    def confine(self, relative_path: str | Path) -> Path:
        return confine_path(self.staging_dir, relative_path)

    def commit_file(self, relative_path: str, *, overwrite: bool = True) -> Path:
        """Atomically move one staged file into the release root."""

        relative = normalize_relative_artifact_path(relative_path)
        source = confine_path(self.staging_dir, relative)
        if not source.is_file():
            raise ArtifactStagingError(f"staged file missing: {relative}")
        destination = confine_path(self.root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not overwrite:
            raise ArtifactStagingError(f"destination already exists: {relative}")
        os.replace(source, destination)
        return destination

    def commit_tree(self, relative_dir: str, *, overwrite: bool = True) -> Path:
        """Atomically promote a staged directory into the release root."""

        relative = normalize_relative_artifact_path(relative_dir)
        source = confine_path(self.staging_dir, relative)
        if not source.is_dir():
            raise ArtifactStagingError(f"staged directory missing: {relative}")
        destination = confine_path(self.root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if not overwrite:
                raise ArtifactStagingError(
                    f"destination already exists: {relative}"
                )
            if destination.is_symlink() or not destination.is_dir():
                raise ArtifactStagingError(
                    f"destination path is unsafe: {relative}"
                )
            backup = self.staging_dir / f".replaced-{PurePosixPath(relative).name}"
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            os.replace(destination, backup)
            try:
                os.replace(source, destination)
            except Exception:
                if backup.exists() and not destination.exists():
                    os.replace(backup, destination)
                raise
        else:
            os.replace(source, destination)
        return destination

    def mark_committed(self) -> None:
        self._committed = True

    def cleanup(self) -> None:
        """Remove the staging directory (no-op if already cleaned)."""

        if self._cleaned:
            return
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir, ignore_errors=True)
        self._cleaned = True


@contextmanager
def atomic_staging(
    root: str | Path,
    *,
    prefix: str = _STAGING_PREFIX,
) -> Iterator[StagingSession]:
    """Stage writes under *root*; cleanup automatically on failure.

    On success the caller must move artifacts out of the staging directory
    (via :meth:`StagingSession.commit_file` / ``commit_tree``) and the context
    still removes any leftover staging files.  On exception the entire staging
    tree is deleted so partial artifacts never remain.
    """

    release_root = resolve_release_root(root, must_exist=False)
    release_root.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=prefix, dir=str(release_root))
    )
    session = StagingSession(root=release_root, staging_dir=staging_dir)
    success = False
    try:
        yield session
        success = True
        session.mark_committed()
    finally:
        # Always cleanup leftover staging content.  On failure this removes
        # partial outputs; on success it removes empty/residual staging dirs.
        session.cleanup()
        if not success:
            # Explicit branch for readability in tests/tracing.
            pass


def atomic_write_bytes(path: str | Path, payload: bytes) -> Path:
    """Write *payload* atomically with partial-file cleanup on failure."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.partial")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
        raise
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
    return target


def atomic_write_canonical_json(path: str | Path, value: Any) -> Path:
    """Write sorted-key JSON bytes atomically."""

    return atomic_write_bytes(path, canonical_json_bytes(value) + b"\n")


# ---------------------------------------------------------------------------
# Parquet writers
# ---------------------------------------------------------------------------


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "hf_graphrag artifact writers require the optional 'pyarrow' package"
        ) from exc
    return pa, pq


def validate_zstd_parquet(
    path: str | Path,
    *,
    max_rows: int | None = MAX_ROWS_PER_PHYSICAL_SHARD,
    expected_row_count: int | None = None,
) -> int:
    """Validate Parquet magic, ZSTD compression, readability, and row bounds."""

    target = Path(path)
    if not target.is_file():
        raise ArtifactIntegrityError(f"Parquet file is missing: {target}")
    header = target.read_bytes()[:4]
    if header != PARQUET_MAGIC:
        raise ArtifactIntegrityError(f"Parquet magic missing: {target}")
    _, pq = _pyarrow()
    try:
        parquet = pq.ParquetFile(target)
    except Exception as exc:
        raise ArtifactIntegrityError(
            f"Parquet file is unreadable: {target}"
        ) from exc
    row_count = int(parquet.metadata.num_rows)
    if max_rows is not None and row_count > max_rows:
        raise PhysicalBoundError(
            f"Parquet file exceeds row limit {max_rows}: {target}"
        )
    if expected_row_count is not None and row_count != expected_row_count:
        raise ArtifactIntegrityError(
            f"Parquet row count mismatch for {target}: "
            f"expected {expected_row_count}, got {row_count}"
        )
    compressions = {
        parquet.metadata.row_group(group).column(column).compression
        for group in range(parquet.metadata.num_row_groups)
        for column in range(parquet.metadata.row_group(group).num_columns)
    }
    if parquet.metadata.num_row_groups and compressions != {"ZSTD"}:
        raise ArtifactIntegrityError(
            f"Parquet file is not uniformly ZSTD-compressed: {target}"
        )
    return row_count


def write_zstd_parquet(
    path: str | Path,
    rows: Sequence[Mapping[str, Any]] | Any,
    *,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    config: ArtifactWriterConfig | None = None,
    schema: Any | None = None,
) -> int:
    """Atomically write a ZSTD Parquet shard with fixed writer settings.

    Accepts either a sequence of row mappings or a pyarrow Table.  Enforces
    the physical row bound and cleans up partial files on failure.
    """

    selected = config or ArtifactWriterConfig(max_rows_per_shard=max_rows)
    if max_rows != selected.max_rows_per_shard and config is None:
        selected = ArtifactWriterConfig(max_rows_per_shard=max_rows)
    pa, pq = _pyarrow()
    if hasattr(rows, "num_rows") and hasattr(rows, "schema"):
        table = rows
    else:
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise HfGraphragArtifactError("rows must be a sequence of mappings")
        materialised = [dict(row) for row in rows]
        if schema is not None:
            table = pa.Table.from_pylist(materialised, schema=schema)
        elif not materialised:
            # Empty shard/index: emit a zero-row table with a placeholder column
            # so Parquet encoding remains well-defined and deterministic.
            table = pa.table({"_empty": pa.array([], type=pa.int8())})
        else:
            table = pa.Table.from_pylist(materialised)
    row_count = int(table.num_rows)
    if row_count > selected.max_rows_per_shard:
        raise PhysicalBoundError(
            f"Parquet shard exceeds {selected.max_rows_per_shard} rows: {path}"
        )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.partial")
    try:
        pq.write_table(
            table,
            temporary,
            compression=selected.compression,
            compression_level=selected.compression_level,
            row_group_size=selected.max_rows_per_shard,
            use_dictionary=True,
            write_statistics=True,
            write_page_index=False,
            data_page_version="1.0",
        )
        validate_zstd_parquet(
            temporary,
            max_rows=selected.max_rows_per_shard,
            expected_row_count=row_count,
        )
        os.replace(temporary, target)
    except Exception:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
        raise
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
    return row_count


def _key_from_row(
    row: Mapping[str, Any],
    key_fields: Sequence[str],
) -> str:
    if not key_fields:
        raise HfGraphragArtifactError("key_fields must not be empty")
    parts: list[str] = []
    for name in key_fields:
        if name not in row:
            raise HfGraphragArtifactError(
                f"key field missing from row: {name!r}"
            )
        parts.append(str(row[name]))
    return "\x1f".join(parts) if len(parts) > 1 else parts[0]


def write_bounded_shards(
    rows: Sequence[Mapping[str, Any]],
    *,
    root: str | Path,
    data_dir: str,
    index_path: str | None = None,
    family: ArtifactFamily | str = ArtifactFamily.CORPUS,
    kind: str | None = None,
    primary_keys: Sequence[str] = (),
    tie_breakers: Sequence[str] = ("entry_cid",),
    descending: Sequence[str] = (),
    key_fields: Sequence[str] | None = None,
    document_index_field: str | None = "document_index",
    config: ArtifactWriterConfig | None = None,
    sort: bool = True,
    schema_id: str = DESCRIPTOR_SCHEMA_VERSION,
) -> ShardWriteResult:
    """Sort (optionally), shard, write, and describe a family of rows.

    Writes ``data_dir/part-NNNNNN.parquet`` under *root*, optionally emits a
    compact routing index at *index_path*, and returns verified descriptors.
    All intermediate work uses atomic staging with cleanup on failure.
    """

    selected = config or ArtifactWriterConfig()
    family_value = ArtifactFamily.coerce(family)
    kind_value = kind or family_value.value
    release_root = resolve_release_root(root, must_exist=False)
    release_root.mkdir(parents=True, exist_ok=True)
    data_relative = normalize_relative_artifact_path(data_dir)
    index_relative = (
        normalize_relative_artifact_path(index_path)
        if index_path is not None
        else None
    )

    if sort and primary_keys:
        ordered = stable_sort_rows(
            rows,
            primary_keys,
            tie_breakers=tie_breakers,
            descending=descending,
        )
    else:
        ordered = tuple(dict(row) for row in rows)

    if not ordered:
        # Empty family: still valid; no data shards, optional empty index.
        compact_rows: tuple[CompactIndexRow, ...] = ()
        index_descriptor: Optional[ArtifactDescriptor] = None
        if index_relative is not None:
            with atomic_staging(release_root) as session:
                staged_index = session.confine(index_relative)
                write_zstd_parquet(
                    staged_index,
                    (),
                    max_rows=selected.max_routing_rows,
                    config=ArtifactWriterConfig(
                        max_rows_per_shard=selected.max_routing_rows,
                        max_pointers_per_row=selected.max_pointers_per_row,
                        max_routing_rows=selected.max_routing_rows,
                        compression=selected.compression,
                        compression_level=selected.compression_level,
                        part_width=selected.part_width,
                    ),
                )
                session.commit_file(index_relative)
            index_descriptor = describe_file(
                confine_path(release_root, index_relative),
                root=release_root,
                row_count=0,
                family=ArtifactFamily.ROUTING_INDEX,
                schema_id=COMPACT_INDEX_SCHEMA_VERSION,
            )
        return ShardWriteResult(
            data_descriptors=(),
            compact_index_rows=compact_rows,
            compact_index_descriptor=index_descriptor,
            total_rows=0,
            config=selected,
        )

    key_cols = tuple(key_fields) if key_fields is not None else (
        tuple(tie_breakers) if tie_breakers else tuple(primary_keys)
    )
    if not key_cols:
        key_cols = ("entry_cid",)

    shards = shard_sequence(ordered, max_rows=selected.max_rows_per_shard)
    data_descriptors: list[ArtifactDescriptor] = []
    compact_index: list[CompactIndexRow] = []
    pending_relatives: list[str] = []

    with atomic_staging(release_root) as session:
        # Write every artifact into the staging tree first.  Nothing is
        # promoted until the full family succeeds, so failures clean up.
        for shard_id, group in enumerate(shards):
            if not group:
                continue
            validate_physical_row_count(
                len(group),
                maximum=selected.max_rows_per_shard,
            )
            relative = (
                f"{data_relative}/"
                f"{part_filename(shard_id, width=selected.part_width)}"
            )
            staged_path = session.confine(relative)
            write_zstd_parquet(
                staged_path,
                group,
                max_rows=selected.max_rows_per_shard,
                config=selected,
            )
            pending_relatives.append(relative)
            first_key = _key_from_row(group[0], key_cols)
            last_key = _key_from_row(group[-1], key_cols)
            start_doc: Optional[int] = None
            end_doc: Optional[int] = None
            if document_index_field and document_index_field in group[0]:
                start_doc = int(group[0][document_index_field])
                end_doc = int(group[-1][document_index_field])
            # Describe against the staging root; relative paths match final.
            staged_descriptor = describe_file(
                staged_path,
                root=session.staging_dir,
                row_count=len(group),
                family=family_value,
                schema_id=schema_id,
                first_key=first_key,
                last_key=last_key,
                shard_id=shard_id,
            )
            data_descriptors.append(staged_descriptor)
            compact_index.append(
                CompactIndexRow(
                    relative_path=staged_descriptor.relative_path,
                    sha256=staged_descriptor.sha256,
                    size_bytes=staged_descriptor.size_bytes,
                    row_count=staged_descriptor.row_count,
                    shard_id=shard_id,
                    first_key=first_key,
                    last_key=last_key,
                    kind=kind_value,
                    content_cid=staged_descriptor.content_cid,
                    start_document_index=start_doc,
                    end_document_index=end_doc,
                )
            )

        index_descriptor = None
        if index_relative is not None:
            if len(compact_index) > selected.max_routing_rows:
                raise PhysicalBoundError(
                    f"compact index has {len(compact_index)} rows; "
                    f"exceeds {selected.max_routing_rows}"
                )
            index_rows = [row.to_dict() for row in compact_index]
            staged_index = session.confine(index_relative)
            write_zstd_parquet(
                staged_index,
                index_rows,
                max_rows=selected.max_routing_rows,
                config=ArtifactWriterConfig(
                    max_rows_per_shard=selected.max_routing_rows,
                    max_pointers_per_row=selected.max_pointers_per_row,
                    max_routing_rows=selected.max_routing_rows,
                    compression=selected.compression,
                    compression_level=selected.compression_level,
                    part_width=selected.part_width,
                ),
            )
            pending_relatives.append(index_relative)
            index_descriptor = describe_file(
                staged_index,
                root=session.staging_dir,
                row_count=len(compact_index),
                family=ArtifactFamily.ROUTING_INDEX,
                schema_id=COMPACT_INDEX_SCHEMA_VERSION,
            )

        # Promote only after every staged write succeeded.  Track promotions
        # so a mid-commit failure can roll back already-moved files.
        promoted: list[str] = []
        try:
            for relative in pending_relatives:
                session.commit_file(relative)
                promoted.append(relative)
        except Exception:
            for relative in reversed(promoted):
                final = confine_path(release_root, relative)
                if final.exists():
                    final.unlink(missing_ok=True)
            raise
        session.mark_committed()

    # Re-verify descriptors against the committed release root.
    verified_data = tuple(
        describe_file(
            confine_path(release_root, item.relative_path),
            root=release_root,
            row_count=item.row_count,
            family=item.family,
            schema_id=item.schema_id,
            first_key=item.first_key,
            last_key=item.last_key,
            shard_id=item.shard_id,
            metadata=dict(item.metadata),
        )
        for item in data_descriptors
    )
    for verified, original in zip(verified_data, data_descriptors):
        if (
            verified.sha256 != original.sha256
            or verified.size_bytes != original.size_bytes
        ):
            raise ArtifactIntegrityError(
                f"committed shard digest drifted: {verified.relative_path}"
            )
    if index_descriptor is not None and index_relative is not None:
        index_descriptor = describe_file(
            confine_path(release_root, index_relative),
            root=release_root,
            row_count=index_descriptor.row_count,
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=COMPACT_INDEX_SCHEMA_VERSION,
        )

    return ShardWriteResult(
        data_descriptors=verified_data,
        compact_index_rows=tuple(compact_index),
        compact_index_descriptor=index_descriptor,
        total_rows=len(ordered),
        config=selected,
    )


def write_pointer_cells(
    pointers: Sequence[Any],
    *,
    max_pointers: int = MAX_POINTERS_PER_ROW,
) -> tuple[tuple[Any, ...], ...]:
    """Split *pointers* into ≤4,096-pointer cells (schema helper re-export)."""

    validate_physical_pointer_count(
        min(len(pointers), max_pointers) if pointers else 0,
        maximum=max_pointers,
    )
    return chunk_pointers(pointers, max_pointers=max_pointers)


# ---------------------------------------------------------------------------
# Deterministic fixture helpers
# ---------------------------------------------------------------------------


def build_fixture_rows(
    count: int,
    *,
    key_prefix: str = "entry",
    start_index: int = 0,
) -> tuple[dict[str, Any], ...]:
    """Build a deterministic sequence of minimal retrieval fixture rows."""

    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
    ):
        raise HfGraphragArtifactError("count must be a non-negative integer")
    rows: list[dict[str, Any]] = []
    for offset in range(count):
        index = start_index + offset
        entry = f"{key_prefix}-{index:06d}"
        rows.append(
            {
                "document_index": index,
                "entry_cid": entry,
                "score": float(count - offset),
                "text": f"fixture text {index}",
            }
        )
    return tuple(rows)


def write_fixture_release(
    root: str | Path,
    *,
    row_count: int = 5,
    max_rows_per_shard: int = 2,
) -> dict[str, Any]:
    """Write a tiny deterministic fixture tree and return its logical summary.

    The summary is free of absolute paths and wall-clock timestamps so two
    builds of the same inputs compare equal after canonical JSON encoding.
    """

    selected = ArtifactWriterConfig(max_rows_per_shard=max_rows_per_shard)
    rows = build_fixture_rows(row_count)
    # Intentionally reverse input order to prove stable sort/tie-breakers.
    shuffled = tuple(reversed(rows))
    result = write_bounded_shards(
        shuffled,
        root=root,
        data_dir="data/corpus",
        index_path="indexes/corpus_chunks.parquet",
        family=ArtifactFamily.CORPUS,
        primary_keys=("document_index",),
        tie_breakers=("entry_cid",),
        key_fields=("entry_cid",),
        config=selected,
        sort=True,
    )
    summary = {
        "bounds": physical_bounds_policy(),
        "config": selected.to_dict(),
        "fixture_schema_version": ARTIFACT_WRITER_SCHEMA_VERSION,
        "result": {
            "compact_index": (
                result.compact_index_descriptor.to_dict()
                if result.compact_index_descriptor is not None
                else None
            ),
            "compact_index_rows": [
                {
                    "first_key": row.first_key,
                    "last_key": row.last_key,
                    "relative_path": row.relative_path,
                    "row_count": row.row_count,
                    "shard_id": row.shard_id,
                }
                for row in result.compact_index_rows
            ],
            "data_shards": [
                {
                    "first_key": item.first_key,
                    "last_key": item.last_key,
                    "relative_path": item.relative_path,
                    "row_count": item.row_count,
                    "sha256": item.sha256,
                    "shard_id": item.shard_id,
                    "size_bytes": item.size_bytes,
                }
                for item in result.data_descriptors
            ],
            "total_rows": result.total_rows,
        },
        "rows": list(rows),
    }
    atomic_write_canonical_json(
        confine_path(root, "fixture_summary.json"),
        summary,
    )
    return summary


__all__ = [
    "ARTIFACT_WRITER_SCHEMA_VERSION",
    "ArtifactDescriptor",
    "ArtifactFamily",
    "ArtifactIntegrityError",
    "ArtifactStagingError",
    "ArtifactWriterConfig",
    "CompactIndexRow",
    "HfGraphragArtifactError",
    "ShardWriteResult",
    "StagingSession",
    "atomic_staging",
    "atomic_write_bytes",
    "atomic_write_canonical_json",
    "build_fixture_rows",
    "chunk_pointers",
    "confine_path",
    "describe_file",
    "file_digest",
    "manifest_descriptor",
    "physical_bounds_policy",
    "resolve_release_root",
    "shard_sequence",
    "stable_sort_rows",
    "validate_zstd_parquet",
    "verify_descriptor",
    "write_bounded_shards",
    "write_fixture_release",
    "write_pointer_cells",
    "write_zstd_parquet",
]
